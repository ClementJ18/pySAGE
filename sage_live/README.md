# sage_live

A Python API for a **running** BFME2 / RotWK game: attach to the process, read what is happening as
typed Python objects, and issue orders back into it.

It mirrors [`sage_replay`](../sage_replay/README.md): one reads recorded games, the other live ones,
and the action space is the same object, `sage_replay.Order`. So a session's orders can be written
by the replay serializer and checked against the replay the engine recorded.

## Example

```python
import sage_live

with sage_live.attach() as game:              # read-only; nothing is written to the game
    observation = game.observe()

    print(observation.frame, observation.me.resources)
    print(observation.census(observation.mine).most_common(5))

    barracks = observation.find(template="GondorBarracks", owner=observation.local_player)
    wounded = observation.find(owner=observation.local_player, damaged=True)
    closest = observation.nearest(barracks[0].position, owner=5)
```

Issuing orders needs the experimental `live-bridge` patch (see Requirements) and a writable handle:

```python
with sage_live.attach(writable=True) as game:
    game.wait_for_match()                     # the menu is a running game; see below
    observation = game.observe()

    game.select([o.object_id for o in observation.orderable(game.player_index)])
    game.move((1200.0, 880.0, 0.0))

    forge = observation.find(template="GondorForge", owner=game.player_index)[0]
    game.research("Upgrade_TechnologyGondorHeavyArmor", forge.object_id)
```

`attach` reads the local player's seat and resolves upgrade, template and power names from the
engine's own registries, with no game files on disk. Science names still need an ini load:
`session.names = Resolver.from_root(...)`.

## Layout

```
sage_live/
  __init__.py     the supported surface; everything below is re-exported here
  __main__.py     the `sage-live` inspector
  api/            the interface          connect, session, observation, orders
  backends/       where bytes come from  base (+ Loopback), memory, bridge, protocol, identity, snapshot
  utils/          the lookups            naming, heroes, resolve*, statics*
```

\* `resolve` and `statics` import `sage_ini`, so they are not re-exported; import them directly
(`from sage_live.utils.statics import Statics`). Everything else is reached from the root
(`sage_live.attach`, `sage_live.Observation`, `sage_live.orders.move`).

## Command line

```sh
python -m sage_live processes            # running game.dat pids (also an elevation check)
python -m sage_live info                 # frame, players, object census by side
python -m sage_live objects --owner 3 --damaged
python -m sage_live objects --upgrade Upgrade_GondorHeavyArmor --list
python -m sage_live snapshot --compact   # the whole observation as one JSON document
python -m sage_live watch                # one line per logic frame
```

## The model

Three frozen dataclasses:

| | carries |
|---|---|
| `Observation` | `frame`, `local_player`, `players`, `objects`, `fogged`, `godsight` |
| `PlayerState` | economy, spellbook points, held sciences, command points, PLAYER-scoped upgrades |
| `GameObject` | id, template, position, facing, health, owner, OBJECT-scoped upgrades, production queue |

`Observation` is also the query surface: `me`, `mine`, `opponents`, `player(i)`, `obj(id)`,
`find(...)` (keyword-only, case-insensitive), `nearest(...)`, `census(...)`, `owned_by(...)`,
`orderable(...)`, `to_dict()`. Static facts (cost, armour, weapons, KindOf) come from joining
`template_name` against the game data - see `Statics` below.

## What a building is making

```python
barracks = observation.find(template="GondorBarracks", owner=game.player_index)[0]
if not barracks.producing:                       # queue non-empty: unit *or* upgrade
    game.select([barracks.object_id])
    game.recruit("GondorFighterHorde")

print([(i.kind, i.name) for i in barracks.production])
# [('unit', 'GondorFighterHorde'), ('upgrade', 'Upgrade_GondorHeavyArmor')]
```

Units and upgrades share one `ProductionUpdate` queue. It costs a module walk per object;
`MemoryBackend(..., read_production=False)` turns it off.

## Recruiting a hero

```python
from sage_live.utils.statics import Statics

game.revives = Statics.from_root(root)          # the roster and the slot blocks
game.select([barracks.object_id])
game.confirm_queued(lambda: game.recruit_hero("GondorBeregond"), barracks.object_id)
```

