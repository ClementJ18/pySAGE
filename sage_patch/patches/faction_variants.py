"""Group a mod's faction variants under their faction in the game-setup screen.

A `PlayerTemplate` gains `VariantOf = <PlayerTemplate>`. A variant stays a whole, independent
template - its own index, its own spellbook, its own AI - so the wire format, replays and every
tool that names a faction by template are untouched; what changes is only how the lobby shows it:

* the faction combo box lists base factions only, and shows a variant's slot as its base;
* a second combo box per slot, `~<slot>.Variant` in the movie, lists the base (as
  `GUI:FactionVariantStandard`) and every playable variant of it - the base alone for a faction
  that has none;
* picking in it asks for the template exactly as the faction box does, through the screen's own
  strategy object, so skirmish, LAN host and LAN client each behave as they already do;
* Random resolves among base factions only, so a faction with three variants is not three times
  as likely.

The movie half is not this patch: the lobby only has a `Variant` box if `MpGameSetup.apt` places
one. Without it every hook degrades to stock except the faction box's filter - variants would then
be unreachable - which is why the ini side is opt-in: no `VariantOf`, nothing is filtered.

Derivation: `../docs/faction-variants.md`.
"""

from __future__ import annotations

import struct

from sage_ini.engine import Engine, FieldDelta

from ..addresses import (
    COMBO_BOX_ADD_ENTRY,
    COMBO_BOX_DROPDOWN_BUTTON,
    COMBO_BOX_ENTRY_COUNT,
    COMBO_BOX_GADGET_DATA,
    COMBO_BOX_GET_ITEM_DATA,
    COMBO_BOX_GET_SELECTED,
    COMBO_BOX_OPEN_GATE,
    COMBO_BOX_OPEN_GATE_BYTES,
    COMBO_BOX_OPEN_GO,
    COMBO_BOX_OPEN_SKIP,
    COMBO_BOX_RESET,
    COMBO_BOX_SET_DROPDOWN_LINES,
    COMBO_BOX_SET_ITEM_DATA,
    COMBO_BOX_SET_SELECTED,
    COMBO_BOX_TOGGLE_BOX_EBP,
    GAME_INFO_GET_SLOT,
    GAME_LOGIC_RANDOM_VALUE,
    GAME_LOGIC_SOURCE_FILE,
    GAME_SLOT_PLAYER_TEMPLATE,
    GAME_SLOT_SET_PLAYER_TEMPLATE,
    GAME_SLOT_TEMPLATE_BOUNDS,
    GAME_START_RANDOM_ASSIGN,
    GAME_START_RANDOM_ASSIGN_BYTES,
    GAME_START_RANDOM_ASSIGN_RESUME,
    GAME_START_RANDOM_CANDIDATES_EBP,
    GAME_START_RANDOM_DRAW,
    GAME_START_RANDOM_DRAW_BYTES,
    GAME_START_RANDOM_DRAW_RESUME,
    GAME_START_RANDOM_POOL,
    GAME_START_RANDOM_POOL_BYTES,
    GAME_START_RANDOM_POOL_INDEX_EBP,
    GAME_START_RANDOM_POOL_RESUME,
    GAME_START_RANDOM_POOL_SKIP,
    GAME_START_RANDOM_SLOT_EBP,
    GAME_START_SLOT_TEMPLATE,
    GAME_START_SLOT_TEMPLATE_BYTES,
    GAME_START_SLOT_TEMPLATE_RESUME,
    GAME_TEXT_FETCH_SLOT,
    GUI_RANDOM_LABEL,
    INI_NEXT_TOKEN_OR_NULL,
    MAP_PREVIEW_OBSERVER_SKIPS,
    MP_SETUP_CTOR_FACTION_WINDOWS_CLEAR,
    MP_SETUP_CTOR_FACTION_WINDOWS_CLEAR_BYTES,
    MP_SETUP_DIRTY,
    MP_SETUP_DROPDOWN_LINES,
    MP_SETUP_FACTION_COMBO,
    MP_SETUP_FACTION_COMBO_CALLS,
    MP_SETUP_FACTION_ENABLE_CALL,
    MP_SETUP_FACTION_ENABLE_CALL_BYTES,
    MP_SETUP_FACTION_LIST_INDEX_EBP,
    MP_SETUP_FACTION_LIST_PLAYABLE,
    MP_SETUP_FACTION_LIST_PLAYABLE_BYTES,
    MP_SETUP_FACTION_LIST_PLAYABLE_RESUME,
    MP_SETUP_FACTION_LIST_SKIP,
    MP_SETUP_FACTION_REQUEST_PENDING,
    MP_SETUP_FACTION_WINDOWS,
    MP_SETUP_GADGET_FILED,
    MP_SETUP_GADGET_HERO_TEST,
    MP_SETUP_GADGET_HERO_TEST_BYTES,
    MP_SETUP_GADGET_HERO_TEST_RESUME,
    MP_SETUP_GADGET_SLOT_EBP,
    MP_SETUP_GADGET_UNKNOWN,
    MP_SETUP_GAME_INFO,
    MP_SETUP_GET_GAME_INFO,
    MP_SETUP_HISTORICAL_FLAGS,
    MP_SETUP_MODE,
    MP_SETUP_MODE_WOTR,
    MP_SETUP_REDRAW_SLOT,
    MP_SETUP_SELECTION_DONE,
    MP_SETUP_SELECTION_UNMATCHED,
    MP_SETUP_SELECTION_UNMATCHED_BYTES,
    MP_SETUP_STRATEGY,
    MP_SETUP_STRATEGY_REQUEST_TEMPLATE_SLOT,
    MP_SETUP_SYNC_FACTION,
    MP_SETUP_SYNC_FACTION_CALLS,
    MP_SETUP_SYNC_FACTION_TEMPLATE,
    MP_SETUP_SYNC_FACTION_TEMPLATE_BYTES,
    MP_SETUP_SYNC_FACTION_TEMPLATE_RESUME,
    MP_SETUP_WOTR,
    MP_SETUP_WOTR_IS_HISTORICAL,
    MULTIPLAYER_COLOR_VALUE,
    MULTIPLAYER_SETTINGS_GET_COLOR,
    NAME_KEY_FROM_CSTR,
    PLAYER_TEMPLATE_EVIL,
    PLAYER_TEMPLATE_FIELD_TABLE_REF_OPCODES,
    PLAYER_TEMPLATE_FIELD_TABLE_REFS,
    PLAYER_TEMPLATE_FIND_BY_INDEX,
    PLAYER_TEMPLATE_GET_DISPLAY_NAME,
    PLAYER_TEMPLATE_IS_OBSERVER,
    PLAYER_TEMPLATE_NAME_KEY,
    PLAYER_TEMPLATE_PARSED_JOIN,
    PLAYER_TEMPLATE_PARSED_JOIN_BYTES,
    PLAYER_TEMPLATE_PARSED_JOIN_RESUME,
    PLAYER_TEMPLATE_PARSED_NEW_KEY,
    PLAYER_TEMPLATE_PARSED_NEW_KEY_BYTES,
    PLAYER_TEMPLATE_PARSED_NEW_KEY_RESUME,
    PLAYER_TEMPLATE_PLAYABLE_SIDE,
    PLAYER_TEMPLATE_SIZE,
    PLAYER_TEMPLATE_STORE_BEGIN,
    PLAYER_TEMPLATE_STORE_END,
    STRICMP,
    THE_GAME_TEXT,
    THE_MULTIPLAYER_SETTINGS,
    THE_NAME_KEY_GENERATOR,
    THE_PLAYER_TEMPLATE_STORE,
    UNICODE_STRING_CONCAT,
    UNICODE_STRING_DTOR,
    WINDOW_ENABLE,
    WINDOW_HIDE,
    WINDOW_STATUS,
    WINDOW_STATUS_ENABLED,
    WINDOW_STATUS_HIDDEN,
)
from ..asm import JAE, JE, JG, JGE, JL, JLE, JNE, Asm
from ..patcher import Patch
from ..utils import (
    allocate_section,
    apply_byte_patch,
    find_section,
    i8,
    jmp_rel32,
    read_cstring,
    u32,
    va_to_offset,
)
from .utils.field_tables import Entry, entries_before, read_field_table, resolve_table

__all__ = [
    "EVIL_LABEL",
    "FIELD_NAME",
    "GADGET_KIND",
    "GOOD_LABEL",
    "RANDOM_OF",
    "RANDOM_EVIL",
    "RANDOM_GOOD",
    "RANDOM_OF_MAX_INDEX",
    "RANDOM_STANDARD",
    "RANDOM_VARIANT",
    "RANDOM_VARIANTS",
    "ROWS",
    "SECTION_NAME",
    "SLOTS",
    "STANDARD_LABEL",
    "VARIANTS_LABEL",
    "FactionVariantsPatch",
    "build_section",
    "layout",
]

SECTION_NAME = ".facvar"  # 7 chars: the PE name field is 8 bytes and truncates silently

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE: code, the rebuilt field
# table, and state written at INI load and while the setup screen is up.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: The `PlayerTemplate` keyword this patch adds.
FIELD_NAME = "VariantOf"

#: The name the movie gives the second box in each slot row, beside `PlayerTemplate`, `Hero` and
#: the other kinds the gadget binder already files.
GADGET_KIND = "Variant"

#: The string table label of the variant box's first row, the base faction itself. It is a
#: `swprintf` format with one argument, the faction's display name (or `GUI:Random`'s text on a
#: Random slot): `Standard` ignores it, `%s` shows it. `%s` is the only directive it may use -
#: anything else would read an argument that is not there.
STANDARD_LABEL = "GUI:FactionVariantStandard"

#: The string table label of a Random slot's third row, `RANDOM_VARIANTS`.
VARIANTS_LABEL = "GUI:FactionVariantVariants"

#: The string table labels of a Random slot's `RANDOM_GOOD` and `RANDOM_EVIL` rows.
GOOD_LABEL = "GUI:FactionVariantGood"
EVIL_LABEL = "GUI:FactionVariantEvil"

#: A slot's template while it is Random. The stock sentinel, -1, draws a base faction and plays it
#: as it stands - "Standard". The patch adds -3 beside it for "Random": a base faction, then a
#: draw among it and its variants. -2 is Observer.
RANDOM_STANDARD = -1
RANDOM_VARIANT = -3
#: "Variants": one of every faction's playable variants, drawn uniformly - no base faction.
#: With no variant in the mod it falls back to `RANDOM_STANDARD`.
RANDOM_VARIANTS = -4
#: "Good" and "Evil": a base faction drawn as for `RANDOM_STANDARD`, from only the candidates whose
#: `PlayerTemplate` says `Evil = No` / `Evil = Yes`, and played as it stands. A slot whose
#: candidates hold none of that side draws from all of them instead.
RANDOM_GOOD = -5
RANDOM_EVIL = -6
_OBSERVER = -2

#: A slot's template for "this faction, a random variant of it": `RANDOM_OF - index`, so faction
#: 5 is -21. Resolved at game start to the faction or one of its playable variants, before the
#: Random draw would see it. The LAN packet carries a template as a signed byte, which is what
#: bounds the index: `RANDOM_OF - RANDOM_OF_MAX_INDEX` is -128, and a faction past it gets no
#: Random row.
RANDOM_OF = -16
RANDOM_OF_MAX_INDEX = 112

#: The lowest template any reader has to accept once `RANDOM_OF` is in play.
_LOWEST_TEMPLATE = RANDOM_OF - RANDOM_OF_MAX_INDEX

#: Lobby slots. The screen's own per-slot arrays hold eight, and so do this cave's.
SLOTS = 8

#: `VariantOf` declarations the table holds. Edain defines about forty `PlayerTemplate` blocks, so
#: this is room, not a design limit; a declaration past it is parsed and dropped.
ROWS = 128

#: Names the `PlayerTemplate` table must carry at these offsets, or this is not the build these
#: addresses came from. Checked by name so another patch having extended the table first is fine.
_FINGERPRINT = {
    "IsObserver": PLAYER_TEMPLATE_IS_OBSERVER,
    "PlayableSide": PLAYER_TEMPLATE_PLAYABLE_SIDE,
    "DisplayName": 0x14,
}


