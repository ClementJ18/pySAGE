"""Tests for `healing-received`, a `ModifierList` keyword that scales the healing a target takes.

Four things can go wrong here and none of them raises on its own.

The first is the **hook window**. Five bytes are replaced by a `call rel32`, and they are two
instructions - `fstp dword [ebp-4]` and `fldz`. A stub that dropped either would leave the caller
comparing a stale slot or with an x87 stack one deep, at a site that runs on every heal in the
game, so both are checked to survive the round trip in order.

The second is the **stack contract**. `getModifierMultiplier` is `__thiscall` with four arguments
and `ret 0x10`, so the stub has to push exactly four, keep its own scratch slot below them, and
leave `esp` where the `call rel32` left it. Off by one dword and the hook returns into the middle
of `attemptHealing`.

The third is **which object is asked**. The multiplier belongs to the *target*, which is `edi` at
the hook - not the source, and not the body sub-object in `esi`. Reading the wrong register would
silently make it a healer-side bonus, which is what `AUTO_HEAL` already is.

The fourth is the **shared name table**. `production-split` appends to it too, so the index the
stub pushes is not a constant: whichever patch is applied second appends after the first. Both
orders are applied and both patches asked to verify, because a stale index resolves to a name that
means something else entirely.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

pytest.importorskip("capstone", reason="the [patch] extra (capstone) is not installed")
from capstone import CS_ARCH_X86, CS_MODE_32, Cs  # noqa: E402 - after the importorskip guard

from sage_ini.engine import Engine  # noqa: E402
from sage_ini.model.enums import ModifierType  # noqa: E402
from sage_patch.patches.healing_received import (  # noqa: E402
    ANCHORS,
    DEFAULT_KEYWORD,
    GET_MODIFIER_MULTIPLIER,
    HOOK_STOCK_BYTES,
    HOOK_VA,
    SECTION_NAME,
    WORLDBUILDER_SECTION_NAME,
    HealingReceivedPatch,
    HealingReceivedWorldbuilderPatch,
    build_stub,
)
from sage_patch.patches.production_split import (  # noqa: E402
    NEW_TYPES,
    ProductionSplitPatch,
    ProductionSplitWorldbuilderPatch,
)
from sage_patch.patches.utils import modifier_types  # noqa: E402
from sage_patch.utils import find_section, va_to_offset  # noqa: E402

from .synthetic import (  # noqa: E402
    healing_received_image,
    modifier_type_image,
    modifier_type_worldbuilder_image,
)

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


@pytest.fixture
def image() -> bytearray:
    return healing_received_image()


def _patched(image: bytearray, keyword: str = DEFAULT_KEYWORD) -> bytearray:
    data = bytearray(image)
    HealingReceivedPatch(keyword=keyword).apply(data)
    return data


def _stub_va(data: bytes | bytearray) -> int:
    """Where the hook actually goes, read off the rewritten `call` rather than recomputed."""
    off = va_to_offset(data, HOOK_VA)
    assert off is not None
    assert data[off] == 0xE8, "the hook is not a call rel32"
    return HOOK_VA + 5 + struct.unpack_from("<i", data, off + 1)[0]


def _disassemble(data: bytes | bytearray, va: int, limit: int = 0x60) -> list:
    off = va_to_offset(data, va)
    assert off is not None
    out = []
    for insn in Cs(CS_ARCH_X86, CS_MODE_32).disasm(bytes(data[off : off + limit]), va):
        out.append(insn)
        if insn.mnemonic == "ret":
            break
    return out


def _text(code: list) -> list[str]:
    return [f"{i.mnemonic} {i.op_str}".strip() for i in code]


def test_the_hook_replaces_exactly_the_two_displaced_instructions(image: bytearray) -> None:
    """The window is `fstp dword [ebp-4]` then `fldz` - five bytes, which is what makes a
    `call rel32` fit without borrowing from either neighbour."""
    stock = Cs(CS_ARCH_X86, CS_MODE_32).disasm(HOOK_STOCK_BYTES, HOOK_VA)
    assert _text(list(stock)) == ["fstp dword ptr [ebp - 4]", "fldz"]
    assert len(HOOK_STOCK_BYTES) == 5


def test_the_hooked_site_holds_its_stock_bytes_before_the_patch(image: bytearray) -> None:
    off = va_to_offset(image, HOOK_VA)
    assert off is not None
    assert bytes(image[off : off + len(HOOK_STOCK_BYTES)]) == HOOK_STOCK_BYTES


def test_the_stub_re_emits_both_displaced_instructions_in_order(image: bytearray) -> None:
    """Whatever the stub does between them, the caller has to see the same two instructions in
    the same order: the amount stored, then a zero pushed for the compare below."""
    data = _patched(image)
    text = _text(_disassemble(data, _stub_va(data)))
    assert text[0] == "fstp dword ptr [ebp - 4]"
    assert text[-2] == "fldz"
    assert text[-1] == "ret"


def test_the_stub_asks_the_healed_object_not_the_healer(image: bytearray) -> None:
    """`edi` is the object being healed (`0x008C2FDD`, still live at `0x008C30C2`). Asking `esi`
    would ask the body sub-object, and asking anything reached through the `DamageInfo` would ask
    the source - which is what `AUTO_HEAL` already scales."""
    data = _patched(image)
    text = _text(_disassemble(data, _stub_va(data)))
    assert "mov ecx, edi" in text
    assert "mov ecx, esi" not in text


def test_the_stub_calls_the_multiplier_query_with_four_arguments(image: bytearray) -> None:
    """`getModifierMultiplier` is `ret 0x10`: four arguments, pushed right to left, with `this`
    in `ecx`. The scratch slot the out parameter points at is the stub's own, below them."""
    data = _patched(image)
    code = _disassemble(data, _stub_va(data))
    text = _text(code)

    assert "sub esp, 4" in text  # the out slot
    assert text.count("push 1") == 1  # flag
    assert text.count("push 0") == 1  # ctx
    assert "lea eax, [esp + 8]" in text  # &out, two pushes below it
    assert "push eax" in text
    assert any(t == f"call {hex(GET_MODIFIER_MULTIPLIER)}" for t in text)
    assert "add esp, 4" in text  # and the scratch slot released, nothing else


