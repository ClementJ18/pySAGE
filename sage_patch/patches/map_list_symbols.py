"""The map-list-symbols patch: `mapSymbol`, a `MapCache` field that gives a map its own icon in
the lobby map list - and, because that icon column *is* the list's sort key, its own place in the
sort order.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Derived in
``../docs/map-list-symbols.md``.

**What the stock engine draws.** The icon beside a map name is not a star-or-hammer boolean. The
lobby fills its list in two passes over a ``std::vector<MapMetaData*>``: the first writes a 32-bit
key into ``MapMetaData+0xF4`` - ``1..6`` for the highest difficulty the map has been beaten on,
with bit 15 set when `isOfficial` is No - and the second reads that key back through a ladder that
picks one of twelve mapped images, `AptDifficulty*Conquered` for an official map and
`AptUserMap*Conquered` for a user one. Between the two passes the vector is sorted, by a
comparator that understands three fields: the display name, `numPlayers`, and that key. So the
star and the hammer are two values of one sort key, and the difficulty medal is the same key's low
nibble.

**What this adds.** ``mapSymbol = <n>``, a small integer on a `MapCache` entry, packed into bits
16 and up of that same key. Everything follows from where it is packed:

* **The icon.** A row whose symbol is non-zero draws `AptMapSymbolNN<state>` instead of the stock
  medal - `NN` being the symbol, two digits, and `<state>` the same six the engine already
  spells: `NotConquered`, `EasyConquered`, `MedConquered`, `HardConquered`, `BrutalConquered`,
  `MaxConquered`. **The conquered state is kept**, because the symbol replaces the *family* of
  twelve images rather than the key that chooses between them.
* **The fallback.** A symbol that defines only the bare `AptMapSymbolNN` gets that one image at
  every difficulty, so a mod that does not care about the medal writes one `MappedImage` instead
  of six. A symbol whose images are all missing draws the stock medal, which is also what
  ``mapSymbol = 0`` (the default) means.
* **The sorting.** Free. The icon column header already sorts on the whole key, so packing the
  symbol above bit 15 makes it the primary grouping, official-versus-user the tiebreak inside a
  symbol, and difficulty the tiebreak inside that. Two options rewrite the seventeen bytes that
  subtract the key if that order is not the wanted one: ``--sort-by-symbol`` masks everything
  below the symbol away, so maps sharing one tie and fall through to the name; ``--sort-by-icon``
  lifts the difficulty above the star/hammer bit, so a symbol's maps beaten on one difficulty are
  contiguous rather than split in two.

**Why the symbol lives in the key rather than in a table beside it.** `MapMetaData` is full - it
ends at ``+0xFC`` with two `UnicodeString`s - and it sits inline in a `std::map` node, so it cannot
be widened without patching the node allocator. A side table would then need a key that outlives a
cache rebuild, which rules out the entry pointer and leaves copying every map's file name into the
cave. Bits 16-31 of ``+0xF4`` are free, are carried by the structure's own copy constructor and
assignment operator, and are read by the comparator as part of the sort key - which is the
behaviour wanted anyway. The one thing they are not is durable across a fill: pass 1 rewrites
``+0xF4`` from scratch for every entry it looks at. So the patch saves the symbol bits as pass 1
picks the entry up and ORs them back in the same pass, thirteen bytes later.

**The images are resolved once per fill**, not once per row and not cached across fills - which is
what the stock code does with its own twelve, and it means a reloaded `MappedImage` set is picked
up the next time the screen opens.

**No `.wnd` change, and no new column.** The symbol is drawn in column 0 where the medal was.

**Determinism.** Nothing here is logic-side: the key exists only to order a menu list and choose a
picture, `MapMetaData` is not CRC'd and no message carries it. Patched and unpatched peers can
play together, and replays cross.

**The one thing that does not round-trip.** `MapCache::writeCacheINI` is not patched, so it does
not emit `mapSymbol`. That costs nothing for maps a mod ships in its archives - the engine cannot
write into a `.big` and never rewrites that file - but a `mapSymbol` hand-written into the
**user** maps folder's own cache is dropped the next time the engine regenerates it.

**A `mapcache.ini` carrying `mapSymbol` will not load on a stock binary.** An unknown keyword is an
INI parse error, not a warning, so the field and this patch ship together or not at all.

**Composition.** Order-independent: the cave is allocated with
:func:`~..utils.allocate_section` past every existing section and :meth:`verify` finds it by name.
No bundled patch touches the `MapCache` field table, `parseMapCacheDefinition` or the lobby's map
list, and none reads what this one writes. The engine routines the cave calls - `INI_PARSE_INT`,
`INI_PARSE_FIELDS`, `MapMetaData::operator=`, the `AsciiString` constructor and destructor and the
mapped-image lookup - are read, never rewritten, here or anywhere else in the package.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sage_ini.engine import Engine

# Every engine fact this patch reads lives in `..addresses`, which is the single home for facts
# about this build; nothing about the target binary is written down here.
from ..addresses import (
    ASCII_STRING_CTOR,
    ASCII_STRING_DTOR,
    FIELD_PARSE_STRIDE,
    INI_PARSE_FIELDS,
    INI_PARSE_INT,
    MAP_CACHE_ASSIGN_CALL,
    MAP_CACHE_ASSIGN_CALL_BYTES,
    MAP_CACHE_FIELD_TABLE,
    MAP_CACHE_FIELD_TABLE_GETTER_REF,
    MAP_CACHE_FIELD_TABLE_PARSE_REF,
    MAP_CACHE_PARSE_FIELDS,
    MAP_CACHE_PARSE_FIELDS_BYTES,
    MAP_CACHE_STOCK_FIELDS,
    MAP_LIST_ANCHORS,
    MAP_LIST_COMPARE_KEY,
    MAP_LIST_COMPARE_KEY_BYTES,
    MAP_LIST_COMPARE_KEY_RESUME,
    MAP_LIST_ICON_LADDER,
    MAP_LIST_ICON_LADDER_BYTES,
    MAP_LIST_ICON_LADDER_RESUME,
    MAP_LIST_OFFICIAL_BIT,
    MAP_LIST_OFFICIAL_BIT_BYTES,
    MAP_LIST_OFFICIAL_BIT_RESUME,
    MAP_LIST_RESOLVE,
    MAP_LIST_RESOLVE_BYTES,
    MAP_LIST_RESOLVE_RESUME,
    MAP_LIST_ROW_ADD,
    MAP_LIST_SAVE_KEY,
    MAP_LIST_SAVE_KEY_BYTES,
    MAP_LIST_SAVE_KEY_RESUME,
    MAP_META_DATA_ASSIGN,
    MAP_META_DATA_IS_OFFICIAL,
    MAP_META_DATA_SORT_KEY,
    OBJECT_IMAGE_UPGRADE_FIND_IMAGE,
    OBJECT_IMAGE_UPGRADE_THE_IMAGES,
)
from ..asm import JA, JB, JBE, JE, JNE, JNZ, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "DEFAULT_KEYWORD",
    "DEFAULT_SORT",
    "DEFAULT_SYMBOLS",
    "DIFFICULTY_MASK",
    "FLAG_SORT_BY_ICON",
    "FLAG_SORT_BY_SYMBOL",
    "IMAGE_STATES",
    "MAX_SYMBOLS",
    "OFFICIAL_SHIFT",
    "SECTION_CHARACTERISTICS",
    "SECTION_NAME",
    "SORT_MODES",
    "SYMBOL_MASK",
    "SYMBOL_SHIFT",
    "MapListSymbolsPatch",
    "build_apply_key",
    "build_compare_icons",
    "build_compare_symbols",
    "build_parse_symbol",
    "build_pick_image",
    "build_pre_fields",
    "build_resolve",
    "build_save_key",
    "build_store_symbol",
    "build_table",
    "image_names",
    "validate_keyword",
]

#: Where the symbol sits in the key. Above `isOfficial`'s bit 15, so a symbol groups official and
#: user maps together and the star/hammer distinction becomes the tiebreak inside it.
SYMBOL_SHIFT = 16

#: The half of the key that is the symbol, and the mask `--sort-by-symbol` puts on both operands
#: of the comparator's key delta so that everything below the symbol stops ordering the list.
SYMBOL_MASK = 0xFFFFFFFF << SYMBOL_SHIFT & 0xFFFFFFFF

#: The rest of the key, as `--sort-by-icon` reads it: pass 1 writes the conquered difficulty into
#: the low nibble (``1``..``6``, ``0`` for a map that is not multiplayer) and `isOfficial` being No
#: into bit 15. Those are the two fields that choose *which* stock image a row draws, and the
#: option's whole job is to reorder them - the medal above the star/hammer instead of below it.
DIFFICULTY_MASK = 0xF
OFFICIAL_SHIFT = 15

#: The cave's flag word, which is how :meth:`MapListSymbolsPatch.detect` recovers a parameter that
#: would otherwise only be visible as the presence of one more rewritten site. The two sort flags
#: are mutually exclusive: both name the same seventeen bytes of the comparator.
FLAG_SORT_BY_SYMBOL = 1
FLAG_SORT_BY_ICON = 2

#: How the icon column orders the list, and the name each mode carries in `options` and in the
#: `.sagepatch` manifest.
#:
#: * ``"key"`` - stock. The comparator subtracts whole keys, so the order is symbol, then
#:   official-before-user, then difficulty.
#: * ``"symbol"`` - the symbol alone. Maps sharing one tie and fall through to the secondary
#:   column, which is the display name unless another header has been clicked.
#: * ``"icon"`` - symbol, then difficulty, then official-before-user. Every map carrying one
#:   symbol and beaten on one difficulty is contiguous, which is what makes the column group by
#:   the picture it is drawing.
SORT_MODES = ("key", "symbol", "icon")

DEFAULT_SORT = "key"

SECTION_NAME = ".mapsym"  # 7 chars: the PE name field is 8 bytes and truncates silently

#: Code + initialised data, executable, readable **and writable**: the cave holds the two globals
#: the hooks pass values through and the array of images the fill resolves into it.
SECTION_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

DEFAULT_KEYWORD = "mapSymbol"

#: How many symbols the patch makes room for, and the ceiling the CLI accepts. The names are
#: formatted with two digits, so 99 is where the scheme stops rather than where the engine does.
DEFAULT_SYMBOLS = 15
MAX_SYMBOLS = 99

#: The seven names a symbol can define, in the order the key's low nibble selects them: index 0 is
#: the bare name, used at every difficulty when the six are absent, and 1..6 are the engine's own
#: spelling of the conquered states - the same six words the stock `AptDifficulty*` images use.
IMAGE_STATES = (
    "",
    "NotConquered",
    "EasyConquered",
    "MedConquered",
    "HardConquered",
    "BrutalConquered",
    "MaxConquered",
)


_KEYWORD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_keyword(keyword: str) -> None:
    """Raise unless ``keyword`` is a name this patch could install.

    An INI keyword is matched with `stricmp` against the table's other rows, so a name that
    collides with one of the 24 would shadow it - silently, because the walk stops at the first
    hit and the stock rows come first."""
    if not _KEYWORD_RE.match(keyword):
        raise ValueError(f"{keyword!r} is not a valid INI keyword: letters, digits, underscores")
    for name, _offset in MAP_CACHE_STOCK_FIELDS:
        if name.lower() == keyword.lower():
            raise ValueError(f"{keyword!r} is already a MapCache field")


def image_names(count: int) -> tuple[str, ...]:
    """Every mapped-image name the cave looks up, symbol-major then state.

    ``count * 7`` names, so the array the fill resolves into is indexed by
    ``(symbol - 1) * 7 + state`` with ``state`` the key's low nibble - 0 for the bare name, 1..6
    for the conquered states."""
    return tuple(
        f"AptMapSymbol{symbol:02d}{state}"
        for symbol in range(1, count + 1)
        for state in IMAGE_STATES
    )


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _read_cstring(data: bytes | bytearray, va: int, limit: int = 64) -> str | None:
    off = va_to_offset(data, va)
    if off is None:
        return None
    end = bytes(data[off : off + limit]).find(b"\x00")
    if end < 0:
        return None
    try:
        return bytes(data[off : off + end]).decode("ascii")
    except UnicodeDecodeError:
        return None


@dataclass(frozen=True)
class _Layout:
    """Where each piece of the cave sits, given its base address and the patch's parameters.

    Pure arithmetic on the parameters, so :meth:`MapListSymbolsPatch.apply` and
    :meth:`MapListSymbolsPatch.verify` compute the same addresses from opposite directions. The
    count comes first, the flags second and the keyword third, so
    :meth:`MapListSymbolsPatch.detect` can read all three straight off the section base without
    knowing how long anything after them is.

    ``compare_va`` is None unless a sort mode other than ``"key"`` is installed, because that is
    the one stub a default build has no use for. Both modes that do want it hook the same
    seventeen bytes and put their stub in the same place, so only its body differs."""

    count_va: int
    flags_va: int
    keyword_va: int
    pending_va: int
    carry_va: int
    images_va: int
    names_va: int
    strings_va: int
    table_va: int
    parse_va: int
    pre_fields_va: int
    store_va: int
    resolve_va: int
    save_va: int
    key_va: int
    pick_va: int
    compare_va: int | None


def _layout(base_va: int, keyword: str, count: int, sort: str = DEFAULT_SORT) -> _Layout:
    names = image_names(count)
    keyword_va = base_va + 8
    after_keyword = keyword_va + len(keyword) + 1
    pending_va = after_keyword + (-after_keyword % 4)
    carry_va = pending_va + 4
    images_va = carry_va + 4
    names_va = images_va + len(names) * 4
    strings_va = names_va + len(names) * 4
    strings = sum(len(name) + 1 for name in names)
    after_strings = strings_va + strings
    table_va = after_strings + (-after_strings % 4)
    # the stock rows, this patch's row and the terminator
    parse_va = table_va + (len(MAP_CACHE_STOCK_FIELDS) + 2) * FIELD_PARSE_STRIDE

    pre_fields_va = parse_va + len(build_parse_symbol(parse_va, pending_va, count))
    store_va = pre_fields_va + len(build_pre_fields(pre_fields_va, pending_va))
    resolve_va = store_va + len(build_store_symbol(store_va, pending_va))
    save_va = resolve_va + len(build_resolve(resolve_va, names_va, images_va, len(names)))
    key_va = save_va + len(build_save_key(save_va, carry_va))
    pick_va = key_va + len(build_apply_key(key_va, carry_va))
    after_pick = pick_va + len(build_pick_image(pick_va, images_va, count))
    compare_va = after_pick if sort != "key" else None
    return _Layout(
        base_va,
        base_va + 4,
        keyword_va,
        pending_va,
        carry_va,
        images_va,
        names_va,
        strings_va,
        table_va,
        parse_va,
        pre_fields_va,
        store_va,
        resolve_va,
        save_va,
        key_va,
        pick_va,
        compare_va,
    )


def build_table(keyword_va: int, parse_va: int, stock_rows: bytes) -> bytes:
    """The rebuilt field-parse table: the 24 stock rows verbatim, this patch's row, the terminator.

    The stock rows are copied rather than rewritten because every pointer in them is absolute -
    their keyword strings stay where they are in ``.rdata``, and only the new row points into the
    cave. Its ``offset`` is 0 and unused: the parse function ignores the ``store`` it is handed
    and writes the cave's own global, which is what spares the patch from having to prove anything
    about the parse temporary's layout."""
    row = struct.pack("<IIII", keyword_va, parse_va, 0, 0)
    return stock_rows + row + bytes(FIELD_PARSE_STRIDE)


