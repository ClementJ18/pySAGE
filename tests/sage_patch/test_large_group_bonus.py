"""Tests for the large-group-bonus patch.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter most
disassemble it back and assert it says what it was meant to say. A wrong byte in a stub does not
raise - it counts the wrong thing, gates on the wrong mask, or hands the filter evaluator a garbage
source player and silently answers for the wrong side - so encoding errors have to be caught
statically. Stack discipline gets the same treatment: three stubs park values on the stack across
``__thiscall`` calls, the allocation stub owes its caller an argument it does not clean, and the
gate carries the caller's flags across two calls - a ``push`` without its ``pop`` corrupts the
frame rather than faulting.

The other half of the suite is the build fingerprint. This patch reads four things it does not
rewrite - the stock field-parse table, the wrapper vtable it copies, the register allocation
`update` establishes, and the mask helpers the gate calls - and each has to fail loudly on anything
that is not the expected build.
"""

from __future__ import annotations

import struct

import pytest

pytest.importorskip("capstone", reason="the [patch] extra (capstone) is not installed")
from capstone import CS_ARCH_X86, CS_MODE_32, Cs  # noqa: E402 - after the importorskip guard

from sage_patch import LargeGroupBonusPatch, apply_patches  # noqa: E402
from sage_patch.addresses import (  # noqa: E402
    FIELD_PARSE_STRIDE,
    INI_PARSE_BOOL,
    OPERATOR_NEW,
)
from sage_patch.patches.large_group_bonus import (  # noqa: E402
    ALLOC_RESUME_VA,
    ALLOC_WINDOW_BYTES,
    ALLOC_WINDOW_VA,
    ANCHORS,
    ATTRIB_REMOVE_VA,
    BONUS_HELD_OFFSET,
    CONFLICTS_WITH_OFFSET,
    COUNT_WINDOW_BYTES,
    COUNT_WINDOW_VA,
    DEFAULT_KEYWORD,
    FIELD_TABLE_REF_VA,
    FIELD_TABLE_VA,
    FILTER_OFFSET,
    FLAG_OFFSET,
    GATE_RESUME_VA,
    GATE_TAIL_VA,
    GATE_WINDOW_BYTES,
    GATE_WINDOW_VA,
    GET_CONTAIN_VA,
    GET_CONTROLLING_PLAYER_VA,
    MASK_ANY_VA,
    MASK_DWORDS,
    MASK_TEST_ALL_VA,
    MASK_TEST_ANY_VA,
    MODULEDATA_CTOR_CALL_VA,
    MODULEDATA_CTOR_VA,
    OBJECT_FILTER_IS_DEFINED_VA,
    OBJECT_FILTER_PARSE_VA,
    OBJECT_FILTER_TEST_VA,
    PARSE_UPGRADE_MASK_VA,
    PARTITION_ALLOW_VA,
    PATCHED_MODULEDATA_SIZE,
    REQUIRES_ALL_CONFLICTING_OFFSET,
    REQUIRES_ALL_TRIGGERS_OFFSET,
    SECTION_NAME,
    SETUP_WINDOW_BYTES,
    SETUP_WINDOW_VA,
    STOCK_FIELDS,
    STOCK_MODULEDATA_SIZE,
    TRIGGERED_BY_OFFSET,
    UPGRADE_FIELDS,
    WRAPPER_VTABLE_SLOTS,
    WRAPPER_VTABLE_VA,
    ZERO_DWORDS,
    _layout,
    build_alloc,
    build_count,
    build_gate,
    build_new_allow,
    build_setup,
)
from sage_patch.patches.large_group_bonus import (  # noqa: E402
    LargeGroupBonusPatch as Patch,
)
from sage_patch.utils import find_section, va_to_offset  # noqa: E402

IMAGE_BASE = 0x400000
#: Where the synthetic image parks the field-name strings, past the table that points at them.
STRINGS_VA = 0x00C64000

