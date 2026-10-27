"""The AI: the skirmish AI, AI groups and commands, and the build assistant's gates."""

from __future__ import annotations

__all__ = [
    "ACTION_MANAGER_CAN_ENTER_OBJECT",
    "ACTION_MANAGER_ENTER_HINT",
    "AI_ACTIVE_ATTACK_MACHINE",
    "AI_ACTIVE_ATTACK_MACHINE_BYTES",
    "AI_ATTACK_MACHINE_TARGET",
    "AI_ATTACK_MACHINE_TARGET_BYTES",
    "AI_COMMAND_OBJECT_EBP",
    "AI_COMMAND_SOURCE_FROM_AI",
    "AI_COMMAND_SOURCE_OFFSET",
    "AI_COMMAND_TRANSFER_ANSWER",
    "AI_COMMAND_TRANSFER_ANSWER_BYTES",
    "AI_COMMAND_TRANSFER_ANSWER_READ",
    "AI_COMMAND_TRANSFER_ANSWER_READ_BYTES",
    "AI_COMMAND_TRANSFER_BOOL_INIT",
    "AI_COMMAND_TRANSFER_BOOL_INIT_BYTES",
    "AI_COMMAND_TRANSFER_CHECK",
    "AI_COMMAND_TRANSFER_CHECK_ENTRY",
    "AI_COMMAND_TRANSFER_DISMOUNT_CALL",
    "AI_COMMAND_TRANSFER_DISMOUNT_CALL_BYTES",
    "AI_COMMAND_TRANSFER_MOUNT_CALL",
    "AI_COMMAND_TRANSFER_MOUNT_CALL_BYTES",
    "AI_COMMAND_TRANSFER_OBJECT_ARM",
    "AI_COMMAND_TRANSFER_OBJECT_ARM_BYTES",
    "AI_COMMAND_TRANSFER_RESUME",
    "AI_COMMAND_TRANSFER_RESUME_BYTES",
    "AI_COMMAND_TRANSFER_TARGET_LOAD",
    "AI_COMMAND_TRANSFER_TARGET_LOAD_BYTES",
    "AI_COMMAND_TRANSFER_TARGET_USE",
    "AI_COMMAND_TRANSFER_TARGET_USE_BYTES",
    "AI_COMMAND_TYPE_OFFSET",
    "AI_CURRENT_STATE_ID",
    "AI_CURRENT_STATE_ID_BYTES",
    "AI_CURRENT_VICTIM",
    "AI_CURRENT_VICTIM_BYTES",
    "AI_CURRENT_VICTIM_ID_OFFSET",
    "AI_DATA_ARMY_DEFINITION",
    "AI_DATA_SET_VALUE",
    "AI_DATA_SET_VALUE_ENTRY",
    "AI_DESTROY_PATH",
    "AI_DESTROY_PATH_BYTES",
    "AI_ENTER_AND_ATTACK_ON_ENTER_CONTAIN_LOAD",
    "AI_ENTER_AND_ATTACK_ON_ENTER_CONTAIN_LOAD_BYTES",
    "AI_ENTER_AND_ATTACK_ON_EXIT_RELEASE",
    "AI_ENTER_AND_ATTACK_ON_EXIT_RELEASE_BYTES",
    "AI_ENTER_AND_ATTACK_STATE_ON_ENTER",
    "AI_ENTER_AND_ATTACK_STATE_ON_EXIT",
    "AI_ENTER_AND_ATTACK_STATE_UPDATE",
    "AI_ENTER_AND_ATTACK_STATE_VTABLE",
    "AI_ENTER_AND_ATTACK_UPDATE_ADD_LOAD",
    "AI_ENTER_AND_ATTACK_UPDATE_ADD_LOAD_BYTES",
    "AI_ENTER_ON_ENTER_CONTAIN_LOAD",
    "AI_ENTER_ON_ENTER_CONTAIN_LOAD_BYTES",
    "AI_ENTER_ON_EXIT_RELEASE",
    "AI_ENTER_ON_EXIT_RELEASE_BYTES",
    "AI_ENTER_STATE_ON_ENTER",
    "AI_ENTER_STATE_ON_EXIT",
    "AI_ENTER_STATE_UPDATE",
    "AI_ENTER_STATE_VTABLE",
    "AI_ENTER_UPDATE_ADD_LOAD",
    "AI_ENTER_UPDATE_ADD_LOAD_BYTES",
    "AI_ENTER_UPDATE_ENTRY_LOAD",
    "AI_ENTER_UPDATE_ENTRY_LOAD_BYTES",
    "AI_FARM_KILL_SQUAD_BUILD",
    "AI_FARM_KILL_SQUAD_BUILD_ENTRY",
    "AI_FARM_KILL_SQUAD_BUILD_SLOT",
    "AI_FARM_KILL_SQUAD_NAME_PUSH",
    "AI_FARM_KILL_SQUAD_NAME_PUSH_BYTES",
    "AI_FARM_KILL_SQUAD_NEXT_RUN_KEY",
    "AI_FARM_KILL_SQUAD_RESET",
    "AI_FARM_KILL_SQUAD_RESET_ENTRY",
    "AI_FARM_KILL_SQUAD_RESET_SLOT",
    "AI_FARM_KILL_SQUAD_RUN_GATE",
    "AI_FARM_KILL_SQUAD_RUN_GATE_ENTRY",
    "AI_FARM_KILL_SQUAD_RUN_GATE_SLOT",
    "AI_FARM_KILL_SQUAD_SOURCE_FILE",
    "AI_FARM_KILL_SQUAD_VTABLE",
    "AI_FLAG_CAPTURE_KEEP",
    "AI_FLAG_CAPTURE_PICKER",
    "AI_FLAG_CAPTURE_PICKER_CALL",
    "AI_FLAG_CAPTURE_PICKER_CALL_BYTES",
    "AI_FLAG_CAPTURE_PICKER_ENTRY",
    "AI_FLAG_CAPTURE_RELATIONSHIP_TEST",
    "AI_FLAG_CAPTURE_RELATIONSHIP_TEST_BYTES",
    "AI_FLAG_CAPTURE_SKIP",
    "AI_FLAG_CAPTURE_SQUAD_NAME_PUSH",
    "AI_FLAG_CAPTURE_SQUAD_NAME_PUSH_BYTES",
    "AI_FLAG_CAPTURE_SQUAD_UPDATE",
    "AI_FLAG_CAPTURE_SQUAD_UPDATE_SLOT",
    "AI_FLAG_CAPTURE_SQUAD_VTABLE",
    "AI_GOAL_IS_OBJECT_OFFSET",
    "AI_GROUP_DO_OBJECT_UPGRADE",
    "AI_GROUP_ENTER_FILTER",
    "AI_GROUP_ENTER_FILTER_MEMBER_TEST",
    "AI_GROUP_ENTER_FILTER_MEMBER_TEST_BYTES",
    "AI_GROUP_ENTER_FILTER_TARGET",
    "AI_GROUP_MEMBER_OBJECT",
    "AI_GROUP_MEMBER_SENTINEL",
    "AI_GROUP_UPGRADE_EBP",
    "AI_GROUP_UPGRADE_MEMBER",
    "AI_GROUP_UPGRADE_MEMBER_BYTES",
    "AI_GROUP_UPGRADE_MEMBER_RESUME",
    "AI_GROUP_UPGRADE_SELF_EBP",
    "AI_HERO_ARMY_DEFINITION_LIST",
    "AI_HERO_ARMY_DEFINITION_LIST_BYTES",
    "AI_HERO_BUILDER_AI_DATA",
    "AI_HERO_BUILDER_AI_DATA_BYTES",
    "AI_HERO_LIST_BEGIN",
    "AI_HERO_LIST_ELEMENT",
    "AI_HERO_LIST_ELEMENT_BYTES",
    "AI_HERO_NAME_RESOLVED",
    "AI_HERO_NAME_RESOLVED_BYTES",
    "AI_HERO_NAME_RESOLVED_RESUME",
    "AI_HERO_PICK_INDEX",
    "AI_HERO_PICK_INDEX_CALL",
    "AI_HERO_PICK_INDEX_CALL_BYTES",
    "AI_HERO_PICK_INDEX_ENTRY",
    "AI_HERO_REJECT",
    "AI_HERO_REJECT_BYTES",
    "AI_HERO_REQUEST",
    "AI_HERO_REQUEST_CALL",
    "AI_HERO_REQUEST_CALL_BYTES",
    "AI_HERO_REQUEST_ENTRY",
    "AI_MOVE_UPDATE_NO_PATH_RECOMPUTE",
    "AI_MOVE_UPDATE_NO_PATH_RECOMPUTE_BYTES",
    "AI_MOVE_UPDATE_STATE_TEST",
    "AI_MOVE_UPDATE_STATE_TEST_BYTES",
    "AI_MOVE_UPDATE_UNGUARDED_PATH_READ",
    "AI_MOVE_UPDATE_UNGUARDED_PATH_READ_BYTES",
    "AI_NEIGHBOUR_LIST_COPY",
    "AI_NEIGHBOUR_LIST_COPY_FAULT",
    "AI_ORDER_PUMP_CAN_START_CALL",
    "AI_ORDER_PUMP_CAN_START_CALL_BYTES",
    "AI_ORDER_PUMP_NO_BUILDER_STOP",
    "AI_ORDER_PUMP_NO_BUILDER_STOP_BYTES",
    "AI_ORDER_PUMP_NO_BUILDER_TEST",
    "AI_ORDER_PUMP_NO_BUILDER_TEST_BYTES",
    "AI_PATH_OFFSET",
    "AI_PLANNER_UNCHECKED_LOOKUPS",
    "AI_POWER_NOT_CAST",
    "AI_POWER_NOT_CAST_BYTES",
    "AI_POWER_READY_WINDOW",
    "AI_POWER_READY_WINDOW_BYTES",
    "AI_POWER_TICK",
    "AI_POWER_TICK_ENTRY",
    "AI_POWER_TICK_HOOK",
    "AI_POWER_TICK_HOOK_BYTES",
    "AI_POWER_TICK_RESUME",
    "AI_POWER_UPDATE_BUTTON_OFFSET",
    "AI_POWER_UPDATE_CTOR_VTABLE_WRITE",
    "AI_POWER_UPDATE_CTOR_VTABLE_WRITE_BYTES",
    "AI_POWER_UPDATE_TICK_VTABLE",
    "AI_PRODUCER_ACCEPT",
    "AI_PRODUCER_ANY_BRANCH",
    "AI_PRODUCER_ANY_BRANCH_ENTRY",
    "AI_PRODUCER_NEXT_CANDIDATE",
    "AI_PRODUCER_PICKER",
    "AI_PRODUCER_PICKER_CALL",
    "AI_PRODUCER_PICKER_CALL_BYTES",
    "AI_PRODUCER_PICKER_ENTRY",
    "AI_PRODUCER_USABLE_TESTS",
    "AI_REBUILD_BEHAVIOR_CTOR",
    "AI_REBUILD_BEHAVIOR_CTOR_BYTES",
    "AI_REBUILD_BEHAVIOR_VTABLE",
    "AI_REBUILD_BODY_FETCH",
    "AI_REBUILD_BODY_FETCH_BYTES",
    "AI_REBUILD_FACTORY_CASE",
    "AI_REBUILD_FACTORY_CASE_CALL",
    "AI_REBUILD_FACTORY_CASE_CALL_BYTES",
    "AI_REBUILD_HEALTH_TEST",
    "AI_REBUILD_HEALTH_TEST_BYTES",
    "AI_REBUILD_HEALTH_THRESHOLD",
    "AI_REBUILD_NEXT_CANDIDATE",
    "AI_REBUILD_NEXT_CANDIDATE_BYTES",
    "AI_REBUILD_PICKER",
    "AI_REBUILD_PICKER_ENTRY",
    "AI_REBUILD_PICKER_VTABLE_SLOT",
    "AI_REGION_GRAPH",
    "AI_REGION_GRAPH_BUILD",
    "AI_REGION_GRAPH_ENABLED_TEST",
    "AI_REGION_GRAPH_ENABLED_TEST_BYTES",
    "AI_REGION_GRAPH_SKIP_DISABLED",
    "AI_REGION_GRAPH_SKIP_DISABLED_BYTES",
    "AI_SET_CURRENT_VICTIM",
    "AI_SET_CURRENT_VICTIM_BYTES",
    "AI_SET_GOAL_OBJECT",
    "AI_SET_GOAL_OBJECT_BYTES",
    "AI_SET_GOAL_POSITION",
    "AI_SET_GOAL_POSITION_BYTES",
    "AI_STATE_NO_PATH_UNSAFE",
    "AI_STATE_ON_ENTER_SLOT",
    "AI_STATE_ON_EXIT_SLOT",
    "AI_STATE_UPDATE_SLOT",
    "AI_TACTIC_PLAYER",
    "AI_TEAM_BUILDER_DONE_SIZE_CALL",
    "AI_TEAM_BUILDER_PLAYER",
    "AI_TEAM_BUILDER_RECRUIT_SIZE_CALL",
    "AI_TEAM_PROTOTYPE_FORBIDDEN_KIND_OF",
    "AI_TEAM_PROTOTYPE_MAX_SIZE",
    "AI_TEAM_PROTOTYPE_MIN_SIZE",
    "AI_TEAM_RECRUIT_ACCEPT",
    "AI_TEAM_RECRUIT_ACCEPT_CALLS",
    "AI_TEAM_RECRUIT_ACCEPT_ENTRY",
    "AI_TEAM_RECRUIT_FORBIDDEN_KIND_OF",
    "AI_TEAM_SIZE",
    "AI_TEAM_SIZE_BACK_EDGE",
    "AI_TEAM_SIZE_BACK_EDGE_BYTES",
    "AI_TEAM_SIZE_ENTRY",
    "AI_TEAM_SIZE_KINDOF_TESTS",
    "AI_TEAM_SIZE_KINDOF_TESTS_BYTES",
    "AI_TEAM_SIZE_MEMBER",
    "AI_TEAM_SIZE_MEMBER_BYTES",
    "AI_TEAM_SIZE_NEXT",
    "AI_TEAM_SIZE_NEXT_BYTES",
    "AI_UPDATE_LOCOMOTOR_SET_SPEED",
    "AI_UPDATE_SET_LOCOMOTOR_SET",
    "AI_UPDATE_SET_LOCOMOTOR_SET_SPEED_STORE",
    "AI_WAITING_FOR_PATH_OFFSET",
    "AI_WORLD_MODEL",
    "ARMY_DEFINITION_MEMBERS",
    "ARMY_DEFINITION_PHASE_DURATION_MID_GAME",
    "ARMY_DEFINITION_PHASE_DURATION_RUSH",
    "ARMY_MEMBER_DEFINITION_ALLOC",
    "ARMY_MEMBER_DEFINITION_ALLOC_BYTES",
    "ARMY_MEMBER_DEFINITION_FIELD_TABLE",
    "ARMY_MEMBER_DEFINITION_FIELD_TABLE_REFS",
    "ARMY_MEMBER_DEFINITION_FIELD_TABLE_REF_OPCODES",
    "ARMY_MEMBER_DEFINITION_SIZE",
    "ATTACK_APPROACH_COMPUTE_PATH",
    "ATTACK_APPROACH_COMPUTE_PATH_BYTES",
    "ATTACK_APPROACH_GOAL_POS_OFFSET",
    "ATTACK_APPROACH_MAY_STOP_GATE",
    "ATTACK_APPROACH_MAY_STOP_GATE_BYTES",
    "ATTACK_APPROACH_MAY_STOP_OFFSET",
    "ATTACK_APPROACH_UPDATE_INTERNAL",
    "ATTACK_APPROACH_UPDATE_INTERNAL_BYTES",
    "ATTACK_APPROACH_VTABLE",
    "BUILD_ASSISTANT_VTABLE",
    "CAN_ENTER_OBJECT_CONTAIN_LOAD",
    "CAN_ENTER_OBJECT_CONTAIN_LOAD_BYTES",
    "CAN_MAKE_UNIT",
    "CAN_MAKE_UNIT_ACCEPT",
    "CAN_MAKE_UNIT_ACCEPT_TEMPLATE",
    "CAN_MAKE_UNIT_ACCEPT_TEMPLATE_BYTES",
    "CAN_MAKE_UNIT_BUMP_SLOT",
    "CAN_MAKE_UNIT_CAN_BUILD_CALL",
    "CAN_MAKE_UNIT_CAN_BUILD_CALL_BYTES",
    "CAN_MAKE_UNIT_EQUIVALENT_CALL",
    "CAN_MAKE_UNIT_EQUIVALENT_CALL_BYTES",
    "CAN_MAKE_UNIT_NEXT_SLOT",
    "CAN_MAKE_UNIT_PRODUCTION_GATE",
    "CAN_MAKE_UNIT_PRODUCTION_GATE_CALL",
    "CAN_MAKE_UNIT_PRODUCTION_GATE_CALL_BYTES",
    "CAN_MAKE_UNIT_PRODUCTION_GATE_SLOT",
    "CAN_MAKE_UNIT_REVIVE_BRANCH",
    "CAN_MAKE_UNIT_REVIVE_BRANCH_ENTRY",
    "CAN_MAKE_UNIT_REVIVE_DISPATCH",
    "CAN_MAKE_UNIT_REVIVE_DISPATCH_BYTES",
    "CAN_MAKE_UNIT_SCAN_BOUND",
    "CAN_MAKE_UNIT_TEMPLATE_BRANCH",
    "CAN_MAKE_UNIT_TEMPLATE_BRANCH_BYTES",
    "CAN_MAKE_UNIT_UPGRADE_GATE",
    "CAN_MAKE_UNIT_VTABLE_SLOT",
    "DEPLOY_STYLE_AI_BYPASS_PATH",
    "DEPLOY_STYLE_AI_BYPASS_PATH_BYTES",
    "DEPLOY_STYLE_AI_DO_COMMAND",
    "DEPLOY_STYLE_AI_DO_COMMAND_ENTRY",
    "DEPLOY_STYLE_AI_RECORD_PATH",
    "DEPLOY_STYLE_AI_RECORD_PATH_BYTES",
    "DEPLOY_STYLE_AI_SOURCE_BRANCH",
    "DEPLOY_STYLE_AI_SOURCE_BRANCH_BYTES",
    "DEPLOY_STYLE_ATTACK_COMMANDS",
    "DEPLOY_STYLE_MODULE_DATA_OFFSET",
    "DEPLOY_STYLE_MOVE_ARM_MUST_DEPLOY",
    "DEPLOY_STYLE_MOVE_ARM_MUST_DEPLOY_BYTES",
    "DEPLOY_STYLE_MUST_DEPLOY_GETTER",
    "DEPLOY_STYLE_MUST_DEPLOY_GETTER_BYTES",
    "DEPLOY_STYLE_MUST_DEPLOY_OFFSET",
    "DEPLOY_STYLE_RECORDED_COMMAND_OFFSETS",
    "DEPLOY_STYLE_RECORD_STORES",
    "DEPLOY_STYLE_SET_MY_STATE",
    "DEPLOY_STYLE_SET_MY_STATE_BYTES",
    "DEPLOY_STYLE_SET_STATE_STORE",
    "DEPLOY_STYLE_SET_STATE_STORE_BYTES",
    "DEPLOY_STYLE_STATE_DEPLOY",
    "DEPLOY_STYLE_STATE_OFFSET",
    "DEPLOY_STYLE_STATE_READY_TO_ATTACK",
    "DEPLOY_STYLE_STATE_READY_TO_MOVE",
    "DEPLOY_STYLE_TARGETED_COMMAND_OFFSETS",
    "DEPLOY_STYLE_UPDATE",
    "DEPLOY_STYLE_UPDATE_ENTRY",
    "DEPLOY_STYLE_UPDATE_ESI_BIAS",
    "DEPLOY_STYLE_UPDATE_OBJECT_PATH",
    "DEPLOY_STYLE_UPDATE_OBJECT_PATH_BYTES",
    "DEPLOY_STYLE_UPDATE_POSITION_PATH",
    "DEPLOY_STYLE_UPDATE_POSITION_PATH_BYTES",
    "DEPLOY_STYLE_UPDATE_RESOLVED",
    "DEPLOY_STYLE_UPDATE_RESOLVED_BYTES",
    "DEPLOY_STYLE_UPDATE_RESOLVE_BRANCH",
    "DEPLOY_STYLE_UPDATE_RESOLVE_BRANCH_BYTES",
    "ENTER_HINT_CONTAIN_LOAD",
    "ENTER_HINT_CONTAIN_LOAD_BYTES",
    "ENTER_HINT_SLAUGHTER_TEST",
    "ENTER_HINT_SLAUGHTER_TEST_BYTES",
    "GATE_CLOSE_ARG_AT_READD",
    "GATE_CLOSE_ARG_TEST",
    "GATE_CLOSE_ARG_TEST_BYTES",
    "GATE_CLOSE_EPILOGUE",
    "GATE_CLOSE_EPILOGUE_BYTES",
    "GATE_CLOSE_FOR_PATHING",
    "GATE_CLOSE_FOR_PATHING_ENTRY",
    "GATE_CLOSE_READD_CALL",
    "GATE_CLOSE_READD_CALL_BYTES",
    "GATE_CLOSE_READD_SETUP",
    "GATE_CLOSE_READD_SETUP_BYTES",
    "GATE_PATHING_BRACKET_CLOSE_CALL",
    "GATE_PATHING_BRACKET_CLOSE_CALL_BYTES",
    "GATE_UPDATE_CLOSE_CALLS",
    "HERO_LEDGER_FIND_ENTRY",
    "HERO_LEDGER_FIND_ENTRY_ENTRY",
    "HERO_LEDGER_GET_ENTRY",
    "HERO_LEDGER_GET_ENTRY_ENTRY",
    "HERO_LEDGER_GET_TEMPLATE",
    "HERO_LEDGER_GET_TEMPLATE_ENTRY",
    "PATHFINDER_ADD_OBJECT",
    "PATHFINDER_ADD_OBJECT_BYTES",
    "PATH_APPEND_NODE_LINK",
    "PATH_APPEND_NODE_LINK_BYTES",
    "PATH_DESTRUCTOR",
    "PATH_DESTRUCTOR_BYTES",
    "PATH_HEAD_OFFSET",
    "PATH_NODE_NEXT_OFFSET",
    "PATH_NODE_POS_OFFSET",
    "PLAYER_GET_BUILDABLE_HERO",
    "PLAYER_GET_BUILDABLE_HERO_ENTRY",
    "SKIRMISH_AI_MANAGER_PLAYER_DATA",
    "SPELLBOOK_AI_REBUILD",
    "SPELLBOOK_AI_REBUILD_NAME",
    "SPELLBOOK_AI_TYPE_COUNT",
    "SPELLBOOK_AI_TYPE_FACTORY",
    "SPELLBOOK_AI_TYPE_FACTORY_ENTRY",
    "SPELLBOOK_AI_TYPE_JUMP_TABLE",
    "SPELLBOOK_AI_TYPE_NAMES",
    "THE_AI",
    "THE_SKIRMISH_AI_MANAGER",
    "SLAVED_IDLE_HOOK",
    "SLAVED_IDLE_FALLTHROUGH",
    "SLAVED_IDLE_GUARD",
    "SLAVED_IDLE_CTOR",
    "SLAVED_IDLE_DTOR",
    "SLAVED_IDLE_XFER",
    "SLAVED_IDLE_UPDATE",
    "SLAVED_IDLE_GUARD_MOVEMENT",
    "SLAVED_IDLE_VTABLE",
    "SLAVED_IDLE_UPDATE_VTABLE",
    "SLAVED_IDLE_HOOKS",
    "SLAVED_IDLE_ANCHORS",
]

