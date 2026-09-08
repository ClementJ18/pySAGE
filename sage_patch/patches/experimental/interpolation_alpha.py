"""The interpolation-alpha patch: take the alpha over the sub-frames the client can actually see.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001`` **as Edain and AotR ship it**.
Every address below is derived in ``../../docs/interpolation-alpha.md``.

**The defect.** ``GameEngine::update`` counts rendered frames in ``TheGameEngine+0x34`` and ends a
logic frame when the count passes the wrap at ``0x0063264A``. The render path bridges the gap with
an alpha, ``+0x3C = +0x34 / +0x38``, recomputed on every sub-frame and read by seven sites - the
live drawable interpolation at ``0x006765C4``, three W3D animation lerps, and the counter readout
at ``0x008A037D``.

On a stock binary the counter takes every value from 1 to the wrap, so the alpha sweeps
``1/N .. N/N`` in N even steps and the step across the logic-frame boundary is the same size as
every other. On this build it does not. The catch-up loop's escape at
`CATCHUP_ESCAPE` is replaced with ``mov eax, 2`` / ``jmp``, so the loop runs one iteration every
logic frame and its ``inc dword [ebp+0x34]`` steps the counter from 1 to 2 *inside the same logic
step* - before ``GameClient::update`` runs again. Measured live over 373 client frames
(``render-rate.md`` §9.2): the counter took 2..6 at rate 30 and 2..12 at rate 60, **never 1**.

The denominator did not move with it. ``+0x38`` is still ``clientRate / logicRate``, so the alpha
sweeps ``2/N .. N/N`` - N-1 steps of ``1/N`` and then a boundary step of ``2/N``. **Every
interpolated thing on screen moves a normal step N-1 times and then a double step, once per logic
frame**: five times a second at 30 fps. That is the jitter in offset animations and in the resource
readout.

**What this does.** Appends an ``.alpha`` PE section holding a replacement for
`ALPHA_RECOMPUTE` and redirects its five-byte head into it. The replacement computes

    alpha = (subFrame - 1) / (ratio - 1)

which maps the range the client actually observes, ``2..N``, onto ``1/(N-1) .. 1`` in N-1 even
steps - so the boundary step is the same size as every other one and the sweep still ends at
exactly 1.0, which is the phase stock has and the seven readers are written against.

**Why the denominator and not the loop.** Reverting `CATCHUP_ESCAPE` to its stock bytes would also
remove the jitter, and would be a smaller patch - but the stolen sub-frame *is* the delay fix. A
logic frame completing in N-1 rendered frames instead of N is what raises the logic clock from
5 Hz to 6 Hz on a 30 fps client, and a network run-ahead counted in logic frames but felt in
seconds shortens by the same sixth. Reverting the loop gives the jitter fix back by giving the
latency fix up. Correcting the denominator keeps both.

**Why not clamp-and-hope.** The alpha is already clamped into ``[0, 1]`` by the routine this
replaces, and the clamp never fires on the values in question - ``2/N`` is a perfectly legal alpha.
Nothing downstream can tell a doubled step from a real one, which is why this is visible on screen
and invisible to every check in the engine.

**The degenerate case is real, not defensive.** ``+0x38`` is 1 from the constructor (``0x0063A4DE``)
until the first recompute fires, so ``ratio - 1`` is genuinely zero for the opening window of a
match. The cave tests for it and writes 1.0 - show the current transform, interpolate nothing -
rather than dividing.

**This build only.** :meth:`~InterpolationAlphaPatch._check_anchors` refuses a binary whose
catch-up loop still carries its stock escape. There sub-frame 1 *is* observable, the stock alpha is
already even, and subtracting one from the numerator would put a zero-length step at the boundary
instead of a doubled one - the same defect with the sign flipped.

**Composition.** Order-independent, and specifically with
:mod:`~sage_patch.patches.experimental.render_rate`, which is the other patch in this block. That
one rewrites the wrap and the recompute gate; this one reads neither, and reads ``+0x38`` at run
time rather than deriving anything from the bytes that set it - so whatever ratio `render-rate`
establishes, the alpha is taken over it. The only engine bytes this edits are the five at
`ALPHA_RECOMPUTE`, which no other bundled patch touches.
"""

from __future__ import annotations

import struct

from ...addresses import (
    ALPHA_RECOMPUTE,
    ALPHA_RECOMPUTE_BODY,
    ALPHA_RECOMPUTE_BODY_BYTES,
    ALPHA_RECOMPUTE_ENTRY,
    CATCHUP_ESCAPE,
    CATCHUP_ESCAPE_ALWAYS_RUNS,
    FLOAT_ONE,
    GAME_ENGINE_ALPHA,
    GAME_ENGINE_SUB_FRAME,
    GAME_ENGINE_SUB_FRAME_RATIO,
)
from ...asm import JBE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "HOOK_ORIGINAL",
    "HOOK_VA",
    "SECTION_NAME",
    "InterpolationAlphaPatch",
    "build_code",
]

SECTION_NAME = ".alpha"  # 6 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

HOOK_VA = ALPHA_RECOMPUTE
HOOK_ORIGINAL = ALPHA_RECOMPUTE_ENTRY

