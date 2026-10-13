"""Execute the emitted wrappers with mocked engine boundaries, without game data."""

from __future__ import annotations

import faulthandler
import struct
from itertools import permutations
from pathlib import Path

import pytest

from sage_patch import addresses as addr
from sage_patch.patches.command_point_cost import CommandPointCostPatch
from sage_patch.patches.commandset import CommandSetLimitPatch
from sage_patch.patches.experimental.command_range_flyout import (
    ANCHORS,
    FIXED_PATCHES,
    HOOKS,
    SUPPORTED_COMMANDS,
    CommandRangeFlyoutPatch,
    build_code,
)
from sage_patch.patches.multi_select_group import MultiSelectGroupPatch
from sage_patch.patches.queue_ignore_cp import QueueIgnoreCpPatch
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import _sparse_image

pytest.importorskip("unicorn")
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EDX,
    UC_X86_REG_EIP,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

TEST_BUTTON_NAME = b"Any_Mod_CommandRange_Opener"
BASE = 0xF00000
END = 0xF10000
OWNER = 0x2000000
PARENT = OWNER + 0x1000
BUTTON = OWNER + 0x2000
BAR = OWNER + 0x3000
CONTEXT = OWNER + 0x4000
DRAWABLE = OWNER + 0x5000
SET = OWNER + 0x6000
ALT_SET = OWNER + 0x7000
GUI = OWNER + 0x8000
STACK = 0x3010000


def _image() -> bytearray:
    refs = {
        site: bytes([opcode]) + struct.pack("<I", addr.COMMAND_BUTTON_RANGE_START_FIELD)
        for site, opcode in zip(
            addr.COMMAND_BUTTON_FIELD_TABLE_REFS,
            addr.COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES,
            strict=True,
        )
    }
    return _sparse_image(ANCHORS | HOOKS | {k: v[0] for k, v in FIXED_PATCHES.items()} | refs)


