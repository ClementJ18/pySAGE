"""Tests for `ai-ally-targets` and its Worldbuilder twin.

Three layers. The apply/verify/detect round-trip runs on sparse stand-ins carrying the real stock
bytes at every site. The factory case and the picker then *execute* under Unicorn, with the engine
calls they make stubbed in Python: the case must build each new behaviour for its own index and
nothing else; the unit picker must choose the fighting ally the button accepts, a hero first, then
the lowest health; the structure picker the first own building the button accepts, structures
before economy buildings; and neither may touch anything it should not.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.addresses import (
    AI_CURRENT_VICTIM,
    AI_KILLER_BEHAVIOR_CTOR,
    AI_KILLER_BEHAVIOR_SIZE,
    AI_KILLER_BEHAVIOR_VTABLE,
    AI_KILLER_BEHAVIOR_VTABLE_SLOTS,
    AI_KILLER_PICKER,
    COMMAND_BUTTON_IS_VALID_TO_USE_ON,
    GAME_LOGIC_FIND_OBJECT_BY_ID,
    KINDOF_HERO_BIT,
    KINDOF_HERO_BYTE,
    OBJECT_AI_UPDATE,
    OBJECT_BODY_MODULE,
    OBJECT_GET_CONTROLLING_PLAYER,
    OBJECT_ID,
    OBJECT_THING_TEMPLATE,
    OPERATOR_NEW,
    SKIRMISH_AI_PLAYER_RECORD,
    SPELLBOOK_AI_TYPE_FACTORY_EXIT,
    SPELLBOOK_AI_TYPE_FACTORY_RANGE_CHECK,
    SPELLBOOK_AI_TYPE_FACTORY_RANGE_CHECK_BYTES,
    SPELLBOOK_AI_TYPE_FACTORY_RETURN,
    SPELLBOOK_SET_TARGET_OBJECT,
    SPELLBOOK_SET_TARGET_OBJECT_BYTES,
    SPELLBOOK_TARGET_ID_OFFSET,
    THE_GAME_LOGIC,
    THE_SKIRMISH_AI_MANAGER,
)
from sage_patch.patches import ai_ally_targets as aao
from sage_patch.patches.ai_ally_targets import (
    ALLY_OBJECT_INDEX,
    ALLY_OBJECT_NAME,
    ALLY_STRUCTURE_INDEX,
    ALLY_STRUCTURE_NAME,
    ANCHORS,
    GAME,
    NAMES,
    SECTION_NAME,
    WORLDBUILDER,
    WORLDBUILDER_SECTION_NAME,
    AiAllyTargetsPatch,
    AiAllyTargetsWorldbuilderPatch,
    build_section,
    layout,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import _sparse_image

#: Where each stand-in parks the stock name strings: a page nothing else in it uses.
_STRINGS_VA = {GAME: 0x00BEF000, WORLDBUILDER: 0x01E6A000}

#: The killer vtable's slots as the stand-in holds them: arbitrary, except the picker slot, which
#: the patch checks.
_KILLER_SLOTS = tuple(
    AI_KILLER_PICKER if i == 7 else 0x00A00000 + i for i in range(AI_KILLER_BEHAVIOR_VTABLE_SLOTS)
)


def _stock_names(target: aao._Target) -> list[str]:
    middle = [f"AI_STAND_IN_{i}" for i in range(1, target.count - 1)]
    return ["AI_SPECIAL_POWER_BASIC_SELF_BUFF", *middle, target.last_name]


def stand_in(target: aao._Target) -> bytearray:
    """The pages a target's patch reads or writes, holding what the real binary holds there."""
    planted: dict[int, bytes] = {}
    strings_va = _STRINGS_VA[target]
    blob = bytearray()
    pointers = []
    for name in _stock_names(target):
        pointers.append(strings_va + len(blob))
        blob += name.encode("ascii") + b"\x00"
    planted[strings_va] = bytes(blob)
    planted[target.table_va] = struct.pack(f"<{len(pointers) + 1}I", *pointers, 0)
    planted[target.read_va] = target.read_bytes
    planted[target.bound_va] = target.bound_bytes
    if target is GAME:
        planted.update(ANCHORS)
        planted[SPELLBOOK_AI_TYPE_FACTORY_RANGE_CHECK] = SPELLBOOK_AI_TYPE_FACTORY_RANGE_CHECK_BYTES
        planted[AI_KILLER_BEHAVIOR_VTABLE] = struct.pack(
            f"<{AI_KILLER_BEHAVIOR_VTABLE_SLOTS}I", *_KILLER_SLOTS
        )
    return _sparse_image(planted)


