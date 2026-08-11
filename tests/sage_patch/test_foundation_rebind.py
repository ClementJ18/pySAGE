"""Tests for `foundation-rebind`, which hands a settlement plot from the object
`ReplaceSelfUpgrade` destroys to the one it creates.

Three things can go wrong here and none of them raises on its own, so all three are checked
statically.

The first is the **frame arithmetic**. Hook 2 reads two locals out of
`ReplaceSelfUpgrade::upgradeImplementation`'s own frame - the dying object's id and the
replacement - and a displacement that is a few bytes out reads a neighbouring local (a float, a
loop counter, a string) and writes it into a plot's occupant field. So both displacements are
re-derived from the stock instructions that *fill* those slots, which the patch carries as
fingerprint windows.

The second is the **field offsets**. The cave is disassembled back and every structure access it
makes is asserted against the offsets the engine's own code uses at the sites this patch pre-empts.

The third is the **build fingerprint**. The patch rewrites four bytes and reads ten windows it does
not rewrite; every one of them has to fail loudly on anything else.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch import FoundationRebindPatch, apply_patches
from sage_patch.patches.foundation_rebind import (
    ANCHORS,
    DESTROY_OBJECT,
    FIND_OBJECT_BY_ID,
    FOUNDATION_BUILT_ON_OFFSET,
    FRAME_NEW_OBJECT,
    FRAME_OLD_ID,
    GET_FIRST_OBJECT,
    GET_FOUNDATION_INTERFACE,
    HOOK_DESTROY_CALL_VA,
    HOOK_WALK_CALL_VA,
    OBJECT_BUILT_BACK_LINK_OFFSET,
    OBJECT_ID_OFFSET,
    OBJECT_PRODUCER_ID_OFFSET,
    RING_SIZE,
    RING_SLOTS,
    SECTION_NAME,
    build_section,
)
from sage_patch.utils import find_section, va_to_offset

from .synthetic import _sparse_image


def _call_bytes(from_va: int, to_va: int) -> bytes:
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


@pytest.fixture
def image() -> bytearray:
    """A stand-in mapping only the pages this patch reads or rewrites.

    Its sites span most of half a megabyte of `.text`, so a sparse image is a few KB where a flat
    one would be that whole span. Everything not planted reads as zero, which is what makes the
    image useful negatively too: a hook aimed one instruction to either side finds nothing there."""
    return _sparse_image(dict(ANCHORS))


def _patched(image: bytearray) -> bytearray:
    data = bytearray(image)
    FoundationRebindPatch().apply(data)
    return data


def _cave(data: bytes | bytearray) -> tuple[int, int, int]:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    return located


def _hook_target(data: bytes | bytearray, call_va: int) -> int:
    off = va_to_offset(data, call_va)
    assert off is not None
    return call_va + 5 + struct.unpack_from("<i", data, off + 1)[0]


# --- round trip ---------------------------------------------------------------------------------


def test_apply_then_verify(image: bytearray) -> None:
    assert FoundationRebindPatch().verify(_patched(image)) == []


def test_verify_rejects_an_unpatched_image(image: bytearray) -> None:
    problems = FoundationRebindPatch().verify(image)
    assert problems and SECTION_NAME in problems[0]


def test_detect_recovers_the_patch(image: bytearray) -> None:
    assert FoundationRebindPatch.detect(_patched(image)) is not None
    assert FoundationRebindPatch.detect(image) is None


def test_apply_is_idempotent_only_once(image: bytearray) -> None:
    """A second application must fail rather than double-patch: the hooked calls no longer hold
    their original displacements and `apply_byte_patch` asserts them."""
    data = _patched(image)
    with pytest.raises(ValueError):
        FoundationRebindPatch().apply(data)


def test_apply_patches_writes_a_file(image: bytearray, tmp_path) -> None:
    src, out = tmp_path / "game.dat.backup", tmp_path / "game.dat"
    src.write_bytes(bytes(image))
    apply_patches(src, [FoundationRebindPatch()], output=out)
    assert FoundationRebindPatch().verify(out.read_bytes()) == []
    assert src.read_bytes() == bytes(image)  # the input is never modified


def test_the_patch_is_attributed() -> None:
    assert FoundationRebindPatch.author


# --- the two hooks ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("call_va", "stock_va"),
    [(HOOK_DESTROY_CALL_VA, DESTROY_OBJECT), (HOOK_WALK_CALL_VA, GET_FIRST_OBJECT)],
)
def test_hook_retargets_a_stock_call_into_the_cave(
    image: bytearray, call_va: int, stock_va: int
) -> None:
    data = _patched(image)
    section_va, _off, vsize = _cave(data)
    off = va_to_offset(data, call_va)
    assert off is not None
    assert bytes(image[off : off + 5]) == _call_bytes(call_va, stock_va)
    assert section_va <= _hook_target(data, call_va) < section_va + vsize


def test_the_two_hooks_land_on_different_thunks(image: bytearray) -> None:
    """One cave, two entry points: they tail-jump to different engine functions with different
    stack contracts, so a shared thunk would return to the wrong place from one of the two."""
    data = _patched(image)
    a = _hook_target(data, HOOK_DESTROY_CALL_VA)
    b = _hook_target(data, HOOK_WALK_CALL_VA)
    assert a != b


def test_nothing_outside_the_two_calls_and_the_cave_is_rewritten(image: bytearray) -> None:
    """The patch's whole footprint in existing code is **eight bytes** of displacement.

    Everything else it changes is the PE header block (one more section, a larger image) and the
    bytes it appends, so the comparison runs over the original file past its headers."""
    data = _patched(image)
    headers = 0x400  # SizeOfHeaders in the stand-in; the section table lives inside it
    changed = {i for i in range(headers, len(image)) if data[i] != image[i]}
    allowed: set[int] = set()
    for call_va in (HOOK_DESTROY_CALL_VA, HOOK_WALK_CALL_VA):
        off = va_to_offset(data, call_va)
        assert off is not None
        allowed |= set(range(off + 1, off + 5))  # the displacement; the 0xE8 stays put
    # A subset rather than an equality: a displacement byte that happens to be the same in both
    # targets does not show up as changed, and both hooks are checked for target elsewhere.
    assert changed <= allowed


# --- the ring -----------------------------------------------------------------------------------


def test_the_ring_leads_the_cave_and_starts_empty(image: bytearray) -> None:
    """Both thunks address the ring by its resolved base, and an entry whose key is zero is the
    free slot - so a cave that shipped with anything else in it would hand out a stale plot."""
    data = _patched(image)
    _va, off, vsize = _cave(data)
    assert vsize > RING_SIZE
    assert bytes(data[off : off + RING_SIZE]) == bytes(RING_SIZE)


def test_both_thunks_address_the_same_ring(image: bytearray) -> None:
    data = _patched(image)
    section_va, off, vsize = _cave(data)
    code = bytes(data[off + RING_SIZE : off + vsize])
    # `mov esi, <ring>` is the only absolute reference either thunk makes to the section, and both
    # scan loops emit it; hook 1 emits it twice (the free slot, and the wrap when the ring is full).
    assert code.count(b"\xbe" + struct.pack("<I", section_va)) == 3


def test_a_full_ring_wraps_rather_than_walking_off_the_end(image: bytearray) -> None:
    """The scan is a fixed `RING_SLOTS` iterations and then a reload of the base, never a write
    past the last slot."""
    data = _patched(image)
    section_va, off, vsize = _cave(data)
    code = bytes(data[off + RING_SIZE : off + vsize])
    assert code.count(b"\xb9" + struct.pack("<I", RING_SLOTS)) == 2  # one bound per thunk


# --- what the cave actually reads and writes ------------------------------------------------------


def _disassembled(data: bytes | bytearray) -> list:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    section_va, off, vsize = _cave(data)
    code = bytes(data[off + RING_SIZE : off + vsize])
    return list(md.disasm(code, section_va + RING_SIZE))


def test_the_cave_leaves_only_by_the_engine_routines_it_names(image: bytearray) -> None:
    """Both thunks end by **jumping** to the function whose `call` they replaced, so the stock
    return value and the stock `ret` size are still the caller's, and the only other way out is a
    `call` to one of the two lookups. Anything else leaving the cave is a resolved branch gone
    wrong, which assembles and applies perfectly and jumps into the middle of an instruction."""
    data = _patched(image)
    section_va, _off, vsize = _cave(data)
    external = [
        (i.mnemonic, int(i.op_str, 16))
        for i in _disassembled(data)
        if i.op_str.startswith("0x") and not section_va <= int(i.op_str, 16) < section_va + vsize
    ]
    assert [target for kind, target in external if kind == "jmp"] == [
        DESTROY_OBJECT,
        GET_FIRST_OBJECT,
    ]
    assert {target for kind, target in external if kind == "call"} == {
        FIND_OBJECT_BY_ID,
        GET_FOUNDATION_INTERFACE,
    }
    assert {kind for kind, _target in external} == {"jmp", "call"}


def test_hook_two_reads_the_frame_slots_the_stock_code_fills(image: bytearray) -> None:
    """The two displacements are the ones `upgradeImplementation` itself writes.

    Derived from the fingerprint windows rather than restated, because a test that repeated the
    constant would only ever agree with the patch."""
    old_id_store = ANCHORS[0x008BB955].index(b"\x89\x45")  # mov [ebp-0x3c], eax
    assert ANCHORS[0x008BB955][old_id_store + 2] == FRAME_OLD_ID & 0xFF
    new_object_store = ANCHORS[0x008BB8D9].index(b"\x89\x7d")  # mov [ebp-0x20], edi
    assert ANCHORS[0x008BB8D9][new_object_store + 2] == FRAME_NEW_OBJECT & 0xFF

    reads = {
        i.op_str.split("[ebp - ")[1].rstrip("]")
        for i in _disassembled(_patched(image))
        if "[ebp - " in i.op_str
    }
    assert reads == {hex(-FRAME_OLD_ID), hex(-FRAME_NEW_OBJECT)}


def test_the_cave_touches_only_the_four_object_fields_it_documents(image: bytearray) -> None:
    """Every structure access, by offset: the occupant field on the plot's foundation interface,
    and the id, producer and back-link fields on an `Object`. A stray offset here is a write into
    an unrelated member of a live object, which nothing else in the suite would catch."""
    displacements = set()
    for i in _disassembled(_patched(image)):
        for register in ("eax", "ebx", "ecx", "esi", "esp"):
            marker = f"[{register} + "
            if marker in i.op_str:
                displacements.add(int(i.op_str.split(marker)[1].split("]")[0], 16))
    assert displacements == {
        FOUNDATION_BUILT_ON_OFFSET,
        OBJECT_ID_OFFSET,
        OBJECT_PRODUCER_ID_OFFSET,
        OBJECT_BUILT_BACK_LINK_OFFSET,
        4,  # the ring slot's second dword, the plot id
        0x10,  # hook 1's `[esp+0x10]`, the argument destroyObject is about to be given
    }


def test_hook_one_cuts_the_link_get_built_behavior_would_follow(image: bytearray) -> None:
    """`GettingBuiltBehavior::onDelete` frees the plot named by `Object+0x78`; zeroing it is the
    whole of why the flag never transitions. The instruction is asserted by encoding because it is
    the one write the patch makes to the object being destroyed."""
    data = _patched(image)
    _va, off, vsize = _cave(data)
    code = bytes(data[off + RING_SIZE : off + vsize])
    assert code.count(bytes([0x83, 0x63, OBJECT_PRODUCER_ID_OFFSET, 0x00])) == 1

    # and the field it reads to get there is the same one `onDelete` pushes
    on_delete = ANCHORS[0x0085757F]
    assert bytes([0xFF, 0x70, OBJECT_PRODUCER_ID_OFFSET]) in on_delete  # push [eax+0x78]


def test_the_occupant_offset_is_the_one_is_occupied_reads(image: bytearray) -> None:
    """`isOccupied` is `return [iface+8] != 0`. If that offset were wrong the patch would write
    into the module's `Object*` instead, one field earlier."""
    assert ANCHORS[0x0097031D][:5] == bytes([0x33, 0xC0, 0x39, 0x41, FOUNDATION_BUILT_ON_OFFSET])


