"""Tests for the unit-plate-option patch.

The cave is hand-assembled x86 that cannot be executed here, so the load-bearing tests read it
back: every hook has to restore the instructions it displaced and return to the byte after them,
every absolute target has to be an address this patch means to reach, and the preference reader has
to be the engine's own accessor with one literal swapped. None of that raises when it is wrong - it
crashes the game, or silently answers for the wrong thing.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    APT_INIT_GADGETS_EPILOGUE,
    APT_INIT_GADGETS_LADDER,
    APT_INIT_GADGETS_LADDER_HOOK,
    APT_INIT_GADGETS_LADDER_HOOK_BYTES,
    APT_INIT_GADGETS_RESOLUTION_ARM,
    APT_OPTIONS_SAVE,
    APT_OPTIONS_SAVE_FLUSH,
    APT_OPTIONS_SAVE_FLUSH_BYTES,
    APT_OPTIONS_SAVE_RESUME,
    ASCII_STRING_CTOR,
    ASCII_STRING_DTOR,
    ASCII_STRING_SET,
    EMPTY_STRING,
    GET_CHECKBOX_STATE,
    MODEL_FIELD_PARSER,
    MODEL_FIELD_STORE,
    MODEL_FIELD_STORE_BYTES,
    MODEL_FIELD_STORE_RESUME,
    MODEL_FIELD_TABLE_ROW,
    OPTION_PREFERENCES_CTOR,
    OPTION_PREFERENCES_DTOR,
    OPTION_PREFERENCES_GET_BOOL_BYTES,
    PREFERENCES_MAP_FIND,
    PREFERENCES_MAP_INDEX,
    SET_CHECKBOX_STATE,
    STRICMP,
    USER_PREFERENCES_WRITE,
    YES_STRING,
)
from sage_patch.patcher import apply_patches
from sage_patch.patches.experimental.unit_plate_option import (
    ANCHORS,
    DEFAULT_GADGET,
    DEFAULT_KEY,
    DEFAULT_MODEL,
    SECTION_NAME,
    UnitPlateOptionPatch,
    _literals,
    build_cave,
)
from sage_patch.utils import align_up, find_section, va_to_offset

BASE = 0x400000
CAVE_VA = 0x00ED3000

#: `AptOptions::InitGadgets`, whose ladder entry branch the row hook takes over.
APT_INIT_GADGETS = 0x009205C4

#: Every engine address the cave is entitled to reach. A target outside this set (or outside the
#: cave itself) means an emitter pointed somewhere it did not mean to.
REACHABLE = {
    STRICMP,
    ASCII_STRING_CTOR,
    ASCII_STRING_DTOR,
    ASCII_STRING_SET,
    PREFERENCES_MAP_FIND,
    PREFERENCES_MAP_INDEX,
    OPTION_PREFERENCES_CTOR,
    OPTION_PREFERENCES_DTOR,
    SET_CHECKBOX_STATE,
    GET_CHECKBOX_STATE,
    USER_PREFERENCES_WRITE,
    MODEL_FIELD_STORE_RESUME,
    APT_INIT_GADGETS_RESOLUTION_ARM,
    APT_INIT_GADGETS_LADDER,
    APT_INIT_GADGETS_EPILOGUE,
    APT_OPTIONS_SAVE_RESUME,
}

_HOOK_SITES = (
    (MODEL_FIELD_STORE, MODEL_FIELD_STORE_BYTES),
    (APT_INIT_GADGETS_LADDER_HOOK, APT_INIT_GADGETS_LADDER_HOOK_BYTES),
    (APT_OPTIONS_SAVE_FLUSH, APT_OPTIONS_SAVE_FLUSH_BYTES),
)


def _game_dat(base: int = BASE) -> bytearray:
    """A PE32 image carrying the stock bytes this patch checks and rewrites, at their real file
    offsets, so apply + verify run without the copyrighted `game.dat`. Raw offset equals RVA
    throughout, as it does in the real binary."""
    highest = max(va - base + len(want) for va, want in ANCHORS.items())
    highest = max(highest, *(va - base + len(b) for va, b in _HOOK_SITES))
    data = bytearray(align_up(highest + 0x1000, 0x200))
    data[0:2] = b"MZ"

    e = 0x80
    struct.pack_into("<I", data, 0x3C, e)  # e_lfanew
    data[e : e + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, e + 4, 0x14C)  # Machine (i386)
    struct.pack_into("<H", data, e + 6, 1)  # NumberOfSections
    struct.pack_into("<H", data, e + 20, 0xE0)  # SizeOfOptionalHeader
    opt = e + 24
    struct.pack_into("<H", data, opt, 0x10B)  # PE32 magic
    struct.pack_into("<I", data, opt + 28, base)  # ImageBase
    struct.pack_into("<I", data, opt + 32, 0x1000)  # SectionAlignment
    struct.pack_into("<I", data, opt + 36, 0x200)  # FileAlignment
    struct.pack_into("<I", data, opt + 56, 0x2000000)  # SizeOfImage (append_section recomputes)
    struct.pack_into("<I", data, opt + 60, 0x400)  # SizeOfHeaders (room for more section headers)
    sectab = opt + 0xE0
    hdr = bytearray(40)
    hdr[0:8] = b".text\x00\x00\x00"
    span = len(data) - 0x1000
    struct.pack_into("<IIII", hdr, 8, span, 0x1000, span, 0x1000)  # vsize, rva, rawsize, praw
    data[sectab : sectab + 40] = hdr

    for va, want in ANCHORS.items():
        data[va - base : va - base + len(want)] = want
    for va, want in _HOOK_SITES:
        data[va - base : va - base + len(want)] = want
    return data


def _cave_bytes(data: bytes | bytearray) -> tuple[int, bytes]:
    """The cave's ``(base virtual address, bytes)``."""
    located = find_section(data, SECTION_NAME)
    assert located is not None
    va, off, size = located
    return va, bytes(data[off : off + size])


