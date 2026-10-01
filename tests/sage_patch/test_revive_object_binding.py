"""Tests for the revive-object-binding patch.

The three routines rejoin the middle of engine functions, so what could be wrong without raising
is where each one leaves and with what in its registers and frame: the ledger index in `ebx`, the
entry at `[ebp-0x28]`, the roster ordinal left where the stock tail expects it, the stack level the
stock code resumes at. Each routine is run under an emulator with the engine helpers stubbed and
every exit treated as a stop, over one case per way it can end.
"""

from __future__ import annotations

import faulthandler
import itertools
import struct
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from sage_patch import AiReviveGatePatch, CommandSetLimitPatch
from sage_patch.addresses import (
    CAN_MAKE_UNIT_NEXT_SLOT,
    CAN_MAKE_UNIT_REVIVE_BRANCH,
    CAN_MAKE_UNIT_REVIVE_DISPATCH,
    CAN_MAKE_UNIT_TEMPLATE_BRANCH,
    CAN_MAKE_UNIT_UPGRADE_GATE,
    COMMAND_BUTTON_GET_THING_TEMPLATE,
    CONTROL_BAR_REVIVE_BIND,
    CONTROL_BAR_REVIVE_BIND_SET_ENTRY,
    CONTROL_BAR_REVIVE_PASS2_NEXT,
    CONTROL_BAR_REVIVE_PASS2_RESUME,
    CONTROL_BAR_REVIVE_PASS2_TEST,
    CONTROL_BAR_REVIVE_ROSTER_LOOKUP,
    CONTROL_BAR_REVIVE_ROSTER_RESUME,
    CONTROL_BAR_REVIVE_UNBOUND,
    CONTROL_BAR_REVIVE_USED_COUNT,
    GUICOMMAND_REVIVE,
    HERO_LEDGER_FIND_ENTRY,
    HERO_LEDGER_GET_ENTRY,
    HERO_LEDGER_GET_TEMPLATE,
    OBJECT_GET_CONTROLLING_PLAYER,
    PLAYER_GET_BUILDABLE_HERO,
    PLAYER_HERO_LEDGER_OFFSET,
)
from sage_patch.patches.revive_object_binding import (
    ANCHORS,
    HOOKS,
    SECTION_NAME,
    ReviveObjectBindingPatch,
    build_code,
    layout,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, jmp_rel32, va_to_offset
from tests.sage_patch.synthetic import revive_object_binding_image

_EXITS = {
    CAN_MAKE_UNIT_TEMPLATE_BRANCH: "template branch",
    CAN_MAKE_UNIT_UPGRADE_GATE: "upgrade gate",
    CAN_MAKE_UNIT_NEXT_SLOT: "next slot",
    CAN_MAKE_UNIT_REVIVE_BRANCH: "stock revive branch",
    CONTROL_BAR_REVIVE_ROSTER_RESUME: "roster resume",
    CONTROL_BAR_REVIVE_BIND_SET_ENTRY: "bind",
    CONTROL_BAR_REVIVE_UNBOUND: "unbound",
    CONTROL_BAR_REVIVE_PASS2_RESUME: "pass 2 resume",
    CONTROL_BAR_REVIVE_PASS2_NEXT: "pass 2 next",
}


def _read(data: bytes | bytearray, va: int, n: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + n])


def _cave_va(data: bytes | bytearray) -> int:
    located = find_section(data, SECTION_NAME)
    assert located is not None, f"no {SECTION_NAME} section"
    return located[0]


@pytest.fixture
def image() -> bytearray:
    return revive_object_binding_image()


@pytest.fixture
def patched() -> bytearray:
    data = revive_object_binding_image()
    ReviveObjectBindingPatch().apply(data)
    return data


