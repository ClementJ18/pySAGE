"""Tests for the campaign-select patch.

The patch is thirty instructions, and all but six of them are the stock callback copied out. What
is actually new is a string parse - find a separator, copy the tail into a bounded buffer - and a
parse is the kind of code whose off-by-one is invisible in a disassembly listing. So the centre of
this file is :class:`TestCave`, which **runs the emitted bytes** through :class:`Machine`, a
20-opcode interpreter covering exactly the forms `build_code` emits. That makes
:func:`~sage_patch.patches.campaign_select.campaign_of` a real oracle rather than a second
description of the same intent: every case asserts the Python rule and the machine agree.

:class:`TestShape` pins what the patch is allowed to be (one `jmp`, five bytes, nothing else), and
:meth:`TestShape.test_the_handler_fingerprint_excludes_the_bytes_it_edits` keeps `verify` honest -
a fingerprint covering the detour would still hold stock bytes after `apply` and report a
correctly patched file as broken.

The synthetic image is built from the patch's own tables, so it cannot confirm the addresses are
the right ones; :class:`TestInstalledBinary` does that against the real `game.dat` when it is
present, and ``docs/campaign-select.md`` records the derivation.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from sage_ini.engine import STOCK
from sage_patch.addresses import (
    ASCII_STRING_SET,
    CAMPAIGN_NAME_STATIC,
    CAMPAIGN_NAME_STATIC_GUARD,
    MAIN_MENU_CAMPAIGN_COMMAND,
    MAIN_MENU_CAMPAIGN_HANDLER,
    MAIN_MENU_CAMPAIGN_HANDLER_BYTES,
    MAIN_MENU_CAMPAIGN_REGISTRATION,
    MAIN_MENU_CAMPAIGN_REGISTRATION_BYTES,
    MAIN_MENU_CAMPAIGN_SELECTION_ID,
    MAIN_MENU_PHASE_LEAVING,
    MAIN_MENU_SCREEN_DIFFICULTY,
    MAIN_MENU_SCREEN_PHASE,
    MAIN_MENU_SCREEN_SELECTION,
)
from sage_patch.patches.campaign_select import (
    ANCHORS,
    CODE_OFF,
    NAME_CAPACITY,
    NAME_OFF,
    SECTION_NAME,
    SEPARATOR,
    CampaignSelectPatch,
    build_code,
    campaign_of,
    params,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import campaign_select_image

_GAME_DAT = Path(r"C:\Program Files (x86)\Games\bfme\rotwk\game.dat")

_DETOUR_LEN = 5

# Where the stand-in parks the cave's operands while the machine runs. Any addresses will do -
# the code carries them as immediates, so the machine reads them out of the bytes rather than
# being told.
_CODE_VA = 0x00F00040
_NAME_VA = 0x00F00000
_PARAMS_VA = 0x00E00000
_THIS = 0x00C00000


def at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + count])


@dataclass
class Machine:
    """An interpreter for the twenty instruction forms `build_code` emits, and nothing else.

    Deliberately narrow. It is not a general x86 emulator and must not become one: an unknown
    opcode raises, so an instruction added to the cave without a test to match it fails here
    rather than being silently skipped. `eax`/`ecx`/`edx` and the ZF/CF pair are the whole machine
    state, because they are the whole of what the cave uses.

    ``call`` is intercepted rather than executed: the one call the cave makes is
    `AsciiString::set`, whose effect is recorded in :attr:`assigned` (and whose `ret 4` is modelled
    by dropping the pushed argument).
    """

    code: bytes
    code_va: int
    mem: dict[int, int] = field(default_factory=dict)
    regs: dict[str, int] = field(default_factory=lambda: {"eax": 0, "ecx": 0, "edx": 0})
    stack: list[int] = field(default_factory=list)
    zf: bool = False
    cf: bool = False
    #: `(this-relative field, value)` for every dword the cave wrote through `ecx`.
    fields: dict[int, int] = field(default_factory=dict)
    #: The C string `AsciiString::set` was called with, or None if it was never called.
    assigned: str | None = None
    #: Addresses the cave `or`-ed a 1 into - the magic-static guard, if it got that far.
    guards: set[int] = field(default_factory=set)

    def write_string(self, va: int, text: str) -> None:
        for index, byte in enumerate(text.encode("ascii") + b"\x00"):
            self.mem[va + index] = byte

    def read_string(self, va: int) -> str:
        out = bytearray()
        while self.mem.get(va, 0):
            out.append(self.mem[va])
            va += 1
        return out.decode("ascii")

    def _u32(self, ip: int) -> int:
        return struct.unpack_from("<I", self.code, ip)[0]

    def _i32(self, ip: int) -> int:
        return struct.unpack_from("<i", self.code, ip)[0]

    def run(self, limit: int = 10_000) -> Machine:
        ip = 0
        for _ in range(limit):
            op = self.code[ip]
            rest = self.code[ip + 1 :]
            if self.code[ip : ip + 4] == b"\x8b\x44\x24\x04":  # mov eax, [esp+4]
                self.regs["eax"] = self.stack[-1]
                ip += 4
            elif op == 0xC7 and rest[0] == 0x81:  # mov [ecx+d32], imm32
                self.fields[self._u32(ip + 2)] = self._u32(ip + 6)
                ip += 10
            elif self.code[ip : ip + 2] == b"\x8a\x10":  # mov dl, [eax]
                self._set_low("edx", self.mem.get(self.regs["eax"], 0))
                ip += 2
            elif op == 0x88 and rest[0] == 0x91:  # mov [ecx+d32], dl
                self.fields[self._u32(ip + 2)] = self.regs["edx"] & 0xFF
                ip += 6
            elif self.code[ip : ip + 2] == b"\x84\xd2":  # test dl, dl
                self.zf = (self.regs["edx"] & 0xFF) == 0
                ip += 2
            elif self.code[ip : ip + 2] == b"\x84\xc9":  # test cl, cl
                self.zf = (self.regs["ecx"] & 0xFF) == 0
                ip += 2
            elif self.code[ip : ip + 2] == b"\x8b\xd0":  # mov edx, eax
                self.regs["edx"] = self.regs["eax"]
                ip += 2
            elif self.code[ip : ip + 2] == b"\x8a\x0a":  # mov cl, [edx]
                self._set_low("ecx", self.mem.get(self.regs["edx"], 0))
                ip += 2
            elif self.code[ip : ip + 2] == b"\x88\x08":  # mov [eax], cl
                self.mem[self.regs["eax"]] = self.regs["ecx"] & 0xFF
                ip += 2
            elif self.code[ip : ip + 3] == b"\xc6\x00\x00":  # mov byte ptr [eax], 0
                self.mem[self.regs["eax"]] = 0
                ip += 3
            elif self.code[ip : ip + 3] == b"\x80\x3a\x00":  # cmp byte ptr [edx], 0
                self._cmp(self.mem.get(self.regs["edx"], 0), 0)
                ip += 3
            elif op == 0x80 and rest[0] == 0xF9:  # cmp cl, imm8
                self._cmp(self.regs["ecx"] & 0xFF, self.code[ip + 2])
                ip += 3
            elif op == 0x3D:  # cmp eax, imm32
                self._cmp(self.regs["eax"], self._u32(ip + 1))
                ip += 5
            elif op == 0x42:  # inc edx
                self.regs["edx"] += 1
                ip += 1
            elif op == 0x40:  # inc eax
                self.regs["eax"] += 1
                ip += 1
            elif op == 0xB8:  # mov eax, imm32
                self.regs["eax"] = self._u32(ip + 1)
                ip += 5
            elif op == 0xB9:  # mov ecx, imm32
                self.regs["ecx"] = self._u32(ip + 1)
                ip += 5
            elif op == 0x68:  # push imm32
                self.stack.append(self._u32(ip + 1))
                ip += 5
            elif op == 0x83 and rest[0] == 0x0D:  # or dword ptr [imm32], 1
                assert self.code[ip + 6] == 1
                self.guards.add(self._u32(ip + 2))
                ip += 7
            elif op == 0xE8:  # call rel32 - only ever AsciiString::set
                target = self.code_va + ip + 5 + self._i32(ip + 1)
                assert target == ASCII_STRING_SET, f"unexpected call to 0x{target:08x}"
                assert self.regs["ecx"] == CAMPAIGN_NAME_STATIC
                self.assigned = self.read_string(self.stack.pop())  # `ret 4`
                ip += 5
            elif op == 0x0F and rest[0] in (0x84, 0x85, 0x82):  # je / jne / jb rel32
                taken = {0x84: self.zf, 0x85: not self.zf, 0x82: self.cf}[rest[0]]
                ip += 6 + (self._i32(ip + 2) if taken else 0)
            elif self.code[ip : ip + 3] == b"\xc2\x04\x00":  # ret 4
                return self
            else:
                raise AssertionError(
                    f"unmodelled opcode {self.code[ip : ip + 4].hex()} at +{ip:#x}"
                )
        raise AssertionError("the cave did not return - the machine ran off its instruction budget")

    def _set_low(self, reg: str, value: int) -> None:
        self.regs[reg] = (self.regs[reg] & ~0xFF) | value

    def _cmp(self, left: int, right: int) -> None:
        self.zf = left == right
        self.cf = left < right


def run_cave(text: str) -> Machine:
    """The emitted cave, run against ``text`` as its FSCommand params string."""
    machine = Machine(build_code(_CODE_VA, _NAME_VA), _CODE_VA)
    machine.regs["ecx"] = _THIS
    machine.stack.append(_PARAMS_VA)
    machine.write_string(_PARAMS_VA, text)
    return machine.run()


class TestCave:
    """What the emitted code actually does, by running it."""

    @pytest.mark.parametrize(
        "text",
        [
            "Hard:ANGMAR_CAMPAIGN",
            "Easy:DWARVEN_CAMPAIGN",
            "Medium:a",
            ":LEADING_SEPARATOR",
            "Hard:HAS:COLONS:INSIDE",
            "Hard",
            "",
            "Hard:",
            "H" * 200,
        ],
    )
    def test_the_machine_agrees_with_campaign_of(self, text: str) -> None:
        """The Python rule and the emitted bytes answer the same for every shape of input.

        This is the whole reason `campaign_of` exists: it is the parse stated once, and the cave is
        checked against it rather than against a re-reading of its own listing."""
        machine = run_cave(text)
        assert machine.assigned == (campaign_of(text) or None)

    def test_a_name_is_installed_and_the_guard_set(self) -> None:
        machine = run_cave(params("Hard", "DWARVEN_CAMPAIGN"))
        assert machine.assigned == "DWARVEN_CAMPAIGN"
        assert machine.guards == {CAMPAIGN_NAME_STATIC_GUARD}

    @pytest.mark.parametrize("text", ["Easy", "Medium", "Hard", "", "Hard:"])
    def test_stock_params_touch_neither_the_static_nor_the_guard(self, text: str) -> None:
        """The compatibility promise, executed. A movie that never names a campaign leaves the
        engine exactly as it found it, so the stock literal - and the `_DEMO` variant the thunk
        picks between - still decides."""
        machine = run_cave(text)
        assert machine.assigned is None
        assert machine.guards == set()

    def test_the_three_stock_fields_are_written_unchanged(self) -> None:
        """The cave is the stock callback plus a parse, so the stock callback's whole effect has
        to survive - including on the paths that bail out early."""
        for text in (params("Hard", "DWARVEN_CAMPAIGN"), "Hard", ""):
            machine = run_cave(text)
            assert machine.fields[MAIN_MENU_SCREEN_PHASE] == MAIN_MENU_PHASE_LEAVING
            assert machine.fields[MAIN_MENU_SCREEN_SELECTION] == MAIN_MENU_CAMPAIGN_SELECTION_ID
            assert machine.fields[MAIN_MENU_SCREEN_DIFFICULTY] == (ord(text[0]) if text else 0)

    def test_an_overlong_name_is_truncated_and_still_terminated(self) -> None:
        """The buffer is bounded by its own end address rather than by a counter, which is the one
        place this cave could overrun. `NAME_CAPACITY - 1` characters plus a terminator is the
        whole budget."""
        machine = run_cave(params("Hard", "C" * 200))
        assert machine.assigned == "C" * (NAME_CAPACITY - 1)
        assert machine.mem[_NAME_VA + NAME_CAPACITY - 1] == 0
        assert max(machine.mem) < _NAME_VA + NAME_CAPACITY

    def test_a_name_exactly_filling_the_buffer_is_not_truncated(self) -> None:
        exact = "C" * (NAME_CAPACITY - 1)
        assert run_cave(params("Hard", exact)).assigned == exact

    def test_the_difficulty_letter_is_still_the_first_byte(self) -> None:
        """The stock callback's one use of the params string, unchanged - which is what lets the
        separator ride along inside the same argument."""
        for word in ("Easy", "Medium", "Hard"):
            machine = run_cave(params(word, "SOME_CAMPAIGN"))
            assert machine.fields[MAIN_MENU_SCREEN_DIFFICULTY] == ord(word[0])


class TestShape:
    """What the patch is allowed to be."""

    def test_the_edit_is_one_five_byte_jmp(self) -> None:
        data = campaign_select_image()
        CampaignSelectPatch().apply(data)
        stock = campaign_select_image()
        differing = [
            va
            for va in range(
                MAIN_MENU_CAMPAIGN_HANDLER,
                MAIN_MENU_CAMPAIGN_HANDLER + len(MAIN_MENU_CAMPAIGN_HANDLER_BYTES),
            )
            if at(data, va, 1) != at(stock, va, 1)
        ]
        assert differing == list(
            range(MAIN_MENU_CAMPAIGN_HANDLER, MAIN_MENU_CAMPAIGN_HANDLER + _DETOUR_LEN)
        )
        assert at(data, MAIN_MENU_CAMPAIGN_HANDLER, 1) == b"\xe9"

    def test_the_handler_fingerprint_excludes_the_bytes_it_edits(self) -> None:
        """`verify` re-checks the callback's tail after `apply`. A fingerprint that reached into
        the detour would report a correctly patched file as broken, so the split has to be exactly
        the detour's length."""
        data = campaign_select_image()
        CampaignSelectPatch().apply(data)
        tail = MAIN_MENU_CAMPAIGN_HANDLER + _DETOUR_LEN
        assert (
            at(data, tail, len(MAIN_MENU_CAMPAIGN_HANDLER_BYTES) - _DETOUR_LEN)
            == MAIN_MENU_CAMPAIGN_HANDLER_BYTES[_DETOUR_LEN:]
        )

    def test_the_buffer_sits_below_the_code_and_they_do_not_overlap(self) -> None:
        assert NAME_OFF + NAME_CAPACITY == CODE_OFF

    def test_the_stock_difficulty_words_carry_no_separator(self) -> None:
        """Why an unpatched movie is safe: none of the three words the stock `LevelOfDifficulty`
        sprite sends can be mistaken for a named campaign."""
        for word in ("Easy", "Medium", "Hard"):
            assert SEPARATOR not in word
            assert campaign_of(word) == ""

    def test_params_refuses_a_difficulty_that_would_be_ambiguous(self) -> None:
        with pytest.raises(ValueError, match="may not contain"):
            params("Ha:rd", "SOME_CAMPAIGN")

    def test_it_changes_nothing_about_the_ini(self) -> None:
        assert CampaignSelectPatch().ini_surface() is STOCK

    def test_it_is_registered(self) -> None:
        assert PATCHES[CampaignSelectPatch.name] is CampaignSelectPatch


