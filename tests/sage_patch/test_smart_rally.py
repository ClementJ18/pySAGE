"""Tests for `smart-rally`, which lets a structure's rally point name a hero or a unit.

Nothing here can be executed, so the four things that would be silent in-game failures are all
checked statically.

The first is the **size ordering**. The patch writes a dword at interface ``+0x24``, which is four
bytes past the end of a stock `QueueProductionExitUpdate` and inside a grown one. If the allocation
edit were dropped, reordered after a hook, or aimed at some other class's `push`, every rally order
in the game would scribble on the heap. The invariant is asserted directly, and `verify` is
required to fail when the size is stock.

The second is the **class discrimination**. `Object::getExitInterface` answers with three other
classes and a contain module, and on all of them ``+0x24`` belongs to somebody else. The record
routine is disassembled back and the vtable comparison is required to sit ahead of the store.

The third is the **stack contract**. The cave displaces two epilogues and one `__cdecl` call
sequence: the clear routine has to issue its own ``ret 4``, the constructor routine its own
``ret 8``, and the record routine has to reproduce the four-argument call *and* drop the object it
stashed on every edge out. A routine that cleans the wrong number of bytes returns into the middle
of its caller's frame.

The fourth is the **build fingerprint**. The patch rewrites five windows and reads fourteen more it
does not rewrite; every one has to fail loudly on anything else.
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

import pytest

from sage_ini.engine import STOCK
from sage_patch import apply_patches
from sage_patch.patches.ai_construction_gate import AiConstructionGatePatch
from sage_patch.patches.experimental.smart_rally import (
    AI_GUARD_OBJECT,
    AI_GUARD_TARGET_OFFSET,
    AI_MOVE_TO_POSITION,
    ALLOC_SIZE_PATCHED,
    ALLOC_SIZE_STOCK,
    ALLOC_SIZE_VA,
    ANCHORS,
    CLEAR_HOOK_VA,
    COMMAND_FROM_AI,
    COMMAND_FROM_PLAYER,
    CTOR_HOOK_VA,
    EXIT_PATH_SLOT,
    EXIT_VTABLE,
    FIND_OBJECT_BY_ID,
    GET_EXIT_INTERFACE,
    GET_RELATIONSHIP,
    GUARD_MODE_NORMAL,
    MARKER_HOOK_STOCK,
    MARKER_HOOK_VAS,
    OBJECT_ID_OFFSET,
    OBJECT_POSITION_OFFSET,
    PATCHED_MODULE_SIZE,
    RECORD_HOOK_VA,
    RECORD_RESUME_VA,
    RELATIONSHIP_ALLIED,
    RELEASE_UNIT,
    SECTION_NAME,
    SET_RALLY_POINT_FOR,
    SET_RALLY_POSITION,
    SPEND_FALLBACK_VA,
    SPEND_HOOK_STOCK,
    SPEND_HOOK_VA,
    SPEND_RESUME_VA,
    STOCK_MODULE_SIZE,
    TARGET_ID_OFFSET,
    SmartRallyPatch,
    build_code,
    entry_points,
)
from sage_patch.patches.spawn_union import SpawnUnionPatch
from sage_patch.patches.wall_mesh_release import WallMeshReleasePatch
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import smart_rally_image

BASE = 0x00F00000

#: Each hook, with the routine it must reach and the branch opcode that reaches it. The marker
#: sites are `call` rather than `jmp`, which is what lets one routine `ret` into either of them.
HOOKS = (
    (CTOR_HOOK_VA, "ctor_tail", 0xE9),
    (CLEAR_HOOK_VA, "clear", 0xE9),
    (RECORD_HOOK_VA, "record", 0xE9),
    (SPEND_HOOK_VA, "spend", 0xE9),
    (MARKER_HOOK_VAS[0], "marker", 0xE8),
    (MARKER_HOOK_VAS[1], "marker", 0xE8),
)


@pytest.fixture
def image() -> bytearray:
    return smart_rally_image()


def _patched(image: bytearray, guard: bool = False) -> bytearray:
    data = bytearray(image)
    SmartRallyPatch(guard=guard).apply(data)
    return data


def _disassemble(guard: bool = False, base: int = BASE):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(build_code(base, guard), base))


def _routine(name: str, guard: bool = False, base: int = BASE):
    """The instructions of one cave routine: from its entry to the next routine's, or the end."""
    starts = sorted(entry_points(base, guard).values())
    entry = entry_points(base, guard)[name]
    end = next((s for s in starts if s > entry), base + len(build_code(base, guard)))
    return [i for i in _disassemble(guard, base) if entry <= i.address < end]


