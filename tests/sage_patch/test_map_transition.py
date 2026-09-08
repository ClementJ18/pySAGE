"""Tests for `map-transition`, which swaps the running session onto another map from a script.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter disassemble
it back and assert it says what it was meant to say. Four things can go wrong and none of them
raises on its own.

The first is the **calling conventions of the three engine calls the hook makes**, which are not
uniform. `AsciiString::format` is cdecl and the cave must clean its four arguments; `startNewGame`
and `loadMap` are `__thiscall` and clean their own. Getting either wrong unbalances the stack
inside a hook that runs every logic frame, so the failure is a crash somewhere else entirely.

The second is **register preservation**. The hook takes `GameLogic::update`'s entry, where `ecx`
carries `this` and the prologue has not run. The block is bracketed by `pushad`/`popad`, and
without them a transition would corrupt the update that follows it rather than the transition
itself.

The third is the **string copy**, which is the only loop in the patch. It has to terminate on both
edges - the null it finds, and the bound it does not - and leave the buffer terminated either way.

The fourth is the **build fingerprint**. The patch rewrites two sites and reads two more it does
not rewrite; every one of them has to fail loudly on anything else, and in particular the action id
it claims has to still be a stub rather than something the engine implements.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch import addresses as ad
from sage_patch.patches.experimental.map_transition import (
    ACTION_ID,
    ANCHORS,
    CODE_OFF,
    HOOK_ORIGINAL,
    HOOK_RETURN_VA,
    HOOK_VA,
    MAX_OBJECTS,
    MAX_SCIENCES,
    NAME_MAX,
    NAME_OFF,
    PENDING_OFF,
    PLAYER_STATE_OFF,
    PLAYER_STATE_UPGRADE_MASK,
    PLAYER_STATE_UPGRADE_SCRATCH,
    PLAYER_STATE_VALID,
    RECORD_ANGLE_OFF,
    RECORD_POSITION_OFF,
    SAVED_MODE_OFF,
    SCRIPT_NAME_MAX,
    SECTION_NAME,
    SLOT_SIZE,
    TABLE_SLOT_STOCK,
    TABLE_SLOT_VA,
    MapTransitionPatch,
    _emit,
    entry_points,
)
from sage_patch.utils import find_section, va_to_offset

from .synthetic import map_transition_image


def _applied() -> tuple[bytearray, int, int, int]:
    """An image with the patch applied, plus the section VA and both entry points."""
    data = map_transition_image()
    MapTransitionPatch().apply(data)
    located = find_section(data, SECTION_NAME)
    assert located is not None
    section_va, _, _ = located
    action_va, hook_va = entry_points(section_va)
    return data, section_va, action_va, hook_va


def _saved_mode_va(data: bytes) -> int:
    located = find_section(data, SECTION_NAME)
    assert located is not None
    return located[0] + SAVED_MODE_OFF


def _label(data: bytes, name: str) -> int:
    """The address a named routine landed at, for asserting one call site names another."""
    located = find_section(data, SECTION_NAME)
    assert located is not None
    a = _emit(located[0])
    a.finish()
    return a.label_va(name)


def _disassemble(data: bytes, va: int, count: int) -> list:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    off = va_to_offset(data, va)
    assert off is not None
    return list(md.disasm(bytes(data[off : off + 0x200]), va))[:count]


class TestTheSitesItClaims:
    def test_the_action_id_is_a_stub_in_the_stock_image(self):
        """The whole design rests on this slot dispatching to the shared do-nothing epilogue."""
        assert TABLE_SLOT_STOCK == struct.pack("<I", ad.SCRIPT_ACTION_EPILOGUE)
        assert TABLE_SLOT_VA == ad.SCRIPT_ACTION_JUMP_TABLE + ACTION_ID * 4

    def test_apply_repoints_the_slot_at_the_action_entry(self):
        data, section_va, action_va, _ = _applied()
        off = va_to_offset(data, TABLE_SLOT_VA)
        assert off is not None
        assert struct.unpack_from("<I", data, off)[0] == action_va
        # The action lives in the code region, after the data block. Its exact offset moves as
        # the cave's other routines change, so this checks the region rather than a constant.
        assert action_va >= section_va + CODE_OFF

    def test_apply_installs_a_jump_to_the_hook_entry(self):
        data, _, _, hook_va = _applied()
        off = va_to_offset(data, HOOK_VA)
        assert off is not None
        assert data[off] == 0xE9
        assert HOOK_VA + 5 + struct.unpack_from("<i", data, off + 1)[0] == hook_va

    def test_it_refuses_an_image_whose_vtable_does_not_name_the_hooked_function(self):
        data = map_transition_image()
        off = va_to_offset(data, ad.GAME_LOGIC_UPDATE_VTABLE_SLOT)
        assert off is not None
        struct.pack_into("<I", data, off, HOOK_VA + 0x10)
        with pytest.raises(ValueError, match="would never fire"):
            MapTransitionPatch().apply(data)

    def test_it_refuses_an_image_whose_action_slot_is_not_the_stub(self):
        """A slot already claimed - by the engine or by another patch - must not be overwritten."""
        data = map_transition_image()
        off = va_to_offset(data, TABLE_SLOT_VA)
        assert off is not None
        struct.pack_into("<I", data, off, 0x00401000)
        with pytest.raises(ValueError, match="expected 46f87c00"):
            MapTransitionPatch().apply(data)

    @pytest.mark.parametrize("va", sorted(ANCHORS))
    def test_it_refuses_an_image_whose_anchors_moved(self, va):
        data = map_transition_image()
        off = va_to_offset(data, va)
        assert off is not None
        data[off] ^= 0xFF
        with pytest.raises(ValueError):
            MapTransitionPatch().apply(data)

    def test_applying_twice_raises_rather_than_double_patching(self):
        data, _, _, _ = _applied()
        with pytest.raises(ValueError, match="expected"):
            MapTransitionPatch().apply(data)


class TestTheActionRoutine:
    def test_it_reads_the_string_parameter_and_leaves_through_the_epilogue(self):
        data, _, action_va, _ = _applied()
        text = [f"{i.mnemonic} {i.op_str}".strip() for i in _disassemble(data, action_va, 24)]
        # Parameter 1's AsciiString, via the inline form every live case body uses.
        assert text[0] == f"cmp dword ptr [esi + {ad.SCRIPT_ACTION_PARAM_COUNT}], 2"
        assert f"mov eax, dword ptr [esi + {hex(ad.SCRIPT_ACTION_PARAM_ARRAY + 4)}]" in text
        assert f"mov eax, dword ptr [eax + {hex(ad.SCRIPT_PARAMETER_STRING)}]" in text
        # Every exit is the shared epilogue: a case body that returns any other way unbalances
        # the dispatcher's SEH frame.
        assert any(
            i.mnemonic == "jmp" and i.op_str == hex(ad.SCRIPT_ACTION_EPILOGUE)
            for i in _disassemble(data, action_va, 40)
        )

    def test_the_copy_is_balanced_and_bounded(self):
        data, section_va, action_va, _ = _applied()
        instructions = _disassemble(data, action_va, 40)
        text = [f"{i.mnemonic} {i.op_str}".strip() for i in instructions]
        # `esi` is the dispatcher's, borrowed for the copy and given back before the epilogue
        # pops it. One push, one pop.
        assert text.count("push esi") == 1
        assert text.count("pop esi") == 1
        # The bound is the buffer's last index, so the terminator written when the loop runs out
        # still lands inside it.
        assert f"cmp ecx, {hex(NAME_MAX - 1)}" in text
        assert "mov byte ptr [edx + ecx], 0" in text
        # It copies into the section's own buffer, not anywhere else.
        assert f"mov edx, {hex(section_va + NAME_OFF)}" in text

    def test_it_refuses_an_empty_name_before_arming(self):
        """An empty name formats to a path that cannot load, with the session already torn down."""
        data, section_va, action_va, _ = _applied()
        text = [f"{i.mnemonic} {i.op_str}".strip() for i in _disassemble(data, action_va, 40)]
        guard = text.index(f"cmp byte ptr [{hex(section_va + NAME_OFF)}], 0")
        arm = text.index(f"mov dword ptr [{hex(section_va + PENDING_OFF)}], 1")
        assert guard < arm


class TestTheHookRoutine:
    """The state machine.

    Four states, because the engine will only do this in steps it already supports: end the match,
    leave the lobby for the shell map, start the destination from the shell, then put the army
    back. Each edge waits for a mode the engine reaches on its own rather than forcing it.
    """

    def test_it_preserves_every_register_across_the_work(self):
        data, _, _, hook_va = _applied()
        text = [f"{i.mnemonic} {i.op_str}".strip() for i in _disassemble(data, hook_va, 80)]
        assert text.count("pushal") == 1
        assert text.count("popal") == 1
        assert text.index("pushal") < text.index("popal")

    def test_it_never_calls_the_swap_itself(self):
        """Calling `startNewGame`/`loadMap` directly builds a world over a live session."""
        data, _, _, hook_va = _applied()
        text = [f"{i.mnemonic} {i.op_str}".strip() for i in _disassemble(data, hook_va, 80)]
        assert f"call {hex(ad.GAME_LOGIC_START_NEW_GAME)}" not in text
        assert f"call {hex(ad.GAME_LOGIC_LOAD_MAP)}" not in text
        assert f"call dword ptr [eax + {hex(ad.APPEND_MESSAGE_VTABLE_SLOT)}]" in text

    def test_step_one_ends_the_match_and_stops(self):
        data, section_va, _, hook_va = _applied()
        text = [f"{i.mnemonic} {i.op_str}".strip() for i in _disassemble(data, hook_va, 80)]
        mode = text.index("mov edx, dword ptr [ecx + 0x110]")
        clear = text.index(f"call {hex(ad.CLEAR_GAME_DATA)}")
        assert mode < clear, "the mode is captured before a teardown that may change it"
        assert text[mode + 1] == f"mov dword ptr [{hex(section_va + SAVED_MODE_OFF)}], edx"
        assert text[mode + 2] == f"mov dword ptr [{hex(section_va + PENDING_OFF)}], 2"
        assert text[clear - 2] == "push 1"
        assert text[clear + 1].startswith("jmp"), "step one must not post anything itself"

    def test_the_lobby_is_routed_through_the_shell_map(self):
        """Measured: a `MSG_NEW_GAME` posted from mode 9 is not acted on.

        The mode stayed 9, the staged name was never promoted and the active map never changed.
        Mode 4 is the state the engine's own shell-to-game start works from, so the lobby asks for
        the shell map and comes back rather than trying to start the destination from there.
        """
        data, _, _, hook_va = _applied()
        text = [f"{i.mnemonic} {i.op_str}".strip() for i in _disassemble(data, hook_va, 80)]
        assert "cmp eax, 4" in text and "cmp eax, 9" in text
        # From the lobby it stages the shell map and posts the shell's own mode.
        copy = text.index(f"call {hex(ad.ASCII_STRING_COPY)}")
        assert text[copy - 5] == f"mov eax, dword ptr [{hex(ad.GLOBAL_DATA)}]"
        assert text[copy - 4] == f"lea edx, [eax + {hex(ad.GLOBAL_DATA_SHELL_MAP)}]"
        assert text[copy - 3] == "push edx"
        assert text[copy - 2] == f"add eax, {hex(ad.GLOBAL_DATA_STAGED_MAP)}"
        assert text[copy + 1] == "push 4"

    def test_the_shell_hop_gives_the_game_info_back(self):
        """`loadMap` nulls `TheGameInfo` for game mode 4 alone (`0x0063152D`), so the shell hop
        takes it away and the destination then loads without one - `LoadScreen::init` returns on a
        null `GameInfo` and leaves its progress window null for the next tick to dereference."""
        data, _, _, hook_va = _applied()
        text = [f"{i.mnemonic} {i.op_str}".strip() for i in _disassemble(data, hook_va, 90)]
        read = text.index(f"mov eax, dword ptr [{hex(ad.THE_SKIRMISH_GAME_INFO)}]")
        assert text[read + 1] == "test eax, eax", "a null skirmish info is a destroyed one"
        assert text[read + 2].startswith("je ")
        assert text[read + 3] == f"mov dword ptr [{hex(ad.THE_GAME_INFO)}], eax"
        # After the shell map's own load, and before the destination's mode is posted.
        assert text.index(f"call {hex(ad.FILE_SYSTEM_DOES_FILE_EXIST)}") < read
        assert read < text.index(f"push dword ptr [{hex(_saved_mode_va(data))}]")

    def test_the_shell_map_is_torn_down_before_the_destination_is_asked_for(self):
        """Without it the destination loads on the logic side and the render scene keeps the shell
        map: its scenery still standing, the destination's terrain nowhere, units on black."""
        data, _, _, hook_va = _applied()
        text = [f"{i.mnemonic} {i.op_str}".strip() for i in _disassemble(data, hook_va, 90)]
        teardowns = [i for i, t in enumerate(text) if t == f"call {hex(ad.CLEAR_GAME_DATA)}"]
        assert len(teardowns) == 2, "one to end the match, one to leave the shell map"
        shell = teardowns[1]
        assert text[shell - 2] == "push 0"
        # After the GameInfo is restored, and before the destination's mode is posted.
        assert text.index(f"mov dword ptr [{hex(ad.THE_GAME_INFO)}], eax") < shell
        assert shell < text.index(f"push dword ptr [{hex(_saved_mode_va(data))}]")

    def test_the_destination_is_staged_not_named_active(self):
        """`startNewGame` promotes the staged name and clears it, so an unserved request cannot
        leave a stale map name behind."""
        data, _, _, hook_va = _applied()
        text = [f"{i.mnemonic} {i.op_str}".strip() for i in _disassemble(data, hook_va, 80)]
        assert f"add eax, {hex(ad.GLOBAL_DATA_STAGED_MAP)}" in text
        assert f"add eax, {hex(ad.GLOBAL_DATA_ACTIVE_MAP)}" not in text

    def test_there_is_one_shared_post(self):
        data, _, _, hook_va = _applied()
        text = [f"{i.mnemonic} {i.op_str}".strip() for i in _disassemble(data, hook_va, 80)]
        assert text.count(f"push {hex(ad.MSG_NEW_GAME)}") == 1
        assert text.count(f"call {hex(ad.GAME_MESSAGE_APPEND_INTEGER)}") == 1
        # Two callers reach it: the shell request with a constant, the destination with the mode
        # step one saved.
        assert "push 4" in text
        assert f"push dword ptr [{hex(_saved_mode_va(data))}]" in text

    def test_the_mode_survives_the_vtable_call_on_the_stack(self):
        data, _, _, hook_va = _applied()
        text = [f"{i.mnemonic} {i.op_str}".strip() for i in _disassemble(data, hook_va, 80)]
        call = text.index(f"call dword ptr [eax + {hex(ad.APPEND_MESSAGE_VTABLE_SLOT)}]")
        assert text[call + 1] == "pop edx"
        assert text[call + 2] == "mov ecx, eax"
        assert text[call + 3] == "push edx"

    def test_it_cleans_up_after_the_cdecl_format(self):
        data, _, _, hook_va = _applied()
        text = [f"{i.mnemonic} {i.op_str}".strip() for i in _disassemble(data, hook_va, 80)]
        fmt = text.index(f"call {hex(ad.ASCII_STRING_FORMAT)}")
        assert text[fmt + 1] == "add esp, 0x10"

    def test_a_missing_destination_leaves_the_player_at_the_menu(self):
        data, _, _, hook_va = _applied()
        text = [f"{i.mnemonic} {i.op_str}".strip() for i in _disassemble(data, hook_va, 80)]
        exists = text.index(f"call {hex(ad.FILE_SYSTEM_DOES_FILE_EXIST)}")
        assert text[exists - 2 : exists] == ["add eax, 8", "push eax"]
        assert text.index(f"call {hex(ad.ASCII_STRING_FORMAT)}") < exists

    def test_it_disarms_before_doing_the_work(self):
        data, section_va, _, hook_va = _applied()
        text = [f"{i.mnemonic} {i.op_str}".strip() for i in _disassemble(data, hook_va, 80)]
        assert f"mov dword ptr [{hex(section_va + PENDING_OFF)}], 3" in text

    def test_the_passthrough_replays_the_stolen_prologue_and_returns(self):
        data, _, _, hook_va = _applied()
        instructions = _disassemble(data, hook_va, 80)
        back = next(
            index
            for index, ins in enumerate(instructions)
            if ins.mnemonic == "jmp" and ins.op_str == hex(HOOK_RETURN_VA)
        )
        assert bytes(instructions[back - 1].bytes) == HOOK_ORIGINAL


