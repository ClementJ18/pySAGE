"""Tests for the lifetime-fields patch.

The cave is hand-assembled x86 that cannot be executed here, so the tests that matter most
disassemble it back and assert it says what it was meant to say. A wrong byte in a stub does not
raise - it asks the wrong mask, pays the bonus on the wrong frame, or hands `update`'s caller a
sleep it did not mean - and an object silently outliving its lifetime, or dying through an
extension, is exactly the class of bug that survives a run. Four things get particular attention
because they are invisible in the bytes: the register roles the hooks inherit from the functions
they interrupt, stack discipline across the three ways out of `update`, the latch order that makes
the extension's trigger an edge rather than a level, and the offsets of the module-shaped scratch
the transform hands to a function that belongs to another module entirely.

The other half of the suite is the build fingerprint. This patch reads a dozen things it does not
rewrite - the field table, the constructor, both mask predicates, `getControllingPlayer`, three
parse functions, the sleepy-update driver whose contract the design rests on, the client's timer
widget that has to follow a death frame it never hears about, and the mount toggle's swap, timer
pass and retire, whose layout assumptions the transform inherits wholesale - and each has to fail
loudly on anything that is not the expected build.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

pytest.importorskip("capstone", reason="the [patch] extra (capstone) is not installed")
from capstone import CS_ARCH_X86, CS_MODE_32, Cs  # noqa: E402 - after the importorskip guard

from sage_ini.engine import parse_type  # noqa: E402
from sage_patch import LifetimeFieldsPatch, apply_patches  # noqa: E402
from sage_patch.addresses import (  # noqa: E402
    FIELD_PARSE_STRIDE,
    GAME_LOGIC_FRAME,
    THE_GAME_LOGIC,
)
from sage_patch.patches.lifetime_fields import (  # noqa: E402
    ALLOC_BYTES,
    ALLOC_RESUME_VA,
    ALLOC_VA,
    ANCHORS,
    ARM_BYTES,
    ARM_VA,
    ASCIISTRING_IS_EMPTY_VA,
    BONUS_OFFSET,
    DEFAULT_BONUS_KEYWORD,
    DEFAULT_KEYWORD,
    DEFAULT_TEMPLATE_KEYWORD,
    DIE_FRAME_OFFSET,
    EXPIRE_BYTES,
    EXPIRE_RESUME_VA,
    EXPIRE_VA,
    FIELD_TABLE_REF_VA,
    FIELD_TABLE_VA,
    GET_CONTROLLING_PLAYER_VA,
    KILL_RETURN_VA,
    LATCH_DEFAULT_BYTES,
    LATCH_DEFAULT_VA,
    LATCH_OFFSET,
    MASK_ANY_VA,
    MASK_DWORDS,
    MASK_OFFSET,
    MASK_TEST_ANY_VA,
    MODULE_DATA_OFFSET,
    MODULE_OBJECT_OFFSET,
    OBJECT_UPGRADES_COMPLETED,
    PARSE_ASCIISTRING_VA,
    PARSE_DURATION_VA,
    PARSE_UPGRADE_MASK_VA,
    PATCHED_MODULEDATA_SIZE,
    PLAYER_UPGRADES_COMPLETED,
    RETIRE_VA,
    SCRATCH_SIZE,
    SECTION_NAME,
    SLEEP_FOREVER,
    STOCK_FIELDS,
    STOCK_MODULEDATA_SIZE,
    SWAP_FLAG_OFFSET,
    SWAP_VA,
    SYNC_SKIP_VA,
    TEMPLATE_OFFSET,
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
    build_expire,
    build_held,
    build_update,
    validate_keywords,
    widened_latch_default,
)
from sage_patch.patches.lifetime_fields import (  # noqa: E402
    LifetimeFieldsPatch as Patch,
)
from sage_patch.registry import PATCHES  # noqa: E402
from sage_patch.utils import find_section, va_to_offset  # noqa: E402
from tests.sage_patch.synthetic import lifetime_fields_image  # noqa: E402

#: The repo's own clean build, for the address checks the synthetic image cannot make.
_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

#: Names other than the defaults, so a test that passes only because both sides used the same
#: fallback is not mistaken for one that checks the arithmetic.
_KEYWORD = "RefreshedByUpgrades"
_BONUS = "RefreshBonusTime"
_TEMPLATE = "BecomesOnExpiry"
_NAMES = (_KEYWORD, _BONUS, _TEMPLATE)
_DEFAULTS = (DEFAULT_KEYWORD, DEFAULT_BONUS_KEYWORD, DEFAULT_TEMPLATE_KEYWORD)


@pytest.fixture
def image() -> bytearray:
    return lifetime_fields_image()


def at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + count])


def disassemble(data: bytes | bytearray, va: int, size: int) -> list[str]:
    """The ``size`` bytes at ``va``, as ``"mnemonic operands"`` strings."""
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    return [f"{ins.mnemonic} {ins.op_str}".strip() for ins in md.disasm(at(data, va, size), va)]


def stub(
    data: bytes | bytearray, name: str, keywords: tuple[str, str, str] = _DEFAULTS
) -> list[str]:
    """One of the cave's five routines, disassembled - exactly its own bytes and no neighbour's,
    which is what lets a test assert on how a routine *ends*."""
    located = find_section(data, SECTION_NAME)
    assert located is not None, "the cave is missing"
    pieces = _layout(located[0], *keywords)
    va = getattr(pieces, f"{name}_va")
    size = {
        "alloc": lambda: len(build_alloc(va)),
        "arm": lambda: len(build_arm(va)),
        "held": lambda: len(build_held(va)),
        "update": lambda: len(build_update(va, pieces.held_va)),
        "expire": lambda: len(build_expire(va)),
    }[name]()
    return disassemble(data, va, size)


def patched(
    keyword: str = DEFAULT_KEYWORD,
    bonus: str = DEFAULT_BONUS_KEYWORD,
    template: str = DEFAULT_TEMPLATE_KEYWORD,
) -> bytearray:
    data = lifetime_fields_image()
    LifetimeFieldsPatch(keyword, bonus, template).apply(data)
    return data


class TestRoundTrip:
    def test_apply_then_verify(self, image: bytearray) -> None:
        patch = LifetimeFieldsPatch()
        patch.apply(image)
        assert patch.verify(image) == []

    def test_a_stock_image_carries_nothing(self, image: bytearray) -> None:
        assert LifetimeFieldsPatch.detect(image) is None
        assert LifetimeFieldsPatch().verify(image) != []

    def test_detect_recovers_every_keyword(self) -> None:
        found = LifetimeFieldsPatch.detect(patched(*_NAMES))
        assert found is not None
        assert (found.keyword, found.bonus_keyword, found.template_keyword) == _NAMES

    def test_verify_names_the_installed_keywords_rather_than_a_size(self) -> None:
        """A cave built for other names is a *different length*, so the size check would trip first
        and report something true but useless. The names are checked ahead of it."""
        (problem,) = LifetimeFieldsPatch().verify(patched(*_NAMES))
        assert _KEYWORD in problem and DEFAULT_KEYWORD in problem

    def test_verify_catches_a_reverted_site(self, image: bytearray) -> None:
        patch = LifetimeFieldsPatch()
        patch.apply(image)
        off = va_to_offset(image, UPDATE_VA)
        assert off is not None
        image[off : off + len(UPDATE_BYTES)] = UPDATE_BYTES  # someone un-hooked `update`
        assert any("update" in problem for problem in patch.verify(image))

    def test_apply_writes_a_file_and_leaves_the_input_alone(self, tmp_path: Path) -> None:
        src = tmp_path / "game.dat.backup"
        src.write_bytes(bytes(lifetime_fields_image()))
        out = tmp_path / "game.dat"
        apply_patches(src, [LifetimeFieldsPatch()], output=out)
        assert src.read_bytes() == bytes(lifetime_fields_image())
        assert LifetimeFieldsPatch().verify(bytearray(out.read_bytes())) == []


class TestTheEdits:
    def test_every_code_hook_replaces_whole_instructions_with_a_jump_and_padding(self) -> None:
        """Each site is displaced in full and rejoined explicitly; nothing is half-overwritten."""
        data = patched()
        sites = (
            (ALLOC_VA, ALLOC_BYTES),
            (ARM_VA, ARM_BYTES),
            (UPDATE_VA, UPDATE_BYTES),
            (EXPIRE_VA, EXPIRE_BYTES),
        )
        for va, stock in sites:
            new = at(data, va, len(stock))
            assert new[0] == 0xE9, f"0x{va:08x} is not a jmp rel32"
            assert new[5:] == b"\x90" * (len(stock) - 5), f"0x{va:08x} is not nop-padded"

    def test_the_edits_keep_their_lengths(self, image: bytearray) -> None:
        patch = LifetimeFieldsPatch()
        before = len(image)
        pieces = _layout(0xED3000, *_DEFAULTS)
        for _off, old, new, note in patch._edits(image, pieces):
            assert len(old) == len(new), note
        assert len(image) == before  # `_edits` reads, it does not write

    def test_the_field_table_reference_is_repointed_into_the_cave(self) -> None:
        data = patched()
        located = find_section(data, SECTION_NAME)
        assert located is not None
        pieces = _layout(located[0], *_DEFAULTS)
        assert struct.unpack("<I", at(data, FIELD_TABLE_REF_VA, 4))[0] == pieces.table_va
        # ... and the stock table is left exactly where it was, since it is copied, not moved
        stock = lifetime_fields_image()
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
        stock = lifetime_fields_image()
        data = patched()
        located = find_section(data, SECTION_NAME)
        assert located is not None
        pieces = _layout(located[0], *_DEFAULTS)
        size = len(STOCK_FIELDS) * FIELD_PARSE_STRIDE
        assert at(data, pieces.table_va, size) == at(stock, FIELD_TABLE_VA, size)

    def test_every_row_names_an_engine_parser(self) -> None:
        """No field needs parse code: the mask reuses `parseUpgradeMask`, the bonus reuses the
        duration parser `MinLifetime` and `MaxLifetime` use - which is what makes it authorable in
        milliseconds and stored in frames - and the template reuses the `AsciiString` parser that
        `MountedTemplate`'s own row names, landing at the offset that row uses."""
        data = patched(*_NAMES)
        located = find_section(data, SECTION_NAME)
        assert located is not None
        pieces = _layout(located[0], *_NAMES)
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
        pieces = _layout(located[0], *_DEFAULTS)
        end = pieces.table_va + (len(STOCK_FIELDS) + 3) * FIELD_PARSE_STRIDE
        assert at(data, end, FIELD_PARSE_STRIDE) == bytes(FIELD_PARSE_STRIDE)

    def test_a_keyword_the_module_already_parses_is_refused(self) -> None:
        for name, _offset in STOCK_FIELDS:
            for index in range(3):
                names = list(_DEFAULTS)
                names[index] = name.lower()
                with pytest.raises(ValueError, match="already"):
                    validate_keywords(*names)

    def test_no_two_keywords_can_be_the_same(self) -> None:
        for a, b in ((0, 1), (0, 2), (1, 2)):
            names = list(_DEFAULTS)
            names[b] = names[a].lower()
            with pytest.raises(ValueError, match="must differ"):
                validate_keywords(*names)

    def test_a_keyword_the_reader_could_never_match_is_refused(self) -> None:
        for bad in ("", "9Lives", "Extended By", "Extended=By"):
            for index in range(3):
                names = list(_DEFAULTS)
                names[index] = bad
                with pytest.raises(ValueError):
                    validate_keywords(*names)


