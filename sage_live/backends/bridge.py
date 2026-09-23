"""`BridgeBackend` - observe *and* act, against a game carrying the live-bridge patch.

Reads like `MemoryBackend`, and writes orders into the command buffer the `live-bridge` patch adds
to `game.dat`. A hook in `GameLogic::update` feeds each order to `TheMessageStream` on the next
logic frame, so it is network-ordered and checksummed like human input. The buffer layout is
imported from the patch, so the two cannot drift.

The buffer is a single slot: write the payload, then set `ready` last; the hook consumes it and
clears the flag. So each order must be acknowledged before the next (`send` waits).

The camera uses a second slot with the same protocol but is not an order (it never reaches the
stream). `capture_camera` reads the live view; re-aiming uses `move_camera`, which writes the view's
position field directly.
"""

from __future__ import annotations

import struct
import time
from collections.abc import Sequence
from typing import Protocol

from sage_live.api.camera import ViewLocation
from sage_live.api.observation import Vec3
from sage_live.backends.memory import LAYOUT_ROTWK_201, EngineLayout, MemoryBackend, MemorySource
from sage_live.backends.protocol import Diagnostic, Handshake
from sage_patch.addresses import (
    IMAGE_BASE,
    THE_TACTICAL_VIEW,
    VIEW_LOCATION_SIZE,
    VIEW_POSITION_OFFSET,
)
from sage_patch.patches.experimental.live_bridge import (
    BUFFER_TAG,
    CAMERA_APPLY,
    CAMERA_CAPTURE,
    CAMERA_OFF,
    LOCATION_OFF,
    MAX_ARGS,
    ORDER_TYPE_OFF,
    READY_OFF,
    SECTION_NAME,
    TAG_OFF,
)
from sage_patch.pe import find as pe_find
from sage_patch.pe import mapped_sections
from sage_replay.replay import Order, OrderArgumentType

__all__ = [
    "BridgeBackend",
    "BridgeUnavailable",
    "WritableMemorySource",
    "decode_view_location",
    "encode_view_location",
    "find_section",
]


# How long to wait for the hook to acknowledge an order before giving up. The engine runs
# well under 60 logic frames a second, so this is many frames' worth of slack.
_ACK_TIMEOUT = 2.0
_ACK_POLL = 0.002


class BridgeUnavailable(Exception):
    """The running game does not carry the live-bridge patch."""


class WritableMemorySource(MemorySource, Protocol):
    """A `MemorySource` that can also be written to."""

    def write(self, address: int, data: bytes) -> bool: ...


def find_section(source: MemorySource, name: str = SECTION_NAME) -> tuple[int, int] | None:
    """Locate a PE section in the running image, as `(virtual_address, virtual_size)`, or None when
    absent - which is how an unpatched game shows. The walk is `sage_patch.pe`'s.
    """
    section = pe_find(mapped_sections(source.read, IMAGE_BASE), name)
    return None if section is None else (section.virtual_address, section.virtual_size)


def _number(value: object, label: str) -> float:
    # bool is a subclass of int, so Boolean arguments pass through here unchanged.
    if not isinstance(value, (int, float)):
        raise ValueError(f"{label} needs a number, got {value!r}")
    return float(value)


def _components(value: object, count: int, label: str) -> list[float]:
    """Validate a fixed-length numeric sequence, so a malformed order is refused here
    rather than becoming a wild pointer read inside the engine."""
    if not isinstance(value, (tuple, list)) or len(value) != count:
        raise ValueError(f"{label} needs {count} components, got {value!r}")
    return [_number(item, label) for item in value]


def _float_bits(value: float) -> int:
    return int(struct.unpack("<I", struct.pack("<f", value))[0])


def encode_argument(argument_type: int, value: object) -> bytes:
    """One 20-byte argument record: the type tag, then up to four value slots. By-value types use
    the first slot; by-pointer types fill the slots and the cave passes their address.
    """
    slots = [0, 0, 0, 0]
    tag = int(argument_type)
    if tag == OrderArgumentType.Float:
        slots[0] = _float_bits(_number(value, "Float"))
    elif tag == OrderArgumentType.Position:
        for i, component in enumerate(_components(value, 3, "Position")):
            slots[i] = _float_bits(component)
    elif tag == OrderArgumentType.ScreenPosition:
        for i, component in enumerate(_components(value, 2, "ScreenPosition")):
            slots[i] = int(component) & 0xFFFFFFFF
    elif tag == OrderArgumentType.ScreenRectangle:
        for i, component in enumerate(_components(value, 4, "ScreenRectangle")):
            slots[i] = int(component) & 0xFFFFFFFF
    else:
        slots[0] = int(_number(value, f"argument type {tag}")) & 0xFFFFFFFF
    return struct.pack("<5I", tag, *slots)


