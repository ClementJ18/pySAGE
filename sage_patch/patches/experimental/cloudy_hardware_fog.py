"""Client-local hardware fog shared by the experimental CLOUDY and FOGGY patches.

RTS3DScene's native Set_Fog submission and object color/material routing are detoured.
The logical GameLogic frame and render interpolation drive the reversible smoothstep blend.
Derivation: docs/cloudy-hardware-fog.md.
"""

from __future__ import annotations

import argparse
import math
import struct
from typing import Self

from sage_patch.addresses.logic import (
    GAME_ENGINE,
    GAME_ENGINE_ALPHA,
    GAME_LOGIC_FRAME,
    GAME_LOGIC_PAUSED,
    LOGIC_FRAMES_PER_SECOND,
    THE_GAME_LOGIC,
)
from sage_patch.addresses.weather import (
    GLOBAL_WEATHER_CLOUDY,
    GLOBAL_WEATHER_CURRENT,
    THE_GLOBAL_WEATHER_SYSTEM,
    WEATHER_FOG_ANCHORS,
    WEATHER_FOG_ENABLE,
    WEATHER_FOG_GHOST_RGB_HOOK,
    WEATHER_FOG_HOOK,
    WEATHER_FOG_HOOK_BYTES,
    WEATHER_FOG_MESH_ENABLED,
    WEATHER_FOG_MESH_GATE_HOOK,
    WEATHER_FOG_OBJECT_HOOK_BYTES,
    WEATHER_FOG_OBJECT_RGB_HOOK,
    WEATHER_FOG_PROJECTION_OVERRIDE,
    WEATHER_FOG_RESUME,
    WEATHER_FOG_SCENE_EXIT_HOOK,
    WEATHER_FOG_SCENE_RGB_HOOK,
    WEATHER_FOG_STATIC_LOD,
)
from sage_patch.asm import JA, JAE, JBE, JE, JL, JNE, Asm
from sage_patch.patcher import Patch
from sage_patch.utils import (
    allocate_section,
    apply_byte_patch,
    f32,
    file_offset,
    find_section,
    image_base,
    jmp_rel32,
    read_bytes,
    u32,
)

__all__ = [
    "BLEND_IN_MS",
    "BLEND_OUT_MS",
    "CONFIG_OFFSET",
    "FOG_END",
    "FOG_RGB",
    "FOG_START",
    "OBJECT_CODE_OFFSET",
    "RGB_OFFSET",
    "SECTION_NAME",
    "STATE_OFFSET",
    "STATE_SIZE",
    "CloudyHardwareFogPatch",
    "build_code",
    "build_hooks",
]

SECTION_NAME = ".cldfog"
BLEND_IN_MS = 10000
BLEND_OUT_MS = 10000
FOG_RGB = (0.70, 0.76, 0.80)
FOG_START = 725.0
FOG_END = 2000.0
OBJECT_CODE_OFFSET = 0x600
CONFIG_OFFSET = 0x800
STATE_OFFSET = 0x880
STATE_SIZE = 0x40
RGB_OFFSET = STATE_OFFSET + 0x20
_MAGIC = b"CLDFOG3\0"
_HEADER = struct.Struct("<8sII5f")
_CHARACTERISTICS = 0xE0000060  # Code, constants and persistent writable render state.
_JS = 0x8


def _single(value: float) -> float:
    return struct.unpack("<f", f32(value))[0]


