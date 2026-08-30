"""The battle-school patch: give `AptMainMenu::BattleSchool` a way back out.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below comes
from :mod:`sage_patch.addresses` and is derived in ``../../docs/battle-school.md``.

**The gap.** BFME1's Battle School - the parchment book of tutorial videos on the main menu - was
two FSCommands: `AptMainMenu::BattleSchool` to go in and `AptMainMenu::TutorialExit` to come back.
ROTWK kept the first one, whole and working, and dropped the second. Going in still does what it
always did::

    0091B55C  mov  byte ptr [shell+0x5D], 1          ; a full-screen movie owns the screen
    0091B577  WindowTransitionsHandler::setGroup("MainMenuToBattleSchool")
    0091B586  stop the shell audio
    0091B5AF  FlashTutorial = 0                      ; and stop blinking the button

and coming back out does nothing at all, because the command that did it is not in the registry.
The transition is a `SOUNDFADE` with ``LeaveSilent = Yes``, so what the player gets is a main menu
that never makes another sound.

**Why this is not a second registration.** The callback map is filled by ~85-byte straight-line
blocks in the `AptMainMenu` constructor with no slack, so adding an entry means building an
`AsciiString`, wrapping a functor and calling `map::insert` from a cave. It is not necessary. The
surviving handler is `ret 4` - it **takes a params string and never reads it**. That unused
argument is the channel, exactly as `campaign-select` uses the discarded tail of its own::

    _root.GameCode("BattleSchool", "enter")     ; the stock behaviour, unchanged
    _root.GameCode("BattleSchool", "leave")     ; the half ROTWK is missing

**What it does.** Replaces the first five bytes of `BATTLE_SCHOOL_HANDLER` with a `jmp` into a cave
that reads `params[0]`. Anything but an ``l`` re-emits the five bytes it displaced and jumps back
to `BATTLE_SCHOOL_HANDLER + 5` - the `call __SEH_prolog` - with the stack untouched, so the stock
path is not merely equivalent to before, it *is* before. An ``l`` runs the exit arm instead.

**The exit arm** is modelled on `AptMainMenu::CreditsExit`'s tail (`CREDITS_EXIT_AUDIO_TAIL`),
which is the same function for the credits screen and is what ROTWK still ships:

- restart the shell music, if `Shell::isShellMusicPlaying` says it has stopped;
- `WindowTransitionsHandler::reverse("MainMenuToBattleSchool")` - the un-fade;
- clear `shell+0x5D`, releasing the screen;
- restore the frame-rate cap from `GlobalData.FramesPerSecondLimit`.

It **copies** that tail rather than calling into it, because the part of `CreditsExit` above the
tail tears down the credits movie player at `0x00DEBF50`, which Battle School never allocates.

Two lines of the template are deliberately **not** copied, on the principle that the exit arm
should undo what the enter arm did and nothing else: `0x0091B786`'s ``mov [esi+0x288], ebx``
(the menu phase - entering Battle School never sets it) and `0x0091B780`'s destruct of the
`GetExtern` scratch string at ``esi+0x2A4`` (entering never touches it either).

**The one new failure mode.** The stock handler never dereferences `params`; this one reads its
first byte. A NULL is guarded, and `campaign-select` - runtime-verified in game - establishes that
what reaches an `AptMainMenu` callback here is a real string when the movie supplies one. A movie
that sends no params at all is the empty-string case, which takes the stock path.

> **Shell-only and client-local.** Nothing here is in the simulation: it runs on a main-menu button
> press, before a game exists. Not CRC'd, does not cross the network, replays cross unpatched
> builds. Same rule as `campaign-select` and `observer-switch`.

**Composition.** Order-independent. It appends its own section with
:func:`~sage_patch.utils.allocate_section`, the five bytes it edits are touched by no other bundled
patch, and it reads nothing another patch rewrites.

**The movie's half is not in here.** The engine can now be told to leave; something has to tell it.
`docs/battle-school.md` §4 and §7 scope the `.apt` work, and `sage_apt`'s `BattleSchool.xml` is the
book itself.
"""

from __future__ import annotations

import struct

