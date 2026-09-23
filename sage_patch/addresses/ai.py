"""The AI: the skirmish AI, AI groups and commands, and the build assistant's gates."""

from __future__ import annotations

__all__ = [
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
    "AI_CURRENT_VICTIM",
    "AI_CURRENT_VICTIM_BYTES",
    "AI_CURRENT_VICTIM_ID_OFFSET",
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
    "AI_GROUP_MEMBER_OBJECT",
    "AI_GROUP_MEMBER_SENTINEL",
    "AI_GROUP_UPGRADE_EBP",
    "AI_GROUP_UPGRADE_MEMBER",
    "AI_GROUP_UPGRADE_MEMBER_BYTES",
    "AI_GROUP_UPGRADE_MEMBER_RESUME",
    "AI_GROUP_UPGRADE_SELF_EBP",
    "AI_HERO_ARMY_DEFINITION_LIST",
    "AI_HERO_ARMY_DEFINITION_LIST_BYTES",
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
    "AI_NEIGHBOUR_LIST_COPY",
    "AI_NEIGHBOUR_LIST_COPY_FAULT",
    "AI_PLANNER_UNCHECKED_LOOKUPS",
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
    "AI_UPDATE_LOCOMOTOR_SET_SPEED",
    "AI_UPDATE_SET_LOCOMOTOR_SET",
    "AI_UPDATE_SET_LOCOMOTOR_SET_SPEED_STORE",
    "AI_WORLD_MODEL",
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
    "SPELLBOOK_AI_REBUILD",
    "SPELLBOOK_AI_REBUILD_NAME",
    "SPELLBOOK_AI_TYPE_COUNT",
    "SPELLBOOK_AI_TYPE_FACTORY",
    "SPELLBOOK_AI_TYPE_FACTORY_ENTRY",
    "SPELLBOOK_AI_TYPE_JUMP_TABLE",
    "SPELLBOOK_AI_TYPE_NAMES",
    "THE_AI",
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
# `BuildAssistant`'s other gate (vtable `+0x64`), which every producer-facing path asks and which
# reaches `canMakeUnit` by a virtual self-call; its return address tells AI queries apart.
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
