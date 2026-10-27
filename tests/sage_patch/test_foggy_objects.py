"""Execute the native RotWK object-color and blend-aware mesh fog paths, without a GPU."""

from __future__ import annotations

import struct

import pytest

from sage_patch.addresses.weather import (
    WEATHER_FOG_ANCHORS,
    WEATHER_FOG_ENABLE,
    WEATHER_FOG_GHOST_RGB_HOOK,
    WEATHER_FOG_MESH_GATE_HOOK,
    WEATHER_FOG_OBJECT_HOOK_BYTES,
    WEATHER_FOG_OBJECT_RGB_HOOK,
    WEATHER_FOG_RESUME,
    WEATHER_FOG_SCENE_EXIT_HOOK,
    WEATHER_FOG_SCENE_RGB_HOOK,
)
from sage_patch.patches.experimental.foggy_weather import STATE_OFFSET, build_hooks

from .test_foggy_renderer import FogHarness


def renderer():
    h = FogHarness()
    for va, size in (
        (0x46F000, 0x1000),
        (0x537000, 0x1000),
        (0x546000, 0x2000),
        (0x54A000, 0x2000),
        (0xDD9000, 0x1000),
    ):
        h.mu.mem_map(va, size)
    for va, raw in WEATHER_FOG_ANCHORS.items():
        if (
            0x46F000 <= va < 0x470000
            or 0x537000 <= va < 0x538000
            or 0x546000 <= va < 0x548000
            or 0x54A000 <= va < 0x54C000
        ):
            h.mu.mem_write(va, raw)
    for va, raw in build_hooks(h.cave).items():
        h.mu.mem_write(va, raw)
    return h


@pytest.mark.parametrize(
    "hook", [WEATHER_FOG_SCENE_RGB_HOOK, WEATHER_FOG_OBJECT_RGB_HOOK, WEATHER_FOG_GHOST_RGB_HOOK]
)
@pytest.mark.parametrize("ms", [0, 1, 1500, 3000])
@pytest.mark.parametrize("global_enable", [0, 1])
def test_object_color_matches_the_current_terrain_blend_with_native_abi(hook, ms, global_enable):
    h = renderer()
    h.draw(0)
    sample = h.draw(ms)
    h.mu.mem_write(WEATHER_FOG_ENABLE, bytes([global_enable]))
    scene, rinfo = h.color + 0x100, h.color + 0x200
    original = struct.pack("<3f", 0.15, 0.3, 0.45)
    h.mu.mem_write(scene + 0x20, original)
    h.mu.mem_write(rinfo, b"\xa5" * 0x40)
    h.mu.reg_write(h.r.UC_X86_REG_ESI, scene)
    h.mu.reg_write(h.r.UC_X86_REG_EDI, scene)
    h.mu.reg_write(h.r.UC_X86_REG_EAX, rinfo)
    before = {reg: h.mu.reg_read(reg) for reg in h.registers}
    expected = dict(before)
    rgb = struct.pack("<3f", *sample["rgb"]) if ms > 0 and global_enable else original
    if hook == WEATHER_FOG_GHOST_RGB_HOOK:
        for reg, offset in (
            (h.r.UC_X86_REG_XMM0, 8),
            (h.r.UC_X86_REG_XMM1, 4),
            (h.r.UC_X86_REG_XMM2, 0),
        ):
            expected[reg] = struct.unpack_from("<I", rgb, offset)[0]
    else:
        expected[h.r.UC_X86_REG_ECX] = struct.unpack_from("<I", rgb, 8)[0]
    resume = hook + len(WEATHER_FOG_OBJECT_HOOK_BYTES[hook])
    h.mu.emu_start(hook, resume, count=100)
    assert h.mu.reg_read(h.r.UC_X86_REG_EIP) == resume
    assert {reg: h.mu.reg_read(reg) for reg in h.registers} == expected
    assert h.mu.mem_read(scene + 0x20, 12) == original
    assert h.mu.mem_read(WEATHER_FOG_ENABLE, 1) == bytes([global_enable])
    if hook != WEATHER_FOG_GHOST_RGB_HOOK:
        assert h.mu.mem_read(rinfo + 8, 12) == rgb
        assert h.mu.mem_read(rinfo, 8) == b"\xa5" * 8
        assert h.mu.mem_read(rinfo + 20, 0x2C) == b"\xa5" * 0x2C
    else:
        # Continue through the actual shroud-ghost multiplication and all stores.
        h.mu.mem_write(h.ebp - 0x14, struct.pack("<f", 0.4))
        h.mu.emu_start(resume, 0x46FA9A, count=30)
        actual = struct.unpack("<3f", h.mu.mem_read(rinfo + 8, 12))
        assert actual == pytest.approx([v * 0.4 for v in struct.unpack("<3f", rgb)])


def shader_bits(source, destination, fog=0):
    return (source << 14) | (destination << 5) | (fog << 8) | (1 << 18) | 0x100B


