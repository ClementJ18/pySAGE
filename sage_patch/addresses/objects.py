"""Objects and their modules: templates, bodies, weapons, hordes, containment."""

from __future__ import annotations

from sage_patch.addresses.logic import THE_COMMAND_SET_STORE
from sage_patch.addresses.player import UPGRADE_MASK_ANY, UPGRADE_MASK_TEST_ANY
from sage_patch.addresses.runtime import (
    ASCII_STRING_IS_EMPTY,
    INI_PARSE_DURATION,
    INI_PARSE_UPGRADE_MASK,
)

__all__ = [
    "ACTIVE_BODY_ATTEMPT_HEALING",
    "ACTIVE_BODY_ATTEMPT_HEALING_AMOUNT_FSTP",
    "ACTIVE_BODY_ATTEMPT_HEALING_AMOUNT_FSTP_BYTES",
    "ACTIVE_BODY_ATTEMPT_HEALING_AMOUNT_TEST",
    "ACTIVE_BODY_INTERNAL_CHANGE_HEALTH",
    "ACTIVE_BODY_INTERNAL_CHANGE_HEALTH_SLOT",
    "ARMOR_ADJUST_DAMAGE",
    "ARMOR_ADJUST_DAMAGE_HEALING_PASSTHROUGH",
    "ATTACK_ELIGIBILITY_NUGGET_CALL",
    "ATTACK_ELIGIBILITY_NUGGET_CALL_WINDOW",
    "ATTACK_ELIGIBILITY_NUGGET_CALL_WINDOW_BYTES",
    "ATTACK_NUGGET_VTABLES",
    "ATTACK_NUGGET_VTABLE_STORES",
    "ATTRIBUTE_MODIFIER_AURA_ANCHORS",
    "ATTRIBUTE_MODIFIER_AURA_DEAD_SLEEP",
    "ATTRIBUTE_MODIFIER_AURA_DEAD_SLEEP_BYTES",
    "ATTRIBUTE_MODIFIER_AURA_GATES",
    "ATTRIBUTE_MODIFIER_AURA_GATES_BYTES",
    "ATTRIBUTE_MODIFIER_AURA_MODULE_NAME_STRING",
    "ATTRIBUTE_MODIFIER_AURA_NORMAL_SLEEP",
    "ATTRIBUTE_MODIFIER_AURA_RUN_WHILE_DEAD_OFFSET",
    "ATTRIBUTE_MODIFIER_AURA_SCAN",
    "ATTRIBUTE_MODIFIER_AURA_THIS_EBP_OFFSET",
    "ATTRIBUTE_MODIFIER_AURA_UPDATE",
    "ATTRIBUTE_MODIFIER_AURA_UPDATE_VTABLE",
    "AUTO_HEAL_AFFECTS_CONTAINED",
    "AUTO_HEAL_ANCHORS",
    "AUTO_HEAL_CONTAINED_EXIT",
    "AUTO_HEAL_CONTAINED_EXIT_BYTES",
    "AUTO_HEAL_CONTAINED_ITERATE",
    "AUTO_HEAL_LAST_RESPAWN_FRAME",
    "AUTO_HEAL_MODULE_BASE_SLOT",
    "AUTO_HEAL_MODULE_NAME_STRING",
    "AUTO_HEAL_RESPAWN_BLOCK",
    "AUTO_HEAL_RESPAWN_FX_LIST",
    "AUTO_HEAL_RESPAWN_MEMBER_FIXUP",
    "AUTO_HEAL_RESPAWN_MINIMUM_DELAY",
    "AUTO_HEAL_RESPAWN_NEARBY_HORDE_MEMBERS",
    "AUTO_HEAL_SCOPE_INDEX_SLOT",
    "AUTO_HEAL_UPDATE",
    "AUTO_HEAL_UPDATE_TAIL",
    "AUTO_HEAL_UPDATE_VTABLE",
    "BEHAVIOR_GET_CONTAIN_SLOT",
    "BEHAVIOR_MODULE_INTERFACE",
    "BODY_GET_HEALTH_RATIO_SLOT",
    "BODY_GET_HEALTH_SLOT",
    "BODY_GET_MAX_HEALTH_SLOT",
    "CASTLE_BEHAVIOR_DESTRUCTOR",
    "CASTLE_BEHAVIOR_FACTION_PREFAB",
    "CASTLE_BEHAVIOR_NAME_STRING",
    "CASTLE_BEHAVIOR_PREFAB_RESOLVER",
    "CASTLE_BEHAVIOR_START_BUILD_UP",
    "CASTLE_BEHAVIOR_START_BUILD_UP_BYTES",
    "CASTLE_BEHAVIOR_START_FADE",
    "CASTLE_BEHAVIOR_START_FADE_BYTES",
    "CASTLE_BEHAVIOR_START_UNPACK",
    "CASTLE_BEHAVIOR_STATE",
    "CASTLE_BEHAVIOR_UNPACK",
    "CASTLE_BEHAVIOR_UNPACK_EPILOGUE",
    "CASTLE_BEHAVIOR_UPDATE",
    "CASTLE_BEHAVIOR_UPDATE_VTABLE",
    "CASTLE_BEHAVIOR_UPDATE_VTABLE_STAMP",
    "CASTLE_BEHAVIOR_UPDATE_VTABLE_STAMP_BYTES",
    "CASTLE_MEMBER_BEHAVIOR_NAME_STRING",
    "CASTLE_MEMBER_CASTLE_ID",
    "CASTLE_MEMBER_CASTLE_ID_STAMP",
    "CASTLE_MEMBER_CASTLE_ID_STAMP_BYTES",
    "CASTLE_PREFAB_RESOLVER_USES",
    "CASTLE_STATE_FADING",
    "CONTAIN_GET_HORDE_IFACE",
    "CONTAIN_GET_HORDE_IFACE_ENTRY",
    "CONTAIN_GET_HORDE_IFACE_SLOT",
    "CONTAIN_EXIT_ALL_HORDE_TEST",
    "CONTAIN_EXIT_ALL_LOOP",
    "CONTAIN_EXIT_ALL_LOOP_BYTES",
    "CONTAIN_EXIT_ALL_ORDER_EXIT",
    "CONTAIN_EXIT_ALL_PASSENGERS",
    "CONTAIN_EXIT_ALL_WRAPPER_CALLS",
    "CONTAIN_ITEM_LIST",
    "CONTAIN_ITEM_LIST_NODE_OBJECT",
    "CONTAIN_ITEM_LIST_WALK",
    "CONTAIN_ITEM_LIST_WALK_ENTRY",
    "CONTAIN_ITERATE_SLOT",
    "CONTAIN_REMOVE_ALL_SLOT",
    "CREATE_AND_FIRE_TEMP_WEAPON_AT_POSITION",
    "CREATE_AND_FIRE_TEMP_WEAPON_AT_POSITION_ENTRY",
    "CREATE_AND_FIRE_TEMP_WEAPON_AT_VICTIM",
    "CREATE_AND_FIRE_TEMP_WEAPON_AT_VICTIM_ENTRY",
    "DAMAGE_INFO_DAMAGE_TYPE",
    "DAMAGE_INFO_SOURCE_ID",
    "DAMAGE_NUGGET_DEALS_DAMAGE_BODY",
    "DAMAGE_NUGGET_DEALS_DAMAGE_BODY_BYTES",
    "DAMAGE_NUGGET_SUBWEAPON_BODY",
    "DAMAGE_NUGGET_SUBWEAPON_BODY_BYTES",
    "DIE_MODULE_IS_APPLICABLE",
    "DIE_MODULE_IS_APPLICABLE_ENTRY",
    "DIE_MUX_IS_APPLICABLE",
    "DIE_MUX_IS_APPLICABLE_ENTRY",
    "EXPERIENCE_LEVELS_FOR_TEMPLATE",
    "EXPERIENCE_TRACKER_ADD_EXPERIENCE_POINTS",
    "FIRE_WEAPON_WHEN_DAMAGED_ON_DAMAGE",
    "FWWD_FIELD_TABLE",
    "FWWD_FIELD_TABLE_REFS",
    "FWWD_FIELD_TABLE_REF_OPCODES",
    "FWWD_IFACE_MODULE_DATA_DISP",
    "FWWD_MODULEDATA_CTOR",
    "FWWD_MODULEDATA_CTOR_CALL",
    "FWWD_MODULEDATA_CTOR_CALL_BYTES",
    "FWWD_MODULEDATA_NEW",
    "FWWD_MODULEDATA_SIZE",
    "FWWD_MODULEDATA_SIZE_BYTES",
    "FWWD_MODULEDATA_SIZE_VA",
    "FWWD_REACTION_AIM",
    "FWWD_REACTION_AIM_BYTES",
    "FWWD_REACTION_FIRE_CALL",
    "FWWD_REACTION_FIRE_RESUME",
    "FX_LIST_PLAY_AT_OBJECT",
    "GAME_LOGIC_DESTROY_OBJECT",
    "HORDE_CONTAIN_BUILD_SLOTS_SLOT",
    "HORDE_CONTAIN_CREATE_PAYLOAD_CALL",
    "HORDE_CONTAIN_CREATE_PAYLOAD_CALL_BYTES",
    "HORDE_CONTAIN_FULL_STRENGTH_INIT",
    "HORDE_CONTAIN_FULL_STRENGTH_INIT_BYTES",
    "HORDE_CONTAIN_IFACE",
    "HORDE_CONTAIN_ON_OBJECT_CREATED",
    "HORDE_CONTAIN_ON_OBJECT_CREATED_ENTRY",
    "HORDE_CONTAIN_PAYLOAD_NAME",
    "HORDE_CONTAIN_PAYLOAD_NAME_ENTRY",
    "HORDE_CONTAIN_PAYLOAD_NAME_SINGLETON_TEST",
    "HORDE_CONTAIN_PAYLOAD_NAME_SINGLETON_TEST_BYTES",
    "HORDE_CONTAIN_PRODUCED_GATE",
    "HORDE_CONTAIN_PRODUCED_GATE_BYTES",
    "HORDE_CONTAIN_PRODUCED_GATE_TEST",
    "HORDE_CONTAIN_PRODUCED_GATE_TEST_BYTES",
    "HORDE_IFACE_ANY_MEMBER_ACCEPTS_SLOT",
    "HORDE_IFACE_ASSIGN_SLOT",
    "HORDE_IFACE_ASSIGN_SLOT_BYTES",
    "HORDE_IFACE_ASSIGN_SLOT_SLOT",
    "HORDE_IFACE_FREE_SLOTS",
    "HORDE_IFACE_GIVE_UPGRADE_SLOT",
    "HORDE_IFACE_MAX_MEMBERS_SLOT",
    "HORDE_IFACE_MEMBER_COUNT_SLOT",
    "HORDE_IFACE_RESPAWN_MEMBER_SLOT",
    "HORDE_IFACE_SLOTS_BUILT",
    "HORDE_IFACE_SLOT_ARRAY",
    "HORDE_IFACE_SLOT_INDEX",
    "HORDE_IFACE_SLOT_STRIDE",
    "HORDE_PAYLOAD_ENTRY_NAME",
    "HORDE_PAYLOAD_LOOKUP",
    "HORDE_PAYLOAD_LOOKUP_ENTRY",
    "INACTIVE_BODY_ATTEMPT_HEALING",
    "KINDOF_ARMY_SUMMARY_BIT",
    "KINDOF_ARMY_SUMMARY_BYTE",
    "KINDOF_BASE_SITE",
    "KINDOF_DEAD_SLOTS",
    "KINDOF_HERO_BIT",
    "KINDOF_HERO_BYTE",
    "KINDOF_HORDE_BIT",
    "KINDOF_HORDE_BYTE",
    "KINDOF_MACHINE_BYTE",
    "KINDOF_MACHINE_MASK",
    "KINDOF_MASK_OFFSET",
    "KINDOF_NAME_TABLE",
    "KINDOF_NAME_TABLE_COUNT",
    "KINDOF_NAME_TABLE_REFS",
    "KINDOF_PARSE",
    "KINDOF_SUMMONED_BIT",
    "KINDOF_SUMMONED_BYTE",
    "LAYER_AFTER_MOVE_SET_CALL",
    "LAYER_AFTER_MOVE_SET_CALL_ENTRY",
    "LAYER_SET_ARGS_ENTRY",
    "LIFETIME_ALLOC",
    "LIFETIME_ALLOC_BYTES",
    "LIFETIME_ALLOC_RESUME",
    "LIFETIME_ANCHORS",
    "LIFETIME_ARM",
    "LIFETIME_ARM_BYTES",
    "LIFETIME_DIE_FRAME",
    "LIFETIME_EXPIRE",
    "LIFETIME_EXPIRE_BYTES",
    "LIFETIME_EXPIRE_RESUME",
    "LIFETIME_FIELD_TABLE",
    "LIFETIME_FIELD_TABLE_REF",
    "LIFETIME_KILL_RETURN",
    "LIFETIME_LATCH_DEFAULT",
    "LIFETIME_LATCH_DEFAULT_BYTES",
    "LIFETIME_MODULE_DATA_SIZE",
    "LIFETIME_START_FRAME",
    "LIFETIME_STOCK_FIELDS",
    "LIFETIME_UI_FRACTION",
    "LIFETIME_UI_MODULE_READ",
    "LIFETIME_UPDATE",
    "LIFETIME_UPDATE_BYTES",
    "LIFETIME_UPDATE_RESUME",
    "LOCOMOTOR_GET_MAX_SPEED",
    "LOCOMOTOR_GET_MAX_SPEED_ENTRY",
    "LOCOMOTOR_SPEED_MODIFIER_CALL",
    "LOCOMOTOR_SPEED_MODIFIER_CALL_BYTES",
    "LOCOMOTOR_SPEED_MODIFIER_FOLD",
    "LOCOMOTOR_SPEED_MODIFIER_FOLD_BYTES",
    "LOCOMOTOR_SPEED_MODIFIER_SETUP",
    "LOCOMOTOR_SPEED_MODIFIER_SETUP_BYTES",
    "MODEL_CONDITION_BASE_BUILD",
    "MODIFIER_HOLDER_APPLY_FX_CALLS",
    "MODIFIER_HOLDER_APPLY_MODIFIER_LIST",
    "MODIFIER_HOLDER_APPLY_REFUSE_CATEGORY",
    "MODIFIER_HOLDER_APPLY_REFUSE_LOOKUP",
    "MODIFIER_LIST_GET_VALUE",
    "MODIFIER_LIST_IGNORE_IF_ANTICATEGORY_ACTIVE",
    "MODIFIER_LIST_REPLACE_IN_CATEGORY_IF_LONGEST",
    "MODIFIER_TYPE_COMMAND_POINT_BONUS",
    "MODIFIER_TYPE_SPEED",
    "MODULE_MODULE_DATA",
    "MODULE_OWNING_OBJECT",
    "NUGGET_PARSE_TABLE",
    "NUGGET_VTBL_DEALS_DAMAGE",
    "NUGGET_VTBL_SUBWEAPON",
    "NUGGET_VTBL_VALID_VICTIM",
    "OBJECT_AI_UPDATE",
    "OBJECT_ANGLE",
    "OBJECT_APPLY_MODIFIER_LIST",
    "OBJECT_APPLY_MODIFIER_LIST_FAIL_BRANCH",
    "OBJECT_APPLY_MODIFIER_LIST_READD",
    "OBJECT_APPLY_MODIFIER_LIST_SUBTRACT",
    "OBJECT_APPLY_UPGRADE_LIST",
    "OBJECT_ARMY_EXCLUDED",
    "OBJECT_ARMY_EXCLUDED_BIT",
    "OBJECT_ARMY_ID",
    "OBJECT_ATTEMPT_HEALING",
    "OBJECT_BODY_MODULE",
    "OBJECT_BOUNDING_CIRCLE_RADIUS",
    "OBJECT_BOUNDING_CIRCLE_RADIUS_READ",
    "OBJECT_BOUNDING_CIRCLE_RADIUS_READ_BYTES",
    "OBJECT_CAN_ACCEPT_UPGRADE",
    "OBJECT_CONSTRUCTION_PERCENT",
    "OBJECT_CONTAIN",
    "OBJECT_CONTAINED_BY",
    "OBJECT_EFFECTIVELY_DEAD_FLAG",
    "OBJECT_FIELD_TABLE",
    "OBJECT_FIELD_TABLE_REFS",
    "OBJECT_FIELD_TABLE_REF_OPCODES",
    "OBJECT_FILTER_ALLOW",
    "OBJECT_FILTER_IS_VALID",
    "OBJECT_GET_COMMAND_SET_STRING",
    "OBJECT_GET_CONTROLLING_PLAYER",
    "OBJECT_GET_GETTING_BUILT_BEHAVIOR",
    "OBJECT_GET_GETTING_BUILT_BEHAVIOR_ENTRY",
    "OBJECT_GET_HEIGHT_ABOVE_TERRAIN",
    "OBJECT_GET_HEIGHT_ABOVE_TERRAIN_BYTES",
    "OBJECT_GET_HORDE_IFACE",
    "OBJECT_GET_MODIFIER_MULTIPLIER",
    "OBJECT_GIVE_UPGRADE",
    "OBJECT_HAS_MODIFIER",
    "OBJECT_HAS_UPGRADE",
    "OBJECT_ID",
    "OBJECT_IMAGE_UPGRADE_APPEND_FIELD_TABLE",
    "OBJECT_IMAGE_UPGRADE_BUILD_UPGRADE_FIELDS",
    "OBJECT_IMAGE_UPGRADE_BUTTON_HOOK",
    "OBJECT_IMAGE_UPGRADE_BUTTON_RESUME",
    "OBJECT_IMAGE_UPGRADE_FIND_IMAGE",
    "OBJECT_IMAGE_UPGRADE_MODULEDATA_CTOR",
    "OBJECT_IMAGE_UPGRADE_MODULEDATA_VTABLE",
    "OBJECT_IMAGE_UPGRADE_REGISTER",
    "OBJECT_IMAGE_UPGRADE_REGISTER_CALL",
    "OBJECT_IMAGE_UPGRADE_REGISTER_CLEANUP",
    "OBJECT_IMAGE_UPGRADE_RUNTIME_FACTORY_STOCK",
    "OBJECT_IMAGE_UPGRADE_SELECT_DISPLACED_CALL",
    "OBJECT_IMAGE_UPGRADE_SELECT_HOOK",
    "OBJECT_IMAGE_UPGRADE_SELECT_RESUME",
    "OBJECT_IMAGE_UPGRADE_SET_ASCII_CSTR",
    "OBJECT_IMAGE_UPGRADE_THE_CONTROL_BAR",
    "OBJECT_IMAGE_UPGRADE_THE_IMAGES",
    "OBJECT_IMAGE_UPGRADE_UPGRADE_VTABLE",
    "OBJECT_MODULE_LIST",
    "OBJECT_FIND_MODULE",
    "OBJECT_FIND_MODULE_ENTRY",
    "OBJECT_POSITION",
    "OBJECT_POSITION_Z",
    "OBJECT_PRODUCER_ID",
    "OBJECT_REMOVE_MODIFIER_LIST",
    "OBJECT_SCRIPT_NAME",
    "OBJECT_SET_ARMY_ID",
    "OBJECT_SET_LAYER",
    "OBJECT_SET_LAYER_ENTRY",
    "OBJECT_SET_ORIENTATION",
    "OBJECT_SET_POSITION",
    "OBJECT_SET_POSITION_ENTRY",
    "OBJECT_STATUS",
    "OBJECT_STATUS_COUNT",
    "OBJECT_STATUS_DWORDS",
    "OBJECT_STATUS_HORDE_MEMBER",
    "OBJECT_STATUS_NAMES",
    "OBJECT_STATUS_UNDER_CONSTRUCTION",
    "OBJECT_STATUS_UNSELECTABLE",
    "OBJECT_TEAM",
    "OBJECT_TEST_MODEL_CONDITION",
    "OBJECT_TEST_MODEL_CONDITION_ENTRY",
    "OBJECT_TEST_STATUS",
    "OBJECT_THING_TEMPLATE",
    "OBJECT_TO_ARMY_RECORD",
    "OBJECT_TRANSFORM",
    "OBJECT_UPGRADE_MASK",
    "OBJECT_WRITE_ARMY_RECORD_STATE",
    "OPEN_CONTAIN_CONTAIN_INTERFACE",
    "OPEN_CONTAIN_EJECT_PASSENGERS_ON_DEATH",
    "OPEN_CONTAIN_GET_CONTAIN",
    "OPEN_CONTAIN_GET_CONTAIN_BYTES",
    "OPEN_CONTAIN_KILL_RIDERS_NOT_FREE_TO_EXIT_SLOT",
    "OPEN_CONTAIN_ON_DIE_EJECT",
    "OPEN_CONTAIN_ON_DIE_EJECT_BYTES",
    "PARTITION_FILTER_DESTRUCTOR",
    "PARTITION_FILTER_NOT_DESTROYED_VTABLE",
    "PARTITION_FILTER_OBJECT_FILTER_VTABLE",
    "PARTITION_FILTER_SLOT_2",
    "PARTITION_GET_CLOSEST_OBJECT",
    "PASSIVE_AREA_EFFECT_ANCHORS",
    "PASSIVE_AREA_EFFECT_CONSTRUCTION_FALLBACK",
    "PASSIVE_AREA_EFFECT_CONSTRUCTION_FALLBACK_BYTES",
    "PASSIVE_AREA_EFFECT_CONSTRUCTION_GATE",
    "PASSIVE_AREA_EFFECT_CONSTRUCTION_GATE_BYTES",
    "PASSIVE_AREA_EFFECT_DEAD_SLEEP",
    "PASSIVE_AREA_EFFECT_DEAD_SLEEP_BYTES",
    "PASSIVE_AREA_EFFECT_DEAD_TEST",
    "PASSIVE_AREA_EFFECT_MODULE_NAME_STRING",
    "PASSIVE_AREA_EFFECT_PING_SLOT_OFFSET",
    "PASSIVE_AREA_EFFECT_UPDATE",
    "PASSIVE_AREA_EFFECT_UPDATE_VTABLE",
    "PATHFINDER_IN_AI",
    "PATHFINDER_WALL_HEIGHTS",
    "PHYSICS_LAYER_SET_CALL",
    "PHYSICS_LAYER_SET_CALL_ENTRY",
    "SELF_BUILD_HEAL_ANCHOR",
    "SELF_BUILD_HEAL_ANCHOR_BYTES",
    "SELF_BUILD_HEAL_STEP",
    "SELF_BUILD_HEAL_STEP_BYTES",
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
    "SLEEPY_UPDATE_DISPATCH",
    "TERRAIN_GET_LAYER_FOR_DESTINATION",
    "THE_PARTITION_MANAGER",
    "THE_SHROUD_MANAGER",
    "THE_THING_FACTORY",
    "THING_FACTORY_FIND_TEMPLATE",
    "THING_FACTORY_FIND_TEMPLATE_ENTRY",
    "THING_FACTORY_ID_SWAP",
    "THING_FACTORY_ID_SWAP_BYTES",
    "THING_FACTORY_ID_SWAP_RESUME",
    "THING_FACTORY_NEW_OBJECT",
    "THING_TEMPLATE_BUILD_COST",
    "THING_TEMPLATE_COMMAND_POINT_BONUS",
    "THING_TEMPLATE_COPY_CALL",
    "THING_TEMPLATE_COPY_CALL_BYTES",
    "THING_TEMPLATE_COPY_FROM",
    "THING_TEMPLATE_COPY_ID",
    "THING_TEMPLATE_COPY_ID_BYTES",
    "THING_TEMPLATE_COPY_ID_RESUME",
    "THING_TEMPLATE_COPY_KEEP_ID",
    "THING_TEMPLATE_COPY_KEEP_ID_BYTES",
    "THING_TEMPLATE_COPY_KEEP_ID_RESUME",
    "THING_TEMPLATE_ID",
    "THING_TEMPLATE_ID_COUNTER",
    "THING_TEMPLATE_ID_SETTER",
    "THING_TEMPLATE_IS_EQUIVALENT",
    "THING_TEMPLATE_IS_EQUIVALENT_ENTRY",
    "THING_TEMPLATE_KINDOF",
    "THING_TEMPLATE_LOCOMOTOR_SET_SPEED",
    "THING_TEMPLATE_REFUND_VALUE",
    "TOGGLE_MOUNTED_DISMOUNT_HEALTH_COPY",
    "TOGGLE_MOUNTED_HEALTH_COPY_HOOK",
    "TOGGLE_MOUNTED_HEALTH_COPY_SEQUENCE",
    "TOGGLE_MOUNTED_INSTANCE_SIZE",
    "TOGGLE_MOUNTED_MODULE_DATA_SIZE",
    "TOGGLE_MOUNTED_MOUNT_HEALTH_COPY",
    "TOGGLE_MOUNTED_RETIRE",
    "TOGGLE_MOUNTED_RETIRE_BYTES",
    "TOGGLE_MOUNTED_RETIRE_DESTROY",
    "TOGGLE_MOUNTED_SWAP",
    "TOGGLE_MOUNTED_SWAP_FLAG",
    "TOGGLE_MOUNTED_SYNC_SKIP",
    "TOGGLE_MOUNTED_TEMPLATE",
    "TRANSPORT_CONTAIN_CREATE_PAYLOAD",
    "TRANSPORT_CONTAIN_CREATE_PAYLOAD_ENTRY",
    "TRANSPORT_CONTAIN_INITIAL_PAYLOAD",
    "UPDATE_MODULE_DATA",
    "UPDATE_MODULE_OBJECT",
    "UPDATE_MODULE_SLEEP_FOREVER",
    "UPDATE_MODULE_THIS_DELTA",
    "WALL_LAYER_FIRST",
    "WALL_LAYER_LAST",
    "WALL_LAYER_PROMOTION",
    "WALL_LAYER_PROMOTION_ENTRY",
    "WALL_LAYER_PROMOTION_SET_ARGS",
    "WALL_LAYER_PROMOTION_SET_ARGS_ENTRY",
    "WALL_LAYER_PROMOTION_SET_CALL",
    "WALL_LAYER_PROMOTION_SET_CALL_ENTRY",
    "WEAPONTEMPLATE_NUGGET_VECTOR_OFFSET",
    "WEAPON_ANY_NUGGET_VALID_VICTIM",
    "WEAPON_ANY_NUGGET_VALID_VICTIM_BYTES",
    "WEAPON_IS_MELEE",
    "WEAPON_IS_MELEE_BYTES",
    "WEAPON_TARGET_IN_RANGE",
    "WEAPON_TARGET_IN_RANGE_BYTES",
    "WEAPON_TEMPLATE_MELEE_OFFSET",
]

