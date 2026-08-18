"""Tests for the upgrade grant/remove list patch.

The applier is the routine that matters and it is *run* here rather than read: it walks a string,
copies each token into its own frame and hands the result to three engine calls, and the questions
worth asking - which names get looked up, in what order, which ones get applied and to what - are
questions a disassembly cannot answer. The four calls are intercepted by the interpreter, which is
what makes "it applied `Upgrade_B` to the object it was given" an assertion rather than a reading.

The parser is the shared one from `sage_patch.patches.utils.token_lists`, tested with
`trigger-recharge-list`; what is checked here is that this cave holds exactly one copy of it and
that both keywords point at it.

The rest is the build fingerprint: two rows of an eleven-row table and two `call`s in a function
two and a half megabytes away, all of which must fail loudly on anything that is not the expected
build.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from sage_ini.model.objects import REGISTRY
from sage_ini.model.types import _List
from sage_patch.addresses import THE_UPGRADE_CENTER
from sage_patch.patches.upgrade_grant_lists import (
    ANCHORS,
    FIELD_TABLE_REF_VA,
    FIELD_TABLE_VA,
    FIELDS,
    FIND_UPGRADE,
    GRANT_CALL_VA,
    MAX_NAME,
    OBJECT_GIVE_UPGRADE,
    OBJECT_REMOVE_UPGRADE,
    REMOVE_CALL_VA,
    SECTION_NAME,
    UpgradeGrantListsPatch,
    build_apply,
)
from sage_patch.patches.utils.field_tables import ROW_SIZE
from sage_patch.patches.utils.token_lists import (
    ASCII_STRING_DTOR,
    ASCII_STRING_SET,
    STOCK_ASCII_STRING_PARSER,
    build_list_parser,
)
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import (
    OBJECT_CREATION_UPGRADE_FIELDS,
    upgrade_grant_lists_image,
)

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


@pytest.fixture
def image() -> bytearray:
    return upgrade_grant_lists_image()


def _patched(image: bytearray) -> bytearray:
    data = bytearray(image)
    UpgradeGrantListsPatch().apply(data)
    return data


def at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + count])


def _cave(data: bytes | bytearray) -> tuple[int, bytes]:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    section_va, section_off, vsize = located
    return section_va, bytes(data[section_off : section_off + vsize])


def _call_target(data: bytes | bytearray, va: int) -> int:
    assert at(data, va, 1) == b"\xe8"
    return va + 5 + struct.unpack("<i", at(data, va + 1, 4))[0]


def _row(data: bytes | bytearray, name: str) -> tuple[int, int, int, int]:
    index = [field_name for field_name, _off in OBJECT_CREATION_UPGRADE_FIELDS].index(name)
    return struct.unpack("<4I", at(data, FIELD_TABLE_VA + index * ROW_SIZE, ROW_SIZE))


class TestApply:
    def test_apply_then_verify(self, image: bytearray) -> None:
        data = _patched(image)
        assert UpgradeGrantListsPatch().verify(data) == []

    def test_verify_rejects_an_unpatched_image(self, image: bytearray) -> None:
        problems = UpgradeGrantListsPatch().verify(image)
        assert problems and SECTION_NAME in problems[0]

    def test_detect(self, image: bytearray) -> None:
        assert UpgradeGrantListsPatch.detect(image) is None
        found = UpgradeGrantListsPatch.detect(_patched(image))
        assert found is not None and found.name == "upgrade-grant-lists"

    def test_applying_twice_fails_rather_than_double_patching(self, image: bytearray) -> None:
        data = _patched(image)
        with pytest.raises(ValueError, match="already patched"):
            UpgradeGrantListsPatch().apply(data)

    def test_both_keywords_point_at_the_one_parser(self, image: bytearray) -> None:
        data = _patched(image)
        section_va, _content = _cave(data)
        for name, _offset in FIELDS:
            _name_va, parse_fn, _userdata, _field_off = _row(data, name)
            assert parse_fn == section_va, f"{name} does not parse through the cave's parser"

    def test_the_rest_of_the_row_is_untouched(self, image: bytearray) -> None:
        """Only the parse function moves: the keyword's name and its `ModuleData` offset are what
        tie the row to the field, and rewriting either would retarget the patch silently."""
        data = _patched(image)
        for name, offset in FIELDS:
            before, after = _row(image, name), _row(data, name)
            assert after[0] == before[0]  # the name pointer
            assert after[2] == before[2]  # userData
            assert after[3] == offset  # the ModuleData offset

    def test_thing_to_spawn_keeps_the_stock_parser(self, image: bytearray) -> None:
        """The third `AsciiString` in the same table names an object, not an upgrade, and nothing
        this patch adds reads it. It must come out of the patch untouched."""
        data = _patched(image)
        assert _row(data, "ThingToSpawn")[1] == STOCK_ASCII_STRING_PARSER
        assert _row(data, "ThingToSpawn") == _row(image, "ThingToSpawn")

    def test_each_lookup_is_repointed_at_its_own_applier(self, image: bytearray) -> None:
        data = _patched(image)
        section_va, content = _cave(data)
        grant, remove = _call_target(data, GRANT_CALL_VA), _call_target(data, REMOVE_CALL_VA)

        assert grant != FIND_UPGRADE and remove != FIND_UPGRADE
        assert grant != remove
        for target in (grant, remove):
            assert section_va < target < section_va + len(content)

    def test_the_two_appliers_differ_only_in_the_upgrade_they_call(self) -> None:
        """The granting and removing caves are the same routine aimed at different engine calls.
        Asserting that here is what makes the pair's `build_apply(action)` parameter meaningful:
        a copy that had drifted would show up as more than one differing dword."""
        grant = build_apply(0x00E00000, OBJECT_GIVE_UPGRADE)
        remove = build_apply(0x00E00000, OBJECT_REMOVE_UPGRADE)
        assert len(grant) == len(remove)
        differing = [
            index for index, (a, b) in enumerate(zip(grant, remove, strict=True)) if a != b
        ]
        assert len(differing) <= 4  # one `call rel32` displacement
        start = differing[0]
        assert grant[start - 1] == 0xE8
        assert struct.unpack("<i", grant[start : start + 4])[0] + 0x00E00000 + start + 4 == (
            OBJECT_GIVE_UPGRADE
        )

    def test_a_moved_field_offset_is_refused(self, image: bytearray) -> None:
        index = [name for name, _off in OBJECT_CREATION_UPGRADE_FIELDS].index("GrantUpgrade")
        off = va_to_offset(image, FIELD_TABLE_VA + index * ROW_SIZE + 12)
        assert off is not None
        struct.pack_into("<I", image, off, 0x148)
        with pytest.raises(ValueError, match="ModuleData"):
            UpgradeGrantListsPatch().apply(image)

    def test_a_missing_keyword_is_refused(self, image: bytearray) -> None:
        index = [name for name, _off in OBJECT_CREATION_UPGRADE_FIELDS].index("RemoveUpgrade")
        name_va = struct.unpack("<I", at(image, FIELD_TABLE_VA + index * ROW_SIZE, 4))[0]
        off = va_to_offset(image, name_va)
        assert off is not None
        image[off] = ord("X")
        with pytest.raises(ValueError, match="no 'RemoveUpgrade' entry"):
            UpgradeGrantListsPatch().apply(image)

    def test_a_relocated_table_is_followed_rather_than_bypassed(self, image: bytearray) -> None:
        """The base comes from the reference that names it. Point that reference somewhere else
        and the patch must go there - the failure it prevents is silent, because the stale table
        still holds every byte the patch would assert."""
        moved = FIELD_TABLE_VA + 0x400
        rows = at(image, FIELD_TABLE_VA, (len(OBJECT_CREATION_UPGRADE_FIELDS) + 1) * ROW_SIZE)
        off = va_to_offset(image, moved)
        assert off is not None and off + len(rows) <= len(image)
        image[off : off + len(rows)] = rows
        ref_off = va_to_offset(image, FIELD_TABLE_REF_VA + 1)
        assert ref_off is not None
        struct.pack_into("<I", image, ref_off, moved)

        data = _patched(image)
        section_va, _content = _cave(data)
        index = [name for name, _off in OBJECT_CREATION_UPGRADE_FIELDS].index("GrantUpgrade")
        assert struct.unpack("<I", at(data, moved + index * ROW_SIZE + 4, 4))[0] == section_va
        # ... and the stale copy is left alone
        assert _row(data, "GrantUpgrade")[1] == STOCK_ASCII_STRING_PARSER

    @pytest.mark.parametrize("va", [va for va, _blob, _what in ANCHORS])
    def test_a_disturbed_anchor_is_refused(self, image: bytearray, va: int) -> None:
        off = va_to_offset(image, va)
        assert off is not None
        image[off] ^= 0xFF
        with pytest.raises(ValueError, match="not the expected build"):
            UpgradeGrantListsPatch().apply(image)


class TestCaveLayout:
    def test_the_parser_sits_at_the_base_and_is_the_shared_one(self, image: bytearray) -> None:
        data = _patched(image)
        section_va, content = _cave(data)
        parser = build_list_parser(section_va)
        assert content[: len(parser)] == parser

    def test_the_cave_holds_exactly_one_parser(self, image: bytearray) -> None:
        """Both keywords share it; a second copy would mean one of them pointing at a routine the
        other's tests never reach."""
        data = _patched(image)
        section_va, content = _cave(data)
        head = build_list_parser(section_va)[:16]
        assert content.count(head) == 1