def _text(insns) -> list[str]:
    return [f"{i.mnemonic} {i.op_str}".strip() for i in insns]


def _hook_target(data: bytes | bytearray, va: int, opcode: int) -> int:
    off = va_to_offset(data, va)
    assert off is not None
    assert data[off] == opcode, f"{va:#010x} does not branch with {opcode:#x}"
    return va + 5 + struct.unpack_from("<i", data, off + 1)[0]


# --- round trip ---------------------------------------------------------------------------------


@pytest.mark.parametrize("guard", [False, True])
def test_apply_then_verify(image: bytearray, guard: bool) -> None:
    assert SmartRallyPatch(guard=guard).verify(_patched(image, guard)) == []


def test_verify_rejects_an_unpatched_image(image: bytearray) -> None:
    problems = SmartRallyPatch().verify(image)
    assert problems and SECTION_NAME in problems[0]


@pytest.mark.parametrize("guard", [False, True])
def test_detect_recovers_the_order_form(image: bytearray, guard: bool) -> None:
    found = SmartRallyPatch.detect(_patched(image, guard))
    assert found is not None
    assert isinstance(found, SmartRallyPatch)
    assert found.guard is guard


def test_detect_returns_nothing_for_an_unpatched_image(image: bytearray) -> None:
    assert SmartRallyPatch.detect(image) is None


def test_the_two_forms_do_not_verify_as_each_other(image: bytearray) -> None:
    """`detect` picks between them by asking `verify`, so they have to be distinguishable."""
    assert SmartRallyPatch(guard=True).verify(_patched(image, guard=False))
    assert SmartRallyPatch(guard=False).verify(_patched(image, guard=True))


def test_apply_is_idempotent_only_once(image: bytearray) -> None:
    data = _patched(image)
    with pytest.raises(ValueError):
        SmartRallyPatch().apply(data)


def test_apply_patches_writes_a_file(image: bytearray, tmp_path) -> None:
    src, out = tmp_path / "game.dat.backup", tmp_path / "game.dat"
    src.write_bytes(bytes(image))
    apply_patches(src, [SmartRallyPatch()], output=out)
    assert SmartRallyPatch().verify(out.read_bytes()) == []
    assert src.read_bytes() == bytes(image)  # the input is never modified


def test_the_patch_is_registered_and_attributed() -> None:
    assert PATCHES[SmartRallyPatch.name] is SmartRallyPatch
    assert SmartRallyPatch.author


def test_it_adds_no_ini_surface() -> None:
    assert SmartRallyPatch().ini_surface() is STOCK


def test_the_cli_round_trips_the_order_form() -> None:
    parser = argparse.ArgumentParser()
    SmartRallyPatch.add_cli_arguments(parser)
    assert SmartRallyPatch.from_cli_args(parser.parse_args([])).guard is False  # type: ignore[attr-defined]
    assert SmartRallyPatch.from_cli_args(parser.parse_args(["--guard"])).guard is True  # type: ignore[attr-defined]
    assert "guard" in str(SmartRallyPatch(guard=True))
    assert "guard" not in str(SmartRallyPatch())


# --- the size, which every other edit depends on ------------------------------------------------


class TestTheGrownModule:
    def test_the_field_lies_outside_a_stock_module(self) -> None:
        """Interface ``+0x24`` is module ``+0x44``: past the stock object, inside the grown one."""
        module_offset = 0x20 + TARGET_ID_OFFSET
        assert module_offset >= STOCK_MODULE_SIZE
        assert module_offset + 4 <= PATCHED_MODULE_SIZE

    def test_apply_grows_the_allocation(self, image: bytearray) -> None:
        data = _patched(image)
        off = va_to_offset(data, ALLOC_SIZE_VA)
        assert off is not None
        assert bytes(data[off : off + 2]) == ALLOC_SIZE_PATCHED

    def test_verify_fails_when_the_allocation_is_stock(self, image: bytearray) -> None:
        """The one failure that would corrupt the heap rather than merely misbehave."""
        data = _patched(image)
        off = va_to_offset(data, ALLOC_SIZE_VA)
        assert off is not None
        data[off : off + 2] = ALLOC_SIZE_STOCK
        problems = SmartRallyPatch().verify(data)
        assert any("past the module" in problem for problem in problems)

    def test_the_constructor_zeroes_the_new_field(self) -> None:
        first = _routine("ctor_tail")[0]
        assert (first.mnemonic, first.op_str) == ("and", "dword ptr [esi + 0x44], 0")


