# Flag-capture squads that stall forever on a built-on plot

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`). The static work is
against this repo's `game.dat`; §1 and §6 are measured off a **live, paused match** read with
`sage_live`, and every figure in them is from one frame (1118) of that match.

**The report.** An allied skirmish AI walks a battalion or two up to an enemy building and then
never attacks it — they circle it for the rest of the match. Reported as happening often, on
several maps, and predating any patch.

**Verdict up front.** Explained, measured end to end, and patched. Two of the skirmish AI's
targetless tactics disagree about what an enemy economy plot is. `AIFarmKillSquad` correctly
holds the *structure* on it in its raid list; `AIFlagCaptureSquad` also holds the *flag under
it* in its capture list, cannot tell a build plot from a plain capture flag, takes the nearest,
and has no timeout. The squad that wins the race parks on top of a building it is not even
trying to attack. `ai-flag-capture-gate` adds the one missing rejection.

## 1. What the running game said

Two battalions of `Player_3` (an Imladris AI) stood at an Isengard economy plot, `MOVING`, with
`NO_AUTO_ACQUIRE` set, health untouched. Two other battalions of the same player were fighting
normally 900 units away. Reading both pairs is what separates cause from symptom.

| object | template | team | AI state | goal | state's status mask |
|---|---|---|---|---|---|
| 504 | `ImladrisHobbitBoundersHorde` | `TARGETLESS_FlagCaptureSquad_119_0` | `AIMoveToStateSA` | object 278 | `NO_AUTO_ACQUIRE` |
| 540 | `ElvenRivendellLancerHordeMod` | `TARGETLESS_FlagCaptureSquad_119_0` | `AIMoveToStateSA` | object 278 | `NO_AUTO_ACQUIRE` |
| 454 | `ImladrisGildorCompanionHorde` | `ENEMY_STRUCTURE_FormationAttack_80_0` | `AIAttackMoveToState` | attack target 586 | `IS_ATTACKING` |
| 471 | `ImladrisGildorCompanionHorde` | `ENEMY_STRUCTURE_FormationAttack_80_0` | `AIAttackMoveToState` | attack target 335 | `IS_ATTACKING` |
| 552 | `BruchtalLancerHorde` | `teamPlayer_3` | `AIGuardState` | — | none |

Object **278** is a `WirtschaftPlotFlag_Real` owned by the enemy, and object **529**, an
`IsengardMinenschacht_ExternB` with 2500 hit points, stands at *exactly* the same coordinates —
`(1554.45, 2253.73, 150.0)` for both. The mineshaft's geometry is a `BOX` of
`GeometryMajorRadius = 56.528`, so the flag sits at the centre of a 113×113 impassable
footprint. The two battalions were 100.9 and 88.8 units out: pressed against it.

The flag itself can never be an attack target. Its `KindOf` carries `UNATTACKABLE`, its body is
`ImmortalBody MaxHealth 1`, and its armour is `InvulnerableArmor`. The two stalled hordes carry
no attack target at all — `AIUpdate+0x40` is empty on both, against 586 and 335 on the two that
are fighting.

So the stall is not a failed attack. It is a **move order that can never complete**, on an
object that was never going to be attacked, in a state that suppresses the
`AutoAcquireEnemiesWhenIdle = YES ATTACK_BUILDINGS` both hordes declare on their own
`HordeAIUpdate`.

### 1a. Reading AI state out of a live game

These offsets are what made the table above possible, and they are reusable for any AI stall.

| offset | field | how it was established |
|---|---|---|
| `Object+0x24C` | `BehaviorModule*[]`, NULL-terminated | already in [`live-object-model.md`](live-object-model.md) §5 |
| module `+0x00` | vtable — `0x00C66D48` is `HordeAIUpdate` | [`horde-formation-orphans.md`](horde-formation-orphans.md) §3 |
| `AIUpdate+0x30` | `StateMachine*` | its target's first dword is the state-machine vtable `0x00C2B330`, written by the constructor at `0x00753755` |
| `AIUpdate+0x40` | current attack target `ObjectID` | set on both fighting hordes, naming exactly what each was hitting; absent on both stalled ones |
| `AIUpdate+0x2DC` | the status mask the current state imposes | `0x00800000` (`NO_AUTO_ACQUIRE`) on both movers, `0x00400000` (`IS_ATTACKING`) on both fighters, `0` on the guard — and each object's real status word carried exactly that bit, 5 of 5 |
| `SM+0x04` | current `State*` | its vtable's slot 2 is a `mov eax, <name>; ret`, which reads back `AIMoveToStateSA`, `AIAttackMoveToState`, `AIGuardState` |
| `SM+0x20` | goal `ObjectID` | 278 on both stalled hordes |
| `SM+0x24`..`+0x2C` | goal position | `(1554.45, 2253.73, 150.0)` — the flag's own position, to the float |

`AIMoveToStateSA` is state id `0x3F` of the main `AIStateMachine`; its constructor is
`0x00741A7B`, its vtable `0x00C28560`, and it is registered exactly once, at `0x00753839`.

## 2. The tactic, and where it comes from

Not mod script. The build paths left in `.rdata` name the whole family:

```
GameLogic/SkirmishAI/AITacticalAI/AITacticsGenerator/TargetlessTactics/AIFlagCaptureSquad.cpp
```

with siblings `AIFarmBuilderTactic`, `AIRoamingDefenseTactic`, `AILumberMillBuildTactic`,
`AIStructureCreepTactic` and `AIFarmKillSquad`, alongside `OffensiveTactics/` (feint, pincer,
flank), `ExpansionTactics/` and `AITacticDefensive`.

| thing | address |
|---|---|
| `AIFlagCaptureSquad` constructor | `0x009BC093` |
| primary vtable | `0x00C8A2FC` |
| `"FlagCaptureSquad"` push, in the constructor | `0x009BC0A2` |
| run gate (vtable slot 1) | `0x009BC39F` |
| squad build (slot 3) | `0x009BC1A0` |
| update (slot 7) | `0x009BC3F4` |
| **flag picker** | `0x009BC213` |
| its one call site, inside the update | `0x009BC477` |
| `AIFarmKillSquad` constructor / vtable / update | `0x009BB3CA` / `0x00C8A1E0` / `0x009BBE48` |

The gate reads two per-player dictionary entries, `AIFlagCaptureSquad_IsRunning` and
`AIFlagCaptureSquad_FrameNextRun`, and refuses if either says no. On finishing it re-arms with
`FrameNextRun = now + GameLogicRandomValue(min, max)`, where the bounds are the statics at
`0x00DEBF14` and `0x00DEBF18` — initialised as `[0x00D9F608] × 20` and `× 90`, which read **100
and 450 frames** live. So the tactic gets a fresh chance every few seconds per player, which is
why a log fills with `creating team instance` lines for it.

The squad build sets a unit `KindOf` filter and a size of `GameLogicRandomValue(1, 3)`. It does
**not** require that any member can capture anything: the stalled squad above drew a Rivendell
Lancer battalion, which carries no `CaptureBuilding.inc` at all.

## 3. The picker, in full

`0x009BC213`–`0x009BC302`. Short enough to state completely:

```c
Object *AIFlagCaptureSquad::pickFlag()
{
    Vec3 anchor = {0, 0, 0};
    getSquadAnchorPosition(&anchor);

    ObjectIDVector list = copyOf(*(TheSkirmishAIManager + 0xA68));   // every capture flag on the map

    Object *best = NULL; float bestDistSq;
    for (ObjectID *it = list.begin; it != list.end; ++it) {
        Object *o = TheGameLogic->findObjectByID(*it);
        if (player->getRelationship(o) == ALLIES) continue;          // 0x009BC28B  <-- the only filter
        if (!(((u8 *)o->tmpl)[0x121] & 0x10)) continue;              // 0x009BC293  KindOf CAPTUREFLAG
        float d2 = sq(o->x - anchor.x) + sq(o->y - anchor.y);
        if (!best || bestDistSq > d2) { bestDistSq = d2; best = o; }
    }
    return best;                                                      // caller stores ->m_id at squad+0x58
}
```

`0x00DE4938` is `TheSkirmishAIManager`, already tabulated in
[`engine-globals.md`](engine-globals.md). Read live, `+0xA68` held 20 entries — every
`CAPTUREFLAG` object on the map, including object 278.

`Player::getRelationship(Object*)` is `0x006ADC43`: null object → 1, otherwise the object's team
through `Player::getRelationship(Team*)` at `0x006ACEAF`, which looks the team up in the map at
`Player+0x350` and **defaults to 1 for a team it does not list**. `ENEMIES` is 0, `NEUTRAL` 1,
`ALLIES` 2 — and the live evidence settles the branch's meaning independently, because the AI
demonstrably *did* pick an enemy-owned flag, so `== 2` cannot be the enemy case.

Three things the picker never asks: whether the plot already carries a structure, whether it is
enemy-held, and whether any member of the squad can capture. It takes the nearest.

## 4. Why the lock is permanent

`AIFlagCaptureSquad::update` (`0x009BC3F4`) re-picks only when the stored target
(`squad+0x58`) is zero, and clears it in exactly two cases: the flag object is gone, or its
relationship has become `ALLIES`. There is no deadline and no progress check.

The contrast with its sibling is the whole story. `AIFarmKillSquad`'s update (`0x009BBE48`)
drops its target when the object is `DESTROYED` (`[obj+0x94] & 1`), when a second flag at
`[obj+0x458]` is set, and — for a `BLOCKING_GATE` target — once that gate's
`GateOpenAndCloseBehavior` reports open. Its picker scores candidates through a float-returning
helper at `0x009BB2A7` that weighs distance against a per-object factor, and rolls
`GameLogicRandomValue(0, 4)` to sometimes take a second picker's answer instead. The raid tactic
has real completion conditions; the capture tactic has one that an uncapturable flag can never
satisfy.

And the raid tactic *already knows about this building*. Its candidate list is per-enemy-player,
at `map[TheSkirmishAIManager + 0xA3C][playerIndex] → record+0x0C`. Read live for the enemy:

```
IsengardMinenschacht_ExternA
IsengardMinenschacht_ExternB    <- object 529, the building being orbited
IsengardFurnace
```

The engine had dispatched one: `TARGETLESS_FarmKillSquad_48_0`, two `ImladrisWaffenmeister`,
both dead at the edge of the Isengard base. The two tactics run concurrently on independent
cooldowns — the capture squad is not an alternative to a raid, it is a second squad walking to
the same place for a different and impossible reason.

## 5. The discriminator

`CAPTUREFLAG` covers two unrelated kinds of object, and the mod data separates them cleanly:

| object | `BASE_SITE` | what it is |
|---|---|---|
| `FestungPlotFlag_Real` | yes | fortress plot |
| `LagerPlotFlag_Real` | yes | camp plot |
| `WirtschaftPlotFlag_Real` | yes | economy plot |
| `DefensivePlotFlag` | yes | defence plot |
| `ExpansionPlotFlag` | yes | expansion plot |
| `HalfCastlePlotFlag_Real` | yes | half-castle plot |
| `CaptureFlag` | **no** | a flag recaptured by standing on it |
| 2 × campaign hobbit objects | **no** | campaign only |

A plain `CaptureFlag` is exactly what the tactic is *for*, and it must keep working whoever
holds it — so `BASE_SITE` has to be asked first and on its own. `BASE_SITE` is `KindOf` bit
**120**, from the engine's own name table: `template+0x108 + 15`, bit `0x01`.

Ownership is the wrong second question. It would need the gate to decide what `NEUTRAL` means
for the civilian player who holds unclaimed plots, and an ownership test alone still gets an
enemy plot that is merely *claimed but unbuilt* wrong in the other direction.

The engine keeps a better answer. Across all 20 capture flags of the live match:

- unclaimed plot → status `UNATTACKABLE` only
- claimed plot → status `UNATTACKABLE | UNSELECTABLE`

20 of 20, including three fortress plots owned by real players that carry no structure at the
flag's own coordinate. `UNSELECTABLE` is `ObjectStatus` bit **3**, `Object+0x94` bit `0x08` —
and it is semantically the right thing to read, because an unclaimed plot is selectable
precisely so a player can click it and build.

> **How far this is verified.** The bit indices are read from the engine's own `KindOf` and
> `ObjectStatus` name tables, and the tests assert both against the shipped binary. The
> `UNSELECTABLE`-means-claimed correlation is 20 flags on one map at one frame; the code that
> sets it has **not** been located. No map in that match carried a plain `CaptureFlag`, so the
> branch that protects the recapture case has not been exercised in game.

## 6. What the gate changes, on the measured match

Skip a candidate that is `BASE_SITE` **and** `UNSELECTABLE`:

| id | template | owner | verdict |
|---|---|---|---|
| 278 | `WirtschaftPlotFlag_Real` | enemy | **skipped** — the stall |
| 274 | `WirtschaftPlotFlag_Real` | enemy | **skipped** |
| 261 | `FestungPlotFlagSE_Real` | enemy | **skipped** |
| 269, 258, 255 | plots | self / ally | skipped already, by the stock `ALLIES` test |
| 272 | `WirtschaftPlotFlag_Real` | free | still a target — the new nearest, 823 units |
| 73, 74, 266–277, 279, 453 | free plots | free | still targets |

The tactic stays busy doing the thing it exists for. It stops locking onto plots that are
already taken.

## 7. The patch

One five-byte site. `cmp eax, 2` / `je <skip>` at `0x009BC28B` is exactly the width of a
`jmp rel32`, so nothing needs relocating or padding:

```
stock: 83 f8 02 74 47
```

Byte-identical in this repo's `game.dat` and in a retail Edain `C:\RotWK\game.dat`, so no
existing patch touches it. The `.aiflag` cave:

```asm
    cmp  eax, 2                      ; ALLIES - the stock test, verbatim
    je   SKIP
    mov  ecx, [esi+4]                ; ThingTemplate*
    test byte ptr [ecx+0x117], 1     ; KindOf BASE_SITE
    je   KEEP                        ; a plain CaptureFlag: always allowed
    test byte ptr [esi+0x94], 8      ; ObjectStatus UNSELECTABLE - already claimed
    jne  SKIP
