"""Tests for the banner-carrier replenish filter patch.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter most
disassemble it back and assert it says what it was meant to say. A wrong byte in a stub does not
raise — it corrupts a ModuleData, or hands the filter evaluator a garbage source player and
silently answers for the wrong side — so encoding errors have to be caught statically.

The other half of the suite is the build fingerprint. This patch reads two things it does not
rewrite (the stock field-parse table, and the frame slot the scan parks the banner's controlling
player in), and both have to fail loudly on anything that is not the expected build.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch import BannerFilterPatch, apply_patches
from sage_patch.patches.banner_filter import (
    FIELD_ENTRY_SIZE,
    FIELD_TABLE_REF_VA,
    FIELD_TABLE_VA,
    FILTER_OFFSET,
    GET_CONTROLLING_PLAYER_VA,
    IS_KIND_OF_VA,
    MODULEDATA_CTOR_CALL_VA,
    MODULEDATA_CTOR_VA,
    MODULEDATA_DTOR_CALL_VA,
    MODULEDATA_DTOR_VA,
    MODULEDATA_SIZE_VA,
    OBJECT_FILTER_CTOR_VA,
    OBJECT_FILTER_DTOR_VA,
    OBJECT_FILTER_IS_DEFINED_VA,
    OBJECT_FILTER_PARSE_VA,
    OBJECT_FILTER_TEST_VA,
    PATCHED_MODULEDATA_SIZE,
    SCAN_KINDOF_CALL_VA,
    SECTION_NAME,
    SOURCE_PLAYER_ANCHOR,
    STOCK_FIELDS,
    STOCK_MODULEDATA_SIZE,
    build_filter,
)
from sage_patch.utils import find_section, va_to_offset

IMAGE_BASE = 0x400000
#: Where the synthetic image parks the field-name strings, past the table that points at them.
STRINGS_VA = 0x00C67000


def _call_bytes(from_va: int, to_va: int) -> bytes:
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


def synthetic_image() -> bytearray:
    """A PE32 image mapping every site this patch asserts, repoints or reads, holding exactly what
    the real ``2.01.2614.37001`` build holds there — so the whole apply + verify path runs in CI
    without the copyrighted `game.dat`, and a patch aimed at a wrong address fails here too."""
    strings = bytearray()
    string_vas: dict[str, int] = {}

    def intern(text: str) -> int:
        if text not in string_vas:
            string_vas[text] = STRINGS_VA + len(strings)
            strings.extend(text.encode("ascii") + b"\x00")
        return string_vas[text]

    name_vas = [intern(name) for name, _off in STOCK_FIELDS]

    highest = STRINGS_VA + len(strings) - IMAGE_BASE + 0x100
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

    write(STRINGS_VA, bytes(strings))

    # The stock 12-entry field-parse table, plus its NULL terminator. `parse` and `userData` are
    # not read by the patch (the entries are copied verbatim), so a recognisable filler stands in.
    table = bytearray()
    for name_va, (_name, offset) in zip(name_vas, STOCK_FIELDS, strict=True):
        table += struct.pack("<4I", name_va, 0x00730000 | offset, 0, offset)
    table += bytes(FIELD_ENTRY_SIZE)
    write(FIELD_TABLE_VA, bytes(table))

    write(MODULEDATA_SIZE_VA, bytes((0x6A, STOCK_MODULEDATA_SIZE)))
    write(MODULEDATA_CTOR_CALL_VA, _call_bytes(MODULEDATA_CTOR_CALL_VA, MODULEDATA_CTOR_VA))
    write(MODULEDATA_DTOR_CALL_VA, _call_bytes(MODULEDATA_DTOR_CALL_VA, MODULEDATA_DTOR_VA))
    write(FIELD_TABLE_REF_VA, struct.pack("<I", FIELD_TABLE_VA))
    write(SCAN_KINDOF_CALL_VA, _call_bytes(SCAN_KINDOF_CALL_VA, IS_KIND_OF_VA))
    write(*SOURCE_PLAYER_ANCHOR)
    return data


@pytest.fixture
def image() -> bytearray:
    return synthetic_image()


def _patched(image: bytearray, **kwargs: object) -> bytearray:
    data = bytearray(image)
    BannerFilterPatch(**kwargs).apply(data)  # type: ignore[arg-type]
    return data


def _cave(data: bytes | bytearray) -> tuple[int, int]:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    section_va, section_off, _vsize = located
    return section_va, section_off


# --- round trip ------------------------------------------------------------------------------


def test_apply_then_verify(image: bytearray) -> None:
    data = _patched(image)
    assert BannerFilterPatch().verify(data) == []


def test_verify_rejects_an_unpatched_image(image: bytearray) -> None:
    problems = BannerFilterPatch().verify(image)
    assert problems and SECTION_NAME in problems[0]


@pytest.mark.parametrize(
    "kwargs",
    [{"keyword": "HordeFilter"}, {"only_when_all": True}, {"keyword": "X", "only_when_all": True}],
)
def test_verify_rejects_other_settings(image: bytearray, kwargs: dict[str, object]) -> None:
    """Verification is settings-specific: a file patched one way must not verify as another."""
    data = _patched(image, **kwargs)
    assert BannerFilterPatch(**kwargs).verify(data) == []  # type: ignore[arg-type]
    assert BannerFilterPatch().verify(data) != []


def test_apply_is_idempotent_only_once(image: bytearray) -> None:
    """A second application must fail rather than double-patch: the size literal is already 0x48
    and `apply_byte_patch` asserts the original bytes."""
    data = _patched(image)
    with pytest.raises(ValueError):
        BannerFilterPatch().apply(data)


# --- the relocated field-parse table ---------------------------------------------------------


def test_table_keeps_the_stock_entries_verbatim(image: bytearray) -> None:
    data = _patched(image)
    section_va, section_off = _cave(data)
    stock_off = va_to_offset(image, FIELD_TABLE_VA)
    assert stock_off is not None
    size = len(STOCK_FIELDS) * FIELD_ENTRY_SIZE
    assert bytes(data[section_off : section_off + size]) == bytes(
        image[stock_off : stock_off + size]
    )

    # ... and the sole reference now points at the copy.
    ref_off = va_to_offset(data, FIELD_TABLE_REF_VA)
    assert ref_off is not None
    assert struct.unpack_from("<I", data, ref_off)[0] == section_va


def test_table_appends_the_new_entry_then_terminates(image: bytearray) -> None:
    data = _patched(image)
    _section_va, section_off = _cave(data)
    at = section_off + len(STOCK_FIELDS) * FIELD_ENTRY_SIZE
    name_va, parse_fn, userdata, offset = struct.unpack_from("<4I", data, at)

    assert parse_fn == OBJECT_FILTER_PARSE_VA
    assert userdata == 0
    assert offset == FILTER_OFFSET

    name_off = va_to_offset(data, name_va)
    assert name_off is not None
    assert bytes(data[name_off : name_off + 16]).split(b"\x00")[0] == b"ReplenishFilter"

    terminator = bytes(data[at + FIELD_ENTRY_SIZE : at + 2 * FIELD_ENTRY_SIZE])
    assert terminator == bytes(FIELD_ENTRY_SIZE)


def test_the_new_field_sits_past_the_stock_structure(image: bytearray) -> None:
    """The field must land at the old end of a fully packed structure, and the allocation must
    grow by exactly its four bytes."""
    assert FILTER_OFFSET == STOCK_MODULEDATA_SIZE
    assert PATCHED_MODULEDATA_SIZE == STOCK_MODULEDATA_SIZE + 4
    assert max(off for _name, off in STOCK_FIELDS) < FILTER_OFFSET

    data = _patched(image)
    off = va_to_offset(data, MODULEDATA_SIZE_VA)
    assert off is not None
    assert bytes(data[off : off + 2]) == bytes((0x6A, PATCHED_MODULEDATA_SIZE))


def test_ini_surface_reports_the_new_field(image: bytearray) -> None:
    surface = BannerFilterPatch(keyword="ReplenishTargetFilter").ini_surface()
    assert [(f.block, f.name, f.type) for f in surface.fields] == [
        ("BannerCarrierUpdate", "ReplenishTargetFilter", "ObjectFilter")
    ]


def test_the_ini_surface_actually_applies_to_the_model() -> None:
    """A field the model cannot take is a declaration that silently does nothing - the surface
    has to land on `BannerCarrierUpdate` itself, not just parse."""
    with BannerFilterPatch().ini_surface().activate() as problems:
        assert problems == []


def test_only_when_all_is_not_part_of_the_ini_surface() -> None:
    """It changes when the scan consults the filter, not whether the keyword parses."""
    assert BannerFilterPatch(only_when_all=True).ini_surface() == BannerFilterPatch().ini_surface()


# --- the build fingerprint -------------------------------------------------------------------


def test_a_renamed_field_is_rejected(image: bytearray) -> None:
    """The table fingerprint checks names, not just shape."""
    off = va_to_offset(image, STRINGS_VA)
    assert off is not None
    image[off : off + len(b"IdleSpawnRate")] = b"IdleSpawnRatX"
    with pytest.raises(ValueError, match="field table entry 0"):
        BannerFilterPatch().apply(image)


def test_a_moved_field_is_rejected(image: bytearray) -> None:
    """... and offsets, so a build that repacks the structure cannot slip through."""
    off = va_to_offset(image, FIELD_TABLE_VA)
    assert off is not None
    struct.pack_into("<I", image, off + 12, 0x99)  # IdleSpawnRate's ModuleData offset
    with pytest.raises(ValueError, match="expected offset"):
        BannerFilterPatch().apply(image)


def test_an_unterminated_table_is_rejected(image: bytearray) -> None:
    off = va_to_offset(image, FIELD_TABLE_VA)
    assert off is not None
    at = off + len(STOCK_FIELDS) * FIELD_ENTRY_SIZE
    struct.pack_into("<I", image, at, 0xDEADBEEF)
    with pytest.raises(ValueError, match="NULL-terminated"):
        BannerFilterPatch().apply(image)


def test_a_moved_source_player_slot_is_rejected(image: bytearray) -> None:
    """The one site the patch reads but never rewrites. Nothing else would catch a mismatch: the
    cave would just hand the evaluator whatever the frame slot happened to hold."""
    va, _expected = SOURCE_PLAYER_ANCHOR
    off = va_to_offset(image, va)
    assert off is not None
    image[off : off + 3] = b"\x89\x45\xd8"  # mov [ebp-0x28], eax
    with pytest.raises(ValueError, match="source-player store"):
        BannerFilterPatch().apply(image)


def test_verify_reports_a_moved_source_player_slot(image: bytearray) -> None:
    data = _patched(image)
    va, _expected = SOURCE_PLAYER_ANCHOR
    off = va_to_offset(data, va)
    assert off is not None
    data[off : off + 3] = b"\x89\x45\xd8"
    problems = BannerFilterPatch().verify(data)
    assert any("source-player store" in problem for problem in problems)


# --- keyword validation ----------------------------------------------------------------------


@pytest.mark.parametrize("keyword", ["", " ", "Has Space", "Trailing ", "nonasciié"])
def test_rejects_malformed_keywords(keyword: str) -> None:
    with pytest.raises(ValueError):
        BannerFilterPatch(keyword=keyword)


@pytest.mark.parametrize("keyword", ["ScanHordeDistance", "replenishnearbyhorde"])
def test_rejects_a_keyword_that_already_exists(keyword: str) -> None:
    """A duplicate name would be shadowed by the stock entry the linear scan reaches first."""
    with pytest.raises(ValueError, match="already a BannerCarrierUpdate field"):
        BannerFilterPatch(keyword=keyword)


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


def _stub_start(data: bytes | bytearray, section_va: int, section_off: int) -> tuple[int, int]:
    """Where the three code stubs begin: past the table and the dword-padded keyword string."""
    table = (len(STOCK_FIELDS) + 2) * FIELD_ENTRY_SIZE
    blob = len(b"ReplenishFilter\x00")
    blob += -blob % 4
    return section_va + table + blob, section_off + table + blob


def test_ctor_stub_runs_the_stock_ctor_then_builds_the_handle(image: bytearray) -> None:
    data = _patched(image)
    section_va, section_off = _cave(data)
    va, off = _stub_start(data, section_va, section_off)
    assert _disassemble(data, va, off, 6) == [
        f"call 0x{MODULEDATA_CTOR_VA:x}",
        "push eax",
        f"lea ecx, [eax + 0x{FILTER_OFFSET:x}]",
        f"call 0x{OBJECT_FILTER_CTOR_VA:x}",
        "pop eax",
        "ret",
    ]


def test_dtor_stub_runs_the_stock_dtor_then_releases_the_handle(image: bytearray) -> None:
    data = _patched(image)
    section_va, section_off = _cave(data)
    va, off = _stub_start(data, section_va, section_off)
    va, off = va + 16, off + 16  # past the ctor stub
    assert _disassemble(data, va, off, 5) == [
        "push ecx",
        f"call 0x{MODULEDATA_DTOR_VA:x}",
        "pop ecx",
        f"add ecx, 0x{FILTER_OFFSET:x}",
        f"jmp 0x{OBJECT_FILTER_DTOR_VA:x}",
    ]


def test_filter_stub_calls_the_evaluator_not_the_wrapper(image: bytearray) -> None:
    """The whole point of the three-argument form: the wrapper at 0x007640C1 passes a null source
    player, which makes every relationship token — `SAME_PLAYER` above all — return false."""
    data = _patched(image)
    section_va, section_off = _cave(data)
    va, off = _stub_start(data, section_va, section_off)
    va, off = va + 31, off + 31  # past the ctor and dtor stubs
    text = _disassemble(data, va, off, 20)

    assert text[:5] == [
        "push ecx",
        f"lea ecx, [edi + 0x{FILTER_OFFSET:x}]",
        f"call 0x{OBJECT_FILTER_IS_DEFINED_VA:x}",
        "test al, al",
        f"je 0x{va + 0x3B:x}",
    ]
    # The three arguments, pushed right-to-left: source player, candidate's player, template.
    assert text[5:13] == [
        "push dword ptr [ebp - 0x20]",
        "mov ecx, dword ptr [esp + 4]",
        f"call 0x{GET_CONTROLLING_PLAYER_VA:x}",
        "push eax",
        "mov ecx, dword ptr [esp + 8]",
        "push dword ptr [ecx + 4]",
        f"lea ecx, [edi + 0x{FILTER_OFFSET:x}]",
        f"call 0x{OBJECT_FILTER_TEST_VA:x}",
    ]
    # Reject reports "immobile" and cleans isKindOf's one argument; everything else tail-calls it.
    assert text[13:] == [
        "test al, al",
        f"jne 0x{va + 0x3B:x}",
        "pop ecx",
        "mov al, 1",
        "ret 4",
        "pop ecx",
        f"jmp 0x{IS_KIND_OF_VA:x}",
    ]


def test_only_when_all_gates_on_the_replenish_all_flag(image: bytearray) -> None:
    data = _patched(image, only_when_all=True)
    section_va, section_off = _cave(data)
    va, off = _stub_start(data, section_va, section_off)
    va, off = va + 31, off + 31
    text = _disassemble(data, va, off, 3)
    assert text[0] == "cmp byte ptr [edi + 0x39], 0"
    assert text[1].startswith("je ")
    assert text[2] == "push ecx"


def test_only_when_all_jumps_past_the_saved_candidate(image: bytearray) -> None:
    """The gate fires before the candidate is pushed, so it must land on the tail-call directly —
    jumping to the `pop ecx` shared with the filter paths would unbalance the stack."""
    section_va = 0x00F00000
    code = build_filter(section_va, only_when_all=True)
    text = _disassemble(code, section_va, 0, 32)
    gate_target = int(text[1].split()[1], 16)
    # The last two instructions are `pop ecx` then the tail-call; the gate must skip the pop.
    assert text[-2:] == ["pop ecx", f"jmp 0x{IS_KIND_OF_VA:x}"]
    assert gate_target == section_va + len(code) - 5


# --- composition -----------------------------------------------------------------------------


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
    assert count == 2


def test_apply_patches_round_trip(tmp_path, image: bytearray) -> None:
    src = tmp_path / "game.dat"
    src.write_bytes(bytes(image))
    out = tmp_path / "patched.dat"
    patch = BannerFilterPatch(keyword="HordeFilter")
    apply_patches(src, [patch], output=out)

    assert src.read_bytes() == bytes(image)  # the input is never modified
    assert patch.verify(out.read_bytes()) == []


class TestDetect:
    """**The gate on parameter recovery.** `verify` only answers "does this file carry *these*
    settings", so the framework's default probe - which builds the patch with its defaults -
    reports a binary patched under any other keyword as unpatched. That is the case detection
    exists for: a `game.dat` somebody else patched, whose keyword is what a reader cannot know."""

    def test_it_recovers_a_non_default_keyword(self, image: bytearray):
        data = _patched(image, keyword="HordeFilter")
        found = BannerFilterPatch.detect(data)
        assert found is not None, "a patch applied under another keyword reports as absent"
        assert found.keyword == "HordeFilter"
        assert found.only_when_all is False

    @pytest.mark.parametrize("only_when_all", [False, True], ids=["both-modes", "only-when-all"])
    def test_it_recovers_the_scope(self, image: bytearray, only_when_all: bool):
        data = _patched(image, keyword="HordeFilter", only_when_all=only_when_all)
        found = BannerFilterPatch.detect(data)
        assert found is not None
        assert found.only_when_all is only_when_all

    def test_the_recovered_patch_verifies_against_the_binary_it_came_from(self, image: bytearray):
        data = _patched(image, keyword="HordeFilter", only_when_all=True)
        assert BannerFilterPatch.detect(data).verify(data) == []

    def test_an_unpatched_image_carries_nothing(self, image: bytearray):
        assert BannerFilterPatch.detect(image) is None

    def test_detection_never_raises_on_something_that_is_not_a_game_dat(self):
        assert BannerFilterPatch.detect(bytearray(b"MZ" + bytes(4096))) is None
