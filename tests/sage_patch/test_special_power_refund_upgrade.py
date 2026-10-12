"""Tests for SpecialPowerRefundUpgrade and its Worldbuilder parser twin.

Structural checks first: the hook, the field table, the copied vtables and the grown ModuleData.
Apply is then run under an emulator against small stand-ins for the engine lookups it makes - the
controlling player, the spellbook object, the template store and the module search - with the
engine's own `ftol`, `getFinalOverride` and `setReadyFrame` bytes, so that what is checked is the
refund arithmetic, which powers are left alone, and the register and stack contract.
"""

from __future__ import annotations

import faulthandler
import struct
from pathlib import Path

import pytest

from sage_ini.engine import parse_type
from sage_patch.addresses import (
    ASCII_STRING_COPY_CTOR,
    FTOL,
    GAME_DATA_ASCIISTRING_PARSER,
    GAME_LOGIC_FRAME,
    GET_FINAL_OVERRIDE,
    INI_PARSE_PERCENT_TO_REAL,
    OBJECT_GET_CONTROLLING_PLAYER,
    OBJECT_GET_SPECIAL_POWER_MODULE,
    OBJECT_IMAGE_UPGRADE_REGISTER,
    OBJECT_IMAGE_UPGRADE_RUNTIME_FACTORY_STOCK,
    OBJECT_IMAGE_UPGRADE_UPGRADE_VTABLE,
    PLAYER_GET_SPELLBOOK_OBJECT,
    SPECIAL_POWER_REFUND_UPGRADE_REGISTER_CALL,
    SPECIAL_POWER_START_POWER_RECHARGE,
    SPECIAL_POWER_STORE_FIND_TEMPLATE,
    THE_GAME_LOGIC,
    THE_SPECIAL_POWER_STORE,
    WORLDBUILDER_INI_PARSE_PERCENT_TO_REAL,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_PARSER,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER,
    WORLDBUILDER_OBJECT_IMAGE_UPGRADE_RUNTIME_FACTORY_STOCK,
    WORLDBUILDER_SPECIAL_POWER_REFUND_UPGRADE_REGISTER_CALL,
)
from sage_patch.patches import SpecialPowerRefundUpgradePatch as Exported
from sage_patch.patches import SpecialPowerRefundUpgradeWorldbuilderPatch as ExportedWorldbuilder
from sage_patch.patches.grant_science_upgrade import (
    GrantScienceUpgradePatch,
    GrantScienceUpgradeWorldbuilderPatch,
)
from sage_patch.patches.object_image_upgrade import ObjectImageUpgradePatch
from sage_patch.patches.special_power_refund_upgrade import (
    BLOCK_NAME,
    MODULEDATA_SIZE,
    POWER_FIELD,
    REFUND_FIELD,
    SECTION_NAME,
    WORLDBUILDER_SECTION_NAME,
    SpecialPowerRefundUpgradePatch,
    SpecialPowerRefundUpgradeWorldbuilderPatch,
)
from sage_patch.patches.utils import tooltip_twin
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import special_power_refund_upgrade_worldbuilder_image

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


@pytest.fixture
def image() -> bytearray:
    if not _GAME_DAT.exists():
        pytest.skip("repository game.dat fixture is absent")
    return bytearray(_GAME_DAT.read_bytes())


@pytest.fixture
def patched(image: bytearray) -> bytearray:
    SpecialPowerRefundUpgradePatch().apply(image)
    return image


@pytest.fixture
def wb_image() -> bytearray:
    return special_power_refund_upgrade_worldbuilder_image()


def _read(data: bytes | bytearray, va: int, size: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + size])


def _body(image: bytearray, section: str, patch, start: str, end: str | None) -> bytes:
    base, section_off, _size = find_section(image, section) or pytest.fail("missing section")
    code = patch._assemble(base)
    begin = section_off + code.label_va(start) - base
    finish = section_off + (
        code.label_va(end) - base if end else code.base_va - base + len(code.finish())
    )
    return bytes(image[begin:finish])


def _call_targets(body: bytes, va: int) -> list[int]:
    return [
        va + index + 5 + struct.unpack_from("<i", body, index + 1)[0]
        for index in range(len(body) - 4)
        if body[index] == 0xE8
    ]