class TestTheCarryover:
    """The army snapshot and restore.

    The engine fills an `ArmyEntry` record from an object and rebuilds an object from one, so the
    patch marshals nothing itself - but the record carries no position, and the two calls run at
    opposite ends of a session teardown. Both of those are easy to get wrong silently.
    """

    @staticmethod
    def _routine(data, name, count=40):
        located = find_section(data, SECTION_NAME)
        assert located is not None
        a = _emit(located[0])
        a.finish()
        ins = _disassemble(data, a.label_va(name), count)
        return [f"{i.mnemonic} {i.op_str}".strip() for i in ins], ins

    def test_the_snapshot_runs_before_the_teardown(self):
        """`clearGameData` destroys the army, so the walk has to happen first."""
        data, _, _, hook_va = _applied()
        text = [f"{i.mnemonic} {i.op_str}".strip() for i in _disassemble(data, hook_va, 60)]
        located = find_section(data, SECTION_NAME)
        a = _emit(located[0])
        a.finish()
        snap = text.index(f"call {hex(a.label_va('snapshot'))}")
        assert snap < text.index(f"call {hex(ad.CLEAR_GAME_DATA)}")

    def test_only_army_summary_objects_are_carried(self):
        """War of the Ring's own rule for "what goes home with the player".

        `LIVING_WORLD_BATTLE_HARVEST` tests `KindOf = ARMY_SUMMARY` on the template and a skip bit
        on the object; both come before anything is written down. Structures fail the first, and
        so do horde *members* - which is the point, because their horde passes it and rebuilds
        them.
        """
        text, _ = self._routine(_applied()[0], "record_one")
        kind = text.index(f"test byte ptr [eax + {hex(ad.KINDOF_ARMY_SUMMARY_BYTE)}], 1")
        assert text[kind - 1] == f"mov eax, dword ptr [esi + {ad.OBJECT_THING_TEMPLATE}]"
        assert text[kind + 1].startswith("je "), "no ARMY_SUMMARY means not carried"
        excluded = text.index(f"test byte ptr [esi + {hex(ad.OBJECT_ARMY_EXCLUDED)}], 1")
        assert text[excluded + 1].startswith("jne "), "the skip bit disqualifies"
        # Both filters run before the record is constructed, as they do in the harvest.
        assert kind < text.index(f"call {hex(ad.ARMY_ENTRY_RECORD_CTOR)}")
        assert excluded < text.index(f"call {hex(ad.ARMY_ENTRY_RECORD_CTOR)}")

    def test_the_callback_is_cdecl_and_keeps_walking(self):
        text, ins = self._routine(data := _applied()[0], "record_one")
        assert text[-1] == "ret" or "ret" in text, "the callback must exist"
        # cdecl: a bare `ret`, never `ret 8` - the engine's walk cleans the arguments.
        rets = [t for t in text if t.startswith("ret")]
        assert rets and all(t == "ret" for t in rets), f"callback must be cdecl, got {rets}"
        assert "inc eax" in text, "it must return non-zero to continue the walk"

    def test_the_callback_is_bounded(self):
        text, _ = self._routine(_applied()[0], "record_one")
        assert f"cmp edi, {hex(MAX_OBJECTS)}" in text
        assert f"imul edi, edi, {hex(SLOT_SIZE)}" in text

    def test_position_and_angle_use_32_bit_displacements(self):
        """A regression guard.

        `RECORD_POSITION_OFF` is 0xD8, which does not fit a signed byte. Emitted as a disp8 it
        assembles cleanly and stores at `edi - 0x28`, corrupting the record instead of appending
        to it - silent, and invisible until a carried unit comes back wrong.
        """
        text, _ = self._routine(_applied()[0], "record_one")
        for step in range(3):
            assert f"mov dword ptr [edi + {hex(RECORD_POSITION_OFF + step * 4)}], eax" in text
        assert f"mov dword ptr [edi + {hex(RECORD_ANGLE_OFF)}], eax" in text
        assert not any("edi - " in t for t in text), (
            "a negative displacement means a disp8 slipped in"
        )

    def test_the_snapshot_records_through_the_engines_own_marshaller(self):
        text, _ = self._routine(_applied()[0], "record_one")
        assert f"call {hex(ad.ARMY_ENTRY_RECORD_CTOR)}" in text
        assert f"call {hex(ad.OBJECT_TO_ARMY_RECORD)}" in text
        assert text.index(f"call {hex(ad.ARMY_ENTRY_RECORD_CTOR)}") < text.index(
            f"call {hex(ad.OBJECT_TO_ARMY_RECORD)}"
        ), "the record must be constructed before it is filled"

    def test_restore_rebuilds_then_places(self):
        text, _ = self._routine(_applied()[0], "restore_loop")
        create = text.index(f"call {hex(ad.ARMY_RECORD_CREATE_OBJECT)}")
        assert text[create + 1] == "test eax, eax", "a failed create must not be placed"
        assert create < text.index(f"call {hex(ad.OBJECT_SET_POSITION)}")
        assert text.index(f"call {hex(ad.OBJECT_SET_POSITION)}") < text.index(
            f"call {hex(ad.OBJECT_SET_ORIENTATION)}"
        )

    def test_restore_waits_for_the_destination_to_be_running(self):
        data, section_va, _, hook_va = _applied()
        text = [f"{i.mnemonic} {i.op_str}".strip() for i in _disassemble(data, hook_va, 90)]
        assert f"cmp eax, dword ptr [{hex(section_va + SAVED_MODE_OFF)}]" in text