@dataclass
class Machine:
    """An interpreter for the instruction forms `build_apply` emits, and nothing else.

    Deliberately narrow, the way the campaign-select one is: an unknown opcode raises, so an
    instruction added to the cave without a test to match it fails here rather than being quietly
    skipped. It models a real stack (the routine builds a `0x108`-byte frame and copies into it),
    byte-addressed memory, and the six registers the routine uses.

    The four engine calls are **intercepted**, not executed: `AsciiString::set` records the C
    string the cave assembled, `findUpgrade` answers from :attr:`upgrades`, the give/remove call
    records what was applied and to what, and the destructor is a no-op. Each returns with its
    argument dropped, which is what their ``ret 4`` does.
    """

    code: bytes
    base_va: int
    action_va: int
    #: Name -> the `UpgradeTemplate *` `findUpgrade` answers with. Anything else answers NULL.
    upgrades: dict[str, int] = field(default_factory=dict)
    mem: dict[int, int] = field(default_factory=dict)
    regs: dict[str, int] = field(
        default_factory=lambda: {"eax": 0, "ecx": 0, "edx": 0, "esi": 0, "edi": 0, "ebp": 0}
    )
    esp: int = 0x00200000
    zf: bool = False
    #: Every name handed to `findUpgrade`, in order.
    looked_up: list[str] = field(default_factory=list)
    #: Every `(object, template)` the action was called with, in order.
    applied: list[tuple[int, int]] = field(default_factory=list)
    #: What the string the cave built currently holds, as `AsciiString::set` left it.
    name: str = ""
    destructed: int = 0

    def write(self, va: int, blob: bytes) -> None:
        for index, byte in enumerate(blob):
            self.mem[va + index] = byte

    def _dword(self, va: int) -> int:
        return int.from_bytes(bytes(self.mem.get(va + i, 0) for i in range(4)), "little")

    def _write_dword(self, va: int, value: int) -> None:
        self.write(va, struct.pack("<I", value & 0xFFFFFFFF))

    def _cstring(self, va: int) -> str:
        out = bytearray()
        while self.mem.get(va, 0):
            out.append(self.mem[va])
            va += 1
        return out.decode("ascii")

    def _push(self, value: int) -> None:
        self.esp -= 4
        self._write_dword(self.esp, value)

    def _pop(self) -> int:
        value = self._dword(self.esp)
        self.esp += 4
        return value

    def _set_low(self, register: str, value: int) -> None:
        self.regs[register] = (self.regs[register] & ~0xFF) | (value & 0xFF)

    def _call(self, target: int) -> None:
        if target == ASCII_STRING_SET:
            self.name = self._cstring(self._pop())
        elif target == FIND_UPGRADE:
            self._pop()  # the AsciiString the cave just set
            self.looked_up.append(self.name)
            self.regs["eax"] = self.upgrades.get(self.name, 0)
        elif target == self.action_va:
            self.applied.append((self.regs["ecx"], self._pop()))
        elif target == ASCII_STRING_DTOR:
            self.destructed += 1
        else:
            raise AssertionError(f"the cave called 0x{target:08x}, which no test models")

    def run(self, limit: int = 100_000) -> int:
        code, ip = self.code, 0
        for _ in range(limit):
            head = code[ip : ip + 6]
            if head[:1] == b"\x55":  # push ebp
                self._push(self.regs["ebp"])
                ip += 1
            elif head[:2] == b"\x8b\xec":  # mov ebp, esp
                self.regs["ebp"] = self.esp
                ip += 2
            elif head[:2] == b"\x81\xec":  # sub esp, imm32
                self.esp -= struct.unpack_from("<I", code, ip + 2)[0]
                ip += 6
            elif head[:1] == b"\x56":  # push esi
                self._push(self.regs["esi"])
                ip += 1
            elif head[:1] == b"\x57":  # push edi
                self._push(self.regs["edi"])
                ip += 1
            elif head[:1] == b"\x50":  # push eax
                self._push(self.regs["eax"])
                ip += 1
            elif head[:4] == b"\x83\x65\xfc\x00":  # and dword [ebp-4], 0
                self._write_dword(self.regs["ebp"] - 4, 0)
                ip += 4
            elif head[:3] == b"\x8b\x47\xf8":  # mov eax, [edi-8]
                self.regs["eax"] = self._dword(self.regs["edi"] - 8)
                ip += 3
            elif head[:3] == b"\x89\x45\xf8":  # mov [ebp-8], eax
                self._write_dword(self.regs["ebp"] - 8, self.regs["eax"])
                ip += 3
            elif head[:3] == b"\x8b\x75\x08":  # mov esi, [ebp+8]
                self.regs["esi"] = self._dword(self.regs["ebp"] + 8)
                ip += 3
            elif head[:3] == b"\x8b\x4d\xf8":  # mov ecx, [ebp-8]
                self.regs["ecx"] = self._dword(self.regs["ebp"] - 8)
                ip += 3
            elif head[:2] == b"\x8b\x36":  # mov esi, [esi]
                self.regs["esi"] = self._dword(self.regs["esi"])
                ip += 2
            elif head[:2] == b"\x85\xf6":  # test esi, esi
                self.zf = self.regs["esi"] == 0
                ip += 2
            elif head[:2] == b"\x85\xc0":  # test eax, eax
                self.zf = self.regs["eax"] == 0
                ip += 2
            elif head[:2] == b"\x83\xc6":  # add esi, imm8
                self.regs["esi"] += code[ip + 2]
                ip += 3
            elif head[:2] == b"\x8a\x06":  # mov al, [esi]
                self._set_low("eax", self.mem.get(self.regs["esi"], 0))
                ip += 2
            elif head[:1] == b"\x3c":  # cmp al, imm8
                self.zf = (self.regs["eax"] & 0xFF) == code[ip + 1]
                ip += 2
            elif head[:2] == b"\x84\xc0":  # test al, al
                self.zf = (self.regs["eax"] & 0xFF) == 0
                ip += 2
            elif head[:2] == b"\x8d\xbd":  # lea edi, [ebp+disp32]
                self.regs["edi"] = self.regs["ebp"] + struct.unpack_from("<i", code, ip + 2)[0]
                ip += 6
            elif head[:2] == b"\x8d\x85":  # lea eax, [ebp+disp32]
                self.regs["eax"] = self.regs["ebp"] + struct.unpack_from("<i", code, ip + 2)[0]
                ip += 6
            elif head[:3] == b"\x8d\x4d\xfc":  # lea ecx, [ebp-4]
                self.regs["ecx"] = self.regs["ebp"] - 4
                ip += 3
            elif head[:3] == b"\x8d\x45\xfc":  # lea eax, [ebp-4]
                self.regs["eax"] = self.regs["ebp"] - 4
                ip += 3
            elif head[:1] == b"\xb9":  # mov ecx, imm32
                self.regs["ecx"] = struct.unpack_from("<I", code, ip + 1)[0]
                ip += 5
            elif head[:2] == b"\x8b\x0d":  # mov ecx, [imm32]
                assert struct.unpack_from("<I", code, ip + 2)[0] == THE_UPGRADE_CENTER
                self.regs["ecx"] = 0xDEADBEEF  # the center, which nothing here models
                ip += 6
            elif head[:2] == b"\x88\x07":  # mov [edi], al
                self.mem[self.regs["edi"]] = self.regs["eax"] & 0xFF
                ip += 2
            elif head[:3] == b"\xc6\x07\x00":  # mov byte [edi], 0
                self.mem[self.regs["edi"]] = 0
                ip += 3
            elif head[:1] == b"\x46":  # inc esi
                self.regs["esi"] += 1
                ip += 1
            elif head[:1] == b"\x47":  # inc edi
                self.regs["edi"] += 1
                ip += 1
            elif head[:1] == b"\x49":  # dec ecx
                self.regs["ecx"] = (self.regs["ecx"] - 1) & 0xFFFFFFFF
                self.zf = self.regs["ecx"] == 0
                ip += 1
            elif head[:2] == b"\x33\xc0":  # xor eax, eax
                self.regs["eax"] = 0
                ip += 2
            elif head[:1] == b"\xe8":  # call rel32
                self._call(self.base_va + ip + 5 + struct.unpack_from("<i", code, ip + 1)[0])
                ip += 5
            elif head[:1] == b"\xe9":  # jmp rel32
                ip += 5 + struct.unpack_from("<i", code, ip + 1)[0]
            elif head[:2] == b"\x0f\x84":  # je rel32
                ip += 6 + (struct.unpack_from("<i", code, ip + 2)[0] if self.zf else 0)
            elif head[:2] == b"\x0f\x85":  # jne rel32
                ip += 6 + (0 if self.zf else struct.unpack_from("<i", code, ip + 2)[0])
            elif head[:1] == b"\x5f":  # pop edi
                self.regs["edi"] = self._pop()
                ip += 1
            elif head[:1] == b"\x5e":  # pop esi
                self.regs["esi"] = self._pop()
                ip += 1
            elif head[:1] == b"\xc9":  # leave
                self.esp = self.regs["ebp"]
                self.regs["ebp"] = self._pop()
                ip += 1
            elif head[:3] == b"\xc2\x04\x00":  # ret 4
                self._pop()  # the return address
                self.esp += 4  # the argument, cleaned by the callee
                return self.regs["eax"]
            else:
                raise AssertionError(f"unknown opcode at +{ip}: {code[ip : ip + 6].hex()}")
        raise AssertionError("the applier did not return")


