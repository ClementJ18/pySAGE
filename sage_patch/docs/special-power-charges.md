# Giving a special power charges

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); file offset is
`VA - 0x400000` for everything cited here. Read **statically** on 2026-08-20 from
`sage_patch/engine/game.dat.backup`
(11,346,432 bytes) with `pefile` + `capstone` - the clean reference, not the repo-root `game.dat`,
which carries eleven modifications. **Nothing below has been observed in a running game.**

**The ask.** A power that can be cast several times in quick succession and then has to wait. Three
new keys on the `SpecialPower` block:

```
SpecialPower ArnorLeadership
  ReloadTime                     = 120000     ; unchanged keyword: time to regain ONE charge
  ChargeNumber                   = 3          ; how many casts are banked
  ReloadTimeBetweenCharge        = 15000      ; the short cooldown between two banked casts
  ReplenishAllChargesOnReloadTime = No        ; Yes: one ReloadTime refills the whole bank
End
```

`ReloadTime` keeps its name and its units (milliseconds) and changes meaning only for a power that
declares `ChargeNumber`: it becomes the refill period, and **the refill clock starts the moment the
first charge goes missing**, not when the bank empties. Plus a tooltip line saying how many charges
are left and how long until the next one lands.

**Verdict up front: this is cheaper than it looks, and the reason is that the engine's cooldown is
an absolute frame rather than a countdown.** Nothing in the engine ticks a special power while it
recharges - `readyFrame` is written once and compared against `TheGameLogic`'s frame on demand
([`recharge-rescale.md`](recharge-rescale.md) §2). So a charge bank does not need a per-frame driver
either: the refill deadline is a second absolute frame, the charge count is recovered from it by
integer division at the only two moments anyone asks, and **`isReady`, the AI's gate, the click
executor and the button's pie clock all keep working untouched** because everything about "can I
cast this" is still expressed in `readyFrame`. That is the whole design, and it is what separates
this from `recharge-rescale`, which needs a sweep over every object every frame.

- **Cost:** 1 hook (5 bytes) inside `startPowerRecharge`, 2 single-bit opcode widenings, 3 same-length
  `imm32` bumps, 2 six-byte windows on the template ctor and its `copyFrom`, one relocated field
  table (2 `imm32` repoints), and ~600 bytes of cave. Plus the tooltip line: 1 six-byte window and
  ~250 bytes more. Three new INI keys, one `.sagepatch` entry.
- **Risk:** medium. Nothing here can crash on its own - the failure modes are a wrong charge count
  and a power that never comes back - but the patch grows `SpecialPowerTemplate`, which is the one
  move in it that is not locally reversible if a fourth allocation site exists somewhere this scan
  missed. §1.2 is the evidence that it does not.
- **Status: implemented as `special-power-charges`**
  ([`../patches/special_power_charges.py`](../patches/special_power_charges.py)). It applies to and
  verifies against both real binaries, round-trips through `detect`, and composes in either order
  with `cooldown-through-death`.
- **It has been in a running game once, and that run rewrote §4.** The first build hooked
  `startPowerRecharge` itself; one cast emptied the whole bank, and a cooldown reset handed back
  the cast without the charge. Both are the same mistake and §4.1 is what it was.

## TL;DR

- **The three keys cost nine bytes of template, and `SpecialPowerTemplate` has two.** It is `0x88`
  bytes with `+0x5A`/`+0x5B` its only interior padding, and
  [`cooldown-through-death`](cooldown-through-death.md) §2 already spends both. So the struct grows
  to `0x94`. That is three `push 0x88` sites, all `68 88 00 00 00` and therefore **same-length**
  edits, and they are all three of the callers of its constructor. §1.2.
- **The per-module state costs six bytes and the module has exactly six free.** `charges spent` is a
  byte at interface `+0x21`, the refill deadline is a **24-bit absolute frame** at `+0x19..+0x1B`,
  and both sit in padding that is neither read nor `Xfer`'d today. Two `88` → `89` opcode
  widenings in the base constructor zero them. §2.
- **A 24-bit frame is not a compromise.** The logic rate is **5 fps**, not the 30 sitting four
  bytes above it in `0x00D9F608`'s block, so `16,777,216` frames is over **900 hours**; the wrap is
  further away than the game is playable, and `0` doubles as "no refill cycle running" because a
  deadline is always `now + interval` with `interval >= 1`.
- **There is no per-frame driver, and that is the finding.** Charges are recovered lazily -
  `granted = 1 + (now - deadline) / interval` - at the two places that consume them: the cast
  (logic side, mutating) and the tooltip (client side, read-only). Both derive the same answer from
  the same stored frames, so no peer has to run the derivation for another peer's answer to be
  right. §3.3.
- **`isReady` is not patched.** With charges left, `readyFrame` holds the short cooldown; with the
  bank empty, `readyFrame` is set **to the refill deadline**, so the power is unavailable until the
  charge that unblocks it lands. One field expresses both rules, which is why nothing downstream -
  `ControlBar::getCommandAvailability`, the click executor, the AI - needs to learn about charges.
  §3.2.
- **The pie clock follows for free.** `getPercentReady` is `1 - (readyFrame - now) / duration` and
  the hook writes both fields together, the way `startPowerRecharge` does. So the button fills over
  the short cooldown while charges remain and over the refill while it is empty, with no UI work.
- **One hook, and it discriminates on the caller.** `startPowerRecharge` arms a cooldown from
  **fourteen** sites, so hooking it plainly spends a charge at all fourteen - one cast emptied the
  bank. But the one call that *looks* like the cast, `doSpecialPower`'s own at `0x008979C2`, is
  skipped entirely for any module with `UpdateModuleStartsAttack = Yes`, which is how most
  targeted hero abilities in Edain are written. So the hook is back in `startPowerRecharge` and
  reads the **return address** at `[ebp+4]`, excluding the two arms that are provably not a use:
  the module constructor and the `OnTriggerRecharge` walk. §4.
- **No float on the simulation path.** `edi` already holds `max(1, ftol(ReloadTime * m))` - the
  engine's own refill interval - so `short` is `ReloadTimeBetweenCharge` scaled by the same ratio
  in integers. §4.3.