def _call_target(original: bytes, site: int) -> int:
    """Where the stock `call rel32` in `original`, at `site`, goes."""
    if original[0] != 0xE8:
        raise ValueError(f"0x{site:08x} does not hold a call")
    return site + 5 + struct.unpack_from("<i", original, 1)[0]


#: The CRT `memset` the constructor calls, read off the call it makes rather than restated.
_MEMSET = _call_target(
    MP_SETUP_CTOR_FACTION_WINDOWS_CLEAR_BYTES, MP_SETUP_CTOR_FACTION_WINDOWS_CLEAR
)
if _call_target(MP_SETUP_FACTION_ENABLE_CALL_BYTES, MP_SETUP_FACTION_ENABLE_CALL) != WINDOW_ENABLE:
    raise ValueError("MP_SETUP_FACTION_ENABLE_CALL does not call WINDOW_ENABLE")

# The cave's data, ahead of the rebuilt field table and the code.
_PENDING_OFF = 0x00  # the parent key `VariantOf` read, until the block's own key is written
_COUNT_OFF = 0x04  # declarations in the table
_BOXES_OFF = 0x08  # per slot: the Variant window
_OWNERS_OFF = _BOXES_OFF + SLOTS * 4  # per slot: the screen that filed it
_ITEMS_OFF = _OWNERS_OFF + SLOTS * 4  # per slot: rows the Variant box holds
_ROWS_OFF = _ITEMS_OFF + SLOTS * 4  # {key, parent key} per declaration
_STRINGS_OFF = _ROWS_OFF + ROWS * 8
#: Everything the setup screen's constructor clears, in dwords: boxes, owners and item counts.
_SLOT_STATE_DWORDS = 3 * SLOTS


def _strings() -> bytes:
    """The C strings the cave names - the gadget kind and the row labels - and an
    empty wide string, the name a template without one is formatted with."""
    out = bytearray()
    for text in (GADGET_KIND, STANDARD_LABEL, VARIANTS_LABEL, GOOD_LABEL, EVIL_LABEL):
        out += text.encode("ascii") + b"\x00"
    out += b"\x00" * (-len(out) % 4)
    return bytes(out) + bytes(4)


_KIND_OFF = _STRINGS_OFF
_LABEL_OFF = _STRINGS_OFF + len(GADGET_KIND) + 1
_VARIANTS_LABEL_OFF = _LABEL_OFF + len(STANDARD_LABEL) + 1
_GOOD_LABEL_OFF = _VARIANTS_LABEL_OFF + len(VARIANTS_LABEL) + 1
_EVIL_LABEL_OFF = _GOOD_LABEL_OFF + len(GOOD_LABEL) + 1
_WIDE_EMPTY_OFF = _STRINGS_OFF + len(_strings()) - 4
_TABLE_OFF = _STRINGS_OFF + len(_strings())


def _table_span(entries: tuple[Entry, ...]) -> int:
    """The rebuilt field table plus its one padded name string, in bytes."""
    name = len(FIELD_NAME) + 1
    return (len(entries) + 2) * 16 + name + (-name % 4)


def _table_bytes(table_va: int, entries: tuple[Entry, ...], parse_fn: int) -> bytes:
    """The live `PlayerTemplate` table by pointer, the `VariantOf` row, the terminator, and the
    row's name. Offset 0: the value lands in the cave's table, never in the template."""
    table_size = (len(entries) + 2) * 16
    out = bytearray()
    for entry in entries:
        out += struct.pack("<IIII", *entry)
    out += struct.pack("<IIII", table_va + table_size, parse_fn, 0, 0)
    out += bytes(16)
    out += FIELD_NAME.encode("ascii") + b"\x00"
    out += b"\x00" * (-len(out) % 4)
    assert len(out) == _table_span(entries)
    return bytes(out)


class _Layout:
    """The cave's data addresses for one base, so the emitters say `lay.boxes` rather than
    `base + _BOXES_OFF` at every site."""

    def __init__(self, base_va: int) -> None:
        self.pending = base_va + _PENDING_OFF
        self.count = base_va + _COUNT_OFF
        self.boxes = base_va + _BOXES_OFF
        self.owners = base_va + _OWNERS_OFF
        self.items = base_va + _ITEMS_OFF
        self.rows = base_va + _ROWS_OFF
        self.kind = base_va + _KIND_OFF
        self.label = base_va + _LABEL_OFF
        self.wide_empty = base_va + _WIDE_EMPTY_OFF
        self.variants_label = base_va + _VARIANTS_LABEL_OFF
        self.good_label = base_va + _GOOD_LABEL_OFF
        self.evil_label = base_va + _EVIL_LABEL_OFF


# Everything below is hand-encoded (the house style: only address arithmetic is automated, by
# `..asm`), with a comment saying what each instruction is.


def _emit_parse(a: Asm, lay: _Layout) -> None:
    """`VariantOf`'s parse function: cdecl `(INI *, void *, void *, const void *)`.

    The block being parsed has no usable identity yet - a new one is a stack temporary, and its
    key is written only after its fields are read - so the parent key waits in `pending` for
    `commit`, which runs where the block's own key is written. The key is taken the way the store
    takes a block's own name (`NAME_KEY_FROM_CSTR` on the raw token), so the two compare equal.
    """
    a.label("parse")
    a.emit(0x55)  # push ebp
    a.emit(0x8B, 0xEC)  # mov ebp, esp
    a.emit(0x8B, 0x4D, 0x08)  # mov ecx, [ebp+8]            ; the INI
    a.emit(0x6A, 0x00)  # push 0                       ; default separators
    a.call_absolute(INI_NEXT_TOKEN_OR_NULL)  # ret 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "parse_out")  # an empty line declares nothing
    a.emit(0x8B, 0x0D, u32(THE_NAME_KEY_GENERATOR))  # mov ecx, [TheNameKeyGenerator]
    a.emit(0x50)  # push eax                     ; the token
    a.call_absolute(NAME_KEY_FROM_CSTR)  # ret 4
    a.emit(0xA3, u32(lay.pending))  # mov [pending], eax
    a.label("parse_out")
    a.emit(0x5D)  # pop ebp
    a.emit(0xC3)  # ret                          ; cdecl


def _emit_commit(a: Asm, lay: _Layout) -> None:
    """`commit`: `edi` = the key of the block just parsed. Files `pending` against it.

    A block re-declaring `VariantOf` replaces its row; a table that is full drops the new
    declaration, which leaves that template a plain faction - the degradation a reader of the lobby
    can see and a crash is not. Preserves everything.
    """
    a.label("commit")
    a.emit(0x50, 0x51, 0x52)  # push eax / push ecx / push edx
    a.emit(0xA1, u32(lay.pending))  # mov eax, [pending]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "commit_out")  # this block said nothing
    a.emit(0x83, 0x25, u32(lay.pending), 0x00)  # and dword [pending], 0
    a.emit(0x85, 0xFF)  # test edi, edi
    a.jcc(JE, "commit_out")
    a.emit(0x8B, 0x0D, u32(lay.count))  # mov ecx, [count]
    a.emit(0xBA, u32(lay.rows))  # mov edx, rows
    a.label("commit_find")
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "commit_append")
    a.emit(0x39, 0x3A)  # cmp [edx], edi
    a.jcc(JE, "commit_set")
    a.emit(0x83, 0xC2, 0x08)  # add edx, 8
    a.emit(0x49)  # dec ecx
    a.jmp("commit_find")
    a.label("commit_append")  # edx is rows + count*8, the first free row
    a.emit(0x81, 0x3D, u32(lay.count), u32(ROWS))  # cmp dword [count], ROWS
    a.jcc(JAE, "commit_out")
    a.emit(0x89, 0x3A)  # mov [edx], edi
    a.emit(0xFF, 0x05, u32(lay.count))  # inc dword [count]
    a.label("commit_set")
    a.emit(0x89, 0x42, 0x04)  # mov [edx+4], eax
    a.label("commit_out")
    a.emit(0x5A, 0x59, 0x58)  # pop edx / pop ecx / pop eax
    a.emit(0xC3)  # ret


def _emit_parse_hooks(a: Asm) -> None:
    """The two places a parsed block's key is written, each reproducing what it displaced."""
    a.label("new_key")
    a.emit(PLAYER_TEMPLATE_PARSED_NEW_KEY_BYTES)  # mov [ebp-0x1e4], edi
    a.call("commit")
    a.jmp_absolute(PLAYER_TEMPLATE_PARSED_NEW_KEY_RESUME)

    a.label("join")
    a.call("commit")
    a.emit(PLAYER_TEMPLATE_PARSED_JOIN_BYTES)  # mov eax, [ThePlayerTemplateStore]
    a.jmp_absolute(PLAYER_TEMPLATE_PARSED_JOIN_RESUME)


def _emit_lookup(a: Asm, lay: _Layout) -> None:
    """`lookup`: `eax` = a template key, `eax` = the key it is a variant of, or 0. Preserves the
    rest. Linear, because it runs a few hundred times per lobby redraw over a table of dozens."""
    a.label("lookup")
    a.emit(0x51, 0x52)  # push ecx / push edx
    a.emit(0x8B, 0x0D, u32(lay.count))  # mov ecx, [count]
    a.emit(0xBA, u32(lay.rows))  # mov edx, rows
    a.label("lookup_loop")
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "lookup_miss")
    a.emit(0x39, 0x02)  # cmp [edx], eax
    a.jcc(JE, "lookup_hit")
    a.emit(0x83, 0xC2, 0x08)  # add edx, 8
    a.emit(0x49)  # dec ecx
    a.jmp("lookup_loop")
    a.label("lookup_hit")
    a.emit(0x8B, 0x42, 0x04)  # mov eax, [edx+4]
    a.jmp("lookup_out")
    a.label("lookup_miss")
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.label("lookup_out")
    a.emit(0x5A, 0x59)  # pop edx / pop ecx
    a.emit(0xC3)  # ret


def _emit_parent_of(a: Asm) -> None:
    """`parent_of`: `eax` = a template index, `eax` = the index of the template it is a variant
    of, or -1. Preserves the rest.

    -1 covers every way of not being a variant: no `VariantOf`, a `VariantOf` naming a template
    that does not exist, one naming itself, and an index that is not a template (Random is -1,
    Observer -2). A variant whose parent is missing therefore stays in the faction box as a
    faction of its own - visible, rather than unreachable.
    """
    a.label("parent_of")
    a.emit(0x53, 0x51, 0x52, 0x56, 0x57)  # push ebx / ecx / edx / esi / edi
    a.emit(0x8B, 0xF8)  # mov edi, eax                 ; the index asked about
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JL, "parent_none")
    a.emit(0x8B, 0x0D, u32(THE_PLAYER_TEMPLATE_STORE))  # mov ecx, [ThePlayerTemplateStore]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "parent_none")
    a.emit(0x8B, 0x71, PLAYER_TEMPLATE_STORE_BEGIN)  # mov esi, [ecx+0xc]   ; begin
    a.emit(0x8B, 0x51, PLAYER_TEMPLATE_STORE_END)  # mov edx, [ecx+0x10]     ; end
    a.emit(0x69, 0xD8, u32(PLAYER_TEMPLATE_SIZE))  # imul ebx, eax, 0x1dc
    a.emit(0x03, 0xDE)  # add ebx, esi                 ; the template
    a.emit(0x3B, 0xDA)  # cmp ebx, edx
    a.jcc(JAE, "parent_none")  # past the end
    a.emit(0x8B, 0x43, PLAYER_TEMPLATE_NAME_KEY)  # mov eax, [ebx+0x10]
    a.call("lookup")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "parent_none")
    a.emit(0x8B, 0xD8)  # mov ebx, eax                 ; the parent's key
    a.emit(0x31, 0xC9)  # xor ecx, ecx                 ; its index, counted up
    a.label("parent_scan")
    a.emit(0x3B, 0xF2)  # cmp esi, edx
    a.jcc(JAE, "parent_none")  # no such template
    a.emit(0x39, 0x5E, PLAYER_TEMPLATE_NAME_KEY)  # cmp [esi+0x10], ebx
    a.jcc(JE, "parent_found")
    a.emit(0x81, 0xC6, u32(PLAYER_TEMPLATE_SIZE))  # add esi, 0x1dc
    a.emit(0x41)  # inc ecx
    a.jmp("parent_scan")
    a.label("parent_found")
    a.emit(0x3B, 0xCF)  # cmp ecx, edi
    a.jcc(JE, "parent_none")  # `VariantOf` naming itself
    a.emit(0x8B, 0xC1)  # mov eax, ecx
    a.jmp("parent_out")
    a.label("parent_none")
    a.emit(0x83, 0xC8, 0xFF)  # or eax, -1
    a.label("parent_out")
    a.emit(0x5F, 0x5E, 0x5A, 0x59, 0x5B)  # pop edi / esi / edx / ecx / ebx
    a.emit(0xC3)  # ret


