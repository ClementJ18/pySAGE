"""Native FOGGY=6 with CLOUDY lighting and the existing reversible hardware-fog renderer.

Replaces the CLOUDY fog test patch in a patch list; they own the same renderer hooks.
The five WeatherData records, sentinel 5 and the actual weather ID stay intact.
Usage, runtime evidence and safety limits: docs/foggy-weather.md.
"""

from __future__ import annotations

import struct

from sage_ini.engine import Engine, EnumDelta
from sage_patch.addresses.weather import (
    FOGGY_NATIVE_ANCHORS,
    FOGGY_NATIVE_HOOK_BYTES,
    FOGGY_PARSER_LIMIT_HOOK,
    FOGGY_PARSER_TABLE_HOOK,
    FOGGY_SOUND_HOOK,
    FOGGY_TEXTURE_HOOK,
    FOGGY_VISUAL_HOOK,
    FOGGY_WB_ANCHORS,
    FOGGY_WB_HOOK_BYTES,
    FOGGY_WB_LIMIT_HOOK,
    FOGGY_WB_TABLE,
    FOGGY_WB_TABLE_HOOK,
    GLOBAL_WEATHER_FOGGY,
    GLOBAL_WEATHER_NAMES,
)
from sage_patch.asm import JB, JNE, Asm
from sage_patch.patcher import Patch
from sage_patch.patches.experimental.cloudy_hardware_fog import (
    BLEND_IN_MS,
    BLEND_OUT_MS,
    FOG_END,
    FOG_RGB,
    FOG_START,
    CloudyHardwareFogPatch,
)
from sage_patch.utils import (
    allocate_section,
    apply_byte_patch,
    file_offset,
    find_section,
    jmp_rel32,
    read_bytes,
    u32,
)

__all__ = [
    "BLEND_IN_MS",
    "BLEND_OUT_MS",
    "FOG_RGB",
    "FOG_START",
    "FOG_END",
    "NATIVE_SECTION_NAME",
    "NAMES_OFFSET",
    "FoggyWeatherPatch",
    "FoggyWeatherWorldbuilderPatch",
    "build_native_code",
]

NATIVE_SECTION_NAME = ".foggy"
NAMES_OFFSET = 0x220
_HEADER_OFFSET = 0x200
_FOGGY_OFFSET = 0x240
_MAGIC = b"FOGGY1\0\0"
_SIZE = 0x248
_ORIGINAL_POINTERS = bytes.fromhex("8415bd00c80cbd00c00cbd00b40cbd00ac0cbd00743cbf00")


def build_native_code(cave_va: int) -> tuple[bytes, dict[int, bytes]]:
    """Emit local weather interpretations and a bounded sound index, never a weather store."""
    a = Asm(cave_va)
    visual = a.va
    a.emit(bytes.fromhex("8b481083f906")).jcc(JNE, "visual_compare")
    a.emit(0xB9, u32(1))
    a.label("visual_compare").emit(b"\x3b\xcb").jmp_absolute(FOGGY_VISUAL_HOOK + 5)

    sound = a.va
    # RemoveAudioEvent has already run. Guard an unsigned index, covering negative
    # and out-of-range IDs too, then use NONE's entry and the native handle lifecycle.
    a.emit(bytes.fromhex("9c8b461083f805")).jcc(JB, "sound_index")
    a.emit(b"\x31\xc0")
    a.label("sound_index").emit(bytes.fromhex("9d8d44c630"))
    a.jmp_absolute(FOGGY_SOUND_HOOK + 7)

    texture = a.va
    # This is the cloud renderer's texture choice, not a gameplay weather alias.
    # EBX=1 throughout its caller; only the comparison sees the normalized value.
    a.emit(bytes.fromhex("518b481083f906")).jcc(JNE, "texture_compare")
    a.emit(0xB9, u32(1))
    a.label("texture_compare").emit(bytes.fromhex("3bcb59"))
    a.jcc(JNE, "texture_original")
    a.jmp_absolute(0x00496F52)
    a.label("texture_original").jmp_absolute(0x00496F55)

    code = a.finish()
    if len(code) > _HEADER_OFFSET:
        raise ValueError("foggy-weather: native code overlaps its header")
    payload = code.ljust(_HEADER_OFFSET, b"\x90") + _MAGIC
    payload = payload.ljust(NAMES_OFFSET, b"\0") + _ORIGINAL_POINTERS
    payload += u32(cave_va + _FOGGY_OFFSET) + u32(0)
    payload = payload.ljust(_FOGGY_OFFSET, b"\0") + b"FOGGY\0"
    hooks = {
        FOGGY_PARSER_TABLE_HOOK: b"\x68" + u32(cave_va + NAMES_OFFSET),
        FOGGY_PARSER_LIMIT_HOOK: bytes.fromhex("83f806"),
        FOGGY_VISUAL_HOOK: jmp_rel32(FOGGY_VISUAL_HOOK, visual),
        FOGGY_SOUND_HOOK: jmp_rel32(FOGGY_SOUND_HOOK, sound) + b"\x90\x90",
        FOGGY_TEXTURE_HOOK: jmp_rel32(FOGGY_TEXTURE_HOOK, texture),
    }
    return payload.ljust(_SIZE, b"\0"), hooks


