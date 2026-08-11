# The live object model — enumerating and reading game objects

Recovered against RotWK 2.01 + Edain, `game.dat` pid 2876, 2026-07-29. Read-only
`ReadProcessMemory` from an elevated handle; no injection, no writes.

**Verdict up front.** Unknowns 1 and 2 of [`live-api.md`](../../docs/live-api.md) §9 are solved.
Every live object can be enumerated with its id, template, side, world position, facing and
health — which is the whole of `Observation.objects` in that document's §5 model, minus
production/queue state.

Start from [`engine-globals.md`](engine-globals.md): `TheGameLogic` is at `0x00DE412C`.

## 1. The object table (unknown 1)

Not a linked list. `TheGameLogic` carries a **flat id-indexed table**:

| offset | meaning |
|---|---|
| `+0x40` | **current logic frame** (ticks continuously; this is `Observation.frame`) |
| `+0xB8` | table begin |
| `+0xBC` | table end — `(end-begin)/4` = **12289** slots |
| `+0xC0` | capacity end (== end) |
| `+0xC4` | **live object count** |

Entries are **not** `Object*`. Each is a small wrapper:

```
entry + 0x04   ->  the object's id
entry + 0x08   ->  Object*
```

That indirection is the trap: validating table entries directly as objects fails on all of them.

**Proof the table is right.** Non-null slots numbered exactly 525, matching `+0xC4`; and slot 1's
`+0x08` is byte-identical to the pointer at `TheGameLogic+0xAC`, which independently resolves to a
`WallHubTemplate` object.

A full enumeration of the test game (solo skirmish, one human):

| side | objects |
|---|---|
| Civilian | 286 |
| Men (the human) | 71 |
| Neutral | 66 |
| Mordor | 56 |
| Wild | 32 |
| Flags | 14 |

**This is the lever on OPEN 8** of [`order_space_map.md`](../../sage_replay/order_space_map.md).
That item records runtime `ObjectId` → template as unsolved, which is why replay move/cast orders
name handles rather than units. Live, the id sits next to the `Object*` in this table, so the
mapping is a lookup.

✅ **The id is numerically the same id the order stream carries** (verified 2026-07-29). An
injected `MSG_CREATE_SELECTED_GROUP` carrying object id `400` — read straight from this table —
was recorded in the resulting replay as `ObjectId 400`. One id space, so an id read here can be
put into an order, and an id parsed out of a stream names a row in this table.

**That settles the live half of OPEN 8, not all of it.** OPEN 8 asks for `ObjectId` → template
*from the stream alone*, so that an archived replay can say which unit a power targeted. That
still needs creation tracked through the stream, because narrating an old replay has no process
to read this table from. What is now certain is that such tracking is chasing the same numbers
this table holds.

## 2. `Object` layout (unknown 2)

| offset | field | notes |
|---|---|---|
| `+0x00` | vtable | |
| `+0x04` | `ThingTemplate*` | name at `+0x64`, `Side` at `+0x6C`, `CommandSet` at `+0x70` |
| `+0x08`–`+0x37` | `Matrix3D` | 3 rows × 4 floats, row-major |
| **`+0x14`** | **world X** | matrix row 0 translation |
| **`+0x24`** | **world Y** | row 1 translation |
| **`+0x34`** | **world Z** | row 2 translation |
| `+0x08`, `+0x18` | cos / sin | facing = `atan2([+0x18], [+0x08])` |
| `+0x38`–`+0x40` | cached position copy | mirrors X/Y/Z |
| `+0x8C` | linked object | ⚠ type-dependent, see below |
| `+0x90` | linked object | ⚠ type-dependent, see below |
| **`+0x25C`** | **`BodyModule*`** | present on every object, but only *valid* on some - see §3 |
| `+0x158`–`+0x17C` | second `Matrix3D` copy | |

**`+0x8C` / `+0x90` are the global object list's `next` and `prev`.** Not horde links, and not
a type-dependent slot either — one doubly-linked list threading *every* live object. Measured on
a 318-object match:

| check | result |
|---|---|
| objects whose `+0x8C` points at another table entry | 317 of 318 |
| objects whose `+0x90` points at another table entry | 317 of 318 |
| `prev(next(x)) == x` | 317 of 317 |
| `next(prev(x)) == x` | 317 of 317 |
| maximum in-degree | 1 |
| entries with no `prev` (head) / no `next` (tail) | exactly 1 each |
| objects reached by walking `next` from the head | 318 of 318 |

A star would be a container; a single chain with in-degree 1 and a clean head and tail is a
list. Reading these two fields as horde membership, or as a wall's neighbour chain, is an
artefact of **creation order**: a battalion's members are created consecutively, so `next`
looks like "the next member of my horde" and `prev` looks like "my containing horde"; wall
segments are created consecutively too, so the same fields look like a neighbour chain. Neither
reading survives asking the whole table at once.

Two consequences. **Horde membership is not readable here at all** — `sage_live` leaves
`parent_id` unset because the information is absent, not because it is ambiguous. And this is a
*second, independent enumeration* of the object table: walking the list must yield the same set
as walking `+0xB8`..`+0xBC`, which makes each a check on the other.

The template chain terminates at a human-legible name, which is what proves every link at once —
the technique from [`runtime-re-workflow.md`](runtime-re-workflow.md) §5.

### 2a. Ownership — `Object+0x31C` is a `Team*`, not a player

| offset | field | notes |
|---|---|---|
| `Object+0x31C` | `Team*` | the owning team; groups objects exactly per player |
| `Player+0x30C` | `Team*` | that player's own team — invert this to get the owner |

**Ownership is not on the object as an index or a `Player*`.** Searching every `Object` for a
known `Player*` found nothing, directly or one hop away. What worked was grouping objects of
known ownership and looking for any field constant within a group and distinct between groups:
`+0x31C` partitioned 58 templates into four buckets whose sides were exactly `Men` (the local
player), `Mordor`+`Wild` (the creeps), and two civilian/neutral sets. The pointers sit ~0x318
apart, so these are consecutive `Team` structs in a pool.

`Team` carries no back-pointer to its `Player` — its first 0x400 bytes hold no known `Player*` —
so the mapping has to be built from the player side. Every player's `+0x30C` matched the bucket
its objects fell into, across all five slots including the unnamed neutral one.

**Do not substitute the template's `Side` for ownership.** It genuinely disagrees, in both
directions, measured in one live match:

- the creeps owned **18** objects whose template `Side` is `Neutral` (creep lairs),
- the local player owned one whose `Side` is `Civilian`,
- and a sandbox hero the local player owned had `Side = Mordor`.

**Coverage is 521/523.** A player may own several teams and script teams exist — two objects
(map scenery) sat on teams that are no player's default. Those are reported with no owner rather
than assigned to a plausible one. Closing that gap needs the team list itself, presumably from a
`TheTeamFactory`-style global.

## 3. The body module — health

`[Object+0x25C]` is the body (`ActiveBody`):

| offset | field | value on an undamaged unit |
|---|---|---|
| `+0x04` | ? | `1.0` |
| **`+0x08`** | **currentHealth** | == max |
| `+0x0C` | previousHealth | `-1.0` when there is no previous |
| **`+0x10`** | **maxHealth** | |
| `+0x14` | `DamagedThreshold` | `0.50` |
| `+0x18` | `ReallyDamagedThreshold` | `0.25` |
| `+0x1C` | initialHealth | == max |

So `Observation`'s health fraction is:

```
[[obj+0x25C]+0x08] / [[obj+0x25C]+0x10]
```

**How it was pinned — triangulation against ini ground truth.** Three lair templates with three
*different* documented `MaxHealth` values were read out of `__edain_data.big`
(`MoriarGoblinLair` 2000, `WargLair` 3000, `FireDrakeLair` 4000). Walking the object graph three
pointer levels deep and keeping only paths where **each template holds its own max** left exactly
one module — `+0x25C` — with four candidate slots inside it. Damaging units then separated them:
`GondorFighter` (max 255) read `237.9`, `215.0`, `167.0`, `146.9` at `+0x08` while `+0x10` stayed
`255.0` throughout.

