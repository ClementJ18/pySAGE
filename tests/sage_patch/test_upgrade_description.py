"""Tests for the upgrade-description patch.

The patch is nine bytes of engine and one small cave, and both halves fail silently when wrong.
A window off by one instruction still assembles, still applies and still verifies against itself;
a cave that called `operator=` instead of `concat` would reproduce the bug it exists to remove and
nothing static would notice. So the cave is disassembled back and asserted to say what it was
meant to say - which of the three `UnicodeString` methods each `call` reaches, that the stack is
neutral, and that the guard really is the engine's own empty test.

:meth:`TestCave.test_the_message_is_appended_not_assigned` is the one that pins the feature.
:meth:`TestShape.test_the_two_windows_are_not_interchangeable` is why the sites are fingerprinted
separately: they are the same length and differ by one `rel32` and the order of two instructions,
so a patch that mixed them up would land a `jmp` mid-instruction.

The synthetic image is built from the patch's own tables, so it cannot confirm the addresses are
the right ones; :class:`TestInstalledBinary` does that against the real `game.dat` when it is
present, and ``docs/upgrade-description.md`` records the derivation.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_ini.engine import STOCK
from sage_patch.addresses import (
    DESCRIPTION_BLOCKED_ASSIGN,
    DESCRIPTION_BLOCKED_ASSIGN_BYTES,
    DESCRIPTION_BLOCKED_RESUME,
    DESCRIPTION_BLOCKED_RUN,
    DESCRIPTION_BLOCKED_RUN_BYTES,
    DESCRIPTION_PURCHASED_ASSIGN,
    DESCRIPTION_PURCHASED_ASSIGN_BYTES,
    DESCRIPTION_PURCHASED_RESUME,
    DESCRIPTION_PURCHASED_RUN,
    DESCRIPTION_PURCHASED_RUN_BYTES,
    DESCRIPTION_TEXT_EBP_OFFSET,
    UNICODE_STRING_APPEND,
    UNICODE_STRING_ASSIGN,
    UNICODE_STRING_CONCAT_WIDE,
    WIDE_BLANK_LINE,
    WIDE_NEWLINE,
)
from sage_patch.patches.upgrade_description import (
    ANCHORS,
    SECTION_NAME,
    SEPARATORS,
    SITES,
    UpgradeDescriptionPatch,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.synthetic import upgrade_description_image

_GAME_DAT = Path(r"C:\Program Files (x86)\Games\bfme\rotwk\game.dat")


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


def disassemble(base_va: int, body: bytes) -> list:
    """``body`` decoded, so a branch is read as a branch.

    A byte scan is not good enough here and the reason is worth stating: the cave is full of
    `lea ecx, [ebp-0x18]`, which encodes as ``8d 4d e8`` - and a scanner looking for ``e8`` finds
    the *displacement* and reads the next four bytes as a `rel32`. Every claim below is about
    where a `call` goes, so the decode has to be real.
    """
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return list(md.disasm(body, base_va))


def branch_targets(base_va: int, body: bytes) -> list[tuple[int, int]]:
    """Every ``call``/``jmp`` in ``body`` as ``(site VA, destination VA)``."""
    return [
        (insn.address, int(insn.op_str, 16))
        for insn in disassemble(base_va, body)
        if insn.mnemonic in ("call", "jmp")
    ]


@pytest.fixture
def image() -> bytearray:
    return upgrade_description_image()


class TestApply:
    def test_applies_and_verifies(self, image):
        patch = UpgradeDescriptionPatch()
        patch.apply(image)
        assert patch.verify(image) == []

    def test_verify_rejects_an_unpatched_image(self, image):
        problems = UpgradeDescriptionPatch().verify(image)
        assert problems and SECTION_NAME in problems[0]

    def test_applying_twice_raises(self, image):
        UpgradeDescriptionPatch().apply(image)
        with pytest.raises(ValueError, match="already carries"):
            UpgradeDescriptionPatch().apply(image)

    def test_the_default_leaves_the_blocked_case_alone(self, image):
        UpgradeDescriptionPatch().apply(image)
        assert (
            at(image, DESCRIPTION_BLOCKED_ASSIGN, len(DESCRIPTION_BLOCKED_ASSIGN_BYTES))
            == DESCRIPTION_BLOCKED_ASSIGN_BYTES
        )

    def test_also_blocked_rewrites_both(self, image):
        patch = UpgradeDescriptionPatch(also_blocked=True)
        patch.apply(image)
        assert patch.verify(image) == []
        for site in SITES.values():
            assert at(image, site.assign, 1) == b"\xe9", site.label

    def test_a_stray_byte_in_the_case_is_refused(self, image):
        off = va_to_offset(image, DESCRIPTION_PURCHASED_RUN + 3)
        image[off] ^= 0xFF
        with pytest.raises(ValueError, match="description builder"):
            UpgradeDescriptionPatch().apply(image)

    def test_a_moved_concat_is_refused(self, image):
        off = va_to_offset(image, UNICODE_STRING_APPEND)
        image[off] ^= 0xFF
        with pytest.raises(ValueError, match="UnicodeString methods"):
            UpgradeDescriptionPatch().apply(image)

    def test_an_unknown_separator_raises(self):
        with pytest.raises(ValueError, match="unknown separator"):
            UpgradeDescriptionPatch(separator="comma")

    def test_the_window_becomes_a_jump_into_the_cave(self, image):
        UpgradeDescriptionPatch().apply(image)
        base_va, _body = cave(image)
        window = at(image, DESCRIPTION_PURCHASED_ASSIGN, len(DESCRIPTION_PURCHASED_ASSIGN_BYTES))
        assert window[0] == 0xE9
        rel = struct.unpack_from("<i", window, 1)[0]
        assert DESCRIPTION_PURCHASED_ASSIGN + 5 + rel == base_va
        # The window is longer than the jump, and the remainder has to be nops rather than the
        # tail of the instructions it replaced - `push eax` / a partial `call` would still run.
        assert window[5:] == b"\x90" * (len(window) - 5)


class TestCave:
    """What the emitted code actually does, disassembled back out of the section."""

    @pytest.fixture
    def patched(self, image) -> bytearray:
        UpgradeDescriptionPatch(also_blocked=True).apply(image)
        return image

    @staticmethod
    def routine(data: bytes | bytearray) -> list:
        """The shared append routine, decoded: everything from the address the thunks call on."""
        base_va, body = cave(data)
        start = min(
            dest
            for _site, dest in branch_targets(base_va, body)
            if base_va <= dest < base_va + len(body)
        )
        return disassemble(start, body[start - base_va :])

    def test_the_message_is_appended_not_assigned(self, patched):
        """The whole point: `concat`, never `operator=`.

        `operator=` releases the buffer it is holding, which is exactly how the stock engine loses
        the description. A cave that reached it would be the bug, reimplemented.
        """
        base_va, body = cave(patched)
        targets = {dest for _site, dest in branch_targets(base_va, body)}
        assert UNICODE_STRING_APPEND in targets
        assert UNICODE_STRING_ASSIGN not in targets

    def test_the_separator_is_the_engines_own_literal(self, patched):
        base_va, body = cave(patched)
        assert struct.pack("<I", WIDE_NEWLINE) in body
        assert UNICODE_STRING_CONCAT_WIDE in {d for _site, d in branch_targets(base_va, body)}

    def test_blank_line_selects_the_other_literal(self, image):
        UpgradeDescriptionPatch(separator="blank-line").apply(image)
        _base_va, body = cave(image)
        assert struct.pack("<I", WIDE_BLANK_LINE) in body
        assert struct.pack("<I", WIDE_NEWLINE) not in body

    def test_each_site_resumes_where_its_window_ended(self, patched):
        base_va, body = cave(patched)
        destinations = {dest for _site, dest in branch_targets(base_va, body)}
        assert DESCRIPTION_PURCHASED_RESUME in destinations
        assert DESCRIPTION_BLOCKED_RESUME in destinations

    def test_the_routine_is_shared(self, patched):
        """Two thunks, one body: each site's `call` reaches the same address inside the cave."""
        base_va, body = cave(patched)
        internal = [
            dest
            for _site, dest in branch_targets(base_va, body)
            if base_va <= dest < base_va + len(body)
        ]
        assert len(internal) == 2
        assert internal[0] == internal[1]

    def test_the_routine_is_stack_neutral(self, patched):
        """Two pushes, no pop, and a plain `ret` - because both callees clean their own argument.

        The opening `push eax` does double duty: it preserves the message across the separator
        call *and* it is the stack argument the final `concat` reads. So a reader counting pushes
        against pops finds no pop at all, which is correct only because `concat` is `ret 4`.
        Asserting the shape here is what keeps that from being a coincidence.
        """
        routine = self.routine(patched)
        assert [i.mnemonic for i in routine].count("pop") == 0
        pushes = [i for i in routine if i.mnemonic == "push"]
        assert [i.op_str for i in pushes] == ["eax", hex(WIDE_NEWLINE)]
        assert routine[0].mnemonic == "push" and routine[0].op_str == "eax"
        assert routine[-1].mnemonic == "ret" and routine[-1].op_str == ""

    def test_the_guard_reads_the_description_slot(self, patched):
        """`mov eax, [ebp-0x18]`, then the engine's own two-part empty test."""
        routine = self.routine(patched)
        slot = f"[ebp - {abs(DESCRIPTION_TEXT_EBP_OFFSET):#x}]"
        assert routine[1].mnemonic == "mov" and routine[1].op_str == f"eax, dword ptr {slot}"
        assert routine[2].mnemonic == "test" and routine[2].op_str == "eax, eax"
        # ...and the length word inside the buffer, which is the half a null check would miss.
        assert any(i.mnemonic == "cmp" and i.op_str == "word ptr [eax + 4], 0" for i in routine)
        # every `this` is the description slot, never the temporary the engine builds at ebp-0x4c
        theirs = [i for i in routine if i.mnemonic == "lea"]
        assert [i.op_str for i in theirs] == [f"ecx, {slot}"] * 2

    def test_both_guard_arms_land_on_the_concat(self, patched):
        """The two `je`s skip the separator, not the message.

        A guard that jumped past the message instead would silently drop the whole line for any
        button with no `DescriptLabel` - which is most of them at the moment the case fires.
        """
        routine = self.routine(patched)
        message_call = [
            i
            for i in routine
            if i.mnemonic == "call" and int(i.op_str, 16) == UNICODE_STRING_APPEND
        ]
        assert len(message_call) == 1
        target = [int(i.op_str, 16) for i in routine if i.mnemonic == "je"]
        assert len(target) == 2 and len(set(target)) == 1
        # the label sits on the `lea` that sets up the message concat, one instruction before it
        assert target[0] < message_call[0].address


