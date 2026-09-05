"""Tests for the horde member-speed patch.

The patch is one five-byte swap, so what can go wrong is about *which* five bytes and what the
cave hands back. Four claims carry the whole thing and each is asserted from anchored bytes rather
than restated in prose:

* the site is a whole `call` to `Object::getModifierMultiplier`, bracketed by a setup that names
  the `SPEED` type and an out slot and by a fold that consumes `al`;
* the cave is call-compatible with what it replaced — same argument cleanup, same "nothing
  contributed" answer, same registers left alone;
* it only ever walks a list for an object the engine calls `KINDOF HORDE`, and only ever asks
  members the engine calls `HORDE_MEMBER`; and
* `min` and `max` differ by exactly one branch condition, which is what makes `detect` able to
  recover which one a binary was built with.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch import apply_patches
from sage_patch.addresses import (
    AI_UPDATE_LOCOMOTOR_SET_SPEED,
    CONTAIN_ITEM_LIST,
    CONTAIN_ITEM_LIST_NODE_OBJECT,
    KINDOF_HORDE_BIT,
    KINDOF_HORDE_BYTE,
    LOCOMOTOR_SPEED_MODIFIER_CALL,
    LOCOMOTOR_SPEED_MODIFIER_CALL_BYTES,
    LOCOMOTOR_SPEED_MODIFIER_FOLD,
    LOCOMOTOR_SPEED_MODIFIER_SETUP,
    MODIFIER_TYPE_SPEED,
    OBJECT_CONTAIN,
    OBJECT_GET_MODIFIER_MULTIPLIER,
    OBJECT_STATUS,
    OBJECT_STATUS_HORDE_MEMBER,
    OBJECT_THING_TEMPLATE,
)
from sage_patch.patches.horde_member_speed import (
    AGGREGATES,
    ANCHORS,
    DEFAULT_AGGREGATE,
    SECTION_NAME,
    HordeMemberSpeedPatch,
    build_section,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

IMAGE_BASE = 0x400000
CAVE_BASE = 0x1000000
_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


def synthetic_image() -> bytearray:
    """A PE32 image big enough to map the query and every anchor, with the real original bytes
    planted, so the whole apply + verify path runs without the copyrighted `game.dat`."""
    highest = max(LOCOMOTOR_SPEED_MODIFIER_CALL, *ANCHORS) - IMAGE_BASE + 0x100
    data = bytearray(((highest + 0x400) // 0x200 + 1) * 0x200)

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
    struct.pack_into("<I", data, opt + 60, 0x400)  # SizeOfHeaders
    header = bytearray(40)
    header[0:8] = b".text\x00\x00\x00"
    size = len(data) - 0x1000
    struct.pack_into("<IIII", header, 8, size, 0x1000, size, 0x1000)
    data[opt + 0xE0 : opt + 0xE0 + 40] = header

    lo = LOCOMOTOR_SPEED_MODIFIER_CALL - IMAGE_BASE
    data[lo : lo + len(LOCOMOTOR_SPEED_MODIFIER_CALL_BYTES)] = LOCOMOTOR_SPEED_MODIFIER_CALL_BYTES
    for va, expected in ANCHORS.items():
        data[va - IMAGE_BASE : va - IMAGE_BASE + len(expected)] = expected
    return data


def disassemble(code: bytes, base: int):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(code, base))


class TestTheSiteIsTheSpeedQuery:
    def test_the_replaced_bytes_are_one_whole_call(self):
        insns = disassemble(LOCOMOTOR_SPEED_MODIFIER_CALL_BYTES, LOCOMOTOR_SPEED_MODIFIER_CALL)
        assert [i.mnemonic for i in insns] == ["call"]
        assert insns[0].size == len(LOCOMOTOR_SPEED_MODIFIER_CALL_BYTES)

    def test_it_calls_get_modifier_multiplier(self):
        insns = disassemble(LOCOMOTOR_SPEED_MODIFIER_CALL_BYTES, LOCOMOTOR_SPEED_MODIFIER_CALL)
        assert int(insns[0].op_str, 16) == OBJECT_GET_MODIFIER_MULTIPLIER

    def test_the_setup_pushes_the_speed_type_and_an_out_slot(self):
        """`push flag / push ctx / lea &out / push / push 8 / mov ecx,obj / seed`, in that order —
        which is what lets the cave forward the caller's own arguments rather than name them."""
        insns = disassemble(ANCHORS[LOCOMOTOR_SPEED_MODIFIER_SETUP], LOCOMOTOR_SPEED_MODIFIER_SETUP)
        pushes = [i for i in insns if i.mnemonic == "push"]
        assert len(pushes) == 4
        assert pushes[-1].op_str == str(MODIFIER_TYPE_SPEED)
        assert any(i.mnemonic == "lea" and i.op_str == "eax, [ebp - 8]" for i in insns)
        assert any(i.mnemonic == "mov" and i.op_str == "ecx, edi" for i in insns)

    def test_the_setup_runs_straight_into_the_call(self):
        end = LOCOMOTOR_SPEED_MODIFIER_SETUP + len(ANCHORS[LOCOMOTOR_SPEED_MODIFIER_SETUP])
        assert end == LOCOMOTOR_SPEED_MODIFIER_CALL

    def test_the_fold_begins_where_the_call_ends(self):
        end = LOCOMOTOR_SPEED_MODIFIER_CALL + len(LOCOMOTOR_SPEED_MODIFIER_CALL_BYTES)
        assert end == LOCOMOTOR_SPEED_MODIFIER_FOLD

    def test_the_fold_skips_the_multiply_when_nothing_contributed(self):
        """`test al,al / je / movss / mulss / movss` — the arm the cave must be able to reproduce
        exactly, since that is what "this patch changes nothing here" means."""
        insns = disassemble(ANCHORS[LOCOMOTOR_SPEED_MODIFIER_FOLD], LOCOMOTOR_SPEED_MODIFIER_FOLD)
        assert [i.mnemonic for i in insns] == ["test", "je", "movss", "mulss", "movss"]
        assert insns[0].op_str == "al, al"
        assert int(insns[1].op_str, 16) > LOCOMOTOR_SPEED_MODIFIER_FOLD
        assert insns[3].op_str == "xmm0, dword ptr [ebp - 4]"


