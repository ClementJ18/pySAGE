"""Automated, opt-in fixes for a subset of lint diagnostics (`lint --fix`). Every fix below
is behaviour-preserving against the engine — it changes only what the engine already ignores:

- ``enum-case``: rewrite a miscased enum token to its canonical name (the engine
  matches enums case-insensitively, so only spelling changes).
- ``reference-case``: rewrite a cross-reference token to the definition's casing (the
  engine resolves names case-insensitively, so only spelling changes). When the token
  reached the field through a macro (`Field = MACRO`), the use site does not hold it, so
  the rewrite follows it back to the `#define` body in the same file.
- ``macro-case``: rewrite a macro reference to the `#define`'s casing (macros are matched
  case-insensitively too) — the same token rewrite as the two above.
- ``repeated-field`` / ``repeated-flag-field``: a scalar (or whole-set flag) field set more
  than once keeps only its last value, so the earlier occurrences are deleted.
- ``spurious-block-label``: a block header written `Block = Tag` where the engine wants
  `Block Tag` — the `=` does nothing, so it is removed.

Fixes are line-level edits on the original text (never an AST reprint), computed
against the original line numbering and applied in one pass so they don't shift.
"""

import re
from collections import defaultdict
from pathlib import Path

from sage_ini.parser.ast import Attribute, Block, Node
from sage_ini.parser.blockparser import parse
from sage_ini.parser.diagnostics import Diagnostic
from sage_ini.parser.io import read_text_with_encoding, writeback_encoding
from sage_ini.parser.lexer import _find_comment_start, forget_path, split_comment

# Diagnostic codes this module knows how to fix.
FIXABLE: frozenset[str] = frozenset(
    {
        "enum-case",
        "reference-case",
        "macro-case",
        "repeated-field",
        "repeated-flag-field",
        "spurious-block-label",
    }
)

# Codes fixed by rewriting a miscased token to its canonical spelling — the same line edit
# for an enum value, a cross-reference and a macro reference, differing only in what supplied
# the casing. All carry `given`/`canonical` in their diagnostic `extra`.
_CASE_REWRITE: frozenset[str] = frozenset({"enum-case", "reference-case", "macro-case"})

# Codes fixed by deleting the earlier, superseded occurrences of a repeated field — a plain
# scalar (`repeated-field`) or a whole-set flag list (`repeated-flag-field`); only the last set
# takes effect either way. The field name is in `extra["key"]` or `extra["field"]`.
_REPEATED: frozenset[str] = frozenset({"repeated-field", "repeated-flag-field"})

# A `#define NAME body…` directive, capturing the body (group 1) the macro expands to — where
# a miscased token lives when a field reaches it through the macro rather than spelling it out.
_DEFINE_RE = re.compile(r"^\s*#define\s+\S+\s+(.*)$")


def fix_diagnostics(diagnostics: list[Diagnostic]) -> tuple[dict[str, int], list[Diagnostic]]:
    """Apply every fixable diagnostic to its source file. Returns `(fixed_by_file,
    applied)`: a per-path count of fixes, and the diagnostics actually applied (so the
    caller can drop them from the report)."""
    by_file: dict[str, list[Diagnostic]] = defaultdict(list)
    for diag in diagnostics:
        if diag.code in FIXABLE:
            by_file[diag.span.file].append(diag)

    fixed_by_file: dict[str, int] = {}
    applied: list[Diagnostic] = []
    for file, diags in by_file.items():
        done = _fix_file(file, diags)
        if done:
            fixed_by_file[file] = len(done)
            applied.extend(done)
    return fixed_by_file, applied


def _fix_file(path: str, diags: list[Diagnostic]) -> list[Diagnostic]:
    """Rewrite one file for its fixable diagnostics; return the ones applied."""
    try:
        text, encoding = read_text_with_encoding(path)
    except OSError:
        return []
    encoding = writeback_encoding(path, encoding)
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.replace("\r\n", "\n").split("\n")

    deletes: set[int] = set()
    replaces: dict[int, list[tuple[str, str]]] = defaultdict(list)
    dequals: set[int] = set()  # header lines whose spurious `=` is to be removed
    applied: list[Diagnostic] = []

    # A document parse is needed to locate a block's repeated occurrences; build it once
    # if any structural fix is present.
    structural = [d for d in diags if d.code in _REPEATED]
    document = parse(text, file=path).document if structural else None

    for diag in (d for d in diags if d.code in _REPEATED):
        key = diag.extra.get("key") or diag.extra.get("field")
        if not key:
            continue
        targets = _repeated_delete_lines(document, diag.span.line_start, key, lines)
        if targets:
            deletes.update(targets)
            applied.append(diag)

    for diag in (d for d in diags if d.code == "spurious-block-label"):
        line_no = diag.span.line_start
        if 1 <= line_no <= len(lines) and _line_has_spurious_equals(lines[line_no - 1]):
            dequals.add(line_no)
            applied.append(diag)

    for diag in diags:
        if diag.code not in _CASE_REWRITE:
            continue
        given, canonical = diag.extra.get("given"), diag.extra.get("canonical")
        if not (given and canonical and given != canonical):
            continue
        line_no = diag.span.line_start
        # The diagnostic's span can point at a line that doesn't hold the token: a macro-supplied
        # value lives in the `#define` body (follow it there), and a repeated field is flagged on
        # its first occurrence while the value sits on a later line (nothing to rewrite, so skip
        # rather than "fix" a no-op that would resurface).
        if 1 <= line_no <= len(lines) and _token_in_value(lines[line_no - 1], given):
            target = line_no
        else:
            target = _macro_def_line_with_token(lines, given)
        if target is None:
            continue
        replaces[target].append((given, canonical))
        applied.append(diag)

    if not deletes and not replaces and not dequals:
        return []

    out: list[str] = []
    for number, line in enumerate(lines, start=1):
        if number in deletes:
            continue
        if number in replaces:
            line = _apply_replacements(line, replaces[number])
        if number in dequals:
            line = _remove_header_equals(line)
        out.append(line)

    Path(path).write_text("\n".join(out).replace("\n", newline), encoding=encoding, newline="")
    # Drop the tokenizer's cached copy: a case-only fix keeps the file's size, and a rewrite in
    # the same mtime tick keeps its mtime, so the cache's (mtime, size) signature would otherwise
    # miss this edit and a re-lint would re-flag what we just fixed.
    forget_path(path)
    return applied