KEEP:
    jmp  0x009BC290                  ; the picker's accept edge
SKIP:
    jmp  0x009BC2D7                  ; the picker's loop step
```

**Register liveness** (static): `eax` is dead — the stock fall-through overwrites it immediately
with `mov eax, [esi+4]`. `ecx` is dead — the loop reloads it at `0x009BC275` and `0x009BC280`
every iteration. `esi` is the candidate `Object` and is preserved. Both exits are edges the
stock picker already had.

**Null candidates** behave exactly as before: the cave dereferences `[esi+4]` on the same path
the stock code does, and on no other.

**AI-only for free.** The picker is inside `SkirmishAI` and has one caller, the tactic's own
update, so unlike [`ai-revive-gate.md`](ai-revive-gate.md) this needs no return-address
discrimination. **Determinism:** a `KindOf` off the template and one bit of the object's status
mask are both logic state, so the added edge is network- and replay-safe — but it is a logic
change, so every peer needs the same binary.

## 8. What remains

- **The `UNSELECTABLE` writer.** §5's correlation is measured, not derived. Finding what sets it
  on a plot would turn the strongest claim in this document from 20 samples into a citation.
- **A live confirmation.** The patch has not been run in a match. The two things to watch are a
  flag-capture squad releasing and re-tasking, and a plain `CaptureFlag` still being recaptured
  on a map that has one.
- **The other half of the waste.** Fixing the picker frees the units; it does not make the AI
  spend them well. A `FarmKillSquad` of `GameLogicRandomValue(1, 3)` units walking into a
  defended base dies on the approach, which is what happened to squad 48 here. Whether the raid
  tactic's squad sizing is worth its own look is an open question, not a defect this patch
  addresses.
- **`AIRoamingDefenseTactic`, `AIStructureCreepTactic`, `AIFarmBuilderTactic`,
  `AILumberMillBuildTactic`** and the three offensive tactics are unread. They share the squad
  base class — `+0x24` the player, `+0x58` the target `ObjectID`, `+0x60` a constructor coin
  flip — so the same reading method applies to all of them.