#: The stock wrapper vtable's other two slots. Only slot 1 (`allow`) is meaningful to the patch;
#: these are copied verbatim and are here so the test can prove that.
STOCK_VTABLE = (0x00893738, PARTITION_ALLOW_VA, 0x0048DACD)


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

    # The stock 8-entry field-parse table, plus its NULL terminator. `parse` and `userData` are not
    # read by the patch (the entries are copied verbatim), so a recognisable filler stands in -
    # except `AlliesOnly`, whose real Bool parser is what three appended rows must also name.
    table = bytearray()
    for name_va, (name, offset) in zip(name_vas, STOCK_FIELDS, strict=True):
        parse = INI_PARSE_BOOL if name == "AlliesOnly" else (0x00730000 | offset)
        table += struct.pack("<4I", name_va, parse, 0, offset)
    table += bytes(FIELD_PARSE_STRIDE)
    write(FIELD_TABLE_VA, bytes(table))

    write(WRAPPER_VTABLE_VA, struct.pack(f"<{WRAPPER_VTABLE_SLOTS}I", *STOCK_VTABLE))
    write(FIELD_TABLE_REF_VA, struct.pack("<I", FIELD_TABLE_VA))
    write(ALLOC_WINDOW_VA, ALLOC_WINDOW_BYTES)
    write(GATE_WINDOW_VA, GATE_WINDOW_BYTES)
    write(SETUP_WINDOW_VA, SETUP_WINDOW_BYTES)
    write(COUNT_WINDOW_VA, COUNT_WINDOW_BYTES)
    for va, blob in ANCHORS.items():
        write(va, blob)
    return data


@pytest.fixture
def image() -> bytearray:
    return synthetic_image()


def _patched(image: bytearray, **kwargs: str) -> bytearray:
    data = bytearray(image)
    Patch(**kwargs).apply(data)
    return data


def _cave(data: bytes | bytearray) -> tuple[int, int]:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    section_va, section_off, _vsize = located
    return section_va, section_off


def _dis(code: bytes, va: int) -> list[str]:
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    return [f"{i.mnemonic} {i.op_str}".strip() for i in md.disasm(code, va)]


def _stub(name: str, base: int = 0x00B00000) -> list[str]:
    """One stub, disassembled at a fixed base so the expected text is stable."""
    built = {
        "alloc": lambda: build_alloc(base),
        "gate": lambda: build_gate(base),
        "setup": lambda: build_setup(base, 0x00B01000, WRAPPER_VTABLE_VA),
        "allow": lambda: build_new_allow(base),
        "count": lambda: build_count(base),
    }[name]()
    return _dis(built, base)


# --- round trip ------------------------------------------------------------------------------


def test_apply_then_verify(image: bytearray) -> None:
    data = _patched(image)
    assert Patch().verify(data) == []


def test_verify_rejects_an_unpatched_image(image: bytearray) -> None:
    problems = Patch().verify(image)
    assert problems and SECTION_NAME in problems[0]


def test_verify_and_detect_are_keyword_specific(image: bytearray) -> None:
    """A file patched under one keyword must not verify - or detect - as another."""
    data = _patched(image, keyword="LooseObjects")
    assert Patch(keyword="LooseObjects").verify(data) == []
    assert Patch().verify(data) != []

    found = Patch.detect(data)
    assert found is not None
    assert found.keyword == "LooseObjects"


def test_detect_finds_the_default(image: bytearray) -> None:
    found = Patch.detect(_patched(image))
    assert found is not None
    assert found.keyword == DEFAULT_KEYWORD
    assert Patch.detect(image) is None


def test_apply_is_idempotent_only_once(image: bytearray) -> None:
    """A second application must fail rather than double-patch: `apply_byte_patch` asserts the
    original bytes, and `newModuleData` no longer allocates the stock size."""
    data = _patched(image)
    with pytest.raises(ValueError):
        Patch().apply(data)


def test_apply_patches_writes_a_file(image: bytearray, tmp_path) -> None:
    src = tmp_path / "game.dat"
    src.write_bytes(bytes(image))
    out = tmp_path / "patched.dat"
    apply_patches(src, [Patch()], output=out)
    assert Patch().verify(bytearray(out.read_bytes())) == []
    assert src.read_bytes() == bytes(image)  # the input is never modified


# --- the grown ModuleData ----------------------------------------------------------------------