# --- the cave ------------------------------------------------------------------------------------


class TestTheCave:
    @pytest.mark.parametrize("guard", [False, True])
    def test_it_disassembles_cleanly_to_its_end(self, guard: bool) -> None:
        """Capstone stopping early means an invalid encoding, which is a crash in-game."""
        insns = _disassemble(guard)
        assert sum(i.size for i in insns) == len(build_code(BASE, guard))

    @pytest.mark.parametrize(("hook_va", "routine", "opcode"), HOOKS)
    def test_each_hook_reaches_its_routine(
        self, image: bytearray, hook_va: int, routine: str, opcode: int
    ) -> None:
        data = _patched(image)
        located = find_section(data, SECTION_NAME)
        assert located is not None
        assert _hook_target(data, hook_va, opcode) == entry_points(located[0])[routine]

    def test_every_displaced_window_is_fully_covered(self, image: bytearray) -> None:
        """A five-byte branch into a longer window leaves stray bytes that decode as code."""
        data = _patched(image)
        for hook_va, _routine, _opcode in HOOKS:
            off = va_to_offset(data, hook_va)
            assert off is not None
            stock = ANCHORS[hook_va]
            assert bytes(data[off + 5 : off + len(stock)]) == b"\x90" * (len(stock) - 5)


class TestTheConstructorRoutine:
    def test_it_reproduces_the_epilogue_it_displaced(self) -> None:
        assert _text(_routine("ctor_tail"))[1:] == ["mov eax, esi", "pop esi", "ret 8"]


class TestTheClearRoutine:
    def test_it_reproduces_the_flag_it_displaced(self) -> None:
        assert _text(_routine("clear"))[0] == "mov byte ptr [ebx + 0x14], 1"

    def test_it_drops_the_target_whenever_a_position_is_stored(self) -> None:
        assert "and dword ptr [ebx + 0x24], 0" in _text(_routine("clear"))

    def test_it_cleans_its_own_argument(self) -> None:
        """Slot ``+0x1C`` is ``__thiscall`` with one argument, so the routine owns the `ret 4`."""
        assert _text(_routine("clear"))[-2:] == ["pop ebx", "ret 4"]


class TestTheRecordRoutine:
    def test_it_reproduces_the_four_argument_call_it_displaced(self) -> None:
        text = _text(_routine("record"))
        pushes = text[: text.index(f"call {SET_RALLY_POINT_FOR:#x}")]
        assert pushes == [
            "push eax",  # the target, stashed below the argument block
            "push ebx",
            "push 1",
            "lea eax, [ebp - 0x24]",
            "push eax",
            "push edi",
        ]
        assert text[text.index(f"call {SET_RALLY_POINT_FOR:#x}") + 1] == "add esp, 0x10"

    def test_it_checks_the_class_before_it_writes(self) -> None:
        """`getExitInterface` answers with classes on which ``+0x24`` is somebody else's field."""
        text = _text(_routine("record"))
        check = text.index(f"cmp dword ptr [eax], {EXIT_VTABLE:#x}")
        store = text.index(f"mov dword ptr [eax + {TARGET_ID_OFFSET:#x}], edx")
        assert check < store
        assert text.index(f"call {GET_EXIT_INTERFACE:#x}") < check

    def test_it_reads_the_target_id_from_the_object(self) -> None:
        assert f"mov edx, dword ptr [ecx + {OBJECT_ID_OFFSET:#x}]" in _text(_routine("record"))

    def test_a_ground_click_stores_zero(self) -> None:
        """Which is what clears a standing target: `xor edx, edx` is the value on the NULL edge."""
        text = _text(_routine("record"))
        assert text.index("xor edx, edx") < text.index(
            f"mov edx, dword ptr [ecx + {OBJECT_ID_OFFSET:#x}]"
        )

    def test_it_leaves_a_refused_rally_alone(self) -> None:
        """`SET_RALLY_POINT_FOR` answers in `al` and can say no; the store is behind that test."""
        text = _text(_routine("record"))
        assert text.index("test al, al") < text.index(f"call {GET_EXIT_INTERFACE:#x}")

    def test_every_edge_drops_the_stashed_object_exactly_once(self) -> None:
        """One stash in, one `add esp, 4` out, and a single exit for every branch to reach."""
        insns = _routine("record")
        text = _text(insns)
        assert text[0] == "push eax"  # the stash, before the reproduced argument block
        assert text.count("add esp, 4") == 1
        assert text[-2:] == ["add esp, 4", f"jmp {RECORD_RESUME_VA:#x}"]
        cleanup = insns[-2].address
        for insn in insns:
            if insn.mnemonic.startswith("j") and insn.mnemonic != "jmp":
                assert int(insn.op_str, 16) <= cleanup, f"{insn.mnemonic} skips the cleanup"


