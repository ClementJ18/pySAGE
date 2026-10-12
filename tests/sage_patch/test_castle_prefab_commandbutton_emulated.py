"""Execute the real x86 parser/sender/receiver, with engine ABI stand-ins."""

from __future__ import annotations

import pytest

from sage_patch import addresses as ad
from sage_patch.patches.experimental import castle_prefab as cp

pytest.importorskip("unicorn", reason="the cave emulator requires the patch extra")
from unicorn import Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EFLAGS,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from .test_castle_prefab_emulated import Engine  # noqa: E402


class Buttons(Engine):
    CONFIG = 0x4000000
    BUTTON = 0x2005000
    MESSAGE = 0x2006000
    TOKEN = 0x2007000
    FACTORY = 0x2008000
    VTABLE = 0x2009000
    CREATE = 0x200A000

    def __init__(self) -> None:
        super().__init__()
        self.cpu.mem_map(self.CONFIG, 0x50000)
        self.command = cp._command_emit(self.CONFIG, (), self.BASE)
        self.cpu.mem_write(self.CONFIG, self.command.finish())
        pages = {
            va & ~0xFFF
            for va in (
                *ad.CASTLE_COMMAND_ANCHORS,
                *cp.COMMAND_HOOKS,
                ad.INI_NEXT_TOKEN_OR_NULL,
                ad.NAME_KEY_FROM_CSTR,
                ad.THE_MESSAGE_STREAM,
                ad.CASTLE_COMMAND_RECEIVER_FAIL,
                ad.CASTLE_COMMAND_SENDER_EXIT,
            )
        }
        for page in pages:
            if not any(lo <= page <= hi for lo, hi, _ in self.cpu.mem_regions()):
                self.cpu.mem_map(page, 0x1000)
        self.write(ad.THE_MESSAGE_STREAM, self.FACTORY)
        self.write(self.FACTORY, self.VTABLE)
        self.write(self.VTABLE + ad.APPEND_MESSAGE_VTABLE_SLOT, self.CREATE)
        for va in (
            ad.CASTLE_COMMAND_RECEIVER_FAIL,
            ad.CASTLE_COMMAND_SENDER_EXIT,
            ad.COMMAND_BUTTON_SIDECAR_CTOR + 6,
        ):
            self.cpu.mem_write(va, b"\x90\xc3")
        self.tokens: list[bytes] = []
        self.args: list[tuple[int, int]] = []
        self.created: list[int] = []
        self.exit = 0
        self.explicit: list[int] = []
        self.interned: list[str] = []
        self.arg_reads: list[int] = []
        self.cpu.mem_write(
            ad.CASTLE_COMMAND_RECEIVER_RESUME,
            ad.CASTLE_COMMAND_ANCHORS[ad.CASTLE_COMMAND_RECEIVER_RESUME],
        )
        self.cpu.mem_write(
            ad.CASTLE_COMMAND_SENDER_STOCK_RESUME,
            ad.CASTLE_COMMAND_ANCHORS[ad.CASTLE_COMMAND_SENDER_STOCK_RESUME],
        )
        self.cpu.mem_write(
            ad.CASTLE_COMMAND_SENDER_FACTORY,
            ad.CASTLE_COMMAND_ANCHORS[ad.CASTLE_COMMAND_SENDER_FACTORY],
        )

    def _hook(self, cpu: Uc, addr: int, size: int, user: object) -> None:
        sp = cpu.reg_read(UC_X86_REG_ESP)
        if addr == ad.INI_NEXT_TOKEN_OR_NULL:
            if self.tokens:
                self.cpu.mem_write(self.TOKEN, self.tokens.pop(0) + b"\0")
                self._return(4, self.TOKEN)
            else:
                self._return(4, 0)
        elif addr == ad.NAME_KEY_FROM_CSTR:
            raw = bytes(self.cpu.mem_read(self.read(sp + 4), 256)).split(b"\0")[0]
            self.interned.append(raw.decode("ascii"))
            self._return(4, self.key + len(self.interned))
        elif addr == self.CREATE:
            assert cpu.reg_read(UC_X86_REG_ECX) == self.FACTORY
            self.created.append(self.read(sp + 4))
            self.args = []
            self._return(4, self.MESSAGE)
        elif addr == ad.GAME_MESSAGE_APPEND_INTEGER:
            assert cpu.reg_read(UC_X86_REG_ECX) == self.MESSAGE
            self.args.append((0, self.read(sp + 4)))
            self._return(4)
        elif addr in (ad.GAME_MESSAGE_GET_ARGUMENT_DATA, ad.GAME_MESSAGE_GET_ARGUMENT_TYPE):
            assert cpu.reg_read(UC_X86_REG_ECX) == self.MESSAGE
            index = self.read(sp + 4)
            self.arg_reads.append(index)
            if addr == ad.GAME_MESSAGE_GET_ARGUMENT_TYPE:
                self._return(4, self.args[index][0])
            else:
                self.write(self.MESSAGE + 0x100, self.args[index][1])
                self._return(4, self.MESSAGE + 0x100)
        elif addr in (
            ad.CASTLE_COMMAND_SENDER_EXIT,
            ad.CASTLE_COMMAND_RECEIVER_FAIL,
            ad.COMMAND_BUTTON_SIDECAR_CTOR + 6,
        ):
            self.exit = addr
            cpu.emu_stop()
        elif addr == ad.CASTLE_BEHAVIOR_START_UNPACK:
            assert cpu.reg_read(UC_X86_REG_ECX) == self.BEHAVIOR
            self.explicit.append(self.read(sp + 8))
            super()._hook(cpu, addr, size, user)
        else:
            super()._hook(cpu, addr, size, user)

    def parse(self, name: str, button: int | None = None, *, extra: bool = False) -> None:
        self.tokens = [name.encode("ascii")]
        if extra:
            self.tokens.append(b"extra")
        self.cpu.reg_write(UC_X86_REG_ESP, self.STACK)
        self.cpu.reg_write(UC_X86_REG_EBP, self.STACK + 0x100)
        self.write(self.STACK, self.STOP)
        for i, value in enumerate((self.FACTORY, button or self.BUTTON, 0xDEADBEEF, 0)):
            self.write(self.STACK + 4 + i * 4, value)
        self.cpu.emu_start(self.command.label_va("parse"), self.STOP, count=100000)
        assert self.cpu.reg_read(UC_X86_REG_ESP) == self.STACK + 4

    def dispatch(self, label: str, *, success: bool = True) -> None:
        self.exit = 0
        self.cpu.reg_write(UC_X86_REG_ESP, self.STACK)
        self.cpu.reg_write(UC_X86_REG_EBP, self.STACK + 0x100)
        self.write(self.STACK + 0x108, self.MESSAGE)
        self.cpu.reg_write(
            UC_X86_REG_ESI, self.BUTTON if label in ("send", "button_ctor") else self.BEHAVIOR
        )
        self.cpu.reg_write(UC_X86_REG_EDI, self.OBJECT)
        self.cpu.reg_write(UC_X86_REG_EBX, 0)
        self.cpu.reg_write(UC_X86_REG_ECX, self.BUTTON)
        self.cpu.reg_write(UC_X86_REG_EFLAGS, 2 if success else 0x42)
        self.cpu.mem_write(self.MESSAGE + ad.GAME_MESSAGE_ARGUMENT_COUNT, bytes([len(self.args)]))
        self.cpu.emu_start(self.command.label_va(label), self.STOP, count=100000)
        assert self.cpu.reg_read(UC_X86_REG_ESP) == self.STACK
        assert self.cpu.reg_read(UC_X86_REG_ESI) == (
            self.BUTTON if label in ("send", "button_ctor") else self.BEHAVIOR
        )
        assert self.cpu.reg_read(UC_X86_REG_EDI) == self.OBJECT
        assert self.cpu.reg_read(UC_X86_REG_EBX) == 0


