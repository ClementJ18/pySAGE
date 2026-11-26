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
  as likely;
* a slot's template may name a Random pool - `RANDOM_POOL` with one bit per template - which
  draws only among the templates it names, variants included, each equally likely;
* a variant saying `EnabledForPvP = No` is held back unless rule 1 (`RULE:ClanGame`) is set,
  which it is not by default: the Variant box does not list it, no Random draws it, and a seat
  still holding it plays its base faction. With `all_variants_box` the patch shows that online-only
  checkbox on every setup screen as `RULE:EnableAllVariants`, so the host can set it; without it
  nothing in skirmish or LAN sets the rule and such a variant is never played;
* in the War of the Ring lobby the Variant box honours the scenario's `DisabledFactions`, the
  `Faction<X>:N` form of `scenario-player-factions` included: a row the scenario refuses that
  seat - the faction's Standard row or a variant - is listed greyed and cannot be picked, as the
  stock faction box lists a faction it refuses.

The movie half is not this patch: the lobby only has a `Variant` box if `MpGameSetup.apt` places
one. Without it every hook degrades to stock except the faction box's filter - variants would then
be unreachable - which is why the ini side is opt-in: no `VariantOf`, nothing is filtered.

Derivation: `../docs/faction-variants.md`.
"""

from __future__ import annotations

import argparse
import struct
from collections.abc import Iterable

from sage_ini.engine import Engine, FieldDelta

from ...addresses import (
    ASCII_STRING_CTOR,
    ASCII_STRING_DTOR,
    COMBO_BOX_ADD_ENTRY,
    COMBO_BOX_DISABLED_COLOR,
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
    COMBO_BOX_SET_ITEM_DISABLED,
    COMBO_BOX_SET_SELECTED,
    COMBO_BOX_TOGGLE_BOX_EBP,
    GAME_INFO_GET_SLOT,
    GAME_INFO_PARSE_TEMPLATE_CHECKS,
    GAME_INFO_RULE_CLAN_GAME,
    GAME_LOGIC_RANDOM_VALUE,
    GAME_LOGIC_SOURCE_FILE,
    GAME_RULES_CLAN_GAME_HIDE,
    GAME_RULES_CLAN_GAME_HIDE_BYTES,
    GAME_RULES_CLAN_GAME_LABEL,
    GAME_RULES_NAMES,
    GAME_SLOT_PLAYER_TEMPLATE,
    GAME_SLOT_REQUEST_TEMPLATE_CHECK,
    GAME_SLOT_SET_PLAYER_TEMPLATE,
    GAME_SLOT_SET_TEMPLATE_OBSERVER_JG,
    GAME_SLOT_STATE,
    GAME_SLOT_STATE_CLOSED,
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
    INI_PARSE_BOOL,
    KEY_ESC,
    KEY_STATE_UP,
    LIVING_WORLD_CAMPAIGN_MANAGER_GET_CAMPAIGN,
    LIVING_WORLD_CAMPAIGN_SCENARIO,
    MAP_PREVIEW_OBSERVER_SKIPS,
    MP_SETUP_CLAN_GAME_READS,
    MP_SETUP_COMMAND_BLOCK,
    MP_SETUP_COMMAND_BLOCK_BYTES,
    MP_SETUP_COMMAND_BLOCK_RESUME,
    MP_SETUP_COMMAND_FUNCTOR_CTOR,
    MP_SETUP_COMMAND_MAP,
    MP_SETUP_COMMAND_MAP_INSERT,
    MP_SETUP_CTOR_FACTION_WINDOWS_CLEAR,
    MP_SETUP_CTOR_FACTION_WINDOWS_CLEAR_BYTES,
    MP_SETUP_CURRENT,
    MP_SETUP_DIRTY,
    MP_SETUP_DROPDOWN_LINES,
    MP_SETUP_EXTERN_MAP,
    MP_SETUP_EXTERN_MAP_INSERT,
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
    MP_SETUP_WOTR_SCENARIO_INDEX,
    MULTIPLAYER_COLOR_VALUE,
    MULTIPLAYER_SETTINGS_GET_COLOR,
    NAME_KEY_FROM_CSTR,
    PLAYER_TEMPLATE_EVIL,
    PLAYER_TEMPLATE_FIELD_TABLE_REF_OPCODES,
    PLAYER_TEMPLATE_FIELD_TABLE_REFS,
    PLAYER_TEMPLATE_FIND_BY_INDEX,
    PLAYER_TEMPLATE_GET_DISPLAY_NAME,
    PLAYER_TEMPLATE_GET_NAME,
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
    THE_GAME_INFO,
    THE_GAME_TEXT,
    THE_LIVING_WORLD_CAMPAIGN_MANAGER,
    THE_MULTIPLAYER_SETTINGS,
    THE_NAME_KEY_GENERATOR,
    THE_PLAYER_TEMPLATE_STORE,
    UNICODE_STRING_CONCAT,
    UNICODE_STRING_DTOR,
    UNICODE_STRING_FROM_WIDE,
    WIDE_DASH,
    WINDOW_ENABLE,
    WINDOW_HIDE,
    WINDOW_MANAGER_PROCESS_KEY,
    WINDOW_MANAGER_PROCESS_KEY_BYTES,
    WINDOW_MANAGER_PROCESS_KEY_RESUME,
    WINDOW_MANAGER_PROCESS_MOUSE,
    WINDOW_MANAGER_PROCESS_MOUSE_BYTES,
    WINDOW_MANAGER_PROCESS_MOUSE_RESUME,
    WINDOW_STATUS,
    WINDOW_STATUS_ENABLED,
    WINDOW_STATUS_HIDDEN,
)
from ...asm import JA, JAE, JE, JG, JGE, JL, JLE, JNE, Asm
from ...patcher import Patch
from ...utils import (
    allocate_section,
    apply_byte_patch,
    find_section,
    i8,
    jmp_rel32,
    read_cstring,
    u32,
    va_to_offset,
)
from ..campaign.scenario_player_factions import emit_is_faction_enabled
from ..utils.field_tables import Entry, entries_before, read_field_table, resolve_table

__all__ = [
    "ALL_VARIANTS_LABEL",
    "ALL_VARIANTS_RULE",
    "EVIL_LABEL",
    "FIELD_NAME",
    "GADGET_KIND",
    "GOOD_LABEL",
    "RANDOM_OF",
    "POOL_COMMAND",
    "POOL_EXTERN",
    "PVP_FIELD_NAME",
    "SEAT_EXTERN",
    "ESCAPE_EXTERN",
    "POOL_MODAL_COMMAND",
    "RANDOM_EVIL",
    "RANDOM_GOOD",
    "RANDOM_OF_MAX_INDEX",
    "LAN_POOL_ESCAPE",
    "RANDOM_POOL",
    "RANDOM_POOL_BITS",
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
    "emit_command_block",
    "layout",
    "pool_indices",
    "random_pool",
]

SECTION_NAME = ".facvar"  # 7 chars: the PE name field is 8 bytes and truncates silently

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE: code, the rebuilt field
# table, and state written at INI load and while the setup screen is up.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: The `PlayerTemplate` keyword this patch adds.
FIELD_NAME = "VariantOf"

#: The second `PlayerTemplate` keyword: a `Bool`, `Yes` when not given. A variant saying `No` is
#: one a match may only field while `ALL_VARIANTS_RULE` is set. Read on variants only - a base
#: faction is always offered.
PVP_FIELD_NAME = "EnabledForPvP"

#: The lobby rule that lets every variant be played: rule 1, `RULE:ClanGame` - a checkbox only an
#: online clan match shows and no simulation code reads, clear by default. With `all_variants_box`
#: the patch shows it on every setup screen, under `ALL_VARIANTS_LABEL`. The host sets it; it
#: travels with the other rules, so every peer, `Skirmish.ini` and the replay header agree on it.
ALL_VARIANTS_RULE = 1
ALL_VARIANTS_LABEL = "RULE:EnableAllVariants"
if GAME_INFO_RULE_CLAN_GAME != 0x60 + 4 * ALL_VARIANTS_RULE:
    raise ValueError("GAME_INFO_RULE_CLAN_GAME is not rule 1")

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

#: The command the game-setup movie sends a seat's Random pool with:
#: `_root.GameCodeNoPrefix("MpGameSetup::SetRandomPool", "<slot>:<mask>")` (the movie's `GameCode`
#: prefixes `_root.CodePrefix`, which this screen never sets), the mask's decimal bits naming
#: template indices, 0 for plain Random. Registered beside the screen's own commands.
POOL_COMMAND = "MpGameSetup::SetRandomPool"

#: The command the panel sends as it opens (`"1"`) and closes (anything else). While it is open
#: the lobby's windows take no mouse input, so every click reaches the panel - the windows the
#: panel is drawn over would take them first otherwise. Leaving the screen ends it however the
#: panel was closed.
POOL_MODAL_COMMAND = "MpGameSetup::RandomPoolModal"

#: The values the panel reads a seat's pool back with as it opens:
#: `_root.GetExtern("MpGameSetup::RandomPool<slot>")`, slot 0 to 7, is the seat's mask in decimal,
#: `"0"` for a seat that is not a pool. The engine keeps the pool in the seat - across a match and
#: back - while the movie's own variables go with the screen, so the seat is what the panel shows.
POOL_EXTERN = "MpGameSetup::RandomPool"

#: Whether a seat's row button may be used: `_root.GetExtern("MpGameSetup::RandomPoolSeat<slot>")`,
#: slot 0 to 7, is `"2"` when the seat's faction box is shown and enabled (the player may change
#: it), `"1"` when it is shown but disabled (another player's seat), and `"0"` when it is hidden or
#: there is none. The movie polls it, since nothing tells it when a box is enabled or disabled.
SEAT_EXTERN = "MpGameSetup::RandomPoolSeat"

#: Whether Escape was let go of while the panel was open: `_root.GetExtern(ESCAPE_EXTERN)` is
#: `"1"` once it was, `"0"` otherwise. The setup screens have no window that takes Escape, so
#: while the panel is open the patch keeps it from the windows and records it here, and the panel
#: polls it and closes as Back does. `POOL_MODAL_COMMAND` clears it, opening or closing.
ESCAPE_EXTERN = "MpGameSetup::RandomPoolEscape"

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
#: bounds the index: `RANDOM_OF - RANDOM_OF_MAX_INDEX` is -127, -128 being `LAN_POOL_ESCAPE`,
#: and a faction past it gets no
#: Random row.
RANDOM_OF = -16
RANDOM_OF_MAX_INDEX = 111

#: The lowest template any reader has to accept once `RANDOM_OF` is in play.
_LOWEST_TEMPLATE = RANDOM_OF - RANDOM_OF_MAX_INDEX

#: A slot's template for "Random, among these templates only": `RANDOM_POOL | mask`, bit n of the
#: 24-bit mask for template index n. Drawn at game start among the named templates that are
#: playable and whose faction the slot's start position allows - variants included, each equally
#: likely - and played as drawn. A pool naming none of those draws as `RANDOM_STANDARD` does. The
#: value is far below every other sentinel, so every reader that tells Random from a template by
#: `< 0` already takes it for Random; the lobby string carries it as the decimal it is.
RANDOM_POOL = -0x80000000
#: Template indices a pool can name. The top byte is the tag, `0x80`; three bytes of mask are
#: what the LAN packet has room to carry after `LAN_POOL_ESCAPE`.
RANDOM_POOL_BITS = 24
_POOL_TAG_BITS = 0xFF000000
_POOL_MASK_BITS = (1 << RANDOM_POOL_BITS) - 1


def random_pool(indices: Iterable[int]) -> int:
    """The slot template for a Random pool of `indices`; raises on an index a pool cannot name, or
    on no index at all."""
    mask = 0
    for index in indices:
        if not 0 <= index < RANDOM_POOL_BITS:
            raise ValueError(f"a Random pool names template indices 0..{RANDOM_POOL_BITS - 1}")
        mask |= 1 << index
    if not mask:
        raise ValueError("a Random pool names at least one template")
    return RANDOM_POOL | mask


def pool_indices(template: int) -> frozenset[int] | None:
    """The template indices a slot template's Random pool names, or None when it is not one."""
    bits = template & 0xFFFFFFFF
    if bits & _POOL_TAG_BITS != RANDOM_POOL & 0xFFFFFFFF or not bits & _POOL_MASK_BITS:
        return None
    return frozenset(i for i in range(RANDOM_POOL_BITS) if bits >> i & 1)