def build_parse_symbol(base_va: int, pending_va: int, count: int) -> bytes:
    """The field's parse function: read an `Int` the way `numPlayers` is read, clamp it, stash it.

    ``__cdecl(INI *, void *instance, void *store, const void *userData)``, which is the signature
    `INI_PARSE_FIELDS` calls a row with. The parsed value goes to a stack slot rather than to
    ``store``, because ``store`` points into the parse temporary and the temporary is not where
    this value has to end up - :func:`build_store_symbol` moves it onto the stored entry once that
    exists.

    An out-of-range or negative symbol becomes 0 rather than an error, which is the same answer
    as not writing the keyword: the row draws the stock medal. `jbe` does both tests at once,
    a negative `Int` being a very large unsigned one."""
    a = Asm(base_va)
    a.emit(b"\x83\xec\x04")  # sub  esp, 4            ; the Int the parser writes
    a.emit(b"\x6a\x00")  # push 0                 ; userData
    a.emit(b"\x8d\x44\x24\x04")  # lea  eax, [esp+4]      ; &slot
    a.emit(0x50)  # push eax               ; store
    a.emit(b"\x6a\x00")  # push 0                 ; instance
    a.emit(b"\xff\x74\x24\x14")  # push [esp+0x14]        ; ini
    a.call_absolute(INI_PARSE_INT)
    a.emit(b"\x83\xc4\x10")  # add  esp, 0x10
    a.emit(0x58)  # pop  eax               ; the parsed symbol
    a.emit(0x3D, _u32(count))  # cmp  eax, count
    a.jcc_short(JBE, "store")  # jbe  .store
    a.emit(b"\x33\xc0")  # xor  eax, eax          ; out of range reads as 'no symbol'
    a.label("store")
    a.emit(b"\xc1\xe0", SYMBOL_SHIFT)  # shl  eax, 16
    a.emit(0xA3, _u32(pending_va))  # mov  [pending], eax
    a.emit(0xC3)  # ret
    return a.finish()