- **A cooldown reset hands back a charge**, without hooking anything that resets one. An empty
  bank holds `readyFrame` at the refill deadline, so a `readyFrame` in the past while the deadline
  is still ahead means somebody else cleared it - and the fold treats that as a refill landing
  early. §3.1.
- **The tooltip line is `description-timers` with a different number in it.** Same
  `Object::getSpecialPowerModule` lookup, same flavour check, same silent-unless-declared string
  fetch, same seconds formatter - it is a fourth key in the same table, and its natural home is the
  special-power case at `0x00808675` rather than the tail `description-timers` already owns. §5.
- **Spellbook powers are covered.** A spellbook is an ordinary `Object` (`GoodSpellBook`,
  `EvilSpellBook` and a `ChildObject` per faction) carrying ordinary `SpecialPowerModule` /
  `OCLSpecialPower` / `PlayerUpgradeSpecialPower` behaviours, and all three allocate `0x34` and run
  the base constructor at `0x008973EE` - so they have the padding §2 spends and take the hook in §4.
  The `SharedSyncedTimer` diversion applies to **three templates in the whole game**, none of them a
  spellbook spell. §6.1.
- **This is simulation state.** Charges gate whether a power fires, so every peer needs the patched
  binary and replays do not cross.

## 1. The INI surface

### 1.1 What the block looks like today

`SpecialPower`'s field table is 24 entries at `0x00DA5FD8`, terminated at `0x00DA6158`, and the two
entries that matter here are:

| offset | field | parse fn |
|---|---|---|
| `0x18` | `Flags` | `0x0042E840` (name table at `0x00DA5F34`) |
| `0x20` | **`ReloadTime`** | `0x0073A429` |
| `0x58` | `PublicTimer` | `0x0042E558` |
| `0x59` | `SharedSyncedTimer` | `0x0042E558` |
| `0x5A`, `0x5B` | interior padding - **spent by `cooldown-through-death`** | |
| `0x80` | `UnitCost` | `0x0042EC5E` |
| `0x84` | `UnitCostDeathType` | `0x0042EC5E` |

`0x0073A429` is the one worth naming, because two of the three new keys want it verbatim: it reads
an `Int`, multiplies by `[0x00D9F610]` (frames per millisecond, written at runtime from the logic
rate) and `ftol`s the product into the field. So at 5 fps `ReloadTime = 120000` is stored as `600`
frames,
and `ReloadTimeBetweenCharge` written the same way is **milliseconds in INI, frames in the struct**,
which is what makes §4's arithmetic a copy of `startPowerRecharge`'s rather than a conversion.

The three rows to append:

```
{ "ChargeNumber",                    0x0042EC5E, 0, 0x88 }   ; INI::parseInt
{ "ReloadTimeBetweenCharge",         0x0073A429, 0, 0x8C }   ; the ReloadTime parser
{ "ReplenishAllChargesOnReloadTime", 0x0042E558, 0, 0x90 }   ; INI::parseBool
```

All three parse functions are already in this table, so `Yes`/`No` handling, the error messages and
`map.ini` overrides come for free. The table itself relocates to the cave the way four other patches
already relocate theirs - `resolve_table` in
[`../patches/utils/field_tables.py`](../patches/utils/field_tables.py) finds whatever is live rather
than assuming the stock base, so this composes with anything that extended it first. Two `imm32`
references, and **there is no interior reference**:

| site | bytes | what |
|---|---|---|
| `0x007B1ABE` | `b8 d8 5f da 00` | `getFieldParse` |
| `0x007B2325` | `68 d8 5f da 00` | pushed into `INI::initFromINI` (`0x0042DB80`) |

### 1.2 The template has to grow, and growth is three same-length edits

There is no room to avoid it. `SpecialPowerTemplate` is `0x88` bytes and packed solid: the
constructor at `0x007B1F5B` accounts for every dword from `+0x00` to `+0x87`, the `+0x64..+0x73`
gap between `PreventActivationConditions` and `MaxCastRange` is a 16-byte subobject constructed at
`0x007B1FEC` (and copied as four `movsd` at `0x007B1F24`), and the only interior padding -
`+0x5A`/`+0x5B` - is already claimed. Nine bytes have to come from the end.

**The allocation is three sites, and all three are found the same way**: scanning `.text` for
`call rel32` reaching the constructor `0x007B1F5B` returns `0x007B21A8`, `0x007B21F2` and
`0x007B22AA`, and each is preceded by a `push 0x88` encoded as `68 88 00 00 00` at `0x007B218E`,
`0x007B21DA` and `0x007B2292`. That is a closed set: a fourth allocation would have to construct
the object some other way, and nothing else calls the constructor. `push imm32` means `0x94` costs
the same five bytes as `0x88`, so all three are in-place immediate rewrites.

Nothing copies a template by size. `copyFrom` (`0x007B1E6C`, three callers: `0x007B21C3`,
`0x007B222C`, `0x007B22E4`) is field-by-field, and the store the parser registers into
(`TheSpecialPowerStore` at `0x00DE878C`, `+0x0C`) takes a **pointer** per template
(`0x007B2317` pushes the address of a local holding one). So growth touches nothing but the three
literals.

### 1.3 Zeroing and inheriting: two six-byte windows

New fields must start at zero on data that never names them, and must survive
`DefaultSpecialPower` and `map.ini` overrides. Both are the same shape of edit:

| what | window | bytes | the cave does |
|---|---|---|---|
| ctor | `0x007B200D` | `89 9e 84 00 00 00` (`mov [esi+0x84], ebx`) | the stock store, then `+0x88`/`+0x8C`/`+0x90` = 0 |
| `copyFrom` | `0x007B1F53` | `8b c3 5e 5d 5b c2 04 00` (its whole epilogue) | three dwords from `ebp+0x88..` to `ebx+0x88..`, **then** the epilogue |

