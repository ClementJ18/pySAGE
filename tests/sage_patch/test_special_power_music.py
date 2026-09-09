"""Execute the emitted x86 against local audio/tokenizer stubs, without game data."""

from __future__ import annotations

import faulthandler
import struct

import pytest

from sage_ini.engine import parse_type
from sage_patch import HeroManaPatch, SpecialPowerMusicPatch
from sage_patch.addresses import (
    ASCII_STRING_CTOR,
    ASCII_STRING_DTOR,
    GET_FINAL_OVERRIDE,
    INI_NEXT_TOKEN_OR_NULL,
    SPM_FRAME_HOOK,
    SPM_FRAME_HOOK_BYTES,
    SPM_FRAME_RESUME,
    SPM_MUSIC_POP,
    SPM_MUSIC_RESUME,
    SPM_SCRIPT_MUSIC_PUSH,
    SPM_STOCK_ANCHORS,
    SPM_THE_AUDIO,
    SPM_TIME_GET_TIME_IAT,
    SPM_TRIGGER_HOOK,
    SPM_TRIGGER_HOOK_BYTES,
    THE_PLAYER_LIST,
)
from sage_patch.patches.experimental import special_power_music as spm
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.test_hero_mana import synthetic_image


def image() -> bytearray:
    data = synthetic_image()
    for va, original in (
        (SPM_TRIGGER_HOOK, SPM_TRIGGER_HOOK_BYTES),
        (SPM_FRAME_HOOK, SPM_FRAME_HOOK_BYTES),
        *SPM_STOCK_ANCHORS.items(),
    ):
        off = va_to_offset(data, va)
        assert off is not None
        data[off : off + len(original)] = original
    return data


def test_apply_verify_detect_and_corruption() -> None:
    patch = SpecialPowerMusicPatch()
    data = image()
    patch.apply(data)
    assert patch.verify(data) == []
    assert patch.detect(data) is not None
    saved = bytes(data)
    with pytest.raises(ValueError, match="already"):
        patch.apply(data)
    assert data == saved
    _base, off, size = find_section(data, spm._SECTION)
    data[off + size - 2] ^= 1
    assert patch.verify(data)
    assert patch.detect(data) is None


@pytest.mark.parametrize("music_first", [True, False])
def test_composes_with_hero_mana(music_first: bool) -> None:
    data = image()
    music, mana = SpecialPowerMusicPatch(), HeroManaPatch()
    for patch in (music, mana) if music_first else (mana, music):
        patch.apply(data)
    assert music.verify(data) == []
    assert mana.verify(data) == []


def test_conflict_rejected_without_partial_mutation() -> None:
    data = image()
    off = va_to_offset(data, SPM_FRAME_HOOK)
    assert off is not None
    data[off] ^= 1
    before = bytes(data)
    with pytest.raises(ValueError, match="conflicting"):
        SpecialPowerMusicPatch().apply(data)
    assert data == before


def test_ini_surface_is_supported() -> None:
    field = SpecialPowerMusicPatch().ini_surface().fields[0]
    assert (field.block, field.name) == ("SpecialPower", "MusicOnTrigger")
    assert parse_type(field.type)[1] == ""