#: The template byte the LAN packet carries for a Random pool, followed by its mask's three bytes,
#: low first. Every LAN reader's lower bound is this rather than `_LOWEST_TEMPLATE`, so the byte
#: gets through to where the pool is put back together.
LAN_POOL_ESCAPE = -128

#: Lobby slots. The screen's own per-slot arrays hold eight, and so do this cave's.
SLOTS = 8

#: Templates declaring `VariantOf` or `EnabledForPvP` the table holds. Edain defines about forty
#: `PlayerTemplate` blocks, so this is room, not a design limit; a declaration past it is parsed
#: and dropped.
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
_ROWS_OFF = _ITEMS_OFF + SLOTS * 4  # {key, parent key, PvP} per declaring template
#: A row: the template's key, the key it is a variant of (0: none), and its `EnabledForPvP` - 0
#: unstated, 1 No, 2 Yes.
_ROW_SIZE = 12
_ROW_PARENT = 4
_ROW_PVP = 8
_PVP_NO = 1
#: The game-setup screen that has the Random-pool panel open (`POOL_MODAL_COMMAND`), or 0.
_MODAL_OFF = _ROWS_OFF + ROWS * _ROW_SIZE
#: `EnabledForPvP` as read, `_ROW_PVP`'s encoding, until the block's own key is written.
_PENDING_PVP_OFF = _MODAL_OFF + 4
#: `ALL_VARIANTS_RULE` of the match being set up or started, nonzero when every variant may be
#: played: written from the screen's game info before the Variant box is filled, and from
#: `TheGameInfo` before `startNewGame` settles a slot.
_ALLOW_OFF = _PENDING_PVP_OFF + 4
#: Nonzero once Escape was let go of while the panel was open (`ESCAPE_EXTERN`).
_ESCAPE_OFF = _ALLOW_OFF + 4
_STRINGS_OFF = _ESCAPE_OFF + 4
#: Everything the setup screen's constructor clears, in dwords: boxes, owners and item counts.
_SLOT_STATE_DWORDS = 3 * SLOTS


def _strings() -> bytes:
    """The C strings the cave names - the gadget kind and the row labels - and an
    empty wide string, the name a template without one is formatted with."""
    out = bytearray()
    for text in (
        GADGET_KIND,
        STANDARD_LABEL,
        VARIANTS_LABEL,
        GOOD_LABEL,
        EVIL_LABEL,
        POOL_COMMAND,
        POOL_MODAL_COMMAND,
        *(f"{POOL_EXTERN}{slot}" for slot in range(SLOTS)),
        *(f"{SEAT_EXTERN}{slot}" for slot in range(SLOTS)),
        ALL_VARIANTS_LABEL,
        ESCAPE_EXTERN,
    ):
        out += text.encode("ascii") + b"\x00"
    out += b"\x00" * (-len(out) % 4)
    return bytes(out) + bytes(4)


_KIND_OFF = _STRINGS_OFF
_LABEL_OFF = _STRINGS_OFF + len(GADGET_KIND) + 1
_VARIANTS_LABEL_OFF = _LABEL_OFF + len(STANDARD_LABEL) + 1
_GOOD_LABEL_OFF = _VARIANTS_LABEL_OFF + len(VARIANTS_LABEL) + 1
_EVIL_LABEL_OFF = _GOOD_LABEL_OFF + len(GOOD_LABEL) + 1
_POOL_COMMAND_OFF = _EVIL_LABEL_OFF + len(EVIL_LABEL) + 1
_POOL_MODAL_COMMAND_OFF = _POOL_COMMAND_OFF + len(POOL_COMMAND) + 1
_POOL_EXTERN_OFF = _POOL_MODAL_COMMAND_OFF + len(POOL_MODAL_COMMAND) + 1
#: One extern name, `POOL_EXTERN` and its slot digit.
_POOL_EXTERN_LEN = len(POOL_EXTERN) + 2
_SEAT_EXTERN_OFF = _POOL_EXTERN_OFF + SLOTS * _POOL_EXTERN_LEN
_SEAT_EXTERN_LEN = len(SEAT_EXTERN) + 2
_ALL_VARIANTS_LABEL_OFF = _SEAT_EXTERN_OFF + SLOTS * _SEAT_EXTERN_LEN
_ESCAPE_EXTERN_OFF = _ALL_VARIANTS_LABEL_OFF + len(ALL_VARIANTS_LABEL) + 1
_WIDE_EMPTY_OFF = _STRINGS_OFF + len(_strings()) - 4
_TABLE_OFF = _STRINGS_OFF + len(_strings())

#: The rows this patch appends to the `PlayerTemplate` field table, in order.
_FIELD_NAMES = (FIELD_NAME, PVP_FIELD_NAME)


def _table_span(entries: tuple[Entry, ...]) -> int:
    """The rebuilt field table plus its padded name strings, in bytes."""
    names = sum(len(name) + 1 for name in _FIELD_NAMES)
    return (len(entries) + len(_FIELD_NAMES) + 1) * 16 + names + (-names % 4)


def _table_bytes(
    table_va: int, entries: tuple[Entry, ...], parse_fn: int, parse_pvp_fn: int
) -> bytes:
    """The live `PlayerTemplate` table by pointer, the `VariantOf` and `EnabledForPvP` rows, the
    terminator, and the rows' names. Offset 0: the values land in the cave's table, never in the
    template."""
    name_va = table_va + (len(entries) + len(_FIELD_NAMES) + 1) * 16
    out = bytearray()
    for entry in entries:
        out += struct.pack("<IIII", *entry)
    for name, parse in zip(_FIELD_NAMES, (parse_fn, parse_pvp_fn), strict=True):
        out += struct.pack("<IIII", name_va, parse, 0, 0)
        name_va += len(name) + 1
    out += bytes(16)
    for name in _FIELD_NAMES:
        out += name.encode("ascii") + b"\x00"
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
        self.pool_command = base_va + _POOL_COMMAND_OFF
        self.pool_modal_command = base_va + _POOL_MODAL_COMMAND_OFF
        self.pool_externs = [
            base_va + _POOL_EXTERN_OFF + slot * _POOL_EXTERN_LEN for slot in range(SLOTS)
        ]
        self.seat_externs = [
            base_va + _SEAT_EXTERN_OFF + slot * _SEAT_EXTERN_LEN for slot in range(SLOTS)
        ]
        self.modal = base_va + _MODAL_OFF
        self.pending_pvp = base_va + _PENDING_PVP_OFF
        self.allow = base_va + _ALLOW_OFF
        self.all_variants_label = base_va + _ALL_VARIANTS_LABEL_OFF
        self.escape = base_va + _ESCAPE_OFF
        self.escape_extern = base_va + _ESCAPE_EXTERN_OFF


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


def _emit_parse_pvp(a: Asm, lay: _Layout) -> None:
    """`EnabledForPvP`'s parse function, cdecl like `parse`: the stock `INI::parseBool` into a
    local, kept in `pending_pvp` as `_ROW_PVP` encodes it for `commit` to file."""
    a.label("parse_pvp")
    a.emit(0x55)  # push ebp
    a.emit(0x8B, 0xEC)  # mov ebp, esp
    a.emit(0x6A, 0x00)  # push 0                       ; [ebp-4]: the Bool
    a.emit(0xFF, 0x75, 0x14)  # push dword [ebp+0x14]        ; userData
    a.emit(0x8D, 0x45, 0xFC)  # lea eax, [ebp-4]
    a.emit(0x50)  # push eax                     ; store
    a.emit(0xFF, 0x75, 0x0C)  # push dword [ebp+0xc]         ; instance
    a.emit(0xFF, 0x75, 0x08)  # push dword [ebp+8]           ; ini
    a.call_absolute(INI_PARSE_BOOL)
    a.emit(0x83, 0xC4, 0x10)  # add esp, 0x10
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.emit(0x80, 0x7D, 0xFC, 0x00)  # cmp byte [ebp-4], 0
    a.emit(0x0F, 0x95, 0xC0)  # setne al
    a.emit(0x40)  # inc eax                      ; No is 1, Yes is 2
    a.emit(0xA3, u32(lay.pending_pvp))  # mov [pending_pvp], eax
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret                          ; cdecl