class TestTheAllocator:
    def test_the_moduledata_grows_to_hold_all_three_fields(self) -> None:
        assert BONUS_OFFSET == MASK_OFFSET + MASK_DWORDS * 4
        assert MASK_OFFSET == STOCK_MODULEDATA_SIZE  # the mask starts where the structure ended
        assert BONUS_OFFSET + 4 <= TEMPLATE_OFFSET  # ... and the bonus clears the template's slot
        assert ZERO_DWORDS * 4 == PATCHED_MODULEDATA_SIZE - STOCK_MODULEDATA_SIZE

    def test_the_structure_reaches_past_the_template_and_its_vector(self) -> None:
        """`TEMPLATE_OFFSET` is `MountedTemplate`'s offset, not a free choice, and the three dwords
        behind it are the vector the swap's timer pass reads. All four have to be inside the
        allocation and zeroed, or that pass walks heap litter."""
        assert TEMPLATE_OFFSET + 4 + 12 <= PATCHED_MODULEDATA_SIZE

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


class TestTheExpireHook:
    def test_the_hook_displaces_two_whole_instructions(self) -> None:
        """The `ScoreKill` compare and the `push esi` behind it, and nothing half of anything - a
        `jmp rel32` is exactly their five bytes, so there is not even padding to check."""
        assert len(EXPIRE_BYTES) == 5
        assert disassemble(lifetime_fields_image(), EXPIRE_VA, len(EXPIRE_BYTES)) == [
            "cmp byte ptr [ebx + 0x11], 0",
            "push esi",
        ]

    def test_a_module_with_no_template_takes_the_stock_path(self) -> None:
        """The whole feature is gated on one `AsciiString::isEmpty`, so an object that does not
        declare the keyword runs the two displaced instructions and carries on."""
        text = stub(patched(), "expire")
        assert text[0] == f"lea ecx, [ebx + {TEMPLATE_OFFSET:#x}]"
        assert text[1] == f"call {ASCIISTRING_IS_EMPTY_VA:#x}"
        assert text[2] == "test al, al"
        assert text[3].startswith("jne ")
        assert text[-3:] == [
            "push esi",
            "cmp byte ptr [ebx + 0x11], 0",
            f"jmp {EXPIRE_RESUME_VA:#x}",
        ]

    def test_the_displaced_pair_is_re_executed_with_the_compare_last(self) -> None:
        """`EXPIRE_RESUME_VA` is a `je` that consumes the compare's flags. `push` sets none, so
        putting it first is what leaves the answer intact across the rejoin."""
        text = stub(patched(), "expire")
        assert text.index("push esi") + 1 == text.index("cmp byte ptr [ebx + 0x11], 0")

    def test_the_scratch_is_module_shaped_and_carries_the_two_pointers(self) -> None:
        """The swap belongs to another module, and reads exactly three things off the pointer it
        is handed. All three have to be at the offsets a real one would have them at."""
        text = stub(patched(), "expire")
        assert f"sub esp, {SCRATCH_SIZE:#x}" in text
        assert f"mov dword ptr [esp + {MODULE_DATA_OFFSET}], ebx" in text
        assert f"mov dword ptr [esp + {MODULE_OBJECT_OFFSET}], edi" in text
        assert f"mov byte ptr [esp + {SWAP_FLAG_OFFSET:#x}], 0" in text
        assert SWAP_FLAG_OFFSET < SCRATCH_SIZE  # ... and the flag is inside the frame

    def test_the_flag_is_cleared_before_the_swap_and_read_after_it(self) -> None:
        """It is the only way to tell a transform that happened from one the template store
        refused, and the stack it lives on holds whatever the last call left there."""
        text = stub(patched(), "expire")
        clear = text.index(f"mov byte ptr [esp + {SWAP_FLAG_OFFSET:#x}], 0")
        swap = text.index(f"call {SWAP_VA:#x}")
        test = text.index(f"cmp byte ptr [esp + {SWAP_FLAG_OFFSET:#x}], 0")
        assert clear < swap < test

    def test_a_refused_swap_falls_through_to_the_stock_death(self) -> None:
        """No such template, or a build the engine would not make: the object dies the way it
        would have without the keyword, rather than living forever."""
        text = stub(patched(), "expire")
        test = text.index(f"cmp byte ptr [esp + {SWAP_FLAG_OFFSET:#x}], 0")
        assert text[test + 1].startswith("je ")
        # ... and that arm unwinds the scratch before rejoining the path that never allocated one
        stock = text.index("push esi")
        assert text[stock - 1] == f"add esp, {SCRATCH_SIZE:#x}"

    def test_the_retire_runs_only_after_a_swap_that_happened(self) -> None:
        text = stub(patched(), "expire")
        assert text.index(f"call {SWAP_VA:#x}") < text.index(f"call {RETIRE_VA:#x}")
        assert text.index(f"cmp byte ptr [esp + {SWAP_FLAG_OFFSET:#x}], 0") < text.index(
            f"call {RETIRE_VA:#x}"
        )

    def test_both_calls_are_made_on_the_scratch(self) -> None:
        """`mov ecx, esp` twice, not once: the swap is a `__thiscall` and so is the retire, and
        the second cannot rely on the first having left `ecx` alone."""
        text = stub(patched(), "expire")
        for callee in (SWAP_VA, RETIRE_VA):
            assert text[text.index(f"call {callee:#x}") - 1] == "mov ecx, esp"

    def test_the_transform_exit_balances_the_stack_and_sleeps_forever(self) -> None:
        """`KILL_RETURN_VA` pops `edi` and `ebx` before its `leave`, so the scratch has to be gone
        by then - and the sleep is the one the stock kill returns, because either way this module's
        object is on its way out."""
        text = stub(patched(), "expire")
        out = text.index(f"jmp {KILL_RETURN_VA:#x}")
        assert text[out - 2 : out] == [
            f"add esp, {SCRATCH_SIZE:#x}",
            f"mov eax, {SLEEP_FOREVER:#x}",
        ]

    def test_it_returns_above_the_push_it_displaced(self) -> None:
        """The exit is the one the `THROWN_PROJECTILE` arm already uses from the same side of the
        `push esi`, which is what makes an unpushed `esi` correct rather than lucky."""
        stock = lifetime_fields_image()
        assert disassemble(stock, KILL_RETURN_VA, 4) == ["pop edi", "pop ebx", "leave", "ret"]
        thrown = 0x007A7FA7  # the reprieve arm, which is above the push and returns the same way
        assert disassemble(stock, thrown, len(ANCHORS[thrown])) == [
            "xor eax, eax",
            "inc eax",
            f"jmp {KILL_RETURN_VA:#x}",
        ]

    def test_the_scratch_is_never_touched_outside_the_transform_arm(self) -> None:
        """Everything between the `sub` and the two `add`s, and nothing else - so an object with no
        keyword never moves the stack pointer at all."""
        text = stub(patched(), "expire")
        assert text.count(f"sub esp, {SCRATCH_SIZE:#x}") == 1
        assert text.count(f"add esp, {SCRATCH_SIZE:#x}") == 2  # the transform and the abort


