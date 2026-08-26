# Putting a button's timer at the bottom of its description

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); file offset is
`VA - 0x400000` for everything cited here. Read **statically** on 2026-08-16 from the stock
`game.dat` in this repo (11,346,944 bytes) with `pefile` + `capstone`. Nothing below has been
observed in a running game.

**The ask.** A `CommandButton`'s description gains one more line at the bottom saying how long the
thing it triggers takes: an ability's **cooldown** (its full length when the power is ready, the
**time left** when it is recharging), a unit's or structure's **build time**, and an upgrade's
**research time** — each with whatever modifier currently applies to it folded in.

**Verdict up front: every number asked for is already computed by a function the engine exports to
itself, and every input those functions want is already sitting in the description builder's own
stack frame.** The patch is twelve bytes of engine, one cave and no new arithmetic — the cooldown
formula is transcribed from `startPowerRecharge`, and the two build times are the engine's own
`calcTimeToBuild` pair, called with the arguments the builder has already assembled for the *cost*
line three instructions away.

**What is not free is the word "remaining".** §2 is the finding that shapes the whole patch: the
tooltip's text is built **exactly once per hover** and never refreshed while the mouse sits still,
so a countdown does not count down. Making it tick is a separate, riskier hook into a second
function, and it is not part of this patch.

- **Cost:** two 6-byte windows + an ~830-byte cave. No structure grows, no `ModuleData` changes, no
  INI keyword, no `.sagepatch` entry, no `.apt`, no `.csf` the engine requires.
- **Risk:** low. Client-local tooltip text, the same blast radius as `upgrade-description`.
- **Status: implemented as `description-timers`**
  ([`../patches/description_timers.py`](../patches/description_timers.py)), applying, verifying and
  detecting against the real `game.dat` and composing in either order with `upgrade-description`.
  **Static only - not yet observed in a running game;** §10 is what a live test has to settle.

```
sage-patch apply description-timers --in game.dat.backup --out game.dat
sage-patch verify description-timers game.dat
```

**Two things this document scoped and the patch does not do**, both deliberate and both recorded
below rather than quietly dropped: the tooltip does not repaint while you hover (§2), so the
remaining cooldown is a snapshot; and a unit already in a production queue gets its full build time
rather than its remaining one (§4). Everything else scoped here is built.

## TL;DR

- **One emit site, not five** — plus a six-byte window in the prologue that exists only to carry
  the button to it. Every case of the description builder has finished by `0x008086AE`, and the
  `Object` (`ebp-0x1c`) and the `Player` (`ebp-0x20`) are still live there; the `CommandButton` is
  not, because three cases reassign `esi` on the way. Copying it out of the prologue costs six
  bytes and buys a line that is genuinely **last**, which per-case hooks cannot promise (§1.2).
- **The description is a `UnicodeString` at `ebp-0x18` and the engine already appends to it.**
  `0x00807E2E` concatenates `TOOLTIP:TooltipCannotPurchaseBecauseQueueFull` onto it with the
  literal `L"\n\n"`. The separator guard is `upgrade-description`'s, which is the engine's own.
- **The cooldown formula is `startPowerRecharge`'s, transcribed.**
  `max(1, ftol(ReloadTime * m))` where `m = (Flags & RESPECT_RECHARGE_TIME_DISCOUNT ? 1 +
  Player[0x718] : 1) * getModifierMultiplier(object, RECHARGE_TIME)`. Recomputing it at hover time
  is what "takes cooldown reduction into account" — an aura that is up right now is in the number.
- **The remaining cooldown is a subtraction, not an estimate.**
  `Object::getSpecialPowerModule(template)` (`0x0068C26D`) hands back the module; `readyFrame` is
  at interface `+0x08` on flavour 1 and `+0x04` on flavour 2, and `TheGameLogic`'s frame is at
  `+0x40`. No float, no percentage. **Both flavours are read** (§3.1.1), which matters far more
  than the "3 of 26 vtables" count suggests: those three are *shared* vtables, and
  `WeaponModeSpecialPowerUpdate` is behind one of them - 340 behaviours in Edain.
- **A spellbook power is asked of the spellbook, not of the selection** (§3.1.2). The builder's
  object slot holds whatever the player has selected, which for a palantir button is nothing or an
  unrelated unit; the power lives on the player's spellbook object, found with the engine's own
  `KINDOF SPELL_BOOK` predicate.
- **A line whose number would be zero is not printed at all.** 204 of Edain's 835 `SpecialPower`
  blocks have no `ReloadTime` - that is what a passive ability's button is - and stating `0` for
  them is worse than saying nothing.
- **Both build times are one call each, with the arguments already on hand.**
  `ThingTemplate::calcTimeToBuild(player, object, -1)` (`0x0073C39E`) and
  `UpgradeTemplate::calcTimeToBuild(player, object)` (`0x0066F1A8`) are the *same functions the
  production queue uses* to decide how long the thing will actually take (`0x008A04DA`), so the
  tooltip cannot disagree with the game. The unit one already folds in the player handicap, the
  per-template production bonus **and** the producer's `ProductionModifier` time multiplier.
- **The line is silent unless the mod declares its string.** The engine's text fetch takes an
  `exists` out-parameter that twelve call sites pass `0` for. Passing a real one and dropping the
  line when the key is missing makes the patch a **no-op on unmodified data** — no `MISSING:'…'`
  text, no layout change — which is the same rule `hero-mana`'s `ManaPool` line follows.
- **The tooltip is built once per hover** (§2), so every number is a snapshot taken when the
  tooltip appeared. The full durations are exactly right — they do not change while you look at
  them — and the remaining cooldown is right at that instant and then frozen.
- **Client-local and read-only.** Nothing enters the simulation, nothing is sent, replays cross —
  the same rule as `upgrade-description`, `replay-outcome` and `observer-switch`.

## 1. The description, and where its bottom is

### 1.1 What the builder is holding

`ControlBar::getTooltipForCommandButton` runs `0x00807A81`..`0x00808788` and is entered through the
functor vtable at `0x00C4EE08` slot `+0x0C`. It keeps six `UnicodeString`s and hands five of them
to the tooltip record's constructor at `0x008086E5`; `ebp-0x18` is the description
(`DESCRIPTION_TEXT_EBP_OFFSET`, already in [`addresses.py`](../addresses.py)).

What matters here is that its prologue resolves, once, everything three different timers need:

| slot | what | set at |
|---|---|---|
| `esi+0x0c` | the `CommandButton` | the `this` pointer's own field |
| `ebp-0x1c` | the `Object` being described — **may be null** | `0x00807AC6` / `0x00807ACB` |
| `ebp-0x20` | its `Player`, falling back to the local player when there is no object | `0x00807AF1` |
| `ebp-0x4c` | the button's `ThingTemplate` (`CommandButton::getThingTemplate`, `0x0075D1DC`) | `0x00807B1D` |
| `ebp-0x24` | the button's `UpgradeTemplate` (`CommandButton+0x24`) | `0x00807B26` |

