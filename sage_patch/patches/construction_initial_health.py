"""The construction-initial-health patch: a building starts its construction with health.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/construction-initial-health.md``.

**What the engine does today.** A structure that is about to be built has its health driven to
exactly **one hit point**. Four sites do it and all four are the same six instructions, ending at
`internalChangeHealth(1.0 - health, NULL)`: `BuildAssistant`'s placement (``0x0079541F``), the
builder dropping a foundation (``0x008AD88E``), `GettingBuiltBehavior`'s rebuild (``0x00858975``)
and the `DozerAIUpdate` helper that restarts a build (``0x0088D59E``). Health only starts climbing
once something is actually building: the `DozerAIUpdate` ramp adds ``maxHealth / frames`` per
frame (``0x0088DEA8``), and a structure with no builder heals ``maxHealth / RebuildTimeSeconds``
per frame instead (``0x00857FC1``).

So between the moment a foundation is placed and the moment the builder reaches it, the structure
stands at 1 hit point. Anything that can reach it removes it for free, and the player who paid for
it has no counterplay - the building is not yet a building, it is a 1-HP object with a footprint.

**What this does.** Starts that structure at a **percentage of its maximum health** instead of at
one point - ``--percent 10`` by default - and re-maps the ramp so the curve still ends where it
did. Health runs ``percent`` to ``100`` across the build, reaching maximum exactly as construction
completes, rather than reaching it early and sitting there.

Three things move together, because moving one without the others changes something nobody asked
to change:

- **The start.** The four sites above set ``max(1.0, percent * maxHealth)`` rather than ``1.0``.
  The floor is what keeps a structure whose maximum health is under ten points from starting below
  one, which is the guarantee the stock constant carries.
- **The two ramps.** Both per-frame amounts are scaled by ``1 - percent``, so the remaining span
  is covered in the same number of frames. Without this a structure reaches full health at 90% and
  is quietly tougher than the progress bar says for the last tenth of every build.
- **The two derivations.** The engine also runs the relation backwards: at ``0x00856800`` and
  ``0x00858078`` it recovers the construction percent *from* the health ratio. Those become
  ``(ratio - percent) / (1 - percent)``, clamped at zero, which is the inverse of the new mapping.
  Without this a self-building structure would read 10% complete the frame it was placed and
  finish a tenth early - a build-speed change wearing a durability patch's clothes.

**`--percent 0` is stock, instruction for instruction in effect.** The start becomes
``max(1.0, 0)``, the ramps scale by 1 and the derivations by 1/1; the cave is still installed, but
every number it produces is the one the stock bytes produced. That is what makes the parameter
honest rather than a second behaviour smuggled in behind a default.

**What it deliberately does not do.** This is a starting health, not a floor: a structure under
construction can still be shot down to nothing, and a builder interrupted early still leaves a
cheap kill. Denying a building remains possible; what stops being possible is denying one that
nobody has had a chance to defend yet.

**Logic-side, so every peer needs the same binary.** Health is world state, it is xfer'd into
saves and replays, and it feeds the frame CRC - a mixed lobby desyncs on the first foundation.
No INI change: nothing here adds a keyword or reads one.

**Composition.** The seven engine sites this edits are touched by no other bundled patch. It does
share `DozerAIUpdate`'s construction advance with
:mod:`~sage_patch.patches.production_split`, which hooks the `calcTimeToBuild` call at
``0x0088DE6D`` twenty-seven bytes above the ramp step this rewrites. The two do not overlap and
neither derives its output from bytes the other writes - but this patch's ramp reads
``[ebp-0x1C]``, the frame count that call produced, at run time, which is the point: a
`PRODUCTION_CONSTRUCTION` modifier stretches or shortens the health curve exactly as it stretches
or shortens the percent curve. `production-split`'s anchor over that function is split in two so
that it pins everything it depends on **except** the six bytes this patch owns; the two apply in
either order.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from ..addresses import (
    ACTIVE_BODY_INTERNAL_CHANGE_HEALTH_SLOT,
    BODY_GET_HEALTH_RATIO_SLOT,
    BODY_GET_MAX_HEALTH_SLOT,
    CONSTRUCTION_INITIAL_HEALTH_ANCHORS,
    CONSTRUCTION_INITIAL_HEALTH_CALL_BYTES,
    CONSTRUCTION_INITIAL_HEALTH_CALLS,
    CONSTRUCTION_PERCENT_FROM_RATIO,
    CONSTRUCTION_PERCENT_FROM_RATIO_ANCHORS,
    CONSTRUCTION_PERCENT_FROM_RATIO_BYTES,
    CONSTRUCTION_RAMP_ANCHOR,
    CONSTRUCTION_RAMP_ANCHOR_BYTES,
    CONSTRUCTION_RAMP_HEALTH_STEP,
    CONSTRUCTION_RAMP_HEALTH_STEP_BYTES,
    SELF_BUILD_HEAL_ANCHOR,
    SELF_BUILD_HEAL_ANCHOR_BYTES,
    SELF_BUILD_HEAL_STEP,
    SELF_BUILD_HEAL_STEP_BYTES,
)
from ..asm import Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "ANCHORS",
    "DEFAULT_PERCENT",
    "MAX_PERCENT",
    "SECTION_NAME",
    "ConstructionInitialHealthPatch",
    "build_code",
]

SECTION_NAME = ".cstart"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_INITIALIZED_DATA | CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is code with its
# five float constants laid out ahead of the first entry point, and is never written.
_CHARACTERISTICS = 0x40 | 0x20 | 0x20000000 | 0x40000000

DEFAULT_PERCENT = 10.0

#: The ceiling, and it is arithmetic rather than taste: the derivations divide by ``1 - percent``,
#: which at 100 is a division by zero and near it magnifies a rounding difference in the health
#: ratio into a visible jump in the progress bar. 90 leaves a tenth of the bar to work with.
MAX_PERCENT = 90.0

#: Byte windows :meth:`ConstructionInitialHealthPatch.apply` requires before it writes anything,
#: as ``{va: expected bytes}``. Each one **contains** the call the patch then repoints, so this
#: table describes a stock image only; `verify` checks the installed hooks instead.
#:
#: They are what entitles the caves to their calling conventions. The four initial-health windows
#: pin that the hooked call is `internalChangeHealth(1.0 - health, NULL)` with `ecx` still the
#: body - not some other body call that happens to sit at that address. The ramp window pins that
#: `ecx` is the body and `[ebp-0x1C]` the frame count. The self-build window pins that the value
#: is divided by `fild [esi+0x1C]` afterwards, which is the order the cave has to reproduce. The
#: two derivation windows pin the `fstp [Object+0x288]` that consumes the result.
ANCHORS: dict[int, bytes] = {
    **CONSTRUCTION_INITIAL_HEALTH_ANCHORS,
    CONSTRUCTION_RAMP_ANCHOR: CONSTRUCTION_RAMP_ANCHOR_BYTES,
    SELF_BUILD_HEAL_ANCHOR: SELF_BUILD_HEAL_ANCHOR_BYTES,
    **CONSTRUCTION_PERCENT_FROM_RATIO_ANCHORS,
}

#: The four routines the cave holds, in the order it lays them out.
_ROUTINES = ("initial", "ramp", "selfbuild", "percent")

#: Every five-byte `call` this patch writes, as ``{call VA: (stock bytes, cave entry label)}``.
#: The displaced instructions are longer than five bytes at every site, so each hook is a call
#: followed by `nop` to the end of what it replaced.
_HOOKS: dict[int, tuple[bytes, str]] = {
    **{
        va: (CONSTRUCTION_INITIAL_HEALTH_CALL_BYTES[va], "initial")
        for va in CONSTRUCTION_INITIAL_HEALTH_CALLS
    },
    CONSTRUCTION_RAMP_HEALTH_STEP: (CONSTRUCTION_RAMP_HEALTH_STEP_BYTES, "ramp"),
    SELF_BUILD_HEAL_STEP: (SELF_BUILD_HEAL_STEP_BYTES, "selfbuild"),
    **{
        va: (CONSTRUCTION_PERCENT_FROM_RATIO_BYTES, "percent")
        for va in CONSTRUCTION_PERCENT_FROM_RATIO
    },
}


def _f32(value: float) -> bytes:
    return struct.pack("<f", value)


def build_code(base_va: int, percent: float) -> bytes:
    """The cave's bytes, for a cave that will sit at ``base_va``."""
    return _assemble(base_va, percent).finish()


