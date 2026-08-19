"""Addresses of one engine build, in one place.

The RotWK SAGE-engine `game.dat` build ``2.01.2614.37001`` (11,346,944 bytes, ImageBase
``0x400000``, no ASLR - so a virtual address here is also where the byte sits in a running
process).

**Why this module exists.** These facts were being carried in two packages at once:
`sage_live.EngineLayout` held the subsystem globals it reads, while
`sage_patch.patches.experimental.live_bridge` held the ones its cave calls. Both describe the
same build, so supporting a second one meant editing two files by two different mechanisms - and
only one of them could be overridden without a code change. A build is one thing; it is described
here, once.

`sage_patch` is the natural home: it is the lower layer, it already owns the binary-facing
work, and `sage_live` already depends on it for the live-bridge command-buffer layout. Nothing
here imports anything, so the dependency costs nothing.

Every address is derived in `docs/engine-globals.md`, `docs/live-object-model.md` and
`docs/message-stream.md`. The globals were confirmed against a running process; the function
addresses were confirmed statically and, for `GAME_LOGIC_UPDATE`, by the hook firing.
"""

from __future__ import annotations

__all__ = [
    "ABILITY_MODULEDATA_SPECIAL_POWER",
    "ABILITY_TRIGGER",
    "ABILITY_TRIGGER_MODULEDATA_EBP",
    "ABILITY_TRIGGER_OBJECT_EBP",
    "ABILITY_TRIGGER_PAY",
    "ABILITY_TRIGGER_PAY_BYTES",
    "ABILITY_TRIGGER_PAY_RESUME",
    "ABILITY_TRIGGER_VTABLE",
    "AI_PRODUCER_ACCEPT",
    "AI_PRODUCER_ANY_BRANCH",
    "AI_PRODUCER_ANY_BRANCH_ENTRY",
    "AI_PRODUCER_NEXT_CANDIDATE",
    "AI_PRODUCER_PICKER",
    "AI_PRODUCER_PICKER_CALL",
    "AI_PRODUCER_PICKER_CALL_BYTES",
    "AI_PRODUCER_PICKER_ENTRY",
    "AI_PRODUCER_USABLE_TESTS",
    "APPEND_MESSAGE_VTABLE_SLOT",
    "ARG_APPENDERS",
    "ASCII_STRING_FORMAT",
    "ASCII_STRING_SET",
    "ASCII_STRING_SET_BYTES",
    "AUTO_DEPOSIT_AMOUNT",
    "AUTO_DEPOSIT_DEPOSIT",
    "AUTO_DEPOSIT_DEPOSIT_BYTES",
    "AUTO_DEPOSIT_DEPOSIT_RESUME",
    "AUTO_DEPOSIT_FIELD_TABLE",
    "AUTO_DEPOSIT_FIELD_TABLE_REFS",
    "AUTO_DEPOSIT_FIELD_TABLE_REF_OPCODES",
    "AUTO_DEPOSIT_FILTER_EBP",
    "AUTO_DEPOSIT_GIVE_NO_XP",
    "AUTO_DEPOSIT_MODULE_DATA_CTOR",
    "AUTO_DEPOSIT_MODULE_DATA_CTOR_BOOLS",
    "AUTO_DEPOSIT_MODULE_DATA_CTOR_BOOLS_BYTES",
    "AUTO_DEPOSIT_MODULE_DATA_EBP",
    "AUTO_DEPOSIT_MODULE_DATA_ESI",
    "AUTO_DEPOSIT_MODULE_DATA_SIZE",
    "AUTO_DEPOSIT_MULTIPLIER_EBP",
    "AUTO_DEPOSIT_OBJECT_ESI",
    "AUTO_DEPOSIT_PAY",
    "AUTO_DEPOSIT_PAY_BYTES",
    "AUTO_DEPOSIT_PAY_RESUME",
    "AUTO_DEPOSIT_SCALE",
    "AUTO_DEPOSIT_SCALE_AMOUNT_EBP",
    "AUTO_DEPOSIT_SCALE_BYTES",
    "AUTO_DEPOSIT_SCALE_RESUME",
    "AUTO_DEPOSIT_TRUNCATE",
    "AUTO_DEPOSIT_TRUNCATE_BYTES",
    "AUTO_DEPOSIT_TRUNCATE_RESUME",
    "AUTO_DEPOSIT_XP_GATE",
    "AUTO_DEPOSIT_XP_GATE_BYTES",
    "AUTO_DEPOSIT_XP_GATE_RESUME",
    "AUTO_DEPOSIT_XP_GATE_SKIP",
    "BUILD",
    "BUILD_ASSISTANT_VTABLE",
    "BUILD_GATE_AFFORD",
    "BUILD_GATE_AFFORD_BYTES",
    "BUILD_GATE_AFFORD_OK",
    "BUILD_GATE_AFFORD_REFUSE",
    "BUILD_GATE_COMMAND_POINTS",
    "BUILD_GATE_COMMAND_POINTS_BYTES",
    "BUILD_GATE_COMMAND_POINTS_OK",
    "BUILD_GATE_COMMAND_POINTS_REFUSE",
    "BUILD_GATE_NOT_ENOUGH_COMMAND_POINTS",
    "BUILD_GATE_NOT_ENOUGH_MONEY",
    "BUILD_GATE_TEMPLATE_EBP",
    "CAMPAIGN_ADVANCE_GATE",
    "CAMPAIGN_LIST_PREDICATE",
    "CAMPAIGN_NAME_BIND",
    "CAMPAIGN_NAME_BIND_BYTES",
    "CAMPAIGN_NAME_STATIC",
    "CAMPAIGN_NAME_STATIC_GUARD",
    "CAMPAIGN_SELECT_GATE",
    "CAN_MAKE_UNIT",
    "CAN_MAKE_UNIT_ACCEPT",
    "CAN_MAKE_UNIT_BUMP_SLOT",
    "CAN_MAKE_UNIT_NEXT_SLOT",
    "CAN_MAKE_UNIT_PRODUCTION_GATE",
    "CAN_MAKE_UNIT_PRODUCTION_GATE_CALL",
    "CAN_MAKE_UNIT_PRODUCTION_GATE_CALL_BYTES",
    "CAN_MAKE_UNIT_PRODUCTION_GATE_SLOT",
    "CAN_MAKE_UNIT_REVIVE_BRANCH",
    "CAN_MAKE_UNIT_REVIVE_BRANCH_ENTRY",
    "CAN_MAKE_UNIT_SCAN_BOUND",
    "CAN_MAKE_UNIT_UPGRADE_GATE",
    "CAN_MAKE_UNIT_VTABLE_SLOT",
    "CAN_USE_SPECIAL_POWER",
    "CAN_USE_SPECIAL_POWER_ENTRY",
    "CLEAR_GAME_DATA",
    "CLI_COUNT_REF",
    "CLI_DISPATCH",
    "CLI_TABLE",
    "CLI_TABLE_BYTES",
    "CLI_TABLE_ENTRIES",
    "CLI_TABLE_FINGERPRINT",
    "CLI_TABLE_REF",
    "COMMAND_BUTTON_AUTO_ABILITY",
    "COMMAND_BUTTON_COMMAND",
    "COMMAND_BUTTON_CTOR",
    "COMMAND_BUTTON_CTOR_AUTO_ABILITY",
    "COMMAND_BUTTON_CTOR_AUTO_ABILITY_BYTES",
    "COMMAND_BUTTON_FIELD_TABLE",
    "COMMAND_BUTTON_FIELD_TABLE_REFS",
    "COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES",
    "COMMAND_BUTTON_FREE_OFFSET",
    "COMMAND_BUTTON_SIZE",
    "COMMAND_BUTTON_SPECIAL_POWER",
    "COMMAND_POINTS_HAS_ENOUGH",
    "COMMAND_POINTS_IN_USE",
    "CONTROL_BAR_UNAVAILABLE",
    "CONTROL_BAR_UNIT_COST_CALL",
    "CONTROL_BAR_UNIT_COST_CALL_BYTES",
    "CRC_EXCLUDE_SHROUD_FLAG",
    "CRT_ATOI",
    "DEBUG_CRASH_EXCEPTION_CODE",
    "DEBUG_CRASH_MESSAGE_EBP",
    "DEBUG_CRASH_MESSAGE_READ",
    "DEBUG_CRASH_MESSAGE_READ_BYTES",
    "DEBUG_CRASH_MODE_EBP",
    "DEBUG_CRASH_RAISE",
    "DEBUG_CRASH_RAISE_BYTES",
    "DEBUG_CRASH_RAISE_RESUME",
    "DEBUG_CRASH_RAISE_RESUME_BYTES",
    "DEBUG_CRASH_TAG_EBP",
    "DEBUG_CRASH_TAG_STORE",
    "DEBUG_CRASH_TAG_STORE_BYTES",
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
    "DICT_SET_ASCII_STRING",
    "DICT_SET_ASCII_STRING_BYTES",
    "DISPLAY_DRAW_VTABLE_SLOT",
    "DO_COMMAND_BUTTON",
    "DO_COMMAND_BUTTON_BUTTON_EBP",
    "DO_COMMAND_BUTTON_REVIVE_QUEUE",
    "DO_COMMAND_BUTTON_REVIVE_QUEUE_BYTES",
    "DO_COMMAND_BUTTON_REVIVE_QUEUE_RESUME",
    "DO_COMMAND_BUTTON_UNIT_QUEUE",
    "DO_COMMAND_BUTTON_UNIT_QUEUE_BYTES",
    "DO_COMMAND_BUTTON_UNIT_QUEUE_RESUME",
    "DO_COMMAND_UPGRADE_GET",
    "DO_COMMAND_UPGRADE_REMOVE",
    "DO_SPECIAL_POWER_SITES",
    "FIELD_PARSE_STRIDE",
    "FLOAT_ONE",
    "FLOAT_ONE_PERCENT",
    "FLOAT_TWO_PERCENT",
    "GAME_CLIENT_DRAW",
    "GAME_CLIENT_DRAW_BYTES",
    "GAME_DATA_ASCIISTRING_PARSER",
    "GAME_DATA_BOOL_PARSER",
    "GAME_DATA_SHELL_MAP_NAME_ROW",
    "GAME_INFO_MAP",
    "GAME_LOGIC_FRAME",
    "GAME_LOGIC_IS_IN_GAME",
    "GAME_LOGIC_UPDATE",
    "GAME_LOGIC_UPDATE_ENTRY",
    "GAME_LOGIC_UPDATE_VTABLE_SLOT",
    "GAME_MODE_SKIRMISH",
    "GAME_TEXT_FORMAT_SLOT",
    "GET_FINAL_OVERRIDE",
    "GLOBAL_DATA",
    "GLOBAL_DATA_FPS_LIMIT",
    "GLOBAL_DATA_USE_FPS_LIMIT",
    "GUICOMMAND_REVIVE",
    "GUI_COMMAND_SPECIAL_POWER",
    "GUI_LOSE_CASH",
    "IMAGE_BASE",
    "IMPORT_FFLUSH",
    "IMPORT_FWRITE",
    "IMPORT_GET_LOCAL_TIME",
    "IMPORT_SWPRINTF",
    "INI_NEXT_TOKEN_OR_NULL",
    "INI_PARSE_BOOL",
    "INI_PARSE_INT",
    "INI_PARSE_REAL",
    "INI_PARSE_UNSIGNED_SHORT",
    "INI_SCAN_INT",
    "IN_GAME_UI_ADD_FLOATING_TEXT",
    "IS_MULTIPLAYER_GAME",
    "IS_MULTIPLAYER_OR_ITS_REPLAY",
    "IS_MULTIPLAYER_OR_ITS_REPLAY_BYTES",
    "IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY",
    "IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY_BYTES",
    "KEY_PLAYER_AI_TYPE",
    "KEY_PLAYER_AI_TYPE_BYTES",
    "LIVE_CAMPAIGN_MODE_OFFSET",
    "LIVING_WORLD_OVERRIDE_OFFSET",
    "LIVING_WORLD_OVERRIDE_ROW",
    "LOGIC_CRC_EMIT",
    "LOGIC_CRC_EMIT_BYTES",
    "LOGIC_CRC_EMIT_RESUME",
    "LOGIC_CRC_SHROUD_XFER",
    "LOGIC_CRC_SHROUD_XFER_BYTES",
    "LOSE_CASH_COLOR",
    "LOSE_CASH_RISE",
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
    "MAX_PLAYER_COUNT",
    "MINI_DUMP_ARGS",
    "MINI_DUMP_ARGS_BYTES",
    "MINI_DUMP_ARGS_RESUME",
    "MINI_DUMP_ARGS_RESUME_BYTES",
    "MINI_DUMP_EXCEPTION_INFO_EBP",
    "MINI_DUMP_FULL_DUMP_EBP",
    "MINI_DUMP_NULL_EDI",
    "MINI_DUMP_NULL_EDI_BYTES",
    "MISSION_OBJECTIVE_LIST_OFFSET",
    "MISSION_OBJECTIVE_TRACKER",
    "MONEY_AMOUNT",
    "MONEY_DEPOSIT",
    "MONEY_WITHDRAW",
    "MSG_CLEAR_GAME_DATA",
    "MSG_NEW_GAME",
    "OBJECT_CONTAIN",
    "OBJECT_FIELD_TABLE",
    "OBJECT_FIELD_TABLE_REFS",
    "OBJECT_FIELD_TABLE_REF_OPCODES",
    "OBJECT_FILTER_ALLOW",
    "OBJECT_FILTER_IS_VALID",
    "OBJECT_ID",
    "OBJECT_MODULE_LIST",
    "OBJECT_POSITION",
    "OBJECT_PRODUCER_ID",
    "OBJECT_STATUS",
    "OBJECT_STATUS_COUNT",
    "OBJECT_STATUS_DWORDS",
    "OBJECT_STATUS_NAMES",
    "OBJECT_STATUS_UNDER_CONSTRUCTION",
    "OBJECT_TEST_STATUS",
    "OBJECT_THING_TEMPLATE",
    "OBSERVER_BAR_GATE_CALL",
    "OBSERVER_BAR_GATE_CALL_BYTES",
    "OBSERVER_BAR_GATE_FINGERPRINT",
    "OBSERVER_BAR_GATE_FINGERPRINT_BYTES",
    "OBSERVER_BAR_HIDE",
    "OBSERVER_BAR_SHOW",
    "OPERATOR_NEW",
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
    "PLAYBACK_INSTALLS_OBSERVER",
    "PLAYER_COMMAND_POINTS_USED",
    "PLAYER_DEFEAT_FRAME",
    "PLAYER_FOR_EACH_TEAM_OBJECT",
    "PLAYER_INDEX",
    "PLAYER_INIT",
    "PLAYER_INIT_ENTRY",
    "PLAYER_INIT_ENTRY_BYTES",
    "PLAYER_INIT_ENTRY_RESUME",
    "PLAYER_INIT_FROM_DICT",
    "PLAYER_INIT_FROM_DICT_BYTES",
    "PLAYER_IS_DEFEATED",
    "PLAYER_IS_OBSERVER",
    "PLAYER_LIST_GET_LOCAL_PLAYER",
    "PLAYER_LIST_LOCAL_IS_NOT_ACTIVE",
    "PLAYER_LIST_LOCAL_PLAYER",
    "PLAYER_LIST_OBSERVE_NEXT_PLAYER",
    "PLAYER_MONEY",
    "PLAYER_PLAYER_TEMPLATE",
    "PLAYER_SCORE_KEEPER",
    "PLAYER_SET_TYPE",
    "PLAYER_SET_TYPE_BYTES",
    "PLAYER_SKIRMISH_FOUND_EBP",
    "PLAYER_SKIRMISH_IMPORT",
    "PLAYER_SKIRMISH_IMPORT_BYTES",
    "PLAYER_SKIRMISH_IMPORT_RESUME",
    "PLAYER_SKIRMISH_IMPORT_SKIP",
    "PLAYER_SKIRMISH_IMPORT_SKIP_BYTES",
    "PLAYER_SKIRMISH_MISSING_EBP",
    "PLAYER_SKIRMISH_ROUTE",
    "PLAYER_SKIRMISH_ROUTE_BYTES",
    "PLAYER_SKIRMISH_ROUTE_RESUME",
    "PLAYER_TEMPLATE_BLOCK_KEY",
    "PLAYER_TEMPLATE_BLOCK_KEY_BYTES",
    "PLAYER_TEMPLATE_BLOCK_KEY_EARLY",
    "PLAYER_TEMPLATE_BLOCK_KEY_EARLY_BYTES",
    "PLAYER_TEMPLATE_BLOCK_KEY_EARLY_RESUME",
    "PLAYER_TEMPLATE_BLOCK_KEY_RESUME",
    "PLAYER_TEMPLATE_DEFAULT_AI_TYPE",
    "PLAYER_TEMPLATE_FIELD_DEFAULT_AI_TYPE",
    "PLAYER_TEMPLATE_FIELD_DEFAULT_AI_TYPE_BYTES",
    "PLAYER_TEMPLATE_FIELD_TABLE",
    "PLAYER_TEMPLATE_FIELD_TABLE_REFS",
    "PLAYER_TEMPLATE_FIELD_TABLE_REF_OPCODES",
    "PLAYER_TEMPLATE_FIND_BY_KEY",
    "PLAYER_TEMPLATE_NAME_KEY",
    "PLAYER_TEMPLATE_PTR",
    "PLAYER_TEMPLATE_RESOURCE_FILTER",
    "PLAYER_TEMPLATE_RESOURCE_VALUES",
    "PLAYER_TEMPLATE_SIZE",
    "PRODUCTION_UPDATE_COMMAND_POINT_STALL",
    "PRODUCTION_UPDATE_INTERFACE_VTABLE",
    "PRODUCTION_UPDATE_REVIVE_COMMAND_POINT_DELAY",
    "PRODUCTION_UPDATE_VTABLE",
    "PRODUCTION_WITHDRAW",
    "PRODUCTION_WITHDRAW_BYTES",
    "PRODUCTION_WITHDRAW_PLAYER_EBP",
    "PRODUCTION_WITHDRAW_RESUME",
    "PRODUCTION_WITHDRAW_TEMPLATE_EBP",
    "RECORDER_END_BRANCH",
    "RECORDER_END_BRANCH_BYTES",
    "RECORDER_END_STOP_CALL",
    "RECORDER_END_STOP_CALL_BYTES",
    "RECORDER_END_STOP_SETUP",
    "RECORDER_END_STOP_SETUP_BYTES",
    "RECORDER_END_WRITE_CALL",
    "RECORDER_END_WRITE_CALL_BYTES",
    "RECORDER_FILE",
    "RECORDER_GAME_MODE",
    "RECORDER_GAME_MODE_RESET",
    "RECORDER_LAST_REPLAY_NAME",
    "RECORDER_LOCAL_PLAYER_INDEX",
    "RECORDER_MODE",
    "RECORDER_MODE_GATE",
    "RECORDER_MODE_GATE_ACCEPT",
    "RECORDER_MODE_GATE_BYTES",
    "RECORDER_MODE_GATE_REJECT",
    "RECORDER_MODE_PLAYBACK",
    "RECORDER_MODE_RECORD",
    "RECORDER_NAME_CALL",
    "RECORDER_NAME_CALL_BYTES",
    "RECORDER_NAME_CALL_FINGERPRINT",
    "RECORDER_NEW_GAME_BRANCH",
    "RECORDER_NEW_GAME_BRANCH_BYTES",
    "RECORDER_RECORDED_MODES",
    "RECORDER_RESET_WRITES_GAME_MODE",
    "RECORDER_STOP_RECORDING",
    "RECORDER_WRITE_TO_FILE",
    "REQUEST_UNIQUE_UNIT_ID",
    "REQUEST_UNIQUE_UNIT_ID_BODY",
    "REQUEST_UNIQUE_UNIT_ID_VTABLE_SLOT",
    "RESOURCE_MODIFIER_COUNT_CALLBACK",
    "SCORE_KEEPER_ADD_OBJECT_DESTROYED",
    "SCORE_KEEPER_ADD_OBJECT_LOST",
    "SCORE_KEEPER_COUNTER_BLOCK",
    "SCORE_KEEPER_COUNTER_BLOCK_DWORDS",
    "SCORE_KEEPER_END_FRAME",
    "SCORE_KEEPER_LAYOUT_SITES",
    "SCORE_KEEPER_MONEY_EARNED",
    "SCORE_KEEPER_MONEY_SPENT",
    "SCORE_KEEPER_PLAYER_REF",
    "SCORE_KEEPER_PLAYER_REF_BYTES",
    "SCORE_KEEPER_STRUCTURES_ALIVE",
    "SCORE_KEEPER_STRUCTURES_BUILT",
    "SCORE_KEEPER_STRUCTURES_DESTROYED",
    "SCORE_KEEPER_STRUCTURES_LOST",
    "SCORE_KEEPER_UNITS_ALIVE",
    "SCORE_KEEPER_UNITS_BUILT",
    "SCORE_KEEPER_UNITS_DESTROYED",
    "SCORE_KEEPER_UNITS_LOST",
    "SHROUD_CELLS",
    "SHROUD_CELLS_X",
    "SHROUD_CELLS_Y",
    "SHROUD_CELL_SIZE",
    "SHROUD_CELL_STRIDE",
    "SHROUD_FOG_ENABLED",
    "SHROUD_IMPL",
    "SHROUD_INV_CELL_SIZE",
    "SHROUD_ORIGIN_X",
    "SHROUD_ORIGIN_Y",
    "SHROUD_RECORD_BASE",
    "SHROUD_RECORD_STRIDE",
    "SIDES_INFO_DICT",
    "SIDES_LIST_GET_SIDE_INFO",
    "SIDES_LIST_GET_SIDE_INFO_BYTES",
    "SIDES_LIST_LOAD_AI_LIBRARY_FOR_SIDE",
    "SIDES_LIST_LOAD_AI_LIBRARY_FOR_SIDE_BYTES",
    "SPECIAL_POWER_FIELD_TABLE",
    "SPECIAL_POWER_FIELD_TABLE_REFS",
    "SPECIAL_POWER_FIELD_TABLE_REF_OPCODES",
    "SPECIAL_POWER_TEMPLATE_COPY_TAIL",
    "SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES",
    "SPECIAL_POWER_TEMPLATE_NEW_SITES",
    "SPECIAL_POWER_TEMPLATE_SIZE",
    "SPECIAL_POWER_UNIT_COST",
    "START_RECORDING",
    "START_RECORDING_MODE_ARG",
    "STATIC_NAME_KEY_KEY",
    "STATIC_NAME_KEY_KEY_BYTES",
    "TERRAIN_RESOURCE_BUILD_FIELD_PARSE",
    "TERRAIN_RESOURCE_DEFAULT_STORES",
    "TERRAIN_RESOURCE_DEFAULT_STORES_BYTES",
    "TERRAIN_RESOURCE_EXP_BLOCK",
    "TERRAIN_RESOURCE_EXP_BLOCK_BYTES",
    "TERRAIN_RESOURCE_EXP_BLOCK_RESUME",
    "TERRAIN_RESOURCE_EXP_BLOCK_SKIP",
    "TERRAIN_RESOURCE_FIELD_TABLE",
    "TERRAIN_RESOURCE_FIELD_TABLE_PUSH",
    "TERRAIN_RESOURCE_FIELD_TABLE_PUSH_BYTES",
    "TERRAIN_RESOURCE_FIELD_TABLE_STOCK",
    "TERRAIN_RESOURCE_FLOOR",
    "TERRAIN_RESOURCE_FLOOR_BYTES",
    "TERRAIN_RESOURCE_FLOOR_RESUME",
    "TERRAIN_RESOURCE_FREE_OFFSET",
    "TERRAIN_RESOURCE_INCOME_FLOAT_EBP",
    "TERRAIN_RESOURCE_INCOME_GATE",
    "TERRAIN_RESOURCE_INCOME_GATE_BYTES",
    "TERRAIN_RESOURCE_MODULE_DATA_CTOR",
    "TERRAIN_RESOURCE_MODULE_DATA_EBP_SLOT",
    "TERRAIN_RESOURCE_MODULE_DATA_SIZE",
    "TERRAIN_RESOURCE_PAY",
    "TERRAIN_RESOURCE_PAY_BYTES",
    "TERRAIN_RESOURCE_PAY_RESUME",
    "TERRAIN_RESOURCE_UPDATE",
    "TERRAIN_RESOURCE_UPDATE_VTABLE",
    "TERRAIN_RESOURCE_UPDATE_VTABLE_SLOT",
    "TEXT_SECTION_LEN",
    "TEXT_SECTION_VA",
    "THE_BUILD_ASSISTANT",
    "THE_DISPLAY",
    "THE_GAME_INFO",
    "THE_GAME_LOGIC",
    "THE_GAME_STATE",
    "THE_GAME_TEXT",
    "THE_IN_GAME_UI",
    "THE_MESSAGE_STREAM",
    "THE_PARTITION_MANAGER",
    "THE_PLAYER_LIST",
    "THE_RECORDER",
    "THE_SCIENCE_STORE",
    "THE_SHROUD_MANAGER",
    "THE_SIDES_LIST",
    "THE_SIDES_LIST_LOAD",
    "THE_SIDES_LIST_LOAD_BYTES",
    "THE_SKIRMISH_GAME_INFO",
    "THE_SPECIAL_POWER_STORE",
    "THE_TACTICAL_VIEW",
    "THE_THING_FACTORY",
    "THE_UPGRADE_CENTER",
    "THE_VICTORY_CONDITIONS",
    "THING_TEMPLATE_BUILD_COST",
    "THING_TEMPLATE_COPY_CALL",
    "THING_TEMPLATE_COPY_CALL_BYTES",
    "THING_TEMPLATE_COPY_FROM",
    "THING_TEMPLATE_COPY_ID",
    "THING_TEMPLATE_COPY_ID_BYTES",
    "THING_TEMPLATE_COPY_ID_RESUME",
    "THING_TEMPLATE_ID",
    "THING_TEMPLATE_ID_COUNTER",
    "THING_TEMPLATE_ID_SETTER",
    "THING_TEMPLATE_REFUND_VALUE",
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
    "VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY",
    "VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY_SLOT",
    "VICTORY_CONDITIONS_HAS_BEEN_DEFEATED",
    "VICTORY_CONDITIONS_HAS_BEEN_DEFEATED_SLOT",
    "VICTORY_CONDITIONS_IS_DEFEATED",
    "VICTORY_CONDITIONS_PLAYERS",
    "VICTORY_CONDITIONS_VTABLE",
    "VIEW_GET_LOCATION_VTABLE_SLOT",
    "VIEW_LOCATION_SIZE",
    "VIEW_POSITION_OFFSET",
    "VIEW_SET_LOCATION_VTABLE_SLOT",
    "WIDE_BLANK_LINE",
    "WIDE_BLANK_LINE_BYTES",
    "WIDE_NEWLINE",
    "WIDE_NEWLINE_BYTES",
    "WRITE_MINI_DUMP",
    "WRITE_MINI_DUMP_BYTES",
]