class Machine:
    def __init__(self, stance: int = 3, start: int = 11, count: int = 3) -> None:
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        # Unicorn catches an internal SEH fault during mapping on Windows.
        enabled = faulthandler.is_enabled()
        faulthandler.disable()
        try:
            self.uc.mem_map(0x400000, 0xC00000)
            self.uc.mem_map(OWNER, 0x10000)
            self.uc.mem_map(0x3000000, 0x20000)
        finally:
            if enabled:
                faulthandler.enable()
        code, self.entries = build_code(BASE)
        self.uc.mem_write(BASE, code)
        self.calls: list[tuple[int, list[int]]] = []
        self.native_dispatch = False
        self.active_command = 0
        self.availability = 1
        self.alternate = False
        self.missing = False
        self.inactive = False
        self.dispatch_success = True
        self.stale = False
        self.stance = stance
        self.start = start
        self.slots: list[int] = []
        self.w(OWNER + 0x14, PARENT)
        self.w(OWNER + 8, OWNER + 0x9000)
        self.w(PARENT + 0x10, PARENT + 0x300)
        self.uc.mem_write(PARENT + 0x304, struct.pack("<H", len(TEST_BUTTON_NAME)))
        self.uc.mem_write(PARENT + 0x308, TEST_BUTTON_NAME + b"\0")
        self.uc.mem_write(PARENT + 0x139, b"\x03")
        self.w(PARENT + 0x14, 57)
        self.w(PARENT + 0x22C, start)
        self.w(PARENT + 0x230, count)
        self.w(BUTTON + 0x44, BUTTON + 0x500)
        self.w(BUTTON + 0x14, 14)
        self.uc.mem_write(BUTTON + 0x105, b"\1")
        self.w(addr.THE_COMMAND_SET_STORE, BAR)
        self.w(addr.THE_PLAYER_LIST, OWNER + 0x9100)
        self.w(addr.THE_GAME_LOGIC, OWNER + 0x9100)
        self.w(BAR + 0x6C, DRAWABLE)
        self.w(DRAWABLE + 0xFC, CONTEXT)
        self.uc.mem_write(addr.COMMAND_SET_CAPACITY_IMMEDIATE, b"\x21")
        self.w(addr.THE_IN_GAME_UI, OWNER + 0xA000)
        self.w(OWNER + 0xA000, OWNER + 0xA100)
        self.w(OWNER + 0xA100 + 0x124, END + 0x100)
        self.w(OWNER + 0xA200, OWNER + 0xA300)
        self.w(OWNER + 0xA300, OWNER + 0xA400)
        self.w(OWNER + 0xA400, OWNER + 0xA300)
        self.w(OWNER + 0xA408, DRAWABLE)
        self.w(OWNER + 0xC, OWNER + 0xB000)
        self.w(OWNER + 0xB000, addr.PALANTIR_STANCE_FACTORY_VTABLE)
        self.w(OWNER + 0xB010, OWNER + 0xB300)
        self.w(OWNER + 0xB300, OWNER + 0xB200)
        self.w(OWNER + 0xB200, addr.PALANTIR_FLYOUT_WRAPPER_VTABLE)
        self.w(addr.PALANTIR_STANCE_FACTORY_VTABLE + 0x10, END + 0x200)
        self.w(GUI + 8, OWNER)
        self.w(GUI + 0xC, stance)
        self.w(addr.THE_MESSAGE_STREAM, OWNER + 0xC000)
        self.w(OWNER + 0xC000, OWNER + 0xC100)
        self.w(OWNER + 0xC148, END + 0x300)
        self.w(OWNER + 0xA1C0, END + 0x400)
        self.w(OWNER + 0xA1BC, END + 0x500)
        self.uc.hook_add(UC_HOOK_CODE, self.on_code)

    def w(self, address: int, value: int) -> None:
        self.uc.mem_write(address, struct.pack("<I", value & 0xFFFFFFFF))

    def r(self, address: int) -> int:
        return struct.unpack("<I", self.uc.mem_read(address, 4))[0]

    def on_code(self, uc: Uc, address: int, size: int, data: object) -> None:
        if BASE <= address < BASE + 0x1000:
            return
        if self.native_dispatch and 0x94086A <= address < 0x941AC3:
            if address == addr.CONTROL_BAR_COMMAND_ACCEPTED:
                uc.reg_write(UC_X86_REG_EIP, END)
            return
        counts = {
            addr.GAME_MESSAGE_APPEND_INTEGER: 1,
            addr.ARG_APPENDERS[3]: 1,
            addr.COMMAND_BUTTON_UPDATE_FOR_CONTEXT: 2,
            0x688D3C: 0,
            addr.STANCE_FIND_INDEX: 1,
            END + 0x300: 1,
            END + 0x400: 0,
            END + 0x500: 1,
            addr.COMMAND_BUTTON_SET_STANCE_INDEX: 1,
            addr.COMMAND_BUTTON_STANCE_GUI_DATA: 0,
            addr.STANCE_GUI_VALUES_SET: 2,
            addr.COMMAND_BUTTON_INI_INTEGER_PARSER: 4,
            addr.COMMAND_UI_GET_OBJECT_ID: 0,
            addr.GAME_LOGIC_FIND_OBJECT_BY_ID: 1,
            addr.PLAYER_LIST_LOCAL_IS_NOT_ACTIVE: 0,
            addr.OBJECT_GET_COMMAND_SET_STRING: 0,
            addr.OBJECT_GET_ALTERNATE_COMMAND_SET_OBJECT: 0,
            addr.COMMAND_SET_STORE_FIND_COMMAND_SET: 1,
            addr.COMMAND_SET_GET_COMMAND_BUTTON: 1,
            addr.CONTROL_BAR_GET_COMMAND_AVAILABILITY: 5,
            addr.CONTROL_BAR_EXECUTE_COMMAND_BUTTON: 3,
            addr.STANCE_FLYOUT_SELECT: 1,
            addr.FLYOUT_SET_STATE: 1,
            addr.FLYOUT_IS_ACTIVE: 0,
            addr.FLYOUT_REQUEST_CLOSE: 0,
            END + 0x100: 0,
            END + 0x200: 0,
        }
        assert address in counts, hex(address)
        sp = uc.reg_read(UC_X86_REG_ESP)
        args = [self.r(sp + 4 + i * 4) for i in range(counts[address])]
        self.calls.append((address, args))
        ecx = uc.reg_read(UC_X86_REG_ECX)
        result = 0
        if address == addr.STANCE_FIND_INDEX:
            assert uc.reg_read(UC_X86_REG_EDI) == PARENT
            result = {2: 0, 3: 1, 1: 2}.get(args[0], 0xFFFFFFFF)
        elif address == END + 0x300:
            assert ecx == OWNER + 0xC000
            result = OWNER + 0xC200
        elif address == addr.GAME_MESSAGE_APPEND_INTEGER:
            assert ecx == OWNER + 0xC200
        elif address == addr.ARG_APPENDERS[3]:
            assert ecx == OWNER + 0xC200
        elif address == 0x688D3C:
            assert ecx == BUTTON + 0x500
            result = ecx
        elif address == addr.COMMAND_BUTTON_UPDATE_FOR_CONTEXT:
            assert ecx == BUTTON
            assert args == [CONTEXT, 1]
        elif address == END + 0x400:
            assert ecx == OWNER + 0xA000
            result = self.active_command
        elif address == END + 0x500:
            assert ecx == OWNER + 0xA000
            self.active_command = args[0]
        elif address == addr.COMMAND_BUTTON_SET_STANCE_INDEX:
            assert ecx == PARENT
            self.w(PARENT + 0xFC, args[0])
        elif address == addr.COMMAND_BUTTON_STANCE_GUI_DATA:
            assert ecx == PARENT
            result = PARENT + 0x400
        elif address == addr.STANCE_GUI_VALUES_SET:
            assert args == [self.r(OWNER + 0x10), PARENT + 0x400]
        elif address == addr.COMMAND_BUTTON_INI_INTEGER_PARSER:
            self.w(args[2], args[0])  # Substitute the token reader, not the field tracking.
        elif address == addr.COMMAND_UI_GET_OBJECT_ID:
            result = 42
        elif address == addr.GAME_LOGIC_FIND_OBJECT_BY_ID:
            assert args == [42]
            result = 0 if self.stale else CONTEXT
        elif address == addr.PLAYER_LIST_LOCAL_IS_NOT_ACTIVE:
            result = int(self.inactive)
        elif address == addr.OBJECT_GET_COMMAND_SET_STRING:
            assert ecx == CONTEXT
            result = CONTEXT + 0x438
        elif address == addr.OBJECT_GET_ALTERNATE_COMMAND_SET_OBJECT:
            assert ecx == CONTEXT
            result = CONTEXT + 0x1000 if self.alternate else 0
        elif address == addr.COMMAND_SET_STORE_FIND_COMMAND_SET:
            assert ecx == BAR
            result = ALT_SET if args == [CONTEXT + 0x1070] else SET
        elif address == addr.COMMAND_SET_GET_COMMAND_BUTTON:
            assert ecx == (ALT_SET if self.alternate else SET)
            self.slots.append(args[0])
            result = PARENT if args[0] == 0 else (0 if self.missing else BUTTON)
        elif address == addr.CONTROL_BAR_GET_COMMAND_AVAILABILITY:
            assert ecx == BAR
            assert args[:3] == [BUTTON, 0, CONTEXT]
            assert args[4] == 0
            self.w(args[3], 0)
            result = self.availability
        elif address == addr.CONTROL_BAR_EXECUTE_COMMAND_BUTTON:
            assert ecx == BAR
            assert args == [BUTTON, 1, 0]
            result = int(self.dispatch_success)
        elif address == addr.STANCE_FLYOUT_SELECT:
            assert ecx == OWNER
            assert args == [self.stance]
        elif address == addr.FLYOUT_SET_STATE:
            assert ecx == GUI
        elif address == END + 0x100:
            result = OWNER + 0xA200
        elif address == END + 0x200:
            result = OWNER + 0xB200
        elif address == addr.FLYOUT_IS_ACTIVE:
            result = 1
        elif address == addr.FLYOUT_REQUEST_CLOSE:
            assert ecx == OWNER + 0xB200
        # Exercise the caller-save ABI; FindStanceIndex alone is caller-cleaned.
        uc.reg_write(UC_X86_REG_EAX, result)
        uc.reg_write(UC_X86_REG_ECX, 0xCCCCCCCC)
        uc.reg_write(UC_X86_REG_EDX, 0xDDDDDDDD)
        uc.reg_write(UC_X86_REG_EIP, self.r(sp))
        uc.reg_write(
            UC_X86_REG_ESP,
            sp
            + 4
            + (
                0
                if address
                in (
                    addr.STANCE_FIND_INDEX,
                    addr.STANCE_GUI_VALUES_SET,
                    addr.COMMAND_BUTTON_INI_INTEGER_PARSER,
                )
                else 4 * len(args)
            ),
        )

    def run(self, state: bool = False) -> None:
        self.calls.clear()
        self.slots.clear()
        registers = {
            UC_X86_REG_EBX: 0x111,
            UC_X86_REG_ESI: 0x222,
            UC_X86_REG_EDI: 0x333,
            UC_X86_REG_EBP: 0x444,
        }
        for reg, value in registers.items():
            self.uc.reg_write(reg, value)
        self.uc.reg_write(UC_X86_REG_ECX, GUI if state else OWNER)
        self.uc.reg_write(UC_X86_REG_ESP, STACK)
        self.w(STACK, END)
        self.w(STACK + 4, 6 if state else self.stance)
        entry = addr.STANCE_FLYOUT_STATE_CALL if state else addr.STANCE_FLYOUT_CLICK_CALL
        self.uc.emu_start(self.entries[entry], END, count=100000)
        assert self.uc.reg_read(UC_X86_REG_EIP) == END
        assert self.uc.reg_read(UC_X86_REG_ESP) == STACK + 8
        for reg, value in registers.items():
            assert self.uc.reg_read(reg) == value

    def called(self, address: int) -> list[list[int]]:
        return [args for target, args in self.calls if target == address]


