"""Give spellbook powers a keyboard shortcut, under Ctrl, with no selection required.

Original RotWK game.dat 2.01.2614.37001; see ``../../docs/spellbook-hotkeys.md``.

A command button's shortcut is the character after the `&` in its localized ``TextLabel``, and
the engine registers one only while that button occupies a control-bar window - so a shortcut
works exactly as long as the unit owning it stays selected. The spellbook bar is an APT movie
rather than a window grid, so its buttons never get one at all.

Two edits. The first lets a key press held with Ctrl alone through the translator's modifier
gate, which stock discards, marking it so nothing else mistakes it for an unmodified press. The
second gives ``HotKeyManager::executeHotKey`` a branch for that mark: resolve the local player's
spellbook CommandSet, read each button's own `&` character, and on a match hand the button to
``ControlBar::doCommand`` exactly as a click on the bar does.

Which powers get a shortcut, and how many, is therefore whatever the strings already say: a
button whose label carries no `&` is never matched, and each faction's spellbook carries its own
buttons. Nothing is bound by slot, and no INI keyword is added.

Static analysis only - no part of this has been confirmed in a running game.
"""

from __future__ import annotations

import struct

from ...addresses import (
    AMPERSAND_SCAN,
    APT_PLAYER_MODE,
    ASCII_STRING_DTOR,
    COMMAND_BUTTON_GET_TEXT_LABEL,
    COMMAND_SET_GET_COMMAND_BUTTON,
    COMMAND_SET_STORE_FIND_COMMAND_SET,
    CONTROL_BAR_AVAILABILITY_OK_HIGH,
    CONTROL_BAR_AVAILABILITY_OK_LOW,
    CONTROL_BAR_DO_COMMAND,
    CONTROL_BAR_GET_COMMAND_AVAILABILITY,
    DO_COMMAND_SPELL_BOOK_EXEMPTION,
    HOT_KEY_EXECUTE,
    HOT_KEY_EXECUTE_FLAG_EBP,
    HOT_KEY_EXECUTE_HIT,
    HOT_KEY_EXECUTE_HOOK,
    HOT_KEY_EXECUTE_HOOK_BYTES,
    HOT_KEY_EXECUTE_KEY_EBP,
    HOT_KEY_EXECUTE_MISS,
    HOT_KEY_EXECUTE_RESUME,
    HOT_KEY_MANAGER_HOTKEY_FROM_LABEL,
    HOT_KEY_TRANSLATOR_FLAG_EBP,
    HOT_KEY_TRANSLATOR_MODIFIER_GATE,
    HOT_KEY_TRANSLATOR_MODIFIER_GATE_BYTES,
    HOT_KEY_TRANSLATOR_PROCEED,
    HOT_KEY_TRANSLATOR_REJECT,
    OBJECT_GET_COMMAND_SET_STRING,
    PLAYER_GET_SPELLBOOK_OBJECT,
    PLAYER_LIST_GET_LOCAL_PLAYER,
    SPELLBOOK_UI_SLOT_LIMIT,
    THE_APT_PLAYER,
    THE_COMMAND_SET_STORE,
    THE_HOT_KEY_MANAGER,
    THE_PLAYER_LIST,
)
from ...asm import JA, JB, JE, JGE, JNE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ALT_MASK",
    "ANCHORS",
    "CTRL_MASK",
    "MARK",
    "SECTION_NAME",
    "SITES",
    "SpellbookHotkeysPatch",
    "build_cave",
    "cave_entries",
]

SECTION_NAME = ".sbhotk"
_CHARACTERISTICS = 0x60000060  # executable/read-only, no persistent state

#: The modifier mask the translator builds, in the same vocabulary the `CommandMap` block's
#: `Modifiers` keyword parses.
#:
#: The engine matches a `CommandMap` entry's `Modifiers` by **equality** (`cmp [rec+0x10], eax`
#: at `0x005DA92F`, `0x005DA93B` and `0x005DA948`), so a binding on Ctrl stops matching the
#: moment any other bit joins the mask - and the `0x400` state bit the translator folds into
#: SHIFT at `0x0075B0F9` is not identified. This gate tests the two bits it cares about instead:
#: Ctrl held, Alt not. Ctrl+Shift therefore fires too, which is the safe direction to be wrong in.
CTRL_MASK = 0x04
ALT_MASK = 0x40

