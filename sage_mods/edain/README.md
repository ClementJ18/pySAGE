# sage_mods.edain

The **Edain overlay** for pySAGE: a collection of tools built on the engine-generic
projects in this repo and tuned for the [Edain mod](https://edain.wikia.com). The other
packages ([`sage_ini`](../sage_ini), [`sage_map`](../sage_map),
[`sage_utils`](../sage_utils), [`sage_ui`](../sage_ui)) stay engine-generic and know
nothing about Edain; this package is where the mod's names, paths, layouts, and
conventions live, wired into those primitives through their extension hooks.

So the split is deliberate: resolution and rendering live upstream, and `sage_mods.edain`
supplies the Edain-specific knowledge and assembles the pieces into task-shaped tools.

## Faction ownership graph

The flagship tool turns a loaded game into an explicit **faction ownership graph** - the
link between a faction and everything a player of it can see. An Edain faction is a
`PlayerTemplate` with `PlayableSide = Yes`; from it hang a spellbook, the starting plot
flags that unpack a base (citadel + foundations) or a single structure, the buildings
constructed on those foundations, and the units / heroes / upgrades those buildings
produce. It walks the loaded `Game` (and the mod's binary base layouts, via `sage_map`)
into one `FactionGraph`, drawing resolution from `sage_ini.model.state` and
`sage_utils.views`.

```sh
# List the playable factions in a mod
python -m sage_mods.edain factions <dir>

# The faction's ownership graph (add --json for the machine-readable shape)
python -m sage_mods.edain explore <dir> <faction>

# The same graph as a Markdown digest with stat tables (the agent-facing view)
python -m sage_mods.edain report <dir> <faction>

# Faction-level changelog between two versions of the mod
python -m sage_mods.edain diff <old> <new> [faction]

# Open a small web UI to traverse the graph
python -m sage_mods.edain serve <dir> <faction>

# sage_replay's corpus aggregation with Edain's knowledge (sage_mods/edain/replay.py)
# injected: economy researches + library arts in its Upgrades pick tables, the
# CP-upgrade CPObject depth-numbered per purchase (CPObject1, CPObject2, ...),
# Dwarves split into their realm (Erebor / Ered Luin / Iron Hills) by the opening
# clan-upgrade purchase, and the Imladris Loremaster fielded as its element-specific
# horde - read off the toggle cast (only for an Imladris caster; the same powers stay
# raw summons for Angmar / Rohan / Lothlorien) with the elementless placeholder dropped
python -m sage_mods.edain replay-aggregate <replay|dir>... --game <install>
```

`<dir>` is the mod's ini root (e.g. `_mod/data/ini`; point it at the mod folder so the
localization table resolves too). Pass `--bases` (the mod's `bases/` folder) to decompose
castle/camp layouts into their citadel + foundations + prebuilt structures.

## Object asset walking

`sage_mods.edain.assets` walks the on-disk art a set of ini objects reference, sized against
an art tree. `object_assets(objects, art)` gathers, for each object's own subtree, every
`.w3d` it shows (one per model-condition state, animation clips, the skeletons a skinned
mesh's HLOD pulls in) and every texture it names - in a typed field (a draw's `Texture`, a
particle system's `ParticleName`, a mapped image's `Texture`) or inside those `.w3d` files -
resolving each to its file size in an `ArtIndex` (loose folders and/or `.big` archives,
later sources overriding earlier ones). Each asset is counted once across the objects
passed, and `write_csv` emits one row each
(`asset,kind,size_bytes,ref_count,references,source`).

It deliberately does **not** follow references from one object to another - a caller controls
the scope by choosing which objects to pass. File size stands in for RAM weight as a
first-order estimate: a `.dds` stays block-compressed in memory the way it sits on disk, a
`.w3d`'s geometry loads roughly 1:1.

```python
from pathlib import Path
from sage_ini.loader import load_game
from sage_mods.edain.assets import ArtIndex, object_assets, write_csv

game = load_game(Path("_mod")).game
art = ArtIndex.build([Path("_mod/art")])  # or a base .big then the mod's, in priority order
records = object_assets([game.objects["GondorTower"]], art)
with open("tower_assets.csv", "w", newline="") as fh:
    write_csv(records, fh)
```

## Map checks

Edain's map-convention rule set (terrain flatness, object counts, resource placement,
camera settings) lives in `sage_mods.edain.map_checks`, layering the mod's conventions over
`sage_map.checks`:

```sh
python -m sage_mods.edain.map_checks <path-to-map-file>
python -m sage_mods.edain.map_checks --help     # list codes / exclude specific checks
```

## Patch notes

`sage_mods.edain.patch_notes` turns the release spreadsheet's CSV export into the two BBcode
forum posts a release needs - English and German - grouped by faction, nested by each note's
leading dashes, and filtered by the beta flag or the date a batch was added.
[`patch_notes/ui`](patch_notes/ui) is a small desktop window over it (`sage-edain-notes`, the
`edain-ui` extra); a script can call the transform directly:

```py
from sage_mods.edain.patch_notes import read_notes, render_notes, write_notes

result = render_notes(read_notes("Edain 4.8.csv"), beta=False)
write_notes(result, ".", "Edain 4.8")
```

## Horde maker

`sage_mods.edain.horde_maker` is a horde's formation - the `RankInfo` block a `HordeContain`
carries - as a flat list of slots at game coordinates, rendered to that block or read back
out of one. [`horde_maker/ui`](horde_maker/ui) is a small desktop window over it
(`sage-edain-horde`, the `edain-ui` extra): click the soldiers onto a grid and the block is
written for you, ranks numbered and each soldier tied to its leader in the rank ahead; paste
an existing block in to see the shape it describes.

```py
from sage_mods.edain.horde_maker import Slot, parse_formation, render_formation

block = render_formation(
    [Slot("GondorSoldier", x=10.0, y=10.0), Slot("GondorSoldier", 10.0, -10.0)],
    {"GondorSoldier": 8.0},
)
slots = parse_formation(block)
```

X is depth, growing towards the front of the formation; Y is lateral, growing to the left of
the centre line. Whether a formation's soldiers overlap depends on how wide each unit is, which
the ini never says - so the diameters they were drawn at ride along in a leading
`; HordeMaker DotSizes` comment (`parse_sizes` reads it back), and the window draws each unit
at its real size.

## Worldbuilder launcher

`sage_mods.edain.worldbuilder` starts Worldbuilder against the mod's **loose** files, so objects
can be added and seen in the editor without building a `.big`. Built as an exe
(`sage-edain-worldbuilder.spec`) it is meant to sit in the `Edain-Mod` folder, one level above
`_mod`.

```
python -m sage_mods.edain.worldbuilder --subtree data/ini/object/civilian
```

It finds the RotWK install through [`sage_utils.installs`](../../sage_utils/installs.py) (the
registry, not a hardcoded path), installs `sage_patch`'s `worldbuilder-mod` into
`Worldbuilder.exe` if it is missing - keeping the stock binary as `Worldbuilder_stock.exe` - and
then launches the editor.

Three things it does that a bare `-mod` gets wrong, all derived in
[`worldbuilder-mod.md`](../../sage_patch/docs/worldbuilder-mod.md):

- **A map goes before `-mod`.** Worldbuilder is an MFC app; its `CCommandLineInfo` claims the
  first non-flag argument as a document to open, so a bare mod path dies with
  `Access to … was denied` before the editor starts.
- **Only a subtree is served.** `-mod` pointed at a full Edain tree kills the editor partway
  through startup; pointed at the subtree being edited it is stable. `--subtree` is repeatable,
  and the served view is built from junctions, so edits still land in the real mod files.
- **The path stays short.** The patch ignores a mod path of 128 characters or more, so the
  staged view lives beside the mod rather than under the temp directory.

`--full` serves the whole mod anyway, `--no-patch` leaves the binary alone, and `--dry-run`
prints the command instead of running it.

## Skirmish bot

`sage_mods.edain.bot` plays a live skirmish through [`sage_live`](../../sage_live): it lays
an economy, widens what it can recruit, buys the upgrades its buildings actually sell, and
takes the map settlement by settlement. It needs the `live-bridge` patch and an elevated
shell, like everything else that issues orders.

```sh
python -m sage_mods.edain.bot --game <install>            # play
python -m sage_mods.edain.bot --game <install> --dry-run   # decide and print, send nothing
```

It is Edain-specific in the same way the rest of this package is - the build orders under
`bot/factions/` name Edain templates - but nothing below `decide` is: classification comes from
`KindOf`, the recruitable set from each building's live `CommandSet`, and the army mix from
the faction's own `ArmyDefinition`. The package docstring is the design record, and
`tuning.py` is the first place to look when a run goes wrong: every threshold there carries
the measurement that put it at that number.

## Claude Code skill

The `bfme-faction` skill packages the faction graph as an agent-facing tool - read,
critique, and compare Edain factions from within Claude Code:

```sh
python -m sage_mods.edain install-skill
```
