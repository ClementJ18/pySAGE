"""Tests for the second-resource patch (phase 1).

The patch is hand-encoded x86 in a cave plus five edits to engine bytes, and none of that fails
loudly when it is wrong: a mis-encoded displacement assembles, applies and verifies, and then the
game reads the wrong field or jumps into the middle of an instruction. So the tests that matter
here **disassemble the result back** and assert it says what it was meant to say - the stance
`test_command_point_upkeep` and `test_hero_mana` take for their bytes.

Two encoding bugs this file exists to have caught, both of which would apply and verify happily:

* `DepositAmount2` lives in two bytes of `ModuleData` padding, so it must be read with a **word**
  load and parsed by the **UInt16** parser. Either one widened to a dword runs past `sizeof`.
* The constructor edit replaces two byte stores with one dword store, and it is that width -
  not the field table - that gives the new field its default of 0. A byte or word store there
  leaves it holding whatever `operator new` returned.

The rest hold the invariants the design rests on: the pool is seeded by assignment rather than
accumulation, every index into it is bounds-checked, the grant still performs the deposit it
displaced, and the patch composes with `command-point-upkeep` - the other patch that needs a
`PlayerTemplate` block key and rebuilds the same field table.
"""

from __future__ import annotations

import itertools
import struct

import pytest

from sage_patch import CommandPointUpkeepPatch, HeroManaPatch, SecondResourcePatch
from sage_patch.addresses import (
    AUTO_DEPOSIT_DEPOSIT,
    AUTO_DEPOSIT_DEPOSIT_BYTES,
    AUTO_DEPOSIT_DEPOSIT_RESUME,
    AUTO_DEPOSIT_FIELD_TABLE,
    AUTO_DEPOSIT_FIELD_TABLE_REF_OPCODES,
    AUTO_DEPOSIT_FIELD_TABLE_REFS,
    AUTO_DEPOSIT_MODULE_DATA_CTOR_BOOLS,
    AUTO_DEPOSIT_MODULE_DATA_CTOR_BOOLS_BYTES,
    AUTO_DEPOSIT_MODULE_DATA_SIZE,
    BUILD_GATE_AFFORD,
    BUILD_GATE_AFFORD_BYTES,
    BUILD_GATE_AFFORD_OK,
    BUILD_GATE_AFFORD_REFUSE,
    INI_PARSE_INT,
    INI_PARSE_UNSIGNED_SHORT,
    MAX_PLAYER_COUNT,
    MONEY_DEPOSIT,
    MONEY_WITHDRAW,
    PALANTIR_RESOURCES,
    PALANTIR_RESOURCES_BYTES,
    PALANTIR_RESOURCES_CACHE,
    PALANTIR_RESOURCES_CACHE_BYTES,
    PALANTIR_RESOURCES_CACHE_PUSH,
    PALANTIR_RESOURCES_CACHE_SKIP,
    PALANTIR_RESOURCES_DONE,
    PALANTIR_RESOURCES_RESUME,
    PLAYER_INIT_ENTRY,
    PLAYER_INIT_ENTRY_BYTES,
    PLAYER_INIT_ENTRY_RESUME,
    PLAYER_TEMPLATE_BLOCK_KEY,
    PLAYER_TEMPLATE_BLOCK_KEY_BYTES,
    PLAYER_TEMPLATE_BLOCK_KEY_EARLY,
    PLAYER_TEMPLATE_BLOCK_KEY_EARLY_BYTES,
    PLAYER_TEMPLATE_BLOCK_KEY_EARLY_RESUME,
    PLAYER_TEMPLATE_FIELD_TABLE,
    PRODUCTION_WITHDRAW,
    PRODUCTION_WITHDRAW_BYTES,
    THING_TEMPLATE_COPY_CALL,
    THING_TEMPLATE_COPY_CALL_BYTES,
    THING_TEMPLATE_COPY_ID,
    THING_TEMPLATE_COPY_ID_BYTES,
    THING_TEMPLATE_COPY_ID_RESUME,
    TOOLTIP_COST_BUILD,
    TOOLTIP_COST_BUILD_RESUME,
    TOOLTIP_COST_BYTES,
    TOOLTIP_COST_REVIVE,
    TOOLTIP_COST_REVIVE_RESUME,
    UNICODE_STRING_CONCAT,
    UNICODE_STRING_DTOR,
    UNICODE_STRING_FORMAT,
)
from sage_patch.patches import second_resource as sr
from sage_patch.patches.hero_mana import entries_before, read_field_table
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch import test_command_point_upkeep as cpu_test

IMAGE_BASE = 0x400000

#: Where this image parks the `AutoDepositUpdate` table's name strings - clear of the block
#: `test_command_point_upkeep` uses for the `PlayerTemplate` ones, so one image hosts both.
STRINGS_VA = 0x00DAC000

#: The stock `AutoDepositUpdate` table, as the real build holds it. The three
#: :meth:`SecondResourcePatch._check_build` fingerprints are among them.
STOCK_FIELDS: tuple[tuple[str, int], ...] = (
    ("DepositTiming", 0x08),
    ("Upgrade", 0x14),
    ("DepositAmount", 0x0C),
    ("InitialCaptureBonus", 0x10),
    ("UpgradeBonusPercent", 0x18),
    ("UpgradeMustBePresent", 0x1C),
    ("GiveNoXP", 0x20),
    ("OnlyWhenGarrisoned", 0x21),
)


