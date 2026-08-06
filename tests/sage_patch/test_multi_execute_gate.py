"""Tests for the `OK_FOR_MULTI_EXECUTE` model-condition gate.

Two things can go wrong here and neither raises on its own, so both are checked statically.

The first is the **stack arithmetic**. Each shim borrows the `Object*` and the
`SpecialPowerTemplate*` out of arguments the caller already pushed, and the two loops push them at
different depths. A displacement that is four bytes out reads the neighbouring argument - an
options word, a bool, a zero - hands it to the gate as a pointer, and the gate dereferences it. So
the shims are disassembled back and their two ``push dword [esp+N]`` displacements asserted against
the argument layout the two gates actually have.

The second is the **build fingerprint**. The patch rewrites four bytes and reads five windows it
does not rewrite: the two loop bodies (which say the hooked call really is a group loop's
per-member gate), the two ``and eax, 0x100000`` sites (which say those loops are the multi-execute
ones) and the model-condition gate's prologue (which says the routine the cave calls is still the
one that reads the two masks). Every one of them has to fail loudly on anything else.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch import MultiExecuteGatePatch, apply_patches
from sage_patch.addresses import GET_FINAL_OVERRIDE, GUI_COMMAND_SPECIAL_POWER
from sage_patch.patches.multi_execute_gate import (
    COMMAND_BUTTON_SPECIAL_POWER_OFFSET,
    DISABLED,
    FIND_COMMAND_SET_VA,
    GATE_A_ARG_BYTES,
    GATE_A_CALL_VA,
    GATE_A_OBJECT_ESP,
    GATE_A_TEMPLATE_ESP,
    GATE_A_VA,
    GATE_A_WINDOW,
    GATE_B_ARG_BYTES,
    GATE_B_CALL_VA,
    GATE_B_OBJECT_ESP,
    GATE_B_TEMPLATE_ESP,
    GATE_B_VA,
    GATE_B_WINDOW,
    GET_COMMAND_BUTTON_VA,
    GET_COMMAND_SET_STRING_VA,
    MODEL_CONDITION_GATE_VA,
    MODEL_CONDITION_GATE_WINDOW,
    MULTI_EXECUTE_BIT,
    MULTI_EXECUTE_WINDOWS,
    SECTION_NAME,
    SPECIAL_POWER_ID_OFFSET,
    STOCK_SLOTS,
    THE_CONTROL_BAR_VA,
    build_gate,
)
from sage_patch.utils import find_section, va_to_offset

IMAGE_BASE = 0x400000

#: Every window the patch asserts or rewrites, as ``(VA, bytes)``.
PLANTED = (GATE_A_WINDOW, GATE_B_WINDOW, MODEL_CONDITION_GATE_WINDOW, *MULTI_EXECUTE_WINDOWS)


def _call_bytes(from_va: int, to_va: int) -> bytes:
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


def synthetic_image() -> bytearray:
    """A PE32 image mapping every site this patch asserts or repoints, holding exactly what the
    real ``2.01.2614.37001`` build holds there — so the whole apply + verify path runs in CI without
    the copyrighted `game.dat`, and a patch aimed at a wrong address fails here too."""
    highest = max(va + len(blob) for va, blob in PLANTED) - IMAGE_BASE + 0x100
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

    for va, blob in PLANTED:
        data[va - IMAGE_BASE : va - IMAGE_BASE + len(blob)] = blob
    return data


@pytest.fixture
def image() -> bytearray:
    return synthetic_image()


def _patched(image: bytearray, **kwargs: object) -> bytearray:
    data = bytearray(image)
    MultiExecuteGatePatch(**kwargs).apply(data)  # type: ignore[arg-type]
    return data


def _cave(data: bytes | bytearray) -> tuple[int, int]:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    section_va, section_off, _vsize = located
    return section_va, section_off


# --- round trip ------------------------------------------------------------------------------


def test_apply_then_verify(image: bytearray) -> None:
    data = _patched(image)
    assert MultiExecuteGatePatch().verify(data) == []


def test_verify_rejects_an_unpatched_image(image: bytearray) -> None:
    problems = MultiExecuteGatePatch().verify(image)
    assert problems and SECTION_NAME in problems[0]


def test_detect_recovers_the_patch(image: bytearray) -> None:
    data = _patched(image)
    found = MultiExecuteGatePatch.detect(data)
    assert found is not None
    assert MultiExecuteGatePatch.detect(image) is None


def test_verify_is_slot_specific(image: bytearray) -> None:
    """A cave built for a 64-slot walk must not verify as the stock 33-slot one: the bound decides
    whether a button past slot 33 is found at all."""
    data = _patched(image, slots=64)
    assert MultiExecuteGatePatch(slots=64).verify(data) == []
    assert MultiExecuteGatePatch(slots=STOCK_SLOTS).verify(data) != []


def test_apply_is_idempotent_only_once(image: bytearray) -> None:
    """A second application must fail rather than double-patch: the hooked calls no longer hold
    their original displacements and `apply_byte_patch` asserts them."""
    data = _patched(image)
    with pytest.raises(ValueError):
        MultiExecuteGatePatch().apply(data)


def test_slots_defaults_to_the_stock_limit(image: bytearray) -> None:
    """With no `commandset-limit` in the image there is nothing to read, so the walk is 33."""
    data = _patched(image)
    assert MultiExecuteGatePatch(slots=STOCK_SLOTS).verify(data) == []


@pytest.mark.parametrize("slots", [0, 128, -1])
def test_rejects_an_impossible_slot_bound(slots: int) -> None:
    with pytest.raises(ValueError):
        MultiExecuteGatePatch(slots=slots)


def test_apply_patches_writes_a_file(image: bytearray, tmp_path: object) -> None:
    src = tmp_path / "game.dat.backup"  # type: ignore[operator]
    out = tmp_path / "game.dat"  # type: ignore[operator]
    src.write_bytes(bytes(image))
    apply_patches(src, [MultiExecuteGatePatch()], output=out)
    assert MultiExecuteGatePatch().verify(out.read_bytes()) == []
    assert src.read_bytes() == bytes(image)  # the input is never modified


# --- the two hooks ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("call_va", "stock_va"),
    [(GATE_A_CALL_VA, GATE_A_VA), (GATE_B_CALL_VA, GATE_B_VA)],
)
def test_hook_retargets_the_gate_call_into_the_cave(
    image: bytearray, call_va: int, stock_va: int
) -> None:
    data = _patched(image)
    section_va, _section_off = _cave(data)
    off = va_to_offset(data, call_va)
    assert off is not None

    assert bytes(image[off : off + 5]) == _call_bytes(call_va, stock_va)
    target = call_va + 5 + struct.unpack_from("<i", data, off + 1)[0]
    _vsize = find_section(data, SECTION_NAME)
    assert _vsize is not None
    assert section_va <= target < section_va + _vsize[2]


def test_the_two_hooks_land_on_different_shims(image: bytearray) -> None:
    """One cave, two entry points: the gates they fall through to clean a different number of
    argument bytes, so a shared shim would corrupt the caller's stack on one of the two."""
    data = _patched(image)
    targets = []
    for call_va in (GATE_A_CALL_VA, GATE_B_CALL_VA):
        off = va_to_offset(data, call_va)
        assert off is not None
        targets.append(call_va + 5 + struct.unpack_from("<i", data, off + 1)[0])
    assert targets[0] != targets[1]


