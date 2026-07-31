"""BridgeBackend: argument marshalling, the ready-flag protocol, and the contract between
the writer here and the cave in `sage_patch.patches.live_bridge`.

The two halves are separate modules that must agree on a byte layout, so the invariants
between them are asserted here rather than trusted.
"""

from __future__ import annotations

import struct

import pytest

from sage_live.bridge import (
    IMAGE_BASE,
    BridgeBackend,
    BridgeUnavailable,
    encode_argument,
    encode_order,
    find_section,
)
from sage_live.identity import ROTWK_201_TIMESTAMP
from sage_live.memory import MemoryBackend
from sage_patch.patches.live_bridge import (
    ARG_COUNT_OFF,
    ARG_STRIDE,
    ARGS_OFF,
    BY_POINTER,
    CODE_OFF,
    MAX_ARGS,
    ORDER_TYPE_OFF,
    READY_OFF,
    SECTION_NAME,
    build_section,
)
from sage_replay.replay import Order, OrderArgument, OrderArgumentType
from tests.sage_live.test_memory import HEAP, FakeImage, build_game

SECTION_VA = HEAP + 0x38000
SECTION_SIZE = 0x400


class WritableImage(FakeImage):
    """The fake process image, plus the `.livebrg` section a patched game carries."""

    def __init__(self, section: bool = True) -> None:
        super().__init__()
        self.writes: list[tuple[int, bytes]] = []
        self.auto_acknowledge = True
        if section:
            # A patch announces itself by appending a section; the header it appends to is the
            # one every image already has, so this adds to it rather than replacing it.
            self.pe_headers(
                ROTWK_201_TIMESTAMP, [(SECTION_NAME, SECTION_VA - IMAGE_BASE, SECTION_SIZE)]
            )

    def write_memory(self, address: int, data: bytes) -> bool:
        self.writes.append((address, data))
        self.write(address, data)
        # Stand in for the hook: consume the order as soon as it is published.
        if self.auto_acknowledge and address == SECTION_VA + READY_OFF:
            self.write(SECTION_VA + READY_OFF, b"\x00\x00\x00\x00")
        return True


class Source:
    """Adapts WritableImage to the read/write source protocol."""

    def __init__(self, img: WritableImage) -> None:
        self.img = img

    def read(self, address: int, size: int) -> bytes | None:
        return self.img.read(address, size)

    def write(self, address: int, data: bytes) -> bool:
        return self.img.write_memory(address, data)

    def close(self) -> None:
        self.img.close()


def make_image(section: bool = True) -> WritableImage:
    img = WritableImage(section)
    # reuse the populated game state so observation still works
    src = build_game()
    img.static[:] = src.static
    img.heap[:] = src.heap
    img.write(SECTION_VA, build_section(SECTION_VA)[:CODE_OFF])
    return img


def make_backend(img: WritableImage) -> BridgeBackend:
    backend = BridgeBackend(Source(img))
    backend.connect()
    return backend


def test_the_writer_and_the_cave_agree_on_the_buffer_layout():
    """These two modules are compiled apart; a silent divergence would corrupt orders."""
    assert ARG_COUNT_OFF == ORDER_TYPE_OFF + 4
    assert ARGS_OFF == ORDER_TYPE_OFF + 12
    assert ARG_STRIDE == 20
    assert set(BY_POINTER) == {
        int(OrderArgumentType.Position),
        int(OrderArgumentType.ScreenPosition),
        int(OrderArgumentType.ScreenRectangle),
        int(OrderArgumentType.WideChar),
    }


def test_an_argument_record_is_a_tag_and_four_slots():
    raw = encode_argument(OrderArgumentType.Integer, 7)
    assert len(raw) == ARG_STRIDE
    assert struct.unpack("<5I", raw) == (0, 7, 0, 0, 0)


def test_float_arguments_carry_their_bit_pattern():
    raw = encode_argument(OrderArgumentType.Float, 0.849)
    tag, bits = struct.unpack_from("<II", raw)
    assert tag == OrderArgumentType.Float
    assert struct.unpack("<f", struct.pack("<I", bits))[0] == pytest.approx(0.849)


def test_position_lays_three_floats_across_the_slots():
    raw = encode_argument(OrderArgumentType.Position, (1200.0, 880.0, 61.0))
    tag, *slots = struct.unpack("<5I", raw)
    assert tag == OrderArgumentType.Position
    xyz = [struct.unpack("<f", struct.pack("<I", s))[0] for s in slots[:3]]
    assert xyz == pytest.approx([1200.0, 880.0, 61.0])
    assert slots[3] == 0


def test_screen_rectangle_uses_all_four_slots():
    raw = encode_argument(OrderArgumentType.ScreenRectangle, (1, 2, 3, 4))
    assert struct.unpack("<5I", raw) == (8, 1, 2, 3, 4)


@pytest.mark.parametrize(
    ("argument_type", "value"),
    [
        (OrderArgumentType.Position, (1.0, 2.0)),
        (OrderArgumentType.ScreenPosition, (1, 2, 3)),
        (OrderArgumentType.ScreenRectangle, (1, 2)),
    ],
)
def test_a_wrong_shaped_structure_is_refused(argument_type, value):
    with pytest.raises(ValueError):
        encode_argument(argument_type, value)


