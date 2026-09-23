"""The War of the Ring (living world): campaigns, armies, regions, acts, battles."""

from __future__ import annotations

__all__ = [
    "ACT_CTOR",
    "ACT_DTOR",
    "ACT_FORCE_BATTLE_APPEND",
    "ACT_FORCE_BATTLE_EXEC",
    "ACT_FORCE_BATTLE_PARSE",
    "ACT_FORCE_BATTLE_POSITION_CALL",
    "ACT_FORCE_BATTLE_POSITION_CALL_BYTES",
    "ACT_FORCE_BATTLE_REGION_CALL",
    "ACT_FORCE_BATTLE_REGION_CALL_BYTES",
    "ACT_NAME_OFFSET",
    "ACT_PARSE",
    "ACT_RUN",
    "ACT_RUN_PASS9_CALL",
    "ACT_RUN_PASS9_CALL_BYTES",
    "ACT_SET_PLAYER_CONTROL_APPEND",
    "ACT_SET_PLAYER_CONTROL_EXEC",
    "ACT_SET_PLAYER_CONTROL_PARSE",
    "ACT_SIZE",
    "ACT_SPAWN_ARMY_AT_POSITION_CALL",
    "ACT_SPAWN_ARMY_AT_POSITION_CALL_BYTES",
    "ACT_SPAWN_ARMY_EXEC",
    "ACT_SPAWN_ARMY_PARSE",
    "ACT_SPAWN_ARMY_PARSE_FIELDS_CALL",
    "ACT_SPAWN_ARMY_PARSE_FIELDS_CALL_BYTES",
    "ACT_SPAWN_ARMY_TABLE_PUSH_SITE",
    "ACT_SPAWN_ARMY_TABLE_PUSH_SITE_BYTES",
    "ACT_VERB_ROW_COUNT",
    "ACT_VERB_ROW_SIZE",
    "ACT_VERB_TABLE",
    "ACT_VERB_TABLE_BYTES",
    "ACT_VERB_TABLE_PUSH",
    "ACT_VERB_TABLE_PUSH_SITE",
    "ACT_VERB_TABLE_PUSH_SITE_BYTES",
    "ARMY_DEFINITION_FIELD_TABLE",
    "ARMY_DEFINITION_FIELD_TABLE_REFS",
    "ARMY_DEFINITION_FIELD_TABLE_REF_OPCODES",
    "ARMY_DEFINITION_HERO_BUILD_ORDER",
    "ARMY_ENTRY_CLONE_AND_APPEND",
    "ARMY_ENTRY_COPY",
    "ARMY_ENTRY_DEFAULT_OFFSET",
    "ARMY_ENTRY_DEFAULT_TABLE",
    "ARMY_ENTRY_DEFAULT_TABLE_BYTES",
    "ARMY_ENTRY_DEFAULT_TABLE_PUSH",
    "ARMY_ENTRY_DEFAULT_TABLE_PUSH_BYTES",
    "ARMY_ENTRY_FIELD_TABLE",
    "ARMY_ENTRY_FIND_TEMPLATE",
    "ARMY_ENTRY_PARSE",
    "ARMY_ENTRY_PARSE_FIELDS",
    "ARMY_ENTRY_PARSE_FIELDS_CALL",
    "ARMY_ENTRY_PARSE_FIELDS_CALL_BYTES",
    "ARMY_ENTRY_QUANTITY_OFFSET",
    "ARMY_ENTRY_RECORD_CTOR",
    "ARMY_ENTRY_REFCOUNT_COUNT",
    "ARMY_ENTRY_REFCOUNT_OFFSET",
    "ARMY_ENTRY_SCRATCH_OFFSET",
    "ARMY_ENTRY_TEMPLATE_OFFSET",
    "ARMY_HERO_TEMPLATE_OFFSET",
    "ARMY_IS_EMPTY_PLACEHOLDER",
    "ARMY_RECORD_CREATE_OBJECT",
    "ARMY_RECORD_HEALTH",
    "ARMY_RECORD_SIZE",
    "ARMY_RECORD_SPAWN",
    "ARMY_RECORD_UPGRADE_LIST",
    "ARMY_SCRIPTING_NAME_OFFSET",
    "ARMY_SET_POSITION",
    "ARMY_UPDATE_REGION",
    "CAMPAIGN_ADVANCE_GATE",
    "CAMPAIGN_LIST_PREDICATE",
    "CAMPAIGN_NAME_BIND",
    "CAMPAIGN_NAME_BIND_BYTES",
    "CAMPAIGN_NAME_STATIC",
    "CAMPAIGN_NAME_STATIC_GUARD",
    "CAMPAIGN_SELECT_GATE",
    "HERO_LEDGER_ENTRIES_BEGIN",
    "HERO_LEDGER_ENTRIES_END",
    "HERO_LEDGER_ENTRY_STRIDE",
    "HERO_LEDGER_FIND_TEMPLATE",
    "HERO_LEDGER_NAME_OFFSET",
    "HERO_LEDGER_TO_RECORD",
    "LIVE_CAMPAIGN_MODE_OFFSET",
    "LIVING_WORLD_ADD_MOVIE_EVENT",
    "LIVING_WORLD_ADVANCE_PENDING_OFFSET",
    "LIVING_WORLD_ADVANCE_TURN_PHASE",
    "LIVING_WORLD_ARMY_ADD_RECORD",
    "LIVING_WORLD_ARMY_DEPLOY",
    "LIVING_WORLD_ARMY_DESTROY",
    "LIVING_WORLD_ARMY_ERASE_RECORD",
    "LIVING_WORLD_ARMY_GET_RECORD",
    "LIVING_WORLD_ARMY_HERO_TEMPLATE_OFFSET",
    "LIVING_WORLD_ARMY_OWNER_ID",
    "LIVING_WORLD_ARMY_QUEUE_RETREAT",
    "LIVING_WORLD_ARMY_RECORDS_BEGIN",
    "LIVING_WORLD_ARMY_RECORDS_END",
    "LIVING_WORLD_ARMY_RECORD_SPAWN_INTO",
    "LIVING_WORLD_ARMY_RECORD_STRIDE",
    "LIVING_WORLD_ARMY_ROSTER_ID",
    "LIVING_WORLD_ARMY_ROSTER_OFFSET",
    "LIVING_WORLD_ARMY_ROSTER_TEAM",
    "LIVING_WORLD_ARMY_SCRIPTING_NAME_OFFSET",
    "LIVING_WORLD_ARMY_SEED_FROM_TEMPLATE",
    "LIVING_WORLD_ARMY_STRENGTH",
    "LIVING_WORLD_ARMY_SURVIVAL_THRESHOLD_OFFSET",
    "LIVING_WORLD_ASSIGN_OBJECT_TO_ARMY",
    "LIVING_WORLD_ASSIGN_OBJECT_TO_ARMY_THUNK",
    "LIVING_WORLD_BATTLE_ARMY_IDS_BEGIN",
    "LIVING_WORLD_BATTLE_ARMY_IDS_END",
    "LIVING_WORLD_BATTLE_BRIDGE_OFFSET",
    "LIVING_WORLD_BATTLE_CTOR",
    "LIVING_WORLD_BATTLE_END",
    "LIVING_WORLD_BATTLE_HARVEST",
    "LIVING_WORLD_BATTLE_HARVEST_CALL",
    "LIVING_WORLD_BATTLE_HARVEST_CALL_BYTES",
    "LIVING_WORLD_BATTLE_MEMBERS_BEGIN",
    "LIVING_WORLD_BATTLE_MEMBERS_END",
    "LIVING_WORLD_BATTLE_MEMBER_STRIDE",
    "LIVING_WORLD_BATTLE_PRIMARY_ARMY_ID",
    "LIVING_WORLD_BATTLE_REGION",
    "LIVING_WORLD_BATTLE_SETUP",
    "LIVING_WORLD_BATTLE_SETUP_CALL",
    "LIVING_WORLD_BATTLE_SETUP_CALL_BYTES",
    "LIVING_WORLD_BATTLE_SETUP_UPGRADE_LOOP",
    "LIVING_WORLD_BATTLE_SIDES_BEGIN",
    "LIVING_WORLD_BATTLE_SIDES_END",
    "LIVING_WORLD_BATTLE_SIDE_STRIDE",
    "LIVING_WORLD_CAMPAIGN_ADVANCE_ACT",
    "LIVING_WORLD_CAMPAIGN_MANAGER_ADVANCE_ACT",
    "LIVING_WORLD_CAMPAIGN_MANAGER_CAMPAIGNS_BEGIN",
    "LIVING_WORLD_CAMPAIGN_MANAGER_CAMPAIGNS_END",
    "LIVING_WORLD_CAMPAIGN_MANAGER_CURRENT",
    "LIVING_WORLD_CAMPAIGN_MANAGER_CURRENT_READ",
    "LIVING_WORLD_CAMPAIGN_MANAGER_CURRENT_READ_BYTES",
    "LIVING_WORLD_CAMPAIGN_SCENARIO",
    "LIVING_WORLD_CAMPAIGN_SCENARIO_READ",
    "LIVING_WORLD_CAMPAIGN_SCENARIO_READ_BYTES",
    "LIVING_WORLD_CAN_ADVANCE_TURN_PHASE",
    "LIVING_WORLD_CONFLICT_PASS",
    "LIVING_WORLD_COUNT_ARMY_OWNERS",
    "LIVING_WORLD_COUNT_LIVE_ARMY_OWNERS",
    "LIVING_WORLD_CURRENT_REGION",
    "LIVING_WORLD_DEPLOY_AT_BATTLE_START",
    "LIVING_WORLD_END_TURN",
    "LIVING_WORLD_FIND_ARMY_BY_ID",
    "LIVING_WORLD_FIND_ARMY_BY_NAME",
    "LIVING_WORLD_FIND_ARMY_ROSTER",
    "LIVING_WORLD_FIND_PLAYER_ARMY_BY_NAME",
    "LIVING_WORLD_FIND_PLAYER_BY_ID",
    "LIVING_WORLD_FORCE_BATTLE_STUB",
    "LIVING_WORLD_HARVEST_ARMY_ID_TEST",
    "LIVING_WORLD_HARVEST_ARMY_ID_TEST_BYTES",
    "LIVING_WORLD_HERO_KILLED_RESOLVE",
    "LIVING_WORLD_IS_MESSAGE_BOX_SHOWING",
    "LIVING_WORLD_LEDGER_TO_PLAYER",
    "LIVING_WORLD_LOGIC_BATTLE_STORE",
    "LIVING_WORLD_LOGIC_CURRENT_REGION_ID",
    "LIVING_WORLD_MERGE_INTO_REGION_ARMY",
    "LIVING_WORLD_MESSAGE_BOX_BODY",
    "LIVING_WORLD_MESSAGE_BOX_CURRENT",
    "LIVING_WORLD_MESSAGE_BOX_FINISHED",
    "LIVING_WORLD_MESSAGE_BOX_ON_EVENT",
    "LIVING_WORLD_MESSAGE_BOX_QUEUE_BEGIN",
    "LIVING_WORLD_MESSAGE_BOX_QUEUE_END",
    "LIVING_WORLD_MESSAGE_BOX_SHOW",
    "LIVING_WORLD_MESSAGE_BOX_SHOWING",
    "LIVING_WORLD_MESSAGE_BOX_TITLE",
    "LIVING_WORLD_OVERRIDE_OFFSET",
    "LIVING_WORLD_OVERRIDE_ROW",
    "LIVING_WORLD_PLAYERS_BEGIN",
    "LIVING_WORLD_PLAYERS_END",
    "LIVING_WORLD_PLAYER_ARMIES_BEGIN",
    "LIVING_WORLD_PLAYER_ARMIES_END",
    "LIVING_WORLD_PLAYER_ARMY_ASSIGN",
    "LIVING_WORLD_PLAYER_ARMY_SIZE",
    "LIVING_WORLD_PLAYER_ARMY_TABLE",
    "LIVING_WORLD_PLAYER_ID",
    "LIVING_WORLD_PUMP_MESSAGE_BOXES",
    "LIVING_WORLD_PUMP_MESSAGE_BOXES_CALL",
    "LIVING_WORLD_REGION_ID",
    "LIVING_WORLD_REGION_OWNER",
    "LIVING_WORLD_REMOVE_MOVIE_EVENT",
    "LIVING_WORLD_REQUEST_ADVANCE_TURN_PHASE",
    "LIVING_WORLD_ROSTER_IN_BATTLE",
    "LIVING_WORLD_SHOW_QUEUE_FRONT",
    "LIVING_WORLD_SPAWN_ARMY",
    "LIVING_WORLD_STORE_BATTLES_BEGIN",
    "LIVING_WORLD_STORE_BATTLES_END",
    "LIVING_WORLD_TICK_GATE",
    "LIVING_WORLD_TURN_NUMBER_OFFSET",
    "LIVING_WORLD_TURN_PHASE_BOX_BRAKE",
    "LIVING_WORLD_TURN_PHASE_DRAIN",
    "LIVING_WORLD_TURN_PHASE_OFFSET",
    "LIVING_WORLD_UPDATE",
    "LIVING_WORLD_UPDATE_TURN_PHASE",
    "REGION_DEFENDS_AGAINST",
    "REGION_ENABLED",
    "REGION_IS_DEFENDED",
    "REGION_STORE_BATTLE_POINT",
    "REGION_STORE_CREATE_BATTLE",
    "REGION_STORE_DETECT_CONFLICTS",
    "REGION_STORE_FIND_BATTLE",
    "REGION_STORE_FIND_REGION_BY_NAME",
    "REGION_STORE_REGION_AT",
    "SCENARIO_ALLOC",
    "SCENARIO_ALLOC_BYTES",
    "SCENARIO_CTOR_HISTORICAL",
    "SCENARIO_CTOR_HISTORICAL_BYTES",
    "SCENARIO_CTOR_USE_MP_RULES",
    "SCENARIO_CTOR_USE_MP_RULES_BYTES",
    "SCENARIO_CTOR_ZERO",
    "SCENARIO_CTOR_ZERO_BYTES",
    "SCENARIO_DISABLED_FACTIONS_BEGIN",
    "SCENARIO_DISABLED_FACTIONS_END",
    "SCENARIO_FACTION_CALL_SITES",
    "SCENARIO_FIELD_TABLE",
    "SCENARIO_FIELD_TABLE_REFS",
    "SCENARIO_FIELD_TABLE_REF_OPCODES",
    "SCENARIO_FREE_OFFSET",
    "SCENARIO_HAS_DISABLED_FACTIONS",
    "SCENARIO_HISTORICAL",
    "SCENARIO_IS_FACTION_ENABLED",
    "SCENARIO_IS_FACTION_ENABLED_ENTRY",
    "SCENARIO_SIZE",
    "SCENARIO_USE_MP_RULES",
    "SPAWN_ARMY_FIELD_ROW_COUNT",
    "SPAWN_ARMY_FIELD_TABLE",
    "SPAWN_ARMY_FIELD_TABLE_BYTES",
    "SPAWN_ARMY_POSITION_OFFSET",
    "SPAWN_ARMY_SCRIPTING_NAME_OFFSET",
    "STRATEGIC_MESSAGE_BOX_ADD",
    "STRATEGIC_MESSAGE_BOX_ADD_THUNK",
    "STRATEGIC_MESSAGE_BOX_APPLY_GUARD",
    "STRATEGIC_MESSAGE_BOX_APPLY_TO_APT",
    "STRATEGIC_MESSAGE_BOX_HIDE",
    "STRATEGIC_MESSAGE_BOX_HIDE_NOTIFY",
    "STRATEGIC_MESSAGE_BOX_RESHOW",
    "STRATEGIC_MESSAGE_BOX_RESHOW_OVERLAYS",
    "STRATEGIC_MESSAGE_BOX_SHOW",
    "THE_GENERAL_MESSAGE_BOX",
    "THE_LIVING_WORLD_CAMPAIGN_MANAGER",
    "THE_LIVING_WORLD_LOGIC",
    "THE_STRATEGIC_MESSAGE_BOX",
]