def _rows(image: bytearray, table_va: int) -> list[tuple[str, int, int, int]]:
    rows = []
    for index in range(3):
        name_va, parser, userdata, offset = struct.unpack(
            "<4I", _read(image, table_va + 16 * index, 16)
        )
        name = _read(image, name_va, 32).split(b"\0")[0].decode() if name_va else ""
        rows.append((name, parser, userdata, offset))
    return rows


def test_apply_verify_and_detect(image: bytearray) -> None:
    patch = SpecialPowerRefundUpgradePatch()
    assert patch.detect(image) is None
    patch.apply(image)
    assert patch.verify(image) == []
    assert patch.detect(image) is not None


def test_second_application_fails(image: bytearray) -> None:
    patch = SpecialPowerRefundUpgradePatch()
    patch.apply(image)
    with pytest.raises(ValueError, match="unexpected build|overlapping patch"):
        patch.apply(image)


@pytest.mark.parametrize("order", [(0, 1, 2), (2, 1, 0), (1, 2, 0)])
def test_composes_with_the_other_tooltip_twins(image: bytearray, order: tuple[int, ...]) -> None:
    patches = [
        ObjectImageUpgradePatch(),
        GrantScienceUpgradePatch(),
        SpecialPowerRefundUpgradePatch(),
    ]
    for index in order:
        patches[index].apply(image)
    assert all(patch.verify(image) == [] for patch in patches)


def test_hook_replaces_only_the_remove_upgrade_registration_call(image: bytearray) -> None:
    stock = bytes(image)
    SpecialPowerRefundUpgradePatch().apply(image)
    off = va_to_offset(image, SPECIAL_POWER_REFUND_UPGRADE_REGISTER_CALL)
    assert off is not None
    assert image[off] == 0xE8
    assert image[off - 19 : off] == stock[off - 19 : off]
    assert image[off + 5 : off + 32] == stock[off + 5 : off + 32]


def test_field_table_is_a_string_row_and_a_percent_row(patched: bytearray) -> None:
    patch = SpecialPowerRefundUpgradePatch()
    base, _off, _size = find_section(patched, SECTION_NAME) or pytest.fail("missing section")
    assert _rows(patched, patch._layout(base)["table"]) == [
        ("SpecialPower", GAME_DATA_ASCIISTRING_PARSER, 0, 0x138),
        ("RefundPercent", INI_PARSE_PERCENT_TO_REAL, 0, 0x140),
        ("", 0, 0, 0),
    ]


def test_the_percentage_gets_its_own_bytes_past_the_two_strings(patched: bytearray) -> None:
    # Tooltip's ModuleData ends in AsciiStrings at +0x138 and +0x13C, both destroyed with it.
    assert POWER_FIELD[1] == 0x138
    assert REFUND_FIELD[1] == tooltip_twin.MODULEDATA_SIZE == 0x140
    assert MODULEDATA_SIZE == 0x144
    patch = SpecialPowerRefundUpgradePatch()
    body = _body(patched, SECTION_NAME, patch, "moduledata_factory", "build_fields")
    assert body.startswith(b"\x55\x8b\xec\x56\x68" + struct.pack("<I", MODULEDATA_SIZE))
    # Zeroed after Tooltip's constructor, which knows nothing of it.
    assert b"\x83\xa6\x40\x01\x00\x00\x00\xc7\x06" in body


def test_registration_replays_stock_then_adds_wrapped_runtime_factory(patched: bytearray) -> None:
    patch = SpecialPowerRefundUpgradePatch()
    base, _off, _size = find_section(patched, SECTION_NAME) or pytest.fail("missing section")
    code = patch._assemble(base)
    body = _body(patched, SECTION_NAME, patch, "register", "runtime_factory")
    targets = _call_targets(body, code.label_va("register"))
    assert targets.count(OBJECT_IMAGE_UPGRADE_REGISTER) == 2
    assert b"\x68" + struct.pack("<I", code.label_va("runtime_factory")) in body
    assert b"\x68" + struct.pack("<I", OBJECT_IMAGE_UPGRADE_RUNTIME_FACTORY_STOCK) not in body
    name_va = patch._layout(base)["block_name"]
    assert b"\x68" + struct.pack("<I", name_va) in body
    assert _read(patched, name_va, len(BLOCK_NAME) + 1) == BLOCK_NAME.encode() + b"\0"
    assert body.endswith(b"\xc2\x18\x00")


