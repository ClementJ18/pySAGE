"""Tests for per-player `DisabledFactions`.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter disassemble
it back and assert it says what it was meant to say. Four of its properties are invisible to
`apply` and `verify` and would be wrong in ways nobody would notice until a scenario misbehaved,
so each gets its own check:

* **which `ebp` displacement each trampoline reads.** The entire patch rests on the claim that a
  named local at each call site holds the lobby slot index. A trampoline reading the displacement
  of some other local assembles, applies, verifies and then disables factions for whichever player
  a start position or a window handle happens to alias;
* **that the argument is still destroyed.** The replaced function takes its `AsciiString` by value
  and owns it. A cave that returns without the destructor leaks a string buffer per faction per
  redraw of the setup screen, and nothing short of a memory profile would say so;
* **that the comparison stays case-sensitive.** The stock comparison ends in `memcmp`, not
  `_memicmp`. Folding case here would start disabling factions in scenarios that load correctly
  today, which looks like a fix until it is a bug report;
* **where a malformed qualifier goes.** A bare `:`, a non-numeric qualifier and `:0` all have to
  reach the *next-entry* edge, not the *disabled* edge - the alternative is an INI typo silently
  disabling a faction for everybody.

The check that the four call sites are **all** of them lives in `TestInstalledBinary`: it is the
one claim the stand-in cannot make, and a fifth reader left unpatched would mean the rule holds in
the combo box and not at the start gate.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    ASCII_STRING_DTOR,
    EMPTY_STRING,
    MP_SETUP_DISABLED_FACTION_PUSH,
    MP_SETUP_FACTION_COMBO_SLOT_ARG,
    MP_SETUP_RANDOM_LOOP_INIT,
    MP_SETUP_START_GATE_LOOP_INIT,
    MP_SETUP_VALIDATE_LOOP_INIT,
    SCENARIO_DISABLED_FACTIONS_BEGIN,
    SCENARIO_DISABLED_FACTIONS_END,
    SCENARIO_FACTION_CALL_SITES,
    SCENARIO_IS_FACTION_ENABLED,
)
from sage_patch.patches.scenario_player_factions import (
    ANCHORS,
    PLAYER_SEPARATOR,
    SECTION_NAME,
    ScenarioPlayerFactionsPatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

from .synthetic import scenario_player_factions_image

BASE = 0x00F00000

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

#: The anchor whose instruction establishes each site's slot local, and the byte of that anchor
#: holding the displacement - `mov [ebp-0x24], ebx`, `and dword [ebp-0x18], 0` and
#: `mov edi, [ebp+8]` all carry it third. Keyed by call-site index, so a reordering of
#: :data:`~sage_patch.addresses.SCENARIO_FACTION_CALL_SITES` breaks the test rather than passing
#: it against the wrong anchor.
_SLOT_ANCHORS = {
    0: MP_SETUP_START_GATE_LOOP_INIT,
    1: MP_SETUP_VALIDATE_LOOP_INIT,
    2: MP_SETUP_RANDOM_LOOP_INIT,
    3: MP_SETUP_FACTION_COMBO_SLOT_ARG,
}
_SLOT_ANCHOR_DISP_BYTE = 2


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


def cstring(data: bytes | bytearray, va: int) -> str:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    end = data.index(b"\x00", off)
    return bytes(data[off:end]).decode("ascii")


def entry_va(base: int = BASE) -> int:
    """Where the shared replacement starts: what the first trampoline jumps to."""
    decoded = instructions(base)
    first = decoded[base + decoded[base].size]
    assert first.mnemonic == "jmp"
    return int(first.op_str, 16)


def trampoline_heads(base: int = BASE) -> list[int]:
    """The first instruction of each trampoline: everything laid out before the replacement, two
    instructions apiece."""
    return sorted(a for a in instructions(base) if a < entry_va(base))[::2]


class TestTheTrampolines:
    def test_there_is_one_per_call_site(self):
        assert len(trampoline_heads()) == len(SCENARIO_FACTION_CALL_SITES)

    @pytest.mark.parametrize("index", range(len(SCENARIO_FACTION_CALL_SITES)))
    def test_each_reads_its_own_sites_slot_local(self, index):
        """The claim the whole patch rests on, asserted against the emitted bytes rather than
        against the table they were emitted from."""
        capstone = pytest.importorskip("capstone")
        head = instructions()[trampoline_heads()[index]]
        assert text(head).startswith("mov edx, dword ptr [ebp")
        source = head.operands[1]
        assert source.type == capstone.x86.X86_OP_MEM
        assert source.mem.disp == SCENARIO_FACTION_CALL_SITES[index][2]

    @pytest.mark.parametrize("index", range(len(SCENARIO_FACTION_CALL_SITES)))
    def test_each_lands_on_the_shared_replacement(self, index):
        decoded = instructions()
        head = trampoline_heads()[index]
        jump = decoded[head + decoded[head].size]
        assert jump.mnemonic == "jmp"
        assert int(jump.op_str, 16) == entry_va()

    def test_a_trampoline_touches_nothing_but_edx(self):
        """It runs on the *caller's* frame, before the replacement has pushed one. Anything else
        it wrote would be written into the caller's locals."""
        decoded = instructions()
        for head in trampoline_heads():
            assert decoded[head].size == 3
            assert decoded[head + 3].mnemonic == "jmp"