@pytest.mark.parametrize("stance,slot", [(2, 11), (3, 12), (1, 13)])
@pytest.mark.parametrize("alternate", [False, True])
def test_absolute_range_and_effective_set(stance: int, slot: int, alternate: bool) -> None:
    m = Machine(stance)
    m.alternate = alternate
    m.run()
    assert m.slots == [0, slot]
    assert m.called(addr.CONTROL_BAR_EXECUTE_COMMAND_BUTTON) == [[BUTTON, 1, 0]]
    assert m.called(addr.FLYOUT_REQUEST_CLOSE) == [[]]
    assert not m.called(addr.STANCE_FLYOUT_SELECT)


@pytest.mark.parametrize("status", range(9))
def test_availability_and_click_recheck(status: int) -> None:
    m = Machine()
    m.availability = status
    m.run(state=True)
    assert m.called(addr.FLYOUT_SET_STATE) == [[6 if status in (1, 2) else 1]]
    m.availability = 3
    m.run()
    assert not m.called(addr.CONTROL_BAR_EXECUTE_COMMAND_BUTTON)
    assert not m.called(addr.STANCE_FLYOUT_SELECT)


@pytest.mark.parametrize("state", [False, True])
def test_vanilla_stance_preserves_call(state: bool) -> None:
    m = Machine()
    m.uc.mem_write(PARENT + 0x139, b"\0")
    m.run(state)
    assert (
        m.calls == [(addr.FLYOUT_SET_STATE, [6])]
        if state
        else m.calls == [(addr.STANCE_FLYOUT_SELECT, [3])]
    )


