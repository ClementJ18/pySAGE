"""Tests for `visible-hotkeys`.

The round trip runs on a sparse image carrying the stock bytes at every site and anchor. The cave is
then *executed* under Unicorn against a modelled control bar: the engine's own `winGetStatus`,
`GameWindow::getData` and `GAME_WINDOW_GET_COMMAND_BUTTON` bytes, and its own hidden / enabled
methods, with only the click stubbed to record which window it was handed.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    GAME_WINDOW_GET_COMMAND_BUTTON,
    GAME_WINDOW_GET_DATA,
    THE_COMMAND_SET_STORE,
)
from sage_patch.patches.visible_hotkeys import (
    ANCHORS,
    CTOR_VTABLE_IMM_VA,
    HANDLER_VTABLE,
    HOOK_ORIGINAL,
    HOOK_RESUME,
    HOOK_VA,
    OPERATOR_NEW,
    SECTION_NAME,
    SLOT_COUNT,
    STOCK_CLICK,
    STOCK_IS_ENABLED,
    STOCK_IS_HIDDEN,
    VisibleHotkeysPatch,
    build_section,
    layout,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import _sparse_image

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


def stand_in() -> bytearray:
    return _sparse_image({HOOK_VA: HOOK_ORIGINAL, **ANCHORS})


class TestRoundTrip:
    def test_apply_verify_detect(self):
        data = stand_in()
        VisibleHotkeysPatch().apply(data)
        assert VisibleHotkeysPatch().verify(data) == []
        assert isinstance(VisibleHotkeysPatch.detect(data), VisibleHotkeysPatch)

    def test_the_constructor_stamps_the_cave_vtable(self):
        data = stand_in()
        VisibleHotkeysPatch().apply(data)
        section_va = find_section(data, SECTION_NAME)[0]
        stamped = struct.unpack_from("<I", data, va_to_offset(data, CTOR_VTABLE_IMM_VA))[0]
        assert stamped == layout(section_va)["vtable"]

    def test_the_cave_vtable_keeps_the_stock_destructor(self):
        """The map frees handlers through slot 0; only the three query/click slots change."""
        vtable_off = layout(0)["vtable"]
        dtor = struct.unpack_from("<I", build_section(0), vtable_off)[0]
        assert dtor == struct.unpack_from("<I", ANCHORS[HANDLER_VTABLE])[0]

    def test_an_unpatched_image_is_not_detected(self):
        assert VisibleHotkeysPatch.detect(stand_in()) is None

    def test_a_moved_handler_is_refused(self):
        data = stand_in()
        data[va_to_offset(data, STOCK_IS_HIDDEN)] ^= 0xFF
        with pytest.raises(ValueError, match="hotkey handler"):
            VisibleHotkeysPatch().apply(data)

    def test_a_second_apply_is_refused(self):
        data = stand_in()
        VisibleHotkeysPatch().apply(data)
        with pytest.raises(ValueError):
            VisibleHotkeysPatch().apply(data)

    def test_registered(self):
        assert PATCHES["visible-hotkeys"] is VisibleHotkeysPatch

    @pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
    def test_round_trip_on_game_dat(self):
        data = bytearray(_GAME_DAT.read_bytes())
        VisibleHotkeysPatch().apply(data)
        assert VisibleHotkeysPatch().verify(data) == []


# Executed

CAVE = 0x01000000
HEAP = 0x02000000
CONTROL_BAR = HEAP
WINDOWS = HEAP + 0x1000  # 0x40 bytes per window
WINDOW_DATA = HEAP + 0x3000  # 0x20 bytes per window's data block
BUTTONS = HEAP + 0x5000  # opaque button identities
LETTERS = HEAP + 0x6000  # AsciiString data blocks for the letters
HANDLERS = HEAP + 0x7000
CLICKED = HEAP + 0x8000  # where the stubbed click writes the window it got
ALLOCATED = HEAP + 0x8100  # what the stubbed operator new returns
STACK = 0x03000000
RETURN = 0x04000000  # a mapped `hlt`, the sentinel every call returns to

HIDDEN, ENABLED = 0x10, 0x08


class Machine:
    """The engine's control bar, as far as the cave reads it."""

    def __init__(self) -> None:
        unicorn = pytest.importorskip("unicorn")
        from unicorn.x86_const import UC_X86_REG_ESP  # noqa: PLC0415

        self._uc_mod = unicorn
        self.uc = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
        self.esp_reg = UC_X86_REG_ESP
        for base, size in (
            (0x00400000, 0x00C00000),
            (CAVE, 0x1000),
            (HEAP, 0x10000),
            (STACK, 0x10000),
            (RETURN, 0x1000),
        ):
            self.uc.mem_map(base, size)
        self.uc.mem_write(RETURN, b"\xf4")
        for va, blob in ANCHORS.items():
            self.uc.mem_write(va, blob)
        # The click: record the window `[ecx+8]` names, answer "handled", `ret 4` like the real one.
        self.uc.mem_write(
            STOCK_CLICK, b"\x8b\x41\x08\xa3" + struct.pack("<I", CLICKED) + b"\xb0\x01\xc2\x04\x00"
        )
        self.uc.mem_write(OPERATOR_NEW, b"\xb8" + struct.pack("<I", ALLOCATED) + b"\xc3")
        self.uc.mem_write(CAVE, build_section(CAVE))
        self.uc.mem_write(THE_COMMAND_SET_STORE, struct.pack("<I", CONTROL_BAR))
        for slot in range(SLOT_COUNT):
            self.uc.mem_write(CONTROL_BAR + 0xDC + slot * 4, struct.pack("<I", self.window(slot)))
            self.uc.mem_write(
                self.window(slot) + 0x2C, struct.pack("<I", WINDOW_DATA + slot * 0x20)
            )
            self.set_status(slot, 0)

    @staticmethod
    def window(slot: int) -> int:
        return WINDOWS + slot * 0x40

    def set_status(self, slot: int, status: int) -> None:
        self.uc.mem_write(self.window(slot) + 8, struct.pack("<I", status))

    def bind(self, slot: int, button: int) -> None:
        """What `setControlCommand` leaves behind: the window's data names the button."""
        self.uc.mem_write(WINDOW_DATA + slot * 0x20 + 0x14, struct.pack("<I", button))

    def read32(self, va: int) -> int:
        return struct.unpack("<I", self.uc.mem_read(va, 4))[0]

    def _run(self, start: int, until: int, esp: int, **regs: int) -> int:
        from unicorn import x86_const as x  # noqa: PLC0415

        for name, value in regs.items():
            self.uc.reg_write(getattr(x, f"UC_X86_REG_{name.upper()}"), value)
        self.uc.reg_write(self.esp_reg, esp)
        self.uc.emu_start(start, until, count=100_000)
        return self.uc.reg_read(x.UC_X86_REG_EAX)

    def register(self, slot: int, button: int, letter: str) -> None:
        """Run the registration hook as `setControlCommand` reaches it for `slot`."""
        self.bind(slot, button)
        string = LETTERS + slot * 0x10
        self.uc.mem_write(string, struct.pack("<IHH", 1, 1, 2) + letter.encode() + b"\x00")
        frame = STACK + 0x8000
        self.uc.mem_write(frame - 0x14, struct.pack("<I", CONTROL_BAR))
        esp = STACK + 0x4000
        eax = self._run(
            layout(CAVE)["code"],
            HOOK_RESUME,
            esp,
            eax=string,
            esi=button,
            edi=self.window(slot),
            ebp=frame,
        )
        assert eax == ALLOCATED, "the displaced allocation still runs"
        assert self.uc.reg_read(self.esp_reg) == esp - 4, "only the 0xC argument is left pushed"

    def handler(self, slot: int) -> int:
        """A slot handler as the stock constructor builds it, stamped with the cave's vtable."""
        handler = HANDLERS + slot * 0x10
        vtable = layout(CAVE)["vtable"]
        self.uc.mem_write(handler, struct.pack("<III", vtable, 1, self.window(slot)))
        return handler

    def method(self, slot: int, index: int, flag: int = 0) -> int:
        """Call vtable slot `index` (1 hidden, 2 enabled, 3 click) on `slot`'s handler."""
        handler = self.handler(slot)
        target = self.read32(layout(CAVE)["vtable"] + index * 4)
        esp = STACK + 0x4000
        self.uc.mem_write(esp, struct.pack("<II", RETURN, flag))
        eax = self._run(target, RETURN, esp, ecx=handler, ebx=0x11, esi=0x22, edi=0x33, ebp=0x44)
        from unicorn import x86_const as x  # noqa: PLC0415

        assert self.uc.reg_read(self.esp_reg) == esp + 8, "ret 4, like the stock method"
        regs = (x.UC_X86_REG_EBX, x.UC_X86_REG_ESI, x.UC_X86_REG_EDI, x.UC_X86_REG_EBP)
        assert [self.uc.reg_read(r) for r in regs] == [0x11, 0x22, 0x33, 0x44]
        return eax & 0xFF

    def hidden(self, slot: int) -> int:
        return self.method(slot, 1)

    def enabled(self, slot: int) -> int:
        return self.method(slot, 2)

    def click(self, slot: int) -> int:
        """The window the stock click was handed."""
        self.uc.mem_write(CLICKED, b"\x00" * 4)
        assert self.method(slot, 3) == 1
        return self.read32(CLICKED)