# `ThePartitionManager` and `TheShroudManager`, the two subsystems holding visibility state
# (confirmed live by the name each object stores at `+0x08`).
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
THE_THING_FACTORY = 0x00DE4A40
# `Object::m_id` (measured on 386 live objects). The id space is not dense - engine-reserved objects
# use ids near 99999999 - so anything indexing an array by it must fold or bound it.
OBJECT_ID = 0x74
# The second `ObjectID` on an object, `m_producerID` ("who made me"): the engine's fallback for
# which horde an object belongs to, and the plot a structure stands on. See
# `docs/foundation-rebind.md` section 2.1.
OBJECT_PRODUCER_ID = 0x78
# `Object::m_status`, the 128-bit `ObjectStatusMaskType`, tested through `Object::testStatus(bit)`
# (`0x0044DDEC`); bit numbers follow the status name table.
# `Object::getHeightAboveTerrain`: one `getGroundHeight` call and an `fsubr`, which pins
# `THE_TERRAIN_LOGIC`, its vtable slot and the calling convention in 28 bytes.
OBJECT_GET_HEIGHT_ABOVE_TERRAIN = 0x0070BC6E
OBJECT_GET_HEIGHT_ABOVE_TERRAIN_BYTES = bytes.fromhex(
    "8b0d9046de00d9463c8b016a005151d95c2404d94638d91c24ff5018"
)
# `Object::setPosition(const Coord3D *)` - `__thiscall`, `ret 4` (`0x0070C31B`). Writes the
# object's `Coord3D` at `+0x38` and carries the partition, layer and drawable bookkeeping that
# goes with a move, which is why a cave that wants to change where an object lands calls this
# rather than storing the three floats itself. Derived in `docs/rebuild-hole-repair.md`.
OBJECT_SET_POSITION = 0x0070C201
OBJECT_SET_POSITION_ENTRY = bytes.fromhex("558bec83ec4053")
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
#: `PartitionManager::getClosestObject(Coord3D *where, Real range, Int distType, PartitionFilter
#: *filters)` - `__thiscall` on `[THE_PARTITION_MANAGER]`, `ret 0x10`, the matching `Object *`
#: or NULL. `filters` is an intrusive list: each filter is `{vtable, next}` followed by its own
#: fields, vtable slot 1 is `Bool allow(Object *)` (`ret 4`), and an object must pass every
#: filter on the chain. The forbidden scan passes `distType = 1`.
PARTITION_GET_CLOSEST_OBJECT = 0x00A39090
#: The filter the forbidden scan puts at the head of its list: two dwords, and its `allow`
#: (`0x00660E71`) rejects an object whose `ObjectStatus` `DESTROYED` bit (`Object+0x458` bit 0)
#: is set.
PARTITION_FILTER_NOT_DESTROYED_VTABLE = 0x00C10E20
#: The forbidden scan's own filter, `{vtable, next, ObjectFilter *, Player *, Bool expect}`.
#: Slot 0 (`0x00893738`) is the scalar-deleting destructor and slot 2 (`0x0048DACD`) returns -1;
#: both are shared with `PARTITION_FILTER_NOT_DESTROYED_VTABLE`, and neither reads a field
#: past `next`.
PARTITION_FILTER_OBJECT_FILTER_VTABLE = 0x00BE4CC8
PARTITION_FILTER_DESTRUCTOR = 0x00893738
PARTITION_FILTER_SLOT_2 = 0x0048DACD
#: The `Object` field-parse table: 191 rows, terminator at `0x00DA49E8`, five references. A byte
#: scan's apparent interior reference at `0x007162A4` is a false positive, so it relocates as a
#: unit.
OBJECT_FIELD_TABLE = 0x00DA3DF8
OBJECT_FIELD_TABLE_REFS = (0x0073BDF4, 0x0073BEFB, 0x0073BF4F, 0x0073C142, 0x0073E8C9)
OBJECT_FIELD_TABLE_REF_OPCODES = (0xB8, 0x68, 0x68, 0x68, 0x68)
#: `Object::m_template`. `ThingTemplate` is `0x650` bytes; its name is at `+0x64`, `Side` at
#: `+0x6C`, `CommandSet` at `+0x70`.
OBJECT_THING_TEMPLATE = 0x04
#: `ThingTemplate::copyFrom(source)`, `ret 4`: the only way a template is duplicated (for INI
#: override blocks), so anything keyed on a `ThingTemplate *` must ride it.
THING_TEMPLATE_COPY_FROM = 0x006D1D80
THING_TEMPLATE_COPY_CALL = 0x006D2781
THING_TEMPLATE_COPY_CALL_BYTES = bytes.fromhex("e8faf5ffff")
PATHFINDER_IN_AI = 0x10
PATHFINDER_WALL_HEIGHTS = 0x1BE78
#: `Object`'s world z. The transform's translation row; `+0x38`/`+0x3C`/`+0x40` is the
#: `Coord3D` the pathfinder reads at `0x006F0762`.
OBJECT_POSITION_Z = 0x40
# `push ebp; mov ebp,esp; push ecx; push ecx` - `TerrainLogic::getLayerForDestination(Object *,
# Coord3D *)`. Returns ground, or `16` when the position is on a ramp record
# (`0x006E89EE` at `0x00680B1A`), or the layer the cell names via `0x006EE600` - which over a
# wall's bounds cells is a wall-height layer. Its two `setLayer` callers below apply the result
# with **no height test at all**, which is the second road onto a wall.
TERRAIN_GET_LAYER_FOR_DESTINATION = 0x00680A75
#: `push eax; mov ecx, esi` - the three bytes before each `setLayer` call this patch gates. All
#: three sites share them: the resolved layer in `eax`, the object in `esi`.
LAYER_SET_ARGS_ENTRY = bytes.fromhex("508bce")
#: `setLayer` after a move, in the object-moved path: `setPosition`, `setOrientation`,
#: `getLayerForDestination`, then this. Unconditional.
LAYER_AFTER_MOVE_SET_CALL = 0x0062E15F
LAYER_AFTER_MOVE_SET_CALL_ENTRY = bytes.fromhex("e839da0500")
#: The same shape in the `PhysicsBehavior` translation unit, guarded only by `IMMOBILE`
#: (`test byte [tmpl+0x108], 4` at `0x00797916`) - so it runs for every mobile object that moves.
PHYSICS_LAYER_SET_CALL = 0x0079792F
PHYSICS_LAYER_SET_CALL_ENTRY = bytes.fromhex("e86942efff")
# `Object::setLayer(PathfindLayerEnum)` - `__thiscall`, one stack argument, `ret 4`. Writes the
# layer to `Object+0x428` (`0x0068BBCE`) and unregisters from the old layer through
# `TheTerrainLogic` vtable `+0xAC` first. `Object::getLayer` (`0x0068BBE0`) reads the same field
# back, forcing `1` while `Object+0x4AC` is set. Derived in `docs/wall-layer-promotion.md`.
OBJECT_SET_LAYER = 0x0068BB9D
OBJECT_SET_LAYER_ENTRY = bytes.fromhex("568bf18b8628040000")  # push esi; mov esi,ecx; mov eax,...
#: Base of the `ThingTemplate`'s `KindOf` bitmask. `0x00936BCE` reads bits 32..63 at `+0x10C`,
#: which fixes the base at `+0x108`; a flag's index gives its byte and bit from there.
THING_TEMPLATE_KINDOF = 0x108
#: `MACHINE` is `KindOf` index 11 - bit `0x08` of the byte at `THING_TEMPLATE_KINDOF + 1`. Every
#: siege engine in the shipped data carries it and no infantry does.
KINDOF_MACHINE_BYTE = 0x109
KINDOF_MACHINE_MASK = 0x08
#: The wall-height layer numbers, straight out of `isWallLayer` (`0x006E82B3`:
#: `cmp [esp+4],0x11 / jl -> 0`, `cmp [esp+4],0x40 / jg -> 0`). A wall stamps one of these into
#: the ground cells its `WallBoundsMesh` covers, and the layer's surface is the flat constant at
#: `Pathfinder+0x1BE78 + layer*4`. Layer `16` is the *ramp* layer and is deliberately outside
#: this range - see `docs/wall-layer-promotion.md` §6b.
WALL_LAYER_FIRST = 0x11
WALL_LAYER_LAST = 0x40
# `push ebp; mov ebp,esp; sub esp,0x10` - `Pathfinder::updateObjectLayer(Object *)`, `__thiscall`
# on the `Pathfinder`, `ret 4`. Reads the cell under the object's centre and, if that cell names a
# layer whose surface is more than 10 units above the object, moves the object to it.
WALL_LAYER_PROMOTION = 0x006F0741
WALL_LAYER_PROMOTION_ENTRY = bytes.fromhex("558bec83ec10")
#: `push eax; mov ecx, esi` - the argument (the cell's stamped layer) and the object, set up
#: immediately before the call below. Asserted so the cave's reading of `ecx` and `[esp+4]` is
#: pinned to this build rather than assumed.
WALL_LAYER_PROMOTION_SET_ARGS = 0x006F07DA
WALL_LAYER_PROMOTION_SET_ARGS_ENTRY = bytes.fromhex("508bce")
#: The `setLayer` call in the `h > z + 10` arm - the teleport itself, and the only engine bytes
#: `wall-layer-promotion` edits. Its rel32 is re-aimed at the gate cave, which tail-calls
#: `OBJECT_SET_LAYER` or returns without it.
WALL_LAYER_PROMOTION_SET_CALL = 0x006F07DD
WALL_LAYER_PROMOTION_SET_CALL_ENTRY = bytes.fromhex("e8bbb3f9ff")
# `ObjectStatus::UNSELECTABLE`, bit 3 of the mask at `OBJECT_STATUS`. Index 3 of the name table at
# `OBJECT_STATUS_NAMES`. On a plot flag this is the engine's own record that the plot has been
# claimed: measured across all 20 capture flags of a live match, every unclaimed plot carried
# `UNATTACKABLE` alone and every claimed one carried `UNATTACKABLE | UNSELECTABLE`.
OBJECT_STATUS_UNSELECTABLE = 3
# `KindOf BASE_SITE`, bit 120 of `KindOfMaskType` - index 120 of the name table at
# `patches.utils.kind_of.NAME_TABLE_VA`. What separates a build **plot** (a flag a structure is
# raised on, so an enemy-held one has to be destroyed rather than walked onto) from a plain
# capture flag (recaptured by standing on it, which is the tactic's real purpose).
KINDOF_BASE_SITE = 120
# `ObjectStatus::UNDER_CONSTRUCTION`, bit 2 of the mask at `OBJECT_STATUS`, tested through
# `OBJECT_TEST_STATUS`. Index 2 of the name table at `OBJECT_STATUS_NAMES`, and confirmed on
# live-captured bytes: the half-built `ElvenMallornTree_Extern` in
# `tests/sage_live/fixtures/match.snapshot.gz` reads `[obj+0x94] == 4`.
OBJECT_STATUS_UNDER_CONSTRUCTION = 2
# `DieModule::isDieApplicable`, a thunk onto `DIE_MUX_IS_APPLICABLE`, and the shared filter it
# calls. The filter reads `DeathTypes` (moduleData `+0x0`), `ExemptStatus` (`+0x4`) and
# `RequiredStatus` (`+0x14`) against the dying object's status bitset at `+0x94`, then
# `DamageAmountRequired` and the killer-angle window. Every die module opens with it, which is
# what lets a hardcoded status rule be retired into `ExemptStatus` rather than simply deleted.
DIE_MODULE_IS_APPLICABLE = 0x0085FED5
DIE_MODULE_IS_APPLICABLE_ENTRY = bytes.fromhex("8b4108ff742404")
DIE_MUX_IS_APPLICABLE = 0x008D29A9
DIE_MUX_IS_APPLICABLE_ENTRY = bytes.fromhex("558bec83ec0c5657")
# `Object+0x24C` is a pointer to a **NULL-terminated** array of `BehaviorModule*`. Read off
# `getProductionUpdateInterface` (`0x0068C327`), which is `mov esi,[ecx+0x24c]` and then walks
# `esi` in steps of 4 until it loads NULL. Three interface getters in a row share the idiom,
# so the offset is corroborated three times over rather than inferred from one.
OBJECT_MODULE_LIST = 0x24C
THING_TEMPLATE_COMMAND_POINT_BONUS = 0x62C
MODIFIER_TYPE_COMMAND_POINT_BONUS = 24
#: `Object::applyModifierList`, the door for all 32 attribute-modifier sites. A refused apply
#: returns before re-adding the object's command-point contribution, losing it for good.
OBJECT_APPLY_MODIFIER_LIST = 0x0068F1A8
OBJECT_APPLY_MODIFIER_LIST_SUBTRACT = 0x0068F225
OBJECT_APPLY_MODIFIER_LIST_FAIL_BRANCH = 0x0068F23A
OBJECT_APPLY_MODIFIER_LIST_READD = 0x0068F243
OBJECT_REMOVE_MODIFIER_LIST = 0x0068F2A0
MODIFIER_HOLDER_APPLY_MODIFIER_LIST = 0x00805A8E
#: The two `call FX_LIST_PLAY_AT_OBJECT` inside `MODIFIER_HOLDER_APPLY_MODIFIER_LIST` that play a
#: list's `FX`/`FX2`/`FX3` on the object it lands on: the first when the list is newly applied,
#: the second when a live one is refreshed. Neither is gated on anything about the target.
MODIFIER_HOLDER_APPLY_FX_CALLS = (0x00805CBB, 0x00805D32)
MODIFIER_HOLDER_APPLY_REFUSE_CATEGORY = 0x00805B9C
MODIFIER_HOLDER_APPLY_REFUSE_LOOKUP = 0x00805B01
MODIFIER_LIST_REPLACE_IN_CATEGORY_IF_LONGEST = 0xD2
MODIFIER_LIST_IGNORE_IF_ANTICATEGORY_ACTIVE = 0xD3
#: `ObjectFilter::isValid` (thiscall, no arguments, `bool` in `al`) and the two-argument
#: `ObjectFilter::allow(Object*, Player*)` (thiscall, `ret 8`). Called back-to-back at
#: `0x008855BC`/`0x008855CE`; re-running the pair is how a second modifier taxes exactly the
#: objects the stock inflation taxes.
OBJECT_FILTER_IS_VALID = 0x00762977
OBJECT_FILTER_ALLOW = 0x007640C1
#: `ActiveBody::attemptHealing`, which every heal reaches; `_AMOUNT_FSTP` is the only place the
#: amount exists. See `docs/healing-received-modifier.md`.
ACTIVE_BODY_ATTEMPT_HEALING = 0x008C2FC1
ACTIVE_BODY_ATTEMPT_HEALING_AMOUNT_FSTP = 0x008C3066
ACTIVE_BODY_ATTEMPT_HEALING_AMOUNT_FSTP_BYTES = bytes.fromhex("d95dfcd9ee")
ACTIVE_BODY_ATTEMPT_HEALING_AMOUNT_TEST = 0x008C3072
INACTIVE_BODY_ATTEMPT_HEALING = 0x008C191D
OBJECT_ATTEMPT_HEALING = 0x00690532
#: `Armor::adjustDamage(DamageInfoInput*, Object *source, Int)` - thiscall, result in `st(0)`. It
#: returns its input **unscaled** for damage type 7 at `..._HEALING_PASSTHROUGH`, which is the
#: engine's own statement that a heal is the raw-amount path and armour has no opinion about it.
ARMOR_ADJUST_DAMAGE = 0x005D893C
ARMOR_ADJUST_DAMAGE_HEALING_PASSTHROUGH = 0x005D8963
#: `ActiveBody::internalChangeHealth` - body vtable slot `+0x84`, thiscall, `ret 8`, taking the
#: delta and the `DamageInfo`. Both `attemptHealing` and `attemptDamage` end at it, and so do the
#: paths that are **not** heals - respawn, level-up and max-health changes through slots `+0x08`,
#: `+0x0C` and `+0x14`, and the `DozerAIUpdate` construction ramp.
ACTIVE_BODY_INTERNAL_CHANGE_HEALTH = 0x008C31A5
ACTIVE_BODY_INTERNAL_CHANGE_HEALTH_SLOT = 0x84
#: `Object::hasModifier` sums and `getModifierMultiplier` multiplies. The latter may return without
#: writing `out`, so callers seed it themselves.
OBJECT_HAS_MODIFIER = 0x0068C818
OBJECT_GET_MODIFIER_MULTIPLIER = 0x0068C82D
MODIFIER_LIST_GET_VALUE = 0x00805268
#: `Object::m_position`, three floats. The floating-text sites read it as `[obj+0x38]`,
#: `[obj+0x3c]`, `[obj+0x40]` and hand `addFloatingText` a `Coord3D` copy.
OBJECT_POSITION = 0x38
#: `ThingTemplate+0x5E8`: not free space but the template's engine-assigned id, which is why
#: `BuildCost2` is kept in a cave.
THING_TEMPLATE_ID = 0x5E8
THING_TEMPLATE_ID_SETTER = 0x006CFBC7
THING_TEMPLATE_ID_COUNTER = 0x00DA18E4
THING_TEMPLATE_BUILD_COST = 0x5EA
THING_TEMPLATE_REFUND_VALUE = 0x5EC
#: The id copy inside `ThingTemplate::copyFrom` (`eax` source, `ebx` destination). Hooking the body
#: covers every caller; `hero-mana` hooks the call site instead.
THING_TEMPLATE_COPY_ID = 0x006D24B7
THING_TEMPLATE_COPY_ID_BYTES = bytes.fromhex("668b88e8050000")
THING_TEMPLATE_COPY_ID_RESUME = 0x006D24BE
#: Inside the identity-keeping copy at `0x007405B1` (reached from `0x006D29C0` and `0x006D2A54`):
#: it saves the template's own id in `bx`, runs `copyFrom` (which copies the source's id over it),
#: then restores the id here. `esi` is the destination, so at this store `[esi+0x5E8]` still holds
#: the source's id and `bx` the destination's own.
THING_TEMPLATE_COPY_KEEP_ID = 0x00740630
THING_TEMPLATE_COPY_KEEP_ID_BYTES = bytes.fromhex("66899ee8050000")
THING_TEMPLATE_COPY_KEEP_ID_RESUME = 0x00740637
#: `ThingFactory::addTemplate` (`0x006D10DE`) meeting a name already registered: the new template
#: (`esi`) has just taken the old one's id, and this hands the old one (`eax` = its `+0x5E8`) a
#: fresh id off the top counter. `mov ecx,[ctr]` / `dec word [ctr]` / `mov [eax],cx`, no relative
#: operand; `ecx` and `edx` are dead at the resume.
THING_FACTORY_ID_SWAP = 0x006D112D
THING_FACTORY_ID_SWAP_BYTES = bytes.fromhex("8b0de418da0066ff0de418da00668908")
THING_FACTORY_ID_SWAP_RESUME = 0x006D113D
#: `KindOf ARMY_SUMMARY` is index 128 - bit `0x01` of KindOf byte `+0x10`, `template + 0x118`. The
#: harvest requires it, and so does the engine's own ledger walk at `0x0078100E`.
KINDOF_ARMY_SUMMARY_BYTE = 0x118
KINDOF_ARMY_SUMMARY_BIT = 0x01
#: The third of `LIVING_WORLD_BATTLE_HARVEST`'s per-object filters (`0x00811EA2`): bit 0 set
#: disqualifies an object from an army. `Object+0x458` is a bitfield whose bits `0x02`, `0x04`,
#: `0x08` and `0x10` each have a setter; **bit 0 has none** - the only writes that reach it are the
#: zeroing stores in the constructors at `0x00699C76` and `0x00679E79`, so on an `Object` this
#: filter never rejects anything. See `docs/living-campaign/army-id-custody.md`.
OBJECT_ARMY_EXCLUDED = 0x458
OBJECT_ARMY_EXCLUDED_BIT = 0x01
# The living-world army id an object carries, and the chain of custody that puts it there.
# Derived in `docs/living-campaign/army-id-custody.md`. The harvest's fourth filter
# (`0x00811EAA`) drops any object holding zero here, which is why a summoned or spawned unit
# never comes home even when its template carries `KindOf = ARMY_SUMMARY`.