def _emit_base_of(a: Asm) -> None:
    """`base_of`: `eax` = a template index, `eax` = its parent if it is a variant, else itself.
    Preserves the rest."""
    a.label("base_of")
    a.emit(0x51)  # push ecx
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.call("parent_of")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JGE, "base_out")
    a.emit(0x8B, 0xC1)  # mov eax, ecx                 ; not a variant: itself
    a.label("base_out")
    a.emit(0x59)  # pop ecx
    a.emit(0xC3)  # ret


def _emit_family(a: Asm) -> None:
    """`family`: `eax` = a slot's template, `eax` = what its faction box shows - a variant's base,
    the faction of a `RANDOM_OF`, `RANDOM_STANDARD` for every Random of a slot (`RANDOM_VARIANT`
    down to just above `RANDOM_OF`: Random, Variants, Good, Evil), Observer as itself. Preserves
    the rest."""
    a.label("family")
    a.emit(0x83, 0xF8, i8(RANDOM_OF))  # cmp eax, -16
    a.jcc(JG, "family_random")
    a.emit(0xF7, 0xD8)  # neg eax
    a.emit(0x83, 0xC0, i8(RANDOM_OF))  # add eax, -16               ; RANDOM_OF - eax
    a.emit(0xC3)  # ret
    a.label("family_random")
    a.emit(0x83, 0xF8, i8(RANDOM_VARIANT))  # cmp eax, -3
    a.jcc(JG, "family_template")  # Standard, Observer, a template
    a.emit(0x83, 0xC8, 0xFF)  # or eax, -1
    a.emit(0xC3)  # ret
    a.label("family_template")
    a.jmp("base_of")  # a negative index is its own base


def _emit_faction_list(a: Asm) -> None:
    """The faction fill's per-template test: playable, and not somebody's variant."""
    a.label("faction_list")
    a.emit(MP_SETUP_FACTION_LIST_PLAYABLE_BYTES[:7])  # cmp byte [esi+0x151], 0
    a.jcc(JE, "faction_list_skip")
    a.emit(0x8B, 0x45, i8(MP_SETUP_FACTION_LIST_INDEX_EBP))  # mov eax, [ebp-0x34]
    a.call("parent_of")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JGE, "faction_list_skip")  # a variant: the Variant box lists it
    a.jmp_absolute(MP_SETUP_FACTION_LIST_PLAYABLE_RESUME)
    a.label("faction_list_skip")
    a.jmp_absolute(MP_SETUP_FACTION_LIST_SKIP)


def _emit_random_pool(a: Asm) -> None:
    """The Random pool's per-template test, the same rule as the faction list's."""
    a.label("random_pool")
    a.emit(GAME_START_RANDOM_POOL_BYTES[:7])  # cmp byte [esi+0x151], 0
    a.jcc(JE, "random_pool_skip")
    a.emit(0x8B, 0x45, i8(GAME_START_RANDOM_POOL_INDEX_EBP))  # mov eax, [ebp-0x10]
    a.call("parent_of")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JGE, "random_pool_skip")
    a.jmp_absolute(GAME_START_RANDOM_POOL_RESUME)
    a.label("random_pool_skip")
    a.jmp_absolute(GAME_START_RANDOM_POOL_SKIP)


def _emit_sync_template(a: Asm) -> None:
    """`syncFactionCombo` reads the slot's template once and uses it for both the selection and
    the read-only text; reading its family instead is what makes a variant show as its faction,
    and "Random, any variant" as the faction box's own Random row."""
    a.label("sync_template")
    a.emit(MP_SETUP_SYNC_FACTION_TEMPLATE_BYTES[:3])  # mov eax, [edi+0x18]
    a.call("family")
    a.emit(MP_SETUP_SYNC_FACTION_TEMPLATE_BYTES[3:])  # mov [ebp-0x14], eax
    a.jmp_absolute(MP_SETUP_SYNC_FACTION_TEMPLATE_RESUME)


def _emit_wrap(a: Asm, name: str, target: int, *, keep_pick: bool) -> None:
    """A stand-in for `call target` at a `push slot / mov ecx, screen` site: the stock routine,
    then the Variant box rebuilt. `ret 4`, as the routine it replaces.

    `keep_pick` is what the stock routine does with its own box: the fill keeps the faction box's
    previous selection, the sync forces the slot's template onto it. The Variant box follows suit,
    which is what keeps a LAN client's pick on screen until the host has answered it."""
    a.label(name)
    a.emit(0x56, 0x57)  # push esi / push edi
    a.emit(0x8B, 0xF1)  # mov esi, ecx                 ; the screen
    a.emit(0x8B, 0x7C, 0x24, 0x0C)  # mov edi, [esp+0xc]           ; the slot
    a.emit(0x57)  # push edi
    a.call_absolute(target)  # ecx is still the screen; ret 4
    if keep_pick:
        a.emit(0xB8, u32(1))  # mov eax, 1                   ; the box's own pick, if still valid
    else:
        a.emit(0x31, 0xC0)  # xor eax, eax                 ; the slot's own template
    a.call("refresh")
    a.emit(0x5F, 0x5E)  # pop edi / pop esi
    a.emit(0xC2, 0x04, 0x00)  # ret 4


def _emit_slot_box(a: Asm, lay: _Layout, fail: str) -> None:
    """`ebx` = this slot's Variant box, or jump to `fail` when the slot has none that belongs to
    this screen. `esi` the screen, `edi` the slot."""
    a.emit(0x83, 0xFF, SLOTS)  # cmp edi, 8
    a.jcc(JAE, fail)
    a.emit(0x8B, 0x1C, 0xBD, u32(lay.boxes))  # mov ebx, [boxes+edi*4]
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JE, fail)
    a.emit(0x39, 0x34, 0xBD, u32(lay.owners))  # cmp [owners+edi*4], esi
    a.jcc(JNE, fail)


def _emit_state(a: Asm, lay: _Layout) -> None:
    """`state`: show and enable the Variant box as its faction box is shown and enabled - and
    only while it lists something. `esi` the screen, `edi` the slot; preserves everything.

    An enabled box also gets its drop-down button enabled, so its arrow shows as every other
    column's does. The combo box gadget keeps that button disabled - drawn without its arrow - while
    it holds fewer than two entries, which is a faction without variants: `WINDOW_ENABLE` enables
    the button with the box and then lets the gadget (`COMBO_BOX_ENABLE_NOTIFY`) disable it again,
    so the button is re-enabled after that. A list of one still does not open.
    """
    a.label("state")
    a.emit(0x60)  # pushad
    _emit_slot_box(a, lay, "state_out")
    a.emit(0x31, 0xD2)  # xor edx, edx                 ; show
    a.emit(0x31, 0xED)  # xor ebp, ebp                 ; enable
    a.emit(0x83, 0x3C, 0xBD, u32(lay.items), 0x00)  # cmp dword [items+edi*4], 0
    a.jcc(JE, "state_apply")  # nothing listed: an observer, or no box to fill
    a.emit(0x8B, 0x84, 0xBE, u32(MP_SETUP_FACTION_WINDOWS))  # mov eax, [esi+edi*4+0x334]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "state_apply")
    a.emit(0x8B, 0x40, WINDOW_STATUS)  # mov eax, [eax+8]    ; the faction box's status
    a.emit(0xA8, WINDOW_STATUS_HIDDEN)  # test al, 0x10
    a.jcc(JNE, "state_apply")  # a hidden row hides both
    a.emit(0xB2, 0x01)  # mov dl, 1
    a.emit(0x8B, 0xE8)  # mov ebp, eax
    a.emit(0x83, 0xE5, WINDOW_STATUS_ENABLED)  # and ebp, 8
    a.label("state_apply")
    a.emit(0x52)  # push edx
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.emit(0x85, 0xD2)  # test edx, edx
    a.emit(0x0F, 0x94, 0xC0)  # sete al                      ; hide = !show
    a.emit(0x50)  # push eax
    a.emit(0x8B, 0xCB)  # mov ecx, ebx
    a.call_absolute(WINDOW_HIDE)  # ret 4
    a.emit(0x5A)  # pop edx
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.emit(0x85, 0xED)  # test ebp, ebp
    a.emit(0x0F, 0x95, 0xC0)  # setne al
    a.emit(0x50)  # push eax
    a.emit(0x8B, 0xCB)  # mov ecx, ebx
    a.call_absolute(WINDOW_ENABLE)  # ret 4
    a.emit(0x85, 0xED)  # test ebp, ebp
    a.jcc(JE, "state_out")  # disabled: its button stays disabled, as every column's does
    a.emit(0x8B, 0x43, COMBO_BOX_GADGET_DATA)  # mov eax, [ebx+0x2c]   ; the combo box's data
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "state_out")
    a.emit(0x8B, 0x48, COMBO_BOX_DROPDOWN_BUTTON)  # mov ecx, [eax+0x24]  ; its drop-down button
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "state_out")
    a.emit(0x6A, 0x01)  # push 1
    a.call_absolute(WINDOW_ENABLE)  # ret 4
    a.label("state_out")
    a.emit(0x61)  # popad
    a.emit(0xC3)  # ret


# `refresh`'s frame, below the `pushad`.
_WANT = -0x04  # the template the box selects
_BASE = -0x08  # the faction whose variants it lists
_ITEMS = -0x0C  # rows added
_SELECTED = -0x10  # the row holding _WANT, or -1
_COUNT = -0x14  # templates in the store; on entry, the prefer-the-box flag
_INDEX = -0x18  # the template being considered
_COLOR = -0x1C  # the colour every row is written in
_TEMPLATE = -0x20  # the final override of _INDEX
_ROW = -0x24  # the row just added
_FORMAT = -0x28  # the standard row's label, as fetched
_NAME = -0x2C  # the name it is formatted with
_RANDOM = -0x30  # RANDOM_OF - _BASE, the faction's Random row
_FRAME = 0x34


def _emit_label_row(a: Asm, label_va: int) -> None:
    """Push the colour and fetch the string table label at `label_va` into the text slot above
    it - the head of a row for `_emit_add_row`, built as the faction fill builds its Random row."""
    a.emit(0xFF, 0x75, i8(_COLOR))  # push dword [ebp-0x1c]
    a.emit(0x6A, 0x00)  # push 0                       ; the text's slot
    a.emit(0x8B, 0xD4)  # mov edx, esp
    a.emit(0x8B, 0x0D, u32(THE_GAME_TEXT))  # mov ecx, [TheGameText]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0x6A, 0x00)  # push 0                       ; exists: not asked
    a.emit(0x68, u32(label_va))  # push <label>
    a.emit(0x52)  # push edx                     ; out
    a.emit(0xFF, 0x50, GAME_TEXT_FETCH_SLOT)  # call [eax+0x3c]      ; ret 0xc


