# Negative income as a maintenance cost

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), read from
`sage_mods/edain/patching/engine/game.dat.backup` — the clean reference, not the repo-root
`game.dat`, which carries eleven modifications of its own. Every window below was checked against
both and is identical in each. This is the writeup for the **`maintenance-cost`** patch,
[`patches/maintenance_cost.py`](../patches/maintenance_cost.py), with the tests in
[`tests/sage_patch/test_maintenance_cost.py`](../../tests/sage_patch/test_maintenance_cost.py).

**What it does.** A **negative** `TerrainResourceBehavior.MaxIncome` or
`AutoDepositUpdate.DepositAmount` takes that much gold per tick from the owning player instead of
being discarded — a per-structure upkeep. The patch computes no multiplier of its own: a charge is
whatever the module's own income arithmetic produced with the sign kept, so it is affected by
inflation exactly when that module's *income* is (always for `TerrainResourceBehavior`; for
`AutoDepositUpdate` only with [`auto-deposit-inflation`](auto-deposit-inflation.md)).

```ini
Behavior = TerrainResourceBehavior ModuleTag_Upkeep
  MaxIncome      = -5          ; five gold a tick, taken
  IncomeInterval = 30
End

Behavior = AutoDepositUpdate ModuleTag_Upkeep
  DepositAmount = -5
  DepositTiming = 30000
End
```

```sh
sage-patch apply maintenance-cost --in game.dat.backup --out game.dat   # no parameters
sage-patch verify maintenance-cost game.dat
```

**Status: built and static-verified.** The five windows hold their stock bytes in both binaries,
no branch reaches the interior of any of them (§4), the cave disassembles cleanly to its end,
apply/verify/detect round-trip, and it composes in both orders with `terrain-resource-exp`,
`second-resource`, `command-point-upkeep`, `inflation-readout` and `auto-deposit-inflation`.

**Five edits and a 306-byte cave**, of which one edit is a single byte and needs no cave at all.

---

## 1. There is no INI work to do

`MaxIncome` is row 2 of the `TerrainResourceBehavior` field table at `0x00C5FD78`, parsed by
`0x0042EC5E` into `ModuleData+0x0C`; `DepositAmount` is the same parser into `AutoDepositUpdate`'s
`ModuleData+0x0C`. That parser is two calls:

```asm
0042ec5e  call 0x42dc9f                     ; INI::getNextTokenOrNull
0042ec6e  call 0x42e9d7                     ; INI::scanInt
0042ec77  mov  [ecx], eax                   ; store
```

and `INI::scanInt` is:

```asm
0042ea03  push 0xbd4194                     ; "%d"
0042ea09  call [0xbd05e8]                   ; sscanf
0042ea12  cmp  eax, 1
0042ea17  push 0xbd4148                     ; "Expected signed integer "   <- on failure
```

So a minus sign parses, on a **stock** binary, today. That single fact decides the shape of the
whole patch: no field-table rebuild, no new keyword string, no `sage_ini` surface, no `.sagepatch`
entry — and, as a consequence worth stating loudly, **a mod written for this patch still loads on
an unpatched binary.** It just silently does not charge there. Compare
[`terrain-resource-exp`](terrain-resource-exp.md), whose new keyword is a fatal INI parse error on
a stock build and therefore cannot be got wrong quietly.

What a negative currently does instead is nothing useful, and the three reasons are §3.

## 2. The one thing that makes this a patch rather than a data change

`Money::deposit` (`0x007B18B8`) and `Money::withdraw` (`0x007B17EF`) are siblings that differ in
exactly the way that matters:

```asm
; deposit(amount, stats, playSound)                ; withdraw(amount, stats, playSound)
007b18ca  mov  edi, [ebp+8]                        007b1801  mov  edi, [ebp+8]
007b18cd  test edi, edi                            007b1806  mov  eax, [esi+4]
007b18cf  je   <ret>                               007b1809  cmp  edi, eax
                                                   007b180b  cmova edi, eax        ; <- unsigned
007b192f  add  [esi+4], edi                        007b1871  sub  [esi+4], edi
007b1954  add  [eax+8], edi   ; MoneyEarned        007b1896  add  [eax+4], edi   ; MoneySpent
007b1971  ret  0xc                                 007b18a6  mov  eax, edi       ; what it took
```