_BASE_VA = 0x00E00000
_FIELD_HANDLE, _FIELD_BUFFER = 0x00A00000, 0x00A01000
_INTERFACE, _OBJECT = 0x00B00000, 0x00B0BEEF
_CHARS = 8


def run_applier(
    listed: str | None,
    upgrades: dict[str, int],
    action_va: int = OBJECT_GIVE_UPGRADE,
) -> Machine:
    """Run one applier over ``listed`` as the field's `AsciiString`, with ``upgrades`` as what
    `TheUpgradeCenter` knows about. None means a field that was never written."""
    machine = Machine(build_apply(_BASE_VA, action_va), _BASE_VA, action_va, upgrades)
    machine.write(_FIELD_HANDLE, struct.pack("<I", _FIELD_BUFFER if listed is not None else 0))
    if listed is not None:
        machine.write(_FIELD_BUFFER + _CHARS, listed.encode("ascii") + b"\x00")
    machine.write(_INTERFACE - 8, struct.pack("<I", _OBJECT))
    machine.regs["edi"] = _INTERFACE
    machine.regs["esi"] = 0x11111111
    machine._push(_FIELD_HANDLE)  # the argument
    machine._push(0x00DEAD00)  # the return address
    return machine


class TestApplier:
    def test_one_name_is_looked_up_and_applied(self) -> None:
        machine = run_applier("Upgrade_A", {"Upgrade_A": 0x1234})
        assert machine.run() == 0
        assert machine.looked_up == ["Upgrade_A"]
        assert machine.applied == [(_OBJECT, 0x1234)]

    def test_every_name_is_applied_left_to_right(self) -> None:
        machine = run_applier(
            "Upgrade_A Upgrade_B Upgrade_C",
            {"Upgrade_A": 1, "Upgrade_B": 2, "Upgrade_C": 3},
        )
        assert machine.run() == 0
        assert machine.looked_up == ["Upgrade_A", "Upgrade_B", "Upgrade_C"]
        assert machine.applied == [(_OBJECT, 1), (_OBJECT, 2), (_OBJECT, 3)]

    def test_an_unknown_name_is_skipped_and_the_rest_still_apply(self) -> None:
        """`findUpgrade` answering NULL is how a misspelled name behaves on stock too - nothing
        happens - and it must not cost the names beside it."""
        machine = run_applier("Nope Upgrade_B", {"Upgrade_B": 2})
        assert machine.run() == 0
        assert machine.looked_up == ["Nope", "Upgrade_B"]
        assert machine.applied == [(_OBJECT, 2)]

    def test_runs_of_separators_and_both_ends_are_tolerated(self) -> None:
        machine = run_applier("   Upgrade_A    Upgrade_B  ", {"Upgrade_A": 1, "Upgrade_B": 2})
        assert machine.run() == 0
        assert machine.looked_up == ["Upgrade_A", "Upgrade_B"]

    def test_an_empty_field_does_nothing(self) -> None:
        for listed in (None, ""):
            machine = run_applier(listed, {"Upgrade_A": 1})
            assert machine.run() == 0
            assert machine.looked_up == []
            assert machine.applied == []

    def test_it_always_answers_no_template(self) -> None:
        """The caller reads the return through `test eax,eax / je` and would otherwise apply the
        last template a second time."""
        machine = run_applier("Upgrade_A", {"Upgrade_A": 0x1234})
        assert machine.run() == 0

    def test_a_pathologically_long_name_is_truncated_not_overrun(self) -> None:
        """The token is copied into the frame to be NUL-terminated, so the copy is bounded. A
        truncated name simply fails the lookup; what must not happen is a write past the buffer."""
        long_name = "U" * (MAX_NAME + 50)
        machine = run_applier(f"{long_name} Upgrade_B", {"Upgrade_B": 2})
        assert machine.run() == 0
        assert machine.looked_up == ["U" * MAX_NAME, "Upgrade_B"]
        assert machine.applied == [(_OBJECT, 2)]
        assert min(machine.mem) >= machine.regs["ebp"] - (MAX_NAME + 1 + 8)

    def test_the_removal_applier_calls_the_removal(self) -> None:
        machine = run_applier("Upgrade_A", {"Upgrade_A": 7}, action_va=OBJECT_REMOVE_UPGRADE)
        assert machine.run() == 0
        assert machine.applied == [(_OBJECT, 7)]

    def test_it_leaves_the_stack_and_the_registers_as_a_thiscall_must(self) -> None:
        machine = run_applier("Upgrade_A Upgrade_B", {"Upgrade_A": 1})
        entry_esp = machine.esp
        machine.run()
        assert machine.esp == entry_esp + 8  # the return address and the one argument
        assert machine.regs["edi"] == _INTERFACE
        assert machine.regs["esi"] == 0x11111111
        assert machine.destructed == 1  # the name it built is released on the way out


