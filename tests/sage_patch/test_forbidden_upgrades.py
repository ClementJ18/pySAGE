"""Tests for the forbidden-upgrades patch.

Two halves. The structural one is the usual: the struct grows at all three allocation sites, the
rebuilt table keeps the live rows verbatim and adds one row naming the engine's own mask parser,
each hook lands where it claims, and the round trip through `verify` / `detect` holds - plus the
refusals that keep this patch off an image `hero-mana` or `special-power-charges` already grew.

The other half **runs the cave** under Unicorn, with every engine routine it calls replaced by a
stub that answers from Python and records how it was called. That is where a wrong stack offset, a
swapped argument or a clobbered callee-saved register would show - all of them assemble, apply and
verify cleanly, and then refuse the wrong casts in a running game.
"""

from __future__ import annotations

import faulthandler
import struct

import pytest

from sage_patch.addresses import (
    FIELD_PARSE_STRIDE,
    GET_FINAL_OVERRIDE,
    INI_PARSE_UPGRADE_MASK,
    OBJECT_POSITION,
    OBJECT_UPGRADE_MASK,
    PARTITION_FILTER_DESTRUCTOR,
    PARTITION_FILTER_NOT_DESTROYED_VTABLE,
    PARTITION_FILTER_SLOT_2,
    PARTITION_GET_CLOSEST_OBJECT,
    SPECIAL_POWER_FIELD_TABLE,
    SPECIAL_POWER_FIELD_TABLE_REF_OPCODES,
    SPECIAL_POWER_FIELD_TABLE_REFS,
    SPECIAL_POWER_FORBIDDEN_OBJECT_RANGE,
    SPECIAL_POWER_FORBIDDEN_OBJECTS_CALL,
    SPECIAL_POWER_FORBIDDEN_OBJECTS_CALL_BYTES,
    SPECIAL_POWER_FORBIDDEN_OBJECTS_CHECK,
    SPECIAL_POWER_TEMPLATE_COPY_TAIL,
    SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES,
    SPECIAL_POWER_TEMPLATE_NEW_SITES,
    SPECIAL_POWER_TEMPLATE_SIZE,
    THE_PARTITION_MANAGER,
    UPGRADE_MASK_ANY,
    UPGRADE_MASK_TEST_ANY,
)
from sage_patch.patches.forbidden_upgrades import (
    ANCHORS,
    KEYWORD,
    MASK_OFFSET,
    MASK_SIZE,
    NEW_TEMPLATE_SIZE,
    OBJECT_GATE_CALL,
    OBJECT_GATE_CALL_BYTES,
    OBJECT_GATE_TARGET,
    SECTION_NAME,
    TEMPLATE_CTOR_TAIL,
    TEMPLATE_CTOR_TAIL_BYTES,
    TEMPLATE_CTOR_TAIL_RESUME,
    ForbiddenUpgradesPatch,
    build_table,
)
from sage_patch.patches.utils.field_tables import entries_before, read_field_table
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.test_terrain_resource_exp import _pe32

IMAGE_BASE = 0x400000

#: Where the synthetic image parks the field-name strings, past every site the patch touches.
STRINGS_VA = 0x00DB0000

#: The stock `SpecialPower` field table, as ``(keyword, SpecialPowerTemplate offset)``.
STOCK_FIELDS: tuple[tuple[str, int], ...] = (
    ("Flags", 0x18),
    ("ReloadTime", 0x20),
    ("RequiredSciences", 0x24),
    ("LightPointCost", 0x30),
    ("InitiateSound", 0x34),
    ("InitiateAtLocationSound", 0x38),
    ("UnitSpecificSoundToUseAsInitiateIntendToDoVoice", 0x3C),
    ("UnitSpecificSoundToUseAsEnterStateInitiateIntendToDoVoice", 0x40),
    ("EvaEventToPlayOnSuccess", 0x44),
    ("PublicTimer", 0x58),
    ("Enum", 0x1C),
    ("DetectionTime", 0x48),
    ("SharedSyncedTimer", 0x59),
    ("ViewObjectDuration", 0x4C),
    ("ViewObjectRange", 0x50),
    ("RadiusCursorRadius", 0x54),
    ("PalantirMovie", 0x5C),
    ("ObjectFilter", 0x60),
    ("PreventActivationConditions", 0x64),
    ("MaxCastRange", 0x74),
    ("ForbiddenObjectFilter", 0x78),
    ("ForbiddenObjectRange", 0x7C),
    ("UnitCost", 0x80),
    ("UnitCostDeathType", 0x84),
)

