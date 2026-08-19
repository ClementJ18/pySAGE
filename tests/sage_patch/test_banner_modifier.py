"""Tests for `banner-modifier`, which gives a horde an `AttributeModifier` when its banner
carrier dies and takes it back when the horde is re-bannered.

Four things can go wrong here and none of them raises on its own.

The first is the **offset**. `HordeContainModuleData` is a base class: `AODHordeContainModuleData`
derives from it and puts thirteen fields where a naively appended one would land. The new field's
offset therefore has to be past *both* layouts, and all three `newModuleData` allocations have to
grow to the same size - a patch that grew two of the three would corrupt the third class's last
field the moment the keyword was written. Every one of those relationships is asserted here rather
than trusted to the constant.

The second is the **stack contract**. Two of the rewritten sites are `call`s the stock code never
made, and one replaces a `call` whose callee cleans twelve argument bytes. The apply stub has to
`ret` with `edx` intact (the caller's very next instruction pushes it) and the restore stub has to
*tail-jump* to the installer it displaced so that installer's `ret 0xc` cleans the original frame.
Both are checked by disassembling the cave back.

The third is the **displaced bytes**. Three hooks overwrite instructions the stock code still
needs, so each stub has to carry them verbatim; a hook that dropped one would silently stop
zeroing a field, stop releasing a string, or stop clearing the banner slot.

The fourth is the **build fingerprint**. The patch relocates a 43-entry field-parse table and
refuses to run against a table that is not the one it read.
"""

from __future__ import annotations

import struct

import pytest

from sage_ini.model.behaviors import AODHordeContain, HordeContain, HorseHordeContain
from sage_patch import apply_patches
from sage_patch.patches.banner_modifier import (
    APPLY_TO_MEMBERS,
    ASCII_STRING_DTOR,
    ASCII_STRING_PARSE_VA,
    BANNER_DIED_BYTES,
    BANNER_DIED_VA,
    BANNER_INSTALLED_VA,
    BANNER_INSTALLER,
    CONTAIN_SUBOBJECT_OFFSET,
    CTOR_TAIL_BYTES,
    CTOR_TAIL_VA,
    DEFAULT_KEYWORD,
    DTOR_STRING_BYTES,
    DTOR_STRING_VA,
    FIELD_ENTRY_SIZE,
    FIELD_TABLE_REF_VA,
    FIELD_TABLE_VA,
    KEYWORD_OFFSET,
    MODIFIER_OFFSET,
    PATCHED_MODULEDATA_SIZE,
    REMOVE_FROM_MEMBERS,
    SECTION_NAME,
    SIZE_SITES,
    STOCK_FIELDS,
    BannerModifierPatch,
)
from sage_patch.utils import append_section, find_section, next_section_rva, va_to_offset

from .synthetic import IMAGE_BASE, _sparse_image

#: Where the stand-in parks the 43 field-name strings the patch fingerprints.
STRINGS_VA = 0x00DA4000


def _call_bytes(from_va: int, to_va: int) -> bytes:
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


def _planted_strings() -> dict[int, bytes]:
    """One entry per field name, laid out from :data:`STRINGS_VA` without straddling a page - the
    sparse image maps a page at a time and the names do not fit in one."""
    planted: dict[int, bytes] = {}
    va = STRINGS_VA
    for name, _offset in STOCK_FIELDS:
        blob = name.encode("ascii") + b"\x00"
        if (va & 0xFFF) + len(blob) > 0x1000:
            va = (va & ~0xFFF) + 0x1000
        planted[va] = blob
        va += len(blob)
    return planted


def synthetic_image() -> bytearray:
    """A stand-in mapping only the pages this patch reads or rewrites.

    Its sites run from `newModuleData` at ``0x0064B61C`` to the field-parse table in `.rdata` at
    ``0x00C5BB50``, six megabytes apart, so a sparse image is a handful of KB where a flat one
    would be that whole span. The stock table is planted in full - names, parse functions and
    offsets - because the patch refuses to run against a table that is not the one it read, and
    that refusal is the check worth having.
    """
    strings = _planted_strings()

    table = bytearray()
    for name_va, (_name, offset) in zip(strings, STOCK_FIELDS, strict=True):
        # `parse` and `userData` are copied verbatim by the patch and never read, so a
        # recognisable filler stands in for the real parser addresses.
        table += struct.pack("<4I", name_va, 0x00420000 | offset, 0, offset)
    table += bytes(FIELD_ENTRY_SIZE)  # the NULL terminator

    planted: dict[int, bytes] = dict(strings)
    planted[FIELD_TABLE_VA] = bytes(table)
    planted[FIELD_TABLE_REF_VA - 1] = b"\x68" + struct.pack("<I", FIELD_TABLE_VA)
    for va, stock_size, _owner in SIZE_SITES:
        planted[va] = b"\x68" + struct.pack("<I", stock_size)
    planted[CTOR_TAIL_VA] = CTOR_TAIL_BYTES
    planted[DTOR_STRING_VA] = DTOR_STRING_BYTES
    planted[BANNER_DIED_VA] = BANNER_DIED_BYTES
    planted[BANNER_INSTALLED_VA] = _call_bytes(BANNER_INSTALLED_VA, BANNER_INSTALLER)
    return _sparse_image(planted)


