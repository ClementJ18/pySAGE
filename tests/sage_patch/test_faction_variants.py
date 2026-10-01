"""Tests for faction variants: where the cave is wired into the engine.

`test_faction_variants_emulated.py` runs the cave. These check the claims about the *engine* the
cave rests on, which the emulator takes on trust: that each hook site holds what the patch says it
displaces, that the wrapped calls are every call of the routine they wrap, and that the patch
composes with the other two that edit the same screen and the same field table.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    COMBO_BOX_OPEN_GATE,
    COMBO_BOX_OPEN_GATE_BYTES,
    COMBO_BOX_OPEN_GO,
    COMBO_BOX_OPEN_SKIP,
    GAME_START_RANDOM_DRAW,
    GAME_START_RANDOM_DRAW_BYTES,
    MP_SETUP_FACTION_COMBO,
    MP_SETUP_FACTION_COMBO_CALLS,
    MP_SETUP_SYNC_FACTION,
    MP_SETUP_SYNC_FACTION_CALLS,
)
from sage_patch.patches.command_point_upkeep import CommandPointUpkeepPatch
from sage_patch.patches.faction_variants import (
    FIELD_NAME,
    SECTION_NAME,
    FactionVariantsPatch,
    build_section,
    layout,
)
from sage_patch.patches.scenario_player_factions import ScenarioPlayerFactionsPatch
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


def test_registered():
    assert PATCHES["faction-variants"] is FactionVariantsPatch


def test_section_name_fits_the_pe_field():
    assert len(SECTION_NAME) <= 8


def test_the_ini_surface_is_one_reference_field():
    (delta,) = FactionVariantsPatch().ini_surface().fields
    assert (delta.block, delta.name, delta.type, delta.default) == (
        "PlayerTemplate",
        FIELD_NAME,
        "Ref:factions",
        None,
    )


def test_the_layout_names_what_the_hooks_jump_to():
    at = layout(0x00F00000)
    for label in (
        "parse",
        "new_key",
        "join",
        "faction_list",
        "random_pool",
        "sync_template",
        "fill",
        "sync",
        "selection",
        "gadget",
        "ctor_clear",
        "enable",
        "random_side",
    ):
        assert at[label] > 0x00F00000


def test_the_cave_decodes_end_to_end():
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    base = 0x00F00000
    section = build_section(base)
    code_va = layout(base)["parse"]
    code = section[code_va - base :]
    decoded = sum(ins.size for ins in md.disasm(code, code_va))
    assert decoded == len(code), "a byte the disassembler cannot read is a byte the CPU misreads"


@pytest.fixture(scope="module")
def stock() -> bytes:
    if not _GAME_DAT.exists():
        pytest.skip("no game.dat at the repository root")
    return _GAME_DAT.read_bytes()


class TestInstalledBinary:
    def test_applies_and_verifies(self, stock: bytes):
        data = bytearray(stock)
        patch = FactionVariantsPatch()
        patch.apply(data)
        assert patch.verify(data) == []

    def test_an_unpatched_binary_does_not_verify(self, stock: bytes):
        assert FactionVariantsPatch().verify(stock) != []

    def test_applying_twice_is_refused(self, stock: bytes):
        data = bytearray(stock)
        FactionVariantsPatch().apply(data)
        with pytest.raises(ValueError, match="already"):
            FactionVariantsPatch().apply(data)

    @pytest.mark.parametrize("first_is_ours", [True, False])
    def test_composes_with_the_other_patches_on_the_same_code(self, stock, first_is_ours):
        # `scenario-player-factions` hooks the same faction fill and asserts its entry;
        # `command-point-upkeep` extends the same field table.
        ours = FactionVariantsPatch()
        others = [ScenarioPlayerFactionsPatch(), CommandPointUpkeepPatch()]
        order = [ours, *others] if first_is_ours else [*others, ours]
        data = bytearray(stock)
        for patch in order:
            patch.apply(data)
        for patch in order:
            assert patch.verify(data) == [], patch.name

    @pytest.mark.parametrize(
        ("target", "sites"),
        [
            (MP_SETUP_FACTION_COMBO, MP_SETUP_FACTION_COMBO_CALLS),
            (MP_SETUP_SYNC_FACTION, MP_SETUP_SYNC_FACTION_CALLS),
        ],
    )
    def test_the_wrapped_calls_are_every_call(self, stock: bytes, target: int, sites):
        # A caller left unwrapped would redraw its faction box and leave the Variant box stale.
        located = find_section(stock, ".text")
        assert located is not None
        text_va, text_off, size = located
        found = []
        for off in range(text_off, text_off + size - 5):
            if stock[off] == 0xE8:
                va = text_va + off - text_off
                if va + 5 + struct.unpack_from("<i", stock, off + 1)[0] == target:
                    found.append(va)
        assert sorted(found) == sorted(sites)
        for site in sites:
            off = va_to_offset(stock, site)
            assert off is not None
            # each is `push <slot>` / `mov ecx, esi` / `call`, which is what the wrapper assumes
            assert stock[off - 2 : off] == b"\x8b\xce", f"0x{site:08x}"


class TestRandomDrawSite:
    """The Good/Evil hook replaces the draw's two loads, `mov esi, [ebp-0x24]` (the candidates'
    end) and `mov edi, [ebp-0x28]` (their begin), at the point both start-position filters'
    skips land on - so it sees the final candidates, and no branch lands inside it."""

    def test_the_displaced_bytes_are_the_two_loads(self):
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        listing = [
            (i.mnemonic, i.op_str)
            for i in md.disasm(GAME_START_RANDOM_DRAW_BYTES, GAME_START_RANDOM_DRAW)
        ]
        assert listing == [
            ("mov", "esi, dword ptr [ebp - 0x24]"),
            ("mov", "edi, dword ptr [ebp - 0x28]"),
        ]

    def test_the_real_binary_carries_them_and_the_branches_land_on_the_first(self, stock: bytes):
        off = va_to_offset(stock, GAME_START_RANDOM_DRAW)
        assert off is not None
        assert stock[off : off + len(GAME_START_RANDOM_DRAW_BYTES)] == GAME_START_RANDOM_DRAW_BYTES
        located = find_section(stock, ".text")
        assert located is not None
        text_va, text_off, size = located
        into: dict[int, list[int]] = {}
        window = range(
            GAME_START_RANDOM_DRAW, GAME_START_RANDOM_DRAW + len(GAME_START_RANDOM_DRAW_BYTES)
        )
        for o in range(text_off, text_off + size - 6):
            va = text_va + o - text_off
            if stock[o] in (0xE8, 0xE9):
                target = va + 5 + struct.unpack_from("<i", stock, o + 1)[0]
            elif stock[o] == 0x0F and 0x80 <= stock[o + 1] <= 0x8F:
                target = va + 6 + struct.unpack_from("<i", stock, o + 2)[0]
            elif 0x70 <= stock[o] <= 0x7F or stock[o] == 0xEB:
                target = va + 2 + struct.unpack_from("<b", stock, o + 1)[0]
            else:
                continue
            if target in window:
                into.setdefault(target, []).append(va)
        # both filters' "nothing to filter" skips, and nothing into the second load
        assert set(into) == {GAME_START_RANDOM_DRAW}
        assert {0x0062D65D, 0x0062D6CD} <= set(into[GAME_START_RANDOM_DRAW])


class TestOpenGateSite:
    """The hook replaces the toggle's two-entry test, whose `jle` is the skip the cave reuses."""

    def test_the_displaced_bytes_are_the_count_test(self):
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        listing = [
            (i.mnemonic, i.op_str)
            for i in md.disasm(COMBO_BOX_OPEN_GATE_BYTES, COMBO_BOX_OPEN_GATE)
        ]
        assert listing == [
            ("cmp", "dword ptr [edi + 0x20], 1"),
            ("jle", f"{COMBO_BOX_OPEN_SKIP:#x}"),
        ]
        assert COMBO_BOX_OPEN_GATE + len(COMBO_BOX_OPEN_GATE_BYTES) == COMBO_BOX_OPEN_GO

    def test_the_real_binary_carries_them(self, stock: bytes):
        off = va_to_offset(stock, COMBO_BOX_OPEN_GATE)
        assert off is not None
        assert stock[off : off + len(COMBO_BOX_OPEN_GATE_BYTES)] == COMBO_BOX_OPEN_GATE_BYTES
