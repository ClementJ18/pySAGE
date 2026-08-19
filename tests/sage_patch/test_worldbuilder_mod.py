"""Tests for the Worldbuilder `-mod` patch.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter most
disassemble it back and assert it says what it was meant to say. Every failure mode of this patch
is silent: a `call` off by a byte lands mid-instruction in the file-system module, a hook that
does not restore the instruction it displaced corrupts `InitInstance`'s frame, and a cave that
forgets to preserve registers breaks a function it never returns a value to. None of that raises
at apply time, and the first symptom is an editor that crashes or quietly ignores `-mod` - which
is indistinguishable from the bug the patch exists to fix.

The other half is the build fingerprint. The hook has to sit *before* Worldbuilder's first INI
read to matter at all, so the patch pins both ends of that window and must refuse anything else.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.patches.worldbuilder_mod import (
    _CODE_OFF,
    _HOOK_BYTES,
    ANCHORS,
    ARCHIVE_FS_PTR,
    GET_COMMAND_LINE_A,
    HOOK_VA,
    SECTION_NAME,
    SET_MOD_DIR,
    WorldbuilderModPatch,
    build_section,
)
from sage_patch.utils import find_section, va_to_offset

from .synthetic import worldbuilder_mod_image


@pytest.fixture
def image() -> bytearray:
    return worldbuilder_mod_image()


def _patched(image: bytearray) -> tuple[bytearray, int]:
    WorldbuilderModPatch().apply(image)
    located = find_section(image, SECTION_NAME)
    assert located is not None
    return image, located[0]


def test_applies_and_verifies_clean(image: bytearray) -> None:
    data, _ = _patched(image)
    assert WorldbuilderModPatch().verify(data) == []


def test_detect_recognises_only_a_patched_image(image: bytearray) -> None:
    assert WorldbuilderModPatch.detect(image) is None
    data, _ = _patched(image)
    detected = WorldbuilderModPatch.detect(data)
    assert detected is not None
    assert detected.name == "worldbuilder-mod"


def test_hook_calls_the_cave_and_pads_the_window(image: bytearray) -> None:
    data, section_va = _patched(image)
    off = va_to_offset(data, HOOK_VA)
    assert off is not None
    window = bytes(data[off : off + len(_HOOK_BYTES)])

    assert window[0] == 0xE8, "the hook must be a call, not a jump: the cave returns with ret"
    displacement = struct.unpack_from("<i", window, 1)[0]
    assert HOOK_VA + 5 + displacement == section_va + _CODE_OFF
    # Every byte of the displaced instruction has to be accounted for; a leftover would be
    # decoded as an instruction when control falls back through.
    assert window[5:] == b"\x90" * (len(_HOOK_BYTES) - 5)


def test_cave_restores_the_displaced_instruction_before_returning(image: bytearray) -> None:
    """The hook consumes a `mov ecx, [ebp-0x1758]` whose result the next instruction stores.

    Dropping it would leave `ecx` holding whatever `popad` restored, and `InitInstance` would
    file a garbage pointer into its own frame - so the cave has to re-run it, *after* `popad`
    rather than before, or the restore would immediately overwrite it.
    """
    data, section_va = _patched(image)
    content = build_section(section_va)
    tail = content[_CODE_OFF:]
    assert tail.endswith(b"\x9d\x61" + _HOOK_BYTES + b"\xc3"), (
        "the cave must end popfd, popad, <displaced instruction>, ret"
    )


def test_cave_brackets_itself_with_pushad_pushfd(image: bytearray) -> None:
    data, section_va = _patched(image)
    content = build_section(section_va)
    assert content[_CODE_OFF : _CODE_OFF + 2] == b"\x60\x9c", (
        "the cave runs mid-function and must preserve every register and flag"
    )


def test_cave_calls_the_engine_at_the_addresses_it_names(image: bytearray) -> None:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    data, section_va = _patched(image)
    content = build_section(section_va)
    code_va = section_va + _CODE_OFF

    direct: list[int] = []
    indirect: list[int] = []
    reads: list[int] = []
    for insn in md.disasm(bytes(content[_CODE_OFF:]), code_va):
        if insn.mnemonic == "call" and not insn.op_str.startswith("dword"):
            direct.append(int(insn.op_str, 16))
        elif insn.mnemonic == "call":
            indirect.append(int(insn.op_str.split("[")[1].rstrip("]"), 16))
        elif insn.mnemonic == "mov" and insn.op_str.startswith("eax, dword ptr ["):
            reads.append(int(insn.op_str.split("[")[1].rstrip("]"), 16))

    assert direct == [SET_MOD_DIR], "the cave's only direct call is the mod-directory setter"
    assert indirect == [GET_COMMAND_LINE_A]
    assert ARCHIVE_FS_PTR in reads, "the cave must check the file system before calling into it"


def test_cave_balances_the_stack_around_the_setter(image: bytearray) -> None:
    """`0x01682780` is cdecl, so the one argument pushed has to be popped by the caller."""
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    data, section_va = _patched(image)
    content = build_section(section_va)

    insns = list(md.disasm(bytes(content[_CODE_OFF:]), section_va + _CODE_OFF))
    call_index = next(
        i
        for i, insn in enumerate(insns)
        if insn.mnemonic == "call" and insn.op_str == hex(SET_MOD_DIR)
    )
    assert insns[call_index - 1].mnemonic == "push"
    assert (insns[call_index + 1].mnemonic, insns[call_index + 1].op_str) == ("add", "esp, 4")


def test_cave_points_the_setter_at_its_own_buffer(image: bytearray) -> None:
    """The path handed over must be the cave's buffer, which lives inside the section it owns."""
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    data, section_va = _patched(image)
    located = find_section(data, SECTION_NAME)
    assert located is not None
    _va, _off, vsize = located
    content = build_section(section_va)

    insns = list(md.disasm(bytes(content[_CODE_OFF:]), section_va + _CODE_OFF))
    pushed = next(
        insns[i - 1]
        for i, insn in enumerate(insns)
        if insn.mnemonic == "call" and insn.op_str == hex(SET_MOD_DIR)
    )
    buffer_va = int(pushed.op_str, 16)
    assert section_va <= buffer_va < section_va + _CODE_OFF, (
        "the buffer must sit in the cave's own data area, not in engine memory"
    )
    assert buffer_va + 128 < section_va + vsize


