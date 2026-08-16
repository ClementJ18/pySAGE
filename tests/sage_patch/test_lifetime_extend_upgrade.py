"""Tests for the lifetime-extend-upgrade patch.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter most
disassemble it back and assert it says what it was meant to say. A wrong byte in a stub does not
raise - it asks the wrong mask, pays the bonus on the wrong frame, or hands `update`'s caller a
sleep it did not mean - and an object silently outliving its lifetime, or dying through an
extension, is exactly the class of bug that survives a run. Three things get particular attention
because they are invisible in the bytes: the register roles the hooks inherit from the functions
they interrupt, stack discipline across the two ways out of `update`, and the latch order that
makes the trigger an edge rather than a level.

The other half of the suite is the build fingerprint. This patch reads eight things it does not
rewrite - the field table, the constructor, both mask predicates, `getControllingPlayer`, both
parse functions, the sleepy-update driver whose contract the design rests on, and the client's
timer widget that has to follow a death frame it never hears about - and each has to fail loudly on
anything that is not the expected build.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

pytest.importorskip("capstone", reason="the [patch] extra (capstone) is not installed")
from capstone import CS_ARCH_X86, CS_MODE_32, Cs  # noqa: E402 - after the importorskip guard

from sage_ini.engine import parse_type  # noqa: E402
from sage_patch import LifetimeExtendUpgradePatch, apply_patches  # noqa: E402
from sage_patch.addresses import (  # noqa: E402
    FIELD_PARSE_STRIDE,
    GAME_LOGIC_FRAME,
    THE_GAME_LOGIC,
)
from sage_patch.patches.lifetime_extend_upgrade import (  # noqa: E402
    ALLOC_BYTES,
    ALLOC_RESUME_VA,
    ALLOC_VA,
    ANCHORS,
    ARM_BYTES,
    ARM_VA,
    BONUS_OFFSET,
    DEFAULT_BONUS_KEYWORD,
    DEFAULT_KEYWORD,
    DIE_FRAME_OFFSET,
    FIELD_TABLE_REF_VA,
    FIELD_TABLE_VA,
    GET_CONTROLLING_PLAYER_VA,
    LATCH_DEFAULT_BYTES,
    LATCH_DEFAULT_VA,
    LATCH_OFFSET,
    MASK_ANY_VA,
    MASK_DWORDS,
    MASK_OFFSET,
    MASK_TEST_ANY_VA,
    OBJECT_UPGRADES_COMPLETED,
    PARSE_DURATION_VA,
    PARSE_UPGRADE_MASK_VA,
    PATCHED_MODULEDATA_SIZE,
    PLAYER_UPGRADES_COMPLETED,
    SECTION_NAME,
    STOCK_FIELDS,
    STOCK_MODULEDATA_SIZE,
    UI_FRACTION_VA,
    UI_MODULE_READ_VA,
    UPDATE_BYTES,
    UPDATE_RESUME_VA,
    UPDATE_THIS_DELTA,
    UPDATE_VA,
    ZERO_DWORDS,
    _layout,
    build_alloc,
    build_arm,
    build_held,
    build_update,
    validate_keywords,
    widened_latch_default,
)
from sage_patch.patches.lifetime_extend_upgrade import (  # noqa: E402
    LifetimeExtendUpgradePatch as Patch,
)
from sage_patch.registry import PATCHES  # noqa: E402
from sage_patch.utils import find_section, va_to_offset  # noqa: E402
from tests.sage_patch.synthetic import lifetime_extend_upgrade_image  # noqa: E402

#: The repo's own clean build, for the address checks the synthetic image cannot make.
_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

#: Names other than the defaults, so a test that passes only because both sides used the same
#: fallback is not mistaken for one that checks the arithmetic.
_KEYWORD = "RefreshedByUpgrades"
_BONUS = "RefreshBonusTime"


@pytest.fixture
def image() -> bytearray:
    return lifetime_extend_upgrade_image()


def at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + count])


def disassemble(data: bytes | bytearray, va: int, size: int) -> list[str]:
    """The ``size`` bytes at ``va``, as ``"mnemonic operands"`` strings."""
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    return [f"{ins.mnemonic} {ins.op_str}".strip() for ins in md.disasm(at(data, va, size), va)]


def stub(data: bytes | bytearray, name: str, keyword: str = DEFAULT_KEYWORD) -> list[str]:
    """One of the cave's four routines, disassembled - exactly its own bytes and no neighbour's,
    which is what lets a test assert on how a routine *ends*."""
    located = find_section(data, SECTION_NAME)
    assert located is not None, "the cave is missing"
    bonus = _BONUS if keyword == _KEYWORD else DEFAULT_BONUS_KEYWORD
    pieces = _layout(located[0], keyword, bonus)
    va = getattr(pieces, f"{name}_va")
    size = {
        "alloc": lambda: len(build_alloc(va)),
        "arm": lambda: len(build_arm(va)),
        "held": lambda: len(build_held(va)),
        "update": lambda: len(build_update(va, pieces.held_va)),
    }[name]()
    return disassemble(data, va, size)


def patched(keyword: str = DEFAULT_KEYWORD, bonus: str = DEFAULT_BONUS_KEYWORD) -> bytearray:
    data = lifetime_extend_upgrade_image()
    LifetimeExtendUpgradePatch(keyword, bonus).apply(data)
    return data


class TestRoundTrip:
    def test_apply_then_verify(self, image: bytearray) -> None:
        patch = LifetimeExtendUpgradePatch()
        patch.apply(image)
        assert patch.verify(image) == []

    def test_a_stock_image_carries_nothing(self, image: bytearray) -> None:
        assert LifetimeExtendUpgradePatch.detect(image) is None
        assert LifetimeExtendUpgradePatch().verify(image) != []

    def test_detect_recovers_both_keywords(self) -> None:
        found = LifetimeExtendUpgradePatch.detect(patched(_KEYWORD, _BONUS))
        assert found is not None
        assert (found.keyword, found.bonus_keyword) == (_KEYWORD, _BONUS)

    def test_verify_names_the_installed_keywords_rather_than_a_size(self) -> None:
        """A cave built for other names is a *different length*, so the size check would trip first
        and report something true but useless. The names are checked ahead of it."""
        (problem,) = LifetimeExtendUpgradePatch().verify(patched(_KEYWORD, _BONUS))
        assert _KEYWORD in problem and DEFAULT_KEYWORD in problem

    def test_verify_catches_a_reverted_site(self, image: bytearray) -> None:
        patch = LifetimeExtendUpgradePatch()
        patch.apply(image)
        off = va_to_offset(image, UPDATE_VA)
        assert off is not None
        image[off : off + len(UPDATE_BYTES)] = UPDATE_BYTES  # someone un-hooked `update`
        assert any("update" in problem for problem in patch.verify(image))

    def test_apply_writes_a_file_and_leaves_the_input_alone(self, tmp_path: Path) -> None:
        src = tmp_path / "game.dat.backup"
        src.write_bytes(bytes(lifetime_extend_upgrade_image()))
        out = tmp_path / "game.dat"
        apply_patches(src, [LifetimeExtendUpgradePatch()], output=out)
        assert src.read_bytes() == bytes(lifetime_extend_upgrade_image())
        assert LifetimeExtendUpgradePatch().verify(bytearray(out.read_bytes())) == []


class TestTheEdits:
    def test_every_code_hook_replaces_whole_instructions_with_a_jump_and_padding(self) -> None:
        """Each site is displaced in full and rejoined explicitly; nothing is half-overwritten."""
        data = patched()
        for va, stock in ((ALLOC_VA, ALLOC_BYTES), (ARM_VA, ARM_BYTES), (UPDATE_VA, UPDATE_BYTES)):
            new = at(data, va, len(stock))
            assert new[0] == 0xE9, f"0x{va:08x} is not a jmp rel32"
            assert new[5:] == b"\x90" * (len(stock) - 5), f"0x{va:08x} is not nop-padded"

    def test_the_edits_keep_their_lengths(self, image: bytearray) -> None:
        patch = LifetimeExtendUpgradePatch()
        before = len(image)
        pieces = _layout(0xED3000, DEFAULT_KEYWORD, DEFAULT_BONUS_KEYWORD)
        for _off, old, new, note in patch._edits(image, pieces):
            assert len(old) == len(new), note
        assert len(image) == before  # `_edits` reads, it does not write

    def test_the_field_table_reference_is_repointed_into_the_cave(self) -> None:
        data = patched()
        located = find_section(data, SECTION_NAME)
        assert located is not None
        pieces = _layout(located[0], DEFAULT_KEYWORD, DEFAULT_BONUS_KEYWORD)
        assert struct.unpack("<I", at(data, FIELD_TABLE_REF_VA, 4))[0] == pieces.table_va
        # ... and the stock table is left exactly where it was, since it is copied, not moved
        stock = lifetime_extend_upgrade_image()
        assert at(data, FIELD_TABLE_VA, 16) == at(stock, FIELD_TABLE_VA, 16)

    def test_the_latch_default_widens_one_store_and_nothing_else(self) -> None:
        """`eax` is already zero there, the instance is 0x2c bytes, and the two stores after it are
        untouched - so the whole cost of the new instance field is one opcode byte."""
        data = patched()
        assert widened_latch_default() == b"\x89" + LATCH_DEFAULT_BYTES[1:]
        assert at(data, LATCH_DEFAULT_VA, 3) == widened_latch_default()
        assert disassemble(data, LATCH_DEFAULT_VA, 3) == ["mov dword ptr [esi + 0x28], eax"]
        assert at(data, LATCH_DEFAULT_VA + 3, 6) == bytes.fromhex("894620894624")

    def test_the_latch_lives_in_the_instances_own_padding(self) -> None:
        """0x2c is the stock `sizeof`, and the WaitForWakeUp byte at 0x28 is the last thing in it,
        so 0x29 is padding the allocator already pays for."""
        assert LATCH_OFFSET == 0x29
        assert LATCH_OFFSET < 0x2C


class TestTheTable:
    def test_the_stock_rows_are_copied_verbatim(self) -> None:
        stock = lifetime_extend_upgrade_image()
        data = patched()
        located = find_section(data, SECTION_NAME)
        assert located is not None
        pieces = _layout(located[0], DEFAULT_KEYWORD, DEFAULT_BONUS_KEYWORD)
        size = len(STOCK_FIELDS) * FIELD_PARSE_STRIDE
        assert at(data, pieces.table_va, size) == at(stock, FIELD_TABLE_VA, size)

    def test_both_rows_name_an_engine_parser(self) -> None:
        """Neither field needs parse code: the mask reuses `parseUpgradeMask`, and the bonus reuses
        the duration parser `MinLifetime` and `MaxLifetime` use, which is what makes it authorable
        in milliseconds and stored in frames."""
        data = patched(_KEYWORD, _BONUS)
        located = find_section(data, SECTION_NAME)
        assert located is not None
        pieces = _layout(located[0], _KEYWORD, _BONUS)
        base = pieces.table_va + len(STOCK_FIELDS) * FIELD_PARSE_STRIDE

        name_va, parse_fn, userdata, offset = struct.unpack("<4I", at(data, base, 16))
        assert (parse_fn, userdata, offset) == (PARSE_UPGRADE_MASK_VA, 0, MASK_OFFSET)
        assert at(data, name_va, len(_KEYWORD) + 1) == _KEYWORD.encode() + b"\x00"

        name_va, parse_fn, userdata, offset = struct.unpack("<4I", at(data, base + 16, 16))
        assert (parse_fn, userdata, offset) == (PARSE_DURATION_VA, 0, BONUS_OFFSET)
        assert at(data, name_va, len(_BONUS) + 1) == _BONUS.encode() + b"\x00"

    def test_the_table_is_terminated(self) -> None:
        data = patched()
        located = find_section(data, SECTION_NAME)
        assert located is not None
        pieces = _layout(located[0], DEFAULT_KEYWORD, DEFAULT_BONUS_KEYWORD)
        end = pieces.table_va + (len(STOCK_FIELDS) + 2) * FIELD_PARSE_STRIDE
        assert at(data, end, FIELD_PARSE_STRIDE) == bytes(FIELD_PARSE_STRIDE)

    def test_a_keyword_the_module_already_parses_is_refused(self) -> None:
        for name, _offset in STOCK_FIELDS:
            with pytest.raises(ValueError, match="already"):
                validate_keywords(name.lower(), DEFAULT_BONUS_KEYWORD)
            with pytest.raises(ValueError, match="already"):
                validate_keywords(DEFAULT_KEYWORD, name.lower())

    def test_the_two_keywords_cannot_be_the_same(self) -> None:
        with pytest.raises(ValueError, match="cannot both be called"):
            validate_keywords("SameName", "samename")

    def test_a_keyword_the_reader_could_never_match_is_refused(self) -> None:
        for bad in ("", "9Lives", "Extended By", "Extended=By"):
            with pytest.raises(ValueError):
                validate_keywords(bad, DEFAULT_BONUS_KEYWORD)


class TestTheAllocator:
    def test_the_moduledata_grows_by_one_mask_and_one_int(self) -> None:
        assert BONUS_OFFSET == MASK_OFFSET + MASK_DWORDS * 4
        assert PATCHED_MODULEDATA_SIZE == BONUS_OFFSET + 4
        assert MASK_OFFSET == STOCK_MODULEDATA_SIZE  # the mask starts where the structure ended
        assert ZERO_DWORDS * 4 == PATCHED_MODULEDATA_SIZE - STOCK_MODULEDATA_SIZE

    def test_the_stub_allocates_the_grown_size_and_zeroes_everything_it_added(self) -> None:
        text = stub(patched(), "alloc")
        assert text[0] == "push esi"  # the register save the window owed its caller
        assert text[1] == f"push {PATCHED_MODULEDATA_SIZE:#x}"
        assert text[2].startswith("call")
        assert f"lea edx, [eax + {STOCK_MODULEDATA_SIZE:#x}]" in text
        assert f"mov ecx, {ZERO_DWORDS:#x}" in text
        assert "mov dword ptr [edx], eax" in text  # the zeroing loop's body

    def test_the_stub_does_not_dereference_a_failed_allocation(self) -> None:
        """`newModuleData` tests the block for null itself, so the zeroing has to as well - and the
        guard has to come *before* the loop, not after it."""
        text = stub(patched(), "alloc")
        assert text[3] == "test eax, eax"
        assert text[4].startswith("je ")
        assert text.index("test eax, eax") < text.index("mov dword ptr [edx], eax")

    def test_the_stub_preserves_the_block_across_the_zeroing(self) -> None:
        text = stub(patched(), "alloc")
        assert text.count("push eax") == text.count("pop eax") == 1
        assert text.index("push eax") < text.index("pop eax")

    def test_the_stub_rejoins_where_the_argument_is_cleaned(self) -> None:
        assert stub(patched(), "alloc")[-1] == f"jmp {ALLOC_RESUME_VA:#x}"


class TestTheArmingHook:
    def test_the_displaced_store_is_reproduced_first(self) -> None:
        text = stub(patched(), "arm")
        assert text[0] == f"mov dword ptr [esi + {DIE_FRAME_OFFSET:#x}], ecx"

    def test_the_sleep_becomes_one_frame_only_when_the_mask_is_declared(self) -> None:
        """Without the poll there is no edge to see: the module would sleep to its death frame and
        wake once, long after the upgrade arrived."""
        text = stub(patched(), "arm")
        assert f"call {MASK_ANY_VA:#x}" in text
        assert "mov eax, 1" in text
        assert text.index("push eax") < text.index(f"call {MASK_ANY_VA:#x}") < text.index("pop eax")
        assert text.index("pop eax") < text.index("mov eax, 1")

    def test_the_stub_returns_the_way_the_stock_tail_did(self) -> None:
        assert stub(patched(), "arm")[-2:] == ["pop esi", "ret 8"]


class TestTheHeldPredicate:
    def test_both_completed_masks_are_asked_in_the_engines_own_order(self) -> None:
        text = stub(patched(), "held")
        assert f"lea ecx, [esi + {OBJECT_UPGRADES_COMPLETED:#x}]" in text
        assert f"call {GET_CONTROLLING_PLAYER_VA:#x}" in text
        assert f"lea ecx, [eax + {PLAYER_UPGRADES_COMPLETED:#x}]" in text
        assert text.count(f"call {MASK_TEST_ANY_VA:#x}") == 2
        assert text.index(f"lea ecx, [esi + {OBJECT_UPGRADES_COMPLETED:#x}]") < text.index(
            f"call {GET_CONTROLLING_PLAYER_VA:#x}"
        )

    def test_the_mask_is_pushed_afresh_for_each_call(self) -> None:
        """`testForAny` is `__thiscall` with one stack argument and cleans it itself, so the second
        call needs its own push - and the mask has to be in a register that survived the first."""
        text = stub(patched(), "held")
        assert text.count("push edi") == 2

    def test_an_unowned_object_answers_on_its_own_mask_alone(self) -> None:
        text = stub(patched(), "held")
        player = text.index(f"call {GET_CONTROLLING_PLAYER_VA:#x}")
        assert text[player + 1] == "test eax, eax"
        assert text[player + 2].startswith("je ")

    def test_every_path_returns_a_boolean_in_al(self) -> None:
        text = stub(patched(), "held")
        assert "mov al, 1" in text
        assert "xor al, al" in text
        last = len(text) - 1 - text[::-1].index(f"call {MASK_TEST_ANY_VA:#x}")
        assert text[last + 1] == "ret"


class TestTheUpdateHook:
    def test_the_module_and_object_come_from_the_interface_subobject(self) -> None:
        text = stub(patched(), "update")
        assert "mov ebx, dword ptr [ecx - 0xc]" in text  # the ModuleData
        assert "mov esi, dword ptr [ecx - 8]" in text  # the Object
        assert f"lea edi, [ebx + {MASK_OFFSET:#x}]" in text  # the mask, for both predicates

    def test_a_module_with_no_mask_takes_the_stock_path(self) -> None:
        text = stub(patched(), "update")
        assert f"call {MASK_ANY_VA:#x}" in text
        assert text[-5:] == [
            "push ebp",
            "mov ebp, esp",
            "push ecx",
            "push ebx",
            f"jmp {UPDATE_RESUME_VA:#x}",
        ]

    def test_the_latch_is_read_before_it_is_written(self) -> None:
        """The whole trigger is these two instructions in this order. Swapped, the stored value is
        read straight back and the answer is always 'held last frame too', so the bonus is paid
        exactly never."""
        text = stub(patched(), "update")
        slot = LATCH_OFFSET - UPDATE_THIS_DELTA
        read = text.index(f"mov dl, byte ptr [ecx + {slot:#x}]")
        write = text.index(f"mov byte ptr [ecx + {slot:#x}], al")
        assert read + 1 == write

    def test_the_latch_is_written_on_every_polled_frame(self) -> None:
        """Both arms of the edge test are reached *after* the store, which is what re-arms the
        trigger when the upgrade goes away rather than latching it forever."""
        text = stub(patched(), "update")
        slot = LATCH_OFFSET - UPDATE_THIS_DELTA
        write = text.index(f"mov byte ptr [ecx + {slot:#x}], al")
        assert text[write + 1] == "test al, al"  # held now?
        assert text[write + 3] == "test dl, dl"  # held last frame?

    def test_the_bonus_is_added_to_the_death_frame(self) -> None:
        text = stub(patched(), "update")
        assert f"mov edx, dword ptr [ebx + {BONUS_OFFSET:#x}]" in text
        assert f"add dword ptr [ecx + {DIE_FRAME_OFFSET - UPDATE_THIS_DELTA:#x}], edx" in text
        assert text.index(f"mov edx, dword ptr [ebx + {BONUS_OFFSET:#x}]") + 1 == text.index(
            f"add dword ptr [ecx + {DIE_FRAME_OFFSET - UPDATE_THIS_DELTA:#x}], edx"
        )

    def test_a_poll_that_is_not_yet_due_sleeps_instead_of_killing(self) -> None:
        """Without this arm every polled frame would run the stock kill, and an extended object
        would die on the frame after it was granted its bonus."""
        text = stub(patched(), "update")
        assert f"mov eax, dword ptr [{THE_GAME_LOGIC:#x}]" in text
        assert f"mov eax, dword ptr [eax + {GAME_LOGIC_FRAME:#x}]" in text
        assert f"cmp eax, dword ptr [ecx + {DIE_FRAME_OFFSET - UPDATE_THIS_DELTA:#x}]" in text
        assert any(line.startswith("jae ") for line in text)
        assert text[text.index("mov eax, 1") + 1] == "ret"  # UPDATE_SLEEP(1), and out

    def test_the_death_frame_is_compared_after_the_bonus_is_paid(self) -> None:
        """Paid first, compared second: an upgrade gained on the very frame the object was due to
        die still saves it."""
        text = stub(patched(), "update")
        add = text.index(f"add dword ptr [ecx + {DIE_FRAME_OFFSET - UPDATE_THIS_DELTA:#x}], edx")
        cmp_ = text.index(f"cmp eax, dword ptr [ecx + {DIE_FRAME_OFFSET - UPDATE_THIS_DELTA:#x}]")
        assert add < cmp_

    def test_the_module_pointer_survives_both_predicates(self) -> None:
        text = stub(patched(), "update")
        assert text.count("push ecx") == 3  # twice here, once in the displaced prologue
        assert text.count("pop ecx") == 2

    def test_every_exit_restores_the_callee_saved_registers(self) -> None:
        """Two ways out - polling and stock - and each pops what the stub pushed, `edi` included:
        the stock function pushes `edi` *after* this hook and pops it on the way out, so a dirty
        one is handed back to `update`'s caller rather than merely clobbered."""
        text = stub(patched(), "update")
        assert text[:3] == ["push ebx", "push esi", "push edi"]
        assert text.count("pop edi") == text.count("pop esi") == text.count("pop ebx") == 2
        exits = [i for i, line in enumerate(text) if line == "ret" or line.startswith("jmp ")]
        assert len(exits) == 2
        for index in exits:
            window = text[max(0, index - 7) : index]
            assert window[window.index("pop edi") : window.index("pop edi") + 3] == [
                "pop edi",
                "pop esi",
                "pop ebx",
            ], f"the exit at instruction {index} does not restore the stack: {window}"


