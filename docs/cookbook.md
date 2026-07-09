# sage_ini cookbook

Task-oriented recipes for building tools on the `sage_ini` library. Every snippet here is
self-contained and runs against the public API (see [Public API](#public-api)); the surface
is typed (`py.typed` ships with the package), so field access autocompletes in an IDE.

For a one-paragraph orientation see the README; this document is the how-to.

## Contents

- [Public API](#public-api)
- [Load a game and read fields](#load-a-game-and-read-fields)
- [Walk all objects of a KindOf](#walk-all-objects-of-a-kindof)
- [Resolve a macro](#resolve-a-macro)
- [Follow BuildVariations (and other references)](#follow-buildvariations-and-other-references)
- [Use the cross-reference graph](#use-the-cross-reference-graph)
- [Edit, then reprint losslessly](#edit-then-reprint-losslessly)
- [Write your own checker](#write-your-own-checker)
- [Parse a single file (no whole-game)](#parse-a-single-file-no-whole-game)

## Public API

These names are re-exported from the top-level package and are the supported surface
(`from sage_ini import …`). Each module also declares `__all__`; anything not listed there,
and every `_`-prefixed name, is internal.

| Name | What it is |
| --- | --- |
| `load_game`, `load_map`, `map_files`, `LoadedGame` | assemble a folder of ini into one `Game` |
| `Game` | the typed container: `game.objects`, `game.weapons`, … plus `lookup`, `get_macro`, `validate` |
| `IniObject` | base of every typed definition; annotated fields convert lazily on access |
| `Xref` | the forward/reverse cross-reference graph of a loaded `Game` |
| `parse`, `parse_file`, `ParseResult` | text/file → comment-preserving AST + diagnostics |
| `print_document` | AST → canonical text (round-trips: `parse(print_document(doc)) == doc`) |
| `IniDocument`, `Node` (and `Block`, `Attribute`, … from `sage_ini.parser.ast`) | AST node types |
| `walk_objects`, `walk_blocks`, `walk_nodes` | depth-first traversal of the model / the AST |
| `Diagnostic`, `Diagnostics`, `Severity`, `Span` | the structured problem-report types |

The game-schema model classes (`Object`, `Weapon`, the behavior modules, …) live in
`sage_ini.model.ini_objects`, `sage_ini.model.behaviors`, `sage_ini.model.data_blocks`, … and
are reached by name through `get_class` / `REGISTRY` or imported directly. They are public
but grow additively (new fields are added as the schema is filled in).

## Load a game and read fields

```python
from pathlib import Path
from sage_ini import load_game

game = load_game(Path("data")).game        # assemble every ini under data/ into one Game
fighter = game.objects["GondorFighter"]
print(fighter.BuildCost)                     # annotated fields convert on access
```

`load_game` returns a `LoadedGame` (`.game` and `.diagnostics`). Pass `bases=` to layer an
unmodified base game beneath a mod so the mod's references resolve.

## Walk all objects of a KindOf

`walk_objects` yields every typed object (descending into nested modules); `has_kindof`
checks the flag up the template-inheritance chain, expanding `#define` macros.

```python
from sage_ini import walk_objects
from sage_ini.model.state import has_kindof

infantry = [obj.name for obj in walk_objects(game) if has_kindof(obj, "INFANTRY")]
```

Filter by model class with the second argument - e.g. only top-level objects:

```python
from sage_ini import walk_objects
from sage_ini.model.ini_objects import Object

for obj in walk_objects(game, Object):
    ...
```

## Resolve a macro

`#define`s are textual. `game.get_macro` resolves a name to its value and passes a
non-macro value through unchanged (matching the engine's loose, case-insensitive lookup).

```python
game.get_macro("HERO_HEALTH")   # -> "4000"
game.get_macro("4000")          # -> "4000"  (not a macro: returned as-is)
```

## Follow BuildVariations (and other references)

A reference-typed field resolves to the registered object(s) on access; an unresolved name
passes through as a raw string. `BuildVariations` is a list of object references:

```python
shell = game.objects["GondorBarracks"]
for variation in shell.BuildVariations:
    name = getattr(variation, "name", variation)  # resolved IniObject, else the raw name
    print(name)
```

The same pattern works for any reference field (`Upgrade`, `WeaponSet` weapons, an OCL's
created objects, …): a resolved field hands back the target object, so you can keep walking.

## Use the cross-reference graph

`Xref` resolves every reference once and records both directions.

```python
from sage_ini import Xref

xref = Xref(game)
fighter = game.objects["GondorFighter"]
print({o.name for o in xref.references(fighter)})     # what it points at
print({o.name for o in xref.referenced_by(fighter)})  # what points at it
print(xref.is_referenced(fighter))                    # used anywhere?
```

## Edit, then reprint losslessly

Parse to the comment-preserving AST, mutate nodes, and print back. The round-trip contract
is `parse(print_document(doc))` equals `doc` (comments preserved; spans and whitespace are
not compared), so an edit touches only what you change.

```python
from sage_ini import parse, print_document
from sage_ini.parser.ast import Attribute, Block

doc = parse(text, file="units.ini").document
for block in doc.children:
    if isinstance(block, Block) and block.label == "GondorFighter":
        for i, child in enumerate(block.children):
            if isinstance(child, Attribute) and child.key == "BuildCost":
                block.children[i] = Attribute(key="BuildCost", value="250", span=child.span)

new_text = print_document(doc)   # canonical formatting, BuildCost now 250, rest untouched
```

(The `sage_lint format` command is this round-trip applied wholesale.)

## Write your own checker

Build checks straight against the model instead of shelling out to the linter CLI:
`walk_objects` to traverse, each object's `.fields` (raw values) or typed attributes to
inspect, and `Diagnostic` / `Diagnostics` / `Span` to report - the same types the linter and
its editor integration consume.

```python
from sage_ini import Diagnostics, Severity, walk_objects
from sage_ini.model.ini_objects import Object

def find_free_units(game) -> Diagnostics:
    """Flag every Object whose BuildCost is written as 0."""
    diagnostics = Diagnostics()
    for obj in walk_objects(game, Object):
        if obj.fields.get("BuildCost") == "0":
            diagnostics.add(
                "free-unit",
                f"{obj.name} has BuildCost 0",
                obj.span,                      # every node carries a Span (file:line)
                Severity.WARNING,
            )
    return diagnostics

for diag in find_free_units(game):
    print(diag)            # "units.ini:12: warning: … [free-unit]"
```

A `Diagnostic` carries `code`, `message`, `span`, `severity` and an `extra` dict of
structured facts; `Diagnostics` is an iterable collection with `.add(...)`. Combine with
`Xref` to write reachability checks ("nothing references this upgrade"), or with `has_kindof`
to scope a rule to a unit category.

## Parse a single file (no whole-game)

When you only need the syntax tree (formatting, a quick scan), skip assembly:

```python
from sage_ini import parse_file

result = parse_file("FXList.ini")     # ParseResult(document, diagnostics)
for diag in result.diagnostics:        # parser-level problems (unclosed block, …)
    print(diag)
```

Cross-references can't resolve without the rest of the game, so for reference-aware checks
use `load_game` (whole folder) and the model instead.