# `HeroBuildOrder` and the skirmish AI's hero builder, which picks an entry at random with no clock
# anywhere on the path. See `docs/ai-hero-build-delay.md`.

# The `ArmyDefinition` field-parse table, and the two instructions that name it - a getter
# (`mov eax, imm32`) and the `parseFields` call (`push imm32`). Resolved *through the references*
# rather than from the constant, so a patch composes with anything that rebuilt the table first.
ARMY_DEFINITION_FIELD_TABLE = 0x00C52B40
ARMY_DEFINITION_FIELD_TABLE_REFS = (0x00830103, 0x008302A0)
ARMY_DEFINITION_FIELD_TABLE_REF_OPCODES = (0xB8, 0x68)
# `HeroBuildOrder`'s `store + offset` inside the 0xEC-byte `ArmyDefinition`. The row's parse
# function is `INI_PARSE_STRING_LIST` and its `userData` is null.
ARMY_DEFINITION_HERO_BUILD_ORDER = 0x8C
LIVING_WORLD_BATTLE_SETUP_UPGRADE_LOOP = 0x008126E5
#: The static `AsciiString` the campaign start passes to `startLinearCampaign`, and its magic-static
#: guard. Setting both first substitutes the campaign name.
CAMPAIGN_NAME_STATIC = 0x00DEA35C
CAMPAIGN_NAME_STATIC_GUARD = 0x00DEA360
CAMPAIGN_NAME_BIND = 0x0091BE96
CAMPAIGN_NAME_BIND_BYTES = bytes.fromhex("f60560a3de000156be5ca3de007525")
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
# The War of the Ring battle boundary (`docs/living-campaign/hero-permadeath.md`). An army's force
# container is `army+0x78`; a record is `0xD8` bytes, the same object an `ArmyEntry` parses into.

