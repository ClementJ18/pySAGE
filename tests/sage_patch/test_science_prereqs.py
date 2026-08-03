"""Tests for the `PrerequisiteSciences` forward-reference patch.

Two things need catching statically. The cave is hand-assembled x86 that cannot be executed here,
and a wrong byte in it does not raise - it hands the parser a key computed from the wrong stack
slot, or throws a formatted exception from a frame that is off by a dword - so the stubs are
disassembled back and asserted to say what they were meant to say, with the stack arithmetic of the
throw sequence checked explicitly.

The other half is the build fingerprint. The patch reads two structures it does not rewrite - the
`Science` field-parse table, and (when it is not the thing being repointed) the shared name-to-
science thunk whose calling convention the shim reproduces - and both have to fail loudly on
anything that is not the expected build.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch import SciencePrereqPatch, apply_patches
from sage_patch.patches.science_prereqs import (
    EXCEPTION_CODE,
    EXCEPTION_FORMAT,
    FIELD_ENTRY_SIZE,
    FIELD_TABLE_VA,
    INIT_DETOUR_VA,
    INIT_RESUME_VA,
    IS_VALID_SCIENCE,
    KEY_TO_NAME,
    NAME_TO_KEY,
    PENDING_CAPACITY,
    PREREQ_CALL_VA,
    PREREQ_PARSE_VA,
    SECTION_NAME,
    STOCK_DETOUR_BYTES,
    STOCK_FIELDS,
    THE_NAME_KEY_GENERATOR,
    THE_SCIENCE_STORE,
    THROW_INFO,
    THUNK_VA,
    UNKNOWN_SCIENCE_FORMAT,
    build_section,
    stock_thunk,
)
from sage_patch.utils import find_section, va_to_offset

IMAGE_BASE = 0x400000
#: Where the synthetic image parks the field-name strings, past the table that points at them.
STRINGS_VA = 0x00BF9000


def _call_bytes(from_va: int, to_va: int) -> bytes:
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


def synthetic_image() -> bytearray:
    """A PE32 image mapping every site this patch asserts or repoints, holding exactly what the
    real ``2.01.2614.37001`` build holds there - so the whole apply + verify path runs in CI
    without the copyrighted `game.dat`, and a patch aimed at a wrong address fails here too."""
    strings = bytearray()
    string_vas: dict[str, int] = {}

    def intern(text: str) -> int:
        if text not in string_vas:
            string_vas[text] = STRINGS_VA + len(strings)
            strings.extend(text.encode("ascii") + b"\x00")
        return string_vas[text]

    name_vas = [intern(name) for name, _off in STOCK_FIELDS]

    highest = max(STRINGS_VA + len(strings), PREREQ_CALL_VA + 16) - IMAGE_BASE + 0x100
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

    # The stock six-entry field table plus its NULL terminator. Only `PrerequisiteSciences`' parse
    # function is read, so the other five carry recognisable filler.
    table = bytearray()
    for name_va, (name, offset) in zip(name_vas, STOCK_FIELDS, strict=True):
        parse = PREREQ_PARSE_VA if name == "PrerequisiteSciences" else 0x00730000 | offset
        table += struct.pack("<4I", name_va, parse, 0, offset)
    table += bytes(FIELD_ENTRY_SIZE)
    write(FIELD_TABLE_VA, bytes(table))

    write(THUNK_VA, stock_thunk())
    write(PREREQ_CALL_VA, _call_bytes(PREREQ_CALL_VA, THUNK_VA))
    write(INIT_DETOUR_VA, STOCK_DETOUR_BYTES)
    return data


@pytest.fixture
def image() -> bytearray:
    return synthetic_image()


def _patched(image: bytearray, **kwargs: bool) -> bytearray:
    data = bytearray(image)
    SciencePrereqPatch(**kwargs).apply(data)
    return data


def _cave(data: bytes | bytearray) -> tuple[int, int]:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    section_va, section_off, _vsize = located
    return section_va, section_off


ALL_SETTINGS = [
    {},
    {"report_missing": False},
    {"all_keywords": True},
]


# Round trip


@pytest.mark.parametrize("kwargs", ALL_SETTINGS)
def test_apply_then_verify(image: bytearray, kwargs: dict[str, bool]) -> None:
    data = _patched(image, **kwargs)
    assert SciencePrereqPatch(**kwargs).verify(data) == []


def test_verify_rejects_an_unpatched_image(image: bytearray) -> None:
    problems = SciencePrereqPatch().verify(image)
    assert problems and SECTION_NAME in problems[0]


@pytest.mark.parametrize("kwargs", ALL_SETTINGS[1:])
def test_verify_rejects_other_settings(image: bytearray, kwargs: dict[str, bool]) -> None:
    """Verification is settings-specific: a file patched one way must not verify as another."""
    data = _patched(image, **kwargs)
    assert SciencePrereqPatch(**kwargs).verify(data) == []
    assert SciencePrereqPatch().verify(data) != []


@pytest.mark.parametrize("kwargs", ALL_SETTINGS)
def test_detect_recovers_the_settings(image: bytearray, kwargs: dict[str, bool]) -> None:
    data = _patched(image, **kwargs)
    found = SciencePrereqPatch.detect(data)
    assert found is not None
    assert found.report_missing == kwargs.get("report_missing", True)
    assert found.all_keywords == kwargs.get("all_keywords", False)


def test_detect_is_none_on_an_unpatched_image(image: bytearray) -> None:
    assert SciencePrereqPatch.detect(image) is None


def test_apply_is_idempotent_only_once(image: bytearray) -> None:
    """A second application must fail rather than double-patch: the call at the prerequisite site
    no longer names the thunk, and `apply_byte_patch` asserts the original bytes."""
    data = _patched(image)
    with pytest.raises(ValueError):
        SciencePrereqPatch().apply(data)


def test_all_keywords_requires_the_report() -> None:
    with pytest.raises(ValueError, match="silence every science-name typo"):
        SciencePrereqPatch(report_missing=False, all_keywords=True)


# Which site is repointed


def test_default_touches_only_the_prerequisite_call(image: bytearray) -> None:
    """The narrow mode is the whole reason the OR-group parser has its own call site: the shared
    thunk, and so every other science keyword, must keep the strict check."""
    data = _patched(image)
    section_va, _section_off = _cave(data)
    labels = build_section(section_va, True)[1]

    off = va_to_offset(data, PREREQ_CALL_VA)
    assert off is not None
    assert bytes(data[off : off + 5]) == _call_bytes(PREREQ_CALL_VA, labels["science_key"])

    off = va_to_offset(data, THUNK_VA)
    assert off is not None
    assert bytes(data[off : off + 16]) == stock_thunk()


def test_all_keywords_repoints_the_thunk_and_leaves_the_call(image: bytearray) -> None:
    data = _patched(image, all_keywords=True)
    section_va, _section_off = _cave(data)
    labels = build_section(section_va, True)[1]

    off = va_to_offset(data, THUNK_VA)
    assert off is not None
    assert bytes(data[off : off + 5]) == b"\xe9" + struct.pack(
        "<i", labels["science_key"] - (THUNK_VA + 5)
    )

    # The narrow edit is not also applied - the thunk now reaches the shim for every caller.
    off = va_to_offset(data, PREREQ_CALL_VA)
    assert off is not None
    assert bytes(data[off : off + 5]) == _call_bytes(PREREQ_CALL_VA, THUNK_VA)


def test_no_report_leaves_the_init_site_alone(image: bytearray) -> None:
    data = _patched(image, report_missing=False)
    off = va_to_offset(data, INIT_DETOUR_VA)
    assert off is not None
    assert bytes(data[off : off + 5]) == STOCK_DETOUR_BYTES


# The build fingerprint


def test_a_renamed_field_is_rejected(image: bytearray) -> None:
    off = va_to_offset(image, STRINGS_VA)
    assert off is not None
    image[off : off + len(b"PrerequisiteSciences")] = b"PrerequisiteScienceX"
    with pytest.raises(ValueError, match="Science field entry 0"):
        SciencePrereqPatch().apply(image)


def test_a_moved_field_is_rejected(image: bytearray) -> None:
    off = va_to_offset(image, FIELD_TABLE_VA)
    assert off is not None
    struct.pack_into("<I", image, off + 12, 0x99)  # PrerequisiteSciences' ScienceInfo offset
    with pytest.raises(ValueError, match="expected offset"):
        SciencePrereqPatch().apply(image)


def test_a_different_prerequisite_parser_is_rejected(image: bytearray) -> None:
    """The edit is *inside* the OR-group parser, so the table has to still name it."""
    off = va_to_offset(image, FIELD_TABLE_VA)
    assert off is not None
    struct.pack_into("<I", image, off + 4, 0x0073B4A0)  # the flat science-vector parser
    with pytest.raises(ValueError, match="OR-group parser"):
        SciencePrereqPatch().apply(image)


def test_an_unterminated_table_is_rejected(image: bytearray) -> None:
    off = va_to_offset(image, FIELD_TABLE_VA)
    assert off is not None
    at = off + len(STOCK_FIELDS) * FIELD_ENTRY_SIZE
    struct.pack_into("<I", image, at, 0xDEADBEEF)
    with pytest.raises(ValueError, match="NULL-terminated"):
        SciencePrereqPatch().apply(image)


def test_a_reshaped_thunk_is_rejected(image: bytearray) -> None:
    """The shim reproduces the thunk's calling convention, and nothing else would catch a build
    where that convention differs - the patch would apply and read the wrong stack slot."""
    off = va_to_offset(image, THUNK_VA)
    assert off is not None
    image[off : off + 4] = b"\xff\x74\x24\x08"  # push dword [esp+8]
    with pytest.raises(ValueError, match="science-name thunk"):
        SciencePrereqPatch().apply(image)


def test_the_thunk_is_not_fingerprinted_when_it_is_the_edit(image: bytearray) -> None:
    """With `all_keywords` the thunk is rewritten, so its old bytes are checked by
    `apply_byte_patch` instead - and only the five the jump covers."""
    off = va_to_offset(image, THUNK_VA)
    assert off is not None
    image[off + 10 : off + 15] = b"\x90\x90\x90\x90\x90"  # the dead tail, past the jump
    SciencePrereqPatch(all_keywords=True).apply(image)


# The cave's code


def _disassemble(data: bytes | bytearray, va: int, off: int, count: int) -> list[str]:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    out = []
    for insn in md.disasm(bytes(data[off : off + count * 8]), va):
        out.append(f"{insn.mnemonic} {insn.op_str}".strip())
        if len(out) >= count:
            break
    return out


def _at(data: bytes | bytearray, section_va: int, section_off: int, label: str, count: int):
    labels = build_section(section_va, True)[1]
    va = labels[label]
    return _disassemble(data, va, section_off + (va - section_va), count)


def test_pending_list_comes_first_and_starts_empty(image: bytearray) -> None:
    """The code addresses the list as a link-time constant, so it has to be laid out first."""
    data = _patched(image)
    section_va, section_off = _cave(data)
    labels = build_section(section_va, True)[1]
    assert labels["science_key"] == section_va + 4 + 4 * PENDING_CAPACITY
    assert bytes(data[section_off : section_off + 4 + 4 * PENDING_CAPACITY]) == bytes(
        4 + 4 * PENDING_CAPACITY
    )


def test_science_key_skips_the_check_entirely(image: bytearray) -> None:
    """Tier one, whole: the key `getScienceFromInternalName` would have computed, and none of the
    validation it would then have done."""
    data = _patched(image, report_missing=False)
    section_va, section_off = _cave(data)
    assert _disassemble(data, section_va, section_off, 4) == [
        f"mov ecx, dword ptr [0x{THE_NAME_KEY_GENERATOR:x}]",
        "push dword ptr [esp + 4]",
        f"call 0x{NAME_TO_KEY:x}",
        "ret",
    ]


def test_science_key_records_what_did_not_resolve(image: bytearray) -> None:
    data = _patched(image)
    section_va, section_off = _cave(data)
    labels = build_section(section_va, True)[1]
    pending_va = section_va + 4
    done_va = labels["validate"] - 1  # the shared `ret`, immediately before `validate`
    text = _at(data, section_va, section_off, "science_key", 19)

    assert text[:3] == [
        f"mov ecx, dword ptr [0x{THE_NAME_KEY_GENERATOR:x}]",
        "push dword ptr [esp + 4]",
        f"call 0x{NAME_TO_KEY:x}",
    ]
    # The key is saved across the call, restored without disturbing the flags isValidScience set.
    assert text[3:12] == [
        f"mov ecx, dword ptr [0x{THE_SCIENCE_STORE:x}]",
        "test ecx, ecx",
        f"je 0x{done_va:x}",
        "push eax",
        "push eax",
        f"call 0x{IS_VALID_SCIENCE:x}",
        "test al, al",
        "pop eax",
        f"jne 0x{done_va:x}",
    ]
    assert text[12:] == [
        f"mov edx, dword ptr [0x{section_va:x}]",
        f"cmp edx, 0x{PENDING_CAPACITY:x}",
        f"jae 0x{done_va:x}",
        f"mov dword ptr [edx*4 + 0x{pending_va:x}], eax",
        "inc edx",
        f"mov dword ptr [0x{section_va:x}], edx",
        "ret",
    ]


def test_validate_walks_the_list_and_rechecks_each_key(image: bytearray) -> None:
    data = _patched(image)
    section_va, section_off = _cave(data)
    pending_va = section_va + 4
    text = _at(data, section_va, section_off, "validate", 10)
    assert text[0] == "xor esi, esi"
    assert text[1] == f"cmp esi, dword ptr [0x{section_va:x}]"
    assert text[2].startswith("jae ")
    assert text[3] == f"mov ebx, dword ptr [esi*4 + 0x{pending_va:x}]"
    assert text[4] == f"mov ecx, dword ptr [0x{THE_SCIENCE_STORE:x}]"
    assert text[5:8] == ["push ebx", f"call 0x{IS_VALID_SCIENCE:x}", "test al, al"]
    assert text[8].startswith("je ")
    assert text[9] == "inc esi"


def test_the_report_uses_the_engines_own_message(image: bytearray) -> None:
    """The name comes back from the key, because the token pointer would dangle - and the format
    string and exception code are the stock ones, so the deferred report reads exactly like the
    parse-time throw it replaces."""
    data = _patched(image)
    section_va, section_off = _cave(data)
    labels = build_section(section_va, True)[1]
    # `missing` follows the scan's `ret`, which follows the `jmp` back to the loop head.
    text = _disassemble(
        data, labels["validate"], section_off + (labels["validate"] - section_va), 30
    )
    tail = text[text.index("push ebx", 6) :]

    assert tail[:6] == [
        "push ebx",
        f"mov ecx, dword ptr [0x{THE_NAME_KEY_GENERATOR:x}]",
        f"call 0x{KEY_TO_NAME:x}",
        "mov eax, dword ptr [eax]",
        "test eax, eax",
        tail[5],
    ]
    assert tail[5].startswith("je ")
    assert "add eax, 8" in tail
    assert f"mov eax, 0x{UNKNOWN_SCIENCE_FORMAT:x}" not in tail  # the format is pushed, not moved


def test_the_throw_addresses_its_own_exception_object(image: bytearray) -> None:
    """The two `lea`s have to name the same eight bytes, through two different esp values. Off by
    a dword and the runtime is handed a pointer to the format string instead of the object."""
    data = _patched(image)
    section_va, section_off = _cave(data)
    labels = build_section(section_va, True)[1]
    text = _disassemble(
        data, labels["validate"], section_off + (labels["validate"] - section_va), 40
    )
    start = text.index("sub esp, 8")
    assert text[start : start + 13] == [
        "sub esp, 8",
        "push eax",
        f"push 0x{UNKNOWN_SCIENCE_FORMAT:x}",
        f"push {EXCEPTION_CODE}",
        "lea eax, [esp + 0xc]",
        "push eax",
        f"call 0x{EXCEPTION_FORMAT:x}",
        "add esp, 0x10",
        f"push 0x{THROW_INFO:x}",
        "lea eax, [esp + 4]",
        "push eax",
        f"call 0x{0x00A3CE04:x}",
        "int3",
    ]


def test_after_load_reissues_both_displaced_instructions(image: bytearray) -> None:
    """The detour spans `add esp, 0x1c` and `push 0x24`; both have to reappear, in order, around
    the walk - and the walk has to run inside a `pushad`, since the site is mid-init with live
    ebx/esi/edi."""
    data = _patched(image)
    section_va, section_off = _cave(data)
    labels = build_section(section_va, True)[1]
    text = _at(data, section_va, section_off, "after_load", 6)
    assert text == [
        "add esp, 0x1c",
        "pushal",
        f"call 0x{labels['validate']:x}",
        "popal",
        "push 0x24",
        f"jmp 0x{INIT_RESUME_VA:x}",
    ]

    off = va_to_offset(data, INIT_DETOUR_VA)
    assert off is not None
    assert bytes(data[off : off + 5]) == b"\xe9" + struct.pack(
        "<i", labels["after_load"] - (INIT_DETOUR_VA + 5)
    )


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
    assert count == 2


def test_the_cave_is_writable_only_when_it_records(image: bytearray) -> None:
    for report_missing, writable in ((True, True), (False, False)):
        data = _patched(image, report_missing=report_missing)
        e = struct.unpack_from("<I", data, 0x3C)[0]
        szopt = struct.unpack_from("<H", data, e + 20)[0]
        sectab = e + 24 + szopt
        flags = struct.unpack_from("<I", data, sectab + 40 + 36)[0]
        assert bool(flags & 0x80000000) is writable


def test_apply_patches_round_trip(tmp_path, image: bytearray) -> None:
    src = tmp_path / "game.dat"
    src.write_bytes(bytes(image))
    out = tmp_path / "patched.dat"
    patch = SciencePrereqPatch(all_keywords=True)
    apply_patches(src, [patch], output=out)

    assert src.read_bytes() == bytes(image)  # the input is never modified
    assert patch.verify(out.read_bytes()) == []
