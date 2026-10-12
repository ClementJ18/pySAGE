# LevelGrantSpecialPower: signed XP and configurable target relationships

`level-grant-special-power` fixes signed XP and target selection in RotWK `game.dat` build
`2.01.2614.37001`: negative `Experience` now reaches the existing XP path, and
an additional fixed ALLIES filter no longer overrides the INI `AcceptanceFilter`.
It also applies negative SpecialPower XP once to the selected parent horde.
All parts are enabled together by `LevelGrantSpecialPowerPatch()`. A code-only
`.lgxp` section holds the local horde helpers; no INI parameter, dependency or
global ObjectFilter/positive-horde aggregation change is added.

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
contained-object iteration, other fixed safety filters and tracker eligibility
remain native. The parent-horde drain is additional and applies only to negative
SpecialPower Experience. This patch itself does not lower levels or special-case maximum
rank. [ExperienceLevelDownPatch](experience-level-down.md) supplies actual
level-down and XP bounds, now enabled by default. Use `xp_cap=False` /
`--no-xp-cap` to explicitly disable bounds.

## Apply and verify

```sh
python -m sage_patch apply level-grant-special-power --in game.dat.backup --out game.dat
python -m sage_patch verify level-grant-special-power game.dat
```

Python callers pass `sage_patch.LevelGrantSpecialPowerPatch()` to `apply_patches`.
There is one registration, no options, and no separate activation for these fixes.
The module is `sage_patch.patches.level_grant_special_power`.

The former `LevelGrantSpecialPowerNegativeExperiencePatch` class,
`level_grant_special_power_negative_experience` module and
`level-grant-special-power-negative-experience` ID are replaced, with no aliases. Update Python imports and patch manifests to the names above and
rebuild from the original binary. An older binary containing only the XP gate
change is not detected as the combined patch, and application to it is rejected
before writing. This also prevents applying the same feature twice. Existing
XP-only binaries are not silently changed. Binaries carrying the previous two-byte
version also require a clean rebuild: verification now requires the horde cave and
hooks. A modified global horde `JBE` is rejected; restore from the clean original,
not by layering this patch over the failed `JE` experiment.

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

## Local horde drain: control flow and ABI

The original member-distribution iterator at VA `0x008C6F01` is followed by a jump
to the shared epilogue. The horde branch reaches it only after obtaining a non-null
interface and a nonzero native member count. EBX is the selected horde object,
ESI is ModuleData, and EDI is the horde interface. The non-horde branch and empty
hordes bypass this hook. The earlier `0x008C6F32` routine resolves members to their
parent and deduplicates by the parent's ObjectID; that native code is unchanged.

| Hook | Original | Replacement |
| --- | --- | --- |
| `0x008C6EF7` | `68 43 6D 8C 00` (push member callback) | Push the cave's callback wrapper |
| `0x008C6F01` | `FF 90 10 01 00 00 EB 22` (iterator call, epilogue jump) | `JMP rel32` and three NOPs |

The completion helper first executes the displaced virtual `+0x110` iterator call
exactly once, with its original arguments. After its return, nonnegative INI XP
jumps directly to `0x008C6F2B`. Negative XP reads the parent tracker at
`Object+0x26C`, checks native eligibility at `0x0079D322`, converts the full signed
INI value with `CVTSI2SS`, then calls the existing XP wrapper at `0x0079D833`.
Its thiscall arguments are `(delta, adjust=0, scale=0, feedback=0, extra=0)` and its
callee pops `0x14` bytes. Thus `-500` reaches the wrapper once, not `-25` for every
member. Ordinary adjustment/scaling is disabled for this already-total INI value;
native ExperienceSink forwarding (including its transfer factor) remains active.
A configured sink receives the drain instead of forcibly changing the source tracker.

The absolute setter at `0x0079D8EF` was examined: it accepts a float and feedback
argument, pops eight bytes, and follows ExperienceSink references before storing.
Computing an absolute target from the source horde's XP and then passing it through
that redirection would use the wrong old XP for a different sink. The delta wrapper
avoids that problem and reaches the existing cap/add/level-down hooks. No level
numbers are copied and no separate level-selection algorithm is added.

