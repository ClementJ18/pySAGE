"""Tests for `production-split`, which gives each of `PRODUCTION`'s meanings its own keyword.

Four things can go wrong here and none of them raises on its own, so all four are checked
statically.

The first is the **stack contract**. Each thunk is entered by a `call` that was aimed at an engine
function with a fixed argument count, and leaves through its own `ret imm`. A thunk that cleans
the wrong number of bytes corrupts the caller's frame at a site that runs every frame, so every
thunk is disassembled back and its `ret` compared against the callee it stands in for.

The second is the **double-query arithmetic**. `getModifierMultiplier` re-seeds its out parameter
to 1.0 on entry, so a thunk that called it twice and read the result once would silently drop the
stock `PRODUCTION` factor. The emitted code is checked to save the first product before the second
call and multiply them afterwards.

The third is the **queue dispatch**: two keywords come out of one hook, chosen by a dword in the
production entry, and picking the wrong one is invisible - an upgrade would simply answer to the
unit keyword. The kind constants and the type each maps to are asserted against the engine's own
dispatch, which the patch carries as a fingerprint window. The same dword decides the hero exit,
which has to leave before the thunk touches the frame or `ecx`, so that is checked too.

The fourth is the **rebuilt name table**. It is the one structure the patch replaces rather than
repoints, and a table that lost an entry, kept the stock terminator or spelled a name wrongly would
either shift every existing modifier's meaning or fail INI parsing on names that used to work.
"""

from __future__ import annotations

import struct

import pytest

from sage_ini.engine import Engine
from sage_ini.model.enums import ModifierType
from sage_patch import ProductionSplitPatch, apply_patches
from sage_patch.patches.production_split import (
    AI_HOOKS,
    ANCHORS,
    CALC_TIME_TO_BUILD,
    GET_MODIFIER_MULTIPLIER,
    HOOKS,
    NEW_TYPES,
    PRODUCTION_TYPE,
    QUEUE_KIND_HERO,
    QUEUE_KIND_OFFSET,
    QUEUE_KIND_UNIT,
    QUEUE_KIND_UPGRADE,
    SECTION_NAME,
    STOCK_TYPE_COUNT,
    TABLE_FINGERPRINT,
    TABLE_REF_CMP_VA,
    TABLE_REF_MOV_VA,
    TYPE_CONSTRUCTION,
    TYPE_MONEY,
    TYPE_TABLE_VA,
    TYPE_UNIT,
    TYPE_UPGRADE,
    build_section,
    read_stock_table,
)
from sage_patch.utils import find_section, va_to_offset

from .synthetic import production_split_image, stock_modifier_name


@pytest.fixture
def image() -> bytearray:
    return production_split_image()


def _patched(image: bytearray, ai_sites: bool = False) -> bytearray:
    data = bytearray(image)
    ProductionSplitPatch(ai_sites=ai_sites).apply(data)
    return data


def _cave(data: bytes | bytearray) -> tuple[int, int, int]:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    return located


def _layout(data: bytes | bytearray) -> tuple[dict[str, int], int]:
    """The thunk addresses and rebuilt-table VA the cave on disk actually carries."""
    section_va, _off, _vsize = _cave(data)
    stock = ProductionSplitPatch()._stock_pointers_from_cave(data, section_va)
    _content, thunks, table_va = build_section(section_va, stock)
    return thunks, table_va


def _hook_target(data: bytes | bytearray, call_va: int) -> int:
    off = va_to_offset(data, call_va)
    assert off is not None
    return call_va + 5 + struct.unpack_from("<i", data, off + 1)[0]


