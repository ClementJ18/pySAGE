"""Make `AutoDepositUpdate`'s income obey the faction's inflation, as `TerrainResourceBehavior`'s
already does.

The engine applies `ResourceModifierValues` only to resource spots, so a keep's income never
inflates. A detour at the deposit's float-to-int conversion scales the amount by the same rule
before truncating it. Applying this rebalances a mod.

Derivation: `../docs/auto-deposit-inflation.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    AUTO_DEPOSIT_OBJECT_ESI,
    AUTO_DEPOSIT_SCALE_AMOUNT_EBP,
    AUTO_DEPOSIT_TRUNCATE,
    AUTO_DEPOSIT_TRUNCATE_BYTES,
    AUTO_DEPOSIT_TRUNCATE_RESUME,
    FLOAT_ONE,
    FLOAT_ONE_PERCENT,
    FLOAT_TWO_PERCENT,
    OBJECT_FILTER_ALLOW,
    OBJECT_FILTER_IS_VALID,
    PLAYER_FOR_EACH_TEAM_OBJECT,
    PLAYER_PLAYER_TEMPLATE,
    PLAYER_TEMPLATE_RESOURCE_FILTER,
    PLAYER_TEMPLATE_RESOURCE_VALUES,
    RESOURCE_MODIFIER_COUNT_CALLBACK,
)
from ..asm import JBE, JE, JGE, Asm
from ..patcher import Patch
from ..utils import (
    allocate_section,
    apply_byte_patch,
    find_section,
    i8,
    jmp_rel32,
    u32,
    va_to_offset,
)

__all__ = ["SECTION_NAME", "AutoDepositInflationPatch", "multiplier"]

#: 8 chars max: the PE name field truncates silently past 8.
SECTION_NAME = ".adinfl"

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ. The cave is code and nothing in it is
# written at run time, so no MEM_WRITE.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000


def multiplier(count: int, values: tuple[int, ...]) -> float:
    """The factor an income is scaled by - the engine's rule, in Python, so the tests can state it
    once and assert the emitted code against the same one.

    `count` is how many of the player's objects the faction's `ResourceModifierObjectFilter`
    accepts and `values` its `ResourceModifierValues`, as percentages. Past the end of the table
    the last entry keeps falling at two percentage points an object, floored at zero.

    Computed in single precision throughout, because the whole point is to produce the number
    `TerrainResourceBehavior` produces rather than one that agrees with it to a few decimals.
    An empty table is `1.0`; see the class docstring for why that diverges from the engine.
    """
    one_percent = struct.unpack("<f", struct.pack("<f", 0.01))[0]
    two_percent = struct.unpack("<f", struct.pack("<f", 0.02))[0]

    def f32(value: float) -> float:
        return struct.unpack("<f", struct.pack("<f", value))[0]  # type: ignore[no-any-return]

    n = len(values)
    if n == 0:
        return 1.0
    if count < n:
        return f32(values[count] * one_percent)
    return max(f32(f32(values[-1] * one_percent) - f32((count - n) * two_percent)), 0.0)


# Everything below is hand-encoded (the house style: only address arithmetic is automated, by
# `..asm`), with a comment saying what each instruction is.

# `inflation`'s frame. The multiplier lives in memory rather than in `xmm0` across the three engine
# calls, because no calling convention in this image promises an SSE register survives one.
# `{ ObjectFilter* filter; Int count; }` is the shape `RESOURCE_MODIFIER_COUNT_CALLBACK` expects,
# filter at the lower address.
_MULT_EBP = -0x04
_CTX_COUNT_EBP = -0x0C
_CTX_EBP = -0x10
_MULT_FRAME = 0x10
_MULT_PLAYER_ARG = 0x08
_MULT_OBJECT_ARG = 0x0C


def _emit_inflation(a: Asm) -> None:
    """`inflation(Player* player, Object* obj) -> xmm0` - cdecl, caller-cleaned.

    `0x008855A3`-`0x0088564B` reproduced for the module that does not have it: the owner's
    `ResourceModifierValues` factor, **gated on the object being one the filter accepts**, which is
    the gate at `0x008855CE` and the reason a faction that declares no filter is untouched.

    `1.0f` on every degenerate path: no template, no filter, an object the filter rejects, an empty
    value table. The last of those diverges deliberately from the engine, which reads `values[n-1]`
    of an empty vector - a stray read of one dword in the deposit path; `inflation-readout` made
    the same call for the same reason.
    """
    a.label("inflation")
    a.emit(0x55)  # push ebp
    a.emit(0x89, 0xE5)  # mov ebp, esp
    a.emit(0x83, 0xEC, _MULT_FRAME)  # sub esp, 0x10
    a.emit(0xF3, 0x0F, 0x10, 0x05, u32(FLOAT_ONE))  # movss xmm0, [1.0f]
    a.emit(0xF3, 0x0F, 0x11, 0x45, i8(_MULT_EBP))  # movss [ebp-4], xmm0

    a.emit(0x8B, 0x45, _MULT_PLAYER_ARG)  # mov eax, [ebp+8]
    a.emit(0x8B, 0x40, PLAYER_PLAYER_TEMPLATE)  # mov eax, [eax+0x34]    ; the PlayerTemplate
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "in_done")
    a.emit(0x05, u32(PLAYER_TEMPLATE_RESOURCE_FILTER))  # add eax, 0x1c8
    a.emit(0x89, 0x45, i8(_CTX_EBP))  # mov [ebp-0x10], eax    ; ctx.filter
    a.emit(0x83, 0x65, i8(_CTX_COUNT_EBP), 0x00)  # and dword [ebp-0xc], 0 ; ctx.count
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.call_absolute(OBJECT_FILTER_IS_VALID)  # thiscall, no arguments
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "in_done")

    # `filter.allow(object, player)` - the engine pushes the player first, so the object is the
    # first argument. This is the gate that keeps an unlisted structure paying its full amount.
    a.emit(0xFF, 0x75, _MULT_PLAYER_ARG)  # push [ebp+8]           ; the Player
    a.emit(0xFF, 0x75, _MULT_OBJECT_ARG)  # push [ebp+0xc]         ; the Object
    a.emit(0x8B, 0x4D, i8(_CTX_EBP))  # mov ecx, [ebp-0x10]
    a.call_absolute(OBJECT_FILTER_ALLOW)  # ret 8
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "in_done")  # not in the list -> no inflation

    a.emit(0x8D, 0x45, i8(_CTX_EBP))  # lea eax, [ebp-0x10]
    a.emit(0x50)  # push eax               ; the context
    a.emit(0x68, u32(RESOURCE_MODIFIER_COUNT_CALLBACK))  # push the engine's own counter
    a.emit(0x8B, 0x4D, _MULT_PLAYER_ARG)  # mov ecx, [ebp+8]
    a.call_absolute(PLAYER_FOR_EACH_TEAM_OBJECT)  # ret 8

    a.emit(0x8B, 0x45, _MULT_PLAYER_ARG)  # mov eax, [ebp+8]
    a.emit(0x8B, 0x40, PLAYER_PLAYER_TEMPLATE)  # mov eax, [eax+0x34]
    a.emit(0x05, u32(PLAYER_TEMPLATE_RESOURCE_VALUES))  # add eax, 0x1cc
    a.emit(0x8B, 0x08)  # mov ecx, [eax]         ; values.begin
    a.emit(0x8B, 0x40, 0x04)  # mov eax, [eax+4]       ; values.end
    a.emit(0x29, 0xC8)  # sub eax, ecx
    a.emit(0xC1, 0xF8, 0x02)  # sar eax, 2             ; n
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "in_done")  # an empty table: see the docstring
    a.emit(0x8B, 0x55, i8(_CTX_COUNT_EBP))  # mov edx, [ebp-0xc]     ; count
    a.emit(0x39, 0xC2)  # cmp edx, eax
    a.jcc(JGE, "in_past_end")
    a.emit(0xF3, 0x0F, 0x2A, 0x04, 0x91)  # cvtsi2ss xmm0, dword [ecx+edx*4]
    a.emit(0xF3, 0x0F, 0x59, 0x05, u32(FLOAT_ONE_PERCENT))  # mulss xmm0, [0.01f]
    a.jmp("in_store")

    a.label("in_past_end")  # values[n-1]*0.01 - (count-n)*0.02, floored at zero
    a.emit(0xF3, 0x0F, 0x2A, 0x44, 0x81, 0xFC)  # cvtsi2ss xmm0, dword [ecx+eax*4-4]
    a.emit(0xF3, 0x0F, 0x59, 0x05, u32(FLOAT_ONE_PERCENT))  # mulss xmm0, [0.01f]
    a.emit(0x29, 0xC2)  # sub edx, eax
    a.emit(0xF3, 0x0F, 0x2A, 0xCA)  # cvtsi2ss xmm1, edx
    a.emit(0xF3, 0x0F, 0x59, 0x0D, u32(FLOAT_TWO_PERCENT))  # mulss xmm1, [0.02f]
    a.emit(0xF3, 0x0F, 0x5C, 0xC1)  # subss xmm0, xmm1
    a.emit(0x0F, 0x57, 0xC9)  # xorps xmm1, xmm1
    a.emit(0x0F, 0x2F, 0xC8)  # comiss xmm1, xmm0
    a.jcc(JBE, "in_store")
    a.emit(0x0F, 0x28, 0xC1)  # movaps xmm0, xmm1      ; the floor

    a.label("in_store")
    a.emit(0xF3, 0x0F, 0x11, 0x45, i8(_MULT_EBP))  # movss [ebp-4], xmm0

    a.label("in_done")
    a.emit(0xF3, 0x0F, 0x10, 0x45, i8(_MULT_EBP))  # movss xmm0, [ebp-4]
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret


def _emit_scale(a: Asm) -> None:
    """Entered in place of `AutoDepositUpdate`'s `cvttss2si eax, [ebp-0x14]`.

    `edi` is the controlling `Player` and `[esi-8]` the depositing `Object`, both callee-saved
    across the helper's engine calls. The displaced instruction is re-emitted here against `xmm0`
    rather than against the slot, so the amount is truncated **once**, on the scaled value - a
    second rounding would lose a gold per tick for no reason.

    Nothing else is touched: `[ebp-0x14]` keeps the unscaled float (the module rewrites it three
    instructions later anyway) and `[ebp-0x10]`, which the experience grant reads at `0x0089DD36`,
    is not written at all.
    """
    a.label("scale")
    a.emit(0xFF, 0x76, i8(AUTO_DEPOSIT_OBJECT_ESI))  # push [esi-8]         ; the Object
    a.emit(0x57)  # push edi             ; the Player
    a.call("inflation")  # -> xmm0
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.emit(0xF3, 0x0F, 0x59, 0x45, i8(AUTO_DEPOSIT_SCALE_AMOUNT_EBP))  # mulss xmm0, [ebp-0x14]
    a.emit(0xF3, 0x0F, 0x2C, 0xC0)  # cvttss2si eax, xmm0  ; the displaced truncation
    a.jmp_absolute(AUTO_DEPOSIT_TRUNCATE_RESUME)


def _assemble(base_va: int) -> Asm:
    """The whole cave: the helper, then the entry point."""
    a = Asm(base_va)
    _emit_inflation(a)
    _emit_scale(a)
    a.finish()  # resolve the internal branches, so `label_va` describes a real layout
    return a


class AutoDepositInflationPatch(Patch):
    """Scale `AutoDepositUpdate`'s deposit by the same `ResourceModifierValues` factor the engine
    already applies to `TerrainResourceBehavior`'s."""

    name = "auto-deposit-inflation"
    author = "officialNecro"
    description = (
        "Make AutoDepositUpdate's deposit obey the faction's ResourceModifierValues inflation, "
        "which the stock engine applies only to TerrainResourceBehavior - so a keep's flat income "
        "falls with a player's building count the way a resource spot's already does. No new INI "
        "field: it reuses the faction's existing ResourceModifierObjectFilter and "
        "ResourceModifierValues, and a faction whose filter does not accept the depositing object "
        "is unaffected. This also makes a negative DepositAmount under maintenance-cost inflate, "
        "since that patch charges whatever amount reaches it"
    )

    def apply(self, data: bytearray) -> None:
        self._check_build(data)
        section_va = allocate_section(
            data, SECTION_NAME, lambda base: _assemble(base).finish(), _CHARACTERISTICS
        )
        for file_off, old, new, note in self._edits(data, section_va):
            apply_byte_patch(data, file_off, old, new, note)

    @staticmethod
    def _check_build(data: bytes | bytearray) -> None:
        """Raise unless the truncation is still the window these bytes came from.

        `apply_byte_patch` would catch this too, but only after the section had been appended - and
        a file left carrying a cave nothing jumps into is a worse failure than a clean raise. The
        already-applied case is checked first, because it also fails the window check and "you
        already applied this" is the useful half of that answer.
        """
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError(f"the file already carries a {SECTION_NAME} section")
        off = va_to_offset(data, AUTO_DEPOSIT_TRUNCATE)
        if off is None:
            raise ValueError(
                f"0x{AUTO_DEPOSIT_TRUNCATE:08x} is not mapped - not the expected build"
            )
        got = bytes(data[off : off + len(AUTO_DEPOSIT_TRUNCATE_BYTES)])
        if got != AUTO_DEPOSIT_TRUNCATE_BYTES:
            raise ValueError(
                "unexpected build: AutoDepositUpdate's amount truncation at "
                f"0x{AUTO_DEPOSIT_TRUNCATE:08x} is {got.hex()}, expected "
                f"{AUTO_DEPOSIT_TRUNCATE_BYTES.hex()}"
            )

    def _edits(
        self, data: bytes | bytearray, section_va: int
    ) -> list[tuple[int, bytes, bytes, str]]:
        """`(file offset, original bytes, patched bytes, note)` for every engine byte this patch
        rewrites - one list, so `apply` writes exactly what `verify` asserts."""
        off = va_to_offset(data, AUTO_DEPOSIT_TRUNCATE)
        if off is None:
            raise ValueError(
                f"0x{AUTO_DEPOSIT_TRUNCATE:08x} is not mapped - not the expected build"
            )
        target = _assemble(section_va).label_va("scale")
        return [
            (
                off,
                AUTO_DEPOSIT_TRUNCATE_BYTES,
                jmp_rel32(AUTO_DEPOSIT_TRUNCATE, target),
                "AutoDepositUpdate's amount truncation -> the inflation scale",
            )
        ]

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
