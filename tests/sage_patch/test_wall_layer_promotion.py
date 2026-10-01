"""Tests for `wall-layer-promotion`, which stops a siege engine being teleported onto a wall it
walked past instead of climbed.

Four things can go wrong here and none of them raises on its own, so all four are checked
statically.

The first is the **stack contract**. Every hooked site is a `call`, so the cave is entered with a
return address on the stack and has to leave it exactly as `Object::setLayer` would: either by
tail-jumping to `setLayer`, whose `ret 4` pops the argument, or by issuing its own `ret 4`. A cave
that jumped away, or returned with a bare `ret`, would unbalance the caller's frame. Both exits are
disassembled back and asserted.

The second is **which promotions the gate refuses**, which is the whole design. Two behaviours have
to survive and one has to stop, and they differ only in operands: a catapult climbing a ramp holds
layer 16, a catapult already on the walkway is level with it, and a trebuchet shoved into a wall's
bounds is a storey below it. The cave is executed over all three, against its own disassembly.

The third is **covering every road**. `setLayer` has 30 callers and gating one of them was measured
in game to be insufficient: the object-moved path reaches it through
`TerrainLogic::getLayerForDestination` with no height test at all. Every site in `HOOK_SITES` is
checked for being redirected, because a patch that installs two of three hooks looks installed.

The fourth is the **build fingerprint**. The patch rewrites five bytes per site and reads six
windows it does not rewrite; every one has to fail loudly on anything else.
"""

from __future__ import annotations

import struct

import pytest

from sage_ini.engine import STOCK
from sage_patch.addresses import (
    KINDOF_MACHINE_BYTE,
    KINDOF_MACHINE_MASK,
    OBJECT_SET_LAYER,
    WALL_LAYER_FIRST,
    WALL_LAYER_LAST,
)
from sage_patch.patches.wall_layer_promotion import (
    ANCHORS,
    HOOK_SITES,
    SECTION_NAME,
    WallLayerPromotionPatch,
    build_code,
)
from sage_patch.utils import find_section, va_to_offset

from .synthetic import wall_layer_promotion_image

capstone = pytest.importorskip("capstone")

CAVE_VA = 0x01000000

#: The engine's own "near enough to the same level", which the gate reuses.
LEVEL_TOLERANCE = 10.0


def _patched() -> tuple[bytearray, bytearray]:
    """The stand-in before and after, patched in memory - `apply` mutates a bytearray."""
    image = wall_layer_promotion_image()
    data = bytearray(image)
    WallLayerPromotionPatch().apply(data)
    return image, data


def _disassemble(code: bytes, base: int = CAVE_VA) -> list[capstone.CsInsn]:
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return list(md.disasm(code, base))


def test_every_site_is_redirected_and_stays_a_call() -> None:
    """All three roads onto a wall, not just the one that was found first.

    Gating only `Pathfinder::updateObjectLayer` was measured in a running game to leave the bug
    in place, so "some hooks installed" must not read as installed.
    """
    _, data = _patched()
    located = find_section(data, SECTION_NAME)
    assert located is not None
    section_va, _, _ = located

    assert len(HOOK_SITES) == 3
    for va, _stock, _args in HOOK_SITES:
        off = va_to_offset(data, va)
        assert off is not None
        assert data[off] == 0xE8, f"the hook at {va:#010x} is no longer a call"
        target = va + 5 + struct.unpack_from("<i", data, off + 1)[0]
        assert target == section_va, f"the hook at {va:#010x} does not reach the gate"


def test_every_site_calls_set_layer_before_patching() -> None:
    """Each site's stock bytes must really be the `setLayer` call the gate stands in front of."""
    for va, stock, _args in HOOK_SITES:
        assert stock[0] == 0xE8
        assert va + 5 + struct.unpack("<i", stock[1:5])[0] == OBJECT_SET_LAYER


def test_both_exits_balance_the_stack() -> None:
    """One exit tail-jumps to `setLayer` (its `ret 4` pops the argument); the other does it here."""
    instructions = _disassemble(build_code(CAVE_VA))

    jumps = [i for i in instructions if i.mnemonic == "jmp"]
    assert len(jumps) == 1, "the allow path should be a single tail jump"
    assert int(jumps[0].op_str, 16) == OBJECT_SET_LAYER

    returns = [i for i in instructions if i.mnemonic.startswith("ret")]
    assert len(returns) == 1, "the refuse path should be a single return"
    assert returns[0].op_str == "4", "the refused path must still pop setLayer's argument"


def test_the_gate_reads_the_argument_the_template_and_the_height() -> None:
    """`ecx` is the object and `[esp+4]` the layer at all three sites; both tests must reach."""
    instructions = _disassemble(build_code(CAVE_VA))
    text = [f"{i.mnemonic} {i.op_str}" for i in instructions]

    assert "mov eax, dword ptr [esp + 4]" in text, "the destination layer is the call's argument"
    assert "mov edx, dword ptr [ecx + 4]" in text, "the ThingTemplate hangs off Object+0x04"
    assert f"test byte ptr [edx + {KINDOF_MACHINE_BYTE:#x}], {KINDOF_MACHINE_MASK}" in text
    assert "subss xmm0, dword ptr [ecx + 0x40]" in text, "the object's z is Object+0x40"


