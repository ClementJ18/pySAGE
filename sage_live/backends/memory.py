"""`MemoryBackend` - observe a running game read-only, with no injection.

`OpenProcess` + `ReadProcessMemory` and nothing else: no code in the game and no patched binary,
which makes this the low-risk observation path. Reading goes through a `MemorySource`, so the whole
decode is tested against a synthetic image, and only `ProcessMemory` needs a real game.

Addresses are build-specific. `LAYOUT_ROTWK_201` is verified against RotWK 2.01; reading the wrong
build does not fail, it returns nonsense, which is why `sage_live.backends.identity` checks the
build first. Derivations: `sage_patch/docs/engine-globals.md` and
`sage_patch/docs/live-object-model.md` (which also holds the notes on each `EngineLayout` field).

Cost: about three reads per additional object (asserted by `test_an_object_costs_three_reads`),
since template strings and module walks are cached per template; about 15 on average over a real
match. Every wide read has a field-by-field fallback that must decode identically, for spans that
cross into unmapped pages.

Worth knowing:

- Observations are whole-map; `Observation.under_fog` applies a seat's view using the shroud grid
  read here.
- Ownership goes through the object's `Team`, inverted from each player's teams. Objects on
  unresolvable teams read as None; do not substitute `template_side`, which often disagrees.
- Upgrades come in two scopes: faction-wide on the `Player`, per-object on the `Object`.
"""

from __future__ import annotations

import ctypes
import math
import struct
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from sage_live.api.observation import (
    GameObject,
    Observation,
    PlayerState,
    ProductionItem,
    SpecialPowerState,
)
from sage_live.backends.base import ConnectionRefused, GameExited
from sage_live.backends.identity import ROTWK_201_TIMESTAMP, BuildIdentity, read_identity
from sage_live.backends.protocol import Diagnostic, DiagnosticLog, Handshake
from sage_live.backends.shroud import ShroudGrid, read_shroud
from sage_patch.addresses import (
    BUILD,
    COMMAND_BUTTON_SPECIAL_POWER,
    DICT_SET_ASCII_STRING_BYTES,
    GLOBAL_DATA,
    GLOBAL_DATA_FPS_LIMIT,
    GLOBAL_DATA_USE_FPS_LIMIT,
    IMAGE_BASE,
    KINDOF_HERO_BIT,
    KINDOF_HERO_BYTE,
    OBJECT_CONSTRUCTION_PERCENT,
    OBJECT_MODULE_LIST,
    OBJECT_PRODUCER_ID,
    OBJECT_STATUS,
    OBJECT_STATUS_COUNT,
    OBJECT_STATUS_DWORDS,
    OBJECT_STATUS_NAMES,
    PRODUCTION_UPDATE_VTABLE,
    SHROUD_CELL_SIZE,
    SHROUD_CELL_STRIDE,
    SHROUD_CELLS,
    SHROUD_CELLS_X,
    SHROUD_CELLS_Y,
    SHROUD_FOG_ENABLED,
    SHROUD_IMPL,
    SHROUD_INV_CELL_SIZE,
    SHROUD_ORIGIN_X,
    SHROUD_ORIGIN_Y,
    SHROUD_RECORD_BASE,
    SHROUD_RECORD_STRIDE,
    SPELLBOOK_UI_SLOT_LIMIT,
    THE_COMMAND_SET_STORE,
    THE_GAME_LOGIC,
    THE_GAME_TEXT,
    THE_IN_GAME_UI,
    THE_MESSAGE_STREAM,
    THE_PLAYER_LIST,
    THE_SCIENCE_STORE,
    THE_SHROUD_MANAGER,
    THE_SIDES_LIST,
    THE_SPECIAL_POWER_STORE,
    THE_THING_FACTORY,
    THE_UPGRADE_CENTER,
    THING_TEMPLATE_KINDOF,
)
from sage_patch.patches.utils.model_conditions import MASK_DWORDS as MODEL_CONDITION_DWORDS
from sage_patch.patches.utils.model_conditions import MASK_OFFSET as MODEL_CONDITION_MASK
from sage_patch.patches.utils.model_conditions import NAME_TABLE_VA as MODEL_CONDITION_NAMES
from sage_patch.patches.utils.model_conditions import STOCK_BIT_COUNT as MODEL_CONDITION_COUNT
from sage_replay.replay import Order

__all__ = [
    "LAYOUT_ROTWK_201",
    "EngineLayout",
    "MemoryBackend",
    "MemorySource",
    "ProcessMemory",
    "UpgradeDefinition",
    "find_game_processes",
]

# A pointer outside this range is not a live heap object on 32-bit Windows.
_MIN_PTR = 0x10000
_MAX_PTR = 0x7FFFFFFF

# Guards against walking a corrupt or mid-write table into a multi-second stall.
_MAX_TABLE_SLOTS = 1 << 20