def _emit_standard_row(a: Asm, lay: _Layout, *, random: bool, tag: str) -> None:
    """Push the colour and build the standard row's text above it: `STANDARD_LABEL` formatted with
    the name the faction box shows for this slot - `_BASE`'s display name, or `GUI:Random`'s text
    for a Random slot. Both are released again; the formatted text goes to `_emit_add_row`."""
    a.emit(0x8D, 0x55, i8(_FORMAT))  # lea edx, [ebp-0x28]
    a.emit(0x8B, 0x0D, u32(THE_GAME_TEXT))  # mov ecx, [TheGameText]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0x6A, 0x00)  # push 0
    a.emit(0x68, u32(lay.label))  # push STANDARD_LABEL
    a.emit(0x52)  # push edx
    a.emit(0xFF, 0x50, GAME_TEXT_FETCH_SLOT)  # call [eax+0x3c]      ; ret 0xc
    if random:
        a.emit(0x8D, 0x55, i8(_NAME))  # lea edx, [ebp-0x2c]
        a.emit(0x8B, 0x0D, u32(THE_GAME_TEXT))  # mov ecx, [TheGameText]
        a.emit(0x8B, 0x01)  # mov eax, [ecx]
        a.emit(0x6A, 0x00)  # push 0
        a.emit(0x68, u32(GUI_RANDOM_LABEL))  # push "GUI:Random"
        a.emit(0x52)  # push edx
        a.emit(0xFF, 0x50, GAME_TEXT_FETCH_SLOT)  # call [eax+0x3c]
    else:
        a.emit(0x83, 0x65, i8(_NAME), 0x00)  # and dword [ebp-0x2c], 0  ; empty until named
        a.emit(0xFF, 0x75, i8(_BASE))  # push dword [ebp-8]
        a.emit(0x8B, 0x0D, u32(THE_PLAYER_TEMPLATE_STORE))  # mov ecx, [ThePlayerTemplateStore]
        a.call_absolute(PLAYER_TEMPLATE_FIND_BY_INDEX)  # ret 4
        a.emit(0x85, 0xC0)  # test eax, eax
        a.jcc(JE, f"{tag}_named")
        a.emit(0x8D, 0x55, i8(_NAME))  # lea edx, [ebp-0x2c]
        a.emit(0x52)  # push edx
        a.emit(0x8B, 0xC8)  # mov ecx, eax
        a.call_absolute(PLAYER_TEMPLATE_GET_DISPLAY_NAME)  # ret 4
        a.label(f"{tag}_named")

    a.emit(0xFF, 0x75, i8(_COLOR))  # push dword [ebp-0x1c]
    a.emit(0x6A, 0x00)  # push 0                       ; the text's slot, an empty string
    a.emit(0x8B, 0x45, i8(_NAME))  # mov eax, [ebp-0x2c]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, f"{tag}_empty")
    a.emit(0x83, 0xC0, 0x08)  # add eax, 8                   ; the characters
    a.jmp(f"{tag}_format")
    a.label(f"{tag}_empty")
    a.emit(0xB8, u32(lay.wide_empty))  # mov eax, L""
    a.label(f"{tag}_format")
    a.emit(0x50)  # push eax                     ; %s
    a.emit(0x8D, 0x45, i8(_FORMAT))  # lea eax, [ebp-0x28]
    a.emit(0x50)  # push eax                     ; the format
    a.emit(0x8D, 0x44, 0x24, 0x08)  # lea eax, [esp+8]             ; the text's slot
    a.emit(0x50)  # push eax
    a.call_absolute(UNICODE_STRING_CONCAT)  # format(dest, fmt, ...): cdecl, replaces dest
    a.emit(0x83, 0xC4, 0x0C)  # add esp, 0xc
    a.emit(0x8D, 0x4D, i8(_FORMAT))  # lea ecx, [ebp-0x28]
    a.call_absolute(UNICODE_STRING_DTOR)
    a.emit(0x8D, 0x4D, i8(_NAME))  # lea ecx, [ebp-0x2c]
    a.call_absolute(UNICODE_STRING_DTOR)


def _emit_add_row(a: Asm, tag: str, data_ebp: int) -> None:
    """Append a row to the box in `ebx` and give it the `Int` at `[ebp+data_ebp]`.

    The caller has pushed the colour and constructed the text in the slot above it, which is
    already the tail of `ADD_ENTRY(box, text, colour)`'s frame - the faction fill builds its rows
    the same way. Counts the row, and remembers it when its data is `_WANT`.
    """
    a.emit(0x53)  # push ebx
    a.call_absolute(COMBO_BOX_ADD_ENTRY)  # cdecl; destroys the text it was given
    a.emit(0x83, 0xC4, 0x0C)  # add esp, 0xc                 ; box, text, colour
    a.emit(0x89, 0x45, i8(_ROW))  # mov [ebp-0x24], eax
    a.emit(0xFF, 0x75, i8(data_ebp))  # push dword [ebp+data]
    a.emit(0x50)  # push eax                     ; the row
    a.emit(0x53)  # push ebx
    a.call_absolute(COMBO_BOX_SET_ITEM_DATA)
    a.emit(0x83, 0xC4, 0x0C)  # add esp, 0xc
    a.emit(0xFF, 0x45, i8(_ITEMS))  # inc dword [ebp-0xc]
    a.emit(0x8B, 0x45, i8(data_ebp))  # mov eax, [ebp+data]
    a.emit(0x3B, 0x45, i8(_WANT))  # cmp eax, [ebp-4]
    a.jcc(JNE, f"{tag}_other")
    a.emit(0x8B, 0x45, i8(_ROW))  # mov eax, [ebp-0x24]
    a.emit(0x89, 0x45, i8(_SELECTED))  # mov [ebp-0x10], eax
    a.label(f"{tag}_other")


def _emit_refresh(a: Asm, lay: _Layout) -> None:
    """`refresh`: rebuild this slot's Variant box. `esi` the screen, `edi` the slot, `eax` 1 to
    keep the box's own pick when it is of the slot's faction, 0 to show the slot as it stands.
    Never called from the box's own selection message: it resets the box. Preserves everything.

    A faction with no playable variant gets its Standard row alone. One with variants lists
    the faction first, under `STANDARD_LABEL`, and its variants
    in store order, each with its template index as the row's data, which is what the faction box
    carries too, behind a `GUI:Random` row (`RANDOM_OF - base`). A Random slot gets its own rows
    instead: `GUI:Random` (`RANDOM_VARIANT`) and `STANDARD_LABEL` (`RANDOM_STANDARD`), then
    `VARIANTS_LABEL` (`RANDOM_VARIANTS`) when the mod has a variant, and `GOOD_LABEL` /
    `EVIL_LABEL` (`RANDOM_GOOD` / `RANDOM_EVIL`) when it has base factions on both sides.
    """
    a.label("refresh")
    a.emit(0x60)  # pushad
    a.emit(0x8B, 0xEC)  # mov ebp, esp
    a.emit(0x83, 0xEC, _FRAME)  # sub esp, 0x20
    a.emit(0x89, 0x45, i8(_COUNT))  # mov [ebp-0x14], eax         ; the flag, for now
    _emit_slot_box(a, lay, "refresh_out")
    a.emit(0x8B, 0x4E, MP_SETUP_GAME_INFO)  # mov ecx, [esi+0x5c]
    a.call_absolute(MP_SETUP_GET_GAME_INFO)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "refresh_out")
    a.emit(0x57)  # push edi
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.call_absolute(GAME_INFO_GET_SLOT)  # ret 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "refresh_out")
    a.emit(0x8B, 0x40, GAME_SLOT_PLAYER_TEMPLATE)  # mov eax, [eax+0x18]
    a.emit(0x89, 0x45, i8(_WANT))  # mov [ebp-4], eax

    # The box's own pick wins when it is of the same family as the slot's template - the same
    # faction, or both Randoms.
    a.emit(0x83, 0x7D, i8(_COUNT), 0x00)  # cmp dword [ebp-0x14], 0
    a.jcc(JE, "refresh_want")
    a.emit(0x83, 0x4D, i8(_SELECTED), 0xFF)  # or dword [ebp-0x10], -1
    a.emit(0x8D, 0x45, i8(_SELECTED))  # lea eax, [ebp-0x10]
    a.emit(0x50)  # push eax
    a.emit(0x53)  # push ebx
    a.call_absolute(COMBO_BOX_GET_SELECTED)
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.emit(0x8B, 0x45, i8(_SELECTED))  # mov eax, [ebp-0x10]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JL, "refresh_want")
    a.emit(0x50)  # push eax
    a.emit(0x53)  # push ebx
    a.call_absolute(COMBO_BOX_GET_ITEM_DATA)
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.emit(0x8B, 0xC8)  # mov ecx, eax                 ; the box's pick
    a.call("family")
    a.emit(0x8B, 0xD0)  # mov edx, eax
    a.emit(0x8B, 0x45, i8(_WANT))  # mov eax, [ebp-4]
    a.call("family")
    a.emit(0x3B, 0xC2)  # cmp eax, edx
    a.jcc(JNE, "refresh_want")
    a.emit(0x89, 0x4D, i8(_WANT))  # mov [ebp-4], ecx

    a.label("refresh_want")
    a.emit(0x53)  # push ebx
    a.call_absolute(COMBO_BOX_RESET)
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4
    a.emit(0x83, 0x65, i8(_ITEMS), 0x00)  # and dword [ebp-0xc], 0
    a.emit(0x83, 0x4D, i8(_SELECTED), 0xFF)  # or dword [ebp-0x10], -1
    a.emit(0x83, 0x7D, i8(_WANT), i8(_OBSERVER))  # cmp dword [ebp-4], -2
    a.jcc(JE, "refresh_done")  # an observer plays no faction

    a.emit(0x8B, 0x0D, u32(THE_MULTIPLAYER_SETTINGS))  # mov ecx, [TheMultiplayerSettings]
    a.emit(0x6A, 0xFF)  # push -1
    a.call_absolute(MULTIPLAYER_SETTINGS_GET_COLOR)  # ret 4
    a.emit(0x8B, 0x40, MULTIPLAYER_COLOR_VALUE)  # mov eax, [eax+0x10]
    a.emit(0x89, 0x45, i8(_COLOR))  # mov [ebp-0x1c], eax

    # Random: "Random" draws a variant too, "Standard" plays the drawn faction as it stands.
    a.emit(0x83, 0x7D, i8(_WANT), 0x00)  # cmp dword [ebp-4], 0
    a.jcc(JGE, "refresh_faction")
    a.emit(0x83, 0x7D, i8(_WANT), i8(RANDOM_OF))  # cmp dword [ebp-4], -16
    a.jcc(JLE, "refresh_faction")  # a faction with a random variant
    a.emit(0xC7, 0x45, i8(_INDEX), u32(RANDOM_VARIANT & 0xFFFFFFFF))  # mov [ebp-0x18], -3
    _emit_label_row(a, GUI_RANDOM_LABEL)
    _emit_add_row(a, "refresh_random", _INDEX)
    a.emit(0xC7, 0x45, i8(_BASE), u32(RANDOM_STANDARD & 0xFFFFFFFF))  # mov [ebp-8], -1
    _emit_standard_row(a, lay, random=True, tag="std_random")
    _emit_add_row(a, "refresh_random_standard", _BASE)
    a.call("count_variants")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "refresh_sides")  # no variant to draw among
    a.emit(0xC7, 0x45, i8(_INDEX), u32(RANDOM_VARIANTS & 0xFFFFFFFF))  # mov [ebp-0x18], -4
    _emit_label_row(a, lay.variants_label)
    _emit_add_row(a, "refresh_random_variants", _INDEX)
    a.label("refresh_sides")
    a.call("sides_offered")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "refresh_done")  # one side only: Good or Evil would just be Standard
    a.emit(0xC7, 0x45, i8(_INDEX), u32(RANDOM_GOOD & 0xFFFFFFFF))  # mov [ebp-0x18], -5
    _emit_label_row(a, lay.good_label)
    _emit_add_row(a, "refresh_random_good", _INDEX)
    a.emit(0xC7, 0x45, i8(_INDEX), u32(RANDOM_EVIL & 0xFFFFFFFF))  # mov [ebp-0x18], -6
    _emit_label_row(a, lay.evil_label)
    _emit_add_row(a, "refresh_random_evil", _INDEX)
    a.jmp("refresh_done")

    a.label("refresh_faction")
    a.emit(0x8B, 0x45, i8(_WANT))  # mov eax, [ebp-4]
    a.call("family")
    a.emit(0x89, 0x45, i8(_BASE))  # mov [ebp-8], eax
    a.emit(0xB9, u32(RANDOM_OF & 0xFFFFFFFF))  # mov ecx, -16
    a.emit(0x2B, 0xC8)  # sub ecx, eax
    a.emit(0x89, 0x4D, i8(_RANDOM))  # mov [ebp-0x30], ecx        ; RANDOM_OF - base

    a.emit(0x8B, 0x0D, u32(THE_PLAYER_TEMPLATE_STORE))  # mov ecx, [ThePlayerTemplateStore]
    a.emit(0x8B, 0x41, PLAYER_TEMPLATE_STORE_END)  # mov eax, [ecx+0x10]
    a.emit(0x2B, 0x41, PLAYER_TEMPLATE_STORE_BEGIN)  # sub eax, [ecx+0xc]
    a.emit(0x99)  # cdq
    a.emit(0xB9, u32(PLAYER_TEMPLATE_SIZE))  # mov ecx, 0x1dc
    a.emit(0xF7, 0xF9)  # idiv ecx
    a.emit(0x89, 0x45, i8(_COUNT))  # mov [ebp-0x14], eax
    a.emit(0x83, 0x65, i8(_INDEX), 0x00)  # and dword [ebp-0x18], 0

    a.label("refresh_each")
    a.emit(0x8B, 0x45, i8(_INDEX))  # mov eax, [ebp-0x18]
    a.emit(0x3B, 0x45, i8(_COUNT))  # cmp eax, [ebp-0x14]
    a.jcc(JGE, "refresh_faction_end")
    a.call("parent_of")
    a.emit(0x3B, 0x45, i8(_BASE))  # cmp eax, [ebp-8]
    a.jcc(JNE, "refresh_next")
    a.emit(0xFF, 0x75, i8(_INDEX))  # push dword [ebp-0x18]
    a.emit(0x8B, 0x0D, u32(THE_PLAYER_TEMPLATE_STORE))  # mov ecx, [ThePlayerTemplateStore]
    a.call_absolute(PLAYER_TEMPLATE_FIND_BY_INDEX)  # ret 4 - the final override
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "refresh_next")
    a.emit(0x80, 0xB8, u32(PLAYER_TEMPLATE_PLAYABLE_SIDE), 0x00)  # cmp byte [eax+0x151], 0
    a.jcc(JE, "refresh_next")
    a.emit(0x80, 0xB8, u32(PLAYER_TEMPLATE_IS_OBSERVER), 0x00)  # cmp byte [eax+0x150], 0
    a.jcc(JNE, "refresh_next")
    a.emit(0x89, 0x45, i8(_TEMPLATE))  # mov [ebp-0x20], eax

    # Random and the faction itself head the list, once, ahead of its first variant.
    a.emit(0x83, 0x7D, i8(_ITEMS), 0x00)  # cmp dword [ebp-0xc], 0
    a.jcc(JNE, "refresh_variant")
    a.emit(0x81, 0x7D, i8(_BASE), u32(RANDOM_OF_MAX_INDEX))  # cmp dword [ebp-8], 112
    a.jcc(JG, "refresh_standard_row")  # no template value left to say it with
    _emit_label_row(a, GUI_RANDOM_LABEL)
    _emit_add_row(a, "refresh_faction_random", _RANDOM)
    a.label("refresh_standard_row")
    _emit_standard_row(a, lay, random=False, tag="std_faction")
    _emit_add_row(a, "refresh_standard", _BASE)

    a.label("refresh_variant")
    a.emit(0xFF, 0x75, i8(_COLOR))  # push dword [ebp-0x1c]
    a.emit(0x6A, 0x00)  # push 0                       ; the text's slot
    a.emit(0x54)  # push esp                     ; out = that slot (push esp pushes the old esp)
    a.emit(0x8B, 0x4D, i8(_TEMPLATE))  # mov ecx, [ebp-0x20]
    a.call_absolute(PLAYER_TEMPLATE_GET_DISPLAY_NAME)  # ret 4
    _emit_add_row(a, "refresh_row", _INDEX)

    a.label("refresh_next")
    a.emit(0xFF, 0x45, i8(_INDEX))  # inc dword [ebp-0x18]
    a.jmp("refresh_each")

    # A faction with no variant still gets its Standard row, alone: no Random to offer.
    a.label("refresh_faction_end")
    a.emit(0x83, 0x7D, i8(_ITEMS), 0x00)  # cmp dword [ebp-0xc], 0
    a.jcc(JNE, "refresh_done")
    _emit_standard_row(a, lay, random=False, tag="std_alone")
    _emit_add_row(a, "refresh_standard_alone", _BASE)

    a.label("refresh_done")
    a.emit(0x8B, 0x45, i8(_ITEMS))  # mov eax, [ebp-0xc]
    a.emit(0x89, 0x04, 0xBD, u32(lay.items))  # mov [items+edi*4], eax
    a.emit(0x8B, 0x45, i8(_SELECTED))  # mov eax, [ebp-0x10]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JL, "refresh_lines")
    a.emit(0x6A, 0x00)  # push 0
    a.emit(0x50)  # push eax
    a.emit(0x53)  # push ebx
    a.call_absolute(COMBO_BOX_SET_SELECTED)
    a.emit(0x83, 0xC4, 0x0C)  # add esp, 0xc
    a.label("refresh_lines")
    a.emit(0x57)  # push edi
    a.call_absolute(MP_SETUP_DROPDOWN_LINES)
    a.emit(0x50)  # push eax
    a.emit(0x53)  # push ebx
    a.call_absolute(COMBO_BOX_SET_DROPDOWN_LINES)
    a.emit(0x83, 0xC4, 0x0C)  # add esp, 0xc
    a.call("state")
    a.label("refresh_out")
    a.emit(0x8B, 0xE5)  # mov esp, ebp
    a.emit(0x61)  # popad
    a.emit(0xC3)  # ret