def _entry(model: str = DEFAULT_MODEL, key: str = DEFAULT_KEY, gadget: str = DEFAULT_GADGET) -> int:
    """The offset of the first instruction, past the data block."""
    return len(_literals(model, key, gadget)[0])


def _branch_targets(cave: bytes, base_va: int) -> set[int]:
    """Every `call rel32` / `jmp rel32` target the disassembler finds in the cave's code."""
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    start = _entry()
    out: set[int] = set()
    for ins in md.disasm(cave[start:], base_va + start):
        for group in ins.groups:
            if ins.group_name(group) in {"jump", "call"}:
                for op in ins.operands:
                    if op.type == capstone.x86.X86_OP_IMM:
                        out.add(op.imm)
    return out


def _calls_between(a, cave: bytes, start: str, end: str) -> set[int]:
    """`call rel32` targets between two labels of a laid-out cave."""
    lo, hi = a.label_va(start) - CAVE_VA, a.label_va(end) - CAVE_VA
    return {
        CAVE_VA + i + 5 + struct.unpack_from("<i", cave, i + 1)[0]
        for i in range(lo, hi - 4)
        if cave[i] == 0xE8
    }


def test_literals_are_nul_terminated_and_aligned() -> None:
    blob, at = _literals(DEFAULT_MODEL, DEFAULT_KEY, DEFAULT_GADGET)
    assert len(blob) % 4 == 0
    assert blob[:12] == bytes(12), "state, gadget and owner all start zeroed"
    assert blob[at["model"] :].startswith(b"unit_plate\x00")
    assert blob[at["none"] :].startswith(b"None\x00")
    assert blob[at["key"] :].startswith(b"ShowUnitPlates\x00")
    assert blob[at["gadget"] :].startswith(b"Options::UnitPlates\x00")
    assert blob[at["yes"] :].startswith(b"yes\x00")
    assert blob[at["no"] :].startswith(b"no\x00")


