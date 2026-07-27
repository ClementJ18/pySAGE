"""Rename a definition - and every reference to it - across an assembled game.

A rename is a set of line-level token rewrites, never an AST reprint: the plan records which
physical lines may hold the old name and how much of each line a rewrite is allowed to touch,
and applying it swaps whole-word occurrences inside those regions only. Comments, layout and
encoding survive untouched, the same way `sage_lint.fixer` applies its fixes.

Three things carry a name, so each is planned separately:

* typed fields, walked through the same converter shapes `sage_lint.rules.references` walks (a
  bare `Reference`, a list/tuple/nullable of one, a `KeyedRecord`'s keys, and a field typed
  directly as a definition class), matched on both the resolved object and the raw name a
  dangling reference leaves behind;
* the digit-keyed slots of a block declaring `numbered_slots` (a `CommandSet`'s buttons), which
  no typed field carries;
* a `ChildObject`'s parent, which lives in the header label rather than in a field.

Names resolve case-insensitively in the engine, so matching is case-insensitive throughout: any
spelling of the old name in a slot typed for its table is the same symbol.

Whatever the typed model does not reach - a field the schema does not model, a declaration in a
file another file shadows - would leave a silent half-rename, so a caller is expected to finish
with `scan_text`. A header declaring the same name in the same table is folded into the plan (it
is unambiguously the same symbol); every other occurrence is reported for a human to judge.
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from sage_ini.model.game import Game
from sage_ini.model.ini_objects import ChildObject
from sage_ini.model.objects import REGISTRY, IniObject, resolve_annotation
from sage_ini.model.types import KeyedRecord, Reference
from sage_ini.parser.io import read_text_with_encoding, writeback_encoding
from sage_ini.parser.lexer import _find_comment_start, forget_path
from sage_ini.parser.location import Span
from sage_ini.walk import walk_objects

__all__ = [
    "Anchor",
    "RenamePlan",
    "RenameSite",
    "TextOccurrence",
    "apply_plan",
    "check_conflicts",
    "collect_sites",
    "dedupe_sites",
    "keywords_for_table",
    "scan_text",
    "valid_name",
]

# A definition name the engine can look up: one bareword. Whitespace would split it into two
# label tokens, and a comment marker or `=` would end the value before the name did.
_NAME_RE = re.compile(r"^[^\s;=]+$")

# The `#define NAME` prefix, up to (and including) the whitespace before the macro's body.
_DEFINE_PREFIX_RE = re.compile(r"^\s*#define\s+\S+\s+")


class Anchor(Enum):
    """Which part of a line a rewrite may touch. Every region stops at a trailing comment; the
    anchor says where it *starts*, so a rewrite cannot reach a key, a block keyword or a child's
    own name that happens to be spelled like the symbol being renamed."""

    VALUE = "value"  # after the field key, when the line leads with it
    HEADER_NAME = "header-name"  # after the block keyword: the declared name
    HEADER_PARENT = "header-parent"  # after the block keyword and the child's own name
    MACRO_BODY = "macro-body"  # after `#define NAME`
    FREE = "free"  # the whole of the line's content


@dataclass(frozen=True, slots=True)
class RenameSite:
    """One line a rewrite may touch, and why. `anchor_token` is whatever the anchor needs to
    locate its region - the field key, the block keyword, the macro name - and is unused for
    `Anchor.FREE`. `detail` is for the dry-run report, never for the rewrite."""

    file: str
    line: int
    anchor: Anchor
    anchor_token: str
    detail: str
    origin: str = "game"  # "game" or the map.ini path whose context found it


@dataclass(frozen=True, slots=True)
class TextOccurrence:
    """A whole-word hit on the old name that the typed plan does not account for - the residue
    of the safety-net scan, reported so a half-rename is visible rather than silent."""

    file: str
    line: int
    text: str


@dataclass
class RenamePlan:
    """Everything a rename would touch, plus everything it refuses to or cannot."""

    table: str
    old: str
    new: str
    sites: list[RenameSite] = field(default_factory=list)
    unaccounted: list[TextOccurrence] = field(default_factory=list)
    map_warnings: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    @property
    def files(self) -> list[str]:
        """The files the rename would rewrite, sorted."""
        return sorted({site.file for site in self.sites})

    def sites_by_file(self) -> dict[str, list[RenameSite]]:
        """The plan's sites grouped by file, each group in line order."""
        grouped: dict[str, list[RenameSite]] = defaultdict(list)
        for site in self.sites:
            grouped[site.file].append(site)
        for group in grouped.values():
            group.sort(key=lambda s: s.line)
        return dict(grouped)


