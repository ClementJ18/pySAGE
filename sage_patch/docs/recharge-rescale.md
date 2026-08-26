# Making a cooldown respond to a modifier that arrives after the cast

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); file offset is
`VA - 0x400000` for everything cited here. Read **statically** on 2026-08-16 from the stock
`game.dat` in this repo (11,346,944 bytes) with `pefile` + `capstone`. **Nothing below has been
observed in a running game** - §9 is still entirely open.

**The complaint.** `SpecialAbilityUpdate::startPowerRecharge` computes the whole cooldown once, at
the moment the power fires, and stores an **absolute ready frame**. A recharge modifier that
arrives one frame later — a leadership aura, a temporary buff, the player finishing a
`SpellRechargeModifierUpgrade` — cannot touch the cooldown already running. It only pays off on the
*next* cast.

**Verdict up front: the engine already stores everything needed to fix this, and the fix needs no
new per-module state at all.** Alongside the ready frame the module keeps the **length of the
cooldown it started**, in frames, scaled by the multiplier that was in force at cast time. That
field is the missing record: dividing it by the template's `ReloadTime` recovers the baked-in
multiplier, so a per-frame sweep can tell — in integers, with no float comparison — whether the
multiplier the engine *would* compute now differs from the one already in the cooldown, and rescale
the remainder when it does.

- **Cost:** 1 `call rel32` swap + 412 bytes of cave. No structure grows, no `ModuleData` changes,
  no ctor/dtor changes, no INI surface, no `.sagepatch` entry.
- **Risk:** low-medium. The failure mode is a wrong cooldown length, not a crash; the one
  crash-shaped risk is the sweep itself walking a module list every frame.
- **Status: implemented as `recharge-rescale`**
  ([`../patches/experimental/recharge_rescale.py`](../patches/experimental/recharge_rescale.py)),
  and **experimental**: it applies to and verifies against the real `game.dat`, it composes in
  either order with `live-bridge`, `production-split` and `spawn-union`, and every address here
  holds its stock bytes in the installed binary - but it has never been in a running match. See
  [`../patches/experimental/`](../patches/experimental/) for what that promises and what it does
  not.

## TL;DR

- **Cooldowns are stored twice over.** `readyFrame` at interface `+0x08` and the **duration that
  produced it** at interface `+0x04`, both written by `startPowerRecharge` at `0x00896F70` /
  `0x00896F8B`, both `Xfer`'d. The second one exists to draw the button clock, and it is what makes
  this patch cheap.
- **`duration == ftol(ReloadTime * m)`, so `m` is recoverable.** Recompute the cast-time formula
  now, quantize it the same way, and compare the two **integers**. Equal means nothing changed —
  which is the answer on essentially every power on every frame, and therefore the patch's exit.
- **Rescaling the remainder is exactly a continuous rate.** `remaining' = remaining * m_new /
  m_old` tracks unscaled work implicitly, so a modifier held for part of a cooldown produces the
  same total as integrating a per-frame rate over that interval. "150% cooldown speed removes 1.5
  seconds per second" is what falls out, not what has to be approximated. §3.2 proves it.
- **The percent readout follows for free and does not jump.** `getPercentReady` is
  `1 - (readyFrame - now) / duration`, recomputed on every call; the patch scales numerator and
  denominator by the same factor, so the clock keeps its position and changes only its speed.
- **There is no per-frame tick to hook.** Most special-power modules are not update modules, and
  the ones that are sleep through their own cooldown. The driver is therefore a sweep over
  `TheGameLogic+0xAC`, once per logic frame, from one `call rel32` inside `GameLogic::update` —
  a different five bytes from the entry `live-bridge` takes.
- **Two things are deliberately left alone:** the *second* implementation of `startPowerRecharge`
  at `0x00991500` (3 module vtables of 26), which keeps no duration and so cannot say what
  multiplier it baked in, and `SharedSyncedTimer` powers, whose timer lives on the `Player`. §7.
- **This is simulation state.** Every peer needs the patched binary and replays will not cross.

## 1. Where a cooldown actually lives

### 1.1 One choke point, one layout

`SpecialAbilityUpdate::startPowerRecharge` — `0x00896E31`, `__thiscall`, `ret 4`, one `float`
argument — is the only thing that starts a cooldown, and its address sits in **23 module vtables**,
always at `SpecialPowerModuleInterface` slot `+0x3C`. It is an adjustor thunk on the interface
subobject at module `+0x10`: `ecx-0xC` is the `ModuleData`, `ecx-0x8` is the `Object`.