#: What the gate writes into the flag byte the matched button would have received, and what the
#: executor's branch tests. Stock only ever puts 0 or 1 there, so no stock functor can see it.
MARK = 0x02

#: Stock bytes at the two edited sites plus the read-only build anchors: every helper the cave
#: calls whose ABI it depends on, the `&` scan's own comparison, and `doCommand`'s exemption for
#: command 0x26. `Object::getCommandSetString` is deliberately **not** anchored - the
#: commandset-button-upgrade patch legitimately detours it, and this cave wants whatever overlay
#: is installed there, the same way the spellbook cache guard does.
ANCHORS = {
    HOT_KEY_EXECUTE: bytes.fromhex("b8a41db900e8ec1f2e0051538bd98b0d2c41de00e8194a1b0084"),
    HOT_KEY_EXECUTE_MISS: bytes.fromhex("32c08b4df45b64890d00000000c9"),
    HOT_KEY_MANAGER_HOTKEY_FROM_LABEL: bytes.fromhex(
        "b85e1db900e81b272e00518365f00056576a00ff750c8bf98b0d044bde008b018d550c52ff503850ff750833"
    ),
    AMPERSAND_SCAN: bytes.fromhex("668b066685c0740a663d26007423464675ee8b4d"),
    COMMAND_BUTTON_GET_TEXT_LABEL: bytes.fromhex(
        "568bf1578d7e7c8bcfe80f50caff84c075048bc7eb308b46583b465c"
    ),
    COMMAND_SET_GET_COMMAND_BUTTON: bytes.fromhex(
        "558bec568bf18b0d2c41de0085c9578b7d0874158d450850578d461050e8aa36"
        "e2ff84c08b450875048b44be145f5e5dc2"
    ),
    CONTROL_BAR_DO_COMMAND: bytes.fromhex("b826c3ba00e8b1ca0f0083ec4853568b7508578bf98b4f70"),
    DO_COMMAND_SPELL_BOOK_EXEMPTION: bytes.fromhex("83f82674318b476c33d2"),
    PLAYER_LIST_GET_LOCAL_PLAYER: bytes.fromhex("568b711085f6750433c05ec38bcee80624000084c07513a1"),
    PLAYER_GET_SPELLBOOK_OBJECT: bytes.fromhex("558bec5151568bf183be100700000075258365fc008d45f8"),
    COMMAND_SET_STORE_FIND_COMMAND_SET: bytes.fromhex(
        "558bec5151ff75088d45f85083c130e8c8e4ebff8b45f885c074058b4008eb0233c0c9c20400"
    ),
    ASCII_STRING_DTOR: bytes.fromhex(
        "6aff68f80eb70064a100000000506489250000000083ec0856578bf1e85f"
    ),
}


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _fold_to_lower(a: Asm, done: str) -> None:
    """AL, case-folded in place. The hotkey the `&` scan yields carries whatever case the string
    table used; the key name the translator built carries whatever the keyboard map used, so one
    of the two has to give."""
    a.emit(0x3C, 0x41)  # cmp al, 'A'
    a.jcc_short(JB, done)
    a.emit(0x3C, 0x5A)  # cmp al, 'Z'
    a.jcc_short(JA, done)
    a.emit(0x04, 0x20)  # add al, 0x20
    a.label(done)


