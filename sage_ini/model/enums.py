import enum


class BFMEEnumMeta(enum.EnumMeta):
    def __getitem__(self, key):
        if key.lower() == "none":
            return None

        return super().__getitem__(key)


class BFMEEnum(enum.Enum, metaclass=BFMEEnumMeta):
    @classmethod
    def convert(cls, parser, name):
        key = _unprefixed(name)
        if isinstance(key, str) and key not in cls.__members__ and key.lower() != "none":
            member = cls._case_insensitive(key)
            if member is not None:
                _warn_enum_case(parser, cls, key, member)
                return member
        return cls[key]

    @classmethod
    def _case_insensitive(cls, key):
        """The member whose name matches `key` ignoring case, or None - the engine treats
        enum tokens case-insensitively, so we accept the mismatch but flag it."""
        upper = key.upper()
        for member_name, member in cls.__members__.items():
            if member_name.upper() == upper:
                return member
        return None

    @classmethod
    def has(cls, key):
        return _unprefixed(key) in cls.__members__


def _warn_enum_case(game, cls, given, member):
    """Record an `enum-case` warning when a token only matched ignoring case."""
    warn = getattr(game, "warn", None)
    if warn is not None:
        warn(
            "enum-case",
            f"{cls.__name__} {given!r} should be {member.name!r} (case mismatch)",
            {"given": given, "canonical": member.name, "enum": cls.__name__},
        )


def _unprefixed(name):
    """Drop a leading `+`/`-` override marker before resolving a member. In an override
    context a list field adds (`+FLAG`) or removes (`-FLAG`) one member; the member named is
    the same either way."""
    if isinstance(name, str) and name[:1] in "+-":
        return name[1:]
    return name


class CaseInsensitiveEnum(BFMEEnum):
    """A `BFMEEnum` that accepts any case *silently* - it still validates membership (an
    unknown token raises), but matches case-insensitively without emitting `enum-case`. For
    token sets the corpus writes in mixed/lower case with no canonical spelling to enforce
    (the audio flags: `world`/`voice`/`music`), where a case warning is pure noise."""

    @classmethod
    def convert(cls, parser, name):
        key = _unprefixed(name)
        if isinstance(key, str) and key not in cls.__members__ and key.lower() != "none":
            member = cls._case_insensitive(key)
            if member is not None:
                return member
        return cls[key]


class GeometryType(BFMEEnum):
    """The primitive an object's collision/footprint shape uses - the value of a
    `Geometry`/`AdditionalGeometry` line."""

    SPHERE = 0
    CYLINDER = 1
    BOX = 2


class FakeEnum(BFMEEnum):
    @classmethod
    def convert(cls, parser, name):
        return name

    @classmethod
    def has(cls, key):
        return True


class MomentEnum(BFMEEnum):
    INITIAL = 0
    MIDPOINT = 1
    FINAL = 2


class SlowDeathPhase(BFMEEnum):
    """When a SlowDeath stage fires - like `MomentEnum` plus the `HIT_GROUND` phase a falling
    death triggers when the body lands."""

    INITIAL = 0
    MIDPOINT = 1
    FINAL = 2
    HIT_GROUND = 3


class StructureCollapsePhase(BFMEEnum):
    """When a `StructureCollapseUpdate` stage fires: `INITIAL`, an `ALMOST_FINAL` warning just
    before it settles, then `FINAL` (unlike `MomentEnum`, which has no `ALMOST_FINAL`)."""

    INITIAL = 0
    ALMOST_FINAL = 1
    FINAL = 2


class AModAuraCondition(BFMEEnum):
    MOUNTED = 0
    TAINT = 1
    ELVEN_WOOD = 2


class HealthOperation(BFMEEnum):
    SAME_CURRENTHEALTH = 0
    PRESERVE_RATIO = 1
    ADD_CURRENT_HEALTH_TOO = 2


class ModifierType(BFMEEnum):
    ARMOR = 0
    DAMAGE_ADD = 1
    RESIST_FEAR = 2
    RESIST_TERROR = 3
    RANGE = 4
    RESIST_KNOCKBACK = 5
    HEALTH = 6
    VISION = 7
    AUTO_HEAL = 8
    SHROUD_CLEARING = 9
    SEPARATOR = 9.5
    DAMAGE_MULT = 10
    EXPERIENCE = 11
    SPEED = 12
    CRUSH_DECELERATE = 13
    SPELL_DAMAGE = 14
    RECHARGE_TIME = 15
    PRODUCTION = 16
    HEALTH_MULT = 17
    RATE_OF_FIRE = 18
    MINIMUM_CRUSH_VELOCITY = 19
    DAMAGE_STRUCTURE_BOUNTY_ADD = 20
    COMMAND_POINT_BONUS = 21
    CRUSHABLE_LEVEL = 22
    INVULNERABLE = 23
    BOUNTY_PERCENTAGE = 24
    CRUSHED_DECELERATE = 25
    CRUSHER_LEVEL = 26

    def is_mult(self):
        return self.value > self.__class__.SEPARATOR.value


class ArmorSetFlags(BFMEEnum):
    VETERAN = 0
    ELITE = 1
    HERO = 2
    PLAYER_UPGRADE = 3
    WEAK_VERSUS_BASEDEFENSES = 4
    ALTERNATE_FORMATION = 5
    MOUNTED = 6
    PLAYER_UPGRADE_2 = 7
    PLAYER_UPGRADE_3 = 8
    UNBESIEGEABLE = 9
    AS_TOWER = 10
    CREATE_A_HERO_01 = 11
    CREATE_A_HERO_02 = 12
    CREATE_A_HERO_03 = 13
    CREATE_A_HERO_04 = 14
    CREATE_A_HERO_05 = 15
    CREATE_A_HERO_06 = 16
    CREATE_A_HERO_07 = 17
    CREATE_A_HERO_08 = 18
    CREATE_A_HERO_09 = 19
    CREATE_A_HERO_10 = 20


class EmotionNuggetAIState(BFMEEnum):
    BACK_AWAY = 0
    AVOID_SCARER = 1
    IDLE = 2
    RUN_AWAY_PANIC = 3
    FACE_OBJECT = 4
    QUARREL = 5


class EmotionTypes(BFMEEnum):
    TAUNT = 0
    CHEER = 1
    HERO_CHEER = 2
    POINT = 3
    FEAR = 4
    UNCONTROLLABLE_FEAR = 5
    TERROR = 6
    DOOM = 7
    QUARRELSOME = 8
    ALERT = 9
    BRACE_FOR_BEING_CRUSHED = 10
    CHEER_FOR_ABOUT_TO_CRUSH = 11


class FactionSide:
    """A faction side, kept open (mods define their own) - any token passes through as the
    raw name; `sides()` exposes the live set declared by the game's `PlayerTemplate`s."""

    @staticmethod
    def convert(game, value):
        return value

    @staticmethod
    def sides(game):
        templates = game.tables.get("factions", {})
        return {pt.Side for pt in templates.values() if pt.Side is not None}

    @staticmethod
    def has(game, key):
        return key in FactionSide.sides(game)


