"""A patched `game.dat` in Unicorn, for running the save-path caves and the engine code around them.

`score-keeper-dangling-keys` and `save-temp-file` change what a save writes and where. Neither
change raises when it is wrong: a count one off, a skipped entry that was live, a rename to the
wrong path all apply, verify and load the game. So the tests execute them. `Machine` maps every
section of an image, a heap, a stack and a thread block (for the `fs:[0]` SEH chain the engine's
prologues push), and runs one routine at a time; any engine routine a test does not want to
execute is answered in Python with `stub`.

Over the real `game.dat` it runs the engine's own `xferObjectCountMap` and score merge with the
patch in place, which is the point: the cave and the stock code it returns into, together. Over a
synthetic stand-in only the caves exist, and the engine routines they call are stubbed.
"""

from __future__ import annotations

import faulthandler
import struct
from collections.abc import Callable
from dataclasses import dataclass, field

import pefile
from unicorn import (
    UC_ARCH_X86,
    UC_HOOK_CODE,
    UC_HOOK_MEM_READ_UNMAPPED,
    UC_HOOK_MEM_WRITE_UNMAPPED,
    UC_MODE_32,
    Uc,
)
from unicorn.x86_const import (
    UC_X86_REG_DS,
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EDX,
    UC_X86_REG_EIP,
    UC_X86_REG_ES,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
    UC_X86_REG_FS,
    UC_X86_REG_GDTR,
    UC_X86_REG_GS,
    UC_X86_REG_SS,
)

HEAP = 0x10000000
HEAP_SIZE = 0x200000
STACK = 0x20000000
STACK_SIZE = 0x40000
#: Where a routine run from Python returns to. Mapped, and stopped at.
RETURN = 0x30000000
TEB = 0x31000000
#: Addresses `stub` hands out for vtable slots and import entries that have no engine code.
STUBS = 0x32000000
#: A one-entry descriptor table, so `fs` can address `TEB` the way Windows sets it up.
GDT = 0x33000000
PAGE = 0x1000

REGISTERS = {
    "eax": UC_X86_REG_EAX,
    "ebx": UC_X86_REG_EBX,
    "ecx": UC_X86_REG_ECX,
    "edx": UC_X86_REG_EDX,
    "esi": UC_X86_REG_ESI,
    "edi": UC_X86_REG_EDI,
    "ebp": UC_X86_REG_EBP,
}