def test_the_new_fields_land_past_the_stock_structure() -> None:
    """Two 36-dword masks and three bools do not fit in the three bytes of padding the stock
    structure has, so the allocation grows and every new field lives past `0x30` - in the region
    the allocation stub zeroes, which is what gives all five their defaults."""
    stock = {off for _name, off in STOCK_FIELDS}
    new = (
        TRIGGERED_BY_OFFSET,
        CONFLICTS_WITH_OFFSET,
        REQUIRES_ALL_TRIGGERS_OFFSET,
        REQUIRES_ALL_CONFLICTING_OFFSET,
        FLAG_OFFSET,
    )
    for offset in new:
        assert offset >= STOCK_MODULEDATA_SIZE
        assert offset < PATCHED_MODULEDATA_SIZE
        assert offset not in stock
    assert len(set(new)) == len(new)
    # the two masks are adjacent and exactly 36 dwords apart, as every mask pair in the engine is
    assert CONFLICTS_WITH_OFFSET - TRIGGERED_BY_OFFSET == MASK_DWORDS * 4
    assert REQUIRES_ALL_TRIGGERS_OFFSET - CONFLICTS_WITH_OFFSET == MASK_DWORDS * 4
    assert ZERO_DWORDS * 4 == PATCHED_MODULEDATA_SIZE - STOCK_MODULEDATA_SIZE


def test_alloc_grows_the_block_and_zeroes_the_tail() -> None:
    text = _stub("alloc")
    assert text[:2] == ["push ecx", "push esi"]  # both displaced pushes, in order
    assert f"push {PATCHED_MODULEDATA_SIZE:#x}" in text
    assert f"call {OPERATOR_NEW:#x}" in text
    assert f"lea edx, [eax + {STOCK_MODULEDATA_SIZE:#x}]" in text
    assert f"mov ecx, {ZERO_DWORDS:#x}" in text
    assert "mov dword ptr [edx], eax" in text  # the zeroing store
    assert text[-1] == f"jmp {ALLOC_RESUME_VA:#x}"


def test_alloc_leaves_the_size_argument_for_the_callers_pop() -> None:
    """`operator new` is cdecl and the caller cleans the argument with the `pop ecx` this stub
    rejoins at, so the stub must not clean it itself - and must not leave anything else behind."""
    text = _stub("alloc")
    assert not any(line.startswith("add esp") for line in text)
    assert text.count("push eax") == text.count("pop eax") == 1  # only the zeroing loop's save


def test_the_allocation_window_becomes_a_jump(image: bytearray) -> None:
    data = _patched(image)
    section_va, _off = _cave(data)
    pieces = _layout(section_va, DEFAULT_KEYWORD)
    off = va_to_offset(data, ALLOC_WINDOW_VA)
    assert off is not None
    window = bytes(data[off : off + len(ALLOC_WINDOW_BYTES)])
    assert window[:5] == b"\xe9" + struct.pack("<i", pieces.alloc_va - (ALLOC_WINDOW_VA + 5))
    assert window[5:] == b"\x90" * (len(ALLOC_WINDOW_BYTES) - 5)


def test_there_is_no_constructor_shim(image: bytearray) -> None:
    """The stock constructor writes nothing past `0x30`, so zeroing in the allocator is enough and
    the ctor call stays pointed at the engine's own constructor - one hook site fewer than the
    `large-group-bonus-filter` this patch replaces."""
    data = _patched(image)
    off = va_to_offset(data, MODULEDATA_CTOR_CALL_VA)
    assert off is not None
    assert bytes(data[off : off + 5]) == _call_bytes(MODULEDATA_CTOR_CALL_VA, MODULEDATA_CTOR_VA)


def test_the_patch_reuses_the_stock_filter_field() -> None:
    """No second `ObjectFilter` is added: the filter stubs read `HordeMemberFilter` where it
    already is."""
    assert FILTER_OFFSET == dict(STOCK_FIELDS)["HordeMemberFilter"]


# --- the relocated field-parse table -----------------------------------------------------------


def test_table_keeps_the_stock_entries_verbatim(image: bytearray) -> None:
    data = _patched(image)
    section_va, _section_off = _cave(data)
    pieces = _layout(section_va, DEFAULT_KEYWORD)

    stock_off = va_to_offset(image, FIELD_TABLE_VA)
    table_off = va_to_offset(data, pieces.table_va)
    assert stock_off is not None and table_off is not None
    size = len(STOCK_FIELDS) * FIELD_PARSE_STRIDE
    assert bytes(data[table_off : table_off + size]) == bytes(image[stock_off : stock_off + size])

    # ... and the sole reference now points at the copy.
    ref_off = va_to_offset(data, FIELD_TABLE_REF_VA)
    assert ref_off is not None
    assert struct.unpack_from("<I", data, ref_off)[0] == pieces.table_va


