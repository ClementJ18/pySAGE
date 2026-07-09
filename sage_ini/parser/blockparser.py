"""Recursive block parser: token lines -> comment-preserving AST.

Every `Header ... End` block is consumed structurally whether or not anything
downstream knows its name, so an unknown module can never desynchronize its
parent. Malformed input produces diagnostics and recovery, never exceptions.
"""

import posixpath
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sage_ini.parser.ast import (
    Attribute,
    BlankLine,
    Block,
    Comment,
    Include,
    IniDocument,
    MacroDef,
    Node,
    ScriptBlock,
)
from sage_ini.parser.diagnostics import Diagnostics
from sage_ini.parser.keywords import (
    BARE_VALUE_KEYS,
    BLOCK_OPENING_KEYWORDS,
    CONDITIONAL_VALUE_OPENERS,
    CONTEXTUAL_BARE_VALUE_KEYS,
    CONTEXTUAL_BLOCK_OPENERS,
    OPENER_VALUE_TOKENS,
)
from sage_ini.parser.lexer import Line, tokenize, tokenize_path
from sage_ini.parser.location import Span

__all__ = [
    "parse",
    "parse_file",
    "parse_lines",
    "ParseResult",
    "expand_includes",
    "include_target",
    "resolve_include",
]


@dataclass(slots=True)
class ParseResult:
    document: IniDocument
    diagnostics: Diagnostics


def _normalize_value(value: str) -> str:
    """Collapse internal whitespace runs in an attribute value to single spaces - alignment
    is never meaningful, so this keeps token-splitting converters robust to a tab between
    tokens and lets the formatter canonicalize the value."""
    return " ".join(value.split())


def parse(text: str, file: str = "<string>") -> ParseResult:
    return parse_lines(tokenize(text, file=file), file=file)


def parse_file(
    path: str | Path,
    resolve_includes: bool = False,
    include_layers: Sequence[str | Path] = (),
) -> ParseResult:
    """Parse one file; with `resolve_includes`, splice `#include`d files in. `include_layers`
    are ordered ini roots (mod first, base after) that includes resolve against, the way the
    engine overlays a mod onto the base game (see `resolve_include`)."""
    path = Path(path).resolve()
    lines = tokenize_path(path)
    diagnostics = Diagnostics()
    if resolve_includes:
        layers = tuple(Path(layer).resolve() for layer in include_layers)
        lines = expand_includes(lines, path, layers, diagnostics, frozenset())
    return parse_lines(lines, file=str(path), diagnostics=diagnostics)


def include_target(content: str) -> str | None:
    """The quoted path of an `#include` line, or None."""
    if not content.startswith("#include"):
        return None
    rest = content[len("#include") :].strip()
    if len(rest) >= 2 and rest.startswith('"') and rest.endswith('"'):
        return rest[1:-1]
    return None


# Resolved include targets, keyed by (target, source, layers). The same `#include` is
# resolved once per root that pulls it in - the same handful of shared headers across hundreds
# of roots - so memoizing collapses the repeated filesystem probing. Like the tokenize cache,
# this assumes the file tree is stable for the run; clear it if includes are added on disk.
_INCLUDE_CACHE: dict[tuple[str, str, tuple[str, ...]], Path | None] = {}


def resolve_include(target: str, source: Path, layers: tuple[Path, ...]) -> Path | None:
    """Resolve an include target written in file `source` to an existing file, relative to
    the including file's own directory (a leading slash is stripped, not ini-root anchoring).
    When `source` sits in an overlay layer, the same virtual path is tried in every layer so
    a mod include can fall through to the base game."""
    cache_key = (target, str(source), tuple(str(layer) for layer in layers))
    if cache_key in _INCLUDE_CACHE:
        return _INCLUDE_CACHE[cache_key]
    resolved = _resolve_include(target, source, layers)
    _INCLUDE_CACHE[cache_key] = resolved
    return resolved


def _resolve_include(target: str, source: Path, layers: tuple[Path, ...]) -> Path | None:
    normalized = target.replace("\\", "/").lstrip("/")

    for layer in layers:
        if source.is_relative_to(layer):
            virtual_dir = source.parent.relative_to(layer)
            relative = posixpath.normpath(str(PurePosixPath(virtual_dir.as_posix()) / normalized))
            for candidate_layer in layers:
                candidate = candidate_layer / relative
                if candidate.is_file():
                    return candidate.resolve()
            return None

    candidate = (source.parent / normalized).resolve()
    return candidate if candidate.is_file() else None


def expand_includes(
    lines: list[Line],
    source: Path,
    layers: tuple[Path, ...],
    diagnostics: Diagnostics,
    seen: frozenset[str],
) -> list[Line]:
    """Splice each `#include`'s lines into the stream. The directive line is kept (it becomes
    an Include node); spliced lines' spans keep pointing at their physical file."""
    out: list[Line] = []
    for line in lines:
        out.append(line)
        target = include_target(line.content)
        if target is None:
            continue

        resolved = resolve_include(target, source, layers)
        if resolved is None:
            diagnostics.add("unresolved-include", f"cannot resolve {target}", line.span)
            continue
        key = str(resolved).lower()
        if key in seen:
            diagnostics.add("include-cycle", f"include cycle via {target}", line.span)
            continue

        sub = tokenize_path(resolved)
        out.extend(expand_includes(sub, resolved, layers, diagnostics, seen | {key}))
    return out