#: The engine bytes the patch replaces, as ``(va, original)``.
WINDOWS: tuple[tuple[int, bytes], ...] = (
    (TEMPLATE_CTOR_TAIL, TEMPLATE_CTOR_TAIL_BYTES),
    (SPECIAL_POWER_TEMPLATE_COPY_TAIL, SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES),
    (SPECIAL_POWER_FORBIDDEN_OBJECTS_CALL, SPECIAL_POWER_FORBIDDEN_OBJECTS_CALL_BYTES),
    (OBJECT_GATE_CALL, OBJECT_GATE_CALL_BYTES),
)

_PUSH_STOCK_SIZE = b"\x68" + struct.pack("<I", SPECIAL_POWER_TEMPLATE_SIZE)


def _string_vas() -> dict[str, int]:
    vas, cursor = {}, STRINGS_VA
    for name, _offset in STOCK_FIELDS:
        vas[name] = cursor
        cursor += len(name) + 1
    return vas


def _stock_entries() -> tuple[tuple[int, int, int, int], ...]:
    vas = _string_vas()
    return tuple((vas[name], 0x0042EC5E, 0, offset) for name, offset in STOCK_FIELDS)


def synthetic_image() -> bytearray:
    """A PE32 image carrying every site the patch asserts, with the real original bytes planted."""
    highest = max(
        max(va + len(w) for va, w in ANCHORS.items()),
        max(va + len(w) for va, w in WINDOWS),
        STRINGS_VA + sum(len(name) + 1 for name, _ in STOCK_FIELDS),
        SPECIAL_POWER_FIELD_TABLE + (len(STOCK_FIELDS) + 1) * FIELD_PARSE_STRIDE,
    )
    data = _pe32(highest)

    def at(va: int) -> int:
        return va - IMAGE_BASE

    for va, window in (*ANCHORS.items(), *WINDOWS):
        data[at(va) : at(va) + len(window)] = window
    for push_va, _call_va in SPECIAL_POWER_TEMPLATE_NEW_SITES:
        data[at(push_va) : at(push_va) + 5] = _PUSH_STOCK_SIZE
    for name, va in _string_vas().items():
        blob = name.encode("ascii") + b"\x00"
        data[at(va) : at(va) + len(blob)] = blob
    table = at(SPECIAL_POWER_FIELD_TABLE)
    for index, entry in enumerate(_stock_entries()):
        struct.pack_into("<IIII", data, table + index * FIELD_PARSE_STRIDE, *entry)
    for ref_va, opcode in zip(
        SPECIAL_POWER_FIELD_TABLE_REFS, SPECIAL_POWER_FIELD_TABLE_REF_OPCODES, strict=True
    ):
        data[at(ref_va)] = opcode
        struct.pack_into("<I", data, at(ref_va) + 1, SPECIAL_POWER_FIELD_TABLE)
    return data


@pytest.fixture
def image() -> bytearray:
    return synthetic_image()


@pytest.fixture
def patched(image: bytearray) -> bytearray:
    ForbiddenUpgradesPatch().apply(image)
    return image


def _read(data: bytes | bytearray, va: int, n: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + n])


def _rel32_target(data: bytes | bytearray, va: int, opcode: int) -> int:
    window = _read(data, va, 5)
    assert window[0] == opcode, f"0x{va:08x} holds {window.hex()}"
    return va + 5 + struct.unpack_from("<i", window, 1)[0]


def _labels(data: bytes | bytearray) -> dict[str, int]:
    """Where each routine landed, re-derived the way `verify` does."""
    located = find_section(data, SECTION_NAME)
    assert located is not None
    live = read_field_table(data, ForbiddenUpgradesPatch._resolve(data))
    preceding = entries_before(data, live, KEYWORD)
    assert preceding is not None
    asm = ForbiddenUpgradesPatch._assemble(located[0], preceding)
    return {name: asm.label_va(name) for name in asm._labels}


