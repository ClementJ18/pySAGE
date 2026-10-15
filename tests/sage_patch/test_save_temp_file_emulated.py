"""`save-temp-file`, executed: what the cave opens, renames and deletes, in each order a save takes.

The cave's four routines run over the patched image - the real `game.dat` when this checkout has
one, the synthetic stand-in otherwise; the cave bytes are the same either way. The wide open,
`File::close` and the three `kernel32` entries are answered in Python and recorded, so each test
reads back exactly which files the save touched and in what order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")
pytest.importorskip("pefile", reason="the emulator harness maps the image with pefile")

from unicorn.x86_const import UC_X86_REG_ESP  # noqa: E402

from sage_patch.addresses import (  # noqa: E402
    DELETE_FILE_W_IAT,
    GAME_STATE_SAVE_CATCH_CLOSE_RESUME,
    GAME_STATE_SAVE_DONE_CLOSE_RESUME,
    GAME_STATE_SAVE_OPEN_CATCH_RESUME,
    GET_MODULE_HANDLE_A_IAT,
    GET_PROC_ADDRESS_IAT,
    LOCAL_FILE_SYSTEM_OPEN_WIDE,
)
from sage_patch.patches.save_temp_file import (  # noqa: E402
    MOVE_FLAGS,
    OFF_ACTIVE,
    OFF_FINAL,
    SECTION_NAME,
    TEMP_CHARS,
    SaveTempFilePatch,
    entry_points,
)
from sage_patch.utils import find_section  # noqa: E402

from .save_machine import STACK, STACK_SIZE, Machine  # noqa: E402
from .synthetic import save_temp_file_image  # noqa: E402

REAL_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

PATH = "C:\\Users\\Player\\Save\\Angmar Act 2.BfME2WotR"
ACCESS = 0x4A
#: Where a jumped-into routine's stack starts: below the area `Machine.call` uses.
JUMP_ESP = STACK + STACK_SIZE - 0x4000


def _image() -> bytes:
    source = REAL_GAME_DAT.read_bytes() if REAL_GAME_DAT.exists() else bytes(save_temp_file_image())
    data = bytearray(source)
    SaveTempFilePatch().apply(data)
    return bytes(data)


@pytest.fixture(scope="module")
def image() -> bytes:
    return _image()


@dataclass
class Save:
    """One `saveGame` frame and the world it talks to, with every call recorded."""

    m: Machine
    section: int
    entries: dict[str, int]
    open_succeeds: bool = True
    resolve_succeeds: bool = True
    calls: list[tuple] = field(default_factory=list)

    def __post_init__(self) -> None:
        m = self.m

        def open_wide(mm: Machine) -> None:
            path, access, size = mm.arg(0), mm.arg(1), mm.arg(2)
            self.calls.append(("open", path, mm.read_wide(path), access, size))
            mm.ret(12, 0xF11E if self.open_succeeds else 0)

        def close(mm: Machine) -> None:
            self.calls.append(("close", mm.reg("ecx")))
            mm.ret(0)

        def get_module_handle(mm: Machine) -> None:
            name = bytes(mm.uc.mem_read(mm.arg(0), 16)).split(b"\x00")[0].decode()
            self.calls.append(("GetModuleHandleA", name))
            mm.ret(4, 0x7C800000)

        def get_proc_address(mm: Machine) -> None:
            name = bytes(mm.uc.mem_read(mm.arg(1), 16)).split(b"\x00")[0].decode()
            self.calls.append(("GetProcAddress", mm.arg(0), name))
            mm.ret(8, self.move_file if self.resolve_succeeds else 0)

        def move_file(mm: Machine) -> None:
            self.calls.append(
                ("MoveFileExW", mm.read_wide(mm.arg(0)), mm.read_wide(mm.arg(1)), mm.arg(2))
            )
            mm.ret(12, 1)

        def delete_file(mm: Machine) -> None:
            self.calls.append(("DeleteFileW", mm.read_wide(mm.arg(0))))
            mm.ret(4, 1)

        m.stub(LOCAL_FILE_SYSTEM_OPEN_WIDE, open_wide)
        self.move_file = m.stub(None, move_file)
        for slot, handler in (
            (GET_MODULE_HANDLE_A_IAT, get_module_handle),
            (GET_PROC_ADDRESS_IAT, get_proc_address),
            (DELETE_FILE_W_IAT, delete_file),
        ):
            m.ensure(slot)
            m.write32(slot, m.stub(None, handler))

        vtable = m.alloc(0x20, b"\x00" * 0x20)
        m.write32(vtable + 8, m.stub(None, close))
        self.file = m.alloc(8)
        m.write32(self.file, vtable)
        self.ebp = m.frame()
        m.write32(self.ebp - 0x14, self.file)
        m.stop_at(
            GAME_STATE_SAVE_DONE_CLOSE_RESUME,
            GAME_STATE_SAVE_CATCH_CLOSE_RESUME,
            GAME_STATE_SAVE_OPEN_CATCH_RESUME,
        )

    @property
    def active(self) -> int:
        return self.m.uc.mem_read(self.section + OFF_ACTIVE, 1)[0]

    def open(self, path: str | None = PATH) -> tuple[int, int]:
        """`saveGame`'s open call; returns the path pointer passed and the handle."""
        at = self.m.wide(path if path is not None else "")
        handle = self.m.call(self.entries["open"], at, ACCESS, 0, ebp=self.ebp)
        return at, handle

    def jump(self, routine: str, **registers: int) -> int | None:
        """Enter a close hook the way the engine does - by the `jmp` in its window."""
        self.m.run(self.entries[routine], JUMP_ESP, ebp=self.ebp, **registers)
        return self.m.stopped_at


