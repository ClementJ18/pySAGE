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
    GAME_STATE_SAVE_GAME,
    IMAGE_BASE,
    THE_GAME_STATE,
    THE_TACTICAL_VIEW,
    VIEW_LOCATION_SIZE,
    VIEW_POSITION_OFFSET,
)
from sage_patch.patches.diagnostics.live_bridge import (
    BUFFER_TAG,
    BUFFER_TAG_CHEATS,
    CALL_DIRECT,
    CALL_MAX_ARGS,
    CALL_SCRATCH_SIZE,
    CALL_VTABLE,
    CAMERA_APPLY,
    CAMERA_CAPTURE,
    CAMERA_OFF,
    LOCATION_OFF,
    MAX_ARGS,
    ORDER_TYPE_OFF,
    READY_OFF,
    SECTION_NAME,
    TAG_OFF,
    cheat_offsets,
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
        self._calls = False

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
        if tag not in (BUFFER_TAG, BUFFER_TAG_CHEATS):
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
        self._calls = tag == BUFFER_TAG_CHEATS
        return super().connect()

    @property
    def can_call(self) -> bool:
        """True when the game's live-bridge carries the call command (`--cheats`)."""
        return self._section is not None and self._calls

    @property
    def scratch_address(self) -> int | None:
        """Where `call`'s `scratch` bytes land - a fixed address a call argument can point at."""
        if self._section is None or not self._calls:
            return None
        return cheat_offsets(self._section[0])["scratch"]

    def call(
        self,
        target: int,
        args: Sequence[int] = (),
        *,
        this: int = 0,
        vtable: bool = False,
        cleanup: int = 0,
        scratch: bytes = b"",
        timeout: float = _ACK_TIMEOUT,
    ) -> int | None:
        """Call engine code on the logic thread, at the start of the next logic frame, and return
        its `eax` - or None when the call was refused or never served.

        `target` is an address, or with `vtable` a byte offset into the vtable at `this`, which
        goes in `ecx`. `cleanup` is what to add to `esp` afterwards: 0 for the engine's
        `__thiscall`/`__stdcall` targets, `4 * len(args)` for a `__cdecl` one. `scratch` is
        written to `scratch_address` first, for arguments that point at a structure.

        Needs the `--cheats` build of live-bridge: it calls whatever address it is given, so a
        wrong one crashes the game.
        """
        if not self._connected or self._section is None:
            self._diagnostics.append(Diagnostic("call before connect"))
            return None
        if not self._calls:
            self._diagnostics.append(
                Diagnostic("the game's live-bridge has no call command; apply it with --cheats")
            )
            return None
        if len(args) > CALL_MAX_ARGS or len(scratch) > CALL_SCRATCH_SIZE:
            raise ValueError(
                f"a call takes at most {CALL_MAX_ARGS} arguments and {CALL_SCRATCH_SIZE} bytes "
                "of scratch"
            )
        fields = cheat_offsets(self._section[0])
        if not self._await_zero(fields["ready"], timeout):
            self._diagnostics.append(Diagnostic("the previous call was never served"))
            return None
        record = struct.pack(
            "<IIIII",
            CALL_VTABLE if vtable else CALL_DIRECT,
            this & 0xFFFFFFFF,
            target & 0xFFFFFFFF,
            len(args),
            cleanup,
        )
        arguments = b"".join(struct.pack("<I", value & 0xFFFFFFFF) for value in args)
        # Everything first, `ready` last: the flag is what publishes the call.
        written = (
            (not scratch or self._writable.write(fields["scratch"], scratch))
            and self._writable.write(fields["mode"], record)
            and (not arguments or self._writable.write(fields["args"], arguments))
            and self._writable.write(fields["result"], struct.pack("<I", 0))
            and self._writable.write(fields["ready"], struct.pack("<I", 1))
        )
        if not written:
            self._diagnostics.append(Diagnostic("failed to write the call block"))
            return None
        if not self._await_zero(fields["ready"], timeout):
            self._diagnostics.append(Diagnostic("the call was not served; is the game paused?"))
            return None
        return self._u32(fields["result"])

    def save_game(self, timeout: float = 60.0) -> bool:
        """Save the running game as a new save, the way the save menu's "new save" does: the
        engine picks the next free `Saved Game N` and the extension of the game's type, in the
        user's save folder. True when the call was served; compare the folder before and after
        to find the file.

        `GameState::saveGame(UnicodeString file, const UnicodeString &desc, int list,
        bool showMessage, bool isAutoSave)` is `__thiscall` on `TheGameState`. A null `file` is
        what selects the engine's own naming (it tests the string's length at +4); `desc` is a
        reference, so it gets the address of an empty string in the scratch area - a null one
        is dereferenced (seen live: an access violation in the string code mid-save).

        A name of the caller's choosing is deliberately not offered. One the engine cannot open
        as a file (seen live: a name without its extension, which it created as a folder) throws
        outside `saveGame`'s own `catch`, and the game ends with "Uncaught Exception in
        GameEngine::update".
        """
        game_state = self._u32(THE_GAME_STATE)
        if not game_state:
            self._diagnostics.append(Diagnostic("save_game: no GameState"))
            return False
        scratch = self.scratch_address
        if scratch is None:
            self._diagnostics.append(Diagnostic("save_game: no call command"))
            return False
        empty_description = struct.pack("<I", 0)  # an `UnicodeString` holding no data
        result = self.call(
            GAME_STATE_SAVE_GAME,
            (0, scratch, 0, 0, 0),
            this=game_state,
            scratch=empty_description,
            timeout=timeout,
        )
        return result is not None

    def _await_zero(self, address: int, timeout: float) -> bool:
        """Wait for the dword at `address` to read 0; False on timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._u32(address) == 0:
                return True
            time.sleep(_ACK_POLL)
        return False

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
