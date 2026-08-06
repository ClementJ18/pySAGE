"""Tests for the stranded-battalion-member patch.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter most
disassemble it back and assert it says what it was meant to say. A wrong byte does not raise -
it makes every attack in the game resolve through a routine that reads the wrong field, which is
the kind of error only a static check catches.

The other half is the build fingerprint. This patch reads two things it does not rewrite - the
two branches that enter the block it relocates, and the prologue of `Object::testStatus`, which
its cave calls - and both have to fail loudly on anything that is not the expected build.
"""

from __future__ import annotations

import struct

import pytest
from capstone import CS_ARCH_X86, CS_MODE_32, Cs

from sage_patch import HordeOrphanTargetPatch, apply_patches
from sage_patch.patches.horde_orphan_target import (
    ENTRY_BRANCHES,
    FALLBACK_BYTES,
    FALLBACK_VA,
    FIND_OBJECT_BY_ID_VA,
    HELPER_FALLBACK_BYTES,
    HELPER_FALLBACK_VA,
    HELPER_NONE_VA,
    HELPER_RETURN_VA,
    SECTION_NAME,
    STATUS_IS_LEAVING_FACTORY,
    TARGET_CONTAINER_VA,
    TARGET_VICTIM_VA,
    TEST_STATUS_PROLOGUE,
    TEST_STATUS_VA,
    build_gate,
    build_helper_gate,
)
from sage_patch.utils import find_section, va_to_offset

IMAGE_BASE = 0x400000


