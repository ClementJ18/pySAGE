"""How much of its 32-bit address space a running game is using.

`game.dat` is a 32-bit process, and with the large-address-aware flag it has 4 GB to map into:
the 2 GB below `0x80000000` it always had, and 2 GB above. What runs out first under a large army
is that space, not physical memory - so a measurement samples it, below and above the line
separately, because anything that cannot use the upper half (an old allocator, a DLL built
without the flag) fails once the lower one is full however much is free above.

Windows only, checked per call, so `sage_test` imports anywhere.
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass

__all__ = ["AddressSpace", "address_space"]

_PROCESS_QUERY_INFORMATION = 0x0400
_MEM_FREE = 0x10000
_TWO_GB, _TOP, _FIRST = 0x80000000, 0x100000000, 0x10000
_MB = 1 << 20


class _MemoryBasicInformation(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_uint64),
        ("AllocationBase", ctypes.c_uint64),
        ("AllocationProtect", ctypes.c_uint32),
        ("PartitionId", ctypes.c_uint16),
        ("RegionSize", ctypes.c_uint64),
        ("State", ctypes.c_uint32),
        ("Protect", ctypes.c_uint32),
        ("Type", ctypes.c_uint32),
    ]


@dataclass(frozen=True, slots=True)
class AddressSpace:
    """Address space in MB: in use below 2 GB, in use above it, and free in all."""

    low: int
    high: int
    free: int

    @property
    def in_use(self) -> int:
        return self.low + self.high


def address_space(pid: int) -> AddressSpace:
    """Walk the 32-bit address space of process `pid`, region by region."""
    if sys.platform != "win32":
        raise RuntimeError(
            f"reading a process's address space needs Windows; this is {sys.platform}"
        )
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
    k32.VirtualQueryEx.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    k32.VirtualQueryEx.restype = ctypes.c_size_t
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = k32.OpenProcess(_PROCESS_QUERY_INFORMATION, False, pid)
    if not handle:
        raise OSError(ctypes.get_last_error(), f"cannot open process {pid}")
    low = high = free = 0
    address = _FIRST
    region = _MemoryBasicInformation()
    try:
        while address < _TOP and k32.VirtualQueryEx(
            handle, address, ctypes.byref(region), ctypes.sizeof(region)
        ):
            base, end = region.BaseAddress, region.BaseAddress + region.RegionSize
            if region.State == _MEM_FREE:
                free += end - base
            else:
                below = max(0, min(end, _TWO_GB) - base)
                low += below
                high += (end - base) - below
            address = end
    finally:
        k32.CloseHandle(handle)
    return AddressSpace(low // _MB, high // _MB, free // _MB)
