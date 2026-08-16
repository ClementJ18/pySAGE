"""Tests for the description-timers patch.

The patch is twelve bytes of engine and one cave that spends its whole life calling other people's
functions with the right arguments in the right order. Almost every way that can be wrong is
invisible to a byte comparison: a cave that pushed `calcTimeToBuild`'s arguments backwards, or
cleaned `0xc` where the callee cleans `0x10`, still assembles, still applies and still verifies
against itself. So the cave is **disassembled back** and asserted to say what it was meant to say -
which engine routine each `call` reaches, that every arm ends at the shared line emitter, and that
the stack arithmetic around the `double` vararg balances.

Two checks carry most of the weight:

- :meth:`TestCave.test_the_stack_balances_through_the_line_emitter` walks the emitter's `sub`/
  `add`/`push`/`pop` arithmetic and asserts it returns to zero, because getting it wrong corrupts
  the *builder's* frame rather than failing anywhere near the cave.
- :meth:`TestCave.test_the_remaining_lookup_is_pinned_to_flavour_one` is the one that keeps the
  patch honest about a wrong *number*: there are two `startPowerRecharge` implementations keeping
  their ready frame at different offsets, and reading the wrong one prints a frame counter as a
  duration.

The synthetic image is built from the patch's own tables, so it cannot confirm the addresses are
the right ones; :class:`TestInstalledBinary` does that against the real `game.dat` when it is
present, and ``docs/description-timers.md`` records the derivation.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

import pytest

from sage_ini.engine import STOCK
from sage_patch.addresses import (
    DESCRIPTION_BUTTON_CAPTURE,
    DESCRIPTION_BUTTON_CAPTURE_BYTES,
    DESCRIPTION_BUTTON_CAPTURE_RESUME,
    DESCRIPTION_TAIL,
    DESCRIPTION_TAIL_BYTES,
    DESCRIPTION_TAIL_RESUME,
    GET_FINAL_OVERRIDE,
    UNICODE_STRING_APPEND,
    UNICODE_STRING_CONCAT,
    UNICODE_STRING_CONCAT_WIDE,
    WIDE_NEWLINE,
)
from sage_patch.patches.description_timers import (
    ANCHORS,
    COMMAND_BUTTON_GET_THING_TEMPLATE,
    GET_MODIFIER_MULTIPLIER,
    GET_SPECIAL_POWER_MODULE,
    KEYS,
    LOGIC_FRAMES_PER_SECOND,
    PLAYER_HAS_UPGRADE_COMPLETE,
    PLAYER_RECHARGE_MODIFIER,
    RECHARGE_FORMULA_ANCHORS,
    SECTION_NAME,
    SPECIAL_POWER_INTERFACE_READY_FRAME,
    SPECIAL_POWER_INTERFACE_RECHARGE_SLOT,
    SPECIAL_POWER_START_RECHARGE,
    THING_TEMPLATE_CALC_TIME_TO_BUILD,
    UNICODE_STRING_DESTRUCT,
    UPGRADE_TEMPLATE_CALC_TIME_TO_BUILD,
    DescriptionTimersPatch,
)
from sage_patch.patches.upgrade_description import UpgradeDescriptionPatch
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import description_timers_image

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


def at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + count])


def cave(data: bytes | bytearray) -> tuple[int, bytes]:
    """``(base VA, bytes)`` of the patch's section."""
    located = find_section(data, SECTION_NAME)
    assert located is not None, f"no {SECTION_NAME} section"
    base_va, off, vsize = located
    return base_va, bytes(data[off : off + vsize])


def code_start(base_va: int, body: bytes) -> int:
    """Where the cave's code begins: past the stash dword, the four keys and the alignment.

    Derived from the data the cave carries rather than written down, so it cannot drift from
    :data:`KEYS`.
    """
    size = 4 + sum(len(text) + 1 for text in KEYS.values())
    return base_va + (size + 3 & ~3)