def _u32(data: bytes | bytearray, va: int) -> int:
    return struct.unpack_from("<I", data, va_to_offset(data, va))[0]


def _cstr(data: bytes | bytearray, va: int) -> str:
    off = va_to_offset(data, va)
    return bytes(data[off : data.index(b"\x00", off)]).decode("ascii")


_PAIRS = [
    pytest.param(AiAllyTargetsPatch, GAME, SECTION_NAME, id="game"),
    pytest.param(AiAllyTargetsWorldbuilderPatch, WORLDBUILDER, WORLDBUILDER_SECTION_NAME, id="wb"),
]


@pytest.mark.parametrize(("cls", "target", "section"), _PAIRS)
class TestApply:
    def test_apply_then_verify_and_detect(self, cls, target, section):
        data = stand_in(target)
        cls().apply(data)
        assert cls().verify(data) == []
        assert isinstance(cls.detect(data), cls)

    def test_an_unpatched_image_is_not_detected(self, cls, target, section):
        assert cls.detect(stand_in(target)) is None
        assert cls().verify(stand_in(target))

    def test_the_parser_reads_the_new_table_two_names_further(self, cls, target, section):
        data = stand_in(target)
        cls().apply(data)
        section_va = find_section(data, section)[0]
        assert _u32(data, target.read_va + target.read_disp_at) == section_va
        bound = data[va_to_offset(data, target.bound_va) + target.bound_imm_at]
        assert bound == target.count + len(NAMES)

    def test_stock_names_keep_their_indices_and_the_new_ones_come_last(self, cls, target, section):
        data = stand_in(target)
        stock = [_u32(data, target.table_va + 4 * i) for i in range(target.count)]
        cls().apply(data)
        table = find_section(data, section)[0]
        relocated = [_u32(data, table + 4 * i) for i in range(target.count + len(NAMES) + 1)]
        assert relocated[: target.count] == stock
        added = [_cstr(data, p) for p in relocated[target.count : -1]]
        assert added == [ALLY_OBJECT_NAME, ALLY_STRUCTURE_NAME]
        assert relocated[-1] == 0

    def test_the_stock_table_is_left_alone(self, cls, target, section):
        """`ai-rebuild-gate` anchors a slot of the stock table, so it must still be there."""
        data = stand_in(target)
        before = bytes(data[va_to_offset(data, target.table_va) :][: 4 * target.count])
        cls().apply(data)
        assert bytes(data[va_to_offset(data, target.table_va) :][: 4 * target.count]) == before

    def test_a_different_table_is_refused(self, cls, target, section):
        data = stand_in(target)
        pointer = _u32(data, target.table_va + 4 * (target.count - 1))
        data[va_to_offset(data, pointer)] = ord("X")
        with pytest.raises(ValueError, match="not the expected"):
            cls().apply(data)

    def test_it_is_registered(self, cls, target, section):
        assert PATCHES[cls.name] is cls


