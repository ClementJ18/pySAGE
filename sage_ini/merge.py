"""Structure-aware 3-way merge for SAGE ini files - the engine behind the `merge`
command (a git merge driver and a conflict-marker resolver).

Git's line-based merge raises spurious conflicts on ini data because definitions are
long and sit next to each other: two branches adding different objects, or editing
neighbouring ones, collide on adjacency alone. This merges by *identity* instead.
Each side is parsed to the comment-preserving AST (whose node equality ignores spans,
so reflowed whitespace and moved blocks read as unchanged), top-level definitions are
matched by name, and only a definition changed the *same way* counts as a real edit.
When both sides changed one definition, the merge recurses into its fields and emits a
git conflict only around the fields that actually overlap; everything else merges
silently.

Conflicts are rendered as ordinary git markers in the output text (there is no AST
node for them), so a partially-merged file still resolves by hand the usual way.
Blocks with repeated child keys (multi-slot `WeaponSet`, repeated bare-value lines)
are not safely key-addressable, so such a block falls back to a textual diff3 of its
body - still confining the conflict to that one block.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from sage_ini.parser.ast import (
    Attribute,
    Block,
    Include,
    IniDocument,
    MacroDef,
    Node,
    ScriptBlock,
)
from sage_ini.parser.blockparser import parse
from sage_ini.parser.io import read_text
from sage_ini.parser.location import Span
from sage_ini.parser.printer import INDENT, print_document

__all__ = [
    "ConflictLabels",
    "MergeResult",
    "merge_documents",
    "merge_files",
    "resolve_markers",
]


@dataclass(frozen=True, slots=True)
class ConflictLabels:
    """Names written next to the git conflict markers (git's `%X`/`%Y` and `merge`
    config). Defaults match git's generic `ours`/`base`/`theirs`."""

    ours: str = "ours"
    theirs: str = "theirs"
    base: str = "base"


_DEFAULT_LABELS = ConflictLabels()  # immutable singleton, used as the default argument


@dataclass(frozen=True, slots=True)
class MergeResult:
    text: str
    conflicts: int  # number of conflict hunks left in `text`


@dataclass(frozen=True, slots=True)
class _Cfg:
    labels: ConflictLabels
    marker_size: int


@dataclass(slots=True)
class _Unit:
    """A keyable top-level/child node together with the comment/blank-line run that
    immediately precedes it (its leading trivia)."""

    key: tuple
    node: Node
    trivia: list[Node] = field(default_factory=list)


# ---------------------------------------------------------------- rendering helpers


def _render_nodes(nodes: Sequence[Node], depth: int) -> list[str]:
    """Canonically print `nodes` at indentation `depth`. Reuses the public printer at
    depth 0 and shifts every non-blank line right by `depth` indents - equivalent to
    printing at that depth, but touching only the supported printer surface."""
    if not nodes:
        return []
    doc = IniDocument(file="<merge>", children=list(nodes), span=Span("<merge>", 1, 1))
    text = print_document(doc)
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # drop the trailing-newline artifact
    pad = INDENT * depth
    return [pad + line if line else line for line in lines]


def _block_header(block: Block, depth: int) -> str:
    header = block.name
    if block.uses_equals:
        header += f" = {block.label}" if block.label else " ="
    elif block.label:
        header += f" {block.label}"
    suffix = f" {block.comment}" if block.comment else ""
    return INDENT * depth + header + suffix


def _block_end(block: Block, depth: int) -> str:
    suffix = f" {block.end_comment}" if block.end_comment else ""
    return INDENT * depth + "End" + suffix


def _conflict_lines(
    cfg: _Cfg, ours: list[str], theirs: list[str], base: list[str] | None
) -> list[str]:
    size = cfg.marker_size
    out = [f"{'<' * size} {cfg.labels.ours}"]
    out.extend(ours)
    if base is not None:
        out.append(f"{'|' * size} {cfg.labels.base}")
        out.extend(base)
    out.append("=" * size)
    out.extend(theirs)
    out.append(f"{'>' * size} {cfg.labels.theirs}")
    return out


# ----------------------------------------------------------------------- segmentation