def build_pre_fields(base_va: int, pending_va: int) -> bytes:
    """Clear the pending symbol, then run `INI_PARSE_FIELDS` unchanged.

    Entered in place of the ``call`` that reads a block's fields, so it runs once per `MapCache`
    block, after the block's name and before any of its keywords. That is what makes a block's
    symbol its own: `INI_PARSE_FIELDS` is ``__thiscall`` with two stack arguments and cleans them
    itself, so tail-jumping into it returns straight to the original caller with everything -
    ``ecx``, both arguments, the return address - exactly as the stock call left it."""
    a = Asm(base_va)
    a.emit(b"\x83\x25", _u32(pending_va), 0x00)  # and dword [pending], 0
    a.jmp_absolute(INI_PARSE_FIELDS)
    return a.finish()


def build_store_symbol(base_va: int, pending_va: int) -> bytes:
    """Copy the parsed block onto the stored entry, then write the symbol into its key.

    Entered by ``call`` in place of ``call MapMetaData::operator=``, with ``ecx`` the stored entry
    and the source still on the stack as that call's argument. The stock copy has to run **first**
    and has to run at all: it is what fills the entry, and it copies ``+0xF4`` from a
    freshly-constructed source, so anything written before it would be overwritten.

    The pending symbol is cleared on the way out as well as on the way in, so a block that is
    parsed but never stored cannot hand its symbol to the next one."""
    a = Asm(base_va)
    a.emit(0x51)  # push ecx               ; the stored entry
    a.emit(b"\xff\x74\x24\x08")  # push [esp+8]           ; the source, re-pushed
    a.call_absolute(MAP_META_DATA_ASSIGN)  # call operator=      ; ret 4
    a.emit(0x59)  # pop  ecx
    a.emit(0xA1, _u32(pending_va))  # mov  eax, [pending]
    a.emit(b"\x89\x81", _u32(MAP_META_DATA_SORT_KEY))  # mov [ecx+0xF4], eax
    a.emit(b"\x83\x25", _u32(pending_va), 0x00)  # and dword [pending], 0
    a.emit(b"\x8b\xc1")  # mov  eax, ecx          ; operator= returns the destination
    a.emit(b"\xc2\x04\x00")  # ret  4
    return a.finish()