class World:
    def __init__(self) -> None:
        unicorn = pytest.importorskip("unicorn")
        from unicorn import x86_const  # noqa: PLC0415 -- optional test dependency

        self.r = x86_const
        self.uc = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
        self.base = 0x1000000
        self.stack = 0x200F000
        self.stop = 0x3000000
        self.template = 0x4000000
        self.token = self.template + 0x1000
        # Unicorn 2.1.4 catches an internal Windows SEH during mapping; suppress
        # misleading fault-handler output here, as in the existing WotR fixture.
        was_enabled = faulthandler.is_enabled()
        faulthandler.disable()
        try:
            for start, size in (
                (0x400000, 0xA00000),
                (self.base, 0x100000),
                (0x2000000, 0x10000),
                (self.stop, 0x1000),
                (self.template, 0x10000),
            ):
                self.uc.mem_map(start, size)
        finally:
            if was_enabled:
                faulthandler.enable()
        self.code = spm._assemble(self.base, ())
        self.uc.mem_write(self.base, spm._build(self.base, ()))
        self.tokens: list[bytes] = []
        self.now = 1000
        self.events: list[tuple[str, object]] = []
        self.music_levels: dict[int, bytes] = {0: b"ScriptMusic"}
        self.music_level = 0
        self.put(self.template + 0x14, 7)
        self.put(SPM_THE_AUDIO, self.template + 0x2000)
        self.put(THE_PLAYER_LIST, self.template + 0x3000)
        self.put(self.template + 0x3010, self.template + 0x4000)
        self.put(SPM_TIME_GET_TIME_IAT, self.stop + 16)
        self.handlers = {
            GET_FINAL_OVERRIDE: (0, "final"),
            INI_NEXT_TOKEN_OR_NULL: (4, "token"),
            ASCII_STRING_CTOR: (4, "ctor"),
            ASCII_STRING_DTOR: (0, "dtor"),
            SPM_SCRIPT_MUSIC_PUSH: (24, "push"),
            SPM_MUSIC_POP: (16, "pop"),
            SPM_MUSIC_RESUME: (16, "resume"),
            self.stop + 16: (0, "time"),
        }
        self.uc.hook_add(unicorn.UC_HOOK_CODE, self.hook)

    def put(self, address: int, value: int) -> None:
        self.uc.mem_write(address, struct.pack("<I", value & 0xFFFFFFFF))

    def get(self, address: int) -> int:
        return struct.unpack("<I", self.uc.mem_read(address, 4))[0]

    def string(self, address: int) -> bytes:
        return bytes(self.uc.mem_read(address, 256)).split(b"\0", 1)[0]

    def hook(self, uc, address, _size, _user) -> None:
        if address not in self.handlers:
            return
        cleanup, kind = self.handlers[address]
        esp = uc.reg_read(self.r.UC_X86_REG_ESP)
        ecx = uc.reg_read(self.r.UC_X86_REG_ECX)
        value = 0
        if kind == "final":
            value = self.template
        elif kind == "token":
            if self.tokens:
                uc.mem_write(self.token, self.tokens.pop(0) + b"\0")
                value = self.token
        elif kind == "ctor":
            self.put(ecx, self.get(esp + 4))
        elif kind == "push":
            args = [self.get(esp + i * 4) for i in range(1, 7)]
            assert args[1:4] == [1, 1, 1]
            assert self.get(args[4]) == 0  # no completion flag / gameplay writes
            assert args[5] == 1  # interruption level; zero overwrites the scripting level
            track = self.string(self.get(args[0]))
            self.music_levels[args[5]] = track
            self.music_level = max(self.music_level, args[5])
            self.events.append((kind, track))
        elif kind in ("pop", "resume"):
            args = [self.get(esp + i * 4) for i in range(1, 5)]
            assert args == ([0, 1, 1, 1] if kind == "pop" else [0, 1, 0, 0])
            self.events.append((kind, args))
            self.music_levels.pop(args[1], None)
            if kind == "resume" and self.music_level == args[1]:
                self.music_level = 0
        elif kind == "time":
            value = self.now
        uc.reg_write(self.r.UC_X86_REG_EAX, value)
        uc.reg_write(self.r.UC_X86_REG_ECX, 0x11111111)
        uc.reg_write(self.r.UC_X86_REG_EDX, 0x22222222)
        if kind != "final":
            uc.reg_write(self.r.UC_X86_REG_XMM0, 12345)
        uc.reg_write(self.r.UC_X86_REG_EIP, self.get(esp))
        uc.reg_write(self.r.UC_X86_REG_ESP, esp + 4 + cleanup)

    def run(self, label: str, args: tuple[int, ...] = ()) -> None:
        self.put(self.stack, self.stop)
        for index, value in enumerate(args):
            self.put(self.stack + 4 + index * 4, value)
        self.uc.reg_write(self.r.UC_X86_REG_ESP, self.stack)
        self.uc.reg_write(self.r.UC_X86_REG_ECX, self.template)
        end = SPM_FRAME_RESUME if label == "frame" else self.stop
        self.uc.emu_start(self.code.label_va(label), end, count=200000)
        assert self.uc.reg_read(self.r.UC_X86_REG_EIP) == end
        assert self.uc.reg_read(self.r.UC_X86_REG_ESP) == self.stack + (
            0 if label == "frame" else 4
        )

    def parse(self, *tokens: bytes) -> None:
        self.tokens = list(tokens)
        self.run("parse", (self.template + 0x5000, self.template, self.template, 0))


def test_retrigger_replaces_deadline_and_resume_only_once() -> None:
    w = World()
    original = bytes(w.uc.mem_read(w.template, 0x88))
    w.parse(b"MusicA", b"100")
    w.run("trigger")
    assert w.events == [("push", b"MusicA")]
    assert w.get(w.base + 4) == 1100
    w.now = 1050
    w.parse(b"MusicB", b"200")
    w.run("trigger")
    assert [e[0] for e in w.events] == ["push", "pop", "push"]
    assert w.events[-1] == ("push", b"MusicB")
    assert w.get(w.base + 4) == 1250
    w.now = 1100
    w.run("frame")
    assert len(w.events) == 3
    w.now = 1250
    w.run("frame")
    w.run("frame")
    assert [e[0] for e in w.events] == ["push", "pop", "push", "resume"]
    assert w.get(w.base) == 0
    assert w.music_level == 0
    assert w.music_levels == {0: b"ScriptMusic"}
    assert bytes(w.uc.mem_read(w.template, 0x88)) == original