#: `TheGameLogic`'s post-battle handler. Its first call hands the object list to the harvest.
LIVING_WORLD_BATTLE_END = 0x00626662
#: Walks the object list and records every **survivor** whose owner is a living-world player, whose
#: template is `KindOf = ARMY_SUMMARY` (`tmpl+0x118` bit 0) and which carries an army id at
#: `obj+0x47C`. Units that died are never written down; that is the whole of hero permadeath.
LIVING_WORLD_BATTLE_HARVEST = 0x00811E1F
#: Appends one record to a force container's `+0x40` vector. Shared by the harvest and `ArmyEntry`.
LIVING_WORLD_ARMY_ADD_RECORD = 0x00811951
#: Spawns an army's records into a battle. Reads `SurvivalThreshhold` and skips `Default` records
#: unless the army's live strength has fallen below it.
LIVING_WORLD_ARMY_DEPLOY = 0x00812119
#: Sums `Quantity` over the records with `Default = No` - the army's strength for the threshold.
LIVING_WORLD_ARMY_STRENGTH = 0x0080FA21
#: Destroy an army: sets `army+0x75` and queues it on `TheLivingWorldLogic+0x118`.
LIVING_WORLD_ARMY_DESTROY = 0x006B9679
#: Queue a hero army for retreat on `TheLivingWorldLogic+0x10C`.
LIVING_WORLD_ARMY_QUEUE_RETREAT = 0x006B921E
#: Drains the retreat queue. A hero army with no adjacent friendly region raises
#: `LW:HeroKilledTitle` and is destroyed.
LIVING_WORLD_HERO_KILLED_RESOLVE = 0x006BABA8
#: `LivingWorldPlayerArmy`: `Name` `+0x18`, `Color` `+0x24`, `NightColor` `+0x28`, the records at
#: `+0x40`, `SurvivalThreshhold` `+0x60`, `DisplayNameTag` `+0x64`.
LIVING_WORLD_PLAYER_ARMY_TABLE = 0x00C4FB58
#: The unit count below which `Default` records deploy anyway. Set nowhere in Edain or BFME1.
LIVING_WORLD_ARMY_SURVIVAL_THRESHOLD_OFFSET = 0x60
#: `HeroTemplateName` on the live army - the engine's "is this a hero army" discriminator.
LIVING_WORLD_ARMY_HERO_TEMPLATE_OFFSET = 0x18
#: Allocates the `0xD8`-byte record an `ArmyEntry` becomes, then appends it.
ARMY_ENTRY_PARSE = 0x00811CF9
#: Copy-constructs a record. `0x0081205B` wraps it as clone-and-append on a roster container -
#: which has no direct callers, so confirm it before a cave depends on it.
ARMY_ENTRY_COPY = 0x0081019B
ARMY_ENTRY_CLONE_AND_APPEND = 0x0081205B
ARMY_ENTRY_FIELD_TABLE = 0x00C2F470  # ThingTemplate -> +0x04, Quantity -> +0xA0
#: The second table the same parser walks, carrying the undocumented `Default` bool.
ARMY_ENTRY_DEFAULT_TABLE = 0x00C4FA94
#: Its stock bytes, terminator included - asserted before the table is relocated.
ARMY_ENTRY_DEFAULT_TABLE_BYTES = bytes.fromhex(
    "a0d2bd0058e5420000000000d500000000000000000000000000000000000000"
)
ARMY_ENTRY_QUANTITY_OFFSET = 0xA0
ARMY_ENTRY_DEFAULT_OFFSET = 0xD5
#: The record's `ThingTemplate` name, compared with `ASCII_STRING_COMPARE`.
ARMY_ENTRY_TEMPLATE_OFFSET = 0x04
#: Read the i-th record out of a roster container, and erase the i-th.
LIVING_WORLD_ARMY_GET_RECORD = 0x0080F590
LIVING_WORLD_ARMY_ERASE_RECORD = 0x00810840
# The campaign `Act` (`0xB8` bytes, no room for a new verb's list) and its verb table. See
# `docs/living-campaign/merge-player-army.md`.

