"""Bracketing a run with an OBS recording, by pressing the key a human would press.

**A hotkey rather than the WebSocket API, because the hotkey needs nothing set up.** OBS ships
its WebSocket server disabled and behind a generated password, so an API client is two pieces of
configuration and a dependency before it can do anything at all; F8 is `Start/Stop Recording` out
of the box. The cost is that this is fire-and-forget - a keystroke reports nothing back, so
nothing here can confirm that a recording actually began.

**OBS registers F8 globally**, which is the whole reason this works: the game is the foreground
window for the entire run and would otherwise swallow the key. A global hotkey is claimed with a
low-level hook that sees synthetic input the same as real input, so it fires while BFME has
focus. It also means the press is not private - anything else listening for F8 hears it too.

The one failure that matters is a recording left running after the bot exits, so `stop` is
called from a `finally` and is idempotent: a run killed with Ctrl-C, a crash mid-cycle and an
ordinary victory all end the recording exactly once.
"""

from __future__ import annotations

import ctypes
import sys
import time

from sage_live.backends.memory import find_game_processes

__all__ = ["OBS_PROCESS", "Recorder"]

# What OBS Studio's 64-bit build is called in the process table. `find_game_processes` matches
# the executable name exactly, and it is not the game's - the name of that helper is about where
# it lives rather than what it can look for.
OBS_PROCESS = "obs64.exe"

_VK_F8 = 0x77
_KEYEVENTF_KEYUP = 0x0002
_INPUT_KEYBOARD = 1
# Long enough for a hook to see a real press rather than an instantaneous blip, short enough not
# to be felt in a run. OBS debounces nothing, so the two presses of a run must also be far apart
# in time - which they are by construction, being a whole match apart.
_HOLD = 0.05


# Fixed-width types rather than `ctypes.wintypes`, which is only accidentally right here: it
# spells `DWORD` as `c_ulong` and `LONG` as `c_long`, both of which are 8 bytes on a 64-bit Linux
# host and 4 on Windows. Windows defines these as exactly 32 and 16 bits, so saying so gives the
# layout Windows demands on whatever machine reads this file - which is what lets the size test
# below guard the layout on a Linux CI runner instead of measuring that runner's own C compiler.
# `dwExtraInfo` is `ULONG_PTR`, pointer-sized by definition, so a pointer type is right as-is.
class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_int32),
        ("dy", ctypes.c_int32),
        ("mouseData", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_uint16),
        ("wScan", ctypes.c_uint16),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUTUNION(ctypes.Union):
    # **`mi` is here because of its size, not because a mouse event is ever sent.** `SendInput`
    # is told the size of one `INPUT` and rejects anything that is not the size *it* declares -
    # 40 bytes on x64, set by `MOUSEINPUT` as the largest member of the union. A union holding
    # only `KEYBDINPUT` measures 32, and every call fails with `ERROR_INVALID_PARAMETER` (87)
    # while returning a count rather than raising. That was shipped once: the keystroke went
    # nowhere, OBS heard nothing, and the run reported that it was filming.
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("u", _INPUTUNION)]


def obs_running() -> bool:
    """Whether OBS Studio is up. False off Windows, where there is nothing to press a key at."""
    return sys.platform == "win32" and bool(find_game_processes(OBS_PROCESS))


def press_f8() -> bool:
    """One F8, down and up, into whatever is listening system-wide.

    **The return value of `SendInput` is the only thing that reports anything here.** Whether
    OBS acted on the key is unknowable, but whether the key was injected at all is not - the
    call answers how many events it inserted, and a refusal is a zero rather than an exception.
    Ignoring it is how a wrongly-sized `INPUT` shipped as a working feature.
    """
    # `obs_running` already answers False off Windows, so no caller reaches here on another
    # platform - but `ctypes.windll` only exists on Windows, and saying so is what lets the
    # type checker read the rest of this function on a Linux runner.
    if sys.platform != "win32":
        return False
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    ok = True
    for up in (False, True):
        event = _INPUT(type=_INPUT_KEYBOARD)
        event.u.ki = _KEYBDINPUT(
            wVk=_VK_F8,
            wScan=0,
            dwFlags=_KEYEVENTF_KEYUP if up else 0,
            time=0,
            dwExtraInfo=None,
        )
        sent = user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT))
        if not sent:
            print(
                f"  SendInput refused the F8 {'release' if up else 'press'}: "
                f"error {kernel32.GetLastError()}"
            )
            ok = False
        if not up:
            time.sleep(_HOLD)
    return ok


class Recorder:
    """Start a recording at the top of a run and stop it at the bottom, or do nothing.

    **Off by default and inert when off**, because a bot run is normally not being filmed and a
    stray F8 would stop a recording someone else started.

    **Whether OBS is running is decided once, at `start`.** Deciding again at `stop` would let a
    run that began filming end without stopping - OBS crashing mid-match is exactly when the
    check would flip - and the failure mode of a stop with nothing listening is that a keystroke
    goes nowhere, which costs nothing.
    """

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self._recording = False

    def start(self) -> None:
        """Begin recording, if asked to and if there is something to ask."""
        if not self.enabled or self._recording:
            return
        if not obs_running():
            print(f"  --record was passed but {OBS_PROCESS} is not running; not filming this run")
            return
        if not press_f8():
            print("  the F8 never left this process; not filming this run")
            return
        self._recording = True
        print("  F8 sent - OBS should be recording (a hotkey reports nothing, so this is a hope)")

    def stop(self) -> None:
        """End the recording this object started. Safe to call any number of times."""
        if not self._recording:
            return
        self._recording = False
        press_f8()
        print("  F8 sent - OBS should have stopped recording")
