"""Client-local, wall-clock SpecialPower music for RotWK 2.01.

The field parser uses the stock tokenizer and a separate table keyed by the template's
stable numeric ID. +0x14 is an ID, not a NameKey: generating NameKeys at trigger time
would mutate the engine's shared name registry for unconfigured powers. No template,
snapshot, script flag or gameplay state is extended. See README for override limitations.
"""

from __future__ import annotations

import struct

from sage_ini.engine import Engine, FieldDelta

from ...addresses import (
    ASCII_STRING_CTOR,
    ASCII_STRING_DTOR,
    GET_FINAL_OVERRIDE,
    INI_NEXT_TOKEN_OR_NULL,
    SPECIAL_POWER_FIELD_TABLE_REF_OPCODES,
    SPECIAL_POWER_FIELD_TABLE_REFS,
    SPM_FRAME_HOOK,
    SPM_FRAME_HOOK_BYTES,
    SPM_FRAME_RESUME,
    SPM_MUSIC_POP,
    SPM_MUSIC_RESUME,
    SPM_SCRIPT_MUSIC_PUSH,
    SPM_STOCK_ANCHORS,
    SPM_TEMPLATE_ID,
    SPM_THE_AUDIO,
    SPM_TIME_GET_TIME_IAT,
    SPM_TRIGGER_HOOK,
    SPM_TRIGGER_HOOK_BYTES,
    THE_PLAYER_LIST,
)
from ...asm import JA, JAE, JE, JNE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset
from ..utils.field_tables import Entry, entries_before, read_field_table, resolve_table
from ..utils.name_tables import read_cstring

__all__ = ["SpecialPowerMusicPatch"]

_SECTION = ".spmusic"
_FIELD = "MusicOnTrigger"
_ROWS = 1024
_STRIDE = 264  # ID, duration, music name (256 bytes including terminator)
_STATE_SIZE = 32  # active, deadline, audio owner, invalid config count; reserved
_TABLE_OFF = _STATE_SIZE + _ROWS * _STRIDE
_RWX = 0xE0000060


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _branch(site: int, target: int, opcode: int = 0xE9) -> bytes:
    return bytes([opcode]) + struct.pack("<i", target - site - 5)


def _resolve(data: bytes | bytearray) -> int:
    return resolve_table(
        data,
        SPECIAL_POWER_FIELD_TABLE_REFS,
        SPECIAL_POWER_FIELD_TABLE_REF_OPCODES,
        "SpecialPower",
    )


def _offset(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"unmapped address {va:#x}: not RotWK 2.01")
    return off


def _save(a: Asm) -> None:
    # Engine audio touches SSE as well as general registers. Preserve x87/MXCSR/XMM too.
    a.emit(b"\x9c\x60\x89\xe5\x81\xec\x10\x02\x00\x00\x83\xe4\xf0")
    a.emit(b"\x0f\xae\x04\x24")  # fxsave [esp], aligned


def _restore(a: Asm) -> None:
    a.emit(b"\x0f\xae\x0c\x24\x89\xec\x61\x9d")