# `AIGroup::doObjectUpgrade(UpgradeTemplate *)`: the logic side of an `OBJECT_UPGRADE` click on a
# whole selection. Nothing on its per-member path asks which command set the button came from.
AI_GROUP_DO_OBJECT_UPGRADE = 0x0076FBFB
AI_GROUP_UPGRADE_EBP = 0x08
AI_GROUP_UPGRADE_SELF_EBP = -0x04
# The member loop's top: `mov edi, [esi+8]` plus the first two argument pushes. Six bytes, three
# whole instructions. `0x0076FC15` is the loop's own back-edge target, so a hook must start exactly
# there; nothing branches into the two instructions behind it.
AI_GROUP_UPGRADE_MEMBER = 0x0076FC15
AI_GROUP_UPGRADE_MEMBER_BYTES = bytes.fromhex("8b7e086a0057")
AI_GROUP_UPGRADE_MEMBER_RESUME = 0x0076FC1B
# The member list, as the loop walks it: `[AIGroup+4]` is the sentinel node, `[node]` the next and
# `[node+8]` the member `Object`. Iteration ends when the walk comes back round to the sentinel.
AI_GROUP_MEMBER_SENTINEL = 0x04
AI_GROUP_MEMBER_OBJECT = 0x08
# `BuildAssistant::canMakeUnit(producer, what, reviveIndex)`, the gate the AI consults, and the
# labels inside it that `ai_revive_gate` needs (`docs/ai-revive-gate.md`).
CAN_MAKE_UNIT = 0x00794F38
BUILD_ASSISTANT_VTABLE = 0x00C307D8
CAN_MAKE_UNIT_VTABLE_SLOT = 0x68
# The `NEED_UPGRADE` / `NeededUpgrade` / `NeededUpgradeAny` check. Only the template branch
# reaches it; it falls through to the accept path and jumps to `..._NEXT_SLOT` on failure.
CAN_MAKE_UNIT_UPGRADE_GATE = 0x0079502A
# Where the upgrade gate falls through to on success, and where the stock revive branch jumps
# when a slot matches: resolve the player and answer the question.
CAN_MAKE_UNIT_ACCEPT = 0x007950AD
# The template the gate asks the player about, and why it has to be the wanted one. Derived
# in `docs/ai-equivalent-build-gate.md`.

