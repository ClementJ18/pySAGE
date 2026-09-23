"""The client: control bar, palantir, tooltips, APT menus, hotkeys, camera and selection."""

from __future__ import annotations

from sage_patch.addresses.logic import MAP_META_DATA_ASSIGN
from sage_patch.addresses.objects import OBJECT_IMAGE_UPGRADE_FIND_IMAGE

__all__ = [
    "APT_INIT_GADGETS_EPILOGUE",
    "APT_INIT_GADGETS_LADDER",
    "APT_INIT_GADGETS_LADDER_BYTES",
    "APT_INIT_GADGETS_LADDER_HOOK",
    "APT_INIT_GADGETS_LADDER_HOOK_BYTES",
    "APT_INIT_GADGETS_RESOLUTION_ARM",
    "APT_OPTIONS_SAVE",
    "APT_OPTIONS_SAVE_BYTES",
    "APT_OPTIONS_SAVE_FLUSH",
    "APT_OPTIONS_SAVE_FLUSH_BYTES",
    "APT_OPTIONS_SAVE_MAP_EBP",
    "APT_OPTIONS_SAVE_PREFS_EBP",
    "APT_OPTIONS_SAVE_RESUME",
    "APT_PLAYER_MODE",
    "AUDIO_MANAGER",
    "AUDIO_STOP_SLOT",
    "BATTLE_SCHOOL_BLINK_REGISTRATION",
    "BATTLE_SCHOOL_BLINK_REGISTRATION_BYTES",
    "BATTLE_SCHOOL_COMMAND",
    "BATTLE_SCHOOL_HANDLER",
    "BATTLE_SCHOOL_HANDLER_BYTES",
    "BATTLE_SCHOOL_REGISTRATION",
    "BATTLE_SCHOOL_REGISTRATION_BYTES",
    "BATTLE_SCHOOL_TRANSITION_NAME",
    "CONTROL_BAR_AVAILABILITY_OK_HIGH",
    "CONTROL_BAR_AVAILABILITY_OK_LOW",
    "CONTROL_BAR_AVAILABILITY_TEST",
    "CONTROL_BAR_CLICK_ARGUMENT_BUILD",
    "CONTROL_BAR_CLICK_ARGUMENT_BUILD_BYTES",
    "CONTROL_BAR_CLICK_BUTTON_LOAD",
    "CONTROL_BAR_CLICK_BUTTON_LOAD_BYTES",
    "CONTROL_BAR_CLICK_GATE_CALL",
    "CONTROL_BAR_CLICK_GATE_CALL_BYTES",
    "CONTROL_BAR_CLICK_GATE_PREFIX",
    "CONTROL_BAR_CLICK_GATE_PREFIX_BYTES",
    "CONTROL_BAR_CLICK_GATE_SUFFIX",
    "CONTROL_BAR_CLICK_GATE_SUFFIX_BYTES",
    "CONTROL_BAR_COMMAND_DISPATCH",
    "CONTROL_BAR_COMMAND_DISPATCH_BYTES",
    "CONTROL_BAR_COMMAND_INDEX_TABLE",
    "CONTROL_BAR_COMMAND_JUMP_TABLE",
    "CONTROL_BAR_DO_COMMAND",
    "CONTROL_BAR_GET_COMMAND_AVAILABILITY",
    "CONTROL_BAR_GET_VISIBLE_RANGE",
    "CONTROL_BAR_MAX_VISIBLE",
    "CONTROL_BAR_MERGE_CLEAR_SLOTS",
    "CONTROL_BAR_MERGE_HIDE",
    "CONTROL_BAR_MERGE_INSTALL",
    "CONTROL_BAR_MERGE_INSTALL_FIRST",
    "CONTROL_BAR_MERGE_INSTALL_FIRST_BYTES",
    "CONTROL_BAR_MERGE_INSTALL_FIRST_RESUME",
    "CONTROL_BAR_MERGE_KEEP",
    "CONTROL_BAR_MERGE_OBJECT_EBP",
    "CONTROL_BAR_MERGE_RESET",
    "CONTROL_BAR_MERGE_RESET_BYTES",
    "CONTROL_BAR_MERGE_SLOT",
    "CONTROL_BAR_MERGE_SLOT_BYTES",
    "CONTROL_BAR_MERGE_SLOT_EBP",
    "CONTROL_BAR_POPULATE_MULTI_SELECT",
    "CONTROL_BAR_POP_RANGE_HANDLER",
    "CONTROL_BAR_POP_RANGE_HANDLER_BYTES",
    "CONTROL_BAR_PROCESS_COMMAND_UI",
    "CONTROL_BAR_PUSH_RANGE_HANDLER",
    "CONTROL_BAR_PUSH_RANGE_HANDLER_BYTES",
    "CONTROL_BAR_RANGE_COUNT_EBP",
    "CONTROL_BAR_RANGE_FETCH",
    "CONTROL_BAR_RANGE_FETCH_BYTES",
    "CONTROL_BAR_RANGE_FETCH_RESUME",
    "CONTROL_BAR_RANGE_LOOP_CAPPED",
    "CONTROL_BAR_RANGE_LOOP_PRODUCTION",
    "CONTROL_BAR_RANGE_LOOP_PRODUCTION_BYTES",
    "CONTROL_BAR_RANGE_LOOP_REVIVE",
    "CONTROL_BAR_RANGE_LOOP_REVIVE_BYTES",
    "CONTROL_BAR_RANGE_START_EBP",
    "CONTROL_BAR_UNAVAILABLE",
    "CONTROL_BAR_UNIT_COST_CALL",
    "CONTROL_BAR_UNIT_COST_CALL_BYTES",
    "CREDITS_EXIT_AUDIO_TAIL",
    "CREDITS_EXIT_AUDIO_TAIL_BYTES",
    "CREDITS_EXIT_HANDLER",
    "DESCRIPTION_BLOCKED_ASSIGN",
    "DESCRIPTION_BLOCKED_ASSIGN_BYTES",
    "DESCRIPTION_BLOCKED_RESUME",
    "DESCRIPTION_BLOCKED_RUN",
    "DESCRIPTION_BLOCKED_RUN_BYTES",
    "DESCRIPTION_BUFFER_EBP_OFFSET",
    "DESCRIPTION_BUTTON_CAPTURE",
    "DESCRIPTION_BUTTON_CAPTURE_BYTES",
    "DESCRIPTION_BUTTON_CAPTURE_RESUME",
    "DESCRIPTION_DONE",
    "DESCRIPTION_LINE_EBP_OFFSET",
    "DESCRIPTION_OBJECT_EBP_OFFSET",
    "DESCRIPTION_PLAYER_EBP_OFFSET",
    "DESCRIPTION_PURCHASED_ASSIGN",
    "DESCRIPTION_PURCHASED_ASSIGN_BYTES",
    "DESCRIPTION_PURCHASED_RESUME",
    "DESCRIPTION_PURCHASED_RUN",
    "DESCRIPTION_PURCHASED_RUN_BYTES",
    "DESCRIPTION_RANK_APPEND",
    "DESCRIPTION_RANK_APPEND_BYTES",
    "DESCRIPTION_RANK_RESUME",
    "DESCRIPTION_SPECIAL_POWER_CASE",
    "DESCRIPTION_SPECIAL_POWER_CASE_BYTES",
    "DESCRIPTION_TAIL",
    "DESCRIPTION_TAIL_BYTES",
    "DESCRIPTION_TAIL_RESUME",
    "DESCRIPTION_TEXT_EBP_OFFSET",
    "DESCRIPTION_UNIT_COST_BODY",
    "GET_CHECKBOX_STATE",
    "GUICOMMAND_POP_VISIBLE_COMMAND_RANGE",
    "GUICOMMAND_PUSH_VISIBLE_COMMAND_RANGE",
    "GUICOMMAND_REVIVE",
    "GUI_COMMAND_SPECIAL_POWER",
    "GUI_LOSE_CASH",
    "HOT_KEY_EXECUTE",
    "HOT_KEY_EXECUTE_FLAG_EBP",
    "HOT_KEY_EXECUTE_HIT",
    "HOT_KEY_EXECUTE_HOOK",
    "HOT_KEY_EXECUTE_HOOK_BYTES",
    "HOT_KEY_EXECUTE_KEY_EBP",
    "HOT_KEY_EXECUTE_MISS",
    "HOT_KEY_EXECUTE_RESUME",
    "HOT_KEY_MANAGER_HOTKEY_FROM_LABEL",
    "HOT_KEY_TRANSLATOR_FLAG_EBP",
    "HOT_KEY_TRANSLATOR_MODIFIER_GATE",
    "HOT_KEY_TRANSLATOR_MODIFIER_GATE_BYTES",
    "HOT_KEY_TRANSLATOR_PROCEED",
    "HOT_KEY_TRANSLATOR_REJECT",
    "IN_GAME_UI_ADD_FLOATING_TEXT",
    "LOSE_CASH_COLOR",
    "LOSE_CASH_RISE",
    "MAIN_MENU_BLINK_FLAG",
    "MAIN_MENU_CAMPAIGN_COMMAND",
    "MAIN_MENU_CAMPAIGN_HANDLER",
    "MAIN_MENU_CAMPAIGN_HANDLER_BYTES",
    "MAIN_MENU_CAMPAIGN_REGISTRATION",
    "MAIN_MENU_CAMPAIGN_REGISTRATION_BYTES",
    "MAIN_MENU_CAMPAIGN_SELECTION_ID",
    "MAIN_MENU_PHASE_LEAVING",
    "MAIN_MENU_SCREEN_DIFFICULTY",
    "MAIN_MENU_SCREEN_PHASE",
    "MAIN_MENU_SCREEN_SELECTION",
    "MAP_LIST_ANCHORS",
    "MAP_LIST_COMPARE_KEY",
    "MAP_LIST_COMPARE_KEY_BYTES",
    "MAP_LIST_COMPARE_KEY_RESUME",
    "MAP_LIST_ICON_LADDER",
    "MAP_LIST_ICON_LADDER_BYTES",
    "MAP_LIST_ICON_LADDER_RESUME",
    "MAP_LIST_OFFICIAL_BIT",
    "MAP_LIST_OFFICIAL_BIT_BYTES",
    "MAP_LIST_OFFICIAL_BIT_RESUME",
    "MAP_LIST_RESOLVE",
    "MAP_LIST_RESOLVE_BYTES",
    "MAP_LIST_RESOLVE_RESUME",
    "MAP_LIST_ROW_ADD",
    "MAP_LIST_SAVE_KEY",
    "MAP_LIST_SAVE_KEY_BYTES",
    "MAP_LIST_SAVE_KEY_RESUME",
    "MISSION_OBJECTIVE_LIST_OFFSET",
    "MISSION_OBJECTIVE_TRACKER",
    "MODEL_FIELD_PARSER",
    "MODEL_FIELD_PARSER_BYTES",
    "MODEL_FIELD_STORE",
    "MODEL_FIELD_STORE_BYTES",
    "MODEL_FIELD_STORE_RESUME",
    "MODEL_FIELD_TABLE_ROW",
    "MP_SETUP_DISABLED_FACTION_PUSH",
    "MP_SETUP_DISABLED_FACTION_PUSH_BYTES",
    "MP_SETUP_FACTION_COMBO",
    "MP_SETUP_FACTION_COMBO_BYTES",
    "MP_SETUP_FACTION_COMBO_SLOT_ARG",
    "MP_SETUP_FACTION_COMBO_SLOT_ARG_BYTES",
    "MP_SETUP_FACTION_COMBO_SLOT_WINDOW",
    "MP_SETUP_FACTION_COMBO_SLOT_WINDOW_BYTES",
    "MP_SETUP_HISTORICAL_FIXUP",
    "MP_SETUP_HISTORICAL_FIXUP_BYTES",
    "MP_SETUP_RANDOM_LOOP_INIT",
    "MP_SETUP_RANDOM_LOOP_INIT_BYTES",
    "MP_SETUP_START_GATE_LOOP_INIT",
    "MP_SETUP_START_GATE_LOOP_INIT_BYTES",
    "MP_SETUP_VALIDATE_LOOP_INIT",
    "MP_SETUP_VALIDATE_LOOP_INIT_BYTES",
    "OBSERVER_BAR_GATE_CALL",
    "OBSERVER_BAR_GATE_CALL_BYTES",
    "OBSERVER_BAR_GATE_FINGERPRINT",
    "OBSERVER_BAR_GATE_FINGERPRINT_BYTES",
    "OBSERVER_BAR_HIDE",
    "OBSERVER_BAR_SHOW",
    "OPTION_PREFERENCES_CTOR",
    "OPTION_PREFERENCES_CTOR_BYTES",
    "OPTION_PREFERENCES_DTOR",
    "OPTION_PREFERENCES_DTOR_BYTES",
    "OPTION_PREFERENCES_GET_BOOL",
    "OPTION_PREFERENCES_GET_BOOL_BYTES",
    "PALANTIR_BUTTON_ROUTE_CALL",
    "PALANTIR_BUTTON_ROUTE_CALL_BYTES",
    "PALANTIR_BUTTON_STATUS_CALL",
    "PALANTIR_BUTTON_STATUS_CALL_BYTES",
    "PALANTIR_BUTTON_TRIBUTE_CALL",
    "PALANTIR_BUTTON_TRIBUTE_CALL_BYTES",
    "PALANTIR_HOTKEY_ROUTE_CALL",
    "PALANTIR_HOTKEY_ROUTE_CALL_BYTES",
    "PALANTIR_HOTKEY_STATUS_CALL",
    "PALANTIR_HOTKEY_STATUS_CALL_BYTES",
    "PALANTIR_HOTKEY_TRIBUTE_CALL",
    "PALANTIR_HOTKEY_TRIBUTE_CALL_BYTES",
    "PALANTIR_OBJECTIVES_PUSH",
    "PALANTIR_OBJECTIVES_PUSH_BYTES",
    "PALANTIR_OPEN_STATUS_SCREEN",
    "PALANTIR_OPEN_TRIBUTE_SCREEN",
    "PALANTIR_PLAYER_STATUS_PUSH",
    "PALANTIR_PLAYER_STATUS_PUSH_BYTES",
    "PALANTIR_RESOURCES",
    "PALANTIR_RESOURCES_BYTES",
    "PALANTIR_RESOURCES_CACHE",
    "PALANTIR_RESOURCES_CACHE_BYTES",
    "PALANTIR_RESOURCES_CACHE_PUSH",
    "PALANTIR_RESOURCES_CACHE_SKIP",
    "PALANTIR_RESOURCES_DONE",
    "PALANTIR_RESOURCES_RESUME",
    "PALANTIR_RESOURCE_MULTIPLIER",
    "PALANTIR_RESOURCE_MULTIPLIER_BYTES",
    "PALANTIR_RESOURCE_MULTIPLIER_RESUME",
    "PALANTIR_SCREEN_CHOICE_CALL",
    "PALANTIR_SCREEN_CHOICE_CALL_BYTES",
    "PREFERENCES_MAP_FIND",
    "PREFERENCES_MAP_INDEX",
    "SELECTION_DETAILS_TRAY_HAS_CONTENT",
    "SELECTION_DETAILS_TRAY_OPEN",
    "SELECTION_DETAILS_TRAY_OPEN_BYTES",
    "SELECTION_DETAILS_TRAY_OPEN_RESUME",
    "SELECTION_DETAILS_TRAY_OPEN_SLOT",
    "SELECTION_DETAILS_TRAY_OPEN_THUNK",
    "SELECTION_DETAILS_TRAY_OPEN_THUNK_BYTES",
    "SELECTION_DETAILS_TRAY_REFRESH_TEST",
    "SELECTION_DETAILS_TRAY_REFRESH_TEST_BYTES",
    "SELECTION_DETAILS_TRAY_SET_HAS_CONTENT",
    "SELECTION_DETAILS_TRAY_SET_HAS_CONTENT_BYTES",
    "SELECTION_DETAILS_TRAY_SET_HAS_CONTENT_RESUME",
    "SELECTION_DETAILS_TRAY_SET_HAS_CONTENT_SLOT",
    "SELECTION_DETAILS_TRAY_STATE",
    "SELECTION_DETAILS_TRAY_VTABLE",
    "SET_CHECKBOX_STATE",
    "SHELL",
    "SHELL_MOVIE_ACTIVE",
    "SHELL_MUSIC_PLAYING",
    "SHELL_MUSIC_PLAYING_BYTES",
    "SHELL_PLAY_MUSIC",
    "SHELL_PLAY_MUSIC_BYTES",
    "THE_APT_PLAYER",
    "THE_GAME_TEXT",
    "THE_HOT_KEY_MANAGER",
    "THE_IN_GAME_UI",
    "THE_TACTICAL_VIEW",
    "TOOLTIP_COST_BUILD",
    "TOOLTIP_COST_BUILD_RESUME",
    "TOOLTIP_COST_BYTES",
    "TOOLTIP_COST_REVIVE",
    "TOOLTIP_COST_REVIVE_RESUME",
    "UNICODE_STRING_APPEND",
    "UNICODE_STRING_APPEND_BYTES",
    "UNICODE_STRING_ASSIGN",
    "UNICODE_STRING_ASSIGN_BYTES",
    "UNICODE_STRING_CONCAT",
    "UNICODE_STRING_CONCAT_WIDE",
    "UNICODE_STRING_CONCAT_WIDE_BYTES",
    "UNICODE_STRING_DTOR",
    "UNICODE_STRING_FORMAT",
    "UNICODE_STRING_FROM_WIDE",
    "USER_PREFERENCES_WRITE",
    "VIEW_GET_LOCATION_VTABLE_SLOT",
    "VIEW_LOCATION_SIZE",
    "VIEW_POSITION_OFFSET",
    "VIEW_SET_LOCATION_VTABLE_SLOT",
    "WINDOW_TRANSITIONS_HANDLER",
    "WINDOW_TRANSITION_REVERSE",
    "WINDOW_TRANSITION_REVERSE_BYTES",
    "WINDOW_TRANSITION_SET_GROUP",
]