class TestTheSpendRoutine:
    def test_it_reads_the_target_from_the_interface(self) -> None:
        first = _routine("spend")[0]
        assert (first.mnemonic, first.op_str) == (
            "mov",
            f"eax, dword ptr [esi + {TARGET_ID_OFFSET:#x}]",
        )

    def test_it_resolves_the_target_and_survives_its_death(self) -> None:
        text = _text(_routine("spend"))
        assert f"call {FIND_OBJECT_BY_ID:#x}" in text
        # Two tests before the relationship call: an id of zero, and an id that no longer resolves.
        assert text.count("test eax, eax") == 2

    def test_it_requires_the_target_to_still_be_allied(self) -> None:
        text = _text(_routine("spend"))
        assert f"call {GET_RELATIONSHIP:#x}" in text
        assert f"cmp eax, {RELATIONSHIP_ALLIED}" in text

    def test_the_producer_is_who_the_relationship_is_asked_of(self) -> None:
        """Interface ``-0x18`` is the producing `Object *`, which is the `this` of the call."""
        text = _text(_routine("spend"))
        assert (
            text[text.index(f"call {GET_RELATIONSHIP:#x}") - 2] == "mov ecx, dword ptr [esi - 0x18]"
        )

    @pytest.mark.parametrize("guard", [False, True])
    def test_every_rejection_reproduces_what_it_displaced(self, guard: bool) -> None:
        """A rejected target has to cost nothing, and this hook displaces a whole call - so the
        reject edge replays all fifteen bytes and re-enters the stock arm after them."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        insns = _routine("spend", guard)
        text = _text(insns)
        stock = _text(list(md.disasm(SPEND_HOOK_STOCK, 0)))
        assert text[-len(stock) - 2 : -2] == stock
        assert text[-2:] == ["mov ecx, dword ptr [edi + 0x260]", f"jmp {SPEND_FALLBACK_VA:#x}"]

        reject = insns[-len(stock) - 2].address
        # The guard form has one more conditional - "the order took, skip the fallback order" -
        # which lands on the `jmp` that rejoins after the stock call, not on the reject edge.
        rejoin = next(i.address for i in insns if f"jmp {SPEND_RESUME_VA:#x}" == _text([i])[0])
        allowed = {reject, rejoin} if guard else {reject}
        for insn in insns:
            if insn.mnemonic in {"je", "jne"}:
                assert int(insn.op_str, 16) in allowed, f"{insn.mnemonic} at {insn.address:#x}"

    @pytest.mark.parametrize("guard", [False, True])
    def test_a_taken_target_suppresses_the_exit_path_call(self, guard: bool) -> None:
        """The whole point of hooking the arm's head rather than its tail. The engine's own
        rally-at-object arm never makes this call, and making it *and* issuing an object order
        gives the unit a second destination - which is what walked produced units to the target
        and then back to the stored rally point."""
        insns = _routine("spend", guard)
        text = _text(insns)
        exit_call = f"call dword ptr [eax + {EXIT_PATH_SLOT:#x}]"
        assert text.count(exit_call) == 1, "the displaced call is reproduced exactly once"
        # ...and only on the reject edge, which is past every order this routine issues.
        last_order = max(
            text.index(f"call {AI_MOVE_TO_POSITION:#x}"),
            text.index(f"call {AI_GUARD_OBJECT:#x}") if guard else -1,
        )
        assert text.index(exit_call) > last_order

    def test_the_guard_form_falls_back_when_the_order_is_refused(self) -> None:
        """`privateGuardObject` returns -1 having done nothing on any of its three gates, and the
        wrapper does not pass that back usably - so the cave reads the id the order would have
        recorded and gives the unit the move form when it is not the one we asked for. Without
        this the unit leaves the door with no order at all, which is what was seen in play."""
        text = _text(_routine("spend", guard=True))
        call_at = text.index(f"call {AI_GUARD_OBJECT:#x}")
        assert text[call_at + 1 : call_at + 4] == [
            "mov eax, dword ptr [edi + 0x260]",
            f"mov eax, dword ptr [eax + {AI_GUARD_TARGET_OFFSET:#x}]",
            f"cmp eax, dword ptr [ebx + {OBJECT_ID_OFFSET:#x}]",
        ]
        assert text[call_at + 4].startswith("je")

    def test_the_guard_fallback_is_the_move_form(self) -> None:
        """Identical to what the default form issues, so a refused guard degrades to the behaviour
        that works rather than to nothing."""
        guarded = _text(_routine("spend", guard=True))
        plain = _text(_routine("spend"))
        call = f"call {AI_MOVE_TO_POSITION:#x}"
        at_guard, at_plain = guarded.index(call), plain.index(call)
        assert guarded[at_guard - 4 : at_guard + 1] == plain[at_plain - 4 : at_plain + 1]

    def test_the_default_form_moves_to_the_target_position(self) -> None:
        text = _text(_routine("spend"))
        assert f"call {AI_MOVE_TO_POSITION:#x}" in text
        assert f"lea eax, [ebx + {OBJECT_POSITION_OFFSET:#x}]" in text
        assert f"call {AI_GUARD_OBJECT:#x}" not in text

    def test_the_guard_form_issues_the_engines_own_guard_order(self) -> None:
        text = _text(_routine("spend", guard=True))
        assert f"call {AI_GUARD_OBJECT:#x}" in text
        # The move call is still there, as the fallback for a refused guard - and it comes after.
        assert text.index(f"call {AI_GUARD_OBJECT:#x}") < text.index(
            f"call {AI_MOVE_TO_POSITION:#x}"
        )
        # `aiGuardObject` is `ret 0xC`: three arguments, pushed target-last. The command source is
        # `CMD_FROM_PLAYER`, matching the engine's own MSG_DO_GUARD_OBJECT path exactly - an
        # AI-sourced standing order is one the unit's idle behaviour is allowed to replace.
        call_at = text.index(f"call {AI_GUARD_OBJECT:#x}")
        assert text[call_at - 3 : call_at] == ["push 0", "push 0", "push ebx"]

    def test_the_guard_order_matches_the_engines_own_argument_list(self) -> None:
        """Every argument of the guard call is the value the stock handler passes: the target, a
        mode of 0 (appended at `0x0081D77F`), and `CMD_FROM_PLAYER` (`push ebx` at `0x0077ABEA`)."""
        assert GUARD_MODE_NORMAL == 0
        assert COMMAND_FROM_PLAYER == 0
        assert COMMAND_FROM_AI == 2  # what the move form uses, as the stock rally path does

    @pytest.mark.parametrize("guard", [False, True])
    def test_the_ai_interface_is_the_this_of_the_order(self, guard: bool) -> None:
        """Every stock caller reaches it as `Object+0x260` plus `0x20`, and so does this one."""
        text = _text(_routine("spend", guard))
        assert "add ecx, 0x20" in text
        assert text[text.index("add ecx, 0x20") - 1] == "mov ecx, dword ptr [edi + 0x260]"

    @pytest.mark.parametrize("guard", [False, True])
    def test_the_taken_arm_rejoins_after_the_stock_call(self, guard: bool) -> None:
        assert f"jmp {SPEND_RESUME_VA:#x}" in _text(_routine("spend", guard))


class TestTheMarkerRoutine:
    """The banner half. It answers the ControlBar with a different `Coord3D *` and touches nothing
    else, so its whole contract is: reproduce the query, substitute only when it is safe to, and
    come back with the stack where it found it."""

    def test_it_reproduces_the_query_it_displaced(self) -> None:
        assert _text(_routine("marker"))[:4] == [
            "push eax",  # the interface, across the call
            "mov edx, dword ptr [eax]",
            "mov ecx, eax",
            "call dword ptr [edx + 0x20]",
        ]

    def test_the_displaced_window_is_what_the_hook_replaces(self) -> None:
        """The three reproduced instructions have to be exactly the bytes taken out of both
        sites, or one of them keeps an instruction the routine also runs."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        stock = _text(list(md.disasm(MARKER_HOOK_STOCK, 0)))
        assert _text(_routine("marker"))[1:4] == stock

    def test_both_sites_share_one_routine(self) -> None:
        assert MARKER_HOOK_VAS[0] != MARKER_HOOK_VAS[1]
        assert len({r for _va, r, _op in HOOKS if _va in MARKER_HOOK_VAS}) == 1

    def test_it_returns_rather_than_jumping(self) -> None:
        """A `jmp` would need one trampoline per site; the `ret` is what makes the sites share."""
        text = _text(_routine("marker"))
        assert text[-1] == "ret"
        assert not [t for t in text if t.startswith("jmp ")]

    def test_a_null_answer_is_passed_straight_through(self) -> None:
        """NULL is how the ControlBar is told to destroy the marker, so it must survive intact."""
        insns = _routine("marker")
        text = _text(insns)
        null_test = text.index("test eax, eax")
        assert text[null_test - 1] == "pop ecx"  # the interface, before anything is decided
        assert insns[null_test + 1].mnemonic == "je"
        assert int(insns[null_test + 1].op_str, 16) == insns[-1].address  # straight to the ret

    def test_it_checks_the_class_before_reading_the_field(self) -> None:
        """`getExitInterface` answers with classes on which `+0x24` is somebody else's field."""
        text = _text(_routine("marker"))
        assert text.index(f"cmp dword ptr [ecx], {EXIT_VTABLE:#x}") < text.index(
            f"mov edx, dword ptr [ecx + {TARGET_ID_OFFSET:#x}]"
        )

    def test_it_asks_the_same_question_the_spend_routine_asks(self) -> None:
        """The banner has to stand where the units will actually go."""
        text = _text(_routine("marker"))
        assert f"call {FIND_OBJECT_BY_ID:#x}" in text
        assert f"call {GET_RELATIONSHIP:#x}" in text
        assert f"cmp eax, {RELATIONSHIP_ALLIED}" in text
        assert (
            text[text.index(f"call {GET_RELATIONSHIP:#x}") - 2] == "mov ecx, dword ptr [ecx - 0x18]"
        )

    def test_it_answers_with_the_target_live_position(self) -> None:
        assert f"add eax, {OBJECT_POSITION_OFFSET:#x}" in _text(_routine("marker"))

    def test_the_relationship_test_is_read_before_the_target_is_restored(self) -> None:
        """`pop` leaves the flags alone, which is the only reason this order is safe."""
        text = _text(_routine("marker"))
        cmp_at = text.index(f"cmp eax, {RELATIONSHIP_ALLIED}")
        assert text[cmp_at + 1] == "pop eax"
        assert text[cmp_at + 2].startswith("jne")

    def test_every_edge_leaves_the_stack_where_it_found_it(self) -> None:
        """Walked instruction by instruction: every path from entry to a `ret` has to end at
        depth zero, or the routine returns into its caller's frame."""
        insns = _routine("marker")
        by_address = {i.address: n for n, i in enumerate(insns)}
        seen: set[tuple[int, int]] = set()
        ends: list[int] = []

        def walk(index: int, depth: int) -> None:
            while index < len(insns):
                if (index, depth) in seen:
                    return
                seen.add((index, depth))
                insn = insns[index]
                text = f"{insn.mnemonic} {insn.op_str}".strip()
                if insn.mnemonic == "push":
                    depth += 4
                elif insn.mnemonic == "pop":
                    depth -= 4
                elif text == "add esp, 4":
                    depth -= 4
                elif insn.mnemonic == "call":
                    # Every callee here is `__thiscall`/`ret 4` and cleans its one argument, which
                    # the caller pushed - so the net effect on this routine's depth is that push.
                    depth -= 4 if insn.op_str != "dword ptr [edx + 0x20]" else 0
                elif insn.mnemonic == "ret":
                    ends.append(depth)
                    return
                if insn.mnemonic.startswith("j"):
                    walk(by_address[int(insn.op_str, 16)], depth)
                    if insn.mnemonic == "jmp":
                        return
                index += 1

        walk(0, 0)
        assert ends, "no return found"
        assert set(ends) == {0}, f"unbalanced exits at depths {sorted(set(ends))}"


