"""Production, income and cost: queues, revives, deposits, money and command points."""

from __future__ import annotations

__all__ = [
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
    "BUILD_OBJECT_NOW",
    "BUILD_OBJECT_NOW_PROLOGUE",
    "BUILD_OBJECT_NOW_SLOT",
    "BUILD_OBJECT_NOW_VTABLE_ENTRY",
    "CLEAR_REMOVABLES",
    "CLEAR_REMOVABLES_CALL",
    "CLEAR_REMOVABLES_CALL_BYTES",
    "CLEAR_REMOVABLES_LOOP",
    "CLEAR_REMOVABLES_LOOP_BYTES",
    "CLEAR_REMOVABLES_PREDICATE_CALL",
    "CLEAR_REMOVABLES_PROLOGUE",
    "CLEAR_REMOVABLES_RETURN",
    "COMMAND_POINTS_HAS_ENOUGH",
    "COMMAND_POINTS_IN_USE",
    "COMMAND_POINT_CAP_BONUS_ADD",
    "COMMAND_POINT_CAP_BONUS_REMOVE",
    "COMMAND_POINT_CAP_BONUS_VALUE",
    "CONSTRUCTION_INITIAL_HEALTH_ANCHORS",
    "CONSTRUCTION_INITIAL_HEALTH_CALLS",
    "CONSTRUCTION_INITIAL_HEALTH_CALL_BYTES",
    "CONSTRUCTION_PERCENT_FROM_RATIO",
    "CONSTRUCTION_PERCENT_FROM_RATIO_ANCHORS",
    "CONSTRUCTION_PERCENT_FROM_RATIO_BYTES",
    "CONSTRUCTION_RAMP_ANCHOR",
    "CONSTRUCTION_RAMP_ANCHOR_BYTES",
    "CONSTRUCTION_RAMP_HEALTH_STEP",
    "CONSTRUCTION_RAMP_HEALTH_STEP_BYTES",
    "EH_PROLOG",
    "EH_PROLOG_BYTES",
    "GETTING_BUILT_CANCEL_RESUME",
    "GETTING_BUILT_CANCEL_STOP",
    "GETTING_BUILT_CANCEL_STOP_BYTES",
    "GETTING_BUILT_DAMAGE_CANCEL",
    "GETTING_BUILT_DAMAGE_CANCEL_BYTES",
    "GETTING_BUILT_DAMAGE_CANCEL_GATE",
    "GETTING_BUILT_DAMAGE_CANCEL_GATE_BYTES",
    "GETTING_BUILT_DISMISS_WORKER",
    "GETTING_BUILT_DISMISS_WORKER_BYTES",
    "GETTING_BUILT_RECENT_DAMAGE_PROBE",
    "GETTING_BUILT_RECENT_DAMAGE_PROBE_BYTES",
    "GETTING_BUILT_SPAWN_COUNTDOWN",
    "GETTING_BUILT_SPAWN_TIMER",
    "GETTING_BUILT_START_WORKER_REPAIR",
    "GETTING_BUILT_STILL_BUILDING_SLOT",
    "GETTING_BUILT_STOP_REPAIR",
    "GETTING_BUILT_UPDATE",
    "GETTING_BUILT_WORKER_SPAWNED",
    "IS_REMOVABLE_FOR_CONSTRUCTION",
    "IS_REMOVABLE_FOR_CONSTRUCTION_BYTES",
    "MONEY_AMOUNT",
    "MONEY_DEPOSIT",
    "MONEY_WITHDRAW",
    "OBJECT_KILL",
    "OBJECT_MODEL_CONDITIONS_CHANGED",
    "OBJECT_PRODUCER",
    "OBJECT_SET_PRODUCER",
    "OBJECT_STATUS_WORKER_REPAIRING",
    "PRODUCTION_BATCH_TEMPLATE_READ",
    "PRODUCTION_BATCH_TEMPLATE_READ_BYTES",
    "PRODUCTION_ENTRY_KIND",
    "PRODUCTION_ENTRY_KIND_REVIVE",
    "PRODUCTION_ENTRY_NEXT",
    "PRODUCTION_HORDE_ENTRY_REWRITE",
    "PRODUCTION_HORDE_ENTRY_REWRITE_BYTES",
    "PRODUCTION_HORDE_PAYLOAD_CALL",
    "PRODUCTION_HORDE_PAYLOAD_CALL_BYTES",
    "PRODUCTION_INHERIT_ARMY_ID",
    "PRODUCTION_QUEUE_APPEND",
    "PRODUCTION_QUEUE_APPEND_BYTES",
    "PRODUCTION_QUEUE_HEAD",
    "PRODUCTION_QUEUE_TAIL",
    "PRODUCTION_UPDATE_COMMAND_POINT_STALL",
    "PRODUCTION_UPDATE_GET_NEXT",
    "PRODUCTION_UPDATE_INTERFACE_VTABLE",
    "PRODUCTION_UPDATE_PICK_CALL",
    "PRODUCTION_UPDATE_PICK_CALL_BYTES",
    "PRODUCTION_UPDATE_PICK_ENTRY",
    "PRODUCTION_UPDATE_PICK_ENTRY_BYTES",
    "PRODUCTION_UPDATE_PICK_FALLBACK",
    "PRODUCTION_UPDATE_PICK_FALLBACK_BYTES",
    "PRODUCTION_UPDATE_PICK_RETURN",
    "PRODUCTION_UPDATE_PICK_RETURN_BYTES",
    "PRODUCTION_UPDATE_PICK_REVIVE_READY",
    "PRODUCTION_UPDATE_PICK_REVIVE_READY_BYTES",
    "PRODUCTION_UPDATE_PICK_REVIVE_SCAN",
    "PRODUCTION_UPDATE_PICK_REVIVE_SCAN_BYTES",
    "PRODUCTION_UPDATE_REVIVE_COMMAND_POINT_DELAY",
    "PRODUCTION_UPDATE_VTABLE",
    "PRODUCTION_WITHDRAW",
    "PRODUCTION_WITHDRAW_BYTES",
    "PRODUCTION_WITHDRAW_PLAYER_EBP",
    "PRODUCTION_WITHDRAW_RESUME",
    "PRODUCTION_WITHDRAW_TEMPLATE_EBP",
    "QUEUE_EXIT_BIND_BLOCK",
    "QUEUE_EXIT_BIND_BLOCK_BYTES",
    "QUEUE_EXIT_FINISH",
    "QUEUE_EXIT_FINISH_ENTRY",
    "QUEUE_EXIT_HORDE_LOOKUP",
    "QUEUE_EXIT_HORDE_LOOKUP_BYTES",
    "QUEUE_EXIT_LONE_UNIT_FLAG",
    "QUEUE_EXIT_LONE_UNIT_FLAG_BYTES",
    "QUEUE_EXIT_OBJECT_VIA_DOOR",
    "QUEUE_EXIT_OBJECT_VIA_DOOR_ENTRY",
    "QUEUE_EXIT_PENDING_HORDE",
    "QUEUE_EXIT_REMEMBER_HORDE",
    "QUEUE_EXIT_REMEMBER_HORDE_BYTES",
    "REBUILD_HOLE_CONSTRUCTION_GATE",
    "REBUILD_HOLE_CONSTRUCTION_GATE_BYTES",
    "REBUILD_HOLE_CONSTRUCTION_TEST",
    "REBUILD_HOLE_CONSTRUCTION_TEST_BYTES",
    "REBUILD_HOLE_ON_DIE",
    "REBUILD_HOLE_ON_DIE_ENTRY",
    "REBUILD_HOLE_SELF_KILL",
    "REBUILD_HOLE_SELF_KILL_BYTES",
    "REBUILD_HOLE_SET_POSITION",
    "REBUILD_HOLE_SET_POSITION_BYTES",
    "REBUILD_HOLE_SET_POSITION_RESUME",
    "REBUILD_HOLE_START_REBUILD",
    "REBUILD_HOLE_START_REBUILD_BYTES",
    "REPLACE_SELF_BUILD_CALL",
    "REPLACE_SELF_BUILD_CALL_BYTES",
    "REPLACE_SELF_BUILD_RETURN",
    "REQUEST_UNIQUE_UNIT_ID",
    "REQUEST_UNIQUE_UNIT_ID_BODY",
    "REQUEST_UNIQUE_UNIT_ID_VTABLE_SLOT",
    "RESOURCE_MODIFIER_COUNT_CALLBACK",
    "REVIVE_MGR_ENTRY_START_FRAME",
    "REVIVE_MGR_OFFSET",
    "REVIVE_MGR_PROGRESS",
    "REVIVE_MGR_PROGRESS_BYTES",
    "REVIVE_MGR_START",
    "REVIVE_MGR_START_BYTES",
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
]

