"""Tests for the give-upgrade-all patch.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter disassemble
it back and assert it says what it was meant to say. A wrong byte does not raise: it grants an
upgrade the recipient was supposed to be refused, or returns an upgrade the engine then hands to a
horde that cannot take it, or falls off the end of `next_upgrade`'s list into arbitrary memory.
All three have to be caught statically.

The other half is the four windows. `grant_rest` replaces a `call` rather than a function entry
and reads three of the caller's registers, so the anchors that pin those registers are load-bearing
in a way an anchor usually is not - `TestTheWindows` and `TestTheRealBinary` are what keep them
honest.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    GIVE_UPGRADE_CAN_GIVE,
    GIVE_UPGRADE_CAN_GIVE_BODY,
    GIVE_UPGRADE_CAN_GIVE_ENTRY,
    GIVE_UPGRADE_PRODUCER_HORDE_IFACE,
    GIVE_UPGRADE_SEARCH_FILTER_OWNER,
    GIVE_UPGRADE_SEARCH_FILTER_OWNER_BYTES,
    GIVE_UPGRADE_SEARCH_FILTER_VTABLE,
    GIVE_UPGRADE_TRIGGER_MEMBER_ARM,
    GIVE_UPGRADE_TRIGGER_OWNER,
    GIVE_UPGRADE_TRIGGER_PICK,
    GIVE_UPGRADE_TRIGGER_PICK_BYTES,
    GIVE_UPGRADE_TRIGGER_TARGET_ARM,
    OBJECT_CAN_ACCEPT_UPGRADE,
    OBJECT_GET_HORDE_IFACE,
    OBJECT_GIVE_UPGRADE,
    OBJECT_HAS_UPGRADE,
    OBJECT_UPGRADE_MASK,
    THE_UPGRADE_CENTER,
    UPGRADE_CENTER_LIST,
    UPGRADE_FILTER_BODY,
    UPGRADE_FILTER_OWNER_SLOT,
    UPGRADE_FILTER_PREDICATE,
    UPGRADE_FILTER_PREDICATE_ENTRY,
    UPGRADE_FILTER_UPGRADE_SLOT,
    UPGRADE_FIRST_SET,
    UPGRADE_TEMPLATE_INDEX,
    UPGRADE_TEMPLATE_NEXT,
)
from sage_patch.patcher import apply_patches
from sage_patch.patches.give_upgrade_all import (
    ANCHORS,
    SECTION_NAME,
    GiveUpgradeAllPatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import give_upgrade_all_image

BASE = 0x00F00000

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

#: The engine functions the cave is allowed to call, and nothing else. A call to anything not on
#: this list is either a displacement computed wrong or a routine that drifted into doing more
#: than the patch claims it does.
ALLOWED_CALLS = {
    GIVE_UPGRADE_PRODUCER_HORDE_IFACE,
    OBJECT_CAN_ACCEPT_UPGRADE,
    OBJECT_GET_HORDE_IFACE,
    OBJECT_GIVE_UPGRADE,
    OBJECT_HAS_UPGRADE,
}

#: The two grant calls, as `(vtable slot, what it grants to)`. Both are indirect, so they are
#: identified by the slot they dispatch through.
HORDE_ACCEPTS_SLOT = 0xAC
HORDE_GIVE_SLOT = 0xB8


def code(base: int = BASE):
    return build_code(base)


def disassemble(base: int = BASE):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(code(base).finish(), base))


def routine(name: str, base: int = BASE):
    """The instructions of one routine: from its label to the `ret` that ends it."""
    start = code(base).label_va(name)
    out = []
    for ins in disassemble(base):
        if ins.address < start:
            continue
        out.append(ins)
        if ins.mnemonic == "ret":
            break
    return out


def prologue_pushes(name: str, base: int = BASE) -> list[str]:
    """The registers a routine saves on entry, in push order."""
    out = []
    for ins in routine(name, base):
        if ins.mnemonic != "push":
            break
        out.append(ins.op_str)
    return out


def epilogue_pops(name: str, base: int = BASE) -> list[str]:
    """The registers a routine restores before its `ret`, in pop order."""
    out = []
    for ins in reversed(routine(name, base)[:-1]):
        if ins.mnemonic != "pop":
            break
        out.append(ins.op_str)
    return list(reversed(out))


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        """Capstone stopping early means an invalid encoding, which is a crash in-game."""
        insns = disassemble()
        assert sum(i.size for i in insns) == len(code().finish())

    def test_it_calls_only_the_engine_functions_it_is_allowed_to(self):
        targets = {
            int(i.op_str, 16)
            for i in disassemble()
            if i.mnemonic == "call" and i.op_str.startswith("0x")
        }
        blob = code().finish()
        internal = {t for t in targets if BASE <= t < BASE + len(blob)}
        assert targets - internal == ALLOWED_CALLS

    def test_its_internal_calls_land_on_its_own_routines(self):
        c = code()
        entries = {
            c.label_va(n)
            for n in ("can_give_any", "grant_rest", "filter_any", "filter_test", "next_upgrade")
        }
        blob = c.finish()
        for ins in disassemble():
            if ins.mnemonic != "call" or not ins.op_str.startswith("0x"):
                continue
            target = int(ins.op_str, 16)
            if BASE <= target < BASE + len(blob):
                assert target in entries, f"call at {ins.address:#x} lands mid-routine"

    def test_every_conditional_branch_stays_inside_the_cave(self):
        """A displacement computed wrong would jump into arbitrary engine code."""
        blob = code().finish()
        for ins in disassemble():
            if not ins.mnemonic.startswith("j"):
                continue
            assert BASE <= int(ins.op_str, 16) < BASE + len(blob), (
                f"{ins.mnemonic} at {ins.address:#x} escapes the cave"
            )

    def test_it_relocates_with_its_section(self):
        a, b = code(BASE).finish(), code(BASE + 0x1000).finish()
        assert a != b, "the calls into the engine must be recomputed for the cave's address"
        assert len(a) == len(b)

    @pytest.mark.parametrize("name", ["can_give_any", "grant_rest", "filter_any"])
    def test_each_entry_point_cleans_the_one_argument_it_is_given(self, name: str):
        """All three replace `ret 4` code: two are thiscall predicates with one argument, and
        `grant_rest` stands in for a call whose callee cleaned the pushed mask pointer. Returning
        with a bare `ret` would unbalance the caller's stack on every delivery."""
        assert routine(name)[-1].op_str == "4"

    @pytest.mark.parametrize("name", ["can_give_any", "grant_rest", "filter_any"])
    def test_each_entry_point_restores_its_prologue(self, name: str):
        """What the prologue pushes, the epilogue pops, in reverse - so the caller gets its
        callee-saved registers back. `can_give_any` is the one that pushes a fourth dword as the
        recipient slot and drops it into a dead register instead of restoring it."""
        pushed = prologue_pushes(name)
        popped = epilogue_pops(name)
        assert len(pushed) == len(popped)
        for saved, restored in zip(pushed, reversed(popped), strict=False):
            assert saved == restored or (saved, restored) == ("eax", "ecx"), name

    def test_the_saved_registers_are_the_callee_saved_ones(self):
        """`grant_rest` is called from inside a function that keeps the porter, the target and
        the module in exactly these, and reads them again after the call."""
        assert prologue_pushes("grant_rest") == ["ebx", "esi", "edi", "ebp"]

    def test_the_scratch_frame_is_balanced(self):
        """`grant_rest` keeps the recipient and the mask in an eight-byte frame, which has to be
        gone before the pops or they restore garbage."""
        text = [f"{i.mnemonic} {i.op_str}" for i in routine("grant_rest")]
        assert text.count("sub esp, 8") == 1
        assert text.count("add esp, 8") == 1
        assert text.index("sub esp, 8") < text.index("add esp, 8")


