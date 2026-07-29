"""Addresses of one engine build, in one place.

The RotWK SAGE-engine `game.dat` build ``2.01.2614.37001`` (11,346,944 bytes, ImageBase
``0x400000``, no ASLR - so a virtual address here is also where the byte sits in a running
process).

**Why this module exists.** These facts were being carried in two packages at once:
`sage_live.EngineLayout` held the subsystem globals it reads, while
`sage_patch.patches.live_bridge` held the ones its cave calls. Both describe the same build,
so supporting a second one meant editing two files by two different mechanisms - and only one
of them could be overridden without a code change. A build is one thing; it is described
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
    "APPEND_MESSAGE_VTABLE_SLOT",
    "ARG_APPENDERS",
    "BUILD",
    "BUILD_ASSISTANT_VTABLE",
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
    "CLEAR_GAME_DATA",
    "GAME_INFO_MAP",
    "GAME_LOGIC_FRAME",
    "GAME_LOGIC_UPDATE",
    "GAME_LOGIC_UPDATE_ENTRY",
    "GAME_LOGIC_UPDATE_VTABLE_SLOT",
    "GAME_MODE_SKIRMISH",
    "GUICOMMAND_REVIVE",
    "IMAGE_BASE",
    "IMPORT_FFLUSH",
    "IMPORT_FWRITE",
    "IMPORT_GET_LOCAL_TIME",
    "IMPORT_SWPRINTF",
    "MAX_PLAYER_COUNT",
    "MSG_CLEAR_GAME_DATA",
    "MSG_NEW_GAME",
    "PLAYER_DEFEAT_FRAME",
    "PLAYER_INDEX",
    "PLAYER_IS_DEFEATED",
    "PLAYER_IS_OBSERVER",
    "PRODUCTION_UPDATE_INTERFACE_VTABLE",
    "RECORDER_END_BRANCH",
    "RECORDER_END_BRANCH_BYTES",
    "RECORDER_END_WRITE_CALL",
    "RECORDER_END_WRITE_CALL_BYTES",
    "RECORDER_FILE",
    "RECORDER_GAME_MODE",
    "RECORDER_LAST_REPLAY_NAME",
    "RECORDER_MODE",
    "RECORDER_MODE_GATE",
    "RECORDER_MODE_GATE_ACCEPT",
    "RECORDER_MODE_GATE_BYTES",
    "RECORDER_MODE_GATE_REJECT",
    "RECORDER_MODE_RECORD",
    "RECORDER_NAME_CALL",
    "RECORDER_NAME_CALL_BYTES",
    "RECORDER_NAME_CALL_FINGERPRINT",
    "RECORDER_NEW_GAME_BRANCH",
    "RECORDER_NEW_GAME_BRANCH_BYTES",
    "RECORDER_GAME_MODE_RESET",
    "RECORDER_RECORDED_MODES",
    "RECORDER_RESET_WRITES_GAME_MODE",
    "RECORDER_STOP_RECORDING",
    "RECORDER_WRITE_TO_FILE",
    "START_RECORDING",
    "START_RECORDING_MODE_ARG",
    "REQUEST_UNIQUE_UNIT_ID",
    "REQUEST_UNIQUE_UNIT_ID_BODY",
    "REQUEST_UNIQUE_UNIT_ID_VTABLE_SLOT",
    "THE_BUILD_ASSISTANT",
    "THE_GAME_INFO",
    "THE_GAME_LOGIC",
    "THE_GAME_STATE",
    "THE_MESSAGE_STREAM",
    "THE_PLAYER_LIST",
    "THE_RECORDER",
    "THE_SCIENCE_STORE",
    "THE_SKIRMISH_GAME_INFO",
    "THE_SPECIAL_POWER_STORE",
    "THE_THING_FACTORY",
    "UNICODE_STRING_FROM_WIDE",
    "THE_UPGRADE_CENTER",
    "THE_VICTORY_CONDITIONS",
    "VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY",
    "VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY_SLOT",
    "VICTORY_CONDITIONS_HAS_BEEN_DEFEATED",
    "VICTORY_CONDITIONS_HAS_BEEN_DEFEATED_SLOT",
    "VICTORY_CONDITIONS_IS_DEFEATED",
    "VICTORY_CONDITIONS_PLAYERS",
    "VICTORY_CONDITIONS_VTABLE",
]

BUILD = "RotWK 2.01.2614.37001"
IMAGE_BASE = 0x00400000

# Subsystem singletons. Each address holds a *pointer to* the object, not the object; they are
# registered by name at startup, which is how they were found (see `docs/engine-globals.md`
# for the full 88).
THE_GAME_LOGIC = 0x00DE412C
THE_PLAYER_LIST = 0x00DE4928
THE_MESSAGE_STREAM = 0x00DE6398
THE_GAME_STATE = 0x00DE4AD4
THE_RECORDER = 0x00DE7CD8
THE_BUILD_ASSISTANT = 0x00DE8200
THE_VICTORY_CONDITIONS = 0x00DE89AC

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

# The four id-space stores. `sage_live.resolve` reconstructs these spaces from ini; reading the
# engine's own tables instead is the alternative, and two of the four are now read that way.
#
# `TheUpgradeCenter` settled the upgrade `+3` (order_space_map OPEN 4: three engine-registered
# veterancy upgrades ahead of the ini's first) and is what `sage_live.memory` names upgrade bits
# with. `TheThingFactory` has the same shape - list head at `+0x0C`, count at `+0x10`, and
# `ThingTemplate+0x494` for `next` - and `sage_live.memory.thing_order` walks it, so a policy can
# name a template with no ini load. Both are derived in `docs/live-object-model.md` sections 3b
# and 3c. `TheSpecialPowerStore` and `TheScienceStore` have not been walked.
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

# `MessageStream::appendMessage(GameMessage::Type)` is virtual, at this vtable offset, and
# returns the new `GameMessage *`.
APPEND_MESSAGE_VTABLE_SLOT = 0x48

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
# The whole stock body: `mov eax,[ecx+0x10]` / `lea edx,[eax+1]` / `mov [ecx+0x10],edx` / `ret`.
# Ten bytes, entered only through the vtable, so all ten are replaceable in place.
REQUEST_UNIQUE_UNIT_ID_BODY = bytes.fromhex("8b41108d5001895110c3")

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