Everything this patch touches is in that subobject. The base constructor `0x008973EE` zeroes the
lot, module-relative:

```
00897430  c707f04fc600     mov  dword [edi], 0xc64ff0    ; edi = this+0x10, the interface vptr
00897436  895e14           mov  dword [esi + 0x14], ebx  ; interface +0x04
00897439  895e18           mov  dword [esi + 0x18], ebx  ; interface +0x08
0089743c  895e1c           mov  dword [esi + 0x1c], ebx  ; interface +0x0c
0089743f  895e20           mov  dword [esi + 0x20], ebx  ; interface +0x10
00897442  f30f114624       movss dword [esi + 0x24], xmm0; interface +0x14
00897447  885e28           mov  byte  [esi + 0x28], bl   ; interface +0x18
```

| interface offset | field | written by |
|---|---|---|
| `+0x00` | vptr | ctor |
| `+0x04` | **duration** — the cooldown's own length, in frames | `0x00896F8B`, full recharges only |
| `+0x08` | **readyFrame** — absolute logic frame | `0x00896F70` / `0x00896F8B` |
| `+0x0C` | pause count | `0x00896756` |
| `+0x10` | frame the pause began | `0x00896756` |
| `+0x14` | percent captured at the pause | `0x00896756` |
| `+0x18` | one byte, cleared at the end of every recharge | `0x00896F8E` |
| `+0x1C` | dword | — |
| `+0x20` | one byte, the "held" latch | `0x00896A32` |

`sizeof` is `0x24` — `SpecialPowerTimerRefreshSpecialPower` allocates exactly `0x34`
(`0x00654884`) and adds no fields of its own, so the base ends where the interface ends.

`+0x04` and `+0x08` are both in the module's `Xfer` (`0x0089679D`, which pushes `this+0x14`,
`this+0x18`, `this+0x1C` and `this+0x24` at `0x008967CB`..`0x008967F7`), so **a savegame preserves
both** and the patch needs no version bump and no xfer change.

### 1.2 What `startPowerRecharge` computes

```
00896e6c  call 0x688d3c            ; template -> final override
00896e71  cmp  byte [eax+0x59], 0  ; SharedSyncedTimer -> Player-side timer, returns (see 7.2)
00896e97  push 0x0c                ; RECHARGE_TIME
00896ea0  call 0x68c82d            ;   -> [ebp-0xc], the attribute-modifier multiplier
00896eba  mov  eax, [eax+0x18]     ; SpecialPowerTemplate.Flags
00896ebd  shr  eax, 5              ;   bit 5 = RESPECT_RECHARGE_TIME_DISCOUNT
00896ec2  je   0x896ed5            ;   not set -> [ebp-8] stays 1.0
00896ec7  call 0x6aaad2            ;   set     -> fld [Player+0x718]
00896ecc  fadd [0xbd1908]          ;              + 1.0
00896ee3  mov  eax, [eax+0x20]     ; SpecialPowerTemplate.ReloadTime, int frames
00896ef6  fmul [ebp-8]             ;   * the player discount
00896ef9  fmul [ebp-0xc]           ;   * the attribute modifier
00896efc  call 0xa3cfa4            ; ftol -> edi
00896f03  test edi, edi / inc edi  ;   clamped to >= 1
00896f14  jbe  0x896f75            ; the float argument decides full vs partial
00896f7f  mov  [esi+8], eax        ;   full:    readyFrame = frame + edi
00896f8b  mov  [esi+4], eax        ;            duration   = edi
```

So, writing `m` for the cast-time multiplier:

```
m         = (Flags & RESPECT_RECHARGE_TIME_DISCOUNT ? 1 + Player[0x718] : 1)
          * getModifierMultiplier(object, RECHARGE_TIME)
duration  = max(1, ftol(ReloadTime * m))
readyFrame= currentFrame + duration
```

Two facts about `m` are worth stating plainly, because they set the patch's whole surface:

- **`RECHARGE_TIME` (attribute-modifier type 12) is read at exactly two sites in the binary** —
  `0x00896EA0` here and `0x00991564` in the second implementation (§7.1). A scan of `.text` for
  `push 0xC` reaching either `0x0068C82D` or `0x0068C818` returns those two and nothing else.
