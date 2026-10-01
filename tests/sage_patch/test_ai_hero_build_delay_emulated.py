"""The AI hero build delay, executed.

`test_ai_hero_build_delay.py` reads the cave back as text. This runs it: the parser and the gate
execute under unicorn against a stand-in engine - the list parser, `nameToKey`, `AsciiString::set`
and the builder's AI-record getter are stubbed in Python, and the gate's two exits are caught
where the stock function would resume. What it pins is the behaviour the text cannot show: a delay
belongs to one faction, so two `ArmyDefinition`s naming the same hero no longer overwrite each
other's delay. Both cases are real Edain data - Boromir is delayed for Men of the West and free
for Belfalas, Círdan free for Imladris and delayed for Arnor.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.addresses import (
    AI_DATA_ARMY_DEFINITION,
    AI_HERO_BUILDER_AI_DATA,
    AI_HERO_NAME_RESOLVED_RESUME,
    AI_HERO_REJECT,
    ARMY_DEFINITION_HERO_BUILD_ORDER,
    ARMY_DEFINITION_SIDE,
    ASCII_STRING_CHARS_OFFSET,
    ASCII_STRING_SET,
    GAME_LOGIC_FRAME,
    INI_PARSE_STRING_LIST,
    LOGIC_FRAMES_PER_SECOND,
    NAME_KEY_FROM_STRING,
    THE_GAME_LOGIC,
    THE_NAME_KEY_GENERATOR,
)
from sage_patch.patches.ai_hero_build_delay import build_section, layout

unicorn = pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

SECTION = 0x00F00000
HEAP = 0x10000000
STACK = 0x20000000
PAGE = 0x1000

#: Where a routine run from Python returns to. Mapped, and stopped at.
RETURN = 0x30000000

RATE = 5
DELAY = 720


class Engine:
    """Just enough of the engine for the parser and the gate to run."""

    def __init__(self) -> None:
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        section = build_section(SECTION)
        self.uc.mem_map(SECTION, _pages(len(section)))
        self.uc.mem_write(SECTION, section)
        self.parse_va, self.gate_va = layout(SECTION)

        self.uc.mem_map(HEAP, 0x100000)
        self.uc.mem_map(STACK, 0x10000)
        self.uc.mem_map(RETURN, PAGE)
        self._heap = HEAP
        self.keys: dict[str, int] = {}
        self.exit: int | None = None

        stubs = {
            INI_PARSE_STRING_LIST: b"\xc3",  # the vector is filled in before the call
            NAME_KEY_FROM_STRING: b"\xc2\x04\x00",
            ASCII_STRING_SET: b"\xc2\x04\x00",
            AI_HERO_BUILDER_AI_DATA: b"\xc3",
            AI_HERO_NAME_RESOLVED_RESUME: b"\xf4",
            AI_HERO_REJECT: b"\xf4",
        }
        for page in {va & ~(PAGE - 1) for va in stubs}:
            self.uc.mem_map(page, PAGE)
        for va, code in stubs.items():
            self.uc.mem_write(va, code)

        for page in {
            va & ~(PAGE - 1)
            for va in (THE_NAME_KEY_GENERATOR, LOGIC_FRAMES_PER_SECOND, THE_GAME_LOGIC)
        }:
            self.uc.mem_map(page, PAGE)
        self._write(LOGIC_FRAMES_PER_SECOND, RATE)
        self.game_logic = self._alloc(0x100)
        self._write(THE_GAME_LOGIC, self.game_logic)

        self.record: int = 0
        self.uc.hook_add(UC_HOOK_CODE, self._on_code)

    def _on_code(self, uc: Uc, address: int, _size: int, _user: object) -> None:
        if address == NAME_KEY_FROM_STRING:
            string = self._read(self._read(uc.reg_read(UC_X86_REG_ESP) + 4))
            name = self._chars(string)
            uc.reg_write(UC_X86_REG_EAX, self.keys.setdefault(name, len(self.keys) + 1))
        elif address == ASCII_STRING_SET:
            source = self._read(uc.reg_read(UC_X86_REG_ESP) + 4)
            text = bytes(uc.mem_read(source, 256)).split(b"\x00", 1)[0].decode()
            self._write(uc.reg_read(UC_X86_REG_ECX), self._string_data(text))
        elif address == AI_HERO_BUILDER_AI_DATA:
            uc.reg_write(UC_X86_REG_EAX, self.record)
        elif address in (AI_HERO_NAME_RESOLVED_RESUME, AI_HERO_REJECT, RETURN):
            self.exit = address
            uc.emu_stop()

    def _alloc(self, size: int) -> int:
        va = self._heap
        self._heap += (size + 15) & ~15
        return va

    def _read(self, va: int) -> int:
        return struct.unpack("<I", self.uc.mem_read(va, 4))[0]

    def _write(self, va: int, value: int) -> None:
        self.uc.mem_write(va, struct.pack("<I", value))

    def _string_data(self, text: str) -> int:
        """An `AsciiStringData`: header, then the characters. Empty strings have none."""
        if not text:
            return 0
        data = self._alloc(ASCII_STRING_CHARS_OFFSET + len(text) + 1)
        self.uc.mem_write(data + ASCII_STRING_CHARS_OFFSET, text.encode() + b"\x00")
        return data

    def _chars(self, data: int) -> str:
        if not data:
            return ""
        raw = bytes(self.uc.mem_read(data + ASCII_STRING_CHARS_OFFSET, 256))
        return raw.split(b"\x00", 1)[0].decode()

    def string(self, text: str) -> int:
        """A fresh `AsciiString` holding `text`."""
        va = self._alloc(4)
        self._write(va, self._string_data(text))
        return va

    def army_definition(self, side: str) -> int:
        army = self._alloc(0xEC)
        self._write(army + ARMY_DEFINITION_SIDE, self._string_data(side))
        return army

    def parse(self, army: int, tokens: list[str]) -> list[str]:
        """Run the `HeroBuildOrder` row on `army`, as if the stock parser had split `tokens`."""
        elements = self._alloc(4 * len(tokens))
        for index, token in enumerate(tokens):
            self._write(elements + 4 * index, self._string_data(token))
        store = army + ARMY_DEFINITION_HERO_BUILD_ORDER
        self._write(store, elements)
        self._write(store + 4, elements + 4 * len(tokens))

        esp = STACK + 0x8000
        esp -= 16
        self.uc.mem_write(esp, struct.pack("<IIII", 0, army, store, 0))
        esp -= 4
        self._write(esp, RETURN)
        self.uc.reg_write(UC_X86_REG_ESP, esp)
        self._run(self.parse_va)
        assert self.exit == RETURN
        return [self._chars(self._read(elements + 4 * i)) for i in range(len(tokens))]

    def gate(self, hero: str, side: str | None, frame: int, index: int = 7) -> bool:
        """Ask the gate about `hero` for an AI running on `side`'s army; True means allowed.

        `side=None` is a player the AI manager has no record for.
        """
        self._write(self.game_logic + GAME_LOGIC_FRAME, frame)
        if side is None:
            self.record = 0
        else:
            self.record = self._alloc(AI_DATA_ARMY_DEFINITION + 4)
            self._write(self.record + AI_DATA_ARMY_DEFINITION, self.army_definition(side))
        esp = STACK + 0x8000
        self.uc.reg_write(UC_X86_REG_ESP, esp)
        self.uc.reg_write(UC_X86_REG_EBP, esp + 0x100)
        self.uc.reg_write(UC_X86_REG_EAX, index)
        self.uc.reg_write(UC_X86_REG_EDI, self.string(hero))
        self.uc.reg_write(UC_X86_REG_ESI, self._alloc(0x60))
        self._run(self.gate_va)
        assert self.uc.reg_read(UC_X86_REG_EAX) == index, "the hero index must survive the gate"
        assert self.uc.reg_read(UC_X86_REG_ESP) == esp, "the gate must leave the stack as found"
        return self.exit == AI_HERO_NAME_RESOLVED_RESUME

    def _run(self, start: int) -> None:
        self.exit = None
        self.uc.emu_start(start, 0xFFFFFFFF, count=100_000)
        assert self.exit is not None, "ran off without reaching an exit"


def _pages(size: int) -> int:
    return (size + PAGE - 1) & ~(PAGE - 1)


EARLY = 60 * RATE
LATE = DELAY * RATE


@pytest.fixture
def engine() -> Engine:
    return Engine()


def test_the_suffix_is_stripped_from_the_stored_name(engine):
    army = engine.army_definition("Men")
    assert engine.parse(army, ["GondorBoromir_mod:720", "GondorBeregond"]) == [
        "GondorBoromir_mod",
        "GondorBeregond",
    ]


def test_a_delayed_hero_is_refused_until_its_time_then_allowed(engine):
    engine.parse(engine.army_definition("Men"), ["GondorBoromir_mod:720"])
    assert not engine.gate("GondorBoromir_mod", "Men", EARLY)
    assert not engine.gate("GondorBoromir_mod", "Men", LATE - 1)
    assert engine.gate("GondorBoromir_mod", "Men", LATE)


def test_a_later_bare_name_in_another_faction_keeps_the_first_factions_delay(engine):
    """Edain's Boromir: `:720` in `MenOfTheWestArmy`, bare in `BelfalasArmy` parsed after it.
    Keyed on the name alone, the bare entry erased Men's delay."""
    engine.parse(engine.army_definition("Men"), ["GondorBoromir_mod:720"])
    engine.parse(engine.army_definition("Belfalas"), ["GondorBoromir_mod"])
    assert not engine.gate("GondorBoromir_mod", "Men", EARLY)
    assert engine.gate("GondorBoromir_mod", "Belfalas", EARLY)


