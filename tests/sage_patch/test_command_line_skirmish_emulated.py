"""Runs the command-line-skirmish setup cave under an emulator, against a stand-in `GameInfo`.

The static tests show the cave *says* the right things; this shows it *does* them, in order, with
the stack where the engine expects it. The patch is applied to the synthetic image and the hook
site itself is where execution starts, so the jump into the cave is part of what runs.

Every engine routine the cave calls is a stub that records what it was handed and cleans the stack
the way the real one does - `ret 4` for the `__thiscall` helpers, a plain `ret` for `_stricmp` and
the `__cdecl` parser. The parser stub stands in for the engine's contract as `docs/game-info.md`
§7 reads it: on success it rewrites the slots and clobbers the map identity with the string's
placeholders; on failure it touches nothing.
"""

from __future__ import annotations

import faulthandler
import struct

import pytest

from sage_patch.addresses import (
    ASCII_STRING_COPY_CTOR,
    ASCII_STRING_CTOR,
    ASCII_STRING_DTOR,
    COMMAND_LINE_SKIRMISH_SETUP,
    COMMAND_LINE_SKIRMISH_SETUP_RESUME,
    GAME_INFO_GSID,
    GAME_INFO_MAP,
    GAME_INFO_MAP_CONTENTS_MASK,
    GAME_INFO_MAP_CRC,
    GAME_INFO_MAP_SIZE,
    GAME_INFO_PARSE,
    GAME_INFO_SET_MAP,
    GAME_INFO_SET_MAP_CRC,
    GAME_INFO_SET_MAP_SIZE,
    GAME_INFO_SI,
    GAME_INFO_SLOT_ARRAY,
    GAME_INFO_SLOT_DATA,
    GAME_INFO_STARTING_RESOURCES,
    GAME_MAIN_ARGC,
    GAME_MAIN_ARGV,
    GAME_MESSAGE_APPEND_INTEGER,
    GAME_SLOT_MAP_PLAYER,
    GAME_SLOT_SIZE,
    GAME_SLOT_START_POS,
    GAME_SLOT_STATE,
    GAME_SLOT_STATE_BRUTAL_AI,
    GAME_SLOT_STATE_CLOSED,
    GAME_SLOT_STATE_EASY_AI,
    GAME_SLOT_STATE_HARD_AI,
    GAME_SLOT_STATE_LOCAL_HUMAN,
    GAME_SLOT_STATE_OPEN,
    STRICMP,
    THE_GAME_INFO,
    THE_SKIRMISH_GAME_INFO,
)
from sage_patch.patches.experimental.command_line_skirmish import (
    SECTION_NAME,
    STATUS_APPLIED,
    STATUS_NOT_GIVEN,
    STATUS_OFFSET,
    STATUS_REJECTED,
    CommandLineSkirmishPatch,
)
from sage_patch.utils import find_section, va_to_offset

from .synthetic import command_line_skirmish_image

unicorn = pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

_PAGE = 0x1000
#: Where the synthetic world lives: far above the image, so a stray read faults instead of
#: quietly finding a structure.
_HEAP = 0x20000000
_STRINGS = 0x22000000
_STACK = 0x30000000
_GAME_INFO = _HEAP + 0x1000
_MAP_PATH = 0x21000000  # the auto-start's map `AsciiString` block; only ever passed around
_ESP = _STACK + 0x2000
_FRAME = _STACK + 0x4000  # `GameEngine::init`'s `ebp`

_MESSAGE = 0x4D455353  # the `GameMessage` the displaced tail hands over in `edi`
_SAVED = {UC_X86_REG_EBX: 0xBBBBBBBB, UC_X86_REG_ESI: 0x51515151, UC_X86_REG_EDI: _MESSAGE}

#: The map identity a `-file` start left behind, and what the parser writes over it.
_IDENTITY = {
    GAME_INFO_MAP: _MAP_PATH,
    GAME_INFO_MAP_CRC: 0x0C1ABD7B,
    GAME_INFO_MAP_SIZE: 487138,
    GAME_INFO_MAP_CONTENTS_MASK: 0x387,
    GAME_INFO_SI: 0xFFFFFFFF,
    GAME_INFO_GSID: 0x1234ABCD,
}
_PLACEHOLDER = 0

_RET = b"\xc3"
_RET_4 = b"\xc2\x04\x00"
_STUBS = {
    GAME_MESSAGE_APPEND_INTEGER: _RET_4,
    STRICMP: _RET,
    ASCII_STRING_CTOR: _RET_4,
    ASCII_STRING_COPY_CTOR: _RET_4,
    ASCII_STRING_DTOR: _RET,
    GAME_INFO_PARSE: _RET,
    GAME_INFO_SET_MAP: _RET_4,
    GAME_INFO_SET_MAP_CRC: _RET_4,
    GAME_INFO_SET_MAP_SIZE: _RET_4,
}