def _emit_commit(a: Asm, lay: _Layout) -> None:
    """`commit`: `edi` = the key of the block just parsed. Files `pending` and `pending_pvp`
    against it.

    A block re-declaring either field replaces that field of its row, and a block that does not
    keeps what an earlier one filed. A table that is full drops the new declaration, which leaves
    that template a plain faction - the degradation a reader of the lobby can see and a crash is
    not. Preserves everything.
    """
    a.label("commit")
    a.emit(0x50, 0x51, 0x52)  # push eax / push ecx / push edx
    a.emit(0xA1, u32(lay.pending))  # mov eax, [pending]
    a.emit(0x0B, 0x05, u32(lay.pending_pvp))  # or eax, [pending_pvp]
    a.jcc(JE, "commit_out")  # this block said nothing
    a.emit(0x85, 0xFF)  # test edi, edi
    a.jcc(JE, "commit_clear")
    a.emit(0x8B, 0x0D, u32(lay.count))  # mov ecx, [count]
    a.emit(0xBA, u32(lay.rows))  # mov edx, rows
    a.label("commit_find")
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "commit_append")
    a.emit(0x39, 0x3A)  # cmp [edx], edi
    a.jcc(JE, "commit_set")
    a.emit(0x83, 0xC2, _ROW_SIZE)  # add edx, 12
    a.emit(0x49)  # dec ecx
    a.jmp("commit_find")
    a.label("commit_append")  # edx is the first free row
    a.emit(0x81, 0x3D, u32(lay.count), u32(ROWS))  # cmp dword [count], ROWS
    a.jcc(JAE, "commit_clear")
    a.emit(0x89, 0x3A)  # mov [edx], edi
    a.emit(0x83, 0x62, _ROW_PARENT, 0x00)  # and dword [edx+4], 0
    a.emit(0x83, 0x62, _ROW_PVP, 0x00)  # and dword [edx+8], 0
    a.emit(0xFF, 0x05, u32(lay.count))  # inc dword [count]
    a.label("commit_set")
    a.emit(0xA1, u32(lay.pending))  # mov eax, [pending]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "commit_set_pvp")
    a.emit(0x89, 0x42, _ROW_PARENT)  # mov [edx+4], eax
    a.label("commit_set_pvp")
    a.emit(0xA1, u32(lay.pending_pvp))  # mov eax, [pending_pvp]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "commit_clear")
    a.emit(0x89, 0x42, _ROW_PVP)  # mov [edx+8], eax
    a.label("commit_clear")
    a.emit(0x83, 0x25, u32(lay.pending), 0x00)  # and dword [pending], 0
    a.emit(0x83, 0x25, u32(lay.pending_pvp), 0x00)  # and dword [pending_pvp], 0
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
    """`lookup`: `eax` = a template key, `eax` = the key it is a variant of, or 0. `pvp_of`: the
    same key, `eax` = its `EnabledForPvP` as `_ROW_PVP` encodes it, 0 when unstated. Both preserve
    the rest. Linear, because they run a few hundred times per lobby redraw over a table of
    dozens."""
    for name, field in (("lookup", _ROW_PARENT), ("pvp_of", _ROW_PVP)):
        a.label(name)
        a.emit(0x51, 0x52)  # push ecx / push edx
        a.emit(0x8B, 0x0D, u32(lay.count))  # mov ecx, [count]
        a.emit(0xBA, u32(lay.rows))  # mov edx, rows
        a.label(f"{name}_loop")
        a.emit(0x85, 0xC9)  # test ecx, ecx
        a.jcc(JE, f"{name}_miss")
        a.emit(0x39, 0x02)  # cmp [edx], eax
        a.jcc(JE, f"{name}_hit")
        a.emit(0x83, 0xC2, _ROW_SIZE)  # add edx, 12
        a.emit(0x49)  # dec ecx
        a.jmp(f"{name}_loop")
        a.label(f"{name}_hit")
        a.emit(0x8B, 0x42, field)  # mov eax, [edx+field]
        a.jmp(f"{name}_out")
        a.label(f"{name}_miss")
        a.emit(0x31, 0xC0)  # xor eax, eax
        a.label(f"{name}_out")
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


def _emit_blocked(a: Asm, lay: _Layout) -> None:
    """`blocked`: `eax` = a template index, `eax` = 1 when it is a variant saying
    `EnabledForPvP = No` and `allow` is clear - a template this match may not field. Anything
    else, a base faction or a sentinel included, is 0. Preserves the rest."""
    a.label("blocked")
    a.emit(0x51, 0x52)  # push ecx / push edx
    a.emit(0x8B, 0xC8)  # mov ecx, eax                 ; the index asked about
    a.emit(0x83, 0x3D, u32(lay.allow), 0x00)  # cmp dword [allow], 0
    a.jcc(JNE, "blocked_no")  # every variant may be played
    a.call("parent_of")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JL, "blocked_no")  # not a variant - in range, when it is one
    a.emit(0x8B, 0x15, u32(THE_PLAYER_TEMPLATE_STORE))  # mov edx, [ThePlayerTemplateStore]
    a.emit(0x8B, 0x52, PLAYER_TEMPLATE_STORE_BEGIN)  # mov edx, [edx+0xc]
    a.emit(0x69, 0xC1, u32(PLAYER_TEMPLATE_SIZE))  # imul eax, ecx, 0x1dc
    a.emit(0x8B, 0x44, 0x10, PLAYER_TEMPLATE_NAME_KEY)  # mov eax, [eax+edx+0x10]
    a.call("pvp_of")
    a.emit(0x83, 0xF8, _PVP_NO)  # cmp eax, 1
    a.jcc(JNE, "blocked_no")
    a.emit(0xB8, u32(1))  # mov eax, 1
    a.jmp("blocked_out")
    a.label("blocked_no")
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.label("blocked_out")
    a.emit(0x5A, 0x59)  # pop edx / pop ecx
    a.emit(0xC3)  # ret


def _emit_refused(a: Asm) -> None:
    """`refused`: `eax` = a template index, `ecx` = the War of the Ring `Scenario` (0 for every
    other lobby), `edi` = the slot. `eax` = 1 when the scenario's `DisabledFactions` bars that
    slot from the template - scenario-wide or through a `:N` naming it - else 0. Preserves the
    rest.

    The answer is `scenario-player-factions`' own matcher (`scenario_enabled`), handed the
    template's name as the stock faction fill hands it (`0x00844E23`..`0x00844E51`): an
    `AsciiString` built in place by `PlayerTemplate::getName`, which the matcher destroys. So a
    Variant box row is refused exactly when the faction box would refuse the same template.
    """
    a.label("refused")
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "refused_none")  # not a War of the Ring lobby
    a.emit(0x51, 0x52, 0x56)  # push ecx / push edx / push esi
    a.emit(0x8B, 0xF1)  # mov esi, ecx                 ; the Scenario
    a.emit(0x50)  # push eax
    a.emit(0x8B, 0x0D, u32(THE_PLAYER_TEMPLATE_STORE))  # mov ecx, [ThePlayerTemplateStore]
    a.call_absolute(PLAYER_TEMPLATE_FIND_BY_INDEX)  # ret 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "refused_pop")  # not a template: nothing to refuse
    a.emit(0x51)  # push ecx                     ; the name's slot, the matcher's argument
    a.emit(0x8B, 0xD4)  # mov edx, esp
    a.emit(0x52)  # push edx
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.call_absolute(PLAYER_TEMPLATE_GET_NAME)  # ret 4
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.emit(0x8B, 0xD7)  # mov edx, edi                 ; the slot
    a.call("scenario_enabled")  # ret 4: the argument is gone
    a.emit(0x34, 0x01)  # xor al, 1
    a.emit(0x0F, 0xB6, 0xC0)  # movzx eax, al
    a.jmp("refused_out")
    a.label("refused_pop")
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.label("refused_out")
    a.emit(0x5E, 0x5A, 0x59)  # pop esi / pop edx / pop ecx
    a.emit(0xC3)  # ret
    a.label("refused_none")
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.emit(0xC3)  # ret


def _emit_allow_from_game(a: Asm, lay: _Layout) -> None:
    """`allow_from_game`: `allow` from the match `startNewGame` is starting - `TheGameInfo`'s
    `ALL_VARIANTS_RULE` - so every peer and every replay draws from the same templates. No game
    info (a campaign) bars nothing. Preserves everything, flags aside."""
    a.label("allow_from_game")
    a.emit(0x50)  # push eax
    a.emit(0xA1, u32(THE_GAME_INFO))  # mov eax, [TheGameInfo]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "allow_from_game_all")
    a.emit(0x8B, 0x40, GAME_INFO_RULE_CLAN_GAME)  # mov eax, [eax+0x64]
    a.jmp("allow_from_game_set")
    a.label("allow_from_game_all")
    a.emit(0xB8, u32(1))  # mov eax, 1
    a.label("allow_from_game_set")
    a.emit(0xA3, u32(lay.allow))  # mov [allow], eax
    a.emit(0x58)  # pop eax
    a.emit(0xC3)  # ret


