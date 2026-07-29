# `sage_live` examples

Reading a running BFME2 / RotWK game, and issuing orders into it. The library reference is
[`sage_live/README.md`](../../sage_live/README.md); this page is the runnable scripts and the
hard-won gotchas behind them.

## Prerequisites

- **A patched `game.dat`.** Ordering anything needs the live-bridge patch:
  `sage-patch apply live-bridge --in game.dat`. Reading does not — [`patrol.py`](patrol.py) and
  the acceptance scripts need the patch; plain `python -m sage_live info` does not.
- **An elevated shell.** `game.dat` runs as administrator, so `ReadProcessMemory` is refused
  otherwise. Every script fails the same way without it, and says so.
- **A match actually running.** At the menu the object list is empty and the local player index
  is 0, which the scripts report rather than misinterpreting.

Run from the repo root, e.g. `python examples/sage_live/patrol.py`.

## The scripts

| script | needs the patch | what it does |
|---|---|---|
| [`inspect_game.py`](inspect_game.py) | — | A read-only tour of the whole observation surface: players, economy, upgrades in both scopes, your army by template, and the nearest enemy to each of your objects. **Run this first** — if something reads wrong here, the layout is wrong for this build. `--wait` sits at the menu until a match starts. |
| [`patrol.py`](patrol.py) | yes | Selects the starting units and walks them back and forth. The short demo. `--game` names them exactly (see below); without it, it orders the first two things you own. |
| [`recruit_by_name.py`](recruit_by_name.py) | yes | Recruits a unit by template *name* instead of a raw id, via `sage_live.resolve`. Needs a `--game` install to load the tables from. |
| [`upgrades.py`](upgrades.py) | yes | Researches an upgrade by name and verifies it landed, in whichever of the two scopes it belongs to. `--list` first. Needs no `--game`: upgrade names are read out of the engine. |
| [`check_bridge.py`](check_bridge.py) | yes | Staged diagnostic: attach → no-argument order → by-value arguments → by-pointer arguments. Run this first when something is wrong. |
| [`acceptance_inject.py`](acceptance_inject.py) | yes | Injects a scripted opening and logs exactly what was sent. |
| [`acceptance_verify.py`](acceptance_verify.py) | — | Parses the recorded replay and checks it against that log. |

## The acceptance test

This is the one that proves the patch is honest rather than merely working. Injected orders go
in through `TheMessageStream`'s `appendMessage`, so the engine should treat them as real input —
network-ordered, check-summed, and **written into the replay it records**. If they show up in
the replay, injection is genuinely on the normal input path.

**Skirmish mode does not record replays.** Use a one-player *online* game.

```
python examples/sage_live/acceptance_inject.py     # in-game, hands off the mouse
                                                   # then end the game
python examples/sage_live/acceptance_verify.py
```

It also answers whether the id in the runtime object table is the same id the order stream
carries, by injecting a selection built from an id read out of memory and seeing what the replay
records. On RotWK 2.01 + Edain it is the same id — see
[`live-object-model.md`](../../sage_patch/docs/live-object-model.md) section 1.

## Things that will bite you

**Your starting units are only knowable from the `PlayerTemplate`.** A spawned starting unit
carries no marker — nothing in the observation says an object was part of the opening roster.
The engine's answer is the faction's `StartingUnit0..9` slots, which is what `--game` reads
(`sage_utils.views.starting_units`), and the templates named there are the ones on the map.
Matching a name instead reads a convention, not the engine: `..._StartUnit` is how Edain
happens to spell its opening battalions, and it misses the slots any faction fills with an
ordinary template — Edain's own dwarves open with a plain `CarcRaben`.

**An upgrade you bought is probably not in `player.upgrades`.** There are two scopes. Faction-wide
researches (`Upgrade_TechnologyGondorHeavyArmor`, bought at a forge) land on the player;
per-battalion and per-structure ones (`Upgrade_GondorHeavyArmor`, bought on the battalion itself)
land on the **object** and appear nowhere else — not on the player, and not in `template_name`, so
an upgraded battalion and a fresh one are identical except for `max_health` and `obj.upgrades`.
The two look alike and are often named alike, differing only by a `Technology` in the middle.

**`upgrades_in_progress` deliberately hides object-scoped upgrades.** The engine sets their
in-progress bit on the player and then never clears it, so an unfiltered read would report every
battalion upgrade ever bought as pending for the rest of the match. There is no honest way to
observe an object upgrade *while* it is being researched; its completion shows up on the object.

**Name the building; don't rely on the selection.** `research` needs the building's own object
id. Passing 0 — the obvious "use my current selection" — is consumed by the bridge and then
discarded by logic, charging nothing. Selecting the building first does not help. Verified live
against the one upgrade a `GondorBarracks` command set offers.

**Don't use command-slot orders with indices read from a CommandSet file.** They work, they
charge, and they buy the wrong thing: slot 1 of the Lothlorien keep (file entry: build Lorien
warriors) recruited the hero Orophin, and slot 7 of the Gondor barracks (file entry: structure
upgrade) recruited the hero Imrahil. The runtime index is against something else. Prefer the
template-id form of `recruit`.

**A consumed order is not an accepted order.** The `ready` flag clearing only means the hook
appended the message to the stream. Game logic can then discard it — for a malformed argument
list, or an unmet prerequisite — and *nothing reports that*: no error, no diagnostic, and the
order still reaches the replay. **Resources are the oracle.** If a recruit or build does not
drop the player's gold within a second, logic refused it. Two separate bugs hid behind this in
one afternoon: a `recruit` constructor emitting 2 arguments where the engine records 5, and a
unit whose sidebar button was disabled for want of an upgrade.


**The `player` argument does not choose who acts.** Order constructors take one, but the bridge
does not transmit it — the engine attributes an injected order to the local player itself. It
matters only when an order is serialised to a replay. The numbering differs too: a game observed
with `PlayerList` index 3 recorded its orders as player 2.

**Do not read a mid-path position as a failure.** A unit sampled while it is still walking can
sit well off the line to its destination, because it is pathing around terrain — or around a
castle that spawned on top of it. Sample after it has stopped. `check_bridge.py` does.
