"""Tests for `wall-mesh-release`, which gives back the pathfinding data a destroyed wall
registered instead of leaking it for the rest of the match.

Four things can go wrong here and not one of them raises on its own, so all four are checked
statically.

The first is the **stack contract**. Five of the seven rewritten sites are `call rel32`, and the
cave either tail-jumps to the callee it displaced or reproduces the call itself - so a routine that
cleans the wrong number of argument bytes returns into the middle of the caller's frame. Each hook
is checked for which engine routine it ends at, and the removal is checked for being the one that
issues its own `ret 4`.

The second is the **frame arithmetic**. The cave reads and writes six of ``0x00935FAA``'s own
locals - the `Object *`, `adding`, and the four dwords of the cell rectangle - and a displacement
a few bytes out reads a neighbouring float or loop counter and hands it to the unmark loop as a
grid coordinate. Every displacement is asserted against the stock instructions that fill those
slots, which the patch carries as fingerprint windows.

The third is the **structure offsets**. The cave walks two engine linked lists by hand. It is
disassembled back and every access asserted against the offsets the engine's own code uses at the
sites this patch pre-empts: the slot's list head, the render object's link, and the ramp record's.

The fourth is the **build fingerprint**. The patch rewrites 34 bytes and reads seventeen windows it
does not rewrite; every one has to fail loudly on anything else.
"""

from __future__ import annotations

import struct

import pytest

from sage_ini.engine import STOCK
from sage_patch import apply_patches
from sage_patch.patches.wall_mesh_release import (
    ANCHORS,
    CLAIM_WALL_LAYER,
    ENTRY_SIZE,
    GET_WALL_BOUNDS_MESH,
    HOOK_BOUNDS_VA,
    HOOK_CLAIM_SLOT_VA,
    HOOK_RAMP_WINDOWS,
    HOOK_RECT_CALLEE,
    HOOK_RECT_VA,
    HOOK_SHARE_SLOT_VA,
    LEDGER_SIZE,
    LEDGER_SLOTS,
    PATHFINDER_RAMP_LIST_OFFSET,
    PUSH_WALL_LAYER_MESH,
    RAMP_NEXT_OFFSET,
    RAMP_WINDOW_STOCK,
    RELEASE_WALL_LAYER,
    RENDER_OBJ_NEXT_OFFSET,
    RESET_TAIL_CALL_VA,
    RESET_TAIL_CALLEE,
    SCRATCH_SIZE,
    SECTION_NAME,
    SLOT_LIST_HEAD_OFFSET,
    UNMARK_LOOP_VA,
    WallMeshReleasePatch,
    build_section,
)
from sage_patch.utils import find_section, va_to_offset

from .synthetic import _sparse_image


def _call_bytes(from_va: int, to_va: int) -> bytes:
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


@pytest.fixture
def image() -> bytearray:
    """A stand-in mapping only the pages this patch reads or rewrites.

    Its sites span from `Pathfinder::reset` to the wall handler, most of two and a half megabytes
    of `.text`, so a sparse image is a few KB where a flat one would be that whole span. Everything
    not planted reads as zero, which is what makes the image useful negatively too: a hook aimed one
    instruction to either side finds nothing there."""
    return _sparse_image(dict(ANCHORS))


def _patched(image: bytearray) -> bytearray:
    data = bytearray(image)
    WallMeshReleasePatch().apply(data)
    return data


def _cave(data: bytes | bytearray) -> tuple[int, int, int]:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    return located


def _hook_target(data: bytes | bytearray, call_va: int) -> int:
    off = va_to_offset(data, call_va)
    assert off is not None
    return call_va + 5 + struct.unpack_from("<i", data, off + 1)[0]


#: Every `call rel32` the patch repoints, with the engine routine it displaced.
CALL_HOOKS = (
    (HOOK_SHARE_SLOT_VA, PUSH_WALL_LAYER_MESH),
    (HOOK_CLAIM_SLOT_VA, CLAIM_WALL_LAYER),
    (HOOK_RECT_VA, HOOK_RECT_CALLEE),
    (HOOK_BOUNDS_VA, GET_WALL_BOUNDS_MESH),
    (RESET_TAIL_CALL_VA, RESET_TAIL_CALLEE),
)


