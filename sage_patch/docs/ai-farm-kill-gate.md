# Putting the AI's farm raids in the INI

The reverse-engineering behind [`patches/ai_farm_kill_gate.py`](../patches/ai_farm_kill_gate.py).
ROTWK `game.dat` build `2.01.2614.37001`, ImageBase `0x400000`, recovered statically 2026-10-11.
**Nothing here has been run in a match yet**; [§7](#7-what-remains) lists what a match has to show.

## TL;DR

- The skirmish AI's farm rush is one targetless tactic, **`AIFarmKillSquad`** (vtable
  `0x00C8A1E0`). Every 10 to 60 seconds it takes one to three idle units and walks them at an
  enemy economy building.
- Its squad is built with a forbidden `KindOf` mask of **`HERO`, `ARCHER`, `MACHINE`, `DOZER`**
  (`0x009BB491`). That is the whole of "the AI only sends melee units at farms": an `ARCHER` horde
  fails the mask.
- No INI field reaches the tactic. It is not driven by `TacticalAITargets`, so `OPPORTUNITY` and
  `TARGETLESS` entries there do not turn it on or off.
- In a mod with fixed build plots the raid is also the only tactic that deliberately attacks an
  enemy's outlying economy buildings, so switching it off costs map control. The patch therefore
  exposes its three dials rather than only an off switch.
- **The patch makes the tactic opt-in.** A faction raids only if its `ArmyDefinition` says
  `FarmKillSquad = Yes`, or leaves that unwritten and flags at least one member. An
  `ArmyDefinition` that writes neither stops raiding the moment the patch is installed.

| Block | Field | Effect |
| --- | --- | --- |
| `ArmyDefinition` | `FarmKillSquad = <Bool>` | `Yes`: that `Side` raids. `No`: it never does. Unwritten: it raids only if a member is flagged |
| `ArmyDefinition` | `FarmKillSquadSize = <min> <max>` | squad size, in place of 1-or-2 to 3 |
| `ArmyDefinition` | `FarmKillSquadInterval = <min> <max>` | seconds to the next squad, in place of 10 to 60 |
| `ArmyMemberDefinition` | `FarmKillerTeam = <Bool>` | this unit may join a squad, in every phase |
| `ArmyMemberDefinition` | `FarmKillerTeamPhase1` / `2` / `3 = <Bool>` | the same, for one phase |


## 1. The tactic

The source path the tactic pushes to its random-number calls names it:
`...\AITacticsGenerator\TargetlessTactics\AIFarmKillSquad.cpp` (`0x00C8A218`), and its constructor
pushes the literal `"FarmKillSquad"` (`0x009BB3D9`), which is also the team-name stem seen live as
`TARGETLESS_FarmKillSquad_48_0` in [`ai-flag-capture-gate.md`](ai-flag-capture-gate.md).

| Vtable slot | Address | What |
| --- | --- | --- |
| 1 | `0x009BB1C4` | Run gate: `__thiscall bool(arg)`, `ret 4` |
| 2 | `0x009BB226` | Reset: `__thiscall void()`; clears "running", rolls the next run frame |
| 3 | `0x009BB479` | Squad build: `__thiscall bool(prototype, index)`, `ret 8`; mask and size |
| 7 | `0x009BBE48` | Update: picks and re-picks the target |

The squad base class keeps the player at `+0x24`, the target `ObjectID` at `+0x58` and a
constructor coin flip at `+0x60`, as the flag-capture write-up already found for its sibling.

## 2. When it runs

The run gate, in full:

```c
record = TheSkirmishAIManager->playerData(this->player);     // 0x006A950B on [0x00DE4938]
if (!this->coin && record->field_16C <= 0) return false;      // +0x60, record+0x16C
if (record->get(IS_RUNNING) != 0) return false;               // key at 0x00DEBEF8
if (record->get(NEXT_RUN_FRAME) > TheGameLogic->frame) return false;   // key at 0x00DEBEFC
return record->hasSomething() != 0;                           // 0x006C7807
```

So **one squad is out at a time per player**. Slot 3 sets `IS_RUNNING` when it builds the team;
slot 2 clears it and stores `NEXT_RUN_FRAME = frame + GameLogicRandomValue(lo, hi)` through
`0x006C7EC5` (`__thiscall(key *, value)` on the record, `ret 8`), with `lo` and `hi` set by two
static initialisers (`0x00BC9CBE`, `0x00BC9CCC`) to **10 and 60 times the logic rate**.

`record+0x16C` and `0x006C7807` were not identified. Neither matters to wrappers that only add a
"no" or overwrite a value the stock code has just written.

## 3. Who it takes

