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
    "ABILITY_MODULEDATA_SPECIAL_POWER",
    "ABILITY_TRIGGER",
    "ABILITY_TRIGGER_MODULEDATA_EBP",
    "ABILITY_TRIGGER_OBJECT_EBP",
    "ABILITY_TRIGGER_PAY",
    "ABILITY_TRIGGER_PAY_BYTES",
    "ABILITY_TRIGGER_PAY_RESUME",
    "ABILITY_TRIGGER_VTABLE",
    "APPEND_MESSAGE_VTABLE_SLOT",
    "ARG_APPENDERS",
    "AUTO_DEPOSIT_FILTER_EBP",
    "AUTO_DEPOSIT_MODULE_DATA_EBP",
    "AUTO_DEPOSIT_MULTIPLIER_EBP",
    "AUTO_DEPOSIT_SCALE",
    "AUTO_DEPOSIT_SCALE_BYTES",
    "AUTO_DEPOSIT_SCALE_RESUME",
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
    "CAN_USE_SPECIAL_POWER",
    "CAN_USE_SPECIAL_POWER_ENTRY",
    "CLEAR_GAME_DATA",
    "COMMAND_BUTTON_SPECIAL_POWER",
    "CONTROL_BAR_UNAVAILABLE",
    "CONTROL_BAR_UNIT_COST_CALL",
    "CONTROL_BAR_UNIT_COST_CALL_BYTES",
    "DESCRIPTION_BUFFER_EBP_OFFSET",
    "DESCRIPTION_DONE",
    "DESCRIPTION_LINE_EBP_OFFSET",
    "DESCRIPTION_OBJECT_EBP_OFFSET",
    "DESCRIPTION_RANK_APPEND",
    "DESCRIPTION_RANK_APPEND_BYTES",
    "DESCRIPTION_RANK_RESUME",
    "DESCRIPTION_SPECIAL_POWER_CASE",
    "DESCRIPTION_SPECIAL_POWER_CASE_BYTES",
    "DESCRIPTION_TEXT_EBP_OFFSET",
    "DESCRIPTION_UNIT_COST_BODY",
    "DO_SPECIAL_POWER_SITES",
    "GAME_INFO_MAP",
    "GAME_LOGIC_FRAME",
    "GAME_LOGIC_UPDATE",
    "GAME_LOGIC_UPDATE_ENTRY",
    "GAME_LOGIC_UPDATE_VTABLE_SLOT",
    "GAME_MODE_SKIRMISH",
    "GAME_TEXT_FORMAT_SLOT",
    "GET_FINAL_OVERRIDE",
    "GUICOMMAND_REVIVE",
    "GUI_COMMAND_SPECIAL_POWER",
    "IMAGE_BASE",
    "IMPORT_FFLUSH",
    "IMPORT_FWRITE",
    "IMPORT_GET_LOCAL_TIME",
    "IMPORT_SWPRINTF",
    "INI_NEXT_TOKEN_OR_NULL",
    "INI_PARSE_INT",
    "INI_SCAN_INT",
    "MAX_PLAYER_COUNT",
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
    "OBJECT_THING_TEMPLATE",
    "OPERATOR_NEW",
    "PALANTIR_COMMAND_POINTS",
    "PALANTIR_COMMAND_POINTS_BYTES",
    "PALANTIR_COMMAND_POINTS_DONE",
    "PALANTIR_COMMAND_POINTS_RESUME",
    "PLAYER_COMMAND_POINTS_USED",
    "PLAYER_DEFEAT_FRAME",
    "PLAYER_INDEX",
    "PLAYER_IS_DEFEATED",
    "PLAYER_IS_OBSERVER",
    "PLAYER_LIST_GET_LOCAL_PLAYER",
    "PLAYER_PLAYER_TEMPLATE",
    "PLAYER_TEMPLATE_BLOCK_KEY",
    "PLAYER_TEMPLATE_BLOCK_KEY_BYTES",
    "PLAYER_TEMPLATE_BLOCK_KEY_RESUME",
    "PLAYER_TEMPLATE_FIELD_TABLE",
    "PLAYER_TEMPLATE_FIELD_TABLE_REFS",
    "PLAYER_TEMPLATE_FIELD_TABLE_REF_OPCODES",
    "PLAYER_TEMPLATE_FIND_BY_KEY",
    "PLAYER_TEMPLATE_NAME_KEY",
    "PLAYER_TEMPLATE_RESOURCE_FILTER",
    "PLAYER_TEMPLATE_RESOURCE_VALUES",
    "PLAYER_TEMPLATE_SIZE",
    "PRODUCTION_UPDATE_INTERFACE_VTABLE",
    "PRODUCTION_UPDATE_VTABLE",
    "RECORDER_END_BRANCH",
    "RECORDER_END_BRANCH_BYTES",
    "RECORDER_END_WRITE_CALL",
    "RECORDER_END_WRITE_CALL_BYTES",
    "RECORDER_FILE",
    "RECORDER_GAME_MODE",
    "RECORDER_GAME_MODE_RESET",
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
    "RECORDER_RECORDED_MODES",
    "RECORDER_RESET_WRITES_GAME_MODE",
    "RECORDER_STOP_RECORDING",
    "RECORDER_WRITE_TO_FILE",
    "REQUEST_UNIQUE_UNIT_ID",
    "REQUEST_UNIQUE_UNIT_ID_BODY",
    "REQUEST_UNIQUE_UNIT_ID_VTABLE_SLOT",
    "FIELD_PARSE_STRIDE",
    "INI_PARSE_BOOL",
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
    "TERRAIN_RESOURCE_FREE_OFFSET",
    "TERRAIN_RESOURCE_MODULE_DATA_CTOR",
    "TERRAIN_RESOURCE_MODULE_DATA_EBP_SLOT",
    "TERRAIN_RESOURCE_MODULE_DATA_SIZE",
    "TERRAIN_RESOURCE_UPDATE",
    "TERRAIN_RESOURCE_UPDATE_VTABLE",
    "TERRAIN_RESOURCE_UPDATE_VTABLE_SLOT",
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
    "THE_BUILD_ASSISTANT",
    "THE_GAME_INFO",
    "THE_GAME_LOGIC",
    "THE_GAME_STATE",
    "THE_GAME_TEXT",
    "THE_MESSAGE_STREAM",
    "THE_PARTITION_MANAGER",
    "THE_PLAYER_LIST",
    "THE_RECORDER",
    "THE_SCIENCE_STORE",
    "THE_SKIRMISH_GAME_INFO",
    "THE_SPECIAL_POWER_STORE",
    "THE_THING_FACTORY",
    "THE_UPGRADE_CENTER",
    "THE_VICTORY_CONDITIONS",
    "THING_TEMPLATE_COPY_CALL",
    "THING_TEMPLATE_COPY_CALL_BYTES",
    "THING_TEMPLATE_COPY_FROM",
    "UNICODE_STRING_APPEND",
    "UNICODE_STRING_CONCAT",
    "UNICODE_STRING_FORMAT",
    "UNICODE_STRING_FROM_WIDE",
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