- **`Player+0x718` is one float per player**, written only by `SpellRechargeModifierUpgrade`, read
  only at `0x00896EC7`, `0x0099156C` and `0x006AD20E`. It defaults to `0.0`, so an unmodified
  player multiplies by `1.0`. See [`spell-recharge-filter.md`](spell-recharge-filter.md), which
  maps the upgrade side of this in full.

`m` is a **time** multiplier, not a speed. The user-facing "150% cooldown speed" is
`RECHARGE_TIME = 66%` in INI, and a `SpellRechargeModifierUpgrade` writing `Percentage = -15%`
produces `m = 0.85`.

### 1.3 The two readers, and why the button clock is not a third problem

```
isReady          0x00896C72   [esi+0xc] == 0 && TheGameLogic.frame >= [esi+8]
getPercentReady  0x00896CF2   1.0 - (readyFrame - now) / duration        (0x00896D77..0x00896DA1)
```

Nothing caches either answer; both are recomputed per call from `+0x04` and `+0x08`. A patch that
keeps those two fields mutually consistent therefore needs **no UI work at all** — no `.apt`, no
`.csf`, no ControlBar hook. §3.3 is what "consistent" has to mean.

## 2. Why there is no tick to hook

The obvious shape — decrement a timer faster — is not available, and the reason is worth spelling
out before the design, because it kills three cheaper ideas.

- **The cooldown is not a countdown.** It is an absolute frame, so nothing has to run while it
  elapses, and nothing does.
- **Most special-power modules are not update modules at all.** The interface appears in 26
  vtables; only some of those are `SpecialAbilityUpdate` flavours, and even those sleep rather than
  spin while recharging.
- **The engine's own precedent shifts the frame, it does not tick it.** `0x00896756` (interface
  slot `+0x24`) pauses a recharge by remembering the frame and the percent, and resumes it with
  `[esi+8] += now - [esi+0x10]`. So "readyFrame is adjusted after the fact" is an established move
  in this class — but only ever *forward*, and only in whole frames between two events.
- **Integrating at read time is not an option**, however tempting. The percent is queried by the
  local UI for the local selection only; making simulation state depend on that is a desync.

What follows from all four: a correct implementation needs a **deterministic per-frame driver**
(§4), and the arithmetic it runs has to be exact enough to survive being applied to thousands of
modules for thousands of frames (§3).

## 3. The design

### 3.1 `duration` is the record of the baked-in multiplier

The one thing the sweep must know is *what multiplier is already in this cooldown* — subtracting a
rate without it double-counts a modifier that was already active at cast time. There is nowhere to
store it, and it does not need storing: `duration` is `max(1, ftol(ReloadTime * m))`, and
`ReloadTime` is still on the template. So the test is

```
frames_now = max(1, ftol(ReloadTime * m_now))      ; recompute the cast-time formula, verbatim
if (frames_now == duration) -> nothing has changed
```

an **integer** comparison against the exact quantity the engine itself would have written. No
tolerance to pick, no float drift to accumulate, and no way for the sweep to disagree with a cast
that happened on the same frame. This is also the patch's fast exit: for every power whose
modifiers have not moved, the sweep does one multiply, one `ftol` and one `cmp`.

Per frame, for one flavour-1 module on cooldown:

```
now         = TheGameLogic.frame
ready       = spi[+0x08];  if (ready <= now)      skip     ; not on cooldown
if (spi[+0x0c] != 0)                             skip     ; paused - 0x00896756 owns readyFrame
tmpl        = getFinalOverride(spi->getSpecialPowerTemplate())
if (tmpl[+0x59])                                 skip     ; SharedSyncedTimer - see 7.2
reload      = tmpl[+0x20];  if (reload <= 0)     skip
duration    = spi[+0x04];   if (duration <= 0)   skip     ; never recharged, or pre-patch savegame
m_now       = getModifierMultiplier(obj, 12)
if (tmpl[+0x18] & 0x20) m_now *= 1.0 + player[+0x718]
frames_now  = max(1, ftol(reload * m_now))
if (frames_now == duration)                      skip     ; <- the common case
remaining   = max(1, ftol((ready - now) * frames_now / duration))
spi[+0x08]  = now + remaining
spi[+0x04]  = frames_now
```

### 3.1.1 Recomputing means *bit-for-bit* recomputing

The comparison in §3.1 is only exact if the recomputation is. The stock sequence is

