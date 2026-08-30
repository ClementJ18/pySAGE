"""Tests for the battle-school patch.

The patch is a fork in the road: read one byte of the FSCommand's params string, and either run a
new exit routine or hand control back to the stock handler as if nothing had happened. Two things
can go wrong there and neither shows up in a disassembly listing.

The first is the **discriminator**. Only `params[0]` reaches the engine, so the two words the
`.apt` sends have to differ in their first character - which ``"enter"``/``"exit"`` do not.
:class:`TestDirection` runs the emitted bytes through :class:`Machine`, an interpreter covering
exactly the forms the fork emits, and asserts the machine and
:func:`~sage_patch.patches.experimental.battle_school.leaves` agree for every shape of input,
`ENTER` and `EXIT` included.

The second is the **stock arm**. It re-emits the five bytes the detour displaced and jumps back
past them, which is only correct while those bytes carry no relative displacement.
:class:`TestStockArm` pins that: the opcode, the re-emission, and the address jumped back to.

The synthetic image is built from the patch's own tables, so it cannot confirm the addresses are
the right ones; :class:`TestInstalledBinary` does that against the real `game.dat` when it is
present, and ``docs/battle-school.md`` records the derivation.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from sage_ini.engine import STOCK
from sage_patch.addresses import (
    BATTLE_SCHOOL_BLINK_REGISTRATION,
    BATTLE_SCHOOL_BLINK_REGISTRATION_BYTES,
    BATTLE_SCHOOL_COMMAND,
    BATTLE_SCHOOL_HANDLER,
    BATTLE_SCHOOL_HANDLER_BYTES,
    BATTLE_SCHOOL_REGISTRATION,
    BATTLE_SCHOOL_REGISTRATION_BYTES,
    BATTLE_SCHOOL_TRANSITION_NAME,
    CREDITS_EXIT_AUDIO_TAIL,
    SHELL,
    SHELL_MUSIC_PLAYING,
    SHELL_PLAY_MUSIC,
    WINDOW_TRANSITION_REVERSE,
    WINDOW_TRANSITIONS_HANDLER,
)
from sage_patch.patches.experimental.battle_school import (
    ANCHORS,
    ENTER,
    EXIT,
    SECTION_NAME,
    BattleSchoolPatch,
    build_code,
    leaves,
    params,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import battle_school_image

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

_DETOUR_LEN = 5

#: Where the stand-in parks the cave while the machine walks it. Any address will do - the code
#: carries its operands as immediates, so the machine reads them out of the bytes.
_CODE_VA = 0x00F00000
_PARAMS_VA = 0x00E00000
_THIS = 0x00C00000


def at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + count])


@dataclass
class Machine:
    """An interpreter for the handful of forms the direction fork emits.

    It stops at the first instruction it cannot decode and records where, which is the point: the
    fork is meant to be short and straight-line, so a `build_code` that grew a form this does not
    know should fail loudly here rather than be waved through untested. Execution ends at the
    first `jmp`/`call` that leaves the fork - the exit arm's first call, or the stock arm's jump
    home - and :attr:`landed` says which side won.
    """

    code: bytes
    base_va: int
    memory: dict[int, int] = field(default_factory=dict)
    regs: dict[str, int] = field(default_factory=lambda: {"eax": 0, "edx": 0})
    stack: dict[int, int] = field(default_factory=dict)
    landed: str = ""
    zero_flag: bool = False

    def byte(self, address: int) -> int:
        if address not in self.memory:
            raise AssertionError(f"the cave read unplanted memory at 0x{address:08x}")
        return self.memory[address]

    def run(self, esp: int) -> str:
        ip = 0
        for _ in range(64):
            op = self.code[ip]
            if op == 0x8B and self.code[ip + 1 : ip + 4] == b"\x44\x24\x04":  # mov eax,[esp+4]
                self.regs["eax"] = self.stack[esp + 4]
                ip += 4
            elif op == 0x85 and self.code[ip + 1] == 0xC0:  # test eax, eax
                self.zero_flag = self.regs["eax"] == 0
                ip += 2
            elif op == 0x8A and self.code[ip + 1] == 0x10:  # mov dl, [eax]
                self.regs["edx"] = self.byte(self.regs["eax"])
                ip += 2
            elif op == 0x80 and self.code[ip + 1] == 0xCA:  # or dl, imm8
                self.regs["edx"] |= self.code[ip + 2]
                ip += 3
            elif op == 0x80 and self.code[ip + 1] == 0xFA:  # cmp dl, imm8
                self.zero_flag = (self.regs["edx"] & 0xFF) == self.code[ip + 2]
                ip += 3
            elif op == 0x0F and self.code[ip + 1] in (0x84, 0x85):  # je / jne rel32
                taken = self.zero_flag if self.code[ip + 1] == 0x84 else not self.zero_flag
                rel = struct.unpack_from("<i", self.code, ip + 2)[0]
                ip = ip + 6 + rel if taken else ip + 6
            elif op == 0x53:  # push ebx - the first instruction of the exit arm
                self.landed = "exit"
                return self.landed
            elif op == 0xB8:  # mov eax, imm32 - the first of the re-emitted stock bytes
                self.landed = "enter"
                return self.landed
            else:
                raise AssertionError(
                    f"the machine does not know the byte 0x{op:02x} at cave offset 0x{ip:x}"
                )
        raise AssertionError("the fork did not terminate")


def walk(text: str | None) -> str:
    """Run the emitted fork over ``text`` as the params string, and report which arm it reached."""
    esp = 0x00D00000
    machine = Machine(code=build_code(_CODE_VA), base_va=_CODE_VA)
    if text is None:
        machine.stack[esp + 4] = 0
    else:
        machine.stack[esp + 4] = _PARAMS_VA
        for index, char in enumerate(text.encode("ascii") + b"\x00"):
            machine.memory[_PARAMS_VA + index] = char
    machine.regs["eax"] = _THIS
    return machine.run(esp)


class TestDirection:
    """The fork, executed. `leaves` is the rule; the machine is the code; they have to agree."""

    @pytest.mark.parametrize(
        "text",
        [ENTER, EXIT, "leave", "Leave", "LEAVE", "enter", "Enter", "exit", "", "l", "L", "x", "0"],
    )
    def test_the_machine_and_the_python_rule_agree(self, text: str) -> None:
        assert walk(text) == ("exit" if leaves(text) else "enter")

    def test_a_null_params_takes_the_stock_arm_without_dereferencing_it(self) -> None:
        """The stock handler never touches `params`; this one reads a byte of it. A NULL has to
        stop before the read, which the machine proves by refusing to serve unplanted memory."""
        assert walk(None) == "enter"

    def test_the_two_words_differ_in_the_only_character_that_reaches_the_engine(self) -> None:
        """The bug this file exists for: `"enter"`/`"exit"` share an initial, so only one of them
        could ever have worked."""
        assert ENTER[0].lower() != EXIT[0].lower()

    def test_params_says_which_word_goes_with_which_direction(self) -> None:
        assert params(True) == EXIT
        assert params(False) == ENTER
        assert leaves(params(True))
        assert not leaves(params(False))

    def test_a_stock_shaped_call_with_no_params_still_enters(self) -> None:
        """BFME1's own movie sends `GameCode("BattleSchool")` with no second argument. Whatever
        that produces - an empty string here - has to mean the stock direction."""
        assert walk("") == "enter"


class TestStockArm:
    """The half of the cave that has to be indistinguishable from not being there."""

    def test_the_displaced_bytes_carry_no_relative_displacement(self) -> None:
        """`mov eax, imm32`. Re-emitting the detour's bytes at a different address is only correct
        for a position-independent instruction, and this is the check that says so."""
        assert BATTLE_SCHOOL_HANDLER_BYTES[0] == 0xB8

    def test_the_cave_ends_by_re_emitting_them_and_jumping_past_them(self) -> None:
        code = build_code(_CODE_VA)
        tail = code[-10:]
        assert tail[:_DETOUR_LEN] == BATTLE_SCHOOL_HANDLER_BYTES[:_DETOUR_LEN]
        assert tail[_DETOUR_LEN] == 0xE9
        rel = struct.unpack_from("<i", tail, _DETOUR_LEN + 1)[0]
        assert _CODE_VA + len(code) + rel == BATTLE_SCHOOL_HANDLER + _DETOUR_LEN

    def test_it_refuses_a_build_whose_handler_does_not_start_that_way(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "sage_patch.patches.experimental.battle_school.BATTLE_SCHOOL_HANDLER_BYTES",
            b"\x55" + BATTLE_SCHOOL_HANDLER_BYTES[1:],
        )
        with pytest.raises(ValueError, match="mov eax, imm32"):
            BattleSchoolPatch().apply(battle_school_image())


class TestShape:
    """What the patch is allowed to be."""

    def test_the_edit_is_one_five_byte_jmp(self) -> None:
        data = battle_school_image()
        BattleSchoolPatch().apply(data)
        stock = battle_school_image()
        differing = {
            va
            for va in range(
                BATTLE_SCHOOL_HANDLER, BATTLE_SCHOOL_HANDLER + len(BATTLE_SCHOOL_HANDLER_BYTES)
            )
            if at(data, va, 1) != at(stock, va, 1)
        }
        # A subset, not an equality: the `jmp`'s displacement can share a byte with the cookie
        # load it replaces, and does in the stand-in, where the cave lands close by.
        assert differing <= set(range(BATTLE_SCHOOL_HANDLER, BATTLE_SCHOOL_HANDLER + _DETOUR_LEN))
        assert at(data, BATTLE_SCHOOL_HANDLER, 1) == b"\xe9"

    def test_the_handler_fingerprint_excludes_the_bytes_it_edits(self) -> None:
        """`verify` re-checks the handler's tail after `apply`. A fingerprint that reached into the
        detour would report a correctly patched file as broken."""
        data = battle_school_image()
        BattleSchoolPatch().apply(data)
        tail = BATTLE_SCHOOL_HANDLER + _DETOUR_LEN
        assert (
            at(data, tail, len(BATTLE_SCHOOL_HANDLER_BYTES) - _DETOUR_LEN)
            == BATTLE_SCHOOL_HANDLER_BYTES[_DETOUR_LEN:]
        )

    def test_it_leaves_the_credits_template_alone(self) -> None:
        """The exit arm copies `CreditsExit`'s tail; copying is not editing, and the credits screen
        has to keep working."""
        data = battle_school_image()
        BattleSchoolPatch().apply(data)
        assert (
            at(data, CREDITS_EXIT_AUDIO_TAIL, len(ANCHORS[CREDITS_EXIT_AUDIO_TAIL]))
            == ANCHORS[CREDITS_EXIT_AUDIO_TAIL]
        )

    def test_the_cave_names_the_battle_school_transition_and_not_the_credits_one(self) -> None:
        """The one immediate that makes this patch's exit arm a Battle School exit rather than a
        second credits exit."""
        assert struct.pack("<I", BATTLE_SCHOOL_TRANSITION_NAME) in build_code(_CODE_VA)

    def test_the_cave_calls_only_routines_the_anchors_pin(self) -> None:
        """Every `call rel32` in the cave resolves to a routine `ANCHORS` fingerprints, so a build
        where one of them moved fails `apply` rather than calling into whatever is there now."""
        code = build_code(_CODE_VA)
        pinned = {SHELL_MUSIC_PLAYING, SHELL_PLAY_MUSIC, WINDOW_TRANSITION_REVERSE}
        targets = {
            _CODE_VA + index + 5 + struct.unpack_from("<i", code, index + 1)[0]
            for index, byte in enumerate(code)
            if byte == 0xE8
        }
        assert pinned <= targets
        assert targets - pinned <= {0x004374E0}  # ASCII_STRING_CTOR, pinned by its own use site

    def test_it_changes_nothing_about_the_ini(self) -> None:
        assert BattleSchoolPatch().ini_surface() is STOCK

    def test_it_is_registered(self) -> None:
        assert PATCHES[BattleSchoolPatch.name] is BattleSchoolPatch

    def test_it_is_marked_experimental(self) -> None:
        """Nothing here has been in front of a running game."""
        assert BattleSchoolPatch.experimental


class TestApplyAndVerify:
    def test_apply_then_verify_is_clean(self) -> None:
        data = battle_school_image()
        BattleSchoolPatch().apply(data)
        assert BattleSchoolPatch().verify(data) == []

    def test_a_stock_image_verifies_as_absent(self) -> None:
        problems = BattleSchoolPatch().verify(battle_school_image())
        assert problems and SECTION_NAME in problems[0]

    def test_detect_finds_it_only_once_applied(self) -> None:
        stock = battle_school_image()
        assert BattleSchoolPatch.detect(stock) is None
        BattleSchoolPatch().apply(stock)
        found = BattleSchoolPatch.detect(stock)
        assert found is not None
        assert found.name == BattleSchoolPatch.name

    def test_the_cave_holds_the_code_the_jmp_points_at(self) -> None:
        data = battle_school_image()
        BattleSchoolPatch().apply(data)
        located = find_section(data, SECTION_NAME)
        assert located is not None
        section_va, _, _ = located
        rel = struct.unpack("<i", at(data, BATTLE_SCHOOL_HANDLER + 1, 4))[0]
        assert BATTLE_SCHOOL_HANDLER + _DETOUR_LEN + rel == section_va
        assert at(data, section_va, len(build_code(section_va))) == build_code(section_va)

    def test_a_moved_anchor_is_refused(self) -> None:
        data = battle_school_image()
        off = va_to_offset(data, SHELL_MUSIC_PLAYING)
        assert off is not None
        data[off] = 0x90
        with pytest.raises(ValueError, match="not this build's"):
            BattleSchoolPatch().apply(data)


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
class TestInstalledBinary:
    """The addresses, against the real build. The synthetic image is built from the patch's own
    tables, so only this can say they point at the right bytes."""

    @pytest.fixture
    def game(self) -> bytes:
        return _GAME_DAT.read_bytes()

    def test_every_anchor_holds_its_stock_bytes(self, game: bytes) -> None:
        for va, expected in ANCHORS.items():
            assert at(game, va, len(expected)) == expected, f"0x{va:08x}"

    def test_the_handler_is_where_the_registration_says(self, game: bytes) -> None:
        """The registration block ends with `mov esi, <handler>`, so its last four bytes are the
        handler's address - the link this patch depends on."""
        block = at(game, BATTLE_SCHOOL_REGISTRATION, len(BATTLE_SCHOOL_REGISTRATION_BYTES))
        assert struct.unpack("<I", block[-4:])[0] == BATTLE_SCHOOL_HANDLER

    def test_the_registration_names_the_battle_school_command(self, game: bytes) -> None:
        """The other end of that link: the block's `push imm32` is the FSCommand string the `.apt`
        sends, which is what rules out an identically shaped neighbour."""
        block = at(game, BATTLE_SCHOOL_REGISTRATION, len(BATTLE_SCHOOL_REGISTRATION_BYTES))
        assert block[0] == 0x68  # push imm32
        name_va = struct.unpack("<I", block[1:5])[0]
        assert name_va == BATTLE_SCHOOL_COMMAND
        assert at(game, name_va, 32).split(b"\x00")[0] == b"AptMainMenu::BattleSchool"

    def test_the_blink_extern_is_still_registered(self, game: bytes) -> None:
        """The movie's other half. `BlinkBattleSchoolOff` is not touched by the patch, but a build
        that had dropped it would be one where the button has nothing to ask."""
        block = at(
            game, BATTLE_SCHOOL_BLINK_REGISTRATION, len(BATTLE_SCHOOL_BLINK_REGISTRATION_BYTES)
        )
        assert block[0] == 0x68
        name_va = struct.unpack("<I", block[1:5])[0]
        assert at(game, name_va, 32).split(b"\x00")[0] == b"BlinkBattleSchoolOff"

    def test_the_handler_is_stock(self, game: bytes) -> None:
        assert (
            at(game, BATTLE_SCHOOL_HANDLER, len(BATTLE_SCHOOL_HANDLER_BYTES))
            == BATTLE_SCHOOL_HANDLER_BYTES
        )

    def test_the_handler_names_the_transition_the_exit_arm_reverses(self, game: bytes) -> None:
        """Both directions have to drive the same `WindowTransition` group, so the name the stock
        handler pushes is the one the cave has to push back."""
        assert struct.pack("<I", BATTLE_SCHOOL_TRANSITION_NAME) in BATTLE_SCHOOL_HANDLER_BYTES
        assert (
            at(game, BATTLE_SCHOOL_TRANSITION_NAME, 32).split(b"\x00")[0]
            == b"MainMenuToBattleSchool"
        )

    def test_the_handler_reads_the_same_shell_the_exit_arm_clears(self, game: bytes) -> None:
        assert struct.pack("<I", SHELL) in BATTLE_SCHOOL_HANDLER_BYTES
        assert struct.pack("<I", WINDOW_TRANSITIONS_HANDLER) in BATTLE_SCHOOL_HANDLER_BYTES

    def test_apply_and_verify_against_the_real_binary(self, game: bytes) -> None:
        data = bytearray(game)
        BattleSchoolPatch().apply(data)
        assert BattleSchoolPatch().verify(data) == []