#: `Object+0x47C`, zeroed by the constructor at `0x00699CD8`. The harvest files each survivor into
#: `findArmyById(obj->[0x47C])`, so this names *which* army an object goes home to.
OBJECT_ARMY_ID = 0x47C
#: `Object::setArmyId(id)` - thiscall, `ret 4`. Writes `OBJECT_ARMY_ID`, then broadcasts the id to
#: every behavior module through virtual slot `+0xB8` of the module's `+0xC` interface
#: (`0x0068C154`). The bare setter at `0x0069A6F8` writes the field without the broadcast and is
#: reached only through the interface vtables at `Object+0x6C` / `Object+0x70`.
OBJECT_SET_ARMY_ID = 0x0068C17D
#: The `KindOf` name table: 222 entries, NULL terminator at `0x00DA11E0`, immediately followed by
#: another table - so adding a token means relocating it and repointing the 14 `.text` references.
#: The parse (`0x0065621C`, from the `KindOf` field row at `0x00DA4148`, template offset `0x108`)
#: sets bit `index & 0x1F` of dword `index >> 5` with no width check, so index 222 lands in dword 6
#: - `template + 0x123` bit `0x40` - inside space the template already allocates.
KINDOF_NAME_TABLE = 0x00DA0E68
KINDOF_NAME_TABLE_COUNT = 222
KINDOF_NAME_TABLE_REFS = (
    0x00655B67,
    0x00655BA7,
    0x00655C12,
    0x006AAD0F,
    0x006AAD20,
    0x006AAD25,
    0x007079FF,
    0x007B3CDB,
    0x007B67E3,
    0x007B67F3,
    0x007B6869,
    0x007B6885,
    0x007B6899,
    0x007B68DD,
)
#: Where the `KindOf` mask begins in a `ThingTemplate`, and the parse that fills it.
KINDOF_MASK_OFFSET = 0x108
KINDOF_PARSE = 0x0065621C
#: `KindOf SUMMONED` is index 179 - bit `0x08` of KindOf byte `+0x17`, `template + 0x11E`. Edain
#: sets it on 530 templates, 220 of which also carry `ARMY_SUMMARY`. **Not** a usable carry-over
#: switch: it is load-bearing for targeting (`ObjectFilter = ANY +HERO -SUMMONED ...`), so a
#: template cannot be summon-filtered and non-persistent at the same time.
KINDOF_SUMMONED_BYTE = 0x11E
KINDOF_SUMMONED_BIT = 0x08
#: The two `KindOf` slots unused by both the engine and Edain's data, so one can be repointed to a
#: new token instead of relocating the name table.
KINDOF_DEAD_SLOTS = {
    13: ("HUGE_VEHICLE", 0x109, 0x20),
    29: ("WAVE_EFFECT", 0x10B, 0x20),
}
#: `KindOf HERO` is index 90 - bit `0x04` of KindOf byte `+0xB`, which is `template + 0x113`.
KINDOF_HERO_BYTE = 0x113
KINDOF_HERO_BIT = 0x04
# Combo-horde recruitment
# Derived in `docs/combo-horde-recruitment.md`. A horde produced by a building never fills itself:
# `HordeContain::onObjectCreated` returns at its second instruction when the object has a
# producer, and the building fills it instead - through a production queue entry that carries one
# `ThingTemplate` and one count, fed by a getter that answers only for single-payload hordes.

