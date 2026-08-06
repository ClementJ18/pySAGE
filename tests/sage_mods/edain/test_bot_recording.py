"""Bracketing a run with OBS's F8, and the one failure that actually costs something.

A missed start loses a video. A missed *stop* leaves OBS recording an empty desktop until
somebody notices, which is why `stop` runs from the `finally` in `Bot.run` and why these tests
care more about the ways a run can end than about the way it begins.

Nothing here presses a real key: `press_f8` is replaced with a counter, because the real one is
system-wide input and a test suite that pressed F8 would stop whatever the machine was recording.
"""

from __future__ import annotations

import ctypes
import sys

import pytest

from sage_mods.edain.bot import recording
from sage_mods.edain.bot.recording import Recorder

# What `SendInput` requires `cbSize` to be, per architecture. This is the whole of the first
# version's bug: a union declaring only `KEYBDINPUT` measures 32 on x64 rather than 40, and
# every call is refused with `ERROR_INVALID_PARAMETER` while returning a count rather than
# raising - so the feature reported success and pressed nothing for a whole release.
_INPUT_SIZE = {8: 40, 4: 28}[ctypes.sizeof(ctypes.c_void_p)]


def test_the_input_struct_is_the_size_windows_demands() -> None:
    """`MOUSEINPUT` is in that union for its size alone - no mouse event is ever sent - so
    nothing in the code says why it must stay except this."""
    assert ctypes.sizeof(recording._INPUT) == _INPUT_SIZE


@pytest.mark.full
@pytest.mark.skipif(sys.platform != "win32", reason="there is no SendInput to refuse anything")
def test_a_real_press_is_accepted_by_windows() -> None:
    """The one thing a mocked press cannot cover: that the struct this builds is one the OS
    will actually take. Asserts only that the events were *injected* - what OBS does with them
    is not observable from here, and this deliberately does not care.

    **Behind `--full` because it presses a real F8**, which toggles whatever recording is
    running on the machine that runs it. `test_the_input_struct_is_the_size_windows_demands`
    is the cheap guard against the same regression and runs every time.
    """
    assert recording.press_f8()


@pytest.fixture
def presses(monkeypatch) -> list[int]:
    """Every F8 this test caused, so a count stands in for "did OBS hear it"."""
    sent: list[int] = []

    def press() -> bool:
        sent.append(1)
        return True

    monkeypatch.setattr(recording, "press_f8", press)
    monkeypatch.setattr(recording, "obs_running", lambda: True)
    return sent


def test_a_run_that_was_not_asked_to_film_presses_nothing(presses) -> None:
    """The default. F8 is a global hotkey, so a stray press would stop a recording somebody
    else started - which makes doing nothing the only safe behaviour when off."""
    recorder = Recorder(enabled=False)
    recorder.start()
    recorder.stop()
    assert presses == []


def test_a_filmed_run_presses_once_at_each_end(presses) -> None:
    """The whole feature: one press to start, one to stop, a match apart."""
    recorder = Recorder(enabled=True)
    recorder.start()
    assert len(presses) == 1
    recorder.stop()
    assert len(presses) == 2


def test_stopping_twice_presses_once(presses) -> None:
    """`Bot.run` stops from a `finally`, and a caller that also stops explicitly must not
    restart the recording - which is exactly what a second F8 would do."""
    recorder = Recorder(enabled=True)
    recorder.start()
    recorder.stop()
    recorder.stop()
    assert len(presses) == 2


def test_starting_twice_presses_once(presses) -> None:
    """Same key, opposite direction: a second start would stop the recording the first began."""
    recorder = Recorder(enabled=True)
    recorder.start()
    recorder.start()
    assert len(presses) == 1


def test_a_run_that_never_started_filming_does_not_stop_anything(presses) -> None:
    """The `finally` fires on every run, including the ones that were never filming. Pressing
    F8 there would *start* a recording as the bot exits and leave it running."""
    recorder = Recorder(enabled=True)
    recorder.stop()
    assert presses == []


def test_no_obs_means_no_press_and_no_pretending(monkeypatch, presses) -> None:
    """`--record` with OBS closed is a mistake worth naming rather than a keystroke worth
    sending - and having declined to start, the run must not press stop at the end either."""
    monkeypatch.setattr(recording, "obs_running", lambda: False)
    recorder = Recorder(enabled=True)
    recorder.start()
    recorder.stop()
    assert presses == []


def test_a_refused_injection_does_not_latch(monkeypatch) -> None:
    """The failure that shipped: `SendInput` refusing the key while the run announced it was
    filming. Having pressed nothing, the run must not think it has a recording to stop - or the
    `finally` sends the *first* F8 OBS ever hears, at the end, and starts recording as we exit.
    """
    refused: list[int] = []

    def press() -> bool:
        refused.append(1)
        return False

    monkeypatch.setattr(recording, "press_f8", press)
    monkeypatch.setattr(recording, "obs_running", lambda: True)
    recorder = Recorder(enabled=True)
    recorder.start()
    recorder.stop()
    assert len(refused) == 1


def test_obs_going_away_mid_match_still_stops(monkeypatch, presses) -> None:
    """Whether OBS is up is decided once, at `start`. Re-checking at `stop` would let the one
    case where the check flips - OBS crashing or being closed mid-run - end without a stop."""
    recorder = Recorder(enabled=True)
    recorder.start()
    monkeypatch.setattr(recording, "obs_running", lambda: False)
    recorder.stop()
    assert len(presses) == 2