#: `call ThingTemplate::isEquivalentTo` - a button stands for the wanted template when the
#: two are equivalent, so they need not be the same template.
CAN_MAKE_UNIT_EQUIVALENT_CALL = 0x0079501D
CAN_MAKE_UNIT_EQUIVALENT_CALL_BYTES = bytes.fromhex("e8a085faff")
#: `mov ecx, esi` / `call CommandButton::getThingTemplate` / `push eax` - the accept path
#: fetches the button's template as the argument of the call below. `[ebp+0xc]` is the
#: wanted one.
CAN_MAKE_UNIT_ACCEPT_TEMPLATE = 0x007950BD
CAN_MAKE_UNIT_ACCEPT_TEMPLATE_BYTES = bytes.fromhex("8bcee81881fcff50")
#: `mov ecx, ebx` / `call Player::canBuild` (`0x006AC927`, `ret 4`): not in the player's
#: disallowed set, `Buildable`, and every `Prerequisites` entry met.
CAN_MAKE_UNIT_CAN_BUILD_CALL = 0x007950C5
CAN_MAKE_UNIT_CAN_BUILD_CALL_BYTES = bytes.fromhex("8bcbe85b78f1ff")
# `BuildAssistant`'s other gate (vtable `+0x64`), which every producer-facing path asks and which
# reaches `canMakeUnit` by a virtual self-call; its return address tells AI queries apart.
CAN_MAKE_UNIT_PRODUCTION_GATE = 0x00793ECB
CAN_MAKE_UNIT_PRODUCTION_GATE_SLOT = 0x64
CAN_MAKE_UNIT_PRODUCTION_GATE_CALL = 0x00793F56
CAN_MAKE_UNIT_PRODUCTION_GATE_CALL_BYTES = bytes.fromhex("ff5068")  # call dword [eax+0x68]
# The per-slot split between the two questions: `cmp byte [ebp-1], 0` (`isRevive`) then
# `jne CAN_MAKE_UNIT_REVIVE_BRANCH`. Ten bytes, two whole instructions, no inbound edge - every
# slot passes through here, which is where `revive-object-binding` decides a bound REVIVE button
# before the positional count ever sees it.
CAN_MAKE_UNIT_REVIVE_DISPATCH = 0x00794FF1
CAN_MAKE_UNIT_REVIVE_DISPATCH_BYTES = bytes.fromhex("807dff000f85d3000000")
# The template branch the dispatch falls through to: `mov eax, [esi+0x14]` (`Command`).
CAN_MAKE_UNIT_TEMPLATE_BRANCH = 0x00794FFB
CAN_MAKE_UNIT_TEMPLATE_BRANCH_BYTES = bytes.fromhex("8b4614")
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
# `Player::getBuildableHeroName(n)` - `__thiscall`, `ret 4`, the `ThingTemplate*` of roster name n
# (the `PlayerTemplate+0x198` ring list, then `+0x18C` `BuildableHeroesMP`), or null past the end.
# The ControlBar's revive pass 1 (`0x00943FD6`) offers REVIVE slot n to exactly this hero.
PLAYER_GET_BUILDABLE_HERO = 0x006AB249
PLAYER_GET_BUILDABLE_HERO_ENTRY = bytes.fromhex("8b442404")  # mov eax, [esp+4]
# `ReviveMgr::getTemplate(index)` on `Player+0x758` - `__thiscall`, `ret 4`, the `ThingTemplate*`
# of hero-ledger entry `index`, or null.
HERO_LEDGER_GET_TEMPLATE = 0x00780C2F
HERO_LEDGER_GET_TEMPLATE_ENTRY = bytes.fromhex("ff742404")  # push dword [esp+4]
# `ReviveMgr::findEntry(ThingTemplate *what, Int id, Int ordinal)` on `Player+0x758` -
# `__thiscall`, `ret 0xc`, the ledger index or -1. Matches `what+0x64` (the template's name)
# against each entry's name, so an override resolves to its base's entry; with `id == -1` it takes
# the `ordinal`-th entry of that name. The ControlBar's pass 1 calls it at `0x0094401B`.
HERO_LEDGER_FIND_ENTRY = 0x0078131E
HERO_LEDGER_FIND_ENTRY_ENTRY = bytes.fromhex("558bec5151")
# `ReviveMgr::getEntry(index)` - `__thiscall`, `ret 4`, the entry or null.
HERO_LEDGER_GET_ENTRY = 0x00781298
HERO_LEDGER_GET_ENTRY_ENTRY = bytes.fromhex("ff742404e8")  # push dword [esp+4] / call
# The `SkirmishAI` producer picker, which lacks the under-construction check the legacy
# `AIPlayer::findFactory` makes. See `docs/ai-construction-gate.md`.

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

#: `TheAI`, registered at `0x0063BE74`..`0x0063BE87`; `TheAI + PATHFINDER_IN_AI` is the
#: `Pathfinder`, and `Pathfinder + PATHFINDER_WALL_HEIGHTS + layer*4` is a wall-height layer's
#: flat surface height.
THE_AI = 0x00DE4B40
AI_PRODUCER_ANY_BRANCH = 0x009A0784
AI_PRODUCER_ANY_BRANCH_ENTRY = bytes.fromhex("807d10007516")
# `mov eax, [esi]` - the head of the usable-producer tests: `ProductionUpdate` vtable `+0x64`
# (is it disabled) then `+0x44` (is its queue empty). `esi` is the producer's `ProductionUpdate`,
# `edi` the candidate `Object`. This is the run of tests `UNDER_CONSTRUCTION` belongs in.
AI_PRODUCER_USABLE_TESTS = 0x009A078A
# The order pump's handling of a build order that cannot start because it has no builder, and
# why one such order starves everything queued behind it. Derived in
# `docs/ai-build-queue-skip.md`.

