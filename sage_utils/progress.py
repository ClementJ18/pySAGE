"""Live progress for long-running command-line work: a status line saying what the tool is
busy with right now, so a multi-minute build is not a silent terminal.

A run installs one reporter for its duration (`progress_to`); the work itself calls the
module-level `phase` and `step` helpers. That keeps the reporter out of every signature
along the way - a loader several frames down can say which file it is on without the
functions between it and the CLI carrying a callback they have no other use for. With no
reporter installed both helpers do nothing, so a library that reports progress costs an
embedding program nothing.

Reporting goes to stderr, never stdout: a text report or a JSON document stays exactly what
a pipe or an editor plugin expects to read.
"""

import shutil
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO, Protocol

__all__ = [
    "Progress",
    "TerminalProgress",
    "muted",
    "phase",
    "progress_to",
    "step",
    "want_progress",
]


class Progress(Protocol):
    """What the `phase`/`step` helpers forward to. A front end that is not a terminal (a GUI
    status bar, a test double) can implement this and be installed the same way."""

    def phase(self, label: str, total: int | None = None) -> None:
        """Start a named unit of work, optionally of `total` items."""

    def step(self, label: str) -> None:
        """Advance one item within the current phase; `label` names it (usually a file)."""

    def close(self) -> None:
        """Finish reporting and leave the stream clean for whatever prints next."""


class TerminalProgress:
    """Report on a single line, overwritten in place, on a terminal - and as one plain line
    per phase when the stream is redirected, where carriage returns would only make a log
    unreadable and per-item lines would bury it.

    Redraws are throttled to `interval` seconds: on a game of several thousand files the
    drawing itself is otherwise a measurable share of the run. The first item of a phase
    always draws, so a slow phase names its first file immediately."""

    def __init__(self, stream: IO[str] | None = None, *, interval: float = 0.08) -> None:
        self.stream = stream if stream is not None else sys.stderr
        self.interval = interval
        self.live = bool(getattr(self.stream, "isatty", lambda: False)())
        self._label = ""
        self._total: int | None = None
        self._count = 0
        self._width = 0  # characters of the line currently on screen, to overwrite them
        self._last_draw = 0.0

    def phase(self, label: str, total: int | None = None) -> None:
        self._label = label
        self._total = total
        self._count = 0
        if self.live:
            self._draw(self._text(""), force=True)
        else:
            self._write(f"{label}...\n" if total is None else f"{label} ({total})...\n")

    def step(self, label: str) -> None:
        self._count += 1
        if self.live:
            self._draw(self._text(label), force=self._count == 1)

    def close(self) -> None:
        if self.live:
            self._clear()

    def _text(self, label: str) -> str:
        # A phase shows its name alone until its first item, so a run that is only announcing
        # what it is about to do does not read as "0 of 340 done".
        if not self._count:
            return self._label
        counter = f"{self._count}/{self._total}" if self._total else str(self._count)
        parts = [part for part in (self._label, counter, label) if part]
        return " ".join(parts)

    def _draw(self, text: str, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_draw < self.interval:
            return
        self._last_draw = now
        # One column short of the terminal width: a line filling the last column wraps on
        # some terminals, and a wrapped line cannot be overwritten by a carriage return.
        limit = max(shutil.get_terminal_size(fallback=(80, 24)).columns - 1, 20)
        if len(text) > limit:
            text = "..." + text[-(limit - 3) :]
        self._write("\r" + text.ljust(self._width))
        self._width = len(text)

    def _clear(self) -> None:
        if self._width:
            self._write("\r" + " " * self._width + "\r")
            self._width = 0

    def _write(self, text: str) -> None:
        try:
            self.stream.write(text)
            self.stream.flush()
        except (OSError, ValueError):
            # A closed or broken stderr must never take down the work being reported on.
            self.live = False


_active: Progress | None = None


@contextmanager
def progress_to(reporter: Progress | None) -> Iterator[None]:
    """Install `reporter` as the progress sink for the duration of the block, then close it
    and restore whatever was installed before. `None` reports nothing, so a caller can decide
    whether progress is wanted without branching around the work itself."""
    global _active
    previous = _active
    _active = reporter
    try:
        yield
    finally:
        if reporter is not None:
            reporter.close()
        _active = previous


@contextmanager
def muted() -> Iterator[None]:
    """Silence progress for the duration of the block. For an outer loop that reports its own
    items and calls work which would otherwise announce a phase of its own per iteration."""
    global _active
    previous = _active
    _active = None
    try:
        yield
    finally:
        _active = previous


def phase(label: str, total: int | None = None) -> None:
    """Announce a named unit of work (`building`, `running rules`), of `total` items when
    that is known ahead of time. A no-op with no reporter installed."""
    if _active is not None:
        _active.phase(label, total)


def step(label: str) -> None:
    """Report one item of the current phase, named by `label`. A no-op with no reporter
    installed, so this is cheap enough to call per file."""
    if _active is not None:
        _active.step(label)


def want_progress(choice: str, stream: IO[str] | None = None) -> bool:
    """Whether a run should report progress, for an `auto`/`always`/`never` option: `auto`
    reports when the stream is a terminal, matching how colour is decided."""
    if choice == "always":
        return True
    if choice == "never":
        return False
    target = stream if stream is not None else sys.stderr
    return bool(getattr(target, "isatty", lambda: False)())
