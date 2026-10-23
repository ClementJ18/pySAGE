"""Tests for `pickup-stuff-enter`.

The cave chooses between two AI orders, and a wrong choice does not raise: a backwards test
sends the Ring hero into the Ring's (absent) contain and leaves carts standing at the wall. So the
choice is executed, twice over:

- **the cave alone**, over the synthetic stand-in, with both orders answered in Python, against
  targets built to each shape - no contain, a contain that keeps passengers, a slaughter contain
  stored or declared ahead of another;
- **`PickupStuffUpdate`'s own move routine** over the real `game.dat`, patched, with the engine's
  real contain vtables answering the slaughter question. Skipped where there is no `game.dat`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from sage_patch.addresses import (
    AI_ENTER,
    AI_MOVE_TO_OBJECT,
    BEHAVIOR_GET_CONTAIN_SLOT,
    BEHAVIOR_MODULE_INTERFACE,
    CONTAIN_IS_SLAUGHTER_SLOT,
    HORDE_GARRISON_CONTAIN_INTERFACE_VTABLE,
    OBJECT_MODULE_LIST,
    PICKUP_STUFF_MOVE_TO,
    SLAUGHTER_HORDE_CONTAIN_INTERFACE_VTABLE,
)
from sage_patch.patches import multi_contain as mcon
from sage_patch.patches.pickup_stuff_enter import (
    ANCHORS,
    HOOK_ORIGINAL,
    HOOK_VA,
    SECTION_NAME,
    PickupStuffEnterPatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import call_rel32, find_section, va_to_offset

from .synthetic import pickup_stuff_enter_image

BASE = 0x00F00000

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


def disassemble(base: int = BASE):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return list(md.disasm(build_code(base), base))


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        insns = disassemble()
        assert sum(i.size for i in insns) == len(build_code(BASE))

    def test_it_leaves_only_by_the_two_orders(self):
        """Both are tail jumps: the cave owns no frame, so the order returns straight to
        `PickupStuffUpdate` with its `ret 8` popping the arguments the module pushed."""
        exits = {int(i.op_str, 16) for i in disassemble() if i.mnemonic == "jmp"}
        assert exits == {AI_ENTER, AI_MOVE_TO_OBJECT}
        assert not [i for i in disassemble() if i.mnemonic in {"ret", "retn"}]

    def test_every_conditional_branch_stays_inside_the_cave(self):
        lo, hi = BASE, BASE + len(build_code(BASE))
        for ins in disassemble():
            if ins.mnemonic.startswith("j") and ins.mnemonic != "jmp":
                assert lo <= int(ins.op_str, 16) < hi, f"{ins.mnemonic} at {ins.address:#x}"

    def test_it_relocates_with_its_section(self):
        a, b = build_code(BASE), build_code(BASE + 0x1000)
        assert a != b
        assert len(a) == len(b)


class TestApply:
    def test_apply_then_verify(self):
        data = pickup_stuff_enter_image()
        PickupStuffEnterPatch().apply(data)
        assert PickupStuffEnterPatch().verify(data) == []

    def test_the_hook_is_a_call_into_the_cave(self):
        """A `call` for a `call`: the five bytes are replaced like for like, so the return
        address the order sees is the stock one."""
        assert len(HOOK_ORIGINAL) == 5
        data = pickup_stuff_enter_image()
        PickupStuffEnterPatch().apply(data)
        section_va, _off, _size = find_section(data, SECTION_NAME)
        off = va_to_offset(data, HOOK_VA)
        assert bytes(data[off : off + 5]) == call_rel32(HOOK_VA, section_va)

    def test_the_stock_call_names_ai_move_to_object(self):
        assert call_rel32(HOOK_VA, AI_MOVE_TO_OBJECT) == HOOK_ORIGINAL

    def test_refuses_to_apply_twice(self):
        data = pickup_stuff_enter_image()
        PickupStuffEnterPatch().apply(data)
        with pytest.raises(ValueError, match="expected"):
            PickupStuffEnterPatch().apply(data)

    @pytest.mark.parametrize("va", sorted(ANCHORS))
    def test_a_moved_anchor_refuses_to_apply(self, va: int):
        data = pickup_stuff_enter_image()
        off = va_to_offset(data, va)
        data[off] ^= 0xFF
        with pytest.raises(ValueError, match="not laid out"):
            PickupStuffEnterPatch().apply(data)

    def test_verify_reports_a_missing_patch(self):
        assert PickupStuffEnterPatch().verify(pickup_stuff_enter_image()) != []

    def test_the_section_name_fits_the_pe_field(self):
        assert len(SECTION_NAME) <= 8


class TestRegistration:
    def test_it_is_offered_on_the_cli(self):
        assert PATCHES[PickupStuffEnterPatch.name] is PickupStuffEnterPatch

    def test_it_declares_no_parameters(self):
        assert PickupStuffEnterPatch().options() == {}

    def test_it_touches_nothing_multi_contain_rewrites(self):
        mine = set(range(HOOK_VA, HOOK_VA + len(HOOK_ORIGINAL)))
        theirs = {va + i for va, raw in mcon.stock_windows().items() for i in range(len(raw))}
        assert not mine & theirs
        assert not set(ANCHORS) & theirs


unicorn = pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")
pytest.importorskip("pefile", reason="the emulator harness maps the image with pefile")

from .save_machine import Machine  # noqa: E402

#: `PickupStuffUpdate` hands the order `CMD_FROM_AI`.
_CMD_FROM_AI = 2


@dataclass
class World:
    """A target object built in the machine's heap, and a log of the orders given."""

    m: Machine
    orders: list[tuple[str, int, int, int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        for name, va in (("enter", AI_ENTER), ("move", AI_MOVE_TO_OBJECT)):
            self.m.stub(va, self._order(name))
        self._yes = self._answer(1)
        self._no = self._answer(0)

    def _order(self, name: str):
        def handler(m: Machine) -> None:
            self.orders.append((name, m.reg("ecx"), m.arg(0), m.arg(1)))
            m.ret(8)

        return handler

    def _answer(self, value: int) -> int:
        """A contain vtable whose slaughter slot answers `value`."""
        vtable = self.m.alloc(0x100, bytes(0x100))
        self.m.write32(vtable + CONTAIN_IS_SLAUGHTER_SLOT, self.m.stub(None, _al(value)))
        return vtable

    def contain(self, slaughter: bool | None = None, vtable: int | None = None) -> int:
        """A contain interface: a synthetic one answering `slaughter`, or one on a real vtable."""
        at = self.m.alloc(0x10, bytes(0x10))
        self.m.write32(at, vtable if vtable is not None else (self._yes if slaughter else self._no))
        return at

    def module(self, contain: int) -> int:
        """A behaviour module whose `getContain` answers `contain` (0 for none)."""
        module = self.m.alloc(0x20, bytes(0x20))
        vtable = self.m.alloc(0x20, bytes(0x20))
        self.m.write32(module + BEHAVIOR_MODULE_INTERFACE, vtable)
        self.m.write32(vtable + BEHAVIOR_GET_CONTAIN_SLOT, self.m.stub(None, _eax(contain)))
        return module

    def target(self, *modules: int, listed: bool = True) -> int:
        obj = self.m.alloc(0x300, bytes(0x300))
        if listed:
            table = self.m.alloc(4 * (len(modules) + 1), bytes(4 * (len(modules) + 1)))
            for i, module in enumerate(modules):
                self.m.write32(table + 4 * i, module)
            self.m.write32(obj + OBJECT_MODULE_LIST, table)
        return obj


def _al(value: int):
    def handler(m: Machine) -> None:
        m.uc.reg_write(unicorn.x86_const.UC_X86_REG_EAX, 0xCCCCCC00 | value)
        m.ret(0)

    return handler


def _eax(value: int):
    def handler(m: Machine) -> None:
        m.ret(0, value)

    return handler


def _cave(data: bytes | bytearray) -> int:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    return located[0]


class TestTheChoice:
    """The cave over the synthetic stand-in, called as `aiMoveToObject` is."""

    AI = 0x0BAD0020

    @pytest.fixture
    def world(self) -> World:
        data = pickup_stuff_enter_image()
        PickupStuffEnterPatch().apply(data)
        return World(Machine(bytes(data)))

    def _order(self, world: World, target: int) -> tuple[str, int, int, int]:
        world.m.call(_cave(world.m.image), target, _CMD_FROM_AI, ecx=self.AI, esi=0x51, edi=0xD1)
        assert world.m.reg("esi") == 0x51 and world.m.reg("edi") == 0xD1, "callee-saved clobbered"
        assert len(world.orders) == 1
        return world.orders[0]

    def test_a_target_with_no_contain_is_moved_to(self, world: World):
        """The One Ring, a crate: the stock order, with the stock `this` and arguments."""
        target = world.target(world.module(0), world.module(0))
        assert self._order(world, target) == ("move", self.AI, target, _CMD_FROM_AI)

    def test_a_target_with_no_module_list_is_moved_to(self, world: World):
        target = world.target(listed=False)
        assert self._order(world, target)[0] == "move"

    def test_a_null_target_is_moved_to(self, world: World):
        """The search answered non-NULL before the call, but the stock order is what a NULL
        would have reached, so the cave must not read through it."""
        assert self._order(world, 0) == ("move", self.AI, 0, _CMD_FROM_AI)

    def test_a_contain_that_keeps_passengers_is_moved_to(self, world: World):
        target = world.target(world.module(world.contain(slaughter=False)))
        assert self._order(world, target)[0] == "move"

    def test_a_slaughter_contain_is_entered(self, world: World):
        target = world.target(world.module(world.contain(slaughter=True)))
        assert self._order(world, target) == ("enter", self.AI, target, _CMD_FROM_AI)

    def test_a_slaughter_contain_ahead_of_a_tunnel_is_entered(self, world: World):
        """The `multi-contain` shape: the stored contain keeps passengers, an earlier one is a
        slaughter contain."""
        target = world.target(
            world.module(0),
            world.module(world.contain(slaughter=True)),
            world.module(world.contain(slaughter=False)),
        )
        assert self._order(world, target)[0] == "enter"


@pytest.fixture(scope="module")
def real_patched() -> bytes:
    if not _GAME_DAT.exists():
        pytest.skip(f"no {_GAME_DAT}")
    data = bytearray(_GAME_DAT.read_bytes())
    PickupStuffEnterPatch().apply(data)
    return bytes(data)


class TestTheRealModule:
    """`PickupStuffUpdate`'s own move routine, patched, with the engine's contain vtables."""

    #: `AIUpdate::pushTemporaryMachine`, which the routine calls before giving the order.
    _PUSH_MACHINE = 0x006630A9

    def _run(self, image: bytes, vtable: int | None) -> tuple[str, int, int, int]:
        world = World(Machine(image))
        world.m.stub(self._PUSH_MACHINE, lambda m: m.ret(0))
        ai = world.m.alloc(0x400, bytes(0x400))
        owner = world.m.alloc(0x300, bytes(0x300))
        world.m.write32(owner + 0x260, ai)
        module = world.m.alloc(0x40, bytes(0x40))
        world.m.write32(module + 8, owner)
        modules = [] if vtable is None else [world.module(world.contain(vtable=vtable))]
        target = world.target(*modules)
        world.m.call(PICKUP_STUFF_MOVE_TO, target, ecx=module)
        assert world.m.stopped_at is not None
        assert len(world.orders) == 1
        name, this, got, source = world.orders[0]
        assert (this, got, source) == (ai + 0x20, target, _CMD_FROM_AI)
        return name, this, got, source

    def test_a_slaughter_horde_contain_is_entered(self, real_patched: bytes):
        assert self._run(real_patched, SLAUGHTER_HORDE_CONTAIN_INTERFACE_VTABLE)[0] == "enter"

    def test_a_horde_garrison_contain_is_moved_to(self, real_patched: bytes):
        assert self._run(real_patched, HORDE_GARRISON_CONTAIN_INTERFACE_VTABLE)[0] == "move"

    def test_no_contain_is_moved_to(self, real_patched: bytes):
        assert self._run(real_patched, None)[0] == "move"

    def test_the_stock_binary_moves_to_a_slaughter_contain(self):
        if not _GAME_DAT.exists():
            pytest.skip(f"no {_GAME_DAT}")
        stock = _GAME_DAT.read_bytes()
        assert self._run(stock, SLAUGHTER_HORDE_CONTAIN_INTERFACE_VTABLE)[0] == "move"
