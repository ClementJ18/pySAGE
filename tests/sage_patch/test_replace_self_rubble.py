"""Tests for the replace-self-rubble patch.

The hook is one repointed `call`, so what can go wrong without raising is the cave's reading of its
surroundings: the two return addresses it compares against, the frame walk from the clearing loop
to `buildObjectNow`'s caller, the `KindOf` bits it lets through, and that `edx` survives for the
loop to read. So the real loop bytes and the real predicate are run, before and after the patch,
over every combination that matters: who is building, and what is lying under the footprint.
"""

from __future__ import annotations

import faulthandler
import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    CLEAR_REMOVABLES_LOOP,
    CLEAR_REMOVABLES_LOOP_BYTES,
    CLEAR_REMOVABLES_PREDICATE_CALL,
    CLEAR_REMOVABLES_RETURN,
    IS_REMOVABLE_FOR_CONSTRUCTION,
    IS_REMOVABLE_FOR_CONSTRUCTION_BYTES,
    OBJECT_EFFECTIVELY_DEAD_FLAG,
    REPLACE_SELF_BUILD_CALL,
    REPLACE_SELF_BUILD_RETURN,
)
from sage_patch.patches.foundation_rebind import FoundationRebindPatch
from sage_patch.patches.replace_self_rubble import (
    ANCHORS,
    SECTION_NAME,
    ReplaceSelfRubblePatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import call_rel32, find_section, va_to_offset
from tests.sage_patch.synthetic import replace_self_rubble_image

#: The instruction after the hooked `call`: `cmp al, 1`.
_AFTER_CALL = CLEAR_REMOVABLES_PREDICATE_CALL + 5
#: The two other routes into a site clear: the dozer placement path's own call to the clearing
#: loop, and the mount swap's call to `buildObjectNow` (`docs/lifetime-transform.md`).
_DOZER_PLACEMENT_RETURN = 0x005F106D
_MOUNT_SWAP_RETURN = 0x008B1489


def _read(data: bytes | bytearray, va: int, n: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + n])


def _cave_va(data: bytes | bytearray) -> int:
    located = find_section(data, SECTION_NAME)
    assert located is not None, f"no {SECTION_NAME} section"
    return located[0]


@pytest.fixture
def image() -> bytearray:
    return replace_self_rubble_image()


@pytest.fixture
def patched() -> bytearray:
    data = replace_self_rubble_image()
    ReplaceSelfRubblePatch().apply(data)
    return data


class TestStructure:
    def test_the_hook_is_the_predicate_call(self) -> None:
        off = CLEAR_REMOVABLES_PREDICATE_CALL - CLEAR_REMOVABLES_LOOP
        stock = CLEAR_REMOVABLES_LOOP_BYTES[off : off + 5]
        assert stock == call_rel32(CLEAR_REMOVABLES_PREDICATE_CALL, IS_REMOVABLE_FOR_CONSTRUCTION)

    def test_the_replace_self_return_follows_its_call(self) -> None:
        # `call [ebx+0x38]` is the last instruction of the pinned window
        assert ANCHORS[REPLACE_SELF_BUILD_CALL].endswith(bytes.fromhex("ff5338"))
        assert REPLACE_SELF_BUILD_CALL + len(ANCHORS[REPLACE_SELF_BUILD_CALL]) == (
            REPLACE_SELF_BUILD_RETURN
        )

    def test_the_hook_calls_the_cave(self, patched: bytearray) -> None:
        want = call_rel32(CLEAR_REMOVABLES_PREDICATE_CALL, _cave_va(patched))
        assert _read(patched, CLEAR_REMOVABLES_PREDICATE_CALL, 5) == want

    def test_nothing_else_in_the_loop_moves(self, patched: bytearray) -> None:
        got = _read(patched, CLEAR_REMOVABLES_LOOP, len(CLEAR_REMOVABLES_LOOP_BYTES))
        hook = CLEAR_REMOVABLES_PREDICATE_CALL - CLEAR_REMOVABLES_LOOP
        assert got[:hook] == CLEAR_REMOVABLES_LOOP_BYTES[:hook]
        assert got[hook + 5 :] == CLEAR_REMOVABLES_LOOP_BYTES[hook + 5 :]

    def test_the_cave_decodes_as_written(self, patched: bytearray) -> None:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        cave = _cave_va(patched)
        code = build_code(cave)
        listing = [f"{i.mnemonic} {i.op_str}" for i in md.disasm(code, cave)]
        stock = f"jne {cave + len(code) - 5:#x}"
        assert listing == [
            f"cmp dword ptr [ebp + 4], {CLEAR_REMOVABLES_RETURN:#x}",
            stock,
            "mov eax, dword ptr [ebp]",
            f"cmp dword ptr [eax + 4], {REPLACE_SELF_BUILD_RETURN:#x}",
            stock,
            "mov eax, dword ptr [esp + 4]",
            "test eax, eax",
            stock.replace("jne", "je"),
            f"test byte ptr [eax + {OBJECT_EFFECTIVELY_DEAD_FLAG:#x}], 1",
            stock.replace("jne", "je"),
            "mov ecx, dword ptr [eax + 4]",
            "test byte ptr [ecx + 0x108], 0x40",
            stock,
            "test byte ptr [ecx + 0x10e], 8",
            stock,
            "xor al, al",
            "ret 4",
            f"jmp {IS_REMOVABLE_FOR_CONSTRUCTION:#x}",
        ]
        assert _read(patched, cave, len(code)) == code