def disassemble(base_va: int, body: bytes) -> list:
    """``body`` decoded, so a branch is read as a branch.

    A byte scan is not good enough and the reason is the usual one: the cave is full of
    `lea ecx, [ebp-0x18]`, which encodes as ``8d 4d e8`` - and a scanner looking for ``e8`` finds
    the *displacement* and reads the next four bytes as a `rel32`.
    """
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return list(md.disasm(body, base_va))


def displacement(op_str: str) -> int | None:
    """The `[reg + N]` displacement in an operand string, as an int.

    Capstone prints small displacements in decimal and larger ones in hex, so a substring match
    against a hex literal quietly passes on some offsets and quietly fails on others.
    """
    match = re.search(r"\[\w+ \+ (0x[0-9a-f]+|\d+)\]", op_str)
    return int(match.group(1), 0) if match else None


def instructions(data: bytes | bytearray) -> list:
    base_va, body = cave(data)
    start = code_start(base_va, body)
    return disassemble(start, body[start - base_va :])


def branch_targets(data: bytes | bytearray) -> set[int]:
    """Every ``call``/``jmp`` destination in the cave's code."""
    return {
        int(insn.op_str, 16)
        for insn in instructions(data)
        if insn.mnemonic in ("call", "jmp") and insn.op_str.startswith("0x")
    }


@pytest.fixture
def image() -> bytearray:
    return description_timers_image()


@pytest.fixture
def patched(image) -> bytearray:
    DescriptionTimersPatch().apply(image)
    return image


class TestApply:
    def test_applies_and_verifies(self, image):
        patch = DescriptionTimersPatch()
        patch.apply(image)
        assert patch.verify(image) == []

    def test_verify_rejects_an_unpatched_image(self, image):
        problems = DescriptionTimersPatch().verify(image)
        assert problems and SECTION_NAME in problems[0]

    def test_applying_twice_raises(self, image):
        DescriptionTimersPatch().apply(image)
        with pytest.raises(ValueError, match="already carries"):
            DescriptionTimersPatch().apply(image)

    def test_detect_recovers_the_configuration(self, image):
        DescriptionTimersPatch(integer_seconds=True).apply(image)
        found = DescriptionTimersPatch.detect(image)
        assert found is not None and found.integer_seconds is True

    def test_detect_says_no_on_a_clean_image(self, image):
        assert DescriptionTimersPatch.detect(image) is None

    def test_the_two_configurations_do_not_verify_each_other(self, patched):
        assert DescriptionTimersPatch().verify(patched) == []
        assert DescriptionTimersPatch(integer_seconds=True).verify(patched)

    def test_a_stray_byte_in_a_window_is_refused(self, image):
        off = va_to_offset(image, DESCRIPTION_TAIL + 1)
        image[off] ^= 0xFF
        with pytest.raises(ValueError, match="description builder"):
            DescriptionTimersPatch().apply(image)

    @pytest.mark.parametrize("va", sorted(ANCHORS))
    def test_a_moved_callee_is_refused(self, image, va):
        image[va_to_offset(image, va)] ^= 0xFF
        with pytest.raises(ValueError, match="not this build"):
            DescriptionTimersPatch().apply(image)

    @pytest.mark.parametrize("va", sorted(RECHARGE_FORMULA_ANCHORS))
    def test_a_changed_recharge_formula_is_refused(self, image, va):
        """The cave does not call these two instructions, it *transcribes* them.

        A build that computed the cooldown differently would leave the patch printing a number
        derived from a formula that build does not use - which no byte comparison against the
        cave itself could notice, because the cave would still be exactly what this code emits.
        """
        image[va_to_offset(image, va)] ^= 0xFF
        with pytest.raises(ValueError, match="not this build"):
            DescriptionTimersPatch().apply(image)

    def test_nothing_is_left_half_applied_when_a_site_is_wrong(self, image):
        image[va_to_offset(image, DESCRIPTION_BUTTON_CAPTURE)] ^= 0xFF
        with pytest.raises(ValueError):
            DescriptionTimersPatch().apply(image)
        assert find_section(image, SECTION_NAME) is None

    @pytest.mark.parametrize(
        ("va", "original"),
        [
            (DESCRIPTION_BUTTON_CAPTURE, DESCRIPTION_BUTTON_CAPTURE_BYTES),
            (DESCRIPTION_TAIL, DESCRIPTION_TAIL_BYTES),
        ],
    )
    def test_each_window_becomes_a_jump_into_the_cave(self, patched, va, original):
        base_va, body = cave(patched)
        window = at(patched, va, len(original))
        assert window[0] == 0xE9
        rel = struct.unpack_from("<i", window, 1)[0]
        target = va + 5 + rel
        assert base_va <= target < base_va + len(body)
        # The window is longer than the jump, and the remainder has to be nops rather than the
        # tail of the instructions it replaced - a partial `mov` would still run.
        assert window[5:] == b"\x90" * (len(window) - 5)

    def test_the_patch_adds_no_ini_surface(self):
        assert DescriptionTimersPatch().ini_surface() is STOCK

    def test_it_is_registered_and_attributed(self):
        assert PATCHES[DescriptionTimersPatch.name] is DescriptionTimersPatch
        assert DescriptionTimersPatch.author