def _emit_changed(a: Asm, lay: _Layout) -> None:
    """`changed`: the Variant box's selection moved. `esi` the screen, `edi` the slot; preserves
    `esi`, `edi`, `ebx` and `ebp`.

    `0x00844177`, the faction box's handler, with the pick read from the Variant box instead: the
    same "request pending" byte cleared, the same strategy call asking for the template, the same
    War of the Ring flags on success, the same slot redraw.

    It does **not** rebuild the box. This runs inside the box's own selection message, and
    resetting a combo box from its own notification pulls its rows out from under it - the game
    crashes. The stock handler leaves its box alone the same way; the screen's next update refills
    both, through the fill wrapper.
    """
    a.label("changed")
    a.emit(0x53, 0x55)  # push ebx / push ebp
    a.emit(0x8B, 0xEC)  # mov ebp, esp
    a.emit(0x51)  # push ecx                     ; [ebp-4]: the pick
    a.emit(0x8B, 0x4E, MP_SETUP_GAME_INFO)  # mov ecx, [esi+0x5c]
    a.call_absolute(MP_SETUP_GET_GAME_INFO)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "changed_out")
    a.emit(0x8B, 0xD8)  # mov ebx, eax                 ; the GameInfo
    a.emit(0xC6, 0x86, u32(MP_SETUP_FACTION_REQUEST_PENDING), 0x00)  # mov byte [esi+0x2c4], 0
    a.emit(0x83, 0x4D, 0xFC, 0xFF)  # or dword [ebp-4], -1
    a.emit(0x8D, 0x45, 0xFC)  # lea eax, [ebp-4]
    a.emit(0x50)  # push eax
    a.emit(0xFF, 0x34, 0xBD, u32(lay.boxes))  # push dword [boxes+edi*4]
    a.call_absolute(COMBO_BOX_GET_SELECTED)
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.emit(0x8B, 0x45, 0xFC)  # mov eax, [ebp-4]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JL, "changed_out")
    a.emit(0x50)  # push eax
    a.emit(0xFF, 0x34, 0xBD, u32(lay.boxes))  # push dword [boxes+edi*4]
    a.call_absolute(COMBO_BOX_GET_ITEM_DATA)
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.emit(0x89, 0x45, 0xFC)  # mov [ebp-4], eax            ; a Random row's data is negative
    a.emit(0x57)  # push edi
    a.emit(0x8B, 0xCB)  # mov ecx, ebx
    a.call_absolute(GAME_INFO_GET_SLOT)  # ret 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "changed_out")
    a.emit(0x8B, 0xD8)  # mov ebx, eax                 ; the GameSlot
    a.emit(0x8B, 0x45, 0xFC)  # mov eax, [ebp-4]
    a.emit(0x3B, 0x43, GAME_SLOT_PLAYER_TEMPLATE)  # cmp eax, [ebx+0x18]
    a.jcc(JE, "changed_redraw")
    a.emit(0x8B, 0x4E, MP_SETUP_STRATEGY)  # mov ecx, [esi+0x58]
    a.emit(0x8B, 0x11)  # mov edx, [ecx]
    a.emit(0x50)  # push eax                     ; the template
    a.emit(0x53)  # push ebx                     ; the slot
    a.emit(0xFF, 0x52, MP_SETUP_STRATEGY_REQUEST_TEMPLATE_SLOT)  # call [edx+0x28]
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "changed_out")  # refused
    a.emit(0x83, 0x7E, MP_SETUP_MODE, MP_SETUP_MODE_WOTR)  # cmp dword [esi+0x7c], 1
    a.jcc(JNE, "changed_redraw")
    a.emit(0x8D, 0x4E, MP_SETUP_WOTR)  # lea ecx, [esi+0x60]
    a.call_absolute(MP_SETUP_WOTR_IS_HISTORICAL)
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "changed_redraw")
    for flag in MP_SETUP_HISTORICAL_FLAGS:
        a.emit(0xC6, 0x86, u32(flag), 0x01)  # mov byte [esi+flag], 1
    a.label("changed_redraw")
    a.emit(0x6A, 0x01)  # push 1
    a.emit(0x57)  # push edi
    a.emit(0x53)  # push ebx
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(MP_SETUP_REDRAW_SLOT)  # ret 0xc
    a.label("changed_out")
    a.emit(0x8B, 0xE5)  # mov esp, ebp
    a.emit(0x5D, 0x5B)  # pop ebp / pop ebx
    a.emit(0xC3)  # ret


def _emit_selection(a: Asm, lay: _Layout) -> None:
    """Where the selection handler's slot walk ends unmatched: try the Variant boxes."""
    a.label("selection")
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.label("selection_each")
    a.emit(0x83, 0xF8, SLOTS)  # cmp eax, 8
    a.jcc(JAE, "selection_done")
    a.emit(0x39, 0x1C, 0x85, u32(lay.boxes))  # cmp [boxes+eax*4], ebx
    a.jcc(JNE, "selection_next")
    a.emit(0x39, 0x34, 0x85, u32(lay.owners))  # cmp [owners+eax*4], esi
    a.jcc(JE, "selection_hit")
    a.label("selection_next")
    a.emit(0x40)  # inc eax
    a.jmp("selection_each")
    a.label("selection_hit")
    a.emit(0x57)  # push edi
    a.emit(0x8B, 0xF8)  # mov edi, eax
    a.call("changed")
    a.emit(0x5F)  # pop edi
    a.emit(0xC6, 0x86, u32(MP_SETUP_DIRTY), 0x01)  # mov byte [esi+0x2b9], 1
    a.label("selection_done")
    a.jmp_absolute(MP_SETUP_SELECTION_DONE)


def _emit_gadget(a: Asm, lay: _Layout) -> None:
    """The gadget binder's last rung, with a `Variant` rung ahead of it."""
    a.label("gadget")
    a.emit(0x68, u32(lay.kind))  # push "Variant"
    a.emit(0x53)  # push ebx                     ; the kind the movie named
    a.call_absolute(STRICMP)
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JNE, "gadget_other")
    a.emit(0x8B, 0x45, MP_SETUP_GADGET_SLOT_EBP)  # mov eax, [ebp+0x10]
    a.emit(0x83, 0xF8, SLOTS)  # cmp eax, 8
    a.jcc(JAE, "gadget_unknown")  # the binder admits a ninth; the arrays do not
    a.emit(0x89, 0x34, 0x85, u32(lay.boxes))  # mov [boxes+eax*4], esi
    a.emit(0x89, 0x3C, 0x85, u32(lay.owners))  # mov [owners+eax*4], edi
    a.emit(0x83, 0x24, 0x85, u32(lay.items), 0x00)  # and dword [items+eax*4], 0
    a.emit(0x56)  # push esi
    a.call_absolute(COMBO_BOX_RESET)  # what every other rung does to its window
    a.jmp_absolute(MP_SETUP_GADGET_FILED)  # its `pop ecx` drops the window pushed above
    a.label("gadget_unknown")
    a.jmp_absolute(MP_SETUP_GADGET_UNKNOWN)
    a.label("gadget_other")
    a.emit(MP_SETUP_GADGET_HERO_TEST_BYTES)  # push "Hero"
    a.jmp_absolute(MP_SETUP_GADGET_HERO_TEST_RESUME)