`deposit` is an unclamped `add`. `withdraw` clamps with `cmova` — an **unsigned** compare, which
is the proof that `Money::m_amount` at `+0x04` is unsigned. So "just deposit a negative number" is
not a charge written oddly: it rolls the balance through zero to about four billion gold, on the
first tick, silently.

Every charge in this patch therefore goes through `withdraw`, which buys three things for free:
the balance cannot go negative, the amount actually taken comes back in `eax` (so the floating
text can be truthful when a player is broke), and the score screen counts it under **MoneySpent**
rather than un-counting MoneyEarned.

## 3. `TerrainResourceBehavior::update` (`0x008854D3`)

Beware the naming: this function is `TERRAIN_RESOURCE_UPDATE` and also the **only** reader of
`PlayerTemplate.ResourceModifierValues` in the image — the thing
[`command-point-upkeep`](command-point-upkeep.md) and [`inflation-readout`](inflation-readout.md)
call "the deposit". `AutoDepositUpdate::update` is a different function at `0x0089DC00`-ish.
`addresses.py` says so at `AUTO_DEPOSIT_MODULE_DATA_CTOR`; the discriminator is the `ModuleData`,
`[ebp-0x18]` here and `[esi-0x0C]` there.

The income, from `MaxIncome` to the purse:

```asm
00885650  mov  eax, [ebp-0x18]              ; the ModuleData
00885653  fild dword [eax+0xc]              ; MaxIncome
00885658  fmul [ebx+0x1c]                   ; the claimed fraction
0088565b  fmul [ebp-0x10]                   ; the object's bonus (query type 0xd)
0088565e  fmul [ebp-0x14]                   ; UpgradeBonusPercent, or 1.0
00885664  call [0xbd0588]                   ; ceil          (msvcr71!ceil)
00885672  fistp dword [ebp-0x20]
00885675  mov  ebx, [ebp-0x20]
00885678  test ebx, ebx
0088567a  jle  0x88573c                     ; (A) non-positive -> straight to the XP block
00885680  fild dword [ebp-0x20]
00885685  fmul [ebp-0x1c]                   ; the inflation multiplier
0088568b  call [0xbd0588]                   ; ceil
00885692  fstp dword [ebp-0x20]             ;      as a float
00885699  fistp dword [ebp-0x1c]
0088569c  mov  ebx, [ebp-0x1c]
0088569f  test ebx, ebx                     ; (B) "never round an income below 1 gold"
008856a1  jg   0x8856a6
008856a3  xor  ebx, ebx / inc ebx
008856a6  push 1 / lea eax,[esi+0x3dc] / push eax / push ebx
008856b0  lea  ecx, [esi+0x90]              ; (C) &player->m_money
008856b6  call 0x7b18b8                     ; Money::deposit
008856bb  ... the green GUI:AddCash floating text ...
0088573c  ... the experience block: addExperiencePoints((float)ebx) ...
```

`esi` is the controlling `Player` (from `Object::getControllingPlayer` at `0x0088552D`), `edi` the
depositing `Object`, and `ebx` is the module `this` until `0x00885675` overwrites it with the
amount.

### (A) the gate, and the one-byte edit

`jle 0x0088573C` is the whole of why a negative does nothing. The condition wants to be `== 0`
rather than `<= 0`, which is `0F 8E` → `0F 84` **in place**: same six bytes, same rel32, so the
zero case lands exactly where it landed and nothing downstream moves.

That one byte is also what buys the inflation requirement for this module for free. `0x00885685`
is stock, and the multiplier it applies was already gated on the object's membership:

```asm
008855bc  call 0x762977                     ; ObjectFilter::isValid   -> no  -> mult stays 1.0
008855ce  call 0x7640c1                     ; filter.allow(edi, esi)  -> no  -> mult stays 1.0
008855ec  call 0x6ababd                     ; Player::forEachTeamObject, counting
0088560a  in range : mult = values[count] * 0.01f
0088561e  past end : mult = values[n-1] * 0.01f - (count-n) * 0.02f, floored at 0
```

So "affected by inflation if the object is in the inflation list" is not implemented here at all —
it is what the engine already does to the number, once the number is allowed to be negative.

### (B) the floor, and the sign a rounding destroys

In the stock build (B) can only ever fire at exactly zero: (A) has established the value was
positive, and the multiplier is never negative. Its job is "an income never rounds away to
nothing". Left alone it turns a charge into a **payment of one gold**, so the cave mirrors it: an
income floors at `+1`, a charge at `-1`.

Which of the two applies cannot be read from `ebx`, because an inflation multiplier of zero rounds
a charge to an integer zero and erases its sign. It is read from `[ebp-0x20]` instead, which at
this point holds the **float** the integer was rounded from — and IEEE gives `-5.0f * 0.0f` the
value `-0.0f`, whose sign bit `test eax, eax` on the raw dword reads directly. (The slot is the
same `ebp-0x20` that held `&ResourceModifierObjectFilter` earlier in the function; the `fistp` at
`0x00885672` is where it stops being that.)

Seven bytes, so the detour is `jmp rel32` plus two `nop`.

### (C) the payment

Hooked at `lea ecx, [esi+0x90]` — the instruction **before** the call, six bytes — rather than at
the call itself, for symmetry with §4 where the choice is forced. The three deposit arguments are
already pushed with the amount at `[esp]`, so the charge path is short:

```asm
        lea  ecx, [esi+0x90]              ; the displaced instruction
        test ebx, ebx
        js   charge
        jmp  0x008856b6                   ; the stock call, and the stock green text
charge: neg  dword [esp]                  ; the magnitude
        call 0x7b17ef                     ; Money::withdraw, ret 0xc -> eax = what it took
        test eax, eax
        je   silent
        push eax / push edi / call lose_text / add esp, 8
silent: xor  ebx, ebx
        jmp  0x0088573c
```

Rejoining at `0x0088573C` rather than at `0x008856BB` is what skips the green `GUI:AddCash` block,
which would otherwise format a minus sign into a string whose `.csf` entry begins with a plus.

## 4. `AutoDepositUpdate::update`

```asm
0089dc99  mov  eax, [esi-0xc]               ; the ModuleData
0089dc9c  cvtsi2ss xmm0, dword [eax+0xc]    ; DepositAmount
0089dca7  mulss xmm0, xmm1                  ; the upgrade bonus, or 1.0
0089dcb0  call 0x625456 / 0x642002          ; the difficulty handicap, in a solo game
0089dcdd  cvttss2si eax, [ebp-0x14]         ; truncate, toward zero
0089dce5  call 0x6aa858                     ; the WotR region money bonus
0089dcf0  call 0xa3cfa4                     ; round-half-away-from-zero
0089dcf5  push 1 / lea ecx,[edi+0x3dc] / push ecx / push eax
0089dcff  lea  ecx, [edi+0x90]              ; &player->m_money
0089dd05  mov  [ebp-0x14], eax
0089dd08  call 0x7b18b8                     ; Money::deposit
0089dd0d  mov  eax, [esi-8]                 ; edi stops being the Player here
0089dd19  cmp  byte [eax+0x20], 0           ; GiveNoXP
0089dd1d  jne  0x89dd4f
0089dd52  cmp  [eax+0xc], ebx               ; DepositAmount > 0 ?
0089dd56  jle  0x89dddf                     ; no -> no "+N" text
```

`edi` is the `Player`, `[esi-8]` the `Object`, `[esi-0x0C]` the `ModuleData`.

