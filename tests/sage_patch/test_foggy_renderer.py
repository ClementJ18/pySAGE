"""Fail-closed patching and native x86 fog submission, without a game or GPU."""

from __future__ import annotations

import struct

import pytest

from sage_patch.addresses.logic import (
    GAME_ENGINE,
    GAME_ENGINE_ALPHA,
    GAME_LOGIC_FRAME,
    GAME_LOGIC_PAUSED,
    LOGIC_FRAMES_PER_SECOND,
    THE_GAME_LOGIC,
)
from sage_patch.addresses.weather import (
    FOGGY_NATIVE_ANCHORS,
    FOGGY_NATIVE_HOOK_BYTES,
    THE_GLOBAL_WEATHER_SYSTEM,
    WEATHER_FOG_ANCHORS,
    WEATHER_FOG_ENABLE,
    WEATHER_FOG_HOOK,
    WEATHER_FOG_HOOK_BYTES,
    WEATHER_FOG_OBJECT_HOOK_BYTES,
    WEATHER_FOG_RESUME,
)
from sage_patch.patches.experimental.foggy_weather import (
    CONFIG_OFFSET,
    FOG_END,
    FOG_RGB,
    FOG_START,
    RGB_OFFSET,
    SECTION_NAME,
    STATE_OFFSET,
    FoggyWeatherPatch,
    build_code,
)
from sage_patch.pe import SHARED_SECTION_NAME
from sage_patch.utils import allocate_section, file_offset, find_section, jmp_rel32

from .synthetic import _sparse_image


def image():
    return _sparse_image(
        {
            **WEATHER_FOG_ANCHORS,
            WEATHER_FOG_HOOK: WEATHER_FOG_HOOK_BYTES,
            **WEATHER_FOG_OBJECT_HOOK_BYTES,
            **FOGGY_NATIVE_ANCHORS,
            **FOGGY_NATIVE_HOOK_BYTES,
        }
    )


def test_apply_verify_detect_and_repeat():
    data = image()
    patch = FoggyWeatherPatch()
    assert patch.author == "Ostkannit" and patch.experimental and patch.runtime_verified == "yes"
    assert patch.verify(data)
    patch.apply(data)
    assert patch.verify(data) == []
    assert isinstance(patch.detect(data), FoggyWeatherPatch)
    once = bytes(data)
    patch.apply(data)
    assert data == once


@pytest.mark.parametrize(
    "va", [WEATHER_FOG_HOOK, *WEATHER_FOG_ANCHORS, *WEATHER_FOG_OBJECT_HOOK_BYTES]
)
def test_unknown_original_bytes_fail_without_mutation(va):
    data = image()
    data[file_offset(data, va)] ^= 1
    original = bytes(data)
    with pytest.raises(ValueError):
        FoggyWeatherPatch().apply(data)
    assert data == original


@pytest.mark.parametrize("target", ["code", "rgb", "hook", "context"])
def test_damaged_patch_is_never_reapplied(target):
    data = image()
    patch = FoggyWeatherPatch()
    patch.apply(data)
    _, off, _ = find_section(data, SECTION_NAME)
    at = {
        "code": off,
        "rgb": off + CONFIG_OFFSET + 0x10,
        "hook": file_offset(data, WEATHER_FOG_HOOK),
        "context": file_offset(data, WEATHER_FOG_RESUME),
    }[target]
    data[at] ^= 1
    original = bytes(data)
    assert patch.verify(data)
    if target != "rgb":
        assert patch.detect(data) is None
    with pytest.raises(ValueError):
        patch.apply(data)
    assert data == original


def test_foreign_cave_name_is_rejected():
    data = image()
    allocate_section(data, SECTION_NAME, lambda _: b"foreign", 0x60000020)
    original = bytes(data)
    with pytest.raises(ValueError):
        FoggyWeatherPatch().apply(data)
    assert data == original