#: `HordeContain::onObjectCreated` - module vtable slot `+0x70`, shared by `HordeContain`,
#: `HorseHordeContain` and `AODHordeContain` (slots `0x00C5B668`, `0x00C5C2F8`, `0x00C5D460`).
HORDE_CONTAIN_ON_OBJECT_CREATED = 0x00871B9B
HORDE_CONTAIN_ON_OBJECT_CREATED_ENTRY = bytes.fromhex("b8dff7b900e84bb31c00")
#: `mov eax, [esi+8]` / `mov eax, [eax+0x78]` - the producer read whose result the very next
#: instruction turns into "skip the whole function". The six bytes `combo-horde-recruitment`
#: replaces with a `call` into its cave.
HORDE_CONTAIN_PRODUCED_GATE = 0x00871BAB
HORDE_CONTAIN_PRODUCED_GATE_BYTES = bytes.fromhex("8b46088b4078")
#: `test eax, eax` / `jne <epilogue>` - the branch itself, left stock by the patch, which only
#: changes what `eax` holds when it is reached. Asserted so a build that moved the jump cannot be
#: patched into falling through unconditionally.
HORDE_CONTAIN_PRODUCED_GATE_TEST = 0x00871BB1
HORDE_CONTAIN_PRODUCED_GATE_TEST_BYTES = bytes.fromhex("85c00f857b010000")
#: The `call TransportContain::createPayload` the gate skips - the one path that reads every
#: `InitialPayload` entry.
HORDE_CONTAIN_CREATE_PAYLOAD_CALL = 0x00871BBB
HORDE_CONTAIN_CREATE_PAYLOAD_CALL_BYTES = bytes.fromhex("e83a86ffff")
#: `TransportContain::createPayload` - outer loop over the payload list, inner loop over each
#: entry's count. `__thiscall`, no arguments.
TRANSPORT_CONTAIN_CREATE_PAYLOAD = 0x0086A1FA
TRANSPORT_CONTAIN_CREATE_PAYLOAD_ENTRY = bytes.fromhex("558bec83ec1456578bf98b47048945ec")
#: `mov dword [esi+0x2a8], 0x64` in the `HordeContain` constructor - the strength percent the
#: trim block below the gate reads. 100 means "destroy nobody", which is what makes it safe for a
#: recruited combo horde to run that block for the first time.
HORDE_CONTAIN_FULL_STRENGTH_INIT = 0x00872972
HORDE_CONTAIN_FULL_STRENGTH_INIT_BYTES = bytes.fromhex("c786a802000064000000")
#: The contain-module interface's `+0x24`: the `InitialPayload` template name, returned **only**
#: when the list holds exactly one entry and the empty string otherwise. The single point at
#: which a combo horde's mix is discarded.
HORDE_CONTAIN_PAYLOAD_NAME = 0x0087048F
HORDE_CONTAIN_PAYLOAD_NAME_ENTRY = bytes.fromhex("558bec518b91e8feffff8b8aa4000000")
#: `cmp esi, 1` / `jne <empty string>` inside it - the defect, in two instructions.
HORDE_CONTAIN_PAYLOAD_NAME_SINGLETON_TEST = 0x008704B2
HORDE_CONTAIN_PAYLOAD_NAME_SINGLETON_TEST_BYTES = bytes.fromhex("83fe01750d")
#: `Module+0x04` is its `ModuleData`, `Module+0x08` the `Object` that owns it - both read by the
#: gate cave, and both pinned by `TRANSPORT_CONTAIN_CREATE_PAYLOAD_ENTRY`'s `mov eax,[edi+4]` and
#: the stock gate's `mov eax,[esi+8]`.
MODULE_MODULE_DATA = 0x04
MODULE_OWNING_OBJECT = 0x08
#: `TransportContainModuleData::m_initialPayload` - an MSVC `std::list` head (one pointer to a
#: self-linked sentinel node); each node is `{next, prev, {AsciiString name, Int count}}`.
TRANSPORT_CONTAIN_INITIAL_PAYLOAD = 0xA4
#: `ContainModuleInterface::getHordeIface`, vtable slot `+0x7C`, `__thiscall` with no arguments.
#: `HordeContain`'s is `lea eax,[ecx-0x20]` / `add ecx, 0xFC` / a NULL-preserving `and` - that is,
#: it hands back the sub-object at module `+0x11C` (`HORDE_CONTAIN_IFACE`), whose vtable is
#: `0x00C5B1F8`. This is the pair of addresses that ties `[obj+0x258]` to the horde interface.
CONTAIN_GET_HORDE_IFACE_SLOT = 0x7C
CONTAIN_GET_HORDE_IFACE = 0x00872A6F
CONTAIN_GET_HORDE_IFACE_ENTRY = bytes.fromhex("8d41e081c1fc000000f7")
#: `HordeContain`'s horde-interface sub-object, at module `+0x11C`. Its methods reach the module
#: back through `lea ecx, [this-0x11C]` and the `ModuleData` through `[this-0x118]`
#: (= module `+0x04`, `MODULE_MODULE_DATA`).
HORDE_CONTAIN_IFACE = 0x11C
#: Horde-interface slot `+0x2C`: give this object a formation slot. It walks the horde's
#: **remaining** slots and takes the first whose declared payload template is equivalent to the
#: object's - so it is already the engine's own answer to "does this object belong in this
#: horde", and `horde-exit-absorption` mirrors exactly this walk.
HORDE_IFACE_ASSIGN_SLOT_SLOT = 0x2C
HORDE_IFACE_ASSIGN_SLOT = 0x00873F30
HORDE_IFACE_ASSIGN_SLOT_BYTES = bytes.fromhex(
    "558bec515153568bf1807e7c005775108d8ee4feffff8b016a01ff90840000008b46788b383bf80f8484000000"
    "8b5d088b47088b4e6c8945fc6bc01cff34088b8ee8feffffe86d84ffff85c0741c8b0d404ade0083c00450e878"
    "d3e5ff8b4b0450e82c96ecff84c07509"
)
#: The fields of that interface the walk reads. `+0x78` is an MSVC `std::list` head - one pointer
#: to a self-linked sentinel - of the slots still unfilled, each node carrying its index at
#: `+0x08`; `+0x6C` is the slot array those index, stride `0x1C`, first dword the payload key;
#: `+0x7C` is the "slots have been built" flag that makes the list lazy.
HORDE_IFACE_SLOT_ARRAY = 0x6C
HORDE_IFACE_FREE_SLOTS = 0x78
HORDE_IFACE_SLOTS_BUILT = 0x7C
HORDE_IFACE_SLOT_STRIDE = 0x1C
HORDE_IFACE_SLOT_INDEX = 0x08
#: `HordeContain` vtable `+0x84`, called with `1` when `HORDE_IFACE_SLOTS_BUILT` is still clear:
#: it is what fills `HORDE_IFACE_FREE_SLOTS` in the first place.
HORDE_CONTAIN_BUILD_SLOTS_SLOT = 0x84
#: Payload key -> declared entry, over the `ModuleData` vector at `+0x18C`..`+0x190`.
#: `__thiscall`, `ret 4`, NULL when the key names no entry; the entry's template **name** starts
#: at `HORDE_PAYLOAD_ENTRY_NAME`.
HORDE_PAYLOAD_LOOKUP = 0x0086C3E7
HORDE_PAYLOAD_LOOKUP_ENTRY = bytes.fromhex("8b918c0100008b899001")
HORDE_PAYLOAD_ENTRY_NAME = 0x04
#: `ThingFactory::findTemplate(name)` - `__thiscall` on `THE_THING_FACTORY`, `ret 4`.
THING_FACTORY_FIND_TEMPLATE = 0x006D1305
THING_FACTORY_FIND_TEMPLATE_ENTRY = bytes.fromhex("558bec5151ff7508")
#: `ThingTemplate::isEquivalentTo(other)` - `__thiscall`, `ret 4`. Compares final overrides first
#: and then the two name lists at `+0x33C`/`+0x340`, so an upgraded variant still answers yes.
THING_TEMPLATE_IS_EQUIVALENT = 0x0073D5C2
THING_TEMPLATE_IS_EQUIVALENT_ENTRY = bytes.fromhex("558bec83ec0c5356")
# Attack eligibility: does a weapon's nugget actually damage the target
# All derived in `docs/attack-requires-damage.md`.

#: `WeaponTemplate::<any-nugget-accepts-victim>` - `__thiscall`, `ret 8`, `this` = `WeaponTemplate`,
#: stack args `victim` at `[esp+4]` and `weapon` at `[esp+8]`. Walks the nugget vector at
#: `WEAPONTEMPLATE_NUGGET_VECTOR_OFFSET` and returns TRUE on the first nugget whose vtable
#: `NUGGET_VTBL_VALID_VICTIM` accepts the victim - with no regard for whether that nugget deals
#: damage. This is the check `attack-requires-damage` narrows.
WEAPON_ANY_NUGGET_VALID_VICTIM = 0x006CB779
WEAPON_ANY_NUGGET_VALID_VICTIM_BYTES = bytes.fromhex("837c240400578bf97504")
#: The `call WEAPON_ANY_NUGGET_VALID_VICTIM` that is the final answer of the attack-eligibility
#: predicate `0x006CDBF3` (auto-acquire, attack-move, right-click). The two other callers of that
#: routine (`0x0090F527`, `0x0090F97E`) are sub-weapon nuggets' own valid-victim methods, used
#: while firing, and are deliberately left stock - so only this call site is hooked.
ATTACK_ELIGIBILITY_NUGGET_CALL = 0x006CDCD1
#: The 16-byte run the call sits in: `mov ecx,[ebx+4]` / `push ebx` / `push esi` / `call` / `pop
#: esi` / `mov ecx,[ebp-0xc]` / `pop edi` / `pop ebx`. Pins that this call really is the predicate's
#: tail; the 5 call bytes start at offset 5.
ATTACK_ELIGIBILITY_NUGGET_CALL_WINDOW = 0x006CDCCC
ATTACK_ELIGIBILITY_NUGGET_CALL_WINDOW_BYTES = bytes.fromhex("8b4b045356e8a3daffff5e8b4df45f5b")
#: `WeaponTemplate` nugget vector (`std::list`) head; each node's nugget pointer is at `+0x08`.
WEAPONTEMPLATE_NUGGET_VECTOR_OFFSET = 0x17C
#: Nugget vtable slots the cave uses. `+0x04` answers "is this a valid victim"; `+0x1C` is a bool
#: "this nugget deals direct damage" (`DamageNugget` -> 1, base/knockback/attribute-modifier -> 0);
#: `+0x2C` returns a sub-weapon `WeaponTemplate*` (a `ProjectileNugget`'s way of dealing damage,
#: NULL on a `DamageNugget`). "Can damage the victim" = `+0x04` AND (`+0x1C` OR `+0x2C != 0`).
NUGGET_VTBL_VALID_VICTIM = 0x04
NUGGET_VTBL_DEALS_DAMAGE = 0x1C
NUGGET_VTBL_SUBWEAPON = 0x2C
#: The two `DamageNugget` vtable slot bodies the discriminator rests on, anchored so a build that
#: read them differently fails before applying. `+0x1C` -> `mov al,1; ret`; `+0x2C` -> `xor
#: eax,eax; ret`.
DAMAGE_NUGGET_DEALS_DAMAGE_BODY = 0x008BD372
DAMAGE_NUGGET_DEALS_DAMAGE_BODY_BYTES = bytes.fromhex("b001c3")
DAMAGE_NUGGET_SUBWEAPON_BODY = 0x00851E97
DAMAGE_NUGGET_SUBWEAPON_BODY_BYTES = bytes.fromhex("33c0c3")
#: The nugget parse table: a NULL-terminated array of `{const char *name, ParseFn parse, 0, 0}`
#: rows. Walking it is how every nugget's parse function - and through the `call OPERATOR_NEW`
#: that follows, its constructor and vtable - was identified.
NUGGET_PARSE_TABLE = 0x00C17458
#: The nuggets that make a weapon able to attack a victim, as `{name: vtable}`. An allowlist,
#: because the engine's damage getters disagree with it in both directions.
ATTACK_NUGGET_VTABLES = {
    "DOTNugget": 0x00C7BAE8,
    "DamageContainedNugget": 0x00C7BA60,
    "DamageFieldNugget": 0x00C7B3A8,
    "DamageNugget": 0x00C7AE78,
    "GrabNugget": 0x00C7B970,
    "HordeAttackNugget": 0x00C7BCAC,
    "ProjectileNugget": 0x00C7B538,
    "SlaveAttackNugget": 0x00C7B9B0,
}
#: The `mov dword ptr [esi], <vtable>` each of those nuggets' constructor executes, as
#: `{VA: bytes}`. This is what ties a bare vtable address to the nugget it belongs to: the
#: constructor is reached from that nugget's own `NUGGET_PARSE_TABLE` row, so a build that
#: laid the nuggets out differently fails here rather than allowlisting the wrong eight.
ATTACK_NUGGET_VTABLE_STORES = {
    0x009114AA: bytes.fromhex("c706e8bac700"),  # DOTNugget
    0x00911158: bytes.fromhex("c70660bac700"),  # DamageContainedNugget
    0x0090F759: bytes.fromhex("c706a8b3c700"),  # DamageFieldNugget
    0x0090DDF5: bytes.fromhex("c70678aec700"),  # DamageNugget
    0x00910D62: bytes.fromhex("c70670b9c700"),  # GrabNugget
    0x00911B41: bytes.fromhex("c706acbcc700"),  # HordeAttackNugget
    0x0090FF04: bytes.fromhex("c70638b5c700"),  # ProjectileNugget
    0x00910E97: bytes.fromhex("c706b0b9c700"),  # SlaveAttackNugget
}
# Reaction weapons: where `FireWeaponWhenDamagedBehavior` aims the weapon it fires, and the
# `WeaponTemplate` entry points it could aim it with. All derived in `docs/fire-at-attacker.md`.