class TestTheBuildFingerprint:
    def test_a_changed_anchor_is_refused(self) -> None:
        for va in ANCHORS:
            data = lifetime_extend_upgrade_image()
            off = va_to_offset(data, va)
            assert off is not None
            data[off] ^= 0xFF
            with pytest.raises(ValueError, match="not the expected build"):
                LifetimeExtendUpgradePatch().apply(data)

    def test_the_ui_timer_is_anchored_even_though_it_is_never_written(self) -> None:
        """The patch's claim that the in-world bar follows is a claim about code it does not touch:
        the widget reads the death frame and the start frame off the live module every frame. A
        build that computed the fill any other way would leave the bar wrong, and nothing else here
        would notice."""
        assert UI_MODULE_READ_VA in ANCHORS
        assert UI_FRACTION_VA in ANCHORS
        data = patched()
        for va in (UI_MODULE_READ_VA, UI_FRACTION_VA):
            assert at(data, va, len(ANCHORS[va])) == ANCHORS[va]

    def test_a_renamed_field_is_refused(self) -> None:
        data = lifetime_extend_upgrade_image()
        name_va = struct.unpack("<I", at(data, FIELD_TABLE_VA, 4))[0]
        off = va_to_offset(data, name_va)
        assert off is not None
        data[off] = ord("X")
        with pytest.raises(ValueError, match="field table entry 0"):
            LifetimeExtendUpgradePatch().apply(data)

    def test_a_moved_field_is_refused(self) -> None:
        data = lifetime_extend_upgrade_image()
        off = va_to_offset(data, FIELD_TABLE_VA + 12)  # the first row's ModuleData offset
        assert off is not None
        data[off] = 0x44
        with pytest.raises(ValueError, match="expected offset"):
            LifetimeExtendUpgradePatch().apply(data)

    def test_an_unterminated_table_is_refused(self) -> None:
        data = lifetime_extend_upgrade_image()
        off = va_to_offset(data, FIELD_TABLE_VA + len(STOCK_FIELDS) * FIELD_PARSE_STRIDE)
        assert off is not None
        data[off] = 0x01
        with pytest.raises(ValueError, match="NULL-terminated"):
            LifetimeExtendUpgradePatch().apply(data)