def test_dynamic_allocation_and_shared_caves():
    for shared in (False, True):
        data = image()
        first = SHARED_SECTION_NAME if shared else ".other"
        first_va = allocate_section(
            data, first, lambda _, shared=shared: b"" if shared else b"other patch", 0x60000020
        )
        patch = FoggyWeatherPatch()
        patch.apply(data)
        va, _, _ = find_section(data, SECTION_NAME)
        assert va > first_va
        allocate_section(data, ".later", lambda _: b"later patch", 0x60000020)
        assert patch.verify(data) == []


def emulator(weather, fog_enabled=0, alignment=0, hooked=True, patch=None, prime=True):
    # Keep the historical three-second fixture explicit; public defaults are tested separately.
    if patch is None:
        patch = FoggyWeatherPatch(blend_in_ms=3000, blend_out_ms=3000)
    unicorn = pytest.importorskip("unicorn")
    r = pytest.importorskip("unicorn.x86_const")

    mu = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
    cave, obj, color = 0x01500000, 0x02500000, 0x02600100
    for address, size in (
        (0x00471000, 0x1000),
        (0x00465000, 0x1000),
        (0x00DD3000, 0x1000),
        (0x00D9B000, 0x1000),
        (0x00DE7000, 0x1000),
        (0x00BD8000, 0x1000),
        (0x00BD0000, 0x1000),
        (0x00DE4000, 0x1000),
        (0x00D9F000, 0x1000),
        (cave, 0x1000),
        (0x02000000, 0x10000),
        (obj, 0x1000),
        (obj + 0x1000, 0x2000),
        (0x02600000, 0x1000),
    ):
        mu.mem_map(address, size)
    mu.mem_write(cave, build_code(cave, patch=patch))
    mu.mem_write(THE_GAME_LOGIC, struct.pack("<I", obj + 0x1000))
    mu.mem_write(GAME_ENGINE, struct.pack("<I", obj + 0x2000))
    mu.mem_write(LOGIC_FRAMES_PER_SECOND, struct.pack("<I", 5))
    mu.mem_write(0x00D9B058, struct.pack("<I", 1))
    mu.mem_write(
        WEATHER_FOG_HOOK, jmp_rel32(WEATHER_FOG_HOOK, cave) if hooked else WEATHER_FOG_HOOK_BYTES
    )
    mu.mem_write(WEATHER_FOG_RESUME, WEATHER_FOG_ANCHORS[WEATHER_FOG_RESUME])
    mu.mem_write(0x00BD88A8, struct.pack("<f", 255.0))
    mu.mem_write(THE_GLOBAL_WEATHER_SYSTEM, struct.pack("<I", obj if weather is not None else 0))
    if weather is not None:
        mu.mem_write(obj + 0x10, struct.pack("<I", weather))
    mu.mem_write(color, struct.pack("<3f", 0.2, 0.4, 0.6))
    mu.mem_write(WEATHER_FOG_ENABLE, b"\xaa")
    gprs = [
        r.UC_X86_REG_EAX,
        r.UC_X86_REG_EBX,
        r.UC_X86_REG_ECX,
        r.UC_X86_REG_EDX,
        r.UC_X86_REG_ESI,
        r.UC_X86_REG_EDI,
        r.UC_X86_REG_EBP,
        r.UC_X86_REG_ESP,
    ]
    for i, reg in enumerate(gprs):
        mu.reg_write(reg, 0x12345000 + i * 0x100)
    mu.reg_write(r.UC_X86_REG_EAX, 0x12345600 | fog_enabled)
    ebp = 0x02009000
    mu.reg_write(r.UC_X86_REG_EBP, ebp)
    mu.reg_write(r.UC_X86_REG_ESP, ebp - 0x80 + alignment)
    mu.mem_write(ebp - 0x40, b"\xa5" * 0x40)
    mu.mem_write(ebp - 0x18, struct.pack("<ffI", 2000.0, 725.0, color))
    mu.mem_write(ebp - 8, struct.pack("<f", 0.0))
    xmm = [getattr(r, f"UC_X86_REG_XMM{i}") for i in range(8)]
    for i, reg in enumerate(xmm):
        low = struct.unpack("<I", struct.pack("<f", 2000.0 if i == 0 else 725.0))[0]
        mu.reg_write(reg, ((0x112233445566778899AABB00 + i) << 32) | low)
    # Native RGB conversion needs XMM2.low == 255, as set immediately before the hook.
    mu.reg_write(xmm[2], struct.unpack("<I", struct.pack("<f", 255.0))[0])
    mu.reg_write(r.UC_X86_REG_FPCW, 0x027F)
    mu.reg_write(r.UC_X86_REG_FPTAG, 0xFFFF)
    mu.reg_write(r.UC_X86_REG_MXCSR, 0x1F80)
    mu.mem_write(0x00465A00, b"\xd9\xe8\xd9\xeb")  # seed two live x87 registers
    mu.emu_start(0x00465A00, 0x00465A04)
    mu.reg_write(r.UC_X86_REG_EFLAGS, 0xCD7)
    state = [
        *gprs,
        *xmm,
        r.UC_X86_REG_EFLAGS,
        r.UC_X86_REG_FPCW,
        r.UC_X86_REG_FPSW,
        r.UC_X86_REG_FPTAG,
        r.UC_X86_REG_MXCSR,
        r.UC_X86_REG_ST0,
        r.UC_X86_REG_ST1,
    ]
    if prime and weather == 6 and hooked:
        mu.emu_start(WEATHER_FOG_HOOK, WEATHER_FOG_RESUME, count=1000)
        frames = (patch.blend_in_ms * 5 + 999) // 1000
        mu.mem_write(obj + 0x1000 + GAME_LOGIC_FRAME, struct.pack("<I", frames))
    return mu, r, state, ebp, cave, color