def test_table_appends_five_rows_then_terminates(image: bytearray) -> None:
    """The loose-object `Bool` under the installed keyword, then the four `UpgradeMuxData` rows
    under the engine's own names, each with the engine's own parser and this module's offset."""
    data = _patched(image)
    section_va, _section_off = _cave(data)
    pieces = _layout(section_va, DEFAULT_KEYWORD)
    at = va_to_offset(data, pieces.table_va)
    assert at is not None
    at += len(STOCK_FIELDS) * FIELD_PARSE_STRIDE

    expected = [(DEFAULT_KEYWORD, INI_PARSE_BOOL, FLAG_OFFSET), *UPGRADE_FIELDS]
    for index, (name, parse, offset) in enumerate(expected):
        name_va, parse_fn, userdata, field_off = struct.unpack_from(
            "<4I", data, at + index * FIELD_PARSE_STRIDE
        )
        assert parse_fn == parse
        assert parse_fn != OBJECT_FILTER_PARSE_VA  # never another filter handle
        assert userdata == 0
        assert field_off == offset
        name_off = va_to_offset(data, name_va)
        assert name_off is not None
        assert bytes(data[name_off : name_off + 64]).split(b"\x00")[0] == name.encode()

    terminator = bytes(
        data[
            at + len(expected) * FIELD_PARSE_STRIDE : at + (len(expected) + 1) * FIELD_PARSE_STRIDE
        ]
    )
    assert terminator == bytes(FIELD_PARSE_STRIDE)


def test_the_upgrade_rows_name_the_engines_own_parsers() -> None:
    """The four rows are copied from the `UpgradeMuxData` base table at `0x00C76AD8`: two masks
    parsed by `INI::parseUpgradeMask`, two bools by the same parser `AlliesOnly` uses."""
    by_name = {name: (parse, offset) for name, parse, offset in UPGRADE_FIELDS}
    assert by_name["TriggeredBy"] == (PARSE_UPGRADE_MASK_VA, TRIGGERED_BY_OFFSET)
    assert by_name["ConflictsWith"] == (PARSE_UPGRADE_MASK_VA, CONFLICTS_WITH_OFFSET)
    assert by_name["RequiresAllTriggers"] == (INI_PARSE_BOOL, REQUIRES_ALL_TRIGGERS_OFFSET)
    assert by_name["RequiresAllConflictingTriggers"] == (
        INI_PARSE_BOOL,
        REQUIRES_ALL_CONFLICTING_OFFSET,
    )


def test_the_keyword_is_at_the_section_base(image: bytearray) -> None:
    """`detect` reads it straight off the base, so the layout must keep it first - ahead of the
    four fixed upgrade names."""
    data = _patched(image)
    _section_va, section_off = _cave(data)
    assert bytes(data[section_off : section_off + 32]).split(b"\x00")[0] == DEFAULT_KEYWORD.encode()


# --- the upgrade gate --------------------------------------------------------------------------


def test_the_gate_window_is_exactly_a_jump(image: bytearray) -> None:
    """The window is one whole five-byte instruction, so the hook needs no padding at all."""
    assert len(GATE_WINDOW_BYTES) == 5
    data = _patched(image)
    section_va, _off = _cave(data)
    pieces = _layout(section_va, DEFAULT_KEYWORD)
    off = va_to_offset(data, GATE_WINDOW_VA)
    assert off is not None
    window = bytes(data[off : off + 5])
    assert window == b"\xe9" + struct.pack("<i", pieces.gate_va - (GATE_WINDOW_VA + 5))


def test_gate_carries_the_callers_flags_and_template_across_itself() -> None:
    """The branch at `GATE_RESUME_VA` consumes flags set before the window, and `ecx` is read again
    just past it - so both are saved on entry and restored before either exit."""
    text = _stub("gate")
    assert text[:2] == ["pushfd", "push ecx"]
    assert text.count("pushfd") == 1
    assert text.count("popfd") == 2  # one per exit
    for index, line in enumerate(text):
        if line == "popfd":
            assert text[index - 1] == "pop ecx"


def test_gate_resumes_with_the_displaced_instruction() -> None:
    """The active path owes the caller the instruction the window held, in `eax`."""
    text = _stub("gate")
    at = text.index(f"jmp {GATE_RESUME_VA:#x}")
    assert text[at - 1] == "mov eax, dword ptr [0xde412c]"
    assert _dis(GATE_WINDOW_BYTES, GATE_WINDOW_VA) == ["mov eax, dword ptr [0xde412c]"]