def build_resolve(base_va: int, names_va: int, images_va: int, total: int) -> bytes:
    """Resolve every `AptMapSymbol...` name to an `Image *`, once per fill.

    Entered in place of the fill's first mapped-image lookup, so this patch's images are resolved
    on exactly the schedule the stock twelve are: every time the screen fills its list, and never
    cached across fills. A name the mod did not define resolves to NULL, which is what
    :func:`build_pick_image` reads as "fall back".

    The `AsciiString` the lookup wants is built and destroyed with the engine's own constructor
    and destructor, the way the stock lookups beside it do, rather than by handing the engine a
    static string object it might retain."""
    a = Asm(base_va)
    for reg in (0x50, 0x51, 0x52, 0x53, 0x56, 0x57):  # push eax, ecx, edx, ebx, esi, edi
        a.emit(reg)
    a.emit(b"\x83\xec\x04")  # sub  esp, 4            ; the AsciiString
    a.emit(b"\x33\xdb")  # xor  ebx, ebx          ; the index
    a.label("loop")
    a.emit(b"\x8b\x04\x9d", _u32(names_va))  # mov  eax, [names + ebx*4]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JE, "miss")  # je   .miss
    a.emit(0x50)  # push eax
    a.emit(b"\x8d\x4c\x24\x04")  # lea  ecx, [esp+4]      ; &the AsciiString
    a.call_absolute(ASCII_STRING_CTOR)  # call AsciiString(const char *)  ; ret 4
    a.emit(b"\x8b\x0d", _u32(OBJECT_IMAGE_UPGRADE_THE_IMAGES))  # mov ecx, [TheMappedImages]
    a.emit(b"\x8d\x04\x24")  # lea  eax, [esp]
    a.emit(0x50)  # push eax
    a.call_absolute(OBJECT_IMAGE_UPGRADE_FIND_IMAGE)  # call findImageByName    ; ret 4
    a.emit(b"\x8b\xf0")  # mov  esi, eax
    a.emit(b"\x8d\x0c\x24")  # lea  ecx, [esp]
    a.call_absolute(ASCII_STRING_DTOR)  # call ~AsciiString
    a.emit(b"\x89\x34\x9d", _u32(images_va))  # mov  [images + ebx*4], esi
    a.jmp_short("next")  # jmp  .next
    a.label("miss")
    a.emit(b"\x83\x24\x9d", _u32(images_va), 0x00)  # and dword [images + ebx*4], 0
    a.label("next")
    a.emit(0x43)  # inc  ebx
    a.emit(0x81, 0xFB, _u32(total))  # cmp  ebx, total
    a.jcc(JB, "loop")  # jb   .loop
    a.emit(b"\x83\xc4\x04")  # add  esp, 4
    for reg in (0x5F, 0x5E, 0x5B, 0x5A, 0x59, 0x58):  # pop edi, esi, ebx, edx, ecx, eax
        a.emit(reg)
    a.emit(0x68, _u32(0x00C54590))  # push <"AptDifficultyNotConquered">
    a.jmp_absolute(MAP_LIST_RESOLVE_RESUME)
    return a.finish()


def build_save_key(base_va: int, carry_va: int) -> bytes:
    """Save the entry's symbol bits before pass 1 overwrites its key.

    Entered in place of the two instructions that pick the next entry up, which is the last point
    at which ``+0xF4`` still holds what `parseMapCacheDefinition` put there. Both displaced
    instructions are reproduced, and the flags are preserved across the rest: the ``ZF`` the
    resume point branches on was set three bytes before the hook, by the test for a null stats
    object, and neither ``mov`` disturbs it."""
    a = Asm(base_va)
    a.emit(b"\x8b\x45\x08")  # mov  eax, [ebp+8]      ; the displaced pair
    a.emit(b"\x8b\x30")  # mov  esi, [eax]
    a.emit(0x9C)  # pushfd
    a.emit(b"\x8b\x86", _u32(MAP_META_DATA_SORT_KEY))  # mov eax, [esi+0xF4]
    a.emit(0x25, _u32(0xFFFF0000))  # and  eax, 0xFFFF0000
    a.emit(0xA3, _u32(carry_va))  # mov  [carry], eax
    a.emit(0x9D)  # popfd
    a.jmp_absolute(MAP_LIST_SAVE_KEY_RESUME)
    return a.finish()


def build_apply_key(base_va: int, carry_va: int) -> bytes:
    """Pass 1's tail: the stock `isOfficial` bit, then the symbol back on top of it.

    The displaced bytes are reproduced exactly, so a map with no symbol comes out of this hook
    holding the key the stock engine would have given it. ``eax`` is free here - the stock code
    reloads it two instructions past the resume point - and no branch downstream reads the flags
    this leaves."""
    a = Asm(base_va)
    a.emit(b"\x80\x7e", MAP_META_DATA_IS_OFFICIAL, 0x00)  # cmp byte [esi+0x26], 0
    a.jcc_short(JNE, "official")  # jne  .official
    a.emit(b"\x80\x8e", _u32(MAP_META_DATA_SORT_KEY + 1), 0x80)  # or byte [esi+0xF5], 0x80
    a.label("official")
    a.emit(0xA1, _u32(carry_va))  # mov  eax, [carry]
    a.emit(b"\x09\x86", _u32(MAP_META_DATA_SORT_KEY))  # or  [esi+0xF4], eax
    a.jmp_absolute(MAP_LIST_OFFICIAL_BIT_RESUME)
    return a.finish()