def run_mesh_gate(h, bits, hardware_fog, active, global_enable=1):
    unicorn = pytest.importorskip("unicorn")
    mesh = h.color + 0x300
    esp = h.mu.reg_read(h.r.UC_X86_REG_ESP)
    h.mu.reg_write(h.r.UC_X86_REG_EBP, mesh)
    h.mu.reg_write(h.r.UC_X86_REG_EAX, bits)
    h.mu.mem_write(esp + 0x1C, struct.pack("<I", bits))
    h.mu.mem_write(mesh + 0xBD, bytes([hardware_fog]))
    h.mu.mem_write(h.cave + STATE_OFFSET + 0x3C, struct.pack("<I", active))
    h.mu.mem_write(WEATHER_FOG_ENABLE, bytes([global_enable]))
    before = {reg: h.mu.reg_read(reg) for reg in h.registers}

    def stop_at_selection(mu, va, size, user):
        if va in (0x546C61, 0x546CA9):
            mu.emu_stop()

    handle = h.mu.hook_add(unicorn.UC_HOOK_CODE, stop_at_selection)
    try:
        h.mu.emu_start(0x546C2A, 0x546CAA, count=100)
    finally:
        h.mu.hook_del(handle)
    assert h.mu.reg_read(h.r.UC_X86_REG_EIP) in (0x546C61, 0x546CA9)
    assert h.mu.reg_read(h.r.UC_X86_REG_ESP) == esp
    assert h.mu.mem_read(mesh + 0xBD, 1) == bytes([hardware_fog])
    assert h.mu.mem_read(WEATHER_FOG_ENABLE, 1) == bytes([global_enable])
    for reg in h.registers:
        if reg not in (
            h.r.UC_X86_REG_EAX,
            h.r.UC_X86_REG_EDX,
            h.r.UC_X86_REG_ECX,
            h.r.UC_X86_REG_EFLAGS,
        ):
            assert h.mu.reg_read(reg) == before[reg]
    return h.mu.reg_read(h.r.UC_X86_REG_EAX)


@pytest.mark.parametrize("hardware_fog", [0, 1])
@pytest.mark.parametrize("active", [0, 1])
@pytest.mark.parametrize("fog", [0, 1, 2, 3])
@pytest.mark.parametrize(
    "source,destination,selected_fog",
    [(1, 0, 1), (2, 5, 1), (3, 4, 1), (1, 1, 2), (1, 3, 2), (0, 2, 3), (2, 1, 0)],
    ids=["opaque", "alpha", "inverse-alpha", "additive", "screen", "multiply", "unsupported"],
)
def test_native_mesh_selection_respects_blending_and_alpha_test(
    hardware_fog, active, fog, source, destination, selected_fog
):
    h = renderer()
    bits = shader_bits(source, destination, fog)
    actual = run_mesh_gate(h, bits, hardware_fog, active)
    expected_fog = (fog or selected_fog) if active or hardware_fog else 0
    assert actual == (bits & ~0x300) | (expected_fog << 8)


def test_native_global_disable_still_skips_mesh_fog_and_keeps_the_shader():
    h = renderer()
    bits = shader_bits(1, 0, 0)
    assert run_mesh_gate(h, bits, hardware_fog=0, active=1, global_enable=0) == bits


@pytest.mark.parametrize("fog,color", [(0, None), (1, 0xB2C1CC), (2, 0), (3, 0xFFFFFF)])
@pytest.mark.parametrize("enable,caps", [(0, 1), (1, 0), (1, 1)])
def test_native_shader_submits_material_correct_fog_renderstates(fog, color, enable, caps):
    h = renderer()
    unicorn = pytest.importorskip("unicorn")
    device_caps, shader = h.color + 0x400, h.color + 0x800
    h.mu.mem_write(0xDD34BC, struct.pack("<I", device_caps))
    h.mu.mem_write(device_caps + 0x2AC, bytes([caps]))
    h.mu.mem_write(shader, struct.pack("<I", shader_bits(1, 0, fog)))
    h.mu.reg_write(h.r.UC_X86_REG_EBP, shader)
    h.mu.reg_write(h.r.UC_X86_REG_EBX, 0)
    h.mu.mem_write(WEATHER_FOG_ENABLE, bytes([enable]))
    h.mu.mem_write(0xDD3464, struct.pack("<I", 0xB2C1CC))
    esp = h.mu.reg_read(h.r.UC_X86_REG_ESP)
    h.mu.mem_write(esp + 0x20, struct.pack("<I", 0x300))
    h.mu.mem_write(0x465904, b"\xc3")
    calls = []

    def submitted(mu, va, size, user):
        stack = mu.reg_read(h.r.UC_X86_REG_ESP)
        calls.append(struct.unpack("<II", mu.mem_read(stack + 4, 8)))

    h.mu.hook_add(unicorn.UC_HOOK_CODE, submitted, begin=0x465904, end=0x465904)
    h.mu.emu_start(0x5371D5, 0x537246, count=100)
    expected = [(28, 1), (34, color)] if enable and caps and fog else [(28, 0)]
    assert calls == expected
    assert h.mu.reg_read(h.r.UC_X86_REG_ESP) == esp