def _emit_family(a: Asm) -> None:
    """`family`: `eax` = a slot's template, `eax` = what its faction box shows - a variant's base,
    the faction of a `RANDOM_OF`, `RANDOM_STANDARD` for every Random of a slot (`RANDOM_VARIANT`
    down to just above `RANDOM_OF`: Random, Variants, Good, Evil; and a `RANDOM_POOL`, below
    them all), Observer as itself. Preserves the rest."""
    a.label("family")
    a.emit(0x83, 0xF8, i8(_LOWEST_TEMPLATE))  # cmp eax, -127
    a.jcc(JL, "family_any")  # a Random pool
    a.emit(0x83, 0xF8, i8(RANDOM_OF))  # cmp eax, -16
    a.jcc(JG, "family_random")
    a.emit(0xF7, 0xD8)  # neg eax
    a.emit(0x83, 0xC0, i8(RANDOM_OF))  # add eax, -16               ; RANDOM_OF - eax
    a.emit(0xC3)  # ret
    a.label("family_random")
    a.emit(0x83, 0xF8, i8(RANDOM_VARIANT))  # cmp eax, -3
    a.jcc(JG, "family_template")  # Standard, Observer, a template
    a.label("family_any")
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
    """`state`: show the Variant box as its faction box is shown - while it lists something - and
    enable it as its faction box is enabled, but only when it lists two rows or more. A box of
    one row - a faction without variants, or a closed seat's `-` - has nothing to choose, so it
    is drawn as another player's is, its arrow greyed. `esi` the screen, `edi` the slot;
    preserves everything.

    An enabled box also gets its drop-down button enabled, so its arrow shows as every other
    column's does: `WINDOW_ENABLE` enables the button with the box and then lets the gadget
    (`COMBO_BOX_ENABLE_NOTIFY`) disable it again while it holds fewer than two entries, so the
    button is re-enabled after that.
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
    a.emit(0x83, 0x3C, 0xBD, u32(lay.items), 0x02)  # cmp dword [items+edi*4], 2
    a.jcc(JAE, "state_apply")
    a.emit(0x31, 0xED)  # xor ebp, ebp                 ; one row: nothing to choose
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
_SLOT_STATE = -0x34  # the seat's state: open, closed, an AI, a human
_HELD = -0x38  # nonzero while the row being added is held back or refused
_SCENARIO = -0x3C  # the War of the Ring `Scenario`, or 0
_ROW_COLOR = -0x40  # the colour of the row being added
_FRAME = 0x44


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


def _emit_standard_row(
    a: Asm, lay: _Layout, *, random: bool, tag: str, color_ebp: int = _COLOR
) -> None:
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

    a.emit(0xFF, 0x75, i8(color_ebp))  # push dword [ebp+colour]
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


def _emit_held_color(a: Asm, tag: str) -> None:
    """`_ROW_COLOR` = the disabled colour while `_HELD` is set, else `_COLOR`."""
    a.emit(0x8B, 0x45, i8(_COLOR))  # mov eax, [ebp-0x1c]
    a.emit(0x83, 0x7D, i8(_HELD), 0x00)  # cmp dword [ebp-0x38], 0
    a.jcc(JE, f"{tag}_color")
    a.emit(0xA1, u32(COMBO_BOX_DISABLED_COLOR))  # mov eax, [disabled colour]
    a.label(f"{tag}_color")
    a.emit(0x89, 0x45, i8(_ROW_COLOR))  # mov [ebp-0x40], eax


def _emit_disable_if_held(a: Asm, tag: str) -> None:
    """Make the row just added unpickable while `_HELD` is set, as the stock fill does a faction
    the scenario refuses (`0x00844EA7`)."""
    a.emit(0x83, 0x7D, i8(_HELD), 0x00)  # cmp dword [ebp-0x38], 0
    a.jcc(JE, f"{tag}_pickable")
    a.emit(0x6A, 0x01)  # push 1
    a.emit(0xFF, 0x75, i8(_ROW))  # push dword [ebp-0x24]       ; the row just added
    a.emit(0x53)  # push ebx
    a.call_absolute(COMBO_BOX_SET_ITEM_DISABLED)  # cdecl
    a.emit(0x83, 0xC4, 0x0C)  # add esp, 0xc
    a.label(f"{tag}_pickable")


def _emit_standard_held(a: Asm, tag: str) -> None:
    """`_HELD` and `_ROW_COLOR` for the faction's own row: refused when the scenario bars this
    seat from the faction itself."""
    a.emit(0x8B, 0x45, i8(_BASE))  # mov eax, [ebp-8]
    a.emit(0x8B, 0x4D, i8(_SCENARIO))  # mov ecx, [ebp-0x3c]
    a.call("refused")
    a.emit(0x89, 0x45, i8(_HELD))  # mov [ebp-0x38], eax
    _emit_held_color(a, tag)


def _emit_refresh(a: Asm, lay: _Layout) -> None:
    """`refresh`: rebuild this slot's Variant box. `esi` the screen, `edi` the slot, `eax` 1 to
    keep the box's own pick when it is of the slot's faction, 0 to show the slot as it stands.
    Never called from the box's own selection message: it resets the box. Preserves everything.

    A closed seat gets one `-` row, as its faction box shows. A faction with no playable variant
    gets its Standard row alone. One with variants lists
    the faction first, under `STANDARD_LABEL`, and its variants
    in store order, each with its template index as the row's data, which is what the faction box
    carries too, behind a `GUI:Random` row (`RANDOM_OF - base`). A Random slot gets its own rows
    instead: `GUI:Random` (`RANDOM_VARIANT`) and `STANDARD_LABEL` (`RANDOM_STANDARD`), then
    `VARIANTS_LABEL` (`RANDOM_VARIANTS`) when the mod has a variant, and `GOOD_LABEL` /
    `EVIL_LABEL` (`RANDOM_GOOD` / `RANDOM_EVIL`) when it has base factions on both sides.

    A held-back variant, and in the War of the Ring lobby any row the scenario refuses this
    seat (`refused`), is listed in the disabled colour and cannot be picked.
    """
    a.label("refresh")
    a.emit(0x60)  # pushad
    a.emit(0x8B, 0xEC)  # mov ebp, esp
    a.emit(0x83, 0xEC, _FRAME)  # sub esp, 0x3c
    a.emit(0x89, 0x45, i8(_COUNT))  # mov [ebp-0x14], eax         ; the flag, for now
    _emit_slot_box(a, lay, "refresh_out")
    a.emit(0x8B, 0x4E, MP_SETUP_GAME_INFO)  # mov ecx, [esi+0x5c]
    a.call_absolute(MP_SETUP_GET_GAME_INFO)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "refresh_out")
    a.emit(0x8B, 0x48, GAME_INFO_RULE_CLAN_GAME)  # mov ecx, [eax+0x64]
    a.emit(0x89, 0x0D, u32(lay.allow))  # mov [allow], ecx           ; this lobby's rule
    a.emit(0x57)  # push edi
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.call_absolute(GAME_INFO_GET_SLOT)  # ret 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "refresh_out")
    a.emit(0x8B, 0x48, GAME_SLOT_STATE)  # mov ecx, [eax+4]
    a.emit(0x89, 0x4D, i8(_SLOT_STATE))  # mov [ebp-0x34], ecx
    a.emit(0x8B, 0x40, GAME_SLOT_PLAYER_TEMPLATE)  # mov eax, [eax+0x18]
    a.emit(0x89, 0x45, i8(_WANT))  # mov [ebp-4], eax

    # A seat left on a variant the lobby has since barred plays its faction, and shows it.
    a.call("blocked")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "refresh_allowed")
    a.emit(0x8B, 0x45, i8(_WANT))  # mov eax, [ebp-4]
    a.call("base_of")
    a.emit(0x89, 0x45, i8(_WANT))  # mov [ebp-4], eax
    a.label("refresh_allowed")

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
    a.emit(0x8B, 0x0D, u32(THE_MULTIPLAYER_SETTINGS))  # mov ecx, [TheMultiplayerSettings]
    a.emit(0x6A, 0xFF)  # push -1
    a.call_absolute(MULTIPLAYER_SETTINGS_GET_COLOR)  # ret 4
    a.emit(0x8B, 0x40, MULTIPLAYER_COLOR_VALUE)  # mov eax, [eax+0x10]
    a.emit(0x89, 0x45, i8(_COLOR))  # mov [ebp-0x1c], eax

    # The War of the Ring scenario this lobby plays, as the faction fill finds it (0x00844E17).
    a.emit(0x83, 0x65, i8(_SCENARIO), 0x00)  # and dword [ebp-0x3c], 0
    a.emit(0x83, 0x7E, MP_SETUP_MODE, MP_SETUP_MODE_WOTR)  # cmp dword [esi+0x7c], 1
    a.jcc(JNE, "refresh_no_scenario")
    a.emit(0x8D, 0x4E, MP_SETUP_WOTR)  # lea ecx, [esi+0x60]
    a.call_absolute(MP_SETUP_WOTR_SCENARIO_INDEX)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JL, "refresh_no_scenario")
    a.emit(0x50)  # push eax
    a.emit(0x8B, 0x0D, u32(THE_LIVING_WORLD_CAMPAIGN_MANAGER))  # mov ecx, [manager]
    a.call_absolute(LIVING_WORLD_CAMPAIGN_MANAGER_GET_CAMPAIGN)  # ret 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "refresh_no_scenario")
    a.emit(0x8B, 0x40, LIVING_WORLD_CAMPAIGN_SCENARIO)  # mov eax, [eax+0x1c]
    a.emit(0x89, 0x45, i8(_SCENARIO))  # mov [ebp-0x3c], eax
    a.label("refresh_no_scenario")

    # A closed seat shows `-`, as the stock faction box does (0x00843DD3), and so does a Random
    # one: what a Random seat may draw is its Random pool's to say, not a row of this box.
    a.emit(0x83, 0x7D, i8(_SLOT_STATE), GAME_SLOT_STATE_CLOSED)  # cmp dword [ebp-0x34], 1
    a.jcc(JE, "refresh_dash")
    a.emit(0x83, 0x7D, i8(_WANT), i8(_OBSERVER))  # cmp dword [ebp-4], -2
    a.jcc(JE, "refresh_done")  # an observer plays no faction
    a.emit(0x83, 0x7D, i8(_WANT), 0x00)  # cmp dword [ebp-4], 0
    a.jcc(JGE, "refresh_faction")
    a.emit(0x83, 0x7D, i8(_WANT), i8(_LOWEST_TEMPLATE))  # cmp dword [ebp-4], -127
    a.jcc(JL, "refresh_dash")  # a Random pool
    a.emit(0x83, 0x7D, i8(_WANT), i8(RANDOM_OF))  # cmp dword [ebp-4], -16
    a.jcc(JLE, "refresh_faction")  # a faction with a random variant
    a.label("refresh_dash")  # Random, Standard, Variants, Good, Evil, a pool, or a closed seat
    a.emit(0xFF, 0x75, i8(_COLOR))  # push dword [ebp-0x1c]
    a.emit(0x6A, 0x00)  # push 0                       ; the text's slot
    a.emit(0x8B, 0xCC)  # mov ecx, esp
    a.emit(0x68, u32(WIDE_DASH))  # push L"-"
    a.call_absolute(UNICODE_STRING_FROM_WIDE)  # ret 4
    _emit_add_row(a, "refresh_dash", _WANT)
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
    a.emit(0x81, 0x7D, i8(_BASE), u32(RANDOM_OF_MAX_INDEX))  # cmp dword [ebp-8], 111
    a.jcc(JG, "refresh_standard_row")  # no template value left to say it with
    _emit_label_row(a, GUI_RANDOM_LABEL)
    _emit_add_row(a, "refresh_faction_random", _RANDOM)
    a.label("refresh_standard_row")
    _emit_standard_held(a, "std_faction_held")
    _emit_standard_row(a, lay, random=False, tag="std_faction", color_ebp=_ROW_COLOR)
    _emit_add_row(a, "refresh_standard", _BASE)
    _emit_disable_if_held(a, "refresh_standard")

    a.label("refresh_variant")
    a.emit(0x8B, 0x45, i8(_INDEX))  # mov eax, [ebp-0x18]
    a.call("blocked")  # not PvP, and the lobby has not enabled every variant: listed, greyed
    a.emit(0x89, 0x45, i8(_HELD))  # mov [ebp-0x38], eax
    a.emit(0x8B, 0x45, i8(_INDEX))  # mov eax, [ebp-0x18]
    a.emit(0x8B, 0x4D, i8(_SCENARIO))  # mov ecx, [ebp-0x3c]
    a.call("refused")  # the scenario bars this seat from it: the same
    a.emit(0x09, 0x45, i8(_HELD))  # or [ebp-0x38], eax
    _emit_held_color(a, "refresh_variant")
    a.emit(0xFF, 0x75, i8(_ROW_COLOR))  # push dword [ebp-0x40]       ; the row's colour
    a.emit(0x6A, 0x00)  # push 0                       ; the text's slot
    a.emit(0x54)  # push esp                     ; out = that slot (push esp pushes the old esp)
    a.emit(0x8B, 0x4D, i8(_TEMPLATE))  # mov ecx, [ebp-0x20]
    a.call_absolute(PLAYER_TEMPLATE_GET_DISPLAY_NAME)  # ret 4
    _emit_add_row(a, "refresh_row", _INDEX)
    _emit_disable_if_held(a, "refresh_row")

    a.label("refresh_next")
    a.emit(0xFF, 0x45, i8(_INDEX))  # inc dword [ebp-0x18]
    a.jmp("refresh_each")

    # A faction with no variant still gets its Standard row, alone: no Random to offer.
    a.label("refresh_faction_end")
    a.emit(0x83, 0x7D, i8(_ITEMS), 0x00)  # cmp dword [ebp-0xc], 0
    a.jcc(JNE, "refresh_done")
    _emit_standard_held(a, "std_alone_held")
    _emit_standard_row(a, lay, random=False, tag="std_alone", color_ebp=_ROW_COLOR)
    _emit_add_row(a, "refresh_standard_alone", _BASE)
    _emit_disable_if_held(a, "refresh_standard_alone")

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

    `0x00844177`, the faction box's handler, with the pick read from the Variant box instead and
    handed to `request`.

    It does **not** rebuild the box. This runs inside the box's own selection message, and
    resetting a combo box from its own notification pulls its rows out from under it - the game
    crashes. The stock handler leaves its box alone the same way; the screen's next update refills
    both, through the fill wrapper.
    """
    a.label("changed")
    a.emit(0x55)  # push ebp
    a.emit(0x8B, 0xEC)  # mov ebp, esp
    a.emit(0x51)  # push ecx                     ; [ebp-4]: the row
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
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8                  ; a Random row's data is negative
    a.call("request")
    a.label("changed_out")
    a.emit(0x8B, 0xE5)  # mov esp, ebp
    a.emit(0x5D)  # pop ebp
    a.emit(0xC3)  # ret