def _key(node: Node) -> tuple | None:
    """Identity of a node for matching, or None for trivia (comments, blank lines)."""
    match node:
        case Block(name=name, label=label):
            return ("block", name.casefold(), (label or "").casefold())
        case MacroDef(name=name):
            return ("macro", name.casefold())
        case Include(path=path):
            return ("include", path.casefold())
        case Attribute(key=akey):
            return ("attr", akey.casefold())
        case ScriptBlock():
            return ("script",)
        case _:
            return None


def _segment(nodes: Sequence[Node]) -> tuple[list[_Unit], list[Node]]:
    """Split nodes into keyed units (each owning its preceding trivia) and the trailing
    trivia run after the last keyed node."""
    units: list[_Unit] = []
    pending: list[Node] = []
    for node in nodes:
        key = _key(node)
        if key is None:
            pending.append(node)
        else:
            units.append(_Unit(key=key, node=node, trivia=pending))
            pending = []
    return units, pending


def _has_dup_keys(units: list[_Unit]) -> bool:
    keys = [u.key for u in units]
    return len(keys) != len(set(keys))


# ---------------------------------------------------------------------- textual diff3


def _three_way_lines(base: list, ours: list, theirs: list) -> list[tuple]:
    """Classic line-level diff3 over three sequences. Yields ('clean', items) and
    ('conflict', ours_seg, theirs_seg, base_seg) regions in order. Works on any
    hashable items (text lines, or identity-key tuples for ordering)."""
    a_map: dict[int, int] = {}
    for i, j, n in SequenceMatcher(a=base, b=ours, autojunk=False).get_matching_blocks():
        for k in range(n):
            a_map[i + k] = j + k
    b_map: dict[int, int] = {}
    for i, j, n in SequenceMatcher(a=base, b=theirs, autojunk=False).get_matching_blocks():
        for k in range(n):
            b_map[i + k] = j + k

    # Base lines unchanged on both sides are the synchronisation points.
    stable = [i for i in range(len(base)) if i in a_map and i in b_map]

    regions: list[tuple] = []
    prev_o = prev_a = prev_b = -1
    for oi in [*stable, len(base)]:
        ai = a_map[oi] if oi < len(base) else len(ours)
        bi = b_map[oi] if oi < len(base) else len(theirs)
        o_seg = base[prev_o + 1 : oi]
        a_seg = ours[prev_a + 1 : ai]
        b_seg = theirs[prev_b + 1 : bi]
        if o_seg or a_seg or b_seg:
            if a_seg == o_seg:
                regions.append(("clean", b_seg))  # only theirs changed
            elif b_seg == o_seg or a_seg == b_seg:
                regions.append(("clean", a_seg))  # only ours changed, or both the same
            else:
                regions.append(("conflict", a_seg, b_seg, o_seg))
        if oi < len(base):
            regions.append(("clean", [base[oi]]))
        prev_o, prev_a, prev_b = oi, ai, bi
    return regions


def _textual_fallback(
    cfg: _Cfg, base: Sequence[Node] | None, ours: Sequence[Node], theirs: Sequence[Node], depth: int
) -> tuple[list[str], int]:
    """Merge a level whose keys repeat by diffing the rendered text instead."""
    ours_lines = _render_nodes(ours, depth)
    theirs_lines = _render_nodes(theirs, depth)
    if base is None:
        if ours_lines == theirs_lines:
            return ours_lines, 0
        return _conflict_lines(cfg, ours_lines, theirs_lines, None), 1
    base_lines = _render_nodes(base, depth)
    out: list[str] = []
    conflicts = 0
    for region in _three_way_lines(base_lines, ours_lines, theirs_lines):
        if region[0] == "clean":
            out.extend(region[1])
        else:
            _, a_seg, b_seg, o_seg = region
            out.extend(_conflict_lines(cfg, a_seg, b_seg, o_seg))
            conflicts += 1
    return out, conflicts


# ----------------------------------------------------------------------- structural merge


def _merge_key_order(base_keys: list, ours_keys: list, theirs_keys: list) -> list:
    """A merged ordering of identity keys: ours order is the spine, theirs-only keys
    splice in where diff3 places them. Flattens conflict regions ours-then-theirs."""
    order: list = []
    for region in _three_way_lines(base_keys, ours_keys, theirs_keys):
        if region[0] == "clean":
            order.extend(region[1])
        else:
            order.extend(region[1])  # ours seg
            order.extend(region[2])  # theirs seg
    return order


def _emit_clean(unit: _Unit, depth: int) -> tuple[list[str], int]:
    return _render_nodes([*unit.trivia, unit.node], depth), 0