@pytest.mark.parametrize("weather", [None, 0, 1, 2, 3, 4, 5, 6, 0x101, 0xFFFFFFFF])
@pytest.mark.parametrize("fog_enabled", [0, 1, 0x7F])
@pytest.mark.parametrize("alignment", [0, 1, 7, 15])
def test_hook_preserves_machine_state_and_only_changes_foggy_fog(weather, fog_enabled, alignment):
    mu, r, registers, ebp, cave, color = emulator(weather, fog_enabled, alignment)
    before = {reg: mu.reg_read(reg) for reg in registers}
    locals_before = bytes(mu.mem_read(ebp - 0x40, 0x40))
    mu.emu_start(WEATHER_FOG_HOOK, WEATHER_FOG_RESUME, count=1000)
    assert mu.reg_read(r.UC_X86_REG_EIP) == WEATHER_FOG_RESUME
    foggy = weather == 6
    expected = dict(before)
    if foggy:
        expected[r.UC_X86_REG_EAX] = (before[r.UC_X86_REG_EAX] & ~0xFF) | 1
        for reg, value in ((r.UC_X86_REG_XMM0, FOG_END), (r.UC_X86_REG_XMM1, FOG_START)):
            low = struct.unpack("<I", struct.pack("<f", value))[0]
            expected[reg] = (before[reg] & ~0xFFFFFFFF) | low
    assert {reg: mu.reg_read(reg) for reg in registers} == expected
    assert mu.mem_read(WEATHER_FOG_ENABLE, 1) == bytes([1 if foggy else fog_enabled])
    locals_expected = bytearray(locals_before)
    if foggy:
        struct.pack_into("<ffI", locals_expected, 0x28, FOG_END, FOG_START, cave + RGB_OFFSET)
    assert mu.mem_read(ebp - 0x40, 0x40) == locals_expected
    assert mu.mem_read(color, 12) == struct.pack("<3f", 0.2, 0.4, 0.6)


