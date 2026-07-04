"""Corpus-wide acceptance gates (PLAN.md scoreboard).

Each phase strengthens the assertions here:
- Phase 0: every file reads with a supported encoding.
- Phase 1: every file tokenizes / block-parses / round-trips.
- Phase 2: typed layer converts without unhandled errors.

Block structure is a property of fully include-expanded root files (a block
may open in one file and close in an included one), so the balance gate runs
over `corpus_root_file`; tokenize/round-trip gates run over every file.
"""

from pathlib import Path

import pytest

from sage_ini.model.game import Game
from sage_ini.model.objects import get_class
from sage_ini.parser.ast import Block, line_count
from sage_ini.parser.blockparser import parse, parse_file
from sage_ini.parser.io import ENCODINGS, read_text_with_encoding
from sage_ini.parser.lexer import COMMENT_MARKERS, tokenize
from sage_ini.parser.printer import print_document

# Corpus acceptance gates are the full-suite regression net (run with --full),
# not the inner-loop core suite.
pytestmark = pytest.mark.full

# Block types whose typed construction the Phase 2.1 gate exercises.
GATE_TYPES = ("Object", "ChildObject", "Weapon")

# Diagnostics that mean the parser mis-structured the file — its own
# correctness claim, which must be zero on real game data.
STRUCTURAL_CODES = frozenset({"stray-end", "unclosed-block", "unclosed-script"})

# Diagnostics about missing or cyclic include files: a data-completeness gap
# in a given corpus pairing (e.g. a mod whose anim .inc files are absent), not
# a parse failure. Absent content could itself contain block opens/closes, so
# structural balance is unverifiable for such a file — recorded, not asserted.
ENVIRONMENTAL_CODES = frozenset({"unresolved-include", "include-cycle"})


def test_reads_with_supported_encoding(corpus_file: Path):
    text, encoding = read_text_with_encoding(corpus_file)

    assert isinstance(text, str)
    assert encoding in ENCODINGS


def test_tokenizes(corpus_file: Path):
    text = read_text_with_encoding(corpus_file)[0]

    lines = tokenize(text, file=str(corpus_file))

    assert len(lines) == len(text.splitlines())
    for line in lines:
        # no comment marker may survive in content
        for marker in COMMENT_MARKERS:
            assert marker not in line.content, f"{line.span}: {marker!r} in {line.content!r}"
        # content and comment are both recoverable slices of the raw line
        assert line.content in line.raw, str(line.span)
        if line.comment is not None:
            assert line.comment in line.raw, str(line.span)
            assert line.comment[0] in ";/-", str(line.span)


def test_block_parses_with_includes_expanded(corpus_root_file: Path, include_layers_of):
    result = parse_file(
        corpus_root_file,
        resolve_includes=True,
        include_layers=include_layers_of(corpus_root_file),
    )

    codes = [d.code for d in result.diagnostics]
    if any(code in ENVIRONMENTAL_CODES for code in codes):
        # missing/cyclic include in this corpus pairing: the absent content
        # could contain block opens/closes, so balance is unverifiable here
        return

    # with every include resolved, a root file must parse perfectly clean
    assert not codes, "\n".join(str(d) for d in result.diagnostics)


def test_round_trips(corpus_file: Path):
    first = parse_file(corpus_file)
    printed = print_document(first.document)
    second = parse(printed, file="reprint")

    assert first.document.children == second.document.children

    if not first.diagnostics:
        # nothing vanished: the tree accounts for at least every non-blank
        # line (combined statements like `End StateName = X` count twice)
        text = read_text_with_encoding(corpus_file)[0]
        non_blank = sum(1 for line in tokenize(text, file=str(corpus_file)) if not line.is_blank)
        assert line_count(first.document.children) >= non_blank


def test_typed_objects_construct(corpus_root_file: Path, include_layers_of):
    result = parse_file(
        corpus_root_file,
        resolve_includes=True,
        include_layers=include_layers_of(corpus_root_file),
    )
    if any(d.code in ENVIRONMENTAL_CODES for d in result.diagnostics):
        return

    # Every Object / ChildObject / Weapon block (and the behaviors, draws and
    # nuggets nested within, recursively) must build a typed instance without
    # raising. Construction stores raw values; conversion stays lazy.
    game = Game()
    for node in result.document.children:
        if isinstance(node, Block) and node.name in GATE_TYPES:
            cls = get_class(node.name)
            try:
                cls.from_block(game, node)
            except Exception as exc:  # noqa: BLE001 - surface which block/file failed
                raise AssertionError(f"{node.name} {node.label} @ {node.span}: {exc!r}") from exc


def test_fields_convert_or_diagnose(corpus_root_file: Path, include_layers_of):
    result = parse_file(
        corpus_root_file,
        resolve_includes=True,
        include_layers=include_layers_of(corpus_root_file),
    )
    if any(d.code in ENVIRONMENTAL_CODES for d in result.diagnostics):
        return

    # Driving conversion of every annotated field across a whole game must
    # never raise: a bad value (unresolved macro, dangling cross-reference,
    # malformed number) is recorded as a diagnostic, not an exception.
    game = Game()
    try:
        game.load_document(result.document)
        game.validate()
    except Exception as exc:  # noqa: BLE001 - the gate is "no unhandled exception"
        raise AssertionError(f"{corpus_root_file}: {exc!r}") from exc
