"""Patching a running game in memory: allocate a cave, redirect a call into it, undo it on detach.

`sage_patch` rewrites `game.dat` on disk, which only helps a game started afterwards. Attaching to
a game that is already running - the script debugger's case - means putting the hooks into the
live process instead. Nothing here touches the file, so the worst a mistake can do is crash the
match, never break the install.

Three rules make it safe enough to do to a game someone is playing:

- **Every hook is checked before it is written.** A site must hold exactly the bytes the caller
  says the stock build has, or exactly the bytes this would write (a hook left by an earlier
  session). Anything else - another build, another tool's hook - refuses the whole attach.
- **The process is suspended around each code write.** A redirected `call` is five bytes that a
  thread could otherwise fetch half-old, half-new; with every thread stopped there is no such
  window, whatever the site's alignment.
- **Detach restores what attach changed**, and only where the site still holds this patcher's
  bytes, so it never reverts someone else's later edit.

The process layer is a protocol so the bookkeeping is testable without Windows or a game.
"""

from __future__ import annotations

import ctypes
import struct
import sys
import time
from dataclasses import dataclass
from typing import Protocol

__all__ = [
    "LivePatchError",
    "LivePatcher",
    "LiveProcess",
    "ProcessGone",
    "WindowsProcess",
    "allocation_base",
    "call_bytes",
    "call_target",
]

_CALL = 0xE8


class LivePatchError(RuntimeError):
    """A hook site is not in a state this patcher may write, or the process refused a request."""


class ProcessGone(LivePatchError):
    """The process has exited or is exiting. Its hooks and caves went with it, so there is
    nothing left to undo - which makes this the one failure detaching treats as success."""


class LiveProcess(Protocol):
    """What patching needs from a process. `write_code` lifts page protection; `write` does not."""

    def read(self, address: int, size: int) -> bytes | None: ...

    def write(self, address: int, data: bytes) -> bool: ...

    def write_code(self, address: int, data: bytes) -> bool: ...

    def alloc(self, size: int) -> int: ...

    def free(self, address: int) -> None: ...

    def suspend(self) -> None: ...

    def resume(self) -> None: ...

    def close(self) -> None: ...


# `VirtualAllocEx` hands out whole allocation-granularity blocks, so a cave's head is the 64 KB
# boundary at or below any address inside it - whatever layout the cave has.
_GRANULARITY = 0x10000


def allocation_base(address: int) -> int:
    """The head of the cave `address` is inside."""
    return address & ~(_GRANULARITY - 1)


def call_bytes(site: int, target: int) -> bytes:
    """A 5-byte `call rel32` at `site` reaching `target`."""
    return bytes([_CALL]) + struct.pack("<i", _rel32(target - (site + 5)))


def call_target(site: int, code: bytes) -> int | None:
    """Where the `call rel32` in `code` (read from `site`) goes, or None if it is not one."""
    if len(code) != 5 or code[0] != _CALL:
        return None
    (rel,) = struct.unpack("<i", code[1:])
    return (site + 5 + rel) & 0xFFFFFFFF


def _rel32(value: int) -> int:
    # A 32-bit process wraps, so any two addresses are within reach of each other.
    value &= 0xFFFFFFFF
    return value - (1 << 32) if value & 0x80000000 else value


@dataclass
class _Hook:
    site: int
    stock: bytes
    ours: bytes