Two field readings are inferred rather than proven: `+0x0C` as previousHealth (from the `-1.0`
sentinel on never-damaged units) and `+0x1C` as initialHealth (constant, equal to max). `+0x08`
and `+0x10` are solid.

**Not every object has a body, and the pointer does not tell you that.** `+0x25C` is populated
on every object, but on inert map markers - `WallHubTemplate`, `FarmTemplate` - it points at
uninitialised memory that reads as `current = 0.0`, `max = 1.8191141e-38` (a denormal). Taken
at face value that makes every wall hub and farm spot look destroyed. **Validate before
believing**: a real body has `max >= 1.0` and `0 <= current <= max`. Live, 48 of 524 objects
failed that check and were correctly excluded, leaving exactly the 9 units that had actually
taken damage.

Confirmed live across object types:

| template | `+0x25C` current / max | reading |
|---|---|---|
| `GondorFighter` | 237.9 / 255.0 | real, damaged |
| `MoriarGoblinLair` | 2000.0 / 2000.0 | real, matches ini |
| `CampOnly10` | 99999.0 / 99999.0 | real (indestructible scenery) |
| `WallHubTemplate` | 0.0 / 1.8e-38 | **no body** |
| `FarmTemplate` | 0.0 / 1.8e-38 | **no body** |

## 3a. Upgrades — two scopes, two masks, and one field that lies

Recovered 2026-07-30 in a live RotWK+Edain skirmish, by researching upgrades through the
live bridge and diffing the structs.

| offset | field | notes |
|---|---|---|
| `Player+0x0BC` | upgrades **in progress** | ⚠ never cleared for object-scoped upgrades |
| `Player+0x14C` | upgrades **completed** | player-scoped upgrades only |
| `Object+0x28C` | upgrades **completed** | the object-scoped ones, per object |

All three are bitsets indexed by the engine's own upgrade id: **bit `id % 32` of the dword at
`base + (id // 32) * 4`**. That id is the same number a replay order carries, so one integer
serves the stream, the registry and these masks.

**How they were pinned.** With 976 upgrades a 64-bit mask is impossible, so the prediction was
sharp before any measurement: researching id N must set one specific bit of one specific dword.
Two upgrades landing in *different* words were researched, and each bit appeared exactly where
its id said it would:

| upgrade | id | word, bit | in progress | completed |
|---|---|---|---|---|
| `Upgrade_MarketplaceUpgradeIronOre` | 420 | 13, 4 | `+0x0F0` set then cleared | `+0x180` set |
| `Upgrade_TechnologyGondorForgedBlades` | 472 | 14, 24 | `+0x0F4` set then cleared | `+0x184` set |
| `Upgrade_GondorForgedBlades` (object) | 473 | 14, 25 | `+0x0F4` set, **stayed set** | `Object+0x2C4` |
| `Upgrade_GondorHeavyArmor` (object) | 475 | 14, 27 | `+0x0F4` set, **stayed set** | `Object+0x2C4` |

Calibrating on a single word would have proved nothing — two adjacent bits match as a set under
an off-by-one base, the same trap [`order_space_map.md`](../../sage_replay/order_space_map.md)
OPEN 4 records for the id space itself.

**`Player+0x0BC` is a trap if read as "researching now".** A player-scoped research sets the bit
and clears it on completion, which is what the name suggests. An **object**-scoped purchase sets
the same bit and the engine never clears it — bit 25 was still set hundreds of frames after the
battalion had visibly received its blades. Read naively, every battalion upgrade ever bought
looks permanently pending. `sage_live` filters this mask by the definition's scope, so it reports
only what it can report honestly.

**Object scope was settled with an effect, not an inference.** `Upgrade_GondorHeavyArmor` raises
hit points, so "has it landed?" has an answer the API can read by itself. In the same sample
where the member's `max_health` went **255 → 510**, both the horde's and the member's `+0x2C4`
gained the bit — and the player's completed mask never did. So `Object+0x28C` is completed, not
in-progress, and an object-scoped upgrade is recorded *nowhere* on the player. The untouched
second battalion held no such bit, which is the negative control.