class TestLayout:
    def test_the_mask_lands_past_every_stock_field(self) -> None:
        assert MASK_OFFSET == SPECIAL_POWER_TEMPLATE_SIZE
        assert max(offset for _name, offset in STOCK_FIELDS) < MASK_OFFSET

    def test_the_struct_grows_by_exactly_one_upgrade_mask(self) -> None:
        assert MASK_SIZE == 0x90
        assert NEW_TEMPLATE_SIZE == 0x118

    def test_every_allocation_site_is_grown(self, patched: bytearray) -> None:
        for push_va, _call_va in SPECIAL_POWER_TEMPLATE_NEW_SITES:
            assert _read(patched, push_va, 5) == b"\x68" + struct.pack("<I", NEW_TEMPLATE_SIZE)


class TestTable:
    def test_both_references_are_repointed_into_the_cave(self, patched: bytearray) -> None:
        labels = _labels(patched)
        for ref_va, opcode in zip(
            SPECIAL_POWER_FIELD_TABLE_REFS, SPECIAL_POWER_FIELD_TABLE_REF_OPCODES, strict=True
        ):
            window = _read(patched, ref_va, 5)
            assert window[0] == opcode
            assert struct.unpack_from("<I", window, 1)[0] == labels["table"]

    def test_the_stock_table_is_left_where_it_was(self, image: bytearray) -> None:
        before = _read(image, SPECIAL_POWER_FIELD_TABLE, 25 * FIELD_PARSE_STRIDE)
        ForbiddenUpgradesPatch().apply(image)
        assert _read(image, SPECIAL_POWER_FIELD_TABLE, 25 * FIELD_PARSE_STRIDE) == before

    def test_the_rebuilt_table_keeps_the_live_rows_and_adds_one(self, patched: bytearray) -> None:
        live = read_field_table(patched, ForbiddenUpgradesPatch._resolve(patched))
        assert live[: len(STOCK_FIELDS)] == _stock_entries()
        name_va, parse_fn, user_data, offset = live[-1]
        assert len(live) == len(STOCK_FIELDS) + 1
        assert _read(patched, name_va, len(KEYWORD) + 1) == KEYWORD.encode("ascii") + b"\x00"
        assert (parse_fn, user_data, offset) == (INI_PARSE_UPGRADE_MASK, 0, MASK_OFFSET)

    def test_build_table_is_terminated(self) -> None:
        table = build_table(_stock_entries(), 0x1234)
        assert table[-FIELD_PARSE_STRIDE:] == bytes(FIELD_PARSE_STRIDE)
        assert len(table) == (len(STOCK_FIELDS) + 2) * FIELD_PARSE_STRIDE


class TestHooks:
    def test_the_constructor_tail_jumps_to_the_default_and_pads(self, patched: bytearray) -> None:
        labels = _labels(patched)
        assert _rel32_target(patched, TEMPLATE_CTOR_TAIL, 0xE9) == labels["ctor"]
        assert _read(patched, TEMPLATE_CTOR_TAIL + 5, 1) == b"\x90"

    def test_the_copy_tail_jumps_to_the_copy_and_pads(self, patched: bytearray) -> None:
        labels = _labels(patched)
        assert _rel32_target(patched, SPECIAL_POWER_TEMPLATE_COPY_TAIL, 0xE9) == labels["copy"]
        assert _read(patched, SPECIAL_POWER_TEMPLATE_COPY_TAIL + 5, 3) == b"\x90" * 3

    def test_both_gate_calls_stay_calls(self, patched: bytearray) -> None:
        """A `call` retargeted at a routine of the same shape, never a displaced `jmp`."""
        labels = _labels(patched)
        location = _rel32_target(patched, SPECIAL_POWER_FORBIDDEN_OBJECTS_CALL, 0xE8)
        assert location == labels["location_gate"]
        assert _rel32_target(patched, OBJECT_GATE_CALL, 0xE8) == labels["object_gate"]

    def test_the_stock_targets_are_the_calls_being_replaced(self) -> None:
        for call_va, window, target in (
            (
                SPECIAL_POWER_FORBIDDEN_OBJECTS_CALL,
                SPECIAL_POWER_FORBIDDEN_OBJECTS_CALL_BYTES,
                SPECIAL_POWER_FORBIDDEN_OBJECTS_CHECK,
            ),
            (OBJECT_GATE_CALL, OBJECT_GATE_CALL_BYTES, OBJECT_GATE_TARGET),
        ):
            assert window[0] == 0xE8
            assert call_va + 5 + struct.unpack_from("<i", window, 1)[0] == target

    def test_the_cave_vtable_shares_the_stock_outer_slots(self, patched: bytearray) -> None:
        labels = _labels(patched)
        slots = struct.unpack("<III", _read(patched, labels["vtable"], 12))
        assert slots == (PARTITION_FILTER_DESTRUCTOR, labels["allow"], PARTITION_FILTER_SLOT_2)


