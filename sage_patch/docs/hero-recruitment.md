# Hero recruitment: the revive system

How a hero is ordered, what index the order carries, and which building may legitimately
recruit which hero. Targets RotWK 2.01 + Edain; the order shape is the engine's and the slot
conventions are the mod's.

The implementation is [`sage_live/heroes.py`](../../sage_live/heroes.py) and the revive half of
[`sage_live/statics.py`](../../sage_live/statics.py).

## 1. The order

A hero is **not** queued by template id. `QUEUE_UNIT_CREATE` (`0x417`) carries five arguments,
and the leading boolean picks how the second is read:

| flag | second argument | constructor |
|---|---|---|
| False | a `thing_template_order` id | `orders.recruit` |
| True | a **revive index** | `orders.recruit_hero` |

Byte-identical otherwise, which is why the two were confused for as long as they were: feeding
a `CommandSet` slot number to the flagged form is accepted, charged, and produces a hero — just
not the one asked for.

## 2. The index space

The revive index is a **0-based position in the player's `BuildableHeroesMP` list**, which
`PlayerTemplate` declares and which lives in `sage_ini`'s `factions` table. `CreateAHero` holds
position 0 for every playable faction.

Confirmed against two live recruits (RotWK 2.01 + Edain):

| order arg | producer | roster entry | what appeared |
|---|---|---|---|
| 7 | `GondorBarracks` | `FactionMen[7]` = `GondorImrahil` | Imrahil |
| 1 | `LothlorienCastleBaseKeep` | `FactionElves[1]` = `LothlorienRumil` | Rumil + Orophin |

`LothlorienRumil` fields a pair — Haldir's brothers share one roster entry, with
`LothlorienOrophin_Slaved` and a joint `RumilundOrophinDeath` — which is why the second recruit
was first written down as "the hero Orophin".

**Both samples were taken before any hero had been fielded**, so they confirm the index *space*
without discriminating a static roster position from a live submenu position. The order stream
says it is the latter: `sage_replay/heroes.py`, ground-truthed on three Linhir replays, has a
fielded hero leave the list with everything behind it sliding forward, and a killed hero
rejoining at the tail. `sage_live` applies those rules against what an observation can see.

## 3. Heroes bind to REVIVE buttons by position

A hero is reached through a `CommandButton` whose `Command` is `REVIVE`. The binding is
positional, so a building that recruits the fourth hero must carry the first three slots too —
every such building carries the whole block, and the slots it must *not* offer are disabled with
a `NeededUpgrade` it can never hold (`Upgrade_HasDragonNestFireDrake` throughout Edain).

The offset is one, because position 0 is the Ring-hero slot and the Ring hero is not a roster
entry:

```
roster_index = position - 1
```

`GondorBarracksCommandSet`, read by `Statics.revive_slots`, with only two of fourteen live:

| position | slot | button | serves |
|---|---|---|---|
| 0 | 15 | `Command_FakeRingHeroReviveSlot` | the Ring hero |
| 1 | 16 | `Command_FakeCreateAHeroReviveSlot` | `CreateAHero` |
| 2 | 17 | `Command_FakeHeroReviveSlot1` | `RohanPippin_mod` |
| **3** | 18 | **`Command_GenericReviveSlot2`** | **`GondorBeregond`** |
| 4 | 19 | `Command_FakeHeroReviveSlot3` | `GondorDenethorMod` |
| **5** | 20 | **`Command_GenericReviveSlot4`** | **`GondorBoromir_mod`** |
| 6–13 | 21–28 | `Command_FakeHeroReviveSlot5..12` | the rest |

Beregond and Boromir are exactly the heroes an Edain Gondor barracks offers. A human reaches
the block through `Command_SelectRevivablesGondorKaserne`, a `PUSH_VISIBLE_COMMAND_RANGE` over
slots 14–29 — that button sits inside the range and is not itself a REVIVE, so counting it would
shift every hero by one.

### What corroborates the offset

Many Edain revive buttons are named after the hero they recruit, which is an author's statement
of the binding and independent of where the button sits. **220 of 231 such buttons across the
tree land on their own roster entry.** The Lothlorien keep has four in a row:

| position | button | serves |
|---|---|---|
| 2 | `Command_HaldirsBruderGenericReviveSlot` | `LothlorienRumil` |
| 3 | `Command_HaldirGenericReviveSlot` | `LothlorienHaldir` |
| 4 | `Command_CelebornGenericReviveSlot` | `LothlorienCeleborn` |
| 5 | `Command_GaladrielGenericReviveSlot` | `LothlorienGaladriel` |

Of the eleven that do not, six are `Command_HaldirsBruder...` matched by substring against
Haldir when it means Rumil — correct after all. Two are permanently-gated fillers. Two are on
`RohanCitadel`, which also carries an enabled slot serving entry 12 of an eight-entry roster and
so does not line up at all; `Statics.check_revive_slots` reports that shape, and 9 of the tree's
187 playable-faction producers trip it.

**The numbers inside these button names are not roster indices.**
`Command_GenericReviveSlot1` occurs at positions 0, 1, 3 and 4 in different sets, so its number
identifies the button. Only the hero names carry information.

## 4. The engine will recruit a hero the interface never offered

`BuildAssistant::canMakeUnit(producer, what, reviveIndex)` is the gate every producer-facing
consumer reaches, the control bar and `ProductionUpdate::queueCreateUnit` included. Its revive
branch, at `CAN_MAKE_UNIT_REVIVE_BRANCH`, **tests only `Command == REVIVE` and a positional
count**, accepting when the count reaches `reviveIndex`. It never reads `Options` or
`NeededUpgrade` — the defect [`ai_revive_gate.py`](../patches/ai_revive_gate.py) repairs for the
AI, deliberately leaving every path a human touches alone.

So a well-formed order naming any index the producer's slot block can *count to* is honoured,
including the slots a control bar hides. The Imrahil recruit in §2 was one of these: index 7
matched position 7, `Command_FakeHeroReviveSlot6`, which no player can see.

Two consequences worth stating separately:

- **The gate's bound and the control bar's are not the same.** The gate needs `index + 1` REVIVE
  buttons to count to; the slot a human would have clicked is at position `index + 1` and needs
  one more. `Session._check_revive` applies each where it belongs.
- **Nothing reports the difference.** A recruit the interface would have refused looks exactly
  like one it would have allowed: charged, queued, and visible in the replay.

`Session.recruit_hero` therefore gates on `godsight`, the session flag that already marks
knowledge a real player could not have:

| | may recruit |
|---|---|
| `godsight=True` | any hero any building's slot block can reach — the engine's real behaviour |
| `godsight=False` | only a hero whose slot at that building exists and is **enabled**, its `NeededUpgrade` met by the player's or the building's own upgrades |

Either way an index past the block is refused outright, since the engine consumes that order and
discards it in silence.

## 5. Confirming a hero recruit

The production queue already reports revives: `ProductionEntry.kind` is 3 for one, decoded as
`ProductionItem(kind="revive")` with the hero's template resolved by pointer identity against
`TheThingFactory`. So `Session.confirm_queued` is the oracle, and needs nothing new:

```python
game.confirm_queued(lambda: game.recruit_hero("GondorBeregond"), barracks.object_id)
```

Gold is not an oracle here for the usual reason — the balance is contested — and neither is the
hero appearing, since a revive takes time and the hero spawns at the producer's rally point.

## 6. What is still open

- **The ControlBar's own walk (`0x00943F81`) has not been disassembled.** The offset in §3 is
  inferred from the data and two live samples, not read out of the binary. It is the only place
  the button-to-hero mapping is authoritative, and where it and the gate's count disagree the
  stock engine cannot tell, because the gate never reads the button it matched.
- **The revive list is not read from memory.** `sage_live` reconstructs it from the roster and
  what the map shows. That is exact for a hero which has never been fielded — the ordinary case
  — and inferred for one killed after fielding, which rejoins at the tail in an order only a
  session that watched it die can know.
- **Map-scoped rosters are not applied.** A `map.ini` may redefine `BuildableHeroesMP`, and
  several Edain maps do; `Statics.hero_roster` reads the base tree.
- **The nine producers that do not line up** (§3) have not been checked against a running game.
  `RohanCitadel` is the one worth doing first.
