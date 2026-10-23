"""Native FOGGY parser, lighting, audio, expiry and snapshot execution without game data."""

from __future__ import annotations

import struct
import sys
from types import SimpleNamespace

import pytest

import tools.build_foggy_weather_patch as foggy_builder
from sage_ini.engine import Engine, dump_engine, parse_engine
from sage_ini.model.enums import WeatherFlag
from sage_patch.__main__ import build_parser, main
from sage_patch.addresses.weather import (
    FOGGY_NATIVE_ANCHORS,
    FOGGY_NATIVE_HOOK_BYTES,
    FOGGY_SOUND_HOOK,
    FOGGY_TEXTURE_HOOK,
    FOGGY_VISUAL_HOOK,
    FOGGY_WB_ANCHORS,
    FOGGY_WB_HOOK_BYTES,
    FOGGY_WB_TABLE,
    WEATHER_FOG_ANCHORS,
    WEATHER_FOG_HOOK,
    WEATHER_FOG_HOOK_BYTES,
    WEATHER_FOG_OBJECT_HOOK_BYTES,
)
from sage_patch.patches import FoggyWeatherPatch as PublicFoggyWeatherPatch
from sage_patch.patches.experimental.cloudy_hardware_fog import (
    CloudyHardwareFogPatch,
    build_code,
)
from sage_patch.patches.experimental.foggy_weather import (
    BLEND_IN_MS,
    BLEND_OUT_MS,
    FOG_END,
    FOG_RGB,
    FOG_START,
    NAMES_OFFSET,
    NATIVE_SECTION_NAME,
    FoggyWeatherPatch,
    FoggyWeatherWorldbuilderPatch,
    build_native_code,
)
from sage_patch.sagepatch import manifest, rebuild
from sage_patch.utils import allocate_section, file_offset, find_section, read_bytes

from .synthetic import _sparse_image
from .test_cloudy_hardware_fog import FogHarness


def test_worldbuilder_separate_null_terminated_table_and_detection():
    data = _sparse_image({**FOGGY_WB_ANCHORS, **FOGGY_WB_HOOK_BYTES})
    original = read_bytes(data, FOGGY_WB_TABLE, 36)
    patch = FoggyWeatherWorldbuilderPatch()
    patch.apply(data)
    assert patch.verify(data) == [] and patch.detect(data) is not None
    section = find_section(data, ".wbfoggy")
    assert section is not None
    table = struct.unpack("<8I", read_bytes(data, section[0], 32))
    assert table[:6] == struct.unpack("<6I", original[:24])
    assert table[7] == 0 and read_bytes(data, table[6], 6) == b"FOGGY\0"
    assert read_bytes(data, FOGGY_WB_TABLE, 36) == original
    once = bytes(data)
    patch.apply(data)
    assert data == once
    data[section[1]] ^= 1
    assert patch.verify(data)
    with pytest.raises(ValueError):
        patch.apply(data)


@pytest.mark.parametrize("va", [*FOGGY_WB_ANCHORS, *FOGGY_WB_HOOK_BYTES])
def test_unknown_worldbuilder_bytes_fail_atomically(va):
    data = _sparse_image({**FOGGY_WB_ANCHORS, **FOGGY_WB_HOOK_BYTES})
    data[file_offset(data, va)] ^= 1
    once = bytes(data)
    with pytest.raises(ValueError):
        FoggyWeatherWorldbuilderPatch().apply(data)
    assert data == once


@pytest.mark.parametrize(
    "token,expected",
    [
        ("NONE", 0),
        ("CLOUDY", 1),
        ("RAINY", 2),
        ("CLOUDYRAINY", 3),
        ("SUNNY", 4),
        ("MOUNTED", 5),
        ("FOGGY", 6),
        ("foggy", 6),
        ("FoGgY", 6),
        ("WEAPON_TOGGLE", -1),
        ("MOVING", -1),
        ("UNKNOWN", -1),
    ],
)
def test_worldbuilder_native_callback_bounds_with_external_ini_lookup_stub(token, expected):
    # Execute the complete original callback. Only the external INI token/lookup
    # services are replaced; the native store and signed range checks execute in x86.
    h = Native()
    for va, raw in {**FOGGY_WB_ANCHORS, **FOGGY_WB_HOOK_BYTES}.items():
        h.write(va, raw)
    patch = FoggyWeatherWorldbuilderPatch()
    cave = 0x2400000
    h.write(cave, patch._payload(cave))
    for va, raw in patch._hooks(cave).items():
        h.write(va, raw)
    names = ("NONE", "CLOUDY", "RAINY", "CLOUDYRAINY", "SUNNY", "MOUNTED")
    for ptr, name in zip(
        struct.unpack("<6I", FOGGY_WB_ANCHORS[FOGGY_WB_TABLE][:24]), names, strict=True
    ):
        h.write(ptr, name.encode() + b"\0")
    h.write(0x6D21F0, b"\xc2\x04\x00")
    h.on(0x6D21F0, lambda: h.mu.reg_write(h.r.UC_X86_REG_EAX, h.CLIENT))
    h.write(0x6CE700, b"\xc2\x08\x00")

    def lookup():
        table = h.arg(1)
        result = -1
        for index in range(8):
            ptr = h.get(table + 4 * index)
            if not ptr:
                break
            raw = bytearray()
            while h.mu.mem_read(ptr + len(raw), 1) != b"\0":
                raw.extend(h.mu.mem_read(ptr + len(raw), 1))
            name = raw.decode()
            if token.casefold() == name.casefold():
                result = index
                break
        h.mu.reg_write(h.r.UC_X86_REG_EAX, result & 0xFFFFFFFF)

    h.on(0x6CE700, lookup)
    h.call(0x11FA120, args=(0, 0, h.CLIENT + 0x100, 0), stop=0x11FA159 if expected < 0 else None)
    assert h.get(h.CLIENT + 0x100) == expected & 0xFFFFFFFF


