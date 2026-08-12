# The 53 script actions WorldBuilder offers and RotWK never runs

Engine build `2.01.2614.37001`, ImageBase `0x400000`. Recovered statically from the installed
`game.dat` on 2026-08-11 with `pefile` + `capstone` via [`../scripts/pe.py`](../../scripts/pe.py), and
anchored against real map data with `sage_map`.

**Why this exists.** "There are scripts in WorldBuilder related to killing armies and calling
reinforcements, but they don't seem to work." They don't. Their dispatch entries point at a bare
`ret`.

## The dispatch is two-stage, and that matters

Getting this wrong produces a list four times too alarming, so it is worth stating carefully.

**Stage 1 — the ScriptEngine's own handler**, an if/subtract chain at `0x0060C211`:

```asm
0060c211  mov eax, [esi + 4]         ; the action type
0060c214  cmp eax, 0x14 ; jg / je    ; ... a sparse chain of ~32 ids ...
0060c3e1  mov ecx, [0x00DE87D8]      ; everything else falls through to:
0060c3ee  call [eax + 0x38]          ; ScriptActions::executeAction
```

It claims **32 action types** — script flow, timers and counters, the things the script engine owns
rather than delegates: ids `1, 2, 5, 6, 8, 9, 10, 15, 16, 20, 103, 124–127, 132–134, 150–155,
373–375, 415, 416, 439, 440, 508`.

**Stage 2 — `ScriptActions::executeAction`** (`0x007CAFA5`), a dense 600-case jump table at
`0x007CF857`:

```asm
007cafc7  mov eax, [esi + 4]
007cafca  cmp eax, 0x257             ; 600 cases
007cafd5  jmp [eax*4 + 0x7CF857]
```

A **live** case reads its parameters and calls an implementation, then falls into the shared
epilogue at `0x007CF846`:

```asm
007ce6aa  push 1 ; call 0x00602EFB   ; getParameter(1)
007ce6c2  call 0x007C506A            ; <-- the implementation
007ce6c7  jmp  0x007CF846            ; the epilogue
```

A **stub** case has its *table entry* pointing straight at that epilogue — no `getParameter`, no
call, no effect.

**66 of the 600 slots are stubs. Exactly 32 of those are the ones stage 1 already handled** — every
single pre-handled id is a stage-2 stub, which is precisely what you would expect and is strong
structural evidence the whole reading is right.

**66 − 32 = 34 actions are genuinely unimplemented.** Nothing anywhere runs them.

### A third state: gutted

A stub table entry is not the only way to do nothing. Some bodies survive, read their parameters,
and then drop them:

```asm
007ce72f  lea  eax, [ebp - 0x24]      ; a local Coord3D
007ce737  push eax ; push 2
007ce73c  call 0x00602EFB             ; getParameter(2)
007ce743  call 0x007B32DE             ; Parameter::getCoord3D(&local)
007ce748  jmp  0x007CF846             ; ...and straight to the epilogue
```

`0x007B32DE` is a pure accessor — it zeroes the output and copies three floats if the parameter type
is `0x10`. So this action reads a coordinate into a stack slot and returns. The parameter
marshalling survived because it is generated from the template's parameter spec; the body was cut
from under it.

Classifying all 600 bodies — following jumps to the epilogue and collecting call targets that are
neither `getParameter` nor a `Parameter` accessor (`0x007B3280`–`0x007B33A0`) — gives:

| | count |
|---|---|
| live (calls a real implementation) | 515 |
| stub (table entry *is* the epilogue) | 66, of which 32 are stage-1 delegations |
| **gutted** (reads parameters, calls nothing) | **19** |

The 19 gutted are mostly camera and audio modifiers — `CAMERA_MOD_*` (21, 22, 26–30),
`CAMERA_MOTION_BLUR_FOLLOW` (138, 139), `SUSPEND`/`RESUME_BACKGROUND_SOUNDS` (24, 25),
`RADAR_FORCE_ENABLE`/`RADAR_REVERT_TO_NORMAL` (212, 213), `SET_FPS_LIMIT` (146),
`SET_CAMERA_CLIP_DEPTH_MULTIPLIER` (334), `MAP_CHANGE_CLOUD_SPEED` (371),
`OBJECT_ALLOW_BONUSES` (323), `SET_VISUAL_SPEED_MULTIPLIER` (22).