# --- the cave's code -------------------------------------------------------------------------


def _disassemble(data: bytes | bytearray, va: int, off: int, count: int) -> list[str]:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    out = []
    for insn in md.disasm(bytes(data[off : off + count * 8]), va):
        out.append(f"{insn.mnemonic} {insn.op_str}".strip())
        if len(out) >= count:
            break
    return out


def _shim(data: bytes | bytearray, call_va: int) -> tuple[int, int]:
    """``(VA, file offset)`` of the shim a hooked call now lands in."""
    off = va_to_offset(data, call_va)
    assert off is not None
    va = call_va + 5 + struct.unpack_from("<i", data, off + 1)[0]
    shim_off = va_to_offset(data, va)
    assert shim_off is not None
    return va, shim_off


@pytest.mark.parametrize(
    ("call_va", "stock_va", "arg_bytes", "object_esp", "template_esp"),
    [
        (GATE_A_CALL_VA, GATE_A_VA, GATE_A_ARG_BYTES, GATE_A_OBJECT_ESP, GATE_A_TEMPLATE_ESP),
        (GATE_B_CALL_VA, GATE_B_VA, GATE_B_ARG_BYTES, GATE_B_OBJECT_ESP, GATE_B_TEMPLATE_ESP),
    ],
    ids=["targetless", "targeted"],
)
def test_shim_borrows_the_right_two_arguments_and_falls_through(
    image: bytearray,
    call_va: int,
    stock_va: int,
    arg_bytes: int,
    object_esp: int,
    template_esp: int,
) -> None:
    """The shim's two ``push dword [esp+N]`` must name the template and then the object, allowing
    for the saved ``ecx`` and for the first push shifting the second. Then: refuse by cleaning
    exactly the arguments the stock gate would have, or tail-jump to it so its own ``ret`` returns
    to the loop."""
    data = _patched(image)
    section_va, _section_off = _cave(data)
    va, off = _shim(data, call_va)
    assert _disassemble(data, va, off, 10) == [
        "push ecx",
        f"push dword ptr [esp + 0x{template_esp + 4:x}]",
        f"push dword ptr [esp + 0x{object_esp + 8:x}]",
        f"call 0x{section_va:x}",
        "add esp, 8",
        "pop ecx",
        "test al, al",
        f"jne 0x{va + 0x1F:x}",
        "xor al, al",
        f"ret 0x{arg_bytes:x}",
    ]
    assert _disassemble(data, va + 0x1F, off + 0x1F, 1) == [f"jmp 0x{stock_va:x}"]


