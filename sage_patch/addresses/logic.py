"""Game logic and session plumbing: the main loop, game info, messages, CRC, recording."""

from __future__ import annotations

__all__ = [
    "APPEND_MESSAGE_VTABLE_SLOT",
    "ARG_APPENDERS",
    "BUILD",
    "CATCHUP_ESCAPE",
    "CATCHUP_ESCAPE_ALWAYS_RUNS",
    "CLEAR_GAME_DATA",
    "CRC_EXCLUDE_SHROUD_FLAG",
    "CRC_LITE_FLAG",
    "DESYNC_DECLARE",
    "DESYNC_DECLARED_OFFSET",
    "DESYNC_DEEP_CRC_FLAG",
    "DESYNC_FILE_WRITER",
    "DESYNC_FOCUS_FRAME",
    "DESYNC_FOCUS_FRAME_FILTER_FLAG",
    "DESYNC_FOCUS_FRAME_GATE",
    "DESYNC_FOCUS_FRAME_UNSET",
    "DESYNC_VERIFY_CLIENT_CRC_FLAG",
    "GAME_CLIENT_DRAW",
    "GAME_CLIENT_DRAW_BYTES",
    "GAME_DATA_ASCIISTRING_PARSER",
    "GAME_DATA_BOOL_PARSER",
    "GAME_DATA_SHELL_MAP_NAME_ROW",
    "GAME_ENGINE",
    "GAME_ENGINE_ALPHA",
    "GAME_ENGINE_INIT",
    "GAME_ENGINE_INIT_GLOBAL_DATA_CALL",
    "GAME_ENGINE_INIT_GLOBAL_DATA_CALL_BYTES",
    "GAME_ENGINE_INIT_MOD_CALL",
    "GAME_ENGINE_INIT_MOD_CALL_BYTES",
    "GAME_ENGINE_MAX_FPS",
    "GAME_ENGINE_QUITTING",
    "GAME_ENGINE_SET_FPS_SLOT",
    "GAME_ENGINE_SUB_FRAME",
    "GAME_ENGINE_SUB_FRAME_RATIO",
    "GAME_INFO_COMMAND_POINT_FACTOR",
    "GAME_INFO_GAME_TYPE",
    "GAME_INFO_GET_SLOT",
    "GAME_INFO_GSID",
    "GAME_INFO_MAP",
    "GAME_INFO_MAP_CONTENTS_MASK",
    "GAME_INFO_MAP_CRC",
    "GAME_INFO_MAP_SIZE",
    "GAME_INFO_OPTIONS",
    "GAME_INFO_PARSE",
    "GAME_INFO_PARSE_ENTRY",
    "GAME_INFO_PARSE_KEYS",
    "GAME_INFO_PARSE_KEYS_BYTES",
    "GAME_INFO_RULES",
    "GAME_INFO_RULES_COUNT",
    "GAME_INFO_SEED",
    "GAME_INFO_SET_MAP",
    "GAME_INFO_SET_MAP_CRC",
    "GAME_INFO_SET_MAP_SIZE",
    "GAME_INFO_SI",
    "GAME_INFO_SIZE",
    "GAME_INFO_SLOT_ARRAY",
    "GAME_INFO_SLOT_COUNT",
    "GAME_INFO_SLOT_DATA",
    "GAME_INFO_STARTING_RESOURCES",
    "GAME_LOGIC_BUILD_WORLD",
    "GAME_LOGIC_CREATE_OBJECT",
    "GAME_LOGIC_FIND_OBJECT_BY_ID",
    "GAME_LOGIC_FIND_OBJECT_BY_ID_ENTRY",
    "GAME_LOGIC_FRAME",
    "GAME_LOGIC_GAME_MODE",
    "GAME_LOGIC_IS_IN_GAME",
    "GAME_LOGIC_LIVING_WORLD_TYPE",
    "GAME_LOGIC_LIVING_WORLD_TYPE_MP_BATTLE",
    "GAME_LOGIC_LOAD_MAP",
    "GAME_LOGIC_OBJECT_BUCKETS_BEGIN",
    "GAME_LOGIC_OBJECT_BUCKETS_END",
    "GAME_LOGIC_OBJECT_HASH_WALK",
    "GAME_LOGIC_OBJECT_HASH_WALK_BYTES",
    "GAME_LOGIC_RANDOM_VALUE",
    "GAME_LOGIC_SOURCE_FILE",
    "GAME_LOGIC_START_NEW_GAME",
    "GAME_LOGIC_UPDATE",
    "GAME_LOGIC_UPDATE_ENTRY",
    "GAME_LOGIC_UPDATE_VTABLE_SLOT",
    "GAME_MAIN",
    "GAME_MAIN_ARGC",
    "GAME_MAIN_ARGV",
    "GAME_MAIN_BYTES",
    "GAME_MESSAGE_APPEND_INTEGER",
    "GAME_MODE_SKIRMISH",
    "GAME_RULES_COMBOS_MP",
    "GAME_RULES_COMMAND_POINT_FACTOR",
    "GAME_RULES_COMMAND_POINT_FACTOR_BYTES",
    "GAME_RULES_COMMAND_POINT_FACTOR_COUNT",
    "GAME_RULES_COMMAND_POINT_FACTOR_OPTIONS",
    "GAME_RULES_COMMAND_POINT_FACTOR_OPTIONS_BYTES",
    "GAME_RULES_POPULATE",
    "GAME_SLOT_ACCEPTED",
    "GAME_SLOT_COLOR",
    "GAME_SLOT_IS_OCCUPIED",
    "GAME_SLOT_LIVING_WORLD_PLAYER_ID",
    "GAME_SLOT_MAP_PLAYER",
    "GAME_SLOT_NAME",
    "GAME_SLOT_OBSERVER_TEMPLATE",
    "GAME_SLOT_ORIGINAL_COLOR",
    "GAME_SLOT_ORIGINAL_PLAYER_TEMPLATE",
    "GAME_SLOT_ORIGINAL_START_POS",
    "GAME_SLOT_PLAYER_TEMPLATE",
    "GAME_SLOT_SET_IS_OCCUPIED",
    "GAME_SLOT_SET_PLAYER_TEMPLATE",
    "GAME_SLOT_SIZE",
    "GAME_SLOT_START_POS",
    "GAME_SLOT_START_POS_GRANTED",
    "GAME_SLOT_STATE",
    "GAME_SLOT_STATE_BRUTAL_AI",
    "GAME_SLOT_STATE_CLOSED",
    "GAME_SLOT_STATE_EASY_AI",
    "GAME_SLOT_STATE_HARD_AI",
    "GAME_SLOT_STATE_LOCAL_HUMAN",
    "GAME_SLOT_STATE_MEDIUM_AI",
    "GAME_SLOT_STATE_OPEN",
    "GAME_SLOT_TEAM",
    "GAME_SLOT_TEMPLATE_BOUNDS",
    "GAME_START_RANDOM_ASSIGN",
    "GAME_START_RANDOM_ASSIGN_BYTES",
    "GAME_START_RANDOM_ASSIGN_RESUME",
    "GAME_START_RANDOM_CANDIDATES_EBP",
    "GAME_START_RANDOM_DRAW",
    "GAME_START_RANDOM_DRAW_BYTES",
    "GAME_START_RANDOM_DRAW_RESUME",
    "GAME_START_RANDOM_POOL",
    "GAME_START_RANDOM_POOL_BYTES",
    "GAME_START_RANDOM_POOL_INDEX_EBP",
    "GAME_START_RANDOM_POOL_RESUME",
    "GAME_START_RANDOM_POOL_SKIP",
    "GAME_START_RANDOM_SLOT_EBP",
    "GAME_START_SLOT_TEMPLATE",
    "GAME_START_SLOT_TEMPLATE_BYTES",
    "GAME_START_SLOT_TEMPLATE_RESUME",
    "GAME_STATE_REGISTER_SNAPSHOT",
    "GAME_TEXT_FORMAT_SLOT",
    "IMAGE_BASE",
    "IS_MULTIPLAYER_GAME",
    "IS_MULTIPLAYER_OR_ITS_REPLAY",
    "IS_MULTIPLAYER_OR_ITS_REPLAY_BYTES",
    "IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY",
    "IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY_BYTES",
    "KEY_PLAYER_AI_TYPE",
    "KEY_PLAYER_AI_TYPE_BYTES",
    "LAN_FACTION_READ_AI",
    "LAN_FACTION_READ_AI_BYTES",
    "LAN_FACTION_READ_HUMAN",
    "LAN_FACTION_READ_HUMAN_BYTES",
    "LAN_FACTION_READ_NEXT_AI",
    "LAN_FACTION_READ_NEXT_AI_BYTES",
    "LAN_FACTION_READ_NEXT_HUMAN",
    "LAN_FACTION_READ_NEXT_HUMAN_BYTES",
    "LAN_FACTION_WRITE_AI",
    "LAN_FACTION_WRITE_AI_BYTES",
    "LAN_FACTION_WRITE_HUMAN",
    "LAN_FACTION_WRITE_HUMAN_BYTES",
    "LAN_GAME_INFO_PACK",
    "LAN_GAME_INFO_PARSE",
    "LAN_PACK_NIBBLES",
    "LAN_PACK_NIBBLES_BYTES",
    "LAN_PARSE_CURSOR_EBP",
    "LAN_PARSE_END_EBP",
    "LAN_UNPACK_NIBBLES",
    "LAN_UNPACK_NIBBLES_BYTES",
    "LAN_WRITE_BYTE",
    "LAN_WRITE_BYTE_BYTES",
    "LOADING_SCREEN_PROGRESS",
    "LOADING_SCREEN_PROGRESS_BYTES",
    "LOADING_SCREEN_PROGRESS_REPORT",
    "LOADING_SCREEN_PROGRESS_RESUME",
    "LOADING_SCREEN_PROGRESS_SINK",
    "LOADING_SCREEN_PROGRESS_WINDOW",
    "LOGIC_CRC_EMIT",
    "LOGIC_CRC_EMIT_BYTES",
    "LOGIC_CRC_EMIT_RESUME",
    "LOGIC_CRC_SHROUD_XFER",
    "LOGIC_CRC_SHROUD_XFER_BYTES",
    "LOGIC_FRAMES_PER_SECOND",
    "MAP_CACHE_ASSIGN_CALL",
    "MAP_CACHE_ASSIGN_CALL_BYTES",
    "MAP_CACHE_FIELD_TABLE",
    "MAP_CACHE_FIELD_TABLE_GETTER_REF",
    "MAP_CACHE_FIELD_TABLE_PARSE_REF",
    "MAP_CACHE_PARSE_FIELDS",
    "MAP_CACHE_PARSE_FIELDS_BYTES",
    "MAP_CACHE_STOCK_FIELDS",
    "MAP_META_DATA_ASSIGN",
    "MAP_META_DATA_IS_OFFICIAL",
    "MAP_META_DATA_SORT_KEY",
    "MAP_PATH_FORMAT",
    "MAP_PREVIEW_OBSERVER_SKIPS",
    "MAX_PLAYER_COUNT",
    "MSG_CLEAR_GAME_DATA",
    "MSG_NEW_GAME",
    "NETWORK_GAME_MODES",
    "NET_CRC_INTERVAL",
    "NET_CRC_INTERVAL_GAME_INFO_CTOR",
    "NET_CRC_INTERVAL_GAME_INFO_OFFSET",
    "NET_CRC_INTERVAL_HEARTBEAT_GATE",
    "NET_CRC_INTERVAL_REPLAY_HEADER",
    "NET_CRC_INTERVAL_SKIRMISH_CLAMP",
    "NET_CRC_INTERVAL_STOCK",
    "OBJECT_HASH_ENTRY_NEXT",
    "OBJECT_HASH_ENTRY_OBJECT",
    "PLAYBACK_INSTALLS_OBSERVER",
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
    "SIDES_INFO_DICT",
    "SIDES_INFO_SCRIPT_LIST",
    "SIDES_INFO_STRIDE",
    "SIDES_LIST_GET_SIDE_INFO",
    "SIDES_LIST_GET_SIDE_INFO_BYTES",
    "SIDES_LIST_LOAD_AI_LIBRARY_FOR_SIDE",
    "SIDES_LIST_LOAD_AI_LIBRARY_FOR_SIDE_BYTES",
    "SIDES_LIST_SIDES",
    "SIDES_LIST_SIDE_COUNT",
    "START_RECORDING",
    "START_RECORDING_MODE_ARG",
    "STD_MAP_INT_FIND",
    "STD_MAP_ITERATOR_INCREMENT",
    "STD_MAP_NODE_VALUE",
    "TERRAIN_LOGIC_GET_GROUND_HEIGHT_SLOT",
    "TERRAIN_LOGIC_MAP_PATH",
    "THE_BUILD_ASSISTANT",
    "THE_COMMAND_SET_STORE",
    "THE_GAME_INFO",
    "THE_GAME_LOGIC",
    "THE_GAME_STATE",
    "THE_MESSAGE_STREAM",
    "THE_NAME_KEY_GENERATOR",
    "THE_RECORDER",
    "THE_SIDES_LIST",
    "THE_SIDES_LIST_LOAD",
    "THE_SIDES_LIST_LOAD_BYTES",
    "THE_SKIRMISH_GAME_INFO",
    "THE_TERRAIN_LOGIC",
    "THE_VICTORY_CONDITIONS",
]