def test_gate_tests_triggeredby_then_conflictswith() -> None:
    """Both halves are optional: `any()` on an undeclared mask answers false, which is what makes
    a module that declares neither resume unchanged."""
    text = _stub("gate")
    assert text.count(f"call {MASK_ANY_VA:#x}") == 2
    first = text.index(f"call {MASK_ANY_VA:#x}")
    second = text.index(f"call {MASK_ANY_VA:#x}", first + 1)
    assert text[first - 1] == f"lea ecx, [edi + {TRIGGERED_BY_OFFSET:#x}]"
    assert text[second - 1] == f"lea ecx, [edi + {CONFLICTS_WITH_OFFSET:#x}]"


def test_gate_passes_each_mask_with_its_own_requires_all_flag() -> None:
    text = _stub("gate")
    assert f"movzx edx, byte ptr [edi + {REQUIRES_ALL_TRIGGERS_OFFSET:#x}]" in text
    assert f"movzx edx, byte ptr [edi + {REQUIRES_ALL_CONFLICTING_OFFSET:#x}]" in text
    for offset, mask in (
        (REQUIRES_ALL_TRIGGERS_OFFSET, TRIGGERED_BY_OFFSET),
        (REQUIRES_ALL_CONFLICTING_OFFSET, CONFLICTS_WITH_OFFSET),
    ):
        at = text.index(f"movzx edx, byte ptr [edi + {offset:#x}]")
        assert text[at - 1] == f"lea eax, [edi + {mask:#x}]"
        assert text[at + 1].startswith("call ")


def test_gate_drops_the_bonus_before_entering_the_tail() -> None:
    """An inactive module loses the bonus the way the stock falling edge does - and only when it
    actually holds it - then enters `update`'s tail, which never built the iterator this path
    skipped."""
    text = _stub("gate")
    at = text.index(f"cmp byte ptr [esi + {BONUS_HELD_OFFSET:#x}], 0")
    assert text[at + 1].startswith("je ")  # never held -> nothing to undo
    assert f"mov byte ptr [esi + {BONUS_HELD_OFFSET:#x}], 0" in text
    assert "lea eax, [edi + 0x2c]" in text  # &AttributeModifier
    assert f"call {ATTRIB_REMOVE_VA:#x}" in text
    selector = text.index("mov byte ptr [ebp - 0xd], 0")  # the sleep selector the tail reads
    assert text[selector + 1] == f"jmp {GATE_TAIL_VA:#x}"


def test_held_picks_between_any_of_and_all_of() -> None:
    """`RequiresAllTriggers` is a one-call swap, which is exactly what the stock mux does."""
    text = _stub("gate")
    assert f"mov ecx, {MASK_TEST_ANY_VA:#x}" in text
    assert f"mov ecx, {MASK_TEST_ALL_VA:#x}" in text
    at = text.index(f"mov ecx, {MASK_TEST_ANY_VA:#x}")
    assert text[at + 1] == "test dl, dl"


def test_held_tests_the_object_mask_then_the_players() -> None:
    """The engine's own two-call idiom, in the engine's own order, with the NULL a player-less
    object answers `getControllingPlayer` with."""
    text = _stub("gate")
    assert "lea ecx, [ebx + 0x28c]" in text  # Object+0x28c, completed
    assert "lea ecx, [eax + 0x14c]" in text  # Player+0x14c, completed
    at = text.index("lea ecx, [ebx + 0x28c]")
    assert text[at + 1] == "call dword ptr [esp + 8]"
    player = text.index(f"call {GET_CONTROLLING_PLAYER_VA:#x}")
    assert text[player + 1] == "test eax, eax"
    assert text[player + 2].startswith("je ")  # unowned -> its own mask alone


def test_held_balances_its_stack() -> None:
    """The test function and the mask are parked across two `ret 4` callees; both are dropped by
    the single `add esp, 8` before the return."""
    text = _stub("gate")
    at = text.index(f"mov ecx, {MASK_TEST_ANY_VA:#x}")  # where `held` begins
    held = text[at:]
    assert held.count("push ecx") == 1
    assert held.count("push eax") == 2  # the mask, kept, and this call's argument
    assert held.count("push dword ptr [esp]") == 1  # the argument for the second call
    assert held.count("add esp, 8") == 1
    assert held[-1] == "ret"
    assert held.count("ret") == 1


