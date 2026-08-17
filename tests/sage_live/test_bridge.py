"""BridgeBackend: argument marshalling, the ready-flag protocol, and the contract between
the writer here and the cave in `sage_patch.patches.experimental.live_bridge`.

The two halves are separate modules that must agree on a byte layout, so the invariants
between them are asserted here rather than trusted.
"""

from __future__ import annotations

import struct

import pytest

from sage_live.api.camera import ViewLocation
from sage_live.backends.bridge import (
    IMAGE_BASE,
    BridgeBackend,
    BridgeUnavailable,
    decode_view_location,
    encode_argument,
    encode_order,
    encode_view_location,
    find_section,
)
from sage_live.backends.identity import ROTWK_201_TIMESTAMP
from sage_live.backends.memory import MemoryBackend
from sage_patch.addresses import THE_TACTICAL_VIEW, VIEW_LOCATION_SIZE, VIEW_POSITION_OFFSET
from sage_patch.patches.experimental.live_bridge import (
    ARG_COUNT_OFF,
    ARG_STRIDE,
    ARGS_OFF,
    BUFFER_TAG,
    BY_POINTER,
    CAMERA_APPLY,
    CAMERA_CAPTURE,
    CAMERA_OFF,
    CODE_OFF,
    LOCATION_OFF,
    MAX_ARGS,
    ORDER_TYPE_OFF,
    READY_OFF,
    SECTION_NAME,
    TAG_OFF,
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
        # What the stand-in view is holding, so a capture has something to answer with and an
        # apply has somewhere to land.
        self.view = ViewLocation(position=(1200.0, 880.0, 20.0), angle=0.75, pitch=1.25, zoom=1.5)
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
        if not self.auto_acknowledge:
            return True
        if address == SECTION_VA + READY_OFF:
            self.write(SECTION_VA + READY_OFF, b"\x00\x00\x00\x00")
        if address == SECTION_VA + CAMERA_OFF:
            self._serve_camera(struct.unpack("<I", data)[0])
        return True

    def _serve_camera(self, command: int) -> None:
        """What the cave does with a camera command, in Python: one direction or the other,
        then the flag cleared last."""
        if command == CAMERA_CAPTURE:
            self.write(SECTION_VA + LOCATION_OFF, encode_view_location(self.view))
        elif command == CAMERA_APPLY:
            applied = decode_view_location(self.read(SECTION_VA + LOCATION_OFF, VIEW_LOCATION_SIZE))
            if applied is not None:
                self.view = applied
        self.write(SECTION_VA + CAMERA_OFF, b"\x00\x00\x00\x00")


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


def test_a_view_location_is_a_flag_a_coord3d_and_four_scalars():
    raw = encode_view_location(ViewLocation((1.0, 2.0, 3.0), angle=4.0, pitch=5.0, zoom=6.0))
    assert len(raw) == VIEW_LOCATION_SIZE
    assert struct.unpack("<I7f", raw) == (1, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 0.0)


def test_a_view_location_round_trips():
    location = ViewLocation((1200.5, 880.25, 61.0), angle=0.5, pitch=1.25, zoom=2.25, extra=3.5)
    assert decode_view_location(encode_view_location(location)) == location


def test_an_invalid_or_short_location_decodes_to_none_rather_than_raising():
    """`setLocation` ignores a location whose flag is clear, so reading one back as a
    placement would report a camera that is not there."""
    assert decode_view_location(encode_view_location(ViewLocation(valid=False))) is None
    assert decode_view_location(b"\x01\x00\x00\x00") is None
    assert decode_view_location(None) is None


def test_capture_camera_reads_the_live_view():
    img = make_image()
    backend = make_backend(img)
    assert backend.capture_camera() == img.view


def test_set_camera_publishes_the_location_before_the_command():
    """Same rule as an order: the flag is what makes the record visible."""
    img = make_image()
    backend = make_backend(img)
    img.writes.clear()
    wanted = ViewLocation((300.0, 400.0, 0.0), angle=0.25, pitch=1.0, zoom=1.0)
    assert backend.set_camera(wanted)

    assert [a for a, _ in img.writes] == [SECTION_VA + LOCATION_OFF, SECTION_VA + CAMERA_OFF]
    assert img.writes[-1][1] == struct.pack("<I", CAMERA_APPLY)
    assert img.view == wanted


def test_a_camera_command_nobody_serves_is_reported():
    img = make_image()
    img.auto_acknowledge = False
    backend = make_backend(img)
    img.write(SECTION_VA + CAMERA_OFF, struct.pack("<I", CAMERA_APPLY))  # stuck pending
    assert not backend.set_camera(ViewLocation())
    assert backend.capture_camera() is None
    assert any("camera" in d.message for d in backend.diagnostics)


def _with_a_view(img: WritableImage) -> int:
    """Give the fake image a `TheTacticalView` to move, and return the view's address."""
    view = img.alloc(0x200)
    img.u32(THE_TACTICAL_VIEW, view)
    return view


def test_move_camera_writes_the_position_and_nothing_else():
    """**The whole reason this exists rather than `set_camera`.**

    `View::setLocation` writes all four scalars unconditionally, and the zoom it writes is not
    the zoom `getLocation` reports - `+0x128` against `+0x124`. Measured against a running match,
    handing back a location captured a moment earlier still moved the live zoom from 1.281116 to
    1.234136, and the client restored it over the next 0.6 seconds; fourteen other values,
    including the reported one, were refused the same way. So the invariant worth pinning is not
    which zoom gets written but that none does.
    """
    img = make_image()
    backend = make_backend(img)
    view = _with_a_view(img)
    img.writes.clear()

    assert backend.move_camera((1200.0, 880.0, 150.0))

    assert struct.unpack("<fff", img.read(view + VIEW_POSITION_OFFSET, 12)) == (
        1200.0,
        880.0,
        150.0,
    )
    assert [a for a, _ in img.writes] == [view + VIEW_POSITION_OFFSET]


def test_move_camera_is_not_a_hook_command():
    """It touches no slot and waits for no acknowledgement, which is what lets a pan write far
    faster than the logic frame rate - and what stops it from delaying an order."""
    img = make_image()
    backend = make_backend(img)
    _with_a_view(img)
    img.auto_acknowledge = False  # nothing is serving the buffer at all
    img.write(SECTION_VA + CAMERA_OFF, struct.pack("<I", CAMERA_APPLY))  # and one is stuck pending

    assert backend.move_camera((10.0, 20.0, 30.0))


def test_move_camera_before_the_client_has_a_view_is_a_diagnostic():
    """A null `TheTacticalView` is ordinary at a loading screen. Writing twelve bytes at
    `0x0C` regardless is not."""
    img = make_image()
    backend = make_backend(img)
    img.u32(THE_TACTICAL_VIEW, 0)
    assert not backend.move_camera((10.0, 20.0, 30.0))
    assert any("no view" in d.message for d in backend.diagnostics)


def test_move_camera_re_reads_the_view_each_time():
    """The client builds a fresh view per match, and a cached pointer writes twelve bytes into
    whatever owns that memory now."""
    img = make_image()
    backend = make_backend(img)
    first = _with_a_view(img)
    assert backend.move_camera((1.0, 2.0, 3.0))

    second = _with_a_view(img)
    assert second != first
    assert backend.move_camera((4.0, 5.0, 6.0))
    assert struct.unpack("<fff", img.read(second + VIEW_POSITION_OFFSET, 12)) == (4.0, 5.0, 6.0)
    assert struct.unpack("<fff", img.read(first + VIEW_POSITION_OFFSET, 12)) == (1.0, 2.0, 3.0)


def test_move_camera_before_connect_is_a_diagnostic():
    backend = BridgeBackend(Source(make_image()))
    assert not backend.move_camera((1.0, 2.0, 3.0))
    assert any("before connect" in d.message for d in backend.diagnostics)


def test_a_camera_command_before_connect_is_a_diagnostic():
    backend = BridgeBackend(Source(make_image()))
    assert not backend.set_camera(ViewLocation())
    assert any("before connect" in d.message for d in backend.diagnostics)


def test_connect_refuses_a_cave_built_to_another_layout():
    """The patched binary can be older than this writer, and then every offset here points
    somewhere else in its cave."""
    img = make_image()
    img.write(SECTION_VA + TAG_OFF, struct.pack("<I", BUFFER_TAG - 1))
    with pytest.raises(BridgeUnavailable, match="different version"):
        BridgeBackend(Source(img)).connect()


def test_the_bridge_still_observes_like_a_memory_backend():
    backend = make_backend(make_image())
    assert isinstance(backend, MemoryBackend)
    observation = backend.observe()
    assert observation.frame == 8688
    assert {p.name for p in observation.players} == {"PlyrCreeps", "Player_1"}
    assert len(observation.objects) == 4
