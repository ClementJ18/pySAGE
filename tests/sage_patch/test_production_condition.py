"""Tests for the production model-condition patch.

Two kinds of thing are checked here, and only one of them is ordinary code.

The cave is hand-encoded x86 that cannot be executed in a test, so the tests that matter
disassemble it back and assert it says what it was meant to say. A wrong byte does not raise -
it crashes the game, or silently flags the wrong bit on the wrong object.

The rest guard *invariants of the target build* that the patch quietly depends on: that bit 591
is the last one the engine's 74-byte `xfer` buffer covers, and that the mask ends exactly where
`Object`'s next field begins. Both are the reason this patch installs exactly one condition, and
neither is visible from the code that relies on it.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.patches import locomotor_sets, weapon_set_flags
from sage_patch.patches.production_condition import (
    _COUNT_SITES,
    _NAME_TABLE_VA,
    _PROPAGATE_VA,
    _SECTION_NAME,
    _TABLE_FINGERPRINT,
    _TABLE_REF_VAS,
    _THIS_TO_OBJECT,
    _THIS_TO_QUEUE_HEAD,
    _UPDATE_ENTRY,
    _UPDATE_VA,
    _UPDATE_VTABLE,
    _UPDATE_VTABLE_SLOT,
    MASK_OFFSET,
    NEW_BIT,
    STOCK_BIT_COUNT,
    ProductionConditionPatch,
    build_hook_code,
)
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import IMAGE_BASE, synthetic_image

BASE = 0x00F00000

#: The two optional halves, as :meth:`ProductionConditionPatch.__init__` takes them.
WEAPON_FLAG = "PRODUCING_WEAPONS"
LOCOMOTOR_SET = "SET_PRODUCING"

#: `ModelConditionFlags` is 19 dwords. The patch relies on this in two places at once: the bit it
#: names must fall inside it, and the `and` mask it writes must not reach the field beyond it.
_MASK_DWORDS = 19


@pytest.fixture(scope="module")
def clean() -> bytearray:
    """Built once - the image is ~10 MB and every test only reads or copies it."""
    return synthetic_image()


@pytest.fixture
def image(clean: bytearray) -> bytearray:
    return bytearray(clean)


def disassemble(base: int = BASE, **kwargs):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(build_hook_code(base, **kwargs), base))


#: The cave with both optional halves installed: flag 104 (the first free one), its mask constant
#: parked at a plausible address in the same cave, and locomotor set 17.
FULL = {"bit": NEW_BIT, "weapon": (104, BASE + 0x400), "locomotor": 17}


class TestBuildInvariants:
    """The facts about the engine that make exactly one new condition free."""

    def test_the_new_bit_is_the_first_unnamed_one(self):
        assert NEW_BIT == STOCK_BIT_COUNT

    def test_the_new_bit_fits_the_existing_mask_without_growing_it(self):
        """591 named bits in 19 dwords leaves 17 unnamed slots, so no structure grows."""
        assert NEW_BIT < _MASK_DWORDS * 32

    def test_the_new_bit_is_inside_the_74_byte_xfer_window(self):
        """`ModelConditionFlags::xfer` packs the mask into 74 bytes = 592 bits exactly. Bit 591 is
        the last one saved and CRC'd, which is why raising the count to 592 leaves the savegame
        and network-CRC layout byte-identical. A 593rd condition would not be free."""
        xfer_bits = 74 * 8
        assert xfer_bits == 592, "the packer's length constant is what bounds this patch"
        assert NEW_BIT < xfer_bits
        # and the patched count exactly fills it, so the packed blob does not change size
        assert STOCK_BIT_COUNT + 1 == xfer_bits

    def test_the_mask_ends_where_the_next_object_field_begins(self):
        """0x10C + 19*4 == 0x158, the second Matrix3D copy. If the mask were shorter, the `and`
        the cave writes would clear a bit of a neighbouring field instead."""
        assert MASK_OFFSET + _MASK_DWORDS * 4 == 0x158

    def test_the_hook_site_is_exactly_a_jmp_rel32_wide(self):
        assert len(_UPDATE_ENTRY) == 5


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        """Capstone stopping early means an invalid encoding, which would be a crash in-game."""
        insns = disassemble()
        assert sum(i.size for i in insns) == len(build_hook_code(BASE))

    def test_it_preserves_this_across_the_body(self):
        """`update`'s SEH prologue still needs ecx, and the cave runs before it."""
        ops = [(i.mnemonic, i.op_str) for i in disassemble()]
        assert ops[0] == ("push", "ecx")
        assert ("pop", "ecx") in ops
        assert ops.index(("push", "ecx")) < ops.index(("pop", "ecx"))

    def test_it_reads_the_object_and_the_queue_head_at_the_derived_offsets(self):
        # capstone renders displacements below 10 in decimal, hence the two formats
        ops = [(i.mnemonic, i.op_str) for i in disassemble()]
        assert ("mov", f"eax, dword ptr [ecx - {abs(_THIS_TO_OBJECT)}]") in ops
        assert ("cmp", f"dword ptr [ecx + {_THIS_TO_QUEUE_HEAD:#x}], 0") in ops

    def test_it_touches_only_the_dword_holding_the_new_bit(self):
        word_offset = MASK_OFFSET + (NEW_BIT // 32) * 4
        mask = 1 << (NEW_BIT % 32)
        touches = [
            i for i in disassemble() if i.mnemonic in ("test", "or", "and") and "ptr [" in i.op_str
        ]
        assert touches, "the cave must read-modify-write the mask"
        for ins in touches:
            assert f"[eax + {word_offset:#x}]" in ins.op_str
        ors = [i for i in touches if i.mnemonic == "or"]
        ands = [i for i in touches if i.mnemonic == "and"]
        assert [i.op_str.split(", ")[-1] for i in ors] == [f"{mask:#x}"]
        assert [i.op_str.split(", ")[-1] for i in ands] == [f"{~mask & 0xFFFFFFFF:#x}"]

    def test_the_clear_mask_leaves_every_other_bit_alone(self):
        ands = [i for i in disassemble() if i.mnemonic == "and"]
        (mask,) = [int(i.op_str.split(", ")[-1], 16) for i in ands]
        assert mask == ~(1 << (NEW_BIT % 32)) & 0xFFFFFFFF
        assert bin(mask).count("0") - 1 == 1, "exactly one bit cleared"

    def test_both_paths_test_before_writing(self):
        """Without this the cave would push the mask to the drawable on every logic frame for
        every producing building. The engine's own condition writes inside `update` test first."""
        insns = disassemble()
        tests = [i for i in insns if i.mnemonic == "test" and "eax +" in i.op_str]
        assert len(tests) == 2, "one guard for the set path, one for the clear path"
        writes = [i for i in insns if i.mnemonic in ("or", "and")]
        for write in writes:
            assert any(t.address < write.address for t in tests)

    def test_its_only_call_is_the_propagate_helper(self):
        calls = [i for i in disassemble() if i.mnemonic == "call"]
        assert [int(i.op_str, 16) for i in calls] == [_PROPAGATE_VA]

    def test_it_reruns_the_displaced_instruction_and_returns_past_it(self):
        insns = disassemble()
        assert (insns[-2].mnemonic, insns[-2].op_str) == ("mov", "eax, 0xba2088")
        assert insns[-1].mnemonic == "jmp"
        assert int(insns[-1].op_str, 16) == _UPDATE_VA + len(_UPDATE_ENTRY)

    def test_it_has_exactly_one_exit(self):
        """The internal `jmp` onto the shared propagate tail stays in the cave; the only jump
        that leaves is the return into `update`."""
        code = build_hook_code(BASE)
        lo, hi = BASE, BASE + len(code)
        targets = {int(i.op_str, 16) for i in disassemble() if i.mnemonic == "jmp"}
        assert {t for t in targets if not lo <= t < hi} == {_UPDATE_VA + len(_UPDATE_ENTRY)}

    def test_every_conditional_branch_stays_inside_the_cave(self):
        """A displacement computed wrong would jump into arbitrary engine code."""
        code = build_hook_code(BASE)
        lo, hi = BASE, BASE + len(code)
        for ins in disassemble():
            if not ins.mnemonic.startswith("j") or ins.mnemonic == "jmp":
                continue
            assert lo <= int(ins.op_str, 16) < hi, f"{ins.mnemonic} at {ins.address:#x} escapes"

    def test_it_relocates_with_its_section(self):
        a, b = build_hook_code(BASE), build_hook_code(BASE + 0x1000)
        assert a != b, "the call and the return jump must be recomputed for the cave's address"
        assert len(a) == len(b)


class TestApply:
    def test_apply_then_verify(self, image: bytearray):
        ProductionConditionPatch().apply(image)
        assert ProductionConditionPatch().verify(image) == []

    def test_verify_rejects_an_unpatched_image(self, clean: bytearray):
        assert ProductionConditionPatch().verify(clean) != []

    def test_the_new_table_appends_one_entry_and_keeps_every_index(self, image: bytearray):
        ProductionConditionPatch(condition="PRODUCING").apply(image)
        base_va, _off, _vsize = find_section(image, _SECTION_NAME)

        def name_at(index: int) -> str | None:
            ptr = struct.unpack_from("<I", image, va_to_offset(image, base_va + index * 4))[0]
            if ptr == 0:
                return None
            off = va_to_offset(image, ptr)
            end = bytes(image[off : off + 64]).find(b"\x00")
            return bytes(image[off : off + end]).decode("ascii")

        for index, expected in _TABLE_FINGERPRINT.items():
            assert name_at(index) == expected
        assert name_at(STOCK_BIT_COUNT) == "PRODUCING"
        assert name_at(STOCK_BIT_COUNT + 1) is None, "the table must stay NULL-terminated"

    def test_every_table_reference_is_repointed(self, image: bytearray):
        ProductionConditionPatch().apply(image)
        base_va, _off, _vsize = find_section(image, _SECTION_NAME)
        for va in _TABLE_REF_VAS:
            got = struct.unpack_from("<I", image, va_to_offset(image, va))[0]
            assert got == base_va, f"{va:#010x} still points at the stock table"

    def test_every_count_site_is_raised(self, image: bytearray):
        ProductionConditionPatch().apply(image)
        for va, prefix in _COUNT_SITES:
            off = va_to_offset(image, va) + len(prefix)
            assert struct.unpack_from("<I", image, off)[0] == STOCK_BIT_COUNT + 1

    def test_the_hook_is_a_jmp_into_the_cave(self, image: bytearray):
        ProductionConditionPatch().apply(image)
        base_va, _off, vsize = find_section(image, _SECTION_NAME)
        off = va_to_offset(image, _UPDATE_VA)
        assert image[off] == 0xE9
        target = _UPDATE_VA + 5 + struct.unpack_from("<i", image, off + 1)[0]
        assert base_va <= target < base_va + vsize, "the hook must land inside its own cave"

    def test_applying_twice_raises_rather_than_corrupting(self, image: bytearray):
        ProductionConditionPatch().apply(image)
        with pytest.raises(ValueError):
            ProductionConditionPatch().apply(image)

    def test_a_wrong_build_is_refused_by_the_fingerprint(self, image: bytearray):
        """A build whose table has different names at the fingerprint indices is not this one."""
        ptr = struct.unpack_from("<I", image, va_to_offset(image, _NAME_TABLE_VA + 218 * 4))[0]
        image[va_to_offset(image, ptr)] = ord("X")
        with pytest.raises(ValueError, match="unexpected build"):
            ProductionConditionPatch().apply(image)

    def test_a_moved_vtable_slot_is_refused(self, image: bytearray):
        """`update` is virtual, so a hook on the wrong function would verify clean and never
        fire. The dispatch check is the only thing that catches it."""
        struct.pack_into(
            "<I", image, _UPDATE_VTABLE + _UPDATE_VTABLE_SLOT - IMAGE_BASE, _UPDATE_VA + 0x40
        )
        with pytest.raises(ValueError, match="ProductionUpdate::update"):
            ProductionConditionPatch().apply(image)

    def test_the_count_and_the_table_must_move_together(self, image: bytearray):
        """Two count-bounded loops index the table with no bound check, so a count raised without
        the table extended would hand a NULL string pointer to AsciiString concatenation. They
        are written by one patch precisely so that cannot happen - assert `verify` notices."""
        ProductionConditionPatch().apply(image)
        va, prefix = _COUNT_SITES[0]
        struct.pack_into("<I", image, va_to_offset(image, va) + len(prefix), STOCK_BIT_COUNT)
        problems = ProductionConditionPatch().verify(image)
        assert any("count bound" in p for p in problems)


class TestTheOptionalCave:
    """The two opt-in blocks. Everything here is about the code they emit; what they mean to the
    engine is in `weapon_set_flags` and `locomotor_sets`."""

    def test_asking_for_neither_emits_exactly_the_cave_it_always_did(self):
        """The extras are additive: with both off, not one byte moves. This is what lets every
        other test in this file go on asserting the original body."""
        assert build_hook_code(BASE) == build_hook_code(BASE, NEW_BIT, None, None)
        assert len(build_hook_code(BASE, **FULL)) > len(build_hook_code(BASE))

    def test_it_disassembles_cleanly_to_its_end(self):
        insns = disassemble(**FULL)
        assert sum(i.size for i in insns) == len(build_hook_code(BASE, **FULL))

    def test_every_conditional_branch_stays_inside_the_cave(self):
        code = build_hook_code(BASE, **FULL)
        lo, hi = BASE, BASE + len(code)
        for ins in disassemble(**FULL):
            if not ins.mnemonic.startswith("j") or ins.mnemonic == "jmp":
                continue
            assert lo <= int(ins.op_str, 16) < hi, f"{ins.mnemonic} at {ins.address:#x} escapes"

    def test_it_still_has_exactly_one_exit(self):
        code = build_hook_code(BASE, **FULL)
        lo, hi = BASE, BASE + len(code)
        targets = {int(i.op_str, 16) for i in disassemble(**FULL) if i.mnemonic == "jmp"}
        assert {t for t in targets if not lo <= t < hi} == {_UPDATE_VA + len(_UPDATE_ENTRY)}

    def test_the_object_is_saved_around_every_added_call(self):
        """`eax` holds the `Object` for the whole body and every added call clobbers it, so each
        one has to sit between a `push eax` and a `pop eax` - and the pairs have to balance, or
        `update`'s prologue pops the wrong `this`."""
        ops = [(i.mnemonic, i.op_str) for i in disassemble(**FULL)]
        pushes = [n for n, op in enumerate(ops) if op == ("push", "eax")]
        pops = [n for n, op in enumerate(ops) if op == ("pop", "eax")]
        assert len(pushes) == len(pops) == 4, "two blocks, two paths each"
        for push, pop in zip(pushes, pops, strict=True):
            assert push < pop
            assert any(ops[n][0] == "call" for n in range(push, pop))

    def test_the_weapon_block_tests_the_flags_own_bit_not_the_conditions(self):
        """Level-triggered, and on `Object+0x38C` rather than `+0x10C`: a savegame restores the
        model condition but not the flag, so guarding on the condition would leave them disagreeing
        for the rest of the game."""
        word = weapon_set_flags.MASK_OFFSET + (FULL["weapon"][0] // 32) * 4
        mask = 1 << (FULL["weapon"][0] % 32)
        tests = [
            i
            for i in disassemble(**FULL)
            if i.mnemonic == "test" and f"[eax + {word:#x}]" in i.op_str
        ]
        assert len(tests) == 2, "one guard on the set path, one on the clear path"
        assert {i.op_str.split(", ")[-1] for i in tests} == {f"{mask:#x}"}

    def test_each_path_calls_the_matching_weapon_helper(self):
        insns = disassemble(**FULL)
        calls = [int(i.op_str, 16) for i in insns if i.mnemonic == "call" and "[" not in i.op_str]
        assert calls == [
            weapon_set_flags.SET_FLAGS_VA,  # the producing path
            weapon_set_flags.CLEAR_FLAGS_VA,  # the idle one
            _PROPAGATE_VA,  # still the only other thing the cave calls
        ]

    def test_the_mask_constants_address_is_what_is_pushed(self):
        pushes = [i.op_str for i in disassemble(**FULL) if i.mnemonic == "push"]
        assert pushes.count(hex(FULL["weapon"][1])) == 2, "both paths pass the same constant"

    def test_the_locomotor_block_null_checks_the_ai_module(self):
        """Most structures have no AI at all, and `[Object+0x260]` is NULL on every one of them."""
        ops = [(i.mnemonic, i.op_str) for i in disassemble(**FULL)]
        load = ("mov", f"ecx, dword ptr [eax + {locomotor_sets.AI_MODULE_OFFSET:#x}]")
        assert ops.count(load) == 2
        for index, op in enumerate(ops):
            if op == load:
                assert ops[index + 1] == ("test", "ecx, ecx")
                assert ops[index + 2][0] == "je"

    def test_the_locomotor_block_compares_the_current_set_before_calling(self):
        """Asking for a set that is already current is wasted work; reverting one that is no
        longer ours would stomp whatever chose it."""
        ops = [(i.mnemonic, i.op_str) for i in disassemble(**FULL)]
        compare = (
            "cmp",
            f"dword ptr [ecx + {locomotor_sets.CURRENT_SET_OFFSET:#x}], {FULL['locomotor']:#x}",
        )
        assert ops.count(compare) == 2
        branches = [ops[index + 1][0] for index, op in enumerate(ops) if op == compare]
        assert branches == ["je", "jne"], (
            "skip when already ours going in, when not ours coming out"
        )

    def test_it_reverts_to_set_normal_and_nothing_else(self):
        pushes = [
            int(i.op_str, 0)
            for i in disassemble(**FULL)
            if i.mnemonic == "push" and not i.op_str.isalpha()
        ]
        assert pushes.count(FULL["locomotor"]) == 1, "asked for once, on the producing path"
        assert pushes.count(locomotor_sets.NORMAL_SET) == 1, "and given back once"

    def test_the_locomotor_call_goes_through_the_vtable(self):
        """`chooseLocomotorSet` is virtual and has no fixed address; the engine's own call site
        loads the vtable off the module and indexes it, which is what this copies."""
        ops = [(i.mnemonic, i.op_str) for i in disassemble(**FULL)]
        indirect = ("call", f"dword ptr [edx + {locomotor_sets.CHOOSE_SET_SLOT:#x}]")
        assert ops.count(indirect) == 2
        for index, op in enumerate(ops):
            if op == indirect:
                assert ops[index - 1] == ("mov", "edx, dword ptr [ecx]")

    def test_it_relocates_with_its_section(self):
        a, b = build_hook_code(BASE, **FULL), build_hook_code(BASE + 0x1000, **FULL)
        assert a != b
        assert len(a) == len(b)


class TestApplyingTheOptionalHalves:
    def test_apply_then_verify_with_both(self, image: bytearray):
        patch = ProductionConditionPatch(weapon_set_flag=WEAPON_FLAG, locomotor_set=LOCOMOTOR_SET)
        patch.apply(image)
        assert patch.verify(image) == []

    @pytest.mark.parametrize(
        "kwargs",
        [{"weapon_set_flag": WEAPON_FLAG}, {"locomotor_set": LOCOMOTOR_SET}],
        ids=["weapon-only", "locomotor-only"],
    )
    def test_each_half_installs_on_its_own(self, image: bytearray, kwargs: dict):
        patch = ProductionConditionPatch(**kwargs)
        patch.apply(image)
        assert patch.verify(image) == []

    def test_neither_table_is_touched_when_neither_is_asked_for(self, image: bytearray):
        ProductionConditionPatch().apply(image)
        for module in (weapon_set_flags, locomotor_sets):
            for va in module.TABLE_REF_VAS:
                got = struct.unpack_from("<I", image, va_to_offset(image, va))[0]
                assert got == module.NAME_TABLE_VA, f"{va:#010x} was repointed for nothing"

    @pytest.mark.parametrize(
        ("module", "name", "stock_count"),
        [
            (weapon_set_flags, WEAPON_FLAG, weapon_set_flags.STOCK_FLAG_COUNT),
            (locomotor_sets, LOCOMOTOR_SET, locomotor_sets.STOCK_SET_COUNT),
        ],
        ids=["weapon-set-flags", "locomotor-sets"],
    )
    def test_the_new_table_appends_one_entry_and_keeps_every_index(
        self, image: bytearray, module, name: str, stock_count: int
    ):
        stock = module.read(image)
        ProductionConditionPatch(weapon_set_flag=WEAPON_FLAG, locomotor_set=LOCOMOTOR_SET).apply(
            image
        )
        patched = module.read(image)
        assert patched.base_va != stock.base_va, "the table has to move to grow"
        assert patched.count == stock_count + 1
        assert patched.pointers[:stock_count] == stock.pointers, "every name keeps its index"
        assert patched.index_of(image, name) == stock_count

    def test_the_weapon_set_count_is_deliberately_left_alone(self, image: bytearray):
        """Raising it would walk the 104-entry weaponset-to-model-condition map out of bounds and
        start saving a bit whose whole value is that it is recomputed. See `weapon_set_flags`."""
        ProductionConditionPatch(weapon_set_flag=WEAPON_FLAG).apply(image)
        off = va_to_offset(image, weapon_set_flags.BIT_COUNT_VA)
        assert bytes(image[off : off + 4]) == weapon_set_flags.BIT_COUNT_BYTES

    def test_the_mask_constant_names_exactly_the_new_flag(self, image: bytearray):
        ProductionConditionPatch(weapon_set_flag=WEAPON_FLAG).apply(image)
        bit = weapon_set_flags.read(image).index_of(image, WEAPON_FLAG)
        blob = weapon_set_flags.mask_bytes(bit)
        words = struct.unpack(f"<{weapon_set_flags.MASK_DWORDS}I", blob)
        assert sum(bin(word).count("1") for word in words) == 1
        assert words[bit // 32] == 1 << (bit % 32)
        base_va, off, vsize = find_section(image, _SECTION_NAME)
        assert blob in bytes(image[off : off + vsize]), "the constant must live in the cave"

    def test_a_name_already_in_the_table_is_refused(self, image: bytearray):
        with pytest.raises(ValueError, match="already weapon set flag"):
            ProductionConditionPatch(weapon_set_flag="VETERAN").apply(image)
        with pytest.raises(ValueError, match="already locomotor set"):
            ProductionConditionPatch(locomotor_set="SET_NORMAL").apply(image)

    def test_a_refused_name_leaves_the_image_untouched(self, clean: bytearray):
        """The optional tables are checked before anything is written, so a name clash is not a
        half-applied patch."""
        image = bytearray(clean)
        with pytest.raises(ValueError, match="already locomotor set"):
            ProductionConditionPatch(locomotor_set="SET_NORMAL").apply(image)
        assert image == clean

    def test_applying_twice_raises_rather_than_corrupting(self, image: bytearray):
        patch = ProductionConditionPatch(weapon_set_flag=WEAPON_FLAG, locomotor_set=LOCOMOTOR_SET)
        patch.apply(image)
        with pytest.raises(ValueError):
            patch.apply(image)

    def test_verify_notices_a_tampered_mask_constant(self, image: bytearray):
        patch = ProductionConditionPatch(weapon_set_flag=WEAPON_FLAG)
        patch.apply(image)
        blob = weapon_set_flags.mask_bytes(
            weapon_set_flags.read(image).index_of(image, WEAPON_FLAG)
        )
        _base_va, off, vsize = find_section(image, _SECTION_NAME)
        at = bytes(image[off : off + vsize]).index(blob)
        image[off + at] ^= 0xFF
        assert any("mask constant" in problem for problem in patch.verify(image))

    def test_verify_notices_a_table_ref_left_behind(self, image: bytearray):
        patch = ProductionConditionPatch(locomotor_set=LOCOMOTOR_SET)
        patch.apply(image)
        va = locomotor_sets.TABLE_REF_VAS[0]
        struct.pack_into("<I", image, va_to_offset(image, va), locomotor_sets.NAME_TABLE_VA)
        assert any("locomotor-set name table ref" in problem for problem in patch.verify(image))

    def test_verify_rejects_an_image_carrying_only_the_condition(self, image: bytearray):
        """Asking whether the extras are installed has to be answered by the image, not by the
        arguments `verify` was constructed with."""
        ProductionConditionPatch().apply(image)
        assert ProductionConditionPatch(weapon_set_flag=WEAPON_FLAG).verify(image) != []


class TestNameValidation:
    @pytest.mark.parametrize("bad", ["", "lower", "1LEADING", "HAS SPACE", "HAS-DASH", "Mixed"])
    def test_it_rejects_names_the_ini_parser_could_never_match(self, bad: str):
        with pytest.raises(ValueError, match="condition name"):
            ProductionConditionPatch(condition=bad)

    def test_it_rejects_a_name_that_is_already_a_model_condition(self, image: bytearray):
        with pytest.raises(ValueError, match="already model condition"):
            ProductionConditionPatch(condition="JUST_BUILT").apply(image)

    def test_the_chosen_name_reaches_the_cave(self, image: bytearray):
        ProductionConditionPatch(condition="TRAINING_OR_RESEARCHING").apply(image)
        base_va, off, _vsize = find_section(image, _SECTION_NAME)
        assert b"TRAINING_OR_RESEARCHING\x00" in bytes(image[off : off + 0xA00])