THE_IN_GAME_UI = 0x00DE4830
#: The button-description builder's special-power case (`cmp ecx, 0x18`), which appends the
#: `UnitCost` line: `_CASE` is the guard, `_BODY` just past it, `_DONE` where the case exits.
DESCRIPTION_SPECIAL_POWER_CASE = 0x00808675
DESCRIPTION_SPECIAL_POWER_CASE_BYTES = bytes.fromhex("83f9187530")
DESCRIPTION_UNIT_COST_BODY = 0x0080867A
DESCRIPTION_DONE = 0x008086AA
#: The builder's hero recruit case, where its rank line is folded into the description - the last
#: moment another line can join it. `esi` is the hero's template; `edi` is zero throughout.
DESCRIPTION_RANK_APPEND = 0x008085C4
DESCRIPTION_RANK_APPEND_BYTES = bytes.fromhex("8d4de8e832e0bfff")
DESCRIPTION_RANK_RESUME = 0x008085CC
#: `UnicodeString::concat(other)` - `__thiscall`, one stack argument, `ret 4`.
UNICODE_STRING_APPEND = 0x004065FE
UNICODE_STRING_APPEND_BYTES = bytes.fromhex("8b4424048b0085c074060fb7")
#: `UnicodeString::concat(const WideChar *)` - `__thiscall`, one stack argument, `ret 4`. The
#: sibling of `UNICODE_STRING_APPEND` for a literal rather than another `UnicodeString`;
#: both end in the same `0x00436D50` worker with `this` still in `ecx`. It clobbers `eax`.
UNICODE_STRING_CONCAT_WIDE = 0x00405183
UNICODE_STRING_CONCAT_WIDE_BYTES = bytes.fromhex("568b74240885f6578bf9740a")
#: `UnicodeString::operator=(const UnicodeString &)` - `__thiscall`, one stack argument, `ret 4`.
#: It **releases** the current buffer and takes a reference on the source, which is why a site
#: calling it *replaces* the string rather than adding to it.
UNICODE_STRING_ASSIGN = 0x00436A90
UNICODE_STRING_ASSIGN_BYTES = bytes.fromhex("6aff68f80eb70064a1000000")
#: The builder's "already researched" case, which assigns `PurchasedLabel` over the description,
#: losing `DescriptLabel`. `_ASSIGN` is the nine-byte assignment window; `eax` holds the text there.
DESCRIPTION_PURCHASED_RUN = 0x0080833B
DESCRIPTION_PURCHASED_RUN_BYTES = bytes.fromhex(
    "8b760c83c6708bcee81c9bbfff8b0d044bde0084c08b018d55b46a00750b5652ff5038c645fc15eb0d68e4eec4"
    "0052ff503cc645fc168d4de850e816e7c2ff8d4db4c645fc06e82ae4c2ff"
)
DESCRIPTION_PURCHASED_ASSIGN = 0x00808371
DESCRIPTION_PURCHASED_ASSIGN_BYTES = bytes.fromhex("8d4de850e816e7c2ff")
DESCRIPTION_PURCHASED_RESUME = 0x0080837A
#: The sibling "conflicting / missing prerequisite" case: the same shape, reached as `esi + 0x78`.
#: Its window starts with `push eax`, not `lea`, so the two windows are not interchangeable.
DESCRIPTION_BLOCKED_RUN = 0x008082C7
DESCRIPTION_BLOCKED_RUN_BYTES = bytes.fromhex(
    "8b760c83c6788bcee8909bbfff8b0d044bde0084c08b018d55b46a00750b5652ff5038c645fc11eb1c682cefc4"
    "0052ff503cc645fc12eb0d6804efc40052ff503cc645fc14508d4de8e87be7c2ff8d4db4c645fc06e88fe4c2ff"
)
DESCRIPTION_BLOCKED_ASSIGN = 0x0080830C
DESCRIPTION_BLOCKED_ASSIGN_BYTES = bytes.fromhex("508d4de8e87be7c2ff")
DESCRIPTION_BLOCKED_RESUME = 0x00808315
#: Where the builder keeps the line it is composing, and the description it appends lines to.
#: Both are `ebp`-relative in the builder's own frame, so a cave reached by `jmp` can use them.
DESCRIPTION_LINE_EBP_OFFSET = -0x2C
DESCRIPTION_TEXT_EBP_OFFSET = -0x18
#: The `Object` the description builder is describing, in its own frame. Its prologue resolves it
#: once (`[0x00DE4830]` vtable `+0x12c` -> a `Drawable`, then `+0xfc` -> the `Object`) and keeps it
#: here; `0x00807AE4` passing it to `Object::getControllingPlayer` is what identifies it. It may be
#: null when nothing is being described.
DESCRIPTION_OBJECT_EBP_OFFSET = -0x1C
#: The frame slot holding the `Object`'s controlling `Player`: never null (seeded from the local
#: player) and written only in the prologue, so safe to read at the end of the function.
DESCRIPTION_PLAYER_EBP_OFFSET = -0x20
#: The builder's prologue, where `[esi+0xc]` is the `CommandButton`. Three cases reassign `esi`
#: later, so a hook that needs the button after the switch copies it here.
DESCRIPTION_BUTTON_CAPTURE = 0x00807AF9
DESCRIPTION_BUTTON_CAPTURE_BYTES = bytes.fromhex("897dc48b4e0c")
DESCRIPTION_BUTTON_CAPTURE_RESUME = 0x00807AFF
#: The builder's tail, past every case: the description at `ebp-0x18` is final, so a line appended
#: here is genuinely last. Not a branch target.
DESCRIPTION_TAIL = 0x008086AE
DESCRIPTION_TAIL_BYTES = bytes.fromhex("8b0d704ade00")
DESCRIPTION_TAIL_RESUME = 0x008086B4
GUI_COMMAND_SPECIAL_POWER = 0x18
#: How the engine builds one `<label>: <number>` line (twelve sites): fetch through `TheGameText`
#: vtable `+0x44`, format into `ebp-0x28`, drop the three caller-pushed arguments.
#: Warning: `UNICODE_STRING_CONCAT` replaces rather than concatenates. To add to an existing string,
#: format into a temporary and join it with `UNICODE_STRING_APPEND`.
THE_GAME_TEXT = 0x00DE4B04
UNICODE_STRING_CONCAT = 0x00ADF7E0
DESCRIPTION_BUFFER_EBP_OFFSET = -0x28
#: The control bar's availability evaluator at its `UnitCost` test (`ecx` the template, `ebx` the
#: object). It never calls `canUseSpecialPower`, so greying a button is a separate edit.
CONTROL_BAR_UNIT_COST_CALL = 0x0094343B
CONTROL_BAR_UNIT_COST_CALL_BYTES = bytes.fromhex("e8fc58d4ff")
CONTROL_BAR_UNAVAILABLE = 0x009438C8
# `UnicodeString::UnicodeString(const WideChar *)` - thiscall, one stack argument which it
# cleans (`ret 4`), returning `this` in `eax`. It zeroes the object before assigning, so it is
# correct on the uninitialised storage a return-value-optimised caller hands out. This is the
# one `getReplayExtension` (`0x0077DEE3`) uses to build its literal.
UNICODE_STRING_FROM_WIDE = 0x00437770
# The palantir's per-frame decision to show the observer bar (next/prior player). `..._FINGERPRINT`
# is the 66-byte run around the call, which identifies it.
OBSERVER_BAR_GATE_CALL = 0x006D7813
OBSERVER_BAR_GATE_CALL_BYTES = bytes.fromhex("e806dcf4ff")  # call 0x0062541E
OBSERVER_BAR_SHOW = 0x008003F6  # SetObserverStuffState("_show"), an APT invoke thunk
OBSERVER_BAR_HIDE = 0x0080041A  # SetObserverStuffState("_hide")
OBSERVER_BAR_GATE_FINGERPRINT = 0x006D7809
OBSERVER_BAR_GATE_FINGERPRINT_BYTES = bytes.fromhex(
    "8b0d2c41de0085c9741ce806dcf4ff84c074138b0d2849de00e8ce0ffdff84"
    "c07404b301eb0232db8a467ec0e8073ad8741d84db7407e8b28b1200eb05e8"
    "cf8b1200"
)
# `ControlBar::processCommandUI`, where a command-button click enters the engine and where every
# observer click is discarded. See `docs/observer-command-range.md`.
CONTROL_BAR_PROCESS_COMMAND_UI = 0x00941B9F
CONTROL_BAR_CLICK_BUTTON_LOAD = 0x00941BB1
CONTROL_BAR_CLICK_BUTTON_LOAD_BYTES = bytes.fromhex("e8e67bdeff598bf0")
CONTROL_BAR_CLICK_GATE_PREFIX = 0x00941BC8
CONTROL_BAR_CLICK_GATE_PREFIX_BYTES = bytes.fromhex("85f674f88b0d2849de00")
CONTROL_BAR_CLICK_GATE_CALL = 0x00941BD2
CONTROL_BAR_CLICK_GATE_CALL_BYTES = bytes.fromhex("e81e6cd6ff")  # call 0x006A87F5
CONTROL_BAR_CLICK_GATE_SUFFIX = 0x00941BD7
CONTROL_BAR_CLICK_GATE_SUFFIX_BYTES = bytes.fromhex("84c075e9817c24140b400000")
# The rest of the click dispatch. Its two `Bool` arguments are pushed as whole dwords, so a
# replacement for the gate must zero all of `eax`, not just `al`.
CONTROL_BAR_CLICK_ARGUMENT_BUILD = 0x00941BE3
CONTROL_BAR_CLICK_ARGUMENT_BUILD_BYTES = bytes.fromhex(
    "8bcb0f94c0817c24140940000089bec4000000500f95c05056e834e8ffff"
)
# The click executor's two-level switch on `CommandButton+0x14`; reading both tables back proves the
# paging commands' numbers in this binary.
CONTROL_BAR_COMMAND_DISPATCH = 0x009408B3
CONTROL_BAR_COMMAND_DISPATCH_BYTES = bytes.fromhex(
    "8b4e148d51ff83fa3b0f87c3fbffff0fb692631b9400ff2495c31a9400"
)
CONTROL_BAR_COMMAND_JUMP_TABLE = 0x00941AC3
CONTROL_BAR_COMMAND_INDEX_TABLE = 0x00941B63
# `ControlBar::populateMultiSelect`'s per-drawable merge: the first drawable installs its command
# set, every later one intersects (the loop at `0x009446CA`).
CONTROL_BAR_POPULATE_MULTI_SELECT = 0x00944534
CONTROL_BAR_MERGE_OBJECT_EBP = -0x14
# The merge's verdict: two units keep a slot only if their buttons are the same pointer (or one is
# `ATTACK_MOVE`); otherwise it is hidden. `edx` and `cl` are free for a cave.
CONTROL_BAR_MERGE_SLOT = 0x0094472E
CONTROL_BAR_MERGE_SLOT_BYTES = bytes.fromhex("3bf8741884c97514")
# The merge's continuations: `HIDE`, `KEEP`, and `INSTALL` (reusable only with `eax` zero).
# `populateMultiSelect`'s slot reset has one caller (`0x00944853`), the place to clear per-populate
# scratch; `ecx` must survive it.
CONTROL_BAR_MERGE_RESET = 0x00944853
CONTROL_BAR_MERGE_RESET_BYTES = bytes.fromhex("e8b1fcffff")
CONTROL_BAR_MERGE_CLEAR_SLOTS = 0x00944509
# The first object's install (`mov [edi+0x84], ebx`). The flags and `ecx` are live across it, so a
# shim must restore both. The slot index is kept in `[ebp+8]`.
CONTROL_BAR_MERGE_INSTALL_FIRST = 0x009445E8
CONTROL_BAR_MERGE_INSTALL_FIRST_BYTES = bytes.fromhex("899f84000000")
CONTROL_BAR_MERGE_INSTALL_FIRST_RESUME = 0x009445EE
CONTROL_BAR_MERGE_SLOT_EBP = 0x08
CONTROL_BAR_MERGE_HIDE = 0x00944736
CONTROL_BAR_MERGE_KEEP = 0x0094474A
CONTROL_BAR_MERGE_INSTALL = 0x00944704
# The two paging handlers: `PUSH` appends the button's range to the stack at `ControlBar+0x2B0`,
# `POP` drops the top record; both then redraw.
CONTROL_BAR_PUSH_RANGE_HANDLER = 0x00941A7D
CONTROL_BAR_PUSH_RANGE_HANDLER_BYTES = bytes.fromhex("81c62c020000")  # add esi, 0x22c
CONTROL_BAR_POP_RANGE_HANDLER = 0x00941A9C
CONTROL_BAR_POP_RANGE_HANDLER_BYTES = bytes.fromhex("8b4dec8d81b0020000")
# `ControlBar::populate`'s read of the visible command range: eleven bytes, only the first a branch
# target, so replaceable whole. See `docs/push-visible-command-range.md`.
CONTROL_BAR_RANGE_FETCH = 0x00943E11
CONTROL_BAR_RANGE_FETCH_BYTES = bytes.fromhex("8d45b8508bcbe8ee90ddff")
CONTROL_BAR_RANGE_FETCH_RESUME = 0x00943E1C
CONTROL_BAR_GET_VISIBLE_RANGE = 0x0071CF0A
# The frame slots that record holds, as every consumer of it addresses them.
CONTROL_BAR_RANGE_START_EBP = -0x48
CONTROL_BAR_RANGE_COUNT_EBP = -0x44
# The three loops `ControlBar::populate` runs over that range. Only the first stops at the
# ControlBar's 33 button widgets; the other two run `count` times whatever `count` is, and each
# walks the 33-entry widget array at `ControlBar+0xDC` in step with the slot index. So an
# unclamped range runs both arrays off their ends - which is the crash `CommandSetLimitPatch`
# fixes by clamping the record once, at the fetch above.
CONTROL_BAR_RANGE_LOOP_CAPPED = 0x00943E29
CONTROL_BAR_RANGE_LOOP_REVIVE = 0x00943F2B
CONTROL_BAR_RANGE_LOOP_REVIVE_BYTES = bytes.fromhex("8b45b88b4dd403c8518b4de8")
CONTROL_BAR_RANGE_LOOP_PRODUCTION = 0x0094426A
CONTROL_BAR_RANGE_LOOP_PRODUCTION_BYTES = bytes.fromhex("8b45b803c8518b4de8")
# How many command buttons the ControlBar can draw at once: the length of its widget array, and
# the bound the first loop carries as a literal. Untouched by the button-limit patch, which
# raises how many buttons a `CommandSet` may *define*, not how many fit on screen.
CONTROL_BAR_MAX_VISIBLE = 33
# `TheTacticalView` - the camera. **Not a subsystem singleton**, which is why it is absent from
# `docs/engine-globals.md`'s registration walk: `TheGameClient` creates it at `0x0069EF61`
# (`createView`, its own vtable slot `+0x1D8`), stores the result here, and calls `init` on it.
# 423 xrefs across the client, and none at all from logic - the camera is presentation state
# that the simulation never reads, which is what makes writing it desync-safe.
THE_TACTICAL_VIEW = 0x00DE447C
# `View::getLocation` / `setLocation(ViewLocation *)`, the camera-bookmark pair: thiscall, `ret 4`.
# The bookmark handler's 32-byte stride gives the struct's size.
VIEW_GET_LOCATION_VTABLE_SLOT = 0x170
VIEW_SET_LOCATION_VTABLE_SLOT = 0x174
# `ViewLocation`: a validity flag, a `Coord3D`, then four angles/distances. Its shape is fixed
# by the `MSG_SET_REPLAY_CAMERA` emitter at `0x0083BA86`, which builds one on the stack and
# ships it as a Position argument followed by exactly four Floats.
VIEW_LOCATION_SIZE = 0x20
# `View::m_pos`, the camera's look-at point. Writing these twelve bytes moves the camera by itself;
# `setLocation` always rewrites the zoom too (see `docs/camera-control.md`).
VIEW_POSITION_OFFSET = 0x0C
# `GUICommandType::GUICOMMAND_REVIVE`, entry 46 of the name table at 0x00DA4D10.
GUICOMMAND_REVIVE = 46
# The two paging commands (55 and 56): they only change which slice of a `CommandSet` is shown,
# which is what makes them safe to give an observer.
GUICOMMAND_PUSH_VISIBLE_COMMAND_RANGE = 55
GUICOMMAND_POP_VISIBLE_COMMAND_RANGE = 56
#: The palantir's resource-multiplier readout: refreshed every frame and blank at exactly `1.0f`,
#: which is what a skirmish feeds it here. Replacing that load is the whole readout.
PALANTIR_RESOURCE_MULTIPLIER = 0x006D59B7
PALANTIR_RESOURCE_MULTIPLIER_BYTES = bytes.fromhex("f30f10050819bd00e9a5000000")
PALANTIR_RESOURCE_MULTIPLIER_RESUME = 0x006D5A69
#: `UnicodeString::format(this, fmt, ...)` - cdecl, caller-cleaned, so one more vararg costs one
#: more push and a `0x10 -> 0x14` on the cleanup.
UNICODE_STRING_FORMAT = 0x00ADF750
#: The engine's red "you lost gold" floating text and its parameters, reused so a charge looks like
#: something the game already does.
GUI_LOSE_CASH = 0x00C732F8
LOSE_CASH_COLOR = 0xFFFF0000
LOSE_CASH_RISE = 0x00BDAE54
IN_GAME_UI_ADD_FLOATING_TEXT = 0x1A0
#: The palantir's resource text, built and pushed to the movie in one place, so no `.apt` edit is
#: needed. The window is before the first vararg push; `[ebp-4]` must still be written.
PALANTIR_RESOURCES = 0x006D5721
PALANTIR_RESOURCES_BYTES = bytes.fromhex("837d0800c745fc01000000")
PALANTIR_RESOURCES_RESUME = 0x006D572C
PALANTIR_RESOURCES_DONE = 0x006D5751  # the setValue, past the format
#: The refresh's change filter on gold. A second number must widen it, or it goes stale while gold
#: is flat.
PALANTIR_RESOURCES_CACHE = 0x006D5804
PALANTIR_RESOURCES_CACHE_BYTES = bytes.fromhex("3b7e0c740a")
PALANTIR_RESOURCES_CACHE_PUSH = 0x006D5809  # push the value and call the text builder
PALANTIR_RESOURCES_CACHE_SKIP = 0x006D5813  # unchanged: no text this frame
#: The two `TOOLTIP:Cost` lines that price a template (a unit or structure, and a hero). The window
#: sits after the line exists and before it is handed over, where a suffix can join it.
TOOLTIP_COST_BUILD = 0x00807F82
TOOLTIP_COST_BUILD_RESUME = 0x00807F87
TOOLTIP_COST_REVIVE = 0x008085EC
TOOLTIP_COST_REVIVE_RESUME = 0x008085F1
TOOLTIP_COST_BYTES = bytes.fromhex("508d45d850")
#: `UnicodeString::~UnicodeString` - thiscall, no arguments. Needed because a suffix built with
#: `UNICODE_STRING_FORMAT` is a real string with a real allocation, not a literal.
UNICODE_STRING_DTOR = 0x004367B0
#: `AptMainMenu::Expansion1Campaign`, the FSCommand name, and the registration block that binds it
#: to `MAIN_MENU_CAMPAIGN_HANDLER`: `push <name>` / `lea ecx, [ebp+8]` / `mov esi, <handler>`.
#: Fingerprinting the registration rather than the handler alone is what proves `0x0091AF8C` is
#: *this* command's callback and not the identically shaped `BonusCampaign` one 35 bytes later.
MAIN_MENU_CAMPAIGN_COMMAND = 0x00C7D254
MAIN_MENU_CAMPAIGN_REGISTRATION = 0x0091CB02
MAIN_MENU_CAMPAIGN_REGISTRATION_BYTES = bytes.fromhex("6854d2c7008d4d08be8caf9100")
#: The campaign callback (35 bytes, thiscall, `ret 4`). It keeps only the first byte of its params
#: string, the difficulty letter.
MAIN_MENU_CAMPAIGN_HANDLER = 0x0091AF8C
MAIN_MENU_CAMPAIGN_HANDLER_BYTES = bytes.fromhex(
    "8b442404c7818802000009000000c7818c0200000d0000008a008881a8020000c20400"
)
#: The three `AptMainMenu` fields the callback writes, and the two constants it writes into the
#: first two. `MAIN_MENU_SCREEN_SELECTION` indexes a 14-entry jump table at `0x0091C70B`
#: (`0x0091C349`: `dec eax` / `cmp eax, 0Dh` / `ja` / `jmp [eax*4 + table]`), whose case 13 is the
#: `ANGMAR_CAMPAIGN` start.
MAIN_MENU_SCREEN_PHASE = 0x288
MAIN_MENU_SCREEN_SELECTION = 0x28C
MAIN_MENU_SCREEN_DIFFICULTY = 0x2A8
MAIN_MENU_PHASE_LEAVING = 9
MAIN_MENU_CAMPAIGN_SELECTION_ID = 0x0D
# The Battle School command and the shell services its exit needs (`docs/battle-school.md`). The
# exit command was dropped; `battle-school` supplies it through the surviving command's params.