class KindOf(BFMEEnum):
    OBSTACLE = 0
    SELECTABLE = 1
    IMMOBILE = 2
    CAN_ATTACK = 3
    STICK_TO_TERRAIN_SLOPE = 4
    CAN_CAST_REFLECTIONS = 5
    SHRUBBERY = 6
    STRUCTURE = 7
    INFANTRY = 8
    CAVALRY = 9
    MONSTER = 10
    MACHINE = 11
    AIRCRAFT = 12
    HUGE_VEHICLE = 13
    DOZER = 14
    SWARM_DOZER = 15
    HARVESTER = 16
    COMMANDCENTER = 17
    CASTLE_CENTER = 18
    SALVAGER = 19
    WEAPON_SALVAGER = 20
    TRANSPORT = 21
    BRIDGE = 22
    LANDMARK_BRIDGE = 23
    BRIDGE_TOWER = 24
    PROJECTILE = 25
    PRELOAD = 26
    NO_GARRISON = 27
    CASTLE_KEEP = 28
    WAVE_EFFECT = 29
    NO_COLLIDE = 30
    REPAIR_PAD = 31
    HEAL_PAD = 32
    STEALTH_GARRISON = 33
    SUPPLY_GATHERING_CENTER = 34
    AIRFIELD = 35
    DRAWABLE_ONLY = 36
    MP_COUNT_FOR_VICTORY = 37
    REBUILD_HOLE = 38
    SCORE = 39
    SCORE_CREATE = 40
    SCORE_DESTROY = 41
    NO_HEAL_ICON = 42
    CAN_RAPPEL = 43
    PARACHUTABLE = 44
    CAN_BE_REPULSED = 45
    MOB_NEXUS = 46
    IGNORED_IN_GUI = 47
    CRATE = 48
    CAPTURABLE = 49
    LINKED_TO_FLAG = 50
    CLEARED_BY_BUILD = 51
    SMALL_MISSILE = 52
    ALWAYS_VISIBLE = 53
    UNATTACKABLE = 54
    MINE = 55
    CLEANUP_HAZARD = 56
    PORTABLE_STRUCTURE = 57
    ALWAYS_SELECTABLE = 58
    ATTACK_NEEDS_LINE_OF_SIGHT = 59
    WALK_ON_TOP_OF_WALL = 60
    DEFENSIVE_WALL = 61
    FS_POWER = 62
    FS_FACTORY = 63
    FS_BASE_DEFENSE = 64
    FS_TECHNOLOGY = 65
    AIRCRAFT_PATH_AROUND = 66
    LOW_OVERLAPPABLE = 67
    FORCEATTACKABLE = 68
    AUTO_RALLYPOINT = 69
    OATHBREAKER = 70
    POWERED = 71
    PRODUCED_AT_HELIPAD = 72
    DRONE = 73
    CAN_SEE_THROUGH_STRUCTURE = 74
    BALLISTIC_MISSILE = 75
    CLICK_THROUGH = 76
    SUPPLY_SOURCE_ON_PREVIEW = 77
    PARACHUTE = 78
    GARRISONABLE_UNTIL_DESTROYED = 79
    BOAT = 80
    IMMUNE_TO_CAPTURE = 81
    HULK = 82
    SHOW_PORTRAIT_WHEN_CONTROLLED = 83
    SPAWNS_ARE_THE_WEAPONS = 84
    CANNOT_BUILD_NEAR_SUPPLIES = 85
    SUPPLY_SOURCE = 86
    REVEAL_TO_ALL = 87
    DISGUISER = 88
    INERT = 89
    HERO = 90
    IGNORES_SELECT_ALL = 91
    DONT_AUTO_CRUSH_INFANTRY = 92
    SIEGE_TOWER = 93
    TREE = 94
    SHRUB = 95
    CLUB = 96
    ROCK = 97
    THROWN_OBJECT = 98
    GRAB_AND_KILL = 99
    OPTIMIZED_PROP = 100
    ENVIRONMENT = 101
    DEFLECT_BY_SPECIAL_POWER = 102
    WORKING_PASSENGER = 103
    BASE_FOUNDATION = 104
    NEED_BASE_FOUNDATION = 105
    REACT_WHEN_SELECTED = 106
    GIMLI = 107
    ORC = 108
    HORDE = 109
    COMBO_HORDE = 110
    NONOCCLUDING = 111
    NO_FREEWILL_ENTER = 112
    CAN_USE_SIEGE_TOWER = 113
    CAN_RIDE_SIEGE_LADDER = 114
    TACTICAL_MARKER = 115
    PATH_THROUGH_EACH_OTHER = 116
    NOTIFY_OF_PREATTACK = 117
    GARRISON = 118
    MELEE_HORDE = 119
    BASE_SITE = 120
    INERT_SHROUD_REVEALER = 121
    OCL_BIT = 122
    SPELL_BOOK = 123
    DEPRECATED = 124
    PATH_THROUGH_INFANTRY = 125
    NO_FORMATION_MOVEMENT = 126
    NO_BASE_CAPTURE = 127
    ARMY_SUMMARY = 128
    HOBBIT = 129
    NOT_AUTOACQUIRABLE = 130
    URUK = 131
    CHUNK_VENDOR = 132
    ARCHER = 133
    MOVE_ONLY = 134
    FS_CASH_PRODUCER = 135
    ROCK_VENDOR = 136
    BLOCKING_GATE = 137
    CAN_RIDE_BATTERING_RAM = 138
    SIEGE_LADDER = 139
    MINE_TRIGGER = 140
    BUFF = 141
    GRAB_AND_DROP = 142
    PORTER = 143
    SCARY = 144
    CRITTER_EMITTER = 145
    SALT_LICK = 146
    CAN_ATTACK_WALLS = 147
    IGNORE_FOR_VICTORY = 148
    DO_NOT_CLASSIFY = 149
    WALL_UPGRADE = 150
    ARMY_OF_DEAD = 151
    TAINT = 152
    BASE_DEFENSE_FOUNDATION = 153
    NOT_SELLABLE = 154
    WEBBED = 155
    WALL_HUB = 156
    BUILD_FOR_FREE = 157
    IGNORE_FOR_EVA_SPEECH_POSITION = 158
    MADE_OF_WOOD = 159
    MADE_OF_METAL = 160
    MADE_OF_STONE = 161
    MADE_OF_DIRT = 162
    FACE_AWAY_FROM_CASTLE_KEEP = 163
    BANNER = 164
    I_WANT_TO_EAT_YOU = 165
    INDUSTRY_AFFECTED = 166
    DWARVENRICHES_AFFECTED = 167
    GANDALF = 168
    ARAGORN = 169
    HAS_HEALTH_BAR = 170
    BIG_MONSTER = 171
    DEPLOYED_MINE = 172
    CANNOT_RETALIATE = 173
    CREEP = 174
    TAINTEFFECT = 175
    TROLL_BUFF_NUGGET = 176
    VITAL_FOR_BASE_SURVIVAL = 177
    DO_NOT_PICK_ME_WHEN_BUILDING = 178
    SUMMONED = 179
    HIDE_IF_FOGGED = 180
    ALWAYS_SHOW_HOUSE_COLOR = 181
    MOVE_FOR_NOONE = 182
    WB_DISPLAY_SCRIPT_NAME = 183
    CAN_CLIMB_WALLS = 184
    MUMAKIL_BUFF_NUGGET = 185
    LARGE_RECTANGLE_PATHFIND = 186
    SUBMARINE = 187
    PORT = 188
    WALL_SEGMENT = 189
    CREATE_A_HERO = 190
    SHIP = 191
    OPTIMIZED_SOUND = 192
    PASS_EXPERIENCE_TO_CONTAINED = 193
    DOZER_FACTORY = 194
    THREAT_FINDER = 195
    ECONOMY_STRUCTURE = 196
    LIVING_WORLD_BUILDING_MIRROR = 197
    PIKE = 198
    NONCOM = 199
    OBSOLETE = 200
    SCALEABLE_WALL = 201
    SKYBOX = 202
    WALL_GATE = 203
    CAPTUREFLAG = 204
    NEUTRALGOLLUM = 205
    PASS_EXPERIENCE_TO_CONTAINER = 206
    GIANT_BIRD = 207
    ORIENTS_TO_CAMERA = 208
    NEVER_CULL_FOR_MP = 209
    DONT_USE_CANCEL_BUILD_BUTTON = 210
    ONE_RING = 211
    HEAVY_MELEE_HITTER = 212
    DONT_HIDE_IF_FOGGED = 213
    CAN_SHOOT_OVER_WALLS = 214
    PASS_EXPERIENCE_TO_PRODUCER = 215
    EXPANSION_PAD = 216
    AMPHIBIOUS = 217
    SUPPORT = 218
    TROLL = 219
    SIEGEENGINE = 220
    HORDE_MONSTER = 221


class WeaponSetConditions(BFMEEnum):
    """Weapon/armor set condition flags (WeaponSet/ArmorSet `Conditions`, toggles); the
    OpenSAGE vanilla set. `None` resolves to `None` via the metaclass."""

    VETERAN = enum.auto()
    ELITE = enum.auto()
    HERO = enum.auto()
    PLAYER_UPGRADE = enum.auto()
    CARBOMB = enum.auto()
    MINE_CLEARING_DETAIL = enum.auto()
    CRATEUPGRADE_ONE = enum.auto()
    CRATEUPGRADE_TWO = enum.auto()
    WEAPON_RIDER1 = enum.auto()
    WEAPON_RIDER2 = enum.auto()
    WEAPON_RIDER3 = enum.auto()
    WEAPON_RIDER4 = enum.auto()
    WEAPON_RIDER5 = enum.auto()
    WEAPON_RIDER6 = enum.auto()
    WEAPON_RIDER7 = enum.auto()
    PASSENGER_TYPE_ONE = enum.auto()
    RAMPAGE = enum.auto()
    CLOSE_RANGE = enum.auto()
    CONTESTING_BUILDING = enum.auto()
    SPECIAL_UPGRADE = enum.auto()
    WEAPONSET_TOGGLE_1 = enum.auto()
    WEAPONSET_HERO_MODE = enum.auto()
    CONTAINED = enum.auto()
    MOUNTED = enum.auto()
    WEAPONSET_ONE_RING_MODE = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_01 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_02 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_03 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_04 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_05 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_06 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_07 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_08 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_09 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_10 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_11 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_12 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_13 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_14 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_15 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_16 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_17 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_18 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_19 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_20 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_21 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_22 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_23 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_24 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_25 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_26 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_27 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_28 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_29 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_30 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_31 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_32 = enum.auto()
    HIDDEN = enum.auto()
    PASSENGER_TYPE_TWO = enum.auto()
    SPECIAL_ONE = enum.auto()
    SPECIAL_TWO = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_33 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_34 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_35 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_36 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_37 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_38 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_39 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_40 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_41 = enum.auto()
    WEAPONSET_CREATE_A_HERO_WS_42 = enum.auto()
    WEAPONSET_TOGGLE_2 = enum.auto()


# WeaponSet and ArmorSet `Conditions`/toggle fields share one engine vocabulary.
WeaponsetFlags = WeaponSetConditions


class SlotTypes(BFMEEnum):
    PRIMARY = 0
    SECONDARY = 1
    TERTIARY = 2
    QUATERNARY = 3
    QUINARY = 4


class LivingWorldObjectType(BFMEEnum):
    ARMY = 0
    BATTLE_MARKER = 1
    REGION_AWARD_DISPUTE = 2
    CLOUD = 3
    BUILDING = 4
    DEFAULT = 5


class DeathFlags(BFMEEnum):
    """A `SlowDeathBehavior.DeathFlags` selector (`DEATH_1`..`DEATH_5`): which of an object's
    slow-death variants this behavior handles. A `[Flags]` set in the engine, though the corpus
    names a single variant per line. `NONE` maps to `None` via the metaclass."""

    DEATH_1 = 1 << 0
    DEATH_2 = 1 << 1
    DEATH_3 = 1 << 2
    DEATH_4 = 1 << 3
    DEATH_5 = 1 << 4


class MappedImageStatus(BFMEEnum):
    """A `MappedImage.Status` flag - how the source texture region is oriented when blitted.
    `NONE` maps to `None` via the metaclass."""

    ROTATED_90_CLOCKWISE = 0


class LivingWorldBuildingType(BFMEEnum):
    """A `LivingWorldBuilding.Type` category. Members surveyed from the corpus."""

    Resource = 0
    Armory = 1
    Barracks = 2
    Fortress = 3


class InvisibilityOptions(BFMEEnum):
    """An `InvisibilityNugget.Options` flag. Members surveyed from the corpus."""

    UNTOGGLE_HIDDEN_WHEN_LEAVING_STEALTH = 0
    ALLOW_NEAR_TREES = 1
    DETECTED_BY_FRIENDLIES = 2


class ParticleSystemType(BFMEEnum):
    """An FX particle `System.Type` - the renderer/primitive a particle system uses. Members
    surveyed from the corpus."""

    DRAWABLE = 0
    GPU_PARTICLE = 1
    STREAK = 2
    VOLUME_PARTICLE = 3
    SMUDGE = 4
    GPU_TERRAINFIRE = 5


class CombatChainUnitType(BFMEEnum):
    """A `CombatChainDefinition.Unit` category - the unit class an auto-resolve combat chain
    targets. Members surveyed from the corpus."""

    INFANTRY = 0
    ARCHER = 1
    CAVALRY = 2
    PIKEMAN = 3
    SIEGEWEAPON = 4
    HERO = 5
    CREEP = 6
    STRUCTURE = 7
    WALL = 8
    BATTLE_TOWER = 9
    SHIP_BATTLESHIP = 10
    SHIP_BOMBARD = 11
    SHIP_SUICIDE = 12


