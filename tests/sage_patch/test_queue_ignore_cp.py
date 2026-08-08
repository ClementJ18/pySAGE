"""Tests for the queue-ignore-cp patch.

The structural checks are the usual ones - the cave's layout, the seven edits, the round trip
through `verify`. The rest hold the properties the patch's correctness actually rests on, none of
which "it applies cleanly" would catch:

* the new field lands in `CommandButton`'s alignment padding, so ``sizeof`` never has to change
  and `ControlBar::newCommandButton`'s ``operator new(0x2E0)`` is left alone;
* the widened constructor store really does zero that byte and really does leave `AutoAbility`
  at `No`, since `operator new` does not zero the block;
* the rebuilt table keeps the live rows *verbatim*, because their name pointers are absolute;
* the flag is raised and cleared by the *same* routine, which is what makes it impossible for a
  press to leave the gate permanently open; and
* the three routines' bytes say what they were meant to say - a wrong displacement assembles,
  applies and verifies, and then jumps into the middle of an instruction in a running game.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch import (
    AiReviveGatePatch,
    CommandSetLimitPatch,
    QueueIgnoreCpPatch,
    UniqueProductionIdPatch,
)
from sage_patch.addresses import (
    BUILD_ASSISTANT_VTABLE,
    BUILD_GATE_AFFORD,
    BUILD_GATE_AFFORD_BYTES,
    BUILD_GATE_COMMAND_POINTS,
    BUILD_GATE_COMMAND_POINTS_BYTES,
    BUILD_GATE_COMMAND_POINTS_OK,
    BUILD_GATE_COMMAND_POINTS_REFUSE,
    BUILD_GATE_NOT_ENOUGH_COMMAND_POINTS,
    CAN_MAKE_UNIT_PRODUCTION_GATE,
    CAN_MAKE_UNIT_PRODUCTION_GATE_SLOT,
    COMMAND_BUTTON_AUTO_ABILITY,
    COMMAND_BUTTON_CTOR_AUTO_ABILITY,
    COMMAND_BUTTON_CTOR_AUTO_ABILITY_BYTES,
    COMMAND_BUTTON_FIELD_TABLE,
    COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES,
    COMMAND_BUTTON_FIELD_TABLE_REFS,
    COMMAND_BUTTON_FREE_OFFSET,
    COMMAND_BUTTON_SIZE,
    DO_COMMAND_BUTTON_BUTTON_EBP,
    DO_COMMAND_BUTTON_REVIVE_QUEUE,
    DO_COMMAND_BUTTON_REVIVE_QUEUE_BYTES,
    DO_COMMAND_BUTTON_REVIVE_QUEUE_RESUME,
    DO_COMMAND_BUTTON_UNIT_QUEUE,
    DO_COMMAND_BUTTON_UNIT_QUEUE_BYTES,
    DO_COMMAND_BUTTON_UNIT_QUEUE_RESUME,
    FIELD_PARSE_STRIDE,
    INI_PARSE_BOOL,
)
from sage_patch.patches.queue_ignore_cp import (
    DEFAULT_KEYWORD,
    SECTION_NAME,
    build_code,
    build_table,
    rewritten_default,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.test_ai_revive_gate import plant_sites as plant_ai_revive_gate_sites
from tests.sage_patch.test_patching import _plant_commandset_sites, _section_rvas
from tests.sage_patch.test_terrain_resource_exp import _pe32
from tests.sage_patch.test_unique_production_id import (
    plant_sites as plant_unique_production_id_sites,
)

IMAGE_BASE = 0x400000

#: The vtable entry that proves the gate being hooked is the live one.
VTABLE_SLOT = BUILD_ASSISTANT_VTABLE + CAN_MAKE_UNIT_PRODUCTION_GATE_SLOT

#: Where the synthetic image parks the field names, past every site any patch here touches.
STRINGS_VA = 0x00C31000

#: The stock `CommandButton` field table, as ``(keyword, CommandButton offset)``. Read out of the
#: real build; the parse functions are not reproduced because the patch copies every row through
#: by value and never looks at them.
STOCK_FIELDS: tuple[tuple[str, int], ...] = (
    ("Command", 0x14),
    ("Options", 0x1C),
    ("Object", 0x20),
    ("Upgrade", 0x24),
    ("NeededUpgrade", 0x28),
    ("NeededUpgradeAny", 0x34),
    ("BuildUpgrades", 0x38),
    ("WeaponSlot", 0x80),
    ("WeaponSlotToggle1", 0x84),
    ("WeaponSlotToggle2", 0x88),
    ("WeaponSlotToggle3", 0x8C),
    ("FlagsUsedForToggle", 0x90),
    ("MaxShotsToFire", 0xA0),
    ("Science", 0xA4),
    ("SpecialPower", 0x44),
    ("ToggleButtonName", 0x48),
    ("TextLabel", 0x58),
    ("DescriptLabel", 0x64),
    ("PurchasedLabel", 0x70),
    ("ConflictingLabel", 0x74),
    ("LacksPrerequisiteLabel", 0x78),
    ("ButtonImage", 0xB4),
    ("CursorName", 0x50),
    ("InvalidCursorName", 0x54),
    ("ButtonBorderType", 0xB0),
    ("RadiusCursorType", 0x4C),
    ("UnitSpecificSound", 0xC8),
    ("SetAutoAbilityUnitSound", 0xD4),
    ("UnsetAutoAbilityUnitSound", 0xE0),
    ("DoubleClick", 0x100),
    ("Radial", 0x101),
    ("ShowProductionCount", 0x104),
    ("InPalantir", 0x102),
    ("IsClickable", 0x105),
    ("ShowButton", 0x106),
    ("RequireLevel", 0x108),
    ("RequiresValidContainer", 0x107),
    ("AutoAbility", 0x10C),
    ("AffectsKindOf", 0x110),
    ("TriggerWhenReady", 0x12C),
    ("PresetRange", 0x130),
    ("AutoDelay", 0x134),
    ("NeedDamagedTarget", 0x138),
    ("AutoAbilityDisallowedOnModelCondition", 0x13C),
    ("CommandTrigger", 0x188),
    ("EnableOnModelCondition", 0x194),
    ("DisableOnModelCondition", 0x1E0),
    ("CommandRangeStart", 0x22C),
    ("CommandRangeCount", 0x230),
    ("Stances", 0x234),
    ("CreateAHeroUIPrerequisiteButtonName", 0x240),
    ("CreateAHeroUIMinimumLevel", 0x244),
    ("CreateAHeroUIIconImageName", 0x248),
    ("CreateAHeroUIAllowableUpgrades", 0x24C),
    ("CreateAHeroUICostIfSelected", 0x2DC),
)

#: Byte widths for the offsets `STOCK_FIELDS` names, so a test can prove the new field's byte is
#: claimed by none of them. Everything not listed is a dword or larger and is covered by the
#: `AffectsKindOf` bound instead.
_WIDTHS = {0x100: 1, 0x101: 1, 0x102: 1, 0x104: 1, 0x105: 1, 0x106: 1, 0x107: 1, 0x10C: 1}


def _string_vas() -> dict[str, int]:
    vas, cursor = {}, STRINGS_VA
    for name, _offset in STOCK_FIELDS:
        vas[name] = cursor
        cursor += len(name) + 1
    return vas


def plant_sites(data: bytearray) -> None:
    """The clean bytes this patch asserts before writing, plus the stock keyword strings."""

    def at(va: int) -> int:
        return va - IMAGE_BASE

    vas = _string_vas()
    for name, va in vas.items():
        blob = name.encode("ascii") + b"\x00"
        data[at(va) : at(va) + len(blob)] = blob

    table = at(COMMAND_BUTTON_FIELD_TABLE)
    for index, (name, offset) in enumerate(STOCK_FIELDS):
        struct.pack_into(
            "<IIII", data, table + index * FIELD_PARSE_STRIDE, vas[name], INI_PARSE_BOOL, 0, offset
        )
    struct.pack_into("<IIII", data, table + len(STOCK_FIELDS) * FIELD_PARSE_STRIDE, 0, 0, 0, 0)

    for ref_va, opcode in zip(
        COMMAND_BUTTON_FIELD_TABLE_REFS, COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES, strict=True
    ):
        data[at(ref_va)] = opcode
        struct.pack_into("<I", data, at(ref_va) + 1, COMMAND_BUTTON_FIELD_TABLE)

    for va, window in (
        (COMMAND_BUTTON_CTOR_AUTO_ABILITY, COMMAND_BUTTON_CTOR_AUTO_ABILITY_BYTES),
        (DO_COMMAND_BUTTON_UNIT_QUEUE, DO_COMMAND_BUTTON_UNIT_QUEUE_BYTES),
        (DO_COMMAND_BUTTON_REVIVE_QUEUE, DO_COMMAND_BUTTON_REVIVE_QUEUE_BYTES),
        (BUILD_GATE_COMMAND_POINTS, BUILD_GATE_COMMAND_POINTS_BYTES),
        (BUILD_GATE_AFFORD, BUILD_GATE_AFFORD_BYTES),
    ):
        data[at(va) : at(va) + len(window)] = window

    struct.pack_into("<I", data, at(VTABLE_SLOT), CAN_MAKE_UNIT_PRODUCTION_GATE)


def synthetic_image() -> bytearray:
    """A PE32 image carrying every site the patch asserts, with the real original bytes planted."""
    highest = max(
        VTABLE_SLOT + 4,
        STRINGS_VA + sum(len(name) + 1 for name, _ in STOCK_FIELDS),
        COMMAND_BUTTON_FIELD_TABLE + (len(STOCK_FIELDS) + 1) * FIELD_PARSE_STRIDE,
    )
    data = _pe32(highest)
    plant_sites(data)
    return data


@pytest.fixture
def image() -> bytearray:
    return synthetic_image()


def _read(data: bytes | bytearray, va: int, n: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + n])


def _cave(data: bytes | bytearray) -> tuple[int, int]:
    located = find_section(data, SECTION_NAME)
    assert located is not None, f"no {SECTION_NAME} section"
    base_va, _off, vsize = located
    return base_va, vsize


def _table_va(data: bytes | bytearray) -> int:
    """Where the field table lives now, read from the reference the parser uses."""
    push = _read(data, COMMAND_BUTTON_FIELD_TABLE_REFS[1], 5)
    assert push[0] == 0x68
    return struct.unpack_from("<I", push, 1)[0]


# --- the field's home ------------------------------------------------------------------------


def test_new_field_lands_in_alignment_padding() -> None:
    """The byte the patch uses is inside the struct and claimed by no stock field.

    This is what the whole patch rests on: if it did not hold, `sizeof(CommandButton)` and the
    `operator new(0x2E0)` that allocates it would both have to grow."""
    claimed: set[int] = set()
    for _name, offset in STOCK_FIELDS:
        claimed.update(range(offset, offset + _WIDTHS.get(offset, 4)))
    assert COMMAND_BUTTON_FREE_OFFSET not in claimed
    assert COMMAND_BUTTON_FREE_OFFSET < COMMAND_BUTTON_SIZE
    # and it is inside the dword the widened constructor store covers
    covered = range(COMMAND_BUTTON_AUTO_ABILITY + 1, COMMAND_BUTTON_AUTO_ABILITY + 4)
    assert COMMAND_BUTTON_FREE_OFFSET in covered


def test_new_field_sits_below_the_kindof_mask() -> None:
    """`AffectsKindOf` is memset separately, starting at +0x110 - so the padding this patch takes
    ends where that memset begins, and the two cannot overlap."""
    kindof = dict(STOCK_FIELDS)["AffectsKindOf"]
    assert COMMAND_BUTTON_FREE_OFFSET < kindof


def test_rewritten_ctor_widens_the_store_and_changes_one_byte() -> None:
    """`mov byte [esi+0x10C], bl` -> `mov dword [esi+0x10C], ebx`: same length, same operands,
    one opcode byte apart."""
    new = rewritten_default()
    old = COMMAND_BUTTON_CTOR_AUTO_ABILITY_BYTES
    assert len(new) == len(old)
    assert new[0] == 0x89  # mov r/m32, r32
    assert old[0] == 0x88  # mov r/m8, r8
    assert new[1:] == old[1:]
    assert sum(1 for a, b in zip(new, old, strict=True) if a != b) == 1


# --- the rebuilt table -----------------------------------------------------------------------


def _live_entries() -> tuple[tuple[int, int, int, int], ...]:
    vas = _string_vas()
    return tuple((vas[name], INI_PARSE_BOOL, 0, offset) for name, offset in STOCK_FIELDS)


def test_table_keeps_the_live_rows_verbatim() -> None:
    entries = _live_entries()
    table = build_table(entries, 0x00F00000)
    for index, entry in enumerate(entries):
        assert struct.unpack_from("<IIII", table, index * FIELD_PARSE_STRIDE) == entry


def test_table_appends_one_bool_row_and_a_terminator() -> None:
    entries = _live_entries()
    keyword_va = 0x00F00000
    table = build_table(entries, keyword_va)
    assert len(table) == (len(entries) + 2) * FIELD_PARSE_STRIDE
    row = struct.unpack_from("<IIII", table, len(entries) * FIELD_PARSE_STRIDE)
    assert row == (keyword_va, INI_PARSE_BOOL, 0, COMMAND_BUTTON_FREE_OFFSET)
    assert table[-FIELD_PARSE_STRIDE:] == bytes(FIELD_PARSE_STRIDE)


# --- the cave's code -------------------------------------------------------------------------


def _decode_jmp(code: bytes, base: int, at: int) -> int:
    assert code[at] == 0xE9, f"expected a jmp rel32 at +0x{at:x}, got 0x{code[at]:02x}"
    return base + at + 5 + struct.unpack_from("<i", code, at + 1)[0]


@pytest.mark.parametrize(
    ("label", "window", "resume"),
    [
        ("unit_build", DO_COMMAND_BUTTON_UNIT_QUEUE_BYTES, DO_COMMAND_BUTTON_UNIT_QUEUE_RESUME),
        ("revive", DO_COMMAND_BUTTON_REVIVE_QUEUE_BYTES, DO_COMMAND_BUTTON_REVIVE_QUEUE_RESUME),
    ],
)
def test_wrapper_arms_runs_the_displaced_call_then_disarms(
    label: str, window: bytes, resume: int
) -> None:
    """Decode a wrapper by hand. The order is the whole safety argument: the flag is cleared by
    the same routine that set it, after the displaced call and before the jump back."""
    base = 0x00F00000
    asm = build_code(base, flag_va=0x00F10000)
    code = asm.finish()
    start = asm.label_va(label) - base
    body = code[start:]

    assert body[0:3] == bytes([0x8B, 0x45, DO_COMMAND_BUTTON_BUTTON_EBP])  # mov eax, [ebp+8]
    assert body[3:6] == bytes([0x0F, 0xB6, 0x80])  # movzx eax, byte [eax+disp32]
    assert struct.unpack_from("<I", body, 6)[0] == COMMAND_BUTTON_FREE_OFFSET
    assert body[10] == 0xA3  # mov [flag], eax
    assert struct.unpack_from("<I", body, 11)[0] == 0x00F10000

    displaced = 15
    assert body[displaced : displaced + len(window)] == window

    disarm = displaced + len(window)
    assert body[disarm : disarm + 2] == bytes([0x83, 0x25])  # and dword [disp32], imm8
    assert struct.unpack_from("<I", body, disarm + 2)[0] == 0x00F10000
    assert body[disarm + 6] == 0x00

    assert _decode_jmp(code, base, start + disarm + 7) == resume


def test_gate_accepts_when_the_stock_verdict_does() -> None:
    """`test al, al` / `jne` straight to the engine's own accept edge - so a press that has the
    command points takes the same path it always did."""
    base = 0x00F00000
    asm = build_code(base, flag_va=0x00F10000)
    code = asm.finish()
    start = asm.label_va("gate") - base
    body = code[start:]

    assert body[0:2] == bytes([0x84, 0xC0])  # test al, al
    assert body[2] == 0x75  # jne rel8
    allow_at = 4 + body[3]
    assert _decode_jmp(body, base + start, allow_at) == BUILD_GATE_COMMAND_POINTS_OK


def test_gate_consults_the_flag_and_still_refuses_with_the_engines_own_code() -> None:
    base = 0x00F00000
    asm = build_code(base, flag_va=0x00F10000)
    code = asm.finish()
    start = asm.label_va("gate") - base
    body = code[start:]

    assert body[4:6] == bytes([0x83, 0x3D])  # cmp dword [disp32], imm8
    assert struct.unpack_from("<I", body, 6)[0] == 0x00F10000
    assert body[10] == 0x00
    assert body[11] == 0x74  # je rel8 -> refuse
    refuse_at = 13 + body[12]

    assert body[refuse_at] == 0x6A  # push imm8
    assert body[refuse_at + 1] == BUILD_GATE_NOT_ENOUGH_COMMAND_POINTS
    assert _decode_jmp(body, base + start, refuse_at + 2) == BUILD_GATE_COMMAND_POINTS_REFUSE


def test_only_the_gate_reads_the_flag() -> None:
    """Two writes (one per wrapper) and one read. A second reader would mean a press could be
    observed by something other than the gate it was raised for."""
    flag_va = 0x00F10000
    code = build_code(0x00F00000, flag_va).finish()
    needle = struct.pack("<I", flag_va)
    assert code.count(bytes([0xA3]) + needle) == 2  # mov [flag], eax
    assert code.count(bytes([0x83, 0x25]) + needle) == 2  # and dword [flag], 0
    assert code.count(bytes([0x83, 0x3D]) + needle) == 1  # cmp dword [flag], 0


def test_code_is_position_independent() -> None:
    """Built at two addresses, only the absolute references differ - the routine bodies do not."""
    a = build_code(0x00F00000, 0x00F10000).finish()
    b = build_code(0x00F02000, 0x00F10000).finish()
    assert len(a) == len(b)
    differing = [i for i, (x, y) in enumerate(zip(a, b, strict=True)) if x != y]
    assert len(differing) <= 5 * 4  # the five rel32s out of the cave


# --- apply -------------------------------------------------------------------------------------


def test_apply_writes_every_site(image: bytearray) -> None:
    QueueIgnoreCpPatch().apply(image)
    base_va, vsize = _cave(image)

    assert _read(image, COMMAND_BUTTON_CTOR_AUTO_ABILITY, 6) == rewritten_default()

    table_va = _table_va(image)
    assert table_va != COMMAND_BUTTON_FIELD_TABLE
    assert base_va <= table_va < base_va + vsize

    for va, window in (
        (DO_COMMAND_BUTTON_UNIT_QUEUE, DO_COMMAND_BUTTON_UNIT_QUEUE_BYTES),
        (DO_COMMAND_BUTTON_REVIVE_QUEUE, DO_COMMAND_BUTTON_REVIVE_QUEUE_BYTES),
        (BUILD_GATE_COMMAND_POINTS, BUILD_GATE_COMMAND_POINTS_BYTES),
    ):
        hook = _read(image, va, len(window))
        assert hook[0] == 0xE9
        assert hook[5:] == b"\x90" * (len(window) - 5)
        target = va + 5 + struct.unpack_from("<i", hook, 1)[0]
        assert base_va <= target < base_va + vsize


def test_apply_repoints_all_three_table_references(image: bytearray) -> None:
    """The two `push`es the parser uses and the static accessor. Leaving any of them naming the
    stock table would leave a reader that never learns about the new field."""
    QueueIgnoreCpPatch().apply(image)
    table_va = _table_va(image)
    for ref_va, opcode in zip(
        COMMAND_BUTTON_FIELD_TABLE_REFS, COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES, strict=True
    ):
        ref = _read(image, ref_va, 5)
        assert ref[0] == opcode
        assert struct.unpack_from("<I", ref, 1)[0] == table_va


def test_apply_leaves_the_stock_table_where_it_was(image: bytearray) -> None:
    """The old table is abandoned, not edited: rewriting `.rdata` in place is exactly the kind of
    edit that collides with another patch."""
    before = _read(image, COMMAND_BUTTON_FIELD_TABLE, (len(STOCK_FIELDS) + 1) * FIELD_PARSE_STRIDE)
    QueueIgnoreCpPatch().apply(image)
    after = _read(image, COMMAND_BUTTON_FIELD_TABLE, (len(STOCK_FIELDS) + 1) * FIELD_PARSE_STRIDE)
    assert after == before


def test_cave_holds_the_keyword_the_new_row_points_at(image: bytearray) -> None:
    QueueIgnoreCpPatch(keyword="QueueOverCap").apply(image)
    table_va = _table_va(image)
    row = struct.unpack(
        "<IIII", _read(image, table_va + len(STOCK_FIELDS) * FIELD_PARSE_STRIDE, 16)
    )
    name_va, parse, user, offset = row
    assert (parse, user, offset) == (INI_PARSE_BOOL, 0, COMMAND_BUTTON_FREE_OFFSET)
    assert _read(image, name_va, 13) == b"QueueOverCap\x00"


def test_the_flag_starts_at_zero(image: bytearray) -> None:
    """It is data in an appended section, so it is zero at load - which is the only state that
    means "no press is in flight"."""
    QueueIgnoreCpPatch().apply(image)
    base_va, _vsize = _cave(image)
    assert _read(image, base_va, 4) == bytes(4)


def test_default_keyword() -> None:
    assert DEFAULT_KEYWORD == "QueueIgnoreCP"


def test_ini_surface_names_the_field_it_installed(image: bytearray) -> None:
    surface = QueueIgnoreCpPatch(keyword="QueueOverCap").ini_surface()
    assert [(f.block, f.name, f.type, f.default) for f in surface.fields] == [
        ("CommandButton", "QueueOverCap", "Bool", False)
    ]


# --- verify ------------------------------------------------------------------------------------


def test_verify_clean_after_apply(image: bytearray) -> None:
    patch = QueueIgnoreCpPatch()
    patch.apply(image)
    assert patch.verify(image) == []


def test_verify_clean_for_a_custom_keyword(image: bytearray) -> None:
    patch = QueueIgnoreCpPatch(keyword="QueueOverCap")
    patch.apply(image)
    assert patch.verify(image) == []


def test_verify_rejects_an_unpatched_image(image: bytearray) -> None:
    assert QueueIgnoreCpPatch().verify(image) != []


def test_verify_rejects_the_wrong_keyword(image: bytearray) -> None:
    QueueIgnoreCpPatch(keyword="QueueOverCap").apply(image)
    assert QueueIgnoreCpPatch().verify(image) != []


@pytest.mark.parametrize(
    "va",
    [
        COMMAND_BUTTON_CTOR_AUTO_ABILITY,
        DO_COMMAND_BUTTON_UNIT_QUEUE,
        DO_COMMAND_BUTTON_REVIVE_QUEUE,
        BUILD_GATE_COMMAND_POINTS,
        *COMMAND_BUTTON_FIELD_TABLE_REFS,
    ],
)
def test_verify_catches_a_reverted_site(image: bytearray, va: int) -> None:
    patch = QueueIgnoreCpPatch()
    patch.apply(image)
    off = va_to_offset(image, va)
    assert off is not None
    image[off : off + 4] = b"\x00\x00\x00\x00"
    assert patch.verify(image) != []


def test_detect_recovers_the_keyword(image: bytearray) -> None:
    QueueIgnoreCpPatch(keyword="QueueOverCap").apply(image)
    found = QueueIgnoreCpPatch.detect(image)
    assert found is not None
    assert found.keyword == "QueueOverCap"


def test_detect_finds_nothing_in_an_unpatched_image(image: bytearray) -> None:
    assert QueueIgnoreCpPatch.detect(image) is None


# --- refusals ------------------------------------------------------------------------------------


def test_apply_refuses_a_second_time(image: bytearray) -> None:
    """The table is read from its live references, so the second run sees the field it added the
    first time and raises rather than stacking two caves."""
    QueueIgnoreCpPatch().apply(image)
    with pytest.raises(ValueError, match="already"):
        QueueIgnoreCpPatch().apply(image)


def test_apply_refuses_a_keyword_the_block_already_has(image: bytearray) -> None:
    with pytest.raises(ValueError, match="already has"):
        QueueIgnoreCpPatch(keyword="AutoAbility").apply(image)


def test_apply_refuses_when_the_vtable_names_another_gate(image: bytearray) -> None:
    off = va_to_offset(image, VTABLE_SLOT)
    assert off is not None
    struct.pack_into("<I", image, off, CAN_MAKE_UNIT_PRODUCTION_GATE + 0x10)
    with pytest.raises(ValueError, match="not the live one"):
        QueueIgnoreCpPatch().apply(image)


def test_apply_refuses_when_the_table_is_not_this_build(image: bytearray) -> None:
    off = va_to_offset(image, COMMAND_BUTTON_FIELD_TABLE)
    assert off is not None
    struct.pack_into("<I", image, off + 12, 0x99)  # `Command` at some other offset
    with pytest.raises(ValueError, match="unexpected build"):
        QueueIgnoreCpPatch().apply(image)


def test_apply_refuses_when_the_table_references_disagree(image: bytearray) -> None:
    off = va_to_offset(image, COMMAND_BUTTON_FIELD_TABLE_REFS[2])
    assert off is not None
    struct.pack_into("<I", image, off + 1, COMMAND_BUTTON_FIELD_TABLE + 0x40)
    with pytest.raises(ValueError, match="disagree"):
        QueueIgnoreCpPatch().apply(image)


@pytest.mark.parametrize("keyword", ["", "9Lives", "Queue Ignore CP", "Queue-Ignore-CP", "a" * 80])
def test_constructor_refuses_an_unparseable_keyword(keyword: str) -> None:
    with pytest.raises(ValueError, match="INI keyword"):
        QueueIgnoreCpPatch(keyword=keyword)


# --- composition ---------------------------------------------------------------------------------


def test_the_gate_windows_of_the_two_verdicts_are_disjoint() -> None:
    """`second-resource` takes the money verdict in the same function. The two windows must not
    touch, or whichever patch is applied second raises."""
    money = range(BUILD_GATE_AFFORD, BUILD_GATE_AFFORD + len(BUILD_GATE_AFFORD_BYTES))
    ours = range(
        BUILD_GATE_COMMAND_POINTS,
        BUILD_GATE_COMMAND_POINTS + len(BUILD_GATE_COMMAND_POINTS_BYTES),
    )
    assert set(money).isdisjoint(ours)
    # and our accept edge is past the money verdict's, so neither jumps into the other's bytes
    assert BUILD_GATE_COMMAND_POINTS_OK > money.stop


#: Comfortably past the highest site any of the four patches below touches.
_COMPOSABLE_TOP = 0x00C80000


def _composable_image() -> bytearray:
    """One image carrying this patch's sites and those of the three it is applied alongside."""
    data = _pe32(_COMPOSABLE_TOP)
    plant_sites(data)
    _plant_commandset_sites(data)
    plant_ai_revive_gate_sites(data)
    plant_unique_production_id_sites(data)
    return data