@dataclass
class Machine:
    image: bytes
    uc: Uc = field(init=False)
    _heap: int = field(init=False, default=HEAP)
    _next_stub: int = field(init=False, default=STUBS)
    stopped_at: int | None = field(init=False, default=None)
    #: Every unmapped address a run read or wrote, in order - what a fault was a fault on.
    faults: list[int] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        pe = pefile.PE(data=bytes(self.image), fast_load=True)
        base = pe.OPTIONAL_HEADER.ImageBase
        # `mem_map` raises and catches an SEH fault inside Unicorn on Windows; quiet the handler.
        was_enabled = faulthandler.is_enabled()
        faulthandler.disable()
        try:
            for section in pe.sections:
                size = max(section.Misc_VirtualSize, len(section.get_data()))
                start = base + section.VirtualAddress
                self._map(start & ~0xFFF, ((start + size + 0xFFF) & ~0xFFF) - (start & ~0xFFF))
                self.uc.mem_write(start, section.get_data())
            self._map(HEAP, HEAP_SIZE)
            self._map(STACK, STACK_SIZE)
            self._map(RETURN, PAGE)
            self._map(TEB, PAGE)
            self._map(STUBS, PAGE)
            self._map(GDT, PAGE)
        finally:
            if was_enabled:
                faulthandler.enable()
        self._point_fs_at_teb()
        self.write32(TEB, 0xFFFFFFFF)  # the end of the SEH chain

        def fault(_uc: Uc, _access: int, address: int, _size: int, _value: int, _u: object) -> bool:
            self.faults.append(address)
            return False

        self.uc.hook_add(UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED, fault)
        self._stops: set[int] = set()

    def _point_fs_at_teb(self) -> None:
        """Load a descriptor table the way Windows has one: flat 32-bit data for `ss`, `ds`, `es`
        and `gs`, and `fs` based at `TEB`. The engine's prologues push and pop the SEH chain
        through `fs:[0]`; without a 32-bit `ss` descriptor the stack would turn 16-bit."""

        def descriptor(base: int, limit: int, granular: bool) -> bytes:
            access = 0x80 | 0x10 | 0x02  # present | data | writable, ring 0
            flags = 0x4 | (0x8 if granular else 0)  # 32-bit, page granularity
            value = (
                (limit & 0xFFFF)
                | (base & 0xFFFFFF) << 16
                | access << 40
                | ((limit >> 16) & 0xF) << 48
                | flags << 52
                | ((base >> 24) & 0xFF) << 56
            )
            return struct.pack("<Q", value)

        self.uc.mem_write(GDT + 8, descriptor(0, 0xFFFFF, granular=True))
        self.uc.mem_write(GDT + 16, descriptor(TEB, PAGE - 1, granular=False))
        self.uc.reg_write(UC_X86_REG_GDTR, (0, GDT, 3 * 8 - 1, 0))
        for register in (UC_X86_REG_SS, UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_GS):
            self.uc.reg_write(register, 1 << 3)
        self.uc.reg_write(UC_X86_REG_FS, 2 << 3)

    def _map(self, start: int, size: int) -> None:
        end = start + size
        overlapping = [(b, e) for b, e, _p in self.uc.mem_regions() if b < end and e >= start]
        if not overlapping:
            self.uc.mem_map(start, size)
            return
        for page in range(start, end, PAGE):
            if not any(b <= page <= e for b, e in overlapping):
                self.uc.mem_map(page, PAGE)

    def ensure(self, va: int) -> None:
        """Map the page `va` is on, if nothing is mapped there - for a global or a routine the
        stand-in image does not carry."""
        self._map(va & ~0xFFF, PAGE)

    def alloc(self, size: int, data: bytes | None = None) -> int:
        at = self._heap
        self._heap += (size + 15) & ~15
        assert self._heap <= HEAP + HEAP_SIZE, "the synthetic heap is full"
        if data is not None:
            self.uc.mem_write(at, data)
        return at

    def read32(self, at: int) -> int:
        return struct.unpack("<I", self.uc.mem_read(at, 4))[0]

    def write32(self, at: int, value: int) -> None:
        self.uc.mem_write(at, struct.pack("<I", value & 0xFFFFFFFF))

    def reg(self, name: str) -> int:
        return self.uc.reg_read(REGISTERS[name])

    def arg(self, index: int) -> int:
        """Argument `index` of a routine just entered (return address at `[esp]`)."""
        return self.read32(self.uc.reg_read(UC_X86_REG_ESP) + 4 + 4 * index)

    def ret(self, pop: int = 0, value: int | None = None) -> None:
        """Return from a stubbed routine, popping `pop` bytes of arguments."""
        esp = self.uc.reg_read(UC_X86_REG_ESP)
        self.uc.reg_write(UC_X86_REG_EIP, self.read32(esp))
        self.uc.reg_write(UC_X86_REG_ESP, esp + 4 + pop)
        if value is not None:
            self.uc.reg_write(UC_X86_REG_EAX, value & 0xFFFFFFFF)

    def stub(self, va: int | None, handler: Callable[[Machine], None]) -> int:
        """Answer the routine at `va` in Python; with `va` None, at a fresh address, which is
        returned - for a vtable slot or an import entry. `handler` must end with `ret`."""
        if va is None:
            va = self._next_stub
            self._next_stub += 0x10
        self.ensure(va)
        self.uc.mem_write(va, b"\xcc")  # never executed: the hook moves eip first

        def hook(_uc: Uc, _address: int, _size: int, _user: object) -> None:
            handler(self)

        self.uc.hook_add(UC_HOOK_CODE, hook, begin=va, end=va)
        return va

    def stop_at(self, *vas: int) -> None:
        """End `run` when execution reaches any of `vas`, recording which in `stopped_at`."""
        for va in vas:
            if va in self._stops:
                continue
            self._stops.add(va)
            self.ensure(va)

            def hook(uc: Uc, address: int, _size: int, _user: object) -> None:
                self.stopped_at = address
                uc.emu_stop()

            self.uc.hook_add(UC_HOOK_CODE, hook, begin=va, end=va)

    def call(self, va: int, *args: int, **registers: int) -> int:
        """Call the routine at `va` with stack `args` (pushed right to left) and the given
        registers, run it until it returns to `RETURN` or reaches a `stop_at` address, and return
        `eax`."""
        esp = STACK + STACK_SIZE - 0x1000
        for value in reversed(args):
            esp -= 4
            self.write32(esp, value)
        esp -= 4
        self.write32(esp, RETURN)
        return self.run(va, esp, **registers)

    def run(self, va: int, esp: int, **registers: int) -> int:
        self.uc.reg_write(UC_X86_REG_ESP, esp)
        for name, value in registers.items():
            self.uc.reg_write(REGISTERS[name], value)
        self.stopped_at = None
        self.stop_at(RETURN)
        self.uc.emu_start(va, RETURN, count=5_000_000)
        if self.stopped_at is None and self.uc.reg_read(UC_X86_REG_EIP) == RETURN:
            self.stopped_at = RETURN  # reaching `until` ends the run without the hook firing
        return self.reg("eax")

    def frame(self, size: int = 0x100) -> int:
        """A zeroed region to point `ebp` at for a mid-function routine, with `size` bytes on both
        sides; returns the `ebp` value."""
        return self.alloc(2 * size, b"\x00" * (2 * size)) + size

    def wide(self, text: str) -> int:
        return self.alloc(2 * len(text) + 2, text.encode("utf-16-le") + b"\x00\x00")

    def read_wide(self, at: int) -> str:
        out = bytearray()
        while True:
            pair = bytes(self.uc.mem_read(at + len(out), 2))
            if pair == b"\x00\x00":
                return out.decode("utf-16-le")
            out += pair