```
00896eeb  fild dword [ebp-4]   ; ReloadTime
00896ef6  fmul dword [ebp-8]   ;   * the player discount
00896ef9  fmul dword [ebp-0xc] ;   * the attribute modifier
00896efc  call 0xa3cfa4        ; ftol
```

and both multiplies happen **in an x87 register**, so the intermediate is never rounded to a
`Real`. A cave that folded the player factor into the attribute slot first — the obvious
simplification, one slot fewer — would round it, and one ULP either side of the `ftol` boundary is
a duration one frame off the engine's own. That is not a rounding curiosity: it makes
`frames_now != duration` on the first swept frame after *every* cast, so the patch would rescale
once per cast on data that has no modifier at all, exactly contradicting §8's no-op property. The
implementation therefore keeps two slots and emits the same three instructions in the same order.

### 3.2 Rescaling the remainder *is* the per-frame rate

This is the claim the whole design rests on, and it is an identity rather than an approximation.

Model the cooldown as a fixed amount of unscaled work `W` — the `ReloadTime` frames the power owes
— consumed at rate `1/m` per frame while multiplier `m` holds. Remaining wall-clock time is then
`W_left * m`. The stored `remaining` *is* `W_left * m`, so when `m` becomes `m'`:

```
remaining' = W_left * m' = (remaining / m) * m' = remaining * m' / m
            = remaining * frames_now / duration          (both scaled by the same ReloadTime)
```

which is what §3.1 writes. Rescaling on change and integrating a rate every frame are the same
function; the rescale form simply skips the frames on which the rate did not change. A multiplier
held for half a cooldown and then dropped produces the same finish frame either way, because the
second rescale reverses exactly the fraction of work the first one did not consume.

Worked, at 30 fps, `ReloadTime = 300` (10 s), no modifier at cast:

| frame | event | duration | remaining | note |
|---|---|---|---|---|
| 0 | cast | 300 | 300 | `m = 1.0` |
| 90 | aura arrives, `RECHARGE_TIME = 66%` | 198 | 138 | `210 * 198/300`; 7 s left becomes 4.6 s |
| 190 | aura drops | 300 | 57 | `38 * 300/198`; 1.27 s left becomes 1.9 s |
| 247 | ready | | | stock would have finished at 300 |

The error is the two `ftol` truncations — **under one frame per change**, and not cumulative in the
number of frames, only in the number of changes.

### 3.3 Why the clock does not jump

`getPercentReady` is `1 - remaining/duration`. The rescale multiplies `remaining` and `duration` by
the same factor, so the ratio is preserved to within the truncation: **the button's pie sits
exactly where it was and changes only how fast it fills**. Writing `+0x08` without `+0x04` — the
tempting one-line version — would instead snap the clock forward the instant an aura arrived and
snap it back when the aura expired, which is precisely the artefact that made
`PRODUCTION_HERO` unshippable in
[`construction-speed-modifiers.md`](construction-speed-modifiers.md) §2.2. Both fields, or neither.

### 3.4 What is deliberately not done

- **No fractional accumulator, and no growth to hold one.** The rescale is event-shaped, so there
  is no per-frame fraction to carry. (A per-frame variant needs one, and the only room is the three
  bytes of tail padding at interface `+0x19`, reachable by widening the ctor's
  `mov byte [esi+0x28], bl` at `0x00897447` to a `mov dword` — same instruction length, `88` → `89`,
  the trick `lifetime-fields` uses. It is not needed here and is recorded only so the next
  reader does not go looking.)
- **No use of the public partial-recharge path.** `startPowerRecharge` with a **negative** argument
  does advance a cooldown — `frames = (1 - (percentReady - arg)) * fullFrames` at
  `0x00896F2F`..`0x00896F62`, and nothing clamps `arg` above zero — which looks like a free
  implementation. It is not: that path re-derives the whole cooldown from the percent and truncates
  through `ftol` on **every** call, so driving it once per frame bleeds up to a frame per frame.
  Use it for a one-shot, never for a rate.

## 4. The driver

### 4.1 The sweep

There is one deterministic per-frame walk available, and `GameLogic::update` already performs it
three times for other reasons (`0x0062E664`, `0x0062E908`, `0x0062E951`):

```
0062e908  mov ebx, [esi+0xac]      ; TheGameLogic+0xAC = the object list head
  ...
0062e92b  mov ebx, [ebx+0x8c]      ; Object+0x8C = next object
0062e931  test ebx, ebx / jne
```