# --- the build fingerprint -----------------------------------------------------------------------


class TestItRefusesAnotherBuild:
    @pytest.mark.parametrize("va", sorted(ANCHORS))
    def test_a_changed_anchor_is_refused(self, image: bytearray, va: int) -> None:
        data = bytearray(image)
        off = va_to_offset(data, va)
        assert off is not None
        data[off] ^= 0xFF
        with pytest.raises(ValueError):
            SmartRallyPatch().apply(data)

    def test_the_vtable_slots_name_the_hooked_routines(self) -> None:
        """The two hooks inside the class are safe only because that vtable is that class's."""
        assert ANCHORS[EXIT_VTABLE + 0x1C] == struct.pack("<I", SET_RALLY_POSITION)
        assert ANCHORS[EXIT_VTABLE + 0x2C] == struct.pack("<I", RELEASE_UNIT)


# --- the real binaries ---------------------------------------------------------------------------

#: Both copies in the tree. The repo-root `game.dat` carries eleven modifications and is **not**
#: stock, so a site is only safe to describe as stock when both agree - and none of this patch's
#: does anything else.
_BINARIES = {
    "repo": Path(__file__).resolve().parents[2] / "game.dat",
    "edain-backup": Path(__file__).resolve().parents[2]
    / "sage_mods"
    / "edain"
    / "patching"
    / "engine"
    / "game.dat.backup",
}

