# Extending a `LifetimeUpdate` when an upgrade arrives

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000` for everything cited here. Read from the repo's own `game.dat`
(11,346,944 bytes).

**Verdict up front: there is no timer to extend.** `LifetimeUpdate` does not count down. It
computes one absolute death frame in its constructor, asks the engine to wake it on that frame, and
sleeps until then — `update()` never looks at the clock and never reads its own `m_dieFrame`. So
"push the death back by N ms" is **one add**, and the whole cost of the patch is *noticing when to
do it*: nothing in the engine tells a module that an upgrade arrived.

- **Cost:** 5 patch sites (one a `push` immediate, one a single opcode byte), two new INI fields
  on `LifetimeUpdate`, and the room in `ModuleData` for them. No relocation of anything shared, no
  name table, no `.apt`, no `.csf`, and no client-side edit.
- **Risk:** *low*. Every hook is inside `LifetimeUpdate.cpp`'s own three functions plus its private
  factory thunk, and the field table has exactly one reference. The one real cost is behavioural,
  not structural: an object carrying the field **wakes every frame for its whole lifetime**
  instead of sleeping to its death frame, because that is the only way to see an upgrade arrive.
- **Status:** **built** as two of `lifetime-fields`'s three keywords
  ([`patches/lifetime_fields.py`](../patches/lifetime_fields.py)), applying and verifying against
  the repo's own `game.dat`. **Runtime-verified in game.** The third keyword is
  [`lifetime-transform.md`](lifetime-transform.md), and it shares this patch's sites 1 and 2 - so
  the `ModuleData` size and the rebuilt table are that document's, not this one's.

```
Behavior = LifetimeUpdate ModuleTag_Life
  MaxLifetime          = 30000   ; the stock 30s
  ExtendedByUpgrades   = Upgrade_SomethingRefreshing
  UpgradeLifetimeBonus = 5000    ; +5s each time that upgrade arrives
End
```

## 1. What the module actually is

`LifetimeUpdate.cpp` sits at `0x007a7d40`–`0x007a8050` (the source path string is in the vtable
tail at `0x00c317e0`: `…\GameLogic\Object\Update\LifetimeUpdate.cpp`).

| address | what |
|---|---|
| `0x007a7d7e` | `setLifetimeRange(min, max)` — rolls the duration, stores the death frame, **returns the sleep** |
| `0x007a7e0b` | `LifetimeUpdateModuleData` ctor (`sizeof` `0x18`, five fields) |
| `0x007a7e00` | `buildFieldParse`'s `push 0x00c31860` — **the only reference to the field table** |
| `0x007a7e41` | `setLifetimeRangeAndWake(min, max)` — the above plus `setWakeFrame` |
| `0x007a7e60` | `startLifetime()` — re-arms from the module data (used by `WaitForWakeUp`) |
| `0x007a7e88` | `xfer` — saves `+0x20` and `+0x24`, and `+0x28` at version ≥ 2 |
| `0x007a7ee6` | `LifetimeUpdate` ctor (`sizeof` `0x2c`) |
| `0x007a7f8b` | **`update()`** — vtable `0x00c317a0` slot 0, i.e. `this` = module `+0x10` |
| `0x0064e053` | `newModule` — `push 0x2c` / `operator new` / ctor |
| `0x0064e08b` | `newModuleData` — `push 0x18` / `operator new` / ctor |

Instance layout, from the ctor and the xfer:

```
LifetimeUpdate  +0x04  ModuleData*          (update() reads it as [this-0x0c])
                +0x08  Object*              (               and [this-0x08])
                +0x14  next wake frame      (UpdateModule's, xfer'd at 0x00850c84)
                +0x20  m_dieFrame           absolute frame
                +0x24  m_startFrame         the frame the lifetime was rolled
                +0x28  Bool                 the WaitForWakeUp latch
                +0x29  ---                  tail padding, inside sizeof 0x2c
                sizeof = 0x2c
