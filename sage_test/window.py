"""The game's window, from outside: find it, bring it forward, switch away and back, capture it.

Some things a test checks only happen to a window - a single-player game pauses its logic while
it is in the background, a device reset follows an Alt+Tab, a menu click lands where the window
is - so a test needs the window as well as the process. This finds it by the engine's own window
class rather than by size or enumeration order: launched with `-scriptDebug2`, the process also
owns the script debugger's dialog, which is visible, large, and enumerated first.

Windows only, checked per call rather than at import, so `sage_test` imports anywhere.
"""

from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

__all__ = [
    "SAGE_WINDOW_CLASS",
    "alt_tab",
    "alt_tab_in",
    "alt_tab_out",
    "bring_to_front",
    "capture_client",
    "game_window",
    "windows_of",
]

#: The window class RotWK's 3D window registers.
SAGE_WINDOW_CLASS = "E99E8455-CC9B-488a-BA22-0E8A8F74F9FA"

_VK_MENU, _VK_TAB, _KEYEVENTF_KEYUP = 0x12, 0x09, 0x2
_SW_RESTORE = 9
_SM_XVIRTUALSCREEN, _SM_YVIRTUALSCREEN = 76, 77


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _user32() -> ctypes.CDLL:
    if sys.platform != "win32":
        raise RuntimeError(f"the game's window needs Windows; this is {sys.platform}")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.ClientToScreen.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    return user32


def windows_of(pid: int) -> list[tuple[int, str, int, int]]:
    """Every visible top-level window the process owns, as `(hwnd, class, width, height)`."""
    user32 = _user32()
    found: list[tuple[int, str, int, int]] = []
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def visit(hwnd: int, _lparam: int) -> bool:
        owner = ctypes.c_uint32()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            rect = _Rect()
            user32.GetClientRect(hwnd, ctypes.byref(rect))
            name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, name, 256)
            found.append((hwnd, name.value, rect.right, rect.bottom))
        return True

    user32.EnumWindows(enum_proc(visit), 0)
    return found


def game_window(pid: int) -> int | None:
    """The 3D game window of process `pid`, matched on the engine's window class, or None.

    Not the biggest visible window and not the first: the `-scriptDebug2` dialog is both. Another
    SAGE build registers a different GUID as its class, so a GUID-shaped class on a window of
    real size is taken as well.
    """
    for hwnd, class_name, width, height in windows_of(pid):
        if class_name == SAGE_WINDOW_CLASS:
            return hwnd
        if class_name.count("-") == 4 and width > 200 and height > 200:
            return hwnd
    return None


def _tap(user32: ctypes.CDLL, key: int) -> None:
    user32.keybd_event(key, 0, 0, 0)
    user32.keybd_event(key, 0, _KEYEVENTF_KEYUP, 0)


def bring_to_front(hwnd: int) -> None:
    """Restore the window and make it the foreground one, as a click on it would.

    Only the process that sent the last input may hand the foreground over, so an Alt tap goes
    first and makes this process that one.
    """
    user32 = _user32()
    user32.ShowWindow(hwnd, _SW_RESTORE)
    _tap(user32, _VK_MENU)
    user32.SetForegroundWindow(hwnd)


def alt_tab() -> None:
    """Alt+Tab as a player presses it: Alt held, Tab tapped, Alt let go."""
    user32 = _user32()
    user32.keybd_event(_VK_MENU, 0, 0, 0)
    time.sleep(0.05)
    _tap(user32, _VK_TAB)
    time.sleep(0.1)
    user32.keybd_event(_VK_MENU, 0, _KEYEVENTF_KEYUP, 0)


def alt_tab_out(hwnd: int) -> bool:
    """Alt+Tab away from the game; whether it lost the foreground."""
    alt_tab()
    time.sleep(0.5)
    return _user32().GetForegroundWindow() != hwnd


def alt_tab_in(hwnd: int, timeout: float = 3.0) -> bool:
    """Alt+Tab back to the game; True when that alone gave it the foreground. When it did not -
    Alt+Tab goes to whichever window was used last - the game is brought back as a click would,
    and this says False."""
    alt_tab()
    user32 = _user32()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.1)
    bring_to_front(hwnd)
    return False


def capture_client(hwnd: int, path: Path) -> None:
    """Save the window's client area as an image, for reading back what a click landed on.

    Needs Pillow (the `ui` extra), and grabs the screen rather than the window, so the window
    has to be in front and on screen.
    """
    try:
        from PIL import ImageGrab  # noqa: PLC0415 - optional, behind the `ui` extra
    except ImportError as exc:
        raise RuntimeError(
            "capturing the window needs Pillow: pip install pysage-tools[ui]"
        ) from exc
    user32 = _user32()
    rect, corner = _Rect(), _Point(0, 0)
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    user32.ClientToScreen(hwnd, ctypes.byref(corner))
    left = user32.GetSystemMetrics(_SM_XVIRTUALSCREEN)
    top = user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)
    screen = ImageGrab.grab(all_screens=True)
    x, y = corner.x - left, corner.y - top
    screen.crop((x, y, x + rect.right, y + rect.bottom)).save(path)
