"""Reproduce the engine's ThingTemplate registration order, so a replay's object id maps to a
template exactly (no per-game offset).

A replay recruit order carries a ThingTemplate id: the dense, 1-based index the engine assigns
each `Object`/`ChildObject`/`ObjectReskin` as it is parsed. The parse order is *not* an
alphabetical walk of `data/ini` - it follows the subsystem load list in
`Data\\INI\\Default\\SubsystemLegend.ini`. For objects that is `LoadSubsystem TheThingFactory`:

    InitFile = Data\\INI\\Default\\Object.ini      ; DefaultThingTemplate first (id 1)
    InitPath = Data\\INI\\Object                   ; then the object tree, recursively
    IncludePathCinematics = Data\\INI\\Object\\Cinematic\\   ; -cinematics only, skipped in a game
    ExcludePath = ...                              ; pruned during the InitPath walk

Reproducing that - the engine's `INI::loadDirectory` two-pass file order (top-level files first,
then all subdirectory files as one flat path-sorted list; see `_walk`), cinematic path excluded,
`#include`s expanded, ids numbered from 1 - makes `replay_id == thing_template_order(...).index(n)
+ 1` for every recruitable unit (36/36 across all six factions) and every built structure (27/27,
`0x41A` builds), ids 2002–2863.

`thing_template_order` walks *every* subsystem in legend order, so objects declared outside the
main object tree (crates, formation icons) land at their true - higher - ids too.
"""

import argparse
import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sage_ini.model.objects import REGISTRY
from sage_ini.parser.ast import Block
from sage_ini.parser.blockparser import parse_file
from sage_ini.stats import as_root_list, ini_root

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


def _resolve_in_layers(legend_path: str, roots: Sequence[Path]) -> Path | None:
    """Resolve a legend path against each game root in priority order, returning the first
    (highest-priority) layer that has it - so a mod file overrides the base game's."""
    for root in roots:
        resolved = _resolve(legend_path, root)
        if resolved is not None and resolved.exists():
            return resolved
    return None


def _game_rel(path: Path, root: Path) -> str:
    """`path`'s engine-facing `data/ini/…` name, normalized, for matching against legend paths."""
    return "data/ini/" + path.relative_to(ini_root(root)).as_posix().lower()


def _walk(legend_path: str, roots: Sequence[Path], pruned: Sequence[str]) -> Iterator[Path]:
    """`.ini` files under one InitPath in the engine's `INI::loadDirectory` order, across every
    game layer merged into one virtual tree: a file present in more than one layer is taken from
    the highest-priority (mod-over-base) layer, and a layer-unique file registers at its own path
    position. Ordering is the engine's two-pass enumeration of one flat, path-sorted set - first
    the files sitting directly in the directory (alphabetical), then every file in a subdirectory
    *at any depth* as a single flat list sorted by full path (backslash-separated, lowercased,
    matching the engine's sorted `FilenameList`); below the top level, files and subdirectories
    interleave purely by path order. Any file whose `data/ini/…` path is, or lies under, a
    `pruned` entry is skipped (ExcludePath / cinematic path)."""

    def blocked(path: Path, root: Path) -> bool:
        rel = _game_rel(path, root)
        return any(rel == p or rel.startswith(p + "/") for p in pruned)

    # rel path (lowercased, backslash-separated) -> the file that wins for it. Layers are visited
    # high priority first and `setdefault` keeps that winner, so a mod file shadows a base file at
    # the same InitPath-relative path while its objects still register at that path's position.
    entries: dict[str, Path] = {}
    for root in roots:
        directory = _resolve(legend_path, root)
        if directory is None or not directory.is_dir() or blocked(directory, root):
            continue
        for path in directory.rglob("*"):
            if not (path.is_file() and path.suffix.lower() == ".ini") or blocked(path, root):
                continue
            rel = path.relative_to(directory).as_posix().replace("/", "\\").lower()
            entries.setdefault(rel, path)

    for rel in sorted(rel for rel in entries if "\\" not in rel):
        yield entries[rel]
    for rel in sorted(rel for rel in entries if "\\" in rel):
        yield entries[rel]


def _object_names(path: Path, layers: tuple[Path, ...]) -> Iterator[str]:
    """The template name of every object-registering top-level block in `path`, in file order,
    with `#include`s expanded (so `.inc`-defined objects register at the include point)."""
    document = parse_file(path, resolve_includes=True, include_layers=layers).document
    for node in document.children:
        if isinstance(node, Block) and node.name in OBJECT_BLOCKS and node.label:
            yield node.label.split()[0]


def thing_template_order(
    root: str | Path | Sequence[str | Path],
    *,
    bases: Sequence[str | Path] = (),
    cinematics: bool = False,
    debug: bool = False,
) -> list[str]:
    """Template names in engine ThingTemplate registration order. The replay object id of a name is
    its index **+ 1** (ids are 1-based; id 0 is the reserved null template).

    `root` is a single game root or an ascending-priority sequence of them (a later root shadows an
    earlier one). `bases` are further lower-priority game roots (the base game a mod is layered
    over): their SubsystemLegend.ini and object tree stand in when the mod does not ship its own,
    and a higher-priority file overrides a lower one at the same path - reproducing the id order
    the engine assigns when the mod is loaded over the base. `cinematics` includes the
    `-cinematics`-only object paths; `debug` includes `InitFileDebug` files. Names redefined later
    keep their first position (the engine updates in place)."""
    # Descending priority (highest first): the game roots last-wins, then the base roots.
    roots = [*reversed(as_root_list(root)), *(Path(base) for base in bases)]
    legend_file = _resolve_in_layers("data/ini/" + _LEGEND, roots)
    if legend_file is None or not legend_file.is_file():
        raise FileNotFoundError(f"no {_LEGEND} under {', '.join(str(r) for r in roots)}")
    subsystems = parse_subsystem_legend(legend_file.read_text(encoding="latin-1"))
    layers = tuple(ini_root(r) for r in roots)

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
            if kind == "file":
                resolved = _resolve_in_layers(legend_path, roots)
                if resolved is not None:
                    register(resolved)
            else:
                for ini in _walk(legend_path, roots, pruned):
                    register(ini)
    return order


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the replay object-id → template table.")
    parser.add_argument(
        "root",
        type=Path,
        nargs="+",
        help="game root (holds data/ini) or extracted ini dump; repeatable, ascending priority "
        "(base game first, mod after it)",
    )
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