#: The 15-row Act verb table, and the single `push` immediate that names it. Relocating the table
#: to a cave to append a verb is that one dword.
ACT_VERB_TABLE = 0x00C84030
ACT_VERB_TABLE_PUSH = 0x0096E7F3
#: The whole `push 0x00C84030`, so the site is asserted as an instruction rather than as four
#: loose bytes that could be anything.
ACT_VERB_TABLE_PUSH_SITE = 0x0096E7F2
ACT_VERB_TABLE_PUSH_SITE_BYTES = b"\x68\x30\x40\xc8\x00"
ACT_VERB_ROW_SIZE = 0x10
ACT_VERB_ROW_COUNT = 15
#: The stock table, terminator included - 15 `{name, parse, userData, offset}` rows. Asserted
#: before it is copied into the cave, because the copy is only as good as what it copies.
ACT_VERB_TABLE_BYTES = bytes.fromhex(
    "e43fc800805a8e000000000000000000d83fc800e05b8e000000000000000000"
    "58b0c100ce788e0000000000000000002085c70006618e000000000000000000"
    "4888c700f25c8e000000000000000000c43fc8009ee542000000000044000000"
    "b83fc8005eee42000000000050000000ac3fc8009c588e000000000000000000"
    "9c3fc80081798e000000000000000000903fc800635e8e000000000000000000"
    "1805bf00bc5d8e000000000000000000883fc80058e5420000000000b4000000"
    "743fc8003a5f8e000000000000000000643fc800bc7e8e000000000000000000"
    "7485c70085618e00000000000000000000000000000000000000000000000000"
)
#: Act struct: the name at `+0x04`, `SetPlayerControlOfArmy`'s 16-byte records at `+0xA8`, the
#: `EndAct` bool at `+0xB4`, and the campaign's act vector strides by `ACT_SIZE`.
ACT_NAME_OFFSET = 0x04
ACT_SIZE = 0xB8
#: Constructor, destructor, and the act parser that builds one on the stack and pushes it.
ACT_CTOR = 0x0096E5E9
ACT_DTOR = 0x0096DB26
ACT_PARSE = 0x0096E776
#: The act runner: ten per-verb passes, the last of them a tail call. `SetPlayerControlOfArmy` is
#: pass nine and the call site an eleventh pass would displace.
ACT_RUN = 0x0096E362
ACT_RUN_PASS9_CALL = 0x0096E39D
ACT_RUN_PASS9_CALL_BYTES = b"\xe8\x09\xe1\xff\xff"
ACT_SET_PLAYER_CONTROL_EXEC = 0x0096C4AB
#: The model parse function for a new verb: null-check, parse fields, append to the act.
ACT_SET_PLAYER_CONTROL_PARSE = 0x008E6185
ACT_SET_PLAYER_CONTROL_APPEND = 0x0096DF5D
#: `ForceBattle`: parse, append to the Act's `0x28`-byte records at `+0x14`, and pass two of the act
#: runner. Derived in `docs/living-campaign/force-battle.md`.
ACT_FORCE_BATTLE_PARSE = 0x008E5BE0
ACT_FORCE_BATTLE_APPEND = 0x0096DF22
ACT_FORCE_BATTLE_EXEC = 0x0096C74B
#: The two calls the battle form makes - `(Region, UseArmy, &ArmyAttackDirection)` and
#: `(&Position, UseArmy, &ArmyAttackDirection)`, thiscall on `TheLivingWorldLogic` - both into
#: `LIVING_WORLD_FORCE_BATTLE_STUB`, so a `ForceBattle` without `Movie` does nothing.
ACT_FORCE_BATTLE_REGION_CALL = 0x0096C897
ACT_FORCE_BATTLE_REGION_CALL_BYTES = b"\xe8\x04\xc3\xfa\xff"
ACT_FORCE_BATTLE_POSITION_CALL = 0x0096C8D4
ACT_FORCE_BATTLE_POSITION_CALL_BYTES = b"\xe8\xc7\xc2\xfa\xff"
#: A bare `ret 0xC`, referenced 172 times - a linker-folded empty body.
LIVING_WORLD_FORCE_BATTLE_STUB = 0x00918BA0
#: `ForceBattle`'s `Movie` form: add a named movie event to the strategic map, or remove one.
LIVING_WORLD_ADD_MOVIE_EVENT = 0x006B9341
LIVING_WORLD_REMOVE_MOVIE_EVENT = 0x006B8372
# How the engine builds a living-world battle, which is what `ForceBattle` needs to do for real.
# Derived in `docs/living-campaign/force-battle.md`. The region store is
# `[TheLivingWorldLogic + LIVING_WORLD_LOGIC_BATTLE_STORE]` and every `REGION_STORE_*` method is
# thiscall on it.

#: `RegionStore::findRegionByName(AsciiString*)`, `ret 4`, returning the `Region*` or NULL.
REGION_STORE_FIND_REGION_BY_NAME = 0x00610278
#: `RegionStore::regionAt(const Coord2D*, Region *hint)`, `ret 8`: the region containing a point.
#: A NULL hint is what the army constructor passes for a brand-new army.
REGION_STORE_REGION_AT = 0x0060F8AC
#: `RegionStore::battlePoint(Region*, Coord2D *out)`, `ret 8`, returning `al`: the point a battle in
#: that region is marked at on the world map.
REGION_STORE_BATTLE_POINT = 0x0060E83D
#: `RegionStore::findBattle(Region*)`, `ret 4`: the pending battle in a region, or NULL.
REGION_STORE_FIND_BATTLE = 0x0060E329
#: `RegionStore::createBattle(Region*, vector<Army*>*, vector<LivingWorldPlayer*>*, Coord2D*)`,
#: `ret 0x10`. Returns early if the region already has a battle; otherwise allocates the `0x40`-byte
#: `LivingWorldBattle`, files it in the store's battle vector and adds the owner's garrison. Reads
#: only `begin`/`end` of the two vectors.
REGION_STORE_CREATE_BATTLE = 0x0060F9D1
#: `RegionStore::detectConflicts()` - the only caller of `REGION_STORE_CREATE_BATTLE`, reached from
#: `LIVING_WORLD_CONFLICT_PASS` when the turn phase enters 1.
REGION_STORE_DETECT_CONFLICTS = 0x0060FBA1
LIVING_WORLD_CONFLICT_PASS = 0x006B4706
#: `LivingWorldBattle::LivingWorldBattle(id, Region*, armies*, players*, Coord2D*)`, `ret 0x14`.
LIVING_WORLD_BATTLE_CTOR = 0x007F869C
#: `Region::isDefended()` - owned, and flagged or holding a qualifying building. Thiscall, `al`.
REGION_IS_DEFENDED = 0x007F1437
#: `Region::defendsAgainst(LivingWorldPlayer*)`, `ret 4`: the owner is not allied with that player
#: and the region is defended. The test `detectConflicts` uses before seating the owner.
REGION_DEFENDS_AGAINST = 0x007F1489
#: `Army::updateRegion()`: recomputes the region from the army's position, caches it at `+0x8C` and
#: returns it. Thiscall, no stack args.
ARMY_UPDATE_REGION = 0x0071A56C
#: `Army::isEmptyPlaceholder()`: no `ScriptingName` and an empty roster. Such an army counts towards
#: a region's conflict only where its owner holds the region and the region is defended.
ARMY_IS_EMPTY_PLACEHOLDER = 0x0071AA69
#: `Army::setPosition(const Coord2D*)`, `ret 4`.
ARMY_SET_POSITION = 0x0071B39E
#: A live army's `HeroTemplateName` and `ScriptingName` strings, copied from the `SpawnArmy` record
#: by the army constructor (`0x0071BC70`). `spawnArmy` tests the hero at `0x006B735C`: empty sends
#: the new army to `LIVING_WORLD_MERGE_INTO_REGION_ARMY`.
ARMY_HERO_TEMPLATE_OFFSET = 0x18
ARMY_SCRIPTING_NAME_OFFSET = 0x1C
#: `LivingWorldLogic::mergeIntoRegionArmy(player, region, army)`: finds the player's army already
#: in the region, folds the new army's roster into it (`0x0071B202`) and destroys the new army
#: (`0x006B674D`), returning the survivor - or NULL, when there is none to merge into.
LIVING_WORLD_MERGE_INTO_REGION_ARMY = 0x006B540B
#: A live army's owning `LivingWorldPlayer` id, and the roster flag `detectConflicts` sets on every
#: army it puts into a battle.
LIVING_WORLD_ARMY_OWNER_ID = 0x54
LIVING_WORLD_ROSTER_IN_BATTLE = 0x2C
# `SpawnArmy` inside an Act, and where it puts the army. Derived in
# `docs/living-campaign/force-battle.md`: an army whose `Position` lies inside a region is moved to
# one of that region's slots if it names a hero, and merged into the army its player already has in
# the region if it does not - losing its `ScriptingName`. Only a point outside every region is kept.

