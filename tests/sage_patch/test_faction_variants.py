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
    GAME_INFO_PARSE,
    GAME_INFO_PARSE_TEMPLATE_CHECKS,
    GAME_INFO_RULE_CLAN_GAME,
    GAME_INFO_RULES,
    GAME_RULES_CLAN_GAME_HIDE,
    GAME_RULES_CLAN_GAME_LABEL,
    GAME_RULES_NAMES,
    GAME_SLOT_REQUEST_TEMPLATE_CHECK,
    GAME_SLOT_SET_TEMPLATE_OBSERVER_JG,
    GAME_START_RANDOM_DRAW,
    GAME_START_RANDOM_DRAW_BYTES,
    MP_SETUP_COMMAND_BLOCK,
    MP_SETUP_COMMAND_BLOCK_BYTES,
    MP_SETUP_COMMAND_BLOCK_RESUME,
    MP_SETUP_FACTION_COMBO,
    MP_SETUP_FACTION_COMBO_CALLS,
    MP_SETUP_SYNC_FACTION,
    MP_SETUP_SYNC_FACTION_CALLS,
)
from sage_patch.asm import Asm
from sage_patch.patches.campaign.scenario_player_factions import ScenarioPlayerFactionsPatch
from sage_patch.patches.economy.command_point_upkeep import CommandPointUpkeepPatch
from sage_patch.patches.multiplayer.faction_variants import (
    ALL_VARIANTS_LABEL,
    ALL_VARIANTS_RULE,
    FIELD_NAME,
    PVP_FIELD_NAME,
    RANDOM_POOL,
    RANDOM_POOL_BITS,
    SECTION_NAME,
    FactionVariantsPatch,
    build_section,
    emit_command_block,
    layout,
    pool_indices,
    random_pool,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"
#: Just past `ParseAsciiStringToGameInfo`'s `ret`.
_GAME_INFO_PARSE_END = 0x00803BC5


def test_registered():
    assert PATCHES["faction-variants"] is FactionVariantsPatch


def test_section_name_fits_the_pe_field():
    assert len(SECTION_NAME) <= 8


def test_the_ini_surface_is_a_reference_and_a_bool():
    variant_of, pvp = FactionVariantsPatch().ini_surface().fields
    assert (variant_of.block, variant_of.name, variant_of.type, variant_of.default) == (
        "PlayerTemplate",
        FIELD_NAME,
        "Ref:factions",
        None,
    )
    assert (pvp.block, pvp.name, pvp.type, pvp.default) == (
        "PlayerTemplate",
        PVP_FIELD_NAME,
        "Bool",
        True,
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


def _branches_into(stock: bytes, window: range) -> dict[int, list[int]]:
    """Every direct `call`/`jmp`/`jcc` in `.text` that lands in `window`, by where it lands. A byte
    scan, not a disassembly: it over-reports, which only makes an empty answer stronger."""
    located = find_section(stock, ".text")
    assert located is not None
    text_va, text_off, size = located
    into: dict[int, list[int]] = {}
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
    return into


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
        into = _branches_into(
            stock,
            range(
                GAME_START_RANDOM_DRAW, GAME_START_RANDOM_DRAW + len(GAME_START_RANDOM_DRAW_BYTES)
            ),
        )
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


class TestRandomPoolEncoding:
    def test_it_round_trips(self):
        assert pool_indices(random_pool([0, 5, RANDOM_POOL_BITS - 1])) == {0, 5, 23}

    def test_it_is_below_every_other_sentinel(self):
        assert random_pool(range(RANDOM_POOL_BITS)) < -128

    @pytest.mark.parametrize("indices", [[], [-1], [RANDOM_POOL_BITS]])
    def test_what_it_cannot_say_is_refused(self, indices: list[int]):
        with pytest.raises(ValueError):
            random_pool(indices)

    @pytest.mark.parametrize(
        "template", [-1, -3, 5, RANDOM_POOL, -0x40000000 | 1, RANDOM_POOL | 1 << 24]
    )
    def test_anything_else_is_not_a_pool(self, template: int):
        assert pool_indices(template) is None


class TestParseTemplateSites:
    """Each slot arm of the lobby string parser checks the template `atoi` read with
    `cmp eax, -2 / pop ecx / mov [ebp-0x28], eax / jl <reject>`, and the code it resumes into
    reloads the template from `[ebp-0x28]` - which is what lets the hook clobber `eax`."""

    @pytest.mark.parametrize("check", GAME_INFO_PARSE_TEMPLATE_CHECKS, ids=lambda c: f"{c[0]:#x}")
    def test_the_window_is_the_check(self, check):
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        site, window, resume, reject = check
        listing = [(i.mnemonic, i.op_str) for i in md.disasm(window, site)]
        assert listing == [
            ("cmp", "eax, -2"),
            ("pop", "ecx"),
            ("mov", "dword ptr [ebp - 0x28], eax"),
            ("jl", f"{reject:#x}"),
        ]
        assert site + len(window) == resume

    @pytest.mark.parametrize("check", GAME_INFO_PARSE_TEMPLATE_CHECKS, ids=lambda c: f"{c[0]:#x}")
    def test_the_binary_carries_it_and_nothing_branches_inside(self, stock: bytes, check):
        site, window, resume, _reject = check
        off = va_to_offset(stock, site)
        assert off is not None
        assert stock[off : off + len(window)] == window
        inside = range(site + 1, resume)
        # The parser itself, disassembled: no branch of its own lands mid-window ...
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        md.detail = True
        start = va_to_offset(stock, GAME_INFO_PARSE)
        assert start is not None
        body = stock[start : start + _GAME_INFO_PARSE_END - GAME_INFO_PARSE]
        listing = list(md.disasm(body, GAME_INFO_PARSE))
        assert listing[-1].address + listing[-1].size == _GAME_INFO_PARSE_END
        for ins in listing:
            if ins.group(capstone.CS_GRP_JUMP) and ins.op_str.startswith("0x"):
                assert int(ins.op_str, 16) not in inside, f"{ins.address:#x}"
        # ... and nothing outside it does either.
        outside = {
            target: [src for src in sources if not GAME_INFO_PARSE <= src < _GAME_INFO_PARSE_END]
            for target, sources in _branches_into(stock, inside).items()
        }
        assert not any(outside.values())
        # what follows reads the template back from the frame, not from `eax`
        assert stock[off + len(window) + 0x14 : off + len(window) + 0x17] == bytes.fromhex("3945d8")


class TestObserverTest:
    """`GameSlot::setPlayerTemplate` clears the seat's start position for "-2 or below"; the patch
    makes it -2 alone, so Random's sentinels and pools keep the seat where it was put."""

    def test_the_binary_carries_the_test(self, stock: bytes):
        off = va_to_offset(stock, GAME_SLOT_SET_TEMPLATE_OBSERVER_JG)
        assert off is not None
        # cmp dword [ebp+8], -2 / pop edi / jg +0xd
        assert stock[off - 5 : off + 2] == bytes.fromhex("837d08fe5f7f0d")

    def test_the_patch_makes_it_jne(self, stock: bytes):
        data = bytearray(stock)
        FactionVariantsPatch().apply(data)
        off = va_to_offset(data, GAME_SLOT_SET_TEMPLATE_OBSERVER_JG)
        assert off is not None
        assert data[off] == 0x75
        assert RANDOM_POOL < -2


class TestCommandBlock:
    """The `SetRandomPool` registration is a copy of the screen's own command blocks."""

    def test_assembled_at_the_stock_block_it_is_the_stock_block(self):
        name, handler = struct.unpack_from("<I", MP_SETUP_COMMAND_BLOCK_BYTES, 1)[0], 0x00840143
        a = Asm(MP_SETUP_COMMAND_BLOCK)
        emit_command_block(a, name, handler)
        assert a.finish() == MP_SETUP_COMMAND_BLOCK_BYTES

    def test_the_binary_carries_it_and_nothing_branches_inside(self, stock: bytes):
        off = va_to_offset(stock, MP_SETUP_COMMAND_BLOCK)
        assert off is not None
        assert stock[off : off + len(MP_SETUP_COMMAND_BLOCK_BYTES)] == MP_SETUP_COMMAND_BLOCK_BYTES
        assert MP_SETUP_COMMAND_BLOCK_RESUME == MP_SETUP_COMMAND_BLOCK + 5
        inside = range(MP_SETUP_COMMAND_BLOCK + 1, MP_SETUP_COMMAND_BLOCK + 5)
        assert not _branches_into(stock, inside)


class TestRequestCheckSite:
    def test_the_window_is_the_check(self, stock: bytes):
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        site, window, resume, refuse = GAME_SLOT_REQUEST_TEMPLATE_CHECK
        assert [(i.mnemonic, i.op_str) for i in md.disasm(window, site)] == [
            ("cmp", "edi, -2"),
            ("jl", f"{refuse:#x}"),
        ]
        assert site + len(window) == resume
        off = va_to_offset(stock, site)
        assert off is not None
        assert stock[off : off + len(window)] == window


class TestAllVariantsRule:
    """With `all_variants_box`, the online-only ClanGame checkbox is shown on every setup screen,
    as "Enable all variants"; without it, the checkbox is left as stock."""

    def test_the_binary_hides_rule_1_outside_a_clan_game(self, stock: bytes):
        off = va_to_offset(stock, GAME_RULES_CLAN_GAME_HIDE)
        assert off is not None
        # test byte [ebx+0x3a4], 0x40 / jne +0xf / push 3 / push 1
        assert stock[off - 7 : off + 6] == bytes.fromhex("f683a403000040750f6a036a01")

    def test_the_binary_names_rule_1_clan_game(self, stock: bytes):
        slot = va_to_offset(stock, GAME_RULES_NAMES + 4 * ALL_VARIANTS_RULE)
        assert slot is not None
        assert struct.unpack_from("<I", stock, slot)[0] == GAME_RULES_CLAN_GAME_LABEL
        label = va_to_offset(stock, GAME_RULES_CLAN_GAME_LABEL)
        assert label is not None
        assert stock[label : label + 14] == b"RULE:ClanGame\x00"

    def test_by_default_the_patch_leaves_it_hidden(self, stock: bytes):
        data = bytearray(stock)
        FactionVariantsPatch().apply(data)
        off = va_to_offset(data, GAME_RULES_CLAN_GAME_HIDE)
        assert off is not None
        assert data[off] == stock[off]
        slot = va_to_offset(data, GAME_RULES_NAMES + 4 * ALL_VARIANTS_RULE)
        assert slot is not None
        assert struct.unpack_from("<I", data, slot)[0] == GAME_RULES_CLAN_GAME_LABEL

    def test_detect_recovers_the_option(self, stock: bytes):
        for box in (False, True):
            data = bytearray(stock)
            FactionVariantsPatch(all_variants_box=box).apply(data)
            found = FactionVariantsPatch.detect(data)
            assert found is not None
            assert found.all_variants_box is box
            assert found.options() == ({"all_variants_box": True} if box else {})

    def test_the_patch_shows_it_under_its_own_label(self, stock: bytes):
        data = bytearray(stock)
        FactionVariantsPatch(all_variants_box=True).apply(data)
        off = va_to_offset(data, GAME_RULES_CLAN_GAME_HIDE)
        assert off is not None
        assert data[off] == 0xEB
        slot = va_to_offset(data, GAME_RULES_NAMES + 4 * ALL_VARIANTS_RULE)
        assert slot is not None
        label = va_to_offset(data, struct.unpack_from("<I", data, slot)[0])
        assert label is not None
        assert data[label : label + len(ALL_VARIANTS_LABEL) + 1] == (
            ALL_VARIANTS_LABEL.encode() + b"\x00"
        )

    def test_rule_1_is_the_clan_game_checkbox(self):
        assert GAME_INFO_RULE_CLAN_GAME == GAME_INFO_RULES + 4 * ALL_VARIANTS_RULE