def encode_order(order: Order) -> bytes:
    """The command-buffer payload for one order, excluding the `ready` flag, laid out from
    `ORDER_TYPE_OFF`.

    `order.player_index` is not transmitted: the engine attributes the message to the local player.
    It only matters when the `Order` is written to a replay, where the numbering also differs (see
    `sage_patch/docs/message-stream.md` section 4c).
    """
    if len(order.arguments) > MAX_ARGS:
        raise ValueError(f"{len(order.arguments)} arguments exceeds the buffer's {MAX_ARGS}")
    body = struct.pack("<III", order.order_type, len(order.arguments), 0)
    for argument in order.arguments:
        body += encode_argument(argument.argument_type, argument.value)
    return body


def encode_view_location(location: ViewLocation) -> bytes:
    """The 32 bytes `View::setLocation` reads: the validity flag, a `Coord3D`, four scalars."""
    x, y, z = _components(location.position, 3, "position")
    return struct.pack(
        "<I7f",
        int(location.valid),
        x,
        y,
        z,
        _number(location.angle, "angle"),
        _number(location.pitch, "pitch"),
        _number(location.zoom, "zoom"),
        _number(location.extra, "extra"),
    )


def decode_view_location(raw: bytes | None) -> ViewLocation | None:
    """A captured `ViewLocation`, or None when the buffer is short or the engine marked the location
    invalid.
    """
    if raw is None or len(raw) < VIEW_LOCATION_SIZE:
        return None
    valid, x, y, z, angle, pitch, zoom, extra = struct.unpack_from("<I7f", raw)
    if not valid:
        return None
    return ViewLocation(
        position=(x, y, z), angle=angle, pitch=pitch, zoom=zoom, extra=extra, valid=True
    )