def _object_code(cave_va: int) -> tuple[bytes, dict[int, int]]:
    """Keep native material policy and shroud scaling, substituting only the fog inputs."""
    a = Asm(cave_va + OBJECT_CODE_OFFSET)
    active = cave_va + STATE_OFFSET + 0x3C
    targets = {}
    for hook in (
        WEATHER_FOG_SCENE_RGB_HOOK,
        WEATHER_FOG_OBJECT_RGB_HOOK,
        WEATHER_FOG_GHOST_RGB_HOOK,
    ):
        original = WEATHER_FOG_OBJECT_HOOK_BYTES[hook]
        targets[hook] = a.va
        fallback, done = f"original_{hook:x}", f"done_{hook:x}"
        a.emit(b"\x9c\x52\x80\x3d", u32(WEATHER_FOG_ENABLE), 0).jcc(JE, fallback)
        a.emit(b"\x83\x3d", u32(active), 0).jcc(JE, fallback)
        a.emit(0xBA, u32(cave_va + RGB_OFFSET))
        if hook == WEATHER_FOG_GHOST_RGB_HOOK:
            a.emit(bytes.fromhex("f30f104208f30f104a04f30f1012"))
        else:
            a.emit(bytes.fromhex("8b0a8948088b4a0489480c8b4a08894810"))
        a.jmp(done)
        a.label(fallback).emit(original)
        a.label(done).emit(b"\x5a\x9d").jmp_absolute(hook + len(original))

    hook = WEATHER_FOG_MESH_GATE_HOOK
    targets[hook] = a.va
    # The native preceding FogEnable test still gates this branch. Taking the
    # HardwareFog=true path lets Enable_Fog choose normal/black/white fog for the
    # existing blend mode, without modifying the mesh or any alpha-test setting.
    a.emit(b"\x9c\x83\x3d", u32(active), 0).jcc(JE, "mesh_original")
    a.emit(b"\x80\x3d", u32(WEATHER_FOG_ENABLE), 0).jcc(JE, "mesh_original")
    a.emit(0x9D).jmp_absolute(WEATHER_FOG_MESH_ENABLED)
    a.label("mesh_original").emit(0x9D, WEATHER_FOG_OBJECT_HOOK_BYTES[hook])
    a.jmp_absolute(hook + len(WEATHER_FOG_OBJECT_HOOK_BYTES[hook]))

    targets[WEATHER_FOG_SCENE_EXIT_HOOK] = a.va
    # MOV preserves the native flags and all registers. The relocated epilogue
    # performs exactly the original pops, LEAVE and RET 4; no render state is cleared.
    a.emit(b"\xc7\x05", u32(active), u32(0))
    a.emit(WEATHER_FOG_OBJECT_HOOK_BYTES[WEATHER_FOG_SCENE_EXIT_HOOK])
    return a.finish(), targets


def build_hooks(cave_va: int) -> dict[int, bytes]:
    """Return complete instruction-aligned replacements for every owned hook."""
    _, targets = _object_code(cave_va)
    return {
        WEATHER_FOG_HOOK: jmp_rel32(WEATHER_FOG_HOOK, cave_va),
        **{
            va: jmp_rel32(va, target).ljust(len(WEATHER_FOG_OBJECT_HOOK_BYTES[va]), b"\x90")
            for va, target in targets.items()
        },
    }


