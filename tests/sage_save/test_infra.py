"""Step 0 infrastructure: the decoder registry, the coverage report, and the reversing aids.

The registry test is the payoff of `CHUNK_CODECS` — one parametrized case round-trips every
registered encoder over every fixture, so a new decoder is regression-tested for free. Coverage
and the reversing helpers (`nested_block_tree`, `first_difference`) get focused tests, mostly on
synthetic bytes so they don't depend on which fixtures are present."""

import struct
from pathlib import Path

import pytest

from sage_save import (
    CHUNK_CODECS,
    chunk_coverage,
    coverage_summary,
    first_difference,
    format_block_tree,
    format_divergence,
    nested_block_tree,
    parse_save_from_path,
)
from sage_save.save import BLOCK_MARKER
from tests.sage_save.corpus import ALL_SAVES as SAVE_FILES
from tests.sage_save.corpus import FIXTURES, fixture_id

SKIRMISH = FIXTURES / "Saved Game 1.BfME2Skirmish"


def _require(path: Path) -> Path:
    if not path.is_file():
        pytest.skip(f"fixture save not present: {path.name}")
    return path


# --- the decoder registry ---


def test_registry_membership():
    # 4 core + 9 Step-1 small chunks + TacticalView + TeamFactory + GameClient + ScriptEngine
    # + Players.
    assert len(CHUNK_CODECS) == 18
    assert {
        "CHUNK_GameState",
        "CHUNK_GameStateMap",
        "CHUNK_Campaign",
        "CHUNK_GameLogic",
        "CHUNK_GameClient",
        "CHUNK_Players",
        "CHUNK_ScriptEngine",
        "CHUNK_TacticalView",
        "CHUNK_TeamFactory",
    } <= set(CHUNK_CODECS)
    # every registered codec now carries an exact-inverse encoder — including GameLogic and
    # GameClient, whose object/drawable bodies stay opaque but round-trip verbatim (their KOLB
    # end-offsets are recomputed from each object's stored body offset)
    assert all(codec.encode is not None for codec in CHUNK_CODECS.values())


# One case per (fixture, encoder-carrying chunk): the encoder is an exact inverse of the decoder.
_ROUND_TRIP = [
    (path, name)
    for path in SAVE_FILES
    for name, codec in CHUNK_CODECS.items()
    if codec.encode is not None
]


@pytest.mark.parametrize(
    "save_path,chunk_name",
    _ROUND_TRIP,
    ids=[f"{fixture_id(p)}-{n}" for p, n in _ROUND_TRIP],
)
def test_registered_codec_round_trips(save_path, chunk_name):
    save = parse_save_from_path(_require(save_path))
    chunk = save.chunk(chunk_name)
    if chunk is None:
        pytest.skip(f"{save_path.name} has no {chunk_name}")
    codec = CHUNK_CODECS[chunk_name]
    assert codec.encode(codec.decode(chunk), chunk.payload) == chunk.payload


# --- coverage report ---


def test_coverage_rows_partition_each_payload():
    save = parse_save_from_path(_require(SKIRMISH))
    rows = chunk_coverage(save)
    assert len(rows) == len(save.chunks)
    for row in rows:
        # decoded + opaque always accounts for the whole payload
        assert row.decoded_bytes + row.opaque_bytes == row.size
        if row.name in CHUNK_CODECS:
            assert row.status in ("decoded", "partial")
        else:
            assert row.status == "opaque"
            assert row.decoded_bytes == 0


def test_coverage_summary_counts_decoded_chunks():
    save = parse_save_from_path(_require(SKIRMISH))
    summary = coverage_summary(save)
    assert summary.chunks_total == 32
    # 4 core + 9 small + TacticalView + TeamFactory + GameClient + ScriptEngine + Players
    assert summary.chunks_decoded == 18
    assert 0 < summary.bytes_decoded < summary.bytes_total
    assert 0.0 < summary.byte_fraction < 1.0
    by_name = {row.name: row for row in chunk_coverage(save)}
    # a skirmish Campaign is fully decoded (empty roster → nothing opaque)
    assert by_name["CHUNK_Campaign"].status == "decoded"
    # GameStateMap keeps its trailing id counters opaque → partial
    assert by_name["CHUNK_GameStateMap"].status == "partial"


# --- reversing aids: nested_block_tree ---


def _kolb(name: bytes | None, end_absolute: int) -> bytes:
    """A KOLB block header: optional `uint8 len + name`, the marker, and the absolute end offset."""
    prefix = bytes([len(name)]) + name if name is not None else b""
    return prefix + BLOCK_MARKER + struct.pack("<I", end_absolute)


def test_nested_block_tree_names_and_nesting():
    base = 0x100  # payload[0] sits at this absolute file offset
    # An outer named block whose body is a second named block plus a 4-byte tail. Both end at the
    # payload end (payload-relative 29); the KOLB end offsets are stored absolute (base + 29).
    inner = _kolb(b"IN", base + 29) + b"\xaa\xbb\xcc\xdd"
    payload = _kolb(b"OUTER", base + 29) + inner
    assert len(payload) == 29  # 14-byte OUTER header + 11-byte IN header + 4-byte body

    blocks = nested_block_tree(payload, base)
    assert [(b.name, b.depth) for b in blocks] == [("OUTER", 0), ("IN", 1)]
    assert blocks[1].size == 4  # the inner body is the four AA BB CC DD bytes


def test_nested_block_tree_rejects_out_of_range_marker():
    # A stray "KOLB" whose following u32 is not a plausible end offset is not treated as a block.
    payload = b"\x00\x00" + BLOCK_MARKER + struct.pack("<I", 0xFFFFFFFF)
    assert nested_block_tree(payload, 0) == []


def test_nested_block_tree_on_real_game_state_map():
    save = parse_save_from_path(_require(SKIRMISH))
    chunk = save.chunk("CHUNK_GameStateMap")
    blocks = nested_block_tree(chunk.payload, chunk.payload_offset)
    # the embedded map is a single unnamed top-level block holding the bulk of the payload
    assert len(blocks) == 1
    assert blocks[0].name is None
    assert blocks[0].depth == 0
    assert blocks[0].size > len(chunk.payload) // 2


def test_nested_block_tree_on_real_game_logic_has_nested_modules():
    save = parse_save_from_path(_require(SKIRMISH))
    chunk = save.chunk("CHUNK_GameLogic")
    blocks = nested_block_tree(chunk.payload, chunk.payload_offset)
    # object bodies are top-level KOLB blocks; each holds nested ModuleTag_* blocks (depth ≥ 1)
    assert any(b.depth == 0 for b in blocks)
    assert any(b.depth >= 1 and (b.name or "").startswith("ModuleTag_") for b in blocks)
    lines = format_block_tree(blocks, limit=5)
    assert len(lines) == 6  # 5 blocks + the "... N more" line
    assert lines[-1].startswith("...")


# --- reversing aids: first_difference / format_divergence ---


def test_first_difference():
    assert first_difference(b"abc", b"abc") is None
    assert first_difference(b"abc", b"abx") == 2
    assert first_difference(b"abc", b"abcd") == 3  # a is a prefix of b → the shorter length
    assert first_difference(b"abcd", b"abc") == 3


def test_format_divergence_reports_offset_and_windows():
    a = bytes(range(32))
    b = bytes(range(32))
    b = b[:20] + b"\xff" + b[21:]
    lines = format_divergence(a, b, first_difference(a, b))
    assert "byte 20" in lines[0]
    assert lines[2].startswith("  A:") and lines[3].startswith("  B:")