class TestTheMechanismItCorrects:
    def test_a_hordes_speed_is_its_own_locomotor_sets(self):
        """The single writer of the cached set speed stores what the *container's* ThingTemplate
        returned — the reason a member's own number never reaches the pace."""
        va = next(v for v in ANCHORS if v == 0x006680FB)
        insns = disassemble(ANCHORS[va], va)
        assert insns[0].mnemonic == "fstp"
        assert insns[0].op_str == f"dword ptr [esi + {AI_UPDATE_LOCOMOTOR_SET_SPEED:#x}]"

    def test_the_contain_walk_reads_a_sentinel_list_of_objects(self):
        """`[iface+0x34]` is the sentinel, `[node+8]` the object — asserted from a walk that lives
        in seventeen contain vtables, which is what makes the offsets a base-class property."""
        va = 0x0086620E
        insns = disassemble(ANCHORS[va], va)
        assert any(i.op_str == f"eax, dword ptr [ebx + {CONTAIN_ITEM_LIST:#x}]" for i in insns)
        assert any(i.op_str == "esi, dword ptr [eax]" for i in insns)
        assert any(i.op_str == "esi, eax" and i.mnemonic == "cmp" for i in insns)
        node = f"edi, dword ptr [esi + {CONTAIN_ITEM_LIST_NODE_OBJECT}]"
        assert any(i.op_str == node for i in insns)

    def test_the_status_bit_encoding_is_the_engines_own(self):
        """`testStatus` indexes `Object+0x94 + (bit>>5)*4` and masks `1 << (bit & 31)`, which is
        what the cave's open-coded `test byte [obj+0x98], 0x40` has to agree with."""
        va = 0x0044DDEC
        insns = disassemble(ANCHORS[va], va)
        assert any("0x1f" in i.op_str for i in insns), "the bit-within-dword mask"
        assert any(i.mnemonic == "shr" and i.op_str == "edx, 5" for i in insns)
        assert any(f"edx*4 + {OBJECT_STATUS:#x}" in i.op_str for i in insns)