class CommandTypes(BFMEEnum):
    """`CommandButton.Command` action, resolved by name; the OpenSAGE set across Generals/ZH
    and BFME 1/2. `NONE` maps to `None` via the metaclass."""

    NONE = enum.auto()
    PLACE_BEACON = enum.auto()
    SPECIAL_POWER = enum.auto()
    SPECIAL_POWER_FROM_COMMAND_CENTER = enum.auto()
    SPECIAL_POWER_FROM_SHORTCUT = enum.auto()
    OBJECT_UPGRADE = enum.auto()
    PLAYER_UPGRADE = enum.auto()
    EXIT_CONTAINER = enum.auto()
    EVACUATE = enum.auto()
    EXECUTE_RAILED_TRANSPORT = enum.auto()
    COMBATDROP = enum.auto()
    GUARD = enum.auto()
    GUARD_WITHOUT_PURSUIT = enum.auto()
    GUARD_FLYING_UNITS_ONLY = enum.auto()
    ATTACK_MOVE = enum.auto()
    STOP = enum.auto()
    FIRE_WEAPON = enum.auto()
    SWITCH_WEAPON = enum.auto()
    DOZER_CONSTRUCT_CANCEL = enum.auto()
    DOZER_CONSTRUCT = enum.auto()
    CANCEL_UNIT_BUILD = enum.auto()
    UNIT_BUILD = enum.auto()
    PURCHASE_SCIENCE = enum.auto()
    TOGGLE_OVERCHARGE = enum.auto()
    SET_RALLY_POINT = enum.auto()
    SELL = enum.auto()
    CANCEL_UPGRADE = enum.auto()
    CONVERT_TO_CARBOMB = enum.auto()
    HIJACK_VEHICLE = enum.auto()
    HACK_INTERNET = enum.auto()
    SABOTAGE_BUILDING = enum.auto()
    SELECT_ALL_UNITS_OF_TYPE = enum.auto()
    SPECIAL_POWER_CONSTRUCT = enum.auto()
    SPECIAL_POWER_CONSTRUCT_FROM_SHORTCUT = enum.auto()
    HORDE_TOGGLE_FORMATION = enum.auto()
    TOGGLE_WEAPONSET = enum.auto()
    WAKE_AUTO_PICKUP = enum.auto()
    BLOODTHIRSTY = enum.auto()
    MONSTERDOCK = enum.auto()
    CREW_EVACUATE = enum.auto()
    TOGGLE_WEAPON = enum.auto()
    EVACUATE_CONTESTED = enum.auto()
    FOUNDATION_CONSTRUCT = enum.auto()
    CASTLE_UNPACK = enum.auto()
    CASTLE_UNPACK_EXPLICIT_OBJECT = enum.auto()
    CASTLE_UPGRADE = enum.auto()
    REVIVE = enum.auto()
    FOUNDATION_CONSTRUCT_CANCEL = enum.auto()
    SPELL_BOOK = enum.auto()
    ONE_RING = enum.auto()
    TOGGLE_NO_AUTO_ACQUIRE = enum.auto()
    TOGGLE_GATE = enum.auto()
    START_SELF_REPAIR = enum.auto()
    POP_VISIBLE_COMMAND_RANGE = enum.auto()
    TOGGLE_STANCE = enum.auto()
    SET_STANCE = enum.auto()
    PUSH_VISIBLE_COMMAND_RANGE = enum.auto()
    START_NEIGHBORHOOD_REPAIR = enum.auto()
    CANCEL_NEIGHBORHOOD = enum.auto()
    SPECIAL_POWER_TOGGLE = enum.auto()


class SpecialPowerAIType(BFMEEnum):
    """An `AISpecialPowerUpdate.SpecialPowerAIType`: the canned behaviour the AI uses to
    decide when and how to fire a special power; the OpenSAGE set across BFME 1/2 and RotWK."""

    AI_SPECIAL_POWER_CAPTURE_BUILDING = enum.auto()
    AI_SPECIAL_POWER_TOGGLE_MOUNTED = enum.auto()
    AI_SPECIAL_POWER_BASIC_SELF_BUFF = enum.auto()
    AI_SPECIAL_POWER_ENEMY_TYPE_KILLER = enum.auto()
    AI_SPECIAL_POWER_GIVEXP_AOE = enum.auto()
    AI_SPECIAL_POWER_GANDALF_WIZARD_BLAST = enum.auto()
    AI_SPECIAL_POWER_RANGED_AOE_ATTACK = enum.auto()
    AI_SPECIAL_POWER_TOGGLE_SIEGE = enum.auto()
    AI_SPECIAL_POWER_ENEMY_TYPE_KILLER_RANGED = enum.auto()
    AI_SPECIAL_POWER_GOBLINKING_MOUNTED = enum.auto()
    AI_SPECIAL_POWER_GOBLINKING_CALLOFTHEDEEP = enum.auto()
    AI_SPECIAL_POWER_CHARGE = enum.auto()
    AI_SPECIAL_POWER_STANCEBATTLE = enum.auto()
    AI_SPECIAL_POWER_STANCEAGGRESSIVE = enum.auto()
    AI_SPECIAL_POWER_STANCEHOLDGROUND = enum.auto()
    AI_SPECIAL_POWER_TARGETAOE_SUMMON = enum.auto()
    AI_SPECIAL_POWER_ENEMY_TYPE_KILLER_STRUCTURES = enum.auto()
    AI_SPECIAL_POWER_SELFAOEHEALHEROS = enum.auto()
    AI_SPELLBOOK_SHROUD_REVEAL = enum.auto()
    AI_SPECIAL_POWER_HEAL_AOE = enum.auto()
    AI_SPECIAL_POWER_LEGOLAS_ARROWWIND = enum.auto()
    AI_SPECIAL_POWER_LEGOLAS_TRAINARCHERS = enum.auto()
    AI_SPECIAL_POWER_ELENDIL = enum.auto()
    AI_SPELLBOOK_ASSIST_BATTLE_BUFF = enum.auto()
    AI_SPELLBOOK_ASSIST_BATTLE_DEBUFF = enum.auto()
    AI_SPELLBOOK_STRUCTURE_BASEKILL = enum.auto()
    AI_SPELLBOOK_STRUCTURE_BREAKER = enum.auto()
    AI_SPELLBOOK_STRUCTURE_BREAKER_PREF_WALLS = enum.auto()
    AI_SPELLBOOK_ALWAYS_FIRE = enum.auto()
    AI_SPELLBOOK_CAPTURE_CREEP = enum.auto()
    AI_SPELLBOOK_TREE_KILLER = enum.auto()
    AI_SPELLBOOK_BUFFTERRAIN = enum.auto()
    AI_SPELLBOOK_REBUILD = enum.auto()
    AI_SPELLBOOK_BUFFECONOMYBUILDING = enum.auto()
    AI_SPELLBOOK_CALLTHEHORDE = enum.auto()
    AI_SPELLBOOK_HEAL = enum.auto()
    AI_SPELLBOOK_ENSHROUDINGMIST = enum.auto()
    AI_SPELLBOOK_ARMY_BREAKER = enum.auto()
    AI_SPELLBOOK_CITADEL = enum.auto()
    # Added in BFME 2 RotWK.
    AI_SPECIAL_POWER_DOMINATE_ENEMY = enum.auto()
    AI_SPECIAL_POWER_TOGGLE_MELEE_AND_RANGE = enum.auto()
    AI_SPECIAL_POWER_RANGED_AOE_ATTACK_UNITS = enum.auto()
    AI_SPECIAL_POWER_SOUL_FREEZE = enum.auto()
    AI_SPECIAL_POWER_AOE_AND_BUFF = enum.auto()
    AI_SPECIAL_POWER_ATTACK_HEAL_AOE = enum.auto()
    AI_SPECIAL_POWER_MORGUL_BLADE = enum.auto()
    AI_SPECIAL_POWER_GOBLIN_POISON = enum.auto()
    AI_SPECIAL_POWER_DOMINATE_TROLL = enum.auto()
    AI_SPECIAL_POWER_TAME_THE_BEAST = enum.auto()
    AI_SPECIAL_POWER_BASIC_SELF_DEBUFF = enum.auto()
    AI_SPELLBOOK_DEBUFFECONOMYBUILDING = enum.auto()
    AI_SPELLBOOK_DEBUFFPRODUCTIONBUILDING = enum.auto()


class LogicTypes(BFMEEnum):
    INCREASE_BURN_RATE = 0
    INCREASE_FUEL = 1
    INCREASE_FUEL_ON_EXISTING_FIRE = 2
    INCREASE_BURN_RATE_ON_EXISTING_FIRE = 3
    DECREASE_BURN_RATE = 4
    DECREASE_FUEL = 5
    DECREASE_FUEL_ON_EXISTING_FIRE = 6
    DECREASE_BURN_RATE_ON_EXISTING_FIRE = 7


