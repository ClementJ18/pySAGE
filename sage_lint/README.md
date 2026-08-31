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

# Rename a definition and every reference to it (reports the plan; --apply performs it)
python -m sage_lint rename <dir> <old> <new> [--table objects] [--apply]
```

## Renaming a definition

`rename` moves a definition's name and every reference to it in one pass. References come from
the typed model - fields (including lists, tuples and `KeyedRecord` keys), a `CommandSet`'s
numbered slots, a `ChildObject`'s parent, and the `#define` body a field reaches a name through -
so the rewrite follows the reference graph rather than grepping for a string. Matching is
case-insensitive, the way the engine resolves names.

```sh
python -m sage_lint rename <dir> OldSword NewSword          # report the plan, write nothing
python -m sage_lint rename <dir> OldSword NewSword --apply  # perform it
python -m sage_lint rename --list-tables                    # the table keys --table accepts
```

Nothing is written without `--apply`, so the destructive step is always a second, deliberate
invocation. `--table` is only needed when one bareword names a definition in more than one table;
otherwise it is inferred. Only files under the root are rewritten - a `--base` tree is read-only,
and renaming a definition declared in one is refused.

Three things the report will tell you about:

- **map.ini overlays are included.** Each is a per-map context the global build deliberately
  excludes, so they are planned separately and *are* rewritten.
- **Binary `.map` layouts are reported, never rewritten.** A WorldBuilder layout belongs to the
  map author, so the rename leaves it alone and names the exact placed object, object property or
  script-argument address that will become a dangling reference - the same thing `lint-maps`
  reports as `map-dangling-object` / `map-dangling-reference` afterwards. Fix those in
  WorldBuilder. `--no-maps` skips the scan (it parses every map, which is the slow part of a run).
- **Unaccounted occurrences.** After planning, the whole tree is scanned for the name. A header
  declaring the same name in the same table is folded into the plan automatically - only the
  *winning* declaration of a name is registered in the game, so a shadowed one is invisible to the
  typed pass. Anything else - a field the schema does not model, a same-spelled name in another
  table - is listed for you to judge rather than guessed at, so an incomplete rename is always
  visible instead of silent.

## Configuration & baselines

Project settings live in a `.sagelint` file (with an optional `.sagelint.local` override);
see [`.sagelint.template`](.sagelint.template) for the documented set of knobs. To adopt
the linter on an existing mod without drowning in pre-existing diagnostics, write a baseline
and report only new findings:

```sh
python -m sage_lint lint <dir> --write-baseline   # snapshot current diagnostics
python -m sage_lint lint <dir> --baseline         # report only what's new since
```

The baseline matches diagnostics by file + code + the structured facts identifying the problem
(which object, which field, which referenced symbol) + count. Line numbers, measured values and
the prose message are all excluded, so an unrelated edit above a finding, a partial fix, or a
reworded rule won't resurface accepted diagnostics.

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

## Linting a mod that runs on a patched `game.dat`

A binary patch can teach the engine INI it could not read before - a new field on a block, a new
model-condition token, a bigger `CommandSet`. The typed model describes the **stock** engine, so
without help every one of those reads as a mistake: unknown attributes, unknown enum tokens, a
paging window that "runs off" an array the patched engine has widened.

A `.sagepatch` is that difference, written down. Generate it from the binary the mod actually
ships with and commit it beside `.sagelint`:

```sh
sage-patch sagepatch game.dat -o .sagepatch     # see ../sage_patch
```

A `.sagepatch` sitting next to the config is picked up automatically, so nothing needs
configuring; `sagepatch = "..."` in `.sagelint` points elsewhere, `--engine PATH` overrides both,
and `--no-engine` lints against the stock engine regardless. The patched fields and tokens then
simply exist - they convert, they cross-reference, they rename, they autocomplete - and the
engine-dependent ceilings the rules enforce move with them. A field a patch *retired* (one the
engine still parses and no longer acts on) is reported as `patched-out-field` rather than
vanishing, so it reads as what it is instead of as an unknown attribute. A malformed or
unreadable `.sagepatch` degrades to the stock engine with an `engine-config` diagnostic; it never
stops the run.

## Map linting

`sage_lint` also exposes game-aware `.map` linting, which resolves script arguments and
object references against the assembled game (see [`sage_map`](../sage_map)). Standalone,
game-data-free map checks live in `sage_map.checks`, with mod-specific rule sets in the mod's
own overlay package (`sage_edain.map_checks`, in [pySAGE-edain](https://github.com/ClementJ18/pySAGE-edain)).

## Desktop UI

A PyQt6 front end ships under `sage_lint/plugins/ui` (install the `lint-ui` extra):

```sh
pip install "pysage-tools[lint-ui]"   # from a checkout: pip install -e ".[lint-ui]"
sage-lint-ui                     # or: python -m sage_lint.plugins.ui.app
```
