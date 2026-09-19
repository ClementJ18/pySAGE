# A building under construction starts with health

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR), recovered
**statically** on 2026-09-17 from the stock `game.dat` in this repo's fixtures with `pefile` +
`capstone`. **None of it is runtime-verified** — see §7 for what a session would have to watch.

- **Goal:** a structure whose foundation has just been placed should not stand at one hit point
  while its builder walks over. It starts at a configurable percentage of its maximum health
  instead, and the rest of the construction health curve is re-mapped so the change is a
  durability change and nothing else.
- **Status: implemented as `construction-initial-health`**
  ([`../patches/construction_initial_health.py`](../patches/construction_initial_health.py)),
  applying and verifying against the real `game.dat` and composing in either order with
  `production-split` — which needed its `DozerAIUpdate` anchor split; §6.

## TL;DR

- **Construction health is one number in two directions.** Forwards, a per-frame amount is added
  to the body; backwards, the construction percent is recovered by multiplying the body's health
  ratio by 100. A patch that moves the floor has to move both, or the progress bar stops meaning
  what the health means.
- **Eight sites, and that is all of them.** Four set the starting health, two advance it, two
  recover the percent from it. Each was found by scanning `.text` for a byte signature rather than
  by following call graphs, so the count is a closed set rather than "the ones I happened to
  find": §2 gives the signature and the scan.
- **The starting health is a literal `1.0f`**, read from `FLOAT_ONE` at `0x00BD1908` — the same
  constant the modifier system uses for "no modifier". There is no INI field anywhere on the path.
- `--percent 0` reproduces stock, because the three transforms are `max(1.0, f·max)`, `×(1-f)` and
  `(r-f)/(1-f)`, all of which are the identity at `f = 0`.

## 1. What the engine does today

### 1.1 Health starts at one point

A structure that is about to be built has its health driven to exactly one hit point. The
sequence, at `0x008AD877` (the builder dropping a foundation):

```
008ad866  8b8e5c020000   mov   ecx, [esi+0x25c]      ; the structure's BodyModule
008ad86c  0f57c0         xorps xmm0, xmm0
008ad86f  f30f1186...    movss [esi+0x288], xmm0     ; constructionPercent = 0
008ad877  8b19           mov   ebx, [ecx]            ; the body's vtable
008ad879  6a00           push  0                     ; arg 2: DamageInfo = NULL
008ad87b  894d18         mov   [ebp+0x18], ecx
008ad87e  ff5310         call  [ebx+0x10]            ; getHealth()        -> st(0)
008ad881  d82d0819bd00   fsubr [0xbd1908]            ; st(0) = 1.0 - health
008ad887  51             push  ecx                   ; reserve the float slot
008ad888  8b4d18         mov   ecx, [ebp+0x18]
008ad88b  d91c24         fstp  [esp]                 ; arg 1: the delta
008ad88e  ff9384000000   call  [ebx+0x84]            ; internalChangeHealth(delta, NULL)
008ad894  6a43           push  0x43                  ; AWAITING_CONSTRUCTION
008ad8a2  6a45 / 6a44    push  0x45 / push 0x44      ; clear ACTIVELY_BEING / PARTIALLY_
008ad8b5  e8ad4ce3ff     call  0x68d607              ; setModelConditionState(set, clear)
```

`internalChangeHealth` is body vtable `+0x84`, `__thiscall`, `ret 8`, already recorded as
[`ACTIVE_BODY_INTERNAL_CHANGE_HEALTH`](../addresses.py). Adding `1.0 - health` leaves the body at
exactly `1.0` whatever it started at, which is why the constant is `FLOAT_ONE` and not a field.

Three body getters are used by the construction arithmetic, all `__thiscall`, all taking no
argument and returning in `st(0)`:

| slot | what |
|---|---|
| `+0x10` | `getHealth` |
| `+0x14` | `getHealthRatio` — health over maximum, so `[0, 1]` |
| `+0x1C` | `getMaxHealth` |