BUILD = "RotWK 2.01.2614.37001"
IMAGE_BASE = 0x00400000
# The `MSG_LOGIC_CRC` emitter in `GameLogic::update`, per `docs/message-stream.md` section 1. Two
# paths compute the frame CRC into `edi` (`0x0062E7CE` and `0x0062E7F4`) and both converge here,
# so a hook at this join sees the value on every route to it. `0x0062E7E2` jumps to exactly this
# address and nothing in the function targets the five bytes after it, so the six displaced bytes
# can be taken whole.
LOGIC_CRC_EMIT = 0x0062E7FD
LOGIC_CRC_EMIT_BYTES = bytes.fromhex("8b0d9863de00")  # mov ecx, [TheMessageStream]
LOGIC_CRC_EMIT_RESUME = 0x0062E803
# `mov eax, [TheShroudManager]` in the CRC producer (`0x00625886`): fog of war is already in the
# sync hash, so `binary-attest` only has to cover clients whose code, not state, differs.
LOGIC_CRC_SHROUD_XFER = 0x00625983
LOGIC_CRC_SHROUD_XFER_BYTES = bytes.fromhex("a15843de00")
CRC_EXCLUDE_SHROUD_FLAG = 0x00DE87BF
# `GameLogic`'s out-of-sync declaration and the byte it latches (0 until declared at `0x00629106`,
# never cleared) - what an observer polls. See `docs/desync-detection.md`.
DESYNC_DECLARE = 0x006290C7
DESYNC_DECLARED_OFFSET = 0x1BC
# The per-frame CRC self-check that writes `CLIENT_DESYNC_<name>.txt`. Unreachable on a retail
# build: its gate's only writer is an orphaned command-line handler (`docs/headless.md` section 5).
DESYNC_FILE_WRITER = 0x006CF681
DESYNC_VERIFY_CLIENT_CRC_FLAG = 0x00DE87C5
# `NetCRCInterval`, the `MSG_LOGIC_CRC` heartbeat cadence: 100 on retail, since only an orphaned
# handler writes it. Three sites read it, so changing the initialiser is enough. See
# `docs/desync-debug.md`.
NET_CRC_INTERVAL = 0x00DA1880
NET_CRC_INTERVAL_STOCK = 100
# `mov eax, [TheGameInfo]` / `mov ecx, [eax+0xC]` / `div ecx` in `GameLogic::update`: the frame is
# divided by the interval and the heartbeat goes out on a zero remainder. **There is no zero
# guard** - an interval of 0 faults on the logic thread on the first frame - which is the reason
# `desync-debug` refuses one.
NET_CRC_INTERVAL_HEARTBEAT_GATE = 0x0062E714
# Where `GameInfo::+0xC` (the per-match copy the gate above divides by) comes from: the constructor
# at `0x00801AE1`, unclamped, and the skirmish re-seed at `0x0077ED5D`, which clamps to at most
# 100. Both read `NET_CRC_INTERVAL`.
NET_CRC_INTERVAL_GAME_INFO_CTOR = 0x00801AE1
NET_CRC_INTERVAL_GAME_INFO_OFFSET = 0x0C
NET_CRC_INTERVAL_SKIRMISH_CLAMP = 0x0077ED5D
# `mov ecx, [NetCRCInterval]` in the recorder's header writer, stored to `recorder+0xEC0` - the
# `crc_interval` field of a `.rep`. A recording made by a patched build carries the patched
# cadence here, which is how `sage_replay` sees it.
NET_CRC_INTERVAL_REPLAY_HEADER = 0x0077D260
# The desync focus frame: -1 when unset, else a heartbeat on every frame of the window ending on it.
# See `docs/desync-debug.md` section 3.
DESYNC_FOCUS_FRAME = 0x00DA62EC
DESYNC_FOCUS_FRAME_UNSET = 0xFFFFFFFF
DESYNC_FOCUS_FRAME_GATE = 0x0062E736
# The declaration filter. When set, `DESYNC_DECLARE` reports a desync **only** if it happens on
# exactly `DESYNC_FOCUS_FRAME` - a filter, not a trigger. Left at 0 the message box and the latch
# behave normally, which is what a focus frame used only to steer the heartbeat wants.
DESYNC_FOCUS_FRAME_FILTER_FLAG = 0x00DE87CA
# `-deepCRC`: a second route through the emitter (`0x0062E774`) that logs the CRC's constituents
# into a named sink. **The sink is a growable heap buffer, not a file** - written by `0x00A15F27`,
# opened against the `Debug` named-channel registry at `[0x00DF1F40]` that no shipping config
# drains - so enabling this buys a per-frame allocation and no log. Recorded so the next reader
# does not re-derive that; see `docs/desync-debug.md` section 4.
DESYNC_DEEP_CRC_FLAG = 0x00DE87C6
# `-liteCRC`: while it is set (the plain emitter sets it per call) the nine `-x<Subsystem>CRC`
# exclusions are ignored, which is why they are inert on retail. See `docs/desync-debug.md` section
# 5.
CRC_LITE_FLAG = 0x00DE87C7
# Subsystem singletons. Each address holds a *pointer to* the object, not the object; they are
# registered by name at startup, which is how they were found (see `docs/engine-globals.md`
# for the full 88).
THE_GAME_LOGIC = 0x00DE412C
THE_MESSAGE_STREAM = 0x00DE6398
THE_NAME_KEY_GENERATOR = 0x00DD90E4
THE_COMMAND_SET_STORE = 0x00DE7744
THE_GAME_STATE = 0x00DE4AD4
THE_RECORDER = 0x00DE7CD8
THE_BUILD_ASSISTANT = 0x00DE8200
THE_VICTORY_CONDITIONS = 0x00DE89AC
# The lobby description of the running game (`TheGameInfo`, whichever flavour is live) and the
# skirmish menu's own, which the skirmish screen also assigns to the first (`0x006309BF`).
THE_GAME_INFO = 0x00DE892C
THE_SKIRMISH_GAME_INFO = 0x00DE8930
# `GameInfo::m_map`, an `AsciiString` holding the map path as it appears in the metadata `M=`
# field (`maps/map mp westfold`). `getMap` (`0x00627692`) is a plain copy of it, and `setMap`
# (`0x00801C46`) writes it, so a cave can read the member instead of constructing a copy it
# would then have to destroy. An `AsciiString` is one pointer; the characters begin at `+8`,
# and a null pointer is the empty string.
GAME_INFO_MAP = 0x40
# `GameInfo`'s remaining layout and `GameSlot`, recovered in `docs/game-info.md`. The slot array
# is eight pointers into the object's own tail (`0xDC + i * 0x1B8`, which runs exactly to the end
# of the object), and the options block is what the skirmish menu fills and what a `-file`
# auto-start leaves at -1 - including the starting resources, whose unset value leaves every
# player one short of a fortress.
GAME_INFO_SIZE = 0xE9C
GAME_INFO_SLOT_ARRAY = 0x18
GAME_INFO_SLOT_COUNT = 8
GAME_INFO_SLOT_DATA = 0xDC
GAME_INFO_MAP_CRC = 0x44
GAME_INFO_MAP_SIZE = 0x48
GAME_INFO_OPTIONS = 0x5C
GAME_INFO_STARTING_RESOURCES = 0x70
# The header fields `ParseAsciiStringToGameInfo` commits, named by the key each is parsed from
# (`docs/game-info.md` §7). `GAME_TYPE` (`GT`) is the first dword of what §4 calls the options
# block - its setter re-seeds the rules from it - and `RULES` (`GR`) is the ten dwords after it,
# copied in with one `memcpy`, so `GAME_INFO_STARTING_RESOURCES` is rule 4. `MAP_CONTENTS_MASK`
# is the hex prefix of `M=`, and `SI`'s meaning is unknown: -1 in every replay.
GAME_INFO_MAP_CONTENTS_MASK = 0x4C
GAME_INFO_SEED = 0x50
GAME_INFO_SI = 0x58
GAME_INFO_GAME_TYPE = 0x5C
GAME_INFO_RULES = 0x60
GAME_INFO_RULES_COUNT = 10
#: Rule 3, the lobby's `RULE:CommandPointFactor` (default 100): a percentage the command-point
#: hard cap is scaled by in `COMMAND_POINTS_INIT_FACTOR`, and nothing else in the simulation reads
#: it. Edain relabels its seven values as game modes. See `docs/command-point-override.md`.
GAME_INFO_COMMAND_POINT_FACTOR = 0x6C
GAME_INFO_GSID = 0x88
#: The lobby's rule-combo tables, read by `AptMpGameRules`. `0x00960A10(ruleSet)` answers a
#: NULL-padded array of descriptors - `GAME_RULES_COMBOS_MP` for rule set 0 (skirmish, LAN, online),
#: whose length `0x00960A46` hard-codes as 2. A descriptor is `{Int rule, {const char *label, Int
#: value} *options, Int count, Int defaultIndex}`. The combo is built from it at
#: `GAME_RULES_POPULATE` (label, value as item data), and a value maps back to a selection by
#: matching item data, so the option list is the only place the choices exist.
GAME_RULES_COMBOS_MP = 0x00DB77BC
GAME_RULES_COMMAND_POINT_FACTOR = 0x00C82578
GAME_RULES_COMMAND_POINT_FACTOR_BYTES = bytes.fromhex(
    "03000000"  # rule 3
    "4025c800"  # options -> GAME_RULES_COMMAND_POINT_FACTOR_OPTIONS
    "07000000"  # count
    "02000000"  # default index (100)
)
GAME_RULES_COMMAND_POINT_FACTOR_OPTIONS = 0x00C82540
#: The seven `{label, value}` pairs: ThirdX 33, HalfX 50, 1X 100, 2X 200, 4X 400, 8X 800, 100X
#: 10000. A label is a string-table key, fetched with the value as its format argument, and the
#: default entry gets `VALUE:Default` appended.
GAME_RULES_COMMAND_POINT_FACTOR_OPTIONS_BYTES = bytes.fromhex(
    "5828c80021000000"
    "4c28c80032000000"
    "4028c80064000000"
    "3428c800c8000000"
    "2828c80090010000"
    "1c28c80020030000"
    "1028c80010270000"
)
GAME_RULES_COMMAND_POINT_FACTOR_COUNT = 7
GAME_RULES_POPULATE = 0x00986B1C
# `ParseAsciiStringToGameInfo(GameInfo *, AsciiString, bool keepNames)`, cdecl; the string is passed
# by value and destroyed by the callee. Nothing is committed unless the whole string parses.
GAME_INFO_PARSE = 0x00802DBA
GAME_INFO_PARSE_ENTRY = bytes.fromhex("b8ca90b900")
#: The parser's key strings, in the order they sit in `.rdata` - which is also how a build whose
#: parser moved is refused, since nothing else references this run.
GAME_INFO_PARSE_KEYS = 0x00C4E73C
GAME_INFO_PARSE_KEYS_BYTES = (
    b"SI\x00\x00GT\x00\x00GSID\x00\x00\x00\x00GR\x00\x00SD\x00\x00MS\x00\x00%X\x00\x00MC\x00\x00"
)
# The three map setters, each `__thiscall` with one stack argument and `ret 4`; `setMap`'s is an
# `AsciiString` by value, which it destroys. `setMapCRC` and `setMapSize` store the value and then
# consult `TheMapCache`, so a cave restoring them calls the setter rather than writing the field.
GAME_INFO_SET_MAP = 0x00801C46
GAME_INFO_SET_MAP_CRC = 0x0080298E
GAME_INFO_SET_MAP_SIZE = 0x00802A49
# `GameSlot`, `0x1B8` bytes. The three `ORIGINAL_` fields mirror their counterparts - the lobby's
# requested-versus-granted pair - and every sample taken has them equal. `MAP_PLAYER` is an
# `AsciiString` reading `Player_<START_POS + 1>`: it binds a seat to the map-side player that owns
# the pre-placed objects at that start position, and it follows the start position rather than the
# slot index.
GAME_SLOT_SIZE = 0x1B8
GAME_SLOT_STATE = 0x04
GAME_SLOT_ACCEPTED = 0x08
GAME_SLOT_COLOR = 0x0C
GAME_SLOT_START_POS = 0x10
GAME_SLOT_START_POS_GRANTED = 0x14
GAME_SLOT_PLAYER_TEMPLATE = 0x18
GAME_SLOT_TEAM = 0x1C
GAME_SLOT_ORIGINAL_COLOR = 0x24
GAME_SLOT_ORIGINAL_START_POS = 0x28
GAME_SLOT_ORIGINAL_PLAYER_TEMPLATE = 0x2C
GAME_SLOT_NAME = 0x30
GAME_SLOT_MAP_PLAYER = 0x34
# The `LivingWorldPlayer` id this seat plays in a War of the Ring session, in the unidentified
# span `docs/game-info.md` leaves at `+0x4C`-`+0x9F`. `GameLogic::buildSidesFromGameInfo`
# (`0x00627C82`) and the living-world message router (`0x006BE766`) both hand it to
# `LIVING_WORLD_FIND_PLAYER_BY_ID`, which is what identifies it. -1 in a game with no living
# world, where that lookup returns NULL immediately.
GAME_SLOT_LIVING_WORLD_PLAYER_ID = 0x4C
# `GameSlot::m_isOccupied` and its setter. A seat at 0 gets no side or player from
# `buildSidesFromGameInfo`; 1 is an ordinary value (`0x006277A4` sets all eight slots).
GAME_SLOT_IS_OCCUPIED = 0x1AC
GAME_SLOT_SET_IS_OCCUPIED = 0x00625171
# `GameSlot::m_playerTemplate` is negative for a seat that is not playing a faction, and
# `buildSidesFromGameInfo` keys the whole observer path off that sign: the side is named
# `Observer_%d` (`0x00627C74`) and built with `FactionObserver` (`0x00627E25`) rather than an
# indexed `PlayerTemplate`. -2 specifically is what `GameLogic::startNewGame` tests at
# `0x0062FE9C` before granting full-map vision.
GAME_SLOT_OBSERVER_TEMPLATE = -2
# `GameInfo::getSlot(i)` - `__thiscall`, one stack argument, `ret 4`. Bounds-checked to
# 0..`GAME_INFO_SLOT_COUNT`-1 and returns NULL outside it, so a cave can walk the array without
# its own guard.
GAME_INFO_GET_SLOT = 0x00800B55
# The LAN lobby's binary `GameInfo` - the payload of `MSG_GAME_OPTIONS_PACKED` (type 0x13, the
# host's broadcast, sent at `0x0084C4D8`) and of the game announce (type 1, `0x00989E20`). Both
# are written by `LAN_GAME_INFO_PACK(GameInfo*, buf, 0x186)` and read back by
# `LAN_GAME_INFO_PARSE`. Each seat's colour and template share one byte, through
# `LAN_PACK_NIBBLES` - `((a - c) << 4) - d + b`, called as `(colour, template, -1, -2)` - and
# `LAN_UNPACK_NIBBLES(byte, -1, -2, &colour, &template)`, both cdecl. So the wire holds 16
# templates, -2..13, and a larger index carries into the colour nibble. Derived in
# `docs/lobby-faction-byte.md`.
LAN_GAME_INFO_PACK = 0x0084A976
LAN_GAME_INFO_PARSE = 0x0084B0EC
LAN_PACK_NIBBLES = 0x009738A5
LAN_PACK_NIBBLES_BYTES = bytes.fromhex("8a4424042a44240cc0e0042a44241002442408c3")
LAN_UNPACK_NIBBLES = 0x009738B9
LAN_UNPACK_NIBBLES_BYTES = bytes.fromhex(
    "558bec8a45088b4d148ad0c0ea0488118b5518240f88028a450c00018a451000025dc3"
)
#: The packer's one-byte writer, `(cursor, byte, end) -> cursor`, cdecl: it appends the low byte
#: of its second argument when it fits before `end` and returns the cursor unchanged when not.
LAN_WRITE_BYTE = 0x0084A537
LAN_WRITE_BYTE_BYTES = bytes.fromhex("ff74240c8d44240c6a0150ff742410e86affffff83c410c3")
#: The packer's two seat arms, human then AI, each from `mov ecx, [esi+0xc]` (the colour) to the
#: `call LAN_WRITE_BYTE` that writes the packed byte; that call is the last five bytes. The seat
#: is `esi` throughout and `edi` is the buffer end.
LAN_FACTION_WRITE_HUMAN = 0x0084AB40
LAN_FACTION_WRITE_HUMAN_BYTES = bytes.fromhex(
    "8b4e0c6afe89450c8b46186aff5051e8518d12008845dc57ff75dcff750ce8d4f9ffff"
)
LAN_FACTION_WRITE_AI = 0x0084ABEE
LAN_FACTION_WRITE_AI_BYTES = bytes.fromhex(
    "8b4e0c6afe89450c8b46186aff5051e8a38c12008845d457ff75d4ff750ce826f9ffff"
)
#: The parser's two seat arms, human then AI, each from the `mov ebx, eax` that takes the cursor
#: past the packed byte to the `call LAN_UNPACK_NIBBLES`, the last five bytes. `ebx` is the
#: cursor, `[ebp+LAN_PARSE_CURSOR_EBP]` its last checked value and `[ebp+LAN_PARSE_END_EBP]` the
#: end of the payload; the colour and template land in two signed bytes the code after the call
#: range-checks with `movsx`.
LAN_FACTION_READ_HUMAN = 0x0084B44A
LAN_FACTION_READ_HUMAN_BYTES = bytes.fromhex(
    "8bd883c40c3b5dec0f865d0500003b5df00f87540500008d45e6508d45e4506afe6affff7598895dece841841200"
)
LAN_FACTION_READ_AI = 0x0084B741
LAN_FACTION_READ_AI_BYTES = bytes.fromhex(
    "8bd883c40c3b5dec0f86660200003b5df00f875d0200008d45e5508d45e3506afe6affff759c895dece84a811200"
)
#: The next field each arm reads (the start position), from `ebx` and checked against the cursor
#: slot - which is why advancing both past a second byte is all the parser needs.
LAN_FACTION_READ_NEXT_HUMAN = 0x0084B4DB
LAN_FACTION_READ_NEXT_HUMAN_BYTES = bytes.fromhex("ff75f08d45e85053e858f1ffff")
LAN_FACTION_READ_NEXT_AI = 0x0084B7D2
LAN_FACTION_READ_NEXT_AI_BYTES = bytes.fromhex("ff75f08d45cc5053e861eeffff")
LAN_PARSE_CURSOR_EBP = -0x14
LAN_PARSE_END_EBP = -0x10
#: `GameLogic::startNewGame`'s Random-faction pool: a loop over every template index that
#: collects the playable ones (`cmp byte [esi+0x151], 0` / `je <next>`, index in `[ebp-0x10]`),
#: which each Random slot then draws from after its start position's restrictions filter it.
#: `..._RESUME` is the push onto the pool, `..._SKIP` the loop's next-index edge.
GAME_START_RANDOM_POOL = 0x0062D4D4
GAME_START_RANDOM_POOL_BYTES = bytes.fromhex("80be5101000000740c")
GAME_START_RANDOM_POOL_RESUME = 0x0062D4DD
GAME_START_RANDOM_POOL_SKIP = 0x0062D4E9
GAME_START_RANDOM_POOL_INDEX_EBP = -0x10
#: Where `startNewGame` gives a Random slot the template it drew - `push esi` / `mov ecx, ebx` /
#: `call GameSlot::setPlayerTemplate` - with the slot in `ebx` and the template in `esi`, which
#: the code after it keeps using. The slot's own template is still the Random sentinel here.
GAME_START_RANDOM_ASSIGN = 0x0062D71C
GAME_START_RANDOM_ASSIGN_BYTES = bytes.fromhex("568bcbe836551d00")
GAME_START_RANDOM_ASSIGN_RESUME = 0x0062D724
#: Where `startNewGame` reads each occupied slot's template into `esi` - `mov esi, [ebx+0x18]` /
#: `jmp <the Random pass>` - with the slot in `ebx`. Anything still negative there but Observer is
#: drawn by the Random pass that follows.
GAME_START_SLOT_TEMPLATE = 0x0062D52C
GAME_START_SLOT_TEMPLATE_BYTES = bytes.fromhex("8b7318e906020000")
GAME_START_SLOT_TEMPLATE_RESUME = 0x0062D73A
#: The Random draw itself, once per Random slot: the slot's candidates are a copy of the pool,
#: `std::vector<Int>` at `[ebp-0x28]`/`[ebp-0x24]`, already filtered by its start position, and
#: the draw is `pool[GameLogicRandomValue(0, 1000) % size]`. `..._DRAW` is the `mov esi, end` /
#: `mov edi, begin` that opens it - reached from both filters' skips, so it is the last point
#: where the candidates are final - and the slot is `[ebp-0x1C]` throughout.
GAME_START_RANDOM_DRAW = 0x0062D6D8
GAME_START_RANDOM_DRAW_BYTES = bytes.fromhex("8b75dc8b7dd8")
GAME_START_RANDOM_DRAW_RESUME = 0x0062D6DE
GAME_START_RANDOM_CANDIDATES_EBP = -0x28
GAME_START_RANDOM_SLOT_EBP = -0x1C
#: `GameSlot::setPlayerTemplate(Int)`, `__thiscall`, `ret 4`.
GAME_SLOT_SET_PLAYER_TEMPLATE = 0x00802C5A
#: `GameLogicRandomValue(lo, hi, file, line)`, cdecl: the synchronised generator, `lo..hi`
#: inclusive. `file` is only read when the random log is on, but must be a real string; the draw
#: `startNewGame` makes passes `GAME_LOGIC_SOURCE_FILE`.
GAME_LOGIC_RANDOM_VALUE = 0x006D328E
GAME_LOGIC_SOURCE_FILE = 0x00BFD400
#: The lower bound on a slot's template, -2 (Observer), in each reader that takes one from outside
#: the screen: the lobby string parser (twice), the LAN host applying a client's request, and the
#: two LAN packet readers. A template below it is refused - the whole string, the request, the
#: packet.
GAME_SLOT_TEMPLATE_BOUNDS = (
    (0x0080351C, bytes.fromhex("83f8fe")),
    (0x0080385B, bytes.fromhex("83f8fe")),
    (0x0064A271, bytes.fromhex("83fffe")),
    (0x0084B4A6, bytes.fromhex("807de6fe")),
    (0x0084B79D, bytes.fromhex("807de5fe")),
)
#: The setup screen's map preview numbering its start positions: `cmp [slot+0x18], -2` then
#: `jle <skip>` - skipping observers by "-2 or below". The `jle` of each.
MAP_PREVIEW_OBSERVER_SKIPS = (0x007053E2, 0x0070545B)
# `GameSlot::m_state`. 1, 2 and 6 are the values observed; the display name at `GAME_SLOT_NAME`
# reads "Closed" and "Easy" against the first two, which is what names them. `GameSlot::isHuman`
# (`0x008009A7`) is exactly `m_state == 6`. The rest are read out of `GAME_INFO_PARSE`, which maps
# the slot letters straight onto them: `O` 0, `X` 1, `CE`/`CM`/`CH`/`CB` 2-5 and `H` 6.
GAME_SLOT_STATE_OPEN = 0
GAME_SLOT_STATE_CLOSED = 1
GAME_SLOT_STATE_EASY_AI = 2
GAME_SLOT_STATE_MEDIUM_AI = 3
GAME_SLOT_STATE_HARD_AI = 4
GAME_SLOT_STATE_BRUTAL_AI = 5
GAME_SLOT_STATE_LOCAL_HUMAN = 6
GAME_MESSAGE_APPEND_INTEGER = 0x007111E5
# The loading screen's progress update. `[this + 0x88]` is a window the shell creates, so a
# menu-less start dereferences null here; the engine treats the same member as nullable at
# `0x0081C5C4`, whose whole body clears it. The twenty-four bytes run to a resume point two
# nearby branches already target.
LOADING_SCREEN_PROGRESS = 0x0081C64A
LOADING_SCREEN_PROGRESS_BYTES = bytes.fromhex("8b8e880000008b0157ff50348b0d2c41de0050e82c9ee0ff")
LOADING_SCREEN_PROGRESS_RESUME = 0x0081C662
LOADING_SCREEN_PROGRESS_WINDOW = 0x88
LOADING_SCREEN_PROGRESS_SINK = 0x00DE412C
LOADING_SCREEN_PROGRESS_REPORT = 0x0062648E
# `MAX_PLAYER_COUNT`. Every per-player array the engine embeds is this wide; see
# `docs/max-player-count.md` for why it cannot be raised.
MAX_PLAYER_COUNT = 20
# The id-space stores (`TheUpgradeCenter`, `TheThingFactory`, `TheSpecialPowerStore`,
# `TheScienceStore`) are described in `docs/live-object-model.md` sections 3b and 3c.
# `TheTerrainLogic` and its `getGroundHeight(x, y, normal)` vtable slot: thiscall, returns in `st0`,
# callee cleans twelve bytes (read off `Object::getHeightAboveTerrain`, `0x0070BC6E`).
THE_TERRAIN_LOGIC = 0x00DE4690
TERRAIN_LOGIC_GET_GROUND_HEIGHT_SLOT = 0x18
# The loaded map's path, an `AsciiString` (`maps\<name>\<name>.map`). Found live in a `-file`
# match, where both `GameInfo` globals are still null: `TheGameState`, `TheRecorder` and the
# hot-key manager hold the same string, but this is the object the map was loaded into. Its
# writer is not traced statically.
TERRAIN_LOGIC_MAP_PATH = 0x4C
# `GameLogic::update`, the per-logic-frame callback. It is virtual and has no call xrefs, so a hook
# should assert that the vtable slot below still names it.
GAME_LOGIC_UPDATE = 0x0062E4E8
GAME_LOGIC_UPDATE_VTABLE_SLOT = 0x00BD85C4
GAME_LOGIC_UPDATE_ENTRY = bytes.fromhex("b8da41b800")  # mov eax, 0xB841DA - exactly 5 bytes
# `GameLogic::m_frame`, the logic-frame counter. It is what the recorder stamps every replay
# chunk with (`RecorderClass::writeToFile` reads it, not the message), so anything writing a
# chunk of its own has to use the same source to land on the same timecode.
GAME_LOGIC_FRAME = 0x40
GAME_TEXT_FORMAT_SLOT = 0x44
# `MSG_CLEAR_GAME_DATA`, which ends a recording. It has thirteen emitters, so hook its consumer (the
# recorder), not an emitter.
CLEAR_GAME_DATA = 0x00625E36
MSG_CLEAR_GAME_DATA = 0x1D
# `MSG_NEW_GAME` - the message that starts one. Its first integer argument is the game mode,
# and it is the only thing that ever starts a recording: `RecorderClass::updateRecord`'s
# `0x1E` branch is `startRecording`'s single caller.
MSG_NEW_GAME = 0x1E
# The `MSG_NEW_GAME` modes the stock recorder accepts: the two network modes. A skirmish is mode 2,
# which is why it is not recorded. See `docs/skirmish-replay.md`.
RECORDER_RECORDED_MODES = (1, 5)
GAME_MODE_SKIRMISH = 2
# `RecorderClass`: `m_mode` is 0 record / 1 playback / 2 none, and `m_file` the `FILE*` for both.
# `writeToFile` writes the chunk format `sage_replay.ReplayChunk` parses.
RECORDER_MODE = 0x1C
RECORDER_MODE_RECORD = 0
RECORDER_MODE_PLAYBACK = 1
RECORDER_FILE = 0x10
RECORDER_WRITE_TO_FILE = 0x0077D8FC
# `RecorderClass::m_gameMode`. Do not read it inside `startRecording`, whose `reset()` overwrites it
# with 9 first; read its mode argument instead (`START_RECORDING_MODE_ARG`).
RECORDER_GAME_MODE = 0xED4
RECORDER_GAME_MODE_RESET = 9
RECORDER_RESET_WRITES_GAME_MODE = 0x0077D7D2
# `RecorderClass::startRecording(arg1, gameMode, arg2, arg3)`: thiscall, `ret 0x10`, `ebp` frame.
# Its arguments go into the header's trailing block, so `[ebp+0x0C]` is the recorded mode.
START_RECORDING = 0x0077EA03
START_RECORDING_MODE_ARG = 0x0C
# `updateRecord`'s `MSG_NEW_GAME` branch, the engine's whole decision to record. The nine-byte
# whitelist tail at `..._MODE_GATE` is all that stands between a skirmish and a recording.
RECORDER_NEW_GAME_BRANCH = 0x0077F8D1
RECORDER_NEW_GAME_BRANCH_BYTES = bytes.fromhex(
    "83f81e0f859d000000558bcee8bc13f9ff8b0083f8040f84f000000083f807"
    "0f84e70000008b0d2c41de0083b914010000030f85d400000033db433bc37409"
)
RECORDER_MODE_GATE = 0x0077F910
RECORDER_MODE_GATE_BYTES = bytes.fromhex("83f8050f85c4000000")  # cmp eax,5 / jne 0x0077F9DD
RECORDER_MODE_GATE_ACCEPT = 0x0077F919  # fall through: start the recording
RECORDER_MODE_GATE_REJECT = 0x0077F9DD  # the function epilogue: record nothing
# `startRecording`'s call to the helper naming the file `Last Replay`, so each recording overwrites
# the last. The helper has a second caller: patch this call site, not the helper.
RECORDER_LAST_REPLAY_NAME = 0x0077DEFD
RECORDER_NAME_CALL = 0x0077EA45
RECORDER_NAME_CALL_BYTES = bytes.fromhex("e8b3f4ffff")  # call 0x0077DEFD
RECORDER_NAME_CALL_FINGERPRINT = bytes.fromhex("8d45ec50e8b3f4ffff5933db8d7e144350")
# `updateRecord`'s `MSG_CLEAR_GAME_DATA` branch, where every ending converges. Its `writeToFile`
# call (`0x0077F98B`) is the last point to append before the end marker, with the file open.
RECORDER_END_BRANCH = 0x0077F977
RECORDER_END_BRANCH_BYTES = bytes.fromhex("83f81d7525396f107416830d0c57da00ff568bcf")
RECORDER_END_WRITE_CALL = 0x0077F98B
RECORDER_END_WRITE_CALL_BYTES = bytes.fromhex("e86cdfffff")  # call 0x0077D8FC
RECORDER_STOP_RECORDING = 0x0077D8C8
# The branch's `stopRecording` call: after the end marker, before the file closes.
# `replay-annotations` hooks it because `replay-outcome` owns the `writeToFile` call.
RECORDER_END_STOP_CALL = 0x0077F992
RECORDER_END_STOP_CALL_BYTES = bytes.fromhex("e831dfffff")  # call 0x0077D8C8
RECORDER_END_STOP_SETUP = 0x0077F990
RECORDER_END_STOP_SETUP_BYTES = bytes.fromhex("8bcf")  # mov ecx, edi
# `TheGameLogic` predicates for "does the observer machinery apply": multiplayer; also a replay of
# one; also skirmish. See `docs/observer-switch.md`.
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
GAME_LOGIC_IS_IN_GAME = 0x00441B60
# Where playback makes the observer the local player: `cmp [TheGameLogic+0x110], 3` - the
# playback game mode - then `setLocalPlayer(findPlayerWithNameKey("ReplayObserver"))` and
# `ControlBar+0x218 = getNthPlayer(TheRecorder+0xECC)`, the recorded local player. Mode 3 is
# mode 3 whatever was recorded, which is why a skirmish replay already gets a working observer
# seat and only the bar above is missing.
PLAYBACK_INSTALLS_OBSERVER = 0x006283D1
RECORDER_LOCAL_PLAYER_INDEX = 0xECC
# `MessageStream::appendMessage(GameMessage::Type)` is virtual, at this vtable offset, and
# returns the new `GameMessage *`.
APPEND_MESSAGE_VTABLE_SLOT = 0x48
# The logic rate in frames per second - **5**, not the 30 four bytes above it at 0x00D9F60C,
# which is the client rate. Seconds become logic frames through this, read from the global rather
# than baked in.
LOGIC_FRAMES_PER_SECOND = 0x00D9F608
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
#: `TheGameEngine`'s vtable slot that takes a frame-rate cap - `0x0066F0FD`, `mov [ecx+0xC], eax`
#: / `ret 4`. Shell movies raise the cap while they play; `CreditsExit` restores it from
#: `GLOBAL_DATA + GLOBAL_DATA_FPS_LIMIT` on the way out, and so does this patch's exit arm.
#: `docs/render-rate.md` §2 derives the slot.
GAME_ENGINE_SET_FPS_SLOT = 0x48
GAME_CLIENT_DRAW = 0x00648861
GAME_CLIENT_DRAW_BYTES = bytes.fromhex("8b0d1844de008b01ff5030")
# `GameData`'s `Bool` and `AsciiString` field parsers. `LivingWorldCampaignOverrride`'s row names
# the `Bool` parser for an `AsciiString` field. See `docs/living-campaign/living-world-campaign.md`.
GAME_DATA_BOOL_PARSER = 0x0042E558
GAME_DATA_ASCIISTRING_PARSER = 0x0042EE5E
GAME_DATA_SHELL_MAP_NAME_ROW = 0x00C00500  # the anchor proving the AsciiString parser's address
#: `std::map<int, T>::find(const int *key)` - thiscall, `ret 4`. The key is at node `+0x10` and
#: the value at `+0x14`; a missing key returns the map's head node, whose value is all zeroes.
STD_MAP_INT_FIND = 0x006B4E57
# Who is fighting the battle the engine is loading a map for. Derived in
# `docs/living-campaign/mp-battle-participation.md`, which also carries the evidence for the two
# vector layouts below - both are read straight out of the accessors the engine ships,
# `0x007F6403` (member count) and `0x007F5D2B` (member at).