def _emit_request(a: Asm) -> None:
    """`request`: ask for `eax` as slot `edi`'s template, as the faction box's handler
    (`0x00844177`) does: the "request pending" byte cleared, the screen's strategy object asked -
    which sets it in skirmish and on a LAN host and sends a request from a LAN client - the War of
    the Ring flags set on success, and the slot redrawn. `esi` the screen; preserves `esi`, `edi`,
    `ebx` and `ebp`."""
    a.label("request")
    a.emit(0x53, 0x55)  # push ebx / push ebp
    a.emit(0x8B, 0xEC)  # mov ebp, esp
    a.emit(0x50)  # push eax                     ; [ebp-4]: the template
    a.emit(0xC6, 0x86, u32(MP_SETUP_FACTION_REQUEST_PENDING), 0x00)  # mov byte [esi+0x2c4], 0
    a.emit(0x8B, 0x4E, MP_SETUP_GAME_INFO)  # mov ecx, [esi+0x5c]
    a.call_absolute(MP_SETUP_GET_GAME_INFO)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "request_out")
    a.emit(0x57)  # push edi
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.call_absolute(GAME_INFO_GET_SLOT)  # ret 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "request_out")
    a.emit(0x8B, 0xD8)  # mov ebx, eax                 ; the GameSlot
    a.emit(0x8B, 0x45, 0xFC)  # mov eax, [ebp-4]
    a.emit(0x3B, 0x43, GAME_SLOT_PLAYER_TEMPLATE)  # cmp eax, [ebx+0x18]
    a.jcc(JE, "request_redraw")
    a.emit(0x8B, 0x4E, MP_SETUP_STRATEGY)  # mov ecx, [esi+0x58]
    a.emit(0x8B, 0x11)  # mov edx, [ecx]
    a.emit(0x50)  # push eax                     ; the template
    a.emit(0x53)  # push ebx                     ; the slot
    a.emit(0xFF, 0x52, MP_SETUP_STRATEGY_REQUEST_TEMPLATE_SLOT)  # call [edx+0x28]
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "request_out")  # refused
    a.emit(0x83, 0x7E, MP_SETUP_MODE, MP_SETUP_MODE_WOTR)  # cmp dword [esi+0x7c], 1
    a.jcc(JNE, "request_redraw")
    a.emit(0x8D, 0x4E, MP_SETUP_WOTR)  # lea ecx, [esi+0x60]
    a.call_absolute(MP_SETUP_WOTR_IS_HISTORICAL)
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "request_redraw")
    for flag in MP_SETUP_HISTORICAL_FLAGS:
        a.emit(0xC6, 0x86, u32(flag), 0x01)  # mov byte [esi+flag], 1
    a.label("request_redraw")
    a.emit(0x6A, 0x01)  # push 1
    a.emit(0x57)  # push edi
    a.emit(0x53)  # push ebx
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(MP_SETUP_REDRAW_SLOT)  # ret 0xc
    a.label("request_out")
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
    of that base a player could pick - the Variant box's own rule, `blocked` included. Preserves
    the rest."""
    a.label("offered")
    a.emit(0x51, 0x52)  # push ecx / push edx
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.call("parent_of")
    a.emit(0x3B, 0x04, 0x24)  # cmp eax, [esp]               ; the base
    a.jcc(JNE, "offered_no")
    a.emit(0x8B, 0xC1)  # mov eax, ecx
    a.call("blocked")
    a.emit(0x85, 0xC0)  # test eax, eax
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
    divide by. A slot on a `RANDOM_POOL` draws in `random_pool` instead. `ebx` is untouched; `esi`
    and `edi` are reloaded by the displaced instructions."""
    begin = GAME_START_RANDOM_CANDIDATES_EBP
    end = GAME_START_RANDOM_CANDIDATES_EBP + 4
    a.label("random_side")
    a.call("allow_from_game")
    a.emit(0x8B, 0x45, i8(GAME_START_RANDOM_SLOT_EBP))  # mov eax, [ebp-0x1c]    ; the slot
    a.emit(0x8B, 0x40, GAME_SLOT_PLAYER_TEMPLATE)  # mov eax, [eax+0x18]
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.call("pool_mask")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JNE, "pool_draw")
    a.emit(0x8B, 0xC1)  # mov eax, ecx
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


def _emit_pool_mask(a: Asm) -> None:
    """`pool_mask`: `eax` = a slot's template, `eax` = the template indices its `RANDOM_POOL`
    names, as a mask, or 0 for any other template. Preserves the rest."""
    a.label("pool_mask")
    a.emit(0x52)  # push edx
    a.emit(0x8B, 0xD0)  # mov edx, eax
    a.emit(0x81, 0xE2, u32(_POOL_TAG_BITS))  # and edx, 0xff000000
    a.emit(0x81, 0xFA, u32(RANDOM_POOL & 0xFFFFFFFF))  # cmp edx, 0x80000000
    a.jcc(JNE, "pool_mask_none")
    a.emit(0x25, u32(_POOL_MASK_BITS))  # and eax, 0xffffff
    a.jmp("pool_mask_out")
    a.label("pool_mask_none")
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.label("pool_mask_out")
    a.emit(0x5A)  # pop edx
    a.emit(0xC3)  # ret


def _emit_pool_drawable(a: Asm) -> None:
    """`pool_drawable`: `eax` = a template index, `eax` = 1 when a pool may draw it - a playable
    template, not an observer, not `blocked`, whose faction (itself, or its base for a variant) is
    among the slot's candidates. Those are `startNewGame`'s per-slot copy of the Random pool,
    already filtered by the slot's start position, so it is only called from inside that frame.
    Preserves the rest."""
    begin = GAME_START_RANDOM_CANDIDATES_EBP
    end = GAME_START_RANDOM_CANDIDATES_EBP + 4
    a.label("pool_drawable")
    a.emit(0x51, 0x52, 0x56)  # push ecx / edx / esi
    a.emit(0x8B, 0xF0)  # mov esi, eax                 ; the index asked about
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JL, "pool_drawable_no")
    a.emit(0x8B, 0x0D, u32(THE_PLAYER_TEMPLATE_STORE))  # mov ecx, [ThePlayerTemplateStore]
    a.emit(0x8B, 0x41, PLAYER_TEMPLATE_STORE_END)  # mov eax, [ecx+0x10]
    a.emit(0x2B, 0x41, PLAYER_TEMPLATE_STORE_BEGIN)  # sub eax, [ecx+0xc]
    a.emit(0x99)  # cdq
    a.emit(0xB9, u32(PLAYER_TEMPLATE_SIZE))  # mov ecx, 0x1dc
    a.emit(0xF7, 0xF9)  # idiv ecx
    a.emit(0x3B, 0xF0)  # cmp esi, eax
    a.jcc(JGE, "pool_drawable_no")  # past the store
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0x0D, u32(THE_PLAYER_TEMPLATE_STORE))  # mov ecx, [ThePlayerTemplateStore]
    a.call_absolute(PLAYER_TEMPLATE_FIND_BY_INDEX)  # ret 4 - the final override
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "pool_drawable_no")
    a.emit(0x80, 0xB8, u32(PLAYER_TEMPLATE_PLAYABLE_SIDE), 0x00)  # cmp byte [eax+0x151], 0
    a.jcc(JE, "pool_drawable_no")
    a.emit(0x80, 0xB8, u32(PLAYER_TEMPLATE_IS_OBSERVER), 0x00)  # cmp byte [eax+0x150], 0
    a.jcc(JNE, "pool_drawable_no")
    a.emit(0x8B, 0xC6)  # mov eax, esi
    a.call("blocked")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JNE, "pool_drawable_no")
    a.emit(0x8B, 0xC6)  # mov eax, esi
    a.call("base_of")
    a.emit(0x8B, 0x4D, i8(begin))  # mov ecx, [ebp-0x28]
    a.emit(0x8B, 0x55, i8(end))  # mov edx, [ebp-0x24]
    a.label("pool_drawable_scan")
    a.emit(0x3B, 0xCA)  # cmp ecx, edx
    a.jcc(JAE, "pool_drawable_no")  # its faction is not a candidate
    a.emit(0x39, 0x01)  # cmp [ecx], eax
    a.jcc(JE, "pool_drawable_yes")
    a.emit(0x83, 0xC1, 0x04)  # add ecx, 4
    a.jmp("pool_drawable_scan")
    a.label("pool_drawable_yes")
    a.emit(0xB8, u32(1))  # mov eax, 1
    a.jmp("pool_drawable_out")
    a.label("pool_drawable_no")
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.label("pool_drawable_out")
    a.emit(0x5E, 0x5A, 0x59)  # pop esi / edx / ecx
    a.emit(0xC3)  # ret


def _emit_pool_draw(a: Asm) -> None:
    """`random_side`'s branch for a slot on a `RANDOM_POOL`, with its mask in `eax`: one of the
    templates it names that `pool_drawable` allows, each equally likely, drawn with
    `GameLogicRandomValue` as every other Random draw is. The pick becomes the candidates' only
    element - written over the first, which exists because the pick's faction is among them - so
    the stock draw that follows can only take it. A pool that allows nothing leaves the candidates
    as they are, and the slot draws as Standard does."""
    begin = GAME_START_RANDOM_CANDIDATES_EBP
    end = GAME_START_RANDOM_CANDIDATES_EBP + 4
    a.label("pool_draw")
    a.emit(0x53)  # push ebx
    a.emit(0x8B, 0xD8)  # mov ebx, eax                 ; the mask
    a.emit(0x31, 0xFF)  # xor edi, edi                 ; templates it allows
    a.emit(0x31, 0xC9)  # xor ecx, ecx
    a.label("pool_draw_count")
    a.emit(0x83, 0xF9, RANDOM_POOL_BITS)  # cmp ecx, 24
    a.jcc(JGE, "pool_draw_counted")
    a.emit(0x0F, 0xA3, 0xCB)  # bt ebx, ecx
    a.jcc(JAE, "pool_draw_count_next")  # not named
    a.emit(0x8B, 0xC1)  # mov eax, ecx
    a.call("pool_drawable")
    a.emit(0x03, 0xF8)  # add edi, eax
    a.label("pool_draw_count_next")
    a.emit(0x41)  # inc ecx
    a.jmp("pool_draw_count")
    a.label("pool_draw_counted")
    a.emit(0x85, 0xFF)  # test edi, edi
    a.jcc(JE, "pool_draw_out")  # nothing allowed: draw as Standard
    a.emit(0x4F)  # dec edi
    a.emit(0x6A, 0x00)  # push 0                       ; line
    a.emit(0x68, u32(GAME_LOGIC_SOURCE_FILE))  # push <GameLogic.cpp>
    a.emit(0x57)  # push edi                     ; hi: the last allowed
    a.emit(0x6A, 0x00)  # push 0                       ; lo: the first
    a.call_absolute(GAME_LOGIC_RANDOM_VALUE)
    a.emit(0x83, 0xC4, 0x10)  # add esp, 0x10
    a.emit(0x8B, 0xF8)  # mov edi, eax                 ; the n-th allowed, from 0
    a.emit(0x31, 0xC9)  # xor ecx, ecx
    a.label("pool_draw_find")
    a.emit(0x83, 0xF9, RANDOM_POOL_BITS)  # cmp ecx, 24
    a.jcc(JGE, "pool_draw_out")
    a.emit(0x0F, 0xA3, 0xCB)  # bt ebx, ecx
    a.jcc(JAE, "pool_draw_find_next")
    a.emit(0x8B, 0xC1)  # mov eax, ecx
    a.call("pool_drawable")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "pool_draw_find_next")
    a.emit(0x85, 0xFF)  # test edi, edi
    a.jcc(JE, "pool_draw_hit")
    a.emit(0x4F)  # dec edi
    a.label("pool_draw_find_next")
    a.emit(0x41)  # inc ecx
    a.jmp("pool_draw_find")
    a.label("pool_draw_hit")
    a.emit(0x8B, 0x45, i8(begin))  # mov eax, [ebp-0x28]
    a.emit(0x89, 0x08)  # mov [eax], ecx
    a.emit(0x83, 0xC0, 0x04)  # add eax, 4
    a.emit(0x89, 0x45, i8(end))  # mov [ebp-0x24], eax          ; the pick alone
    a.label("pool_draw_out")
    a.emit(0x5B)  # pop ebx
    a.jmp("random_side_out")


