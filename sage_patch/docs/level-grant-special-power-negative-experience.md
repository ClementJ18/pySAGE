# Negative Experience for LevelGrantSpecialPower

`level-grant-special-power-negative-experience` enables negative values of the existing
`LevelGrantSpecialPower.Experience` INI parameter in RotWK `game.dat` build
`2.01.2614.37001`. Positive XP grants remain unchanged; zero still skips XP processing.
Negative XP follows the existing target ExperienceTracker path.

```ini
Behavior = LevelGrantSpecialPower ModuleTag_ExperienceDrain
    SpecialPowerTemplate = SpecialAbilityExperienceDrain
    Experience = -250
    RadiusEffect = 100
End
```

The parser already accepts a signed integer. No new INI field or Worldbuilder patch is needed.
Target selection, `AcceptanceFilter`, radius and horde deduplication are unchanged.
An XP deduction does **not** automatically lower the unit's level. Maximum-level special
cases are deliberately unsupported: the existing `CanGainExperience` check remains intact.

## Apply and verify

```sh
python -m sage_patch apply level-grant-special-power-negative-experience --in game.dat.backup --out game.dat
python -m sage_patch verify level-grant-special-power-negative-experience game.dat
```

For Python callers, `sage_patch.LevelGrantSpecialPowerNegativeExperiencePatch()` can be passed
to `apply_patches`. The patch has no options and is independently selectable in the registry.

## Evidence and byte edit

The supplied Ghidra analysis identifies the XP distribution routine at VA `0x008C6E82`:

```asm
008C6E89  MOV  ESI, [ECX+04h]
008C6E8C  MOV  EAX, [ESI+0D0h]
008C6E92  TEST EAX, EAX
008C6E94  PUSH EDI
008C6E95  JLE  008C6F2C
```

The `0xE0`-byte ModuleData stores signed `Experience` at `+0xD0`, `RadiusEffect` at `+0xD4`,
`AcceptanceFilter` at `+0xD8` and `LevelFX` at `+0xDC`. `PUSH EDI` preserves the test flags.
Replacing `JLE` with `JE` rejects only zero and allows negative XP into the original processing.

| VA | Original | Replacement |
| --- | --- | --- |
| `0x008C6E95` | `0F 8E 91 00 00 00` (`JLE`) | `0F 84 91 00 00 00` (`JE`) |

Only `0x008C6E96` changes, from `8E` to `84`. The six-byte instruction and its displacement
`0x91` remain the same, so both branches target `0x008C6F2C`. `file_offset` maps the VA through
the PE section table. `apply_byte_patch` verifies all six original bytes before writing and
raises `ValueError` on a mismatch. `verify` checks the complete replacement instruction;
the standard `detect` implementation recognizes it. No code cave or new patch mechanism is used.

The supplied analysis also identifies target processing at `0x008C6F32`, XP forwarding at
`0x008C6D43`, the tracker eligibility check at `0x0079D322` and XP processing at `0x0079D833`.
Individual targets use signed `CVTSI2SS`; hordes use signed `FILD` followed by division by the
member count. These routines and conversions are untouched.

## Scope and validation

This is an ordinary patch module using the existing registry and byte-patch helper. Future
XP-drain sources, level-down and SciencePurchasePoints changes can be separate, independently
registered patches; this patch introduces no shared abstraction or XP storage.

It does not bypass eligibility, change global tracker routines, undo upgrades, bonuses or
abilities, alter `AwardXPForTriggering` or `SkillPointsForTriggering`, or manipulate available
SciencePurchasePoints. Actual level-down and maximum-level handling belong to future work.

Data-free tests cover every original and replacement byte, rejection without mutation, VA
mapping with different raw offsets, single-byte output, instruction decoding, signed branch
execution, CLI registration/application/verification and composition with `commandset-limit`
in both orders. Capstone and Unicorn tests use the existing optional test dependencies.

A `full` integration test uses `tools/BFME-FILES/game.dat.backup` and skips when that local
unpatched binary is absent. The supplied supported binary passes this test. No in-game
tests were performed. In-game testing must confirm XP deductions for individual units and
hordes, positive/zero behavior, filter/radius/deduplication behavior, retention of the current
level and the unchanged eligibility restrictions, including maximum-level units.

Tests run with Python 3.13 cover the supplied original binary, including composition in both
orders with [experience-level-down](experience-level-down.md). That separate patch supplies
actual level-down and removal of lost level effects; this minimal patch remains independent.