def _emit_gate(a: Asm) -> None:
    """The translator's modifier gate, with Ctrl alone routed on instead of discarded.

    Replaces the thirteen bytes at :data:`HOT_KEY_TRANSLATOR_MODIFIER_GATE`. `esi` is the
    modifier mask, `ebx` is zero and `[ebp-0x10]` the flag, all exactly as stock left them.
    """
    a.label("gate")
    a.emit(0x3B, 0xF3)  # cmp esi, ebx
    a.jcc(JE, "gate_proceed")  # unmodified: stock's own answer
    a.emit(0x38, 0x5D, HOT_KEY_TRANSLATOR_FLAG_EBP & 0xFF)  # cmp byte [ebp-0x10], bl
    a.jcc(JNE, "gate_proceed")  # shift-only: stock's own answer, flag already set
    a.emit(0xF7, 0xC6, _u32(ALT_MASK))  # test esi, 0x40
    a.jcc(JNE, "gate_reject")  # Alt in any combination stays stock's answer
    a.emit(0xF7, 0xC6, _u32(CTRL_MASK))  # test esi, 4
    a.jcc(JE, "gate_reject")
    a.emit(0xC6, 0x45, HOT_KEY_TRANSLATOR_FLAG_EBP & 0xFF, MARK)  # mov byte [ebp-0x10], 2
    a.jmp("gate_proceed")
    a.label("gate_reject")
    a.jmp_absolute(HOT_KEY_TRANSLATOR_REJECT)
    a.label("gate_proceed")
    a.jmp_absolute(HOT_KEY_TRANSLATOR_PROCEED)