def _emit_ctor_clear(a: Asm, lay: _Layout) -> None:
    """A new setup screen owns no Variant boxes. Tail-jumps into the `memset` it displaced."""
    a.label("ctor_clear")
    a.emit(0x50, 0x51, 0x57)  # push eax / push ecx / push edi
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.emit(0xBF, u32(lay.boxes))  # mov edi, boxes
    a.emit(0xB9, u32(_SLOT_STATE_DWORDS))  # mov ecx, 24                  ; boxes, owners, items
    a.emit(0xFC)  # cld
    a.emit(0xF3, 0xAB)  # rep stosd
    a.emit(0x5F, 0x59, 0x58)  # pop edi / pop ecx / pop eax
    a.jmp_absolute(_MEMSET)


def _emit_enable(a: Asm) -> None:
    """The faction box's `winEnable`, then the Variant box brought into line with it."""
    a.label("enable")
    a.emit(0xFF, 0x74, 0x24, 0x04)  # push dword [esp+4]          ; the flag
    a.call_absolute(WINDOW_ENABLE)  # ecx is still the faction box; ret 4
    a.call("state")
    a.emit(0xC2, 0x04, 0x00)  # ret 4


def _emit_open_gate(a: Asm, lay: _Layout) -> None:
    """The combo box toggle's "two entries or it does not open" test, with one exception: a
    Variant box opens on a single entry, so a faction without variants drops down to show its
    Standard row as every other column drops down. Every other combo box in the game keeps the
    stock rule. `edi` is the gadget data, `[ebp+8]` the box; `eax` and `ecx` are free here - the
    code at both exits reloads them."""
    a.label("open_gate")
    a.emit(0x8B, 0x47, COMBO_BOX_ENTRY_COUNT)  # mov eax, [edi+0x20]
    a.emit(0x83, 0xF8, 0x01)  # cmp eax, 1
    a.jcc(JG, "open_gate_go")  # two or more: stock opens
    a.jcc(JL, "open_gate_skip")  # empty: nothing to show
    a.emit(0x8B, 0x45, COMBO_BOX_TOGGLE_BOX_EBP)  # mov eax, [ebp+8]            ; the box
    a.emit(0x31, 0xC9)  # xor ecx, ecx
    a.label("open_gate_each")
    a.emit(0x39, 0x04, 0x8D, u32(lay.boxes))  # cmp [boxes+ecx*4], eax
    a.jcc(JE, "open_gate_go")
    a.emit(0x41)  # inc ecx
    a.emit(0x83, 0xF9, SLOTS)  # cmp ecx, 8
    a.jcc(JL, "open_gate_each")
    a.label("open_gate_skip")
    a.jmp_absolute(COMBO_BOX_OPEN_SKIP)
    a.label("open_gate_go")
    a.jmp_absolute(COMBO_BOX_OPEN_GO)


def _emit_offered(a: Asm) -> None:
    """`offered`: `eax` = a template index, `edx` = a base; `eax` = 1 when the index is a variant
    of that base a player could pick - the Variant box's own rule. Preserves the rest."""
    a.label("offered")
    a.emit(0x51, 0x52)  # push ecx / push edx
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.call("parent_of")
    a.emit(0x3B, 0x04, 0x24)  # cmp eax, [esp]               ; the base
    a.jcc(JNE, "offered_no")
    a.emit(0x51)  # push ecx
    a.emit(0x8B, 0x0D, u32(THE_PLAYER_TEMPLATE_STORE))  # mov ecx, [ThePlayerTemplateStore]
    a.call_absolute(PLAYER_TEMPLATE_FIND_BY_INDEX)  # ret 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "offered_no")
    a.emit(0x80, 0xB8, u32(PLAYER_TEMPLATE_PLAYABLE_SIDE), 0x00)  # cmp byte [eax+0x151], 0
    a.jcc(JE, "offered_no")
    a.emit(0x80, 0xB8, u32(PLAYER_TEMPLATE_IS_OBSERVER), 0x00)  # cmp byte [eax+0x150], 0
    a.jcc(JNE, "offered_no")
    a.emit(0xB8, u32(1))  # mov eax, 1
    a.jmp("offered_out")
    a.label("offered_no")
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.label("offered_out")
    a.emit(0x5A, 0x59)  # pop edx / pop ecx
    a.emit(0xC3)  # ret


def _emit_roll(a: Asm) -> None:
    """`roll`: `eax` = a base faction, `eax` = it or one of its offered variants, each equally
    likely. Drawn with `GameLogicRandomValue`, the synchronised generator the faction draw itself
    uses, so every peer and every replay of the match draws the same one. A faction with no
    variants draws nothing. Preserves the rest."""
    a.label("roll")
    a.emit(0x53, 0x51, 0x52, 0x56, 0x57)  # push ebx / ecx / edx / esi / edi
    a.emit(0x8B, 0xD8)  # mov ebx, eax                 ; the base
    a.emit(0x8B, 0x0D, u32(THE_PLAYER_TEMPLATE_STORE))  # mov ecx, [ThePlayerTemplateStore]
    a.emit(0x8B, 0x41, PLAYER_TEMPLATE_STORE_END)  # mov eax, [ecx+0x10]
    a.emit(0x2B, 0x41, PLAYER_TEMPLATE_STORE_BEGIN)  # sub eax, [ecx+0xc]
    a.emit(0x99)  # cdq
    a.emit(0xB9, u32(PLAYER_TEMPLATE_SIZE))  # mov ecx, 0x1dc
    a.emit(0xF7, 0xF9)  # idiv ecx
    a.emit(0x8B, 0xF8)  # mov edi, eax                 ; templates
    a.emit(0x31, 0xF6)  # xor esi, esi                 ; variants offered
    a.emit(0x31, 0xC9)  # xor ecx, ecx
    a.label("roll_count")
    a.emit(0x3B, 0xCF)  # cmp ecx, edi
    a.jcc(JGE, "roll_draw")
    a.emit(0x8B, 0xC1)  # mov eax, ecx
    a.emit(0x8B, 0xD3)  # mov edx, ebx
    a.call("offered")
    a.emit(0x03, 0xF0)  # add esi, eax
    a.emit(0x41)  # inc ecx
    a.jmp("roll_count")
    a.label("roll_draw")
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JE, "roll_base")  # nothing to draw between
    a.emit(0x6A, 0x00)  # push 0                       ; line
    a.emit(0x68, u32(GAME_LOGIC_SOURCE_FILE))  # push <GameLogic.cpp>
    a.emit(0x56)  # push esi                     ; hi: the last variant
    a.emit(0x6A, 0x00)  # push 0                       ; lo: the base itself
    a.call_absolute(GAME_LOGIC_RANDOM_VALUE)
    a.emit(0x83, 0xC4, 0x10)  # add esp, 0x10
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "roll_base")
    a.emit(0x8B, 0xF0)  # mov esi, eax                 ; the n-th offered variant, from 1
    a.emit(0x31, 0xC9)  # xor ecx, ecx
    a.label("roll_find")
    a.emit(0x3B, 0xCF)  # cmp ecx, edi
    a.jcc(JGE, "roll_base")
    a.emit(0x8B, 0xC1)  # mov eax, ecx
    a.emit(0x8B, 0xD3)  # mov edx, ebx
    a.call("offered")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "roll_next")
    a.emit(0x4E)  # dec esi
    a.jcc(JE, "roll_hit")
    a.label("roll_next")
    a.emit(0x41)  # inc ecx
    a.jmp("roll_find")
    a.label("roll_hit")
    a.emit(0x8B, 0xC1)  # mov eax, ecx
    a.jmp("roll_out")
    a.label("roll_base")
    a.emit(0x8B, 0xC3)  # mov eax, ebx
    a.label("roll_out")
    a.emit(0x5F, 0x5E, 0x5A, 0x59, 0x5B)  # pop edi / esi / edx / ecx / ebx
    a.emit(0xC3)  # ret


def _emit_any_variant(a: Asm) -> None:
    """`any_variant`: `eax` = a template index, `eax` = 1 when it is an offered variant of any
    faction. Preserves the rest."""
    a.label("any_variant")
    a.emit(0x52, 0x50)  # push edx / push eax
    a.call("parent_of")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JL, "any_variant_no")
    a.emit(0x8B, 0xD0)  # mov edx, eax                 ; its faction
    a.emit(0x8B, 0x04, 0x24)  # mov eax, [esp]               ; the index
    a.call("offered")
    a.jmp("any_variant_out")
    a.label("any_variant_no")
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.label("any_variant_out")
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4
    a.emit(0x5A)  # pop edx
    a.emit(0xC3)  # ret


def _emit_variants(a: Asm) -> None:
    """`count_variants`: `eax` = how many offered variants the store holds, and `roll_variants`:
    `eax` = one of them, drawn uniformly with the synchronised generator, or -1 when there are
    none. Both preserve the rest."""
    for name in ("count_variants", "roll_variants"):
        a.label(name)
        a.emit(0x51, 0x52, 0x56, 0x57)  # push ecx / edx / esi / edi
        a.emit(0x8B, 0x0D, u32(THE_PLAYER_TEMPLATE_STORE))  # mov ecx, [ThePlayerTemplateStore]
        a.emit(0x8B, 0x41, PLAYER_TEMPLATE_STORE_END)  # mov eax, [ecx+0x10]
        a.emit(0x2B, 0x41, PLAYER_TEMPLATE_STORE_BEGIN)  # sub eax, [ecx+0xc]
        a.emit(0x99)  # cdq
        a.emit(0xB9, u32(PLAYER_TEMPLATE_SIZE))  # mov ecx, 0x1dc
        a.emit(0xF7, 0xF9)  # idiv ecx
        a.emit(0x8B, 0xF8)  # mov edi, eax                 ; templates
        a.emit(0x31, 0xF6)  # xor esi, esi                 ; variants
        a.emit(0x31, 0xC9)  # xor ecx, ecx
        a.label(f"{name}_count")
        a.emit(0x3B, 0xCF)  # cmp ecx, edi
        a.jcc(JGE, f"{name}_counted")
        a.emit(0x8B, 0xC1)  # mov eax, ecx
        a.call("any_variant")
        a.emit(0x03, 0xF0)  # add esi, eax
        a.emit(0x41)  # inc ecx
        a.jmp(f"{name}_count")
        a.label(f"{name}_counted")
        if name == "count_variants":
            a.emit(0x8B, 0xC6)  # mov eax, esi
            a.jmp("variants_out")
            continue
        a.emit(0x85, 0xF6)  # test esi, esi
        a.jcc(JE, "roll_variants_none")
        a.emit(0x4E)  # dec esi                      ; hi
        a.emit(0x6A, 0x00)  # push 0                       ; line
        a.emit(0x68, u32(GAME_LOGIC_SOURCE_FILE))  # push <GameLogic.cpp>
        a.emit(0x56)  # push esi
        a.emit(0x6A, 0x00)  # push 0                       ; lo
        a.call_absolute(GAME_LOGIC_RANDOM_VALUE)
        a.emit(0x83, 0xC4, 0x10)  # add esp, 0x10
        a.emit(0x8D, 0x70, 0x01)  # lea esi, [eax+1]             ; the n-th variant, from 1
        a.emit(0x31, 0xC9)  # xor ecx, ecx
        a.label("roll_variants_find")
        a.emit(0x3B, 0xCF)  # cmp ecx, edi
        a.jcc(JGE, "roll_variants_none")
        a.emit(0x8B, 0xC1)  # mov eax, ecx
        a.call("any_variant")
        a.emit(0x85, 0xC0)  # test eax, eax
        a.jcc(JE, "roll_variants_next")
        a.emit(0x4E)  # dec esi
        a.jcc(JE, "roll_variants_hit")
        a.label("roll_variants_next")
        a.emit(0x41)  # inc ecx
        a.jmp("roll_variants_find")
        a.label("roll_variants_hit")
        a.emit(0x8B, 0xC1)  # mov eax, ecx
        a.jmp("variants_out")
        a.label("roll_variants_none")
        a.emit(0x83, 0xC8, 0xFF)  # or eax, -1
    a.label("variants_out")
    a.emit(0x5F, 0x5E, 0x5A, 0x59)  # pop edi / esi / edx / ecx
    a.emit(0xC3)  # ret