def emit_command_block(a: Asm, name_va: int, handler_va: int) -> None:
    """One command block of `MpGameSetup`'s constructor, as the stock ones are written: file
    `handler_va` in the screen's command map under the C string at `name_va`. Runs in the
    constructor's frame (`ebx` the screen, `[ebp-0x10]` .. `[ebp-0x38]` the block's locals,
    `[ebp-4]` the unwind state) and clobbers `esi`, `edi`, `eax`, `ecx`, `edx`, which the next stock
    block reloads. Assembled at `MP_SETUP_COMMAND_BLOCK` with that block's own name and handler, it
    is byte for byte the block the screen already runs."""
    a.emit(0x68, u32(name_va))  # push <name>
    a.emit(0x8D, 0x4D, 0xF0)  # lea ecx, [ebp-0x10]
    a.emit(0xBE, u32(handler_va))  # mov esi, <handler>
    a.emit(0x33, 0xFF)  # xor edi, edi
    a.call_absolute(ASCII_STRING_CTOR)
    a.emit(0x89, 0x75, 0xE0)  # mov [ebp-0x20], esi          ; the functor: handler,
    a.emit(0x89, 0x7D, 0xE4)  # mov [ebp-0x1c], edi          ; 0,
    a.emit(0x89, 0x5D, 0xD8)  # mov [ebp-0x28], ebx          ; and the screen
    a.emit(0x8D, 0x75, 0xD8)  # lea esi, [ebp-0x28]
    a.emit(0x8D, 0x7D, 0xC8)  # lea edi, [ebp-0x38]
    a.emit(0xA5, 0xA5)  # movsd / movsd
    a.emit(0x51)  # push ecx                     ; room for the copy on the stack
    a.emit(0xA5)  # movsd
    a.emit(0x8D, 0x45, 0xC8)  # lea eax, [ebp-0x38]
    a.emit(0x89, 0x65, 0xE8)  # mov [ebp-0x18], esp
    a.emit(0x8B, 0xCC)  # mov ecx, esp
    a.emit(0x50)  # push eax
    a.emit(0xC7, 0x45, 0xFC, u32(1))  # mov dword [ebp-4], 1      ; the string is live
    a.emit(0xA5)  # movsd
    a.call_absolute(MP_SETUP_COMMAND_FUNCTOR_CTOR)
    a.emit(0x8D, 0x45, 0xF0)  # lea eax, [ebp-0x10]
    a.emit(0x50)  # push eax
    a.emit(0x8D, 0x4B, MP_SETUP_COMMAND_MAP)  # lea ecx, [ebx+4]
    a.call_absolute(MP_SETUP_COMMAND_MAP_INSERT)
    a.emit(0x83, 0x4D, 0xFC, 0xFF)  # or dword [ebp-4], -1
    a.emit(0x8D, 0x4D, 0xF0)  # lea ecx, [ebp-0x10]
    a.call_absolute(ASCII_STRING_DTOR)


def emit_extern_block(a: Asm, name_va: int, handler_va: int, index: int) -> None:
    """One extern block of `MpGameSetup`'s constructor, as the stock `MpGameSetup::HostMode` one is
    written: the command block's string and functor, then `index` and the screen's extern map in
    place of its command map. Same frame and clobbers as `emit_command_block`."""
    a.emit(0x68, u32(name_va))  # push <name>
    a.emit(0x8D, 0x4D, 0xF0)  # lea ecx, [ebp-0x10]
    a.emit(0xBE, u32(handler_va))  # mov esi, <handler>
    a.emit(0x33, 0xFF)  # xor edi, edi
    a.call_absolute(ASCII_STRING_CTOR)
    a.emit(0x89, 0x75, 0xE0)  # mov [ebp-0x20], esi
    a.emit(0x89, 0x7D, 0xE4)  # mov [ebp-0x1c], edi
    a.emit(0x89, 0x5D, 0xD8)  # mov [ebp-0x28], ebx
    a.emit(0x8D, 0x75, 0xD8)  # lea esi, [ebp-0x28]
    a.emit(0x8D, 0x7D, 0xC8)  # lea edi, [ebp-0x38]
    a.emit(0xA5, 0xA5)  # movsd / movsd
    a.emit(0x51)  # push ecx                     ; room for the functor
    a.emit(0xA5)  # movsd
    a.emit(0x8D, 0x45, 0xC8)  # lea eax, [ebp-0x38]
    a.emit(0x89, 0x65, 0xE8)  # mov [ebp-0x18], esp
    a.emit(0x8B, 0xCC)  # mov ecx, esp
    a.emit(0x50)  # push eax
    a.emit(0xC7, 0x45, 0xFC, u32(1))  # mov dword [ebp-4], 1
    a.emit(0xA5)  # movsd
    a.call_absolute(MP_SETUP_COMMAND_FUNCTOR_CTOR)
    a.emit(0x6A, index)  # push <index>
    a.emit(0x8D, 0x45, 0xF0)  # lea eax, [ebp-0x10]
    a.emit(0x8D, 0x4B, MP_SETUP_EXTERN_MAP)  # lea ecx, [ebx+0x10]
    a.emit(0x50)  # push eax
    a.call_absolute(MP_SETUP_EXTERN_MAP_INSERT)  # ret 0xc
    a.emit(0x83, 0x4D, 0xFC, 0xFF)  # or dword [ebp-4], -1
    a.emit(0x8D, 0x4D, 0xF0)  # lea ecx, [ebp-0x10]
    a.call_absolute(ASCII_STRING_DTOR)


def _emit_get_pool(a: Asm) -> None:
    """`POOL_EXTERN`'s handler, `thiscall (int slot, char *out, bool flag)`, `ret 0xc`: the slot's
    pool mask in decimal, or "0" when the slot is not a pool (or there is no such slot)."""
    a.label("get_pool")
    a.emit(0x53, 0x56, 0x57)  # push ebx / esi / edi
    a.emit(0x8B, 0xF1)  # mov esi, ecx                 ; the screen
    a.emit(0x80, 0x7C, 0x24, 0x18, 0x00)  # cmp byte [esp+0x18], 0  ; flag
    a.jcc(JNE, "get_pool_out")
    a.emit(0x8B, 0x7C, 0x24, 0x14)  # mov edi, [esp+0x14]       ; out
    a.emit(0x85, 0xFF)  # test edi, edi
    a.jcc(JE, "get_pool_out")
    a.emit(0x66, 0xC7, 0x07, 0x30, 0x00)  # mov word [edi], "0"
    a.emit(0x8B, 0x4E, MP_SETUP_GAME_INFO)  # mov ecx, [esi+0x5c]
    a.call_absolute(MP_SETUP_GET_GAME_INFO)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "get_pool_out")
    a.emit(0xFF, 0x74, 0x24, 0x10)  # push dword [esp+0x10]      ; slot
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.call_absolute(GAME_INFO_GET_SLOT)  # ret 4
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "get_pool_out")
    a.emit(0x8B, 0x40, GAME_SLOT_PLAYER_TEMPLATE)  # mov eax, [eax+0x18]
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.emit(0x81, 0xE1, u32(_POOL_TAG_BITS))  # and ecx, 0xff000000
    a.emit(0x81, 0xF9, u32(RANDOM_POOL & 0xFFFFFFFF))  # cmp ecx, 0x80000000
    a.jcc(JNE, "get_pool_out")
    a.emit(0x25, u32(_POOL_MASK_BITS))  # and eax, 0x00ffffff
    a.emit(0xB9, u32(10))  # mov ecx, 10
    a.emit(0x31, 0xDB)  # xor ebx, ebx                 ; digits
    a.label("get_pool_divide")
    a.emit(0x31, 0xD2)  # xor edx, edx
    a.emit(0xF7, 0xF1)  # div ecx
    a.emit(0x52)  # push edx                     ; lowest digit first
    a.emit(0x43)  # inc ebx
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JNE, "get_pool_divide")
    a.label("get_pool_write")
    a.emit(0x58)  # pop eax                      ; highest digit first
    a.emit(0x04, 0x30)  # add al, "0"
    a.emit(0x88, 0x07)  # mov [edi], al
    a.emit(0x47)  # inc edi
    a.emit(0x4B)  # dec ebx
    a.jcc(JNE, "get_pool_write")
    a.emit(0xC6, 0x07, 0x00)  # mov byte [edi], 0
    a.label("get_pool_out")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi / esi / ebx
    a.emit(0xC2, 0x0C, 0x00)  # ret 0xc


def _emit_get_seat(a: Asm) -> None:
    """`SEAT_EXTERN`'s handler, `thiscall (int slot, char *out, bool flag)`, `ret 0xc`: `"2"` for
    a seat whose faction box is shown and enabled, `"1"` for one shown but disabled, `"0"` for one
    hidden, missing, or past slot 7 - the same test `set_random_pool` refuses a seat by."""
    a.label("get_seat")
    a.emit(0x80, 0x7C, 0x24, 0x0C, 0x00)  # cmp byte [esp+0xc], 0   ; flag
    a.jcc(JNE, "get_seat_out")
    a.emit(0x8B, 0x54, 0x24, 0x08)  # mov edx, [esp+8]           ; out
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JE, "get_seat_out")
    a.emit(0x66, 0xC7, 0x02, 0x30, 0x00)  # mov word [edx], "0"
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov eax, [esp+4]           ; slot
    a.emit(0x83, 0xF8, SLOTS)  # cmp eax, 8
    a.jcc(JAE, "get_seat_out")
    a.emit(0x8B, 0x84, 0x81, u32(MP_SETUP_FACTION_WINDOWS))  # mov eax, [ecx+eax*4+0x334]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "get_seat_out")
    a.emit(0x8B, 0x40, WINDOW_STATUS)  # mov eax, [eax+8]
    a.emit(0xA8, WINDOW_STATUS_HIDDEN)  # test al, 0x10
    a.jcc(JNE, "get_seat_out")
    a.emit(0xFE, 0x02)  # inc byte [edx]               ; "1": shown
    a.emit(0xA8, WINDOW_STATUS_ENABLED)  # test al, 8
    a.jcc(JE, "get_seat_out")
    a.emit(0xFE, 0x02)  # inc byte [edx]               ; "2": shown and enabled
    a.label("get_seat_out")
    a.emit(0xC2, 0x0C, 0x00)  # ret 0xc


def _emit_register_pool(a: Asm, lay: _Layout) -> None:
    """At the start of a stock command block in `MpGameSetup`'s constructor: file `POOL_COMMAND`
    first, then run the displaced `push <name>` and carry on into the stock block."""
    a.label("register_pool")
    a.emit(0x83, 0x25, u32(lay.modal), 0x00)  # and dword [modal], 0     ; a new screen
    emit_command_block(a, lay.pool_command, a.label_va("set_random_pool"))
    emit_command_block(a, lay.pool_modal_command, a.label_va("set_pool_modal"))
    for slot, name in enumerate(lay.pool_externs):
        emit_extern_block(a, name, a.label_va("get_pool"), slot)
    for slot, name in enumerate(lay.seat_externs):
        emit_extern_block(a, name, a.label_va("get_seat"), slot)
    emit_extern_block(a, lay.escape_extern, a.label_va("get_escape"), 0)
    a.emit(MP_SETUP_COMMAND_BLOCK_BYTES[:5])  # push <the stock block's name>
    a.jmp_absolute(MP_SETUP_COMMAND_BLOCK_RESUME)


