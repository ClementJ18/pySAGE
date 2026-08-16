"""The description-timers patch: how long a button's thing takes, at the bottom of its description.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../docs/description-timers.md``.

**What the engine does today.** A `CommandButton`'s tooltip says what a thing costs and never says
how long it takes. An ability's cooldown, a unit's build time and an upgrade's research time are
all computed by the engine, all visible to it at the moment the tooltip is built, and none of them
is written down anywhere the player can read.

**What this patch adds.** One line at the end of the description:

- a **special-power** button gets its cooldown - the full length while the power is ready, the
  **time left** while it is recharging;
- a button carrying a **`ThingTemplate`** gets its build time;
- an **upgrade** button the player does not already own gets its research time.

**Everything is in logic frames until the last step, and the logic frame rate is 5.** The three
fields these numbers come from are *not* in the same units in INI - `SpecialPower.ReloadTime` is
**milliseconds**, while `Object.BuildTime` and `Upgrade.BuildTime` are **seconds** - but all three
are converted to frames before they are stored, so this patch never sees the difference: the
`ReloadTime` parser (`0x0073A429`) multiplies by `logic/1000`, and both `calcTimeToBuild` functions
multiply by the rate on the way out. Only the final divide has to know the rate, and it reads it
live from :data:`LOGIC_FRAMES_PER_SECOND` - which is **`0x00D9F608`, holding 5**, not the 30 four
bytes above it. Getting that one wrong is a silent factor of six on every line the patch prints.

**Every number is the engine's own.** Nothing here re-derives a duration from INI. The cooldown is
`SpecialAbilityUpdate::startPowerRecharge`'s arithmetic transcribed instruction for instruction
(:data:`GET_MODIFIER_MULTIPLIER` for the `RECHARGE_TIME` attribute modifier, `Player+0x718` for the
`SpellRechargeModifierUpgrade` discount, both live), and the two build times are
:data:`THING_TEMPLATE_CALC_TIME_TO_BUILD` and :data:`UPGRADE_TEMPLATE_CALC_TIME_TO_BUILD` - the
same two functions `ProductionUpdate` asks for a queue entry's total, so the tooltip cannot
disagree with what the game then does. **That is also what makes "with the reduction taken into
account" free**: the producer's `ProductionModifier` time multiplier is applied inside
`calcTimeToBuild`, and a leadership aura that is up right now is inside the modifier query.

**Two hooks, and why the first one exists.** The line is appended at
:data:`~..addresses.DESCRIPTION_TAIL`, the one instruction past the point where every case of the
builder's switch has converged - which is what makes it genuinely *last*, where a per-case site
cannot be (the `CONTROLBAR:Requirements` and `TOOLTIP:BuildDisabled` folds run after several of
them). The cost of being that late is that `esi` no longer holds the builder's `this`: three cases
reassign it, so `[esi+0xc]` is not the button any more. So a second, 6-byte window in the prologue
at :data:`~..addresses.DESCRIPTION_BUTTON_CAPTURE` - on the function's unconditional path, at the
instruction that loads the button - takes a copy into the cave. The builder is not reentrant (it
runs on hover, on one client, from a single call site at `0x00807676`), and the copy is refreshed
on every build, so the stash cannot go stale.

**Silent unless the mod declares the string.** `TheGameText`'s fetch takes an `exists`
out-parameter that all twelve stock callers pass `0` for. This passes a real one and drops the
whole line - separator included - when the key is missing, so on a string table that has not added
these four keys the tooltip is **byte-identical to a stock build**. A modder opts in one line at a
time by adding `TOOLTIP:Cooldown`, `TOOLTIP:CooldownRemaining`, `TOOLTIP:BuildTime` or
`TOOLTIP:ResearchTime`, each taking one `%.1f` (or one `%d` under ``--integer-seconds``).

**The honest limit: the tooltip is built once per hover.** `0x00DE8998` latches at `0x00807971`
and the same-request path returns early on every frame after, so nothing rebuilds the text while
the pointer sits still. The three full durations are unaffected - they do not change while you look
at them - but **the remaining cooldown is a snapshot** taken when the tooltip appeared, not a
countdown. Moving off the button and back re-reads it. Making it tick means forcing a repaint,
which is a second patch to a second function and a question about the movie that only a live test
answers; ``docs/description-timers.md`` §2 is the write-up.

**What is deliberately not covered.** Hero revive and recruit buttons, whose time comes off the
player's hero ledger rather than the `ThingTemplate` (`0x00780687`), are skipped rather than given
the base number - the test is the engine's own, :data:`THING_TEMPLATE_HERO_FLAG`. A power whose
module is the second `startPowerRecharge` flavour (`0x00991500`, 3 vtables of 26) keeps its ready
frame at a different offset, so the remaining lookup falls back to the full duration rather than
reading the wrong field. Both fail towards saying less, never towards saying something wrong.

> **Client-local and read-only.** This runs inside the ControlBar's tooltip builder on hover.
> Nothing enters the simulation, nothing is sent, no INI keyword changes and no `.apt` edit is
> needed. A patched and an unpatched client can play each other and replays cross, the same rule as
> `upgrade-description`, `replay-outcome` and `observer-switch`.

**Composition.** Order-independent. The cave is allocated with
:func:`~..utils.allocate_section` and :meth:`verify` finds it by name; the twelve bytes it rewrites
are touched by no other bundled patch. Three other patches edit this same function and all of them
are disjoint: `upgrade-description` at `0x00808371`/`0x0080830C`, and `hero-mana` at `0x008085C4`
and `0x00808675`. `hero-mana` appends to the same description slot, which composes by construction
- its `ManaCost` line simply lands above this one.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from ..addresses import (
    DESCRIPTION_BUTTON_CAPTURE,
    DESCRIPTION_BUTTON_CAPTURE_BYTES,
    DESCRIPTION_BUTTON_CAPTURE_RESUME,
    DESCRIPTION_OBJECT_EBP_OFFSET,
    DESCRIPTION_PLAYER_EBP_OFFSET,
    DESCRIPTION_TAIL,
    DESCRIPTION_TAIL_BYTES,
    DESCRIPTION_TAIL_RESUME,
    DESCRIPTION_TEXT_EBP_OFFSET,
    FLOAT_ONE,
    GAME_LOGIC_FRAME,
    GAME_TEXT_FORMAT_SLOT,
    GET_FINAL_OVERRIDE,
    THE_GAME_LOGIC,
    THE_GAME_TEXT,
    UNICODE_STRING_APPEND,
    UNICODE_STRING_CONCAT_WIDE,
    WIDE_NEWLINE,
)
from ..addresses import (
    UNICODE_STRING_CONCAT as UNICODE_STRING_FORMAT,
)
from ..asm import JE, JG, JGE, JLE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "ANCHORS",
    "KEYS",
    "SECTION_NAME",
    "DescriptionTimersPatch",
]

#: 8 chars max: the PE name field truncates silently past 8.
SECTION_NAME = ".dsctim"

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. Writable because of the
# one dword the capture hook stores the CommandButton in; `herobar` allocates its slot cursors the
# same way for the same reason.
_CHARACTERISTICS = 0xE0000060

#: `CommandButton::getThingTemplate` - `__thiscall(ecx=CommandButton *)`, no arguments, returns the
#: template in `eax`. The builder's own prologue calls it at `0x00807B14`.
COMMAND_BUTTON_GET_THING_TEMPLATE = 0x0075D1DC
COMMAND_BUTTON_GET_THING_TEMPLATE_BYTES = bytes.fromhex("568d71208bce")

#: `CommandButton` fields this patch reads: the GUI command, the `UpgradeTemplate` and the
#: `SpecialPowerTemplate`.
COMMAND_BUTTON_GUI_COMMAND = 0x14
COMMAND_BUTTON_UPGRADE = 0x24
COMMAND_BUTTON_SPECIAL_POWER = 0x44

#: The two GUI commands the builder's own cost block refuses (`0x00807F12` / `0x00807F1B`). A
#: button carrying a `ThingTemplate` under either of them is described without a cost, so it is
#: described without a time too - mirroring the engine rather than inventing a rule.
GUI_COMMANDS_WITHOUT_COST = (0x19, 0x34)

#: `Object::getSpecialPowerModule(SpecialPowerTemplate *)` - `__thiscall`, `ret 4`, NULL when the
#: object has no module for that template. It walks `Object+0x24C`, asks each module for its
#: special-power interface and matches on interface slot `+0x00` (`0x008969D1`), which compares the
#: module data's template pointer - the same raw pointer `CommandButton+0x44` holds.
GET_SPECIAL_POWER_MODULE = 0x0068C26D
GET_SPECIAL_POWER_MODULE_BYTES = bytes.fromhex("837c24040075")

#: `Object::getModifierMultiplier(type, out, ctx, flag)` - `__thiscall` plus four stack arguments,
#: `ret 0x10`, seeds `*out` at 1.0 and multiplies. **It does not preserve `ecx`.**
GET_MODIFIER_MULTIPLIER = 0x0068C82D

#: Attribute-modifier type 12, the one `startPowerRecharge` folds into a cooldown.
MODIFIER_TYPE_RECHARGE_TIME = 0x0C

#: `Player`'s spell-recharge modifier, read the way the recharge maths reads it: `__thiscall`, no
#: arguments, leaves `Player+0x718` on the FPU stack.
PLAYER_RECHARGE_MODIFIER = 0x006AAAD2
PLAYER_RECHARGE_MODIFIER_BYTES = bytes.fromhex("d98118070000c3")

#: `Player::hasUpgradeComplete(UpgradeTemplate *)` - `__thiscall`, `ret 4`, answers in `al`. The
#: builder asks it at `0x0080816E`; this patch asks again rather than reading the frame byte it
#: caches the answer in, because that byte is only meaningful on the upgrade path.
PLAYER_HAS_UPGRADE_COMPLETE = 0x006AC2AF
PLAYER_HAS_UPGRADE_COMPLETE_BYTES = bytes.fromhex("8b44240485c07504")

#: `ThingTemplate::calcTimeToBuild(Player *, Object *, Int override)` - `__thiscall`, `ret 0xC`,
#: returns frames. `-1` means "use the template's own `BuildTime`". The identical call shape one
#: function along is the cost line at `0x00807F37`.
THING_TEMPLATE_CALC_TIME_TO_BUILD = 0x0073C39E
THING_TEMPLATE_CALC_TIME_TO_BUILD_BYTES = bytes.fromhex("558bec837d10ff5356")

#: `UpgradeTemplate::calcTimeToBuild(Player *, Object *)` - `__thiscall`, `ret 8`, returns frames.
#: Established from the production queue's own kind-2 arm at `0x008A0514`.
UPGRADE_TEMPLATE_CALC_TIME_TO_BUILD = 0x0066F1A8
UPGRADE_TEMPLATE_CALC_TIME_TO_BUILD_BYTES = bytes.fromhex("568bf18b4c2408")

#: The `ThingTemplate` byte and bit the builder itself dispatches the hero rank case on
#: (`0x00807752`). A button describing a hero is skipped: its time comes off the player's ledger,
#: not off this template, and printing the template's number would be printing a number that is
#: missing the hero time multiplier.
THING_TEMPLATE_HERO_FLAG = 0x11F
THING_TEMPLATE_HERO_FLAG_MASK = 0x40

#: `SpecialPowerTemplate` fields the cooldown formula reads.
SPECIAL_POWER_TEMPLATE_FLAGS = 0x18
SPECIAL_POWER_TEMPLATE_RELOAD_TIME = 0x20
#: `Flags` bit 5, `RESPECT_RECHARGE_TIME_DISCOUNT`, tested at the only instruction in the binary
#: that reads it (`0x00896EBA`).
RESPECT_RECHARGE_TIME_DISCOUNT_SHIFT = 5

#: `SpecialPowerModuleInterface`: where flavour 1 keeps its absolute ready frame, and the vtable
#: slot that identifies the flavour. There are two implementations of `startPowerRecharge` and the
#: other one (`0x00991500`) keeps its ready frame at `+0x04` instead, so reading `+0x08` on it
#: would print a frame number as a duration. Fail closed: anything that is not flavour 1 falls back
#: to the full duration.
SPECIAL_POWER_INTERFACE_READY_FRAME = 0x08
SPECIAL_POWER_INTERFACE_RECHARGE_SLOT = 0x3C
SPECIAL_POWER_START_RECHARGE = 0x00896E31
SPECIAL_POWER_START_RECHARGE_BYTES = bytes.fromhex("558bec83ec0c568bf1")

#: `UnicodeString::~UnicodeString` - `__thiscall`, no arguments. Releases the reference the object
#: holds on its buffer. Reached by name here because the line this patch builds is a temporary of
#: its own, which the stock idiom never needs: the twelve engine sites format into a slot the
#: builder itself destroys on the way out.
#:
#: **The name imported for `0x00ADF7E0` is a warning, not a preference.**
#: :data:`~..addresses.UNICODE_STRING_CONCAT` **replaces** its destination - it ends in a
#: `vswprintf` into a scratch buffer followed by a `set` - and is imported here as
#: `UNICODE_STRING_FORMAT` so that no reader of this file can make the mistake that produced the
#: first version of it, which formatted straight into `ebp-0x18` and deleted every description it
#: touched.
UNICODE_STRING_DESTRUCT = 0x004367B0
UNICODE_STRING_DESTRUCT_BYTES = bytes.fromhex("6aff68f80eb70064a100000000506489250000000083ec08")

#: `ftol`, and the constant the engine adds when an `fild`'d dword was meant as unsigned. Both are
#: copied from the recharge maths rather than simplified away.
FTOL = 0x00A3CFA4
FLOAT_U32_FIXUP = 0x00BD8698

#: **The logic frame rate**, as an `Int`, and the divisor that turns every duration here into
#: seconds. It is **5**, not the 30 sitting four bytes above it - and picking the wrong one of the
#: two is a silent factor-of-six error in every number this patch prints, so the derivation is
#: worth stating.
#:
#: Both are written at runtime by :data:`FRAME_RATE_SETUP`, which takes the two rates as arguments
#: and derives a block of ratios from them: `[0x00D9F610] = logic/1000` (the millisecond-to-frame
#: factor the `ReloadTime` parser at `0x0073A429` multiplies by, and it holds **0.005**),
#: `[0x00D9F614] = 1000/logic` (**200** ms per logic frame) and `[0x00D9F61C] = 1/logic`
#: (**0.2** seconds per logic frame). Every one of those says 5. The second rate, at `0x00D9F60C`,
#: is the client's - `[0x00D9F620]` is its 33.33 ms and `[0x00D9F62C]` its 1/30 - and the setter
#: caps the ratio between them at six, which 30/5 exactly meets.
#:
#: It is also confirmed from outside the binary: `sage_replay`'s finalized BFME2 corpus clusters at
#: **0.20 seconds per timecode** measured against each replay's own wall-clock span
#: (`_NOMINAL_SECONDS_PER_FRAME` in [`sage_replay.replay`](../../sage_replay/replay.py)).
LOGIC_FRAMES_PER_SECOND = 0x00D9F608

#: The routine that fills that block, at the `mov [0x00D9F608], esi` which is what *makes* the
#: global above the logic rate rather than the client one. Anchored because the patch's whole
#: unit conversion rests on which of the two adjacent dwords is which, and nothing else it checks
#: would notice them being swapped.
FRAME_RATE_SETUP = 0x00644FA6
FRAME_RATE_SETUP_BYTES = bytes.fromhex("893508f6d900")

#: The localization keys, in the order they are laid out in the cave. Each takes **one** format
#: argument: a `%.1f` by default, a `%d` under ``--integer-seconds``. A key the string table does
#: not define produces no line at all - see the module docstring.
KEYS: dict[str, str] = {
    "cooldown": "TOOLTIP:Cooldown",
    "cooldown_remaining": "TOOLTIP:CooldownRemaining",
    "build_time": "TOOLTIP:BuildTime",
    "research_time": "TOOLTIP:ResearchTime",
}

#: Everything the cave calls, reads or compares against, by address and by first bytes. A patch
#: whose whole job is calling twelve engine functions with the right arguments has no way to notice
#: that one of them moved: it would simply call whatever now lives there. So each is asserted
#: before a byte is written.
#:
#: :data:`SPECIAL_POWER_START_RECHARGE` is here for a second reason - the cave does not call it, it
#: *compares a vtable slot against it*, and if that function moved the comparison would answer "not
#: flavour 1" for every power in the game and the remaining readout would silently disappear.
ANCHORS: dict[int, bytes] = {
    FRAME_RATE_SETUP: FRAME_RATE_SETUP_BYTES,
    COMMAND_BUTTON_GET_THING_TEMPLATE: COMMAND_BUTTON_GET_THING_TEMPLATE_BYTES,
    GET_SPECIAL_POWER_MODULE: GET_SPECIAL_POWER_MODULE_BYTES,
    PLAYER_RECHARGE_MODIFIER: PLAYER_RECHARGE_MODIFIER_BYTES,
    PLAYER_HAS_UPGRADE_COMPLETE: PLAYER_HAS_UPGRADE_COMPLETE_BYTES,
    THING_TEMPLATE_CALC_TIME_TO_BUILD: THING_TEMPLATE_CALC_TIME_TO_BUILD_BYTES,
    UPGRADE_TEMPLATE_CALC_TIME_TO_BUILD: UPGRADE_TEMPLATE_CALC_TIME_TO_BUILD_BYTES,
    SPECIAL_POWER_START_RECHARGE: SPECIAL_POWER_START_RECHARGE_BYTES,
    UNICODE_STRING_DESTRUCT: UNICODE_STRING_DESTRUCT_BYTES,
}

#: The cast-time arithmetic this patch transcribes, at the two instructions that carry its whole
#: meaning: the `RESPECT_RECHARGE_TIME_DISCOUNT` test (`mov eax, [eax+0x18]` / `shr eax, 5` /
#: `test al, 1`) and the `ReloadTime` read. If a build encodes either differently, the transcription
#: in :func:`_emit_ability` is describing a formula that build does not use.
RECHARGE_FORMULA_ANCHORS: dict[int, bytes] = {
    0x00896EBA: bytes.fromhex("8b4018c1e805a801"),
    0x00896EE3: bytes.fromhex("8b4020"),
}


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _i8(value: int) -> int:
    """A signed byte displacement as the unsigned byte that encodes it."""
    return value & 0xFF


# Everything below is hand-encoded (the house style: only address arithmetic is automated, by
# `..asm`), with a comment saying what each instruction is.

_EBP_TEXT = _i8(DESCRIPTION_TEXT_EBP_OFFSET)
_EBP_OBJECT = _i8(DESCRIPTION_OBJECT_EBP_OFFSET)
_EBP_PLAYER = _i8(DESCRIPTION_PLAYER_EBP_OFFSET)


def _emit_line(a: Asm, integer_seconds: bool) -> None:
    """`eax` = a duration in logic frames, `edx` = a localization key. Appends one line.

    Clobbers `eax`, `ecx` and `edx` and preserves everything else, which is what lets the three
    arms keep the button in `esi` and the full duration in `edi` across it.

    Three locals live below `esp` for the length of the routine: the frame count (the format
    argument has to survive the fetch), the fetch's `exists` out-parameter, and the fetched format
    string (it has to survive the separator's `concat`, and no engine call promises to preserve a
    register across one).
    """
    a.label("emit_line")
    # [esp]=frames  [esp+4]=exists  [esp+8]=fmt  [esp+0xc]=the line being built
    a.emit(0x83, 0xEC, 0x10)  # sub esp, 0x10
    a.emit(0x89, 0x04, 0x24)  # mov [esp], eax
    a.emit(0x83, 0x64, 0x24, 0x04, 0x00)  # and dword [esp+4], 0
    a.emit(0x83, 0x64, 0x24, 0x0C, 0x00)  # and dword [esp+0xc], 0    an empty UnicodeString

    # TheGameText->fetch(key, &exists). `__thiscall`, `ret 8`, and the string it returns is not
    # owned by the caller - which is why the twelve stock sites destroy nothing and touch no
    # exception-handling state, and why this routine does not have to either.
    a.emit(0x8D, 0x4C, 0x24, 0x04)  # lea ecx, [esp+4]          -> &exists
    a.emit(0x51)  # push ecx
    a.emit(0x52)  # push edx                                    -> the key
    a.emit(0x8B, 0x0D, _u32(THE_GAME_TEXT))  # mov ecx, [TheGameText]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x50, GAME_TEXT_FORMAT_SLOT)  # call [eax+0x44]
    a.emit(0x89, 0x44, 0x24, 0x08)  # mov [esp+8], eax

    # The whole line is dropped when the string table has no such key, separator included.
    a.emit(0x83, 0x7C, 0x24, 0x04, 0x00)  # cmp dword [esp+4], 0
    a.jcc(JE, "el_drop")

    # The engine's own "is there anything to separate from" test, from the two folds at
    # `0x008080AE` and `0x008080FB`: a null buffer pointer, or a zero length word inside it. Those
    # sites compare against `edi`, which is their path's zero and is not reliably zero here, so this
    # compares with immediates.
    a.emit(0x8B, 0x4D, _EBP_TEXT)  # mov ecx, [ebp-0x18]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "el_no_separator")
    a.emit(0x66, 0x83, 0x79, 0x04, 0x00)  # cmp word [ecx+4], 0
    a.jcc(JE, "el_no_separator")
    a.emit(0x68, _u32(WIDE_NEWLINE))  # push <L"\n">
    a.emit(0x8D, 0x4D, _EBP_TEXT)  # lea ecx, [ebp-0x18]
    a.call_absolute(UNICODE_STRING_CONCAT_WIDE)  # thiscall, ret 4

    a.label("el_no_separator")
    # `UNICODE_STRING_FORMAT` **replaces** its destination - it ends in `vswprintf` into a scratch
    # buffer and then `set`s. The twelve engine sites hide that, because each of them formats into
    # a slot it is the only writer of. So the line is built in a local of its own and joined to the
    # description with `concat`, which is the same two-step the builder's own rank case performs at
    # `0x008085C4`. Formatting straight into `ebp-0x18` would delete the description.
    if integer_seconds:
        a.emit(0x8B, 0x04, 0x24)  # mov eax, [esp]
        a.emit(0x99)  # cdq
        a.emit(0xF7, 0x3D, _u32(LOGIC_FRAMES_PER_SECOND))  # idiv dword [logic fps]
        a.emit(0x50)  # push eax                                 the one dword vararg
        a.emit(0xFF, 0x74, 0x24, 0x0C)  # push dword [esp+0xc]   the format string
        a.emit(0x8D, 0x4C, 0x24, 0x14)  # lea ecx, [esp+0x14]    -> the line local
        a.emit(0x51)  # push ecx                                 the destination
        a.call_absolute(UNICODE_STRING_FORMAT)  # cdecl
        a.emit(0x83, 0xC4, 0x0C)  # add esp, 0xc     one vararg + the format's two arguments
    else:
        # A `double` vararg, the way `CONTROLBAR:UnderConstructionDesc` passes one at `0x00677E62`
        # - which is also where the cleanup constant of 0x10 rather than 0xc comes from.
        a.emit(0xDB, 0x04, 0x24)  # fild dword [esp]                       the frame count
        a.emit(0xDA, 0x35, _u32(LOGIC_FRAMES_PER_SECOND))  # fidiv dword [logic fps] -> seconds
        a.emit(0x83, 0xEC, 0x08)  # sub esp, 8
        a.emit(0xDD, 0x1C, 0x24)  # fstp qword [esp]                       the vararg
        a.emit(0xFF, 0x74, 0x24, 0x10)  # push dword [esp+0x10]            the format string
        a.emit(0x8D, 0x4C, 0x24, 0x18)  # lea ecx, [esp+0x18]              -> the line local
        a.emit(0x51)  # push ecx                                           the destination
        a.call_absolute(UNICODE_STRING_FORMAT)  # cdecl
        a.emit(0x83, 0xC4, 0x10)  # add esp, 0x10   the double + the format's two arguments

    # The line joins the description, rather than becoming it.
    a.emit(0x8D, 0x44, 0x24, 0x0C)  # lea eax, [esp+0xc]        -> the line
    a.emit(0x50)  # push eax
    a.emit(0x8D, 0x4D, _EBP_TEXT)  # lea ecx, [ebp-0x18]
    a.call_absolute(UNICODE_STRING_APPEND)  # concat(const UnicodeString &), thiscall, ret 4

    # And releases the buffer it took. The `el_drop` path skips this deliberately: it is reached
    # before the format, with the local still the zero it was initialised to and owning nothing.
    a.emit(0x8D, 0x4C, 0x24, 0x0C)  # lea ecx, [esp+0xc]
    a.call_absolute(UNICODE_STRING_DESTRUCT)  # ~UnicodeString, thiscall, no arguments

    a.label("el_drop")
    a.emit(0x83, 0xC4, 0x10)  # add esp, 0x10
    a.emit(0xC3)  # ret


def _emit_ability(a: Asm) -> None:
    """`esi` = the CommandButton, `ebx` = its SpecialPowerTemplate.

    The full duration is computed first and unconditionally, because it is also the fallback for
    every way the remaining lookup can decline to answer.
    """
    a.label("ability")

    # Two locals: the RECHARGE_TIME attribute multiplier and the player discount, both seeded at
    # 1.0 exactly as `startPowerRecharge` seeds them.
    a.emit(0x83, 0xEC, 0x08)  # sub esp, 8
    a.emit(0xC7, 0x04, 0x24, _u32(0x3F800000))  # mov dword [esp], 1.0f
    a.emit(0xC7, 0x44, 0x24, 0x04, _u32(0x3F800000))  # mov dword [esp+4], 1.0f

    a.emit(0x8B, 0x4D, _EBP_OBJECT)  # mov ecx, [ebp-0x1c]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "ab_no_object")  # no object: the attribute multiplier stays 1.0
    a.emit(0x6A, 0x01)  # push 1
    a.emit(0x6A, 0x00)  # push 0
    a.emit(0x8D, 0x44, 0x24, 0x08)  # lea eax, [esp+8]        -> the multiplier local
    a.emit(0x50)  # push eax
    a.emit(0x6A, MODIFIER_TYPE_RECHARGE_TIME)  # push 0xc
    a.call_absolute(GET_MODIFIER_MULTIPLIER)  # ret 0x10, and it eats ecx

    a.label("ab_no_object")
    a.emit(0x8B, 0xCB)  # mov ecx, ebx
    a.call_absolute(GET_FINAL_OVERRIDE)
    a.emit(0x8B, 0x50, SPECIAL_POWER_TEMPLATE_FLAGS)  # mov edx, [eax+0x18]
    a.emit(0xC1, 0xEA, RESPECT_RECHARGE_TIME_DISCOUNT_SHIFT)  # shr edx, 5
    a.emit(0xF6, 0xC2, 0x01)  # test dl, 1
    a.jcc(JE, "ab_no_discount")
    a.emit(0x8B, 0x4D, _EBP_PLAYER)  # mov ecx, [ebp-0x20]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "ab_no_discount")
    a.call_absolute(PLAYER_RECHARGE_MODIFIER)  # fld [Player+0x718]
    a.emit(0xD8, 0x05, _u32(FLOAT_ONE))  # fadd dword [1.0f]
    a.emit(0xD9, 0x5C, 0x24, 0x04)  # fstp dword [esp+4]

    a.label("ab_no_discount")
    a.emit(0x8B, 0xCB)  # mov ecx, ebx
    a.call_absolute(GET_FINAL_OVERRIDE)
    a.emit(0x8B, 0x40, SPECIAL_POWER_TEMPLATE_RELOAD_TIME)  # mov eax, [eax+0x20]
    a.emit(0x50)  # push eax
    a.emit(0xDB, 0x04, 0x24)  # fild dword [esp]
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JGE, "ab_reload_positive")
    a.emit(0xD8, 0x05, _u32(FLOAT_U32_FIXUP))  # fadd dword [2^32]   the engine's own fixup

    a.label("ab_reload_positive")
    a.emit(0xD8, 0x4C, 0x24, 0x04)  # fmul dword [esp+4]      the player discount
    a.emit(0xD8, 0x0C, 0x24)  # fmul dword [esp]              the attribute multiplier
    a.call_absolute(FTOL)  # -> eax
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8                    the two locals are done with
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JG, "ab_have_full")
    a.emit(0xB8, _u32(1))  # mov eax, 1                       the engine's >= 1 clamp

    a.label("ab_have_full")
    a.emit(0x8B, 0xF8)  # mov edi, eax                        the full duration, in frames

    # Is it recharging? Everything that cannot be answered here falls back to the full duration.
    a.emit(0x8B, 0x4D, _EBP_OBJECT)  # mov ecx, [ebp-0x1c]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "ab_full")
    a.emit(0x53)  # push ebx                       the raw template, as the button holds it
    a.call_absolute(GET_SPECIAL_POWER_MODULE)  # ret 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "ab_full")
    a.emit(0x8B, 0x10)  # mov edx, [eax]                      the interface vtable
    # Flavour 1, or nothing: see SPECIAL_POWER_INTERFACE_READY_FRAME.
    a.emit(0x81, 0x7A, SPECIAL_POWER_INTERFACE_RECHARGE_SLOT, _u32(SPECIAL_POWER_START_RECHARGE))
    a.jcc(JNE, "ab_full")
    a.emit(0x8B, 0x0D, _u32(THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "ab_full")
    a.emit(0x8B, 0x49, GAME_LOGIC_FRAME)  # mov ecx, [ecx+0x40]
    a.emit(0x8B, 0x40, SPECIAL_POWER_INTERFACE_READY_FRAME)  # mov eax, [eax+8]
    a.emit(0x2B, 0xC1)  # sub eax, ecx
    a.jcc(JLE, "ab_full")  # ready, or a timer this module never started
    a.emit(0xBA, _u32(a.label_va("key_cooldown_remaining")))  # mov edx, <key>
    a.jmp("emit_line")

    a.label("ab_full")
    a.emit(0x8B, 0xC7)  # mov eax, edi
    a.emit(0xBA, _u32(a.label_va("key_cooldown")))  # mov edx, <key>
    a.jmp("emit_line")


def _emit_upgrade(a: Asm) -> None:
    """`esi` = the CommandButton, `ebx` = its UpgradeTemplate."""
    a.label("upgrade")
    a.emit(0x8B, 0x4D, _EBP_PLAYER)  # mov ecx, [ebp-0x20]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "up_out")
    a.emit(0x53)  # push ebx
    a.call_absolute(PLAYER_HAS_UPGRADE_COMPLETE)  # ret 4
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JNE, "up_out")  # already researched: there is nothing left to time
    a.emit(0x8B, 0xCB)  # mov ecx, ebx
    a.emit(0xFF, 0x75, _EBP_OBJECT)  # push dword [ebp-0x1c]
    a.emit(0xFF, 0x75, _EBP_PLAYER)  # push dword [ebp-0x20]
    a.call_absolute(UPGRADE_TEMPLATE_CALC_TIME_TO_BUILD)  # ret 8, -> frames
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JLE, "up_out")
    a.emit(0xBA, _u32(a.label_va("key_research_time")))  # mov edx, <key>
    a.jmp("emit_line")

    a.label("up_out")
    a.emit(0xC3)  # ret


def _emit_unit(a: Asm) -> None:
    """`esi` = the CommandButton, which carries neither a special power nor an upgrade."""
    a.label("unit")
    a.emit(0x8B, 0x46, COMMAND_BUTTON_GUI_COMMAND)  # mov eax, [esi+0x14]
    for command in GUI_COMMANDS_WITHOUT_COST:
        a.emit(0x83, 0xF8, command)  # cmp eax, <command>
        a.jcc(JE, "un_out")
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(COMMAND_BUTTON_GET_THING_TEMPLATE)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "un_out")
    # A hero's time is the ledger's, not this template's - see THING_TEMPLATE_HERO_FLAG.
    a.emit(0xF6, 0x80, _u32(THING_TEMPLATE_HERO_FLAG), THING_TEMPLATE_HERO_FLAG_MASK)
    a.jcc(JNE, "un_out")
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.emit(0x6A, 0xFF)  # push -1                         use the template's own BuildTime
    a.emit(0xFF, 0x75, _EBP_OBJECT)  # push dword [ebp-0x1c]
    a.emit(0xFF, 0x75, _EBP_PLAYER)  # push dword [ebp-0x20]
    a.call_absolute(THING_TEMPLATE_CALC_TIME_TO_BUILD)  # ret 0xc, -> frames
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JLE, "un_out")
    a.emit(0xBA, _u32(a.label_va("key_build_time")))  # mov edx, <key>
    a.jmp("emit_line")

    a.label("un_out")
    a.emit(0xC3)  # ret


def _emit(a: Asm, integer_seconds: bool) -> None:
    """The whole cave: its data, then its two hook thunks, then the arms they reach.

    Data comes first so that the code emitted after it can name a string by its final address -
    `Asm.label_va` can only answer for a label that has already been placed.
    """
    a.label("button_stash")
    a.emit(_u32(0))
    for key, text in KEYS.items():
        a.label(f"key_{key}")
        a.emit(text.encode("ascii") + b"\x00")
    while len(a.buf) % 4:  # keep the code dword-aligned; costs at most three bytes
        a.emit(0x00)

    # Hook 1: the prologue's `mov ecx, [esi+0xc]`, plus a copy of what it loaded. Both replaced
    # instructions are reproduced verbatim; the resume point is the `cmp ecx, edi` that tests it.
    a.label("capture")
    a.emit(DESCRIPTION_BUTTON_CAPTURE_BYTES)
    a.emit(0x89, 0x0D, _u32(a.label_va("button_stash")))  # mov [button_stash], ecx
    a.jmp_absolute(DESCRIPTION_BUTTON_CAPTURE_RESUME)

    # Hook 2: the tail. `pushad` because this is the join of every case and the register state
    # here is whatever the case that ran left behind - the function's own epilogue is still to
    # come, and nothing about it is this patch's to assume.
    a.label("tail")
    a.emit(0x60)  # pushad
    a.call("lines")
    a.emit(0x61)  # popad
    a.emit(DESCRIPTION_TAIL_BYTES)  # the replaced instruction, after popad restores ecx
    a.jmp_absolute(DESCRIPTION_TAIL_RESUME)

    # The dispatcher, in the order the builder itself prefers: a button that carries several of
    # these describes the most specific one. Keying on the fields rather than on the GUI command
    # is what lets the ability arm cover every flavour of special-power button without this patch
    # having to know their enum values.
    a.label("lines")
    a.emit(0x8B, 0x35, _u32(a.label_va("button_stash")))  # mov esi, [button_stash]
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JE, "no_button")
    a.emit(0x8B, 0x5E, COMMAND_BUTTON_SPECIAL_POWER)  # mov ebx, [esi+0x44]
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JNE, "ability")
    a.emit(0x8B, 0x5E, COMMAND_BUTTON_UPGRADE)  # mov ebx, [esi+0x24]
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JNE, "upgrade")
    a.jmp("unit")

    a.label("no_button")
    a.emit(0xC3)  # ret

    _emit_ability(a)
    _emit_upgrade(a)
    _emit_unit(a)
    _emit_line(a, integer_seconds)


class DescriptionTimersPatch(Patch):
    """Append a cooldown, build time or research time to a CommandButton's description."""

    name = "description-timers"
    author = "officialNecro"
    description = (
        "Put a button's timer at the bottom of its description: an ability's cooldown (full when "
        "ready, remaining while recharging), a unit's build time and an upgrade's research time, "
        "each with the modifiers that apply to it right now"
    )

    def __init__(self, integer_seconds: bool = False) -> None:
        self.integer_seconds = integer_seconds

    def apply(self, data: bytearray) -> None:
        self._check_build(data)
        section_va = allocate_section(
            data, SECTION_NAME, lambda base: self._assemble(base).finish(), _CHARACTERISTICS
        )
        for file_off, old, new, note in self._edits(data, section_va):
            apply_byte_patch(data, file_off, old, new, note)

    def _check_build(self, data: bytes | bytearray) -> None:
        """Raise unless every hook site, every callee and the transcribed formula are this build's.

        `apply_byte_patch` catches the two windows, but only after the section has been appended -
        and a file left carrying a cave nothing jumps into is a worse failure than a clean raise.
        It catches none of the rest: nothing about the windows says where `calcTimeToBuild` lives.

        The already-applied case is checked first, because it also fails the window check, and
        "you already applied this" is the useful half of that answer.
        """
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError(f"the file already carries a {SECTION_NAME} section")
        for va, expected in self._windows():
            got = _at(data, va, len(expected))
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - this is not the "
                    "ControlBar description builder this patch was written against"
                )
        for va, expected in {**ANCHORS, **RECHARGE_FORMULA_ANCHORS}.items():
            got = _at(data, va, len(expected))
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the engine "
                    "routine the cave depends on is not this build's"
                )

    @staticmethod
    def _windows() -> list[tuple[int, bytes]]:
        """The engine bytes this patch replaces, as ``(va, original)``."""
        return [
            (DESCRIPTION_BUTTON_CAPTURE, DESCRIPTION_BUTTON_CAPTURE_BYTES),
            (DESCRIPTION_TAIL, DESCRIPTION_TAIL_BYTES),
        ]

    def _assemble(self, base_va: int) -> Asm:
        a = Asm(base_va)
        _emit(a, self.integer_seconds)
        a.finish()  # resolve the internal branches, so `label_va` describes a real layout
        return a

    def _edits(
        self, data: bytes | bytearray, section_va: int
    ) -> list[tuple[int, bytes, bytes, str]]:
        """``(file offset, original bytes, patched bytes, note)`` for every engine byte this patch
        rewrites - one list, so :meth:`apply` writes exactly what :meth:`verify` asserts."""
        assembled = self._assemble(section_va)
        edits = []
        for (va, original), label, note in zip(
            self._windows(),
            ("capture", "tail"),
            ("description: capture the CommandButton", "description: append the timer line"),
            strict=True,
        ):
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            patched = _jmp(va, assembled.label_va(label))
            patched += b"\x90" * (len(original) - len(patched))
            edits.append((off, original, patched, note))
        return edits

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located
        problems: list[str] = []

        expected_cave = self._assemble(section_va).finish()
        got_cave = bytes(data[section_off : section_off + len(expected_cave)])
        if got_cave != expected_cave:
            problems.append(
                f"the {SECTION_NAME} cave is not what this configuration builds "
                f"(integer_seconds={self.integer_seconds})"
            )

        try:
            edits = self._edits(data, section_va)
        except ValueError as exc:
            return [*problems, f"cannot recompute the expected edits (wrong build?): {exc}"]
        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")

        for va, expected in {**ANCHORS, **RECHARGE_FORMULA_ANCHORS}.items():
            got = _at(data, va, len(expected))
            if got != expected:
                problems.append(f"{va:#010x} holds {got.hex()}, expected {expected.hex()}")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> DescriptionTimersPatch | None:
        """Recover the configuration from the image.

        One parameter, and it changes the cave's code rather than a constant in it, so probing
        both and keeping the one that verifies needs no second description of the layout.
        """
        for integer_seconds in (False, True):
            try:
                patch = cls(integer_seconds=integer_seconds)
                problems = patch.verify(data)
            except (ValueError, KeyError, IndexError, TypeError, struct.error):
                continue
            if not problems:
                return patch
        return None

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--integer-seconds",
            action="store_true",
            help=(
                "pass the duration as a whole number of seconds, so each key takes a %%d. The "
                "default passes a double and each key takes a %%.1f, which is the engine's own "
                "CONTROLBAR:UnderConstructionDesc idiom"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> DescriptionTimersPatch:
        return cls(integer_seconds=args.integer_seconds)


def _at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"{va:#010x} is not mapped - not the expected build")
    return bytes(data[off : off + count])


def _jmp(at_va: int, target_va: int) -> bytes:
    return b"\xe9" + struct.pack("<i", target_va - (at_va + 5))