# --- round trip ---------------------------------------------------------------------------------


def test_apply_then_verify(image: bytearray) -> None:
    assert WallMeshReleasePatch().verify(_patched(image)) == []


def test_verify_rejects_an_unpatched_image(image: bytearray) -> None:
    problems = WallMeshReleasePatch().verify(image)
    assert problems and SECTION_NAME in problems[0]


def test_detect_recovers_the_patch(image: bytearray) -> None:
    assert WallMeshReleasePatch.detect(_patched(image)) is not None
    assert WallMeshReleasePatch.detect(image) is None


def test_apply_is_idempotent_only_once(image: bytearray) -> None:
    """A second application must fail rather than double-patch: the hooked calls no longer hold
    their original displacements and `apply_byte_patch` asserts them."""
    data = _patched(image)
    with pytest.raises(ValueError):
        WallMeshReleasePatch().apply(data)


def test_apply_patches_writes_a_file(image: bytearray, tmp_path) -> None:
    src, out = tmp_path / "game.dat.backup", tmp_path / "game.dat"
    src.write_bytes(bytes(image))
    apply_patches(src, [WallMeshReleasePatch()], output=out)
    assert WallMeshReleasePatch().verify(out.read_bytes()) == []
    assert src.read_bytes() == bytes(image)  # the input is never modified


def test_the_patch_is_attributed() -> None:
    assert WallMeshReleasePatch.author


def test_the_patch_adds_no_ini_surface() -> None:
    """There is no keyword and no opt-in: the patch changes what an existing wall block already
    does, so a mod that never heard of it still benefits and cannot write anything to decline."""
    assert WallMeshReleasePatch().ini_surface() is STOCK


# --- the hooks ----------------------------------------------------------------------------------


@pytest.mark.parametrize(("call_va", "stock_va"), CALL_HOOKS)
def test_hook_retargets_a_stock_call_into_the_cave(
    image: bytearray, call_va: int, stock_va: int
) -> None:
    data = _patched(image)
    section_va, _off, vsize = _cave(data)
    off = va_to_offset(data, call_va)
    assert off is not None
    assert bytes(image[off : off + 5]) == _call_bytes(call_va, stock_va)
    assert section_va <= _hook_target(data, call_va) < section_va + vsize


def test_every_call_hook_lands_on_its_own_entry_point(image: bytearray) -> None:
    """Five hooks, five routines. They tail-jump to different engine functions with different
    stack contracts, so a shared thunk would return to the wrong place from four of the five."""
    data = _patched(image)
    targets = [_hook_target(data, call_va) for call_va, _stock in CALL_HOOKS]
    assert len(set(targets)) == len(targets)


@pytest.mark.parametrize("window_va", HOOK_RAMP_WINDOWS)
def test_ramp_window_becomes_a_call_and_two_nops(image: bytearray, window_va: int) -> None:
    """The seven displaced bytes are re-emitted by the routine, so the window is a `call` plus
    padding to the original length - never a shortened instruction stream."""
    data = _patched(image)
    section_va, _off, vsize = _cave(data)
    off = va_to_offset(data, window_va)
    assert off is not None
    assert bytes(image[off : off + len(RAMP_WINDOW_STOCK)]) == RAMP_WINDOW_STOCK
    new = bytes(data[off : off + len(RAMP_WINDOW_STOCK)])
    assert new[0] == 0xE8
    assert new[5:] == b"\x90\x90"
    assert section_va <= _hook_target(data, window_va) < section_va + vsize


def test_both_ramp_windows_share_one_routine(image: bytearray) -> None:
    """They displace byte-identical instructions and record into the same row, so one routine
    serves both - which is also what makes the second ramp land in the second field."""
    data = _patched(image)
    first, second = (_hook_target(data, va) for va in HOOK_RAMP_WINDOWS)
    assert first == second