def test_encode_order_writes_type_count_then_arguments():
    order = Order(
        3,
        0x42F,
        [OrderArgument(OrderArgumentType.Position, (10.0, 20.0, 30.0))],
    )
    payload = encode_order(order)
    order_type, count, _reserved = struct.unpack_from("<III", payload)
    assert order_type == 0x42F
    assert count == 1
    assert len(payload) == 12 + ARG_STRIDE


def test_too_many_arguments_is_refused_before_anything_is_written():
    order = Order(
        0, 0x3E9, [OrderArgument(OrderArgumentType.ObjectId, i) for i in range(MAX_ARGS + 1)]
    )
    with pytest.raises(ValueError, match="exceeds"):
        encode_order(order)


def test_connect_refuses_an_unpatched_game():
    img = make_image(section=False)
    with pytest.raises(BridgeUnavailable, match=SECTION_NAME):
        BridgeBackend(Source(img)).connect()


def test_find_section_locates_the_command_buffer():
    img = make_image()
    located = find_section(Source(img))
    assert located == (SECTION_VA, SECTION_SIZE)


def test_the_patch_does_not_change_what_build_this_is():
    """Appending a cave bumps `NumberOfSections` and `SizeOfImage` and leaves the COFF header
    alone, which is why the timestamp identifies a build whether or not it is patched - and it
    has to, because the writable path only ever runs against a patched binary."""
    backend = make_backend(make_image())
    identity = backend.identity
    assert identity is not None
    assert identity.timestamp == ROTWK_201_TIMESTAMP
    assert identity.carries(SECTION_NAME)


def test_send_publishes_the_payload_before_the_ready_flag():
    """The flag is what makes the record visible; writing it first would race the hook."""
    img = make_image()
    backend = make_backend(img)
    order = Order(3, 0x42F, [OrderArgument(OrderArgumentType.Position, (5.0, 6.0, 7.0))])
    assert backend.send([order]) == 1

    addresses = [a for a, _ in img.writes]
    assert addresses == [SECTION_VA + ORDER_TYPE_OFF, SECTION_VA + READY_OFF]
    assert img.writes[-1][1] == struct.pack("<I", 1)


def test_a_sent_order_lands_in_the_buffer_verbatim():
    img = make_image()
    img.auto_acknowledge = False
    backend = make_backend(img)
    order = Order(3, 0x417, [OrderArgument(OrderArgumentType.Integer, 4242)])
    assert backend.send([order]) == 1

    raw = img.read(SECTION_VA, ARGS_OFF + ARG_STRIDE)
    assert struct.unpack_from("<I", raw, READY_OFF)[0] == 1
    assert struct.unpack_from("<I", raw, ORDER_TYPE_OFF)[0] == 0x417
    assert struct.unpack_from("<I", raw, ARG_COUNT_OFF)[0] == 1
    assert struct.unpack_from("<5I", raw, ARGS_OFF) == (0, 4242, 0, 0, 0)


def test_send_stops_when_the_hook_never_acknowledges():
    img = make_image()
    img.auto_acknowledge = False
    backend = make_backend(img)
    img.write(SECTION_VA + READY_OFF, struct.pack("<I", 1))  # a stuck pending order
    order = Order(3, 0x435, [])
    assert backend.send([order]) == 0
    assert any("did not consume" in d.message for d in backend.diagnostics)


def test_pending_reports_the_handshake_slot():
    img = make_image()
    img.auto_acknowledge = False
    backend = make_backend(img)
    assert not backend.pending
    backend.send([Order(3, 0x435, [])])
    assert backend.pending, "the hook has not consumed it yet"
    img.write(SECTION_VA + READY_OFF, struct.pack("<I", 0))  # the hook consumes it
    assert not backend.pending


def test_pending_is_false_before_connect_rather_than_raising():
    """A caller polling an unconnected bridge gets an answer, not an AttributeError."""
    assert not BridgeBackend(Source(make_image())).pending


def test_wait_until_idle_returns_false_when_the_hook_is_dead():
    img = make_image()
    img.auto_acknowledge = False
    backend = make_backend(img)
    img.write(SECTION_VA + READY_OFF, struct.pack("<I", 1))
    assert not backend.wait_until_idle(timeout=0.05)


def test_wait_until_idle_returns_true_once_consumed():
    backend = make_backend(make_image())  # auto_acknowledge clears the flag on read
    assert backend.wait_until_idle(timeout=0.5)


def test_send_before_connect_is_a_diagnostic():
    backend = BridgeBackend(Source(make_image()))
    assert backend.send([Order(0, 0x435, [])]) == 0
    assert any("before connect" in d.message for d in backend.diagnostics)


def test_the_bridge_still_observes_like_a_memory_backend():
    backend = make_backend(make_image())
    assert isinstance(backend, MemoryBackend)
    observation = backend.observe()
    assert observation.frame == 8688
    assert {p.name for p in observation.players} == {"PlyrCreeps", "Player_1"}
    assert len(observation.objects) == 4