BUILD = "RotWK 2.01.2614.37001"
IMAGE_BASE = 0x00400000

# `.text`, as this build's section table maps it. The image carries no `.reloc` and does not opt
# into `DYNAMIC_BASE`, so the loader places it at `IMAGE_BASE` and never rewrites a byte of it:
# the code in memory is the code in the file. That is what lets `binary-attest` hash this range
# at runtime and lets the same hash be recomputed offline from the file - see
# `docs/binary-attest.md`.
TEXT_SECTION_VA = 0x00401000
TEXT_SECTION_LEN = 0x007CF000

# The `MSG_LOGIC_CRC` emitter in `GameLogic::update`, per `docs/message-stream.md` section 1. Two
# paths compute the frame CRC into `edi` (`0x0062E7CE` and `0x0062E7F4`) and both converge here,
# so a hook at this join sees the value on every route to it. `0x0062E7E2` jumps to exactly this
# address and nothing in the function targets the five bytes after it, so the six displaced bytes
# can be taken whole.
LOGIC_CRC_EMIT = 0x0062E7FD
LOGIC_CRC_EMIT_BYTES = bytes.fromhex("8b0d9863de00")  # mov ecx, [TheMessageStream]
LOGIC_CRC_EMIT_RESUME = 0x0062E803

# `mov eax, [TheShroudManager]` inside the CRC producer at `0x00625886`, where the shroud manager
# is xfer'd into the frame checksum like every other logic subsystem.
#
# **This is the anchor for the claim the whole patch rests on**: fog of war is already part of the
# sync hash on this build, so a client whose *shroud state* diverges already desyncs, and
# attestation is aimed at the remaining hole - a client whose shroud state agrees because only its
# code was changed. The contribution is guarded by `-xShroudCRC` (`0x00DE87BF`), which excludes it;
# absent that flag it is always included.
LOGIC_CRC_SHROUD_XFER = 0x00625983
LOGIC_CRC_SHROUD_XFER_BYTES = bytes.fromhex("a15843de00")
CRC_EXCLUDE_SHROUD_FLAG = 0x00DE87BF

# Subsystem singletons. Each address holds a *pointer to* the object, not the object; they are
# registered by name at startup, which is how they were found (see `docs/engine-globals.md`
# for the full 88).
THE_GAME_LOGIC = 0x00DE412C
THE_PLAYER_LIST = 0x00DE4928
THE_MESSAGE_STREAM = 0x00DE6398
THE_IN_GAME_UI = 0x00DE4830
THE_GAME_STATE = 0x00DE4AD4
THE_RECORDER = 0x00DE7CD8
THE_BUILD_ASSISTANT = 0x00DE8200
THE_VICTORY_CONDITIONS = 0x00DE89AC

# `ThePartitionManager` and `TheShroudManager`, the two subsystems holding visibility state.
#
# ⚠ **`THE_PARTITION_MANAGER` used to read `0x00DE4358`, which is `TheShroudManager`.** The old
# value came from reading the registration block as "the object built immediately after the name
# string is pushed"; the block actually pushes each name *after* storing the object it names, so
# that reading was one slot late. The decisive instruction is the `setName` call site, which
# reloads the global it is about to name:
#
#     0x0062CEB3  mov [0x00DE4354], eax      ; store the object
#     0x0062CECB  push 0x00BFDC08            ; "ThePartitionManager"
#     0x0062CED5  mov ecx, [0x00DE4354]      ; <- names the object stored above
#     0x0062CEDB  call 0x0046EC7F            ; setName
#
# Both are now **confirmed live** rather than statically: each object holds its own name as an
# `AsciiString` at `+0x08`, and reading it back gives `ThePartitionManager` at `0x00DE4354` and
# `TheShroudManager` at `0x00DE4358` (`TheTaintManager` and `TheCollisionManager` follow at
# `0x00DE435C` and `0x00DE4360`). Nothing consumed the wrong value, so this corrects a
# declaration rather than a behaviour.
THE_PARTITION_MANAGER = 0x00DE4354

# `TheShroudManager` owns the per-cell, per-player visibility grid that fog filtering needs.
# See `docs/fog-of-war.md` for the model and `sage_live.backends.shroud` for the reader.
#
# Both managers are 20-byte **facades**: every method is `mov ecx, [ecx+0x10]; jmp <impl>`, so
# the real object is the one at `+0x10` and every offset below is relative to *that*.
THE_SHROUD_MANAGER = 0x00DE4358

# The facade's pointer to the 0x70-byte implementation object.
SHROUD_IMPL = 0x10

# Implementation fields, all confirmed live on RotWK 2.01 + Edain.
SHROUD_ORIGIN_X = 0x04
SHROUD_ORIGIN_Y = 0x08
SHROUD_CELL_SIZE = 0x1C  # 40.0 world units on the measured map
SHROUD_INV_CELL_SIZE = 0x20  # 0.025 - the reciprocal the engine actually multiplies by
SHROUD_CELLS_X = 0x24
SHROUD_CELLS_Y = 0x28
SHROUD_CELLS = 0x2C  # the cell array, row-major: index `cells_x * cy + cx`
SHROUD_FOG_ENABLED = 0x68  # one byte, 0 when the match runs with fog switched off

# One cell is 0xA8 bytes: a 4-byte head, then 20 eight-byte per-player records. The first `u16`
# of a record is that player's shroud level; the other three are the cell's value maps.
SHROUD_CELL_STRIDE = 0xA8
SHROUD_RECORD_BASE = 0x04
SHROUD_RECORD_STRIDE = 0x08

# The lobby description of the game being played - map, seed, slots, factions - and the source
# `RecorderClass::startRecording` builds a replay header's metadata string from.
#
# `TheGameInfo` is whichever flavour is live (`LANGameInfo`, the GameSpy one, or the skirmish
# one); `TheSkirmishGameInfo` is the skirmish menu's own, and the skirmish setup screen assigns
# it to both (`0x006309BF` is `TheGameInfo = TheSkirmishGameInfo`). Reading the first and
# falling back to the second is what lets a cave name the map without reproducing
# `startRecording`'s three-way branch on the network session object.
THE_GAME_INFO = 0x00DE892C
THE_SKIRMISH_GAME_INFO = 0x00DE8930

# `GameInfo::m_map`, an `AsciiString` holding the map path as it appears in the metadata `M=`
# field (`maps/map mp westfold`). `getMap` (`0x00627692`) is a plain copy of it, and `setMap`
# (`0x00801C46`) writes it, so a cave can read the member instead of constructing a copy it
# would then have to destroy. An `AsciiString` is one pointer; the characters begin at `+8`,
# and a null pointer is the empty string.
GAME_INFO_MAP = 0x40

# `MAX_PLAYER_COUNT`. Every per-player array the engine embeds is this wide; see
# `docs/max-player-count.md` for why it cannot be raised.
MAX_PLAYER_COUNT = 20

# The four id-space stores. `sage_live.utils.resolve` reconstructs these spaces from ini;
# reading the engine's own tables instead is the alternative, and two of the four are now read
# that way.
#
# `TheUpgradeCenter` settled the upgrade `+3` (order_space_map OPEN 4: three engine-registered
# veterancy upgrades ahead of the ini's first) and is what `sage_live.backends.memory` names
# upgrade bits with. `TheThingFactory` has the same shape - list head at `+0x0C`, count at
# `+0x10`, and `ThingTemplate+0x494` for `next` - and `sage_live.backends.memory.thing_order`
# walks it, so a policy can name a template with no ini load. Both are derived in
# `docs/live-object-model.md` sections 3b and 3c.
#
# `TheSpecialPowerStore` is walked too, and is the reason to check the *shape* before assuming
# one: it is a `std::vector` (`{begin, end, capacity}` at `+0x0C`), not a linked list, which is
# why a list walk found nothing there. Its 1,566 names agree with the ini reconstruction
# position by position on every entry. `TheScienceStore` has the same vector shape and exactly
# the 263 entries the ini defines, but its elements are separately allocated at *different
# sizes*, so no fixed offset names them and it is still unwalked.
THE_THING_FACTORY = 0x00DE4A40
THE_UPGRADE_CENTER = 0x00DE45A0
THE_SPECIAL_POWER_STORE = 0x00DE878C
THE_SCIENCE_STORE = 0x00DE3B20

# `GameLogic::update` - the per-logic-frame callback on the logic thread.
#
# It is **virtual**, dispatched through the vtable slot below, so it has no `call rel32`
# xrefs and cannot be found by following calls. Anything hooking it should assert the slot
# still names it: a hook on a function nothing dispatches to installs perfectly, never fires,
# and is indistinguishable from a working patch.
GAME_LOGIC_UPDATE = 0x0062E4E8
GAME_LOGIC_UPDATE_VTABLE_SLOT = 0x00BD85C4
GAME_LOGIC_UPDATE_ENTRY = bytes.fromhex("b8da41b800")  # mov eax, 0xB841DA - exactly 5 bytes

# `GameLogic::m_frame`, the logic-frame counter. It is what the recorder stamps every replay
# chunk with (`RecorderClass::writeToFile` reads it, not the message), so anything writing a
# chunk of its own has to use the same source to land on the same timecode.
GAME_LOGIC_FRAME = 0x40

# `Object::m_id`. Measured, not inferred: for **386 of 386** live objects in the recorded match
# `tests/sage_live/fixtures/match.snapshot.gz`, the dword here equals the id `TheGameLogic`'s
# object table carries beside the `Object*`, and no other offset in the first `0x400` bytes
# matched more than a handful. See `docs/live-object-model.md` section 2.
#
# ⚠ **The id space is not dense.** 382 of those 386 sat at `slot == id`; four engine-reserved
# objects held ids `99999996`..`99999999` at slots 4403-4406. Anything indexing an array by this
# value must fold or bound it - see `patches/experimental/hero_mana.py`, which masks it.
OBJECT_ID = 0x74

# The **second** `ObjectID` on an object, immediately after its own, and the engine's fallback
# answer to "which horde does this belong to": `resolveAttackTarget` (`0x00668167`) looks it up
# through `GameLogic::findObjectByID` when `m_containedBy` is null, and treats the result as
# this object's horde if it is `KINDOF HORDE`. In the Generals-lineage layout that field is
# `m_producerID` - who made me - which fits what the fallback is for and is why an object that
# has *left* its horde still resolves back to it. Not measured live; see
# `docs/horde-formation-orphans.md` section 6.
#
# Corroborated statically from a second, unrelated consumer: on a structure standing on a build
# plot this field is the **plot**, written by the build path (`0x00857AEA`) and by the plot's own
# first-update adopt scan (`0x008584C7`), and read by `GettingBuiltBehavior::onDelete`
# (`0x0085757F`) to free that plot when the structure goes away. Two producers and one consumer
# that all mean "who made me" is about as far as this can be taken without a debugger; see
# `docs/foundation-rebind.md` section 2.1.
OBJECT_PRODUCER_ID = 0x78

# `Object::m_status`, the `ObjectStatusMaskType` bitset - 4 dwords, so 128 slots for the 106
# names this build defines. Recovered from the one helper every test site goes through,
# `Object::testStatus(bit)` at `0x0044DDEC`, whose body is
# `and eax, [esi + edx*4 + 0x94]` with `edx = bit >> 5`.
#
# The bit numbering is the name table's index order, corroborated by the call sites rather than
# assumed: 91 of them push a literal bit, and all 39 distinct values name a status that makes
# sense where it is used - `HORDE_MEMBER` (38) in the horde target resolver, `IS_LEAVING_FACTORY`
# (90) in the stance module's wait, `UNDER_CONSTRUCTION` (2) thirteen times.
OBJECT_STATUS = 0x94
OBJECT_STATUS_DWORDS = 4
OBJECT_TEST_STATUS = 0x0044DDEC

# The `ObjectStatus` names, a flat `const char*[]` in static data, in bit order and NULL
# terminated. Index 0 is `DESTROYED`; the last named slot is 105, `USER_DEFINED_2`.
OBJECT_STATUS_NAMES = 0x00D8AFF0
OBJECT_STATUS_COUNT = 106

# `Object::m_contain`, the `ContainModuleInterface*` a horde or transport carries and a lone
# unit does not. Vtable `+0x7c` returns the horde interface, whose `+0x188` is the member count.
# This is the field that makes `SpecialPower.UnitCost` a no-op on a hero: all three of the
# engine's `UnitCost` sites skip the check outright when it is null, rather than failing it.
OBJECT_CONTAIN = 0x258

#
# The activation path, end to end, as `docs/hero-mana.md` derives it:
#
#   order/UI -> Object::doSpecialPower*  -> SpecialPowerStore::canUseSpecialPower  (the predicate)
#                                        -> Object::getSpecialPowerModule          (the module)
#                                        -> module vtable +0x2c / +0x30 / +0x34    (the effect)

#: `Overridable::getFinalOverride`. **Every** template field read goes through it - an INI
#: override block is a copy further down a chain, and reading the base misses it.
GET_FINAL_OVERRIDE = 0x00688D3C

