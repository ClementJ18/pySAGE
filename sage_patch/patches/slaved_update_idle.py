"""Alternate optional SlavedUpdate wandering and rest, without cancelling orders.

RotWK byte and stack derivation, lifecycle and clock limits: ../docs/slaved-update-idle.md.
"""

from __future__ import annotations

import argparse
import struct

from ..addresses import (
    GAME_LOGIC_FRAME,
    OBJECT_ID,
    SLAVED_IDLE_ANCHORS,
    SLAVED_IDLE_CTOR,
    SLAVED_IDLE_DTOR,
    SLAVED_IDLE_FALLTHROUGH,
    SLAVED_IDLE_GUARD,
    SLAVED_IDLE_HOOK,
    SLAVED_IDLE_HOOKS,
    SLAVED_IDLE_XFER,
    THE_GAME_LOGIC,
)
from ..asm import JBE, JE, JLE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, jmp_rel32, u32, va_to_offset

__all__ = [
    "SlavedUpdateIdlePatch",
    "build_code",
    "milliseconds_to_logic_frames",
    "SECTION_NAME",
    "TABLE_OFFSET",
    "CODE_OFFSET",
]

SECTION_NAME = ".slvidle"
TABLE_OFFSET = 32
_SLOTS = 4096
_STRIDE = 32
CODE_OFFSET = TABLE_OFFSET + _SLOTS * _STRIDE
_MAX_MS = 86_400_000
_SEED = 0x9E3779B9
_LCG_MULTIPLIER = 1664525
_LCG_INCREMENT = 1013904223
_PARAMETERS = ("wander_min_ms", "wander_max_ms", "idle_min_ms", "idle_max_ms")
_DEFAULTS = (6000, 14191, 3000, 7095)


def milliseconds_to_logic_frames(ms: int) -> int:
    """Round positive integer milliseconds up to RotWK's 200-ms simulation grid."""
    if type(ms) is not int or not 1 <= ms <= _MAX_MS:
        raise ValueError(f"duration must be an integer in 1..{_MAX_MS} milliseconds")
    return (ms + 199) // 200


def _save_fp(a: Asm) -> None:
    # FXSAVE covers x87, MXCSR and all XMM registers, including across the Xfer predicate call.
    a.emit(bytes.fromhex("89e783ec1081ec0002000083e4f00fae0424"))


def _restore_fp(a: Asm) -> None:
    a.emit(bytes.fromhex("0fae0c2489fc"))  # fxrstor [esp]; mov esp, edi


