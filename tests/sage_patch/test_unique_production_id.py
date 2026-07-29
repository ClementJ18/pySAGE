"""Tests for the unique-production-id patch.

The replacement is ten hand-encoded bytes written over a live engine function, so the important
tests disassemble them back and assert they say what they were meant to say. A wrong byte does
not raise - it returns a nonsense id, or crashes the game - so encoding errors have to be caught
statically. The rest hold the two invariants the fix rests on: the ids it mints are distinct,
and 0 is never among them.
"""

from __future__ import annotations

import itertools
import struct

import pytest

from sage_patch import (
    AiReviveGatePatch,
    CahFactionsPatch,
    CommandSetLimitPatch,
    UniqueProductionIdPatch,
)
from sage_patch.addresses import (
    PRODUCTION_UPDATE_INTERFACE_VTABLE,
    REQUEST_UNIQUE_UNIT_ID,
    REQUEST_UNIQUE_UNIT_ID_BODY,
    REQUEST_UNIQUE_UNIT_ID_VTABLE_SLOT,
)
from sage_patch.patches.unique_production_id import COUNTER_SIZE, SECTION_NAME, build_body
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.test_ai_revive_gate import plant_sites as plant_ai_revive_gate_sites
from tests.sage_patch.test_patching import (
    _cah_game_dat,
    _plant_commandset_sites,
    _section_rvas,
    _tiny_pe,
)

COUNTER = 0x00F00000
IMAGE_BASE = 0x400000
VTABLE_SLOT = PRODUCTION_UPDATE_INTERFACE_VTABLE + REQUEST_UNIQUE_UNIT_ID_VTABLE_SLOT