def test_upgrade_vtable_patches_apply_and_unapply_slots(patched: bytearray) -> None:
    patch = SpecialPowerRefundUpgradePatch()
    base, _off, _size = find_section(patched, SECTION_NAME) or pytest.fail("missing section")
    code = patch._assemble(base)
    table_va = patch._layout(base)["upgrade"]
    ours = _read(patched, table_va, 0x48)
    stock = _read(patched, OBJECT_IMAGE_UPGRADE_UPGRADE_VTABLE, 0x48)
    assert struct.unpack_from("<I", ours, 0x20)[0] == code.label_va("unapply")
    assert struct.unpack_from("<I", ours, 0x28)[0] == code.label_va("apply")
    for slot in range(0, 0x48, 4):
        if slot not in (0x20, 0x28):
            assert ours[slot : slot + 4] == stock[slot : slot + 4]


def test_apply_makes_the_script_action_lookups_in_order(patched: bytearray) -> None:
    patch = SpecialPowerRefundUpgradePatch()
    base, _off, _size = find_section(patched, SECTION_NAME) or pytest.fail("missing section")
    code = patch._assemble(base)
    body = _body(patched, SECTION_NAME, patch, "apply", "unapply")
    assert _call_targets(body, code.label_va("apply")) == [
        OBJECT_GET_CONTROLLING_PLAYER,
        PLAYER_GET_SPELLBOOK_OBJECT,
        ASCII_STRING_COPY_CTOR,
        SPECIAL_POWER_STORE_FIND_TEMPLATE,
        OBJECT_GET_SPECIAL_POWER_MODULE,
        GET_FINAL_OVERRIDE,
        FTOL,
    ]
    assert b"\x8b\x0d" + struct.pack("<I", THE_SPECIAL_POWER_STORE) in body
    # Fail closed on the second cooldown layout: the module's own startPowerRecharge decides.
    assert b"\x81\x78\x3c" + struct.pack("<I", SPECIAL_POWER_START_POWER_RECHARGE) in body
    assert body.endswith(b"\xff\x50\x20\x5f\x5e\x5b\xc3")  # setReadyFrame, then the epilogue


def test_unapply_never_takes_the_refund_back(patched: bytearray) -> None:
    patch = SpecialPowerRefundUpgradePatch()
    assert _body(patched, SECTION_NAME, patch, "unapply", None) == b"\xc3"


def test_ini_surface_declares_the_new_behavior() -> None:
    surface = SpecialPowerRefundUpgradePatch().ini_surface()
    # UpgradeBehavior, not Behavior: the block must inherit TriggeredBy, ConflictsWith and the
    # other UpgradeModule fields, or every use of it lints as unknown-attribute.
    assert [(block.name, block.base) for block in surface.blocks] == [
        (BLOCK_NAME, "UpgradeBehavior")
    ]
    assert [(field.name, field.type) for field in surface.fields] == [
        ("SpecialPower", "Ref:specialpowers"),
        ("RefundPercent", "Float"),
    ]
    assert all(parse_type(field.type)[1] == "" for field in surface.fields)


def test_registered_and_exported() -> None:
    assert Exported is SpecialPowerRefundUpgradePatch
    assert ExportedWorldbuilder is SpecialPowerRefundUpgradeWorldbuilderPatch
    assert PATCHES["special-power-refund-upgrade"] is SpecialPowerRefundUpgradePatch
    assert PATCHES["special-power-refund-upgrade-wb"] is SpecialPowerRefundUpgradeWorldbuilderPatch
    assert not SpecialPowerRefundUpgradePatch.experimental


def test_worldbuilder_apply_verify_detect(wb_image: bytearray) -> None:
    patch = SpecialPowerRefundUpgradeWorldbuilderPatch()
    assert patch.detect(wb_image) is None
    patch.apply(wb_image)
    assert patch.verify(wb_image) == []
    assert patch.detect(wb_image) is not None
    with pytest.raises(ValueError, match="unexpected Worldbuilder build|overlapping patch"):
        patch.apply(wb_image)


@pytest.mark.parametrize("first_grant_science", [True, False])
def test_worldbuilder_composes_with_grant_science_upgrade(
    wb_image: bytearray, first_grant_science: bool
) -> None:
    order = [GrantScienceUpgradeWorldbuilderPatch(), SpecialPowerRefundUpgradeWorldbuilderPatch()]
    for patch in order if first_grant_science else reversed(order):
        patch.apply(wb_image)
    assert all(patch.verify(wb_image) == [] for patch in order)