def synthetic_image() -> bytearray:
    """A PE32 image mapping every site this patch asserts or replaces, holding exactly what the
    real ``2.01.2614.37001`` build holds there - so the whole apply + verify path runs in CI
    without the copyrighted `game.dat`, and a patch aimed at a wrong address fails here too."""
    highest = 0x00700000 - IMAGE_BASE
    data = bytearray(((highest + 0x400) // 0x200 + 1) * 0x200)

    data[0:2] = b"MZ"
    e = 0x80
    struct.pack_into("<I", data, 0x3C, e)
    data[e : e + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, e + 4, 0x14C)  # Machine (i386)
    struct.pack_into("<H", data, e + 6, 1)  # NumberOfSections
    struct.pack_into("<H", data, e + 20, 0xE0)  # SizeOfOptionalHeader
    opt = e + 24
    struct.pack_into("<H", data, opt, 0x10B)  # PE32 magic
    struct.pack_into("<I", data, opt + 28, IMAGE_BASE)
    struct.pack_into("<I", data, opt + 32, 0x1000)  # SectionAlignment
    struct.pack_into("<I", data, opt + 36, 0x200)  # FileAlignment
    struct.pack_into("<I", data, opt + 56, 0x2000000)  # SizeOfImage
    struct.pack_into("<I", data, opt + 60, 0x400)  # SizeOfHeaders, room for more headers
    header = bytearray(40)
    header[0:8] = b".text\x00\x00\x00"
    size = len(data) - 0x1000
    struct.pack_into("<IIII", header, 8, size, 0x1000, size, 0x1000)
    data[opt + 0xE0 : opt + 0xE0 + 40] = header

    def write(va: int, blob: bytes) -> None:
        data[va - IMAGE_BASE : va - IMAGE_BASE + len(blob)] = blob

    write(FALLBACK_VA, FALLBACK_BYTES)
    write(HELPER_FALLBACK_VA, HELPER_FALLBACK_BYTES)
    write(TEST_STATUS_VA, TEST_STATUS_PROLOGUE)
    for va, encoding in ENTRY_BRANCHES:
        write(va, encoding)
    return data


@pytest.fixture
def image() -> bytearray:
    return synthetic_image()


def _patched(image: bytearray) -> bytearray:
    data = bytearray(image)
    HordeOrphanTargetPatch().apply(data)
    return data


def _cave(data: bytes | bytearray) -> tuple[int, int]:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    section_va, section_off, _vsize = located
    return section_va, section_off


def _disasm(data: bytes | bytearray, va: int, length: int) -> list[tuple[str, str]]:
    off = va_to_offset(data, va)
    assert off is not None
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    return [(i.mnemonic, i.op_str) for i in md.disasm(bytes(data[off : off + length]), va)]


# --- round trip ------------------------------------------------------------------------------


def test_apply_then_verify(image):
    data = _patched(image)
    assert HordeOrphanTargetPatch().verify(data) == []


def test_an_unpatched_image_does_not_verify(image):
    problems = HordeOrphanTargetPatch().verify(image)
    assert problems and SECTION_NAME in problems[0]


def test_detect_finds_it_only_once_applied(image):
    assert HordeOrphanTargetPatch.detect(image) is None
    assert HordeOrphanTargetPatch.detect(_patched(image)) is not None


def test_applying_twice_fails_rather_than_double_patching(image):
    data = _patched(image)
    with pytest.raises(ValueError):
        HordeOrphanTargetPatch().apply(data)


def test_it_writes_a_file(tmp_path, image):
    src = tmp_path / "game.dat"
    src.write_bytes(bytes(image))
    out = apply_patches(src, [HordeOrphanTargetPatch()], output=tmp_path / "patched.dat")
    assert HordeOrphanTargetPatch().verify(out.read_bytes()) == []


# --- what the detour and the cave actually say -------------------------------------------------


def test_the_resolver_fallback_jumps_to_the_cave_and_the_rest_is_a_trap(image):
    """The block is entered only at its first byte, so everything past the jump is unreachable -
    filled with `int3` rather than left as half of a relocated instruction."""
    data = _patched(image)
    section_va, _off = _cave(data)
    body = _disasm(data, FALLBACK_VA, len(FALLBACK_BYTES))
    assert body[0] == ("jmp", hex(section_va))
    assert {mnemonic for mnemonic, _ops in body[1:]} == {"int3"}
    assert len(body) == 1 + (len(FALLBACK_BYTES) - 5)


def test_the_shared_helper_is_gated_too(image):
    """The one that matters. `resolveAttackTarget` holds an inlined copy of this redirect, but
    `Object::getHorde` is what 114 call sites - including a clicked attack - actually go
    through, and patching only the copy changed nothing observable in a live game."""
    data = _patched(image)
    section_va, _off = _cave(data)
    helper_va = section_va + len(build_gate(section_va))
    body = _disasm(data, HELPER_FALLBACK_VA, len(HELPER_FALLBACK_BYTES))
    assert body[0] == ("jmp", hex(helper_va))
    assert {mnemonic for mnemonic, _ops in body[1:]} == {"int3"}

    code = _disasm(data, helper_va, len(build_helper_gate(helper_va)))
    assert code[0] == ("push", "ecx"), "`this` must survive the call"
    assert code[1] == ("push", hex(STATUS_IS_LEAVING_FACTORY))
    assert code[2] == ("call", hex(TEST_STATUS_VA))
    assert code[3] == ("pop", "ecx")
    assert code[4] == ("test", "al, al")
    assert code[5][0] == "je"


def test_the_helper_gate_reads_the_useproducer_flag_at_the_same_slot(image):
    """It is reached by a jump, not a call, so the caller's frame is untouched and the
    relocated `cmp byte [esp+8], 0` still names the same argument. A `push` left unbalanced
    before it would silently read the wrong slot."""
    data = _patched(image)
    section_va, _off = _cave(data)
    helper_va = section_va + len(build_gate(section_va))
    code = _disasm(data, helper_va, len(build_helper_gate(helper_va)))
    assert ("cmp", "byte ptr [esp + 8], 0") in code
    pushes = [ops for mnemonic, ops in code if mnemonic == "push"]
    pops = [ops for mnemonic, ops in code if mnemonic == "pop"]
    assert pushes[0] == "ecx" and pops == ["ecx"], "the only save is balanced before the cmp"


def test_the_helper_gate_exits_where_the_stock_block_did(image):
    data = _patched(image)
    section_va, _off = _cave(data)
    helper_va = section_va + len(build_gate(section_va))
    code = _disasm(data, helper_va, len(build_helper_gate(helper_va)))
    assert [ops for mnemonic, ops in code if mnemonic == "jmp"] == [
        hex(HELPER_RETURN_VA),
        hex(HELPER_NONE_VA),
    ]


def test_a_different_helper_block_refuses(image):
    """The shared helper is relocated verbatim like the resolver's copy, so a build that shaped
    it differently would have this patch reproduce the wrong code at a new address."""
    off = va_to_offset(image, HELPER_FALLBACK_VA)
    assert off is not None
    image[off : off + 3] = bytes([0x90, 0x90, 0x90])
    with pytest.raises(ValueError, match="getHorde"):
        HordeOrphanTargetPatch().apply(image)


def test_the_gate_tests_the_status_before_anything_else(image):
    """The whole point: the producer lookup must not run for a unit that has stopped leaving a
    factory, so the test and its branch come first."""
    data = _patched(image)
    section_va, _off = _cave(data)
    code = _disasm(data, section_va, len(build_gate(section_va)))
    assert code[0] == ("push", hex(STATUS_IS_LEAVING_FACTORY))
    assert code[1] == ("mov", "ecx, esi")
    assert code[2] == ("call", hex(TEST_STATUS_VA))
    assert code[3] == ("test", "al, al")
    assert code[4][0] == "je"


def test_the_gate_reproduces_the_block_it_relocated(image):
    """Everything after the test is the stock block, instruction for instruction. Only its three
    branch targets move, because they became near jumps out of the cave."""
    data = _patched(image)
    section_va, _off = _cave(data)
    code = _disasm(data, section_va, len(build_gate(section_va)))
    stock = [(mnemonic, ops) for mnemonic, ops in code[5:] if mnemonic not in {"je", "jmp"}]
    assert stock == [
        ("push", "dword ptr [esi + 0x78]"),
        ("mov", "ecx, dword ptr [0xde412c]"),
        ("call", hex(FIND_OBJECT_BY_ID_VA)),
        ("cmp", "eax, ebx"),
        ("mov", "ecx, dword ptr [eax + 4]"),
        ("test", "dword ptr [ecx + 0x114], edi"),
    ]


def test_every_rejection_lands_on_the_victim_and_only_success_on_the_container(image):
    """Three ways to decide the producer is not a horde to redirect to, and the new status test
    is a fourth - all four have to reach the same exit, or a stranded unit resolves to garbage."""
    data = _patched(image)
    section_va, _off = _cave(data)
    code = _disasm(data, section_va, len(build_gate(section_va)))
    victim_exit = hex(TARGET_VICTIM_VA)
    assert [ops for mnemonic, ops in code if mnemonic == "jmp"] == [
        hex(TARGET_CONTAINER_VA),
        victim_exit,
    ]
    branches = [ops for mnemonic, ops in code if mnemonic == "je"]
    assert len(branches) == 3, "the status test plus the block's own two rejections"
    assert len(set(branches)) == 1, "all three reject to one place"
    # They branch inside the cave, to the final `jmp` that leaves for the victim exit.
    assert _disasm(data, int(branches[0], 16), 5) == [("jmp", victim_exit)]


def test_the_cave_preserves_what_the_caller_still_needs(image):
    """`esi`, `ebx` and `edi` carry the victim, zero and the KINDOF mask across the whole
    routine. Nothing may write them - `Object::testStatus` does not, which is why no save is
    emitted, so a stray `mov` here would be a silent corruption of branch A."""
    data = _patched(image)
    section_va, _off = _cave(data)
    code = _disasm(data, section_va, len(build_gate(section_va)))
    written = {ops.split(",")[0].strip() for mnemonic, ops in code if mnemonic in {"mov", "pop"}}
    assert not written & {"esi", "ebx", "edi"}


# --- build fingerprint --------------------------------------------------------------------------


def test_a_different_entry_branch_refuses(image):
    """If branch A no longer reaches the block with those two `je`s, this cave cannot stand in
    for it - and the failure has to be loud, not a silently unreachable cave."""
    va, _encoding = ENTRY_BRANCHES[0]
    off = va_to_offset(image, va)
    assert off is not None
    image[off : off + 2] = b"\x90\x90"
    with pytest.raises(ValueError, match="fallback"):
        HordeOrphanTargetPatch().apply(image)


def test_a_different_test_status_refuses(image):
    """The cave calls this address with a status bit. Calling anything else with one would be a
    wild call on every attack order in the game."""
    off = va_to_offset(image, TEST_STATUS_VA)
    assert off is not None
    image[off : off + 4] = b"\x90\x90\x90\x90"
    with pytest.raises(ValueError, match="testStatus"):
        HordeOrphanTargetPatch().apply(image)


def test_a_different_fallback_block_refuses(image):
    """The block is relocated verbatim, so a build that shaped it differently would have this
    patch reproduce the wrong code at a new address."""
    off = va_to_offset(image, FALLBACK_VA)
    assert off is not None
    image[off : off + 3] = b"\x90\x90\x90"
    with pytest.raises(ValueError, match="ancestry fallback"):
        HordeOrphanTargetPatch().apply(image)


def test_verify_notices_a_tampered_cave(image):
    data = _patched(image)
    _section_va, off = _cave(data)
    data[off] = 0x90
    problems = HordeOrphanTargetPatch().verify(data)
    assert problems and "gate" in problems[0]


def test_verify_notices_a_restored_fallback(image):
    """Half-reverted is the state that would run the stock block *and* leave a cave behind."""
    data = _patched(image)
    off = va_to_offset(data, FALLBACK_VA)
    assert off is not None
    data[off : off + len(FALLBACK_BYTES)] = FALLBACK_BYTES
    problems = HordeOrphanTargetPatch().verify(data)
    assert any("does not jump to the cave" in p for p in problems)