class TestLifecycle:
    def test_apply_verify_detect(self, patched: bytearray) -> None:
        assert ReplaceSelfRubblePatch().verify(patched) == []
        assert isinstance(ReplaceSelfRubblePatch.detect(patched), ReplaceSelfRubblePatch)

    def test_an_unpatched_image_is_not_detected(self, image: bytearray) -> None:
        assert ReplaceSelfRubblePatch().verify(image) != []
        assert ReplaceSelfRubblePatch.detect(image) is None

    def test_a_second_apply_refuses(self, patched: bytearray) -> None:
        with pytest.raises(ValueError, match="already carries this patch"):
            ReplaceSelfRubblePatch().apply(patched)

    @pytest.mark.parametrize("va", sorted(ANCHORS), ids=lambda va: f"{va:08x}")
    def test_every_anchor_is_load_bearing(self, image: bytearray, va: int) -> None:
        """Disturb one window: `apply` refuses before writing, and a patched image stops
        verifying."""
        off = va_to_offset(image, va)
        assert off is not None
        # the last byte: never the hooked call, which sits mid-window
        image[off + len(ANCHORS[va]) - 1] ^= 0xFF
        before = bytes(image)
        with pytest.raises(ValueError, match=f"@0x{va:08x}"):
            ReplaceSelfRubblePatch().apply(image)
        assert bytes(image) == before

        data = replace_self_rubble_image()
        ReplaceSelfRubblePatch().apply(data)
        off = va_to_offset(data, va)
        assert off is not None
        data[off + len(ANCHORS[va]) - 1] ^= 0xFF
        assert ReplaceSelfRubblePatch().verify(data) != []

    def test_registered_as_settled(self) -> None:
        assert PATCHES["replace-self-rubble"] is ReplaceSelfRubblePatch
        assert not ReplaceSelfRubblePatch.experimental


unicorn = pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EDI,
    UC_X86_REG_EDX,
    UC_X86_REG_ESP,
)

_PAGE = 0x1000
_HEAP = 0x20000000
_STACK = 0x30000000
_BUILD_ASSISTANT = 0x12345678

#: `KindOf` bits as `(byte offset in the template, bit)`: the mask starts at `template+0x108`.
KINDS = {
    "plain": None,
    "SHRUBBERY": (0x108, 0x40),
    "CLEARED_BY_BUILD": (0x10E, 0x08),
    "INERT": (0x113, 0x02),
}

#: Who asked for the site to be cleared, as `(clearing loop's return, buildObjectNow's return)`.
#: `None` for the second means the clearing loop was not reached through `buildObjectNow` at all,
#: so its caller's `[ebp]` is left unmapped and any read of it faults.
CALLERS = {
    "replace-self": (CLEAR_REMOVABLES_RETURN, REPLACE_SELF_BUILD_RETURN),
    "mount swap": (CLEAR_REMOVABLES_RETURN, _MOUNT_SWAP_RETURN),
    "dozer placement": (_DOZER_PLACEMENT_RETURN, None),
}