def test_gate_walks_the_command_set_and_asks_the_model_condition_gate(image: bytearray) -> None:
    """The gate, end to end: resolve the object's *effective* command set (so a command-set swap is
    honoured), look it up, walk its slots for a `SPECIAL_POWER` button naming the same power, and
    answer false only when that button's own model conditions disable it on that object."""
    data = _patched(image)
    section_va, section_off = _cave(data)
    text = _disassemble(data, section_va, section_off, 45)

    assert f"call 0x{GET_COMMAND_SET_STRING_VA:x}" in text
    assert f"mov ecx, dword ptr [0x{THE_CONTROL_BAR_VA:x}]" in text
    assert f"call 0x{FIND_COMMAND_SET_VA:x}" in text
    assert f"call 0x{GET_COMMAND_BUTTON_VA:x}" in text
    assert f"cmp dword ptr [edi + 0x14], 0x{GUI_COMMAND_SPECIAL_POWER:x}" in text
    assert f"mov ecx, dword ptr [edi + 0x{COMMAND_BUTTON_SPECIAL_POWER_OFFSET:x}]" in text
    assert f"call 0x{GET_FINAL_OVERRIDE:x}" in text
    assert f"mov eax, dword ptr [eax + 0x{SPECIAL_POWER_ID_OFFSET:x}]" in text
    assert f"cmp eax, dword ptr [ecx + 0x{SPECIAL_POWER_ID_OFFSET:x}]" in text
    assert f"call 0x{MODEL_CONDITION_GATE_VA:x}" in text
    assert f"cmp eax, {DISABLED}" in text

    # The default answer is "allow": every early exit reaches `mov al, 1`.
    assert "mov al, 1" in text

    # The match is on the id, not on the template pointer — the loop's template came from the
    # store by id, the button's may be an INI override copy of it.
    assert "cmp eax, ecx" not in text


@pytest.mark.parametrize("slots", [STOCK_SLOTS, 64, 127])
def test_gate_walk_bound_is_the_slot_count(slots: int) -> None:
    code = build_gate(0x00ED3000, slots)
    assert bytes((0x83, 0xFB, slots)) in code  # cmp ebx, <slots>


def test_gate_is_position_independent(image: bytearray) -> None:
    """Two caves at different addresses must differ only in their resolved displacements — the
    whole point of building the body from the base VA rather than from a fixed RVA."""
    assert build_gate(0x00ED3000) != build_gate(0x00EE4000)
    assert len(build_gate(0x00ED3000)) == len(build_gate(0x00EE4000))


# --- the build fingerprint --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("va", "blob"),
    list(PLANTED),
    ids=["gate-a-loop", "gate-b-loop", "model-condition-gate", "multi-bit-a", "multi-bit-b"],
)
def test_apply_refuses_a_build_whose_window_moved(image: bytearray, va: int, blob: bytes) -> None:
    """Each of the five is silent when wrong: a shim would hook a call that is not the per-member
    gate, or the cave would call a routine that no longer reads the two masks."""
    data = bytearray(image)
    off = va_to_offset(data, va)
    assert off is not None
    data[off + len(blob) - 1] ^= 0xFF
    with pytest.raises(ValueError, match="not the expected build"):
        MultiExecuteGatePatch().apply(data)


def test_verify_still_checks_the_windows_around_the_hooks(image: bytearray) -> None:
    """`verify` blanks the five bytes it rewrote and checks the rest of each loop window, so a file
    whose loop body drifted around an intact hook is not reported as verified."""
    data = _patched(image)
    off = va_to_offset(data, GATE_A_WINDOW[0])
    assert off is not None
    data[off] ^= 0xFF
    assert MultiExecuteGatePatch().verify(data) != []


def test_multi_execute_bit_is_the_documented_one() -> None:
    """`OK_FOR_MULTI_EXECUTE` is index 20 of the `CommandButton` `Options` name table, and both
    asserted windows really do mask that bit."""
    assert MULTI_EXECUTE_BIT == 0x100000
    for _va, blob in MULTI_EXECUTE_WINDOWS:
        assert struct.pack("<I", MULTI_EXECUTE_BIT) in blob