def test_a_later_delay_in_another_faction_does_not_reach_back(engine):
    """Edain's Círdan: bare in `ImladrisArmy`, `:720` in `ArnorArmy` parsed after it. Keyed on
    the name alone, Imladris inherited Arnor's delay."""
    engine.parse(engine.army_definition("Imladris"), ["LothlorienCirdan"])
    engine.parse(engine.army_definition("Arnor"), ["LothlorienCirdan:720"])
    assert engine.gate("LothlorienCirdan", "Imladris", EARLY)
    assert not engine.gate("LothlorienCirdan", "Arnor", EARLY)


def test_two_factions_can_hold_different_delays_on_one_hero(engine):
    engine.parse(engine.army_definition("Men"), ["GondorGandalf_mod:720"])
    engine.parse(engine.army_definition("Belfalas"), ["GondorGandalf_mod:120"])
    assert not engine.gate("GondorGandalf_mod", "Belfalas", 119 * RATE)
    assert engine.gate("GondorGandalf_mod", "Belfalas", 120 * RATE)
    assert not engine.gate("GondorGandalf_mod", "Men", 120 * RATE)


def test_a_reparse_of_the_same_faction_is_authoritative(engine):
    """A name that loses its suffix loses its delay - for that faction only."""
    engine.parse(engine.army_definition("Men"), ["GondorBoromir_mod:720"])
    engine.parse(engine.army_definition("Belfalas"), ["GondorBoromir_mod:720"])
    engine.parse(engine.army_definition("Men"), ["GondorBoromir_mod"])
    assert engine.gate("GondorBoromir_mod", "Men", EARLY)
    assert not engine.gate("GondorBoromir_mod", "Belfalas", EARLY)