class TestShape:
    """Properties of the sites themselves, independent of any image."""

    def test_the_windows_are_the_same_length(self):
        assert len(DESCRIPTION_PURCHASED_ASSIGN_BYTES) == len(DESCRIPTION_BLOCKED_ASSIGN_BYTES)

    def test_the_two_windows_are_not_interchangeable(self):
        """Same length, same three instructions, different order and a different `rel32`.

        This is why each site carries its own fingerprint: the bytes alone cannot tell them apart
        by length, so a check that only measured would accept the wrong one and land a `jmp` in
        the middle of an instruction.
        """
        assert DESCRIPTION_PURCHASED_ASSIGN_BYTES != DESCRIPTION_BLOCKED_ASSIGN_BYTES
        assert DESCRIPTION_PURCHASED_ASSIGN_BYTES[0] == 0x8D  # lea ecx, [ebp-0x18] first
        assert DESCRIPTION_BLOCKED_ASSIGN_BYTES[0] == 0x50  # push eax first

    def test_both_windows_call_operator_assign(self):
        """What makes each window "the assignment" is where its `call` goes."""
        for window_va, window in (
            (DESCRIPTION_PURCHASED_ASSIGN, DESCRIPTION_PURCHASED_ASSIGN_BYTES),
            (DESCRIPTION_BLOCKED_ASSIGN, DESCRIPTION_BLOCKED_ASSIGN_BYTES),
        ):
            calls = [i for i in disassemble(window_va, window) if i.mnemonic == "call"]
            assert [int(i.op_str, 16) for i in calls] == [UNICODE_STRING_ASSIGN]

    def test_each_window_sits_inside_its_run(self):
        for site in SITES.values():
            end = site.offset + len(site.assign_bytes)
            assert site.run_bytes[site.offset : end] == site.assign_bytes, site.label

    def test_each_run_resumes_immediately_after_its_window(self):
        assert DESCRIPTION_PURCHASED_RESUME == DESCRIPTION_PURCHASED_ASSIGN + len(
            DESCRIPTION_PURCHASED_ASSIGN_BYTES
        )
        assert DESCRIPTION_BLOCKED_RESUME == DESCRIPTION_BLOCKED_ASSIGN + len(
            DESCRIPTION_BLOCKED_ASSIGN_BYTES
        )

    def test_the_window_has_room_for_a_near_jump(self):
        for site in SITES.values():
            assert len(site.assign_bytes) >= 5, site.label

    def test_the_two_cases_are_adjacent(self):
        """The blocked case ends where the already-upgraded one's guard begins.

        Which is why the stand-in plants both: a fingerprint that overran its case would meet real
        code rather than zeroes, the same property `observer-switch`'s two predicates give it.
        """
        assert DESCRIPTION_BLOCKED_RUN < DESCRIPTION_PURCHASED_RUN
        blocked_end = DESCRIPTION_BLOCKED_RUN + len(DESCRIPTION_BLOCKED_RUN_BYTES)
        assert blocked_end < DESCRIPTION_PURCHASED_RUN

    def test_the_separators_are_anchored(self):
        for va in SEPARATORS.values():
            assert va in ANCHORS