#: `LivingWorldLogic::spawnArmy(record, LivingWorldPlayer*, controllable)`, `ret 0xC`, returning
#: the army (or the existing army an unnamed spawn merged into).
LIVING_WORLD_SPAWN_ARMY = 0x006B7229
#: Pass three of the act runner, and its call for a record with a non-zero `Position`.
ACT_SPAWN_ARMY_EXEC = 0x0096E0B8
ACT_SPAWN_ARMY_AT_POSITION_CALL = 0x0096E1D8
ACT_SPAWN_ARMY_AT_POSITION_CALL_BYTES = b"\xe8\x4c\x90\xd4\xff"
#: The Act's `SpawnArmy` parser, the push of its field table and its `INI::parseFields` call. The
#: table has two other users (`0x008E5748`, `0x008E8298`) that are left alone.
ACT_SPAWN_ARMY_PARSE = 0x008E78CE
ACT_SPAWN_ARMY_TABLE_PUSH_SITE = 0x008E7902
ACT_SPAWN_ARMY_TABLE_PUSH_SITE_BYTES = b"\x68\x80\x83\xc7\x00"
ACT_SPAWN_ARMY_PARSE_FIELDS_CALL = 0x008E790B
ACT_SPAWN_ARMY_PARSE_FIELDS_CALL_BYTES = b"\xe8\x70\x62\xb4\xff"
SPAWN_ARMY_FIELD_TABLE = 0x00C78380
SPAWN_ARMY_FIELD_ROW_COUNT = 18
SPAWN_ARMY_FIELD_TABLE_BYTES = bytes.fromhex(
    "4cbdbf005eee420000000000040000003c59c3005eee42000000000008000000"
    "f499be0098f2420000000000200000007083c7005eee42000000000028000000"
    "6483c7005eee4200000000002c0000003c50c3005eee42000000000030000000"
    "5883c7005eee420000000000340000004483c700d6ee42000000000038000000"
    "3483c7005eee420000000000180000002083c7005eee4200000000001c000000"
    "1883c70058e5420000000000540000000483c7005eee42000000000050000000"
    "f882c70000ed420000000000440000007c0bc1005eec42000000000048000000"
    "14a8c1005eee4200000000000c000000fca7c1005eee42000000000010000000"
    "e8a7c1005eee42000000000014000000e882c70058e542000000000055000000"
    "00000000000000000000000000000000"
)
#: `SpawnArmy` record fields: the `ScriptingName` string and the `Position` x, y.
SPAWN_ARMY_SCRIPTING_NAME_OFFSET = 0x18
SPAWN_ARMY_POSITION_OFFSET = 0x20
#: A region's enabled flag, written by `Region::setEnabled` (`0x007F1067`).
REGION_ENABLED = 0x1C2
#: `LivingWorldLogic::findArmyByScriptingName(AsciiString*)` - thiscall, walks `+0x8C..+0x90`.
LIVING_WORLD_FIND_ARMY_BY_NAME = 0x006B53A4
#: `LivingWorldCampaignManager::findPlayerArmyByName(AsciiString*)` - thiscall on
#: `THE_LIVING_WORLD_CAMPAIGN_MANAGER`, striding its store at `+0x20..+0x24` by `0x68`.
LIVING_WORLD_FIND_PLAYER_ARMY_BY_NAME = 0x007B98EC
THE_LIVING_WORLD_CAMPAIGN_MANAGER = 0x00DE87AC
#: `sizeof(LivingWorldPlayerArmy)`. The INI template and a live army's roster container at
#: `army+0x78` are the same class - `0x0071BC70` allocates this many bytes for the container and
#: `0x0081176F` deep-copies one onto the other.
LIVING_WORLD_PLAYER_ARMY_SIZE = 0x68
# The battle boundary an army's heroes cross. Derived in
# `docs/living-campaign/hero-permadeath.md`, and measured against BFME1 saves: both games harvest a
# battle back into the living-world army, and differ only in what becomes of a hero record whose
# object did not survive.