@pytest.mark.parametrize("weather", [None, 0, 1, 2, 3, 4, 5, 6])
def test_native_continuation_receives_consistent_color_and_ranges(weather):
    outputs = []
    for hooked in (False, True):
        mu, r, _, ebp, _, _ = emulator(weather, hooked=hooked)
        calls = []
        unicorn = pytest.importorskip("unicorn")

        def submit(uc, address, size, user, r=r, calls=calls):
            if address == 0x00465904:
                esp = uc.reg_read(r.UC_X86_REG_ESP)
                calls.append(struct.unpack("<II", uc.mem_read(esp + 4, 8)))

        mu.mem_write(0x00465904, b"\xc3")  # cdecl renderer submission stub
        mu.hook_add(unicorn.UC_HOOK_CODE, submit)
        esp_before = mu.reg_read(r.UC_X86_REG_ESP)
        mu.emu_start(WEATHER_FOG_HOOK, 0x004719CD, count=1000)
        assert mu.reg_read(r.UC_X86_REG_EIP) == 0x004719CD
        assert mu.reg_read(r.UC_X86_REG_ESP) == esp_before - 16  # native caller cleans next
        assert mu.mem_read(ebp - 0x1C, 4) == b"\xa5" * 4
        outputs.append((bytes(mu.mem_read(WEATHER_FOG_ENABLE, 15)), calls))
    if weather != 6:
        assert outputs[0] == outputs[1]
    else:
        globals_after, calls = outputs[1]
        rgb = struct.unpack("<3f", struct.pack("<3f", *FOG_RGB))
        packed = sum(
            int(channel * 255) << shift for channel, shift in zip(rgb, (16, 8, 0), strict=True)
        )
        assert struct.unpack_from("<Iff", globals_after, 3) == (packed, FOG_START, FOG_END)

        def bits(value):
            return struct.unpack("<I", struct.pack("<f", value))[0]

        assert calls == [(36, bits(FOG_START)), (37, bits(FOG_END))]


class FogHarness:
    def __init__(self, enabled=0, start=300.0, end=5000.0, patch=None, rate=5):
        self.mu, self.r, self.registers, self.ebp, self.cave, self.color = emulator(
            0, enabled, patch=patch, prime=False
        )
        self.enabled, self.start, self.end = enabled, start, end
        self.rate = rate
        self.weather_ptr, self.logic_ptr, self.engine_ptr = 0x02500000, 0x02501000, 0x02502000
        self.mu.mem_write(LOGIC_FRAMES_PER_SECOND, struct.pack("<I", rate))

    def draw(self, ms, weather=6, paused=False, fraction=None):
        frame = ms * self.rate / 1000
        return self.draw_frame(
            int(frame) & 0xFFFFFFFF,
            frame - int(frame) if fraction is None else fraction,
            weather,
            paused,
        )

    def draw_frame(self, frame, fraction=0.0, weather=6, paused=False):
        mu, r = self.mu, self.r
        mu.mem_write(
            THE_GLOBAL_WEATHER_SYSTEM,
            struct.pack("<I", 0 if weather is None else self.weather_ptr),
        )
        if weather is not None:
            mu.mem_write(self.weather_ptr + 0x10, struct.pack("<I", weather))
        mu.mem_write(self.logic_ptr + GAME_LOGIC_FRAME, struct.pack("<I", frame))
        mu.mem_write(self.logic_ptr + GAME_LOGIC_PAUSED, bytes([int(paused)]))
        mu.mem_write(self.engine_ptr + GAME_ENGINE_ALPHA, struct.pack("<f", fraction))
        # Native scene setup runs again on every render pass; no overridden output is
        # fed back into the next pass's original endpoint.
        mu.mem_write(self.ebp - 0x18, struct.pack("<ffI", self.end, self.start, self.color))
        mu.reg_write(r.UC_X86_REG_EAX, 0x12345600 | self.enabled)
        for reg, value in ((r.UC_X86_REG_XMM0, self.end), (r.UC_X86_REG_XMM1, self.start)):
            bits = struct.unpack("<I", struct.pack("<f", value))[0]
            mu.reg_write(reg, (mu.reg_read(reg) & ~0xFFFFFFFF) | bits)
        mu.emu_start(WEATHER_FOG_HOOK, WEATHER_FOG_RESUME, count=1000)
        assert mu.reg_read(r.UC_X86_REG_EIP) == WEATHER_FOG_RESUME
        end, start, rgb = struct.unpack("<ffI", mu.mem_read(self.ebp - 0x18, 12))
        phase, weight = struct.unpack("<ff", mu.mem_read(self.cave + STATE_OFFSET + 0x14, 8))
        return {
            "phase": phase,
            "weight": weight,
            "enable": mu.mem_read(WEATHER_FOG_ENABLE, 1)[0],
            "start": start,
            "end": end,
            "rgb": struct.unpack("<3f", mu.mem_read(rgb, 12)),
        }