def _emit_sides(a: Asm) -> None:
    """`is_side`: `eax` = a template index, `edx` = 0 for Good or 1 for Evil; `eax` = 1 when it is
    a base faction a Random slot could draw - playable, not an observer, nobody's variant - of
    that side. `count_side`: `edx` as above, `eax` = how many the store holds. `sides_offered`:
    `eax` = 1 when the store holds some of each. All preserve the rest."""
    a.label("is_side")
    a.emit(0x51, 0x52)  # push ecx / push edx
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JL, "is_side_no")  # not a template
    a.call("parent_of")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JGE, "is_side_no")  # a variant: the Random pool holds base factions only
    a.emit(0x51)  # push ecx
    a.emit(0x8B, 0x0D, u32(THE_PLAYER_TEMPLATE_STORE))  # mov ecx, [ThePlayerTemplateStore]
    a.call_absolute(PLAYER_TEMPLATE_FIND_BY_INDEX)  # ret 4 - the final override
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "is_side_no")
    a.emit(0x80, 0xB8, u32(PLAYER_TEMPLATE_PLAYABLE_SIDE), 0x00)  # cmp byte [eax+0x151], 0
    a.jcc(JE, "is_side_no")
    a.emit(0x80, 0xB8, u32(PLAYER_TEMPLATE_IS_OBSERVER), 0x00)  # cmp byte [eax+0x150], 0
    a.jcc(JNE, "is_side_no")
    a.emit(0x80, 0xB8, u32(PLAYER_TEMPLATE_EVIL), 0x00)  # cmp byte [eax+0x1bc], 0
    a.emit(0x0F, 0x95, 0xC0)  # setne al
    a.emit(0x0F, 0xB6, 0xC0)  # movzx eax, al               ; 1 when Evil
    a.emit(0x3B, 0x04, 0x24)  # cmp eax, [esp]               ; the side asked for
    a.jcc(JNE, "is_side_no")
    a.emit(0xB8, u32(1))  # mov eax, 1
    a.jmp("is_side_out")
    a.label("is_side_no")
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.label("is_side_out")
    a.emit(0x5A, 0x59)  # pop edx / pop ecx
    a.emit(0xC3)  # ret

    a.label("count_side")
    a.emit(0x51, 0x52, 0x56, 0x57)  # push ecx / edx / esi / edi
    a.emit(0x8B, 0x0D, u32(THE_PLAYER_TEMPLATE_STORE))  # mov ecx, [ThePlayerTemplateStore]
    a.emit(0x8B, 0x41, PLAYER_TEMPLATE_STORE_END)  # mov eax, [ecx+0x10]
    a.emit(0x2B, 0x41, PLAYER_TEMPLATE_STORE_BEGIN)  # sub eax, [ecx+0xc]
    a.emit(0x99)  # cdq
    a.emit(0xB9, u32(PLAYER_TEMPLATE_SIZE))  # mov ecx, 0x1dc
    a.emit(0xF7, 0xF9)  # idiv ecx
    a.emit(0x8B, 0xF8)  # mov edi, eax                 ; templates
    a.emit(0x8B, 0x54, 0x24, 0x08)  # mov edx, [esp+8]             ; the side, back from cdq
    a.emit(0x31, 0xF6)  # xor esi, esi                 ; of that side
    a.emit(0x31, 0xC9)  # xor ecx, ecx
    a.label("count_side_each")
    a.emit(0x3B, 0xCF)  # cmp ecx, edi
    a.jcc(JGE, "count_side_done")
    a.emit(0x8B, 0xC1)  # mov eax, ecx
    a.call("is_side")
    a.emit(0x03, 0xF0)  # add esi, eax
    a.emit(0x41)  # inc ecx
    a.jmp("count_side_each")
    a.label("count_side_done")
    a.emit(0x8B, 0xC6)  # mov eax, esi
    a.emit(0x5F, 0x5E, 0x5A, 0x59)  # pop edi / esi / edx / ecx
    a.emit(0xC3)  # ret

    a.label("sides_offered")
    a.emit(0x52)  # push edx
    a.emit(0x31, 0xD2)  # xor edx, edx                 ; Good
    a.call("count_side")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "sides_offered_out")
    a.emit(0x42)  # inc edx                      ; Evil
    a.call("count_side")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "sides_offered_out")
    a.emit(0xB8, u32(1))  # mov eax, 1
    a.label("sides_offered_out")
    a.emit(0x5A)  # pop edx
    a.emit(0xC3)  # ret


def _emit_random_side(a: Asm) -> None:
    """Where `startNewGame` draws a Random slot's faction from its candidates: a slot on Good or
    Evil first keeps only the candidates of that side. The candidates are a per-slot copy of the
    pool, already filtered by the slot's start position, so lowering the vector's end is all it
    takes - the elements are `Int`s and the block is freed through its begin. A slot whose
    candidates hold none of that side keeps them all, rather than leaving the draw nothing to
    divide by. `ebx` is untouched; `esi` and `edi` are reloaded by the displaced instructions."""
    begin = GAME_START_RANDOM_CANDIDATES_EBP
    end = GAME_START_RANDOM_CANDIDATES_EBP + 4
    a.label("random_side")
    a.emit(0x8B, 0x45, i8(GAME_START_RANDOM_SLOT_EBP))  # mov eax, [ebp-0x1c]    ; the slot
    a.emit(0x8B, 0x40, GAME_SLOT_PLAYER_TEMPLATE)  # mov eax, [eax+0x18]
    a.emit(0x31, 0xD2)  # xor edx, edx                 ; Good
    a.emit(0x83, 0xF8, i8(RANDOM_GOOD))  # cmp eax, -5
    a.jcc(JE, "random_side_filter")
    a.emit(0x42)  # inc edx                      ; Evil
    a.emit(0x83, 0xF8, i8(RANDOM_EVIL))  # cmp eax, -6
    a.jcc(JNE, "random_side_out")
    a.label("random_side_filter")
    a.emit(0x8B, 0x75, i8(begin))  # mov esi, [ebp-0x28]
    a.emit(0x8B, 0x4D, i8(end))  # mov ecx, [ebp-0x24]
    a.emit(0x31, 0xFF)  # xor edi, edi                 ; candidates of that side
    a.label("random_side_count")
    a.emit(0x3B, 0xF1)  # cmp esi, ecx
    a.jcc(JAE, "random_side_counted")
    a.emit(0x8B, 0x06)  # mov eax, [esi]
    a.call("is_side")
    a.emit(0x03, 0xF8)  # add edi, eax
    a.emit(0x83, 0xC6, 0x04)  # add esi, 4
    a.jmp("random_side_count")
    a.label("random_side_counted")
    a.emit(0x85, 0xFF)  # test edi, edi
    a.jcc(JE, "random_side_out")  # none of that side: draw from them all
    a.emit(0x8B, 0x75, i8(begin))  # mov esi, [ebp-0x28]          ; read
    a.emit(0x8B, 0xFE)  # mov edi, esi                 ; write
    a.label("random_side_keep")
    a.emit(0x3B, 0xF1)  # cmp esi, ecx
    a.jcc(JAE, "random_side_kept")
    a.emit(0x8B, 0x06)  # mov eax, [esi]
    a.call("is_side")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "random_side_next")
    a.emit(0x8B, 0x06)  # mov eax, [esi]
    a.emit(0x89, 0x07)  # mov [edi], eax
    a.emit(0x83, 0xC7, 0x04)  # add edi, 4
    a.label("random_side_next")
    a.emit(0x83, 0xC6, 0x04)  # add esi, 4
    a.jmp("random_side_keep")
    a.label("random_side_kept")
    a.emit(0x89, 0x7D, i8(end))  # mov [ebp-0x24], edi          ; the new end
    a.label("random_side_out")
    a.emit(GAME_START_RANDOM_DRAW_BYTES)  # mov esi, [ebp-0x24] / mov edi, [ebp-0x28]
    a.jmp_absolute(GAME_START_RANDOM_DRAW_RESUME)


def _emit_slot_template(a: Asm) -> None:
    """Where `startNewGame` reads each occupied slot's template (`ebx` the slot) into `esi` for
    the Random pass: a `RANDOM_OF` is settled here, to its faction or a variant of it, and a
    `RANDOM_VARIANTS` to one of every faction's variants; either is set on the slot, so the Random
    pass sees a real template and leaves it alone."""
    a.label("slot_template")
    a.emit(GAME_START_SLOT_TEMPLATE_BYTES[:3])  # mov esi, [ebx+0x18]
    a.emit(0x83, 0xFE, i8(RANDOM_VARIANTS))  # cmp esi, -4
    a.jcc(JNE, "slot_template_of")
    a.call("roll_variants")  # -1 with none: the Random pass draws a faction instead
    a.jmp("slot_template_set")
    a.label("slot_template_of")
    a.emit(0x83, 0xFE, i8(RANDOM_OF))  # cmp esi, -16
    a.jcc(JG, "slot_template_out")
    a.emit(0x81, 0xFE, u32(_LOWEST_TEMPLATE & 0xFFFFFFFF))  # cmp esi, -128
    a.jcc(JL, "slot_template_out")  # nothing this patch wrote
    a.emit(0xB8, u32(RANDOM_OF & 0xFFFFFFFF))  # mov eax, -16
    a.emit(0x2B, 0xC6)  # sub eax, esi                 ; the faction
    a.call("roll")
    a.label("slot_template_set")
    a.emit(0x8B, 0xF0)  # mov esi, eax
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0xCB)  # mov ecx, ebx
    a.call_absolute(GAME_SLOT_SET_PLAYER_TEMPLATE)  # ret 4
    a.label("slot_template_out")
    a.jmp_absolute(GAME_START_SLOT_TEMPLATE_RESUME)


def _emit_random_assign(a: Asm) -> None:
    """Where `startNewGame` hands a Random slot the base faction it drew: a slot on "Random"
    draws again, among that faction and its variants. `ebx` the slot, `esi` the draw - which the
    stock code goes on using, so the variant replaces it there too."""
    a.label("random_assign")
    a.emit(0x83, 0x7B, GAME_SLOT_PLAYER_TEMPLATE, i8(RANDOM_VARIANT))  # cmp dword [ebx+0x18], -3
    a.jcc(JNE, "random_assign_set")
    a.emit(0x8B, 0xC6)  # mov eax, esi
    a.call("roll")
    a.emit(0x8B, 0xF0)  # mov esi, eax
    a.label("random_assign_set")
    a.emit(GAME_START_RANDOM_ASSIGN_BYTES[:3])  # push esi / mov ecx, ebx
    a.call_absolute(GAME_SLOT_SET_PLAYER_TEMPLATE)  # ret 4
    a.jmp_absolute(GAME_START_RANDOM_ASSIGN_RESUME)


def _assemble(code_va: int, lay: _Layout) -> Asm:
    """The cave's code at `code_va`. `_build_section` takes the bytes and `_edits` the label
    addresses from this one layout, so nothing is pointed at a routine that moved."""
    a = Asm(code_va)
    _emit_parse(a, lay)
    _emit_commit(a, lay)
    _emit_parse_hooks(a)
    _emit_lookup(a, lay)
    _emit_parent_of(a)
    _emit_base_of(a)
    _emit_family(a)
    _emit_faction_list(a)
    _emit_random_pool(a)
    _emit_sync_template(a)
    _emit_wrap(a, "fill", MP_SETUP_FACTION_COMBO, keep_pick=True)
    _emit_wrap(a, "sync", MP_SETUP_SYNC_FACTION, keep_pick=False)
    _emit_state(a, lay)
    _emit_refresh(a, lay)
    _emit_changed(a, lay)
    _emit_selection(a, lay)
    _emit_gadget(a, lay)
    _emit_ctor_clear(a, lay)
    _emit_enable(a)
    _emit_open_gate(a, lay)
    _emit_offered(a)
    _emit_roll(a)
    _emit_random_assign(a)
    _emit_any_variant(a)
    _emit_variants(a)
    _emit_slot_template(a)
    _emit_sides(a)
    _emit_random_side(a)
    a.finish()
    return a