The team recruiter (`0x009A2E06`, described in [`ai-team-size.md`](ai-team-size.md)) puts each
idle object to `0x009A24FC`, `__thiscall bool(object, prototypePart, where)` on the team builder,
`ret 0xC`, where `prototypePart` is the team prototype `+0x12C`. That test screens the object
against two `KindOf` masks: required at prototype `+0x2E0`, forbidden at `+0x2FC`. It has three
call sites; two are in the recruiter (`0x009A2EEB`, `0x009A2FFC`) and the third (`0x009A2B62`) is
in a routine with no callers.

Slot 3 writes the forbidden mask:

```asm
009bb48b  lea  eax, [esi+0x2fc]
009bb491  or   byte  [eax+0xb], 4        ; HERO     (90)
009bb495  or   dword [eax+0x10], 0x20    ; ARCHER   (133)
009bb499  or   byte  [eax+1], 0x48       ; MACHINE  (11), DOZER (14)
```

and sizes the team: min (`+0x2D4`) 1 or 2 by `record+0x16C`, max (`+0x2D0`)
`GameLogicRandomValue(min, 3)`.

For comparison, the other writers of that mask:

| Sizing | Tactic | Forbidden | Min / max |
| --- | --- | --- | --- |
| `0x009BC1A0` | `AIFlagCaptureSquad` | `HERO`, `MACHINE`, `DOZER` | 1 / random |
| `0x009B38DB` | an offensive tactic, vtable `0x00C8954C` | team 0: `CAVALRY`, `MONSTER`, `DOZER`; team 1: `HERO`, `MACHINE`, `DOZER` | 3 / 6 and 1 / 2 |
| `0x009B3307` | an offensive tactic, vtable `0x00C89460` | `ARCHER`, `DOZER` | 5 / 8 |
| `0x009B35EF` | a siege tactic, vtable `0x00C894B0` | none; team 0 *requires* `SIEGEENGINE` | 1 / 2 and 3 / 6 |

The last three were not matched to their source names.

This is why relabelling melee hordes as `ARCHER` - the INI workaround - stops the farm rush: the
squad can no longer recruit them. It also locks those hordes out of the `0x00C89460` tactic, has
the formation tactics place them where archers go (`push 0x85` at `0x009B5B1A`, `0x009B6853` and
four more), and leaves monsters and anything else unlabelled still raiding.

## 4. The data it reads

`ArmyDefinition` (field table `0x00C52B40`, referenced at `0x00830103` and `0x008302A0`):

| Offset | Field |
| --- | --- |
| `+0x00` | `Side` |
| `+0x04` / `+0x08` | `std::vector<ArmyMemberDefinition *>`, begin and end |
| `+0xB0`, `+0xB4` | `PhaseDuration_Rush`, `PhaseDuration_MidGame`, `Real` seconds |

`ArmyMemberDefinition` is 16 bytes: `Unit` (an `AsciiString`) and the three percentages. Its block
parser (`0x0082FEFE`) allocates it with `push 0x10` / `call operator new`, zeroes it inline,
parses it through the table at `0x00C52538` (referenced at `0x0082FC89` and `0x0082FF2A`) and
pushes the pointer onto the army's vector. The block's own name is not kept anywhere.

**Neither field table has a terminator.** The 47 `ArmyDefinition` rows are followed directly by a
vtable, the 4 member rows by another table's strings, and a reader walking to the first zero name
passes through whatever is there. The rebuilds copy only the rows whose name is a keyword and
terminate properly.

## 5. The patch

One cave (`.farmkil`), four wrappers, two rebuilt tables.

**Per-faction values** live in a 64-slot table at the cave's base: the `NameKey` of the block's
`Side`, the `FarmKillSquad` answer (0 unwritten, 1 `No`, 2 `Yes`), the size pair and the interval
pair. They are keyed on `Side` rather than
on the `ArmyDefinition` pointer for the reason [`ai-hero-build-delay.md`](ai-hero-build-delay.md)
gives. `FarmKillSquad` goes through the stock `Bool` parser into a local; the two pairs go through
the stock `Int` parser twice, with the pair's slot offset carried as the row's `userData`.

**Per-member flags** live in the member itself, which grows to 20 bytes: the allocation's size
immediate becomes `0x14` and its `call operator new` goes through a stub that clears the new
dword. `FarmKillerTeamPhase1`..`3` are plain rows through the stock `Bool` parser at `+0x10`,
`+0x11`, `+0x12`; `FarmKillerTeam` parses into the first and copies it to the other two.

**Run gate (slot 1).** Decides who may raid at all:

| `FarmKillSquad` | Any member flagged | Result |
| --- | --- | --- |
| `Yes` | either | stock routine |
| `No` | either | `false` |
| unwritten | yes | stock routine |
| unwritten | no | `false` |

`false` is returned with the stock `ret 4`. "Unwritten" covers both a faction with no slot and
one whose slot holds only a size or an interval. A player with no AI record or no
`ArmyDefinition` has no INI to have asked through and is left to the stock routine.

**Reset (slot 2).** Calls the stock routine, then, for a faction whose interval's max is positive,
stores `NEXT_RUN_FRAME` again as `frame + GameLogicRandomValue(min, max) * rate`.

**Squad build (slot 3).** Calls the stock routine, then:

1. sets `KindOf SKYBOX` (202) in the prototype's forbidden mask. No unit is a `SKYBOX`, so this
   changes who is recruited by nothing; it is the **mark** the recruiter's wrapper recognises a
   farm squad by, and it needs no state of the patch's own;
2. for an army with any flagged member, clears `ARCHER` from the forbidden mask;
3. for a faction whose size max is positive, writes min (at least 1) and
   `GameLogicRandomValue(min, max)` as the max.

**Recruit test.** The recruiter's two calls reach a wrapper that sends every unmarked team
straight to the stock test. For a marked one it first asks whether the candidate is eligible:

```c
army = playerData(builder->player)->armyDefinition;
phase = seconds < rush ? 0 : seconds < rush + midGame ? 1 : 2;
for (member in army->members) {
    if (!member->anyFlag) continue;
    someoneIsFlagged = true;
    if (member->flag[phase] &&
        object->template->isEquivalentTo(findTemplate(member->Unit))) return true;
}
return !someoneIsFlagged;        // nobody flagged: the stock rule stands
```

An eligible candidate still has to pass the stock test, so heroes, machines and builders stay out
whatever is flagged. Equivalence is `ThingTemplate::isEquivalentTo` (`0x0073D5C2`), so a member
that names an `EquivalentTo` child matches the parent's units and the reverse.

The phase is computed from the two phase lengths as the INI comments define them. How the unit
builder itself decides its phase was not read; if it differs, the flags follow this definition.

### Composition

`ai-hero-build-delay` repoints the `HeroBuildOrder` row in whatever `ArmyDefinition` table is
live, so the two apply in either order. `verify` here checks its own rows and its own code and
leaves the copied rows alone. Both orders were applied to this build and both patches verified.

The extra `GameLogicRandomValue` calls change the synchronised random sequence only for an army
that sets a size or an interval, and then identically on every machine running the same INI.

## 6. Using it

```ini
ArmyDefinition MenOfTheWestArmy
    Side                  = Men
    FarmKillSquadSize     = 3 5
    FarmKillSquadInterval = 90 240

    ArmyMemberDefinition AmrothKnightHorde_Member
        Unit                   = AmrothKnightHorde
        PercentageOfArmyPhase1 = 10
        PercentageOfArmyPhase2 = 20
        PercentageOfArmyPhase3 = 15
        FarmKillerTeamPhase1   = Yes
        FarmKillerTeamPhase2   = Yes
    End
```

- This army raids because it flags a member. With no flagged member it would need
  `FarmKillSquad = Yes`, and would then recruit by the stock rule.
- `FarmKillSquad = No` wins over flags: the flags are only read once a squad forms.
- `Side` has to come before the three `ArmyDefinition` fields; a line met before any `Side` is
  dropped.
- A pair needs both numbers. A max below the min is raised to it; a max of zero or less means
  unset.
- Flags do not split a unit's numbers between raiding and fighting. One squad is out at a time,
  so what they decide is which units that one squad may be made of.
- Once any member is flagged, a phase in which no flagged member exists has no eligible unit, and
  the squad waits unfilled until one does.
- **Size counts what `AI_TEAM_SIZE` counts.** Without [`ai-team-size`](ai-team-size.md) a
  battalion counts as its members plus itself, so the min is met by one battalion and only the max
  limits how many are taken in one pass. With it, both numbers are battalions.

## 7. What remains

- **A match.** Teams named `TARGETLESS_FarmKillSquad_*`: none for a faction that did not opt in, of the
  configured size and spacing for one that set them, and made only of flagged templates for an
  army that flags members.
- **The unit builder's phase**, to confirm the flags switch when production does.
- **`record+0x16C`, `0x006C7807`**, and the names of the three offensive tactics in §3.
- **The third caller of the recruit test** (`0x009A2B62`) is not wrapped. It sits in a routine
  nothing calls; if that turns out to be wrong, a farm squad recruited through it would ignore the
  flags.
