"""Players, teams, upgrades, sciences, special powers and the score keeper."""

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
    "CAN_DO_SPECIAL_POWER_AT_LOCATION",
    "CAN_DO_SPECIAL_POWER_AT_OBJECT",
    "CAN_USE_SPECIAL_POWER",
    "CAN_USE_SPECIAL_POWER_ENTRY",
    "COMMAND_BUTTON_AUTO_ABILITY",
    "COMMAND_BUTTON_COMMAND",
    "COMMAND_BUTTON_CTOR",
    "COMMAND_BUTTON_CTOR_AUTO_ABILITY",
    "COMMAND_BUTTON_CTOR_AUTO_ABILITY_BYTES",
    "COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY",
    "COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY_BYTES",
    "COMMAND_BUTTON_FIELD_TABLE",
    "COMMAND_BUTTON_FIELD_TABLE_REFS",
    "COMMAND_BUTTON_FIELD_TABLE_REF_OPCODES",
    "COMMAND_BUTTON_FREE_OFFSET",
    "COMMAND_BUTTON_GET_TEXT_LABEL",
    "COMMAND_BUTTON_GET_THING_TEMPLATE",
    "COMMAND_BUTTON_GET_THING_TEMPLATE_ENTRY",
    "COMMAND_BUTTON_OBJECT",
    "COMMAND_BUTTON_REVIVE_INDEX",
    "COMMAND_BUTTON_SIZE",
    "COMMAND_BUTTON_SPECIAL_POWER",
    "COMMAND_BUTTON_TRIGGER_WHEN_READY",
    "COMMAND_POINTS_BASE",
    "COMMAND_POINTS_HARD_CAP",
    "COMMAND_POINTS_INIT",
    "COMMAND_POINTS_INIT_FACTOR",
    "COMMAND_POINTS_INIT_FACTOR_BYTES",
    "COMMAND_POINTS_INIT_MERGE",
    "COMMAND_POINTS_INIT_MERGE_BYTES",
    "COMMAND_POINTS_INIT_RETURN",
    "COMMAND_POINTS_INIT_RETURN_BYTES",
    "COMMAND_POINTS_OVERRIDDEN",
    "COMMAND_POINTS_OVERRIDE",
    "COMMAND_POINTS_RESET",
    "COMMAND_SET_GET_COMMAND_BUTTON",
    "COMMAND_SET_STORE_FIND_COMMAND_SET",
    "COMMAND_SET_STORE_GET_PURCHASE_SCIENCE_COMMAND_SET",
    "DO_COMMAND_BUTTON",
    "DO_COMMAND_BUTTON_BUTTON_EBP",
    "DO_COMMAND_BUTTON_REVIVE_QUEUE",
    "DO_COMMAND_BUTTON_REVIVE_QUEUE_BYTES",
    "DO_COMMAND_BUTTON_REVIVE_QUEUE_RESUME",
    "DO_COMMAND_BUTTON_UNIT_QUEUE",
    "DO_COMMAND_BUTTON_UNIT_QUEUE_BYTES",
    "DO_COMMAND_BUTTON_UNIT_QUEUE_RESUME",
    "DO_COMMAND_SPELL_BOOK_EXEMPTION",
    "DO_COMMAND_UPGRADE_GET",
    "DO_COMMAND_UPGRADE_REMOVE",
    "DO_SPECIAL_POWER_SITES",
    "GET_FINAL_OVERRIDE",
    "GIVE_UPGRADE_CAN_GIVE",
    "GIVE_UPGRADE_CAN_GIVE_BODY",
    "GIVE_UPGRADE_CAN_GIVE_BODY_BYTES",
    "GIVE_UPGRADE_CAN_GIVE_ENTRY",
    "GIVE_UPGRADE_PRODUCER_HORDE_IFACE",
    "GIVE_UPGRADE_PRODUCER_HORDE_IFACE_ENTRY",
    "GIVE_UPGRADE_SEARCH_FILTER_OWNER",
    "GIVE_UPGRADE_SEARCH_FILTER_OWNER_BYTES",
    "GIVE_UPGRADE_SEARCH_FILTER_VTABLE",
    "GIVE_UPGRADE_SEARCH_FILTER_VTABLE_BYTES",
    "GIVE_UPGRADE_SEARCH_OWNER_LOAD",
    "GIVE_UPGRADE_SEARCH_OWNER_LOAD_BYTES",
    "GIVE_UPGRADE_TRIGGER_MEMBER_ARM",
    "GIVE_UPGRADE_TRIGGER_MEMBER_ARM_BYTES",
    "GIVE_UPGRADE_TRIGGER_OWNER",
    "GIVE_UPGRADE_TRIGGER_OWNER_BYTES",
    "GIVE_UPGRADE_TRIGGER_PICK",
    "GIVE_UPGRADE_TRIGGER_PICK_BYTES",
    "GIVE_UPGRADE_TRIGGER_TARGET_ARM",
    "GIVE_UPGRADE_TRIGGER_TARGET_ARM_BYTES",
    "PLAYER_ADD_COMMAND_POINTS_FOR_OBJECT",
    "PLAYER_COMMAND_POINTS_BONUS",
    "PLAYER_COMMAND_POINTS_CAP",
    "PLAYER_COMMAND_POINTS_HARD_CAP",
    "PLAYER_COMMAND_POINTS_USED",
    "PLAYER_COMPLETED_UPGRADE_MASK",
    "PLAYER_COMPLETED_UPGRADE_MASK_WORDS",
    "PLAYER_DEFAULT_TEAM",
    "PLAYER_DEFEAT_FRAME",
    "PLAYER_FOR_EACH_TEAM_OBJECT",
    "PLAYER_GET_SPELLBOOK_OBJECT",
    "PLAYER_GET_UPGRADE_DISCOUNT",
    "PLAYER_GET_UPGRADE_DISCOUNT_BODY",
    "PLAYER_GRANT_UPGRADE",
    "PLAYER_HERO_LEDGER_OFFSET",
    "PLAYER_INDEX",
    "PLAYER_INIT",
    "PLAYER_INIT_ENTRY",
    "PLAYER_INIT_ENTRY_BYTES",
    "PLAYER_INIT_ENTRY_RESUME",
    "PLAYER_INIT_FROM_DICT",
    "PLAYER_INIT_FROM_DICT_BYTES",
    "PLAYER_IS_DEFEATED",
    "PLAYER_IS_OBSERVER",
    "PLAYER_KILL_PLAYER",
    "PLAYER_LIST_COUNT_OFFSET",
    "PLAYER_LIST_GET_LOCAL_PLAYER",
    "PLAYER_LIST_GET_NTH",
    "PLAYER_LIST_LOCAL_IS_NOT_ACTIVE",
    "PLAYER_LIST_LOCAL_IS_NOT_ACTIVE_BYTES",
    "PLAYER_LIST_LOCAL_PLAYER",
    "PLAYER_LIST_OBSERVE_NEXT_PLAYER",
    "PLAYER_LIST_PLAYER_FROM_INDEX",
    "PLAYER_LIST_RECOMPUTE_COMMAND_POINTS",
    "PLAYER_LIVING_WORLD_ID_OFFSET",
    "PLAYER_MONEY",
    "PLAYER_NAME_KEY",
    "PLAYER_PLAYER_TEMPLATE",
    "PLAYER_POWER_POINTS",
    "PLAYER_POWER_POINTS_TOTAL",
    "PLAYER_RELATIONSHIP_ALLIES",
    "PLAYER_REMOVE_COMMAND_POINTS_FOR_OBJECT",
    "PLAYER_RESOURCES",
    "PLAYER_SCIENCES",
    "PLAYER_SCORE_KEEPER",
    "PLAYER_SET_SCIENCES",
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
    "PLAYER_TEAM_LIST",
    "PLAYER_TEMPLATE_BLOCK_KEY",
    "PLAYER_TEMPLATE_BLOCK_KEY_BYTES",
    "PLAYER_TEMPLATE_BLOCK_KEY_EARLY",
    "PLAYER_TEMPLATE_BLOCK_KEY_EARLY_BYTES",
    "PLAYER_TEMPLATE_BLOCK_KEY_EARLY_RESUME",
    "PLAYER_TEMPLATE_BLOCK_KEY_RESUME",
    "PLAYER_TEMPLATE_DEFAULT_AI_TYPE",
    "PLAYER_TEMPLATE_FIELD_DEFAULT_AI_TYPE",
    "PLAYER_TEMPLATE_FIELD_DEFAULT_AI_TYPE_BYTES",
    "PLAYER_TEMPLATE_EVIL",
    "PLAYER_TEMPLATE_FIELD_TABLE",
    "PLAYER_TEMPLATE_FIELD_TABLE_REFS",
    "PLAYER_TEMPLATE_FIELD_TABLE_REF_OPCODES",
    "PLAYER_TEMPLATE_FIND_BY_INDEX",
    "PLAYER_TEMPLATE_FIND_BY_KEY",
    "PLAYER_TEMPLATE_GET_DISPLAY_NAME",
    "PLAYER_TEMPLATE_IS_OBSERVER",
    "PLAYER_TEMPLATE_NAME_KEY",
    "PLAYER_TEMPLATE_PARSED_JOIN",
    "PLAYER_TEMPLATE_PARSED_JOIN_BYTES",
    "PLAYER_TEMPLATE_PARSED_JOIN_RESUME",
    "PLAYER_TEMPLATE_PARSED_NEW_KEY",
    "PLAYER_TEMPLATE_PARSED_NEW_KEY_BYTES",
    "PLAYER_TEMPLATE_PARSED_NEW_KEY_RESUME",
    "PLAYER_TEMPLATE_PLAYABLE_SIDE",
    "PLAYER_TEMPLATE_PTR",
    "PLAYER_TEMPLATE_PURCHASE_SCIENCE_COMMAND_SET",
    "PLAYER_TEMPLATE_PURCHASE_SCIENCE_COMMAND_SET_MP",
    "PLAYER_TEMPLATE_RESOURCE_FILTER",
    "PLAYER_TEMPLATE_RESOURCE_VALUES",
    "PLAYER_TEMPLATE_SIZE",
    "PLAYER_TEMPLATE_STORE_BEGIN",
    "PLAYER_TEMPLATE_STORE_END",
    "PLAYER_TRANSFER_COMMAND_POINTS_FOR_OBJECT",
    "PLAYER_UPGRADE_DISCOUNTS",
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
    "SHARE_EXPERIENCE",
    "SHARE_EXPERIENCE_CALC",
    "SHARE_EXPERIENCE_CALC_BYTES",
    "SHARE_EXPERIENCE_CALC_RESUME",
    "SHARE_EXPERIENCE_DISPATCH",
    "SHARE_EXPERIENCE_DISPATCH_BYTES",
    "SHARE_EXPERIENCE_DROPOFF",
    "SHARE_EXPERIENCE_GET_DROPOFF",
    "SHARE_EXPERIENCE_GET_DROPOFF_BYTES",
    "SHARE_EXPERIENCE_GET_DROPOFF_RESUME",
    "SHARE_EXPERIENCE_INTERFACE",
    "SHARE_EXPERIENCE_LOOP",
    "SHARE_EXPERIENCE_LOOP_BACK",
    "SHARE_EXPERIENCE_MODULEDATA",
    "SHARE_EXPERIENCE_MODULEDATA_SIZE",
    "SHARE_EXPERIENCE_OWNER",
    "SHARE_EXPERIENCE_PERCENTAGE",
    "SHARE_EXPERIENCE_QUERY_SLOT",
    "SHARE_EXPERIENCE_RADIUS",
    "SHARE_EXPERIENCE_SIZE",
    "SHARE_EXPERIENCE_TARGET_FILTER",
    "SPECIAL_POWER_FIELD_TABLE",
    "SPECIAL_POWER_FIELD_TABLE_REFS",
    "SPECIAL_POWER_FIELD_TABLE_REF_OPCODES",
    "SPECIAL_POWER_FORBIDDEN_OBJECTS_CALL",
    "SPECIAL_POWER_FORBIDDEN_OBJECTS_CALL_BYTES",
    "SPECIAL_POWER_FORBIDDEN_OBJECTS_CHECK",
    "SPECIAL_POWER_FORBIDDEN_OBJECT_FILTER",
    "SPECIAL_POWER_FORBIDDEN_OBJECT_RANGE",
    "SPECIAL_POWER_NOTIFY_TRIGGERED_AND_PLAY_INITIATE_AUDIO",
    "SPECIAL_POWER_READY_FRAME",
    "SPECIAL_POWER_START_RECHARGE",
    "SPECIAL_POWER_TEMPLATE_COPY_TAIL",
    "SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES",
    "SPECIAL_POWER_TEMPLATE_NEW_SITES",
    "SPECIAL_POWER_TEMPLATE_SIZE",
    "SPECIAL_POWER_UNIT_COST",
    "SPELLBOOK_UI_CACHE",
    "SPELLBOOK_UI_CACHE_HOOK",
    "SPELLBOOK_UI_CACHE_PLAYER_CHANGED",
    "SPELLBOOK_UI_CACHE_REBUILD",
    "SPELLBOOK_UI_CACHE_RETURN",
    "SPELLBOOK_UI_SLOT_LIMIT",
    "SPELLBOOK_UI_UPDATE_CACHE_CALL",
    "SPELLBOOK_UI_UPDATE_COMMAND_BUTTON",
    "SPELL_STORE_COMMAND_SET_CALL",
    "SPELL_STORE_COMMAND_SET_CALL_BYTES",
    "SPELL_STORE_INITIALIZE_SPELL_SLOTS",
    "SPM_FRAME_HOOK",
    "SPM_FRAME_HOOK_BYTES",
    "SPM_FRAME_RESUME",
    "SPM_MUSIC_POP",
    "SPM_MUSIC_PUSH",
    "SPM_MUSIC_RESUME",
    "SPM_SCRIPT_MUSIC_PUSH",
    "SPM_STOCK_ANCHORS",
    "SPM_TEMPLATE_ID",
    "SPM_THE_AUDIO",
    "SPM_TIME_GET_TIME_IAT",
    "SPM_TRIGGER_HOOK",
    "SPM_TRIGGER_HOOK_BYTES",
    "THE_EXPERIENCE_LEVEL_SYSTEM",
    "THE_PLAYER_LIST",
    "THE_PLAYER_TEMPLATE_STORE",
    "THE_SCIENCE_STORE",
    "THE_SPECIAL_POWER_STORE",
    "THE_UPGRADE_CENTER",
    "UPGRADE_CALC_COST_TO_BUILD",
    "UPGRADE_CENTER_FIND_UPGRADE",
    "UPGRADE_CENTER_FIND_UPGRADE_BY_KEY",
    "UPGRADE_CENTER_FIND_UPGRADE_BY_KEY_ENTRY",
    "UPGRADE_CENTER_FIND_UPGRADE_ENTRY",
    "UPGRADE_CENTER_FIND_UPGRADE_RESUME",
    "UPGRADE_CENTER_LIST",
    "UPGRADE_DISCOUNT_CALL",
    "UPGRADE_DISCOUNT_CALL_BYTES",
    "UPGRADE_DISCOUNT_ENTRY_VALUE",
    "UPGRADE_DISCOUNT_ENTRY_VALUE_ENTRY",
    "UPGRADE_DISCOUNT_GATE",
    "UPGRADE_DISCOUNT_GATE_BYTES",
    "UPGRADE_DISCOUNT_TYPE_BRANCH",
    "UPGRADE_DISCOUNT_TYPE_BRANCH_BYTES",
    "UPGRADE_FILTER_BODY",
    "UPGRADE_FILTER_BODY_BYTES",
    "UPGRADE_FILTER_OWNER_SLOT",
    "UPGRADE_FILTER_PREDICATE",
    "UPGRADE_FILTER_PREDICATE_ENTRY",
    "UPGRADE_FILTER_UPGRADE_SLOT",
    "UPGRADE_FIRST_SET",
    "UPGRADE_FIRST_SET_ENTRY",
    "UPGRADE_MASK_ANY",
    "UPGRADE_MASK_TEST_ANY",
    "UPGRADE_TEMPLATE_INDEX",
    "UPGRADE_TEMPLATE_NEXT",
    "VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY",
    "VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY_SLOT",
    "VICTORY_CONDITIONS_HAS_BEEN_DEFEATED",
    "VICTORY_CONDITIONS_HAS_BEEN_DEFEATED_SLOT",
    "VICTORY_CONDITIONS_IS_DEFEATED",
    "VICTORY_CONDITIONS_PLAYERS",
    "VICTORY_CONDITIONS_VTABLE",
]

