"""A synthetic PE32 image carrying the ROTWK patch sites, with the real original bytes planted.

The point is that the whole apply + verify path runs in CI without the copyrighted `game.dat`:
every address a patch asserts, repoints or replaces exists here holding exactly what the real
build holds there, and nothing else does. A patch aimed at the wrong address therefore fails here
the same way it would fail on a real binary.

Everything both condition-adding patches need is planted in one image, because they share the
model-condition name table and the tests that matter most are the ones that apply *both*.

:func:`worldbuilder_image` is a second, separate image, because `desert-weather-wb` targets a
different binary. Its sites are ~35 MB apart in a 34 MB executable, so rather than allocate that
it maps only the pages the patch touches, as several small sections - which `va_to_offset` handles
exactly as it handles the real thing.

:func:`instance_guard_image` builds the same way, and builds both stand-ins the `multi-instance`
pair needs: `game.dat`'s two guards and `lotrbfme2ep1.exe`'s one live in different binaries, so the
image is chosen by which patch is under test.

:func:`observer_switch_image` is sparse for the same reason: `observer-switch` edits one `call` and
reads two functions most of a megabyte away from it, so only those two pages need to exist.
"""

from __future__ import annotations

import struct

from sage_patch import addresses as ad
from sage_patch.patches import crash_dump as cd
from sage_patch.patches import description_timers as dt
from sage_patch.patches import desert_weather as dw
from sage_patch.patches import desert_weather_wb as wb
from sage_patch.patches import hero_bar_slots as hbs
from sage_patch.patches import herobar as hb
from sage_patch.patches import infantry_lighting as il
from sage_patch.patches import lifetime_extend_upgrade as lex
from sage_patch.patches import multi_instance as mi
from sage_patch.patches import observer_switch as obs
from sage_patch.patches import production_condition as pc
from sage_patch.patches import production_split as ps
from sage_patch.patches import skirmish_ai_fallback as saf
from sage_patch.patches import trigger_recharge_list as trl
from sage_patch.patches import upgrade_description as ud
from sage_patch.patches import upgrade_grant_lists as ugl
from sage_patch.patches.experimental import campaign_select as cs
from sage_patch.patches.experimental import recharge_rescale as rr
from sage_patch.patches.experimental import standalone_launcher as sl
from sage_patch.patches.utils import kind_of as ko
from sage_patch.patches.utils import locomotor_sets as ls
from sage_patch.patches.utils import model_conditions as mc
from sage_patch.patches.utils import token_lists as tl
from sage_patch.patches.utils import weapon_set_flags as ws

IMAGE_BASE = 0x400000

#: Where the image parks every name string, past the two tables that point into it.
STRINGS_VA = 0x00DA4000


def stock_condition_name(index: int) -> str:
    """The name the synthetic table carries at ``index``: the real one where the patch fingerprints
    it, an index-derived placeholder everywhere else."""
    return mc.TABLE_FINGERPRINT.get(index, f"COND_{index}")


def stock_weapon_set_name(index: int) -> str:
    return ws.TABLE_FINGERPRINT.get(index, f"WSFLAG_{index}")


def stock_locomotor_set_name(index: int) -> str:
    return ls.TABLE_FINGERPRINT.get(index, f"SET_STOCK_{index}")


def stock_kindof_name(index: int) -> str:
    return ko.TABLE_FINGERPRINT.get(index, f"KIND_{index}")