#: Where an ability *actually fires*, and the reason the charge cannot sit on the click.
#:
#: A BFME hero ability is a pair: a `SpecialPowerModule` "starter" and a `…SpecialAbilityUpdate`
#: that takes the timing (approach to `StartAbilityRange`, `UnpackTime` wind-up, then the effect).
#: With `UpdateModuleStartsAttack = Yes` the starter does not perform the power at all, so
#: `Object::doSpecialPower*` is never even reached - measured live: casting Gandalf's Word of
#: Power produced zero records at those three sites.
#:
#: `0x00854DF7` is the update's tick, a virtual through vtable `0x00C769EC`. `ebp` is the
#: interface `this` (`mov ebp, ecx`), **not** a frame pointer, so the module reaches back at
#: negative offsets. At `0x00855042` an unpack countdown has just hit zero and the engine pays
#: `UnitCost` - the same instant a mana cost is owed.
ABILITY_TRIGGER = 0x00854DF7
ABILITY_TRIGGER_VTABLE = 0x00C769EC
ABILITY_TRIGGER_PAY = 0x00855042
ABILITY_TRIGGER_PAY_BYTES = bytes.fromhex("8b45f48b7838")
ABILITY_TRIGGER_PAY_RESUME = 0x00855048

#: Reached from the interface `this` the tick runs on: the module data, the owning `Object`, and
#: the module data's `SpecialPowerTemplate`.
ABILITY_TRIGGER_MODULEDATA_EBP = -0x0C
ABILITY_TRIGGER_OBJECT_EBP = -0x08
ABILITY_MODULEDATA_SPECIAL_POWER = 0x38

#: `SpecialPowerStore::canUseSpecialPower(Object*, SpecialPowerTemplate*)` -> bool in `al`.
#: `__thiscall` on `TheSpecialPowerStore`, two stack arguments, `ret 8`. The single affordability
#: predicate: recharge (`module->isReady`), `RequiredSciences`, and `PreventActivationConditions`
#: all resolve inside it, and its six callers are the four `Object::doSpecialPower*` entries plus
#: two AI ones - which is why gating here reaches the AI for free.
CAN_USE_SPECIAL_POWER = 0x007B1D79
CAN_USE_SPECIAL_POWER_ENTRY = bytes.fromhex("b87165b900")  # mov eax, 0xB96571 - exactly 5 bytes

#: The three `Object::doSpecialPower*` variants. Each resolves the module then dispatches through
#: it; the tuple is `(window VA, window bytes, VA just past the window)`. The window is the
#: `mov ecx, <module>` + `call [vtable+slot]` pair (variant 3 also carries the third argument's
#: `push`), which is the last point at which an activation can still be refused.
#:
#: ⚠ Each variant guards its `canUseSpecialPower` call with a caller-supplied bool
#: (`cmp byte ptr [ebp+0x14], 0`), so a caller can ask for the power to fire *without* the
#: predicate. That is why the charge has to re-check rather than trust the gate.
DO_SPECIAL_POWER_SITES = (
    # The targetless one, dispatching through `+0x28`. Missed on the first pass because it sits
    # *before* the other three and uses a different slot - and it is the one a `Command =
    # SPECIAL_POWER` button with no target emits, so Gandalf's Word of Power went through here
    # and nowhere else.
    (0x0068E664, bytes.fromhex("8bceff5028"), 0x0068E669),  # doSpecialPower (targetless)
    (0x0068E73E, bytes.fromhex("8bceff502c"), 0x0068E743),  # doSpecialPower
    (0x0068E7A1, bytes.fromhex("8bceff5030"), 0x0068E7A6),  # doSpecialPowerAtLocation
    (0x0068E7F9, bytes.fromhex("8bceff750cff5034"), 0x0068E801),  # ...AtObject
)

#: `SpecialPowerTemplate`: `0x88` bytes, id at `+0x14`, `UnitCost`/`UnitCostDeathType` the last
#: two fields. The ctor zeroes both at `0x007B2007`/`0x007B200D`, so there is no padding to hide
#: a new field in and the struct has to grow.
SPECIAL_POWER_TEMPLATE_SIZE = 0x88
SPECIAL_POWER_UNIT_COST = 0x80

#: `(push-size VA, operator-new call VA)` for each of the three places a `SpecialPowerTemplate`
#: is allocated. All three are `push 0x88` + `call operator new`; 26 other sites in the image
#: allocate `0x88` bytes for other classes, so the three are named rather than searched for.
SPECIAL_POWER_TEMPLATE_NEW_SITES = (
    (0x007B218E, 0x007B2195),
    (0x007B21DA, 0x007B21DF),
    (0x007B2292, 0x007B2297),
)
OPERATOR_NEW = 0x0042F6E0

#: The copy constructor's epilogue, right after it copies `+0x84`. It copies field by field, so a
#: grown struct has to copy the new fields too or an INI override block that does not mention
#: them loses them. `ebp` holds the *source* here - it is a spare register in this routine, not a
#: frame pointer.
SPECIAL_POWER_TEMPLATE_COPY_TAIL = 0x007B1F53
SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES = bytes.fromhex("8bc35e5d5bc20400")

#: The `SpecialPower` INI field-parse table: 24 entries of
#: `{const char *name, ParseFn, void *userData, UnsignedInt offset}`, an all-zero terminator, and
#: **no slack after it** - `0x00DA6168` is live data. Exactly two references, both bare imm32
#: operands one byte into their instruction: `mov eax, imm32` (the `getFieldParse` accessor) and
#: `push imm32` (the parse call). Two is the smallest repoint of any table this package moves;
#: `production-condition` has sixteen.
SPECIAL_POWER_FIELD_TABLE = 0x00DA5FD8
SPECIAL_POWER_FIELD_TABLE_REFS = (0x007B1ABD, 0x007B2324)
SPECIAL_POWER_FIELD_TABLE_REF_OPCODES = (0xB8, 0x68)

#: The `Object` INI field-parse table - the one an `Object` block is parsed through, writing into
#: a `ThingTemplate`. 191 entries of the same 16-byte shape, all-zero terminator at `0x00DA49E8`,
#: and **five** references, each a bare imm32 one byte into its instruction.
#:
#: There is **no interior reference**. A byte scan reports one at `0x007162A4` pointing at entry
#: 127, but disassembly says `0x007162A4` is `call 0x723CEE`, whose `E8` opcode plus the
#: first three bytes of its displacement happen to spell `0x00DA45E8`. A false positive, so the
#: table relocates as a unit.
OBJECT_FIELD_TABLE = 0x00DA3DF8
OBJECT_FIELD_TABLE_REFS = (0x0073BDF4, 0x0073BEFB, 0x0073BF4F, 0x0073C142, 0x0073E8C9)
OBJECT_FIELD_TABLE_REF_OPCODES = (0xB8, 0x68, 0x68, 0x68, 0x68)

#: `Object::m_template`. `ThingTemplate` is `0x650` bytes; its name is at `+0x64`, `Side` at
#: `+0x6C`, `CommandSet` at `+0x70`.
OBJECT_THING_TEMPLATE = 0x04

#: `ThingTemplate::copyFrom(source)` - `__thiscall`, one stack argument, `ret 4`, copying field by
#: field. `ThingFactory::newOverride` allocates a default-constructed template and calls it, which
#: is the **only** way a `ThingTemplate` is ever duplicated: the other allocation
#: (`ThingFactory::newTemplate`) builds a fresh one that is then parsed. Both are `push 0x650`,
#: and those two are the only `push 0x650` sites in the image.
#:
#: Anything keyed on a `ThingTemplate*` has to ride this call, or an INI override block silently
#: loses whatever the base template carried.
THING_TEMPLATE_COPY_FROM = 0x006D1D80
THING_TEMPLATE_COPY_CALL = 0x006D2781
THING_TEMPLATE_COPY_CALL_BYTES = bytes.fromhex("e8faf5ffff")

#: `INI::parseInt`, the stock `Int` field parser: cdecl `(INI*, void *instance, void *store,
#: const void *userData)`, writing to `store` == `instance + offset`. Both `UnitCost` entries
#: already use it, so a new `Int` field needs no parser of its own.
INI_PARSE_INT = 0x0042EC5E

#: The ControlBar's button-description builder, at its `UnitCost` case.
#:
#: The whole routine is a switch on the `CommandButton`'s GUI command (`+0x14`); case `0x18` is
#: the special-power one, and its body reads `UnitCost` off the button's `SpecialPowerTemplate`
#: (`+0x44`) and appends one formatted line. `..._CASE` is the five-byte `cmp ecx, 0x18` /
#: `jne <done>` pair that guards it, `..._BODY` the instruction just past that pair, and
#: `..._DONE` the label the whole case falls out to.
DESCRIPTION_SPECIAL_POWER_CASE = 0x00808675
DESCRIPTION_SPECIAL_POWER_CASE_BYTES = bytes.fromhex("83f9187530")
DESCRIPTION_UNIT_COST_BODY = 0x0080867A
DESCRIPTION_DONE = 0x008086AA

#: The same builder's **hero revive / recruit** case, at the point its rank line is handed over.
#:
#: That case resolves the hero's `ThingTemplate` through `TheThingFactory::findTemplate` (so `esi`
#: is the template, not the button), appends an `APT:RankLabel` line describing the hero's level,
#: and then folds the accumulated line at `ebp-0x2c` into the description at `ebp-0x18`. The
#: window named here is that fold - `lea ecx, [ebp-0x18]` plus the `call` - which is the last
#: moment another line can join the same batch.
#:
#: `edi` is the function's zero throughout (`xor edi, edi` in its prologue), which is what the
#: middle argument of a formatted line wants.
DESCRIPTION_RANK_APPEND = 0x008085C4
DESCRIPTION_RANK_APPEND_BYTES = bytes.fromhex("8d4de8e832e0bfff")
DESCRIPTION_RANK_RESUME = 0x008085CC

#: `UnicodeString::concat(other)` - `__thiscall`, one stack argument, `ret 4`.
UNICODE_STRING_APPEND = 0x004065FE
UNICODE_STRING_APPEND_BYTES = bytes.fromhex("8b4424048b0085c074060fb7")

#: `UnicodeString::concat(const WideChar *)` - `__thiscall`, one stack argument, `ret 4`. The
#: sibling of :data:`UNICODE_STRING_APPEND` for a literal rather than another `UnicodeString`;
#: both end in the same `0x00436D50` worker with `this` still in `ecx`. It clobbers `eax`.
UNICODE_STRING_CONCAT_WIDE = 0x00405183
UNICODE_STRING_CONCAT_WIDE_BYTES = bytes.fromhex("568b74240885f6578bf9740a")

#: `UnicodeString::operator=(const UnicodeString &)` - `__thiscall`, one stack argument, `ret 4`.
#: It **releases** the current buffer and takes a reference on the source, which is why a site
#: calling it *replaces* the string rather than adding to it.
UNICODE_STRING_ASSIGN = 0x00436A90
UNICODE_STRING_ASSIGN_BYTES = bytes.fromhex("6aff68f80eb70064a1000000")

#: Two wide literals the description builder already joins lines with: `L"\n"` (the separator the
#: `CONTROLBAR:Requirements` and `TOOLTIP:BuildDisabled` folds use) and `L"\n\n"` (the blank-line
#: separator the two "cannot buy this" messages use). Neither is owned by any one site.
WIDE_NEWLINE = 0x00BDBC40
WIDE_NEWLINE_BYTES = bytes.fromhex("0a000000")
WIDE_BLANK_LINE = 0x00C4F008
WIDE_BLANK_LINE_BYTES = bytes.fromhex("0a000a000000")

#: The same builder's **"you already have this upgrade"** case, where it hands the message over.
#:
#: The case is reached when `Player::hasUpgradeComplete` answers yes for the button's `Upgrade`
#: (`CommandButton+0x24`) and the GUI command is one of the three upgrade kinds. It fetches the
#: button's own `PurchasedLabel` (`CommandButton+0x70`), or `TOOLTIP:AlreadyUpgradedDefault` when
#: that is empty, and **assigns** the result over the description at `ebp-0x18` - which is what
#: throws away the `DescriptLabel` text fetched earlier at `0x00807DCF`.
#:
#: `..._ASSIGN` is the nine-byte `lea ecx, [ebp-0x18]` / `push eax` / `call <operator=>` window,
#: `..._RESUME` the temporary's destructor immediately after it, and `..._RUN` the whole case
#: (the `add esi, 0x70` that names the field, both fetch arms, and the window) for fingerprinting.
#: `eax` holds the fetched `UnicodeString *` at `..._ASSIGN` on both arms.
DESCRIPTION_PURCHASED_RUN = 0x0080833B
DESCRIPTION_PURCHASED_RUN_BYTES = bytes.fromhex(
    "8b760c83c6708bcee81c9bbfff8b0d044bde0084c08b018d55b46a00750b5652ff5038c645fc15eb0d68e4eec4"
    "0052ff503cc645fc168d4de850e816e7c2ff8d4db4c645fc06e82ae4c2ff"
)
DESCRIPTION_PURCHASED_ASSIGN = 0x00808371
DESCRIPTION_PURCHASED_ASSIGN_BYTES = bytes.fromhex("8d4de850e816e7c2ff")
DESCRIPTION_PURCHASED_RESUME = 0x0080837A

#: The sibling case, immediately before it: **"a conflicting upgrade"** / **"a prerequisite
#: upgrade you do not have"**. Same shape, one field along (`ConflictingLabel` and
#: `LacksPrerequisiteLabel` share `CommandButton+0x74`/`+0x78`, reached as `esi + 0x78`), two
#: default keys instead of one, and the same assignment over the description.
#:
#: Note the window's first byte is the `push eax` rather than the `lea` - the two sites emit the
#: argument and the `this` in opposite order - so the two are not interchangeable.
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

#: That `Object`'s controlling `Player`, in the same frame - and **never null**, which is the
#: useful part: `0x00807AD4` seeds the slot from `ThePlayerList` (`0x00DE4928`) and only then
#: overwrites it with `getControllingPlayer` when there *is* an object. So a per-player value is
#: answerable even for a button with nothing selected behind it.
#:
#: Both this and :data:`DESCRIPTION_OBJECT_EBP_OFFSET` are written **once**, in the prologue, and
#: by nothing else in the function - unlike the button's `ThingTemplate` slot at `ebp-0x4c` and
#: (on one path) its `UpgradeTemplate` slot at `ebp-0x24`, both of which later cases reuse as
#: scratch. That is what makes these two safe to read from a hook at the end of the function.
DESCRIPTION_PLAYER_EBP_OFFSET = -0x20

#: The description builder's prologue, at the instruction that loads the `CommandButton`.
#:
#: `esi` is the builder's `this` here and `[esi+0xc]` is the button - but `esi` does **not** hold
#: the `this` at the end of the function: three cases reassign it (`0x00808426`, `0x00808654`,
#: `0x0080867A`), so a hook that runs after the switch cannot recover the button from it. This is
#: where a patch that needs the button later takes a copy, because the path through here is
#: unconditional: everything above it is straight-line from the function's entry, and the null
#: button check (`0x00807AFF`) is the instruction immediately *after* the window.
#:
#: The window is the two instructions `mov [ebp-0x3c], edi` / `mov ecx, [esi+0xc]`; the resume
#: point is the `cmp ecx, edi` that tests what the second one loaded.
DESCRIPTION_BUTTON_CAPTURE = 0x00807AF9
DESCRIPTION_BUTTON_CAPTURE_BYTES = bytes.fromhex("897dc48b4e0c")
DESCRIPTION_BUTTON_CAPTURE_RESUME = 0x00807AFF

#: The same builder's **tail**: the first instruction past the point where every case has finished.
#:
#: The whole switch converges on `0x008086AA`, and between there and the tooltip record's
#: constructor at `0x008086E5` the only thing written is the hint slot at `ebp-0x48`. So the
#: description at `ebp-0x18` is **final** here, which makes this the one site where a line can be
#: appended and be genuinely last - the per-case sites cannot promise that, because the
#: `CONTROLBAR:Requirements` and `TOOLTIP:BuildDisabled` folds run after several of them.
#:
#: `0x008086AA` and `0x008086AB` are both branch targets and this is not, and the four bytes it
#: encodes appear as an imm32 nowhere in the image, so no jump table reaches it either. The window
#: is the single `mov ecx, [0x00DE4A70]` that begins the hint block.
DESCRIPTION_TAIL = 0x008086AE
DESCRIPTION_TAIL_BYTES = bytes.fromhex("8b0d704ade00")
DESCRIPTION_TAIL_RESUME = 0x008086B4

#: `CommandButton::m_specialPower`, and the GUI command value that says a button has one.
COMMAND_BUTTON_SPECIAL_POWER = 0x44
GUI_COMMAND_SPECIAL_POWER = 0x18

#: How the engine builds one `<label>: <number>` line. Twelve sites share the idiom, so it is
#: stable: fetch the localized label through `TheGameText`'s vtable `+0x44` with the caller's three
#: already-pushed arguments, then format it into the buffer the builder keeps at `ebp-0x28`, then
#: drop all three.
#:
#: ⚠ **`UNICODE_STRING_CONCAT` does not concatenate - it replaces.** The name is kept because three
#: patches import it, but `0x00ADF7E0` forwards to `0x00437120`, which `vswprintf`s into a `0x4000`
#: scratch buffer and finishes with `UnicodeString::set` (`0x00436B20`) - so the destination's
#: previous contents are gone. The twelve engine sites conceal this perfectly, because each formats
#: into a slot it is the only writer of. A patch that formats into a slot something else has
#: already written **deletes that text**, and neither `verify` nor a disassembly of the cave can
#: see it. To add a line to an existing string, format into a temporary and join it with
#: :data:`UNICODE_STRING_APPEND`, which is what the builder's own rank case does at `0x008085C4`.
#:
#: The three arguments are pushed *by the caller* as `(label key, 0, value)` and cleaned by the
#: `add esp, 0xc` at the end, which is what makes the block copyable into a cave: it is
#: stack-neutral and needs only `ebp` to still be the builder's frame.
THE_GAME_TEXT = 0x00DE4B04
GAME_TEXT_FORMAT_SLOT = 0x44
UNICODE_STRING_CONCAT = 0x00ADF7E0
DESCRIPTION_BUFFER_EBP_OFFSET = -0x28

#: The ControlBar's command-availability evaluator, at its `UnitCost` test. `ecx` holds the
#: `SpecialPowerTemplate` and `ebx` the `Object`; the `call` named here is the
#: `getFinalOverride` immediately before `cmp [eax+0x80], 0`. `..._UNAVAILABLE` is the tail the
#: existing `unitCost > members` branch jumps to (`xor eax, eax`), at the same stack depth.
#:
#: The ControlBar does **not** call `canUseSpecialPower`, which is why greying a button is a
#: separate edit from gating the activation.
CONTROL_BAR_UNIT_COST_CALL = 0x0094343B
CONTROL_BAR_UNIT_COST_CALL_BYTES = bytes.fromhex("e8fc58d4ff")
CONTROL_BAR_UNAVAILABLE = 0x009438C8

# `MSG_CLEAR_GAME_DATA` - the message that ends a recording. `sage_replay` reads the chunk it
# produces as `Bfme2OrderType.EndOfRecording`.
#
# **It has thirteen emitters, not one.** `GameLogic::clearGameData` (`0x00625E36`) is only the
# one a mid-match quit takes; a game that *finishes* reaches the score screen and ends through
# a different site entirely (the 0x9C5088 / 0x91xxxx window code), and there are eleven more.
# So there is no single place upstream to hook - the funnel is downstream, at the consumer.
CLEAR_GAME_DATA = 0x00625E36
MSG_CLEAR_GAME_DATA = 0x1D

# `MSG_NEW_GAME` - the message that starts one. Its first integer argument is the game mode,
# and it is the only thing that ever starts a recording: `RecorderClass::updateRecord`'s
# `0x1E` branch is `startRecording`'s single caller.
MSG_NEW_GAME = 0x1E