The `Player` slot is the quietly useful one: `0x00807AD4` seeds it from `ThePlayerList`
(`0x00DE4928`) and only *then* overwrites it with `Object::getControllingPlayer` when there is an
object. So `1 + Player[0x718]` — the `SpellRechargeModifierUpgrade` discount — is answerable even
for a button with no object behind it.

**`ebp-0x4c` is not stable.** Three later cases reuse it as a scratch slot (`0x008081A6`,
`0x00808271`, and every `lea edx, [ebp-0x4c]` fetch temporary). A hook placed at the end of the
function must therefore re-resolve the `ThingTemplate` through `0x0075D1DC` rather than read that
slot. `ebp-0x24` and `ebp-0x1c` survive.

### 1.2 The one site after every case

The builder is a chain of `cmp`s on the button's GUI command (`CommandButton+0x14`), not a jump
table — `0x2E`, `0x21`, `0x18` at the tail, `0x14`, `0x19`, `0x34` earlier — and **every arm
converges on `0x008086AA`**:

```
008086a8  33 ff              xor  edi, edi
008086aa  5b                 pop  ebx                  ; balances the push at 0x00807B13
008086ab  89 7d b8           mov  [ebp-0x48], edi      ; the hint slot - branch target
008086ae  8b 0d 70 4a de 00  mov  ecx, [0x00de4a70]    ; <- the six bytes this patch takes
008086b4  3b cf              cmp  ecx, edi             ; <- the resume point
...
008086e1  8d 4d e8           lea  ecx, [ebp-0x18]      ; the description, final
008086e5  8d 4d c0           lea  ecx, [ebp-0x40]
```

`0x008086AE` is **not a branch target** (verified by disassembling the whole function and
collecting every direct branch immediate; `0x008086AB` and `0x008086AA` are, and it is not), and
the four bytes `0x008086AE` encodes appear as a little-endian imm32 **nowhere in the image**, so no
jump table reaches it either. Between it and the record's construction the only thing written is
`ebp-0x48`, the hint. **The description is final at `0x008086AE` and every case has run.**

That is the whole argument for one emit site instead of three. The per-case alternative — the unit
cost's neighbourhood at `0x00807F24`, the upgrade cost's at `0x0080839E`, the special-power case's
body at `0x0080867A` — was checked and works (all three are safe windows, and `0x0080867A`
deliberately composes with `hero-mana`, whose cave falls into exactly that address). It was
rejected for one reason: the unit case runs at `0x00807F24`, and the `CONTROLBAR:Requirements` fold
at `0x008080AE` and the `TOOLTIP:BuildDisabled` fold at `0x008080FB` both append to `ebp-0x18`
*after* it. A line emitted there is not at the bottom. One late site is the only place "bottom"
is a fact rather than a hope.

### 1.2a The price of being that late: the button has to be carried there

The one thing `0x008086AE` does **not** have is the `CommandButton`. `esi` holds the builder's
`this` for most of the function — `[esi+0xc]` is the button, read at eighteen sites — but three
cases reassign it before the join: `0x00808426` (a `ThingTemplate`), `0x00808654` and `0x0080867A`
(a `SpecialPowerTemplate`). Reading `[esi+0xc]` at the tail would dereference whichever of those
last ran.

Nor is there a frame slot to fall back on. `ebp-0x4c` holds the button's `ThingTemplate` from
`0x00807B1D`, and later cases reuse it as a `UnicodeString` scratch slot (`0x008081A6`,
`0x00808271`); `ebp-0x24` holds its `UpgradeTemplate` and is rewritten by the `0x2E` case at
`0x0080840E`. Only `ebp-0x1c` and `ebp-0x20` are written once and never touched again.

So the patch takes a **second window, six bytes, in the prologue**, at the instruction that loads
the button:

```
00807af9  89 7d c4           mov  [ebp-0x3c], edi      ; <- the six bytes this patch takes
00807afc  8b 4e 0c           mov  ecx, [esi+0xc]       ;    the CommandButton
00807aff  3b cf              cmp  ecx, edi             ; <- the resume point, the null test
```

The cave reproduces both instructions and copies `ecx` into a dword of its own. Three properties
make that safe rather than merely convenient:

- **The path is unconditional.** Everything above `0x00807AF9` is straight-line from the function's
  entry, so the copy is refreshed on every build and cannot be stale.
- **The null case takes care of itself.** `0x00807AFF` is the test that sends a null button
  straight to `0x008086AB` — which is *before* the emit window, so the tail hook still runs. It
  runs having been handed the null the prologue loaded, and does nothing.
- **The builder is not reentrant.** It has exactly one caller, `0x00807676`, which runs on hover on
  one client. There is no second description being built while this one is in flight.

The cave's dword is why its section is `MEM_WRITE` as well as executable, which is the same
allocation `herobar` makes for its per-slot cursors.

### 1.3 The line idiom, and why it costs no exception-handling state

Twelve sites share the way a `<label>: <number>` line is made. The canonical one, the `UnitCost`
line at `0x00808697`:

```
push <value>                   ; the varargs, lowest address read first
push 0                         ; the fetch's `exists` out-parameter - NOT a value slot
push 0x00c4ee20                ; "TOOLTIP:UnitCost"
mov  ecx, [0x00de4b04]         ; TheGameText
mov  eax, [ecx]
call [eax+0x44]                ; fetch(label, exists) - __thiscall, ret 8
push eax
lea  eax, [ebp-0x28]           ; the destination UnicodeString
push eax
call 0x00adf7e0                ; concat-format into it
add  esp, 0xc                  ; one vararg + the concat's two arguments
```

Two properties make this cheap to copy. **Slot `+0x44` returns a string the caller does not own** —
no site destroys it and no site touches the EH state byte at `ebp-4`, unlike slot `+0x3C`, which
fetches into a caller `UnicodeString` at `ebp-0x44` and bumps `ebp-4` around it. And `0x00ADF7E0`
is `cdecl`, so the whole block is stack-neutral and needs only `ebp` to still be the builder's
frame.

**And one property makes it a trap, which this patch fell into and had to be told about.**
`0x00ADF7E0` is not a concatenate — it forwards to `0x00437120`, which `vswprintf`s into a `0x4000`
scratch buffer and ends in `UnicodeString::set` (`0x00436B20`). **It replaces its destination.**
Every one of the twelve engine sites hides that, because each of them formats into a slot it is the
only writer of: the cost line owns `ebp-0x28`, the command-point line owns `ebp-0x40`, and neither
ever sees text it did not put there. Pointing the same block at `ebp-0x18` does not add a line to
the description — it *becomes* the description, and the `DescriptLabel` is gone. Nothing static
catches this: the cave is exactly what the emitter meant to emit, `verify` passes, and the tooltip
comes out looking deliberate.