def build_code(cave_va: int, *, patch: CloudyHardwareFogPatch | None = None) -> bytes:
    """Build immutable code/config followed by zero-initialized mutable blend/output state."""
    p = patch if patch is not None else CloudyHardwareFogPatch()
    config = cave_va + CONFIG_OFFSET
    a = Asm(cave_va)
    # Aligned FXSAVE scratch preserves every register and the caller's floating-point
    # environment; EBP remains the native render frame. No timer or native call is added.
    a.emit(bytes.fromhex("9c6089e381ec3002000083e4f00fae442420"))
    a.emit(0xBF, u32(cave_va + STATE_OFFSET))
    a.emit(b"\xc7\x47\x3c", u32(0))  # object override is scoped to this scene submission
    a.emit(b"\x80\x3d", u32(WEATHER_FOG_PROJECTION_OVERRIDE), 0).jcc(JNE, "reset")
    a.emit(b"\x83\x3d", u32(WEATHER_FOG_STATIC_LOD), 1).jcc(JL, "reset")
    a.emit(b"\x8b\x35", u32(THE_GLOBAL_WEATHER_SYSTEM))
    a.emit(b"\x85\xf6").jcc(JE, "reset")
    a.emit(b"\x8b\x0d", u32(THE_GAME_LOGIC))
    a.emit(b"\x85\xc9").jcc(JE, "reset")
    a.emit(b"\x89\x4c\x24\x08")  # scratch GameLogic pointer
    a.emit(b"\x8b\x41", GAME_LOGIC_FRAME, b"\x89\x04\x24")  # scratch current frame
    a.emit(b"\x0f\xb6\x81", u32(GAME_LOGIC_PAUSED), b"\x89\x44\x24\x0c")
    a.emit(b"\xa1", u32(LOGIC_FRAMES_PER_SECOND), b"\x48\x3d", u32(999))
    a.jcc(JA, "reset")  # do not divide by an invalid live simulation rate
    a.emit(b"\x0f\xae\x15", u32(config + 0x38))
    a.emit(b"\x0f\x57\xc9\x8b\x0d", u32(GAME_ENGINE))
    a.emit(b"\x85\xc9").jcc(JE, "fraction")
    a.emit(b"\xf3\x0f\x10\x49", GAME_ENGINE_ALPHA)
    a.label("fraction")
    a.emit(b"\x0f\x57\xc0\xf3\x0f\x5f\xc8")
    a.emit(b"\xf3\x0f\x5d\x0d", u32(config + 0x28))
    a.emit(b"\xf3\x0f\x11\x4c\x24\x04")  # finite, clamped current render alpha
    a.emit(b"\x31\xd2\x83\x7e", GLOBAL_WEATHER_CURRENT, p._weather_id)
    a.emit(b"\x0f\x94\xc2")
    a.emit(b"\x83\x3f\x01").jcc(JNE, "init")
    a.emit(b"\x39\x77\x04").jcc(JNE, "init")
    a.emit(b"\x8b\x44\x24\x08\x39\x47\x34").jcc(JNE, "init")
    a.emit(b"\x8b\x04\x24\x2b\x47\x0c").jcc(_JS, "init")
    a.emit(b"\x39\x57\x08").jcc(JNE, "reverse")
    a.emit(b"\x83\x7c\x24\x0c\x00").jcc(JNE, "observe")
    a.emit(b"\x83\x7f\x38\x00").jcc(JNE, "observe")  # first resumed draw rebases
    # A stalled/recomputed interpolation fraction must never spend the same part
    # of a logic tick twice. A new integer frame starts a fresh fraction interval.
    a.emit(b"\x85\xc0").jcc(JNE, "elapsed_cap")
    a.emit(b"\xf3\x0f\x5f\x4f\x1c\xf3\x0f\x11\x4c\x24\x04")
    a.label("elapsed_cap")
    a.emit(b"\x3d", u32(600000)).jcc(JBE, "elapsed_ok")
    a.emit(0xB8, u32(600000))
    a.label("elapsed_ok")
    a.emit(b"\xf3\x0f\x2a\xc0\xf3\x0f\x58\xc1\xf3\x0f\x5c\x47\x1c")
    a.emit(b"\x0f\x57\xd2\xf3\x0f\x5f\xc2")  # a fraction regression contributes zero
    a.emit(b"\xf3\x0f\x2a\x1d", u32(LOGIC_FRAMES_PER_SECOND))
    a.emit(b"\xf3\x0f\x59\x1d", u32(config + 0x44))  # live logic frames per millisecond
    a.emit(b"\x85\xd2").jcc(JE, "out")
    a.emit(b"\xf3\x0f\x2a\x0d", u32(config + 8))
    a.emit(b"\xf3\x0f\x59\xcb\xf3\x0f\x5e\xc1").jmp("accumulate")
    a.label("out")
    a.emit(b"\xf3\x0f\x2a\x0d", u32(config + 12))
    a.emit(b"\xf3\x0f\x59\xcb\xf3\x0f\x5e\xc1")
    a.emit(b"\x0f\x57\xd2\xf3\x0f\x5c\xd0\x0f\x28\xc2")
    a.label("accumulate")
    # Compensated summation prevents render-rate-dependent float drift during long fades.
    a.emit(b"\xf3\x0f\x5c\x47\x10\xf3\x0f\x10\x4f\x14\x0f\x28\xd1")
    a.emit(b"\xf3\x0f\x58\xc8\x0f\x28\xd9\xf3\x0f\x5c\xda\xf3\x0f\x5c\xd8")
    a.emit(b"\xf3\x0f\x11\x5f\x10\x0f\x28\xc1\x85\xd2").jcc(JE, "snap_out")
    a.emit(b"\x0f\x2e\x05", u32(config + 0x40)).jcc(JBE, "clamp")
    a.emit(b"\xf3\x0f\x10\x05", u32(config + 0x28)).jmp("clamp")
    a.label("snap_out")
    a.emit(b"\x0f\x2e\x05", u32(config + 0x3C)).jcc(JAE, "clamp")
    a.emit(b"\x0f\x57\xc0")
    a.label("clamp")
    a.emit(b"\x0f\x57\xc9\xf3\x0f\x5f\xc1")
    a.emit(b"\xf3\x0f\x5d\x05", u32(config + 0x28))
    a.emit(b"\xf3\x0f\x11\x47\x14").jmp("observe")
    a.label("init")
    a.emit(b"\xc7\x07\x01\x00\x00\x00\x89\x77\x04")
    a.emit(b"\x8b\x44\x24\x08\x89\x47\x34")
    a.emit(b"\xc7\x47\x14\x00\x00\x00\x00")
    a.label("reverse")
    a.emit(b"\x89\x57\x08\xc7\x47\x10\x00\x00\x00\x00")
    a.label("observe")
    a.emit(b"\x8b\x04\x24\x89\x47\x0c")
    a.emit(b"\x8b\x44\x24\x04\x89\x47\x1c")
    a.emit(b"\x8b\x44\x24\x0c\x89\x47\x38")
    a.label("weight")
    a.emit(b"\xf3\x0f\x10\x47\x14\x0f\x28\xc8")
    a.emit(b"\xf3\x0f\x59\xc8\xf3\x0f\x58\xc0")  # p^2, 2p
    a.emit(b"\xf3\x0f\x10\x15", u32(config + 0x30))
    a.emit(b"\xf3\x0f\x5c\xd0\xf3\x0f\x59\xca")
    a.emit(b"\xf3\x0f\x5d\x0d", u32(config + 0x28))
    a.emit(b"\xf3\x0f\x11\x4f\x18")
    a.emit(b"\x0f\x57\xc0\x0f\x2e\xc8").jcc(JBE, "done")
    a.emit(b"\x0f\x2e\x0d", u32(config + 0x28)).jcc(JAE, "target")

    # RGB = original + (target-original)*smoothstep. All results are private outputs.
    a.emit(b"\x8b\x75\xf0")
    for offset in (0, 4, 8):
        a.emit(b"\xf3\x0f\x10\x56", offset)
        a.emit(b"\xf3\x0f\x10\x05", u32(config + 0x10 + offset))
        a.emit(b"\xf3\x0f\x5c\xc2\xf3\x0f\x59\xc1\xf3\x0f\x58\xc2")
        a.emit(b"\xf3\x0f\x11\x47", 0x20 + offset)
    a.emit(b"\x80\x7b\x1c\x00").jcc(JE, "neutral")  # original AL, not a previous override
    # Only a finite increasing original range is a usable interpolation endpoint.
    a.emit(b"\x8b\x45\xec\x25\xff\xff\xff\x7f\x3d\x00\x00\x80\x7f")
    a.jcc(JAE, "neutral")
    a.emit(b"\x8b\x45\xe8\x25\xff\xff\xff\x7f\x3d\x00\x00\x80\x7f")
    a.jcc(JAE, "neutral")
    a.emit(b"\xf3\x0f\x10\x45\xe8\x0f\x2e\x45\xec").jcc(JBE, "neutral")
    for source, destination, target in ((0xEC, 0x2C, 0x1C), (0xE8, 0x30, 0x20)):
        a.emit(b"\xf3\x0f\x10\x55", source)
        a.emit(b"\xf3\x0f\x10\x05", u32(config + target))
        a.emit(b"\xf3\x0f\x5c\xc2\xf3\x0f\x59\xc1\xf3\x0f\x58\xc2")
        a.emit(b"\xf3\x0f\x11\x47", destination)
    a.jmp("commit")
    a.label("neutral")
    # A disabled fog has no meaningful range. Scale the linear fog slope by alpha:
    # S=S_target, E=S_target+(E_target-S_target)/alpha. As alpha->0 the end
    # approaches infinity, smoothly removing fog at every finite visible distance.
    a.emit(b"\xf3\x0f\x10\x05", u32(config + 0x24))
    a.emit(b"\xf3\x0f\x5e\xc1\xf3\x0f\x5d\x05", u32(config + 0x34))
    a.emit(b"\xf3\x0f\x10\x15", u32(config + 0x1C))
    a.emit(b"\xf3\x0f\x58\xc2\xf3\x0f\x11\x47\x30\xf3\x0f\x11\x57\x2c")
    a.jmp("commit")
    a.label("target")
    for target, destination in (
        (0x10, 0x20),
        (0x14, 0x24),
        (0x18, 0x28),
        (0x1C, 0x2C),
        (0x20, 0x30),
    ):
        a.emit(b"\x8b\x05", u32(config + target), b"\x89\x47", destination)
    a.label("commit")
    a.emit(b"\xc7\x47\x3c", u32(1))
    a.emit(b"\x8d\x47\x20\x89\x45\xf0")  # [ebp-10] = private RGB
    a.emit(b"\x8b\x47\x2c\x89\x45\xec\x89\x84\x24\xd0\x00\x00\x00")
    a.emit(b"\x8b\x47\x30\x89\x45\xe8\x89\x84\x24\xc0\x00\x00\x00")
    # Patch only the saved low SSE lanes and AL; FXRSTOR/POPAD restore everything else.
    a.emit(b"\xc6\x43\x1c\x01").jmp("done")
    a.label("reset")
    for offset in (0, 4, 8, 0x10, 0x14, 0x18, 0x34, 0x38):
        a.emit(b"\xc7\x47", offset, b"\x00\x00\x00\x00")
    a.label("done")
    a.emit(bytes.fromhex("0fae4c242089dc619d"))
    a.emit(WEATHER_FOG_HOOK_BYTES).jmp_absolute(WEATHER_FOG_RESUME)
    code = a.finish()
    if len(code) > OBJECT_CODE_OFFSET:
        raise ValueError("cloudy-hardware-fog: blend code overlaps object routing")
    object_code, _ = _object_code(cave_va)
    code = code.ljust(OBJECT_CODE_OFFSET, b"\x90") + object_code
    if len(code) > CONFIG_OFFSET:
        raise ValueError("cloudy-hardware-fog: object code overlaps configuration")
    header = _HEADER.pack(_MAGIC, p.blend_in_ms, p.blend_out_ms, *p.fog_rgb, p.fog_start, p.fog_end)
    constants = f32(p.fog_end - p.fog_start) + f32(1) + f32(2) + f32(3)
    constants += f32(1e30) + u32(0x1F80) + f32(1e-6) + f32(1 - 1e-6) + f32(0.001)
    return (code.ljust(CONFIG_OFFSET, b"\x90") + header + constants).ljust(
        STATE_OFFSET + STATE_SIZE, b"\0"
    )