class TestStructure:
    @pytest.mark.parametrize("va", sorted(HOOKS), ids=lambda va: f"{va:#010x}")
    def test_each_site_jumps_to_its_routine(self, patched: bytearray, va: int) -> None:
        stock, label = HOOKS[va]
        target = layout(_cave_va(patched)).label_va(label)
        assert _read(patched, va, len(stock)) == jmp_rel32(va, target, len(stock))

    def test_the_cave_decodes_to_its_end(self) -> None:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        base = 0x01000000
        code = build_code(base)
        assert sum(i.size for i in md.disasm(code, base)) == len(code)

    def test_every_branch_lands_inside_the_cave_or_on_a_known_exit(self) -> None:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        base = 0x01000000
        code = build_code(base)
        calls = {
            COMMAND_BUTTON_GET_THING_TEMPLATE,
            OBJECT_GET_CONTROLLING_PLAYER,
            HERO_LEDGER_FIND_ENTRY,
            HERO_LEDGER_GET_ENTRY,
            HERO_LEDGER_GET_TEMPLATE,
            PLAYER_GET_BUILDABLE_HERO,
        }
        for ins in md.disasm(code, base):
            if not ins.mnemonic.startswith(("j", "call")):
                continue
            target = int(ins.op_str, 16)
            inside = base <= target < base + len(code)
            if ins.mnemonic == "call":
                assert target in calls, f"call at {ins.address:#x}"
            elif ins.mnemonic == "jmp":
                assert inside or target in _EXITS, f"jmp at {ins.address:#x}"
            else:
                assert inside, f"{ins.mnemonic} at {ins.address:#x} escapes"

    def test_the_stock_revive_branch_is_jumped_to_and_never_read(self) -> None:
        """`ai-revive-gate` rewrites it; composing depends on this patch not asserting it."""
        assert CAN_MAKE_UNIT_REVIVE_BRANCH not in ANCHORS
        for va, (stock, _label) in HOOKS.items():
            assert not va <= CAN_MAKE_UNIT_REVIVE_BRANCH < va + len(stock)

    def test_pass_one_rejoins_the_bind_on_its_call(self) -> None:
        """The cave pushes the entry and sets `ecx` itself, then enters on the `call` - the 13
        bytes it skips are those two instructions and the unguarded used-flag store."""
        assert CONTROL_BAR_REVIVE_BIND_SET_ENTRY - CONTROL_BAR_REVIVE_BIND == 13
        assert ANCHORS[CONTROL_BAR_REVIVE_BIND][13] == 0xE8


class TestLifecycle:
    def test_apply_verify_detect(self, patched: bytearray) -> None:
        assert ReviveObjectBindingPatch().verify(patched) == []
        assert isinstance(ReviveObjectBindingPatch.detect(patched), ReviveObjectBindingPatch)

    def test_an_unpatched_image_is_not_detected(self, image: bytearray) -> None:
        assert ReviveObjectBindingPatch().verify(image) != []
        assert ReviveObjectBindingPatch.detect(image) is None

    def test_a_second_apply_refuses_before_writing(self, patched: bytearray) -> None:
        before = bytes(patched)
        with pytest.raises(ValueError, match="already carries this patch"):
            ReviveObjectBindingPatch().apply(patched)
        assert bytes(patched) == before

    @pytest.mark.parametrize("va", sorted(ANCHORS), ids=lambda va: f"{va:#010x}")
    def test_a_drifted_anchor_refuses_before_writing(self, image: bytearray, va: int) -> None:
        off = va_to_offset(image, va)
        assert off is not None
        image[off] ^= 0xFF
        before = bytes(image)
        with pytest.raises(ValueError, match="layout is not this build's"):
            ReviveObjectBindingPatch().apply(image)
        assert bytes(image) == before

    def test_a_moved_hook_is_reported(self, patched: bytearray) -> None:
        off = va_to_offset(patched, CONTROL_BAR_REVIVE_PASS2_TEST)
        assert off is not None
        patched[off + 1] ^= 0xFF
        assert any("does not jump" in p for p in ReviveObjectBindingPatch().verify(patched))

    def test_registered_as_settled(self) -> None:
        assert PATCHES["revive-object-binding"] is ReviveObjectBindingPatch
        assert not ReviveObjectBindingPatch.experimental


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

_PAGE = 0x1000
_CAVE = 0x01000000
_HEAP = 0x20000000
_STACK = 0x30000000
_EBP = _STACK + 0x800