from ...addresses import (
    ASCII_STRING_CTOR,
    AUDIO_MANAGER,
    AUDIO_STOP_SLOT,
    BATTLE_SCHOOL_BLINK_REGISTRATION,
    BATTLE_SCHOOL_BLINK_REGISTRATION_BYTES,
    BATTLE_SCHOOL_HANDLER,
    BATTLE_SCHOOL_HANDLER_BYTES,
    BATTLE_SCHOOL_REGISTRATION,
    BATTLE_SCHOOL_REGISTRATION_BYTES,
    BATTLE_SCHOOL_TRANSITION_NAME,
    CREDITS_EXIT_AUDIO_TAIL,
    CREDITS_EXIT_AUDIO_TAIL_BYTES,
    GAME_ENGINE,
    GAME_ENGINE_SET_FPS_SLOT,
    GLOBAL_DATA,
    GLOBAL_DATA_FPS_LIMIT,
    SHELL,
    SHELL_MOVIE_ACTIVE,
    SHELL_MUSIC_PLAYING,
    SHELL_MUSIC_PLAYING_BYTES,
    SHELL_PLAY_MUSIC,
    SHELL_PLAY_MUSIC_BYTES,
    WINDOW_TRANSITION_REVERSE,
    WINDOW_TRANSITION_REVERSE_BYTES,
    WINDOW_TRANSITIONS_HANDLER,
)
from ...asm import JE, JNE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "ENTER",
    "EXIT",
    "SECTION_NAME",
    "BattleSchoolPatch",
    "build_code",
    "leaves",
    "params",
]

#: 8 chars max: the PE name field truncates silently past 8.
SECTION_NAME = ".btlsch"

# CNT_CODE | MEM_EXECUTE | MEM_READ. Nothing in this cave is written at run time, unlike
# `campaign-select`'s, so it does not need to be writable.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

#: The two params strings the `.apt` sends. Only the **first character** reaches the engine, so
#: the two words have to differ in it - "enter"/"exit" would not, which is why leaving is spelled
#: `"leave"`. The rest of each word is for whoever reads the movie. `ENTER` is spelled out rather
#: than left empty so both buttons look alike in the `.apt`; anything that is not an ``l`` word
#: means the same thing, including the empty string a stock-shaped `GameCode("BattleSchool")`
#: produces.
ENTER = "enter"
EXIT = "leave"

#: What the cave compares `params[0]` against, after OR-ing in `0x20`. ASCII-folding rather than
#: testing two constants costs two bytes and makes ``"Leave"`` work as well as ``"leave"``.
_EXIT_INITIAL = ord("l")
_CASE_FOLD = 0x20

#: How many of the handler's bytes the `jmp` takes over. The other 164 are left as they were:
#: reachable again through the cave's `enter` arm, and a fingerprint `verify` can still read.
_DETOUR_LEN = 5

#: `mov eax, imm32` - the SEH prologue's cookie load, and the whole reason a five-byte detour is
#: clean here. The cave re-emits these bytes verbatim, which is only correct because the
#: instruction carries no relative displacement; `_check_handler` refuses a build where it is not
#: this opcode.
_COOKIE_LOAD_OPCODE = 0xB8


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def params(leaving: bool) -> str:
    """The params string the `.apt` passes to ``GameCode("BattleSchool", …)``."""
    return EXIT if leaving else ENTER


def leaves(text: str) -> bool:
    """Whether the cave would take ``text`` as "leave Battle School" - the rule in Python, so the
    tests can hold the emitted code to the same one the `.apt` is written against."""
    return bool(text) and (ord(text[0]) | _CASE_FOLD) == _EXIT_INITIAL


