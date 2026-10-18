"""F9 hides the HUD while watching a replay, and a hidden HUD takes the on-screen clutter with it.

Whenever the engine hides the HUD, it now also stops drawing:

- the behind-building silhouettes (unit occlusion),
- the top-left text messages,
- the floating "+N" over resource buildings,
- the veterancy pips,
- the construction percentage over buildings being built.

That covers every caller of the engine's hide: the `HIDE_UI` script action, cinematics, a mod's
`TOGGLE_CONTROL_BAR` binding, and F9 (no Ctrl, Shift or Alt) during replay playback, which this
patch adds. Whenever the engine shows the HUD again they come back with it: F9 again, `SHOW_UI`,
the end of a cinematic, and every game start, which is what keeps a match from starting with them
hidden. Outside playback F9 does what it did before, which in stock is nothing. Client-side
only, and nothing is sent to the game logic. No INI change.

Derivation: `../docs/better-hud-toggle.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    CONSTRUCT_PERCENT_DRAW_CALL,
    CONSTRUCT_PERCENT_DRAW_CALL_BYTES,
    CONSTRUCT_PERCENT_LABEL,
    CONSTRUCT_PERCENT_LABEL_BYTES,
    DRAWABLE_DRAW_CONSTRUCT_PERCENT,
    DRAWABLE_DRAW_CONSTRUCT_PERCENT_ENTRY,
    DRAWABLE_DRAW_VETERANCY,
    DRAWABLE_DRAW_VETERANCY_ENTRY,
    FLOATING_TEXT_DRAW,
    FLOATING_TEXT_DRAW_CALL,
    FLOATING_TEXT_DRAW_CALL_BYTES,
    FLOATING_TEXT_DRAW_ENTRY,
    IN_GAME_UI_MESSAGES_DONE,
    IN_GAME_UI_MESSAGES_DRAW,
    IN_GAME_UI_MESSAGES_GATE,
    IN_GAME_UI_MESSAGES_GATE_BYTES,
    IN_GAME_UI_MESSAGES_ON,
    KEY_F9,
    KEY_STATE_AUTOREPEAT,
    KEY_STATE_DOWN,
    KEY_STATE_MODIFIER_KEYS,
    META_TRANSLATOR_CONSUMED,
    META_TRANSLATOR_CONSUMED_BYTES,
    META_TRANSLATOR_KEY_EBP,
    META_TRANSLATOR_KEY_HOOK,
    META_TRANSLATOR_KEY_HOOK_BYTES,
    META_TRANSLATOR_KEY_RESUME,
    META_TRANSLATOR_KEY_STORE,
    META_TRANSLATOR_KEY_STORE_BYTES,
    META_TRANSLATOR_STATE_EBP,
    META_TRANSLATOR_STATE_STORE,
    META_TRANSLATOR_STATE_STORE_BYTES,
    OCCLUSION_FLAG_READ_A,
    OCCLUSION_FLAG_READ_A_BYTES,
    OCCLUSION_FLAG_READ_B,
    OCCLUSION_FLAG_READ_B_BYTES,
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
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import (
    allocate_section,
    apply_byte_patch,
    call_rel32,
    file_offset,
    find_section,
    jmp_rel32,
)

__all__ = [
    "ANCHORS",
    "CODE_OFFSET",
    "HOOKS",
    "SECTION_NAME",
    "BetterHudTogglePatch",
    "build_section",
    "entries",
    "replacements",
]

SECTION_NAME = ".hudtogl"  # 8 chars exactly: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. Writable, because
# the hidden flag at the section's base is flipped at run time.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: The hidden flag is the section's first byte; the code starts here, so `verify` can compare it
#: without caring what the flag holds.
CODE_OFFSET = 0x10

#: Read, never rewritten: the stores that put the key and its state in the translator's frame, the
#: tail a matched `CommandMap` jumps to, the entries of the draw passes the cave jumps to, the
#: `UnderConstruction` label push that pins the construction routine, and the `GameLogic+0x99`
#: reads that pin both occlusion gates as the occlusion ones.
ANCHORS: dict[int, bytes] = {
    META_TRANSLATOR_KEY_STORE: META_TRANSLATOR_KEY_STORE_BYTES,
    META_TRANSLATOR_STATE_STORE: META_TRANSLATOR_STATE_STORE_BYTES,
    META_TRANSLATOR_CONSUMED: META_TRANSLATOR_CONSUMED_BYTES,
    FLOATING_TEXT_DRAW: FLOATING_TEXT_DRAW_ENTRY,
    DRAWABLE_DRAW_VETERANCY: DRAWABLE_DRAW_VETERANCY_ENTRY,
    DRAWABLE_DRAW_CONSTRUCT_PERCENT: DRAWABLE_DRAW_CONSTRUCT_PERCENT_ENTRY,
    CONSTRUCT_PERCENT_LABEL: CONSTRUCT_PERCENT_LABEL_BYTES,
    OCCLUSION_FLAG_READ_A: OCCLUSION_FLAG_READ_A_BYTES,
    OCCLUSION_FLAG_READ_B: OCCLUSION_FLAG_READ_B_BYTES,
}

#: Every window the patch rewrites, by the cave routine that replaces it, with its stock bytes and
#: whether the replacement is a `call` (the window is one) or a `jmp` padded with `nop`s.
HOOKS: dict[str, tuple[int, bytes, str]] = {
    "key": (META_TRANSLATOR_KEY_HOOK, META_TRANSLATOR_KEY_HOOK_BYTES, "jmp"),
    "hide": (UI_HIDE, UI_HIDE_ENTRY, "jmp"),
    "show": (UI_SHOW, UI_SHOW_BYTES, "jmp"),
    "messages": (IN_GAME_UI_MESSAGES_GATE, IN_GAME_UI_MESSAGES_GATE_BYTES, "jmp"),
    "floating_text": (FLOATING_TEXT_DRAW_CALL, FLOATING_TEXT_DRAW_CALL_BYTES, "call"),
    "veterancy": (VETERANCY_DRAW_CALL, VETERANCY_DRAW_CALL_BYTES, "call"),
    "construct_percent": (CONSTRUCT_PERCENT_DRAW_CALL, CONSTRUCT_PERCENT_DRAW_CALL_BYTES, "call"),
    "occlusion_a": (OCCLUSION_GATE_A, OCCLUSION_GATE_A_BYTES, "jmp"),
    "occlusion_b": (OCCLUSION_GATE_B, OCCLUSION_GATE_B_BYTES, "jmp"),
}


def _abs(va: int) -> bytes:
    return struct.pack("<I", va)


def _assemble(base_va: int) -> tuple[bytes, dict[str, int]]:
    """Return the code (laid out from `base_va + CODE_OFFSET`) and each routine's VA."""
    flag = _abs(base_va)
    a = Asm(base_va + CODE_OFFSET)

    # Entered by `jmp` from the meta translator's raw-key path, with its frame live. F9 going down,
    # no modifier key held, not a repeat, during playback: toggle, and leave as a matched
    # `CommandMap` does. Anything else rejoins the stock code.
    a.label("key")
    a.emit(0x83, 0x7D, META_TRANSLATOR_KEY_EBP & 0xFF, KEY_F9)  # cmp dword [ebp-0xc], 0x43
    a.jcc(JNE, "key_stock")
    a.emit(0x8B, 0x45, META_TRANSLATOR_STATE_EBP & 0xFF)  # mov eax, [ebp-0x10]
    a.emit(0xA9, _abs(KEY_STATE_AUTOREPEAT | KEY_STATE_MODIFIER_KEYS))  # test eax, 0x1fc
    a.jcc(JNE, "key_stock")
    a.emit(0xA8, KEY_STATE_DOWN)  # test al, 2
    a.jcc(JE, "key_stock")
    a.emit(0xA1, _abs(THE_RECORDER))  # mov eax, [TheRecorder]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "key_stock")
    a.emit(0x83, 0x78, RECORDER_MODE, RECORDER_MODE_PLAYBACK)  # cmp dword [eax+0x1c], 1
    a.jcc(JNE, "key_stock")
    # A HUD hidden some other way (a cinematic in the replay, say) counts as hidden: F9 shows it.
    a.emit(0x80, 0x3D, flag, 0x00)  # cmp byte [flag], 0
    a.jcc(JNE, "key_show")
    a.emit(0x6A, 0x01)  # push 1
    a.call_absolute(UI_HIDE)  # sets the flag, through "hide" below
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4
    a.jmp_absolute(META_TRANSLATOR_CONSUMED)
    a.label("key_show")
    a.emit(0x6A, 0x00)  # push 0                  ; ignored, as every caller's is
    a.call_absolute(UI_SHOW)  # clears the flag, through "show" below
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4
    a.jmp_absolute(META_TRANSLATOR_CONSUMED)
    a.label("key_stock")
    a.emit(0xA1, _abs(SHELL))  # mov eax, [TheShell]   ; the displaced instruction
    a.jmp_absolute(META_TRANSLATOR_KEY_RESUME)

    # The engine's hide and show, each entered by `jmp` from its first instruction. Show starts by
    # calling hide, so it clears the flag only once that call is back.
    a.label("hide")
    a.emit(0xC6, 0x05, flag, 0x01)  # mov byte [flag], 1
    a.emit(0xB8, UI_HIDE_ENTRY[1:])  # mov eax, <SEH frame>   ; the displaced instruction
    a.jmp_absolute(UI_HIDE_RESUME)
    a.label("show")
    a.emit(0x6A, 0x01)  # push 1                  ; the displaced instructions
    a.call_absolute(UI_HIDE)
    a.emit(0xC6, 0x05, flag, 0x00)  # mov byte [flag], 0
    a.jmp_absolute(UI_SHOW_RESUME)

    # `postDraw`'s message test, with `edi` the InGameUI: hidden reads as messages off.
    a.label("messages")
    a.emit(0x80, 0xBF, _abs(IN_GAME_UI_MESSAGES_ON), 0x00)  # cmp byte [edi+0x811], 0
    a.jcc(JE, "messages_off")
    a.emit(0x80, 0x3D, flag, 0x00)  # cmp byte [flag], 0
    a.jcc(JNE, "messages_off")
    a.jmp_absolute(IN_GAME_UI_MESSAGES_DRAW)
    a.label("messages_off")
    a.jmp_absolute(IN_GAME_UI_MESSAGES_DONE)

    # Called in place of the floating-text pass, the veterancy pips and the construction
    # percentage: tail-jump into the stock routine, or return as if it had drawn nothing. None takes
    # an argument.
    a.label("floating_text")
    a.emit(0x80, 0x3D, flag, 0x00)  # cmp byte [flag], 0
    a.jcc(JNE, "skip_draw")
    a.jmp_absolute(FLOATING_TEXT_DRAW)
    a.label("veterancy")
    a.emit(0x80, 0x3D, flag, 0x00)  # cmp byte [flag], 0
    a.jcc(JNE, "skip_draw")
    a.jmp_absolute(DRAWABLE_DRAW_VETERANCY)
    a.label("construct_percent")
    a.emit(0x80, 0x3D, flag, 0x00)  # cmp byte [flag], 0
    a.jcc(JNE, "skip_draw")
    a.jmp_absolute(DRAWABLE_DRAW_CONSTRUCT_PERCENT)
    a.label("skip_draw")
    a.emit(0xC3)  # ret

    # The occlusion setups' suppress test: hidden reads as suppressed.
    for gate, on, off in (
        ("occlusion_a", OCCLUSION_GATE_A_ON, OCCLUSION_GATE_A_OFF),
        ("occlusion_b", OCCLUSION_GATE_B_ON, OCCLUSION_GATE_B_OFF),
    ):
        a.label(gate)
        a.emit(0x80, 0x3D, _abs(OCCLUSION_SUPPRESS), 0x00)  # cmp byte [0x00DD1E44], 0
        a.jcc(JNE, f"{gate}_off")
        a.emit(0x80, 0x3D, flag, 0x00)  # cmp byte [flag], 0
        a.jcc(JNE, f"{gate}_off")
        a.jmp_absolute(on)
        a.label(f"{gate}_off")
        a.jmp_absolute(off)

    code = a.finish()
    return code, {name: a.label_va(name) for name in HOOKS}


