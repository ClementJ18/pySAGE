# LevelGrantSpecialPower: signed XP and configurable target relationships

`level-grant-special-power` fixes two restrictions in RotWK `game.dat` build
`2.01.2614.37001`: negative `Experience` now reaches the existing XP path, and
an additional fixed ALLIES filter no longer overrides the INI `AcceptanceFilter`.
Both changes are always enabled together by `LevelGrantSpecialPowerPatch()`.
No new INI parameter, code cave, dependency or global ObjectFilter change is added.

```ini
Behavior = LevelGrantSpecialPower ModuleTag_ExperienceDrain
    SpecialPowerTemplate = SpecialAbilityExperienceDrain
    Experience = -250
    RadiusEffect = 100
    AcceptanceFilter = ANY +HERO ENEMIES
End
```

The parser already accepts signed integers. Positive XP remains supported, and
zero still skips XP processing. XP conversions, radius, horde deduplication,
contained-object processing, other fixed safety filters and tracker eligibility
remain native. This patch itself does not lower levels or special-case maximum
rank. [ExperienceLevelDownPatch](experience-level-down.md) supplies actual
level-down and optional XP bounds through `xp_cap=True` / `--xp-cap`.

## Apply and verify

```sh
python -m sage_patch apply level-grant-special-power --in game.dat.backup --out game.dat
python -m sage_patch verify level-grant-special-power game.dat
```

Python callers pass `sage_patch.LevelGrantSpecialPowerPatch()` to `apply_patches`.
There is one registration, no options, and no separate activation for either fix.
The module is `sage_patch.patches.level_grant_special_power`.

The former `LevelGrantSpecialPowerNegativeExperiencePatch` class,
`level_grant_special_power_negative_experience` module and
`level-grant-special-power-negative-experience` ID are replaced, with no aliases. Update Python imports and patch manifests to the names above and
rebuild from the original binary. An older binary containing only the XP gate
change is not detected as the combined patch, and application to it is rejected
before writing. This also prevents applying the same feature twice. Existing
XP-only binaries are not silently changed.

## Two independent instruction fixes

Every address here is a RotWK VA, mapped with `file_offset` through PE sections;
RVA and raw file offset are not interchangeable. Addresses and original signatures
are centralized in `sage_patch/addresses/objects.py`, re-exported by
`sage_patch.addresses`.

| Instruction VA | Original | Replacement | Changed byte VA |
| --- | --- | --- | --- |
| `0x008C6E95` | `0F 8E 91 00 00 00` (`JLE`) | `0F 84 91 00 00 00` (`JE`) | `0x008C6E96`: `8E` to `84` |
| `0x008C7018` | `C7 45 B8 04 00 00 00` | `C7 45 B8 07 00 00 00` | `0x008C701B`: `04` to `07` |

The first instruction follows `TEST EAX,EAX` and `PUSH EDI` in XP distribution
at `0x008C6E82`. Changing `JLE` to `JE` skips only zero; the six-byte instruction
and target `0x008C6F2C` are unchanged. Individual objects use signed `CVTSI2SS`,
and hordes use signed `FILD` followed by division by member count. The underlying
XP forwarding and eligibility routines are untouched.

The second instruction constructs a local relationship filter in
`LevelGrantSpecialPower::triggerAbilityEffect`, VA `0x008C6FA4`. Its original
mask `4` allows only ALLIES; mask `7` allows ENEMIES (`1`), NEUTRAL (`2`) and
ALLIES (`4`). Instruction length remains seven bytes; the other six bytes stay
identical. The immediate is RVA `0x004C701B` at ImageBase `0x00400000`.

The supplied binary confirms the fixed filter vtable at `0x00C11DC0`:
destructor `0x00893738`, `allow(Object*)` at `0x00660B85`, and `getPlayerMask()`
at `0x00660B3E`. The allow function calls `0x0068D7AB` to obtain the relationship
and tests `flags & (1 << relationship)`. The player-mask function maps flags `4`
to mask `3` and flags `7` to mask `15`. Changing the construction fixes both
queries without editing these shared functions.

The local flag after the mask is written from `CL` at `0x008C701F` in this binary;
the preceding `XOR ECX,ECX` clears it. This differs in encoding from a literal-zero
MOV in the supplied schematic disassembly but has the same value and is untouched.

## AcceptanceFilter and ModuleData

The existing wrapper vtable at `0x00BE4CC8` and INI ObjectFilter implementation
remain unchanged. The broadened fixed relationship mask admits candidates; the
existing `AcceptanceFilter` still decides which candidates match:

| Configured relationship condition | Remaining selection rule |
| --- | --- |
| No relationship restriction | All relationships, subject to other filters |
| `ENEMIES` | Enemies |
| `ALLIES` | Allies under the existing ObjectFilter semantics |
| `SAME_PLAYER` | Objects belonging to the same player |
| Additional KindOf criteria | Only matching objects within the allowed relationships |

The RotWK ModuleData is `0xE0` bytes. Its parse table is at `0x00C73550`:

| Field | Offset |
| --- | --- |
| `Experience` | `+0xD0` |
| `RadiusEffect` | `+0xD4` |
| `AcceptanceFilter` | `+0xD8` |
| `LevelFX` | `+0xDC` |

The effect loads ModuleData through `[EDI+4]` at `0x008C6FBE` and takes the filter
address with `LEA EDX,[EBX+0xD8]` at `0x008C6FDA`. The table points to the
AcceptanceFilter parser at `0x0076392F`. These are RotWK offsets, not the older
BFME2 reconstruction layout.

The central address module also records the supplied module instance/data factories
(`0x006517D5`, `0x00651810`), runtime constructor (`0x008C6CFA`), runtime vtable
(`0x00C735A0`) and effect entry (`0x00C735E4`), filter-chain linking (`0x00A394C0`),
partition search (`0x00A39340`) and per-object callback (`0x008C6F32`). These are
reference addresses; applying this patch depends only on its two instruction windows.

## Safety and validation

Application verifies all six original XP-gate bytes and all seven original mask
instruction bytes before changing either site. Mismatches raise the existing
`ValueError` failure. The standard byte-patch helper applies the XP instruction
replacement and the single mask byte. Verification and detection require both
complete replacement instructions. No global filter, vtable or tracker is patched.

Python 3.13 tests cover both complete original signatures, rejection before
mutation, every replacement byte, unchanged instruction lengths/XP branch target,
signed XP execution, native relationship/player-mask fragments, one registration,
CLI round trips and composition with other patches. Full tests use
`tools/BFME-FILES/game.dat.backup` and skip when it is unavailable; they check
that exactly two bytes differ and that the original is unchanged.

No in-game test has been performed. A test map must confirm positive XP on own,
allied and enemy units; negative XP on own/enemy units with level-down enabled;
`ENEMIES`, unrestricted, `ALLIES` and `SAME_PLAYER` filters; mixed radius targets;
and horde/contain processing. KindOf filtering, save/load and actual game eligibility
remain native paths to check in game. Automated relationship tests exercise the
confirmed bit-mask code, not the complete spatial search or INI-filter pipeline.