#: `WeaponTemplate::createAndFireTempWeapon(Object *source, Object *victim)` - `__thiscall`,
#: `ret 8`, `this` = the `WeaponTemplate`. Fires the weapon **at an object**: it passes the victim
#: and its `OBJECT_ID` into the shared firing routine `0x006CEF6D`, which is what makes a nugget
#: with no `Radius` still land. Two stock callers, both inside `TheWeaponStore`.
CREATE_AND_FIRE_TEMP_WEAPON_AT_VICTIM = 0x006CF3AE
CREATE_AND_FIRE_TEMP_WEAPON_AT_VICTIM_ENTRY = bytes.fromhex("8b4424088b50746a006a00")
#: `WeaponTemplate::createAndFireTempWeapon(Object *source, const Coord3D *at)` - `__thiscall`,
#: `ret 8`. The **positional** sibling of the above: it passes the same firing routine a NULL
#: victim object and a bare position, so only nuggets with a `Radius` reach anything. Six stock
#: callers, two of them `FireWeaponWhenDamagedBehavior`'s.
CREATE_AND_FIRE_TEMP_WEAPON_AT_POSITION = 0x006CF3D2
CREATE_AND_FIRE_TEMP_WEAPON_AT_POSITION_ENTRY = bytes.fromhex("558bec5133c08d55fc")
#: `DamageInfo` offsets. `+0x08` is the `ObjectID` of whatever dealt the damage - the field
#: `ReflectDamage::onDamage` resolves through `GAME_LOGIC_FIND_OBJECT_BY_ID` and
#: `FireWeaponWhenDamagedBehavior::onDamage` reads no part of. `+0x10` is the `DamageType`, which
#: both of them filter on.
DAMAGE_INFO_SOURCE_ID = 0x08
DAMAGE_INFO_DAMAGE_TYPE = 0x10
#: `FireWeaponWhenDamagedBehavior::onDamage` - slot 0 of the module's damage-interface vtable
#: (`0x00C5FE10`), `__thiscall`, `ret 4`, the `DamageInfo*` at `[esp+4]` on entry. `esi` is the
#: interface sub-object throughout and `edi` is the owning `Object` from `0x00885D12` on.
FIRE_WEAPON_WHEN_DAMAGED_ON_DAMAGE = 0x00885CD5
#: The `ModuleData` pointer, as `onDamage` reaches it: `[esi-0x24]`, the interface sub-object
#: sitting at module `+0x28` and `MODULE_MODULE_DATA` at module `+0x04`. Pinned by the two
#: stock reads through it - `DamageTypes` at `+0x13C` and `DamageAmount` at `+0x140`.
FWWD_IFACE_MODULE_DATA_DISP = -0x24
#: Where the four body-state arms converge to aim the reaction weapon: `lea eax,[edi+0x38]` /
#: `push eax` / `push edi`, the owning object's **own** position and itself as the source. Every
#: arm jumps here, so the whole block has one entry - and it is exactly five bytes, which is a
#: `jmp rel32` and not one byte more.
FWWD_REACTION_AIM = 0x00885D81
FWWD_REACTION_AIM_BYTES = bytes.fromhex("8d47385057")
#: The `call CREATE_AND_FIRE_TEMP_WEAPON_AT_POSITION` the aim falls into, and the instruction
#: after it (`pop edi` / `pop esi` / `ret 4`) for a cave that made the call itself.
FWWD_REACTION_FIRE_CALL = 0x00885D86
FWWD_REACTION_FIRE_RESUME = 0x00885D8B
#: `FireWeaponWhenDamagedBehavior`'s `newModuleData`: `operator new(0x164)` then the constructor.
#: The size is a bare `push imm32`, which is what makes the block growable by four bytes.
FWWD_MODULEDATA_NEW = 0x00653466
FWWD_MODULEDATA_SIZE_VA = 0x00653467
FWWD_MODULEDATA_SIZE_BYTES = bytes.fromhex("6864010000")
FWWD_MODULEDATA_SIZE = 0x164
#: Inside it, the `call` to the `ModuleData` constructor. `__thiscall` with no arguments,
#: returning `this` in `eax`, which is what lets a shim run it and then write one more field.
FWWD_MODULEDATA_CTOR = 0x006533E5
FWWD_MODULEDATA_CTOR_CALL = 0x00653478
FWWD_MODULEDATA_CTOR_CALL_BYTES = bytes.fromhex("e868ffffff")
#: `FireWeaponWhenDamagedBehavior`'s own INI field-parse table, and the single instruction that
#: names it - `push 0xC06698` inside the module's parse callback, which walks this table and then
#: the shared `UpgradeMux` one at base offset 8.
FWWD_FIELD_TABLE = 0x00C06698
FWWD_FIELD_TABLE_REFS = (0x0065344A,)
FWWD_FIELD_TABLE_REF_OPCODES = (0x68,)
# The ObjectImageUpgrade module's registration, stock TooltipUpgrade construction/layout twin,
# field-table helpers and the two presentation-only UI interception points. Derived in
# `docs/object-image-upgrade.md`; the patch keeps instruction signatures beside the edits, while
# every engine address lives here.
OBJECT_IMAGE_UPGRADE_REGISTER_CALL = 0x0065A7F2
OBJECT_IMAGE_UPGRADE_REGISTER = 0x006570FE
OBJECT_IMAGE_UPGRADE_RUNTIME_FACTORY_STOCK = 0x006504C2
OBJECT_IMAGE_UPGRADE_MODULEDATA_CTOR = 0x0065563C
OBJECT_IMAGE_UPGRADE_SET_ASCII_CSTR = 0x0040611E
OBJECT_IMAGE_UPGRADE_REGISTER_CLEANUP = 0x0042DBBD
OBJECT_IMAGE_UPGRADE_BUILD_UPGRADE_FIELDS = 0x008D26E0
OBJECT_IMAGE_UPGRADE_APPEND_FIELD_TABLE = 0x0042B8D7
OBJECT_IMAGE_UPGRADE_UPGRADE_VTABLE = 0x00C6F820
OBJECT_IMAGE_UPGRADE_MODULEDATA_VTABLE = 0x00C09AD0
OBJECT_IMAGE_UPGRADE_FIND_IMAGE = 0x006DA34C
OBJECT_IMAGE_UPGRADE_THE_IMAGES = 0x00DE4AC0
OBJECT_IMAGE_UPGRADE_THE_CONTROL_BAR = THE_COMMAND_SET_STORE
OBJECT_IMAGE_UPGRADE_SELECT_HOOK = 0x00694F06
OBJECT_IMAGE_UPGRADE_SELECT_RESUME = 0x00694F0E
OBJECT_IMAGE_UPGRADE_SELECT_DISPLACED_CALL = 0x00694BF8
OBJECT_IMAGE_UPGRADE_BUTTON_HOOK = 0x0073D0BA
OBJECT_IMAGE_UPGRADE_BUTTON_RESUME = 0x0073D0BF
OBJECT_GET_COMMAND_SET_STRING = 0x0069156B
# `WeaponTemplate::isMeleeWeapon` - the whole function is `mov al, [ecx+0x125]; ret`. The offset is
# row 45 of the weapon field table at 0x00C16DD8, which is `MeleeWeapon`.
WEAPON_IS_MELEE = 0x00441B59
WEAPON_IS_MELEE_BYTES = bytes.fromhex("8a8125010000c3")
WEAPON_TEMPLATE_MELEE_OFFSET = 0x125
# `Weapon::isTargetObjectInRange(source, victim, extraRange, flag)` - `__thiscall` on the weapon,
# `ret 0x10`, answering in `al`. `update` calls it at 0x0089269E with `(ebp, target, 0.0f, 1)`
# and the cave copies that shape exactly.
WEAPON_TARGET_IN_RANGE = 0x006CC653
WEAPON_TARGET_IN_RANGE_BYTES = bytes.fromhex("8b54240485d27427")
# The object-scoped completed-upgrade bitset, indexed exactly like the per-player one at
# `PLAYER_COMPLETED_UPGRADE_MASK`: word `index >> 5`, bit `index & 31`. This is what
# `GrantUpgradeCreate` writes and what a porter's carried upgrades are read out of.
OBJECT_UPGRADE_MASK = 0x28C
# `Object::m_containedBy` - the horde a battalion member belongs to, and the field every
# member-versus-lone-unit test in the delivery path branches on.
OBJECT_CONTAINED_BY = 0x27C
# `Object::canAcceptUpgrade(u)`: the player must satisfy the upgrade's `RequiredObjectFilter`
# (`UpgradeTemplate+0x80`), and the object must own a module whose upgrade interface says it would
# fire on the resulting mask - `TriggeredBy` that upgrade, in ini terms. Recurses into `+0x258`,
# so asking a horde container asks its members too.
OBJECT_CAN_ACCEPT_UPGRADE = 0x00694914
# `Object::giveUpgrade(u)` and `Object::hasUpgrade(u)`, both `ret 4`.
OBJECT_GIVE_UPGRADE = 0x0069388B
OBJECT_HAS_UPGRADE = 0x00691421
# `Object::getHordeIface()`: `m_contain` then `CONTAIN_GET_HORDE_IFACE_SLOT`, NULL for anything
# that contains nothing. No arguments.
OBJECT_GET_HORDE_IFACE = 0x0068C866
# On the horde interface: `+0xAC` `anyMemberCanAccept(u)` (`0x0086ECAB`, `ret 4`) and `+0xB8`
# `giveUpgradeToMembers(u, force)` (`0x00871A90`, `ret 8`). The latter grants to the container
# unconditionally and then gates every member on `OBJECT_CAN_ACCEPT_UPGRADE` unless `force`.
HORDE_IFACE_ANY_MEMBER_ACCEPTS_SLOT = 0xAC
HORDE_IFACE_GIVE_UPGRADE_SLOT = 0xB8
# `KINDOF HORDE`, bit 109: bit 0x20 of the `KindOf` byte at `ThingTemplate+0x115`.
KINDOF_HORDE_BYTE = 0x115
KINDOF_HORDE_BIT = 0x20
# The horde-pace block, derived in `docs/horde-member-speed.md`. A battalion's speed is the
# container's `LocomotorSet` `Speed`, not its members'; `SPEED` attribute modifiers are folded in
# per object by `Locomotor::getMaxSpeed`, so a modifier on a member scales the member and never
# the pace the formation advances at.

