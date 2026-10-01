# Upgrade discounts and `Type = PLAYER`

`CostModifierUpgrade` with `UpgradeDiscount = Yes` never changes the price of a `Type = PLAYER`
upgrade. The engine checks the type on purpose: only `OBJECT` upgrades read the discount.
Static reading only; nothing here has been checked in a running game yet.

## 1. Where the price is computed

`UpgradeTemplate::calcCostToBuild` at `0x0066F2C8`: `__thiscall(UpgradeTemplate*)`, stack args
`(Player *, Object *)`, `ret 8`, returns the price in `eax`. Every consumer goes through it: the
affordability check (`0x0066F4AE`), the charge at queue time (`0x008A10AD`, withdraws from
`Player+0x3DC`), the tooltip cost line (`0x00808399`) and the command and AI sites
(`0x0099F918`, `0x009A0210`, `0x009A15F5`, `0x009B6397`, `0x009B661E`, `0x008EF648`,
`0x008A2039`). So one fix inside this function reaches all of them.

It picks one of three paths:

```
0066f2d1  lea  edi, [esi+0x7c]          ; UseObjectTemplateForCostDiscount
0066f2dd  jne  0x66f304                 ; empty -> own price
0066f2fa  call 0x73c25f                 ; else ThingTemplate::calcCostToBuild(player, obj, BuildCost)
                                        ;   -> object-style modifiers, BOTH upgrade types
0066f304  cmp  [ebp+8], 0               ; no Player -> return BuildCost unchanged
0066f314  ...                           ; SubUpgradeTemplateNames: price = sum of the sub-upgrades
0066f363  cmp  dword [esi+4], 1         ; Type: 0 PLAYER, 1 OBJECT (name table 0x00DA05C8)
0066f367  movss xmm0, [0xbd1908]        ; multiplier = 1.0
0066f36f  jne  0x66f39c                 ; <-- PLAYER skips the discount here
0066f371  cmp  byte [esi+0x79], 0       ; NoUpgradeDiscount
0066f375  jne  0x66f39c
0066f389  call 0x6ae7cb                 ; Player::getUpgradeDiscount(name)
0066f38e  fadd [0xbd1908]               ; multiplier = 1.0 + sum
0066f39c  price = (int)(price * multiplier)
0066f3ac  ...                           ; then the AI-difficulty handicap, both types
```

`0x006AE7CB` adds up the entries of the vector at `Player+0x3D0..+0x3D4` (stride `0x24`) using
`0x006ADA3E`. For each entry, an empty `ApplyToTheseUpgrades` list (`+0x14..+0x18`) matches every
upgrade, and a non-empty list matches by name. The entry's value is at `+0x20`, and an entry that
does not match adds `0.0` (`0x00C1B594`). `CostModifierUpgrade`'s palantir label (`0x0092F712`)
checks `UpgradeDiscount` (`ModuleData+0x148`) and reads this same sum, so this vector is where
`UpgradeDiscount = Yes` modules put their entries.

## 2. The data it affects

In the Edain tree there are 37 `UpgradeDiscount = Yes` modules. None of them names a PLAYER upgrade
in `ApplyToTheseUpgrades`. Two have no list and so apply to all upgrades: `beutehort.ini` (−20%)
and `schatzlager.ini` (0%). If the gate were removed, both would also start discounting PLAYER
upgrades.

## 3. Workaround without a patch

The `UseObjectTemplateForCostDiscount` path runs before the type check. A PLAYER upgrade that names
an object there is priced by `ThingTemplate::calcCostToBuild` with `BuildCost` as the base, so the
object-cost `CostModifierUpgrade` modules whose `ObjectFilter` matches that object apply to it. It
also stops reading `UpgradeDiscount` entries entirely. Edain already uses this path for
`Upgrade_OpenGarrison` (an OBJECT upgrade).

## 4. The patch: `player-upgrade-discount`

It makes two edits, both inside the discount block (`UPGRADE_DISCOUNT_GATE`, `0x0066F363`):

| site | stock | patched |
|---|---|---|
| `0x0066F36F` | `jne 0x66f39c` (`75 2B`), the OBJECT-only branch | `90 90` |
| `0x0066F389` | `call 0x6ae7cb` | `call` the `.plrdisc` cave |

The cave has the same contract as `0x006AE7CB` (`__thiscall`, the name by value, `ret 4`, sum in
`st0`):

- **OBJECT** (`[esi-4] == 1`, because `esi` already points at the name at `+0x08`): a tail `jmp` to
  the stock routine with the stack untouched, so OBJECT prices are exactly as before.
- **PLAYER**: a copy of the stock loop that skips any entry whose `ApplyToTheseUpgrades` is empty.
  A PLAYER upgrade is therefore discounted only by modules that name it, and the two list-less
  Edain modules (§2) keep discounting OBJECT upgrades only. `NoUpgradeDiscount = Yes` still opts an
  upgrade out, because its test at `0x0066F371` now runs for both types.

Nothing in the stock data names a PLAYER upgrade, so the patch changes no existing price. It has no
new INI keyword; a mod uses it by listing a PLAYER upgrade in `ApplyToTheseUpgrades` on an
`UpgradeDiscount = Yes` module.

Not yet run in game. To check it: list a PLAYER upgrade in a discount module, then compare the
tooltip price, the gold withdrawn (`Player+0x94`) and the refund after cancelling. The refund path
has not been traced; if it reads `BuildCost` directly rather than calling `calcCostToBuild`, a
cancel would refund more than was charged.
