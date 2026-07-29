"""`BridgeBackend` - observe *and* act, against a game carrying the live-bridge patch.

Reads exactly as `MemoryBackend` does, and adds the write half: an order is marshalled into
the command buffer that `sage_patch`'s `live-bridge` patch appends to `game.dat`, and the
hook inside `GameLogic::update` picks it up on the next logic frame and feeds it to
`TheMessageStream`.

Orders therefore enter through the engine's own `appendMessage`, so they are network-ordered
and check-summed like any human input. Nothing here calls a logic function directly.

**The buffer layout is owned by the patch**, and imported from it rather than restated, so a
change to the cave cannot silently desynchronise from the writer.

**The handshake protocol is a single slot.** Write the payload, then set `ready` **last**; the
hook consumes it and clears the flag. One writer and one reader, and x86 store ordering makes
that safe without locking - but it does mean an order must be acknowledged before the next
one is written, which `send` waits for.
"""

from __future__ import annotations

import struct
import time
from collections.abc import Sequence
from typing import Protocol

from sage_live.memory import LAYOUT_ROTWK_201, EngineLayout, MemoryBackend, MemorySource
from sage_live.protocol import Diagnostic, Handshake
from sage_patch.addresses import IMAGE_BASE
from sage_patch.patches.live_bridge import (
    MAX_ARGS,
    ORDER_TYPE_OFF,
    READY_OFF,
    SECTION_NAME,
)
from sage_patch.pe import find as pe_find
from sage_patch.pe import mapped_sections
from sage_replay.replay import Order, OrderArgumentType

__all__ = ["BridgeBackend", "BridgeUnavailable", "WritableMemorySource", "find_section"]


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
    """Locate a PE section in the running image by walking the image's own headers.

    Returns `(virtual_address, virtual_size)`, or None when the section is absent - which is
    how an unpatched game announces itself. The walk itself is `sage_patch.pe`, shared with
    the file-image side; only the byte source differs.
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
    """One 20-byte argument record: the type tag then up to four value slots.

    By-value types put the value in the first slot; by-pointer types lay their structure out
    across the slots and the cave passes the slot address instead.
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
    """The command-buffer payload for one order, excluding the `ready` flag.

    Laid out from `ORDER_TYPE_OFF`, so the caller writes it at that offset and only then
    sets `ready`.

    **`order.player_index` is deliberately not transmitted.** The engine attributes an
    appended message to the local player itself, so the field is inert here and matters only
    when the same `Order` is written out by `sage_replay.serialize`. It is also *not* the same
    numbering: a game observed with `PlayerList` index 3 recorded its orders as player 2 in the
    replay (see `sage_patch/docs/message-stream.md` section 4c).
    """
    if len(order.arguments) > MAX_ARGS:
        raise ValueError(f"{len(order.arguments)} arguments exceeds the buffer's {MAX_ARGS}")
    body = struct.pack("<III", order.order_type, len(order.arguments), 0)
    for argument in order.arguments:
        body += encode_argument(argument.argument_type, argument.value)
    return body


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
        """True while an order sits in the buffer that the hook has not yet consumed.

        The single-slot handshake means this is also the answer to "did my last order get
        through": it goes false within a logic frame of a healthy hook, and stays true when
        the game is paused or the hook is not running.
        """
        return self._ready_flag() == 1

    def wait_until_idle(self, timeout: float = _ACK_TIMEOUT) -> bool:
        """Block until the hook has consumed the pending order; False on timeout.

        `send` already waits before writing, so this is for callers that want to *confirm*
        an order was taken - a caller wanting to report per-order acknowledgement, rather
        than only discovering a stall on the next send.
        """
        return self._await_acknowledgement(timeout)

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