def test_none_is_spelled_as_the_remover_inc_spells_it() -> None:
    """The substituted name has to be the one 78 shipped child objects already carry - that is
    the whole argument that the `off` state is not new engine behaviour."""
    blob, at = _literals(DEFAULT_MODEL, DEFAULT_KEY, DEFAULT_GADGET)
    assert blob[at["none"] : at["none"] + 5] == b"None\x00"


def test_code_starts_immediately_after_the_data_block() -> None:
    """The cave emits its data into the same `Asm` as its code, so the `Asm`'s base has to be the
    section base. Getting that wrong shifts every absolute target by the data block's length, and
    the patch still applies, verifies and detects clean."""
    a = build_cave(CAVE_VA)
    assert a.label_va("model") == CAVE_VA + _entry()
    assert a.finish()[: _entry()] == _literals(DEFAULT_MODEL, DEFAULT_KEY, DEFAULT_GADGET)[0]


def test_every_branch_leaves_for_somewhere_this_patch_means_to_reach() -> None:
    """The general form of the check above: no `call` or `jmp` may land outside the cave except on
    one of the engine addresses this patch documents."""
    cave = build_cave(CAVE_VA).finish()
    inside = range(CAVE_VA, CAVE_VA + len(cave))
    for target in _branch_targets(cave, CAVE_VA):
        assert target in inside or target in REACHABLE, f"stray branch to {target:#010x}"


def test_each_engine_helper_is_actually_reached() -> None:
    """The complement: every address the docstring claims is reached really is."""
    targets = _branch_targets(build_cave(CAVE_VA).finish(), CAVE_VA)
    for va in REACHABLE:
        assert va in targets, f"{va:#010x} is documented but never reached"


def test_model_hook_restores_both_displaced_instructions() -> None:
    """Six bytes are lifted; the cave has to put both instructions back and resume at the byte
    after them, or the parser stores an `AsciiString` built from nothing."""
    a = build_cave(CAVE_VA)
    cave = a.finish()
    at = a.label_va("model_keep") - CAVE_VA
    assert cave[at] == 0x61, "the decision runs under pushad/popad"
    assert cave[at + 1 : at + 7] == MODEL_FIELD_STORE_BYTES
    assert cave[at + 7] == 0xE9
    rel = struct.unpack_from("<i", cave, at + 8)[0]
    assert CAVE_VA + at + 7 + 5 + rel == MODEL_FIELD_STORE_RESUME


def test_save_hook_restores_both_displaced_instructions() -> None:
    """Same contract as the model hook, and the reason the insertion goes *in front of* the flush:
    the new key has to be in the map before `UserPreferences::write` runs."""
    a = build_cave(CAVE_VA)
    cave = a.finish()
    at = a.label_va("save_done") - CAVE_VA
    assert cave[at] == 0x61, "popad"
    body = cave[at + 1 :]
    assert body[:2] == b"\x8d\x8d", "lea ecx, [ebp-0x34]"
    assert body[6] == 0xE8, "then the stock call to UserPreferences::write"
    rel = struct.unpack_from("<i", body, 7)[0]
    assert CAVE_VA + at + 1 + 6 + 5 + rel == USER_PREFERENCES_WRITE
    assert body[11] == 0xE9
    rel = struct.unpack_from("<i", body, 12)[0]
    assert CAVE_VA + at + 1 + 11 + 5 + rel == APT_OPTIONS_SAVE_RESUME