def _read_u32(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    assert off is not None
    return struct.unpack_from("<I", data, off)[0]


def _read_name(data: bytes | bytearray, va: int) -> str:
    off = va_to_offset(data, va)
    assert off is not None
    return bytes(data[off : data.index(0, off, off + 64)]).decode("ascii")


def _disassemble(data: bytes | bytearray, va: int, limit: int = 0x90) -> list:
    """One thunk, decoded up to and including its `ret`."""
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    off = va_to_offset(data, va)
    assert off is not None
    out = []
    for ins in md.disasm(bytes(data[off : off + limit]), va):
        out.append(ins)
        if ins.mnemonic.startswith("ret"):
            break
    assert out and out[-1].mnemonic.startswith("ret"), "the thunk does not end in a ret"
    return out


def test_apply_then_verify(image: bytearray) -> None:
    assert ProductionSplitPatch().verify(_patched(image)) == []


def test_apply_then_verify_with_the_ai_sites(image: bytearray) -> None:
    data = _patched(image, ai_sites=True)
    assert ProductionSplitPatch(ai_sites=True).verify(data) == []


def test_verify_rejects_an_unpatched_image(image: bytearray) -> None:
    problems = ProductionSplitPatch().verify(image)
    assert problems and SECTION_NAME in problems[0]


def test_verify_is_parameter_aware(image: bytearray) -> None:
    """The AI sites are opt-in, so the two configurations must not verify each other: an image
    built without them is not an image built with them, and saying otherwise would let `detect`
    report the wrong `.sagepatch`."""
    assert ProductionSplitPatch(ai_sites=True).verify(_patched(image)) != []
    assert ProductionSplitPatch().verify(_patched(image, ai_sites=True)) != []


def test_detect_recovers_the_patch_and_its_parameter(image: bytearray) -> None:
    plain = ProductionSplitPatch.detect(_patched(image))
    withai = ProductionSplitPatch.detect(_patched(image, ai_sites=True))
    assert plain is not None and plain.ai_sites is False
    assert withai is not None and withai.ai_sites is True
    assert ProductionSplitPatch.detect(image) is None


def test_apply_is_idempotent_only_once(image: bytearray) -> None:
    """A second application must fail rather than double-patch: the hooked calls no longer hold
    their original displacements and `apply_byte_patch` asserts them."""
    data = _patched(image)
    with pytest.raises(ValueError):
        ProductionSplitPatch().apply(data)


def test_apply_patches_writes_a_file(image: bytearray, tmp_path) -> None:
    src, out = tmp_path / "game.dat.backup", tmp_path / "game.dat"
    src.write_bytes(bytes(image))
    apply_patches(src, [ProductionSplitPatch()], output=out)
    assert ProductionSplitPatch().verify(out.read_bytes()) == []
    assert src.read_bytes() == bytes(image)  # the input is never modified


def test_apply_refuses_another_build(image: bytearray) -> None:
    data = bytearray(image)
    off = va_to_offset(data, next(iter(ANCHORS)))
    assert off is not None
    data[off] ^= 0xFF
    with pytest.raises(ValueError, match="not the expected build"):
        ProductionSplitPatch().apply(data)


@pytest.mark.parametrize(("call_va", "stock_va", "thunk", "note"), HOOKS)
def test_every_hook_retargets_its_stock_call_into_the_cave(
    image: bytearray, call_va: int, stock_va: int, thunk: str, note: str
) -> None:
    data = _patched(image)
    assert _hook_target(image, call_va) == stock_va  # the stand-in starts stock
    thunks, _table = _layout(data)
    assert _hook_target(data, call_va) == thunks[thunk], note


@pytest.mark.parametrize(("call_va", "stock_va", "thunk", "note"), AI_HOOKS)
def test_the_ai_hooks_move_only_when_asked(
    image: bytearray, call_va: int, stock_va: int, thunk: str, note: str
) -> None:
    assert _hook_target(_patched(image), call_va) == stock_va
    assert _hook_target(_patched(image, ai_sites=True), call_va) != stock_va


def test_the_three_thunks_are_distinct(image: bytearray) -> None:
    """One cave, three entry points. Two of them stand in for a function with four arguments and
    the third for one with three, so a shared thunk would clean the wrong frame."""
    thunks, _table = _layout(_patched(image))
    assert len(set(thunks.values())) == 3


def test_nothing_outside_the_hooks_and_the_table_refs_is_rewritten(image: bytearray) -> None:
    """The patch's whole footprint in existing code is six `call` displacements and the two
    operands naming the name table. Everything else it changes is the PE header block and the
    bytes it appends."""
    data = _patched(image)
    headers = 0x400  # SizeOfHeaders in the stand-in; the section table lives inside it
    changed = {i for i in range(headers, len(image)) if data[i] != image[i]}

    allowed: set[int] = set()
    for call_va, _stock, _thunk, _note in HOOKS:
        off = va_to_offset(data, call_va)
        assert off is not None
        allowed |= set(range(off + 1, off + 5))  # the displacement; the 0xE8 stays put
    for ref_va in (TABLE_REF_CMP_VA, TABLE_REF_MOV_VA):
        off = va_to_offset(data, ref_va)
        assert off is not None
        allowed |= set(range(off, off + 4))
    assert changed <= allowed


def test_both_table_references_name_the_rebuilt_table(image: bytearray) -> None:
    """Two instructions name the table - the empty-table guard and the walk. Repointing one and
    not the other would scan the new table while testing the old one for emptiness."""
    data = _patched(image)
    _thunks, table_va = _layout(data)
    assert _read_u32(image, TABLE_REF_CMP_VA) == TYPE_TABLE_VA
    assert _read_u32(image, TABLE_REF_MOV_VA) == TYPE_TABLE_VA
    assert _read_u32(data, TABLE_REF_CMP_VA) == table_va
    assert _read_u32(data, TABLE_REF_MOV_VA) == table_va


def test_the_stock_table_is_left_in_place(image: bytearray) -> None:
    """The stock table is copied, not moved: nothing else in the image is known to reach it, but
    rewriting a table in `.data` that 134 other copies are indistinguishable from is a risk with
    no upside."""
    data = _patched(image)
    off = va_to_offset(data, TYPE_TABLE_VA)
    assert off is not None
    width = (STOCK_TYPE_COUNT + 1) * 4
    assert bytes(data[off : off + width]) == bytes(image[off : off + width])


def test_the_rebuilt_table_keeps_every_stock_name_at_its_stock_index(image: bytearray) -> None:
    data = _patched(image)
    _thunks, table_va = _layout(data)
    for index in range(STOCK_TYPE_COUNT):
        pointer = _read_u32(data, table_va + index * 4)
        assert _read_name(data, pointer) == stock_modifier_name(index), index


def test_the_rebuilt_table_appends_the_new_names_and_terminates(image: bytearray) -> None:
    data = _patched(image)
    _thunks, table_va = _layout(data)
    for offset, name in enumerate(NEW_TYPES):
        pointer = _read_u32(data, table_va + (STOCK_TYPE_COUNT + offset) * 4)
        assert _read_name(data, pointer) == name
    end = table_va + (STOCK_TYPE_COUNT + len(NEW_TYPES)) * 4
    assert _read_u32(data, end) == 0


def test_the_new_indices_follow_the_stock_ones(image: bytearray) -> None:
    """The index a name resolves to is its position in the table, so the five new types must be
    exactly the five past the stock count - anything else and the cave would push a type no name
    resolves to."""
    assert (TYPE_MONEY, TYPE_UNIT, TYPE_UPGRADE, TYPE_CONSTRUCTION) == tuple(
        range(STOCK_TYPE_COUNT, STOCK_TYPE_COUNT + len(NEW_TYPES))
    )


def test_read_stock_table_rejects_a_table_that_spells_something_else(image: bytearray) -> None:
    """The fingerprint is what stops the patch rebuilding some other name list that happens to
    live at this address in a build it was not written for."""
    data = bytearray(image)
    pointer = _read_u32(data, TYPE_TABLE_VA + 13 * 4)  # PRODUCTION
    off = va_to_offset(data, pointer)
    assert off is not None
    data[off] = ord("X")
    with pytest.raises(ValueError, match="expected 'PRODUCTION'"):
        read_stock_table(data)


def test_read_stock_table_rejects_a_table_of_another_length(image: bytearray) -> None:
    data = bytearray(image)
    off = va_to_offset(data, TYPE_TABLE_VA + STOCK_TYPE_COUNT * 4)
    assert off is not None
    struct.pack_into("<I", data, off, 0x00BD0000)  # a 29th entry where the terminator was
    with pytest.raises(ValueError, match="NULL terminator"):
        read_stock_table(data)


@pytest.mark.parametrize(
    ("thunk", "stock_callee", "cleanup"),
    [("money", GET_MODIFIER_MULTIPLIER, 0x10), ("queue", GET_MODIFIER_MULTIPLIER, 0x10)],
)
def test_a_widening_thunk_cleans_the_frame_its_callee_would_have(
    image: bytearray, thunk: str, stock_callee: int, cleanup: int
) -> None:
    data = _patched(image)
    thunks, _table = _layout(data)
    code = _disassemble(data, thunks[thunk])
    assert code[-1].mnemonic == "ret"
    assert int(code[-1].op_str, 16) == cleanup
    calls = [i for i in code if i.mnemonic == "call"]
    assert [int(i.op_str, 16) for i in calls] == [stock_callee, stock_callee]


def test_the_construction_thunk_cleans_the_frame_calc_time_to_build_would_have(
    image: bytearray,
) -> None:
    """Three arguments, not four: this thunk stands in for `calcTimeToBuild`, and the modifier
    query it makes on the side is its own business."""
    data = _patched(image)
    thunks, _table = _layout(data)
    code = _disassemble(data, thunks["construction"])
    assert int(code[-1].op_str, 16) == 0x0C
    assert [int(i.op_str, 16) for i in code if i.mnemonic == "call"] == [
        CALC_TIME_TO_BUILD,
        GET_MODIFIER_MULTIPLIER,
    ]


@pytest.mark.parametrize("thunk", ["money", "queue"])
def test_a_widening_thunk_keeps_the_first_product_before_asking_again(
    image: bytearray, thunk: str
) -> None:
    """`getModifierMultiplier` writes 1.0 into the out parameter on entry, so the stock factor has
    to be copied out between the two calls and multiplied back in after the second. Without the
    save this thunk would silently return the new keyword alone."""
    data = _patched(image)
    thunks, _table = _layout(data)
    code = _disassemble(data, thunks[thunk])
    text = [f"{i.mnemonic} {i.op_str}" for i in code]
    first_call = next(n for n, i in enumerate(code) if i.mnemonic == "call")
    last_call = max(n for n, i in enumerate(code) if i.mnemonic == "call")
    # between the calls: read the out slot, park it in a local
    assert "mov eax, dword ptr [edi]" in text[first_call:last_call]
    assert any(t.startswith("mov dword ptr [ebp - 0x10], eax") for t in text[first_call:last_call])
    # after the second: multiply the two products back together into the out slot
    assert "mulss xmm0, dword ptr [ebp - 0x10]" in text[last_call:]
    assert "movss dword ptr [edi], xmm0" in text[last_call:]


def test_a_widening_thunk_passes_the_stock_type_through_unchanged(image: bytearray) -> None:
    """`PRODUCTION` keeps every meaning it has: the first query forwards the caller's own type
    argument rather than an immediate, so a site asking for something else would still get it."""
    data = _patched(image)
    thunks, _table = _layout(data)
    code = _disassemble(data, thunks["money"])
    text = [f"{i.mnemonic} {i.op_str}" for i in code]
    assert "push dword ptr [ebp + 8]" in text  # the stock argument, forwarded
    assert f"push {hex(TYPE_MONEY)}" in text  # and the new type, beside it
    assert f"push {hex(PRODUCTION_TYPE)}" not in text  # never hardcoded


def test_the_queue_thunk_maps_each_entry_kind_to_its_own_keyword(image: bytearray) -> None:
    """One hook, two keywords. The kind is a dword at `entry+4` and the mapping has to match the
    engine's own dispatch: 2 is an upgrade, everything else that reaches the widening is a unit."""
    data = _patched(image)
    thunks, _table = _layout(data)
    code = _disassemble(data, thunks["queue"])
    text = [f"{i.mnemonic} {i.op_str}" for i in code]

    assert f"mov eax, dword ptr [ebx + {QUEUE_KIND_OFFSET}]" in text
    assert f"cmp eax, {QUEUE_KIND_UPGRADE}" in text
    assert f"cmp eax, {QUEUE_KIND_UNIT}" not in text  # the fall-through, not a test
    for type_index in (TYPE_UNIT, TYPE_UPGRADE):
        assert f"mov eax, {hex(type_index)}" in text
    assert "push dword ptr [ebp - 0x14]" in text  # the chosen type, not an immediate
    # no keyword is invented for a hero, so no third index is ever pushed
    assert f"mov eax, {hex(TYPE_CONSTRUCTION)}" not in text


def test_the_queue_thunk_hands_a_hero_entry_straight_to_the_stock_callee(
    image: bytearray,
) -> None:
    """A hero completes off the player's ledger, not off this accrual (`0x008A1F21` skips the
    percentage test for kind 3), so there is no honest keyword to apply and the thunk declines to
    invent one.

    The exit has to be the *first* thing the thunk does and it has to be a `jmp`: the arguments and
    `ecx` are still the site's own at that point, so tail-calling leaves the site behaving exactly
    as if it had never been hooked. A `call` here would leave the stock callee returning into the
    thunk with a frame it never built."""
    data = _patched(image)
    thunks, _table = _layout(data)
    code = _disassemble(data, thunks["queue"])

    assert f"{code[0].mnemonic} {code[0].op_str}" == (
        f"cmp dword ptr [ebx + {QUEUE_KIND_OFFSET}], {QUEUE_KIND_HERO}"
    )
    assert code[1].mnemonic == "jne"  # everything else falls into the widening
    assert code[2].mnemonic == "jmp"
    assert int(code[2].op_str, 16) == GET_MODIFIER_MULTIPLIER
    # nothing has been pushed, so the stock callee's own `ret 0x10` balances the site
    assert not any(i.mnemonic in ("push", "sub") for i in code[:3])


def test_the_queue_thunk_reads_the_kind_before_it_clobbers_anything(image: bytearray) -> None:
    """`ebx` is the caller's queue entry. It is callee-saved, so it survives into the thunk - but
    only until the thunk starts using it as a scratch register for the found flag."""
    data = _patched(image)
    thunks, _table = _layout(data)
    code = _disassemble(data, thunks["queue"])
    reads_kind = next(n for n, i in enumerate(code) if i.op_str.startswith("eax, dword ptr [ebx"))
    writes_bl = next(n for n, i in enumerate(code) if i.op_str.startswith("bl,"))
    assert reads_kind < writes_bl


def test_the_construction_thunk_divides_and_clamps(image: bytearray) -> None:
    """The caller divides both `100` and `maxHealth` by this thunk's return value, so a zero or
    negative multiplier must be ignored and the result must never fall below one frame."""
    data = _patched(image)
    thunks, _table = _layout(data)
    section_va, _off, _vsize = _cave(data)
    code = _disassemble(data, thunks["construction"])
    text = [f"{i.mnemonic} {i.op_str}" for i in code]

    assert f"push {hex(TYPE_CONSTRUCTION)}" in text
    assert "mov ecx, edi" in text  # the structure being built, not the builder
    assert f"comiss xmm0, dword ptr [{hex(section_va)}]" in text  # against the cave's own 0.0
    assert any(t.startswith("jbe") for t in text)  # unordered included: NaN is not a multiplier
    assert "divss xmm1, xmm0" in text
    assert "cmp eax, 1" in text and "mov eax, 1" in text


def test_the_cave_carries_its_own_constants(image: bytearray) -> None:
    """The float the clamp compares against lives in the cave, not at one of the engine's own
    constant addresses - one less thing to be wrong about in a build this was not derived from."""
    data = _patched(image)
    _va, off, _vsize = _cave(data)
    assert bytes(data[off : off + 8]) == struct.pack("<ff", 0.0, 1.0)


def test_ini_surface_names_the_five_keywords_at_their_table_indices() -> None:
    surface = ProductionSplitPatch().ini_surface()
    assert [(d.enum, d.name, d.value) for d in surface.enum_members] == [
        ("ModifierType", name, STOCK_TYPE_COUNT + index) for index, name in enumerate(NEW_TYPES)
    ]


def test_the_ini_surface_actually_applies_to_the_model() -> None:
    """A surface the model rejects is a `.sagepatch` that lies, so it is applied rather than only
    inspected: `sage_ini` has to end up able to name the new types."""
    surface: Engine = ProductionSplitPatch().ini_surface()
    with surface.activate() as problems:
        assert problems == []
        for name in NEW_TYPES:
            assert name in ModifierType.__members__
            member = ModifierType[name]
            assert member.is_mult(), f"{name} must multiply, like the PRODUCTION it splits"
    assert "PRODUCTION_MONEY" not in ModifierType.__members__  # and it is scoped


def test_the_fingerprint_covers_the_type_this_patch_splits() -> None:
    """`PRODUCTION` is the whole reason the table is being rebuilt; a fingerprint that did not
    pin its index could rebuild a table in which the cave's own pushes mean something else."""
    assert TABLE_FINGERPRINT[PRODUCTION_TYPE] == "PRODUCTION"
