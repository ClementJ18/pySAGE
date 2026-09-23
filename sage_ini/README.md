# sage_ini

A typed, comment-preserving parser for **SAGE-engine** (Battle for Middle-earth) `.ini` files, and
the library the rest of pySAGE builds on.

It reads game ini data into a tree that round-trips losslessly, comments included, then layers a
typed model on top: a block becomes an `IniObject` whose annotated fields convert lazily on access -
numbers, enums, macros (`#define`, `#MULTIPLY( ... )`), and cross-references resolved through the
loaded game. It also provides the whole-game loader, the cross-reference graph (`model/xref.py`) and
the `validate` "does it convert?" pass.

## Command line

```sh
python -m sage_ini stats <dir>                   # parse-rate scoreboard over a folder
python -m sage_ini lint <paths...>               # parse, load and conversion facts
python -m sage_ini xref <dir> GondorFighter      # what it references, and what references it
python -m sage_ini resolve <dir> GondorFighter   # where a name or macro is defined
python -m sage_ini includes <dir> <file>         # a file's #include edges
python -m sage_ini brief <dir> <file> [name]     # one-shot briefing of a single file
python -m sage_ini merge <base> <ours> <theirs> [-o out.ini]   # structure-aware 3-way merge
python -m sage_ini macro-merge <conflicted.ini> [--write]      # set-merge a #define list
```

`lint`, `xref`, `resolve`, `brief` and `diff` accept `--json`. `--engine <file>` applies a
`.sagepatch` to any command (see below).

### Merging ini in git

Git merges ini line by line, so edits to the same long definition, or objects added side by side,
collide. `merge` matches definitions by name and merges field by field; install it once as a git
merge driver:

```sh
python -m sage_ini merge --install     # adds the 'sage-ini' driver to .git/config (--global too)
printf '*.ini merge=sage-ini\n*.inc merge=sage-ini\n' >> .gitattributes
python -m sage_ini merge --resolve <conflicted.ini>   # shrink conflicts already in a file
```

`macro-merge` treats a conflicted `#define NAME a b c ...` list as a 3-way set difference (it needs
diff3 markers): it reports each side's additions and removals and, with `--write`, keeps every
addition and honours every removal, flagging one-sided deletions to **VERIFY**. The full how-to is
[../docs/merge.md](../docs/merge.md).

### For an LLM coding agent

```sh
python -m sage_ini primer                 # compact schema digest (tables, modules, legend)
python -m sage_ini primer expand Object   # one kind's full field schema
python -m sage_ini install-skill          # install the bundled bfme-ini Claude Code skill
```

### Standalone binary (no Python)

`pyinstaller sage_ini/sage-ini.spec` builds `dist/sage_ini` (one binary per OS), serving every
subcommand. `merge --install` run from it registers the binary itself as the merge driver.

## Library use

```python
from sage_ini import Xref, load_game

game = load_game("data").game
fighter = game.objects["GondorFighter"]
print(fighter.BuildCost)                              # fields convert on access
print({o.name for o in Xref(game).referenced_by(fighter)})  # e.g. GondorFighterHorde
```

More recipes - walking objects by KindOf, resolving macros, following references, editing and
reprinting losslessly, writing a checker - are in [../docs/cookbook.md](../docs/cookbook.md).

## Data for a patched engine

The model describes the **stock** engine. A binary patch ([`sage_patch`](../sage_patch)) can make
the engine accept INI it could not read before - a new field, a new token, a bigger `CommandSet` -
which the stock model would report as mistakes. An [`Engine`](engine.py) is that difference as data,
loaded from the `.sagepatch` a mod commits:

```python
from sage_ini import load_engine, load_game

game = load_game("data", engine=load_engine("data/.sagepatch")).game
game.specialpowers["MyHeroPower"].ManaCost      # a field only the patched engine has
```

Applying is process-wide, because the schema lives on the model classes; one engine is active at a
time, and `Engine.activate()` is the scoped form. A bad file degrades to the stock engine with a
warning rather than raising. The file also lists the patches the `game.dat` was built from
(`engine.patches`), which `sage-patch rebuild` can replay.

## Public API and stability

The supported surface is what `sage_ini` re-exports (its `__all__`): the loader, the `Game` and
`IniObject` model, `parse` / `print_document`, the `walk` and `Xref` helpers, and the `Diagnostic`
types. Anything else, and every `_`-prefixed name, may change without notice. The package ships
`py.typed`. Semantic versioning applies to that surface; before 1.0 it may still shift between minor
versions.

```python
from sage_ini import (
    load_game, Game, IniObject, Xref,
    parse, parse_file, print_document,
    walk_objects, Diagnostic, Diagnostics, Severity, Span,
)
```