def button(n: int) -> int:
    return BUTTONS + n * 4


@pytest.fixture
def bar() -> Machine:
    return Machine()


class TestExecuted:
    def test_dwarven_foundation_the_third_variant_answers(self, bar: Machine):
        """Three barracks variants in slots 2, 4, 6 share `K`; only the last is shown. Stock would
        give the letter to slots 2 and 4, both hidden, and the shown one would have none."""
        for slot, n in ((2, 1), (4, 2), (6, 3)):
            bar.register(slot, button(n), "K")
        bar.set_status(2, HIDDEN)
        bar.set_status(4, HIDDEN)
        bar.set_status(6, ENABLED)
        assert bar.hidden(2) == 0
        assert bar.enabled(2) == 1
        assert bar.click(2) == bar.window(6)

    def test_nothing_visible_carries_it_so_nothing_fires(self, bar: Machine):
        for slot, n in ((2, 1), (4, 2)):
            bar.register(slot, button(n), "K")
            bar.set_status(slot, HIDDEN | ENABLED)
        assert bar.hidden(2) == 1
        assert bar.hidden(4) == 1

    def test_an_enabled_match_beats_an_earlier_disabled_one(self, bar: Machine):
        bar.register(2, button(1), "K")
        bar.register(6, button(2), "K")
        bar.set_status(2, 0)  # shown, greyed
        bar.set_status(6, ENABLED)
        assert bar.click(2) == bar.window(6)

    def test_a_visible_disabled_match_reports_disabled(self, bar: Machine):
        """It is still the one the player can see, so the press gets the engine's "disabled"
        response rather than reaching anything hidden."""
        bar.register(2, button(1), "K")
        bar.register(6, button(2), "K")
        bar.set_status(2, HIDDEN | ENABLED)
        bar.set_status(6, 0)
        assert bar.hidden(2) == 0
        assert bar.enabled(2) == 0

    def test_the_first_visible_enabled_slot_wins(self, bar: Machine):
        bar.register(3, button(1), "K")
        bar.register(5, button(2), "K")
        bar.set_status(3, ENABLED)
        bar.set_status(5, ENABLED)
        assert bar.click(5) == bar.window(3)

    def test_letters_compare_without_case(self, bar: Machine):
        bar.register(2, button(1), "k")
        bar.register(6, button(2), "K")
        bar.set_status(2, HIDDEN)
        bar.set_status(6, ENABLED)
        assert bar.click(2) == bar.window(6)

    def test_another_letter_is_never_chosen(self, bar: Machine):
        bar.register(2, button(1), "K")
        bar.register(6, button(2), "M")
        bar.set_status(2, HIDDEN)
        bar.set_status(6, ENABLED)
        assert bar.hidden(2) == 1

    def test_a_slot_rebound_since_it_was_recorded_is_ignored(self, bar: Machine):
        """A slot rebound to a button without a shortcut keeps its old record; the button check is
        what stops the old letter reaching the new button."""
        bar.register(2, button(1), "K")
        bar.register(6, button(2), "K")
        bar.bind(6, button(9))
        bar.set_status(2, HIDDEN)
        bar.set_status(6, ENABLED)
        assert bar.hidden(2) == 1

    def test_a_window_outside_the_slot_array_behaves_as_stock(self, bar: Machine):
        handler = HANDLERS + 0x200
        outsider = HEAP + 0x9000
        bar.uc.mem_write(outsider + 8, struct.pack("<I", ENABLED))
        bar.uc.mem_write(handler, struct.pack("<III", layout(CAVE)["vtable"], 1, outsider))
        bar.handler = lambda slot: handler  # type: ignore[method-assign]
        assert bar.hidden(0) == 0
        assert bar.click(0) == outsider

    def test_registration_outside_the_slot_array_records_nothing(self, bar: Machine):
        string = LETTERS + 0x400
        bar.uc.mem_write(string, struct.pack("<IHH", 1, 1, 2) + b"K\x00")
        frame = STACK + 0x8000
        bar.uc.mem_write(frame - 0x14, struct.pack("<I", CONTROL_BAR))
        before = bytes(bar.uc.mem_read(CAVE, SLOT_COUNT * 8))
        bar._run(
            layout(CAVE)["code"],
            HOOK_RESUME,
            STACK + 0x4000,
            eax=string,
            esi=button(1),
            edi=HEAP + 0x9000,
            ebp=frame,
        )
        assert bytes(bar.uc.mem_read(CAVE, SLOT_COUNT * 8)) == before

    def test_stock_methods_are_the_engines_own(self):
        """The hidden / enabled bits the cave tests inline are the ones the stock methods shift
        out: `shr eax, 4` and `shr eax, 3` of `winGetStatus`."""
        assert ANCHORS[STOCK_IS_HIDDEN][8:11] == bytes.fromhex("c1e804")
        assert ANCHORS[STOCK_IS_ENABLED][8:11] == bytes.fromhex("c1e803")
        assert GAME_WINDOW_GET_DATA in ANCHORS and GAME_WINDOW_GET_COMMAND_BUTTON in ANCHORS