@pytest.fixture
def image() -> bytearray:
    return synthetic_image()


def _patched(image: bytearray, **kwargs: object) -> bytearray:
    data = bytearray(image)
    BannerModifierPatch(**kwargs).apply(data)  # type: ignore[arg-type]
    return data


def _cave(data: bytes | bytearray) -> tuple[int, int, int]:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    return located


def _read(data: bytes | bytearray, va: int, size: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None
    return bytes(data[off : off + size])


def _call_target(data: bytes | bytearray, va: int) -> int:
    """Where the `call`/`jmp rel32` at ``va`` goes."""
    return va + 5 + struct.unpack("<i", _read(data, va, 5)[1:])[0]


# --- round trip ---------------------------------------------------------------------------------


def test_apply_then_verify(image: bytearray) -> None:
    assert BannerModifierPatch().verify(_patched(image)) == []


def test_verify_rejects_an_unpatched_image(image: bytearray) -> None:
    problems = BannerModifierPatch().verify(image)
    assert problems and SECTION_NAME in problems[0]


@pytest.mark.parametrize(
    "kwargs", [{"keyword": "BannerLossModifier"}, {"restore": False}, {"keyword": "X"}]
)
def test_verify_rejects_other_settings(image: bytearray, kwargs: dict[str, object]) -> None:
    """Verification is settings-specific: a file patched one way must not verify as another."""
    data = _patched(image, **kwargs)
    assert BannerModifierPatch(**kwargs).verify(data) == []  # type: ignore[arg-type]
    assert BannerModifierPatch().verify(data) != []


@pytest.mark.parametrize("kwargs", [{}, {"keyword": "BannerLossModifier"}, {"restore": False}])
def test_detect_recovers_the_settings(image: bytearray, kwargs: dict[str, object]) -> None:
    data = _patched(image, **kwargs)
    found = BannerModifierPatch.detect(data)
    assert found is not None
    assert found.keyword == kwargs.get("keyword", DEFAULT_KEYWORD)
    assert found.restore == kwargs.get("restore", True)
    assert BannerModifierPatch.detect(image) is None


def test_apply_is_idempotent_only_once(image: bytearray) -> None:
    """A second application must fail rather than double-patch: the size literals already read
    0x2d0 and `apply_byte_patch` asserts the original bytes."""
    data = _patched(image)
    with pytest.raises(ValueError):
        BannerModifierPatch().apply(data)


def test_apply_patches_writes_a_file(image: bytearray, tmp_path) -> None:
    src, out = tmp_path / "game.dat.backup", tmp_path / "game.dat"
    src.write_bytes(bytes(image))
    apply_patches(src, [BannerModifierPatch()], output=out)
    assert BannerModifierPatch().verify(out.read_bytes()) == []
    assert src.read_bytes() == bytes(image)  # the input is never modified


def test_the_patch_is_attributed() -> None:
    assert BannerModifierPatch.author


# --- the field offset, which is the whole reason this patch is not a one-liner -------------------


def test_the_field_lands_past_every_class_in_the_family() -> None:
    """`AODHordeContainModuleData` derives from `HordeContainModuleData` and fills the base's old
    end with its own fields, so the new field has to sit past the *largest* class in the family -
    which is what makes one offset correct in the code all three share."""
    stock_sizes = {size for _va, size, _owner in SIZE_SITES}
    assert MODIFIER_OFFSET >= max(stock_sizes)
    assert PATCHED_MODULEDATA_SIZE == MODIFIER_OFFSET + 4
    assert PATCHED_MODULEDATA_SIZE > max(stock_sizes)


def test_every_allocation_in_the_family_grows(image: bytearray) -> None:
    """All three, to the same size. Growing two of the three would leave the third writing the
    new field past the end of its allocation."""
    data = _patched(image)
    for va, stock_size, owner in SIZE_SITES:
        assert _read(image, va, 5) == b"\x68" + struct.pack("<I", stock_size), owner
        assert _read(data, va, 5) == b"\x68" + struct.pack("<I", PATCHED_MODULEDATA_SIZE), owner


def test_the_three_allocations_are_distinct_sites() -> None:
    """Two of them are `HordeContain` and `HorseHordeContain`, which allocate the same size at
    different addresses - so the sites cannot be deduplicated by their literal."""
    assert len({va for va, _size, _owner in SIZE_SITES}) == len(SIZE_SITES)


# --- the relocated field-parse table -------------------------------------------------------------


def test_table_keeps_the_stock_entries_verbatim(image: bytearray) -> None:
    data = _patched(image)
    section_va, section_off, _vsize = _cave(data)
    stock_off = va_to_offset(image, FIELD_TABLE_VA)
    assert stock_off is not None
    size = len(STOCK_FIELDS) * FIELD_ENTRY_SIZE
    assert bytes(data[section_off : section_off + size]) == bytes(
        image[stock_off : stock_off + size]
    )

    # ... and the sole reference now points at the copy.
    assert struct.unpack("<I", _read(data, FIELD_TABLE_REF_VA, 4))[0] == section_va


def test_table_appends_the_new_entry_then_terminates(image: bytearray) -> None:
    data = _patched(image)
    _section_va, section_off, _vsize = _cave(data)
    at = section_off + len(STOCK_FIELDS) * FIELD_ENTRY_SIZE
    name_va, parse_fn, userdata, offset = struct.unpack_from("<4I", data, at)

    assert parse_fn == ASCII_STRING_PARSE_VA
    assert userdata == 0
    assert offset == MODIFIER_OFFSET

    name_off = va_to_offset(data, name_va)
    assert name_off is not None
    assert bytes(data[name_off : name_off + 64]).split(b"\x00")[0] == DEFAULT_KEYWORD.encode()

    terminator = bytes(data[at + FIELD_ENTRY_SIZE : at + 2 * FIELD_ENTRY_SIZE])
    assert terminator == bytes(FIELD_ENTRY_SIZE)


def test_the_keyword_sits_where_detect_reads_it(image: bytearray) -> None:
    data = _patched(image, keyword="BannerLossModifier")
    section_va, _off, _vsize = _cave(data)
    assert _read(data, section_va + KEYWORD_OFFSET, 19) == b"BannerLossModifier\x00"


@pytest.mark.parametrize(
    ("index", "corruption"),
    [(12, "name"), (12, "offset"), (42, "name")],
)
def test_apply_refuses_a_table_that_is_not_this_build(
    image: bytearray, index: int, corruption: str
) -> None:
    """The fingerprint is all 43 names *and* offsets, which is what makes it a build check rather
    than a shape check."""
    data = bytearray(image)
    entry = va_to_offset(data, FIELD_TABLE_VA + index * FIELD_ENTRY_SIZE)
    assert entry is not None
    if corruption == "offset":
        struct.pack_into("<I", data, entry + 12, 0x999)
    else:
        name_va = struct.unpack_from("<I", data, entry)[0]
        name_off = va_to_offset(data, name_va)
        assert name_off is not None
        data[name_off] = ord("Z")
    with pytest.raises(ValueError):
        BannerModifierPatch().apply(data)


def test_apply_refuses_a_table_that_does_not_terminate(image: bytearray) -> None:
    data = bytearray(image)
    end = va_to_offset(data, FIELD_TABLE_VA + len(STOCK_FIELDS) * FIELD_ENTRY_SIZE)
    assert end is not None
    struct.pack_into("<I", data, end, 0x00DA4000)
    with pytest.raises(ValueError):
        BannerModifierPatch().apply(data)


# --- the hooks -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("va", "stock", "padding"),
    [
        (CTOR_TAIL_VA, CTOR_TAIL_BYTES, 1),
        (DTOR_STRING_VA, DTOR_STRING_BYTES, 5),
        (BANNER_DIED_VA, BANNER_DIED_BYTES, 2),
    ],
)
def test_each_displaced_site_becomes_a_call_into_the_cave(
    image: bytearray, va: int, stock: bytes, padding: int
) -> None:
    data = _patched(image)
    section_va, _off, vsize = _cave(data)
    target = _call_target(data, va)
    assert section_va <= target < section_va + vsize
    assert _read(data, va + 5, padding) == b"\x90" * padding


