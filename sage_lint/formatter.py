"""Canonical formatter for SAGE ini files: parse a file and re-emit the tree through
the round-trip-proven printer (four-space indentation, spaces only). A file equal to
that output is well formatted; one that differs can be rewritten.

Files with *structural* parse errors (a stray `End`, an unclosed block/script) are
skipped, never rewritten, since reprinting a recovered tree could move content. Each
file formats on its own, with `#include`s left as text. Tab indentation is reported as
a smell that reformatting clears.
"""

from dataclasses import dataclass, field
from pathlib import Path

from sage_ini.parser.ast import Block, IniDocument, ScriptBlock
from sage_ini.parser.blockparser import parse
from sage_ini.parser.diagnostics import Diagnostic, Severity
from sage_ini.parser.io import read_text_with_encoding, writeback_encoding
from sage_ini.parser.location import Span
from sage_ini.parser.printer import print_document

STRUCTURAL_CODES = frozenset({"stray-end", "unclosed-block", "unclosed-script"})


@dataclass(slots=True)
class FormatResult:
    file: str
    original: str
    formatted: str  # canonical text (LF newlines); equals `original` content when unchanged
    changed: bool
    skipped: bool
    skip_reason: str | None
    smells: list[Diagnostic] = field(default_factory=list)
    parse_diagnostics: list[Diagnostic] = field(default_factory=list)
    encoding: str = "utf-8"


def _leading_whitespace(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _verbatim_lines(document: IniDocument) -> set[int]:
    """1-based line numbers inside `BeginScript`/`EndScript` bodies. The printer reproduces
    these verbatim (an opaque Lua body), so reformatting never touches their indentation —
    flagging tabs there would be an un-fixable warning that survives every format pass."""
    lines: set[int] = set()

    def walk(nodes) -> None:
        for node in nodes:
            if isinstance(node, ScriptBlock):
                # The delimiters (BeginScript/EndScript) are reprinted with canonical
                # indentation, so only the body between them is verbatim.
                lines.update(range(node.span.line_start + 1, node.span.line_end))
            elif isinstance(node, Block):
                walk(node.children)

    walk(document.children)
    return lines


def detect_indent_smells(
    text: str, file: str = "<string>", skip_lines: set[int] | None = None
) -> list[Diagnostic]:
    """Report tab-based indentation, which the canonical style forbids. Lines in `skip_lines`
    are exempt — used to skip script bodies the printer reproduces verbatim, whose tabs
    reformatting can never clear."""
    skip_lines = skip_lines or set()
    smells: list[Diagnostic] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or number in skip_lines:
            continue
        leading = _leading_whitespace(raw)
        if "\t" not in leading:
            continue
        span = Span(file, number, number)
        if " " in leading:
            smells.append(
                Diagnostic(
                    code="mixed-indentation",
                    message="indentation mixes tabs and spaces",
                    span=span,
                    severity=Severity.WARNING,
                )
            )
        else:
            smells.append(
                Diagnostic(
                    code="tab-indentation",
                    message="indentation uses tabs; the canonical style is spaces",
                    span=span,
                    severity=Severity.WARNING,
                )
            )
    return smells


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def format_text(
    text: str,
    file: str = "<string>",
    *,
    align_equals: bool = False,
    align_exclude: tuple[str, ...] = (),
) -> FormatResult:
    result = parse(text, file=file)
    smells = detect_indent_smells(text, file, _verbatim_lines(result.document))
    structural = [d for d in result.diagnostics if d.code in STRUCTURAL_CODES]
    if structural:
        return FormatResult(
            file=file,
            original=text,
            formatted=text,
            changed=False,
            skipped=True,
            skip_reason="structural parse errors",
            smells=smells,
            parse_diagnostics=list(result.diagnostics),
        )

    formatted = print_document(
        result.document,
        align_equals=align_equals,
        align_exclude=align_exclude,
        commandset_layout=True,
    )
    # Newline style is preserved on write-back, so it is not a formatting
    # difference: compare content with newlines normalized.
    changed = formatted != _normalize_newlines(text)
    return FormatResult(
        file=file,
        original=text,
        formatted=formatted,
        changed=changed,
        skipped=False,
        skip_reason=None,
        smells=smells,
        parse_diagnostics=list(result.diagnostics),
    )


def format_file(
    path: str | Path, *, align_equals: bool = False, align_exclude: tuple[str, ...] = ()
) -> FormatResult:
    path = Path(path)
    text, encoding = read_text_with_encoding(path)
    encoding = writeback_encoding(path, encoding)
    result = format_text(
        text, file=str(path), align_equals=align_equals, align_exclude=align_exclude
    )
    result.encoding = encoding
    return result