# --- the copied wrapper vtable -----------------------------------------------------------------


def test_the_cave_vtable_differs_from_stock_in_exactly_one_slot(image: bytearray) -> None:
    data = _patched(image)
    section_va, _off = _cave(data)
    pieces = _layout(section_va, DEFAULT_KEYWORD)
    off = va_to_offset(data, pieces.vtable_va)
    assert off is not None
    slots = struct.unpack_from(f"<{WRAPPER_VTABLE_SLOTS}I", data, off)

    assert slots[0] == STOCK_VTABLE[0]
    assert slots[2] == STOCK_VTABLE[2]
    assert slots[1] == pieces.allow_va
    assert slots[1] != PARTITION_ALLOW_VA


def test_the_stock_vtable_is_left_alone(image: bytearray) -> None:
    """The widened `allow` is reached by installing a different vtable, not by editing the stock
    one - which is what keeps every unwidened `LargeGroupBonusUpdate` byte-identical."""
    data = _patched(image)
    off = va_to_offset(data, WRAPPER_VTABLE_VA)
    assert off is not None
    assert struct.unpack_from(f"<{WRAPPER_VTABLE_SLOTS}I", data, off) == STOCK_VTABLE


def test_a_relocated_allow_is_rejected(image: bytearray) -> None:
    """Copying the vtable is only safe if slot 1 really is the horde gate."""
    off = va_to_offset(image, WRAPPER_VTABLE_VA)
    assert off is not None
    struct.pack_into("<I", image, off + 4, 0x00660000)
    with pytest.raises(ValueError, match="horde gate"):
        Patch().apply(image)


# --- the two hooked windows of the loose-object count -------------------------------------------


def test_gate1_keeps_the_lea_the_next_instruction_consumes() -> None:
    """The window's `lea eax,[edi+0xc]` feeds a `mov [ebp-0x48], eax` outside it, so the shim has
    to leave the same value in eax - and it must write the wrapper's vtable slot either way."""
    text = _stub("setup")
    assert text[0] == "mov dword ptr [ebp - 0x50], 0xc63870"
    assert text[-2] == "lea eax, [edi + 0xc]"
    assert text[-1] == "ret"
    assert "mov dword ptr [ebp - 0x50], 0xb01000" in text  # the cave vtable, on the widened path
    assert "mov dword ptr [ebp - 0x4c], ebx" in text  # the owning Object, into the free slot


def test_gate1_is_a_call_and_padding(image: bytearray) -> None:
    data = _patched(image)
    section_va, _off = _cave(data)
    pieces = _layout(section_va, DEFAULT_KEYWORD)
    off = va_to_offset(data, SETUP_WINDOW_VA)
    assert off is not None
    window = bytes(data[off : off + len(SETUP_WINDOW_BYTES)])
    assert window[:5] == _call_bytes(SETUP_WINDOW_VA, pieces.setup_va)
    assert window[5:] == b"\x90" * (len(SETUP_WINDOW_BYTES) - 5)


def test_gate2_reproduces_the_windows_own_first_and_last_instruction(image: bytearray) -> None:
    """Only the middle of the count window is replaced: `mov ecx,eax` and the accumulate are the
    stock instructions, so the loop around them is untouched."""
    data = _patched(image)
    section_va, _off = _cave(data)
    pieces = _layout(section_va, DEFAULT_KEYWORD)
    off = va_to_offset(data, COUNT_WINDOW_VA)
    assert off is not None
    window = bytes(data[off : off + len(COUNT_WINDOW_BYTES)])

    text = _dis(window, COUNT_WINDOW_VA)
    assert text[0] == "mov ecx, eax"
    assert text[1] == f"call 0x{pieces.count_va:x}"
    assert text[2] == "add dword ptr [ebp - 0x18], eax"
    assert set(text[3:]) == {"nop"}
    assert window[:2] == COUNT_WINDOW_BYTES[:2]  # the stock `mov ecx, eax`, byte for byte
    assert window[7:10] == COUNT_WINDOW_BYTES[-3:]  # the stock `add [ebp-0x18], eax`


# --- the widened allow -------------------------------------------------------------------------


def test_allow_keeps_the_stock_contain_path() -> None:
    """A candidate that *does* carry a contain interface must be handled exactly as stock: hand
    `HordeMemberFilter` to vslot +0x180 and accept on a non-zero count."""
    text = _stub("allow")
    assert f"call 0x{GET_CONTAIN_VA:x}" in text
    assert "push dword ptr [esi + 8]" in text
    assert "call dword ptr [edx + 0x180]" in text
    assert "mov al, byte ptr [esi + 0xc]" in text  # the accept polarity
    assert "sete al" in text  # ... and the reject one