# The `MSG_NEW_GAME` game modes the stock recorder accepts, and the one it does not. The mode
# is the message's argument 0; the emitters that name a constant cover 0..7, and the two the
# recorder keeps are the network ones - every replay in the corpus carries mode 1 in its
# header tail. The skirmish setup screen (`Skirmish.apt`, the start handler at `0x009287D9`
# that also allocates `TheSkirmishGameInfo`) emits **2**, as does the command-line map launch
# at `0x0063CB7B` on the branch that builds a `SkirmishGameInfo` - which is why a skirmish is
# not recorded. Derived in `docs/skirmish-replay.md`.
RECORDER_RECORDED_MODES = (1, 5)
GAME_MODE_SKIRMISH = 2

# `RecorderClass`. `m_mode` is `RECORD` / `PLAYBACK` / `NONE` (0/1/2 - the constructor seeds
# `NONE`, `startRecording` zeroes it and `startPlayback` writes 1), and `m_file` is the `FILE*`
# it both writes recordings to and reads playbacks from - so `m_mode == RECORD` is what tells
# a live recording apart from a replay being watched, and both must hold before anything
# writes to that handle.
#
# `writeToFile` is the engine's own chunk writer, and the format it lays down is what
# `sage_replay.ReplayChunk` parses: `fwrite` of the logic frame, the message type and the
# message's player number, then a unique-argument-type count, one `(type, count)` pair each,
# and the values.
RECORDER_MODE = 0x1C
RECORDER_MODE_RECORD = 0
RECORDER_MODE_PLAYBACK = 1
RECORDER_FILE = 0x10
RECORDER_WRITE_TO_FILE = 0x0077D8FC

# `RecorderClass::m_gameMode` - the `MSG_NEW_GAME` mode a recording was started for, or the one
# read back out of a header during playback (`startPlayback` freads into it at `0x0077F788`).
#
# **Do not read this from inside `startRecording`.** `updateRecord` stores the mode here
# (`0x0077F923`) and immediately passes it on (`0x0077F965`), but `startRecording`'s first act
# is `reset()` (vtable `+0x24`, `0x0077D86C`), which tail-jumps to `0x0077D7C1` and writes the
# sentinel **9** over it at `0x0077D7D2` - 40 bytes before the file is even named. A cave inside
# `startRecording` that asks this field what kind of game it is gets 9, always. Confirmed on a
# live skirmish: the field read 9 while the header the same call wrote carried mode 2.
#
# The mode is still `startRecording`'s own second argument, which is the value it writes into
# the header, so that is what a cave in there should read. See `START_RECORDING_MODE_ARG`.
RECORDER_GAME_MODE = 0xED4
RECORDER_GAME_MODE_RESET = 9
RECORDER_RESET_WRITES_GAME_MODE = 0x0077D7D2

# `RecorderClass::startRecording(Int arg1, Int gameMode, Int arg2, Int arg3)` - thiscall, four
# stack arguments, `ret 0x10`. It runs on a normal `ebp` frame (the SEH prologue at its entry
# establishes one), and writes all four arguments into the header's trailing block at
# `0x0077EFBB`+ - which is where `sage_replay` reads them back as the last four words of
# `unknown_tail`. So `[ebp+0x0C]` inside it *is* the mode the replay will claim it was recorded
# at, by construction rather than by a second lookup that can go stale.
START_RECORDING = 0x0077EA03
START_RECORDING_MODE_ARG = 0x0C

# `RecorderClass::updateRecord`'s `MSG_NEW_GAME` branch - the whole of the engine's decision to
# record, and `startRecording`'s only caller:
#
#     cmp  eax, 0x1E                  ; 0x0077F8D1  message type
#     jne  <not a new game>
#     push ebp / mov ecx, esi
#     call 0x00710C9E                 ; getArgument(0) -> the game mode
#     mov  eax, [eax]
#     cmp  eax, 4    ; je <skip>      ; the shell map
#     cmp  eax, 7    ; je <skip>
#     cmp  [TheGameLogic+0x114], 3    ; je <skip>
#     xor  ebx, ebx / inc ebx         ; ebx = 1, the default arg1
#     cmp  eax, ebx  ; je <record>    ; mode 1
#     cmp  eax, 5                     ; 0x0077F910  <- the whitelist tail, 9 bytes
#     jne  <skip>                     ; 0x0077F9DD
#     <record>                        ; 0x0077F919
#
# The nine bytes at `..._MODE_GATE` are the only thing between a skirmish and a recording: the
# 4/7 rejects above are redundant against the whitelist, and `TheGameLogic+0x114` is 3 for any
# game started from the shell (`0x00779F20` sets it there and nothing else writes it outside a
# savegame load). `..._BRANCH_BYTES` is the 63-byte run from the message-type compare down to
# the gate: a bare `cmp eax, 5` says nothing about which comparison it is, and that context
# does.
RECORDER_NEW_GAME_BRANCH = 0x0077F8D1
RECORDER_NEW_GAME_BRANCH_BYTES = bytes.fromhex(
    "83f81e0f859d000000558bcee8bc13f9ff8b0083f8040f84f000000083f807"
    "0f84e70000008b0d2c41de0083b914010000030f85d400000033db433bc37409"
)
RECORDER_MODE_GATE = 0x0077F910
RECORDER_MODE_GATE_BYTES = bytes.fromhex("83f8050f85c4000000")  # cmp eax,5 / jne 0x0077F9DD
RECORDER_MODE_GATE_ACCEPT = 0x0077F919  # fall through: start the recording
RECORDER_MODE_GATE_REJECT = 0x0077F9DD  # the function epilogue: record nothing

# `RecorderClass::startRecording`'s call to the helper that names the file. The helper is
# `TheGameText->fetch("GUI:LastReplay")` with a `00000000` fallback, so every recording is
# written to `<UserDataDir>\Replays\Last Replay.BfME2Replay` and overwrites the previous one.
#
# It has a second caller (`0x00817E49`, the replay menu reconstructing that exact name to find
# the entry), so the *call site* is the patchable thing, not the helper. It is cdecl with one
# argument - the uninitialised `UnicodeString` storage to construct into - and returns it in
# `eax`; `..._CALL_BYTES` sits at offset 4 of the surrounding fingerprint.
RECORDER_LAST_REPLAY_NAME = 0x0077DEFD
RECORDER_NAME_CALL = 0x0077EA45
RECORDER_NAME_CALL_BYTES = bytes.fromhex("e8b3f4ffff")  # call 0x0077DEFD
RECORDER_NAME_CALL_FINGERPRINT = bytes.fromhex("8d45ec50e8b3f4ffff5933db8d7e144350")

# `UnicodeString::UnicodeString(const WideChar *)` - thiscall, one stack argument which it
# cleans (`ret 4`), returning `this` in `eax`. It zeroes the object before assigning, so it is
# correct on the uninitialised storage a return-value-optimised caller hands out. This is the
# one `getReplayExtension` (`0x0077DEE3`) uses to build its literal.
UNICODE_STRING_FROM_WIDE = 0x00437770

# `RecorderClass::updateRecord`'s `MSG_CLEAR_GAME_DATA` branch - the one place every ending
# converges on, whichever of the thirteen emitters appended the message. It reads:
#
#     cmp  eax, 0x1D                  ; 0x0077F977
#     jne  <ordinary order>
#     cmp  [edi+0x10], ebp            ; m_file != NULL
#     je   <nothing to write>
#     or   dword [0xDA570C], -1
#     push esi                        ; the GameMessage *
#     mov  ecx, edi
#     call 0x0077D8FC                 ; 0x0077F98B  writeToFile(msg)  <- the hook site
#     mov  ecx, edi
#     call 0x0077D8C8                 ; stopRecording() - closes the file
#
# Hooking the `writeToFile` call is what puts a cave *between* the last order and the end
# marker, with `m_file` already proven non-NULL by the branch above and the file still open.
# It is the last moment anything can be appended to a recording.
#
# `..._END_BRANCH_BYTES` is the 20-byte fingerprint from the `cmp eax, 0x1D` through the
# `mov ecx, edi` that sets up the call: it pins the message id, the file test and the register
# the recorder is in, so a build whose layout moved fails instead of hooking a bare call.
RECORDER_END_BRANCH = 0x0077F977
RECORDER_END_BRANCH_BYTES = bytes.fromhex("83f81d7525396f107416830d0c57da00ff568bcf")
RECORDER_END_WRITE_CALL = 0x0077F98B
RECORDER_END_WRITE_CALL_BYTES = bytes.fromhex("e86cdfffff")  # call 0x0077D8FC
RECORDER_STOP_RECORDING = 0x0077D8C8

# The branch's *second* call - `stopRecording`, two instructions past the `writeToFile` one.
# A cave here runs after the `0x1D` end marker has been written and before the file is closed,
# which is the second and last such moment; `replay-annotations` takes it precisely because
# `replay-outcome` owns the first (composing rule 2 - two patches must not edit one site).
#
# `..._SETUP_BYTES` is the `mov ecx, edi` that loads the recorder for the call. Together with
# `RECORDER_END_BRANCH_BYTES` (which stops one byte short of the `writeToFile` call, so it stays
# valid whether or not `replay-outcome` has rewritten those five bytes) it pins the site without
# reading a byte any other patch may have changed.
RECORDER_END_STOP_CALL = 0x0077F992
RECORDER_END_STOP_CALL_BYTES = bytes.fromhex("e831dfffff")  # call 0x0077D8C8
RECORDER_END_STOP_SETUP = 0x0077F990
RECORDER_END_STOP_SETUP_BYTES = bytes.fromhex("8bcf")  # mov ecx, edi

# Two siblings that answer "is this a game the observer machinery applies to". Both are
# thiscall on `TheGameLogic` and return a bool in `al`; they differ only in whether skirmish
# counts. Derived in `docs/observer-switch.md`.
#
#     IS_MULTIPLAYER_GAME              `m_gameMode` in {1, 5} - the two network flavours.
#     IS_MULTIPLAYER_OR_ITS_REPLAY     that, or a *playback* whose recorded mode is 1 or 5.
#     IS_MULTIPLAYER_OR_SKIRMISH...    that, plus live mode 2 and a recorded mode of 2.
#
# The last one is the predicate `docs/skirmish-replay.md` §3 cites as proof the engine already
# anticipates a mode-2 recording; it has 31 callers. The middle one has **exactly one**, the
# observer bar's visibility gate below.
IS_MULTIPLAYER_GAME = 0x00441B7C
IS_MULTIPLAYER_OR_ITS_REPLAY = 0x0062541E
IS_MULTIPLAYER_OR_ITS_REPLAY_BYTES = bytes.fromhex(
    "e859c7e1ff84c075298b0dd87cde0085c97422e8efba180083f8017518a1d8"
    "7cde008b80d40e000083f801740583f8057503b001c332c0c3"
)
IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY = 0x00625456
IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY_BYTES = bytes.fromhex(
    "568bf1e81ec7e1ff84c0753783be1001000002742e8b0dd87cde0085c97428"
    "e8abba180083f801751ea1d87cde008b80d40e000083f802740a83f8017405"
    "83f8057504b0015ec332c05ec3"
)

# The palantir's per-frame decision to show or hide the observer bar - the APT clip holding
# `ObserverStuff/NextPlayerBttn` and `PriorPlayerBttn`, the only UI that reaches
# `PlayerList::observeNextPlayer`:
#
#     mov  ecx, [TheGameLogic]         ; 0x006D7809
#     test ecx, ecx ; je <hide>
#     call 0x0062541E                  ; 0x006D7813  multiplayer, or a replay of one?
#     test al, al   ; je <hide>
#     mov  ecx, [ThePlayerList]
#     call 0x006A87F5                  ; is the local player an observer (or defeated)?
#     test al, al   ; je <hide>
#     mov  bl, 1 / jmp / xor bl, bl    ; the answer
#     <compare against the cached bit at Palantir+0x7E>
#     call 0x008003F6                  ; SetObserverStuffState("_show")
#     jmp
#     call 0x0080041A                  ; SetObserverStuffState("_hide")
#
# `..._FINGERPRINT` is that whole 66-byte run, with `..._BYTES` at offset 10 of it. A bare
# `call` says nothing about which one it is; the two predicates around it and the two APT
# thunks below it do.
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

# `PlayerList::localPlayerIsNotActive` (`mov ecx, [this+0x10]` - the local player - then
# `!Player::isPlayerActive`, which is `!m_isObserver && !m_isDefeated`). The second half of the
# gate above, and the *only* other test `PlayerList::observeNextPlayer` makes beyond
# `GameLogic::isInGame` (`0x00441B60`: mode not in {4, 7, 9}). Neither cares about skirmish.
PLAYER_LIST_LOCAL_IS_NOT_ACTIVE = 0x006A87F5
PLAYER_LIST_OBSERVE_NEXT_PLAYER = 0x006A8D2B
GAME_LOGIC_IS_IN_GAME = 0x00441B60

# Where playback makes the observer the local player: `cmp [TheGameLogic+0x110], 3` - the
# playback game mode - then `setLocalPlayer(findPlayerWithNameKey("ReplayObserver"))` and
# `ControlBar+0x218 = getNthPlayer(TheRecorder+0xECC)`, the recorded local player. Mode 3 is
# mode 3 whatever was recorded, which is why a skirmish replay already gets a working observer
# seat and only the bar above is missing.
PLAYBACK_INSTALLS_OBSERVER = 0x006283D1
RECORDER_LOCAL_PLAYER_INDEX = 0xECC

# `msvcr71.dll` imports, by IAT slot. The engine calls them exactly this way
# (`call dword ptr [slot]`, cdecl, caller cleans), so a cave can too.
IMPORT_FWRITE = 0x00BD053C
IMPORT_FFLUSH = 0x00BD065C
IMPORT_SWPRINTF = 0x00BD0490

# `kernel32!GetLocalTime(LPSYSTEMTIME)` - stdcall, so it cleans its own argument.
# `startRecording` already calls it (`0x0077EBB1`) for the header's timestamp.
IMPORT_GET_LOCAL_TIME = 0x00BD01D4

# `VictoryConditions` - the subsystem that decides who is out and who has won. Derived in
# `docs/replay-outcome.md`; `sizeof` is 0x94 and the vtable is the one its constructor
# installs.
#
# `m_players` is a compacted list: `addPlayer` walks `ThePlayerList` at game start and keeps
# only the real playable sides, so an index here is *not* a `ThePlayerList` index. A player is
# named by its own `PLAYER_INDEX` instead, which is what the engine stamps into every replay
# chunk, so a chunk written from here is attributable exactly as a real order is.
#
# `m_isDefeated[i]` is a latch: `VictoryConditions::update` sets it once, on the frame the
# player is first found defeated, and never clears it. The two vtable predicates are the
# engine's own answers, teams included, and both are already called every frame by the stock
# UI - so calling them again costs nothing new.
VICTORY_CONDITIONS_VTABLE = 0x00C4F108
VICTORY_CONDITIONS_PLAYERS = 0x18  # Player *m_players[MAX_PLAYER_COUNT]
VICTORY_CONDITIONS_IS_DEFEATED = 0x70  # Bool m_isDefeated[MAX_PLAYER_COUNT]
VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY_SLOT = 0x38
VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY = 0x00808AA8
VICTORY_CONDITIONS_HAS_BEEN_DEFEATED_SLOT = 0x40
VICTORY_CONDITIONS_HAS_BEEN_DEFEATED = 0x0080953C

# `Player`. `m_playerIndex` is the number the engine writes into every replay chunk: the
# `GameMessage` constructor at 0x710C36 fills the message's player field from
# `ThePlayerList->getLocalPlayer()->m_playerIndex`, and `RecorderClass::writeToFile` copies
# that field straight out. `m_defeatedFrame` is stamped by `VictoryConditions::update` on the
# transition, `m_isDefeated` is the player's own hard flag (a quit, or nothing left that
# `MP_COUNT_FOR_VICTORY` counts), and `m_isObserver` marks a slot that plays no side.
PLAYER_INDEX = 0x54
PLAYER_IS_OBSERVER = 0x35A
PLAYER_DEFEAT_FRAME = 0x4CC
PLAYER_IS_DEFEATED = 0x754

# `ScoreKeeper`, embedded in `Player` (not a pointer) - the score-screen counters, which no
# replay has ever carried. Derived in `docs/replay-annotations.md` §2.
#
# The base is pinned twice over: 107 `lea reg, [reg+0x3DC]` sites hand that address to the
# method block at 0x0079DB00-0x0079DD00, and `PLAYER_SCORE_KEEPER + SCORE_KEEPER_END_FRAME`
# is exactly `PLAYER_DEFEAT_FRAME` - the field `replay-outcome` already reads and has
# runtime-verified, so the two readings check each other.
PLAYER_SCORE_KEEPER = 0x3DC

# The counters. `..._DESTROYED` are `Int[20]` arrays indexed by the *victim's*
# `m_playerIndex`: `ScoreKeeper::addObjectDestroyed` resolves the destroyed object's owner and
# indexes by `Player+0x54`, which is what makes the pair a per-opponent kill matrix rather
# than a total. The five marked (*) are pinned by their own increment sites (below); the rest
# hold by position in the stats-file writer's column order, which those five align.
SCORE_KEEPER_MONEY_EARNED = 0x04
SCORE_KEEPER_MONEY_SPENT = 0x08
SCORE_KEEPER_UNITS_DESTROYED = 0x20  # (*) Int[20]
SCORE_KEEPER_UNITS_BUILT = 0x70
SCORE_KEEPER_UNITS_LOST = 0x74  # (*)
SCORE_KEEPER_STRUCTURES_DESTROYED = 0x78  # (*) Int[20]
SCORE_KEEPER_STRUCTURES_BUILT = 0xC8
SCORE_KEEPER_STRUCTURES_LOST = 0xCC  # (*)
SCORE_KEEPER_END_FRAME = 0xF0
SCORE_KEEPER_UNITS_ALIVE = 0x108
SCORE_KEEPER_STRUCTURES_ALIVE = 0x10C

#: `SCORE_KEEPER_UNITS_DESTROYED` through `SCORE_KEEPER_STRUCTURES_LOST` are contiguous -
#: `units_destroyed[20]`, `units_built`, `units_lost`, `structures_destroyed[20]`,
#: `structures_built`, `structures_lost` - so all six counters copy in one `rep movsd`.
SCORE_KEEPER_COUNTER_BLOCK = SCORE_KEEPER_UNITS_DESTROYED
SCORE_KEEPER_COUNTER_BLOCK_DWORDS = (
    SCORE_KEEPER_STRUCTURES_LOST + 4 - SCORE_KEEPER_UNITS_DESTROYED
) // 4

# The increment sites that pin four of the offsets, used as the patch's layout fingerprint.
# `addObjectDestroyed` (0x0079F303) bumps the two per-victim arrays through `esi` = the victim's
# `m_playerIndex`; `addObjectLost` (0x0079F486) bumps the two loss counters on `ebx` = `this`.
# A build that moved a counter fails here instead of writing a chunk of the wrong numbers.
SCORE_KEEPER_ADD_OBJECT_DESTROYED = 0x0079F303
SCORE_KEEPER_ADD_OBJECT_LOST = 0x0079F486
SCORE_KEEPER_LAYOUT_SITES = (
    (0x0079F36A, bytes.fromhex("ff44b778")),  # inc [edi+esi*4+0x78]  structures destroyed
    (0x0079F3B2, bytes.fromhex("ff44b720")),  # inc [edi+esi*4+0x20]  units destroyed
    (0x0079F4E2, bytes.fromhex("ff83cc000000")),  # inc [ebx+0xcc]    structures lost
    (0x0079F52C, bytes.fromhex("ff4374")),  # inc [ebx+0x74]          units lost
)

#: `ScoreKeeper::addObjectDestroyed`'s victim lookup, as the `lea ecx, [edi+0x3DC]` that hands
#: a `Player`'s embedded keeper to a method - the fingerprint for `PLAYER_SCORE_KEEPER` itself.
SCORE_KEEPER_PLAYER_REF = 0x006ABFE3
SCORE_KEEPER_PLAYER_REF_BYTES = bytes.fromhex("8d8fdc030000")  # lea ecx, [edi+0x3dc]

