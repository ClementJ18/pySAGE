"""Wire protocol: framing, the handshake gate, and the observation codec.

Frames are little-endian: `u16 magic | u16 type | u32 payload_length | payload`. Two
logical channels share one stream - request/response (handshake, orders, control) and
pushed events (observations, session events) - distinguished by message type rather than by
connection.

The magic word is what makes recovery possible. A purely length-prefixed frame cannot
resynchronise: once the reader is off by a byte, arbitrary bytes parse as a plausible
length and the stream stalls waiting for a payload that will never arrive. With a marker,
a confused reader scans forward to the next one and carries on.

Observations are a **versioned binary struct, not JSON**, from the first version. Not for
speed today, but so that swapping the transport for a shared-memory ring buffer later is
invisible to every caller: the bytes stay the same, only who writes them changes.

The handshake is a gate, not a greeting. It carries the protocol version, the engine build
id and the loaded mod's data checksum; a mismatch fails the connection rather than
degrading, the same discipline `sage_patch` applies when it asserts expected bytes before
writing.

Per CONVENTIONS.md rule 4, decoding never raises: a frame we cannot read becomes a
`Diagnostic` and the stream resynchronises, so one bad frame does not kill a session.
"""

from __future__ import annotations

import logging
import struct
from collections import deque
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from typing import overload

from sage_live.api.observation import GameObject, Observation, PlayerState, ProductionItem

__all__ = [
    "FRAME_HEADER",
    "FRAME_MAGIC",
    "OBSERVATION_STRUCT_VERSION",
    "PROTOCOL_VERSION",
    "Diagnostic",
    "DiagnosticLog",
    "Frame",
    "Handshake",
    "MessageType",
    "decode_frames",
    "decode_handshake",
    "decode_observation",
    "encode_frame",
    "encode_handshake",
    "encode_observation",
]

# One logger for the package, named for it, with no handler attached: a library that
# configures logging decides for the application that imported it. A consumer that wants these
# calls `logging.basicConfig()`, and one that does not is unaffected.
_log = logging.getLogger("sage_live")

PROTOCOL_VERSION = 1

# Bumped independently of PROTOCOL_VERSION whenever the observation payload layout changes,
# so a reader can refuse a struct it does not know without rejecting the whole connection.
#
# 5 (2026-08-04) added the player's held sciences, which is the only observable answer to "have
# I already bought that spellbook power" - a science lands in no upgrade mask.
#
# 4 (2026-08-01) added per-object `ModelConditionFlags`, which is how the engine itself knows a
# structure is still going up - health cannot say, since it ramps while building.
#
# 3 (2026-08-01) added `godsight`, so a snapshot records whether it still carries knowledge a
# real player could not have - an opponent's economy, or what their buildings are making.
#
# 2 (2026-07-31) added per-object production queues, and carried two fields the model had all
# along that version 1 silently dropped: `GameObject.upgrades` and
# `PlayerState.upgrades_in_progress`. Dropping them was not cosmetic - `LoopbackBackend` round
# -trips every observation through this codec, so a policy tested against it saw battalions
# whose object-scoped upgrades had vanished, which is the one field distinguishing an upgraded
# battalion from a fresh one.
OBSERVATION_STRUCT_VERSION = 5

# "SG" - the sync marker every frame opens with, so a confused reader can find its footing.
FRAME_MAGIC = 0x4753
FRAME_HEADER = struct.Struct("<HHI")

# A payload larger than this is treated as a desynchronised stream rather than a real message.
_MAX_FRAME = 64 << 20
_NO_INDEX = -1


class MessageType(IntEnum):
    HANDSHAKE_REQUEST = 1
    HANDSHAKE_REPLY = 2
    OBSERVATION = 3
    ORDERS = 4
    CONTROL = 5
    EVENT = 6


@dataclass(frozen=True)
class Diagnostic:
    """A problem encountered while decoding. Never raised - always returned."""

    message: str
    offset: int = 0

    def __str__(self) -> str:
        return f"{self.message} (at byte {self.offset})"