class ModelCondition(BFMEEnum):
    TOPPLED = 0
    FRONTCRUSHED = 1
    BACKCRUSHED = 2
    DAMAGED = 3
    REALLYDAMAGED = 4
    RUBBLE = 5
    SPECIAL_DAMAGED = 6
    NIGHT = 7
    SNOW = 8
    PARACHUTING = 9
    GARRISONED = 10
    ENEMYNEAR = 11
    WEAPONSET_VETERAN = 12
    WEAPONSET_ELITE = 13
    WEAPONSET_HERO = 14
    WEAPONSET_PASSENGER_TYPE_ONE = 15
    WEAPONSET_PASSENGER_TYPE_TWO = 16
    WEAPONSET_PLAYER_UPGRADE = 17
    WEAPONSTATE_ONE = 18
    WEAPONSTATE_TWO = 19
    WEAPONSTATE_THREE = 20
    DOOR_1_OPENING = 21
    DOOR_1_CLOSING = 22
    DOOR_1_WAITING_OPEN = 23
    DOOR_1_WAITING_TO_CLOSE = 24
    DOOR_2_OPENING = 25
    DOOR_2_CLOSING = 26
    DOOR_2_WAITING_OPEN = 27
    DOOR_2_WAITING_TO_CLOSE = 28
    DOOR_3_OPENING = 29
    DOOR_3_CLOSING = 30
    DOOR_3_WAITING_OPEN = 31
    DOOR_3_WAITING_TO_CLOSE = 32
    DOOR_4_OPENING = 33
    DOOR_4_CLOSING = 34
    DOOR_4_WAITING_OPEN = 35
    DOOR_4_WAITING_TO_CLOSE = 36
    ATTACKING = 37
    ATTACKING_STRUCTURE = 38
    ATTACKING_POSITION = 39
    PREATTACK_A = 40
    FIRING_A = 41
    FIRING_OR_PREATTACK_A = 42
    FIRING_OR_RELOADING_A = 43
    BETWEEN_FIRING_SHOTS_A = 44
    RELOADING_A = 45
    PREATTACK_B = 46
    FIRING_B = 47
    FIRING_OR_PREATTACK_B = 48
    FIRING_OR_RELOADING_B = 49
    BETWEEN_FIRING_SHOTS_B = 50
    RELOADING_B = 51
    PREATTACK_C = 52
    FIRING_C = 53
    FIRING_OR_PREATTACK_C = 54
    FIRING_OR_RELOADING_C = 55
    BETWEEN_FIRING_SHOTS_C = 56
    RELOADING_C = 57
    TURRET_ROTATE = 58
    POST_RUBBLE = 59
    POST_COLLAPSE = 60
    MOVING = 61
    DYING = 62
    EMOTION_ALERT = 63
    EMOTION_AFRAID = 64
    EMOTION_TERROR = 65
    EMOTION_PANIC = 66
    AWAITING_CONSTRUCTION = 67
    PARTIALLY_CONSTRUCTED = 68
    ACTIVELY_BEING_CONSTRUCTED = 69
    UNIT_ACTIVELY_BEING_CONSTRUCTED = 70
    PRONE = 71
    FREEFALL = 72
    ACTIVELY_CONSTRUCTING = 73
    CONSTRUCTION_COMPLETE = 74
    RADAR_EXTENDING = 75
    RADAR_UPGRADED = 76
    PANICKING = 77
    AFLAME = 78
    SMOLDERING = 79
    BURNED = 80
    DOCKING = 81
    DOCKING_BEGINNING = 82
    DOCKING_ACTIVE = 83
    DOCKING_ENDING = 84
    CARRYING = 85
    FLOODED = 86
    LOADED = 87
    PASSENGER = 88
    TRANSPORT_MOVING = 89
    TRANSPORT_STOPPED = 90
    CLUB = 91
    JETAFTERBURNER = 92
    JETEXHAUST = 93
    PACKING = 94
    PREPARING = 95
    UNPACKING = 96
    PACKING_TYPE_1 = 97
    PACKING_TYPE_2 = 98
    PACKING_TYPE_3 = 99
    DEPLOYED = 100
    OVER_WATER = 101
    POWER_PLANT_UPGRADED = 102
    CLIMBING = 103
    SOLD = 104
    RAPPELLING = 105
    ARMED = 106
    POWER_PLANT_UPGRADING = 107
    BUILD_PLACEMENT_CURSOR = 108
    PHANTOM_STRUCTURE = 109
    START_CAPTURE = 110
    CANCEL_CAPTURE = 111
    CAPTURING = 112
    PORCUPINE = 113
    SPECIAL_CHEERING = 114
    CONTINUOUS_FIRE_SLOW = 115
    CONTINUOUS_FIRE_MEAN = 116
    CONTINUOUS_FIRE_FAST = 117
    RAISING_FLAG = 118
    CAPTURED = 119
    EXPLODED_FLAILING = 120
    EXPLODED_BOUNCING = 121
    SPLATTED = 122
    USING_WEAPON_A = 123
    USING_WEAPON_B = 124
    USING_WEAPON_C = 125
    PREORDER = 126
    STUNNED_FLAILING = 127
    STUNNED = 128
    STONED = 129
    WANDER = 130
    WALKING = 131
    CHARGING = 132
    TURN_LEFT = 133
    TURN_RIGHT = 134
    ACCELERATE = 135
    DECELERATE = 136
    TURN_LEFT_HIGH_SPEED = 137
    TURN_RIGHT_HIGH_SPEED = 138
    DESTROYED_FRONT = 139
    DESTROYED_RIGHT = 140
    DESTROYED_BACK = 141
    DESTROYED_LEFT = 142
    WEAPONSET_GARRISONED = 143
    WEAPONLOCK_PRIMARY = 144
    WEAPONLOCK_SECONDARY = 145
    WEAPONLOCK_TERTIARY = 146
    WEAPONLOCK_QUATERNARY = 147
    WEAPONLOCK_QUINARY = 148
    DEATH_1 = 149
    DEATH_2 = 150
    DEATH_3 = 151
    DEATH_4 = 152
    DECAY = 153
    THROWN_PROJECTILE = 154
    ABOUT_TO_HIT = 155
    BACKING_UP = 156
    ENGAGED = 157
    DEFLECT_SPECIAL_POWER = 158
    WEAPONSET_CLOSE_RANGE = 159
    WEAPONSTATE_CLOSE_RANGE = 160
    WEAPONSET_RAMPAGE = 161
    RAMPAGE_ANIMATION_ONLY = 162
    STUNNED_STANDING_UP = 163
    REACT_1 = 164
    REACT_2 = 165
    REACT_3 = 166
    REACT_4 = 167
    REACT_5 = 168
    REACT_6 = 169
    SELECTED = 170
    GUARDING = 171
    HIT_REACTION = 172
    HIT_LEVEL_1 = 173
    HIT_LEVEL_2 = 174
    HIT_LEVEL_3 = 175
    GRAB_BUILDING_CHUNK = 176
    DEATH_5 = 177
    AIM_HIGH = 178
    AIM_STRAIGHT = 179
    AIM_LOW = 180
    AIM_NEAR = 181
    AIM_FAR = 182
    DIVING = 183
    USER_1 = 184
    USER_2 = 185
    USER_3 = 186
    USER_4 = 187
    USER_5 = 188
    SWOOPING = 189
    BURNT_MODEL = 190
    BURNT_TEXTURE = 191
    WEAPONSET_CONTESTING_BUILDING = 192
    DEBUG = 193
    PASSENGER_VARIATION_1 = 194
    PASSENGER_VARIATION_2 = 195
    PASSENGER_VARIATION_3 = 196
    PASSENGER_VARIATION_4 = 197
    PASSENGER_VARIATION_5 = 198
    EMOTION_GUNG_HO = 199
    EMOTION_LOOK_TO_SKY = 200
    EMOTION_CELEBRATING = 201
    EMOTION_AMUSED = 202
    EMOTION_MORALE_HIGH = 203
    EMOTION_MORALE_LOW = 204
    EMOTION_COWER = 205
    EMOTION_DISSIDENT = 206
    USING_SPECIAL_ABILITY = 207
    WORLD_BUILDER = 208
    SIEGE_CONTAIN = 209
    LEVELED = 210
    SPECIAL_POWER_1 = 211
    SPECIAL_POWER_2 = 212
    SPECIAL_POWER_3 = 213
    MOUNTED = 214
    OATH_FULLFILLED = 215
    RESURRECTED = 216
    DESTROYED_WEAPON = 217
    JUST_BUILT = 218
    BASE_BUILD = 219
    HERO = 220
    RIDER1 = 221
    RIDER2 = 222
    RIDER3 = 223
    RIDER4 = 224
    RIDER5 = 225
    RIDER6 = 226
    RIDER7 = 227
    RIDER8 = 228
    WEAPONSET_RIDER1 = 229
    WEAPONSET_RIDER2 = 230
    WEAPONSET_RIDER3 = 231
    WEAPONSET_RIDER4 = 232
    WEAPONSET_RIDER5 = 233
    WEAPONSET_RIDER6 = 234
    WEAPONSET_RIDER7 = 235
    WEAPONSET_RIDER8 = 236
    WEAPONSET_SPECIAL_ONE = 237
    WEAPONSET_SPECIAL_TWO = 238
    WADING = 239
    SWIMMING = 240
    WEAPONSET_CONTAINED = 241
    WEAPONSTATE_CONTAINED = 242
    HORDE_EMPTY = 243
    SPECIAL_WEAPON_ONE = 244
    SPECIAL_WEAPON_TWO = 245
    SPECIAL_WEAPON_THREE = 246
    WEAPONSET_MOUNTED = 247
    EATING = 248
    CHANT_FOR_GROND = 249
    WEAPONSET_ENRAGED = 250
    WEAPONSET_SPECIAL_UPGRADE = 251
    RUNNING_OFF_MAP = 252
    ONE_RING = 253
    PRIMARY_FORMATION = 254
    ALTERNATE_FORMATION = 255
    HARVEST_PREPARATION = 256
    HARVEST_ACTION = 257
    SPECIAL_ENEMY_NEAR = 258
    HIDDEN = 259
    PUTTING_ON_RING = 260
    TAKING_OFF_RING = 261
    UPGRADE_BOILING_OIL = 262
    UPGRADE_GARRISON = 263
    UPGRADE_POSTERN_GATE = 264
    UPGRADE_TREBUCHET = 265
    UPGRADE_NUMENOR_STONEWORK = 266
    UPGRADE_IVORY_TOWER = 267
    UPGRADE_HOUSE_OF_HEALING = 268
    UPGRADE_BLANK4 = 269
    UPGRADE_FORTRESS_MONUMENT = 270
    FORTRESS_IMPROVEMENT_1 = 271
    FORTRESS_IMPROVEMENT_2 = 272
    FORTRESS_IMPROVEMENT_3 = 273
    FORTRESS_IMPROVEMENT_4 = 274
    FORTRESS_IMPROVEMENT_5 = 275
    FORTRESS_IMPROVEMENT_6 = 276
    FORTRESS_IMPROVEMENT_7 = 277
    FORTRESS_IMPROVEMENT_8 = 278
    FORTRESS_IMPROVEMENT_9 = 279
    FORTRESS_IMPROVEMENT_1_BUILDING = 280
    FORTRESS_IMPROVEMENT_2_BUILDING = 281
    FORTRESS_IMPROVEMENT_3_BUILDING = 282
    FORTRESS_IMPROVEMENT_4_BUILDING = 283
    FORTRESS_IMPROVEMENT_5_BUILDING = 284
    FORTRESS_IMPROVEMENT_6_BUILDING = 285
    FORTRESS_IMPROVEMENT_7_BUILDING = 286
    FORTRESS_IMPROVEMENT_8_BUILDING = 287
    FORTRESS_IMPROVEMENT_9_BUILDING = 288
    FORTRESS_MONUMENT_CREATURE_AVAILABLE = 289
    FORTRESS_MONUMENT_CREATURE_UNAVAILABLE = 290
    FORTRESS_MONUMENT_UNDER_CONSTRUC = 291
    DRILL0 = 292
    DRILL1 = 293
    DRILL2 = 294
    DRILL3 = 295
    DRILL4 = 296
    RIDERLESS = 297
    DRAFTED = 298
    UPGRADED_ARMOR = 299
    DISGUISED = 300
    WEAPONSET_TOGGLE_1 = 301
    WEAPONSET_TOGGLE_2 = 302
    WEAPONSET_TOGGLE_3 = 303
    WEAPONSET_HERO_MODE = 304
    DOCKING_PRE_DOCK = 305
    TURRET_ANGLE_0 = 306
    TURRET_ANGLE_90 = 307
    TURRET_ANGLE_180 = 308
    TURRET_ANGLE_270 = 309
    USING_COMBO_LOCOMOTOR = 310
    WAR_CHANT = 311
    EMOTION_QUARRELSOME = 312
    QUARRELSOME_FIGHTING = 313
    UNCONTROLLABLE = 314
    INITIAL_ENRAGED = 315
    ARMORSET_VETERAN = 316
    ARMORSET_ELITE = 317
    ARMORSET_HERO = 318
    ARMORSET_WEAK_VERSUS_BASEDEFENSE = 319
    ARMORSET_ALTERNATE_FORMATION = 320
    ARMORSET_MOUNTED = 321
    ARMORSET_PLAYER_UPGRADE = 322
    ARMORSET_PLAYER_UPGRADE_2 = 323
    ARMORSET_PLAYER_UPGRADE_3 = 324
    ARMORSET_UNBESIEGEABLE = 325
    EMOTION_TAUNTING = 326
    EMOTION_DOOM = 327
    EMOTION_POINTING = 328
    WEAPON_TOGGLING = 329
    INVULNERABLE = 330
    MARCHING = 331
    UPGRADE_ECONOMY_BONUS = 332
    COMING_OUT_OF_FACTORY = 333
    DESTROYED_WHILST_BEING_CONSTRUCT = 334
    COLLAPSING = 335
    EMOTION_UNCONTROLLABLY_AFRAID = 336
    SAIL_FLAPPING = 337
    SAIL_BLOWN_RIGHT = 338
    SAIL_BLOWN_LEFT = 339
    BUILD_VARIATION_ONE = 340
    BUILD_VARIATION_TWO = 341
    LEASHED_RETURNING = 342
    CREATE_A_HERO_00 = 343
    CREATE_A_HERO_01 = 344
    CREATE_A_HERO_02 = 345
    CREATE_A_HERO_03 = 346
    CREATE_A_HERO_04 = 347
    CREATE_A_HERO_05 = 348
    CREATE_A_HERO_06 = 349
    CREATE_A_HERO_07 = 350
    CREATE_A_HERO_08 = 351
    CREATE_A_HERO_09 = 352
    CREATE_A_HERO_10 = 353
    CREATE_A_HERO_11 = 354
    CREATE_A_HERO_12 = 355
    CREATE_A_HERO_13 = 356
    CREATE_A_HERO_14 = 357
    CREATE_A_HERO_15 = 358
    CREATE_A_HERO_16 = 359
    CREATE_A_HERO_17 = 360
    CREATE_A_HERO_18 = 361
    CREATE_A_HERO_19 = 362
    CREATE_A_HERO_20 = 363
    CREATE_A_HERO_21 = 364
    CREATE_A_HERO_22 = 365
    CREATE_A_HERO_23 = 366
    CREATE_A_HERO_24 = 367
    CREATE_A_HERO_25 = 368
    CREATE_A_HERO_26 = 369
    CREATE_A_HERO_27 = 370
    CREATE_A_HERO_28 = 371
    CREATE_A_HERO_29 = 372
    CREATE_A_HERO_30 = 373
    CREATE_A_HERO_31 = 374
    CREATE_A_HERO_32 = 375
    CREATE_A_HERO_33 = 376
    CREATE_A_HERO_34 = 377
    CREATE_A_HERO_35 = 378
    CREATE_A_HERO_36 = 379
    CREATE_A_HERO_37 = 380
    CREATE_A_HERO_38 = 381
    CREATE_A_HERO_39 = 382
    CREATE_A_HERO_40 = 383
    CREATE_A_HERO_41 = 384
    CREATE_A_HERO_42 = 385
    CREATE_A_HERO_43 = 386
    CREATE_A_HERO_44 = 387
    CREATE_A_HERO_45 = 388
    CREATE_A_HERO_46 = 389
    CREATE_A_HERO_47 = 390
    CREATE_A_HERO_48 = 391
    CREATE_A_HERO_49 = 392
    CREATE_A_HERO_50 = 393
    CREATE_A_HERO_51 = 394
    CREATE_A_HERO_52 = 395
    CREATE_A_HERO_53 = 396
    CREATE_A_HERO_54 = 397
    CREATE_A_HERO_55 = 398
    CREATE_A_HERO_56 = 399
    CREATE_A_HERO_57 = 400
    CREATE_A_HERO_58 = 401
    CREATE_A_HERO_59 = 402
    CREATE_A_HERO_60 = 403
    CREATE_A_HERO_61 = 404
    CREATE_A_HERO_62 = 405
    CREATE_A_HERO_63 = 406
    CREATE_A_HERO_64 = 407
    CREATE_A_HERO_65 = 408
    WEAPONSET_CREATE_A_HERO_WS_01 = 409
    WEAPONSET_CREATE_A_HERO_WS_02 = 410
    WEAPONSET_CREATE_A_HERO_WS_03 = 411
    WEAPONSET_CREATE_A_HERO_WS_04 = 412
    WEAPONSET_CREATE_A_HERO_WS_05 = 413
    WEAPONSET_CREATE_A_HERO_WS_06 = 414
    WEAPONSET_CREATE_A_HERO_WS_07 = 415
    WEAPONSET_CREATE_A_HERO_WS_08 = 416
    WEAPONSET_CREATE_A_HERO_WS_09 = 417
    WEAPONSET_CREATE_A_HERO_WS_10 = 418
    WEAPONSET_CREATE_A_HERO_WS_11 = 419
    WEAPONSET_CREATE_A_HERO_WS_12 = 420
    WEAPONSET_CREATE_A_HERO_WS_13 = 421
    WEAPONSET_CREATE_A_HERO_WS_14 = 422
    WEAPONSET_CREATE_A_HERO_WS_15 = 423
    WEAPONSET_CREATE_A_HERO_WS_16 = 424
    WEAPONSET_CREATE_A_HERO_WS_17 = 425
    WEAPONSET_CREATE_A_HERO_WS_18 = 426
    WEAPONSET_CREATE_A_HERO_WS_19 = 427
    WEAPONSET_CREATE_A_HERO_WS_20 = 428
    WEAPONSET_CREATE_A_HERO_WS_21 = 429
    WEAPONSET_CREATE_A_HERO_WS_22 = 430
    WEAPONSET_CREATE_A_HERO_WS_23 = 431
    WEAPONSET_CREATE_A_HERO_WS_24 = 432
    WEAPONSET_CREATE_A_HERO_WS_25 = 433
    WEAPONSET_CREATE_A_HERO_WS_26 = 434
    WEAPONSET_CREATE_A_HERO_WS_27 = 435
    WEAPONSET_CREATE_A_HERO_WS_28 = 436
    WEAPONSET_CREATE_A_HERO_WS_29 = 437
    WEAPONSET_CREATE_A_HERO_WS_30 = 438
    WEAPONSET_CREATE_A_HERO_WS_31 = 439
    WEAPONSET_CREATE_A_HERO_WS_32 = 440
    FORMATION_PREVIEW = 441
    SCALING_WALL = 442
    SCALING_WALL_HORDE = 443
    OBSOLETE = 444
    SWAPPING_TO_WEAPONSET_1 = 445
    SWAPPING_TO_WEAPONSET_2 = 446
    SWAPPING_TO_WEAPONSET_3 = 447
    ARMORSET_CREATE_A_HERO_01 = 448
    ARMORSET_CREATE_A_HERO_02 = 449
    ARMORSET_CREATE_A_HERO_03 = 450
    ARMORSET_CREATE_A_HERO_04 = 451
    ARMORSET_CREATE_A_HERO_05 = 452
    ARMORSET_CREATE_A_HERO_06 = 453
    ARMORSET_CREATE_A_HERO_07 = 454
    ARMORSET_CREATE_A_HERO_08 = 455
    ARMORSET_CREATE_A_HERO_09 = 456
    ARMORSET_CREATE_A_HERO_10 = 457
    USER_6 = 458
    USER_7 = 459
    USER_8 = 460
    USER_9 = 461
    USER_10 = 462
    USER_11 = 463
    USER_12 = 464
    USER_13 = 465
    USER_14 = 466
    USER_15 = 467
    USER_16 = 468
    USER_17 = 469
    USER_18 = 470
    USER_19 = 471
    USER_20 = 472
    USER_21 = 473
    USER_22 = 474
    USER_23 = 475
    USER_24 = 476
    USER_25 = 477
    USER_26 = 478
    USER_27 = 479
    USER_28 = 480
    USER_29 = 481
    USER_30 = 482
    USER_31 = 483
    USER_32 = 484
    USER_33 = 485
    USER_34 = 486
    USER_35 = 487
    USER_36 = 488
    USER_37 = 489
    USER_38 = 490
    USER_39 = 491
    USER_40 = 492
    USER_41 = 493
    USER_42 = 494
    USER_43 = 495
    USER_44 = 496
    USER_45 = 497
    USER_46 = 498
    USER_47 = 499
    USER_48 = 500
    USER_49 = 501
    USER_50 = 502
    USER_51 = 503
    USER_52 = 504
    USER_53 = 505
    USER_54 = 506
    USER_55 = 507
    USER_56 = 508
    USER_57 = 509
    USER_58 = 510
    USER_59 = 511
    USER_60 = 512
    USER_61 = 513
    USER_62 = 514
    USER_63 = 515
    USER_64 = 516
    USER_65 = 517
    USER_66 = 518
    USER_67 = 519
    USER_68 = 520
    USER_69 = 521
    USER_70 = 522
    USER_71 = 523
    USER_72 = 524
    USER_73 = 525
    USER_74 = 526
    USER_75 = 527
    EMOTION_BRACE_FOR_BEING_CRUSHED = 528
    PARALYZED = 529
    FIRING_D = 530
    FIRING_E = 531
    BETWEEN_FIRING_SHOTS_D = 532
    BETWEEN_FIRING_SHOTS_E = 533
    RELOADING_D = 534
    RELOADING_E = 535
    PREATTACK_D = 536
    PREATTACK_E = 537
    USING_WEAPON_D = 538
    USING_WEAPON_E = 539
    FIRING_OR_PREATTACK_D = 540
    FIRING_OR_PREATTACK_E = 541
    FIRING_OR_RELOADING_D = 542
    FIRING_OR_RELOADING_E = 543
    BURNINGDEATH = 544
    EMOTION_CHEER_FOR_ABOUT_TO_CRUSH = 545
    INVISIBLE_STEALTH = 546
    INVISIBLE_CAMOUFLAGE = 547
    CREATE_A_HERO_EXAMINE_SELF = 548
    CREATE_A_HERO_EXAMINE_WEAPON_LEF = 549
    CREATE_A_HERO_EXAMINE_WEAPON_RIG = 550
    CREATE_A_HERO_SELECTED_CHEER = 551
    CREATE_A_HERO_IN_CREATION_SCREEN = 552
    WEAPONSET_CREATE_A_HERO_WS_33 = 553
    WEAPONSET_CREATE_A_HERO_WS_34 = 554
    WEAPONSET_CREATE_A_HERO_WS_35 = 555
    WEAPONSET_CREATE_A_HERO_WS_36 = 556
    WEAPONSET_CREATE_A_HERO_WS_37 = 557
    WEAPONSET_CREATE_A_HERO_WS_38 = 558
    WEAPONSET_CREATE_A_HERO_WS_39 = 559
    WEAPONSET_CREATE_A_HERO_WS_40 = 560
    WEAPONSET_CREATE_A_HERO_WS_41 = 561
    WEAPONSET_CREATE_A_HERO_WS_42 = 562
    WEAPONSET_CREATE_A_HERO_WS_43 = 563
    WEAPONSET_CREATE_A_HERO_WS_44 = 564
    WEAPONSET_CREATE_A_HERO_WS_45 = 565
    WEAPONSET_CREATE_A_HERO_WS_46 = 566
    WEAPONSET_CREATE_A_HERO_WS_47 = 567
    WEAPONSET_CREATE_A_HERO_WS_48 = 568
    WEAPONSET_CREATE_A_HERO_WS_49 = 569
    WEAPONSET_CREATE_A_HERO_WS_50 = 570
    WEAPONSET_CREATE_A_HERO_WS_51 = 571
    WEAPONSET_CREATE_A_HERO_WS_52 = 572
    WEAPONSET_CREATE_A_HERO_WS_53 = 573
    WEAPONSET_CREATE_A_HERO_WS_54 = 574
    WEAPONSET_CREATE_A_HERO_WS_55 = 575
    WEAPONSET_CREATE_A_HERO_WS_56 = 576
    WEAPONSET_CREATE_A_HERO_WS_57 = 577
    WEAPONSET_CREATE_A_HERO_WS_58 = 578
    WEAPONSET_CREATE_A_HERO_WS_59 = 579
    WEAPONSET_CREATE_A_HERO_WS_60 = 580
    WEAPONSET_CREATE_A_HERO_WS_61 = 581
    WEAPONSET_CREATE_A_HERO_WS_62 = 582
    WEAPONSET_CREATE_A_HERO_WS_63 = 583
    WEAPONSET_CREATE_A_HERO_WS_64 = 584
    PACKING_TYPE_4 = 585
    PACKING_TYPE_5 = 586
    PACKING_TYPE_6 = 587
    SPECIAL_WEAPON_FOUR = 588
    SPECIAL_WEAPON_FIVE = 589
    SPECIAL_WEAPON_SIX = 590
    AWAY_FROM_TREES = 591
    TAKING_DAMAGE = 592
    HORDEBRAIN_NOT_STEALTHED = 593
    USING_ABILITY = 594