@pytest.mark.parametrize(
    ("va", "stock"),
    [(CTOR_TAIL_VA, CTOR_TAIL_BYTES), (DTOR_STRING_VA, DTOR_STRING_BYTES)],
)
def test_the_displaced_instructions_survive_in_the_cave(
    image: bytearray, va: int, stock: bytes
) -> None:
    """A hook that dropped what it overwrote would stop zeroing a field or stop releasing a
    string, and nothing would say so."""
    data = _patched(image)
    _section_va, off, vsize = _cave(data)
    assert stock in bytes(data[off : off + vsize])


def test_the_death_hook_still_clears_the_banner_slot(image: bytearray) -> None:
    data = _patched(image)
    _section_va, off, vsize = _cave(data)
    assert bytes(data[off : off + vsize]).count(BANNER_DIED_BYTES) == 1


def test_the_install_hook_is_the_only_repointed_call(image: bytearray) -> None:
    """The stock `call` at the install site goes to the installer; patched, it goes to the cave,
    and the cave goes back to the installer."""
    assert _call_target(image, BANNER_INSTALLED_VA) == BANNER_INSTALLER
    data = _patched(image)
    section_va, _off, vsize = _cave(data)
    stub = _call_target(data, BANNER_INSTALLED_VA)
    assert section_va <= stub < section_va + vsize


