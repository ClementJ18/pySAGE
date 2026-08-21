"""Tests for the asset-load-profile patch.

The edit is twelve bytes in one instruction slot, so "it applies cleanly" is nearly the whole
patch and nearly worthless as a test. What the correctness rests on is narrower and is what is
asserted here:

* the replacement really encodes `mov word [esi+0x123C], 0x0100` - a wrong immediate byte order
  writes the 1 into ``+0x123C`` and leaves the profiler off, and both spellings assemble, apply
  and verify;
* it writes **exactly** the two bytes the stock pair wrote, so the padding at ``+0x123E`` that
  the constructor never initialises is not quietly zeroed;
* the field offset the instruction names is the one the profiler's own gates read, which is the
  only thing tying this store to the asset profiler rather than to the dozen neighbouring fields
  initialised the same way; and
* the anchor check refuses a build where those gates say something else, in *both* directions -
  a moved gate and a renamed literal.
"""

from __future__ import annotations

import struct

import pytest

from sage_ini.engine import STOCK
from sage_patch.addresses import GLOBAL_DATA_ASSET_PROFILE
from sage_patch.patches.asset_load_profile import (
    ANCHORS,
    CTOR_STORE_PAIR,
    CTOR_STORE_PAIR_BYTES,
    PATCHED_STORE,
    PROFILE_NAME_PREFIX_VA,
    AssetLoadProfilePatch,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import va_to_offset
from tests.sage_patch.synthetic import _sparse_image

#: The neighbouring field the stock pair also zeroes, and the padding byte past the pair that the
#: constructor never writes at all. Both are read back to prove the store's width.
NEIGHBOUR_OFFSET = 0x123C
PADDING_OFFSET = 0x123E


def stock_image() -> bytearray:
    """A PE32 mapping the constructor's store pair and the four read-only anchors, each holding
    what the real build holds there."""
    planted: dict[int, bytes] = {CTOR_STORE_PAIR: CTOR_STORE_PAIR_BYTES}
    planted.update(ANCHORS)
    return _sparse_image(planted)


def _applied() -> bytearray:
    data = stock_image()
    AssetLoadProfilePatch().apply(data)
    return data


def _store(data: bytes | bytearray) -> bytes:
    off = va_to_offset(data, CTOR_STORE_PAIR)
    assert off is not None
    return bytes(data[off : off + len(PATCHED_STORE)])


class TestApply:
    def test_applies_and_verifies(self):
        assert AssetLoadProfilePatch().verify(_applied()) == []

    def test_absent_from_an_unpatched_image(self):
        problems = AssetLoadProfilePatch().verify(stock_image())
        assert len(problems) == 1
        assert "does not carry this patch" in problems[0]

    def test_detect(self):
        assert AssetLoadProfilePatch.detect(stock_image()) is None
        assert isinstance(AssetLoadProfilePatch.detect(_applied()), AssetLoadProfilePatch)

    def test_it_does_not_grow_the_image(self):
        """No cave, no section: the patch is a same-length overwrite."""
        assert len(_applied()) == len(stock_image())

    def test_only_the_store_pair_changes(self):
        stock, patched = stock_image(), _applied()
        off = va_to_offset(stock, CTOR_STORE_PAIR)
        assert off is not None
        differing = [i for i in range(len(stock)) if stock[i] != patched[i]]
        assert differing, "the patch changed nothing"
        assert all(off <= i < off + len(CTOR_STORE_PAIR_BYTES) for i in differing)

    def test_applying_twice_raises(self):
        data = _applied()
        with pytest.raises(ValueError, match="expected 889e3c"):
            AssetLoadProfilePatch().apply(data)


class TestTheStoreItWrites:
    """What the twelve bytes mean, read back out of them rather than trusted from the constant."""

    def test_it_is_a_16_bit_store_through_esi(self):
        store = _store(_applied())
        # 0x66 operand-size prefix, C7 /0 (mov r/m16, imm16), ModRM 0x86 = [esi + disp32]
        assert store[:3] == b"\x66\xc7\x86"

    def test_the_displacement_is_the_field_below_the_flag(self):
        """The store starts one byte *below* the flag, because it writes the pair."""
        store = _store(_applied())
        assert struct.unpack_from("<I", store, 3)[0] == NEIGHBOUR_OFFSET
        assert NEIGHBOUR_OFFSET + 1 == GLOBAL_DATA_ASSET_PROFILE

    def test_the_immediate_sets_the_flag_and_clears_its_neighbour(self):
        """The byte order is the whole patch: little-endian, so the low half of `0x0100` lands on
        the neighbour and the high half on the flag. Swapped, this applies and verifies and
        profiles nothing."""
        store = _store(_applied())
        immediate = struct.unpack_from("<H", store, 7)[0]
        assert immediate & 0xFF == 0, "the neighbouring field must stay zero, as stock"
        assert immediate >> 8 == 1, "the profiler flag must come up set"

    def test_the_tail_is_padding_not_a_second_instruction(self):
        assert _store(_applied())[9:] == b"\x90\x90\x90"

    def test_it_writes_no_more_bytes_than_the_pair_it_replaces(self):
        """A dword store would have encoded just as easily and would have reached ``+0x123E``,
        which nothing in the constructor initialises."""
        store = _store(_applied())
        base = struct.unpack_from("<I", store, 3)[0]
        assert base + 2 <= PADDING_OFFSET


class TestTheAnchors:
    """The store on its own says nothing about which field it writes. These are what say it."""

    def test_a_moved_gate_is_refused(self):
        """The gate that arms the profile reading some other offset means this is not the build
        whose `+0x123D` the patch is defaulting."""
        planted = {CTOR_STORE_PAIR: CTOR_STORE_PAIR_BYTES, **ANCHORS}
        gate_va = 0x0063160B
        planted[gate_va] = bytes.fromhex("38983e120000")  # +0x123E, one field along
        with pytest.raises(ValueError, match=f"anchor {gate_va:#010x}"):
            AssetLoadProfilePatch().apply(_sparse_image(planted))

    def test_a_different_name_literal_is_refused(self):
        planted = {CTOR_STORE_PAIR: CTOR_STORE_PAIR_BYTES, **ANCHORS}
        planted[PROFILE_NAME_PREFIX_VA] = b"otherload \x00"
        with pytest.raises(ValueError, match=f"anchor {PROFILE_NAME_PREFIX_VA:#010x}"):
            AssetLoadProfilePatch().apply(_sparse_image(planted))

    def test_an_unmapped_anchor_is_refused(self):
        data = _sparse_image({CTOR_STORE_PAIR: CTOR_STORE_PAIR_BYTES})
        with pytest.raises(ValueError, match="is not mapped"):
            AssetLoadProfilePatch().apply(data)

    def test_a_rewritten_store_pair_is_refused(self):
        planted = {CTOR_STORE_PAIR: bytes(len(CTOR_STORE_PAIR_BYTES)), **ANCHORS}
        with pytest.raises(ValueError, match="expected 889e3c"):
            AssetLoadProfilePatch().apply(_sparse_image(planted))


class TestRegistration:
    def test_it_is_registered_and_settled(self):
        assert PATCHES[AssetLoadProfilePatch.name] is AssetLoadProfilePatch
        assert not AssetLoadProfilePatch().experimental

    def test_it_declares_no_ini_surface(self):
        """It adds no keyword and no token: the switch it flips is not reachable from INI at all,
        which is the reason the patch exists."""
        assert AssetLoadProfilePatch().ini_surface() is STOCK


def test_the_patched_instruction_disassembles_as_intended():
    """The encoding, checked against a disassembler rather than against the constant that produced
    it. A hand-encoded ModRM that is off by one register applies and verifies just as happily."""
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    insns = list(md.disasm(PATCHED_STORE, CTOR_STORE_PAIR))
    assert [i.mnemonic for i in insns] == ["mov", "nop", "nop", "nop"]
    assert insns[0].op_str == f"word ptr [esi + {NEIGHBOUR_OFFSET:#x}], 0x100"
