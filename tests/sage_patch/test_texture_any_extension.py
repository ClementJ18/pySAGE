"""Tests for the texture-any-extension patch.

The hook is one `jmp` and a wrapper that calls the stock getter back, so the structural checks are
short. What could be wrong without raising is the wrapper itself: which name it hands on, that
the four arguments arrive where the getter reads them, and that the stack and the callee-saved
registers come back as they went in. So the wrapper is run, with the CRT helpers and the cache
lookup answered from Python, over one name of each kind.
"""

from __future__ import annotations

import faulthandler
import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    ASSET_CACHE_HAS_ASSET,
    STRCPY,
    STRLEN,
    STRRCHR_SLOT,
    TEXTURE_EXTENSION_TGA,
    TEXTURE_GET_BY_NAME,
    TEXTURE_GET_BY_NAME_BYTES,
    TEXTURE_GET_BY_NAME_RESUME,
)
from sage_patch.patches.texture_any_extension import (
    ANCHORS,
    HOOK_WIDTH,
    MAX_NAME_LENGTH,
    SECTION_NAME,
    STOCK_HOOK,
    TextureAnyExtensionPatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, jmp_rel32, va_to_offset
from tests.sage_patch.synthetic import texture_any_extension_image


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
    return texture_any_extension_image()


@pytest.fixture
def patched() -> bytearray:
    data = texture_any_extension_image()
    TextureAnyExtensionPatch().apply(data)
    return data


class TestStructure:
    def test_the_hook_is_the_handler_load(self) -> None:
        # mov eax, 0xb79b0f
        assert STOCK_HOOK == bytes.fromhex("b80f9bb700")

    def test_the_hook_jumps_to_the_cave(self, patched: bytearray) -> None:
        want = jmp_rel32(TEXTURE_GET_BY_NAME, _cave_va(patched), HOOK_WIDTH)
        assert _read(patched, TEXTURE_GET_BY_NAME, HOOK_WIDTH) == want

    def test_nothing_else_in_the_getter_moves(self, patched: bytearray) -> None:
        got = _read(patched, TEXTURE_GET_BY_NAME, len(TEXTURE_GET_BY_NAME_BYTES))
        assert got[HOOK_WIDTH:] == TEXTURE_GET_BY_NAME_BYTES[HOOK_WIDTH:]

    def test_the_cave_decodes_as_written(self, patched: bytearray) -> None:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        cave = _cave_va(patched)
        code = build_code(cave)
        listing = [f"{i.mnemonic} {i.op_str}" for i in md.disasm(code, cave)]
        assert sum(i.size for i in md.disasm(code, cave)) == len(code)
        get = next(i.address for i in md.disasm(code, cave) if i.op_str == "dword ptr [ebp + 0x14]")
        assert listing[:7] == [
            "push ebp",
            "mov ebp, esp",
            "sub esp, 0x10c",
            "push esi",
            "push edi",
            "mov esi, dword ptr [ebp + 0xc]",
            "test esi, esi",
        ]
        assert listing[7] == f"je {get:#x}"
        assert f"cmp eax, {MAX_NAME_LENGTH:#x}" in listing
        assert f"call dword ptr [{STRRCHR_SLOT:#x}]" in listing
        assert f"push {TEXTURE_EXTENSION_TGA:#x}" in listing
        assert listing[-9:] == [
            "push dword ptr [ebp + 8]",
            f"call {cave + len(code) - 10:#x}",
            "add esp, 0x10",
            "pop edi",
            "pop esi",
            "leave ",
            "ret ",
            "mov eax, 0xb79b0f",
            f"jmp {TEXTURE_GET_BY_NAME_RESUME:#x}",
        ]
        assert _read(patched, cave, len(code)) == code


class TestLifecycle:
    def test_apply_verify_detect(self, patched: bytearray) -> None:
        assert TextureAnyExtensionPatch().verify(patched) == []
        assert isinstance(TextureAnyExtensionPatch.detect(patched), TextureAnyExtensionPatch)

    def test_an_unpatched_image_is_not_detected(self, image: bytearray) -> None:
        assert TextureAnyExtensionPatch().verify(image) != []
        assert TextureAnyExtensionPatch.detect(image) is None

    def test_a_second_apply_refuses(self, patched: bytearray) -> None:
        with pytest.raises(ValueError, match="already carries this patch"):
            TextureAnyExtensionPatch().apply(patched)

    @pytest.mark.parametrize("va", sorted(ANCHORS))
    def test_a_drifted_anchor_refuses_before_writing(self, image: bytearray, va: int) -> None:
        off = va_to_offset(image, va)
        assert off is not None
        image[off + len(ANCHORS[va]) - 1] ^= 0xFF
        before = bytes(image)
        with pytest.raises(ValueError, match="not the expected build"):
            TextureAnyExtensionPatch().apply(image)
        assert bytes(image) == before

    def test_registered_as_settled(self) -> None:
        assert PATCHES["texture-any-extension"] is TextureAnyExtensionPatch
        assert not TextureAnyExtensionPatch.experimental


unicorn = pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EDI,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

_PAGE = 0x1000
_HEAP = 0x20000000
_STACK = 0x30000000
_STUBS = 0x40000000
_STRRCHR = _STUBS + 0x10
_RETURN = _STUBS + 0x20
_OUT, _A3, _A4 = 0x11111111, 0x33333333, 0x44444444
_ESI, _EDI, _EBP = 0x51515151, 0xD1D1D1D1, 0xB9B9B9B9


def _cstring(emu: Uc, va: int) -> str:
    out = bytearray()
    while (byte := bytes(emu.mem_read(va + len(out), 1))[0]) != 0:
        out.append(byte)
    return out.decode("latin-1")


def _get(data: bytes | bytearray, name: str | None, cached: set[str]) -> str | None:
    """Call the getter out of `data` for `name`, with a cache holding `cached`, and return the
    name the stock body was entered with. The four helpers are answered here; the stock body is a
    bare `ret` that reports its arguments."""
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    cave = find_section(data, SECTION_NAME)
    assert cave is not None
    pages = {va & ~0xFFF for va in (TEXTURE_GET_BY_NAME, STRLEN, ASSET_CACHE_HAS_ASSET)}
    pages |= {STRRCHR_SLOT & ~0xFFF, TEXTURE_EXTENSION_TGA & ~0xFFF, cave[0] & ~0xFFF}
    pages |= {_HEAP, _STACK, _STUBS}
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

    uc.mem_write(TEXTURE_GET_BY_NAME, _read(data, TEXTURE_GET_BY_NAME, HOOK_WIDTH))
    uc.mem_write(cave[0], _read(data, cave[0], len(build_code(cave[0]))))
    uc.mem_write(TEXTURE_EXTENSION_TGA, _read(data, TEXTURE_EXTENSION_TGA, 5))
    uc.mem_write(STRRCHR_SLOT, struct.pack("<I", _STRRCHR))
    for stub in (STRLEN, STRCPY, ASSET_CACHE_HAS_ASSET, _STRRCHR, TEXTURE_GET_BY_NAME_RESUME):
        uc.mem_write(stub, b"\xc3")  # ret - every one is cdecl

    name_va = 0
    if name is not None:
        name_va = _HEAP + 0x100
        uc.mem_write(name_va, name.encode("latin-1") + b"\x00")
    held = {entry.lower() for entry in cached}
    entered: list[str | None] = []

    def on_code(emu: Uc, address: int, _size: int, _user: object) -> None:
        esp = emu.reg_read(UC_X86_REG_ESP)
        args = struct.unpack("<IIII", bytes(emu.mem_read(esp + 4, 16)))
        if address == STRLEN:
            emu.reg_write(UC_X86_REG_EAX, len(_cstring(emu, args[0])))
        elif address == STRCPY:
            emu.mem_write(args[0], _cstring(emu, args[1]).encode("latin-1") + b"\x00")
            emu.reg_write(UC_X86_REG_EAX, args[0])
        elif address == _STRRCHR:
            assert args[1] == ord(".")
            at = _cstring(emu, args[0]).rfind(".")
            emu.reg_write(UC_X86_REG_EAX, 0 if at < 0 else args[0] + at)
        elif address == ASSET_CACHE_HAS_ASSET:
            emu.reg_write(UC_X86_REG_EAX, int(_cstring(emu, args[0]).lower() in held))
        elif address == TEXTURE_GET_BY_NAME_RESUME:
            assert emu.reg_read(UC_X86_REG_EAX) == 0xB79B0F, "the displaced mov was not replayed"
            assert (args[0], args[2], args[3]) == (_OUT, _A3, _A4)
            entered.append(_cstring(emu, args[1]) if args[1] else None)
            emu.reg_write(UC_X86_REG_EAX, args[0])

    uc.hook_add(UC_HOOK_CODE, on_code)

    esp = _STACK + 0xC00
    uc.mem_write(esp, struct.pack("<IIIII", _RETURN, _OUT, name_va, _A3, _A4))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ESI, _ESI)
    uc.reg_write(UC_X86_REG_EDI, _EDI)
    uc.reg_write(UC_X86_REG_EBP, _EBP)
    uc.emu_start(TEXTURE_GET_BY_NAME, _RETURN, count=400)

    assert uc.reg_read(UC_X86_REG_ESP) == esp + 4, "the wrapper left the stack unlevel"
    assert uc.reg_read(UC_X86_REG_EAX) == _OUT
    assert uc.reg_read(UC_X86_REG_ESI) == _ESI
    assert uc.reg_read(UC_X86_REG_EDI) == _EDI
    assert uc.reg_read(UC_X86_REG_EBP) == _EBP
    assert len(entered) == 1, "the stock body must run exactly once"
    return entered[0]