THE_PLAYER_LIST = 0x00DE4928
THE_UPGRADE_CENTER = 0x00DE45A0
THE_SPECIAL_POWER_STORE = 0x00DE878C
THE_SCIENCE_STORE = 0x00DE3B20
# The activation path (`docs/hero-mana.md`): order/UI -> `Object::doSpecialPower*` ->
# `SpecialPowerStore::canUseSpecialPower` (the predicate) -> `Object::getSpecialPowerModule` ->
# module vtable `+0x2c`/`+0x30`/`+0x34` (the effect).

#: `Overridable::getFinalOverride`. **Every** template field read goes through it - an INI
#: override block is a copy further down a chain, and reading the base misses it.
GET_FINAL_OVERRIDE = 0x00688D3C
#: Where a hero ability actually fires: the `...SpecialAbilityUpdate` tick (`0x00854DF7`), not the
#: click - with `UpdateModuleStartsAttack = Yes`, `doSpecialPower*` never runs. `ebp` is the
#: interface `this` here, not a frame pointer; `UnitCost` is paid at `0x00855042`.
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
#: The three `Object::doSpecialPower*` variants as `(window VA, bytes, resume VA)`: the last point
#: an activation can be refused. Callers may skip `canUseSpecialPower`, so a charge must re-check.
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
#: `SpecialPowerTemplate`: `0x88` bytes, id at `+0x14`, no padding, so a new field must grow it.
# RotWK 2.01 addresses for `special-power-music`. The call returns the final template in `eax`; the
# `push 0` at `0x0089718B` belongs to the later `AudioEvent` constructor, not to this call.
SPECIAL_POWER_NOTIFY_TRIGGERED_AND_PLAY_INITIATE_AUDIO = 0x0089713F
SPM_TRIGGER_HOOK = 0x0089718C
SPM_TRIGGER_HOOK_BYTES = bytes.fromhex("e8ab1bdfff")
# After the application frame and profiling end, before frame pacing. +0x0C of
# subsystem vtables is an init lifecycle callback, not an established frame update.
SPM_FRAME_HOOK = 0x00639EEB
SPM_FRAME_HOOK_BYTES = bytes.fromhex("e9ff000000")
SPM_FRAME_RESUME = 0x00639FEF
SPM_TIME_GET_TIME_IAT = 0x00BD0920  # WINMM!timeGetTime, DWORD milliseconds, stdcall ()
SPM_THE_AUDIO = 0x00DE42FC  # AudioManager* global, not the vtable
SPM_MUSIC_PUSH = 0x00459EC2  # vtable +0x84; thiscall (AudioEvent*, immediate), ret 8
SPM_MUSIC_POP = 0x00455242  # +0x88; thiscall (channel, level, immediateOut, immediateIn), ret 16
SPM_MUSIC_RESUME = 0x00456192  # +0x94; same arguments, music channel=0, level=1, ret 16
# thiscall, `ret 24`: `(AsciiString *name, fadeOut, noFadeIn, count, flag *, level)`. Use level 1:
# level 0 is normal scripting, and a level-0 push cannot be undone by `Resume(0, 1)`.
SPM_SCRIPT_MUSIC_PUSH = 0x007C0EB8
# Assigned by 0x7B1ACD before INI parsing and copied by 0x7B1E6C. This is the
# store's numeric template ID, NOT a NameKey; the actual name is AsciiString +0x10.
SPM_TEMPLATE_ID = 0x14
# Short ABI anchors for routines called directly by the music cave. Hook windows
# alone do not prove that a different executable has the same audio-action ABI.
SPM_STOCK_ANCHORS = {
    SPM_MUSIC_POP: bytes.fromhex("b8eb1bb700e8a47c5e0083ec1453"),
    SPM_MUSIC_RESUME: bytes.fromhex("b8eb1bb700e8546d5e0083ec1453"),
    SPM_SCRIPT_MUSIC_PUSH: bytes.fromhex("b82970b900e82ec0270081ec88000000"),
}
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
#: The copy constructor's epilogue, right after it copies `+0x84`. It copies field by field, so a
#: grown struct has to copy the new fields too or an INI override block that does not mention
#: them loses them. `ebp` holds the *source* here - it is a spare register in this routine, not a
#: frame pointer.
SPECIAL_POWER_TEMPLATE_COPY_TAIL = 0x007B1F53
SPECIAL_POWER_TEMPLATE_COPY_TAIL_BYTES = bytes.fromhex("8bc35e5d5bc20400")
#: The `SpecialPower` field-parse table: 24 rows and a terminator with no slack after it, and
#: exactly two references, both bare imm32 operands.
SPECIAL_POWER_FIELD_TABLE = 0x00DA5FD8
SPECIAL_POWER_FIELD_TABLE_REFS = (0x007B1ABD, 0x007B2324)
SPECIAL_POWER_FIELD_TABLE_REF_OPCODES = (0xB8, 0x68)
#: The two targeted-cast predicates on `TheActionManager` (`...AtLocation` is `ret 0x1c`,
#: `...AtObject` `ret 0x18`); every caster reaches them. See `docs/forbidden-upgrade-filter.md`.
CAN_DO_SPECIAL_POWER_AT_LOCATION = 0x0082DFB7
CAN_DO_SPECIAL_POWER_AT_OBJECT = 0x0082D925
#: The `Flags = NO_FORBIDDEN_OBJECTS` scan: ``(Object *caster, Coord3D *where,
#: SpecialPowerTemplate *)`, `ret 0xc`, `al = 1`` when no `ForbiddenObjectFilter` match lies
#: within `ForbiddenObjectRange` of `where`. Its one caller is the location predicate's call at
#: `SPECIAL_POWER_FORBIDDEN_OBJECTS_CALL`; the object predicate has no forbidden check at all.
SPECIAL_POWER_FORBIDDEN_OBJECTS_CHECK = 0x0082D2FD
SPECIAL_POWER_FORBIDDEN_OBJECTS_CALL = 0x0082E128
SPECIAL_POWER_FORBIDDEN_OBJECTS_CALL_BYTES = bytes.fromhex("e8d0f1ffff")  # call 0x0082D2FD
SPECIAL_POWER_FORBIDDEN_OBJECT_FILTER = 0x78
SPECIAL_POWER_FORBIDDEN_OBJECT_RANGE = 0x7C
#: `CommandButton::m_specialPower`, and the GUI command value that says a button has one.
COMMAND_BUTTON_SPECIAL_POWER = 0x44
# `PlayerList::localPlayerIsNotActive` (observer or defeated). It has 12 callers: retarget the one
# call that needs a different answer, never widen the function.
PLAYER_LIST_LOCAL_IS_NOT_ACTIVE = 0x006A87F5
PLAYER_LIST_LOCAL_IS_NOT_ACTIVE_BYTES = bytes.fromhex("8b4910e855240000f6d8")
PLAYER_LIST_OBSERVE_NEXT_PLAYER = 0x006A8D2B
# `VictoryConditions`, which decides who is out and who has won (`docs/replay-outcome.md`).
# `m_players` is compacted, so its index is not a `ThePlayerList` index; `m_isDefeated` latches.
VICTORY_CONDITIONS_VTABLE = 0x00C4F108
VICTORY_CONDITIONS_PLAYERS = 0x18  # Player *m_players[MAX_PLAYER_COUNT]
VICTORY_CONDITIONS_IS_DEFEATED = 0x70  # Bool m_isDefeated[MAX_PLAYER_COUNT]
VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY_SLOT = 0x38
VICTORY_CONDITIONS_HAS_ACHIEVED_VICTORY = 0x00808AA8
VICTORY_CONDITIONS_HAS_BEEN_DEFEATED_SLOT = 0x40
VICTORY_CONDITIONS_HAS_BEEN_DEFEATED = 0x0080953C
# `Player` fields: `m_playerIndex` (the number in every replay chunk), the defeat frame and flag,
# and `m_isObserver`.
PLAYER_INDEX = 0x54
PLAYER_IS_OBSERVER = 0x35A
PLAYER_DEFEAT_FRAME = 0x4CC
PLAYER_IS_DEFEATED = 0x754
# `ScoreKeeper`, embedded in `Player`: the score-screen counters. See `docs/replay-annotations.md`.
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
# `UpgradeCenter::findUpgrade(const AsciiString *)` - `__thiscall` on `THE_UPGRADE_CENTER`,
# `ret 4`, NULL for an unknown name. **The one place a name becomes an upgrade**: 84 direct
# callers cover the INI mask and scalar parsers, the Lua bindings (`ObjectGrantUpgrade` reaches
# it at 0x00736E6C) and the map-script actions, so a change here reaches every name source.
UPGRADE_CENTER_FIND_UPGRADE = 0x0066F5E5
# Its whole body, for reference: `push esi` / `push [esp+8]` / `mov esi, ecx` /
# `mov ecx, [THE_NAME_KEY_GENERATOR]` / `call NAME_KEY_FROM_STRING` / `push eax` / `mov ecx, esi`
# / `call UPGRADE_CENTER_FIND_UPGRADE_BY_KEY` / `pop esi` / `ret 4`. The first five bytes are the
# hook site and the rest is what a cave has to reproduce.
UPGRADE_CENTER_FIND_UPGRADE_ENTRY = bytes.fromhex("56ff742408")
# Where the stock body resumes once `push esi` / `push [esp+8]` have been reproduced.
UPGRADE_CENTER_FIND_UPGRADE_RESUME = 0x0066F5EA
# `UpgradeCenter::findUpgradeByKey(NameKeyType)` - `__thiscall`, `ret 4`. Walks the template list
# from `UPGRADE_CENTER_LIST` comparing `UpgradeTemplate+0x0C`, chaining on `+0x64`.
UPGRADE_CENTER_FIND_UPGRADE_BY_KEY = 0x0066F230
UPGRADE_CENTER_FIND_UPGRADE_BY_KEY_ENTRY = bytes.fromhex("8b410c")
# `Relationship::ALLIES`, the value `Player::getRelationship` returns for one's own and one's
# allies' objects. `ENEMIES` is 0 and `NEUTRAL` is 1 - which is also what the accessor returns for
# a null object, at `0x006ACEED`, and what an unlisted team defaults to.
PLAYER_RELATIONSHIP_ALLIES = 2
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
#: `PlayerTemplate+0x10`, the block name's `NameKeyType`: the only stable identity a template has,
#: since templates are parsed into a temporary and copied into a vector.
PLAYER_TEMPLATE_NAME_KEY = 0x10
PLAYER_TEMPLATE_PURCHASE_SCIENCE_COMMAND_SET = 0x138
PLAYER_TEMPLATE_PURCHASE_SCIENCE_COMMAND_SET_MP = 0x13C
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
# The completed per-player upgrade mask is a fixed 36-dword bitset. An upgrade's bit is selected
# by `UpgradeTemplate::upgradeIndex`: word `index >> 5`, bit `index & 31`. The spell-store
# override resolves names at run time, validates the index against this exact bound, and reads no
# pending/requested mask beside it.
PLAYER_COMPLETED_UPGRADE_MASK = 0x14C
PLAYER_COMPLETED_UPGRADE_MASK_WORDS = 36
UPGRADE_TEMPLATE_INDEX = 0x38
# `AptSpellStore::initializeSpellSlots`, and its one call that asks for the player's purchase-
# science CommandSet. The patch deliberately retargets this call rather than the shared callee,
# so every other ControlBar/CommandSetStore consumer keeps stock behaviour. The stock rel32 lands
# at `0x0071F933`; `0x0071EFA2` is the same store's name lookup used by the selector after a match.
SPELL_STORE_INITIALIZE_SPELL_SLOTS = 0x00822A98
SPELL_STORE_COMMAND_SET_CALL = 0x00822ACF
SPELL_STORE_COMMAND_SET_CALL_BYTES = bytes.fromhex("e85fceefff")
COMMAND_SET_STORE_FIND_COMMAND_SET = 0x0071EFA2
COMMAND_SET_STORE_GET_PURCHASE_SCIENCE_COMMAND_SET = 0x0071F933
#: The command-point block: `cap = min(base +0x64 + bonus +0x6C + filtered extras, hard +0x70)`. The
#: extras need the engine to evaluate, so the flat fields give a lower bound.
PLAYER_COMMAND_POINTS_CAP = 0x64
PLAYER_COMMAND_POINTS_BONUS = 0x6C
PLAYER_COMMAND_POINTS_HARD_CAP = 0x70
#: Where the base and hard cap are (re)computed and where a script overrides them. See
#: `docs/command-point-override.md`.
#:
#: `CommandPointBookkeeping::init(playerIndex, isEvil)`, `ret 8`, on `Player+0x60`. Picks the
#: GameData pair (`GoodCommandPointsMPn` for n live players, `...AI`, plain, living-world bonus),
#: then at `..._MERGE` stores it - but on a bookkeeping whose `OVERRIDDEN` byte is set it keeps
#: `max(current, computed)` for each of base and hard cap - and at `..._FACTOR` scales the hard cap
#: by `GameInfo.CommandPointFactor / 100` outside a living-world session. `..._RETURN` is the
#: `pop ebx` epilogue every path that pushed `ebx` reaches. `edi` is the bookkeeping, `ebx` the
#: computed base and `esi` the computed hard cap throughout the merge.
COMMAND_POINTS_INIT = 0x006A7C86
COMMAND_POINTS_INIT_MERGE = 0x006A7DC7
COMMAND_POINTS_INIT_MERGE_BYTES = bytes.fromhex(
    "8a472c"  # mov al, [edi+0x2c]
    "84c0"  # test al, al
    "7405"  # je  store hard
    "3b7710"  # cmp esi, [edi+0x10]
    "7e03"  # jle skip
    "897710"  # mov [edi+0x10], esi
    "84c0"  # test al, al
    "7405"  # je  store base
    "3b5f04"  # cmp ebx, [edi+4]
    "7e03"  # jle skip
    "895f04"  # mov [edi+4], ebx
)
COMMAND_POINTS_INIT_FACTOR = 0x006A7DE2
COMMAND_POINTS_INIT_FACTOR_BYTES = bytes.fromhex("a12c89de00")  # mov eax, [THE_GAME_INFO]
COMMAND_POINTS_INIT_RETURN = 0x006A7E0A
COMMAND_POINTS_INIT_RETURN_BYTES = bytes.fromhex("5b5f5ec9c20800")  # pop ebx/edi/esi; leave; ret 8
#: `CommandPointBookkeeping::override(base, hardCap)`, `ret 8`: stores both and sets `OVERRIDDEN`.
#: Its one caller is script action 504, `OVERRIDE_PLAYER_COMMAND_POINTS` (case body `0x007CF2BF`,
#: worker `0x007BDC36`). `COMMAND_POINTS_RESET` (`0x006A8183`, from `Player::init`) clears the byte;
#: the bookkeeping's xfer saves it from version 7.
COMMAND_POINTS_OVERRIDE = 0x006A7ACD
COMMAND_POINTS_RESET = 0x006A8183
COMMAND_POINTS_BASE = 0x04
COMMAND_POINTS_HARD_CAP = 0x10
COMMAND_POINTS_OVERRIDDEN = 0x2C
#: `Player::killPlayer`: sets `PLAYER_IS_DEFEATED`, destroys what the player owns and then calls
#: `ThePlayerList->recomputeCommandPoints()` (`PLAYER_LIST_RECOMPUTE_COMMAND_POINTS`, vtable
#: `+0x40`, from `0x006ABF44` - its only caller), which re-runs `COMMAND_POINTS_INIT` for all
#: twenty players.
PLAYER_KILL_PLAYER = 0x006ABE7C
PLAYER_LIST_RECOMPUTE_COMMAND_POINTS = 0x006A84F3
#: The command-point accounting as objects are gained, lost and modified, and the leak in it. See
#: `docs/command-point-leak.md`.
PLAYER_ADD_COMMAND_POINTS_FOR_OBJECT = 0x006AA56D
PLAYER_REMOVE_COMMAND_POINTS_FOR_OBJECT = 0x006AA590
PLAYER_TRANSFER_COMMAND_POINTS_FOR_OBJECT = 0x006914B7
#: The spendable resource balance, and the spellbook points (`+0x24` spendable, `+0x1C` lifetime).
#: `+0x94` is what a player can afford; the `ScoreKeeper`'s money fields do not give it.
PLAYER_RESOURCES = 0x94
PLAYER_POWER_POINTS = 0x24
PLAYER_POWER_POINTS_TOTAL = 0x1C
#: The player's purchased sciences - a `std::vector<ScienceType>`, so `+0x310` begin, `+0x314` end.
#: Found from `LIVING_WORLD_BATTLE_SETUP`, which restores a living-world player's list onto its RTS
#: player through `PLAYER_SET_SCIENCES` at `0x008126CF`. Confirmed live: every seat in a
#: skirmish carries the four baseline sciences 30-33 and only the human seat had a fifth, 16.
PLAYER_SCIENCES = 0x310
#: `__thiscall(const std::vector<ScienceType> *)`, `ret 4`. Assigns the whole list, and **returns
#: without doing anything when the source is empty** (`0x006ACEFD`), so restoring nothing is safe.
#: It only reads `[src]` and `[src+4]`, which means a three-word header built on the stack over a
#: caller-owned buffer is a valid argument.
PLAYER_SET_SCIENCES = 0x006ACEF4
#: `__thiscall(UpgradeTemplate *, 2, 0)`, `ret 0xC`: the engine's "player completed this upgrade"
#: path (sets the bit and runs the effect). The loop at `0x008126E5` is the reference for replaying
#: a saved mask.
PLAYER_GRANT_UPGRADE = 0x006AEE22
#: `PlayerList::getLocalPlayer`. Not a plain getter: for an observer or defeated player it returns
#: the seat being watched, which is how the command bar follows a replay's watched player.
PLAYER_LIST_GET_LOCAL_PLAYER = 0x006A8839
#: The field that getter reads (`mov esi, [ecx+0x10]`), for a cave that wants the local player
#: without a call. The engine inlines the same read itself, e.g. at `0x00819CEA`. Note this is
#: the *raw* seat, so inlining the read skips the observer redirect above - which is right for a
#: question about who is at the keyboard and wrong for one about whose HUD is on screen.
PLAYER_LIST_LOCAL_PLAYER = 0x10
#: `Player::forEachTeamObject(fn, ctx)` (pure, stops early) and the engine's own per-object counter
#: callback, reused so a readout agrees with the deposit.
PLAYER_FOR_EACH_TEAM_OBJECT = 0x006ABABD
#: `Player::m_money` and `Money::m_amount`. The amount is unsigned and `deposit` has no clamp, so
#: charge a player through `MONEY_WITHDRAW`, never with a negative deposit.
PLAYER_MONEY = 0x90
#: The `PlayerTemplate` block key, one instruction before `PLAYER_TEMPLATE_BLOCK_KEY`, which
#: `command-point-upkeep` owns. Both hooks only copy `eax`.
PLAYER_TEMPLATE_BLOCK_KEY_EARLY = 0x005FE880
PLAYER_TEMPLATE_BLOCK_KEY_EARLY_BYTES = bytes.fromhex("8b0d103bde00")
PLAYER_TEMPLATE_BLOCK_KEY_EARLY_RESUME = 0x005FE886
#: `ThePlayerTemplateStore` and its `std::vector<PlayerTemplate>` (`+0x0C` begin, `+0x10` end, a
#: `PLAYER_TEMPLATE_SIZE` stride). A template's lobby identity is its index in that vector - the
#: `Int` a `GameSlot` holds - and `FIND_BY_INDEX(i)` (`__thiscall`, `ret 4`) resolves it to the
#: final override, or null past the end.
THE_PLAYER_TEMPLATE_STORE = 0x00DE3B10
PLAYER_TEMPLATE_STORE_BEGIN = 0x0C
PLAYER_TEMPLATE_STORE_END = 0x10
PLAYER_TEMPLATE_FIND_BY_INDEX = 0x005FCAD9
PLAYER_TEMPLATE_IS_OBSERVER = 0x150
PLAYER_TEMPLATE_PLAYABLE_SIDE = 0x151
#: `Evil`, a Bool (row 53 of the field table, `INI::parseBool`). `Player::initCommandPoints` reads
#: the same byte to pick the Good or Evil command-point pair.
PLAYER_TEMPLATE_EVIL = 0x1BC
#: `PlayerTemplate::getDisplayName`, which copy-constructs the `DisplayName` `UnicodeString` into
#: the caller's buffer - `__thiscall(UnicodeString *out)`, `ret 4`.
PLAYER_TEMPLATE_GET_DISPLAY_NAME = 0x0062772D
#: Where `PlayerTemplateStore::parse` writes the block's name key into the template it has just
#: parsed - the only two places the key and the finished fields meet. A new block is parsed into
#: a stack temporary that takes the key at `..._NEW_KEY` (`mov [ebp-0x1e4], edi`) before it is
#: copied into the vector; an override or a re-parse of an existing block has its key written
#: inside the branch and joins at `..._PARSED_JOIN` (`mov eax, [ThePlayerTemplateStore]`). `edi`
#: is the key at both.
PLAYER_TEMPLATE_PARSED_NEW_KEY = 0x005FE95C
PLAYER_TEMPLATE_PARSED_NEW_KEY_BYTES = bytes.fromhex("89bd1cfeffff")
PLAYER_TEMPLATE_PARSED_NEW_KEY_RESUME = 0x005FE962
PLAYER_TEMPLATE_PARSED_JOIN = 0x005FE900
PLAYER_TEMPLATE_PARSED_JOIN_BYTES = bytes.fromhex("a1103bde00")
PLAYER_TEMPLATE_PARSED_JOIN_RESUME = 0x005FE905
#: `Player::init(PlayerTemplate *)`, where a purse is seeded. The reset calls it with NULL on all
#: twenty slots, so the hook sits before the NULL branch, to both clear and seed.
PLAYER_INIT = 0x006B0239
PLAYER_INIT_ENTRY = 0x006B0243
PLAYER_INIT_ENTRY_BYTES = bytes.fromhex("83ec0c8b4508")
PLAYER_INIT_ENTRY_RESUME = 0x006B0249
# CommandButton, and the command-point gate a button press meets