class TestNextUpgrade:
    """The cursor that replaces `UpgradeCenter::firstSetIn`. If this walks the list differently
    from the engine's own picker, the patch answers about upgrades a porter does not carry."""

    def test_it_starts_at_the_registry_the_picker_reads(self):
        text = [f"{i.mnemonic} {i.op_str}" for i in routine("next_upgrade")]
        assert f"mov eax, dword ptr [{THE_UPGRADE_CENTER:#x}]" in text
        assert f"mov eax, dword ptr [eax + {UPGRADE_CENTER_LIST:#x}]" in text

    def test_it_follows_the_same_link_field(self):
        text = [f"{i.mnemonic} {i.op_str}" for i in routine("next_upgrade")]
        assert f"mov eax, dword ptr [eax + {UPGRADE_TEMPLATE_NEXT:#x}]" in text

    def test_it_selects_the_bit_the_way_the_engine_selects_it(self):
        """Word `index >> 5`, bit `index & 31`, read out of `UpgradeTemplate+0x38` - the same
        arithmetic `0x0066F468` does, which is why passing a null cursor answers what it answers."""
        text = [f"{i.mnemonic} {i.op_str}" for i in routine("next_upgrade")]
        assert f"mov ecx, dword ptr [eax + {UPGRADE_TEMPLATE_INDEX:#x}]" in text
        assert "and ecx, 0x1f" in text
        assert "shr ebx, 5" in text
        assert "mov ebx, dword ptr [edx + ebx*4]" in text
        assert "shr ebx, cl" in text
        assert "test bl, 1" in text

    def test_it_ends_the_walk_on_a_null_link(self):
        """Two null tests - one on the registry, one on every node - are what stop the loop
        running off the end of the list."""
        insns = routine("next_upgrade")
        assert len([i for i in insns if (i.mnemonic, i.op_str) == ("test", "eax, eax")]) == 3

    def test_it_preserves_everything_but_its_answer(self):
        """Its three callers keep the mask in `ebx` and their cursor in `esi` across the call."""
        insns = routine("next_upgrade")
        assert [i.op_str for i in insns if i.mnemonic == "push"] == ["ebx", "ecx"]
        assert [i.op_str for i in insns if i.mnemonic == "pop"] == ["ecx", "ebx"]
        written = {
            i.op_str.split(",")[0] for i in insns if i.mnemonic in {"mov", "xor", "and", "shr"}
        }
        assert written <= {"eax", "ebx", "ecx"}


