"""`drain-life-fix`, executed.

The sibling file reads the cave back as text. This one runs it under Unicorn:

- **The cave's three routines**, over the real `game.dat` when this checkout has one and the
  synthetic stand-in otherwise. The body-damage step, `findObjectByID` and `attemptHealing` are
  answered in Python, so each case is a hit of known size and a source that is, or isn't, there.
- **The engine around it**, over the real `game.dat` only (skipped without it): the patched input
  constructor zeroes the padding and the patched copy constructor carries it. The stock
  `Object::attemptDamage` (an immediate hit) and the delayed-damage list's update (a hit whose
  delay runs out) both reach the drain.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")
pytest.importorskip("pefile", reason="the emulator harness maps the image with pefile")

from sage_patch.addresses import (  # noqa: E402
    DAMAGE_INFO_DAMAGE_DEALT,
    DAMAGE_INFO_DAMAGE_TYPE,
    DAMAGE_INFO_PAD_DWORD,
    DAMAGE_INFO_SOURCE_ID,
    DAMAGE_NUGGET_DRAIN_LIFE,
    DAMAGE_NUGGET_DRAIN_LIFE_MULTIPLIER,
    DAMAGE_TYPE_HEALING,
    DOT_MANAGER_ADD,
    GAME_LOGIC_FIND_OBJECT_BY_ID,
    KINDOF_PROJECTILE_BYTE,
    KINDOF_PROJECTILE_MASK,
    OBJECT_ATTEMPT_DAMAGE,
    OBJECT_ATTEMPT_HEALING,
    OBJECT_DAMAGE_NOW,
    OBJECT_THING_TEMPLATE,
    THE_GAME_LOGIC,
)
from sage_patch.patches.drain_life_fix import (  # noqa: E402
    SECTION_NAME,
    DrainLifeFixPatch,
    layout,
    pack_multiplier,
)
from sage_patch.utils import find_section  # noqa: E402

from .save_machine import Machine  # noqa: E402
from .synthetic import drain_life_fix_image  # noqa: E402

REAL_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"
needs_game_dat = pytest.mark.skipif(not REAL_GAME_DAT.exists(), reason="needs the real game.dat")

#: The input constructor and copy constructor whose byte moves the patch widens, the object's
#: delayed-damage list update, and the list erase it calls.
DAMAGE_INFO_INPUT_CTOR = 0x0066341C
DAMAGE_INFO_INPUT_COPY = 0x00662A5C
OBJECT_DELAYED_DAMAGE_UPDATE = 0x00697EB6
OBJECT_DELAYED_DAMAGE_LIST = 0x460
DELAYED_LIST_ERASE = 0x00702055
#: The object-status test `attemptDamage` opens with (`0x48`, "delay nothing").
OBJECT_TEST_STATUS_BIT = 0x0044DDEC
INFO_DELAY = 0x28
SOURCE_ID = 0x0777
TARGET = 0x0D0D0D0D


def _patched(source: bytes) -> bytes:
    data = bytearray(source)
    DrainLifeFixPatch().apply(data)
    return bytes(data)


@pytest.fixture(scope="module")
def image() -> bytes:
    if REAL_GAME_DAT.exists():
        return _patched(REAL_GAME_DAT.read_bytes())
    return _patched(bytes(drain_life_fix_image()))


def _f(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def _float(raw: int) -> float:
    return struct.unpack("<f", struct.pack("<I", raw))[0]


@dataclass
class Battle:
    """A target, a source that may be gone or be a projectile, and every hit and heal."""

    m: Machine
    dealt: float = 40.0
    source_exists: bool = True
    projectile: bool = False
    hits: list[tuple[int, int]] = field(default_factory=list)
    heals: list[tuple[int, float, int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        m = self.m
        self.at = layout(find_section(m.image, SECTION_NAME)[0])
        self.source = m.alloc(0x100, bytes(0x100))
        template = m.alloc(0x200, bytes(0x200))
        m.write32(self.source + OBJECT_THING_TEMPLATE, template)
        self.template = template
        logic = m.alloc(0x100, bytes(0x100))
        m.ensure(THE_GAME_LOGIC)
        m.write32(THE_GAME_LOGIC, logic)
        m.stub(OBJECT_DAMAGE_NOW, self._damage_now)
        m.stub(GAME_LOGIC_FIND_OBJECT_BY_ID, self._find)
        m.stub(OBJECT_ATTEMPT_HEALING, self._heal)

    def info(self, multiplier: float | None, bool_byte: int = 0, kind: int = 0x16) -> int:
        """A `DamageInfo` from `SOURCE_ID`, carrying `multiplier` as the stamp leaves it."""
        info = self.m.alloc(0x7C, bytes(0x7C))
        self.m.write32(info + DAMAGE_INFO_SOURCE_ID, SOURCE_ID)
        self.m.write32(info + DAMAGE_INFO_DAMAGE_TYPE, kind)
        packed = 0 if multiplier is None else pack_multiplier(multiplier)
        self.m.write32(info + DAMAGE_INFO_PAD_DWORD, packed | bool_byte)
        return info

    def _damage_now(self, m: Machine) -> None:
        info = m.arg(0)
        self.hits.append((m.reg("ecx"), info))
        if self.dealt is not None:
            m.uc.mem_write(info + DAMAGE_INFO_DAMAGE_DEALT, struct.pack("<f", self.dealt))
        m.ret(4)

    def _find(self, m: Machine) -> None:
        assert m.arg(0) == SOURCE_ID
        if self.projectile:
            m.uc.mem_write(self.template + KINDOF_PROJECTILE_BYTE, bytes([KINDOF_PROJECTILE_MASK]))
        m.ret(4, self.source if self.source_exists else 0)

    def _heal(self, m: Machine) -> None:
        self.heals.append((m.reg("ecx"), _float(m.arg(0)), m.arg(1)))
        m.ret(8)

    def hit(self, info: int) -> None:
        self.m.call(self.at["damage_now"], info, ecx=TARGET)


@pytest.fixture
def battle(image: bytes) -> Battle:
    return Battle(Machine(image))


class TestTheDrain:
    def test_a_stamped_hit_heals_the_source_by_multiplier_times_damage(self, battle: Battle):
        info = battle.info(0.5)
        battle.hit(info)
        assert battle.hits == [(TARGET, info)]
        assert battle.heals == [(battle.source, 20.0, 0)]

    def test_an_unstamped_hit_heals_nobody(self, battle: Battle):
        battle.hit(battle.info(None, bool_byte=1))  # the Bool alone is not a multiplier
        assert len(battle.hits) == 1
        assert battle.heals == []

    def test_the_inputs_bool_does_not_change_the_amount(self, battle: Battle):
        battle.hit(battle.info(0.25, bool_byte=1))
        assert battle.heals == [(battle.source, 10.0, 0)]

    def test_healing_damage_never_drains(self, battle: Battle):
        battle.hit(battle.info(1.0, kind=DAMAGE_TYPE_HEALING))
        assert battle.heals == []

    def test_a_hit_that_deals_nothing_heals_nothing(self, battle: Battle):
        battle.dealt = 0.0
        battle.hit(battle.info(1.0))
        assert battle.heals == []

    def test_a_previous_ticks_damage_is_not_reused(self, battle: Battle):
        """A DOT reuses its DamageInfo; a tick the body skips must not drain the last tick's
        damage again."""
        battle.dealt = None  # the body writes nothing this time
        info = battle.info(1.0)
        battle.m.uc.mem_write(info + DAMAGE_INFO_DAMAGE_DEALT, struct.pack("<f", 99.0))
        battle.hit(info)
        assert battle.heals == []

    def test_a_dead_source_is_skipped(self, battle: Battle):
        battle.source_exists = False
        battle.hit(battle.info(1.0))
        assert battle.heals == []

    def test_a_projectile_source_is_skipped(self, battle: Battle):
        battle.projectile = True
        battle.hit(battle.info(1.0))
        assert battle.heals == []


class TestTheStamps:
    def nugget(self, m: Machine, drain: bool, multiplier: float) -> int:
        nugget = m.alloc(0x200, bytes(0x200))
        m.uc.mem_write(nugget + DAMAGE_NUGGET_DRAIN_LIFE, bytes([drain]))
        m.write32(nugget + DAMAGE_NUGGET_DRAIN_LIFE_MULTIPLIER, _f(multiplier))
        return nugget

    @pytest.mark.parametrize(("drain", "expected"), [(True, pack_multiplier(1.5) | 1), (False, 1)])
    def test_attempt_stamps_then_hands_the_call_on(self, image: bytes, drain: bool, expected: int):
        m = Machine(image)
        at = layout(find_section(image, SECTION_NAME)[0])
        seen = []
        m.stub(
            OBJECT_ATTEMPT_DAMAGE, lambda mm: (seen.append((mm.reg("ecx"), mm.arg(0))), mm.ret(4))
        )
        info = m.alloc(0x7C, bytes(0x7C))
        m.write32(info + DAMAGE_INFO_PAD_DWORD, 1)  # the Bool, set
        m.call(at["stamp_attempt"], info, ecx=TARGET, esi=self.nugget(m, drain, 1.5))
        assert seen == [(TARGET, info)]
        assert m.read32(info + DAMAGE_INFO_PAD_DWORD) == expected

    def test_dot_stamps_the_stored_entry_then_registers_it(self, image: bytes):
        m = Machine(image)
        at = layout(find_section(image, SECTION_NAME)[0])
        seen = []
        m.stub(DOT_MANAGER_ADD, lambda mm: (seen.append((mm.arg(0), mm.arg(1))), mm.ret(8)))
        entry = m.alloc(0x90, bytes(0x90))
        m.call(at["stamp_dot"], 0x1234, entry, ecx=0x5555, esi=self.nugget(m, True, 0.75))
        assert seen == [(0x1234, entry)]
        assert m.read32(entry + DAMAGE_INFO_PAD_DWORD) == pack_multiplier(0.75)


@needs_game_dat
class TestTheEngine:
    def test_the_input_constructor_zeroes_the_padding(self, image: bytes):
        m = Machine(image)
        input_ = m.alloc(0x80, b"\xcc" * 0x80)
        m.call(DAMAGE_INFO_INPUT_CTOR, ecx=input_)
        assert m.read32(input_ + 0x4C) == 0

    def test_the_copy_constructor_carries_the_padding(self, image: bytes):
        m = Machine(image)
        source = m.alloc(0x80, bytes(0x80))
        m.write32(source + 0x4C, pack_multiplier(0.5) | 1)
        copy = m.alloc(0x80, b"\xcc" * 0x80)
        m.call(DAMAGE_INFO_INPUT_COPY, source, ecx=copy)
        assert m.read32(copy + 0x4C) == pack_multiplier(0.5) | 1

    def test_an_immediate_hit_through_attempt_damage_drains(self, image: bytes):
        battle = Battle(Machine(image))
        target = battle.m.alloc(0x600, bytes(0x600))
        battle.m.stub(OBJECT_TEST_STATUS_BIT, lambda mm: mm.ret(4, 0))
        info = battle.info(0.5)
        battle.m.call(OBJECT_ATTEMPT_DAMAGE, info, ecx=target)
        assert battle.hits == [(target, info)]
        assert battle.heals == [(battle.source, 20.0, 0)]

    def test_a_delayed_hit_drains_when_it_lands(self, image: bytes):
        """The target's delayed list with one queued copy whose delay runs out this frame."""
        battle = Battle(Machine(image))
        m = battle.m
        target = m.alloc(0x600, bytes(0x600))
        sentinel = m.alloc(0x10, bytes(0x10))
        node = m.alloc(0x8 + 0x7C, bytes(0x8 + 0x7C))
        m.write32(sentinel, node)
        m.write32(sentinel + 4, node)
        m.write32(node, sentinel)
        m.write32(node + 4, sentinel)
        m.write32(target + OBJECT_DELAYED_DAMAGE_LIST, sentinel)
        info = node + 8
        m.write32(info + DAMAGE_INFO_SOURCE_ID, SOURCE_ID)
        m.write32(info + DAMAGE_INFO_DAMAGE_TYPE, 0x16)
        m.write32(info + DAMAGE_INFO_PAD_DWORD, pack_multiplier(1.0))
        m.uc.mem_write(info + INFO_DELAY, struct.pack("<f", 0.5))  # lands this frame

        def erase(mm: Machine) -> None:
            out = mm.arg(0)
            mm.write32(sentinel, sentinel)
            mm.write32(sentinel + 4, sentinel)
            mm.write32(out, sentinel)
            mm.ret(8, out)

        m.stub(DELAYED_LIST_ERASE, erase)
        m.call(OBJECT_DELAYED_DAMAGE_UPDATE, ecx=target)
        assert battle.hits == [(target, info)]
        assert battle.heals == [(battle.source, 40.0, 0)]