So the line is built in two steps, which is what the builder's **own** rank case does at
`0x008085C4` and the reason `ebp-0x2c` exists at all: format into a temporary `UnicodeString`, then
join it to the description with `UnicodeString::concat` (`0x004065FE`). The temporary is a single
dword — a pointer to a refcounted buffer — so the cave initialises one to zero below `esp`, formats
into it, concatenates it, and calls `~UnicodeString` (`0x004367B0`) to give the reference back. The
key-missing path skips the destructor because it is reached before the format, with the local still
the zero it was initialised to and owning nothing.

The one thing that step costs is exception safety: the temporary is not covered by the builder's
`ebp-4` state, so a throw out of `format` or `concat` leaks its buffer. Both throw only on
allocation failure, and the alternative — participating in the function's EH bookkeeping from a
cave — is far more dangerous than the leak.

Two changes from the stock idiom:

- **The destination is `ebp-0x18`, not `ebp-0x28`.** `ebp-0x28` is the tooltip record's *cost*
  slot, drawn separately; the description is `ebp-0x18`. The engine appends to `ebp-0x18` itself at
  `0x00807E2E`, so this is not a new use of the slot.
- **A guarded separator goes in front.** The engine's own "is there anything to separate from"
  test, from the two folds at `0x008080AE` and `0x008080FB`: null buffer pointer, or zero length
  word. `upgrade-description` already reproduces it, and for the same reason — a button with no
  `DescriptLabel` must not gain a leading blank line. Note the trap that patch documents: those
  folds compare against `edi`, which is the function's zero *on their path* and is not reliably
  zero elsewhere, so the cave compares with immediates.

### 1.4 Frames to seconds, and the rate that is not 30

Every timer below is in logic frames, so the last step is a divide — and **the logic frame rate is
5, not 30**. Two adjacent dwords hold the two rates and picking the wrong one is a silent factor of
six on every line the patch prints, so this is worth deriving rather than assuming.

Neither is a link-time constant. `0x00644F11` takes both rates as arguments and fills a block of
derived ratios from them:

```
00644f4a  mulss xmm0, xmm2            ; xmm3 = (float)logic, xmm2 = 0.001
00644f4e  movss [0x00d9f610], xmm0    ; logic/1000  -> 0.005   ms to frames
00644f61  divss xmm1, xmm3
00644f65  movss [0x00d9f614], xmm1    ; 1000/logic  -> 200      ms per frame
00644f78  divss xmm4, xmm3
00644fa6  mov   [0x00d9f608], esi     ; logic                   -> 5
00644fb0  mov   [0x00d9f60c], ecx     ; the other rate          -> 30
00644fb6  movss [0x00d9f61c], xmm4    ; 1/logic     -> 0.2       seconds per frame
```

Four independent values say the same thing: `0.005`, `200`, `0.2` and the `5` itself. The second
rate is the client's — `0x00D9F620` holds its `33.33` ms and `0x00D9F62C` its `1/30` — and the
setter caps the ratio between the two at six, which `30/5` exactly meets.

**Confirmed from outside the binary.** `sage_replay`'s finalized BFME2 corpus clusters at **0.20
seconds per timecode**, measured against each replay's own wall-clock span rather than an assumed
tick rate (`_NOMINAL_SECONDS_PER_FRAME` in [`sage_replay/replay.py`](../../sage_replay/replay.py)).
A recorded timecode is a logic frame, so the recordings and the constant block agree.

So the displayed value is `frames / [0x00D9F608]`, read live — a mod that changed the rate moves
the readout with it. (Note this is also why
[`recharge-rescale.md`](recharge-rescale.md) §3.2's worked example, which converts at 30 fps, reads
six times short; the arithmetic there is unaffected, only the seconds in its table.)

A one-decimal readout wants a `double` vararg. That is also the engine's own move, at
`0x00677E5A`..`0x00677E7B` (`CONTROLBAR:UnderConstructionDesc`): `fld` the real, `push ecx / push
ecx`, `fstp qword [esp]`, and the cleanup constant becomes `0x10` instead of `0xC`. `--integer-
seconds` uses `%d` and the stock `0xC`. **Getting that constant wrong corrupts the builder's frame
rather than failing**, which is why `hero-mana` asserts both forms in a test and this patch should
too.

## 2. The tooltip is built once per hover

This is the finding that decides what "remaining" can mean, and it is worth stating before the
arithmetic, because it kills the obvious design.

The tooltip request is installed by `0x00807848`. Its shape:

```
008078a9  mov  eax, [edi]              ; edi = this+0x2ac, the request currently held
008078ad  je   0x8078f9                ;   none -> take the new one
008078b1  call 0x008075a3              ; are the two the same request?
008078ba  je   0x8078f9                ;   no  -> replace it, and clear the latch at 0x807960
008078c7  call [eax+8]                 ;   yes -> the request's delay
008078ca  cmp  byte [0x00de8998], 0
008078d4  jne  0x8079aa                ;        <- ALREADY SHOWN: return, every frame, forever
008078da  call GetTickCount            ;        not yet shown: has the delay elapsed?
...
00807971  mov  byte [0x00de8998], 1    ; latch it
0080798d  call 0x00807676              ; and show it - this is the only call
```

and `0x00807676` is the only thing that ever calls the builder:

```
00807691  call [eax+0xc]               ; -> 0x00807A81, the description builder
008076ac  call 0x006d4728              ; hand the record to the movie
008076bc  call 0x0047d8b0              ; destroy it
```

`0x00DE8998` has **exactly three references in the image** — the read at `0x008078CA`, the clear at
`0x00807960` (reached only when a *different* request replaces the stored one) and the set at
`0x00807971`. There is no other path back into `0x00807676`.

**So the description text is composed once, at the moment the tooltip appears, and is not touched
again until the pointer moves to a different button.** A "12.4 s left" line written that way is
correct when it appears and wrong a second later.

Two answers, and **the patch ships the first**:

**(a) Snapshot — what is built.** The line reads *time left when you hovered*. The full durations
are unaffected — a cooldown length, a build time and a research time do not change while you look
at them — and the remaining cooldown is accurate on arrival and stale afterwards. Moving the mouse
off the button and back re-reads it. Zero extra risk; the patch stays entirely inside a function
that already runs on hover, which is what keeps its blast radius the same as
`upgrade-description`'s.

**(b) A live refresh — scoped, not built.** One more 6-byte window, at `0x008078D4`
(`0f 85 d0 00 00 00`, the `jne 0x8079aa` above), replaced by a `jmp` into a cave that keeps the
stock answer unless the tooltip has been up for more than some interval, in which case it falls
through to `0x00807969` and lets the show path run again. The tick source is already there:
`0x00DE899C` holds the `GetTickCount` value the delay logic uses, refreshed at `0x0080795B`.

What (b) risks is not correctness but presentation: the record is rebuilt and handed to
`0x006D4728` again, and whether that repaints in place or re-runs whatever the movie does on a new
tooltip is a question a live test answers, not a disassembler. **That is why it is not in the
patch**: it is the one part of this design whose failure mode is a UI artefact nobody can predict
from the disassembly, and it does not have to ship for the rest to be useful. Build it after §10's
item 4 has been seen once.

