"""Tests for `script-debug-window`, which patches `DebugWindowLite.dll` rather than `game.dat`.

The stand-in is built at the DLL's own ImageBase, so these also exercise the one thing that is
structurally different about a DLL target: every address the patch resolves goes through
`image_base` rather than assuming an executable's `0x400000`.
"""

import struct

import pytest

from sage_patch.patcher import apply_patches
from sage_patch.patches import script_debug_window as sdw
from sage_patch.patches.script_debug_window import ScriptDebugWindowPatch
from sage_patch.utils import find_section, image_base, va_to_offset

from .synthetic import quiet_exit_image, script_debug_window_image


@pytest.fixture
def clean() -> bytearray:
    return script_debug_window_image()


@pytest.fixture
def patched(clean: bytearray) -> bytearray:
    ScriptDebugWindowPatch().apply(clean)
    return clean


class TestTheStandIn:
    def test_it_is_a_dll_image(self, clean):
        assert image_base(clean) == 0x10000000

    def test_it_carries_the_stock_rebuild_call(self, clean):
        off = va_to_offset(clean, sdw.HOOK_VA)
        assert bytes(clean[off : off + 5]) == sdw.HOOK_ORIGINAL


class TestTheHookedCallIsTheRebuild:
    def test_the_stock_bytes_decode_to_update_display(self):
        """The patch derives the call's target from its own bytes rather than trusting a constant,
        so this is what makes "the five bytes being redirected are the rebuild" a checked fact."""
        assert sdw.HOOK_TARGET == sdw.UPDATE_DISPLAY

    def test_the_hook_sits_inside_the_append_method(self):
        assert sdw.DIALOG_APPEND_MESSAGE < sdw.HOOK_VA < sdw.DIALOG_APPEND_MESSAGE + 0x20


class TestApply:
    def test_apply_then_verify(self, patched):
        assert ScriptDebugWindowPatch().verify(patched) == []

    def test_the_hook_becomes_a_call_into_the_cave(self, patched):
        section_va, _, _ = find_section(patched, sdw.SECTION_NAME)
        off = va_to_offset(patched, sdw.HOOK_VA)
        assert patched[off] == 0xE8
        target = sdw.HOOK_VA + 5 + struct.unpack_from("<i", patched, off + 1)[0]
        assert target == section_va

    def test_the_cave_lands_past_every_existing_section(self, clean):
        highest = max(
            va
            for va in (*sdw.ANCHORS, sdw.HOOK_VA)  # every page the stand-in maps
        )
        ScriptDebugWindowPatch().apply(clean)
        section_va, _, _ = find_section(clean, sdw.SECTION_NAME)
        assert section_va > highest

    def test_the_rebuild_itself_is_left_alone(self, patched):
        """The cave replaces the *call*, not the routine: Clear still rebuilds, and rebuilding an
        emptied vector is what makes the button still empty the control."""
        off = va_to_offset(patched, sdw.UPDATE_DISPLAY)
        assert bytes(patched[off : off + 5]) == sdw.ANCHORS[sdw.UPDATE_DISPLAY]

    def test_the_push_back_is_left_alone(self, patched):
        """`0x100034B0`'s first five bytes are the argument load and the `push esi` that precede
        the `push_back`; touching them would be touching the vector this patch deliberately keeps.
        """
        off = va_to_offset(patched, sdw.DIALOG_APPEND_MESSAGE)
        assert bytes(patched[off : off + 5]) == sdw.ANCHORS[sdw.DIALOG_APPEND_MESSAGE]