@dataclass(frozen=True)
class EngineLayout:
    """Static addresses and struct offsets for one engine build.

    Defaults are RotWK 2.01 + Edain. Every field here was confirmed against a running
    process, not inferred from shape alone.
    """

    # Which image these offsets are meaningful for, as its PE `TimeDateStamp`. `connect`
    # reads the same number out of the running process and refuses a mismatch, because
    # reading the wrong build with these offsets does not fail - it reports nonsense that
    # looks like data. **0 disables the check**, which is what a layout for an unidentified
    # build should carry: no gate is honest, a wrong gate is not.
    build_timestamp: int = ROTWK_201_TIMESTAMP

    # Subsystem globals come from `sage_patch.addresses`, the single description of this
    # build, so the addresses this reads and the ones the live-bridge cave calls cannot drift.
    the_player_list: int = THE_PLAYER_LIST
    the_game_logic: int = THE_GAME_LOGIC
    the_message_stream: int = THE_MESSAGE_STREAM
    the_upgrade_center: int = THE_UPGRADE_CENTER
    # `TheShroudManager` is a 20-byte facade; the grid lives on the object at `+0x10`. See
    # `sage_live.backends.shroud` for the model and how it was recovered.
    the_shroud_manager: int = THE_SHROUD_MANAGER
    shroud_impl: int = SHROUD_IMPL
    shroud_origin_x: int = SHROUD_ORIGIN_X
    shroud_origin_y: int = SHROUD_ORIGIN_Y
    shroud_cell_size: int = SHROUD_CELL_SIZE
    shroud_inv_cell_size: int = SHROUD_INV_CELL_SIZE
    shroud_cells_x: int = SHROUD_CELLS_X
    shroud_cells_y: int = SHROUD_CELLS_Y
    shroud_cells: int = SHROUD_CELLS
    shroud_fog_enabled: int = SHROUD_FOG_ENABLED
    # The cell's own geometry, which `sage_live.backends.shroud` reads through directly and a
    # writer needs by name: one cell is `0xA8` bytes, a 4-byte head then 20 eight-byte
    # per-player records whose first `u16` is that seat's shroud level.
    shroud_cell_stride: int = SHROUD_CELL_STRIDE
    shroud_record_base: int = SHROUD_RECORD_BASE
    shroud_record_stride: int = SHROUD_RECORD_STRIDE

    # PlayerList, from PlayerList::getNthPlayer
    pl_local_player: int = 0x10
    pl_count: int = 0x14
    pl_array: int = 0x18
    pl_max_players: int = 20

    # InGameUI's selected-drawable list (an MSVC `std::list` at `+0x20`, found through the virtual
    # `getAllSelectedDrawables`). Client state, not simulation state: this machine's selection.
    the_in_game_ui: int = THE_IN_GAME_UI
    ui_selected_drawables: int = 0x20
    list_node_value: int = 0x08
    # A selection larger than this is a bad walk rather than a big army.
    max_selection: int = 4096

    # Player
    player_display_name: int = 0x38
    player_name: int = 0x4C
    player_side: int = 0x58
    # The seat's `PlayerTemplate`, which holds the faction (`player_side` is the broader side):
    # `+0x14` the display name (UnicodeString), `+0x18` the side (AsciiString).
    player_template: int = 0x34
    template_faction: int = 0x14
    template_side: int = 0x18
    player_resources: int = 0x94
    player_resources_collected: int = 0x3E0
    # Spellbook points. Found by granting points with the sandbox hero and then *spending*
    # one: both fields rise together on a grant, only `+0x24` falls on a purchase, which is
    # what separates the spendable balance from the lifetime total.
    player_power_points: int = 0x24
    player_power_points_total: int = 0x1C
    # The rank ladder: lifetime skill points and the skill needed for the next and current rank
    # (Generals' `Player` order). Not yet confirmed live; `power_point_progress` rejects an
    # implausible triple.
    player_skill_points: int = 0x20
    player_rank_next: int = 0x28
    player_rank_floor: int = 0x2C
    # The seat colour, `0xFF000000 | rgb`; an opaque alpha proves the colour was set, so an unset
    # one reads as None. Read statically.
    player_color: int = 0x2A0
    # The match ledger, `Player+0x3DC` onward: the stat switch at `0x009CDF23` reads each of
    # these for the score screen (`sage_patch/docs/runtime-re-workflow.md`), and they read
    # plausibly live.
    player_spent_on_units: int = 0x3F0
    player_spent_on_structures: int = 0x3F4
    player_spent_on_heroes: int = 0x3F8
    player_units_created: int = 0x44C
    player_units_lost: int = 0x450
    player_structures_created: int = 0x4A4
    player_structures_lost: int = 0x4A8

    # Alliances: each seat's side dict in `TheSidesList` lists its allies' `playerName`s under
    # `playerAllies`. Read statically; a list that does not decode yields no allies.
    the_sides_list: int = THE_SIDES_LIST
    sl_count: int = 0x3C
    sl_sides: int = 0x40
    sl_side_stride: int = 0x60
    side_dict: int = 0x04
    dict_count: int = 0x04
    dict_pairs: int = 0x06
    dict_pair_stride: int = 0x08
    dict_pair_value: int = 0x04
    dict_type_ascii: int = DICT_SET_ASCII_STRING_BYTES[2]
    key_player_name: int = 0x00DA2F2C
    key_player_allies: int = 0x00DA2F5C
    max_dict_pairs: int = 256
    # The sciences the player holds, a `std::vector<ScienceType>` of ids (`game.sciences` index +
    # 1). Confirmed live by decoding each seat's spellbook. An AI's set need not obey the ini's
    # prerequisites.
    player_sciences: int = 0x310
    # A held-science vector longer than this is a bad read rather than a real spellbook. The
    # store carries 263 entries on RotWK 2.01 + Edain and a seat holds a handful of them, so
    # this is loose by two orders of magnitude on purpose - it is a sanity limit, not a count.
    max_sciences: int = 1 << 12
    # `TheScienceStore`: its entries cannot be named at a fixed offset, but its count bounds a valid
    # science id.
    the_science_store: int = THE_SCIENCE_STORE
    sc_vector: int = 0x0C

    # `TheWritableGlobalData` and the `UseFPSLimit` / `FramesPerSecondLimit` fields that pace the
    # main loop, plus the loop's cached copy of the first, which the engine recomputes every frame.
    the_global_data: int = GLOBAL_DATA
    gd_use_fps_limit: int = GLOBAL_DATA_USE_FPS_LIMIT  # one byte
    gd_fps_limit: int = GLOBAL_DATA_FPS_LIMIT
    gd_fps_limit_flag: int = 0x00DE4320  # the loop's own copy, recomputed per frame

    # `Object::m_experienceTracker` and its fields (points, level, max level). The level-up cascade
    # only runs on a grant, so experience written from outside applies at the next grant.
    obj_experience_tracker: int = 0x26C
    xt_experience: int = 0x10  # float
    xt_scalar: int = 0x1C  # float, the multiplier applied to incoming grants
    xt_level: int = 0x24
    xt_max_level: int = 0x28
    # Command points: in use, base cap, bonus, and a hard ceiling. The engine's cap is `min(base +
    # bonus + filtered extras, hard)`, so raising the ceiling means writing both bonus and hard. The
    # extras need the engine to evaluate, so the flat fields give a lower bound.
    player_command_points_used: int = 0x68
    player_command_points_cap: int = 0x64
    player_command_points_bonus: int = 0x6C
    player_command_points_hard_cap: int = 0x70
    # The player's own Team. Ownership on an Object is a Team*, not a player index, so the
    # only way from an object to its owner is to invert this.
    player_default_team: int = 0x30C
    # Upgrade bitsets, indexed by the engine's own upgrade id: bit `id % 32` of the dword at
    # `base + (id // 32) * 4`. Found by researching two upgrades landing in different words and
    # confirming each bit where its id predicted. `in_progress` is set the moment an order is
    # accepted and cleared on completion - but only for PLAYER-scoped upgrades; for an
    # OBJECT-scoped one the engine sets it here and never clears it, so it is filtered by scope.
    player_upgrades_in_progress: int = 0x0BC
    player_upgrades_completed: int = 0x14C

    # GameLogic
    gl_frame: int = 0x40
    gl_table_begin: int = 0xB8
    gl_table_end: int = 0xBC
    gl_object_count: int = 0xC4
    # Set to 1 when this client declares itself out of sync, zero for the rest of the match. A
    # latch rather than a pulse, which is what lets a 5 Hz poller be sure of catching the edge.
    # Derived statically; see `sage_patch/docs/desync-detection.md` for the two sites that write
    # it. Unlike its neighbours above this one has **not** been confirmed against a running
    # process, because confirming it needs a match that actually desyncs.
    gl_desync_declared: int = 0x1BC

    # Table entry: a wrapper, not the object itself
    entry_id: int = 0x04
    entry_object: int = 0x08

    # UpgradeCenter - the engine's own upgrade table, so bit -> name needs no ini load.
    uc_list: int = 0x0C  # head of the template list, most recently registered first
    uc_count: int = 0x10
    # UpgradeTemplate
    upgrade_type: int = 0x04  # 0 = PLAYER, 1 = OBJECT
    upgrade_name: int = 0x08  # AsciiString
    upgrade_index: int = 0x38  # the engine's registration index == the replay id
    upgrade_next: int = 0x64

    # ThingFactory - the same shape as the UpgradeCenter, one list head and one count, so the
    # thing id space is readable from the process too. `tf_count` read 11143 on RotWK 2.01 +
    # Edain. Unlike an upgrade, a `ThingTemplate` carries no index field that was findable, so
    # the id comes from the walk position: the list is prepended, and reversing it gives
    # registration order with `DefaultThingTemplate` first.
    the_thing_factory: int = THE_THING_FACTORY
    tf_list: int = 0x0C
    tf_count: int = 0x10
    tmpl_next: int = 0x494

    # SpecialPowerStore - the third of the four id spaces, and the one registry that is **not**
    # a linked list. It is a `std::vector` of `SpecialPowerTemplate*`: `{begin, end, capacity}`
    # at `+0x0C`, so the count is `(end - begin) / 4` and there is no count field to check it
    # against. That shape is why the list walk used for the other two never found it.
    the_special_power_store: int = THE_SPECIAL_POWER_STORE
    sps_vector: int = 0x0C
    power_name: int = 0x10  # AsciiString on the template
    # A vector longer than this is a bad read rather than a real store.
    max_powers: int = 1 << 14

    # A special-power module and the frame its power is next usable on - the engine's own,
    # discounted cooldown (confirmed live), which is shorter than the ini's `ReloadTime`.
    module_data: int = 0x04
    module_ready_frame: int = 0x18
    module_data_template: int = 0x08
    # A module list longer than this is a bad read; the spellbook carries about 140.
    max_modules: int = 1 << 10

    # Object
    obj_template: int = 0x04
    obj_team: int = 0x31C  # Team*, resolved to a player via the prototype below
    # `Team` -> `TeamPrototype` -> `Player`: resolves the teams a player owns besides its default
    # one (checked live; see `_owner_of_team`).
    team_proto: int = 0x30
    proto_owner: int = 0x08
    # A pointer to a **NULL-terminated** array of `BehaviorModule*`. This is the hop
    # `live-object-model.md` §5 named as the one thing missing for a live consumer: production
    # state lives on a module, and this is how an object reaches its modules.
    obj_modules: int = OBJECT_MODULE_LIST
    # Completed OBJECT-scoped upgrades, same bitset layout as the player's masks. An object has
    # no in-progress mask; the player's carries that, unclearable.
    obj_upgrades_completed: int = 0x28C
    obj_pos_x: int = 0x14
    obj_pos_y: int = 0x24
    obj_pos_z: int = 0x34
    obj_cos: int = 0x08
    obj_sin: int = 0x18
    # The engine's `ModelConditionFlags` bitset (19 dwords, 591 names), inside `obj_span` so it
    # costs no extra read. Offsets from `sage_patch.patches.utils.model_conditions`.
    obj_model_conditions: int = MODEL_CONDITION_MASK
    model_condition_words: int = MODEL_CONDITION_DWORDS
    the_model_condition_names: int = MODEL_CONDITION_NAMES
    model_condition_count: int = MODEL_CONDITION_COUNT

    # What contains this object (a battalion member's horde), or 0. Found differentially and checked
    # across four factions; probably `m_containedBy`, but only horde membership has been observed.
    obj_contained_by: int = 0x27C
    # The engine's `ObjectStatusMaskType` (`HORDE_MEMBER`, `IS_LEAVING_FACTORY`, ...), in the same
    # window as the fields above.
    obj_status: int = OBJECT_STATUS
    status_words: int = OBJECT_STATUS_DWORDS
    the_object_status_names: int = OBJECT_STATUS_NAMES
    object_status_count: int = OBJECT_STATUS_COUNT
    # The second `ObjectID`, next to the object's own. The engine falls back to it when
    # `obj_contained_by` is null and treats what it names as this object's horde, so a unit that
    # has left its battalion still points at it here - which is the whole reason it is read.
    obj_producer_id: int = OBJECT_PRODUCER_ID
    # A float, 0-100 while the structure is being built and -1 otherwise. Written to 0 where a
    # builder drops a foundation (`0x008AD86F`), advanced per frame and re-derived from the
    # body's health ratio by `GettingBuiltBehavior` (`0x00856809`) - see
    # `sage_patch/docs/construction-initial-health.md`. Inside `obj_span`, so it is free.
    obj_construction_percent: int = OBJECT_CONSTRUCTION_PERCENT
    # `next` and `prev` of one **global** doubly-linked list holding every live object, not any
    # kind of parent link. Measured: 317 of 318 objects link, the two are exact inverses for
    # every one of them, there is a single head and a single tail, and walking `next` from the
    # head visits the whole table. They read like horde membership only because a battalion's
    # members are created consecutively and so end up adjacent in the list.
    obj_list_next: int = 0x8C
    obj_list_prev: int = 0x90
    obj_body: int = 0x25C
    # The object's `Drawable`, and the drawable's way back. Only the reverse link is needed to
    # turn a selection into objects, but both were measured together and the pair is what makes
    # either trustworthy: the selected drawable was found by searching the whole object table for
    # the pointer, which landed on exactly one object (a `GondorTrebuchet`, 2026-08-13), and that
    # object's own address appears in the drawable at `+0xFC`.
    obj_drawable: int = 0x84
    drawable_object: int = 0xFC
    # How much of an `Object` one read takes. Sized to reach past the last field read inline -
    # the team pointer at `+0x31C` - so a single read serves the whole header, upgrade mask
    # included. Widening it costs bytes; narrowing it silently reintroduces per-field reads
    # through the fallback path.
    obj_span: int = 0x320

    # BodyModule
    body_health: int = 0x08
    body_max_health: int = 0x10

    # ThingTemplate
    tmpl_name: int = 0x64
    tmpl_side: int = 0x6C
    # `DisplayName`, already localised. The field parser (`0x0073D3E0`) stores the label at
    # `+0x2C`, fetches it through `TheGameText` and assigns the result to the `UnicodeString`
    # beside it, so the name the game shows reads straight off the template in whatever language
    # and mod the game is running - no string table on disk.
    tmpl_display_name: int = 0x30
    tmpl_hero_byte: int = KINDOF_HERO_BYTE
    tmpl_hero_bit: int = KINDOF_HERO_BIT
    # `KindOf SPELL_BOOK` is index 123: bit 0x08 of the KindOf byte at `+0xF`, from the engine's
    # own name table (`explore.py enum KindOf`).
    tmpl_spellbook_byte: int = THING_TEMPLATE_KINDOF + 0xF
    tmpl_spellbook_bit: int = 0x08
    # `KindOf STRUCTURE` is index 7: bit 0x80 of the first KindOf byte.
    tmpl_structure_byte: int = THING_TEMPLATE_KINDOF
    tmpl_structure_bit: int = 0x80
    # `KindOf SELECTABLE` is index 1: bit 0x02 of the first KindOf byte.
    tmpl_selectable_byte: int = THING_TEMPLATE_KINDOF
    tmpl_selectable_bit: int = 0x02
    # `BuildCost`, row 39 of the ThingTemplate field table (`0x00DA3DB8`). Its parser
    # (`0x0042EC11`) range-checks 0..0xFFFF and stores a `word`, hence the odd offset.
    tmpl_build_cost: int = 0x5EA

    # UpgradeTemplate. Unlike a thing's, an upgrade's `DisplayName` is stored as the bare label
    # (an `AsciiString`, per the `Upgrade` field table), so it is resolved through `TheGameText`.
    upgrade_display_label: int = 0x28

    # SpecialPowerTemplate. `RequiredSciences` is a `std::vector<ScienceType>`: its parser
    # (`0x0073B4A0`) empties it with `erase([+0], [+4])` and appends, which is the same
    # `{begin, end, capacity}` shape as the player's own science vector.
    power_required_sciences: int = 0x24
    max_power_sciences: int = 64

    # ScienceInfo. `DisplayName`'s parser (`0x0073B192`) fetches the label through `TheGameText`
    # and stores the localised text back as an `AsciiString`, so this is the name, not a label.
    # `science_id` is the entry's own `ScienceType`, read to *prove* an entry is the one asked
    # for rather than trusting the vector's order - see `science_display_name`.
    science_id: int = 0x10
    science_display_name: int = 0x14

    # `TheGameText`, the string table labels resolve through: two tables of 8-byte entries whose
    # record holds the text at `+4` (the label at `+0` is inferred, so lookups require an exact
    # match).
    the_game_text: int = THE_GAME_TEXT
    gt_tables: tuple[int, ...] = (0x2C, 0x30)
    gt_count: int = 0x00
    gt_entries: int = 0x08
    gt_entry_stride: int = 0x08
    gt_entry_record: int = 0x04
    gt_record_label: int = 0x00
    gt_record_text: int = 0x04
    max_game_text: int = 1 << 18

    # The buttons an object offers, where a power's in-game name lives: the three runtime
    # command-set overrides `Object::getCommandSetString` checks, then the template's `CommandSet`.
    obj_command_set_overrides: tuple[int, ...] = (0x438, 0x440, 0x43C)
    tmpl_command_set: int = 0x70
    # `ControlBar::findCommandSet` (`0x0071EFA2`) looks the name up in a hash map at `+0x30`,
    # whose search (`0x006C033A`) indexes a bucket vector `{begin +4, end +8}` and walks each
    # bucket's chain of `{next, AsciiString name, CommandSet*}` nodes.
    the_control_bar: int = THE_COMMAND_SET_STORE
    cb_command_sets: int = 0x30
    hash_buckets: int = 0x04
    hash_node_next: int = 0x00
    hash_node_key: int = 0x04
    hash_node_value: int = 0x08
    max_hash_buckets: int = 1 << 16
    max_command_sets: int = 1 << 15
    # `CommandSet::getCommandButton` (`0x0080C837`) is `[this + slot*4 + 0x14]`, unbounded; the
    # spellbook bar's own loop stops at `SPELLBOOK_UI_SLOT_LIMIT`.
    cs_buttons: int = 0x14
    cs_slots: int = SPELLBOOK_UI_SLOT_LIMIT
    # CommandButton. `getTextLabel` (`0x0075CE47`) returns the runtime override at `+0x7C` when
    # it is set, and otherwise element `[+0xFC]` of the `TextLabel` vector `{+0x58, +0x5C}`,
    # clamped to the last one.
    button_special_power: int = COMMAND_BUTTON_SPECIAL_POWER
    button_label_override: int = 0x7C
    button_labels: int = 0x58
    button_label_range: int = 0xFC

    # ProductionUpdate - what a structure is currently making.
    #
    # The module is identified by its **primary vtable**, which is unique to the class, so this
    # needs none of the engine calls `getProductionUpdateInterface` makes and cannot mistake a
    # different module for this one. Units and upgrades share one queue, appended at the tail.
    production_update_vtable: int = PRODUCTION_UPDATE_VTABLE
    module_object: int = 0x08  # Object* back-pointer, used to check the walk landed correctly
    production_head: int = 0x28
    production_tail: int = 0x2C
    production_count: int = 0x34
    # ProductionEntry, 0x54 bytes. `kind` is 1 for a unit, 2 for an upgrade, 3 for a hero
    # revive; the unit kinds keep a `ThingTemplate*` and the upgrade kind an `UpgradeTemplate*`,
    # in different slots.
    entry_kind: int = 0x04
    entry_template: int = 0x08
    entry_upgrade: int = 0x0C
    entry_next: int = 0x48
    # A production entry's progress: `entry_progress` is the accumulator that decides completion,
    # `entry_percent` is derived from it for reading, and `entry_percent_per_frame` is `100 /
    # buildTime`, so remaining frames need no ini load.
    entry_percent: int = 0x14
    entry_percent_per_frame: int = 0x18
    entry_progress: int = 0x1C
    # A queue longer than this means a corrupt read rather than a real structure - refuse rather
    # than spin.
    max_queue: int = 64
    # The module slots `_production_module` reads in one all-or-nothing read - kept separate from
    # `max_modules`, because a large read fails whole when it crosses an unmapped page.
    production_scan: int = 64

    # AsciiString / UnicodeString: `{u32 refcount; u16 length; u16 allocated; chars[]}`, counts in
    # characters (measured live).
    string_length: int = 4
    string_chars: int = 8