The `copyFrom` half takes the epilogue rather than the `+0x84` store one instruction earlier -
`addresses.py` already names it as `SPECIAL_POWER_TEMPLATE_COPY_TAIL` for `hero-mana`, which grows
the same struct - and the copies go **before** the displaced bytes there, because those bytes end
in `ret 4`. In both windows the register holding the object (`esi` in the ctor, `ebx` the
destination and `ebp` the *source* in `copyFrom`) is live. Note that unlike
`cooldown-through-death`, where the `copyFrom` half was optional politeness, here it is **required**:
all three `copyFrom` callers are on the override path, so a template overridden by a `map.ini`
without it would silently lose its charges.

## 2. Where the charge state lives

### 2.1 The module's own six free bytes

`SpecialPowerModuleInterface` is the subobject at module `+0x10`;
[`recharge-rescale.md`](recharge-rescale.md) §1.1 maps it and this scope corrects it in two places,
both read out of the constructor at `0x008973EE` and the `Xfer` at `0x0089679D`:

| interface | module | field | zeroed by ctor | `Xfer`'d |
|---|---|---|---|---|
| `+0x00` | `+0x10` | vptr `0x00C64FF0` | `0x00897430` | - |
| `+0x04` | `+0x14` | **duration** | `0x00897436` | yes (v>=2) |
| `+0x08` | `+0x18` | **readyFrame** | `0x00897439` | yes |
| `+0x0C` | `+0x1C` | pause count | `0x0089743C` | yes |
| `+0x10` | `+0x20` | frame the pause began | `0x0089743F` | yes |
| `+0x14` | `+0x24` | percent captured at the pause | `0x00897442` | yes |
| `+0x18` | `+0x28` | cleared at the end of every recharge | `0x00897447` (**byte**) | yes |
| `+0x19..+0x1B` | `+0x29..+0x2B` | **free - 3 bytes** | no | no |
| `+0x1C` | `+0x2C` | an **ObjectID** - *not* free | `0x0089744A` | yes, via `0x00707887` |
| `+0x20` | `+0x30` | the "held" latch | `0x0089744D` (**byte**) | yes (v>=3) |
| `+0x21..+0x23` | `+0x31..+0x33` | **free - 3 bytes** | no | no |

Two corrections worth carrying back into `recharge-rescale.md`: the constructor does *not* stop at
`+0x18` - it writes `+0x1C` and `+0x20` as well, at `0x0089744A` and `0x0089744D` - and `+0x1C` is
**not** an unused dword. `Xfer` hands it to `0x00707887` at `0x0089680E`, and that helper pushes the literal
`"ObjectID"` (`0x00C1E18C`) and a size of 4 into the xfer vtable's `+0x94` slot - so `+0x1C` holds
an object reference and this patch must not touch it.

`sizeof` is `0x34` (`SpecialPowerTimerRefreshSpecialPower`'s factory does `push 0x34` /
`call operator new` at `0x0065488F` and adds no fields of its own), so `+0x31..+0x33` is tail padding inside every derived module: the 23 flavours
that share this base all place their own fields at `0x34` and above.

### 2.2 The layout, and one bit per byte of it

```
module +0x29 .. +0x2B   refillDeadline   24-bit absolute logic frame, 0 = no cycle running
module +0x31            chargesSpent     byte, 0 .. ChargeNumber
```

Six free bytes, five used, one left over. Zeroing costs two edits of the kind this repo has made
twice before (`lifetime-fields`, `cooldown-through-death` §2.1) - widen a `mov byte` to a
`mov dword`, `88` → `89`, **same instruction length**:

```
00897447  88 5e 28   mov byte  [esi+0x28], bl   ->  89 5e 28   mov dword [esi+0x28], ebx
0089744d  88 5e 30   mov byte  [esi+0x30], bl   ->  89 5e 30   mov dword [esi+0x30], ebx
```

The first zeroes `+0x28..+0x2B`, which is the recharge flag plus the deadline; the second zeroes
`+0x30..+0x33`, which is the held latch plus the charge count. Both stay inside `sizeof`, both write
the same `bl`/`ebx` zero the surrounding stores use, and the widened byte keeps its stock value
because `ebx` is zero at both sites.