#: `TheLivingWorldLogic`'s living-world players, and each player's armies - both plain pointer
#: vectors. Walked to reach every army's roster without a name to look one up by.
LIVING_WORLD_PLAYERS_BEGIN = 0x8C
LIVING_WORLD_PLAYERS_END = 0x90
LIVING_WORLD_PLAYER_ARMIES_BEGIN = 0x1E4
LIVING_WORLD_PLAYER_ARMIES_END = 0x1E8
#: `LivingWorldPlayer::m_id`, the value `GAME_SLOT_LIVING_WORLD_PLAYER_ID` names and the one
#: `LIVING_WORLD_REGION_OWNER` is compared against to find a battle's defender.
LIVING_WORLD_PLAYER_ID = 0x14
#: `LivingWorldLogic::findPlayerById(id, int *outIndex)` - thiscall, `ret 8`, walking
#: `LIVING_WORLD_PLAYERS_BEGIN`. Returns NULL for id -1 without touching the vector.
LIVING_WORLD_FIND_PLAYER_BY_ID = 0x006B5DE0
#: The store on `THE_LIVING_WORLD_LOGIC` that holds both the battles and the regions, and the
#: region id of the battle currently being entered - written by `LivingWorldLogic::
#: enterRealtimeBattle` (`0x006B95F5`) from the battle's own region, before the map loads.
LIVING_WORLD_LOGIC_BATTLE_STORE = 0xB0
LIVING_WORLD_LOGIC_CURRENT_REGION_ID = 0xB8
#: The store's battle vector: plain pointers, walked by `0x0060E2AB` to find one by its id.
LIVING_WORLD_STORE_BATTLES_BEGIN = 0x14
LIVING_WORLD_STORE_BATTLES_END = 0x18
#: `LivingWorldLogic::getCurrentRegion()` - thiscall, `ret 0`. The region the battle is being
#: fought over, looked up by `LIVING_WORLD_LOGIC_CURRENT_REGION_ID`.
LIVING_WORLD_CURRENT_REGION = 0x006B351E
LIVING_WORLD_REGION_ID = 0x14C
#: The region's owning `LivingWorldPlayer` id. `buildSidesFromGameInfo` gives that player the
#: `Player_1` side and every other seat a `Player_%d` numbered off its slot index.
LIVING_WORLD_REGION_OWNER = 0x15C
#: A battle's sides - a vector of `LIVING_WORLD_BATTLE_SIDE_STRIDE`-byte records - and, inside
#: each record, the vector of `LIVING_WORLD_BATTLE_MEMBER_STRIDE`-byte member records whose first
#: dword is the `LivingWorldPlayer` fighting on that side.
LIVING_WORLD_BATTLE_SIDES_BEGIN = 0x18
LIVING_WORLD_BATTLE_SIDES_END = 0x1C
LIVING_WORLD_BATTLE_SIDE_STRIDE = 0x1C
LIVING_WORLD_BATTLE_MEMBERS_BEGIN = 0x04
LIVING_WORLD_BATTLE_MEMBERS_END = 0x08
LIVING_WORLD_BATTLE_MEMBER_STRIDE = 0x30
#: The region a battle is fought in, restored by id on load (`0x007F8822`).
LIVING_WORLD_BATTLE_REGION = 0x24
#: `LivingWorldLogic::findArmyById(id)` - thiscall, `ret 4`. The id is stamped on the army's roster
#: container at `LIVING_WORLD_ARMY_ROSTER_ID`, which is how an army is found again after a battle.
LIVING_WORLD_FIND_ARMY_BY_ID = 0x006B5351
LIVING_WORLD_ARMY_ROSTER_ID = 0x1C
#: The battle-start counterpart of the harvest: restores each living-world player's money, sciences
#: and upgrades onto its RTS player. Runs before any army deploys, which is what makes it the place
#: to read rosters that the deployment is about to consume.
LIVING_WORLD_BATTLE_SETUP = 0x008125FC
LIVING_WORLD_BATTLE_SETUP_CALL = 0x0062565A
LIVING_WORLD_BATTLE_SETUP_CALL_BYTES = b"\xe8\x9d\xcf\x1e\x00"
#: The call site of `LIVING_WORLD_BATTLE_HARVEST`, in `TheGameLogic`'s post-battle handler.
LIVING_WORLD_BATTLE_HARVEST_CALL = 0x0062667C
LIVING_WORLD_BATTLE_HARVEST_CALL_BYTES = b"\xe8\x9e\xb7\x1e\x00"
HERO_LEDGER_ENTRIES_BEGIN = 0x04
HERO_LEDGER_ENTRIES_END = 0x08
HERO_LEDGER_ENTRY_STRIDE = 0xE8
#: Copies the ledger's `KindOf HERO` + `KindOf ARMY_SUMMARY` entries onto the living-world player
#: when a battle ends, which is what puts a dead hero's build button back in his faction's
#: fortress. Called from inside `LIVING_WORLD_BATTLE_HARVEST`. **Deliberately untouched** by
#: `hero-army-carryover`, so a hero who died is both back with his army and recruitable again.
LIVING_WORLD_LEDGER_TO_PLAYER = 0x0078100E
#: `entry -> ThingTemplate`, thiscall, no stack args.
HERO_LEDGER_FIND_TEMPLATE = 0x007806FA
#: **`entry -> roster record`**: name, `Quantity = 1`, the `0x90`-byte state block and the upgrade
#: list, then `record+0xD0`. The exact mirror of `Object -> record` (`0x0069192F`), and what makes a
#: hero carried over from the ledger arrive at the level and upgrades he died with. Thiscall on the
#: entry, `ret 4`.
HERO_LEDGER_TO_RECORD = 0x00780FEF
#: The `ArmyEntry` record's constructor, and the sub-block parse the `Persistent` keyword is added
#: to. `0x0080EF6D` pushes `ARMY_ENTRY_DEFAULT_TABLE`; that immediate is what relocation repoints.
ARMY_ENTRY_RECORD_CTOR = 0x0080ECA7
ARMY_ENTRY_PARSE_FIELDS = 0x0080EF6D
ARMY_ENTRY_PARSE_FIELDS_CALL = 0x00811D41
ARMY_ENTRY_PARSE_FIELDS_CALL_BYTES = b"\xe8\x27\xd2\xff\xff"
ARMY_ENTRY_DEFAULT_TABLE_PUSH = 0x0080EF86
ARMY_ENTRY_DEFAULT_TABLE_PUSH_BYTES = b"\x68\x94\xfa\xc4\x00"
#: A record byte the constructor does not initialise, the copy-constructor does not carry and
#: nothing else reads - so a keyword may borrow it for the length of one `ArmyEntry` block, which
#: is all the `Persistent` flag needs before it is turned into a name in the patch's own table.
ARMY_ENTRY_SCRATCH_OFFSET = 0xD7
#: `record -> ThingTemplate`: `TheThingFactory->findTemplate(record + 4)`. Thiscall, no stack args.
ARMY_ENTRY_FIND_TEMPLATE = 0x007800DC
#: The reference count itself, one dword past the count object `REF_COUNT_RELEASE` is called on.
ARMY_ENTRY_REFCOUNT_COUNT = 0xC0
#: The hero's `ThingTemplate` name inside a `PLAYER_HERO_LEDGER_OFFSET` entry.
HERO_LEDGER_NAME_OFFSET = 0xE4
#: `assignObjectToArmy(obj, armyId)` - resolves the army, sets the object's team
#: (`0x0068B6CB`) and then its army id. A zero id resolves no army and writes nothing.
LIVING_WORLD_ASSIGN_OBJECT_TO_ARMY = 0x0080FD9C
#: The `TheGameLogic` thunk in front of it (`add ecx, 0x184; jmp`), which is how nearly every
#: caller reaches it - the call site to look for when tracing who hands out army ids.
LIVING_WORLD_ASSIGN_OBJECT_TO_ARMY_THUNK = 0x00625E0A
#: `findArmyById(id)->[0x78]` - the roster container the harvest appends to, or NULL for id 0.
LIVING_WORLD_FIND_ARMY_ROSTER = 0x0080FAD4
#: Battle-start deployment: walks the living-world player's armies and places each one at its
#: `Player_%d_Start` waypoint, assigning the army id as it goes.
LIVING_WORLD_DEPLOY_AT_BATTLE_START = 0x00629F34
#: `ArmyRecord::spawnInto` - `ArmyRecord::createObject` (`0x00780172`) followed by the assignment.
LIVING_WORLD_ARMY_RECORD_SPAWN_INTO = 0x0080EDF1
#: The harvest's army-id test - the six stock bytes are `mov eax, [edi + 0x47c]`, and no branch in
#: the function targets them, which makes it the hook site for a "carry this anyway" rule.
LIVING_WORLD_HARVEST_ARMY_ID_TEST = 0x00811EAA
LIVING_WORLD_HARVEST_ARMY_ID_TEST_BYTES = b"\x8b\x87\x7c\x04\x00\x00"
#: The living-world battle bridge is `TheGameLogic + 0x184`. It holds the vector of army ids taking
#: part in this battle between `+0x14` and `+0x18` - the place to resolve a fallback army from,
#: since `findArmyRoster(id)` then `LIVING_WORLD_ARMY_ROSTER_TEAM` gives the army's team and so its
#: player.
LIVING_WORLD_BATTLE_BRIDGE_OFFSET = 0x184
LIVING_WORLD_BATTLE_ARMY_IDS_BEGIN = 0x14
LIVING_WORLD_BATTLE_ARMY_IDS_END = 0x18
#: Walks that vector and returns `roster->[0x1C]` for the first army whose `roster->[0x14]` is zero.
LIVING_WORLD_BATTLE_PRIMARY_ARMY_ID = 0x0080FF1B
#: `roster -> Team`, the lookup `LIVING_WORLD_ASSIGN_OBJECT_TO_ARMY` uses before `Object::setTeam`.
LIVING_WORLD_ARMY_ROSTER_TEAM = 0x0080F45F
#: Seed a live army's roster from its `PlayerArmy` template, and the assignment that does the copy.
LIVING_WORLD_ARMY_SEED_FROM_TEMPLATE = 0x0071AD41
LIVING_WORLD_PLAYER_ARMY_ASSIGN = 0x0081176F
THE_LIVING_WORLD_LOGIC = 0x00DE4950
#: A live army: its `ScriptingName` and the roster container the campaign verbs move records
#: between. The container's record vector is `begin`/`end` of 8-byte `{id, record*}` elements.
LIVING_WORLD_ARMY_SCRIPTING_NAME_OFFSET = 0x1C
LIVING_WORLD_ARMY_ROSTER_OFFSET = 0x78
LIVING_WORLD_ARMY_RECORDS_BEGIN = 0x40
LIVING_WORLD_ARMY_RECORDS_END = 0x44
LIVING_WORLD_ARMY_RECORD_STRIDE = 8
#: The record's embedded reference count: `REF_COUNT_RELEASE` is called on `record + 0xBC` and the
#: count itself lives one dword further in, at `ARMY_ENTRY_REFCOUNT_OFFSET + 4`.
ARMY_ENTRY_REFCOUNT_OFFSET = 0xBC
# The living-world turn phase, which is the only thing that advances a campaign act. Derived in
# `docs/living-campaign/act-advance-stall.md`: the act cursor moves when the phase reaches 6, and
# the phase is braked in four places by the strategic message-box gate.