#: `Locomotor::getMaxSpeed(Object *obj)` - `__thiscall` on the `Locomotor`, `ret 4`. Forty call
#: sites reach it, `getMaxAcceleration` (`0x005E40AD`) among them, so it is the single place a
#: locomotor speed becomes a number. The entry pins the function: the prologue, `edi` as the
#: object argument, the body-module damage-state call and the read of the AI's cached set speed.
LOCOMOTOR_GET_MAX_SPEED = 0x005E3F49
LOCOMOTOR_GET_MAX_SPEED_ENTRY = bytes.fromhex(
    "558bec51515356578b7d088bf18b8f5c0200008b01ff50248b8f60020000f30f1089f80100008b0d6443de0033db"
)
#: Its `SPEED` query, in three anchored runs so the middle one can be rewritten while the two
#: around it stay asserted. The setup pushes `flag`, `ctx`, `&out = [ebp-8]` and the type, seeds
#: the slot to 0.0 and puts the object in `ecx`; the call is the five bytes a hook replaces; the
#: fold is `test al,al` / `je` / `mulss` into the running speed at `[ebp-4]`, which is what makes
#: "nothing contributed" mean "leave the speed exactly alone".
LOCOMOTOR_SPEED_MODIFIER_SETUP = 0x005E4002
LOCOMOTOR_SPEED_MODIFIER_SETUP_BYTES = bytes.fromhex("0f57c06a01538d45f8506a088bcff30f1145f8")
LOCOMOTOR_SPEED_MODIFIER_CALL = 0x005E4015
LOCOMOTOR_SPEED_MODIFIER_CALL_BYTES = bytes.fromhex("e813880a00")
LOCOMOTOR_SPEED_MODIFIER_FOLD = 0x005E401A
LOCOMOTOR_SPEED_MODIFIER_FOLD_BYTES = bytes.fromhex("84c0740ff30f1045f8f30f5945fcf30f1145fc")
#: `SPEED`, index 8 of the attribute-modifier name table at `0x00D8AF48` (index 0 is
#: `ATTRIBUTE_NONE`). Named directly by the `push 8` in `LOCOMOTOR_SPEED_MODIFIER_SETUP`.
MODIFIER_TYPE_SPEED = 8
#: `Object+0x260` - the `AIUpdate` module, and `AIUpdate+0x1F8` the speed of the object's current
#: `LocomotorSet`. Written in exactly one place in the image, `AIUpdate::setLocomotorSet` at
#: `AI_UPDATE_SET_LOCOMOTOR_SET_SPEED_STORE`, from `THING_TEMPLATE_LOCOMOTOR_SET_SPEED`, which
#: reads the per-set `Speed` line out of the map at `ThingTemplate+0x3A0` (entry `+0x14`). So the
#: container's speed and the member's are two independent INI numbers on two independent objects.
OBJECT_AI_UPDATE = 0x260
THING_TEMPLATE_LOCOMOTOR_SET_SPEED = 0x0073DD2A
#: The contained-items list, on the `ContainModuleInterface` at `OBJECT_CONTAIN`: `+0x34` is a
#: pointer to an MSVC `std::list` sentinel node, `+0x00` of a node is the next and `+0x08` the
#: contained `Object`. A base-class property, not a `HordeContain` one - the walk below is a slot
#: in 17 contain vtables, `0x00C5B510` being `HordeContain`'s.
CONTAIN_ITEM_LIST = 0x34
CONTAIN_ITEM_LIST_NODE_OBJECT = 0x08
#: That walk, anchored for the layout it proves rather than for anything anybody rewrites: it
#: takes the sentinel, steps to the first node, stops when the two are equal, and reads
#: `[node+8]->tmpl` to test a `KindOf` on it - which is only meaningful if `+8` is an `Object`.
CONTAIN_ITEM_LIST_WALK = 0x0086620E
CONTAIN_ITEM_LIST_WALK_ENTRY = bytes.fromhex(
    "538bd98b4334568b303bf07449578b7e088b4704f6800c01000002"
)
#: The exit-all loop behind `EVACUATE` on a garrison-family contain (`TunnelContain`,
#: `HordeGarrisonContain`, the slaughter contains). `__stdcall(contain, cmdSource, arg)`, reached
#: from contain-interface slot `+0x80` through the two wrappers whose `call`s are listed below.
#: For each passenger: one with its own contain is asked for a horde interface and, if it has
#: one, the whole battalion is told to exit; one without a contain gets `aiExit` through its
#: `AIUpdate`. A passenger with a contain that is **not** a horde falls through both and is
#: skipped - which is every ring hero, whose ring pickup is a `CitadelSlaughterHordeContain`.
#: See `docs/evacuate-contained-heroes.md`.
CONTAIN_EXIT_ALL_PASSENGERS = 0x00991027
CONTAIN_EXIT_ALL_WRAPPER_CALLS = (0x0087A56A, 0x0087CEA0)
#: The loop body, `mov eax, [esi+8]` through the `jne` back to it.
CONTAIN_EXIT_ALL_LOOP = 0x0099105E
CONTAIN_EXIT_ALL_LOOP_BYTES = bytes.fromhex(
    "8b46088b885802000085c9741b8b01ff507c85c0742aff75108b10ff750c8bc8ff9284000000eb188b806002"
    "000085c0740eff75108d4820ff750ce82306deff8b363b750875b9"
)
#: `test eax, eax / je next / push [ebp+0x10]` on the horde interface just fetched - the test that
#: drops a non-horde contain-carrying passenger.
CONTAIN_EXIT_ALL_HORDE_TEST = 0x00991070
#: `mov eax, [eax+0x260]`: the `AIUpdate` arm, which expects the passenger in `eax`.
CONTAIN_EXIT_ALL_ORDER_EXIT = 0x00991086
#: `ObjectStatus HORDE_MEMBER`, bit 38 of the mask at `OBJECT_STATUS` - so bit `0x40` of the byte
#: at `Object+0x98`, by `OBJECT_TEST_STATUS`'s own encoding. `HordeContain::addToContain`
#: (`0x0086CF2A`) clears it for a `MACHINE`, `HERO` or `SIEGE_TOWER` that joins a battalion, which
#: makes it the engine's own answer to "is this one of the rank and file".
OBJECT_STATUS_HORDE_MEMBER = 38
#: Making an object and dressing it like one that no longer exists, as `RebuildHoleBehavior::onDie`
#: does (`docs/map-transition.md`). Objects are created onto a `Team`, not a `Player`.
THING_FACTORY_NEW_OBJECT = 0x006D165E
OBJECT_SET_ORIENTATION = 0x0070C31E
OBJECT_ANGLE = 0x44
OBJECT_TEAM = 0x31C
OBJECT_SCRIPT_NAME = 0x88
EXPERIENCE_LEVELS_FOR_TEMPLATE = 0x00689509
#: `Object::toArmyRecord` and its inverse `ARMY_RECORD_CREATE_OBJECT`: the `0xD8` army record, free
#: of living-world state. `ARMY_RECORD_SPAWN` is the layer that adds it.
OBJECT_TO_ARMY_RECORD = 0x0069192F
OBJECT_WRITE_ARMY_RECORD_STATE = 0x006917BB
OBJECT_APPLY_UPGRADE_LIST = 0x0068CC6C
# `LifetimeUpdate` and the mount-swap module it borrows from (`docs/lifetime-extend-upgrade.md`,
# `docs/lifetime-transform.md`).
#: `LifetimeUpdate::newModuleData`'s allocation; the cave rejoins at the `pop ecx`.
LIFETIME_ALLOC = 0x0064E096
LIFETIME_ALLOC_BYTES = bytes.fromhex("566a18e84216deff")
LIFETIME_ALLOC_RESUME = 0x0064E09E
#: `LifetimeUpdate::ModuleData`'s stock `sizeof`, which is what `LIFETIME_ALLOC` asks
#: `operator new` for and therefore the offset any added field has to start past.
LIFETIME_MODULE_DATA_SIZE = 0x18
#: `MountedTemplate`'s offset in `ToggleMountedSpecialAbilityUpdate`'s `ModuleData`, which is what
#: `TOGGLE_MOUNTED_SWAP` reads, and therefore where a transform's keyword has to land - not a
#: free choice. The three dwords behind it are that module's `SynchronizeTimerOnSpecialPower`
#: vector; zeroed, they read as empty and the swap's timer pass does nothing (see
#: `TOGGLE_MOUNTED_SYNC_SKIP`).
TOGGLE_MOUNTED_TEMPLATE = 0xD8
#: `ToggleMountedSpecialAbilityUpdate`'s own `sizeof`, which is what growing to
#: `TOGGLE_MOUNTED_TEMPLATE` plus that vector comes to. Nothing past the template is ever
#: written; it is allocated and zeroed so the vector the swap reads is an empty one rather
#: than heap litter.
TOGGLE_MOUNTED_MODULE_DATA_SIZE = 0xE8
#: The 16-byte-stride field-parse table, and the single imm32 that loads it (inside
#: `push 0xc31860` at `0x007A7E00`, so the operand starts one byte later).
LIFETIME_FIELD_TABLE = 0x00C31860
LIFETIME_FIELD_TABLE_REF = 0x007A7E01
#: The stock table in table order, as `(name, ModuleData offset)`. Used as a fingerprint before
#: anything is written: all five names *and* offsets must match, which is a far stronger build
#: check than any single literal, and the rows are copied wholesale so a mismatch would otherwise
#: rebuild the table wrong and silently.
LIFETIME_STOCK_FIELDS = (
    ("MinLifetime", 0x08),
    ("MaxLifetime", 0x0C),
    ("WaitForWakeUp", 0x10),
    ("ScoreKill", 0x11),
    ("DeathType", 0x14),
)
#: `setLifetimeRange`'s tail: the death-frame store, the `pop esi` and the `ret 8`. Seven
#: bytes, all three reproduced by the cave. `esi` is the module and `eax` the duration, which
#: is what the two call sites push as the sleep.
LIFETIME_ARM = 0x007A7DAE
LIFETIME_ARM_BYTES = bytes.fromhex("894e205ec20800")
#: `LifetimeUpdate::update`'s prologue - `push ebp` / `mov ebp,esp` / `push ecx` /
#: `push ebx`, exactly five bytes of whole instructions - and where the cave rejoins it.
LIFETIME_UPDATE = 0x007A7F8B
LIFETIME_UPDATE_BYTES = bytes.fromhex("558bec5153")
LIFETIME_UPDATE_RESUME = 0x007A7F90
#: `update`'s `ScoreKill` test and the `push esi` behind it - five bytes of two whole
#: instructions, and the last point before either scoring arm runs. `ebx` is the `ModuleData`
#: and `edi` the `Object` here, and the `THROWN_PROJECTILE` reprieve above has already been
#: taken, so a projectile in flight never reaches the transform either.
LIFETIME_EXPIRE = 0x007A7FAF
LIFETIME_EXPIRE_BYTES = bytes.fromhex("807b110056")
#: The `je` that picks a scoring arm, which is where the cave rejoins after re-executing the
#: displaced pair. It consumes the `cmp`'s flags, so the cave has to set them again.
LIFETIME_EXPIRE_RESUME = 0x007A7FB4
#: `update`'s epilogue *before* its `pop esi` - `pop edi` / `pop ebx` / `leave` / `ret`.
#: The stock `THROWN_PROJECTILE` arm returns through exactly this address from above the
#: `push esi`, which is what makes it the right exit for a hook that displaced that push.
LIFETIME_KILL_RETURN = 0x007A8038
#: `update`'s "sleep forever" - what the stock kill returns, and what a completed transform
#: returns, since in both cases the object this module belongs to is on its way out.
UPDATE_MODULE_SLEEP_FOREVER = 0x3FFFFFFF
#: `ToggleMountedSpecialAbilityUpdate`'s mount swap: `__thiscall`, no arguments, and of the
#: module it is handed it reads only `UPDATE_MODULE_DATA` and `UPDATE_MODULE_OBJECT` and writes
#: only `TOGGLE_MOUNTED_SWAP_FLAG`. It makes no virtual call on that pointer, which is what lets a
#: `LifetimeUpdate` supply a plain stack frame in place of one.
TOGGLE_MOUNTED_SWAP = 0x008B140D
#: The byte the swap sets last, after the replacement exists and everything has moved onto it. It
#: stays clear when `findTemplate` finds nothing or the build refuses, and it is the only way to
#: ask whether the transform happened.
TOGGLE_MOUNTED_SWAP_FLAG = 0x8C
#: The swap's timer pass, which walks the `SynchronizeTimerOnSpecialPower` vector at
#: `ModuleData+0xdc`. Anchored because "a zeroed vector is safe to read" is the claim that lets
#: `LifetimeUpdate`'s grown `ModuleData` stand in: it compares `+0xdc` against `+0xe0` and
#: returns when they match.
TOGGLE_MOUNTED_SYNC_SKIP = 0x008B12BF
#: The retire the mount toggle runs a step later: hide the drawable, drop the object out of the
#: UI, `GameLogic::destroyObject`. `__thiscall`, and it reads `UPDATE_MODULE_OBJECT` and nothing
#: else. A retire is not a kill - no `DeathType`, no death FX, no `SlowDeathBehavior`, nothing
#: scored.
TOGGLE_MOUNTED_RETIRE = 0x008B1E9A
#: The retire in full, `push esi` to `ret`. `esi` is the old `Object` from the second instruction
#: on and nothing reassigns it, which is what lets a hook at `TOGGLE_MOUNTED_RETIRE_DESTROY` read
#: it.
TOGGLE_MOUNTED_RETIRE_BYTES = bytes.fromhex(
    "568b71088bcee8eaa2ddff8bcee842a8ddff8bcee860c1e5ff85c074106a018bcee853c1e5ff8bc8e834fadbff"
    "a1404bde0085c074098b481056e82267e3ff8b0d2c41de0056e8c69cd7ff5ec3"
)
#: The retire's `mov ecx, [THE_GAME_LOGIC]`, six bytes, ahead of `push esi` / `call
#: GAME_LOGIC_DESTROY_OBJECT`. The `je` at `0x008B1ECE` (no UI to deselect from) lands exactly
#: here and nothing branches into the middle of it.
TOGGLE_MOUNTED_RETIRE_DESTROY = 0x008B1ED9
#: `GameLogic::destroyObject(Object *)`, `__thiscall` on `*THE_GAME_LOGIC`, `ret 4`.
GAME_LOGIC_DESTROY_OBJECT = 0x0062BBAB
#: A `BehaviorModule`'s `BehaviorModuleInterface` sub-object sits at `+0x0C` (the offset
#: `GAME_LOGIC_DESTROY_OBJECT` and the `Object` constructor's module loop both use), and slot
#: `+0x08` of that interface is `getContain`: the constructor stores its non-NULL answer at
#: `OBJECT_CONTAIN` (`0x0069A3D2`). The store is unconditional per module, so an object with two
#: contain modules - an Edain hero with a hobbit `TransportContain` and a ring
#: `CitadelSlaughterHordeContain` - keeps only the **last** one at `OBJECT_CONTAIN`.
BEHAVIOR_MODULE_INTERFACE = 0x0C
BEHAVIOR_GET_CONTAIN_SLOT = 0x08
#: `OpenContain::getContain`: a NULL-preserving `this - 0x0C + 0x20`, the module's own
#: `ContainModuleInterface` at `OPEN_CONTAIN_CONTAIN_INTERFACE` (39 interface vtables point at it,
#: `TransportContain`'s `0x00C5E130` among them). A module whose interface slot holds this address
#: is known to have `OpenContain`'s layout: `MODULE_MODULE_DATA` is an `OpenContainModuleData` and
#: the primary vtable is at `+0`.
OPEN_CONTAIN_GET_CONTAIN = 0x008A18E0
OPEN_CONTAIN_GET_CONTAIN_BYTES = bytes.fromhex("8d41f483c114f7d81bc023c1c3")
OPEN_CONTAIN_CONTAIN_INTERFACE = 0x20
#: `EjectPassengersOnDeath`'s byte in `OpenContainModuleData` (row `0x00C5A050` of the base field
#: table at `0x00C59F30`, parsed as a `Bool`). `KillPassengersOnDeath` is the next byte.
OPEN_CONTAIN_EJECT_PASSENGERS_ON_DEATH = 0x82
#: The eject arm of `OpenContain::onDie` (`0x00867120`, the die interface at module `+0x28`, so
#: `[esi-0x24]` is the `ModuleData`, `esi-0x28` the module and `esi-8` its contain interface):
#: `EjectPassengersOnDeath` set -> `processDamageToContained` when `DamagePercentToUnits > 0`,
#: then the module's `+0x64`, then the interface's `removeAllContained(false)`. What stock death
#: does with the flag, and the source of the two slots below.
OPEN_CONTAIN_ON_DIE_EJECT = 0x00867151
OPEN_CONTAIN_ON_DIE_EJECT_BYTES = bytes.fromhex(
    "80b882000000007430f30f10406c0f2f0594b5c100760b8d4ef88b01ff90480100008d4ed88b01ff5064"
    "8d4ef88b016a00ff90a8000000"
)
#: Module primary-vtable slot: kill (or, with the transport's destroy flag, silently destroy) each
#: passenger that could not walk out from where the container stands. `TransportContain`'s is
#: `0x0086B05F`, asking slot `+0x6C` per rider; `OpenContain`'s is a bare `ret`.
OPEN_CONTAIN_KILL_RIDERS_NOT_FREE_TO_EXIT_SLOT = 0x64
#: `ContainModuleInterface::removeAllContained(Bool exposeStealthUnits)`, `__thiscall`, `ret 4`.
#: `OpenContain`'s (`0x00866675`, inherited by `TransportContain`) pops the item list front until it
#: is empty, each through `removeFromContain` (`0x00865EB6`), which is a full exit: `onRemoving`,
#: the contained status cleared, and the passenger put back in the world where the container is.
CONTAIN_REMOVE_ALL_SLOT = 0xA8
#: The stack the cave hands the swap in place of a `ToggleMountedSpecialAbilityUpdate` instance:
#: that module's `sizeof`, so `TOGGLE_MOUNTED_SWAP_FLAG` lands inside it. Only three slots
#: are ever touched - the two pointers and the flag - so the rest is left as whatever the
#: stack held.
TOGGLE_MOUNTED_INSTANCE_SIZE = 0x90
#: The health hand-over in the mount swap and in its dismount sibling, which are byte-identical
#: here: load both bodies (`esi` the new object, `edi` the old), keep the new body at `[ebp-0x14]`
#: and its vtable in `ebx`, then `new->setHealth(old->getHealth())` through body slot `+0xac` - a
#: raw store to `+0x08` with no clamp and no ratio. Absolute health therefore crosses between
#: templates with different `MaxHealth` unchanged. The experience copy just before it has already
#: run the new object's level-ups, so the new body's maximum includes its rank bonus by now.
TOGGLE_MOUNTED_MOUNT_HEALTH_COPY = 0x008B14F0
TOGGLE_MOUNTED_DISMOUNT_HEALTH_COPY = 0x008B236F
TOGGLE_MOUNTED_HEALTH_COPY_SEQUENCE = bytes.fromhex(
    "8b865c0200008b8f5c0200008b188945ec8b01ff5010518b4decd91c24ff93ac000000"
)
#: `mov eax, [ecx]` / `call [eax+0x10]` - the `getHealth` call on the old body, five bytes of two
#: whole instructions at this offset into the sequence. Nothing in the image branches into it.
TOGGLE_MOUNTED_HEALTH_COPY_HOOK = 0x11
#: The constructor's `mov byte [esi+0x28], al` with `eax` already zero, widened to a dword so
#: it clears the edge latch in the instance's tail padding as well. One byte changed, three for
#: three: the stores that follow it are untouched and `sizeof` does not move.
LIFETIME_LATCH_DEFAULT = 0x007A7F04
LIFETIME_LATCH_DEFAULT_BYTES = bytes.fromhex("884628")
#: The module instance, as `update` and `setLifetimeRange` address it. `update` runs on the
#: `UpdateModule` subobject at `module+0x10`, which is why it reads the others as negative
#: displacements - and why the cave's own reads are `0x10` lower than these.
UPDATE_MODULE_DATA = 0x04
UPDATE_MODULE_OBJECT = 0x08
UPDATE_MODULE_THIS_DELTA = 0x10
LIFETIME_DIE_FRAME = 0x20
LIFETIME_START_FRAME = 0x24
#: `Object::getControllingPlayer()` - `__thiscall(ecx = Object*) -> Player*`, NULL for an
#: unowned object. It is `mov ecx,[this+0x31c] / jmp Team::getControllingPlayer`, which is what
#: pins `Object+0x31c` as the team and therefore the object's mask as the one ending before it.
OBJECT_GET_CONTROLLING_PLAYER = 0x0068B678
#: `GameLogic`'s sleepy-update driver, the one site that calls an `UpdateModule`'s `update`. It
#: reads `lea ecx,[module+0x10]`, takes the return as a **sleep in frames** (clamped to a minimum
#: of 1) and stores `now + sleep` into the module's wake frame at `+0x14`. Both hooks depend on
#: all three of those, and none of them is checkable from `LifetimeUpdate` alone.
SLEEPY_UPDATE_DISPATCH = 0x0062EA97
#: The client's timer-widget source: it finds the `LifetimeUpdate` module by class name, skips it
#: while the `WaitForWakeUp` byte at `+0x28` is set, and otherwise reads the death frame and the
#: start frame straight off the instance...
LIFETIME_UI_MODULE_READ = 0x0092F7C5
#: ... and turns them into the bar's fill, `(die - now) / (die - start)`, every frame. The patch
#: writes nothing here; it is anchored because "the in-world timer follows the extension" is a
#: claim about *this* code, and a build that computed the fill from the template's `MaxLifetime`
#: instead would leave the bar stuck while the object lived on.
LIFETIME_UI_FRACTION = 0x0092F8C8
#: Byte windows the patch depends on and does not rewrite. The register anchors matter most: the
#: cave reads `esi` as the module in `setLifetimeRange` and `[ecx-0xc]`/`[ecx-8]` as the
#: `ModuleData`/`Object` in `update`, and nothing the patch writes would catch a build that
#: allocated them differently - the cave would simply dereference whatever the registers held.
LIFETIME_ANCHORS: dict[int, bytes] = {
    # `setLifetimeRange`'s prologue: esi = the module, and the two duration arguments
    0x007A7D7E: bytes.fromhex("566a7668e017c300ff7424148bf1ff742414"),
    # ... and its tail up to the hook: the duration clamp, TheGameLogic's frame, m_startFrame
    0x007A7D98: bytes.fromhex("83f801730333c0408b0d2c41de008b4940894e2403c8"),
    # the ModuleData constructor, in full: the five stock fields, and no sixth
    0x007A7E0B: bytes.fromhex("8bc133c9c700307ac00089480889480c884810884811894814c3"),
    # `setLifetimeRangeAndWake`: the call, and the `push eax` handing the return to setWakeFrame
    0x007A7E4C: bytes.fromhex("e82dffffff50ff76088bcee8d68d0a005ec2"),
    # `wakeUp`, which clears the WaitForWakeUp byte at +0x28 with a *byte* store - the reason the
    # latch at +0x29 is the module's own and nothing else writes it
    0x007A7E6F: bytes.fromhex("817c2404ffffff3f740cc641180083c1f0e8dbffffff"),
    # the two stores that follow the widened one, and `eax` being zero across all three
    0x007A7F02: bytes.fromhex("33c0"),
    0x007A7F07: bytes.fromhex("894620894624"),
    # ... and the WaitForWakeUp latch, written as a byte after the zeroing
    0x007A7F27: bytes.fromhex("8a481080f901884e28"),
    # the constructor's arming path, which hands setLifetimeRange's return to setWakeFrame
    0x007A7F6A: bytes.fromhex("e80ffeffff50ff76088bcee8b88c0a00"),
    # `update` past the prologue: ebx = [ecx-0xc], edi = [ecx-8], then the THROWN_PROJECTILE gate
    # whose `return 1` is the idiom the poll reuses
    LIFETIME_UPDATE_RESUME: bytes.fromhex("8b59f4578b79f8689a0000008bcfe87569ccff84c07408"),
    # ... and the arm that gate takes: `return 1` through LIFETIME_KILL_RETURN, from above the
    # `push esi`. The transform's exit is this one, so a build that returned through the pop
    # instead would be refused rather than unbalancing the stack
    0x007A7FA7: bytes.fromhex("33c040e989000000"),
    # the `je` the displaced pair falls into, so the cave rejoins a branch that is still there
    LIFETIME_EXPIRE_RESUME: bytes.fromhex("743b8db75c020000"),
    # the sleep-forever the stock kill returns, and the epilogue behind it: `pop esi` is *last*
    # in, so LIFETIME_KILL_RETURN is the entry for a path that never pushed it
    0x007A8032: bytes.fromhex("b8ffffff3f5e5f5bc9c3"),
    # the mount swap from its entry: the frame it sets up, ModuleData at +4, the template at
    # +0xd8, findTemplate, the null exit that leaves the flag clear, and the Object at +8. Every
    # offset the scratch has to satisfy, and the entry the cave calls
    TOGGLE_MOUNTED_SWAP: bytes.fromhex(
        "b8a82bba00e8d9ba180081ecd40000005356578bf98b47048b0d404ade0005d8000000"
        "50897de8e8ccfee1ff85c08945ec0f843d0200008b7f088bcfe8c5cbe5ff"
    ),
    # ... and its tail: the success flag at +0x8c, then the register restores that make the swap
    # safe to call with `ebx` and `edi` still holding the caller's ModuleData and Object
    0x008B167A: bytes.fromhex("c6838c000000018b4df45f5e64890d000000005b"),
    # the timer pass: `+0xdc` against `+0xe0`, and the jump taken when they match - which is what
    # makes a zeroed vector in the grown ModuleData an empty one rather than a fault
    TOGGLE_MOUNTED_SYNC_SKIP: bytes.fromhex("558bec5151538b59048d83dc0000008b103b500456570f848200"),
    # the retire, reading the Object off +8 and nothing else off the pointer it is given
    TOGGLE_MOUNTED_RETIRE: bytes.fromhex("568b71088bcee8eaa2ddff8bcee842a8ddff8bcee860c1e5"),
    # `AsciiString::isEmpty` in full: NULL buffer or zero length -> 1, and `eax` is all it touches
    ASCII_STRING_IS_EMPTY: bytes.fromhex("8b0185c0740a6683780400740333c0c333c040c3"),
    # `MountedTemplate`'s row and the `SynchronizeTimerOnSpecialPower` row behind it, verbatim:
    # the parse function the transform's row copies and the two offsets the grown ModuleData has
    # to reproduce, read from the engine's own table rather than asserted
    0x00C05A48: bytes.fromhex("b859c0005eee420000000000d80000009859c000d6ee420000000000dc000000"),
    # `newModuleData`'s ctor call and the null test the cave's zeroing has to respect
    0x0064E09E: bytes.fromhex("598bc8894df08365fc0085c97409e85a9d1500"),
    # `UpgradeMaskType::any()` - the 36-dword scan, ecx = the mask, no arguments
    UPGRADE_MASK_ANY: bytes.fromhex("33c0833c810075094083f82472f432c0c3b001c3"),
    # `testForAny` - the same width, one stack argument, `ret 4`
    UPGRADE_MASK_TEST_ANY: bytes.fromhex(
        "8b44240433d22bc1568b34088531750f4283c10483fa2472f032c05ec20400"
    ),
    # `Object::getControllingPlayer` - the team hop that pins Object+0x31c
    OBJECT_GET_CONTROLLING_PLAYER: bytes.fromhex("8b891c03000085c97405e9e846110033c0c3"),
    # `UpdateModule::setWakeFrame`: `frame = TheGameLogic->frame + delta`, which is what makes the
    # value the arming hook returns a sleep rather than a frame
    0x00850C32: bytes.fromhex("a12c41de008b5040035424085251ff74240c8bc8"),
    # the sleepy-update driver, the whole contract both hooks rely on: `update` is called on the
    # `module+0x10` interface, its return is a delta clamped to a minimum of 1, and the next wake
    # is recomputed as `now + delta` at the moment of the call - so a poll of 1 is every frame and
    # cannot drift
    SLEEPY_UPDATE_DISPATCH: bytes.fromhex(
        "8d4b108b01ff1083f8018945ec7d07c745ec0100000083a60401000000"
        "a12c41de008b40408b4dec03c1b9ffffff3f3bc10f47c1894314"
    ),
    # `INI::parseUpgradeMask`'s entry, and the ms -> frames duration parser: the two functions the
    # appended rows name, so a build where either moved is refused rather than mis-parsed
    INI_PARSE_UPGRADE_MASK: bytes.fromhex("b86375b800e8e3d83c0083ec1453565768900000"),
    INI_PARSE_DURATION: bytes.fromhex(
        "558bec518b4d086a00e86838cfff8b4d0850e80246cfff85c08945fcdb45"
    ),
    # the client's timer widget: the module lookup, the WaitForWakeUp skip, and the two loads that
    # make the bar follow the death frame this patch moves
    LIFETIME_UI_MODULE_READ: bytes.fromhex(
        "8b7d0cff35e0a3de008bcfe8d0c5d5ff3bc6741480782800750e895de08b50248b4820e9db000000"
    ),
    # ... and the fill itself: remaining / span, both derived from the live module every frame
    LIFETIME_UI_FRACTION: bytes.fromhex(
        "3bca0f869f000000a12c41de008b40408bf12bf085f68975ecdb45ec7d06d8059886bd00"
        "8bf12bf285f68975ecdb45ec7d06d8059886bd003bc1def9d95de877"
    ),
}
# Semantic name for the confirmed float XP path; original EA name is unknown.
EXPERIENCE_TRACKER_ADD_EXPERIENCE_POINTS = 0x0079D833
# Derived in `docs/passive-aura-revive.md`. `PassiveAreaEffectBehavior` parks its update at the
# sleep-forever sentinel the first time it ticks on a dead object, and nothing wakes an update
# module when an object is revived - so an aura on a structure that survives death as rubble is
# gone for the rest of the game once the structure is rebuilt.