class TestRoundTrip:
    def test_apply_then_verify(self, patched: bytearray) -> None:
        assert ForbiddenUpgradesPatch().verify(patched) == []

    def test_detect_finds_it(self, patched: bytearray) -> None:
        assert ForbiddenUpgradesPatch.detect(patched) is not None

    def test_a_stock_image_carries_nothing(self, image: bytearray) -> None:
        assert ForbiddenUpgradesPatch.detect(image) is None
        assert ForbiddenUpgradesPatch().verify(image) != []

    def test_verify_catches_a_reverted_gate(self, patched: bytearray) -> None:
        off = va_to_offset(patched, OBJECT_GATE_CALL)
        assert off is not None
        patched[off : off + 5] = OBJECT_GATE_CALL_BYTES
        assert any("object gate" in problem for problem in ForbiddenUpgradesPatch().verify(patched))

    def test_applying_twice_raises(self, patched: bytearray) -> None:
        with pytest.raises(ValueError, match="already"):
            ForbiddenUpgradesPatch().apply(patched)

    def test_a_moved_anchor_is_refused(self, image: bytearray) -> None:
        off = va_to_offset(image, PARTITION_GET_CLOSEST_OBJECT)
        assert off is not None
        image[off] ^= 0xFF
        with pytest.raises(ValueError, match="not the build"):
            ForbiddenUpgradesPatch().apply(image)

    def test_a_struct_another_patch_grew_is_refused(self, image: bytearray) -> None:
        """What `hero-mana` and `special-power-charges` leave behind: a row at `+0x88`."""
        table = va_to_offset(image, SPECIAL_POWER_FIELD_TABLE)
        assert table is not None
        row = table + len(STOCK_FIELDS) * FIELD_PARSE_STRIDE
        struct.pack_into("<IIII", image, row, STRINGS_VA, 0x0042EC5E, 0, MASK_OFFSET)
        struct.pack_into("<IIII", image, row + FIELD_PARSE_STRIDE, 0, 0, 0, 0)
        with pytest.raises(ValueError, match="already been grown|already uses offset"):
            ForbiddenUpgradesPatch().apply(image)

    def test_a_grown_allocation_is_refused(self, image: bytearray) -> None:
        push_va = SPECIAL_POWER_TEMPLATE_NEW_SITES[0][0]
        off = va_to_offset(image, push_va)
        assert off is not None
        image[off : off + 5] = b"\x68" + struct.pack("<I", 0x94)
        with pytest.raises(ValueError, match="already been grown"):
            ForbiddenUpgradesPatch().apply(image)

    def test_registered_as_settled(self) -> None:
        """It lives outside `patches/experimental/`, so it must not carry the warning."""
        assert PATCHES["forbidden-upgrades"] is ForbiddenUpgradesPatch
        assert not ForbiddenUpgradesPatch.experimental

    def test_ini_surface_declares_the_upgrade_list(self) -> None:
        (field,) = ForbiddenUpgradesPatch().ini_surface().fields
        assert (field.block, field.name, field.type) == ("SpecialPower", KEYWORD, "Ref[]:upgrades")


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

_CAVE = 0x00ED3000
_HEAP = 0x20000000
_STACK = 0x30000000
_DONE = 0x40000000  # the return address pushed for each run; reaching it ends the run
_PAGE = 0x1000