class TestTheWrapperRuns:
    CACHE = frozenset({"gumaarms_skn.tga", "authored.dds", "authored.tga"})

    @pytest.mark.parametrize(
        ("name", "handed_on"),
        [
            ("gumaarms_skn.tga", "gumaarms_skn.tga"),
            ("gumaarms_skn.dds", "gumaarms_skn.tga"),
            ("GUMAArms_SKN.DDS", "GUMAArms_SKN.tga"),
            ("gumaarms_skn.png", "gumaarms_skn.tga"),
            ("gumaarms_skn.psd", "gumaarms_skn.tga"),
            ("gumaarms_skn", "gumaarms_skn.tga"),
            ("gumaarms_skn.", "gumaarms_skn.tga"),
        ],
    )
    def test_any_extension_reaches_the_tga_entry(
        self, patched: bytearray, name: str, handed_on: str
    ) -> None:
        assert _get(patched, name, set(self.CACHE)) == handed_on

    def test_a_name_the_cache_holds_is_not_rewritten(self, patched: bytearray) -> None:
        assert _get(patched, "authored.dds", set(self.CACHE)) == "authored.dds"

    @pytest.mark.parametrize("name", ["missing.dds", "missing.tga", "missing", "a.b\\missing"])
    def test_a_name_with_no_tga_twin_goes_through_as_written(
        self, patched: bytearray, name: str
    ) -> None:
        assert _get(patched, name, set(self.CACHE)) == name

    def test_a_null_name_goes_through(self, patched: bytearray) -> None:
        assert _get(patched, None, set(self.CACHE)) is None

    def test_an_empty_cache_changes_nothing(self, patched: bytearray) -> None:
        assert _get(patched, "gumaarms_skn.dds", set()) == "gumaarms_skn.dds"

    def test_the_longest_rewritten_name_fits_the_buffer(self, patched: bytearray) -> None:
        stem = "x" * (MAX_NAME_LENGTH - 1)
        assert _get(patched, stem, {stem + ".tga"}) == stem + ".tga"

    def test_a_longer_name_is_left_alone(self, patched: bytearray) -> None:
        stem = "x" * MAX_NAME_LENGTH
        assert _get(patched, stem, {stem + ".tga"}) == stem


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

    def test_the_helpers_are_the_crt_thunks(self, which: str) -> None:
        """`STRLEN` and `STRCPY` are `jmp [import slot]` thunks, six bytes apart."""
        stock = self._stock(which)
        assert _read(stock, STRLEN, 2) == b"\xff\x25"
        assert _read(stock, STRCPY, 2) == b"\xff\x25"

    def test_apply_verify_detect_round_trip(self, which: str) -> None:
        data = bytearray(self._stock(which))
        TextureAnyExtensionPatch().apply(data)
        assert TextureAnyExtensionPatch().verify(data) == []
        assert isinstance(TextureAnyExtensionPatch.detect(data), TextureAnyExtensionPatch)