#: `call` the order's "can this start now" (`0x00961975`, which calls the order's own vtable
#: slot `+0x40`). `eax` comes back 0 to start the order, 9 or 10 to cancel it, 2 to end the
#: walk, and 8 when the order has no builder it can use.
AI_ORDER_PUMP_CAN_START_CALL = 0x008F1020
AI_ORDER_PUMP_CAN_START_CALL_BYTES = bytes.fromhex("e850090700")
#: `cmp eax, 8` / `jne +6` / `cmp dword [ebp-8], 0` - answer 8, and whether the AI's pool of
#: free builders (the list at `AIPlayer+0x144`, counted into `[ebp-8]` before the walk) holds
#: anything.
AI_ORDER_PUMP_NO_BUILDER_TEST = 0x008F1029
AI_ORDER_PUMP_NO_BUILDER_TEST_BYTES = bytes.fromhex("83f8087506837df800")
#: `ja 0x008F1073` - with a builder in the pool, end the walk at this order. Without the
#: branch the order falls through to the pump's ordinary "not this one, next" path.
AI_ORDER_PUMP_NO_BUILDER_STOP = 0x008F1032
AI_ORDER_PUMP_NO_BUILDER_STOP_BYTES = bytes.fromhex("773f")
# `xor dl, dl` - the accept path, shared by both arms.
AI_PRODUCER_ACCEPT = 0x009A07A0
# `push dword [ebp+8]` - release this candidate and go round for the next one. Every one of the
# picker's rejection edges lands here.
AI_PRODUCER_NEXT_CANDIDATE = 0x009A07C7
# `mov eax, [eax+0x160]` / `add eax, 0x8c` / `lea edi, [esi+0x4c]` - the one place the AI's hero
# builder takes its list, copying `ArmyDefinition+0x8C` into its own `+0x4C`. The anchor that ties
# everything below to the `HeroBuildOrder` keyword: without it, `+0x4C` is just a vector of names.
AI_HERO_ARMY_DEFINITION_LIST = 0x009A10E1
AI_HERO_ARMY_DEFINITION_LIST_BYTES = bytes.fromhex("8b8060010000058c0000008d7e4c")
# The getter that list copy calls first: `__thiscall` on the hero builder, pushes its `Player*`
# (`+0x30`) and asks `TheSkirmishAIManager` for that player's AI record (`0x006A950B`, which answers
# null for a player it does not know). Keeps `esi` and `edi`; `eax`/`ecx`/`edx` are the callee's.
# The record's `+0x160` is the `ArmyDefinition` the player runs on.
AI_HERO_BUILDER_AI_DATA = 0x009A0383
AI_HERO_BUILDER_AI_DATA_BYTES = bytes.fromhex("ff71308b0d3849de00e87a91d0ffc3")
AI_DATA_ARMY_DEFINITION = 0x160
# The hero build order on the builder, `{begin, end}` at `+0x4C`/`+0x50`. Logic state: xfered at
# 0x009A11C8, so it is saved into a `.sav` and folded into the per-frame CRC.
AI_HERO_LIST_BEGIN = 0x4C
# `pickHeroIndex` - returns an index into that list. Three rules: retry an index already requested,
# else a random index in `1..count-1`, else force 0 when the player holds the Ring. No cost term
# and no clock.
AI_HERO_PICK_INDEX = 0x009A05DB
AI_HERO_PICK_INDEX_ENTRY = bytes.fromhex("b80a1fbb00")
# `createHeroBuildRequest` and its single call site. The caller runs the AI's **unit** builder when
# this answers null, so refusing a hero here costs the AI nothing but the hero.
AI_HERO_REQUEST = 0x009A0993
AI_HERO_REQUEST_ENTRY = bytes.fromhex("b84d1fbb00")
AI_HERO_REQUEST_CALL = 0x009A1063
AI_HERO_REQUEST_CALL_BYTES = bytes.fromhex("e82bf9ffff")
# `call AI_HERO_PICK_INDEX`, then `mov ecx, [esi+0x4c]` / `lea edi, [ecx+eax*4]` - what makes `edi`
# the chosen hero's `AsciiString` and `eax` its index at the site below.
AI_HERO_PICK_INDEX_CALL = 0x009A09D8
AI_HERO_PICK_INDEX_CALL_BYTES = bytes.fromhex("e8fefbffff")
AI_HERO_LIST_ELEMENT = 0x009A09DD
AI_HERO_LIST_ELEMENT_BYTES = bytes.fromhex("8b4e4c8d3c81")
# `mov ecx, [THE_THING_FACTORY]` - six bytes between "the name is resolved" and "the template is
# looked up", and the last point before anything is committed. `edi` holds the name, `eax` the
# index (**live** - it is stored to `[ebp-0x20]` one instruction later, so a cave here must
# preserve it), and `ebx`/`ecx`/`edx` are dead. A sweep of every branch displacement and imm32 in
# `.text` finds no inbound edge into the six bytes, so the only way in is fallthrough.
AI_HERO_NAME_RESOLVED = 0x009A09E3
AI_HERO_NAME_RESOLVED_BYTES = bytes.fromhex("8b0d404ade00")
AI_HERO_NAME_RESOLVED_RESUME = 0x009A09E9
# `or dword [esi+0x38], -1` - the engine's own rejection edge, reached from two stock branches at
# this same stack depth. It forgets the chosen index, so the next tick re-picks and the rest of the
# list stays reachable, then falls into the return-null tail. `[ebp-0x14]`, the local read two
# instructions later, is zeroed at 0x009A09B6 on every path that reaches here.
AI_HERO_REJECT = 0x009A0AE1
AI_HERO_REJECT_BYTES = bytes.fromhex("834e38ff")
# `AIFlagCaptureSquad::pickFlag` - the skirmish AI's flag-capture tactic choosing which capture
# flag to send a squad at. Walks the global list of every `CAPTUREFLAG` object on the map, keeps
# the nearest candidate that is not already allied, and returns it. Derived, with the whole tactic
# around it, in `docs/ai-flag-capture-gate.md`.
AI_FLAG_CAPTURE_PICKER = 0x009BC213
AI_FLAG_CAPTURE_PICKER_ENTRY = bytes.fromhex("b80739bb00")
# `cmp eax, 2` / `je AI_FLAG_CAPTURE_SKIP` - the picker's **only** ownership test, five bytes
# exactly, on the result of `Player::getRelationship(flag)`. `esi` is the candidate `Object` and
# `eax` is dead the instant this falls through, which is what makes it hookable in place.
AI_FLAG_CAPTURE_RELATIONSHIP_TEST = 0x009BC28B
AI_FLAG_CAPTURE_RELATIONSHIP_TEST_BYTES = bytes.fromhex("83f8027447")
# `mov eax, [esi+4]` - the candidate survived the ownership test and the picker goes on to require
# `KindOf CAPTUREFLAG` of it. The edge a gate has to give back to accept a flag.
AI_FLAG_CAPTURE_KEEP = 0x009BC290
# `add ebx, 4` - the loop step. Every one of the picker's rejection edges lands here, so this is
# the edge a gate takes to drop a candidate.
AI_FLAG_CAPTURE_SKIP = 0x009BC2D7
# `call AI_FLAG_CAPTURE_PICKER`, inside `AIFlagCaptureSquad::update` - the tactic's one and only
# use of the picker, and therefore what proves the function above belongs to this tactic rather
# than being a same-shaped nearest-object scan somewhere else in the subsystem.
AI_FLAG_CAPTURE_PICKER_CALL = 0x009BC477
AI_FLAG_CAPTURE_PICKER_CALL_BYTES = bytes.fromhex("e897fdffff")
# `AIFlagCaptureSquad`'s primary vtable and the slot holding the update above.
AI_FLAG_CAPTURE_SQUAD_VTABLE = 0x00C8A2FC
AI_FLAG_CAPTURE_SQUAD_UPDATE_SLOT = 0x1C
AI_FLAG_CAPTURE_SQUAD_UPDATE = 0x009BC3F4
# `push <"FlagCaptureSquad">` in the tactic's constructor - the human-legible end of the chain,
# and the one anchor that cannot be a coincidence of layout.
AI_FLAG_CAPTURE_SQUAD_NAME_PUSH = 0x009BC0A2
AI_FLAG_CAPTURE_SQUAD_NAME_PUSH_BYTES = bytes.fromhex("68d0a3c800")
# `AIFarmKillSquad`, the flag-capture tactic's sibling: a targetless tactic that sends one to three
# idle battalions at an enemy economy building. Its vtable, and the slot the tactics generator asks
# "may this run now" through. Derived in `docs/ai-farm-kill-gate.md`.
AI_FARM_KILL_SQUAD_VTABLE = 0x00C8A1E0
AI_FARM_KILL_SQUAD_RUN_GATE_SLOT = 0x04
# `__thiscall bool(arg)`, `ret 4`. Its opening is the whole of what a wrapper needs to know: the
# tactic's player sits at `+0x24` and goes to `TheSkirmishAIManager` for that player's AI record.
AI_FARM_KILL_SQUAD_RUN_GATE = 0x009BB1C4
AI_FARM_KILL_SQUAD_RUN_GATE_ENTRY = bytes.fromhex("568bf18b0d3849de0057ff7624e835e3ceff")
# `push <"FarmKillSquad">` in the tactic's constructor, which is what names the vtable above.
AI_FARM_KILL_SQUAD_NAME_PUSH = 0x009BB3D9
AI_FARM_KILL_SQUAD_NAME_PUSH_BYTES = bytes.fromhex("68aca2c800")
# The tactic's other two hooks. Slot 2 is `__thiscall void()`: it clears the player's "a squad is
# out" variable and stores the frame the next squad may form, `now + GameLogicRandomValue(lo, hi)`
# with `lo`/`hi` ten and sixty seconds. Slot 3 is `__thiscall bool(prototype, index)`, `ret 8`: it
# writes the team prototype's forbidden `KindOf` mask and its min and max size.
AI_FARM_KILL_SQUAD_RESET_SLOT = 0x08
AI_FARM_KILL_SQUAD_RESET = 0x009BB226
AI_FARM_KILL_SQUAD_RESET_ENTRY = bytes.fromhex("5657ff71248b0d3849de00")
AI_FARM_KILL_SQUAD_BUILD_SLOT = 0x0C
AI_FARM_KILL_SQUAD_BUILD = 0x009BB479
AI_FARM_KILL_SQUAD_BUILD_ENTRY = bytes.fromhex("568b74240857ff7424108bf956")
# The key of the "next run frame" variable slot 2 stores, as it pushes it, and the source path the
# tactic passes to every random-number call.
AI_FARM_KILL_SQUAD_NEXT_RUN_KEY = 0x00DEBEFC
AI_FARM_KILL_SQUAD_SOURCE_FILE = 0x00C8A218
# `__thiscall(key *, value)` on a player's AI record, `ret 8`: stores a named integer variable.
AI_DATA_SET_VALUE = 0x006C7EC5
AI_DATA_SET_VALUE_ENTRY = bytes.fromhex("ff74240481c17c010000")
# The team recruiter's per-object test: `__thiscall bool(object, prototypePart, where)` on the
# team builder, `ret 0xC`. `prototypePart` is the team prototype `+0x12C`; the test screens the
# object against the required `KindOf` mask at part `+0x1B4` and the forbidden one at `+0x1D0`.
# Its two live call sites are both in the recruiter (`0x009A2E06`).
AI_TEAM_RECRUIT_ACCEPT = 0x009A24FC
AI_TEAM_RECRUIT_ACCEPT_ENTRY = bytes.fromhex("53568b74240c85f657")
AI_TEAM_RECRUIT_ACCEPT_CALLS = (0x009A2EEB, 0x009A2FFC)
AI_TEAM_RECRUIT_FORBIDDEN_KIND_OF = 0x1D0
# The same forbidden mask and the two sizes, from the prototype's own base.
AI_TEAM_PROTOTYPE_FORBIDDEN_KIND_OF = 0x2FC
AI_TEAM_PROTOTYPE_MIN_SIZE = 0x2D4
AI_TEAM_PROTOTYPE_MAX_SIZE = 0x2D0
# The `Player*` a team builder recruits for.
AI_TEAM_BUILDER_PLAYER = 0x14
# `ArmyDefinition`: the `std::vector<ArmyMemberDefinition *>` (`begin` here, `end` four bytes on)
# and the two phase lengths, `Real` seconds.
ARMY_DEFINITION_MEMBERS = 0x04
ARMY_DEFINITION_PHASE_DURATION_RUSH = 0xB0
ARMY_DEFINITION_PHASE_DURATION_MID_GAME = 0xB4
# `ArmyMemberDefinition`: sixteen bytes - `Unit` and three percentages - allocated by its block
# parser with `push 0x10` / `call operator new`, and a four-row field table with no terminator.
ARMY_MEMBER_DEFINITION_SIZE = 0x10
ARMY_MEMBER_DEFINITION_ALLOC = 0x0082FF02
ARMY_MEMBER_DEFINITION_ALLOC_BYTES = bytes.fromhex("6a10e8d7f7bfff")
ARMY_MEMBER_DEFINITION_FIELD_TABLE = 0x00C52538
ARMY_MEMBER_DEFINITION_FIELD_TABLE_REFS = (0x0082FC89, 0x0082FF2A)
ARMY_MEMBER_DEFINITION_FIELD_TABLE_REF_OPCODES = (0xB8, 0x68)
# The player a tactic belongs to, on the squad base class every targetless tactic shares.
AI_TACTIC_PLAYER = 0x24
# `TheSkirmishAIManager`, and its `__thiscall(player)` lookup of that player's AI record - null for
# a player it does not know, `ret 4`. The record's `AI_DATA_ARMY_DEFINITION` is the
# `ArmyDefinition` the player runs on.
THE_SKIRMISH_AI_MANAGER = 0x00DE4938
SKIRMISH_AI_MANAGER_PLAYER_DATA = 0x006A950B
# The `SkirmishAI` team builder's size count, and why a team leaves with one battalion. Derived in
# `docs/ai-team-size.md`.

#: `__thiscall`, one stack argument (the `Team*`), `ret 4`: how many objects on the team carry
#: `CAN_ATTACK`, `HERO` or `SUPPORT`. A battalion's members are on its team, so it counts them.
AI_TEAM_SIZE = 0x009A24A6
AI_TEAM_SIZE_ENTRY = bytes.fromhex("558bec83ec188b4d08578d45e85033ff")
#: The loop head: `mov eax, [ebp-0x18]` (the member) / `mov eax, [eax+4]` (its template). Six
#: bytes, two whole instructions, and the target of the loop's own back-edge.
AI_TEAM_SIZE_MEMBER = 0x009A24C6
AI_TEAM_SIZE_MEMBER_BYTES = bytes.fromhex("8b45e88b4004")
#: `test byte [eax+0x108], 8` - the first of the three KindOf tests, with the template in `eax`.
AI_TEAM_SIZE_KINDOF_TESTS = 0x009A24CC
AI_TEAM_SIZE_KINDOF_TESTS_BYTES = bytes.fromhex("f6800801000008")
#: `lea ecx, [ebp-0x18]` - advance the iterator without counting.
AI_TEAM_SIZE_NEXT = 0x009A24E6
AI_TEAM_SIZE_NEXT_BYTES = bytes.fromhex("8d4de8")
#: `jne AI_TEAM_SIZE_MEMBER` - the back-edge, the only branch into the loop head.
AI_TEAM_SIZE_BACK_EDGE = 0x009A24F2
AI_TEAM_SIZE_BACK_EDGE_BYTES = bytes.fromhex("75d2")
#: The team builder update's two calls to `AI_TEAM_SIZE`, its only callers: the count the recruiter
#: starts from (it adds battalions while that is below the prototype's max, `+0x2D0`), and the
#: finished-team test (at least the min, `+0x2D4`, and either the max or enough threat).
AI_TEAM_BUILDER_RECRUIT_SIZE_CALL = 0x009A3311
AI_TEAM_BUILDER_DONE_SIZE_CALL = 0x009A33D1
# The War of the Ring AI's region graph, and why a disabled region crashes it. Derived in
# `docs/living-campaign/ai-disabled-regions.md`.