def _removable(data: bytes | bytearray, caller: str, dead: bool, kind: str) -> bool:
    """Run the hooked `call` out of `data` - the real loop bytes, the real predicate, and the cave
    if there is one - and return what the loop is told, checking that `edx` and `esp` come back
    as the loop expects."""
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    cave = find_section(data, SECTION_NAME)
    pages = {CLEAR_REMOVABLES_LOOP & ~0xFFF, IS_REMOVABLE_FOR_CONSTRUCTION & ~0xFFF, _STACK}
    pages |= {_HEAP, _HEAP + _PAGE}
    if cave is not None:
        pages.add(cave[0] & ~0xFFF)
    # `mem_map` raises and catches an SEH access violation inside Unicorn on Windows; every map
    # still succeeds, but the fault handler would print a stack for each one.
    was_enabled = faulthandler.is_enabled()
    faulthandler.disable()
    try:
        for page in sorted(pages):
            uc.mem_map(page, _PAGE)
    finally:
        if was_enabled:
            faulthandler.enable()

    uc.mem_write(
        CLEAR_REMOVABLES_LOOP,
        _read(data, CLEAR_REMOVABLES_LOOP, len(CLEAR_REMOVABLES_LOOP_BYTES)),
    )
    uc.mem_write(
        IS_REMOVABLE_FOR_CONSTRUCTION,
        _read(data, IS_REMOVABLE_FOR_CONSTRUCTION, len(IS_REMOVABLE_FOR_CONSTRUCTION_BYTES)),
    )
    if cave is not None:
        code = build_code(cave[0])
        uc.mem_write(cave[0], _read(data, cave[0], len(code)))

    obj, tmpl = _HEAP, _HEAP + _PAGE
    uc.mem_write(obj + 4, struct.pack("<I", tmpl))
    uc.mem_write(obj + OBJECT_EFFECTIVELY_DEAD_FLAG, bytes([1 if dead else 0]))
    if KINDS[kind] is not None:
        byte, bit = KINDS[kind]
        uc.mem_write(tmpl + byte, bytes([bit]))

    # Two frames, as `__EH_prolog` lays them out: `[ebp]` the caller's `ebp`, `[ebp+4]` the
    # return address. The clearing loop's frame sits below `buildObjectNow`'s.
    loop_return, build_return = CALLERS[caller]
    esp = _STACK + 0x400
    ebp = _STACK + 0x600
    outer = _STACK + 0x800
    uc.mem_write(ebp, struct.pack("<II", outer if build_return is not None else 0, loop_return))
    if build_return is not None:
        uc.mem_write(outer + 4, struct.pack("<I", build_return))

    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_EBP, ebp)
    uc.reg_write(UC_X86_REG_EDX, obj)
    uc.reg_write(UC_X86_REG_EDI, _BUILD_ASSISTANT)
    uc.reg_write(UC_X86_REG_EAX, 0xDEADBEEF)
    uc.emu_start(CLEAR_REMOVABLES_LOOP, _AFTER_CALL, count=100)

    assert uc.reg_read(UC_X86_REG_ESP) == esp, "the stack did not come back level"
    assert uc.reg_read(UC_X86_REG_EDX) == obj, "edx, which the loop reads next, was clobbered"
    return bool(uc.reg_read(UC_X86_REG_EAX) & 0xFF)


def _stock_rule(dead: bool, kind: str) -> bool:
    """`isRemovableForConstruction`, as its bytes read."""
    if kind == "INERT":
        return False
    return kind in ("SHRUBBERY", "CLEARED_BY_BUILD") or dead


_CASES = [(caller, dead, kind) for caller in CALLERS for dead in (True, False) for kind in KINDS]


@pytest.mark.parametrize(("caller", "dead", "kind"), _CASES)
class TestTheLoopRuns:
    def test_stock_follows_the_predicate(
        self, image: bytearray, caller: str, dead: bool, kind: str
    ) -> None:
        assert _removable(image, caller, dead, kind) is _stock_rule(dead, kind)

    def test_patched_keeps_only_rubble_under_a_replacement(
        self, patched: bytearray, caller: str, dead: bool, kind: str
    ) -> None:
        kept = caller == "replace-self" and dead and kind in ("plain", "INERT")
        want = False if kept else _stock_rule(dead, kind)
        assert _removable(patched, caller, dead, kind) is want


#: Both copies a checkout can hold; neither is committed, so each check skips when absent.
_BINARIES = {
    "repo": Path(__file__).resolve().parents[2] / "game.dat",
    "clean": Path(__file__).resolve().parents[2] / "sage_patch" / "engine" / "game.dat.backup",
}


@pytest.mark.parametrize("which", sorted(_BINARIES))
class TestStockBinaries:
    def _stock(self, which: str) -> bytes:
        path = _BINARIES[which]
        if not path.exists():
            pytest.skip(f"needs {path.name}")
        return path.read_bytes()

    def test_every_anchor_is_stock(self, which: str) -> None:
        stock = self._stock(which)
        for va, want in ANCHORS.items():
            assert _read(stock, va, len(want)) == want, f"0x{va:08x}"

    def test_apply_verify_detect_round_trip(self, which: str) -> None:
        data = bytearray(self._stock(which))
        ReplaceSelfRubblePatch().apply(data)
        assert ReplaceSelfRubblePatch().verify(data) == []
        assert isinstance(ReplaceSelfRubblePatch.detect(data), ReplaceSelfRubblePatch)

    @pytest.mark.parametrize("first_self", [True, False])
    def test_composes_with_foundation_rebind(self, which: str, first_self: bool) -> None:
        """Both read the `ReplaceSelfUpgrade` creation `call`; neither may rewrite it."""
        data = bytearray(self._stock(which))
        order = [ReplaceSelfRubblePatch(), FoundationRebindPatch()]
        for patch in order if first_self else order[::-1]:
            patch.apply(data)
        assert ReplaceSelfRubblePatch().verify(data) == []
        assert FoundationRebindPatch().verify(data) == []
