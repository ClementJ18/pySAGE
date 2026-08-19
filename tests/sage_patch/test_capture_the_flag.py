"""Tests for the proximity capture-the-flag patch.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter most
disassemble it back and assert it says what it was meant to say. A wrong byte does not raise: it
buckets a candidate against a garbage player index, or hands `setTeam` something that is not a
team, and the first symptom is a crash in a live match. Encoding errors have to be caught
statically, so every engine call the routine makes is checked to land on the address it names.

The other half is the build fingerprint. The patch replaces a field-parse table it first *reads*,
and abandons four stock keywords in the process, so it has to refuse anything that is not the
table it expects rather than quietly installing over it.
"""

from __future__ import annotations

import struct

import pytest

from sage_ini.engine import STOCK
from sage_ini.model.objects import REGISTRY
from sage_patch.patches.experimental import capture_the_flag as ctf
from sage_patch.patches.experimental.capture_the_flag import (
    DEFAULT_BLOCK,
    FIELD_TABLE_REF_VA,
    FIELD_TABLE_VA,
    FIELDS,
    INSTANCE_SIZE_VA,
    MODULEDATA_SIZE_VA,
    NAME_REF_VAS,
    PATCHED_INSTANCE_SIZE,
    PATCHED_MODULEDATA_SIZE,
    SECTION_NAME,
    STOCK_FIELD_TABLE,
    UPDATE_VTABLE_VA,
    CaptureTheFlagPatch,
)
from sage_patch.patches.utils.kind_of import read as read_kindof_table
from sage_patch.patches.utils.name_tables import read_cstring
from sage_patch.utils import find_section, va_to_offset

from .synthetic import capture_the_flag_image


@pytest.fixture
def image() -> bytearray:
    return capture_the_flag_image()