@pytest.mark.parametrize("enabled", [0, 1])
def test_smoothstep_in_and_out_recover_the_original_scene(enabled):
    h = FogHarness(enabled)
    initial = h.draw(0, 0)
    assert h.draw(0, 6) == initial
    quarter, half, full = h.draw(750), h.draw(1500), h.draw(3000)
    assert quarter["weight"] == pytest.approx(0.15625)
    assert half["weight"] == pytest.approx(0.5)
    assert full["phase"] == full["weight"] == 1
    assert (full["start"], full["end"]) == (FOG_START, FOG_END)
    assert full["rgb"] == pytest.approx(FOG_RGB)
    assert h.draw(3000, 0) == full  # direction change retains the current visible output
    assert h.draw(4500, 0)["weight"] == pytest.approx(0.5)
    assert h.draw(6000, 0) == initial
    assert h.draw(600000, 0) == initial
    assert h.mu.mem_read(h.color, 12) == struct.pack("<3f", 0.2, 0.4, 0.6)


def test_enabled_original_fog_lerps_both_ranges_and_color():
    h = FogHarness(1, 300.0, 5000.0)
    h.draw(0)
    sample = h.draw(1500)
    assert sample["start"] == pytest.approx((300 + FOG_START) / 2)
    assert sample["end"] == pytest.approx((5000 + FOG_END) / 2)
    assert sample["rgb"] == pytest.approx(
        tuple((a + b) / 2 for a, b in zip((0.2, 0.4, 0.6), FOG_RGB, strict=True))
    )


@pytest.mark.parametrize("start,end", [(0, 0), (-100, -200), (float("nan"), float("inf"))])
def test_disabled_original_range_is_ignored_and_fog_density_grows_gradually(start, end):
    h = FogHarness(0, start, end)
    h.draw(0)
    for ms in (1, 10, 100, 750, 1500, 2250, 3000):
        sample = h.draw(ms)
        weight = sample["weight"]
        assert sample["start"] == FOG_START
        assert sample["end"] == pytest.approx(FOG_START + (FOG_END - FOG_START) / weight)
        # At a point halfway through the target ramp the fog contribution is alpha/2.
        distance = (FOG_START + FOG_END) / 2
        density = (distance - sample["start"]) / (sample["end"] - sample["start"])
        assert density == pytest.approx(weight / 2, rel=2e-5)


def test_reversing_a_partial_fade_has_no_jump_in_either_direction():
    h = FogHarness()
    h.draw(0)
    incoming = h.draw(1000)
    assert h.draw(1000, 0) == incoming
    outgoing = h.draw(1300, 0)
    assert outgoing["phase"] < incoming["phase"]
    assert h.draw(1300, 6) == outgoing
    assert h.draw(1600, 6)["phase"] > outgoing["phase"]
    assert h.draw(5000, 6)["phase"] == 1


@pytest.mark.parametrize("fps", [15, 30, 60, 144, 635])
def test_render_rate_and_repeated_passes_do_not_change_logical_duration(fps):
    h = FogHarness()
    h.draw(0)
    for tick in range(1, int(1.5 * fps) + 1):
        sample = h.draw(1000 * tick / fps)
        assert h.draw(1000 * tick / fps) == sample
    sample = h.draw(1500)
    assert sample["phase"] == pytest.approx(0.5, abs=2e-6)
    assert h.draw(3000)["phase"] == 1


def test_pause_freezes_the_blend_even_when_render_alpha_changes():
    h = FogHarness()
    h.draw(0)
    before = h.draw(1000)
    for _ in range(20):
        for alpha in (0.1, 0.2, 0.8, 1.0, 0.0):
            assert h.draw(1000, paused=True, fraction=alpha) == before
    assert h.draw(1000, paused=False) == before
    assert h.draw(1200)["phase"] > before["phase"]


def test_recomputed_subframe_fraction_cannot_spend_a_logic_tick_twice():
    h = FogHarness()
    h.draw_frame(0)
    before = h.draw_frame(0, 0.8)
    for _ in range(20):
        for alpha in (0.0, 0.1, 0.5, 0.8):
            assert h.draw_frame(0, alpha) == before
    assert h.draw_frame(1, 0.1)["phase"] == pytest.approx(1.1 / 15)