A horde **and every member** carry the same bit, so a consumer counting upgrades across objects
will see one purchase 16 times.

**Width.** The two player masks sit `0x90` apart, which is more room than the `0x7C` that 976
upgrades need, so the arrays are wider than the ids in use. Read only as far as the registered
count (`ceil(count / 32)` dwords); a stray bit in the unused tail must never decode to an
upgrade.

## 3a-bis. Sciences — `Player+0x310`, a vector rather than a mask

Recovered 2026-08-04 in a live RotWK+Edain skirmish, by scanning each `Player` for a pointer
whose target decodes as ini-order science ids.

| offset | field | notes |
|---|---|---|
| `Player+0x310` | held sciences | `std::vector<ScienceType>` — `{begin, end, capacity}` |

**Not a bitset, unlike the upgrades next door.** With 263 sciences a mask would be 9 dwords and
the obvious place to look; the engine keeps a vector of ids instead, so the count is
`(end - begin) / 4` and — as with `TheSpecialPowerStore` — there is no count field to check the
walk against. Reading to `capacity` rather than to `end` picks up whatever the allocation still
holds, which decodes as perfectly plausible sciences belonging to other factions.

**Pinned by what it decodes to, not by its shape.** Across one match's five seats: every seat
carried the four view sciences (`SCIENCE_GENERAL_VIEW`, `..._COMMANDER_VIEW`, `..._UNIT_VIEW`,
`..._GROUND_VIEW`), each playing seat carried its own faction science first (`SCIENCE_MEN` for
the Men seat, `SCIENCE_MORDOR` for the Mordor one) and nobody else's, and the Mordor AI carried
five Mordor spellbook powers on top. A wrong offset does not produce a per-seat spellbook.

That also **corroborates the science id space independently of the replay corpus**: the ids the
engine holds are `game.sciences` index + 1, which is what
[`order_space_map.md`](../../sage_replay/order_space_map.md) §A derives from recorded
`0x414` orders and what `sage_live.api.orders.purchase_power` sends.

**The AI's set does not obey the ini's prerequisites.** The Mordor seat held `SCIENCE_Darkness`
holding none of the three sciences `science.ini` says unlock it, so a skirmish AI is granted
spells by script. This field answers what a player *has*, never how they got it — which is the
right answer for "can I cast it", and the wrong one for inferring an opponent's spending.

The name side is still shut: `TheScienceStore` is a 263-entry vector at `+0x0C` whose elements
are separately allocated, differently sized, and expose no name at a constant offset — see
[`sage_live/README.md`](../../sage_live/README.md) "Known gaps". So `sage_live` reports ids and
leaves naming to an ini load.

## 3b. The upgrade registry — `TheUpgradeCenter`, and the end of OPEN 4

`[0x00DE45A0]` is `TheUpgradeCenter`, and it carries the engine's own upgrade table:

| offset | field |
|---|---|
| `UpgradeCenter+0x0C` | head of the `UpgradeTemplate` list |
| `UpgradeCenter+0x10` | template count (**976** on this build) |

`UpgradeTemplate`:

| offset | field | notes |
|---|---|---|
| `+0x04` | type | `0` = PLAYER, `1` = OBJECT |
| `+0x08` | `AsciiString` name | `Upgrade_GondorForgedBlades` |
| `+0x38` | **registration index** | == the replay id and the mask bit index |
| `+0x64` | next template | the list is **prepended**: the head is the last registered |

The type field partitions cleanly against the ini: 161 templates read 0 and every one of those
whose ini block declares a `Type` declares `PLAYER`; 815 read 1 and every declared one is
`OBJECT`. (`DefaultUpgrade` declares no `Type` and reads 0; the three veterancy upgrades read 1,
which is right — veterancy is per-unit.)