# `ThePartitionManager`, which owns the per-cell and per-object shroud state that fog filtering
# needs (`PartitionCell::m_shroudLevel[N]`, `PartitionData::m_shroudedness[N]` - see
# `docs/max-player-count.md`).
#
# **Derived statically, not yet confirmed against a running process** - unlike every other
# global here. The name string at `0x00BFDC08` is pushed at `0x0062CECB`, and the object built
# immediately after (`push 0x14` - it is only 20 bytes - then a constructor) is stored to this
# address at `0x0062CF01`. The same read of the `TheGameLogic` registration recovers its known
# `0x00DE412C`, which is what makes the pattern trustworthy rather than suggestive. To confirm:
# read it in a live match and expect a non-null pointer to a 20-byte object.
THE_PARTITION_MANAGER = 0x00DE4358

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
# and 3c.
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
# value must fold or bound it - see `patches/hero_mana.py`, which masks it.
OBJECT_ID = 0x74

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
#: 127, and `docs/ideas/second-resource-type.md` records it as something a relocation would have
#: to re-derive - but disassembly says `0x007162A4` is `call 0x723CEE`, whose `E8` opcode plus the
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

#: Where the builder keeps the line it is composing, and the description it appends lines to.
#: Both are `ebp`-relative in the builder's own frame, so a cave reached by `jmp` can use them.
DESCRIPTION_LINE_EBP_OFFSET = -0x2C
DESCRIPTION_TEXT_EBP_OFFSET = -0x18