**Why 24 bits.** A dword deadline would need four contiguous free bytes and the module has two runs
of three. The logic rate is **5** frames per second (`0x00D9F608`; the 30 four bytes above it is
the client's, and [`description-timers.md`](description-timers.md) derives the pair in full), so
`0x00FFFFFF` frames is over 900 hours - past the point where the frame counter is the least of the
problems - and it buys `0` as the "no refill cycle" sentinel for free,
because a live deadline is always `now + interval` with `interval >= 1`.

### 2.3 What is deliberately not done: the `Xfer`

Neither field is in `Xfer`, so **a savegame does not carry charges**: a loaded game brings every
charge power back at a full bank with no refill cycle running, while `duration`/`readyFrame` reload
correctly and keep whatever cooldown was in flight. Adding them means a version bump on a function
whose version byte is already compared twice (`0x008967C3`, `0x00896818`), which breaks savegame
interchange with unpatched clients in both directions for a feature that is a skirmish-ability
mechanic. Same trade `cooldown-through-death` §4.3 takes, recorded for the same reason.

## 3. The design

### 3.1 The state machine

Write `N` for `ChargeNumber`, `spent` for the byte, `deadline` for the 24-bit frame, `interval` for
the refill period and `short` for the cooldown between banked casts. §4.3 is where the two come
from: `interval` is the `duration` the engine has just written, and `short` is
`ReloadTimeBetweenCharge` scaled by the same ratio.

**Refill, evaluated on demand at frame `now`, writing nothing:**

```
if deadline == 0 or spent == 0:            granted = 0
elif now >= deadline:                      granted = 1 + (now - deadline) / interval
elif spent == N and now >= readyFrame:     granted = 1, and the cycle restarts from now
else:                                      granted = 0

if ReplenishAllChargesOnReloadTime and granted:
                       spent' = 0;              deadline' = 0
elif granted >= spent: spent' = 0;              deadline' = 0
else:                  spent' = spent - granted; deadline' = deadline + granted * interval
```

**Cast, at the hook, after the refill above has been folded in:**

```
spent  = min(N, spent + 1)
if deadline == 0:  deadline = now + interval          ; "as soon as one charge is missing"
if spent < N:      readyFrame = now + short
else:              readyFrame = max(deadline, now + short)
duration = readyFrame - now
```

**The third refill arm is the "something restored this cooldown" case**, and it is the second thing
the live test taught. Every mechanism that clears a cooldown - a script action, `HeroDie`'s
recharge-by-dying, any of §4.1's other thirteen sites - writes `readyFrame` and knows nothing about
a bank. Left alone, a restore hands back the cast without the charge, and the bank drains one use
per restore, which is what a restoration ability did in the first run.

It is detectable without hooking any of them, because of what §3.2 does with `readyFrame`: a power
whose bank is **empty** holds `readyFrame` *at* its refill deadline. So `readyFrame` in the past
while the deadline is still ahead can only mean somebody else moved it, and the honest reading is
that the refill landed early. It cannot misfire on a power with charges left - there `readyFrame`
is an ordinary short cooldown, and the test requires `spent == N`.

Three properties fall out of writing it this way:

- **The refill clock is anchored to the first missing charge, not to the last cast.** `deadline` is
  only seeded when it is `0`, so casting again mid-cycle does not restart the wait. That is exactly
  what the request asks for, and it is one comparison.
- **`ReplenishAllChargesOnReloadTime` is not a second mechanism.** It is one branch on how `granted`
  is computed, and it leaves the deadline arithmetic alone: refilling the bank clears the cycle
  either way.
- **`max(deadline, now + short)` is the only clamp needed.** A power configured with
  `ReloadTimeBetweenCharge` longer than `ReloadTime` would otherwise become castable before its own
  short cooldown elapsed.
- **Nothing that clears a cooldown has to be hooked**, because the arm above notices after the
  fact. That is worth more than the bytes it saves: `setReadyFrame` has two callers today and a mod
  can reach it from a script, so a patch that tried to enumerate them would be wrong the first time
  somebody wrote a new one.

### 3.2 Why `isReady` needs no patch

`isReady` (`0x00896C72`) ends at

```
00896cd4  cmp  dword [esi+0xc], 0        ; not paused
00896cd8  jne  0x896cec
00896cda  mov  eax, [0xde412c]           ; TheGameLogic
00896cdf  mov  eax, [eax+0x40]           ;   .frame
00896ce2  cmp  eax, [esi+8]              ; >= readyFrame
```

and every consumer of "can this be cast" - `ControlBar::getCommandAvailability` (`0x00942733`),
both click arms (`0x009405B3`, `0x00940625`), the per-frame context update (`0x00943ADB`), the AI -
reaches the answer through that one comparison. Because §3.1 spends the bank by writing
`readyFrame`, the bank is enforced by code this patch never touches. The alternative design - a
charge counter consulted by a patched `isReady` - would have to be correct at seven call sites
instead of zero, and would still have to keep `readyFrame` consistent for the pie clock.

The pie is the same story. `getPercentReady` (`0x00896CF2`) is `1 - (readyFrame - now) / duration`
recomputed per call, and the hook writes `duration = readyFrame - now` alongside every `readyFrame`,
so the clock starts empty and fills over whichever wait is actually in force. Writing one without
the other is the artefact [`recharge-rescale.md`](recharge-rescale.md) §3.3 documents.

### 3.3 Why there is no sweep, and why lazy evaluation is not a desync

`recharge-rescale` needs a per-frame walk over `TheGameLogic+0xAC` because it is tracking a quantity
that changes continuously - a modifier that can arrive on any frame. A charge bank does not: it
changes at casts, which are ordered events every peer sees on the same frame, and at refills, whose
frames are **computable from stored state**. So nothing has to run on the frame a refill lands.

The one rule that makes this safe is that the derivation in §3.1 is a **pure function of
`(spent, deadline, interval, now)`** and is *idempotent under intermediate evaluation*: folding it
at frame 100 and again at 130 gives the same `(spent, deadline)` as folding it once at 130, because
`deadline` advances by whole multiples of `interval`. A client that hovers a button, and therefore
evaluates it locally, cannot drag its simulation state away from a peer that never hovered - and in
fact the tooltip does not write at all (§5), so the only writer is the cast.

**The one thing that breaks the identity is a moving `interval`.** `interval` is recomputed from
`ReloadTime * m` at each cast, and `m` folds in `RECHARGE_TIME` attribute modifiers and the
`SpellRechargeModifierUpgrade` player discount, both of which can change mid-cycle. Two casts
straddling an aura would then fold a cycle at two different intervals. This scope takes the simple
answer - **the interval in force is whatever the most recent cast computed**, and a cycle spanning a
modifier change is quantized at the boundary - because the alternative is storing the interval
alongside the deadline and there is exactly one free byte left. The error is bounded by one refill
period and only appears on powers that both have charges and live under a changing recharge
modifier. If that turns out to matter, the fix is the three bytes at `+0x32`: a 16-bit stored
interval, capped at 65535 frames.

## 4. The hook

### 4.1 Two mistakes this section is named after

**The first build hooked `startPowerRecharge` itself.** It applied, verified, and in a running game
one cast emptied the whole bank. The reason is not an assembly error: **`startPowerRecharge` means
"arm the cooldown", not "somebody used the power", and the engine arms cooldowns from fourteen
places.** A scan of `.text` for `fld1` reaching a call through interface slot `+0x3C`, plus the one
direct `call rel32`, returns:

| site | what it is |
|---|---|
| `0x00897471` | **the base module constructor** - a power declared to start on cooldown |
| `0x008979C2` | `doSpecialPower`, on its **own** interface |
| `0x00897A35` | `doSpecialPower`'s `OnTriggerRechargeSpecialPower` walk - a *different* power |
| `0x0068B953`, `0x006AE292`, `0x00853F41`, `0x0085476F` | |
| `0x0089636B`, `0x00896B6D`, `0x008984AC`, `0x008985DC` | the `SpecialAbilityUpdate` flavours |
| `0x008CC0FE`, `0x008CC5DC`, `0x008CCCE6` | `PlayerUpgradeSpecialPower` |

**The second build hooked `0x008979C2`** - the call `doSpecialPower` makes on its own interface,
which is *the* cast for a `SpecialPowerModule` that drives itself. It is not reached at all when
the module sets `UpdateModuleStartsAttack = Yes`, because that is `ModuleData+0xC`, which is the
byte in the engine's own guard three instructions earlier:

```
008979ae  8b 5f 04            mov ebx, [edi+4]          ; the ModuleData
008979b1  80 7b 0c 00         cmp byte [ebx+0xc], 0     ; UpdateModuleStartsAttack
008979b5  75 0e               jne 0x8979c5              ;   Yes -> not here; the update module
008979b7  8d 4f 10            lea ecx, [edi+0x10]
008979ba  d9 e8               fld1
008979bc  8b 01               mov eax, [ecx]
008979be  51                  push ecx
008979bf  d9 1c 24            fstp dword [esp]
008979c2  ff 50 3c            call [eax+0x3c]
```

That pairing is how most targeted hero abilities in Edain are written. Zaphragor's
`SpecialAbilityVerheerenderAngriff` is exactly it:

```
Behavior = SpecialPowerModule ModuleTag_VerheerenderAngriffSpecialPower
    SpecialPowerTemplate      = SpecialAbilityVerheerenderAngriff
    UpdateModuleStartsAttack  = Yes
End
Behavior = WeaponFireSpecialAbilityUpdate ModuleTag_VerheerenderAngriffUpdate
    SpecialPowerTemplate      = SpecialAbilityVerheerenderAngriff
```

so `doSpecialPower` never arms it, the `WeaponFireSpecialAbilityUpdate` does when the attack fires,
and charges did nothing at all.

**Both mistakes are the same mistake**, and it is worth naming because it is not about x86. A choke
point is only a choke point for the thing it is named after. `startPowerRecharge` is a genuine
single implementation of *set this cooldown* - 23 vtables share it - and `0x008979C2` is a genuine
*cast*. Neither is "a use of the power", because the engine deliberately routes that through one of
two modules depending on an INI flag.

### 4.2 Discriminating on the caller

The hook is back inside `startPowerRecharge`, at `0x00896F75` - the five bytes that open its
full-recharge arm - and it asks **who called**:

```
00896f75  a1 2c 41 de 00   mov eax, [0xde412c]   ; <- THE WINDOW, 5 bytes
00896f7a  8b 40 40         mov eax, [eax+0x40]   ; TheGameLogic.frame
00896f7d  03 c7            add eax, edi          ; + the computed frames
00896f7f  89 46 08         mov [esi+8], eax      ; readyFrame
  ...
00896f8b  89 46 04         mov [esi+4], eax      ; duration
00896f8e  c6 46 18 00      mov byte [esi+0x18], 0
```

`startPowerRecharge` opens `push ebp` / `mov ebp, esp`, so `[ebp+4]` is the return address for the
whole function. Two values mean "armed, but nobody used it":

| return address | the call | why it is not a use |
|---|---|---|
| `0x00897476` | `call 0x00896E31` at `0x00897471` | the base module constructor - before the match, for every power that starts on cooldown |
| `0x00897A38` | `call [eax+0x3c]` at `0x00897A35` | the `OnTriggerRecharge` walk - arms *another* power because this one was used |

Everything else is a use, whichever module flavour drove it, and this patch never has to learn
which. **That works because of what the function is:** it never *clears* a cooldown, it only ever
arms one, so "this power went on cooldown" is exactly the event the player watches the pie start
for. Both calls are anchored, so a build that moved either fails to apply rather than quietly
charging the constructor again.

`0x00896F75` is a `jbe` target, which a `jmp rel32` replacing the whole five-byte instruction is
fine to be, and the state there is everything the cave needs:

| register / slot | what |
|---|---|
| `esi` | the interface subobject (`module+0x10`) |
| `edi` | `max(1, ftol(ReloadTime * m))` - **already the refill interval** |
| `[ebp+4]` | the return address |

The exit: any arm that declines - either excluded caller, no template, `ChargeNumber <= 0` -
replays the displaced `mov eax, [0xde412c]` and jumps to `0x00896F7A`, so a power without charges
takes the stock path byte for byte. Charged powers write `readyFrame` and `duration` themselves and
rejoin at `0x00896F8E`, the `mov byte [esi+0x18], 0` every arm shares.

### 4.3 The arithmetic, in integers

The engine has just computed the number this patch needs. `edi` **is**
`max(1, ftol(ReloadTime * m))`, with whatever modifiers were in force - and that is exactly the
refill interval. So the cave takes it rather than recomputing it, and there is no second float
path:

```
interval = edi                                            ; the engine's own answer
short    = max(1, ReloadTimeBetweenCharge * interval / ReloadTime)
```

The short cooldown is the same ratio the engine applied to the long one, in integers, with the
standard pre-division overflow guard (`cmp edx, ecx` before the `div`, because a quotient that does
not fit raises #DE). **No float arithmetic on the simulation path at all**, which also disposes of
[`recharge-rescale.md`](recharge-rescale.md) §3.1.1's ULP question rather than answering it.

`SharedSyncedTimer` needs no test here: `startPowerRecharge` diverts those templates to the
`Player`-side timer at `0x00896E71` and returns long before this window.

The template comes back the way the stock code gets it twice already - `mov eax, [esi]` /
`call [eax+0x18]` (interface slot `+0x18` = `getSpecialPowerTemplate`, `0x008969CA`) then
`call 0x00688D3C` for the final override.

### 4.4 The partial arm is left alone

`startPowerRecharge` with an argument below `1.0` - the script engine's "advance this cooldown by a
fraction" - takes the other branch at `0x00896F14` and re-derives everything from
`getPercentReady`. A fraction of a charged cooldown is not a defined idea and this patch does not
invent one: partial recharges move `readyFrame` and leave the bank where it is, and §3.1's restore
rule is how the bank catches up afterwards.

## 5. The button readout

### 5.1 What surface there is

The tooltip is the only text a command button has. The per-frame context update at `0x00943ADB` does
maintain a per-button overlay record (fetched through `0x009A5E08`; setters at `0x00729F0C` for the
clock pair at `+0x04`/`+0x08`, `0x00729F40` for `+0x18`, `0x00729F6B` for `+0x14`, `0x00729FD2` for
`+0x20`, `0x00729F96` for `+0x24`), but every one of those setters stores an `Int`, a `Real` or a
flag - **there is no string member**, and no call in that function assigns a `UnicodeString` to a
button. So a live number *drawn on the cameo* is not a small patch, and it is not this one.

**One lead, recorded not claimed.** `PublicTimer` (template `+0x58`) gates a path at `0x00896BD9`
that tests a `KindOf` bit on the object's template (`+0x108 & 0x80`) and then calls interface slot
`+0x14` - the engine's own "show this power's countdown in the world" behaviour, which is exactly
the kind of readout that *does* tick. Whether it can carry a second number has not been read out,
and it is not on this patch's path.

### 5.2 The line, and where it goes

Everything needed already exists in [`description-timers.md`](description-timers.md), which fetches
a remaining cooldown out of exactly this module for exactly this kind of line. The additions:

- **Site.** `description-timers` owns the builder's tail (`0x008086AE`) because its line has to be
  last across five cases. A charges line applies to one case only, so it takes the special-power
  case instead: `DESCRIPTION_SPECIAL_POWER_CASE` at `0x00808675` (`83 f9 18 75 30`, the
  `cmp ecx, 0x18` / `jne` pair) with the stock `UnitCost` body at `0x0080867A` as the rejoin. The
  two patches then touch disjoint bytes. **`hero-mana` takes this same window** (`hero_mana.py:1357`)
  - the two are mutually exclusive as written, and composing them means one cave chaining into the
  other, which is a build decision rather than a scope one.
- **Reads.** `CommandButton+0x44` is the raw `SpecialPowerTemplate`; `[ebp-0x1c]` is the `Object`
  (may be null - no object, no line); `Object::getSpecialPowerModule` (`0x0068C26D`, `ret 4`) hands
  back the module; the flavour check is `[[module]+0x3c] == 0x00896E31`, the same guard
  `description_timers._emit_ability` already writes. `ChargeNumber` comes off the final override
  (`0x00688D3C`), `spent` and `deadline` off the module, `now` from `[0x00DE412C]+0x40`.
- **Arithmetic.** §3.1's refill derivation, evaluated **read-only** - the tooltip computes what the
  bank *would* be and writes nothing back. Seconds until the next charge are
  `(deadline' - now) / framesPerSecond` with the frame rate at `[0x00D9F608]`, which is the
  conversion `description-timers` already anchors at `0x00644FA6`.
- **The string.** A fourth entry in that patch's `KEYS` table, taking **three** format arguments
  where the existing four take one:

  ```
  TOOLTIP:SpecialPowerCharges             two %d       e.g.  "Charges: %d/%d"
  TOOLTIP:SpecialPowerChargesRecharging   two %d, %.1f e.g.  "Charges: %d/%d (next in %.1f s)"
  ```

  Two keys rather than one, mirroring `description-timers`' own `Cooldown`/`CooldownRemaining`
  pair: a full bank has no deadline to report, and printing a seconds field that is always zero is
  worse than not printing one. Both are silent unless the mod declares them, by the same `exists`
  out-parameter rule - so the readout is a no-op on unmodified string tables, and a mod that
  declares only the recharging one gets a line only while a refill is pending.

### 5.3 The line does not tick

`description-timers` §2 is the constraint and it applies unchanged: the tooltip is composed once
when it appears (`0x00807971` latches `0x00DE8998`; `0x00807676` is the only builder call) and is
never rebuilt while the pointer sits still. **"Next in 8.4 s" is right when the tooltip opens and
frozen after.** Moving off the button and back re-reads it. The live-refresh variant is scoped in
that document's §2(b) - one more six-byte window at `0x008078D4` - and inherits its open question
about what the movie does when a tooltip record is handed over twice. It is the same follow-up for
both patches and should be built once, for both.

## 6. What this does not cover

### 6.1 `SharedSyncedTimer` - three templates, and not the spellbook

`startPowerRecharge` returns before anything this patch hooks when the template's `SharedSyncedTimer`
byte at `+0x59` is set:

```
00896e71  cmp  byte [eax+0x59], 0
00896e75  je   0x896e87                 ; normal: on into the arithmetic
00896e77  push [ebp-0xc] / call 0x6ad1b0 ; shared: the Player's own timer, then out
```

`0x006AD1B0` walks a linked list off `Player+0x724`, keyed by the template's id at `+0x14`, and
writes a ready frame into the matching record's `+0x0C`. `isReady` diverts to the sibling reader
`0x006AD26F` on the same flag. So for those powers the cooldown really is player-side, the record
holds **only** a ready frame and no duration, and neither §2's storage nor §4's hook reaches them.

**But that is a three-template exclusion, not a category.** Grepping `ini.big`, `_patch201ini.big`
and `__edain_data.big` returns `SharedSyncedTimer = Yes` on exactly three `SpecialPower` blocks, the
same three in all of them: `SuperweaponSpawnOrcs`, `SpecialPowerRevealArea` and
`SuperweaponPartTheHeavens`.

**A spellbook is an object, and its powers are ordinary module powers.** `GoodSpellBook` /
`EvilSpellBook` and a `ChildObject` per faction (`GondorSpellBook`, `AngmarSpellBook`,
`ImladrisSpellBook`, …) carry the spells as `Behavior = SpecialPowerModule`,
`Behavior = OCLSpecialPower` and `Behavior = PlayerUpgradeSpecialPower`, each naming a
`SpecialPowerTemplate` with a plain `ReloadTime`. All three behaviours resolve into the 23-vtable
family this patch hooks:

| behaviour | `newModule` | allocates | ctor | interface vptr |
|---|---|---|---|---|
| `SpecialPowerModule` | `0x0064D92D` | `0x34` | `0x008973EE` (the base itself) | `0x00C64FF0` |
| `OCLSpecialPower` | `0x006518F0` | `0x34` | `0x008C72E9` | `0x00C73890` |
| `PlayerUpgradeSpecialPower` | `0x006522A0` | `0x34` | `0x008CC022` | `0x00C74D48` |

All three call `0x008973EE`, so the constructor widenings in §2.2 zero their padding too, and all
three vtables are in the 23 that carry `0x00896E31` at slot `+0x3C`. In `__edain_data.big` that is
**3,234 `SpecialPowerModule`, 737 `OCLSpecialPower` and 21 `PlayerUpgradeSpecialPower`** behaviours
covered.

What a spellbook power *does* have that a hero ability does not is `RequirementsFilterMPSkirmish`
and, usually, `AvailableAtStart = No` behind an `UpgradeName` - both of which gate whether the
button is usable at all, upstream of `readyFrame`, and neither of which this patch touches. A
spellbook spell with `ChargeNumber = 2` should therefore behave exactly as scoped once it is
unlocked.

### 6.2 The other `startPowerRecharge`

Three of the 26 vtables (`0x00C650F0`, `0x00C74878`, `0x00C873E0`) carry `0x00991500` in slot `+0x3C`
instead, and they are the **`SpecialPowerUpdateModule` family**. They are a different class shape -
the interface subobject sits at `+0x24` rather than `+0x10` (`0x008C9B77`) - and their
implementation keeps no `duration` (`getPercentReady` at `0x009913BC` divides by the raw
`ReloadTime`), so they have neither the field layout §2 assumes nor the multiplier §4 reuses.
Powers on those modules ignore `ChargeNumber` entirely - the keys parse, nothing reads them. Same
exclusion `recharge-rescale` §7.1 takes, for the same reason.

**Three vtables is not three module types**, and the difference is what the exclusion actually
costs. An interface vtable is shared by every class that overrides none of its methods, so the
classes installing these three outnumber them - the writers of each vptr say which
([`description-timers.md`](description-timers.md) §3.1.1 tabulates them):

| interface vtable | classes that install it |
|---|---|
| `0x00C650F0` | `WeaponModeSpecialPowerUpdate` (`0x00898249`), `DeflectSpecialPower` (`0x008C9920`), `SiegeDeployHordeSpecialPower` (`0x008CA84A`) |
| `0x00C74878` | `SiegeDeploySpecialPower` (`0x008C9B7A`) |
| `0x00C873E0` | the base itself (`0x0099115D`; name accessor `0x00991166`) |

In `__edain_data.big` that is 6 `DeflectSpecialPower`, 31 `SiegeDeployHordeSpecialPower`, 4
`SiegeDeploySpecialPower` - and **340 `WeaponModeSpecialPowerUpdate`**, the standard shape for a
hero ability that switches weapon mode for a `Duration`. So the exclusion is a real one, not the
rounding error the vtable count suggests: `ChargeNumber` on a `WeaponModeSpecialPowerUpdate` power
parses and does nothing.

### 6.3 Externally triggered recharges do **not** spend a charge

`OnTriggerRechargeSpecialPower` and the script engine's recharge actions reach
`startPowerRecharge(1.0)` on a module that did not fire - "using this ability also puts that one on
cooldown" ([`trigger-recharge-list.md`](trigger-recharge-list.md)). They go through `0x00897A35`,
which this patch does not hook, so they arm the named power's cooldown exactly as they do today and
leave its bank alone.

That is the right reading - a forced recharge is not a cast - and it is not a decision so much as a
consequence of hooking the cast rather than the recharge. The first build, which hooked
`startPowerRecharge`, got the other answer by accident along with twelve more it did not want.

Nothing that *clears* a cooldown is hooked either: `setReadyFrame` (interface slot `+0x20`,
`0x0099344A`; its callers are the script actions and `HeroDie::onDie`) and the other full-recharge
sites all keep stock behaviour. They do not need to be hooked, because §3.1's third refill arm sees
the result: a power whose bank is empty holds `readyFrame` at its refill deadline, so a cleared
cooldown is visible as `readyFrame` in the past with the deadline still ahead, and the fold hands a
charge back. `HeroDie`'s recharge-by-dying, a script reset and a modder's own restoration ability
all land on the same rule without this patch having to know any of them exist.

## 7. Composition

| patch | verdict |
|---|---|
| `recharge-rescale` | **Conflicts.** Its per-frame sweep tests `ftol(ReloadTime * m) == duration` and rescales when they differ; a charged power's `duration` is the *short* cooldown, so the sweep would rescale it every frame. Composing them means teaching the sweep to skip modules with `ChargeNumber != 0`, which is one compare in a cave that already reads the template - worth doing, but it is a change to *that* patch. |
| `cooldown-through-death` | **Composes, but ordered: apply it first.** It anchors a 29-byte window over `startPowerRecharge`'s full arm - the five bytes this patch's hook takes - so it refuses to apply afterwards, loudly. The other order is tested against both binaries. Both extend the `SpecialPower` field table and both read it live, so the second appends to the first's; it spends the interior padding at `+0x5A`/`+0x5B` and this one grows the tail. Its state table snapshots `(readyFrame, duration, deathFrame)` and not the bank, so a revived hero returns with a restored cooldown and a full bank. |
| `description-timers` | **Composes**, on disjoint bytes (`0x00808675` here, `0x008086AE` there) - and shares the seconds formatter and the string-fetch discipline. |
| `hero-mana` | **Conflicts** on `0x00808675`. Both want the special-power case. |
| `trigger-recharge-list` | **Composes**, in bytes and in meaning. It rewrites a parse-function slot in `SpecialAbilityUpdate`'s *module* field table and one `call`; it neither reads nor writes `SpecialPowerTemplate`, and the powers it recharges go through a site this patch does not hook. §6.3. |
| `player-heal-filter`, `spell-recharge-filter` | **Compose.** Both work on `Flags` (`+0x18`) and the player discount at `Player+0x718`, which this patch only ever reads through the engine's own expression. |

## 8. No-op on unmodified data

Four independent reasons a mod that never writes `ChargeNumber` sees the stock game:

- The field defaults to `0` (§1.3 zeroes it, `copyFrom` inherits the zero), and `0` is the hook's
  first exit.
- The stock five bytes are replayed on that exit, so `readyFrame`/`duration` are written by the same
  instructions in the same order.
- The tooltip line needs both a charged power *and* a declared string key; a missing key drops the
  line entirely rather than printing `MISSING:'…'`.
- The template's extra 12 bytes are never read by anything that does not go through the new rows.

## 9. Determinism and the network

`readyFrame` decides whether a power fires, so this is simulation state on the same footing as
`production-condition` and `cooldown-through-death`: **every peer must run the same patched binary**,
and replays do not cross between patched and unpatched clients. Both new module fields are written
only on the logic thread inside `startPowerRecharge`, from integers, and the derivation that reads
them is a pure function of stored frames and `TheGameLogic`'s frame (§3.3). No float enters the
stored state - `short` and `interval` are `ftol`'d before anything is written, exactly as the stock
duration is.

The tooltip half is client-local and read-only, the same blast radius as `upgrade-description`.

## 10. What the live test settled, and what is still open

**Settled, in one run**, and both answers are in the patch now:

- A cast spent the **whole bank**, not one charge - `startPowerRecharge` is not the cast (§4.1).
- A restoration ability cleared the cooldown and handed back **no charge** - nothing that clears a
  cooldown is hooked, and it does not need to be (§3.1's third arm).

**Still open**, in the order a second run should take them:

1. **A three-charge ability behaves like one**: three casts spaced by `ReloadTimeBetweenCharge`, then
   a wait of `ReloadTime` measured from the *first* cast, then one charge back.
2. **The pie matches the wait it is drawing** in both phases - short between charges, long when the
   bank is empty - and does not jump when the phase changes.
3. **`ReplenishAllChargesOnReloadTime = Yes`** returns the whole bank in one step and starts no
   further cycle.
4. **The AI casts a charge power** - it comes through `isReady` like everything else, but "the AI
   fires it three times in a row" is the observation that proves §3.2.
5. **A power with `ChargeNumber` unset is byte-identical in behaviour**, cooldown length included, on
   a hero with a `RECHARGE_TIME` aura up.
6. **Save and reload mid-cycle** and confirm the documented loss (§2.3) is what actually happens -
   a full bank, no cycle - rather than something worse.
7. **A `map.ini` override of a charged `SpecialPower`** keeps its charges (the `copyFrom` half of
   §1.3).
8. **A spellbook spell with `ChargeNumber`** behaves like a hero ability's - §6.1 says it should,
   from the class layout, but the spellbook reaches its powers through the palantir UI and a
   `RequirementsFilterMPSkirmish` gate that a hero ability does not have.
9. **A power that starts on cooldown** begins the match with a **full** bank - the constructor's
   own `startPowerRecharge` at `0x00897471` is excluded by return address, and that exclusion is
   worth seeing rather than inferring.
11. **An ability driven by an update module** - `UpdateModuleStartsAttack = Yes` beside a
   `WeaponFireSpecialAbilityUpdate`, as Zaphragor's `SpecialAbilityVerheerenderAngriff` is - spends
   exactly one charge per cast. This is the case the second build did nothing for, and it is the
   first thing a third run should check.
10. **A restoration ability on a power with charges left** clears the short cooldown and spends
   nothing - the restore arm requires an empty bank, and the case where it does not fire is as
   worth seeing as the case where it does.

## Address table

| VA | what |
|---|---|
| `0x00DA5FD8` | `SpecialPower` field-parse table, 24 entries, terminator at `0x00DA6158` |
| `0x007B1ABE`, `0x007B2325` | the two `imm32` references to it |
| `0x0042EC5E` / `0x0073A429` / `0x0042E558` | `INI::parseInt` / the `ReloadTime` ms→frames parser / `INI::parseBool` |
| `0x007B1F5B` | `SpecialPowerTemplate` ctor |
| `0x007B218E`, `0x007B21DA`, `0x007B2292` | the three `push 0x88` allocations (`68 88 00 00 00`) |
| `0x007B200D` | ctor window, `mov [esi+0x84], ebx` |
| `0x007B1E6C` | `copyFrom`; callers `0x007B21C3`, `0x007B222C`, `0x007B22E4` |
| `0x007B1F53` | `copyFrom` window - its whole epilogue, `SPECIAL_POWER_TEMPLATE_COPY_TAIL` |
| `0x008973EE` | `SpecialPowerModule` base ctor; the two widenings at `0x00897447`, `0x0089744D` |
| `0x0089679D` | its `Xfer` - the evidence for what is and is not saved; `0x00707887` = `xferObjectID` |
| `0x00896E31` | `startPowerRecharge`, 23 vtables, interface slot `+0x3C` |
| `0x00896F75` | **the hook**, `a1 2c 41 de 00`; stock resume `0x00896F7A`, charged rejoin `0x00896F8E` |
| `0x00897471` -> `0x00897476` | the module constructor's `call startPowerRecharge` - excluded by return address |
| `0x00897A35` -> `0x00897A38` | the `OnTriggerRecharge` walk - excluded by return address |
| `0x008979AE` | `doSpecialPower`'s `UpdateModuleStartsAttack` guard - why the hook is on the caller |
| `0x00896EE3` | the `ReloadTime` read the readout's `interval` transcribes |
| `0x00896C72` / `0x00896CF2` | `isReady` / `getPercentReady` - read, never patched |
| `0x00688D3C` | `getFinalOverride` |
| `0x0068C26D` | `Object::getSpecialPowerModule`, `ret 4` |
| `0x00808675` | the description builder's special-power case (`83 f9 18 75 30`); body `0x0080867A` |
| `0x00DE412C` `+0x40` | `TheGameLogic`, its frame |
| `0x00D9F608` / `0x00D9F610` | logic frames per second / per millisecond |
| `0x00991500` | the second `startPowerRecharge` - the `SpecialPowerUpdateModule` family, excluded (§6.2) |
| `0x006AD1B0` / `0x006AD26F` | the `SharedSyncedTimer` player-side recharge / reader; list head `Player+0x724` (§6.1) |
| `0x0064D92D` / `0x006518F0` / `0x006522A0` | `newModule` for `SpecialPowerModule` / `OCLSpecialPower` / `PlayerUpgradeSpecialPower` - the spellbook's three behaviours |
| `0x00991166`, `0x008C9939`, `0x008CA867` | name accessors for the three excluded `SpecialPowerUpdateModule` classes |