The `push 0` that precedes `call [ebx+0x10]` is not that call's argument — it is
`internalChangeHealth`'s second, pushed early by the compiler. `0x00857FC1` calls `+0x1C` with no
push at all, which is what settles it.

### 1.2 Health advances two ways

**With a builder**, inside the `DozerAIUpdate` build state machine — the same block
[`construction-speed-modifiers.md`](construction-speed-modifiers.md) §3.2 anatomises, one
instruction past the `calcTimeToBuild` call it hooks:

```
0088dea1  8b31           mov   esi, [ecx]            ; the body's vtable (ecx = the body)
0088dea3  6a00           push  0                     ; DamageInfo = NULL
0088dea5  894df0         mov   [ebp-0x10], ecx
0088dea8  ff561c         call  [esi+0x1c]            ; getMaxHealth()
0088deab  d875e4         fdiv  [ebp-0x1c]            ; / frames
0088deae  51             push  ecx
0088deaf  8b4df0         mov   ecx, [ebp-0x10]
0088deb2  d91c24         fstp  [esp]
0088deb5  ff9684000000   call  [esi+0x84]            ; internalChangeHealth(maxHealth/frames)
```

`[ebp-0x1c]` is the frame count `calcTimeToBuild` returned, converted at `0x0088DE80` — the same
one `100 / frames` is computed from four instructions above, which is what keeps the health ramp
and the percent ramp in step.

**Without one**, `GettingBuiltBehavior::update` (`0x00857E77`) heals the structure itself:

```
00857faf  8b9f5c020000   mov   ebx, [edi+0x25c]      ; the body
00857fb7  0f84da000000   je    0x858097              ; no body: nothing to do
00857fbd  8b03           mov   eax, [ebx]
00857fbf  8bcb           mov   ecx, ebx
00857fc1  ff501c         call  [eax+0x1c]            ; getMaxHealth()   -> st(0)
00857fc4  db461c         fild  [esi+0x1c]            ; RebuildTimeSeconds as frames
00857fce  d8059886bd00   fadd  [0xbd8698]            ; the unsigned fixup
00857fd4  def9           fdivp st(1)                 ; st(0) = maxHealth / frames
00857fe0  d95df0         fstp  [ebp-0x10]            ; the per-frame amount
0085806f  e81085e3ff     call  0x690584              ; apply it
```

This arm is reached only when nothing else is building the structure: `[ebp-2]`, set at
`0x00857F1D` when the object's producer (`Object+0x7C`) exists and is not itself, sends the update
to `0x008580A1` and skips the whole block. So a builder-built structure never takes it, and the
two ramps never both run.

### 1.3 And the percent is recovered back out of the health

Two sites run the relation backwards:

```
008567f8  8b8f5c020000   mov   ecx, [edi+0x25c]
008567fe  8b01           mov   eax, [ecx]
00856800  ff5014         call  [eax+0x14]            ; getHealthRatio()
00856803  d80dd888bd00   fmul  [0xbd88d8]            ; * 100.0
00856809  d99f88020000   fstp  [edi+0x288]           ; constructionPercent
```

`0x00856800` is `GettingBuiltBehavior` resynchronising when neither of its two in-progress flags
(`module+0x15`, `module+0x16`) is set; `0x00858078` is the self-build update, one instruction after
the heal above. Both are byte-identical nine-byte windows.

This is the fact that makes a half-patch wrong. Raise the starting health and leave these alone,
and a self-building structure reports `f × 100` percent complete the frame it is placed — it
finishes a tenth early. The durability change would have smuggled in a build-speed change.

## 2. Finding all of them, rather than some of them

Four sites is a claim, so it was made falsifiable. `fsubr [FLOAT_ONE]` is six bytes
(`d82d0819bd00`); scanning `.text` for it gives 36 hits, and filtering to the ones preceded by
`call [reg+0x10]` and followed by `call [reg+0x84]` gives exactly four:

| call VA | where | what marks it as construction |
|---|---|---|
| `0x0079541F` | `BuildAssistant`'s placement | `[esi+0x288] = 0` at `0x0079546F`, then `ObjectStatus` 2 (`UNDER_CONSTRUCTION`) at `0x0079547C` |
| `0x00858975` | `GettingBuiltBehavior`'s rebuild | `[esi+0x288] = 0` at `0x00858924`, `AWAITING_CONSTRUCTION` at `0x00858943` |
| `0x0088D59E` | a `DozerAIUpdate` helper that restarts a build | `UNDER_CONSTRUCTION` mask built at `0x0088D5F9`, applied at `0x0088D616` |
| `0x008AD88E` | the builder placing a foundation | `[esi+0x288] = 0` at `0x008AD86F`, `AWAITING_CONSTRUCTION` at `0x008AD894` |

The percent derivations were closed the same way: `fmul [0x00BD88D8]` has 40 hits in `.text`, five
of them preceded by `call [reg+0x14]`, and only two of those store to `Object+0x288`
(`d99f88020000`) — `0x00856803` and `0x0085807B`. The other three multiply a ratio by 100 for
something else.

A fifth `fsubr [FLOAT_ONE]` after a `getHealth`, at `0x008C4ABD`, is a small standalone function
that compares rather than writes; it is not on this path.

## 3. The design

Let `f` be the fraction. Three transforms, which together make health a linear function of build
progress from `f` to `1`:

| site | stock | patched |
|---|---|---|
| the four starts | `health = 1.0` | `health = max(1.0, f · maxHealth)` |
| the two ramps | `+ maxHealth / frames` | `+ (1 - f) · maxHealth / frames` |
| the two derivations | `percent = ratio · 100` | `percent = max(0, (ratio - f) / (1 - f)) · 100` |

So `health(p) = f + (1-f)·p` and `progress(r) = (r - f)/(1 - f)`, which are inverses. At `f = 0`
all three are the identity, which is what makes `--percent 0` stock rather than a second
behaviour.

**The `max(1.0, …)` floor** keeps the guarantee the stock constant carried: a structure whose
maximum health is under ten points would otherwise start below one hit point at 10%.

**The `max(0, …)` clamp** is not defensive. Stock could never produce a negative percent because
its floor was a single point; with a floor at a fraction of maximum, a structure damaged below its
starting health during construction has `ratio < f`, and the unclamped expression is negative.

**The ceiling is 90%**, because the derivations divide by `1 - f`: at 100 that is a division by
zero, and near it a rounding difference in the health ratio becomes a visible jump in the bar.

## 4. The caves

One `.cstart` section, five float constants (`f`, `1.0`, `1-f`, `1/(1-f)`, `100.0`) laid out ahead
of four routines. Every hook is a five-byte `call` plus `nop` padding to the length of what it
displaced, so nothing shifts.

**`initial`** replaces `call [vtable+0x84]` at the four starts. It does not call
`internalChangeHealth` itself — it **rewrites the argument the caller already pushed** and tail-
jumps to the real slot, so the callee's own `ret 8` still cleans the stack and the hook's `call`
returns normally. The wanted delta is `target - health`, and the caller computed `1.0 - health`,
so the edit is `delta + target - 1.0`:

```
    push  ecx                   ; a thiscall callee may clobber it
    sub   esp, 4
    mov   eax, [ecx]
    call  [eax+0x1c]            ; getMaxHealth -> st(0)
    fstp  [esp]
    movss xmm0, [esp]
    mulss xmm0, [f]
    movss xmm1, [1.0]
    maxss xmm0, xmm1            ; target
    subss xmm0, xmm1            ; target - 1.0
    addss xmm0, [esp+0xc]       ; + the stock delta
    movss [esp+0xc], xmm0
    add   esp, 4
    pop   ecx
    mov   eax, [ecx]
    jmp   [eax+0x84]
```

Rewriting the argument rather than recomputing it is what lets **one** routine serve all four
sites, which differ in which register holds the vtable and where `ecx` was stashed.

