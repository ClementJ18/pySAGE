"""`ReplayTail` against a fixture replay written out a piece at a time, the way the recorder
grows the file during a match, and `ReplayChunk.is_action`."""

from collections import Counter
from pathlib import Path

import pytest

from sage_replay import Bfme2OrderType, Order, ReplayChunk, ReplayTail, parse_replay

FIXTURES = Path(__file__).parent / "fixtures"
REPLAY_PATH = FIXTURES / "4.8.2 Angmar vs Isengard (Dyastro) epic.BfME2Replay"


@pytest.fixture(scope="module")
def data() -> bytes:
    return REPLAY_PATH.read_bytes()


def _chunk(order_type: int) -> ReplayChunk:
    return ReplayChunk(timecode=0, order_type=order_type, number=3, order=Order(2, order_type))


def test_a_file_read_in_pieces_gives_every_chunk_once(tmp_path, data):
    whole = parse_replay(data)
    live = tmp_path / "Last Replay.BfME2Replay"
    tail = ReplayTail(live)
    seen = []
    # Odd step sizes, so the cuts land inside the header and inside chunks.
    for end in (*range(0, len(data), 7919), len(data)):
        live.write_bytes(data[:end])
        read = tail.poll()
        assert not read.restarted
        seen.extend(read.chunks)
    assert tail.header is not None
    assert tail.header.metadata.map_file == whole.header.metadata.map_file
    assert [(c.timecode, c.order_type, c.number) for c in seen] == [
        (c.timecode, c.order_type, c.number) for c in whole.chunks
    ]
    assert tail.chunks == seen
    assert tail.offset == len(data)


def test_a_partial_header_reads_as_nothing_yet(tmp_path, data):
    live = tmp_path / "Last Replay.BfME2Replay"
    live.write_bytes(data[:40])
    read = ReplayTail(live).poll()
    assert read.header is None
    assert read.chunks == ()


def test_a_missing_file_reads_as_nothing(tmp_path):
    read = ReplayTail(tmp_path / "absent.BfME2Replay").poll()
    assert read.header is None
    assert read.chunks == ()


def test_a_file_that_shrinks_is_a_new_recording(tmp_path, data):
    live = tmp_path / "Last Replay.BfME2Replay"
    live.write_bytes(data)
    tail = ReplayTail(live)
    first = tail.poll()
    live.write_bytes(data[: len(data) // 2])
    second = tail.poll()
    assert second.restarted
    assert second.header is not None
    assert 0 < len(second.chunks) < len(first.chunks)
    assert tail.chunks == list(second.chunks)


def test_is_action_counts_player_orders_only():
    assert _chunk(Bfme2OrderType.Select).is_action
    assert _chunk(Bfme2OrderType.GroundMove).is_action
    assert _chunk(Bfme2OrderType.SpecialPowerAtLocation).is_action
    for engine in (
        Bfme2OrderType.EndOfRecording,
        Bfme2OrderType.ChecksumHeartbeat,
        Bfme2OrderType.Handshake,
        Bfme2OrderType.ModalBracket,
        Bfme2OrderType.LeaveGame,
        Bfme2OrderType.GameOutcome,
        Bfme2OrderType.PlayerScore,
    ):
        assert not _chunk(engine).is_action


def test_both_players_of_the_fixture_act(data):
    replay = parse_replay(data)
    actions = Counter(replay.slot_index(c) for c in replay.chunks if c.is_action)
    assert actions[0] > 0
    assert actions[1] > 0
    assert None not in actions