## 3. The three timers

The cave dispatches on `CommandButton+0x14`, the same value the builder's own chain reads.

### 3.1 An ability's cooldown

**The full duration** is `startPowerRecharge`'s arithmetic recomputed at hover time.
`0x00896E87`..`0x00896F03`, transcribed:

```
m_attr   = getModifierMultiplier(object, RECHARGE_TIME=0xC)      ; 0x0068C82D, ret 0x10
m_player = (tmpl->Flags & RESPECT_RECHARGE_TIME_DISCOUNT)        ; tmpl+0x18, bit 5
             ? 1.0 + Player[0x718]                               ; 0x006AAAD2
             : 1.0
frames   = max(1, ftol(tmpl->ReloadTime * m_player * m_attr))    ; tmpl+0x20, ftol 0x00A3CFA4
```

with `tmpl` reached through `Overridable::getFinalOverride` (`0x00688D3C`) exactly where the engine
reaches it. Both multipliers are live values, so **a leadership aura that is up right now, and a
`SpellRechargeModifierUpgrade` the player has already researched, are both in the number**. That is
the whole of "take cooldown reduction into account", and it costs one call each.

Two notes the transcription must keep. `0x0068C82D` is `__thiscall` plus four stack arguments,
cleans its own `0x10`, and **does not preserve `ecx`** — the same trap
[`construction-speed-modifiers.md`](construction-speed-modifiers.md) §4.3 and
[`recharge-rescale.md`](recharge-rescale.md) §5.2 both record. And the `ReloadTime` fold is written
as an unsigned fixup (`fild` plus a conditional `fadd [0x00BD8698]`); copy it rather than assuming
the field is small.

**The remaining duration** is a subtraction:

```
spi = getSpecialPowerModule(owner, tmpl)       ; 0x0068C26D, __thiscall, ret 4, NULL if absent
fn  = spi->vtable[+0x3c]                       ; which startPowerRecharge -> which layout
if      fn == 0x00896E31: pause = spi[+0x0c], ready = spi[+0x08]     ; flavour 1
else if fn == 0x00991500: pause = spi[+0x08], ready = spi[+0x04]     ; flavour 2
else                    -> fall back to the full duration
if (pause != 0)         -> fall back: a paused recharge has not moved its ready frame yet
now       = [[0x00DE412C] + 0x40]              ; TheGameLogic's frame
remaining = ready - now
if (remaining <= 0) -> the power is ready: show the full duration instead
```

`0x0068C26D` is the engine's own finder: it walks `Object+0x24C`, asks each module for its
special-power interface (`[m+0xc]` vtable `+0x20`) and matches on interface slot `+0x00`
(`0x008969D1` / `0x009911E0`), which compares the module data's template pointer against the
argument. The button holds the same raw pointer at `CommandButton+0x44`, so the two agree without a
`getFinalOverride` on either side. It returns the **first** match, which is also what the button's
own clock reads (`CommandButton::getPercentReady`, `0x0075CCC5`) — so a template carried by two
modules on one object is read the way the engine reads it, by construction.

The pause count is the field `isReady` gates on before it looks at the ready frame at all, and it
is worth honouring for the same reason: `0x00896756` (interface slot `+0x24`) parks a recharge by
remembering the frame it stopped on and only pushes the ready frame forward when it resumes, so
while `pause != 0` the subtraction above is counting down towards a frame that is going to move.

#### 3.1.1 Two flavours, two layouts

There are two implementations of `startPowerRecharge` and they keep the recharge in different
places, so the vtable slot has to be read before either field is:

| | flavour 1 | flavour 2 |
|---|---|---|
| `startPowerRecharge` | `0x00896E31` | `0x00991500` |
| interface subobject at module | `+0x10` | `+0x24` |
| ready frame | interface `+0x08` | interface `+0x04` |
| pause count | interface `+0x0C` | interface `+0x08` |
| `duration` kept | yes, at `+0x04` | no |
| interface vtables | 23 | 3 |
| `isReady` | `0x00896C72` (its field reads at `0x00896CD4`) | `0x0099135D` (at `0x0099139E`) |

Those two `isReady` bodies are what the patch anchors, rather than the vtables: each one is a
single window holding the pause test, the `TheGameLogic` frame load and the ready-frame compare, so
one comparison pins both offsets of one flavour in the order the engine uses them.

**"3 of 26 vtables" badly understates flavour 2**, and correcting that is why this section exists.
Those three are *shared* interface vtables — a class that overrides no interface method gets the
one its base already installed — so the module classes behind them outnumber them:

| interface vtable | classes that install it |
|---|---|
| `0x00C650F0` | `WeaponModeSpecialPowerUpdate` (`0x00898249`), `DeflectSpecialPower` (`0x008C9920`), `SiegeDeployHordeSpecialPower` (`0x008CA84A`) |
| `0x00C74878` | `SiegeDeploySpecialPower` (`0x008C9B7A`) |
| `0x00C873E0` | `SpecialPowerUpdateModule`, the base itself (`0x0099115D`) |

`WeaponModeSpecialPowerUpdate` alone is **340 behaviours in Edain** — it is the standard shape for
a hero ability that switches weapon mode for a `Duration`, and Pippin's *Neugier des Narren* is one
of them. Falling back to the full duration for all of those is why the remaining readout looked
broken rather than merely absent. Both flavours are now read; a vtable holding neither still
**fails closed** onto the full duration, which costs a feature and not a wrong number.

Deliberately *not* used: `getPercentReady` (slot `+0x08`, `0x00896CF2` / `0x009913BC`). It is the
natural-looking route and it is wrong for flavour 2, whose implementation divides by the raw
`ReloadTime` and so is already inconsistent with a cast that had a modifier applied.

#### 3.1.2 Which object owns the power

Everything above needs an *owner*, and so does the `RECHARGE_TIME` query in the full duration. The
builder's `ebp-0x1c` is **the selection**, which is the right answer for a hero ability and the
wrong one for a palantir spell button: those are drawn with whatever the player happens to have
selected behind them, usually nothing. Asking the selection for a spell's module returns NULL, and
every spellbook power then reads as its full cooldown forever.

**A spellbook is an ordinary `Object`.** `GoodSpellBook` / `EvilSpellBook` and a `ChildObject` per
faction carry their spells as `Behavior = SpecialPowerModule`, `OCLSpecialPower` and
`PlayerUpgradeSpecialPower`, all three of them flavour 1 with a plain `ReloadTime` — see
[`special-power-charges.md`](special-power-charges.md) §6.1, which maps that side in full. So the
only thing missing is the object itself, and the engine has a finder for it:

```
0x006AAE3C  cdecl (Object *obj, void *ctx) -> keep going?
            takes the first obj whose template is KINDOF SPELL_BOOK (tmpl+0x117 bit 3) and whose
            controlling player is ctx[0]; writes it to ctx[1] and stops the walk
0x006ABABD  Player::forEachTeamObject(fn, ctx) - thiscall, ret 8, pure
```