**And two living-world actions**, which is why this distinction earns its own section.

## What this means for your three cases

### Handing heroes off when a mission loads

**The entire `*_ASSIMILATE_WITH_ARMY_BY_NAME` family is dead — all three scopes:**

| id | action | status |
|---|---|---|
| 540 | `PLAYER_ASSIMILATE_WITH_ARMY_BY_NAME` | **DEAD** |
| 541 | `TEAM_ASSIMILATE_WITH_ARMY_BY_NAME` | **DEAD** |
| 542 | `UNIT_ASSIMILATE_WITH_ARMY_BY_NAME` | **DEAD** |
| 514 | `TEAM_ASSIMILATE_WITH_FIRST_WALK_ON_ARMY` | live |
| 515 | `UNIT_ASSIMILATE_WITH_FIRST_WALK_ON_ARMY` | live |

That is the answer to "the heroes all spawn and have to be moved to a neutral player by hand".
The intended tool — attach these units to the named living-world army — **does not exist at any
scope**, so hand-moving is not a workaround you chose, it is the only thing left.

**The workaround worth trying:** the `*_WITH_FIRST_WALK_ON_ARMY` pair is live. It picks the army
implicitly rather than by name, which is a real constraint, but if a mission has one walk-on army
it may do the whole job. This is the cheapest experiment in this document.

### Heroes dying permanently

**Nothing in the carryover/revival family is dead:**

| id | action | status |
|---|---|---|
| 579 | `CREATE_DELAYED_CARRYOVER_UNIT_AT_WAYPOINT` | live |
| 595 | `CREATE_UNIT_REVIVAL_ENTRY` | live |
| 596 | `CREATE_UNIT_REVIVAL_ENTRY_FROM_DELAYED_CARRYOVER_HERO` | live |
| 597 | `CREATE_UNIT_REVIVAL_ENTRY_AT_LEVEL` | live |
| 538 | `SET_HERO_EXPERIENCE_SHARING` | live |

So permadeath is **not** a stubbed-action problem. `CREATE_UNIT_REVIVAL_ENTRY_FROM_DELAYED_CARRYOVER_HERO`
names your exact case — a hero that died earlier, turned back into a revival entry — and it is
implemented. Read with the INI fields `DelayCarryoverSpawningOf` and `ArmyCarryoverPoints`, the
implied shape is: a dead hero becomes a *delayed carryover* record, and a later mission converts
that record into a revival.

The question therefore moves to whether the living-world **battle-exit path writes those records**.
That is [`living-world-parity.md`](living-world-parity.md) §3's open question, now much sharper: not
"does carryover exist" but "does a WotR battle exit populate it". The actions to drive it are all
there and callable from a mission script today.

### Killing armies and calling reinforcements

| id | action | status |
|---|---|---|
| 361 | `LIVING_WORLD_MOVE_ARMY_TO_POSITION` | **GUTTED** |
| 362 | `LIVING_WORLD_MOVE_ARMY_TO_ZONE` | **STUB** |
| 363 | `LIVING_WORLD_SPAWN_ARMY_AT_POSITION` | **GUTTED** |
| 364 | `LIVING_WORLD_SPAWN_ARMY_IN_ZONE` | **STUB** |
| 365 | `LIVING_WORLD_DESPAWN_ARMY` | **STUB** |
| 366 | `LIVING_WORLD_EXIT_TO_REGION_VIEW` | live |
| 557 | `LIVING_WORLD_SET_PLAYER_REF_BY_TEMPLATE` | live |
| 430 | `REINFORCEMENTS_DISPLAY_BANNER` | **STUB** |
| 539 | `REMOVE_REINFORCEMENT_ARMY` | **STUB** |
| 543 | `CALL_IN_REINFORCEMENTS_WITHOUT_MOVIE` | **STUB** |
| 34 | `CREATE_REINFORCEMENT_TEAM` | live |
| 444 | `CREATE_REINFORCEMENT_TEAM_AT_UNIT_POSITION` | live |