@pytest.mark.parametrize("anchor_va", sorted(ANCHORS))
def test_refuses_a_build_whose_anchors_moved(image: bytearray, anchor_va: int) -> None:
    off = va_to_offset(image, anchor_va)
    assert off is not None
    image[off] ^= 0xFF
    with pytest.raises(ValueError, match="not the one the cave was written against"):
        WorldbuilderModPatch().apply(image)


def test_refuses_a_build_whose_hook_window_moved(image: bytearray) -> None:
    off = va_to_offset(image, HOOK_VA)
    assert off is not None
    image[off] ^= 0xFF
    with pytest.raises(ValueError):
        WorldbuilderModPatch().apply(image)


def test_refuses_an_aslr_image(image: bytearray) -> None:
    e_lfanew = struct.unpack_from("<I", image, 0x3C)[0]
    dll_characteristics_off = e_lfanew + 24 + 70
    (stock,) = struct.unpack_from("<H", image, dll_characteristics_off)
    struct.pack_into("<H", image, dll_characteristics_off, stock | 0x0040)
    with pytest.raises(ValueError, match="DYNAMIC_BASE"):
        WorldbuilderModPatch().apply(image)


def test_verify_reports_a_tampered_cave(image: bytearray) -> None:
    data, section_va = _patched(image)
    located = find_section(data, SECTION_NAME)
    assert located is not None
    _va, section_off, _vsize = located
    data[section_off + _CODE_OFF] ^= 0xFF
    problems = WorldbuilderModPatch().verify(data)
    assert problems and "cave" in problems[0]


def test_verify_reports_a_missing_section(image: bytearray) -> None:
    assert WorldbuilderModPatch().verify(image) == [
        f"no {SECTION_NAME} section: the file does not carry this patch"
    ]