class TestTheReplacement:
    def test_it_disassembles_cleanly_to_its_end(self):
        decoded = instructions()
        assert decoded, "nothing decoded"
        last = max(decoded)
        assert last + decoded[last].size == BASE + len(build_code(BASE))

    def test_it_keeps_the_stock_calling_convention(self):
        """`__thiscall` with one by-value argument, so `ret 4` - anything else unbalances the
        stack of all four callers at once."""
        decoded = instructions()
        rets = [ins for ins in decoded.values() if ins.mnemonic == "ret"]
        assert [text(ins) for ins in rets] == ["ret 4"]

    def test_it_preserves_every_callee_saved_register(self):
        """`ebx`, `esi`, `edi` and `ebp` belong to the caller; `edx` and `ecx` are pushed to make
        the two locals and discarded on the way out."""
        decoded = instructions()
        pushes = [i.op_str for _, i in sorted(decoded.items()) if i.mnemonic == "push"]
        pops = [i.op_str for _, i in sorted(decoded.items()) if i.mnemonic == "pop"]
        assert pushes == ["ebp", "edx", "ecx", "ebx", "esi", "edi"]
        assert pops == ["edi", "esi", "ebx", "ecx", "ecx", "ebp"]

    def test_it_reads_the_disabled_factions_vector_off_the_scenario(self):
        decoded = instructions()
        body = {text(ins) for ins in decoded.values()}
        assert f"mov ebx, dword ptr [ecx + 0x{SCENARIO_DISABLED_FACTIONS_BEGIN:x}]" in body
        assert f"mov edi, dword ptr [ecx + 0x{SCENARIO_DISABLED_FACTIONS_END:x}]" in body

    def test_a_null_argument_reads_as_the_engines_empty_string(self):
        decoded = instructions()
        assert any(text(ins) == f"mov eax, 0x{EMPTY_STRING:x}" for ins in decoded.values())

    def test_it_destroys_the_argument_exactly_once(self):
        """The argument comes by value and the callee owns it, which is what the stock function's
        own tail does. Leaking it is invisible until the setup screen has been redrawn enough
        times to matter."""
        decoded = instructions()
        calls = [ins for ins in decoded.values() if ins.mnemonic == "call"]
        assert [int(ins.op_str, 16) for ins in calls] == [ASCII_STRING_DTOR]
        setup = decoded[max(a for a in decoded if a < calls[0].address)]
        assert text(setup) == "lea ecx, [ebp + 8]", "the argument, still where the caller left it"

    def test_the_answer_survives_the_destructor(self):
        """It clobbers `eax`, so the result has to be parked in a callee-saved register and
        brought back after - and brought back *before* that register is popped."""
        decoded = instructions()
        call = next(ins for ins in decoded.values() if ins.mnemonic == "call")
        stash = next(a for a, i in decoded.items() if text(i) == "mov bl, al")
        assert stash < call.address
        restore = decoded[call.address + call.size]
        assert text(restore) == "mov al, bl"
        pop_ebx = next(a for a, i in decoded.items() if i.mnemonic == "pop" and i.op_str == "ebx")
        assert restore.address < pop_ebx

    def test_the_comparison_is_case_sensitive(self):
        """The stock path bottoms out in `memcmp`. The two character registers may only be loaded
        and compared - any arithmetic on them would be a case fold."""
        decoded = instructions()
        touching = [
            text(ins)
            for ins in decoded.values()
            if any(reg in ins.op_str.split(", ") for reg in ("dl", "cl"))
        ]
        assert set(touching) == {
            "mov dl, byte ptr [eax]",
            "mov cl, byte ptr [esi]",
            f"cmp dl, {PLAYER_SEPARATOR:#x}",
            "test dl, dl",
            "cmp dl, cl",
        }, touching

    def test_it_reads_the_separator_the_ini_writes(self):
        decoded = instructions()
        assert PLAYER_SEPARATOR == ord(":")
        separators = [i for i in decoded.values() if text(i) == f"cmp dl, {PLAYER_SEPARATOR:#x}"]
        assert len(separators) == 2, "once to end the name, once to ask whether a player follows"

    def test_an_unqualified_entry_reaches_the_disabled_edge(self):
        """The stock meaning, and the one every existing scenario depends on: an entry with no
        `:N` disables its faction for everybody."""
        decoded = instructions()
        asks = sorted(a for a, i in decoded.items() if text(i) == f"cmp dl, {PLAYER_SEPARATOR:#x}")
        second = asks[1]
        branch = decoded[second + decoded[second].size]
        assert branch.mnemonic == "jne"
        landing = int(branch.op_str, 16)
        assert text(decoded[landing]) == "xor al, al"

    def test_a_qualifier_with_no_digits_reaches_the_next_entry_edge(self):
        """A bare `:` names no player. Reading it as slot zero would disable the faction for the
        first player on the strength of a typo."""
        decoded = instructions()
        first_digit_test = min(a for a, i in decoded.items() if text(i) == "cmp edx, 9")
        branch = decoded[first_digit_test + decoded[first_digit_test].size]
        assert branch.mnemonic == "ja"
        assert text(decoded[int(branch.op_str, 16)]) == "add ebx, 4"

    def test_player_zero_reaches_the_next_entry_edge(self):
        decoded = instructions()
        zero_test = next(a for a, i in decoded.items() if text(i) == "test ecx, ecx")
        branch = decoded[zero_test + decoded[zero_test].size]
        assert branch.mnemonic == "je"
        assert text(decoded[int(branch.op_str, 16)]) == "add ebx, 4"

    def test_the_ini_counts_players_from_one(self):
        """The INI writes `:1` for the first slot; the engine's slot index is 0-based. The `inc`
        between the two is the whole of that translation, and dropping it would shift every
        scenario by one player."""
        decoded = instructions()
        load = next(a for a, i in decoded.items() if text(i) == "mov edx, dword ptr [ebp - 4]")
        assert text(decoded[load + decoded[load].size]) == "inc edx"
        compare = load + decoded[load].size + decoded[load + decoded[load].size].size
        assert text(decoded[compare]) == "cmp ecx, edx"

    def test_a_qualifier_for_another_player_reaches_the_next_entry_edge(self):
        decoded = instructions()
        compare = next(a for a, i in decoded.items() if text(i) == "cmp ecx, edx")
        branch = decoded[compare + decoded[compare].size]
        assert branch.mnemonic == "jne"
        assert text(decoded[int(branch.op_str, 16)]) == "add ebx, 4"

    def test_a_prefix_of_the_side_name_is_not_a_match(self):
        """`FactionMen` must not match `FactionMenX`, in either direction: the entry stops at its
        NUL or its `:`, so the side name has to be exhausted at the same point."""
        decoded = instructions()
        assert any(text(ins) == "cmp byte ptr [esi], 0" for ins in decoded.values())

    def test_every_branch_stays_inside_the_cave(self):
        decoded = instructions()
        size = len(build_code(BASE))
        for ins in decoded.values():
            if ins.mnemonic.startswith("j"):
                target = int(ins.op_str, 16)
                assert BASE <= target < BASE + size, f"{text(ins)} leaves the cave"

    def test_it_writes_only_its_own_frame(self):
        """Two locals, both below `ebp`. A store anywhere else would be writing through a pointer
        the routine only has permission to read."""
        capstone = pytest.importorskip("capstone")
        decoded = instructions()
        stores = {
            text(ins)
            for ins in decoded.values()
            for op in ins.operands
            if op.type == capstone.x86.X86_OP_MEM and op.access & capstone.CS_AC_WRITE
        }
        assert stores == {"mov dword ptr [ebp - 8], eax"}, stores

    def test_it_relocates_with_its_section(self):
        assert build_code(BASE) != build_code(BASE + 0x1000)


