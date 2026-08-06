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

## Layout

Three folders, because there are three genuinely different kinds of module here and a
consumer should not have to guess which is which.

```
sage_live/
  __init__.py     the supported surface — every name below is re-exported here
  __main__.py     the `sage-live` inspector
  api/            the interface      connect · session · observation · orders
  backends/       where bytes come from   base (+ Loopback) · memory · bridge
                                          protocol · identity · snapshot
  utils/          the lookups        naming · heroes · resolve* · statics*
```

`* needs a game install` — `resolve` and `statics` import `sage_ini`, so they are the only two
modules not reachable from the root. Import them from their own module:

```python
from sage_live.utils.statics import Statics
from sage_live.utils.resolve import Resolver
```

Everything else is re-exported, so `sage_live.attach`, `sage_live.Observation` and
`sage_live.orders.move` are the supported spellings; the folders are for reading the source,
not for everyday imports. Dependencies point one way — `api` uses `backends` and `utils`,
`backends` uses neither, `utils` uses only the two model modules in `api`.

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
| `PlayerState` | economy, spellbook points, held sciences, command points, PLAYER-scoped upgrades |
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
from sage_live.utils.statics import Statics

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

## Buying a spellbook power

```python
from sage_live.utils.statics import Statics

statics = Statics.from_root(root)
held = {n.lower() for n in ("SCIENCE_MEN",)}          # or read them live, see below
for power in statics.spell_store("Men"):              # PurchaseScienceCommandSetMP
    if power.purchasable and power.enabled_for(held) and power.cost <= me.power_points:
        game.confirm_power(lambda: game.purchase_power(power.science), power.science)
        break
```

Powers are bought with **spellbook points**, a currency that buys nothing else — so a policy
that never spends them is throwing away everything they would have bought, and no gold decision
is affected either way.

`Statics.spell_store(faction)` is the store's own palette, the same command-set rule everything
else here obeys: a `PURCHASE_SCIENCE` button on the faction's `PurchaseScienceCommandSetMP` is a
button the spell store would have shown. Each `PowerButton` carries its price in points
(`SciencePurchasePointCostMP` — **not** the single-player field, they differ for nearly every
power) and its prerequisites as *alternative all-required groups*: `SCIENCE_GOOD OR SCIENCE_MEN
SCIENCE_RebuildMen` is two ways in, and reading it as a flat list opens the whole book at once.
Every store is padded to twenty slots with `Command_PurchaseSpellEmpty`, and `purchasable`
excludes those by what the data says rather than by name.

**What is already held is read, not remembered.** `PlayerState.sciences` is the player's own
science vector, which is the only observable answer — a science lands in neither upgrade mask.
It carries **ids**, not names, because naming them still needs an ini load (see Known gaps), so
membership is tested through a resolver: `names.science("SCIENCE_RebuildMen") in me.sciences`.

Bookkeeping would have been wrong as well as unnecessary: a skirmish AI is *granted* spells by
script with the ini's prerequisites bypassed — one measured Mordor seat held `SCIENCE_Darkness`
holding none of the three sciences that unlock it. `confirm_power` therefore watches the science
appear rather than the points fall; points rise on their own clock, which is `confirm_spend`'s
trap in a second currency.

## What a bought power actually does

```python
for power in statics.spell_book("Men"):           # the SpellBookMp's command set
    if power.castable and power.enabled_for(held):
        print(power.power, power.form, power.effect, power.radius, power.reload_seconds)
# SpellBookRebuild        location heal    150.0 180.0
# SpellBookArrowVolleyGood location strike  95.0 360.0
# SpellBookArmyoftheDead  location summon 200.0 830.0
```

Casting is a **different command set from buying** — the store hangs off the `PlayerTemplate`,
the book off the `SpellBookMp` object, and they are different lengths (Gondor sells 11 powers
and shows 15 buttons). The book is also what disambiguates the science: `RequiredSciences` is
one-to-many, with three sub-faction variants requiring `SCIENCE_GraueSchaar` alone, and only one
of each family is on the faction's actual book.

**`form` decides the order** and comes from the firing button's `Options`, never from what the
spell sounds like — the corpus confirms the engine picks the order type to match the
`NEED_TARGET_*` bits on every recorded cast. A button with **no target and no recharge** is not
an order at all: it is a power whose whole effect landed when it was bought (Gondor's Gandalf
the White, Formationen Gondors). Casting one is discarded in silence.

**`effect` is the one thing no ini field states**, so it is read off the module on the spellbook
object that implements the power — the same "ask the module" rule behind production queues and
lair spawns. `Enum` looks like it should answer and does not: Edain declares Army of the Dead as
`SPECIAL_SPELL_BOOK_BOMBARD` with the army-of-the-dead slot commented out beside it.

A summon and a bombardment are the *same* module (`OCLSpecialPower`), so what separates them is
where the creation chain ends — and it never ends in one hop. Every one of these creates an
**egg** that dies immediately and whose `SlowDeathBehavior` names the next list; `Statics.creates`
follows that to the templates finally placed, guarded against cycles because `OCL_SpawnEagles`
genuinely recreates its own members. Ending at units is a summon, at a structure a build, at
`UNATTACKABLE` scenery a strike.