@pytest.mark.parametrize("rate", [5, 10, 30])
def test_the_live_logic_rate_converts_frames_to_simulation_milliseconds(rate):
    h = FogHarness(rate=rate)
    h.draw(0)
    assert h.draw(1500)["phase"] == pytest.approx(0.5)
    assert h.draw(3000)["phase"] == 1


def test_missing_render_engine_falls_back_to_logic_steps():
    h = FogHarness()
    h.mu.mem_write(GAME_ENGINE, bytes(4))
    h.draw_frame(0)
    assert h.draw_frame(7)["phase"] == pytest.approx(7 / 15)
    assert h.draw_frame(15)["phase"] == 1


def test_unsigned_logic_wrap_and_load_time_reset():
    h = FogHarness()
    h.draw_frame(0xFFFFFFFC)
    assert h.draw_frame(3)["phase"] == pytest.approx(7 / 15)
    assert h.draw_frame(11)["phase"] == 1
    assert h.draw_frame(0)["phase"] == 0  # load/new logical epoch


def test_absent_simulation_or_weather_clears_private_state_and_restores_original():
    h = FogHarness()
    h.draw(0)
    assert h.draw(1000)["weight"] > 0
    assert h.draw(1000, None)["enable"] == 0
    assert h.draw(1200)["weight"] == 0
    h.draw(2200)
    h.mu.mem_write(THE_GAME_LOGIC, bytes(4))
    assert h.draw(2200)["weight"] == 0


@pytest.mark.parametrize("projection,lod", [(1, 1), (0, 0), (0, -1)])
def test_native_projection_and_lod_gates_are_kept(projection, lod):
    h = FogHarness()
    h.mu.mem_write(0x00DD3445, bytes([projection]))
    h.mu.mem_write(0x00D9B058, struct.pack("<i", lod))
    assert h.draw(0)["enable"] == 0
    assert h.draw(3000)["weight"] == 0


def test_custom_durations_profile_and_manifest_detection():
    patch = FoggyWeatherPatch(1000, 5000, 800, 2400, (0.5, 0.6, 0.7))
    h = FogHarness(patch=patch)
    h.draw(0)
    assert h.draw(500)["weight"] == pytest.approx(0.5)
    assert h.draw(1000)["end"] == 2400
    h.draw(1000, 0)
    assert h.draw(3500, 0)["weight"] == pytest.approx(0.5)
    assert h.draw(6000, 0)["enable"] == 0
    data = image()
    patch.apply(data)
    detected = patch.detect(data)
    assert detected is not None and detected.options() == patch.options()
    with pytest.raises(ValueError):
        FoggyWeatherPatch().apply(data)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"blend_in_ms": 0},
        {"blend_out_ms": True},
        {"blend_in_ms": 600001},
        {"fog_start": 4000, "fog_end": 1000},
        {"fog_end": float("inf")},
        {"fog_rgb": (0, 1, 2)},
        {"fog_rgb": (0, 1)},
    ],
)
def test_invalid_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        FoggyWeatherPatch(**kwargs)


def test_the_cave_contains_no_calls_or_os_timers():
    capstone = pytest.importorskip("capstone")
    cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    instructions = list(cs.disasm(build_code(0x01500000)[:CONFIG_OFFSET], 0x01500000))
    assert not any(i.mnemonic == "call" for i in instructions)
    assert sum(i.size for i in instructions) == CONFIG_OFFSET


def test_mutable_runtime_output_is_not_misidentified_as_code_damage():
    data = image()
    patch = FoggyWeatherPatch()
    patch.apply(data)
    _, off, _ = find_section(data, SECTION_NAME)
    data[off + RGB_OFFSET] ^= 1
    assert patch.verify(data) == []
    before = bytes(data)
    patch.apply(data)
    assert data == before