def test_scene_exit_clears_only_private_override_and_preserves_the_return_abi():
    h = renderer()
    h.draw(0)
    h.draw(3000)
    ebp, esp = h.ebp, h.mu.reg_read(h.r.UC_X86_REG_ESP)
    h.mu.mem_write(esp, struct.pack("<III", 0x11, 0x22, 0x33))
    h.mu.mem_write(ebp, struct.pack("<III", 0x44, 0x465A04, 0x55))
    before = {reg: h.mu.reg_read(reg) for reg in h.registers}
    cached = bytes(h.mu.mem_read(WEATHER_FOG_ENABLE, 15))
    h.mu.emu_start(WEATHER_FOG_SCENE_EXIT_HOOK, 0x465A04, count=30)
    expected = dict(before)
    for reg, value in (
        (h.r.UC_X86_REG_EDI, 0x11),
        (h.r.UC_X86_REG_ESI, 0x22),
        (h.r.UC_X86_REG_EBX, 0x33),
        (h.r.UC_X86_REG_EBP, 0x44),
        (h.r.UC_X86_REG_ESP, ebp + 12),
    ):
        expected[reg] = value
    assert {reg: h.mu.reg_read(reg) for reg in h.registers} == expected
    assert h.mu.mem_read(h.cave + STATE_OFFSET + 0x3C, 4) == b"\0" * 4
    assert h.mu.mem_read(WEATHER_FOG_ENABLE, 15) == cached
    # A later draw outside the scene respects the original per-mesh opt-out.
    assert run_mesh_gate(h, shader_bits(1, 0, 1), hardware_fog=0, active=0) & 0x300 == 0


@pytest.mark.parametrize("ms", [0, 1500, 3000])
@pytest.mark.parametrize("hook", [WEATHER_FOG_OBJECT_RGB_HOOK, WEATHER_FOG_SCENE_RGB_HOOK])
def test_native_scene_to_renderinfo_mesh_and_fx_color_agree(ms, hook):
    outputs = []
    for patched in (False, True):
        h = renderer()
        h.draw(0)
        h.draw(ms)
        # Execute the actual terrain/global fog submission first.
        h.mu.mem_write(0x465904, b"\xc3")
        h.mu.emu_start(WEATHER_FOG_RESUME, 0x4719CD, count=300)
        global_color = bytes(h.mu.mem_read(0xDD3464, 4))
        ranges = bytes(h.mu.mem_read(0xDD3468, 8))
        enable = bytes(h.mu.mem_read(WEATHER_FOG_ENABLE, 1))
        scene, rinfo, mesh = h.color + 0x100, h.color + 0x200, h.color + 0x300
        h.mu.mem_write(scene + 0x20, struct.pack("<3f", 0.2, 0.4, 0.6))
        h.mu.reg_write(h.r.UC_X86_REG_ESI, scene)
        h.mu.reg_write(h.r.UC_X86_REG_EDI, scene)
        h.mu.reg_write(h.r.UC_X86_REG_EAX, rinfo)
        if not patched:
            h.mu.mem_write(hook, WEATHER_FOG_OBJECT_HOOK_BYTES[hook])
        h.mu.emu_start(hook, hook + len(WEATHER_FOG_OBJECT_HOOK_BYTES[hook]), count=100)
        # MeshClass::Render copies RenderInfo fog RGB into Mesh+314.
        h.mu.reg_write(h.r.UC_X86_REG_EBX, rinfo)
        h.mu.reg_write(h.r.UC_X86_REG_ESI, mesh)
        h.mu.emu_start(0x54B6E4, 0x54B714, count=30)
        # FX prepare temporarily replaces the shared color with this mesh's RGB.
        h.mu.mem_write(h.ebp - 0x14, struct.pack("<I", mesh))
        h.mu.emu_start(0x54A0C9, 0x54A1B6, count=200)
        mesh_color = bytes(h.mu.mem_read(0xDD3464, 4))
        assert h.mu.mem_read(0xDD90EC, 4) == global_color
        assert h.mu.mem_read(0xDD3468, 8) == ranges
        assert h.mu.mem_read(WEATHER_FOG_ENABLE, 1) == enable
        outputs.append((global_color, mesh_color))
    if ms:
        assert outputs[0][0] != outputs[0][1]  # reproduce the pre-fix color mismatch
        assert outputs[1][0] == outputs[1][1]
    else:
        assert outputs[0] == outputs[1]


def test_foggy_mesh_gate_does_not_touch_registers_flags_or_floating_point_state():
    h = renderer()
    h.draw(0)
    h.draw(1500)
    before = {reg: h.mu.reg_read(reg) for reg in h.registers}
    h.mu.emu_start(WEATHER_FOG_MESH_GATE_HOOK, 0x546C3C, count=50)
    assert h.mu.reg_read(h.r.UC_X86_REG_EIP) == 0x546C3C
    assert {reg: h.mu.reg_read(reg) for reg in h.registers} == before