#: `CommandButton`, the INI block the ControlBar allocates one of per `CommandButton` definition.
#: `operator new(0x2E0)` at `ControlBar::newCommandButton` (`0x0071C439`), then the constructor.
COMMAND_BUTTON_SIZE = 0x2E0
COMMAND_BUTTON_CTOR = 0x0075D516
#: `Command`, the `GUICOMMAND` the button dispatches on - `Object::doCommandButton`'s switch
#: reads exactly this (`0x00697086`). `3` is `UNIT_BUILD` and `46` is `REVIVE`
#: (`GUICOMMAND_REVIVE`), the two cases that reach production.
COMMAND_BUTTON_COMMAND = 0x14
#: `Object`, a handle to the button's `ThingTemplate` (parse fn `0x0073AD1F`). Read it through
#: `COMMAND_BUTTON_GET_THING_TEMPLATE`, never directly: the handle is followed to the template's
#: last override, and re-resolved by name when the template table was reloaded.
COMMAND_BUTTON_OBJECT = 0x20
#: `CommandButton::getThingTemplate()` - `__thiscall`, no arguments, plain `ret`; the resolved
#: `Object`, or null when the button names none. Keeps `esi`; clobbers `eax`, `ecx`, `edx`.
COMMAND_BUTTON_GET_THING_TEMPLATE = 0x0075D1DC
# push esi / lea esi, [ecx+0x20]
COMMAND_BUTTON_GET_THING_TEMPLATE_ENTRY = bytes.fromhex("568d7120")
#: The hero-ledger index the ControlBar's revive populate attached to a REVIVE button, -1 when
#: none. Written by both passes (`0x009440AC`, `0x00944340`), read by `Object::doCommandButton`'s
#: revive case (`0x006973D3`) and the tooltip builder (`0x008083FE`). It lives on the shared
#: button definition, so it describes whatever the local player last had selected.
COMMAND_BUTTON_REVIVE_INDEX = 0xC0
#: `AutoAbility` (`+0x10C`). The three bytes after it are padding, cleared for free by widening the
#: constructor's byte store to a dword. (`+0x103` is not padding.)
COMMAND_BUTTON_AUTO_ABILITY = 0x10C
COMMAND_BUTTON_FREE_OFFSET = 0x10D
COMMAND_BUTTON_CTOR_AUTO_ABILITY = 0x0075D688
COMMAND_BUTTON_CTOR_AUTO_ABILITY_BYTES = bytes.fromhex("889e0c010000")
#: `TriggerWhenReady` (`+0x12C`). The three bytes after it are padding, defaulted for free the same
#: way as `AutoAbility`'s.
COMMAND_BUTTON_TRIGGER_WHEN_READY = 0x12C
COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY = 0x0075D69C
COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY_BYTES = bytes.fromhex("889e2c010000")
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
#: The player's in-mission hero ledger - what the ControlBar offers as revivable, and what the
#: harvest copies onto the living-world player at `0x0078100E`. Entries are `0xE8` bytes with the
#: hero's `ThingTemplate` name at `+0xE4`; a dead hero's level and upgrades survive **here**, not on
#: his object, which is gone from the object list by the time the battle ends.
PLAYER_HERO_LEDGER_OFFSET = 0x758
#: `ThePlayerList::getNthPlayer(n)`, and the player count.
PLAYER_LIST_GET_NTH = 0x006A844E
PLAYER_LIST_COUNT_OFFSET = 0x14
#: The living-world player id a `Player` carries, or -1.
PLAYER_LIVING_WORLD_ID_OFFSET = 0x3CC
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
# The persistent left spellbook bar, not the purchase-science / spellstore window.
# Original game.dat, verified against the cache function and its update caller.
SPELLBOOK_UI_CACHE = 0x00930F96
SPELLBOOK_UI_CACHE_HOOK = 0x00930FDE
SPELLBOOK_UI_CACHE_PLAYER_CHANGED = 0x00930FE3
SPELLBOOK_UI_CACHE_REBUILD = 0x0093100C
SPELLBOOK_UI_CACHE_RETURN = 0x00931038
SPELLBOOK_UI_UPDATE_CACHE_CALL = 0x00931318
SPELLBOOK_UI_UPDATE_COMMAND_BUTTON = 0x0093134A
PLAYER_GET_SPELLBOOK_OBJECT = 0x006AD0F8
# The porter's upgrade delivery - `GiveUpgradeUpdate`, both its targeted (`SPECIAL_GIVE_UPGRADE`)
# and its auto-deliver (`SPECIAL_GIVE_UPGRADE_NEAREST`) form. Derived in `docs/give-upgrade-all.md`,
# which is also where the one-upgrade-per-porter limit these describe is laid out.