class TestIntegration:
    def test_the_patch_is_registered_and_attributed(self) -> None:
        assert PATCHES[LifetimeExtendUpgradePatch.name] is LifetimeExtendUpgradePatch
        assert LifetimeExtendUpgradePatch.author

    def test_ini_surface_declares_both_fields_under_the_installed_names(self) -> None:
        mask, bonus = LifetimeExtendUpgradePatch(_KEYWORD, _BONUS).ini_surface().fields
        assert (mask.block, mask.name, mask.type, mask.default) == (
            "LifetimeUpdate",
            _KEYWORD,
            "Ref[]:upgrades",
            None,
        )
        assert (bonus.block, bonus.name, bonus.type, bonus.default) == (
            "LifetimeUpdate",
            _BONUS,
            "Int",
            0,
        )
        assert mask.patch == bonus.patch == LifetimeExtendUpgradePatch.name

    def test_the_declared_types_are_ones_the_grammar_accepts(self) -> None:
        for delta in LifetimeExtendUpgradePatch().ini_surface().fields:
            converter, problem = parse_type(delta.type)
            assert converter is not None and problem == ""

    def test_the_str_names_both_keywords(self) -> None:
        assert str(Patch(_KEYWORD, _BONUS)) == f"lifetime-extend-upgrade ({_KEYWORD}, {_BONUS})"