def test_composes_with_the_other_patches_in_either_order() -> None:
    """Any order produces a binary every patch still verifies, and the section table stays sorted
    by RVA - the property `allocate_section` exists to hold."""
    ours, other = QueueIgnoreCpPatch(), UniqueProductionIdPatch()
    first, second = _composable_image(), _composable_image()

    ours.apply(first)
    other.apply(first)
    other.apply(second)
    ours.apply(second)

    for data in (first, second):
        assert ours.verify(data) == []
        assert other.verify(data) == []
        rvas = _section_rvas(data)
        assert rvas == sorted(rvas)


def test_composes_with_the_patches_that_share_no_bytes() -> None:
    data = _composable_image()
    for patch in (CommandSetLimitPatch(count=64), AiReviveGatePatch(), QueueIgnoreCpPatch()):
        patch.apply(data)
    assert QueueIgnoreCpPatch().verify(data) == []
    assert AiReviveGatePatch().verify(data) == []


def test_touches_no_byte_another_patch_touches() -> None:
    """`ai-revive-gate` edits the same *function* family - `canMakeUnit` and the gate that calls
    it - so this is the pair worth asserting rather than assuming."""
    base = _composable_image()
    ours = _composable_image()
    QueueIgnoreCpPatch().apply(ours)
    changed_by_ours = {i for i in range(len(base)) if base[i] != ours[i]}

    others = _composable_image()
    for patch in (CommandSetLimitPatch(count=64), AiReviveGatePatch(), UniqueProductionIdPatch()):
        patch.apply(others)
    changed_by_others = {i for i in range(min(len(base), len(others))) if base[i] != others[i]}

    overlap = changed_by_ours & changed_by_others
    # both append sections, so the PE header's section count and SizeOfImage move for either
    header_end = 0x400
    assert {i for i in overlap if i >= header_end} == set()


def test_registered_under_its_name() -> None:
    assert PATCHES[QueueIgnoreCpPatch.name] is QueueIgnoreCpPatch