@pytest.mark.parametrize(
    "start,duration,elapsed",
    [
        (0xFFFFFFF0, 40, 39),
        (0xFFFFFFF0, 40, 40),
        (100, 200, 90000),
        (0x7FFFFFF0, 40, 40),
        (0, 0x7FFFFFFF, 0x7FFFFFFF),
    ],
)
def test_wallclock_wrap_and_late_frame(start: int, duration: int, elapsed: int) -> None:
    w = World()
    w.now = start
    w.parse(b"Music", str(duration).encode())
    w.run("trigger")
    w.now = (start + elapsed) & 0xFFFFFFFF
    w.run("frame")
    assert (w.events[-1][0] == "resume") == (elapsed >= duration)


@pytest.mark.parametrize(
    "tokens",
    [
        (),
        (b"Music",),
        (b"", b"10"),
        (b"Music", b"-1"),
        (b"Music", b"2147483648"),
        (b"Music", b"999999999999"),
        (b"Music", b"1x"),
        (b"Music", b"1", b"extra"),
        (b"x" * 256, b"10"),
    ],
)
def test_bad_config_is_rejected(tokens: tuple[bytes, ...]) -> None:
    w = World()
    w.parse(*tokens)
    assert w.get(w.base + 12) == 1
    w.run("trigger")
    assert w.events == []


def test_unconfigured_zero_duration_and_missing_audio() -> None:
    w = World()
    w.run("trigger")
    w.parse(b"Music", b"0")
    w.run("trigger")
    assert w.events == []
    w.parse(b"Music", b"5")
    w.put(SPM_THE_AUDIO, 0)
    w.run("trigger")
    assert w.events == []


def test_audio_teardown_drops_active_timer() -> None:
    w = World()
    w.parse(b"Music", b"100")
    w.run("trigger")
    w.put(SPM_THE_AUDIO, 0)
    w.now = 1100
    w.run("frame")
    assert w.get(w.base) == 0
    assert len(w.events) == 1


def test_frame_preserves_registers_flags_and_sse() -> None:
    w = World()
    w.parse(b"Music", b"1")
    w.run("trigger")
    w.now = 1001
    regs = [
        w.r.UC_X86_REG_EAX,
        w.r.UC_X86_REG_EBX,
        w.r.UC_X86_REG_EDX,
        w.r.UC_X86_REG_ESI,
        w.r.UC_X86_REG_EDI,
        w.r.UC_X86_REG_EBP,
        w.r.UC_X86_REG_XMM0,
        w.r.UC_X86_REG_XMM7,
    ]
    for reg in regs:
        w.uc.reg_write(reg, 0x12345678)
    w.uc.reg_write(w.r.UC_X86_REG_EFLAGS, 0x246)
    w.run("frame")
    assert all(w.uc.reg_read(reg) == 0x12345678 for reg in regs)
    assert w.uc.reg_read(w.r.UC_X86_REG_EFLAGS) == 0x246


def test_distinct_ids_and_full_table_do_not_overwrite() -> None:
    w = World()
    w.parse(b"First", b"12")
    w.put(w.template + 0x14, 8)
    w.parse(b"Second", b"13")
    w.put(w.template + 0x14, 7)
    w.run("trigger")
    assert w.events[-1] == ("push", b"First")
    for index in range(spm._ROWS):
        w.put(w.base + spm._STATE_SIZE + index * spm._STRIDE, index + 1)
    w.put(w.template + 0x14, spm._ROWS + 1)
    w.parse(b"Overflow", b"10")
    assert w.get(w.base + 12) == 1


def test_maximum_name_and_invalid_redefinition() -> None:
    w = World()
    name = b"m" * 255
    w.parse(name, b"10")
    w.parse(b"BadReplacement", b"-1")
    w.run("trigger")
    assert w.events == [("push", name)]


def test_trigger_preserves_pending_argument_and_original_return() -> None:
    w = World()
    w.parse(b"Music", b"1")
    w.uc.reg_write(w.r.UC_X86_REG_XMM0, 0x12345678)
    w.uc.reg_write(w.r.UC_X86_REG_EFLAGS, 0x246)
    w.run("trigger", (0x1234,))
    assert w.get(w.stack + 4) == 0x1234
    assert w.uc.reg_read(w.r.UC_X86_REG_EAX) == w.template
    assert w.uc.reg_read(w.r.UC_X86_REG_ECX) == 0x11111111
    assert w.uc.reg_read(w.r.UC_X86_REG_EDX) == 0x22222222
    assert w.uc.reg_read(w.r.UC_X86_REG_XMM0) == 0x12345678
    assert w.uc.reg_read(w.r.UC_X86_REG_EFLAGS) == 0x246
