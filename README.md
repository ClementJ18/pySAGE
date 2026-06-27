# sage_ini

A typed, comment-preserving parser and linter for **SAGE-engine** (Battle for
Middle-earth) `.ini` files.

`sage_ini` reads the game's ini data into a tree that round-trips losslessly
(comments included), then layers a typed object model on top: a block becomes an
`IniObject` whose annotated fields convert lazily on access — numbers, enums,
macros (`#define`/`#MULTIPLY( … )`), and cross-references resolved through the
loaded game. `sage_lint` builds on it to format files and report problems.

## Packages

- **`sage_ini`** — the library: parser, comment-preserving AST, typed model,
  whole-game loader, the cross-reference graph (`model/xref.py`), and the
  `validate` "does it convert?" pass.
- **`sage_lint`** — the formatter and linter: canonical reprint, and judgment
  rules (repeated fields, unknown/dangling references, out-of-range values,
  duplicate definitions, undefined macros, …) plus meta-analysis
  (`analysis.py`: per-faction stats, cost curves, mod-vs-base diffs).

## Install

```sh
pip install -e .            # core library + linter (Python ≥ 3.13)
pip install -e ".[wiki,ui]" # optional peripheral tools
```

## Command line

```sh
# Parse-rate scoreboard over a folder of game data
python -m sage_ini stats <dir>

# Parse + load + conversion facts for files or a folder
python -m sage_ini lint <paths...>

# What a definition references, and what references it
python -m sage_ini xref <dir> GondorFighter

# Where a name or macro is defined (file:line); a file's #include edges
python -m sage_ini resolve <dir> GondorFighter
python -m sage_ini includes <dir> <file>

# One-shot briefing of a single file (defs, references, includes, macros)
python -m sage_ini brief <dir> <file> [name]

# Reformat ini files to the canonical style (--check to dry-run)
python -m sage_lint format <paths...>

# Assemble a game and report problems (facts + judgment rules)
python -m sage_lint lint <dir> [--base <base-game>] [--ignore CODE] [--fix]
```

### For an LLM coding agent

`sage_ini` ships a compact, model-derived primer and a Claude Code skill so an agent can
understand a mod's ini and know where to chase references:

```sh
python -m sage_ini primer                 # lean schema digest (tables + modules + legend)
python -m sage_ini primer expand Object   # one kind's full field schema, on demand
python -m sage_ini install-skill          # install the bundled bfme-ini skill (~/.claude/skills)
```

## Library use

```python
from pathlib import Path
from sage_ini.loader import load_game
from sage_ini.model.xref import Xref

game = load_game(Path("data")).game
fighter = game.objects["GondorFighter"]
print(fighter.BuildCost)                       # fields convert on access

xref = Xref(game)
print({o.name for o in xref.referenced_by(fighter)})  # e.g. GondorFighterHorde
```

More in **[docs/cookbook.md](docs/cookbook.md)**: walking objects by KindOf, resolving
macros, following references, editing-then-reprinting losslessly, and writing your own
checker against the model.

## Public API & stability

The supported surface is what `sage_ini` re-exports at the top level (and lists in its
`__all__`): the loader, the typed `Game` / `IniObject` model, the comment-preserving
`parse` / `print_document`, the `walk` / `Xref` traversal helpers, and the `Diagnostic`
types tool authors build checkers against. Every public module declares its own `__all__`;
anything not exported — and every `_`-prefixed name — is internal and may change without
notice.

```python
from sage_ini import (
    load_game, Game, IniObject, Xref,
    parse, parse_file, print_document,
    walk_objects, Diagnostic, Diagnostics, Severity, Span,
)
```

The package ships a `py.typed` marker, so the model's field typing surfaces in a consumer's
type checker and IDE. Semantic versioning applies **to that public surface**: within a major
version the exported names and their documented behaviour stay backward-compatible (the
game-schema model classes only grow new fields, which is additive). It is pre-1.0, so the
surface may still shift between minor versions until it settles.

## Tests

```sh
pytest            # fast, data-free core suite
pytest --full     # + corpus acceptance gates and peripheral-package suites
```