class TestTheScriptState:
    """Counters, timers and flags.

    Two `std::map`s whose node layout was read off a live engine rather than inferred: `+0x10` the
    scope `AsciiString`, `+0x14` the name, `STD_MAP_NODE_VALUE` the record. The tree is ordered by
    scope first and then name, which is the independent check on which field is which.
    """

    @staticmethod
    def _routine(data, name, count=60):
        located = find_section(data, SECTION_NAME)
        assert located is not None
        a = _emit(located[0])
        a.finish()
        ins = _disassemble(data, a.label_va(name), count)
        text = [f"{i.mnemonic} {i.op_str}".strip() for i in ins]
        return text[: text.index("ret") + 1]

    def test_both_maps_are_walked_with_the_engines_own_iterator(self):
        text = self._routine(_applied()[0], "script_snapshot")
        assert f"mov edi, dword ptr [eax + {hex(ad.SCRIPT_ENGINE_COUNTER_MAP)}]" in text
        assert f"mov edi, dword ptr [eax + {hex(ad.SCRIPT_ENGINE_FLAG_MAP)}]" in text
        walk = self._routine(_applied()[0], "script_walk")
        assert "mov esi, dword ptr [edi + 8]" in walk, "iteration starts at the leftmost node"
        assert "cmp esi, edi" in walk, "and stops when it comes back to the header"
        step = walk.index(f"call {hex(ad.STD_MAP_ITERATOR_INCREMENT)}")
        assert walk[step - 1] == "push esi"
        assert walk[step + 1] == "pop ecx", "the iterator is cdecl"

    def test_the_walk_keeps_its_header_across_the_per_node_call(self):
        """`script_record` needs `edi` for the slot and the caller is holding the header in it."""
        text = self._routine(_applied()[0], "script_record")
        assert text[0] == "push edi"
        assert text[-2:] == ["pop edi", "ret"]

    def test_the_name_is_scope_qualified_with_an_unconditional_separator(self):
        """`SCRIPT_KEY_COMPOSE` splits on the first `/` and only falls back to the engine's
        current scope when there is none, so always writing one keeps restore independent of
        whatever `SCRIPT_ENGINE_SCOPE` holds outside script evaluation."""
        text = self._routine(_applied()[0], "script_record")
        scope = text.index("mov edx, dword ptr [esi + 0x10]")
        name = text.index("mov edx, dword ptr [esi + 0x14]", scope)
        slash = text.index("mov byte ptr [edi + ecx], 0x2f")
        assert scope < slash < name, "scope, separator, then name"
        # The separator is not inside the branch that skips an empty scope.
        skip = next(i for i, t in enumerate(text[scope:], scope) if t.startswith("je "))
        assert int(text[skip].split()[-1], 16) <= _label(_applied()[0], "script_record_slash")

    def test_engine_internal_symbols_are_not_carried(self):
        """Three leading underscores is the engine's convention for script state the map did not
        author - all 20 of them in a live skirmish are `___MusicScript_`."""
        text = self._routine(_applied()[0], "script_record")
        underscores = [t for t in text if t.endswith("0x5f")]
        assert len(underscores) == 3
        assert underscores == [
            "cmp byte ptr [eax + 8], 0x5f",
            "cmp byte ptr [eax + 9], 0x5f",
            "cmp byte ptr [eax + 0xa], 0x5f",
        ]

    def test_a_counter_takes_the_dword_and_a_flag_the_byte(self):
        text = self._routine(_applied()[0], "script_record")
        assert f"mov eax, dword ptr [esi + {hex(ad.STD_MAP_NODE_VALUE)}]" in text
        assert f"movzx eax, byte ptr [esi + {hex(ad.STD_MAP_NODE_VALUE)}]" in text
        # A timer is a counter record with the flag set, so both bytes ride along with the value.
        timer = ad.STD_MAP_NODE_VALUE + ad.SCRIPT_COUNTER_IS_TIMER
        seconds = ad.STD_MAP_NODE_VALUE + ad.SCRIPT_COUNTER_IS_SECONDS
        assert f"mov al, byte ptr [esi + {hex(timer)}]" in text
        assert f"mov al, byte ptr [esi + {hex(seconds)}]" in text

    def test_the_name_copy_is_bounded(self):
        text = self._routine(_applied()[0], "script_append")
        assert f"cmp ecx, {hex(SCRIPT_NAME_MAX - 2)}" in text
        assert text[-1] == "ret"

    def test_restore_hands_the_string_over_by_value(self):
        """Both lookups take an `AsciiString` by value and destroy it themselves, so the string is
        built into the stack slot that is already the argument and their `ret 4` frees both."""
        text = self._routine(_applied()[0], "script_restore")
        sub = text.index("sub esp, 4")
        assert text[sub + 1] == "mov ecx, esp"
        assert text[sub + 2] == "push edi", "the name buffer is the slot's first field"
        assert text[sub + 3] == f"call {hex(ad.ASCII_STRING_CTOR)}"
        # No manual cleanup between the constructor and the lookup that consumes it.
        counter = text.index(f"call {hex(ad.SCRIPT_ENGINE_FIND_OR_CREATE_COUNTER)}")
        assert not any(t.startswith("add esp") for t in text[sub:counter])

    def test_restore_writes_the_record_the_lookup_returns(self):
        text = self._routine(_applied()[0], "script_restore")
        for call in (
            ad.SCRIPT_ENGINE_FIND_OR_CREATE_COUNTER,
            ad.SCRIPT_ENGINE_FIND_OR_CREATE_FLAG,
        ):
            at = text.index(f"call {hex(call)}")
            assert text[at + 1] == "test eax, eax"
            assert text[at + 2].startswith("je ")
        assert f"mov byte ptr [eax + {ad.SCRIPT_COUNTER_IS_TIMER}], dl" in text
        assert f"mov byte ptr [eax + {ad.SCRIPT_COUNTER_IS_SECONDS}], dl" in text
        assert "mov byte ptr [eax], dl" in text, "a flag is one byte"

    def test_it_is_snapshotted_before_the_teardown_and_restored_on_arrival(self):
        data, _, _, hook_va = _applied()
        text = [f"{i.mnemonic} {i.op_str}".strip() for i in _disassemble(data, hook_va, 90)]
        snap = text.index(f"call {hex(_label(data, 'script_snapshot'))}")
        assert snap < text.index(f"call {hex(ad.CLEAR_GAME_DATA)}")
        assert f"call {hex(_label(data, 'script_restore'))}" in text