class Dispositions(BFMEEnum):
    # CreateObject.Disposition: several may combine on one line; values are
    # arbitrary (resolution is by name), the names are the engine's set.
    RANDOM_FORCE = 0
    LIKE_EXISTING = 1
    INHERIT_VELOCITY = 2
    ON_GROUND_ALIGNED = 3
    SEND_IT_FLYING = 4
    SEND_IT_OUT = 5
    SEND_IT_UP = 6
    FLOATING = 7
    BUILDING_CHUNKS = 8
    FORWARD_IMPACT = 9
    SPAWN_AROUND = 10
    SET_ANGLE = 11
    FADE_AND_DIE_ORNAMENT = 12
    ANIMATED = 13
    RELATIVE_ANGLE = 14
    USE_WATER_SURFACE = 15
    USE_CLIFF = 16
    ABSOLUTE_ANGLE = 17


class SpecialPowerTriggerPosition(BFMEEnum):
    # The position an `ActivateModuleSpecialPower.TriggerSpecialPower` fires at:
    # the special power's target location, or the casting object's own location.
    TARGETPOS = 0
    OBJECTPOS = 1


class SpecialPowerUnpackConditions(BFMEEnum):
    MOUNTED = 0
    WEAPON_TOGGLE = 1
    MOVING = 2


