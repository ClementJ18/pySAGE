"""`replacement-transfer`'s `HORDE` flag, executed.

`horde_copy` is run under Unicorn over the real `game.dat` when this checkout has one and the
synthetic stand-in otherwise. Two hordes are built in memory: a contain list per horde, the leader
and banner-carrier IDs on the horde interface, member bodies whose ratio and maximum getters are
real x87 code, and member experience trackers. The engine routines the cave calls - the horde
interface lookup, the member removal slot, `destroyObject`, the experience-account lookup and
`HORDE_EXPERIENCE_ADD` - are answered in Python and recorded.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")
pytest.importorskip("pefile", reason="the emulator harness maps the image with pefile")

from sage_patch.addresses import (  # noqa: E402
    BODY_GET_HEALTH_RATIO_SLOT,
    BODY_GET_MAX_HEALTH_SLOT,
    BODY_SET_HEALTH_SLOT,
    CONTAIN_ITEM_LIST,
    EXPERIENCE_TRACKER_FEEDBACK,
    EXPERIENCE_TRACKER_XP,
    GAME_LOGIC_DESTROY_OBJECT,
    HORDE_EXPERIENCE_ADD,
    HORDE_EXPERIENCE_GROUP_LOOKUP_OR_INSERT,
    HORDE_EXPERIENCE_GROUPS_OFFSET,
    HORDE_IFACE_BANNER_CARRIER_ID,
    HORDE_IFACE_LEADER_ID,
    HORDE_IFACE_REMOVE_MEMBER_SLOT,
    OBJECT_BODY_MODULE,
    OBJECT_CONTAIN,
    OBJECT_EXPERIENCE_TRACKER,
    OBJECT_GET_HORDE_IFACE,
    OBJECT_ID,
    OBJECT_TEMPLATE_EXPERIENCE_GROUP_OFFSET,
    OBJECT_THING_TEMPLATE,
    THE_GAME_LOGIC,
)
from sage_patch.patches.replacement_transfer import (  # noqa: E402
    FLAG_HORDE,
    HORDE_MEMBER_CAP,
    SECTION_NAME,
    ReplacementTransferPatch,
    layout,
)
from sage_patch.utils import find_section  # noqa: E402

from .save_machine import Machine  # noqa: E402
from .synthetic import replacement_transfer_image  # noqa: E402

REAL_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


def _patched(source: bytes) -> bytes:
    data = bytearray(source)
    ReplacementTransferPatch().apply(data)
    return bytes(data)


@pytest.fixture(scope="module")
def image() -> bytes:
    if REAL_GAME_DAT.exists():
        return _patched(REAL_GAME_DAT.read_bytes())
    return _patched(bytes(replacement_transfer_image()))


def _float(raw: int) -> float:
    return struct.unpack("<f", struct.pack("<I", raw))[0]


@dataclass
class Hordes:
    """Two hordes: `old` with `old_members`, `new` with `new_members`, each `(ratio, xp, key)`."""

    m: Machine
    removed: list[tuple[int, int]] = field(default_factory=list)
    destroyed: list[int] = field(default_factory=list)
    health_set: list[tuple[int, float]] = field(default_factory=list)
    synced: list[tuple[int, int, float]] = field(default_factory=list)
    feedback_during_sync: list[int] = field(default_factory=list)
    #: A tracker whose level-up feedback byte `_add` records, or 0.
    watch: int = 0

    def __post_init__(self) -> None:
        m = self.m
        self.at = layout(find_section(m.image, SECTION_NAME)[0])
        self.ifaces: dict[int, int] = {}
        self.accounts: dict[tuple[int, int], int] = {}
        self.templates: dict[int, int] = {}
        self.next_id = 0x100
        self.body_vt = m.alloc(0x100, bytes(0x100))
        m.write32(self.body_vt + BODY_GET_HEALTH_RATIO_SLOT, m.alloc(4, bytes.fromhex("d94108c3")))
        m.write32(self.body_vt + BODY_GET_MAX_HEALTH_SLOT, m.alloc(4, bytes.fromhex("d9410cc3")))
        m.write32(self.body_vt + BODY_SET_HEALTH_SLOT, m.stub(None, self._set_health))
        self.iface_vt = m.alloc(0x200, bytes(0x200))
        m.write32(self.iface_vt + HORDE_IFACE_REMOVE_MEMBER_SLOT, m.stub(None, self._remove))
        m.stub(OBJECT_GET_HORDE_IFACE, lambda mm: mm.ret(0, self.ifaces.get(mm.reg("ecx"), 0)))
        m.stub(GAME_LOGIC_DESTROY_OBJECT, self._destroy)
        m.stub(HORDE_EXPERIENCE_GROUP_LOOKUP_OR_INSERT, self._lookup)
        m.stub(HORDE_EXPERIENCE_ADD, self._add)
        m.ensure(THE_GAME_LOGIC)
        m.write32(THE_GAME_LOGIC, m.alloc(0x100, bytes(0x100)))

    def object(self) -> int:
        obj = self.m.alloc(0x500, bytes(0x500))
        self.m.write32(obj + OBJECT_ID, self.next_id)
        self.next_id += 1
        tracker = self.m.alloc(0x80, bytes(0x80))
        self.m.uc.mem_write(tracker + EXPERIENCE_TRACKER_FEEDBACK, b"\x01")
        self.m.write32(obj + OBJECT_EXPERIENCE_TRACKER, tracker)
        return obj

    def template(self, key: int) -> int:
        if key not in self.templates:
            tmpl = self.m.alloc(0x600, bytes(0x600))
            self.m.uc.mem_write(
                tmpl + OBJECT_TEMPLATE_EXPERIENCE_GROUP_OFFSET, struct.pack("<H", key)
            )
            self.templates[key] = tmpl
        return self.templates[key]

    def member(self, ratio: float, xp: float, key: int, maximum: float = 200.0) -> int:
        obj = self.object()
        body = self.m.alloc(0x10, bytes(0x10))
        self.m.write32(body, self.body_vt)
        self.m.uc.mem_write(body + 8, struct.pack("<ff", ratio, maximum))
        self.m.write32(obj + OBJECT_BODY_MODULE, body)
        self.m.write32(obj + OBJECT_THING_TEMPLATE, self.template(key))
        tracker = self.m.read32(obj + OBJECT_EXPERIENCE_TRACKER)
        self.m.uc.mem_write(tracker + EXPERIENCE_TRACKER_XP, struct.pack("<f", xp))
        return obj

    def horde(self, members: list[int], leader: int = 0, banner: int = 0) -> int:
        """A horde object whose contain list holds `members`, in order."""
        m = self.m
        obj = self.object()
        contain = m.alloc(0x40, bytes(0x40))
        m.write32(obj + OBJECT_CONTAIN, contain)
        sentinel = m.alloc(0x10, bytes(0x10))
        m.write32(contain + CONTAIN_ITEM_LIST, sentinel)
        previous = sentinel
        for member in members:
            node = m.alloc(0x10, bytes(0x10))
            m.write32(node + 8, member)
            m.write32(previous, node)
            previous = node
        m.write32(previous, sentinel)
        iface = m.alloc(0x200, bytes(0x200))
        m.write32(iface, self.iface_vt)
        m.write32(iface + HORDE_IFACE_LEADER_ID, m.read32(leader + OBJECT_ID) if leader else 0)
        m.write32(
            iface + HORDE_IFACE_BANNER_CARRIER_ID, m.read32(banner + OBJECT_ID) if banner else 0
        )
        self.ifaces[obj] = iface
        return obj

    def account(self, horde: int, key: int) -> float | None:
        at = self.accounts.get((self.ifaces[horde], key))
        return None if at is None else struct.unpack("<f", self.m.uc.mem_read(at, 4))[0]

    def _set_health(self, m: Machine) -> None:
        self.health_set.append((m.reg("ecx"), _float(m.arg(0))))
        m.ret(4)

    def _remove(self, m: Machine) -> None:
        self.removed.append((m.reg("ecx"), m.arg(0)))
        m.ret(4)

    def _destroy(self, m: Machine) -> None:
        self.destroyed.append(m.arg(0))
        m.ret(4)

    def _lookup(self, m: Machine) -> None:
        iface = m.reg("ecx") - HORDE_EXPERIENCE_GROUPS_OFFSET
        key = struct.unpack("<H", m.uc.mem_read(m.arg(0), 2))[0]
        if (iface, key) not in self.accounts:
            self.accounts[(iface, key)] = m.alloc(4, bytes(4))
        m.ret(4, self.accounts[(iface, key)])

    def _add(self, m: Machine) -> None:
        if self.watch:
            feedback = m.uc.mem_read(self.watch + EXPERIENCE_TRACKER_FEEDBACK, 1)[0]
            self.feedback_during_sync.append(feedback)
        self.synced.append((m.reg("ecx"), m.arg(0), _float(m.arg(1))))
        m.ret(8)

    def body(self, obj: int) -> int:
        return self.m.read32(obj + OBJECT_BODY_MODULE)

    def run(self, old: int, new: int) -> None:
        tracker = self.m.read32(new + OBJECT_EXPERIENCE_TRACKER)
        self.new_tracker = tracker
        self.m.call(self.at["horde_copy"], old, new)


@pytest.fixture
def hordes(image: bytes) -> Hordes:
    return Hordes(Machine(image))


class TestCount:
    def test_new_members_without_an_old_partner_leave_and_are_destroyed(self, hordes: Hordes):
        old_members = [hordes.member(0.5, 0.0, 1) for _ in range(3)]
        new_members = [hordes.member(1.0, 0.0, 1) for _ in range(5)]
        old, new = hordes.horde(old_members), hordes.horde(new_members)
        hordes.run(old, new)
        assert hordes.removed == [(hordes.ifaces[new], member) for member in new_members[3:]]
        assert hordes.destroyed == new_members[3:]

    def test_a_larger_old_horde_removes_nobody(self, hordes: Hordes):
        old = hordes.horde([hordes.member(1.0, 0.0, 1) for _ in range(6)])
        new = hordes.horde([hordes.member(1.0, 0.0, 1) for _ in range(4)])
        hordes.run(old, new)
        assert hordes.destroyed == []

    def test_the_banner_carrier_stays_only_if_the_old_one_lives(self, hordes: Hordes):
        old_members = [hordes.member(1.0, 0.0, 1) for _ in range(3)]
        banner, *rest = [hordes.member(1.0, 0.0, 1) for _ in range(4)]
        old = hordes.horde(old_members)  # its banner carrier is dead: id 0
        new = hordes.horde([banner, *rest], banner=banner)
        hordes.run(old, new)
        assert hordes.destroyed == [banner]

    def test_leader_and_banner_pair_with_their_old_counterparts(self, hordes: Hordes):
        old_leader = hordes.member(0.25, 0.0, 1)
        old_banner = hordes.member(0.75, 0.0, 1)
        old_plain = hordes.member(0.5, 0.0, 1)
        new_plain = hordes.member(1.0, 0.0, 1)
        new_banner = hordes.member(1.0, 0.0, 1)
        new_leader = hordes.member(1.0, 0.0, 1)
        old = hordes.horde(
            [old_plain, old_banner, old_leader], leader=old_leader, banner=old_banner
        )
        new = hordes.horde(
            [new_plain, new_banner, new_leader], leader=new_leader, banner=new_banner
        )
        hordes.run(old, new)
        assert hordes.destroyed == []
        assert sorted(hordes.health_set) == sorted(
            [
                (hordes.body(new_plain), 100.0),  # 0.5 of 200
                (hordes.body(new_banner), 150.0),  # 0.75
                (hordes.body(new_leader), 50.0),  # 0.25
            ]
        )

    def test_an_empty_old_horde_changes_nothing(self, hordes: Hordes):
        old = hordes.horde([])
        new = hordes.horde([hordes.member(1.0, 0.0, 1)])
        hordes.run(old, new)
        assert (hordes.destroyed, hordes.health_set, hordes.synced) == ([], [], [])

    def test_a_non_horde_on_either_side_changes_nothing(self, hordes: Hordes):
        old = hordes.horde([hordes.member(0.5, 0.0, 1)])
        plain = hordes.object()
        hordes.run(old, plain)
        hordes.run(plain, old)
        assert (hordes.destroyed, hordes.health_set) == ([], [])

    def test_more_members_than_the_cap_are_left_alone(self, hordes: Hordes):
        count = HORDE_MEMBER_CAP + 3
        old = hordes.horde([hordes.member(1.0, 0.0, 1) for _ in range(count)])
        new = hordes.horde([hordes.member(1.0, 0.0, 1) for _ in range(count)])
        hordes.run(old, new)
        assert hordes.destroyed == []
        assert len(hordes.health_set) == HORDE_MEMBER_CAP


class TestHealth:
    def test_paired_members_take_their_partners_ratio_of_their_own_maximum(self, hordes: Hordes):
        old = hordes.horde([hordes.member(0.5, 0.0, 1), hordes.member(0.25, 0.0, 1)])
        a, b = hordes.member(1.0, 0.0, 1, 300.0), hordes.member(1.0, 0.0, 1, 100.0)
        new = hordes.horde([a, b])
        hordes.run(old, new)
        assert hordes.health_set == [(hordes.body(a), 150.0), (hordes.body(b), 25.0)]

    def test_a_ratio_of_zero_sets_nothing(self, hordes: Hordes):
        old = hordes.horde([hordes.member(0.0, 0.0, 1)])
        new = hordes.horde([hordes.member(1.0, 0.0, 1)])
        hordes.run(old, new)
        assert hordes.health_set == []


class TestExperience:
    def test_each_group_account_rises_to_the_best_partner(self, hordes: Hordes):
        old = hordes.horde(
            [
                hordes.member(1.0, 300.0, 1),
                hordes.member(1.0, 500.0, 1),
                hordes.member(1.0, 80.0, 2),
            ]
        )
        kept = [hordes.member(1.0, 0.0, 1), hordes.member(1.0, 0.0, 1), hordes.member(1.0, 0.0, 2)]
        new = hordes.horde(kept)
        hordes.run(old, new)
        assert (hordes.account(new, 1), hordes.account(new, 2)) == (500.0, 80.0)

    def test_an_account_is_never_lowered(self, hordes: Hordes):
        old = hordes.horde([hordes.member(1.0, 50.0, 1)])
        member = hordes.member(1.0, 0.0, 1)
        new = hordes.horde([member])
        iface = hordes.ifaces[new]
        hordes.accounts[(iface, 1)] = hordes.m.alloc(4, struct.pack("<f", 400.0))
        hordes.run(old, new)
        assert hordes.account(new, 1) == 400.0

    def test_every_kept_member_is_synced_with_a_zero_delta(self, hordes: Hordes):
        old = hordes.horde([hordes.member(1.0, 10.0, 1)])
        kept, dropped = hordes.member(1.0, 0.0, 1), hordes.member(1.0, 0.0, 1)
        new = hordes.horde([kept, dropped])
        hordes.run(old, new)
        assert hordes.synced == [(hordes.ifaces[new], kept, 0.0)]

    def test_the_horde_feedback_is_off_during_the_sync_and_restored(self, hordes: Hordes):
        old = hordes.horde([hordes.member(1.0, 10.0, 1)])
        new = hordes.horde([hordes.member(1.0, 0.0, 1)])
        tracker = hordes.m.read32(new + OBJECT_EXPERIENCE_TRACKER)
        hordes.watch = tracker
        hordes.run(old, new)
        assert hordes.feedback_during_sync == [0]
        assert hordes.m.uc.mem_read(tracker + EXPERIENCE_TRACKER_FEEDBACK, 1)[0] == 1


def test_the_flag_reaches_horde_copy_from_the_transfer(image: bytes):
    hordes = Hordes(Machine(image))
    old = hordes.horde([hordes.member(0.5, 0.0, 1)])
    new = hordes.horde([hordes.member(1.0, 0.0, 1), hordes.member(1.0, 0.0, 1)])
    hordes.m.call(hordes.at["transfer"], old, new, FLAG_HORDE)
    assert len(hordes.destroyed) == 1
    assert len(hordes.health_set) == 1