def build_code(code_va: int) -> bytes:
    """The replacement callback, assembled to run at ``code_va``.

    Entered by the `jmp` that replaced the handler's first five bytes, so on entry `ecx` is the
    `AptMainMenu`, `[esp]` is the caller's return address and `[esp+4]` is the params string.

    The `enter` arm touches only `eax` before handing control back, so the stock handler resumes
    with every other register, and the stack, exactly as it found them.
    """
    a = Asm(code_va)

    # --- which direction? ---
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov eax, [esp+4]        ; params
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "enter")  # no params at all -> stock
    a.emit(0x8A, 0x10)  # mov dl, [eax]
    a.emit(0x80, 0xCA, _CASE_FOLD)  # or dl, 0x20             ; fold; 0 stays non-'l'
    a.emit(0x80, 0xFA, _EXIT_INITIAL)  # cmp dl, 'l'
    a.jcc(JNE, "enter")

    # --- the exit arm ---
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(0x33, 0xDB)  # xor ebx, ebx            ; the zero the tail is written around
    a.emit(0x8B, 0xF1)  # mov esi, ecx            ; the AptMainMenu

    # Restart the shell music if it stopped, exactly as `CreditsExit` does. A NULL shell skips
    # the whole block: the template falls into the audio stop instead, but it then calls
    # `SHELL_PLAY_MUSIC` on that same NULL, so following it there would only move the fault.
    a.emit(0x8B, 0x0D, _u32(SHELL))  # mov ecx, [SHELL]
    a.emit(0x3B, 0xCB)  # cmp ecx, ebx
    a.jcc(JE, "transition")
    a.call_absolute(SHELL_MUSIC_PLAYING)  # Shell::isShellMusicPlaying()
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JNE, "transition")  # still playing -> leave it alone
    a.emit(0x8B, 0x0D, _u32(AUDIO_MANAGER))  # mov ecx, [TheAudio]
    a.emit(0x3B, 0xCB)  # cmp ecx, ebx
    a.jcc(JE, "restart")
    a.emit(0x8B, 0x01)  # mov eax, [ecx]          ; the vtable
    a.emit(0x53)  # push ebx
    a.emit(0x6A, 0x01)  # push 1
    a.emit(0x6A, 0x02)  # push 2
    a.emit(0xFF, 0x90, _u32(AUDIO_STOP_SLOT))  # call [eax+0x8C]
    a.label("restart")
    a.emit(0x8B, 0x0D, _u32(SHELL))  # mov ecx, [SHELL]
    a.call_absolute(SHELL_PLAY_MUSIC)  # Shell::playShellMusic()

    # Reverse the transition group the enter arm set. The argument is a by-value `AsciiString`,
    # which on this compiler means: reserve the slot, construct into it, and let the callee both
    # destroy it and pop it (`ret 4` on each of the two calls).
    a.label("transition")
    a.emit(0x51)  # push ecx                ; the slot
    a.emit(0x8B, 0xCC)  # mov ecx, esp            ; -> the AsciiString
    a.emit(0x68, _u32(BATTLE_SCHOOL_TRANSITION_NAME))  # push "MainMenuToBattleSchool"
    a.call_absolute(ASCII_STRING_CTOR)
    a.emit(0x8B, 0x0D, _u32(WINDOW_TRANSITIONS_HANDLER))  # mov ecx, [handler]
    a.call_absolute(WINDOW_TRANSITION_REVERSE)

    # Release the screen.
    a.emit(0xA1, _u32(SHELL))  # mov eax, [SHELL]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "framerate")
    a.emit(0x88, 0x58, SHELL_MOVIE_ACTIVE)  # mov byte ptr [eax+0x5D], bl

    # Restore the frame-rate cap the movie playback raised.
    a.label("framerate")
    a.emit(0x8B, 0x15, _u32(GLOBAL_DATA))  # mov edx, [TheWritableGlobalData]
    a.emit(0x8B, 0x0D, _u32(GAME_ENGINE))  # mov ecx, [TheGameEngine]
    a.emit(0xFF, 0x72, GLOBAL_DATA_FPS_LIMIT)  # push [edx+0x28]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x50, GAME_ENGINE_SET_FPS_SLOT)  # call [eax+0x48]

    a.emit(0x5E)  # pop esi
    a.emit(0x5B)  # pop ebx
    a.emit(0xC2, 0x04, 0x00)  # ret 4

    # --- the stock arm: the displaced bytes, then back where they were ---
    a.label("enter")
    a.emit(BATTLE_SCHOOL_HANDLER_BYTES[:_DETOUR_LEN])
    a.jmp_absolute(BATTLE_SCHOOL_HANDLER + _DETOUR_LEN)
    return a.finish()


def build_section(base_va: int) -> bytes:
    return build_code(base_va)


#: The sites that have to still hold their stock bytes for the patch to mean what it says, by
#: address. The handler's own first five bytes are *not* among them - those are the edit - but its
#: tail is, and so is every routine the cave calls and the registration that proves the handler is
#: the Battle School one rather than a neighbour of the same shape.
ANCHORS = {
    BATTLE_SCHOOL_REGISTRATION: BATTLE_SCHOOL_REGISTRATION_BYTES,
    BATTLE_SCHOOL_BLINK_REGISTRATION: BATTLE_SCHOOL_BLINK_REGISTRATION_BYTES,
    CREDITS_EXIT_AUDIO_TAIL: CREDITS_EXIT_AUDIO_TAIL_BYTES,
    SHELL_MUSIC_PLAYING: SHELL_MUSIC_PLAYING_BYTES,
    SHELL_PLAY_MUSIC: SHELL_PLAY_MUSIC_BYTES,
    WINDOW_TRANSITION_REVERSE: WINDOW_TRANSITION_REVERSE_BYTES,
}


