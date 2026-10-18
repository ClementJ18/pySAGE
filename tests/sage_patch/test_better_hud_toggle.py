"""Tests for the better-hud-toggle patch.

The stock windows are disassembled to show each is the test or call the patch takes it to be, and
every hook runs under Unicorn from its own engine address on a synthetic stand-in: F9 in playback
hides then shows, every other key press rejoins the stock code untouched, the engine's show clears
the flag, and each draw gate skips exactly when the flag is set.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_patch.addresses import (
    CONSTRUCT_PERCENT_DRAW_CALL,
    CONSTRUCT_PERCENT_DRAW_CALL_BYTES,
    DRAWABLE_DRAW_CONSTRUCT_PERCENT,
    DRAWABLE_DRAW_VETERANCY,
    FLOATING_TEXT_DRAW,
    FLOATING_TEXT_DRAW_CALL,
    FLOATING_TEXT_DRAW_CALL_BYTES,
    IN_GAME_UI_MESSAGES_DONE,
    IN_GAME_UI_MESSAGES_DRAW,
    IN_GAME_UI_MESSAGES_GATE,
    IN_GAME_UI_MESSAGES_GATE_BYTES,
    IN_GAME_UI_MESSAGES_ON,
    KEY_F9,
    KEY_STATE_AUTOREPEAT,
    KEY_STATE_DOWN,
    META_TRANSLATOR_CONSUMED,
    META_TRANSLATOR_KEY_EBP,
    META_TRANSLATOR_KEY_HOOK,
    META_TRANSLATOR_KEY_HOOK_BYTES,
    META_TRANSLATOR_KEY_RESUME,
    META_TRANSLATOR_STATE_EBP,
    OCCLUSION_GATE_A,
    OCCLUSION_GATE_A_BYTES,
    OCCLUSION_GATE_A_OFF,
    OCCLUSION_GATE_A_ON,
    OCCLUSION_GATE_B,
    OCCLUSION_GATE_B_BYTES,
    OCCLUSION_GATE_B_OFF,
    OCCLUSION_GATE_B_ON,
    OCCLUSION_SUPPRESS,
    RECORDER_MODE,
    RECORDER_MODE_PLAYBACK,
    RECORDER_MODE_RECORD,
    SHELL,
    THE_RECORDER,
    UI_HIDE,
    UI_HIDE_ENTRY,
    UI_HIDE_RESUME,
    UI_SHOW,
    UI_SHOW_BYTES,
    UI_SHOW_RESUME,
    VETERANCY_DRAW_CALL,
    VETERANCY_DRAW_CALL_BYTES,
)
from sage_patch.patches.better_hud_toggle import (
    ANCHORS,
    HOOKS,
    SECTION_NAME,
    BetterHudTogglePatch,
    build_section,
    entries,
    replacements,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import better_hud_toggle_image

REPO = Path(__file__).resolve().parents[2]
REAL_GAME_DATS = [
    REPO / "game.dat",
    REPO / "sage_mods" / "edain" / "patching" / "engine" / "game.dat.backup",
]
BASE = 0x00F00000

SHIFT = 0x10
CTRL = 0x04
ALT = 0x40
KEY_UP = 0x01
KEY_F8 = 0x42


def ops(code: bytes, base: int) -> list[tuple[str, str]]:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return [(i.mnemonic, i.op_str) for i in md.disasm(code, base)]


@pytest.fixture
def patched() -> bytearray:
    data = better_hud_toggle_image()
    BetterHudTogglePatch().apply(data)
    return data


class TestTheStockWindows:
    def test_the_key_hook_is_the_shell_load(self):
        assert ops(META_TRANSLATOR_KEY_HOOK_BYTES, META_TRANSLATOR_KEY_HOOK) == [
            ("mov", f"eax, dword ptr [{SHELL:#x}]"),
        ]
        assert META_TRANSLATOR_KEY_HOOK + 5 == META_TRANSLATOR_KEY_RESUME

    def test_the_hide_hook_is_the_seh_frame_load(self):
        assert ops(UI_HIDE_ENTRY, UI_HIDE) == [
            ("mov", f"eax, {int.from_bytes(UI_HIDE_ENTRY[1:], 'little'):#x}")
        ]
        assert UI_HIDE + len(UI_HIDE_ENTRY) == UI_HIDE_RESUME

    def test_show_starts_by_calling_hide(self):
        assert ops(UI_SHOW_BYTES, UI_SHOW) == [("push", "1"), ("call", hex(UI_HIDE))]
        assert UI_SHOW + len(UI_SHOW_BYTES) == UI_SHOW_RESUME

    def test_the_message_gate_tests_the_messages_flag(self):
        assert ops(IN_GAME_UI_MESSAGES_GATE_BYTES, IN_GAME_UI_MESSAGES_GATE) == [
            ("cmp", f"byte ptr [edi + {IN_GAME_UI_MESSAGES_ON:#x}], 0"),
            ("je", hex(IN_GAME_UI_MESSAGES_DONE)),
        ]
        assert IN_GAME_UI_MESSAGES_GATE + len(IN_GAME_UI_MESSAGES_GATE_BYTES) == (
            IN_GAME_UI_MESSAGES_DRAW
        )

    @pytest.mark.parametrize(
        ("va", "stock", "target"),
        [
            (FLOATING_TEXT_DRAW_CALL, FLOATING_TEXT_DRAW_CALL_BYTES, FLOATING_TEXT_DRAW),
            (VETERANCY_DRAW_CALL, VETERANCY_DRAW_CALL_BYTES, DRAWABLE_DRAW_VETERANCY),
            (
                CONSTRUCT_PERCENT_DRAW_CALL,
                CONSTRUCT_PERCENT_DRAW_CALL_BYTES,
                DRAWABLE_DRAW_CONSTRUCT_PERCENT,
            ),
        ],
    )
    def test_the_draw_hooks_are_calls_to_the_passes(self, va, stock, target):
        assert ops(stock, va) == [("call", hex(target))]

    @pytest.mark.parametrize(
        ("va", "stock", "on", "off"),
        [
            (OCCLUSION_GATE_A, OCCLUSION_GATE_A_BYTES, OCCLUSION_GATE_A_ON, OCCLUSION_GATE_A_OFF),
            (OCCLUSION_GATE_B, OCCLUSION_GATE_B_BYTES, OCCLUSION_GATE_B_ON, OCCLUSION_GATE_B_OFF),
        ],
    )
    def test_the_occlusion_gates_test_the_suppress_byte(self, va, stock, on, off):
        assert ops(stock, va) == [
            ("cmp", f"byte ptr [{OCCLUSION_SUPPRESS:#x}], 0"),
            ("jne", hex(off)),
        ]
        assert va + len(stock) == on

    def test_every_replacement_fills_its_window_exactly(self):
        new = replacements(BASE)
        routines = entries(BASE)
        for name, (va, stock, kind) in HOOKS.items():
            assert len(new[va]) == len(stock)
            insns = ops(new[va], va)
            assert insns[0] == (kind, hex(routines[name]))
            assert {m for m, _ in insns[1:]} <= {"nop"}

    def test_the_section_starts_with_a_clear_flag(self):
        assert build_section(BASE)[0] == 0


class TestApply:
    def test_apply_then_verify(self, patched: bytearray):
        assert BetterHudTogglePatch().verify(patched) == []

    def test_a_stock_image_does_not_verify(self):
        assert BetterHudTogglePatch().verify(better_hud_toggle_image())

    def test_refuses_to_apply_twice(self, patched: bytearray):
        with pytest.raises(ValueError, match="already carries"):
            BetterHudTogglePatch().apply(patched)

    @pytest.mark.parametrize("va", [*sorted(ANCHORS), *(va for va, _, _ in HOOKS.values())])
    def test_a_moved_site_refuses_to_apply(self, va: int):
        data = better_hud_toggle_image()
        data[va_to_offset(data, va)] ^= 0xFF
        before = bytes(data)
        with pytest.raises(ValueError):
            BetterHudTogglePatch().apply(data)
        assert bytes(data) == before

    def test_it_is_registered_and_detected_once_applied(self, patched: bytearray):
        assert PATCHES[BetterHudTogglePatch.name] is BetterHudTogglePatch
        assert BetterHudTogglePatch.detect(better_hud_toggle_image()) is None
        assert isinstance(BetterHudTogglePatch.detect(patched), BetterHudTogglePatch)

    @pytest.mark.parametrize("path", REAL_GAME_DATS, ids=lambda p: p.name)
    def test_applies_to_a_real_binary(self, path: Path):
        if not path.exists():
            pytest.skip(f"{path} is not present")
        data = bytearray(path.read_bytes())
        BetterHudTogglePatch().apply(data)
        assert BetterHudTogglePatch().verify(data) == []


class TestExecuted:
    """Each hook entered at its engine address, as the stock code reaches it."""

    @pytest.fixture
    def machine(self, patched: bytearray):
        pytest.importorskip("unicorn")
        pytest.importorskip("pefile")
        from tests.sage_patch.save_machine import Machine  # noqa: PLC0415

        m = Machine(bytes(patched))
        self.flag = find_section(m.image, SECTION_NAME)[0]
        self.hides: list[int] = []
        self.drawn: list[str] = []
        # The rest of the engine's hide, past the hooked first instruction.
        m.stub(UI_HIDE_RESUME, lambda mm: (self.hides.append(mm.arg(0)), mm.ret(0)))
        # The rest of the engine's show, as far as the stack is concerned: `pop ecx` / `ret`.
        m.ensure(UI_SHOW_RESUME)
        m.uc.mem_write(UI_SHOW_RESUME, b"\x59\xc3")
        m.stub(FLOATING_TEXT_DRAW, lambda mm: (self.drawn.append("floating"), mm.ret(0)))
        m.stub(DRAWABLE_DRAW_VETERANCY, lambda mm: (self.drawn.append("veterancy"), mm.ret(0)))
        m.stub(
            DRAWABLE_DRAW_CONSTRUCT_PERCENT,
            lambda mm: (self.drawn.append("construct"), mm.ret(0)),
        )
        for va in (SHELL, THE_RECORDER, OCCLUSION_SUPPRESS):
            m.ensure(va)
        self.shell = 0x5E11
        m.write32(SHELL, self.shell)
        self.recorder = m.alloc(0x40, bytes(0x40))
        m.write32(THE_RECORDER, self.recorder)
        m.write32(self.recorder + RECORDER_MODE, RECORDER_MODE_PLAYBACK)
        return m

    def hidden(self, m) -> bool:
        return bytes(m.uc.mem_read(self.flag, 1)) == b"\x01"

    def set_hidden(self, m, value: bool) -> None:
        m.uc.mem_write(self.flag, bytes([value]))

    def press(self, m, key: int = KEY_F9, state: int = KEY_STATE_DOWN) -> int | None:
        """Enter the key hook with the translator's frame holding `key` and `state`; return where
        execution left the cave."""
        ebp = m.frame()
        m.write32(ebp + META_TRANSLATOR_KEY_EBP, key)
        m.write32(ebp + META_TRANSLATOR_STATE_EBP, state)
        m.stop_at(META_TRANSLATOR_CONSUMED, META_TRANSLATOR_KEY_RESUME)
        self.eax = m.call(META_TRANSLATOR_KEY_HOOK, ebp=ebp)
        return m.stopped_at

    def test_f9_hides_then_shows(self, machine):
        assert self.press(machine) == META_TRANSLATOR_CONSUMED
        assert self.hidden(machine)
        assert self.hides == [1]
        assert self.press(machine) == META_TRANSLATOR_CONSUMED
        assert not self.hidden(machine)
        assert self.hides == [1, 1]  # the second is the engine's show starting with its hide

    @pytest.mark.parametrize(
        ("key", "state"),
        [
            (KEY_F8, KEY_STATE_DOWN),
            (KEY_F9, KEY_UP),
            (KEY_F9, KEY_STATE_DOWN | KEY_STATE_AUTOREPEAT),
            (KEY_F9, KEY_STATE_DOWN | SHIFT),
            (KEY_F9, KEY_STATE_DOWN | CTRL),
            (KEY_F9, KEY_STATE_DOWN | ALT),
        ],
    )
    def test_any_other_press_rejoins_the_stock_code(self, machine, key, state):
        assert self.press(machine, key, state) == META_TRANSLATOR_KEY_RESUME
        assert self.eax == self.shell  # the displaced load, done
        assert not self.hidden(machine)
        assert self.hides == []

    def test_f9_outside_playback_rejoins_the_stock_code(self, machine):
        machine.write32(self.recorder + RECORDER_MODE, RECORDER_MODE_RECORD)
        assert self.press(machine) == META_TRANSLATOR_KEY_RESUME
        assert not self.hidden(machine)

    def test_f9_with_no_recorder_rejoins_the_stock_code(self, machine):
        machine.write32(THE_RECORDER, 0)
        assert self.press(machine) == META_TRANSLATOR_KEY_RESUME
        assert not self.hidden(machine)

    def test_f9_shows_a_hud_hidden_some_other_way(self, machine):
        machine.call(UI_HIDE, 1)
        assert self.press(machine) == META_TRANSLATOR_CONSUMED
        assert not self.hidden(machine)
        assert self.hides == [1, 1]

    def test_any_caller_of_the_engines_hide_sets_the_flag(self, machine):
        machine.call(UI_HIDE, 1)
        assert machine.stopped_at is not None
        assert self.hidden(machine)
        assert self.hides == [1]

    def test_the_engines_show_clears_the_flag_after_its_own_hide(self, machine):
        self.set_hidden(machine, True)
        machine.call(UI_SHOW, 0)
        assert machine.stopped_at is not None
        assert not self.hidden(machine)
        assert self.hides == [1]

    @pytest.mark.parametrize(
        ("messages_on", "hidden", "expected"),
        [
            (1, False, IN_GAME_UI_MESSAGES_DRAW),
            (1, True, IN_GAME_UI_MESSAGES_DONE),
            (0, False, IN_GAME_UI_MESSAGES_DONE),
            (0, True, IN_GAME_UI_MESSAGES_DONE),
        ],
    )
    def test_messages_draw_only_when_on_and_not_hidden(
        self, machine, messages_on, hidden, expected
    ):
        self.set_hidden(machine, hidden)
        ui = machine.alloc(0x1000, bytes(0x1000))
        machine.uc.mem_write(ui + IN_GAME_UI_MESSAGES_ON, bytes([messages_on]))
        machine.stop_at(IN_GAME_UI_MESSAGES_DRAW, IN_GAME_UI_MESSAGES_DONE)
        machine.call(IN_GAME_UI_MESSAGES_GATE, edi=ui)
        assert machine.stopped_at == expected

    @pytest.mark.parametrize(
        ("site", "pass_name"),
        [
            (FLOATING_TEXT_DRAW_CALL, "floating"),
            (VETERANCY_DRAW_CALL, "veterancy"),
            (CONSTRUCT_PERCENT_DRAW_CALL, "construct"),
        ],
    )
    @pytest.mark.parametrize("hidden", [False, True])
    def test_draw_passes_run_only_when_not_hidden(self, machine, site, pass_name, hidden):
        self.set_hidden(machine, hidden)
        machine.stop_at(site + 5)
        machine.call(site)
        assert machine.stopped_at == site + 5
        assert self.drawn == ([] if hidden else [pass_name])

    @pytest.mark.parametrize(
        ("gate", "on", "off"),
        [
            (OCCLUSION_GATE_A, OCCLUSION_GATE_A_ON, OCCLUSION_GATE_A_OFF),
            (OCCLUSION_GATE_B, OCCLUSION_GATE_B_ON, OCCLUSION_GATE_B_OFF),
        ],
    )
    @pytest.mark.parametrize(
        ("suppress", "hidden", "occluded"),
        [(0, False, True), (0, True, False), (1, False, False), (1, True, False)],
    )
    def test_occlusion_runs_only_when_neither_suppressed_nor_hidden(
        self, machine, gate, on, off, suppress, hidden, occluded
    ):
        self.set_hidden(machine, hidden)
        machine.uc.mem_write(OCCLUSION_SUPPRESS, bytes([suppress]))
        machine.stop_at(on, off)
        machine.call(gate)
        assert machine.stopped_at == (on if occluded else off)
