"""`replacement-transfer`, executed.

The sibling file reads the cave back as text. This one runs it under Unicorn:

- **The two replacement hooks**, over the real `game.dat` when this checkout has one and the
  synthetic stand-in otherwise (the cave bytes are the same either way). `Object::giveUpgrade` and
  `ExperienceTracker::setExperienceAndLevel` are answered in Python and recorded; the
  `UpgradeCenter` list the cave walks is built in memory. Each hook is entered with the frame the
  stock function has at that point and stopped where it rejoins, so the test also shows the
  displaced instructions leave the registers the stock code expects.
- **The two constructors**, over the real `game.dat` only (skipped without it), stock and patched
  side by side on a buffer pre-filled with garbage: the stock constructors leave the new field's
  byte as it was, the patched ones clear it.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")
pytest.importorskip("pefile", reason="the emulator harness maps the image with pefile")

from unicorn.x86_const import UC_X86_REG_ESP  # noqa: E402

from sage_patch.addresses import (  # noqa: E402
    APPEND_MESSAGE_VTABLE_SLOT,
    ARG_APPENDERS,
    BODY_GET_HEALTH_RATIO_SLOT,
    BODY_GET_MAX_HEALTH_SLOT,
    BODY_SET_HEALTH_SLOT,
    DRAWABLE_SELECTED,
    EXIT_INTERFACE_GET_RALLY_POINT_SLOT,
    EXIT_INTERFACE_SET_RALLY_POINT_SLOT,
    EXPERIENCE_TRACKER_FEEDBACK,
    EXPERIENCE_TRACKER_SET_ABSOLUTE,
    EXPERIENCE_TRACKER_XP,
    IN_GAME_UI_DESELECT_DRAWABLE_SLOT,
    IN_GAME_UI_SELECT_DRAWABLE_SLOT,
    INI_PARSE_BIT_STRING_32,
    MSG_ADD_TO_TEAM0,
    MSG_CREATE_SELECTED_GROUP,
    OBJECT_BODY_MODULE,
    OBJECT_EXPERIENCE_TRACKER,
    OBJECT_GET_CONTROLLING_PLAYER,
    OBJECT_GET_DRAWABLE,
    OBJECT_GET_EXIT_INTERFACE,
    OBJECT_GET_PRODUCTION_UPDATE_INTERFACE,
    OBJECT_GIVE_UPGRADE,
    OBJECT_ID,
    OBJECT_IS_LOCALLY_CONTROLLED,
    OBJECT_UPGRADE_MASK,
    PLAYER_FIND_SQUAD,
    PRODUCTION_ENTRY_NEXT,
    PRODUCTION_ENTRY_PREV,
    PRODUCTION_ENTRY_PROGRESS,
    PRODUCTION_INTERFACE_DOOR_HOLD,
    PRODUCTION_INTERFACE_ID_COUNTER,
    PRODUCTION_INTERFACE_OFFSET,
    PRODUCTION_INTERFACE_QUEUE_LENGTH,
    PRODUCTION_QUEUE_APPEND,
    REPLACE_SELF_FREE_OFFSET,
    REPLACE_SELF_MODULE_DATA_CTOR,
    REPLACE_SELF_NAME_COPY,
    REPLACE_SELF_NAME_COPY_RESUME,
    SUMMON_REPLACEMENT_FREE_OFFSET,
    SUMMON_REPLACEMENT_HEALTH_COPY_END,
    SUMMON_REPLACEMENT_MODULE_DATA_CTOR,
    SUMMON_REPLACEMENT_XP_RESTORE,
    SUMMON_REPLACEMENT_XP_RESTORE_RESUME,
    THE_IN_GAME_UI,
    THE_MESSAGE_STREAM,
    THE_UPGRADE_CENTER,
    UPGRADE_CENTER_LIST,
    UPGRADE_TEMPLATE_INDEX,
    UPGRADE_TEMPLATE_NEXT,
)
from sage_patch.patches.replacement_transfer import (  # noqa: E402
    FLAG_EXPERIENCE,
    FLAG_HEALTH,
    FLAG_PRODUCTION,
    FLAG_RALLY,
    FLAG_SELECTION,
    FLAG_UPGRADES,
    FLAGS,
    SECTION_NAME,
    ReplacementTransferPatch,
    layout,
)
from sage_patch.utils import find_section  # noqa: E402

from .save_machine import STACK, STACK_SIZE, Machine  # noqa: E402
from .synthetic import replacement_transfer_image  # noqa: E402

REAL_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"
needs_game_dat = pytest.mark.skipif(not REAL_GAME_DAT.exists(), reason="needs the real game.dat")

#: Where a jumped-into hook's stack starts: below the area `Machine.call` uses.
JUMP_ESP = STACK + STACK_SIZE - 0x4000
#: The CRT `memset` the upgrade-mask constructor reaches; it reads a CPU-feature global the
#: emulator does not set up, so it is answered in Python.
CRT_MEMSET = 0x00A3CF28

#: Upgrade mask indices in the stand-in `UpgradeCenter`, chosen across three different words.
OWNED = (3, 70)
NOT_OWNED = 40


def _patched(source: bytes) -> bytes:
    data = bytearray(source)
    ReplacementTransferPatch().apply(data)
    return bytes(data)


@pytest.fixture(scope="module")
def image() -> bytes:
    if REAL_GAME_DAT.exists():
        return _patched(REAL_GAME_DAT.read_bytes())
    return _patched(bytes(replacement_transfer_image()))


@dataclass
class World:
    """An old object, a new one, their experience trackers and an `UpgradeCenter` list."""

    m: Machine
    given: list[tuple[int, int]] = field(default_factory=list)
    xp_set: list[tuple[int, float, int, int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        m = self.m
        self.old = self._object(xp=500.0)
        self.new = self._object(xp=100.0)
        self.templates = {}
        center = m.alloc(0x40, bytes(0x40))
        previous = center + UPGRADE_CENTER_LIST
        for index in (*OWNED, NOT_OWNED):
            template = m.alloc(0x80, bytes(0x80))
            m.write32(template + UPGRADE_TEMPLATE_INDEX, index)
            m.write32(previous, template)
            previous = template + UPGRADE_TEMPLATE_NEXT
            self.templates[index] = template
        m.ensure(THE_UPGRADE_CENTER)
        m.write32(THE_UPGRADE_CENTER, center)
        for index in OWNED:
            self.set_bit(self.old, index)
        m.stub(OBJECT_GIVE_UPGRADE, self._give)
        m.stub(EXPERIENCE_TRACKER_SET_ABSOLUTE, self._set_xp)
        self._bodies()
        self._exits()
        self._client()
        self._producers()

    def _object(self, xp: float) -> int:
        m = self.m
        obj = m.alloc(0x500, bytes(0x500))
        tracker = m.alloc(0x80, bytes(0x80))
        m.uc.mem_write(tracker + EXPERIENCE_TRACKER_XP, struct.pack("<f", xp))
        m.uc.mem_write(tracker + EXPERIENCE_TRACKER_FEEDBACK, b"\x01")
        m.write32(obj + OBJECT_EXPERIENCE_TRACKER, tracker)
        return obj

    def tracker(self, obj: int) -> int:
        return self.m.read32(obj + OBJECT_EXPERIENCE_TRACKER)

    def xp(self, obj: int) -> float:
        raw = self.m.uc.mem_read(self.tracker(obj) + EXPERIENCE_TRACKER_XP, 4)
        return struct.unpack("<f", raw)[0]

    def set_xp(self, obj: int, xp: float) -> None:
        self.m.uc.mem_write(self.tracker(obj) + EXPERIENCE_TRACKER_XP, struct.pack("<f", xp))

    def set_bit(self, obj: int, index: int) -> None:
        at = obj + OBJECT_UPGRADE_MASK + 4 * (index >> 5)
        self.m.write32(at, self.m.read32(at) | 1 << (index & 31))

    def has(self, obj: int, index: int) -> bool:
        return bool(self.m.read32(obj + OBJECT_UPGRADE_MASK + 4 * (index >> 5)) >> (index & 31) & 1)

    # HEALTH: a body is `{vtable, ratio at +8, maximum at +0xC}`; the two getters are real x87
    # code over those fields, and `setHealth` is answered in Python.
    health_set: list[tuple[int, float]] = field(default_factory=list)

    def _bodies(self) -> None:
        m = self.m
        vtable = m.alloc(0x100, bytes(0x100))
        m.write32(vtable + BODY_GET_HEALTH_RATIO_SLOT, m.alloc(4, bytes.fromhex("d94108c3")))
        m.write32(vtable + BODY_GET_MAX_HEALTH_SLOT, m.alloc(4, bytes.fromhex("d9410cc3")))
        m.write32(vtable + BODY_SET_HEALTH_SLOT, m.stub(None, self._set_health))
        for obj, (ratio, maximum) in ((self.old, (0.25, 400.0)), (self.new, (1.0, 1000.0))):
            body = m.alloc(0x10, bytes(0x10))
            m.write32(body, vtable)
            m.uc.mem_write(body + 8, struct.pack("<ff", ratio, maximum))
            m.write32(obj + OBJECT_BODY_MODULE, body)

    def body(self, obj: int) -> int:
        return self.m.read32(obj + OBJECT_BODY_MODULE)

    def set_ratio(self, obj: int, ratio: float) -> None:
        self.m.uc.mem_write(self.body(obj) + 8, struct.pack("<f", ratio))

    def _set_health(self, m: Machine) -> None:
        self.health_set.append((m.reg("ecx"), struct.unpack("<f", struct.pack("<I", m.arg(0)))[0]))
        m.ret(4)

    # RALLY: each object's exit interface is `{vtable, Coord3D at +4, set flag at +0x10}`, with
    # the default exit's own get and set.
    rally_set: list[tuple[int, tuple[float, float, float]]] = field(default_factory=list)

    def _exits(self) -> None:
        m = self.m
        self.exits: dict[int, int] = {}
        vtable = m.alloc(0x40, bytes(0x40))
        m.write32(vtable + EXIT_INTERFACE_GET_RALLY_POINT_SLOT, m.stub(None, self._get_rally))
        m.write32(vtable + EXIT_INTERFACE_SET_RALLY_POINT_SLOT, m.stub(None, self._set_rally))
        for obj in (self.old, self.new):
            interface = m.alloc(0x20, bytes(0x20))
            m.write32(interface, vtable)
            self.exits[obj] = interface
        m.stub(OBJECT_GET_EXIT_INTERFACE, lambda mm: mm.ret(0, self.exits.get(mm.reg("ecx"), 0)))

    def set_rally(self, obj: int, point: tuple[float, float, float]) -> None:
        self.m.uc.mem_write(self.exits[obj] + 4, struct.pack("<fff", *point) + b"\x01")

    def _get_rally(self, m: Machine) -> None:
        interface = m.reg("ecx")
        m.ret(0, interface + 4 if m.uc.mem_read(interface + 0x10, 1)[0] else 0)

    def _set_rally(self, m: Machine) -> None:
        point = struct.unpack("<fff", m.uc.mem_read(m.arg(0), 12))
        self.rally_set.append((m.reg("ecx"), point))
        m.ret(4)

    # SELECTION: who owns what, the old object's control group, the drawables, and every
    # message posted and UI call made, in order.
    local: bool = True
    squad: int = -1
    selected: bool = False
    posted: list[tuple] = field(default_factory=list)

    def _client(self) -> None:
        m = self.m
        self.player = m.alloc(0x10, bytes(0x10))
        self.drawables = {obj: m.alloc(0x500, bytes(0x500)) for obj in (self.old, self.new)}
        m.write32(self.old + OBJECT_ID, 0x0101)
        m.write32(self.new + OBJECT_ID, 0x0202)
        m.stub(OBJECT_IS_LOCALLY_CONTROLLED, lambda mm: mm.ret(0, int(self.local)))
        m.stub(OBJECT_GET_CONTROLLING_PLAYER, lambda mm: mm.ret(0, self.player))
        m.stub(PLAYER_FIND_SQUAD, self._find_squad)
        m.stub(OBJECT_GET_DRAWABLE, lambda mm: mm.ret(0, self.drawables.get(mm.reg("ecx"), 0)))
        stream_vt = m.alloc(0x100, bytes(0x100))
        m.write32(stream_vt + APPEND_MESSAGE_VTABLE_SLOT, m.stub(None, self._append))
        stream = m.alloc(0x10, bytes(0x10))
        m.write32(stream, stream_vt)
        m.ensure(THE_MESSAGE_STREAM)
        m.write32(THE_MESSAGE_STREAM, stream)
        ui_vt = m.alloc(0x200, bytes(0x200))
        for slot, what in (
            (IN_GAME_UI_SELECT_DRAWABLE_SLOT, "select"),
            (IN_GAME_UI_DESELECT_DRAWABLE_SLOT, "deselect"),
        ):
            m.write32(ui_vt + slot, m.stub(None, lambda mm, w=what: self._ui(mm, w)))
        ui = m.alloc(0x10, bytes(0x10))
        m.write32(ui, ui_vt)
        m.ensure(THE_IN_GAME_UI)
        m.write32(THE_IN_GAME_UI, ui)
        for kind, va in (("bool", ARG_APPENDERS[2]), ("id", ARG_APPENDERS[3])):
            m.stub(va, lambda mm, k=kind: self._argument(mm, k))

    def select_old(self) -> None:
        self.m.uc.mem_write(self.drawables[self.old] + DRAWABLE_SELECTED, b"\x01")

    def _find_squad(self, m: Machine) -> None:
        assert (m.reg("ecx"), m.arg(0)) == (self.player, self.old)
        m.ret(4, self.squad & 0xFFFFFFFF)

    def _append(self, m: Machine) -> None:
        message = m.alloc(0x10, bytes(0x10))
        self.posted.append(("message", m.arg(0), message))
        m.ret(4, message)

    def _argument(self, m: Machine, kind: str) -> None:
        self.posted.append((kind, m.reg("ecx"), m.arg(0)))
        m.ret(4)

    def _ui(self, m: Machine, what: str) -> None:
        self.posted.append((what, m.arg(0)))
        m.ret(4)

    # PRODUCTION: a `ProductionUpdate` per object (the module, its interface at `+0x20`), and
    # `append` answered in Python with the stock linking, recording what it was handed.
    appended: list[tuple[int, int, int, int]] = field(default_factory=list)

    def _producers(self) -> None:
        m = self.m
        self.interfaces = {}
        for obj in (self.old, self.new):
            module = m.alloc(0x200, bytes(0x200))
            self.interfaces[obj] = module + PRODUCTION_INTERFACE_OFFSET
        m.stub(
            OBJECT_GET_PRODUCTION_UPDATE_INTERFACE,
            lambda mm: mm.ret(4, self.interfaces.get(mm.reg("ecx"), 0)),
        )
        m.stub(PRODUCTION_QUEUE_APPEND, self._append_entry)

    def queue(self, obj: int, *entries: tuple[float, int]) -> list[int]:
        """Queue `(progress, production id)` entries on `obj`, linked as `append` links them."""
        made = []
        for progress, pid in entries:
            entry = self.m.alloc(0x54, bytes(0x54))
            self.m.uc.mem_write(entry + PRODUCTION_ENTRY_PROGRESS, struct.pack("<f", progress))
            self.m.write32(entry + 0x10, pid)
            self._link(self.interfaces[obj] - PRODUCTION_INTERFACE_OFFSET, entry)
            made.append(entry)
        return made

    def _link(self, module: int, entry: int) -> None:
        m = self.m
        head, tail, length = module + 0x28, module + 0x2C, module + 0x34
        if m.read32(head) == 0:
            m.write32(head, entry)
        if m.read32(tail):
            m.write32(m.read32(tail) + PRODUCTION_ENTRY_NEXT, entry)
            m.write32(entry + PRODUCTION_ENTRY_PREV, m.read32(tail))
        m.write32(length, m.read32(length) + 1)
        m.write32(tail, entry)

    def _append_entry(self, m: Machine) -> None:
        module, entry = m.reg("ecx"), m.arg(0)
        next_, prev = (
            m.read32(entry + PRODUCTION_ENTRY_NEXT),
            m.read32(entry + PRODUCTION_ENTRY_PREV),
        )
        self.appended.append((module, entry, next_, prev))
        self._link(module, entry)
        m.ret(4)

    def entries(self, obj: int) -> list[int]:
        out, entry = [], self.m.read32(self.interfaces[obj] - PRODUCTION_INTERFACE_OFFSET + 0x28)
        while entry:
            out.append(entry)
            entry = self.m.read32(entry + PRODUCTION_ENTRY_NEXT)
        return out

    def length(self, obj: int) -> int:
        return self.m.read32(self.interfaces[obj] + PRODUCTION_INTERFACE_QUEUE_LENGTH)

    def _give(self, m: Machine) -> None:
        template = m.arg(0)
        index = m.read32(template + UPGRADE_TEMPLATE_INDEX)
        self.given.append((m.reg("ecx"), index))
        self.set_bit(m.reg("ecx"), index)
        m.ret(4)

    def _set_xp(self, m: Machine) -> None:
        tracker = m.reg("ecx")
        xp = struct.unpack("<f", struct.pack("<I", m.arg(0)))[0]
        feedback = m.uc.mem_read(tracker + EXPERIENCE_TRACKER_FEEDBACK, 1)[0]
        self.xp_set.append((tracker, xp, m.arg(1), feedback))
        m.uc.mem_write(tracker + EXPERIENCE_TRACKER_XP, struct.pack("<f", xp))
        m.ret(8)


def _run_replace_self(world: World, flags: int) -> dict[str, int]:
    """Enter `upgradeImplementation` at the hooked name copy with its frame and stop at the
    rejoin. `[ebp-0x50]` is the ModuleData, `edi` the new object, `[esi-8]` the old one."""
    m = world.m
    module_data = m.alloc(0x200, bytes(0x200))
    m.uc.mem_write(module_data + REPLACE_SELF_FREE_OFFSET, bytes([flags]))
    frame = m.frame()
    m.write32(frame - 0x50, module_data)
    interface = m.alloc(0x40, bytes(0x40)) + 0x20
    m.write32(interface - 8, world.old)
    m.stop_at(REPLACE_SELF_NAME_COPY_RESUME)
    m.run(
        REPLACE_SELF_NAME_COPY,
        JUMP_ESP,
        ebp=frame,
        edi=world.new,
        esi=interface,
        ebx=0x0B0B0B0B,
    )
    assert m.stopped_at == REPLACE_SELF_NAME_COPY_RESUME
    return {
        "eax": m.reg("eax"),
        "ecx": m.reg("ecx"),
        "esp": m.uc.reg_read(UC_X86_REG_ESP),
        "ebx": m.reg("ebx"),
        "esi": m.reg("esi"),
        "edi": m.reg("edi"),
        "ebp": m.reg("ebp"),
        "frame": frame,
        "interface": interface,
    }


def _run_summon(world: World, flags: int) -> int:
    """Enter the summon swap after its experience copy: `esi` the new object, `edi` the old,
    `[ebp-0x18]` the module whose `+4` is the ModuleData."""
    m = world.m
    module_data = m.alloc(0x100, bytes(0x100))
    m.uc.mem_write(module_data + SUMMON_REPLACEMENT_FREE_OFFSET, bytes([flags]))
    module = m.alloc(0x40, bytes(0x40))
    m.write32(module + 4, module_data)
    frame = m.frame()
    m.write32(frame - 0x18, module)
    m.stop_at(SUMMON_REPLACEMENT_XP_RESTORE_RESUME, SUMMON_REPLACEMENT_HEALTH_COPY_END)
    m.run(SUMMON_REPLACEMENT_XP_RESTORE, JUMP_ESP, ebp=frame, esi=world.new, edi=world.old)
    assert m.uc.reg_read(UC_X86_REG_ESP) == JUMP_ESP
    return m.stopped_at


class TestReplaceSelfUpgrade:
    def test_no_flags_is_stock(self, image: bytes):
        world = World(Machine(image))
        _run_replace_self(world, 0)
        assert world.given == []
        assert world.xp_set == []

    def test_the_rejoin_sees_what_the_stock_pair_computes(self, image: bytes):
        world = World(Machine(image))
        regs = _run_replace_self(world, FLAG_UPGRADES | FLAG_EXPERIENCE)
        assert regs["eax"] == regs["frame"] - 0x24
        assert regs["ecx"] == world.new + 0x88
        assert regs["esp"] == JUMP_ESP
        assert (regs["ebx"], regs["esi"], regs["edi"], regs["ebp"]) == (
            0x0B0B0B0B,
            regs["interface"],
            world.new,
            regs["frame"],
        )

    def test_upgrades_carries_every_owned_upgrade_and_nothing_else(self, image: bytes):
        world = World(Machine(image))
        _run_replace_self(world, FLAG_UPGRADES)
        assert sorted(world.given) == sorted((world.new, index) for index in OWNED)
        assert not world.has(world.new, NOT_OWNED)
        assert world.xp_set == []

    def test_an_upgrade_the_new_object_already_has_is_not_granted_again(self, image: bytes):
        world = World(Machine(image))
        world.set_bit(world.new, OWNED[0])
        _run_replace_self(world, FLAG_UPGRADES)
        assert world.given == [(world.new, OWNED[1])]

    def test_experience_raises_with_feedback_off_and_restores_it(self, image: bytes):
        world = World(Machine(image))
        _run_replace_self(world, FLAG_EXPERIENCE)
        assert world.xp_set == [(world.tracker(world.new), 500.0, 1, 0)]
        assert world.xp(world.new) == 500.0
        feedback = world.m.uc.mem_read(world.tracker(world.new) + EXPERIENCE_TRACKER_FEEDBACK, 1)
        assert feedback[0] == 1
        assert world.given == []

    def test_experience_is_never_lowered(self, image: bytes):
        world = World(Machine(image))
        world.set_xp(world.new, 900.0)
        _run_replace_self(world, FLAG_EXPERIENCE)
        assert world.xp_set == []
        assert world.xp(world.new) == 900.0


class TestSummonReplacement:
    def test_no_flags_is_stock(self, image: bytes):
        world = World(Machine(image))
        _run_summon(world, 0)
        assert world.given == []
        assert world.xp_set == []

    def test_upgrades_are_carried_and_the_feedback_flag_is_put_back(self, image: bytes):
        world = World(Machine(image))
        world.m.uc.mem_write(world.tracker(world.new) + EXPERIENCE_TRACKER_FEEDBACK, b"\x00")
        _run_summon(world, FLAG_UPGRADES)
        assert sorted(world.given) == sorted((world.new, index) for index in OWNED)
        feedback = world.m.uc.mem_read(world.tracker(world.new) + EXPERIENCE_TRACKER_FEEDBACK, 1)
        assert feedback[0] == 1

    def test_experience_after_the_stock_copy_changes_nothing(self, image: bytes):
        """Stock has already copied the experience by this point, so the two are equal."""
        world = World(Machine(image))
        world.set_xp(world.new, world.xp(world.old))
        _run_summon(world, FLAG_EXPERIENCE)
        assert world.xp_set == []


class TestHealth:
    def test_the_new_body_takes_the_old_ratio_of_its_own_maximum(self, image: bytes):
        world = World(Machine(image))
        _run_replace_self(world, FLAG_HEALTH)
        assert world.health_set == [(world.body(world.new), 250.0)]  # 0.25 of 1000

    def test_a_ratio_of_zero_sets_nothing(self, image: bytes):
        world = World(Machine(image))
        world.set_ratio(world.old, 0.0)
        _run_replace_self(world, FLAG_HEALTH)
        assert world.health_set == []

    def test_without_the_flag_health_is_untouched(self, image: bytes):
        world = World(Machine(image))
        _run_replace_self(world, FLAG_UPGRADES | FLAG_EXPERIENCE | FLAG_RALLY)
        assert world.health_set == []

    def test_on_the_summon_swap_it_replaces_the_stock_absolute_copy(self, image: bytes):
        world = World(Machine(image))
        assert _run_summon(world, FLAG_HEALTH) == SUMMON_REPLACEMENT_HEALTH_COPY_END
        assert world.health_set == [(world.body(world.new), 250.0)]

    def test_without_it_the_summon_swap_keeps_its_copy(self, image: bytes):
        world = World(Machine(image))
        assert _run_summon(world, FLAG_UPGRADES) == SUMMON_REPLACEMENT_XP_RESTORE_RESUME
        assert world.health_set == []


class TestRally:
    def test_a_set_rally_point_is_carried(self, image: bytes):
        world = World(Machine(image))
        world.set_rally(world.old, (10.5, -20.25, 3.0))
        _run_replace_self(world, FLAG_RALLY)
        assert world.rally_set == [(world.exits[world.new], (10.5, -20.25, 3.0))]

    def test_no_rally_point_sets_nothing(self, image: bytes):
        world = World(Machine(image))
        _run_replace_self(world, FLAG_RALLY)
        assert world.rally_set == []

    def test_a_new_object_without_an_exit_sets_nothing(self, image: bytes):
        world = World(Machine(image))
        world.set_rally(world.old, (1.0, 2.0, 3.0))
        del world.exits[world.new]
        _run_replace_self(world, FLAG_RALLY)
        assert world.rally_set == []

    def test_it_works_on_the_summon_swap_too(self, image: bytes):
        world = World(Machine(image))
        world.set_rally(world.old, (1.0, 2.0, 3.0))
        _run_summon(world, FLAG_RALLY)
        assert world.rally_set == [(world.exits[world.new], (1.0, 2.0, 3.0))]


class TestSelection:
    def test_a_selected_object_in_a_group_hands_both_over(self, image: bytes):
        world = World(Machine(image))
        world.squad = 4
        world.select_old()
        _run_replace_self(world, FLAG_SELECTION)
        team, select = (p for p in world.posted if p[0] == "message")
        old, new = world.drawables[world.old], world.drawables[world.new]
        assert world.posted == [
            ("message", MSG_ADD_TO_TEAM0 + 4, team[2]),
            ("id", team[2], 0x0202),
            ("deselect", old),
            ("message", MSG_CREATE_SELECTED_GROUP, select[2]),
            ("bool", select[2], 0),
            ("id", select[2], 0x0202),
            ("select", new),
        ]

    def test_an_unselected_object_outside_any_group_posts_nothing(self, image: bytes):
        world = World(Machine(image))
        _run_replace_self(world, FLAG_SELECTION)
        assert world.posted == []

    def test_only_the_owner_posts(self, image: bytes):
        world = World(Machine(image))
        world.local = False
        world.squad = 2
        world.select_old()
        _run_replace_self(world, FLAG_SELECTION)
        assert world.posted == []

    def test_the_summon_swap_does_it_in_stock_so_the_flag_is_dropped_there(self, image: bytes):
        world = World(Machine(image))
        world.squad = 1
        world.select_old()
        _run_summon(world, FLAG_SELECTION)
        assert world.posted == []

    def test_all_five_together(self, image: bytes):
        world = World(Machine(image))
        world.squad = 0
        world.set_rally(world.old, (5.0, 6.0, 7.0))
        _run_replace_self(world, (1 << len(FLAGS)) - 1)
        assert sorted(world.given) == sorted((world.new, index) for index in OWNED)
        assert world.xp(world.new) == 500.0
        assert world.health_set == [(world.body(world.new), 250.0)]
        assert world.rally_set == [(world.exits[world.new], (5.0, 6.0, 7.0))]
        (_, team, message), (_, target, new_id) = world.posted  # the group, not the selection
        assert (team, target, new_id) == (MSG_ADD_TO_TEAM0, message, 0x0202)


class TestProduction:
    def test_the_queue_moves_in_order_with_its_progress(self, image: bytes):
        world = World(Machine(image))
        moved = world.queue(world.old, (37.5, 1), (0.0, 2), (0.0, 3))
        _run_replace_self(world, FLAG_PRODUCTION)
        assert world.entries(world.new) == moved
        assert (world.length(world.new), world.length(world.old)) == (3, 0)
        assert world.entries(world.old) == []
        raw = world.m.uc.mem_read(moved[0] + PRODUCTION_ENTRY_PROGRESS, 4)
        assert struct.unpack("<f", raw)[0] == 37.5

    def test_each_entry_is_unlinked_before_it_is_appended(self, image: bytes):
        world = World(Machine(image))
        world.queue(world.old, (0.0, 1), (0.0, 2))
        _run_replace_self(world, FLAG_PRODUCTION)
        new_module = world.interfaces[world.new] - PRODUCTION_INTERFACE_OFFSET
        assert [(module, n, p) for module, _e, n, p in world.appended] == [(new_module, 0, 0)] * 2

    def test_it_goes_after_what_the_new_producer_already_has(self, image: bytes):
        world = World(Machine(image))
        (own,) = world.queue(world.new, (0.0, 9))
        moved = world.queue(world.old, (10.0, 1))
        _run_replace_self(world, FLAG_PRODUCTION)
        assert world.entries(world.new) == [own, *moved]

    def test_a_unit_held_at_the_old_door_stays_behind(self, image: bytes):
        world = World(Machine(image))
        held, waiting = world.queue(world.old, (100.0, 1), (20.0, 2))
        world.m.write32(world.interfaces[world.old] + PRODUCTION_INTERFACE_DOOR_HOLD, 1)
        _run_replace_self(world, FLAG_PRODUCTION)
        assert world.entries(world.old) == [held]
        assert world.entries(world.new) == [waiting]

    def test_a_finished_entry_without_a_door_hold_moves(self, image: bytes):
        world = World(Machine(image))
        done = world.queue(world.old, (100.0, 1))
        _run_replace_self(world, FLAG_PRODUCTION)
        assert world.entries(world.new) == done

    @pytest.mark.parametrize(("old", "new", "after"), [(7, 2, 7), (3, 5, 5)])
    def test_the_id_counter_is_only_ever_raised(self, image: bytes, old: int, new: int, after: int):
        world = World(Machine(image))
        world.m.write32(world.interfaces[world.old] + PRODUCTION_INTERFACE_ID_COUNTER, old)
        world.m.write32(world.interfaces[world.new] + PRODUCTION_INTERFACE_ID_COUNTER, new)
        _run_replace_self(world, FLAG_PRODUCTION)
        assert (
            world.m.read32(world.interfaces[world.new] + PRODUCTION_INTERFACE_ID_COUNTER) == after
        )

    def test_a_replacement_that_is_not_a_producer_leaves_the_queue_alone(self, image: bytes):
        world = World(Machine(image))
        kept = world.queue(world.old, (0.0, 1))
        del world.interfaces[world.new]
        _run_replace_self(world, FLAG_PRODUCTION)
        assert world.appended == []
        assert (
            world.m.read32(world.interfaces[world.old] - PRODUCTION_INTERFACE_OFFSET + 0x28)
            == (kept[0])
        )

    def test_without_the_flag_nothing_moves(self, image: bytes):
        world = World(Machine(image))
        kept = world.queue(world.old, (0.0, 1))
        _run_replace_self(world, FLAG_UPGRADES | FLAG_RALLY)
        assert world.entries(world.old) == kept
        assert world.appended == []


class TestTheParseShim:
    """The shim hands the stock bit-string parser a dword temp seeded from the byte, and stores
    the low byte back. The parser is answered in Python: it records what it was handed and ORs
    in a bit, the way a `+NAME` token does."""

    @pytest.mark.parametrize("before", [0x00, FLAG_EXPERIENCE])
    def test_it_seeds_from_the_byte_and_writes_one_byte_back(self, image: bytes, before: int):
        m = Machine(image)
        base = find_section(image, SECTION_NAME)[0]
        at = layout(base)
        seen: list[tuple[int, int, int, int]] = []

        def parser(mm: Machine) -> None:
            ini, instance, store, names = (mm.arg(i) for i in range(4))
            seen.append((ini, instance, mm.read32(store), names))
            mm.write32(store, mm.read32(store) | FLAG_UPGRADES)
            mm.ret(0)

        m.stub(INI_PARSE_BIT_STRING_32, parser)
        field = m.alloc(4, bytes([before, 0xAA, 0xBB, 0xCC]))
        m.call(at["parse"], 0x1111, 0x2222, field, at["name_list"])
        assert seen == [(0x1111, 0x2222, before, at["name_list"])]
        assert bytes(m.uc.mem_read(field, 4)) == bytes([before | FLAG_UPGRADES, 0xAA, 0xBB, 0xCC])

    def test_the_name_list_is_the_flags_in_bit_order(self, image: bytes):
        m = Machine(image)
        at = layout(find_section(image, SECTION_NAME)[0])
        names = []
        for i in range(len(FLAGS) + 1):
            pointer = m.read32(at["name_list"] + 4 * i)
            if pointer == 0:
                break
            raw = bytes(m.uc.mem_read(pointer, 32))
            names.append(raw.split(b"\x00")[0].decode())
        assert tuple(names) == FLAGS


def _memset(m: Machine) -> None:
    destination, value, size = m.arg(0), m.arg(1), m.arg(2)
    m.uc.mem_write(destination, bytes([value & 0xFF]) * size)
    m.ret(0, destination)


def _constructed(source: bytes, ctor: int, stubs: dict[int, int]) -> bytes:
    """Run a ModuleData constructor on a `0xCC`-filled buffer; return the buffer."""
    m = Machine(source)
    m.stub(CRT_MEMSET, _memset)
    for va, pop in stubs.items():
        m.stub(va, lambda mm, pop=pop: mm.ret(pop, mm.reg("ecx")))
    buffer = m.alloc(0x200, b"\xcc" * 0x200)
    m.call(ctor, ecx=buffer)
    assert m.faults == []
    return bytes(m.uc.mem_read(buffer, 0x200))


#: Helpers the two constructors reach that have nothing to do with the bytes under test: list and
#: filter initialisers, and the `SpecialAbilityUpdate` base. `{va: bytes of arguments popped}`.
_RSU_STUBS = {0x00478CBE: 4, 0x0042CA04: 8}
_SUMMON_STUBS = {0x00851909: 0, 0x0076406F: 0, 0x00478CBE: 4, 0x00444D65: 4, 0x00763DAA: 0x1C}


@needs_game_dat
class TestTheConstructors:
    def test_replace_self_upgrade_clears_its_byte(self):
        stock = REAL_GAME_DAT.read_bytes()
        before = _constructed(stock, REPLACE_SELF_MODULE_DATA_CTOR, _RSU_STUBS)
        after = _constructed(_patched(stock), REPLACE_SELF_MODULE_DATA_CTOR, _RSU_STUBS)
        assert before[REPLACE_SELF_FREE_OFFSET] == 0xCC
        assert after[REPLACE_SELF_FREE_OFFSET] == 0
        assert before[:REPLACE_SELF_FREE_OFFSET] == after[:REPLACE_SELF_FREE_OFFSET]

    def test_summon_replacement_clears_its_byte(self):
        stock = REAL_GAME_DAT.read_bytes()
        before = _constructed(stock, SUMMON_REPLACEMENT_MODULE_DATA_CTOR, _SUMMON_STUBS)
        after = _constructed(_patched(stock), SUMMON_REPLACEMENT_MODULE_DATA_CTOR, _SUMMON_STUBS)
        offset = SUMMON_REPLACEMENT_FREE_OFFSET
        assert before[offset - 2 : offset + 2] == b"\x00\x00\xcc\xcc"
        assert after[offset - 2 : offset + 2] == bytes(4)
