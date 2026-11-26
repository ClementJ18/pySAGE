"""Exit the server when the agent client that started it is gone.

A stdio server normally stops when its client closes the pipe, but a client that crashes or is
killed on Windows can leave the pipe open (another child inherited the handle), and the server
then runs forever. So the server also watches the client process itself.

The client is the first ancestor that is not one of our own launchers: the venv's
`sage-worldbuilder-mcp.exe` shim, the venv's `python.exe` redirector and PyInstaller's onefile
bootloader each start a child and wait on it, so they outlive the client just as the server does.
A launcher is an ancestor named like the shim, or running the same image as this process.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from collections.abc import Callable
from ctypes import wintypes

__all__ = ["exit_with_client"]

_LAUNCHER_PREFIX = "sage-worldbuilder-mcp"
_SYNCHRONIZE = 0x00100000
_INFINITE = 0xFFFFFFFF
_TH32CS_SNAPPROCESS = 0x2
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _process_table() -> dict[int, tuple[int, str]]:
    """`{pid: (parent pid, exe name)}` for every running process."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    table: dict[int, tuple[int, str]] = {}
    entry = _ProcessEntry()
    entry.dwSize = ctypes.sizeof(_ProcessEntry)
    try:
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            table[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile)
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return table


def _image_path(pid: int) -> str | None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return buffer.value
    finally:
        kernel32.CloseHandle(handle)


def _same_file(a: str | None, b: str) -> bool:
    return a is not None and os.path.normcase(os.path.abspath(a)) == os.path.normcase(
        os.path.abspath(b)
    )


def client_pid(
    table: dict[int, tuple[int, str]],
    parent: int,
    is_launcher: Callable[[int, str], bool],
) -> int:
    """The nearest ancestor from `parent` up for which `is_launcher(pid, exe name)` is false."""
    pid = parent
    seen: set[int] = set()
    while pid in table and pid not in seen and is_launcher(pid, table[pid][1]):
        seen.add(pid)
        pid = table[pid][0]
    return pid


def _is_launcher(pid: int, name: str) -> bool:
    if name.lower().startswith(_LAUNCHER_PREFIX):
        return True
    return _same_file(_image_path(pid), sys.executable)


def exit_with_client() -> None:
    """Start a daemon thread that ends the process once the client process exits. Windows only."""
    if sys.platform != "win32":
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    pid = client_pid(_process_table(), os.getppid(), _is_launcher)
    # Opening the handle now pins the process object, so a reused pid cannot fool the wait.
    handle = kernel32.OpenProcess(_SYNCHRONIZE, False, pid)
    if not handle:
        return

    def wait() -> None:
        kernel32.WaitForSingleObject(wintypes.HANDLE(handle), _INFINITE)
        os._exit(0)

    threading.Thread(target=wait, name="exit-with-client", daemon=True).start()