**This settles [`order_space_map.md`](../../sage_replay/order_space_map.md) OPEN 4.** That item
carried `+3` as a ground-truthed but unexplained constant between the ini table and the replay id.
Walking this list shows there is no offset: the replay carries the engine's registration index,
and the engine registers three upgrades of its own — `Upgrade_Veterancy_VETERAN`,
`Upgrade_Veterancy_ELITE`, `Upgrade_Veterancy_HEROIC`, indices 0/1/2 — before parsing a single
`Upgrade` block. **None of the three is defined in ini anywhere** in the mounted tree, so a table
rebuilt from ini is missing exactly three leading entries and needs `+3` to line up. All 976
templates were walked and **976/976** satisfy `engine index == ini index + 3`.

Two consequences worth acting on:

- A live consumer needs no ini load to name an upgrade, and no offset either. `sage_live.backends.memory`
  reads this registry once and decodes the masks straight from it, which also makes it correct
  for whatever mod is loaded rather than for the one tree that was parsed.
- The other three id-space stores (`TheThingFactory`, `TheSpecialPowerStore`,
  `TheScienceStore` — see [`../addresses.py`](../addresses.py)) are the same kind of object and
  have not been walked. If any of their `+1` offsets ever looks wrong, this is the way to check.

⚠ **Method note — `x or -1` fabricated two anomalies here.** A first pass through this table
reported `Upgrade_Veterancy_VETERAN` as index `-1` (breaking the otherwise perfect 0,1,2 run) and
every PLAYER-scoped upgrade as type `-1`. Both fields are `0`; the probe read them with
`value or -1` as a None-guard, and `0 or -1` is `-1`. The lesson is narrow and worth keeping:
when a field's valid range **includes zero**, a falsy-default read cannot distinguish "absent"
from "zero", and the fake value it invents is exactly the kind of off-by-one anomaly that then
gets written up as an engine quirk. Guard on `is None`.

## 3c. The thing registry — `TheThingFactory`

Same shape as `TheUpgradeCenter`, so the thing id space is readable from the process too.

| offset | field | value on RotWK 2.01 + Edain |
|---|---|---|
| `TheThingFactory+0x0C` | head of the template list | `TreasureChest_Expedition` |
| `TheThingFactory+0x10` | template count | 11,143 |
| `ThingTemplate+0x494` | `next` | walks 11,142 |

**The id is the walk position, not a stored field.** An `UpgradeTemplate` carries its own index
at `+0x38`; no equivalent turned up on a `ThingTemplate` within `0x120` of its head. The list is
prepended, so reversing the walk gives registration order — and index 0 comes out as
`DefaultThingTemplate`, which is exactly what an id space with `THING_OFFSET = 1` puts at id 1.

That is corroboration, not proof, and the distinction matters because the walk is **one short of
the count**. Three checks bound the risk:

- every `ThingTemplate` referenced by a live object (51 distinct) is present in the chain,
- no name occurs twice, and none is empty,
- index 0 is `DefaultThingTemplate`, so nothing is missing ahead of the first registration.

A shortfall at the *tail* — the newest registration — shifts no id, because the reversal anchors
index 0 at the oldest. A gap in the middle would shift everything after it, so `thing_order`
emits a diagnostic whenever the walk and the count disagree rather than staying silent.

**Not yet confirmed by a round trip.** No order carrying one of these ids has been observed to
build the thing it names: `build_at` against a build plot was refused for six candidate ids
(resources unchanged, which is the oracle), and the player owned no producer at the time, so
`recruit` could not be tested either. Treat a wrong build as a possible id error.

## 4. Method notes — four dead ends worth not repeating

**Read window too small.** The body module is at `+0x25C`; scans using a `0x180` object window
miss it entirely. Read at least `0x400` before concluding a field is absent.

**Diffing a fight is swamped by movement.** `+0x14`/`+0x24` change constantly as units walk, so
"floats that decreased during combat" returns almost pure position noise. Attacking a *stationary*
target removes the confounder — but a lair under attack only revealed spawn timers, because health
is deeper than one pointer level.

**A link field read on one object tells you nothing; ask the whole table.** `+0x8C`/`+0x90`
were read as horde membership, then as a type-dependent slot, and are neither — both readings
came from looking at a handful of objects whose creation order happened to fit. Building the
entire graph and measuring it (in-degree, inverse-ness, head and tail count, reachability)
settled it in one pass and would have settled it the first time.