LAYOUT_ROTWK_201 = EngineLayout()

# Refuse to walk a list longer than this; a corrupt `next` pointer would otherwise spin.
_MAX_UPGRADES = 1 << 14
# The thing table is an order of magnitude larger - 11,143 on RotWK 2.01 + Edain.
_MAX_THINGS = 1 << 17


def _clamp_percent(value: float | None) -> float:
    """A production entry's percent, held to 0-100. An unread or non-finite float reads as 0,
    and the engine overshoots 100 by one step on the frame an entry completes."""
    if value is None or not math.isfinite(value):
        return 0.0
    return min(100.0, max(0.0, value))


def _opaque_rgb(value: int | None) -> int | None:
    """A stored `0xAARRGGBB` colour as `0xRRGGBB`, or None unless the alpha is fully opaque -
    which is what the engine's own `or 0xFF000000` makes of every colour it was actually given."""
    if value is None or (value >> 24) != 0xFF:
        return None
    return value & 0xFFFFFF


def _construction_percent(value: float) -> float | None:
    """`Object+0x288` as the model carries it: None for the engine's -1 "not being built", and
    for anything else outside 0-100, which is a bad read rather than a building."""
    if not math.isfinite(value) or value < 0.0 or value > 100.0 + 1e-3:
        return None
    return min(100.0, value)


@dataclass(frozen=True)
class UpgradeDefinition:
    """One row of the engine's upgrade table. `upgrade_id` is the registration index - the same
    number the replay order stream carries and the live bitsets are indexed by.
    """

    upgrade_id: int
    name: str
    player_scoped: bool


class MemorySource(Protocol):
    """Somewhere bytes can be read from by address."""

    def read(self, address: int, size: int) -> bytes | None: ...

    def close(self) -> None: ...


def find_game_processes(name: str = "game.dat") -> list[int]:
    """Pids whose executable matches `name`. Returns [] off Windows rather than raising."""
    if sys.platform != "win32":
        return []

    class _Entry(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_uint32),
            ("cntUsage", ctypes.c_uint32),
            ("th32ProcessID", ctypes.c_uint32),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", ctypes.c_uint32),
            ("cntThreads", ctypes.c_uint32),
            ("th32ParentProcessID", ctypes.c_uint32),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_uint32),
            ("szExeFile", ctypes.c_char * 260),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    snapshot = k32.CreateToolhelp32Snapshot(0x2, 0)
    if snapshot in (0, -1):
        return []
    found: list[int] = []
    try:
        entry = _Entry()
        entry.dwSize = ctypes.sizeof(_Entry)
        ok = k32.Process32First(snapshot, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.decode("latin-1").lower() == name.lower():
                found.append(int(entry.th32ProcessID))
            ok = k32.Process32Next(snapshot, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snapshot)
    return found


class ProcessMemory:
    """Access to another process through `ReadProcessMemory`.

    Read-only unless `writable=True` (only the bridge needs writes). The platform check is here
    rather than at import, so `sage_live` imports anywhere.
    """

    # PROCESS_VM_READ | PROCESS_QUERY_INFORMATION
    _READ = 0x0010 | 0x0400
    # PROCESS_VM_WRITE | PROCESS_VM_OPERATION
    _WRITE = 0x0020 | 0x0008

    # Declared rather than left to inference: everything below the platform check in `__init__`
    # is unreachable to a type checker running as Linux, so the assignments there give these no
    # type at all and every use in the methods below becomes an error on the CI runner.
    writable: bool
    _k32: ctypes.CDLL  # a `WinDLL` on Windows, which `CDLL` is the cross-platform spelling of

    def __init__(self, pid: int, writable: bool = False) -> None:
        if sys.platform != "win32":
            raise RuntimeError(
                f"ProcessMemory needs Windows; this is {sys.platform}. "
                "Use a LoopbackBackend, or run the policy against a game in a VM."
            )
        self.pid = pid
        self.writable = writable
        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._k32.OpenProcess.restype = ctypes.c_void_p
        self._k32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        for name in ("ReadProcessMemory", "WriteProcessMemory"):
            getattr(self._k32, name).argtypes = (
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_size_t),
            )
        access = self._READ | (self._WRITE if writable else 0)
        handle = self._k32.OpenProcess(access, 0, pid)
        if not handle:
            err = ctypes.get_last_error()
            hint = (
                " - the game runs as administrator, so this process must be elevated too"
                if err == 5
                else ""
            )
            raise PermissionError(f"OpenProcess({pid}) failed with error {err}{hint}")
        self._handle: int | None = handle

    def read(self, address: int, size: int) -> bytes | None:
        if self._handle is None or size <= 0:
            return None
        buf = (ctypes.c_ubyte * size)()
        got = ctypes.c_size_t()
        ok = self._k32.ReadProcessMemory(
            self._handle, ctypes.c_void_p(address), buf, size, ctypes.byref(got)
        )
        if not ok or got.value != size:
            return None
        return bytes(buf)

    def write(self, address: int, data: bytes) -> bool:
        """Write `data` at `address`. False unless the handle was opened writable."""
        if self._handle is None or not self.writable or not data:
            return False
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        put = ctypes.c_size_t()
        ok = self._k32.WriteProcessMemory(
            self._handle, ctypes.c_void_p(address), buf, len(data), ctypes.byref(put)
        )
        return bool(ok) and put.value == len(data)

    def close(self) -> None:
        if self._handle is not None:
            self._k32.CloseHandle(ctypes.c_void_p(self._handle))
            self._handle = None