class TestGameSide:
    def test_the_factory_branch_reaches_the_new_case(self):
        data = stand_in(GAME)
        AiAllyTargetsPatch().apply(data)
        at = layout(find_section(data, SECTION_NAME)[0])
        off = va_to_offset(data, SPELLBOOK_AI_TYPE_FACTORY_RANGE_CHECK)
        assert bytes(data[off : off + 2]) == b"\x0f\x87"  # still `ja`
        rel = struct.unpack_from("<i", data, off + 2)[0]
        assert SPELLBOOK_AI_TYPE_FACTORY_RANGE_CHECK + 6 + rel == at.factory_case

    @pytest.mark.parametrize("which", ["object", "structure"])
    def test_each_vtable_is_the_killers_with_its_picker_in_place(self, which):
        data = stand_in(GAME)
        AiAllyTargetsPatch().apply(data)
        at = layout(find_section(data, SECTION_NAME)[0])
        vtable = getattr(at, f"{which}_vtable")
        slots = [_u32(data, vtable + 4 * i) for i in range(AI_KILLER_BEHAVIOR_VTABLE_SLOTS)]
        want = list(_KILLER_SLOTS)
        want[7] = getattr(at, f"{which}_picker")
        assert slots == want

    def test_a_moved_picker_slot_is_refused(self):
        data = stand_in(GAME)
        off = va_to_offset(data, AI_KILLER_BEHAVIOR_VTABLE + 0x1C)
        data[off : off + 4] = struct.pack("<I", 0x00123456)
        with pytest.raises(ValueError, match="picker slot"):
            AiAllyTargetsPatch().apply(data)

    def test_the_new_names_are_on_the_ini_surface(self):
        members = AiAllyTargetsPatch().ini_surface().enum_members
        assert [(m.enum, m.name, m.value) for m in members] == [
            ("SpecialPowerAIType", ALLY_OBJECT_NAME, ALLY_OBJECT_INDEX),
            ("SpecialPowerAIType", ALLY_STRUCTURE_NAME, ALLY_STRUCTURE_INDEX),
        ]

    def test_the_new_indices_follow_the_stock_names(self):
        assert (ALLY_OBJECT_INDEX, ALLY_STRUCTURE_INDEX) == (GAME.count, GAME.count + 1) == (53, 54)


unicorn = pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EIP,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

SECTION = 0x00F00000
HEAP = 0x10000000
STACK = 0x20000000
STACK_TOP = STACK + 0xF000
RETURN = 0x30000000
PAGE = 0x1000

MANAGER = HEAP + 0x100
RECORD = HEAP + 0x200
UNITS = HEAP + 0x300
STRUCTURES = HEAP + 0x340
ECONOMY = HEAP + 0x380
IDS = HEAP + 0x400
STRUCTURE_IDS = HEAP + 0x480
ECONOMY_IDS = HEAP + 0x500
PLAYER = HEAP + 0x600
BEHAVIOUR = HEAP + 0x700
BUTTON = HEAP + 0x800
BODY_VTABLE = HEAP + 0x900
CASTER = HEAP + 0x1000
OBJECTS = HEAP + 0x2000
OBJECT_STRIDE = 0x800
NEW_BLOCK = HEAP + 0x8000

#: `fld dword [ecx+8]` / `ret`: the body's health ratio, read off the body itself.
_GET_HEALTH_RATIO = bytes.fromhex("d94108c3")

#: Callee-saved registers the picker must hand back as it found them.
_SAVED = {
    UC_X86_REG_ESI: 0x05050505,
    UC_X86_REG_EBX: 0x0B0B0B0B,
    UC_X86_REG_EDI: 0x0D0D0D0D,
    UC_X86_REG_EBP: 0x0E0E0E0E,
}


def _pages(size: int) -> int:
    return (size + PAGE - 1) & ~(PAGE - 1)


class Unit:
    def __init__(self, ident: int, *, hero=False, fighting=True, health=1.0, allowed=True):
        self.ident, self.hero, self.fighting = ident, hero, fighting
        self.health, self.allowed = health, allowed


