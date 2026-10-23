"""`horde-self-experience`, executed.

The sibling file reads the cave back as text. This one runs it under Unicorn, over the real
`game.dat` when this checkout has one and the synthetic stand-in otherwise. The horde interface's
`HORDE_EXPERIENCE_ADD` slot is answered in Python, so each case is a horde of known members and
a record of which members the cave credits, with how much.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")
pytest.importorskip("pefile", reason="the emulator harness maps the image with pefile")

from sage_patch.addresses import (  # noqa: E402
    CONTAIN_ITEM_LIST,
    CONTAIN_ITEM_LIST_NODE_OBJECT,
    HORDE_CONTAIN_IFACE,
    HORDE_IFACE_EXPERIENCE_ADD_SLOT,
    MODULE_OWNING_OBJECT,
    OBJECT_CONTAIN,
    OBJECT_TEMPLATE_EXPERIENCE_GROUP_OFFSET,
    OBJECT_THING_TEMPLATE,
)
from sage_patch.patches.horde_self_experience import (  # noqa: E402
    GROUP_CAP,
    SECTION_NAME,
    HordeSelfExperiencePatch,
    layout,
)
from sage_patch.utils import find_section  # noqa: E402

from .save_machine import Machine  # noqa: E402
from .synthetic import horde_self_experience_image  # noqa: E402

REAL_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


def _patched(source: bytes) -> bytes:
    data = bytearray(source)
    HordeSelfExperiencePatch().apply(data)
    return bytes(data)


@pytest.fixture(scope="module")
def image() -> bytes:
    if REAL_GAME_DAT.exists():
        return _patched(REAL_GAME_DAT.read_bytes())
    return _patched(bytes(horde_self_experience_image()))


def _float(raw: int) -> float:
    return struct.unpack("<f", struct.pack("<I", raw))[0]


def _f(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


@dataclass
class Horde:
    """A horde object with a `HordeContain`, its members, and every `HORDE_EXPERIENCE_ADD`."""

    m: Machine
    adds: list[tuple[int, int, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        m = self.m
        self.at = layout(find_section(m.image, SECTION_NAME)[0])
        self.module = m.alloc(0x400, bytes(0x400))
        self.iface = self.module + HORDE_CONTAIN_IFACE
        vtable = m.alloc(0x200, bytes(0x200))
        m.write32(vtable + HORDE_IFACE_EXPERIENCE_ADD_SLOT, m.stub(None, self._add))
        m.write32(self.iface, vtable)
        self.horde = self.object(group=0x7777)
        m.write32(self.module + MODULE_OWNING_OBJECT, self.horde)
        self.contain = m.alloc(0x100, bytes(0x100))
        self.sentinel = m.alloc(0x10, bytes(0x10))
        m.write32(self.sentinel, self.sentinel)
        m.write32(self.contain + CONTAIN_ITEM_LIST, self.sentinel)
        m.write32(self.horde + OBJECT_CONTAIN, self.contain)
        self._tail = self.sentinel

    def object(self, group: int) -> int:
        template = self.m.alloc(0x600, bytes(0x600))
        self.m.uc.mem_write(
            template + OBJECT_TEMPLATE_EXPERIENCE_GROUP_OFFSET, struct.pack("<H", group)
        )
        obj = self.m.alloc(0x300, bytes(0x300))
        self.m.write32(obj + OBJECT_THING_TEMPLATE, template)
        return obj

    def member(self, group: int) -> int:
        """A new member of experience group `group`, appended to the contained list."""
        obj = self.object(group)
        node = self.m.alloc(0x10, bytes(0x10))
        self.m.write32(node, self.sentinel)
        self.m.write32(node + CONTAIN_ITEM_LIST_NODE_OBJECT, obj)
        self.m.write32(self._tail, node)
        self._tail = node
        return obj

    def _add(self, m: Machine) -> None:
        self.adds.append((m.reg("ecx"), m.arg(0), _float(m.arg(1))))
        m.ret(8)

    def credit(self, killer: int, xp: float) -> None:
        self.m.call(self.at["distribute"], killer, _f(xp), ecx=self.iface)


@pytest.fixture
def horde(image: bytes) -> Horde:
    return Horde(Machine(image))


def test_the_owner_offset_reaches_the_horde_object(horde: Horde):
    assert horde.m.read32(horde.iface + (MODULE_OWNING_OBJECT - HORDE_CONTAIN_IFACE)) == horde.horde


class TestAMemberKiller:
    def test_goes_to_the_slot_unchanged(self, horde: Horde):
        orc = horde.member(1)
        horde.credit(orc, 25.0)
        assert horde.adds == [(horde.iface, orc, 25.0)]


class TestTheHordeItself:
    def test_one_group_gets_the_whole_amount_once(self, horde: Horde):
        orcs = [horde.member(1) for _ in range(5)]
        horde.credit(horde.horde, 40.0)
        assert horde.adds == [(horde.iface, orcs[0], 40.0)]

    def test_each_group_of_a_combo_gets_the_whole_amount(self, horde: Horde):
        """Orcs, an overseer among them, and more orcs: one call per group, in list order."""
        orc = horde.member(1)
        horde.member(1)
        overseer = horde.member(2)
        horde.member(1)
        horde.credit(horde.horde, 40.0)
        assert horde.adds == [(horde.iface, orc, 40.0), (horde.iface, overseer, 40.0)]

    def test_an_empty_horde_keeps_the_stock_call(self, horde: Horde):
        horde.credit(horde.horde, 40.0)
        assert horde.adds == [(horde.iface, horde.horde, 40.0)]

    def test_a_horde_without_a_contain_keeps_the_stock_call(self, horde: Horde):
        horde.m.write32(horde.horde + OBJECT_CONTAIN, 0)
        horde.credit(horde.horde, 40.0)
        assert horde.adds == [(horde.iface, horde.horde, 40.0)]

    def test_groups_past_the_cap_are_left_out(self, horde: Horde):
        members = [horde.member(group) for group in range(1, GROUP_CAP + 3)]
        horde.credit(horde.horde, 10.0)
        assert [member for _iface, member, _xp in horde.adds] == members[:GROUP_CAP]