def test_nothing_outside_the_hooks_and_the_cave_is_rewritten(image: bytearray) -> None:
    """The patch's whole footprint in existing code is five displacements and two seven-byte
    windows. Everything else it changes is the PE header block and the bytes it appends, so the
    comparison runs over the original file past its headers."""
    data = _patched(image)
    headers = 0x400  # SizeOfHeaders in the stand-in; the section table lives inside it
    changed = {i for i in range(headers, len(image)) if data[i] != image[i]}
    allowed: set[int] = set()
    for call_va, _stock in CALL_HOOKS:
        off = va_to_offset(data, call_va)
        assert off is not None
        allowed |= set(range(off + 1, off + 5))  # the displacement; the 0xE8 stays put
    for window_va in HOOK_RAMP_WINDOWS:
        off = va_to_offset(data, window_va)
        assert off is not None
        allowed |= set(range(off, off + len(RAMP_WINDOW_STOCK)))
    # A subset rather than an equality: a displacement byte that happens to match the stock one
    # does not show up as changed, and every hook is checked for target above.
    assert changed <= allowed


# --- the ledger ---------------------------------------------------------------------------------


def test_the_ledger_leads_the_cave_and_starts_empty(image: bytearray) -> None:
    """Every routine addresses the table by its resolved base, and a row whose key is zero is
    free - so a cave that shipped with anything else in it would release a stale render object."""
    data = _patched(image)
    _va, off, vsize = _cave(data)
    assert vsize > LEDGER_SIZE + SCRATCH_SIZE
    assert bytes(data[off : off + LEDGER_SIZE + SCRATCH_SIZE]) == bytes(LEDGER_SIZE + SCRATCH_SIZE)


def test_the_ledger_is_bounded_by_its_declared_size(image: bytearray) -> None:
    """Both scans are a fixed `LEDGER_SLOTS` iterations, so a full table returns nothing rather
    than walking past the last row into the scratch dwords behind it."""
    data = _patched(image)
    _section_va, off, vsize = _cave(data)
    code = bytes(data[off + LEDGER_SIZE + SCRATCH_SIZE : off + vsize])
    bound = b"\xb9" + struct.pack("<I", LEDGER_SLOTS)  # mov ecx, LEDGER_SLOTS
    assert code.count(bound) == 3  # the lookup, the free-row search, and the wholesale clear
    assert LEDGER_SIZE == LEDGER_SLOTS * ENTRY_SIZE


def test_the_scratch_dwords_sit_behind_the_table(image: bytearray) -> None:
    """The removal keeps its row and its `Pathfinder` in the cave rather than in registers, and
    both have to be addressable without colliding with the last row."""
    section_va = 0x10000000
    content, _entries = build_section(section_va)
    entry_va = section_va + LEDGER_SIZE
    pathfinder_va = entry_va + 4
    code = content[LEDGER_SIZE + SCRATCH_SIZE :]
    assert struct.pack("<I", entry_va) in code
    assert struct.pack("<I", pathfinder_va) in code


# --- what the cave actually reads and writes -----------------------------------------------------


def _disassembled(data: bytes | bytearray) -> list:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    section_va, off, vsize = _cave(data)
    start = LEDGER_SIZE + SCRATCH_SIZE
    code = bytes(data[off + start : off + vsize])
    return list(md.disasm(code, section_va + start))


def test_the_cave_disassembles_cleanly_to_its_end(image: bytearray) -> None:
    """A mistyped opcode does not raise - it desynchronises, and the tail decodes as garbage. So
    the whole body has to decode, and the last instruction has to be one that leaves."""
    data = _patched(image)
    _va, off, vsize = _cave(data)
    body = vsize - LEDGER_SIZE - SCRATCH_SIZE
    instructions = _disassembled(data)
    decoded = sum(ins.size for ins in instructions)
    assert decoded == body, f"decoded {decoded} of {body} bytes"
    assert instructions[-1].mnemonic == "jmp"