class TestApply:
    @pytest.fixture
    def image(self) -> bytearray:
        return scenario_player_factions_image()

    def test_apply_then_verify(self, image):
        patch = ScenarioPlayerFactionsPatch()
        patch.apply(image)
        assert patch.verify(image) == []

    def test_every_site_becomes_a_call_into_its_own_trampoline(self, image):
        ScenarioPlayerFactionsPatch().apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        section_va, _, _ = located
        heads = trampoline_heads(section_va)
        for head, (site, original, _) in zip(heads, SCENARIO_FACTION_CALL_SITES, strict=True):
            hook = at(image, site, len(original))
            assert hook[0] == 0xE8
            assert site + 5 + struct.unpack("<i", hook[1:5])[0] == head

    def test_it_leaves_the_replaced_function_alone(self, image):
        """The stock `Scenario::isFactionEnabled` stays where it is, unreferenced. Rewriting it in
        place would be a second patch's worth of risk for no gain, and leaving it makes the
        four redirected calls the whole of the change."""
        before = at(image, SCENARIO_IS_FACTION_ENABLED, len(ANCHORS[SCENARIO_IS_FACTION_ENABLED]))
        ScenarioPlayerFactionsPatch().apply(image)
        assert at(image, SCENARIO_IS_FACTION_ENABLED, len(before)) == before

    def test_the_section_name_survives_the_eight_byte_pe_field(self):
        assert len(SECTION_NAME) <= 8

    def test_refuses_to_apply_twice(self, image):
        ScenarioPlayerFactionsPatch().apply(image)
        with pytest.raises(ValueError):
            ScenarioPlayerFactionsPatch().apply(image)

    @pytest.mark.parametrize("anchor", sorted(ANCHORS))
    def test_refuses_a_build_where_an_anchor_moved(self, image, anchor):
        off = va_to_offset(image, anchor)
        image[off] ^= 0xFF
        with pytest.raises(ValueError, match="layout is not this build's"):
            ScenarioPlayerFactionsPatch().apply(image)

    def test_refuses_an_unmapped_build(self):
        with pytest.raises(ValueError, match="not mapped"):
            ScenarioPlayerFactionsPatch().apply(bytearray(b"MZ" + b"\x00" * 0x400))