def test_a_reparse_replaces_rather_than_duplicates(engine):
    engine.parse(engine.army_definition("Men"), ["GondorBoromir_mod:720"])
    engine.parse(engine.army_definition("Men"), ["GondorBoromir_mod:60"])
    assert engine.gate("GondorBoromir_mod", "Men", 60 * RATE)


def test_an_undelayed_hero_is_allowed(engine):
    engine.parse(engine.army_definition("Men"), ["GondorBoromir_mod:720", "GondorBeregond"])
    assert engine.gate("GondorBeregond", "Men", 0)


def test_a_player_with_no_ai_record_gets_no_faction_delay(engine):
    """The getter answers null for a player the AI manager does not know. The gate keys that as
    no faction, and must not dereference the null."""
    engine.parse(engine.army_definition("Men"), ["GondorBoromir_mod:720"])
    assert engine.gate("GondorBoromir_mod", None, EARLY)


def test_a_block_with_no_side_only_binds_an_ai_with_no_side(engine):
    """`Side` after `HeroBuildOrder` - which no shipped block does - keys the delay on zero, and
    zero is also what an `ArmyDefinition` without a `Side` presents at the gate."""
    engine.parse(engine.army_definition(""), ["GondorBoromir_mod:720"])
    assert engine.gate("GondorBoromir_mod", "Men", EARLY)
    assert not engine.gate("GondorBoromir_mod", "", EARLY)
