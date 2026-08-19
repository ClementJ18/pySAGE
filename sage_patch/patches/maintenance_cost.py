"""The maintenance-cost patch: a negative income is a per-tick charge, not a discarded number.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below comes
from :mod:`sage_patch.addresses` and is derived in ``../docs/maintenance-cost.md``.

**No new INI field, and none needed.** `MaxIncome` and `DepositAmount` are parsed by
`INI::parseInt`, which is `INI::getNextToken` plus `INI::scanInt` - an `sscanf("%d")` whose error
message is literally ``"Expected signed integer"``. So ``MaxIncome = -5`` parses on a stock binary
today. What it does not do is charge anybody: the engine throws the number away at run time, in
three different places, and this patch is those three places::

    Behavior = TerrainResourceBehavior ModuleTag_Upkeep
      MaxIncome      = -5           ; gold taken per tick, not paid
      IncomeInterval = 30
    End

    Behavior = AutoDepositUpdate ModuleTag_Upkeep
      DepositAmount  = -5
      DepositTiming  = 30000
    End

**Why a negative cannot simply be deposited.** `Money::deposit` is ``add [this+4], amount`` with
no clamp, and the balance is **unsigned** - `Money::withdraw` compares it with `cmova`. A negative
deposit does not charge a player, it rolls their balance through zero to about four billion gold.
Every charge here therefore goes through `Money::withdraw`, which clamps to what is actually there,
returns what it took, and credits `ScoreKeeper.MoneySpent` rather than `MoneyEarned`.

Inflation
---------
**This patch computes no multiplier of its own.** A charge is whatever the module's own income
arithmetic produced, with the sign kept - so each module's charge is affected by inflation exactly
when that module's *income* is, and never otherwise.

`TerrainResourceBehavior` reads `PlayerTemplate.ResourceModifierValues` in the stock build: the
multiply at `0x00885685` is already there, already gated on `filter.allow(thisObject, player)` at
`0x008855CE`, and a negative reaches it the moment the gate below stops discarding it. So a
resource spot's upkeep falls with its income - ten farms that each earn 60% of their income each
cost 60% of their upkeep - and none of that is code this patch wrote.

`AutoDepositUpdate` reads no such table, in stock or here. Its charge is the flat
`DepositAmount`, matching its flat income, unless
:mod:`~sage_patch.patches.auto_deposit_inflation` is also applied - that patch scales the amount
at `0x0089DCDD`, upstream of anything here, and scales an income and a charge with the same
instruction. Applying it changes what this module *pays* as well as what it takes, which is why it
is a separate patch and not a branch in this one.

The three sites, and the fourth that is a consequence
-----------------------------------------------------
1. **`TerrainResourceBehavior`'s non-positive gate**, `jle 0x0088573C`. This is the whole of why a
   negative does nothing today. The condition wants to be `== 0` rather than `<= 0`, which is one
   byte in place - `0F 8E` -> `0F 84` - keeping the length, the target and the zero case exactly
   as they were.

2. **Its floor at one gold**, `test ebx, ebx / jg / xor ebx, ebx / inc ebx`, applied *after* the
   inflation multiply. In the stock build this only ever raises an exact zero, because the gate
   has already established the value was positive. Left alone it would turn a charge into a
   **payment of one gold**, so the cave mirrors it: a charge floors at -1 the way an income floors
   at 1. Which of the two applies is read from the **float** the amount was rounded from, still in
   `[ebp-0x20]`, and not from `ebx` - a multiplier of zero rounds a charge to an integer zero and
   erases its sign, where the float keeps it, `-5.0f * 0.0f` being `-0.0f`.

3. **The deposit**, hooked at the `lea ecx, [player+0x90]` *before* the call rather than at the
   call - which leaves `AUTO_DEPOSIT_DEPOSIT` free for `second-resource`, whose cave owns it. A
   positive amount rejoins the stock path and nothing downstream can tell; a negative is negated
   into `Money::withdraw`, draws the engine's own red `GUI:LoseCash` text, and rejoins past the
   green `GUI:AddCash` block that would otherwise render a minus sign after a plus.

4. **The experience grant**, which is a consequence rather than a goal. Both modules hand the
   amount to `ExperienceTracker::addExperiencePoints`, so a charge would drain a building's
   veterancy - a second mechanic nobody asked for, down a path no sane stock data reaches. A
   charge tick therefore grants **zero** experience, which is precisely the stock "no income this
   tick" case: `TerrainResourceBehavior`'s cave zeroes the amount before rejoining the block, and
   `AutoDepositUpdate`'s stock `GiveNoXP` test gains a second reason to skip.

What this does not do
---------------------
* **It does not make a charge affordable.** `Money::withdraw` clamps, so a player with 3 gold and
  a 5 gold charge pays 3 and the floating text says 3. Nothing is destroyed, nothing goes into
  debt and nothing is disabled for want of upkeep - if a mod wants a building to shut down when
  its owner cannot pay, that is a different mechanic on a different module.
* **It does not touch a positive amount anywhere.** Every edit is behind a sign test, and the two
  in-place condition changes preserve the stock outcome for every value the stock build could
  produce. A mod that declares no negative income is byte-for-byte unaffected at run time.
* **It adds no INI keyword**, so - unlike `terrain-resource-exp` - a mod written for this patch
  still **loads** on an unpatched binary. It silently does not charge there, which is the failure
  worth knowing about: the number parses either way, and only the patched build acts on it.

**Determinism.** Money is logic-side `Player` state and the engine CRCs it, so **every peer must
run the same patched binary**. Same rule as `command-point-upkeep`, and stricter than the
client-local `inflation-readout`.

**Composition.** Order-independent, and it shares no byte with any bundled patch.
`terrain-resource-exp` hooks `0x0088573C`, which this patch *jumps to* rather than rewrites, so
the two compose - and its `GiveNoXP` still governs the income ticks, which are the only ticks left
that grant experience. `second-resource` hooks the `AutoDepositUpdate` deposit call this patch
stops one instruction short of; a charge never reaches it, which is the right answer for a pool a
charge does not credit. `command-point-upkeep` scales `TerrainResourceBehavior`'s multiplier slot
and is therefore applied to a charge as well, by the stock arithmetic rather than by anything
here. `auto-deposit-inflation` hooks `0x0089DCDD`, three instructions above this patch's own
`AutoDepositUpdate` hook, and the two are related only through the number that flows between them.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from ..addresses import (
    AUTO_DEPOSIT_AMOUNT,
    AUTO_DEPOSIT_DEPOSIT_RESUME,
    AUTO_DEPOSIT_GIVE_NO_XP,
    AUTO_DEPOSIT_OBJECT_ESI,
    AUTO_DEPOSIT_PAY,
    AUTO_DEPOSIT_PAY_BYTES,
    AUTO_DEPOSIT_PAY_RESUME,
    AUTO_DEPOSIT_XP_GATE,
    AUTO_DEPOSIT_XP_GATE_BYTES,
    AUTO_DEPOSIT_XP_GATE_RESUME,
    AUTO_DEPOSIT_XP_GATE_SKIP,
    GAME_TEXT_FORMAT_SLOT,
    GUI_LOSE_CASH,
    IN_GAME_UI_ADD_FLOATING_TEXT,
    LOSE_CASH_COLOR,
    LOSE_CASH_RISE,
    MONEY_WITHDRAW,
    OBJECT_POSITION,
    PLAYER_MONEY,
    TERRAIN_RESOURCE_EXP_BLOCK,
    TERRAIN_RESOURCE_FLOOR,
    TERRAIN_RESOURCE_FLOOR_BYTES,
    TERRAIN_RESOURCE_FLOOR_RESUME,
    TERRAIN_RESOURCE_INCOME_FLOAT_EBP,
    TERRAIN_RESOURCE_INCOME_GATE,
    TERRAIN_RESOURCE_INCOME_GATE_BYTES,
    TERRAIN_RESOURCE_PAY,
    TERRAIN_RESOURCE_PAY_BYTES,
    TERRAIN_RESOURCE_PAY_RESUME,
    THE_GAME_TEXT,
    THE_IN_GAME_UI,
    UNICODE_STRING_CONCAT,
    UNICODE_STRING_DTOR,
)
from ..asm import JE, JG, JL, JLE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["SECTION_NAME", "MaintenanceCostPatch", "charge"]

#: 8 chars max: the PE name field truncates silently past 8.
SECTION_NAME = ".upkeep2"

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ. The cave is code and nothing in it is
# written at run time, so no MEM_WRITE.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000

# `jl` on flags set by `test reg, reg` is `js`: the test clears OF, so "SF != OF" is "SF". Written
# as the signed comparison it is, because that is what the sign of an income means here.
_JS = JL


def charge(amount: int, multiplier: float, floor: bool) -> int:
    """What a negative ``amount`` actually takes, before the purse is consulted - the rule the
    emitted code implements, in Python, so the tests can state it once and assert the bytes
    against the same one.

    ``multiplier`` is whatever scaled the amount **upstream of this patch** - the owner's
    inflation factor for `TerrainResourceBehavior`, where the engine applies it; `1.0` for
    `AutoDepositUpdate` unless `auto-deposit-inflation` is installed, and its factor when it is.
    ``floor`` is `TerrainResourceBehavior`'s never-round-below-one rule, mirrored: it has one and
    `AutoDepositUpdate` does not.

    Rounding is **toward zero** in both modules - `ceil` on the one that already rounds with it,
    `cvttss2si` on the one that already truncates - so a fractional charge is rounded down in
    magnitude, the same direction the engine rounds an income up in.
    """
    if amount >= 0:
        raise ValueError(f"only a negative amount is a charge, got {amount}")
    scaled = int(amount * multiplier)  # C truncation: toward zero for a negative
    if floor:
        scaled = min(scaled, -1)
    return -scaled


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _i8(value: int) -> int:
    """A signed byte displacement as the unsigned byte that encodes it."""
    return value & 0xFF


# Everything below is hand-encoded (the house style: only address arithmetic is automated, by
# `..asm`), with a comment saying what each instruction is.

# `lose_text`'s frame. The `Coord3D` is three consecutive floats with `x` lowest, because
# `addFloatingText` takes its address; the `UnicodeString` is one pointer and has to start empty,
# since `UNICODE_STRING_CONCAT` releases whatever the destination already holds.
_TEXT_STRING_EBP = -0x04
_TEXT_Z_EBP = -0x08
_TEXT_Y_EBP = -0x0C
_TEXT_X_EBP = -0x10
_TEXT_FRAME = 0x10
_TEXT_OBJECT_ARG = 0x08
_TEXT_AMOUNT_ARG = 0x0C


def _emit_lose_text(a: Asm) -> None:
    """``lose_text(Object* obj, Int amount)`` - cdecl, caller-cleaned.

    The engine's own "you lost gold" floating text, copied from the money-transfer site at
    `0x008C6980`: `GUI:LoseCash` formatted with the amount, drawn in red above the object. The
    green `GUI:AddCash` half of that same site is what both income modules already draw, so a
    charge and an income look like two halves of one thing because they are.
    """
    a.label("lose_text")
    a.emit(0x55)  # push ebp
    a.emit(0x89, 0xE5)  # mov ebp, esp
    a.emit(0x83, 0xEC, _TEXT_FRAME)  # sub esp, 0x10
    a.emit(0x56)  # push esi
    a.emit(0x83, 0x65, _i8(_TEXT_STRING_EBP), 0x00)  # and dword [ebp-4], 0   ; an empty string
    a.emit(0x8B, 0x75, _TEXT_OBJECT_ARG)  # mov esi, [ebp+8]       ; the Object

    # `TheGameText->fetch(key, 0)`, then `format(&str, fetched, amount)` - the engine's idiom,
    # with the vararg pushed before the fetch exactly as the twelve stock sites push it.
    a.emit(0x8B, 0x0D, _u32(THE_GAME_TEXT))  # mov ecx, [TheGameText]
    a.emit(0x8B, 0x11)  # mov edx, [ecx]         ; its vtable
    a.emit(0xFF, 0x75, _TEXT_AMOUNT_ARG)  # push [ebp+0xc]         ; the amount
    a.emit(0x6A, 0x00)  # push 0
    a.emit(0x68, _u32(GUI_LOSE_CASH))  # push "GUI:LoseCash"
    a.emit(0xFF, 0x52, GAME_TEXT_FORMAT_SLOT)  # call [edx+0x44]        ; ret 8
    a.emit(0x50)  # push eax               ; the fetched format
    a.emit(0x8D, 0x45, _i8(_TEXT_STRING_EBP))  # lea eax, [ebp-4]
    a.emit(0x50)  # push eax
    a.call_absolute(UNICODE_STRING_CONCAT)  # cdecl (dest, fmt, amount)
    a.emit(0x83, 0xC4, 0x0C)  # add esp, 0xc

    # The position, lifted the way the stock `LoseCash` site lifts it - a constant rather than the
    # geometry query the `AddCash` site makes, because that is what the site being copied does.
    a.emit(0xF3, 0x0F, 0x10, 0x46, OBJECT_POSITION)  # movss xmm0, [esi+0x38]
    a.emit(0xF3, 0x0F, 0x11, 0x45, _i8(_TEXT_X_EBP))  # movss [ebp-0x10], xmm0
    a.emit(0xF3, 0x0F, 0x10, 0x46, OBJECT_POSITION + 4)  # movss xmm0, [esi+0x3c]
    a.emit(0xF3, 0x0F, 0x11, 0x45, _i8(_TEXT_Y_EBP))  # movss [ebp-0xc], xmm0
    a.emit(0xF3, 0x0F, 0x10, 0x46, OBJECT_POSITION + 8)  # movss xmm0, [esi+0x40]
    a.emit(0xF3, 0x0F, 0x58, 0x05, _u32(LOSE_CASH_RISE))  # addss xmm0, [30.0f]
    a.emit(0xF3, 0x0F, 0x11, 0x45, _i8(_TEXT_Z_EBP))  # movss [ebp-8], xmm0

    a.emit(0x8B, 0x0D, _u32(THE_IN_GAME_UI))  # mov ecx, [TheInGameUI]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0x68, _u32(LOSE_CASH_COLOR))  # push 0xffff0000        ; red, ARGB
    a.emit(0x8D, 0x55, _i8(_TEXT_X_EBP))  # lea edx, [ebp-0x10]
    a.emit(0x52)  # push edx               ; &the Coord3D
    a.emit(0x8D, 0x55, _i8(_TEXT_STRING_EBP))  # lea edx, [ebp-4]
    a.emit(0x52)  # push edx               ; &the UnicodeString
    a.emit(0xFF, 0x90, _u32(IN_GAME_UI_ADD_FLOATING_TEXT))  # call [eax+0x1a0]  ; ret 0xc

    a.emit(0x8D, 0x4D, _i8(_TEXT_STRING_EBP))  # lea ecx, [ebp-4]
    a.call_absolute(UNICODE_STRING_DTOR)  # the string owns a real allocation
    a.emit(0x5E)  # pop esi
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret


def _emit_terrain_floor(a: Asm) -> None:
    """Entered in place of `TerrainResourceBehavior`'s floor at one gold, with `ebx` holding the
    post-inflation amount and `ebp` still the function's own frame.

    Which floor applies is decided by the **float** the amount was rounded from, still sitting in
    `[ebp-0x20]`, rather than by `ebx`: an inflation multiplier of zero rounds a charge to an
    integer zero and erases its sign, while the float keeps it - IEEE gives `-5.0f * 0.0f` the
    value `-0.0f`, whose sign bit is set, and `test` on the raw bits reads exactly that bit.

    The positive branch is the stock instruction sequence, condition included.
    """
    a.label("trb_floor")
    a.emit(0x8B, 0x45, _i8(TERRAIN_RESOURCE_INCOME_FLOAT_EBP))  # mov eax, [ebp-0x20]
    a.emit(0x85, 0xC0)  # test eax, eax          ; the float's sign bit
    a.jcc(_JS, "tf_charge")
    a.emit(0x85, 0xDB)  # test ebx, ebx          ; the stock floor, verbatim
    a.jcc(JG, "tf_out")
    a.emit(0xBB, _u32(1))  # mov ebx, 1
    a.jmp("tf_out")

    a.label("tf_charge")
    a.emit(0x83, 0xFB, 0xFF)  # cmp ebx, -1
    a.jcc(JLE, "tf_out")  # already at or past the floor
    a.emit(0xBB, _u32(0xFFFFFFFF))  # mov ebx, -1            ; a charge floors at -1

    a.label("tf_out")
    a.jmp_absolute(TERRAIN_RESOURCE_FLOOR_RESUME)


def _emit_terrain_pay(a: Asm) -> None:
    """Entered in place of the `lea ecx, [esi+0x90]` before `TerrainResourceBehavior`'s deposit.

    `esi` is the controlling `Player`, `edi` the depositing `Object`, `ebx` the signed amount, and
    the three deposit arguments are already pushed with the amount at `[esp]` - so the charge path
    negates that slot in place and lets `Money::withdraw`, which takes the same three arguments
    and cleans them itself, consume the stock call's own stack.

    It rejoins at the experience block rather than at the deposit's fall-through, which skips the
    green `GUI:AddCash` text, and it zeroes `ebx` first - that block's only use of the register -
    so a charge tick grants zero experience rather than negative experience.
    """
    a.label("trb_pay")
    a.emit(0x8D, 0x8E, _u32(PLAYER_MONEY))  # lea ecx, [esi+0x90]   ; the displaced instruction
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(_JS, "tp_charge")
    a.jmp_absolute(TERRAIN_RESOURCE_PAY_RESUME)  # the stock deposit and its "+N" text

    a.label("tp_charge")
    a.emit(0xF7, 0x1C, 0x24)  # neg dword [esp]       ; the magnitude
    a.call_absolute(MONEY_WITHDRAW)  # ret 0xc -> eax = what it took
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "tp_silent")  # took nothing: say nothing
    a.emit(0x50)  # push eax
    a.emit(0x57)  # push edi              ; the Object
    a.call("lose_text")
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8

    a.label("tp_silent")
    a.emit(0x33, 0xDB)  # xor ebx, ebx          ; no experience for a charge tick
    a.jmp_absolute(TERRAIN_RESOURCE_EXP_BLOCK)


def _emit_auto_deposit_pay(a: Asm) -> None:
    """Entered in place of the `lea ecx, [edi+0x90]` before `AutoDepositUpdate`'s deposit.

    `edi` is the controlling `Player`, `[esi-8]` the depositing `Object`, `eax` and `[esp]` the
    signed amount. A positive one rejoins **above** the `call`, so `second-resource`'s hook on it
    still runs; a negative never reaches the call at all.

    **No arithmetic of its own.** Whatever the amount arrived as is what is charged - which is why
    this module's charge is affected by inflation exactly when
    :mod:`~sage_patch.patches.auto_deposit_inflation` is also applied and not otherwise. That
    patch scales the amount at `0x0089DCDD`, upstream of here, and scales an income and a charge
    with the same instruction.
    """
    a.label("adu_pay")
    a.emit(0x8D, 0x8F, _u32(PLAYER_MONEY))  # lea ecx, [edi+0x90]  ; the displaced instruction
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(_JS, "ap_charge")
    a.jmp_absolute(AUTO_DEPOSIT_PAY_RESUME)

    a.label("ap_charge")
    a.emit(0xF7, 0x1C, 0x24)  # neg dword [esp]      ; the magnitude
    a.call_absolute(MONEY_WITHDRAW)  # ret 0xc -> eax = what it took
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "ap_silent")  # took nothing: say nothing
    a.emit(0x50)  # push eax
    a.emit(0xFF, 0x76, _i8(AUTO_DEPOSIT_OBJECT_ESI))  # push [esi-8]         ; the Object
    a.call("lose_text")
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8

    a.label("ap_silent")
    a.jmp_absolute(AUTO_DEPOSIT_DEPOSIT_RESUME)  # past the deposit call, not through it


def _emit_auto_deposit_xp(a: Asm) -> None:
    """Entered in place of `AutoDepositUpdate`'s stock `GiveNoXP` test, with `eax` already holding
    the `ModuleData`.

    Reproduces that test and adds the second reason to skip it - a negative `DepositAmount`, which
    would otherwise hand `addExperiencePoints` the negation of the grant. The stock field keeps
    doing exactly what it does; this only takes a path away from data that could not previously
    reach it usefully.
    """
    a.label("adu_xp")
    a.emit(0x80, 0x78, AUTO_DEPOSIT_GIVE_NO_XP, 0x00)  # cmp byte [eax+0x20], 0  ; GiveNoXP
    a.jcc(JNE, "ax_skip")
    a.emit(0x83, 0x78, AUTO_DEPOSIT_AMOUNT, 0x00)  # cmp dword [eax+0xc], 0  ; DepositAmount
    a.jcc(JL, "ax_skip")
    a.jmp_absolute(AUTO_DEPOSIT_XP_GATE_RESUME)

    a.label("ax_skip")
    a.jmp_absolute(AUTO_DEPOSIT_XP_GATE_SKIP)


def _assemble(base_va: int) -> Asm:
    """The whole cave: the two shared routines, then the four entry points."""
    a = Asm(base_va)
    _emit_lose_text(a)
    _emit_terrain_floor(a)
    _emit_terrain_pay(a)
    _emit_auto_deposit_pay(a)
    _emit_auto_deposit_xp(a)
    a.finish()  # resolve the internal branches, so `label_va` describes a real layout
    return a


def _jmp(at_va: int, target_va: int) -> bytes:
    return b"\xe9" + struct.pack("<i", target_va - (at_va + 5))


def _detour(at_va: int, target_va: int, window: bytes) -> bytes:
    """A `jmp rel32` to the cave, padded with `nop` to the length of what it displaces."""
    return _jmp(at_va, target_va) + b"\x90" * (len(window) - 5)


class MaintenanceCostPatch(Patch):
    """Let `TerrainResourceBehavior` and `AutoDepositUpdate` take gold as well as pay it, by
    honouring a negative `MaxIncome` / `DepositAmount` as a per-tick maintenance charge."""

    name = "maintenance-cost"
    author = "officialNecro"
    description = (
        "Make a negative MaxIncome (TerrainResourceBehavior) or DepositAmount "
        "(AutoDepositUpdate) charge the owning player that much gold per tick instead of being "
        "discarded, clamped to what the player has and drawn as the engine's own red GUI:LoseCash "
        "text. A charge inherits whatever scales its module's income, so a TerrainResourceBehavior "
        "one falls with the faction's ResourceModifierValues and an AutoDepositUpdate one is flat "
        "unless auto-deposit-inflation is also applied. No new INI keyword, so a mod using it "
        "still loads on an unpatched binary - and silently does not charge there"
    )

    def apply(self, data: bytearray) -> None:
        self._check_build(data)
        section_va = allocate_section(
            data, SECTION_NAME, lambda base: _assemble(base).finish(), _CHARACTERISTICS
        )
        for file_off, old, new, note in self._edits(data, section_va):
            apply_byte_patch(data, file_off, old, new, note)

    @staticmethod
    def _windows() -> tuple[tuple[int, bytes, str], ...]:
        """``(VA, the stock bytes, what it is)`` for every engine site this patch rewrites."""
        return (
            (
                TERRAIN_RESOURCE_INCOME_GATE,
                TERRAIN_RESOURCE_INCOME_GATE_BYTES,
                "TerrainResourceBehavior's non-positive income gate",
            ),
            (
                TERRAIN_RESOURCE_FLOOR,
                TERRAIN_RESOURCE_FLOOR_BYTES,
                "TerrainResourceBehavior's floor at one gold",
            ),
            (
                TERRAIN_RESOURCE_PAY,
                TERRAIN_RESOURCE_PAY_BYTES,
                "TerrainResourceBehavior's money pointer",
            ),
            (AUTO_DEPOSIT_PAY, AUTO_DEPOSIT_PAY_BYTES, "AutoDepositUpdate's money pointer"),
            (AUTO_DEPOSIT_XP_GATE, AUTO_DEPOSIT_XP_GATE_BYTES, "AutoDepositUpdate's GiveNoXP gate"),
        )

    def _check_build(self, data: bytes | bytearray) -> None:
        """Raise unless every site is still the stock window these bytes came from.

        `apply_byte_patch` would catch this too, but only after the section had been appended -
        and a file left carrying a cave nothing jumps into is a worse failure than a clean raise.
        The already-applied case is checked first, because it also fails the window check and
        "you already applied this" is the useful half of that answer.
        """
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError(f"the file already carries a {SECTION_NAME} section")
        for va, stock, what in self._windows():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"0x{va:08x} is not mapped - not the expected build")
            got = bytes(data[off : off + len(stock)])
            if got != stock:
                raise ValueError(
                    f"unexpected build: {what} at 0x{va:08x} is {got.hex()}, expected {stock.hex()}"
                )

    def _edits(
        self, data: bytes | bytearray, section_va: int
    ) -> list[tuple[int, bytes, bytes, str]]:
        """``(file offset, original bytes, patched bytes, note)`` for every engine byte this patch
        rewrites - one list, so :meth:`apply` writes exactly what :meth:`verify` asserts."""
        code = _assemble(section_va)
        return list(self._describe(data, code))

    def _describe(
        self, data: bytes | bytearray, code: Asm
    ) -> Iterator[tuple[int, bytes, bytes, str]]:
        replacements = {
            # The one edit with no cave: `jle` -> `je`, same length and same target, so the
            # non-positive gate becomes the zero gate it wants to be.
            TERRAIN_RESOURCE_INCOME_GATE: (
                b"\x0f\x84" + TERRAIN_RESOURCE_INCOME_GATE_BYTES[2:],
                "the income gate rejects only an exact zero",
            ),
            TERRAIN_RESOURCE_FLOOR: (
                _detour(
                    TERRAIN_RESOURCE_FLOOR,
                    code.label_va("trb_floor"),
                    TERRAIN_RESOURCE_FLOOR_BYTES,
                ),
                "the floor at one gold -> the sign-preserving floor",
            ),
            TERRAIN_RESOURCE_PAY: (
                _detour(TERRAIN_RESOURCE_PAY, code.label_va("trb_pay"), TERRAIN_RESOURCE_PAY_BYTES),
                "TerrainResourceBehavior's deposit -> deposit or charge",
            ),
            AUTO_DEPOSIT_PAY: (
                _detour(AUTO_DEPOSIT_PAY, code.label_va("adu_pay"), AUTO_DEPOSIT_PAY_BYTES),
                "AutoDepositUpdate's deposit -> deposit or charge",
            ),
            AUTO_DEPOSIT_XP_GATE: (
                _detour(AUTO_DEPOSIT_XP_GATE, code.label_va("adu_xp"), AUTO_DEPOSIT_XP_GATE_BYTES),
                "the GiveNoXP gate also skips a charge tick",
            ),
        }
        for va, stock, _what in self._windows():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"0x{va:08x} is not mapped - not the expected build")
            new, note = replacements[va]
            assert len(new) == len(stock), f"the replacement at 0x{va:08x} changes length"
            yield off, stock, new, note

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, vsize = located

        problems: list[str] = []
        want = _assemble(section_va).finish()
        if len(want) > vsize:
            problems.append(
                f"{SECTION_NAME} holds {vsize} bytes, too few for the {len(want)} the cave takes"
            )
        elif bytes(data[section_off : section_off + len(want)]) != want:
            problems.append(f"the cave at 0x{section_va:08x} is not the one this patch builds")

        try:
            edits = self._edits(data, section_va)
        except ValueError as exc:
            return [*problems, f"cannot recompute the expected edits (wrong build?): {exc}"]
        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")
        return problems
