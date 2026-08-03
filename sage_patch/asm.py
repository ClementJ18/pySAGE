"""A tiny x86 emitter with labels, for the code a patch puts in its cave.

Patches hand-assemble small routines. Done literally, a jump means counting bytes to its
target and a call means computing `target - (here + 5)` - and then keeping both correct as
the code around them changes. That arithmetic is invisible when wrong: the bytes assemble,
the patch applies, `verify` passes, and the game jumps into the middle of an instruction.

So branches are written against **labels** and resolved once the body is laid out. A label
that is never defined raises rather than assembling a plausible displacement, and a short
branch that will not reach raises rather than silently truncating.

This is deliberately not an assembler. Instructions are still emitted as literal bytes with
a comment saying what they are - only the address arithmetic is automated, because that is
the part that cannot be checked by reading.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

__all__ = [
    "JA",
    "JAE",
    "JB",
    "JBE",
    "JE",
    "JG",
    "JGE",
    "JL",
    "JLE",
    "JNAE",
    "JNB",
    "JNC",
    "JNE",
    "JNZ",
    "JZ",
    "Asm",
]

# Condition codes, as the low nibble of the 0x70/0x0F80 opcodes.
JB = JNAE = 0x2
JAE = JNB = JNC = 0x3
JE = JZ = 0x4
JNE = JNZ = 0x5
JBE = 0x6
JA = 0x7
JL = 0xC
JGE = 0xD
JLE = 0xE
JG = 0xF


@dataclass
class _Fixup:
    at: int  # where the displacement is written
    label: str
    next_ip: int  # offset of the instruction after this one
    width: int  # 1 for rel8, 4 for rel32


@dataclass
class Asm:
    """Emitted bytes plus the labels and fixups needed to resolve branches.

    `base_va` is the virtual address the first emitted byte will occupy, which is what makes
    `call_absolute` and `jmp_absolute` able to reach engine code.
    """

    base_va: int
    buf: bytearray = field(default_factory=bytearray)
    _labels: dict[str, int] = field(default_factory=dict)
    _fixups: list[_Fixup] = field(default_factory=list)

    @property
    def va(self) -> int:
        """The virtual address of the next byte to be emitted."""
        return self.base_va + len(self.buf)

    def emit(self, *chunks: bytes | int) -> Asm:
        """Append literal bytes. An `int` is one byte; `bytes` go through as-is."""
        for chunk in chunks:
            self.buf += bytes([chunk]) if isinstance(chunk, int) else chunk
        return self

    def label(self, name: str) -> Asm:
        if name in self._labels:
            raise ValueError(f"duplicate label {name!r}")
        self._labels[name] = len(self.buf)
        return self

    def label_va(self, name: str) -> int:
        """The virtual address a defined label sits at.

        A cave with several routines has to tell the engine where each one starts, and the only
        honest source for that is the layout that was actually emitted - counting the bytes a
        second time by hand is the arithmetic this module exists to remove."""
        if name not in self._labels:
            raise ValueError(f"undefined label {name!r}")
        return self.base_va + self._labels[name]

    def jmp(self, name: str) -> Asm:
        """`jmp rel32` to a label."""
        self.emit(0xE9)
        return self._fixup(name, 4)

    def jcc(self, condition: int, name: str) -> Asm:
        """`jcc rel32` to a label. Always near - a short branch that grows out of range as
        the body changes is exactly the failure this module exists to prevent, so widening
        is the default and shortening is opt-in."""
        self.emit(0x0F, 0x80 | condition)
        return self._fixup(name, 4)

    def call(self, name: str) -> Asm:
        """`call rel32` to a label - a routine inside this same cave.

        The sibling of :meth:`call_absolute`, which reaches engine code at a known address. A
        cave with more than one routine cannot use that form for its own internals: the callee's
        address is not known until the body it lives in has been laid out, which is the whole
        reason labels exist here."""
        self.emit(0xE8)
        return self._fixup(name, 4)

    def jmp_short(self, name: str) -> Asm:
        """`jmp rel8`. Raises at `finish` if the target is out of range."""
        self.emit(0xEB)
        return self._fixup(name, 1)

    def jcc_short(self, condition: int, name: str) -> Asm:
        """`jcc rel8`. Raises at `finish` if the target is out of range."""
        self.emit(0x70 | condition)
        return self._fixup(name, 1)

    def _fixup(self, name: str, width: int) -> Asm:
        self._fixups.append(_Fixup(len(self.buf), name, len(self.buf) + width, width))
        self.emit(b"\x00" * width)
        return self

    def call_absolute(self, va: int) -> Asm:
        """`call rel32` to a fixed virtual address - engine code outside the cave."""
        self.emit(0xE8, struct.pack("<i", va - (self.va + 5)))
        return self

    def jmp_absolute(self, va: int) -> Asm:
        """`jmp rel32` to a fixed virtual address - typically the hook's return point."""
        self.emit(0xE9, struct.pack("<i", va - (self.va + 5)))
        return self

    def finish(self) -> bytes:
        """Resolve every branch and return the code."""
        for fixup in self._fixups:
            if fixup.label not in self._labels:
                raise ValueError(f"undefined label {fixup.label!r}")
            displacement = self._labels[fixup.label] - fixup.next_ip
            if fixup.width == 1:
                if not -128 <= displacement <= 127:
                    raise ValueError(
                        f"short branch to {fixup.label!r} needs {displacement} bytes, "
                        "which does not fit in rel8 - use the near form"
                    )
                struct.pack_into("<b", self.buf, fixup.at, displacement)
            else:
                struct.pack_into("<i", self.buf, fixup.at, displacement)
        return bytes(self.buf)