#: `AptMainMenu::BattleSchool`, the FSCommand name, and the registration block that binds it to
#: `BATTLE_SCHOOL_HANDLER`: `push <name>` / `lea ecx, [ebp+8]` / `mov esi, <handler>`. Same
#: fingerprint shape as `MAIN_MENU_CAMPAIGN_REGISTRATION`, and for the same reason - the handler
#: alone is not distinguishable from the other registration blocks around it.
BATTLE_SCHOOL_COMMAND = 0x00C7D0A8
BATTLE_SCHOOL_REGISTRATION = 0x0091D052
BATTLE_SCHOOL_REGISTRATION_BYTES = bytes.fromhex("68a8d0c7008d4d08be40b59100")
#: The Battle School handler (169 bytes, thiscall, `ret 4`). Its first five bytes are the SEH cookie
#: load, which makes a five-byte detour clean.
BATTLE_SCHOOL_HANDLER = 0x0091B540
BATTLE_SCHOOL_HANDLER_BYTES = bytes.fromhex(
    "b8569aba00e8a619120083ec1ca19078de005333db3bc3568bf17404c6405d0153518965"
    "ec8bcc6828cec700e86fbfb1ff8b0d5436de00e82a04ccff8b0d9078de003bcb7405e826"
    "24e4ff8d4dd8e860a1dcff6818cec7008d4df0895dfce83dbfb1ff538d45f0508d4dd8c6"
    "45fc01e8c570e9ff8d4df0885dfce891a7b1ff8d4dd8e88571e9ff834dfcff8d4dd8889e"
    "81020000e856a0dcff8b4df45e64890d000000005bc9c20400"
)
#: `"MainMenuToBattleSchool"`, the `WindowTransition` group both directions name. Still defined in
#: stock `data/ini/windowtransitions.ini`, byte-identical to BFME1's, as a `SOUNDFADE` with
#: `LeaveSilent = Yes` - which is why leaving needs the reverse and cannot simply do nothing.
BATTLE_SCHOOL_TRANSITION_NAME = 0x00C7CE28
#: `BlinkBattleSchoolOff`'s registration in the sibling `GetExtern` map at `this+0x228`. Not
#: touched by the patch; fingerprinted because it is the other half of the movie's contract, and a
#: build where it had moved would be one where `BATTLE_SCHOOL_HANDLER` had moved too.
BATTLE_SCHOOL_BLINK_REGISTRATION = 0x0091D2AA
BATTLE_SCHOOL_BLINK_REGISTRATION_BYTES = bytes.fromhex("68f4cfc7008d4d08be6bbb9100")
#: The `AptMainMenu` byte the shared `GetExtern` getter (`0x0091BB6B`, case 3 at `0x0091BB91`)
#: answers `BlinkBattleSchoolOff` from: nonzero means "still blinking", and the getter returns
#: `"0"`/`"1"` inverted from it. Seeded from the `FlashTutorial` preference at `0x0091D446` and
#: self-cleared once `TimesInGame` passes 5 (`0x0091D477`).
MAIN_MENU_BLINK_FLAG = 0x281
#: `AptMainMenu::CreditsExit` and the tail `battle-school`'s exit arm is modelled on
#: (`0x0091B733`..`0x0091B7B3`): restart the shell music if it stopped, reverse the screen's
#: transition group, release `SHELL_MOVIE_ACTIVE`, restore the frame-rate limit. The patch copies
#: the shape rather than calling into it, because the part above this tail tears down the credits
#: movie player at `0x00DEBF50`, which Battle School never allocates.
CREDITS_EXIT_HANDLER = 0x0091B6FD
CREDITS_EXIT_AUDIO_TAIL = 0x0091B733
CREDITS_EXIT_AUDIO_TAIL_BYTES = bytes.fromhex(
    "8b0d9078de003bcb7409e88822e4ff84c0751e8b0dfc42de008b01536a016a02ff908c00"
    "00008b0d9078de00e8c227e4ff518964240c8bcc6840cec700e86bbdb1ff8b0d5436de00"
    "e81903ccff8d8ea4020000899e88020000e8bfa5b1ffa19078de0088585d8b156443de00"
    "8b0d2443de00ff72288b01ff50485e5b59c20400"
)
#: `TheShell` - the singleton pointer, not the object. `+0x5D` is the flag both directions of a
#: full-screen shell movie set and clear; `+0x68` holds the handle of the shell music track that
#: `SHELL_MUSIC_PLAYING` asks `TheAudio` about.
SHELL = 0x00DE7890
SHELL_MOVIE_ACTIVE = 0x5D
#: `Shell::isShellMusicPlaying()` (`thiscall`, no arguments, `al` nonzero when it still is) and
#: `Shell::playShellMusic()` (`thiscall`, no arguments). `CreditsExit` uses the pair as a guard:
#: only when the music has stopped does it stop the audio channels and start it again.
SHELL_MUSIC_PLAYING = 0x0075D9CA
SHELL_MUSIC_PLAYING_BYTES = bytes.fromhex("a1fc42de0085c07415ff71688b108bc8")
SHELL_PLAY_MUSIC = 0x0075DF26
SHELL_PLAY_MUSIC_BYTES = bytes.fromhex("b88b21b900e8c0ef2d0081ec8c000000")
#: `TheAudio`, and the vtable slot both the enter and the exit path call with `(2, 1, 0)` to stop
#: the playing audio channels. `docs/engine-globals.md` tabulates the pointer.
AUDIO_MANAGER = 0x00DE42FC
AUDIO_STOP_SLOT = 0x8C
#: `TheWindowTransitionsHandler`, and the two `thiscall`s that drive a transition group by name.
#: Both take one **by-value** `AsciiString` (a single pointer) and `ret 4`; MSVC has the callee
#: destroy a by-value class argument, which `WINDOW_TRANSITION_REVERSE` does at `0x005DBB6A`, so a
#: caller reserves the slot, constructs into it and lets the call clean up.
WINDOW_TRANSITIONS_HANDLER = 0x00DE3654
WINDOW_TRANSITION_SET_GROUP = 0x005DB9A6
WINDOW_TRANSITION_REVERSE = 0x005DBA99
WINDOW_TRANSITION_REVERSE_BYTES = bytes.fromhex("b801dbb700e84d14460051515356578b")
THE_APT_PLAYER = 0x00DE3F0C
# The Palantir's objectives button, which pushes one of three movies after asking the game-type
# predicate `0x00625456` twice. See `docs/objectives-in-any-map.md`.
PALANTIR_SCREEN_CHOICE_CALL = 0x008E8958
PALANTIR_SCREEN_CHOICE_CALL_BYTES = bytes.fromhex("e8f9cad3ff")
#: The two edges, kept as anchors: a build whose branch moved fails on these rather than having
#: some unrelated call redirected.
PALANTIR_PLAYER_STATUS_PUSH = 0x008E896B
PALANTIR_PLAYER_STATUS_PUSH_BYTES = bytes.fromhex("682c8cc100")
PALANTIR_OBJECTIVES_PUSH = 0x008E8972
PALANTIR_OBJECTIVES_PUSH_BYTES = bytes.fromhex("685c8cc100")
#: The two handlers the outer question routes between. `PALANTIR_OPEN_TRIBUTE_SCREEN` pushes
#: `PlayerTribute.apt` with no further question asked; `PALANTIR_OPEN_STATUS_SCREEN` is the one
#: holding `PALANTIR_SCREEN_CHOICE_CALL`. Their guard chains are the same except for the
#: already-open check each makes on its own screen, so anything that reaches one reaches the other.
PALANTIR_OPEN_TRIBUTE_SCREEN = 0x00914EF0
PALANTIR_OPEN_STATUS_SCREEN = 0x008E8843
#: The outer question, in the button's callback (`0x006D40C9`) - the site that actually decides
#: what a skirmish or War of the Ring battle sees, and the reason patching only the inner one had
#: no effect. The two `call`s it branches between are anchors: they name the handlers, so a build
#: whose branch moved or swapped fails rather than having an unrelated call redirected.
PALANTIR_BUTTON_ROUTE_CALL = 0x006D40D2
PALANTIR_BUTTON_ROUTE_CALL_BYTES = bytes.fromhex("e87f13f5ff")
PALANTIR_BUTTON_TRIBUTE_CALL = 0x006D40DB
PALANTIR_BUTTON_TRIBUTE_CALL_BYTES = bytes.fromhex("e8100e2400")
PALANTIR_BUTTON_STATUS_CALL = 0x006D40E2
PALANTIR_BUTTON_STATUS_CALL_BYTES = bytes.fromhex("e85c472100")
#: The same question again in the hotkey dispatch (`0x0081FFAA`), which reaches the handlers
#: without going through the button. Left alone, the key and the button would disagree.
PALANTIR_HOTKEY_ROUTE_CALL = 0x0081FFD8
PALANTIR_HOTKEY_ROUTE_CALL_BYTES = bytes.fromhex("e87954e0ff")
PALANTIR_HOTKEY_TRIBUTE_CALL = 0x0081FFE1
PALANTIR_HOTKEY_TRIBUTE_CALL_BYTES = bytes.fromhex("e80a4f0f00")
PALANTIR_HOTKEY_STATUS_CALL = 0x0081FFEB
PALANTIR_HOTKEY_STATUS_CALL_BYTES = bytes.fromhex("e853880c00")
#: `TheMissionObjectiveTracker`, a startup subsystem registered at `0x0063BA12`. Its `+0x10` holds
#: the objective list a map's `MissionObjectiveList` block installs (parser `0x00836497`, which
#: sets the member only when it is null); the list is a vector of 8-byte entries at `+0x04`/`+0x08`.
#: The HUD's own consumers read exactly these two fields - see `0x006D789C` and `0x0079DEA8`.
MISSION_OBJECTIVE_TRACKER = 0x00DE8C94
MISSION_OBJECTIVE_LIST_OFFSET = 0x10
# The unit-plate option: the `Model =` parse-time gate, and the preference plumbing it borrows.
# Derived in `docs/options-menu-rows.md` (the options screen) and in
# `patches/unit_plate_option.py`'s module docstring (the gate). Static only - none of this has
# been confirmed against a running game.