# `MessageStream::appendMessage(GameMessage::Type)` is virtual, at this vtable offset, and
# returns the new `GameMessage *`.
APPEND_MESSAGE_VTABLE_SLOT = 0x48

# `TheTacticalView` - the camera. **Not a subsystem singleton**, which is why it is absent from
# `docs/engine-globals.md`'s registration walk: `TheGameClient` creates it at `0x0069EF61`
# (`createView`, its own vtable slot `+0x1D8`), stores the result here, and calls `init` on it.
# 423 xrefs across the client, and none at all from logic - the camera is presentation state
# that the simulation never reads, which is what makes writing it desync-safe.
THE_TACTICAL_VIEW = 0x00DE447C

# `View::getLocation(ViewLocation *)` and `View::setLocation(const ViewLocation *)`, the pair
# the camera-bookmark hotkeys use. Both are `__thiscall` taking one pointer, and the callee
# cleans the argument (`ret 4`) - the engine's own call sites push and never adjust `esp`.
#
# The pair, and the struct's size, come from the bookmark handler reading its slot array with a
# 32-byte stride: `0x0083B294` saves the live camera into slot *n* through `+0x170`, and
# `0x0083B420` restores slot *n* through `+0x174`, both addressing `[base + n*32]`.
VIEW_GET_LOCATION_VTABLE_SLOT = 0x170
VIEW_SET_LOCATION_VTABLE_SLOT = 0x174

# `ViewLocation`: a validity flag, a `Coord3D`, then four angles/distances. Its shape is fixed
# by the `MSG_SET_REPLAY_CAMERA` emitter at `0x0083BA86`, which builds one on the stack and
# ships it as a Position argument followed by exactly four Floats.
VIEW_LOCATION_SIZE = 0x20

# `View::m_pos` - the camera's look-at point on the terrain, and the one field of a placement
# that can be written on its own. `setLocation` copies a `ViewLocation`'s three position floats
# here with `lea edi,[ebx+0x0C]` and three MOVSDs (`0x0065E995`), and `getLocation` reads them
# back from `[esi+0x0C]` (`0x0065E942`).
#
# **Writing these twelve bytes moves the camera by itself**, without the recompute `setLocation`
# calls afterwards - measured live against a running match, at 160 writes a second. That matters
# because `setLocation` is otherwise the only way in and it always writes all four scalars, one
# of which it cannot write correctly: `zoom` is read from `+0x124` and written to `+0x128`, so
# handing a captured location straight back still moved the live zoom from 1.281116 to 1.234136,
# after which the client restored it over about 0.6 seconds. Asking for the reported zoom is
# refused identically, so there is no value that makes `setLocation` a no-op.
VIEW_POSITION_OFFSET = 0x0C

# `BuildAssistant::canMakeUnit(Object *producer, const ThingTemplate *what, int reviveIndex)` -
# the one gate the AI consults before deciding a producer may make something. It is virtual, at
# the vtable slot below, and `BUILD_ASSISTANT_VTABLE` is the class's vtable (from the constructor
# `TheBuildAssistant` is registered with), so a patch can assert the slot still names it.
#
# It walks the producer's `CommandSet` and branches on whether a revive index was passed. The
# labels below are the four points inside it that `patches/ai_revive_gate.py` needs; they are
# derived in `docs/ai-revive-gate.md`.
CAN_MAKE_UNIT = 0x00794F38
BUILD_ASSISTANT_VTABLE = 0x00C307D8
CAN_MAKE_UNIT_VTABLE_SLOT = 0x68

# The `NEED_UPGRADE` / `NeededUpgrade` / `NeededUpgradeAny` check. Only the template branch
# reaches it; it falls through to the accept path and jumps to `..._NEXT_SLOT` on failure.
CAN_MAKE_UNIT_UPGRADE_GATE = 0x0079502A
# Where the upgrade gate falls through to on success, and where the stock revive branch jumps
# when a slot matches: resolve the player and answer the question.
CAN_MAKE_UNIT_ACCEPT = 0x007950AD

# `BuildAssistant`'s **other** gate, vtable slot `+0x64`. It is the one every producer-facing
# consumer asks - the ControlBar's button availability, `ProductionUpdate::queueCreateUnit`,
# the script and AI production paths, 14 call sites in all - and it reaches `canMakeUnit`
# through a *virtual self-call* on its own `this`, which is why a scan for a
# `TheBuildAssistant` global load followed by `call [reg+0x68]` cannot see it.
#
# So it is the edge that puts `canMakeUnit` on the player's path, and the return address it
# leaves on the stack is how `patches/ai_revive_gate.py` tells the AI's own queries apart from
# everyone else's. Anchoring the call rather than naming the return address means a build whose
# layout moved fails loudly instead of comparing against a stale constant.
CAN_MAKE_UNIT_PRODUCTION_GATE = 0x00793ECB
CAN_MAKE_UNIT_PRODUCTION_GATE_SLOT = 0x64
CAN_MAKE_UNIT_PRODUCTION_GATE_CALL = 0x00793F56
CAN_MAKE_UNIT_PRODUCTION_GATE_CALL_BYTES = bytes.fromhex("ff5068")  # call dword [eax+0x68]
# The revive branch: `cmp [esi+0x14], GUICOMMAND_REVIVE` then `jne ..._NEXT_SLOT`. Six bytes,
# one inbound edge (the `jne` at 0x00794FF5), which is what makes it hookable.
CAN_MAKE_UNIT_REVIVE_BRANCH = 0x007950CE
CAN_MAKE_UNIT_REVIVE_BRANCH_ENTRY = bytes.fromhex("837e142e750b")
# `inc dword [ebp-0xc]` - count this REVIVE slot, then fall into the next-slot step.
CAN_MAKE_UNIT_BUMP_SLOT = 0x007950DC
# `inc dword [ebp-8]` - advance to the next `CommandSet` slot without counting a REVIVE.
CAN_MAKE_UNIT_NEXT_SLOT = 0x007950DF
# `cmp dword [ebp-8], 0x21` - how many `CommandSet` slots the walk visits. Stock 33, raised to N
# by `CommandSetLimitPatch` so the AI can see the slots the button-limit patch makes definable.
CAN_MAKE_UNIT_SCAN_BOUND = 0x007950E2

# `GUICommandType::GUICOMMAND_REVIVE`, entry 46 of the name table at 0x00DA4D10.
GUICOMMAND_REVIVE = 46

#
# The `SkirmishAI` producer picker, and the construction check that is missing from it.
# Derived in `docs/ai-construction-gate.md`.
#
# RotWK ships **two** AIs. The Generals/BFME1-lineage `AIPlayer::findFactory` at 0x008F5347 does
# test `UNDER_CONSTRUCTION` (at 0x008F53A2) before it asks `canMakeUnit` - but a skirmish match
# runs the BFME2-era `SkirmishAI` subsystem, whose own producer index and picker live in the
# 0x0096xxxx-0x009Exxxx region and consult no status at all. The picker below is where the AI
# chooses which of its buildings will make a thing, for units and for hero revives alike.

# `SkirmishAI`'s "which of my producers should make this" - `__thiscall`, three stack arguments,
# `ret 0xc`, returning the chosen `Object*` (or null). Six direct callers, **all** of them AI,
# which is what makes a gate here AI-only without the return-address discrimination
# `ai-revive-gate` needs. Not virtual, so it is anchored by its own prologue and by one of its
# call sites rather than by a vtable slot.
AI_PRODUCER_PICKER = 0x009A0705
AI_PRODUCER_PICKER_ENTRY = bytes.fromhex("558bec51515356")
# `AIPlayer`'s order pump, the caller that stamps the picked producer's id into a pending build
# order (`mov [edi+8], eax` at 0x008F0FE4). Anchoring the call proves the picker being patched is
# the one the AI's production actually reaches, the way `ai-revive-gate` anchors a vtable slot.
AI_PRODUCER_PICKER_CALL = 0x008F0FD4
AI_PRODUCER_PICKER_CALL_BYTES = bytes.fromhex("e82cf70a00")  # call 0x009A0705

# `cmp byte [ebp+0x10], 0` then `jne ..._ACCEPT`. The picker's third argument splits it in two:
# zero means "pick one to use **now**" and runs the usable-producer tests below; non-zero means
# "could anything ever make this" and skips straight to accept. Six bytes, and a scan of every
# branch displacement and imm32 in `.text` finds **no** inbound edge into them - the only way in
# is fallthrough from the `je` at 0x009A0782 - which is what makes them hookable.
AI_PRODUCER_ANY_BRANCH = 0x009A0784
AI_PRODUCER_ANY_BRANCH_ENTRY = bytes.fromhex("807d10007516")
# `mov eax, [esi]` - the head of the usable-producer tests: `ProductionUpdate` vtable `+0x64`
# (is it disabled) then `+0x44` (is its queue empty). `esi` is the producer's `ProductionUpdate`,
# `edi` the candidate `Object`. This is the run of tests `UNDER_CONSTRUCTION` belongs in.
AI_PRODUCER_USABLE_TESTS = 0x009A078A
# `xor dl, dl` - the accept path, shared by both arms.
AI_PRODUCER_ACCEPT = 0x009A07A0
# `push dword [ebp+8]` - release this candidate and go round for the next one. Every one of the
# picker's rejection edges lands here.
AI_PRODUCER_NEXT_CANDIDATE = 0x009A07C7

# `ObjectStatus::UNDER_CONSTRUCTION`, bit 2 of the mask at `OBJECT_STATUS`, tested through
# `OBJECT_TEST_STATUS`. Index 2 of the name table at `OBJECT_STATUS_NAMES`, and confirmed on
# live-captured bytes: the half-built `ElvenMallornTree_Extern` in
# `tests/sage_live/fixtures/match.snapshot.gz` reads `[obj+0x94] == 4`.
OBJECT_STATUS_UNDER_CONSTRUCTION = 2

# `ProductionUpdateInterface::requestUniqueUnitID()` - the mint for the `ProductionID` that
# names one queued production. `ProductionUpdate` is its only implementer: the address below
# appears in exactly one vtable slot in the image, the one named here.
#
# The interface is a secondary base of the `ProductionUpdate` module, at module `+0x20`, so
# `this` is the interface subobject and the counter it advances is module `+0x30`. The
# constructor (`0x008A17D8`) seeds that counter to 1 and nothing but this function reads or
# writes it - which is what makes it replaceable. Derived in `docs/unique-production-id.md`.
REQUEST_UNIQUE_UNIT_ID = 0x008A18FA
PRODUCTION_UPDATE_INTERFACE_VTABLE = 0x00C67DB0
REQUEST_UNIQUE_UNIT_ID_VTABLE_SLOT = 0x08

# The module's *primary* vtable, written at `module+0x00` by the constructor
# (`0x008A1819`: `mov dword [esi], 0xc67ef4`). A vtable address is unique to its class, so
# this is how a reader outside the process identifies which of an object's behaviour modules
# is the `ProductionUpdate` - without calling the engine's own `getProductionUpdateInterface`,
# which it cannot. Used by `sage_live.backends.memory` to read production state; see
# `docs/production-model-condition.md` §5.
PRODUCTION_UPDATE_VTABLE = 0x00C67EF4

# `Object+0x24C` is a pointer to a **NULL-terminated** array of `BehaviorModule*`. Read off
# `getProductionUpdateInterface` (`0x0068C327`), which is `mov esi,[ecx+0x24c]` and then walks
# `esi` in steps of 4 until it loads NULL. Three interface getters in a row share the idiom,
# so the offset is corroborated three times over rather than inferred from one.
OBJECT_MODULE_LIST = 0x24C
# The whole stock body: `mov eax,[ecx+0x10]` / `lea edx,[eax+1]` / `mov [ecx+0x10],edx` / `ret`.
# Ten bytes, entered only through the vtable, so all ten are replaceable in place.
REQUEST_UNIQUE_UNIT_ID_BODY = bytes.fromhex("8b41108d5001895110c3")


# A module's INI fields are a 16-byte-stride array of `{const char *name, parseFn, userData,
# offset}`, walked to a NULL name pointer - never to a count, which is why adding a field needs
# no bound raised anywhere. `INI::parseBool` is the parser every `Bool` field names; its tail is
# `mov ecx,[esp+0xc]` / `mov byte [ecx], al`, a single byte store through the pointer the reader
# forms as `store + offset`, which is what lets a `Bool` live in a struct's padding byte.
FIELD_PARSE_STRIDE = 16
INI_PARSE_BOOL = 0x0042E558

# `INI::parseReal`, the parser every `Real` field names: it scans one token, converts it and
# does `fstp dword [store]`, a single 4-byte float store through the same `store + offset`
# pointer - so a new `Real` field needs an aligned 4-byte slot and nothing else.
INI_PARSE_REAL = 0x0042ED00


# The module on a claimed resource spot: it wakes every `IncomeInterval`, deposits an income, and
# hands the same number to the building's `ExperienceTracker`. Derived in
# `docs/terrain-resource-exp.md`.
#
# `ModuleData` is 0x24 bytes holding eight fields. Two `Bool`s sit at +0x14/+0x15 and the next
# field is a 4-byte `KindOfFilter` that has to start aligned at +0x18, so **+0x16 and +0x17 are
# padding**: nothing reads them and the constructor never writes them.
TERRAIN_RESOURCE_MODULE_DATA_CTOR = 0x0088525D
TERRAIN_RESOURCE_MODULE_DATA_SIZE = 0x24
TERRAIN_RESOURCE_FREE_OFFSET = 0x16

# The constructor's two `Bool` defaults: `mov byte [esi+0x14], 0` (HighPriority = No) then
# `mov byte [esi+0x15], 1` (Visible = Yes). `operator new(0x24)` does not zero the block, so a
# field the constructor skips holds heap garbage - which is why a new field at +0x16 needs these
# eight bytes rewritten rather than nothing at all.
TERRAIN_RESOURCE_DEFAULT_STORES = 0x0088528B
TERRAIN_RESOURCE_DEFAULT_STORES_BYTES = bytes.fromhex("c6461400c6461501")

# `buildFieldParse` and the `push` that hands the reader the field table - the table's **only**
# reference in the image, which is what makes relocating it a single 4-byte repoint.
TERRAIN_RESOURCE_BUILD_FIELD_PARSE = 0x008852B8
TERRAIN_RESOURCE_FIELD_TABLE_PUSH = 0x008852BE
TERRAIN_RESOURCE_FIELD_TABLE_PUSH_BYTES = bytes.fromhex("6878fdc500")  # push 0x00c5fd78
TERRAIN_RESOURCE_FIELD_TABLE = 0x00C5FD78

# The whole stock table: eight rows and the NULL terminator. The keyword strings its rows point
# at sit immediately *before* it and the terminator immediately after, so it cannot grow in
# place. Rows in table order: Radius +0x08, MaxIncome +0x0C, IncomeInterval +0x10,
# HighPriority +0x14, Visible +0x15, Upgrade +0x1C, UpgradeBonusPercent +0x20,
# UpgradeMustBePresent +0x18.
TERRAIN_RESOURCE_FIELD_TABLE_STOCK = bytes.fromhex(
    "1036be0000ed420000000000080000006cfdc5005eec4200000000000c000000"
    "5cfdc50029a4730000000000100000004cfdc50058e542000000000014000000"
    "44fdc50058e542000000000015000000ac8cbf0089af7300000000001c000000"
    "8c7fc000faee42000000000020000000747fc0002f397600000000001800000000000000"
    "000000000000000000000000"
)

# `TerrainResourceBehavior::update`, slot 0 of the `UpdateModule` vtable the module stores at
# +0x10. It caches its `ModuleData` in `[ebp-0x18]` at 0x008854EF and reads that slot again at
# 0x0088576A, so the cave reads exactly what the function reads.
TERRAIN_RESOURCE_UPDATE = 0x008854D3
TERRAIN_RESOURCE_UPDATE_VTABLE = 0x00C5FBCC
TERRAIN_RESOURCE_UPDATE_VTABLE_SLOT = 0x00
TERRAIN_RESOURCE_MODULE_DATA_EBP_SLOT = -0x18

# The experience block at the tail of `update`: load the `ExperienceTracker` from `Object+0x26C`,
# test it, ask `isTrainable`, then hand `addExperiencePoints` the integer just deposited. The
# load is 6 bytes and is itself a jump target (the `jle` at 0x0088567A lands on it when the
# income comes out <= 0), so hooking *at* it gates both paths with one edit. Both stock
# rejections already land on 0x0088576A, which is the edge a gated tick takes.
TERRAIN_RESOURCE_EXP_BLOCK = 0x0088573C
TERRAIN_RESOURCE_EXP_BLOCK_BYTES = bytes.fromhex("8bbf6c020000")  # mov edi, [edi+0x26c]
TERRAIN_RESOURCE_EXP_BLOCK_RESUME = 0x00885742
TERRAIN_RESOURCE_EXP_BLOCK_SKIP = 0x0088576A

# The three sites a **negative** `MaxIncome` has to get past, in the order `update` reaches them.
# Derived in `docs/maintenance-cost.md`; nothing here is a new field, because `INI::parseInt`
# already accepts a minus sign - `INI::scanInt` is an `sscanf("%d")` - so a negative parses today
# and is thrown away at run time instead.
#
# `..._INCOME_GATE` is `jle 0x0088573C`, taken when the income *before* inflation comes out <= 0.
# It is the whole of why a negative does nothing today, and the one edit that needs no cave: the
# condition wants to be "== 0" rather than "<= 0", which is `0F 8E` -> `0F 84` in place, the same
# six bytes and the same target.
TERRAIN_RESOURCE_INCOME_GATE = 0x0088567A
TERRAIN_RESOURCE_INCOME_GATE_BYTES = bytes.fromhex("0f8ebc000000")  # jle 0x0088573c

# `..._FLOOR` is the engine's "never round an income below 1 gold" rule, applied *after* the
# inflation multiply: `test ebx, ebx / jg +3 / xor ebx, ebx / inc ebx`. Reachable in the stock
# build only at exactly zero - the gate above has already established the value was positive and
# the multiplier is never negative - so raising a zero is all it ever does there. A negative
# arriving here would be turned into a **payment of one gold**, which is why it is a site.
TERRAIN_RESOURCE_FLOOR = 0x0088569F
TERRAIN_RESOURCE_FLOOR_BYTES = bytes.fromhex("85db7f0333db43")
TERRAIN_RESOURCE_FLOOR_RESUME = 0x008856A6

# The slot the income lives in as a **float** between the inflation multiply and the floor:
# `fstp dword [ebp-0x20]` at 0x00885692 writes it, and the `fld`/`fistp` two instructions later
# turn it into the `ebx` the floor tests. It is the same `ebp-0x20` that held
# `&ResourceModifierObjectFilter` earlier in the function, reused - see `AUTO_DEPOSIT_FILTER_EBP`.
#
# Worth a name because the float **keeps a sign the integer loses**: an inflation multiplier of
# zero turns a charge into an integer 0, but IEEE gives `-5.0f * 0.0f` the value `-0.0f`, whose
# sign bit a `test` on the raw dword reads directly.
TERRAIN_RESOURCE_INCOME_FLOAT_EBP = -0x20

# `..._PAY` is the `lea ecx, [esi+0x90]` that addresses the player's `Money` for the deposit -
# the instruction *before* the `call`, deliberately, so the call itself stays free for whatever
# else wants it. `esi` is the controlling `Player`, `edi` the depositing `Object` and `ebx` the
# signed amount; the three deposit arguments are already pushed, with the amount at `[esp]`.
TERRAIN_RESOURCE_PAY = 0x008856B0
TERRAIN_RESOURCE_PAY_BYTES = bytes.fromhex("8d8e90000000")  # lea ecx, [esi+0x90]
TERRAIN_RESOURCE_PAY_RESUME = 0x008856B6