```

The arming path, at `0x007a7da0`:

```
007a7da0  mov ecx, [0x00de412c]     ; TheGameLogic
007a7da6  mov ecx, [ecx+0x40]       ; now
007a7da9  mov [esi+0x24], ecx       ; m_startFrame = now
007a7dac  add ecx, eax              ; eax = max(1, GameLogicRandomValue(Min, Max))
007a7dae  mov [esi+0x20], ecx       ; m_dieFrame  = now + duration
007a7db1  pop esi
007a7db2  ret 8                     ; eax (the duration) is the caller's sleep
```

Both callers immediately do `push eax / push [esi+8] / call 0x00850c32`, and `setWakeFrame`
(`0x00850c32`) is `frame = TheGameLogic->frame + delta` — so the returned value is an
`UpdateSleepTime` **delta**, not a frame. `setLifetimeRange` has exactly **two** callers
(`0x007a7e4c`, `0x007a7f6a`), so it is the single funnel every arming path goes through; the five
sites that set a lifetime from outside (`0x005f1bfa`, `0x00873cc5`, `0x00876231`, `0x008c58e3`, and
`startLifetime` at `0x007a7e69`) all reach it.

`update()` is therefore called **once, on the death frame**, and consists of:

```
007a7f97  push 0x9a                 ; model condition 154 = THROWN_PROJECTILE
007a7f9e  call 0x0046e918           ; Object::testModelCondition (the 19-dword bitset at Object+0x10c)
007a7fa5  je   0x007a7faf
007a7fa7  eax = 1                   ;   -> in flight: come back next frame, do not kill
007a7faa  jmp  0x007a8038
007a7faf  cmp byte [ebx+0x11], 0    ; ScoreKill
   …      the two scoring arms …
