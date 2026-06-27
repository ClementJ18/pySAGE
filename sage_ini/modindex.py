"""Per-mod resolution index (Tier 2 of the LLM primer): given a folder of ini files, answer
the location questions an agent reading one file needs — where a referenced name or macro is
*defined*, and how files include one another (a file's resolution scope).

The schema digest (`sage_ini.primer`) is mod-independent and says which table a reference
*kind* resolves into; this index is mod-specific and says where a particular name actually
lives. It is built once from a loaded `Game` (definitions and macros already carry source
spans) plus a lightweight include-graph scan, then queried for one answer at a time rather than
dumped wholesale.
"""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from sage_ini.loader import load_game
from sage_ini.parser.blockparser import include_target, resolve_include
from sage_ini.parser.io import iter_ini_files
from sage_ini.parser.lexer import tokenize_path
from sage_ini.parser.location import Span
from sage_ini.stats import ini_root

__all__ = ["Definition", "MacroSite", "ModIndex"]


@dataclass(frozen=True, slots=True)
class Definition:
    name: str  # the definition's canonical name (may differ in case from the query)
    table: str  # the Game table it registers into
    span: Span  # where it opens


@dataclass(frozen=True, slots=True)
class MacroSite:
    name: str  # canonical `#define` spelling
    value: str
    span: Span | None  # definition site, or None if only an expansion path recorded it


def _include_graph(root: Path) -> dict[Path, list[Path]]:
    """`source-file -> [included files]` for every ini under `root`, resolved the way the
    engine overlays includes. Built from a raw token scan (not the spliced document) so each
    physical edge is recorded once at its real source."""
    layers = (ini_root(root),)
    graph: dict[Path, list[Path]] = {}
    for path in iter_ini_files(root):
        source = path.resolve()
        targets: list[Path] = []
        for line in tokenize_path(source):
            target = include_target(line.content)
            if target is None:
                continue
            resolved = resolve_include(target, source, layers)
            if resolved is not None:
                targets.append(resolved)
        if targets:
            graph[source] = targets
    return graph


class ModIndex:
    """Resolution queries over a loaded mod folder."""

    def __init__(
        self,
        root: str | Path,
        overlays: tuple[str | Path, ...] = (),
        bases: tuple[str | Path, ...] = (),
    ) -> None:
        self.root = Path(root)
        loaded = load_game(root, overlays=overlays, bases=bases)
        self.game = loaded.game
        self.diagnostics = loaded.diagnostics
        self._includes = _include_graph(self.root)
        self._included_by: dict[Path, list[Path]] = defaultdict(list)
        for source, targets in self._includes.items():
            for target in targets:
                self._included_by[target].append(source)

    def resolve(self, name: str) -> list[Definition]:
        """Every table in which `name` is defined (usually one), with its source span. Matches
        case-insensitively, the way the engine interns names."""
        found: list[Definition] = []
        for table in self.game.tables:
            obj, canonical = self.game.lookup(table, name)
            if obj is not None and obj.span is not None:
                found.append(Definition(str(canonical), table, obj.span))
        return found

    def macro(self, name: str) -> MacroSite | None:
        """The `#define` named `name` (case-insensitive), with its definition site, or None."""
        macros = self.game.macros
        canonical = name if name in macros else None
        if canonical is None:
            canonical = next((key for key in macros if key.lower() == name.lower()), None)
        if canonical is None:
            return None
        return MacroSite(canonical, macros[canonical], self.game.macro_definitions.get(canonical))

    def includes(self, file: str | Path) -> list[Path]:
        """The files `file` directly `#include`s (resolved)."""
        return list(self._includes.get(Path(file).resolve(), ()))

    def included_by(self, file: str | Path) -> list[Path]:
        """The files that directly `#include` `file`."""
        return list(self._included_by.get(Path(file).resolve(), ()))

    def rel(self, path: Path) -> str:
        """A path relative to the mod root when possible, for compact display."""
        resolved = path.resolve()
        try:
            return resolved.relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return str(resolved)