def test_allow_calls_the_three_argument_evaluator_not_the_wrapper() -> None:
    """The two-argument wrapper starves the evaluator of a source player and makes every
    relationship token return false, so the loose path must not use it."""
    text = _stub("allow")
    assert f"call 0x{OBJECT_FILTER_TEST_VA:x}" in text
    assert "call 0x7640c1" not in text
    assert text.count(f"call 0x{GET_CONTROLLING_PLAYER_VA:x}") == 2  # source and candidate


def test_allow_reads_the_source_player_from_the_wrapper_slot() -> None:
    """The partition scan has no register holding the module's own object, so the shim parks it in
    the wrapper's free +4 dword and `allow` reads it back from there."""
    text = _stub("allow")
    assert "mov ecx, dword ptr [esi + 4]" in text
    at = text.index("mov ecx, dword ptr [esi + 4]")
    assert text[at + 1] == f"call 0x{GET_CONTROLLING_PLAYER_VA:x}"
    assert text[at + 2] == "push eax"  # arg3, the source player


def test_allow_gates_the_loose_path_on_isdefined() -> None:
    """`CountLooseObjects` without a `HordeMemberFilter` must be inert, not sweeping."""
    assert f"call 0x{OBJECT_FILTER_IS_DEFINED_VA:x}" in _stub("allow")


def test_allow_balances_its_stack_on_every_path() -> None:
    text = _stub("allow")
    assert text[:2] == ["push ebx", "push esi"]
    assert text.count("pop esi") == 2  # one per exit
    assert text.count("pop ebx") == 2
    assert text.count("ret 4") == 2  # the stock signature: callee-cleaned, one argument
    # every `pop esi` is immediately followed by `pop ebx` then the return
    for index, line in enumerate(text):
        if line == "pop esi":
            assert text[index + 1 : index + 3] == ["pop ebx", "ret 4"]


# --- the count stub ------------------------------------------------------------------------------


def test_count_returns_the_member_count_for_a_container() -> None:
    text = _stub("count")
    assert text[0] == "push ecx"
    assert text[1] == f"call 0x{GET_CONTAIN_VA:x}"
    assert "call dword ptr [edx + 0x180]" in text


def test_count_gates_the_loose_path_on_both_the_flag_and_the_filter() -> None:
    text = _stub("count")
    assert f"cmp byte ptr [edi + {FLAG_OFFSET:#x}], 0" in text
    assert f"call 0x{OBJECT_FILTER_IS_DEFINED_VA:x}" in text
    assert f"call 0x{OBJECT_FILTER_TEST_VA:x}" in text
    assert "movzx eax, al" in text  # a loose match contributes exactly 1


def test_count_reads_the_owner_from_ebx() -> None:
    """`ebx` holds the owning Object for the whole of `update`, which is what saves this stub a
    frame slot - and is why the register anchors are asserted before anything is written."""
    text = _stub("count")
    at = text.index("mov ecx, ebx")
    assert text[at + 1] == f"call 0x{GET_CONTROLLING_PLAYER_VA:x}"


def test_count_balances_its_stack_on_every_path() -> None:
    """The candidate is pushed once on entry and dropped before each of the three returns; the
    filter pointer handed to +0x180 is cleaned by that callee's own `ret 4`."""
    text = _stub("count")
    assert text.count("ret") == 3
    for index, line in enumerate(text):
        if line == "ret":
            assert text[index - 1] == "pop ecx"


def test_count_leaves_the_callee_saved_registers_alone() -> None:
    """`esi`, `edi` and `ebx` are live across the loop; the stub may only clobber what the window
    it replaced clobbered."""
    text = _stub("count")
    for banned in ("push esi", "push edi", "push ebx", "pop esi", "pop edi", "pop ebx"):
        assert banned not in text
    assert not any(line.startswith(("mov esi,", "mov edi,", "mov ebx,")) for line in text)


# --- the build fingerprint -------------------------------------------------------------------