class SpecialPowerForbiddenUnpackConditions(BFMEEnum):
    MOUNTED = 0


class CreateAtLocation(BFMEEnum):
    CREATE_AT_EDGE_NEAR_SOURCE = 0
    CREATE_AT_EDGE_NEAR_TARGET = 1
    CREATE_AT_EDGE_NEAR_TARGET_AND_MOVE_TO_LOCATION = 2
    CREATE_AT_LOCATION = 3
    USE_OWNER_OBJECT = 4
    CREATE_ABOVE_LOCATION = 5
    CREATE_AT_EDGE_FARTHEST_FROM_TARGET = 6
    CREATE_CLOSEST_TO_SPAWN_POINT = 7
    USE_SECONDARY_OBJECT_LOCATION = 8


class DamageType(BFMEEnum):
    FORCE = 0
    CRUSH = 1
    SLASH = 2
    PIERCE = 3
    SIEGE = 4
    STRUCTURAL = 5
    FLAME = 6
    HEALING = 7
    UNRESISTABLE = 8
    WATER = 9
    PENALTY = 10
    FALLING = 11
    TOPPLING = 12
    REFLECTED = 13
    PASSENGER = 14
    MAGIC = 15
    CHOP = 16
    HERO = 17
    SPECIALIST = 18
    URUK = 19
    HERO_RANGED = 20
    FLY_INTO = 21
    UNDEFINED = 22
    LOGICAL_FIRE = 23
    CAVALRY = 24
    CAVALRY_RANGED = 25
    POISON = 26
    FROST = 27
    GOOD_ARROW_PIERCE = 28
    EVIL_ARROW_PIERCE = 29
    SWORD_SLASH = 30
    WITCH_KING_MORGUL_BLADE = 31
    BALROG_SWORD = 32
    BALROG_WHIP = 33
    ELECTRIC = 34
    GIMLI_LEAP = 35
    BIG_ROCK = 36
    CLUBBING = 37
    BECOME_UNDEAD = 38
    BOLT = 39
    TORNADO = 40
    FLOOD_HORSE = 41
    FIRE3 = 42
    BECOME_UNDEAD_ONCE = 43
    NECRO1 = 44
    NECRO2 = 45
    FIRE = (FLAME, LOGICAL_FIRE)


# DamageFX selectors (`DamageFXType`) are keyed by the same engine names.
DamageFXTypes = DamageType


class DeathType(BFMEEnum):
    NORMAL = 0
    NONE = 1
    CRUSHED = 2
    BURNED = 3
    EXPLODED = 4
    POISONED = 5
    TOPPLED = 6
    FLOODED = 7
    SUICIDED = 8
    LASERED = 9
    DETONATED = 10
    SPLATTED = 11
    POISONED_BETA = 12
    EXTRA_2 = 13
    EXTRA_3 = 14
    EXTRA_4 = 15
    EXTRA_5 = 16
    EXTRA_6 = 17
    EXTRA_7 = 18
    EXTRA_8 = 19
    KNOCKBACK = 20
    SUPERNATURAL = 21
    FADED = 22
    SLAUGHTERED = 23


class HealthRatioType(BFMEEnum):
    SAME_CURRENTHEALTH = 0
    PRESERVE_RATIO = 1
    ADD_CURRENT_HEALTH_TOO = 2


class ObjectStatus(BFMEEnum):
    DESTROYED = 0
    CAN_ATTACK = 1
    UNDER_CONSTRUCTION = 2
    UNSELECTABLE = 3
    NO_COLLISIONS = 4
    NO_ATTACK = 5
    AIRBORNE_TARGET = 6
    PARACHUTING = 7
    REPULSOR = 8
    HIJACKED = 9
    AFLAME = 10
    BURNED = 11
    WET = 12
    IS_FIRING_WEAPON = 13
    IS_BRAKING = 14
    STEALTHED = 15
    HIDDEN = 16
    DETECTED = 17
    CAN_STEALTH = 18
    SOLD = 19
    UNDERGOING_REPAIR = 20
    RECONSTRUCTING = 21
    IS_ATTACKING = 22
    NO_AUTO_ACQUIRE = 23
    USING_ABILITY = 24
    IS_AIMING_WEAPON = 25
    NO_ATTACK_FROM_AI = 26
    IGNORING_STEALTH = 27
    IS_MELEE_ATTACKING = 28
    GUARD_SELECTION = 29
    LEASHED_RETURNING = 30
    DEATH_1 = 31
    DEATH_2 = 32
    DEATH_3 = 33
    DEATH_4 = 34
    DEATH_5 = 35
    CONTESTED = 36
    CONTESTING_BUILDING = 37
    HORDE_MEMBER = 38
    RIDERLESS = 39
    RIDER_IS_PILOT = 40
    RIDER1 = 41
    RIDER2 = 42
    RIDER3 = 43
    RIDER4 = 44
    RIDER5 = 45
    RIDER6 = 46
    RIDER7 = 47
    RIDER8 = 48
    IMMOBILE = 49
    FLEE_OFF_MAP = 50
    NOT_IN_WORLD = 51
    INAUDIBLE = 52
    CHANTING = 53
    ENRAGED = 54
    CREATE_DRAWABLE_WITH_LOW_DETAIL = 55
    SINKING = 56
    RAMPAGING = 57
    INSIDE_GARRISON = 58
    DEPLOYED = 59
    UNATTACKABLE = 60
    ENCLOSED = 61
    TEMPORARILY_DEFECTED = 62
    TAGGED = 63
    DEPLOYING = 64
    BLOODTHIRSTY = 65
    PORTER_TAGGED = 66
    GRAB_AND_DROP = 67
    STAND_GROUND = 68
    UNCONTROLLABLY_SCARED = 69
    SPECIAL_ABILITY_PACKING_UNPACKING = 70
    PLEASE_EAT_ME = 71
    UPDATING_AI = 72
    HUNT_WHEN_IDLE = 73
    IGNORE_AI_COMMAND = 74
    RUNNING_DOWN_FROM_BEHIND = 75
    DO_NOT_SCORE = 76
    CAN_NOT_WALK_ON = 77
    MARCH_OF_DEATH = 78
    DO_NOT_PICK_ME = 79
    INHERITED_FROM_ALLY_TEAM = 80
    SWITCHED_WEAPONS = 81
    END_FIRE_STATE = 82
    BOOKENDING = 83
    ELVISH_EXPRESSLY = 84
    INSIDE_CASTLE = 85
    BUILD_BEING_CANCELED = 86
    PENDING_CONSTRUCTION = 87
    PHANTOM_STRUCTURE = 88
    IN_FORMATION_TEMPLATE = 89
    IS_LEAVING_FACTORY = 90
    MOVING_TO_DISMOUNT = 91
    NO_HERO_PROPERTIES = 92
    CAN_ENTER_ANYTHING = 93
    HOLDING_THE_RING = 94
    INVISIBLE_DETECTED_BY_FRIEND = 95
    INVISIBLE_DETECTED = 96
    WORKER_REPAIRING = 97
    ATTACHED = 98
    WONT_RIDE_WITH_YOU = 99
    COMMAND_BUTTON_TOGGLED = 100
    IGNORE_PARALYZE_NUGGET = 101
    SUMMONING_REPLACEMENT = 102
    HOLDING_THE_SHARD = 103
    USER_DEFINED_1 = 104
    USER_DEFINED_2 = 105


class ParticleSysBonePersist(BFMEEnum):
    NONE = 0
    HOLD = 1
    KILL = 2
    SPAWN = 3