**Shape alone does not identify a structure.** A begin/end/capacity-looking triple at `Object+0xD4`
held plain floats on a `GondorFighter` while looking like a module vector on a horde object. Align
against a value you can confirm at runtime, never against a shape — the same rule
[`runtime-re-workflow.md`](runtime-re-workflow.md) §6 states.

The technique that actually worked was the ini triangulation: an external source of truth for
several *different* expected values, then keep only the location consistent with all of them.

## 5. What remains

- Production / queue and construction state per object — not located, but **ruled out of the
  object's own header**. A structure was built and then made a battalion while every owned
  object's first `0x400` bytes were sampled every 0.4 s for 531 samples (frames 3856–5484). Over
  that whole life exactly **nine dwords** of the new `MordorOrcPit` ever changed, all of them
  settled by frame 4002, and three were upgrade-mask bits — yet the pit produced a horde at
  frame 4203 with nothing in the window moving. So neither the queue nor the build progress is
  inline: both live in a module reached through a pointer, and the next step is the object's
  module list rather than a wider window.

  Two things that looked like leads and are not. The upgrade mask does not carry it: the new
  structure had `Upgrade_TestBuilding` at creation and `Upgrade_StructureLevel1` two frames
  later, then nothing until an unrelated research. And health cannot stand in for it either -
  a structure ramping its hit points while building is indistinguishable from a damaged one.

  **The far side of that pointer is now mapped**, statically, in
  [`production-model-condition.md`](production-model-condition.md) §5 - which confirms the
  conclusion above and says exactly what the module list leads to. `ProductionUpdate` keeps
  **one** queue for units *and* upgrades:

  | offset | field |
  |---|---|
  | `module+0x08` | `Object *` (the back-pointer, so the list can be walked in either direction) |
  | `module+0x28` | queue head, or NULL |
  | `entry+0x04` | kind — `2` is an upgrade |
  | `entry+0x0C` | payload (`UpgradeTemplate *` for an upgrade) |
  | `entry+0x48` | next entry |

  `ProductionEntry` is `0x54` bytes.

  **The first hop is now found, and this is closed.** `Object+0x24C` holds a pointer to a
  **NULL-terminated** array of `BehaviorModule*`. Read off `getProductionUpdateInterface`
  (`0x0068C327`), which is `mov esi,[ecx+0x24c]` followed by a walk in steps of 4 until it
  loads NULL; three interface getters in a row share the idiom, so it is corroborated three
  times rather than inferred once.

  The engine picks its module out of that array by *calling* each one's second vtable
  (`module+0x0C`, slot `+0x70`), which a reader outside the process cannot do. It does not need
  to: a vtable address is unique to its class, so matching `[module+0x00]` against
  `0x00C67EF4` — the primary vtable the constructor at `0x008A1819` writes — answers the same
  question without executing anything.

  Three fields the table above did not have, from the list insert at `0x008A0C99`:

  | offset | field |
  |---|---|
  | `module+0x2C` | queue **tail** |
  | `module+0x34` | queue **length** — a count, so "is it busy" needs no walk |
  | `entry+0x4C` | previous entry |

  Two things to get right while reading it. The queue is **appended** to, not prepended
  (`production-model-condition.md` says prepended): the head is written only when the list is
  empty, and the tail always. And a unit entry keeps its `ThingTemplate*` at `entry+0x08`, not
  at the `+0x0C` an upgrade uses — `queueCreateUnit` writes `[esi+4]=1; [esi+8]=what` for a
  build and `[esi+4]=3` for a hero revive, so `kind` is 1, 2 and 3 for unit, upgrade and revive.

  `sage_live.backends.memory` reads all of this per object, and checks the walk landed correctly by
  requiring the module's own `Object*` back-pointer to name the object it was reached from.
