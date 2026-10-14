"""Execute the retained RotWK event/money code and the patch, not a Python money model."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_ini.engine import parse_type
from sage_patch import LargeGroupBonusPatch, PillageModuleExtensionPatch, UpgradeModuleRemovalPatch
from sage_patch.addresses import (
    MONEY_AMOUNT,
    MONEY_DEPOSIT,
    MONEY_WITHDRAW,
    OBJECT_GET_CONTROLLING_PLAYER,
    OBJECT_UPGRADE_MASK,
    OPERATOR_NEW,
    PILLAGE_ANCHORS,
    PILLAGE_EVENT,
    PILLAGE_FIELD_TABLE_REF,
    PILLAGE_MODULEDATA_FACTORY,
    PILLAGE_RUNTIME_FACTORY,
    PILLAGE_WINDOWS,
    PLAYER_COMPLETED_UPGRADE_MASK,
    PLAYER_MONEY,
    PLAYER_SCORE_KEEPER,
)
from sage_patch.patches import pillage_module_extension as module
from sage_patch.patches.utils.field_tables import read_field_table, resolve_table
from sage_patch.pe import image_sections
from sage_patch.registry import PATCHES
from sage_patch.utils import file_offset, find_section


def synthetic_image() -> bytearray:
    top = max(va + len(blob) for va, blob in PILLAGE_ANCHORS.items())
    data = bytearray((top - 0x400000 + 0x11FF) & ~0x1FF)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", data, 0x84, 0x14C, 1)
    struct.pack_into("<H", data, 0x94, 0xE0)
    opt = 0x98
    struct.pack_into("<H", data, opt, 0x10B)
    for offset, value in [(28, 0x400000), (32, 0x1000), (36, 0x200), (60, 0x400)]:
        struct.pack_into("<I", data, opt + offset, value)
    size = len(data) - 0x1000
    struct.pack_into("<I", data, opt + 56, (len(data) + 0xFFF) & ~0xFFF)
    section = opt + 0xE0
    data[section : section + 8] = b".text\0\0\0"
    struct.pack_into("<IIII", data, section + 8, size, 0x1000, size, 0x1000)
    for va, blob in {**PILLAGE_ANCHORS, **PILLAGE_WINDOWS}.items():
        off = file_offset(data, va)
        data[off : off + len(blob)] = blob
    return data


@pytest.fixture
def image() -> bytearray:
    return synthetic_image()


def test_registration_surface_and_layout() -> None:
    patch = PillageModuleExtensionPatch()
    assert PATCHES[patch.name] is type(patch)
    assert not patch.experimental
    assert module._SIZE == 0x13C
    fields = patch.ini_surface().fields
    assert [f.name for f in fields] == [
        "StealAmount",
        "TriggeredBy",
        "ConflictsWith",
        "RequiresAllTriggers",
        "RequiresAllConflictingTriggers",
    ]
    assert fields[0].default is None
    for field in fields:
        assert field.block == "PillageModule"
        assert parse_type(field.type)[1] == ""
        assert field.patch == patch.name


def test_emitted_code_decodes_completely() -> None:
    capstone = pytest.importorskip("capstone")
    base = 0xF00000
    code = module._assemble(base)
    start = code.label_va("allocate")
    content = module._content(base)[start - base :]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    instructions = list(md.disasm(content, start))
    assert sum(i.size for i in instructions) == len(content)
    boundaries = {i.address for i in instructions}
    for instruction in instructions:
        if instruction.mnemonic.startswith("j") or instruction.mnemonic == "call":
            if instruction.op_str.startswith("0x"):
                target = int(instruction.op_str, 16)
                if start <= target < base + len(module._content(base)):
                    assert target in boundaries


def test_apply_verify_and_preserved_factories(image: bytearray) -> None:
    original = bytes(image)
    patch = PillageModuleExtensionPatch()
    assert patch.detect(image) is None
    patch.apply(image)
    assert patch.verify(image) == []
    assert patch.detect(image) is not None
    for va in (0x0065AB0C, 0x0065AB11, PILLAGE_RUNTIME_FACTORY):
        off = file_offset(image, va)
        assert image[off : off + 5] == original[off : off + 5]

    rows = read_field_table(
        image, resolve_table(image, (PILLAGE_FIELD_TABLE_REF,), (0x68,), "pillage")
    )
    assert len(rows) == 8
    assert rows[3][3] == module._STEAL
    assert [row[3] for row in rows[4:]] == [
        module._TRIGGER,
        module._CONFLICT,
        module._ALL_TRIGGER,
        module._ALL_CONFLICT,
    ]
    before = bytes(image)
    with pytest.raises(ValueError, match="already carries"):
        patch.apply(image)
    assert bytes(image) == before


@pytest.mark.parametrize("va", list(PILLAGE_ANCHORS) + list(PILLAGE_WINDOWS))
def test_wrong_build_or_foreign_hook_rejected_before_mutation(image: bytearray, va: int) -> None:
    image[file_offset(image, va)] ^= 1
    before = bytes(image)
    with pytest.raises(ValueError):
        PillageModuleExtensionPatch().apply(image)
    assert bytes(image) == before


@pytest.mark.parametrize("location", ["cave", *PILLAGE_WINDOWS])
def test_tampered_installation_is_not_detected(image: bytearray, location: str | int) -> None:
    patch = PillageModuleExtensionPatch()
    patch.apply(image)
    located = find_section(image, module.SECTION_NAME)
    assert located is not None
    offset = located[1] if location == "cave" else file_offset(image, int(location))
    image[offset] ^= 1
    assert patch.verify(image)
    assert patch.detect(image) is None


class World:
    """Native EH, masks, counter, transfer, Money, and GUI flow with service doubles.

    Audio/INI/renderer/filter/player lookup are modeled; the money methods and
    bookkeeping arithmetic actually execute. Every event checks callee-saved
    registers, stack cleanup and restoration of the exception chain.
    """

    data = 0x2000000
    runtime = 0x2001000
    owner = 0x2002000
    victim = 0x2003000
    attacker = 0x2004000
    target = 0x2005000
    allocation = 0x2006000
    logic = 0x2007000
    audio = 0x2008000
    audio_vtable = 0x2009000
    text = 0x200A000
    text_vtable = 0x200B000
    ui = 0x200C000
    ui_vtable = 0x200D000
    exception_chain = 0x3000000
    gdt = 0x3001000
    stack = 0x2108000
    stop = 0x13F0000
    audio_misc = 0x13F0100
    audio_dispatch = 0x13F0110
    text_fetch = 0x13F0120
    ui_display = 0x13F0130
    xfer_uint = 0x13F0140

    def __init__(self, image: bytes | bytearray, *, patched: bool = True) -> None:
        self.uni = pytest.importorskip("unicorn")
        self.reg = pytest.importorskip("unicorn.x86_const")
        self.uc = self.uni.Uc(self.uni.UC_ARCH_X86, self.uni.UC_MODE_32)
        self.uc.mem_map(0x400000, 0x1000000)
        self.uc.mem_map(0x2000000, 0x200000)
        # Use a real FS descriptor and flat 32-bit SS/DS/ES for the native EH frame.
        self.uc.mem_map(self.exception_chain, 0x2000)
        self.uc.mem_write(
            self.gdt + 8,
            struct.pack("<HHBBBB", 0xFFFF, 0, 0, 0x93, 0xCF, 3),
        )
        self.uc.mem_write(self.gdt + 16, struct.pack("<HHBBBB", 0xFFFF, 0, 0, 0x93, 0xCF, 0))
        self.uc.reg_write(self.reg.UC_X86_REG_GDTR, (0, self.gdt, 0x1000, 0))
        self.uc.reg_write(self.reg.UC_X86_REG_FS, 8)
        for name in ("SS", "DS", "ES"):
            self.uc.reg_write(getattr(self.reg, f"UC_X86_REG_{name}"), 16)
        self.uc.reg_write(self.reg.UC_X86_REG_FPTAG, 0xFFFF)
        self.uc.reg_write(self.reg.UC_X86_REG_FPCW, 0x037F)
        binary = bytearray(image)
        if patched:
            PillageModuleExtensionPatch().apply(binary)
        for section in image_sections(binary):
            self.uc.mem_write(
                section.virtual_address,
                bytes(binary[section.raw_offset : section.raw_offset + section.raw_size]),
            )
        located = find_section(binary, module.SECTION_NAME)
        self.code = None if located is None else module._assemble(located[0])
        # Real compiler EH prologue, using the isolated exception chain above.
        self.uc.mem_write(
            0xA3CEF0,
            bytes.fromhex("6aff5064a100000000508b44240c64892500000000896c240c8d6c240c50c3"),
        )
        self.uc.mem_write(
            0x79DCB3, bytes.fromhex("a12c41de0080b8980000000074078b442404014108c20400")
        )
        self.uc.mem_write(
            0x79DCCB, bytes.fromhex("a12c41de0080b89800000000740d8b442404014104018114010000c20400")
        )
        self.uc.mem_write(0xAD1920, b"\xd9\xee\xc3")  # geometry returns ST(0) = 0
        self.trace: list[tuple[str, int]] = []
        self.popups: list[int] = []
        self.accepts = True
        self.token_value = 0
        self.allocate_null = False
        self.requested_size = 0
        self.owner_player = self.attacker
        self.freed: list[int] = []
        self.xfer_values: dict[int, int] = {}
        self.loading = False
        self.w32(self.runtime + 4, self.data)
        self.w32(self.runtime + 8, self.owner)
        self.w32(self.data + 0x0C, 1)
        self.w32(0xDE412C, self.logic)
        self.uc.mem_write(self.logic + 0x98, b"\x01")
        self.w32(0xDE42FC, self.audio)
        self.w32(self.audio, self.audio_vtable)
        self.w32(self.audio_vtable + 0x138, self.audio_misc)
        self.w32(self.audio_vtable + 0x64, self.audio_dispatch)
        self.w32(0xDE4B04, self.text)
        self.w32(self.text, self.text_vtable)
        self.w32(self.text_vtable + 0x44, self.text_fetch)
        self.w32(0xDE4830, self.ui)
        self.w32(self.ui, self.ui_vtable)
        self.w32(self.ui_vtable + 0x1A0, self.ui_display)
        self.uc.hook_add(self.uni.UC_HOOK_CODE, self.hook)

    def r32(self, address: int) -> int:
        return struct.unpack("<I", self.uc.mem_read(address, 4))[0]

    def w32(self, address: int, value: int) -> None:
        self.uc.mem_write(address, struct.pack("<I", value & 0xFFFFFFFF))

    def ret(self, cleanup: int = 0, result: int = 0) -> None:
        sp = self.uc.reg_read(self.reg.UC_X86_REG_ESP)
        self.uc.reg_write(self.reg.UC_X86_REG_EAX, result)
        self.uc.reg_write(self.reg.UC_X86_REG_EIP, self.r32(sp))
        self.uc.reg_write(self.reg.UC_X86_REG_ESP, sp + 4 + cleanup)

    def hook(self, uc, address: int, size: int, user_data) -> None:
        sp = uc.reg_read(self.reg.UC_X86_REG_ESP)
        this = uc.reg_read(self.reg.UC_X86_REG_ECX)
        if address == OBJECT_GET_CONTROLLING_PLAYER:
            self.ret(result=self.owner_player if this == self.owner else self.target)
        elif address == 0x7640C1:
            assert this == self.data + 0x10
            assert (self.r32(sp + 4), self.r32(sp + 8)) == (self.victim, 0)
            self.ret(8, int(self.accepts))
        elif address in (MONEY_WITHDRAW, MONEY_DEPOSIT):
            name = "withdraw" if address == MONEY_WITHDRAW else "deposit"
            player = self.target if name == "withdraw" else self.owner_player
            assert this == player + PLAYER_MONEY
            assert self.r32(sp + 8) == player + PLAYER_SCORE_KEEPER
            assert self.r32(sp + 12) == 1
            self.trace.append((name, self.r32(sp + 4)))
        elif address == self.audio_misc:
            self.ret(4, self.audio + 0x100)
        elif address in (0x6DA95E, 0x66ECE1, self.audio_dispatch):
            self.ret(4)
        elif address in (0x6DABCB, 0x4367B0):
            self.ret()
        elif address == self.text_fetch:
            self.ret(8, self.text + 0x100)
        elif address == 0xADF7E0:
            self.popups.append(self.r32(sp + 12))
            self.ret()
        elif address == self.ui_display:
            self.ret(12)
        elif address == OPERATOR_NEW:
            self.requested_size = self.r32(sp + 4)
            self.uc.mem_write(self.allocation, b"\xcd" * (self.requested_size + 16))
            self.ret(result=0 if self.allocate_null else self.allocation)
        elif address == 0x76406F:
            self.w32(this, 0xFFFFFFFF)
            self.ret()
        elif address == 0x42DC9F:
            self.ret(4, 0x200E000)
        elif address == 0x42EA42:
            self.ret(4, self.token_value)
        elif address == 0x708270:
            assert (self.r32(sp + 4), self.r32(sp + 8)) == (self.owner, self.data)
            self.w32(this + 4, self.data)
            self.w32(this + 8, self.owner)
            self.ret(8, this)
        elif address == 0x7629B0:
            assert this == self.allocation + 0x10
            self.ret()
        elif address == 0x42F6A0:
            self.freed.append(self.r32(sp + 4))
            self.ret()
        elif address == 0x404F15:
            self.ret()
        elif address == 0x8CD4AA:
            self.ret(4)
        elif address == 0x707887:
            self.transfer_value(self.r32(sp + 8))
            self.ret()
        elif address == self.xfer_uint:
            self.transfer_value(self.r32(sp + 4))
            self.ret(4)

    def transfer_value(self, pointer: int) -> None:
        if self.loading:
            self.w32(pointer, self.xfer_values[pointer])
        else:
            self.xfer_values[pointer] = self.r32(pointer)

    def call(self, address: int, args: tuple[int, ...], *, this: int = 0, cleanup: int = 0) -> None:
        saved = {"EBX": 0x12345678, "ESI": 0x23456789, "EDI": 0x3456789A, "EBP": 0x210F000}
        for name, value in saved.items():
            self.uc.reg_write(getattr(self.reg, f"UC_X86_REG_{name}"), value)
        self.uc.reg_write(self.reg.UC_X86_REG_ESP, self.stack)
        self.uc.reg_write(self.reg.UC_X86_REG_ECX, this)
        self.uc.reg_write(self.reg.UC_X86_REG_EFLAGS, 0x202)
        before_x87 = self.uc.reg_read(self.reg.UC_X86_REG_FPTAG)
        self.w32(self.stack, self.stop)
        for index, arg in enumerate(args):
            self.w32(self.stack + 4 + index * 4, arg)
        self.uc.emu_start(address, self.stop, count=10000)
        assert self.uc.reg_read(self.reg.UC_X86_REG_EIP) == self.stop
        assert self.uc.reg_read(self.reg.UC_X86_REG_ESP) == self.stack + 4 + cleanup
        assert self.r32(self.exception_chain) == 0
        assert self.uc.reg_read(self.reg.UC_X86_REG_FPTAG) == before_x87
        for name, value in saved.items():
            assert self.uc.reg_read(getattr(self.reg, f"UC_X86_REG_{name}")) == value

    def event(self) -> None:
        self.call(PILLAGE_EVENT, (0, self.victim), this=self.runtime + 0x10, cleanup=8)

    def configure(
        self, *, payout: int = 10, cost: int | None = None, balance: int = 100, threshold: int = 1
    ) -> None:
        self.w32(self.data + 8, payout)
        self.w32(self.data + 0x0C, threshold)
        self.w32(self.target + PLAYER_MONEY + MONEY_AMOUNT, balance)
        if cost is not None:
            assert self.code is not None
            self.token_value = cost
            self.call(
                self.code.label_va("parse_steal"),
                (0x200E000, self.data, self.data + module._STEAL, 0),
            )
            assert self.r32(self.data + module._STEAL) == cost
            assert self.uc.mem_read(self.data + module._PRESENT, 1) == b"\x01"

    @property
    def balances(self) -> tuple[int, int]:
        return (
            self.r32(self.target + PLAYER_MONEY + MONEY_AMOUNT),
            self.r32(self.attacker + PLAYER_MONEY + MONEY_AMOUNT),
        )

    @property
    def counter(self) -> int:
        return self.r32(self.runtime + 0x18)


@pytest.mark.parametrize(
    "balance,payout,threshold,accepted",
    [
        (100, 10, 1, True),
        (3, 10, 2, True),
        (0, 10, 3, True),
        (100, 0, 1, True),
        (100, 10, 0, True),
        (100, 10, 1, False),
    ],
)
def test_omission_executes_identical_native_behavior(
    image, balance, payout, threshold, accepted
) -> None:
    worlds = [World(image, patched=False), World(image)]
    for world in worlds:
        world.configure(balance=balance, payout=payout, threshold=threshold)
        world.accepts = accepted
        for _ in range(5):
            world.event()
    original, patched = worlds
    assert (patched.balances, patched.counter, patched.trace, patched.popups) == (
        original.balances,
        original.counter,
        original.trace,
        original.popups,
    )
    for player in (patched.target, patched.attacker):
        assert patched.uc.mem_read(player + PLAYER_SCORE_KEEPER, 0x118) == original.uc.mem_read(
            player + PLAYER_SCORE_KEEPER, 0x118
        )


@pytest.mark.parametrize(
    "balance,cost,payout,expected",
    [
        (100, 10, 10, (90, 10)),
        (3, 4, 10, (3, 0)),
        (3, 3, 10, (0, 10)),
        (3, 2, 10, (1, 10)),
        (3, 0, 10, (3, 10)),
        (0, 0, 10, (0, 10)),
        (20, 10, 0, (10, 0)),
        (20, 10, 4, (10, 4)),
        (0, 0, 0, (0, 0)),
        (0xFFFFFFFF, 0xFFFFFFFF, 10, (0, 10)),
        (0xFFFFFFFE, 0xFFFFFFFF, 10, (0xFFFFFFFE, 0)),
    ],
)
def test_independent_all_or_nothing_native_transfer(image, balance, cost, payout, expected) -> None:
    world = World(image)
    world.configure(balance=balance, cost=cost, payout=payout)
    world.event()
    assert world.balances == expected
    assert world.counter == 0
    assert world.popups == ([payout] if payout > 0 and balance >= cost else [])
    assert world.r32(world.target + PLAYER_SCORE_KEEPER + 8) == (cost if balance >= cost else 0)
    assert world.r32(world.attacker + PLAYER_SCORE_KEEPER + 4) == expected[1]
    if balance < cost:
        assert world.trace == []


def test_unaffordable_threshold_is_consumed(image) -> None:
    world = World(image)
    world.configure(cost=10, balance=5, threshold=3)
    for expected in [1, 2, 0, 1]:
        world.event()
        assert world.counter == expected
    assert world.balances == (5, 0)
    assert world.trace == world.popups == []


@pytest.mark.parametrize(
    "trigger,conflict,all_trigger,all_conflict,object_mask,player_mask,active",
    [
        (1, 0, 0, 0, 0, 0, False),
        (1, 0, 0, 0, 1, 0, True),
        (1, 0, 0, 0, 0, 1, True),
        (3, 0, 1, 0, 1, 2, False),
        (3, 0, 1, 0, 3, 0, True),
        (3, 0, 1, 0, 0, 3, True),
        (0, 1, 0, 0, 1, 0, False),
        (1, 1, 0, 0, 1, 0, False),
        (0, 3, 0, 1, 1, 0, True),
        (0, 3, 0, 1, 3, 0, False),
        (0, 3, 0, 1, 1, 2, True),
        (0, 3, 0, 1, 0, 3, False),
    ],
)
def test_upgrade_gate_preserves_partial_counter(
    image, trigger, conflict, all_trigger, all_conflict, object_mask, player_mask, active
) -> None:
    world = World(image)
    world.configure(cost=2, threshold=3)
    world.w32(world.runtime + 0x18, 1)
    for offset, value in [(module._TRIGGER, trigger), (module._CONFLICT, conflict)]:
        world.w32(world.data + offset, value)
    world.uc.mem_write(world.data + module._ALL_TRIGGER, bytes([all_trigger, all_conflict]))
    world.w32(world.owner + OBJECT_UPGRADE_MASK, object_mask)
    world.w32(world.attacker + PLAYER_COMPLETED_UPGRADE_MASK, player_mask)
    world.event()
    assert world.counter == (2 if active else 1)
    assert world.trace == []


def test_grant_remove_regrant_and_native_filter(image) -> None:
    world = World(image)
    world.configure(cost=2, threshold=3)
    world.w32(world.data + module._TRIGGER, 1)
    world.event()
    assert world.counter == 0
    world.w32(world.owner + OBJECT_UPGRADE_MASK, 1)
    world.event()
    assert world.counter == 1
    world.w32(world.owner + OBJECT_UPGRADE_MASK, 0)
    world.event()
    assert world.counter == 1
    world.w32(world.owner + OBJECT_UPGRADE_MASK, 1)
    world.accepts = False
    world.event()
    assert world.counter == 1
    world.accepts = True
    world.event()
    world.event()
    assert world.counter == 0
    assert world.balances == (98, 10)


@pytest.mark.parametrize("null", [False, True])
def test_native_factory_allocates_and_initializes_tail(image, null) -> None:
    world = World(image)
    world.allocate_null = null
    world.call(PILLAGE_MODULEDATA_FACTORY, (0,))
    assert world.requested_size == module._SIZE
    assert world.uc.reg_read(world.reg.UC_X86_REG_EAX) == (0 if null else world.allocation)
    if not null:
        assert world.uc.mem_read(world.allocation + 0x14, module._SIZE - 0x14) == bytes(
            module._SIZE - 0x14
        )
        assert world.r32(world.allocation + 4) == 0xCDCDCDCD  # do not repurpose unknown base field
        assert world.uc.mem_read(world.allocation + module._SIZE, 16) == b"\xcd" * 16


def test_runtime_factory_preserves_interfaces_and_size(image) -> None:
    world = World(image)
    world.call(PILLAGE_RUNTIME_FACTORY, (world.owner, world.data))
    assert world.requested_size == 0x1C
    assert world.r32(world.allocation + 4) == world.data
    assert world.r32(world.allocation + 8) == world.owner
    for offset, expected in [
        (0, 0xC60DCC),
        (0x0C, 0xC60D10),
        (0x10, 0xC60D04),
        (0x14, 0),
        (0x18, 0),
    ]:
        assert world.r32(world.allocation + offset) == expected
    assert world.uc.mem_read(world.allocation + 0x1C, 16) == b"\xcd" * 16


def test_enlarged_data_uses_original_unsized_deletion(image) -> None:
    world = World(image)
    world.call(PILLAGE_MODULEDATA_FACTORY, (0,))
    world.call(0x654D4E, (1,), this=world.allocation, cleanup=4)
    assert world.freed == [world.allocation]
    assert world.r32(world.allocation) == 0xBD15B0


def test_native_xfer_round_trips_partial_counter_without_new_state(image) -> None:
    world = World(image)
    world.w32(world.runtime + 0x14, 123)
    world.w32(world.runtime + 0x18, 2)
    xfer, vtable = 0x200F000, 0x200F100
    world.w32(xfer, vtable)
    world.w32(vtable + 0x78, world.xfer_uint)
    world.call(0x888247, (xfer,), this=world.runtime, cleanup=4)
    assert world.xfer_values == {world.runtime + 0x14: 123, world.runtime + 0x18: 2}
    world.w32(world.runtime + 0x14, 0)
    world.w32(world.runtime + 0x18, 0)
    world.loading = True
    world.call(0x888247, (xfer,), this=world.runtime, cleanup=4)
    assert world.counter == 2
    assert world.r32(world.runtime + 0x14) == 123


def test_player_change_and_last_upgrade_mask_word(image) -> None:
    world = World(image)
    world.configure(cost=2, threshold=2)
    last = 35 * 4
    world.w32(world.data + module._TRIGGER + last, 0x80000000)
    world.w32(world.attacker + PLAYER_COMPLETED_UPGRADE_MASK + last, 0x80000000)
    world.event()
    assert world.counter == 1
    world.owner_player = 0x2010000
    world.event()
    assert world.counter == 1
    world.w32(world.owner_player + PLAYER_COMPLETED_UPGRADE_MASK + last, 0x80000000)
    world.event()
    assert world.counter == 0
    assert world.r32(world.owner_player + PLAYER_MONEY + MONEY_AMOUNT) == 10
    assert world.balances == (98, 0)


def test_presence_uses_store_pointer_and_explicit_zero_overrides(image) -> None:
    world = World(image)
    assert world.code is not None
    for value in (0xFFFFFFFF, 0):
        world.token_value = value
        # An enclosing instance need not be the data base; the field pointer is decisive.
        world.call(
            world.code.label_va("parse_steal"),
            (0x200E000, 0x200F000, world.data + module._STEAL, 0),
        )
        assert world.r32(world.data + module._STEAL) == value
        assert world.uc.mem_read(world.data + module._PRESENT, 1) == b"\x01"


def test_unowned_object_with_unmet_gate_never_counts(image) -> None:
    world = World(image)
    world.configure(cost=0)
    world.owner_player = 0
    world.w32(world.data + module._TRIGGER, 1)
    world.event()
    assert world.counter == 0
    assert world.trace == []


_BINARY = Path(__file__).resolve().parents[2] / "tools/BFME-FILES/game.dat.backup"


@pytest.mark.full
@pytest.mark.skipif(not _BINARY.is_file(), reason="requires the supported local RotWK binary")
def test_real_binary_native_paths_and_patch_composition() -> None:

    original = _BINARY.read_bytes()
    for companion in (LargeGroupBonusPatch(), UpgradeModuleRemovalPatch()):
        for reverse in (False, True):
            data = bytearray(original)
            patches = [PillageModuleExtensionPatch(), companion]
            for patch in reversed(patches) if reverse else patches:
                patch.apply(data)
            assert all(patch.verify(data) == [] for patch in patches)
    native, patched = World(original, patched=False), World(original)
    for world in (native, patched):
        world.configure(balance=3, threshold=2)
        for _ in range(4):
            world.event()
    assert (patched.balances, patched.trace, patched.popups) == (
        native.balances,
        native.trace,
        native.popups,
    )
    extended = World(original)
    extended.configure(cost=0, balance=0)
    extended.event()
    assert extended.balances == (0, 10)
    assert _BINARY.read_bytes() == original