def test_no_restore_leaves_the_install_site_alone(image: bytearray) -> None:
    data = _patched(image, restore=False)
    assert _call_target(data, BANNER_INSTALLED_VA) == BANNER_INSTALLER
    assert BannerModifierPatch(restore=False).verify(data) == []


def test_no_restore_omits_the_stub_rather_than_stranding_it(image: bytearray) -> None:
    """The removal stub is emitted last, so declining it shortens the cave instead of leaving
    unreachable code in the image."""
    with_restore = _cave(_patched(image))[2]
    without = _cave(_patched(image, restore=False))[2]
    assert without < with_restore


# --- what the cave actually does -----------------------------------------------------------------


def _disassembled(data: bytes | bytearray) -> list:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    section_va, off, vsize = _cave(data)
    start = _cave_code_offset(data)
    code = bytes(data[off + start : off + vsize])
    return list(md.disasm(code, section_va + start))


def _cave_code_offset(data: bytes | bytearray) -> int:
    """Where the stubs begin: past the relocated table and the dword-padded keyword."""
    section_va, _off, _vsize = _cave(data)
    keyword = _read(data, section_va + KEYWORD_OFFSET, 64).split(b"\x00")[0]
    return KEYWORD_OFFSET + (len(keyword) + 4) // 4 * 4


def test_the_cave_disassembles_cleanly_to_its_end(image: bytearray) -> None:
    """A mistyped opcode does not raise - it desynchronises, and the tail decodes as garbage. So
    the whole body has to decode, and the last instruction has to be one that leaves."""
    data = _patched(image)
    _va, _off, vsize = _cave(data)
    body = vsize - _cave_code_offset(data)
    instructions = _disassembled(data)
    assert sum(ins.size for ins in instructions) == body
    assert instructions[-1].mnemonic == "jmp"  # the restore stub's tail call


def test_the_cave_calls_the_engines_own_apply_and_remove(image: bytearray) -> None:
    """Both routines are `HordeContain`'s own - the ones behind the stock `AttributeModifiers`
    keyword - so the patch inherits their idea of what a horde's members are."""
    targets = {
        int(ins.op_str, 16)
        for ins in _disassembled(_patched(image))
        if ins.mnemonic in {"call", "jmp"} and ins.op_str.startswith("0x")
    }
    assert {APPLY_TO_MEMBERS, REMOVE_FROM_MEMBERS, ASCII_STRING_DTOR, BANNER_INSTALLER} <= targets


def test_the_apply_stub_asks_for_the_blocks_own_duration(image: bytearray) -> None:
    """`push -1` is what makes the `ModifierList`'s `Duration` govern how long the effect lasts;
    `push 0` beside it is the (absent) `ObjectFilter`. A literal frame count here would bake the
    patch's opinion into the binary."""
    pushes = [ins.op_str for ins in _disassembled(_patched(image)) if ins.mnemonic == "push"]
    assert "-1" in pushes