def test_arm_re_takes_the_branch_the_hook_displaced() -> None:
    """The ladder hook replaces a `jne` with an unconditional `jmp`, so the cave's first
    instruction has to be that same `jne` - the flags from the `Options::Resolution` compare are
    still live - and the fall-through has to reach the stock Resolution arm."""
    a = build_cave(CAVE_VA)
    cave = a.finish()
    at = a.label_va("arm") - CAVE_VA
    assert cave[at : at + 2] == b"\x0f\x85", "jcc rel32, condition NE"
    assert cave[at + 6] == 0xE9
    rel = struct.unpack_from("<i", cave, at + 7)[0]
    assert CAVE_VA + at + 6 + 5 + rel == APT_INIT_GADGETS_RESOLUTION_ARM

    at = a.label_va("arm_ladder") - CAVE_VA
    assert cave[at] == 0xE9
    rel = struct.unpack_from("<i", cave, at + 1)[0]
    assert CAVE_VA + at + 5 + rel == APT_INIT_GADGETS_LADDER


def test_arm_remembers_the_gadget_and_its_owner() -> None:
    """`Save` reaches the gadget through these two globals, and refuses when the owner is some
    other screen - which is what stops it dereferencing a freed pointer."""
    cave = build_cave(CAVE_VA).finish()
    assert b"\x89\x3d" + struct.pack("<I", CAVE_VA + 8) in cave, "mov [owner], edi"
    assert b"\x89\x35" + struct.pack("<I", CAVE_VA + 4) in cave, "mov [gadget], esi"
    assert b"\xa1" + struct.pack("<I", CAVE_VA + 8) in cave, "mov eax, [owner]"
    assert b"\xa1" + struct.pack("<I", CAVE_VA + 4) in cave, "mov eax, [gadget]"


def test_the_row_reads_fresh_and_the_model_gate_reads_cached() -> None:
    """The checkbox must show the *saved* value, so it cannot come from the launch-time cache; the
    `Model =` parser runs thousands of times, so it must not re-parse `Options.ini` each time."""
    a = build_cave(CAVE_VA)
    cave = a.finish()
    enabled, read_fresh = a.label_va("enabled"), a.label_va("read_fresh")

    assert enabled in _calls_between(a, cave, "model", "model_keep"), (
        "the model gate uses the cache"
    )
    row = _calls_between(a, cave, "arm_mine", "arm_ladder")
    assert read_fresh in row, "the row reads fresh"
    assert enabled not in row


def test_reader_is_the_engine_accessor_with_one_literal_swapped() -> None:
    """`read` is `OptionPreferences::getAllHealthBars` with a different key. Asserting that
    byte-for-byte is the only static check that the map lookup, the miss branch and the `yes`
    comparison were all copied correctly."""
    a = build_cave(CAVE_VA)
    cave = a.finish()
    stock = OPTION_PREFERENCES_GET_BOOL_BYTES
    key_at = stock.index(b"\x68") + 1  # the `push <"AllHealthBars">` immediate

    start = a.label_va("read") - CAVE_VA
    got = cave[start : start + len(stock)]
    assert got[:key_at] == stock[:key_at], "prologue and `mov esi, ecx` differ from the engine's"
    assert got[key_at + 4 : key_at + 7] == stock[key_at + 4 : key_at + 7], "lea ecx,[ebp-4]"
    # The AsciiString ctor call is rel32 and therefore differs; everything after it does not.
    assert got[key_at + 12 :] == stock[key_at + 12 :], "the map lookup preamble differs"

    key_va = struct.unpack_from("<I", cave, start + key_at)[0]
    _blob, at = _literals(DEFAULT_MODEL, DEFAULT_KEY, DEFAULT_GADGET)
    assert key_va == CAVE_VA + at["key"]


def test_cave_falls_back_to_the_empty_string_and_compares_against_yes() -> None:
    cave = build_cave(CAVE_VA).finish()
    assert bytes([0xB8]) + struct.pack("<I", EMPTY_STRING) in cave
    assert bytes([0x68]) + struct.pack("<I", YES_STRING) in cave


