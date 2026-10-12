# Dynamic XP lower and upper bounds

The `xp_cap=True` option of [ExperienceLevelDownPatch](experience-level-down.md)
bounds XP by the lowest and highest eligible level thresholds in RotWK
`2.01.2614.37001`. It is disabled by default and enabled with `--xp-cap`.
The downward helper, lost-effect removal, delayed-grant cancellation and explicit level setter are
not rewritten. [upgrade-module-removal](upgrade-module-removal.md) is optional.

For a highest allowed threshold of 1,000 XP:

| Before | Change | After |
| --- | --- | --- |
| Rank 9, 950 XP | +200 | Rank 10, 1,000 XP |
| Rank 10, 1,000 XP | +500 | Rank 10, 1,000 XP |
| Rank 10, 1,000 XP | -100 | 900 XP, with native level-down effects |
| Rank 10, 1,500 XP from an old save | -100 | Normalize to 1,000, then subtract: 900 XP |

With a first eligible level requiring 1 XP, `1 - 100` stays at `1`, while
`35 - 100` becomes `1` and still triggers any required level-down. If that first
level instead requires `0`, the lower bound is `0`. Other level definitions supply
their own lower threshold; no fixed global minimum of one is imposed.

No fixed rank or XP limit is used and no INI parameter is added.

## Bounds and XP processing

The same native collection lookup (`0x0068931C`), effective-record resolver
(`0x00688D3C`) and mode predicate (`0x00688DB0`) used by level-down select the highest
allowed rank. A positive configured `tracker+0x28` excludes higher ranks; a zero or
negative MaxRank retains the engine's unbounded rank convention. The ceiling is
that record's `RequiredExperience` at `+0x18`, converted to a float as native XP
storage requires. Same-rank aliases choose the greater threshold; exact ties use
collection order. Missing collections or no eligible records leave stock behavior.

The same collection scan also selects the lowest eligible rank for the floor,
with lower threshold breaking same-rank ties and collection order breaking exact
ties. Both bounds use the same SP/MP and MaxRank filters. The lowest record's
`RequiredExperience` at `+0x18` supplies the lower bound, using native float storage.

The relative XP path retains the native trainability, SSE scaling and x87 adjustment.
Both adjusted and unadjusted paths pass through the cap before the existing addition
window. Stored XP above the ceiling is normalized before applying the effective delta.
Results within the bounds retain the original delta and arithmetic. A result above
the ceiling is stored as the ceiling with an effective zero delta into the existing
addition/check path. This avoids rounding loss from subtracting and readding very
large floats. The native upward cascade still runs when below maximum rank; the
level-down maximum-rank guard is never reinstated on negative deltas.

A result below the floor normally replaces the effective delta with `floor - oldXP`.
Old XP is not prematurely overwritten, so the unchanged addition/downward path still
detects an actual loss and removes lost level effects. The cap checks the float32
sum of that replacement delta and old XP. If cancellation or infinity prevents an
exact floor result, it decides the direction before storing the exact floor, then
calls the existing `.xpdown` downward helper for a loss or native upward check for
a correction/increase. The helper address is resolved from the verified prerequisite
section; no new game hook or change to the level-down cave is introduced. Its native
feedback argument, register preservation and calling convention are retained.

The absolute setter at `0x0079D8EF` retains its ExperienceSink resolution, trainability
and feedback handling. Its input is bounded on both sides and any old upper reserve
is normalized before the existing
store/check window. A genuine decrease from normalized old XP uses the existing
downward helper. Normalizing a reserve alone does not demote an explicitly granted
level. NaN is not interpreted as a decrease or an ordered overflow.

A native next-level result above configured MaxRank is rejected before its virtual
grant, including equal-threshold definitions. The original mode filtering stays in
the native finder. Normal level data should have increasing thresholds with rank;
this patch does not repair contradictory or non-monotonic mod definitions.

Explicit level grants through `0x0079D76D`, scripts and LevelUpUpgrade keep their
native rank-setting behavior. The cap does not impose a general XP/rank reconciliation
on them. Old saves are normalized on the next relative or absolute XP operation,
not during deserialization. An old value below the floor is corrected if the computed
result is still below the floor. An upward correction does not demote an explicitly
granted rank; genuine subsequent losses keep the ordinary level-down behavior.