class TestCave:
    """What the emitted code actually does, disassembled back out of the section."""

    def test_both_thunks_resume_where_their_window_ended(self, patched):
        targets = branch_targets(patched)
        assert DESCRIPTION_BUTTON_CAPTURE_RESUME in targets
        assert DESCRIPTION_TAIL_RESUME in targets

    def test_the_capture_thunk_reproduces_what_it_replaced(self, patched):
        """The two instructions the window took have to still run, ahead of the copy.

        Dropping either would be silent: `mov [ebp-0x3c], edi` initialises a slot a later case
        reads, and `mov ecx, [esi+0xc]` is what the builder's own null-button test looks at.
        """
        base_va, body = cave(patched)
        start = code_start(base_va, body)
        assert body[start - base_va :][: len(DESCRIPTION_BUTTON_CAPTURE_BYTES)] == (
            DESCRIPTION_BUTTON_CAPTURE_BYTES
        )

    def test_the_tail_thunk_reproduces_what_it_replaced_after_restoring_registers(self, patched):
        """`popad` first, then the replaced `mov ecx, [...]` - never the other way round.

        The replaced instruction loads `ecx`, and `popad` would immediately overwrite it with the
        value the cave was entered with. The engine then dereferences it.
        """
        decoded = instructions(patched)
        popad = next(i for i, insn in enumerate(decoded) if insn.mnemonic in ("popal", "popad"))
        assert decoded[popad + 1].bytes == DESCRIPTION_TAIL_BYTES
        assert decoded[popad + 2].mnemonic == "jmp"
        assert int(decoded[popad + 2].op_str, 16) == DESCRIPTION_TAIL_RESUME

    def test_the_registers_are_saved_across_the_whole_line_emission(self, patched):
        """The tail is the join of every case, so the register state there is whatever ran.

        The function's own epilogue is still to come and nothing about it is this patch's to
        assume, which is why the thunk brackets its call rather than preserving a chosen few.
        """
        decoded = instructions(patched)
        mnemonics = [insn.mnemonic for insn in decoded]
        assert any(m in ("pushal", "pushad") for m in mnemonics)
        assert any(m in ("popal", "popad") for m in mnemonics)

    @pytest.mark.parametrize(
        "callee",
        [
            GET_MODIFIER_MULTIPLIER,
            GET_SPECIAL_POWER_MODULE,
            PLAYER_RECHARGE_MODIFIER,
            PLAYER_HAS_UPGRADE_COMPLETE,
            THING_TEMPLATE_CALC_TIME_TO_BUILD,
            UPGRADE_TEMPLATE_CALC_TIME_TO_BUILD,
            COMMAND_BUTTON_GET_THING_TEMPLATE,
            GET_FINAL_OVERRIDE,
            UNICODE_STRING_CONCAT,
            UNICODE_STRING_CONCAT_WIDE,
        ],
    )
    def test_every_engine_routine_the_design_names_is_reached(self, patched, callee):
        assert callee in branch_targets(patched)

    def test_the_durations_come_from_the_engine_not_from_ini(self, patched):
        """Both build times are the engine's own `calcTimeToBuild`, which is the whole claim.

        Re-deriving either from a template's `BuildTime` field would produce a number the
        production queue then disagrees with, because the queue asks these two functions.
        """
        targets = branch_targets(patched)
        assert THING_TEMPLATE_CALC_TIME_TO_BUILD in targets
        assert UPGRADE_TEMPLATE_CALC_TIME_TO_BUILD in targets

    def test_the_remaining_lookup_is_pinned_to_flavour_one(self, patched):
        """The ready frame is only at `+0x08` on one of the two implementations.

        The other keeps it at `+0x04`, so a cave that skipped the vtable comparison would read a
        neighbouring field on three module types and print a frame counter as a duration. The
        comparison is against the flavour-1 function's address, which is why that address is also
        an anchor.
        """
        _base_va, body = cave(patched)
        assert struct.pack("<I", SPECIAL_POWER_START_RECHARGE) in body
        compare = next(
            insn
            for insn in instructions(patched)
            if insn.mnemonic == "cmp" and hex(SPECIAL_POWER_START_RECHARGE) in insn.op_str
        )
        assert displacement(compare.op_str) == SPECIAL_POWER_INTERFACE_RECHARGE_SLOT
        # The load has to come off the interface the comparison just vouched for, at +0x08.
        assert bytes([0x8B, 0x40, SPECIAL_POWER_INTERFACE_READY_FRAME]) in body

    def test_the_line_is_formatted_into_a_local_and_concatenated_on(self, patched):
        """The description is never the format call's destination. This is the bug it shipped with.

        `0x00ADF7E0` **replaces** what it writes to — it ends in a `vswprintf` into a scratch buffer
        followed by a `set` — so formatting straight into `ebp-0x18` deletes the description instead
        of adding to it. Every one of the twelve engine sites hides that, because each formats into
        a slot it is the only writer of, and the first version of this patch copied the shape
        without the consequence.

        What that has to look like: the format's `this` is a stack local, and the description is
        reached only through `concat`.
        """
        decoded = instructions(patched)
        fmt = next(
            i
            for i, insn in enumerate(decoded)
            if insn.mnemonic == "call" and insn.op_str == hex(UNICODE_STRING_CONCAT)
        )
        pushed_this = decoded[fmt - 2]
        assert pushed_this.mnemonic == "lea" and "esp" in pushed_this.op_str, (
            "the format writes to a local, never to the description"
        )
        assert not any(
            insn.mnemonic == "lea" and "0x18" in insn.op_str and "ebp" in insn.op_str
            for insn in decoded[fmt - 3 : fmt]
        )
        # And the local reaches the description through `concat`, which appends.
        assert UNICODE_STRING_APPEND in branch_targets(patched)

    def test_the_formatted_line_is_released(self, patched):
        """The local holds a reference on a heap buffer; the emitter has to give it back.

        The engine's own line temporaries are destroyed by the builder's exception-handling
        bookkeeping on the way out. This one is the cave's, so the cave destroys it — and only on
        the path that formatted, since the drop path leaves it the zero it was initialised to.
        """
        decoded = instructions(patched)
        concat = next(
            i
            for i, insn in enumerate(decoded)
            if insn.mnemonic == "call" and insn.op_str == hex(UNICODE_STRING_APPEND)
        )
        assert any(
            insn.mnemonic == "call" and insn.op_str == hex(UNICODE_STRING_DESTRUCT)
            for insn in decoded[concat : concat + 4]
        )

    def test_the_separator_is_the_engines_own_literal_and_guard(self, patched):
        """`L"\\n"`, behind the null-pointer plus zero-length pair the two engine folds use.

        Without the guard a button carrying no `DescriptLabel` gains a leading blank line instead
        of coming out byte-identical to stock.
        """
        _base_va, body = cave(patched)
        assert struct.pack("<I", WIDE_NEWLINE) in body
        assert UNICODE_STRING_CONCAT_WIDE in branch_targets(patched)
        assert any(
            insn.mnemonic == "cmp" and insn.op_str.startswith("word ptr")
            for insn in instructions(patched)
        )

    def test_the_line_is_dropped_when_the_key_does_not_exist(self, patched):
        """The `exists` out-parameter is read, not passed as a throwaway zero.

        All twelve stock callers pass `0` there. Passing a real pointer and testing what comes
        back is the whole of "silent on a string table that has not added these keys", and it is
        what makes the patch a no-op on unmodified data.
        """
        decoded = instructions(patched)
        fetch = next(
            i
            for i, insn in enumerate(decoded)
            if insn.mnemonic == "call" and "+ 0x44" in insn.op_str
        )
        after = decoded[fetch : fetch + 6]
        assert any(insn.mnemonic == "lea" and "esp" in insn.op_str for insn in decoded[:fetch])
        assert any(insn.mnemonic == "cmp" and "esp" in insn.op_str for insn in after)

    def test_every_key_is_present_and_nul_terminated(self, patched):
        _base_va, body = cave(patched)
        for text in KEYS.values():
            assert text.encode("ascii") + b"\x00" in body

    def test_seconds_come_from_the_engines_own_frame_rate(self, patched):
        _base_va, body = cave(patched)
        assert struct.pack("<I", LOGIC_FRAMES_PER_SECOND) in body

    def test_integer_seconds_divides_instead_of_scaling_a_double(self, image):
        DescriptionTimersPatch(integer_seconds=True).apply(image)
        mnemonics = {insn.mnemonic for insn in instructions(image)}
        assert "idiv" in mnemonics
        assert "fidiv" not in mnemonics

    def test_the_default_passes_a_double(self, patched):
        """`fstp qword`, and a cleanup of 0x10 rather than 0xc.

        The engine's own `double` site (`CONTROLBAR:UnderConstructionDesc`) cleans four dwords
        where the one-dword sites clean three. Getting that constant wrong corrupts the builder's
        frame rather than failing anywhere the mistake is visible.
        """
        decoded = instructions(patched)
        assert any(insn.mnemonic == "fstp" and "qword" in insn.op_str for insn in decoded)
        concat = next(
            i
            for i, insn in enumerate(decoded)
            if insn.mnemonic == "call" and insn.op_str == hex(UNICODE_STRING_CONCAT)
        )
        cleanup = decoded[concat + 1]
        assert cleanup.mnemonic == "add" and cleanup.op_str == "esp, 0x10"

    def test_the_stack_balances_through_the_line_emitter(self, patched):
        """Walk the emitter's own stack arithmetic and land back where it started.

        This is the check that cannot be done by reading: the emitter reaches its locals through
        `esp`, so every `push` between them and the read has to be accounted for, and a mistake
        corrupts the *builder's* frame - which shows up as a crash somewhere else entirely.
        """
        decoded = instructions(patched)
        start = next(
            i
            for i, insn in enumerate(decoded)
            if insn.mnemonic == "sub" and insn.op_str == "esp, 0x10"
        )
        depth = 0
        for insn in decoded[start:]:
            if insn.mnemonic == "push":
                depth += 4
            elif insn.mnemonic == "pop":
                depth -= 4
            elif insn.mnemonic == "sub" and insn.op_str.startswith("esp, "):
                depth += int(insn.op_str.split(", ")[1], 16)
            elif insn.mnemonic == "add" and insn.op_str.startswith("esp, "):
                depth -= int(insn.op_str.split(", ")[1], 16)
            elif insn.mnemonic == "call":
                # Every callee here cleans its own arguments except the one `cdecl` concat, and
                # the walk has to know each count or it reports a balanced routine as broken.
                depth -= _cleanup(insn)
            elif insn.mnemonic == "ret":
                break
        assert depth == 0

    def test_every_arm_ends_at_the_shared_emitter(self, patched):
        """Three arms, one emitter, and no arm that computes a number and drops it.

        An arm whose tail `jmp` went anywhere else would compute a duration and never print it,
        which nothing else here would notice.
        """
        decoded = instructions(patched)
        emitter = next(
            insn.address
            for insn in decoded
            if insn.mnemonic == "sub" and insn.op_str == "esp, 0x10"
        )
        keys = {
            insn.address for insn in decoded if insn.mnemonic == "mov" and "edx, 0x" in insn.op_str
        }
        assert len(keys) == len(KEYS), "one `mov edx, <key>` per key, and no more"
        for insn in decoded:
            if insn.mnemonic == "mov" and "edx, 0x" in insn.op_str:
                nxt = next(x for x in decoded if x.address > insn.address)
                assert nxt.mnemonic == "jmp" and int(nxt.op_str, 16) == emitter