def test_worldbuilder_registers_with_stock_runtime_and_editor_parsers(wb_image: bytearray) -> None:
    patch = SpecialPowerRefundUpgradeWorldbuilderPatch()
    patch.apply(wb_image)
    base, _off, _size = find_section(wb_image, WORLDBUILDER_SECTION_NAME) or pytest.fail(
        "missing section"
    )
    code = patch._assemble(base)
    body = _body(wb_image, WORLDBUILDER_SECTION_NAME, patch, "register", "moduledata_factory")
    targets = _call_targets(body, code.label_va("register"))
    assert targets.count(WORLDBUILDER_OBJECT_IMAGE_UPGRADE_REGISTER) == 2
    assert (
        b"\x68" + struct.pack("<I", WORLDBUILDER_OBJECT_IMAGE_UPGRADE_RUNTIME_FACTORY_STOCK) in body
    )

    assert _rows(wb_image, patch._layout(base)["table"]) == [
        ("SpecialPower", WORLDBUILDER_OBJECT_IMAGE_UPGRADE_ASCIISTRING_PARSER, 0, 0x138),
        ("RefundPercent", WORLDBUILDER_INI_PARSE_PERCENT_TO_REAL, 0, 0x140),
        ("", 0, 0, 0),
    ]
    # The editor's percent parser writes +0x140 too, so its ModuleData grows as the game's does.
    factory = _body(
        wb_image, WORLDBUILDER_SECTION_NAME, patch, "moduledata_factory", "build_fields"
    )
    assert factory.startswith(b"\x55\x8b\xec\x56\x68" + struct.pack("<I", MODULEDATA_SIZE))

    hook_off = va_to_offset(wb_image, WORLDBUILDER_SPECIAL_POWER_REFUND_UPGRADE_REGISTER_CALL)
    assert hook_off is not None
    assert _call_targets(
        bytes(wb_image[hook_off : hook_off + 5]),
        WORLDBUILDER_SPECIAL_POWER_REFUND_UPGRADE_REGISTER_CALL,
    ) == [code.label_va("register")]


unicorn = pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

_PAGE = 0x1000
_HEAP = 0x20000000
_STACK = 0x30000000
_STUBS = 0x40000000
_RETURN = 0x50000000  # a `ret` lands here and the run stops

# Where the stand-ins keep what the engine lookups would find.
_OBJECT_OWNER = 0x100
_PLAYER_SPELLBOOK = 0x10
_OBJECT_POWER_MODULE = 0x20
_INTERFACE_TEMPLATE = 0x30
_GET_TEMPLATE_STUB = _STUBS  # interface slot +0x18
# The engine's `setReadyFrame`, the routine interface slot +0x20 holds in the stock vtable.
_SET_READY_FRAME = 0x0099344A
_OTHER_START_POWER_RECHARGE = 0x00991500

_STUB_CODE = {
    OBJECT_GET_CONTROLLING_PLAYER: b"\x8b\x81" + struct.pack("<I", _OBJECT_OWNER) + b"\xc3",
    PLAYER_GET_SPELLBOOK_OBJECT: b"\x8b\x41" + bytes([_PLAYER_SPELLBOOK]) + b"\xc3",
    # thiscall copy constructor, `ret 4`: the new string shares the source's handle.
    ASCII_STRING_COPY_CTOR: bytes.fromhex("8b4424048b0089018bc1c20400"),
    # The by-value name's handle points at a cell holding its template, 0 for an unknown name.
    SPECIAL_POWER_STORE_FIND_TEMPLATE: bytes.fromhex("8b4424048b00c20400"),
    OBJECT_GET_SPECIAL_POWER_MODULE: b"\x8b\x41" + bytes([_OBJECT_POWER_MODULE]) + b"\xc2\x04\x00",
    _GET_TEMPLATE_STUB: b"\x8b\x41" + bytes([_INTERFACE_TEMPLATE]) + b"\xc3",
}

_NOW = 10_000
_DURATION = 7_200  # a 240-second cooldown at 30 frames a second