#: `ModelConditionState`'s `Model =` field parser, from the block's field-parse table. Reads the
#: model name with `INI::getNextTokenOrNull`, then optionally `ExtraMesh <bool>`, then stores the
#: name as an `AsciiString` at `ModelConditionState+0x4C`.
MODEL_FIELD_PARSER = 0x004C21EE
MODEL_FIELD_PARSER_BYTES = bytes.fromhex("b83a58b700e8f8ac570051538b5d0c85db0f")
#: Inside it, the point where the parsed name is about to be copied into the `AsciiString`:
#: `push dword [ebp-0x10]` / `lea ecx, [ebp+0xc]`. Six bytes, two whole instructions, and
#: `[ebp-0x10]` is a plain `const char *` - which is what makes this the cheapest place to
#: substitute one model name for another exactly once per `Model =` line.
MODEL_FIELD_STORE = 0x004C2266
MODEL_FIELD_STORE_BYTES = bytes.fromhex("ff75f08d4d0c")
MODEL_FIELD_STORE_RESUME = 0x004C226C
#: `OptionPreferences::OptionPreferences()` - sets the vtable (`0x00C1B180`) and loads the whole of
#: `Options.ini` (`0x00C1B1C8`) into the string map at `+4`. Returns `this` in `eax`. Constructing
#: one is a file parse, so a caller on a hot path resolves its preference once and caches it.
OPTION_PREFERENCES_CTOR = 0x006E56F3
OPTION_PREFERENCES_CTOR_BYTES = bytes.fromhex("b8b6d0b800e8f37735005151568bf18975ece840d40c")
OPTION_PREFERENCES_DTOR = 0x006E562F
OPTION_PREFERENCES_DTOR_BYTES = bytes.fromhex("c70180b1c100e984d40c00a1843bde00")
#: `OptionPreferences::getAllHealthBars()` - the shape every boolean preference accessor has, and
#: the one `unit-plate-option` clones with a different key: look the key up in the map at `this+4`,
#: answer true only if the value `stricmp`s equal to `"yes"`, and false when the key is absent.
OPTION_PREFERENCES_GET_BOOL = 0x006E6179
OPTION_PREFERENCES_GET_BOOL_BYTES = bytes.fromhex(
    "558bec5156578bf168b8b2c1008d4dfce85213d5ff8d45fc83c604508bce"
)
#: `std::map<AsciiString, AsciiString>::find(&key)` as the preference accessors call it - `this` is
#: the map (`OptionPreferences+4`), and a miss returns the map's header node, which is also what
#: `[this]` holds. So "not found" is `result == *this`, not NULL.
PREFERENCES_MAP_FIND = 0x00456726
#: The `ModelConditionState` field-parse row for `Model =`: `{name, parse, userData, offset}` with
#: `name -> "Model"` and `parse -> MODEL_FIELD_PARSER`. The only dword in the image that points at
#: that parser, which is what identifies it as the `Model =` handler rather than a lookalike.
MODEL_FIELD_TABLE_ROW = 0x00BE0A78
# The Options screen's gadget ladder and its save path, for `unit-plate-option`'s 20th row.
# Derived in `docs/options-menu-rows.md` §2, §5 and §6a. Static only.