#: `TheGameLogic`'s living-world session type, distinct from `m_gameMode` at `+0x110`. 0 is the
#: strategic map, 1 a multiplayer battle, 2 a single-player one and 3 everything that is not a
#: living-world session at all - `0x0062602B` maps the first three onto a game mode and leaves 3
#: alone, and `0x00610A21` answers "in a living-world battle" for {1, 2}.
GAME_LOGIC_LIVING_WORLD_TYPE = 0x114
GAME_LOGIC_LIVING_WORLD_TYPE_MP_BATTLE = 1
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
#: The `StaticNameKey` for `playerAIType`, the side-dict key naming a `PlayerAIType` block. Its
#: bytes are the empty key plus the pointer to the literal at `0x00C1FB20`.
KEY_PLAYER_AI_TYPE = 0x00DA2FA4
KEY_PLAYER_AI_TYPE_BYTES = bytes.fromhex("0000000020fbc100")
# quiet-exit: suppress the shutdown-assert minidump.
# The engine's own "Game crash" assert (`DEBUG_CRASH_EXCEPTION_CODE`) fires during a normal
# shutdown; the unhandled-exception filter catches it and writes a minidump, so closing the game
# leaves a `.dmp` every time. `quiet-exit` gates the filter's dump call on `m_quitting`, so the
# artifact is written for a real in-game fault and not for a clean quit.

