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
from sage_patch.patches import desert_weather as dw
from sage_patch.patches import desert_weather_wb as wb
from sage_patch.patches import herobar as hb
from sage_patch.patches import kind_of as ko
from sage_patch.patches import locomotor_sets as ls
from sage_patch.patches import model_conditions as mc
from sage_patch.patches import multi_instance as mi
from sage_patch.patches import observer_switch as obs
from sage_patch.patches import production_condition as pc
from sage_patch.patches import weapon_set_flags as ws

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