class TestApplyAndVerify:
    def test_apply_then_verify_is_clean(self) -> None:
        data = campaign_select_image()
        CampaignSelectPatch().apply(data)
        assert CampaignSelectPatch().verify(data) == []

    def test_a_stock_image_verifies_as_absent(self) -> None:
        problems = CampaignSelectPatch().verify(campaign_select_image())
        assert problems and SECTION_NAME in problems[0]

    def test_detect_finds_it_only_once_applied(self) -> None:
        stock = campaign_select_image()
        assert CampaignSelectPatch.detect(stock) is None
        CampaignSelectPatch().apply(stock)
        found = CampaignSelectPatch.detect(stock)
        assert found is not None
        assert found.name == CampaignSelectPatch.name

    def test_the_cave_holds_the_code_the_jmp_points_at(self) -> None:
        data = campaign_select_image()
        CampaignSelectPatch().apply(data)
        located = find_section(data, SECTION_NAME)
        assert located is not None
        section_va, _, _ = located
        rel = struct.unpack("<i", at(data, MAIN_MENU_CAMPAIGN_HANDLER + 1, 4))[0]
        target = MAIN_MENU_CAMPAIGN_HANDLER + _DETOUR_LEN + rel
        assert target == section_va + CODE_OFF
        assert at(data, target, 4) == build_code(target, section_va + NAME_OFF)[:4]

    def test_the_buffer_starts_zeroed(self) -> None:
        data = campaign_select_image()
        CampaignSelectPatch().apply(data)
        located = find_section(data, SECTION_NAME)
        assert located is not None
        section_va, _, _ = located
        assert at(data, section_va + NAME_OFF, NAME_CAPACITY) == bytes(NAME_CAPACITY)

    def test_applying_twice_raises(self) -> None:
        data = campaign_select_image()
        CampaignSelectPatch().apply(data)
        with pytest.raises(ValueError):
            CampaignSelectPatch().apply(data)

    @pytest.mark.parametrize("va", sorted(ANCHORS))
    def test_a_moved_anchor_refuses_to_apply(self, va: int) -> None:
        """Each site is load-bearing: the registration is what says this callback is
        `Expansion1Campaign`'s, the bind is what says `CAMPAIGN_NAME_STATIC` is the campaign name,
        and `AsciiString::set` is what the cave calls."""
        data = campaign_select_image()
        off = va_to_offset(data, va)
        assert off is not None
        data[off] ^= 0xFF
        with pytest.raises(ValueError, match="not this build's"):
            CampaignSelectPatch().apply(data)

    def test_a_rewritten_callback_tail_refuses_to_apply(self) -> None:
        data = campaign_select_image()
        off = va_to_offset(data, MAIN_MENU_CAMPAIGN_HANDLER)
        assert off is not None
        data[off + len(MAIN_MENU_CAMPAIGN_HANDLER_BYTES) - 1] ^= 0xFF
        with pytest.raises(ValueError, match="not the campaign callback"):
            CampaignSelectPatch().apply(data)


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="the ROTWK game.dat is not installed here")
class TestInstalledBinary:
    """The addresses, against the real build. The synthetic image is built from the patch's own
    tables, so only this can say they point at the right bytes."""

    @pytest.fixture
    def game(self) -> bytes:
        return _GAME_DAT.read_bytes()

    def test_every_anchor_holds_its_stock_bytes(self, game: bytes) -> None:
        for va, expected in ANCHORS.items():
            assert at(game, va, len(expected)) == expected, f"0x{va:08x}"

    def test_the_callback_is_where_the_registration_says(self, game: bytes) -> None:
        """The registration block ends with `mov esi, <handler>`, so the last four of its bytes
        are the callback's address - which is the link this patch depends on."""
        registration = at(
            game, MAIN_MENU_CAMPAIGN_REGISTRATION, len(MAIN_MENU_CAMPAIGN_REGISTRATION_BYTES)
        )
        assert struct.unpack("<I", registration[-4:])[0] == MAIN_MENU_CAMPAIGN_HANDLER

    def test_the_registration_names_the_expansion1_campaign_command(self, game: bytes) -> None:
        """The other end of the same link: the block's `push imm32` is the FSCommand string the
        `.apt` sends, so this is what rules out the identically shaped `BonusCampaign` block."""
        registration = at(
            game, MAIN_MENU_CAMPAIGN_REGISTRATION, len(MAIN_MENU_CAMPAIGN_REGISTRATION_BYTES)
        )
        assert registration[0] == 0x68  # push imm32
        name_va = struct.unpack("<I", registration[1:5])[0]
        assert name_va == MAIN_MENU_CAMPAIGN_COMMAND
        assert at(game, name_va, 32).rstrip(b"\x00") == b"AptMainMenu::Expansion1Campaign"

    def test_the_callback_is_stock(self, game: bytes) -> None:
        assert (
            at(game, MAIN_MENU_CAMPAIGN_HANDLER, len(MAIN_MENU_CAMPAIGN_HANDLER_BYTES))
            == MAIN_MENU_CAMPAIGN_HANDLER_BYTES
        )

    def test_apply_and_verify_against_the_real_binary(self, game: bytes) -> None:
        data = bytearray(game)
        CampaignSelectPatch().apply(data)
        assert CampaignSelectPatch().verify(data) == []