#: `TheGameEngine` - the singleton pointer variable, not the object. `[GAME_ENGINE]` is the
#: `GameEngine *` (`0x04b750d8` in a shutdown dump). Its `+0x10` byte is `m_quitting`, the flag the
#: main loop reads at `0x00639EC6` (`cmp byte [esi+0x10], bl`) to decide whether to keep running;
#: `docs/render-rate.md` §2 derives both. Set true by `GameEngine::setQuitting` (`0x0093D255`,
#: `mov byte [ecx+0x10], 1 ; ret`) when the app is asked to exit, and stays true through teardown.
GAME_ENGINE = 0x00DE4324
#: `m_quitting`'s offset on the `GameEngine`: a byte, nonzero once the process is on its way out.
GAME_ENGINE_QUITTING = 0x10
#: `m_maxFPS`, the frame cap the main loop paces itself to: `0x0063A19C` loads it (`fild dword
#: [esi+0xc]`) and spins each iteration out to `1000 / cap` ms, and nothing else sets the pace.
#: Its source is `GLOBAL_DATA + GLOBAL_DATA_FPS_LIMIT`, pushed in through `GAME_ENGINE_SET_FPS_SLOT`
#: at `0x00779DCF`. `docs/render-rate.md` §2 derives it.
GAME_ENGINE_MAX_FPS = 0x0C
#: `TheGameLogic::findObjectByID` - `__thiscall`, `ret 4`, NULL for an id nothing holds.
GAME_LOGIC_FIND_OBJECT_BY_ID = 0x00449681
GAME_LOGIC_FIND_OBJECT_BY_ID_ENTRY = bytes.fromhex("837c24040074148d")
# The sub-frame pacing block, derived in `docs/interpolation-alpha.md`. `GameEngine::update`
# advances a counter once per rendered frame and ends a logic frame when it passes the wrap, and
# the render path interpolates transforms across the gap with an alpha recomputed on every
# sub-frame. `docs/render-rate.md` §3 derives the surrounding loop.