_VALUE = b"M=000maps/command line;MC=0;MS=0;SD=7;GSID=0;GT=0;SI=-1;GR=0 0 1 100 1000;S=X:;"


class _Launch:
    """One emulated `-file` start, from the hook site to the resume point.

    `commit` is what a successful parse writes: `(slot index, state, start position)` per slot.
    `parses` None means the parser must never be called.
    """

    def __init__(
        self,
        argv: list[bytes],
        *,
        parses: bool | None = None,
        commit: tuple[tuple[int, int, int], ...] = (),
    ):
        self.parses = parses
        self.commit = commit
        self.calls: list[tuple] = []

        data = command_line_skirmish_image()
        CommandLineSkirmishPatch().apply(data)
        base, file_off, size = find_section(data, SECTION_NAME)
        self.base = base

        pages: set[int] = set()

        def cover(va: int, length: int = 1) -> None:
            pages.update(range(va & ~0xFFF, va + length, _PAGE))

        cover(base, size)
        cover(COMMAND_LINE_SKIRMISH_SETUP)
        cover(THE_GAME_INFO, 8)
        for va in _STUBS:
            cover(va)
        cover(_HEAP, 0x3000)
        cover(_STRINGS, 0x2000)
        cover(_STACK, 0x5000)

        self.uc = uc = Uc(UC_ARCH_X86, UC_MODE_32)
        # `mem_map` raises and catches an SEH access violation inside Unicorn 2.1.4 on Windows -
        # every map still succeeds, but Python's fault handler prints a stack for each one.
        was_enabled = faulthandler.is_enabled()
        faulthandler.disable()
        try:
            for page in sorted(pages):
                uc.mem_map(page, _PAGE)
        finally:
            if was_enabled:
                faulthandler.enable()

        uc.mem_write(base, bytes(data[file_off : file_off + size]))
        site = COMMAND_LINE_SKIRMISH_SETUP & ~0xFFF
        site_off = va_to_offset(data, site)
        uc.mem_write(site, bytes(data[site_off : site_off + _PAGE]))
        for va, stub in _STUBS.items():
            uc.mem_write(va, stub)
            uc.hook_add(UC_HOOK_CODE, self._stub, begin=va, end=va)

        for index in range(8):
            slot = _GAME_INFO + GAME_INFO_SLOT_DATA + index * GAME_SLOT_SIZE
            self._put(_GAME_INFO + GAME_INFO_SLOT_ARRAY + index * 4, slot)
            state = GAME_SLOT_STATE_LOCAL_HUMAN if index == 0 else GAME_SLOT_STATE_CLOSED
            self._put(slot + GAME_SLOT_STATE, state)
            self._put(slot + GAME_SLOT_START_POS, 0xFFFFFFFF)
        for offset, value in _IDENTITY.items():
            self._put(_GAME_INFO + offset, value)
        self._put(THE_SKIRMISH_GAME_INFO, _GAME_INFO)
        self._put(THE_GAME_INFO, 0)

        cursor = _STRINGS
        pointers = []
        for argument in argv:
            uc.mem_write(cursor, argument + b"\x00")
            pointers.append(cursor)
            cursor += len(argument) + 1
        self._next_string = (cursor + 0x100) & ~0xFF
        table = _HEAP
        uc.mem_write(table, struct.pack(f"<{len(pointers)}I", *pointers))
        # `init`'s own argument slots hold what they hold at the hook: stack addresses.
        self._put(_FRAME + 0x08, _FRAME - 0x1000)
        self._put(_FRAME + 0x0C, _FRAME - 0x2000)
        self._put(_FRAME + GAME_MAIN_ARGC, len(argv))
        self._put(_FRAME + GAME_MAIN_ARGV, table)

        uc.reg_write(UC_X86_REG_ESP, _ESP)
        uc.reg_write(UC_X86_REG_EBP, _FRAME)
        uc.reg_write(UC_X86_REG_ECX, 0xCCCCCCCC)
        for register, value in _SAVED.items():
            uc.reg_write(register, value)
        uc.emu_start(COMMAND_LINE_SKIRMISH_SETUP, COMMAND_LINE_SKIRMISH_SETUP_RESUME)

    def _put(self, va: int, value: int) -> None:
        self.uc.mem_write(va, struct.pack("<I", value & 0xFFFFFFFF))

    def dword(self, va: int) -> int:
        return struct.unpack("<I", self.uc.mem_read(va, 4))[0]

    def cstring(self, va: int) -> bytes:
        out = bytearray()
        while (byte := self.uc.mem_read(va + len(out), 1)[0]) != 0:
            out.append(byte)
        return bytes(out)

    def _stub(self, uc, address, _size, _data):
        esp = uc.reg_read(UC_X86_REG_ESP)
        this = uc.reg_read(UC_X86_REG_ECX)
        first = self.dword(esp + 4)
        if address == STRICMP:
            left, right = self.cstring(first), self.cstring(self.dword(esp + 8))
            self.calls.append(("stricmp", left, right))
            uc.reg_write(UC_X86_REG_EAX, 0 if left.lower() == right.lower() else 1)
        elif address == ASCII_STRING_CTOR:
            text = self.cstring(first)
            block = self._next_string
            uc.mem_write(block, struct.pack("<IHH", 1, len(text), len(text) + 1) + text + b"\x00")
            self._next_string = (block + len(text) + 0x20) & ~0x3
            self._put(this, block)
            self.calls.append(("ctor", this, text))
        elif address == ASCII_STRING_COPY_CTOR:
            self._put(this, self.dword(first))
            self.calls.append(("copy", this, first))
        elif address == ASCII_STRING_DTOR:
            self.calls.append(("dtor", this))
        elif address == GAME_INFO_PARSE:
            string = self.dword(esp + 8)
            text = self.cstring(string + 8) if string else b""
            self.calls.append(("parse", first, esp + 8, text, self.dword(esp + 12)))
            assert self.parses is not None, "the parser was called with no switch given"
            if self.parses:
                for index, state, start in self.commit:
                    slot = self.dword(first + GAME_INFO_SLOT_ARRAY + index * 4)
                    self._put(slot + GAME_SLOT_STATE, state)
                    self._put(slot + GAME_SLOT_START_POS, start)
                    self._put(slot + GAME_SLOT_MAP_PLAYER, 0)
                for offset in _IDENTITY:
                    self._put(first + offset, _PLACEHOLDER)
            uc.reg_write(UC_X86_REG_EAX, 1 if self.parses else 0)
        elif address == GAME_MESSAGE_APPEND_INTEGER:
            self.calls.append(("append", this, first))
        else:
            name = {
                GAME_INFO_SET_MAP: "setMap",
                GAME_INFO_SET_MAP_CRC: "setMapCRC",
                GAME_INFO_SET_MAP_SIZE: "setMapSize",
            }[address]
            self.calls.append((name, this, first))

    def named(self, name: str) -> list[tuple]:
        return [call for call in self.calls if call[0] == name]

    def order(self, name: str) -> int:
        return next(i for i, call in enumerate(self.calls) if call[0] == name)

    @property
    def status(self) -> int:
        return self.dword(self.base + STATUS_OFFSET)

    def slot(self, index: int) -> int:
        return self.dword(_GAME_INFO + GAME_INFO_SLOT_ARRAY + index * 4)

    def map_player(self, index: int) -> bytes | None:
        block = self.dword(self.slot(index) + GAME_SLOT_MAP_PLAYER)
        return None if block == 0 else self.cstring(block + 8)

    def state(self, index: int) -> int:
        return self.dword(self.slot(index) + GAME_SLOT_STATE)


