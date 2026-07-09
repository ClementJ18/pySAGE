# sage_edain

The **Edain overlay** for pySAGE: a collection of tools built on the engine-generic
projects in this repo and tuned for the [Edain mod](https://edain.wikia.com). The other
packages ([`sage_ini`](../sage_ini), [`sage_map`](../sage_map),
[`sage_utils`](../sage_utils), [`sage_ui`](../sage_ui)) stay engine-generic and know
nothing about Edain; this package is where the mod's names, paths, layouts, and
conventions live, wired into those primitives through their extension hooks.

So the split is deliberate: resolution and rendering live upstream, and `sage_edain`
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
python -m sage_edain factions <dir>

# The faction's ownership graph (add --json for the machine-readable shape)
python -m sage_edain explore <dir> <faction>

# The same graph as a Markdown digest with stat tables (the agent-facing view)
python -m sage_edain report <dir> <faction>

# Faction-level changelog between two versions of the mod
python -m sage_edain diff <old> <new> [faction]

# Open a small web UI to traverse the graph
python -m sage_edain serve <dir> <faction>
```

`<dir>` is the mod's ini root (e.g. `_mod/data/ini`; point it at the mod folder so the
localization table resolves too). Pass `--bases` (the mod's `bases/` folder) to decompose
castle/camp layouts into their citadel + foundations + prebuilt structures (needs the
`[edain]` extra). `--base` layers a base-game ini source for completeness, like
[`sage_lint`](../sage_lint).

## Map checks

Edain's map-convention rule set (terrain flatness, object counts, resource placement,
camera settings) lives in `sage_edain.map_checks`, layering the mod's conventions over
`sage_map.checks`:

```sh
python -m sage_edain.map_checks <path-to-map-file>
python -m sage_edain.map_checks --help     # list codes / exclude specific checks
```

## Claude Code skill

The `bfme-faction` skill packages the faction graph as an agent-facing tool - read,
critique, and compare Edain factions from within Claude Code:

```sh
python -m sage_edain install-skill
```