def _merge_block(
    cfg: _Cfg, base: Block | None, ours: Block, theirs: Block, depth: int
) -> tuple[list[str], int]:
    """Both sides changed this block: merge its children field-by-field, keeping ours'
    header and End line."""
    body, conflicts = _merge_nodes(
        cfg,
        base.children if base is not None else None,
        ours.children,
        theirs.children,
        depth + 1,
    )
    return [_block_header(ours, depth), *body, _block_end(ours, depth)], conflicts


def _merge_or_conflict(
    cfg: _Cfg, base: _Unit | None, ours: _Unit, theirs: _Unit, depth: int
) -> tuple[list[str], int]:
    """Two differing edits to the same definition: recurse if both are blocks, else
    emit a conflict around the whole unit."""
    base_node = base.node if base is not None else None
    base_is_block = base_node is None or isinstance(base_node, Block)
    if isinstance(ours.node, Block) and isinstance(theirs.node, Block) and base_is_block:
        trivia = _render_nodes(ours.trivia, depth)
        body, conflicts = _merge_block(
            cfg, base_node if isinstance(base_node, Block) else None, ours.node, theirs.node, depth
        )
        return [*trivia, *body], conflicts
    return _conflict_unit(cfg, ours, theirs, base, depth)


def _conflict_unit(
    cfg: _Cfg, ours: _Unit | None, theirs: _Unit | None, base: _Unit | None, depth: int
) -> tuple[list[str], int]:
    def render(unit: _Unit | None) -> list[str]:
        return _render_nodes([*unit.trivia, unit.node], depth) if unit is not None else []

    base_lines = render(base) if base is not None else None
    return _conflict_lines(cfg, render(ours), render(theirs), base_lines), 1


def _decide(
    cfg: _Cfg,
    key: tuple,
    base_map: dict | None,
    ours_map: dict,
    theirs_map: dict,
    depth: int,
) -> tuple[list[str], int]:
    base = base_map.get(key) if base_map is not None else None
    ours = ours_map.get(key)
    theirs = theirs_map.get(key)

    if ours is not None and theirs is not None:
        if base is None:  # add/add
            if ours.node == theirs.node:
                return _emit_clean(ours, depth)
            return _merge_or_conflict(cfg, None, ours, theirs, depth)
        ours_changed = ours.node != base.node
        theirs_changed = theirs.node != base.node
        if not theirs_changed:
            return _emit_clean(ours, depth)  # only ours touched it (or neither)
        if not ours_changed:
            return _emit_clean(theirs, depth)  # only theirs touched it
        if ours.node == theirs.node:
            return _emit_clean(ours, depth)  # both made the same edit
        return _merge_or_conflict(cfg, base, ours, theirs, depth)

    if ours is not None:  # theirs is missing
        if base is None:
            return _emit_clean(ours, depth)  # ours added it
        if ours.node == base.node:
            return [], 0  # theirs deleted, ours untouched -> drop
        return _conflict_unit(cfg, ours, None, base, depth)  # modify/delete

    if theirs is not None:  # ours is missing
        if base is None:
            return _emit_clean(theirs, depth)  # theirs added it
        if theirs.node == base.node:
            return [], 0  # ours deleted, theirs untouched -> drop
        return _conflict_unit(cfg, None, theirs, base, depth)  # delete/modify

    return [], 0  # present only in base: deleted on both sides