class TestTheCave:
    @pytest.mark.parametrize("aggregate", sorted(AGGREGATES))
    def test_it_decodes_cleanly_end_to_end(self, aggregate: str):
        code = build_section(CAVE_BASE, aggregate)
        insns = disassemble(code, CAVE_BASE)
        assert sum(i.size for i in insns) == len(code)

    @pytest.mark.parametrize("aggregate", sorted(AGGREGATES))
    def test_it_returns_the_way_the_stock_callee_does(self, aggregate: str):
        """One exit, `ret 0x10`: the four arguments the site pushed are cleaned by the callee, so
        a cave that returned any other way would unbalance `getMaxSpeed`'s stack."""
        insns = disassemble(build_section(CAVE_BASE, aggregate), CAVE_BASE)
        rets = [i for i in insns if i.mnemonic == "ret"]
        assert len(rets) == 1
        assert rets[0].op_str == "0x10"
        assert rets[0].address == insns[-1].address

    @pytest.mark.parametrize("aggregate", sorted(AGGREGATES))
    def test_it_restores_every_register_the_caller_keeps_live(self, aggregate: str):
        """`ebx`, `esi`, `edi` and `ebp` are all live across the call at the hook site, and the
        cave uses all four — so each push must have its pop."""
        insns = disassemble(build_section(CAVE_BASE, aggregate), CAVE_BASE)
        saved = {"ebp", "ebx", "esi", "edi"}
        pushed = [i.op_str for i in insns if i.mnemonic == "push" and i.op_str in saved]
        popped = [i.op_str for i in insns if i.mnemonic == "pop"]
        assert pushed == ["ebp", "ebx", "esi", "edi"]
        assert popped == ["edi", "esi", "ebx", "ebp"]
        assert any(i.mnemonic == "mov" and i.op_str == "esp, ebp" for i in insns)

    @pytest.mark.parametrize("aggregate", sorted(AGGREGATES))
    def test_it_makes_the_same_query_twice_and_only_that_query(self, aggregate: str):
        """Once for the object, once per qualifying member — and never any other engine function,
        which is what keeps the cave's side effects to the one it forwards."""
        insns = disassemble(build_section(CAVE_BASE, aggregate), CAVE_BASE)
        calls = [i for i in insns if i.mnemonic == "call"]
        assert len(calls) == 2
        assert {int(i.op_str, 16) for i in calls} == {OBJECT_GET_MODIFIER_MULTIPLIER}

    @pytest.mark.parametrize("aggregate", sorted(AGGREGATES))
    def test_both_queries_forward_the_callers_arguments(self, aggregate: str):
        """The type, ctx and flag come from `[ebp+8]`, `[ebp+0x10]` and `[ebp+0x14]` rather than
        from constants, so the cave widens the site's own question instead of asking a new one."""
        insns = disassemble(build_section(CAVE_BASE, aggregate), CAVE_BASE)
        forwarded = [i.op_str for i in insns if i.mnemonic == "push" and "ebp +" in i.op_str]
        assert forwarded.count("dword ptr [ebp + 8]") == 2
        assert forwarded.count("dword ptr [ebp + 0x10]") == 2
        assert forwarded.count("dword ptr [ebp + 0x14]") == 2

    @pytest.mark.parametrize("aggregate", sorted(AGGREGATES))
    def test_neither_query_is_handed_the_callers_out_pointer(self, aggregate: str):
        """`[ebp+0xC]` is read exactly once, on the way out. Every query writes the cave's private
        slot, so the caller's `Real*` holds the finished product or is never touched at all."""
        insns = disassemble(build_section(CAVE_BASE, aggregate), CAVE_BASE)
        reads = [i for i in insns if "[ebp + 0xc]" in i.op_str]
        assert len(reads) == 1
        assert reads[0].mnemonic == "mov"
        assert reads[0].op_str == "eax, dword ptr [ebp + 0xc]"
        assert not any(i.mnemonic == "push" and "0xc" in i.op_str for i in insns)

    @pytest.mark.parametrize("aggregate", sorted(AGGREGATES))
    def test_the_nothing_contributed_arm_leaves_the_out_pointer_alone(self, aggregate: str):
        """The one write through the caller's pointer is downstream of `test ebx,ebx`, so an
        object nothing modified gets `al = 0` and a slot the caller never reads — stock."""
        insns = disassemble(build_section(CAVE_BASE, aggregate), CAVE_BASE)
        gate = next(i for i in insns if i.mnemonic == "test" and i.op_str == "ebx, ebx")
        write = next(i for i in insns if i.op_str == "dword ptr [eax], xmm0")
        clear = next(i for i in insns if i.mnemonic == "xor" and i.op_str == "al, al")
        assert gate.address < write.address < clear.address

    @pytest.mark.parametrize("aggregate", sorted(AGGREGATES))
    def test_both_accumulators_start_at_one(self, aggregate: str):
        """A neutral multiplier, so an object with no modifier and a horde with no modified member
        both come out at exactly the number the site already had."""
        one = struct.unpack("<I", struct.pack("<f", 1.0))[0]
        insns = disassemble(build_section(CAVE_BASE, aggregate), CAVE_BASE)
        seeds = [i for i in insns if i.mnemonic == "mov" and hex(one) in i.op_str]
        assert {i.op_str for i in seeds} == {
            f"dword ptr [ebp - 4], {one:#x}",
            f"dword ptr [ebp - 0xc], {one:#x}",
        }

    @pytest.mark.parametrize("aggregate", sorted(AGGREGATES))
    def test_the_result_is_the_object_times_the_members(self, aggregate: str):
        """One `mulss`, of the own-modifier slot by the member aggregate — the horde's own SPEED
        list keeps working and composes with what the members contribute."""
        insns = disassemble(build_section(CAVE_BASE, aggregate), CAVE_BASE)
        muls = [i for i in insns if i.mnemonic == "mulss"]
        assert len(muls) == 1
        assert muls[0].op_str == "xmm0, dword ptr [ebp - 0xc]"
        load = next(i for i in insns if i.address < muls[0].address and i.mnemonic == "movss")
        assert load is not None

    @pytest.mark.parametrize("aggregate", sorted(AGGREGATES))
    def test_the_walk_is_gated_on_kindof_horde_then_on_a_contain_module(self, aggregate: str):
        """Every non-horde object in the game pays one template read, one `test` and a not-taken
        branch — so the gate has to come before anything that dereferences a list."""
        insns = disassemble(build_section(CAVE_BASE, aggregate), CAVE_BASE)
        tmpl = next(
            i
            for i in insns
            if i.op_str == f"eax, dword ptr [edi + {OBJECT_THING_TEMPLATE}]"  # noqa: E501
        )
        kind = next(
            i
            for i in insns
            if i.mnemonic == "test"
            and i.op_str == f"byte ptr [eax + {KINDOF_HORDE_BYTE:#x}], {KINDOF_HORDE_BIT:#x}"
        )
        contain = next(
            i for i in insns if i.op_str == f"edi, dword ptr [edi + {OBJECT_CONTAIN:#x}]"
        )
        head = next(
            i for i in insns if i.op_str == f"esi, dword ptr [edi + {CONTAIN_ITEM_LIST:#x}]"
        )
        assert tmpl.address < kind.address < contain.address < head.address

    @pytest.mark.parametrize("aggregate", sorted(AGGREGATES))
    def test_every_pointer_it_follows_is_null_checked(self, aggregate: str):
        """The contain module, the list head and each member object: three `test reg,reg` guards,
        because `getMaxSpeed` runs for objects that contain nothing at all."""
        insns = disassemble(build_section(CAVE_BASE, aggregate), CAVE_BASE)
        guards = {
            i.op_str
            for i in insns
            if i.mnemonic == "test" and i.op_str in {"edi, edi", "esi, esi", "eax, eax"}
        }
        assert guards == {"edi, edi", "esi, esi", "eax, eax"}

    @pytest.mark.parametrize("aggregate", sorted(AGGREGATES))
    def test_only_horde_members_are_asked(self, aggregate: str):
        """The status filter is the engine's own membership answer: `addToContain` clears the bit
        for a MACHINE, HERO or SIEGE_TOWER, so a hero in the battalion cannot skew the aggregate."""
        byte = OBJECT_STATUS + (OBJECT_STATUS_HORDE_MEMBER // 32) * 4
        mask = 1 << (OBJECT_STATUS_HORDE_MEMBER % 8)
        insns = disassemble(build_section(CAVE_BASE, aggregate), CAVE_BASE)
        assert any(
            i.mnemonic == "test" and i.op_str == f"byte ptr [eax + {byte:#x}], {mask:#x}"
            for i in insns
        )

    @pytest.mark.parametrize("aggregate", sorted(AGGREGATES))
    def test_the_loop_terminates_on_the_sentinel(self, aggregate: str):
        """One backward branch, and the only way out of it is `cmp edi,esi` reaching the node the
        head pointed at — a list the game corrupts would hang, so this is the invariant."""
        insns = disassemble(build_section(CAVE_BASE, aggregate), CAVE_BASE)
        back = [i for i in insns if i.mnemonic == "jmp" and int(i.op_str, 16) < i.address]
        assert len(back) == 1
        top = int(back[0].op_str, 16)
        assert next(i for i in insns if i.address == top).op_str == "edi, esi"
        assert any(i.op_str == "edi, dword ptr [edi]" for i in insns)

    def test_min_and_max_differ_by_exactly_one_branch(self):
        """Which is what `detect` leans on to recover the aggregate a binary was built with."""
        lo = build_section(CAVE_BASE, "min")
        hi = build_section(CAVE_BASE, "max")
        assert len(lo) == len(hi)
        differing = [i for i, (a, b) in enumerate(zip(lo, hi, strict=True)) if a != b]
        assert len(differing) == 1
        assert {lo[differing[0]], hi[differing[0]]} == {0x73, 0x76}  # jae / jbe

    @pytest.mark.parametrize("aggregate", sorted(AGGREGATES))
    def test_the_comparison_precedes_the_store_it_guards(self, aggregate: str):
        insns = disassemble(build_section(CAVE_BASE, aggregate), CAVE_BASE)
        cmp_ = next(i for i in insns if i.mnemonic == "comiss")
        assert cmp_.op_str == "xmm0, dword ptr [ebp - 0xc]"
        store = next(i for i in insns if i.op_str == "dword ptr [ebp - 0xc], xmm0")
        assert cmp_.address < store.address

    @pytest.mark.parametrize("aggregate", sorted(AGGREGATES))
    def test_only_its_own_base_moves_its_bytes(self, aggregate: str):
        """The two `call rel32` displacements are the only position-dependent thing in it, which
        is why `verify` recomputes the cave from the section header's VA."""
        a = build_section(CAVE_BASE, aggregate)
        b = build_section(CAVE_BASE + 0x10000, aggregate)
        assert len(a) == len(b)
        assert sum(x != y for x, y in zip(a, b, strict=True)) <= 8


class TestApply:
    @pytest.mark.parametrize("aggregate", sorted(AGGREGATES))
    def test_apply_then_verify(self, aggregate: str):
        data = synthetic_image()
        HordeMemberSpeedPatch(aggregate).apply(data)
        assert HordeMemberSpeedPatch(aggregate).verify(data) == []

    def test_a_stock_image_does_not_verify(self):
        assert HordeMemberSpeedPatch().verify(synthetic_image()) == [
            f"no {SECTION_NAME} section: the file does not carry this patch"
        ]

    def test_the_other_aggregate_does_not_verify(self):
        data = synthetic_image()
        HordeMemberSpeedPatch("min").apply(data)
        assert HordeMemberSpeedPatch("max").verify(data) != []

    def test_detect_recovers_the_aggregate(self):
        for aggregate in AGGREGATES:
            data = synthetic_image()
            HordeMemberSpeedPatch(aggregate).apply(data)
            found = HordeMemberSpeedPatch.detect(data)
            assert found is not None
            assert found.aggregate == aggregate
            assert found.options() == {"aggregate": aggregate}

    def test_detect_says_no_on_a_stock_image(self):
        assert HordeMemberSpeedPatch.detect(synthetic_image()) is None

    def test_the_call_lands_on_the_section_it_allocated(self):
        data = synthetic_image()
        HordeMemberSpeedPatch().apply(data)
        section_va, _off, _vsize = find_section(data, SECTION_NAME)
        off = va_to_offset(data, LOCOMOTOR_SPEED_MODIFIER_CALL)
        target = LOCOMOTOR_SPEED_MODIFIER_CALL + 5 + struct.unpack_from("<i", data, off + 1)[0]
        assert target == section_va

    def test_it_rewrites_nothing_in_text_but_those_five_bytes(self):
        before = synthetic_image()
        data = synthetic_image()
        HordeMemberSpeedPatch().apply(data)
        off = va_to_offset(data, LOCOMOTOR_SPEED_MODIFIER_CALL)
        changed = {i for i in range(0x1000, len(before)) if data[i] != before[i]}
        window = set(range(off, off + len(LOCOMOTOR_SPEED_MODIFIER_CALL_BYTES)))
        assert changed <= window, "the hook must not spill outside the call it replaces"
        assert changed, "the hook has to be written somewhere"

    def test_the_setup_and_the_fold_survive(self):
        """They bracket the hook and are asserted, never written — `verify` re-checks both, so a
        later patch landing on either is reported rather than silently tolerated."""
        data = synthetic_image()
        HordeMemberSpeedPatch().apply(data)
        for va in (LOCOMOTOR_SPEED_MODIFIER_SETUP, LOCOMOTOR_SPEED_MODIFIER_FOLD):
            off = va_to_offset(data, va)
            assert bytes(data[off : off + len(ANCHORS[va])]) == ANCHORS[va]

    def test_a_clobbered_bracket_fails_verify(self):
        data = synthetic_image()
        HordeMemberSpeedPatch().apply(data)
        off = va_to_offset(data, LOCOMOTOR_SPEED_MODIFIER_FOLD)
        data[off : off + 2] = b"\x90\x90"
        assert HordeMemberSpeedPatch().verify(data) == [
            f"{LOCOMOTOR_SPEED_MODIFIER_FOLD:#010x} no longer holds the query it brackets"
        ]

    def test_refuses_to_apply_twice(self):
        data = synthetic_image()
        HordeMemberSpeedPatch().apply(data)
        with pytest.raises(ValueError, match="expected"):
            HordeMemberSpeedPatch().apply(data)

    def test_an_unknown_aggregate_is_refused_at_construction(self):
        with pytest.raises(ValueError, match="unknown aggregate"):
            HordeMemberSpeedPatch("average")

    @pytest.mark.parametrize("va", sorted(ANCHORS))
    def test_a_moved_anchor_refuses_to_apply(self, va: int):
        data = synthetic_image()
        data[va - IMAGE_BASE : va - IMAGE_BASE + 2] = b"\x90\x90"
        with pytest.raises(ValueError, match="not this build's"):
            HordeMemberSpeedPatch().apply(data)

    def test_a_moved_anchor_leaves_the_query_alone(self):
        """The anchors are checked before anything is written, so a refused apply is a no-op."""
        before = synthetic_image()
        data = synthetic_image()
        lo = 0x0086620E - IMAGE_BASE
        data[lo : lo + 2] = b"\x90\x90"
        with pytest.raises(ValueError):
            HordeMemberSpeedPatch().apply(data)
        off = va_to_offset(before, LOCOMOTOR_SPEED_MODIFIER_CALL)
        end = off + len(LOCOMOTOR_SPEED_MODIFIER_CALL_BYTES)
        assert data[off:end] == before[off:end]
        assert find_section(data, SECTION_NAME) is None


class TestRegistration:
    def test_it_is_registered_under_its_name(self):
        assert PATCHES[HordeMemberSpeedPatch.name] is HordeMemberSpeedPatch

    def test_it_is_not_experimental(self):
        assert not HordeMemberSpeedPatch.experimental

    def test_the_default_aggregate_is_the_slowest_member(self):
        assert DEFAULT_AGGREGATE == "min"
        assert HordeMemberSpeedPatch().aggregate == DEFAULT_AGGREGATE

    def test_its_name_carries_the_aggregate(self):
        assert str(HordeMemberSpeedPatch("max")) == "horde-member-speed (max)"


class TestTheRealBinary:
    """The synthetic image proves the patch is self-consistent; only a real `game.dat` proves the
    addresses are right. Skipped where there is none, which is every machine but the author's."""

    @staticmethod
    @pytest.fixture(scope="class")
    def game_dat() -> bytes:
        if not _GAME_DAT.exists():
            pytest.skip(f"no {_GAME_DAT}")
        return _GAME_DAT.read_bytes()

    def test_every_anchor_holds_what_the_patch_says_it_holds(self, game_dat: bytes) -> None:
        for va, expected in sorted(ANCHORS.items()):
            off = va_to_offset(game_dat, va)
            assert off is not None, f"0x{va:08X}"
            assert bytes(game_dat[off : off + len(expected)]) == expected, f"0x{va:08X}"

    def test_the_site_holds_the_stock_query(self, game_dat: bytes) -> None:
        off = va_to_offset(game_dat, LOCOMOTOR_SPEED_MODIFIER_CALL)
        got = bytes(game_dat[off : off + len(LOCOMOTOR_SPEED_MODIFIER_CALL_BYTES)])
        assert got == LOCOMOTOR_SPEED_MODIFIER_CALL_BYTES

    @pytest.mark.parametrize("aggregate", sorted(AGGREGATES))
    def test_apply_and_verify_on_the_real_thing(
        self, game_dat: bytes, tmp_path: Path, aggregate: str
    ) -> None:
        src = tmp_path / "game.dat"
        src.write_bytes(game_dat)
        patch = HordeMemberSpeedPatch(aggregate)
        out = apply_patches(src, [patch], tmp_path / f"out-{aggregate}.dat")
        data = out.read_bytes()
        assert patch.verify(data) == []
        assert HordeMemberSpeedPatch.detect(data).aggregate == aggregate
        section_va, _off, _vsize = find_section(data, SECTION_NAME)
        off = va_to_offset(data, LOCOMOTOR_SPEED_MODIFIER_CALL)
        target = LOCOMOTOR_SPEED_MODIFIER_CALL + 5 + struct.unpack_from("<i", data, off + 1)[0]
        assert target == section_va
        assert src.read_bytes() == game_dat, "the input was modified"