class BridgeBackend(MemoryBackend):
    """A `MemoryBackend` that can also issue orders, via the live-bridge patch."""

    def __init__(
        self,
        source: WritableMemorySource,
        layout: EngineLayout = LAYOUT_ROTWK_201,
        handshake: Handshake | None = None,
        expect: Handshake | None = None,
    ) -> None:
        super().__init__(source, layout=layout, handshake=handshake, expect=expect)
        self._writable = source
        self._section: tuple[int, int] | None = None

    @property
    def section(self) -> tuple[int, int] | None:
        """`(virtual_address, virtual_size)` of the command buffer, once connected."""
        return self._section

    def connect(self) -> Handshake:
        located = find_section(self.source)
        if located is None:
            raise BridgeUnavailable(
                f"the running game has no {SECTION_NAME} section - it is not carrying the "
                "live-bridge patch"
            )
        self._section = located
        tag = self._u32(located[0] + TAG_OFF)
        if tag != BUFFER_TAG:
            # The section is present, so the game is patched - just not by this version. Every
            # offset this module writes at would land somewhere else in that cave, and the
            # nearest thing to a camera write is the middle of the appender table, which the
            # hook calls through. Refusing is the only safe answer.
            self._section = None
            raise BridgeUnavailable(
                f"the {SECTION_NAME} section is tagged {tag:#010x}, not {BUFFER_TAG:#010x}: this "
                "game was patched by a different version of live-bridge. Re-apply it with "
                "`sage-patch apply live-bridge --in game.dat`."
            )
        return super().connect()

    def _ready_flag(self) -> int | None:
        if self._section is None:
            return None
        return self._u32(self._section[0] + READY_OFF)

    def _await_acknowledgement(self, timeout: float = _ACK_TIMEOUT) -> bool:
        """Wait for the hook to consume the pending order and clear `ready`."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._ready_flag() == 0:
                return True
            time.sleep(_ACK_POLL)
        return False

    @property
    def pending(self) -> bool:
        """True while an order sits in the buffer unconsumed. Goes false within a logic frame on a
        healthy hook; stays true while the game is paused or the hook is not running.
        """
        return self._ready_flag() == 1

    def wait_until_idle(self, timeout: float = _ACK_TIMEOUT) -> bool:
        """Block until the hook has consumed the pending order; False on timeout. For callers that
        want per-order acknowledgement (`send` already waits before writing).
        """
        return self._await_acknowledgement(timeout)

    def _camera_flag(self) -> int | None:
        if self._section is None:
            return None
        return self._u32(self._section[0] + CAMERA_OFF)

    def _await_camera(self, timeout: float) -> bool:
        """Wait for the hook to serve the pending camera command and clear the flag."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._camera_flag() == 0:
                return True
            time.sleep(_ACK_POLL)
        return False

    def _camera_command(self, command: int, payload: bytes | None, timeout: float) -> bool:
        """Publish one camera command and wait for the hook to serve it.

        Waits before writing too, since a second command would overwrite a pending one. With no view
        yet (a loading screen) the cave leaves the flag set, so the command times out rather than
        vanishing.
        """
        if not self._connected or self._section is None:
            self._diagnostics.append(Diagnostic("camera command before connect"))
            return False
        base = self._section[0]
        if not self._await_camera(timeout):
            self._diagnostics.append(
                Diagnostic("the bridge did not serve the previous camera command; is there a view?")
            )
            return False
        if payload is not None and not self._writable.write(base + LOCATION_OFF, payload):
            self._diagnostics.append(Diagnostic("failed to write the camera location"))
            return False
        if not self._writable.write(base + CAMERA_OFF, struct.pack("<I", command)):
            self._diagnostics.append(Diagnostic("failed to publish the camera command"))
            return False
        if not self._await_camera(timeout):
            self._diagnostics.append(
                Diagnostic("the camera command was not served; the client may have no view yet")
            )
            return False
        return True

    def set_camera(self, location: ViewLocation, timeout: float = _ACK_TIMEOUT) -> bool:
        """Place the camera; True once the hook has handed it to `View::setLocation`.

        Not an order and not rate-limited. The view clamps placements to the map's camera limits, so
        `capture_camera` is what says where the camera actually is.
        """
        try:
            payload = encode_view_location(location)
        except ValueError as exc:
            self._diagnostics.append(Diagnostic(f"cannot encode the camera location: {exc}"))
            return False
        return self._camera_command(CAMERA_APPLY, payload, timeout)

    def move_camera(self, position: Vec3) -> bool:
        """Re-aim the camera by writing the view's position field. **Prefer this to `set_camera`**
        whenever only the aim changes.

        `setLocation` always rewrites the zoom as well, visibly disturbing it (see
        `sage_patch/docs/camera-control.md`). Writing the position needs no hook command and no
        acknowledgement, so it can run fast enough for a smooth pan. `position` is the look-at point
        on the terrain, not the camera's eye. `TheTacticalView` is re-read on each call, because
        each match builds a new one.
        """
        if not self._connected:
            self._diagnostics.append(Diagnostic("camera move before connect"))
            return False
        view = self._pointer(THE_TACTICAL_VIEW)
        if not view:
            self._diagnostics.append(Diagnostic("no view yet; the client may still be loading"))
            return False
        payload = struct.pack("<fff", float(position[0]), float(position[1]), float(position[2]))
        if not self._writable.write(view + VIEW_POSITION_OFFSET, payload):
            self._diagnostics.append(Diagnostic("failed to write the camera position"))
            return False
        return True

    def capture_camera(self, timeout: float = _ACK_TIMEOUT) -> ViewLocation | None:
        """Read the live camera, or None if it cannot be read - the starting point for any change
        that should keep the player's zoom and facing.
        """
        section = self._section
        if section is None or not self._camera_command(CAMERA_CAPTURE, None, timeout):
            return None
        return decode_view_location(self.source.read(section[0] + LOCATION_OFF, VIEW_LOCATION_SIZE))

    def send(self, orders: Sequence[Order]) -> int:
        if not self._connected or self._section is None:
            self._diagnostics.append(Diagnostic("send before connect"))
            return 0
        base = self._section[0]
        accepted = 0
        for order in orders:
            if not self._await_acknowledgement():
                self._diagnostics.append(
                    Diagnostic("the bridge did not consume the previous order; is the game paused?")
                )
                break
            try:
                payload = encode_order(order)
            except ValueError as exc:
                self._diagnostics.append(Diagnostic(f"cannot encode order: {exc}"))
                continue
            # Payload first, `ready` last: the flag is what publishes the record.
            if not self._writable.write(base + ORDER_TYPE_OFF, payload):
                self._diagnostics.append(Diagnostic("failed to write the command buffer"))
                break
            if not self._writable.write(base + READY_OFF, struct.pack("<I", 1)):
                self._diagnostics.append(Diagnostic("failed to publish the ready flag"))
                break
            accepted += 1
        return accepted