class LivePatcher:
    """The hooks and caves one attach put into one process, and the way to take them out again."""

    def __init__(self, process: LiveProcess) -> None:
        self.process = process
        self._hooks: list[_Hook] = []
        self._caves: list[int] = []
        # Set once the process is found to have exited: nothing is restored or freed after that.
        self._gone = False

    def allocate(self, size: int) -> int:
        """Executable memory in the target, owned by this patcher until `close`."""
        address = self.process.alloc(size)
        self._caves.append(address)
        return address

    def adopt(self, address: int) -> None:
        """Take over a cave an earlier session left behind, so it is not allocated twice."""
        self._caves.append(address)

    def hook(self, site: int, stock: bytes, ours: bytes) -> bool:
        """Write `ours` over `stock` at `site`. False when `ours` was already there.

        Raises unless the site holds one of the two, which is the check that stops a wrong build
        or a foreign hook from being overwritten.
        """
        if len(stock) != len(ours):
            raise ValueError("a hook must replace its site byte for byte")
        self.process.suspend()
        try:
            current = self.process.read(site, len(stock))
            if current == ours:
                self._hooks.append(_Hook(site, stock, ours))
                return False
            if current != stock:
                found = current.hex() if current else "unreadable"
                raise LivePatchError(
                    f"0x{site:08X} holds {found}, expected the stock {stock.hex()} - "
                    "another build, or another tool's hook"
                )
            if not self.process.write_code(site, ours):
                raise LivePatchError(f"writing the hook at 0x{site:08X} failed")
            self._hooks.append(_Hook(site, stock, ours))
            return True
        finally:
            self.process.resume()

    def unhook_all(self) -> list[str]:
        """Restore every site this patcher hooked. Returns a note per site it had to leave alone."""
        notes: list[str] = []
        if not self._hooks:
            return notes
        try:
            self.process.suspend()
        except ProcessGone:
            self._hooks.clear()
            self._gone = True
            return notes
        try:
            for hook in reversed(self._hooks):
                current = self.process.read(hook.site, len(hook.ours))
                if current != hook.ours:
                    notes.append(f"0x{hook.site:08X} was changed by something else; left as is")
                elif not self.process.write_code(hook.site, hook.stock):
                    notes.append(f"restoring 0x{hook.site:08X} failed")
        finally:
            self.process.resume()
        self._hooks.clear()
        return notes

    def close(self, free_caves: bool = True) -> list[str]:
        """Unhook, then release the caves. A cave is freed only once nothing can call into it."""
        notes = self.unhook_all()
        if free_caves and not notes and not self._gone:
            # A thread already inside a cave when its call site was restored leaves within a few
            # instructions; this is far longer than that.
            time.sleep(0.1)
            for cave in self._caves:
                self.process.free(cave)
        self._caves.clear()
        return notes


