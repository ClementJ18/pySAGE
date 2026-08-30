# sage_ini

A typed, comment-preserving parser for **SAGE-engine** (Battle for Middle-earth)
`.ini` files.

`sage_ini` reads the game's ini data into a tree that round-trips losslessly
(comments included), then layers a typed object model on top: a block becomes an
`IniObject` whose annotated fields convert lazily on access - numbers, enums,
macros (`#define`/`#MULTIPLY( … )`), and cross-references resolved through the
loaded game. It is the library the rest of pySAGE builds on: the parser, the
comment-preserving AST, the typed model, the whole-game loader, the cross-reference
graph (`model/xref.py`), and the `validate` "does it convert?" pass.

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

# Machine-readable output for agents and tool builders: the query commands
# (lint, xref, resolve, brief, diff) all accept --json
python -m sage_ini xref <dir> GondorFighter --json

# Structure-aware 3-way merge: match definitions by name and merge by field, so
# independent edits never collide (git merge driver / conflict-marker resolver)
python -m sage_ini merge <base> <ours> <theirs> [-o out.ini]
python -m sage_ini merge --resolve <conflicted.ini>   # shrink existing conflicts
python -m sage_ini merge --install [--global]         # register as a git merge driver

# Set-merge a conflicted #define reference list: report each side's adds/removes,
# then --write the union (honouring deliberate removals). Needs diff3 markers.
python -m sage_ini macro-merge <conflicted.ini>          # report only (dry run)
python -m sage_ini macro-merge <conflicted.ini> --write  # apply the merge
```

### Merging ini in git

Git merges ini files line by line, so two branches that touch the same long
definition - or merely add objects next to each other - collide spuriously, and a
`#define` reference list collides on the whole line. Two helpers merge ini the way it
actually means:

- `merge` matches definitions by name and merges field by field, so independent edits
  apply silently. Install it as a git merge driver once and every `git merge`/`git
  rebase` routes ini files through it automatically:

  ```sh
  python -m sage_ini merge --install     # adds the 'sage-ini' driver to .git/config
  printf '*.ini merge=sage-ini\n*.inc merge=sage-ini\n' >> .gitattributes
  ```

  No Python? The standalone binary (below) works too: running `sage_ini merge --install`
  from the downloaded exe registers the exe's own absolute path as the driver command, so
  git merges ini structurally with nothing else installed.

- `macro-merge` reads a conflicted `#define NAME a b c ...` list as a 3-way *set* diff
  against the diff3 base - reporting each side's adds/removes, then (with `--write`)
  keeping every addition and honouring every removal, flagging one-sided deletions to
  **VERIFY** so a retired reference is never silently resurrected.

Full how-to - installing the driver (per-repo and `--global`), the recommended
`merge.conflictStyle = zdiff3`, resolving files that already carry conflict markers,
reading the `macro-merge` report, and how the merge decides: **[../docs/merge.md](../docs/merge.md)**.

### For an LLM coding agent

`sage_ini` ships a compact, model-derived primer and a Claude Code skill so an agent can
understand a mod's ini and know where to chase references:

```sh
python -m sage_ini primer                 # lean schema digest (tables + modules + legend)
python -m sage_ini primer expand Object   # one kind's full field schema, on demand
python -m sage_ini install-skill          # install the bundled bfme-ini skill (~/.claude/skills)
```

### Standalone binary (no Python)

```sh
pyinstaller sage_ini/sage-ini.spec
```

This produces `dist/sage_ini` (`dist/sage_ini.exe` on Windows) - one binary serving every
subcommand, the git merge driver included: `merge --install` run from the binary registers
the binary's own absolute path, so structure-aware merging needs nothing else installed.
PyInstaller binaries are not cross-platform, so build once per OS you support.

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

More in **[../docs/cookbook.md](../docs/cookbook.md)**: walking objects by KindOf, resolving
macros, following references, editing-then-reprinting losslessly, and writing your own
checker against the model.

## Data for a patched engine

The model describes the **stock** SAGE engine. A binary patch (see [`sage_patch`](../sage_patch))
can make the engine accept INI it could not read before - a new field on a block, a new
model-condition token, a bigger `CommandSet` - and against the stock model all of that reads as a
mistake. An [`Engine`](engine.py) is that difference as data, loaded from the `.sagepatch` a mod
commits and applied to the model before anything builds:

```python
from sage_ini import load_engine, load_game

game = load_game("data", engine=load_engine("data/.sagepatch")).game
game.specialpowers["MyHeroPower"].ManaCost      # a field only the patched engine has
```

Applying is process-wide - the schema lives on the model classes, which is exactly what makes a
patched field work everywhere without each consumer knowing about engines - so one engine is
active at a time and `Engine.activate()` is the scoped form. `sage-ini --engine <file>` applies
one to any command. Nothing in the path raises on a bad file: it degrades to the stock engine and
says why.

The same file carries a `[[patches]]` list: every binary patch the `game.dat` was built from,
with the parameters it was built with, whether or not it changes any INI. The model never reads
it - it is provenance, not schema - but it is what makes the committed file a build manifest as
well as a schema difference: `engine.patches` says what the binary is, and `sage-patch rebuild`
replays the list onto a clean binary to make it again.

## Public API & stability

The supported surface is what `sage_ini` re-exports at the top level (and lists in its
`__all__`): the loader, the typed `Game` / `IniObject` model, the comment-preserving
`parse` / `print_document`, the `walk` / `Xref` traversal helpers, and the `Diagnostic`
types tool authors build checkers against. Every public module declares its own `__all__`;
anything not exported - and every `_`-prefixed name - is internal and may change without
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