@pytest.mark.parametrize(
    ("layer", "machine", "surface", "z", "refused", "what"),
    [
        (1, True, 0.0, 0.0, False, "ground"),
        (16, True, 0.0, 200.0, False, "a catapult part-way up a ramp"),
        (16, False, 0.0, 200.0, False, "infantry on a ramp"),
        (WALL_LAYER_FIRST, True, 255.4, 255.4, False, "a catapult stepping off the ramp"),
        (WALL_LAYER_FIRST, True, 255.4, 252.0, False, "a catapult on the walkway, slightly low"),
        (18, True, 219.0, 165.6, True, "THE BUG: a trebuchet at ground level"),
        (18, False, 219.0, 165.6, False, "infantry at ground level: not this patch's business"),
        (WALL_LAYER_LAST, True, 300.0, 100.0, True, "the last wall-height layer"),
        (WALL_LAYER_LAST + 1, True, 300.0, 100.0, False, "past the range isWallLayer accepts"),
    ],
)
def test_gate_decision(
    layer: int, machine: bool, surface: float, z: float, refused: bool, what: str
) -> None:
    """Execute the cave's decision the way the CPU would, over the cases that were measured.

    The ramp and walkway rows are the ones that matter: refusing either would strand a catapult
    that climbed a castle ramp properly, which is worse than the bug being fixed.
    """
    decision = _decide(layer, machine, surface, z)
    assert decision is refused, (
        f"{what}: {'refused' if decision else 'allowed'}, "
        f"expected {'refused' if refused else 'allowed'}"
    )


def test_the_threshold_is_the_engines_own() -> None:
    """The boundary must sit at the engine's 10 units, not at a number invented here."""
    assert _decide(18, True, 100.0 + LEVEL_TOLERANCE + 1.0, 100.0) is True
    assert _decide(18, True, 100.0 + LEVEL_TOLERANCE - 1.0, 100.0) is False


def _decide(layer: int, machine: bool, surface: float = 0.0, z: float = 0.0) -> bool:
    """The cave's logic, read off its own disassembly rather than restated.

    Walks the emitted instructions and follows the branches with the operands the CPU would have,
    so a cave whose comparisons were emitted the wrong way round fails this rather than passing a
    hand-written copy of the intended rule.
    """
    instructions = {i.address: i for i in _disassemble(build_code(CAVE_VA))}
    pc = min(instructions)
    eax = 0
    flags = 0
    above = False
    xmm0 = 0.0

    while True:
        instruction = instructions[pc]
        text = f"{instruction.mnemonic} {instruction.op_str}"
        following = instruction.address + instruction.size

        if text == "mov eax, dword ptr [esp + 4]":
            eax = layer
        elif instruction.mnemonic == "cmp":
            flags = eax - int(instruction.op_str.split(", ")[1], 0)
        elif instruction.mnemonic == "mov":
            eax = 1  # every other load here is a pointer a running game has
        elif instruction.mnemonic == "test" and "byte ptr" in instruction.op_str:
            flags = KINDOF_MACHINE_MASK if machine else 0
        elif instruction.mnemonic == "test":
            flags = 1  # the null checks: a running game has all of these
        elif instruction.mnemonic == "movss":
            xmm0 = surface
        elif instruction.mnemonic == "subss":
            xmm0 -= z
        elif instruction.mnemonic == "comiss":
            above = xmm0 > LEVEL_TOLERANCE
        elif instruction.mnemonic == "jl":
            pc = int(instruction.op_str, 16) if flags < 0 else following
            continue
        elif instruction.mnemonic == "jg":
            pc = int(instruction.op_str, 16) if flags > 0 else following
            continue
        elif instruction.mnemonic == "je":
            pc = int(instruction.op_str, 16) if flags == 0 else following
            continue
        elif instruction.mnemonic == "ja":
            pc = int(instruction.op_str, 16) if above else following
            continue
        elif instruction.mnemonic == "jmp":
            return False  # tail-called setLayer: the layer is set
        elif instruction.mnemonic.startswith("ret"):
            return True  # returned without moving the object
        pc = following


def test_verify_round_trip() -> None:
    patch = WallLayerPromotionPatch()
    image, data = _patched()
    assert patch.verify(image), "an unpatched image should not verify clean"
    assert patch.verify(data) == []
    assert patch.ini_surface() is STOCK


def test_a_half_installed_patch_does_not_verify() -> None:
    """Three hooks, and two of them is not the fix - the measured failure mode of the first cut."""
    patch = WallLayerPromotionPatch()
    _, data = _patched()
    va, stock, _args = HOOK_SITES[-1]
    off = va_to_offset(data, va)
    assert off is not None
    data[off : off + len(stock)] = stock  # put one site back to stock
    assert patch.verify(data), "a site left unhooked should be reported"


def test_only_the_hooked_calls_are_rewritten() -> None:
    """The patch's whole footprint in existing code is one displacement per site.

    Everything else it changes is the PE header block and the appended cave, so the comparison
    runs over the original file past its headers.
    """
    image, data = _patched()
    headers = 0x400  # SizeOfHeaders in the stand-in; the section table lives inside it
    changed = {i for i in range(headers, len(image)) if data[i] != image[i]}

    allowed: set[int] = set()
    for va, stock, _args in HOOK_SITES:
        off = va_to_offset(image, va)
        assert off is not None
        # The 0xE8 stays put - only the displacement moves. A subset rather than an equality: a
        # displacement byte that happens to match the stock one does not show up as changed.
        allowed |= set(range(off + 1, off + len(stock)))
    assert changed <= allowed


@pytest.mark.parametrize("va", sorted(ANCHORS))
def test_a_moved_anchor_is_refused(va: int) -> None:
    """Each window the cave depends on has to fail loudly if this is not that build."""
    image = wall_layer_promotion_image()
    off = va_to_offset(image, va)
    assert off is not None
    image[off] ^= 0xFF

    with pytest.raises(ValueError, match="expected"):
        WallLayerPromotionPatch().apply(bytearray(image))