# `GameMessage::append*Argument`, indexed by `sage_replay.OrderArgumentType`. All are thiscall
# (ecx = the GameMessage) taking one stack argument, and clean it themselves (`ret 4`).
# Position, ScreenPosition, ScreenRectangle and WideChar take the *address* of their data;
# the rest take the value.
ARG_APPENDERS = (
    0x007111E5,  # 0  Integer
    0x007110EA,  # 1  Float
    0x00711104,  # 2  Boolean
    0x0071111A,  # 3  ObjectId
    0x00711130,  # 4  DrawableId
    0x00711146,  # 5  TeamId
    0x0071115C,  # 6  Position         (by pointer, 3 floats)
    0x00711179,  # 7  ScreenPosition   (by pointer, 2 dwords)
    0x00711197,  # 8  ScreenRectangle  (by pointer, 4 dwords)
    0x007111B5,  # 9  Timestamp
    0x007111CB,  # 10 WideChar         (by pointer, one 16-bit unit)
)


# Derived in `docs/command-point-upkeep.md`. The whole per-building "inflation" mechanic lives
# in one function, and these are the pieces of it a second modifier has to reach.

#: The `PlayerTemplate` INI field-parse table, and the **single** reference that names it - the
#: smallest repoint in this tree (`hero-mana` moves a two- and a five-reference table). The
#: reference is a `push imm32` inside `PlayerTemplate::parse` (`0x005FDF75`), which builds a
#: two-table `MultiIniFieldParse` on the stack; this is the first table, added with extra
#: offset 0, so an appended entry's `offset` is used as-is.
PLAYER_TEMPLATE_FIELD_TABLE = 0x00BF81A8
PLAYER_TEMPLATE_FIELD_TABLE_REFS = (0x005FDF8E,)
PLAYER_TEMPLATE_FIELD_TABLE_REF_OPCODES = (0x68,)  # push imm32

#: `PlayerTemplate` members. `+0x10` is the `NameKeyType` of the block name, and it is the only
#: **stable** identity a template has: templates live in a `std::vector<PlayerTemplate>` at
#: `PlayerTemplateStore+0x0C` with stride `0x1DC`, are parsed into a *stack temporary* and then
#: copied in, so every pointer a parse callback sees is transient.
#: `PlayerTemplateStore::findPlayerTemplate` (`0x005FCA2E`) walks that vector comparing exactly
#: this dword, which is what proves it survives the copy.
PLAYER_TEMPLATE_NAME_KEY = 0x10
PLAYER_TEMPLATE_RESOURCE_FILTER = 0x1C8  # ResourceModifierObjectFilter (an interned handle)
PLAYER_TEMPLATE_RESOURCE_VALUES = 0x1CC  # ResourceModifierValues, a std::vector<Int>
PLAYER_TEMPLATE_SIZE = 0x1DC

#: The one place a `PlayerTemplate` block's name key is computed, before any of the three parse
#: paths (new block / override / re-parse) branch. Hooking here is what lets a field callback
#: know *which faction* it is parsing without a usable `this` pointer.
#: The window is `mov edi, eax` / `push edi` / `call PlayerTemplateStore::findPlayerTemplate`.
PLAYER_TEMPLATE_BLOCK_KEY = 0x005FE886
PLAYER_TEMPLATE_BLOCK_KEY_BYTES = bytes.fromhex("8bf857e8a0e1ffff")
PLAYER_TEMPLATE_BLOCK_KEY_RESUME = 0x005FE88E
PLAYER_TEMPLATE_FIND_BY_KEY = 0x005FCA2E

#: `Player` members. `+0x34` is the (final-override) `PlayerTemplate*`; `+0x60` is the
#: command-point bookkeeping subobject and `+0x68` its "points in use" counter, which
#: `0x006A7FDA`/`0x006A7FEB` add to and subtract from by each owned object's
#: `ThingTemplate.CommandPoints` (`+0x628`) as it is created and destroyed.
PLAYER_PLAYER_TEMPLATE = 0x34
PLAYER_COMMAND_POINTS_USED = 0x68

#: The rest of the command-point block, as `Player::getCommandPointsAvailable` combines them:
#: `cap = min(+0x64 base + +0x6C bonus + <filtered extras>, +0x70 hard)`. The extras are a
#: vector at `+0x80`/`+0x84` whose entries carry an `ObjectFilter`, so evaluating them means
#: calling the engine - a reader that copies only the flat fields gets a **lower bound** on the
#: real ceiling, which is why all four are recorded rather than a computed total.
#: Confirmed live 2026-08-16: a fresh Angmar seat read used 120 / base 500 / bonus 0 / hard 1500.
PLAYER_COMMAND_POINTS_CAP = 0x64
PLAYER_COMMAND_POINTS_BONUS = 0x6C
PLAYER_COMMAND_POINTS_HARD_CAP = 0x70

#: The player's spendable resource balance, and the spellbook point pair (`+0x24` is the
#: spendable balance, `+0x1C` the lifetime total - only the former falls when a power is bought).
#:
#: **`+0x94` is not derivable from the `ScoreKeeper`'s money fields.** Measured live 2026-08-16
#: over 130 frames: `+0x94` tracked `starting purse + ScoreKeeper.money_earned` exactly, while
#: `money_spent` sat unchanged at 5000 from before the first order with `units_built` still 0 -
#: so `money_spent` carries a setup charge that was never deducted from the balance, and only
#: `+0x94` says what a player could actually afford.
#:
#: `Player+0x3E0` is deliberately absent: it is lifetime income and reads **byte-identical** to
#: `ScoreKeeper+0x04` on every sample, so recording it would duplicate a field.
PLAYER_RESOURCES = 0x94
PLAYER_POWER_POINTS = 0x24
PLAYER_POWER_POINTS_TOTAL = 0x1C

#: `PlayerList::getLocalPlayer` - thiscall, no arguments. The palantir's own refresh
#: (`0x006D577C`) reaches the displayed player through it, so a HUD-side read matches.
PLAYER_LIST_GET_LOCAL_PLAYER = 0x006A8839

#: The field that getter reads (`mov esi, [ecx+0x10]`), for a cave that wants the local player
#: without a call. The engine inlines the same read itself, e.g. at `0x00819CEA`.
PLAYER_LIST_LOCAL_PLAYER = 0x10

#: `AutoDepositUpdate::update` (`0x008854D3`) - the tick income path, and the *only* reader of
#: `PlayerTemplate.ResourceModifierValues` in the whole image.
#:
#: `..._SCALE` is where the finished inflation multiplier stops being written and starts being
#: used: `[ebp-0x1C]` holds it, nothing touches it between here and the `fmul` at `0x00885685`,
#: and the window is `mov eax, [ebp-0x18]` / `fild dword ptr [eax+0xC]` - six bytes.
#: `esi` is the controlling `Player` and `edi` the depositing `Object` throughout.
#:
#: `..._FILTER_EBP` holds `&template->ResourceModifierObjectFilter` **only until `0x00885672`**,
#: where a `fistp` reuses the slot for the rounded amount. A hook at `..._SCALE` is before that.
AUTO_DEPOSIT_SCALE = 0x00885650
AUTO_DEPOSIT_SCALE_BYTES = bytes.fromhex("8b45e8db400c")
AUTO_DEPOSIT_SCALE_RESUME = 0x00885656
AUTO_DEPOSIT_MULTIPLIER_EBP = -0x1C
AUTO_DEPOSIT_FILTER_EBP = -0x20
AUTO_DEPOSIT_MODULE_DATA_EBP = -0x18

#: `ObjectFilter::isValid` (thiscall, no arguments, `bool` in `al`) and the two-argument
#: `ObjectFilter::allow(Object*, Player*)` (thiscall, `ret 8`). Called back-to-back at
#: `0x008855BC`/`0x008855CE`; re-running the pair is how a second modifier taxes exactly the
#: objects the stock inflation taxes.
OBJECT_FILTER_IS_VALID = 0x00762977
OBJECT_FILTER_ALLOW = 0x007640C1

#: `Player::forEachTeamObject(fn, ctx)` - thiscall, `ret 8`, walks the team list at `Player+0x34C`
#: and stops early if `fn` returns 0. Pure: it writes nothing and takes no lock, so a HUD-side
#: read of the same count the deposit computes is safe.
#:
#: `..._COUNT_CALLBACK` is the engine's own per-object counter, `cdecl (Object*, void *ctx)` with
#: ``ctx = { ObjectFilter* filter; Int count; }``. It skips objects failing `testStatus(2)` and
#: counts those the filter accepts - calling `allow(object, NULL)`, a **null player**, where the
#: gate three instructions earlier passes the real one. Reusing it rather than writing a second
#: counter is what makes a readout agree with the deposit by construction.
PLAYER_FOR_EACH_TEAM_OBJECT = 0x006ABABD
RESOURCE_MODIFIER_COUNT_CALLBACK = 0x00885230

#: Float constants the inflation arithmetic reads, reused verbatim by anything that recomputes it.
FLOAT_ONE = 0x00BD1908  # 1.0f  - the "no modifier" multiplier
FLOAT_ONE_PERCENT = 0x00BE5600  # 0.01f - a percentage table entry into a multiplier
FLOAT_TWO_PERCENT = 0x00BDC320  # 0.02f - the per-object slope past the end of the table

#: `INI::getNextTokenOrNull(seps)` and `INI::scanInt(token)` - both thiscall on the `INI`, both
#: `ret 4`. The pair the stock `ResourceModifierValues` parser (`0x005FD599`) loops over, and
#: the only engine help a variable-length `Int` list parser needs.
INI_NEXT_TOKEN_OR_NULL = 0x0042DBF5
INI_SCAN_INT = 0x0042E9D7

#: The palantir's **resource-multiplier** readout - a slot that already exists, is already
#: refreshed every frame, and is already blank in a skirmish.
#:
#: The text builder at `0x00800844` takes one **float** and blanks itself at exactly `1.0f`
#: (`ucomiss` against `FLOAT_ONE`, then `L" "` at `0x00BD16E4`); anything else it formats with
#: `L"x%g"` (`0x00C4E5BC`) and pushes to `TheAptPlayer::setValue("APT:PalantirResourceMultiplier",
#: …)`. The `.csf` entry of that name is a design-time placeholder as usual - Edain's reads `x23`.
#:
#: The refresh at `0x006D577C` feeds it the War-of-the-Ring region bonus (`0x006E1F2F`, capped by
#: `GameData.ResourceMultiplierLimit`) and otherwise **exactly `1.0f`**, at the window below.
#: Replacing that constant load is therefore the whole of a readout: everything downstream - the
#: `ucomiss` change filter against the cached float at `palantir+0x18`, the builder, the blanking
#: rule - is untouched.
#:
#: The window is `movss xmm0, [FLOAT_ONE]` / `jmp 0x006D5A69`, thirteen bytes. All three branches
#: into it (`0x006D5997`, `0x006D59A0`, `0x006D59A7`) target its **first** byte, so nothing lands
#: inside and a five-byte `jmp` plus padding is safe.
PALANTIR_RESOURCE_MULTIPLIER = 0x006D59B7
PALANTIR_RESOURCE_MULTIPLIER_BYTES = bytes.fromhex("f30f10050819bd00e9a5000000")
PALANTIR_RESOURCE_MULTIPLIER_RESUME = 0x006D5A69

#: `UnicodeString::format(this, fmt, ...)` - cdecl, caller-cleaned, so one more vararg costs one
#: more push and a `0x10 -> 0x14` on the cleanup.
UNICODE_STRING_FORMAT = 0x00ADF750


#: `INI::parseUnsignedShort`, the stock `UInt16` field parser: cdecl, same four arguments as
#: `INI_PARSE_INT`, but it range-checks `0..0xFFFF` and stores a **word** through `store`. That
#: word store is what lets a new field live in two bytes of a struct's alignment padding, the way
#: `INI_PARSE_BOOL`'s byte store does for one.
INI_PARSE_UNSIGNED_SHORT = 0x0042EC11

#: `Money::deposit(amount, stats, playSound)` - thiscall on the `Money` subobject, three stack
#: arguments, callee-cleaned. The sibling `Money::withdraw` at `0x007B17EF` **clamps to what is
#: available and returns what it took**, which is why affordability is always decided upstream of
#: it and never by it. 35 call sites deposit, 22 withdraw.
MONEY_DEPOSIT = 0x007B18B8
MONEY_WITHDRAW = 0x007B17EF

#: `Player::m_money`, the `Money` subobject both income modules address as `lea ecx, [player+0x90]`
#: before the deposit, and `Money::m_amount` inside it.
#:
#: ⚠ **The amount is unsigned, and `deposit` does not check.** `Money::deposit` is
#: `add [this+4], amount` with no clamp, while `withdraw` compares with `cmova` - an *unsigned*
#: compare. So a "negative deposit" is not a charge that happens to be written oddly: it rolls the
#: balance through zero to about four billion gold. Anything charging a player goes through
#: `MONEY_WITHDRAW`, which clamps to what is there and returns what it took.
PLAYER_MONEY = 0x90
MONEY_AMOUNT = 0x04

#: The engine's own "you lost gold" floating text, at `0x008C6980` where a transfer pays one
#: player and charges another: `GUI:LoseCash` in red at the payer, `GUI:AddCash` in green at the
#: receiver, both lifted above the object by a constant. Reusing the pair is what keeps a charge
#: looking like something the game already does.
#:
#: `..._RISE` is the float added to the object's `z` (30.0f; the `AddCash` site uses 20.0f), and
#: the color is `ARGB`. `IN_GAME_UI_ADD_FLOATING_TEXT` is `TheInGameUI`'s vtable slot for
#: `addFloatingText(UnicodeString*, Coord3D*, Color)` - callee-cleaned, `ret 0xC`.
GUI_LOSE_CASH = 0x00C732F8
LOSE_CASH_COLOR = 0xFFFF0000
LOSE_CASH_RISE = 0x00BDAE54
IN_GAME_UI_ADD_FLOATING_TEXT = 0x1A0

#: `Object::m_position`, three floats. The floating-text sites read it as `[obj+0x38]`,
#: `[obj+0x3c]`, `[obj+0x40]` and hand `addFloatingText` a `Coord3D` copy.
OBJECT_POSITION = 0x38

#: `AutoDepositUpdate` - the "this structure pays you on a timer" module, and the one the
#: second-resource grant rides on. Derived in `docs/second-resource.md`.
#:
#: **Not** the module `AUTO_DEPOSIT_SCALE` above names: that constant sits inside
#: `TerrainResourceBehavior::update` (`0x008854D3`), the *other* income module, which is the only
#: reader of `PlayerTemplate.ResourceModifierValues`. The two are easy to confuse and the fields
#: read alike; the discriminator is the `ModuleData`, reached as `[ebp-0x18]` there and as
#: `[esi-0x0C]` here.
#:
#: `ModuleData` is 0x24 bytes holding eight fields ending with two `Bool`s at +0x20/+0x21, so
#: **+0x22 and +0x23 are alignment padding**: no field names them and the constructor never
#: writes them. The two `Bool` stores at `..._CTOR_BOOLS` are six bytes for what `mov [esi+0x20],
#: ebx` does in three with `ebx` already zero - and that one dword store clears the padding too,
#: so the new field's default costs no bytes at all.
AUTO_DEPOSIT_MODULE_DATA_CTOR = 0x00653EBA
AUTO_DEPOSIT_MODULE_DATA_SIZE = 0x24
AUTO_DEPOSIT_MODULE_DATA_CTOR_BOOLS = 0x00653EFB
AUTO_DEPOSIT_MODULE_DATA_CTOR_BOOLS_BYTES = bytes.fromhex("885e20885e21")
AUTO_DEPOSIT_FIELD_TABLE = 0x00C07FD8
#: One reference in the whole image - the `push` immediate inside `buildFieldParse`
#: (`0x00653F0E`) - and the table is walked to its terminator, so appending a field is one
#: 4-byte repoint and no bound raised anywhere.
AUTO_DEPOSIT_FIELD_TABLE_REFS = (0x00653F14,)
AUTO_DEPOSIT_FIELD_TABLE_REF_OPCODES = (0x68,)  # push imm32

#: The deposit inside `AutoDepositUpdate::update`, as a whole five-byte `call` - so the hook
#: displaces one complete instruction and needs no padding.
#:
#: `esi` is the module (its `ModuleData` at `[esi-0x0C]`) and `edi` the controlling `Player`,
#: both callee-saved across the deposit. `edi` stops being the player at the resume address,
#: where it is reloaded with the depositing object's `ExperienceTracker`.
AUTO_DEPOSIT_DEPOSIT = 0x0089DD08
AUTO_DEPOSIT_DEPOSIT_BYTES = bytes.fromhex("e8ab3bf1ff")
AUTO_DEPOSIT_DEPOSIT_RESUME = 0x0089DD0D
AUTO_DEPOSIT_MODULE_DATA_ESI = -0x0C

# The two sites a **negative** `DepositAmount` has to get past. Unlike `TerrainResourceBehavior`
# this module clamps the amount nowhere - `cvttss2si`, the region bonus at `0x006AA858` and the
# rounding helper at `0x00A3CFA4` all carry a sign through, and the floating `+N` text is already
# gated on `DepositAmount > 0` at `0x0089DD52`. Only the deposit itself and the experience grant
# need an edit.
#
# `..._PAY` is `lea ecx, [edi+0x90]`, the money pointer, chosen over the `call` five bytes later
# for one reason: `second-resource` owns that call. `edi` is the controlling `Player`, `[esi-8]`
# the depositing `Object`, `eax` and `[esp]` the signed amount. `..._PAY_RESUME` is the
# `mov [ebp-0x14], eax` between the two, so a positive amount rejoins *above* the call and
# whatever occupies it still runs.
AUTO_DEPOSIT_PAY = 0x0089DCFF
AUTO_DEPOSIT_PAY_BYTES = bytes.fromhex("8d8f90000000")  # lea ecx, [edi+0x90]
AUTO_DEPOSIT_PAY_RESUME = 0x0089DD05
AUTO_DEPOSIT_OBJECT_ESI = -0x08

# `..._XP_GATE` is the module's stock `GiveNoXP` test - `cmp byte [eax+0x20], 0 / jne` with `eax`
# already holding the `ModuleData`. It is the field `terrain-resource-exp` reproduces on the other
# income module, and it is the natural place to add a second reason to skip the grant.
# `..._XP_GATE_RESUME` is the null-tracker test the untaken branch falls into, `..._XP_GATE_SKIP`
# the address the taken one jumps to.
AUTO_DEPOSIT_XP_GATE = 0x0089DD19
AUTO_DEPOSIT_XP_GATE_BYTES = bytes.fromhex("807820007530")  # cmp byte [eax+0x20], 0 / jne
AUTO_DEPOSIT_XP_GATE_RESUME = 0x0089DD1F
AUTO_DEPOSIT_XP_GATE_SKIP = 0x0089DD4F

# Where `AutoDepositUpdate::update`'s amount stops being a float: `cvttss2si eax, [ebp-0x14]`,
# after `UpgradeBonusPercent` (0x0089DC83) and the difficulty handicap (0x0089DCD2) and before the
# War-of-the-Ring region bonus (0x0089DCE5) and the final rounding. Derived in
# `docs/auto-deposit-inflation.md`.
#
# **Five bytes holding exactly one instruction**, so a detour needs no padding. The window's first
# byte is a branch target - `je 0x0089DCDD` at 0x0089DCB7, the no-handicap path - which is what a
# detour wants: both paths converge on it and both get scaled. Nothing lands in its interior, and
# no byte of it appears as an imm32 anywhere in the image; `scripts/scan_branches.py` is what
# establishes that, by decoding a branch at every byte offset rather than sweeping linearly.
#
# `edi` is the controlling `Player` and `[esi-8]` the depositing `Object` here, and `eax` is the
# only register the resume point needs.
AUTO_DEPOSIT_TRUNCATE = 0x0089DCDD
AUTO_DEPOSIT_TRUNCATE_BYTES = bytes.fromhex("f30f2c45ec")  # cvttss2si eax, dword ptr [ebp-0x14]
AUTO_DEPOSIT_TRUNCATE_RESUME = 0x0089DCE2
AUTO_DEPOSIT_SCALE_AMOUNT_EBP = -0x14
AUTO_DEPOSIT_GIVE_NO_XP = 0x20
AUTO_DEPOSIT_AMOUNT = 0x0C