def valid_name(name: str) -> bool:
    """Whether `name` is a name the engine could look up (one bareword, no comment marker)."""
    return bool(_NAME_RE.match(name)) and "//" not in name and "--" not in name


def keywords_for_table(table: str) -> frozenset[str]:
    """Every block keyword that declares into `table`. One table is often opened by more than
    one keyword (`Object`, `ChildObject` and `ObjectReskin` all register into `objects`), and a
    declaration this game did not load - one a higher-priority file shadows - can use any of
    them, so the text scan has to recognise the whole set."""
    return frozenset(
        name
        for name, cls in REGISTRY.items()
        if isinstance(cls, type) and issubclass(cls, IniObject) and cls.key == table
    )


def _iter_ref_names(value: object, converter: object) -> Iterator[tuple[str, str]]:
    """`(table_key, name)` for every cross-reference reachable through `value` given its
    resolved `converter`, whether or not it resolved.

    A reference that resolved is an `IniObject` and one that dangled is the leftover `str`
    (`sage_ini.model.types.Reference` passes an unknown name through), and a rename has to catch
    both: a name that dangles today is still the name the modder meant. The converter shapes are
    the ones `sage_lint.rules.references` walks, plus `inner` so a nullable slot is descended
    too."""
    if isinstance(converter, Reference):
        yield from _named(value, converter.key)
        return
    if isinstance(converter, type) and issubclass(converter, IniObject) and converter.key:
        # A field typed directly as a definition class names a value in that class's table.
        yield from _named(value, converter.key)
        return
    if isinstance(converter, type) and issubclass(converter, KeyedRecord):
        for record in value if isinstance(value, list) else [value]:
            if record is None:
                continue
            for key, annotation in converter._keyspec.items():
                yield from _resolved_refs(getattr(record, key, None), annotation)
        return
    for attr in ("element", "inner"):
        nested = getattr(converter, attr, None)
        if nested is not None:
            for item in value if isinstance(value, list) else [value]:
                yield from _resolved_refs(item, nested)
            return
    element_types = getattr(converter, "element_types", None)
    if element_types is not None and isinstance(value, (list, tuple)):
        # A tuple slot: each converted value is aligned to its element types, so a reference in
        # any slot (the object of a `Tuple[Object, Int]`) is reachable here.
        for slot, annotation in zip(value, element_types, strict=False):
            yield from _resolved_refs(slot, annotation)


def _resolved_refs(value: object, annotation: object) -> Iterator[tuple[str, str]]:
    """`_iter_ref_names` for a value whose annotation still needs resolving."""
    try:
        converter = resolve_annotation(annotation)
    except (KeyError, TypeError):
        return
    yield from _iter_ref_names(value, converter)


def _named(value: object, table_key: str) -> Iterator[tuple[str, str]]:
    """The name `value` holds for `table_key`, resolved (an object) or not (a bare string)."""
    if isinstance(value, str):
        yield table_key, value
    elif isinstance(value, IniObject) and isinstance(value.name, str):
        # The registered object's own table wins: a field typed for one table cannot hold an
        # object registered in another, but the object knows its table exactly.
        yield value.key or table_key, value.name


def _matches(name: str, old: str) -> bool:
    """Whether `name` is the symbol `old` names (the engine's case-insensitive match)."""
    return name.strip().lower() == old.strip().lower()