@pytest.mark.parametrize("start,count", [(-1, 3), (32, 3), (11, 0), (11, 4), (11, -1)])
def test_invalid_ranges_disable(start: int, count: int) -> None:
    m = Machine(start=start, count=count)
    m.run(True)
    assert m.called(addr.FLYOUT_SET_STATE) == [[1]]
    m.run()
    assert not m.called(addr.CONTROL_BAR_EXECUTE_COMMAND_BUTTON)


@pytest.mark.parametrize("capacity", [33, 64, 127])
def test_reads_installed_capacity(capacity: int) -> None:
    m = Machine(stance=1, start=capacity - 3)
    m.uc.mem_write(addr.COMMAND_SET_CAPACITY_IMMEDIATE, bytes([capacity]))
    m.run()
    assert m.slots[-1] == capacity - 1
    assert m.called(addr.CONTROL_BAR_EXECUTE_COMMAND_BUTTON)


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "inactive",
        "stale",
        "multi",
        "selection",
        "null",
        "targeting",
        "power",
        "disabled",
        "unknown_stance",
        "no_owner",
    ],
)
def test_fail_closed(case: str) -> None:
    m = Machine()
    if case in ("missing", "inactive", "stale"):
        setattr(m, case, True)
    elif case == "multi":
        m.w(BAR + 0x70, 7)
    elif case == "selection":
        m.w(OWNER + 0xA400, OWNER + 0xA500)
    elif case == "null":
        m.w(BAR + 0x6C, 0)
    elif case == "targeting":
        m.w(BUTTON + 0x1C, 1)
    elif case == "power":
        m.w(BUTTON + 0x14, 3)
    elif case == "disabled":
        m.uc.mem_write(BUTTON + 0x105, b"\0")
    elif case == "unknown_stance":
        m.stance = 8
        m.w(GUI + 0xC, 8)
    else:
        m.w(OWNER + 8, 0)
    m.run(True)
    assert m.called(addr.FLYOUT_SET_STATE) == [[1]]
    m.run()
    assert not m.called(addr.CONTROL_BAR_EXECUTE_COMMAND_BUTTON)
    assert not m.called(addr.STANCE_FLYOUT_SELECT)


