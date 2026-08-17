"""Tests for the cooldown-through-death patch.

The structural checks are the usual ones - the cave's layout, the seven edits, the round trip
through `verify`. The rest hold the properties the patch's correctness actually rests on, none of
which "it applies cleanly" would catch:

* the two new fields land in `SpecialPowerTemplate`'s interior padding, so ``sizeof`` stays
  `0x88` and the three `operator new(0x88)` sites are left alone - which is also what lets this
  patch compose with `hero-mana`, whose field grows the struct instead;
* the widened constructor store really does cover both new bytes, since `operator new` does not
  zero the block and a field that starts as heap garbage would change behaviour on data that
  never named the keyword;
* the widened copy pair really does carry them through a `DefaultSpecialPower` block;
* the rebuilt table keeps the live rows *verbatim*, because their name pointers are absolute;
* the snapshot hook runs the call it displaced **before** anything else, so a hero reaches the
  revive list whatever the cave then does; and
* the routines' bytes say what they were meant to say - a wrong displacement assembles, applies
  and verifies, and then jumps into the middle of an instruction in a running game.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.addresses import (
    FIELD_PARSE_STRIDE,
    INI_PARSE_BOOL,
    SPECIAL_POWER_FIELD_TABLE,
    SPECIAL_POWER_FIELD_TABLE_REF_OPCODES,
    SPECIAL_POWER_FIELD_TABLE_REFS,
    SPECIAL_POWER_TEMPLATE_SIZE,
)
from sage_patch.patches.experimental.cooldown_through_death import (
    ADD_HERO,
    ADD_HERO_CALL,
    ADD_HERO_CALL_BYTES,
    ADD_HERO_RESUME,
    ANCHORS,
    DEFAULT_PERSIST_KEYWORD,
    DEFAULT_TICKS_KEYWORD,
    SECTION_NAME,
    SLOT_STRIDE,
    SLOTS,
    TEMPLATE_COPY_LOAD,
    TEMPLATE_COPY_LOAD_BYTES,
    TEMPLATE_COPY_STORE,
    TEMPLATE_COPY_STORE_BYTES,
    TEMPLATE_CTOR_BOOLS,
    TEMPLATE_CTOR_BOOLS_BYTES,
    TEMPLATE_PERSIST,
    TEMPLATE_TICKS,
    UPGRADE_MASK_CALL,
    UPGRADE_MASK_CALL_BYTES,
    UPGRADE_MASK_RESTORE,
    UPGRADE_MASK_RESUME,
    CooldownThroughDeathPatch,
    build_table,
    rewritten_copy_load,
    rewritten_copy_store,
    rewritten_ctor,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.test_terrain_resource_exp import _pe32

IMAGE_BASE = 0x400000

#: Where the synthetic image parks the field-name strings, past every site the patch touches.
STRINGS_VA = 0x00DB0000

#: Scratch room for the test that stands in for a *later* patch rebuilding the same table.
RELOCATED_TABLE_VA = 0x00DB4000
RELOCATED_TABLE_SIZE = 0x400

#: The stock `SpecialPower` field table, as ``(keyword, SpecialPowerTemplate offset)``, in the
#: order the real build holds them. The parse functions are not reproduced because the patch copies
#: every row through by value and never looks at them.
STOCK_FIELDS: tuple[tuple[str, int], ...] = (
    ("Flags", 0x18),
    ("ReloadTime", 0x20),
    ("RequiredSciences", 0x24),
    ("LightPointCost", 0x30),
    ("InitiateSound", 0x34),
    ("InitiateAtLocationSound", 0x38),
    ("UnitSpecificSoundToUseAsInitiateIntendToDoVoice", 0x3C),
    ("UnitSpecificSoundToUseAsEnterStateInitiateIntendToDoVoice", 0x40),
    ("EvaEventToPlayOnSuccess", 0x44),
    ("PublicTimer", 0x58),
    ("Enum", 0x1C),
    ("DetectionTime", 0x48),
    ("SharedSyncedTimer", 0x59),
    ("ViewObjectDuration", 0x4C),
    ("ViewObjectRange", 0x50),
    ("RadiusCursorRadius", 0x54),
    ("PalantirMovie", 0x5C),
    ("ObjectFilter", 0x60),
    ("PreventActivationConditions", 0x64),
    ("MaxCastRange", 0x74),
    ("ForbiddenObjectFilter", 0x78),
    ("ForbiddenObjectRange", 0x7C),
    ("UnitCost", 0x80),
    ("UnitCostDeathType", 0x84),
)

#: Byte widths for the offsets `STOCK_FIELDS` names. The two `Bool`s are the only single bytes in
#: the block; everything else is a dword or larger, which is what makes the gap behind them a gap.
_WIDTHS = {0x58: 1, 0x59: 1}


def _string_vas() -> dict[str, int]:
    vas, cursor = {}, STRINGS_VA
    for name, _offset in STOCK_FIELDS:
        vas[name] = cursor
        cursor += len(name) + 1
    return vas


def plant_sites(data: bytearray) -> None:
    """The clean bytes this patch asserts before writing, plus the stock keyword strings.

    Every window in `ANCHORS` is planted, not just the five the patch rewrites: the anchors are
    what `apply` refuses on, so a synthetic image that omitted one would test the refusal rather
    than the patch."""

    def at(va: int) -> int:
        return va - IMAGE_BASE

    for va, window in ANCHORS.items():
        data[at(va) : at(va) + len(window)] = window

    vas = _string_vas()
    for name, va in vas.items():
        blob = name.encode("ascii") + b"\x00"
        data[at(va) : at(va) + len(blob)] = blob

    table = at(SPECIAL_POWER_FIELD_TABLE)
    for index, (name, offset) in enumerate(STOCK_FIELDS):
        struct.pack_into(
            "<IIII", data, table + index * FIELD_PARSE_STRIDE, vas[name], INI_PARSE_BOOL, 0, offset
        )
    struct.pack_into("<IIII", data, table + len(STOCK_FIELDS) * FIELD_PARSE_STRIDE, 0, 0, 0, 0)

    for ref_va, opcode in zip(
        SPECIAL_POWER_FIELD_TABLE_REFS, SPECIAL_POWER_FIELD_TABLE_REF_OPCODES, strict=True
    ):
        data[at(ref_va)] = opcode
        struct.pack_into("<I", data, at(ref_va) + 1, SPECIAL_POWER_FIELD_TABLE)


def synthetic_image() -> bytearray:
    """A PE32 image carrying every site the patch asserts, with the real original bytes planted."""
    highest = max(
        max(va + len(window) for va, window in ANCHORS.items()),
        STRINGS_VA + sum(len(name) + 1 for name, _ in STOCK_FIELDS),
        SPECIAL_POWER_FIELD_TABLE + (len(STOCK_FIELDS) + 1) * FIELD_PARSE_STRIDE,
        RELOCATED_TABLE_VA + RELOCATED_TABLE_SIZE,
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
    push = _read(data, SPECIAL_POWER_FIELD_TABLE_REFS[1], 5)
    assert push[0] == 0x68
    return struct.unpack_from("<I", push, 1)[0]


def _rows(data: bytes | bytearray, table_va: int) -> list[tuple[int, int, int, int]]:
    rows = []
    index = 0
    while True:
        row = struct.unpack(
            "<IIII", _read(data, table_va + index * FIELD_PARSE_STRIDE, FIELD_PARSE_STRIDE)
        )
        if row[0] == 0 and row[1] == 0:
            return rows
        rows.append(row)
        index += 1


def _jump_target(data: bytes | bytearray, va: int) -> int:
    window = _read(data, va, 5)
    assert window[0] == 0xE9, f"0x{va:08x} does not hold a jmp rel32"
    return va + 5 + struct.unpack_from("<i", window, 1)[0]


def _call_target(data: bytes | bytearray, va: int) -> int:
    window = _read(data, va, 5)
    assert window[0] == 0xE8, f"0x{va:08x} does not hold a call rel32"
    return va + 5 + struct.unpack_from("<i", window, 1)[0]


# --- where the two fields live ----------------------------------------------------------------


def test_both_fields_land_in_interior_padding() -> None:
    """The two bytes the patch uses are inside the struct and claimed by no stock field.

    This is what the whole patch rests on: if it did not hold, `sizeof(SpecialPowerTemplate)` and
    the three `operator new(0x88)` sites would have to grow - which is exactly the price
    `hero-mana` pays for its own field, and exactly what this patch avoids paying."""
    claimed: set[int] = set()
    for _name, offset in STOCK_FIELDS:
        claimed.update(range(offset, offset + _WIDTHS.get(offset, 4)))
    assert TEMPLATE_PERSIST not in claimed
    assert TEMPLATE_TICKS not in claimed
    assert TEMPLATE_TICKS < SPECIAL_POWER_TEMPLATE_SIZE


def test_the_padding_is_exactly_the_gap_behind_the_two_bools() -> None:
    """`PublicTimer` and `SharedSyncedTimer` are single bytes at +0x58/+0x59 and the next field is
    a dword at +0x5C, so the gap is two bytes wide and both of them are used."""
    fields = dict(STOCK_FIELDS)
    assert fields["PublicTimer"] == 0x58
    assert fields["SharedSyncedTimer"] == 0x59
    assert fields["PalantirMovie"] == 0x5C
    assert (TEMPLATE_PERSIST, TEMPLATE_TICKS) == (0x5A, 0x5B)


def test_both_fields_are_inside_the_widened_ctor_store() -> None:
    """The constructor zeroes them by writing a dword at +0x58, so both have to be within it."""
    covered = range(0x58, 0x58 + 4)
    assert TEMPLATE_PERSIST in covered
    assert TEMPLATE_TICKS in covered


# --- the three single-bit edits ---------------------------------------------------------------


def test_rewritten_ctor_widens_the_store_and_changes_one_byte() -> None:
    """`mov byte [esi+0x58], bl` -> `mov dword [esi+0x58], ebx`: same length, same operands, one
    opcode byte apart, so there is no hook and no displaced instruction."""
    new, old = rewritten_ctor(), TEMPLATE_CTOR_BOOLS_BYTES
    assert len(new) == len(old)
    assert new[1:] == old[1:]
    assert (old[0], new[0]) == (0x88, 0x89)


def test_rewritten_copy_pair_widens_the_same_way() -> None:
    """The load and the store both widen, and neither changes length - `eax` is already the scratch
    register the copies either side of them use."""
    for new, old, want in (
        (rewritten_copy_load(), TEMPLATE_COPY_LOAD_BYTES, (0x8A, 0x8B)),
        (rewritten_copy_store(), TEMPLATE_COPY_STORE_BYTES, (0x88, 0x89)),
    ):
        assert len(new) == len(old)
        assert new[1:] == old[1:]
        assert (old[0], new[0]) == want


def test_the_copy_edits_do_not_touch_hero_manas_hook() -> None:
    """`hero-mana` displaces the copy constructor's epilogue at 0x007B1F53. Both patches edit the
    same routine, and this is the assertion that they edit different bytes of it."""
    assert TEMPLATE_COPY_STORE + len(TEMPLATE_COPY_STORE_BYTES) <= 0x007B1F53


# --- applying -----------------------------------------------------------------------------------


def test_apply_writes_every_site(image: bytearray) -> None:
    CooldownThroughDeathPatch().apply(image)
    base_va, vsize = _cave(image)

    assert _read(image, TEMPLATE_CTOR_BOOLS, 3) == rewritten_ctor()
    assert _read(image, TEMPLATE_COPY_LOAD, 3) == rewritten_copy_load()
    assert _read(image, TEMPLATE_COPY_STORE, 3) == rewritten_copy_store()

    table_va = _table_va(image)
    assert table_va != SPECIAL_POWER_FIELD_TABLE
    assert base_va <= table_va < base_va + vsize

    for va in (ADD_HERO_CALL, UPGRADE_MASK_CALL):
        assert base_va <= _jump_target(image, va) < base_va + vsize


def test_apply_repoints_both_table_references(image: bytearray) -> None:
    """Leaving either of them naming the stock table would leave a reader that never learns about
    the two new fields - the accessor and the parse call have to agree."""
    CooldownThroughDeathPatch().apply(image)
    table_va = _table_va(image)
    for ref_va, opcode in zip(
        SPECIAL_POWER_FIELD_TABLE_REFS, SPECIAL_POWER_FIELD_TABLE_REF_OPCODES, strict=True
    ):
        ref = _read(image, ref_va, 5)
        assert ref[0] == opcode
        assert struct.unpack_from("<I", ref, 1)[0] == table_va


def test_apply_leaves_the_stock_table_where_it_was(image: bytearray) -> None:
    """The old table is abandoned, not edited: rewriting `.rdata` in place is exactly the kind of
    edit that collides with another patch."""
    span = (len(STOCK_FIELDS) + 1) * FIELD_PARSE_STRIDE
    before = _read(image, SPECIAL_POWER_FIELD_TABLE, span)
    CooldownThroughDeathPatch().apply(image)
    assert _read(image, SPECIAL_POWER_FIELD_TABLE, span) == before


def test_rebuilt_table_keeps_the_live_rows_verbatim(image: bytearray) -> None:
    """Every pointer in a row is absolute, so a copied row still names the string it always did."""
    before = _rows(image, SPECIAL_POWER_FIELD_TABLE)
    CooldownThroughDeathPatch().apply(image)
    after = _rows(image, _table_va(image))
    assert after[: len(before)] == before
    assert len(after) == len(before) + 2


def test_rebuilt_table_appends_two_bools_at_the_padding(image: bytearray) -> None:
    patch = CooldownThroughDeathPatch()
    patch.apply(image)
    persist, ticks = _rows(image, _table_va(image))[-2:]
    for row, offset in ((persist, TEMPLATE_PERSIST), (ticks, TEMPLATE_TICKS)):
        assert row[1] == INI_PARSE_BOOL
        assert row[2] == 0
        assert row[3] == offset
    base_va, vsize = _cave(image)
    for row, keyword in (
        (persist, patch.persist_keyword),
        (ticks, patch.ticks_keyword),
    ):
        assert base_va <= row[0] < base_va + vsize
        assert _read(image, row[0], len(keyword) + 1) == keyword.encode() + b"\x00"


def test_build_table_is_terminated() -> None:
    """The reader walks to the terminator and never to a count, so the rebuilt table has to carry
    one - a missing terminator reads whatever follows the cave as more fields."""
    table = build_table((), 0x1000, 0x2000)
    assert table[-FIELD_PARSE_STRIDE:] == bytes(FIELD_PARSE_STRIDE)


# --- the cave ------------------------------------------------------------------------------------


def test_snapshot_hook_runs_the_displaced_call_first(image: bytearray) -> None:
    """The hook stands in for the call that puts the hero on the revive list. Running it first is
    what makes every later exit harmless: the hero is listed before the cave can decide anything,
    and `pushad` carries the record index it returned back to the caller."""
    CooldownThroughDeathPatch().apply(image)
    entry = _jump_target(image, ADD_HERO_CALL)
    assert _call_target(image, entry) == ADD_HERO
    assert _read(image, entry + 5, 1) == b"\x60"  # pushad, before anything else


def test_restore_hook_runs_the_displaced_call_first(image: bytearray) -> None:
    """Same shape on the other side: the upgrade mask lands on the new object before any cooldown
    does, so a hero the cave then skips is exactly a stock hero."""
    CooldownThroughDeathPatch().apply(image)
    entry = _jump_target(image, UPGRADE_MASK_CALL)
    assert _call_target(image, entry) == UPGRADE_MASK_RESTORE
    assert _read(image, entry + 5, 1) == b"\x60"


@pytest.mark.parametrize(
    ("site", "window", "resume"),
    [
        (ADD_HERO_CALL, ADD_HERO_CALL_BYTES, ADD_HERO_RESUME),
        (UPGRADE_MASK_CALL, UPGRADE_MASK_CALL_BYTES, UPGRADE_MASK_RESUME),
    ],
)
def test_hooks_resume_at_the_instruction_after_the_site(
    image: bytearray, site: int, window: bytes, resume: int
) -> None:
    """A resume address one byte out lands in the middle of an instruction, which assembles,
    applies and verifies exactly like a correct one."""
    assert resume == site + len(window)
    CooldownThroughDeathPatch().apply(image)
    base_va, vsize = _cave(image)
    entry = _jump_target(image, site)
    tail = _read(image, base_va, vsize)
    # the routine ends with `popad` + `jmp <resume>`; searching forward from its entry finds its
    # own epilogue rather than the other hook's
    jmp_off = tail.index(b"\x61\xe9", entry - base_va) + 1
    target = base_va + jmp_off + 5 + struct.unpack_from("<i", tail, jmp_off + 1)[0]
    assert target == resume


def test_slot_table_starts_empty(image: bytearray) -> None:
    """A slot is free when its power pointer is NULL, so an all-zero table is an empty one - and
    the section carries the zeros rather than claiming uninitialised virtual size, so what the
    table starts as is a fact about the file."""
    CooldownThroughDeathPatch().apply(image)
    base_va, vsize = _cave(image)
    blob = _read(image, base_va, vsize)
    assert blob.count(b"\x00" * (SLOTS * SLOT_STRIDE)) == 1


def test_the_epoch_starts_at_zero(image: bytearray) -> None:
    """The epoch is the frame the table was last touched on, and it opens the cave. Zero is the
    only safe start: the first logic frame either hook sees is at least that, so a fresh image
    never wipes a table that is already empty."""
    CooldownThroughDeathPatch().apply(image)
    base_va, _vsize = _cave(image)
    assert struct.unpack("<I", _read(image, base_va, 4))[0] == 0


def test_cave_is_writable(image: bytearray) -> None:
    """Unlike every other cave in this package, this one holds a table the game writes. A
    read-only section would fault on the first hero death rather than on the first test."""
    CooldownThroughDeathPatch().apply(image)
    off = struct.unpack_from("<I", image, 0x3C)[0]
    count = struct.unpack_from("<H", image, off + 6)[0]
    size_opt = struct.unpack_from("<H", image, off + 20)[0]
    table = off + 24 + size_opt
    for index in range(count):
        header = table + index * 40
        if image[header : header + 8].rstrip(b"\x00") == SECTION_NAME.encode():
            characteristics = struct.unpack_from("<I", image, header + 36)[0]
            assert characteristics & 0x80000000, "the cave is not writable"
            assert characteristics & 0x20000000, "the cave is not executable"
            return
    pytest.fail(f"no {SECTION_NAME} section")


# --- verify, detect, and refusing ---------------------------------------------------------------


def test_verify_clean_after_apply(image: bytearray) -> None:
    patch = CooldownThroughDeathPatch()
    patch.apply(image)
    assert patch.verify(image) == []


def test_verify_clean_for_custom_keywords(image: bytearray) -> None:
    patch = CooldownThroughDeathPatch("KeepCooldownWhenSlain", "CooldownRunsWhileSlain")
    patch.apply(image)
    assert patch.verify(image) == []


def test_verify_survives_a_later_patch_rebuilding_the_table(image: bytearray) -> None:
    """`hero-mana` adds its own `SpecialPower` field, so on a binary carrying both, whichever went
    second owns the table and the references name *its* cave.

    That is a working binary - both fields parse - so `verify` has to hold the invariant that
    matters (the live table still carries these two rows, pointing at this cave's strings and
    writing this cave's bytes) rather than the one that is easy to check (the references still
    name this patch's own table). Applying the two in the other order is otherwise a clean apply
    followed by a `verify` that says the patch is not there."""
    patch = CooldownThroughDeathPatch()
    patch.apply(image)
    assert patch.verify(image) == []

    # stand in for the later patch: copy the live table somewhere else, append a row of its own,
    # and repoint both references at the copy
    live_va = _table_va(image)
    rows = _rows(image, live_va)
    off = va_to_offset(image, RELOCATED_TABLE_VA)
    assert off is not None
    for index, row in enumerate(rows):
        struct.pack_into("<IIII", image, off + index * FIELD_PARSE_STRIDE, *row)
    struct.pack_into(
        "<IIII", image, off + len(rows) * FIELD_PARSE_STRIDE, STRINGS_VA, INI_PARSE_BOOL, 0, 0x88
    )
    struct.pack_into("<IIII", image, off + (len(rows) + 1) * FIELD_PARSE_STRIDE, 0, 0, 0, 0)
    for ref_va, opcode in zip(
        SPECIAL_POWER_FIELD_TABLE_REFS, SPECIAL_POWER_FIELD_TABLE_REF_OPCODES, strict=True
    ):
        ref_off = va_to_offset(image, ref_va)
        assert ref_off is not None
        image[ref_off] = opcode
        struct.pack_into("<I", image, ref_off + 1, RELOCATED_TABLE_VA)

    assert patch.verify(image) == []


def test_verify_rejects_a_table_that_dropped_the_fields(image: bytearray) -> None:
    """The other half of the invariant: a table the patch's rows are gone from is a binary that no
    longer parses them, whoever rebuilt it."""
    patch = CooldownThroughDeathPatch()
    patch.apply(image)
    off = va_to_offset(image, RELOCATED_TABLE_VA)
    assert off is not None
    struct.pack_into("<IIII", image, off, 0, 0, 0, 0)  # an empty table
    for ref_va, opcode in zip(
        SPECIAL_POWER_FIELD_TABLE_REFS, SPECIAL_POWER_FIELD_TABLE_REF_OPCODES, strict=True
    ):
        ref_off = va_to_offset(image, ref_va)
        assert ref_off is not None
        image[ref_off] = opcode
        struct.pack_into("<I", image, ref_off + 1, RELOCATED_TABLE_VA)
    assert patch.verify(image) != []


def test_verify_rejects_an_unpatched_image(image: bytearray) -> None:
    assert CooldownThroughDeathPatch().verify(image) != []


def test_verify_rejects_the_wrong_keywords(image: bytearray) -> None:
    CooldownThroughDeathPatch("KeepCooldownWhenSlain", "CooldownRunsWhileSlain").apply(image)
    assert CooldownThroughDeathPatch().verify(image) != []


def test_detect_recovers_both_keywords(image: bytearray) -> None:
    """The default probe would only ever recognise the default names, and a `.sagepatch` generated
    from a binary somebody else built has to say what that binary actually parses."""
    CooldownThroughDeathPatch("KeepCooldownWhenSlain", "CooldownRunsWhileSlain").apply(image)
    found = CooldownThroughDeathPatch.detect(image)
    assert found is not None
    assert (found.persist_keyword, found.ticks_keyword) == (
        "KeepCooldownWhenSlain",
        "CooldownRunsWhileSlain",
    )


def test_detect_finds_nothing_in_a_clean_image(image: bytearray) -> None:
    assert CooldownThroughDeathPatch.detect(image) is None


@pytest.mark.parametrize("keywords", [(), ("Persist2", "Ticks2")])
def test_applying_twice_raises(image: bytearray, keywords: tuple[str, ...]) -> None:
    """The second run stops at its own section, under either set of names, rather than quietly
    installing a second copy of both fields.

    The section is checked before the anchors on purpose: applying rewrites bytes two anchors
    cover, so the anchor check would refuse a second run too - correctly, but describing it as the
    wrong build."""
    CooldownThroughDeathPatch().apply(image)
    with pytest.raises(ValueError, match="already applied"):
        CooldownThroughDeathPatch(*keywords).apply(image)


def test_another_patch_may_not_have_taken_the_padding(image: bytearray) -> None:
    """The refusal is about the two bytes, not about the keyword: a second field parsing into the
    same byte under a different name would appear to work and silently fight this one."""
    off = va_to_offset(image, SPECIAL_POWER_FIELD_TABLE)
    assert off is not None
    # a foreign row already parsing into +0x5A, where this patch wants to put its own
    index = [name for name, _ in STOCK_FIELDS].index("UnitCostDeathType")
    struct.pack_into("<I", image, off + index * FIELD_PARSE_STRIDE + 12, TEMPLATE_PERSIST)
    with pytest.raises(ValueError, match="already parsed"):
        CooldownThroughDeathPatch().apply(image)


def test_the_two_keywords_must_differ() -> None:
    """The reader takes the first row that matches, so a shared name would make the second field
    unreachable and its `Yes` silently ignored."""
    with pytest.raises(ValueError, match="two names"):
        CooldownThroughDeathPatch("Same", "Same")


@pytest.mark.parametrize("keyword", ["", "9Lives", "has space", "has-dash"])
def test_invalid_keywords_are_refused(keyword: str) -> None:
    with pytest.raises(ValueError, match="INI keyword"):
        CooldownThroughDeathPatch(keyword)


def test_apply_refuses_a_moved_anchor(image: bytearray) -> None:
    """The anchors are the reads the caves are built on and never rewrite. A build where one has
    moved would still take the patch and still verify, and then bank a cooldown off the wrong
    field - so the refusal has to happen at `apply`."""
    va = 0x00896F75  # the site that writes the ready frame and the duration
    off = va_to_offset(image, va)
    assert off is not None
    image[off] ^= 0xFF
    with pytest.raises(ValueError, match="not the build"):
        CooldownThroughDeathPatch().apply(image)


def test_apply_refuses_when_the_flavour_slot_moved(image: bytearray) -> None:
    """The flavour test is the only thing keeping this patch off a layout whose ready frame is
    somewhere else, so a vtable that no longer names `startPowerRecharge` is a refusal."""
    off = va_to_offset(image, 0x00C6502C)
    assert off is not None
    struct.pack_into("<I", image, off, 0x00991500)
    with pytest.raises(ValueError, match="not the build|flavour test"):
        CooldownThroughDeathPatch().apply(image)


def test_apply_refuses_a_table_whose_bools_moved(image: bytearray) -> None:
    """The padding is only free because of where the two `Bool`s and the `AsciiString` behind them
    sit. A table that puts `SharedSyncedTimer` elsewhere is a different layout."""
    off = va_to_offset(image, SPECIAL_POWER_FIELD_TABLE)
    assert off is not None
    index = [name for name, _ in STOCK_FIELDS].index("SharedSyncedTimer")
    struct.pack_into("<I", image, off + index * FIELD_PARSE_STRIDE + 12, 0x68)
    with pytest.raises(ValueError, match="SpecialPower.SharedSyncedTimer"):
        CooldownThroughDeathPatch().apply(image)


# --- the surface it declares --------------------------------------------------------------------


def test_ini_surface_names_both_fields() -> None:
    surface = CooldownThroughDeathPatch().ini_surface()
    assert [(f.block, f.name, f.type, f.default) for f in surface.fields] == [
        ("SpecialPower", DEFAULT_PERSIST_KEYWORD, "Bool", False),
        ("SpecialPower", DEFAULT_TICKS_KEYWORD, "Bool", False),
    ]


def test_ini_surface_follows_custom_keywords() -> None:
    """It describes *this instance*, so a `.sagepatch` written from a binary built with other
    names teaches the linter those names."""
    surface = CooldownThroughDeathPatch("A", "B").ini_surface()
    assert [f.name for f in surface.fields] == ["A", "B"]


def test_registered() -> None:
    assert PATCHES[CooldownThroughDeathPatch.name] is CooldownThroughDeathPatch