class Engine:
    """Just enough engine for the factory case and the picker to run."""

    def __init__(self) -> None:
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.stock = tuple(0x00BEF000 + 0x40 * i for i in range(GAME.count))
        section = build_section(SECTION, self.stock, _KILLER_SLOTS)
        self.uc.mem_map(SECTION, _pages(len(section)))
        self.uc.mem_write(SECTION, section)
        self.at = layout(SECTION)

        self.uc.mem_map(HEAP, 0x10000)
        self.uc.mem_map(STACK, 0x10000)
        self.uc.mem_map(RETURN, PAGE)

        # Each stubbed engine routine is the `ret` it would end with; a hook on its first byte
        # supplies the answer before the `ret` runs.
        stubs = {
            OBJECT_GET_CONTROLLING_PLAYER: b"\xc3",
            SKIRMISH_AI_PLAYER_RECORD: b"\xc2\x04\x00",
            GAME_LOGIC_FIND_OBJECT_BY_ID: b"\xc2\x04\x00",
            AI_CURRENT_VICTIM: b"\xc3",
            COMMAND_BUTTON_IS_VALID_TO_USE_ON: b"\xc2\x10\x00",
            OPERATOR_NEW: b"\xc3",
            AI_KILLER_BEHAVIOR_CTOR: b"\x8b\xc1\xc3",  # mov eax, ecx / ret
            SPELLBOOK_SET_TARGET_OBJECT: SPELLBOOK_SET_TARGET_OBJECT_BYTES,
            SPELLBOOK_AI_TYPE_FACTORY_EXIT: b"\xf4",
        }
        mapped: set[int] = set()
        for va in [*stubs, THE_GAME_LOGIC, THE_SKIRMISH_AI_MANAGER]:  # pages, deduplicated
            if va & ~0xFFF not in mapped:
                self.uc.mem_map(va & ~0xFFF, PAGE)
                mapped.add(va & ~0xFFF)
        for va, code in stubs.items():
            self.uc.mem_write(va, code)

        self.uc.mem_write(THE_SKIRMISH_AI_MANAGER, struct.pack("<I", MANAGER))
        self.uc.mem_write(THE_GAME_LOGIC, struct.pack("<I", HEAP + 0x50))
        self.uc.mem_write(BODY_VTABLE + 0x14, struct.pack("<I", BODY_VTABLE + 0x40))
        self.uc.mem_write(BODY_VTABLE + 0x40, _GET_HEALTH_RATIO)
        self.uc.mem_write(BEHAVIOUR + 0x0C, struct.pack("<I", BUTTON))

        self.record: int | None = RECORD
        self.objects: dict[int, int] = {}
        self.units: dict[int, Unit] = {}
        self.valid_calls: list[tuple[int, int]] = []
        self.fpu_depth_at_calls: list[int] = []
        self.stop_at: set[int] = set()
        self.stopped: int | None = None
        self.uc.hook_add(UC_HOOK_CODE, self._hook)

    def _arg(self, n: int) -> int:
        esp = self.uc.reg_read(UC_X86_REG_ESP)
        return struct.unpack("<I", self.uc.mem_read(esp + 4 + 4 * n, 4))[0]

    def _hook(self, uc, address, size, user_data) -> None:
        if address in self.stop_at:
            self.stopped = address
            uc.emu_stop()
        elif address == OBJECT_GET_CONTROLLING_PLAYER:
            uc.reg_write(UC_X86_REG_EAX, PLAYER)
        elif address == SKIRMISH_AI_PLAYER_RECORD:
            assert uc.reg_read(UC_X86_REG_ECX) == MANAGER
            assert self._arg(0) == PLAYER
            uc.reg_write(UC_X86_REG_EAX, self.record or 0)
        elif address == GAME_LOGIC_FIND_OBJECT_BY_ID:
            uc.reg_write(UC_X86_REG_EAX, self.objects.get(self._arg(0), 0))
        elif address == AI_CURRENT_VICTIM:
            ai = uc.reg_read(UC_X86_REG_ECX)
            obj = next(o for o in self.objects.values() if self._ai_of(o) == ai)
            fighting = self.units[obj].fighting
            uc.reg_write(UC_X86_REG_EAX, CASTER if fighting else 0)
        elif address == COMMAND_BUTTON_IS_VALID_TO_USE_ON:
            assert uc.reg_read(UC_X86_REG_ECX) == BUTTON
            caster, target, pos, source = (self._arg(i) for i in range(4))
            assert (caster, pos, source) == (CASTER, 0, 0)
            self.valid_calls.append((caster, target))
            self.fpu_depth_at_calls.append(self._fpu_depth())
            uc.reg_write(UC_X86_REG_EAX, int(self.units[target].allowed))
        elif address == OPERATOR_NEW:
            assert self._arg(0) == AI_KILLER_BEHAVIOR_SIZE
            uc.reg_write(UC_X86_REG_EAX, NEW_BLOCK)

    def _fpu_depth(self) -> int:
        from unicorn.x86_const import UC_X86_REG_FPSW  # noqa: PLC0415

        top = (self.uc.reg_read(UC_X86_REG_FPSW) >> 11) & 7
        return (8 - top) % 8

    def _ai_of(self, obj: int) -> int:
        return struct.unpack("<I", self.uc.mem_read(obj + OBJECT_AI_UPDATE, 4))[0]

    def place(self, units: list[Unit], ids_extra: tuple[int, ...] = ()) -> None:
        """Plant the units as objects and list their ids, in order, as the player's unit list."""
        for n, unit in enumerate(units):
            obj = OBJECTS + n * OBJECT_STRIDE
            template, ai, body = obj + 0x500, obj + 0x600, obj + 0x700
            self.uc.mem_write(obj, b"\x00" * OBJECT_STRIDE)
            self.uc.mem_write(obj + OBJECT_THING_TEMPLATE, struct.pack("<I", template))
            self.uc.mem_write(obj + OBJECT_ID, struct.pack("<I", unit.ident))
            self.uc.mem_write(obj + OBJECT_AI_UPDATE, struct.pack("<I", ai))
            self.uc.mem_write(obj + OBJECT_BODY_MODULE, struct.pack("<I", body))
            hero = KINDOF_HERO_BIT if unit.hero else 0
            self.uc.mem_write(template + KINDOF_HERO_BYTE, bytes([hero]))
            self.uc.mem_write(body, struct.pack("<I", BODY_VTABLE))
            self.uc.mem_write(body + 8, struct.pack("<f", unit.health))
            self.objects[unit.ident] = obj
            self.units[obj] = unit
        ids = [u.ident for u in units] + list(ids_extra)
        self.uc.mem_write(IDS, struct.pack(f"<{len(ids)}I", *ids))
        self.uc.mem_write(RECORD, struct.pack("<I", UNITS))
        self.uc.mem_write(UNITS + 4, struct.pack("<II", IDS, IDS + 4 * len(ids)))

    def place_buildings(self, structures: list[Unit], economy: list[Unit]) -> None:
        """Plant buildings as objects, listed in the record's structure and economy lists."""
        self.place([*structures, *economy])
        self.uc.mem_write(RECORD + 8, struct.pack("<II", STRUCTURES, ECONOMY))
        lists = ((STRUCTURES, STRUCTURE_IDS, structures), (ECONOMY, ECONOMY_IDS, economy))
        for base, ids_va, group in lists:
            ids = [b.ident for b in group]
            if ids:
                self.uc.mem_write(ids_va, struct.pack(f"<{len(ids)}I", *ids))
            self.uc.mem_write(base + 4, struct.pack("<II", ids_va, ids_va + 4 * len(ids)))

    def pick(self, picker: str = "object") -> tuple[bool, int]:
        """Run a picker on `CASTER`; return its answer and the target id it left behind."""
        self.uc.mem_write(BEHAVIOUR + SPELLBOOK_TARGET_ID_OFFSET, struct.pack("<I", 0xDEADBEEF))
        esp = STACK_TOP - 8
        self.uc.mem_write(esp, struct.pack("<II", RETURN, CASTER))
        self.uc.reg_write(UC_X86_REG_ESP, esp)
        self.uc.reg_write(UC_X86_REG_ECX, BEHAVIOUR)
        for reg, value in _SAVED.items():
            self.uc.reg_write(reg, value)
        self.uc.emu_start(getattr(self.at, f"{picker}_picker"), RETURN, count=100_000)
        assert self.uc.reg_read(UC_X86_REG_EIP) == RETURN
        assert self.uc.reg_read(UC_X86_REG_ESP) == esp + 8, "ret 4 left the stack unbalanced"
        for reg, value in _SAVED.items():
            assert self.uc.reg_read(reg) == value
        assert self._fpu_depth() == 0, "the picker left something on the x87 stack"
        target = struct.unpack("<I", self.uc.mem_read(BEHAVIOUR + SPELLBOOK_TARGET_ID_OFFSET, 4))[0]
        return bool(self.uc.reg_read(UC_X86_REG_EAX) & 0xFF), target

    def factory(self, index: int) -> tuple[int, int]:
        """Enter the factory case with `index` in `eax`; return where it left and `eax`."""
        self.uc.mem_write(SPELLBOOK_AI_TYPE_FACTORY_RETURN, b"\xf4")
        self.uc.reg_write(UC_X86_REG_ESP, STACK_TOP)
        self.uc.reg_write(UC_X86_REG_EAX, index & 0xFFFFFFFF)
        exits = {SPELLBOOK_AI_TYPE_FACTORY_EXIT, SPELLBOOK_AI_TYPE_FACTORY_RETURN}
        self.uc.emu_start(self.at.factory_case, 0, count=1000)
        eip = self.uc.reg_read(UC_X86_REG_EIP)
        assert eip - 1 in exits or eip in exits
        stopped = eip if eip in exits else eip - 1
        assert self.uc.reg_read(UC_X86_REG_ESP) == STACK_TOP
        return stopped, self.uc.reg_read(UC_X86_REG_EAX)