The additional call preserves general registers, flags and complete x87/MXCSR/XMM
state with `PUSHFD`/`PUSHAD` and aligned `FXSAVE`/`FXRSTOR`, then resumes the original
epilogue. The original iterator remains responsible for member XP and LevelFX.
The existing level-down guard still requires the Object-specific tracker method
at vtable `+0x10` (`0x0079DA9D`). The native Object tracker constructor at
`0x0079D5E7` installs vtable `0x00C3148C`, whose slot matches that guard. Horde
object trackers use the Object-owned path, not their interface's group storage;
the guard is not broadened to arbitrary tracker classes.

## Why positive horde aggregation stays native

The group XP function at `0x00873A02` adds each member callback's float to the
matching group account, synchronizes matching members through `0x0086BC09` and
the absolute setter, then promotes the parent only when the group XP exceeds
parent XP. Its original `JBE` at `0x00873AAB` remains `76 2F` and is fingerprinted.
The new parent drain never calls the special horde rank-gain helper `0x008719E4`.
The original aggregation may still invoke that helper on a genuine upward change.

Positive SpecialPower XP does not receive an additional parent credit. Mixed group
keys cannot overwrite parent XP with a lower account. Combat XP never enters the
new SpecialPower wrappers. Counts come from the existing virtual member-count
method: neither 20, 21 nor 22 is hardcoded. The extra object's identity in the CE
log is unknown; the implementation does not assume it is a banner carrier.

## Negative group reserves

The native group account uses unbounded `ADDSS`. With member XP bounds active,
a `300 - 500` group balance can become `-200` while member trackers store their
floor (0 or 1). Later gains would first repay that hidden reserve. This is confirmed
by the native-code fixture and the group lookup returning `MapNode+0x14`.

Only the SpecialPower's member callback is wrapped. It calls the original callback
first, then checks a negative incoming delta, a nonnegative stored member XP and
an existing negative group account. It clears that account to zero, without
creating entries or editing global aggregation. Lookup uses the actual template's
16-bit group key at `+0x5E8`; the collection is at interface `+0x13C`, the key at
node `+0x10`, and XP at node `+0x14`. Positive callbacks, absent trackers/groups,
NaN group balances and genuinely negative member XP keep native storage behavior.
The added bookkeeping is integer-only and restores registers/flags after the
original callback. It leaves its floating-point state unchanged.

With `--no-xp-cap`, negative member XP and negative group reserves remain native.
This is an explicit opt-out from bounded XP; a later gain can repay those reserves.
Cleanup addresses negative reserves hidden by a nonnegative member floor, not a
general redesign of group bounds, positive reserves, spawning or synchronization.

## Safety and validation

Application fingerprints the full distribution/deduplication/member callback paths,
native group aggregation/sync/lookup code, XP wrapper and eligibility code, the
Object tracker constructor/virtual slot, and all edited instruction windows before
allocation or writing. A wrong build, a partial prior patch, a `.lgxp` section or
the failed global `JBE -> JE` experiment is rejected. Verification checks the entire
relocated cave, both existing instruction fixes, both new hooks and preserved
native anchors. Addresses/offsets are centralized and existing constants reused.

Python 3.13 tests execute actual special-power distribution, horde deduplication,
member/group XP arithmetic, native setter/wrapper/core XP routines and the existing
cap/level-down assembly. Contain iteration, collection allocation, effect storage,
engine services and special upward-horde bookkeeping are modeled. Coverage includes
homogeneous and mixed groups, two hordes, repeated member hits, signed/extreme
losses, recovery after the floor, positive powers/combat compared with the same
native baseline, sink/eligibility/type guards, absent trackers/interfaces/counts,
state preservation, original-byte rejection, cave verification and real-binary
composition with other patches. Full tests skip if the supported backup is absent.

No in-game test has been performed. The supplied CE findings support the selected
paths, but real game/mod behavior still needs test-map validation: positive and
negative effects on own/allied/enemy targets; mixed groups and radii; actual contain
ordering and spawned/replaced members; horde bonuses/upgrade removals and UI; and
save/load and multiplayer. Nonstandard tracker classes remain excluded from rank
rollback. The extra logged object's identity and the 21-versus-22 callback count
remain unresolved and are not assumptions used by the implementation.
