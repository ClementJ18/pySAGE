"""`attach` - what it selects, and how it fails.

The happy path needs Windows and a running game, so what is covered here is the part that
decides: which backend, which player index, and whether each failure arrives as its own type
with a message that says what to do. Those are the parts that were previously copy-pasted at
every call site and could differ between them.
"""

from __future__ import annotations

import pytest

import sage_live
from sage_live.api import connect as connect_module
from sage_live.api.connect import AttachError, NoGameRunning, NotPermitted, attach, open_backend
from sage_live.backends.memory import EngineLayout, MemoryBackend
from sage_live.utils.naming import LiveNames
from tests.sage_live.test_memory import FakeImage


class FakeSource:
    """A `MemorySource` that answers nothing, so a backend built on it reads an empty game."""

    def __init__(self, pid: int, writable: bool = False) -> None:
        self.pid = pid
        self.writable = writable
        self.closed = False

    def read(self, address: int, size: int) -> bytes | None:
        return None

    def write(self, address: int, data: bytes) -> bool:
        return self.writable

    def close(self) -> None:
        self.closed = True


def test_no_game_running_is_its_own_error(monkeypatch):
    monkeypatch.setattr(connect_module, "find_game_processes", lambda: [])
    with pytest.raises(NoGameRunning) as caught:
        open_backend()
    assert "launch the game" in str(caught.value)


def test_an_unelevated_shell_is_reported_as_such(monkeypatch):
    def refuse(pid: int, writable: bool = False) -> FakeSource:
        raise PermissionError(f"OpenProcess({pid}) failed with error 5")

    monkeypatch.setattr(connect_module, "find_game_processes", lambda: [4242])
    monkeypatch.setattr(connect_module, "ProcessMemory", refuse)
    with pytest.raises(NotPermitted) as caught:
        open_backend()
    assert "elevated" in str(caught.value)


def test_every_failure_is_an_attach_error(monkeypatch):
    """One type to catch, so a script can handle all of them with a single `except`."""
    monkeypatch.setattr(connect_module, "find_game_processes", lambda: [])
    with pytest.raises(AttachError):
        attach()


def test_a_process_that_is_not_the_game_refuses_before_reading_anything(monkeypatch):
    """No readable PE image at the base means this is not `game.dat`, or the handle cannot
    read it. Either way there is nothing to identify, so nothing is decoded."""
    monkeypatch.setattr(connect_module, "find_game_processes", lambda: [4242])
    monkeypatch.setattr(connect_module, "ProcessMemory", FakeSource)
    with pytest.raises(AttachError) as caught:
        open_backend()
    assert "no PE image" in str(caught.value)


def test_a_game_with_no_logic_refuses_rather_than_returning_an_empty_session(monkeypatch):
    """The right build, but nothing running: `TheGameLogic` is null."""
    monkeypatch.setattr(connect_module, "find_game_processes", lambda: [4242])
    monkeypatch.setattr(connect_module, "ProcessMemory", lambda pid, writable=False: FakeImage())
    with pytest.raises(AttachError) as caught:
        open_backend()
    assert "TheGameLogic" in str(caught.value)


def test_another_build_is_refused_rather_than_read_with_the_wrong_offsets(monkeypatch):
    """The failure this gate exists for. A different `game.dat` does not read as an error - it
    reads as data - so the build is identified before anything is decoded."""
    monkeypatch.setattr(connect_module, "find_game_processes", lambda: [4242])
    monkeypatch.setattr(
        connect_module, "ProcessMemory", lambda pid, writable=False: FakeImage(timestamp=0xDEADBEEF)
    )
    with pytest.raises(AttachError) as caught:
        open_backend()
    assert "not the build the layout describes" in str(caught.value)
    assert "0xdeadbeef" in str(caught.value)


def test_the_first_process_is_used_when_no_pid_is_given(monkeypatch):
    opened: list[tuple[int, bool]] = []

    def record(pid: int, writable: bool = False) -> FakeSource:
        opened.append((pid, writable))
        return FakeSource(pid, writable)

    monkeypatch.setattr(connect_module, "find_game_processes", lambda: [111, 222])
    monkeypatch.setattr(connect_module, "ProcessMemory", record)
    with pytest.raises(AttachError):
        open_backend()
    assert opened == [(111, False)]


def test_read_only_is_the_default_and_writable_is_opt_in(monkeypatch):
    opened: list[tuple[int, bool]] = []

    def record(pid: int, writable: bool = False) -> FakeSource:
        opened.append((pid, writable))
        return FakeSource(pid, writable)

    monkeypatch.setattr(connect_module, "ProcessMemory", record)
    for writable in (False, True):
        with pytest.raises(AttachError):
            open_backend(4242, writable=writable)
    assert [w for _, w in opened] == [False, True]


def test_a_refused_connection_closes_the_process_handle(monkeypatch):
    sources: list[FakeSource] = []

    def record(pid: int, writable: bool = False) -> FakeSource:
        source = FakeSource(pid, writable)
        sources.append(source)
        return source

    monkeypatch.setattr(connect_module, "ProcessMemory", record)
    with pytest.raises(AttachError):
        open_backend(4242)
    assert sources[0].closed, "a failed attach must not leak the handle"


def test_attach_reads_the_local_player_rather_than_defaulting_to_zero(monkeypatch):
    """The seat decides who orders are attributed to, and it is readable, so it is read."""
    backend = MemoryBackend(FakeSource(4242), EngineLayout())
    monkeypatch.setattr(connect_module, "open_backend", lambda *a, **k: backend)
    monkeypatch.setattr(backend, "connect", lambda: backend._handshake)
    monkeypatch.setattr(backend, "local_player_index", lambda: 3)

    session = attach()
    assert session.player_index == 3
    assert isinstance(session.names, LiveNames), "upgrade names should work with no ini load"
    assert session.connected


def test_an_explicit_player_index_overrides_the_read_one(monkeypatch):
    backend = MemoryBackend(FakeSource(4242), EngineLayout())
    monkeypatch.setattr(connect_module, "open_backend", lambda *a, **k: backend)
    monkeypatch.setattr(backend, "connect", lambda: backend._handshake)
    monkeypatch.setattr(backend, "local_player_index", lambda: 3)

    assert attach(player_index=1).player_index == 1


def test_attach_is_exported_from_the_package_root():
    assert sage_live.attach is attach
    assert {"attach", "open_backend", "AttachError"} <= set(sage_live.__all__)