def original_image():
    return _sparse_image(
        {
            **WEATHER_FOG_ANCHORS,
            WEATHER_FOG_HOOK: WEATHER_FOG_HOOK_BYTES,
            **WEATHER_FOG_OBJECT_HOOK_BYTES,
            **FOGGY_NATIVE_ANCHORS,
            **FOGGY_NATIVE_HOOK_BYTES,
        }
    )


def test_apply_verify_detect_and_original_weather_table():
    data = original_image()
    original_names = read_bytes(data, 0xDB0074, 36)
    patch = FoggyWeatherPatch(1250, 4500, 700, 2100, (0.6, 0.7, 0.8))
    patch.apply(data)
    assert patch.verify(data) == []
    detected = patch.detect(data)
    assert detected is not None and detected.options() == patch.options()
    assert CloudyHardwareFogPatch.detect(data) is None
    assert read_bytes(data, 0xDB0074, 36) == original_names
    section = find_section(data, NATIVE_SECTION_NAME)
    assert section is not None
    table = struct.unpack("<8I", read_bytes(data, section[0] + NAMES_OFFSET, 32))
    assert table[:6] == struct.unpack("<6I", original_names[:24])
    assert read_bytes(data, table[6], 6) == b"FOGGY\0" and table[7] == 0
    once = bytes(data)
    patch.apply(data)
    assert data == once


@pytest.mark.parametrize("va", [*FOGGY_NATIVE_HOOK_BYTES, *FOGGY_NATIVE_ANCHORS])
def test_unknown_native_bytes_fail_without_mutation(va):
    data = original_image()
    data[file_offset(data, va)] ^= 1
    original = bytes(data)
    with pytest.raises(ValueError):
        FoggyWeatherPatch().apply(data)
    assert data == original


@pytest.mark.parametrize("foggy_first", [False, True])
def test_legacy_cloudy_fog_cannot_be_layered_in_either_order(foggy_first):
    data = original_image()
    a, b = (FoggyWeatherPatch(), CloudyHardwareFogPatch())
    if not foggy_first:
        a, b = b, a
    a.apply(data)
    original = bytes(data)
    with pytest.raises(ValueError, match="clean backup"):
        b.apply(data)
    assert data == original


def test_native_cave_collision_is_atomic():
    data = original_image()
    allocate_section(data, NATIVE_SECTION_NAME, lambda _: b"foreign", 0x60000020)
    original = bytes(data)
    with pytest.raises(ValueError):
        FoggyWeatherPatch().apply(data)
    assert data == original


@pytest.mark.parametrize("va", list(FOGGY_NATIVE_HOOK_BYTES))
def test_native_hook_damage_is_detected_and_never_reapplied(va):
    patch, data = FoggyWeatherPatch(), original_image()
    patch.apply(data)
    data[file_offset(data, va)] ^= 1
    original = bytes(data)
    assert patch.verify(data) and patch.detect(data) is None
    with pytest.raises(ValueError):
        patch.apply(data)
    assert data == original


def test_renderer_changes_exactly_one_weather_comparison_byte():
    cloudy = build_code(0x1500000, patch=CloudyHardwareFogPatch())
    foggy = build_code(0x1500000, patch=FoggyWeatherPatch()._renderer())
    differences = [i for i, (a, b) in enumerate(zip(cloudy, foggy, strict=True)) if a != b]
    assert len(differences) == 1
    at = differences[0]
    assert cloudy[at - 3 : at + 1] == b"\x83\x7e\x10\x01"
    assert foggy[at] == 6