def test_failed_dispatch_does_not_request_close() -> None:
    m = Machine()
    m.dispatch_success = False
    m.run()
    assert m.called(addr.CONTROL_BAR_EXECUTE_COMMAND_BUTTON)
    assert not m.called(addr.FLYOUT_REQUEST_CLOSE)


def test_registration_signatures_and_tamper_detection() -> None:
    p = CommandRangeFlyoutPatch()
    assert PATCHES[p.name] is type(p)
    assert p.author == "Ostkannit" and p.experimental and not p.runtime_verified
    data = _image()
    p.apply(data)
    assert p.verify(data) == []
    assert type(p.detect(data)) is type(p)
    section = find_section(data, ".cmdfly")
    assert section is not None
    data[section[1] + 20] ^= 1
    assert p.verify(data)
    assert p.detect(data) is None


@pytest.mark.parametrize("site", list(ANCHORS) + list(HOOKS) + list(FIXED_PATCHES))
def test_refuses_modified_dependencies_before_writing(site: int) -> None:
    data = _image()
    off = va_to_offset(data, site)
    assert off is not None
    data[off] ^= 1
    before = bytes(data)
    with pytest.raises(ValueError, match="signature mismatch"):
        CommandRangeFlyoutPatch().apply(data)
    assert data == before


@pytest.mark.full
@pytest.mark.parametrize("count", [33, 64, 127])
@pytest.mark.parametrize("reverse", [False, True])
def test_stock_image_composition(count: int, reverse: bool) -> None:
    path = Path(__file__).resolve().parents[2] / "tools/BFME-FILES/game.dat.backup"
    if not path.exists():
        pytest.skip("RotWK stock image not present")
    data = bytearray(path.read_bytes())
    patches = [CommandRangeFlyoutPatch()]
    if count > 33:
        patches.append(CommandSetLimitPatch(count))
    if reverse:
        patches.reverse()
    for patch in patches:
        patch.apply(data)
    for patch in patches:
        assert patch.verify(data) == []


@pytest.mark.parametrize("field", [OWNER + 0xB000, OWNER + 0xB200])
def test_other_ui_factories_keep_original_behavior(field: int) -> None:
    m = Machine()
    m.w(field, 0x123456)
    m.run()
    assert m.calls == [(addr.STANCE_FLYOUT_SELECT, [3])]
    m.run(True)
    assert m.calls == [(addr.FLYOUT_SET_STATE, [6])]


@pytest.mark.parametrize(
    "site", [addr.STANCE_OWNER_NOTIFY_INDEX_CALL, addr.STANCE_OWNER_INITIAL_INDEX_CALL]
)
@pytest.mark.parametrize("flags", [0, 1, 2, 3])
def test_external_stance_and_initial_binding_do_not_replace_range_icon(
    site: int, flags: int
) -> None:
    m = Machine()
    m.w(PARENT + 0xFC, 1)
    m.uc.mem_write(PARENT + 0x139, bytes([flags]))
    m.uc.reg_write(UC_X86_REG_ESI, OWNER)
    m.uc.reg_write(UC_X86_REG_ECX, PARENT)
    m.uc.reg_write(UC_X86_REG_ESP, STACK)
    m.w(STACK, END)
    m.w(STACK + 4, 2)
    m.uc.emu_start(m.entries[site], END, count=10000)
    assert m.r(PARENT + 0xFC) == (1 if flags == 3 else 2)
    assert m.uc.reg_read(UC_X86_REG_ESP) == STACK + 8
    assert m.uc.reg_read(UC_X86_REG_ESI) == OWNER
    assert bool(m.called(addr.COMMAND_BUTTON_SET_STANCE_INDEX)) == (flags != 3)


@pytest.mark.parametrize("stance,index", [(2, 0), (3, 1), (1, 2)])
@pytest.mark.parametrize("success", [False, True])
def test_only_successful_click_updates_presentation(stance: int, index: int, success: bool) -> None:
    m = Machine(stance)
    m.w(PARENT + 0xFC, 9)
    m.dispatch_success = success
    m.run()
    assert m.r(PARENT + 0xFC) == (index if success else 9)
    assert bool(m.called(addr.STANCE_GUI_VALUES_SET)) == success
    assert not m.called(addr.STANCE_FLYOUT_SELECT)