def _repeated_delete_lines(document, first_line: int, key: str, lines: list[str]) -> list[int]:
    """Lines of the earlier (superseded) occurrences of `key` to delete.

    Locates the block whose own attribute sits at `first_line`, then keeps the
    last occurrence of `key` and returns the others. Only single-statement lines
    are returned, so a rare shared line (`End  Key = X`) is left for a human.
    """
    siblings = _block_children_with_attr_at(document.children, first_line)
    if siblings is None:
        return []
    occurrences = [c for c in siblings if isinstance(c, Attribute) and c.key == key]
    if len(occurrences) < 2:
        return []
    targets = []
    for attr in occurrences[:-1]:
        line_no = attr.span.line_start
        if attr.span.line_end == line_no and _line_is_only_attr(lines, line_no, key):
            targets.append(line_no)
    return targets


def _line_has_spurious_equals(line: str) -> bool:
    """Whether `line` is a `Block = Tag` header whose `=` can be removed: an `=` before any
    comment with a token on each side. Guards the rewrite against a line that holds no `=` (e.g.
    a multi-line block already flagged on a different physical line)."""
    content, _ = split_comment(line)
    return re.match(r"^\s*\S+\s*=\s*\S", content) is not None


def _remove_header_equals(line: str) -> str:
    """Rewrite a `Block = Tag` header to the engine's plain `Block Tag` form, dropping only the
    `=` (and the padding around it), and leaving indentation and any trailing comment intact."""
    comment_start = _find_comment_start(line)
    if comment_start == -1:
        comment_start = len(line)
    head, comment = line[:comment_start], line[comment_start:]
    head = re.sub(r"^(\s*\S+)\s*=\s*", r"\1 ", head, count=1)
    return head + comment


def _block_children_with_attr_at(nodes: list[Node], line: int) -> list[Node] | None:
    """The children of the block that directly owns an attribute on `line`."""
    for node in nodes:
        if not isinstance(node, Block):
            continue
        if any(isinstance(c, Attribute) and c.span.line_start == line for c in node.children):
            return node.children
        found = _block_children_with_attr_at(node.children, line)
        if found is not None:
            return found
    return None


def _line_is_only_attr(lines: list[str], line_no: int, key: str) -> bool:
    """Whether `line_no` holds exactly one attribute statement for `key` and nothing else —
    either the `Key = value` form or the space-delimited `Key value` form (e.g. `Geometry
    nh1_fills`). Guards against a rare shared line (`End  Key = X`) where `key` is not the
    line's first token."""
    if not 1 <= line_no <= len(lines):
        return False
    content, _ = split_comment(lines[line_no - 1])
    if "=" in content:
        leading = content.split("=", 1)[0].split()
        return len(leading) == 1 and leading[0] == key
    tokens = content.split()
    return bool(tokens) and tokens[0] == key


def _value_region(line: str) -> tuple[int, int]:
    """The `(start, comment_start)` slice of `line` holding the value — after the key/`=` and
    before any trailing comment. The span a case rewrite is allowed to touch."""
    comment_start = _find_comment_start(line)
    if comment_start == -1:
        comment_start = len(line)
    return _value_start(line, comment_start), comment_start


def _macro_def_line_with_token(lines: list[str], token: str) -> int | None:
    """The 1-based line of a `#define` whose macro *body* contains `token` as a whole word, or
    None. Lets a case rewrite follow a macro-supplied value (`Field = MACRO`) back to the
    `#define` that actually holds the miscased token, since the use site does not contain it.
    Only the `#define`'s own physical line is searched (the common single-line form)."""
    pattern = re.compile(rf"\b{re.escape(token)}\b")
    for number, line in enumerate(lines, start=1):
        content, _ = split_comment(line)
        match = _DEFINE_RE.match(content)
        if match is not None and pattern.search(match.group(1)):
            return number
    return None


def _token_in_value(line: str, token: str) -> bool:
    """Whether `token` appears as a whole word in `line`'s value region — i.e. the rewrite
    would actually find it there. Guards against a diagnostic whose span doesn't hold the
    token (a repeated field's earlier line, or a macro-supplied value)."""
    start, comment_start = _value_region(line)
    return re.search(rf"\b{re.escape(token)}\b", line[start:comment_start]) is not None


def _apply_replacements(line: str, replacements: list[tuple[str, str]]) -> str:
    """Rewrite miscased value tokens (an enum or a cross-reference) in `line`'s value,
    leaving key and comment."""
    start, comment_start = _value_region(line)
    region = line[start:comment_start]
    for given, canonical in replacements:
        region = re.sub(rf"\b{re.escape(given)}\b", canonical, region)
    return line[:start] + region + line[comment_start:]


def _value_start(line: str, comment_start: int) -> int:
    """Index where the value begins: after `=`, else after the first bare token."""
    equals = line.find("=")
    if equals != -1 and equals < comment_start:
        return equals + 1
    index = 0
    while index < len(line) and line[index].isspace():
        index += 1
    while index < len(line) and not line[index].isspace():
        index += 1
    return index