class TestVerify:
    def test_rejects_an_unpatched_file(self):
        problems = ScenarioPlayerFactionsPatch().verify(scenario_player_factions_image())
        assert problems == [f"{SECTION_NAME} section is absent"]

    def test_rejects_a_cave_whose_code_was_altered(self):
        image = scenario_player_factions_image()
        patch = ScenarioPlayerFactionsPatch()
        patch.apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        _, section_off, _ = located
        image[section_off] ^= 0xFF
        assert patch.verify(image) == [
            f"the {SECTION_NAME} cave does not hold the expected routine"
        ]

    def test_rejects_a_call_pointing_somewhere_else(self):
        image = scenario_player_factions_image()
        patch = ScenarioPlayerFactionsPatch()
        patch.apply(image)
        off = va_to_offset(image, SCENARIO_FACTION_CALL_SITES[0][0])
        struct.pack_into("<i", image, off + 1, 0x20)
        assert any("calls" in problem for problem in patch.verify(image))

    def test_a_call_left_unpatched_is_reported(self):
        """Three of four is not the patch: the rule would hold in the combo box and not at the
        start gate, or the other way round."""
        image = scenario_player_factions_image()
        patch = ScenarioPlayerFactionsPatch()
        patch.apply(image)
        site, original, _ = SCENARIO_FACTION_CALL_SITES[-1]
        off = va_to_offset(image, site)
        image[off : off + len(original)] = original
        assert any("calls" in problem for problem in patch.verify(image))


