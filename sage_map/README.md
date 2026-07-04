# sage_map

A Python library for reading, writing and analysing BFME `.map` files. Can potentially work with
the map files of other SAGE games but might need to be adjusted. The binary format implementation
is not complete.

All the credit for the parsing logic goes to: https://github.com/OpenSAGE/OpenSAGE. I simply
"translated" it to Python and simplified it.

The package has three layers:

- `sage_map.map` + `sage_map.assets` — the binary `.map` reader/writer (dataclasses per asset).
- `sage_map.model` / `sage_map.scripts` / `sage_map.linter` / `sage_map.diff` — a game-aware
  typed overlay: resolves script arguments and object references against game definitions, lints
  maps the way `sage_lint` lints ini files, and renders content diffs of binary maps.
- `sage_map.checks` — the architecture for standalone map checks (findings, rule-runner, terrain
  helpers); rule sets are mod conventions and live with their mod package
  (`sage_edain.map_checks` for Edain).

## Example

```python
from sage_map import parse_map_from_path

# Load a BFME .map file
map = parse_map_from_path('path/to/your/file.map')

# Access map properties
print(map.world_info)
print(map.height_map_data)
print(map.objects_list)
```

## Standalone map checks

`sage_map.checks` validates maps without game data: a rule-runner (`lint_map`) and terrain
helpers, with findings emitted as ordinary `sage_ini` `Diagnostic`s. The rules themselves are mod
conventions — the Edain set (terrain flatness, object counts, resource placement, camera
settings) lives in `sage_edain.map_checks` with a command-line front end:

```
python -m sage_edain.map_checks <path-to-map-file>
```

You can list all available error codes or exclude specific checks using command-line options. For
more details, run:

```
python -m sage_edain.map_checks --help
```

### Using the checks programmatically

```python
from sage_map import parse_map_from_path
from sage_edain.map_checks import lint_map

map = parse_map_from_path('path/to/your/file.map')
errors = lint_map(map)

for error in errors:
    print(f"{error.code}: {error.message}")
```

For game-aware linting (references resolved against the assembled game), see `sage_map.linter`,
exposed through the `sage-lint` CLI.