_MANAGER = 0x11110000  # what `[THE_PARTITION_MANAGER]` holds
_ACTION_MANAGER = 0x22220000  # the predicate's `this`, which the gates must hand on in `ecx`
_TEMPLATE = _HEAP + 0x1000
_TARGET = _HEAP + 0x2000
_CASTER = _HEAP + 0x3000
_WHERE = _HEAP + 0x4000
_FRAME = _STACK + 0xC00  # the object predicate's `ebp`

_SAVED = {
    UC_X86_REG_EBX: 0xBBBBBBBB,
    UC_X86_REG_ESI: 0x51515151,
    UC_X86_REG_EDI: 0xD1D1D1D1,
}

_UPGRADE_A = 3
_UPGRADE_B = 700


def _mask(*bits: int) -> bytes:
    words = [0] * (MASK_SIZE // 4)
    for bit in bits:
        words[bit >> 5] |= 1 << (bit & 31)
    return struct.pack(f"<{len(words)}I", *words)


class _World:
    """One emulated call into the cave. Every engine routine it reaches is a ``ret`` of the right
    width, with a code hook in front that sets ``eax`` from Python and records the call."""

    def __init__(
        self,
        *,
        forbidden: tuple[int, ...] = (),
        forbidden_range: float = 0.0,
        target_upgrades: tuple[int, ...] = (),
        nearby: tuple[tuple[int, ...], ...] = (),
        stock_answer: int = 1,
    ) -> None:
        self.calls: list[tuple] = []
        self.nearby = nearby
        self.stock_answer = stock_answer
        self.uc = uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.labels = self._map()

        template = bytearray(NEW_TEMPLATE_SIZE)
        struct.pack_into("<f", template, SPECIAL_POWER_FORBIDDEN_OBJECT_RANGE, forbidden_range)
        template[MASK_OFFSET : MASK_OFFSET + MASK_SIZE] = _mask(*forbidden)
        uc.mem_write(_TEMPLATE, bytes(template))
        uc.mem_write(_TARGET + OBJECT_UPGRADE_MASK, _mask(*target_upgrades))
        uc.mem_write(_TARGET + OBJECT_POSITION, struct.pack("<fff", 10.0, 20.0, 0.0))
        uc.mem_write(THE_PARTITION_MANAGER, struct.pack("<I", _MANAGER))

    def _map(self) -> dict[str, int]:
        uc = self.uc
        asm = ForbiddenUpgradesPatch._assemble(_CAVE, _stock_entries())
        code = asm.finish()
        stubs = {
            GET_FINAL_OVERRIDE: (b"\xc3", self._final_override),
            UPGRADE_MASK_ANY: (b"\xc3", self._any),
            UPGRADE_MASK_TEST_ANY: (b"\xc2\x04\x00", self._test_any),
            SPECIAL_POWER_FORBIDDEN_OBJECTS_CHECK: (b"\xc2\x0c\x00", self._stock_scan),
            OBJECT_GATE_TARGET: (b"\xc2\x04\x00", self._stock_gate),
            PARTITION_GET_CLOSEST_OBJECT: (b"\xc2\x10\x00", self._closest),
        }
        pages = {_DONE, _HEAP, _HEAP + 0x1000, _HEAP + 0x2000, _HEAP + 0x3000, _HEAP + 0x4000}
        pages |= {_STACK, _STACK + _PAGE}
        pages |= {(_CAVE + off) & ~0xFFF for off in range(0, len(code) + _PAGE, _PAGE)}
        pages |= {va & ~0xFFF for va in (*stubs, THE_PARTITION_MANAGER, TEMPLATE_CTOR_TAIL_RESUME)}
        # `mem_map` raises and catches an SEH access violation inside Unicorn 2.1.4 on Windows;
        # every map still succeeds, but the fault handler would print a stack for each one.
        was_enabled = faulthandler.is_enabled()
        faulthandler.disable()
        try:
            for page in sorted(pages):
                uc.mem_map(page, _PAGE)
        finally:
            if was_enabled:
                faulthandler.enable()
        uc.mem_write(_CAVE, code)
        for va, (ret, handler) in stubs.items():
            uc.mem_write(va, ret)
            uc.hook_add(UC_HOOK_CODE, handler, begin=va, end=va)
        return {name: asm.label_va(name) for name in asm._labels}

    def _arg(self, index: int) -> int:
        esp = self.uc.reg_read(UC_X86_REG_ESP)
        return struct.unpack("<I", self.uc.mem_read(esp + 4 + 4 * index, 4))[0]

    def _u32(self, va: int) -> int:
        return struct.unpack("<I", self.uc.mem_read(va, 4))[0]

    def _bits(self, va: int) -> bytes:
        return bytes(self.uc.mem_read(va, MASK_SIZE))

    def _final_override(self, uc, *_: object) -> None:
        self.calls.append(("getFinalOverride", uc.reg_read(UC_X86_REG_ECX)))
        uc.reg_write(UC_X86_REG_EAX, uc.reg_read(UC_X86_REG_ECX))

    def _any(self, uc, *_: object) -> None:
        mask = self._bits(uc.reg_read(UC_X86_REG_ECX))
        uc.reg_write(UC_X86_REG_EAX, int(any(mask)))

    def _test_any(self, uc, *_: object) -> None:
        mine, other = self._bits(uc.reg_read(UC_X86_REG_ECX)), self._bits(self._arg(0))
        hit = any(a & b for a, b in zip(mine, other, strict=True))
        self.calls.append(("testForAny", uc.reg_read(UC_X86_REG_ECX) - OBJECT_UPGRADE_MASK))
        uc.reg_write(UC_X86_REG_EAX, int(hit))

    def _stock_scan(self, uc, *_: object) -> None:
        args = (self._arg(0), self._arg(1), self._arg(2))
        self.calls.append(("stockScan", uc.reg_read(UC_X86_REG_ECX), *args))
        uc.reg_write(UC_X86_REG_EAX, self.stock_answer)

    def _stock_gate(self, uc, *_: object) -> None:
        self.calls.append(("stockGate", uc.reg_read(UC_X86_REG_ECX), self._arg(0)))
        uc.reg_write(UC_X86_REG_EAX, self.stock_answer)

    def _closest(self, uc, *_: object) -> None:
        """Checks the filter chain the cave built, then answers as the partition would: the
        first nearby object the cave's own filter would accept."""
        where, range_bits, dist_type, head = (self._arg(i) for i in range(4))
        ours = self._u32(head + 4)
        mask = self._bits(self._u32(ours + 8))
        self.calls.append(
            (
                "getClosestObject",
                uc.reg_read(UC_X86_REG_ECX),
                where,
                struct.unpack("<f", struct.pack("<I", range_bits))[0],
                dist_type,
                self._u32(head),
                self._u32(ours),
                self._u32(ours + 4),
            )
        )
        found = 0
        for index, upgrades in enumerate(self.nearby):
            if any(a & b for a, b in zip(_mask(*upgrades), mask, strict=True)):
                found = _HEAP + 0x5000 + index
                break
        uc.reg_write(UC_X86_REG_EAX, found)

    def run(self, entry: str, args: tuple[int, ...], *, ebp: int = 0) -> int:
        """Call ``entry`` with ``args`` as a caller would, and return ``al``. Asserts the routine
        popped exactly its arguments and gave back every callee-saved register."""
        uc = self.uc
        esp0 = _STACK + 0x800
        uc.mem_write(esp0, struct.pack(f"<{1 + len(args)}I", _DONE, *args))
        uc.reg_write(UC_X86_REG_ESP, esp0)
        uc.reg_write(UC_X86_REG_ECX, _ACTION_MANAGER)
        uc.reg_write(UC_X86_REG_EBP, ebp)
        for register, value in _SAVED.items():
            uc.reg_write(register, value)
        uc.emu_start(self.labels[entry], _DONE)
        assert uc.reg_read(UC_X86_REG_ESP) == esp0 + 4 + 4 * len(args), "unbalanced stack"
        for register, value in _SAVED.items():
            assert uc.reg_read(register) == value, f"register {register} clobbered"
        assert uc.reg_read(UC_X86_REG_EBP) == ebp
        return uc.reg_read(UC_X86_REG_EAX) & 0xFF

    def location(self) -> int:
        """`canDoSpecialPowerAtLocation`'s call: ``(caster, where, template)``, 1 = allowed."""
        return self.run("location_gate", (_CASTER, _WHERE, _TEMPLATE))

    def at_object(self) -> int:
        """`canDoSpecialPowerAtObject`'s call: ``(caster)``, the rest in its frame, 1 = refused."""
        self.uc.mem_write(_FRAME + 0x0C, struct.pack("<I", _TARGET))
        self.uc.mem_write(_FRAME + 0x14, struct.pack("<I", _TEMPLATE))
        return self.run("object_gate", (_CASTER,), ebp=_FRAME)

    def named(self, name: str) -> list[tuple]:
        return [call for call in self.calls if call[0] == name]


class TestLocationGate:
    def test_the_stock_scan_runs_first_with_the_same_arguments_and_this(self) -> None:
        world = _World()
        world.location()
        assert world.calls[0] == ("stockScan", _ACTION_MANAGER, _CASTER, _WHERE, _TEMPLATE)

    def test_a_stock_refusal_stands_without_reading_the_template(self) -> None:
        world = _World(forbidden=(_UPGRADE_A,), forbidden_range=150.0, stock_answer=0)
        assert world.location() == 0
        assert world.named("getFinalOverride") == []

    def test_an_empty_list_is_stock_behaviour(self) -> None:
        world = _World(forbidden_range=150.0, nearby=((_UPGRADE_A,),))
        assert world.location() == 1
        assert world.named("getClosestObject") == []

    def test_no_range_means_no_area(self) -> None:
        world = _World(forbidden=(_UPGRADE_A,), nearby=((_UPGRADE_A,),))
        assert world.location() == 1
        assert world.named("getClosestObject") == []

    def test_a_carrier_in_range_refuses(self) -> None:
        world = _World(forbidden=(_UPGRADE_B,), forbidden_range=150.0, nearby=((1,), (_UPGRADE_B,)))
        assert world.location() == 0

    def test_nobody_carrying_allows(self) -> None:
        world = _World(forbidden=(_UPGRADE_A,), forbidden_range=150.0, nearby=((1,), (2,)))
        assert world.location() == 1

    def test_the_scan_is_the_stock_one_around_the_cast_point(self) -> None:
        world = _World(forbidden=(_UPGRADE_A,), forbidden_range=150.0)
        world.location()
        (call,) = world.named("getClosestObject")
        _name, this, where, radius, dist_type, head_vtable, our_vtable, our_next = call
        assert (this, where, radius, dist_type) == (_MANAGER, _WHERE, 150.0, 1)
        assert head_vtable == PARTITION_FILTER_NOT_DESTROYED_VTABLE
        assert (our_vtable, our_next) == (world.labels["vtable"], 0)

    def test_the_final_override_is_the_template_read(self) -> None:
        world = _World(forbidden=(_UPGRADE_A,), forbidden_range=150.0)
        world.location()
        assert world.named("getFinalOverride") == [("getFinalOverride", _TEMPLATE)]


class TestObjectGate:
    def test_the_stock_gate_runs_first_with_the_same_argument_and_this(self) -> None:
        world = _World()
        world.at_object()
        assert world.calls[0] == ("stockGate", _ACTION_MANAGER, _CASTER)

    def test_a_stock_refusal_stands(self) -> None:
        world = _World(forbidden=(_UPGRADE_A,), target_upgrades=(_UPGRADE_A,), stock_answer=1)
        assert world.at_object() == 1
        assert world.named("getFinalOverride") == []

    def test_a_carrying_target_is_refused_without_any_range(self) -> None:
        world = _World(forbidden=(_UPGRADE_A,), target_upgrades=(_UPGRADE_A,), stock_answer=0)
        assert world.at_object() == 1
        assert world.named("testForAny") == [("testForAny", _TARGET)]
        assert world.named("getClosestObject") == []

    def test_a_clean_target_with_no_range_is_allowed(self) -> None:
        world = _World(forbidden=(_UPGRADE_A,), target_upgrades=(2,), stock_answer=0)
        assert world.at_object() == 0

    def test_the_area_is_measured_around_the_target(self) -> None:
        world = _World(
            forbidden=(_UPGRADE_A,), forbidden_range=80.0, nearby=((_UPGRADE_A,),), stock_answer=0
        )
        assert world.at_object() == 1
        (call,) = world.named("getClosestObject")
        assert call[2:5] == (_TARGET + OBJECT_POSITION, 80.0, 1)

    def test_an_empty_list_is_stock_behaviour(self) -> None:
        world = _World(target_upgrades=(_UPGRADE_A,), forbidden_range=80.0, stock_answer=0)
        assert world.at_object() == 0
        assert world.named("testForAny") == []


class TestFilter:
    def test_allow_asks_the_candidates_object_upgrades(self) -> None:
        world = _World()
        filter_va = _HEAP + 0x4800
        mask_va = _HEAP + 0x4900
        world.uc.mem_write(filter_va, struct.pack("<III", world.labels["vtable"], 0, mask_va))
        world.uc.mem_write(mask_va, _mask(_UPGRADE_B))
        for upgrades, want in (((_UPGRADE_B,), 1), ((_UPGRADE_A,), 0)):
            world.uc.mem_write(_TARGET + OBJECT_UPGRADE_MASK, _mask(*upgrades))
            uc = world.uc
            esp0 = _STACK + 0x800
            uc.mem_write(esp0, struct.pack("<II", _DONE, _TARGET))
            uc.reg_write(UC_X86_REG_ESP, esp0)
            uc.reg_write(UC_X86_REG_ECX, filter_va)
            uc.emu_start(world.labels["allow"], _DONE)
            assert uc.reg_read(UC_X86_REG_EAX) & 0xFF == want
            assert uc.reg_read(UC_X86_REG_ESP) == esp0 + 8


class TestTemplateLifecycle:
    def test_the_constructor_empties_the_mask_and_nothing_past_it(self) -> None:
        world = _World()
        uc = world.uc
        uc.mem_write(_TEMPLATE, b"\xff" * (NEW_TEMPLATE_SIZE + 4))
        uc.reg_write(UC_X86_REG_ESI, _TEMPLATE)
        uc.reg_write(UC_X86_REG_EBX, 0)
        uc.emu_start(world.labels["ctor"], TEMPLATE_CTOR_TAIL_RESUME)
        written = bytes(uc.mem_read(_TEMPLATE, NEW_TEMPLATE_SIZE + 4))
        assert written[0x84:NEW_TEMPLATE_SIZE] == bytes(NEW_TEMPLATE_SIZE - 0x84)
        assert written[:0x84] == b"\xff" * 0x84
        assert written[NEW_TEMPLATE_SIZE:] == b"\xff" * 4

    def test_the_copy_carries_the_mask_and_keeps_the_epilogue(self) -> None:
        world = _World()
        uc = world.uc
        source, dest = _HEAP + 0x3000, _HEAP + 0x4000
        uc.mem_write(source + MASK_OFFSET, _mask(1, 64, _UPGRADE_B))
        uc.mem_write(dest, bytes(NEW_TEMPLATE_SIZE))
        esp0 = _STACK + 0x800
        # the three saves the epilogue pops, then the return address and the one argument
        uc.mem_write(esp0, struct.pack("<IIIII", 0x51515151, 0xEBEBEBEB, 0xBBBBBBBB, _DONE, 0))
        uc.reg_write(UC_X86_REG_ESP, esp0)
        uc.reg_write(UC_X86_REG_EBP, source)
        uc.reg_write(UC_X86_REG_EBX, dest)
        uc.emu_start(world.labels["copy"], _DONE)
        assert bytes(uc.mem_read(dest + MASK_OFFSET, MASK_SIZE)) == _mask(1, 64, _UPGRADE_B)
        assert uc.reg_read(UC_X86_REG_EAX) == dest
        assert (uc.reg_read(UC_X86_REG_ESI), uc.reg_read(UC_X86_REG_EBP)) == (
            0x51515151,
            0xEBEBEBEB,
        )
        assert uc.reg_read(UC_X86_REG_EBX) == 0xBBBBBBBB
        assert uc.reg_read(UC_X86_REG_ESP) == esp0 + 0x14