@pytest.mark.full
@pytest.mark.skipif(
    not _GAME_DAT.exists(), reason="requires a local game.dat (gitignored, absent in CI)"
)
class TestInstalledBinary:
    """The addresses, against the real thing. Everything above is self-consistent by
    construction; only this says the sites are where the patch claims."""

    @pytest.fixture(scope="class")
    @classmethod
    def real(cls) -> bytes:
        return _GAME_DAT.read_bytes()

    def test_every_site_holds_its_stock_bytes(self, real: bytes) -> None:
        for va, stock in (
            (ALLOC_VA, ALLOC_BYTES),
            (ARM_VA, ARM_BYTES),
            (UPDATE_VA, UPDATE_BYTES),
            (LATCH_DEFAULT_VA, LATCH_DEFAULT_BYTES),
        ):
            assert at(real, va, len(stock)) == stock, f"{va:#010x}"
        assert struct.unpack("<I", at(real, FIELD_TABLE_REF_VA, 4))[0] == FIELD_TABLE_VA

    def test_every_anchor_holds_what_the_patch_expects(self, real: bytes) -> None:
        for va, expected in ANCHORS.items():
            assert at(real, va, len(expected)) == expected, f"{va:#010x}"

    def test_the_field_table_is_the_module_the_patch_thinks_it_is(self, real: bytes) -> None:
        for index, (name, offset) in enumerate(STOCK_FIELDS):
            row = at(real, FIELD_TABLE_VA + index * FIELD_PARSE_STRIDE, FIELD_PARSE_STRIDE)
            name_va, _parse, _ud, field_off = struct.unpack("<4I", row)
            assert at(real, name_va, len(name) + 1) == name.encode() + b"\x00"
            assert field_off == offset

    def test_the_bonus_reuses_the_parser_the_lifetime_fields_use(self, real: bytes) -> None:
        """`MinLifetime` and `MaxLifetime` are milliseconds in, frames out. The bonus is added to a
        frame, so it has to be parsed by that same function and no other."""
        for index, (name, _offset) in enumerate(STOCK_FIELDS):
            if name not in ("MinLifetime", "MaxLifetime"):
                continue
            row = at(real, FIELD_TABLE_VA + index * FIELD_PARSE_STRIDE, FIELD_PARSE_STRIDE)
            assert struct.unpack("<4I", row)[1] == PARSE_DURATION_VA

    def test_the_installed_binary_is_not_already_patched(self, real: bytes) -> None:
        assert LifetimeExtendUpgradePatch.detect(real) is None

    def test_apply_against_the_real_binary_verifies(self, real: bytes) -> None:
        data = bytearray(real)
        patch = LifetimeExtendUpgradePatch(_KEYWORD, _BONUS)
        patch.apply(data)
        assert patch.verify(data) == []
        assert LifetimeExtendUpgradePatch.detect(data) is not None