@pytest.mark.parametrize("reverse", [False, True])
def test_parser_tracks_both_explicit_fields_in_either_order(reverse: bool) -> None:
    m = Machine()
    m.uc.mem_write(PARENT + 0x139, b"\0")
    m.w(PARENT + 0x14, 0)  # Command may be parsed later.
    fields = [
        (addr.COMMAND_BUTTON_RANGE_START_FIELD, 0x22C, 0, 1),
        (addr.COMMAND_BUTTON_RANGE_COUNT_FIELD, 0x230, 33, 2),
    ]
    if reverse:
        fields.reverse()
    seen = 0
    for row, offset, value, flag in fields:
        m.uc.reg_write(UC_X86_REG_ESP, STACK)
        for i, arg in enumerate([END, value, PARENT, PARENT + offset, 0]):
            m.w(STACK + 4 * i, arg)
        m.uc.emu_start(m.entries[row + 4], END, count=10000)
        seen |= flag
        assert m.uc.mem_read(PARENT + 0x139, 1) == bytes([seen])
        assert m.r(PARENT + offset) == value
        assert m.uc.reg_read(UC_X86_REG_ESP) == STACK + 4
    # Explicit default values count as present too, and integer values stay unchanged.
    assert m.r(PARENT + 0x22C) == 0 and m.r(PARENT + 0x230) == 33


@pytest.mark.parametrize("flags", [0, 1, 2])
def test_missing_either_field_keeps_stock_stances(flags: int) -> None:
    m = Machine()
    m.uc.mem_write(PARENT + 0x139, bytes([flags]))
    m.run()
    assert m.calls == [(addr.STANCE_FLYOUT_SELECT, [3])]


def test_non_stance_command_is_never_opted_in() -> None:
    m = Machine()
    m.w(PARENT + 0x14, 55)
    m.run()
    assert m.calls == [(addr.STANCE_FLYOUT_SELECT, [3])]


def test_padding_initialization_and_override_copy_preserve_neighbors() -> None:
    m = Machine()
    m.uc.mem_write(PARENT + 0x134, b"\xa5" * 12)
    init = FIXED_PATCHES[addr.COMMAND_BUTTON_RANGE_FLAGS_INIT][1]
    copy = FIXED_PATCHES[addr.COMMAND_BUTTON_RANGE_FLAGS_COPY][1]
    # Execute the actual replacement instructions independently of the large engine routines.
    m.uc.mem_write(BASE + 0xE00, init + b"\xc3")
    m.uc.reg_write(UC_X86_REG_ESI, PARENT)
    m.uc.reg_write(UC_X86_REG_EBX, 0)
    m.uc.reg_write(UC_X86_REG_ESP, STACK)
    m.w(STACK, END)
    m.uc.emu_start(BASE + 0xE00, END, count=100)
    assert m.r(PARENT + 0x138) == 0
    assert m.r(PARENT + 0x134) == m.r(PARENT + 0x13C) == 0xA5A5A5A5
    m.w(BUTTON + 0x138, 0x301)
    m.uc.mem_write(BASE + 0xE80, copy + b"\x59\xc3")
    m.uc.reg_write(UC_X86_REG_EBP, BUTTON)
    m.uc.reg_write(UC_X86_REG_EBX, PARENT)
    m.uc.reg_write(UC_X86_REG_ESP, STACK)
    m.uc.emu_start(BASE + 0xE80, END, count=100)
    assert m.r(PARENT + 0x138) == 0x301
    assert m.r(PARENT + 0x134) == m.r(PARENT + 0x13C) == 0xA5A5A5A5


@pytest.mark.full
@pytest.mark.parametrize("order", list(permutations(range(4))))
def test_composes_with_commandbutton_field_patches(order: tuple[int, ...]) -> None:
    path = Path(__file__).resolve().parents[2] / "tools/BFME-FILES/game.dat.backup"
    if not path.exists():
        pytest.skip("RotWK stock image not present")
    data = bytearray(path.read_bytes())
    patches = [
        CommandRangeFlyoutPatch(),
        QueueIgnoreCpPatch(),
        CommandPointCostPatch(),
        MultiSelectGroupPatch(),
    ]
    for index in order:
        patches[index].apply(data)
    for patch in patches:
        assert patch.verify(data) == [], patch.name


def test_name_is_irrelevant_to_activation() -> None:
    m = Machine()
    m.w(PARENT + 0x10, 0)
    m.run()
    assert m.called(addr.CONTROL_BAR_EXECUTE_COMMAND_BUTTON)