# `RebuildHoleExposeDie::onDie` - the module that puts a rebuild hole where a structure stood.
# `esi` is the module subobject on entry, from which it takes moduleData (`[esi-0xc]`) and the
# dying `Object` (`[esi-8]`). Derived in `docs/rebuild-hole-repair.md`.
REBUILD_HOLE_ON_DIE = 0x00889AAF
REBUILD_HOLE_ON_DIE_ENTRY = bytes.fromhex("558bec83ec1456ff7508")
# The three instructions that load the dying object's status bitset and isolate
# `UNDER_CONSTRUCTION` from it, immediately before the branch below. Anchored as one run rather
# than as a lone `jne`, because a bare conditional branch says nothing about what it tests.
REBUILD_HOLE_CONSTRUCTION_TEST = 0x00889B03
REBUILD_HOLE_CONSTRUCTION_TEST_BYTES = bytes.fromhex("8b8694000000c1e802a801")
# `jne <return>` - the gate. A structure destroyed while it is still going up leaves no hole,
# which for a creep lair means the rebuild loop (and the treasure that hangs off the hole's own
# `CreateObjectDie`) ends there. Six bytes; a scan of every branch displacement and imm32 in the
# image finds no inbound edge into them, so they are replaceable in place.
REBUILD_HOLE_CONSTRUCTION_GATE = 0x00889B0E
REBUILD_HOLE_CONSTRUCTION_GATE_BYTES = bytes.fromhex("0f8546010000")
# `push [esi+0x74]`, the tail of `onDie`: anchors that this is the function arming the rebuild.
# The eleven bytes placing the fresh hole at the dying object's position, which for a structure
# killed mid-rebuild is buried. Replaceable in place; `RESUME` is the angle copy.
REBUILD_HOLE_SET_POSITION = 0x00889B4E
REBUILD_HOLE_SET_POSITION_BYTES = bytes.fromhex("8d4638508bcfe8a826e8ff")
REBUILD_HOLE_SET_POSITION_RESUME = 0x00889B59
REBUILD_HOLE_START_REBUILD = 0x00889BE7
REBUILD_HOLE_START_REBUILD_BYTES = bytes.fromhex("ff76748b4d08ff7604")
# `RebuildHoleBehavior::update`'s self-kill: `Object::kill(UNRESISTABLE, FADED)` on the hole,
# reached in the same pass that creates the structure it was holding the place for. This is why
# every hole in the data writes `DeathTypes = ALL -FADED` on its treasure module, and why the
# hole is already gone by the time the rebuilding structure can be attacked.
REBUILD_HOLE_SELF_KILL = 0x00886C3A
REBUILD_HOLE_SELF_KILL_BYTES = bytes.fromhex("6a166a088bcf")
# `ProductionUpdateInterface::requestUniqueUnitID()`, minting `ProductionID`s from a counter at
# module `+0x30` that nothing else touches. See `docs/unique-production-id.md`.
REQUEST_UNIQUE_UNIT_ID = 0x008A18FA
PRODUCTION_UPDATE_INTERFACE_VTABLE = 0x00C67DB0
REQUEST_UNIQUE_UNIT_ID_VTABLE_SLOT = 0x08
# `ProductionUpdate`'s primary vtable: how a reader outside the process identifies the module
# (`sage_live.backends.memory`).
PRODUCTION_UPDATE_VTABLE = 0x00C67EF4
# The whole stock body: `mov eax,[ecx+0x10]` / `lea edx,[eax+1]` / `mov [ecx+0x10],edx` / `ret`.
# Ten bytes, entered only through the vtable, so all ten are replaceable in place.
REQUEST_UNIQUE_UNIT_ID_BODY = bytes.fromhex("8b41108d5001895110c3")
# `TerrainResourceBehavior`, which deposits an income and grants the same amount as experience
# (`docs/terrain-resource-exp.md`). Its `ModuleData` has two padding bytes at `+0x16`.
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
# The three sites a negative `MaxIncome` must get past (`docs/maintenance-cost.md`). `_INCOME_GATE`
# is the `jle` that discards it; `je` in its place is the whole first edit.
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
# The income as a float between the inflation multiply and the floor (written at `0x00885692`). It
# keeps a sign the integer loses: `-0.0f`.
TERRAIN_RESOURCE_INCOME_FLOAT_EBP = -0x20
# `..._PAY` is the `lea ecx, [esi+0x90]` that addresses the player's `Money` for the deposit -
# the instruction *before* the `call`, deliberately, so the call itself stays free for whatever
# else wants it. `esi` is the controlling `Player`, `edi` the depositing `Object` and `ebx` the
# signed amount; the three deposit arguments are already pushed, with the amount at `[esp]`.
TERRAIN_RESOURCE_PAY = 0x008856B0
TERRAIN_RESOURCE_PAY_BYTES = bytes.fromhex("8d8e90000000")  # lea ecx, [esi+0x90]
TERRAIN_RESOURCE_PAY_RESUME = 0x008856B6
COMMAND_POINT_CAP_BONUS_ADD = 0x006A7C3E
COMMAND_POINT_CAP_BONUS_REMOVE = 0x006A7C51
COMMAND_POINT_CAP_BONUS_VALUE = 0x006A7C01
#: Despite the name, in `TerrainResourceBehavior::update` (`0x008854D3`): where the finished
#: inflation multiplier (`[ebp-0x1C]`) is about to be used. `_FILTER_EBP` holds the filter pointer
#: only until `0x00885672`.
AUTO_DEPOSIT_SCALE = 0x00885650
AUTO_DEPOSIT_SCALE_BYTES = bytes.fromhex("8b45e8db400c")
AUTO_DEPOSIT_SCALE_RESUME = 0x00885656
AUTO_DEPOSIT_MULTIPLIER_EBP = -0x1C
AUTO_DEPOSIT_FILTER_EBP = -0x20
AUTO_DEPOSIT_MODULE_DATA_EBP = -0x18
RESOURCE_MODIFIER_COUNT_CALLBACK = 0x00885230
#: `Money::deposit(amount, stats, playSound)` - thiscall on the `Money` subobject, three stack
#: arguments, callee-cleaned. The sibling `Money::withdraw` at `0x007B17EF` **clamps to what is
#: available and returns what it took**, which is why affordability is always decided upstream of
#: it and never by it. 35 call sites deposit, 22 withdraw.
MONEY_DEPOSIT = 0x007B18B8
MONEY_WITHDRAW = 0x007B17EF
MONEY_AMOUNT = 0x04
#: `AutoDepositUpdate` (not the module `AUTO_DEPOSIT_SCALE` sits in). Its `ModuleData` has two
#: padding bytes at `+0x22`, cleared for free by widening the constructor's store.
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
#: The deposit call inside `AutoDepositUpdate::update` (one whole instruction). `esi` is the module
#: and `edi` the player until the resume address.
AUTO_DEPOSIT_DEPOSIT = 0x0089DD08
AUTO_DEPOSIT_DEPOSIT_BYTES = bytes.fromhex("e8ab3bf1ff")
AUTO_DEPOSIT_DEPOSIT_RESUME = 0x0089DD0D
AUTO_DEPOSIT_MODULE_DATA_ESI = -0x0C
# The two sites a negative `DepositAmount` must pass: the deposit and the experience grant. `_PAY`
# is the money-pointer load, because `second-resource` owns the call after it.
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
# Where `AutoDepositUpdate::update`'s amount becomes an integer (`cvttss2si`): one five-byte
# instruction both handicap paths reach. See `docs/auto-deposit-inflation.md`.
AUTO_DEPOSIT_TRUNCATE = 0x0089DCDD
AUTO_DEPOSIT_TRUNCATE_BYTES = bytes.fromhex("f30f2c45ec")  # cvttss2si eax, dword ptr [ebp-0x14]
AUTO_DEPOSIT_TRUNCATE_RESUME = 0x0089DCE2
AUTO_DEPOSIT_SCALE_AMOUNT_EBP = -0x14
AUTO_DEPOSIT_GIVE_NO_XP = 0x20
AUTO_DEPOSIT_AMOUNT = 0x0C
#: The one affordability comparison every human production path shares. Refusing here with the
#: engine's code 2 reuses its "not enough money" message.
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
#: `CommandPointBookkeeping::hasEnoughCommandPoints(const ThingTemplate *what, Int count)`, on
#: the subobject at `Player+0x60`. Returns `inUse + what->CommandPoints <= cap`, or TRUE outright
#: when `what` costs no command points or carries the `ARMY_OF_DEAD` KindOf. `count` is pushed by
#: every caller and read by none.
COMMAND_POINTS_HAS_ENOUGH = 0x006A7F79
COMMAND_POINTS_IN_USE = 0x08
#: The command-point verdict in `BuildAssistant`'s `+0x64` gate, its last refusal; it covers
#: `UNIT_BUILD` and `REVIVE` at once.
BUILD_GATE_COMMAND_POINTS = 0x0079402B
BUILD_GATE_COMMAND_POINTS_BYTES = bytes.fromhex("84c075046a07eb6b")
BUILD_GATE_COMMAND_POINTS_OK = 0x00794033  # enough: on with the rest of the checks
BUILD_GATE_COMMAND_POINTS_REFUSE = 0x0079409E  # the `pop eax` that carries the pushed code out
BUILD_GATE_NOT_ENOUGH_COMMAND_POINTS = 7
#: Where the stock engine already stalls a queue that has outrun the command-point cap (units and
#: revives). Not patched; named so the claim can be checked.
PRODUCTION_UPDATE_COMMAND_POINT_STALL = 0x008A1E27
PRODUCTION_UPDATE_REVIVE_COMMAND_POINT_DELAY = 0x008A0669
# The production queue's per-frame entry picker (`docs/hero-recruit-parallel.md`): one list of
# units, upgrades and revives, and exactly one entry advanced per frame.

