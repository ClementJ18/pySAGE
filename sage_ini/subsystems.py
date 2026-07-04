"""Reproduce the engine's ThingTemplate registration order, so a replay's object id maps to a
template exactly (no per-game offset).

A replay recruit order carries a ThingTemplate id: the dense, 1-based index the engine assigns
each `Object`/`ChildObject`/`ObjectReskin` as it is parsed. The parse order is *not* an
alphabetical walk of `data/ini` — it follows the subsystem load list in
`Data\\INI\\Default\\SubsystemLegend.ini`. For objects that is `LoadSubsystem TheThingFactory`:

    InitFile = Data\\INI\\Default\\Object.ini      ; DefaultThingTemplate first (id 1)
    InitPath = Data\\INI\\Object                   ; then the object tree, recursively
    IncludePathCinematics = Data\\INI\\Object\\Cinematic\\   ; -cinematics only, skipped in a game
    ExcludePath = ...                              ; pruned during the InitPath walk

Reproducing that — the engine's `INI::loadDirectory` two-pass file order (top-level files first,
then all subdirectory files as one flat path-sorted list; see `_walk`), cinematic path excluded,
`#include`s expanded, ids numbered from 1 — makes `replay_id == thing_template_order(...).index(n)
+ 1` for every recruitable unit (36/36 across all six factions) and every built structure (27/27,
`0x41A` builds), ids 2002–2863.

`thing_template_order` walks *every* subsystem in legend order, so objects declared outside the
main object tree (crates, formation icons) land at their true — higher — ids too.
"""

import argparse
import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sage_ini.model.objects import REGISTRY
from sage_ini.parser.ast import Block
from sage_ini.parser.blockparser import parse_file
from sage_ini.stats import ini_root

__all__ = ["Subsystem", "parse_subsystem_legend", "thing_template_order"]

# Block keywords that register a ThingTemplate (and so consume an id), taken from the model so a
# future object-bearing block type is picked up automatically.
OBJECT_BLOCKS = frozenset(
    name for name, cls in REGISTRY.items() if getattr(cls, "key", None) == "objects"
)

_LEGEND = "default/subsystemlegend.ini"


@dataclass(slots=True)
class Subsystem:
    """One `LoadSubsystem` entry. `loads` keeps InitFile/InitPath in declared order (the engine
    loads them in that sequence); `excludes`/`cinematics` prune the InitPath walks."""

    name: str
    loads: list[tuple[str, str]] = field(default_factory=list)  # ("file"|"path", raw legend path)
    debug_loads: list[tuple[str, str]] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    cinematics: list[str] = field(default_factory=list)


def parse_subsystem_legend(text: str) -> list[Subsystem]:
    """The ordered `LoadSubsystem` list from a SubsystemLegend.ini body."""
    subsystems: list[Subsystem] = []
    current: Subsystem | None = None
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        # A directive is either `Key = value` or a header `Keyword Name` with no `=`.
        if "=" in line:
            head, _, value = line.partition("=")
            head, value = head.strip(), value.strip()
        else:
            parts = line.split(None, 1)
            head, value = parts[0], (parts[1] if len(parts) > 1 else "")
        low = head.lower()
        if low == "loadsubsystem":
            current = Subsystem(name=value or "?")
            subsystems.append(current)
        elif current is None:
            continue
        elif low == "end":
            current = None
        elif low == "initfile":
            current.loads.append(("file", value))
        elif low == "initpath":
            current.loads.append(("path", value))
        elif low == "initfiledebug":
            current.debug_loads.append(("file", value))
        elif low == "excludepath":
            current.excludes.append(_norm(value))
        elif low == "includepathcinematics":
            current.cinematics.append(_norm(value))
    return subsystems


def _norm(legend_path: str) -> str:
    """A legend path folded to lowercase, forward-slashed, no leading/trailing slash."""
    return legend_path.strip().replace("\\", "/").strip("/").lower()


def _resolve(legend_path: str, root: Path) -> Path | None:
    """Turn a `Data\\INI\\…` legend path into a real path under `root`, case-insensitively. The
    part after `data/ini` resolves against `ini_root(root)` (handling the nested-dump layout)."""
    parts = _norm(legend_path).split("/")
    if parts[:2] == ["data", "ini"]:
        parts = parts[2:]
    node = ini_root(root)
    for part in parts:
        if not part:
            continue
        nxt = node / part
        if nxt.exists():
            node = nxt
            continue
        if not node.is_dir():
            return None
        match = next((c for c in node.iterdir() if c.name.lower() == part), None)
        if match is None:
            return None
        node = match
    return node


