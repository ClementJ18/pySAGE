"""The progress reporter: what a terminal and a redirected stream each get, how the helpers
behave with no reporter installed, and that a run leaves the stream clean."""

import io

from sage_utils import progress
from sage_utils.progress import TerminalProgress, want_progress


class Tty(io.StringIO):
    """A stream that claims to be a terminal, so the live single-line path is exercised."""

    def isatty(self) -> bool:
        return True


def reporter(stream: io.StringIO) -> TerminalProgress:
    """A reporter with throttling off, so every step shows up in the captured output."""
    return TerminalProgress(stream, interval=0.0)


def test_helpers_are_silent_with_no_reporter():
    progress.phase("building", 3)
    progress.step("a.ini")  # must not raise, and nothing is installed to write anywhere


def test_terminal_overwrites_one_line():
    out = Tty()
    with progress.progress_to(reporter(out)):
        progress.phase("building", 2)
        progress.step("a.ini")
        progress.step("b.ini")
    written = out.getvalue()
    assert written.count("\n") == 0
    assert "building 1/2 a.ini" in written
    assert "building 2/2 b.ini" in written


def test_phase_shows_its_name_before_the_first_item():
    out = Tty()
    with progress.progress_to(reporter(out)):
        progress.phase("merging base game")
    assert out.getvalue().startswith("\rmerging base game")


def test_terminal_clears_its_line_when_done():
    out = Tty()
    with progress.progress_to(reporter(out)):
        progress.phase("building", 1)
        progress.step("a.ini")
    assert out.getvalue().endswith("\r")
    assert out.getvalue().rstrip("\r").endswith(" ")


def test_long_label_is_truncated_to_the_terminal_width():
    out = Tty()
    with progress.progress_to(reporter(out)):
        progress.phase("building", 1)
        progress.step("data/ini/object/" + "x" * 500 + ".ini")
    line = out.getvalue().split("\r")[-3]  # the last drawn line, before the clearing blanks
    assert len(line) < 500
    assert line.startswith("...")
    assert line.endswith(".ini")  # the tail is kept: the file name is the useful half


def test_redirected_stream_gets_one_plain_line_per_phase():
    out = io.StringIO()
    with progress.progress_to(reporter(out)):
        progress.phase("building", 2)
        progress.step("a.ini")
        progress.step("b.ini")
        progress.phase("running rules")
    assert out.getvalue() == "building (2)...\nrunning rules...\n"


def test_muted_hides_inner_reporting():
    out = Tty()
    with progress.progress_to(reporter(out)):
        progress.phase("linting map.ini", 1)
        progress.step("skirmish/map.ini")
        with progress.muted():
            progress.phase("running rules", 4)
            progress.step("unknown-attribute")
    assert "running rules" not in out.getvalue()
    assert "skirmish/map.ini" in out.getvalue()


def test_reporter_is_restored_after_the_block():
    out = Tty()
    with progress.progress_to(reporter(out)):
        with progress.progress_to(reporter(io.StringIO())):
            progress.phase("inner")
        progress.phase("outer")
    assert "outer" in out.getvalue()


def test_broken_stream_does_not_propagate():
    out = Tty()
    out.close()
    with progress.progress_to(reporter(out)):
        progress.phase("building", 1)
        progress.step("a.ini")


def test_want_progress_follows_the_stream_for_auto():
    assert want_progress("auto", Tty()) is True
    assert want_progress("auto", io.StringIO()) is False
    assert want_progress("always", io.StringIO()) is True
    assert want_progress("never", Tty()) is False