class SpecialPowerType(BFMEEnum):
    SPECIAL_INVALID = 0
    SPECIAL_DAISY_CUTTER = 1
    SPECIAL_PARADROP_AMERICA = 2
    SPECIAL_CARPET_BOMB = 3
    SPECIAL_CLUSTER_MINES = 4
    SPECIAL_UP_FOR_GRABS_2 = 5
    SPECIAL_UP_FOR_GRABS_3 = 6
    SPECIAL_UP_FOR_GRABS_4 = 7
    SPECIAL_NEUTRON_MISSILE = 8
    SPECIAL_UP_FOR_GRABS = 9
    SPECIAL_DEFECTOR = 10
    SPECIAL_TERROR_CELL = 11
    SPECIAL_AMBUSH = 12
    SPECIAL_BLACK_MARKET_NUKE = 13
    SPECIAL_ANTHRAX_BOMB = 14
    SPECIAL_SCUD_STORM = 15
    SPECIAL_PRINCE_OF_DOL_ARMOTH = 16
    SPECIAL_CRATE_DROP = 17
    SPECIAL_A10_THUNDERBOLT_STRIKE = 18
    SPECIAL_DETONATE_DIRTY_NUKE = 19
    SPECIAL_ARTILLERY_BARRAGE = 20
    SPECIAL_MISSILE_DEFENDER_LASER_GUIDED_MISSILES = 21
    SPECIAL_REMOTE_CHARGES = 22
    SPECIAL_TIMED_CHARGES = 23
    SPECIAL_HACKER_DISABLE_BUILDING = 24
    SPECIAL_TANKHUNTER_TNT_ATTACK = 25
    SPECIAL_BLACKLOTUS_CAPTURE_BUILDING = 26
    SPECIAL_MAN_THE_WALLS = 27
    SPECIAL_OSGILIATH_VETERANS = 28
    SPECIAL_INFANTRY_CAPTURE_BUILDING = 29
    SPECIAL_RADAR_VAN_SCAN = 30
    SPECIAL_SPY_DRONE = 31
    SPECIAL_DISGUISE_AS_VEHICLE = 32
    SPECIAL_REPAIR_VEHICLES = 33
    SPECIAL_PARTICLE_UPLINK_CANNON = 34
    SPECIAL_RANGER_AMBUSH = 35
    SPECIAL_CHANGE_BATTLE_PLANS = 36
    SPECIAL_CIA_INTELLIGENCE = 37
    SPECIAL_CLEANUP_AREA = 38
    SPECIAL_GRAB_PASSENGER = 39
    SPECIAL_GRAB_CHUNK = 40
    SPECIAL_SPAWN_ORCS = 41
    SPECIAL_CHARGE_ATTACK = 42
    SPECIAL_PART_THE_HEAVENS = 43
    SPECIAL_DEFLECT_PROJECTILES = 44
    SPECIAL_SIEGEDEPLOY = 45
    SPECIAL_STOP = 46
    SPECIAL_ARROW_STORM = 47
    SPECIAL_SWOOP_ATTACK = 48
    SPECIAL_LEVEL_ATTACK = 49
    SPECIAL_LEVEL_POSITION = 50
    SPECIAL_GIVE_UPGRADE = 51
    SPECIAL_ROUSING_SPEECH = 52
    SPECIAL_GENERAL_TARGETLESS = 53
    SPECIAL_GENERAL_TARGETLESS_TWO = 54
    SPECIAL_SHIELD_BUBBLE = 55
    SPECIAL_TOGGLE_MOUNTED = 56
    SPECIAL_WIZARD_BLAST = 57
    SPECIAL_GLORIOUS_CHARGE = 58
    SPECIAL_WOUND_ARROW = 59
    SPECIAL_HERO_MODE = 60
    SPECIAL_FLAMING_SWORD = 61
    SPECIAL_FIRE_WHIP = 62
    SPECIAL_BALROG_BREATH = 63
    SPECIAL_MTTROLL_BORED = 64
    SPECIAL_BALROG_WINGS = 65
    SPECIAL_BALROG_SCREAM = 66
    SPECIAL_TRAINING = 67
    SPECIAL_TELEKENETIC_PUSH = 68
    SPECIAL_SONIC_SONG = 69
    SPECIAL_REVEAL_MAP_AREA = 70
    SPECIAL_KNIFE_ATTACK = 71
    SPECIAL_SPAWN_OATHBREAKERS = 72
    SPECIAL_CALL_OF_THE_DEEP = 73
    SPECIAL_SKULL_TOTEM = 74
    SPECIAL_EXTINGUISH_FIRE = 75
    SPECIAL_TRIGGER_ATTRIBUTE_MODIFIER = 76
    SPECIAL_DOMINATE_ENEMY = 77
    SPECIAL_WORD_OF_POWER = 78
    SPECIAL_KNIFE_FIGHTER = 79
    SPECIAL_SPELL_BOOK_HEAL = 80
    SPECIAL_SPELL_BOOK_ELVEN_GIFTS = 81
    SPECIAL_SPELL_BOOK_SPAWN_LONE_TOWER = 82
    SPECIAL_SPELL_BOOK_ENSHROUDING_MIST = 83
    SPECIAL_SPELL_BOOK_RALLYING_CALL = 84
    SPECIAL_SPELL_BOOK_TOM_BOMBADIL = 85
    SPECIAL_SPELL_BOOK_HOBBIT_ALLIES = 86
    SPECIAL_SPELL_BOOK_REBUILD = 87
    SPECIAL_SPELL_BOOK_ARROW_VOLLEY_GOOD = 88
    SPECIAL_SPELL_BOOK_ELVEN_WOOD = 89
    SPECIAL_SPELL_BOOK_DWARVEN_RICHES = 90
    SPECIAL_SPELL_BOOK_MEN_OF_DALE_ALLIES = 91
    SPECIAL_SPELL_BOOK_CLOUD_BREAK = 92
    SPECIAL_SPELL_BOOK_ROHAN_ALLIES = 93
    SPECIAL_SPELL_BOOK_DUNEDAIN_ALLIES = 94
    SPECIAL_SPELL_BOOK_ENT_ALLIES = 95
    SPECIAL_SPELL_BOOK_EAGLE_ALLIES = 96
    SPECIAL_SPELL_BOOK_UNDERMINE = 97
    SPECIAL_SPELL_BOOK_BOMBARD = 98
    SPECIAL_SPELL_BOOK_ARMY_OF_THE_DEAD = 99
    SPECIAL_SPELL_BOOK_EARTHQUAKE = 100
    SPECIAL_SPELL_BOOK_FLOOD = 101
    SPECIAL_SPELL_BOOK_SUNFLARE = 102
    SPECIAL_SPELL_BOOK_CITADEL = 103
    SPECIAL_SPELL_BOOK_TAINT = 104
    SPECIAL_SPELL_BOOK_EYE_OF_SAURON = 105
    SPECIAL_SPELL_BOOK_BARRICADE = 106
    SPECIAL_SPELL_BOOK_WAR_CHANT = 107
    SPECIAL_SPELL_BOOK_PALANTIR_VISION = 108
    SPECIAL_SPELL_BOOK_CREBAIN = 109
    SPECIAL_SPELL_BOOK_CAVE_BATS = 110
    SPECIAL_SPELL_BOOK_INDUSTRY = 111
    SPECIAL_SPELL_BOOK_DEVASTATION = 112
    SPECIAL_SPELL_BOOK_UNTAMED_ALLEGIANCE = 113
    SPECIAL_SPELL_BOOK_ARROW_VOLLEY_EVIL = 114
    SPECIAL_SPELL_BOOK_WILD_MEN_ALLIES = 115
    SPECIAL_SPELL_BOOK_SCAVENGER = 116
    SPECIAL_SPELL_BOOK_CALL_THE_HORDE = 117
    SPECIAL_SPELL_BOOK_SPIDERLING_ALLIES = 118
    SPECIAL_SPELL_BOOK_DARKNESS = 119
    SPECIAL_SPELL_BOOK_AWAKEN_WYRM = 120
    SPECIAL_SPELL_BOOK_FREEZING_RAIN = 121
    SPECIAL_SPELL_BOOK_FUEL_THE_FIRES = 122
    SPECIAL_SPELL_BOOK_WATCHER_ALLY = 123
    SPECIAL_SPELL_BOOK_BALROG_ALLY = 124
    SPECIAL_SPELL_BOOK_RAIN_OF_FIRE = 125
    SPECIAL_SPELL_BOOK_DRAGON_ALLY = 126
    SPECIAL_SPELL_BOOK_DRAGON_STRIKE = 127
    SPECIAL_ATHELAS = 128
    SPECIAL_AT_VISIBLE_OBJECT = 129
    SPECIAL_SARUMAN_FIRE_BALL = 130
    SPECIAL_DISGUISE = 131
    SPECIAL_SMITE_CANCELDISGUISE = 132
    SPECIAL_ATTRIBUTEMOD_CANCELDISGUISE = 133
    SPECIAL_KINGS_FAVOR = 134
    SPECIAL_FAKE_LEADERSHIP_BUTTON = 135
    SPECIAL_GIVE_UPGRADE_NEAREST = 136
    SPECIAL_SCREECH = 137
    SPECIAL_REPAIR_STRUCTURE = 138
    SPECIAL_EAT = 139
    SPECIAL_GIMLI_LEAP = 140
    SPECIAL_HARVEST = 141
    SPECIAL_PERSONAL_FLOOD = 142
    SPECIAL_ELVEN_GRACE = 143
    SPECIAL_AT_VISIBLE_GROUNDED_OBJECT = 144
    SPECIAL_TELEPORT_TEAM_TO_CASTER = 145
    SPECIAL_SPAWN_TORNADO = 146
    SPECIAL_CURSE_ENEMY = 147
    SPECIAL_STORE_LIST_1 = 148
    SPECIAL_STORE_LIST_2 = 149
    SPECIAL_TELEPORT_LIST_TO_POSITION = 150
    SPECIAL_EVACUATE_GARRISON = 151
    SPECIAL_GENERAL_TARGETLESS_THREE = 152
    SPECIAL_SUMMON_ALLIES = 153
    SPECIAL_SPELL_BOOK_GENERAL_SUMMON = 154
    SPECIAL_SPELL_BOOK_BLIGHT = 155
    SPECIAL_SPELL_BOOK_SNOWBIND = 156
    SPECIAL_SPELL_BOOK_CHILL_WIND = 157
    SPECIAL_AOE_ATTACK_HEAL = 158


class TimeOfDay(BFMEEnum):
    NONE = 0
    MORNING = 1
    AFTERNOON = 2
    EVENING = 3
    NIGHT = 4
    INTERPOLATE = 5


class WeatherFlag(BFMEEnum):
    RAINY = 0
    CLOUDYRAINY = 1
    SUNNY = 2
    CLOUDY = 3
    NORMAL = 4
    SNOWY = 5


class RadarPriority(BFMEEnum):
    INVALID = 0
    NOT_ON_RADAR = 1
    UNIT = 2
    STRUCTURE = 3
    LOCAL_UNIT_ONLY = 4


class EditorSorting(BFMEEnum):
    STRUCTURE = 0
    UNIT = 1
    MISC_MAN_MADE = 2
    MISC_NATURAL = 3
    SHRUBBERY = 4
    AUDIO = 5
    DEBRIS = 6
    SYSTEM = 7
    OBSOLETE = 8
    SELECTABLE = 9
    EMITTERS = 10


class ButtonBorderTypes(BFMEEnum):
    """`CommandButton.ButtonBorderType`; OpenSAGE set. `NONE` maps to `None` via
    the metaclass.
    """

    NONE = enum.auto()
    ACTION = enum.auto()
    BUILD = enum.auto()
    UPGRADE = enum.auto()
    SYSTEM = enum.auto()


class LocomotorSetType(BFMEEnum):
    """Locomotor-set selector (`SET_NORMAL`, `SET_MOUNTED`, ...); OpenSAGE set."""

    SET_NORMAL = 0
    SET_NORMAL_UPGRADED = 1
    SET_FREEFALL = 2
    SET_WANDER = 3
    SET_PANIC = 4
    SET_TAXIING = 5
    SET_SUPERSONIC = 6
    SET_SLUGGISH = 7
    SET_ENRAGED = 8
    SET_SCARED = 9
    SET_MOUNTED = 10
    SET_COMBO = 11
    SET_CONTAINED = 12
    SET_BURNINGDEATH = 13


class WeaponPrefireType(BFMEEnum):
    """Weapon.PreAttackType: when the pre-attack delay is applied.

    The engine reads the type from the first token and ignores the rest of the
    line, so a trailing marker - seen in the corpus as ``PreAttackType =
    PER_SHOT *`` - is valid and resolves to the leading member.
    """

    PER_ATTACK = 0  # delay each time a new target is attacked
    PER_CLIP = 1  # delay after every clip reload
    PER_SHOT = 2  # delay before every single shot
    PER_POSITION = 3

    @classmethod
    def convert(cls, parser, name):
        token = name.split(maxsplit=1)[0] if isinstance(name, str) and name.split() else name
        return cls[_unprefixed(token)]


class WeaponReloadType(BFMEEnum):
    """`Weapon.AutoReloadsClip`: whether a clip auto-reloads (`Yes`/`No`), or the unit must
    `RETURN_TO_BASE` to reload. Member names match the engine's INI tokens."""

    No = 0
    Yes = 1
    RETURN_TO_BASE = 2


class AutoAcquireEnemiesType(BFMEEnum):
    """`AutoAcquireEnemiesWhenIdle` qualifiers; OpenSAGE set."""

    YES = enum.auto()
    NO = enum.auto()
    ATTACK_BUILDINGS = enum.auto()
    NotWhileAttacking = enum.auto()
    STEALTHED = enum.auto()