class WindowsProcess:
    """`LiveProcess` over a Win32 handle with the rights patching needs."""

    # VM_OPERATION | VM_READ | VM_WRITE | QUERY_INFORMATION | SUSPEND_RESUME
    _ACCESS = 0x0008 | 0x0010 | 0x0020 | 0x0400 | 0x0800
    _MEM_COMMIT_RESERVE = 0x1000 | 0x2000
    _MEM_RELEASE = 0x8000
    _PAGE_EXECUTE_READWRITE = 0x40
    # `NtSuspendProcess` on a process that is shutting down, and `GetExitCodeProcess`'s answer
    # for one still running.
    _STATUS_PROCESS_IS_TERMINATING = 0xC000010A
    _STILL_ACTIVE = 259

    # Declared rather than inferred: below the platform check is unreachable to a type checker
    # running as Linux, which would otherwise leave these untyped.
    _k32: ctypes.CDLL
    _ntdll: ctypes.CDLL
    _handle: int | None

    def __init__(self, pid: int) -> None:
        if sys.platform != "win32":
            raise RuntimeError(f"patching a live game needs Windows; this is {sys.platform}")
        self.pid = pid
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ntdll = ctypes.WinDLL("ntdll")
        handle_t, void_p, size_t = ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t
        k32.OpenProcess.restype = handle_t
        k32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        for name in ("ReadProcessMemory", "WriteProcessMemory"):
            getattr(k32, name).argtypes = (
                handle_t,
                void_p,
                void_p,
                size_t,
                ctypes.POINTER(size_t),
            )
        k32.VirtualProtectEx.argtypes = (
            handle_t,
            void_p,
            size_t,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        )
        k32.VirtualAllocEx.restype = void_p
        k32.VirtualAllocEx.argtypes = (handle_t, void_p, size_t, ctypes.c_uint32, ctypes.c_uint32)
        k32.VirtualFreeEx.argtypes = (handle_t, void_p, size_t, ctypes.c_uint32)
        k32.FlushInstructionCache.argtypes = (handle_t, void_p, size_t)
        k32.CloseHandle.argtypes = (handle_t,)
        k32.GetExitCodeProcess.argtypes = (handle_t, ctypes.POINTER(ctypes.c_uint32))
        ntdll.NtSuspendProcess.argtypes = (handle_t,)
        ntdll.NtResumeProcess.argtypes = (handle_t,)
        self._k32, self._ntdll = k32, ntdll
        handle = k32.OpenProcess(self._ACCESS, 0, pid)
        if not handle:
            err = ctypes.get_last_error()
            hint = " - the game runs as administrator, so this must be elevated" if err == 5 else ""
            raise PermissionError(f"OpenProcess({pid}) failed with error {err}{hint}")
        self._handle = handle

    def read(self, address: int, size: int) -> bytes | None:
        if self._handle is None or size <= 0:
            return None
        buf = (ctypes.c_ubyte * size)()
        got = ctypes.c_size_t()
        ok = self._k32.ReadProcessMemory(
            self._handle, ctypes.c_void_p(address), buf, size, ctypes.byref(got)
        )
        return bytes(buf) if ok and got.value == size else None

    def write(self, address: int, data: bytes) -> bool:
        if self._handle is None or not data:
            return False
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        put = ctypes.c_size_t()
        ok = self._k32.WriteProcessMemory(
            self._handle, ctypes.c_void_p(address), buf, len(data), ctypes.byref(put)
        )
        return bool(ok) and put.value == len(data)

    def write_code(self, address: int, data: bytes) -> bool:
        old = ctypes.c_uint32()
        where = ctypes.c_void_p(address)
        if not self._k32.VirtualProtectEx(
            self._handle, where, len(data), self._PAGE_EXECUTE_READWRITE, ctypes.byref(old)
        ):
            return False
        ok = self.write(address, data)
        self._k32.VirtualProtectEx(self._handle, where, len(data), old, ctypes.byref(old))
        self._k32.FlushInstructionCache(self._handle, where, len(data))
        return ok

    def alloc(self, size: int) -> int:
        address = self._k32.VirtualAllocEx(
            self._handle, None, size, self._MEM_COMMIT_RESERVE, self._PAGE_EXECUTE_READWRITE
        )
        if not address:
            assert sys.platform == "win32"  # `__init__` refused anything else; narrows for mypy
            raise LivePatchError(f"VirtualAllocEx failed with error {ctypes.get_last_error()}")
        return int(address)

    def free(self, address: int) -> None:
        self._k32.VirtualFreeEx(self._handle, ctypes.c_void_p(address), 0, self._MEM_RELEASE)

    def exited(self) -> bool:
        """Whether the process has exited, which a handle to it can still ask."""
        code = ctypes.c_uint32()
        if not self._k32.GetExitCodeProcess(self._handle, ctypes.byref(code)):
            return True
        return code.value != self._STILL_ACTIVE

    def suspend(self) -> None:
        status = self._ntdll.NtSuspendProcess(self._handle) & 0xFFFFFFFF
        if status == 0:
            return
        if status == self._STATUS_PROCESS_IS_TERMINATING or self.exited():
            raise ProcessGone("the game has exited")
        raise LivePatchError(f"NtSuspendProcess failed with status 0x{status:08X}")

    def resume(self) -> None:
        self._ntdll.NtResumeProcess(self._handle)

    def close(self) -> None:
        if self._handle is not None:
            self._k32.CloseHandle(self._handle)
            self._handle = None