def _dword(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    assert off is not None
    return int(struct.unpack_from("<I", data, off)[0])


def _cstring(data: bytes | bytearray, va: int) -> str:
    off = va_to_offset(data, va)
    assert off is not None
    return bytes(data[off : data.index(b"\x00", off)]).decode("ascii")


class TestApply:
    def test_applies_and_verifies(self, image: bytearray) -> None:
        patch = CaptureTheFlagPatch()
        patch.apply(image)
        assert patch.verify(image) == []

    def test_verify_fails_on_an_unpatched_image(self, image: bytearray) -> None:
        assert CaptureTheFlagPatch().verify(image) != []

    def test_allocations_grow(self, image: bytearray) -> None:
        CaptureTheFlagPatch().apply(image)
        instance = va_to_offset(image, INSTANCE_SIZE_VA)
        moduledata = va_to_offset(image, MODULEDATA_SIZE_VA)
        assert instance is not None and moduledata is not None
        assert image[instance + 1] == PATCHED_INSTANCE_SIZE
        assert image[moduledata + 1] == PATCHED_MODULEDATA_SIZE

    def test_every_repoint_lands_inside_the_cave(self, image: bytearray) -> None:
        patch = CaptureTheFlagPatch()
        patch.apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        base_va, _off, vsize = located
        for va in (UPDATE_VTABLE_VA, FIELD_TABLE_REF_VA, *NAME_REF_VAS):
            assert base_va <= _dword(image, va) < base_va + vsize, f"{va:#x} escapes the cave"

    def test_the_block_is_renamed_consistently(self, image: bytearray) -> None:
        """All three references name the block. If they ever disagree the engine registers one
        name and parses another, which is a silently broken module rather than a loud one."""
        patch = CaptureTheFlagPatch()
        patch.apply(image)
        names = {_cstring(image, _dword(image, va)) for va in NAME_REF_VAS}
        assert names == {DEFAULT_BLOCK}

    def test_a_custom_block_name_is_installed(self, image: bytearray) -> None:
        patch = CaptureTheFlagPatch(block_name="HoldTheLineUpdate")
        patch.apply(image)
        assert patch.verify(image) == []
        assert _cstring(image, _dword(image, NAME_REF_VAS[0])) == "HoldTheLineUpdate"

    def test_a_block_name_that_is_not_an_identifier_is_refused(self) -> None:
        with pytest.raises(ValueError, match="identifier"):
            CaptureTheFlagPatch(block_name="Not A Name")

    def test_the_rebuilt_table_carries_every_keyword(self, image: bytearray) -> None:
        patch = CaptureTheFlagPatch()
        patch.apply(image)
        table_va = _dword(image, FIELD_TABLE_REF_VA)
        for index, (keyword, parse, offset, _type) in enumerate(FIELDS):
            row = table_va + index * 16
            assert _cstring(image, _dword(image, row)) == keyword
            assert _dword(image, row + 4) == parse
            assert _dword(image, row + 12) == offset
        assert _dword(image, table_va + len(FIELDS) * 16) == 0, "table is not terminated"


class TestBuildFingerprint:
    """The patch reads before it writes, so a binary that is not this build must fail loudly."""

    def test_a_changed_keyword_is_refused(self, image: bytearray) -> None:
        """Row 0 is pointed at another row's keyword - a perfectly valid string in a perfectly
        valid table, just not the one this patch read. That is the realistic shape of a build
        difference, and the one a length or mapping check would miss."""
        off = va_to_offset(image, FIELD_TABLE_VA)
        assert off is not None
        struct.pack_into("<I", image, off, _dword(image, FIELD_TABLE_VA + 3 * 16))
        with pytest.raises(ValueError, match="row 0"):
            CaptureTheFlagPatch().apply(image)

    def test_a_changed_parse_function_is_refused(self, image: bytearray) -> None:
        off = va_to_offset(image, FIELD_TABLE_VA)
        assert off is not None
        struct.pack_into("<I", image, off + 4, 0x00DEAD00)
        with pytest.raises(ValueError, match="row 0"):
            CaptureTheFlagPatch().apply(image)

    def test_an_unterminated_table_is_refused(self, image: bytearray) -> None:
        off = va_to_offset(image, FIELD_TABLE_VA)
        assert off is not None
        struct.pack_into("<I", image, off + len(STOCK_FIELD_TABLE) * 16, 0x00C00000)
        with pytest.raises(ValueError, match="terminated"):
            CaptureTheFlagPatch().apply(image)

    def test_a_moved_allocation_literal_is_refused(self, image: bytearray) -> None:
        off = va_to_offset(image, INSTANCE_SIZE_VA)
        assert off is not None
        image[off + 1] = 0x28
        with pytest.raises(ValueError, match="expected"):
            CaptureTheFlagPatch().apply(image)

    def test_applying_twice_is_refused(self, image: bytearray) -> None:
        """The second apply meets its own rewritten table, which is not the stock one."""
        CaptureTheFlagPatch().apply(image)
        with pytest.raises(ValueError):
            CaptureTheFlagPatch().apply(image)


class TestDetect:
    def test_detects_nothing_in_a_clean_image(self, image: bytearray) -> None:
        assert CaptureTheFlagPatch.detect(image) is None

    def test_recovers_the_installed_block_name(self, image: bytearray) -> None:
        CaptureTheFlagPatch(block_name="HoldTheLineUpdate").apply(image)
        found = CaptureTheFlagPatch.detect(image)
        assert found is not None
        assert found.block_name == "HoldTheLineUpdate"


class TestCave:
    """Read the emitted machine code back. Nothing else catches a wrong ModRM byte."""

    @staticmethod
    def _instructions(data: bytes | bytearray) -> list:
        capstone = pytest.importorskip("capstone")
        located = find_section(data, SECTION_NAME)
        assert located is not None
        base_va, off, _vsize = located
        patch = CaptureTheFlagPatch()
        code_bytes = patch._layout(base_va).table_va - base_va
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        return list(md.disasm(bytes(data[off : off + code_bytes]), base_va))

    def test_every_engine_call_is_an_address_the_patch_names(self, image: bytearray) -> None:
        """A `call` into the middle of an instruction disassembles perfectly well. What proves
        the targets right is that each one equals a documented entry point."""
        expected = {
            ctf._ITERATE_IN_RANGE,
            ctf._ITER_NEXT,
            ctf._ITER_RELEASE,
            ctf._GET_CONTROLLING_PLAYER,
            ctf._GET_CONTAIN,
            ctf._SET_TEAM,
            ctf._PROPAGATE_MODEL_CONDITIONS,
            ctf._FILTER_TEST,
            ctf._FILTER_WAS_SPECIFIED,
            ctf._FILTER_CTOR,
            ctf._REGISTER_COMMAND_SET,
            ctf.INSTANCE_CTOR_VA,
            ctf.MODULEDATA_CTOR_VA,
        }
        CaptureTheFlagPatch().apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        base_va, _off, vsize = located
        targets = set()
        for insn in self._instructions(image):
            if insn.mnemonic == "call" and insn.op_str.startswith("0x"):
                target = int(insn.op_str, 16)
                if not base_va <= target < base_va + vsize:
                    targets.add(target)
        assert targets <= expected, (
            f"unexpected call targets: {sorted(hex(t) for t in targets - expected)}"
        )
        assert expected <= targets, f"never called: {expected - targets}"

    def test_no_branch_leaves_the_cave(self, image: bytearray) -> None:
        CaptureTheFlagPatch().apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        base_va, _off, vsize = located
        for insn in self._instructions(image):
            if insn.mnemonic.startswith("j") and insn.op_str.startswith("0x"):
                target = int(insn.op_str, 16)
                assert base_va <= target < base_va + vsize, f"{insn.address:#x} jumps out"

    def test_the_update_restores_its_own_stack(self, image: bytearray) -> None:
        """`iterateObjectsInRange` is cdecl and does not clean its arguments, so the epilogue has
        to recover esp from ebp. Popping the saved registers off a leaked stack would return into
        nothing."""
        CaptureTheFlagPatch().apply(image)
        text = [f"{i.mnemonic} {i.op_str}" for i in self._instructions(image)]
        assert "lea esp, [ebp - 0xfc]" in text
        assert text.index("lea esp, [ebp - 0xfc]") < text.index("pop edi")

    def test_the_share_test_is_an_integer_cross_multiply(self, image: bytearray) -> None:
        """No division and no float: two peers must agree on the comparison exactly."""
        CaptureTheFlagPatch().apply(image)
        text = [f"{i.mnemonic} {i.op_str}" for i in self._instructions(image)]
        assert "imul eax, eax, 0x64" in text
        assert "imul edx, ecx" in text
        assert not any(t.startswith(("div", "idiv", "fdiv")) for t in text)

    def test_the_instance_constructor_keeps_the_stock_signature(self, image: bytearray) -> None:
        """The shim stands in for a `__thiscall` taking two arguments, so it must clean them."""
        CaptureTheFlagPatch().apply(image)
        text = [f"{i.mnemonic} {i.op_str}" for i in self._instructions(image)]
        assert "ret 8" in text

    def test_the_player_index_is_bounds_checked(self, image: bytearray) -> None:
        """Twenty buckets on the stack. An unchecked index writes through the frame."""
        CaptureTheFlagPatch().apply(image)
        text = [f"{i.mnemonic} {i.op_str}" for i in self._instructions(image)]
        assert "cmp ecx, 0x14" in text
        assert any(t.startswith("jae") for t in text)


class TestIniSurface:
    def test_the_block_and_its_keywords_are_declared(self) -> None:
        engine = CaptureTheFlagPatch().ini_surface()
        try:
            assert engine.apply() == []
            block = REGISTRY.get(DEFAULT_BLOCK)
            assert block is not None
            for keyword, _parse, _offset, _type in FIELDS:
                assert keyword in block._fieldspec
        finally:
            STOCK.apply()

    def test_the_adopted_module_stops_existing(self) -> None:
        engine = CaptureTheFlagPatch().ini_surface()
        try:
            engine.apply()
            assert "AutoFindHealingUpdate" not in REGISTRY
        finally:
            STOCK.apply()
        assert "AutoFindHealingUpdate" in REGISTRY, "reverting must put the stock block back"

    def test_a_custom_block_name_reaches_the_model(self) -> None:
        engine = CaptureTheFlagPatch(block_name="HoldTheLineUpdate").ini_surface()
        try:
            assert engine.apply() == []
            assert "HoldTheLineUpdate" in REGISTRY
            assert DEFAULT_BLOCK not in REGISTRY
        finally:
            STOCK.apply()


class TestModelConditions:
    """The conditions are chosen to match the flag's *art*, and the first build got this wrong.

    `CAPTURING` is a real entry in the engine's name table, so setting it looks right and reads
    back right - but the stock `CaptureFlag`'s draw defines no `AnimationState = CAPTURING`, and a
    condition no state names selects nothing. The flag stayed down and the `OnStateEnter` Lua that
    raises it never ran. Nothing but a test pinning the three animated conditions catches that
    coming back.
    """

    #: The three `AnimationState`s the stock `Object CaptureFlag` declares, and their indices in
    #: the engine's model-condition name table.
    ANIMATED = {"START_CAPTURE": 110, "CANCEL_CAPTURE": 111, "CAPTURED": 119}

    def test_the_bits_set_are_the_ones_the_art_animates(self) -> None:
        assert ctf._BIT_START_CAPTURE == 1 << (self.ANIMATED["START_CAPTURE"] - 96)
        assert ctf._BIT_CANCEL_CAPTURE == 1 << (self.ANIMATED["CANCEL_CAPTURE"] - 96)
        assert ctf._BIT_CAPTURED == 1 << (self.ANIMATED["CAPTURED"] - 96)

    def test_capturing_is_cleared_but_never_set(self, image: bytearray) -> None:
        capstone = pytest.importorskip("capstone")
        CaptureTheFlagPatch().apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        base_va, off, _vsize = located
        code_bytes = CaptureTheFlagPatch()._layout(base_va).table_va - base_va
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        loaded = {
            insn.op_str.split(", ")[1]
            for insn in md.disasm(bytes(image[off : off + code_bytes]), base_va)
            if insn.mnemonic == "mov" and insn.op_str.startswith("edx, 0x")
        }
        assert hex(ctf._BIT_CAPTURING) not in loaded, "CAPTURING has no AnimationState to select"
        assert {hex(ctf._BIT_START_CAPTURE), hex(ctf._BIT_CANCEL_CAPTURE)} <= loaded
        assert hex(ctf._BIT_CAPTURED) in loaded
        # ...but it is still cleared, so a binary carrying an older build comes out consistent.
        assert not ctf._BIT_CLEAR_MASK & ctf._BIT_CAPTURING

    def test_all_four_bits_live_in_the_dword_the_patch_writes(self) -> None:
        for index in (*self.ANIMATED.values(), 112):
            assert 0x10C + (index // 32) * 4 == ctf._MODEL_CONDITION_DWORD


class TestFrameLayout:
    """No scalar local may land inside one of the two per-player arrays.

    This is the bug that got furthest: `counts[]` is based at `[ebp-0x90]` and twenty dwords
    reach `[ebp-0x44]`, so `-0x44`, `-0x48` and `-0x4C` are `counts[19]`, `counts[18]` and
    `counts[17]`. Three scalars added later sat exactly there, and storing a `Player*` into one
    of them made the tally elect a contender of 18 with no team behind it - the bar filled,
    `CAPTURED` was applied, and the ownership flip was skipped in silence.

    Nothing else in this suite could see it: the encodings were right, every branch resolved,
    every call landed on a named entry point, and the patch verified. It took reading the
    module's own state out of a live match (`progress = 100, claimant = 18`) to find it. So the
    invariant is asserted directly on the emitted code.
    """

    #: `(base displacement, entries)` for the two arrays the update routine indexes by player.
    ARRAYS = ((0x90, 20), (0xE0, 20))

    def _scalar_displacements(self, image: bytearray) -> list[tuple[int, int, str]]:
        capstone = pytest.importorskip("capstone")
        CaptureTheFlagPatch().apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        base_va, off, _vsize = located
        end = CaptureTheFlagPatch()._layout(base_va).table_va - base_va
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        out = []
        for insn in md.disasm(bytes(image[off : off + end]), base_va):
            text = insn.op_str
            # Indexed forms (`ebp + ecx*4 - 0x90`) are the arrays themselves, and a bare `lea`
            # of a base is taking an array's address (the zeroing does exactly that) - neither is
            # a scalar access, which is what this invariant is about.
            if insn.mnemonic == "lea":
                continue
            if "ebp - " in text and "*4" not in text:
                disp = int(text.split("ebp - ")[1].split("]")[0], 16)
                out.append((insn.address, disp, f"{insn.mnemonic} {text}"))
        return out

    def test_no_scalar_local_lands_inside_a_player_array(self, image: bytearray) -> None:
        collisions = []
        for address, disp, text in self._scalar_displacements(image):
            for array_base, entries in self.ARRAYS:
                if array_base - (entries - 1) * 4 <= disp <= array_base:
                    collisions.append(
                        f"{address:#x} {text} is inside the array at -{array_base:#x}"
                    )
        assert not collisions, "scalar locals overlapping a per-player array: " + "; ".join(
            collisions
        )

    def test_the_arrays_are_zeroed_before_the_scan(self, image: bytearray) -> None:
        """One `rep stosd` covers both arrays and neither scalar block."""
        capstone = pytest.importorskip("capstone")
        CaptureTheFlagPatch().apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        base_va, off, _vsize = located
        end = CaptureTheFlagPatch()._layout(base_va).table_va - base_va
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        text = [
            f"{i.mnemonic} {i.op_str}" for i in md.disasm(bytes(image[off : off + end]), base_va)
        ]
        assert any(t.startswith("rep stosd") for t in text)
        assert "mov ecx, 0x28" in text, "the zeroing count must cover both twenty-entry arrays"
        assert "lea edi, [ebp - 0xe0]" in text, "zeroing must start at the lower array"


class TestLinkedFlagPropagation:
    """Capturing a flag has to move the structures the flag speaks for.

    A `ShipWright` carries `KINDOF_LINKED_TO_FLAG` and **not** `CAPTURABLE`, so a flag is its
    only route to changing hands - and the map that surfaced this has no ownership-transfer
    script at all, so nothing else will do it. A capture that moves only the flag leaves the
    thing the flag exists for sitting neutral, which is what shipped first.
    """

    def _text(self, image: bytearray) -> list[str]:
        capstone = pytest.importorskip("capstone")
        CaptureTheFlagPatch().apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        base_va, off, _vsize = located
        end = CaptureTheFlagPatch()._layout(base_va).table_va - base_va
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        return [
            f"{i.mnemonic} {i.op_str}" for i in md.disasm(bytes(image[off : off + end]), base_va)
        ]

    def test_the_kindof_bit_is_the_one_the_engine_names(self) -> None:
        """Bit 50 of the template mask at +0x108, so byte +0x10E mask 0x04 - checked against the
        engine's own KindOf name table rather than a hardcoded list."""
        data = capture_the_flag_image()
        try:
            table = read_kindof_table(data)
            names = [read_cstring(data, p) for p in table.pointers]
            bit = names.index("LINKED_TO_FLAG")
        except (ValueError, IndexError):
            pytest.skip("the synthetic image carries no KindOf name table")
        assert 0x108 + bit // 8 == ctf._KINDOF_BYTE
        assert 1 << (bit % 8) == ctf._LINKED_TO_FLAG

    def test_the_linked_kindof_is_tested(self, image: bytearray) -> None:
        text = self._text(image)
        assert "test byte ptr [esi + 4], 4" not in text, "must test the template, not the object"
        assert f"test byte ptr [eax + {ctf._KINDOF_BYTE:#x}], {ctf._LINKED_TO_FLAG}" in text

    def test_set_team_is_called_for_the_flag_and_for_linked_objects(self, image: bytearray) -> None:
        text = self._text(image)
        assert text.count(f"call {ctf._SET_TEAM:#x}") == 2, (
            "one call flips the flag, the second flips each LINKED_TO_FLAG structure"
        )

    def test_the_propagation_scan_is_a_complete_iteration(self, image: bytearray) -> None:
        """Its own iterate/next/release - a leaked iterator would outlive the frame."""
        text = self._text(image)
        assert text.count(f"call {ctf._ITERATE_IN_RANGE:#x}") == 2
        assert text.count(f"call {ctf._ITER_RELEASE:#x}") == 2
        assert text.count(f"call {ctf._ITER_NEXT:#x}") == 2

    def test_the_new_team_survives_the_first_set_team(self, image: bytearray) -> None:
        """`setTeam` clobbers edx, so the team is parked in the frame before the flag is flipped
        and reloaded per linked object."""
        text = self._text(image)
        assert "mov dword ptr [ebp - 0xf0], edx" in text
        assert "mov edx, dword ptr [ebp - 0xf0]" in text
        assert text.index("mov dword ptr [ebp - 0xf0], edx") < text.index(
            f"call {ctf._SET_TEAM:#x}"
        )


class TestSetTeamNotifies:
    """`setTeam`'s second argument must be 0, and this is invisible to every other check.

    At `0x00697DB8` the routine reads `cmp byte [ebp+0xC], 0 / jne` around its call to
    `Object::onCapture` (`0x00696F0A`), which walks the module array and calls vslot `+0x24` on
    every module with the old and new player. Non-zero skips all of it. The team still moves - so
    ownership changes, the minimap updates, and the patch looks correct - but no module is ever
    told, and a captured structure never re-runs `CommandSetUpgrade`. A shipyard changes hands
    and keeps its neutral command set.

    An early build copied the 1 from `0x0069831E`, which is savegame restore, where suppressing
    the notification is right because the modules are being rebuilt from a snapshot.
    """

    def test_both_set_team_calls_pass_zero(self, image: bytearray) -> None:
        capstone = pytest.importorskip("capstone")
        CaptureTheFlagPatch().apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        base_va, off, _vsize = located
        end = CaptureTheFlagPatch()._layout(base_va).table_va - base_va
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        insns = list(md.disasm(bytes(image[off : off + end]), base_va))

        sites = [
            i
            for i, x in enumerate(insns)
            if x.mnemonic == "call" and x.op_str == hex(ctf._SET_TEAM)
        ]
        assert len(sites) == 2, "the flag and the LINKED_TO_FLAG sweep"
        for i in sites:
            window = [f"{x.mnemonic} {x.op_str}" for x in insns[i - 3 : i]]
            assert "push 0" in window, f"setTeam at {insns[i].address:#x} suppresses onCapture"
            assert "push 1" not in window, (
                f"setTeam at {insns[i].address:#x} passes 1 - that is the savegame-restore "
                "convention and skips Object::onCapture entirely"
            )


class TestCapturingObjectIsPublished:
    """`Object+0x80` has to carry the capturer while the bar is filling.

    It is what `ObjectCapturingObjectPlayerSide` reads, and the flag's art asks for it by name:
    `START_CAPTURE` carries `LuaEvent = OnStateEnter`, and the script it fires raises the
    *capturing* player's banner. That is what makes a stock capture look like a flag going up
    over the capture's duration. Leave the field unset and the script falls back to the flag's
    own side - mid-capture that is still the old owner - so the pole rises bare and the new
    banner appears already raised at the end.

    Nothing in the stock image writes this field, so on a flag the module is its only source.
    """

    def _text(self, image: bytearray) -> list[str]:
        capstone = pytest.importorskip("capstone")
        CaptureTheFlagPatch().apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        base_va, off, _vsize = located
        end = CaptureTheFlagPatch()._layout(base_va).table_va - base_va
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        return [
            f"{i.mnemonic} {i.op_str}" for i in md.disasm(bytes(image[off : off + end]), base_va)
        ]

    def test_the_capturing_id_is_written_while_the_bar_rises(self, image: bytearray) -> None:
        text = self._text(image)
        assert f"mov dword ptr [ecx + {ctf._OBJ_CAPTURING_ID:#x}], eax" in text
        assert f"mov eax, dword ptr [eax + {ctf._OBJ_ID:#x}]" in text, (
            "the value published must be the representative's ObjectID, not its address"
        )

    def test_it_is_cleared_when_the_claim_is_lost(self, image: bytearray) -> None:
        assert f"and dword ptr [ecx + {ctf._OBJ_CAPTURING_ID:#x}], 0" in self._text(image)

    def test_the_array_holds_objects_so_both_id_and_team_are_reachable(
        self, image: bytearray
    ) -> None:
        """One array of representative objects, not of teams: the team is `+0x31C` away and the
        id is `+0x74` away, and the capture path needs both."""
        text = self._text(image)
        assert "mov dword ptr [ebp + ecx*4 - 0xe0], esi" in text, "store the object itself"
        assert f"mov edx, dword ptr [edx + {ctf._OBJ_TEAM:#x}]" in text, "deref it for the team"


class TestDecayWhenUnheld:
    """No contender means the ground is not held, and the bar gives it back.

    The first design froze on a halt, which left a flag stuck at 90% forever after the units
    that raised it wandered off. Falling instead means the art plays `CANCEL_CAPTURE` - the state
    whose animation lowers the banner - and at zero the flag reads exactly as it started.

    All three ways to have no contender route here: an empty radius, a tie, and a leader short
    of `CaptureShare`.
    """

    def _text(self, image: bytearray) -> list[str]:
        capstone = pytest.importorskip("capstone")
        CaptureTheFlagPatch().apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        base_va, off, _vsize = located
        end = CaptureTheFlagPatch()._layout(base_va).table_va - base_va
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        return [
            f"{i.mnemonic} {i.op_str}" for i in md.disasm(bytes(image[off : off + end]), base_va)
        ]

    def test_the_bar_falls_when_nobody_holds_the_share(self, image: bytearray) -> None:
        text = self._text(image)
        # Two `sub [esi+0x14], eax`: one for a rival taking the claim, one for decay.
        assert text.count("sub dword ptr [esi + 0x14], eax") == 2, (
            "decay must subtract TickAmount the same way a contested fall does"
        )

    def test_reaching_zero_clears_the_claim_and_the_capturer(self, image: bytearray) -> None:
        text = self._text(image)
        assert "or dword ptr [esi + 0x18], 0xffffffff" in text, "claimant back to nobody"
        assert f"and dword ptr [ecx + {ctf._OBJ_CAPTURING_ID:#x}], 0" in text

    def test_decay_flies_the_losing_flag_so_the_art_lowers_the_banner(
        self, image: bytearray
    ) -> None:
        """Three `mov [ebp-0xEC], N`: zeroed per tick, set on a contested fall, set on decay."""
        text = self._text(image)
        assert text.count("mov dword ptr [ebp - 0xec], 1") == 2
        assert text.count("mov dword ptr [ebp - 0xec], 0") == 1


class TestLinkedObjectsAreMarkedCaptured:
    """A stock capture sets `CAPTURED` on the linked structure; this must too.

    Measured across two stock right-click captures in a live match: the `ShipWright`'s `+0x118`
    gained `0x00800000` both times, while the same structure taken by this module came out with
    the bit clear. It was the only non-pointer difference between the two, and the engine ships a
    `MonitorConditionUpdate` whose entire job is swapping a command set on a model condition - so
    an unmarked structure is one nothing downstream believes has been captured.
    """

    def test_the_linked_sweep_sets_captured_and_propagates(self, image: bytearray) -> None:
        capstone = pytest.importorskip("capstone")
        CaptureTheFlagPatch().apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        base_va, off, _vsize = located
        end = CaptureTheFlagPatch()._layout(base_va).table_va - base_va
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        text = [
            f"{i.mnemonic} {i.op_str}" for i in md.disasm(bytes(image[off : off + end]), base_va)
        ]

        assert f"or eax, {ctf._BIT_CAPTURED:#x}" in text
        assert f"mov dword ptr [esi + {ctf._MODEL_CONDITION_DWORD:#x}], eax" in text, (
            "the linked object's own conditions, addressed through esi"
        )
        assert text.count(f"call {ctf._PROPAGATE_MODEL_CONDITIONS:#x}") == 2, (
            "once for the flag's own conditions, once per linked structure"
        )


class TestCommandSetReregistration:
    """A captured structure has to be re-filed under its new owner.

    `CommandSetUpgrade` does not put its override on the object - it registers it into the
    controlling *player*, keyed by the object's id. An object that changes hands therefore leaves
    its entry with the old owner and falls back to its template default, which is a shipyard that
    changed hands and kept the neutral command set.

    The trap is the subobject offset. The class's constructor writes its interface vtable to
    `module+0x10`, and the registration is slot `+0x20` of *that* vtable - while every generic
    module-array walk in the engine (`Object::onCapture`, the upgrade refresh at `0x006902FA`)
    dispatches through the vtable at `module+0`. A build that called `0x006902FA` reached an
    unrelated slot and changed nothing, which is exactly how it behaved in play.
    """

    def _text(self, image: bytearray) -> list[str]:
        capstone = pytest.importorskip("capstone")
        CaptureTheFlagPatch().apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        base_va, off, _vsize = located
        end = CaptureTheFlagPatch()._layout(base_va).table_va - base_va
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        return [
            f"{i.mnemonic} {i.op_str}" for i in md.disasm(bytes(image[off : off + end]), base_va)
        ]

    def test_it_dispatches_through_the_plus_0x10_subobject(self, image: bytearray) -> None:
        text = self._text(image)
        assert "lea ecx, [esi + 0x10]" in text, (
            "the registration lives on the interface at module+0x10, not on the module itself"
        )
        assert f"call {ctf._REGISTER_COMMAND_SET:#x}" in text

    def test_the_module_is_identified_by_vtable_not_assumed(self, image: bytearray) -> None:
        assert f"cmp dword ptr [esi + 0x10], {ctf._COMMAND_SET_UPGRADE_VTABLE:#x}" in self._text(
            image
        )

    def test_the_ineffective_generic_walker_is_not_called(self, image: bytearray) -> None:
        """`0x006902FA` walks `module+0`, so it cannot reach this. Calling it was a wrong fix."""
        assert f"call {ctf._REFRESH_UPGRADES:#x}" not in self._text(image)

    def test_both_the_flag_and_linked_structures_are_re_filed(self, image: bytearray) -> None:
        capstone = pytest.importorskip("capstone")
        CaptureTheFlagPatch().apply(image)
        located = find_section(image, SECTION_NAME)
        assert located is not None
        base_va, off, _vsize = located
        patch = CaptureTheFlagPatch()
        end = patch._layout(base_va).table_va - base_va
        target = hex(patch._asm(base_va).label_va("command_sets"))
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        calls = [
            i
            for i in md.disasm(bytes(image[off : off + end]), base_va)
            if i.mnemonic == "call" and i.op_str == target
        ]
        assert len(calls) == 2, "once for the flag, once per linked structure"