_BUTTON, _PRODUCER, _PLAYER = _HEAP + 0x100, _HEAP + 0x200, _HEAP + 0x400
_LEDGER = _PLAYER + PLAYER_HERO_LEDGER_OFFSET
_ENTRIES = _HEAP + 0x8000
_BEREGOND, _BOROMIR, _ROSTER_HERO = 0x0B0B0001, 0x0B0B0002, 0x0B0B0003

#: What each stubbed helper takes off the stack besides its return address.
_ARGS = {
    COMMAND_BUTTON_GET_THING_TEMPLATE: 0,
    OBJECT_GET_CONTROLLING_PLAYER: 0,
    HERO_LEDGER_FIND_ENTRY: 3,
    HERO_LEDGER_GET_ENTRY: 1,
    HERO_LEDGER_GET_TEMPLATE: 1,
    PLAYER_GET_BUILDABLE_HERO: 1,
}


@dataclass
class World:
    """One REVIVE button, its owner, and that owner's hero ledger, as the stubs see them."""

    command: int = GUICOMMAND_REVIVE
    bound: int = _BEREGOND  # the button's `Object`, 0 for none
    has_player: bool = True
    ledger: list[int] = field(default_factory=lambda: [_ROSTER_HERO, _BOROMIR, _BEREGOND])
    revive_index: int = 2
    ordinal: int = 5
    calls: list[tuple[int, int, tuple[int, ...]]] = field(default_factory=list)


@dataclass
class Outcome:
    exit: str
    regs: dict[str, int]
    frame: bytes  # [ebp-0x84, ebp+0x14)
    stack: list[int]  # dwords from esp up to where the routine was entered

    def at(self, displacement: int) -> int:
        return struct.unpack_from("<i", self.frame, displacement + 0x84)[0]

    def used(self, index: int) -> int:
        return self.frame[index]


def _run(world: World, label: str, is_revive: bool = True) -> Outcome:
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    pages = {_CAVE, _HEAP, _HEAP + 0x8000, _STACK}
    pages |= {va & ~0xFFF for va in (*_ARGS, *_EXITS)}
    was_enabled = faulthandler.is_enabled()
    faulthandler.disable()
    try:
        for page in sorted(pages):
            uc.mem_map(page, _PAGE)
    finally:
        if was_enabled:
            faulthandler.enable()

    asm = layout(_CAVE)
    uc.mem_write(_CAVE, asm.finish())
    uc.mem_write(_BUTTON + 0x14, struct.pack("<I", world.command))

    frame = bytearray(0x84 + 0x14)
    frame[0x84 - 1] = int(is_revive)
    struct.pack_into("<I", frame, 0x84 + 8, _PRODUCER)
    struct.pack_into("<i", frame, 0x84 + 0x10, world.revive_index)
    struct.pack_into("<I", frame, 0x84 - 0x1C, _PLAYER)
    struct.pack_into("<i", frame, 0x84 - 0x20, world.ordinal)
    uc.mem_write(_EBP - 0x84, bytes(frame))

    def answer(fn: int, this: int, args: tuple[int, ...]) -> int:
        if fn == COMMAND_BUTTON_GET_THING_TEMPLATE:
            assert this == _BUTTON
            return world.bound
        if fn == OBJECT_GET_CONTROLLING_PLAYER:
            assert this == _PRODUCER
            return _PLAYER if world.has_player else 0
        if fn == PLAYER_GET_BUILDABLE_HERO:
            assert this == _PLAYER
            return _ROSTER_HERO
        assert this == _LEDGER, f"ledger helper {fn:#x} called on {this:#x}"
        if fn == HERO_LEDGER_FIND_ENTRY:
            what, ident, ordinal = args
            assert (ident, ordinal) == (0xFFFFFFFF, 0)
            return world.ledger.index(what) if what in world.ledger else 0xFFFFFFFF
        (index,) = args
        if not 0 <= index < len(world.ledger):
            return 0
        if fn == HERO_LEDGER_GET_ENTRY:
            return _ENTRIES + index * 0xE8
        return world.ledger[index]

    reached: list[str] = []

    def on_code(emu: Uc, address: int, _size: int, _user: object) -> None:
        if address in _EXITS:
            reached.append(_EXITS[address])
            emu.emu_stop()
            return
        if address not in _ARGS:
            return
        n = _ARGS[address]
        esp = emu.reg_read(UC_X86_REG_ESP)
        ret, *args = struct.unpack(f"<{n + 1}I", bytes(emu.mem_read(esp, 4 * (n + 1))))
        this = emu.reg_read(UC_X86_REG_ECX)
        world.calls.append((address, this, tuple(args)))
        emu.reg_write(UC_X86_REG_EAX, answer(address, this, tuple(args)))
        emu.reg_write(UC_X86_REG_ESP, esp + 4 * (n + 1))
        emu.reg_write(UC_X86_REG_EIP, ret)

    uc.hook_add(UC_HOOK_CODE, on_code)
    esp = _EBP - 0x100
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_EBP, _EBP)
    uc.reg_write(UC_X86_REG_ESI, _BUTTON)
    uc.emu_start(asm.label_va(label), 0, count=500)

    assert len(reached) == 1, "the routine must leave through exactly one known exit"
    now = uc.reg_read(UC_X86_REG_ESP)
    depth = (esp - now) // 4
    stack = list(struct.unpack(f"<{depth}I", bytes(uc.mem_read(now, depth * 4)))) if depth else []
    regs = {
        "eax": uc.reg_read(UC_X86_REG_EAX),
        "ebx": uc.reg_read(UC_X86_REG_EBX),
        "ecx": uc.reg_read(UC_X86_REG_ECX),
        "edi": uc.reg_read(UC_X86_REG_EDI),
        "esi": uc.reg_read(UC_X86_REG_ESI),
    }
    assert regs["esi"] == _BUTTON, "the button in esi must survive"
    return Outcome(reached[0], regs, bytes(uc.mem_read(_EBP - 0x84, 0x84 + 0x14)), stack)