This module **clamps the amount nowhere.** `cvttss2si` truncates toward zero, the region bonus at
`0x006AA858` is a multiply-and-round, `0x00A3CFA4` branches on the sign — all three carry a
negative through unharmed. And the floating text is *already* gated on `DepositAmount > 0` at
`0x0089DD52`, which reads as the original authors having thought about a non-positive amount and
declined to draw anything for it. So only the deposit itself needs an edit.

### The hook site is forced

[`second-resource`](second-resource.md) hooks the `call` at `0x0089DD08` — it is
`AUTO_DEPOSIT_DEPOSIT` in `addresses.py`. Taking it would make the two patches mutually exclusive
for no reason, so this patch hooks the `lea` at `0x0089DCFF` instead (six bytes) and rejoins at
`0x0089DD05`, one instruction **above** the call. A positive amount therefore runs whatever
occupies that call; a negative jumps past it to `0x0089DD0D`, which is also the right answer for
`second-resource` specifically — a charge does not credit a second-resource pool.

### Inflation is somebody else's patch

This module reads no `ResourceModifierValues`, and this patch does not teach it to. A charge here
is the amount that reached the hook, negated — no multiply, no conversion, nothing.

That is deliberate, and it is what makes the rule clean: **a charge is affected by inflation
exactly when the module's income is.** For `TerrainResourceBehavior` that is always, because
`0x00885685` is stock. For `AutoDepositUpdate` it is never, because the module pays flat — unless
[`auto-deposit-inflation`](auto-deposit-inflation.md) is also applied, which scales the amount at
`0x0089DCDD`, three instructions above this patch's hook, and therefore scales an income and a
charge with the same instruction.

| | income (`DepositAmount > 0`) | charge (`DepositAmount < 0`) |
|---|---|---|
| neither patch | flat | discarded |
| `maintenance-cost` only | flat | **flat charge** |
| both | inflated | **inflated charge** |

Applying inflation to an `AutoDepositUpdate` *charge* but not to its *income* would have been the
asymmetry this table exists to avoid, and doing both from inside this patch would have re-balanced
every mod that ships the module the moment somebody wanted an upkeep somewhere. Hence two patches.

### No branch reaches any window

