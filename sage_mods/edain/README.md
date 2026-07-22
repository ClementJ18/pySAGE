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

## Claude Code skill

The `bfme-faction` skill packages the faction graph as an agent-facing tool - read,
critique, and compare Edain factions from within Claude Code:

```sh
python -m sage_mods.edain install-skill
```