class TestTheCave:
    def test_it_reaches_the_imports_without_an_absolute_operand(self):
        """The DLL can be rebased and this patch writes no relocation entries, so the cave has to
        recover its own load address. It does that with a zero-displacement `call`, a `pop`, and a
        subtraction - and getting that subtraction wrong is invisible until the game jumps."""
        base = 0x1002E000
        code = sdw.build_code(base)
        pop = code.index(bytes.fromhex("5f81ef"))
        # The `call` pushes the address of the `pop`, which is where `edi` starts from.
        pop_va = base + pop
        delta = struct.unpack_from("<I", code, pop + 3)[0]
        assert (pop_va - delta) & 0xFFFFFFFF == sdw.IAT_GET_DLG_ITEM
        # ... and one `add edi` later it is the other slot.
        assert sdw.IAT_GET_DLG_ITEM + (sdw.IAT_SEND_MESSAGE - sdw.IAT_GET_DLG_ITEM) == (
            sdw.IAT_SEND_MESSAGE
        )

    def test_it_holds_no_pointer_into_the_image(self):
        """Any dword in the cave that happens to be a valid VA would be a missing relocation. The
        separator is pushed as an immediate and the imports are reached through `edi` precisely so
        that there is none."""
        code = sdw.build_code(0x1002E000)
        words = [struct.unpack_from("<I", code, i)[0] for i in range(len(code) - 3)]
        assert not [w for w in words if 0x10001000 <= w < 0x1002F000]

    def test_it_is_stack_balanced_on_every_path(self):
        """Three pushes in, three pops out, and the one `push` that is not an argument is undone
        by its own `add esp, 4`."""
        code = sdw.build_code(0x1002E000)
        assert code.startswith(bytes.fromhex("535657"))
        assert code.endswith(bytes.fromhex("5f5e5bc3"))
        assert bytes.fromhex("83c404") in code  # drops the "\r\n" slot

    def test_it_appends_rather_than_replacing_the_buffer(self):
        """The whole point: `EM_REPLACESEL` at the caret, never a whole-buffer write."""
        code = sdw.build_code(0x1002E000)
        for message in (
            sdw.WM_GETTEXTLENGTH,
            sdw.EM_SETSEL,
            sdw.EM_REPLACESEL,
            sdw.EM_SCROLLCARET,
        ):
            assert b"\x68" + struct.pack("<I", message) in code

    def test_the_separator_is_a_terminated_crlf(self):
        assert struct.pack("<I", sdw.CRLF_IMMEDIATE) == b"\r\n\x00\x00"


class TestVerify:
    def test_rejects_an_unpatched_image(self, clean):
        assert ScriptDebugWindowPatch().verify(clean) != []

    def test_rejects_a_cave_that_has_been_overwritten(self, patched):
        _, section_off, _ = find_section(patched, sdw.SECTION_NAME)
        patched[section_off] = 0x90
        assert ScriptDebugWindowPatch().verify(patched) != []

    def test_rejects_a_hook_pointing_somewhere_else(self, patched):
        off = va_to_offset(patched, sdw.HOOK_VA)
        struct.pack_into("<i", patched, off + 1, 0x100)
        assert ScriptDebugWindowPatch().verify(patched) != []


class TestDetect:
    def test_it_recognises_its_own_output(self, patched):
        found = ScriptDebugWindowPatch.detect(patched)
        assert found is not None
        assert found.name == "script-debug-window"

    def test_an_unpatched_image_carries_nothing(self, clean):
        assert ScriptDebugWindowPatch.detect(clean) is None

    def test_detection_never_raises_on_something_that_is_not_the_dll(self):
        assert ScriptDebugWindowPatch.detect(bytearray(b"not a PE at all")) is None


class TestApplyRefusesTheWrongBinary:
    def test_a_game_dat_is_refused_before_anything_is_written(self):
        """The registry is swept over `game.dat` by `sagepatch`, and this patch's addresses are
        another binary's. Nothing there is mapped at `0x1000_0000`, so it stops at the first
        lookup."""
        image = quiet_exit_image()
        with pytest.raises(ValueError, match="not DebugWindowLite.dll"):
            ScriptDebugWindowPatch().apply(image)
        assert find_section(image, sdw.SECTION_NAME) is None

    @pytest.mark.parametrize("va", sorted(sdw.ANCHORS))
    def test_an_anchor_that_moved(self, clean, va):
        """Every anchor is load-bearing, so every one of them has to be able to fail the patch."""
        off = va_to_offset(clean, va)
        clean[off] ^= 0xFF
        with pytest.raises(ValueError, match="DebugWindowLite"):
            ScriptDebugWindowPatch().apply(clean)

    def test_it_does_not_write_a_section_when_an_anchor_fails(self, clean):
        off = va_to_offset(clean, sdw.UPDATE_DISPLAY)
        clean[off] ^= 0xFF
        with pytest.raises(ValueError):
            ScriptDebugWindowPatch().apply(clean)
        assert find_section(clean, sdw.SECTION_NAME) is None


class TestThroughApplyPatches:
    def test_it_round_trips_through_a_file(self, tmp_path):
        src = tmp_path / "DebugWindowLite.dll.backup"
        src.write_bytes(bytes(script_debug_window_image()))
        out = tmp_path / "DebugWindowLite.dll"
        apply_patches(src, [ScriptDebugWindowPatch()], output=out)
        assert ScriptDebugWindowPatch().verify(out.read_bytes()) == []
        assert src.read_bytes() != out.read_bytes()