class BattleSchoolPatch(Patch):
    name = "battle-school"
    author = "officialNecro"
    experimental = True
    description = (
        "Restore the way out of BFME1's Battle School screen: the surviving "
        "AptMainMenu::BattleSchool command reads its unused params argument, so "
        "GameCode('BattleSchool', 'leave') reverses the sound fade ROTWK can currently only "
        "start. The mod supplies the movie - the tutorial book and its videos"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        self._check_handler(data)

        off = va_to_offset(data, BATTLE_SCHOOL_HANDLER)
        if off is None:
            raise ValueError(
                f"{BATTLE_SCHOOL_HANDLER:#010x} is not mapped - not the expected build"
            )
        code_va = allocate_section(data, SECTION_NAME, build_section, _CHARACTERISTICS)
        jump = b"\xe9" + struct.pack("<i", code_va - (BATTLE_SCHOOL_HANDLER + _DETOUR_LEN))
        apply_byte_patch(
            data,
            off,
            BATTLE_SCHOOL_HANDLER_BYTES[:_DETOUR_LEN],
            jump,
            "AptMainMenu::BattleSchool -> the callback that also knows how to leave",
        )

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the Battle School "
                    "path is not this build's"
                )

    @staticmethod
    def _check_handler(data: bytes | bytearray) -> None:
        """Raise unless the handler's **tail** - everything the `jmp` does not cover - is still
        stock, and unless the five bytes it does cover are the position-independent cookie load
        the cave re-emits. The first five are excluded from the fingerprint so this one check can
        serve :meth:`apply` and :meth:`verify` alike; their *opcode* is checked separately,
        against the stock bytes rather than the image, because after `apply` the image holds a
        `jmp` there.
        """
        if BATTLE_SCHOOL_HANDLER_BYTES[0] != _COOKIE_LOAD_OPCODE:
            raise ValueError(
                f"{BATTLE_SCHOOL_HANDLER:#010x} does not begin with a mov eax, imm32 - the "
                "displaced bytes cannot be re-emitted somewhere else"
            )
        off = va_to_offset(data, BATTLE_SCHOOL_HANDLER)
        if off is None:
            raise ValueError(
                f"{BATTLE_SCHOOL_HANDLER:#010x} is not mapped - not the expected build"
            )
        expected = BATTLE_SCHOOL_HANDLER_BYTES[_DETOUR_LEN:]
        got = bytes(data[off + _DETOUR_LEN : off + len(BATTLE_SCHOOL_HANDLER_BYTES)])
        if got != expected:
            raise ValueError(
                f"{BATTLE_SCHOOL_HANDLER + _DETOUR_LEN:#010x} is {got.hex()}, expected "
                f"{expected.hex()} - this is not the Battle School handler this patch replaces"
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"the {SECTION_NAME} section is absent - not installed"]
        code_va, section_off, _ = located

        off = va_to_offset(data, BATTLE_SCHOOL_HANDLER)
        if off is None:
            return [f"{BATTLE_SCHOOL_HANDLER:#010x} is not mapped by any section"]
        if data[off] != 0xE9:
            problems.append(
                f"{BATTLE_SCHOOL_HANDLER:#010x} is not a jmp - the handler is unpatched"
            )
        else:
            rel = struct.unpack_from("<i", data, off + 1)[0]
            target = BATTLE_SCHOOL_HANDLER + _DETOUR_LEN + rel
            if target != code_va:
                problems.append(
                    f"the Battle School handler jumps to {target:#010x}, expected {code_va:#010x}"
                )

        expected = build_code(code_va)
        got = bytes(data[section_off : section_off + len(expected)])
        if got != expected:
            problems.append(f"the {SECTION_NAME} cave does not hold this patch's code")

        try:
            self._check_anchors(data)
            self._check_handler(data)
        except ValueError as exc:
            problems.append(str(exc))
        return problems
