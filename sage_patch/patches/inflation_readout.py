"""The inflation-readout patch: draw the local player's income multiplier in the palantir.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below comes
from :mod:`sage_patch.addresses` and is derived in ``../docs/inflation-readout.md``.

**Why this is one detour.** The palantir's resource-multiplier slot is not a thing this patch
adds. It already exists, is already refreshed every frame, and in a skirmish is already **blank**:
the refresh at `0x006D577C` feeds the text builder the War-of-the-Ring region bonus, or - with no
region, which is every skirmish - exactly `1.0f`, and the builder blanks itself at exactly `1.0f`.
So a readout is a matter of feeding that fallback a different float::

    006d59b7  movss xmm0, [0xbd1908]   ; 1.0f      <- replaced by  jmp <cave>
    006d59bf  jmp  0x6d5a69            ; the resume point

Everything downstream is untouched: the `ucomiss` change filter against the cached float, the
`L"x%g"` formatting, the blank-at-1.0 rule. **No new format string, no `.apt` edit, no `.csf`
edit, no INI field**, and nothing this patch reads or writes enters the simulation.

**The arithmetic is the engine's own.** `_emit_multiplier` reproduces `0x008855F7`-`0x0088564B`
instruction for instruction and calls the engine's own counting callback through
`Player::forEachTeamObject`, so the number drawn is the number `AutoDepositUpdate` computes - the
past-end extension, its `0.02f` slope and its floor at zero all included - rather than a
re-derivation that can drift from it.

One deliberate divergence: the engine reads `values[n-1]` on the past-end path **without checking
that the vector is non-empty**, which a faction setting `ResourceModifierObjectFilter` and no
`ResourceModifierValues` reaches. That is a stray read of one dword in the deposit path; in a
per-frame HUD read it is not worth reproducing, so an empty vector takes the `1.0f` path here and
draws a blank slot.

**The blank at no penalty is exact, not lucky.** `0.01f` is `0.00999999977648…`, and
`100.0f * 0.01f` rounds to `1.0f` (the product is `2.2e-8` from `1.0` and `3.7e-8` from the float
below it), so a faction whose table entry is `100` - which is every faction, for its first few
buildings - draws exactly what the stock engine draws.

**Combining with `command-point-upkeep`.** Both patches scale the same income, and the deposit
multiplies their factors, so the readout does too: `-15%` inflation with `-10%` upkeep draws
``x0.765``. The link is a null function pointer either patch can fill, described in
:mod:`~sage_patch.patches.income_link`; the pair stays order-independent because neither patch's
*code* depends on the other, only four bytes of data.

> **Client-local and read-only.** No simulation state is read or written, so - unlike
> `command-point-upkeep`, whose mechanic is inside the simulation - a patched and an unpatched
> client can play each other and replays cross. Same rule as `replay-outcome`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    FLOAT_ONE,
    FLOAT_ONE_PERCENT,
    FLOAT_TWO_PERCENT,
    OBJECT_FILTER_IS_VALID,
    PALANTIR_RESOURCE_MULTIPLIER,
    PALANTIR_RESOURCE_MULTIPLIER_BYTES,
    PALANTIR_RESOURCE_MULTIPLIER_RESUME,
    PLAYER_FOR_EACH_TEAM_OBJECT,
    PLAYER_LIST_GET_LOCAL_PLAYER,
    PLAYER_PLAYER_TEMPLATE,
    PLAYER_TEMPLATE_RESOURCE_FILTER,
    PLAYER_TEMPLATE_RESOURCE_VALUES,
    RESOURCE_MODIFIER_COUNT_CALLBACK,
    THE_PLAYER_LIST,
)
from ..asm import JBE, JE, JGE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset
from .income_link import READOUT_IMPORT_OFF, READOUT_SECTION, UPKEEP_SECTION, read_export

__all__ = [
    "CODE_OFF",
    "MAX_PERCENT",
    "SECTION_NAME",
    "InflationReadoutPatch",
    "multiplier",
]

#: 8 chars max: the PE name field truncates silently past 8.
SECTION_NAME = READOUT_SECTION

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ. The cave holds code and the import
# slot, both written at patch time - nothing in it is written at runtime, so no MEM_WRITE.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000

#: Where the code starts. Everything below it is the import slot plus padding to a tidy boundary.
CODE_OFF = 0x10

#: The percentage `command-point-upkeep`'s `percent` returns when it is taking nothing, and the
#: value this patch assumes when there is no upkeep to ask.
MAX_PERCENT = 100

# The cave's stack frame. `percent` clobbers `eax`/`ecx`/flags and the three engine calls are
# MSVC thiscall, so the player and the upkeep factor live in slots rather than in registers -
# the cave then depends on no callee-save convention of its own.
_PLAYER_EBP = -0x04
_KEPT_EBP = -0x08
#: `{ ObjectFilter* filter; Int count; }`, the shape `RESOURCE_MODIFIER_COUNT_CALLBACK` expects.
#: The filter is at the **lower** address, so the context base is the count's slot minus four.
_CTX_COUNT_EBP = -0x0C
_CTX_EBP = -0x10
_FRAME = 0x10


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _i8(value: int) -> int:
    """A signed byte displacement as the unsigned byte that encodes it."""
    return value & 0xFF


def multiplier(count: int, values: tuple[int, ...], kept: int = MAX_PERCENT) -> float:
    """What the palantir shows - the cave's arithmetic, in Python.

    The single source of truth for what the readout *means*, so the tests can state the rule once
    and assert the emitted code against the same one. ``count`` is how many of the player's
    objects the faction's `ResourceModifierObjectFilter` accepts and ``kept`` is
    `command-point-upkeep`'s percentage, `100` when that patch is absent.

    Computed in single precision throughout, because whether the result is exactly `1.0` decides
    whether the engine draws a number at all.
    """
    one_percent = struct.unpack("<f", struct.pack("<f", 0.01))[0]
    two_percent = struct.unpack("<f", struct.pack("<f", 0.02))[0]

    def f32(value: float) -> float:
        return struct.unpack("<f", struct.pack("<f", value))[0]  # type: ignore[no-any-return]

    n = len(values)
    if n == 0:
        result = 1.0
    elif count < n:
        result = f32(values[count] * one_percent)
    else:
        result = f32(f32(values[-1] * one_percent) - f32((count - n) * two_percent))
        result = max(result, 0.0)
    if kept != MAX_PERCENT:
        result = f32(result * f32(kept * one_percent))
    return result


# Everything below is hand-encoded (the house style: only address arithmetic is automated, by
# `..asm`), with a comment saying what each instruction is.


def _emit_multiplier(a: Asm, import_va: int) -> None:
    """The whole patch: `xmm0` = the local player's income multiplier, then back to the refresh.

    Entered by the detour that replaced the stock `movss xmm0, [1.0f]`, and leaves by the `jmp`
    that constant load was followed by - so to everything downstream this is still just "the
    multiplier arrived in `xmm0`".

    `1.0f` on every degenerate path: no player list, no local player, no template, no filter, an
    empty value table. The engine draws a blank slot for `1.0f`, which is exactly right - all of
    those mean "no modifier", and all of them are what an unpatched build shows.
    """
    a.label("mult")
    a.emit(0x55)  # push ebp
    a.emit(0x89, 0xE5)  # mov ebp, esp
    a.emit(0x83, 0xEC, _FRAME)  # sub esp, 0x10
    a.emit(0xF3, 0x0F, 0x10, 0x05, _u32(FLOAT_ONE))  # movss xmm0, [1.0f]
    a.emit(0xC7, 0x45, _i8(_KEPT_EBP), _u32(MAX_PERCENT))  # mov [ebp-8], 100

    # The local player, through the same call the palantir's own refresh reaches it by.
    a.emit(0x8B, 0x0D, _u32(THE_PLAYER_LIST))  # mov ecx, [ThePlayerList]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "mu_done")
    a.call_absolute(PLAYER_LIST_GET_LOCAL_PLAYER)  # thiscall, no arguments
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "mu_done")
    a.emit(0x89, 0x45, _i8(_PLAYER_EBP))  # mov [ebp-4], eax

    # `command-point-upkeep`'s factor, if this file carries it. The slot is zero otherwise, which
    # is the whole of "the two patches compose" - see `income_link`.
    a.emit(0xA1, _u32(import_va))  # mov eax, [g_upkeep_percent]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "mu_inflation")
    a.emit(0x8B, 0x4D, _i8(_PLAYER_EBP))  # mov ecx, [ebp-4]        ; thiscall-shaped
    a.emit(0xFF, 0xD0)  # call eax                ; -> eax = percent kept
    a.emit(0x89, 0x45, _i8(_KEPT_EBP))  # mov [ebp-8], eax

    # The count, exactly as `AutoDepositUpdate` takes it. The engine gates this on
    # `filter.allow(thisObject, player)` first, because it is asking "is the building I am
    # depositing for a taxed one"; a per-player readout has no such building and skips it.
    a.label("mu_inflation")
    a.emit(0x8B, 0x45, _i8(_PLAYER_EBP))  # mov eax, [ebp-4]
    a.emit(0x8B, 0x40, PLAYER_PLAYER_TEMPLATE)  # mov eax, [eax+0x34]     ; the PlayerTemplate
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "mu_fold")
    a.emit(0x05, _u32(PLAYER_TEMPLATE_RESOURCE_FILTER))  # add eax, 0x1c8
    a.emit(0x89, 0x45, _i8(_CTX_EBP))  # mov [ebp-0x10], eax     ; ctx.filter
    a.emit(0x83, 0x65, _i8(_CTX_COUNT_EBP), 0x00)  # and dword ptr [ebp-0xc], 0 ; ctx.count
    a.emit(0x8B, 0x4D, _i8(_CTX_EBP))  # mov ecx, [ebp-0x10]
    a.call_absolute(OBJECT_FILTER_IS_VALID)  # thiscall, no arguments
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "mu_fold")  # no filter -> no inflation, as in the engine
    a.emit(0x8D, 0x45, _i8(_CTX_EBP))  # lea eax, [ebp-0x10]
    a.emit(0x50)  # push eax                ; the context
    a.emit(0x68, _u32(RESOURCE_MODIFIER_COUNT_CALLBACK))  # push the engine's own counter
    a.emit(0x8B, 0x4D, _i8(_PLAYER_EBP))  # mov ecx, [ebp-4]
    a.call_absolute(PLAYER_FOR_EACH_TEAM_OBJECT)  # ret 8

    # `0x008855F7`-`0x0088564B`, instruction for instruction.
    a.emit(0x8B, 0x45, _i8(_PLAYER_EBP))  # mov eax, [ebp-4]
    a.emit(0x8B, 0x40, PLAYER_PLAYER_TEMPLATE)  # mov eax, [eax+0x34]
    a.emit(0x05, _u32(PLAYER_TEMPLATE_RESOURCE_VALUES))  # add eax, 0x1cc
    a.emit(0x8B, 0x08)  # mov ecx, [eax]          ; values.begin
    a.emit(0x8B, 0x40, 0x04)  # mov eax, [eax+4]        ; values.end
    a.emit(0x29, 0xC8)  # sub eax, ecx
    a.emit(0xC1, 0xF8, 0x02)  # sar eax, 2              ; n
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "mu_fold")  # an empty table: see the module docstring
    a.emit(0x8B, 0x55, _i8(_CTX_COUNT_EBP))  # mov edx, [ebp-0xc]      ; count
    a.emit(0x39, 0xC2)  # cmp edx, eax
    a.jcc(JGE, "mu_past_end")
    a.emit(0xF3, 0x0F, 0x2A, 0x04, 0x91)  # cvtsi2ss xmm0, dword ptr [ecx+edx*4]
    a.emit(0xF3, 0x0F, 0x59, 0x05, _u32(FLOAT_ONE_PERCENT))  # mulss xmm0, [0.01f]
    a.jmp("mu_fold")

    a.label("mu_past_end")  # values[n-1]*0.01 - (count-n)*0.02, floored at zero
    a.emit(0xF3, 0x0F, 0x2A, 0x44, 0x81, 0xFC)  # cvtsi2ss xmm0, dword ptr [ecx+eax*4-4]
    a.emit(0xF3, 0x0F, 0x59, 0x05, _u32(FLOAT_ONE_PERCENT))  # mulss xmm0, [0.01f]
    a.emit(0x29, 0xC2)  # sub edx, eax
    a.emit(0xF3, 0x0F, 0x2A, 0xCA)  # cvtsi2ss xmm1, edx
    a.emit(0xF3, 0x0F, 0x59, 0x0D, _u32(FLOAT_TWO_PERCENT))  # mulss xmm1, [0.02f]
    a.emit(0xF3, 0x0F, 0x5C, 0xC1)  # subss xmm0, xmm1
    a.emit(0x0F, 0x57, 0xC9)  # xorps xmm1, xmm1
    a.emit(0x0F, 0x2F, 0xC8)  # comiss xmm1, xmm0
    a.jcc(JBE, "mu_fold")
    a.emit(0x0F, 0x28, 0xC1)  # movaps xmm0, xmm1       ; the floor

    # The upkeep factor, in the order the deposit applies it: inflation first, then `kept/100`.
    # Skipped at 100 so a file without upkeep produces a bit-identical result to one built
    # before the two were linked - and so `1.0f` stays exactly `1.0f`, which is what blanks.
    a.label("mu_fold")
    a.emit(0x8B, 0x45, _i8(_KEPT_EBP))  # mov eax, [ebp-8]
    a.emit(0x83, 0xF8, MAX_PERCENT)  # cmp eax, 100
    a.jcc(JE, "mu_done")
    a.emit(0xF3, 0x0F, 0x2A, 0xC8)  # cvtsi2ss xmm1, eax
    a.emit(0xF3, 0x0F, 0x59, 0x0D, _u32(FLOAT_ONE_PERCENT))  # mulss xmm1, [0.01f]
    a.emit(0xF3, 0x0F, 0x59, 0xC1)  # mulss xmm0, xmm1

    a.label("mu_done")
    a.emit(0xC9)  # leave
    a.jmp_absolute(PALANTIR_RESOURCE_MULTIPLIER_RESUME)


class InflationReadoutPatch(Patch):
    """Draw the local player's income multiplier in the palantir's resource-multiplier slot.

    `x0.7` when the faction's `ResourceModifierValues` is currently taking 30%, blank when nothing
    is being taken, and the product of both factors when `command-point-upkeep` is also installed.
    """

    name = "inflation-readout"
    description = (
        "Show the local player's current income multiplier (PlayerTemplate.ResourceModifierValues, "
        "times command-point-upkeep's factor when that patch is present) in the palantir"
    )

    def apply(self, data: bytearray) -> None:
        self._check_build(data)
        section_va = allocate_section(
            data, SECTION_NAME, lambda base: self._build_section(base, data), _CHARACTERISTICS
        )
        for file_off, old, new, note in self._edits(data, section_va):
            apply_byte_patch(data, file_off, old, new, note)

    @staticmethod
    def _check_build(data: bytes | bytearray) -> None:
        """Raise unless the palantir's `1.0f` fallback is still the window these bytes came from.

        `apply_byte_patch` would catch this too, but only after the section had been appended -
        and a file left carrying a cave nothing jumps into is a worse failure than a clean raise.

        The already-applied case is checked *first*, because it also fails the window check - and
        "you already applied this" is the useful half of that answer.
        """
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError(f"the file already carries a {SECTION_NAME} section")
        off = va_to_offset(data, PALANTIR_RESOURCE_MULTIPLIER)
        if off is None:
            raise ValueError(
                f"0x{PALANTIR_RESOURCE_MULTIPLIER:08x} is not mapped - not the expected build"
            )
        got = bytes(data[off : off + len(PALANTIR_RESOURCE_MULTIPLIER_BYTES)])
        if got != PALANTIR_RESOURCE_MULTIPLIER_BYTES:
            raise ValueError(
                "unexpected build: the palantir's resource-multiplier fallback is "
                f"{got.hex()}, expected {PALANTIR_RESOURCE_MULTIPLIER_BYTES.hex()}"
            )

    def _build_section(self, base_va: int, data: bytes | bytearray) -> bytes:
        """The import slot, then the code.

        The slot is `command-point-upkeep`'s `percent` when this file already carries it, and zero
        otherwise - in which case upkeep fills it in if it is applied later. Either order, one
        link; see :mod:`~sage_patch.patches.income_link`.
        """
        body = bytearray(CODE_OFF)
        struct.pack_into("<I", body, READOUT_IMPORT_OFF, read_export(data) or 0)
        return bytes(body) + self._assemble(base_va).finish()

    @staticmethod
    def _assemble(base_va: int) -> Asm:
        a = Asm(base_va + CODE_OFF)
        _emit_multiplier(a, base_va + READOUT_IMPORT_OFF)
        a.finish()  # resolve the internal branches, so `label_va` describes a real layout
        return a

    def _edits(
        self, data: bytes | bytearray, section_va: int
    ) -> list[tuple[int, bytes, bytes, str]]:
        """``(file offset, original bytes, patched bytes, note)`` for every engine byte this patch
        rewrites - one list, so :meth:`apply` writes exactly what :meth:`verify` asserts."""
        off = va_to_offset(data, PALANTIR_RESOURCE_MULTIPLIER)
        if off is None:
            raise ValueError(
                f"0x{PALANTIR_RESOURCE_MULTIPLIER:08x} is not mapped - not the expected build"
            )
        target = self._assemble(section_va).label_va("mult")
        return [
            (
                off,
                PALANTIR_RESOURCE_MULTIPLIER_BYTES,
                _jmp(PALANTIR_RESOURCE_MULTIPLIER, target)
                + b"\x90" * (len(PALANTIR_RESOURCE_MULTIPLIER_BYTES) - 5),
                "palantir resource multiplier -> the income multiplier",
            )
        ]

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located
        problems: list[str] = []

        # The link is legitimately absent, so the check is "zero, or the right address" - not
        # "present". A wrong address is the failure worth naming: it would be a call into
        # whatever `.upkeep` holds at that offset.
        linked = struct.unpack_from("<I", data, section_off + READOUT_IMPORT_OFF)[0]
        expected = read_export(data)
        if linked and expected is None:
            problems.append(
                f"the upkeep import is 0x{linked:08x}, but the file carries no {UPKEEP_SECTION}"
            )
        elif linked and linked != expected:
            problems.append(
                f"the upkeep import is 0x{linked:08x}, but {UPKEEP_SECTION} exports "
                f"0x{expected:08x}"
            )
        elif not linked and expected is not None:
            problems.append(
                f"the file carries {UPKEEP_SECTION} but the readout is unlinked, so the palantir "
                "would show the inflation factor without the upkeep one"
            )

        try:
            edits = self._edits(data, section_va)
        except ValueError as exc:
            return [*problems, f"cannot recompute the expected edits (wrong build?): {exc}"]
        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")
        return problems


def _jmp(at_va: int, target_va: int) -> bytes:
    return b"\xe9" + struct.pack("<i", target_va - (at_va + 5))