#: `AptOptions::InitGadgets`' entry branch: the `jne` taken when the gadget is not
#: `Options::Resolution`, which is what sends every other name into the 19-arm ladder. Six bytes,
#: and the flags it reads survive an unconditional `jmp`, so a cave can re-take the branch. The
#: ladder's *tail* `jne` at `0x00920DB9` is only two bytes and cannot hold a `jmp rel32`.
APT_INIT_GADGETS_LADDER_HOOK = 0x00920602
APT_INIT_GADGETS_LADDER_HOOK_BYTES = bytes.fromhex("0f8589010000")
#: Where the two arms of that branch go: the `Options::Resolution` body, and the ladder head
#: (`push "Options::Detail"`). Both are stock instruction boundaries.
APT_INIT_GADGETS_RESOLUTION_ARM = 0x00920608
APT_INIT_GADGETS_LADDER = 0x00920791
APT_INIT_GADGETS_LADDER_BYTES = bytes.fromhex("68f0d8c700ff7508")
#: The epilogue every matched arm jumps to.
APT_INIT_GADGETS_EPILOGUE = 0x00920DF2
#: `AptOptions::Save`. Its `OptionPreferences` is constructed at `0x0091FCC0` into `[ebp-0x34]`,
#: so the string map it writes through is `[ebp-0x30]`.
APT_OPTIONS_SAVE = 0x0091FC9C
APT_OPTIONS_SAVE_BYTES = bytes.fromhex("b81aa2ba00e84ad2110083ec3c5333db")
APT_OPTIONS_SAVE_PREFS_EBP = -0x34
APT_OPTIONS_SAVE_MAP_EBP = -0x30
#: Inside it, `lea ecx, [ebp-0x34]` / `call UserPreferences::write` - the flush, and the last point
#: at which a key can be added to the map and still reach the file. Eight bytes, two whole
#: instructions.
APT_OPTIONS_SAVE_FLUSH = 0x009204D9
APT_OPTIONS_SAVE_FLUSH_BYTES = bytes.fromhex("8d4dcce86b22e9ff")
APT_OPTIONS_SAVE_RESUME = 0x009204E1
#: `UserPreferences::write()` - serialises the map back to the file the object was loaded from.
USER_PREFERENCES_WRITE = 0x007B274C
#: The checkbox accessors the option rows use: `setCheckBoxState(gadget, bool)` and
#: `getCheckBoxState(gadget)`, both `__cdecl` with the gadget as the first stack argument.
SET_CHECKBOX_STATE = 0x00729534
GET_CHECKBOX_STATE = 0x00729579
#: `std::map<AsciiString, AsciiString>::operator[](&key)` - inserts if absent and returns the
#: value slot. `__thiscall`, `ret 4`, `this` being the map (`OptionPreferences+4`).
PREFERENCES_MAP_INDEX = 0x00602B76
#: `mov [ebp-0x24], ebx` with `ebx` zero - what establishes the start-game gate's slot counter,
#: and `push <"GUI:DisabledFaction">`, the message that loop exists to raise. Together they say
#: the local at `-0x24` really is the slot index of the pass that reads `DisabledFactions`.
MP_SETUP_START_GATE_LOOP_INIT = 0x008432E2
MP_SETUP_START_GATE_LOOP_INIT_BYTES = bytes.fromhex("895ddc")
MP_SETUP_DISABLED_FACTION_PUSH = 0x008435D9
MP_SETUP_DISABLED_FACTION_PUSH_BYTES = bytes.fromhex("68cc42c500")
#: The entry of the historical-scenario fixup, which holds both the validation pass and the
#: Random-resolution pass, and the `and dword [ebp-0x18], 0` that starts each one's slot loop.
MP_SETUP_HISTORICAL_FIXUP = 0x008445F2
MP_SETUP_HISTORICAL_FIXUP_BYTES = bytes.fromhex("b895d1b900")
MP_SETUP_VALIDATE_LOOP_INIT = 0x00844685
MP_SETUP_VALIDATE_LOOP_INIT_BYTES = bytes.fromhex("8365e800")
MP_SETUP_RANDOM_LOOP_INIT = 0x008447C8
MP_SETUP_RANDOM_LOOP_INIT_BYTES = bytes.fromhex("8365e800")
#: The entry of the combo-box fill, and the two instructions that prove its one argument is a
#: lobby slot index: it is handed to `GameInfo::getSlot`, and it indexes the screen's array of
#: per-slot faction windows at `this+0x334`.
MP_SETUP_FACTION_COMBO = 0x00844BD4
MP_SETUP_FACTION_COMBO_BYTES = bytes.fromhex("b8c1d1b900")
MP_SETUP_FACTION_COMBO_SLOT_ARG = 0x00844BFB
MP_SETUP_FACTION_COMBO_SLOT_ARG_BYTES = bytes.fromhex("8b7d0857")
MP_SETUP_FACTION_COMBO_SLOT_WINDOW = 0x00844C0F
MP_SETUP_FACTION_COMBO_SLOT_WINDOW_BYTES = bytes.fromhex("8bbcbe34030000")
#: The tray's class, constructed once, by `StrategicHUD`'s `_OnSelectionDetailsLoaded` handler
#: (`0x0083A141`). `+0x28` is its state - 0 closed, 1 opening, 2 open, 3 closing - and `+0x2C` says
#: the selection has something to show.
SELECTION_DETAILS_TRAY_VTABLE = 0x00C867C0
SELECTION_DETAILS_TRAY_STATE = 0x28
SELECTION_DETAILS_TRAY_HAS_CONTENT = 0x2C
#: vtable `+0x04`, `setHasContent(Bool)`: `ret 4`, and the only writer of `+0x2C`. The `je` at the
#: resume address takes the flags of the compare the hook replays.
SELECTION_DETAILS_TRAY_SET_HAS_CONTENT = 0x009859D6
SELECTION_DETAILS_TRAY_SET_HAS_CONTENT_BYTES = bytes.fromhex("8a4424043a412c")
SELECTION_DETAILS_TRAY_SET_HAS_CONTENT_RESUME = 0x009859DD
SELECTION_DETAILS_TRAY_SET_HAS_CONTENT_SLOT = 0x04
#: `open()`: calls the movie's `Open` and sets the state to 1, plain `ret`. Reached through the
#: vtable `+0x1C` thunk and from the `_OnToggleButtonClicked` handler at `0x00985CC2`.
SELECTION_DETAILS_TRAY_OPEN = 0x00985B28
SELECTION_DETAILS_TRAY_OPEN_BYTES = bytes.fromhex("568bf18b4618")
SELECTION_DETAILS_TRAY_OPEN_RESUME = 0x00985B2E
SELECTION_DETAILS_TRAY_OPEN_THUNK = 0x00985CB8
SELECTION_DETAILS_TRAY_OPEN_THUNK_BYTES = bytes.fromhex("e96bfeffff")
SELECTION_DETAILS_TRAY_OPEN_SLOT = 0x1C
#: The per-frame refresh's `cmp byte [esi+0x2C], 0`: with nothing to show it closes an open tray and
#: sets the toggle button `_disabled`.
SELECTION_DETAILS_TRAY_REFRESH_TEST = 0x00985C56
SELECTION_DETAILS_TRAY_REFRESH_TEST_BYTES = bytes.fromhex("807e2c00")
#: The lobby fill's first mapped-image lookup, `push <"AptDifficultyNotConquered">`. Hooked to
#: resolve this patch's own images once per fill, on the same schedule as the stock twelve.
MAP_LIST_RESOLVE = 0x008460E7
MAP_LIST_RESOLVE_BYTES = bytes.fromhex("689045c500")
MAP_LIST_RESOLVE_RESUME = 0x008460EC
#: Pass 1's per-entry preamble, `mov eax, [ebp+8]` / `mov esi, [eax]` - the two instructions
#: that pick the next `MapMetaData` up, and the last point before the difficulty stores overwrite
#: its key. The `ZF` set by the `cmp` three bytes earlier is live across them and is consumed at
#: the resume point, which is why the cave saves the flags.
MAP_LIST_SAVE_KEY = 0x00846443
MAP_LIST_SAVE_KEY_BYTES = bytes.fromhex("8b45088b30")
MAP_LIST_SAVE_KEY_RESUME = 0x00846448
#: Pass 1's tail: `cmp byte [esi+0x26], 0` / `jne` / `or byte [esi+0xF5], 0x80`. Thirteen
#: bytes, reached on both of the pass's paths - the one that computed a difficulty and the one
#: that zeroed the key for a non-multiplayer map - which is what makes it the place to put the
#: symbol back.
MAP_LIST_OFFICIAL_BIT = 0x00846590
MAP_LIST_OFFICIAL_BIT_BYTES = bytes.fromhex("807e26007507808ef500000080")
MAP_LIST_OFFICIAL_BIT_RESUME = 0x0084659D
#: Pass 2's ladder entry: `mov eax, [esi+0xF4]` / `cmp eax, 0x8001`. The `cmp`'s flags are
#: consumed five bytes past the resume point, so a cave that declines to handle a row has to set
#: them again on its way back.
MAP_LIST_ICON_LADDER = 0x008465EA
MAP_LIST_ICON_LADDER_BYTES = bytes.fromhex("8b86f40000003d01800000")
MAP_LIST_ICON_LADDER_RESUME = 0x008465F5
#: Where the ladder's arms converge: the row is added with the key as its item data and
#: `[ebp+8]` as its image. A cave that picked an image jumps straight here.
MAP_LIST_ROW_ADD = 0x00846674
#: The map-list comparator's key delta, which compares the whole dword at `+0xF4`; a sort that
#: ignores part of the key must mask both operands here.
MAP_LIST_COMPARE_KEY = 0x008424E2
MAP_LIST_COMPARE_KEY_BYTES = bytes.fromhex("8b83f40000008b4df02b87f40000008b09")
MAP_LIST_COMPARE_KEY_RESUME = 0x008424F3
#: Everything the map-list patch depends on and does not rewrite: the table it copies, the
#: assignment operator its store hook calls, the insert whose `ret 4` leaves that call's
#: argument on the stack, and the mapped-image lookup. The comparator arm is checked separately,
#: because one of the patch's options rewrites it.
MAP_LIST_ANCHORS: dict[int, bytes] = {
    MAP_META_DATA_ASSIGN: bytes.fromhex("5355"),
    # `MapCache::insert`'s `ret 4` and the `lea eax, [esi+0x14]` that makes its return value the
    # stored entry rather than the node.
    0x0070662A: bytes.fromhex("8d4614"),
    0x00706636: bytes.fromhex("c20400"),
    # `findImageByName`: thiscall on the collection, an `AsciiString *`, `ret 4`, NULL on a miss.
    OBJECT_IMAGE_UPGRADE_FIND_IMAGE: bytes.fromhex("558bec56"),
    0x006DA376: bytes.fromhex("33c0"),
    0x006DA37E: bytes.fromhex("c20400"),
}
# The hotkey translator's modifier gate, which discards Ctrl and Alt key presses (so Ctrl+letter is
# unused). See `docs/spellbook-hotkeys.md`.
HOT_KEY_TRANSLATOR_MODIFIER_GATE = 0x0075B11D
HOT_KEY_TRANSLATOR_MODIFIER_GATE_BYTES = bytes.fromhex("3bf37409385df00f8482000000")
HOT_KEY_TRANSLATOR_REJECT = 0x0075B1AC
HOT_KEY_TRANSLATOR_PROCEED = 0x0075B12A
#: The flag slot the gate writes and `HOT_KEY_EXECUTE` receives as its second argument. Stock
#: stores one byte into it and pushes the whole dword, so the upper three bytes are whatever the
#: frame held: every reader takes it as a byte, and so must anything that adds a value.
HOT_KEY_TRANSLATOR_FLAG_EBP = -0x10
#: `HotKeyManager::executeHotKey(key, flag)`. `..._HOOK` sits past its game-state gates; a cave
#: there must preserve `esi` and `edi`.
HOT_KEY_EXECUTE = 0x0075AEFA
HOT_KEY_EXECUTE_HOOK = 0x0075AF43
HOT_KEY_EXECUTE_HOOK_BYTES = bytes.fromhex("5657ff7508")
HOT_KEY_EXECUTE_RESUME = 0x0075AF48
HOT_KEY_EXECUTE_KEY_EBP = 0x08
HOT_KEY_EXECUTE_FLAG_EBP = 0x0C
#: The two exits, at the stack depth `..._HOOK` sits at - only `ebx` is pushed below `ebp` there,
#: which is what makes them reachable from a cave that saved `esi`/`edi` itself. `..._MISS` forces
#: `al` to zero; `..._HIT` is the same epilogue entered one instruction later, so a cave sets its
#: own `al` and jumps there.
HOT_KEY_EXECUTE_MISS = 0x0075B057
HOT_KEY_EXECUTE_HIT = 0x0075B059
#: `HotKeyManager::getHotKeyFromLabel(AsciiString *out, AsciiString label)` - `__thiscall`,
#: `ret 8`, the `&` scan that is the engine's whole hotkey-authoring story. It fetches the
#: localized text for `label` through `TheGameText`, finds the first `&` (`cmp ax, 0x26` at
#: `0x0075A6B8`) and **copy-constructs** the character after it into `out` - so `out` is written
#: as raw memory rather than assigned, and the caller owns the result and must destroy it.
HOT_KEY_MANAGER_HOTKEY_FROM_LABEL = 0x0075A7CB
THE_HOT_KEY_MANAGER = 0x00DE7870
#: `ControlBar::doCommand(CommandButton *, Bool, Bool)`, where every click lands; `SPELL_BOOK` is
#: exempt from its selection requirement.
CONTROL_BAR_DO_COMMAND = 0x00940435
#: The mode test the APT spellbook bar makes on its way into `doCommand` (`0x00930E07`), and the
#: only reason the second argument is not simply zero. Reproduced rather than simplified: it is
#: what a click on that bar passes.
APT_PLAYER_MODE = 0x318
#: `ControlBar::getCommandAvailability`: 1 and 2 are the only answers meaning "a click does
#: something". The spellbook path never asks it.
CONTROL_BAR_GET_COMMAND_AVAILABILITY = 0x00942733
CONTROL_BAR_AVAILABILITY_OK_LOW = 1
CONTROL_BAR_AVAILABILITY_OK_HIGH = 2
#: `doCommand`'s copy of that rule, kept as an anchor: a build that changed which values pass
#: fails here rather than having a cave silently disagree with the bar beside it.
CONTROL_BAR_AVAILABILITY_TEST = 0x009405B3