@pytest.fixture
def engine() -> Engine:
    return Engine()


class TestFactoryCase:
    @pytest.mark.parametrize(
        ("index", "which"), [(ALLY_OBJECT_INDEX, "object"), (ALLY_STRUCTURE_INDEX, "structure")]
    )
    def test_each_new_index_builds_its_behaviour(self, engine, index, which):
        left, eax = engine.factory(index)
        assert left == SPELLBOOK_AI_TYPE_FACTORY_RETURN
        assert eax == NEW_BLOCK
        vtable = struct.unpack("<I", engine.uc.mem_read(NEW_BLOCK, 4))[0]
        assert vtable == getattr(engine.at, f"{which}_vtable")

    @pytest.mark.parametrize("index", [ALLY_STRUCTURE_INDEX + 1, -1, 0x7FFFFFFF])
    def test_anything_else_out_of_range_gets_no_behaviour(self, engine, index):
        left, _ = engine.factory(index)
        assert left == SPELLBOOK_AI_TYPE_FACTORY_EXIT


class TestPicker:
    def test_a_hero_beats_a_more_hurt_unit(self, engine):
        engine.place([Unit(1, health=0.2), Unit(2, hero=True, health=0.9)])
        assert engine.pick() == (True, 2)

    def test_among_heroes_the_most_hurt_wins(self, engine):
        engine.place(
            [Unit(1, hero=True, health=0.7), Unit(2, hero=True, health=0.3), Unit(3, hero=True)]
        )
        assert engine.pick() == (True, 2)

    def test_among_units_the_most_hurt_wins(self, engine):
        engine.place([Unit(1, health=0.8), Unit(2, health=0.4), Unit(3, health=0.6)])
        assert engine.pick() == (True, 2)

    def test_an_idle_hero_is_passed_over(self, engine):
        engine.place([Unit(1, hero=True, fighting=False), Unit(2)])
        assert engine.pick() == (True, 2)

    def test_a_hero_the_button_refuses_is_passed_over(self, engine):
        """The power's ObjectFilter speaks through `isValidToUseOn`."""
        engine.place([Unit(1, hero=True, allowed=False), Unit(2, health=0.9)])
        assert engine.pick() == (True, 2)

    def test_nobody_fighting_means_no_cast_and_no_target(self, engine):
        engine.place([Unit(1, hero=True, fighting=False), Unit(2, fighting=False)])
        assert engine.pick() == (False, 0)
        assert engine.valid_calls == []

    def test_an_id_with_no_object_is_skipped(self, engine):
        engine.place([Unit(1)], ids_extra=(99,))
        assert engine.pick() == (True, 1)

    def test_the_caster_is_never_its_own_target(self, engine):
        engine.place([Unit(1, hero=True)])
        engine.objects[50] = CASTER
        engine.uc.mem_write(IDS, struct.pack("<II", 50, 1))
        engine.uc.mem_write(UNITS + 4, struct.pack("<II", IDS, IDS + 8))
        assert engine.pick() == (True, 1)

    def test_a_player_the_manager_does_not_run_gets_nothing(self, engine):
        engine.place([Unit(1, hero=True)])
        engine.record = None
        assert engine.pick() == (False, 0)

    def test_an_empty_list_gets_nothing(self, engine):
        engine.place([])
        assert engine.pick() == (False, 0)

    def test_the_x87_stack_is_empty_at_every_validity_call(self, engine):
        engine.place([Unit(1, health=0.5), Unit(2, hero=True, health=0.9), Unit(3, hero=True)])
        engine.pick()
        assert engine.fpu_depth_at_calls and set(engine.fpu_depth_at_calls) == {0}

    def test_a_worse_rank_is_never_validated(self, engine):
        """Once a hero is picked, units cost one KindOf test each, not an `isValidToUseOn`."""
        engine.place([Unit(1, hero=True), Unit(2), Unit(3)])
        engine.pick()
        assert [target for _, target in engine.valid_calls] == [engine.objects[1]]