def test_apply_verify_detect_round_trip() -> None:
    data = _game_dat()
    patch = UnitPlateOptionPatch()
    patch.apply(data)
    assert patch.verify(data) == []

    recovered = UnitPlateOptionPatch.detect(data)
    assert recovered is not None
    assert (recovered.model, recovered.key, recovered.gadget) == (
        DEFAULT_MODEL,
        DEFAULT_KEY,
        DEFAULT_GADGET,
    )
    assert recovered.verify(data) == []


@pytest.mark.parametrize(("va", "stock"), _HOOK_SITES)
def test_every_hook_site_becomes_a_padded_jmp_into_the_cave(va: int, stock: bytes) -> None:
    data = _game_dat()
    UnitPlateOptionPatch().apply(data)
    off = va_to_offset(data, va)
    assert off is not None
    assert data[off] == 0xE9
    assert bytes(data[off + 5 : off + len(stock)]) == b"\x90" * (len(stock) - 5)
    target = va + 5 + struct.unpack_from("<i", data, off + 1)[0]
    cave_va, cave = _cave_bytes(data)
    assert cave_va <= target < cave_va + len(cave)


def test_parameters_reach_the_cave_and_come_back_out() -> None:
    data = _game_dat()
    patch = UnitPlateOptionPatch(
        model="banner_disc", key="ShowBannerDiscs", gadget="Options::BannerDiscs"
    )
    patch.apply(data)
    _, cave = _cave_bytes(data)
    assert b"banner_disc\x00" in cave
    assert b"ShowBannerDiscs\x00" in cave
    assert b"Options::BannerDiscs\x00" in cave
    assert b"unit_plate\x00" not in cave

    recovered = UnitPlateOptionPatch.detect(data)
    assert recovered is not None
    assert (recovered.model, recovered.key, recovered.gadget) == (
        "banner_disc",
        "ShowBannerDiscs",
        "Options::BannerDiscs",
    )
    assert recovered.verify(data) == []


def test_verify_rejects_a_cave_built_for_a_different_model() -> None:
    data = _game_dat()
    UnitPlateOptionPatch(model="banner_disc").apply(data)
    problems = UnitPlateOptionPatch(model="unit_plate").verify(data)
    assert problems and any("does not hold the cave" in p for p in problems)


def test_apply_refuses_an_image_whose_anchors_moved() -> None:
    for va in ANCHORS:
        data = _game_dat()
        data[va - BASE] ^= 0xFF
        with pytest.raises(ValueError, match="expected bytes"):
            UnitPlateOptionPatch().apply(data)


@pytest.mark.parametrize(("va", "stock"), _HOOK_SITES)
def test_apply_refuses_an_image_whose_hook_site_moved(va: int, stock: bytes) -> None:
    data = _game_dat()
    data[va - BASE : va - BASE + len(stock)] = b"\x90" * len(stock)
    with pytest.raises(ValueError):
        UnitPlateOptionPatch().apply(data)


def test_verify_reports_an_unpatched_image() -> None:
    assert UnitPlateOptionPatch().verify(_game_dat()) == [f"{SECTION_NAME} section is absent"]
    assert UnitPlateOptionPatch.detect(_game_dat()) is None


def test_rejects_a_non_ascii_or_empty_parameter() -> None:
    for kwargs in ({"model": ""}, {"key": ""}, {"gadget": ""}, {"model": "pläte"}):
        with pytest.raises(ValueError, match="non-empty ASCII"):
            UnitPlateOptionPatch(**kwargs)


def test_applies_through_the_driver(tmp_path) -> None:
    src = tmp_path / "game.dat"
    src.write_bytes(bytes(_game_dat()))
    out = tmp_path / "out.dat"
    apply_patches(src, [UnitPlateOptionPatch()], output=out)
    assert UnitPlateOptionPatch().verify(bytearray(out.read_bytes())) == []