#: `LivingWorldLogic::update` - the per-frame tick. Everything below it is skipped unless the
#: two-sides-still-standing test at `LIVING_WORLD_TICK_GATE` passes.
LIVING_WORLD_UPDATE = 0x006BE50E
LIVING_WORLD_TICK_GATE = 0x006BE57C
#: The distinct-owner counts that gate drives on: live armies (`army+0x444` clear) and all armies.
LIVING_WORLD_COUNT_LIVE_ARMY_OWNERS = 0x006B839A
LIVING_WORLD_COUNT_ARMY_OWNERS = 0x006B83DF
#: `LivingWorldLogic::updateTurnPhase` - computes one "may advance" boolean and acts on it. Its
#: message-box brake is `LIVING_WORLD_TURN_PHASE_BOX_BRAKE`, its pending-advance drain the other.
LIVING_WORLD_UPDATE_TURN_PHASE = 0x006BE20A
LIVING_WORLD_TURN_PHASE_BOX_BRAKE = 0x006BE376
LIVING_WORLD_TURN_PHASE_DRAIN = 0x006BE3B6
#: Request an advance (posts message `0x6A6`, sets the pending byte), its precondition, and the
#: increment the drain tail-jumps to once every army has settled.
LIVING_WORLD_REQUEST_ADVANCE_TURN_PHASE = 0x006B6BA1
LIVING_WORLD_CAN_ADVANCE_TURN_PHASE = 0x006B6ACC
LIVING_WORLD_ADVANCE_TURN_PHASE = 0x006BDF30
#: Phase 6: end the turn and advance the campaign act. The only live caller of the manager's
#: `advanceAct`; the two other branches to it are in unreferenced, dead functions.
LIVING_WORLD_END_TURN = 0x006BDEC7
LIVING_WORLD_CAMPAIGN_MANAGER_ADVANCE_ACT = 0x007B970F
LIVING_WORLD_CAMPAIGN_ADVANCE_ACT = 0x00932A57
#: `TheLivingWorldLogic` turn state: the phase, the turn number, and the byte that says an advance
#: has been requested and the drain path is running instead of the phase machine.
LIVING_WORLD_TURN_PHASE_OFFSET = 0xF4
LIVING_WORLD_TURN_NUMBER_OFFSET = 0xFC
LIVING_WORLD_ADVANCE_PENDING_OFFSET = 0x10A
# The strategic message-box gate. A box that is marked showing and never dismissed freezes the
# campaign, because all four brakes below wait on it and none of them has a timeout.

#: `LivingWorldLogic::isMessageBoxShowing` - `[this+0x160] && [[this+0x160]+0x25]`. Four callers,
#: every one a brake: the turn-phase update, the advance precondition, the phase 1/5 predicate,
#: and the queue pump itself.
LIVING_WORLD_IS_MESSAGE_BOX_SHOWING = 0x006B4019
#: The pump: release a finished box, then show the queue front. Called once per update, and the
#: hook site for a watchdog because it already holds both the current box and the queue.
LIVING_WORLD_PUMP_MESSAGE_BOXES = 0x006B74D5
LIVING_WORLD_PUMP_MESSAGE_BOXES_CALL = 0x006BE5D7
LIVING_WORLD_SHOW_QUEUE_FRONT = 0x006B67B2
#: The queue and the box on screen, both refcounted, on `THE_LIVING_WORLD_LOGIC`.
LIVING_WORLD_MESSAGE_BOX_QUEUE_BEGIN = 0x154
LIVING_WORLD_MESSAGE_BOX_QUEUE_END = 0x158
LIVING_WORLD_MESSAGE_BOX_CURRENT = 0x160
#: The living-world strategic message-box manager, and the general one. Two instances of the same
#: class; the living-world prompts go to the first, `0x0081A4EB`'s to the second.
THE_STRATEGIC_MESSAGE_BOX = 0x00DEBA1C
THE_GENERAL_MESSAGE_BOX = 0x00DE8A9C
#: `StrategicMessageBox::add` and the five-argument wrapper the box's `show` calls. `add` begins by
#: hiding the current box **without** notifying, so an add over a live box strands it.
STRATEGIC_MESSAGE_BOX_ADD = 0x00953861
STRATEGIC_MESSAGE_BOX_ADD_THUNK = 0x00953C0B
#: `StrategicMessageBox::show(type)`, and `hide(notify)` - the notifying path is the only thing in
#: the image that fires completion event 3, which is the only thing that clears the gate byte.
STRATEGIC_MESSAGE_BOX_SHOW = 0x009539D3
STRATEGIC_MESSAGE_BOX_HIDE = 0x00953243
STRATEGIC_MESSAGE_BOX_HIDE_NOTIFY = 0x00953498
#: Push the manager's state onto `THE_APT_PLAYER`. Skipped when the player is null, and then only
#: `STRATEGIC_MESSAGE_BOX_RESHOW_OVERLAYS` re-applies it.
STRATEGIC_MESSAGE_BOX_APPLY_TO_APT = 0x009532F3
STRATEGIC_MESSAGE_BOX_APPLY_GUARD = 0x0095397F
STRATEGIC_MESSAGE_BOX_RESHOW = 0x009534A0
STRATEGIC_MESSAGE_BOX_RESHOW_OVERLAYS = 0x00782C56
#: A living-world message box: its `show`, its completion delegate, and the byte the delegate
#: clears on event 3. `+0x08`/`+0x0C` are the title and body, which name a stuck box in a live read.
LIVING_WORLD_MESSAGE_BOX_SHOW = 0x00900CBC
LIVING_WORLD_MESSAGE_BOX_ON_EVENT = 0x00900B6D
LIVING_WORLD_MESSAGE_BOX_TITLE = 0x08
LIVING_WORLD_MESSAGE_BOX_BODY = 0x0C
LIVING_WORLD_MESSAGE_BOX_SHOWING = 0x25
LIVING_WORLD_MESSAGE_BOX_FINISHED = 0x26
# War of the Ring faction selection: `DisabledFactions` and the four readers of it
# Derived in `docs/scenario-player-factions.md`. Static only.

