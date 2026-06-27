"""Single-file briefing for an LLM agent: compose the cross-reference graph and the mod
resolver into one report for one ini file. It answers, for the definitions in this file alone,
"what does it declare, what does it point at (and where do those live), what does it include,
and which macros does it lean on" — the "insight into a single file while knowing where to
look" the primer is for.

Resolved references come from the tested `Xref` graph (every target is a registered object, so
it carries its own `file:line`). Broken references, undefined macros, and range checks are a
linter's judgment, left to `sage-lint lint`; the report points there rather than guessing.
"""

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from sage_ini.model.xref import Xref
from sage_ini.modindex import ModIndex
from sage_ini.parser.ast import Attribute
from sage_ini.parser.blockparser import parse_file
from sage_ini.parser.location import Span
from sage_ini.walk import walk_nodes

__all__ = ["Defined", "TargetRef", "SourceRefs", "MacroUse", "Brief", "build_brief", "format_brief"]

# Identifier-shaped tokens, so a macro name is found even glued inside a `#MULTIPLY( NAME 2 )`.
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# A catalog file (commandbutton.ini has ~1000) would swamp the report; cap each list and
# point at the focused form for the rest.
_CAP = 40


@dataclass(frozen=True, slots=True)
class Defined:
    name: str
    table: str
    line: int


@dataclass(frozen=True, slots=True)
class TargetRef:
    name: str
    table: str
    site: str  # file:line of the target definition


@dataclass(frozen=True, slots=True)
class SourceRefs:
    name: str  # a definition in this file
    table: str
    targets: list[TargetRef]


@dataclass(frozen=True, slots=True)
class MacroUse:
    name: str
    value: str
    site: str | None


@dataclass(frozen=True, slots=True)
class Brief:
    file: Path
    focus: str | None  # a single definition the brief was narrowed to, or None for the whole file
    defines: list[Defined]
    includes: list[Path]
    references: list[SourceRefs]
    ref_table_counts: dict[str, int]  # resolved reference edges per target table, whole file
    macros: list[MacroUse]


def _same_file(span_file: str, target: Path) -> bool:
    return Path(span_file).resolve() == target


def _macros_used(
    file: Path, index: ModIndex, line_range: tuple[int, int] | None = None
) -> list[MacroUse]:
    """Distinct macros referenced by the file's attribute values, each with its origin. With
    `line_range`, only attributes inside it are scanned, so a focused brief reports the macros
    of that one definition rather than the whole catalog file."""
    result = parse_file(file, resolve_includes=False)
    seen: dict[str, MacroUse] = {}
    for node in walk_nodes(result.document):
        if not isinstance(node, Attribute):
            continue
        if line_range is not None and not line_range[0] <= node.span.line_start <= line_range[1]:
            continue
        for token in _IDENT.findall(node.value):
            macro = index.macro(token)
            if macro is None or macro.name in seen:
                continue
            site = _site(macro.span, index) if macro.span is not None else None
            seen[macro.name] = MacroUse(macro.name, macro.value, site)
    return sorted(seen.values(), key=lambda m: m.name)


def _site(span: Span, index: ModIndex) -> str:
    return f"{index.rel(Path(span.file))}:{span.line_start}"


def build_brief(index: ModIndex, file: str | Path, focus: str | None = None) -> Brief:
    """Report on the definitions whose source is `file`, resolved against the loaded `index`.
    `focus` narrows it to one definition (by name, case-insensitive) — the way to inspect one
    entry of a large catalog file."""
    game = index.game
    xref = Xref(game)
    target = Path(file).resolve()

    file_objs = [
        obj
        for table in game.tables.values()
        for obj in table.values()
        if obj.span is not None and obj.key is not None and _same_file(obj.span.file, target)
    ]
    if focus is not None:
        file_objs = [obj for obj in file_objs if str(obj.name).lower() == focus.lower()]
    file_objs.sort(key=lambda o: o.span.line_start)

    defines = [Defined(str(obj.name), str(obj.key), obj.span.line_start) for obj in file_objs]

    references: list[SourceRefs] = []
    table_counts: Counter[str] = Counter()
    for obj in file_objs:
        targets = [
            TargetRef(str(target_obj.name), str(target_obj.key), _site(target_obj.span, index))
            for target_obj in sorted(xref.references(obj), key=lambda o: (o.key or "", o.name))
            if target_obj.span is not None and target_obj.key is not None
        ]
        if targets:
            references.append(SourceRefs(str(obj.name), str(obj.key), targets))
            table_counts.update(ref.table for ref in targets)

    # In focus mode, scope the macro scan to the one definition's lines, not the whole file.
    line_range = None
    if focus is not None and file_objs:
        span = file_objs[0].span
        line_range = (span.line_start, span.line_end)

    return Brief(
        file=target,
        focus=focus,
        defines=defines,
        includes=index.includes(target),
        references=references,
        ref_table_counts=dict(table_counts.most_common()),
        macros=_macros_used(target, index, line_range),
    )


def _capped(lines: list[str], items: list[str], note: str) -> None:
    """Append up to `_CAP` items, summarising the overflow rather than flooding the report."""
    for item in items[:_CAP]:
        lines.append(item)
    if len(items) > _CAP:
        lines.append(f"  ... and {len(items) - _CAP} more ({note})")


def format_brief(brief: Brief, index_rel) -> str:
    """Render a `Brief` as the compact agent-facing report. `index_rel` maps a path to a short
    display form (a `ModIndex.rel`)."""
    header = index_rel(brief.file) + (f"  [focus: {brief.focus}]" if brief.focus else "")
    lines = [header]
    focus_hint = "narrow with `brief <dir> <file> <name>`"

    lines.append(f"defines ({len(brief.defines)}):")
    _capped(
        lines,
        [f"  {d.name} [{d.table}]  line {d.line}" for d in brief.defines],
        focus_hint,
    )

    lines.append(f"includes ({len(brief.includes)}):")
    lines += [f"  -> {index_rel(path)}" for path in brief.includes]

    total = sum(brief.ref_table_counts.values())
    summary = " ".join(f"{table}({count})" for table, count in brief.ref_table_counts.items())
    lines.append(f"references ({total} resolved){':  ' + summary if summary else ':'}")
    detail = []
    for source in brief.references:
        detail.append(f"  {source.name} [{source.table}]")
        detail += [f"    -> {ref.name} [{ref.table}]  {ref.site}" for ref in source.targets]
    _capped(lines, detail, focus_hint)

    lines.append(f"macros used ({len(brief.macros)}):")
    _capped(
        lines,
        [
            f"  {m.name} = {m.value}" + (f"  {m.site}" if m.site else "  (no recorded site)")
            for m in brief.macros
        ],
        "see `resolve`",
    )

    lines.append("(dangling references, undefined macros, range checks: `sage-lint lint <dir>`)")
    return "\n".join(lines)