class TestDetect:
    @pytest.mark.parametrize("separator", sorted(SEPARATORS))
    @pytest.mark.parametrize("also_blocked", [False, True])
    def test_round_trips_every_configuration(self, image, separator, also_blocked):
        UpgradeDescriptionPatch(separator=separator, also_blocked=also_blocked).apply(image)
        found = UpgradeDescriptionPatch.detect(image)
        assert found is not None
        assert (found.separator, found.also_blocked) == (separator, also_blocked)

    def test_absent_from_a_stock_image(self, image):
        assert UpgradeDescriptionPatch.detect(image) is None


class TestSurface:
    def test_changes_no_ini(self, image):
        """No keyword, no name-table token: the strings it joins are ones the engine fetched."""
        assert UpgradeDescriptionPatch().ini_surface() is STOCK


class TestRegistry:
    def test_is_registered(self):
        assert PATCHES[UpgradeDescriptionPatch.name] is UpgradeDescriptionPatch

    def test_is_attributed(self):
        assert UpgradeDescriptionPatch.author

    def test_is_not_experimental(self):
        assert not UpgradeDescriptionPatch.experimental


@pytest.mark.skipif(
    not _GAME_DAT.exists(), reason="requires a local ROTWK install (not available in CI)"
)
class TestInstalledBinary:
    """The addresses against the real `game.dat`. The only thing here that can catch a patch
    aimed at bytes that are not actually the tooltip builder's status-message cases."""

    @pytest.fixture
    def installed(self) -> bytearray:
        return bytearray(_GAME_DAT.read_bytes())

    def test_both_cases_are_present(self, installed):
        for site in SITES.values():
            end = site.offset + len(site.assign_bytes)
            got = at(installed, site.run, len(site.run_bytes))
            # Everything but the window, which may already be patched.
            assert got[: site.offset] == site.run_bytes[: site.offset], site.label
            assert got[end:] == site.run_bytes[end:], site.label

    def test_the_callees_are_present(self, installed):
        for va, expected in ANCHORS.items():
            assert at(installed, va, len(expected)) == expected, f"0x{va:08x}"

    def test_the_default_key_is_referenced_once(self, installed):
        """`TOOLTIP:AlreadyUpgradedDefault` has exactly one `push` in the image, and it is inside
        the case this patch edits. That single reference is what identifies the site."""
        key_va = 0x00C4EEE4
        assert at(installed, key_va, 30) == b"TOOLTIP:AlreadyUpgradedDefault"
        needle = struct.pack("<I", key_va)
        assert installed.count(needle) == 1
        found = installed.index(needle)
        run_off = va_to_offset(installed, DESCRIPTION_PURCHASED_RUN)
        assert run_off <= found < run_off + len(DESCRIPTION_PURCHASED_RUN_BYTES)

    def test_applies_to_a_stock_copy(self, installed):
        if find_section(installed, SECTION_NAME) is not None:
            pytest.skip("the installed game.dat already carries this patch")
        patch = UpgradeDescriptionPatch(also_blocked=True)
        patch.apply(installed)
        assert patch.verify(installed) == []