#: `Scenario::isFactionEnabled(AsciiString side)`: it takes no player, which is why
#: `DisabledFactions` can only be scenario-wide. The argument is by value, destroyed by the callee.
SCENARIO_IS_FACTION_ENABLED = 0x0090182D
SCENARIO_IS_FACTION_ENABLED_ENTRY = bytes.fromhex("b8be7dba00")
#: `Scenario::hasDisabledFactions()` - `(end - begin) != 0`, and the gate the start-game check
#: asks before it looks at any slot. A per-player entry is a vector element like any other, so a
#: scenario that writes only those still opens this gate.
SCENARIO_HAS_DISABLED_FACTIONS = 0x009012D7
#: `begin` and `end` of the `DisabledFactions` `std::vector<AsciiString>` inside `Scenario`. The
#: INI field-parse row writes `+0x40`; the same struct holds `MaxPlayers` at `+0x10` and
#: `HistoricalScenario` at `+0xC0`.
SCENARIO_DISABLED_FACTIONS_BEGIN = 0x40
SCENARIO_DISABLED_FACTIONS_END = 0x44
#: The four calls to it, all in the multiplayer setup screen, as `(call VA, bytes, ebp slot of the
#: lobby slot index)`.
SCENARIO_FACTION_CALL_SITES = (
    (0x0084348B, bytes.fromhex("e89de30b00"), -0x24),
    (0x00844735, bytes.fromhex("e8f3d00b00"), -0x18),
    (0x008448E1, bytes.fromhex("e847cf0b00"), -0x18),
    (0x00844E51, bytes.fromhex("e8d7c90b00"), 0x08),
)
# The War of the Ring selection-details tray - the panel `StrategicHUD.apt` loads from
# `StrategicDetailsTray.swf` into its `selectionDetails` clip - and the `Scenario` field that keeps
# it shut. Derived in `docs/living-campaign/hide-selection-details.md`. Static only.

#: `Scenario`'s INI field-parse table, and its one reference: the block parser's `push`.
SCENARIO_FIELD_TABLE = 0x00C7A578
SCENARIO_FIELD_TABLE_REFS = (0x009028B2,)
SCENARIO_FIELD_TABLE_REF_OPCODES = (0x68,)  # push imm32
#: `push sizeof(Scenario)` before the block parser's `operator new`. The last field is
#: `UseMpRulesVictoryCondition` at `+0xC1`, so `+0xC2..+0xC3` is alignment padding no row names.
SCENARIO_ALLOC = 0x0090288D
SCENARIO_ALLOC_BYTES = bytes.fromhex("68c4000000")
SCENARIO_SIZE = 0xC4
SCENARIO_HISTORICAL = 0xC0
SCENARIO_USE_MP_RULES = 0xC1
SCENARIO_FREE_OFFSET = 0xC2
#: The constructor's `xor ebx, ebx` - the zero every default is stored from - its
#: `mov byte [esi+0xC0], bl` (`HistoricalScenario = No`), and the `mov byte [esi+0xC1], 1`
#: (`UseMpRulesVictoryCondition = Yes`) that follows it.
SCENARIO_CTOR_ZERO = 0x00901DE5
SCENARIO_CTOR_ZERO_BYTES = bytes.fromhex("33db")
SCENARIO_CTOR_HISTORICAL = 0x00901E6A
SCENARIO_CTOR_HISTORICAL_BYTES = bytes.fromhex("889ec0000000")
SCENARIO_CTOR_USE_MP_RULES = 0x00901E70
SCENARIO_CTOR_USE_MP_RULES_BYTES = bytes.fromhex("c686c100000001")
#: The campaign manager's current campaign: an index at `+0x10` into the pointer vector at
#: `+0x14..+0x18`. Read that way, bounds check included, by the manager method at this address and
#: by `advanceAct` just above it.
LIVING_WORLD_CAMPAIGN_MANAGER_CURRENT_READ = 0x007B9743
LIVING_WORLD_CAMPAIGN_MANAGER_CURRENT_READ_BYTES = bytes.fromhex(
    "8b411085c07c1a8b51182b5114c1fa023bc2730d8b49148b0481"
)
LIVING_WORLD_CAMPAIGN_MANAGER_CURRENT = 0x10
LIVING_WORLD_CAMPAIGN_MANAGER_CAMPAIGNS_BEGIN = 0x14
LIVING_WORLD_CAMPAIGN_MANAGER_CAMPAIGNS_END = 0x18
#: A `LivingWorldCampaign`'s `Scenario`, as the start-up state builder reads it before it walks
#: `DisableRegions`: `mov esi, [esi+0x1C]` / `test esi, esi` / `je`.
LIVING_WORLD_CAMPAIGN_SCENARIO_READ = 0x00932B95
LIVING_WORLD_CAMPAIGN_SCENARIO_READ_BYTES = bytes.fromhex("8b761c85f67437")
LIVING_WORLD_CAMPAIGN_SCENARIO = 0x1C
ARMY_RECORD_SPAWN = 0x00811104
#: The record half of an army carryover, usable on any player. `ARMY_RECORD_SIZE` is what
#: `ARMY_ENTRY_RECORD_CTOR` constructs, and the same record an `ArmyEntry` line parses into, so the
#: `ARMY_ENTRY_*` offsets apply to it. `ARMY_RECORD_HEALTH` is a float applied to the body only
#: when it exceeds the template maximum; `ARMY_RECORD_UPGRADE_LIST` is copied onto
#: `OBJECT_UPGRADE_MASK` through `OBJECT_APPLY_UPGRADE_LIST`.
ARMY_RECORD_CREATE_OBJECT = 0x00780172
ARMY_RECORD_SIZE = 0xD8
ARMY_RECORD_HEALTH = 0x08
ARMY_RECORD_UPGRADE_LIST = 0x10