007a8026  push [ebx+0x14]           ; DeathType
007a802b  push 8 / call 0x00698ec3  ; kill
007a8032  mov eax, 0x3fffffff       ; sleep forever
```

**The engine already ships a "come back next frame" arm in this exact function** — a thrown object
re-sleeps one frame at a time until it lands. That is the idiom the poll below reuses, and the
proof that a returned `1` means what the patch needs it to mean.

## 2. What "every time the upgrade fires" can mean

**An upgrade already held cannot be granted again**: granting sets a bit that is already set, and
nothing anywhere records a second grant. So the only edge that exists is the mask going **empty →
non-empty**, and that is what the patch triggers on:

| frame | mask | what happens |
|---|---|---|
| 10 | — | nothing |
| 40 | held | **+5000 ms**, and the latch is set |
| 70 | held | nothing — the same grant, not a new one |
| 100 | — | the latch clears, re-arming the trigger |
| 130 | held | **+5000 ms** again |

Consequences worth stating plainly, because they decide whether the field does what a mod wants:

- **A permanent player-scoped upgrade fires once per object.** Nothing ever clears it, so nothing
  re-arms. That includes an object created *while it is already held*, which fires on that object's
  first poll — which is exactly what makes "this research makes every summon last 5 s longer" work.
- **An object-scoped upgrade re-arms whenever something removes it**, so a spell that grants and
  later strips an upgrade can pay the bonus repeatedly.
- **Seeing the edge at all is what costs money.** The engine has no "an upgrade arrived" hook a
  non-upgrade module can subscribe to, so the module has to look. That is the per-frame poll, and
  it is the entire reason the arming hook exists.

## 3. The upgrade test is already written, three times

An upgrade is held either by the **object** (`Object+0x28C`, completed, object-scoped) or by its
**controlling player** (`Player+0x14C`, completed, player-scoped). Both are 36-dword bitsets indexed
by the engine's upgrade id — pinned live, with an effect rather than an inference, in
[`live-object-model.md`](live-object-model.md) §3a.

There is one mask on the object and two on the player, and they are easy to swap — `0x008b901a` and
`0x008badfe` both `lea` the object mask off the pointer they then hand to `getControllingPlayer`,
which is itself `mov ecx,[this+0x31c] / jmp Team::getControllingPlayer`, so `Object+0x31c` is
`m_team` and the object's mask is the one that ends just before it.
[`upgrade-mask-limit.md`](upgrade-mask-limit.md) carried these two owners the other way round until
this patch; its ceiling and everything derived from it were unaffected, and it now agrees.

The helpers, all `__thiscall` on the mask:

| address | signature |
|---|---|
| `0x00444dce` | `UpgradeMaskType::any()` → `al`, no args (36-dword non-zero scan) |
| `0x008097d6` | `testForAny(const UpgradeMaskType&)` → `al`, `ret 4` |
| `0x006aacb3` | `testForAll(const UpgradeMaskType&)` → `al`, `ret 4` |
| `0x0066f603` | `INI::parseUpgradeMask` — the field-table parse function `TriggeredBy` uses |
| `0x0068b678` | `Object::getControllingPlayer()` → `eax` (NULL for an unowned object) |

And the two-mask idiom, verbatim, from `UpgradeMux`'s conflict test at `0x008b8fe0`:

```
008b901a  lea  ecx, [edi+0x28c]     ; edi = the Object
008b9020  call 0x008097d6           ; testForAny(mask)
008b9027  jne  …                    ; held
008b902d  mov  ecx, edi
008b902f  call 0x0068b678           ; getControllingPlayer
008b903b  lea  ecx, [eax+0x14c]
008b9041  call 0x008097d6
```

Two calls, no union built. `testUpgradeConditions` (`0x008b8329`) picks between `testForAny` and
`testForAll` on the mux's own `RequiresAllTriggers`, so an `…RequiresAll` companion keyword later is
a one-call swap — the first cut is **any-of**, matching a bare `TriggeredBy`.

## 4. Milliseconds are free

The bonus is authored in **milliseconds** and stored in **frames**, and the patch converts nothing,
because the appended row names the engine's own duration parser — `0x0073a429`, the one
`MinLifetime` and `MaxLifetime` already use:

```
0073a429  … scanInt …
0073a445  fild  [ebp-4]                ; the INI value
0073a450  fmul  [0x00d9f610]           ; ms -> frames
0073a45b  call  [0xbd0588] / ftol
0073a46b  mov   [ecx], eax
```

`0x00d9f610` is not a constant: it is written at `0x00644f11` as `rate * 0.001`, from the live logic
frame rate (`[0x00d9f614] = 1000 / rate` is set two instructions later, and the static initialisers
in that block — `0.005`, `200.0`, `5.0`, `0.2` — are simply a placeholder pair for `rate = 5`). So
the stored value is already on the clock `m_dieFrame` counts, at whatever rate the build runs, and
the extension is a plain `add`. Authoring `UpgradeLifetimeBonus = 5000` beside
`MaxLifetime = 30000` means what it looks like it means.

## 5. The in-world timer follows for free

The clock drawn over a summoned object comes from `0x0092f778`, which returns
`{kind, _, fraction}` by value and finds its source by walking the object's modules **by class
name**:

```
0092f7c5  mov  edi, [ebp+0xc]        ; the Object
0092f7ce  call 0x0068bda5            ; findUpdateModule("LifetimeUpdate")
0092f7d9  cmp  byte [eax+0x28], 0    ; still WaitForWakeUp? -> no bar
0092f7dd  jne  0x0092f7ed
0092f7e2  mov  edx, [eax+0x24]       ; m_startFrame
0092f7e5  mov  ecx, [eax+0x20]       ; m_dieFrame
…
0092f8c8  cmp  ecx, edx / jbe        ; die <= start -> no bar
0092f8d0  mov  eax, [TheGameLogic]+0x40
0092f8da  sub  esi, eax              ; remaining = die - now
0092f8ee  sub  esi, edx              ; span      = die - start
0092f902  fdivp                      ; fraction  = remaining / span
0092f907  … clamp to [0,1], 0 once now > die
```

Both terms are read off the **live module every frame**, and nothing anywhere reads the template's
`MaxLifetime` to draw it. So pushing `m_dieFrame` out grows the numerator and the denominator by
the same amount: the bar jumps up when the bonus lands and then drains over the new, longer total.
Nothing client-side has to be patched. The `+0x28` guard is also why the patch's own latch went in
the byte *after* it — see §6.

> **This is also the reason a `LifetimeUpdate` cannot simply be *paused*.** Freezing the clock means
> holding `m_dieFrame` ahead of `now`, which freezes the numerator while the denominator keeps
> growing — so the bar would drain to nothing over an object that is not dying. A pause has to push
> `m_startFrame` along with the death frame to keep `die - start` constant, one extra
> `inc dword [ecx+0x14]`; an extension does not, because growing the span is the truth.

## 6. Where the fields go

The stock field table is at `0x00c31860` — five rows plus its terminator, boxed in by its own
keyword strings, and with **exactly one reference** (the `push` immediate at `0x007a7e01`). That is
the cheapest relocation in this package, alongside `science-prereqs` and
`large-group-bonus`: rebuild the table in the cave with two more rows and repoint one `push`.

`ModuleData` has no hole big enough (`+0x12`/`+0x13` is the only padding, two bytes), so it grows
past `0x18`: the mask at `+0x18`, the bonus at `+0xa8`, and whatever else the patch's other
keywords need behind them. That is one hook, because
`newModuleData` (`0x0064e08b`) is **LifetimeUpdate's own thunk** — it calls the ctor at `0x007a7e0b`
directly, and a full `call`/`jmp` scan of `.text` finds one caller for each and no absolute
reference to either outside the module-factory registration at `0x00658e2f`:

```
0064e096  56           push esi         ; 8 bytes, one jmp rel32 + 3 nops
0064e097  6a 18        push 0x18
0064e099  e8 ……        call 0x0042f6e0  ; operator new — does not zero
```

The cave replaces the size **and zeroes everything past `0x18`**, which is required rather than
tidy: for every `LifetimeUpdate` in the game that does *not* declare the keywords neither parser
ever runs, and the mask and the bonus would be whatever the allocator handed back. `operator new`
is the right place because the ctor runs after it and writes only its own five fields — so the ctor
keeps every store it had.

**The edge latch needs one byte of instance state**, and the instance has three going spare:
`sizeof` is `0x2c` and the `WaitForWakeUp` byte at `+0x28` is the last thing in it. The ctor zeroes
that byte with a *byte* store while `eax` is already zero, so widening that one store clears the
latch too — `88 46 28` → `89 46 28`, **one opcode byte**, and the two dword stores after it are
untouched. `wakeUp` (`0x007a7e6f`) and the xfer both write `+0x28` as a byte, so `+0x29` is the
patch's alone.

## 7. The recipe

Five sites, one cave section (`sage_patch.utils.allocate_section`).

| # | site | stock bytes | what |
|---|---|---|---|
| 1 | `0x0064e096` | `56 6a 18 e8 42 16 de ff` | `sizeof(ModuleData)` grown past `0x18`, and zero what it added |
| 2 | `0x007a7e00` | `68 60 18 c3 00` | `push` the rebuilt field table (in place, 5 for 5) |
| 3 | `0x007a7f04` | `88 46 28` | the ctor's byte store widened, so the latch defaults to "not held" |
| 4 | `0x007a7dae` | `89 4e 20 5e c2 08 00` | arm the poll: return a sleep of 1 when the mask is declared |
| 5 | `0x007a7f8b` | `55 8b ec 51 53` | the extension, at `update()`'s first instruction |

Site 5 is exactly five bytes of whole instructions (`push ebp / mov ebp,esp / push ecx / push ebx`),
and the hook is at the function's entry rather than at the kill, because the module pointer is only
live in `ecx` there — `update()` never spills it.

```asm
cave_alloc:                        ; site 1. entered in place of the size push and the allocation
    push esi                       ;   the register save the window owed its caller
    push <the grown sizeof>
    call 0x0042f6e0                ;   operator new — does not zero
    test eax, eax
    je   .done                     ;   `newModuleData` tests for null too; do not beat it to it
    push eax
    lea  edx, [eax+0x18]
    mov  ecx, <that many dwords>   ;   the mask, the bonus and the room behind them
    xor  eax, eax