class _Machine:
    """One spellbook power on cooldown, and a module about to refund part of it."""

    def __init__(self, data: bytes | bytearray) -> None:
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.mapped: set[int] = set()
        self.heap = _HEAP
        located = find_section(data, SECTION_NAME)
        assert located is not None
        base, off, size = located
        self.write(base, bytes(data[off : off + size]))
        self.apply_va = SpecialPowerRefundUpgradePatch()._assemble(base).label_va("apply")
        for va, size in ((FTOL, 0x80), (GET_FINAL_OVERRIDE, 0x18), (_SET_READY_FRAME, 0x0A)):
            self.write(va, _read(data, va, size))
        for va, code in _STUB_CODE.items():
            self.write(va, code)
        self.write(_RETURN, b"\xf4")
        self.write(_STACK, bytes(_PAGE))

        logic = self.alloc(0x80)
        self.write(logic + GAME_LOGIC_FRAME, struct.pack("<I", _NOW))
        self.write(THE_GAME_LOGIC, struct.pack("<I", logic))
        self.write(THE_SPECIAL_POWER_STORE, struct.pack("<I", self.alloc(0x10)))

        self.template = self.alloc(0x60)
        self.vtable = self.alloc(0x40)
        self.write(self.vtable + 0x18, struct.pack("<I", _GET_TEMPLATE_STUB))
        self.write(self.vtable + 0x20, struct.pack("<I", _SET_READY_FRAME))
        self.set_flavour(SPECIAL_POWER_START_POWER_RECHARGE)
        self.interface = self.alloc(0x40, struct.pack("<I", self.vtable))
        self.write(self.interface + _INTERFACE_TEMPLATE, struct.pack("<I", self.template))
        self.set_cooldown(duration=_DURATION, remaining=5_400)

        self.spellbook = self.alloc(0x40)
        self.write(self.spellbook + _OBJECT_POWER_MODULE, struct.pack("<I", self.interface))
        self.player = self.alloc(0x40)
        self.write(self.player + _PLAYER_SPELLBOOK, struct.pack("<I", self.spellbook))
        self.owner = self.alloc(0x200)
        self.write(self.owner + _OBJECT_OWNER, struct.pack("<I", self.player))

        self.name = self.alloc(0x10, struct.pack("<I", self.template))
        self.module_data = self.alloc(MODULEDATA_SIZE)
        self.set_power(self.name)
        self.set_refund(0.5)
        runtime = self.alloc(0x40)
        self.mux = runtime + 0x10
        self.write(self.mux + tooltip_twin.MUX_MODULE_DATA, struct.pack("<I", self.module_data))
        self.write(self.mux + tooltip_twin.MUX_OBJECT, struct.pack("<I", self.owner))

    def _map(self, va: int, size: int) -> None:
        was_enabled = faulthandler.is_enabled()
        faulthandler.disable()
        try:
            for page in range(va & ~0xFFF, va + size, _PAGE):
                if page not in self.mapped:
                    self.uc.mem_map(page, _PAGE)
                    self.mapped.add(page)
        finally:
            if was_enabled:
                faulthandler.enable()

    def write(self, va: int, blob: bytes) -> None:
        self._map(va, len(blob))
        self.uc.mem_write(va, blob)

    def u32(self, va: int) -> int:
        return struct.unpack("<I", bytes(self.uc.mem_read(va, 4)))[0]

    def alloc(self, size: int, blob: bytes = b"") -> int:
        va = self.heap
        self.heap += (size + 0xF) & ~0xF
        self.write(va, blob.ljust(size, b"\x00"))
        return va

    def set_flavour(self, start_power_recharge: int) -> None:
        self.write(self.vtable + 0x3C, struct.pack("<I", start_power_recharge))

    def set_cooldown(self, duration: int, remaining: int) -> None:
        self.write(self.interface + 0x04, struct.pack("<I", duration))
        self.write(self.interface + 0x08, struct.pack("<I", (_NOW + remaining) & 0xFFFFFFFF))

    def set_power(self, handle: int) -> None:
        self.write(self.module_data + POWER_FIELD[1], struct.pack("<I", handle))

    def set_refund(self, fraction: float) -> None:
        self.write(self.module_data + REFUND_FIELD[1], struct.pack("<f", fraction))

    def remaining(self) -> int:
        """Frames left on the cooldown after Apply has run, with the caller's registers and stack
        checked on the way out."""
        esp = _STACK + 0x800
        self.write(esp, struct.pack("<I", _RETURN))
        saved = {UC_X86_REG_EBX: 0x11111111, UC_X86_REG_ESI: 0x22222222, UC_X86_REG_EDI: 0x33333333}
        for register, value in saved.items():
            self.uc.reg_write(register, value)
        self.uc.reg_write(UC_X86_REG_ESP, esp)
        self.uc.reg_write(UC_X86_REG_ECX, self.mux)
        self.uc.emu_start(self.apply_va, _RETURN, count=100_000)
        assert self.uc.reg_read(UC_X86_REG_ESP) == esp + 4
        for register, value in saved.items():
            assert self.uc.reg_read(register) == value
        return self.u32(self.interface + 0x08) - _NOW