**Every script action that spawns, moves or despawns a living-world army is non-functional — five
of five.** Three are stubs, two are gutted. The only survivors are `EXIT_TO_REGION_VIEW`, which
changes the view, and `SET_PLAYER_REF_BY_TEMPLATE`, which sets a script reference. Neither touches
an army.

So the honest statement is stronger than "despawn is missing": **you cannot manipulate a
living-world army from a mission script in RotWK at all.** An earlier revision of this section said
the "position" variants worked and only the "zone" ones were dead; that was the two-way
classification missing the gutted state, and it is wrong.

`CREATE_REINFORCEMENT_TEAM` does work — but everything that manages reinforcements afterwards does
not: you cannot call one in without a movie, remove one, or show the banner.

### Confirmed against your own maps

Parsing all 480 maps under `D:\Edain-Mod\_mod\maps` and matching `content_type` against the dead
set — with `internal_name` read from the same record, so the id↔name pairing is measured per
occurrence, not assumed:

| id | action | occurrences | where |
|---|---|---|---|
| 130 | `DRAW_SKYBOX_BEGIN` | 227 | across many maps |
| 497 | `GATE_READY` | 7 | |
| 148 | `MAP_SHROUD_AT_WAYPOINT` | 2 | |
| 69 | `CAMERA_MOVE_HOME` | 2 | |
| 553 | `MAP_REVEAL_IN_TRIGGER` | 1 | |
| **365** | **`LIVING_WORLD_DESPAWN_ARMY`** | **1** | **`map kampa angmar 01`** |

The Angmar campaign's first mission contains a despawn-army script that has never run. The
reinforcement and assimilate stubs appear **zero** times — they have not been authored against yet,
which is consistent with them never having appeared to work.

`DRAW_SKYBOX_BEGIN` at 227 uses is incidental to this investigation but worth knowing: that is a lot
of map script calling a no-op.

**Ids 539–543 are five consecutive dead actions** — `REMOVE_REINFORCEMENT_ARMY`, the three
`ASSIMILATE_WITH_ARMY_BY_NAME`, and `CALL_IN_REINFORCEMENTS_WITHOUT_MOVIE`. A contiguous run that
large is a feature block cut wholesale rather than five independent oversights, and every one of
them is about **moving units between the tactical battle and a living-world army**. That is the
same boundary all three of your complaints sit on.

It is also the script-level mirror of the INI-level finding in
[`living-world-parity.md`](living-world-parity.md) §6, where `DespawnArmy` is likewise the verb that
was removed. Two independent tables, same missing capability.

## The full 34

| id | action | id | action |
|---|---|---|---|
| 69 | `CAMERA_MOVE_HOME` | 284 | `TEAM_WAIT_FOR_NOT_CONTAINED_PARTIAL` |
| 89 | `PALANTIR_EVENT` | 289 | `AI_PLAYER_BUILD_SUPPLY_CENTER` |
| 95 | `TEAM_COLLECT_NEARBY_FOR_TEAM` | 324 | `SOUND_REMOVE_ALL_DISABLED` |
| 130 | `DRAW_SKYBOX_BEGIN` | 343 | *(name not captured)* |
| 131 | `DRAW_SKYBOX_END` | 362 | `LIVING_WORLD_MOVE_ARMY_TO_ZONE` |
| 143 | `CAMERA_SET_AUDIBLE_DISTANCE` | 364 | `LIVING_WORLD_SPAWN_ARMY_IN_ZONE` |
| 148 | `MAP_SHROUD_AT_WAYPOINT` | 365 | `LIVING_WORLD_DESPAWN_ARMY` |
| 220 | *(name not captured)* | 382 | *(name not captured)* |
| 227 | *(name not captured)* | 430 | `REINFORCEMENTS_DISPLAY_BANNER` |
| 248 | `SKIRMISH_BUILD_BUILDING` | 495 | `SET_COUNTER_TO_BASE_POPULATION` |
| 254 | `SKIRMISH_BUILD_BASE_DEFENSE_FRONT` | 497 | `GATE_READY` |
| 258 | `SKIRMISH_BUILD_BASE_DEFENSE_FLANK` | 539 | `REMOVE_REINFORCEMENT_ARMY` |
| 259 | `SKIRMISH_BUILD_STRUCTURE_FRONT` | 540 | `PLAYER_ASSIMILATE_WITH_ARMY_BY_NAME` |
| 260 | `SKIRMISH_BUILD_STRUCTURE_FLANK` | 541 | `TEAM_ASSIMILATE_WITH_ARMY_BY_NAME` |
| 263 | `SKIRMISH_WAIT_FOR_COMMANDBUTTON_AVAILABLE_ALL` | 542 | `UNIT_ASSIMILATE_WITH_ARMY_BY_NAME` |
| 264 | `SKIRMISH_WAIT_FOR_COMMANDBUTTON_AVAILABLE_PARTIAL` | 543 | `CALL_IN_REINFORCEMENTS_WITHOUT_MOVIE` |
| 283 | `TEAM_WAIT_FOR_NOT_CONTAINED_ALL` | 553 | `MAP_REVEAL_IN_TRIGGER` |