def _assert_it_returned_cleanly(run: _Launch) -> None:
    """Every borrowed register back, the stack where the hook found it, the displaced tail run,
    and the live `GameInfo` published."""
    uc = run.uc
    assert uc.reg_read(UC_X86_REG_ESP) == _ESP
    assert uc.reg_read(UC_X86_REG_EBP) == _FRAME
    for register, value in _SAVED.items():
        assert uc.reg_read(register) == value
    assert run.named("append") == [("append", _MESSAGE, 2)]
    assert run.dword(THE_GAME_INFO) == _GAME_INFO


_FILE = [b"game.dat", b"-file", b"maps\\map mp harlindon.map"]


class TestWithoutTheSwitch:
    @pytest.fixture(scope="class")
    def run(self):
        return _Launch([*_FILE, b"-win"])

    def test_it_returns_cleanly(self, run):
        _assert_it_returned_cleanly(run)

    def test_the_status_says_not_given(self, run):
        assert run.status == STATUS_NOT_GIVEN

    def test_nothing_is_parsed_saved_or_released(self, run):
        assert run.named("parse") == []
        assert run.named("copy") == []
        assert run.named("dtor") == []

    def test_every_argument_after_the_program_is_compared_but_the_last(self):
        """The switch needs a value after it, so the final argument is never a candidate."""
        run = _Launch([*_FILE, b"-win"])
        compared = [call[1] for call in run.named("stricmp")]
        assert compared == [b"-file", b"maps\\map mp harlindon.map"]

    def test_the_default_match_is_seated(self, run):
        assert run.state(0) == GAME_SLOT_STATE_LOCAL_HUMAN
        assert run.state(1) == GAME_SLOT_STATE_EASY_AI
        assert run.map_player(0) == b"Player_1"
        assert run.map_player(1) == b"Player_2"
        assert run.dword(_GAME_INFO + GAME_INFO_STARTING_RESOURCES) == 5000

    def test_a_switch_with_no_value_is_not_given(self):
        run = _Launch([*_FILE, b"-gameInfo"])
        assert run.status == STATUS_NOT_GIVEN
        assert run.named("parse") == []
        _assert_it_returned_cleanly(run)


