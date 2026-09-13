# `ForceBattle` does not force a battle in RotWK

Engine build `2.01.2614.37001`, ImageBase `0x400000`. Static analysis 2026-09-13 against
`game.dat`. **Not runtime-verified** — but it agrees with the only in-game attempt on record: Edain's
`wotrscenariotest.inc` carries a `ForceBattle` block commented out with *"Bisher keine Auswirkungen
bemerkt"* ("no effect noticed so far").

## The finding

`ForceBattle` parses, is stored on the Act, and is executed by the act runner. It has two forms,
chosen by whether `Movie` is set:

- **With `Movie`** it places (or, with `RemoveEvent = Yes`, removes) a named **movie event** on the
  strategic map. This form has a body.
- **Without `Movie`** — the form BFME1's campaigns use, with `Region` or `Position`, `UseArmy` and
  `ArmyAttackDirection` — it calls `0x00918BA0`, which is a bare `ret 0xC`. **Nothing happens.**

`0x00918BA0` is one instruction referenced 172 times across `.text` and `.rdata`: an empty body the
linker folded into one copy. The battle half of the verb is compiled out, not merely unused.

Nothing in the executor reads `IsScriptedCampaign`; the result is the same in either mode.

## The record

Parser `0x008E5BE0` fills a stack record through field table `0x00C787A8` and appends it with
`0x0096DF22` (`add ecx, 0x14; jmp 0x96dc50`) to the Act's vector at **`act+0x14`**, stride `0x28`.

| field | offset | type |
|---|---|---|
| `Region` | `+0x04` | AsciiString |
| `EventName` | `+0x08` | AsciiString |
| `UseArmy` | `+0x0C` | AsciiString |
| `Position` | `+0x10` | Coord3D (x, y read) |
| `Movie` | `+0x18` | AsciiString |
| `PlayNextActAfterMovie` | `+0x1C` | Bool |
| `RemoveEvent` | `+0x1D` | Bool |
| `ArmyAttackDirection` | `+0x20` | Coord3D |

## The executor — pass 2 of the act runner

`ACT_RUN` (`0x0096E362`) calls `0x0096C74B` second, straight after `EnableRegion`. Per record:

```asm
0096c758  eax = [TheLivingWorldLogic 0x00DE4950]->[0xB0]
0096c76a  je   done                      ; no region manager -> skip the whole pass
0096c79b  call 0x96c6b3                  ; rec+0x18, Movie
0096c7bf  je   0x96c840                  ; empty -> the battle form

          ; Movie set
0096c7c1  cmp  byte [rec+0x1D], 0        ; RemoveEvent
0096c7cb  call 0x44f0df                  ;   rec+0x08, EventName
0096c7db  call 0x6b8372                  ;   yes -> removeMovieEvent(name)
0096c827  call 0x6b9341                  ;   no  -> addMovieEvent(pos, Movie, PlayNextActAfterMovie, EventName)

          ; Movie empty
0096c844  call 0x96c67d                  ; rec+0x04, Region
0096c868  je   0x96c8ad
0096c897  call 0x918ba0                  ; Region set:   (Region, UseArmy, &ArmyAttackDirection)
0096c8d4  call 0x918ba0                  ; Region empty: (&Position, UseArmy, &ArmyAttackDirection)

00918ba0  c2 0c 00    ret 0xC            ; <- the entire function
```

`addMovieEvent` (`0x006B9341`) allocates a `0x18`-byte event — position `+0x00`, an id from a
counter at `[LivingWorldLogic+0xB0]+0x2C` at `+0x08`, `Movie` `+0x0C`, `EventName` `+0x10`,
`PlayNextActAfterMovie` `+0x14` (constructor `0x006B65A2`) — registers it on `TheLivingWorldManager`
(`0x00DE3C08`) through `0x00612EDB` with type 2, and pushes it onto `TheLivingWorldLogic+0xBC`.
`removeMovieEvent` (`0x006B8372`) finds one by name (`0x006B750A`) and removes it (`0x006B58D5`).
What the player sees and does with a movie event is not traced.

## How the engine makes a battle

There is exactly one live battle creator, and it runs once per turn.

```
0x006BDD98  LivingWorldLogic::onPhaseChanged
            phase 1 -> 0x006B455E, 0x006B546B,
                       0x006B4706  LivingWorldLogic::conflictPass
                                     for every player's armies: 0x0071AF26 (register in its region)
                                     jmp 0x0060FBA1  RegionStore::detectConflicts
                       0x0060E985
            phase 2 -> 0x006BBBFD (battles are resolved from here)
```

`detectConflicts` walks every region's army ids (`region+0x184`), collects the armies and their
distinct owners, and - when two non-allied players meet, or one meets an owner who
`Region::defendsAgainst` him - adds the owner, takes the region's battle point and calls

```
0x0060F9D1  RegionStore::createBattle(Region*, vector<Army*>*, vector<LivingWorldPlayer*>*, Coord2D*)
              if findBattle(region) -> return                    ; one battle per region
              battle = new(0x40) LivingWorldBattle(++store[0x30], region, armies, players, pos)
              store->battles.push_back(battle)                   ; store+0x14
              owner's garrison army joins the owner's side
```