class TestIniSurface:
    def test_it_retypes_both_keywords_as_upgrade_lists(self) -> None:
        surface = UpgradeGrantListsPatch().ini_surface()
        assert [(f.block, f.name, f.type) for f in surface.fields] == [
            ("ObjectCreationUpgrade", "RemoveUpgrade", "Ref[]:upgrades"),
            ("ObjectCreationUpgrade", "GrantUpgrade", "Ref[]:upgrades"),
        ]

    def test_the_model_takes_it(self) -> None:
        block = REGISTRY["ObjectCreationUpgrade"]
        stock = {name: block._fieldspec[name] for name, _off in FIELDS}

        with UpgradeGrantListsPatch().ini_surface().activate() as problems:
            assert problems == []
            for name, _offset in FIELDS:
                assert isinstance(block._fieldspec[name], _List)

        assert {name: block._fieldspec[name] for name, _off in FIELDS} == stock


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

    def test_the_table_reference_names_the_stock_table(self, game: bytes) -> None:
        assert at(game, FIELD_TABLE_REF_VA, 1) == b"\x68"
        assert struct.unpack("<I", at(game, FIELD_TABLE_REF_VA + 1, 4))[0] == FIELD_TABLE_VA

    def test_both_keywords_are_one_token_ascii_strings_at_the_offsets_the_code_reads(
        self, game: bytes
    ) -> None:
        for name, offset in FIELDS:
            row = _row(game, name)
            assert at(game, row[0], len(name) + 1) == name.encode() + b"\x00"
            assert row[1] == STOCK_ASCII_STRING_PARSER
            assert row[3] == offset

    def test_both_lookups_still_call_find_upgrade(self, game: bytes) -> None:
        assert _call_target(game, GRANT_CALL_VA) == FIND_UPGRADE
        assert _call_target(game, REMOVE_CALL_VA) == FIND_UPGRADE

    def test_the_module_looks_no_upgrade_up_anywhere_else(self, game: bytes) -> None:
        """Two calls, two fields. A third `findUpgrade` inside the module would be a third name
        this patch had not accounted for."""
        start, end = 0x008B83E4, 0x008B8800  # the module's own code
        found = []
        for va in range(start, end - 5):
            if at(game, va, 1) == b"\xe8" and _call_target(game, va) == FIND_UPGRADE:
                found.append(va)
        assert found == [GRANT_CALL_VA, REMOVE_CALL_VA]

    def test_apply_and_verify_round_trip(self, game: bytes) -> None:
        data = bytearray(game)
        patch = UpgradeGrantListsPatch()
        patch.apply(data)
        assert patch.verify(data) == []
        assert UpgradeGrantListsPatch.detect(game) is None