**And scenery carrying a weapon is not proof of hostility.** Edain delivers friendly effects the
same way: `EndloseHordenPing` fires a weapon that hands every horde a banner, and
`BeistandinderNotNormalEgg` attaches to your own beacon before firing. The relationship token on
the filters those created objects carry is what settles it — `SAME_PLAYER`/`ALLIES` against
`ENEMIES`. Where nothing in the chain names a side, the effect is reported as **unknown** rather
than guessed: 3 of Mordor's 16 buttons land there, and a wrong guess spends a recharge measured
in minutes helping the wrong army.

Recharge is the shape of the whole decision. `reload_seconds` runs from 180 to 940, so a power
fires a handful of times a match — and it is the *undiscounted* figure, since Edain's
`SpellRechargeModifierUpgrade` shortens it as live player state, so treating it as the cooldown
is conservative and never early.

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

**`producer_id` is the second link, and the two can disagree.** `Object+0x78` is an `ObjectID`
naming whatever produced this object, and unlike `parent_id` it is *not* cleared when the object
leaves what it names — the engine falls back to it when deciding which horde an attack should
really be aimed at. On a healthy match they agree everywhere (all 40 members of the recorded
fixture name their own container), so the interesting reading is a disagreement: a unit with no
`parent_id` whose `producer_id` still names a live horde is a battalion that came apart. That,
plus `status` — the engine's own `ObjectStatus` bits, where `HORDE_MEMBER` and
`IS_LEAVING_FACTORY` say whether a unit is in a battalion and whether it has finished coming out
of the building — is what
[`horde_formation.py`](../examples/sage_live/horde_formation.py) watches; the engine side is
[`horde-formation-orphans.md`](../sage_patch/docs/horde-formation-orphans.md).

## Moving the camera

```python
here = game.camera()                      # the live ViewLocation, or None if unreadable
game.look_at(centroid_of(fight))          # re-aim, and touch nothing else at all
game.look_at(plot.position, zoom=0.6)     # override one scalar - see the warning below

with CameraPan(game) as pan:              # a thread that eases toward whatever it is given
    pan.aim(centroid_of(fight))           # cheap, and safe from any thread
```

**The camera is not an order and is not throttled.** No logic reads it, so a placement cannot
desync a match, cannot be discarded by game logic, and never enters the message stream. It costs
no APM either: a policy that frames what it is doing is not playing faster, it is being
watchable.

**Keeping the zoom means not writing it.** `look_at` writes the view's position field directly
and does not read the camera first. It once did the obvious thing — capture the live
`ViewLocation`, replace the position, hand it back — and that is broken at the engine level:
`View::setLocation` writes all four scalars every call, and each is *read* from one field and
*written* to another, so the zoom it reports cannot be written back. Measured live, echoing a
just-captured location moved the zoom by 0.047 and the client restored it over the next 0.6
seconds. A policy re-aiming every cycle therefore zoomed in and snapped out, forever. Passing
`zoom`, `angle` or `pitch` asks for exactly that write, so those still take the old path — use
them when you mean to, and not otherwise.

It does not **interpolate**: a placement is a jump. `CameraPan` is the interpolation, and it is a
thread because it has to be — a policy deciding every two seconds and easing one step per
decision is a jump every two seconds, however small the step. A re-aim is twelve bytes with no
handshake, so the pan can write at 160 Hz, which is what reads as a pan. It stops writing once it
arrives, so a settled camera is still yours to move.

Being served is not proof of arrival — the view clamps a placement to the map's camera limits, so
`camera()` is what says where it actually ended up. `position` is the look-at point **on the
terrain**, not the camera's eye; the camera's own altitude is derived from it and is not in the
struct. Only a bridge-backed session can move a camera at all; every other backend answers None
or False rather than pretending.

Derivation, the live measurements, and the one field that is carried unnamed because nothing in
the binary says what it is: [`camera-control.md`](../sage_patch/docs/camera-control.md).

## `Statics` — the join, and why you cannot skip it

```python
from sage_live.utils.statics import Statics          # imports sage_ini; not re-exported

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
| what is my army? | "mobile, has a body, not a structure" — that also counts a farm's civilians and a battalion's standard | `SELECTABLE` **and** not `is_slaved` |
| is that an enemy? | "owned by someone else and it moves" — the map's rabbits and fish qualify | `INERT` rules them out |
| why is this flag still guarded? | killing the defenders — a lair replaces every one of them | `spawns` finds the lair; then `is_rebuild_hole` finds the stump that rebuilds it |

`kind_of` resolves inheritance and SAGE's delta form (`KindOf = +SUMMONED`), because a
`ChildObject` does not restate its parent's flags — reading the field directly reports nothing
for a large share of real templates, `GondorBuildingFoundation_Independant` among them. It also
expands `#define`s, because 136 templates write their whole `KindOf` as a macro and then answer
"carries nothing" to every question — every animal in the tree is `NATUREUNITS_KINDOF`, and a
lair's stump is `WILD_HOLE_KINDOF`.

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

**Observations arrive whole-map, and some of what they carry a player could never know at
all.** These are two different problems and only one of them is about visibility.

*Visibility* is fog, and it is now readable. `attach(fog=True)` filters every observation down to
what the seat can actually see, using the engine's own per-cell shroud grid, and the snapshot
records `fogged` so a consumer can tell which it is holding. Left off — the default, because it
changes what every existing consumer sees — you read the whole map. One thing the grid does not
carry is a memory: a scouted building disappears again when the scout leaves, where a real player
would still see it drawn. See [`fog-of-war.md`](../sage_patch/docs/fog-of-war.md).

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