# --- the build fingerprint ------------------------------------------------------------------------


@pytest.mark.parametrize("va", sorted(ANCHORS))
def test_a_disturbed_anchor_refuses_to_apply(image: bytearray, va: int) -> None:
    data = bytearray(image)
    off = va_to_offset(data, va)
    assert off is not None
    data[off] ^= 0xFF
    with pytest.raises(ValueError, match="not the expected build"):
        FoundationRebindPatch().apply(data)


@pytest.mark.parametrize("va", sorted(ANCHORS))
def test_a_disturbed_anchor_fails_verification(image: bytearray, va: int) -> None:
    data = _patched(image)
    off = va_to_offset(data, va)
    assert off is not None
    data[off] ^= 0xFF
    assert FoundationRebindPatch().verify(data) != []


def test_verify_survives_the_hooked_calls_it_rewrote(image: bytearray) -> None:
    """Both anchor windows contain a `call` the patch repoints, so verification has to blank those
    five bytes - otherwise a correctly patched image reports its own edit as corruption."""
    data = _patched(image)
    assert FoundationRebindPatch().verify(data) == []
    for call_va in (HOOK_DESTROY_CALL_VA, HOOK_WALK_CALL_VA):
        off = va_to_offset(data, call_va)
        assert off is not None
        assert bytes(data[off : off + 5]) != _call_bytes(call_va, DESTROY_OBJECT)


def test_a_moved_cave_fails_verification(image: bytearray) -> None:
    """The thunks address the ring and the engine absolutely, so a cave whose bytes were built for
    another base address must not pass - the ring pointer would name whatever is at the old VA."""
    data = _patched(image)
    section_va, off, vsize = _cave(data)
    content, _stash, _rebind = build_section(section_va + 0x1000)
    data[off : off + len(content)] = content
    problems = FoundationRebindPatch().verify(data)
    assert problems and SECTION_NAME in problems[0]