#: The AI's world model, and the region graph inside it: a `std::map<int, ...>` from region id
#: (`Region+0x14C`) to that region's neighbour lists.
AI_WORLD_MODEL = 0x00DE9F60
AI_REGION_GRAPH = 0x00DE9F9C
#: Builds the graph - only while it is empty, so once per session - from the region store.
AI_REGION_GRAPH_BUILD = 0x00908010
#: The builder's `cmp byte [region+0x1C2], 0` / `mov [ebp-0x18], ecx`, and the `je` straight after
#: it that leaves a disabled region out of the graph.
AI_REGION_GRAPH_ENABLED_TEST = 0x0090806C
AI_REGION_GRAPH_ENABLED_TEST_BYTES = bytes.fromhex("80b9c201000000894de8")
AI_REGION_GRAPH_SKIP_DISABLED = 0x00908076
AI_REGION_GRAPH_SKIP_DISABLED_BYTES = bytes.fromhex("0f8424010000")
#: The AI planner's two graph lookups that use the result without comparing it with the head node,
#: and the neighbour-list copy that faults on the zeroed value they hand it.
AI_PLANNER_UNCHECKED_LOOKUPS = (0x009A47AA, 0x009A5A5E)
AI_NEIGHBOUR_LIST_COPY = 0x00905643
AI_NEIGHBOUR_LIST_COPY_FAULT = 0x00905674
# `DeployStyleAIUpdate::aiDoCommand` - the module's whole "deploy before you attack" mechanism.
# `__thiscall`, `ret 8`; vtable slot `+0x268` (`0x00C63498`). On entry `esi` is the module and
# `edi` the `AICommandParms`, which the prologue establishes and which is what the cave of
# `deploy-before-attack` relies on. Derived in `docs/deploy-before-attack.md`.
DEPLOY_STYLE_AI_DO_COMMAND = 0x0089209F
DEPLOY_STYLE_AI_DO_COMMAND_ENTRY = bytes.fromhex("56578b7c240c8bf1")
# `cmp dword [edi+4], 2` + `je 0x008921C9` - the command-source test that sends every
# `CMD_FROM_AI` order straight to the base state machine, past the record-and-deploy path. Ten
# bytes, and the only inbound edge in `.text` lands on the first of them (the two `je`s at
# 0x008920BD and 0x008920C2, the `AICMD_IDLE` and 0x35 shortcuts), which is what makes them
# hookable.
DEPLOY_STYLE_AI_SOURCE_BRANCH = 0x008920CE
DEPLOY_STYLE_AI_SOURCE_BRANCH_BYTES = bytes.fromhex("837f04020f84f1000000")
# `mov ecx, esi` / `call 0x00891CEB` - the record-and-deploy path the branch falls through to:
# clear the recorded command, save the new one, forward it unless mid-deploy, then record what
# kind it was.
DEPLOY_STYLE_AI_RECORD_PATH = 0x008920D8
DEPLOY_STYLE_AI_RECORD_PATH_BYTES = bytes.fromhex("8bcee80cfcffff")
# `mov eax, [esi+0x574]` - the `CMD_FROM_AI` arm: snapshot what the unit was doing and hand the
# command to the base state machine. The module's own re-issues need this and keep it.
DEPLOY_STYLE_AI_BYPASS_PATH = 0x008921C9
DEPLOY_STYLE_AI_BYPASS_PATH_BYTES = bytes.fromhex("8b8674050000578d4e20")
# The whole of the `MustDeployToAttack` getter: `mov eax,[ecx+4]` (the `ModuleData`) then
# `mov al,[eax+0x6f]`. Asserting these seven bytes fixes both offsets at once.
DEPLOY_STYLE_MUST_DEPLOY_GETTER = 0x00891ED4
DEPLOY_STYLE_MUST_DEPLOY_GETTER_BYTES = bytes.fromhex("8b41048a406fc3")
# `mov [esi+0x578], ebx` in `setMyState` (0x008921E3) - where the state lives, written before the
# switch on the new value.
DEPLOY_STYLE_SET_STATE_STORE = 0x008921FE
DEPLOY_STYLE_SET_STATE_STORE_BYTES = bytes.fromhex("899e78050000")
# `mov eax,[esi-0xc]` / `cmp byte [eax+0x6f], bl` - `update`'s `READY_TO_MOVE` arm asking
# `MustDeployToAttack` before it calls `setMyState(DEPLOY)`. This is the one place the keyword
# decides anything, and it is reached only when a command has been recorded.
DEPLOY_STYLE_MOVE_ARM_MUST_DEPLOY = 0x0089296D
DEPLOY_STYLE_MOVE_ARM_MUST_DEPLOY_BYTES = bytes.fromhex("8b46f438586f")
#: The three `mov byte [esi+<flag>], 1` stores that end `aiDoCommand`'s command switch, as
#: `{va: bytes}`. They are what "a command is recorded" means, and the cave reads the same three
#: flags to tell an acquire the engine started from a re-issue the module started.
DEPLOY_STYLE_RECORD_STORES = {
    0x00892175: bytes.fromhex("c6869405000001"),  # +0x594 no explicit target
    0x008921AC: bytes.fromhex("c6869505000001"),  # +0x595 attack object
    0x0089217E: bytes.fromhex("c6869605000001"),  # +0x596 attack position
}
# The module fields the cave reads, and the state value that means "standing, weapons free".
DEPLOY_STYLE_MODULE_DATA_OFFSET = 0x04
DEPLOY_STYLE_MUST_DEPLOY_OFFSET = 0x6F
DEPLOY_STYLE_STATE_OFFSET = 0x578
DEPLOY_STYLE_STATE_READY_TO_ATTACK = 2
DEPLOY_STYLE_RECORDED_COMMAND_OFFSETS = (0x594, 0x595, 0x596)
#: The recorded-command kinds `READY_TO_MOVE` can resolve alone (attack object, attack position).
#: `+0x594` (no explicit target) is deliberately absent.
DEPLOY_STYLE_TARGETED_COMMAND_OFFSETS = (0x595, 0x596)
#: The `AICommandType` values `aiDoCommand`'s switch recognises, in the order its `cmp` chain
#: tests them: attack object / force-attack object, attack position, the attack-move and hunt
#: forms, the four guard forms, and a further attack-object form. `AICMD_ATTACK_TEAM` (0x0D) is
#: explicitly skipped, and so is everything else.
DEPLOY_STYLE_ATTACK_COMMANDS = (
    0x0B,
    0x0C,
    0x0E,
    0x0F,
    0x10,
    0x11,
    0x12,
    0x1E,
    0x1F,
    0x21,
    0x23,
    0x39,
)
# `DeployStyleAIUpdate::update` - vtable slot `+0x10` of the module (`0x00C63224`). On entry it
# biases `esi` to `this + 0x10`, so every module field it names reads 0x10 lower than the same
# field in `aiDoCommand`: `[esi-0x10]` is the module, `[esi-0xc]` the `ModuleData`, `[esi+0x568]`
# the state and `[esi+0x584..0x586]` the three recorded-command flags. `ebx` holds the weapon it
# fetched, `ebp` the owning `Object` and `edi` zero. Derived in `docs/deploy-before-attack.md`.
DEPLOY_STYLE_UPDATE = 0x0089251C
DEPLOY_STYLE_UPDATE_ENTRY = bytes.fromhex("51515355568bf18b")
DEPLOY_STYLE_UPDATE_ESI_BIAS = 0x10
# `cmp byte [esi+0x586], 0` + `je 0x00892578` - the head of the recorded-command resolution, the
# first thing `update` does once it has a weapon. Nine bytes, and no branch in `.text` lands
# inside them, which is what makes them hookable.
DEPLOY_STYLE_UPDATE_RESOLVE_BRANCH = 0x00892545
DEPLOY_STYLE_UPDATE_RESOLVE_BRANCH_BYTES = bytes.fromhex("80be8605000000742a")
# The two arms the displaced branch chooses between: a recorded attack *position* falls through
# to 0x0089254E, anything else goes to 0x00892578 to try the recorded attack *object*.
DEPLOY_STYLE_UPDATE_POSITION_PATH = 0x0089254E
DEPLOY_STYLE_UPDATE_POSITION_PATH_BYTES = bytes.fromhex("6a01d9ee51d9")
DEPLOY_STYLE_UPDATE_OBJECT_PATH = 0x00892578
DEPLOY_STYLE_UPDATE_OBJECT_PATH_BYTES = bytes.fromhex("80be8505000000")
# `xor ebp, ebp` - where every arm of the resolution rejoins, with `edi` holding the resolved
# target (zero when there is none) and `[esp+0x11]`/`[esp+0x12]` holding the range answer. The
# cave jumps here after it has already decided, so the stock code runs on with nothing resolved.
DEPLOY_STYLE_UPDATE_RESOLVED = 0x008926E7
DEPLOY_STYLE_UPDATE_RESOLVED_BYTES = bytes.fromhex("33ed80be87050000")
# `setMyState`, `__thiscall` on the module with the new state as its only argument. Its `DEPLOY`
# arm opens with `aiIdle(CMD_FROM_AI)`, which is what takes the attack away from the base state
# machine while the unit stands up.
DEPLOY_STYLE_SET_MY_STATE = 0x008921E3
DEPLOY_STYLE_SET_MY_STATE_BYTES = bytes.fromhex("b8b30eba00e803ad")
DEPLOY_STYLE_STATE_READY_TO_MOVE = 0
DEPLOY_STYLE_STATE_DEPLOY = 1
# `AIUpdateInterface::getActiveAttackMachine` - scans the attack-machine slots at `this+0x20c`
# and returns the index of the one that is running, or -1. `__thiscall`, no arguments. Only some
# attack forms allocate one: a unit attacking out of its guard machine leaves the slots null, which
# is why this is *not* the question `deploy-before-attack` asks. Kept because `update` itself calls
# it at 0x008925D7.
AI_ACTIVE_ATTACK_MACHINE = 0x0066243F
AI_ACTIVE_ATTACK_MACHINE_BYTES = bytes.fromhex("565733ff8db10c0200")
# `AIUpdateInterface::getCurrentVictim`: the one field that sees an attack however the engine
# started it; it is cleared on the victim's death.
AI_CURRENT_VICTIM = 0x00668303
AI_CURRENT_VICTIM_BYTES = bytes.fromhex("8b414085c0740d8b0d2c41de00")
AI_CURRENT_VICTIM_ID_OFFSET = 0x40
AI_SET_CURRENT_VICTIM = 0x006682B1
AI_SET_CURRENT_VICTIM_BYTES = bytes.fromhex("8b44240485c0568bf1753d")
# `AIUpdateInterface::getAttackMachineTarget(index)` - the `Object*` that machine is attacking,
# or NULL. `__thiscall`, `ret 4`.
AI_ATTACK_MACHINE_TARGET = 0x006622E6
AI_ATTACK_MACHINE_TARGET_BYTES = bytes.fromhex("558bec83ec0c8b4508")
# `AIAttackApproachTargetState`, the state a unit runs while walking to the target of a direct
# attack order. Its vtable is installed at 0x00744328; the class-name getter at 0x007443BA reads
# back "AIAttackApproachTargetState". `computePath` is the vtable `+0x44` slot and is named by its
# own debug trace, "CritterDesync: ComputePath10". See `docs/ranged-approach-overshoot.md`.
ATTACK_APPROACH_VTABLE = 0x00C28C70
ATTACK_APPROACH_UPDATE_INTERNAL = 0x00749D46
ATTACK_APPROACH_UPDATE_INTERNAL_BYTES = bytes.fromhex("558bec83ec2c568bf18b")
ATTACK_APPROACH_COMPUTE_PATH = 0x00749A3E
ATTACK_APPROACH_COMPUTE_PATH_BYTES = bytes.fromhex("558bec83ec24803d8591")
#: The state's goal position, handed to the pathfinder. `computePath` fills it with the victim's
#: own position and never pulls it back by the weapon's range.
ATTACK_APPROACH_GOAL_POS_OFFSET = 0x20
#: The state byte that permits it to end because the target is in range. `updateInternal` derives
#: it from `AI_GOAL_IS_OBJECT_OFFSET` every frame, forces it on while the unit is blocked, and
#: forces it off for a `MeleeWeapon`.
ATTACK_APPROACH_MAY_STOP_OFFSET = 0x6E
# The `sete` that derives it: `cmp byte [edi+0x3b2], 0` / `sete al` / the blocked-wait override /
# `mov [esi+0x6e], al`. An object goal makes `al` zero, which is what strands a ranged unit on top
# of its target.
ATTACK_APPROACH_MAY_STOP_GATE = 0x00749D83
ATTACK_APPROACH_MAY_STOP_GATE_BYTES = bytes.fromhex("80bfb2030000000f94c0807e710088466e")
#: `AIUpdateInterface`'s flag for what the current move goal is: 1 an object, 0 a position. Written
#: by both setters below, read at 0x00669049 and 0x00749D83.
AI_GOAL_IS_OBJECT_OFFSET = 0x3B2
# `AIUpdateInterface::setGoalObject(ObjectID, const Coord3D *)` - `__thiscall`, the id first. Sets
# the goal object at `this+0x144`, the position at `+0x148`, and `AI_GOAL_IS_OBJECT_OFFSET` to 1.
AI_SET_GOAL_OBJECT = 0x00663802
AI_SET_GOAL_OBJECT_BYTES = bytes.fromhex("803d8591de00005356")
# `AIUpdateInterface::setGoalPosition(const Coord3D *, Bool)` - the sibling that clears the goal
# object and `AI_GOAL_IS_OBJECT_OFFSET` instead.
AI_SET_GOAL_POSITION = 0x00667ED1
AI_SET_GOAL_POSITION_BYTES = bytes.fromhex("538bd983bbdc010000")
# `AICommandParms`, from its constructor 0x007536DD: the command type is the first dword and the
# `CommandSourceType` the second. Source 2 is the engine's own AI - what auto-acquire issues with,
# and what the module re-issues its own attacks with.
AI_COMMAND_TYPE_OFFSET = 0x00
AI_COMMAND_SOURCE_OFFSET = 0x04
AI_COMMAND_SOURCE_FROM_AI = 2
#: `AICommandParms::m_obj`, the command's target: NULL when the object is gone, since `reconstitute`
#: does not check. It is `[ebp+0x1c]` in the transfer check's frame.
AI_COMMAND_OBJECT_EBP = 0x1C
# `AIUpdateInterface::isCommandWorthTransferring(AICommandParms)` - the mount swap's "should the
# replacement object inherit this pending order" test. `__thiscall` on the AIUpdate with the
# parms by value (`ret 0xc0`), answering in `al`: **non-zero means do not transfer**. Switches on
# the command type and, for the arms that name an object, measures the distance from the owner to
# the target against the locomotor's `+0x3c`. Derived in `docs/ai-command-null-target.md`.
AI_COMMAND_TRANSFER_CHECK = 0x0066C2BF
AI_COMMAND_TRANSFER_CHECK_ENTRY = bytes.fromhex("b8fc72b800e8270c")
# `xor ebx, ebx` + `inc ebx` - where the answer is seeded to 1 ("not worth transferring"). Every
# arm that decides otherwise clears `bl`; the tail reads it back out. Anchored because the guard
# jumps into that tail and has to know what the register there means.
AI_COMMAND_TRANSFER_BOOL_INIT = 0x0066C2D1
AI_COMMAND_TRANSFER_BOOL_INIT_BYTES = bytes.fromhex("33db43")
# `mov eax, [ecx+8]` - the head of the object-target arm, reached for command types 1
# (`AICMD_MOVE_TO_OBJECT`), 0x48 and 0x49. `[ecx+8]` is the AIUpdate's owning `Object`, whose
# position the arm reads before it reads the target's.
AI_COMMAND_TRANSFER_OBJECT_ARM = 0x0066C3FB
AI_COMMAND_TRANSFER_OBJECT_ARM_BYTES = bytes.fromhex("8b4108")
# `mov eax, [ebp+0x1c]` - the load of `AICommandParms::m_obj`. Anchoring these three bytes is
# what pins `AI_COMMAND_OBJECT_EBP` to this frame: the guard tests whatever this instruction
# produced, so a build that read the target from a different slot fails here.
AI_COMMAND_TRANSFER_TARGET_LOAD = 0x0066C40D
AI_COMMAND_TRANSFER_TARGET_LOAD_BYTES = bytes.fromhex("8b451c")
# `subss xmm0, dword [eax+0x38]` - **the faulting instruction**, and the hook window. Five bytes,
# exactly one `jmp rel32`, and nothing in `.text` branches into its interior.
AI_COMMAND_TRANSFER_TARGET_USE = 0x0066C410
AI_COMMAND_TRANSFER_TARGET_USE_BYTES = bytes.fromhex("f30f5c4038")
# `subss xmm1, dword [eax+0x3c]` - where the displaced instruction returns to.
AI_COMMAND_TRANSFER_RESUME = 0x0066C415
AI_COMMAND_TRANSFER_RESUME_BYTES = bytes.fromhex("f30f5c483c")
# `or dword [ebp-4], 0xffffffff` - the shared tail every arm reaches: restore the SEH state, free
# the parms' waypoint vector at `[ebp+0x28]` if it has one, then `mov al, bl` and return. The
# guard jumps here with `bl` set, which is what makes it answer without duplicating the cleanup.
AI_COMMAND_TRANSFER_ANSWER = 0x0066C470
AI_COMMAND_TRANSFER_ANSWER_BYTES = bytes.fromhex("834dfcff")
# `mov al, bl` - the tail reading the answer back out of `bl`, four instructions later.
AI_COMMAND_TRANSFER_ANSWER_READ = 0x0066C483
AI_COMMAND_TRANSFER_ANSWER_READ_BYTES = bytes.fromhex("8ac3")
# The two calls to `AI_COMMAND_TRANSFER_CHECK`, both inside
# `ToggleMountedSpecialAbilityUpdate` - the mount swap at 0x008B140D and its sibling. Their five
# bytes *are* the displacement, so asserting them asserts that the function this patch edits is
# the one the swap reaches.
AI_COMMAND_TRANSFER_MOUNT_CALL = 0x008B1644
AI_COMMAND_TRANSFER_MOUNT_CALL_BYTES = bytes.fromhex("e876acdbff")
AI_COMMAND_TRANSFER_DISMOUNT_CALL = 0x008B24C3
AI_COMMAND_TRANSFER_DISMOUNT_CALL_BYTES = bytes.fromhex("e8f79ddbff")
AI_UPDATE_LOCOMOTOR_SET_SPEED = 0x1F8
AI_UPDATE_SET_LOCOMOTOR_SET = 0x006680B2
AI_UPDATE_SET_LOCOMOTOR_SET_SPEED_STORE = 0x006680FB
# The skirmish AI's spellbook target pickers (`docs/ai-rebuild-gate.md`): name -> index -> factory
# case -> vtable slot 7, each link asserted as bytes.