.zero:
    mov  [edx], eax
    add  edx, 4
    dec  ecx
    jnz  .zero
    pop  eax
.done:
    jmp  0x0064e09e                ;   the `pop ecx` that cleans the size argument

cave_arm:                          ; site 4. esi = module, ecx = die frame, eax = duration
    mov  [esi+0x20], ecx           ;   the displaced store
    push eax
    mov  ecx, [esi+0x04]           ;   ModuleData
    add  ecx, 0x18                 ;   &ExtendedByUpgrades
    call 0x00444dce                ;   any()
    test al, al
    pop  eax
    je   .out
    mov  eax, 1                    ;   poll every frame: an edge is invisible from a long sleep
.out:
    pop  esi
    ret  8

cave_held:                         ; esi = Object, edi = the mask -> al
    push edi
    lea  ecx, [esi+0x28c]
    call 0x008097d6                ;   object-scoped
    test al, al
    jne  .yes
    mov  ecx, esi
    call 0x0068b678                ;   getControllingPlayer
    test eax, eax
    je   .no
    lea  ecx, [eax+0x14c]
    push edi
    call 0x008097d6                ;   player-scoped; its al is ours
    ret
.yes:
    mov  al, 1
    ret
.no:
    xor  al, al
    ret

cave_update:                       ; site 5. ecx = module+0x10, stack = [ret]
    push ebx
    push esi
    push edi
    mov  ebx, [ecx-0x0c]           ;   ModuleData
    mov  esi, [ecx-0x08]           ;   Object
    lea  edi, [ebx+0x18]           ;   &ExtendedByUpgrades
    push ecx
    mov  ecx, edi
    call 0x00444dce                ;   any()  -- absent on every stock object
    pop  ecx
    test al, al
    je   .stock
    push ecx
    call cave_held
    pop  ecx
    mov  dl, [ecx+0x19]            ;   held last poll?      (module+0x29)
    mov  [ecx+0x19], al            ;   ... and latch this one, held or not
    test al, al
    je   .due                      ;   not held -> re-armed, nothing paid
    test dl, dl
    jne  .due                      ;   same grant as last frame -> not an edge
    mov  edx, [ebx+0xa8]           ;   UpgradeLifetimeBonus, already in frames
    add  [ecx+0x10], edx           ;   m_dieFrame += it     (module+0x20)