def build_code(base: int, intervals: tuple[int, int, int, int]) -> tuple[bytes, dict[int, int]]:
    """Emit code and hook destinations. State is separate from all engine objects.

    Slots contain base instance pointer, ObjectID, deadline, phase (0 idle), PRNG and padding.
    Keys 0/1 mean virgin/tombstone. Linear probing never evicts another live instance.
    """
    frames = tuple(milliseconds_to_logic_frames(ms) for ms in intervals)
    if intervals[0] > intervals[1] or intervals[2] > intervals[3]:
        raise ValueError("each minimum must be <= its maximum")
    a = Asm(base + CODE_OFFSET)
    hooks = {SLAVED_IDLE_HOOK: a.va}
    a.jcc(JBE, "fallthrough")  # consume original JA flags before any flag-changing instruction
    a.emit(0x9C, 0x60)  # pushfd; pushad
    a.emit(bytes.fromhex("8b45f483781000"))  # ModuleData; signed integer GuardWanderRange
    a.jcc(JLE, "original")
    a.emit(0xA1, u32(THE_GAME_LOGIC), 0x85, 0xC0)
    a.jcc(JE, "original")  # no simulation: no state allocation or phase advancement
    a.emit(bytes.fromhex("8b55f883ea10"))  # embedded Update* -> complete SlavedUpdate*
    a.call("lookup")
    a.emit(0x85, 0xF6)
    a.jcc(JE, "original")  # full table: stock behaviour, never steal state
    a.emit(bytes.fromhex("8b45fc8b40") + bytes([OBJECT_ID]))
    a.emit(0x39, 0x16)  # cmp [esi], edx
    a.jcc(JNE, "initialize")
    a.emit(0x39, 0x46, 0x04)
    a.jcc(JE, "frame")
    a.label("initialize")
    a.emit(0x89, 0x16, 0x89, 0x46, 0x04)  # key = instance; id = owner ObjectID
    a.emit(bytes.fromhex("c7460c00000000"))  # phase = idle
    a.emit(0x35, u32(_SEED), 0x89, 0x46, 0x10)  # PRNG = ObjectID XOR fixed seed
    a.emit(bytes.fromhex("c7461801000000"))  # first interval still needs scheduling
    a.label("frame")
    a.emit(0xA1, u32(THE_GAME_LOGIC))
    a.emit(0x8B, 0x40, GAME_LOGIC_FRAME, 0x8B, 0xD8)  # eax = ebx = current frame
    a.emit(bytes.fromhex("837e1800"))
    a.jcc(JNE, "schedule")
    a.emit(bytes.fromhex("2b4608"))  # signed (now - deadline), wrap-safe within half period
    a.jcc(0x8, "phase")  # JS
    a.emit(bytes.fromhex("83760c01"))  # toggle once, do not catch up after pauses
    a.label("schedule")
    a.emit(bytes.fromhex("c7461800000000"))  # clear pending initialization
    a.emit(0x8B, 0x46, 0x10)  # eax = per-instance PRNG
    a.emit(0x69, 0xC0, u32(_LCG_MULTIPLIER), 0x05, u32(_LCG_INCREMENT))
    a.emit(bytes.fromhex("894610837e0c00"))
    a.jcc(JNE, "wander")
    a.emit(0xB9, u32(frames[3] - frames[2] + 1), 0xBF, u32(frames[2]))
    a.jmp("duration")
    a.label("wander")
    a.emit(0xB9, u32(frames[1] - frames[0] + 1), 0xBF, u32(frames[0]))
    a.label("duration")
    a.emit(bytes.fromhex("89c2c1ea1031d0"))  # sample = state XOR (state >> 16)
    a.emit(0x31, 0xD2, 0xF7, 0xF1)  # unsigned div ecx: edx = sample % width
    a.emit(bytes.fromhex("01fa01da895608"))  # deadline = remainder + min + current frame
    a.label("phase")
    a.emit(bytes.fromhex("837e0c00"))
    a.jcc(JNE, "original")
    a.emit(0x61, 0x9D)
    a.jmp("fallthrough")
    a.label("original")
    a.emit(0x61, 0x9D)
    a.jmp_absolute(SLAVED_IDLE_GUARD)
    a.label("fallthrough")
    a.emit(bytes.fromhex("8b45f4"))
    a.jmp_absolute(SLAVED_IDLE_FALLTHROUGH)

    for site in (SLAVED_IDLE_CTOR, SLAVED_IDLE_DTOR, SLAVED_IDLE_XFER):
        hooks[site] = a.va
        a.emit(0x9C, 0x60)
        if site == SLAVED_IDLE_XFER:
            # Entry ESP + 36 + return address = xfer argument. The stock UpdateModule
            # snapshot uses virtual slot +4 as isLoading before resetting its wake frame.
            a.emit(bytes.fromhex("8b4c2428"))
            _save_fp(a)
            a.emit(bytes.fromhex("8b01ff5004"))
            _restore_fp(a)
            a.emit(0x84, 0xC0)
            a.jcc(JE, "xfer_restore")
            a.emit(bytes.fromhex("8b542418"))  # saved ECX (complete instance)
        else:
            a.emit(0x8B, 0xD1)
        a.call("lookup")
        a.emit(0x85, 0xF6)
        a.jcc(JE, f"restore_{site}")
        a.emit(0x39, 0x16)
        a.jcc(JNE, f"restore_{site}")
        a.emit(bytes.fromhex("c70601000000"))
        a.label(f"restore_{site}")
        if site == SLAVED_IDLE_XFER:
            a.label("xfer_restore")
        a.emit(0x61, 0x9D, SLAVED_IDLE_HOOKS[site])
        a.jmp_absolute(site + len(SLAVED_IDLE_HOOKS[site]))

    a.label("lookup")  # edx key -> esi existing or reusable slot, zero if full
    a.emit(bytes.fromhex("8bfa c1ef04 c1e705"))
    a.emit(0x81, 0xE7, u32((_SLOTS - 1) * _STRIDE))
    a.emit(0xB9, u32(_SLOTS), 0x31, 0xDB)
    a.label("probe")
    a.emit(0x8D, 0xB7, u32(base + TABLE_OFFSET))  # lea esi,[edi+table]
    a.emit(0x8B, 0x06, 0x39, 0xD0)
    a.jcc(JE, "found")
    a.emit(0x85, 0xC0)
    a.jcc(JE, "vacant")
    a.emit(0x83, 0xF8, 0x01)
    a.jcc(JNE, "advance")
    a.emit(0x85, 0xDB)
    a.jcc(JNE, "advance")
    a.emit(0x8B, 0xDE)  # remember first tombstone, keep looking for an existing key
    a.label("advance")
    a.emit(0x83, 0xC7, _STRIDE, 0x81, 0xE7, u32((_SLOTS - 1) * _STRIDE), 0x49)
    a.jcc(JNE, "probe")
    a.emit(0x8B, 0xF3, 0xC3)
    a.label("vacant")
    a.emit(0x85, 0xDB)
    a.jcc(JE, "found")
    a.emit(0x8B, 0xF3)
    a.label("found")
    a.emit(0xC3)
    return a.finish(), hooks