and per object, the module array is the null-terminated one the curse fan-out walks
(`0x0068BDD0`), with the special-power interface reached through the module's own vtable rather
than by guessing a layout:

```
esi = [obj+0x24c]                  ; BehaviorModule *[], NULL-terminated
for each m:
    ecx = m + 0xc                  ; the BehaviorModuleInterface subobject
    spi = [[ecx] + 0x20]()         ; getSpecialPower() -> SpecialPowerModuleInterface* or NULL
```

That last call is the engine's own idiom, lifted from
`SpecialPowerTimerRefreshSpecialPower::doSpecialPower` at `0x008979F5`..`0x008979FC`. Using it
means the sweep never assumes a module layout, and a module type this patch has never heard of
answers `NULL` and costs one indirect call.

**Order the work object-first, modifier-last.** `getModifierMultiplier` (`0x0068C82D`) reaches the
holder through `0x0068C4A6`, which is a *module lookup by name key* — a second walk of the same
module list. Query it only once per object, and only after the module walk has found at least one
power actually on cooldown. In a normal match that is zero objects on almost every frame, and the
whole sweep degenerates to a pointer chase plus one indirect call per module.

### 4.2 Where to hook it

**Recommended: `0x0062E56A`, the call that gates the frame counter.**

```
0062e568  8bce             mov ecx, esi
0062e56a  e8c16bffff       call 0x625130     ; <- 5 bytes, not a branch target
0062e56f  84c0             test al, al
0062e571  7407             je 0x62e57a
0062e573  84db             test bl, bl
0062e575  7507             jne 0x62e57e
0062e577  ff4640           inc dword [esi+0x40]   ; the logic frame advances here
```

The cave calls `0x00625130`, keeps `al`, and runs the sweep **only when `al != 0 && bl == 0`** —
that is, on exactly the frames where the counter increments. Both flags are logic-side and
identical on every peer, so the sweep cannot run a different number of times on two machines. `bl`
is live and initialised on every path that reaches this instruction (`0x0062E550` / `0x0062E554`,
both under the `edi == 1` arm that leads here).

`0x0062E577` itself is 3 bytes and is a fall-through target, which is why `live-bridge` does not
take it either; see [`live-bridge`](../patches/experimental/live_bridge.py)'s docstring for the same finding.

**Alternative: `0x0062E6A4`** (`e8 60 21 e1 ff`, `call 0x440809`) — five bytes further down the
unconditional main path, not a branch target, and simpler because it needs no flag reading. It sits
*after* an early-exit at `0x0062E5C0`, so it is skipped on frames the recommended site would still
cover. Take it only if a live test shows that path never runs mid-match.

**Do not take the entry.** `GameLogic::update` begins at `0x0062E4E8` and its first five bytes
(`b8 da 41 b8 00`) are `live-bridge`'s hook. `0x0062E56A` is 130 bytes past it and inside the same
function, so the two compose; that is deliberate, since `hero-mana` gave up a per-frame design
precisely to stay out of `live-bridge`'s way.

## 5. Hook inventory

| # | site | original bytes | what replaces it |
|---|---|---|---|
| 1 | `0x0062E56A` | `e8 c1 6b ff ff` | `call <tick>`; the cave calls `0x00625130`, then sweeps when `al && !bl` |

One edit — **four bytes**, since the `0xE8` stays put. Everything else is cave.

As built, in emission order (the innermost first, so the internal calls resolve as labels):

| block | bytes |
|---|---|
| `power` — flavour check, the §3.1 arithmetic | 293 |
| `object` — module walk, `getSpecialPower` per module | 52 |
| `sweep` — the object list | 46 |
| `tick` — call through, flag gate, `pushad`/`popad` | 21 |
| **total** | **412** |

One `0x1000` section via `sage_patch.utils.allocate_section`, as every other patch here does. The
section is **not writable**: the patch keeps no state of its own, which is §3.1 restated as a
property `verify` can check.

### 5.1 The flavour check is one comparison

The sweep must not write `+0x08` on a module whose readyFrame is at `+0x04`. The cleanest
discriminator is the definition of the flavour itself:

```
fn = [[spi] + 0x3c]              ; the module's own startPowerRecharge
cmp fn, 0x00896e31
jne skip                         ; 0x00991500 or anything else -> leave alone
```