class TestStructurePicker:
    def test_the_first_accepted_structure_wins(self, engine):
        engine.place_buildings([Unit(1, allowed=False), Unit(2), Unit(3)], [Unit(4)])
        assert engine.pick("structure") == (True, 2)

    def test_economy_buildings_come_after_the_structures(self, engine):
        engine.place_buildings([Unit(1, allowed=False)], [Unit(2), Unit(3)])
        assert engine.pick("structure") == (True, 2)

    def test_no_fight_is_needed(self, engine):
        """The point of the type: a building, or a caster with no weapon, never fights."""
        engine.place_buildings([Unit(1, fighting=False)], [])
        assert engine.pick("structure") == (True, 1)

    def test_nothing_accepted_means_no_cast_and_no_target(self, engine):
        engine.place_buildings([Unit(1, allowed=False)], [Unit(2, allowed=False)])
        assert engine.pick("structure") == (False, 0)
        assert [t for _, t in engine.valid_calls] == [engine.objects[1], engine.objects[2]]

    def test_an_id_with_no_object_is_skipped(self, engine):
        engine.place_buildings([], [Unit(1)])
        engine.uc.mem_write(STRUCTURE_IDS, struct.pack("<I", 99))
        engine.uc.mem_write(STRUCTURES + 4, struct.pack("<II", STRUCTURE_IDS, STRUCTURE_IDS + 4))
        assert engine.pick("structure") == (True, 1)

    def test_the_caster_is_never_its_own_target(self, engine):
        engine.place_buildings([Unit(1)], [])
        engine.objects[50] = CASTER
        engine.uc.mem_write(STRUCTURE_IDS, struct.pack("<II", 50, 1))
        engine.uc.mem_write(STRUCTURES + 4, struct.pack("<II", STRUCTURE_IDS, STRUCTURE_IDS + 8))
        assert engine.pick("structure") == (True, 1)

    def test_a_missing_list_is_skipped(self, engine):
        engine.place_buildings([], [Unit(1)])
        engine.uc.mem_write(RECORD + 8, struct.pack("<I", 0))
        assert engine.pick("structure") == (True, 1)

    def test_a_player_the_manager_does_not_run_gets_nothing(self, engine):
        engine.place_buildings([Unit(1)], [])
        engine.record = None
        assert engine.pick("structure") == (False, 0)

    def test_the_unit_list_is_not_walked(self, engine):
        """Units are `ALLY_OBJECT`'s; the record's `+0` list is not this type's business."""
        engine.place_buildings([], [])
        engine.place([Unit(7)])  # listed only as a unit
        assert engine.pick("structure") == (False, 0)
