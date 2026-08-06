"""Tests for the `SpawnBehavior` union patch.

The cave is hand-assembled x86 that cannot be executed here, and every way it can be wrong is
silent: a stub that pops the wrong number of argument dwords corrupts its caller's stack rather
than raising, a forwarding push with the wrong displacement passes whatever happens to sit there,
and a vtable slot pointing one stub off calls a three-argument method with none. So the stubs are
disassembled back and asserted to say what they were meant to say, with the argument arithmetic
checked explicitly against each slot's stack size.

The other half is the build fingerprint. The patch replaces a function and mirrors an interface it
does not rewrite - the getter's own body, `SpawnBehavior`'s second-vtable answer, the sixteen-slot
interface vtable, and the distance helper the merged `getClosestSlave` calls - and all four have to
fail loudly on anything that is not the expected build.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch import SpawnUnionPatch, apply_patches
from sage_patch.patches.spawn_union import (
    ANY,
    BROADCAST,
    CLOSEST,
    DISTANCE_SQUARED_2D,
    GETTER_VA,
    IFACE_SLOTS,
    IFACE_VTABLE_VA,
    MODULE_LIST,
    RING_SIZE,
    SECTION_NAME,
    SPAWN_ANSWER_THUNK,
    SPAWN_IFACE_SLOT,
    SPAWN_SECOND_VTABLE_VA,
    STOCK_DISTANCE_HELPER,
    STOCK_GETTER,
    STOCK_IFACE_VTABLE,
    UNREACHABLE,
    build_section,
)
from sage_patch.utils import find_section, va_to_offset

from .synthetic import _pe32

IMAGE_BASE = 0x400000


def synthetic_image() -> bytearray:
    """A stand-in for `game.dat` mapping only the pages this patch reads or writes.

    Its four sites are ~6 MB apart in an 11 MB executable, so rather than allocate that it maps
    three pages as three small sections, which `va_to_offset` handles exactly as it handles the
    real thing. Every one holds what the real ``2.01.2614.37001`` build holds there, so a patch
    aimed at a wrong address fails here too."""
    pages: dict[int, bytearray] = {}

    def write(va: int, blob: bytes) -> None:
        base = va & ~0xFFF
        page = pages.setdefault(base, bytearray(0x1000))
        start = va & 0xFFF
        assert start + len(blob) <= 0x1000, f"0x{va:08x} straddles a page in the stand-in"
        page[start : start + len(blob)] = blob

    write(GETTER_VA, STOCK_GETTER)
    write(DISTANCE_SQUARED_2D, STOCK_DISTANCE_HELPER)
    write(SPAWN_SECOND_VTABLE_VA + SPAWN_IFACE_SLOT, struct.pack("<I", SPAWN_ANSWER_THUNK))
    write(IFACE_VTABLE_VA, b"".join(struct.pack("<I", va) for va in STOCK_IFACE_VTABLE))

    sections = [
        (f".s{index}", base - IMAGE_BASE, bytes(pages[base]))
        for index, base in enumerate(sorted(pages))
    ]
    return _pe32(sections, max(pages) - IMAGE_BASE + 0x1000)


@pytest.fixture
def image() -> bytearray:
    return synthetic_image()


def _patched(image: bytearray) -> bytearray:
    data = bytearray(image)
    SpawnUnionPatch().apply(data)
    return data


def _cave(data: bytes | bytearray) -> tuple[int, int]:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    section_va, section_off, _vsize = located
    return section_va, section_off


# Round trip


def test_apply_then_verify(image: bytearray) -> None:
    assert SpawnUnionPatch().verify(_patched(image)) == []


def test_verify_rejects_an_unpatched_image(image: bytearray) -> None:
    problems = SpawnUnionPatch().verify(image)
    assert problems and SECTION_NAME in problems[0]


def test_detect(image: bytearray) -> None:
    assert SpawnUnionPatch.detect(image) is None
    assert SpawnUnionPatch.detect(_patched(image)) is not None


def test_apply_is_idempotent_only_once(image: bytearray) -> None:
    """A second application must fail rather than double-patch: the getter no longer holds its
    stock head, and `_check_getter` asserts that before anything is written."""
    data = _patched(image)
    with pytest.raises(ValueError, match="getSpawnBehaviorInterface"):
        SpawnUnionPatch().apply(data)


def test_apply_patches_round_trip(tmp_path, image: bytearray) -> None:
    src = tmp_path / "game.dat"
    src.write_bytes(bytes(image))
    out = tmp_path / "patched.dat"
    patch = SpawnUnionPatch()
    apply_patches(src, [patch], output=out)

    assert src.read_bytes() == bytes(image)  # the input is never modified
    assert patch.verify(out.read_bytes()) == []


def test_only_the_getter_head_is_rewritten(image: bytearray) -> None:
    """One edit, five bytes. The getter's remaining 27 go dead: nothing branches into the middle
    of it and all thirteen call sites name its first byte."""
    data = _patched(image)
    section_va, _off = _cave(data)
    labels = build_section(section_va)[1]

    off = va_to_offset(data, GETTER_VA)
    assert off is not None
    expected = b"\xe9" + struct.pack("<i", labels["entry"] - (GETTER_VA + 5))
    assert bytes(data[off : off + 5]) == expected
    assert bytes(data[off + 5 : off + len(STOCK_GETTER)]) == STOCK_GETTER[5:]


# The build fingerprint


def test_a_reshaped_getter_is_rejected(image: bytearray) -> None:
    """The module-list offset, the second-vtable hop and the interface slot are all immediates in
    the body the cave reproduces, so one wrong byte anywhere in it means the wrong build."""
    off = va_to_offset(image, GETTER_VA)
    assert off is not None
    image[off + 2 : off + 6] = b"\xb1\x50\x02\x00"  # a different module-list offset
    with pytest.raises(ValueError, match="not the expected build"):
        SpawnUnionPatch().apply(image)


def test_a_different_interface_answer_is_rejected(image: bytearray) -> None:
    """The thunk says *which* subobject the getter hands back, which is what makes the vtable
    below the right one to mirror."""
    off = va_to_offset(image, SPAWN_SECOND_VTABLE_VA + SPAWN_IFACE_SLOT)
    assert off is not None
    struct.pack_into("<I", image, off, 0x00851E97)  # the generic "no interface" stub
    with pytest.raises(ValueError, match="interface slot"):
        SpawnUnionPatch().apply(image)


def test_a_reordered_interface_is_rejected(image: bytearray) -> None:
    """A build that kept the getter but moved a method would be patched into calling the wrong
    one with the wrong argument count, and nothing downstream would notice."""
    off = va_to_offset(image, IFACE_VTABLE_VA)
    assert off is not None
    struct.pack_into("<I", image, off + 0x0C, STOCK_IFACE_VTABLE[4])  # slots +0x0c and +0x10 swap
    with pytest.raises(ValueError, match=r"slot \+0x0c"):
        SpawnUnionPatch().apply(image)


def test_a_reshaped_distance_helper_is_rejected(image: bytearray) -> None:
    off = va_to_offset(image, DISTANCE_SQUARED_2D)
    assert off is not None
    image[off : off + 4] = b"\x8b\x44\x24\x08"  # mov eax, [esp+8]
    with pytest.raises(ValueError, match="distance helper"):
        SpawnUnionPatch().apply(image)


# The cave's code


def _disassemble(content: bytes, base_va: int, va: int, end_va: int) -> list[str]:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    body = content[va - base_va : end_va - base_va]
    return [f"{insn.mnemonic} {insn.op_str}".strip() for insn in md.disasm(body, va)]


def _stub(base_va: int, content: bytes, labels: dict[str, int], slot: int) -> list[str]:
    """The one stub, bounded by whatever label comes next, less any alignment padding."""
    va = labels[f"slot_{slot:02x}"]
    later = [v for v in labels.values() if v > va]
    text = _disassemble(content, base_va, va, min(later))
    while text and text[-1] == "nop":
        text.pop()
    return text


CAVE_BASE = 0x01000000


def _imm(value: int) -> str:
    """How capstone renders an immediate: decimal below ten, hex at or above it."""
    return str(value) if value < 10 else f"0x{value:x}"


def _call_slot(slot: int) -> str:
    """How capstone renders ``call [edx+slot]``, which drops a zero displacement."""
    return "call dword ptr [edx]" if slot == 0 else f"call dword ptr [edx + {_imm(slot)}]"


def _ret(nargs: int) -> str:
    return f"ret {_imm(4 * nargs)}" if nargs else "ret"


@pytest.fixture
def cave() -> tuple[bytes, dict[str, int]]:
    return build_section(CAVE_BASE)


def test_the_ring_comes_first_and_starts_empty(cave) -> None:
    """The entry stub addresses the ring as link-time constants, so it has to be laid out first."""
    content, labels = cave
    assert labels["ring_index"] == CAVE_BASE
    assert labels["ring"] == CAVE_BASE + 4
    assert content[: 4 + 8 * RING_SIZE] == bytes(4 + 8 * RING_SIZE)


def test_the_vtable_names_a_stub_per_slot(cave) -> None:
    content, labels = cave
    table = labels["vtable"] - CAVE_BASE
    assert table % 4 == 0
    for index, (slot, _nargs, mode, _note) in enumerate(IFACE_SLOTS):
        assert slot == index * 4
        got = struct.unpack_from("<I", content, table + slot)[0]
        expected = labels["dead"] if mode == UNREACHABLE else labels[f"slot_{slot:02x}"]
        assert got == expected, f"slot +0x{slot:02x}"


def test_the_unreachable_slots_are_an_int3(cave) -> None:
    """They are reached through the module, never through this getter. If that is ever wrong it
    has to stop at the instruction that was wrong, not return a plausible value."""
    content, labels = cave
    assert content[labels["dead"] - CAVE_BASE] == 0xCC
    assert sum(1 for _s, _n, mode, _t in IFACE_SLOTS if mode == UNREACHABLE) == 3


def test_entry_is_stock_for_none_and_for_one(cave) -> None:
    """The common path has to stay the stock answer: the first interface found, or NULL, with the
    proxy reached only once a *second* one turns up."""
    content, labels = cave
    text = _disassemble(content, CAVE_BASE, labels["entry"], CAVE_BASE + len(content))
    assert text[:6] == [
        "push ebx",
        "push esi",
        "push edi",
        "mov ebx, ecx",
        f"mov esi, dword ptr [ebx + 0x{MODULE_LIST:x}]",
        "xor edi, edi",
    ]
    assert text[6:14] == [
        "mov eax, dword ptr [esi]",
        "test eax, eax",
        text[8],
        "lea ecx, [eax + 0xc]",
        "mov eax, dword ptr [ecx]",
        f"call dword ptr [eax + 0x{SPAWN_IFACE_SLOT:x}]",
        "test eax, eax",
        text[13],
    ]
    # The walk leaves for the proxy on the second answer, and returns edi otherwise.
    assert text[14:17] == ["test edi, edi", f"jne 0x{labels['entry_proxy']:x}", "mov edi, eax"]
    assert "mov eax, edi" in text
    assert text[text.index("mov eax, edi") + 1 : text.index("mov eax, edi") + 5] == [
        "pop edi",
        "pop esi",
        "pop ebx",
        "ret",
    ]


def test_the_proxy_is_taken_from_the_ring(cave) -> None:
    """A nested call has to get its own proxy: ordering slaves runs slave AI that comes back
    through the getter, and a single static one would be clobbered mid-call."""
    content, labels = cave
    text = _disassemble(content, CAVE_BASE, labels["entry_proxy"], CAVE_BASE + len(content))
    assert text[:8] == [
        f"mov eax, dword ptr [0x{labels['ring_index']:x}]",
        "inc eax",
        f"and eax, {RING_SIZE - 1}",
        f"mov dword ptr [0x{labels['ring_index']:x}], eax",
        "shl eax, 3",
        f"add eax, 0x{labels['ring']:x}",
        f"mov dword ptr [eax], 0x{labels['vtable']:x}",
        "mov dword ptr [eax + 4], ebx",
    ]


@pytest.mark.parametrize(
    ("slot", "nargs"), [(slot, n) for slot, n, mode, _t in IFACE_SLOTS if mode == BROADCAST]
)
def test_broadcast_stubs_forward_every_argument_and_clean_up(cave, slot: int, nargs: int) -> None:
    """The forwarding pushes all use one displacement, which is only correct because the reverse
    order makes each argument's index plus its push count constant. Getting it wrong forwards
    whatever sits next to the arguments, and only this arithmetic would catch it."""
    content, labels = cave
    text = _stub(CAVE_BASE, content, labels, slot)
    assert text[:4] == [
        "push esi",
        "push edi",
        "mov esi, dword ptr [ecx + 4]",
        f"mov esi, dword ptr [esi + 0x{MODULE_LIST:x}]",
    ]
    if nargs:
        displacement = 0x0C + 4 * (nargs - 1)
        assert text.count(f"push dword ptr [esp + 0x{displacement:x}]") == nargs
    else:
        assert not any(line.startswith("push dword ptr [esp") for line in text)
    assert _call_slot(slot) in text
    assert text[-3:] == ["pop edi", "pop esi", _ret(nargs)]


@pytest.mark.parametrize(
    ("slot", "nargs"), [(slot, n) for slot, n, mode, _t in IFACE_SLOTS if mode == ANY]
)
def test_any_stubs_ask_every_behavior_and_set_the_whole_register(cave, slot, nargs) -> None:
    """No short-circuit - every behavior is asked - and the result is a full `eax`, because the
    stock implementations disagree about whether they write `al` or `eax` and `0x006C8A1D`
    compares the whole register."""
    content, labels = cave
    text = _stub(CAVE_BASE, content, labels, slot)
    assert "xor edi, edi" in text[:6]
    assert _call_slot(slot) in text
    assert "test al, al" in text
    assert "mov edi, 1" in text
    assert text[-4:] == ["mov eax, edi", "pop edi", "pop esi", _ret(nargs)]
    # the loop continues past a TRUE rather than returning from inside it
    assert text.index("mov edi, 1") < text.index("add esi, 4")


def test_the_closest_stub_re_runs_the_distance_comparison(cave) -> None:
    """Taking the first behavior's answer would be the original bug with extra steps, so the
    merged form calls the same helper the stock loop calls and compares the same way - `comiss`
    and `jbe`, so an unordered result keeps the incumbent."""
    slot = next(slot for slot, _n, mode, _t in IFACE_SLOTS if mode == CLOSEST)
    content, labels = cave
    text = _stub(CAVE_BASE, content, labels, slot)

    assert text[:5] == ["push ebx", "push esi", "push edi", "push 0", "push 0"]
    # three saved registers plus two locals put the Coord3D * at [esp+0x18]
    assert text.count("push dword ptr [esp + 0x18]") == 2
    assert _call_slot(slot) in text
    assert f"call 0x{DISTANCE_SQUARED_2D:x}" in text
    assert "fstp dword ptr [esp]" in text
    assert text[text.index("fstp dword ptr [esp]") + 1] == "test edi, edi"
    assert "movss xmm1, dword ptr [esp + 4]" in text
    assert text[text.index("movss xmm1, dword ptr [esp + 4]") + 1] == "comiss xmm1, dword ptr [esp]"
    assert text[-6:] == [
        "mov eax, edi",
        "add esp, 8",
        "pop edi",
        "pop esi",
        "pop ebx",
        "ret 4",
    ]


def test_every_stub_reads_the_object_out_of_the_proxy(cave) -> None:
    """`this` is the proxy, not a module: every stub has to hop through `[this+4]` to the object
    before it can walk anything."""
    content, labels = cave
    for slot, _nargs, mode, _note in IFACE_SLOTS:
        if mode == UNREACHABLE:
            continue
        text = _stub(CAVE_BASE, content, labels, slot)
        assert "mov esi, dword ptr [ecx + 4]" in text[:6], f"slot +0x{slot:02x}"
        assert f"mov esi, dword ptr [esi + 0x{MODULE_LIST:x}]" in text[:7], f"slot +0x{slot:02x}"


# Composition


def test_cave_lands_past_every_existing_section(image: bytearray) -> None:
    """Allocating past the highest section is what lets section-adding patches compose in any
    order, so assert the section table stays sorted by RVA."""
    data = _patched(image)
    e = struct.unpack_from("<I", data, 0x3C)[0]
    count = struct.unpack_from("<H", data, e + 6)[0]
    szopt = struct.unpack_from("<H", data, e + 20)[0]
    sectab = e + 24 + szopt
    rvas = [struct.unpack_from("<I", data, sectab + i * 40 + 12)[0] for i in range(count)]
    assert rvas == sorted(rvas)


def test_the_cave_is_writable(image: bytearray) -> None:
    """The ring is written at runtime."""
    data = _patched(image)
    e = struct.unpack_from("<I", data, 0x3C)[0]
    count = struct.unpack_from("<H", data, e + 6)[0]
    szopt = struct.unpack_from("<H", data, e + 20)[0]
    sectab = e + 24 + szopt
    flags = struct.unpack_from("<I", data, sectab + (count - 1) * 40 + 36)[0]
    assert flags & 0x80000000


def test_a_written_ring_still_verifies(image: bytearray) -> None:
    """A dump taken from a running process has a non-zero ring, which is not a failed patch."""
    data = _patched(image)
    section_va, section_off = _cave(data)
    labels = build_section(section_va)[1]
    at = section_off + (labels["ring"] - section_va)
    struct.pack_into("<II", data, at, 0xDEADBEEF, 0x0BADF00D)
    struct.pack_into("<I", data, section_off, 3)  # the ring index
    assert SpawnUnionPatch().verify(data) == []
