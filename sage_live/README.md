# sage_live

A Python API for a **running** BFME2 / RotWK game: attach to the process, read what is
happening as typed Python objects, and issue orders back into it.

The shape mirrors [`sage_replay`](../sage_replay/README.md) — one reads recorded games, the
other reads and drives live ones — and the action space is literally the same object,
`sage_replay.Order`. An action this package emits can be written by the byte-exact serializer
the replay corpus already gates, and a session's output can be checked against the replay the
engine recorded of that same session.

## Example

```python
import sage_live

with sage_live.attach() as game:              # read-only; no injection, nothing written
    observation = game.observe()

    print(observation.frame, observation.me.resources)
    print(observation.census(observation.mine).most_common(5))

    barracks = observation.find(template="GondorBarracks", owner=observation.local_player)
    wounded = observation.find(owner=observation.local_player, damaged=True)
    closest = observation.nearest(barracks[0].position, owner=5)
```

Ordering needs the live-bridge patch and a writable handle:

```python
with sage_live.attach(writable=True) as game:
    game.wait_for_match()                     # the menu is a running game; see below
    observation = game.observe()

    game.select([o.object_id for o in observation.find(owner=game.player_index, has_body=True)])
    game.move((1200.0, 880.0, 0.0))

    forge = observation.find(template="GondorForge", owner=game.player_index)[0]
    game.research("Upgrade_TechnologyGondorHeavyArmor", forge.object_id)
```

`attach` reads the local player's seat out of `PlayerList+0x10` rather than assuming 0, and
fits the session with a `LiveNames` that resolves **upgrade and template** names against the
engine's own `TheUpgradeCenter` and `TheThingFactory` — 976 upgrades and 11,142 templates, read
in under a fifth of a second, with **no game files on disk at all**. Power and science names
still need an ini load; attach one with `session.names = Resolver.from_root(...)`.

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

Three frozen dataclasses. Immutability is deliberate: a policy that mutates last frame's world
is a bug class this rules out entirely.

| | carries |
|---|---|
| `Observation` | `frame`, `local_player`, `players`, `objects`, `fogged` |
| `PlayerState` | economy, spellbook points, command points, PLAYER-scoped upgrades |
| `GameObject` | id, template name and Side, position, facing, health, owner, OBJECT-scoped upgrades |

`Observation` is also the query surface: `me`, `mine`, `opponents`, `player(i)`, `obj(id)`,
`find(...)`, `nearest(...)`, `census(...)`, `by_side(...)`, `owned_by(...)`, `to_dict()`.
`find` is keyword-only and every criterion is optional, so a call reads as its own
documentation; all string matching is case-insensitive because ini identifiers are.

`template_name` is the join key. Once an object names its template, `sage_ini` and
`sage_mods.edain` supply cost, armour, weapons, build time, command points and the faction
tree — so the observation stays small and the consumer joins against static data it already
holds.

## Backends

```
        policy / bot / notebook
                  |
        sage_live.Session          <- selection state, APM cap, name resolution, waits
                  |
          Backend (Protocol)       <- connect() / poll() / step() / send()
        /         |         \
LoopbackBackend  MemoryBackend  BridgeBackend
 (in-process)     (read-only)    (patched, read+write)
```

**`LoopbackBackend`** is fed scripted observations and needs no game. Not a stub: every
observation is encoded to the wire format and decoded back before being handed out, so a test
that drives a policy through it is also a conformance test for the protocol codec.

**`MemoryBackend`** is `OpenProcess` + `ReadProcessMemory` and nothing else — no code loaded
into the game, no patched binary, no anti-tamper surface. It cannot issue orders, and says so
via a diagnostic rather than dropping them silently.

**`BridgeBackend`** adds the write half, marshalling orders into the command buffer that
`sage_patch`'s `live-bridge` patch appends to `game.dat`. Orders enter through the engine's own
`appendMessage`, so they are network-ordered and check-summed like any human input.

Backends are constructed explicitly and check their platform in the constructor, never at
import: this package imports cleanly on a machine with no game and no Windows.

## Five things that will catch you out

**The main menu is a running game.** BFME2 draws its menu over a *shell map* — a real map
simulated by the same `GameLogic` — so the frame counter advances, objects exist, and every
cheap "is a game running?" test says yes while the player is still choosing a faction. What the
menu does not have is a player: its roster is `PlyrCivilian` and `ReplayObserver`, and the local
player *is* the observer. `Observation.in_match` asks that question; `Session.wait_for_match`
blocks on it and re-reads the seat on arrival.