## Hooks and safety

All addresses are VAs, mapped with `file_offset` through the PE section table.

| Hook VA | Original bytes | Replacement |
| --- | --- | --- |
| `0x0079D6CD` | `38 55 0C 74 14` | `JMP rel32` to adjusted/unadjusted routing |
| `0x0079D6E1` | `F3 0F 10 45 FC` | `JMP rel32` to relative normalization/cap |
| `0x0079D921` | `F3 0F 10 44 24 08` | `JMP rel32` + `90` to absolute normalization/cap |
| `0x0079D17B` | `8B F8 85 FF 74 21` | `JMP rel32` + `90` to MaxRank grant guard |

These windows do not overlap the existing level-down hooks. The `.xpcap` section is
allocated dynamically with the standard allocator, executable/readable and code-only.
Relative jump bytes depend on the section location. Before writing either section,
all level-down anchors and these original windows must match. Unknown builds and reapplication fail before mutation. The integrated
verifier checks both complete helper bodies, their hooks and preserved native anchors.

An older upper-only `.xpcap` binary must be rebuilt from the clean backup with this
version. Reapplying over its existing cave is rejected; it is not silently upgraded
or overwritten. Existing generated binaries remain unchanged on disk.

Helpers preserve the integer registers and full XMM0/XMM1/XMM2 values except the
intended XP operand, and introduce no x87 operations, persistent state or dependencies.
Other tracker subclasses retain their existing behavior.

## Applying the combined patches

Run from the repository using Python 3.13. The source backup is never overwritten:

```powershell
.venv\Scripts\python.exe -m sage_patch apply level-grant-special-power --in tools/BFME-FILES/game.dat.backup --out tools/BFME-FILES/experience-follow-up/game.dat
.venv\Scripts\python.exe -m sage_patch apply experience-level-down --xp-cap --in tools/BFME-FILES/experience-follow-up/game.dat --out tools/BFME-FILES/experience-follow-up/game.dat
.venv\Scripts\python.exe -m sage_patch apply upgrade-module-removal --in tools/BFME-FILES/experience-follow-up/game.dat --out tools/BFME-FILES/experience-follow-up/game.dat
.venv\Scripts\python.exe -m sage_patch verify level-grant-special-power tools/BFME-FILES/experience-follow-up/game.dat
.venv\Scripts\python.exe -m sage_patch verify experience-level-down --xp-cap tools/BFME-FILES/experience-follow-up/game.dat
.venv\Scripts\python.exe -m sage_patch verify upgrade-module-removal tools/BFME-FILES/experience-follow-up/game.dat
```

Create the output directory first if needed. Python callers select
`ExperienceLevelDownPatch(xp_cap=True)`; select
`UpgradeModuleRemovalPatch()` independently before or after those patches.

## Validation and remaining game tests

Python 3.13 tests execute generated x86 and native XP addition, setter, upward cascade,
mode filters, state changes and delayed grants. Tests cover below/exact/above ceiling,
further maximum-level XP, losses through several levels, old reserves, different
MaxRanks, no configured limit, mode filtering, scaling, very large positive values,
absolute XP, explicit grants, reascending and a simulated restored tracker. Native
services and effect storage are modeled. Real-binary tests compose and verify all three
patches against the supplied original and confirm it is unchanged.

Floor coverage includes thresholds `0`, `1` and other configured values, unchanged
XP at the floor, actual level loss to the floor with modifier/OBJECT upgrade removal,
regaining levels, filtered first levels, a single eligible level, negative old
reserves, infinities, NaN remaining unordered, and cancellation at large float32
values. Tests compare the unchanged level-down cave and its hooks byte-for-byte
and assert that the set of four cap hook addresses remains identical.

No in-game follow-up tests were performed. In a map with known level thresholds,
gain enough XP to overshoot the last threshold, drain XP immediately, and verify the
expected lower rank and effects. Repeat with a lower MaxRank, SP/MP filters, scripts,
LevelUpUpgrade, revive, save/load and a save that contains an old reserve. Confirm
level effects, actual power activation, replay and multiplayer consistency. Native
float/integer conversion limits and arbitrary self-regrant/irreversible upgrade
callbacks remain engine/mod limitations rather than features of this cap.