class FoggyWeatherPatch(CloudyHardwareFogPatch):
    """Compose the existing renderer and native enum extension as one atomic patch."""

    name = "foggy-weather"
    author = "Ostkannit"
    experimental = True
    runtime_verified = "yes"
    _weather_id = GLOBAL_WEATHER_FOGGY
    description = (
        "Add ChangeWeather = FOGGY (ID 6) with native CLOUDY dimming and smooth hardware fog; "
        "keep CLOUDY and sentinel 5, bound WeatherData sound lookup. No WeatherData FOGGY block"
    )

    def __init__(
        self,
        blend_in_ms: int = BLEND_IN_MS,
        blend_out_ms: int = BLEND_OUT_MS,
        fog_start: float = FOG_START,
        fog_end: float = FOG_END,
        fog_rgb: tuple[float, float, float] = FOG_RGB,
    ) -> None:
        """Set optional simulation-time fades, world-unit distances and normalized RGB.

        Durations are integer milliseconds in 1..600000. Distances must satisfy
        0 <= start < end <= 10000000 after float32 conversion; RGB has three
        finite components in 0..1. All settings are embedded at patch-build time
        and recovered by detection and .sagepatch rebuilds.
        """
        super().__init__(blend_in_ms, blend_out_ms, fog_start, fog_end, fog_rgb)

    def _renderer(self) -> CloudyHardwareFogPatch:
        renderer = CloudyHardwareFogPatch(
            self.blend_in_ms, self.blend_out_ms, self.fog_start, self.fog_end, self.fog_rgb
        )
        renderer._weather_id = self._weather_id
        return renderer

    @staticmethod
    def _check_native_anchors(data: bytes | bytearray) -> None:
        for va, expected in FOGGY_NATIVE_ANCHORS.items():
            if read_bytes(data, va, len(expected)) != expected:
                raise ValueError(f"foggy-weather: unexpected native bytes at {va:#010x}")
        if read_bytes(data, GLOBAL_WEATHER_NAMES, 24) != _ORIGINAL_POINTERS:
            raise ValueError("foggy-weather: stock weather names/sentinel differ")

    def apply(self, data: bytearray) -> None:
        self._check_native_anchors(data)
        if find_section(data, NATIVE_SECTION_NAME) is not None:
            if problems := self.verify(data):
                raise ValueError("; ".join(problems) + "; rebuild from the clean backup")
            return
        for va, expected in FOGGY_NATIVE_HOOK_BYTES.items():
            if read_bytes(data, va, len(expected)) != expected:
                raise ValueError(f"foggy-weather: native hook {va:#010x} is occupied")
        staged = bytearray(data)
        self._renderer().apply(staged)
        cave = allocate_section(
            staged, NATIVE_SECTION_NAME, lambda va: build_native_code(va)[0], 0x60000020
        )
        _, hooks = build_native_code(cave)
        for va, replacement in hooks.items():
            apply_byte_patch(
                staged,
                file_offset(staged, va),
                FOGGY_NATIVE_HOOK_BYTES[va],
                replacement,
                "native FOGGY weather",
            )
        if problems := self.verify(staged):
            raise ValueError("; ".join(problems))
        data[:] = staged

    def verify(self, data: bytes | bytearray) -> list[str]:
        try:
            self._check_native_anchors(data)
            if problems := self._renderer().verify(data):
                return problems
            section = find_section(data, NATIVE_SECTION_NAME)
            if section is None:
                return ["foggy-weather: missing native cave"]
            va, off, size = section
            expected, hooks = build_native_code(va)
            if size != len(expected) or data[off : off + size] != expected:
                return ["foggy-weather: native cave differs"]
            for hook, replacement in hooks.items():
                if read_bytes(data, hook, len(replacement)) != replacement:
                    return [f"foggy-weather: native hook {hook:#010x} differs"]
        except (ValueError, IndexError, TypeError, struct.error) as exc:
            return [f"foggy-weather: {exc}"]
        return []

    def ini_surface(self) -> Engine:
        # WeatherFlag is the schema union used by the existing ChangeWeather behavior
        # fields. No other native enum/table or the WeatherData block parser is extended.
        return Engine(enum_members=(EnumDelta("WeatherFlag", "FOGGY", 6, self.name),))


