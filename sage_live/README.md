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
engine's own `TheUpgradeCenter`, `TheThingFactory` and `TheSpecialPowerStore` — 976 upgrades,
11,142 templates and 1,566 powers, with **no game files on disk at all**. Only science names
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
| `Observation` | `frame`, `local_player`, `players`, `objects`, `fogged`, `godsight` |
| `PlayerState` | economy, spellbook points, command points, PLAYER-scoped upgrades |
| `GameObject` | id, template name and Side, position, facing, health, owner, OBJECT-scoped upgrades, production queue |

`Observation` is also the query surface: `me`, `mine`, `opponents`, `player(i)`, `obj(id)`,
`find(...)`, `nearest(...)`, `census(...)`, `by_side(...)`, `owned_by(...)`, `to_dict()`.
`find` is keyword-only and every criterion is optional, so a call reads as its own
documentation; all string matching is case-insensitive because ini identifiers are.

`template_name` is the join key. Once an object names its template, `sage_ini` and
`sage_mods.edain` supply cost, armour, weapons, build time, command points and the faction
tree — so the observation stays small and the consumer joins against static data it already
holds.

## What a building is making

```python
barracks = observation.find(template="GondorBarracks", owner=game.player_index)[0]
if not barracks.producing:                       # queue non-empty: unit *or* upgrade
    game.select([barracks.object_id])
    game.recruit("GondorFighterHorde")

print([(i.kind, i.name) for i in barracks.production])
# [('unit', 'GondorFighterHorde'), ('upgrade', 'Upgrade_GondorHeavyArmor')]
```

Units and upgrades share **one** queue on the engine's `ProductionUpdate`, so a barracks
training and an armoury researching are the same list with different `kind`s — that is the
engine's shape, not a simplification.

This was the interface's largest blind spot: a barracks already training read as idle, so a
policy queued into a building that was busy and could not tell why nothing was charged. The
missing piece was one hop, `Object` → its modules, and it is `Object+0x24C` — a
NULL-terminated `BehaviorModule*` array, read off the engine's own
`getProductionUpdateInterface`. The module is then picked out by matching its **primary
vtable**, because a vtable address is unique to its class and needs no call.

Names are resolved by **pointer identity** against the registries the backend already walks, so
an entry pointing at something neither registry knows reports an empty name rather than a
guessed one. And the module has to name the object it was reached from — if that back-pointer
disagrees, the read is refused with a diagnostic instead of reporting fiction.

Reading this costs a module walk per object. `MemoryBackend(..., read_production=False)` turns
it off for a consumer polling every frame that does not need it.

## Recruiting a hero

```python
from sage_live.statics import Statics

game.revives = Statics.from_root(root)          # the roster and the slot blocks
game.select([barracks.object_id])
game.confirm_queued(lambda: game.recruit_hero("GondorBeregond"), barracks.object_id)
```

**A hero is not recruited by template id.** It is queued by its position in the player's
`BuildableHeroesMP` list, through a `CommandButton` whose `Command` is `REVIVE` — the same
`0x417` order as `recruit` with the leading flag set, and the second argument read as a revive
index instead of a template. The two forms are otherwise byte-identical, which is why feeding a
`CommandSet` slot number to the flagged one was charged in full and produced a hero nobody asked
for, twice.

Heroes bind to those buttons **by position**, offset by one because position 0 is the Ring-hero
slot. A building that recruits the fourth hero carries the first three slots too, disabled by an
upgrade it can never hold — so `GondorBarracksCommandSet` has fourteen REVIVE buttons of which
two are live, and those two are Beregond and Boromir.

**The list is not the roster.** A fielded hero leaves it and everything behind slides forward; a
hero killed after fielding rejoins at the tail. `Session` follows both across frames, so
`revive_index` stays right as a match runs — exact for a hero never yet fielded, and inferred
from observed deaths for one being re-recruited.

**The engine will recruit a hero the interface never offered.** Its own gate matches a REVIVE
slot by counting and never reads the button it matched, so an order can buy a hero whose slot
the control bar hides — that is how a `GondorBarracks` was made to produce Imrahil, and nothing
in the game reports it. So `recruit_hero` gates on `godsight`: with it, any hero the producer's
slot block can reach; without it, only a hero whose slot at that building is **enabled**, which
is the set a human would have been shown. Either way an index past the block raises rather than
being consumed and silently discarded.

Derivation, the two live recruits, and what is still open:
[`hero-recruitment.md`](../sage_patch/docs/hero-recruitment.md).

## Who is in a battalion

```python
game.select([o.object_id for o in observation.orderable(game.player_index)])
```

A battalion appears in an observation as its ~15 members **plus** the container, and the
members are slaved to the container's `HordeAIUpdate`. Selecting the members and issuing a move
produces an order the engine records and then ignores — the "sometimes recorded but nothing
moved" symptom, and one of the easiest ways to conclude a constructor is broken when it is not.

`GameObject.parent_id` names the container, `Observation.members(id)` is the inverse, and
`orderable(player)` is the selection an order should be addressed to. This needs no game files
and cannot disagree with the running game, so it supersedes the name-based `is_horde_member`
wherever a live observation is in hand.