#: The other `game.dat` cave patches this one shares an image with. None of them touches the
#: production-exit modules or the rally handler, so any order has to give a verifying result.
_NEIGHBOURS = (AiConstructionGatePatch, SpawnUnionPatch, WallMeshReleasePatch)


def _section_rvas(data: bytes | bytearray) -> list[int]:
    e = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, e + 6)[0]
    sectab = e + 24 + struct.unpack_from("<H", data, e + 20)[0]
    return [struct.unpack_from("<I", data, sectab + i * 40 + 12)[0] for i in range(nsec)]


@pytest.mark.parametrize("which", sorted(_BINARIES))
class TestStockBinaries:
    """Against the real binaries, which are the only things that can say the addresses are right."""

    def _stock(self, which: str) -> bytes:
        path = _BINARIES[which]
        if not path.exists():
            pytest.skip(f"needs {path.name}")
        return path.read_bytes()

    def test_every_anchor_holds_its_stock_bytes(self, which: str) -> None:
        stock = self._stock(which)
        for va, expected in ANCHORS.items():
            off = va_to_offset(stock, va)
            assert off is not None, f"{va:#010x} is not mapped"
            assert bytes(stock[off : off + len(expected)]) == expected, f"{va:#010x}"

    @pytest.mark.parametrize("guard", [False, True])
    def test_apply_verify_detect_round_trip(self, which: str, guard: bool) -> None:
        data = bytearray(self._stock(which))
        patch = SmartRallyPatch(guard=guard)
        patch.apply(data)
        assert patch.verify(data) == []
        found = SmartRallyPatch.detect(data)
        assert isinstance(found, SmartRallyPatch)
        assert found.guard is guard

    @pytest.mark.parametrize("last", [False, True], ids=["rally-first", "rally-last"])
    def test_it_composes_with_the_other_cave_patches(self, which: str, last: bool) -> None:
        data = bytearray(self._stock(which))
        others = [cls() for cls in _NEIGHBOURS]
        order = [*others, SmartRallyPatch()] if last else [SmartRallyPatch(), *others]
        for patch in order:
            patch.apply(data)
        for patch in order:
            assert patch.verify(data) == [], f"{patch} failed in {[str(p) for p in order]}"
        rvas = _section_rvas(data)
        assert rvas == sorted(rvas)