def test_the_apply_stub_preserves_edx(image: bytearray) -> None:
    """The caller's very next instruction pushes `edx` (the dying object) as an argument, and the
    stock code makes no call between the two - so the stub's own call would eat it."""
    body = _disassembled(_patched(image))
    saves = [i for i, ins in enumerate(body) if ins.mnemonic == "push" and ins.op_str == "edx"]
    restores = [i for i, ins in enumerate(body) if ins.mnemonic == "pop" and ins.op_str == "edx"]
    assert saves and restores and saves[0] < restores[0]


def test_the_restore_stub_tail_jumps_to_the_installer(image: bytearray) -> None:
    """It replaces a `call` to a callee that cleans twelve argument bytes. Returning to the stub
    and then calling would leave those arguments pushed twice; the tail jump lets the installer's
    own `ret 0xc` clean the original frame."""
    body = _disassembled(_patched(image))
    assert body[-1].mnemonic == "jmp"
    assert int(body[-1].op_str, 16) == BANNER_INSTALLER


@pytest.mark.parametrize("offset", [MODIFIER_OFFSET, CONTAIN_SUBOBJECT_OFFSET])
def test_the_cave_uses_the_documented_offsets(image: bytearray, offset: int) -> None:
    accesses = [ins for ins in _disassembled(_patched(image)) if f"0x{offset:x}]" in ins.op_str]
    assert accesses, f"the cave never touches +0x{offset:x}"


def test_the_cave_touches_no_stock_field_it_has_no_business_with(image: bytearray) -> None:
    """Every stock offset is in use by a field of one of the three classes, and the cave has
    business with exactly two of them.

    `LivingWorldOverloadTemplate` at ``0x280`` is the one whose constructor store and destructor
    call the hooks displaced, so both appear verbatim. ``0x26C`` is a **coincidence worth
    stating**: on the `ModuleData` it is `FlankedDuration`, but the instruction the cave carries
    is the death arm's ``and dword [esi+0x26c], 0``, which clears the banner slot on the *module
    instance* - a different structure that happens to put something at the same offset."""
    expected = {0x280, 0x26C}
    touched = {
        offset
        for _name, offset in STOCK_FIELDS
        if any(f"0x{offset:x}]" in ins.op_str for ins in _disassembled(_patched(image)))
    }
    assert touched == expected


# --- the INI surface -----------------------------------------------------------------------------


def test_ini_surface_adds_one_reference_field() -> None:
    surface = BannerModifierPatch().ini_surface()
    assert len(surface.fields) == 1
    field = surface.fields[0]
    assert field.block == "HordeContain"
    assert field.name == DEFAULT_KEYWORD
    assert field.type == "Ref:modifiers"
    assert field.default is None  # absent == stock


def test_ini_surface_follows_the_keyword() -> None:
    assert BannerModifierPatch(keyword="Shaken").ini_surface().fields[0].name == "Shaken"


def test_ini_surface_reaches_the_derived_contains() -> None:
    """`HorseHordeContain` and `AODHordeContain` inherit the field in the model the same way they
    inherit it in the engine, where `buildFieldParse` chains to `HordeContain`'s.

    The surface is applied to the live model here; the suite's autouse fixture reverts it."""
    assert BannerModifierPatch().ini_surface().apply() == []
    for cls in (HordeContain, HorseHordeContain, AODHordeContain):
        assert DEFAULT_KEYWORD in cls._fieldspec, cls.__name__


# --- the keyword ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "keyword",
    ["", " ", "Two Words", "Trailing ", "BannerCarrierDestroyHordeOnDeath", "attributemodifiers"],
)
def test_bad_keywords_are_refused(keyword: str) -> None:
    """Empty, padded, spaced - and a name the module already has, in any case, which would shadow
    a stock field in a table the engine scans linearly."""
    with pytest.raises(ValueError):
        BannerModifierPatch(keyword)


# --- composition ---------------------------------------------------------------------------------


def test_the_cave_lands_past_a_section_another_patch_appended(image: bytearray) -> None:
    """The composition contract: the cave is allocated past every existing section and found again
    by name, so the patch does not care whether it ran first."""
    data = bytearray(image)
    foreign = next_section_rva(data)
    append_section(data, ".other", foreign, b"\x90" * 0x40, 0x60000060)
    BannerModifierPatch().apply(data)
    assert BannerModifierPatch().verify(data) == []

    section_va, _off, _vsize = _cave(data)
    assert section_va > IMAGE_BASE + foreign
    assert find_section(data, ".other") is not None