def _lines_of(span: Span | None, fallback: Span | None) -> Iterator[tuple[str, int]]:
    """`(file, line)` for every physical line a span covers, falling back to the block's span
    when a field recorded none. The lines are candidates only - the rewrite still has to find
    the whole-word token on one before it changes anything - so a fallback that covers a whole
    block is safe, just broader than needed."""
    chosen = span if span is not None else fallback
    if chosen is None:
        return
    for line in range(chosen.line_start, chosen.line_end + 1):
        yield chosen.file, line


def collect_sites(game: Game, table: str, old: str, *, origin: str = "game") -> list[RenameSite]:
    """Every line in `game` a rename of `table`/`old` would rewrite.

    `origin` labels where the sites came from, so a caller merging a map.ini context's sites into
    a whole-game plan can still tell them apart in the report."""
    sites: list[RenameSite] = []
    seen: set[tuple[str, int, Anchor]] = set()

    def add(file: str, line: int, anchor: Anchor, token: str, detail: str) -> None:
        key = (file, line, anchor)
        if key in seen:
            return
        seen.add(key)
        sites.append(RenameSite(file, line, anchor, token, detail, origin))

    for obj in walk_objects(game):
        fieldspec = type(obj)._fieldspec
        label = type(obj).__name__

        for key in obj.fields:
            if key not in fieldspec:
                continue  # an unmodelled field is the text scan's to report
            try:
                converter = resolve_annotation(fieldspec[key])
                value = getattr(obj, key)
            except (ValueError, KeyError, TypeError, IndexError):
                continue  # a bad value is the conversion pass's own diagnostic
            hit = any(
                table_key == table and _matches(name, old)
                for table_key, name in _iter_ref_names(value, converter)
            )
            if not hit:
                continue
            for span in obj.field_spans(key):
                for file, line in _lines_of(span, obj.span):
                    add(file, line, Anchor.VALUE, key, f"{label}.{key}")

        # Digit-keyed slots are dynamic, so no typed field carries them; a command set's buttons
        # are real references and have to move with the rename.
        if obj.numbered_slots and obj.numbered_slot_ref == table:
            for slot, name in obj.fields.items():
                if not slot.isdigit() or not isinstance(name, str) or not _matches(name, old):
                    continue
                for span in obj.field_spans(slot):
                    for file, line in _lines_of(span, obj.span):
                        add(file, line, Anchor.VALUE, slot, f"{label} slot {slot}")

        # A `ChildObject`'s parent is a reference written in the header label, past the child's
        # own name, so it is anchored differently from every field.
        if (
            table == "objects"
            and isinstance(obj, ChildObject)
            and isinstance(obj.parent_name, str)
            and _matches(obj.parent_name, old)
            and obj.span is not None
        ):
            add(obj.span.file, obj.span.line_start, Anchor.HEADER_PARENT, label, f"{label} parent")

    declared, _ = game.lookup(table, old)
    if declared is not None and declared.span is not None:
        add(
            declared.span.file,
            declared.span.line_start,
            Anchor.HEADER_NAME,
            type(declared).__name__,
            f"{type(declared).__name__} declaration",
        )

    # A macro body holding the name is how a field reaches it without spelling it out
    # (`Weapon = MY_WEAPON`), so the `#define` is where that reference actually lives.
    pattern = _word_re(old)
    for name, body in game.macros.items():
        if not pattern.search(body):
            continue
        span = game.macro_definitions.get(name)
        if span is not None:
            add(span.file, span.line_start, Anchor.MACRO_BODY, name, f"#define {name}")

    return sites


def dedupe_sites(groups: Iterable[Iterable[RenameSite]]) -> list[RenameSite]:
    """One flat, ordered site list from several collections, keeping the first of each
    `(file, line, anchor)`. Every map.ini is built against the same global game, so its context
    re-finds the global macros and declarations the whole-game pass already found; merging without
    this would rewrite the same line under several origins."""
    merged: dict[tuple[str, int, Anchor], RenameSite] = {}
    for group in groups:
        for site in group:
            merged.setdefault((str(Path(site.file)), site.line, site.anchor), site)
    return sorted(merged.values(), key=lambda s: (s.file, s.line, s.anchor.value))


