"""Tests for the `PlayerHealSpecialPower` filter patch.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter most
disassemble it back and assert it says what it was meant to say. A wrong byte in a stub does not
raise - it corrupts a ModuleData, or hands the filter evaluator a garbage source player and
silently answers for the wrong side - so encoding errors have to be caught statically.

The other half of the suite is the build fingerprint. This patch reads three things it does not
rewrite (its own field-parse table, the inherited `SpecialAbilityUpdate` one, and the register
allocation of the per-candidate heal routine), and all three have to fail loudly on anything that
is not the expected build.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch import PlayerHealFilterPatch, apply_patches
from sage_patch.patches.player_heal_filter import (
    FIELD_ENTRY_SIZE,
    FIELD_TABLE_REF_VA,
    FIELD_TABLE_VA,
    FILTER_OFFSET,
    GET_CONTROLLING_PLAYER_VA,
    HEAL_KINDOF_CALL_VA,
    INHERITED_FIELD_COUNT,
    INHERITED_FIELD_TABLE_VA,
    KIND_OF_MATCHES_VA,
    MODULEDATA_CTOR_CALL_VA,
    MODULEDATA_CTOR_VA,
    MODULEDATA_SIZE_VA,
    OBJECT_FILTER_CTOR_VA,
    OBJECT_FILTER_IS_DEFINED_VA,
    OBJECT_FILTER_PARSE_VA,
    OBJECT_FILTER_TEST_VA,
    PATCHED_MODULEDATA_SIZE,
    REGISTER_ANCHORS,
    SECTION_NAME,
    STOCK_FIELDS,
    STOCK_MODULEDATA_SIZE,
    build_ctor,
)
from sage_patch.utils import find_section, va_to_offset

IMAGE_BASE = 0x400000
#: Where the synthetic image parks the field-name strings, past both tables that point at them.
STRINGS_VA = 0x00C76000

#: `SpecialAbilityUpdate`'s 35 keywords, in table order - the names this module inherits and must
#: not collide with. Only the names matter here, so the offsets are not restated.
INHERITED_NAMES = (
    "SpecialPowerTemplate",
    "UpdateModuleStartsAttack",
    "StartsPaused",
    "InitiateSound",
    "ReEnableAntiCategory",
    "AntiCategory",
    "AntiFX",
    "AttributeModifier",
    "AttributeModifierRange",
    "AttributeModifierAffectsSelf",
    "AttributeModifierAffects",
    "AttributeModifierFX",
    "AttributeModifierWeatherBased",
    "WeatherDuration",
    "RequirementsFilterMPSkirmish",
    "RequirementsFilterStrategic",
    "TargetEnemy",
    "TargetAllSides",
    "InitiateFX",
    "TriggerFX",
    "SetModelCondition",
    "SetModelConditionTime",
    "GiveLevels",
    "DisableDuringAnimDuration",
    "IdleWhenStartingPower",
    "AffectGood",
    "AffectEvil",
    "AffectAllies",
    "AvailableAtStart",
    "ChangeWeather",
    "AdjustVictim",
    "OnTriggerRechargeSpecialPower",
    "BurnDecayModifier",
    "UseDistanceFromCommandCenter",
    "DistanceFromCommandCenter",
)


def _call_bytes(from_va: int, to_va: int) -> bytes:
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


def synthetic_image() -> bytearray:
    """A PE32 image mapping every site this patch asserts, repoints or reads, holding exactly what
    the real ``2.01.2614.37001`` build holds there - so the whole apply + verify path runs in CI
    without the copyrighted `game.dat`, and a patch aimed at a wrong address fails here too."""
    strings = bytearray()
    string_vas: dict[str, int] = {}

    def intern(text: str) -> int:
        if text not in string_vas:
            string_vas[text] = STRINGS_VA + len(strings)
            strings.extend(text.encode("ascii") + b"\x00")
        return string_vas[text]

    name_vas = [intern(name) for name, _off in STOCK_FIELDS]
    inherited_vas = [intern(name) for name in INHERITED_NAMES]

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

    # The stock six-entry field-parse table, plus its NULL terminator. `parse` and `userData` are
    # not read by the patch (the entries are copied verbatim), so a recognisable filler stands in.
    table = bytearray()
    for name_va, (_name, offset) in zip(name_vas, STOCK_FIELDS, strict=True):
        table += struct.pack("<4I", name_va, 0x00730000 | offset, 0, offset)
    table += bytes(FIELD_ENTRY_SIZE)
    write(FIELD_TABLE_VA, bytes(table))

    # The inherited table, read only for its names.
    inherited = bytearray()
    for index, name_va in enumerate(inherited_vas):
        inherited += struct.pack("<4I", name_va, 0x00890000 | index, 0, 8 + index * 4)
    inherited += bytes(FIELD_ENTRY_SIZE)
    write(INHERITED_FIELD_TABLE_VA, bytes(inherited))

    write(MODULEDATA_SIZE_VA, b"\x68" + struct.pack("<I", STOCK_MODULEDATA_SIZE))
    write(MODULEDATA_CTOR_CALL_VA, _call_bytes(MODULEDATA_CTOR_CALL_VA, MODULEDATA_CTOR_VA))
    write(FIELD_TABLE_REF_VA, struct.pack("<I", FIELD_TABLE_VA))
    write(HEAL_KINDOF_CALL_VA, _call_bytes(HEAL_KINDOF_CALL_VA, KIND_OF_MATCHES_VA))
    for va, expected, _what in REGISTER_ANCHORS:
        write(va, expected)
    return data


@pytest.fixture
def image() -> bytearray:
    return synthetic_image()


def _patched(image: bytearray, **kwargs: object) -> bytearray:
    data = bytearray(image)
    PlayerHealFilterPatch(**kwargs).apply(data)  # type: ignore[arg-type]
    return data


def _cave(data: bytes | bytearray) -> tuple[int, int]:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    section_va, section_off, _vsize = located
    return section_va, section_off


def test_apply_then_verify(image: bytearray) -> None:
    data = _patched(image)
    assert PlayerHealFilterPatch().verify(data) == []


def test_verify_rejects_an_unpatched_image(image: bytearray) -> None:
    problems = PlayerHealFilterPatch().verify(image)
    assert problems and SECTION_NAME in problems[0]


def test_verify_rejects_another_keyword(image: bytearray) -> None:
    """Verification is settings-specific: a file patched one way must not verify as another."""
    data = _patched(image, keyword="HealTargetFilter")
    assert PlayerHealFilterPatch(keyword="HealTargetFilter").verify(data) == []
    assert PlayerHealFilterPatch().verify(data) != []


def test_detect_recovers_the_keyword(image: bytearray) -> None:
    data = _patched(image, keyword="HealTargetFilter")
    found = PlayerHealFilterPatch.detect(data)
    assert found is not None
    assert found.keyword == "HealTargetFilter"
    assert PlayerHealFilterPatch.detect(image) is None


def test_apply_is_idempotent_only_once(image: bytearray) -> None:
    """A second application must fail rather than double-patch: the size literal is already 0xB0
    and `apply_byte_patch` asserts the original bytes."""
    data = _patched(image)
    with pytest.raises(ValueError):
        PlayerHealFilterPatch().apply(data)


def test_ini_surface_reports_the_new_field(image: bytearray) -> None:
    surface = PlayerHealFilterPatch(keyword="HealTargetFilter").ini_surface()
    assert [(f.block, f.name, f.type) for f in surface.fields] == [
        ("PlayerHealSpecialPower", "HealTargetFilter", "ObjectFilter")
    ]


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
    assert bytes(data[name_off : name_off + 16]).split(b"\x00")[0] == b"HealFilter"

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
    assert bytes(data[off : off + 5]) == b"\x68" + struct.pack("<I", PATCHED_MODULEDATA_SIZE)


def test_a_renamed_field_is_rejected(image: bytearray) -> None:
    """The table fingerprint checks names, not just shape."""
    off = va_to_offset(image, STRINGS_VA)
    assert off is not None
    image[off : off + len(b"HealAmount")] = b"HealAmounX"
    with pytest.raises(ValueError, match="field table entry 0"):
        PlayerHealFilterPatch().apply(image)


def test_a_moved_field_is_rejected(image: bytearray) -> None:
    """... and offsets, so a build that repacks the structure cannot slip through."""
    off = va_to_offset(image, FIELD_TABLE_VA)
    assert off is not None
    struct.pack_into("<I", image, off + 12, 0x99)  # HealAmount's ModuleData offset
    with pytest.raises(ValueError, match="expected offset"):
        PlayerHealFilterPatch().apply(image)


def test_an_unterminated_table_is_rejected(image: bytearray) -> None:
    off = va_to_offset(image, FIELD_TABLE_VA)
    assert off is not None
    at = off + len(STOCK_FIELDS) * FIELD_ENTRY_SIZE
    struct.pack_into("<I", image, at, 0xDEADBEEF)
    with pytest.raises(ValueError, match="NULL-terminated"):
        PlayerHealFilterPatch().apply(image)


def test_an_unterminated_inherited_table_is_rejected(image: bytearray) -> None:
    """A build whose `SpecialAbilityUpdate` grew or shrank is not this build, and the
    duplicate-keyword scan would be reading the wrong names."""
    off = va_to_offset(image, INHERITED_FIELD_TABLE_VA)
    assert off is not None
    struct.pack_into("<I", image, off + INHERITED_FIELD_COUNT * FIELD_ENTRY_SIZE, 0xDEADBEEF)
    with pytest.raises(ValueError, match="NULL-terminated"):
        PlayerHealFilterPatch().apply(image)


@pytest.mark.parametrize(
    ("va", "replacement"),
    [
        (0x008CC38D, b"\x8b\xf1"),  # mov esi, ecx - the module in another register
        (0x008CC390, b"\x8b\x7b\x08"),  # mov edi, [ebx+8] - the Object, not the ModuleData
    ],
)
def test_a_reallocated_register_is_rejected(image: bytearray, va: int, replacement: bytes) -> None:
    """The sites the patch reads but never rewrites. Nothing else would catch a mismatch: the
    cave would just dereference whatever the register happened to hold."""
    off = va_to_offset(image, va)
    assert off is not None
    image[off : off + len(replacement)] = replacement
    with pytest.raises(ValueError, match=f"0x{va:08x}"):
        PlayerHealFilterPatch().apply(image)


def test_verify_reports_a_reallocated_register(image: bytearray) -> None:
    data = _patched(image)
    va, expected, _what = REGISTER_ANCHORS[1]
    off = va_to_offset(data, va)
    assert off is not None
    data[off : off + len(expected)] = b"\x8b\xf1"
    problems = PlayerHealFilterPatch().verify(data)
    assert any("the module" in problem for problem in problems)


@pytest.mark.parametrize("keyword", ["", " ", "Has Space", "Trailing ", "nonasciié"])
def test_rejects_malformed_keywords(keyword: str) -> None:
    with pytest.raises(ValueError):
        PlayerHealFilterPatch(keyword=keyword)


@pytest.mark.parametrize("keyword", ["HealRadius", "healaffects"])
def test_rejects_a_keyword_that_already_exists(keyword: str) -> None:
    """A duplicate name would be shadowed by the stock entry the linear scan reaches first."""
    with pytest.raises(ValueError, match="already a PlayerHealSpecialPower field"):
        PlayerHealFilterPatch(keyword=keyword)


@pytest.mark.parametrize("keyword", ["StartsPaused", "attributemodifieraffects"])
def test_rejects_a_keyword_the_module_inherits(image: bytearray, keyword: str) -> None:
    """The inherited table is added to the same `MultiIniFieldParse` first, so a name it already
    defines would be parsed into that field instead of the new one."""
    with pytest.raises(ValueError, match="already a SpecialAbilityUpdate field"):
        PlayerHealFilterPatch(keyword=keyword).apply(image)


def _disassemble(data: bytes | bytearray, va: int, off: int, count: int) -> list[str]:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    out = []
    for insn in md.disasm(bytes(data[off : off + count * 8]), va):
        out.append(f"{insn.mnemonic} {insn.op_str}".strip())
        if len(out) >= count:
            break
    return out


def _stub_start(section_va: int, section_off: int) -> tuple[int, int]:
    """Where the two code stubs begin: past the table and the dword-padded keyword string."""
    table = (len(STOCK_FIELDS) + 2) * FIELD_ENTRY_SIZE
    blob = len(b"HealFilter\x00")
    blob += -blob % 4
    return section_va + table + blob, section_off + table + blob


def test_ctor_stub_runs_the_stock_ctor_then_builds_the_handle(image: bytearray) -> None:
    data = _patched(image)
    section_va, section_off = _cave(data)
    va, off = _stub_start(section_va, section_off)
    assert _disassemble(data, va, off, 6) == [
        f"call 0x{MODULEDATA_CTOR_VA:x}",
        "push eax",
        f"lea ecx, [eax + 0x{FILTER_OFFSET:x}]",
        f"call 0x{OBJECT_FILTER_CTOR_VA:x}",
        "pop eax",
        "ret",
    ]


def test_filter_stub_calls_the_evaluator_not_the_wrapper(image: bytearray) -> None:
    """The whole point of the three-argument form: the wrapper at 0x007640C1 passes a null source
    player, which makes every relationship token - `SAME_PLAYER` above all - return false."""
    data = _patched(image)
    section_va, section_off = _cave(data)
    va, off = _stub_start(section_va, section_off)
    ctor_size = len(build_ctor(va))
    va, off = va + ctor_size, off + ctor_size
    text = _disassemble(data, va, off, 20)
    tail = va + 0x47  # the shared `pop ecx` before the tail-call

    assert text[:5] == [
        "push ecx",
        f"lea ecx, [edi + 0x{FILTER_OFFSET:x}]",
        f"call 0x{OBJECT_FILTER_IS_DEFINED_VA:x}",
        "test al, al",
        f"je 0x{tail:x}",
    ]
    # The three arguments, pushed right-to-left: source player, candidate's player, template. The
    # source is the caster's own player, recomputed from the module rather than read off a frame.
    assert text[5:14] == [
        "mov ecx, dword ptr [ebx + 8]",
        f"call 0x{GET_CONTROLLING_PLAYER_VA:x}",
        "push eax",
        "mov ecx, dword ptr [esp + 4]",
        f"call 0x{GET_CONTROLLING_PLAYER_VA:x}",
        "push eax",
        "mov ecx, dword ptr [esp + 8]",
        "push dword ptr [ecx + 4]",
        f"lea ecx, [edi + 0x{FILTER_OFFSET:x}]",
    ]
    # A reject reports "no match" and cleans the one argument the caller pushed; everything else
    # tail-calls the HealAffects test so its own `ret 4` lands at the original return address.
    assert text[14:] == [
        f"call 0x{OBJECT_FILTER_TEST_VA:x}",
        "test al, al",
        f"jne 0x{tail:x}",
        "pop ecx",
        "xor al, al",
        "ret 4",
    ]
    assert _disassemble(data, tail, off + 0x47, 2) == [
        "pop ecx",
        f"jmp 0x{KIND_OF_MATCHES_VA:x}",
    ]


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
    patch = PlayerHealFilterPatch(keyword="HealTargetFilter")
    apply_patches(src, [patch], output=out)

    assert src.read_bytes() == bytes(image)  # the input is never modified
    assert patch.verify(out.read_bytes()) == []