#: The `Object` the description builder is describing, in its own frame. Its prologue resolves it
#: once (`[0x00DE4830]` vtable `+0x12c` -> a `Drawable`, then `+0xfc` -> the `Object`) and keeps it
#: here; `0x00807AE4` passing it to `Object::getControllingPlayer` is what identifies it. It may be
#: null when nothing is being described.
DESCRIPTION_OBJECT_EBP_OFFSET = -0x1C

#: `CommandButton::m_specialPower`, and the GUI command value that says a button has one.
COMMAND_BUTTON_SPECIAL_POWER = 0x44
GUI_COMMAND_SPECIAL_POWER = 0x18

#: How the engine appends one `<label>: <number>` line to a description. Twelve sites share the
#: idiom, so it is stable: fetch the localized label through `TheGameText`'s vtable `+0x44` with
#: the caller's three already-pushed arguments, then concatenate onto the buffer the builder keeps
#: at `ebp-0x28`, then drop all three.
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

# The module's *primary* vtable, written at `module+0x00` by the constructor
# (`0x008A1819`: `mov dword [esi], 0xc67ef4`). A vtable address is unique to its class, so
# this is how a reader outside the process identifies which of an object's behaviour modules
# is the `ProductionUpdate` - without calling the engine's own `getProductionUpdateInterface`,
# which it cannot. Used by `sage_live.memory` to read production state; see
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

#: `PlayerList::getLocalPlayer` - thiscall, no arguments. The palantir's own refresh
#: (`0x006D577C`) reaches the displayed player through it, so a HUD-side read matches.
PLAYER_LIST_GET_LOCAL_PLAYER = 0x006A8839

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

#: `INI::getNextTokenOrNull(seps)` and `INI::scanInt(token)` - both thiscall on the `INI`, both
#: `ret 4`. The pair the stock `ResourceModifierValues` parser (`0x005FD599`) loops over, and
#: the only engine help a variable-length `Int` list parser needs.
INI_NEXT_TOKEN_OR_NULL = 0x0042DBF5
INI_SCAN_INT = 0x0042E9D7

#: The palantir's command-point text, built and pushed to the movie in one place.
#:
#: It is **not** a numeric data binding: `0x0080078F` formats `L"%d/%d"` (`0x00C4E594`) with
#: `(used, cap)` into a `UnicodeString` and hands it to
#: `TheAptPlayer::setValue("APT:PalantirCommandPoints", …)` (`0x00624FFD`). The mod's `.csf`
#: entry of the same name is a design-time placeholder - Edain's reads `102/200` - overwritten
#: every refresh, which is why a third number has to come from the engine and not from data.
#:
#: The window is `cmp [ebp+0xC], edi` / `push dword ptr [ebp+8]`, six bytes, and it sits
#: *before* the first vararg push - which is what makes room for a third one, since varargs are
#: pushed last-argument-first.
PALANTIR_COMMAND_POINTS = 0x008007DC
PALANTIR_COMMAND_POINTS_BYTES = bytes.fromhex("397d0cff7508")
PALANTIR_COMMAND_POINTS_RESUME = 0x008007E2
PALANTIR_COMMAND_POINTS_DONE = 0x00800817

#: `UnicodeString::format(this, fmt, ...)` - cdecl, caller-cleaned, so one more vararg costs one
#: more push and a `0x10 -> 0x14` on the cleanup.
UNICODE_STRING_FORMAT = 0x00ADF750