The field is `Object+0x27C`, found by asking which dword in a member's header holds its
container's address — 22 of 23 members agreed and no other offset managed more than 2. Across a
whole live match it never once pointed outside the object table or more than 200 units away,
and the template pairs were right for four factions at once.

## `Statics` — the join, and why you cannot skip it

```python
from sage_live.statics import Statics          # imports sage_ini; not re-exported

statics = Statics.from_root(root)              # one ini load, about a minute
plots = [o for o in observation.mine if statics.is_build_site(o.template_name)]
```

A live object carries a template name and nothing else, and **none of the categories a policy
needs are guessable from that name**. Each of these was got wrong in a real match first:

| question | the wrong answer | what actually answers it |
|---|---|---|
| where can I build? | "an object with no body" — a plot has an `ImmortalBody` of 15,000 | `is_build_site` (`BASE_FOUNDATION` / `BASE_SITE`) |
| is this plot free? | "the plot disappeared" — building on a plot does not consume it | what is *standing* on it |
| did my building appear? | counting the ordered name — `BuildVariations` means it never appears | `same_building` / `canonical` |
| who has lost? | "owns no objects", or "owns no buildings" — an economy building is `IGNORE_FOR_VICTORY` | `counts_for_victory` (`MP_COUNT_FOR_VICTORY`) |
| what do I order? | the units you can see — they are horde *members*, and orders to them are ignored | `Observation.orderable` (live, exact); `is_horde_member` offline |

`kind_of` resolves inheritance and SAGE's delta form (`KindOf = +SUMMONED`), because a
`ChildObject` does not restate its parent's flags — reading the field directly reports nothing
for a large share of real templates, `GondorBuildingFoundation_Independant` among them.

## What an observation costs

**Three reads for an additional object; about fifteen averaged over a real match.** Both numbers
are real and they answer different questions, so it is worth being exact about which is which.

*Marginal* cost — one more object of a template already seen — is **3**: the table entry, the
object header, and the body. Everything else on the header comes out of that one read.

*Average* cost over a captured 386-object match is **15.1**, because a real match holds dozens
of distinct templates and each pays once for its name, its Side and its module walk. Measured
against the same capture, the improvements decompose as:

| | reads per object |
|---|---|
| originally | 49.8 |
| caching template facts | 29.1 |
| + batching the reads | **15.1** |

So batching is a 1.9x cut on top of a 1.7x from caching — **3.3x** together on real data, not the
5.3x the marginal figure alone suggests. A 400-object observation took 0.32 s before any of it.

Every wide read falls back to reading fields individually, and the two must decode identically
- an object straddling an unmapped page fails the wide read while each field inside it reads
fine. `MemoryBackend(..., read_production=False)` drops the module walk as well.

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

**`SnapshotSource`** replays a recorded process: `capture_snapshot.py` writes the bytes a decode
touched during a real match, and any backend can read them back with no game, no Windows and no
elevation. That is what regression-tests the layout — every other fixture in this package writes
its fields where `EngineLayout` says they are, so a wrong offset is written wrong *and* read
wrong and the test passes. Bytes the engine laid out cannot cancel out that way.

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

## Six things that will catch you out

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
diagnostic, and the order still reaches the replay. So `send` returning 1 means the game
*received* the order, never that it obeyed it. The only honest test is the side effect, and
`Session` ships the three that work:

```python
game.confirm_queued(lambda: game.recruit("GondorFighterHorde"), barracks.object_id)
game.confirm_moved(lambda: game.move(there), [u.object_id for u in army])
game.confirm_appeared(lambda: game.build("GondorWohnhaus", plot.position), near=plot.position)
```

Each answers False rather than raising, because "it did nothing" is a result a policy acts on.
The obvious version of each is wrong: a plot vanishing is not the oracle for a build (building
on a plot does not consume it), and the ordered template never appears when it has
`BuildVariations`.

**Gold is not a sound oracle, in either direction.** It reads as the obvious one — the order
costs money, so watch the money — and `confirm_spend` still offers it for spends with no other
visible effect. But the balance is a contested number: an enemy ability can **steal** it, so it
falls with no spend of yours, and an ability can **grant** 500–1000 at once, so a real spend
hides under a net rise. Prefer `confirm_queued`, which watches the queue of the building the
order actually named — that is the thing the order was supposed to do, and nothing else in the
match can forge it.

`send` also returns *why* nothing went — `Sent.throttled` is the APM cap pacing you, which is
normal, and `Sent.refused` is the backend turning the order down, which is not.

**A crashed game reads exactly like a finished one.** A vanished process does not read as
zeroes; it does not read at all, so every field falls back to its default and the observation
comes back with no objects and no local player — which is what a match that ended looks like.
`poll` raises `GameExited` rather than handing that over, and `session.alive` is the loop
condition to prefer over anything inferred from an observation.

**Nothing here is fog-filtered, and some of it a player could never know at all.** These are
two different problems and only one of them is about visibility.