The arm is therefore: **the selected object if it has a module for this template, otherwise the
player's spellbook if it has one, otherwise nothing.** Keying on the module rather than on the
button is what keeps the cave from having to recognise a spellbook button — a power neither object
has finds no module and changes nothing — and it costs the walk only on the buttons that need it.

**Not `Player::getSpellBookObject` (`0x006AD0F8`)**, which is the engine's own wrapper around that
same pair and the obvious call to make. It memoises the answer into `Player+0x710`, and a tooltip
may not write to a `Player`. The field is read at no other site and appears in no `Xfer`, so the
write would in fact be harmless — but "client-local and read-only" is the promise this patch is
built on, and a lazily-primed cache is not the place to start making exceptions to it.

**`SharedSyncedTimer = Yes` powers** keep their cooldown on the `Player` rather than on any module:
`0x00896E71` diverts them into `Player::startSharedSyncedTimer` (`0x006AD1B0`), which stores the
ready frame in a list node off `Player+0x724`, and `0x006AD26F` reads it back. That is **three
templates in the shipped INI** — `SuperweaponSpawnOrcs`, `SpecialPowerRevealArea` and
`SuperweaponPartTheHeavens` — and not, despite the obvious guess, how a spellbook power works.
Covering them is one extra arm gated on `tmpl+0x59`; it is not built, and those three fall back to
the full duration.

#### 3.1.3 A cooldown of zero is not printed

`startPowerRecharge` clamps its result to `>= 1` before storing it, because a recharge has to end
on some frame. There is nothing to clamp *to* in a tooltip: a `SpecialPower` with no `ReloadTime`
has no cooldown, and that is exactly what a passive ability's button is — **204 of the 835
`SpecialPower` blocks in Edain**. So the ability arm reads the pre-clamp value and emits nothing at
all when it is `<= 0`.

The same rule is applied one level down, in the shared line emitter, against the number the format
will actually see: the integer quotient, so the test is exactly `frames < the frame rate` and a
duration below one second drops the line. That test has to sit **ahead of the separator** — the
emitter's late exit is reachable only before the line is built, and dropping any later leaves a
newline behind on a description that then says nothing after it.

### 3.2 A unit's or structure's build time

`ThingTemplate::calcTimeToBuild` at `0x0073C39E` — `__thiscall(ThingTemplate*)`, three stack
arguments `(Player *, Object *, Int override)`, returns **frames** in `eax`. The `-1` override
means "use the template's own `BuildTime`" (`ThingTemplate+0x4EC`, a plain `Real` parsed by
`0x0042ED00`).

The builder already makes the *identical* call one function along, for the cost line:

```
00807f2d  6a ff              push -1
00807f2f  ff 75 e4           push [ebp-0x1c]         ; the Object
00807f32  8b cb              mov  ecx, ebx           ; the ThingTemplate
00807f34  ff 75 e0           push [ebp-0x20]         ; the Player
00807f37  e8 23 43 f3 ff     call 0x0073c25f         ; ThingTemplate::calcCostToBuild
```

so the build-time line is those five instructions with one different `rel32`. What that one call
already folds in, in order:

- the player's build-time handicap table (`Player+0x3C`, indexed via `0x007B19BF`),
- the player's per-template production bonus (`0x006AF484`, applied as `1 + bonus`),
- **the producing object's `ProductionModifier` time multiplier** — `0x0068C363` finds the
  interface and slot `+0x6C` is asked for the unit flavour, at `0x0073C409`..`0x0073C41A`.

That third one is why the `Object` argument matters and why passing the builder's `ebp-0x1c` is
right: it is the producer whose button is being hovered.

**This is the same function the production queue uses.** `ProductionUpdate`'s
`getTotalBuildTimeFrames` (`0x008A04DA`) branches on the queue entry's kind at `entry+0x04` and,
for kind 1, calls `0x0073C39E` with `(player, producer, -1)` and `ecx` = `entry+0x08`. So the
tooltip and the queue cannot disagree.

The window this arm covers is wider than "units": the builder reaches the cost block for any button
carrying a `ThingTemplate` whose GUI command is not `0x19` or `0x34`, which includes structure
placement. For a structure, `calcTimeToBuild`'s frame count is also what the `DozerAIUpdate` build
state machine divides `100` and `maxHealth` by (see
[`construction-speed-modifiers.md`](construction-speed-modifiers.md) §4.5), so the number is
correct there too.

### 3.3 An upgrade's research time

`UpgradeTemplate::calcTimeToBuild` at `0x0066F1A8` — `__thiscall(UpgradeTemplate*)`, two stack
arguments `(Player *, Object *)`, `ret 8`, returns **frames** in `eax`. Established from the queue
site, which is unambiguous:

```
008a0514  ff 76 08           push [esi+8]            ; the producing Object
008a0517  8b 49 0c           mov  ecx, [ecx+0xc]     ; entry+0x0c = the UpgradeTemplate
008a051a  50                 push eax                ; the Player
008a051b  e8 88 ec dc ff     call 0x0066f1a8
```

and the builder holds the same two arguments plus the template at `ebp-0x24` — which it already
uses three instructions earlier for the cost line at `0x00808393`
(`UpgradeTemplate::calcCostToBuild`, `0x0066F2C8`).

**The `* 5` is the frame rate, not an anomaly.** Both arms of `0x0066F1A8` end in
`BuildTime * [0x00D9F608]`, and §1.4 is what that constant is: the logic frame rate. `BuildTime` is
in **seconds** here — a plain `Real` parsed by `0x0042ED00`, no unit conversion — so multiplying by
frames-per-second is exactly the conversion to frames, and an `Upgrade` block's `BuildTime = 30`
really is thirty seconds. It looked like a discrepancy only against the assumption that the rate
was 30.

Worth stating beside it, because the three fields this patch reads are **not** in the same units in
INI: `SpecialPower.ReloadTime` is **milliseconds** (parsed by the duration function at
`0x0073A429`, which multiplies by `logic/1000`), while `Object.BuildTime` and `Upgrade.BuildTime`
are **seconds**. All three are frames by the time they are stored, so the patch never sees the
difference — but a modder reading these lines does.

The first arm (`0x0066F1B4`, taken when `0x006AA61B` on the player answers 3) folds in a handicap
read from `[0x00DE4938] + 0x960`. Nothing to do; it is inside the call.

**Skip the line when the player already owns the upgrade.** The description builder's own test is
`Player::hasUpgradeComplete` (`0x006AC2AF`, called at `0x0080816E` with the button's
`CommandButton+0x24`), and its result is cached in the frame byte at `ebp-0x0d`. Re-asking is one
call and does not depend on which path reached the hook, so re-ask. A researched upgrade already
takes the early exit at `0x0080838A` and shows no cost line; showing it a research time would be
worse than showing it nothing.

### 3.4 Heroes — named, not covered