#: The `PlayerTemplate` block's name key, one instruction *before*
#: `PLAYER_TEMPLATE_BLOCK_KEY` - `eax` already holds the key and the window is the six bytes of
#: `mov ecx, [PlayerTemplateStore]`.
#:
#: Two hooks are needed here rather than one because a template's per-block key is the only
#: identity a field callback can file against, and `command-point-upkeep` already owns the
#: instruction pair at `PLAYER_TEMPLATE_BLOCK_KEY`. The two windows do not overlap and neither
#: reads what the other writes: both only copy `eax`.
PLAYER_TEMPLATE_BLOCK_KEY_EARLY = 0x005FE880
PLAYER_TEMPLATE_BLOCK_KEY_EARLY_BYTES = bytes.fromhex("8b0d103bde00")
PLAYER_TEMPLATE_BLOCK_KEY_EARLY_RESUME = 0x005FE886

#: `Player::init(PlayerTemplate *)` - the one place a player's purse is seeded from its faction,
#: and therefore the one place a second pool has to be seeded and cleared.
#:
#: `PlayerList`'s own reset (`0x006A8916`) calls it on **all twenty slots** with a NULL template,
#: and the money block is inside the `template != NULL` branch - so a hook placed at the money
#: block would never clear an unused slot. `..._ENTRY` is past the SEH prologue and before that
#: branch, with `ecx` still the `Player` and `[ebp+8]` the template, so one hook both clears and
#: seeds. Four callers, none of them a per-frame path.
PLAYER_INIT = 0x006B0239
PLAYER_INIT_ENTRY = 0x006B0243
PLAYER_INIT_ENTRY_BYTES = bytes.fromhex("83ec0c8b4508")
PLAYER_INIT_ENTRY_RESUME = 0x006B0249

#: `AsciiString::format(this, fmt, ...)` - cdecl, caller-cleaned, so one more vararg costs one
#: more push and a `0x0C -> 0x10` on the cleanup. The narrow sibling of `UNICODE_STRING_FORMAT`:
#: the palantir's **resource** text is built as an `AsciiString` from an 8-bit `"%d"` and only
#: widened on the way into the movie, where the command-point text is `UnicodeString` throughout.
ASCII_STRING_FORMAT = 0x00437A90

#: The palantir's resource text, built and pushed to the movie in one place - the same shape as
#: `PALANTIR_COMMAND_POINTS`, and the reason a second number needs no `.apt` edit.
#:
#: `0x006D56E1` takes the amount as its only argument, formats `"%d"` (`0x00BD4194`, **8-bit**)
#: into an `AsciiString` and hands it to `TheAptPlayer::setValue("APT:PalantirResources", …)`
#: through the widening wrapper at `0x00625071`. A negative amount takes a `" "` placeholder
#: (`0x00BD343C`) instead. So the movie's own text is overwritten every refresh and a mod's `.csf`
#: entry of that name is a design-time placeholder, exactly as for the command-point readout.
#:
#: The window is `cmp [ebp+8], 0` / `mov [ebp-4], 1` - eleven bytes, sitting *before* the first
#: vararg push, which is the only place a second one fits. `[ebp-4]` is the SEH state marking the
#: `AsciiString` at `[ebp-0x10]` constructed, so a hook has to keep writing it on every path.
PALANTIR_RESOURCES = 0x006D5721
PALANTIR_RESOURCES_BYTES = bytes.fromhex("837d0800c745fc01000000")
PALANTIR_RESOURCES_RESUME = 0x006D572C
PALANTIR_RESOURCES_DONE = 0x006D5751  # the setValue, past the format

#: The refresh's change filter, in the palantir update at `0x006D577C`.
#:
#: `edi` is the local player's gold (or -1 when there is no playable local player) and `[esi+0xC]`
#: the last value pushed; the text call only happens when they differ. **A second number has to
#: widen that filter or it goes stale**, because a game where gold is momentarily flat still moves
#: the second pool. `cmp edi, [esi+0xC]` / `je` is exactly five bytes.
PALANTIR_RESOURCES_CACHE = 0x006D5804
PALANTIR_RESOURCES_CACHE_BYTES = bytes.fromhex("3b7e0c740a")
PALANTIR_RESOURCES_CACHE_PUSH = 0x006D5809  # push the value and call the text builder
PALANTIR_RESOURCES_CACHE_SKIP = 0x006D5813  # unchanged: no text this frame

#: `ThingTemplate+0x5E8`, and why a second build cost cannot live there.
#:
#: The idea document costs the 2-byte gap between `CampnessValue` (an `Int` at +0x5E4) and
#: `BuildCost` (a `UInt16` at +0x5EA) as possibly-free storage. **It is not.** It is the
#: template's engine-assigned id: a dedicated setter at `0x006CFBC7`, a down-counting global
#: allocator at `0x00DA18E4`, ~15 readers, and the ControlBar pushes it into build orders
#: (`0x00940948`). An override *swaps* ids so the new template inherits the old one's identity.
#:
#: That is the second apparent hole in a template that turned out to be a real member - see
#: `PlayerTemplate+0x34` in `docs/second-resource.md` §1.2 - and it is why `BuildCost2` is keyed
#: in a cave rather than stored on the template.
THING_TEMPLATE_ID = 0x5E8
THING_TEMPLATE_ID_SETTER = 0x006CFBC7
THING_TEMPLATE_ID_COUNTER = 0x00DA18E4
THING_TEMPLATE_BUILD_COST = 0x5EA
THING_TEMPLATE_REFUND_VALUE = 0x5EC

#: The id copy **inside** `ThingTemplate::copyFrom`, where `eax` is the source template and `ebx`
#: the destination. Anything keyed on a `ThingTemplate *` has to ride this, or an INI override
#: block silently loses whatever the base template carried.
#:
#: `hero-mana` rides the same copy from the outside, by retargeting its **call site**
#: (`THING_TEMPLATE_COPY_CALL`). This is the body, so the two do not share a byte - and hooking
#: the body also covers any caller that is not that one call.
THING_TEMPLATE_COPY_ID = 0x006D24B7
THING_TEMPLATE_COPY_ID_BYTES = bytes.fromhex("668b88e8050000")
THING_TEMPLATE_COPY_ID_RESUME = 0x006D24BE

#: The one affordability comparison every human production path shares, inside `BuildAssistant`'s
#: `+0x64` gate (`0x00793ECB`).
#:
#: `esi` is the `Player` (`+0x94` is its gold), `eax` the cost `calcCostToBuild` just returned
#: (`0x0073C25F`), `ebx` gold plus the allowance the frame computed, and `[ebp+0xC]` the
#: `ThingTemplate` being priced. The window is `cmp eax, ebx` / `jbe <affordable>` / `push 2` -
#: six bytes - and **2 is the engine's own "not enough money" code**, so refusing here reuses the
#: refusal message and the button tint that already exist.
BUILD_GATE_AFFORD = 0x00794013
BUILD_GATE_AFFORD_BYTES = bytes.fromhex("3bc376076a02")
BUILD_GATE_AFFORD_OK = 0x0079401E  # affordable: on with the rest of the checks
BUILD_GATE_AFFORD_REFUSE = 0x00794019  # the jmp that carries the pushed code out
BUILD_GATE_TEMPLATE_EBP = 0x0C
BUILD_GATE_NOT_ENOUGH_MONEY = 2

#: `ProductionUpdate::queueCreateUnit`'s withdrawal, as a whole five-byte `call`.
#:
#: `[ebp-0x0C]` is the `Player` (`ecx` has already become `&player->m_money` by here) and
#: `[ebp+8]` the `ThingTemplate` being produced - the same one the `ScoreKeeper` call three
#: instructions later is given.
PRODUCTION_WITHDRAW = 0x008A12A2
PRODUCTION_WITHDRAW_BYTES = bytes.fromhex("e84805f1ff")
PRODUCTION_WITHDRAW_RESUME = 0x008A12A7
PRODUCTION_WITHDRAW_PLAYER_EBP = -0x0C
PRODUCTION_WITHDRAW_TEMPLATE_EBP = 0x08

#: The two `TOOLTIP:Cost` lines in the ControlBar's description builder that price a
#: `ThingTemplate` - a unit or structure to build, and a hero to revive or recruit.
#:
#: `TOOLTIP:Cost` (`0x00C4F028`) has four call sites; these are the two where the thing being
#: priced is a template in a known register, and they are exactly the two `BuildCost2` applies to.
#: The other two price a science and a per-frame float.
#:
#: Every site shares one shape: three pushes, `TheGameText`'s vtable `+0x44` formats the localized
#: line into `eax`, then the line is concatenated onto the description at `ebp-0x28`. The window
#: named here is `push eax` / `lea eax, [ebp-0x28]` / `push eax` - five bytes, sitting **after**
#: the line exists and **before** it is handed over, which is the one place a suffix can join it.
TOOLTIP_COST_BUILD = 0x00807F82
TOOLTIP_COST_BUILD_RESUME = 0x00807F87
TOOLTIP_COST_REVIVE = 0x008085EC
TOOLTIP_COST_REVIVE_RESUME = 0x008085F1
TOOLTIP_COST_BYTES = bytes.fromhex("508d45d850")

#: `UnicodeString::~UnicodeString` - thiscall, no arguments. Needed because a suffix built with
#: `UNICODE_STRING_FORMAT` is a real string with a real allocation, not a literal.
UNICODE_STRING_DTOR = 0x004367B0

# --- CommandButton, and the command-point gate a button press meets -------------------------

#: `CommandButton`, the INI block the ControlBar allocates one of per `CommandButton` definition.
#: `operator new(0x2E0)` at `ControlBar::newCommandButton` (`0x0071C439`), then the constructor.
COMMAND_BUTTON_SIZE = 0x2E0
COMMAND_BUTTON_CTOR = 0x0075D516

#: `Command`, the `GUICOMMAND` the button dispatches on - `Object::doCommandButton`'s switch
#: reads exactly this (`0x00697086`). `3` is `UNIT_BUILD` and `46` is `REVIVE`
#: (`GUICOMMAND_REVIVE`), the two cases that reach production.
COMMAND_BUTTON_COMMAND = 0x14

#: `AutoAbility`, the last `Bool` before the `KindOfFlags` at +0x110, and **the three bytes after
#: it are alignment padding**: no field in the table names +0x10D..+0x10F, the constructor never
#: writes them, and the `memset(this+0x110, 0, 0x1C)` that follows starts past them.
#:
#: That is what makes the new field's default free. The constructor's `mov byte [esi+0x10C], bl`
#: becomes `mov dword [esi+0x10C], ebx` - **one byte changed, six for six** - and since `ebx` is
#: the zero the whole constructor stores from (it is `xor ebx, ebx` at 0x0075D52A and is what
#: `RequireLevel` is defaulted with six bytes earlier), the dword store leaves `AutoAbility` at
#: `No` and clears the padding on the way past.
#:
#: +0x103, the other apparent hole, is **not** one: the constructor zeroes it explicitly and
#: `CommandButton::getBorderType` (`0x0075CBA5`) returns border type 5 when it is set.
COMMAND_BUTTON_AUTO_ABILITY = 0x10C
COMMAND_BUTTON_FREE_OFFSET = 0x10D
COMMAND_BUTTON_CTOR_AUTO_ABILITY = 0x0075D688
COMMAND_BUTTON_CTOR_AUTO_ABILITY_BYTES = bytes.fromhex("889e0c010000")

#: The `CommandButton` field-parse table (55 rows on the stock build) and its **three**
#: references: the static accessor `mov eax, imm32` / `ret` at `0x005DA706`, and the two `push`
#: immediates in the block parser (`0x005DA711`) - one for a fresh button, one for an override.
#: The table is walked to its NULL terminator rather than to a count, so appending a row needs no
#: bound raised anywhere.
COMMAND_BUTTON_FIELD_TABLE = 0x00C2BAC8
COMMAND_BUTTON_FIELD_TABLE_REFS = (0x005DA706, 0x005DA7B6, 0x005DA7D0)
COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES = (0xB8, 0x68, 0x68)  # mov eax, imm32 / push imm32

#: `Object::doCommandButton(CommandButton *btn, ...)` - the one dispatcher every button press
#: goes through, whether the press came from a player's order or from the engine itself
#: (`DoCommandUpgrade` calls it directly). `btn` stays in `[ebp+8]` for the whole function.
DO_COMMAND_BUTTON = 0x00696FD2
DO_COMMAND_BUTTON_BUTTON_EBP = 0x08

#: The `UNIT_BUILD` case's call to `ProductionUpdate::queueCreateUnit` (interface vtable +0x20),
#: as `mov ecx, edi` plus the call - five bytes, two whole instructions, so the hook displaces no
#: partial one. `edi` is the production interface and `esi` its vtable; every argument has
#: already been pushed, and `eax` (the id `requestUniqueUnitID` just minted) is dead, having been
#: pushed at 0x006977FA.
DO_COMMAND_BUTTON_UNIT_QUEUE = 0x00697800
DO_COMMAND_BUTTON_UNIT_QUEUE_BYTES = bytes.fromhex("8bcfff5620")
DO_COMMAND_BUTTON_UNIT_QUEUE_RESUME = 0x00697805

#: The `REVIVE` case's call to the same slot: `mov ecx, esi` / `push ebx` / `call [edi+0x20]`.
#: Six bytes, so the hook is a `jmp rel32` plus one `nop`. Here `esi` is the interface and `edi`
#: its vtable - the opposite of the `UNIT_BUILD` case - and `ebx` is the zero that stands in for
#: the `ThingTemplate` a revive does not name.
DO_COMMAND_BUTTON_REVIVE_QUEUE = 0x00697403
DO_COMMAND_BUTTON_REVIVE_QUEUE_BYTES = bytes.fromhex("8bce53ff5720")
DO_COMMAND_BUTTON_REVIVE_QUEUE_RESUME = 0x00697409

#: `DoCommandUpgrade`'s two halves, and the reason a `CommandButton` field can carry engine-side
#: behaviour at all: each looks its button up by name in `TheControlBar`
#: (`ControlBar::findCommandButton`, `0x0071D6EA`, from `ModuleData+0x138` /  `+0x13C`) and then
#: calls `DO_COMMAND_BUTTON` on the owning object with it.
DO_COMMAND_UPGRADE_GET = 0x008B8E2E
DO_COMMAND_UPGRADE_REMOVE = 0x008B8DFC

#: `CommandPointBookkeeping::hasEnoughCommandPoints(const ThingTemplate *what, Int count)`, on
#: the subobject at `Player+0x60`. Returns `inUse + what->CommandPoints <= cap`, or TRUE outright
#: when `what` costs no command points or carries the `ARMY_OF_DEAD` KindOf. `count` is pushed by
#: every caller and read by none.
COMMAND_POINTS_HAS_ENOUGH = 0x006A7F79
COMMAND_POINTS_IN_USE = 0x08

#: The command-point verdict inside `BuildAssistant`'s `+0x64` gate
#: (`CAN_MAKE_UNIT_PRODUCTION_GATE`), eight bytes: `test al, al` / `jne <ok>` / `push 7` /
#: `jmp <carry the code out>`. It is the **last** refusal in the gate and it sits below the money
#: one (`BUILD_GATE_AFFORD`, 24 bytes earlier, which `second-resource` takes), so the two do not
#: share a byte.
#:
#: Both branches arrive here: `0x00793FED` jumps into the call at `0x00794023` with the revive's
#: template, so hooking the verdict covers `UNIT_BUILD` and `REVIVE` at once.
BUILD_GATE_COMMAND_POINTS = 0x0079402B
BUILD_GATE_COMMAND_POINTS_BYTES = bytes.fromhex("84c075046a07eb6b")
BUILD_GATE_COMMAND_POINTS_OK = 0x00794033  # enough: on with the rest of the checks
BUILD_GATE_COMMAND_POINTS_REFUSE = 0x0079409E  # the `pop eax` that carries the pushed code out
BUILD_GATE_NOT_ENOUGH_COMMAND_POINTS = 7

#: Where the **stock** engine already holds a queue that has outrun the command-point cap, and
#: the reason this patch needs no second half. Neither address is patched; they are named so the
#: claim can be checked.
#:
#: `PRODUCTION_UPDATE_COMMAND_POINT_STALL` is inside `ProductionUpdate::update`: for a head entry
#: of kind 1 (unit) or 3 (revive) it asks `COMMAND_POINTS_HAS_ENOUGH` about the entry's own
#: template and, when the answer is no, plays EVA message 0x0B for the local player and returns
#: **before** the block at `0x008A1EBC` that adds this frame's progress to `entry+0x1C`. The
#: queue simply does not advance.
#:
#: `PRODUCTION_UPDATE_REVIVE_COMMAND_POINT_DELAY` is the revive-side equivalent, called from the
#: top of `update` (`0x008A1C10`): it walks the queue and, for every kind-3 entry the player
#: cannot afford, increments that hero's revive start frame (`ReviveMgr` entry +0xA8) - pushing
#: the completion out by one frame for as long as the cap holds.
PRODUCTION_UPDATE_COMMAND_POINT_STALL = 0x008A1E27
PRODUCTION_UPDATE_REVIVE_COMMAND_POINT_DELAY = 0x008A0669

# --- the shell's campaign start ---------------------------------------------------------------
#
# Derived in `docs/campaign-select.md`. `AptMainMenu` registers a string-keyed callback map at
# `this+0x21C` in its constructor (`0x0091CA80` onwards, one ~85-byte block per command); the
# APT movie reaches those callbacks through `_root.GameCode(func, params)`, which is
# `geturl2("FSCommand:AptMainMenu::" + func, params)`.

#: `AsciiString::set(const char *)` - `strlen`s its argument and hands both to the buffer assign
#: at `0x004360C0`, which releases or reuses whatever the string already held. Safe to call on a
#: never-constructed (zeroed) `AsciiString` as well: the assign tests `m_data` against NULL first.
#: `ret 4`, so it cleans its own argument; `esi`/`edi` are pushed and popped.
ASCII_STRING_SET = 0x004050E6
ASCII_STRING_SET_BYTES = bytes.fromhex("568b74240885f6578bf9740956e8187e6300")

#: `AptMainMenu::Expansion1Campaign`, the FSCommand name, and the registration block that binds it
#: to `MAIN_MENU_CAMPAIGN_HANDLER`: `push <name>` / `lea ecx, [ebp+8]` / `mov esi, <handler>`.
#: Fingerprinting the registration rather than the handler alone is what proves `0x0091AF8C` is
#: *this* command's callback and not the identically shaped `BonusCampaign` one 35 bytes later.
MAIN_MENU_CAMPAIGN_COMMAND = 0x00C7D254
MAIN_MENU_CAMPAIGN_REGISTRATION = 0x0091CB02
MAIN_MENU_CAMPAIGN_REGISTRATION_BYTES = bytes.fromhex("6854d2c7008d4d08be8caf9100")

#: The callback itself, whole (35 bytes, `thiscall`, `ret 4`, one `const char *` argument):
#:
#:     mov  eax, [esp+4]              ; the FSCommand's params string
#:     mov  [ecx+0x288], 9            ; MAIN_MENU_PHASE_LEAVING
#:     mov  [ecx+0x28C], 0Dh          ; MAIN_MENU_CAMPAIGN_SELECTION_ID
#:     mov  al, [eax]                 ; **only the first byte is kept**
#:     mov  [ecx+0x2A8], al           ; 'E' / 'M' / 'H', from "Easy" / "Medium" / "Hard"
#:     ret  4
#:
#: The whole of `campaign-select` follows from line four: the params string is a `const char *`
#: the engine already has in hand and already dereferences, and it throws away everything after
#: the first character.
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