Fail closed. A vtable slot holding neither known implementation is a module type this reading does
not cover, and skipping it costs a feature, not correctness.

### 5.2 Registers and reentrancy

- `0x0068C82D` is `__thiscall` + 4 stack args, `ret 0x10`, and **does not preserve `ecx`**; the
  cave must stash the object across it. `ebx`/`esi`/`edi` are preserved, which is what lets the
  module cursor survive the call. This is the same trap
  [`construction-speed-modifiers.md`](construction-speed-modifiers.md) §4.3 documents.
- The cave is entered at a `call` site, so it owes the caller `ebx`, `esi`, `edi`, `ebp` and must
  return `0x00625130`'s `al` untouched.
- Nothing in the sweep calls back into game logic — `getSpecialPower`, `getSpecialPowerTemplate`,
  `getFinalOverride` and `getModifierMultiplier` are all queries — so there is no reentrancy to
  guard, unlike `spawn-union`'s proxy.

## 6. What follows for free

- **The button clock**, §3.3 — no `.apt`, no `.csf`, no ControlBar hook.
- **The AI.** Its planning asks `isReady` and `canUseSpecialPower`, both of which read the same
  `readyFrame`. An AI hero whose cooldown was shortened by an aura simply finds the power available
  sooner.
- **Pause/resume.** Skipped while `+0x0C` is non-zero, so the two mechanisms never fight over
  `readyFrame`; a power paused mid-cooldown resumes at whatever length the last rescale left it.
- **The original complaint.** A player finishing `SpellRechargeModifierUpgrade` mid-match now
  shortens every flagged power already on cooldown, because `1 + Player[0x718]` moved and
  `frames_now != duration` follows on the next frame. No extra code.
- **Savegames.** Both fields are already `Xfer`'d (§1.1), so a load restores a rescaled cooldown
  exactly, with no version bump.

## 7. Out of scope, named

### 7.1 The second `startPowerRecharge`

There is a **second implementation** at `0x00991500`, in 3 of the 26 interface vtables
(`0x00C650F0`, `0x00C74878`, `0x00C873E0`). It is the same routine written against a different
layout — `ModuleData` at `ecx-0x20`, so the interface sits at module `+0x24` — and it differs in
two ways that matter:

- **It keeps no duration.** `readyFrame` is at `+0x04` and there is no second field; its
  `getPercentReady` (`0x009913BC`) divides by the template's raw `ReloadTime` at `0x00991452`
  instead. So its clock is *already* wrong today whenever a cast-time modifier applied, and there
  is nothing on the module from which `m` at cast could be recovered.
- **It has no flag test.** `0x0099156C` folds `Player+0x718` in unconditionally, where
  `0x00896EC7` gates on `RESPECT_RECHARGE_TIME_DISCOUNT`. Worth noting against
  [`spell-recharge-filter.md`](spell-recharge-filter.md), which says the flag is tested at exactly
  one instruction — true, and this is why: the other implementation does not test it at all.

Covering flavour 2 means giving it a duration field, which means growing a class whose identity is
not yet established. **Which three module types these are is the first open question in §9**, and
until it is answered the honest position is that they are skipped.

### 7.2 `SharedSyncedTimer` powers

`0x00896E71` diverts a `SharedSyncedTimer = Yes` power into `Player::startSharedSyncedTimer`
(`0x006AD1B0`), which stores a ready frame in a list node hanging off `Player+0x724` (node `+0x08`
is the shared-timer id, `+0x0C` the frame) and applies `Player+0x718` at `0x006AD20E` with no flag
test. That timer is per **player**, so an object-scoped `RECHARGE_TIME` modifier has no meaning for
it and only the player upgrade could ever move it. It stores no duration either. Skipped, and cheap
to skip: the sweep already reads `tmpl[+0x59]`.

### 7.3 Not attempted

- **Making the recharge *start* respond to anything.** Untouched; `startPowerRecharge` keeps its
  stock arithmetic byte for byte, which is what keeps a stock-data game identical.
- **Carrying a cooldown across a hero's death.** A separate question with a separate answer, because
  a citadel revive builds a *new* object and this patch only ever rewrites a living one. Scoped in
  [`cooldown-through-death.md`](cooldown-through-death.md), which composes with this patch.
- **A per-power opt-out.** See §8 — the patch is already a no-op for any power whose multiplier
  never moves mid-cooldown, so a keyword would be gating something that mostly does not fire.