def synthetic_image() -> bytearray:
    """A PE32 image big enough to map the rewritten function and the vtable slot that names it,
    with the real original bytes planted, so the whole apply + verify path runs without the
    copyrighted `game.dat`."""
    highest = max(REQUEST_UNIQUE_UNIT_ID + len(REQUEST_UNIQUE_UNIT_ID_BODY), VTABLE_SLOT + 4)
    size = highest - IMAGE_BASE + 0x100
    data = bytearray(((size + 0x400) // 0x200 + 1) * 0x200)

    data[0:2] = b"MZ"
    e = 0x80
    struct.pack_into("<I", data, 0x3C, e)
    data[e : e + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, e + 4, 0x14C)  # Machine (i386)
    struct.pack_into("<H", data, e + 6, 1)  # NumberOfSections
    struct.pack_into("<H", data, e + 20, 0xE0)  # SizeOfOptionalHeader
    opt = e + 24
    struct.pack_into("<H", data, opt, 0x10B)  # PE32 magic
    struct.pack_into("<I", data, opt + 28, IMAGE_BASE)
    struct.pack_into("<I", data, opt + 32, 0x1000)  # SectionAlignment
    struct.pack_into("<I", data, opt + 36, 0x200)  # FileAlignment
    struct.pack_into("<I", data, opt + 56, 0x2000000)  # SizeOfImage
    struct.pack_into("<I", data, opt + 60, 0x400)  # SizeOfHeaders, room for more headers
    header = bytearray(40)
    header[0:8] = b".text\x00\x00\x00"
    mapped = len(data) - 0x1000
    struct.pack_into("<IIII", header, 8, mapped, 0x1000, mapped, 0x1000)
    data[opt + 0xE0 : opt + 0xE0 + 40] = header

    plant_sites(data)
    return data


def plant_sites(data: bytearray) -> None:
    """The clean bytes the patch asserts before writing. Separate so a composition test can host
    this patch and the others in one image."""
    at = REQUEST_UNIQUE_UNIT_ID - IMAGE_BASE
    data[at : at + len(REQUEST_UNIQUE_UNIT_ID_BODY)] = REQUEST_UNIQUE_UNIT_ID_BODY
    struct.pack_into("<I", data, VTABLE_SLOT - IMAGE_BASE, REQUEST_UNIQUE_UNIT_ID)


def disassemble(counter: int = COUNTER):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(build_body(counter), REQUEST_UNIQUE_UNIT_ID))


class TestTheMint:
    def test_it_is_exactly_as_long_as_the_body_it_replaces(self):
        """The whole point of this encoding: ten bytes for ten, so there is no hook, no cave and
        no displaced instruction to relocate."""
        assert len(build_body(COUNTER)) == len(REQUEST_UNIQUE_UNIT_ID_BODY) == 10

    def test_it_disassembles_cleanly_to_its_end(self):
        """Capstone stopping early means an invalid encoding, which would be a crash in-game."""
        insns = disassemble()
        assert sum(i.size for i in insns) == len(build_body(COUNTER))

    def test_it_reads_the_counter_increments_it_and_returns_the_new_value(self):
        ops = [(i.mnemonic, i.op_str) for i in disassemble()]
        assert ops == [
            ("mov", f"eax, {COUNTER:#x}"),
            ("inc", "dword ptr [eax]"),
            ("mov", "eax, dword ptr [eax]"),
            ("ret", ""),
        ]

    def test_it_increments_before_it_reads(self):
        """Post-increment is what keeps 0 unmintable. A revive entry that has never been used
        holds 0 in the field the id is matched against, so an id of 0 would collide with every
        idle hero the player has."""
        insns = disassemble()
        inc = next(i for i in insns if i.mnemonic == "inc")
        read = [i for i in insns if i.mnemonic == "mov"][-1]
        assert inc.address < read.address

    def test_it_touches_no_register_the_caller_keeps(self):
        """`__thiscall` with no arguments: the caller may rely on ecx and on the callee-saved
        registers surviving, and the stock body clobbered only eax and edx."""
        clobbered = {i.reg_name(r) for i in disassemble() for r in i.regs_access()[1]}
        assert clobbered <= {"eax", "eflags", "esp"}  # esp: the `ret` pop

    def test_it_returns_through_a_plain_ret(self):
        """The stock body takes no stack arguments, so a `ret imm16` would unbalance every
        caller - and the two `doCommandButton` cases call it mid-way through pushing seven
        arguments for `queueCreateUnit`."""
        last = disassemble()[-1]
        assert (last.mnemonic, last.op_str) == ("ret", "")

    def test_it_relocates_with_its_section(self):
        a, b = build_body(COUNTER), build_body(COUNTER + 0x1000)
        assert a != b, "the counter's address must be recomputed for where the section lands"
        assert len(a) == len(b)


class TestApply:
    def test_apply_then_verify(self):
        data = synthetic_image()
        UniqueProductionIdPatch().apply(data)
        assert UniqueProductionIdPatch().verify(data) == []

    def test_the_body_points_at_the_appended_section(self):
        data = synthetic_image()
        UniqueProductionIdPatch().apply(data)
        counter_va, _off, _vsize = find_section(data, SECTION_NAME)
        off = va_to_offset(data, REQUEST_UNIQUE_UNIT_ID)
        assert struct.unpack_from("<I", data, off + 1)[0] == counter_va

    def test_the_counter_starts_at_zero(self):
        """So the first id minted is 1 - the same first id the stock per-building counter gave,
        which keeps the change invisible to anything that merely stores an id."""
        data = synthetic_image()
        UniqueProductionIdPatch().apply(data)
        _va, off, _vsize = find_section(data, SECTION_NAME)
        assert bytes(data[off : off + COUNTER_SIZE]) == bytes(COUNTER_SIZE)

    def test_the_section_is_writable_data_and_not_executable(self):
        data = synthetic_image()
        UniqueProductionIdPatch().apply(data)
        e = struct.unpack_from("<I", data, 0x3C)[0]
        nsec = struct.unpack_from("<H", data, e + 6)[0]
        sectab = e + 24 + struct.unpack_from("<H", data, e + 20)[0]
        for i in range(nsec):
            hdr = sectab + i * 40
            if bytes(data[hdr : hdr + 8]).rstrip(b"\x00").decode() != SECTION_NAME:
                continue
            chars = struct.unpack_from("<I", data, hdr + 36)[0]
            assert chars & 0x80000000, "the counter is written every time a production is queued"
            assert chars & 0x40000000, "and read back in the same breath"
            assert not chars & 0x20000000, "nothing in it is ever executed"
            return
        pytest.fail(f"{SECTION_NAME} is absent")

    def test_it_writes_nothing_outside_the_ten_bytes(self):
        before = synthetic_image()
        after = bytearray(before)
        UniqueProductionIdPatch().apply(after)
        edited = range(
            REQUEST_UNIQUE_UNIT_ID - IMAGE_BASE,
            REQUEST_UNIQUE_UNIT_ID - IMAGE_BASE + len(REQUEST_UNIQUE_UNIT_ID_BODY),
        )
        headers = range(0, 0x400)  # the section header append_section adds
        differing = {i for i in range(len(before)) if before[i] != after[i]}
        assert not differing - set(edited) - set(headers)

    def test_the_section_name_survives_the_eight_byte_pe_field(self):
        assert len(SECTION_NAME) <= 8, "a longer name is silently truncated in the header"
        data = synthetic_image()
        UniqueProductionIdPatch().apply(data)
        assert find_section(data, SECTION_NAME) is not None

    def test_refuses_to_apply_twice(self):
        data = synthetic_image()
        UniqueProductionIdPatch().apply(data)
        with pytest.raises(ValueError, match="expected"):
            UniqueProductionIdPatch().apply(data)

    def test_refuses_a_build_whose_vtable_names_another_function(self):
        """A rewrite of ten bytes production does not dispatch to installs perfectly and never
        runs, which is indistinguishable from a working patch."""
        data = synthetic_image()
        struct.pack_into("<I", data, VTABLE_SLOT - IMAGE_BASE, REQUEST_UNIQUE_UNIT_ID + 0x20)
        with pytest.raises(ValueError, match="dispatches to"):
            UniqueProductionIdPatch().apply(data)

    def test_refuses_a_build_whose_body_is_not_the_stock_one(self):
        data = synthetic_image()
        data[REQUEST_UNIQUE_UNIT_ID - IMAGE_BASE] ^= 0xFF
        with pytest.raises(ValueError, match="expected"):
            UniqueProductionIdPatch().apply(data)

    def test_refuses_an_unmapped_build(self):
        with pytest.raises(ValueError, match="not mapped"):
            UniqueProductionIdPatch().apply(_tiny_pe())


class TestVerify:
    def test_an_unpatched_image_does_not_verify(self):
        problems = UniqueProductionIdPatch().verify(synthetic_image())
        assert problems == [f"{SECTION_NAME} section is absent"]

    def test_a_body_pointing_elsewhere_does_not_verify(self):
        data = synthetic_image()
        UniqueProductionIdPatch().apply(data)
        off = va_to_offset(data, REQUEST_UNIQUE_UNIT_ID)
        struct.pack_into("<I", data, off + 1, 0xDEADBEEF)
        assert any("points at another address" in p for p in UniqueProductionIdPatch().verify(data))

    def test_a_dirty_counter_does_not_verify(self):
        data = synthetic_image()
        UniqueProductionIdPatch().apply(data)
        _va, off, _vsize = find_section(data, SECTION_NAME)
        data[off] = 7
        assert any("not zero-initialised" in p for p in UniqueProductionIdPatch().verify(data))


class TestTheIdSequenceItMints:
    """The counter is four bytes of state and three instructions, so its behaviour can be stated
    exactly: these hold the two properties the revive manager depends on."""

    @staticmethod
    def mint(counter: list[int]) -> int:
        counter[0] += 1
        return counter[0]

    def test_ids_are_distinct_across_producers(self):
        """The defect in one line: with a per-building counter, two buildings' first productions
        are both id 1, and the second one to reach `startRevive` is refused."""
        shared = [0]
        ids = [self.mint(shared) for _ in range(100)]
        assert len(set(ids)) == len(ids)

    def test_the_first_id_matches_the_stock_first_id(self):
        assert self.mint([0]) == 1

    def test_zero_is_never_minted(self):
        shared = [0]
        assert 0 not in {self.mint(shared) for _ in range(100)}


def _all_four():
    return (
        CommandSetLimitPatch(count=64),
        CahFactionsPatch(sides=["Rohan"]),
        AiReviveGatePatch(),
        UniqueProductionIdPatch(),
    )


def _image_for_all_four() -> bytearray:
    data = _cah_game_dat()
    _plant_commandset_sites(data)
    plant_ai_revive_gate_sites(data)
    plant_sites(data)
    return data


class TestComposesWithTheOtherPatches:
    def test_it_shares_no_byte_with_the_other_patches(self):
        """`requestUniqueUnitID` is a leaf in `ProductionUpdate`; the other bundled patches edit
        `canMakeUnit`, the `CommandSet` parse table and the CAH faction enum."""
        data = _image_for_all_four()
        edited = range(
            REQUEST_UNIQUE_UNIT_ID - IMAGE_BASE,
            REQUEST_UNIQUE_UNIT_ID - IMAGE_BASE + len(REQUEST_UNIQUE_UNIT_ID_BODY),
        )
        before = bytearray(data)
        for patch in _all_four()[:-1]:
            patch.apply(data)
        assert all(before[i] == data[i] for i in edited)

    @pytest.mark.parametrize("order", list(itertools.permutations(range(4))))
    def test_any_order_applies_and_verifies(self, order):
        data = _image_for_all_four()
        patches = _all_four()
        for i in order:
            patches[i].apply(data)
        for patch in _all_four():
            assert patch.verify(data) == [], f"{patch} failed in order {order}"

    @pytest.mark.parametrize("order", list(itertools.permutations(range(4))))
    def test_any_order_keeps_the_section_table_rva_sorted(self, order):
        data = _image_for_all_four()
        patches = _all_four()
        for i in order:
            patches[i].apply(data)
        rvas = _section_rvas(data)
        assert rvas == sorted(rvas)
