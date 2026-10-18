"""`production-death-no-refund`, executed.

The sibling file reads the caves back as text. This one runs them, in two ways:

- **The caves alone**, over the synthetic stand-in, with the stock thunk answered in Python. Runs
  everywhere: the flag is up while the thunk runs and down after, and each gate takes the stock
  path with the flag down and skips the deposit with it up.
- **The engine's own loss path with the patch in place**, over the real `game.dat`, stock and
  patched side by side. Skipped where there is no `game.dat`. A producer with a unit, an upgrade
  and a hero queued is killed, captured and sold through the real `onDie` slot, slot 16 and
  cancel-all; `Money::deposit`, the spent tally, the revive release and the upgrade release are
  answered in Python and recorded. Stock refunds all three ways; patched refunds only the two
  that are not a death, and a death still releases everything else.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")
pytest.importorskip("pefile", reason="the emulator harness maps the image with pefile")

from sage_patch.addresses import (  # noqa: E402
    MONEY_DEPOSIT,
    OBJECT_GET_CONTROLLING_PLAYER,
    PRODUCTION_CANCEL_ALL,
    PRODUCTION_CANCEL_UNIT,
    PRODUCTION_CANCEL_UNIT_REFUND,
    PRODUCTION_CANCEL_UNIT_REFUND_RESUME,
    PRODUCTION_CANCEL_UNIT_REFUND_SKIP,
    PRODUCTION_CANCEL_UPGRADE,
    PRODUCTION_CANCEL_UPGRADE_REFUND,
    PRODUCTION_CANCEL_UPGRADE_REFUND_RESUME,
    PRODUCTION_CANCEL_UPGRADE_REFUND_SKIP,
    PRODUCTION_ON_DIE,
    PRODUCTION_ON_DIE_SLOT,
    PRODUCTION_ON_LOSS,
    PRODUCTION_QUEUE_HEAD,
    PRODUCTION_UPDATE_INTERFACE_VTABLE,
    PRODUCTION_UPDATE_VTABLE,
    REVIVE_MGR_OFFSET,
)
from sage_patch.patches.production_death_no_refund import (  # noqa: E402
    FLAG_OFF,
    SECTION_NAME,
    ProductionDeathNoRefundPatch,
    layout,
)
from sage_patch.utils import find_section  # noqa: E402

from .save_machine import Machine  # noqa: E402
from .synthetic import production_death_no_refund_image  # noqa: E402

REAL_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

needs_game_dat = pytest.mark.skipif(not REAL_GAME_DAT.exists(), reason="needs the real game.dat")


def _patched(source: bytes) -> bytes:
    data = bytearray(source)
    ProductionDeathNoRefundPatch().apply(data)
    return bytes(data)


def _section_base(image: bytes) -> int:
    located = find_section(image, SECTION_NAME)
    assert located is not None
    return located[0]


class TestTheCavesAlone:
    @pytest.fixture
    def machine(self) -> Machine:
        return Machine(_patched(bytes(production_death_no_refund_image())))

    def test_on_die_raises_the_flag_around_the_thunk_and_lowers_it_after(self, machine: Machine):
        base = _section_base(machine.image)
        flag = base + FLAG_OFF
        seen: list[tuple[int, int, int]] = []

        def thunk(m: Machine) -> None:
            seen.append((m.uc.mem_read(flag, 1)[0], m.reg("ecx"), m.arg(0)))
            m.ret(4)

        machine.stub(PRODUCTION_ON_DIE, thunk)
        machine.call(layout(base)["on_die"], 0xDA4A6E, ecx=0x10000024)
        assert seen == [(1, 0x10000024, 0xDA4A6E)]
        assert machine.uc.mem_read(flag, 1)[0] == 0

    @pytest.mark.parametrize(
        ("routine", "resume", "skip"),
        [
            (
                "upgrade_gate",
                PRODUCTION_CANCEL_UPGRADE_REFUND_RESUME,
                PRODUCTION_CANCEL_UPGRADE_REFUND_SKIP,
            ),
            ("unit_gate", PRODUCTION_CANCEL_UNIT_REFUND_RESUME, PRODUCTION_CANCEL_UNIT_REFUND_SKIP),
        ],
    )
    @pytest.mark.parametrize("dying", [False, True])
    def test_a_gate_skips_the_deposit_only_while_dying(
        self, machine: Machine, routine: str, resume: int, skip: int, dying: bool
    ):
        base = _section_base(machine.image)
        machine.uc.mem_write(base + FLAG_OFF, bytes([int(dying)]))
        machine.stop_at(resume, skip)
        frame = machine.frame()  # [ebp-1] = 0: not a finished unit at the door
        machine.write32(frame + 8, 0x0BADF00D)  # cancelUpgrade's [ebp+8], the owner
        machine.call(layout(base)[routine], ebp=frame, eax=0x0BADF00D)
        assert machine.stopped_at == (skip if dying else resume)


@dataclass
class World:
    """One producer, its owner and its queue, over a real `game.dat` image."""

    m: Machine
    deposits: list[tuple[int, int]] = field(default_factory=list)
    tallies: list[int] = field(default_factory=list)
    revives_released: list[int] = field(default_factory=list)
    upgrades_released: list[int] = field(default_factory=list)
    freed: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        m = self.m
        self.player = m.alloc(0x1000, bytes(0x1000))
        self.owner = m.alloc(0x400, bytes(0x400))
        self.producer = m.alloc(0x200, bytes(0x200))
        m.write32(self.producer, PRODUCTION_UPDATE_VTABLE)
        m.write32(self.producer + 8, self.owner)
        m.write32(self.interface, PRODUCTION_UPDATE_INTERFACE_VTABLE)
        m.write32(self.die, PRODUCTION_ON_DIE_SLOT)
        self.upgrade = m.alloc(0x40, bytes(0x40))  # +4 = 0: a player upgrade
        entry_vtable = m.alloc(4)
        m.write32(entry_vtable, m.stub(None, lambda mm: mm.ret(4, mm.reg("ecx"))))
        self.entry_vtable = entry_vtable

        m.stub(OBJECT_GET_CONTROLLING_PLAYER, lambda mm: mm.ret(0, self.player))
        m.stub(MONEY_DEPOSIT, self._deposit)
        m.stub(0x0079DFC2, self._tally)  # the owner's +0x3DC spent tally
        m.stub(0x00780C64, self._release_revive)  # the revive manager's release
        m.stub(0x006AB2E1, lambda mm: mm.ret(4, 1))  # "this upgrade is in production"
        m.stub(0x006AE60C, self._release_upgrade)
        m.stub(0x008A0CF2, self._unlink)
        m.stub(0x0042F6A0, self._free)
        m.stub(0x0068BB14, lambda mm: mm.ret(0, 0))  # no held RespawnUpdate object

    @property
    def interface(self) -> int:
        return self.producer + 0x20

    @property
    def die(self) -> int:
        return self.producer + 0x24

    def queue(self, kind: int, paid: int, production_id: int) -> int:
        m = self.m
        entry = m.alloc(0x50, bytes(0x50))
        m.write32(entry, self.entry_vtable)
        m.write32(entry + 4, kind)
        m.write32(entry + 0xC, self.upgrade if kind == 2 else 0)
        m.write32(entry + 0x10, production_id)
        m.uc.mem_write(entry + 0x14, struct.pack("<f", 0.5))
        m.write32(entry + 0x28, paid)
        at = self.producer + PRODUCTION_QUEUE_HEAD
        while m.read32(at):
            at = m.read32(at) + 0x48
        m.write32(at, entry)
        return entry

    def _deposit(self, m: Machine) -> None:
        self.deposits.append((m.reg("ecx") - self.player, m.arg(0)))
        m.ret(12)

    def _tally(self, m: Machine) -> None:
        self.tallies.append(m.arg(1) - (1 << 32) if m.arg(1) >> 31 else m.arg(1))
        m.ret(8)

    def _release_revive(self, m: Machine) -> None:
        assert m.reg("ecx") == self.player + REVIVE_MGR_OFFSET
        self.revives_released.append(m.arg(0))
        m.ret(4)

    def _release_upgrade(self, m: Machine) -> None:
        self.upgrades_released.append(m.arg(0))
        m.ret(8)

    def _unlink(self, m: Machine) -> None:
        assert m.reg("ecx") == self.producer
        head = self.producer + PRODUCTION_QUEUE_HEAD
        assert m.read32(head) == m.arg(0), "cancel-all always cancels the head"
        m.write32(head, m.read32(m.arg(0) + 0x48))
        m.ret(4)

    def _free(self, m: Machine) -> None:
        self.freed.append(m.arg(0))
        m.ret(0)

    def fill(self) -> None:
        self.queue(1, 300, 7)  # a unit
        self.queue(2, 1000, 0)  # a player upgrade
        self.queue(3, 1500, 9)  # a hero revive

    def run_death(self) -> None:
        self.m.call(self.m.read32(PRODUCTION_ON_DIE_SLOT), 0, ecx=self.die)

    def run_capture(self) -> None:
        self.m.call(PRODUCTION_ON_LOSS, ecx=self.interface)

    def run_sell(self) -> None:
        self.m.call(PRODUCTION_CANCEL_ALL, ecx=self.interface)

    def drained(self) -> bool:
        return self.m.read32(self.producer + PRODUCTION_QUEUE_HEAD) == 0


@pytest.fixture(scope="module")
def stock() -> bytes:
    return REAL_GAME_DAT.read_bytes()


@pytest.fixture(scope="module")
def patched(stock: bytes) -> bytes:
    return _patched(stock)


@needs_game_dat
class TestTheEnginesLossPath:
    def test_the_interface_slots_name_the_cancels(self, stock: bytes):
        m = Machine(stock)
        slot = lambda n: m.read32(PRODUCTION_UPDATE_INTERFACE_VTABLE + n)  # noqa: E731
        assert slot(0x10) == PRODUCTION_CANCEL_UPGRADE
        assert slot(0x28) == PRODUCTION_CANCEL_UNIT
        assert slot(0x3C) == PRODUCTION_CANCEL_ALL
        assert slot(0x40) == PRODUCTION_ON_LOSS
        assert m.read32(PRODUCTION_ON_DIE_SLOT) == PRODUCTION_ON_DIE
        assert PRODUCTION_CANCEL_UPGRADE < PRODUCTION_CANCEL_UPGRADE_REFUND < PRODUCTION_CANCEL_UNIT
        assert PRODUCTION_CANCEL_UNIT < PRODUCTION_CANCEL_UNIT_REFUND

    @pytest.mark.parametrize("how", ["run_death", "run_capture", "run_sell"])
    def test_stock_refunds_every_loss(self, stock: bytes, how: str):
        world = World(Machine(stock))
        world.fill()
        getattr(world, how)()
        assert world.drained()
        assert world.deposits == [(0x90, 300), (0x90, 1000), (0x90, 1500)]
        assert world.tallies == [-300, -1500]

    def test_patched_death_cancels_everything_and_refunds_nothing(self, patched: bytes):
        world = World(Machine(patched))
        world.fill()
        world.run_death()
        assert world.m.stopped_at is not None
        assert world.drained()
        assert world.deposits == []
        assert world.tallies == []
        assert world.revives_released == [9]
        assert world.upgrades_released == [world.upgrade]
        assert len(world.freed) == 3
        flag = _section_base(patched) + FLAG_OFF
        assert world.m.uc.mem_read(flag, 1)[0] == 0

    @pytest.mark.parametrize("how", ["run_capture", "run_sell"])
    def test_patched_capture_and_sale_still_refund(self, patched: bytes, how: str):
        world = World(Machine(patched))
        world.fill()
        getattr(world, how)()
        assert world.drained()
        assert world.deposits == [(0x90, 300), (0x90, 1000), (0x90, 1500)]
        assert world.tallies == [-300, -1500]

    def test_a_sale_after_a_death_refunds_again(self, patched: bytes):
        """The flag is lowered on the way out, so it cannot leak into the next cancel."""
        world = World(Machine(patched))
        world.fill()
        world.run_death()
        assert world.deposits == []
        world.fill()
        world.run_sell()
        assert world.deposits == [(0x90, 300), (0x90, 1000), (0x90, 1500)]

    def test_the_hooks_are_where_the_patch_says(self, patched: bytes):
        m = Machine(patched)
        base = _section_base(patched)
        assert m.read32(PRODUCTION_ON_DIE_SLOT) == layout(base)["on_die"]
        for site in (PRODUCTION_CANCEL_UPGRADE_REFUND, PRODUCTION_CANCEL_UNIT_REFUND):
            assert m.uc.mem_read(site, 1)[0] == 0xE9
