"""Generic, lossless parser for SAGE-engine (BFME) ini files.

See CONVENTIONS.md (repo root) for the coding rules and `docs/cookbook.md` for
task-oriented recipes against the public API.

## Public API & stability

The names re-exported here (and listed in `__all__`) are the supported surface: the
loader, the typed `Game`/`IniObject` model, the comment-preserving parser and printer, the
`walk`/`Xref` traversal helpers, and the `Diagnostic` types a tool author builds checkers
against. Each public module also declares its own `__all__`; anything not exported — and
every `_`-prefixed name — is internal and may change without notice.

`sage_ini` ships a `py.typed` marker, so the field typing on the model surfaces in a
consumer's type checker and IDE. The package follows semantic versioning **on that public
surface**: within a major version, the exported names and their documented behaviour stay
backward-compatible (the game-schema model classes grow new fields, which is additive). The
library is pre-1.0, so the surface may still shift between minor versions until it settles;
`__version__` tracks that.
"""

from sage_ini.loader import LoadedGame, load_game, load_map, map_files
from sage_ini.model.game import Game, Redefinition
from sage_ini.model.objects import IniObject, get_class
from sage_ini.model.xref import Xref
from sage_ini.parser.ast import IniDocument, Node
from sage_ini.parser.blockparser import ParseResult, parse, parse_file
from sage_ini.parser.diagnostics import Diagnostic, Diagnostics, Severity
from sage_ini.parser.location import Span
from sage_ini.parser.printer import print_document
from sage_ini.walk import walk_blocks, walk_nodes, walk_objects

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # whole-game assembly
    "load_game",
    "load_map",
    "map_files",
    "LoadedGame",
    # typed model
    "Game",
    "IniObject",
    "Redefinition",
    "get_class",
    "Xref",
    # parse / reprint
    "parse",
    "parse_file",
    "ParseResult",
    "print_document",
    "IniDocument",
    "Node",
    # traversal
    "walk_objects",
    "walk_blocks",
    "walk_nodes",
    # diagnostics
    "Diagnostic",
    "Diagnostics",
    "Severity",
    "Span",
]