def test_a_renamed_field_is_rejected(image: bytearray) -> None:
    """The table fingerprint checks names, not just shape."""
    off = va_to_offset(image, FIELD_TABLE_VA)
    assert off is not None
    name_va = struct.unpack_from("<I", image, off + FIELD_PARSE_STRIDE)[0]  # HordeMemberFilter
    name_off = va_to_offset(image, name_va)
    assert name_off is not None
    image[name_off : name_off + len("HordeMemberFilter")] = b"X" * len("HordeMemberFilter")
    with pytest.raises(ValueError, match="HordeMemberFilter"):
        Patch().apply(image)


def test_a_moved_field_is_rejected(image: bytearray) -> None:
    off = va_to_offset(image, FIELD_TABLE_VA)
    assert off is not None
    struct.pack_into("<I", image, off + FIELD_PARSE_STRIDE + 12, 0x40)  # HordeMemberFilter -> +0x40
    with pytest.raises(ValueError, match="expected offset"):
        Patch().apply(image)


@pytest.mark.parametrize("anchor_va", sorted(ANCHORS))
def test_every_anchor_is_asserted_before_anything_is_written(
    image: bytearray, anchor_va: int
) -> None:
    """The register anchors are the load-bearing ones: nothing the patch writes would catch a build
    that put the ModuleData somewhere other than `edi`."""
    off = va_to_offset(image, anchor_va)
    assert off is not None
    image[off] ^= 0xFF
    with pytest.raises(ValueError, match="not the expected build"):
        Patch().apply(image)


def test_an_older_filter_patch_is_refused(image: bytearray) -> None:
    """A binary carrying the `large-group-bonus-filter` this patch replaces has a constructor shim
    where the stock ctor call belongs. That is a different structure layout, so it must be rebuilt
    from a clean image rather than patched on top of."""
    off = va_to_offset(image, MODULEDATA_CTOR_CALL_VA)
    assert off is not None
    image[off : off + 5] = _call_bytes(MODULEDATA_CTOR_CALL_VA, 0x00B00000)
    with pytest.raises(ValueError, match="not the expected build"):
        Patch().apply(image)


def test_verify_notices_a_corrupted_anchor(image: bytearray) -> None:
    data = _patched(image)
    off = va_to_offset(data, GET_CONTAIN_VA)
    assert off is not None
    data[off] ^= 0xFF
    assert any("anchor" in problem for problem in Patch().verify(data))


# --- the keyword ------------------------------------------------------------------------------


@pytest.mark.parametrize("keyword", ["", "0Bad", "has space", "with-dash", "x" * 64])
def test_bad_keywords_are_refused(keyword: str) -> None:
    with pytest.raises(ValueError):
        Patch(keyword=keyword)


@pytest.mark.parametrize(
    "keyword",
    [name for name, _off in STOCK_FIELDS] + [name for name, _p, _o in UPGRADE_FIELDS],
)
def test_a_keyword_the_module_already_parses_is_refused(keyword: str) -> None:
    """A duplicate row would parse - the reader takes the first match and never complains - so the
    field would exist and silently write the wrong offset. That now covers the four keywords this
    patch appends beside the renameable one."""
    with pytest.raises(ValueError, match="already"):
        Patch(keyword=keyword)


# --- the INI surface --------------------------------------------------------------------------


def test_ini_surface_declares_all_five_fields() -> None:
    surface = LargeGroupBonusPatch(keyword="LooseObjects").ini_surface()
    declared = {delta.name: (delta.type, delta.default) for delta in surface.fields}
    assert declared == {
        "LooseObjects": ("Bool", False),
        "TriggeredBy": ("Ref[]:upgrades", None),
        "ConflictsWith": ("Ref[]:upgrades", None),
        "RequiresAllTriggers": ("Bool", False),
        "RequiresAllConflictingTriggers": ("Bool", False),
    }
    for delta in surface.fields:
        assert delta.block == "LargeGroupBonusUpdate"
        assert delta.patch == LargeGroupBonusPatch.name


def test_the_upgrade_keywords_are_not_renameable() -> None:
    """They are the engine's own spellings, taken row for row from `UpgradeMuxData` - a mod that
    writes them expects them to mean here what they mean everywhere else."""
    surface = LargeGroupBonusPatch(keyword="Whatever").ini_surface()
    names = {delta.name for delta in surface.fields}
    assert {name for name, _p, _o in UPGRADE_FIELDS} <= names


def test_the_patch_is_attributed() -> None:
    assert LargeGroupBonusPatch.author
    assert "(by " in LargeGroupBonusPatch().credit