class TestCanMakeUnit:
    def test_a_unit_question_takes_the_template_branch_untouched(self) -> None:
        world = World()
        out = _run(world, "can_make_unit", is_revive=False)
        assert out.exit == "template branch"
        assert world.calls == [] and out.stack == []

    def test_another_command_takes_the_stock_revive_branch(self) -> None:
        world = World(command=3)
        assert _run(world, "can_make_unit").exit == "stock revive branch"
        assert world.calls == []

    def test_an_unbound_revive_button_takes_the_stock_revive_branch(self) -> None:
        out = _run(World(bound=0), "can_make_unit")
        assert out.exit == "stock revive branch"
        assert out.stack == []

    def test_a_bound_button_for_the_requested_hero_goes_to_the_upgrade_gate(self) -> None:
        out = _run(World(), "can_make_unit")
        assert out.exit == "upgrade gate"
        assert out.stack == [], "every push must be popped or consumed by a callee"

    @pytest.mark.parametrize("index", [0, 1, 3])
    def test_a_bound_button_for_another_hero_moves_on_without_counting(self, index: int) -> None:
        out = _run(World(revive_index=index), "can_make_unit")
        assert out.exit == "next slot"
        assert out.at(-0xC) == 0, "a bound button must not advance the positional count"

    def test_a_bound_hero_not_in_the_ledger_never_matches(self) -> None:
        assert _run(World(bound=0x0BADBAD0), "can_make_unit").exit == "next slot"

    def test_no_controlling_player_never_matches(self) -> None:
        out = _run(World(has_player=False), "can_make_unit")
        assert out.exit == "next slot"
        assert out.stack == []