def _routine_addresses(base_va: int, percent: float) -> dict[str, int]:
    """Where each of the four routines starts, read off the layout that is actually emitted.

    The labels are the only honest source for this: counting the bytes a second time by hand is
    exactly the arithmetic :mod:`sage_patch.asm` exists to remove.
    """
    a = _assemble(base_va, percent)
    return {name: a.label_va(name) for name in _ROUTINES}


def _assemble(base_va: int, percent: float) -> Asm:
    """The four cave routines, preceded by the five constants they read.

    The constants sit first so their addresses are known while the code that references them is
    being emitted; nothing ever enters the cave at its base, only at a labelled entry point.
    """
    fraction = percent / 100.0
    span = 1.0 - fraction

    a = Asm(base_va)
    frac_va = a.va
    a.emit(_f32(fraction))
    one_va = a.va
    a.emit(_f32(1.0))
    span_va = a.va
    a.emit(_f32(span))
    inv_span_va = a.va
    a.emit(_f32(1.0 / span))
    hundred_va = a.va
    a.emit(_f32(100.0))

    frac = struct.pack("<I", frac_va)
    one = struct.pack("<I", one_va)

    # `initial` replaces `call [vtable+0x84]` at the four "health = 1.0" sites.
    # On entry `ecx` is the body and the caller has already pushed `internalChangeHealth`'s two
    # arguments: `[esp+4]` the delta it computed as `1.0 - health`, `[esp+8]` a NULL `DamageInfo`.
    # Rewriting the delta in place is what makes one routine serve all four sites - the wanted
    # `target - health` is the delta the caller computed, less the 1.0 it aimed at, plus the
    # target - and it leaves the tail call carrying exactly the arguments the stock call carried.
    a.label("initial")
    a.emit(0x51)  # push ecx                  ; the callee may clobber it
    a.emit(0x83, 0xEC, 0x04)  # sub esp, 4    ; scratch, to land st(0) in
    a.emit(0x8B, 0x01)  # mov  eax, [ecx]
    a.emit(0xFF, 0x50, BODY_GET_MAX_HEALTH_SLOT)  # call [eax+0x1c]  -> st(0) = maxHealth
    a.emit(0xD9, 0x1C, 0x24)  # fstp dword [esp]
    a.emit(0xF3, 0x0F, 0x10, 0x04, 0x24)  # movss xmm0, [esp]
    a.emit(0xF3, 0x0F, 0x59, 0x05, frac)  # mulss xmm0, [fraction]
    a.emit(0xF3, 0x0F, 0x10, 0x0D, one)  # movss xmm1, [1.0]
    a.emit(0xF3, 0x0F, 0x5F, 0xC1)  # maxss xmm0, xmm1   ; target, never below one point
    a.emit(0xF3, 0x0F, 0x5C, 0xC1)  # subss xmm0, xmm1   ; target - 1.0
    a.emit(0xF3, 0x0F, 0x58, 0x44, 0x24, 0x0C)  # addss xmm0, [esp+0xc]  ; + (1.0 - health)
    a.emit(0xF3, 0x0F, 0x11, 0x44, 0x24, 0x0C)  # movss [esp+0xc], xmm0
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4
    a.emit(0x59)  # pop ecx
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    # Tail into the call that was displaced. Its `ret 8` cleans both arguments, so the cave is
    # invisible to the site's stack: the hook's `call` returns straight to the next instruction.
    a.emit(0xFF, 0xA0, struct.pack("<I", ACTIVE_BODY_INTERNAL_CHANGE_HEALTH_SLOT))  # jmp [eax+0x84]

    # `ramp` replaces `call [esi+0x1c]` + `fdiv [ebp-0x1c]` in the DozerAIUpdate advance.
    # `ebp` is the caller's frame pointer and the cave never sets up its own, so the divisor is
    # read exactly where the displaced `fdiv` read it - the frame count `calcTimeToBuild`
    # produced for this structure, whatever `production-split` scaled it by.
    a.label("ramp")
    a.emit(0x8B, 0x01)  # mov  eax, [ecx]
    a.emit(0xFF, 0x50, BODY_GET_MAX_HEALTH_SLOT)  # call [eax+0x1c]  -> st(0) = maxHealth
    a.emit(0xD8, 0x0D, struct.pack("<I", span_va))  # fmul dword [span]
    a.emit(0xD8, 0x75, 0xE4)  # fdiv dword [ebp-0x1c]
    a.emit(0xC3)  # ret

    # `selfbuild` replaces `call [eax+0x1c]` + `fild [esi+0x1c]` in GettingBuiltBehavior.
    # The caller divides one by the other two instructions later, so the routine has to leave the
    # x87 stack the way the displaced pair left it: frames on top, scaled maximum beneath. `esi`
    # is the module and survives the call, which is the same assumption the stock `fild` makes.
    a.label("selfbuild")
    a.emit(0x8B, 0x01)  # mov  eax, [ecx]
    a.emit(0xFF, 0x50, BODY_GET_MAX_HEALTH_SLOT)  # call [eax+0x1c]  -> st(0) = maxHealth
    a.emit(0xD8, 0x0D, struct.pack("<I", span_va))  # fmul dword [span]
    a.emit(0xDB, 0x46, 0x1C)  # fild dword [esi+0x1c]   ; st(0) = frames, st(1) = scaled maximum
    a.emit(0xC3)  # ret

    # `percent` replaces `call [vtable+0x14]` + `fmul [100.0]` at the two derivations.
    # The inverse of the new mapping. The low clamp is not defensive: a structure damaged below
    # its starting health during construction has a ratio under the fraction, and the stock code
    # would have read that as a negative percent.
    a.label("percent")
    a.emit(0x51)  # push ecx
    a.emit(0x83, 0xEC, 0x04)  # sub esp, 4
    a.emit(0x8B, 0x01)  # mov  eax, [ecx]
    a.emit(0xFF, 0x50, BODY_GET_HEALTH_RATIO_SLOT)  # call [eax+0x14]  -> st(0) = health / maximum
    a.emit(0xD9, 0x1C, 0x24)  # fstp dword [esp]
    a.emit(0xF3, 0x0F, 0x10, 0x04, 0x24)  # movss xmm0, [esp]
    a.emit(0xF3, 0x0F, 0x5C, 0x05, frac)  # subss xmm0, [fraction]
    a.emit(0xF3, 0x0F, 0x59, 0x05, struct.pack("<I", inv_span_va))  # mulss xmm0, [1/span]
    a.emit(0x0F, 0x57, 0xC9)  # xorps xmm1, xmm1
    a.emit(0xF3, 0x0F, 0x5F, 0xC1)  # maxss xmm0, xmm1
    a.emit(0xF3, 0x0F, 0x59, 0x05, struct.pack("<I", hundred_va))  # mulss xmm0, [100.0]
    a.emit(0xF3, 0x0F, 0x11, 0x04, 0x24)  # movss [esp], xmm0
    a.emit(0xD9, 0x04, 0x24)  # fld dword [esp]   ; the caller's `fstp` is expecting st(0)
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4
    a.emit(0x59)  # pop ecx
    a.emit(0xC3)  # ret
    return a