**`ramp`** replaces `call [esi+0x1c]` + `fdiv [ebp-0x1c]` — six bytes — and reproduces both, with
the scale between them. It reads `[ebp-0x1c]` because the cave never sets up a frame of its own,
so `ebp` is still the caller's.

**`selfbuild`** replaces `call [eax+0x1c]` + `fild [esi+0x1c]` and has to leave the x87 stack the
way that pair left it — frames on top, scaled maximum beneath — because the caller's `fdivp st(1)`
two instructions later divides one by the other. `esi` survives the call for the same reason the
stock `fild` assumed it would.

**`percent`** replaces `call [vtable+0x14]` + `fmul [100.0]` — nine bytes — does the arithmetic in
SSE and hands the result back on the x87 stack, because the site's next instruction is
`fstp [Object+0x288]`.

All four are branch-free: both clamps are `maxss`.

## 5. What this does not do

It is a **starting** health, not a floor. A structure under construction can still be damaged
below `f` — the clamp in `percent` exists precisely because it can — and a builder interrupted
early still leaves something cheap to finish off. What stops being possible is killing a building
nobody has yet had the chance to defend.

It is also not a `GameData.ini` or per-object setting: the fraction is baked into the binary at
apply time. Every structure in every faction gets the same one. Making it per-object would mean a
new `ActiveBody` or `GettingBuiltBehavior` field and a read on each of the eight sites, which is a
much larger patch than the balance question seems to justify.

## 6. Composition

`production-split` hooks `calcTimeToBuild` at `0x0088DE6D`, twenty-seven bytes above this patch's
ramp step, and its anchor over that function ran to `0x0088DEB6` — across the six bytes at
`0x0088DEA8`. The anchor is now **split in two**, `0x0088DE43` (101 bytes) and `0x0088DEAE`
(9 bytes), around exactly the bytes this patch owns. Everything that patch depends on is still
pinned: the percent accumulate, its own hooked call, the frame count landing in `[ebp-0x1C]` and,
after the gap, that the health step's divisor is that same local.

Neither derives its output from bytes the other writes. This patch's ramp does read `[ebp-0x1C]`
at run time — the frame count `production-split` may have scaled by a `PRODUCTION_CONSTRUCTION`
modifier — and that is the point: the health curve stretches and shrinks with the percent curve
rather than drifting out of step with it. The two apply in either order; the tests assert the byte
sets are disjoint in both directions.

No other bundled patch touches any of the eight sites.

**Logic-side.** Health is world state, xfer'd into saves and replays and folded into the frame
CRC. A lobby where one peer has this patch and another does not desyncs on the first foundation.

## 7. What is still unknown

Everything here is static. In particular:

1. **Which of the four start sites actually fires** for a given faction's builder has not been
   observed. All four are patched because all four mean the same thing, but a session watching
   `Object+0x288` and the body's health through one build would say which path a RotWK skirmish
   takes — and whether `0x0088D59E` is the build-restart it reads as.
2. **Whether `GettingBuiltBehavior`'s self-build arm is reachable at all in RotWK** with a builder
   present. §1.2's reading of `[ebp-2]` says no; a structure with no `WorkerName` would settle it.
3. **The build-up animation.** The drawable copies `Object+0x288` at `0x004B51FD` to raise the
   model out of the ground. With the derivations re-mapped the percent is unchanged for a given
   build progress, so the animation should be unchanged — but that is an inference from §1.3, not
   an observation.
4. **`0x0088D5xx`'s drawable field.** `0x0088D3E7` writes `0.4f` to `drawable+0xB0` at construction
   start and `0x0088D663` writes `1.0f` to it in the restart helper. Neither is health and neither
   is touched; what the field is stays a black box.

A session that would settle 1–3: place a structure, `sage_live watch` the object's health and
`+0x288` for the walk and the build, and check that health reaches maximum on the same frame the
model condition flips to `CONSTRUCTION_COMPLETE`.