class TestPassOne:
    def test_an_unbound_button_runs_the_displaced_roster_lookup(self) -> None:
        world = World(bound=0)
        out = _run(world, "pass1")
        assert out.exit == "roster resume"
        assert out.regs["eax"] == _ROSTER_HERO
        assert (PLAYER_GET_BUILDABLE_HERO, _PLAYER, (5,)) in world.calls
        assert out.at(-0x20) == 5, "the roster ordinal is the tail's to advance"
        assert out.stack == []

    def test_a_bound_button_rejoins_the_bind_with_its_own_entry(self) -> None:
        out = _run(World(), "pass1")
        assert out.exit == "bind"
        assert out.regs["ebx"] == 2  # the index written to +0xC0
        assert out.regs["edi"] == _BEREGOND  # whose display name labels the button
        assert out.regs["ecx"] == _BUTTON  # `this` for the setter the bind calls
        assert out.at(-0x28) == _ENTRIES + 2 * 0xE8
        assert out.stack == [_ENTRIES + 2 * 0xE8], "the setter's argument, already pushed"
        assert out.used(2) == 1, "pass 2 must see the entry as claimed"

    @pytest.mark.parametrize(
        "world", [World(bound=0x0BADBAD0), World(ledger=[])], ids=["not in ledger", "empty"]
    )
    def test_a_bound_hero_with_no_entry_takes_the_unbound_arm(self, world: World) -> None:
        out = _run(world, "pass1")
        assert out.exit == "unbound"
        assert out.stack == []

    @pytest.mark.parametrize("world", [World(), World(bound=0x0BADBAD0)], ids=["bound", "absent"])
    def test_a_bound_button_does_not_consume_a_roster_ordinal(self, world: World) -> None:
        """Both exits reach the tail's `inc [ebp-0x20]`, so the cave leaves it one lower."""
        assert _run(world, "pass1").at(-0x20) == world.ordinal - 1

    def test_a_ledger_index_past_the_flags_is_not_marked(self) -> None:
        ledger = [_ROSTER_HERO] * CONTROL_BAR_REVIVE_USED_COUNT + [_BEREGOND]
        out = _run(World(ledger=ledger), "pass1")
        assert out.exit == "bind"
        assert out.regs["ebx"] == CONTROL_BAR_REVIVE_USED_COUNT
        assert out.frame[: CONTROL_BAR_REVIVE_USED_COUNT + 1] == bytes(
            CONTROL_BAR_REVIVE_USED_COUNT + 1
        )


class TestPassTwo:
    def test_an_unbound_revive_button_is_a_free_slot(self) -> None:
        assert _run(World(bound=0), "pass2").exit == "pass 2 resume"

    def test_a_bound_revive_button_is_skipped(self) -> None:
        assert _run(World(), "pass2").exit == "pass 2 next"

    def test_another_command_is_skipped_as_stock(self) -> None:
        world = World(command=3)
        assert _run(world, "pass2").exit == "pass 2 next"
        assert world.calls == []


#: Both copies a checkout can hold; neither is committed, so each check skips when absent.
_BINARIES = {
    "repo": Path(__file__).resolve().parents[2] / "game.dat",
    "clean": Path(__file__).resolve().parents[2] / "sage_patch" / "engine" / "game.dat.backup",
}


@pytest.mark.parametrize("which", sorted(_BINARIES))
class TestStockBinaries:
    def _stock(self, which: str) -> bytes:
        path = _BINARIES[which]
        if not path.exists():
            pytest.skip(f"needs {path.name}")
        return path.read_bytes()

    def test_every_site_is_stock(self, which: str) -> None:
        stock = self._stock(which)
        for va, (expected, _label) in HOOKS.items():
            assert _read(stock, va, len(expected)) == expected, f"{va:#010x}"
        for va, expected in ANCHORS.items():
            assert _read(stock, va, len(expected)) == expected, f"{va:#010x}"

    @pytest.mark.parametrize("order", list(itertools.permutations(range(3))))
    def test_composes_with_the_other_can_make_unit_patches(
        self, which: str, order: tuple[int, ...]
    ) -> None:
        data = bytearray(self._stock(which))
        patches = (CommandSetLimitPatch(count=64), AiReviveGatePatch(), ReviveObjectBindingPatch())
        for i in order:
            patches[i].apply(data)
        for patch in patches:
            assert patch.verify(data) == [], f"{patch} in order {order}"
        assert _read(data, CAN_MAKE_UNIT_REVIVE_DISPATCH, 1) == b"\xe9"
        assert _read(data, CONTROL_BAR_REVIVE_ROSTER_LOOKUP, 1) == b"\xe9"