#: The function-local `static AsciiString` that case 13's start thunk (`0x0091BE64`) passes to
#: `startLinearCampaign` (`0x0091B1D2`, which resolves it through `TheCampaignManager` and does
#: nothing if the name is unknown), and the MSVC magic-static guard beside it:
#:
#:     0091BE96  test byte ptr [0x00DEA360], 1   ; the guard
#:     0091BE9D  push esi
#:     0091BE9E  mov  esi, 0x00DEA35C            ; the static - loaded unconditionally
#:     0091BEA3  jne  0x0091BECA                 ; already initialised -> straight to the start
#:
#: The initialisation the `jne` skips is the *only* place the hardcoded `ANGMAR_CAMPAIGN` string
#: reaches the static, and it runs at most once per process. Filling the static and setting the
#: guard before the thunk runs therefore substitutes the campaign name without touching the thunk,
#: the jump table or the callback registry.
CAMPAIGN_NAME_STATIC = 0x00DEA35C
CAMPAIGN_NAME_STATIC_GUARD = 0x00DEA360
CAMPAIGN_NAME_BIND = 0x0091BE96
CAMPAIGN_NAME_BIND_BYTES = bytes.fromhex("f60560a3de000156be5ca3de007525")

# --- the command line, and the two instructions that give it its length ----------------------
#
# `game.dat` parses argv against a table of `{const char *name, int (*handler)(char **argSlot,
# int remaining)}`. The dispatcher compares with `_strnicmp` and requires equal length, rewrites
# a leading `0x96` (a Word en-dash) to `-` first, and adds each handler's return value to the
# argument index - so a handler returns how many arguments it consumed, 1 for a flag and 2 for
# one that takes a value. Only `eax`, `ecx` and `edx` are free inside one.
#
# The table's address and its length reach the dispatcher from a single call site, as a
# register load and a pushed constant. That is what makes the table extensible in six bytes:
# repoint `CLI_TABLE_REF` at a copy with more rows and raise the count. `push imm8` reaches 127
# entries, so the count edit keeps its length and nothing shifts.
#
# Derived in `docs/headless.md` §1.
CLI_TABLE = 0x00C35DA8
CLI_TABLE_ENTRIES = 16
CLI_TABLE_BYTES = CLI_TABLE_ENTRIES * 8
CLI_DISPATCH = 0x007BA7E1
CLI_TABLE_REF = 0x007BAA4B  # mov ebx, 0x00C35DA8
CLI_COUNT_REF = 0x007BAA54  # push 0x10

#: The options at four positions of the stock table, as `{index: name}`. Enough to prove the
#: table being copied is this build's - a table that has moved, or a build whose option list
#: differs, fails here rather than being copied verbatim into the cave and dispatched to.
CLI_TABLE_FINGERPRINT = {
    0: "-noshellmap",
    5: "-win",
    14: "-resumeGame",
    15: "-randomSeed",
}

#: `msvcr71.dll!atoi`, as its import-address-table slot. The stock `-xres` handler
#: (`0x007BA104`) calls through this slot, which is how a new handler reads a numeric argument.
CRT_ATOI = 0x00BD0628

# --- the per-frame draw ------------------------------------------------------------------------
#
# `TheDisplay`, and the one call that draws a frame. `GameClient::update` reaches the display
# twice: `update` through vtable `+0x28` at `0x00648838`, then `draw` through `+0x30` eleven
# bytes later. Suppressing the second is what makes a headless run cheap; the first is left
# alone, because everything downstream of the display's own update is state, not pixels.
#
# `THE_DISPLAY` has 540 references in `.text`, essentially none of them null-checked, which is
# why a headless mode here suppresses drawing rather than removing the display.
THE_DISPLAY = 0x00DE4418
DISPLAY_DRAW_VTABLE_SLOT = 0x30
GAME_CLIENT_DRAW = 0x00648861
GAME_CLIENT_DRAW_BYTES = bytes.fromhex("8b0d1844de008b01ff5030")

# --- `TheWritableGlobalData`, and the two frame-rate fields -------------------------------------
#
# The pointer, and the pair of `GameData` fields that cap the loop. Both are ordinary INI fields
# (the field-parse table at `0x00BFF580` maps `UseFPSLimit` to `+0x26` and
# `FramesPerSecondLimit` to `+0x28`) and both are read live - `0x0063A01B` copies `+0x26` into
# the loop's own global, and `0x0062C6FF` already writes the pair at runtime.
#
# The command line is parsed *after* `GlobalData`'s INI is loaded (`0x0063AFA4` registers and
# loads it, `0x0063AFB2` parses argv), so a handler writing these fields wins over the tree.
GLOBAL_DATA = 0x00DE4364
GLOBAL_DATA_USE_FPS_LIMIT = 0x26
GLOBAL_DATA_FPS_LIMIT = 0x28

# --- `GameData`'s LivingWorldCampaignOverrride, and the two parsers -----------------------------
#
# A `GameData` field-table row is `{const char *name, parse_fn, user_data, offset}`. Two of the
# parsers matter here, both identified by the fields that already use them: `0x0042E558` is the
# `Bool` parser (`Windowed`, `AudioOn`, `ShellMapOn`), and ends in `mov byte ptr [ecx], al`;
# `0x0042EE5E` is the `AsciiString` parser, which `ShellMapName` uses.
#
# `LivingWorldCampaignOverrride` (the engine's own spelling) names a `LivingWorldCampaign` to start
# by name. Its row declares the **Bool** parser while `GlobalData+0x8C` is an `AsciiString` in
# every code path - the constructor stores a pointer there (`0x00642AA3`), the campaign selector
# calls `AsciiString::isEmpty` on it (`0x007B96E4`), and the orphaned command-line handler at
# `0x007BAA28` sets it with `AsciiString::set`. Setting it in INI writes one byte over the pointer.
#
# Derived in `docs/living-world-campaign.md`.
GAME_DATA_BOOL_PARSER = 0x0042E558
GAME_DATA_ASCIISTRING_PARSER = 0x0042EE5E
GAME_DATA_SHELL_MAP_NAME_ROW = 0x00C00500  # the anchor proving the AsciiString parser's address
LIVING_WORLD_OVERRIDE_ROW = 0x00BFF740
LIVING_WORLD_OVERRIDE_OFFSET = 0x8C

# The two `LiveCampaignMode` gates, named so the doc's claims can be re-checked. Neither is
# patched: the flag defaults to **1** (`GlobalData`'s constructor, `0x00642A91`), so both pass.
LIVE_CAMPAIGN_MODE_OFFSET = 0x86
CAMPAIGN_SELECT_GATE = 0x007B96DA
CAMPAIGN_ADVANCE_GATE = 0x007B9714
#: Answers "may this campaign appear in the War of the Ring scenario list" - and says no as soon as
#: `IsScriptedCampaign` (`campaign+0x58`) is set.
CAMPAIGN_LIST_PREDICATE = 0x007B9551

# --- the Palantir's objectives button, and which screen it opens ---------------------------------
#
# The button does not show or hide: it pushes **one of three movies**, and
# `IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY` (`0x00625456`, above) is asked **twice** on the way -
# once to pick the handler, then again inside the handler it picked.
#
# The outer question runs in the button's own callback (`0x006D40C9`) and, identically, in the
# hotkey dispatch (`0x0081FFAA`):
#
#     006d40d2  call 0x00625456
#     006d40d9  je   0x006D40E2
#     006d40db  call 0x00914EF0      ; pushes "PlayerTribute.apt" unconditionally
#     006d40e2  call 0x008E8843      ; asks again, below
#
# and the inner one is inside `0x008E8843`:
#
#     008e8958  call 0x00625456
#     008e8961  test al, al
#     008e8968  je   0x008E8972
#     008e896b  push 0x00C18C2C      ; "PlayerStatus.apt"  - the player/enemy list
#     008e8972  push 0x00C18C5C      ; "Objectives.apt"
#
# Every term of that predicate is a game-type test; none of them consults the map. A War of the
# Ring battle is skirmish-mode, so the outer question already routes it to the tribute screen and
# `0x008E8843` never runs - which is why the campaign maps show the resource-transfer screen where
# objectives belong. Redirecting only the inner call changes nothing outside the linear campaign.
#
# Not to be confused with `0x006D7873`, which gates the button's **flash** on whether the living
# world is active (its helper targets the APT function `FlashObjectivesButton`). That one changes
# no screen. Derived in `docs/objectives-in-any-map.md`.
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

#: `TheSidesList`, the singleton the map's sides are read into and the skirmish sides parked in.
#: `+0x3c`/`+0x40` are the live sides (`SidesInfo`, stride `0x60`); `+0x7c0`/`+0x7c4` the skirmish
#: sides `SidesList::prepareForMP` (`0x0073193d`) moves everything but neutral, `PlyrCivilian` and
#: `PlyrCreeps` into. Derived in `docs/skirmish-ai-fallback.md`.
THE_SIDES_LIST = 0x00DE77A0

#: One instruction that loads it, inside `Player::initFromDict` - so asserting these bytes proves
#: the global *and* that the function around the hooks is this build's.
THE_SIDES_LIST_LOAD = 0x006B0DC1
THE_SIDES_LIST_LOAD_BYTES = bytes.fromhex("8b0da077de00")

#: `SidesList::getSideInfo(Int)` - `__thiscall`, `ret 4`, bounds-checked against `+0x3c`, returns
#: `this + 0x40 + i * 0x60` or NULL. The index is a *sides* index, which is what `Player+0x54`
#: holds: `PlayerList::newGame` walks the sides in order and hands each one to `initFromDict`.
SIDES_LIST_GET_SIDE_INFO = 0x00602F20
SIDES_LIST_GET_SIDE_INFO_BYTES = bytes.fromhex("8b44240485c0")

#: The `Dict` inside a `SidesInfo`. `PlayerList::newGame` passes `&sideInfo->m_dict` as
#: `initFromDict`'s argument, so the player's own side dict is reachable both ways.
SIDES_INFO_DICT = 0x04

#: `SidesList::loadAILibraryForSide(Int)` - `__thiscall`, `ret 4`. Builds the loader's temporaries
#: and calls the per-side loader at `0x0073161c`, which reads `playerAIType` off that side's dict,
#: resolves it through `TheAIPlayerTypeStore` (`0x00DE3D5C`) and merges the named `LibraryMap`'s
#: scripts into the side. **The stock image never calls it** - it is the single-side sibling of the
#: whole-list `0x007318a1` that `prepareForMP` uses, which is exactly what a per-player load needs.
SIDES_LIST_LOAD_AI_LIBRARY_FOR_SIDE = 0x007318F4
SIDES_LIST_LOAD_AI_LIBRARY_FOR_SIDE_BYTES = bytes.fromhex("b89202b900e8")

#: `Dict::setAsciiString(NameKey, const AsciiString&)` - `__thiscall`, `ret 8`, key pushed last.
DICT_SET_ASCII_STRING = 0x00715028
DICT_SET_ASCII_STRING_BYTES = bytes.fromhex("566a03ff7424")

#: `StaticNameKey::key()` - `__thiscall`, no arguments, `ret`, interns on first use and caches into
#: `[this]`. A `StaticNameKey` is `{ NameKey m_key; const char *m_name; }`, so `+4` is the name and
#: the key slot reads zero in the file.
STATIC_NAME_KEY_KEY = 0x00548930
STATIC_NAME_KEY_KEY_BYTES = bytes.fromhex("568bf1833e00")

#: The `StaticNameKey` for `playerAIType`, the side-dict key naming a `PlayerAIType` block. Its
#: bytes are the empty key plus the pointer to the literal at `0x00C1FB20`.
KEY_PLAYER_AI_TYPE = 0x00DA2FA4
KEY_PLAYER_AI_TYPE_BYTES = bytes.fromhex("0000000020fbc100")

#: `Player::m_playerTemplate`, set by `PLAYER_INIT`.
PLAYER_TEMPLATE_PTR = 0x34

#: `PlayerTemplate::m_defaultPlayerAIType` - the `DefaultPlayerAIType` INI field, which names the
#: `PlayerAIType` block whose `LibraryMap` is that faction's AI script library. `prepareForMP`
#: stamps it onto each skirmish side from *that side's* faction, which is why a borrowed side
#: brings a borrowed library.
PLAYER_TEMPLATE_DEFAULT_AI_TYPE = 0x1B0

#: Its entry in the `PlayerTemplate` field table - name pointer, parser, userdata, offset. Asserting
#: it is how `PLAYER_TEMPLATE_DEFAULT_AI_TYPE` stops being a number somebody wrote down: the INI
#: parser itself says where that field lands.
PLAYER_TEMPLATE_FIELD_DEFAULT_AI_TYPE = 0x00BF84C8
PLAYER_TEMPLATE_FIELD_DEFAULT_AI_TYPE_BYTES = bytes.fromhex("f87dbf005eee420000000000b0010000")

#: `Player::setPlayerType(PlayerType, Bool isSkirmish)` - `__thiscall`, `ret 8`. Type 1 is
#: `PLAYER_COMPUTER`; with `isSkirmish` it allocates an `AISkirmishPlayer` (`0xa4`, ctor
#: `0x008F3DF3`) and without it the legacy `AIPlayer` (`0x7c`, ctor `0x008F7F2B`). Type 0 gets
#: neither unless `TheSkirmishAIManager+0x96c` (`MakeAllSkirmishSidesAIControlled`) is set.
PLAYER_SET_TYPE = 0x006AA450
PLAYER_SET_TYPE_BYTES = bytes.fromhex("b8989db800e8")

#: `Player::initFromDict(Dict *)` - where a side becomes a player, and where both skirmish hooks
#: live.
PLAYER_INIT_FROM_DICT = 0x006B07EF
PLAYER_INIT_FROM_DICT_BYTES = bytes.fromhex("b8dea0b800e8f7c6")

#: Its two frame locals. `..._FOUND` is set to 1 when the skirmish-side scan matches this player's
#: `Side`; `..._MISSING` is set to 1 when the scan runs out. Both are written as bytes and only the
#: low byte of `..._FOUND` is ever read - it is pushed as `setPlayerType`'s `isSkirmish`, which is
#: tested `cmp byte`.
PLAYER_SKIRMISH_FOUND_EBP = -0x20
PLAYER_SKIRMISH_MISSING_EBP = -0x25

#: Hook 1: `cmp byte [ebp-0x25], al` / `jne 0x006B0A20` - the fork that sends a player with no
#: matching skirmish side to the type-0 (human, no AI) path.
PLAYER_SKIRMISH_ROUTE = 0x006B09F5
PLAYER_SKIRMISH_ROUTE_BYTES = bytes.fromhex("3845db7526")
PLAYER_SKIRMISH_ROUTE_RESUME = 0x006B09FA

#: Hook 2: `cmp byte [ebp-0x20], 0` / `je 0x006B102E` - the fork that decides whether to import
#: the matched side's script list and teams. `..._RESUME` is the matched path
#: (`findSkirmishSideByFaction` at `0x006ACFA3`); `..._SKIP` is the continuation for a player
#: with nothing to import from.
PLAYER_SKIRMISH_IMPORT = 0x006B0D4E
PLAYER_SKIRMISH_IMPORT_BYTES = bytes.fromhex("807de0000f84d6020000")
PLAYER_SKIRMISH_IMPORT_RESUME = 0x006B0D58
PLAYER_SKIRMISH_IMPORT_SKIP = 0x006B102E
PLAYER_SKIRMISH_IMPORT_SKIP_BYTES = bytes.fromhex("8b8e04030000")

#: `writeMiniDump(EXCEPTION_POINTERS *ep, BOOL fullDump)` - `cdecl`, two stack arguments, called
#: from the unhandled-exception filter at `0x0043D610`. It resolves `MiniDumpWriteDump` out of the
#: `dbghelp.dll` handle at `0x00DC62EC`, builds the file name, opens it, takes `SeDebugPrivilege`
#: and calls through. `docs/crash-dump-quality.md` derives the whole body.
WRITE_MINI_DUMP = 0x0043BE80
WRITE_MINI_DUMP_BYTES = bytes.fromhex("558bec81ec50010000a1ec62dc00")

#: `xor edi, edi` inside it, at the point the file name has been formatted. Every `push edi` from
#: here to the `MiniDumpWriteDump` call is therefore a literal `NULL`, which is what makes the two
#: at `MINI_DUMP_ARGS` the null user-stream and callback parameters rather than live values.
MINI_DUMP_NULL_EDI = 0x0043BF24
MINI_DUMP_NULL_EDI_BYTES = bytes.fromhex("33ff57576a02")

#: `writeMiniDump`'s frame slots. `..._FULL_DUMP_EBP` is the second argument, the `fulldump` debug
#: flag the engine reads off `Debug+0x9F56`; `..._EXCEPTION_INFO_EBP` is the
#: `MINIDUMP_EXCEPTION_INFORMATION` the function fills at `0x0043BF9D`..`0x0043BFB7`.
MINI_DUMP_FULL_DUMP_EBP = 0x0C
MINI_DUMP_EXCEPTION_INFO_EBP = -0x10

#: The eighteen bytes that push `MiniDumpWriteDump`'s last four arguments: `CallbackParam` and
#: `UserStreamParam` (both `push edi`, both `NULL`), `ExceptionParam`, and the dump type - which
#: the stock code derives as `1` or `2` from the `fulldump` flag and nothing else. `..._RESUME` is
#: the `push esi` that follows with the file handle, the first byte the window does not cover.
MINI_DUMP_ARGS = 0x0043C001
MINI_DUMP_ARGS_BYTES = bytes.fromhex("8a550c33c984d20f95c157578d45f0504151")
MINI_DUMP_ARGS_RESUME = 0x0043C013
MINI_DUMP_ARGS_RESUME_BYTES = bytes.fromhex("56ff154401bd00")

#: The engine's own "Game crash" exception code, raised at `DEBUG_CRASH_RAISE` and recognised by
#: the unhandled-exception filter at `0x0043D673`. Four of the six dumps found in the install root
#: carry it, which is why its (stock, empty) parameter block is worth filling.
DEBUG_CRASH_EXCEPTION_CODE = 0x04560123

#: `Debug::crash(int mode)` - `__thiscall` on the `Debug` singleton (`0x00DC62C0`), the function
#: that formats the crash text, shows the message box and raises. Its three frame slots below are
#: everything the exception record is missing.
#:
#: `..._MESSAGE_EBP` is the formatted crash text: allocated at `0x0043A91E` and filled with the
#: current error record's expression, file and line followed by `..._TAG_EBP`'s literal. It is a
#: heap pointer, so it is readable offline only in a dump that carries the heap.
#: `..._TAG_EBP` is one of two `.rdata` literals chosen at `DEBUG_CRASH_TAG_STORE` by `mode`, and
#: `..._MODE_EBP` is `mode` itself - 1 for an assertion, anything else for an error.
DEBUG_CRASH_MESSAGE_EBP = -0x04
DEBUG_CRASH_TAG_EBP = -0x08
DEBUG_CRASH_MODE_EBP = 0x08

#: `mov dword [ebp-8], 0x00BD4BAC` - the assertion arm of the tag choice, which is what pins
#: `DEBUG_CRASH_TAG_EBP` to a slot holding a pointer rather than a count.
DEBUG_CRASH_TAG_STORE = 0x0043A89B
DEBUG_CRASH_TAG_STORE_BYTES = bytes.fromhex("c745f8ac4bbd00")

#: `mov ecx, [ebp-4]` - the engine's own read of the message pointer, feeding the `MessageBoxA`
#: five instructions later. It sits on the only path that reaches the raise, so asserting it is
#: what says `DEBUG_CRASH_MESSAGE_EBP` is live there.
DEBUG_CRASH_MESSAGE_READ = 0x0043AC2A
DEBUG_CRASH_MESSAGE_READ_BYTES = bytes.fromhex("8b4dfc6810100100")

#: `push edi ; push edi ; push edi ; push 0x04560123` - `RaiseException`'s four arguments, in
#: which `lpArguments` and `nNumberOfArguments` are both zero, so the exception record reaches the
#: dump with an empty `ExceptionInformation[]`. `..._RESUME` is the `call RaiseException` itself,
#: the first byte the window does not cover.
DEBUG_CRASH_RAISE = 0x0043AC57
DEBUG_CRASH_RAISE_BYTES = bytes.fromhex("5757576823015604")
DEBUG_CRASH_RAISE_RESUME = 0x0043AC5F
DEBUG_CRASH_RAISE_RESUME_BYTES = bytes.fromhex("ff15d801bd00")