def test_the_stub_seeds_the_out_slot_to_one(image: bytearray) -> None:
    """`getModifierMultiplier` returns at its own holder guard without writing through `out` when
    the object has never been modified. A stub that trusted the callee to seed it would multiply
    the heal by whatever was on the stack."""
    data = _patched(image)
    text = _text(_disassemble(data, _stub_va(data)))
    assert f"mov dword ptr [esp], {hex(struct.unpack('<I', struct.pack('<f', 1.0))[0])}" in text


def test_the_stub_scales_the_amount_rather_than_replacing_it(image: bytearray) -> None:
    """The engine's own value has to survive: the product multiplies `[ebp-4]` and goes back to
    the same slot, which is the dword everything below the hook reads."""
    data = _patched(image)
    text = _text(_disassemble(data, _stub_va(data)))
    assert "movss xmm0, dword ptr [esp]" in text
    assert "mulss xmm0, dword ptr [ebp - 4]" in text
    assert "movss dword ptr [ebp - 4], xmm0" in text


def test_the_stub_pushes_the_index_the_table_gave_the_keyword(image: bytearray) -> None:
    """The immediate and the name table are the two halves of one fact. A stub pushing an index
    the table does not give this name would silently read some other modifier."""
    data = _patched(image)
    text = _text(_disassemble(data, _stub_va(data)))
    index = modifier_types.read(data).index_of(data, DEFAULT_KEYWORD)
    assert index == modifier_types.STOCK_TYPE_COUNT
    assert f"push {hex(index)}" in text


def test_the_rebuilt_table_keeps_every_stock_name_at_its_stock_index(image: bytearray) -> None:
    data = _patched(image)
    table = modifier_types.read(data)
    names = modifier_types.names(data, table)
    assert len(names) == modifier_types.STOCK_TYPE_COUNT + 1
    for index, name in modifier_types.TABLE_FINGERPRINT.items():
        assert names[index] == name
    assert names[-1] == DEFAULT_KEYWORD


def test_the_keyword_is_configurable(image: bytearray) -> None:
    data = _patched(image, keyword="HEAL_TAKEN")
    assert modifier_types.read(data).index_of(data, "HEAL_TAKEN") is not None
    patch = HealingReceivedPatch.detect(data)
    assert patch is not None
    assert patch.keyword == "HEAL_TAKEN"


def test_a_name_the_ini_parser_could_never_match_is_refused() -> None:
    with pytest.raises(ValueError, match="uppercase letters"):
        HealingReceivedPatch(keyword="Healing Received")


def test_applying_twice_is_refused(image: bytearray) -> None:
    """The second application would give the same name a second index, and the walk stops at the
    first match - so one of the two would be dead and which one is not obvious.

    The anchor check catches it first, because the hooked five bytes are a `call` by then; the
    name check behind it is what refuses a second *differently named* application on a binary
    someone else hooked."""
    data = _patched(image)
    with pytest.raises(ValueError, match="not the expected build"):
        HealingReceivedPatch().apply(data)

    table = modifier_types.read(data)
    with pytest.raises(ValueError, match="already modifier type"):
        modifier_types.check_free(table, data, [DEFAULT_KEYWORD])