def _parse_directive(line: Line, children: list[Node], diagnostics: Diagnostics):
    content = line.content

    if content.startswith("#define"):
        parts = content.split(maxsplit=2)
        if len(parts) < 2:
            diagnostics.add("malformed-define", "#define without a name", line.span)
            return
        value = parts[2] if len(parts) == 3 else ""
        children.append(MacroDef(name=parts[1], value=value, comment=line.comment, span=line.span))
        return

    if content.startswith("#include"):
        target = include_target(content)
        if target is not None:
            children.append(Include(path=target, comment=line.comment, span=line.span))
            return
        diagnostics.add("malformed-include", "#include expects a quoted path", line.span)
        return

    diagnostics.add("unknown-directive", f"unknown directive: {content.split()[0]}", line.span)


def parse_lines(
    lines: list[Line], file: str, diagnostics: Diagnostics | None = None
) -> ParseResult:
    if diagnostics is None:
        diagnostics = Diagnostics()
    root: list[Node] = []
    stack: list[Block] = []
    script: ScriptBlock | None = None
    pending_blank: Span | None = None  # first span of a run of blank lines, if any

    def children() -> list[Node]:
        return stack[-1].children if stack else root

    def flush_blank() -> None:
        # Emit one separator for a run of blank lines, but never at the start of
        # a block or the document, so the tree stays canonical and idempotent.
        nonlocal pending_blank
        if pending_blank is not None:
            if children():
                children().append(BlankLine(span=pending_blank))
            pending_blank = None

    for line in lines:
        if script is not None:
            if line.content.lower() == "endscript":
                script.end_comment = line.comment
                if script.span.file == line.span.file:
                    script.span = script.span.merge(line.span)
                script = None
            else:
                script.lines.append(line.raw)
            continue

        if line.is_blank:
            if pending_blank is None:
                pending_blank = line.span
            continue

        if not line.content:
            flush_blank()
            # Reaching here means a non-blank line with no content - i.e. comment-only - so
            # `line.comment` is set; `or ""` only satisfies the type narrower.
            children().append(Comment(text=line.comment or "", span=line.span))
            continue

        content = line.content

        # Token-based grammar: End may share a line with the next statement
        # (`End  StateName = Sword`), so peel leading End tokens first.
        while content:
            end_parts = content.split(maxsplit=1)
            if end_parts[0].lower() != "end":
                break
            # a trailing blank inside the closing block; drop it rather than carry it past End
            pending_blank = None
            if stack:
                block = stack.pop()
                # a block may open in one file and close in an included one; keep its span
                # within the opener's file
                if block.span.file == line.span.file:
                    block.span = block.span.merge(line.span)
                if len(end_parts) == 1:
                    block.end_comment = line.comment
            else:
                diagnostics.add("stray-end", "End with no open block", line.span)
            content = end_parts[1] if len(end_parts) == 2 else ""

        if not content:
            continue

        if content.startswith("#"):
            flush_blank()
            _parse_directive(line, children(), diagnostics)
            continue

        # The engine treats '=' as a skippable token, so block detection keys on the line's
        # first token (`Behavior SubObjectsUpgrade = X` is a Behavior header).
        head = content.split(maxsplit=1)[0].split("=", maxsplit=1)[0] or "="
        rest = content[len(head) :].strip()
        rest_tokens = rest.replace("=", " ").split()

        parent = stack[-1].name if stack else ""
        contextual = CONTEXTUAL_BLOCK_OPENERS.get(parent, frozenset())
        value_head = rest_tokens[0] if rest_tokens else ""
        opens = (
            head in BLOCK_OPENING_KEYWORDS
            or head in contextual
            or value_head in OPENER_VALUE_TOKENS
            or CONDITIONAL_VALUE_OPENERS.get(head) == value_head
        )

        if opens:
            flush_blank()
            block = Block(
                name=head,
                label=" ".join(rest_tokens) or None,
                uses_equals="=" in content,
                comment=line.comment,
                span=line.span,
            )
            children().append(block)
            stack.append(block)
            continue

        if "=" in content:
            flush_blank()
            key, _, value = content.partition("=")
            children().append(
                Attribute(
                    key=key.strip(),
                    value=_normalize_value(value),
                    comment=line.comment,
                    span=line.span,
                )
            )
            continue

        parts = content.split(maxsplit=1)
        label_rest = parts[1] if len(parts) == 2 else None

        if parts[0] == "BeginScript":
            flush_blank()
            script = ScriptBlock(lines=[], comment=line.comment, span=line.span)
            children().append(script)
            continue

        parent = stack[-1].name if stack else ""
        contextual_values = CONTEXTUAL_BARE_VALUE_KEYS.get(parent, frozenset())
        # block names are identifiers: a first token starting with anything else (a
        # commandset slot `2 Command_X`, a stray `"` after End) is a value line, not an opener
        if (
            parts[0] in BARE_VALUE_KEYS
            or parts[0] in contextual_values
            or not (parts[0][0].isalpha() or parts[0][0] == "_")
        ):
            flush_blank()
            children().append(
                Attribute(
                    key=parts[0],
                    value=_normalize_value(label_rest) if label_rest else "",
                    uses_equals=False,
                    comment=line.comment,
                    span=line.span,
                )
            )
            continue

        flush_blank()
        block = Block(
            name=parts[0],
            label=label_rest,
            uses_equals=False,
            comment=line.comment,
            span=line.span,
        )
        children().append(block)
        stack.append(block)

    if script is not None:
        diagnostics.add("unclosed-script", "missing EndScript", script.span)

    for block in stack:
        diagnostics.add("unclosed-block", f"missing End for block '{block.name}'", block.span)

    last_line = max(1, len(lines))
    document = IniDocument(file=file, children=root, span=Span(file, 1, last_line))
    return ParseResult(document=document, diagnostics=diagnostics)