def check_conflicts(
    game: Game, table: str, old: str, new: str, root: Path | None = None
) -> list[str]:
    """Reasons this rename must not proceed. A conflict is blocking: applying the plan anyway
    would merge two definitions, write a name the engine cannot read, or edit a file the caller
    does not own."""
    problems: list[str] = []
    if not valid_name(new):
        problems.append(f"{new!r} is not a usable definition name (one bareword, no `;`/`=`)")
    if _matches(new, old):
        problems.append(f"{new!r} and {old!r} are the same name to the engine")
    if table not in game.tables:
        problems.append(f"no {table!r} table in this game")
        return problems

    declared, _ = game.lookup(table, old)
    if declared is None:
        problems.append(f"no {table} definition named {old!r}")
    existing, canonical = game.lookup(table, new)
    if existing is not None:
        where = existing.span.file if existing.span is not None else "an unknown file"
        problems.append(
            f"{table} {canonical!r} already exists ({where}); renaming would merge them"
        )

    # A definition that lives outside the tree being renamed belongs to a base game or another
    # layer: rewriting it would edit data this run does not own, and renaming only the references
    # would break every one of them.
    if declared is not None and declared.span is not None and root is not None:
        try:
            Path(declared.span.file).resolve().relative_to(Path(root).resolve())
        except ValueError:
            problems.append(
                f"{table} {old!r} is declared outside the rename root, in "
                f"{declared.span.file} - rename it where it is defined"
            )
    return problems


def _word_re(name: str) -> re.Pattern[str]:
    """A case-insensitive whole-word matcher for `name`.

    `\\b` is wrong here: a definition name routinely holds characters Python calls
    non-word (`Command_Foo:Bar`, `GondorTower-Upgrade`), and a `\\b` next to one of those
    matches inside a longer token. The boundaries are instead "not one of the characters a
    bareword is made of", which is what the engine's own tokenizer splits on."""
    escaped = re.escape(name)
    return re.compile(rf"(?<![^\s=,:]){escaped}(?![^\s=,:])", re.IGNORECASE)


def _region(line: str, site: RenameSite) -> tuple[int, int]:
    """The `(start, end)` slice of `line` the site's rewrite may touch. Every region ends at a
    trailing comment; the anchor decides where it starts. A start the anchor cannot locate falls
    back to the content, which is never wider than the line itself."""
    end = _find_comment_start(line)
    if end == -1:
        end = len(line)
    content = line[:end]
    start = len(content) - len(content.lstrip())

    if site.anchor is Anchor.VALUE:
        # Only skip the leading token when it really is this field's key: a continuation line of
        # a multi-line value leads with the value itself, and skipping that would miss it.
        match = re.match(r"(\s*)(\S+)(\s*=\s*|\s+)", content)
        if match is not None and match.group(2).lower() == site.anchor_token.lower():
            return match.end(), end
    elif site.anchor is Anchor.HEADER_NAME:
        match = re.match(rf"\s*{re.escape(site.anchor_token)}\s*=?\s*", content, re.IGNORECASE)
        if match is not None:
            return match.end(), end
    elif site.anchor is Anchor.HEADER_PARENT:
        # Past the keyword *and* the child's own name, so renaming a parent cannot touch a child
        # that happens to share the old name's spelling.
        match = re.match(rf"\s*{re.escape(site.anchor_token)}\s+\S+\s+", content, re.IGNORECASE)
        if match is not None:
            return match.end(), end
    elif site.anchor is Anchor.MACRO_BODY:
        match = _DEFINE_PREFIX_RE.match(content)
        if match is not None:
            return match.end(), end
    return start, end