class TestRegistration:
    def test_it_is_registered_under_its_name(self):
        assert PATCHES[ScenarioPlayerFactionsPatch.name] is ScenarioPlayerFactionsPatch

    def test_it_is_not_experimental(self):
        """The module lives outside `experimental/`, so the attribute has to agree - the two are
        the same fact, and `TestExperimentalPatchesAreDeclared` fails on either mismatch."""
        assert not ScenarioPlayerFactionsPatch.experimental


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
class TestInstalledBinary:
    """Against the real binary, which is the only thing that can say the addresses are right.

    The stand-in is built from this patch's own tables, so it round-trips whatever they say. Only
    the shipped `game.dat` can confirm that the four addresses really are `call
    Scenario::isFactionEnabled`, that there is no fifth, and that each site's declared slot
    displacement is the one that site's own code establishes.
    """

    @pytest.fixture(scope="class")
    def stock(self) -> bytes:
        return _GAME_DAT.read_bytes()

    def test_every_site_holds_its_stock_bytes(self, stock):
        for va, original, _ in SCENARIO_FACTION_CALL_SITES:
            assert at(stock, va, len(original)) == original, f"0x{va:08x}"

    def test_every_anchor_holds_its_stock_bytes(self, stock):
        for va, expected in ANCHORS.items():
            assert at(stock, va, len(expected)) == expected, f"0x{va:08x}"

    def test_every_site_calls_the_function_being_replaced(self, stock):
        for va, original, _ in SCENARIO_FACTION_CALL_SITES:
            assert original[0] == 0xE8
            assert va + 5 + struct.unpack("<i", original[1:5])[0] == SCENARIO_IS_FACTION_ENABLED

    def test_those_four_are_every_caller_in_the_image(self, stock):
        """Decoded at every byte offset rather than by a linear sweep, which desynchronises on
        inlined data and drops call sites silently. That yields the occasional false positive
        instead - which is visible, and which a window with no hits rules out entirely."""
        section = next(s for s in _sections(stock) if s[0] == ".text")
        _, start_va, raw_off, size = section
        found = set()
        for offset in range(size - 5):
            if stock[raw_off + offset] != 0xE8:
                continue
            va = start_va + offset
            target = va + 5 + struct.unpack_from("<i", stock, raw_off + offset + 1)[0]
            if target == SCENARIO_IS_FACTION_ENABLED:
                found.add(va)
        assert found == {va for va, _, _ in SCENARIO_FACTION_CALL_SITES}

    @pytest.mark.parametrize("index", sorted(_SLOT_ANCHORS))
    def test_each_slot_displacement_is_the_one_its_site_establishes(self, stock, index):
        """`SCENARIO_FACTION_CALL_SITES` says which local holds the slot; the anchor is the
        instruction that writes or loads it. If they ever disagree, the trampoline is reading
        something that is not a slot."""
        anchor = _SLOT_ANCHORS[index]
        declared = SCENARIO_FACTION_CALL_SITES[index][2]
        planted = ANCHORS[anchor][_SLOT_ANCHOR_DISP_BYTE]
        assert struct.unpack("<b", bytes([planted]))[0] == declared
        assert at(stock, anchor, len(ANCHORS[anchor])) == ANCHORS[anchor]

    def test_the_start_gate_raises_the_disabled_faction_message(self, stock):
        """The one anchor that cannot be a coincidence of layout: the `push` recorded in ANCHORS
        carries the address of the string the gate this patch extends puts on screen."""
        push = ANCHORS[MP_SETUP_DISABLED_FACTION_PUSH]
        assert push[0] == 0x68
        assert cstring(stock, struct.unpack("<I", push[1:5])[0]) == "GUI:DisabledFaction"


def _sections(data: bytes) -> list[tuple[str, int, int, int]]:
    """`(name, virtual address, raw offset, raw size)` for every section of ``data``."""
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    count = struct.unpack_from("<H", data, e_lfanew + 6)[0]
    opt_size = struct.unpack_from("<H", data, e_lfanew + 20)[0]
    base = struct.unpack_from("<I", data, e_lfanew + 24 + 28)[0]
    table = e_lfanew + 24 + opt_size
    out = []
    for index in range(count):
        header = table + index * 40
        name = data[header : header + 8].rstrip(b"\x00").decode("ascii")
        rva, raw_size, raw_off = struct.unpack_from("<III", data, header + 12)
        out.append((name, base + rva, raw_off, raw_size))
    return out
