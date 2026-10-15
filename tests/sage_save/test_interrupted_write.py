"""`find_interrupted_write` / `diagnose_container` on synthetic saves.

The engine writes a chunk's end offset only once the chunk is complete, so a save it aborted ends
inside the chunk it was writing with that offset still zero. These build that shape from a small
well-formed save rather than from a fixture, so they run in the data-free core suite.
"""

import struct

from sage_save import (
    Chunk,
    SaveFile,
    SaveHeader,
    diagnose_container,
    find_interrupted_write,
    write_save,
)
from sage_save.save import HEADER_SIZE, MAGIC_EALA, MAGIC_RTS


def _complete_save() -> bytes:
    chunks = [
        Chunk("CHUNK_LivingWorldLogic", bytes([6]) + b"\x11" * 40, 0),
        Chunk("CHUNK_Audio", bytes([4]) + b"\x22" * 12, 0),
        Chunk("CHUNK_GameLogic", bytes([8]) + b"\x33" * 64, 0),
    ]
    return write_save(SaveFile(SaveHeader(MAGIC_EALA, MAGIC_RTS, 1, 0), chunks))


def _chunk_offsets(data: bytes) -> list[int]:
    offsets, position = [], HEADER_SIZE
    while data[position + 1 : position + 1 + data[position]] != b"SG_EOF":
        offsets.append(position)
        name_end = position + 1 + data[position]
        (position,) = struct.unpack_from("<I", data, name_end + 4)
    return offsets


def _abort_inside(data: bytes, index: int, written: int) -> bytes:
    """`data` as the engine leaves it when the chunk at `index` fails after `written` payload
    bytes: earlier chunks intact, this one's end offset zero, nothing after."""
    start = _chunk_offsets(data)[index]
    name_end = start + 1 + data[start]
    payload_start = name_end + 8
    cut = bytearray(data[: payload_start + written])
    cut[name_end + 4 : name_end + 8] = b"\x00\x00\x00\x00"
    return bytes(cut)


def test_complete_save_is_not_an_interrupted_write():
    assert find_interrupted_write(_complete_save()) is None


def test_abort_in_the_first_chunk_names_it():
    found = find_interrupted_write(_abort_inside(_complete_save(), 0, 17))
    assert found is not None
    assert found.chunk == "CHUNK_LivingWorldLogic"
    assert found.written == 17
    assert found.completed == ()


def test_abort_later_keeps_the_completed_chunks():
    found = find_interrupted_write(_abort_inside(_complete_save(), 2, 5))
    assert found is not None
    assert found.chunk == "CHUNK_GameLogic"
    assert found.completed == ("CHUNK_LivingWorldLogic", "CHUNK_Audio")


def test_abort_between_chunks_has_no_chunk():
    data = _complete_save()
    found = find_interrupted_write(data[: _chunk_offsets(data)[2]])
    assert found is not None
    assert found.chunk is None
    assert found.completed == ("CHUNK_LivingWorldLogic", "CHUNK_Audio")


def test_other_damage_is_not_reported_as_an_interrupted_write():
    data = bytearray(_complete_save())
    start = _chunk_offsets(bytes(data))[1]
    data[start + 1 + data[start] : start + 1 + data[start] + 4] = b"XXXX"
    assert find_interrupted_write(bytes(data)) is None
    assert find_interrupted_write(b"not a save at all") is None


def test_diagnose_container_adds_the_interrupted_chunk():
    found = diagnose_container(_abort_inside(_complete_save(), 1, 3), "parse error")
    assert [d.category for d in found] == ["container", "interrupted-write"]
    assert all(d.severity == "fatal" for d in found)
    assert found[1].chunk == "CHUNK_Audio"


def test_diagnose_container_without_the_shape_reports_only_the_parse_error():
    found = diagnose_container(b"garbage", "parse error")
    assert [d.category for d in found] == ["container"]