def _merge_nodes(
    cfg: _Cfg,
    base: Sequence[Node] | None,
    ours: Sequence[Node],
    theirs: Sequence[Node],
    depth: int,
) -> tuple[list[str], int]:
    """Merge one level (a document's or a block's children). Returns rendered lines and
    a conflict count."""
    ours_units, ours_tail = _segment(ours)
    theirs_units, theirs_tail = _segment(theirs)
    base_units, base_tail = _segment(base) if base is not None else (None, [])

    repeated = (
        _has_dup_keys(ours_units)
        or _has_dup_keys(theirs_units)
        or (base_units is not None and _has_dup_keys(base_units))
    )
    if repeated:
        return _textual_fallback(cfg, base, ours, theirs, depth)

    base_map = {u.key: u for u in base_units} if base_units is not None else None
    ours_map = {u.key: u for u in ours_units}
    theirs_map = {u.key: u for u in theirs_units}

    if base_units is None:
        seen = set(ours_map)
        order = [u.key for u in ours_units] + [u.key for u in theirs_units if u.key not in seen]
    else:
        order = _merge_key_order(
            [u.key for u in base_units],
            [u.key for u in ours_units],
            [u.key for u in theirs_units],
        )

    final_order: list[tuple] = []
    seen = set()
    for key in order:
        if key not in seen:
            seen.add(key)
            final_order.append(key)
    # diff3 ordering can drop a key it sees as deleted; append any straggler so its
    # value decision (which may still be a real conflict) is never skipped.
    all_keys = set(ours_map) | set(theirs_map) | (set(base_map) if base_map else set())
    for key in sorted(all_keys - seen):
        final_order.append(key)

    out: list[str] = []
    conflicts = 0
    for key in final_order:
        lines, count = _decide(cfg, key, base_map, ours_map, theirs_map, depth)
        out.extend(lines)
        conflicts += count

    # Trailing trivia (comments/blanks after the last definition): keep ours, else theirs.
    tail = ours_tail or theirs_tail
    out.extend(_render_nodes(tail, depth))
    return out, conflicts


# ------------------------------------------------------------------------- public API


def merge_documents(
    base: IniDocument | None,
    ours: IniDocument,
    theirs: IniDocument,
    *,
    labels: ConflictLabels = _DEFAULT_LABELS,
    marker_size: int = 7,
) -> MergeResult:
    """3-way merge of parsed ini documents. `base=None` does a 2-way merge (no common
    ancestor - only identical edits merge silently, everything else conflicts)."""
    cfg = _Cfg(labels=labels, marker_size=marker_size)
    lines, conflicts = _merge_nodes(
        cfg,
        base.children if base is not None else None,
        ours.children,
        theirs.children,
        0,
    )
    text = "\n".join(lines) + "\n" if lines else ""
    return MergeResult(text=text, conflicts=conflicts)


def merge_files(
    base: str | Path | None,
    ours: str | Path,
    theirs: str | Path,
    *,
    labels: ConflictLabels = _DEFAULT_LABELS,
    marker_size: int = 7,
) -> MergeResult:
    """Merge three ini files. The git merge driver calls this with %O/%A/%B. Files are read
    with sage_ini's encoding fallback (utf-8 / windows-1252 / latin-1), since SAGE data mixes
    encodings and a driver must never crash on a non-utf-8 file."""

    def read(path: str | Path) -> IniDocument:
        return parse(read_text(path), file=str(path)).document

    base_doc = read(base) if base is not None else None
    return merge_documents(
        base_doc, read(ours), read(theirs), labels=labels, marker_size=marker_size
    )


def _split_marked(text: str) -> tuple[str, str, str | None]:
    """Reconstruct the ours/theirs (and diff3 base, if present) versions of a file that
    still carries `<<<<<<<`/`|||||||`/`=======`/`>>>>>>>` conflict markers."""
    ours: list[str] = []
    theirs: list[str] = []
    base: list[str] = []
    have_base = False
    state = "common"
    for line in text.split("\n"):
        if line.startswith("<<<<<<<"):
            state = "ours"
        elif line.startswith("|||||||"):
            state = "base"
            have_base = True
        elif line.startswith("======="):
            state = "theirs"
        elif line.startswith(">>>>>>>"):
            state = "common"
        elif state == "common":
            ours.append(line)
            theirs.append(line)
            base.append(line)
        elif state == "ours":
            ours.append(line)
        elif state == "base":
            base.append(line)
        else:
            theirs.append(line)
    return "\n".join(ours), "\n".join(theirs), ("\n".join(base) if have_base else None)


def resolve_markers(
    text: str,
    *,
    labels: ConflictLabels = _DEFAULT_LABELS,
    marker_size: int = 7,
) -> MergeResult:
    """Re-merge a file that already contains git conflict markers, structurally
    collapsing conflicts git raised between independent definitions. Diff3-style
    markers (`merge.conflictStyle = diff3`/`zdiff3`) give a true common ancestor; plain
    markers fall back to a 2-way merge."""
    ours_text, theirs_text, base_text = _split_marked(text)
    ours = parse(ours_text, file="<ours>").document
    theirs = parse(theirs_text, file="<theirs>").document
    base = parse(base_text, file="<base>").document if base_text is not None else None
    return merge_documents(base, ours, theirs, labels=labels, marker_size=marker_size)