@pytest.fixture
def machine(patched: bytearray) -> _Machine:
    return _Machine(patched)


class TestApply:
    def test_half_of_a_240_second_cooldown_comes_off_what_is_left(self, machine: _Machine) -> None:
        # Sixty seconds in, 180 left: half the cooldown back leaves 60.
        assert machine.remaining() == 5_400 - 3_600

    def test_the_cooldown_length_is_not_touched(self, machine: _Machine) -> None:
        # The button clock is 1 - remaining / duration, so it jumps by the refund and no further.
        machine.remaining()
        assert machine.u32(machine.interface + 0x04) == _DURATION

    @pytest.mark.parametrize(
        ("fraction", "expected"), [(0.25, 3_600), (0.1, 4_680), (0.75, 0), (1.0, 0), (5.0, 0)]
    )
    def test_the_refund_scales_and_stops_at_ready(
        self, machine: _Machine, fraction: float, expected: int
    ) -> None:
        machine.set_refund(fraction)
        assert machine.remaining() == expected

    def test_the_refund_is_a_share_of_the_cooldown_that_was_started(
        self, machine: _Machine
    ) -> None:
        # A discounted cast starts a shorter cooldown, and the refund shrinks with it.
        machine.set_cooldown(duration=3_600, remaining=3_000)
        assert machine.remaining() == 3_000 - 1_800

    def test_the_refund_truncates_as_the_engine_does(self, machine: _Machine) -> None:
        machine.set_cooldown(duration=7_201, remaining=5_400)
        assert machine.remaining() == 5_400 - 3_600

    @pytest.mark.parametrize("fraction", [0.0, -0.5])
    def test_no_refund_or_a_negative_one_changes_nothing(
        self, machine: _Machine, fraction: float
    ) -> None:
        machine.set_refund(fraction)
        assert machine.remaining() == 5_400

    @pytest.mark.parametrize("remaining", [0, -300])
    def test_a_ready_power_is_left_alone(self, machine: _Machine, remaining: int) -> None:
        machine.set_cooldown(duration=_DURATION, remaining=remaining)
        assert machine.remaining() == remaining

    def test_a_power_that_never_recharged_is_left_alone(self, machine: _Machine) -> None:
        machine.set_cooldown(duration=0, remaining=5_400)
        assert machine.remaining() == 5_400

    def test_a_paused_power_is_left_alone(self, machine: _Machine) -> None:
        machine.write(machine.interface + 0x0C, struct.pack("<I", 1))
        assert machine.remaining() == 5_400

    def test_a_shared_timer_power_is_left_alone(self, machine: _Machine) -> None:
        machine.write(machine.template + 0x59, b"\x01")
        assert machine.remaining() == 5_400

    def test_the_second_cooldown_layout_is_left_alone(self, machine: _Machine) -> None:
        machine.set_flavour(_OTHER_START_POWER_RECHARGE)
        assert machine.remaining() == 5_400

    def test_no_special_power_line_does_nothing(self, machine: _Machine) -> None:
        machine.set_power(0)
        assert machine.remaining() == 5_400

    def test_an_unknown_power_does_nothing(self, machine: _Machine) -> None:
        machine.set_power(machine.alloc(0x10))
        assert machine.remaining() == 5_400

    @pytest.mark.parametrize(
        ("holder", "field"),
        [
            ("owner", _OBJECT_OWNER),
            ("player", _PLAYER_SPELLBOOK),
            ("spellbook", _OBJECT_POWER_MODULE),
        ],
    )
    def test_a_missing_player_spellbook_or_module_does_nothing(
        self, machine: _Machine, holder: str, field: int
    ) -> None:
        machine.write(getattr(machine, holder) + field, bytes(4))
        assert machine.remaining() == 5_400

    def test_an_object_that_is_gone_does_nothing(self, machine: _Machine) -> None:
        machine.write(machine.mux + tooltip_twin.MUX_OBJECT, bytes(4))
        assert machine.remaining() == 5_400