class SlavedUpdateIdlePatch(Patch):
    """Configure deterministic idle/wander ranges in simulation milliseconds for RotWK 2.01."""

    name = "slaved-update-idle"
    author = "Ostkannit"
    description = (
        "Alternate optional SlavedUpdate wandering with independent random rest intervals; "
        "deterministic simulation frames and ObjectID-seeded per-instance randomness. "
        "Milliseconds round up to 200-ms frames; no INI changes"
    )

    def __init__(
        self,
        wander_min_ms: int = 6000,
        wander_max_ms: int = 14191,
        idle_min_ms: int = 3000,
        idle_max_ms: int = 7095,
    ) -> None:
        self.intervals = (wander_min_ms, wander_max_ms, idle_min_ms, idle_max_ms)
        for name, value in zip(_PARAMETERS, self.intervals, strict=True):
            if type(value) is not int or not 1 <= value <= _MAX_MS:
                raise ValueError(f"{name} must be an integer in 1..{_MAX_MS} milliseconds")
        if wander_min_ms > wander_max_ms or idle_min_ms > idle_max_ms:
            raise ValueError("each minimum must be <= its maximum")

    def options(self) -> dict[str, object]:
        return dict(zip(_PARAMETERS, self.intervals, strict=True))

    def _section(self, base: int) -> bytes:
        header = b"SLVIDL02" + struct.pack("<4I", *self.intervals)
        return header.ljust(CODE_OFFSET, b"\0") + build_code(base, self.intervals)[0]

    @staticmethod
    def _check(data: bytes | bytearray, anchors: dict[int, bytes]) -> None:
        for va, expected in anchors.items():
            off = va_to_offset(data, va)
            if off is None or data[off : off + len(expected)] != expected:
                raise ValueError(
                    f"SlavedUpdate contract mismatch at {va:#010x}; "
                    "wrong build or conflicting patch"
                )

    def apply(self, data: bytearray) -> None:
        self._check(data, SLAVED_IDLE_ANCHORS | SLAVED_IDLE_HOOKS)
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError("SlavedUpdate idle section already exists")
        base = allocate_section(data, SECTION_NAME, self._section, 0xE0000060)
        for va, destination in build_code(base, self.intervals)[1].items():
            old = SLAVED_IDLE_HOOKS[va]
            off = va_to_offset(data, va)
            assert off is not None
            apply_byte_patch(
                data, off, old, jmp_rel32(va, destination) + b"\x90" * (len(old) - 5), self.name
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"missing {SECTION_NAME} section"]
        base, off, size = located
        expected = self._section(base)
        if size < len(expected) or data[off : off + len(expected)] != expected:
            return ["SlavedUpdate cave/configuration/state initializer mismatch"]
        try:
            self._check(data, SLAVED_IDLE_ANCHORS)
            self._check(
                data,
                {
                    va: jmp_rel32(va, dest) + b"\x90" * (len(SLAVED_IDLE_HOOKS[va]) - 5)
                    for va, dest in build_code(base, self.intervals)[1].items()
                },
            )
        except ValueError as exc:
            return [str(exc)]
        return []

    @classmethod
    def detect(cls, data: bytes | bytearray) -> SlavedUpdateIdlePatch | None:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        try:
            patch = cls(*struct.unpack_from("<4I", data, located[1] + 8))
            return None if patch.verify(data) else patch
        except (ValueError, struct.error):
            return None

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        for name, default in zip(_PARAMETERS, _DEFAULTS, strict=True):
            parser.add_argument(
                "--" + name.replace("_", "-"),
                type=int,
                default=default,
                help=f"inclusive simulation milliseconds (1..{_MAX_MS}), rounded up to 200 ms",
            )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> SlavedUpdateIdlePatch:
        return cls(*(getattr(args, name) for name in _PARAMETERS))