def test_schema_token_is_scoped_and_reversible():
    assert "FOGGY" not in WeatherFlag.__members__
    with FoggyWeatherPatch().ini_surface().activate() as problems:
        assert problems == [] and WeatherFlag.__members__["FOGGY"].value == 6
    assert "FOGGY" not in WeatherFlag.__members__


def test_cloudy_stays_clear_and_foggy_blends_out_without_changing_the_weather_id():
    h = FogHarness(patch=FoggyWeatherPatch(3000, 3000)._renderer())
    assert h.draw(0, weather=1)["phase"] == 0
    assert h.draw(3000, weather=1)["enable"] == 0
    assert h.draw(3000, weather=6)["phase"] == 0
    assert h.draw(4500, weather=6)["weight"] == pytest.approx(0.5)
    assert h.draw(6000, weather=6)["phase"] == 1
    assert h.draw(6000, weather=1)["phase"] == 1
    assert h.draw(7500, weather=1)["weight"] == pytest.approx(0.5)
    assert h.draw(9000, weather=1)["enable"] == 0
    assert struct.unpack("<I", h.mu.mem_read(0x2500010, 4))[0] == 1


class Native:
    CAVE = 0x1500000
    STACK = 0x2000000
    STOP = 0x3000000
    WEATHER = 0x2500000
    CLOUD = 0x2501000
    CLIENT = 0x2502000
    AUDIO = 0x2503000
    VTABLE = 0x2504000
    TEXT = 0x2505000

    def __init__(self, patched=True):
        self.uc = pytest.importorskip("unicorn")
        self.r = pytest.importorskip("unicorn.x86_const")
        self.mu = self.uc.Uc(self.uc.UC_ARCH_X86, self.uc.UC_MODE_32)
        self.pages = set()
        self.callbacks = []
        for va, raw in {
            **WEATHER_FOG_ANCHORS,
            **FOGGY_NATIVE_ANCHORS,
            **FOGGY_NATIVE_HOOK_BYTES,
        }.items():
            self.write(va, raw)
        for va in (
            0,
            self.STACK,
            self.STACK + 0x1000,
            self.STACK + 0x2000,
            self.WEATHER,
            self.CLOUD,
            self.CLIENT,
            self.AUDIO,
            self.VTABLE,
            self.TEXT,
            self.STOP,
            0xD9989C,
            0xDE42FC,
            0xDE46A8,
            0xDE4388,
            0xDE772C,
            0xDE3C24,
            0xDC78EC,
            0xBD051C,
        ):
            self.write(va, b"\0" * 4)
        payload, hooks = build_native_code(self.CAVE)
        self.write(self.CAVE, payload)
        if patched:
            for va, raw in hooks.items():
                self.write(va, raw)
        self.put(0xDE772C, self.WEATHER)
        self.put(0xDE3C24, self.CLOUD)
        self.put(0xDE4388, self.CLIENT)
        self.put(0xDE42FC, self.AUDIO)
        self.put(0xDE46A8, self.CLIENT)
        self.put(0xDC78EC, self.CLIENT)
        self.put(self.CLOUD, 0xBDE130)
        self.put(self.CLIENT, self.VTABLE)
        self.put(self.AUDIO, self.VTABLE)
        self.put(self.CLOUD + 0xC4, 255)
        self.put(0xD9989C, 2)
        self.write(self.CLOUD + 0x30, struct.pack("<6f", 0.15, 0.2, 0.25, 0.4, 0.4, 0.4))
        self.remove, self.add, self.config = [], [], []
        self.put(self.VTABLE + 0x7C, 0x9F9F1A)  # real GameClient::getFrame
        self.stub(0x20, 0, lambda: self.config.append(self.get(self.WEATHER + 0x10)))
        self.put(0xBDE130 + 0x38, self.STOP + 0x20)
        self.stub(0x30, 4, lambda: None)
        self.put(self.VTABLE + 0x224, self.STOP + 0x30)
        self.stub(0x40, 4, lambda: self.remove.append(self.arg(0)))
        self.put(self.VTABLE + 0x6C, self.STOP + 0x40)
        self.stub(0x50, 4, self.audio_add)
        self.put(self.VTABLE + 0x64, self.STOP + 0x50)
        self.write(0x6DA95E, b"\xc2\x08\x00")
        self.write(0x6DABCB, b"\xc3")
        self.event_refs = []
        self.on(0x6DA95E, lambda: self.event_refs.append(self.arg(0)))
        self.ctor_names = []

    def write(self, va, raw):
        for page in range(va & ~0xFFF, (va + len(raw) + 0xFFF) & ~0xFFF, 0x1000):
            if page not in self.pages:
                self.mu.mem_map(page, 0x1000)
                self.pages.add(page)
        self.mu.mem_write(va, raw)

    def put(self, va, value):
        self.write(va, struct.pack("<I", value & 0xFFFFFFFF))

    def get(self, va):
        return struct.unpack("<I", self.mu.mem_read(va, 4))[0]

    def arg(self, at):
        return self.get(self.mu.reg_read(self.r.UC_X86_REG_ESP) + 4 + at * 4)

    def on(self, address, callback):
        def called(mu, va, size, user):
            callback()

        self.callbacks.append(
            self.mu.hook_add(self.uc.UC_HOOK_CODE, called, begin=address, end=address)
        )

    def stub(self, offset, cleanup, callback):
        self.write(self.STOP + offset, b"\xc2" + struct.pack("<H", cleanup))
        self.on(self.STOP + offset, callback)

    def audio_add(self):
        self.add.append(self.arg(0))
        self.mu.reg_write(self.r.UC_X86_REG_EAX, 0x777)

    def call(self, va, this=0, args=(), stop=None):
        esp = self.STACK + 0x2800
        self.write(esp, struct.pack("<" + "I" * (len(args) + 1), self.STOP, *args))
        self.mu.reg_write(self.r.UC_X86_REG_ESP, esp)
        self.mu.reg_write(self.r.UC_X86_REG_ECX, this)
        self.mu.reg_write(self.r.UC_X86_REG_EFLAGS, 0x246)
        self.mu.emu_start(va, self.STOP if stop is None else stop, count=10000)
        assert self.mu.reg_read(self.r.UC_X86_REG_EIP) == (self.STOP if stop is None else stop)
        return esp

    def draw(self, weather, frame):
        self.put(self.WEATHER + 0x10, weather)
        self.put(self.CLIENT + 0x10, frame)
        self.call(0x497D00, self.CLOUD)
        assert self.get(self.WEATHER + 0x10) == weather
        return (
            self.get(self.CLOUD + 0xBC),
            self.get(self.CLOUD + 0xC0),
            self.get(self.CLOUD + 0xC4),
            struct.unpack("<3f", self.mu.mem_read(self.CLOUD + 0xD4, 12)),
        )


