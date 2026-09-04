# The disappearing command points

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), read statically from the
repo's `game.dat`. **Status: statically derived, not yet runtime-confirmed.** No patch yet.

## The report

> There are scenarios in which a player's command points disappear, both the display and the actual
> points, since the player can no longer recruit anything. The latest record is in freebuild, to
> enemies that have Angmar's Witch King use `SpecialAbilityLetzterWinter`. It also used to happen
> sometimes when an enemy was defeated in certain game modes.

## TL;DR

`Object::applyModifierList` (`0x0068F1A8`) subtracts an object's command-point contribution from its
owner **before** applying the modifier, and re-adds it only if the apply succeeded. The apply has
four `return FALSE` exits. On any of them the subtraction stands and the addition never happens, so
`Player+0x6C` — the command-point cap bonus — permanently loses that object's whole contribution.

The guard at `0x0068F217` limits the damage to objects with `ThingTemplate.CommandPointBonus > 0`
(`+0x62C`), which in Edain is 195 templates: farms, mineshafts, outposts, dormitories, citadels —
exactly the buildings a player's cap is made of. `getCommandPointCap` (`0x006A7B9F`) is
`min(base + bonus + filtered terms, hard cap)`, so a bonus driven far negative collapses the cap,
and `hasEnoughCommandPoints` (`0x006A7F79`) then refuses every unit that costs anything.

## 1. Where the cap bonus is maintained

The `Player+0x60` command-point subobject is laid out in
[`command-point-upkeep.md`](command-point-upkeep.md) §2. Two wrappers on `Player` maintain it, and
which of the two counters an object touches is decided by its template, not by its kind:

```asm
006aa56d  mov  eax, [esp+4]              ; Player::addCommandPointsForObject(obj)
006aa571  mov  edx, [eax+4]              ; the ThingTemplate
006aa574  add  ecx, 0x60                 ; the command-point subobject
006aa577  cmp  dword [edx+0x62c], 0      ; ThingTemplate.CommandPointBonus
006aa57e  push eax
006aa57f  jle  0x6aa588
006aa581  call 0x6a7c3e                  ;   bonus > 0 -> add to the CAP BONUS  (+0x0C)
006aa586  jmp  0x6aa58d
006aa588  call 0x6a7fda                  ;   otherwise -> add to POINTS IN USE  (+0x08)
```

`0x006AA590` is the same function with `0x6A7C51` / `0x6A7FEB`, subtracting. So a cap-granting
object never counts against usage and a costing object never grants cap.

The value a cap-granting object is worth is **not** a constant:

```asm
006a7c01  mov  ecx, [ebp+8]              ; the Object
006a7c07  mov  eax, [ecx+4]              ; its ThingTemplate
006a7c0a  xorps xmm0, xmm0
006a7c0e  mov  esi, [eax+0x62c]          ; CommandPointBonus
006a7c14  push 0                         ; ] Object::hasModifier(24, &out, 0)
006a7c16  lea  eax, [ebp+8]              ; ]  type 24 == COMMAND_POINT_BONUS
006a7c19  push eax                       ; ]
006a7c1a  push 0x18                      ; ]
006a7c1c  movss [ebp+8], xmm0            ; seed *out = 0.0
006a7c21  call 0x68c818
006a7c26  test al, al
006a7c28  je   0x6a7c37
006a7c2a  cvtsi2ss xmm0, esi             ; bonus + the summed live modifiers
006a7c2e  addss xmm0, [ebp+8]
006a7c33  cvttss2si esi, xmm0
006a7c37  mov  eax, esi
```

It is `CommandPointBonus` **plus every active `COMMAND_POINT_BONUS` attribute modifier on the
object**. The modifier type numbering is the table in
[`construction-speed-modifiers.md`](construction-speed-modifiers.md) §1.2; 24 is
`COMMAND_POINT_BONUS`.

That is the whole reason the leaking routine exists. A modifier changes the object's worth, so the
only way the cap can track it is to remove the old worth, change the modifier set, and add the new
worth back.

## 2. The leak

`Object::applyModifierList`, `0x0068F1A8`, `ret 8`. Two early exits — a list-level refusal at
`0x0068F1C6`, and the horde forward at `0x0068F1E4` that hands the list to the container's members —
run before any accounting and are harmless. The tail is not:

```asm
0068f1f8  push ebx
0068f1f9  mov  ecx, esi
0068f1fb  call 0x68c4a6                  ; Object::getModifierHolder
0068f200  test eax, eax
0068f202  mov  [ebp-4], eax
0068f205  je   0x68f250                  ; no holder -> FALSE, before any accounting
0068f207  mov  ecx, esi
0068f209  call 0x68b678                  ; Object::getControllingPlayer
0068f20e  mov  edi, eax
0068f210  test edi, edi
0068f212  je   0x68f24c                  ; no player  -> bl = 0, skip both halves
0068f214  mov  eax, [esi+4]
0068f217  cmp  dword [eax+0x62c], 0
0068f21e  jle  0x68f24c                  ; no bonus   -> bl = 0, skip both halves
0068f220  push esi
0068f221  mov  ecx, edi
0068f223  mov  bl, 1
0068f225  call 0x6aa590                  ; ** SUBTRACT the object's cap contribution **
0068f22a  push [ebp+0xc]
0068f22d  mov  ecx, [ebp-4]
0068f230  push [ebp+8]
0068f233  call 0x805a8e                  ; ModifierHolder::applyModifierList
0068f238  test al, al
0068f23a  je   0x68f250                  ; ** FAILED -> return FALSE, NEVER RE-ADDING **
0068f23c  test bl, bl
0068f23e  je   0x68f248
0068f240  push esi
0068f241  mov  ecx, edi
0068f243  call 0x6aa56d                  ; the add back, on the success path only
```

Both guards that can skip the accounting (`0x0068F212`, `0x0068F21E`) clear `bl` and jump *past* the
subtraction, so the two halves are correctly paired on every path **except** the one at
`0x0068F23A`. There the subtraction has already run.

The removal counterpart at `0x0068F2A0` is written correctly: it calls `0x008052FB` with no
return-value test and re-adds unconditionally when `bl` is set. Only the apply path leaks.

`0x0068F1A8` has **32 call sites** — aura updates, weapon nuggets, upgrade modules, special powers.
It is the single door every attribute modifier in the game goes through.

## 3. The four ways the apply says no

`ModifierHolder::applyModifierList`, `0x00805A8E`. Its epilogue at `0x00805E78` returns `al`.

| exit | at | condition |
|---|---|---|
| 1 | `0x00805AD3` to `0x00805B01` | the list name does not resolve in `TheAttributeModifierStore` (`0x00614470` returned < 0) |
| 2 | `0x00805AE5` to `0x00805B01` | the store returned NULL for that index |
| 3 | `0x00805AFF` to `0x00805B01` | `IgnoreIfAnticategoryActive` (`ModifierList+0xD3`) is set and an anticategory of the same index is still live |
| 4 | `0x00805B9C` to `0x00805CD1` | `ReplaceInCategoryIfLongest` (`ModifierList+0xD2`) is set and an existing entry of the same `Category` expires later or at the same frame |

Exit 4 is the important one, and its comparison is the crux:

```asm
00805b4c  mov  al, [edi+0xd2]            ; ReplaceInCategoryIfLongest
00805b56  test al, al
00805b58  je   0x805b97                  ; not set -> no scan, cannot refuse here
00805b5a  mov  esi, [ebx+0x20]           ; walk the holder's entries, stride 0x10
00805b5f  push [esi]
00805b61  mov  ecx, [0xde3c14]           ; TheAttributeModifierStore
00805b67  call 0x6146e0
00805b6c  mov  ecx, [ebp-0x14]
00805b6f  cmp  [esi], ecx
00805b71  je   0x805b8f                  ; the same list -> not a rival, skip
00805b73  mov  ecx, [edi+0xc]            ; the incoming Category
00805b76  cmp  ecx, [eax+0xc]
00805b79  jne  0x805b8f                  ; a different Category -> skip
00805b7b  mov  ecx, [ebp+0xc]            ; the new expiry frame
00805b7e  cmp  [esi+8], ecx              ; the existing entry's expiry
00805b81  jae  0x805b9c                  ; existing lasts at least as long -> FALSE
```

Two properties make this fire far more often than "longest wins" suggests. A list re-applying
*itself* is skipped, so the refusal is always caused by a **different** list sharing the `Category`.
And `Duration = 0` does not mean "instant":

```asm
00805b39  mov  dword [ebp+0xc], 0x3fffffff
```

A zero duration becomes expiry `0x3FFFFFFF`, the maximum. **A permanent modifier therefore outlasts
everything, so any shorter list of the same `Category` with `ReplaceInCategoryIfLongest = Yes`
applied to that object is refused unconditionally, forever.**

## 4. Why Last Winter

`SpecialAbilityLetzterWinter` is an `OCLSpecialPower` spawning `LetzterWinterObject`, which fires
`LetzterWinterWeapon` once. One of its six `AttributeModifierNugget`s is:

```
AttributeModifierNugget
    AttributeModifier   = LetzterWinterModifier
    Radius              = 100000
    SpecialObjectFilter = ANY +FS_FACTORY +FS_CASH_PRODUCER +ECONOMY_STRUCTURE +VITAL_FOR_BASE_SURVIVAL -BASE_FOUNDATION ENEMIES
End

ModifierList LetzterWinterModifier
    Category       = SPELL
    Modifier       = PRODUCTION 75%
    Duration       = 60000
    ModelCondition = SNOW
End
```

Radius `100000` is the whole map, and the filter is a precise description of the buildings that
carry `CommandPointBonus`. `LetzterWinterModifier` sets neither flag, so it is never itself
refused — it is the **blocker**, not the victim. For 60 seconds every economy building the victim
owns carries a `SPELL` entry expiring at `now + 60000`.

Edain has 30 `SPELL`-category lists with `ReplaceInCategoryIfLongest = Yes`, and all but one outlier
are shorter than 60 seconds:

| list | Duration |
|---|---|
| `ErestorBeaufsichtigungModifierEconomy` / `Military` / `Forges` / `Library` | 3000 |
| `SarumanCuromo`, `SarumanCuromoOrthanc`, `SarumanCuromo2`, `ThorinGebaudeRingBonus` | 10000 |
| `DenethorSteuererlassModifier` | 12400 |
| `OrophinRageBuff`, `ThranduilReinigungBuff`, `FellStrengthModifier` and six more | 30000 |
| `Jagdinstinkt` | 60000 |

The `ErestorBeaufsichtigung*` family is the worst case: a building aura on a 3-second refresh aimed
at economy structures. Inside Last Winter's window every one of those re-applications is refused at
exit 4, and every refusal deletes that building's entire command-point contribution. One cast can
therefore drain the same building around twenty times, across every economy building the victim
owns.

`Player+0x6C` goes deeply negative. `getCommandPointCap` adds it to the base before the `min`, so
the cap collapses; the palantir draws the collapsed number and `hasEnoughCommandPoints` refuses
everything with a nonzero cost. That is the reported symptom in both halves.

### The standing version of the same bug

Four cap-granting lists are `Category = SPELL` with `Duration = 0`, so they sit at expiry
`0x3FFFFFFF` permanently: `DwarvenMineShaftBonusLevel2` / `Level3` and
`WildMineShaftProductionBonus1` / `2`. On a levelled mineshaft, **every** `SPELL`-category
`ReplaceInCategoryIfLongest` application is refused for the rest of the game, with no Last Winter
needed. This is an independent prediction worth testing first, because it needs no ability and no
timing.

The `STRUCTURE` category is clean by luck: none of Edain's 154 permanent `STRUCTURE` lists — the
`CommandPoints_UpgradeLvl*` and `*LevelNProduction` families that carry most of the cap — has
`ReplaceInCategoryIfLongest` set, so they neither refuse nor get refused.

## 5. The defeat variant, not closed

The sibling routine `0x006914B7` moves an object's accounting between two players:

```asm
006914bc  cmp  dword [ebp+8], 0
006914c3  je   0x691521                  ; no old player -> do NOTHING
006914c5  cmp  dword [ebp+0xc], 0
006914c9  je   0x691521                  ; no new player -> do NOTHING
006914cb  mov  ecx, [ebp+8]
006914ce  push esi
006914cf  call 0x6aa590                  ; subtract from the old
006914d4  mov  ecx, [ebp+0xc]
006914d7  push esi
006914d8  call 0x6aa56d                  ; add to the new
```

Both halves are skipped together, so a transfer to or from "no player" leaves the charge on the
original owner — an *inflation*, not a loss, and the wrong direction for this report. The likelier
explanation for the defeat cases is the same §2 leak reached through the ownership churn that
follows a defeat, since every aura affecting the transferred buildings re-applies under the new
owner. Not established; it needs a runtime reading.

## 6. Confirming it in a game

`sage_live` reads `Player+0x6C` directly, and the sign is the whole test: the field is a sum of
non-negative template bonuses, so **a negative value is proof of the leak** and no other mechanism
produces one.

1. `python -m sage_live info` on a seat that owns levelled economy buildings; note base, bonus, hard
   cap.
2. Reproduce — the mineshaft case of §4 is cheapest, Last Winter against a built-up economy is the
   reported one.
3. Read again. A bonus that has fallen, and especially one below zero, confirms it.

## 7. Fixing it

The minimal correct change is at `0x0068F23A`: on the failure branch, re-add before returning FALSE.
The object's state is unchanged, so the value `0x006A7C01` computes is the one that was just
subtracted. `bl` is already the "did we subtract" flag and `edi` still holds the player, so the
repair is the same three instructions the success path uses.

Better, and larger: do the subtraction only once the apply has succeeded. That needs the apply's
result before the accounting, which means restructuring rather than a hook, so the failure-path
re-add is the patch-shaped fix.

Neither is written yet.