def _assemble(base: int, entries: tuple[Entry, ...]) -> Asm:
    code_off = _TABLE_OFF + (len(entries) + 2) * 16 + 16
    a = Asm(base + code_off)
    rows = base + _STATE_SIZE

    # EDX = template ID; EAX = matching or first empty row. Bounded linear probing
    # preserves colliding IDs instead of silently replacing another power's config.
    a.label("lookup")
    a.emit(b"\x85\xd2")
    a.jcc(JE, "missing")
    a.emit(0xB8, _u32(rows), 0xB9, _u32(_ROWS))
    a.label("probe")
    a.emit(b"\x39\x10")
    a.jcc(JE, "found")
    a.emit(b"\x83\x38\x00")
    a.jcc(JE, "found")
    a.emit(b"\x05", _u32(_STRIDE), 0x49)
    a.jcc(JNE, "probe")
    a.label("missing")
    a.emit(b"\x31\xc0")
    a.label("found")
    a.emit(0xC3)

    # cdecl (INI*, instance, store, userData). Parse transactionally on the stack;
    # missing/invalid/extra tokens never call the stock fatal integer parser.
    a.label("parse")
    a.emit(b"\x55\x89\xe5\x53\x56\x57\x81\xec\x04\x01\x00\x00")
    a.emit(b"\x89\xe7\x31\xc0\xb9\x40\x00\x00\x00\xfc\xf3\xab")
    a.emit(b"\x8b\x75\x08\x8b\xce\x6a\x00")
    a.call_absolute(INI_NEXT_TOKEN_OR_NULL)
    a.emit(b"\x85\xc0")
    a.jcc(JE, "invalid")
    a.emit(b"\x89\xe7\x31\xc9")  # buffer = esp
    a.label("copy_token")
    a.emit(b"\x8a\x14\x08\x88\x14\x0f\x84\xd2")
    a.jcc(JE, "token_done")
    a.emit(b"\x41\x81\xf9\x00\x01\x00\x00")
    a.jcc(JAE, "invalid")
    a.jmp("copy_token")
    a.label("token_done")
    a.emit(b"\x85\xc9")
    a.jcc(JE, "invalid")
    a.emit(b"\x8b\xce\x6a\x00")
    a.call_absolute(INI_NEXT_TOKEN_OR_NULL)
    a.emit(b"\x85\xc0")
    a.jcc(JE, "invalid")
    a.emit(b"\x89\xc1\x31\xdb\x80\x39\x00")
    a.jcc(JE, "invalid")
    a.label("digits")
    a.emit(b"\x0f\xb6\x11\x85\xd2")
    a.jcc(JE, "duration_done")
    a.emit(b"\x83\xea\x30\x83\xfa\x09")
    a.jcc(JA, "invalid")
    a.emit(b"\x81\xfb", _u32(214748364))
    a.jcc(JA, "invalid")
    a.emit(b"\x6b\xdb\x0a\x01\xd3\x81\xfb", _u32(0x7FFFFFFF))
    a.jcc(JA, "invalid")
    a.emit(0x41)
    a.jmp("digits")
    a.label("duration_done")
    a.emit(b"\x8b\xce\x6a\x00")
    a.call_absolute(INI_NEXT_TOKEN_OR_NULL)
    a.emit(b"\x85\xc0")
    a.jcc(JNE, "invalid")
    a.emit(b"\x8b\x45\x0c\x85\xc0")
    a.jcc(JE, "invalid")
    a.emit(b"\x8b\x50", SPM_TEMPLATE_ID)
    a.call("lookup")
    a.emit(b"\x85\xc0")
    a.jcc(JE, "invalid")
    a.emit(b"\x89\x10\x89\x58\x04\x8d\x78\x08\x89\xe6")
    a.emit(0xB9, _u32(256), b"\xfc\xf3\xa4")
    a.jmp("parse_done")
    a.label("invalid")
    a.emit(b"\xff\x05", _u32(base + 12))
    a.label("parse_done")
    a.emit(b"\x81\xc4\x04\x01\x00\x00\x5f\x5e\x5b\x5d\xc3")

    # Replace the CALL only. The caller's pending push 0 belongs to its later audio
    # constructor; GET_FINAL_OVERRIDE consumes no arguments, and neither does this wrapper.
    a.label("trigger")
    a.call_absolute(GET_FINAL_OVERRIDE)
    _save(a)
    a.emit(b"\x85\xc0")
    a.jcc(JE, "trigger_done")
    a.emit(b"\x8b\x50", SPM_TEMPLATE_ID)
    a.call("lookup")
    a.emit(b"\x85\xc0")
    a.jcc(JE, "trigger_done")
    a.emit(b"\x39\x10")
    a.jcc(JNE, "trigger_done")
    a.emit(b"\x83\x78\x04\x00")
    a.jcc(JE, "trigger_done")
    a.emit(b"\x89\xc6\x8b\x1d", _u32(SPM_THE_AUDIO), b"\x85\xdb")
    a.jcc(JE, "trigger_done")
    # The stock music-action helper tags events with the local player's index.
    a.emit(0xA1, _u32(THE_PLAYER_LIST), b"\x85\xc0")
    a.jcc(JE, "trigger_done")
    a.emit(b"\x83\x78\x10\x00")
    a.jcc(JE, "trigger_done")
    a.emit(b"\x83\x3d", _u32(base), 0)
    a.jcc(JE, "push")
    a.emit(b"\x39\x1d", _u32(base + 8))
    a.jcc(JNE, "push")
    a.emit(b"\x6a\x01\x6a\x01\x6a\x01\x6a\x00\x89\xd9")
    a.call_absolute(SPM_MUSIC_POP)  # (0, 1, immediate-out, immediate-in), ret 16
    a.label("push")
    # Two temporary AsciiStrings: music name and an empty completion flag. Empty
    # suppresses the helper's entire ScriptEngine flag/qualification branch.
    a.emit(b"\x83\xec\x08\xc7\x44\x24\x04\x00\x00\x00\x00")
    a.emit(b"\x8d\x46\x08\x50\x8d\x4c\x24\x04")
    a.call_absolute(ASCII_STRING_CTOR)
    # Level 1 interrupts the script-managed level 0. Pop/Resume also target level 1.
    # Pushing into level 0 replaces the script track and makes Resume(0, 1, ...) inert.
    a.emit(b"\x89\xe7\x8d\x47\x04\x6a\x01\x50\x6a\x01\x6a\x01\x6a\x01\x57")
    a.call_absolute(SPM_SCRIPT_MUSIC_PUSH)  # name, fade-out, no-fade-in, once, empty flag, level 1
    a.emit(b"\x89\xf9")
    a.call_absolute(ASCII_STRING_DTOR)
    a.emit(b"\x83\xc4\x08\xff\x15", _u32(SPM_TIME_GET_TIME_IAT))
    a.emit(b"\x03\x46\x04\xa3", _u32(base + 4))
    a.emit(b"\x89\x1d", _u32(base + 8), b"\xc7\x05", _u32(base), _u32(1))
    a.label("trigger_done")
    _restore(a)
    a.emit(0xC3)

    a.label("frame")
    _save(a)
    a.emit(b"\x83\x3d", _u32(base), 0)
    a.jcc(JE, "frame_done")
    a.emit(b"\x8b\x1d", _u32(SPM_THE_AUDIO), b"\x85\xdb")
    a.jcc(JE, "clear")
    a.emit(b"\x39\x1d", _u32(base + 8))
    a.jcc(JNE, "clear")
    a.emit(b"\xff\x15", _u32(SPM_TIME_GET_TIME_IAT))
    a.emit(b"\x2b\x05", _u32(base + 4))
    a.jcc(0x8, "frame_done")  # JS: signed modular difference, not signed JL after subtraction
    a.emit(b"\x6a\x00\x6a\x00\x6a\x01\x6a\x00\x89\xd9")
    a.call_absolute(SPM_MUSIC_RESUME)  # fade out/in, ret 16; no scripting reset
    a.label("clear")
    a.emit(b"\xc7\x05", _u32(base), _u32(0))
    a.label("frame_done")
    _restore(a)
    a.jmp_absolute(SPM_FRAME_RESUME)
    return a