@pytest.mark.parametrize("weather", [0, 1, 2, 3, 4, 5, 6, 0xFFFFFFFF])
def test_visual_hook_changes_only_local_id_and_native_comparison_flags(weather):
    h = Native()
    h.put(h.WEATHER + 0x10, weather)
    h.mu.reg_write(h.r.UC_X86_REG_EAX, h.WEATHER)
    h.mu.reg_write(h.r.UC_X86_REG_EBX, 1)
    h.mu.reg_write(h.r.UC_X86_REG_ESP, h.STACK + 0x2800)
    h.mu.emu_start(FOGGY_VISUAL_HOOK, FOGGY_VISUAL_HOOK + 5, count=30)
    assert h.mu.reg_read(h.r.UC_X86_REG_ECX) == (1 if weather == 6 else weather)
    assert bool(h.mu.reg_read(h.r.UC_X86_REG_EFLAGS) & 0x40) == (weather in (1, 6))
    assert h.get(h.WEATHER + 0x10) == weather


def test_foggy_matches_the_complete_cloudy_state_machine_and_its_exit():
    original, foggy = Native(False), Native()
    for frame in range(1, 300):
        assert original.draw(1, frame) == foggy.draw(6, frame)
    assert foggy.get(foggy.CLOUD + 0xC0) == 2
    assert foggy.config == [6]
    for frame in range(300, 600):
        assert original.draw(0, frame) == foggy.draw(0, frame)
    assert foggy.get(foggy.CLOUD + 0xC0) == 0


@pytest.mark.parametrize("weather", [0, 1, 2, 3, 4, 5])
def test_other_native_weather_state_machine_is_unchanged(weather):
    original, patched = Native(False), Native()
    for frame in range(1, 8):
        assert original.draw(weather, frame) == patched.draw(weather, frame)


def test_cloudy_to_foggy_keeps_dimming_and_duplicate_client_frame_is_idle():
    h = Native()
    before = h.draw(1, 1)
    assert h.draw(6, 1) == before
    after = h.draw(6, 2)
    assert after[0:2] == (1, 1) and after[2] == before[2] - 1
    assert h.config == [1]
    assert h.draw(1, 3)[2] == after[2] - 1


@pytest.mark.parametrize("mode", [0, 1, 2])
def test_cloud_graphics_gate_matches_original_cloudy(mode):
    a, b = Native(False), Native()
    a.put(0xD9989C, mode)
    b.put(0xD9989C, mode)
    for frame in (1, 2, 3):
        assert a.draw(1, frame) == b.draw(6, frame)


