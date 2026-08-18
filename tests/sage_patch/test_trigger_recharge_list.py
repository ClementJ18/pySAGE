"""Tests for the trigger-recharge list patch.

Two hand-assembled routines, and each is checked the way it can be checked. The matcher touches
nothing but memory it is given, so it is *run* here, against a table of strings that says what
"one of these names" has to mean - the questions a disassembly cannot answer, like whether
``AB`` matches the list ``A B``. The parser cannot be run without an `INI` and four engine
routines behind it, so it is disassembled instead and read back for the calls it makes, in order,
which is the part a wrong byte would silently change.

The rest is the build fingerprint. The patch repoints one entry of a 35-entry table and one
``call`` three megabytes away, and both have to fail loudly on anything that is not the expected
build.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from sage_ini.model.objects import REGISTRY
from sage_ini.model.types import _List
from sage_patch.patches.trigger_recharge_list import (
    ANCHORS,
    ASCII_STRING_COMPARE,
    FIELD_ENTRY_SIZE,
    FIELD_INDEX,
    FIELD_NAME,
    FIELD_OFFSET,
    FIELD_TABLE_VA,
    MATCH_CALL_VA,
    SECTION_NAME,
    TriggerRechargeListPatch,
    build_match,
)
from sage_patch.patches.utils.token_lists import (
    ASCII_STRING_ASSIGN,
    ASCII_STRING_CONCAT_CHAR,
    ASCII_STRING_CONCAT_CSTR,
    ASCII_STRING_DTOR,
    ASCII_STRING_IS_EMPTY,
    INI_NEXT_ASCII_STRING,
    STOCK_ASCII_STRING_PARSER,
)
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import SPECIAL_ABILITY_FIELDS, trigger_recharge_list_image

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


@pytest.fixture
def image() -> bytearray:
    return trigger_recharge_list_image()


def _patched(image: bytearray) -> bytearray:
    data = bytearray(image)
    TriggerRechargeListPatch().apply(data)
    return data


def at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + count])


def _cave(data: bytes | bytearray) -> tuple[int, int]:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    section_va, section_off, _vsize = located
    return section_va, section_off


class TestApply:
    def test_apply_then_verify(self, image: bytearray) -> None:
        data = _patched(image)
        assert TriggerRechargeListPatch().verify(data) == []

    def test_verify_rejects_an_unpatched_image(self, image: bytearray) -> None:
        problems = TriggerRechargeListPatch().verify(image)
        assert problems and SECTION_NAME in problems[0]

    def test_detect(self, image: bytearray) -> None:
        assert TriggerRechargeListPatch.detect(image) is None
        found = TriggerRechargeListPatch.detect(_patched(image))
        assert found is not None and found.name == "trigger-recharge-list"

    def test_applying_twice_fails_rather_than_double_patching(self, image: bytearray) -> None:
        """The second run must be refused at the entry it already rewrote, not silently repoint
        the keyword at a second cave and leave the first one orphaned."""
        data = _patched(image)
        with pytest.raises(ValueError, match="already patched"):
            TriggerRechargeListPatch().apply(data)

    def test_the_repointed_entry_is_the_keyword_and_nothing_else_moves(
        self, image: bytearray
    ) -> None:
        data = _patched(image)
        section_va, _off = _cave(data)

        before = at(image, FIELD_TABLE_VA, (len(SPECIAL_ABILITY_FIELDS) + 1) * FIELD_ENTRY_SIZE)
        after = at(data, FIELD_TABLE_VA, (len(SPECIAL_ABILITY_FIELDS) + 1) * FIELD_ENTRY_SIZE)
        entry = FIELD_INDEX * FIELD_ENTRY_SIZE
        assert before[: entry + 4] == after[: entry + 4]
        assert before[entry + 8 :] == after[entry + 8 :]
        assert struct.unpack_from("<I", after, entry + 4)[0] == section_va

    def test_the_other_ascii_field_keeps_the_stock_parser(self, image: bytearray) -> None:
        """`AttributeModifier` holds the same stock parse function in the same table. It must be
        left alone: it is a single name, and nothing reads it as a list."""
        data = _patched(image)
        index = [name for name, _off in SPECIAL_ABILITY_FIELDS].index("AttributeModifier")
        entry = at(data, FIELD_TABLE_VA + index * FIELD_ENTRY_SIZE, FIELD_ENTRY_SIZE)
        assert struct.unpack_from("<I", entry, 4)[0] == STOCK_ASCII_STRING_PARSER

    def test_the_walks_compare_is_repointed_at_the_matcher(self, image: bytearray) -> None:
        data = _patched(image)
        section_va, _off = _cave(data)
        target = MATCH_CALL_VA + 5 + struct.unpack("<i", at(data, MATCH_CALL_VA + 1, 4))[0]
        assert at(data, MATCH_CALL_VA, 1) == b"\xe8"
        assert target != ASCII_STRING_COMPARE
        assert section_va < target < section_va + len(_cave_bytes(data))

    def test_a_moved_field_offset_is_refused(self, image: bytearray) -> None:
        """The offset is what ties the entry being repointed to the field the matcher reads."""
        off = va_to_offset(image, FIELD_TABLE_VA + FIELD_INDEX * FIELD_ENTRY_SIZE + 12)
        assert off is not None
        struct.pack_into("<I", image, off, FIELD_OFFSET + 4)
        with pytest.raises(ValueError, match="ModuleData"):
            TriggerRechargeListPatch().apply(image)

    def test_a_renamed_entry_is_refused(self, image: bytearray) -> None:
        name_va = struct.unpack("<I", at(image, FIELD_TABLE_VA + FIELD_INDEX * FIELD_ENTRY_SIZE, 4))
        off = va_to_offset(image, name_va[0])
        assert off is not None
        image[off] = ord("X")
        with pytest.raises(ValueError, match="not the expected build"):
            TriggerRechargeListPatch().apply(image)

    @pytest.mark.parametrize("va", [va for va, _blob, _what in ANCHORS])
    def test_a_disturbed_anchor_is_refused(self, image: bytearray, va: int) -> None:
        off = va_to_offset(image, va)
        assert off is not None
        image[off] ^= 0xFF
        with pytest.raises(ValueError, match="not the expected build"):
            TriggerRechargeListPatch().apply(image)


def _cave_bytes(data: bytes | bytearray) -> bytes:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    _va, off, vsize = located
    return bytes(data[off : off + vsize])


class TestParseRoutine:
    """The parser, read back from the cave. What a wrong byte changes here is which engine routine
    runs, so the calls are checked by target and in order."""

    def _instructions(self, data: bytes | bytearray) -> list[tuple[int, str, str]]:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        section_va, _off = _cave(data)
        return [
            (i.address, i.mnemonic, i.op_str)
            for i in md.disasm(_cave_bytes(data), section_va)
            if i.address < section_va + len(_cave_bytes(data))
        ]

    def test_it_calls_the_engine_routines_in_order(self, image: bytearray) -> None:
        data = _patched(image)
        calls = [
            int(op, 16) for _addr, mnemonic, op in self._instructions(data) if mnemonic == "call"
        ]
        # every call in the whole cave: the parser's, in order, and none from the matcher
        assert calls == [
            INI_NEXT_ASCII_STRING,
            ASCII_STRING_IS_EMPTY,  # is there a token?
            ASCII_STRING_IS_EMPTY,  # is the accumulator still empty?
            ASCII_STRING_CONCAT_CHAR,  # the separator
            ASCII_STRING_CONCAT_CSTR,  # the token
            ASCII_STRING_ASSIGN,  # into the field
            ASCII_STRING_DTOR,
            ASCII_STRING_DTOR,
        ]

    def test_it_reads_the_ini_and_writes_the_field_from_the_cdecl_frame(
        self, image: bytearray
    ) -> None:
        """A cdecl field parser takes ``(INI *, instance, store, userData)``: the `INI` at
        ``[ebp+8]`` and the field at ``[ebp+0x10]``. Reading the wrong slot would parse into the
        instance pointer."""
        data = _patched(image)
        text = [f"{m} {o}" for _a, m, o in self._instructions(data)]
        assert "mov ecx, dword ptr [ebp + 8]" in text
        assert "mov ecx, dword ptr [ebp + 0x10]" in text

    def test_it_leaves_the_stack_the_way_a_cdecl_callee_must(self, image: bytearray) -> None:
        data = _patched(image)
        body = [f"{m} {o}".strip() for _a, m, o in self._instructions(data)]
        assert body[:3] == ["push ebp", "mov ebp, esp", "sub esp, 8"]
        # `ret` with no immediate: the INI parser cleans its own four arguments.
        assert "leave" in body
        assert body[body.index("leave") + 1] == "ret"


@dataclass
class Machine:
    """An interpreter for the twenty-odd instruction forms `build_match` emits, and nothing else.

    Deliberately narrow, for the reason the campaign-select one is: an unknown opcode raises, so
    an instruction added to the matcher without a test to match it fails here rather than being
    quietly skipped. The matcher calls nothing and writes nothing, so a byte-addressed dictionary
    and six registers are the whole machine.
    """

    code: bytes
    mem: dict[int, int] = field(default_factory=dict)
    regs: dict[str, int] = field(
        default_factory=lambda: {"eax": 0, "ecx": 0, "edx": 0, "ebx": 0, "esi": 0, "edi": 0}
    )
    stack: list[int] = field(default_factory=list)
    #: The one stack argument, as `[esp+0x10]` reaches it past the three saved registers.
    argument: int = 0
    zf: bool = False

    def write(self, va: int, blob: bytes) -> None:
        for index, byte in enumerate(blob):
            self.mem[va + index] = byte

    def _dword(self, va: int) -> int:
        return int.from_bytes(bytes(self.mem.get(va + i, 0) for i in range(4)), "little")

    def _set_low(self, register: str, value: int) -> None:
        self.regs[register] = (self.regs[register] & ~0xFF) | (value & 0xFF)

    def run(self, limit: int = 10_000) -> int:
        code, ip = self.code, 0
        for _ in range(limit):
            head = code[ip : ip + 4]
            if head[:1] == b"\x56":  # push esi
                self.stack.append(self.regs["esi"])
                ip += 1
            elif head[:1] == b"\x57":  # push edi
                self.stack.append(self.regs["edi"])
                ip += 1
            elif head[:1] == b"\x53":  # push ebx
                self.stack.append(self.regs["ebx"])
                ip += 1
            elif head[:2] == b"\x8b\x01":  # mov eax, [ecx]
                self.regs["eax"] = self._dword(self.regs["ecx"])
                ip += 2
            elif head == b"\x8b\x44\x24\x10":  # mov eax, [esp+0x10]
                assert len(self.stack) == 3, "the argument is not where the matcher reads it"
                self.regs["eax"] = self.argument
                ip += 4
            elif head[:2] == b"\x8b\x00":  # mov eax, [eax]
                self.regs["eax"] = self._dword(self.regs["eax"])
                ip += 2
            elif head[:2] == b"\x85\xc0":  # test eax, eax
                self.zf = self.regs["eax"] == 0
                ip += 2
            elif head[:2] == b"\x8d\x78":  # lea edi, [eax+d8]
                self.regs["edi"] = self.regs["eax"] + code[ip + 2]
                ip += 3
            elif head[:2] == b"\x8d\x70":  # lea esi, [eax+d8]
                self.regs["esi"] = self.regs["eax"] + code[ip + 2]
                ip += 3
            elif head[:2] == b"\x8a\x06":  # mov al, [esi]
                self._set_low("eax", self.mem.get(self.regs["esi"], 0))
                ip += 2
            elif head[:2] == b"\x8a\x13":  # mov dl, [ebx]
                self._set_low("edx", self.mem.get(self.regs["ebx"], 0))
                ip += 2
            elif head[:1] == b"\x3c":  # cmp al, imm8
                self.zf = (self.regs["eax"] & 0xFF) == code[ip + 1]
                ip += 2
            elif head[:2] == b"\x84\xc0":  # test al, al
                self.zf = (self.regs["eax"] & 0xFF) == 0
                ip += 2
            elif head[:2] == b"\x3a\xc2":  # cmp al, dl
                self.zf = (self.regs["eax"] & 0xFF) == (self.regs["edx"] & 0xFF)
                ip += 2
            elif head[:3] == b"\x80\x3b\x00":  # cmp byte [ebx], 0
                self.zf = self.mem.get(self.regs["ebx"], 0) == 0
                ip += 3
            elif head[:2] == b"\x8b\xdf":  # mov ebx, edi
                self.regs["ebx"] = self.regs["edi"]
                ip += 2
            elif head[:1] == b"\x46":  # inc esi
                self.regs["esi"] += 1
                ip += 1
            elif head[:1] == b"\x43":  # inc ebx
                self.regs["ebx"] += 1
                ip += 1
            elif head[:2] == b"\x33\xc0":  # xor eax, eax
                self.regs["eax"] = 0
                ip += 2
            elif head[:1] == b"\x40":  # inc eax
                self.regs["eax"] += 1
                ip += 1
            elif head[:1] == b"\xe9":  # jmp rel32
                ip += 5 + struct.unpack_from("<i", code, ip + 1)[0]
            elif head[:2] == b"\x0f\x84":  # je rel32
                ip += 6 + (struct.unpack_from("<i", code, ip + 2)[0] if self.zf else 0)
            elif head[:2] == b"\x0f\x85":  # jne rel32
                ip += 6 + (0 if self.zf else struct.unpack_from("<i", code, ip + 2)[0])
            elif head[:1] == b"\x5b":  # pop ebx
                self.regs["ebx"] = self.stack.pop()
                ip += 1
            elif head[:1] == b"\x5f":  # pop edi
                self.regs["edi"] = self.stack.pop()
                ip += 1
            elif head[:1] == b"\x5e":  # pop esi
                self.regs["esi"] = self.stack.pop()
                ip += 1
            elif head[:3] == b"\xc2\x04\x00":  # ret 4
                return self.regs["eax"]
            else:
                raise AssertionError(f"unknown opcode at +{ip}: {code[ip : ip + 4].hex()}")
        raise AssertionError("the matcher did not return")


_BASE_VA = 0x00E00000
_NAME_HANDLE, _NAME_BUFFER = 0x00A00000, 0x00A01000
_LIST_HANDLE, _LIST_BUFFER = 0x00B00000, 0x00B01000
_CHARS = 8  # where an AsciiString's characters sit in the buffer its handle points at


def matches(name: str | None, listed: str | None) -> bool:
    """Run the matcher over ``name`` against ``listed``, both as `AsciiString`s - None for a
    never-assigned one, whose handle holds NULL. Returns what the caller reads: ``eax == 0``."""
    machine = Machine(build_match(_BASE_VA))
    machine.write(_NAME_HANDLE, struct.pack("<I", _NAME_BUFFER if name is not None else 0))
    machine.write(_LIST_HANDLE, struct.pack("<I", _LIST_BUFFER if listed is not None else 0))
    if name is not None:
        machine.write(_NAME_BUFFER + _CHARS, name.encode("ascii") + b"\x00")
    if listed is not None:
        machine.write(_LIST_BUFFER + _CHARS, listed.encode("ascii") + b"\x00")
    machine.regs["ecx"] = _NAME_HANDLE
    machine.argument = _LIST_HANDLE
    return machine.run() == 0


class TestMatcher:
    @pytest.mark.parametrize(
        ("name", "listed"),
        [
            ("A", "A"),  # the one-name list stock already understood
            ("A", "A B C"),
            ("B", "A B C"),
            ("C", "A B C"),
            ("B", "  A   B  "),  # runs of separators, and both ends of the string
            ("AA", "A AA"),  # a token that is a suffix of the name, and vice versa
            ("A", "AA A"),
        ],
    )
    def test_a_listed_name_matches(self, name: str, listed: str) -> None:
        assert matches(name, listed)

    @pytest.mark.parametrize(
        ("name", "listed"),
        [
            ("D", "A B C"),
            ("AB", "A B"),  # not two tokens run together
            ("A", "AB"),  # not a prefix
            ("BC", "A B C"),  # not a suffix
            ("Ab", "A ab B"),  # case-sensitive, exactly as the compare it replaces was
            ("A", ""),
            ("", "A"),
            (None, "A"),  # a template with no name
            ("A", None),  # a field never written
        ],
    )
    def test_an_unlisted_name_does_not(self, name: str | None, listed: str | None) -> None:
        assert not matches(name, listed)

    def test_it_restores_the_registers_the_walk_keeps_its_cursor_in(self) -> None:
        """The loop this sits inside holds its module cursor, its module and its `ModuleData` in
        `esi`, `edi` and `ebx` across the call, exactly as the `__thiscall` being replaced did."""
        machine = Machine(build_match(_BASE_VA))
        machine.regs.update({"esi": 0x11111111, "edi": 0x22222222, "ebx": 0x33333333})
        machine.regs["ecx"] = _NAME_HANDLE
        machine.argument = _LIST_HANDLE
        machine.write(_NAME_HANDLE, struct.pack("<I", _NAME_BUFFER))
        machine.write(_LIST_HANDLE, struct.pack("<I", _LIST_BUFFER))
        machine.write(_NAME_BUFFER + _CHARS, b"B\x00")
        machine.write(_LIST_BUFFER + _CHARS, b"A B\x00")

        assert machine.run() == 0
        assert machine.regs["esi"] == 0x11111111
        assert machine.regs["edi"] == 0x22222222
        assert machine.regs["ebx"] == 0x33333333
        assert machine.stack == []


class TestIniSurface:
    def test_it_retypes_the_keyword_as_a_list(self) -> None:
        surface = TriggerRechargeListPatch().ini_surface()
        assert [(f.block, f.name, f.type) for f in surface.fields] == [
            ("SpecialPowerModuleBehavior", FIELD_NAME, "Ref[]:specialpowers")
        ]

    def test_the_model_takes_it_and_every_special_power_module_sees_it(self) -> None:
        """Declared on the base the modules derive from, which is what the shared field-parse
        table means - so the module that reads the field and one that merely parses it agree.
        Reverting has to put the scalar back, or a later conversion would still read a list."""
        refresh = REGISTRY["SpecialPowerTimerRefreshSpecialPower"]
        heal = REGISTRY["PlayerHealSpecialPower"]
        stock = refresh._fieldspec[FIELD_NAME]

        with TriggerRechargeListPatch().ini_surface().activate() as problems:
            assert problems == []
            listed = refresh._fieldspec[FIELD_NAME]
            assert listed is not stock
            assert listed is heal._fieldspec[FIELD_NAME]
            assert isinstance(listed, _List)

        assert refresh._fieldspec[FIELD_NAME] is stock


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
class TestInstalledBinary:
    """The addresses, against the real build. The stand-in plants what the patch expects, so only
    this can say the real binary holds it there."""

    @pytest.fixture
    def game(self) -> bytes:
        return _GAME_DAT.read_bytes()

    def test_every_anchor_holds_its_stock_bytes(self, game: bytes) -> None:
        for va, expected, what in ANCHORS:
            assert at(game, va, len(expected)) == expected, what

    def test_the_table_entry_is_the_keyword_parsed_as_one_token(self, game: bytes) -> None:
        entry = at(game, FIELD_TABLE_VA + FIELD_INDEX * FIELD_ENTRY_SIZE, FIELD_ENTRY_SIZE)
        name_va, parse_fn, userdata, field_off = struct.unpack("<4I", entry)
        assert at(game, name_va, len(FIELD_NAME) + 1) == FIELD_NAME.encode() + b"\x00"
        assert parse_fn == STOCK_ASCII_STRING_PARSER
        assert userdata == 0
        assert field_off == FIELD_OFFSET

    def test_the_keyword_is_named_by_exactly_one_table(self, game: bytes) -> None:
        """One entry means one parse function to repoint. A second table naming the same keyword
        would be a second module parsing it, left on the stock single-token parser."""
        needle = FIELD_NAME.encode() + b"\x00"
        string_off = game.find(needle)
        assert string_off >= 0 and game.find(needle, string_off + 1) < 0
        # .rdata is contiguous here, so the string's VA follows from the entry that points at it
        name_va = struct.unpack("<I", at(game, FIELD_TABLE_VA + FIELD_INDEX * FIELD_ENTRY_SIZE, 4))[
            0
        ]
        pointer = struct.pack("<I", name_va)
        first = game.find(pointer)
        assert first >= 0 and game.find(pointer, first + 1) < 0

    def test_the_walk_still_compares_through_the_call_being_repointed(self, game: bytes) -> None:
        target = MATCH_CALL_VA + 5 + struct.unpack("<i", at(game, MATCH_CALL_VA + 1, 4))[0]
        assert at(game, MATCH_CALL_VA, 1) == b"\xe8"
        assert target == ASCII_STRING_COMPARE

    def test_apply_and_verify_round_trip(self, game: bytes) -> None:
        data = bytearray(game)
        patch = TriggerRechargeListPatch()
        patch.apply(data)
        assert patch.verify(data) == []
        assert TriggerRechargeListPatch.detect(game) is None