def _emit_set_random_pool(a: Asm) -> None:
    """`POOL_COMMAND`'s handler, `thiscall (const char *params)`, `ret 4`: `params` is
    `"<slot>:<mask>"` in decimal. Asks for slot `<slot>`'s template to be `RANDOM_POOL | mask`, or
    `RANDOM_STANDARD` for a mask of 0, through `request` - so skirmish, a LAN host and a LAN client
    each do what a faction pick does. A seat whose faction box is disabled or hidden is one the
    player may not change, and is left alone; so is anything malformed, a slot past 7 or a mask
    past `RANDOM_POOL_BITS`."""
    a.label("set_random_pool")
    a.emit(0x53, 0x56, 0x57)  # push ebx / esi / edi
    a.emit(0x8B, 0xF1)  # mov esi, ecx                 ; the screen
    a.emit(0x8B, 0x4C, 0x24, 0x10)  # mov ecx, [esp+0x10]       ; params
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "set_random_pool_out")
    a.emit(0x31, 0xFF)  # xor edi, edi                 ; the slot
    a.emit(0x0F, 0xB6, 0x01)  # movzx eax, byte [ecx]
    a.emit(0x83, 0xE8, 0x30)  # sub eax, 0x30
    a.emit(0x83, 0xF8, 0x09)  # cmp eax, 9
    a.jcc(JA, "set_random_pool_out")  # no slot digit
    a.label("set_random_pool_slot")
    a.emit(0x0F, 0xB6, 0x01)  # movzx eax, byte [ecx]
    a.emit(0x83, 0xF8, 0x3A)  # cmp eax, 0x3a                ; the colon
    a.jcc(JE, "set_random_pool_mask")
    a.emit(0x83, 0xE8, 0x30)  # sub eax, 0x30
    a.emit(0x83, 0xF8, 0x09)  # cmp eax, 9
    a.jcc(JA, "set_random_pool_out")
    a.emit(0x6B, 0xFF, 0x0A)  # imul edi, edi, 10
    a.emit(0x03, 0xF8)  # add edi, eax
    a.emit(0x83, 0xFF, SLOTS)  # cmp edi, 8
    a.jcc(JAE, "set_random_pool_out")
    a.emit(0x41)  # inc ecx
    a.jmp("set_random_pool_slot")
    a.label("set_random_pool_mask")
    a.emit(0x41)  # inc ecx                      ; past the colon
    a.emit(0x31, 0xDB)  # xor ebx, ebx                 ; the mask
    a.label("set_random_pool_digit")
    a.emit(0x0F, 0xB6, 0x01)  # movzx eax, byte [ecx]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "set_random_pool_parsed")
    a.emit(0x83, 0xE8, 0x30)  # sub eax, 0x30
    a.emit(0x83, 0xF8, 0x09)  # cmp eax, 9
    a.jcc(JA, "set_random_pool_out")
    a.emit(0x6B, 0xDB, 0x0A)  # imul ebx, ebx, 10
    a.emit(0x03, 0xD8)  # add ebx, eax
    a.emit(0x81, 0xFB, u32(_POOL_MASK_BITS + 1))  # cmp ebx, 0x1000000
    a.jcc(JAE, "set_random_pool_out")  # names an index a pool cannot
    a.emit(0x41)  # inc ecx
    a.jmp("set_random_pool_digit")
    a.label("set_random_pool_parsed")
    a.emit(0x83, 0xC8, 0xFF)  # or eax, -1                   ; every faction: plain Random
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JE, "set_random_pool_seat")
    a.emit(0x8B, 0xC3)  # mov eax, ebx
    a.emit(0x0D, u32(RANDOM_POOL & 0xFFFFFFFF))  # or eax, 0x80000000
    a.label("set_random_pool_seat")
    a.emit(0x8B, 0x94, 0xBE, u32(MP_SETUP_FACTION_WINDOWS))  # mov edx, [esi+edi*4+0x334]
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JE, "set_random_pool_out")
    a.emit(0x8B, 0x52, WINDOW_STATUS)  # mov edx, [edx+8]
    a.emit(0xF6, 0xC2, WINDOW_STATUS_ENABLED)  # test dl, 8
    a.jcc(JE, "set_random_pool_out")  # a seat the player may not change
    a.emit(0xF6, 0xC2, WINDOW_STATUS_HIDDEN)  # test dl, 0x10
    a.jcc(JNE, "set_random_pool_out")
    a.call("request")
    a.label("set_random_pool_out")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi / esi / ebx
    a.emit(0xC2, 0x04, 0x00)  # ret 4


def _emit_set_pool_modal(a: Asm, lay: _Layout) -> None:
    """`POOL_MODAL_COMMAND`'s handler, `thiscall (const char *params)`, `ret 4`: `"1"` records the
    screen as having the panel open, anything else clears it. Either way an Escape recorded before
    is forgotten."""
    a.label("set_pool_modal")
    a.emit(0x83, 0x25, u32(lay.escape), 0x00)  # and dword [escape], 0
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov eax, [esp+4]          ; params
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "set_pool_modal_off")
    a.emit(0x80, 0x38, 0x31)  # cmp byte [eax], '1'
    a.jcc(JNE, "set_pool_modal_off")
    a.emit(0x89, 0x0D, u32(lay.modal))  # mov [modal], ecx           ; the screen
    a.emit(0xC2, 0x04, 0x00)  # ret 4
    a.label("set_pool_modal_off")
    a.emit(0x83, 0x25, u32(lay.modal), 0x00)  # and dword [modal], 0
    a.emit(0xC2, 0x04, 0x00)  # ret 4


def _emit_get_escape(a: Asm, lay: _Layout) -> None:
    """`ESCAPE_EXTERN`'s handler, `thiscall (int index, char *out, bool flag)`, `ret 0xc`: `"1"`
    once Escape was let go of while the panel was open, `"0"` otherwise. Reading leaves it set:
    the panel closes, and its `POOL_MODAL_COMMAND` clears it."""
    a.label("get_escape")
    a.emit(0x80, 0x7C, 0x24, 0x0C, 0x00)  # cmp byte [esp+0xc], 0   ; flag
    a.jcc(JNE, "get_escape_out")
    a.emit(0x8B, 0x54, 0x24, 0x08)  # mov edx, [esp+8]           ; out
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JE, "get_escape_out")
    a.emit(0x66, 0xC7, 0x02, 0x30, 0x00)  # mov word [edx], "0"
    a.emit(0x83, 0x3D, u32(lay.escape), 0x00)  # cmp dword [escape], 0
    a.jcc(JE, "get_escape_out")
    a.emit(0xFE, 0x02)  # inc byte [edx]               ; "1"
    a.label("get_escape_out")
    a.emit(0xC2, 0x0C, 0x00)  # ret 0xc


def _emit_key_gate(a: Asm, lay: _Layout) -> None:
    """At `winProcessKey`'s entry: while the game-setup screen that is up has the panel open,
    Escape goes to no window - it is reported used, and its release recorded for the panel
    (`ESCAPE_EXTERN`). Every other key, and every key while the panel is shut, takes the stock
    path."""
    a.label("key_gate")
    a.emit(0xA1, u32(lay.modal))  # mov eax, [modal]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "key_gate_stock")
    a.emit(0x3B, 0x05, u32(MP_SETUP_CURRENT))  # cmp eax, [TheMpGameSetup]
    a.jcc(JNE, "key_gate_stock")
    a.emit(0x80, 0x7C, 0x24, 0x04, KEY_ESC)  # cmp byte [esp+4], KEY_ESC   ; key
    a.jcc(JNE, "key_gate_stock")
    a.emit(0xF6, 0x44, 0x24, 0x08, KEY_STATE_UP)  # test byte [esp+8], KEY_STATE_UP ; state
    a.jcc(JE, "key_gate_used")
    a.emit(0xC7, 0x05, u32(lay.escape), u32(1))  # mov dword [escape], 1
    a.label("key_gate_used")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.emit(0x40)  # inc eax                      ; used
    a.emit(0xC2, 0x08, 0x00)  # ret 8
    a.label("key_gate_stock")
    a.emit(WINDOW_MANAGER_PROCESS_KEY_BYTES)  # push ebp / mov ebp, esp / push ecx / push ecx
    a.jmp_absolute(WINDOW_MANAGER_PROCESS_KEY_RESUME)


def _emit_mouse_gate(a: Asm, lay: _Layout) -> None:
    """At `winProcessMouseEvent`'s entry: while the game-setup screen that is up has the panel
    open, no window takes the mouse - the event is reported unused, and goes on to the screen's
    APT. A screen that has gone has cleared `MP_SETUP_CURRENT`, so it cannot hold the gate shut
    for the next screen."""
    a.label("mouse_gate")
    a.emit(0xA1, u32(lay.modal))  # mov eax, [modal]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "mouse_gate_stock")
    a.emit(0x3B, 0x05, u32(MP_SETUP_CURRENT))  # cmp eax, [TheMpGameSetup]
    a.jcc(JNE, "mouse_gate_stock")
    a.emit(0x31, 0xC0)  # xor eax, eax                 ; not used
    a.emit(0xC2, 0x0C, 0x00)  # ret 0xc
    a.label("mouse_gate_stock")
    a.emit(WINDOW_MANAGER_PROCESS_MOUSE_BYTES)  # push ebp / mov ebp, esp / sub esp, 0x28
    a.jmp_absolute(WINDOW_MANAGER_PROCESS_MOUSE_RESUME)


def _emit_request_check(a: Asm) -> None:
    """The LAN host's check on a client's `PlayerTemplate` request, `edi` the template: what it
    accepted (`_LOWEST_TEMPLATE` and up), plus a `RANDOM_POOL` naming something."""
    _site, _window, resume, refuse = GAME_SLOT_REQUEST_TEMPLATE_CHECK
    a.label("request_check")
    a.emit(0x83, 0xFF, i8(_LOWEST_TEMPLATE))  # cmp edi, -127
    a.jcc(JGE, "request_check_ok")
    a.emit(0x8B, 0xC7)  # mov eax, edi
    a.call("pool_mask")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JNE, "request_check_ok")
    a.jmp_absolute(refuse)
    a.label("request_check_ok")
    a.jmp_absolute(resume)


def _parse_label(site: int) -> str:
    return f"parse_template_{site:08x}"


def _emit_parse_template(a: Asm, label: str, window: bytes, resume: int, reject: int) -> None:
    """The lobby string parser's template check, taken over at one slot arm: what it accepted
    (`_LOWEST_TEMPLATE` and up), plus a `RANDOM_POOL` naming something. `eax` is what `atoi` read;
    the arm reloads it from `[ebp-0x28]`, so the check may clobber it."""
    a.label(label)
    a.emit(window[3:7])  # pop ecx / mov [ebp-0x28], eax
    a.emit(0x83, 0xF8, i8(_LOWEST_TEMPLATE))  # cmp eax, -127
    a.jcc(JGE, f"{label}_ok")
    a.call("pool_mask")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JNE, f"{label}_ok")
    a.jmp_absolute(reject)
    a.label(f"{label}_ok")
    a.jmp_absolute(resume)