Four names were not captured by the scan; the *count* and the ids are read straight from the jump
table and are not affected.

The rest of the list is recognisable as Generals-era leftovers BFME never wired up — the
`SKIRMISH_BUILD_*` AI helpers, `AI_PLAYER_BUILD_SUPPLY_CENTER`, `TEAM_COLLECT_NEARBY_FOR_TEAM` —
which is a further sanity check that the mapping is sane.

## How the id ↔ name mapping was established

The names come from a **template table** — 800 fixed `0x80`-byte records built by a constructor
across `0x007D0000`–`0x007E8000`, each holding an internal `ALL_CAPS_NAME`, the WorldBuilder UI
string, and a parameter spec. Actions occupy 0–599, conditions 600–799. This table is what
WorldBuilder lists, and it is why dead actions still appear in the editor: **the template table says
they exist; the jump table decides whether they run, and they disagree.**

Template index `N` puts its name field at `esi + base + N*0x80`. The first three templates register
their names through a path the scan does not match, so the lowest captured offset is index 3, and
**engine id = captured index + 3**.

That `+3` is not a guess. `sage_map` reads both `content_type` *and* `internal_name` out of real map
files, giving direct ground truth, and the offset is uniform across the whole range:

| action | map `content_type` | captured index |
|---|---|---|
| `VICTORY` | 3 | 0 |
| `NO_OP` | 5 | 2 |
| `ENABLE_SCRIPT` | 8 | 5 |
| `CREATE_REINFORCEMENT_TEAM` | 34 | 31 |
| `TOGGLE_AVI_CAPTURE` | 367 | 364 |
| `SET_UNIT_REFERENCE` | 376 | 373 |
| `GIVE_PLAYER_UPGRADE` | 419 | 416 |
| `ATTACK_MOVE_TEAM_TO` | 544 | 541 |
| `MAP_REVEAL_PERMANENTLY_IN_TRIGGER` | 554 | 551 |

The map file's `content_type` **is** the switch value — `0x007CAFC7` reads it straight off the
parsed action — so this is the engine's own enum, measured rather than inferred.

Two further checks, both passed:

1. **Every one of the 32 stage-1 ids is a stage-2 stub.** Two independently recovered sets, and one
   is exactly contained in the other. A wrong offset would break the containment immediately.
2. **`NO_OP` is id 5, and stage 1 handles id 5 by jumping straight to the function exit** — an
   action named "do nothing" implemented as doing nothing.

### One correction worth recording

An earlier pass of this analysis missed stage 1 entirely and reported all 66 stubs as broken. That
put `ENABLE_SCRIPT`, `CALL_SUBROUTINE`, `SET_TIMER` and the counter actions on the dead list —
actions used over a thousand times in Edain's own maps, which plainly work. **The contradiction was
the useful signal**: a result that says a shipped mod's most-used script action does nothing is
wrong about the model, not about the mod. Chasing it produced the two-stage structure above.

## Reviving `*_ASSIMILATE_WITH_ARMY_BY_NAME` — the implementation still exists