*Visibility* is fog: `Observation.fogged` is always False, so you read the whole map. The
engine's own per-object shroud state is the honest source and has not been read yet.

*Knowledge* is `godsight`, and it is not fixed by fog. A fully visible enemy barracks still has
no readable production queue — the game gives a player no tell whatever — and an opponent's
gold, income, spellbook points and researches have no on-screen equivalent either. So
`attach(godsight=False)` strips exactly that: an opponent keeps their name and faction, and
nothing else. Every observation the session hands out goes through one filter, and the snapshot
records `godsight` itself, because a saved observation outlives the session that made it.

Training a policy on information a human never had should be a decision, not an accident.

## Requirements

- **Windows**, for the two live backends. The package imports anywhere; `ProcessMemory` raises
  in its constructor off Windows, pointing at `LoopbackBackend`.
- **An elevated shell.** `game.dat` runs as administrator, so `ReadProcessMemory` is refused
  otherwise. `attach` says exactly that when it happens.
- **A patched `game.dat`**, for `writable=True` only: `sage-patch apply live-bridge --in game.dat`.
- **Addresses are build-specific, and the build is checked.** `LAYOUT_ROTWK_201` is verified
  against RotWK 2.01 (`game.dat`, PE timestamp `0x460DA09E`). `attach` reads that stamp out of
  the running image and **refuses a mismatch**, because reading another build with these
  offsets does not fail — it reports plausible nonsense, which is far harder to notice than an
  exception. Pass a different `EngineLayout` for another build, or `--layout-json` on the CLI;
  `build_timestamp: 0` there disables the check for a build nobody has measured yet.

  The stamp identifies the *engine*, not the mod: a different Edain release runs the same
  `game.dat`, and it is the id spaces rather than the layout that move (see `LiveNames`). It
  also survives patching — appending a cave leaves the COFF header alone — which it has to,
  since the writable path only ever runs against a patched binary.

## Where the layouts come from

Every offset was confirmed against a running process, not inferred from shape:

- [`engine-globals.md`](../sage_patch/docs/engine-globals.md) — the subsystem singletons.
- [`live-object-model.md`](../sage_patch/docs/live-object-model.md) — the object table, the
  `Object` layout, ownership, the body module, and the two upgrade masks.
- [`message-stream.md`](../sage_patch/docs/message-stream.md) — how an order reaches the engine.
- [`live-api.md`](../docs/live-api.md) — the design and its milestones.

## Known gaps

- **Construction reports state, not progress.** `under_construction` is verified (below), but
  there is no percentage: how far along a structure is remains unread.
- **Ownership misses script teams** — 2 objects of 523 in a live match, reported as no owner.
- **The revive list is reconstructed, not read.** A hero's index comes from the faction roster
  and what the map shows, which is exact for a hero never yet fielded and inferred from observed
  deaths for one being re-recruited — a session that started mid-match has not seen those. The
  button-to-hero binding is likewise derived from the slot block's shape rather than read out of
  the ControlBar's own walk (`0x00943F81`), and 9 of the tree's 187 playable-faction producers
  do not line up under it; `Statics.check_revive_slots` names them, `RohanCitadel` included.
  Map-scoped `BuildableHeroesMP` overrides are not applied. See
  [`hero-recruitment.md`](../sage_patch/docs/hero-recruitment.md).
- **Science names need an ini load** — the last id space that does. `TheScienceStore` is a
  `std::vector` at `+0x0C` exactly like `TheSpecialPowerStore`, and it holds **263 pointers,
  which is exactly the 263 sciences the ini tree defines**. That count agreeing to the entry is
  good evidence the vector *is* the registry in registration order, so the ini rule is
  corroborated even though the live path is not usable yet.

  What blocks it is the element: the entries are **separately allocated and of different
  sizes** (0x80, 0x70, 0x78, 0x58 apart), all sharing one vtable, and no offset in the first
  0x100 bytes names more than a fifth of them. The `SCIENCE_*` strings sit adjacent in memory,
  so a scan for "a pointer whose target reads as a name" finds mostly coincidences — one such
  hit pointed into the *middle* of a neighbouring string. Reading it needs the parser followed
  statically, not another differential.

  `TheSpecialPowerStore` *is* walked — same vector shape, which is why the linked-list pass
  first missed both — and its 1,566 names agree with the ini reconstruction position by
  position on every single one.
- **Thing ids are corroborated, not round-tripped** — but the corroboration is now measured.
  `thing_order` anchors index 0 at `DefaultThingTemplate`, contains every template any live
  object uses, and has no duplicate names. Against the ini tree it reads 11,142 templates to
  11,132, and the two are **identical up to index 11,086**; in a live match all 69 templates in
  play agreed exactly, over ids 3 to 10,994. So the gap is confined to the tail, well above
  anything a match touches. No order carrying one of these ids has yet been seen to build the
  thing it names, and only the ini rule has corpus backing (491/491 `FOUNDATION_CONSTRUCT`
  orders), so `resolve.Resolver` is still the path to prefer where a game tree exists.