@pytest.mark.parametrize("weather", [0, 1, 2, 3, 4, 5, 6])
def test_native_cloud_texture_choice_and_registers(weather):
    h = Native()
    h.put(h.WEATHER + 0x10, weather)
    h.mu.reg_write(h.r.UC_X86_REG_EAX, h.WEATHER)
    h.mu.reg_write(h.r.UC_X86_REG_EBX, 1)
    h.mu.reg_write(h.r.UC_X86_REG_ECX, 0x12345678)
    esp = h.STACK + 0x2800
    h.mu.reg_write(h.r.UC_X86_REG_ESP, esp)
    stop = 0x496F52 if weather in (1, 6) else 0x496F55
    h.mu.emu_start(FOGGY_TEXTURE_HOOK, stop, count=30)
    assert h.mu.reg_read(h.r.UC_X86_REG_ECX) == 0x12345678
    assert h.mu.reg_read(h.r.UC_X86_REG_EAX) == h.WEATHER
    assert h.mu.reg_read(h.r.UC_X86_REG_ESP) == esp
    assert h.get(h.WEATHER + 0x10) == weather


@pytest.mark.parametrize("weather", [0, 1, 2, 3, 4, 5, 6, 7, 0xFFFFFFFF, 0x80000000])
def test_full_native_sound_lifecycle_bounds_the_index_and_stops_the_old_event(weather):
    h = Native()
    h.put(h.WEATHER + 0x10, weather)
    h.put(h.WEATHER + 0x14, 0x123)
    for index in range(5):
        h.put(h.WEATHER + 0x30 + 8 * index, 0x100 + index)
    h.put(h.WEATHER + 0x60, 0xDEADBEEF)
    esp = h.call(0x719DEE, h.WEATHER)
    expected = weather if weather < 5 else 0
    assert h.remove == [0x123] and len(h.add) == 1
    assert h.event_refs == [h.WEATHER + 0x30 + expected * 8]
    assert h.get(h.WEATHER + 0x10) == weather
    assert h.get(h.WEATHER + 0x14) == 0x777
    assert h.mu.reg_read(h.r.UC_X86_REG_ESP) == esp + 4


def test_foggy_without_none_sound_is_silent_and_releases_the_old_sound():
    h = Native()
    h.put(h.WEATHER + 0x10, 6)
    h.put(h.WEATHER + 0x14, 0x123)
    h.call(0x719DEE, h.WEATHER)
    assert h.remove == [0x123] and h.add == [] and h.event_refs == []
    assert h.get(h.WEATHER + 0x14) == 1


@pytest.mark.parametrize("weather", [0, 1, 2, 3, 4, 5, 6])
def test_native_specialpower_dispatch_preserves_sentinel_and_the_real_weather_id(weather):
    h = Native()
    h.put(h.TEXT + 0x64, weather)
    h.put(h.TEXT + 0x30, 3)
    h.put(h.TEXT + 0x70, 9)
    h.mu.reg_write(h.r.UC_X86_REG_EBX, h.TEXT)
    h.call(0x897B2C, stop=0x897D14)
    assert h.get(h.WEATHER + 0x10) == (0 if weather == 5 else weather)
    assert h.get(h.WEATHER + 0x28) == (0 if weather in (0, 5) else 3)
    assert len(h.remove) == (0 if weather in (0, 5) else 1)


def test_native_expiry_counts_logic_updates_and_returns_to_none():
    h = Native()
    h.call(0x71A024, h.WEATHER, (6, 9, 3))
    assert h.get(h.WEATHER + 0x10) == 6
    for left in (2, 1, 0):
        h.call(0x71A09E, h.WEATHER)
        assert h.get(h.WEATHER + 0x28) == left
        assert h.get(h.WEATHER + 0x10) == (6 if left else 0)
    assert len(h.remove) == 2


@pytest.mark.parametrize("weather", [0, 1, 2, 3, 4, 5, 6, 0xFFFFFFFF])
def test_native_lightning_bounds_are_unchanged(weather):
    h = Native()
    h.put(h.WEATHER + 0x10, weather)
    for index in range(5):
        h.write(h.WEATHER + 0x34 + index * 8, b"\x01")
    h.call(0x719BE4, h.WEATHER)
    assert h.mu.reg_read(h.r.UC_X86_REG_EAX) & 0xFF == (1 if weather < 5 else 0)


@pytest.mark.parametrize("weather", [1, 6])
def test_real_virtual_getter_is_consumed_as_one_minus_rgb_by_scene_lighting(weather):
    h = Native()
    for frame in range(1, 256):
        h.draw(weather, frame)
    h.mu.reg_write(h.r.UC_X86_REG_EBP, h.STACK + 0x1000)
    h.mu.reg_write(h.r.UC_X86_REG_EBX, 0)
    h.mu.reg_write(h.r.UC_X86_REG_XMM0, 0x3F800000)
    h.call(0x4713C0, stop=0x47141C)
    actual = struct.unpack("<3f", h.mu.mem_read(h.STACK + 0x1000 - 0x20, 12))
    assert actual == pytest.approx((0.85, 0.8, 0.75))