def test_parse_sidecar_and_constructor_reuse() -> None:
    e = Buttons()
    before = bytes(e.cpu.mem_read(e.BUTTON, ad.COMMAND_BUTTON_SIZE))
    e.parse("RohanCastleLarge")
    assert bytes(e.cpu.mem_read(e.BUTTON, ad.COMMAND_BUTTON_SIZE)) == before
    assert e.read(e.CONFIG + cp.COMMAND_BUTTON_OFF) == e.BUTTON
    assert e.read(e.CONFIG + cp.COMMAND_BUTTON_OFF + 4) == cp._prefab_id("RohanCastleLarge")
    assert e.interned == ["RohanCastleLarge"]
    e.dispatch("button_ctor")
    assert e.read(e.CONFIG + cp.COMMAND_BUTTON_OFF) == 0
    e.dispatch("send")
    assert e.created == [ad.MSG_CASTLE_UNPACK]
    assert e.args == []


@pytest.mark.parametrize("configured", [False, True])
def test_sender_stock_or_extended(configured: bool) -> None:
    e = Buttons()
    if configured:
        e.parse("RohanCastleLarge")
    e.dispatch("send")
    assert e.created == [ad.MSG_CASTLE_UNPACK]
    assert e.args == (
        [(0, cp.COMMAND_MAGIC), (0, cp._prefab_id("RohanCastleLarge"))] if configured else []
    )
    assert e.exit == ad.CASTLE_COMMAND_SENDER_EXIT


@pytest.mark.parametrize(
    "args",
    [
        [],
        [(0, cp.COMMAND_MAGIC)],
        [(0, 123), (0, cp._prefab_id("RohanCastleLarge"))],
        [(1, cp.COMMAND_MAGIC), (0, cp._prefab_id("RohanCastleLarge"))],
        [(0, cp.COMMAND_MAGIC), (1, cp._prefab_id("RohanCastleLarge"))],
        [(0, cp.COMMAND_MAGIC), (0, 456)],
    ],
)
def test_receiver_invalid_retail_fallback(args: list[tuple[int, int]]) -> None:
    e = Buttons()
    e.parse("RohanCastleLarge")
    e.args = args
    e.dispatch("receive")
    assert e.started == 1
    assert e.free_flags == [0]
    assert e.explicit == [0]
    assert e.read(e.BASE + cp.TABLE_OFF) == 0