def _emit_dispatch(a: Asm) -> None:
    """The executor's spellbook branch, entered five bytes past its game-state gates.

    Frame, once the two callee-saved registers this entry point has not saved yet are pushed:
    `[esp+0]` the `AsciiString` the `&` scan constructs into, `[esp+4]` the button under test,
    `[esp+8]` the folded character that was pressed, `[esp+0xc]` the `Real` the availability
    evaluator fills in and nothing here reads. Every engine call below cleans its own arguments,
    so those four offsets hold across all of them. `ebx` is left alone: it carries the
    `HotKeyManager` and both exits restore it.
    """
    a.label("dispatch")
    a.emit(0x80, 0x7D, HOT_KEY_EXECUTE_FLAG_EBP, MARK)  # cmp byte [ebp+0xc], 2
    a.jcc(JE, "spellbook")
    a.emit(0x56, 0x57)  # push esi / push edi
    a.emit(0xFF, 0x75, HOT_KEY_EXECUTE_KEY_EBP)  # push [ebp+8]
    a.jmp_absolute(HOT_KEY_EXECUTE_RESUME)

    a.label("spellbook")
    a.emit(0x56, 0x57)
    a.emit(0x83, 0xEC, 0x10)  # sub esp, 0x10
    a.emit(0x83, 0x24, 0x24, 0x00)  # and dword [esp], 0 -- an empty AsciiString to destroy

    a.emit(0x8B, 0x45, HOT_KEY_EXECUTE_KEY_EBP)  # mov eax, [ebp+8]
    a.emit(0x8B, 0x00)  # mov eax, [eax]
    a.emit(0x85, 0xC0)
    a.jcc(JE, "miss")
    a.emit(0x0F, 0xB6, 0x40, 0x08)  # movzx eax, byte [eax+8]
    a.emit(0x84, 0xC0)
    a.jcc(JE, "miss")
    _fold_to_lower(a, "pressed_folded")
    a.emit(0x89, 0x44, 0x24, 0x08)  # mov [esp+8], eax

    # The spellbook bar's own chain: local player, its spellbook Object, that Object's CommandSet.
    a.emit(0x8B, 0x0D, _u32(THE_PLAYER_LIST))
    a.call_absolute(PLAYER_LIST_GET_LOCAL_PLAYER)
    a.emit(0x85, 0xC0)
    a.jcc(JE, "miss")
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.call_absolute(PLAYER_GET_SPELLBOOK_OBJECT)
    a.emit(0x85, 0xC0)
    a.jcc(JE, "miss")
    a.emit(0x8B, 0xC8)
    a.call_absolute(OBJECT_GET_COMMAND_SET_STRING)
    a.emit(0x8B, 0x0D, _u32(THE_COMMAND_SET_STORE))
    a.emit(0x50)  # push eax
    a.call_absolute(COMMAND_SET_STORE_FIND_COMMAND_SET)
    a.emit(0x85, 0xC0)
    a.jcc(JE, "miss")
    a.emit(0x8B, 0xF0)  # mov esi, eax
    a.emit(0x33, 0xFF)  # xor edi, edi

    a.label("next")
    a.emit(0x83, 0xFF, SPELLBOOK_UI_SLOT_LIMIT)  # cmp edi, 0x18
    a.jcc(JGE, "miss")
    a.emit(0x57)  # push edi
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(COMMAND_SET_GET_COMMAND_BUTTON)
    a.emit(0x85, 0xC0)
    a.jcc(JE, "step")
    a.emit(0x89, 0x44, 0x24, 0x04)  # mov [esp+4], eax
    a.emit(0x8B, 0xC8)
    a.call_absolute(COMMAND_BUTTON_GET_TEXT_LABEL)
    a.emit(0x85, 0xC0)
    a.jcc(JE, "step")
    a.emit(0x8B, 0x0D, _u32(THE_HOT_KEY_MANAGER))
    a.emit(0x50)  # push eax -- the label
    a.emit(0x8D, 0x44, 0x24, 0x04)  # lea eax, [esp+4] -- the out slot, one push down
    a.emit(0x50)
    a.call_absolute(HOT_KEY_MANAGER_HOTKEY_FROM_LABEL)

    a.emit(0x8B, 0x04, 0x24)  # mov eax, [esp]
    a.emit(0x85, 0xC0)
    a.jcc(JE, "release")  # no `&` in this label: not a shortcut, and never was
    a.emit(0x0F, 0xB6, 0x40, 0x08)
    a.emit(0x84, 0xC0)
    a.jcc(JE, "release")
    _fold_to_lower(a, "button_folded")
    a.emit(0x3A, 0x44, 0x24, 0x08)  # cmp al, byte [esp+8]
    a.jcc(JNE, "release")

    # Release the scan's result here rather than after firing: this arm may still rejoin the
    # loop below, and doCommand re-enters UI code that has no business running with a string of
    # ours live on the frame.
    a.emit(0x8D, 0x0C, 0x24)  # lea ecx, [esp]
    a.call_absolute(ASCII_STRING_DTOR)

    # Ask what a click would be allowed to do. Nothing on the SPELL_BOOK path asks, because the
    # bar greys its buttons inside the APT movie and a disabled one never reaches the engine -
    # so without this a shortcut casts powers the bar would not let you click.
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov eax, [esp+4] -- the button
    a.emit(0x6A, 0x00)  # push 0
    a.emit(0x8D, 0x4C, 0x24, 0x10)  # lea ecx, [esp+0x10] -- the Real out, one push down
    a.emit(0x51)
    a.emit(0x6A, 0x00)
    a.emit(0x6A, 0x00)
    a.emit(0x50)  # push eax -- the button
    a.emit(0x8B, 0x0D, _u32(THE_COMMAND_SET_STORE))
    a.call_absolute(CONTROL_BAR_GET_COMMAND_AVAILABILITY)
    a.emit(0x48)  # dec eax
    a.emit(0x83, 0xF8, CONTROL_BAR_AVAILABILITY_OK_HIGH - CONTROL_BAR_AVAILABILITY_OK_LOW)
    a.jcc(JA, "step")  # greyed, hidden or spent: the same nothing a click on it would do
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov eax, [esp+4] -- the button again
    a.emit(0x8B, 0x0D, _u32(THE_APT_PLAYER))
    a.emit(0x83, 0xB9, _u32(APT_PLAYER_MODE), 0x02)  # cmp dword [ecx+0x318], 2
    a.emit(0x6A, 0x00)  # push 0
    a.emit(0x0F, 0x95, 0xC1)  # setne cl
    a.emit(0x51)  # push ecx -- read as a byte, exactly as the APT bar leaves it
    a.emit(0x8B, 0x0D, _u32(THE_COMMAND_SET_STORE))
    a.emit(0x50)  # push eax
    a.call_absolute(CONTROL_BAR_DO_COMMAND)
    a.emit(0x83, 0xC4, 0x10)  # add esp, 0x10
    a.emit(0x5F, 0x5E)  # pop edi / pop esi
    a.emit(0xB0, 0x01)  # mov al, 1 -- the key was consumed
    a.jmp_absolute(HOT_KEY_EXECUTE_HIT)

    a.label("release")
    a.emit(0x8D, 0x0C, 0x24)
    a.call_absolute(ASCII_STRING_DTOR)  # leaves the slot null, ready for the next construct
    a.label("step")
    a.emit(0x47)  # inc edi
    a.jmp("next")

    a.label("miss")
    a.emit(0x8D, 0x0C, 0x24)
    a.call_absolute(ASCII_STRING_DTOR)  # null-safe, which is what the early exits rely on
    a.emit(0x83, 0xC4, 0x10)
    a.emit(0x5F, 0x5E)
    a.jmp_absolute(HOT_KEY_EXECUTE_MISS)