def _code_offset(entries: tuple[Entry, ...]) -> int:
    return _TABLE_OFF + _table_span(entries)


def build_section(base_va: int, entries: tuple[Entry, ...] = ()) -> bytes:
    """The whole `.facvar` section for a base: zeroed state, the two strings, the rebuilt field
    table (`entries`, then `VariantOf`), then the code."""
    lay = _Layout(base_va)
    code = _assemble(base_va + _code_offset(entries), lay)
    body = bytearray(_STRINGS_OFF)
    body += _strings()
    body += _table_bytes(base_va + _TABLE_OFF, entries, code.label_va("parse"))
    assert len(body) == _code_offset(entries)
    return bytes(body) + code.finish()


def layout(base_va: int, entries: tuple[Entry, ...] = ()) -> dict[str, int]:
    """Every data slot and routine of the section `build_section` lays out at `base_va`, by name:
    the routines under their labels, the data as `pending`, `count`, `boxes`, `owners`, `items`,
    `rows`, `kind` and `label`."""
    lay = _Layout(base_va)
    code = _assemble(base_va + _code_offset(entries), lay)
    out = {name: code.label_va(name) for name in code._labels}
    out.update(vars(lay))
    return out


class FactionVariantsPatch(Patch):
    """`PlayerTemplate` `VariantOf`, and the game-setup screen that lists variants in a second
    combo box beside their faction instead of beside every other faction."""

    name = "faction-variants"
    author = "officialNecro"
    description = (
        "Add VariantOf = <PlayerTemplate> to PlayerTemplate, so a faction variant is picked in a "
        "second combo box beside its faction in the game-setup screen instead of crowding the "
        "faction list. The faction box lists base factions only; the Variant box lists the "
        "faction (as GUI:FactionVariantStandard) and its playable variants, or the faction alone "
        "when it has none; Random picks among base factions. For a Random slot it offers Random "
        "(a random faction, then a random variant of it, Standard included), Standard (a random "
        "faction as it stands), Variants (any faction's variant, never a base) and, when the mod "
        "has base factions on both sides, Good and Evil (a random faction with Evil = No or "
        "Evil = Yes, as it stands; GUI:FactionVariantGood / GUI:FactionVariantEvil); a faction's "
        "own Variant box leads with Random (that faction, a random variant of it). The movie "
        "must place a ~<slot>."
        "Variant combo box in each MpGameSetup.apt row, or variants cannot be picked at all"
    )

    def apply(self, data: bytearray) -> None:
        table_va = self._resolve(data)
        entries = self._check_build(data, table_va)
        section_va = allocate_section(
            data, SECTION_NAME, lambda base: self._build_section(base, entries), _CHARACTERISTICS
        )
        for file_off, old, new, note in self._edits(data, section_va, entries, table_va):
            apply_byte_patch(data, file_off, old, new, note)

    @staticmethod
    def _resolve(data: bytes | bytearray) -> int:
        """The `PlayerTemplate` field table as the image currently holds it - read from its one
        reference, so this appends to whatever another patch left there."""
        return resolve_table(
            data,
            PLAYER_TEMPLATE_FIELD_TABLE_REFS,
            PLAYER_TEMPLATE_FIELD_TABLE_REF_OPCODES,
            "PlayerTemplate",
        )

    @staticmethod
    def _check_build(data: bytes | bytearray, table_va: int) -> tuple[Entry, ...]:
        entries = read_field_table(data, table_va)
        by_name = {read_cstring(data, name): offset for name, _fn, _ud, offset in entries}
        for field, want in _FINGERPRINT.items():
            got = by_name.get(field)
            if got != want:
                raise ValueError(
                    f"unexpected build: PlayerTemplate.{field} is at "
                    f"{'absent' if got is None else hex(got)}, expected {want:#x}"
                )
        if FIELD_NAME in by_name:
            raise ValueError(
                f"the PlayerTemplate table already names {FIELD_NAME} - this patch is already "
                "applied, or another patch has added the same field"
            )
        return entries

    @staticmethod
    def _code_offset(entries: tuple[Entry, ...]) -> int:
        return _code_offset(entries)

    @staticmethod
    def _build_section(base_va: int, entries: tuple[Entry, ...]) -> bytes:
        return build_section(base_va, entries)

    def _edits(
        self,
        data: bytes | bytearray,
        section_va: int,
        entries: tuple[Entry, ...],
        old_table: int,
        *,
        table_ref: bool = True,
    ) -> list[tuple[int, bytes, bytes, str]]:
        """`(file offset, original, patched, note)` for every engine byte this patch rewrites.

        `table_ref=False` drops the field-table repoint, the one edit a later patch extending the
        same table is entitled to overwrite; `verify` checks the live table names the field
        instead.
        """
        labels = _assemble(section_va + self._code_offset(entries), _Layout(section_va)).label_va
        out: list[tuple[int, bytes, bytes, str]] = []

        def at(va: int) -> int:
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"0x{va:08x} is not mapped - not the expected build")
            return off

        def jump(site: int, original: bytes, label: str, note: str) -> None:
            patched = jmp_rel32(site, labels(label)) + b"\x90" * (len(original) - 5)
            out.append((at(site), original, patched, note))

        def call(site: int, target: int, label: str, note: str) -> None:
            original = b"\xe8" + struct.pack("<i", target - (site + 5))
            patched = b"\xe8" + struct.pack("<i", labels(label) - (site + 5))
            out.append((at(site), original, patched, note))

        if table_ref:
            for ref_va, opcode in zip(
                PLAYER_TEMPLATE_FIELD_TABLE_REFS,
                PLAYER_TEMPLATE_FIELD_TABLE_REF_OPCODES,
                strict=True,
            ):
                out.append(
                    (
                        at(ref_va),
                        bytes([opcode]) + u32(old_table),
                        bytes([opcode]) + u32(section_va + _TABLE_OFF),
                        f"PlayerTemplate field table ref @0x{ref_va:08x}",
                    )
                )
        jump(
            PLAYER_TEMPLATE_PARSED_NEW_KEY,
            PLAYER_TEMPLATE_PARSED_NEW_KEY_BYTES,
            "new_key",
            "new PlayerTemplate key -> VariantOf commit",
        )
        jump(
            PLAYER_TEMPLATE_PARSED_JOIN,
            PLAYER_TEMPLATE_PARSED_JOIN_BYTES,
            "join",
            "PlayerTemplate override key -> VariantOf commit",
        )
        jump(
            MP_SETUP_FACTION_LIST_PLAYABLE,
            MP_SETUP_FACTION_LIST_PLAYABLE_BYTES,
            "faction_list",
            "faction combo fill -> skip variants",
        )
        jump(
            GAME_START_RANDOM_POOL,
            GAME_START_RANDOM_POOL_BYTES,
            "random_pool",
            "Random faction pool -> skip variants",
        )
        jump(
            MP_SETUP_SYNC_FACTION_TEMPLATE,
            MP_SETUP_SYNC_FACTION_TEMPLATE_BYTES,
            "sync_template",
            "faction combo sync -> a variant shows as its faction",
        )
        jump(
            MP_SETUP_SELECTION_UNMATCHED,
            MP_SETUP_SELECTION_UNMATCHED_BYTES,
            "selection",
            "combo selection handler -> Variant boxes",
        )
        jump(
            MP_SETUP_GADGET_HERO_TEST,
            MP_SETUP_GADGET_HERO_TEST_BYTES,
            "gadget",
            "gadget binder -> file the Variant box",
        )
        jump(
            GAME_START_RANDOM_ASSIGN,
            GAME_START_RANDOM_ASSIGN_BYTES,
            "random_assign",
            "Random faction assignment -> draw a variant for Random",
        )
        jump(
            GAME_START_RANDOM_DRAW,
            GAME_START_RANDOM_DRAW_BYTES,
            "random_side",
            "Random faction draw -> Good / Evil keep only their side",
        )
        jump(
            GAME_START_SLOT_TEMPLATE,
            GAME_START_SLOT_TEMPLATE_BYTES,
            "slot_template",
            "startNewGame slot template -> settle a faction's random variant",
        )
        # RANDOM_VARIANT and RANDOM_OF have to survive every reader that bounds a template from
        # below at -2 ...
        for site, original in GAME_SLOT_TEMPLATE_BOUNDS:
            patched = original[:-1] + bytes([_LOWEST_TEMPLATE & 0xFF])
            out.append((at(site), original, patched, f"template lower bound @0x{site:08x} -> -128"))
        # ... and the map preview, which skips observers as "-2 or below", must skip only -2.
        jle, je = bytes([0x0F, 0x8E]), bytes([0x0F, 0x84])
        for site in MAP_PREVIEW_OBSERVER_SKIPS:
            out.append((at(site), jle, je, f"map preview observer skip @0x{site:08x}: jle -> je"))
        for site in MP_SETUP_FACTION_COMBO_CALLS:
            call(site, MP_SETUP_FACTION_COMBO, "fill", f"faction combo fill @0x{site:08x}")
        for site in MP_SETUP_SYNC_FACTION_CALLS:
            call(site, MP_SETUP_SYNC_FACTION, "sync", f"faction combo sync @0x{site:08x}")
        call(
            MP_SETUP_CTOR_FACTION_WINDOWS_CLEAR,
            _MEMSET,
            "ctor_clear",
            "setup screen constructor -> clear the Variant boxes",
        )
        call(
            MP_SETUP_FACTION_ENABLE_CALL,
            WINDOW_ENABLE,
            "enable",
            "faction box enable -> Variant box follows",
        )
        jump(
            COMBO_BOX_OPEN_GATE,
            COMBO_BOX_OPEN_GATE_BYTES,
            "open_gate",
            "combo box drop-down -> a Variant box opens on one entry",
        )
        return out

    def ini_surface(self) -> Engine:
        """`VariantOf`, naming the `PlayerTemplate` a template is a variant of."""
        return Engine(
            fields=(FieldDelta("PlayerTemplate", FIELD_NAME, "Ref:factions", None, self.name),)
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located
        try:
            table_va = self._resolve(data)
            all_entries = read_field_table(data, table_va)
        except ValueError as exc:
            return [f"cannot read the PlayerTemplate field table: {exc}"]
        entries = entries_before(data, all_entries, FIELD_NAME)
        if entries is None:
            return [f"the PlayerTemplate table does not name {FIELD_NAME}"]

        problems: list[str] = []
        lay = _Layout(section_va)
        code = _assemble(section_va + self._code_offset(entries), lay)
        entry = next(e for e in all_entries if read_cstring(data, e[0]) == FIELD_NAME)
        if entry[1] != code.label_va("parse"):
            problems.append(f"{FIELD_NAME} does not use the patch's own parse function")
        if entry[3] != 0:
            problems.append(f"{FIELD_NAME} has a non-zero template offset ({entry[3]:#x})")

        state = bytes(data[section_off : section_off + _STRINGS_OFF])
        if state != bytes(_STRINGS_OFF):
            problems.append("the cave's state is not zero-initialised")
        strings_off = section_off + _STRINGS_OFF
        if bytes(data[strings_off : strings_off + len(_strings())]) != _strings():
            problems.append("the cave does not hold its gadget kind and label strings")
        code_off = section_off + self._code_offset(entries)
        body = code.finish()
        if bytes(data[code_off : code_off + len(body)]) != body:
            problems.append(f"the {SECTION_NAME} code is not the expected routine")

        try:
            edits = self._edits(data, section_va, entries, table_va, table_ref=False)
        except ValueError as exc:
            return [*problems, f"cannot recompute the expected edits (wrong build?): {exc}"]
        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")
        return problems