def _rewrite_line(line: str, sites: list[RenameSite], pattern: re.Pattern[str], new: str) -> str:
    """Rewrite every whole-word occurrence of the old name inside the union of `sites`' regions.

    One line can be several sites at once (two fields sharing it, a declaration that is also a
    macro body); the union of their regions is still bounded by the narrowest thing every anchor
    agrees on - the line's content, minus its comment."""
    regions = [_region(line, site) for site in sites]
    start = min(region[0] for region in regions)
    end = max(region[1] for region in regions)
    if start >= end:
        return line
    return line[:start] + pattern.sub(new, line[start:end]) + line[end:]


def apply_plan(plan: RenamePlan) -> dict[str, int]:
    """Rewrite every file the plan touches; return the per-file count of lines changed.

    Edits are computed against the original line numbering and applied in one pass per file, so
    nothing shifts underneath them. A file whose lines all turn out not to hold the token is left
    alone - the plan's lines are candidates, and the whole-word match is the real filter."""
    pattern = _word_re(plan.old)
    changed: dict[str, int] = {}
    for path, sites in plan.sites_by_file().items():
        by_line: dict[int, list[RenameSite]] = defaultdict(list)
        for site in sites:
            by_line[site.line].append(site)
        try:
            text, encoding = read_text_with_encoding(path)
        except OSError:
            continue
        encoding = writeback_encoding(path, encoding)
        newline = "\r\n" if "\r\n" in text else "\n"
        lines = text.replace("\r\n", "\n").split("\n")

        count = 0
        for number, line_sites in by_line.items():
            if not 1 <= number <= len(lines):
                continue
            rewritten = _rewrite_line(lines[number - 1], line_sites, pattern, plan.new)
            if rewritten != lines[number - 1]:
                lines[number - 1] = rewritten
                count += 1
        if not count:
            continue
        Path(path).write_text(
            "\n".join(lines).replace("\n", newline), encoding=encoding, newline=""
        )
        # Drop the tokenizer's cached copy: a same-length rename keeps the file's size, and a
        # rewrite inside one mtime tick keeps its mtime, so the cache's (mtime, size) signature
        # would otherwise serve the pre-rename lines to the next load.
        forget_path(path)
        changed[path] = count
    return changed


def scan_text(
    paths: Iterable[Path], table: str, old: str, accounted: Iterable[RenameSite]
) -> tuple[list[RenameSite], list[TextOccurrence]]:
    """Read every file in `paths` and account for each whole-word hit on `old`.

    Returns `(promoted, unaccounted)`. A hit on a header line declaring `old` into `table` is
    *promoted* into the plan: it is unambiguously the same symbol, and it is exactly what the
    typed model cannot see, since only the winning declaration of a name is registered in the
    game. Every other unaccounted hit is returned for a human to judge - it may be an unmodelled
    field holding a real reference, a same-spelled name in another table, or prose in a comment.
    """
    known = {(str(Path(site.file)), site.line) for site in accounted}
    pattern = _word_re(old)
    header_re = re.compile(
        rf"^\s*(?:{'|'.join(sorted(re.escape(k) for k in keywords_for_table(table)))})"
        rf"\s*=?\s*{re.escape(old)}(?![^\s=,:])",
        re.IGNORECASE,
    )
    promoted: list[RenameSite] = []
    unaccounted: list[TextOccurrence] = []
    for path in paths:
        try:
            text, _ = read_text_with_encoding(path)
        except OSError:
            continue
        if not pattern.search(text):
            continue
        for number, line in enumerate(text.replace("\r\n", "\n").split("\n"), start=1):
            end = _find_comment_start(line)
            content = line if end == -1 else line[:end]
            if not pattern.search(content):
                continue
            if (str(path), number) in known:
                continue
            match = header_re.match(content)
            if match is not None:
                keyword = content.split()[0]
                promoted.append(
                    RenameSite(
                        str(path),
                        number,
                        Anchor.HEADER_NAME,
                        keyword,
                        f"{keyword} declaration (shadowed)",
                        origin="text-scan",
                    )
                )
                continue
            unaccounted.append(TextOccurrence(str(path), number, line.strip()))
    return promoted, unaccounted
