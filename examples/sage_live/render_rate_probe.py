"""Measure what the client frame rate actually drives, in a running match.

`sage_patch/docs/render-rate.md` §8 withdrew the render-rate patch on an argument: raising the
client rate speeds up "client content authored in client frames". The census in
`sage_patch/scripts/census_client_rate.py` enumerated the sites statically. This measures the
two that decide whether the feature is reachable, because neither has ever been observed:

  1. **Does a higher client rate actually buy distinct interpolated positions?**
     The interpolated transform is cached per drawable and stamped with the client frame, so
     more client frames only mean smoother motion if it is genuinely recomputed between them.
     §8 asserts it is. Phase 3 counts recomputes and distinct outputs per logic frame across
     many drawables, which is the whole value of the feature. Mind the offsets below: the
     function §8 reads is **not** the one this build runs.

  2. **Does frame-counted content really advance one unit per client frame?**
     The list at `[0x00DC78D4]`, walked by `0x004655F8`, is handed a hardcoded `1/30` second
     (`[0x00BDFC6C]`) once per client frame and expires an entry when its accumulator at
     `+0x20` passes its lifetime at `+0x18`. Phase 4 measures the accumulator against the
     client frame: an increment of 0.0333 per client frame is "FX at double speed" proved
     mechanically rather than argued.

  3. **Does the alpha's denominator hold still on a networked client?**
     `+0x38` is not a reporting field: it is what the alpha divides by, so every interpolated
     transform and every W3D animation lerp is scaled by it. `0x006323D2` grows it while a peer
     is behind, and that site is unreachable without a network object - so it can only ever
     move off-host. §9.10 is that measurement, and it is the one the "multiplayer must work"
     directive turns on.

**Read-only, and needs no patch** - which is the point. Run it on a stock install first for the
30 fps baseline, then on a render-rate build at 60 and diff the two JSON files. It does need an
elevated shell, because `game.dat` runs as administrator.

    python examples/sage_live/render_rate_probe.py
    python examples/sage_live/render_rate_probe.py --seconds 5 --json baseline-30.json

For the multiplayer question, run the frozen build on **both** machines during the same match -
the host and the off-host - and diff the two files. `dist/render_rate_probe.exe`, built with:

    pyinstaller examples/sage_live/render-rate-probe.spec
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

if not getattr(sys, "frozen", False):  # a frozen build carries its imports; the path would be junk
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

from sage_live.backends.memory import (  # noqa: E402
    LAYOUT_ROTWK_201,
    ProcessMemory,
    find_game_processes,
)

# The pacing globals, from render-rate.md §1 and §3. Addresses are VAs in a no-ASLR image.
LOGIC_RATE = 0x00D9F608
CLIENT_RATE = 0x00D9F60C
DERIVED_FLOATS = {
    0x00D9F610: "logic/1000",
    0x00D9F614: "1000/logic",
    0x00D9F618: "(float)logic",
    0x00D9F61C: "1/logic",
    0x00D9F620: "1000/client",
    0x00D9F624: "client/1000",
    0x00D9F628: "(float)client",
    0x00D9F62C: "1/client",
}
THE_GAME_ENGINE = 0x00DE4324
THE_GAME_CLIENT = 0x00DE4388
THE_GAME_LOGIC = 0x00DE412C
FX_LIFETIME_LIST = 0x00DC78D4  # the list 0x004655F8 walks with a fixed 1/30 dt
HARDCODED_STEP = 0x00BDFC6C  # the 1/30 the withdrawn patch never rescaled

# TheGameEngine fields (render-rate.md §3).
ENGINE_MAX_FPS = 0x0C
ENGINE_SUBFRAME = 0x34
ENGINE_RATIO = 0x38
ENGINE_ALPHA = 0x3C
ENGINE_RATES_CHANGED = 0x40  # the latch the +0x38 recompute needs set before it will run
ENGINE_SUBFRAME_HIGH = 0x44  # the float high-water mark 0x0063239D keeps beside the ratio

# The network pacing state (render-rate.md §9.10). `+0x38` is the alpha's denominator, and on a
# networked client it is not a constant: `0x0063239D` grows it with `inc dword [esi+0x38]` when a
# peer is behind. Its only other writer is the recompute at `0x0063260F`, which the patch gates on
# a sub-frame index that never occurs - so the growth is one-way. These are the fields that say so.
NET_OBJECT = 0x00DE4468  # the network singleton; null in single-player and in replays
NET_SLOWDOWN = 0x00D9F498  # the scalar the Sleep(0) pace multiplies m_maxFPS by (§2)
RECOMPUTE_GATE_IMM = 0x00632606  # imm8 of `cmp ecx, N` at 0x00632604 - stock 6, the patch wrote 1
WRAP_IMM = 0x0063264C  # imm8 of `cmp eax, N` at 0x0063264A - stock 6, the patch writes the ratio

# GameClient+0x10 is the client frame; its getter is vtable +0x7C (`mov eax,[ecx+0x10]; ret`).
CLIENT_FRAME = 0x10
LOGIC_FRAME = 0x40  # TheGameLogic+0x40

# Drawable fields, from `0x006765C4` - **not** from `0x0067171D`.
#
# render-rate.md §8 reads the interpolation out of `Drawable::getInterpolatedTransform`
# (`0x0067171D`, fields +0x170 / +0x1A0 / +0x1D0 / +0x204 / +0x378). On the running binary that
# function has exactly **one** caller, behind a per-drawable flag, and its stamp reads
# 0xFFFFFFFF on every live drawable - it never runs. Measured 2026-08-20 across 615 objects.
#
# The path that does run is `0x006765C4`, and it is the same idea at different offsets: stamp
# the result with the client frame, return the cache on a second call in the same frame.
#
#   0065E3  cmp [esi+0x244], clientFrame  ; already computed this client frame -> cached
#   0065F9  cmp [esi+0x3A4], logicFrame-2 ; not moved in 2 logic frames -> snap, no interpolation
#   06688   lerp(+0x3AC, +0x3DC, alpha) -> +0x208, then a spline over +0x40C/+0x418/+0x424/+0x430
#           overwrites the output matrix's translation
DRAW_PREVIOUS = 0x3AC
DRAW_CURRENT = 0x3DC
DRAW_INTERPOLATED = 0x208
DRAW_STAMP = 0x244  # the client frame the interpolation was last computed on
DRAW_LAST_MOVED = 0x3A4  # snaps instead of interpolating once this is 2 logic frames stale
MATRIX_BYTES = 48  # row-major 3x4; translation at +0x0C, +0x1C, +0x2C
WATCHED_DRAWABLES = 40


def must(value: int | float | None, what: str) -> float:
    """A reading the probe cannot continue without.

    Every accessor returns None on a failed read, which is right for a report but wrong for
    arithmetic - a probe that quietly treats an unreadable field as zero produces a plausible
    number and no warning, which is the one outcome worse than stopping.
    """
    if value is None:
        raise SystemExit(f"could not read {what} - is a match running, and is this shell elevated?")
    return value


class Probe:
    """Typed reads against the live process. Every accessor returns None on a failed read."""

    def __init__(self, memory: ProcessMemory) -> None:
        self.memory = memory

    def u32(self, address: int) -> int | None:
        raw = self.memory.read(address, 4)
        return struct.unpack("<I", raw)[0] if raw else None

    def u8(self, address: int) -> int | None:
        raw = self.memory.read(address, 1)
        return raw[0] if raw else None

    def i32(self, address: int) -> int | None:
        raw = self.memory.read(address, 4)
        return struct.unpack("<i", raw)[0] if raw else None

    def f32(self, address: int) -> float | None:
        raw = self.memory.read(address, 4)
        return struct.unpack("<f", raw)[0] if raw else None

    def pointer(self, address: int) -> int | None:
        value = self.u32(address)
        return value if value and 0x00010000 <= value <= 0x7FFFFFFF else None


def describe_divergence(probe: Probe, client_rate: int) -> dict:
    """How this running binary differs from the one render-rate.md §3.3 and §3.4 reasoned about.

    The installed `game.dat` is byte-identical to the repo-root one, which §0 flags as not
    stock - and two of its differences are in this code:

      * `0x00632535` divides the client rate by `[0x00ECA400]` (8) instead of by the logic
        rate, so the once-per-logic-frame latch fires on a different sub-frame. **The
        sub-frame it picks depends on the client rate**, so raising the rate moves it: at 30
        the divisor gives 3, which is under the floor of 6, so the predicate answers
        `subFrame == 2`; at 60 it gives 7, which is over, so it answers `subFrame == 1`.
        §3.3's "needs no edit, it answers subFrame == 1 at every rate this patch allows" is
        true of the backup and false here.

      * `0x00632A9B` is `mov eax, 2` followed by a jump over the `cmp ecx, 6 / jge` escape, so
        the catch-up loop of §3.4 **always runs** one extra `GameLogic::update(2)` per logic
        frame rather than staying dormant - and `0x00632ACF`, one of the three strides the
        patch edits, lives inside it.

    Both are read out of the live process rather than assumed, because a reinstall or a
    different Edain build would change them.
    """
    # `mov eax,[clientRate]` (5) + `cdq` (1) + `idiv dword ptr [disp32]` (2 + disp32): the
    # divisor's address is decoded out of the instruction rather than assumed, so this reports
    # correctly on a stock binary, on this one, and on whatever a future Edain build ships.
    predicate_bytes = probe.memory.read(0x0063252F, 12)
    catchup_bytes = probe.memory.read(0x00632A9B, 7)
    if predicate_bytes is None or catchup_bytes is None:
        raise SystemExit("could not read the pacing code - is this shell elevated?")
    divisor_global = struct.unpack_from("<I", predicate_bytes, 8)[0]
    divisor = probe.i32(divisor_global)
    stock_predicate = divisor_global == LOGIC_RATE
    stock_catchup = catchup_bytes[0] != 0xB8  # not `mov eax, imm32`

    n = client_rate // divisor if divisor else None
    fires_on = None if n is None else (1 if n >= 6 else (6 // n if n else None))

    print("\nbinary")
    origin = (
        "the logic rate (stock)" if stock_predicate else f"[0x{divisor_global:08X}] = {divisor}"
    )
    print(f"  latch predicate divides the client rate by {origin}")
    print(f"    -> it fires on sub-frame {fires_on}")
    print(f"  catch-up loop: {'dormant above ratio 6 (stock)' if stock_catchup else 'ALWAYS RUNS'}")
    return {
        "predicate_divisor_global": f"0x{divisor_global:08X}",
        "predicate_divisor": divisor,
        "predicate_is_stock": stock_predicate,
        "predicate_fires_on_subframe": fires_on,
        "catchup_is_stock": stock_catchup,
    }


def describe_rates(probe: Probe) -> dict:
    """The rate block and the sub-frame state, as the binary currently holds them."""
    engine = probe.pointer(THE_GAME_ENGINE)
    client = probe.pointer(THE_GAME_CLIENT)
    logic = probe.pointer(THE_GAME_LOGIC)
    if engine is None or client is None:
        raise SystemExit("TheGameEngine or TheGameClient is null - is a match running?")

    client_rate = int(must(probe.i32(CLIENT_RATE), "the client rate"))
    derived = {name: probe.f32(va) for va, name in DERIVED_FLOATS.items()}
    step = must(probe.f32(HARDCODED_STEP), "the hardcoded step at 0x00BDFC6C")
    readout = {
        "logic_rate": probe.i32(LOGIC_RATE),
        "client_rate": client_rate,
        "derived": derived,
        "hardcoded_step_0x00BDFC6C": step,
        "max_fps": probe.i32(engine + ENGINE_MAX_FPS),
        "ratio": probe.i32(engine + ENGINE_RATIO),
        "subframe": probe.i32(engine + ENGINE_SUBFRAME),
        "alpha": probe.f32(engine + ENGINE_ALPHA),
        "client_frame": probe.u32(client + CLIENT_FRAME),
        "logic_frame": probe.u32(logic + LOGIC_FRAME) if logic else None,
    }

    print("rates")
    print(f"  logic  [0x00D9F608] = {readout['logic_rate']}")
    print(f"  client [0x00D9F60C] = {client_rate}")
    print(f"  TheGameEngine+0x0C maxFPS = {readout['max_fps']}   +0x38 ratio = {readout['ratio']}")
    per_client = derived["1/client"]
    if per_client is not None:
        print(f"  1/client [0x00D9F62C] = {per_client:.6f}   (the patch rescales this one)")
    print(f"  hardcoded step [0x00BDFC6C] = {step:.6f}   (the patch does not)")
    expected = 1.0 / client_rate if client_rate else 0.0
    if abs(step - expected) > 1e-6:
        print(f"    ! disagrees with 1/{client_rate} = {expected:.6f}")
    return readout


def measure_pace(probe: Probe, seconds: float) -> dict:
    """Client and logic frames against the wall clock, plus the alpha's observed sweep.

    Sampling as fast as the reads allow and recording only on change keeps this honest about
    the *engine's* cadence rather than the sampler's.
    """
    client = probe.pointer(THE_GAME_CLIENT)
    logic = probe.pointer(THE_GAME_LOGIC)
    engine = probe.pointer(THE_GAME_ENGINE)
    if client is None or logic is None or engine is None:
        raise SystemExit("pacing globals are unreadable")

    first_client = int(must(probe.u32(client + CLIENT_FRAME), "the client frame"))
    first_logic = int(must(probe.u32(logic + LOGIC_FRAME), "the logic frame"))
    alphas: list[float] = []
    subframes: Counter[int] = Counter()
    ratios: Counter[int] = Counter()
    seen_client = first_client
    start = time.perf_counter()
    while time.perf_counter() - start < seconds:
        now = probe.u32(client + CLIENT_FRAME)
        if now is not None and now != seen_client:
            seen_client = now
            alpha = probe.f32(engine + ENGINE_ALPHA)
            sub = probe.i32(engine + ENGINE_SUBFRAME)
            ratio = probe.i32(engine + ENGINE_RATIO)
            if alpha is not None:
                alphas.append(alpha)
            if sub is not None:
                subframes[sub] += 1
            if ratio is not None:
                ratios[ratio] += 1
    elapsed = time.perf_counter() - start
    last_client = int(must(probe.u32(client + CLIENT_FRAME), "the client frame"))
    last_logic = int(must(probe.u32(logic + LOGIC_FRAME), "the logic frame"))

    client_hz = (last_client - first_client) / elapsed
    logic_hz = (last_logic - first_logic) / elapsed
    result: dict[str, Any] = {
        "seconds": round(elapsed, 3),
        "client_frames": last_client - first_client,
        "logic_frames": last_logic - first_logic,
        "client_hz": round(client_hz, 2),
        "logic_hz": round(logic_hz, 2),
        "observed_ratio": round(client_hz / logic_hz, 3) if logic_hz else None,
        "subframes_seen": sorted(subframes),
        "alpha_min": round(min(alphas), 4) if alphas else None,
        "alpha_max": round(max(alphas), 4) if alphas else None,
        "distinct_alphas": len({round(a, 4) for a in alphas}),
        "alpha_saturated": (
            round(sum(1 for a in alphas if a >= 1.0) / len(alphas), 3) if alphas else None
        ),
        "ratios_seen": sorted(ratios),
    }
    print("\npace")
    print(f"  client {result['client_hz']} fps over {result['seconds']}s")
    print(f"  logic  {result['logic_hz']} Hz    observed ratio {result['observed_ratio']}")
    print(f"  sub-frames seen: {result['subframes_seen']}")
    print(f"  +0x38 ratio while sampling: {result['ratios_seen']}")
    print(
        f"  alpha {result['alpha_min']} .. {result['alpha_max']}"
        f" in {result['distinct_alphas']} distinct values"
    )
    saturated = result["alpha_saturated"]
    if saturated is not None:
        print(f"  alpha pinned at 1.0 on {saturated:.0%} of client frames")
        if saturated > 0.5:
            print("    ! interpolation is mostly not happening - drawables snap once per")
            print("      logic frame however many client frames are drawn between them")
    # A sweep that neither starts at 0 nor finishes at 1 leaves a discontinuity at the logic
    # frame boundary: the drawable stops short of the current position, then the matrices roll
    # over and it restarts part-way into the next segment. That gap, once per logic frame, is
    # what a stutter looks like from here - so name it rather than leaving it to be read off
    # two numbers.
    lo, hi = result["alpha_min"], result["alpha_max"]
    ratio = ratios.most_common(1)[0][0] if ratios else None
    if lo is not None and hi is not None:
        snap = (1.0 - hi) + lo
        result["snap_per_logic_frame"] = round(snap, 4)
        # The gap on its own reads worse than it looks, because a healthy build has one too: the
        # catch-up loop eats sub-frame 1, so the alpha starts at 2/ratio and the boundary frame
        # always moves double. What matters is the gap measured *against the frame either side of
        # it* - a healthy build spikes 2.0x at any rate, and anything above that is this defect.
        spike = snap * ratio if ratio else None
        result["boundary_spike"] = round(spike, 2) if spike else None
        print(
            f"  -> {snap:.0%} of each step is skipped at the logic-frame boundary,"
            f" {result['logic_hz']} times a second"
        )
        if spike:
            print(f"  -> the boundary frame moves {spike:.1f}x a normal frame (healthy is 2.0x)")
    return result


def measure_network(probe: Probe, seconds: float) -> dict:
    """Whether the alpha's denominator holds still, and what moves it when it does not.

    The interpolation alpha is `clamp(+0x34 / +0x38, 0, 1)` (`0x0063256F`), so `+0x38` is not a
    reporting field - it is the divisor every interpolated transform and every W3D animation lerp
    is scaled by. Two sites write it:

      * `0x0063260F`, the recompute, which sets it to `clientRate / logicRate`. It needs both the
        rates-changed latch at `+0x40` **and** the sub-frame index named by the imm8 at
        `0x00632606`. Stock that imm8 is 6, which occurs; the patch wrote 1, which §9.2 measured
        373 frames without ever seeing. A recompute that never runs leaves `+0x38` at the 1 the
        constructor put there (`0x0063A4DE`).

      * `0x006323D2`, `inc dword [esi+0x38]`, inside `0x0063239D`. That function returns early at
        `0x006323A6` when `[0x00DE4468]` is null, so it cannot run in single-player or in a
        replay - **only on a networked client**, and only while it is waiting on a peer.

    So the two questions this phase answers are "is `+0x38` the ratio the wrap uses" and "is it
    moving", and the second one can only ever be yes off-host. Run this on both machines during
    the same match and diff the two JSON files.
    """
    engine = probe.pointer(THE_GAME_ENGINE)
    if engine is None:
        raise SystemExit("TheGameEngine is unreadable")

    gate = probe.memory.read(RECOMPUTE_GATE_IMM, 1)
    wrap = probe.memory.read(WRAP_IMM, 1)
    if gate is None or wrap is None:
        raise SystemExit("could not read the pacing code - is this shell elevated?")
    gate_subframe, wrap_at = gate[0], wrap[0]

    net = probe.pointer(NET_OBJECT)
    ratios: list[int] = []
    seen = None
    start = time.perf_counter()
    while time.perf_counter() - start < seconds:
        ratio = probe.i32(engine + ENGINE_RATIO)
        if ratio is not None and ratio != seen:
            seen = ratio
            ratios.append(ratio)

    ratio_now = probe.i32(engine + ENGINE_RATIO)
    result = {
        "networked": net is not None,
        "net_object": f"0x{net:08X}" if net else None,
        "slowdown_scalar": probe.f32(NET_SLOWDOWN),
        "rates_changed_latch": probe.u8(engine + ENGINE_RATES_CHANGED),
        "subframe_high_water": probe.f32(engine + ENGINE_SUBFRAME_HIGH),
        "recompute_gate_subframe": gate_subframe,
        "wrap_at": wrap_at,
        "ratio": ratio_now,
        "ratio_track": ratios,
        "ratio_moved": len(set(ratios)) > 1,
        "ratio_matches_wrap": ratio_now == wrap_at,
    }

    print("\nnetwork pacing")
    print(f"  [0x00DE4468] network object : {result['net_object'] or 'null (single-player)'}")
    print(f"  [0x00D9F498] slowdown scalar: {result['slowdown_scalar']}")
    print(f"  +0x38 ratio = {ratio_now}    wrap at 0x0063264A = {wrap_at}")
    print(
        f"  recompute gate fires on sub-frame {gate_subframe}    +0x40 latch ="
        f" {result['rates_changed_latch']}"
    )
    if len(set(ratios)) > 1:
        print(f"  ! +0x38 MOVED while sampling: {ratios}")
        print("    0x006323D2 is growing it and nothing resets it - the alpha's denominator")
        print("    is drifting away from the wrap, so interpolation runs short and then snaps")
    if not result["ratio_matches_wrap"]:
        print(
            f"  ! +0x38 ({ratio_now}) disagrees with the wrap ({wrap_at}): the alpha spans"
            f" {ratio_now} sub-frames"
        )
        print(
            f"    but the logic frame spans {wrap_at}, so motion is wrong by"
            f" {wrap_at / ratio_now if ratio_now else float('inf'):.2f}x"
        )
    if gate_subframe == 1:
        print("  ! the recompute gate is sub-frame 1, which the catch-up loop at 0x00632A9B")
        print("    skips past every logic frame - so +0x38 is never restored (see 9.10)")
    return result


def object_addresses(probe: Probe) -> list[int]:
    """Every live `Object*`, from TheGameLogic's table - the walk `read_objects` uses."""
    lay = LAYOUT_ROTWK_201
    logic = probe.pointer(THE_GAME_LOGIC)
    if logic is None:
        return []
    begin = probe.pointer(logic + lay.gl_table_begin)
    end = probe.u32(logic + lay.gl_table_end)
    if begin is None or end is None or end <= begin:
        return []
    slots = min((end - begin) // 4, 16384)
    raw = probe.memory.read(begin, slots * 4)
    if raw is None:
        return []
    out = []
    for entry in struct.unpack(f"<{slots}I", raw):
        if not (0x00010000 <= entry <= 0x7FFFFFFF):
            continue
        obj = probe.pointer(entry + lay.entry_object)
        if obj is not None:
            out.append(obj)
    return out


def moving_drawables(probe: Probe) -> list[int]:
    """Drawables whose previous and current matrices differ - the ones actually in motion.

    A still drawable interpolates between two identical matrices, so its output never changes
    however often it recomputes; measuring one would report "no distinct positions" for a reason
    that has nothing to do with the frame rate.
    """
    lay = LAYOUT_ROTWK_201
    found = []
    for obj in object_addresses(probe):
        drawable = probe.pointer(obj + lay.obj_drawable)
        if drawable is None:
            continue
        previous = probe.memory.read(drawable + DRAW_PREVIOUS, MATRIX_BYTES)
        current = probe.memory.read(drawable + DRAW_CURRENT, MATRIX_BYTES)
        if previous is not None and current is not None and previous != current:
            found.append(drawable)
    return found


def measure_interpolation(probe: Probe, seconds: float) -> dict:
    """How often the interpolated transform is recomputed per logic frame.

    This is the whole value of the feature: the client rate buys smoothness only in proportion
    to how many distinct interpolated positions a drawable takes between two logic frames. It is
    measured across many drawables rather than one, because the count turns out to vary per
    drawable - most recompute far less often than the client rate would allow.
    """
    watched = moving_drawables(probe)[:WATCHED_DRAWABLES]
    if not watched:
        print("\ninterpolation\n  nothing is moving - order some units and retry")
        return {"watched": 0}

    client = probe.pointer(THE_GAME_CLIENT)
    logic = probe.pointer(THE_GAME_LOGIC)
    if client is None or logic is None:
        raise SystemExit("pacing globals are unreadable")

    stamps: dict[int, dict[int, set[int]]] = {d: {} for d in watched}
    outputs: dict[int, dict[int, set[bytes]]] = {d: {} for d in watched}
    seen = None
    frames = 0
    start = time.perf_counter()
    while time.perf_counter() - start < seconds:
        frame = probe.u32(client + CLIENT_FRAME)
        if frame is None or frame == seen:
            continue
        seen = frame
        frames += 1
        logic_frame = probe.u32(logic + LOGIC_FRAME)
        if logic_frame is None:
            continue
        for drawable in watched:
            stamp = probe.u32(drawable + DRAW_STAMP)
            matrix = probe.memory.read(drawable + DRAW_INTERPOLATED, MATRIX_BYTES)
            if stamp is not None:
                stamps[drawable].setdefault(logic_frame, set()).add(stamp)
            if matrix is not None:
                outputs[drawable].setdefault(logic_frame, set()).add(matrix)

    def peaks(per_drawable: dict[int, dict[int, set]]) -> list[int]:
        out = []
        for per_logic in per_drawable.values():
            # The first and last logic frames are partial - the sampler joined mid-frame.
            complete = sorted(per_logic)[1:-1]
            if complete:
                out.append(max(len(per_logic[k]) for k in complete))
        return out

    recomputes = peaks(stamps)
    distinct = peaks(outputs)
    histogram = Counter(recomputes)
    alive = sum(
        1
        for per_logic in stamps.values()
        for values in per_logic.values()
        if any(0 < v < 0xFFFFFFFF for v in values)
    )

    result = {
        "watched": len(watched),
        "client_frames_sampled": frames,
        "recomputes_per_logic_frame": {str(k): v for k, v in sorted(histogram.items())},
        "max_recomputes": max(recomputes) if recomputes else None,
        "median_recomputes": sorted(recomputes)[len(recomputes) // 2] if recomputes else None,
        "max_distinct_outputs": max(distinct) if distinct else None,
        "stamp_is_live": alive > 0,
    }
    print(f"\ninterpolation  ({len(watched)} moving drawables, {frames} client frames)")
    print("  recomputes per logic frame (+0x244 distinct values):")
    for count, how_many in sorted(histogram.items()):
        print(f"    {count:>2} per logic frame : {how_many} drawables")
    print(
        f"  best drawable took {result['max_distinct_outputs']} distinct positions per logic frame"
    )
    return result


def fx_entries(probe: Probe) -> list[int]:
    """The items on the list at `[0x00DC78D4]`, as `0x004655F8` walks it.

    `sentinel = list + 4`, `node = [list + 8]`, `item = [node + 0x0C]`, `next = [node + 4]`.
    """
    head = probe.pointer(FX_LIFETIME_LIST)
    if head is None:
        return []
    sentinel = head + 4
    node = probe.pointer(head + 8)
    items: list[int] = []
    while node is not None and node != sentinel and len(items) < 512:
        item = probe.pointer(node + 0x0C)
        if item is not None:
            items.append(item)
        nxt = probe.u32(node + 4)
        if nxt is None or nxt == node:
            break
        node = nxt if nxt != sentinel else None
    return items


def measure_fx(probe: Probe, seconds: float) -> dict:
    """The per-client-frame increment of a fixed-dt lifetime accumulator.

    An increment of 1/30 regardless of the client rate is the mechanism behind "FX play at
    exactly twice speed": the step is a constant, so raising the rate halves the wall-clock
    lifetime of everything on this list.
    """
    client = probe.pointer(THE_GAME_CLIENT)
    if client is None:
        raise SystemExit("TheGameClient is unreadable")
    entries = fx_entries(probe)
    if not entries:
        print("\nfx lifetimes\n  list at [0x00DC78D4] is empty - trigger an effect and retry")
        return {"entries": 0}

    tracked = entries[0]
    first_frame = probe.u32(client + CLIENT_FRAME)
    first_value = probe.f32(tracked + 0x20)
    lifetime = probe.f32(tracked + 0x18)
    readings: list[tuple[int, float]] = []
    start = time.perf_counter()
    while time.perf_counter() - start < seconds:
        frame = probe.u32(client + CLIENT_FRAME)
        value = probe.f32(tracked + 0x20)
        if frame is None or value is None:
            break
        if not readings or readings[-1][0] != frame:
            readings.append((frame, value))
        if value < (readings[0][1] if readings else 0.0):
            break  # the entry expired and its slot was reused; stop rather than average junk

    step = None
    if len(readings) > 1:
        frames = readings[-1][0] - readings[0][0]
        grew = readings[-1][1] - readings[0][1]
        step = round(grew / frames, 6) if frames else None

    result = {
        "entries": len(entries),
        "tracked": f"0x{tracked:08X}",
        "lifetime_field": lifetime,
        "first_value": first_value,
        "first_frame": first_frame,
        "samples": len(readings),
        "step_per_client_frame": step,
    }
    print(f"\nfx lifetimes  ({len(entries)} on the list, tracking {result['tracked']})")
    print(f"  +0x18 lifetime = {lifetime}   +0x20 accumulator = {first_value}")
    if step is not None:
        print(f"  step per client frame = {step:.6f}")
        print(
            f"    fixed 1/30 would be {1 / 30:.6f}; a rate-following step would be"
            f" {1 / (probe.i32(CLIENT_RATE) or 30):.6f}"
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=3.0, help="sampling window per phase")
    parser.add_argument("--json", type=Path, help="write the readings here for cross-run diffing")
    args = parser.parse_args()

    pids = find_game_processes()
    if not pids:
        raise SystemExit("no game.dat running - start a match first")
    try:
        memory = ProcessMemory(pids[0])
    except PermissionError as exc:
        raise SystemExit(f"{exc}\nrun this from an elevated shell") from exc

    probe = Probe(memory)
    print(f"attached to game.dat pid {pids[0]}\n")
    rates = describe_rates(probe)
    report = {
        "pid": pids[0],
        "rates": rates,
        "binary": describe_divergence(probe, int(rates["client_rate"])),
        "pace": measure_pace(probe, args.seconds),
        "network": measure_network(probe, args.seconds),
        "interpolation": measure_interpolation(probe, args.seconds),
        "fx": measure_fx(probe, args.seconds),
    }
    memory.close()

    if args.json:
        args.json.write_text(json.dumps(report, indent=2))
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