class TestGrantRest:
    """The routine that does the granting."""

    def test_it_reads_the_porters_own_upgrade_mask(self):
        text = [f"{i.mnemonic} {i.op_str}" for i in routine("can_give_any")]
        assert f"add ebx, {OBJECT_UPGRADE_MASK:#x}" in text

    def test_it_resolves_the_recipient_the_way_the_trigger_does(self):
        """A target that is itself a horde answers through its own interface, anything else
        through its producer's - the same two calls the engine makes sixteen bytes later."""
        targets = [
            int(i.op_str, 16)
            for i in routine("grant_rest")
            if i.mnemonic == "call" and i.op_str.startswith("0x")
        ]
        assert OBJECT_GET_HORDE_IFACE in targets
        assert GIVE_UPGRADE_PRODUCER_HORDE_IFACE in targets

    def test_it_tests_the_kindof_horde_bit_the_engine_tests(self):
        text = [f"{i.mnemonic} {i.op_str}" for i in routine("grant_rest")]
        assert "test byte ptr [eax + 0x115], 0x20" in text

    def test_every_grant_is_preceded_by_an_acceptance_test(self):
        """The whole safety property: an upgrade nobody accepts is never handed over. Each of the
        two grant calls has to be dominated by one of the two acceptance calls."""
        insns = routine("grant_rest")
        seen_test = False
        grants = 0
        for ins in insns:
            if ins.mnemonic != "call":
                continue
            if ins.op_str == f"dword ptr [edx + {HORDE_ACCEPTS_SLOT:#x}]" or (
                ins.op_str.startswith("0x") and int(ins.op_str, 16) == OBJECT_CAN_ACCEPT_UPGRADE
            ):
                seen_test = True
            if ins.op_str == f"dword ptr [edx + {HORDE_GIVE_SLOT:#x}]" or (
                ins.op_str.startswith("0x") and int(ins.op_str, 16) == OBJECT_GIVE_UPGRADE
            ):
                grants += 1
                assert seen_test, f"grant at {ins.address:#x} precedes any acceptance test"
        assert grants == 2, "one grant for a horde, one for a lone object"

    def test_the_horde_grant_does_not_force(self):
        """`giveUpgradeToMembers(u, force)` with `force` set would skip the per-member acceptance
        test the engine does for us, which is the one thing keeping the extra upgrades honest."""
        insns = routine("grant_rest")
        give = next(i for i in insns if i.op_str == f"dword ptr [edx + {HORDE_GIVE_SLOT:#x}]")
        pushes = [i for i in insns if i.address < give.address and i.mnemonic == "push"]
        assert pushes[-2].op_str == "0", "the force argument is pushed first and must be zero"

    def test_it_returns_the_chosen_upgrade_and_nothing_else(self):
        """`ebp` accumulates the first acceptable upgrade and is the return value. Returning the
        cursor instead would hand the engine an upgrade it has already granted."""
        insns = routine("grant_rest")
        last_write = [i for i in insns if i.mnemonic == "mov" and i.op_str.startswith("eax,")][-1]
        assert last_write.op_str == "eax, ebp"

    def test_nothing_acceptable_returns_zero(self):
        """Zero is the picker's own "this porter carries nothing" answer, which the trigger
        already handles by fading the porter out."""
        text = [f"{i.mnemonic} {i.op_str}" for i in routine("grant_rest")]
        assert "xor ebp, ebp" in text