The first attempt at this check used a linear capstone sweep of `.text`, and **it was wrong**:
`Cs.disasm` stops at the first undecodable byte, so it covered 43,078 instructions of an 8.2 MB
section and answered "no branches" for every window here — including one it could be proved wrong
about by hand. [`scripts/scan_branches.py`](../scripts/scan_branches.py) replaces it by decoding a
branch at **every byte offset**, which over-approximates and so cannot produce a false negative;
it reports no interior hit for any of the five windows, and no window byte appears as an `imm32`
anywhere in the image. The full output is in
[`auto-deposit-inflation.md` §5](auto-deposit-inflation.md#5-the-window-is-safe-and-how-that-was-actually-established).

## 5. Experience

Both modules hand the tick amount to `ExperienceTracker::addExperiencePoints` — `0x0088575A`
converts `ebx`, and `0x0089DD31` recomputes `DepositAmount * bonus`. A negative amount would
therefore **drain** a building's veterancy, down a path no sane stock data reaches and whose
behaviour past the first call (`0x0079D833` → `0x0079D68D`) has not been read. That is a second
mechanic nobody asked for with an unaudited failure surface, so a charge tick grants **zero**
experience instead, which is precisely the stock "no income this tick" case:

* `TerrainResourceBehavior`: `xor ebx, ebx` before rejoining the block, `ebx` being its only input.
* `AutoDepositUpdate`: the stock `GiveNoXP` test at `0x0089DD19` is reproduced in the cave with a
  second condition after it, `cmp dword [eax+0xc], 0 / jl`. The stock field keeps doing exactly
  what it did.

`terrain-resource-exp`'s `GiveNoXP` still governs the income ticks, which are now the only ticks
that grant experience at all.

## 6. The floating text

The engine already draws both halves of this, at the money-transfer site `0x008C6980`, which pays
one player and charges another:

| | key | color | z offset |
|---|---|---|---|
| received | `GUI:AddCash` (`0x00C13EE0`) | `0xFF00FF00` | `+20.0f` (`0x00BDBC6C`) |
| paid | `GUI:LoseCash` (`0x00C732F8`) | `0xFFFF0000` | `+30.0f` (`0x00BDAE54`) |

`GUI:LoseCash` has exactly one reference in the image, that one. The cave copies the idiom
verbatim — `TheGameText->fetch(key, 0)` through vtable `+0x44`, `UnicodeString::format` into a
local, `TheInGameUI->addFloatingText(&str, &pos, color)` through vtable `+0x1A0`, then the string's
destructor — so there is **no new string key, no `.csf` edit and no `.apt` edit**, and a charge
looks like something the game already does because it is.

Two details it inherits rather than invents: the destination `UnicodeString` is zeroed before the
format, because `0x00ADF7E0` *replaces* rather than appends and releases what the slot held (the
warning at `UNICODE_STRING_CONCAT` in `addresses.py`); and the amount passed is `withdraw`'s return
value, not the requested one, so a player with 3 gold facing a 5 gold charge sees `3`.

## 7. What it does not do

* **No affordability rule.** `withdraw` clamps. Nothing is destroyed, disabled, or put into debt
  for want of upkeep — a structure that shuts down when its owner cannot pay is a different
  mechanic on a different module, and this patch deliberately does not invent one.
* **No positive-path change anywhere.** Every edit is behind a sign test; the two in-place
  condition rewrites preserve the stock outcome for every value the stock build could reach them
  with.
* **No `InitialCaptureBonus`.** It has its own deposit at `0x0089DABE` and is not covered, the same
  scope line `second-resource` draws.
* **No inflation of its own** — see §4.

## 8. Determinism, and verifying it

Money is logic-side `Player` state and the engine CRCs it, so **every peer must run the same
patched binary** — the `command-point-upkeep` rule, stricter than the client-local
`inflation-readout`. Savegames are unaffected: `ModuleData` is load-time configuration read from
`.ini` and never `Xfer`'d, and the cave holds no state.

To verify it in a game:

1. Put `MaxIncome = -5` on a `TerrainResourceBehavior` with a short `IncomeInterval` and watch the
   balance fall and a red number rise off the building.
2. On a `TerrainResourceBehavior` charge, build enough of the faction's inflation-listed
   structures to push `ResourceModifierValues` down a tier, and check the charge falls in the same
   proportion the income does — the palantir readout from `inflation-readout` shows the factor
   being applied. An `AutoDepositUpdate` charge should *not* move, unless
   `auto-deposit-inflation` is installed, in which case it should move by the same factor.
3. Charge a player who has less gold than the tick asks for, and check the balance stops at zero
   rather than wrapping — the failure mode §2 exists to prevent.
4. Confirm the building's veterancy does not move on a charge tick.

## 9. Site table

| what | VA | window | resume |
|---|---|---|---|
| the non-positive gate | `0x0088567A` | `0f8ebc000000` | in place, `0f84…` |
| the floor at one gold | `0x0088569F` | `85db7f0333db43` | `0x008856A6` |
| the money pointer (TRB) | `0x008856B0` | `8d8e90000000` | `0x008856B6` / `0x0088573C` |
| the money pointer (ADU) | `0x0089DCFF` | `8d8f90000000` | `0x0089DD05` / `0x0089DD0D` |
| the `GiveNoXP` gate | `0x0089DD19` | `807820007530` | `0x0089DD1F` / `0x0089DD4F` |

Engine routines the cave calls: `Money::withdraw` `0x007B17EF` · `ObjectFilter::isValid`
`0x00762977` · `ObjectFilter::allow` `0x007640C1` · `Player::forEachTeamObject` `0x006ABABD` ·
the counting callback `0x00885230` · `UnicodeString::format` `0x00ADF7E0` ·
`UnicodeString::~UnicodeString` `0x004367B0` · `TheGameText` `0x00DE4B04` (`+0x44`) ·
`TheInGameUI` `0x00DE4830` (`+0x1A0`).