def build_pick_image(base_va: int, images_va: int, count: int) -> bytes:
    """Pass 2: draw this row's symbol, or hand the row back to the stock ladder.

    Three ways out, and the two that decline have to leave the stock ladder exactly what it
    expects: ``eax`` holding the key, and the flags of ``cmp eax, 0x8001``, which the ladder
    branches on five bytes past the resume point.

    The symbol's own way out skips the ladder entirely, writing the image into ``[ebp+8]`` - the
    same local the ladder's arms write - and jumping to where they converge. A symbol whose image
    for this difficulty is missing falls back to its bare name; a symbol with no image at all
    falls back to the stock medal, so a half-installed image set degrades a row at a time rather
    than blanking the column."""
    a = Asm(base_va)
    a.emit(b"\x8b\x86", _u32(MAP_META_DATA_SORT_KEY))  # mov eax, [esi+0xF4]
    a.emit(0x50)  # push eax               ; the key
    a.emit(b"\xc1\xe8", SYMBOL_SHIFT)  # shr  eax, 16
    a.jcc_short(JE, "stock")  # je   .stock           ; no symbol
    a.emit(0x3D, _u32(count))  # cmp  eax, count
    a.jcc_short(JA, "stock")  # ja   .stock           ; a symbol this build has no room for
    a.emit(0x48)  # dec  eax
    a.emit(b"\x6b\xc0", len(IMAGE_STATES))  # imul eax, eax, 7
    a.emit(b"\x8b\x0c\x24")  # mov  ecx, [esp]        ; the key again
    a.emit(b"\x83\xe1\x0f")  # and  ecx, 0x0F         ; the conquered state
    a.emit(b"\x83\xf9", len(IMAGE_STATES) - 1)  # cmp  ecx, 6
    a.jcc_short(JBE, "state")  # jbe  .state
    a.emit(b"\x33\xc9")  # xor  ecx, ecx          ; unreachable today; the bare name
    a.label("state")
    a.emit(0x50)  # push eax               ; this symbol's base index
    a.emit(b"\x03\xc1")  # add  eax, ecx
    a.emit(b"\x8b\x04\x85", _u32(images_va))  # mov  eax, [images + eax*4]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JNZ, "done")  # jnz  .done
    a.emit(b"\x8b\x04\x24")  # mov  eax, [esp]        ; the base index
    a.emit(b"\x8b\x04\x85", _u32(images_va))  # mov  eax, [images + eax*4]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JE, "unset")  # je   .unset
    a.label("done")
    a.emit(b"\x89\x45\x08")  # mov  [ebp+8], eax      ; the image this row draws
    a.emit(0x59)  # pop  ecx               ; drop the base index
    a.emit(0x58)  # pop  eax               ; the key, as the row's item data
    a.jmp_absolute(MAP_LIST_ROW_ADD)
    a.label("unset")
    a.emit(0x59)  # pop  ecx               ; drop the base index
    a.label("stock")
    a.emit(0x58)  # pop  eax               ; the key
    a.emit(0x3D, _u32(0x8001))  # cmp  eax, 0x8001       ; the displaced compare
    a.jmp_absolute(MAP_LIST_ICON_LADDER_RESUME)
    return a.finish()


def build_compare_symbols(base_va: int) -> bytes:
    """The comparator's key delta, with everything below the symbol masked off both operands.

    Installed only by ``--sort-by-symbol``. The stock arm subtracts the **whole** key, so two maps
    carrying the same symbol but a different conquered state never tie and the sort orders them by
    that state - which is the thing the option exists to stop. Masking makes them tie, and a tie
    falls through to the comparator's next key, which is the secondary sort column (the display
    name unless the header has been clicked).

    All four displaced instructions are reproduced. ``ebx`` and ``edi`` are the two entries and
    ``[ebp-0x10]`` the sort functor, all three of which the stock arm reads and none of which this
    touches; ``edx`` is scratch because the stock code zeroes it four bytes past the resume point.
    Nothing downstream reads the flags this leaves."""
    a = Asm(base_va)
    a.emit(b"\x8b\x83", _u32(MAP_META_DATA_SORT_KEY))  # mov  eax, [ebx+0xF4]
    a.emit(0x25, _u32(SYMBOL_MASK))  # and  eax, 0xFFFF0000
    a.emit(b"\x8b\x97", _u32(MAP_META_DATA_SORT_KEY))  # mov  edx, [edi+0xF4]
    a.emit(0x81, 0xE2, _u32(SYMBOL_MASK))  # and  edx, 0xFFFF0000
    a.emit(b"\x2b\xc2")  # sub  eax, edx
    a.emit(b"\x8b\x4d\xf0")  # mov  ecx, [ebp-0x10]   ; the displaced load
    a.emit(b"\x8b\x09")  # mov  ecx, [ecx]        ; ... and its deref
    a.jmp_absolute(MAP_LIST_COMPARE_KEY_RESUME)
    return a.finish()


def build_compare_icons(base_va: int) -> bytes:
    """The comparator's key delta, with the difficulty lifted above the `isOfficial` bit.

    Installed only by ``--sort-by-icon``. The stock key packs the symbol at bit 16, `isOfficial`
    being No at bit 15 and the conquered difficulty in the low nibble, so subtracting whole keys
    orders the column symbol, then star-before-hammer, then medal - and a symbol's maps beaten on
    one difficulty are split in two by that middle field. This ranks each operand as
    ``symbol | difficulty << 1 | official`` instead, which is the same three fields with the last
    two swapped, and subtracts the ranks.

    The rank cannot carry into the symbol: the difficulty is ``0``..``6``, so the two low fields
    together reach ``13`` and bit 15 is left clear. Nothing is masked away, so untagged maps keep
    ordering against each other exactly as the difficulty and the star/hammer say - the option
    reorders the column, it does not coarsen it.

    All four displaced instructions are reproduced. The ranking is a local subroutine because it
    runs on both operands; it reads ``eax`` and writes ``eax``, ``ecx`` and ``edx``, all three of
    which this arm is free to spend - ``ecx`` because the displaced load rewrites it on the way
    out, ``edx`` because the stock code zeroes it four bytes past the resume point."""
    a = Asm(base_va)
    a.emit(b"\x8b\x83", _u32(MAP_META_DATA_SORT_KEY))  # mov  eax, [ebx+0xF4]
    a.call("rank")
    a.emit(0x50)  # push eax               ; the left rank
    a.emit(b"\x8b\x87", _u32(MAP_META_DATA_SORT_KEY))  # mov  eax, [edi+0xF4]
    a.call("rank")
    a.emit(b"\x8b\xd0")  # mov  edx, eax          ; the right rank
    a.emit(0x58)  # pop  eax               ; ... and the left one back
    a.emit(b"\x2b\xc2")  # sub  eax, edx
    a.emit(b"\x8b\x4d\xf0")  # mov  ecx, [ebp-0x10]   ; the displaced load
    a.emit(b"\x8b\x09")  # mov  ecx, [ecx]        ; ... and its deref
    a.jmp_absolute(MAP_LIST_COMPARE_KEY_RESUME)

    a.label("rank")
    a.emit(b"\x8b\xc8")  # mov  ecx, eax
    a.emit(0x81, 0xE1, _u32(SYMBOL_MASK))  # and  ecx, 0xFFFF0000   ; the symbol, kept in place
    a.emit(b"\x8b\xd0")  # mov  edx, eax
    a.emit(0x83, 0xE2, DIFFICULTY_MASK)  # and  edx, 0xF          ; the conquered difficulty
    a.emit(0xC1, 0xE8, OFFICIAL_SHIFT)  # shr  eax, 15
    a.emit(b"\x83\xe0\x01")  # and  eax, 1            ; isOfficial == No
    a.emit(b"\x8d\x04\x50")  # lea  eax, [eax+edx*2]  ; difficulty above it
    a.emit(b"\x0b\xc1")  # or   eax, ecx
    a.emit(0xC3)  # ret
    return a.finish()