## 8. Cost, risk and what it changes

| | |
|---|---|
| edits to `.text` | 1 `call rel32` |
| new sections | 1 (~250 bytes) |
| INI surface | **none** — no keyword, no `.sagepatch` entry, no `sage_ini` change |
| structures | none grow; no ctor, dtor or xfer change |
| effort | ~1 day, most of it in the sweep and its `verify` |
| risk | low-medium |

**The safety property worth stating first: on data that never moves a recharge multiplier during a
cooldown, this patch changes nothing.** The rescale is gated on `frames_now != duration`, and
`frames_now` is computed by the stock formula from stock inputs, so a match with no `RECHARGE_TIME`
modifier and no mid-match `SpellRechargeModifierUpgrade` produces the identical finish frame for
every power. That makes it cheap to test and cheap to back out.

What it does change:

- **Simulation state.** `readyFrame` gates whether an ability can fire. Every peer needs the
  patched binary, and replays recorded on it will not play back on a stock one.
- **Per-frame cost, honestly.** The sweep is `O(objects x modules)` pointer loads plus one indirect
  call per module, per logic frame — a few thousand indirect calls in a large match, with the
  expensive `getModifierMultiplier` reached only for objects that actually hold a power on
  cooldown. That is small against what `GameLogic::update` already does on the same list, but it is
  not nothing, and it is the only part of this patch that scales with army size.
- **Balance.** A leadership aura that shortens cooldowns becomes materially stronger, because it
  now pays out on the ability already spent rather than only on the next one. That is the point,
  and it is worth saying out loud to whoever tunes the mod.

**Conflicts.** Nothing in the current `PATCHES` registry touches `0x0062E56A`, the object list
walk, or any field of `SpecialPowerModule`. `live-bridge` takes `GameLogic::update`'s **entry**
(`0x0062E4E8`, 5 bytes) and nothing else in the function, so the two compose in either order;
`multi-execute-gate` and `hero-mana` both read special-power state but write neither field.

**Verification.** A `sage-patch verify` pass should assert `e8 c1 6b ff ff` at `0x0062E56A`, the
untouched cast-time arithmetic at `0x00896EBA` (`8b 40 18 c1 e8 05 a8 01`) and at `0x00896F8B`
(`89 46 04`), that `0x00896E31` still appears at slot `+0x3C` of exactly 23 vtables, and that the
cave's flavour constant matches the function actually found there — if a future build splits or
merges the two implementations, the premise moved and the patch must not apply.

## 9. What a live test has to settle

1. **Which three module types use `0x00991500`** (§7.1), and whether any of them is common enough
   that skipping them is visible. This decides whether §7.1 stays a limitation or becomes a second
   patch.
2. **That the sweep sees every power.** Put a `RECHARGE_TIME` aura on a hero mid-cooldown and read
   `interface+0x04` / `+0x08` out of process with `sage_live`; the duration must change on the
   frame the aura lands, not on the next cast.
3. **That the clock does not jump** when it does, and does not jump back when the aura expires —
   §3.3 is derived from `0x00896D77`, not observed.
4. **That `0x0062E56A` runs exactly once per logic frame** across a pause, a save/load, and a
   replay — count sweeps against `TheGameLogic+0x40` from the cave.
5. **Determinism.** Two patched clients, one aura, one long cooldown: the finish frames must agree
   to the frame, and a recorded replay must play back identically.
6. **The frame cost** in a large late-game match, measured rather than assumed (§8).
7. **Degenerate multipliers** — `0`, negative, and very large — at both the cast site and the
   rescale, checking the `max(1, ...)` clamps hold on both.
8. **Interaction with the pause path**: pause a power mid-cooldown (`0x00896756`), change the
   multiplier while paused, resume, and confirm the resume does not undo the rescale.

## Appendix — every address this document depends on