class TestTheBuildFingerprint:
    def test_a_changed_anchor_is_refused(self) -> None:
        for va in ANCHORS:
            data = lifetime_fields_image()
            off = va_to_offset(data, va)
            assert off is not None
            data[off] ^= 0xFF
            with pytest.raises(ValueError, match="not the expected build"):
                LifetimeFieldsPatch().apply(data)

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

    def test_the_borrowed_mount_code_is_anchored_even_though_it_is_never_written(self) -> None:
        """The transform is three calls into another module's code, and every layout assumption it
        makes lives there: the swap's reads of the scratch and of `TEMPLATE_OFFSET`, the timer
        pass's short-circuit on an empty vector - which is the whole reason a zeroed one is safe -
        and the retire's single read of the `Object`. A build where any of those moved would run
        the transform on nonsense, and nothing else here would notice."""
        data = patched()
        for va in (SWAP_VA, SYNC_SKIP_VA, RETIRE_VA, ASCIISTRING_IS_EMPTY_VA):
            assert va in ANCHORS, f"0x{va:08x} is not fingerprinted"
            assert at(data, va, len(ANCHORS[va])) == ANCHORS[va]

    def test_the_template_offset_is_read_out_of_the_engines_own_table(self) -> None:
        """`TEMPLATE_OFFSET` is `MountedTemplate`'s offset and `PARSE_ASCIISTRING_VA` its parse
        function, both of which the transform copies rather than chooses. The row they come from
        is anchored, so a build that spelled either differently is refused."""
        row = 0x00C05A48
        name_va, parse_fn, userdata, offset = struct.unpack("<4I", ANCHORS[row][:16])
        assert (parse_fn, userdata, offset) == (PARSE_ASCIISTRING_VA, 0, TEMPLATE_OFFSET)
        assert name_va  # the keyword string, wherever `.rdata` put it
        # ... and the row behind it is the vector, which is what fixes the structure's tail
        _name_va, _parse, _ud, vector = struct.unpack("<4I", ANCHORS[row][16:32])
        assert vector == TEMPLATE_OFFSET + 4

    def test_a_renamed_field_is_refused(self) -> None:
        data = lifetime_fields_image()
        name_va = struct.unpack("<I", at(data, FIELD_TABLE_VA, 4))[0]
        off = va_to_offset(data, name_va)
        assert off is not None
        data[off] = ord("X")
        with pytest.raises(ValueError, match="field table entry 0"):
            LifetimeFieldsPatch().apply(data)

    def test_a_moved_field_is_refused(self) -> None:
        data = lifetime_fields_image()
        off = va_to_offset(data, FIELD_TABLE_VA + 12)  # the first row's ModuleData offset
        assert off is not None
        data[off] = 0x44
        with pytest.raises(ValueError, match="expected offset"):
            LifetimeFieldsPatch().apply(data)

    def test_an_unterminated_table_is_refused(self) -> None:
        data = lifetime_fields_image()
        off = va_to_offset(data, FIELD_TABLE_VA + len(STOCK_FIELDS) * FIELD_PARSE_STRIDE)
        assert off is not None
        data[off] = 0x01
        with pytest.raises(ValueError, match="NULL-terminated"):
            LifetimeFieldsPatch().apply(data)