A hero is recruited by its position in the player's revive list, not by template id, and the list
changes as heroes are fielded and die; `Session` tracks it. The engine will recruit a hero the
control bar hides, so `recruit_hero` only allows that with `godsight`. Details:
[`hero-recruitment.md`](../sage_patch/docs/hero-recruitment.md).

## Buying and casting spellbook powers

```python
statics = Statics.from_root(root)
for power in statics.spell_store("Men"):              # what the store sells
    if power.purchasable and power.enabled_for(held) and power.cost <= me.power_points:
        game.confirm_power(lambda: game.purchase_power(power.science), power.science)
        break

for power in statics.spell_book("Men"):               # what the book casts
    if power.castable and power.enabled_for(held):
        print(power.power, power.form, power.effect, power.radius, power.reload_seconds)
# SpellBookRebuild        location heal    150.0 180.0
# SpellBookArmyoftheDead  location summon 200.0 830.0
```

- Powers cost spellbook points, at the multiplayer price, and prerequisites are alternative groups.
- What a player holds is read live (`PlayerState.sciences`, ids; test with
  `names.science(...) in me.sciences`), not remembered: the AI is granted spells by script.
- `form` (location / object / self / passive) comes from the firing button; the wrong cast order is
  silently discarded. `effect` (summon, strike, build, buff, heal, grant, unknown) is read from the
  module implementing the power and the objects it finally creates; unknown means nothing in the
  data names a side, so do not aim it.
- `reload_seconds` is undiscounted; `Session.power_cooldowns` gives the engine's live cooldown.
- Pass the player's spellbook object as the cast's source (`Statics.spell_book_object`).

## Who is in a battalion

```python
game.select([o.object_id for o in observation.orderable(game.player_index)])
```

A battalion appears as its members plus the container, and orders to members are ignored.
`GameObject.parent_id` names the container, `Observation.members(id)` is the inverse, and
`orderable` is what to select. `producer_id` and `status` (`HORDE_MEMBER`, `IS_LEAVING_FACTORY`)
show battalions that came apart; see
[`horde_formation.py`](../examples/sage_live/horde_formation.py) and
[`horde-formation-orphans.md`](../sage_patch/docs/horde-formation-orphans.md).

## Moving the camera

```python
here = game.camera()                      # the live ViewLocation, or None if unreadable
game.look_at(centroid_of(fight))          # re-aim, touching nothing else
game.look_at(plot.position, zoom=0.6)     # override one scalar

with CameraPan(game) as pan:              # a thread that eases toward its target
    pan.aim(centroid_of(fight))
```

The camera is not an order: it cannot desync, costs no APM, and needs a bridge-backed session.
`look_at` writes only the aim, because writing a whole location always disturbs the zoom; passing
`zoom`, `angle` or `pitch` does that deliberately. A placement is a jump; `CameraPan` interpolates.
See [`camera-control.md`](../sage_patch/docs/camera-control.md).

## `Statics`: the join you cannot skip

```python
from sage_live.utils.statics import Statics          # imports sage_ini; not re-exported

statics = Statics.from_root(root)              # one ini load, about a minute
plots = [o for o in observation.mine if statics.is_build_site(o.template_name)]
```

A live object carries only a template name, and none of these can be guessed from it:

| question | the wrong answer | what actually answers it |
|---|---|---|
| where can I build? | "an object with no body" (a plot has an `ImmortalBody`) | `is_build_site` |
| is this plot free? | "the plot disappeared" (building does not consume it) | what is *standing* on it |
| did my building appear? | the ordered name (`BuildVariations` places a stand-in) | `same_building` / `canonical` |
| who has lost? | "owns no objects / buildings" | `counts_for_victory` (`MP_COUNT_FOR_VICTORY`) |
| what do I order? | the visible units (horde members ignore orders) | `Observation.orderable` |
| what is my army? | "mobile, has a body" (counts civilians and standards) | `SELECTABLE` and not `is_slaved` |
| is that an enemy? | "someone else's and it moves" (rabbits and fish) | `INERT` rules them out |
| why is this flag still guarded? | kill the defenders (a lair replaces them) | `spawns`, then `is_rebuild_hole` |

`kind_of` resolves inheritance, `+`/`-` deltas and `#define` macros.

## Backends

```
        policy / bot / notebook
                  |
        sage_live.Session          <- selection, APM cap, name resolution, waits
                  |
          Backend (Protocol)       <- connect() / poll() / step() / send()
        /         |         \
LoopbackBackend  MemoryBackend  BridgeBackend
 (in-process)     (read-only)    (patched, read+write)
```