def _jmp_bytes(from_va: int, to_va: int, width: int) -> bytes:
    """A ``jmp rel32`` to ``to_va``, padded with ``nop`` out to ``width``."""
    return b"\xe9" + struct.pack("<i", to_va - (from_va + 5)) + b"\x90" * (width - 5)


class MapListSymbolsPatch(Patch):
    """`mapSymbol` on a `MapCache` entry: its own icon in the lobby map list, and its own place in
    the sort."""

    name = "map-list-symbols"
    author = "officialNecro"
    description = (
        "Add mapSymbol to a MapCache entry, a number from 1 to the installed count that gives the "
        "map its own icon in the skirmish and multiplayer map list instead of the stock star or "
        "hammer, and its own group when the list is sorted by that column. Each symbol NN draws "
        "the MappedImage AptMapSymbolNN<state>, <state> being NotConquered, EasyConquered, "
        "MedConquered, HardConquered, BrutalConquered or MaxConquered, and falls back to a bare "
        "AptMapSymbolNN and then to the stock medal; mapSymbol 0, the default, is stock. "
        "--sort-by-symbol makes that column sort by the symbol alone, so maps sharing one group "
        "together in name order rather than by how far each has been beaten, and --sort-by-icon "
        "sorts it by the picture drawn - symbol, then medal, then star or hammer. Note that a "
        "mapcache.ini using the keyword will not load on an unpatched game.dat"
    )

    def __init__(
        self,
        keyword: str = DEFAULT_KEYWORD,
        symbols: int = DEFAULT_SYMBOLS,
        sort: str = DEFAULT_SORT,
    ):
        self.keyword = keyword
        self.symbols = symbols
        self.sort = sort
        validate_keyword(keyword)
        if not 1 <= symbols <= MAX_SYMBOLS:
            raise ValueError(f"symbols must be between 1 and {MAX_SYMBOLS}, not {symbols}")
        if sort not in SORT_MODES:
            raise ValueError(f"sort must be one of {', '.join(SORT_MODES)}, not {sort!r}")

    def __str__(self) -> str:
        sorting = {"key": "", "symbol": ", symbol-only sort", "icon": ", icon-order sort"}
        return f"{self.name} ({self.keyword}, {self.symbols} symbols{sorting[self.sort]})"

    @property
    def _flags(self) -> int:
        return {"key": 0, "symbol": FLAG_SORT_BY_SYMBOL, "icon": FLAG_SORT_BY_ICON}[self.sort]

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        stock_rows = self._read_stock_table(data)

        base_va = allocate_section(
            data,
            SECTION_NAME,
            lambda va: self._build(va, stock_rows),
            SECTION_CHARACTERISTICS,
        )
        pieces = _layout(base_va, self.keyword, self.symbols, self.sort)
        for file_off, old, new, note in self._edits(data, pieces):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch with exactly this keyword and count.

        Locates the cave, recomputes everything the two parameters imply and compares it and every
        rewritten site to what is on disk. Reads only via ``struct`` and the section table, so
        verification needs no disassembler.

        The stock rows are read back **out of the cave's own copy** rather than from the address
        they came from, because that address still holds them: on a patched image it would only
        ever confirm the copy against itself."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, vsize = located

        installed = self._installed_parameters(data, section_va)
        if installed != (self.keyword, self.symbols, self.sort):
            return [f"{SECTION_NAME} was built for {installed!r}, not this patch's parameters"]

        pieces = _layout(section_va, self.keyword, self.symbols, self.sort)
        problems: list[str] = []
        try:
            content = self._build(section_va, self._copied_rows(data, pieces))
            edits = self._edits(data, pieces)
        except (ValueError, struct.error) as exc:
            return [f"cannot recompute the expected cave (wrong build?): {exc}"]

        if len(content) > vsize:
            return [f"{SECTION_NAME} holds {vsize} bytes, too few for this patch's cave"]
        if bytes(data[section_off : section_off + len(content)]) != content:
            problems.append(
                f"{SECTION_NAME} does not match {self.keyword!r} at {self.symbols} symbols "
                "(the table, names or stubs differ)"
            )
        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")

        problems += self._table_problems(data, pieces)
        problems += self._anchor_problems(data)
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> MapListSymbolsPatch | None:
        """Recognise this patch **and recover its parameters**.

        The default probe would only ever recognise a default-built one. The count is the cave's
        first dword and the keyword the string after it, so both read straight back out; `verify`
        then checks the whole cave against them."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        try:
            patch = cls(*cls._installed_parameters(data, located[0]))
        except (ValueError, struct.error, TypeError):
            return None
        return None if patch.verify(data) else patch

    def ini_surface(self) -> Engine:
        """Nothing, deliberately.

        `mapSymbol` is a real INI keyword, but `maps\\mapcache.ini` is not part of the INI surface
        `sage_ini` models: the file is parsed through a callback of its own rather than through the
        engine's block-type table, and no `MapCache` block exists in the schema to add a field to.
        Declaring one here would invent a block rather than describe a patched one."""
        return super().ini_surface()

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--keyword",
            default=DEFAULT_KEYWORD,
            metavar="NAME",
            help=(
                f"name of the field to add to a MapCache entry (default {DEFAULT_KEYWORD}); "
                "letters, digits and underscores, and must not already be one of the block's 24 "
                "fields"
            ),
        )
        parser.add_argument(
            "--symbols",
            type=int,
            default=DEFAULT_SYMBOLS,
            metavar="N",
            help=(
                f"how many symbols to make room for, 1..{MAX_SYMBOLS} (default {DEFAULT_SYMBOLS}); "
                "each one costs seven MappedImage names in the binary and none of them has to be "
                "defined"
            ),
        )

        # The two hook the same seventeen bytes of the comparator, so at most one can be installed.
        sorting = parser.add_mutually_exclusive_group()
        sorting.add_argument(
            "--sort-by-symbol",
            action="store_true",
            help=(
                "sort the icon column by the symbol alone. Without it that column sorts on the "
                "whole key, so maps sharing a symbol are grouped but ordered inside the group by "
                "the star/hammer and then by how far each has been beaten; with it they tie and "
                "fall through to the secondary column, which is the map name unless another "
                "header has been clicked. The icon still tracks the conquered state either way"
            ),
        )
        sorting.add_argument(
            "--sort-by-icon",
            action="store_true",
            help=(
                "sort the icon column by the picture it draws: the symbol first, then the "
                "conquered medal, then the star/hammer. Every map carrying one symbol and beaten "
                "on one difficulty is contiguous, where the default splits that run in two "
                "because it puts official-before-user above the medal. Nothing is discarded, so "
                "untagged maps still order by medal and then star/hammer"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> MapListSymbolsPatch:
        sort = "symbol" if args.sort_by_symbol else "icon" if args.sort_by_icon else DEFAULT_SORT
        return cls(keyword=args.keyword, symbols=args.symbols, sort=sort)

    @staticmethod
    def _installed_parameters(data: bytes | bytearray, section_va: int) -> tuple[str, int, str]:
        off = va_to_offset(data, section_va)
        if off is None:
            raise ValueError(f"the {SECTION_NAME} base 0x{section_va:08x} is not mapped")
        count, flags = struct.unpack_from("<2I", data, off)
        keyword = _read_cstring(data, section_va + 8)
        if keyword is None:
            raise ValueError(f"no keyword string at the {SECTION_NAME} base")
        sort = {0: "key", FLAG_SORT_BY_SYMBOL: "symbol", FLAG_SORT_BY_ICON: "icon"}.get(flags)
        if sort is None:
            raise ValueError(f"unrecognised {SECTION_NAME} flags 0x{flags:x}")
        return keyword, count, sort

    def _build(self, base_va: int, stock_rows: bytes) -> bytes:
        """The cave: the count, the keyword, the two globals, the image array and its names, the
        rebuilt field table, then the seven stubs - in that order, so :meth:`detect` finds both
        parameters at the section base."""
        pieces = _layout(base_va, self.keyword, self.symbols, self.sort)
        names = image_names(self.symbols)

        blob = bytearray(_u32(self.symbols) + _u32(self._flags))
        blob += self.keyword.encode("ascii") + b"\x00"
        blob += bytes(pieces.pending_va - (base_va + len(blob)))
        blob += bytes(8)  # the pending symbol and the per-entry carry, both zero at rest
        blob += bytes(len(names) * 4)  # the images the fill resolves into

        offsets = bytearray()
        strings = bytearray()
        for name in names:
            offsets += _u32(pieces.strings_va + len(strings))
            strings += name.encode("ascii") + b"\x00"
        blob += offsets + strings
        blob += bytes(pieces.table_va - (base_va + len(blob)))

        blob += build_table(pieces.keyword_va, pieces.parse_va, stock_rows)
        assert base_va + len(blob) == pieces.parse_va, "the cave layout and its addresses disagree"

        blob += build_parse_symbol(pieces.parse_va, pieces.pending_va, self.symbols)
        blob += build_pre_fields(pieces.pre_fields_va, pieces.pending_va)
        blob += build_store_symbol(pieces.store_va, pieces.pending_va)
        blob += build_resolve(pieces.resolve_va, pieces.names_va, pieces.images_va, len(names))
        blob += build_save_key(pieces.save_va, pieces.carry_va)
        blob += build_apply_key(pieces.key_va, pieces.carry_va)
        blob += build_pick_image(pieces.pick_va, pieces.images_va, self.symbols)
        if pieces.compare_va is not None:
            builder = build_compare_symbols if self.sort == "symbol" else build_compare_icons
            blob += builder(pieces.compare_va)
        return bytes(blob)

    def _read_stock_table(self, data: bytes | bytearray) -> bytes:
        """The 24 stock entries verbatim, after checking they really are this build's `MapCache`
        table: every keyword and every offset into the parse temporary must match, and the
        twenty-fifth entry must be the NULL terminator."""
        off = va_to_offset(data, MAP_CACHE_FIELD_TABLE)
        if off is None:
            raise ValueError(f"the field table VA 0x{MAP_CACHE_FIELD_TABLE:08x} is not mapped")

        size = len(MAP_CACHE_STOCK_FIELDS) * FIELD_PARSE_STRIDE
        entries = bytes(data[off : off + size])
        if len(entries) != size:
            raise ValueError("the field table runs past the end of the image")

        for index, (name, offset) in enumerate(MAP_CACHE_STOCK_FIELDS):
            name_va, _parse, _userdata, field_off = struct.unpack_from(
                "<4I", entries, index * FIELD_PARSE_STRIDE
            )
            got = _read_cstring(data, name_va)
            if got != name:
                raise ValueError(f"field table entry {index}: expected {name!r}, found {got!r}")
            if field_off != offset:
                raise ValueError(
                    f"field table entry {name!r}: expected offset 0x{offset:x}, "
                    f"found 0x{field_off:x}"
                )

        terminator = bytes(data[off + size : off + size + FIELD_PARSE_STRIDE])
        if terminator != bytes(FIELD_PARSE_STRIDE):
            raise ValueError(
                "the field table is not NULL-terminated after "
                f"{len(MAP_CACHE_STOCK_FIELDS)} entries "
                f"(found {terminator.hex()})"
            )
        return entries

    def _copied_rows(self, data: bytes | bytearray, pieces: _Layout) -> bytes:
        off = va_to_offset(data, pieces.table_va)
        if off is None:
            raise ValueError(f"the rebuilt table at 0x{pieces.table_va:08x} is not mapped")
        return bytes(data[off : off + len(MAP_CACHE_STOCK_FIELDS) * FIELD_PARSE_STRIDE])

    def _table_problems(self, data: bytes | bytearray, pieces: _Layout) -> list[str]:
        """What the rebuilt table has to spell: the 24 stock keywords still at their stock offsets,
        then this patch's row, parsed by the cave's own function."""
        problems: list[str] = []
        off = va_to_offset(data, pieces.table_va)
        if off is None:
            return [f"the rebuilt table at 0x{pieces.table_va:08x} is not mapped"]

        for index, (name, offset) in enumerate(MAP_CACHE_STOCK_FIELDS):
            name_va, _parse, _ud, field_off = struct.unpack_from(
                "<4I", data, off + index * FIELD_PARSE_STRIDE
            )
            got = _read_cstring(data, name_va)
            if got != name or field_off != offset:
                problems.append(
                    f"rebuilt table entry {index}: expected {name!r} at 0x{offset:x}, "
                    f"found {got!r} at 0x{field_off:x}"
                )

        row = off + len(MAP_CACHE_STOCK_FIELDS) * FIELD_PARSE_STRIDE
        name_va, parse_fn, _ud, _field_off = struct.unpack_from("<4I", data, row)
        got = _read_cstring(data, name_va)
        if got != self.keyword:
            problems.append(f"the added field is called {got!r}, not {self.keyword!r}")
        if parse_fn != pieces.parse_va:
            problems.append(
                f"the added field parses with 0x{parse_fn:08x}, not 0x{pieces.parse_va:08x}"
            )
        terminator = bytes(data[row + FIELD_PARSE_STRIDE : row + 2 * FIELD_PARSE_STRIDE])
        if terminator != bytes(FIELD_PARSE_STRIDE):
            problems.append(f"the rebuilt table is not NULL-terminated (found {terminator.hex()})")
        return problems

    def _anchor_problems(self, data: bytes | bytearray) -> list[str]:
        """Everything the patch depends on and does not rewrite: the assignment operator its store
        hook wraps, the insert whose ``ret 4`` leaves that call's argument behind, and the
        mapped-image lookup's convention.

        The comparator's key delta joins them only in the stock sort mode, because the other two
        rewrite it - and then the edit's own stock-byte assertion is the check instead. It is the
        same evidence either way: this arm is what makes ``+0xF4`` order the list."""
        anchors = dict(MAP_LIST_ANCHORS)
        if self.sort == "key":
            anchors[MAP_LIST_COMPARE_KEY] = MAP_LIST_COMPARE_KEY_BYTES
        problems: list[str] = []
        for va, expected in anchors.items():
            off = va_to_offset(data, va)
            if off is None:
                problems.append(f"anchor 0x{va:08x} is not mapped - not the expected build")
                continue
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                problems.append(f"anchor 0x{va:08x}: expected {expected.hex()}, got {got.hex()}")
        return problems

    def _check_anchors(self, data: bytes | bytearray) -> None:
        problems = self._anchor_problems(data)
        if problems:
            raise ValueError(f"{self.name}: this is not the expected build: {'; '.join(problems)}")

    def _edits(
        self, data: bytes | bytearray, pieces: _Layout
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte range this patch rewrites, as ``(file offset, old, new, note)``."""
        edits: list[tuple[int, bytes, bytes, str]] = []

        def at(va: int, old: bytes, new: bytes, note: str) -> None:
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{note}: VA 0x{va:08x} is not mapped")
            edits.append((off, old, new, note))

        at(
            MAP_CACHE_FIELD_TABLE_GETTER_REF,
            _u32(MAP_CACHE_FIELD_TABLE),
            _u32(pieces.table_va),
            f"the MapCache field-table getter -> the {SECTION_NAME} table",
        )
        at(
            MAP_CACHE_FIELD_TABLE_PARSE_REF,
            _u32(MAP_CACHE_FIELD_TABLE),
            _u32(pieces.table_va),
            f"parseMapCacheDefinition -> the {SECTION_NAME} table",
        )
        at(
            MAP_CACHE_PARSE_FIELDS,
            MAP_CACHE_PARSE_FIELDS_BYTES,
            b"\xe8" + struct.pack("<i", pieces.pre_fields_va - (MAP_CACHE_PARSE_FIELDS + 5)),
            f"each MapCache block starts with no pending {self.keyword}",
        )
        at(
            MAP_CACHE_ASSIGN_CALL,
            MAP_CACHE_ASSIGN_CALL_BYTES,
            b"\xe8" + struct.pack("<i", pieces.store_va - (MAP_CACHE_ASSIGN_CALL + 5)),
            f"the stored MapMetaData carries its {self.keyword}",
        )
        at(
            MAP_LIST_RESOLVE,
            MAP_LIST_RESOLVE_BYTES,
            _jmp_bytes(MAP_LIST_RESOLVE, pieces.resolve_va, len(MAP_LIST_RESOLVE_BYTES)),
            f"the map-list fill resolves {self.symbols * len(IMAGE_STATES)} symbol images",
        )
        at(
            MAP_LIST_SAVE_KEY,
            MAP_LIST_SAVE_KEY_BYTES,
            _jmp_bytes(MAP_LIST_SAVE_KEY, pieces.save_va, len(MAP_LIST_SAVE_KEY_BYTES)),
            "pass 1 remembers each entry's symbol before it rewrites the key",
        )
        at(
            MAP_LIST_OFFICIAL_BIT,
            MAP_LIST_OFFICIAL_BIT_BYTES,
            _jmp_bytes(MAP_LIST_OFFICIAL_BIT, pieces.key_va, len(MAP_LIST_OFFICIAL_BIT_BYTES)),
            "pass 1 puts the symbol back on top of the isOfficial bit",
        )
        at(
            MAP_LIST_ICON_LADDER,
            MAP_LIST_ICON_LADDER_BYTES,
            _jmp_bytes(MAP_LIST_ICON_LADDER, pieces.pick_va, len(MAP_LIST_ICON_LADDER_BYTES)),
            "pass 2 draws a symbol's image where the stock medal would go",
        )
        if pieces.compare_va is not None:
            at(
                MAP_LIST_COMPARE_KEY,
                MAP_LIST_COMPARE_KEY_BYTES,
                _jmp_bytes(
                    MAP_LIST_COMPARE_KEY, pieces.compare_va, len(MAP_LIST_COMPARE_KEY_BYTES)
                ),
                (
                    f"the icon column sorts on {self.keyword} alone"
                    if self.sort == "symbol"
                    else f"the icon column sorts on {self.keyword}, then the conquered medal"
                ),
            )
        return edits