- **Horde membership: `Object+0x27C` is what contains this object.** The two link fields at
  `+0x8C`/`+0x90` are the global list's `next`/`prev`, as recorded above; the container link is
  a separate inline pointer, and a container's own is null.

  Found differentially rather than by disassembly, which a live match makes cheap: of all 256
  dwords in a member's first `0x400` bytes, this is the one holding its container's address,
  and it did so for 22 of 23 members while nothing else managed more than 2. Checked over a
  whole match afterwards — every one of the 38 objects carrying it pointed at a live object in
  the table, none stood further than 200 units from it, and the pairs were right across four
  factions (`HobbitBounder` → `ImladrisHobbitBoundersHorde`, `IsengardPikeman` →
  `IsengardPikemanHorde`, and an `ImladrisBanner` inside a `BruchtalLancerHorde`, where the
  names disagree but the membership does not).

  Presumably `m_containedBy`, so a garrisoned or transported object should report its holder
  here too; only horde membership has been observed, so only that is claimed.
- **Per-object shroud — fog of war is solved, though not by this route.** Per-player
  visibility is readable from `TheShroudManager`'s per-cell grid, which answers "can this
  seat see that right now" without `PartitionData` at all — see
  [`fog-of-war.md`](fog-of-war.md). `ThePartitionManager` is `0x00DE4354`; `0x00DE4358` is
  `TheShroudManager`, and the 109 references counted below are its.

  What remains open is the per-object `m_everSeenByPlayer`, which is what keeps a scouted
  building drawn after the scout leaves. The grid has no such state, so a consumer's fog has no
  memory.

  **Why the cheap approach is ruled out.**
  [`max-player-count.md`](max-player-count.md) documents `PartitionData` as carrying
  `ObjectShroudStatus m_shroudedness[N]` **per object**, which would make fog a per-object
  lookup rather than a grid query. The hop from `Object` to it was hunted differentially in a
  live match and **is not** a per-player array reachable one pointer from the `Object`:

  | test | scope | result |
  |---|---|---|
  | mirror (mine vs theirs, `arr[me] == theirs[foe]` and vice versa) | every pointer in `Object+0x000..0x400`, 0x300 followed, strides 1, 2 and 4 | one hit, and it is not the shroud — see below |
  | near vs far enemy objects (within 200 of my units vs beyond 900) | same | 9 byte-stride candidates, none shaped like a 20-wide array; nothing at all at int stride |

  So `PartitionData` is reached by more than one indirection, sits further than 0x300 into
  whatever holds it, or is keyed by the object's `m_lastCell` through `ThePartitionManager`
  rather than pointed at directly.

  **The static route reaches the manager and no further.** `ThePartitionManager` is
  `0x00DE4354`, recovered from its registration site the way the other subsystem globals are
  ([`fog-of-war.md`](fog-of-war.md) §1 has the derivation and the neighbouring globals). It is
  referenced from **285** sites, too many to read by hand.

  A scan for the accessor's *shape* - load a member pointer out of `this`, then index an array
  by an argument - found nothing, because it required `this` to still be in `ecx`, which it
  rarely is past a prologue. Worth repeating with the pointer load allowed from any register.
  The other lead not yet pulled is `-xShroudCRC`, a real command-line flag whose handler must
  reach code that walks the shroud.

- **The alliance table is `Team+0x1A8`** — found by the mirror test above, which it passes
  perfectly: a 20-wide per-player byte array where the owning player's own slot reads **25** and
  an enemy's reads **0**, mirrored exactly between the two sides. Reached as
  `Object+0x31C` (the `Team*`) `+0x1A8`. Not yet used, but it is what "allied vision" and a
  correct `opponents` will need, and it is the same team data the shroud work wants.
- Ownership for objects on non-default (script) teams — 2 of 523 live, reported as no owner.
  Needs the team list itself, presumably a `TheTeamFactory`-style global.
- `Player+0x06C` sits with the command-point fields and moved 200 → 400 when a command-point
  grant fired, but has not been matched to anything the game displays.
- **Fog of war — done.** Everything above still reads the whole map, which is the right
  thing for it to do; the filter is a separate deliberate step built on the shroud grid.
  `sage_live.api.shroud` holds the model, `Observation.under_fog` applies it, and
  [`fog-of-war.md`](fog-of-war.md) records the recovery.