def _assemble(base_va: int) -> Asm:
    a = Asm(base_va)
    _emit_gate(a)
    _emit_dispatch(a)
    return a


def build_cave(base_va: int) -> bytes:
    """Both routines, laid out together so one section carries the whole patch."""
    return _assemble(base_va).finish()


def cave_entries(base_va: int) -> tuple[int, int]:
    """The gate's and the dispatch's virtual addresses, read off the layout that was emitted."""
    a = _assemble(base_va)
    return a.label_va("gate"), a.label_va("dispatch")


def _detour(target_va: int, site_va: int, width: int) -> bytes:
    jump = b"\xe9" + struct.pack("<i", target_va - (site_va + 5))
    return jump + b"\x90" * (width - 5)


#: The two windows this patch rewrites, each with the stock bytes it expects to find there.
SITES = {
    HOT_KEY_TRANSLATOR_MODIFIER_GATE: HOT_KEY_TRANSLATOR_MODIFIER_GATE_BYTES,
    HOT_KEY_EXECUTE_HOOK: HOT_KEY_EXECUTE_HOOK_BYTES,
}


def _site_problems(data: bytes | bytearray, expected: dict[int, bytes]) -> list[str]:
    problems: list[str] = []
    for va, want in {**expected, **ANCHORS}.items():
        off = va_to_offset(data, va)
        if off is None or bytes(data[off : off + len(want)]) != want:
            problems.append(f"0x{va:08x}: not the expected game.dat hotkey bytes")
    return problems


class SpellbookHotkeysPatch(Patch):
    """Fire a spellbook power from Ctrl plus the `&` letter its own label already carries."""

    name = "spellbook-hotkeys"
    author = "officialNecro"
    experimental = True
    description = (
        "Lets spellbook powers be cast with Ctrl + their existing '&' shortcut letter, "
        "with nothing selected"
    )

    def apply(self, data: bytearray) -> None:
        problems = _site_problems(data, SITES)
        if problems:
            raise ValueError("; ".join(problems))
        section_va = allocate_section(data, SECTION_NAME, build_cave, _CHARACTERISTICS)
        gate_va, dispatch_va = cave_entries(section_va)
        for site, (va, target) in {
            "translator modifier gate": (HOT_KEY_TRANSLATOR_MODIFIER_GATE, gate_va),
            "hotkey executor": (HOT_KEY_EXECUTE_HOOK, dispatch_va),
        }.items():
            off = va_to_offset(data, va)
            assert off is not None  # checked before allocation
            stock = SITES[va]
            apply_byte_patch(data, off, stock, _detour(target, va, len(stock)), site)

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, vsize = located
        expected = build_cave(section_va)
        gate_va, dispatch_va = cave_entries(section_va)
        patched = {
            va: _detour(target, va, len(SITES[va]))
            for va, target in (
                (HOT_KEY_TRANSLATOR_MODIFIER_GATE, gate_va),
                (HOT_KEY_EXECUTE_HOOK, dispatch_va),
            )
        }
        problems = _site_problems(data, patched)
        if vsize != len(expected) or bytes(data[section_off : section_off + vsize]) != expected:
            problems.append(f"{SECTION_NAME} does not hold the expected spellbook hotkey cave")
        return problems