#: A human at start position 3, a hard AI at 0, and three slots the binding must leave alone: a
#: closed one and an open one that name start positions, and a medium AI with none.
_COMMIT = (
    (0, GAME_SLOT_STATE_LOCAL_HUMAN, 3),
    (1, GAME_SLOT_STATE_HARD_AI, 0),
    (2, GAME_SLOT_STATE_CLOSED, 5),
    (3, GAME_SLOT_STATE_OPEN, 6),
    (4, GAME_SLOT_STATE_BRUTAL_AI, 0xFFFFFFFF),
)


class TestAnAcceptedString:
    @pytest.fixture(scope="class")
    def run(self):
        return _Launch([*_FILE, b"-gameInfo", _VALUE, b"-win"], parses=True, commit=_COMMIT)

    def test_it_returns_cleanly(self, run):
        _assert_it_returned_cleanly(run)

    def test_the_status_says_applied(self, run):
        assert run.status == STATUS_APPLIED

    def test_the_parser_gets_the_value_the_game_info_and_keep_names_false(self, run):
        [(_, game_info, slot, text, keep_names)] = run.named("parse")
        assert game_info == _GAME_INFO
        assert text == _VALUE
        assert keep_names & 0xFF == 0
        # the string it was handed is the one constructed in that very argument slot
        [(_, constructed_in, constructed_from)] = run.named("ctor")
        assert constructed_in == slot
        assert constructed_from == _VALUE

    def test_the_switch_is_matched_without_regard_to_case(self):
        run = _Launch([*_FILE, b"-GAMEINFO", _VALUE], parses=True, commit=_COMMIT)
        assert run.status == STATUS_APPLIED

    def test_the_map_identity_is_put_back(self, run):
        assert run.named("setMap") == [("setMap", _GAME_INFO, _MAP_PATH)]
        assert run.named("setMapCRC") == [("setMapCRC", _GAME_INFO, _IDENTITY[GAME_INFO_MAP_CRC])]
        assert run.named("setMapSize") == [
            ("setMapSize", _GAME_INFO, _IDENTITY[GAME_INFO_MAP_SIZE])
        ]
        for offset in (GAME_INFO_MAP_CONTENTS_MASK, GAME_INFO_SI, GAME_INFO_GSID):
            assert run.dword(_GAME_INFO + offset) == _IDENTITY[offset]

    def test_the_copy_is_taken_before_the_parse_and_released_after_it_is_used(self, run):
        first_copy = run.named("copy")[0]
        assert first_copy[2] == _GAME_INFO + GAME_INFO_MAP
        saved = first_copy[1]
        assert run.order("copy") < run.order("parse") < run.order("setMap") < run.order("dtor")
        assert run.named("dtor") == [("dtor", saved)]

    def test_every_seated_slot_is_bound_to_its_start_position(self, run):
        assert run.map_player(0) == b"Player_4"
        assert run.map_player(1) == b"Player_1"

    def test_unseated_slots_and_a_seat_with_no_start_position_bind_nowhere(self, run):
        assert run.map_player(2) is None
        assert run.map_player(3) is None
        assert run.map_player(4) is None


class TestARejectedString:
    @pytest.fixture(scope="class")
    def run(self):
        return _Launch([*_FILE, b"-gameInfo", b"garbage"], parses=False)

    def test_it_returns_cleanly(self, run):
        _assert_it_returned_cleanly(run)

    def test_the_status_says_rejected(self, run):
        assert run.status == STATUS_REJECTED

    def test_nothing_is_restored_because_nothing_was_overwritten(self, run):
        assert run.named("setMap") == []
        assert run.named("setMapCRC") == []
        assert run.named("setMapSize") == []

    def test_the_saved_copy_is_still_released(self, run):
        saved = run.named("copy")[0][1]
        assert run.named("dtor") == [("dtor", saved)]

    def test_the_default_match_stands(self, run):
        assert run.state(1) == GAME_SLOT_STATE_EASY_AI
        assert run.map_player(0) == b"Player_1"
        assert run.map_player(1) == b"Player_2"