@pytest.mark.parametrize("success", [False, True])
def test_valid_payload_only_after_retail_checks(success: bool) -> None:
    e = Buttons()
    e.parse("RohanCastleLarge")
    e.args = [(0, cp.COMMAND_MAGIC), (0, cp._prefab_id("RohanCastleLarge")), (9, 123)]
    e.dispatch("receive", success=success)
    assert e.started == int(success)
    assert bool(e.arg_reads) == success
    assert e.read(e.BASE + cp.TABLE_OFF) == (e.BEHAVIOR if success else 0)
    assert e.read(e.BASE + cp.PENDING_OFF) == 0
    if success:
        assert e.names == [e.key + 1]
        assert e.explicit == [0]
        assert e.free_flags == [0]
        assert e.run("resolve") == e.key + 1
        e.run("destroy")
        assert e.read(e.BASE + cp.TABLE_OFF) == 0


@pytest.mark.parametrize("reverse", [False, True])
def test_collision_quarantines_both_names(reverse: bool) -> None:
    e = Buttons()
    names = ["Castle_12443256909038804325", "Castle_9189280535366551549"]
    if reverse:
        names.reverse()
    e.parse(names[0])
    e.parse(names[1], e.BUTTON + 0x400)
    assert e.read(e.CONFIG + 4) == 1
    assert e.read(e.CONFIG + cp.COMMAND_PREFAB_OFF + 4) == 0
    e.dispatch("send")
    assert e.args == []
    e.args = [(0, cp.COMMAND_MAGIC), (0, cp._prefab_id(names[0]))]
    e.dispatch("receive")
    assert e.read(e.BASE + cp.TABLE_OFF) == 0
    e.parse(names[0])
    assert e.read(e.CONFIG + cp.COMMAND_PREFAB_OFF + 4) == 0


@pytest.mark.parametrize(
    "name,extra", [("", False), ("x" * 256, False), ("a b", False), ("Valid", True)]
)
def test_invalid_parser_clears_previous_config(name: str, extra: bool) -> None:
    e = Buttons()
    e.parse("RohanCastleLarge")
    e.parse(name, extra=extra)
    e.dispatch("send")
    assert e.args == []
    assert e.read(e.CONFIG) == 1


def test_lookup_walks_beyond_recycled_hole() -> None:
    e = Buttons()
    e.parse("First", e.BUTTON + 0x400)
    e.parse("Second")
    e.write(e.CONFIG + cp.COMMAND_BUTTON_OFF, 0)
    e.dispatch("send")
    assert e.args == [(0, cp.COMMAND_MAGIC), (0, cp._prefab_id("Second"))]


def test_repeated_name_reuses_id_and_namekey() -> None:
    e = Buttons()
    e.parse("RohanCastleLarge")
    e.parse("RohanCastleLarge", e.BUTTON + 0x400)
    assert e.interned == ["RohanCastleLarge"]
    assert e.read(e.CONFIG + cp.COMMAND_PREFAB_OFF + cp.COMMAND_PREFAB_STRIDE) == 0
    assert e.read(e.CONFIG + cp.COMMAND_BUTTON_OFF + 12) == cp._prefab_id("RohanCastleLarge")


def test_persistent_core_full_falls_back() -> None:
    e = Buttons()
    e.parse("RohanCastleLarge")
    for i in range(cp.MAX_OVERRIDES):
        e.write(e.BASE + cp.TABLE_OFF + i * cp.SLOT_SIZE, 0x123000 + i)
    before = bytes(e.cpu.mem_read(e.BASE + cp.TABLE_OFF, cp.MAX_OVERRIDES * cp.SLOT_SIZE))
    e.args = [(0, cp.COMMAND_MAGIC), (0, cp._prefab_id("RohanCastleLarge"))]
    e.dispatch("receive")
    assert e.started == 1
    assert bytes(e.cpu.mem_read(e.BASE + cp.TABLE_OFF, len(before))) == before
    assert e.read(e.BASE + cp.PENDING_OFF) == 0


@pytest.mark.parametrize("table", ["button", "prefab"])
def test_config_capacity_falls_back(table: str) -> None:
    e = Buttons()
    rows, start, stride = (
        (cp.COMMAND_BUTTON_ROWS, cp.COMMAND_BUTTON_OFF, 8)
        if table == "button"
        else (cp.COMMAND_PREFAB_ROWS, cp.COMMAND_PREFAB_OFF, cp.COMMAND_PREFAB_STRIDE)
    )
    for i in range(rows):
        e.write(e.CONFIG + start + i * stride, 0x123000 + i)
    e.parse("RohanCastleLarge")
    assert e.read(e.CONFIG + 8) == 1
    e.dispatch("send")
    assert e.args == []