def entries(base_va: int) -> dict[str, int]:
    """Each routine's VA, for a section based at `base_va`."""
    return _assemble(base_va)[1]


def build_section(base_va: int) -> bytes:
    """The whole section: the hidden flag (clear), padding, then the code."""
    return bytes(CODE_OFFSET) + _assemble(base_va)[0]


def replacements(base_va: int) -> dict[int, bytes]:
    """The bytes each hooked window holds once patched, by its VA."""
    routines = entries(base_va)
    out: dict[int, bytes] = {}
    for name, (va, stock, kind) in HOOKS.items():
        if kind == "call":
            out[va] = call_rel32(va, routines[name])
        else:
            out[va] = jmp_rel32(va, routines[name], len(stock))
    return out


class BetterHudTogglePatch(Patch):
    name = "better-hud-toggle"
    author = "officialNecro"
    description = (
        "F9 during replay playback hides the HUD, and any hidden HUD (F9, HIDE_UI, cinematics) "
        "also stops drawing unit occlusion, the top-left text messages, the floating +N "
        "resource text, veterancy pips and the construction percentage; they return whenever "
        "the HUD is shown again. "
        "Client-side only. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        for va, expected in {**ANCHORS, **{va: stock for va, stock, _ in HOOKS.values()}}.items():
            self._check_stock(data, va, expected)
        base_va = allocate_section(data, SECTION_NAME, build_section, _CHARACTERISTICS)
        for name, new in zip(HOOKS, replacements(base_va).values(), strict=True):
            va, stock, _ = HOOKS[name]
            apply_byte_patch(
                data, file_offset(data, va), stock, new, f"better HUD toggle: {name} hook"
            )

    @staticmethod
    def _check_stock(data: bytes | bytearray, va: int, expected: bytes) -> None:
        off = file_offset(data, va)
        got = bytes(data[off : off + len(expected)])
        if got != expected:
            raise ValueError(
                f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the file is not "
                "the expected build, or already carries this patch"
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        base_va, section_off, vsize = located
        problems: list[str] = []
        code = _assemble(base_va)[0]
        start = section_off + CODE_OFFSET
        if vsize < CODE_OFFSET + len(code) or bytes(data[start : start + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave is not the one this patch builds")
        for name, (va, new) in zip(HOOKS, replacements(base_va).items(), strict=True):
            off = file_offset(data, va)
            if bytes(data[off : off + len(new)]) != new:
                problems.append(f"@{va:#010x}: the {name} hook is not installed")
        return problems