def test_refuses_mismatched_live_table_without_mutation() -> None:
    data = _image()
    ref = va_to_offset(data, addr.COMMAND_BUTTON_FIELD_TABLE_REFS[0])
    assert ref is not None
    data[ref + 1 : ref + 5] = struct.pack("<I", addr.COMMAND_BUTTON_RANGE_COUNT_FIELD)
    before = bytes(data)
    with pytest.raises(ValueError, match="disagree"):
        CommandRangeFlyoutPatch().apply(data)
    assert data == before


@pytest.mark.parametrize("range_owner", [False, True])
@pytest.mark.parametrize("stance", [1, 2, 3])
def test_set_stance_hotkey_preserves_order_without_range_presentation(
    range_owner: bool, stance: int
) -> None:
    m = Machine(stance)
    m.uc.mem_write(PARENT + 0x139, bytes([3 if range_owner else 0]))
    m.w(PARENT + 0xFC, 7)
    m.uc.reg_write(UC_X86_REG_ECX, OWNER)
    m.uc.reg_write(UC_X86_REG_ESP, STACK)
    m.w(STACK, END)
    m.w(STACK + 4, stance)
    m.uc.emu_start(m.entries[addr.STANCE_HOTKEY_SELECT_CALL], END, count=10000)
    assert m.uc.reg_read(UC_X86_REG_ESP) == STACK + 8
    assert m.r(PARENT + 0xFC) == 7
    if range_owner:
        assert m.calls == [(END + 0x300, [0x468]), (addr.GAME_MESSAGE_APPEND_INTEGER, [stance])]
    else:
        assert m.calls == [(addr.STANCE_FLYOUT_SELECT, [stance])]


@pytest.mark.parametrize("command", list(SUPPORTED_COMMANDS))
def test_supported_commands_use_native_dispatch(command: int) -> None:
    m = Machine()
    m.w(BUTTON + 0x14, command)
    m.run(True)
    assert m.called(addr.FLYOUT_SET_STATE) == [[6]]
    m.run()
    assert m.called(addr.CONTROL_BAR_EXECUTE_COMMAND_BUTTON) == [[BUTTON, 1, 0]]
    assert m.called(addr.COMMAND_BUTTON_SET_STANCE_INDEX) == [[1]]


@pytest.mark.parametrize("command", [23, 24, 37])
@pytest.mark.parametrize("target_flags", [1, 2, 4, 0x20, 0x200, 7, 0x227])
def test_power_and_weapon_target_modes_are_forwarded(command: int, target_flags: int) -> None:
    m = Machine()
    m.w(BUTTON + 0x14, command)
    m.w(BUTTON + 0x1C, target_flags)
    m.run()
    assert m.called(addr.CONTROL_BAR_EXECUTE_COMMAND_BUTTON) == [[BUTTON, 1, 0]]
    assert m.r(BUTTON + 0x1C) == target_flags
    assert m.r(BUTTON + 0xC4) == 0  # No fabricated or borrowed GameWindow.


@pytest.mark.parametrize("command", [3, 5, 6, 7, 16, 22, 25, 32, 38, 46, 53, 55, 56, 57, 58])
def test_unreviewed_command_categories_stay_disabled(command: int) -> None:
    m = Machine()
    m.w(BUTTON + 0x14, command)
    m.run(True)
    assert m.called(addr.FLYOUT_SET_STATE) == [[1]]
    m.run()
    assert not m.called(addr.CONTROL_BAR_EXECUTE_COMMAND_BUTTON)


@pytest.mark.parametrize("flags", [0x80000, 0x10000000, 0x20000000, 0x80000000])
def test_passive_script_autocast_cancel_options_stay_disabled(flags: int) -> None:
    m = Machine()
    m.w(BUTTON + 0x14, 24)
    m.w(BUTTON + 0x1C, flags)
    m.run()
    assert not m.called(addr.CONTROL_BAR_EXECUTE_COMMAND_BUTTON)


@pytest.mark.parametrize("command", [24, 37])
def test_missing_special_power_template_is_disabled(command: int) -> None:
    m = Machine()
    m.w(BUTTON + 0x14, command)
    m.w(BUTTON + 0x44, 0)
    m.run()
    assert not m.called(addr.CONTROL_BAR_EXECUTE_COMMAND_BUTTON)