#: `TheGameEngine+0x34` - the sub-frame counter, reset to 1 by the wrap at `0x0063264A`.
GAME_ENGINE_SUB_FRAME = 0x34
#: `TheGameEngine+0x38` - the alpha's denominator. The constructor (`0x0063A4DE`) leaves it at 1
#: and the recompute at `0x0063260F` sets it to `clientRate / logicRate`, so it is 1 until the
#: first logic frame ends.
GAME_ENGINE_SUB_FRAME_RATIO = 0x38
#: `TheGameEngine+0x3C` - the interpolation alpha, read by seven render sites.
GAME_ENGINE_ALPHA = 0x3C
#: The catch-up loop's escape (`docs/render-rate.md` §3.4). Stock derives `clientRate / logicRate`
#: here and skips the loop when it is 6 or more, which on a 30 fps client it always is. The Edain
#: and AotR binaries replace those seven bytes with `mov eax, 2` / `jmp 0x00632ABB`, so the loop
#: runs one iteration every logic frame and its `inc dword [ebp+0x34]` at `0x00632AC0` steps the
#: sub-frame counter past 1 before any client code can observe it.
CATCHUP_ESCAPE = 0x00632A9B
CATCHUP_ESCAPE_ALWAYS_RUNS = bytes.fromhex("b802000000eb19")
#: The `-mod` pipeline: `GAME_ENGINE_INIT` loads the subsystem legend and `GameData.ini` before
#: `-mod` is mounted. See `docs/mod-load-order.md`.
GAME_ENGINE_INIT = 0x0063AD4F
GAME_ENGINE_INIT_GLOBAL_DATA_CALL = 0x0063AFA4
GAME_ENGINE_INIT_GLOBAL_DATA_CALL_BYTES = bytes.fromhex("e85bb4ffff")
GAME_ENGINE_INIT_MOD_CALL = 0x0063AFB2
GAME_ENGINE_INIT_MOD_CALL_BYTES = bytes.fromhex("e88dfa1700")
#: `GameMain(argc, argv)`. From inside `init`, its arguments are at `[ebp+0x14]`/`[ebp+0x18]`;
#: `init`'s own `[ebp+8]`/`[ebp+0xC]` are reused as scratch.
GAME_MAIN = 0x006443B0
GAME_MAIN_BYTES = bytes.fromhex("e83ed9dbffff742408a32443de00ff7424088b108bc8ff5238")
GAME_MAIN_ARGC = 0x14
GAME_MAIN_ARGV = 0x18
#: The mid-session map swap, as `LivingWorldLogic::startCampaign` performs it. See
#: `docs/map-transition.md`.
GAME_LOGIC_START_NEW_GAME = 0x0077948E
GAME_LOGIC_LOAD_MAP = 0x006314CD
GAME_LOGIC_BUILD_WORLD = 0x0062F91A
MAP_PATH_FORMAT = 0x00BF51B4
#: `GameState::registerSnapshot(AsciiString name, Snapshot *obj, int list)` - appends a
#: `{name, snapshot}` pair to a list at `this + 0x10 + list*4`. `0x006DF904` registers
#: `CHUNK_ScriptEngine` against `THE_SCRIPT_ENGINE + 0xC`; `0x006DFCA5` is the load-side twin.
#: The chunk's own byte layout is decoded by `sage_save.chunks.decode_script_engine`.
GAME_STATE_REGISTER_SNAPSHOT = 0x006DF45B
STD_MAP_NODE_VALUE = 0x18
STD_MAP_ITERATOR_INCREMENT = 0x00423EA0
GAME_LOGIC_CREATE_OBJECT = 0x00625841
#: The live script tree, derived in `docs/script-debugger.md` §2. `SidesList` holds
#: `SIDES_LIST_SIDE_COUNT` sides from `SIDES_LIST_SIDES` on, `SIDES_INFO_STRIDE` apart, and each
#: `SidesInfo` **embeds** its `ScriptList` at `SIDES_INFO_SCRIPT_LIST`. Side `i` is player `i`: the
#: per-frame driver walks both lists with one index.
SIDES_LIST_SIDE_COUNT = 0x3C
SIDES_LIST_SIDES = 0x40
SIDES_INFO_STRIDE = 0x60
SIDES_INFO_SCRIPT_LIST = 0x08
#: `GameLogic::m_gameMode`. `GameLogic::isInMultiplayerGame` (`0x00441B7C`) is membership of
#: `NETWORK_GAME_MODES`; 3 is replay playback. Derived in `docs/observer-switch.md`.
GAME_LOGIC_GAME_MODE = 0x110
NETWORK_GAME_MODES = (1, 5)
# An INI keyword is matched by exact compare, so anything the parser could never match is a typo