**Ownership is not the template's Side.** `owner_index` is the owning player;
`template_side` is what the template declares, and they genuinely disagree in both directions.
Measured in one live match: the creeps owned 18 objects whose Side is `Neutral`, and the local
player owned one whose Side is `Civilian`. Filtering by Side to find "my units" both misses
things you own and claims things you do not. Use `mine` / `find(owner=...)`.

**Upgrades come in two scopes and neither is optional.** Faction-wide researches land on the
`Player`; per-battalion and per-structure ones land on the **object** and appear in no other
field — not in `template_name`, not in `player.upgrades`. An upgraded battalion differs from a
fresh one by `max_health` and `GameObject.upgrades`, and by nothing else.
`upgrades_in_progress` is filtered to player scope on purpose: the engine sets an object
upgrade's in-progress bit on the player and then never clears it.

**A consumed order is not an accepted order.** Game logic can discard a malformed or
unaffordable order after the stream has taken it, and *nothing reports that* — no error, no
diagnostic, and the order still reaches the replay. **Resources are the oracle**: if a recruit
or build does not drop the player's gold within a second, logic refused it.

**Nothing here is fog-filtered.** This reads the whole map. The engine knows what each player
can see, but that filter belongs on the game side and cannot be reconstructed honestly from
outside, so `Observation.fogged` is always False on the memory and bridge backends. Training a
policy on information a human never had should be a decision, not an accident.

## Requirements

- **Windows**, for the two live backends. The package imports anywhere; `ProcessMemory` raises
  in its constructor off Windows, pointing at `LoopbackBackend`.
- **An elevated shell.** `game.dat` runs as administrator, so `ReadProcessMemory` is refused
  otherwise. `attach` says exactly that when it happens.
- **A patched `game.dat`**, for `writable=True` only: `sage-patch apply live-bridge --in game.dat`.
- **Addresses are build-specific.** `LAYOUT_ROTWK_201` is verified against RotWK 2.01 + Edain
  (`game.dat`, 11,346,944 bytes). Pass a different `EngineLayout` for another build, or
  `--layout-json` on the CLI.

## Where the layouts come from

Every offset was confirmed against a running process, not inferred from shape:

- [`engine-globals.md`](../sage_patch/docs/engine-globals.md) — the subsystem singletons.
- [`live-object-model.md`](../sage_patch/docs/live-object-model.md) — the object table, the
  `Object` layout, ownership, the body module, and the two upgrade masks.
- [`message-stream.md`](../sage_patch/docs/message-stream.md) — how an order reaches the engine.
- [`live-api.md`](../docs/live-api.md) — the design and its milestones.

## Known gaps

- **Production, queue and construction state are not located** — but they are ruled out of the
  object's own header. Sampling every owned object's first `0x400` bytes for 531 consecutive
  samples while a structure was built and then produced a battalion, exactly nine dwords of that
  structure ever changed and all had settled long before it produced anything. Both live in a
  module behind a pointer. So a barracks already training still reads as idle, and a half-built
  structure is indistinguishable from a finished one.
- **Horde membership is not reported.** `Object+0x8C`/`+0x90` turned out to be the `next`/`prev`
  of one global doubly-linked list of every live object — exact inverses for all 317 links in a
  318-object match, one head, one tail, full reachability. They looked like battalion links only
  because members are created consecutively. `parent_id` is therefore unset because the
  information is *absent*, and a battalion appears as its individual members.
- **Ownership misses script teams** — 2 objects of 523 in a live match, reported as no owner.
- **Power and science names need an ini load.** `TheSpecialPowerStore` and `TheScienceStore`
  have addresses but have not been walked. `TheUpgradeCenter` and `TheThingFactory` have, which
  is why upgrade and template names need no game data.
- **Thing ids are corroborated, not round-tripped** — but the corroboration is now measured.
  `thing_order` anchors index 0 at `DefaultThingTemplate`, contains every template any live
  object uses, and has no duplicate names. Against the ini tree it reads 11,142 templates to
  11,132, and the two are **identical up to index 11,086**; in a live match all 69 templates in
  play agreed exactly, over ids 3 to 10,994. So the gap is confined to the tail, well above
  anything a match touches. No order carrying one of these ids has yet been seen to build the
  thing it names, and only the ini rule has corpus backing (491/491 `FOUNDATION_CONSTRUCT`
  orders), so `resolve.Resolver` is still the path to prefer where a game tree exists.