@pytest.mark.full
@pytest.mark.parametrize("target_flags", [1, 2, 4, 0x20, 0x200])
@pytest.mark.parametrize("already_active", [False, True])
def test_stock_dispatch_enters_or_cancels_real_target_mode(
    target_flags: int, already_active: bool
) -> None:
    path = Path(__file__).resolve().parents[2] / "tools/BFME-FILES/game.dat.backup"
    if not path.exists():
        pytest.skip("RotWK stock image not present")
    data = path.read_bytes()
    m = Machine()
    start = addr.CONTROL_BAR_COMMAND_TARGET_ROUTE
    off = va_to_offset(data, start)
    assert off is not None
    m.uc.mem_write(start, data[off : off + 0x941AC3 - start])
    m.native_dispatch = True
    m.active_command = BUTTON if already_active else 0
    m.w(BUTTON + 0x14, 24)
    m.w(BUTTON + 0x1C, target_flags)
    m.uc.reg_write(UC_X86_REG_ESI, BUTTON)
    m.uc.reg_write(UC_X86_REG_EBP, STACK + 0x100)
    m.uc.reg_write(UC_X86_REG_ESP, STACK)
    m.w(STACK + 0x10C, 1)  # Native left-click argument, after availability has succeeded.
    m.uc.emu_start(start, END, count=10000)
    assert m.uc.reg_read(UC_X86_REG_EIP) == END
    assert m.active_command == (0 if already_active else BUTTON)
    assert not m.called(END + 0x300)  # Target selection sends no immediate order.
    assert m.r(BUTTON + 0xC4) == 0


@pytest.mark.full
def test_supported_command_ids_match_stock_names_and_dispatch_cases() -> None:
    path = Path(__file__).resolve().parents[2] / "tools/BFME-FILES/game.dat.backup"
    if not path.exists():
        pytest.skip("RotWK stock image not present")
    data = path.read_bytes()
    for command, expected in SUPPORTED_COMMANDS.items():
        off = va_to_offset(data, 0xDA4D10 + 4 * command)
        assert off is not None
        name = va_to_offset(data, struct.unpack_from("<I", data, off)[0])
        assert name is not None
        assert data[name : data.index(0, name)].decode("ascii") == expected
        indices = va_to_offset(data, addr.CONTROL_BAR_COMMAND_DISPATCH_INDICES)
        table = va_to_offset(data, addr.CONTROL_BAR_COMMAND_DISPATCH_TABLE)
        assert indices is not None and table is not None
        case = struct.unpack_from("<I", data, table + 4 * data[indices + command - 1])[0]
        assert case not in (0x940485, addr.CONTROL_BAR_COMMAND_ACCEPTED)


@pytest.mark.full
@pytest.mark.parametrize(
    "command,message,integers,objects",
    [
        (14, 0x435, [], []),
        (23, 0x40D, [2, 5], []),
        (24, 0x410, [123, 0], [0, 0]),
        (37, 0x410, [123, 0], [0, 42]),
        (45, 0x457, [], [42]),
        (51, 0x45D, [], []),
        (59, 0x46E, [], []),
        (60, 0x46F, [], []),
    ],
)
def test_stock_immediate_dispatch_payloads(
    command: int, message: int, integers: list[int], objects: list[int]
) -> None:
    path = Path(__file__).resolve().parents[2] / "tools/BFME-FILES/game.dat.backup"
    if not path.exists():
        pytest.skip("RotWK stock image not present")
    data = path.read_bytes()
    m = Machine()
    start = addr.CONTROL_BAR_COMMAND_TARGET_ROUTE
    off = va_to_offset(data, start)
    assert off is not None
    m.uc.mem_write(start, data[off : off + 0x941B9F - start])
    m.native_dispatch = True
    m.w(BUTTON + 0x14, command)
    m.w(BUTTON + 0x80, 2)
    m.w(BUTTON + 0xA0, 5)
    m.w(BUTTON + 0x514, 123)
    m.w(CONTEXT + 0x74, 42)
    m.uc.reg_write(UC_X86_REG_ESI, BUTTON)
    m.uc.reg_write(UC_X86_REG_EBX, CONTEXT)
    m.uc.reg_write(UC_X86_REG_EBP, STACK + 0x100)
    m.uc.reg_write(UC_X86_REG_ESP, STACK)
    m.w(STACK + 0x10C, 1)
    m.uc.emu_start(start, END, count=10000)
    assert m.uc.reg_read(UC_X86_REG_EIP) == END
    assert m.called(END + 0x300) == [[message]]
    assert m.called(addr.GAME_MESSAGE_APPEND_INTEGER) == [[v] for v in integers]
    assert m.called(addr.ARG_APPENDERS[3]) == [[v] for v in objects]
    assert not m.called(addr.STANCE_FLYOUT_SELECT)