def cstring(h, pointer):
    data = bytearray()
    for i in range(256):
        byte = bytes(h.mu.mem_read(pointer + i, 1))
        if byte == b"\0":
            return data.decode("ascii")
        data += byte
    raise AssertionError("Unterminated test string")


@pytest.mark.parametrize(
    "name,value",
    [
        ("NONE", 0),
        ("cloudy", 1),
        ("RAINY", 2),
        ("CLOUDYRAINY", 3),
        ("SUNNY", 4),
        ("MOUNTED", 5),
        ("FOGGY", 6),
        ("fOgGy", 6),
        ("WEAPON_TOGGLE", None),
        ("MOVING", None),
        ("INVALID", None),
    ],
)
def test_actual_changeweather_parser_and_null_terminated_native_lookup(name, value):
    h = Native()
    h.write(h.TEXT, name.encode() + b"\0")
    h.stub(0x60, 4, lambda: h.mu.reg_write(h.r.UC_X86_REG_EAX, h.TEXT))
    # Only token retrieval and the imported string comparison are stubs; both
    # native lookup functions and the entire ChangeWeather parser execute.
    h.write(0x42DC9F, b"\xe9" + struct.pack("<i", h.STOP + 0x60 - 0x42DCA4))

    def compare():
        a, b = cstring(h, h.arg(0)).lower(), cstring(h, h.arg(1)).lower()
        h.mu.reg_write(h.r.UC_X86_REG_EAX, (a > b) - (a < b))

    h.stub(0x70, 0, compare)
    h.put(0xBD051C, h.STOP + 0x70)
    h.write(0x42F3C1, b"\xc3")
    esp = h.call(
        0x8966F9, args=(h.CLIENT, 0, h.TEXT + 0x100, 0), stop=0x42F3C1 if value is None else None
    )
    if value is not None:
        assert h.get(h.TEXT + 0x100) == value
        assert h.mu.reg_read(h.r.UC_X86_REG_ESP) == esp + 4  # cdecl caller owns arguments


def snapshot(h, mode, values=None, version=4):
    """Execute the whole native Xfer method; replace only the external I/O services."""
    stream = [] if values is None else list(values)
    calls = []
    xfer, table = h.TEXT, h.TEXT + 0x100
    h.put(xfer, table)

    def transfer(pointer, count):
        calls.append((pointer, count))
        if mode == "save":
            stream.append(bytes(h.mu.mem_read(pointer, count)))
        else:
            data = stream.pop(0)
            assert len(data) == count
            h.mu.mem_write(pointer, data)

    def version_io():
        h.mu.mem_write(h.arg(0) + 1, bytes([version]))

    h.stub(0x80, 4, version_io)
    h.put(table + 0x28, h.STOP + 0x80)
    h.stub(0x90, 12, lambda: transfer(h.arg(1), h.arg(2)))
    h.put(table + 0x94, 0xA1F8B5)  # actual enum-width checks and enu4 transfer
    h.put(table + 0x98, h.STOP + 0x90)
    h.stub(0xA0, 4, lambda: None)  # empty AsciiString: external string I/O
    h.put(table + 0x6C, h.STOP + 0xA0)
    h.stub(0xB0, 4, lambda: transfer(h.arg(0), 4))
    h.put(table + 0x78, h.STOP + 0xB0)
    h.stub(0xC0, 8, lambda: None)  # external AudioManager handle mapping
    h.put(h.VTABLE + 0x160, h.STOP + 0xC0)
    h.write(0x763EDF, b"\xc2\x04\x00")  # unrelated object filter snapshot
    h.write(0x71A1A7, b"\xc2\x04\x00")  # unrelated modifier flag snapshot
    h.write(0xA3CF28, b"\xc3")
    h.on(0xA3CF28, lambda: h.mu.mem_write(h.arg(0), bytes([h.arg(1)]) * h.arg(2)))
    h.call(0x71A2E3, h.WEATHER + 0xC, (xfer,))
    return stream, calls


@pytest.mark.parametrize("weather", [0, 1, 2, 3, 4, 6])
@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_native_snapshot_keeps_four_byte_weather_id_and_existing_timer_version_gates(
    weather, version
):
    writer, reader = Native(), Native()
    writer.put(writer.WEATHER + 0x10, weather)
    writer.put(writer.WEATHER + 0x28, 1234)
    writer.put(writer.WEATHER + 0x2C, 5678)
    data, calls = snapshot(writer, "save", version=version)
    assert calls[0] == (writer.WEATHER + 0x10, 4)
    assert data[0] == struct.pack("<I", weather)
    left, _ = snapshot(reader, "load", values=data, version=version)
    assert not left and reader.get(reader.WEATHER + 0x10) == weather
    assert reader.get(reader.WEATHER + 0x28) == (1234 if version >= 3 else 0)
    assert reader.get(reader.WEATHER + 0x2C) == (5678 if version >= 3 else 0)
    # The actual Snapshot LoadPostProcess thunk re-enters the now-bounded audio path.
    reader.call(0x71A0D6, reader.WEATHER + 0xC)
    assert reader.get(reader.WEATHER + 0x10) == weather
    assert reader.get(reader.WEATHER + 0x14) == 1