# The `MapCache` block and the lobby map list (`docs/map-list-symbols.md`).
#: The `MapCache` field-parse table: 24 rows. Offsets are into a parse-time temporary.
MAP_CACHE_FIELD_TABLE = 0x00C7FAE8
#: The table's only two references, each the imm32 of one instruction: the getter's
#: `mov eax, 0xc7fae8` and the `push 0xc7fae8` that hands it to `INI_PARSE_FIELDS`. Repointing
#: both is what moves the table, and having exactly two is what makes moving it cheap.
MAP_CACHE_FIELD_TABLE_GETTER_REF = 0x0093B447
MAP_CACHE_FIELD_TABLE_PARSE_REF = 0x0093BA81
#: `parseMapCacheDefinition`'s `call INI_PARSE_FIELDS`. Hooked to clear the pending symbol before
#: a block's fields are read, which is what stops a `mapSymbol` on a block whose entry is then
#: rejected - a missing file, an empty name - from leaking into the next block.
MAP_CACHE_PARSE_FIELDS = 0x0093BA8C
MAP_CACHE_PARSE_FIELDS_BYTES = bytes.fromhex("e8ef20afff")
#: `call MapMetaData::operator=` on the entry `MapCache::insert` just returned - the last thing
#: `parseMapCacheDefinition` does to a block, and the first moment the *stored* entry exists. The
#: insert is `ret 4` and leaves the source pointer on the stack as this call's argument, so the
#: cave has to re-push it rather than tail-jump.
MAP_CACHE_ASSIGN_CALL = 0x0093BCE4
MAP_CACHE_ASSIGN_CALL_BYTES = bytes.fromhex("e8798ddcff")
#: `MapMetaData::operator=` itself - `__thiscall`, one stack argument, `ret 4`, returning the
#: destination in `eax`. It copies `+0xF4` from the source, which is why the symbol is written
#: after it and not before.
MAP_META_DATA_ASSIGN = 0x00704A62
#: The two `MapMetaData` offsets this patch reads: the sort/icon key, and the `isOfficial` byte
#: whose only job in the stock engine is to set bit 15 of that key.
MAP_META_DATA_SORT_KEY = 0xF4
MAP_META_DATA_IS_OFFICIAL = 0x26
#: The 24 stock rows, `(keyword, offset into the parse temporary)`, in table order. Checked
#: before the table is copied, so a build whose table is not this one fails loudly rather than
#: having a row appended to whatever is there.
MAP_CACHE_STOCK_FIELDS = (
    ("isOfficial", 0x28),
    ("isMultiplayer", 0x1C),
    ("isScenarioMP", 0x1D),
    ("extentMin", 0x00),
    ("extentMax", 0x0C),
    ("numPlayers", 0x18),
    ("fileSize", 0x34),
    ("fileCRC", 0x38),
    ("timestampLo", 0x2C),
    ("timestampHi", 0x30),
    ("displayName", 0x20),
    ("description", 0x24),
    ("supplyPosition", 0x00),
    ("techPosition", 0x00),
    ("Player_1_Start", 0x3C),
    ("Player_2_Start", 0x48),
    ("Player_3_Start", 0x54),
    ("Player_4_Start", 0x60),
    ("Player_5_Start", 0x6C),
    ("Player_6_Start", 0x78),
    ("Player_7_Start", 0x84),
    ("Player_8_Start", 0x90),
    ("InitialCameraPosition", 0x9C),
    ("PlayerPosition", 0x00),
)
#: `TheGameLogic`'s object-id hash: a bucket array from `+0xB8` to `+0xBC`, each bucket a chain of
#: `{next, ObjectID, Object *}` entries. Walked by the lookup `findObjectByID` reaches
#: (`0x006B4E8F`, on the table header at `+0xB4`): bucket `id % count`, then `next` until the id
#: matches. Ids past the bucket count share a bucket, so a full walk has to follow `next`.
GAME_LOGIC_OBJECT_BUCKETS_BEGIN = 0xB8
GAME_LOGIC_OBJECT_BUCKETS_END = 0xBC
OBJECT_HASH_ENTRY_NEXT = 0x00
OBJECT_HASH_ENTRY_OBJECT = 0x08
#: `mov eax, [ecx+4]` / `mov eax, [eax+edx*4]` / ... / `cmp [eax+4], esi` / `mov eax, [eax]` - the
#: bucket index and chain walk that fix the entry layout above.
GAME_LOGIC_OBJECT_HASH_WALK = 0x006B4EA6
GAME_LOGIC_OBJECT_HASH_WALK_BYTES = bytes.fromhex("8b41048b0490eb0739700474068b0085c075f5")