def _emit_slot_template(a: Asm) -> None:
    """Where `startNewGame` reads each occupied slot's template (`ebx` the slot) into `esi` for
    the Random pass: a `RANDOM_OF` is settled here, to its faction or a variant of it, a
    `RANDOM_VARIANTS` to one of every faction's variants, and a `blocked` variant to its faction;
    each is set on the slot, so the Random pass sees a real template and leaves it alone."""
    a.label("slot_template")
    a.call("allow_from_game")
    a.emit(GAME_START_SLOT_TEMPLATE_BYTES[:3])  # mov esi, [ebx+0x18]
    a.emit(0x83, 0xFE, i8(RANDOM_VARIANTS))  # cmp esi, -4
    a.jcc(JNE, "slot_template_of")
    a.call("roll_variants")  # -1 with none: the Random pass draws a faction instead
    a.jmp("slot_template_set")
    a.label("slot_template_of")
    a.emit(0x83, 0xFE, i8(RANDOM_OF))  # cmp esi, -16
    a.jcc(JG, "slot_template_picked")
    a.emit(0x81, 0xFE, u32(_LOWEST_TEMPLATE & 0xFFFFFFFF))  # cmp esi, -127
    a.jcc(JL, "slot_template_out")  # nothing this patch wrote
    a.emit(0xB8, u32(RANDOM_OF & 0xFFFFFFFF))  # mov eax, -16
    a.emit(0x2B, 0xC6)  # sub eax, esi                 ; the faction
    a.call("roll")
    a.jmp("slot_template_set")
    a.label("slot_template_picked")  # a template, or a sentinel `blocked` answers 0 for
    a.emit(0x8B, 0xC6)  # mov eax, esi
    a.call("blocked")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "slot_template_out")
    a.emit(0x8B, 0xC6)  # mov eax, esi
    a.call("base_of")
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
    a.call("allow_from_game")
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
    _emit_parse_pvp(a, lay)
    _emit_commit(a, lay)
    _emit_parse_hooks(a)
    _emit_lookup(a, lay)
    _emit_parent_of(a)
    _emit_base_of(a)
    _emit_blocked(a, lay)
    _emit_refused(a)
    emit_is_faction_enabled(a, "scenario_enabled")
    _emit_allow_from_game(a, lay)
    _emit_family(a)
    _emit_faction_list(a)
    _emit_random_pool(a)
    _emit_sync_template(a)
    _emit_wrap(a, "fill", MP_SETUP_FACTION_COMBO, keep_pick=True)
    _emit_wrap(a, "sync", MP_SETUP_SYNC_FACTION, keep_pick=False)
    _emit_state(a, lay)
    _emit_refresh(a, lay)
    _emit_changed(a, lay)
    _emit_request(a)
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
    _emit_pool_mask(a)
    _emit_pool_drawable(a)
    _emit_pool_draw(a)
    for site, window, resume, reject in GAME_INFO_PARSE_TEMPLATE_CHECKS:
        _emit_parse_template(a, _parse_label(site), window, resume, reject)
    _emit_request_check(a)
    _emit_set_random_pool(a)
    _emit_set_pool_modal(a, lay)
    _emit_get_pool(a)
    _emit_get_seat(a)
    _emit_get_escape(a, lay)
    _emit_mouse_gate(a, lay)
    _emit_key_gate(a, lay)
    _emit_register_pool(a, lay)
    a.finish()
    return a


def _code_offset(entries: tuple[Entry, ...]) -> int:
    return _TABLE_OFF + _table_span(entries)


def build_section(base_va: int, entries: tuple[Entry, ...] = ()) -> bytes:
    """The whole `.facvar` section for a base: zeroed state, the strings, the rebuilt field
    table (`entries`, then `VariantOf` and `EnabledForPvP`), then the code."""
    lay = _Layout(base_va)
    code = _assemble(base_va + _code_offset(entries), lay)
    body = bytearray(_STRINGS_OFF)
    body += _strings()
    body += _table_bytes(
        base_va + _TABLE_OFF, entries, code.label_va("parse"), code.label_va("parse_pvp")
    )
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
        "own Variant box leads with Random (that faction, a random variant of it). A slot's "
        "template may also be a Random pool, -0x80000000 plus one bit per template index, drawn "
        "only among the templates it names (variants included, each equally likely); the movie "
        'sets one with GameCode("SetRandomPool", "<slot>:<mask>"), a new MpGameSetup command '
        "that refuses seats the player may not change. The lobby string, Skirmish.ini and replays "
        "carry a pool, and the LAN lobby does with lobby-faction-byte. Choosing any Random no "
        "longer clears the seat's start position. A variant may say EnabledForPvP = No: it is "
        "then offered, drawn and played only while rule 1 (the online-only ClanGame rule, clear "
        "by default) is set; a seat left on it plays its base faction. --all-variants-box shows "
        "that checkbox on every setup screen as RULE:EnableAllVariants so the host can set it; "
        "without it no skirmish or LAN match fields such a variant. In the War of the Ring "
        "lobby the Variant box honours the scenario's DisabledFactions, Faction<X>:N entries "
        "included: a row the scenario refuses that seat is listed greyed and cannot be picked. "
        "The movie must "
        "place a ~<slot>."
        "Variant combo box in each MpGameSetup.apt row, or variants cannot be picked at all"
    )

    def __init__(self, all_variants_box: bool = False) -> None:
        self.all_variants_box = all_variants_box

    def __str__(self) -> str:
        return f"{self.name} (all-variants box)" if self.all_variants_box else self.name

    def options(self) -> dict[str, object]:
        """`all_variants_box` only when set, so a manifest written before the option existed still
        matches a build without it."""
        return {"all_variants_box": True} if self.all_variants_box else {}

    @classmethod
    def detect(cls, data: bytes | bytearray) -> FactionVariantsPatch | None:
        """The patch as `data` carries it, with or without the all-variants box: whichever
        instance `verify` finds nothing wrong with, the box first: a binary with it also carries
        every edit of the one without."""
        for box in (True, False):
            patch = cls(all_variants_box=box)
            try:
                problems = patch.verify(data)
            except (ValueError, KeyError, IndexError, TypeError, struct.error):
                return None
            if not problems:
                return patch
        return None

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--all-variants-box",
            action="store_true",
            help=(
                f"show the online-only ClanGame checkbox on every setup screen as "
                f"{ALL_VARIANTS_LABEL}, so the host can field EnabledForPvP = No variants"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> FactionVariantsPatch:
        return cls(all_variants_box=args.all_variants_box)

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
        for name in _FIELD_NAMES:
            if name in by_name:
                raise ValueError(
                    f"the PlayerTemplate table already names {name} - this patch is already "
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
        # below at -2. The lobby string parser takes a RANDOM_POOL too, which no immediate can
        # say; the LAN readers and the host's request handler keep refusing one, since the LAN
        # packet carries a template as a byte ...
        hooked = set()
        for site, window, _resume, _reject in GAME_INFO_PARSE_TEMPLATE_CHECKS:
            hooked.add(site)
            jump(site, window, _parse_label(site), "lobby string template check -> Random pools")
        request_site, request_window, _resume, _refuse = GAME_SLOT_REQUEST_TEMPLATE_CHECK
        hooked.add(request_site)
        jump(request_site, request_window, "request_check", "LAN request check -> Random pools")
        # The LAN packet readers keep a byte bound, down to LAN_POOL_ESCAPE, which
        # lobby-faction-byte turns back into the pool that follows it.
        for site, original in GAME_SLOT_TEMPLATE_BOUNDS:
            if site in hooked:
                continue
            patched = original[:-1] + bytes([LAN_POOL_ESCAPE & 0xFF])
            out.append((at(site), original, patched, f"template lower bound @0x{site:08x} -> -128"))
        jump(
            MP_SETUP_COMMAND_BLOCK,
            MP_SETUP_COMMAND_BLOCK_BYTES[:5],
            "register_pool",
            f"setup screen commands -> {POOL_COMMAND}, {POOL_MODAL_COMMAND}, {POOL_EXTERN}0-7, "
            f"{SEAT_EXTERN}0-7, {ESCAPE_EXTERN}",
        )
        jump(
            WINDOW_MANAGER_PROCESS_MOUSE,
            WINDOW_MANAGER_PROCESS_MOUSE_BYTES,
            "mouse_gate",
            "window mouse input -> none while the Random-pool panel is open",
        )
        jump(
            WINDOW_MANAGER_PROCESS_KEY,
            WINDOW_MANAGER_PROCESS_KEY_BYTES,
            "key_gate",
            "window key input -> Escape closes the Random-pool panel while it is open",
        )
        # ... and setting one must not clear the seat's start position as setting an observer does.
        out.append(
            (
                at(GAME_SLOT_SET_TEMPLATE_OBSERVER_JG),
                bytes([0x7F]),
                bytes([0x75]),
                "setPlayerTemplate observer test: jg -> jne (only -2 is an observer)",
            )
        )
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
        if not self.all_variants_box:
            return out
        # The online-only ClanGame checkbox becomes "Enable all variants": shown on every setup
        # screen, and labelled with the cave's string-table key.
        out.append(
            (
                at(GAME_RULES_CLAN_GAME_HIDE),
                GAME_RULES_CLAN_GAME_HIDE_BYTES,
                bytes([0xEB]) + GAME_RULES_CLAN_GAME_HIDE_BYTES[1:],
                "setup screen constructor: rule 1's checkbox no longer hidden (jne -> jmp)",
            )
        )
        label_slot = GAME_RULES_NAMES + 4 * ALL_VARIANTS_RULE
        out.append(
            (
                at(label_slot),
                u32(GAME_RULES_CLAN_GAME_LABEL),
                u32(_Layout(section_va).all_variants_label),
                f"rule 1 label @0x{label_slot:08x} -> {ALL_VARIANTS_LABEL}",
            )
        )
        # Ticking it must not turn the lobby into a clan match: no AI, teams locked.
        for va, stock, patched in MP_SETUP_CLAN_GAME_READS:
            out.append(
                (at(va), stock, patched, f"setup screen @0x{va:08x}: rule 1 is no clan match")
            )
        return out

    def ini_surface(self) -> Engine:
        """`VariantOf`, naming the `PlayerTemplate` a template is a variant of, and
        `EnabledForPvP`, whether a variant is offered while the lobby's `ALL_VARIANTS_LABEL` box is
        clear."""
        return Engine(
            fields=(
                FieldDelta("PlayerTemplate", FIELD_NAME, "Ref:factions", None, self.name),
                FieldDelta("PlayerTemplate", PVP_FIELD_NAME, "Bool", True, self.name),
            )
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
        for name, parse in zip(_FIELD_NAMES, ("parse", "parse_pvp"), strict=True):
            entry = next((e for e in all_entries if read_cstring(data, e[0]) == name), None)
            if entry is None:
                problems.append(f"the PlayerTemplate table does not name {name}")
                continue
            if entry[1] != code.label_va(parse):
                problems.append(f"{name} does not use the patch's own parse function")
            if entry[3] != 0:
                problems.append(f"{name} has a non-zero template offset ({entry[3]:#x})")

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