@pytest.mark.parametrize("source", [0, 1, 2, 3, 4, 6])
@pytest.mark.parametrize("target", [0, 1, 2, 3, 4, 6])
def test_all_direct_weather_switches_keep_native_duration_and_sound_semantics(source, target):
    h = Native()
    h.call(0x71A024, h.WEATHER, (source, 0, 10))
    h.call(0x71A024, h.WEATHER, (target, 0, 20))
    assert h.get(h.WEATHER + 0x10) == target
    expected = (10 if source else 0) if target == source else 20
    assert h.get(h.WEATHER + 0x28) == expected


@pytest.mark.parametrize("weather", [0, 1, 6, 0xFFFFFFFF])
@pytest.mark.parametrize("hook", [FOGGY_VISUAL_HOOK, FOGGY_SOUND_HOOK, FOGGY_TEXTURE_HOOK])
def test_trampoline_abi_matches_the_original_local_interpretation(hook, weather):
    results = []
    for patched in (False, True):
        h = Native(patched)
        local = (
            (weather if weather < 5 else 0)
            if hook == FOGGY_SOUND_HOOK
            else (1 if weather == 6 else weather)
        )
        h.put(h.WEATHER + 0x10, weather if patched else local)
        registers = [
            getattr(h.r, f"UC_X86_REG_{name}")
            for name in (
                "EAX",
                "EBX",
                "ECX",
                "EDX",
                "ESI",
                "EDI",
                "EBP",
                "ESP",
                "EFLAGS",
                *[f"XMM{i}" for i in range(8)],
                "MXCSR",
                "FPCW",
                "FPSW",
                "FPTAG",
                "ST0",
                "ST1",
            )
        ]
        for name in ("EAX", "ECX", "EDX", "EDI"):
            h.mu.reg_write(getattr(h.r, f"UC_X86_REG_{name}"), 0x12345678)
        h.mu.reg_write(h.r.UC_X86_REG_EAX, h.WEATHER)
        h.mu.reg_write(h.r.UC_X86_REG_ESI, h.WEATHER)
        h.mu.reg_write(h.r.UC_X86_REG_EBX, 1)
        h.mu.reg_write(h.r.UC_X86_REG_EBP, h.STACK + 0x1000)
        h.mu.reg_write(h.r.UC_X86_REG_ESP, h.STACK + 0x2800)
        for i in range(8):
            h.mu.reg_write(
                getattr(h.r, f"UC_X86_REG_XMM{i}"), 0xFFEEDDCCBBAA99887766554433221100 + i
            )
        h.mu.reg_write(h.r.UC_X86_REG_FPCW, 0x077F)
        h.mu.reg_write(h.r.UC_X86_REG_FPTAG, 0xFFFF)
        h.mu.reg_write(h.r.UC_X86_REG_MXCSR, 0x7FA0)
        h.write(h.STOP + 0xD0, b"\xd9\xe8\xd9\xeb")
        h.mu.emu_start(h.STOP + 0xD0, h.STOP + 0xD4)
        h.mu.reg_write(h.r.UC_X86_REG_EFLAGS, 0xCD7)
        end = hook + len(FOGGY_NATIVE_HOOK_BYTES[hook])
        if hook == FOGGY_TEXTURE_HOOK:
            end = 0x496F52 if local == 1 else 0x496F55
        h.mu.emu_start(hook, end, count=100)
        assert h.mu.reg_read(h.r.UC_X86_REG_EIP) == end
        assert h.get(h.WEATHER + 0x10) == (weather if patched else local)
        results.append({reg: h.mu.reg_read(reg) for reg in registers})
    assert results[0] == results[1]


def test_public_api_resolves_to_the_experimental_implementations():
    assert PublicFoggyWeatherPatch is FoggyWeatherPatch
    assert FoggyWeatherPatch.experimental
    assert FoggyWeatherPatch.__module__ == "sage_patch.patches.experimental.foggy_weather"
    assert (
        CloudyHardwareFogPatch.__module__ == "sage_patch.patches.experimental.cloudy_hardware_fog"
    )
    assert FoggyWeatherPatch.runtime_verified == "yes"
    assert FoggyWeatherWorldbuilderPatch.experimental
    assert not FoggyWeatherWorldbuilderPatch.runtime_verified  # Editor runtime is not confirmed.


