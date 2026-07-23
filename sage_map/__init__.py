"""Reader, writer and game-aware typed model for SAGE WorldBuilder `.map` files.

`sage_map.map` (with `sage_map.assets`) parses a binary `.map` into dataclasses and writes it
back. On top of that the overlay modules attach game meaning: the parsed script arguments and
object references are only weakly typed - an argument knows it is a string, not that the string
must name a defined Object, Science or map-local team. `sage_map.model` / `sage_map.scripts` map
each value to the scope it must resolve against (a definition in the assembled `Game`, a symbol
the map itself defines, or a closed enum) - so a map can be linted the way `sage_lint` lints ini
files.

The overlay's v1 covers script-argument and object references only; object-property typing and
the `content_type` action table are deferred. See docs/sage_map_plan.md.

`sage_map.diff` adds a human-readable content diff of two maps (or of the map files a git commit
touches), reporting moved objects, script edits and terrain summaries where git can only say
"binary files differ". `sage_map.checks` is the architecture for standalone (no game data) map
checks - findings, rule-runner, terrain helpers; the Edain rule set lives in
`sage_mods.edain.map_checks`.
"""

from sage_map.diff import (
    MapDiff,
    MapFileChange,
    MapFileDiff,
    commit_map_changes,
    diff_commit_maps,
    diff_map_files,
    diff_maps,
    diff_range_maps,
    format_map_diff,
    format_map_file_diffs,
    format_map_file_diffs_md,
    range_map_changes,
    resolve_range,
)
from sage_map.linter import lint_map, lint_map_file, lint_maps
from sage_map.map import (
    Map,
    parse_map,
    parse_map_from_path,
    write_map,
    write_map_to_path,
)
from sage_map.model import (
    MapModel,
    MapSymbols,
    ScriptArgRef,
    build_symbols,
    iter_script_arguments,
)
from sage_map.scb import (
    ScriptLibrary,
    extract_scripts,
    inject_scripts,
    parse_scb,
    parse_scb_from_path,
    write_scb,
    write_scb_to_path,
)
from sage_map.scripts import (
    ARG_SPECS,
    ArgSpec,
    ResolvedArg,
    Scope,
    arg_spec,
    typed_value,
)

__all__ = [
    "ARG_SPECS",
    "ArgSpec",
    "Map",
    "MapDiff",
    "MapFileChange",
    "MapFileDiff",
    "MapModel",
    "MapSymbols",
    "ResolvedArg",
    "Scope",
    "ScriptArgRef",
    "ScriptLibrary",
    "arg_spec",
    "build_symbols",
    "commit_map_changes",
    "diff_commit_maps",
    "diff_map_files",
    "diff_maps",
    "diff_range_maps",
    "extract_scripts",
    "format_map_diff",
    "format_map_file_diffs",
    "format_map_file_diffs_md",
    "inject_scripts",
    "range_map_changes",
    "resolve_range",
    "iter_script_arguments",
    "lint_map",
    "lint_map_file",
    "lint_maps",
    "parse_map",
    "parse_map_from_path",
    "parse_scb",
    "parse_scb_from_path",
    "typed_value",
    "write_map",
    "write_map_to_path",
    "write_scb",
    "write_scb_to_path",
]