class TestThePlayerState:
    """The purse, the command-point ceiling and the spellbook currency.

    Flat fields, so the risk is not logic but addressing: two of them do not fit a signed byte
    displacement, and the object record has already shown once what a silent disp8 does.
    """

    @staticmethod
    def _routine(data, name, count=90):
        located = find_section(data, SECTION_NAME)
        assert located is not None
        a = _emit(located[0])
        a.finish()
        ins = _disassemble(data, a.label_va(name), count)
        text = [f"{i.mnemonic} {i.op_str}".strip() for i in ins]
        return text[: text.index("ret") + 1], ins[: text.index("ret") + 1]

    def test_every_field_round_trips_through_the_same_slot(self):
        data = _applied()[0]
        located = find_section(data, SECTION_NAME)
        assert located is not None
        base = located[0] + PLAYER_STATE_OFF
        out, _ = self._routine(data, "player_snapshot")
        back, _ = self._routine(data, "player_restore")
        for player_off, slot_off in (
            (ad.PLAYER_RESOURCES, 0x04),
            (ad.PLAYER_COMMAND_POINTS_CAP, 0x08),
            (ad.PLAYER_COMMAND_POINTS_BONUS, 0x0C),
            (ad.PLAYER_COMMAND_POINTS_HARD_CAP, 0x10),
            (ad.PLAYER_POWER_POINTS, 0x14),
            (ad.PLAYER_POWER_POINTS_TOTAL, 0x18),
        ):
            read = out.index(f"mov ecx, dword ptr [eax + {hex(player_off)}]")
            assert out[read + 1] == f"mov dword ptr [{hex(base + slot_off)}], ecx"
            write = back.index(f"mov ecx, dword ptr [{hex(base + slot_off)}]")
            assert back[write + 1] == f"mov dword ptr [eax + {hex(player_off)}], ecx"

    def test_the_points_in_use_counter_is_not_carried(self):
        """`Player+0x68` is re-accrued as the carried objects are created, so restoring the number
        as well would count every carried unit twice."""
        out, _ = self._routine(_applied()[0], "player_snapshot")
        back, _ = self._routine(_applied()[0], "player_restore")
        used = hex(ad.PLAYER_COMMAND_POINTS_USED)
        assert not any(used in line for line in out + back)

    def test_every_field_uses_a_32_bit_displacement(self):
        """`Player+0x94` and `Player+0x14C` do not fit a signed byte; mixing forms in one block is
        how the object record grew a store at `[edi-0x28]` that assembled cleanly."""
        for name in ("player_snapshot", "player_restore"):
            _, ins = self._routine(_applied()[0], name)
            for i in ins:
                if i.mnemonic == "mov" and "[eax +" in i.op_str:
                    # ModRM's mod field: 0b10 is disp32, 0b01 is the disp8 form to stay out of.
                    assert i.bytes[1] >> 6 == 0b10, f"{i.mnemonic} {i.op_str} is not disp32"

    def test_nothing_is_written_back_unless_a_snapshot_ran(self):
        """An aborted transition must not zero the player's purse."""
        data = _applied()[0]
        located = find_section(data, SECTION_NAME)
        assert located is not None
        valid = hex(located[0] + PLAYER_STATE_OFF + PLAYER_STATE_VALID)
        out, _ = self._routine(data, "player_snapshot")
        assert out[0] == f"mov dword ptr [{valid}], 0", "cleared before the walk that fills it"
        assert out[-2] == f"mov dword ptr [{valid}], 1", "and set only once every field is stored"
        back, _ = self._routine(data, "player_restore")
        assert back[0] == f"cmp dword ptr [{valid}], 0"
        assert back[1].startswith("je ")

    def test_the_science_copy_is_bounded_and_reads_the_vector_as_begin_and_end(self):
        out, _ = self._routine(_applied()[0], "player_snapshot", count=60)
        begin = out.index(f"mov ecx, dword ptr [eax + {hex(ad.PLAYER_SCIENCES)}]")
        assert out[begin + 1] == "test ecx, ecx", "an unallocated vector is not walked"
        assert f"mov edx, dword ptr [eax + {hex(ad.PLAYER_SCIENCES + 4)}]" in out
        assert "sar edx, 2" in out, "the count is a pointer difference, not a stored length"
        assert f"cmp edx, {hex(MAX_SCIENCES)}" in out
        assert f"mov edx, {hex(MAX_SCIENCES)}" in out, "and is clamped rather than trusted"

    def test_the_sciences_go_back_as_one_assignment_over_a_stack_header(self):
        """`setSciences` reads only begin and end, so the argument is a three-word header built
        over the arena's own buffer - and it no-ops when the two are equal."""
        back, _ = self._routine(_applied()[0], "player_restore", count=80)
        call = back.index(f"call {hex(ad.PLAYER_SET_SCIENCES)}")
        assert back[call - 1] == "mov ecx, esi", "thiscall on the Player"
        assert back[call - 2] == "push edx"
        assert back[call - 3] == "mov edx, esp", "the header is the stack triple just pushed"
        assert back[call - 4 : call - 1] != ["push edx", "push edx", "push eax"]
        assert back[call + 1] == "add esp, 0xc", "the header is dropped; the callee took the arg"

    def test_upgrades_are_replayed_through_the_engine_not_written_back(self):
        """Writing the bitset would set every bit and run nothing. The engine's own restore turns
        the mask into a template, grants it, clears the bit and goes round."""
        back, _ = self._routine(_applied()[0], "player_restore", count=80)
        first = back.index(f"call {hex(ad.UPGRADE_FIRST_SET)}")
        assert back[first - 4] == f"mov ecx, dword ptr [{hex(ad.THE_UPGRADE_CENTER)}]"
        assert back[first - 3] == "test ecx, ecx", "a store that is not up yet grants nothing"
        grant = back.index(f"call {hex(ad.PLAYER_GRANT_UPGRADE)}")
        assert back[grant - 4 : grant] == ["push 0", "push 2", "push edi", "mov ecx, esi"]
        assert first < grant
        # Nothing writes the player's own bitset.
        assert not any(hex(ad.PLAYER_COMPLETED_UPGRADE_MASK) in line for line in back)

    def test_the_upgrade_loop_always_makes_progress(self):
        """The bit is cleared after the grant whatever the grant did, so a refused upgrade cannot
        spin the cave forever."""
        back, _ = self._routine(_applied()[0], "player_restore", count=80)
        grant = back.index(f"call {hex(ad.PLAYER_GRANT_UPGRADE)}")
        assert back[grant + 1] == f"mov ecx, dword ptr [edi + {hex(ad.UPGRADE_TEMPLATE_INDEX)}]"
        clear = next(i for i, x in enumerate(back[grant:], grant) if x.startswith("and dword"))
        assert back[clear + 1].startswith("jmp "), "and the loop closes right after"
        assert not any(x.startswith("j") for x in back[grant + 1 : clear])

    def test_restore_consumes_a_copy_so_the_snapshot_survives(self):
        data = _applied()[0]
        located = find_section(data, SECTION_NAME)
        assert located is not None
        base = located[0] + PLAYER_STATE_OFF
        mask = hex(base + PLAYER_STATE_UPGRADE_MASK)
        scratch = hex(base + PLAYER_STATE_UPGRADE_SCRATCH)
        back, _ = self._routine(data, "player_restore", count=80)
        assert f"mov edx, dword ptr [ecx*4 + {mask}]" in back
        assert f"mov dword ptr [ecx*4 + {scratch}], edx" in back
        # Only the copy is consumed.
        assert f"and dword ptr [eax*4 + {scratch}], edx" in back
        assert f"push {scratch}" in back

    def test_it_is_restored_before_the_army(self):
        """The ceiling has to be in place before carried units start filling it."""
        data, _, _, hook_va = _applied()
        text = [f"{i.mnemonic} {i.op_str}".strip() for i in _disassemble(data, hook_va, 100)]
        assert text.index(f"call {hex(_label(data, 'player_restore'))}") < text.index(
            f"call {hex(_label(data, 'restore'))}"
        )


class TestRoundTrip:
    def test_apply_verify_detect(self):
        data, _, _, _ = _applied()
        assert MapTransitionPatch().verify(data) == []
        found = MapTransitionPatch.detect(data)
        assert found is not None
        assert found.name == "map-transition"

    def test_detect_is_negative_on_a_stock_image(self):
        assert MapTransitionPatch.detect(map_transition_image()) is None

    def test_verify_reports_an_unhooked_image(self):
        assert MapTransitionPatch().verify(map_transition_image()) == [
            f"{SECTION_NAME} section is absent"
        ]