class CloudyHardwareFogPatch(Patch):
    """Apply the shared hardware-fog profile to native CLOUDY=1."""

    name = "cloudy-hardware-fog"
    author = "Ostkannit"
    experimental = True
    description = (
        "Blend CLOUDY hardware fog using configurable simulation durations, RGB and range; "
        "share color with objects and enable native mesh fog selection during the blend. "
        "No INI change; mutually exclusive with foggy-weather"
    )
    # The native FOGGY extension reuses this renderer with its own weather ID.
    _weather_id = GLOBAL_WEATHER_CLOUDY

    def __init__(
        self,
        blend_in_ms: int = BLEND_IN_MS,
        blend_out_ms: int = BLEND_OUT_MS,
        fog_start: float = FOG_START,
        fog_end: float = FOG_END,
        fog_rgb: tuple[float, float, float] = FOG_RGB,
    ) -> None:
        for duration in (blend_in_ms, blend_out_ms):
            if type(duration) is not int or not 1 <= duration <= 600000:
                raise ValueError("Blend durations must be integer milliseconds in 1..600000")
        values = [float(fog_start), float(fog_end), *(float(c) for c in fog_rgb)]
        if len(values) != 5 or not all(math.isfinite(v) for v in values):
            raise ValueError("Fog profile must have finite start/end and three RGB components")
        if not 0 <= values[0] < values[1] <= 1e7 or not all(0 <= c <= 1 for c in values[2:]):
            raise ValueError("Require 0 <= start < end <= 10000000 and RGB in 0..1")
        start, end, red, green, blue = map(_single, values)
        if start >= end:
            raise ValueError("Fog range collapses at float32 precision")
        self.blend_in_ms = blend_in_ms
        self.blend_out_ms = blend_out_ms
        self.fog_start = start
        self.fog_end = end
        self.fog_rgb = (red, green, blue)

    def __str__(self) -> str:
        return (
            f"{self.name} (blend_in_ms={self.blend_in_ms}, blend_out_ms={self.blend_out_ms}, "
            f"fog_start={self.fog_start:g}, fog_end={self.fog_end:g}, "
            f"fog_rgb={tuple(round(value, 7) for value in self.fog_rgb)})"
        )

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        if image_base(data) != 0x00400000:
            raise ValueError("cloudy-hardware-fog: unsupported image base")
        for va, expected in WEATHER_FOG_ANCHORS.items():
            if read_bytes(data, va, len(expected)) != expected:
                raise ValueError(f"cloudy-hardware-fog: unexpected bytes at {va:#010x}")

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        if find_section(data, SECTION_NAME) is not None:
            if problems := self.verify(data):
                raise ValueError("; ".join(problems) + "; rebuild from the clean backup for V3")
            return
        originals = {WEATHER_FOG_HOOK: WEATHER_FOG_HOOK_BYTES, **WEATHER_FOG_OBJECT_HOOK_BYTES}
        for va, expected in originals.items():
            if read_bytes(data, va, len(expected)) != expected:
                raise ValueError(f"cloudy-hardware-fog: hook {va:#010x} is occupied or unsupported")
        staged = bytearray(data)
        cave_va = allocate_section(
            staged, SECTION_NAME, lambda va: build_code(va, patch=self), _CHARACTERISTICS
        )
        for va, replacement in build_hooks(cave_va).items():
            apply_byte_patch(
                staged, file_offset(staged, va), originals[va], replacement, "CLOUDY hardware fog"
            )
        if problems := self.verify(staged):
            raise ValueError("; ".join(problems))
        data[:] = staged

    def verify(self, data: bytes | bytearray) -> list[str]:
        try:
            self._check_anchors(data)
            section = find_section(data, SECTION_NAME)
            if section is None:
                return [f"cloudy-hardware-fog: missing {SECTION_NAME}"]
            cave_va, off, size = section
            expected = build_code(cave_va, patch=self)
            # The loader initializes state once; live state and RGB outputs are mutable.
            if size != len(expected) or data[off : off + STATE_OFFSET] != expected[:STATE_OFFSET]:
                return ["cloudy-hardware-fog: immutable V3 code or configuration differs"]
            for va, replacement in build_hooks(cave_va).items():
                if read_bytes(data, va, len(replacement)) != replacement:
                    return [f"cloudy-hardware-fog: hook {va:#010x} does not target its cave"]
        except (ValueError, IndexError, TypeError, struct.error) as exc:
            return [f"cloudy-hardware-fog: {exc}"]
        return []

    @classmethod
    def detect(cls, data: bytes | bytearray) -> Self | None:
        try:
            section = find_section(data, SECTION_NAME)
            if section is None or section[2] < STATE_OFFSET + STATE_SIZE:
                return None
            magic, blend_in, blend_out, red, green, blue, start, end = _HEADER.unpack_from(
                data, section[1] + CONFIG_OFFSET
            )
            if magic != _MAGIC:
                return None
            patch = cls(blend_in, blend_out, start, end, (red, green, blue))
            return None if patch.verify(data) else patch
        except (ValueError, IndexError, TypeError, struct.error):
            return None

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Expose the same optional render profile to apply, verify and info."""
        defaults = cls()
        for name in ("blend_in_ms", "blend_out_ms"):
            parser.add_argument(
                "--" + name.replace("_", "-"),
                type=int,
                default=getattr(defaults, name),
                help=(f"simulation milliseconds in 1..600000 (default: {getattr(defaults, name)})"),
            )
        for name in ("fog_start", "fog_end"):
            parser.add_argument(
                "--" + name.replace("_", "-"),
                type=float,
                default=getattr(defaults, name),
                help=f"fog distance in world units (default: {getattr(defaults, name):g})",
            )
        parser.add_argument(
            "--fog-rgb",
            type=float,
            nargs=3,
            metavar=("R", "G", "B"),
            default=FOG_RGB,
            help="three finite RGB components in 0..1 (default: 0.70 0.76 0.80)",
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> Self:
        return cls(
            blend_in_ms=args.blend_in_ms,
            blend_out_ms=args.blend_out_ms,
            fog_start=args.fog_start,
            fog_end=args.fog_end,
            fog_rgb=tuple(args.fog_rgb),
        )