#: What has to be true of the image before the correction means anything, as a `{va: bytes}` map.
#:
#: `ALPHA_RECOMPUTE_BODY` says the routine being replaced is the one that divides the sub-frame by
#: the ratio and clamps - not some other build's arithmetic. `CATCHUP_ESCAPE` says the catch-up
#: loop always runs, which is the whole premise: it is what makes sub-frame 1 unobservable and
#: therefore what makes `(subFrame - 1) / (ratio - 1)` the even sweep rather than the skewed one.
#: `FLOAT_ONE` is the 1.0f the cave subtracts and clamps against, and is the constant the routine
#: being replaced already reads for its own high clamp.
ANCHORS = {
    ALPHA_RECOMPUTE_BODY: ALPHA_RECOMPUTE_BODY_BYTES,
    CATCHUP_ESCAPE: CATCHUP_ESCAPE_ALWAYS_RUNS,
    FLOAT_ONE: struct.pack("<f", 1.0),
}


def build_code(base_va: int) -> bytes:
    """The replacement alpha. Reached only from the hook, and returns to the hook's caller.

    `ecx` is `TheGameEngine`, as it is at the entry this displaces. Only `xmm0` and `xmm1` are
    touched, which is exactly what the routine being replaced clobbers, so no caller can tell the
    difference beyond the value written to `+0x3C`.
    """
    one = struct.pack("<I", FLOAT_ONE)
    a = Asm(base_va)

    # xmm1 = ratio - 1: the number of sub-frames the client actually observes, because the
    # catch-up loop consumes the first one before `GameClient::update` next runs.
    a.emit(0xF3, 0x0F, 0x2A, 0x49, GAME_ENGINE_SUB_FRAME_RATIO)  # cvtsi2ss xmm1, [ecx+0x38]
    a.emit(0xF3, 0x0F, 0x5C, 0x0D, one)  # subss xmm1, [FLOAT_ONE]

    # Until the first recompute fires, the constructor's `+0x38` of 1 makes that zero.
    a.emit(0x0F, 0x57, 0xC0)  # xorps  xmm0, xmm0
    a.emit(0x0F, 0x2F, 0xC8)  # comiss xmm1, xmm0
    a.jcc(JBE, "no_span")

    # xmm0 = (subFrame - 1) / (ratio - 1), on the same 1-based phase stock ends at 1.0 with.
    a.emit(0xF3, 0x0F, 0x2A, 0x41, GAME_ENGINE_SUB_FRAME)  # cvtsi2ss xmm0, [ecx+0x34]
    a.emit(0xF3, 0x0F, 0x5C, 0x05, one)  # subss xmm0, [FLOAT_ONE]
    a.emit(0xF3, 0x0F, 0x5E, 0xC1)  # divss xmm0, xmm1

    # The same two-sided clamp the displaced routine ends with. It does not fire on any sub-frame
    # the wrap produces; it fires when `0x006323D2` has ratcheted `+0x38` on a networked peer.
    a.emit(0x0F, 0x57, 0xC9)  # xorps xmm1, xmm1
    a.emit(0xF3, 0x0F, 0x5F, 0xC1)  # maxss xmm0, xmm1
    a.emit(0xF3, 0x0F, 0x10, 0x0D, one)  # movss xmm1, [FLOAT_ONE]
    a.emit(0xF3, 0x0F, 0x5D, 0xC1)  # minss xmm0, xmm1
    a.emit(0xF3, 0x0F, 0x11, 0x41, GAME_ENGINE_ALPHA)  # movss [ecx+0x3c], xmm0
    a.emit(0xC3)  # ret

    # No span to interpolate across yet: show the current transform rather than divide by zero.
    a.label("no_span")
    a.emit(0xF3, 0x0F, 0x10, 0x05, one)  # movss xmm0, [FLOAT_ONE]
    a.emit(0xF3, 0x0F, 0x11, 0x41, GAME_ENGINE_ALPHA)  # movss [ecx+0x3c], xmm0
    a.emit(0xC3)  # ret
    return a.finish()


class InterpolationAlphaPatch(Patch):
    name = "interpolation-alpha"
    author = "officialNecro"
    experimental = True
    description = (
        "Stop every interpolated transform taking a doubled step at the logic-frame boundary, "
        "five times a second, by taking the interpolation alpha over the sub-frames the client "
        "actually observes instead of over the nominal ratio. For a binary whose catch-up loop "
        "always runs, which is what makes sub-frame 1 unobservable. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        jump = b"\xe9" + struct.pack("<i", section_va - (HOOK_VA + 5))
        apply_byte_patch(
            data,
            hook_off,
            HOOK_ORIGINAL,
            jump,
            "GameEngine::recomputeAlpha -> interpolation-alpha cave",
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
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - this is not a "
                    "binary whose catch-up loop always runs, so sub-frame 1 is observable and "
                    "the correction would skew the sweep the other way"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located
        off = va_to_offset(data, HOOK_VA)
        if off is None:
            return [f"{HOOK_VA:#010x} is not mapped by any section"]
        if data[off] != 0xE9:
            return [f"{HOOK_VA:#010x} is not a jmp - the hook is not installed"]
        target = HOOK_VA + 5 + struct.unpack_from("<i", data, off + 1)[0]
        if target != section_va:
            problems.append(f"hook jumps to {target:#010x}, expected {section_va:#010x}")
        code = build_code(section_va)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected alpha")
        return problems