@pytest.mark.parametrize("enabled", [0, 1])
def test_a_partial_blend_preserves_flags_registers_and_floating_point_state(enabled):
    h = FogHarness(enabled)
    h.draw(0)
    h.mu.reg_write(h.r.UC_X86_REG_MXCSR, 0x7FA0)
    h.mu.reg_write(h.r.UC_X86_REG_FPCW, 0x077F)
    before = {reg: h.mu.reg_read(reg) for reg in h.registers}
    sample = h.draw(1500)
    expected = dict(before)
    expected[h.r.UC_X86_REG_EAX] = (expected[h.r.UC_X86_REG_EAX] & ~0xFF) | 1
    for reg, value in (
        (h.r.UC_X86_REG_XMM0, sample["end"]),
        (h.r.UC_X86_REG_XMM1, sample["start"]),
    ):
        bits = struct.unpack("<I", struct.pack("<f", value))[0]
        expected[reg] = (expected[reg] & ~0xFFFFFFFF) | bits
    assert {reg: h.mu.reg_read(reg) for reg in h.registers} == expected
    assert h.mu.mem_read(h.ebp - 0x1C, 4) == b"\xa5" * 4


def test_partial_native_submission_uses_the_same_ranges_as_the_cache():
    h = FogHarness(1)
    h.draw(0)
    sample = h.draw(1500)
    calls = []
    unicorn = pytest.importorskip("unicorn")

    def submit(mu, address, size, user):
        esp = mu.reg_read(h.r.UC_X86_REG_ESP)
        calls.append(struct.unpack("<II", mu.mem_read(esp + 4, 8)))

    h.mu.mem_write(0x00465904, b"\xc3")
    h.mu.hook_add(unicorn.UC_HOOK_CODE, submit, begin=0x00465904, end=0x00465904)
    h.mu.emu_start(WEATHER_FOG_RESUME, 0x004719CD, count=300)
    assert h.mu.reg_read(h.r.UC_X86_REG_EIP) == 0x004719CD
    cached = struct.unpack("<ff", h.mu.mem_read(0x00DD3468, 8))
    assert cached == (sample["start"], sample["end"])
    for (state, bits), value in zip(calls, cached, strict=True):
        assert state in (36, 37)
        assert struct.unpack("<f", struct.pack("<I", bits))[0] == value


def test_long_custom_fade_does_not_accumulate_render_rate_error():
    h = FogHarness(patch=FoggyWeatherPatch(600000, 600000))
    h.draw(0)
    for tick in range(1, 3001):
        sample = h.draw(tick * 1000 / 635)
    assert sample["phase"] == pytest.approx((3000 / 635) / 600, abs=1e-8)


def test_foreign_v1_cave_is_rejected_without_a_second_hook():
    data = image()
    va = allocate_section(data, SECTION_NAME, lambda _: b"\x90" * 140, 0x60000060)
    off = file_offset(data, WEATHER_FOG_HOOK)
    data[off : off + 5] = jmp_rel32(WEATHER_FOG_HOOK, va)
    original = bytes(data)
    with pytest.raises(ValueError, match="clean backup"):
        FoggyWeatherPatch().apply(data)
    assert data == original


@pytest.mark.parametrize("hook", WEATHER_FOG_OBJECT_HOOK_BYTES)
def test_damaged_object_hook_is_rejected_atomically(hook):
    data = image()
    patch = FoggyWeatherPatch()
    patch.apply(data)
    data[file_offset(data, hook)] ^= 1
    original = bytes(data)
    assert patch.verify(data)
    assert patch.detect(data) is None
    with pytest.raises(ValueError, match="clean backup"):
        patch.apply(data)
    assert data == original


def test_v2_cave_requires_a_clean_rebuild():
    data = image()
    payload = bytearray(0x6C0)
    payload[0x600:0x608] = b"CLDFOG2\0"
    va = allocate_section(data, SECTION_NAME, lambda _: bytes(payload), 0xE0000060)
    off = file_offset(data, WEATHER_FOG_HOOK)
    data[off : off + 5] = jmp_rel32(WEATHER_FOG_HOOK, va)
    original = bytes(data)
    patch = FoggyWeatherPatch()
    assert patch.detect(data) is None
    with pytest.raises(ValueError, match="clean backup"):
        patch.apply(data)
    assert data == original