#: `PassiveAreaEffectBehavior::update` - slot 0 of the module's `UpdateModule` sub-object, whose
#: vtable is `PASSIVE_AREA_EFFECT_UPDATE_VTABLE`. `this` is the sub-object at module `+0x10`,
#: so `[this-0xc]` is the `ModuleData` and `[this-0x8]` the `Object`.
PASSIVE_AREA_EFFECT_UPDATE = 0x00887DF7
#: The `UpdateModule` vtable `PassiveAreaEffectBehavior`'s constructor stores at module `+0x10`
#: (`0x00887D2E`, `mov dword [esi+0x10], 0xC60C28`). Three slots; the first is the update above.
PASSIVE_AREA_EFFECT_UPDATE_VTABLE = 0x00C60C28
#: The class's `getModuleName` (`0x00887D63`, `mov eax, 0xC0AD50 ; ret`) returns this, so the
#: string is what ties every address in this block to `PassiveAreaEffectBehavior` by name rather
#: than by position.
PASSIVE_AREA_EFFECT_MODULE_NAME_STRING = 0x00C0AD50
#: `test byte [ebx+0x458], 1 ; je 0x00887E76` - the update's "is my own object effectively dead"
#: test and the branch that skips it. `ebx` is the `Object`; bit 0 of `+0x458` is the flag
#: `Object::setEffectivelyDead` (`0x0068D950`) writes. Falls straight through into
#: `PASSIVE_AREA_EFFECT_DEAD_SLEEP`, which is what makes that site the dead arm and not
#: some other return.
PASSIVE_AREA_EFFECT_DEAD_TEST = 0x00887E5B
#: The dead arm's `mov eax, 0x3FFFFFFF` - `UPDATE_SLEEP_FOREVER`, returned through the `jmp` two
#: bytes on. This is the whole bug and the whole patch: five bytes that decide whether the module
#: is ever scheduled again.
PASSIVE_AREA_EFFECT_DEAD_SLEEP = 0x00887E64
PASSIVE_AREA_EFFECT_DEAD_SLEEP_BYTES = bytes.fromhex("b8ffffff3f")
#: Where the update keeps the sleep it returns on every other path: a scratch dword in the frame,
#: written from `ModuleData+0x10` (`PingDelay`, floored at 1) at `0x00887E09` and read back by the
#: normal return at `0x00887EBE`. The five pushes in the prologue are still on the stack at
#: `PASSIVE_AREA_EFFECT_DEAD_SLEEP` and every call in between is callee-balanced, so the
#: same `[esp+0x10]` names the same slot there.
PASSIVE_AREA_EFFECT_PING_SLOT_OFFSET = 0x10
#: The gate keeping `PassiveAreaEffectBehavior` quiet while its object is built, which
#: `passive-aura-revive` transcribes for `AttributeModifierAuraUpdate`.
PASSIVE_AREA_EFFECT_CONSTRUCTION_GATE = 0x00887E45
PASSIVE_AREA_EFFECT_CONSTRUCTION_GATE_BYTES = bytes.fromhex(
    "8bcbe89a45e0ff85c0741b8b108bc8ff522c84c0"
)
#: The other arm of the gate above, for an object with no `GettingBuiltBehavior` at all:
#: `push 2 ; mov ecx, ebx ; call OBJECT_TEST_STATUS ; jmp back to the test`. `2` is
#: `OBJECT_STATUS_UNDER_CONSTRUCTION`.
PASSIVE_AREA_EFFECT_CONSTRUCTION_FALLBACK = 0x00887E6B
PASSIVE_AREA_EFFECT_CONSTRUCTION_FALLBACK_BYTES = bytes.fromhex("6a028bcbe8785fbcffebe1")
#: Everything the patch reads and does not rewrite. The vtable slot and the module-name string
#: identify the function; the `PingDelay` read and the normal return frame the scratch slot; the
#: dead test abuts the rewritten instruction; the construction gate is the routine the cave
#: transcribes for the sibling module.
PASSIVE_AREA_EFFECT_ANCHORS: dict[int, bytes] = {
    # `mov dword [esi+0x10], 0xC60C28` in the constructor: this vtable is this module's.
    0x00887D2E: bytes.fromhex("c74610280cc600"),
    # `getModuleName`: `mov eax, 0xC0AD50 ; ret`.
    0x00887D63: bytes.fromhex("b850adc000c3"),
    # `mov eax, [edi+0x10]` (`PingDelay`) / `test eax, eax` / `mov [esp+0x10], eax`.
    0x00887E04: bytes.fromhex("8b471085c089442410"),
    PASSIVE_AREA_EFFECT_DEAD_TEST: bytes.fromhex("f68358040000017412"),
    PASSIVE_AREA_EFFECT_CONSTRUCTION_GATE: PASSIVE_AREA_EFFECT_CONSTRUCTION_GATE_BYTES,
    PASSIVE_AREA_EFFECT_CONSTRUCTION_FALLBACK: PASSIVE_AREA_EFFECT_CONSTRUCTION_FALLBACK_BYTES,
    # The normal return: `mov eax, [esp+0x10]` then the five pops matching the prologue, and `ret`.
    0x00887EBE: bytes.fromhex("8b4424105f5e5d5b59c3"),
    # Slot 0 of the update vtable is the function above.
    PASSIVE_AREA_EFFECT_UPDATE_VTABLE: PASSIVE_AREA_EFFECT_UPDATE.to_bytes(4, "little"),
    PASSIVE_AREA_EFFECT_MODULE_NAME_STRING: b"PassiveAreaEffectBehavior\x00",
}
# Derived in `docs/passive-aura-revive.md` §8.2. `AttributeModifierAuraUpdate` carries the same
# defect as `PassiveAreaEffectBehavior` above, in a shape that needs a cave rather than a five-byte
# rewrite: its sleep-forever sentinel is shared with the module's designed idle state - an aura
# still waiting on its `TriggeredBy` upgrade - so the dead arm has to be split off from it.

#: `AttributeModifierAuraUpdate::update` - slot 0 of the module's `UpdateModule` sub-object, whose
#: vtable is `ATTRIBUTE_MODIFIER_AURA_UPDATE_VTABLE`. Same `this-0x10` layout as the passive
#: module: `[this-0xc]` is the `ModuleData` and `[this-0x8]` the `Object`, loaded into `edi` and
#: `esi` at `0x0089F449` and `0x0089F43C`.
ATTRIBUTE_MODIFIER_AURA_UPDATE = 0x0089F42D
#: The `UpdateModule` vtable the constructor stores at module `+0x10` (`0x0089ED9B`,
#: `mov dword [esi+0x10], 0xC67598`). Slot 0 is the update above.
ATTRIBUTE_MODIFIER_AURA_UPDATE_VTABLE = 0x00C67598
#: What the class's `getModuleName` (`0x0089EDD2`, `mov eax, 0xC0B290 ; ret`) returns - the string
#: that ties every address in this block to `AttributeModifierAuraUpdate` by name, not by position.
ATTRIBUTE_MODIFIER_AURA_MODULE_NAME_STRING = 0x00C0B290
#: The 24-byte gate block the patch rewrites: the dead test and `RunWhileDead`.
ATTRIBUTE_MODIFIER_AURA_GATES = 0x0089F441
ATTRIBUTE_MODIFIER_AURA_GATES_BYTES = bytes.fromhex(
    "f6865804000001578b79f4894dec7408389f6a010000741b"
)
#: `RunWhileDead` on the `ModuleData` - `Bool`, default `No`. Confirmed against the recovered field
#: table for the block as well as against the compare above.
ATTRIBUTE_MODIFIER_AURA_RUN_WHILE_DEAD_OFFSET = 0x16A
#: Bit 0 of `Object+0x458`, the effectively-dead flag `Object::setEffectivelyDead` (`0x0068D950`)
#: writes and both aura updates test. `ActiveBody::internalChangeHealth` (`0x008C31A5`) rewrites it
#: on every health change from `health <= 0` (`0x008C32B1`), so it clears on the **first** frame a
#: rubble structure repairs above zero - which is why resuming on it alone would restart an aura at
#: the start of a rebuild rather than at its end.
OBJECT_EFFECTIVELY_DEAD_FLAG = 0x458
#: Where the gate falls through for `RunWhileDead = Yes`. `ecx` must still be `this` here: reload it
#: from `ATTRIBUTE_MODIFIER_AURA_THIS_EBP_OFFSET` after any call.
ATTRIBUTE_MODIFIER_AURA_SCAN = 0x0089F459
#: The update's own scratch slot for `this`, written by the displaced `mov [ebp-0x14], ecx` at
#: `0x0089F44C` and read back by the stock code at `0x0089F4A0`. It is what makes `ecx` recoverable
#: after a call, and the frame pointer it hangs off is set up by the `__EH_prolog` at `0x0089F432`,
#: so it is live for the whole body.
ATTRIBUTE_MODIFIER_AURA_THIS_EBP_OFFSET = -0x14
#: `UPDATE_SLEEP_FOREVER`, left stock: an aura waiting for its `TriggeredBy` upgrade also sleeps
#: here, correctly, until the upgrade wakes it.
ATTRIBUTE_MODIFIER_AURA_DEAD_SLEEP = 0x0089F474
ATTRIBUTE_MODIFIER_AURA_DEAD_SLEEP_BYTES = bytes.fromhex("b8ffffff3f")
#: The sleep every ordinary path returns, computed at the exit rather than stashed in a slot the
#: way `PassiveAreaEffectBehavior` does it: `RefreshDelay` (`ModuleData+0x18`) plus the object's id
#: modulo five, a stagger so that not every aura in a game scans on the same frame. The cave jumps
#: here, and falls straight into the epilogue two instructions on.
ATTRIBUTE_MODIFIER_AURA_NORMAL_SLEEP = 0x0089F6BD
#: `Object::getGettingBuiltBehavior` - walks `Object+0x24C` and returns the first module whose
#: behaviour interface answers `[iface+0x80]` with a non-NULL `GettingBuiltBehaviorInterface`, or
#: NULL. `__thiscall`, no arguments, and it saves `esi`.
OBJECT_GET_GETTING_BUILT_BEHAVIOR = 0x0068C3E6
OBJECT_GET_GETTING_BUILT_BEHAVIOR_ENTRY = bytes.fromhex("568bb14c020000")
#: Everything the aura half of the patch reads and does not rewrite. The vtable slot and the
#: module-name string identify the function; the dead test abuts the rewritten gate; the sentinel
#: and the sleep computation are the two exits the cave has to keep telling apart.
ATTRIBUTE_MODIFIER_AURA_ANCHORS: dict[int, bytes] = {
    # `mov dword [esi+0x10], 0xC67598` in the constructor: this vtable is this module's.
    0x0089ED9B: bytes.fromhex("c746109875c600"),
    # `getModuleName`: `mov eax, 0xC0B290 ; ret`.
    0x0089EDD2: bytes.fromhex("b890b2c000c3"),
    # `mov eax, [esi+0x11c]` - the gate the cave hands `RunWhileDead = Yes` back to.
    ATTRIBUTE_MODIFIER_AURA_SCAN: bytes.fromhex("8b861c010000"),
    # The sentinel the un-triggered arm still needs, which is why the patch does not touch it.
    ATTRIBUTE_MODIFIER_AURA_DEAD_SLEEP: ATTRIBUTE_MODIFIER_AURA_DEAD_SLEEP_BYTES,
    # `mov eax, [esi+0x74]` / `cdq` / `push 5` / `pop ecx` / `idiv ecx` / `mov eax, edx` /
    # `add eax, [edi+0x18]` - the ordinary sleep, which is what the cave jumps to.
    ATTRIBUTE_MODIFIER_AURA_NORMAL_SLEEP: bytes.fromhex("8b4674996a0559f7f98bc2034718"),
    # Slot 0 of the update vtable is the function above.
    ATTRIBUTE_MODIFIER_AURA_UPDATE_VTABLE: ATTRIBUTE_MODIFIER_AURA_UPDATE.to_bytes(4, "little"),
    ATTRIBUTE_MODIFIER_AURA_MODULE_NAME_STRING: b"AttributeModifierAuraUpdate\x00",
    # The two routines the cave calls, so a build that moved either fails here rather than on a
    # wild call: the module-array walk and the status test its empty-handed arm falls back to.
    OBJECT_GET_GETTING_BUILT_BEHAVIOR: OBJECT_GET_GETTING_BUILT_BEHAVIOR_ENTRY,
    OBJECT_TEST_STATUS: bytes.fromhex("8b54240433c0568bf140"),
}
# Derived in `docs/contained-horde-respawn.md`. `AutoHealBehavior::update` is an if/else chain over
# four `ModuleData` flags, and `RespawnNearbyHordeMembers` is read in exactly one of the four arms
# - the radius scan. `AffectsContained` is the arm above it and returns before reaching it, so in
# the stock engine the two fields are mutually exclusive and a garrison can be healed or a horde
# replenished but never both.