#: The `SpecialPowerAIType` name table, walked by the parse function at 0x00992693 with a
#: case-insensitive compare. `SPELLBOOK_AI_TYPE_NAMES + 4*index` is a `const char *`.
SPELLBOOK_AI_TYPE_NAMES = 0x00DB84F8
SPELLBOOK_AI_TYPE_COUNT = 53
#: `mov eax, [ebp+8]` / `push 0x34` / `pop esi` / `cmp eax, esi` / `ja` - the factory that turns a
#: parsed type index into a behaviour object, and the jump table it dispatches through.
#: `SPELLBOOK_AI_TYPE_JUMP_TABLE + 4*index` is the case address.
SPELLBOOK_AI_TYPE_FACTORY = 0x0099272E
SPELLBOOK_AI_TYPE_FACTORY_ENTRY = bytes.fromhex("8b4508566a345e3bc60f")
SPELLBOOK_AI_TYPE_JUMP_TABLE = 0x00992EFE
#: `AI_SPELLBOOK_REBUILD`'s index in that table, and the string it is the index of. The name is
#: anchored rather than trusted so "index 31 is the rebuild type" is proved from the image.
SPELLBOOK_AI_REBUILD = 31
SPELLBOOK_AI_REBUILD_NAME = 0x00C87A24
#: `push 0x2c` / `call OPERATOR_NEW` - the factory's case for `SPELLBOOK_AI_REBUILD`, and the
#: `call` to the behaviour's constructor 28 bytes into it. The call's rel32 *is* the constructor's
#: address, so asserting its five bytes asserts the target.
AI_REBUILD_FACTORY_CASE = 0x00992D50
AI_REBUILD_FACTORY_CASE_CALL = 0x00992D6C
AI_REBUILD_FACTORY_CASE_CALL_BYTES = bytes.fromhex("e89a490500")  # call 0x009E770B
#: The behaviour's constructor, planted whole because its last instruction is the vtable write
#: (`mov dword [esi], 0xC8DEEC`) - which is what makes `AI_REBUILD_BEHAVIOR_VTABLE` a derived fact
#: rather than a claim.
AI_REBUILD_BEHAVIOR_CTOR = 0x009E770B
AI_REBUILD_BEHAVIOR_CTOR_BYTES = bytes.fromhex("568bf1e858a50100c706ecdec800")
#: The behaviour's vtable, and the slot the type-specific target picker sits in. Slots 0-6 are
#: shared with every other spellbook behaviour; slot 7 is the only one the class owns.
#: `AI_REBUILD_BEHAVIOR_VTABLE + AI_REBUILD_PICKER_VTABLE_SLOT` holds `AI_REBUILD_PICKER`.
AI_REBUILD_BEHAVIOR_VTABLE = 0x00C8DEEC
AI_REBUILD_PICKER_VTABLE_SLOT = 0x1C
#: `push ebx` / `push ebp` / `push esi` / `mov ebp, ecx` - `AI_SPELLBOOK_REBUILD`'s target picker,
#: `__thiscall` on the behaviour with the caster `Object *` on the stack, `ret 4`. It walks
#: `TheSkirmishAIManager`'s per-player structure list and takes the first entry below half health.
#: Nothing in `.text` branches to it: the vtable slot above is the only way in, which is what
#: makes the patch AI-only without a return-address test.
AI_REBUILD_PICKER = 0x009E7744
AI_REBUILD_PICKER_ENTRY = bytes.fromhex("5355568be9")
#: `mov ecx, [ebx+0x25C]` - the candidate's `Object::m_body`, fetched two instructions after
#: `findObjectByID` returned it in `ebx`. Six bytes, and the only inbound edge is fallthrough, so
#: this is the hook site: the last point before the health test at which the candidate can still
#: be rejected.
AI_REBUILD_BODY_FETCH = 0x009E777C
AI_REBUILD_BODY_FETCH_BYTES = bytes.fromhex("8b8b5c020000")
#: `mov eax, [ecx]` - where the cave resumes, planted through the accept branch rather than just
#: its first two bytes: `call [eax+0x14]` is `BODY_GET_HEALTH_RATIO_SLOT`, `fld [0xBD869C]` loads
#: the 0.5, `fcomip st(1)` compares it *against* the ratio and pops, and `ja` is therefore taken
#: when the ratio is **below** half. Asserting the run pins the reading the gate is placed on.
AI_REBUILD_HEALTH_TEST = 0x009E7782
AI_REBUILD_HEALTH_TEST_BYTES = bytes.fromhex("8b01ff5014d9059c86bd00dff1ddd87711")
#: The `0.5f` that test compares against. A pooled constant - the cast step at 0x00993071 reads
#: the same four bytes for its coin flip - so it is recorded for reading, never for writing.
AI_REBUILD_HEALTH_THRESHOLD = 0x00BD869C
#: `add esi, 4` / `cmp esi, [edi+4]` / `jne` - the picker's own next-candidate edge and the loop
#: test. A rejected candidate lands here rather than at the `ret`, so one construction site does
#: not hide a genuinely damaged building further down the list.
AI_REBUILD_NEXT_CANDIDATE = 0x009E7793
AI_REBUILD_NEXT_CANDIDATE_BYTES = bytes.fromhex("83c6043b770475d2")