A `REVIVE` button's ThingTemplate would answer `0x0073C39E` happily, and the answer would be wrong.
A hero's time comes from the player's hero ledger at `Player+0x758`: `0x008A04DA`'s kind-3 arm calls
`0x00780B72`, which reaches `0x00780687`, which starts from `calcTimeToBuild` at `0x007806DF` and
then applies the `ProductionModifier`'s **hero** time multiplier (vtable slot `+0x74`, selected by
the ledger entry's revive-versus-purchase bool at `+0xB0`). Reaching the ledger entry from a button
means resolving the hero id first, which is a different lookup than any of the three above.

Out of scope, and cheap to keep out — **using the engine's own test rather than a GUI-command
list**. `0x0080774E`, the routine the builder calls to decide whether this button describes a hero
at all, opens with `test byte [template+0x11f], 0x40` and answers no when it is clear. The unit arm
asks the same question of the same byte and declines. That is better than enumerating revive
commands for two reasons: it is the question actually being asked, and if the bit turns out to mean
something narrower than "hero", the failure is a **missing** line rather than a wrong number.

It is the obvious second patch, and
[`construction-speed-modifiers.md`](construction-speed-modifiers.md) §2.2 is the standing warning
about assuming the hero path works like the other two.

## 4. Remaining, for a thing in a queue

The same distinction the ability line makes — full when idle, time left when running — has an
exact analogue for production, and the builder already reaches half of it: at `0x00807E15` it calls
`Object::getProductionUpdateInterface` (`0x0068C327`, `__thiscall`, one `Bool` argument, pass `0`)
and, when the interface reports a queue length of `0x14`, appends the queue-full message to the
description with `L"\n\n"`. That is both the finder and the precedent.

The queue itself:

| field | what |
|---|---|
| `module+0x08` | the head entry |
| `module+0x14` | the entry count (interface slot `+0x44`, `0x009F9F37`; `0x14` is full) |
| `entry+0x04` | kind: 1 unit, 2 upgrade, 3 hero |
| `entry+0x08` | the `ThingTemplate` |
| `entry+0x0c` | the `UpgradeTemplate` |
| `entry+0x10` | the production id |
| `entry+0x1c` | accrued progress, in scaled frames |
| `entry+0x48` | the next entry |

so "is this button's thing in the queue" is a walk of at most 20 nodes comparing one pointer, and
its total is `0x008A04DA(entry)`. Remaining wall-clock frames are
`(total - progress) / multiplier`, where the multiplier is the same `PRODUCTION` factor the accrual
applies per frame at `0x008A1ED6` — the progress field counts **scaled** frames, which is exactly
the subtlety [`recharge-rescale.md`](recharge-rescale.md) §3.2 works through for cooldowns.

**Scoped, not built.** Not because it is hard — every field above is pinned — but because it is the
only part of this design with a genuine question rather than an address to find: with several of
the same unit queued, "remaining" is ambiguous, and answering for the head entry only is a decision
a player has to be able to read off the string. The full build time, the part that is unambiguous
and that every mod wants, does not wait on it. A button whose thing is already in the queue
therefore shows the full build time today, not the remainder.

## 5. Hook inventory

Both windows are six bytes and neither is a branch target; each becomes a `jmp rel32` plus one
`nop`, and each cave thunk reproduces the instructions it displaced before resuming.

| # | site | original bytes | what replaces it |
|---|---|---|---|
| 1 | `0x00807AF9` | `89 7d c4 8b 4e 0c` | `jmp <capture>`; reproduces both instructions, copies the button into the cave, resumes at `0x00807AFF` |
| 2 | `0x008086AE` | `8b 0d 70 4a de 00` | `jmp <tail>`; `pushad`, emits the line, `popad`, reproduces the `mov`, resumes at `0x008086B4` |

As built, measured from the assembled cave rather than estimated:

| block | bytes |
|---|---|
| the button stash and the four localization keys | 0x58 |
| `capture` and `tail` thunks | 0x23 |
| dispatcher on the button's three template fields | 0x2A |
| ability arm — owner resolution, the `m` transcription, both flavours of the remaining lookup | 0x16D |
| upgrade arm | 0x39 |
| unit arm | 0x53 |
| shared emitter — zero guard, fetch with `exists`, separator guard, format into a temporary, concat, release | 0x9C |
| **total** | **819** |

One `0x1000` section via `allocate_section`, as every other patch here does — `MEM_WRITE` as well
as executable, for the one dword §1.2a explains.

**The cave keeps the builder's `ebp`.** It needs `[ebp-0x18]`, `[ebp-0x1c]` and `[ebp-0x20]`, so it
cannot build a frame of its own the way `startPowerRecharge` does with `[ebp-4]`/`[ebp-8]`/
`[ebp-0xc]`. Scratch is `esp`-relative. This is the one place the transcription in §3.1 has to be
edited rather than copied.

## 6. Silent unless the mod declares the string

`TheGameText`'s fetch at vtable slot `+0x44` takes `(label, exists)`, and every one of the twelve
stock call sites passes `0` for the second. Passing a real `Bool *` — one dword of cave-local stack
— and dropping the whole line when it comes back false gives the patch a property worth more than
the feature:

**on a mod that has not added the keys, the tooltip is byte-identical to a stock build.** No
`MISSING:'TOOLTIP:Cooldown'` in the description, no stray separator, no reflow. A modder opts in per
line by adding a string, and can ship cooldowns without build times or the reverse.

The keys, **one `%d` each** — the duration in whole seconds:

| key | when |
|---|---|
| `TOOLTIP:Cooldown` | a special-power button whose power is ready |
| `TOOLTIP:CooldownRemaining` | …and while it is recharging |
| `TOOLTIP:BuildTime` | a button with a `ThingTemplate` |
| `TOOLTIP:ResearchTime` | an upgrade button the player does not already own |
| `TOOLTIP:BuildTimeRemaining` / `TOOLTIP:ResearchTimeRemaining` | not built — the queue walk of §4 |

Each key is fetched and tested independently, so a mod can declare `TOOLTIP:Cooldown` without
`TOOLTIP:CooldownRemaining` and get a line only while the power is ready. There is deliberately no
fallback from `…Remaining` to the plain key: the two say different things, and silently printing
"Cooldown: 12" for a power that is *twelve seconds from ready* is the one wrong-number failure
this design otherwise cannot produce.

## 7. What follows for free

- **No `.apt` and no ControlBar work.** The line joins a `UnicodeString` the record already
  carries; the movie is handed the same five strings it always was.
- **No `.csf` requirement on the engine's side.** The keys are the mod's, and their absence is the
  off switch (§6).
- **Overrides.** Both `calcTimeToBuild` functions and the recharge transcription reach their
  templates the way the engine does, `getFinalOverride` included, so a `map.ini` override is
  reflected without any extra work.
- **`hero-mana` composes.** It edits `0x008085C4` and `0x00808675`, both before this patch's window
  and disjoint from it, and it appends to the same description slot — which composes by
  construction, the same way it composes with `upgrade-description`.