class DiagnosticLog(Sequence[Diagnostic]):
    """A backend's diagnostics: bounded, logged, and drainable.

    Three things a plain list got wrong for a session that runs for an hour rather than for a
    test. **Bounded**, because a backend appends per observation and a game that has gone away
    appends the same message every cycle forever - unbounded memory in exchange for a thousand
    copies of one sentence. **Logged**, because a diagnostic nobody reads is not a diagnostic;
    `logging` is how a long run surfaces one without the library choosing to print. And
    **drainable**, so a loop can consume what is new instead of re-scanning a growing tail.

    Kept oldest-first with the newest retained: on a `deque` with a `maxlen` the oldest are
    what fall out, which is right here - the first occurrence of a problem is usually the one
    that explains the rest, but a stale first occurrence is worth less than a current one.
    """

    def __init__(self, limit: int = 256, logger: logging.Logger | None = None) -> None:
        self._entries: deque[Diagnostic] = deque(maxlen=limit)
        self._logger = logger or _log
        self._seen = 0

    def append(self, diagnostic: Diagnostic) -> None:
        self._entries.append(diagnostic)
        self._seen += 1
        self._logger.warning("%s", diagnostic)

    def extend(self, diagnostics: Iterable[Diagnostic]) -> None:
        for diagnostic in diagnostics:
            self.append(diagnostic)

    def drain(self) -> tuple[Diagnostic, ...]:
        """Take everything held and clear it, so a loop reports each problem once."""
        taken = tuple(self._entries)
        self._entries.clear()
        return taken

    @property
    def seen(self) -> int:
        """How many have ever been recorded, including those dropped by the bound."""
        return self._seen

    def __iter__(self) -> Iterator[Diagnostic]:
        # Over a copy: a consumer that reports while the backend is polling would otherwise
        # be iterating a deque that is being appended to.
        return iter(tuple(self._entries))

    def __len__(self) -> int:
        return len(self._entries)

    @overload
    def __getitem__(self, index: int) -> Diagnostic: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[Diagnostic]: ...

    def __getitem__(self, index: int | slice) -> Diagnostic | Sequence[Diagnostic]:
        return tuple(self._entries)[index]

    def __repr__(self) -> str:
        return f"DiagnosticLog({len(self._entries)} held, {self._seen} seen)"


@dataclass(frozen=True)
class Frame:
    message_type: int
    payload: bytes


@dataclass(frozen=True)
class Handshake:
    """The connection gate. `engine_build` and `data_checksum` are the same patch identity
    the replay header records and that `sage_replay.aggregate` already refuses to mix."""

    protocol_version: int = PROTOCOL_VERSION
    engine_build: str = ""
    data_checksum: str = ""
    fog_of_war: bool = True
    apm_cap: int = 0

    def accepts(self, other: Handshake) -> tuple[bool, str]:
        """Whether `other` may connect to us, and why not when it may not."""
        if other.protocol_version != self.protocol_version:
            return False, (
                f"protocol version mismatch: peer {other.protocol_version}, "
                f"expected {self.protocol_version}"
            )
        if self.engine_build and other.engine_build != self.engine_build:
            return False, f"engine build mismatch: peer {other.engine_build!r}"
        if self.data_checksum and other.data_checksum != self.data_checksum:
            return False, f"game data checksum mismatch: peer {other.data_checksum!r}"
        return True, ""


def encode_frame(message_type: int, payload: bytes) -> bytes:
    return FRAME_HEADER.pack(FRAME_MAGIC, message_type, len(payload)) + payload


def _resync(buffer: bytes, pos: int) -> int:
    """The next plausible frame start at or after `pos`, else the end of the buffer."""
    nxt = buffer.find(struct.pack("<H", FRAME_MAGIC), pos + 1)
    return len(buffer) if nxt < 0 else nxt