class FoggyWeatherWorldbuilderPatch(Patch):
    """Editor-only ChangeWeather enum extension; no WeatherData or viewport changes."""

    name = "foggy-weather-wb"
    experimental = True
    author = "Ostkannit"
    description = (
        "Worldbuilder.exe (not game.dat): accept ChangeWeather = FOGGY (ID 6) in behavior INI; "
        "keep original names and sentinel 5. No editor viewport fog or WeatherData FOGGY block"
    )
    _section = ".wbfoggy"

    @staticmethod
    def _anchors(data: bytes | bytearray) -> None:
        for va, expected in FOGGY_WB_ANCHORS.items():
            if read_bytes(data, va, len(expected)) != expected:
                raise ValueError(f"foggy-weather-wb: unexpected original bytes at {va:#010x}")

    @staticmethod
    def _payload(va: int) -> bytes:
        return FOGGY_WB_ANCHORS[FOGGY_WB_TABLE][:24] + u32(va + 32) + u32(0) + b"FOGGY\0"

    @staticmethod
    def _hooks(va: int) -> dict[int, bytes]:
        return {
            FOGGY_WB_TABLE_HOOK: b"\x68" + u32(va),
            FOGGY_WB_LIMIT_HOOK: bytes.fromhex("833806"),
        }

    def apply(self, data: bytearray) -> None:
        self._anchors(data)
        if find_section(data, self._section) is not None:
            if problems := self.verify(data):
                raise ValueError("; ".join(problems) + "; rebuild from the clean editor backup")
            return
        for va, expected in FOGGY_WB_HOOK_BYTES.items():
            if read_bytes(data, va, len(expected)) != expected:
                raise ValueError(f"foggy-weather-wb: occupied hook at {va:#010x}")
        staged = bytearray(data)
        cave = allocate_section(staged, self._section, self._payload, 0x40000040)
        for va, replacement in self._hooks(cave).items():
            apply_byte_patch(
                staged,
                file_offset(staged, va),
                FOGGY_WB_HOOK_BYTES[va],
                replacement,
                "Worldbuilder FOGGY enum",
            )
        if problems := self.verify(staged):
            raise ValueError("; ".join(problems))
        data[:] = staged

    def verify(self, data: bytes | bytearray) -> list[str]:
        try:
            self._anchors(data)
            section = find_section(data, self._section)
            if section is None:
                return ["foggy-weather-wb: missing name table"]
            va, off, size = section
            expected = self._payload(va)
            if size != len(expected) or data[off : off + size] != expected:
                return ["foggy-weather-wb: name table differs"]
            for hook, replacement in self._hooks(va).items():
                if read_bytes(data, hook, len(replacement)) != replacement:
                    return [f"foggy-weather-wb: hook {hook:#010x} differs"]
        except (ValueError, IndexError, TypeError, struct.error) as exc:
            return [f"foggy-weather-wb: {exc}"]
        return []