# `UpgradeCenter::firstSetIn(mask)`: walks the `UpgradeTemplate` list at `TheUpgradeCenter+0x0C`
# through `+0x64` and returns the first template whose `+0x38` index is set in the caller's bitset.
# Thirteen callers; `GiveUpgradeUpdate` is three of them. The list is newest-first, so "first"
# means the upgrade declared last in ini load order.
UPGRADE_FIRST_SET = 0x0066F468
UPGRADE_FIRST_SET_ENTRY = bytes.fromhex("8b410c56eb1c")
UPGRADE_CENTER_LIST = 0x0C
UPGRADE_TEMPLATE_NEXT = 0x64
# `GiveUpgradeUpdate::canGiveTo(target)` - the whole validity predicate, and the only thing
# standing between the cursor and a target once relationship and `KINDOF IMMOBILE` have passed.
# The entry is the six-byte hook window (`push esi` / `mov esi, ecx` / `mov eax, [esi+8]`); the
# body is the remaining 83 bytes, anchored so a build whose predicate differs fails before
# anything is replaced.
GIVE_UPGRADE_CAN_GIVE = 0x0089FE64
GIVE_UPGRADE_CAN_GIVE_ENTRY = bytes.fromhex("568bf18b4608")
GIVE_UPGRADE_CAN_GIVE_BODY = 0x0089FE6A
GIVE_UPGRADE_CAN_GIVE_BODY_BYTES = bytes.fromhex(
    "8b0da045de0057058c02000050e8ecf5dcff8bf885ff74348b4c240c83b97c02000000"
    "7419518bcee8e0feffff85c0741b8b10578bc8ff92ac000000eb0657e8664adfff84c0"
    "7404b001eb0232c05f5ec20400"
)
# `GiveUpgradeUpdate::producerHordeIface(target)`: `findObjectByID(target->+0x78)`, then that
# object's contain module and its horde interface. How a picked battalion *member* is resolved
# back to the horde that is the real recipient.
GIVE_UPGRADE_PRODUCER_HORDE_IFACE = 0x0089FD77
GIVE_UPGRADE_PRODUCER_HORDE_IFACE_ENTRY = bytes.fromhex("8b44240485c0741c")
# Inside `GiveUpgradeUpdate::trigger` (`0x008A01B2`). `TRIGGER_PICK` is its call to
# `UPGRADE_FIRST_SET`, the hook window; the other three are the anchors that pin the registers the
# replacement reads - `ebx` the owning porter, `edi` the target, `esi` the module.
GIVE_UPGRADE_TRIGGER_OWNER = 0x008A01D8
GIVE_UPGRADE_TRIGGER_OWNER_BYTES = bytes.fromhex("8b5e08")
GIVE_UPGRADE_TRIGGER_PICK = 0x008A021B
GIVE_UPGRADE_TRIGGER_PICK_BYTES = bytes.fromhex("e848f2dcff")
GIVE_UPGRADE_TRIGGER_TARGET_ARM = 0x008A022B
GIVE_UPGRADE_TRIGGER_TARGET_ARM_BYTES = bytes.fromhex("8b4704f680150100002074098bcf")
GIVE_UPGRADE_TRIGGER_MEMBER_ARM = 0x008A0240
GIVE_UPGRADE_TRIGGER_MEMBER_ARM_BYTES = bytes.fromhex("578bcee82ffbffff")
# Inside the `DeliverUpgrade = Yes` search (`0x0089FEC7`), which builds a filter functor on the
# stack - `{vtable 0x00C67A88, 0, upgrade}` - and scans for the nearest object it accepts.
# `SEARCH_OWNER_LOAD` is what puts the porter in `esi`; `SEARCH_FILTER_OWNER` is the store that
# zeroes the functor's dead `+4` slot, which is where the owner is parked instead;
# `SEARCH_FILTER_VTABLE` pins the functor's base, and therefore which frame slot `+4` is.
GIVE_UPGRADE_SEARCH_OWNER_LOAD = 0x0089FEEB
GIVE_UPGRADE_SEARCH_OWNER_LOAD_BYTES = bytes.fromhex("8b7708")
GIVE_UPGRADE_SEARCH_FILTER_OWNER = 0x0089FF17
GIVE_UPGRADE_SEARCH_FILTER_OWNER_BYTES = bytes.fromhex("895ddc")
GIVE_UPGRADE_SEARCH_FILTER_VTABLE = 0x0089FF1A
GIVE_UPGRADE_SEARCH_FILTER_VTABLE_BYTES = bytes.fromhex("c745d8887ac600")
# `UpgradeFilter::operator()(candidate)` - `canAcceptUpgrade(+8) && !hasUpgrade(+8)`. Private to
# `GiveUpgradeUpdate`: its vtable is built at exactly two sites, both in that class, and nothing
# else branches here. The entry is the five-byte hook window, the body the remaining 40 bytes.
UPGRADE_FILTER_PREDICATE = 0x00660E04
UPGRADE_FILTER_PREDICATE_ENTRY = bytes.fromhex("568bf1ff76")
UPGRADE_FILTER_BODY = 0x00660E09
UPGRADE_FILTER_BODY_BYTES = bytes.fromhex(
    "088b4c240ce8013b030084c07414ff76088b4c240ce8fe05030084c07504fec0eb0232c05ec20400"
)
UPGRADE_FILTER_OWNER_SLOT = 0x04
UPGRADE_FILTER_UPGRADE_SLOT = 0x08
#: `TheExperienceLevelSystem` and the lookup resolving a template plus a level index to its
#: `ExperienceLevel`, as `SCRIPT_ACTIONS_CREATE_UNIT_REVIVAL_ENTRY` uses it.
THE_EXPERIENCE_LEVEL_SYSTEM = 0x00DE4704
PLAYER_LIST_PLAYER_FROM_INDEX = 0x006A85EE
PLAYER_NAME_KEY = 0x50
#: A `Player`'s default team - what `ARMY_RECORD_CREATE_OBJECT` hands to `THING_FACTORY_NEW_OBJECT`,
#: since objects are owned by a `Team` and not by a `Player`. `PLAYER_TEAM_LIST` is the separate
#: list `PLAYER_FOR_EACH_TEAM_OBJECT` walks.
PLAYER_DEFAULT_TEAM = 0x30C
PLAYER_TEAM_LIST = 0x34C
#: A special power's cooldown: an absolute logic frame, unlike a script timer. Anything restarting
#: the frame counter must rebase it.
SPECIAL_POWER_READY_FRAME = 0x08
SPECIAL_POWER_START_RECHARGE = 0x00896F70
#: `UpgradeMaskType::any()` - `__thiscall(ecx = mask) -> al`, no arguments - and
#: `testForAny(const UpgradeMaskType &)` - `__thiscall`, `ret 4`. Both are 36-dword loops that
#: touch only `eax`/`ecx`/`edx` and (in `testForAny`) a saved `esi`.
UPGRADE_MASK_ANY = 0x00444DCE
UPGRADE_MASK_TEST_ANY = 0x008097D6
# Confirmed ROTWK XP dispatch and interface query; docs/share-experience-all.md.
SHARE_EXPERIENCE_DISPATCH = 0x00695588
SHARE_EXPERIENCE_DISPATCH_BYTES = bytes.fromhex(
    "56 E8 CD DA 1E 00 85 C0 59 74 0D D9 45 08 8B 10 51 8B C8 D9 1C 24 FF 12"
)
SHARE_EXPERIENCE_QUERY_SLOT = 0xA4
# ROTWK ShareExperience ABI and exact stock windows; docs/share-experience-all.md.
SHARE_EXPERIENCE = 0x008832F0
SHARE_EXPERIENCE_INTERFACE = 0x20
SHARE_EXPERIENCE_MODULEDATA = 0x04
SHARE_EXPERIENCE_OWNER = 0x08
SHARE_EXPERIENCE_SIZE = 0x24
SHARE_EXPERIENCE_MODULEDATA_SIZE = 0x18
SHARE_EXPERIENCE_RADIUS = 0x08
SHARE_EXPERIENCE_DROPOFF = 0x0C
SHARE_EXPERIENCE_PERCENTAGE = 0x10
# ObjectFilter-like field; exact EA type is not established.
SHARE_EXPERIENCE_TARGET_FILTER = 0x14
SHARE_EXPERIENCE_GET_DROPOFF = 0x0088325B
SHARE_EXPERIENCE_GET_DROPOFF_RESUME = 0x00883261
SHARE_EXPERIENCE_GET_DROPOFF_BYTES = bytes.fromhex(
    "558bec83ec0c568b7104f30f10460c0f2e050819bd009ff6c4447a6e"
    "8b450cf30f104038f30f10483cf30f1050408b4508f30f5c00f30f5c4804"
    "f30f5c50088d4df4f30f1145f4f30f114df8f30f1155fce84422b8ff"
    "d95d0cf30f104d0cf30f5e4e08f30f10050819bd00f30f5cc10f2f0594b5c100"
    "f30f11450c7205d9450ceb0ed90594b5c100eb06d9050819bd005ec9c20800"
)
SHARE_EXPERIENCE_CALC = 0x00883453
SHARE_EXPERIENCE_CALC_RESUME = 0x00883494
SHARE_EXPERIENCE_CALC_BYTES = bytes.fromhex(
    "d945088b4decd84f10568d45bc5083c1e0d95d08e8effdffffd84d08d95d08"
    "d9eed94508dff1ddd87617d945086a006a016a016a01518b4de8d91c24e89fa3f1ff"
)
SHARE_EXPERIENCE_LOOP = 0x0088341F
SHARE_EXPERIENCE_LOOP_BACK = 0x008834A0
#: `CommandButton::getTextLabel` - `__thiscall`, the runtime override at `+0x7c` when it is set,
#: otherwise the `TextLabel` vector at `+0x58` indexed by the button's current command range.
COMMAND_BUTTON_GET_TEXT_LABEL = 0x0075CE47
#: `CommandSet::getCommandButton(Int slot)` - `__thiscall`, `ret 4`, plain `[this+slot*4+0x14]`
#: with an override hook in front. It is **not** bounds-checked, so a caller supplies the bound;
#: the spellbook bar's own update loop uses `SPELLBOOK_UI_SLOT_LIMIT` (`0x00931331`).
COMMAND_SET_GET_COMMAND_BUTTON = 0x0080C837
SPELLBOOK_UI_SLOT_LIMIT = 0x18
#: That exemption, as an anchor: `cmp eax, 0x26` on the button's `Command` followed by the jump
#: into the arm that does not ask for a selection.
DO_COMMAND_SPELL_BOOK_EXEMPTION = 0x00940462