def test_optional_defaults_and_cli_defaults_match():
    patch = FoggyWeatherPatch()
    assert patch.blend_in_ms == BLEND_IN_MS == 10000
    assert patch.blend_out_ms == BLEND_OUT_MS == 10000
    assert patch.fog_start == FOG_START and patch.fog_end == FOG_END
    assert patch.fog_rgb == pytest.approx(FOG_RGB)
    args = build_parser().parse_args(["verify", "foggy-weather", __file__])
    assert FoggyWeatherPatch.from_cli_args(args).options() == patch.options()


@pytest.mark.parametrize(
    "settings",
    [
        {"blend_in_ms": 1250},
        {"blend_out_ms": 4500},
        {"fog_start": 123.5},
        {"fog_end": 2345.5},
        {"fog_rgb": (0.1, 0.3, 0.8)},
        {
            "blend_in_ms": 1000,
            "blend_out_ms": 5000,
            "fog_rgb": (0.5, 0.6, 0.7),
            "fog_start": 800.0,
            "fog_end": 2400.0,
        },
    ],
)
def test_each_optional_setting_survives_detection_and_manifest_rebuild(settings):
    patch, data = FoggyWeatherPatch(**settings), original_image()
    patch.apply(data)
    detected = FoggyWeatherPatch.detect(data)
    assert detected is not None and detected.options() == patch.options()
    records, notes = manifest([detected])
    assert not notes and records[0].experimental
    engine = parse_engine(dump_engine(Engine(patches=records)))
    assert not engine.warnings
    selected, problems = rebuild(engine)
    assert not problems and selected[0].options() == patch.options()
    fresh = original_image()
    selected[0].apply(fresh)
    assert fresh == data


def test_cli_applies_and_verifies_all_five_options_and_reports_them(tmp_path, capsys):
    source, output = tmp_path / "original.dat", tmp_path / "foggy.dat"
    source.write_bytes(original_image())
    options = [
        "--blend-in-ms",
        "1250",
        "--blend-out-ms",
        "4500",
        "--fog-rgb",
        "0.5",
        "0.6",
        "0.7",
        "--fog-start",
        "800",
        "--fog-end",
        "2400",
    ]
    assert (
        main(["apply", "foggy-weather", "--in", str(source), "--out", str(output), *options]) == 0
    )
    assert source.read_bytes() == original_image()
    assert main(["verify", "foggy-weather", str(output), *options]) == 0
    assert main(["verify", "foggy-weather", str(output)]) == 1
    assert main(["info", "foggy-weather", "--file", str(output)]) == 0
    text = capsys.readouterr().out
    for option in ("--blend-in-ms", "--blend-out-ms", "--fog-rgb", "--fog-start", "--fog-end"):
        assert option in text
    assert "1250" in text and "4500" in text
    assert "EXPERIMENTAL" in text


@pytest.mark.parametrize(
    "option",
    [
        ["--blend-in-ms", "0"],
        ["--blend-out-ms", "600001"],
        ["--fog-start", "2001"],
        ["--fog-end", "nan"],
        ["--fog-rgb", "0.1", "1.1", "0.3"],
    ],
)
def test_invalid_cli_profile_fails_before_writing(tmp_path, option):
    source, output = tmp_path / "original.dat", tmp_path / "foggy.dat"
    source.write_bytes(original_image())
    with pytest.raises(ValueError):
        main(["apply", "foggy-weather", "--in", str(source), "--out", str(output), *option])
    assert not output.exists() and source.read_bytes() == original_image()


def test_helper_overrides_one_option_and_keeps_the_configured_profile(tmp_path, monkeypatch):
    configured = FoggyWeatherPatch(1250, 4500, 800, 2400, (0.5, 0.6, 0.7))
    selected = SimpleNamespace(patches=[configured])
    (tmp_path / "applymypatches.py").touch()
    monkeypatch.setattr(foggy_builder, "REPO", tmp_path)
    original_import = foggy_builder.importlib.import_module
    monkeypatch.setattr(
        foggy_builder.importlib,
        "import_module",
        lambda name: selected if name == "applymypatches" else original_import(name),
    )
    built = []

    def build(source, output, mode, patch):
        built.append(patch)
        return {"output": str(output), "output_sha256": "test", "verified_patches": [patch.name]}

    monkeypatch.setattr(foggy_builder, "build", build)
    monkeypatch.setattr(
        sys, "argv", ["builder", "--out", str(tmp_path / "out.dat"), "--blend-in-ms", "2000"]
    )
    foggy_builder.main()
    assert built[0].options() == {**configured.options(), "blend_in_ms": 2000}
    assert not (tmp_path / "out.dat").exists()


def test_editor_helper_rejects_game_profile_options(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "builder",
            "--target",
            "worldbuilder",
            "--out",
            str(tmp_path / "out.exe"),
            "--fog-end",
            "3000",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        foggy_builder.main()
    assert exc.value.code == 2 and not (tmp_path / "out.exe").exists()