def decode_frames(buffer: bytes) -> tuple[list[Frame], bytes, list[Diagnostic]]:
    """Pull every complete frame out of `buffer`.

    Returns the frames, the unconsumed tail to carry into the next read, and any
    diagnostics. A bad magic or an implausible length scans forward to the next marker, so
    a corrupted stream recovers instead of stalling.
    """
    frames: list[Frame] = []
    diags: list[Diagnostic] = []
    pos = 0
    while pos + FRAME_HEADER.size <= len(buffer):
        magic, message_type, length = FRAME_HEADER.unpack_from(buffer, pos)
        if magic != FRAME_MAGIC:
            diags.append(Diagnostic(f"bad frame magic {magic:#06x}", pos))
            pos = _resync(buffer, pos)
            continue
        if length > _MAX_FRAME:
            diags.append(Diagnostic(f"implausible payload length {length}", pos))
            pos = _resync(buffer, pos)
            continue
        end = pos + FRAME_HEADER.size + length
        if end > len(buffer):
            break
        frames.append(Frame(message_type, buffer[pos + FRAME_HEADER.size : end]))
        pos = end
    return frames, buffer[pos:], diags


@dataclass
class _Writer:
    buf: bytearray = field(default_factory=bytearray)

    def u8(self, v: int) -> None:
        self.buf += struct.pack("<B", v & 0xFF)

    def u16(self, v: int) -> None:
        self.buf += struct.pack("<H", v & 0xFFFF)

    def u32(self, v: int) -> None:
        self.buf += struct.pack("<I", v & 0xFFFFFFFF)

    def i32(self, v: int) -> None:
        self.buf += struct.pack("<i", v)

    def f32(self, v: float) -> None:
        self.buf += struct.pack("<f", v)

    def text(self, v: str) -> None:
        raw = v.encode("utf-8")[:0xFFFF]
        self.u16(len(raw))
        self.buf += raw