`LivingWorldBattle`'s constructor (`0x007F869C`, `ret 0x14`) makes one side per player and puts every
army whose owner id (`army+0x54`) matches that player on it; its finalize step (`0x007F597F`) gives
the battle an id and registers a map marker at its position (`+0x28`) on `TheLivingWorldManager`.
Both only read `begin`/`end` of the two vectors. The three removal sites (`0x006BBA3A`,
`0x006BC4C0`, `0x006BEB88`) all follow resolution; nothing clears pending battles at a turn's start.

An army's region is `Army::updateRegion` (`0x0071A56C`), recomputed from its position each time. The
conflict pass counts an army in that region unless it is an unnamed, empty placeholder
(`0x0071AA69`), which counts only where its owner holds a defended region.

## `SpawnArmy`'s `Position` is snapped

Pass three (`0x0096E0B8`) spawns a record whose `Position` is non-zero through
`LivingWorldLogic::spawnArmy` (`0x006B7229`). The army's constructor places it at `Position` (or, with
`InitialRegion`, at that region's first army slot), and then `spawnArmy` looks up the region at that
point and branches on the army's **hero**, not its name (`0x006B735C`, `army+0x18`, copied from
`HeroTemplateName`):

- **with a hero**, it moves the army into a free hero-army slot (`0x007F3D27`, slot lists at
  `region+0x110`/`+0x1AC`);
- **without one**, it calls `0x006B540B`, which folds the new army's roster into the army its
  player already has in that region and destroys the new army - `ScriptingName` and all. Only when
  there is no such army is the new one placed (`0x007F3D27`'s `+0x104`/`+0x1A0` lists).

So an army lands exactly on its `Position` only when the point lies outside every region, and a
hero-less army spawned in a region its player owns stops existing under its own name. **Measured
live on 2026-09-13** in `WOTRScenarioMordor`: every region an `OwnershipSet` gives a player starts
with one unnamed army, and each hero-less story army spawned into such a region was found folded
into it - Saruman and Lurtz into Isengard's, the Ents into Fangorn's - after which `MoveArmy` and
`ForceBattle UseArmy` named nothing. Edain's scenarios give every story army a `HeroTemplateName`,
whether or not its roster contains that hero, which is what keeps theirs apart. All 25 of Edain's
`SpawnArmy` positions depend on the snapping.

## Built: `ForceBattle` and `ExactPosition` in `campaign-army-verbs`

Both live in [`campaign-army-verbs`](../../patches/campaign_army_verbs.py), which already owns the
eleventh act pass. **Static only.**

**`ForceBattle`.** The two calls into the stub (`0x0096C897`, `0x0096C8D4`) are repointed at cave
routines with the same `ret 0xC`, which copy the request - region name or point, and `UseArmy` - into
a queue; the pass's strings are temporaries. The queue is drained after the act's merges, so after
pass three and `MoveArmy`: an army the act spawns can fight. For each request the cave does what
`detectConflicts` does for one region, minus its "is there a conflict" gate:

1. resolve the region (`findRegionByName`, or `regionAt(Position)`) and the battle point
   (`battlePoint`, or `Position` itself); stop if the region already has a battle;
2. move `UseArmy` to the battle point if it stands in another region, and stop if a named
   `UseArmy` does not exist;
3. take every army in the region by the conflict pass's membership rule, plus `UseArmy`; flag each
   roster (`+0x2C = 1`) as `detectConflicts` does;
4. one player per owner, then the region's owner when `Region::defendsAgainst(attacker)`;
5. with at least two players, `createBattle`.

The battle then waits in the store and is offered in the turn's battle phase like any other. It
does **not** open immediately, and a battle cannot be fought against nobody: a lone army in its own
empty region makes no battle. `ArmyAttackDirection` parses and is ignored; the battle has no field
for it.

**`ExactPosition = Yes`.** The Act `SpawnArmy` parser's field-table `push` (`0x008E7902`) names a
copy of the table with one more row, whose parser writes a flag into the cave, and its
`INI::parseFields` call (`0x008E790B`) is wrapped: clear the flag, parse, and if the block set it,
file the `ScriptingName`. Pass three's spawn call (`0x0096E1D8`) is wrapped so that after the engine
spawns and places the army, a filed name is moved to the record's `Position` and its region is
refreshed. Opt-in, because stock placement is what Edain relies on. The army keeps the slot it
reserved.

## Still unknown

| | question | how to settle |
|---|---|---|
| 1 | Does a battle created at act time behave like one `detectConflicts` made - prompt, deployment, harvest? | play one: `ForceBattle` into a garrisoned enemy region |
| 2 | Does anything re-snap an exactly placed army to its slot on a later turn? | spawn with `ExactPosition`, end two turns, compare positions |
| 3 | What does `0x0060E985` do after the conflict pass, and does it treat an early battle differently? | read it |
| 4 | Does a teleported `UseArmy` need its old region's slot released? | read `0x007F3D27`'s counterpart on army departure |