class TestIntegration:
    def test_the_patch_is_registered_and_attributed(self) -> None:
        assert PATCHES[LifetimeFieldsPatch.name] is LifetimeFieldsPatch
        assert LifetimeFieldsPatch.author

    def test_ini_surface_declares_every_field_under_the_installed_names(self) -> None:
        mask, bonus, template = LifetimeFieldsPatch(*_NAMES).ini_surface().fields
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
        assert (template.block, template.name, template.type, template.default) == (
            "LifetimeUpdate",
            _TEMPLATE,
            "Ref:objects",
            None,
        )
        assert mask.patch == bonus.patch == template.patch == LifetimeFieldsPatch.name

    def test_the_declared_types_are_ones_the_grammar_accepts(self) -> None:
        for delta in LifetimeFieldsPatch().ini_surface().fields:
            converter, problem = parse_type(delta.type)
            assert converter is not None and problem == ""

    def test_the_str_names_every_keyword(self) -> None:
        assert str(Patch(*_NAMES)) == f"lifetime-fields ({_KEYWORD}, {_BONUS}, {_TEMPLATE})"


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
        assert LifetimeFieldsPatch.detect(real) is None

    def test_apply_against_the_real_binary_verifies(self, real: bytes) -> None:
        data = bytearray(real)
        patch = LifetimeFieldsPatch(*_NAMES)
        patch.apply(data)
        assert patch.verify(data) == []
        assert LifetimeFieldsPatch.detect(data) is not None