# Derived in `docs/player-upgrade-discount.md`. `UpgradeTemplate::calcCostToBuild` -
# `__thiscall`, stack args `(Player *, Object *)`, `ret 8`, the price in `eax`. Every place an
# upgrade's price is shown, checked or charged calls it.
UPGRADE_CALC_COST_TO_BUILD = 0x0066F2C8
# Its discount block, from the `Type` test to the `fadd` that turns the discount sum into a
# multiplier. `esi` is the `UpgradeTemplate` until `add esi, 8` at `0x0066F37D`, and after it the
# name copied as the discount call's argument.
UPGRADE_DISCOUNT_GATE = 0x0066F363
UPGRADE_DISCOUNT_GATE_BYTES = bytes.fromhex(
    "837e0401f30f10050819bd00752b807e790075255189650c8bcc83c60856e8aa6bdcff8b4d08e83df40300"
)
# `jne` past the discount when `Type` (`+0x04`) is not 1 (`OBJECT`; 0 is `PLAYER`).
UPGRADE_DISCOUNT_TYPE_BRANCH = 0x0066F36F
UPGRADE_DISCOUNT_TYPE_BRANCH_BYTES = bytes.fromhex("752b")
# `call PLAYER_GET_UPGRADE_DISCOUNT`, `ecx` = the `Player`, the upgrade's name by value.
UPGRADE_DISCOUNT_CALL = 0x0066F389
UPGRADE_DISCOUNT_CALL_BYTES = bytes.fromhex("e83df40300")
# `Player::getUpgradeDiscount(AsciiString name)` - `__thiscall`, `ret 4`, destroys its argument,
# returns in `st0` the sum of every `UpgradeDiscount = Yes` entry that applies to `name`.
PLAYER_GET_UPGRADE_DISCOUNT = 0x006AE7CB
PLAYER_GET_UPGRADE_DISCOUNT_BODY = bytes.fromhex(
    "558bec510f57c056578bf98bb7d0030000f30f1145fceb148d4508508bcee850f2ffffd845fc83c624d95dfc"
    "3bb7d403000075e48d4d08e84975d8ffd945fc5f5ec9c20400"
)
# The `Player`'s vector of those entries, begin/end at `+0x3D0`/`+0x3D4`, `0x24` bytes each: the
# `ApplyToTheseUpgrades` list begin/end at `+0x14`/`+0x18` (empty = every upgrade) and the
# `Percentage` at `+0x20`.
PLAYER_UPGRADE_DISCOUNTS = 0x3D0
# One entry's share for a name - `__thiscall` on the entry, `(const AsciiString *)`, `ret 4`,
# `st0`: its `Percentage` if the list is empty or names it, else `0.0`.
UPGRADE_DISCOUNT_ENTRY_VALUE = 0x006ADA3E
UPGRADE_DISCOUNT_ENTRY_VALUE_ENTRY = bytes.fromhex("568bf1")