.due:
    mov  eax, [0x00de412c]         ;   TheGameLogic
    mov  eax, [eax+0x40]           ;   now
    cmp  eax, [ecx+0x10]
    jae  .stock                    ;   due -> the stock kill
    pop  edi / pop esi / pop ebx
    mov  eax, 1                    ;   UPDATE_SLEEP(1)
    ret
.stock:
    pop  edi / pop esi / pop ebx
    push ebp                       ;   the displaced prologue
    mov  ebp, esp
    push ecx
    push ebx
    jmp  0x007a7f90
```

`mov eax, 1 / ret` is a legal early return from `update()`: the hook is at the entry, so the stack
is still the caller's, and the function takes no arguments (`0x007a803b` is a bare `ret`).

**Two orderings are load-bearing**, and neither would fault if reversed. The latch is **read before
it is written**, or the answer is always "held last frame too" and the bonus is paid exactly never.
And the bonus is **paid before the due check**, so an upgrade that arrives on the very frame the
object was going to die still saves it.

`edi` is pushed because the stock function pushes it *after* this hook returns (`0x007a7f93`) and
pops it on the way out — a dirty `edi` would be handed back to `update`'s caller rather than merely
clobbered.

**Cave budget, as built:** 40 (alloc) + 29 (arm) + 46 (held) + 106 (update) = **221 bytes** of
stubs, beside the rebuilt table and the keyword strings the patch's three keywords share. One
`0x1000` section covers the lot.

An object that does not declare the keyword pays one `any()` — 36 compares — once, on the frame it
dies. Everything else about it is byte-identical to stock, including its sleep.

## 8. Properties

- **Determinism.** This changes *when objects die*, which is logic-side state and is CRC'd. **Every
  peer must run the same patched binary**, and replays do not cross — the same rule as
  `multi-execute-gate` and `foundation-rebind`, and stricter than the client-local patches.
- **The keywords are fatal on a stock build.** SAGE treats an unknown field in a known block as a
  parse error, so a mod using them cannot run without the patch — same as `terrain-resource-exp`
  and `queue-ignore-cp`.
- **Savegames need no version bump**, and the one thing not carried across a load is the edge
  latch: it is instance state the module's `xfer` does not know about, so a still-held upgrade
  reads as freshly gained on the first poll after a load and pays its bonus a second time. Bounded
  to one extension per load. Carrying it would mean bumping the module's xfer version from 2 to 3,
  which makes patched saves unreadable by anything that does not know about the field.
- **`WaitForWakeUp = Yes` is unaffected until it matters.** That path sleeps `0x3fffffff` without
  going through `setLifetimeRange` (`0x007a7f32`); when something wakes it, `startLifetime` funnels
  into the arming hook and the poll starts then. The UI shows no bar for such a module either, on
  the same `+0x28` byte.
- **Composition.** Order-independent: the cave is allocated past every section by
  `allocate_section` and found again by name. No bundled patch touches `LifetimeUpdate`, its field
  table, or the module-factory thunk at `0x0064e08b`, and none reads what this one writes.
- **`sagepatch` surface.** `FieldDelta("LifetimeUpdate", mask, "Ref[]:upgrades", None, …)` and
  `FieldDelta("LifetimeUpdate", bonus, "Int", 0, …)`. `Ref[]:` is new: the `.sagepatch` grammar
  could spell a single cross-reference and a list of scalars but not a list of references, which is
  what every upgrade mask in the model already is (`TriggeredBy: List[Upgrade]`). Four lines in
  [`sage_ini/engine.py`](../../sage_ini/engine.py), mirroring the `Enum` / `Enum[]` pair that was
  already there.
- **CLI.** `--keyword NAME` (default `ExtendedByUpgrades`) and `--bonus-keyword NAME` (default
  `UpgradeLifetimeBonus`), each validated against the five stock keywords and against each other
  the way `terrain-resource-exp` validates its one.

## 9. Open questions and what needs a live test

- **The per-frame wake is the whole risk**, and it is opt-in rather than universal. The shipped
  RotWK data declares `LifetimeUpdate` **1722 times across 408 files** (median `MaxLifetime`
  **29 s**, p90 116 s, 251 of them ≤ 5 s — the FX and debris end), and **every one of those keeps
  its stock sleep**: the poll is armed by the new keyword and nothing else. So the bill is whatever
  a mod actually annotates, times however many of those are alive at once — a swarm summon with 60
  members annotated costs 60 module updates a frame, each ~110 mask words plus a
  `getControllingPlayer`. That has not been measured in a running game. If it ever matters, the
  poll interval is a one-immediate change in `cave_arm` (sleep `N` instead of `1`) at the cost of
  the bonus landing up to `N-1` frames late, which is invisible unless the object was about to die
  inside that window.
- **The default keywords collide with nothing.** Neither `ExtendedByUpgrades` nor
  `UpgradeLifetimeBonus` appears anywhere in the shipped tree, which matters because an unknown
  field in a known block is a parse error rather than a warning: a mod adopting the defaults is
  adding names, not shadowing them.
- **~~Is `update()` ever called off-schedule?~~ Settled** — this was the design's one load-bearing
  assumption, and the driver states it in nine instructions at `0x0062ea97`:

  ```
  0062ea97  lea  ecx, [module+0x10]        ; the interface subobject the hook inherits as `this`
  0062ea9a  mov  eax, [ecx] / call [eax]   ; update()
  0062ea9e  cmp  eax, 1 / jge / mov 1      ; the return is a sleep, clamped up to 1
  0062eab4  mov  eax, [TheGameLogic]+0x40  ; ... and the next wake is recomputed from *now*
  0062eabf  add  eax, ecx                  ;     rather than from the frame that was asked for
  0062eacb  mov  [module+0x14], eax
  ```

  So a sleep of 1 is every frame, and a late call cannot accumulate error: the reschedule is
  relative to when the call actually happened. The patch anchors this window, because nothing in
  `LifetimeUpdate` itself would catch a build that changed it.
- **~~Does the in-world timer follow?~~ Settled**, in §5, and anchored: the widget recomputes both
  of its terms from the live module every frame. What has *not* been established is whether any
  mod's own HUD reads the death frame some other way.
- **The two-frame edges.** Arming happens with a sleep of 1, so both the trigger and the death land
  within a frame of the truth. `MinLifetime`/`MaxLifetime` of 0 rolls to a duration of 1
  (`0x007a7d98` clamps), and such an object still gets one poll before it dies.

## 10. Verification notes

Read directly from `game.dat` and reproducible from the addresses above: the field table at
`0x00c31860` (five rows, offsets `0x8`/`0xc`/`0x10`/`0x11`/`0x14`) and its single reference; the two
allocation sizes and their ctors, each with exactly one caller; the instance layout and the xfer
that saves it; the two callers of `setLifetimeRange` and the five of `setLifetimeRangeAndWake` (a
full `call`/`jmp` rel32 scan of `.text`); `setWakeFrame`'s delta arithmetic; the duration parser and
the frame-rate scalar it multiplies by, including the site that writes that scalar; the
`THROWN_PROJECTILE` gate, resolved through the model-condition name table
(`sage_patch.patches.utils.model_conditions`, 591 names at `Object+0x10c`) — **not** the `KindOf`
table, which resolves index 154 to a plausible-looking `NOT_SELLABLE` and is the wrong table; the
mask helpers and the two-mask idiom at `0x008b8fe0`; the sleepy-update driver at `0x0062ea97`; and
the timer widget at `0x0092f778`, its three module sources and its fraction.

Every site and every anchor above is asserted against the real `game.dat` by
[`tests/sage_patch/test_lifetime_fields.py`](../../tests/sage_patch/test_lifetime_fields.py)
(`TestInstalledBinary`, skipped where the binary is absent), and the four cave stubs are
disassembled back and checked instruction by instruction against what this document says they do —
including both load-bearing orderings.

The data figures in §9 are counted over the mounted RotWK tree
(`data/ini`, 408 files declaring the module), not estimated.

Not established: whether any mod's HUD reads the death frame some other way, and the runtime cost
of the poll under load — the patch is runtime-verified, but neither of those was measured.