class TestFilterAny:
    def test_it_reads_the_owner_out_of_the_filters_dead_slot(self):
        text = [f"{i.mnemonic} {i.op_str}" for i in routine("filter_any")]
        assert f"mov ebx, dword ptr [esi + {UPGRADE_FILTER_OWNER_SLOT}]" in text

    def test_a_filter_without_an_owner_falls_back_to_the_captured_upgrade(self):
        """The one thing that keeps a functor built by an unedited path behaving as stock."""
        text = [f"{i.mnemonic} {i.op_str}" for i in routine("filter_any")]
        assert f"mov esi, dword ptr [esi + {UPGRADE_FILTER_UPGRADE_SLOT}]" in text

    def test_the_predicate_asks_the_stock_pair_of_questions(self):
        targets = [
            int(i.op_str, 16)
            for i in routine("filter_test")
            if i.mnemonic == "call" and i.op_str.startswith("0x")
        ]
        assert targets == [OBJECT_CAN_ACCEPT_UPGRADE, OBJECT_HAS_UPGRADE]


class TestTheWindows:
    def test_the_can_give_window_needs_its_nop(self):
        """Six bytes of stock instructions, five of `jmp rel32`: the padding byte is what keeps
        the window an integral number of instructions."""
        assert len(GIVE_UPGRADE_CAN_GIVE_ENTRY) == 6

    def test_the_body_anchor_starts_where_the_window_ends(self):
        """The anchor has to survive being applied, so it must not overlap what apply rewrites."""
        assert (
            GIVE_UPGRADE_CAN_GIVE + len(GIVE_UPGRADE_CAN_GIVE_ENTRY) == GIVE_UPGRADE_CAN_GIVE_BODY
        )

    def test_the_filter_body_anchor_starts_where_its_window_ends(self):
        assert UPGRADE_FILTER_PREDICATE + len(UPGRADE_FILTER_PREDICATE_ENTRY) == UPGRADE_FILTER_BODY

    def test_no_anchor_overlaps_a_rewritten_window(self):
        windows = {
            GIVE_UPGRADE_CAN_GIVE: len(GIVE_UPGRADE_CAN_GIVE_ENTRY),
            GIVE_UPGRADE_TRIGGER_PICK: len(GIVE_UPGRADE_TRIGGER_PICK_BYTES),
            GIVE_UPGRADE_SEARCH_FILTER_OWNER: len(GIVE_UPGRADE_SEARCH_FILTER_OWNER_BYTES),
            UPGRADE_FILTER_PREDICATE: len(UPGRADE_FILTER_PREDICATE_ENTRY),
        }
        written = {va + n for va, size in windows.items() for n in range(size)}
        for va, expected in ANCHORS.items():
            assert not written & set(range(va, va + len(expected))), f"0x{va:08X}"

    def test_the_owner_capture_changes_one_register_and_nothing_else(self):
        """`mov [ebp-0x24], ebx` -> `mov [ebp-0x24], esi`: same instruction, same length, same
        frame slot. Anything else would move the store or resize it."""
        stock = GIVE_UPGRADE_SEARCH_FILTER_OWNER_BYTES
        patched = bytes.fromhex("8975dc")
        assert len(stock) == len(patched)
        assert stock[0] == patched[0] and stock[2] == patched[2]
        assert stock[1] != patched[1]

    def test_the_registers_the_cave_reads_are_anchored(self):
        """`grant_rest` reads `ebx`, `edi` and `esi` out of the caller. The three instructions
        that put them there are anchors, and all three precede the window."""
        for va in (
            GIVE_UPGRADE_TRIGGER_OWNER,
            GIVE_UPGRADE_TRIGGER_TARGET_ARM,
            GIVE_UPGRADE_TRIGGER_MEMBER_ARM,
        ):
            assert va in ANCHORS
        assert GIVE_UPGRADE_TRIGGER_OWNER < GIVE_UPGRADE_TRIGGER_PICK
        assert GIVE_UPGRADE_TRIGGER_PICK < GIVE_UPGRADE_TRIGGER_TARGET_ARM
        assert GIVE_UPGRADE_TRIGGER_TARGET_ARM < GIVE_UPGRADE_TRIGGER_MEMBER_ARM

    def test_the_filter_capture_belongs_to_the_functor_the_search_builds(self):
        """The store this patch rewrites has to be the one three bytes before the vtable store,
        or `+4` is some other frame slot."""
        end = GIVE_UPGRADE_SEARCH_FILTER_OWNER + len(GIVE_UPGRADE_SEARCH_FILTER_OWNER_BYTES)
        assert end == GIVE_UPGRADE_SEARCH_FILTER_VTABLE