def _game_rel(path: Path, root: Path) -> str:
    """`path`'s engine-facing `data/ini/…` name, normalized, for matching against legend paths."""
    return "data/ini/" + path.relative_to(ini_root(root)).as_posix().lower()


def _walk(directory: Path, root: Path, pruned: Sequence[str]) -> Iterator[Path]:
    """`.ini` files under `directory` in the engine's `INI::loadDirectory` order: a two-pass
    enumeration of one flat, path-sorted set — first the files sitting directly in `directory`
    (alphabetical), then every file in a subdirectory *at any depth* as a single flat list
    sorted by full path (backslash-separated, lowercased, matching the engine's sorted
    `FilenameList`). This is **not** recursive files-before-subdirs: below the top level, files
    and subdirectories interleave purely by path order. Any file whose `data/ini/…` path is, or
    lies under, a `pruned` entry is skipped (ExcludePath / cinematic path)."""

    def blocked(path: Path) -> bool:
        rel = _game_rel(path, root)
        return any(rel == p or rel.startswith(p + "/") for p in pruned)

    if blocked(directory):
        return

    def sort_key(path: Path) -> str:
        # The engine sorts its FilenameList of lowercased, backslash-separated archive paths.
        return path.relative_to(directory).as_posix().replace("/", "\\").lower()

    files = [
        p
        for p in directory.rglob("*")
        if p.is_file() and p.suffix.lower() == ".ini" and not blocked(p)
    ]
    top = sorted((p for p in files if p.parent == directory), key=sort_key)
    subdirs = sorted((p for p in files if p.parent != directory), key=sort_key)
    yield from top
    yield from subdirs


def _object_names(path: Path, layers: tuple[Path, ...]) -> Iterator[str]:
    """The template name of every object-registering top-level block in `path`, in file order,
    with `#include`s expanded (so `.inc`-defined objects register at the include point)."""
    document = parse_file(path, resolve_includes=True, include_layers=layers).document
    for node in document.children:
        if isinstance(node, Block) and node.name in OBJECT_BLOCKS and node.label:
            yield node.label.split()[0]


def thing_template_order(
    root: str | Path, *, cinematics: bool = False, debug: bool = False
) -> list[str]:
    """Template names in engine ThingTemplate registration order. The replay object id of a name is
    its index **+ 1** (ids are 1-based; id 0 is the reserved null template).

    `cinematics` includes the `-cinematics`-only object paths; `debug` includes `InitFileDebug`
    files. Names redefined later keep their first position (the engine updates in place)."""
    root = Path(root)
    legend_file = _resolve("data/ini/" + _LEGEND, root)
    if legend_file is None or not legend_file.is_file():
        raise FileNotFoundError(f"no {_LEGEND} under {root}")
    subsystems = parse_subsystem_legend(legend_file.read_text(encoding="latin-1"))
    layers = (ini_root(root),)

    order: list[str] = []
    seen: set[str] = set()

    def register(path: Path) -> None:
        for name in _object_names(path, layers):
            if name not in seen:
                seen.add(name)
                order.append(name)

    for subsystem in subsystems:
        pruned = list(subsystem.excludes)
        if not cinematics:
            pruned += subsystem.cinematics
        loads = subsystem.loads + (subsystem.debug_loads if debug else [])
        for kind, legend_path in loads:
            resolved = _resolve(legend_path, root)
            if resolved is None or not resolved.exists():
                continue
            if kind == "file":
                register(resolved)
            else:
                for ini in _walk(resolved, root, pruned):
                    register(ini)
    return order


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the replay object-id → template table.")
    parser.add_argument("root", type=Path, help="game root (holds data/ini) or extracted ini dump")
    parser.add_argument("-o", "--out", type=Path, help="write id→name JSON here (else a summary)")
    parser.add_argument("--cinematics", action="store_true", help="include -cinematics paths")
    args = parser.parse_args(argv)

    order = thing_template_order(args.root, cinematics=args.cinematics)
    table = {str(i + 1): name for i, name in enumerate(order)}
    if args.out:
        args.out.write_text(json.dumps(table, indent=2), encoding="utf-8")
        print(f"wrote {args.out}: {len(table)} templates (id 1..{len(order)})")
    else:
        print(f"{len(order)} templates; ids 1..{len(order)}")
        for i in (0, 1, len(order) // 2, len(order) - 1):
            print(f"  id {i + 1}: {order[i]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