class MemoryBackend:
    """Observation-only backend over a live process. It cannot issue orders; `send` records a
    diagnostic rather than silently dropping them.
    """

    def __init__(
        self,
        source: MemorySource,
        layout: EngineLayout = LAYOUT_ROTWK_201,
        handshake: Handshake | None = None,
        expect: Handshake | None = None,
        read_production: bool = True,
    ) -> None:
        self.source = source
        self.layout = layout
        # Reading production state costs a module-list walk per object - one read for the array
        # plus one per module until the `ProductionUpdate` is found or the list ends. That is
        # the largest per-object cost here after the object itself, so a consumer polling every
        # frame and not asking "what is this building making" can turn it off.
        self.read_production = read_production
        # Declared rather than agreed. A caller-supplied handshake is used unchanged; the
        # default one is built at connect time out of what the running image actually says,
        # so `expect` has something real to gate on.
        self._declared = handshake
        self._handshake = handshake or Handshake(engine_build=BUILD, fog_of_war=False)
        self._identity: BuildIdentity | None = None
        self._expect = expect
        self._diagnostics = DiagnosticLog()
        self._connected = False
        self._latest: Observation | None = None
        self._upgrades: dict[int, UpgradeDefinition] | None = None
        self._upgrade_word_count: int | None = None
        self._things: tuple[str, ...] | None = None
        self._powers: tuple[str, ...] | None = None
        # Bit-order name tables by their address, so the two bitsets share one cache.
        self._bit_name_tables: dict[int, tuple[str, ...]] = {}
        # `{template address -> name}` for both registries, filled by the walks above and used
        # to name whatever a production queue entry points at.
        self._thing_at: dict[int, str] = {}
        self._upgrade_at: dict[int, str] = {}
        # Per-template caches. A template's strings and its module composition are fixed once
        # ini parsing is done, so both are read once per template rather than once per object.
        self._template_at: dict[int, tuple[str, str]] = {}
        # `{template address -> (is hero, is spellbook)}`, read with the template's KindOf.
        self._template_kinds: dict[int, tuple[bool, bool, bool, bool, int]] = {}
        # Display names by lowercased code name, and the string table's `{label -> record}`.
        self._thing_display: dict[str, str] = {}
        self._upgrade_display: dict[str, str] = {}
        self._science_display: dict[int, str] | None = None
        self._game_text: dict[str, int] | None = None
        # `{lowercased command set name -> CommandSet*}`, walked once.
        self._command_sets: dict[str, int] | None = None
        self._template_produces: dict[int, bool] = {}
        # `{object id -> Object*}`, rebuilt by every `read_objects`. Not a per-template cache
        # like the two above: object ids are reused as objects die and are created, so this is
        # only meaningful for the table walk that filled it.
        self._object_at: dict[int, int] = {}
        # `{Player* -> index}`, rebuilt with the team map each walk. `_owner_of_team` needs it to
        # turn the `Player*` a team's prototype names back into the index everything else uses.
        self._players_by_pointer: dict[int, int] = {}
        # Teams whose prototype chain did not land on a known player. Remembered so a team that
        # cannot be resolved is not re-walked for every object standing on it.
        self._teams_unresolved: set[int] = set()

    @property
    def diagnostics(self) -> DiagnosticLog:
        return self._diagnostics

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def identity(self) -> BuildIdentity | None:
        """What the running image says it is, once connected."""
        return self._identity

    def connect(self) -> Handshake:
        """Identify the build, agree the handshake, and confirm a game is running - in that order,
        so the most specific failure is reported.
        """
        self._identity = self._identify()
        if self._declared is None:
            self._handshake = Handshake(
                engine_build=BUILD,
                data_checksum=self._identity.fingerprint,
                fog_of_war=False,
            )
        if self._expect is not None:
            ok, why = self._expect.accepts(self._handshake)
            if not ok:
                raise ConnectionRefused(why)
        if self._u32(self.layout.the_game_logic) in (None, 0):
            raise ConnectionRefused(
                "TheGameLogic is null - no game in progress, or the layout is for another build"
            )
        self._connected = True
        return self._handshake

    def _identify(self) -> BuildIdentity:
        """The running image, refused unless it is the build this layout describes."""
        identity = read_identity(self.source.read, IMAGE_BASE)
        if identity is None:
            raise ConnectionRefused(
                f"no PE image is mapped at {IMAGE_BASE:#010x}: this is not a game.dat process, "
                "the handle cannot read it (an unelevated shell), or the image was relocated - "
                "and a relocated image invalidates every address in the layout"
            )
        expected = self.layout.build_timestamp
        if expected and identity.timestamp != expected:
            raise ConnectionRefused(
                f"this is not the build the layout describes: the running game.dat is stamped "
                f"{identity.timestamp:#010x}, and these offsets were confirmed against "
                f"{expected:#010x}. Reading it anyway would not fail - it would report plausible "
                "nonsense - so pass an EngineLayout for this build, or set `build_timestamp` to 0 "
                "in --layout-json to read it unverified"
            )
        return identity

    def close(self) -> None:
        self._connected = False
        self.source.close()

    def _u32(self, address: int) -> int | None:
        raw = self.source.read(address, 4)
        return struct.unpack("<I", raw)[0] if raw else None

    def _i32(self, address: int) -> int | None:
        raw = self.source.read(address, 4)
        return struct.unpack("<i", raw)[0] if raw else None

    def _f32(self, address: int) -> float | None:
        raw = self.source.read(address, 4)
        return float(struct.unpack("<f", raw)[0]) if raw else None

    def _pointer(self, address: int) -> int | None:
        """A pointer field, or None when it is null or implausible."""
        value = self._u32(address)
        if value is None or not (_MIN_PTR <= value <= _MAX_PTR):
            return None
        return value

    def _ascii(self, address: int, limit: int = 128) -> str:
        """Follow an `AsciiString` field and read its characters."""
        data_ptr = self._pointer(address)
        if data_ptr is None:
            return ""
        raw = self.source.read(data_ptr + self.layout.string_chars, limit)
        if not raw:
            return ""
        return raw.split(b"\x00")[0].decode("latin-1", errors="replace")

    def _utf16(self, address: int, limit: int = 128) -> str:
        data_ptr = self._pointer(address)
        if data_ptr is None:
            return ""
        raw = self.source.read(data_ptr + self.layout.string_chars, limit)
        if not raw:
            return ""
        text = raw.decode("utf-16-le", errors="replace")
        return text.split("\x00")[0]

    def upgrade_table(self) -> dict[int, UpgradeDefinition]:
        """`{engine upgrade id -> definition}`, read from `TheUpgradeCenter` once and cached.

        Read from the engine, so ids are exact for the loaded mod with no ini load.
        (`sage_live.utils.resolve` needs a `+3` offset to reconstruct them from ini: the three
        veterancy upgrades the engine registers first.) The list is prepended, but each id comes off
        its template, so walk order does not matter.
        """
        if self._upgrades is not None:
            return self._upgrades
        lay = self.layout
        table: dict[int, UpgradeDefinition] = {}
        centre = self._pointer(lay.the_upgrade_center)
        if centre is None:
            self._diagnostics.append(Diagnostic("TheUpgradeCenter is null; upgrades unnamed"))
            self._upgrades = table
            return table
        node = self._pointer(centre + lay.uc_list)
        seen: set[int] = set()
        while node is not None and node not in seen and len(seen) < _MAX_UPGRADES:
            seen.add(node)
            name = self._ascii(node + lay.upgrade_name)
            upgrade_id = self._i32(node + lay.upgrade_index)
            # id 0 is a real upgrade (`Upgrade_Veterancy_VETERAN`), so only negatives are junk.
            if name:
                self._upgrade_at[node] = name
            if name and upgrade_id is not None and upgrade_id >= 0:
                table[upgrade_id] = UpgradeDefinition(
                    upgrade_id=upgrade_id,
                    name=name,
                    player_scoped=self._i32(node + lay.upgrade_type) == 0,
                )
            node = self._pointer(node + lay.upgrade_next)
        expected = self._u32(centre + lay.uc_count)
        # One id is legitimately missing: the first-registered template reads -1 rather than 0.
        if expected is not None and len(seen) != expected:
            self._diagnostics.append(
                Diagnostic(f"walked {len(seen)} upgrade templates but the centre claims {expected}")
            )
        self._upgrades = table
        return table

    def thing_order(self) -> tuple[str, ...]:
        """Every `ThingTemplate` name in registration order, from `TheThingFactory` (cached).

        An order id is `index + sage_replay.idspace.THING_OFFSET`; index 0 is
        `DefaultThingTemplate`. The list is prepended, so it is reversed here, which keeps a missing
        tail entry from shifting any id. The walk is checked against the factory's count.
        """
        if self._things is not None:
            return self._things
        lay = self.layout
        factory = self._pointer(lay.the_thing_factory)
        if factory is None:
            self._diagnostics.append(Diagnostic("TheThingFactory is null; thing names unavailable"))
            self._things = ()
            return self._things

        # One read per node covers both the name pointer and the next pointer.
        span = lay.tmpl_next + 4
        node = self._pointer(factory + lay.tf_list)
        walked: list[str] = []
        seen: set[int] = set()
        while node is not None and node not in seen and len(seen) < _MAX_THINGS:
            seen.add(node)
            blob = self.source.read(node, span)
            if blob is None:
                break
            name_ptr = struct.unpack_from("<I", blob, lay.tmpl_name)[0]
            name = ""
            if _MIN_PTR <= name_ptr <= _MAX_PTR:
                chars = self.source.read(name_ptr + lay.string_chars, 128)
                if chars:
                    name = chars.split(b"\x00")[0].decode("latin-1", errors="replace")
            walked.append(name)
            # Kept so a pointer held by something else - a production queue entry - can be
            # resolved to a name by identity rather than by a second guess at a layout.
            self._thing_at[node] = name
            nxt = struct.unpack_from("<I", blob, lay.tmpl_next)[0]
            node = nxt if _MIN_PTR <= nxt <= _MAX_PTR else None

        expected = self._u32(factory + lay.tf_count)
        if expected is not None and len(walked) != expected:
            self._diagnostics.append(
                Diagnostic(
                    f"walked {len(walked)} thing templates but the factory claims {expected}; "
                    "ids are trustworthy only if the missing entries are the newest ones"
                )
            )
        self._things = tuple(reversed(walked))
        return self._things

    def power_order(self) -> tuple[str, ...]:
        """Every `SpecialPower` name in registration order, from `TheSpecialPowerStore`.

        An order id is `index + sage_replay.idspace.POWER_OFFSET`. Agrees with the ini
        reconstruction at every position on RotWK 2.01 + Edain. A vector, so there is no count to
        check against; the bound is a sanity limit.
        """
        if self._powers is not None:
            return self._powers
        lay = self.layout
        store = self._pointer(lay.the_special_power_store)
        if store is None:
            self._diagnostics.append(Diagnostic("TheSpecialPowerStore is null; powers unnamed"))
            self._powers = ()
            return self._powers
        begin = self._pointer(store + lay.sps_vector)
        end = self._u32(store + lay.sps_vector + 4)
        if begin is None or end is None or end < begin:
            self._diagnostics.append(Diagnostic("the special-power vector is unreadable"))
            self._powers = ()
            return self._powers
        count = (end - begin) // 4
        if not (0 < count <= lay.max_powers):
            self._diagnostics.append(Diagnostic(f"implausible special-power count {count}"))
            self._powers = ()
            return self._powers
        raw = self.source.read(begin, count * 4)
        if raw is None:
            self._powers = ()
            return self._powers
        names: list[str] = []
        for template in struct.unpack(f"<{count}I", raw):
            if not (_MIN_PTR <= template <= _MAX_PTR):
                names.append("")
                continue
            names.append(self._ascii(template + lay.power_name))
        self._powers = tuple(names)
        return self._powers

    def _bit_names(self, table: int, declared: int, label: str) -> tuple[str, ...]:
        """A bit-order name table (a NULL-terminated `const char*[]` in static data), walked to its
        terminator and checked against the engine's bit count.
        """
        cached = self._bit_name_tables.get(table)
        if cached is not None:
            return cached
        names: list[str] = []
        for index in range(declared + 1):
            pointer = self._pointer(table + index * 4)
            if pointer is None:
                break
            raw = self.source.read(pointer, 64)
            if raw is None:
                break
            names.append(raw.split(b"\x00")[0].decode("latin-1", errors="replace"))
        if names and len(names) != declared:
            self._diagnostics.append(
                Diagnostic(f"walked {len(names)} {label} names but this build declares {declared}")
            )
        self._bit_name_tables[table] = tuple(names)
        return self._bit_name_tables[table]

    def model_condition_names(self) -> tuple[str, ...]:
        """The engine's `ModelConditionFlags` names, in bit order, read from the image."""
        lay = self.layout
        return self._bit_names(
            lay.the_model_condition_names, lay.model_condition_count, "model-condition"
        )

    def object_status_names(self) -> tuple[str, ...]:
        """The engine's `ObjectStatus` names, in bit order, read from the image."""
        lay = self.layout
        return self._bit_names(
            lay.the_object_status_names, lay.object_status_count, "object-status"
        )

    def _flags_at(
        self, blob: bytes | None, obj_ptr: int, base: int, words: int, names: tuple[str, ...]
    ) -> frozenset[str]:
        """Decode one of an object's bitsets into names, from the already-read header (no extra
        read).
        """
        span = words * 4
        if blob is not None and base + span <= len(blob):
            raw: bytes | None = blob[base : base + span]
        else:
            raw = self.source.read(obj_ptr + base, span)
        if not raw:
            return frozenset()
        bits = int.from_bytes(raw, "little")
        if not bits or not names:
            return frozenset()
        found: list[str] = []
        while bits:
            lowest = bits & -bits
            index = lowest.bit_length() - 1
            if index < len(names):
                found.append(names[index])
            bits ^= lowest
        return frozenset(found)

    def _upgrade_words(self) -> int:
        """How many dwords of a bitset cover every upgrade this build defines - from the engine's
        count, so stray bits past it are never decoded. Cached.
        """
        if self._upgrade_word_count is not None:
            return self._upgrade_word_count
        centre = self._pointer(self.layout.the_upgrade_center)
        count = self._u32(centre + self.layout.uc_count) if centre is not None else None
        if count is None or not (0 < count <= _MAX_UPGRADES):
            count = max(self.upgrade_table(), default=0) + 1
        self._upgrade_word_count = (count + 31) // 32
        return self._upgrade_word_count

    def _upgrades_at(
        self,
        base_ptr: int,
        base: int,
        player_scope: bool | None = None,
        blob: bytes | None = None,
    ) -> frozenset[str]:
        """Decode one upgrade bitset into code names, from the already-read header.

        `player_scope` filters by definition scope: the player's in-progress mask also records
        object-scoped upgrades and never clears them.
        """
        words = self._upgrade_words()
        if blob is not None and base + words * 4 <= len(blob):
            raw: bytes | None = blob[base : base + words * 4]
        else:
            raw = self.source.read(base_ptr + base, words * 4)
        if raw is None:
            return frozenset()
        table = self.upgrade_table()
        names: list[str] = []
        bits = int.from_bytes(raw, "little")
        while bits:
            lowest = bits & -bits
            definition = table.get(lowest.bit_length() - 1)
            if definition is not None and (
                player_scope is None or definition.player_scoped == player_scope
            ):
                names.append(definition.name)
            bits ^= lowest
        return frozenset(names)

    def _sciences_at(self, base_ptr: int) -> frozenset[int]:
        """The ids in a player's held-science vector (see `player_sciences`). Empty is an ordinary
        answer; an implausible length is treated as a bad read.
        """
        lay = self.layout
        begin = self._pointer(base_ptr + lay.player_sciences)
        end = self._u32(base_ptr + lay.player_sciences + 4)
        if begin is None or end is None or end < begin:
            return frozenset()
        count = (end - begin) // 4
        if not (0 < count <= lay.max_sciences):
            if count:
                self._diagnostics.append(Diagnostic(f"implausible science count {count}"))
            return frozenset()
        raw = self.source.read(begin, count * 4)
        if raw is None:
            return frozenset()
        return frozenset(struct.unpack(f"<{count}i", raw))

    def read_players(self) -> tuple[PlayerState, ...]:
        lay = self.layout
        pl = self._pointer(lay.the_player_list)
        if pl is None:
            self._diagnostics.append(Diagnostic("ThePlayerList is null"))
            return ()
        count = self._u32(pl + lay.pl_count) or 0
        if count > lay.pl_max_players:
            self._diagnostics.append(Diagnostic(f"implausible player count {count}"))
            count = lay.pl_max_players
        players: list[PlayerState] = []
        allied = self._alliances()
        for index in range(count):
            ptr = self._pointer(pl + lay.pl_array + index * 4)
            if ptr is None:
                continue
            name = self._ascii(ptr + lay.player_name)
            side = self._ascii(ptr + lay.player_side)
            # The neutral placeholder slot carries no name and no side; it is not a player.
            if not name and not side:
                continue
            players.append(
                PlayerState(
                    index=index,
                    name=name or self._utf16(ptr + lay.player_display_name),
                    faction=side,
                    resources=self._i32(ptr + lay.player_resources) or 0,
                    resources_collected=self._i32(ptr + lay.player_resources_collected) or 0,
                    power_points=self._i32(ptr + lay.player_power_points) or 0,
                    skill_points=self._i32(ptr + lay.player_skill_points) or 0,
                    rank_floor=self._i32(ptr + lay.player_rank_floor) or 0,
                    rank_next=self._i32(ptr + lay.player_rank_next) or 0,
                    display_name=self._utf16(ptr + lay.player_display_name),
                    faction_name=self._faction_name(ptr),
                    spent_on_units=self._i32(ptr + lay.player_spent_on_units) or 0,
                    spent_on_structures=self._i32(ptr + lay.player_spent_on_structures) or 0,
                    spent_on_heroes=self._i32(ptr + lay.player_spent_on_heroes) or 0,
                    units_created=self._i32(ptr + lay.player_units_created) or 0,
                    units_lost=self._i32(ptr + lay.player_units_lost) or 0,
                    structures_created=self._i32(ptr + lay.player_structures_created) or 0,
                    structures_lost=self._i32(ptr + lay.player_structures_lost) or 0,
                    color=_opaque_rgb(self._u32(ptr + lay.player_color)),
                    command_points=(
                        self._i32(ptr + lay.player_command_points_used) or 0,
                        # Base plus bonus, because neither alone is the ceiling the engine
                        # checks - see the layout note on `player_command_points_bonus`.
                        (self._i32(ptr + lay.player_command_points_cap) or 0)
                        + (self._i32(ptr + lay.player_command_points_bonus) or 0),
                    ),
                    sciences=self._sciences_at(ptr),
                    upgrades=self._upgrades_at(ptr, lay.player_upgrades_completed, True),
                    upgrades_in_progress=self._upgrades_at(
                        ptr, lay.player_upgrades_in_progress, True
                    ),
                )
            )
        by_name = {player.name.lower(): player.index for player in players}
        return tuple(
            replace(
                player,
                allies=frozenset(
                    by_name[ally]
                    for ally in allied.get(player.name.lower(), ())
                    if ally in by_name and by_name[ally] != player.index
                ),
            )
            for player in players
        )

    def _alliances(self) -> dict[str, tuple[str, ...]]:
        """`{player name -> the player names it is allied with}`, lowercased, from the sides
        list - see `the_sides_list`. Empty whenever anything on the way does not decode."""
        lay = self.layout
        name_key = self._u32(lay.key_player_name)
        allies_key = self._u32(lay.key_player_allies)
        sides = self._pointer(lay.the_sides_list)
        if not name_key or not allies_key or sides is None:
            return {}
        count = self._u32(sides + lay.sl_count) or 0
        found: dict[str, tuple[str, ...]] = {}
        for index in range(min(count, lay.pl_max_players)):
            side = sides + lay.sl_sides + index * lay.sl_side_stride
            values = self._dict_strings(side + lay.side_dict, {name_key, allies_key})
            name = values.get(name_key, "")
            if name:
                found[name.lower()] = tuple(values.get(allies_key, "").lower().split())
        return found

    def _dict_strings(self, dict_address: int, keys: set[int]) -> dict[int, str]:
        """The `AsciiString` values a `Dict` holds under `keys`, by key."""
        lay = self.layout
        data = self._pointer(dict_address)
        if data is None:
            return {}
        raw_count = self.source.read(data + lay.dict_count, 2)
        count = struct.unpack("<H", raw_count)[0] if raw_count else 0
        if not (0 < count <= lay.max_dict_pairs):
            return {}
        pairs = self.source.read(data + lay.dict_pairs, count * lay.dict_pair_stride)
        if pairs is None:
            return {}
        found: dict[int, str] = {}
        for index in range(count):
            head = struct.unpack_from("<I", pairs, index * lay.dict_pair_stride)[0]
            key, kind = head >> 8, head & 0xFF
            if key in keys and kind == lay.dict_type_ascii:
                pair = data + lay.dict_pairs + index * lay.dict_pair_stride
                found[key] = self._ascii(pair + lay.dict_pair_value, 256)
        return found

    def _faction_name(self, player: int) -> str:
        """The seat's faction as the lobby named it, off its `PlayerTemplate` - see
        `player_template`."""
        template = self._pointer(player + self.layout.player_template)
        return "" if template is None else self._utf16(template + self.layout.template_faction)

    def local_player_index(self) -> int:
        lay = self.layout
        pl = self._pointer(lay.the_player_list)
        if pl is None:
            return 0
        local = self._pointer(pl + lay.pl_local_player)
        count = min(self._u32(pl + lay.pl_count) or 0, lay.pl_max_players)
        for index in range(count):
            if self._pointer(pl + lay.pl_array + index * 4) == local:
                return index
        return 0

    def _kinds_of(self, template: int) -> tuple[bool, bool, bool, bool, int]:
        """`(is hero, is spellbook, is structure, is selectable, build cost)` for a
        `ThingTemplate`, cached by address."""
        cached = self._template_kinds.get(template)
        if cached is None:
            lay = self.layout

            def flag(offset: int, bit: int) -> bool:
                raw = self.source.read(template + offset, 1)
                return bool(raw and raw[0] & bit)

            cost = self.source.read(template + lay.tmpl_build_cost, 2)
            cached = (
                flag(lay.tmpl_hero_byte, lay.tmpl_hero_bit),
                flag(lay.tmpl_spellbook_byte, lay.tmpl_spellbook_bit),
                flag(lay.tmpl_structure_byte, lay.tmpl_structure_bit),
                flag(lay.tmpl_selectable_byte, lay.tmpl_selectable_bit),
                struct.unpack("<H", cost)[0] if cost else 0,
            )
            self._template_kinds[template] = cached
        return cached

    @staticmethod
    def _template_named(registry: dict[int, str], name: str) -> int | None:
        lowered = name.lower()
        return next((ptr for ptr, known in registry.items() if known.lower() == lowered), None)

    def thing_display_name(self, name: str) -> str:
        """The in-game name of a `ThingTemplate`, or "" when it has none or cannot be read.

        Read off the template itself, which the engine localised while parsing - see
        `tmpl_display_name`.
        """
        lowered = name.lower()
        cached = self._thing_display.get(lowered)
        if cached is None:
            self.thing_order()
            template = self._template_named(self._thing_at, name)
            cached = (
                ""
                if template is None
                else self._utf16(template + self.layout.tmpl_display_name, 256)
            )
            self._thing_display[lowered] = cached
        return cached

    def upgrade_display_name(self, name: str) -> str:
        """The in-game name of an upgrade, or "" when its label does not resolve."""
        lowered = name.lower()
        cached = self._upgrade_display.get(lowered)
        if cached is None:
            self.upgrade_table()
            template = self._template_named(self._upgrade_at, name)
            label = (
                ""
                if template is None
                else self._ascii(template + self.layout.upgrade_display_label)
            )
            cached = self.game_text(label) if label else ""
            self._upgrade_display[lowered] = cached
        return cached

    def game_text(self, label: str) -> str:
        """The localised text for a string-table label, as the game would show it, or "".

        The table is indexed once - labels only, a few reads per entry - and each text is read
        when it is first asked for. Labels match case-insensitively, as the engine's do.
        """
        if self._game_text is None:
            self._game_text = self._index_game_text()
        record = self._game_text.get(label.lower())
        if record is None:
            return ""
        return self._utf16(record + self.layout.gt_record_text, 512)

    def _index_game_text(self) -> dict[str, int]:
        lay = self.layout
        found: dict[str, int] = {}
        manager = self._pointer(lay.the_game_text)
        if manager is None:
            self._diagnostics.append(Diagnostic("TheGameText is null; labels unavailable"))
            return found
        for offset in lay.gt_tables:
            table = self._pointer(manager + offset)
            if table is None:
                continue
            count = self._u32(table + lay.gt_count) or 0
            entries = self._pointer(table + lay.gt_entries)
            if entries is None or not (0 < count <= lay.max_game_text):
                continue
            raw = self.source.read(entries, count * lay.gt_entry_stride)
            if raw is None:
                continue
            for index in range(count):
                record = struct.unpack_from(
                    "<I", raw, index * lay.gt_entry_stride + lay.gt_entry_record
                )[0]
                if not (_MIN_PTR <= record <= _MAX_PTR):
                    continue
                label = self._ascii(record + lay.gt_record_label, 256)
                # The engine tries the first table before the second, so the first entry wins.
                if label:
                    found.setdefault(label.lower(), record)
        return found

    def science_display_name(self, science: int) -> str:
        """The in-game name of a science by id, or `""`. Store entries are filed under the id each
        states, not their position.
        """
        if self._science_display is None:
            self._science_display = self._index_sciences()
        return self._science_display.get(science, "")

    def _index_sciences(self) -> dict[int, str]:
        lay = self.layout
        named: dict[int, str] = {}
        store = self._pointer(lay.the_science_store)
        if store is None:
            return named
        begin = self._pointer(store + lay.sc_vector)
        end = self._u32(store + lay.sc_vector + 4)
        if begin is None or end is None or end <= begin:
            return named
        count = (end - begin) // 4
        if count > lay.max_sciences:
            return named
        raw = self.source.read(begin, count * 4)
        if raw is None:
            return named
        for (entry,) in struct.iter_unpack("<I", raw):
            if not (_MIN_PTR <= entry <= _MAX_PTR):
                continue
            own_id = self._i32(entry + lay.science_id)
            text = self._ascii(entry + lay.science_display_name, 256)
            if own_id is not None and 0 < own_id <= count and text:
                named.setdefault(own_id, text)
        return named

    def power_button_names(self, object_id: int) -> dict[str, str]:
        """`{special power name -> the in-game text of the button that fires it}` for one object's
        buttons (on a spellbook, the names its bar shows). Empty when anything fails to decode.
        """
        lay = self.layout
        address = self._object_at.get(object_id)
        if address is None:
            return {}
        command_set = self._command_set(self._command_set_name(address))
        if command_set is None:
            return {}
        raw = self.source.read(command_set + lay.cs_buttons, lay.cs_slots * 4)
        if raw is None:
            return {}
        named: dict[str, str] = {}
        for (button,) in struct.iter_unpack("<I", raw):
            if not (_MIN_PTR <= button <= _MAX_PTR):
                continue
            power = self._pointer(button + lay.button_special_power)
            if power is None:
                continue
            name = self._ascii(power + lay.power_name)
            label = self._button_label(button)
            # `&` marks the hotkey letter in a label's text; the game draws it as an underline.
            text = self.game_text(label).replace("&", "").strip() if label else ""
            if name and text:
                named.setdefault(name, text)
        return named

    def _command_set_name(self, address: int) -> str:
        lay = self.layout
        for offset in lay.obj_command_set_overrides:
            name = self._ascii(address + offset)
            if name:
                return name
        template = self._pointer(address + lay.obj_template)
        return "" if template is None else self._ascii(template + lay.tmpl_command_set)

    def _command_set(self, name: str) -> int | None:
        if not name:
            return None
        if self._command_sets is None:
            self._command_sets = self._index_command_sets()
        return self._command_sets.get(name.lower())

    def _index_command_sets(self) -> dict[str, int]:
        lay = self.layout
        found: dict[str, int] = {}
        bar = self._pointer(lay.the_control_bar)
        if bar is None:
            return found
        table = bar + lay.cb_command_sets
        begin = self._pointer(table + lay.hash_buckets)
        end = self._u32(table + lay.hash_buckets + 4)
        if begin is None or end is None or end <= begin:
            return found
        count = (end - begin) // 4
        raw = self.source.read(begin, count * 4) if count <= lay.max_hash_buckets else None
        if raw is None:
            return found
        for (node,) in struct.iter_unpack("<I", raw):
            seen: set[int] = set()
            while _MIN_PTR <= node <= _MAX_PTR and node not in seen:
                if len(found) >= lay.max_command_sets:
                    return found
                seen.add(node)
                name = self._ascii(node + lay.hash_node_key)
                value = self._pointer(node + lay.hash_node_value)
                if name and value is not None:
                    found.setdefault(name.lower(), value)
                node = self._u32(node + lay.hash_node_next) or 0
        return found

    def _button_label(self, button: int) -> str:
        lay = self.layout
        override = self._ascii(button + lay.button_label_override)
        if override:
            return override
        begin = self._pointer(button + lay.button_labels)
        end = self._u32(button + lay.button_labels + 4)
        if begin is None or end is None or end <= begin:
            return ""
        count = (end - begin) // 4
        wanted = self._u32(button + lay.button_label_range) or 0
        return self._ascii(begin + min(wanted, count - 1) * 4)

    def special_powers(self, object_id: int) -> tuple[SpecialPowerState, ...]:
        """Every special power on one object, with its recharge and the sciences it requires.

        The same module walk as `power_cooldowns`, which keeps its `{name -> frame}` shape for
        the callers that only want that; see it for why the recharge is read, not computed.
        """
        lay = self.layout
        address = self._object_at.get(object_id)
        modules = None if address is None else self._pointer(address + lay.obj_modules)
        if modules is None:
            return ()
        found: list[SpecialPowerState] = []
        for index in range(lay.max_modules):
            module = self._pointer(modules + index * 4)
            if module is None:
                break
            data = self._pointer(module + lay.module_data)
            template = None if data is None else self._pointer(data + lay.module_data_template)
            if template is None:
                continue
            name = self._ascii(template + lay.power_name)
            ready = self._i32(module + lay.module_ready_frame)
            if name and ready is not None:
                found.append(SpecialPowerState(name, ready, self._required_sciences(template)))
        return tuple(found)

    def _required_sciences(self, template: int) -> frozenset[int]:
        lay = self.layout
        begin = self._pointer(template + lay.power_required_sciences)
        end = self._u32(template + lay.power_required_sciences + 4)
        if begin is None or end is None or end <= begin:
            return frozenset()
        count = (end - begin) // 4
        if count > lay.max_power_sciences:
            return frozenset()
        raw = self.source.read(begin, count * 4)
        return frozenset() if raw is None else frozenset(struct.unpack(f"<{count}i", raw))

    def power_cooldowns(self, object_id: int) -> dict[str, int]:
        """`{power name -> the frame it is next usable on}` for one object's special powers.

        The engine's own cooldown, which is shorter than the ini's `ReloadTime` once a mod's
        discounts apply, and survives a consumer restarting. Works on a spellbook or a hero. The id
        must come from the last `read_objects` walk, since ids are reused.
        """
        lay = self.layout
        address = self._object_at.get(object_id)
        if address is None:
            return {}
        modules = self._pointer(address + lay.obj_modules)
        if modules is None:
            return {}
        found: dict[str, int] = {}
        for index in range(lay.max_modules):
            module = self._pointer(modules + index * 4)
            if module is None:
                # A NULL terminates the list, which is what bounds this walk in practice.
                break
            data = self._pointer(module + lay.module_data)
            if data is None:
                continue
            template = self._pointer(data + lay.module_data_template)
            if template is None:
                # Not a special-power module: every other module family leaves this unset, and
                # the engine's own recharge path bails on exactly this test.
                continue
            name = self._ascii(template + lay.power_name)
            ready = self._i32(module + lay.module_ready_frame)
            if name and ready is not None:
                found[name] = ready
        return found

    def read_objects(self) -> tuple[GameObject, ...]:
        lay = self.layout
        gl = self._pointer(lay.the_game_logic)
        if gl is None:
            self._diagnostics.append(Diagnostic("TheGameLogic is null"))
            return ()
        begin = self._pointer(gl + lay.gl_table_begin)
        end = self._u32(gl + lay.gl_table_end)
        if begin is None or end is None or end <= begin:
            self._diagnostics.append(Diagnostic("object table bounds are unreadable"))
            return ()
        slots = (end - begin) // 4
        if slots > _MAX_TABLE_SLOTS:
            self._diagnostics.append(Diagnostic(f"implausible object table of {slots} slots"))
            return ()

        raw = self.source.read(begin, slots * 4)
        if raw is None:
            self._diagnostics.append(Diagnostic("object table is unreadable"))
            return ()

        # Two passes: ids live on the table entry but horde links point at the Object, so a
        # parent's id is only knowable once every object pointer has been indexed.
        entries: list[tuple[int, int]] = []
        id_of: dict[int, int] = {}
        for entry_ptr in struct.unpack(f"<{slots}I", raw):
            if not (_MIN_PTR <= entry_ptr <= _MAX_PTR):
                continue
            # The id and the object pointer are adjacent, so one read serves both.
            head = self.source.read(entry_ptr + lay.entry_id, lay.entry_object - lay.entry_id + 4)
            if head is None:
                continue
            object_id, obj_ptr = struct.unpack_from("<II", head)
            if not (_MIN_PTR <= obj_ptr <= _MAX_PTR):
                continue
            entries.append((entry_ptr, obj_ptr))
            id_of[obj_ptr] = object_id
            # The inverse, kept for the walks that start from an id rather than from the table -
            # `power_cooldowns` is one. Free here and a 12,289-slot scan anywhere else.
            self._object_at[object_id] = obj_ptr

        owner_of = self._team_owners()
        objects: list[GameObject] = []
        for entry_ptr, obj_ptr in entries:
            obj = self._read_object(entry_ptr, obj_ptr, id_of, owner_of)
            if obj is not None:
                objects.append(obj)
        return tuple(objects)

    def _team_owners(self) -> dict[int, int]:
        """`{Team* -> player index}`, seeded from each player's default team (a `Team` has no
        pointer back to its `Player`). `_owner_of_team` adds the rest on demand.
        """
        lay = self.layout
        self._players_by_pointer = {}
        self._teams_unresolved = set()
        pl = self._pointer(lay.the_player_list)
        if pl is None:
            return {}
        count = min(self._u32(pl + lay.pl_count) or 0, lay.pl_max_players)
        owners: dict[int, int] = {}
        for index in range(count):
            player = self._pointer(pl + lay.pl_array + index * 4)
            if player is None:
                continue
            self._players_by_pointer[player] = index
            team = self._pointer(player + lay.player_default_team)
            if team is not None:
                owners.setdefault(team, index)
        return owners

    def _owner_of_team(self, team: int, owners: dict[int, int]) -> int | None:
        """The player index owning `team`, through its prototype when it is not a default team.

        Players own extra teams (a superweapon's summons arrive on one). The route is `Team+0x30 ->
        TeamPrototype`, `+0x08 -> Player`, checked against every default team. Memoised into
        `owners`; None when the chain breaks.
        """
        known = owners.get(team)
        if known is not None:
            return known
        # **Both misses are memoised, and that is what keeps this off the per-object budget.**
        # An object costs three reads; walking the prototype for every one of them would add two
        # more, and a team that does not resolve would pay them again on the next object and the
        # next. A null team never resolves and is answered without reading anything at all.
        if not team or team in self._teams_unresolved:
            return None
        proto = self._pointer(team + self.layout.team_proto)
        player = self._pointer(proto + self.layout.proto_owner) if proto else None
        index = self._players_by_pointer.get(player) if player else None
        if index is None:
            self._teams_unresolved.add(team)
        else:
            owners[team] = index
        return index

    def _body_values(self, body: int) -> tuple[float | None, float | None]:
        """Current and maximum hit points in one read, falling back to one read per field."""
        lay = self.layout
        span = lay.body_max_health - lay.body_health + 4
        raw = self.source.read(body + lay.body_health, span)
        if raw is not None and len(raw) >= span:
            return (
                float(struct.unpack_from("<f", raw, 0)[0]),
                float(struct.unpack_from("<f", raw, span - 4)[0]),
            )
        return self._f32(body + lay.body_health), self._f32(body + lay.body_max_health)

    def _template_info(self, template: int) -> tuple[str, str] | None:
        """`(name, Side)` for a `ThingTemplate`, cached by address. None when the pointer does not
        land on a template (the name is not a single identifier).
        """
        cached = self._template_at.get(template)
        if cached is None:
            name = self._ascii(template + self.layout.tmpl_name)
            if not name or " " in name or "." in name:
                self._template_at[template] = ("", "")
                return None
            cached = (name, self._ascii(template + self.layout.tmpl_side))
            self._template_at[template] = cached
        return cached if cached[0] else None

    def _read_object(
        self, entry_ptr: int, obj_ptr: int, id_of: dict[int, int], owner_of: dict[int, int]
    ) -> GameObject | None:
        lay = self.layout
        # One read for the whole header instead of a dozen. The fallback is not defensive
        # decoration: an object whose header straddles into an unmapped page fails the wide
        # read and reads perfectly well field by field, and a recorded snapshot only holds the
        # ranges its capture touched.
        blob = self.source.read(obj_ptr, lay.obj_span)

        def u32(offset: int) -> int | None:
            if blob is not None:
                return int(struct.unpack_from("<I", blob, offset)[0])
            return self._u32(obj_ptr + offset)

        def f32(offset: int) -> float:
            if blob is not None:
                return float(struct.unpack_from("<f", blob, offset)[0])
            return self._f32(obj_ptr + offset) or 0.0

        def pointer(offset: int) -> int | None:
            value = u32(offset)
            return value if value is not None and _MIN_PTR <= value <= _MAX_PTR else None

        template = pointer(lay.obj_template)
        if template is None:
            return None
        named = self._template_info(template)
        if named is None:
            return None
        name, side = named

        # Not every object has a body: inert map markers (wall hubs, farm spots) carry a
        # pointer at this offset whose contents are uninitialised, reading as denormal
        # floats. A body is only believed when its maximum is a plausible hit-point figure,
        # so max_health == 0 means "no body", not "dead".
        health, max_health = 1.0, 0.0
        body = pointer(lay.obj_body)
        if body is not None:
            current, maximum = self._body_values(body)
            if current is not None and maximum is not None and maximum >= 1.0 and current >= 0.0:
                health = max(0.0, min(1.0, current / maximum))
                max_health = maximum

        upgrades = self._upgrades_at(obj_ptr, lay.obj_upgrades_completed, False, blob=blob)
        is_hero, is_spellbook, is_structure, is_selectable, build_cost = self._kinds_of(template)
        experience: float | None = None
        experience_level: int | None = None
        tracker = pointer(lay.obj_experience_tracker) if is_hero else None
        if tracker is not None:
            points = self._f32(tracker + lay.xt_experience)
            level = self._i32(tracker + lay.xt_level)
            if points is not None and math.isfinite(points) and points >= 0.0:
                experience = points
            if level is not None and 0 <= level <= 100:
                experience_level = level
        return GameObject(
            object_id=id_of.get(obj_ptr, 0),
            template_name=name,
            template_side=side,
            position=(f32(lay.obj_pos_x), f32(lay.obj_pos_y), f32(lay.obj_pos_z)),
            angle=math.atan2(f32(lay.obj_sin), f32(lay.obj_cos)),
            health=health,
            max_health=max_health,
            owner_index=self._owner_of_team(pointer(lay.obj_team) or 0, owner_of),
            # Object-scoped only. A structure or battalion upgrade is recorded nowhere else -
            # not in the template name, not on the player - so without this an upgrade the
            # policy paid for is indistinguishable from one it never bought.
            upgrades=upgrades,
            conditions=self._flags_at(
                blob,
                obj_ptr,
                lay.obj_model_conditions,
                lay.model_condition_words,
                self.model_condition_names(),
            ),
            status=self._flags_at(
                blob, obj_ptr, lay.obj_status, lay.status_words, self.object_status_names()
            ),
            # The container this object is inside, resolved through the address->id map the
            # first pass built. `None` when it stands alone, which is why the walk is two-pass:
            # the pointer names an `Object`, and only the table knows that object's id.
            parent_id=id_of.get(pointer(lay.obj_contained_by) or 0),
            # An id, not a pointer, so it needs no map - and unlike `parent_id` it is not
            # cleared when the object leaves what it names. A stale one is the point: it is how
            # the engine still finds a horde for a unit that is no longer in it.
            producer_id=u32(lay.obj_producer_id) or None,
            construction_percent=_construction_percent(f32(lay.obj_construction_percent)),
            is_hero=is_hero,
            is_spellbook=is_spellbook,
            is_structure=is_structure,
            is_selectable=is_selectable,
            build_cost=build_cost,
            experience=experience,
            experience_level=experience_level,
            production=(
                self._read_production(obj_ptr, template, pointer(lay.obj_modules))
                if self.read_production
                else ()
            ),
        )

    @property
    def alive(self) -> bool:
        """Whether the process is still there, by the cheapest read that proves it.

        `TheGameLogic` is a static inside the mapped image, so the read succeeds for as long
        as the process does - whatever value it holds.
        """
        return self._u32(self.layout.the_game_logic) is not None

    def _game_logic(self) -> int | None:
        """The `GameLogic` pointer, telling a dead process (the read fails) apart from a null global
        (a match that ended).
        """
        value = self._u32(self.layout.the_game_logic)
        if value is None:
            raise GameExited(
                f"the game is gone: reading TheGameLogic at "
                f"{self.layout.the_game_logic:#010x} failed. The process exited, crashed, or "
                "the handle was closed - this is not a match that ended"
            )
        return value if _MIN_PTR <= value <= _MAX_PTR else None

    def _production_module(self, array: int) -> tuple[int | None, bool]:
        """The `ProductionUpdate` in an object's module array, matched by vtable, and whether the
        walk was conclusive (only a conclusive "not there" may be cached per template).
        """
        lay = self.layout
        raw = self.source.read(array, lay.production_scan * 4)
        if raw is None:
            return None, False
        for module in struct.unpack(f"<{lay.production_scan}I", raw):
            if module == 0:  # the terminator: the list really does end without one
                return None, True
            if not (_MIN_PTR <= module <= _MAX_PTR):
                return None, False
            vtable = self._u32(module)
            if vtable is None:
                return None, False
            if vtable == lay.production_update_vtable:
                return module, True
        return None, True

    def _read_production(
        self, obj_ptr: int, template: int, array: int | None
    ) -> tuple[ProductionItem, ...]:
        """What this object is making, in queue order; empty for most objects.

        Names resolve by pointer identity against the thing and upgrade registries; an unknown entry
        has an empty name. Templates known to have no production module skip the walk.
        """
        lay = self.layout
        if array is None or self._template_produces.get(template) is False:
            return ()
        module, conclusive = self._production_module(array)
        if module is None:
            if conclusive:
                self._template_produces[template] = False
            return ()
        self._template_produces[template] = True
        # The module names its owner. If this disagrees, the module array was not what we
        # thought it was, and everything read past here would be fiction.
        if self._pointer(module + lay.module_object) != obj_ptr:
            self._diagnostics.append(
                Diagnostic(
                    f"a ProductionUpdate at {module:#x} does not point back at the object "
                    f"{obj_ptr:#x} it was reached from; the module list layout is wrong"
                )
            )
            return ()

        items: list[ProductionItem] = []
        node = self._pointer(module + lay.production_head)
        seen: set[int] = set()
        while node is not None and node not in seen and len(items) < lay.max_queue:
            seen.add(node)
            kind = self._i32(node + lay.entry_kind)
            percent = _clamp_percent(self._f32(node + lay.entry_percent))
            if kind == 2:
                # Both registry walks are cached and are triggered here rather than up front,
                # so an observation of a game where nothing is producing never pays for them.
                self.upgrade_table()
                name = self._upgrade_at.get(self._u32(node + lay.entry_upgrade) or 0, "")
                items.append(ProductionItem("upgrade", name, percent))
            elif kind in (1, 3):
                self.thing_order()
                name = self._thing_at.get(self._u32(node + lay.entry_template) or 0, "")
                items.append(ProductionItem("unit" if kind == 1 else "revive", name, percent))
            else:
                items.append(ProductionItem("unknown"))
            node = self._pointer(node + lay.entry_next)

        declared = self._u32(module + lay.production_count)
        if declared is not None and declared != len(items):
            self._diagnostics.append(
                Diagnostic(
                    f"walked {len(items)} production entries but the module counts {declared}"
                )
            )
        return tuple(items)

    def frame(self) -> int:
        gl = self._game_logic()
        if gl is None:
            return 0
        return self._u32(gl + self.layout.gl_frame) or 0

    def desync_declared(self) -> bool | None:
        """Has this client declared itself out of sync? None when the byte cannot be read, which a
        watcher must not treat as "in sync".
        """
        gl = self._game_logic()
        if gl is None:
            return None
        raw = self.source.read(gl + self.layout.gl_desync_declared, 1)
        return None if raw is None else raw[0] != 0

    def read_shroud(self, players: Sequence[int]) -> ShroudGrid | None:
        """The visibility grid for `players`, or None (the ordinary answer at the menu)."""
        lay = self.layout
        return read_shroud(
            self._u32,
            self._f32,
            self.source.read,
            lay.the_shroud_manager,
            lay.shroud_impl,
            {
                "origin_x": lay.shroud_origin_x,
                "origin_y": lay.shroud_origin_y,
                "cell_size": lay.shroud_cell_size,
                "inv_cell_size": lay.shroud_inv_cell_size,
                "cells_x": lay.shroud_cells_x,
                "cells_y": lay.shroud_cells_y,
                "cells": lay.shroud_cells,
                "fog_enabled": lay.shroud_fog_enabled,
            },
            players,
        )

    def observe(self) -> Observation:
        # Ordered so the liveness check runs before anything can quietly default.
        self._game_logic()
        players = self.read_players()
        # Every seat, not just the local one: `under_fog` takes a viewer, and a caller checking
        # what an *opponent* can see is exactly how you tell a working filter from one that
        # happens to hide everything. A seat costs one `u16` per cell, ~21 KB on a 104x104 map.
        return Observation(
            frame=self.frame(),
            local_player=self.local_player_index(),
            players=players,
            objects=self.read_objects(),
            # False because `objects` is still the whole map. The grid rides along so a consumer
            # can apply the filter; `under_fog` is what sets this True.
            fogged=False,
            shroud=self.read_shroud([p.index for p in players]),
        )

    def poll(self) -> Observation | None:
        if not self._connected:
            self._diagnostics.append(Diagnostic("poll before connect"))
            return None
        self._latest = self.observe()
        return self._latest

    def step(self, timeout: float | None = None) -> Observation | None:
        """Wait for the logic frame to advance, then observe. It watches the frame counter; it does
        not hold the engine.
        """
        if not self._connected:
            self._diagnostics.append(Diagnostic("step before connect"))
            return None
        start_frame = self.frame()
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.frame() == start_frame:
            if deadline is not None and time.monotonic() >= deadline:
                return None
            time.sleep(0.001)
        return self.poll()

    def send(self, orders: Sequence[Order]) -> int:
        if orders:
            self._diagnostics.append(
                Diagnostic(
                    "MemoryBackend is observation-only; issuing orders needs a bridge "
                    "running inside the game"
                )
            )
        return 0