def test_apply_verify_detect_round_trip(image: bytearray) -> None:
    data = _patched(image)
    patch = HealingReceivedPatch()
    assert patch.verify(data) == []
    found = HealingReceivedPatch.detect(data)
    assert found is not None and found.keyword == DEFAULT_KEYWORD
    assert HealingReceivedPatch.detect(image) is None


def test_verify_notices_a_hook_pointing_somewhere_else(image: bytearray) -> None:
    data = _patched(image)
    off = va_to_offset(data, HOOK_VA)
    assert off is not None
    struct.pack_into("<i", data, off + 1, 0x40)  # a call to nowhere in particular
    assert HealingReceivedPatch().verify(data)


def test_verify_notices_a_stub_that_pushes_a_stale_index(image: bytearray) -> None:
    """The check that matters most: the cave's immediate and the live table have to agree, and
    they are two separate places in the file."""
    data = _patched(image)
    stub_off = va_to_offset(data, _stub_va(data))
    assert stub_off is not None
    push = bytes(data).index(b"\x6a" + bytes([modifier_types.STOCK_TYPE_COUNT]), stub_off)
    data[push + 1] = modifier_types.STOCK_TYPE_COUNT + 1
    assert HealingReceivedPatch().verify(data)


def test_the_anchors_are_what_the_image_holds(image: bytearray) -> None:
    """Every window the patch asserts and does not rewrite."""
    for va, expected in ANCHORS.items():
        off = va_to_offset(image, va)
        assert off is not None, f"0x{va:08x} is not mapped"
        assert bytes(image[off : off + len(expected)]) == expected, f"0x{va:08x}"


def test_a_moved_healing_path_stops_the_patch(image: bytearray) -> None:
    """The hook is five bytes inside a much larger window; the window is what says those five
    bytes are the ones after the armor call and before the `<= 0` test."""
    data = bytearray(image)
    off = va_to_offset(data, 0x008C3005)
    assert off is not None
    data[off + 0x20] ^= 0xFF
    with pytest.raises(ValueError, match="not the expected build"):
        HealingReceivedPatch().apply(data)


def test_the_stub_is_a_pure_function_of_its_address_and_index() -> None:
    """Two caves at different addresses differ only in the `call` displacement, which is what lets
    `verify` recompute the expected bytes from the section it finds."""
    a = build_stub(0x00E00000, 28)
    b = build_stub(0x00E00010, 28)
    assert len(a) == len(b)
    assert a != b
    assert build_stub(0x00E00000, 29) != a


def test_ini_surface_names_the_keyword_and_claims_no_index() -> None:
    """The name is this patch's to declare; the index is not, because `production-split` shifts it.
    `sagepatch` reads the index off the live table and fuses it with this provenance."""
    surface = HealingReceivedPatch().ini_surface()
    assert [(d.enum, d.name, d.value, d.patch) for d in surface.enum_members] == [
        ("ModifierType", DEFAULT_KEYWORD, None, HealingReceivedPatch.name)
    ]


def test_the_ini_surface_actually_applies_to_the_model() -> None:
    """A surface the model rejects is a `.sagepatch` that lies, so it is applied rather than only
    inspected: `sage_ini` has to end up able to name the new type."""
    surface: Engine = HealingReceivedPatch().ini_surface()
    with surface.activate() as problems:
        assert problems == []
        assert DEFAULT_KEYWORD in ModifierType.__members__
    assert DEFAULT_KEYWORD not in ModifierType.__members__  # and it is scoped


class TestSharingTheNameTable:
    """`production-split` appends to the same table, so the pair has to compose in either order."""

    @pytest.fixture
    def image(self) -> bytearray:
        return modifier_type_image()

    @pytest.mark.parametrize("healing_first", [True, False], ids=["healing-first", "split-first"])
    def test_both_patches_verify_in_either_order(
        self, image: bytearray, healing_first: bool
    ) -> None:
        healing, split = HealingReceivedPatch(), ProductionSplitPatch()
        order = (healing, split) if healing_first else (split, healing)
        for patch in order:
            patch.apply(image)

        assert healing.verify(image) == []
        assert split.verify(image) == []
        assert HealingReceivedPatch.detect(image) is not None
        assert ProductionSplitPatch.detect(image) is not None

    @pytest.mark.parametrize("healing_first", [True, False], ids=["healing-first", "split-first"])
    def test_the_second_patch_appends_rather_than_renumbering(
        self, image: bytearray, healing_first: bool
    ) -> None:
        """Whoever runs second copies the live table through by pointer, so the first patch's
        names keep the indices its code was built to push."""
        healing, split = HealingReceivedPatch(), ProductionSplitPatch()
        order = (healing, split) if healing_first else (split, healing)
        for patch in order:
            patch.apply(image)

        names = modifier_types.names(image, modifier_types.read(image))
        stock = modifier_types.STOCK_TYPE_COUNT
        expected = [DEFAULT_KEYWORD, *NEW_TYPES] if healing_first else [*NEW_TYPES, DEFAULT_KEYWORD]
        assert names[stock:] == expected
        for index, name in modifier_types.TABLE_FINGERPRINT.items():
            assert names[index] == name

    def test_the_stub_pushes_the_index_it_ended_up_with(self, image: bytearray) -> None:
        """Applied second, the keyword lands four slots higher - and the stub has to say so."""
        ProductionSplitPatch().apply(image)
        HealingReceivedPatch().apply(image)

        index = modifier_types.read(image).index_of(image, DEFAULT_KEYWORD)
        assert index == modifier_types.STOCK_TYPE_COUNT + len(NEW_TYPES)
        text = _text(_disassemble(image, _stub_va(image)))
        assert f"push {hex(index)}" in text