class _Reader:
    """A bounds-checked reader. Running off the end sets `failed` rather than raising."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0
        self.failed = False

    def _take(self, n: int) -> bytes | None:
        if self.failed or self.pos + n > len(self.data):
            self.failed = True
            return None
        chunk = self.data[self.pos : self.pos + n]
        self.pos += n
        return chunk

    def u8(self) -> int:
        c = self._take(1)
        return struct.unpack("<B", c)[0] if c else 0

    def u16(self) -> int:
        c = self._take(2)
        return struct.unpack("<H", c)[0] if c else 0

    def u32(self) -> int:
        c = self._take(4)
        return struct.unpack("<I", c)[0] if c else 0

    def i32(self) -> int:
        c = self._take(4)
        return struct.unpack("<i", c)[0] if c else 0

    def f32(self) -> float:
        c = self._take(4)
        return float(struct.unpack("<f", c)[0]) if c else 0.0

    def text(self) -> str:
        raw = self._take(self.u16())
        return raw.decode("utf-8", errors="replace") if raw else ""


def encode_handshake(hs: Handshake) -> bytes:
    w = _Writer()
    w.u16(hs.protocol_version)
    w.text(hs.engine_build)
    w.text(hs.data_checksum)
    w.u8(int(hs.fog_of_war))
    w.u32(hs.apm_cap)
    return bytes(w.buf)


def decode_handshake(payload: bytes) -> tuple[Handshake | None, list[Diagnostic]]:
    r = _Reader(payload)
    hs = Handshake(
        protocol_version=r.u16(),
        engine_build=r.text(),
        data_checksum=r.text(),
        fog_of_war=bool(r.u8()),
        apm_cap=r.u32(),
    )
    if r.failed:
        return None, [Diagnostic("truncated handshake", r.pos)]
    return hs, []


def encode_observation(obs: Observation) -> bytes:
    w = _Writer()
    w.u16(OBSERVATION_STRUCT_VERSION)
    w.u32(obs.frame)
    w.i32(obs.local_player)
    w.u8(int(obs.fogged))
    w.u8(int(obs.godsight))
    w.u16(len(obs.players))
    for p in obs.players:
        w.u16(p.index)
        w.text(p.name)
        w.text(p.faction)
        w.i32(p.resources)
        w.i32(p.resources_collected)
        w.i32(p.power_points)
        w.i32(p.command_points[0])
        w.i32(p.command_points[1])
        w.u16(len(p.upgrades))
        for up in sorted(p.upgrades):
            w.text(up)
        w.u16(len(p.upgrades_in_progress))
        for up in sorted(p.upgrades_in_progress):
            w.text(up)
        # Ids rather than names, which is what the model carries - see `PlayerState.sciences`.
        w.u16(len(p.sciences))
        for science in sorted(p.sciences):
            w.i32(science)
    w.u32(len(obs.objects))
    for o in obs.objects:
        w.u32(o.object_id)
        w.text(o.template_name)
        w.text(o.template_side)
        w.f32(o.position[0])
        w.f32(o.position[1])
        w.f32(o.position[2])
        w.f32(o.angle)
        w.f32(o.health)
        w.f32(o.max_health)
        w.i32(_NO_INDEX if o.owner_index is None else o.owner_index)
        w.i32(_NO_INDEX if o.parent_id is None else o.parent_id)
        # OBJECT-scoped upgrades. Absent from struct version 1, which silently dropped them -
        # and they are the only thing distinguishing an upgraded battalion from a fresh one.
        w.u16(len(o.upgrades))
        for up in sorted(o.upgrades):
            w.text(up)
        w.u16(len(o.conditions))
        for name in sorted(o.conditions):
            w.text(name)
        w.u16(len(o.production))
        for item in o.production:
            w.text(item.kind)
            w.text(item.name)
    return bytes(w.buf)


def decode_observation(payload: bytes) -> tuple[Observation | None, list[Diagnostic]]:
    r = _Reader(payload)
    version = r.u16()
    if version != OBSERVATION_STRUCT_VERSION:
        return None, [
            Diagnostic(
                f"observation struct version {version}, expected {OBSERVATION_STRUCT_VERSION}"
            )
        ]
    frame = r.u32()
    local_player = r.i32()
    fogged = bool(r.u8())
    godsight = bool(r.u8())

    players: list[PlayerState] = []
    for _ in range(r.u16()):
        index = r.u16()
        name = r.text()
        faction = r.text()
        resources = r.i32()
        collected = r.i32()
        power = r.i32()
        cp_used = r.i32()
        cp_cap = r.i32()
        upgrades = frozenset(r.text() for _ in range(r.u16()))
        in_progress = frozenset(r.text() for _ in range(r.u16()))
        sciences = frozenset(r.i32() for _ in range(r.u16()))
        if r.failed:
            return None, [Diagnostic("truncated player block", r.pos)]
        players.append(
            PlayerState(
                index=index,
                name=name,
                faction=faction,
                resources=resources,
                resources_collected=collected,
                power_points=power,
                command_points=(cp_used, cp_cap),
                sciences=sciences,
                upgrades=upgrades,
                upgrades_in_progress=in_progress,
            )
        )

    objects: list[GameObject] = []
    for _ in range(r.u32()):
        object_id = r.u32()
        template = r.text()
        side = r.text()
        pos = (r.f32(), r.f32(), r.f32())
        angle = r.f32()
        health = r.f32()
        max_health = r.f32()
        owner = r.i32()
        parent = r.i32()
        obj_upgrades = frozenset(r.text() for _ in range(r.u16()))
        conditions = frozenset(r.text() for _ in range(r.u16()))
        production = tuple(ProductionItem(r.text(), r.text()) for _ in range(r.u16()))
        if r.failed:
            return None, [Diagnostic("truncated object block", r.pos)]
        objects.append(
            GameObject(
                object_id=object_id,
                template_name=template,
                template_side=side,
                position=pos,
                angle=angle,
                health=health,
                max_health=max_health,
                owner_index=None if owner == _NO_INDEX else owner,
                parent_id=None if parent == _NO_INDEX else parent,
                upgrades=obj_upgrades,
                conditions=conditions,
                production=production,
            )
        )

    if r.failed:
        return None, [Diagnostic("truncated observation", r.pos)]
    return (
        Observation(
            frame=frame,
            local_player=local_player,
            players=tuple(players),
            objects=tuple(objects),
            fogged=fogged,
            godsight=godsight,
        ),
        [],
    )