# Gate closing and in-flight paths (`docs/gate-close-pathfinding.md` §8). A path planned while a
# gate was open is never re-checked when it closes; these are the pieces the `gate-close-repath`
# cave uses to make such a unit plan again.

#: `GateOpenAndCloseBehavior` "close for pathing": `+0x2C := 1`, pull the gate out of the pathfind
#: map, flip its `GeometryForOpen` / `GeometryForClosed` shapes, put it back. `__thiscall` on the
#: module, one `Bool` argument, `ret 4`. The opening `cmp [esi+0x2c], 1` / `je` is the early exit
#: for a gate already closed for pathing, so everything past it runs once per close.
GATE_CLOSE_FOR_PATHING = 0x0089C9FA
GATE_CLOSE_FOR_PATHING_ENTRY = bytes.fromhex("565733ff8bf147397e2c7479")
#: `call 0x006E85E9` - the re-add at the end of close-for-pathing, with `ecx` the pathfinder and
#: the gate `Object *` pushed just before. The last thing the function does before its epilogue.
GATE_CLOSE_READD_CALL = 0x0089CA78
GATE_CLOSE_READD_CALL_BYTES = bytes.fromhex("e86cbbe4ff")
#: The run around it: `mov eax, [TheAI]` / `mov ecx, [eax+0x10]` / `push ebx` before, and the
#: `pop ebp` / `pop ebx` / `pop edi` / `pop esi` / `ret 4` epilogue after - nothing reads `eax`
#: once the call returns.
GATE_CLOSE_READD_SETUP = 0x0089CA6F
GATE_CLOSE_READD_SETUP_BYTES = bytes.fromhex("a1404bde008b481053")
GATE_CLOSE_EPILOGUE = 0x0089CA7D
GATE_CLOSE_EPILOGUE_BYTES = bytes.fromhex("5d5b5f5ec20400")
#: The function's `Bool` argument says whether the gate is really shutting. Close-for-pathing has
#: three live callers and only two of them close a gate: the two in the module's `update`
#: (`GATE_UPDATE_CLOSE_CALLS`) pass `1`. The third is the pathfinder's bracket - before a player's
#: queued path requests are served, the gate manager (`0x008ED6DC`, called from `0x008EDE5B`)
#: closes for pathing every gate that player is an enemy of, and `0x008ED726` opens them again
#: straight after (`0x008EDEA2`). That is what makes an open gate a wall to an enemy's planner, it
#: runs on an open gate about once a logic frame, and it passes `0`
#: (`GATE_PATHING_BRACKET_CLOSE_CALL`: `test eax, eax` / `jne` / `push eax`). Seen live 2026-10-13:
#: `module+0x2C` going `2 -> 1 -> 2` every frame on a gate standing open at 100%.
#: `GATE_CLOSE_ARG_TEST` is the function's own read of the argument, `cmp byte [esp+0xc], 0` two
#: pushes in, which is what puts it at `[esp+0x1c]` when the re-add call is entered.
GATE_CLOSE_ARG_TEST = 0x0089CA06
GATE_CLOSE_ARG_TEST_BYTES = bytes.fromhex("807c240c007405e847fdffff")
GATE_CLOSE_ARG_AT_READD = 0x1C
GATE_UPDATE_CLOSE_CALLS = {
    0x0089CDFB: bytes.fromhex("6a018d4eece8f5fbffff"),
    0x0089CE72: bytes.fromhex("6a018d4eece87efbffff"),
}
GATE_PATHING_BRACKET_CLOSE_CALL = 0x008ED700
GATE_PATHING_BRACKET_CLOSE_CALL_BYTES = bytes.fromhex("85c07508508bcfe8eef2faff")
#: `Pathfinder::addObjectToPathfindMap(Object *)` - a wrapper over
#: `addOrRemoveObjectFromPathfindMap` (`0x00936B7D`) with the add flag set. `__thiscall`, `ret 4`.
PATHFINDER_ADD_OBJECT = 0x006E85E9
PATHFINDER_ADD_OBJECT_BYTES = bytes.fromhex("6a006a006a01ff742410e885e52400c20400")

#: `AIUpdateInterface::destroyPath` - free `m_path`, clear it, clear `m_waitingForPath`, the
#: blocked-and-stuck byte and `AI_GOAL_IS_OBJECT_OFFSET`, then tail-jump to vtable `+0x220`
#: (`0x00662997`, locomotor goal := none). `__thiscall`, no arguments; 45 engine callers.
AI_DESTROY_PATH = 0x0066276B
AI_DESTROY_PATH_BYTES = bytes.fromhex(
    "53568bf1578dbe400100008b1f85db740e8bcbe87c3f100053e817cfdcff598327008b065f"
    "c686b103000000c686b803000000c686b2030000008bce5e5bffa020020000"
)
#: `AIUpdateInterface::m_path` (`Path *`, NULL when the unit has none) and `m_waitingForPath`
#: (set while a request sits in the pathfinder's queue), as `destroyPath` clears them.
AI_PATH_OFFSET = 0x140
AI_WAITING_FOR_PATH_OFFSET = 0x3B1
#: `AIUpdateInterface::getCurrentStateID` - the id of the main state machine's current state,
#: `0xF423F` when it has none. `__thiscall`, no arguments, touches only `eax`.
AI_CURRENT_STATE_ID = 0x00660AC1
AI_CURRENT_STATE_ID_BYTES = bytes.fromhex("8b41308b400485c074048b4004c3b83f420f00c3")
#: The one main-machine state in which `AIInternalMoveToState::update` (`0x00748E46`) can reach its
#: tail with no path: with this state current and the unit near its goal, a missing path skips the
#: recompute and falls to `0x0074927C`, which reads `[m_path+8]` unguarded. The cave leaves units in
#: this state alone.
AI_STATE_NO_PATH_UNSAFE = 0x47
#: `mov ecx, [ebx+0x260]` / `call AI_CURRENT_STATE_ID` / `cmp eax, 0x47` - where the move state
#: tests for that state, and the unguarded read it protects.
AI_MOVE_UPDATE_STATE_TEST = 0x0074911B
AI_MOVE_UPDATE_STATE_TEST_BYTES = bytes.fromhex("8b8b60020000e89b79f1ff83f847")
AI_MOVE_UPDATE_UNGUARDED_PATH_READ = 0x0074927C
AI_MOVE_UPDATE_UNGUARDED_PATH_READ_BYTES = bytes.fromhex("8b8640010000f30f1047208b4008")
#: `cmp [ebp-8], 0` / `mov byte [ebp-1], 0` / `jne` / `mov byte [ebp-1], 1` - the move state's
#: "no path -> force a recompute" test, which is what turns a destroyed path into a new plan.
AI_MOVE_UPDATE_NO_PATH_RECOMPUTE = 0x00748F35
AI_MOVE_UPDATE_NO_PATH_RECOMPUTE_BYTES = bytes.fromhex("837df800c645ff007504c645ff01")

#: `Path`: `+4` the first `PathNode`, `+8` the last. `PathNode`: `+0` next, `+4` previous, `+0xC`
#: the position (`Coord3D`), `+0x20` the layer. Read from `Path::appendNode` (`0x00665429`) and the
#: node walk in `Path::~Path` (`0x007666FF`).
PATH_HEAD_OFFSET = 0x04
PATH_NODE_NEXT_OFFSET = 0x00
PATH_NODE_POS_OFFSET = 0x0C
PATH_APPEND_NODE_LINK = 0x00665480
PATH_APPEND_NODE_LINK_BYTES = bytes.fromhex("8b4e0885c974058901894804")
PATH_DESTRUCTOR = 0x007666FF
PATH_DESTRUCTOR_BYTES = bytes.fromhex("8b410485c07411568b3050e899ebefff85f6598bc675f15e")

# `AISpecialPowerUpdate`: the per-object module that owns one AI hook. See
# `docs/ai-power-model-condition.md`.

#: `mov dword [esi+0x10], 0xC6D948` - the module's constructor (`0x008B703A`) stamping its
#: `UpdateModuleInterface` vtable, whose slot 0 is `AI_POWER_TICK`. Inside the tick `esi` is that
#: interface, so the module's own fields read at `esi-0x10`: the `Object` at `esi-8`, the bound
#: flag at `esi+0x11` and the type behaviour at `esi+0x14`.
AI_POWER_UPDATE_CTOR_VTABLE_WRITE = 0x008B7062
AI_POWER_UPDATE_CTOR_VTABLE_WRITE_BYTES = bytes.fromhex("c7461048d9c600")
AI_POWER_UPDATE_TICK_VTABLE = 0x00C6D948
#: `push ebx` / `push esi` / `mov esi, ecx` / `xor ebx, ebx` - `AISpecialPowerUpdate::update`.
#: It binds the hook's button on its first run, asks whether the power is ready, then hands the
#: coin flip, the type's picker and the cast to `0x00993055`.
AI_POWER_TICK = 0x008B73B7
AI_POWER_TICK_ENTRY = bytes.fromhex("53568bf133db")
#: The type behaviour's `CommandButton *`, set by the bind. The tick has already tested it for
#: NULL (`0x008B7437`) before the hook site.
AI_POWER_UPDATE_BUTTON_OFFSET = 0x0C
#: From the button load through the ready check (`0x008B708B`: a status test, `canUseSpecialPower`,
#: the power module ready) to the `call 0x00993055` that picks and casts. The call's rel32 is its
#: target, so asserting the run pins both the ready test the hook follows and the cast it gates.
AI_POWER_READY_WINDOW = 0x008B7431
AI_POWER_READY_WINDOW_BYTES = bytes.fromhex(
    "8b46148b400c3bc374638b40443bc3578b7ef4740b508d4ef0e83cfcffffeb02b0013ac3743c8a4f198b46f8"
    "518a4f18518b4e1450e8eabb0d00"
)
#: `mov cl, [edi+0x19]` / `mov eax, [esi-8]` - the first two argument loads for the cast step,
#: reached only once the power is ready. Six bytes, fallthrough only: the hook site.
AI_POWER_TICK_HOOK = 0x008B7457
AI_POWER_TICK_HOOK_BYTES = bytes.fromhex("8a4f198b46f8")
AI_POWER_TICK_RESUME = 0x008B745D
#: `mov ecx, [esi+0x14]` / `mov eax, [ecx]` / `pop edi, esi, ebx` / `jmp [eax+0x10]` - the exit
#: every "did not cast" edge takes, the not-ready one included: it tail-calls the behaviour's
#: next-wake computation.
AI_POWER_NOT_CAST = 0x008B7493
AI_POWER_NOT_CAST_BYTES = bytes.fromhex("8b4e148b015f5e5bff6010")

# Entering a container, and the sites that ask the target's contain about one particular rider.
# Derived in `docs/multi-contain.md`.