# `AutoAcquireEnemiesWhenIdle` lists these qualifiers.
AllowedWhenConditions = AutoAcquireEnemiesType


# Open, data-extensible set: the engine accepts modder-defined tokens, so it
# accepts any name and keeps it as the raw value (a closed member list would
# reject legitimate corpus/mod values).
class Stances(FakeEnum):
    """Unit-stance identifiers a command button cycles through."""


class Options(BFMEEnum):
    """`CommandButton.Options` flags, resolved by name; the OpenSAGE
    `CommandButtonOption` set across Generals/ZH and BFME 1/2 (a field lists any
    number of these tokens).
    """

    OK_FOR_MULTI_SELECT = enum.auto()
    CHECK_LIKE = enum.auto()
    NEED_TARGET_ENEMY_OBJECT = enum.auto()
    NEED_TARGET_NEUTRAL_OBJECT = enum.auto()
    NEED_TARGET_ALLY_OBJECT = enum.auto()
    CONTEXTMODE_COMMAND = enum.auto()
    OPTION_ONE = enum.auto()
    OPTION_TWO = enum.auto()
    OPTION_THREE = enum.auto()
    NEED_TARGET_POS = enum.auto()
    NOT_QUEUEABLE = enum.auto()
    IGNORES_UNDERPOWERED = enum.auto()
    NEED_SPECIAL_POWER_SCIENCE = enum.auto()
    SCRIPT_ONLY = enum.auto()
    NEED_UPGRADE = enum.auto()
    USES_MINE_CLEARING_WEAPONSET = enum.auto()
    CAN_USE_WAYPOINTS = enum.auto()
    MUST_BE_STOPPED = enum.auto()
    TOGGLE_IMAGE_ON_FORMATION = enum.auto()
    TOGGLE_IMAGE_ON_WEAPONSET = enum.auto()
    ALLOW_SHRUBBERY_TARGET = enum.auto()
    ALLOW_ROCK_TARGET = enum.auto()
    NONPRESSABLE = enum.auto()
    CANCELABLE = enum.auto()
    UNMOUNTED_ONLY = enum.auto()
    MOUNTED_ONLY = enum.auto()
    ON_GROUND_ONLY = enum.auto()
    HIDE_WHILE_DISABLED = enum.auto()
    NO_PLAY_UNIT_SPECIFIC_SOUND_FOR_AUTO_ABILITY = enum.auto()
    TOGGLE_IMAGE_ON_WEAPON = enum.auto()
    NEEDS_CASTLE_KINDOF = enum.auto()
    OK_FOR_MULTI_EXECUTE = enum.auto()


class UpgradeTypes(BFMEEnum):
    OBJECT = 0
    PLAYER = 1


class Descriptors(BFMEEnum):
    ANY = 0
    NONE = 1
    ALL = 2


class Relations(BFMEEnum):
    ENEMIES = 0
    ALLIES = 1
    SAME_PLAYER = 2
    NEUTRAL = 3
    SELF = 4
    SUICIDE = 5


class WeaponCollideTypes(BFMEEnum):
    """What a weapon's projectile collides with (`Weapon.ProjectileCollidesWith`).

    A flag set: each token is one collision class and a field lists every class
    the projectile stops on. `NONE` resolves to `None` via the metaclass.
    """

    STRUCTURES = 0
    WALLS = 1
    ENEMIES = 2
    SHRUBBERY = 3
    ALLIES = 4
    NEUTRAL = 5
    MONSTERS = 6


class ObjectFilterRules(BFMEEnum):
    """The relation/quality flags an object filter accepts (`RadiusDamageAffects`).

    An engine-fixed set (the parser rejects anything else), distinct from
    :class:`Relations`. ``NEUTRAL`` and ``NEUTRALS`` are the same rule.
    """

    ALL = 0
    NONE = 1
    ANY = 2
    ALLIES = 3
    ENEMIES = 4
    NEUTRAL = 5
    NEUTRALS = 5
    NOT_SIMILAR = 6
    SELF = 7
    SUICIDE = 8
    NOT_AIRBORNE = 9
    SAME_HEIGHT_ONLY = 10
    MINES = 11
    SAME_PLAYER = 12


class ModifierCategories(BFMEEnum):
    LEADERSHIP = 0
    FORMATION = 1
    SPELL = 2
    WEAPON = 3
    STRUCTURE = 4
    LEVEL = 5
    BUFF = 6
    DEBUFF = 7
    STUN = 8
    INNATE_ARMOR = 9
    INNATE_DAMAGEMULT = 10
    INNATE_VISION = 11
    INNATE_AUTOHEAL = 12
    INNATE_HEALTH = 13


class AudioTypeFlags(CaseInsensitiveEnum):
    NONE = 0

    UI = 1
    WORLD = 2
    SHROUDED = 4
    VOICE = 8
    PLAYER = 16
    ALLIES = 32
    ENEMIES = 64
    EVERYONE = 128
    DEFAULT = 256
    GLOBAL = 512
    FAKE = 1024


class AudioVolumeSlider(CaseInsensitiveEnum):
    SOUNDFX = "SOUNDFX"
    VOICE = "VOICE"
    MUSIC = "MUSIC"
    AMBIENT = "AMBIENT"
    MOVIE = "MOVIE"
    NONE = "None"


class AudioControlFlags(CaseInsensitiveEnum):
    NONE = 0

    LOOP = 1 << 0
    SEQUENTIAL = 1 << 1
    RANDOMSTART = 1 << 2
    INTERRUPT = 1 << 3
    FADE_ON_KILL = 1 << 4
    FADE_ON_START = 1 << 5

    ALLOW_KILL_MID_FILE = 1 << 6

    ALL = 1 << 7
    RANDOM = 1 << 8
    PLAY_ONE = 1 << 9


class AudioPriority(CaseInsensitiveEnum):
    """An audio event's `Priority` - how readily the mixer drops it when channels run short.
    The corpus writes these upper-cased; the engine tokens are lower-case, so match either."""

    LOWEST = enum.auto()
    LOW = enum.auto()
    NORMAL = enum.auto()
    HIGH = enum.auto()
    CRITICAL = enum.auto()


class ParticleSystemPriority(BFMEEnum):
    """An FX particle system's render `Priority` (also `DynamicGameLOD.MinParticle*Priority`):
    which systems survive when the particle budget is cut."""

    NONE = 0
    WEAPON_EXPLOSION = 1
    WEAPON_EXPLSION = 1  # engine-side misspelling, kept as an alias
    SCORCHMARK = 2
    DUST_TRAIL = 3
    BUILDUP = 4
    DEBRIS_TRAIL = 5
    UNIT_DAMAGE_FX = 6
    DEATH_EXPLOSION = 7
    SEMI_CONSTANT = 8
    CONSTANT = 9
    WEAPON_TRAIL = 10
    AREA_EFFECT = 11
    CRITICAL = 12
    ALWAYS_RENDER = 13
    ULTRA_HIGH_ONLY = 14
    HIGH_OR_ABOVE = 15
    MEDIUM_OR_ABOVE = 16
    LOW_OR_ABOVE = 17
    VERY_LOW_OR_ABOVE = 18


class ParticleSystemShader(BFMEEnum):
    """The blend mode a particle system's `Shader` draws with."""

    NONE = enum.auto()
    ADDITIVE = enum.auto()
    ALPHA = enum.auto()
    ALPHA_TEST = enum.auto()
    MULTIPLY = enum.auto()
    W3D_EMISSIVE = enum.auto()
    W3D_ALPHA = enum.auto()
    W3D_DIFFUSE = enum.auto()


class DamageFXType(BFMEEnum):
    """The damage flavour a damage nugget reports as its `DamageFXType`, selecting which hit
    FX play."""

    MAGIC = enum.auto()
    SWORD_SLASH = enum.auto()
    EVIL_ARROW_PIERCE = enum.auto()
    CLUBBING = enum.auto()
    SMALL_ROCK = enum.auto()
    BIG_ROCK = enum.auto()
    FLAME = enum.auto()
    ELECTRIC = enum.auto()
    BALROG_SWORD = enum.auto()
    GOOD_ARROW_PIERCE = enum.auto()
    REFLECTED = enum.auto()
    GIMLI_LEAP = enum.auto()
    WITCH_KING_MORGUL_BLADE = enum.auto()
    STRUCTURAL = enum.auto()
    BALROG_WHIP = enum.auto()
    POISON = enum.auto()
    BOLT = enum.auto()
    TORNADO = enum.auto()
    FIRE1 = enum.auto()
    FIRE2 = enum.auto()
    FIRE3 = enum.auto()
    FLOOD_HORSE = enum.auto()
    UNDEFINED = enum.auto()
    NECRO1 = enum.auto()
    NECRO2 = enum.auto()


class ObjectShadowType(BFMEEnum):
    """How an object casts its `Shadow` - volume, decal, or one of the non-self/alpha variants."""

    NONE = enum.auto()
    SHADOW_VOLUME = enum.auto()
    SHADOW_DECAL = enum.auto()
    SHADOW_VOLUME_NON_SELF_1 = enum.auto()
    SHADOW_VOLUME_NON_SELF_2 = enum.auto()
    SHADOW_VOLUME_NEW = enum.auto()
    SHADOW_ADDITIVE_DECAL = enum.auto()
    SHADOW_ADDITIVE_DECAL_DYNAMIC = enum.auto()
    SHADOW_VOLUME_NON_SELF_3 = enum.auto()
    SHADOW_ALPHA_DECAL_DYNAMIC = enum.auto()
    SHADOW_ALPHA_DECAL = enum.auto()


class VeterancyLevel(BFMEEnum):
    """A unit experience tier, e.g. a `CrateData.VeterancyLevel` award."""

    REGULAR = enum.auto()
    VETERAN = enum.auto()
    ELITE = enum.auto()
    HEROIC = enum.auto()


class BodyDamageType(BFMEEnum):
    """A body's visible damage state (`GameData.MovementPenaltyDamageState`)."""

    PRISTINE = enum.auto()
    DAMAGED = enum.auto()
    REALLYDAMAGED = enum.auto()
    RUBBLE = enum.auto()


class TerrainLod(BFMEEnum):
    """`GameData.TerrainLOD` - the engine only recognises `DISABLE` here."""

    DISABLE = enum.auto()


class MapWeatherType(BFMEEnum):
    """`GameData.Weather` - the map's base weather."""

    NORMAL = enum.auto()
    SNOWY = enum.auto()


class SubsystemLoader(BFMEEnum):
    """A `LoadSubsystem.Loader` strategy; only the `INI` loader exists."""

    INI = enum.auto()


class AcademyType(BFMEEnum):
    """A `SpecialPower.AcademyClassify` advice category for the academy/tutorial hint system."""

    ACT_SUPERPOWER = enum.auto()
    ACT_UPGRADE_RADAR = enum.auto()


class DistributionType(BFMEEnum):
    """The distribution of a `RandomVariable`'s draw between its low and high bounds; absent,
    the engine defaults to `UNIFORM`."""

    CONSTANT = enum.auto()
    UNIFORM = enum.auto()