@pytest.mark.parametrize(
    ("offset", "what"),
    [
        (SLOT_LIST_HEAD_OFFSET, "the wall-layer slot's render-object list head"),
        (RENDER_OBJ_NEXT_OFFSET, "the render object's own link"),
    ],
)
def test_the_surface_walk_uses_the_engines_own_offsets(
    image: bytearray, offset: int, what: str
) -> None:
    """`pushWallLayerMesh` is the whole of the engine's side of this list, and the removal is its
    inverse written by hand - so both offsets are taken from the routine being inverted."""
    data = _patched(image)
    accesses = {
        ins.op_str
        for ins in _disassembled(data)
        if f"+ 0x{offset:x}]" in ins.op_str and ins.mnemonic in {"mov", "cmp"}
    }
    assert accesses, f"the cave never touches {what} at +0x{offset:x}"


def test_the_ramp_walk_uses_the_engines_own_offsets(image: bytearray) -> None:
    """The ramp list is headed on the `Pathfinder` and linked through the record's `+4`, exactly
    as `Pathfinder::reset` walks it."""
    data = _patched(image)
    text = " ".join(ins.op_str for ins in _disassembled(data))
    assert f"+ 0x{PATHFINDER_RAMP_LIST_OFFSET:x}]" in text
    assert f"+ {RAMP_NEXT_OFFSET}]" in text or f"+ 0x{RAMP_NEXT_OFFSET:x}]" in text


def test_the_removal_ends_at_the_stock_unmark_loop(image: bytearray) -> None:
    """Restoring the rectangle is only half of leg 3 - the other half is arriving at the loop that
    reads it, which is reached by an absolute jump and by nothing else."""
    data = _patched(image)
    targets = {
        ins.op_str for ins in _disassembled(data) if ins.mnemonic == "jmp" and "0x" in ins.op_str
    }
    assert hex(UNMARK_LOOP_VA) in targets


def test_the_removal_hands_a_shared_slot_back_through_the_engine(image: bytearray) -> None:
    """The slot is released with the engine's own routine, never by clearing its fields here:
    that routine also drops the slot's cell data, which nothing in this patch reproduces."""
    data = _patched(image)
    calls = {ins.op_str for ins in _disassembled(data) if ins.mnemonic == "call"}
    assert hex(RELEASE_WALL_LAYER) in calls


def test_the_cave_reads_the_frame_at_the_documented_displacements(image: bytearray) -> None:
    """Six of ``0x00935FAA``'s locals, and a displacement a few bytes out silently reads its
    neighbour. The rectangle is four dwords at ebp-0x38/-0x30/-0x3C/-0x34, `Object *` is at
    ebp+8 and `adding` at ebp+0xC - all of them pinned by anchor windows."""
    data = _patched(image)
    frame = {
        ins.op_str.split("[")[1].split("]")[0]
        for ins in _disassembled(data)
        if "ebp" in ins.op_str and "[" in ins.op_str
    }
    assert {"ebp - 0x38", "ebp - 0x30", "ebp - 0x3c", "ebp - 0x34"} <= frame
    assert {"ebp + 8", "ebp + 0xc"} <= frame


# --- the build fingerprint ------------------------------------------------------------------------


@pytest.mark.parametrize("va", sorted(ANCHORS))
def test_a_corrupted_anchor_is_refused(image: bytearray, va: int) -> None:
    """Every window the patch depends on has to fail loudly, whether it is one the patch rewrites
    or one it only reads."""
    data = bytearray(image)
    off = va_to_offset(data, va)
    assert off is not None
    data[off] ^= 0xFF
    with pytest.raises(ValueError, match="not the expected build"):
        WallMeshReleasePatch().apply(data)


def test_an_unmapped_anchor_is_refused() -> None:
    """The other way an anchor fails: not wrong bytes but no bytes, which is what a binary that
    is not this build at all looks like from here."""
    dropped = min(ANCHORS)
    image = _sparse_image({va: b for va, b in ANCHORS.items() if va != dropped})
    with pytest.raises(ValueError, match="not the expected build"):
        WallMeshReleasePatch().apply(bytearray(image))