- **`MemoryBackend`**: `ReadProcessMemory` only. About three reads per extra object, fifteen on
  average over a real match. Cannot send orders.
- **`BridgeBackend`**: adds orders, through the `live-bridge` command buffer and the engine's own
  `appendMessage`, so they are network-ordered like human input.
- **`LoopbackBackend`**: scripted observations, no game; every observation round-trips the wire
  codec, so it also tests the protocol.
- **`SnapshotSource`**: replays bytes captured from a real match (`capture_snapshot.py`), which is
  what regression-tests the memory layout.

Backends check their platform in the constructor, so the package imports anywhere.

## Things that will catch you out

- **The main menu is a running game** (a shell map). `Observation.in_match` tells a real match
  apart; `Session.wait_for_match` waits for one.
- **Ownership is not the template's Side.** Use `owner_index` / `mine` / `find(owner=...)`.
- **Upgrades come in two scopes**: faction-wide on the player, per-object on the object.
- **A consumed order is not an obeyed one.** The engine discards bad orders silently, so confirm
  with the side effect:

  ```python
  game.confirm_queued(lambda: game.recruit("GondorFighterHorde"), barracks.object_id)
  game.confirm_moved(lambda: game.move(there), [u.object_id for u in army])
  game.confirm_appeared(lambda: game.build("GondorWohnhaus", plot.position), near=plot.position)
  ```

  Gold is an unreliable oracle (it can be stolen or granted); `confirm_spend` is the last resort.
  `Sent.throttled` means the APM cap held an order back; `Sent.refused` means the backend would not
  take it.
- **A crashed game reads like a finished one.** `poll` raises `GameExited`; loop on
  `session.alive`.
- **Observations are whole-map and all-knowing by default.** `attach(fog=True)` hides what the
  seat cannot see (there is no memory of scouted buildings; see
  [`fog-of-war.md`](../sage_patch/docs/fog-of-war.md)). `attach(godsight=False)` removes what no
  player could know even when visible: opponents' production, economy and research. Snapshots
  record both settings.

## Requirements

- **Windows** for the live backends; `ProcessMemory` raises elsewhere.
- **An elevated shell**, since `game.dat` runs as administrator.
- For `writable=True` only: a `game.dat` with the **experimental** `live-bridge` patch
  (`sage-patch apply live-bridge ...`). Keep the unpatched binary. Reading needs no patch.
- **The build is checked.** `LAYOUT_ROTWK_201` is for RotWK 2.01 (PE timestamp `0x460DA09E`);
  `attach` refuses another build, since wrong offsets return plausible nonsense rather than
  failing. Pass another `EngineLayout` (or `--layout-json`; `build_timestamp: 0` disables the
  check). The stamp identifies the engine, not the mod, and survives patching.

## Where the layouts come from

- [`engine-globals.md`](../sage_patch/docs/engine-globals.md): the subsystem singletons.
- [`live-object-model.md`](../sage_patch/docs/live-object-model.md): the object table, `Object`
  layout, ownership, bodies, upgrade masks, and notes on every `EngineLayout` field.
- [`message-stream.md`](../sage_patch/docs/message-stream.md): how an order reaches the engine.
- [`live-api.md`](../docs/live-api.md): the design, milestones, and which orders are verified.

## Known gaps

- **Ownership misses script teams** (2 objects of 523 in one match), reported as no owner.
- **The revive list is reconstructed, not read**: exact for a hero never fielded, inferred for one
  being re-recruited, and a session started mid-match has missed the deaths. 9 of 187
  playable-faction producers do not line up (`Statics.check_revive_slots`). Map-scoped
  `BuildableHeroesMP` overrides are not applied. See
  [`hero-recruitment.md`](../sage_patch/docs/hero-recruitment.md).
- **Science names need an ini load.** `TheScienceStore` holds exactly the 263 sciences the ini
  defines, but its entries have different sizes and no fixed name offset, so reading it needs the
  parser followed statically.
- **Thing ids are corroborated, not round-tripped.** The live walk matches the ini table up to
  index 11,086 (all templates in play agree); prefer `resolve.Resolver` when a game tree exists,
  since only its rule is validated against recorded orders.