#: `ProductionUpdate::pickEntryToAdvance()`, called once per tick from `update` at
#: `PRODUCTION_UPDATE_PICK_CALL` and nowhere else. Four rules in order: an entry with a batch
#: already part-produced; a `DOZER`; a revive whose player-side clock has reached 1.0
#: (`PRODUCTION_UPDATE_PICK_REVIVE_SCAN` walks the list, `..._REVIVE_READY` asks); otherwise the
#: head, at `PRODUCTION_UPDATE_PICK_FALLBACK`.
PRODUCTION_UPDATE_PICK_ENTRY = 0x008A072F
PRODUCTION_UPDATE_PICK_ENTRY_BYTES = bytes.fromhex("568bf18b4628")  # push esi; mov esi,ecx; head
PRODUCTION_UPDATE_PICK_CALL = 0x008A1C17
PRODUCTION_UPDATE_PICK_CALL_BYTES = bytes.fromhex("e813ebffff")
#: The revive rule's loop body - `cmp dword [ebx+4], 3` - and the call inside it that asks how far
#: along the hero is. The fallback that follows both, seven bytes wide, is what
#: `hero-recruit-parallel` displaces: `test ebx,ebx` / `jne <the loop>` / the head load's first
#: byte. Nothing in the image branches into `0x008A07D2`..`0x008A07D7`.
PRODUCTION_UPDATE_PICK_REVIVE_SCAN = 0x008A078A
PRODUCTION_UPDATE_PICK_REVIVE_SCAN_BYTES = bytes.fromhex("837b0403")
PRODUCTION_UPDATE_PICK_REVIVE_READY = 0x008A07B7
PRODUCTION_UPDATE_PICK_REVIVE_READY_BYTES = bytes.fromhex("e8e304eeff")  # call REVIVE_MGR_PROGRESS
PRODUCTION_UPDATE_PICK_FALLBACK = 0x008A07D1
PRODUCTION_UPDATE_PICK_FALLBACK_BYTES = bytes.fromhex("85db75b58b4628")
PRODUCTION_UPDATE_PICK_RETURN = 0x008A07D8
PRODUCTION_UPDATE_PICK_RETURN_BYTES = bytes.fromhex("5b5f5ec3")  # pop ebx/edi/esi; ret
#: `ProductionUpdate::append(entry)` - unconditional, tail-first, identical for all three kinds.
PRODUCTION_QUEUE_APPEND = 0x008A0C99
PRODUCTION_QUEUE_APPEND_BYTES = bytes.fromhex("558bec83ec4c")
#: `ProductionInterface::getNextProduction(entry)`, interface vtable `+0x58`, and literally
#: `entry ? entry->next : NULL` - which is what makes a raw `PRODUCTION_ENTRY_NEXT` walk equivalent.
PRODUCTION_UPDATE_GET_NEXT = 0x008A1904
#: `ProductionUpdate` and `ProductionEntry` field offsets, and the one entry kind that is a hero.
PRODUCTION_QUEUE_HEAD = 0x28
PRODUCTION_QUEUE_TAIL = 0x2C
PRODUCTION_ENTRY_KIND = 0x04
PRODUCTION_ENTRY_NEXT = 0x48
PRODUCTION_ENTRY_KIND_REVIVE = 3
#: The revive manager, at `Player+0x758`: a vector of `0xE8`-byte roster records, one per
#: `BuildableHeroesMP` entry. `REVIVE_MGR_START` stamps `TheGameLogic->frame` into a record's
#: `+0xA8` when the hero is queued and refuses if `+0xA8` is not `-1`; `REVIVE_MGR_PROGRESS`
#: answers `(now - +0xA8) / totalFrames` as a fraction of 1.0, or `0.0` when `+0xA8` is `-1`.
#: A hero's recruitment therefore runs on the logic frame, not on the queue.
REVIVE_MGR_OFFSET = 0x758
REVIVE_MGR_START = 0x007812B2
REVIVE_MGR_START_BYTES = bytes.fromhex("568b74240c")
REVIVE_MGR_PROGRESS = 0x00780C9F
REVIVE_MGR_PROGRESS_BYTES = bytes.fromhex("558bec56")
REVIVE_MGR_ENTRY_START_FRAME = 0xA8
#: `ProductionUpdate`'s assignment: a recruited unit keeps its own army id if it has one, else it
#: inherits the producing structure's. This is the whole reason a recruited unit comes home.
PRODUCTION_INHERIT_ARMY_ID = 0x008A2519
#: `call [eax+0x24]` in `ProductionUpdate::update` - the only caller of
#: `HORDE_CONTAIN_PAYLOAD_NAME` in the image, and therefore the whole of recruitment's knowledge
#: of what a horde is made of.
PRODUCTION_HORDE_PAYLOAD_CALL = 0x008A2C91
PRODUCTION_HORDE_PAYLOAD_CALL_BYTES = bytes.fromhex("ff5024")
#: The queue-entry rewrite that follows it: `entry->template = the payload`,
#: `entry->total = Slots + 1`, `entry+0x34 = 1`. Skipped entirely when the getter answered "".
PRODUCTION_HORDE_ENTRY_REWRITE = 0x008A2CC4
PRODUCTION_HORDE_ENTRY_REWRITE_BYTES = bytes.fromhex("8b4dbc4083632800894b08894320c6433401")
#: `mov ecx, [ebx+8]` - the batch loop's read of the one template every object in this entry is
#: made from, and the reason the mix cannot survive production.
PRODUCTION_BATCH_TEMPLATE_READ = 0x008A1FB8
PRODUCTION_BATCH_TEMPLATE_READ_BYTES = bytes.fromhex("8b4b088b432c")
# `QueueProductionExitUpdate` - the door every production building pushes its finished objects
# out of, and the module `docs/horde-exit-absorption.md` derives. Its `ExitInterface` sub-object
# sits at module `+0x20` (vtable `0x00C682C4`), and that sub-object is the `ecx` every routine
# named here receives - so a field written `interface +N` below is module `+0x20+N`.
QUEUE_EXIT_OBJECT_VIA_DOOR = 0x008A3DD5
QUEUE_EXIT_OBJECT_VIA_DOOR_ENTRY = bytes.fromhex("b81e21ba00")
#: `ExitInterface` slot `+0x2C`, called by `ProductionUpdate::update` once a whole queue entry
#: has been emitted. It clears `QUEUE_EXIT_PENDING_HORDE` and takes the horde off
#: `UNDER_CONSTRUCTION`/`UNSELECTABLE`, which is what ends the exit.
QUEUE_EXIT_FINISH = 0x008A3BF8
QUEUE_EXIT_FINISH_ENTRY = bytes.fromhex("558bec83ec1453568bf1")
#: Interface `+0x20`, module `+0x40`: the `ObjectID` of the horde currently coming out of this
#: door. Zeroed by the constructor, written by `QUEUE_EXIT_REMEMBER_HORDE` for a `KINDOF HORDE`
#: object only, and cleared only by `QUEUE_EXIT_FINISH` - so it names one horde for the whole of
#: that horde's production entry, which is `Slots + 1` objects long
#: (`PRODUCTION_HORDE_ENTRY_REWRITE`).
QUEUE_EXIT_PENDING_HORDE = 0x20
#: The read of it, at the head of `exitObjectViaDoor`: `push [edi+0x20]` /
#: `mov ecx, TheGameLogic` / `call findObjectByID`. The five bytes of that call are the
#: `horde-exit-absorption` hook - a NULL answer is the "no horde is coming out" path the stock
#: code already has.
QUEUE_EXIT_HORDE_LOOKUP = 0x008A4036
QUEUE_EXIT_HORDE_LOOKUP_BYTES = bytes.fromhex("e84656baff")
#: What that lookup gates, in order: `obj->setProducer(horde)`, the horde interface's
#: `+0x2C` slot-assignment (`HORDE_IFACE_ASSIGN_SLOT`), and `obj->setTeam(horde->m_team)`. None
#: of the three tests what the exiting object is.
QUEUE_EXIT_BIND_BLOCK = 0x008A4066
QUEUE_EXIT_BIND_BLOCK_BYTES = bytes.fromhex("ff75e48bcbe83176deff8b06538bceff502c")
#: `[ebp+0xB]` - "this is a lone unit": set when the exiting object is not itself `KINDOF HORDE`
#: **and** no horde is pending. Only a lone unit gets the structure's rally point appended to its
#: own exit path, so an object wrongly bound to a pending horde walks out of the door and stops.
QUEUE_EXIT_LONE_UNIT_FLAG = 0x008A4169
QUEUE_EXIT_LONE_UNIT_FLAG_BYTES = bytes.fromhex(
    "8b4304f6801501000020750a837de400c6450b017404c6450b00"
)
#: The tail of `exitObjectViaDoor`: `test byte [tmpl+0x115], 0x20` (`KINDOF HORDE`, bit 109),
#: then `UNSELECTABLE`/`UNDER_CONSTRUCTION` on the horde and `mov [edi+0x20], eax` - the only
#: write of `QUEUE_EXIT_PENDING_HORDE` in the image.
QUEUE_EXIT_REMEMBER_HORDE = 0x008A4267
QUEUE_EXIT_REMEMBER_HORDE_BYTES = bytes.fromhex(
    "8b4304f680150100002074428b076a018d4d98518bcfff50248d45985053e89bafe4ff59596a008d4598508bcb"
    "e8ca2bdfff8b43746a016a038bcb894720"
)
#: `GettingBuiltBehaviorInterface::isStillBuilding` - slot `+0x2C` of the interface
#: `OBJECT_GET_GETTING_BUILT_BEHAVIOR` returns. True for the whole of a build **and** of a
#: rebuild out of rubble, which is what makes it the "the structure is not finished yet" test that
#: the effectively-dead flag is not.
GETTING_BUILT_STILL_BUILDING_SLOT = 0x2C
#: `GettingBuiltBehavior::update`. `ecx` is the module's update interface (`module+0x10`), so the
#: GettingBuilt interface is `esi+0x10` and its flags `+0x12`..`+0x16` read as `esi+0x22`..`+0x26`.
#: Derived in `docs/repair-damage-cancel.md`.
GETTING_BUILT_UPDATE = 0x00857E77
#: `GettingBuiltBehaviorInterface::stopRepair` - slot `+0x14`: when the repairing flag (`+0x12`) is
#: set, clears it and `UNDERGOING_REPAIR` / `UNDER_CONSTRUCTION` and stops the repair sound loop.
GETTING_BUILT_STOP_REPAIR = 0x00856644
#: The update's "damaged recently" probe: `[ebp-1] = Object::wasDamagedWithin(4 seconds)`
#: (`0x0068C933`), forced to 0 while the interface's repairing-from-rubble flag (`esi+0x25`) is set.
GETTING_BUILT_RECENT_DAMAGE_PROBE = 0x00857EB0
GETTING_BUILT_RECENT_DAMAGE_PROBE_BYTES = bytes.fromhex(
    "8365ec00807e250075156a048d45ec508bcfe86c4ae3ff84c0c645ff017504c645ff00"
)
#: The damage cancel: `SpawnTimer` (`ModuleData+0x20`) `>= 0`, damaged recently, and not still
#: building (`esi+0x26`) -> `0x008580AC`, which calls `stopRepair`.
GETTING_BUILT_DAMAGE_CANCEL = 0x00857F29
GETTING_BUILT_DAMAGE_CANCEL_BYTES = bytes.fromhex(
    "8b5df0f30f1043200f2f0594b5c1007210807dff00740a807e26000f8462010000"
)
#: `jb` past the cancel when `SpawnTimer < 0` - the gate that exempts every structure without
#: auto-heal (castles, walls, gates, camps) from having its repair cancelled by damage.
GETTING_BUILT_DAMAGE_CANCEL_GATE = 0x00857F38
GETTING_BUILT_DAMAGE_CANCEL_GATE_BYTES = bytes.fromhex("7210")
#: The cancel itself: `mov ecx, [ebp-0x18] / mov eax, [ecx] / call [eax+0x14]` - `stopRepair` on
#: the GettingBuilt interface. Its two entries are the branches at `0x00857F23` and `0x00857F44`;
#: nothing branches into the middle of it. `GETTING_BUILT_CANCEL_RESUME` follows, and is itself a
#: branch target (`0x008580A5`), which is why the hook ends there.
GETTING_BUILT_CANCEL_STOP = 0x008580AC
GETTING_BUILT_CANCEL_STOP_BYTES = bytes.fromhex("8b4de88b01ff5014")
GETTING_BUILT_CANCEL_RESUME = 0x008580B4
#: `GettingBuiltBehaviorInterface` slot `+0x04`, the repair start for a structure with a
#: `WorkerName`: spawns the worker, makes each the other's producer, sets `+0x1C` and orders the
#: worker to repair. It never sets the repairing flag `+0x12`, so `stopRepair` has nothing to stop
#: on such a structure. Without a `WorkerName` it defers to `startRepair` (slot `+0x10`).
GETTING_BUILT_START_WORKER_REPAIR = 0x00857A19
#: Interface byte set when slot `+0x04` has spawned a worker (`0x00857AFA`).
GETTING_BUILT_WORKER_SPAWNED = 0x1C
#: `ModuleData+0x20`, `SpawnTimer` (a `Real`, seconds).
GETTING_BUILT_SPAWN_TIMER = 0x20
#: Interface `+0x08`, the auto-repair countdown: seeded from `SpawnTimer` (`0x00857EA4`), less
#: `1.0` per update while the structure is hurt and not recently hit (`0x008579ED`), and slot
#: `+0x04` spawns a worker when it reaches zero with no worker present (`0x008579FA`).
GETTING_BUILT_SPAWN_COUNTDOWN = 0x08
#: The engine's own dismissal of a finished repair worker, in the worker manager `0x00857238`:
#: raise model condition `+0x128` bit `0x10000000` (and notify), `Object::kill(UNRESISTABLE,
#: FADED)`, then clear the structure's producer. The cancel cave repeats it, so these bytes are
#: asserted as the pattern it copies and the three helpers it calls.
GETTING_BUILT_DISMISS_WORKER = 0x008572D2
GETTING_BUILT_DISMISS_WORKER_BYTES = bytes.fromhex(
    "b800000010858628010000750d0986280100008bcee85042e3ff6a166a088bcee8cc1be4ff6a008bcfe8b643e3ff"
)
#: `Object+0x7C`, the id `Object::setProducer` writes and `GettingBuiltBehavior` reads its worker
#: back from (`0x00857EEF`, `0x0085724F`).
OBJECT_PRODUCER = 0x7C
#: `Object::setProducer(Object *)` - `__thiscall`, `ret 4`; stores the object's id (0 for NULL).
OBJECT_SET_PRODUCER = 0x0068B6B6
#: `Object::kill(DamageType, DeathType)` - `__thiscall`, `ret 8`.
OBJECT_KILL = 0x00698EC3
#: The model-condition-changed notification, called after editing `Object+0x10C` in place.
OBJECT_MODEL_CONDITIONS_CHANGED = 0x0068B53C
#: `ObjectStatus` `WORKER_REPAIRING` (bit 97): set on a worker while it is repairing a structure.
OBJECT_STATUS_WORKER_REPAIRING = 97
#: The four places a structure about to be built is driven to one hit point, all the same shape
#: (`ecx` the body, `[esp+4]` the delta).
CONSTRUCTION_INITIAL_HEALTH_CALLS = (0x0079541F, 0x00858975, 0x0088D59E, 0x008AD88E)
CONSTRUCTION_INITIAL_HEALTH_CALL_BYTES = {
    0x0079541F: bytes.fromhex("ff9784000000"),
    0x00858975: bytes.fromhex("ff9784000000"),
    0x0088D59E: bytes.fromhex("ff9784000000"),
    0x008AD88E: bytes.fromhex("ff9384000000"),
}
#: The sequence around each of those calls, from the `Object+0x25C` load onwards - what makes the
#: hooked call `internalChangeHealth(1.0 - health, NULL)` rather than some other body call.
CONSTRUCTION_INITIAL_HEALTH_ANCHORS = {
    0x00795400: bytes.fromhex(
        "8b9e5c02000085db741b8b3b6a008bcbff5710d82d0819bd00518bcbd91c24ff9784000000"
    ),
    0x0085895A: bytes.fromhex("8b9e5c0200008b3b6a008bcbff5710d82d0819bd00518bcbd91c24ff9784000000"),
    0x0088D581: bytes.fromhex(
        "8b8b5c0200008b396a00894df8ff5710d82d0819bd00518b4df8d91c24ff9784000000"
    ),
    0x008AD866: bytes.fromhex(
        "8b8e5c0200000f57c0f30f1186880200008b196a00894d18ff5310d82d0819bd00518b4d18d91c24"
        "ff9384000000"
    ),
}
#: The `DozerAIUpdate` construction ramp's health step: `call [esi+0x1C]` (`getMaxHealth`) then
#: `fdiv [ebp-0x1C]` (the frame count the hooked `calcTimeToBuild` produced). Six bytes, and the
#: cave that replaces them keeps the `ebp` the caller set up, because the divisor is its local.
CONSTRUCTION_RAMP_HEALTH_STEP = 0x0088DEA8
CONSTRUCTION_RAMP_HEALTH_STEP_BYTES = bytes.fromhex("ff561cd875e4")
#: The ramp step in context: `ecx` is the body and `[ebp-0x10]` keeps it across the call.
CONSTRUCTION_RAMP_ANCHOR = 0x0088DEA1
CONSTRUCTION_RAMP_ANCHOR_BYTES = bytes.fromhex(
    "8b316a00894df0ff561cd875e4518b4df0d91c24ff9684000000"
)
#: The two places the engine derives the construction percent back **out of** the health ratio -
#: `call [vtable+0x14]`, `fmul [FLOAT_HUNDRED]`, `fstp [Object+0x288]`. `0x00856800` is
#: `GettingBuiltBehavior`'s resync when neither of its two in-progress flags is set; `0x00858078`
#: is the self-build update, one instruction after the heal it just applied. Nine bytes each, and
#: identical.
CONSTRUCTION_PERCENT_FROM_RATIO = (0x00856800, 0x00858078)
CONSTRUCTION_PERCENT_FROM_RATIO_BYTES = bytes.fromhex("ff5014d80dd888bd00")
CONSTRUCTION_PERCENT_FROM_RATIO_ANCHORS = {
    0x008567F8: bytes.fromhex("8b8f5c0200008b01ff5014d80dd888bd00d99f88020000"),
    0x00858074: bytes.fromhex("8b038bcbff5014d80dd888bd00d99f88020000"),
}
# `BuildAssistant::buildObjectNow` and the site clearing it does first
# (`docs/replace-self-rubble.md`).
#: `BuildAssistant::buildObjectNow(constructor, template, pos, angle, owner)` - `__thiscall`,
#: `ret 0x14`, `TheBuildAssistant` vtable `+0x38`. Unless the constructor is a `DOZER` or the
#: template is `NO_COLLIDE`, it clears the site (`CLEAR_REMOVABLES`) and moves units off it before
#: it creates anything.
BUILD_OBJECT_NOW = 0x00797796
BUILD_OBJECT_NOW_SLOT = 0x38
BUILD_OBJECT_NOW_VTABLE_ENTRY = 0x00C30810
#: `mov eax, <handler>; call EH_PROLOG` - what makes `[ebp+4]` its return address.
BUILD_OBJECT_NOW_PROLOGUE = bytes.fromhex("b80252b900e850572a00")
#: `BuildAssistant::clearRemovablesForConstruction(template, pos, angle)` - `__thiscall`,
#: `ret 0xC`. Walks every object the new footprint would collide with and destroys each one
#: `IS_REMOVABLE_FOR_CONSTRUCTION` accepts, unless its template has `KindOf` 58.
CLEAR_REMOVABLES = 0x00796576
CLEAR_REMOVABLES_PROLOGUE = bytes.fromhex("b81b51b900e870692a00")
#: `buildObjectNow`'s call to it, `push ebx; push esi; call`, and where that call returns.
CLEAR_REMOVABLES_CALL = 0x007977F1
CLEAR_REMOVABLES_CALL_BYTES = bytes.fromhex("5356e87eedffff")
CLEAR_REMOVABLES_RETURN = 0x007977F8
#: The loop body, `push edx` through the `jne` back to it: ask the predicate, skip `KindOf` 58,
#: `GameLogic::destroyObject`, next.
CLEAR_REMOVABLES_LOOP = 0x007965E3
CLEAR_REMOVABLES_LOOP_BYTES = bytes.fromhex(
    "528bcfe8bbdaffff3c0175188b4204f6800f01000004750c8b0d2c41de0052e8a455e9ff8d4d10e80ae9caff"
    "8bd085d275ce"
)
#: `call IS_REMOVABLE_FOR_CONSTRUCTION` inside that loop, with the object pushed. The caller reads
#: `edx` (the object) again after it returns, so a replacement must preserve `edx`.
CLEAR_REMOVABLES_PREDICATE_CALL = 0x007965E6
#: `BuildAssistant::isRemovableForConstruction(Object *)`, `ret 4`, no `this` use: false for
#: `INERT` or `TAINT`; true for `SHRUBBERY` or `CLEARED_BY_BUILD`; otherwise the effectively-dead
#: bit (`Object+0x458` bit 0). The last case is why any rubble under a new footprint is destroyed.
#: `isLocationClearOfObjects` asks the same question, to decide what does not block placement
#: (`docs/castle-unpack-clearance.md` §2.4).
IS_REMOVABLE_FOR_CONSTRUCTION = 0x007940A6
IS_REMOVABLE_FOR_CONSTRUCTION_BYTES = bytes.fromhex(
    "8b4c240485c9750432c0eb338b4104f680130100000275f0f6801b0100000175e7f68008010000407404b001"
    "eb11f6800e0100000875f38a81580400002401c20400"
)
#: MSVC `__EH_prolog`: `push -1; push eax; push fs:[0]; ...; mov [esp+0xc], ebp;
#: lea ebp, [esp+0xc]` - so in every function that opens with it, `[ebp]` is the caller's `ebp`
#: and `[ebp+4]` the return address.
EH_PROLOG = 0x00A3CEF0
EH_PROLOG_BYTES = bytes.fromhex("6aff5064a100000000508b44240c64892500000000896c240c8d6c240c50c3")
#: `ReplaceSelfUpgrade::upgradeImplementation`'s creation of the replacement: `mov eax,
#: [TheBuildAssistant]; mov ebx, [eax]` through `call [ebx+0x38]`, and where that call returns.
#: `docs/foundation-rebind.md` pins the same `call`.
REPLACE_SELF_BUILD_CALL = 0x008BB8B4
REPLACE_SELF_BUILD_CALL_BYTES = bytes.fromhex(
    "a10082de008b18894de0e8b5fddcffd945c850518b0d0082de00d91c248d45e45057ff75e0ff5338"
)
REPLACE_SELF_BUILD_RETURN = 0x008BB8DC