_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
class TestInstalledBinary:
    """Against the real binary, which is the only thing that can say the addresses are right.

    The synthetic image round-trips whatever the anchors say; only the shipped `game.dat` can
    confirm that `0x004C21EE` is the `Model =` parser, and that each hook site is whole
    instructions inside its function that nothing jumps into the middle of.
    """

    @pytest.fixture(scope="class")
    def stock(self) -> bytes:
        return _GAME_DAT.read_bytes()

    def test_every_anchor_holds_its_stock_bytes(self, stock) -> None:
        for va, want in ANCHORS.items():
            off = va_to_offset(stock, va)
            assert off is not None, f"{va:#010x} is unmapped"
            assert bytes(stock[off : off + len(want)]) == want, f"{va:#010x} moved"

    @pytest.mark.parametrize(("va", "want"), _HOOK_SITES)
    def test_every_hook_site_holds_its_stock_bytes(self, stock, va: int, want: bytes) -> None:
        off = va_to_offset(stock, va)
        assert off is not None
        assert bytes(stock[off : off + len(want)]) == want

    def test_the_field_table_names_this_parser_model(self, stock) -> None:
        """The check no synthetic image can make: the parser is reached from the
        `ModelConditionState` field table under the name `Model`, so hooking it gates model names
        and nothing else."""
        off = va_to_offset(stock, MODEL_FIELD_TABLE_ROW)
        assert off is not None
        name_ptr, parse, user_data, field_off = struct.unpack_from("<IIII", stock, off)
        assert parse == MODEL_FIELD_PARSER
        assert (user_data, field_off) == (0, 0), "a generic-parser row would carry an offset"
        name_off = va_to_offset(stock, name_ptr)
        assert stock[name_off : name_off + 6] == b"Model\x00"

    def test_the_parser_is_named_only_once(self, stock) -> None:
        """Exactly one dword in the image points at the parser - the field-table row above. A
        second would mean another keyword shares it, and the gate would fire for that one too."""
        hits = list(re.finditer(re.escape(struct.pack("<I", MODEL_FIELD_PARSER)), stock))
        assert len(hits) == 1

    @pytest.mark.parametrize(
        ("hook", "resume", "owner"),
        [
            (MODEL_FIELD_STORE, MODEL_FIELD_STORE_RESUME, MODEL_FIELD_PARSER),
            (APT_INIT_GADGETS_LADDER_HOOK, APT_INIT_GADGETS_RESOLUTION_ARM, APT_INIT_GADGETS),
            (APT_OPTIONS_SAVE_FLUSH, APT_OPTIONS_SAVE_RESUME, APT_OPTIONS_SAVE),
        ],
    )
    def test_each_hook_is_whole_instructions_inside_its_function(
        self, stock, hook: int, resume: int, owner: int
    ) -> None:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        start = va_to_offset(stock, owner)
        boundaries = {ins.address for ins in md.disasm(stock[start : start + 0x900], owner)}
        assert hook in boundaries, "the hook would land mid-instruction"
        assert resume in boundaries, "the return would land mid-instruction"

    @pytest.mark.parametrize(("va", "stock_bytes"), _HOOK_SITES)
    def test_nothing_branches_into_the_displaced_bytes(self, stock, va, stock_bytes) -> None:
        """The bytes may be *landed on* at their first byte, but nothing may branch into their
        interior, or the replacement `jmp` would be entered part-way through."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        md.detail = True
        interior = set(range(va + 1, va + len(stock_bytes)))
        # Sweep the whole neighbourhood of each hook, not just its own function: a branch from
        # anywhere nearby is what matters, and these two bands are where any of it could be.
        for lo, size in ((0x004C1000, 0x4000), (0x0091E000, 0x5000)):
            off = va_to_offset(stock, lo)
            for ins in md.disasm(stock[off : off + size], lo):
                for group in ins.groups:
                    if ins.group_name(group) in {"jump", "call"}:
                        for op in ins.operands:
                            if op.type == capstone.x86.X86_OP_IMM:
                                assert op.imm not in interior, (
                                    f"{ins.address:#x} branches into the hook at {va:#x}"
                                )