def _name_vas() -> tuple[list[int], bytes]:
    strings = bytearray()
    vas: list[int] = []
    for name, _offset in STOCK_FIELDS:
        vas.append(STRINGS_VA + len(strings))
        strings += name.encode("ascii") + b"\x00"
    return vas, bytes(strings)


def synthetic_image() -> bytearray:
    """A PE32 image mapping every address this patch touches - and every address
    `command-point-upkeep` touches, so the composition test needs no second image - with the real
    original bytes planted, so the whole apply + verify path runs in CI without the copyrighted
    `game.dat`."""
    data = cpu_test.synthetic_image()
    vas, strings = _name_vas()
    needed = STRINGS_VA + len(strings) - IMAGE_BASE + 0x400
    if len(data) < needed:
        data += bytes(((needed - len(data)) // 0x200 + 1) * 0x200)
        _grow_text_section(data)
    plant_sites(data, vas, strings)
    return data


def _grow_text_section(data: bytearray) -> None:
    """Extend the single mapped section over the bytes just appended."""
    e = struct.unpack_from("<I", data, 0x3C)[0]
    header = e + 24 + struct.unpack_from("<H", data, e + 20)[0]
    mapped = len(data) - 0x1000
    struct.pack_into("<IIII", data, header + 8, mapped, 0x1000, mapped, 0x1000)


def plant_sites(data: bytearray, vas: list[int], strings: bytes) -> None:
    """The clean bytes the patch asserts before writing."""

    def at(va: int) -> int:
        return va - IMAGE_BASE

    data[at(STRINGS_VA) : at(STRINGS_VA) + len(strings)] = strings

    table = at(AUTO_DEPOSIT_FIELD_TABLE)
    for index, (_name, offset) in enumerate(STOCK_FIELDS):
        struct.pack_into("<IIII", data, table + index * 16, vas[index], INI_PARSE_INT, 0, offset)
    struct.pack_into("<IIII", data, table + len(STOCK_FIELDS) * 16, 0, 0, 0, 0)
    for ref_va, opcode in zip(
        AUTO_DEPOSIT_FIELD_TABLE_REFS, AUTO_DEPOSIT_FIELD_TABLE_REF_OPCODES, strict=True
    ):
        data[at(ref_va)] = opcode
        struct.pack_into("<I", data, at(ref_va) + 1, AUTO_DEPOSIT_FIELD_TABLE)

    for va, window in (
        (AUTO_DEPOSIT_MODULE_DATA_CTOR_BOOLS, AUTO_DEPOSIT_MODULE_DATA_CTOR_BOOLS_BYTES),
        (PLAYER_TEMPLATE_BLOCK_KEY_EARLY, PLAYER_TEMPLATE_BLOCK_KEY_EARLY_BYTES),
        (PLAYER_INIT_ENTRY, PLAYER_INIT_ENTRY_BYTES),
        (AUTO_DEPOSIT_DEPOSIT, AUTO_DEPOSIT_DEPOSIT_BYTES),
        (PALANTIR_RESOURCES, PALANTIR_RESOURCES_BYTES),
        (PALANTIR_RESOURCES_CACHE, PALANTIR_RESOURCES_CACHE_BYTES),
        (THING_TEMPLATE_COPY_ID, THING_TEMPLATE_COPY_ID_BYTES),
        (BUILD_GATE_AFFORD, BUILD_GATE_AFFORD_BYTES),
        (PRODUCTION_WITHDRAW, PRODUCTION_WITHDRAW_BYTES),
        (TOOLTIP_COST_BUILD, TOOLTIP_COST_BYTES),
        (TOOLTIP_COST_REVIVE, TOOLTIP_COST_BYTES),
    ):
        data[at(va) : at(va) + len(window)] = window


@pytest.fixture(scope="module")
def image() -> bytearray:
    return synthetic_image()


@pytest.fixture(scope="module")
def patched(image: bytearray) -> bytes:
    data = bytearray(image)
    SecondResourcePatch().apply(data)
    return bytes(data)


def _tables(data: bytes) -> tuple:
    """The rows that preceded this patch's own in every table it extends, in `_TABLES` order."""
    bases = SecondResourcePatch._resolve(data)  # noqa: SLF001
    return tuple(
        entries_before(data, read_field_table(data, base), spec.field)
        for spec, base in zip(sr._TABLES, bases, strict=True)  # noqa: SLF001
    )


def cave(data: bytes, *, hud: bool = True):
    """``(section VA, code VA, code bytes)`` for the emitted routines."""
    section_va, off, vsize = find_section(data, sr.SECTION_NAME)
    code_off = SecondResourcePatch._code_offset(_tables(data))  # noqa: SLF001
    return section_va, section_va + code_off, bytes(data[off + code_off : off + vsize])


def labels(data: bytes, *, hud: bool = True) -> dict[str, int]:
    section_va, _off, _vsize = find_section(data, sr.SECTION_NAME)
    asm = SecondResourcePatch(hud=hud)._assemble(section_va, _tables(data))  # noqa: SLF001
    return {name: asm.label_va(name) for name in asm._labels}  # noqa: SLF001


def name_of(data: bytes, entry) -> str | None:
    off = va_to_offset(data, entry[0])
    return None if off is None else data[off : data.index(b"\x00", off)].decode("latin1")


def disasm(data: bytes, start: int, end: int):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    _section, code_va, code = cave(data)
    return [i for i in md.disasm(code, code_va) if start <= i.address < end]


#: The cave's routines, in the order :meth:`SecondResourcePatch._assemble` emits them - which is
#: what bounds each one, so a test looking at `init` cannot accidentally read `grant`'s bytes.
ROUTINES = (
    "lookup",
    "insert",
    "block",
    "parse",
    "dep_parse",
    "init",
    "grant",
    "cost_row",
    "cost_claim",
    "cost_of",
    "cost_parse",
    "cost_copy",
    "gate",
    "spend",
    "local_pool",
    "text",
    "refresh",
    "tip",
    "tip_build",
    "tip_revive",
)


def routine(data: bytes, label: str):
    """The instructions of one emitted routine, from its label to the next one's."""
    known = labels(data)
    start = known[label]
    following = [known[name] for name in ROUTINES if name in known and known[name] > start]
    _section, code_va, code = cave(data)
    return disasm(data, start, min(following, default=code_va + len(code)))


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self, patched):
        """Capstone stopping early means an invalid encoding, which would be a crash in-game."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        _section, code_va, code = cave(patched)
        assert sum(i.size for i in md.disasm(code, code_va)) == len(code)

    def test_the_pool_is_exactly_the_engines_player_array(self):
        """One slot per `Player`, indexed by `m_playerIndex`. `MAX_PLAYER_COUNT` is not a budget
        this patch chose - it is how wide every per-player array the engine embeds already is."""
        assert sr._ROWS_OFF - sr._POOL_OFF == MAX_PLAYER_COUNT * 4  # noqa: SLF001

    def test_the_pool_the_rows_and_the_block_key_start_zeroed(self, patched):
        """A zero key is the empty marker, so a dirty row table would hand a faction another
        faction's starting balance - and a dirty pool would start a game with free resources."""
        _va, off, _vsize = find_section(patched, sr.SECTION_NAME)
        for start, size in (
            (sr._KEY_OFF, 4),  # noqa: SLF001
            (sr._POOL_OFF, MAX_PLAYER_COUNT * 4),  # noqa: SLF001
            (sr._ROWS_OFF, sr.ROWS * sr.ROW_STRIDE),  # noqa: SLF001
        ):
            assert bytes(patched[off + start : off + start + size]) == bytes(size)

    def test_the_row_index_fold_is_a_mask(self):
        assert sr.ROWS & (sr.ROWS - 1) == 0, "a non-power-of-two would need a divide"

    def test_it_relocates_with_its_section(self, image):
        """Every routine address and every table pointer is recomputed for where the section
        lands, so the cave cannot be assembled once and reused at another base."""
        tables = tuple(
            read_field_table(image, base) for base in SecondResourcePatch._resolve(image)
        )  # noqa: SLF001
        patch = SecondResourcePatch()
        a = patch._assemble(0x00F00000, tables).finish()  # noqa: SLF001
        b = patch._assemble(0x00F01000, tables).finish()  # noqa: SLF001
        assert a != b
        assert len(a) == len(b)


class TestTheNewFieldFitsItsPadding:
    """The whole "no struct growth" claim is two bytes wide, and three things have to agree
    about that width or the module writes past its own allocation."""

    def test_the_field_sits_in_the_two_bytes_past_the_last_bool(self):
        assert sr.DEPOSIT_OFFSET == 0x22
        assert sr.DEPOSIT_OFFSET + 2 == AUTO_DEPOSIT_MODULE_DATA_SIZE

    def test_the_parsing_is_the_uint16_one_not_the_int_one(self, patched):
        """The wrapper adds the in-use flag and nothing else - all the *parsing* is the engine's
        `INI::parseUnsignedShort`. `INI::parseInt` would store four bytes at +0x22 and run two
        past `sizeof`."""
        table = read_field_table(patched, SecondResourcePatch._resolve(patched)[0])  # noqa: SLF001
        entry = next(e for e in table if name_of(patched, e) == sr.DEPOSIT_FIELD)
        assert entry[1] == labels(patched)["dep_parse"]
        calls = [i for i in routine(patched, "dep_parse") if i.mnemonic == "call"]
        assert [int(i.op_str, 16) for i in calls] == [INI_PARSE_UNSIGNED_SHORT]
        assert INI_PARSE_INT not in [int(i.op_str, 16) for i in calls]

    def test_the_wrapper_cleans_up_after_the_cdecl_parser_it_forwards_to(self, patched):
        """Four arguments forwarded, sixteen bytes reclaimed. A wrong `add esp` here unbalances
        the INI reader's stack for the rest of the file."""
        body = routine(patched, "dep_parse")
        pushes = [i for i in body if i.mnemonic == "push" and i.op_str.startswith("dword")]
        cleanups = [i for i in body if i.mnemonic == "add" and i.op_str.startswith("esp")]
        assert len(pushes) == 4
        assert [i.op_str for i in cleanups] == ["esp, 0x10"]

    def test_the_grant_reads_it_as_a_word(self, patched):
        """A dword load at +0x22 reads two bytes of whatever follows the allocation."""
        loads = [i for i in routine(patched, "grant") if i.mnemonic == "movzx"]
        assert [i.op_str for i in loads] == [f"eax, word ptr [eax + 0x{sr.DEPOSIT_OFFSET:x}]"]

    def test_the_constructor_clears_all_four_bytes_it_now_owns(self, patched):
        """The field table gives the field a *name*, not a default: `operator new` does not zero
        the block. The two `Bool` stores become one dword store, which is what makes
        `DepositAmount2 = 0` true for a module that never mentions it."""
        off = va_to_offset(patched, AUTO_DEPOSIT_MODULE_DATA_CTOR_BOOLS)
        window = len(AUTO_DEPOSIT_MODULE_DATA_CTOR_BOOLS_BYTES)
        assert bytes(patched[off : off + 3]) == bytes.fromhex("895e20")  # mov [esi+0x20], ebx
        assert bytes(patched[off + 3 : off + window]) == b"\x90" * (window - 3)


class TestTheFieldTables:
    def test_every_field_is_added(self, patched):
        bases = SecondResourcePatch._resolve(patched)  # noqa: SLF001
        for spec, table_va in zip(sr._TABLES, bases, strict=True):  # noqa: SLF001
            names = [name_of(patched, e) for e in read_field_table(patched, table_va)]
            assert names[-1] == spec.field, spec.block

    def test_start_money_uses_the_cave_parser_and_writes_nothing_into_the_template(self, patched):
        """Offset 0 is the whole storage argument: `PlayerTemplate` is `0x1DC` bytes with no hole
        - +0x34 is the `Money` subobject's own `m_playerIndex`, not padding - and a parse-time
        `this` is a stack temporary anyway."""
        template_va = SecondResourcePatch._resolve(patched)[1]  # noqa: SLF001
        table = read_field_table(patched, template_va)
        entry = next(e for e in table if name_of(patched, e) == sr.START_FIELD)
        assert (entry[1], entry[2], entry[3]) == (labels(patched)["parse"], 0, 0)

    def test_the_stock_entries_pass_through_untouched(self, image, patched):
        before_bases = SecondResourcePatch._resolve(image)  # noqa: SLF001
        after_bases = SecondResourcePatch._resolve(patched)  # noqa: SLF001
        for old, new in zip(before_bases, after_bases, strict=True):
            before = read_field_table(image, old)
            assert read_field_table(patched, new)[: len(before)] == before

    def test_every_table_moved_out_of_read_only_memory(self, image, patched):
        before = SecondResourcePatch._resolve(image)  # noqa: SLF001
        after = SecondResourcePatch._resolve(patched)  # noqa: SLF001
        assert before[:2] == (AUTO_DEPOSIT_FIELD_TABLE, PLAYER_TEMPLATE_FIELD_TABLE)
        assert not set(before) & set(after)


class TestTheHooks:
    @pytest.mark.parametrize(
        ("site", "window", "resume", "label"),
        [
            (
                PLAYER_TEMPLATE_BLOCK_KEY_EARLY,
                PLAYER_TEMPLATE_BLOCK_KEY_EARLY_BYTES,
                PLAYER_TEMPLATE_BLOCK_KEY_EARLY_RESUME,
                "block",
            ),
            (PLAYER_INIT_ENTRY, PLAYER_INIT_ENTRY_BYTES, PLAYER_INIT_ENTRY_RESUME, "init"),
            (
                AUTO_DEPOSIT_DEPOSIT,
                AUTO_DEPOSIT_DEPOSIT_BYTES,
                AUTO_DEPOSIT_DEPOSIT_RESUME,
                "grant",
            ),
            (PALANTIR_RESOURCES, PALANTIR_RESOURCES_BYTES, PALANTIR_RESOURCES_RESUME, "text"),
            (
                PALANTIR_RESOURCES_CACHE,
                PALANTIR_RESOURCES_CACHE_BYTES,
                PALANTIR_RESOURCES_CACHE_PUSH,
                "refresh",
            ),
        ],
    )
    def test_each_site_is_a_jump_to_its_routine_padded_with_nops(
        self, patched, site, window, resume, label
    ):
        off = va_to_offset(patched, site)
        target = struct.unpack_from("<i", patched, off + 1)[0] + site + 5
        assert patched[off] == 0xE9
        assert target == labels(patched)[label]
        assert bytes(patched[off + 5 : off + len(window)]) == b"\x90" * (len(window) - 5)
        assert resume == site + len(window), "the resume point must be the end of the window"

    def test_the_grant_still_makes_the_deposit_it_displaced(self, patched):
        """The hook replaces a whole `call Money::deposit`. Losing it would stop every income in
        the game - and the patch would still verify, because nothing else reads that call."""
        calls = [i for i in routine(patched, "grant") if i.mnemonic == "call"]
        assert [int(i.op_str, 16) for i in calls] == [MONEY_DEPOSIT]

    def test_the_block_key_hook_does_not_touch_command_point_upkeeps(self):
        """Both patches need the same value out of the same prologue, so they take neighbouring
        windows rather than the same one - which is what lets `apply_byte_patch` stay a guard
        instead of a collision."""
        mine = range(
            PLAYER_TEMPLATE_BLOCK_KEY_EARLY,
            PLAYER_TEMPLATE_BLOCK_KEY_EARLY + len(PLAYER_TEMPLATE_BLOCK_KEY_EARLY_BYTES),
        )
        theirs = range(
            PLAYER_TEMPLATE_BLOCK_KEY,
            PLAYER_TEMPLATE_BLOCK_KEY + len(PLAYER_TEMPLATE_BLOCK_KEY_BYTES),
        )
        assert not set(mine) & set(theirs)
        assert PLAYER_TEMPLATE_BLOCK_KEY_EARLY_RESUME == PLAYER_TEMPLATE_BLOCK_KEY


class TestThePoolArithmetic:
    def test_the_seed_assigns_rather_than_accumulates(self, patched):
        """`Player::init` runs more than once per process. Adding would carry the previous game's
        balance forward, which is the bug the hook exists to prevent."""
        stores = [
            i for i in routine(patched, "init") if i.mnemonic in {"mov", "add"} and "*4" in i.op_str
        ]
        assert [i.mnemonic for i in stores] == ["mov"]

    def test_the_grant_accumulates(self, patched):
        writes = [i for i in routine(patched, "grant") if "*4" in i.op_str]
        assert [i.mnemonic for i in writes] == ["add", "mov"], "an add, then the saturating clamp"

    def test_the_grant_saturates_instead_of_wrapping(self, patched):
        """A long game with a large `DepositAmount2` would otherwise wrap a player's balance
        back to nearly nothing, which reads as a bug rather than as a cap."""
        clamps = [
            i for i in routine(patched, "grant") if i.mnemonic == "mov" and "0xffffffff" in i.op_str
        ]
        assert len(clamps) == 1

    @pytest.mark.parametrize("label", ["init", "grant"])
    def test_every_index_into_the_pool_is_bounds_checked(self, patched, label):
        """The pool is a fixed array in a cave: an out-of-range `m_playerIndex` would write into
        the code that follows it."""
        cmps = [
            i
            for i in routine(patched, label)
            if i.mnemonic == "cmp" and i.op_str.endswith(f"0x{MAX_PLAYER_COUNT:x}")
        ]
        assert len(cmps) == 1
        assert any(i.mnemonic == "jae" for i in routine(patched, label)), "unsigned, so -1 fails"


class TestTheBracket:
    """`APT:PalantirResources` is engine-formatted text, not a numeric binding, so a second
    number goes in the same string the engine already overwrites every refresh - no `.apt` edit
    and no `.csf` edit. This is `command-point-upkeep`'s trick on the other readout."""

    def test_the_format_carries_two_numbers_and_brackets_the_second(self):
        assert sr.FORMAT.count("%d") == 2
        assert sr.FORMAT == "%d (%d)"

    def test_the_format_string_is_8_bit_and_terminated(self, patched):
        """The resource text is an `AsciiString`, unlike the command-point one - a UTF-16 literal
        here would format as a single stray character."""
        _va, off, _vsize = find_section(patched, sr.SECTION_NAME)
        raw = bytes(patched[off + sr._FMT_OFF :])  # noqa: SLF001
        assert raw[: raw.index(b"\x00")].decode("ascii") == sr.FORMAT

    def test_the_cleanup_counts_both_varargs(self, patched):
        """`AsciiString::format` is cdecl, so the caller reclaims. The stock call pushes three
        dwords and reclaims 0xC; a second vararg makes that four and 0x10."""
        body = routine(patched, "text")
        cleanups = [i for i in body if i.mnemonic == "add" and i.op_str.startswith("esp")]
        assert [i.op_str for i in cleanups] == ["esp, 0x10"]

    def test_the_seh_state_is_written_on_every_path(self, patched):
        """`[ebp-4]` marks the `AsciiString` at `[ebp-0x10]` constructed for the unwinder. It is
        one of the two displaced instructions, and unlike the compare it must run on both edges -
        so it is emitted before the branch, not duplicated after it."""
        stores = [
            i for i in routine(patched, "text") if i.mnemonic == "mov" and "ebp - 4" in i.op_str
        ]
        assert len(stores) == 1
        assert stores[0].address == labels(patched)["text"], "before any branch"

    def test_the_displaced_compare_runs_last_on_the_stock_path(self, patched):
        """The resume address is the engine's own `jl`, so the flags it reads have to be the ones
        this compare sets - which means re-executing it immediately before the jump back."""
        body = routine(patched, "text")
        tail = body[-2:]
        assert tail[0].mnemonic == "cmp" and tail[0].op_str == "dword ptr [ebp + 8], 0"
        assert tail[1].mnemonic == "jmp"
        assert int(tail[1].op_str, 16) == PALANTIR_RESOURCES_RESUME

    def test_the_fast_path_rejoins_at_the_setvalue(self, patched):
        jumps = [int(i.op_str, 16) for i in routine(patched, "text") if i.mnemonic == "jmp"]
        assert PALANTIR_RESOURCES_DONE in jumps

    def test_the_refresh_filter_keeps_both_stock_edges(self, patched):
        """Widening the filter must not lose either of the engine's own answers: unchanged means
        no text this frame, changed means push it."""
        jumps = [int(i.op_str, 16) for i in routine(patched, "refresh") if i.mnemonic == "jmp"]
        assert PALANTIR_RESOURCES_CACHE_SKIP in jumps
        assert PALANTIR_RESOURCES_CACHE_PUSH in jumps

    def test_the_refresh_forces_a_push_when_only_the_second_number_moved(self, patched):
        """Without this the bracket shows whatever it said the last time *gold* changed."""
        body = routine(patched, "refresh")
        assert any(i.mnemonic == "call" for i in body), "it reads the pool"
        assert any(i.mnemonic == "mov" and i.op_str.endswith(", eax") for i in body), "and caches"

    @pytest.mark.parametrize("label", ["text", "refresh"])
    def test_every_hud_path_is_gated_on_the_in_use_flag(self, patched, label):
        """A mod that never mentions either field must get the stock readout, byte for byte."""
        _va, off, _vsize = find_section(patched, sr.SECTION_NAME)
        section_va, _o, _v = find_section(patched, sr.SECTION_NAME)
        gate = f"[0x{section_va + sr._INUSE_OFF:x}], 0"  # noqa: SLF001
        assert any(i.mnemonic == "cmp" and gate in i.op_str for i in routine(patched, label))

    def test_the_flag_is_raised_at_ini_load_not_from_the_pool(self, patched):
        """Deciding the readout's shape from the pool would make it appear and vanish mid-game.
        Both parse functions raise it; nothing in the per-frame paths writes it."""
        section_va, _off, _vsize = find_section(patched, sr.SECTION_NAME)
        flag = f"0x{section_va + sr._INUSE_OFF:x}"  # noqa: SLF001
        writers = {
            name
            for name in ROUTINES
            if any(
                i.mnemonic == "mov" and flag in i.op_str and i.op_str.endswith(", 1")
                for i in routine(patched, name)
            )
        }
        assert writers == {"parse", "dep_parse", "cost_parse"}


@pytest.fixture(scope="module")
def plain(image: bytearray) -> bytes:
    """The `--no-hud` build: the mechanic, without either palantir hook."""
    data = bytearray(image)
    SecondResourcePatch(hud=False).apply(data)
    return bytes(data)


class TestTheNoHudBuild:
    def test_it_applies_and_verifies(self, plain):
        assert SecondResourcePatch(hud=False).verify(plain) == []

    def test_it_leaves_both_palantir_sites_stock(self, plain):
        for site, window in (
            (PALANTIR_RESOURCES, PALANTIR_RESOURCES_BYTES),
            (PALANTIR_RESOURCES_CACHE, PALANTIR_RESOURCES_CACHE_BYTES),
        ):
            off = va_to_offset(plain, site)
            assert bytes(plain[off : off + len(window)]) == window

    def test_the_mechanic_is_unchanged(self, plain, patched):
        """`--no-hud` drops the display, not the resource: both builds hook the same three
        mechanic sites."""
        for site in (PLAYER_TEMPLATE_BLOCK_KEY_EARLY, PLAYER_INIT_ENTRY, AUTO_DEPOSIT_DEPOSIT):
            assert plain[va_to_offset(plain, site)] == 0xE9
            assert patched[va_to_offset(patched, site)] == 0xE9

    def test_verify_tells_the_two_builds_apart(self, plain, patched):
        assert SecondResourcePatch(hud=True).verify(plain)
        assert SecondResourcePatch(hud=False).verify(patched)

    def test_detect_recovers_which_half_was_built(self, plain, patched):
        assert SecondResourcePatch.detect(plain).hud is False
        assert SecondResourcePatch.detect(patched).hud is True


class TestApplyAndVerify:
    def test_apply_then_verify(self, patched):
        assert SecondResourcePatch().verify(patched) == []

    def test_verify_rejects_an_unpatched_file(self, image):
        assert SecondResourcePatch().verify(image)

    def test_detect_finds_it_only_when_it_is_there(self, image, patched):
        assert SecondResourcePatch.detect(image) is None
        assert SecondResourcePatch.detect(patched) is not None

    def test_applying_twice_raises(self, patched):
        """The second run reads its own rebuilt table, sees the fields already there, and stops -
        rather than installing a second copy of both."""
        with pytest.raises(ValueError, match="already names"):
            SecondResourcePatch().apply(bytearray(patched))

    def test_the_wrong_build_is_refused(self, image):
        """A table that does not put `DepositAmount` where these offsets came from is not the
        build they were derived against, whatever else it looks like."""
        data = bytearray(image)
        table = va_to_offset(data, AUTO_DEPOSIT_FIELD_TABLE)
        struct.pack_into("<I", data, table + 2 * 16 + 12, 0x99)  # DepositAmount's offset
        with pytest.raises(ValueError, match="unexpected build"):
            SecondResourcePatch().apply(data)

    def test_the_ini_surface_names_every_field(self):
        surface = SecondResourcePatch().ini_surface()
        assert {(f.block, f.name, f.type, f.default) for f in surface.fields} == {
            ("AutoDepositUpdate", "DepositAmount2", "Int", 0),
            ("PlayerTemplate", "StartMoney2", "Int", 0),
            ("Object", "BuildCost2", "Int", 0),
        }

    def test_the_defaults_are_the_stock_behaviour(self):
        """Both fields default to 0 - no second income, and none to start with - so a mod that
        never mentions them runs on a patched binary exactly as it does today."""
        assert all(f.default == 0 for f in SecondResourcePatch().ini_surface().fields)


class TestComposition:
    """`command-point-upkeep` is the one bundled patch this shares a *structure* with: both need
    a `PlayerTemplate` block key and both rebuild the `PlayerTemplate` field table."""

    @pytest.mark.parametrize("order", list(itertools.permutations([0, 1])))
    def test_both_orders_apply_and_verify(self, image, order):
        patches = [SecondResourcePatch(), CommandPointUpkeepPatch()]
        data = bytearray(image)
        for index in order:
            patches[index].apply(data)
        for patch in patches:
            assert patch.verify(data) == [], f"{patch.name} after {order}"

    @pytest.mark.parametrize("order", list(itertools.permutations([0, 1])))
    def test_the_live_table_carries_every_field_both_patches_added(self, image, order):
        """The second patch to run rebuilds the first one's table by pointer, so its rows survive
        with their own parse functions - which is the whole reason either patch reads the table
        live instead of from its stock address."""
        patches = [SecondResourcePatch(), CommandPointUpkeepPatch()]
        data = bytearray(image)
        for index in order:
            patches[index].apply(data)
        template_va = SecondResourcePatch._resolve(data)[1]  # noqa: SLF001
        names = [name_of(data, e) for e in read_field_table(data, template_va)]
        assert {"StartMoney2", "UpkeepCommandPointStep", "UpkeepValues"} <= set(names)


class TestTheCost:
    """Phase 2: `Object.BuildCost2`, the gate that refuses it and the withdrawal that takes it."""

    def test_the_field_is_stored_in_the_cave_not_on_the_template(self, patched):
        """`ThingTemplate` has no hole. The 2-byte gap at +0x5E8 that looks like one is the
        template's engine-assigned id - a down-counting global, a dedicated setter and ~15
        readers - so a table entry offset of 0 is the whole storage argument."""
        object_va = SecondResourcePatch._resolve(patched)[2]  # noqa: SLF001
        table = read_field_table(patched, object_va)
        entry = next(e for e in table if name_of(patched, e) == sr.COST_FIELD)
        assert entry[3] == 0
        assert entry[1] == labels(patched)["cost_parse"]

    def test_the_parser_keys_on_instance_rather_than_store(self, patched):
        """`store` is `instance + offset + whatever extra offset the block was registered with`;
        only `instance` is guaranteed to be the `ThingTemplate` itself."""
        loads = [
            i
            for i in routine(patched, "cost_parse")
            if i.mnemonic == "mov" and i.op_str.startswith("ecx, dword ptr [ebp")
        ]
        assert loads[0].op_str == "ecx, dword ptr [ebp + 0xc]", "the instance, not [ebp+0x10]"

    def test_the_pointer_key_drops_its_dead_bits(self, patched):
        """Templates are 4-byte aligned and allocated far apart, so folding the raw pointer
        would pile every one of them into a handful of slots."""
        shifts = [i for i in routine(patched, "cost_row") if i.mnemonic == "shr"]
        assert [i.op_str for i in shifts] == ["eax, 4"]

    def test_the_cost_rides_an_override(self, patched):
        """An INI override block is parsed into a *fresh* template copied from the old one, and
        the copy is field by field - so anything keyed on the pointer is lost without this."""
        off = va_to_offset(patched, THING_TEMPLATE_COPY_ID)
        assert patched[off] == 0xE9
        target = struct.unpack_from("<i", patched, off + 1)[0] + THING_TEMPLATE_COPY_ID + 5
        assert target == labels(patched)["cost_copy"]
        tail = routine(patched, "cost_copy")[-2:]
        assert tail[0].mnemonic == "mov" and "0x5e8" in tail[0].op_str, "the displaced id copy"
        assert int(tail[1].op_str, 16) == THING_TEMPLATE_COPY_ID_RESUME

    def test_the_copy_hook_shares_no_byte_with_hero_manas(self):
        """`hero-mana` rides the same copy from its *call site*; this is the body. Hooking the
        body also covers any caller that is not that one call."""
        mine = range(
            THING_TEMPLATE_COPY_ID, THING_TEMPLATE_COPY_ID + len(THING_TEMPLATE_COPY_ID_BYTES)
        )
        theirs = range(
            THING_TEMPLATE_COPY_CALL, THING_TEMPLATE_COPY_CALL + len(THING_TEMPLATE_COPY_CALL_BYTES)
        )
        assert not set(mine) & set(theirs)

    def test_the_gate_keeps_both_stock_edges(self, patched):
        """Refusal reuses the engine's own "not enough money" code, so the button tint, the
        sound and the message are the ones the player already knows."""
        body = routine(patched, "gate")
        jumps = [int(i.op_str, 16) for i in body if i.mnemonic == "jmp"]
        assert BUILD_GATE_AFFORD_OK in jumps
        assert BUILD_GATE_AFFORD_REFUSE in jumps
        pushes = [i for i in body if i.mnemonic == "push" and i.op_str == "2"]
        assert len(pushes) == 1, "the engine's own not-enough-money code, pushed once"

    def test_the_gate_runs_the_displaced_gold_test_first(self, patched):
        """Short of gold is still short of gold: the stock answer must not depend on the new
        pool, and must not read it."""
        head = routine(patched, "gate")[:2]
        assert head[0].mnemonic == "cmp" and head[0].op_str == "eax, ebx"
        assert head[1].mnemonic == "ja", "short of gold -> straight to the refusal"

    def test_an_unpriced_object_never_reads_the_pool(self, patched):
        """A cost of 0 is the default and the AI's whole story: its unit variants leave
        `BuildCost2` unset, so the gate short-circuits before it looks at anything."""
        body = routine(patched, "gate")
        cost = next(i for i in body if i.mnemonic == "call")
        pool = next(i for i in body if "*4" in i.op_str)
        test = next(i for i in body if i.mnemonic == "test" and i.address > cost.address)
        assert test.address < pool.address, "the zero test comes before the pool read"

    def test_the_gate_treats_an_unaddressable_pool_as_broke(self, patched):
        """Never as free. An out-of-range `m_playerIndex` must not become a discount."""
        body = routine(patched, "gate")
        bound = next(i for i in body if i.mnemonic == "cmp" and i.op_str.endswith("0x14"))
        guard = next(i for i in body if i.mnemonic == "jae" and i.address > bound.address)
        refuse = next(i for i in body if i.mnemonic == "push" and i.op_str == "2")
        assert int(guard.op_str, 16) < refuse.address + 8, "the guard lands on the refusal"

    def test_the_spend_still_makes_the_withdrawal_it_displaced(self, patched):
        """The hook replaces a whole `call Money::withdraw`. Losing it would make everything
        free - and the patch would still verify."""
        calls = [i for i in routine(patched, "spend") if i.mnemonic == "call"]
        assert int(calls[0].op_str, 16) == MONEY_WITHDRAW

    def test_the_spend_clamps_at_zero_rather_than_wrapping(self, patched):
        """`Money::withdraw` takes what is there and never refuses, so affordability is decided
        upstream - and a debit that arrives anyway must not wrap a UInt32 into four billion."""
        body = routine(patched, "spend")
        assert any(i.mnemonic == "cmp" and "*4" in i.op_str for i in body), "compare with the pool"
        assert any(i.mnemonic == "jbe" for i in body)
        assert any(i.mnemonic == "sub" and "*4" in i.op_str for i in body)

    def test_a_negative_cost_is_free_rather_than_a_fortune(self, patched):
        body = routine(patched, "cost_parse")
        assert any(i.mnemonic == "jge" for i in body)
        assert any(i.mnemonic == "xor" and i.op_str == "eax, eax" for i in body)


class TestCostComposition:
    """`hero-mana` is the other patch that rebuilds the `Object` field table."""

    @pytest.mark.parametrize("order", list(itertools.permutations([0, 1])))
    def test_it_composes_with_hero_mana(self, image, order):
        patches = [SecondResourcePatch(), HeroManaPatch()]
        data = bytearray(image)
        for index in order:
            patches[index].apply(data)
        for patch in patches:
            assert patch.verify(data) == [], f"{patch.name} after {order}"

    @pytest.mark.parametrize("order", list(itertools.permutations([0, 1])))
    def test_the_live_object_table_carries_both_patches_fields(self, image, order):
        patches = [SecondResourcePatch(), HeroManaPatch()]
        data = bytearray(image)
        for index in order:
            patches[index].apply(data)
        object_va = SecondResourcePatch._resolve(data)[2]  # noqa: SLF001
        names = [name_of(data, e) for e in read_field_table(data, object_va)]
        assert {"BuildCost2", "ManaPool", "ManaRegen"} <= set(names)


class TestTheCostBracket:
    """The secondary cost in brackets after the real one: ``Cost: 100 (25)``."""

    def test_the_suffix_is_utf16_and_terminated(self, patched):
        """A description is `UnicodeString`s all the way down, unlike the palantir's 8-bit
        resource text - an ASCII literal here would format as one stray character."""
        _va, off, _vsize = find_section(patched, sr.SECTION_NAME)
        raw = bytes(patched[off + sr._SUFFIX_OFF :])  # noqa: SLF001
        units = [raw[i : i + 2] for i in range(0, len(raw) - 1, 2)]
        assert b"".join(units[: units.index(b"\x00\x00")]).decode("utf-16-le") == sr.SUFFIX

    def test_it_appends_rather_than_rebuilding_the_line(self, patched):
        """The `Cost:` label is the mod's own localized `.csf` string. Appending to what the
        engine produced is what keeps it - and is why this needs no `.csf` edit."""
        body = routine(patched, "tip")
        calls = [
            int(i.op_str, 16) for i in body if i.mnemonic == "call" and i.op_str.startswith("0x")
        ]
        assert UNICODE_STRING_CONCAT in calls, "concatenated onto the engine's own line"

    def test_the_temporary_string_is_destroyed(self, patched):
        """`UnicodeString::format` allocates. Skipping the destructor leaks once per tooltip
        refresh, which is per frame while the cursor sits on a button."""
        body = routine(patched, "tip")
        calls = [
            int(i.op_str, 16) for i in body if i.mnemonic == "call" and i.op_str.startswith("0x")
        ]
        assert calls.count(UNICODE_STRING_DTOR) == 1

    def test_nothing_is_constructed_when_the_cost_is_zero(self, patched):
        """The default. An object that never names `BuildCost2` must get the stock line with no
        allocation at all."""
        body = routine(patched, "tip")
        test = next(i for i in body if i.mnemonic == "test" and i.op_str == "eax, eax")
        fmt = next(
            i
            for i in body
            if i.mnemonic == "call"
            and i.op_str.startswith("0x")
            and int(i.op_str, 16) == UNICODE_STRING_FORMAT
        )
        assert test.address < fmt.address

    def test_the_line_pointer_survives(self, patched):
        """`eax` is what the displaced pushes hand to the concatenation. Clobbering it would
        push whatever the suffix machinery left behind."""
        body = routine(patched, "tip")
        assert body[3].mnemonic == "push" and body[3].op_str == "eax"
        restores = [i for i in body if i.mnemonic == "pop" and i.op_str == "eax"]
        assert len(restores) == 1

    @pytest.mark.parametrize(
        ("site", "resume", "label", "register"),
        [
            (TOOLTIP_COST_BUILD, TOOLTIP_COST_BUILD_RESUME, "tip_build", "ebx"),
            (TOOLTIP_COST_REVIVE, TOOLTIP_COST_REVIVE_RESUME, "tip_revive", "esi"),
        ],
    )
    def test_each_site_reads_the_template_from_its_own_register(
        self, patched, site, resume, label, register
    ):
        """The two cost lines differ only in where the template is, which is why each is a stub
        in front of one shared body."""
        off = va_to_offset(patched, site)
        assert patched[off] == 0xE9
        target = struct.unpack_from("<i", patched, off + 1)[0] + site + 5
        assert target == labels(patched)[label]
        body = routine(patched, label)
        assert body[1].mnemonic == "mov" and body[1].op_str == f"ecx, {register}"
        assert int(body[-1].op_str, 16) == resume

    def test_the_no_hud_build_leaves_both_cost_lines_stock(self, plain):
        for site in (TOOLTIP_COST_BUILD, TOOLTIP_COST_REVIVE):
            off = va_to_offset(plain, site)
            assert bytes(plain[off : off + len(TOOLTIP_COST_BYTES)]) == TOOLTIP_COST_BYTES