@pytest.fixture
def save(image) -> Save:
    m = Machine(image)
    section_va, _off, _size = find_section(image, SECTION_NAME)
    return Save(m, section_va, entry_points(section_va))


def _named(calls: list[tuple], *names: str) -> list[tuple]:
    return [c for c in calls if c[0] in names]


class TestOpen:
    def test_it_opens_the_temporary_file_with_the_stock_arguments(self, save: Save) -> None:
        at, handle = save.open()
        (call,) = _named(save.calls, "open")
        assert call[2] == PATH + ".tmp"
        assert call[1] != at, "the engine's own string is not written to"
        assert call[3:] == (ACCESS, 0)
        assert handle == 0xF11E
        assert save.m.read_wide(at) == PATH

    def test_it_marks_the_save_and_remembers_the_real_path(self, save: Save) -> None:
        at, _handle = save.open()
        assert save.active == 1
        assert save.m.read32(save.section + OFF_FINAL) == at

    def test_a_failed_open_is_not_marked(self, save: Save) -> None:
        save.open_succeeds = False
        _at, handle = save.open()
        assert handle == 0
        assert save.active == 0

    def test_an_empty_path_opens_as_stock(self, save: Save) -> None:
        at, _handle = save.open("")
        (call,) = _named(save.calls, "open")
        assert call[1] == at
        assert save.active == 0

    def test_the_longest_path_that_fits_gets_a_temporary_file(self, save: Save) -> None:
        longest = "x" * (TEMP_CHARS - len(".tmp") - 2)
        save.open(longest)
        assert _named(save.calls, "open")[0][2] == longest + ".tmp"
        assert save.active == 1

    def test_a_path_one_longer_opens_as_stock(self, save: Save) -> None:
        too_long = "x" * (TEMP_CHARS - len(".tmp") - 1)
        at, _handle = save.open(too_long)
        (call,) = _named(save.calls, "open")
        assert call[1] == at
        assert call[2] == too_long
        assert save.active == 0

    def test_it_returns_like_the_open_it_stands_in_for(self, save: Save) -> None:
        """`ret 0xC`, and the callee-saved registers the caller relies on (`edi` is compared
        against the result straight after) come back as they went in."""
        regs = {"ebx": 0x1111, "esi": 0x2222, "edi": 0x3333}
        at = save.m.wide(PATH)
        save.m.call(save.entries["open"], at, ACCESS, 0, ebp=save.ebp, **regs)
        assert {name: save.m.reg(name) for name in regs} == regs
        assert save.m.reg("ebp") == save.ebp
        assert save.m.uc.reg_read(UC_X86_REG_ESP) == STACK + STACK_SIZE - 0x1000