#: `AutoHealBehavior::update`: `this` is the `UpdateModule` sub-object at module `+0x10`.
AUTO_HEAL_UPDATE = 0x008558C0
#: The `UpdateModule` vtable the constructor stores at module `+0x10` (`0x00855673`,
#: `mov dword [esi+0x10], 0xC564F8`). Slot 0 is the update above.
AUTO_HEAL_UPDATE_VTABLE = 0x00C564F8
#: What the class's `getModuleName` (`0x00855415`, `mov eax, 0xC0BED4 ; ret`) returns - the string
#: that ties every address in this block to `AutoHealBehavior` by name rather than by position.
AUTO_HEAL_MODULE_NAME_STRING = 0x00C0BED4
#: `ModuleData` offsets, each read at exactly one site in the image. `AffectsContained` at
#: `0x00855A25` selects the arm this patch extends; the three respawn fields are read only inside
#: the radius arm, at `0x00855D1C`, `0x00855D85` and `0x00855B04`. `RespawnMinimumDelay` is an
#: `Int` of raw frames, not a `Duration`.
AUTO_HEAL_AFFECTS_CONTAINED = 0x14D
AUTO_HEAL_RESPAWN_NEARBY_HORDE_MEMBERS = 0x175
AUTO_HEAL_RESPAWN_FX_LIST = 0x178
AUTO_HEAL_RESPAWN_MINIMUM_DELAY = 0x17C
#: `[ebp-0x20]`, written once at `0x008558F2` from `lea eax, [ecx-0x10]` and never again: the
#: module base, which is also the `this` `AutoHealBehavior::healObject` (`0x00855761`) is called on
#: throughout the function. The update's own `[ebp-0x18]` holds the same pointer plus `0x10` at the
#: top of the function but is **reused as a list head** by the `AffectsContained` and
#: `AffectsWholePlayer` arms, so a cave entered from either of those has to go through this slot.
AUTO_HEAL_MODULE_BASE_SLOT = 0x20
#: `[ebp-0x04]`, the MSVC `__EH_prolog` scope index (the prologue is `0x008558C0`'s
#: `mov eax, 0xB9E267 ; call 0x00A3CEF0`, and the epilogue restores `fs:[0]` from `[ebp-0xc]`).
#: The `AffectsContained` arm sets it to `1` when it builds its list at `0x00855A6A` and, unlike
#: the radius arm at `0x00855DC1`, never resets it after destroying that list.
AUTO_HEAL_SCOPE_INDEX_SLOT = 0x04
#: Module base `+0x34` - the frame the last respawn was stamped at. Zeroed by the constructor
#: (`0x0085568D`, `and dword [esi+0x34], 0`), compared against `RespawnMinimumDelay` at
#: `0x00855B15` and written at `0x00855DBE`, both of which reach it as `+0x24` off the
#: `UpdateModule` sub-object.
AUTO_HEAL_LAST_RESPAWN_FRAME = 0x34
#: The `AffectsContained` arm's own `iterateContained` call, twenty-six bytes ending three
#: instructions before the hook. It is where the callback ABI comes from: `push 1` / `push
#: userData` / `push func` with `ecx` the interface and the slot at
#: `CONTAIN_ITERATE_SLOT`, callee-cleaned, and `func` (`0x0085584B`) ends in a plain `ret`.
#: It is also the arm's `mov [ebp-4], 1`, the scope index the cave has to clear.
AUTO_HEAL_CONTAINED_ITERATE = 0x00855A64
#: The end of the `AffectsContained` arm: a `jmp` to `AUTO_HEAL_UPDATE_TAIL`, five bytes with
#: nothing else in them, which is the whole hook site. `ebx` still holds the `ModuleData` and `edi`
#: the `ContainModuleInterface` the arm selected - either the object's own (`0x00855A32`) or, for a
#: module on a passenger, the one containing it (`0x00855A4A`).
AUTO_HEAL_CONTAINED_EXIT = 0x00855AC1
AUTO_HEAL_CONTAINED_EXIT_BYTES = bytes.fromhex("e907030000")
#: Where every arm but `AffectsWholePlayer` converges: `SingleBurst` decides between
#: `UPDATE_SLEEP_FOREVER` and `HealingDelay`, both read off `ebx`. The cave returns here, so the
#: sleep the module asks for is unchanged.
AUTO_HEAL_UPDATE_TAIL = 0x00855DCD
#: The stock respawn, inside the radius arm's per-object loop and reachable from nowhere else. The
#: cave transcribes it: `KindOf HORDE` on the found object, not `UNDER_CONSTRUCTION`, a non-NULL
#: horde interface, live members below the contain's `Slots`, then the spawn slot and the effect
#: list. Anchored in full because it is what the cave claims to reproduce.
AUTO_HEAL_RESPAWN_BLOCK = 0x00855D16
#: The helper the stock respawn calls on a new member. What it unlinks is not established; the cave
#: calls it because the stock respawn does.
AUTO_HEAL_RESPAWN_MEMBER_FIXUP = 0x0068C7E9
#: `__cdecl(FXList *fx, Object *at, void *unused)` - the null-and-empty-safe wrapper every caller
#: plays an `FXList` on an object through. Returns without doing anything for a NULL `fx`, so a
#: `RespawnFXList` left out of the INI costs a compare.
FX_LIST_PLAY_AT_OBJECT = 0x004B1B5A
#: `ContainModuleInterface::iterateContained(func, userData, Bool)`, a vtable slot on the interface
#: at `OBJECT_CONTAIN`. `__thiscall`, callee-cleaned, and `func` is `__cdecl(Object *,
#: void *)` returning nothing - the shape of `0x0085584B`, the callback the `AffectsContained` arm
#: hands it at `0x00855A78`. Preferred over walking `CONTAIN_ITEM_LIST` by hand when the
#: concrete contain type is whatever the object happened to have.
CONTAIN_ITERATE_SLOT = 0x110
#: Three more slots on the horde interface `OBJECT_GET_HORDE_IFACE` returns, all `__thiscall`
#: with no arguments except the last. `+0x17C` (`0x0086C8DE`) is the contain's `Slots` field, `0` if
#: the module data is missing; `+0x188` (`0x0086C09B`) is the live member count; `+0x18C`
#: (`0x00873AE3`, `ret 4`) creates one member at a `Matrix3D *` and returns it, which is the banner
#: carrier's own respawn.
HORDE_IFACE_MAX_MEMBERS_SLOT = 0x17C
HORDE_IFACE_MEMBER_COUNT_SLOT = 0x188
HORDE_IFACE_RESPAWN_MEMBER_SLOT = 0x18C
#: `Object`'s `Matrix3D`, three rows of four floats at `+0x08`. What the respawn slot above takes,
#: and what the stock respawn passes it with `add esi, 8` at `0x00855D6E`.
OBJECT_TRANSFORM = 0x08
#: Everything the patch reads but does not rewrite, asserted so the function is identified.
AUTO_HEAL_ANCHORS: dict[int, bytes] = {
    # `mov dword [esi+0x10], 0xC564F8` in the constructor: this vtable is this module's.
    0x00855673: bytes.fromhex("c74610f864c500"),
    # `getModuleName`: `mov eax, 0xC0BED4 ; ret`.
    0x00855415: bytes.fromhex("b8d4bec000c3"),
    # The prologue: `push ebx` / `mov ebx, [ecx-0xc]` / `lea eax, [ecx-0x10]` / `push esi` /
    # `mov esi, [ecx-8]` / `lea ecx, [eax+0x20]` / `mov [ebp-0x20], eax` / the upgrade gate call.
    0x008558E4: bytes.fromhex("538b59f48d41f0568b71f88d48208945e08b01ff10"),
    # `cmp byte [ebx+0x14d], 0` / `je 0x00855AC6` - the arm the cave extends, and the only read of
    # `AffectsContained` in the image.
    0x00855A25: bytes.fromhex("80bb4d010000000f8494000000"),
    # The contain fetch: `[esi+0x258]`, else `[esi+0x27c]`'s `[+0x258]`, else straight to the tail.
    # This is `edi`'s last write before the hook.
    0x00855A32: bytes.fromhex(
        "8bbe5802000085ff751c8bb67c02000085f60f84830300008bbe5802000085ff0f8475030000"
    ),
    # The arm's own `iterateContained` call: the slot, the argument order and the scope index the
    # cave clears, all in one window.
    AUTO_HEAL_CONTAINED_ITERATE: bytes.fromhex(
        "8b1733c040508945fc8d45e850684b5885008bcfff9210010000"
    ),
    # `lea ecx, [ebp-0x18]` / `call 0x005EAEA2` - the list destructor, which ends where the hook
    # begins. The second of the two calls `edi` has to survive, both callee-saved `__thiscall`.
    0x00855AB9: bytes.fromhex("8d4de8e8e153d9ff"),
    # The radius arm's respawn-delay gate: `RespawnMinimumDelay` plus the module's `+0x24` (module
    # base `+0x34`) against `TheGameLogic`'s frame, into `[ebp-0xd]`.
    0x00855B04: bytes.fromhex("8b8b7c0100008b55e8a12c41de008b4040034a24897dc43bc11ac0fec08845f3"),
    # The whole stock respawn block, which the cave transcribes.
    AUTO_HEAL_RESPAWN_BLOCK: bytes.fromhex(
        "807df300747e80bb750100000074758b4604f680150100002074696a028bcee8b280bfff84c0755c8bcee821"
        "6be3ff3bc78945ec744e8b108bc8ff927c0100008b4dec8945dc8b01ff90880100003b45dc73318b4dec8b01"
        "83c60856ff908c0100008bf03bf7741c8bcee8646ae3ff8b83780100003bc7740b575650e8c3bdc5ff83c40c"
    ),
    # The write-back: if the gate was open, stamp `TheGameLogic`'s frame into the module.
    0x00855DAD: bytes.fromhex("807df300740ea12c41de008b40408b4de8894124"),
    # The shared tail the cave returns to.
    AUTO_HEAL_UPDATE_TAIL: bytes.fromhex("80bb3a01000000b8ffffff3f750d8b8340010000eb05b8ffffff3f"),
    # The four routines the cave calls, at their entries.
    OBJECT_TEST_STATUS: bytes.fromhex("8b54240433c0568bf140"),
    OBJECT_GET_HORDE_IFACE: bytes.fromhex("8b895802000085c97503"),
    AUTO_HEAL_RESPAWN_MEMBER_FIXUP: bytes.fromhex("568bf18b46688b40048d"),
    FX_LIST_PLAY_AT_OBJECT: bytes.fromhex("558bec837d0800741a"),
    # Slot 0 of the update vtable is the function above.
    AUTO_HEAL_UPDATE_VTABLE: AUTO_HEAL_UPDATE.to_bytes(4, "little"),
    AUTO_HEAL_MODULE_NAME_STRING: b"AutoHealBehavior\x00",
}
#: `Object+0x25C` - the object's `BodyModule`, and the three getter slots on its vtable that the
#: construction arithmetic reads. `+0x10` is `getHealth`, `+0x14` `getHealthRatio` (health over
#: maximum, so `[0, 1]`) and `+0x1C` `getMaxHealth`; all three are `__thiscall`, take no argument
#: and return in `st(0)`. The fourth slot the same code uses,
#: `ACTIVE_BODY_INTERNAL_CHANGE_HEALTH_SLOT`, is `+0x84`.
OBJECT_BODY_MODULE = 0x25C
BODY_GET_HEALTH_SLOT = 0x10
BODY_GET_HEALTH_RATIO_SLOT = 0x14
BODY_GET_MAX_HEALTH_SLOT = 0x1C
#: `Object+0x288` - the construction percent, `0` to `100`, or `-1.0` for "not being built".
OBJECT_CONSTRUCTION_PERCENT = 0x288
#: `GettingBuiltBehavior::update`'s self-build heal, the path taken when no builder is driving the
#: structure: `call [eax+0x1C]` (`getMaxHealth`) then `fild [esi+0x1C]` (`RebuildTimeSeconds` as a
#: frame count), divided one into the other at `0x00857FD4` to give the per-frame amount.
SELF_BUILD_HEAL_STEP = 0x00857FC1
SELF_BUILD_HEAL_STEP_BYTES = bytes.fromhex("ff501cdb461c")
SELF_BUILD_HEAL_ANCHOR = 0x00857FAF
SELF_BUILD_HEAL_ANCHOR_BYTES = bytes.fromhex(
    "8b9f5c02000085db0f84da0000008b038bcbff501cdb461c8b461c85c07d06d8059886bd00def9"
    "8b4704f6801f01000020d95df0"
)
#: `Object+0xB8` - the bounding-circle radius of the object's `GeometryCollection` (which starts at
#: `+0xA8`): the largest 2D radius over its active shapes, offsets included, recomputed by
#: `0x00AD2860` whenever a shape is switched on or off. `privateMoveAwayFromUnit` reads the other
#: object's copy at `0x0066DCC9`.
OBJECT_BOUNDING_CIRCLE_RADIUS = 0xB8
OBJECT_BOUNDING_CIRCLE_RADIUS_READ = 0x0066DCC9
OBJECT_BOUNDING_CIRCLE_RADIUS_READ_BYTES = bytes.fromhex("f30f1098b8000000")

#: `Object::testModelCondition(index)` - `__thiscall`, one stack argument, `ret 4`; answers `0` or
#: `1` in `eax` from the `ModelConditionFlags` bitset at `Object+0x10C`. Clobbers only `eax`, `ecx`
#: and `edx`.
OBJECT_TEST_MODEL_CONDITION = 0x0046E918
OBJECT_TEST_MODEL_CONDITION_ENTRY = bytes.fromhex("8b54240433c0568bf140")
#: `ModelConditionFlags` `BASE_BUILD` - the build-up a castle unpack plays after its fade.
MODEL_CONDITION_BASE_BUILD = 219
#: `Object::findModule(NameKeyType)` - `__thiscall`, `ret 4`. Walks `OBJECT_MODULE_LIST` and returns
#: the first module whose `getModuleNameKey` (vtable `+0x10`) equals the argument, or NULL. The
#: key is the module's class name (`"CastleMemberBehavior"`), not its `ModuleTag`.
OBJECT_FIND_MODULE = 0x0068BDA5
OBJECT_FIND_MODULE_ENTRY = bytes.fromhex("568bb14c0200005733ffeb0e8b01ff50103b44240c")

#: `CastleBehavior`, the flag-side module that unpacks a camp or castle. Derived in
#: `docs/castle-unpack-button-gap.md` and `docs/castle-unpack-clearance.md`.
CASTLE_BEHAVIOR_NAME_STRING = 0x00C0BE9C
CASTLE_MEMBER_BEHAVIOR_NAME_STRING = 0x00C0BE84
CASTLE_BEHAVIOR_UNPACK = 0x0079BE6A
#: The update interface sits at module `+0x10`: the constructor stamps its vtable there, and
#: slot 0 of that vtable is `CastleBehavior::update`.
CASTLE_BEHAVIOR_UPDATE = 0x0079CF2A
CASTLE_BEHAVIOR_UPDATE_VTABLE = 0x00C30E08
CASTLE_BEHAVIOR_UPDATE_VTABLE_STAMP = 0x0079A954
CASTLE_BEHAVIOR_UPDATE_VTABLE_STAMP_BYTES = bytes.fromhex("c74610080ec300")  # mov [esi+0x10], vt
#: The unpack state, as a module-base offset: `update` keeps it at `[this+0x24]` with `this` the
#: interface at `+0x10`. `CASTLE_STATE_FADING` is the state between the unpack and the build-up:
#: the members exist, carry `JUST_BUILT`, and are fading in for `FadeTime`.
CASTLE_BEHAVIOR_STATE = 0x34
CASTLE_STATE_FADING = 2
#: `update`'s state-1 arm: `push ebx` (zero) / `lea ecx, [esi-0x10]` / `mov [esi+0x24], 2` /
#: `call unpack`. It is what makes state 2 mean "just unpacked".
CASTLE_BEHAVIOR_START_FADE = 0x0079D09D
CASTLE_BEHAVIOR_START_FADE_BYTES = bytes.fromhex("538d4ef0c7462402000000e8bdedffff")
#: `update`'s state-2 expiry: `mov [esi+0x24], 3`, two mask clears, then `or byte [ebp-9], 4`
#: (`JUST_BUILT`) and `or byte [ebp+0x43], 8` (`BASE_BUILD`) - the swap that ends the fade.
CASTLE_BEHAVIOR_START_BUILD_UP = 0x0079D065
CASTLE_BEHAVIOR_START_BUILD_UP_BYTES = bytes.fromhex(
    "c7462403000000e8b7fe29006a4c8d45dc5350e8abfe2900804df704804d4308"
)
#: `CastleMemberBehavior+0x18` - the `ObjectID` of the flag whose `CastleBehavior` built this
#: member. `CastleBehavior::onStructureBuilt` stamps it on every member it is handed:
#: `mov eax, [ebp-0x10]` (the flag) / `mov eax, [eax+0x74]` (its id) / `mov [ebx+0x18], eax`.
CASTLE_MEMBER_CASTLE_ID = 0x18
CASTLE_MEMBER_CASTLE_ID_STAMP = 0x0079AC81
CASTLE_MEMBER_CASTLE_ID_STAMP_BYTES = bytes.fromhex("8b45f08b4074894318")


#: Castle prefab selection: StartUnpack(bool, Object*), the no-argument prefab resolver,
#: ModuleData faction resolver(Player*), both actual-unpack resolver calls and common
#: SEH epilogue. The destructor also clears cancelled overrides; see docs/castle-prefab.md.
#: CASTLE_BEHAVIOR_UNPACK (0x0079BE6A) is already defined above.
CASTLE_BEHAVIOR_START_UNPACK = 0x0079C17D
CASTLE_BEHAVIOR_PREFAB_RESOLVER = 0x00799021
CASTLE_BEHAVIOR_FACTION_PREFAB = 0x00798F70
CASTLE_PREFAB_RESOLVER_USES = (0x0079B892, 0x0079B918)
CASTLE_BEHAVIOR_UNPACK_EPILOGUE = 0x0079C16D
CASTLE_BEHAVIOR_DESTRUCTOR = 0x0079AAA7