class TestWorldbuilder:
    """The authoring half: the editor throws on a token its own table does not hold."""

    @pytest.fixture
    def image(self) -> bytearray:
        return modifier_type_worldbuilder_image()

    def test_apply_verify_detect_round_trip(self, image: bytearray) -> None:
        patch = HealingReceivedWorldbuilderPatch()
        patch.apply(image)
        assert patch.verify(image) == []
        found = HealingReceivedWorldbuilderPatch.detect(image)
        assert found is not None and found.keyword == DEFAULT_KEYWORD

    def test_the_editor_lookup_finds_the_new_name(self, image: bytearray) -> None:
        HealingReceivedWorldbuilderPatch().apply(image)
        table = modifier_types.read_worldbuilder(image)
        names = modifier_types.names(image, table)
        assert names[-1] == DEFAULT_KEYWORD
        for index, name in modifier_types.WORLDBUILDER_TABLE_FINGERPRINT.items():
            assert names[index] == name

    def test_it_targets_its_own_section(self, image: bytearray) -> None:
        """A separate cave from `production-split-wb`'s, so both twins can be applied."""
        HealingReceivedWorldbuilderPatch().apply(image)
        assert find_section(image, WORLDBUILDER_SECTION_NAME) is not None
        assert find_section(image, SECTION_NAME) is None

    @pytest.mark.parametrize("healing_first", [True, False], ids=["healing-first", "split-first"])
    def test_both_twins_compose_in_either_order(
        self, image: bytearray, healing_first: bool
    ) -> None:
        """The editor's table is shared exactly like the engine's, and neither twin may claim the
        two references it repointed once the other has run."""
        healing = HealingReceivedWorldbuilderPatch()
        split = ProductionSplitWorldbuilderPatch()
        for patch in (healing, split) if healing_first else (split, healing):
            patch.apply(image)

        assert healing.verify(image) == []
        assert split.verify(image) == []
        names = modifier_types.names(image, modifier_types.read_worldbuilder(image))
        stock = modifier_types.STOCK_TYPE_COUNT
        assert sorted(names[stock:]) == sorted([DEFAULT_KEYWORD, *NEW_TYPES])


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
class TestInstalledBinary:
    """Against the real binary, which is the only thing that can say the addresses are right."""

    @pytest.fixture(scope="class")
    def stock(self) -> bytes:
        return _GAME_DAT.read_bytes()

    def test_every_anchor_holds_its_stock_bytes(self, stock: bytes) -> None:
        for va, expected in ANCHORS.items():
            off = va_to_offset(stock, va)
            assert off is not None, f"0x{va:08x} is not mapped"
            assert bytes(stock[off : off + len(expected)]) == expected, f"0x{va:08x}"

    def test_the_hook_site_holds_its_stock_bytes(self, stock: bytes) -> None:
        off = va_to_offset(stock, HOOK_VA)
        assert off is not None
        assert bytes(stock[off : off + len(HOOK_STOCK_BYTES)]) == HOOK_STOCK_BYTES

    def test_apply_verify_detect_round_trip(self, stock: bytes) -> None:
        data = bytearray(stock)
        patch = HealingReceivedPatch()
        patch.apply(data)
        assert patch.verify(data) == []
        assert HealingReceivedPatch.detect(data) is not None

    @pytest.mark.parametrize("healing_first", [True, False], ids=["healing-first", "split-first"])
    def test_it_composes_with_production_split(self, stock: bytes, healing_first: bool) -> None:
        data = bytearray(stock)
        healing, split = HealingReceivedPatch(), ProductionSplitPatch()
        for patch in (healing, split) if healing_first else (split, healing):
            patch.apply(data)
        assert healing.verify(data) == []
        assert split.verify(data) == []