class ConstructionInitialHealthPatch(Patch):
    name = "construction-initial-health"
    author = "officialNecro"
    description = (
        "Start a structure's construction at a percentage of its maximum health instead of at "
        "one hit point, so a foundation is not a free kill for the seconds its builder spends "
        "walking to it, and re-map both construction ramps and the two percent-from-health "
        "derivations so the curve still reaches full health exactly at completion. --percent 0 "
        "reproduces stock behaviour. Logic-side: every peer needs the same binary. No INI change"
    )

    def __init__(self, percent: float = DEFAULT_PERCENT) -> None:
        if not 0.0 <= percent <= MAX_PERCENT:
            raise ValueError(f"percent must be between 0 and {MAX_PERCENT:g}, got {percent!r}")
        self.percent = float(percent)

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        code = self._layout(data)
        for va, (original, label) in _HOOKS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            target = code[label]
            call = b"\xe8" + struct.pack("<i", target - (va + 5))
            apply_byte_patch(
                data,
                off,
                original,
                call + b"\x90" * (len(original) - 5),
                f"{va:#010x} -> construction-initial-health {label} thunk",
            )

    def _layout(self, data: bytearray) -> dict[str, int]:
        """Allocate the cave and return each routine's virtual address."""
        section_va = allocate_section(
            data, SECTION_NAME, lambda va: build_code(va, self.percent), _CHARACTERISTICS
        )
        return _routine_addresses(section_va, self.percent)

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - this is not the "
                    "construction arithmetic this patch is written against"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located
        code = build_code(section_va, self.percent)
        if bytes(data[section_off : section_off + len(code)]) != code:
            return [f"the {SECTION_NAME} cave does not hold this patch's arithmetic"]
        entries = _routine_addresses(section_va, self.percent)
        for va, (original, label) in _HOOKS.items():
            off = va_to_offset(data, va)
            if off is None:
                problems.append(f"{va:#010x} is not mapped by any section")
                continue
            if data[off] != 0xE8:
                problems.append(f"{va:#010x} is not a call - the {label} hook is not installed")
                continue
            target = va + 5 + struct.unpack_from("<i", data, off + 1)[0]
            if target != entries[label]:
                problems.append(
                    f"{va:#010x} calls {target:#010x}, expected the {label} thunk at "
                    f"{entries[label]:#010x}"
                )
            padding = bytes(data[off + 5 : off + len(original)])
            if padding != b"\x90" * (len(original) - 5):
                problems.append(f"{va:#010x} is not padded to the displaced instruction's length")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> ConstructionInitialHealthPatch | None:
        """Recover the percentage from the cave's own constant, then verify at that value."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        _, section_off, _ = located
        try:
            (fraction,) = struct.unpack_from("<f", data, section_off)
        except struct.error:
            return None
        percent = round(fraction * 100.0, 4)
        if not 0.0 <= percent <= MAX_PERCENT:
            return None
        try:
            patch = cls(percent=percent)
        except ValueError:
            return None
        return None if patch.verify(data) else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--percent",
            type=float,
            default=DEFAULT_PERCENT,
            metavar="N",
            help=(
                f"fraction of maximum health a structure starts its construction at, 0 to "
                f"{MAX_PERCENT:g} (default {DEFAULT_PERCENT:g}); 0 reproduces stock behaviour"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> ConstructionInitialHealthPatch:
        return cls(percent=args.percent)