- **`upgrade-description` composes**, and the two are complementary: it keeps a researched
  upgrade's `DescriptLabel` visible, and this patch declines to add a research time underneath it.

## 8. Out of scope, named

- **Hero revive and recruit timings** (§3.4).
- **`SharedSyncedTimer = Yes` powers** (three templates in the shipped INI, none of them a
  spellbook spell): their cooldown is a `Player`-side list node, and the remaining readout falls
  back to the full duration for them rather than reading a module field they never wrote (§3.1.2).
- **A recharge that is currently paused**: same fall-back, because its ready frame has not been
  moved forward yet (§3.1).
- **Weapon reload, `LifetimeUpdate` durations, and every other timer that is not on a button.**
- **Making anything faster.** Every number here is read-only. The mechanisms that would *change*
  them are separate, already-scoped patches: [`recharge-rescale.md`](recharge-rescale.md) for a
  cooldown that responds to a modifier arriving mid-cooldown, and `production-split` for build
  speed. This patch is the readout those two would make legible, and it is independent of both.
- **A remaining cooldown that ticks.** It is a snapshot taken when the tooltip was built (§2).

## 9. Cost, risk and what it changes

| | |
|---|---|
| edits to `.text` | 2 six-byte windows |
| new sections | 1 (826 bytes) |
| INI surface | **none** — no keyword, no `.sagepatch` entry, no `sage_ini` change |
| structures | none grow; no ctor, dtor or xfer change |
| effort | built in a day; the refresh and the queue walk are half a day each, if wanted |
| risk | low |

**Determinism.** The whole edit is inside the tooltip builder and the tooltip's display gate. Both
run on hover, on one client. No `GameMessage` is emitted, no logic-side state is written, and every
value read — `readyFrame`, the modifier multipliers, the queue progress — is read the same way the
UI already reads the recharge clock. A patched and an unpatched client can play each other and
replays cross: the same rule as `upgrade-description`, `replay-outcome` and `observer-switch`, and
unlike `production-condition`.

**The one thing to watch is not correctness but reentrancy of a different kind.**
`getModifierMultiplier` reaches the modifier holder through `0x0068C4A6`, which is a module lookup
by name key — a second walk of the object's module list — and the ability arm now performs that
walk on every hover. That is trivial next to what the tooltip already does, but it is the only part
of this patch that touches the logic-side object graph at all, and it must be read-only.

**Conflicts.** Nothing in the current `PATCHES` registry touches `0x008086AE` or `0x008078D4`.
`upgrade-description` edits `0x00808371` and optionally `0x0080830C`; `hero-mana` edits
`0x008085C4` and `0x00808675`. All four are inside the same function and none intersects the
window here.

**Verification.** A `sage-patch verify` pass should assert the untouched cast-time arithmetic at
`0x00896EBA` (`8b 40 18 c1 e8 05 a8 01`) and the `ReloadTime` read at `0x00896EE3`, the two
`calcTimeToBuild` entry points, `0x0068C26D`'s match on interface slot `+0x00`, the prologues of
both `startPowerRecharge` flavours out to the `mov edi, [esi-N]` that distinguishes them, both
`isReady` field-read windows (`0x00896CD4` and `0x0099139E`, which pin the pause count and the
ready frame of one flavour each), the spellbook finder and `forEachTeamObject`, and the twelve-site
line idiom's cleanup constants — `0xC` for one dword vararg at `0x008083C4` and `0x10` for the `double` at `0x00677E7E`.
If any of those moved, the transcription is not this build's.

## 10. What a live test has to settle

1. **That the line lands where it is supposed to** — under the description, under
   `upgrade-description`'s "already researched" line, under `hero-mana`'s `ManaCost` line, with no
   leading blank line on a button that carries no `DescriptLabel`.
2. **That an absent key produces no line**, on a stock string table (§6).
3. **The cooldown reduction actually shows.** Hover a hero's ability with no aura, note the
   number; walk a `RECHARGE_TIME` leadership into range and hover again. The two must differ by the
   modifier, and the second must match what the ability then really takes.
4. **The remaining readout on arrival**, timed against a stopwatch, and confirmed frozen without
   a refresh hook — that is the documented behaviour, not a bug, and it should be seen once,
   because it is what decides whether §2(b) is worth building.
5. **Whether a forced repaint flickers, re-fades or repositions the tooltip** (§2) — the one claim
   in this document that a disassembler cannot support at all, and the reason §2(b) is not built.
6. **A stopwatch against all three lines**, which is the single most valuable check here: §1.4's
   frame rate is derived from the constant block and corroborated by the replay corpus, but it is
   the one number a factor-of-six error hides in, and the only way to see such an error is to time
   an ability and an upgrade against what the tooltip claimed.
7. **A structure placement button**, confirming the number matches the construction the
   `DozerAIUpdate` state machine then runs.
8. **A spellbook button with nothing selected, and again with an unrelated unit selected**, which
   is the §3.1.2 walk: both must print the same number, and it must count down after a cast.
9. **A hero revive button prints no line**, which is §3.4 being kept out rather than being wrong.
10. **A `WeaponModeSpecialPowerUpdate` ability counts down** — Pippin's *Neugier des Narren* is the
    case that produced §3.1.1 — and a **passive ability prints no line at all**, which is §3.1.3.
    Those two are the fixes this document's second pass exists for, so they are the two a live run
    has to see.

## Appendix — every address this document depends on