#: What each callee removes on the way out. `UNICODE_STRING_CONCAT` is absent because it is
#: `cdecl` and the cave cleans up after it; the indirect one is `TheGameText`'s fetch, which takes
#: the label and the `exists` pointer and cleans both.
_CALLEE_CLEANUP = {
    UNICODE_STRING_CONCAT_WIDE: 4,  # __thiscall, ret 4
    UNICODE_STRING_APPEND: 4,  # __thiscall, ret 4
    UNICODE_STRING_DESTRUCT: 0,  # __thiscall, no arguments
}
_FETCH_CLEANUP = 8


def _cleanup(insn) -> int:
    """How much ``insn``'s callee pops before returning."""
    if not insn.op_str.startswith("0x"):
        return _FETCH_CLEANUP  # the only indirect call in the emitter
    return _CALLEE_CLEANUP.get(int(insn.op_str, 16), 0)


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
class TestInstalledBinary:
    """Against the real binary, which is the only thing that can say the addresses are right.

    The synthetic image is built from this patch's own tables, so it round-trips whatever those
    tables say. Only the shipped `game.dat` can confirm that `0x008086AE` is the tooltip builder's
    tail rather than the middle of something else.
    """

    @pytest.fixture(scope="class")
    def stock(self) -> bytes:
        return _GAME_DAT.read_bytes()

    def test_every_site_holds_its_stock_bytes(self, stock):
        for va, expected in (
            (DESCRIPTION_BUTTON_CAPTURE, DESCRIPTION_BUTTON_CAPTURE_BYTES),
            (DESCRIPTION_TAIL, DESCRIPTION_TAIL_BYTES),
            *ANCHORS.items(),
            *RECHARGE_FORMULA_ANCHORS.items(),
        ):
            assert at(stock, va, len(expected)) == expected, f"0x{va:08x}"

    def test_apply_verify_detect_round_trip(self, stock):
        for integer_seconds in (False, True):
            data = bytearray(stock)
            patch = DescriptionTimersPatch(integer_seconds=integer_seconds)
            patch.apply(data)
            assert patch.verify(data) == []
            found = DescriptionTimersPatch.detect(data)
            assert found is not None and found.integer_seconds is integer_seconds

    def test_the_tail_is_not_a_branch_target(self, stock):
        """Nothing may jump into the middle of the six bytes the tail window replaces.

        `0x008086AA` and `0x008086AB` both are branch targets and this is not, which is the whole
        reason the window starts where it does. The check here is the cheap half: the four bytes
        the address encodes appear as an imm32 nowhere in the file, so no jump table reaches it
        either.
        """
        assert struct.pack("<I", DESCRIPTION_TAIL) not in stock
        assert struct.pack("<I", DESCRIPTION_BUTTON_CAPTURE) not in stock

    def test_it_composes_with_upgrade_description(self, stock):
        """Both patches edit this one function and neither reads what the other writes.

        `upgrade-description` rewrites `0x00808371`, which is inside the switch; this patch takes
        the prologue and the tail. They compose in either order, and both orders verify.
        """
        for order in (
            (DescriptionTimersPatch(), UpgradeDescriptionPatch()),
            (UpgradeDescriptionPatch(), DescriptionTimersPatch()),
        ):
            data = bytearray(stock)
            for patch in order:
                patch.apply(data)
            for patch in order:
                assert patch.verify(data) == [], type(patch).__name__