def _build(base: int, entries: tuple[Entry, ...]) -> bytes:
    code = _assemble(base, entries)
    name_va = base + _TABLE_OFF + (len(entries) + 2) * 16
    table = b"".join(struct.pack("<IIII", *entry) for entry in entries)
    table += struct.pack("<IIII", name_va, code.label_va("parse"), 0, 0) + bytes(16)
    return bytes(_TABLE_OFF) + table + _FIELD.encode().ljust(16, b"\0") + code.finish()


class SpecialPowerMusicPatch(Patch):
    """Expose MusicOnTrigger without growing SpecialPowerTemplate or gameplay state."""

    name = "special-power-music"
    author = "Ostkannit"
    experimental = True
    description = (
        "SpecialPower MusicOnTrigger = <MusicEvent> <DurationMilliseconds>: "
        "local music on each peer, replacing the active track and wall-clock timer"
    )

    def ini_surface(self) -> Engine:
        return Engine(
            fields=(
                FieldDelta(
                    block="SpecialPower",
                    name=_FIELD,
                    type="Opaque[]",
                    patch=self.name,
                ),
            )
        )

    def apply(self, data: bytearray) -> None:
        table_va = _resolve(data)
        entries = read_field_table(data, table_va)
        if (
            find_section(data, _SECTION) is not None
            or entries_before(data, entries, _FIELD) is not None
        ):
            raise ValueError("special-power-music is already applied or MusicOnTrigger exists")
        fields = {read_cstring(data, e[0]): e[3] for e in entries}
        if fields.get("UnitCostDeathType") != 0x84:
            raise ValueError("unexpected SpecialPower table: not RotWK 2.01")
        for site, old in (
            (SPM_TRIGGER_HOOK, SPM_TRIGGER_HOOK_BYTES),
            (SPM_FRAME_HOOK, SPM_FRAME_HOOK_BYTES),
            *SPM_STOCK_ANCHORS.items(),
        ):
            off = _offset(data, site)
            if bytes(data[off : off + len(old)]) != old:
                raise ValueError(f"conflicting hook or wrong build at {site:#x}")
        # Work on a copy so even a failed allocation leaves the caller's buffer intact.
        out = bytearray(data)
        base = allocate_section(out, _SECTION, lambda va: _build(va, entries), _RWX)
        code = _assemble(base, entries)
        for site, old, target, opcode in (
            (SPM_TRIGGER_HOOK, SPM_TRIGGER_HOOK_BYTES, "trigger", 0xE8),
            (SPM_FRAME_HOOK, SPM_FRAME_HOOK_BYTES, "frame", 0xE9),
        ):
            apply_byte_patch(
                out, _offset(out, site), old, _branch(site, code.label_va(target), opcode), target
            )
        for ref in SPECIAL_POWER_FIELD_TABLE_REFS:
            apply_byte_patch(
                out,
                _offset(out, ref) + 1,
                _u32(table_va),
                _u32(base + _TABLE_OFF),
                "MusicOnTrigger table",
            )
        data[:] = out

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, _SECTION)
        if located is None:
            return ["no special-power-music section"]
        base, off, _size = located
        try:
            live = read_field_table(data, _resolve(data))
            preceding = entries_before(data, live, _FIELD)
            if preceding is None:
                return ["no MusicOnTrigger field"]
            code = _assemble(base, preceding)
            expected = _build(base, preceding)
            problems = []
            for site, original in SPM_STOCK_ANCHORS.items():
                start = _offset(data, site)
                if bytes(data[start : start + len(original)]) != original:
                    problems.append(f"stock audio dependency differs at {site:#x}")
            if bytes(data[off : off + len(expected)]) != expected:
                problems.append("special-power-music cave differs from expected code/data")
            row = live[len(preceding)]
            if row[1:] != (code.label_va("parse"), 0, 0):
                problems.append("MusicOnTrigger parser/offset differs")
            for site, label, opcode in (
                (SPM_TRIGGER_HOOK, "trigger", 0xE8),
                (SPM_FRAME_HOOK, "frame", 0xE9),
            ):
                start = _offset(data, site)
                if bytes(data[start : start + 5]) != _branch(site, code.label_va(label), opcode):
                    problems.append(f"{label} hook differs")
            return problems
        except (ValueError, struct.error, IndexError) as exc:
            return [f"invalid special-power-music image: {exc}"]
