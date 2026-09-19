"""Running as administrator on Windows: whether this process is, and starting it again as one.

Reading or hooking a game that runs elevated needs an elevated reader, so a tool that finds it
cannot open the game offers to restart itself through the UAC prompt (`ShellExecuteW` with the
`runas` verb) rather than asking the user to find the right shortcut.
"""

import ctypes
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

__all__ = ["is_elevated", "own_command", "relaunch_elevated"]

_SW_SHOWNORMAL = 1
# `ShellExecuteW` returns a value above this on success, an error code at or below it.
_SHELL_EXECUTE_OK = 32


def is_elevated() -> bool:
    """Whether this process runs as administrator; always False off Windows."""
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.WinDLL("shell32").IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def own_command() -> list[str]:
    """The command that started this process, without its arguments: the frozen executable, or
    the interpreter with its own options and the script, console-script launcher or `-m` module."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    arguments = len(sys.argv) - 1
    prefix = sys.orig_argv[: len(sys.orig_argv) - arguments] if arguments else sys.orig_argv
    # The interpreter by its full path: `orig_argv[0]` may be a bare `python` found on PATH.
    return [sys.executable, *prefix[1:]]


def relaunch_elevated(arguments: Sequence[str], cwd: Path | None = None) -> bool:
    """Start this program again as administrator with `arguments`, through the UAC prompt.
    False when it did not start - the prompt was declined, or this is not Windows. The caller
    closes itself on True."""
    if sys.platform != "win32":
        return False
    command = [*own_command(), *arguments]
    shell32 = ctypes.WinDLL("shell32")
    shell32.ShellExecuteW.restype = ctypes.c_void_p
    shell32.ShellExecuteW.argtypes = (
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_int,
    )
    result = shell32.ShellExecuteW(
        None,
        "runas",
        command[0],
        subprocess.list2cmdline(command[1:]),
        str(cwd if cwd is not None else os.getcwd()),
        _SW_SHOWNORMAL,
    )
    return (result or 0) > _SHELL_EXECUTE_OK