| VA | meaning |
|---|---|
| `0x0042ED00` | `INI::parseReal` — the parser both `BuildTime` rows name |
| `0x0047D8B0` | the tooltip record's destructor |
| `0x00405183` | `UnicodeString::concat(const WideChar *)` |
| `0x004065FE` | `UnicodeString::concat(const UnicodeString &)` |
| `0x0066F1A8` | **`UpgradeTemplate::calcTimeToBuild(Player *, Object *)`** — frames, `ret 8` |
| `0x0066F2C8` | `UpgradeTemplate::calcCostToBuild` — the cost line's call, the shape to copy |
| `0x00677E5A`..`0x00677E7E` | `CONTROLBAR:UnderConstructionDesc` — the `double` vararg idiom, cleanup `0x10` |
| `0x0068B678` | `Object::getControllingPlayer` |
| `0x0068C26D` | **`Object::getSpecialPowerModule(SpecialPowerTemplate *)`** — `ret 4`, NULL if absent |
| `0x0068C327` | `Object::getProductionUpdateInterface(Bool)` — `ret 4`; the builder calls it at `0x00807E15` |
| `0x0068C363` | the production-interface finder `calcTimeToBuild` uses for the time multiplier |
| `0x0068C4A6` | `Object::getModifierHolder` — a module lookup by name key, not a field |
| `0x0068C82D` | `Object::getModifierMultiplier(type, out, ctx, flag)` — `ret 0x10`, clobbers `ecx` |
| `0x00688D3C` | `Overridable::getFinalOverride` |
| `0x006AAAD2` | `fld [Player+0x718]` — the spell-recharge discount |
| `0x006AA61B` | the player query `UpgradeTemplate::calcTimeToBuild` compares against 3 |
| `0x006AC2AF` | `Player::hasUpgradeComplete` |
| `0x006AD1B0` / `0x006AD26F` | `Player::startSharedSyncedTimer` / its reader (`Player+0x724`) |
| `0x006AF484` | the player's per-template production bonus, applied as `1 + bonus` |
| `0x006D4728` | hands the finished tooltip record to the movie |
| `0x0073C25F` | `ThingTemplate::calcCostToBuild(Player *, Object *, Int)` — the cost line's call |
| `0x0073C39E` | **`ThingTemplate::calcTimeToBuild(Player *, Object *, Int)`** — frames |
| `0x0073C409`..`0x0073C41A` | the producer's `ProductionModifier` time multiplier, slot `+0x6C` |
| `0x0075CECD` | `CommandButton::getDescriptLabel` |
| `0x0075D1DC` | **`CommandButton::getThingTemplate`** — how the late hook re-resolves it |
| `0x00780687` / `0x00780B72` | the hero ledger's build time (§3.4) |
| `0x007B19BF` | the player's build-time handicap table lookup (`Player+0x3C`) |
| `0x00807676` | shows the tooltip — the **only** caller of the description builder |
| `0x00807848` | installs a tooltip request; holds the once-per-hover latch |
| `0x008075A3` | the request equality test |
| `0x008078CA` / `0x008078D4` | the latch read and the `jne` a refresh hook would replace (§2b) |
| `0x00807960` / `0x00807971` | the latch's only clear and only set |
| `0x00807A00` / `0x00807A81` | the tooltip functor's two-argument entry / the description builder |
| `0x00807AC6` / `0x00807AF1` | where `ebp-0x1c` (Object) and `ebp-0x20` (Player) are filled |
| `0x00807B1D` / `0x00807B26` | where `ebp-0x4c` (ThingTemplate) and `ebp-0x24` (UpgradeTemplate) are filled |
| `0x00807E15`..`0x00807E36` | the engine appending to the description at `ebp-0x18` with `L"\n\n"` |
| `0x00807F2D`..`0x00807F37` | the unit cost call — the five instructions §3.2 reuses |
| `0x008080AE` / `0x008080FB` | the two folds whose separator guard the cave copies |
| `0x0080816E` | the `hasUpgradeComplete` test, cached at `ebp-0x0d` |
| `0x00808393`..`0x00808399` | the upgrade cost call |
| `0x008083AF`..`0x008083C4` | the shared line-format block, cleanup `0xC` |
| `0x00808675` / `0x0080867A` | the special-power case guard (`hero-mana`'s window) and its body |
| `0x008086AA` / `0x008086AB` | the convergence point, and the branch target just past it |
| **`0x00807AF9`** | **hook 1**, the capture — `89 7d c4 8b 4e 0c`, not a branch target |
| `0x00807AFF` | its resume point, the builder's own null-button test |
| **`0x008086AE`** | **hook 2**, the emit — `8b 0d 70 4a de 00`, not a branch target |
| `0x008086B4` | the resume point |
| `0x008086E5` | the record's constructor, taking all five strings |
| `0x00896CF2` | `getPercentReady` — deliberately not used |
| `0x00896C72` | flavour-1 `isReady` — its field reads at `0x00896CD4` are the layout anchor |
| `0x00896E31` | `startPowerRecharge`, flavour 1 — 23 vtables, the flavour constant |
| `0x00896E71` | the `SharedSyncedTimer` divert (`tmpl+0x59`) |
| `0x00896E87`..`0x00896F03` | the cast-time multiplier arithmetic §3.1 transcribes |
| `0x008969D1` | interface slot `+0x00` — the template match `getSpecialPowerModule` uses |
| `0x0099135D` | flavour-2 `isReady` — its field reads at `0x0099139E` are the layout anchor |
| `0x00991500` | `startPowerRecharge`, flavour 2 — ready frame at `+0x04`, pause count at `+0x08` |
| `0x006AAE3C` | the `KINDOF SPELL_BOOK` predicate, `cdecl (Object *, ctx)` |
| `0x006ABABD` | `Player::forEachTeamObject(fn, ctx)` — thiscall, `ret 8`, pure |
| `0x006AD0F8` | `Player::getSpellBookObject` — **not called**, it memoises into `Player+0x710` |
| `0x0075CCC5` | `CommandButton::getPercentReady` — the button clock, same first-module rule |
| `0x009F9F37` | production interface slot `+0x44` — the queue count at `module+0x14` |
| `0x008A04DA` | `ProductionUpdate::getTotalBuildTimeFrames(entry)` — branches on `entry+0x04` |
| `0x008A1ED6` | the queue's per-frame `PRODUCTION` accrual into `entry+0x1c` |
| `0x00A3CFA4` | `ftol` |
| `0x00ADF7E0` | the line idiom's formatter, `cdecl` — **replaces** its destination |
| `0x00437120` / `0x00436B20` | its worker, and the `set` that makes it a replace |
| `0x004065FE` / `0x004367B0` | `UnicodeString::concat` and `~UnicodeString` — the two-step |
| `0x00BD1908` / `0x00BD8698` | `1.0f` / the unsigned `fild` fixup constant |
| `0x00BDBC40` / `0x00C4F008` | `L"\n"` / `L"\n\n"` |
| `0x00C4EE08` | the tooltip functor vtable; the builder at slot `+0x0C` |
| `0x00C4EE20` / `0x00C4F028` | `"TOOLTIP:UnitCost"` / `"TOOLTIP:Cost"` |
| `0x00C64FF0` | flavour-1 `SpecialPowerModuleInterface` vtable |
| `0x00C67DB0` | the `ProductionUpdateInterface` vtable |
| `0x00644F11` | the frame-rate setter, which fills the whole derived block from two arguments |
| `0x00644FA6` | `mov [0x00D9F608], esi` — the instruction that makes that global **the logic rate** |
| `0x0073A429` | the duration parser `ReloadTime` names: milliseconds in, logic frames out |
| `0x00D9F608` / `0x00D9F60C` | the logic rate (**5**) and the client rate (30), both written at init |
| `0x00D9F610` / `0x00D9F614` / `0x00D9F61C` | `0.005`, `200`, `0.2` — three more statements of the same 5 |
| `0x00DE412C` | `TheGameLogic` — frame at `+0x40` |
| `0x00DE4830` / `0x00DE4928` / `0x00DE4B04` | `TheInGameUI` / `ThePlayerList` / `TheGameText` |
| `0x00DE8998` / `0x00DE899C` | the tooltip-displayed latch and its tick stamp |
| `ThingTemplate+0x4EC` / `UpgradeTemplate+0x30` | the two `BuildTime` fields |
| `SpecialPowerTemplate+0x18` / `+0x20` / `+0x59` | `Flags` / `ReloadTime` / `SharedSyncedTimer` |
