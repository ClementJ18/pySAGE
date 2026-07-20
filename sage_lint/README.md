# sage_lint

A formatter and linter for SAGE ini game data, built on [`sage_ini`](../sage_ini).

It canonically reprints files (preserving comments and intentional blank lines) and
assembles a whole game to report problems - the parse/load/conversion facts from
`sage_ini` plus judgment rules: repeated fields, unknown or dangling references,
out-of-range values, duplicate definitions, undefined macros, unused definitions, and
more. `analysis.py` layers meta-analysis on top (per-faction stats, cost curves,
mod-vs-base diffs).

## Command line

```sh
# Reformat ini files to the canonical style (--check to dry-run)
python -m sage_lint format <paths...>

# Assemble a game and report problems (facts + judgment rules)
python -m sage_lint lint <dir> [--base <base-game>] [--ignore CODE] [--fix]

# Player-facing changelog between two versions (display names, resolved values)
python -m sage_lint diff --player <old> <new>

# Find copy-pasted chunks (blocks or runs of lines) worth moving into a shared #include
python -m sage_lint duplicates <dir> [--min-lines N] [-v]
```

## Configuration & baselines

Project settings live in a `.sagelint` file (with an optional `.sagelint.local` override);
see [`.sagelint.template`](.sagelint.template) for the documented set of knobs. To adopt
the linter on an existing mod without drowning in pre-existing diagnostics, write a baseline
and report only new findings:

```sh
python -m sage_lint lint <dir> --write-baseline   # snapshot current diagnostics
python -m sage_lint lint <dir> --baseline         # report only what's new since
```

The baseline matches diagnostics by file + code + message + count (line-insensitive), so
unrelated edits above a finding don't resurface it.

## Linting without a base game on disk

`lint` normally needs the base game loaded (`--base` / config `base`) so a mod's references
into it resolve, which means having the base tree on disk and paying to load it every run.
`sage_lint manifest` indexes a loaded base game once into a compact **symbol manifest** - a
JSON file (optionally gzipped) capturing the names, tables, module tags and handful of raw
field values the lint rules actually consult:

```sh
python -m sage_lint manifest --game <base-game> -o sage-base-manifest.json.gz
```

Point `base_manifest` (in `.sagelint`, since a manifest is small and committable, unlike a
`base` path) or `--base-manifest` at it, and a mod lints against those base symbols with no
base tree required. A real `base` always wins when both are configured - real data is
strictly more complete. **Limitation:** a mod that `#include`s base-game files still needs a
real `base`; a manifest carries symbols, not include text.

## Map linting

`sage_lint` also exposes game-aware `.map` linting, which resolves script arguments and
object references against the assembled game (see [`sage_map`](../sage_map)). Standalone,
game-data-free map checks live in `sage_map.checks`, with mod-specific rule sets under the
mod package (`sage_mods.edain.map_checks`).

## Desktop UI

A PyQt6 front end ships under `sage_lint/plugins/ui` (install the `lint-ui` extra):

```sh
pip install "py-sage[lint-ui]"   # from a checkout: pip install -e ".[lint-ui]"
sage-lint-ui                     # or: python -m sage_lint.plugins.ui.app
```