#: `ActionManager::canEnterObject(Object *rider, Object *target, CommandSourceType, Int mode,
#: Bool checkCapacity, Bool *outFlag)`, `__thiscall` on `[THE_ACTION_MANAGER]`, `ret 0x18`. The
#: test behind the client's enter command (context kinds 8, 9 and 15) and the enter states' own
#: re-check every frame; twelve callers in all.
ACTION_MANAGER_CAN_ENTER_OBJECT = 0x0082CBD5
#: `mov ebx, [edi+0x258]` / `test ebx, ebx` / `je fail`: the target's contain, loaded once with
#: `esi` the rider and `edi` the target. Every contain question the predicate asks after this one
#: is asked of `ebx`.
CAN_ENTER_OBJECT_CONTAIN_LOAD = 0x0082CC38
CAN_ENTER_OBJECT_CONTAIN_LOAD_BYTES = bytes.fromhex("8b9f5802000085db0f846f010000")
#: `(Object *target, list<Drawable *> *selection)`, `ret 8`: the hint (cursor) for entering
#: `target` with the current selection - `0xCB` when the contain answers
#: `CONTAIN_IS_SLAUGHTER_SLOT`, otherwise `0xB9`, `0xBA` or `0xCC`.
ACTION_MANAGER_ENTER_HINT = 0x0082CEFB
#: `mov ebx, [edi+0x258]` / `test ebx, ebx` / `je`: `edi` the target and `esi` the selection,
#: already known not to be empty. The first selected drawable is `[[[esi]]+8]`.
ENTER_HINT_CONTAIN_LOAD = 0x0082CF1A
ENTER_HINT_CONTAIN_LOAD_BYTES = bytes.fromhex("8b9f5802000085db0f8499000000")
#: `mov eax, [ebx]` / `mov ecx, ebx` / `call [eax+0x30]` / `test al, al` / `mov eax, 0xCB`: the
#: slaughter test, asked of the `ebx` the load above produced.
ENTER_HINT_SLAUGHTER_TEST = 0x0082CFB1
ENTER_HINT_SLAUGHTER_TEST_BYTES = bytes.fromhex("8b038bcbff503084c0b8cb000000")

#: An AI `State`'s vtable: `+0` the name, `+4` the destructor, then the three the machine drives.
AI_STATE_ON_ENTER_SLOT = 0x08
AI_STATE_ON_EXIT_SLOT = 0x0C
AI_STATE_UPDATE_SLOT = 0x10
#: `AIEnterState`, the state a unit runs to walk into a container; its slot 0 returns the string
#: `"AIEnterState"` at `0x00C29538`. In all three routines `[this+0x18]+0x14` is the rider, and the
#: target is the state's goal object (`0x008DBACE`) or, in `onExit`, its `ObjectID` at `this+0x4C`.
AI_ENTER_STATE_VTABLE = 0x00C294F8
AI_ENTER_STATE_ON_ENTER = 0x007515E1
AI_ENTER_STATE_ON_EXIT = 0x00752B0F
AI_ENTER_STATE_UPDATE = 0x00756067
#: `onEnter`, past its `canEnterObject`: `mov ecx, [ebx+0x258]` / `cmp ecx, edi` /
#: `mov [esp+0x14], ecx` / `je`. The contain's entry position (`+0x158`) becomes the walk's goal
#: and the rider is recorded through `CONTAIN_RIDER_INTENT_SLOT`. `ebx` target, `esi` rider.
AI_ENTER_ON_ENTER_CONTAIN_LOAD = 0x00751645
AI_ENTER_ON_ENTER_CONTAIN_LOAD_BYTES = bytes.fromhex("8b8b580200003bcf894c241474578b01")
#: `update`'s goal refresh: `mov ecx, [ebp+0x258]` / `test ecx, ecx` / `je` / entry position.
#: `ebp` target, `ebx` rider.
AI_ENTER_UPDATE_ENTRY_LOAD = 0x007560AB
AI_ENTER_UPDATE_ENTRY_LOAD_BYTES = bytes.fromhex("8b8d5802000085c9740c8b01ff9058010000")
#: `update`'s arrival: `mov esi, [ebp+0x258]` / `cmp esi, edi` / `je` / entry position, then a
#: distance test and `addToContain(rider)` (`+0x9C`) on the same `esi`. `ebp` target, `ebx` rider.
AI_ENTER_UPDATE_ADD_LOAD = 0x0075618C
AI_ENTER_UPDATE_ADD_LOAD_BYTES = bytes.fromhex("8bb5580200003bf774648b068bceff9058010000")
#: `onExit`: `mov ecx, [eax+0x258]` / `test ecx, ecx` / `je out` / `mov eax, [ecx]` / `push 2` /
#: `push ebx` / `call [eax+0x44]` - the release of the rider recorded on enter. `eax` the target,
#: found again from its id, `ebx` the rider; `out` is the next instruction.
AI_ENTER_ON_EXIT_RELEASE = 0x00752B5B
AI_ENTER_ON_EXIT_RELEASE_BYTES = bytes.fromhex("8b885802000085c974088b016a0253ff5044")
#: `AIEnterAndAttackState`, entering a container an enemy holds. Slot 0 returns
#: `"AIEnterAndAttackState"` at `0x00C295E8`; the three routines mirror `AIEnterState`'s.
AI_ENTER_AND_ATTACK_STATE_VTABLE = 0x00C295A8
AI_ENTER_AND_ATTACK_STATE_ON_ENTER = 0x00751777
AI_ENTER_AND_ATTACK_STATE_ON_EXIT = 0x00752B73
AI_ENTER_AND_ATTACK_STATE_UPDATE = 0x0075620A
#: `mov ecx, [edi+0x258]` / `test ecx, ecx` / `mov [ebp-4], ecx` / `je` / entry position.
#: `edi` target, `esi` rider.
AI_ENTER_AND_ATTACK_ON_ENTER_CONTAIN_LOAD = 0x007517E7
AI_ENTER_AND_ATTACK_ON_ENTER_CONTAIN_LOAD_BYTES = bytes.fromhex(
    "8b8f5802000085c9894dfc74288b01ff9058010000"
)
#: `mov ebp, [ebp+0x258]` / `cmp ebp, esi` / `je` / `addToContain(ebx)`. `ebp` is the target and
#: then its contain; `ebx` the rider.
AI_ENTER_AND_ATTACK_UPDATE_ADD_LOAD = 0x00756368
AI_ENTER_AND_ATTACK_UPDATE_ADD_LOAD_BYTES = bytes.fromhex(
    "8bad580200003bee740c8b4500538bcdff909c000000"
)
#: The same 18 bytes as `AI_ENTER_ON_EXIT_RELEASE`, with the same registers.
AI_ENTER_AND_ATTACK_ON_EXIT_RELEASE = 0x00752BDC
AI_ENTER_AND_ATTACK_ON_EXIT_RELEASE_BYTES = AI_ENTER_ON_EXIT_RELEASE_BYTES
#: `AIGroup`'s pre-enter filter, `(command)`, `ret 4`, run before the group hands out enter
#: orders: each member the target's contain refuses is dropped from the group, and the command
#: fails if that empties it. The target `Object` is `[command+AI_GROUP_ENTER_FILTER_TARGET]`.
AI_GROUP_ENTER_FILTER = 0x0076F518
AI_GROUP_ENTER_FILTER_TARGET = 0x0C
#: The per-member question: `mov eax, [esi]` / `push 1` / `push 0` / `push ebx` / `mov ecx, esi` /
#: `call [eax+0x98]`, with `esi` the contain loaded once outside the loop, `ebx` the member and
#: `ebp` the filter's frame. Followed by `test al, al` / `jne keep`.
AI_GROUP_ENTER_FILTER_MEMBER_TEST = 0x0076F540
AI_GROUP_ENTER_FILTER_MEMBER_TEST_BYTES = bytes.fromhex("8b066a016a00538bceff909800000084c0750d")


# RotWK 2.01 SlavedUpdate contracts; see docs/slaved-update-idle.md.
SLAVED_IDLE_HOOK = 0x008A615A
SLAVED_IDLE_FALLTHROUGH = 0x008A615F
SLAVED_IDLE_GUARD = 0x008A6181
SLAVED_IDLE_CTOR = 0x008A4F67
SLAVED_IDLE_DTOR = 0x008A4EFC
SLAVED_IDLE_XFER = 0x008A51F6
SLAVED_IDLE_UPDATE = 0x008A5D00
SLAVED_IDLE_GUARD_MOVEMENT = 0x008A567E
SLAVED_IDLE_VTABLE = 0x00C6890C
SLAVED_IDLE_UPDATE_VTABLE = 0x00C68844
SLAVED_IDLE_HOOKS = {
    0x008A615A: bytes.fromhex("77258b45f4"),
    0x008A4F67: bytes.fromhex("56ff74240c"),
    0x008A4EFC: bytes.fromhex("c7010c89c600"),
    0x008A51F6: bytes.fromhex("558bec568b7508"),
}
SLAVED_IDLE_ANCHORS = {
    SLAVED_IDLE_VTABLE: bytes.fromhex("c84f8a00b0888b00614f8a00f6518a00"),
    SLAVED_IDLE_UPDATE_VTABLE: bytes.fromhex("005d8a00"),
    SLAVED_IDLE_UPDATE: bytes.fromhex(
        "558bec83ec38568bf18b462433c93bc18975f87e0448894624394e28750d394e247f0da1fc95de00"
        "894624394e14750833c040e9d80100008d4e108b01ff501c84c0740ab8ffffff3fe9c2010000538b"
        "5ef885db578b7ef4897df4895dfc"
    ),
    0x008A6131: bytes.fromhex(
        "8b7de88b078bcfff90b801000084c0744d8b4dfc8d45d450e896dad3ffd905b00cdb00d9c9dff1ddd8"
    ),
    0x008A615F: bytes.fromhex(
        "8b780c8b4dfc8d433850e876dad3ff8bc70fafc78945e0db45e0d9c9dff1ddd876558d7ef08bcfe8"
        "27f1ffff6a00eb3c8bcfe86d21dcff85c0743c8b45f48b780c8b4dfc8d433850e838dad3ff8bc70f"
        "afc78945e0db45e0d9c9dff1ddd876178d7ef08bcfe8e9f0ffff6a018d45d48bcf50e8a8f4ffff8b"
        "7df4837f08000f8428fdffff8b4de88b01ff90b801000084c075268b4dfc8b7f0883c33853e8e3d9"
        "d3ff8bc70fafc78945e0db45e0d9c9dff1ddd80f86f3fcffff8b4de88b01ff90b801000084c07528"
        "8b7dfc6a016a1e8bcfe81806d8ffb800004000858734010000750d0987340100008bcfe8ed52deff"
        "83c6f08bcee859f0ffff6a008d45d4508bcee818f4ffffe9a0fcffff"
    ),
    0x008A5684: bytes.fromhex("8bf18b4e088b5e04"),
    0x008A56A7: bytes.fromhex("8b43108bc80fafc8"),
    0x008A56E2: bytes.fromhex("837b10000f84a3000000"),
    0x008A5123: bytes.fromhex("8b4374"),
    0x00850C77: bytes.fromhex(
        "8b068bceff501084c0751a8b068d4f14518bceff50788b068bceff500484c07404834f18ff"
    ),
    # Independent stock users of GameLogic->frame and the 5 Hz duration conversion.
    0x00850C32: bytes.fromhex("a12c41de008b5040035424085251ff74240c8bc8e8d6acddffc20800"),
    0x0088B759: bytes.fromhex("8b0d2c41de008b494003c8894e20"),
    0x0073A450: bytes.fromhex("d80d10f6d9005151dd1c24ff158805bd005959e83c2b3000"),
    0x00D9F608: bytes.fromhex("05000000"),
    0x00D9F610: bytes.fromhex("0ad7a33b"),
}
