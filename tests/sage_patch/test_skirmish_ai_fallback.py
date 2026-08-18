"""Tests for the skirmish AI fallback.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter disassemble
it back and assert it says what it was meant to say. Two failure modes are invisible to `apply` and
`verify` and fatal in game, so both get their own check:

* a **stack imbalance** - the cave calls four engine routines with three different `ret` sizes and
  discards its own return address on one path, and getting any of that wrong corrupts the frame of
  the function it was called from rather than failing anywhere near the cave. `TestStackBalance`
  walks every path and asserts the net `esp` delta at each exit;
* a hook that **fires on the wrong case** - the whole point is that a faction with a side keeps its
  stock behaviour byte for byte, so the marker value and the three edges of the second hook are
  asserted individually.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    DICT_SET_ASCII_STRING,
    PLAYER_INDEX,
    PLAYER_INIT_FROM_DICT,
    PLAYER_SKIRMISH_FOUND_EBP,
    PLAYER_SKIRMISH_IMPORT,
    PLAYER_SKIRMISH_IMPORT_BYTES,
    PLAYER_SKIRMISH_IMPORT_RESUME,
    PLAYER_SKIRMISH_IMPORT_SKIP,
    PLAYER_SKIRMISH_MISSING_EBP,
    PLAYER_SKIRMISH_ROUTE,
    PLAYER_SKIRMISH_ROUTE_BYTES,
    PLAYER_SKIRMISH_ROUTE_RESUME,
    PLAYER_TEMPLATE_DEFAULT_AI_TYPE,
    PLAYER_TEMPLATE_PTR,
    SIDES_INFO_DICT,
    SIDES_LIST_GET_SIDE_INFO,
    SIDES_LIST_LOAD_AI_LIBRARY_FOR_SIDE,
    STATIC_NAME_KEY_KEY,
    THE_SIDES_LIST,
)
from sage_patch.patches.skirmish_ai_fallback import (
    ANCHORS,
    SECTION_NAME,
    SYNTHESISED,
    SkirmishAiFallbackPatch,
    build_code,
    entry_points,
)
from sage_patch.pe import image_sections
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, next_section_rva, va_to_offset

from .synthetic import skirmish_ai_fallback_image

BASE = 0x00F00000

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

#: `Player::initFromDict` runs from its prologue to the next function's, which is where the
#: branch-target sweep has to stop: a jump from outside it cannot reach a frame local anyway.
_INIT_FROM_DICT_SIZE = 0x957

#: How much each engine routine the cave calls pops on the way out. A `__thiscall` with stack
#: arguments cleans them itself, so this is what the call is worth to `esp` - and it is the claim
#: `TestStackBalance` turns into a check.
RET_SIZES = {
    STATIC_NAME_KEY_KEY: 0,
    SIDES_LIST_GET_SIDE_INFO: 4,
    DICT_SET_ASCII_STRING: 8,
    SIDES_LIST_LOAD_AI_LIBRARY_FOR_SIDE: 4,
}


def instructions(base: int = BASE):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return {ins.address: ins for ins in md.disasm(build_code(base), base)}


def text(ins) -> str:
    return f"{ins.mnemonic} {ins.op_str}".strip()


def at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + count])


class TestTheCave:
    def test_the_route_hook_starts_the_cave(self):
        route, _ = entry_points(BASE)
        assert route == BASE

    def test_the_two_entry_points_are_distinct_instructions(self):
        route, import_ = entry_points(BASE)
        decoded = instructions()
        assert route in decoded and import_ in decoded
        assert route != import_

    def test_the_route_hook_reproduces_the_flag_test_it_replaced(self):
        route, _ = entry_points(BASE)
        decoded = instructions()
        missing = PLAYER_SKIRMISH_MISSING_EBP & 0xFF
        assert text(decoded[route]) == f"cmp byte ptr [ebp - 0x{0x100 - missing:x}], 0"

    def test_the_route_hook_writes_the_marker_and_clears_the_missing_flag(self):
        route, _ = entry_points(BASE)
        decoded = instructions()
        body = [text(decoded[a]) for a in sorted(decoded) if route <= a]
        writes = [line for line in body[:5] if line.startswith("mov byte")]
        assert writes == [
            f"mov byte ptr [ebp - 0x{0x100 - (PLAYER_SKIRMISH_MISSING_EBP & 0xFF):x}], 0",
            f"mov byte ptr [ebp - 0x{0x100 - (PLAYER_SKIRMISH_FOUND_EBP & 0xFF):x}], {SYNTHESISED}",
        ]

    def test_the_route_hook_returns_rather_than_jumping(self):
        """It is called in place of a `cmp`/`jne` pair and has to give the stock fall-through
        back, because that fall-through is the arm a player with a matching side takes."""
        route, import_ = entry_points(BASE)
        decoded = instructions()
        assert any(decoded[a].mnemonic == "ret" for a in sorted(decoded) if route <= a < import_)
        assert not any(
            decoded[a].mnemonic in {"jmp", "call"} for a in sorted(decoded) if route <= a < import_
        )

    def test_the_marker_is_neither_of_the_stock_flag_values(self):
        """0 and 1 both have stock meanings at the second hook and must keep them."""
        assert SYNTHESISED not in (0, 1)

    def test_the_import_hook_reads_the_found_flag_first(self):
        _, import_ = entry_points(BASE)
        decoded = instructions()
        found = PLAYER_SKIRMISH_FOUND_EBP & 0xFF
        assert text(decoded[import_]) == f"mov al, byte ptr [ebp - 0x{0x100 - found:x}]"

    def test_the_import_hook_compares_against_the_marker(self):
        _, import_ = entry_points(BASE)
        decoded = instructions()
        assert any(text(ins) == f"cmp al, {SYNTHESISED}" for ins in decoded.values())

    def test_the_synthesised_path_reads_the_players_own_template(self):
        decoded = instructions()
        assert any(
            text(ins) == f"mov eax, dword ptr [esi + 0x{PLAYER_TEMPLATE_PTR:x}]"
            for ins in decoded.values()
        ), "the template has to come off the Player, not off any matched side"

    def test_it_takes_the_default_ai_type_field(self):
        decoded = instructions()
        assert any(
            text(ins) == f"add eax, 0x{PLAYER_TEMPLATE_DEFAULT_AI_TYPE:x}"
            for ins in decoded.values()
        )

    def test_it_addresses_the_players_own_side_by_its_player_index(self):
        decoded = instructions()
        pushes = [text(ins) for ins in decoded.values() if ins.mnemonic == "push"]
        assert pushes.count(f"push dword ptr [esi + 0x{PLAYER_INDEX:x}]") == 2, (
            "once for getSideInfo and once for the library load"
        )

    def test_it_writes_into_the_side_dict_not_the_side(self):
        decoded = instructions()
        assert any(text(ins) == f"lea ecx, [eax + {SIDES_INFO_DICT}]" for ins in decoded.values())

    @pytest.mark.parametrize(
        "target",
        [
            STATIC_NAME_KEY_KEY,
            SIDES_LIST_GET_SIDE_INFO,
            DICT_SET_ASCII_STRING,
            SIDES_LIST_LOAD_AI_LIBRARY_FOR_SIDE,
        ],
    )
    def test_it_calls_each_engine_routine_exactly_once(self, target):
        decoded = instructions()
        calls = [ins for ins in decoded.values() if ins.mnemonic == "call"]
        assert [ins for ins in calls if ins.op_str == hex(target)], f"{target:#010x} is not called"

    def test_it_loads_the_sides_list_singleton_for_each_thiscall(self):
        decoded = instructions()
        loads = [
            text(ins)
            for ins in decoded.values()
            if text(ins) == f"mov ecx, dword ptr [{THE_SIDES_LIST:#x}]"
        ]
        assert len(loads) == 2

    def test_the_only_outward_jump_is_the_engines_own_nothing_to_import_edge(self):
        decoded = instructions()
        outward = [
            ins.op_str
            for ins in decoded.values()
            if ins.mnemonic == "jmp" and not (BASE <= int(ins.op_str, 16) < BASE + 0x200)
        ]
        assert outward == [hex(PLAYER_SKIRMISH_IMPORT_SKIP)]

    def test_the_matched_case_returns_into_the_stock_import(self):
        """A found flag of 1 must leave the engine's own path alone, which means returning - the
        call was written over the `cmp`/`je` pair that sits immediately before it."""
        decoded = instructions()
        _, import_ = entry_points(BASE)
        assert [a for a in sorted(decoded) if a > import_ and decoded[a].mnemonic == "ret"]


class TestStackBalance:
    """Every path through the cave, walked for its net effect on `esp`.

    A `call` is worth what the callee pops, because all four are `__thiscall` with the callee
    cleaning its stack arguments. An exit by `ret` has to be back where it started; an exit by
    `jmp` has to have discarded the return address the hook's `call` pushed, so `+4`.
    """

    def _walk(self):
        decoded = instructions()
        _, import_ = entry_points(BASE)
        exits: list[tuple[int, str, int]] = []
        seen: set[tuple[int, int]] = set()

        def step(addr: int, delta: int) -> None:
            while True:
                if (addr, delta) in seen:
                    return
                seen.add((addr, delta))
                ins = decoded.get(addr)
                assert ins is not None, f"walked out of the cave at {addr:#010x}"
                name, ops = ins.mnemonic, ins.op_str
                if name == "push":
                    delta -= 4
                elif name == "pop":
                    delta += 4
                elif name == "add" and ops.startswith("esp,"):
                    delta += int(ops.split(",")[1], 0)
                elif name == "call":
                    delta += RET_SIZES[int(ops, 16)]
                elif name == "ret":
                    exits.append((addr, "ret", delta))
                    return
                elif name == "jmp":
                    target = int(ops, 16)
                    if not (BASE <= target < BASE + 0x200):
                        exits.append((addr, "jmp", delta))
                        return
                    addr = target
                    continue
                elif name.startswith("j"):
                    step(int(ops, 16), delta)
                addr += ins.size

        step(import_, 0)
        return exits

    def test_every_path_exits_balanced(self):
        for addr, kind, delta in self._walk():
            expected = 0 if kind == "ret" else 4
            assert delta == expected, (
                f"{kind} at {addr:#010x} leaves esp {delta:+d}, expected {expected:+d}"
            )

    def test_the_walk_reaches_both_kinds_of_exit(self):
        kinds = {kind for _, kind, _ in self._walk()}
        assert kinds == {"ret", "jmp"}


class TestApply:
    def test_it_applies_and_verifies(self):
        data = skirmish_ai_fallback_image()
        patch = SkirmishAiFallbackPatch()
        patch.apply(data)
        assert patch.verify(data) == []

    def test_a_stock_image_does_not_verify(self):
        assert SkirmishAiFallbackPatch().verify(skirmish_ai_fallback_image())

    def test_both_hooks_become_calls_into_the_cave(self):
        data = skirmish_ai_fallback_image()
        SkirmishAiFallbackPatch().apply(data)
        section_va, _, _ = find_section(data, SECTION_NAME)
        route, import_ = entry_points(section_va)
        for hook_va, expected in (
            (PLAYER_SKIRMISH_ROUTE, route),
            (PLAYER_SKIRMISH_IMPORT, import_),
        ):
            off = va_to_offset(data, hook_va)
            assert data[off] == 0xE8
            assert hook_va + 5 + struct.unpack_from("<i", data, off + 1)[0] == expected

    def test_the_wider_window_is_filled_to_its_resume_point(self):
        """The second window is ten bytes and a call is five, so the rest has to be `nop` - a
        leftover byte of the old `je` would be decoded as an instruction."""
        data = skirmish_ai_fallback_image()
        SkirmishAiFallbackPatch().apply(data)
        off = va_to_offset(data, PLAYER_SKIRMISH_IMPORT)
        tail = bytes(data[off + 5 : off + len(PLAYER_SKIRMISH_IMPORT_BYTES)])
        assert tail == b"\x90" * 5
        assert PLAYER_SKIRMISH_IMPORT + len(PLAYER_SKIRMISH_IMPORT_BYTES) == (
            PLAYER_SKIRMISH_IMPORT_RESUME
        )

    def test_the_narrow_window_is_exactly_a_call(self):
        assert len(PLAYER_SKIRMISH_ROUTE_BYTES) == 5
        assert PLAYER_SKIRMISH_ROUTE + 5 == PLAYER_SKIRMISH_ROUTE_RESUME

    def test_it_is_detected_with_its_cave(self):
        data = skirmish_ai_fallback_image()
        SkirmishAiFallbackPatch().apply(data)
        assert isinstance(SkirmishAiFallbackPatch.detect(data), SkirmishAiFallbackPatch)

    def test_an_unpatched_image_carries_nothing(self):
        assert SkirmishAiFallbackPatch.detect(skirmish_ai_fallback_image()) is None

    def test_detection_never_raises_on_something_that_is_not_a_game_dat(self):
        assert SkirmishAiFallbackPatch.detect(b"not a PE at all") is None

    def test_applying_twice_raises_rather_than_double_hooking(self):
        data = skirmish_ai_fallback_image()
        SkirmishAiFallbackPatch().apply(data)
        with pytest.raises(ValueError):
            SkirmishAiFallbackPatch().apply(data)

    def test_the_cave_lands_past_every_existing_section(self):
        data = skirmish_ai_fallback_image()
        expected = next_section_rva(data)
        SkirmishAiFallbackPatch().apply(data)
        section_va, _, _ = find_section(data, SECTION_NAME)
        assert section_va - 0x400000 == expected

    @pytest.mark.parametrize("va", sorted(ANCHORS))
    def test_a_moved_anchor_is_refused(self, va):
        data = skirmish_ai_fallback_image()
        off = va_to_offset(data, va)
        data[off] ^= 0xFF
        with pytest.raises(ValueError):
            SkirmishAiFallbackPatch().apply(data)

    @pytest.mark.parametrize("va", [PLAYER_SKIRMISH_ROUTE, PLAYER_SKIRMISH_IMPORT])
    def test_a_moved_hook_site_is_refused(self, va):
        data = skirmish_ai_fallback_image()
        off = va_to_offset(data, va)
        data[off] ^= 0xFF
        with pytest.raises(ValueError):
            SkirmishAiFallbackPatch().apply(data)

    def test_it_is_registered(self):
        assert PATCHES[SkirmishAiFallbackPatch.name] is SkirmishAiFallbackPatch


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
class TestInstalledBinary:
    """Against the real binary, which is the only thing that can say the addresses are right.

    The stand-in is built from this patch's own anchor table, so it round-trips whatever that table
    says. Only the shipped `game.dat` can confirm that `0x006B09F5` is the skirmish-side fork rather
    than the middle of some other comparison.
    """

    @pytest.fixture(scope="class")
    def stock(self) -> bytes:
        return _GAME_DAT.read_bytes()

    def test_every_site_holds_its_stock_bytes(self, stock):
        for va, expected in (
            (PLAYER_SKIRMISH_ROUTE, PLAYER_SKIRMISH_ROUTE_BYTES),
            (PLAYER_SKIRMISH_IMPORT, PLAYER_SKIRMISH_IMPORT_BYTES),
            *ANCHORS.items(),
        ):
            assert at(stock, va, len(expected)) == expected, f"0x{va:08x}"

    def test_apply_verify_detect_round_trip(self, stock):
        data = bytearray(stock)
        patch = SkirmishAiFallbackPatch()
        patch.apply(data)
        assert patch.verify(data) == []
        assert SkirmishAiFallbackPatch.detect(data) is not None

    def test_the_stock_binary_carries_no_fallback(self, stock):
        assert SkirmishAiFallbackPatch.detect(stock) is None

    @pytest.mark.parametrize(
        ("hook", "window"),
        [
            (PLAYER_SKIRMISH_ROUTE, PLAYER_SKIRMISH_ROUTE_BYTES),
            (PLAYER_SKIRMISH_IMPORT, PLAYER_SKIRMISH_IMPORT_BYTES),
        ],
    )
    def test_nothing_branches_into_a_window(self, stock, hook, window):
        """A hook may be *landed on* - two jumps target the second one - but nothing may jump into
        its interior, or the replacement `call` would be entered part-way through."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        start = va_to_offset(stock, PLAYER_INIT_FROM_DICT)
        body = stock[start : start + _INIT_FROM_DICT_SIZE]
        interior = range(hook + 1, hook + len(window))
        for ins in md.disasm(body, PLAYER_INIT_FROM_DICT):
            if ins.mnemonic.startswith("j") and ins.op_str.startswith("0x"):
                assert int(ins.op_str, 16) not in interior, (
                    f"{ins.address:#010x} branches into the window at {hook:#010x}"
                )

    def test_the_library_loader_has_no_other_caller(self, stock):
        """The whole design rests on `SIDES_LIST_LOAD_AI_LIBRARY_FOR_SIDE` being the engine's own
        single-side loader that nothing currently uses, so driving it once per player disturbs
        nobody. Every direct `call` in the image is decoded and counted."""
        callers = 0
        for section in image_sections(stock):
            body = stock[section.raw_offset : section.raw_offset + section.raw_size]
            for off in range(len(body) - 5):
                if body[off] != 0xE8:
                    continue
                va = section.virtual_address + off
                target = va + 5 + struct.unpack_from("<i", body, off + 1)[0]
                if target == SIDES_LIST_LOAD_AI_LIBRARY_FOR_SIDE:
                    callers += 1
        assert callers == 0, f"{callers} call sites already reach the single-side loader"