| VA | meaning |
|---|---|
| `0x00440809` | the call at the alternative hook site `0x0062E6A4` |
| `0x00625130` | the predicate gating the frame increment — the recommended hook's callee |
| `0x0062E4E8` | `GameLogic::update` (entry; `live-bridge`'s five bytes) |
| `0x0062E56A` | **the hook site** — `call 0x625130`, `e8 c1 6b ff ff` |
| `0x0062E577` | `inc dword [TheGameLogic+0x40]` — the frame advance, 3 bytes |
| `0x0062E664` / `0x0062E908` / `0x0062E951` | the engine's own object-list walks in `GameLogic::update` |
| `0x0062E6A4` | the alternative hook site, `e8 60 21 e1 ff` |
| `0x00651980` | `SpecialPowerTimerRefreshSpecialPower` ctor — writes the three vptrs |
| `0x006519A6` | interface slot `+0x0C` — `[interface+0x0c] > 0` |
| `0x006519AF` | thunk: `BehaviorModuleInterface` slot `+0xAC` -> `startPowerRecharge` |
| `0x00654884` | that module's `newModule` — allocates `0x34`, fixing `sizeof(base)` |
| `0x006570FE` | `ModuleFactory::addModule` — the registration all 330 module types go through |
| `0x00688D3C` | `Overridable::getFinalOverride` |
| `0x0068B678` | `Object::getControllingPlayer` |
| `0x0068BDD0` | the curse fan-out — the canonical `Object+0x24C` module walk |
| `0x0068C4A6` | `Object::getModifierHolder` — a module lookup by name key, not a field |
| `0x0068C82D` | `Object::getModifierMultiplier(type, out, ctx, flag)`, `ret 0x10`, clobbers `ecx` |
| `0x006AAAD2` / `0x006AAAEE` | get / set `Player+0x718`, the spell-recharge modifier |
| `0x006AD1B0` | `Player::startSharedSyncedTimer` — the `Player+0x724` list |
| `0x006AD20E` | `fmul [Player+0x718]` inside it, with no flag test |
| `0x006AD26F` | the shared-timer reader |
| `0x00804FFF` | `ModifierHolder::getMultiplier` — seeds `*out = 1.0`, walks `holder+0x20..+0x24` |
| `0x00805268` | `ModifierList::getValue` — the linear scan over `0x14`-byte entries |
| `0x00896756` | interface slot `+0x24` — pause / resume, `[esi+8] += now - [esi+0x10]` |
| `0x00896C72` | `isReady` — `[esi+0xc] == 0 && frame >= [esi+8]` |
| `0x00896CF2` | `getPercentReady` — `1 - (readyFrame - now) / duration` |
| `0x00896D77`..`0x00896DA1` | that division, and the shared-timer variant above it |
| `0x00896E31` | **`startPowerRecharge`, flavour 1** — 23 vtables, interface at module `+0x10` |
| `0x00896E71` | the `SharedSyncedTimer` divert (`template+0x59`) |
| `0x00896EA0` | the `RECHARGE_TIME` query — one of two in the binary |
| `0x00896EBA` | the `RESPECT_RECHARGE_TIME_DISCOUNT` test |
| `0x00896EE3` | `SpecialPowerTemplate.ReloadTime` (`+0x20`, int frames) |
| `0x00896F03` | the `>= 1` clamp |
| `0x00896F70` / `0x00896F8B` | `readyFrame` (partial / full) and **`duration`** (full only) |
| `0x00896F8E` | `mov byte [esi+0x18], 0` — the byte before the tail padding |
| `0x0089679D` | the module `Xfer` — covers `this+0x14`, `+0x18`, `+0x1C`, `+0x24` |
| `0x008973EE` | the base ctor; `0x00897447` is the `mov byte` that could be widened (§3.4) |
| `0x008979F5` | the `getSpecialPower` idiom the sweep copies (`[m+0xc]` vtable slot `+0x20`) |
| `0x00991500` | **`startPowerRecharge`, flavour 2** — 3 vtables, `readyFrame` at `+0x04`, no duration |
| `0x00991564` | its `RECHARGE_TIME` query — the other one of two |
| `0x0099156C` | its unconditional `Player+0x718` fold, with no flag test |
| `0x009913BC` | its `getPercentReady`, dividing by raw `ReloadTime` at `0x00991452` |
| `0x00A3CFA4` | `ftol` |
| `0x00BD1908` | `1.0f` |
| `0x00C64FF0` | flavour-1 `SpecialPowerModuleInterface` vtable; `startPowerRecharge` at `+0x3C` |
| `0x00C650F0` / `0x00C74878` / `0x00C873E0` | the three flavour-2 vtables |
| `0x00DE412C` | `TheGameLogic` — frame at `+0x40`, object list head at `+0xAC` |
| `Object+0x8C` | next object in that list |
| `Object+0x24C` | the NULL-terminated `BehaviorModule *[]` |