def synthetic_image() -> bytearray:
    strings = bytearray()
    string_vas: dict[str, int] = {}

    def intern(text: str) -> int:
        if text not in string_vas:
            string_vas[text] = STRINGS_VA + len(strings)
            strings.extend(text.encode("ascii") + b"\x00")
        return string_vas[text]

    condition_vas = [intern(stock_condition_name(i)) for i in range(mc.STOCK_BIT_COUNT)]
    weather_vas = [intern(name) for name in dw.STOCK_WEATHER_NAMES]
    weapon_set_vas = [intern(stock_weapon_set_name(i)) for i in range(ws.STOCK_FLAG_COUNT)]
    locomotor_vas = [intern(stock_locomotor_set_name(i)) for i in range(ls.STOCK_SET_COUNT)]
    kindof_vas = [intern(stock_kindof_name(i)) for i in range(ko.STOCK_KIND_COUNT)]

    highest = STRINGS_VA + len(strings) - IMAGE_BASE + 0x100
    data = bytearray(((highest + 0x400) // 0x200 + 1) * 0x200)

    data[0:2] = b"MZ"
    e = 0x80
    struct.pack_into("<I", data, 0x3C, e)
    data[e : e + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, e + 4, 0x14C)  # Machine (i386)
    struct.pack_into("<H", data, e + 6, 1)  # NumberOfSections
    struct.pack_into("<H", data, e + 20, 0xE0)  # SizeOfOptionalHeader
    opt = e + 24
    struct.pack_into("<H", data, opt, 0x10B)  # PE32 magic
    struct.pack_into("<I", data, opt + 28, IMAGE_BASE)
    struct.pack_into("<I", data, opt + 32, 0x1000)  # SectionAlignment
    struct.pack_into("<I", data, opt + 36, 0x200)  # FileAlignment
    struct.pack_into("<I", data, opt + 56, 0x2000000)  # SizeOfImage
    struct.pack_into("<I", data, opt + 60, 0x400)  # SizeOfHeaders, room for more headers
    header = bytearray(40)
    header[0:8] = b".text\x00\x00\x00"
    size = len(data) - 0x1000
    struct.pack_into("<IIII", header, 8, size, 0x1000, size, 0x1000)
    data[opt + 0xE0 : opt + 0xE0 + 40] = header

    def write(va: int, blob: bytes) -> None:
        data[va - IMAGE_BASE : va - IMAGE_BASE + len(blob)] = blob

    def u32(va: int, value: int) -> None:
        struct.pack_into("<I", data, va - IMAGE_BASE, value)

    write(STRINGS_VA, bytes(strings))

    for index, va in enumerate(condition_vas):
        u32(mc.NAME_TABLE_VA + index * 4, va)
    u32(mc.NAME_TABLE_VA + mc.STOCK_BIT_COUNT * 4, 0)  # the terminator
    for va in mc.TABLE_REF_VAS:
        u32(va, mc.NAME_TABLE_VA)
    for va, prefix in mc.COUNT_SITES:
        write(va, prefix)
        u32(va + len(prefix), mc.STOCK_BIT_COUNT)
    for va in mc.XFER_LENGTH_VAS:
        write(va, bytes([0x6A, mc.XFER_STOCK_LENGTH]))  # push 0x4a

    write(pc._UPDATE_VA, pc._UPDATE_ENTRY)
    u32(pc._UPDATE_VTABLE + pc._UPDATE_VTABLE_SLOT, pc._UPDATE_VA)

    # Neither has a count to raise; the weapon-set one has a count that must *not* move, so its
    # four bytes are planted for the check that asserts exactly that.
    for table_va, vas, ref_vas in (
        (ws.NAME_TABLE_VA, weapon_set_vas, ws.TABLE_REF_VAS),
        (ls.NAME_TABLE_VA, locomotor_vas, ls.TABLE_REF_VAS),
    ):
        for index, va in enumerate(vas):
            u32(table_va + index * 4, va)
        u32(table_va + len(vas) * 4, 0)  # the terminator
        for va in ref_vas:
            u32(va, table_va)
    write(ws.BIT_COUNT_VA, ws.BIT_COUNT_BYTES)

    for index, va in enumerate(weather_vas):
        u32(dw.WEATHER_TABLE_VA + index * 4, va)
    u32(dw.WEATHER_TABLE_VA + len(weather_vas) * 4, 0)
    for va in dw.WEATHER_TABLE_REF_VAS:
        u32(va, dw.WEATHER_TABLE_VA)
    write(dw._ANY_WEATHER_DEFAULT_VA, dw._ANY_WEATHER_DEFAULT_PREFIX)
    u32(dw._ANY_WEATHER_DEFAULT_VA + len(dw._ANY_WEATHER_DEFAULT_PREFIX), dw.NEW_WEATHER_INDEX)
    write(dw._ANY_WEATHER_TEST_VA, dw._ANY_WEATHER_TEST_PREFIX + bytes([dw.NEW_WEATHER_INDEX]))
    write(dw._BIND_SITE_VA, dw._BIND_ORIGINAL)
    write(dw._UPGRADE_SITE_VA, dw._UPGRADE_ORIGINAL)

    for index, va in enumerate(kindof_vas):
        u32(ko.NAME_TABLE_VA + index * 4, va)
    u32(ko.NAME_TABLE_VA + ko.STOCK_KIND_COUNT * 4, 0)  # the terminator
    # The next table starts immediately after it in the real image, which is why the kindof table
    # cannot grow in place either.
    u32(ko.NAME_TABLE_VA + (ko.STOCK_KIND_COUNT + 1) * 4, STRINGS_VA)
    for va in ko.TABLE_REF_VAS:
        u32(va, ko.NAME_TABLE_VA)
    for va, prefix in ko.COUNT_SITES:
        write(va, prefix)
        u32(va + len(prefix), ko.STOCK_KIND_COUNT)

    for hook in hb.HOOKS:
        write(hook.va, hook.original)
    write(hb.TOOLTIP_EDIT.va, hb.TOOLTIP_EDIT.original)

    return data


#: Where the Worldbuilder image parks its two stock weather strings. Any mapped page will do; the
#: patch only ever follows the table's pointers.
WB_STRINGS_VA = 0x0056B000 + 0x800


def _pe32(sections: list[tuple[str, int, bytes]], size_of_image: int) -> bytearray:
    """A minimal PE32 whose section table maps ``(name, rva, content)``, in ascending RVA order.

    Several small sections rather than one big one is what keeps a synthetic image of a 34 MB
    binary down to a few KB: only the pages a patch reads or writes have to exist."""
    file_align, section_align = 0x200, 0x1000
    headers = 0x400
    data = bytearray(headers)
    data[0:2] = b"MZ"
    e = 0x80
    struct.pack_into("<I", data, 0x3C, e)
    data[e : e + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, e + 4, 0x14C)  # Machine (i386)
    struct.pack_into("<H", data, e + 6, len(sections))
    struct.pack_into("<H", data, e + 20, 0xE0)  # SizeOfOptionalHeader
    opt = e + 24
    struct.pack_into("<H", data, opt, 0x10B)  # PE32 magic
    struct.pack_into("<I", data, opt + 28, IMAGE_BASE)
    struct.pack_into("<I", data, opt + 32, section_align)
    struct.pack_into("<I", data, opt + 36, file_align)
    struct.pack_into("<I", data, opt + 56, size_of_image)
    struct.pack_into("<I", data, opt + 60, headers)
    struct.pack_into("<H", data, opt + 70, 0)  # DllCharacteristics: no DYNAMIC_BASE

    sectab = opt + 0xE0
    for index, (name, rva, content) in enumerate(sections):
        raw_size = (len(content) + file_align - 1) // file_align * file_align
        praw = len(data)
        header = bytearray(40)
        header[0:8] = name.encode("ascii").ljust(8, b"\x00")[:8]
        struct.pack_into("<IIII", header, 8, len(content), rva, raw_size, praw)
        struct.pack_into("<I", header, 36, 0x40000040)
        data[sectab + index * 40 : sectab + (index + 1) * 40] = header
        data += content + b"\x00" * (raw_size - len(content))
    return data


def worldbuilder_image() -> bytearray:
    """A stand-in for `Worldbuilder.exe`, mapping only the pages `desert-weather-wb` touches."""
    pages: dict[int, bytearray] = {}

    def page_of(va: int) -> bytearray:
        base = va & ~0xFFF
        return pages.setdefault(base, bytearray(0x1000))

    def write(va: int, blob: bytes) -> None:
        page = page_of(va)
        start = va & 0xFFF
        assert start + len(blob) <= 0x1000, f"0x{va:08x} straddles a page in the stand-in"
        page[start : start + len(blob)] = blob

    def u32(va: int, value: int) -> None:
        write(va, struct.pack("<I", value))

    # the two stock name strings, and the table pointing at them
    string_vas = []
    blob = bytearray()
    for name in wb.STOCK_WEATHER_NAMES:
        string_vas.append(WB_STRINGS_VA + len(blob))
        blob += name.encode("ascii") + b"\x00"
    write(WB_STRINGS_VA, bytes(blob))
    for index, va in enumerate(string_vas):
        u32(wb.WEATHER_TABLE_VA + index * 4, va)
    u32(wb.WEATHER_TABLE_VA + len(string_vas) * 4, 0)  # the terminator
    # the next table starts immediately after it, which is why it cannot grow in place
    u32(wb.WEATHER_TABLE_VA + (len(string_vas) + 1) * 4, WB_STRINGS_VA)

    for va, prefix in wb.WEATHER_TABLE_REF_SITES:
        write(va, prefix + struct.pack("<I", wb.WEATHER_TABLE_VA))
    write(wb.COMBO_BOUND_VA, bytes.fromhex("837de0") + bytes([len(wb.STOCK_WEATHER_NAMES)]))
    for va, expected in wb._DIALOG_FINGERPRINT.items():
        write(va, expected)

    sections = [
        (f".s{index}", base - IMAGE_BASE, bytes(pages[base]))
        for index, base in enumerate(sorted(pages))
    ]
    return _pe32(sections, max(pages) - IMAGE_BASE + 0x1000)


def _sparse_image(planted: dict[int, bytes]) -> bytearray:
    """A PE32 mapping one section per touched page, each holding the bytes ``planted`` puts in it.

    Everything not planted reads as zero, which is what makes these images useful negatively as
    well: a patch that looked one instruction to either side of where it claims to would find
    nothing there.
    """
    pages: dict[int, bytearray] = {}
    for va, blob in planted.items():
        base = va & ~0xFFF
        start = va & 0xFFF
        assert start + len(blob) <= 0x1000, f"0x{va:08x} straddles a page in the stand-in"
        pages.setdefault(base, bytearray(0x1000))[start : start + len(blob)] = blob

    sections = [
        (f".s{index}", base - IMAGE_BASE, bytes(pages[base]))
        for index, base in enumerate(sorted(pages))
    ]
    return _pe32(sections, max(pages) - IMAGE_BASE + 0x1000)


def observer_switch_image() -> bytearray:
    """A stand-in carrying the palantir's observer-bar gate and both game-mode predicates.

    The gate and the predicates are ~0xB2000 apart, so a sparse image maps two pages rather than
    three-quarters of a megabyte. The two predicates are adjacent in the real binary and are
    planted that way here, which is what makes the "aimed at the wrong function" check meaningful:
    the stock target sits immediately before the new one, so a `call` left unpatched lands in real
    code rather than in zeroes.
    """
    return _sparse_image(
        {
            ad.OBSERVER_BAR_GATE_FINGERPRINT: ad.OBSERVER_BAR_GATE_FINGERPRINT_BYTES,
            **obs.ANCHORS,
        }
    )


def skirmish_ai_fallback_image() -> bytearray:
    """A stand-in carrying both hook windows in `Player::initFromDict` and everything the cave
    reaches.

    Sparse for the usual reason: the two windows and the continuation sit in two pages of
    `initFromDict`, and the four engine routines, the name-key object and the `PlayerTemplate`
    field-table entry are spread over eight megabytes around them. Everything not planted reads as
    zero, so a hook aimed one instruction to either side of where it claims to be would find
    nothing there.
    """
    return _sparse_image(
        {
            ad.PLAYER_SKIRMISH_ROUTE: ad.PLAYER_SKIRMISH_ROUTE_BYTES,
            ad.PLAYER_SKIRMISH_IMPORT: ad.PLAYER_SKIRMISH_IMPORT_BYTES,
            **saf.ANCHORS,
        }
    )


def crash_dump_image() -> bytearray:
    """A stand-in carrying both crash-path windows and everything the cave reads through.

    Sparse for the usual reason: `writeMiniDump`'s argument push and `Debug::crash`'s
    `RaiseException` push sit in three pages a few kilobytes apart, and nothing else in the
    11 MB image is touched. Everything not planted reads as zero, so a window aimed one
    instruction to either side of where it claims to be would find nothing there.
    """
    return _sparse_image(
        {
            ad.MINI_DUMP_ARGS: ad.MINI_DUMP_ARGS_BYTES,
            ad.DEBUG_CRASH_RAISE: ad.DEBUG_CRASH_RAISE_BYTES,
            **cd.ANCHORS,
        }
    )


def description_timers_image() -> bytearray:
    """A stand-in carrying the tooltip builder's two windows and every routine the cave reaches.

    Sparse for the usual reason: the builder's prologue and its tail are one page apart, and the
    seven engine routines the cave calls or compares against are spread over five megabytes below
    them. Everything not planted reads as zero, so a window aimed one instruction to either side of
    where it claims to be would find nothing there.

    The two `RECHARGE_FORMULA_ANCHORS` are planted too, even though the patch never jumps to them:
    they are the instructions the cooldown transcription copies, and a build that encoded them
    differently would be a build whose formula the cave is not reproducing.
    """
    return _sparse_image(
        {
            ad.DESCRIPTION_BUTTON_CAPTURE: ad.DESCRIPTION_BUTTON_CAPTURE_BYTES,
            ad.DESCRIPTION_TAIL: ad.DESCRIPTION_TAIL_BYTES,
            **dt.ANCHORS,
            **dt.RECHARGE_FORMULA_ANCHORS,
        }
    )


def upgrade_description_image() -> bytearray:
    """A stand-in carrying both of the tooltip builder's status-message cases and the three
    `UnicodeString` methods plus two wide literals the cave reaches.

    Sparse for the usual reason: the two cases sit together in one page, and `operator=`, both
    `concat` forms and the separators are spread over four megabytes below them. Everything not
    planted reads as zero, so a window aimed one instruction to either side of where it claims to
    be would find nothing there - and the two cases are planted adjacently, as they are in the real
    binary, which is what makes "the wrong case" a reachable failure rather than a walk into
    zeroes.
    """
    return _sparse_image(
        {
            ad.DESCRIPTION_PURCHASED_RUN: ad.DESCRIPTION_PURCHASED_RUN_BYTES,
            ad.DESCRIPTION_BLOCKED_RUN: ad.DESCRIPTION_BLOCKED_RUN_BYTES,
            **ud.ANCHORS,
        }
    )


def campaign_select_image() -> bytearray:
    """A stand-in carrying the shell's campaign callback and the three sites the patch reads.

    Sparse for the usual reason: the callback, the start thunk's static bind and
    `AsciiString::set` span most of five megabytes between them and the patch touches four pages
    of it. Everything else reads as zero, so a check that looked one instruction to either side of
    where it claims to would find nothing there.
    """
    return _sparse_image(
        {
            ad.MAIN_MENU_CAMPAIGN_HANDLER: ad.MAIN_MENU_CAMPAIGN_HANDLER_BYTES,
            **cs.ANCHORS,
        }
    )


def hero_bar_slots_image() -> bytearray:
    """A stand-in carrying every site `hero-bar-slots` rewrites, in its stock 16-slot form.

    Driven off the patch's own tables, so what it exercises is the arithmetic and the
    apply/verify/detect machinery rather than the addresses - which a stand-in restating them
    could only ever confirm against itself. The addresses are derived in
    `docs/hero-bar-slots.md` and checked against the real binary by `TestInstalledBinary`.
    """
    planted: dict[int, bytes] = {
        hbs.CLASS_SIZE_SITE: hbs.CLASS_SIZE_OPCODE + struct.pack("<I", hbs.STOCK_CLASS_SIZE)
    }
    for count_site in hbs.COUNT_SITES:
        planted[count_site.va] = count_site.encode(hbs.STOCK_SLOTS)
    for field_site in hbs.FIELD_SITES:
        planted[field_site.va] = bytes.fromhex(field_site.original)
    return _sparse_image(planted)


#: Where the `infantry-lighting` stand-in parks the kindof name strings: a page in the same region
#: as the table that points at them, and one nothing else in that image uses.
KINDOF_STRINGS_VA = 0x00DA4000

#: The stock kindof names in mask bits 8..15 - the lane `infantry-lighting` can name. Test data
#: rather than patch data, deliberately: the patch resolves names through the image's *own* table
#: and hardcodes none of them, so a stand-in has to carry the real ones for a name to resolve at
#: all - and the check that `HERO` (bit 90) is refused needs a table where 90 really is `HERO`,
#: which :data:`kind_of.TABLE_FINGERPRINT` already supplies.
INFANTRY_LIGHTING_LANE = {
    8: "INFANTRY",
    9: "CAVALRY",
    10: "MONSTER",
    11: "MACHINE",
    12: "AIRCRAFT",
    13: "HUGE_VEHICLE",
    14: "DOZER",
    15: "SWARM_DOZER",
}


def infantry_lighting_image() -> bytearray:
    """A stand-in carrying both lighting gates in their stock form, plus the whole kindof name
    table the patch resolves names against.

    Sparse for the usual reason: the two gates, the render loop that reads the flag back and the
    kindof table are spread over most of ten megabytes, and the patch touches a dozen pages of it.
    Everything not planted reads as zero, so a gate aimed one instruction to either side of where
    it claims to be would find nothing there.

    The table is planted one pointer at a time rather than as one blob because it crosses a page
    boundary, which `_sparse_image` refuses per write.
    """
    planted: dict[int, bytes] = {}

    strings_va = KINDOF_STRINGS_VA
    for index in range(ko.STOCK_KIND_COUNT):
        name = INFANTRY_LIGHTING_LANE.get(index, stock_kindof_name(index))
        blob = name.encode("ascii") + b"\x00"
        if (strings_va & 0xFFF) + len(blob) > 0x1000:  # never let one name straddle a page
            strings_va = (strings_va & ~0xFFF) + 0x1000
        planted[strings_va] = blob
        planted[ko.NAME_TABLE_VA + index * 4] = struct.pack("<I", strings_va)
        strings_va += len(blob)
    planted[ko.NAME_TABLE_VA + ko.STOCK_KIND_COUNT * 4] = struct.pack("<I", 0)  # the terminator

    for va in ko.TABLE_REF_VAS:
        planted[va] = struct.pack("<I", ko.NAME_TABLE_VA)
    for va, prefix in ko.COUNT_SITES:
        planted[va] = prefix + struct.pack("<I", ko.STOCK_KIND_COUNT)

    planted.update(il.FINGERPRINT)
    for site in il.SITES:
        planted[site.va] = site.stock
    return _sparse_image(planted)


def standalone_launcher_image() -> bytearray:
    """A stand-in for `lotrbfme2ep1.exe` carrying the token site in its stock form plus every
    site `standalone-launcher` reads.

    Sparse for the usual reason: the key derivation, the Blowfish schedule, the `gi.dat` accessor
    and `strcpy` are spread over 0x45000 bytes and the patch touches four pages of it. The clamp
    anchor sits immediately *before* the site, so a patch that started one instruction early would
    collide with real bytes here rather than with zeroes.
    """
    return _sparse_image({sl.TOKEN_SITE: sl.TOKEN_SITE_STOCK, **sl.ANCHORS})


def instance_guard_image(patch: mi._MutexGuardPatch) -> bytearray:
    """A stand-in for whichever binary ``patch`` targets, carrying its fingerprint sites and its
    guards in their stock, unpatched form.

    Driving it off the patch's own tables rather than a second hardcoded copy of the addresses is
    deliberate: what these tests check is the apply/verify machinery and the shape of the edit, and
    a stand-in that restated the VAs would only ever agree with itself. The bytes themselves are
    checked against the real binaries in `docs/multi-instance.md`.
    """
    planted = dict(patch.fingerprint)
    for guard in patch.guards:
        planted[guard.va] = guard.stock
    return _sparse_image(planted)


#: Where the `production-split` stand-in parks the modifier-type name strings. Any mapped address
#: works - the patch reaches them through the table's own pointers - so this is simply a page
#: nothing else in that image uses.
MODIFIER_STRINGS_VA = 0x00DA4800


def stock_modifier_name(index: int) -> str:
    """The name the synthetic modifier-type table carries at ``index``: the real one where the
    patch fingerprints it, an index-derived placeholder everywhere else."""
    return ps.TABLE_FINGERPRINT.get(index, f"MODTYPE_{index}")


def binary_attest_image(text_va: int = ad.TEXT_SECTION_VA) -> bytearray:
    """A stand-in carrying a full-size `.text` plus the two sites `binary-attest` reads.

    **Not sparse, and it cannot be.** Every other stand-in here maps only the pages its patch
    touches, because the addresses are what the test is about. This patch's subject is the
    *whole* code section: it hashes `TEXT_SECTION_LEN` bytes and the property under test is that
    one changed byte anywhere in that range changes the published value. A sparse image would
    read past its own section and answer a different question.

    The content is a cheap deterministic filler rather than zeros, so that a fold over it is a
    real mixing test - an all-zero range makes FNV-1a's `xor` a no-op and would hide a swapped
    operand. `text_va` is a parameter so a test can build the "`.text` moved" build that the
    patch must refuse.
    """
    text = bytearray(ad.TEXT_SECTION_LEN)
    for index in range(0, ad.TEXT_SECTION_LEN, 4):
        struct.pack_into("<I", text, index, (index * 2654435761) & 0xFFFFFFFF)

    def plant(va: int, blob: bytes) -> None:
        start = va - text_va
        assert 0 <= start and start + len(blob) <= len(text), f"0x{va:08x} is outside .text"
        text[start : start + len(blob)] = blob

    plant(ad.LOGIC_CRC_EMIT, ad.LOGIC_CRC_EMIT_BYTES)
    plant(ad.LOGIC_CRC_SHROUD_XFER, ad.LOGIC_CRC_SHROUD_XFER_BYTES)
    return _pe32(
        [(".text", text_va - IMAGE_BASE, bytes(text))],
        text_va - IMAGE_BASE + ad.TEXT_SECTION_LEN,
    )


#: Where the `lifetime-extend-upgrade` stand-in parks the five field-name strings: a page in the
#: same region as the table that points at them, and one nothing else in that image uses.
LIFETIME_STRINGS_VA = 0x00C32800


def lifetime_extend_upgrade_image() -> bytearray:
    """A stand-in carrying every site `lifetime-extend-upgrade` reads or rewrites.

    Sparse for the usual reason: the module's three functions, its factory thunk, the two mask
    predicates, the sleepy-update driver and the client's timer widget are spread over most of five
    megabytes and the patch touches a dozen pages of it. Everything not planted reads as zero, so
    a hook aimed one instruction to either side of where it claims to be would find nothing there.

    The field table is built here from the patch's own `STOCK_FIELDS` rather than pasted as a hex
    blob, because what the table has to survive is being *copied* - the test that matters is that
    the five rows come out of the cave unchanged, and a blob would only ever agree with itself.
    """
    strings = bytearray()
    rows = bytearray()
    for name, offset in lex.STOCK_FIELDS:
        name_va = LIFETIME_STRINGS_VA + len(strings)
        strings += name.encode("ascii") + b"\x00"
        # `parse` and `userData` are not read by the patch (the rows are copied verbatim), so a
        # recognisable filler stands in for everything but the offset the fingerprint checks.
        rows += struct.pack("<IIII", name_va, 0x00730000 + offset, 0, offset)
    rows += bytes(16)  # the terminator the patch requires before it will copy anything

    return _sparse_image(
        {
            **lex.ANCHORS,
            lex.ALLOC_VA: lex.ALLOC_BYTES,
            lex.ARM_VA: lex.ARM_BYTES,
            lex.UPDATE_VA: lex.UPDATE_BYTES,
            lex.LATCH_DEFAULT_VA: lex.LATCH_DEFAULT_BYTES,
            # `buildFieldParse`, whose one imm32 is the table's only reference in the image
            0x007A7DFA: bytes.fromhex("8b4c24046a00")
            + b"\x68"
            + struct.pack("<I", lex.FIELD_TABLE_VA)
            + bytes.fromhex("e8cd3ac8ffc3"),
            lex.FIELD_TABLE_VA: bytes(rows),
            LIFETIME_STRINGS_VA: bytes(strings),
        }
    )


def production_split_image() -> bytearray:
    """A stand-in carrying every site `production-split` reads or rewrites, plus the
    modifier-type name table and the strings its pointers reach.

    Sparse for the usual reason: the eight modifier sites, the name walk and the two callees are
    spread over most of a megabyte and the patch touches a dozen pages of it. The AI windows are
    planted whether or not the test hooks them, so the opt-in and the default run against the
    same image.

    The table is built here rather than copied as a hex blob so that the placeholder names differ
    from the four the patch fingerprints - a check that read the wrong index would find
    ``MODTYPE_13`` where it expected ``PRODUCTION``.
    """
    strings = bytearray()
    pointers = []
    for index in range(ps.STOCK_TYPE_COUNT):
        pointers.append(MODIFIER_STRINGS_VA + len(strings))
        strings += stock_modifier_name(index).encode("ascii") + b"\x00"
    return _sparse_image(
        {
            **ps.ANCHORS,
            **ps.AI_ANCHORS,
            MODIFIER_STRINGS_VA: bytes(strings),
            ps.TYPE_TABLE_VA: struct.pack(f"<{len(pointers) + 1}I", *pointers, 0),
        }
    )


def recharge_rescale_image() -> bytearray:
    """A stand-in carrying every site `recharge-rescale` reads or rewrites.

    Sparse for the usual reason: the hooked frame gate in `GameLogic::update`, both
    `startPowerRecharge` implementations, the three readers that pin the interface layout and the
    six callees the cave calls are spread over most of four megabytes, and the patch touches a
    dozen pages of it. Everything not planted reads as zero, so a hook aimed one instruction to
    either side of where it claims to be would find nothing there.

    Driven straight off the patch's own anchor table, because that table *is* what the patch reads:
    a second hardcoded copy here could only ever agree with it. Whether those addresses hold those
    bytes in the real build is what `TestInstalledBinary` answers.
    """
    return _sparse_image(dict(rr.ANCHORS))


#: Where the `trigger-recharge-list` stand-in parks the 35 field-name strings: a page below the
#: table that points at them, and one nothing else in that image uses.
TRIGGER_RECHARGE_STRINGS_VA = 0x00C63000

#: `SpecialAbilityUpdate`'s field-parse table as `(name, ModuleData offset)`, in **table order** -
#: which is neither alphabetical nor offset order, and is what makes the patch's index meaningful.
#: Planted in full so that a patch reading the wrong entry finds a real keyword there rather than
#: zeroes, and so `AttributeModifier` - the other `AsciiString` field in the table, holding the
#: same stock parse function - stands where a repoint aimed one entry short would land.
SPECIAL_ABILITY_FIELDS = (
    ("SpecialPowerTemplate", 0x08),
    ("UpdateModuleStartsAttack", 0x0C),
    ("StartsPaused", 0x0D),
    ("InitiateSound", 0x10),
    ("ReEnableAntiCategory", 0x42),
    ("AntiCategory", 0x34),
    ("AntiFX", 0x4C),
    ("AttributeModifier", 0x18),
    ("AttributeModifierRange", 0x1C),
    ("AttributeModifierAffectsSelf", 0x20),
    ("AttributeModifierAffects", 0x24),
    ("AttributeModifierFX", 0x28),
    ("AttributeModifierWeatherBased", 0x2C),
    ("WeatherDuration", 0x30),
    ("RequirementsFilterMPSkirmish", 0x38),
    ("RequirementsFilterStrategic", 0x3C),
    ("TargetEnemy", 0x40),
    ("TargetAllSides", 0x41),
    ("InitiateFX", 0x44),
    ("TriggerFX", 0x48),
    ("SetModelCondition", 0x50),
    ("SetModelConditionTime", 0x54),
    ("GiveLevels", 0x58),
    ("DisableDuringAnimDuration", 0x5C),
    ("IdleWhenStartingPower", 0x5D),
    ("AffectGood", 0x5E),
    ("AffectEvil", 0x5F),
    ("AffectAllies", 0x60),
    ("AvailableAtStart", 0x61),
    ("ChangeWeather", 0x64),
    ("AdjustVictim", 0x68),
    ("OnTriggerRechargeSpecialPower", 0x6C),
    ("BurnDecayModifier", 0x70),
    ("UseDistanceFromCommandCenter", 0x74),
    ("DistanceFromCommandCenter", 0x78),
)


def trigger_recharge_list_image() -> bytearray:
    """A stand-in carrying `SpecialAbilityUpdate`'s field-parse table and the module walk that
    reads the field it repoints.

    Sparse for the usual reason: the table and the walk are three megabytes apart. The table is
    built here from names and offsets rather than pasted as a hex blob, because what the patch
    does to it is find *one* entry among 35 identically shaped ones - a blob would only ever agree
    with itself about which.

    Both `AsciiString` entries carry the real stock parse function, so "repointed the right entry"
    is a check the image can actually fail.
    """
    strings = bytearray()
    rows = bytearray()
    for name, offset in SPECIAL_ABILITY_FIELDS:
        name_va = TRIGGER_RECHARGE_STRINGS_VA + len(strings)
        strings += name.encode("ascii") + b"\x00"
        stock_ascii = name in ("AttributeModifier", trl.FIELD_NAME)
        parse = tl.STOCK_ASCII_STRING_PARSER if stock_ascii else 0x00730000 + offset
        rows += struct.pack("<IIII", name_va, parse, 0, offset)
    rows += bytes(trl.FIELD_ENTRY_SIZE)  # the terminator

    return _sparse_image(
        {
            **{va: blob for va, blob, _what in trl.ANCHORS},
            trl.MATCH_CALL_VA: b"\xe8"
            + struct.pack("<i", trl.ASCII_STRING_COMPARE - (trl.MATCH_CALL_VA + 5)),
            trl.FIELD_TABLE_VA: bytes(rows),
            # `buildFieldParse`, whose one imm32 is the table's only reference in the image
            trl.FIELD_TABLE_REF_VA: b"h" + struct.pack("<I", trl.FIELD_TABLE_VA),
            TRIGGER_RECHARGE_STRINGS_VA: bytes(strings),
        }
    )


#: Where the `upgrade-grant-lists` stand-in parks the eleven field-name strings: a page below the
#: table that points at them, and one nothing else in that image uses.
UPGRADE_LIST_STRINGS_VA = 0x00C6D000

#: `ObjectCreationUpgrade`'s field-parse table as `(name, ModuleData offset)`, in table order.
#: Planted in full so that a patch reading the wrong entry finds a real keyword there rather than
#: zeroes - and in particular so `ThingToSpawn`, the third `AsciiString` in the table and the one
#: this patch must **not** touch, stands right beside the two it does.
OBJECT_CREATION_UPGRADE_FIELDS = (
    ("UpgradeObject", 0x008),
    ("Delay", 0x00C),
    ("RemoveUpgrade", 0x140),
    ("GrantUpgrade", 0x144),
    ("ThingToSpawn", 0x148),
    ("Offset", 0x14C),
    ("Angle", 0x158),
    ("DestroyWhenSold", 0x15C),
    ("DeathAnimAndDuration", 0x160),
    ("FadeInTime", 0x16C),
    ("UseBuildingProduction", 0x170),
)

#: Which of those rows carry the stock `AsciiString` parser in the real build - the three the
#: patch has to tell apart by name.
_UPGRADE_LIST_ASCII_FIELDS = ("RemoveUpgrade", "GrantUpgrade", "ThingToSpawn")


def upgrade_grant_lists_image() -> bytearray:
    """A stand-in carrying `ObjectCreationUpgrade`'s field-parse table and the upgrade step that
    reads the two fields it re-types.

    Sparse for the usual reason: the table, the module's code and the interface search the object
    argument depends on are spread over two and a half megabytes. The table is built here from
    names and offsets rather than pasted as a hex blob, because what the patch does to it is find
    two rows among eleven identically shaped ones.
    """
    strings = bytearray()
    rows = bytearray()
    for name, offset in OBJECT_CREATION_UPGRADE_FIELDS:
        name_va = UPGRADE_LIST_STRINGS_VA + len(strings)
        strings += name.encode("ascii") + b"\x00"
        stock_ascii = name in _UPGRADE_LIST_ASCII_FIELDS
        parse = tl.STOCK_ASCII_STRING_PARSER if stock_ascii else 0x00730000 + offset
        rows += struct.pack("<IIII", name_va, parse, 0, offset)
    rows += bytes(16)  # the terminator

    def call(from_va: int, to_va: int) -> bytes:
        return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))

    return _sparse_image(
        {
            **{va: blob for va, blob, _what in ugl.ANCHORS},
            ugl.GRANT_CALL_VA: call(ugl.GRANT_CALL_VA, ugl.FIND_UPGRADE),
            ugl.REMOVE_CALL_VA: call(ugl.REMOVE_CALL_VA, ugl.FIND_UPGRADE),
            # the stock give and remove, which the patch reads only to point its caves at them
            ugl.GRANT_CALL_VA + 13: call(ugl.GRANT_CALL_VA + 13, ugl.OBJECT_GIVE_UPGRADE),
            ugl.REMOVE_CALL_VA + 13: call(ugl.REMOVE_CALL_VA + 13, ugl.OBJECT_REMOVE_UPGRADE),
            # `buildFieldParse`, whose one imm32 is the table's only reference in the image
            ugl.FIELD_TABLE_REF_VA: b"\x68" + struct.pack("<I", ugl.FIELD_TABLE_VA),
            ugl.FIELD_TABLE_VA: bytes(rows),
            UPGRADE_LIST_STRINGS_VA: bytes(strings),
        }
    )