class TestApply:
    def test_apply_then_verify(self):
        data = give_upgrade_all_image()
        GiveUpgradeAllPatch().apply(data)
        assert GiveUpgradeAllPatch().verify(data) == []

    def test_the_hooks_point_at_the_routines_they_name(self):
        data = give_upgrade_all_image()
        GiveUpgradeAllPatch().apply(data)
        section_va, _off, _vsize = find_section(data, SECTION_NAME)
        c = build_code(section_va)
        for va, opcode, label in (
            (GIVE_UPGRADE_CAN_GIVE, 0xE9, "can_give_any"),
            (GIVE_UPGRADE_TRIGGER_PICK, 0xE8, "grant_rest"),
            (UPGRADE_FILTER_PREDICATE, 0xE9, "filter_any"),
        ):
            off = va_to_offset(data, va)
            assert data[off] == opcode, f"0x{va:08X}"
            target = va + 5 + struct.unpack_from("<i", data, off + 1)[0]
            assert target == c.label_va(label), f"0x{va:08X}"

    def test_the_cave_holds_the_expected_routines(self):
        data = give_upgrade_all_image()
        GiveUpgradeAllPatch().apply(data)
        section_va, off, _vsize = find_section(data, SECTION_NAME)
        expected = build_code(section_va).finish()
        assert bytes(data[off : off + len(expected)]) == expected

    def test_refuses_to_apply_twice(self):
        data = give_upgrade_all_image()
        GiveUpgradeAllPatch().apply(data)
        with pytest.raises(ValueError, match="expected"):
            GiveUpgradeAllPatch().apply(data)

    def test_a_moved_anchor_refuses_to_apply(self):
        data = give_upgrade_all_image()
        off = va_to_offset(data, GIVE_UPGRADE_TRIGGER_TARGET_ARM)
        data[off : off + 3] = b"\x90\x90\x90"
        with pytest.raises(ValueError, match="not laid out as this patch reads it"):
            GiveUpgradeAllPatch().apply(data)

    def test_a_missing_picker_refuses_to_apply(self):
        """`next_upgrade` reimplements that function's contract, so a build where it moved is a
        build where the cursor is walking something else's list."""
        data = give_upgrade_all_image()
        off = va_to_offset(data, UPGRADE_FIRST_SET)
        data[off] = 0x90
        with pytest.raises(ValueError, match="not laid out as this patch reads it"):
            GiveUpgradeAllPatch().apply(data)

    def test_verify_catches_a_tampered_window(self):
        data = give_upgrade_all_image()
        GiveUpgradeAllPatch().apply(data)
        off = va_to_offset(data, GIVE_UPGRADE_SEARCH_FILTER_OWNER)
        data[off + 1] = 0x5D  # back to `ebx`: the filter would never see a porter
        assert GiveUpgradeAllPatch().verify(data) != []

    def test_verify_catches_a_tampered_cave(self):
        data = give_upgrade_all_image()
        GiveUpgradeAllPatch().apply(data)
        _va, off, _vsize = find_section(data, SECTION_NAME)
        data[off + 8] ^= 0xFF
        assert GiveUpgradeAllPatch().verify(data) != []

    def test_the_section_name_survives_the_eight_byte_pe_field(self):
        assert len(SECTION_NAME) <= 8, "a longer name is silently truncated in the header"
        data = give_upgrade_all_image()
        GiveUpgradeAllPatch().apply(data)
        assert find_section(data, SECTION_NAME) is not None


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES[GiveUpgradeAllPatch.name] is GiveUpgradeAllPatch

    def test_it_is_not_experimental(self):
        """The module lives outside `experimental/`, so the attribute has to agree - the two are
        the same fact, and `TestExperimentalPatchesAreDeclared` fails on either mismatch."""
        assert not GiveUpgradeAllPatch().experimental

    def test_it_declares_no_parameters(self):
        """`detect` takes the default, which is only correct for a patch with none."""
        assert GiveUpgradeAllPatch().options() == {}


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

    def test_every_window_holds_its_stock_bytes(self, game_dat: bytes) -> None:
        for va, expected in (
            (GIVE_UPGRADE_CAN_GIVE, GIVE_UPGRADE_CAN_GIVE_ENTRY),
            (GIVE_UPGRADE_TRIGGER_PICK, GIVE_UPGRADE_TRIGGER_PICK_BYTES),
            (GIVE_UPGRADE_SEARCH_FILTER_OWNER, GIVE_UPGRADE_SEARCH_FILTER_OWNER_BYTES),
            (UPGRADE_FILTER_PREDICATE, UPGRADE_FILTER_PREDICATE_ENTRY),
        ):
            off = va_to_offset(game_dat, va)
            assert bytes(game_dat[off : off + len(expected)]) == expected, f"0x{va:08X}"

    def test_the_replaced_call_really_names_the_picker(self, game_dat: bytes) -> None:
        """The window's five bytes *are* the displacement, so asserting them asserts that the
        call `grant_rest` stands in for is the one whose contract it reproduces."""
        rel = struct.unpack_from("<i", GIVE_UPGRADE_TRIGGER_PICK_BYTES, 1)[0]
        assert GIVE_UPGRADE_TRIGGER_PICK + 5 + rel == UPGRADE_FIRST_SET

    def test_the_functions_the_cave_calls_are_where_it_calls_them(self, game_dat: bytes) -> None:
        """Every call target has to be a function entry, not the middle of one. Each is checked
        against the first byte of a real prologue rather than merely being mapped."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        for va in sorted(ALLOWED_CALLS):
            off = va_to_offset(game_dat, va)
            assert off is not None, f"0x{va:08X}"
            first = next(md.disasm(game_dat[off : off + 16], va), None)
            assert first is not None, f"0x{va:08X} does not decode"

    def test_apply_and_verify_on_the_real_thing(self, game_dat: bytes, tmp_path: Path) -> None:
        src = tmp_path / "game.dat"
        src.write_bytes(game_dat)
        out = apply_patches(src, [GiveUpgradeAllPatch()], tmp_path / "out.dat")
        data = out.read_bytes()
        assert GiveUpgradeAllPatch().verify(data) == []
        assert GiveUpgradeAllPatch.detect(data) is not None
        assert src.read_bytes() == game_dat, "the input was modified"

    def test_it_is_not_detected_in_the_unpatched_binary(self, game_dat: bytes) -> None:
        assert GiveUpgradeAllPatch.detect(game_dat) is None