class TestASaveThatCompletes:
    def test_it_closes_then_moves_the_file_into_place(self, save: Save) -> None:
        save.open()
        stopped = save.jump("done")
        assert stopped == GAME_STATE_SAVE_DONE_CLOSE_RESUME
        assert _named(save.calls, "close", "MoveFileExW", "DeleteFileW") == [
            ("close", save.file),
            ("MoveFileExW", PATH + ".tmp", PATH, MOVE_FLAGS),
        ]
        assert save.active == 0

    def test_moving_replaces_the_existing_save(self) -> None:
        assert MOVE_FLAGS & 0x1, "MOVEFILE_REPLACE_EXISTING"

    def test_it_resolves_move_file_once(self, save: Save) -> None:
        for _ in range(3):
            save.open()
            save.jump("done")
        assert len(_named(save.calls, "GetModuleHandleA")) == 1
        assert _named(save.calls, "GetProcAddress")[0][2] == "MoveFileExW"
        assert len(_named(save.calls, "MoveFileExW")) == 3

    def test_a_save_that_never_opened_a_temporary_file_is_not_moved(self, save: Save) -> None:
        save.open_succeeds = False
        save.open()
        assert save.jump("done") == GAME_STATE_SAVE_DONE_CLOSE_RESUME
        assert not _named(save.calls, "MoveFileExW", "DeleteFileW")

    def test_without_move_file_the_save_stays_in_the_temporary_file(self, save: Save) -> None:
        save.resolve_succeeds = False
        save.open()
        assert save.jump("done") == GAME_STATE_SAVE_DONE_CLOSE_RESUME
        assert not _named(save.calls, "MoveFileExW", "DeleteFileW")
        save.resolve_succeeds = True
        save.open()
        save.jump("done")
        assert len(_named(save.calls, "GetProcAddress")) == 2, "a failed resolve is retried"

    def test_it_preserves_the_registers_saveGame_resumes_with(self, save: Save) -> None:
        save.open()
        regs = {"ebx": 0x1111, "esi": 0x2222, "edi": 0x3333}
        save.jump("done", **regs)
        assert {name: save.m.reg(name) for name in regs} == regs


class TestASaveThatFails:
    @pytest.mark.parametrize(
        ("routine", "resume"),
        [
            ("abort", GAME_STATE_SAVE_CATCH_CLOSE_RESUME),
            ("open_abort", GAME_STATE_SAVE_OPEN_CATCH_RESUME),
        ],
    )
    def test_it_closes_then_deletes_the_temporary_file(self, save: Save, routine, resume) -> None:
        save.open()
        assert save.jump(routine) == resume
        assert _named(save.calls, "close", "MoveFileExW", "DeleteFileW") == [
            ("close", save.file),
            ("DeleteFileW", PATH + ".tmp"),
        ]
        assert save.active == 0

    def test_the_real_save_is_never_touched(self, save: Save) -> None:
        save.open()
        save.jump("abort")
        touched = [c for c in save.calls if c[0] in ("MoveFileExW", "DeleteFileW", "open")]
        assert all(PATH not in c[1:] for c in touched if c[0] != "open")

    def test_a_failure_before_any_temporary_file_deletes_nothing(self, save: Save) -> None:
        save.open_succeeds = False
        save.open()
        save.jump("abort")
        assert not _named(save.calls, "DeleteFileW")

    def test_the_next_save_after_a_failure_completes(self, save: Save) -> None:
        save.open()
        save.jump("abort")
        save.open()
        save.jump("done")
        assert _named(save.calls, "MoveFileExW", "DeleteFileW") == [
            ("DeleteFileW", PATH + ".tmp"),
            ("MoveFileExW", PATH + ".tmp", PATH, MOVE_FLAGS),
        ]