The question that decides whether any stub is revivable is whether its implementation was stripped
with the feature or merely orphaned. For the assimilate block, **it was orphaned**, and the whole
chain is reachable from functions still in the binary.

`UNIT_ASSIMILATE_WITH_FIRST_WALK_ON_ARMY` (515) is live, and short enough to read whole:

```asm
007c410d  eax = param + 0x10                    ; the unit name AsciiString
007c411f  call 0x00435F30                       ; copy to a stack temp
007c4124  ecx = [0x00DE3BAC]
007c412a  call 0x0075A243                       ; findObjectByName(name) -> esi
007c4133  if (!esi) return
007c4135  ecx = [0x00DE412C]
007c413b  call 0x00625DFF                       ; getFirstWalkOnArmy() -> eax
007c4142  if (!eax) return
007c4144  ecx = [0x00DE412C]
007c414a  push eax ; push esi
007c414c  call 0x00625E0A                       ; assimilate(object, armyId)
```

`0x00625DFF` and `0x00625E0A` are thin thunks — `add ecx, 0x184 ; jmp` — onto a sub-object at
`[0x00DE412C] + 0x184` that bridges the tactical battle and the living-world army list. Nineteen
such thunks sit at `0x00625D4F`–`0x00625E15`; that is the sub-object's whole public API.

**The currency is an army id, not a pointer:**

```
0x0080FAD4  resolveArmy(id):      [0x00DE4950]->findArmyById(id)     ; 0x006B5351
                                  return army ? army->[0x78] : 0      ; the battle-side record
0x0080FF1B  getFirstWalkOnArmy(): scan this->[0x14..0x18] (ids), resolve each,
                                  take the first with record[0x14] != 0,
                                  return record->[0x1C]               ; <-- the id
0x0080FD9C  assimilate(obj, id):  resolveArmy(id), then act on obj
```

So `army->[0x78]` is the record and `record->[0x1C]` is the id. That closes the loop, because the
**by-name lookup already exists**: `0x006B53A4` is `findArmyByScriptingName(AsciiString*)` on the
same manager `0x00DE4950`, walking the same army vector at `+0x8C..+0x90`. It is the function
`SetPlayerControlOfArmy`'s executor uses ([`living-world-parity.md`](living-world-parity.md) §2).

**The missing action is a composition of functions that all still exist:**

```
obj  = [0x00DE3BAC]->findObjectByName(param0)          ; 0x0075A243
army = [0x00DE4950]->findArmyByScriptingName(param1)   ; 0x006B53A4, ret 4
if (!obj || !army) return
id   = army->[0x78]->[0x1C]
[0x00DE412C]->assimilate(obj, id)                      ; 0x00625E0A, ret 8
```

A cave of roughly 60–80 bytes plus **one dword** at `0x007CF857 + 542*4`. No new FSCommand, no table
relocation, no parameter-spec change — the template already declares the two parameters, so
WorldBuilder already offers the action with the right fields.

The team (541) and player (540) variants need the same cave plus an object enumeration, which the
live `TEAM_ASSIMILATE_WITH_FIRST_WALK_ON_ARMY` (514) at `0x007C409F` already demonstrates.

**Confidence: the chain is traced; none of it has been run.** Two unknowns decide it:

1. **Is `army->[0x78]` populated for an army that is not a walk-on participant in the current
   battle?** If that record only exists for armies the battle instantiated, a by-name lookup of an
   arbitrary campaign army yields a null record and the action does nothing — which would be a
   plausible reason the by-name variants were cut rather than shipped.
2. What `record[0x14]` (the walk-on flag) gates, and whether bypassing it is safe.

Question 1 decides whether the patch is worth writing, and it is answerable live with `live-bridge`:
in a running battle, resolve a campaign army by name and read `+0x78`.

For the other stubs — `LIVING_WORLD_DESPAWN_ARMY` and the reinforcement block — no equivalent trace
has been done, so nothing is claimed. The living-world manager's methods cluster around
`0x006B3F1D`–`0x006BF1C1`, which is where a surviving despawn would be.

Meanwhile the `*_WITH_FIRST_WALK_ON_ARMY` workaround costs nothing and needs no patch at all.
