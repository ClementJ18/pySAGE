# Field annotations are the typed converter aliases from sage_ini/model/types.py
# (`Annotated[PyType, converter]`): a checker reads each field's value type, while the
# converter runs at access time (see resolve_annotation).
# Module aliases (`e`, `t`, `io`, `obj`) qualify a type whose name a field shadows
# (`Cursor: t.Cursor`, `Upgrade: io.Upgrade`); `io` is this module, for its own classes.
import sage_ini.model.enums as e
import sage_ini.model.ini_objects as io
import sage_ini.model.objects as obj
import sage_ini.model.types as t
from sage_ini.model.data_blocks import PlayerAIType
from sage_ini.model.enums import (
    ArmorSetFlags,
    ButtonBorderTypes,
    CommandTypes,
    Dispositions,
    EmotionNuggetAIState,
    EmotionTypes,
    FactionSide,
    FakeEnum,
    GeometryType,
    KindOf,
    LocomotorSetType,
    ModelCondition,
    ModifierCategories,
    SlotTypes,
    SpecialPowerType,
    UpgradeTypes,
    WeaponCollideTypes,
    WeaponPrefireType,
    WeaponsetFlags,
)
from sage_ini.model.nuggets import WEAPON_NUGGETS
from sage_ini.model.objects import Draw, IniObject, MarkerGroup, NestedAttribute, Nugget
from sage_ini.model.types import (
    RGB,
    RGBA,
    Bone,
    Bool,
    ContactPoint,
    Coords,
    CoordsList,
    Cursor,
    EvaEvent,
    FlagList,
    Float,
    FXList,
    Image,
    Int,
    Label,
    List,
    ModifierEntry,
    Nullable,
    ObjectFilter,
    Opaque,
    RangeDuration,
    RawList,
    ScienceRequirements,
    Sound,
    TimedPosition,
    Tuple,
    Union,
    Untyped,
    UpgradeWithDelay,
    to_number,
)


class Upgrade(IniObject):
    key = "upgrades"

    Type: UpgradeTypes
    GroupName: t.String
    GroupOrder: Int
    UpgradeFX: Opaque
    UnitSpecificSound: Untyped
    DisplayName: Label
    BuildTime: Int = 0
    BuildCost: Int = 0
    ButtonImage: Image
    Tooltip: Label
    Cursor: t.Cursor
    PersistsInCampaign: Bool = False
    LocalPlayerGainsUpgradeEvaEvent: EvaEvent
    LocalPlayerLosesUpgradeEvaEvent: EvaEvent
    AlliedPlayerGainsUpgradeEvaEvent: EvaEvent
    EnemyPlayerGainsUpgradeEvaEvent: EvaEvent
    AlliedPlayerLosesUpgradeEvaEvent: EvaEvent
    EnemyPlayerLosesUpgradeEvaEvent: EvaEvent
    AcademyClassify: FakeEnum
    NoUpgradeDiscount: Bool = False
    UseObjectTemplateForCostDiscount: "Object"
    SkirmishAIHeuristic: FakeEnum
    ResearchCompleteEvaEvent: EvaEvent
    ResearchSound: Sound
    RequiredObjectFilter: ObjectFilter
    StrategicIcon: Image
    SubUpgradeTemplateNames: List["Upgrade"] = []


class FloodMember(IniObject):
    MemberTemplateName: "Object"
    ControlPointOffsetOne: Coords
    ControlPointOffsetTwo: Coords
    ControlPointOffsetThree: Coords
    ControlPointOffsetFour: Coords
    MemberSpeed: Float


class ReplaceObject(IniObject):
    TargetObjectFilter: ObjectFilter
    ReplacementObjectName: List["Object"]


class TurretModule(IniObject):
    pass


class Armor(IniObject):
    key = "armorsets"

    Armor: List[Untyped]  # `<DamageType> <scalar%>`, one per repeat
    FlankedPenalty: Float = 0
    DamageScalar: Float = 1

    def damage_scalars(self) -> dict[str, float]:
        """`DamageType` name -> multiplier, from the repeated `Armor = TYPE pct` lines
        (`DEFAULT` applies to any type not listed)."""
        raw = self._fields.get("Armor", [])
        if isinstance(raw, str):
            raw = [raw]
        scalars: dict[str, float] = {}
        for entry in raw:
            parts = entry.split()
            if len(parts) >= 2:
                scalars[parts[0]] = to_number(parts[1])
        return scalars

    def get_damage_scalar(self, d_type, flanked=False) -> float:
        """Fraction of a `d_type` hit this armor lets through (1.0 = full damage)."""
        scalars = self.damage_scalars()
        value = scalars.get(d_type.name, scalars.get("DEFAULT", 1.0))
        if flanked:
            value += value * self.FlankedPenalty
        return value


class SpecialPower(IniObject):
    key = "specialpowers"

    Enum: SpecialPowerType
    InitiateSound: Sound
    PreventActivationConditions: Untyped
    SharedSyncedTimer: Bool
    EvaEventToPlayOnSuccess: Opaque
    UnitSpecificSoundToUseAsInitiateIntendToDoVoice: Opaque
    UnitSpecificSoundToUseAsEnterStateInitiateIntendToDoVoice: Opaque
    ReloadTime: Int
    PublicTimer: Bool = False
    Flags: List[FakeEnum]
    RequiredSciences: ScienceRequirements
    InitiateAtLocationSound: Sound
    ViewObjectDuration: Float
    ViewObjectRange: Float
    RadiusCursorRadius: Float
    MaxCastRange: Float
    ForbiddenObjectFilter: t.ObjectFilter
    ForbiddenObjectRange: Float
    ObjectFilter: t.ObjectFilter
    AcademyClassify: e.AcademyType
    PalantirMovie: t.Opaque
    RequiredScience: t.Opaque
    ShortcutPower: t.Bool
    UnitCost: t.Int
    UnitCostDeathType: t.Int


class Science(IniObject):
    key = "sciences"

    PrerequisiteSciences: ScienceRequirements
    SciencePurchasePointCost: Int = 0
    SciencePurchasePointCostMP: Int = 0
    IsGrantable: Bool = False
    SciencePurchasePoIntCostMP: Int = 0
    Description: t.Label
    DisplayName: t.Label

    def is_unlocked(self, *sciences):
        """True when any prerequisite group is fully held by `sciences`."""
        return any(all(x in sciences for x in preq) for preq in self.PrerequisiteSciences)


class AttackPriority(IniObject):
    """An `AttackPriority` table: a `Default` weight plus per-object `Target` weightings the AI
    uses to choose what to attack first. (Edain marks every block OUTDATED, leaving only
    `Default`, but the engine still parses the `Target` list.)"""

    key = "attackpriorities"

    Default: Int
    Target: t.AttackPriorityTarget


class FCurve(NestedAttribute):
    """An animated value curve (`Radius`/`Opacity`/`Angle` of a `PartTheHeavensUpdate`): a list
    of `Key` keyframes, with optional `InPadding`/`OutPadding` describing how the curve behaves
    before the first and after the last key (`HOLD`, `CYCLE`, …)."""

    InPadding: Untyped
    OutPadding: Untyped
    Key: t.FCurveKey


class CreateObject(IniObject):
    key = None

    ObjectNames: List["Object"]
    IgnoreCommandPointLimit: Bool
    Disposition: List[Dispositions]
    Count: Int
    UseJustBuiltFlag: Bool
    JustBuiltDuration: Int
    StartingBusyTime: Int
    ClearRemovables: Bool
    FadeIn: Bool
    FadeTime: Int
    RequiredUpgrades: List[Upgrade]
    Offset: Coords
    DispositionAngle: Float
    SpreadFormation: Bool
    MinDistanceAFormation: Float
    MinDistanceBFormation: Float
    MaxDistanceFormation: Float
    OrientInSecondaryDirection: Bool
    OrientationOffset: Float
    IssueMoveAfterCreation: Bool
    IgnoreAllObjects: Bool
    DispositionIntensity: Float
    VelocityScale: Float
    InvulnerableTime: Int
    InheritAttributesFromSource: Bool
    RequiresLivePlayer: Bool
    InheritScriptingName: Bool
    OrientInPrimaryDirection: Bool
    OffsetInLocalSpace: Bool
    PreserveLayer: Bool
    MoveUsesStrafeUpdate: Bool
    ParticleSystem: Opaque
    ForbiddenUpgrades: List[Opaque]
    DestinationPlayer: Opaque
    WaypointSpawnPoints: Opaque
    VeterancyLevel: Untyped
    MinLifetime: Int
    MaxLifetime: Int
    SkipIfSignificantlyAirborne: Bool


class ObjectCreationList(IniObject):
    key = "objectcreationlists"

    CreateObject: list[io.CreateObject]

    nested_attributes = {
        "CreateObject": [CreateObject],
        "CreateDebris": ["CreateDebris"],
        "FireWeapon": ["FireWeapon"],
        "ApplyRandomForce": ["ApplyRandomForce"],
        "Attack": ["Attack"],
        "DeliverPayload": ["DeliverPayload"],
    }


class CommandButton(IniObject):
    key = "commandbuttons"

    ButtonBorderType: ButtonBorderTypes

    CommandTrigger: "CommandButton"
    ToggleButtonName: "CommandButton"

    Command: CommandTypes

    CursorName: Cursor
    InvalidCursorName: Cursor
    RadiusCursorType: Cursor

    FlagsUsedForToggle: List[ModelCondition]
    ButtonImage: List[Image]
    AffectsKindOf: List[KindOf]
    Options: List[e.Options]
    Stances: List[e.Stances]
    CreateAHeroUIAllowableUpgrades: List[io.Upgrade]

    AutoAbilityDisallowedOnModelCondition: List[ModelCondition]
    DisableOnModelCondition: List[ModelCondition]
    EnableOnModelCondition: List[ModelCondition]

    Object: Nullable["Object"]
    Science: io.Science

    UnitSpecificSound: List[Sound]
    SetAutoAbilityUnitSound: Sound

    SpecialPower: Nullable[io.SpecialPower]

    DescriptLabel: List[Label]
    TextLabel: List[Label]
    LacksPrerequisiteLabel: Label
    ConflictingLabel: Label
    PurchasedLabel: Label
    CreateAHeroUIPrerequisiteButtonName: t.CommandButtonRef

    NeededUpgrade: List[Nullable[io.Upgrade]]

    WeaponSlot: SlotTypes
    WeaponSlotToggle1: SlotTypes
    WeaponSlotToggle2: SlotTypes

    DoubleClick: Bool
    Radial: Bool
    InPalantir: Bool
    AutoAbility: Bool
    TriggerWhenReady: Bool
    ShowButton: Bool
    NeedDamagedTarget: Bool
    IsClickable: Bool
    ShowProductionCount: Bool
    NeededUpgradeAny: Bool
    RequiresValidContainer: Bool

    PresetRange: Float
    AutoDelay: Float

    CommandRangeStart: Int
    CommandRangeCount: Int
    CreateAHeroUIMinimumLevel: Int
    CreateAHeroUICostIfSelected: Int
    Upgrade: io.Upgrade
    AffectsAllies: t.Bool
    BuildUpgrades: t.Opaque
    MaxShotsToFire: t.Int
    UnitSpecificSound2: t.Opaque


class SelectionDecal(IniObject):
    key = None

    Texture: t.TextureFile
    Texture2: Opaque
    Style: FakeEnum
    OpacityMin: Float
    OpacityMax: Float
    MinRadius: Float
    MaxRadius: Float
    MaxSelectedUnits: Int


class ExperienceLevel(IniObject):
    key = "levels"

    TargetNames: List[Union["Object", FactionSide]]
    RequiredExperience: Float
    ExperienceAward: Float
    Rank: Float
    ExperienceAwardOwnGuysDie: Float
    Upgrades: List[Upgrade]
    InformUpdateModule: Bool
    LevelUpTintColor: RGB
    LevelUpTintPreColorTime: Float
    LevelUpTintPostColorTime: Float
    LevelUpTintSustainColorTime: Float
    AttributeModifiers: List["ModifierList"]
    LevelUpFx: FXList
    ShowLevelUpTint: Bool
    EmotionType: EmotionTypes

    SelectionDecal: list[io.SelectionDecal]

    nested_attributes = {"SelectionDecal": [SelectionDecal]}


class EmotionNugget(IniObject):
    key = "emotions"

    Type: EmotionTypes
    AIState: EmotionNuggetAIState
    ModelConditions: List[ModelCondition] = []
    ModelConditionsClear: List[ModelCondition] = []
    Duration: Int
    AILockDuration: Int
    AttributeStartDelay: Int
    InactiveDuration: Int
    InactiveDurationSameType: Int
    InactiveDurationSameObject: Int
    OnlyIfEnemyThreatBelow: Int
    IgnoreIfUnitBusy: Bool
    IgnoreIfUnitIdle: Bool
    PreventPlayerCommands: Bool
    AttributeModifierWhileEmotionActive: Bool
    StartFXList: FXList
    UpdateFXList: FXList
    EndFXList: FXList


class CommandSet(IniObject):
    key = "commandsets"

    numbered_slots = True  # `1 = Command_X` ... button slots, read via `CommandButtons`
    numbered_slot_ref = "commandbuttons"  # the slots reference CommandButtons (for the xref graph)

    InitialVisible: Int

    def __repr__(self):
        slots = sum(1 for key in self._fields if key.isdigit())
        return f"<CommandSet {self.name} len={slots}>"

    @property
    def CommandButtons(self):
        """Slot index -> resolved CommandButton for each digit-keyed field."""
        return {
            int(slot): CommandButton.convert(self._game, name)
            for slot, name in self._fields.items()
            if slot.isdigit()
        }

    def as_list(self):
        buttons = self.CommandButtons
        if not buttons:
            return []
        size = max(buttons)
        return [buttons.get(index) for index in range(1, size + 1)]

    def initial_visible(self):
        visible = sorted(self.CommandButtons.items())[: self.InitialVisible]
        return dict(visible)

    def get_button(self, index):
        try:
            return self.CommandButtons[index]
        except KeyError:
            raise KeyError(f"No CommandButton on slot {index}") from None


class ModifierList(IniObject):
    key = "modifiers"

    Category: ModifierCategories
    EndFX2: FXList
    EndFX3: FXList
    Duration: Int
    FX: FXList
    ReplaceInCategoryIfLongest: Bool
    IgnoreIfAnticategoryActive: Bool
    FX2: FXList
    FX3: FXList
    MultiLevelFX: Bool
    ClearModelCondition: List[e.ModelCondition]
    ModelCondition: e.ModelCondition
    Upgrade: UpgradeWithDelay
    EndFX: FXList
    # Each `Modifier =` line is `<ModifierType> <amount> [<DamageType>...]`; the key repeats,
    # so this is the list of all of them. `ARMOR`/`INVULNERABLE` are modifier types whose
    # trailing tokens scope them to specific damage types.
    Modifier: ModifierEntry


class Weapon(IniObject):
    key = "weapons"

    AttackRange: Float
    ScatterTargetScalar: Float
    ScatterTarget: List[Untyped]  # `X: <n> Y: <n>` offsets, one per repeat
    WeaponBonus: List[
        Tuple[Untyped, Untyped, Untyped]
    ]  # `<condition> <field> <value>`, one per repeat
    RangeBonusMinHeight: Float
    RangeBonus: Float
    RangeBonusPerFoot: Float
    WeaponSpeed: Float
    MinWeaponSpeed: Float
    MaxWeaponSpeed: Float
    FireFX: FXList
    ScaleWeaponSpeed: Bool
    HitPercentage: Float
    ScatterRadius: Float
    AcceptableAimDelta: Float
    DelayBetweenShots: RangeDuration
    PreAttackDelay: Float
    PreAttackType: WeaponPrefireType
    FiringDuration: Float
    ClipSize: Float
    AutoReloadsClip: e.WeaponReloadType
    AutoReloadWhenIdle: Float
    ClipReloadTime: RangeDuration
    ContinuousFireOne: Float
    ContinuousFireCoast: Float
    AntiAirborneVehicle: Bool
    AntiAirborneMonster: Bool
    CanFireWhileMoving: Bool
    ProjectileCollidesWith: List[WeaponCollideTypes]
    RadiusDamageAffects: ObjectFilter
    HitStoredTarget: Bool
    PreferredTargetBone: Bone
    LeechRangeWeapon: Bool
    MeleeWeapon: Bool
    DamageDealtAtSelfPosition: Bool
    PreAttackFX: FXList
    ShouldPlayUnderAttackEvaEvent: Bool
    FireFlankFX: FXList
    InstantLoadClipOnActivate: Bool
    IdleAfterFiringDelay: Float
    MinimumAttackRange: Float
    ProjectileSelf: Bool
    PreAttackRandomAmount: Float
    HitPassengerPercentage: Float
    CanBeDodged: Bool
    NoVictimNeeded: Bool
    BombardType: Bool
    OverrideVoiceAttackSound: Sound
    OverrideVoiceEnterStateAttackSound: Sound
    RequireFollowThru: Bool
    FinishAttackOnceStarted: Bool
    HoldDuringReload: Bool
    IsAimingWeapon: Bool
    HoldAfterFiringDelay: Float
    ProjectileFilterInContainer: ObjectFilter
    AntiStructure: Bool
    AntiGround: Bool
    ScatterRadiusVsInfantry: Float
    ScatterIndependently: Bool
    PlayFXWhenStealthed: Bool
    AimDirection: Float
    FXTrigger: Untyped  # a named trigger flag (e.g. CATAPULT_ROCK) FX gate on, not an FXList
    ShareTimers: Bool
    DisableScatterForTargetsOnWall: Bool
    DamageType: e.DamageType
    CanSwoop: Bool
    PassengerProportionalAttack: Bool
    MaxAttackPassengers: Float
    ChaseWeapon: Bool
    CanFireWhileCharging: Bool
    IgnoreLinearFirstTarget: Bool
    LinearTarget: TimedPosition
    ForceDisplayPercentReady: Bool
    AntiAirborneInfantry: Bool
    LockWhenUsing: Bool
    ProjectileStreamName: "Object"
    UseInnateAttributes: Bool
    PrimaryDamage: Float
    PrimaryDamageRadius: Float
    SecondaryDamage: Float
    SecondaryDamageRadius: Float
    ShockWaveAmount: Float
    ShockWaveRadius: Float
    ShockWaveTaperOff: Float
    DeathType: e.DeathType
    DamageStatusType: FakeEnum
    ProjectileObject: "Object"
    ProjectileDetonationFX: FXList
    ProjectileDetonationOCL: ObjectCreationList
    ProjectileExhaust: Opaque
    VeterancyProjectileExhaust: Opaque
    VeterancyFireFX: FXList
    FireOCL: ObjectCreationList
    FireSound: Sound
    FireSoundLoopTime: Int
    LaserName: Opaque
    LaserBoneName: Bone
    HistoricBonusWeapon: "Weapon"
    HistoricBonusCount: Int
    HistoricBonusRadius: Int
    HistoricBonusTime: Int
    ContinueAttackRange: Int
    ContinuousFireTwo: Int
    RequestAssistRange: Int
    MaxTargetPitch: Int
    MinTargetPitch: Int
    ShotsPerBarrel: Int
    WeaponRecoil: Int
    SuspendFXDelay: Int
    AllowAttackGarrisonedBldgs: Bool
    CapableOfFollowingWaypoints: Bool
    MissileCallsOnDie: Bool
    RotatingTurret: Bool
    ShowsAmmoPips: Bool
    AntiBallisticMissile: Bool
    AntiMine: Bool
    AntiProjectile: Bool
    AntiSmallMissile: Bool
    AntiMask: Untyped

    Nuggets: list[Nugget]

    nested_attributes = {"Nuggets": WEAPON_NUGGETS}

    @property
    def AttackSpeed(self):
        return self.FiringDuration + self.DelayBetweenShots.average


class Locomotor(IniObject):
    key = "locomotors"

    # The terrain the locomotor crosses (flag set), its motion model on the Z axis, the visual
    # movement style, and how it slots into formations - all named token sets, kept as strings.
    Surfaces: Untyped
    ZAxisBehavior: Untyped
    Appearance: Untyped
    FormationPriority: Untyped

    # Core speeds, turning and braking (and their damaged-state variants). Distances are world
    # units, times are in milliseconds, rates are per-frame unless noted.
    Speed: Float
    SpeedDamaged: Float
    MinSpeed: Float
    MinTurnSpeed: Float
    Acceleration: Float
    Braking: Float
    TurnTime: Float
    TurnTimeDamaged: Float
    FastTurnRadius: Float
    SlowTurnRadius: Float
    TurnThreshold: Float
    TurnThresholdHS: Float
    TurnPivotOffset: Float
    MaxTurnWithoutReform: Float
    CirclingRadius: Float
    WalkDistance: Float
    LookAheadMult: Float
    CloseEnoughDist: Float

    PreferredHeight: Float
    PreferredAttackHeight: Float
    AirborneTargetingHeight: Float
    MaxOverlappedHeight: Float
    Lift: Float
    LiftDamaged: Float
    MaxThrustAngle: Float
    AllowAirborneMotiveForce: Bool
    Apply2DFrictionWhenAirborne: Bool

    ForwardAccelerationPitchFactor: Float
    ForwardVelocityPitchFactor: Float
    LateralAccelerationRollFactor: Float
    LateralVelocityRollFactor: Float
    PitchInDirectionOfZVelFactor: Float
    PitchStiffness: Float
    RollStiffness: Float
    PitchDamping: Float
    RollDamping: Float
    AccelerationPitchLimit: Float
    BounceAmount: Float
    UseTerrainSmoothing: Bool

    HasSuspension: Bool
    MaximumWheelExtension: Float
    MaximumWheelCompression: Float
    FrontWheelTurnAngle: Float

    ElevatorCorrectionDegree: Float
    ElevatorCorrectionRate: Float
    AeleronCorrectionDegree: Float
    AeleronCorrectionRate: Float
    RudderCorrectionDegree: Float
    RudderCorrectionRate: Float

    # Swoop: a flyer's diving attack run.
    SwoopStandoffRadius: Float
    SwoopStandoffHeight: Float
    SwoopTerminalVelocity: Float
    SwoopAccelerationRate: Float

    CanMoveBackwards: Bool
    BackingUpSpeed: Float
    BackingUpStopWhenTurning: Bool
    BackingUpDistanceMin: Float
    BackingUpDistanceMax: Float
    BackingUpAngle: Float

    ChargeSpeed: Float
    ChargeAvailable: Bool
    ChargeIgnoresCondition: Bool

    WanderWidthFactor: Float
    WanderLengthFactor: Float
    WanderAboutPointRadius: Float

    AccDecTrigger: Float
    SlideIntoPlaceTime: Float
    RiverModifier: Float
    StickToGround: Bool
    ScalesWalls: Bool
    CrewPowered: Bool
    TurnWhileMoving: Bool
    WaitForFormation: Bool
    NonDirtyTransform: Bool
    LocomotorWorksWhenDead: Bool
    EnableHighSpeedTurnModelconditions: Bool
    BurningDeathRadius: Float
    BurningDeathIsCavalry: Bool
    AccelerationDamaged: Float
    TurnRate: Float
    TurnRateDamaged: Float
    Extra2DFriction: Float
    SpeedLimitZ: Float
    PreferredHeightDamping: Float
    CloseEnoughDist3D: Bool
    DownhillOnly: Bool
    UniformAxialDamping: Float
    DecelerationPitchLimit: Float
    GroupMovementPriority: FakeEnum
    ThrustRoll: Float
    ThrustWobbleRate: Float
    ThrustMinWobble: Float
    ThrustMaxWobble: Float
    SwoopSpeedTuningFactor: Float


class WeaponSet(IniObject):
    key = None

    Conditions: List[WeaponsetFlags]
    # `Weapon = PRIMARY None` clears a slot, so the weapon reference is nullable.
    Weapon: List[Tuple[SlotTypes, Nullable[io.Weapon]]]
    ReadyStatusSharedWithinSet: Bool
    ShareWeaponReloadTime: Bool
    DefaultWeaponChoiceCritera: Untyped
    # Per-slot gating lines (`PRIMARY <flags>`); each may repeat, one per weapon slot.
    AutoChooseSources: List[Untyped]
    OnlyAgainst: List[Untyped]
    PreferredAgainst: List[Untyped]
    OnlyInCondition: List[Untyped]


class ArmorSet(IniObject):
    key = None

    Conditions: List[ArmorSetFlags]
    Armor: io.Armor
    DamageFX: t.DamageFXRef


class AutoResolveArmor(IniObject):
    key = None

    Armor: Untyped
    RequiredUpgrades: List[t.UpgradeRef]
    ExcludedUpgrades: List[t.UpgradeRef]


class AutoResolveWeapon(IniObject):
    key = None

    Weapon: Untyped
    RequiredUpgrades: List[t.UpgradeRef]
    ExcludedUpgrades: List[t.UpgradeRef]
    DamagePerRound: t.Opaque
    LevelBonus: t.Opaque
    MissPercentChance: t.Int
    ReduceAttackWhenHurt: t.Bool


class UnitSpecificSounds(IniObject):
    key = None

    # Every field names the audio event for a context-specific voice/ambient line (a soft
    # reference; `NoSound` and unknown names pass through as the raw token).
    UnderConstruction: Sound
    UnderRepairFromRubble: Sound
    UnderRepairFromDamage: Sound
    VoiceGarrison: Sound
    VoiceInitiateCaptureBuilding: Sound
    VoiceEnterUnitElvenTransportShip: Sound
    VoiceEnterUnitSlaughterHouse: Sound
    VoiceEnterUnitMordorMumakil: Sound
    VoiceEnterUnitEvilMenTransportShip: Sound
    VoiceEnterUnitTransportShip: Sound
    VoiceEnter: Sound
    VoiceEnterHostile: Sound
    VoiceGetHealed: Sound
    VoiceMoveToTrees: Sound
    VoiceDesperateAttack: Sound
    VoiceEnterStateMoveToTrees: Sound
    VoiceBuildResponse: Sound
    VoiceExtinguishFireAtLocation: Sound
    VoiceNoBuild: Sound
    VoiceSelectIdleWorker: Sound
    VoiceCreatedFromInn: Sound
    VoiceFullyCreatedFromInn: Sound
    VoiceAttackUnitWebbedHumanoidWithGondorFighterInside: Sound
    VoiceAttackUnitWebbedHumanoidWithGondorArcherInside: Sound
    VoicePrimaryWeaponMode: Sound
    VoiceSecondaryWeaponMode: Sound
    VoiceEnterStateInitiateCaptureBuilding: Sound
    VoiceRepair: Sound
    VoiceAttackFireball: Sound
    VoiceAttackUnitRohanEntBirch: Sound
    VoiceAttackUnitRohanEntFir: Sound
    VoiceAttackUnitRohanTreeBerd: Sound
    VoiceAttackUnitRohanEntAsh: Sound
    VoiceSupply: Sound
    VoiceStartCharging: Sound
    VoiceInitiateBarbedArrowAttack: Sound
    VoiceSpecialAbilityCurseEnemy: Sound
    VoiceInitiatePoisonArrowAttack: Sound
    VoiceInitiateBlackArrowsAttack: Sound


class LocomotorSet(IniObject):
    key = None

    Locomotor: Nullable[io.Locomotor]
    Condition: LocomotorSetType
    Speed: Int


class GeometryShape(NestedAttribute):
    """One collision/footprint primitive of an Object's geometry, built by `MarkerGroup`
    from a `Geometry`/`AdditionalGeometry` line and the `Geometry*` keys that follow.
    `is_primary` marks the first (`Geometry`) shape versus the appended ones."""

    key = None

    type: GeometryType
    GeometryName: Opaque
    GeometryMajorRadius: Float
    GeometryMinorRadius: Float
    GeometryHeight: Float
    GeometryFrontAngle: Float
    GeometryActive: Bool
    GeometryIsSmall: Bool
    GeometryOffset: Coords

    @classmethod
    def from_raw(cls, game, raw):
        fields = {"type": raw.value, **raw.fields}
        field_spans = {"type": raw.span, **raw.field_spans}
        shape = cls(
            name=raw.value,
            game=game,
            fields=fields,
            extras=[],
            span=raw.span,
            field_spans=field_spans,
        )
        shape._marker = raw.marker
        return shape

    @property
    def is_primary(self) -> bool:
        return self._marker == "Geometry"


class AddModule(IniObject):
    """An `AddModule` block on a (usually inheriting) object: contributes the one module it
    wraps to the object on top of those it inherits."""

    key = None

    @property
    def module(self):
        """The single module this op contributes, or None if it holds no typed module."""
        return self._modules[0] if self._modules else None


class ReplaceModule(IniObject):
    """A `ReplaceModule <tag>` block: swaps the inherited module tagged `<tag>` (the block's
    `name`) for the replacement module it wraps (`module`)."""

    key = None

    @property
    def module(self):
        """The replacement module, or None if it holds no typed module."""
        return self._modules[0] if self._modules else None


class InheritableModule(IniObject):
    """An `InheritableModule` wrapper (used on `DefaultThingTemplate`): the module it holds is
    copied into every object and kept across copies, so it is part of every object's inherited
    module set."""

    key = None

    @property
    def module(self):
        """The wrapped module, or None if it holds no typed module."""
        return self._modules[0] if self._modules else None


class Object(IniObject):
    key = "objects"

    EditorSorting: t.FlagList[e.EditorSorting]
    BuildCost: Int
    BuildTime: Int
    ShockwaveResistance: Int
    DisplayMeleeDamage: Int
    HeroSortOrder: Int
    CommandSet: Nullable[io.CommandSet]
    CommandPoints: Int
    DisplayName: Label
    RecruitText: Label
    ReviveText: Label
    Hotkey: Untyped

    VisionRange: Float
    RefundValue: Int
    IsForbidden: Bool
    IsBridge: Bool
    IsPrerequisite: Bool
    KindOf: FlagList[e.KindOf]

    ThingClass: t.String
    Side: e.FactionSide
    FactionSide: e.FactionSide
    Description: Label
    SelectPortrait: Image
    ButtonImage: Image
    RadarPriority: e.RadarPriority
    ThreatLevel: Float
    BuildCompletion: Opaque
    PlacementViewAngle: Int
    TransportSlotCount: Int
    BountyValue: Int
    CampnessValue: Int
    CrushableLevel: Int
    CrusherLevel: Int
    ShroudClearingRange: Int
    IsTrainable: Bool
    CrowdResponseKey: t.CrowdResponseRef
    EmotionRange: Int
    InstanceScaleFuzziness: Float

    GeometryUsedForHealthBox: Bool
    GeometryRotationAnchorOffset: CoordsList  # repeats once per geometry block
    GeometryContactPoint: ContactPoint
    AttackContactPoint: ContactPoint

    Shadow: e.ObjectShadowType
    ShadowTexture: Opaque
    ShadowSizeX: Int
    ShadowSizeY: Int
    ShadowOffsetX: Float
    ShadowMaxHeight: Float
    ShadowSunAngle: Float
    ShadowOverrideLODVisibility: Bool
    ShadowOpacityStart: Int
    ShadowOpacityPeak: Int
    ShadowOpacityEnd: Int
    ShadowOpacityFadeInTime: Int
    ShadowOpacityFadeOutTime: Int

    VisionSide: Float
    VisionRear: Float
    VisionBonusPercentPerFoot: Float
    VisionBonusTestRadius: Float
    MaxVisionBonusPercent: Float

    VoicePriority: Int
    VoiceSelect: Sound
    VoiceSelectBattle: Sound
    VoiceSelectUnderConstruction: Sound
    VoiceMove: Sound
    VoiceMoveToCamp: Sound
    VoiceMoveToHigherGround: Sound
    VoiceMoveOverWalls: Sound
    VoiceMoveWhileAttacking: Sound
    VoiceAttack: Sound
    VoiceAttackStructure: Sound
    VoiceAttackMachine: Sound
    VoiceAttackCharge: Sound
    VoiceAttackAir: Sound
    VoiceGuard: Sound
    VoiceFear: Sound
    VoiceCreated: List[Sound]
    VoiceFullyCreated: List[Sound]
    VoiceRetreatToCastle: Sound
    VoiceCombineWithHorde: Sound
    VoiceTaskComplete: Sound
    VoiceAlert: Sound
    VoiceDefect: Sound
    VoiceEnterStateMove: Sound
    VoiceEnterStateMoveToCamp: Sound
    VoiceEnterStateMoveToHigherGround: Sound
    VoiceEnterStateMoveOverWalls: Sound
    VoiceEnterStateMoveWhileAttacking: Sound
    VoiceEnterStateAttack: Sound
    VoiceEnterStateAttackStructure: Sound
    VoiceEnterStateAttackMachine: Sound
    VoiceEnterStateAttackCharge: Sound
    VoiceEnterStateAttackAir: Sound
    VoiceEnterStateRetreatToCastle: Sound

    SoundOnDamaged: Sound
    SoundOnReallyDamaged: Sound
    SoundAmbient: Sound
    SoundAmbientDamaged: Sound
    SoundAmbientReallyDamaged: Sound
    SoundAmbientBattle: Sound
    SoundAmbientRubble: Sound
    SoundImpact: Sound
    SoundImpactCyclonic: Sound
    SoundCrushing: Sound
    SoundCreated: Sound
    SoundMoveStart: Sound
    SoundMoveStartDamaged: Sound
    SoundMoveLoop: Sound
    SoundMoveLoopDamaged: Sound
    SoundStealthOn: Sound
    SoundStealthOff: Sound
    SoundEnter: Sound
    SoundExit: Sound
    SoundFallingFromPlane: Sound
    SoundPromotedVeteran: Sound
    SoundPromotedElite: Sound
    SoundPromotedHero: Sound

    EvaEventDamagedOwner: EvaEvent
    EvaEventDamagedByFireOwner: EvaEvent
    EvaEventDamagedFromShroudedSourceOwner: EvaEvent
    EvaEventSecondDamageFarFromFirstOwner: EvaEvent
    EvaEventDieOwner: EvaEvent
    EvaEventAmbushed: EvaEvent
    EvaEnemyObjectSightedEvent: EvaEvent
    EvaEnemyObjectSightedAfterRespawnEvent: EvaEvent
    EvaOnFirstSightingEventEnemy: EvaEvent
    EvaOnFirstSightingEventNonEnemy: EvaEvent
    EvaEventDetectedEnemy: EvaEvent
    EvaEventDetectedAlly: EvaEvent
    EvaEventDetectedOwner: EvaEvent
    EvaEventSecondDamageFarFromFirstScanRange: Int
    EvaEventSecondDamageFarFromFirstTimeoutMS: Int

    # Presentation: the prop model and how it is drawn/oriented (used by simple decorative
    # and world-map objects). Reference-like names are kept raw (Opaque) for now.
    Model: Opaque
    Scale: Float
    SubObjects: Opaque
    OrientAngle: Float
    ZOffset: Untyped  # a min/max pair on some props, not a scalar
    Browser: t.String
    VisibleArmySizes: Untyped
    FadeMethod: Untyped
    UseHouseColor: Bool
    Clickable: Bool
    Pickbox: Opaque
    DisplayColor: RGBA
    GeometryOther: (
        RawList  # a colon-keyed extra-geometry spec (`GeomType:BOX IsSmall:No ...`), one per repeat
    )

    DescriptionStrategic: Untyped
    DisplayNameStrategic: Untyped
    DisplayNameInvisibleForEnemy: Untyped
    AutoResolveUnitType: Opaque
    AutoResolveBody: t.AutoResolveBodyRef
    AutoResolveCombatChain: t.AutoResolveCombatChainRef
    AutoResolveLeadership: t.AutoResolveLeadershipRef
    WorldMapArmoryUpgradesAllowed: List[t.UpgradeRef]
    ExperienceScalarTable: Opaque

    KeepSelectableWhenDead: Bool
    HideWhenUnhilighted: Bool
    HideWhenUnselected: Bool
    ShowOnlyForAllies: Bool
    HideWhenUnderConstruction: Bool
    HideWhenNotUnderConstruction: Bool
    HideWhenNotProducing: Bool
    DisplayAtRallyPoint: Bool
    ShowOnlyAfterMoveOrder: Bool
    ShowHealthInSelectionDecal: Bool
    FadeTypeForHilighting: Untyped
    FadeTypeForUnhilighting: Untyped
    FadeTypeForSelection: Untyped
    FadeTypeForShowing: Untyped
    FadeTypeForHiding: Untyped
    FadeHoldPercent: Opaque  # a `#define`d percentage
    FadeInTime: Int
    FadeOutTime: Int

    CrushWeapon: t.WeaponRef
    CrushRevengeWeapon: t.WeaponRef
    UseCrushAttack: Bool
    CrushOnlyWhileCharging: Bool
    CrushAllies: Bool
    CrushDecelerationPercent: Float
    MinCrushVelocityPercent: Float
    CrushZFactor: Float
    CrushKnockback: Float
    MountedCrusherLevel: Int
    MountedCrushableLevel: Int
    RamPower: Float
    RamZMult: Float

    FormationWidth: Int
    FormationDepth: Int

    AnimMode: Untyped
    PathfindDiameter: Float
    CamouflageDetectionMultiplier: t.Float  # a `#define`d distance
    CommandPointBonus: t.Int  # a `#define`d bonus
    SelectionPriority: t.Int  # a `#define`d priority
    HealthBoxHeightOffset: Float
    HealthBoxScale: Float
    UpgradeCameo1: t.UpgradeRef
    ForceLuaRegistration: Bool
    MaxSimultaneousOfType: Int
    IsGrabbable: Bool
    IsHarvestable: Bool
    MinZIncreaseForVoiceMoveToHigherGround: Float
    DeadCollideSize: Untyped
    LiveCameraOffset: Coords
    LiveCameraPitch: Float
    IsAutoBuilt: Bool
    CanPathThroughGates: Bool
    BuildVariations: t.List[t.ObjectRef]
    EquivalentTo: t.ObjectRef
    BuildFadeInOnCreateTime: Int
    BuildFadeInOnCreateList: t.String
    Buildable: Bool
    EnergyProduction: Int
    CampnessValueRadius: Float
    RemoveTerrainRadius: Float
    ShouldClearShotsOnIdle: Bool

    DisplayRangedDamage: Float
    EnergyBonus: Int
    EnterGuard: Bool
    EvaEnemyUnitSightedEvent: EvaEvent
    ExperienceRequired: Untyped
    ExperienceValue: Untyped
    FactoryExitWidth: Int
    FactoryExtraBibWidth: Float
    FenceWidth: Float
    FenceXOffset: Float
    GroupVoiceThreshold: Int
    HijackGuard: Bool
    ImmuneToShockwave: Bool
    Locomotor: List[Untyped]
    MaxSimultaneousLinkKey: t.String
    OverrideableByLikeKind: Untyped
    Prerequisites: Untyped
    ShroudRevealToAllRange: Float
    SoundAmbient2: Sound
    SoundAmbientDamaged2: Sound
    SoundAmbientReallyDamaged2: Sound
    SoundAmbientRubble2: Sound
    SoundCrush: Sound
    SoundDie: Sound
    SoundDieFire: Sound
    SoundDieToxin: Sound
    StructureRubbleHeight: Int
    SupplyOverride: Int
    UnitSpecificFX: Untyped
    UpgradeCameo2: Upgrade
    UpgradeCameo3: Upgrade
    UpgradeCameo4: Upgrade
    UpgradeCameo5: Upgrade
    VoiceAlert2: Sound
    VoiceAmbushBlockingRadius: Int
    VoiceAmbushTimeout: Int
    VoiceAmbushed: Sound
    VoiceAmbushed2: Sound
    VoiceAttack2: Sound
    VoiceAttackAir2: Sound
    VoiceAttackAirGroup: Sound
    VoiceAttackAirGroup2: Sound
    VoiceAttackCharge2: Sound
    VoiceAttackChargeGroup: Sound
    VoiceAttackChargeGroup2: Sound
    VoiceAttackGroup: Sound
    VoiceAttackGroup2: Sound
    VoiceAttackMachine2: Sound
    VoiceAttackMachineGroup: Sound
    VoiceAttackMachineGroup2: Sound
    VoiceAttackStructure2: Sound
    VoiceAttackStructureGroup: Sound
    VoiceAttackStructureGroup2: Sound
    VoiceCombineWithHorde2: Sound
    VoiceCreated2: Sound
    VoiceDefect2: Sound
    VoiceEnter: Sound
    VoiceEnterStateAttack2: Sound
    VoiceEnterStateAttackAir2: Sound
    VoiceEnterStateAttackCharge2: Sound
    VoiceEnterStateAttackMachine2: Sound
    VoiceEnterStateAttackStructure2: Sound
    VoiceEnterStateMove2: Sound
    VoiceEnterStateMoveToCamp2: Sound
    VoiceEnterStateMoveWhileAttacking2: Sound
    VoiceEnterStateRetreatToCastle2: Sound
    VoiceFear2: Sound
    VoiceFullyCreated2: Sound
    VoiceGarrison: Sound
    VoiceGroupSelect: Sound
    VoiceGuard2: Sound
    VoiceGuardGroup: Sound
    VoiceGuardGroup2: Sound
    VoiceMeetEnemy: Sound
    VoiceMove2: Sound
    VoiceMoveGroup: Sound
    VoiceMoveGroup2: Sound
    VoiceMoveToCamp2: Sound
    VoiceMoveToCampGroup: Sound
    VoiceMoveToCampGroup2: Sound
    VoiceMoveWhileAttacking2: Sound
    VoiceMoveWhileAttackingGroup: Sound
    VoiceMoveWhileAttackingGroup2: Sound
    VoiceRetreatToCastle2: Sound
    VoiceRetreatToCastleGroup: Sound
    VoiceRetreatToCastleGroup2: Sound
    VoiceSelect2: Sound
    VoiceSelectBattle2: Sound
    VoiceSelectBattleGroup: Sound
    VoiceSelectBattleGroup2: Sound
    VoiceSelectElite: Sound
    VoiceSelectGroup: Sound
    VoiceSelectGroup2: Sound
    VoiceTaskComplete2: Sound
    VoiceTaskUnable: Sound

    # Element types of the nested/marker groups below, declared so `obj.WeaponSet[0]` etc.
    # are typed; the runtime mapping lives in `nested_attributes`/`marker_groups`.
    WeaponSet: list[io.WeaponSet]
    ArmorSet: list[io.ArmorSet]
    AutoResolve: list[AutoResolveArmor | AutoResolveWeapon]
    UnitSpecificSounds: list[io.UnitSpecificSounds]
    LocomotorSet: list[io.LocomotorSet]
    Draw: list[obj.Draw]
    AddModule: list[io.AddModule]
    ReplaceModule: list[io.ReplaceModule]
    InheritableModule: list[io.InheritableModule]
    geometry: list[GeometryShape]

    # Inherited-module edits applied by a `ChildObject` (and harmless on a base object).
    # `RemoveModule = <tag>` is a plain attribute (may repeat); the others are blocks.
    RemoveModule: List[Untyped]

    nested_attributes = {
        "WeaponSet": [WeaponSet],
        "ArmorSet": [ArmorSet],
        "AutoResolve": [AutoResolveArmor, AutoResolveWeapon],
        "UnitSpecificSounds": [UnitSpecificSounds],
        "LocomotorSet": [LocomotorSet],
        "Draw": [Draw],
        "AddModule": [AddModule],
        "ReplaceModule": [ReplaceModule],
        "InheritableModule": [InheritableModule],
        # Misc object sub-blocks; concrete classes in `sage_ini.model.misc_blocks`.
        "ThreatBreakdown": ["ThreatBreakdown"],
        "Flammability": ["Flammability"],
        "FormationPreviewDecal": ["FormationPreviewDecal"],
        "FormationPreviewItemDecal": ["FormationPreviewItemDecal"],
    }

    marker_groups = {
        "geometry": MarkerGroup(
            markers=("Geometry", "AdditionalGeometry"),
            keys=(
                "GeometryName",
                "GeometryMajorRadius",
                "GeometryMinorRadius",
                "GeometryHeight",
                "GeometryOffset",
                "GeometryActive",
                "GeometryFrontAngle",
                "GeometryIsSmall",
            ),
            item=GeometryShape,
        ),
    }

    def call_special_power(self, power):
        return [
            module
            for module in self.modules
            if getattr(module, "trigger", None) is not None and module.trigger.name == power.name
        ]


class ChildObject(Object):
    parent_name = None
    header_arity = 2

    @classmethod
    def from_block(cls, game, block):
        obj = super().from_block(game, block)
        parts = (block.label or "").split(maxsplit=1)
        obj.parent_name = parts[1] if len(parts) == 2 else None
        return obj

    @property
    def parent(self):
        if self.parent_name is None:
            return None
        return self._game.tables["objects"].get(self.parent_name)

    def __getattr__(self, name):
        cls = type(self)
        if name.startswith("_") or name in cls._nested or name not in cls._fieldspec:
            return super().__getattr__(name)
        if name in self._fields:
            return super().__getattr__(name)
        parent = self.parent
        if parent is not None:
            return getattr(parent, name)
        return super().__getattr__(name)


class ObjectReskin(ChildObject):
    pass


class PlayerTemplate(IniObject):
    key = "factions"

    Side: e.FactionSide
    PlayableSide: Bool
    FactionSide: e.FactionSide
    SideIconImage: Image
    PlayableFactionSide: Bool
    StartMoney: Int
    PreferredColor: RGB
    IntrinsicSciences: Nullable[List[Science]]
    DisplayName: Label
    ScoreScreenImage: Image
    LoadScreenMusic: Untyped
    IsObserver: Bool
    LoadScreenImage: Image
    BeaconName: "Object"
    FactionSideIconImage: Image
    Evil: Bool
    MaxLevelMP: Int
    MaxLevelSP: Int
    StartingUnit1: Object
    StartingUnitOffset1: Coords
    StartingUnit0: Object
    StartingUnitOffset0: Coords
    StartingUnit2: Object
    StartingUnitOffset2: Coords
    StartingUnit5: Object
    StartingUnitOffset5: Coords
    StartingUnitTacticalWOTR: List[Object]
    IntrinsicSciencesMP: Nullable[List[Science]]
    SpellBook: Object
    SpellBookMp: Object
    PurchaseScienceCommandSet: CommandSet
    PurchaseScienceCommandSetMP: CommandSet
    DefaultPlayerAIType: "PlayerAIType"
    LightPointsUpSound: Sound
    ObjectiveAddedSound: Sound
    ObjectiveCompletedSound: Sound
    InitialUpgrades: List[Upgrade]
    BuildableHeroesMP: List[Nullable[Object]]
    BuildableRingHeroesMP: List[Nullable[Object]]
    SpellStoreCurrentPowerLabel: Label
    SpellStoreMaximumPowerLabel: Label
    ResourceModifierObjectFilter: ObjectFilter
    ResourceModifierValues: List[Float]
    MultiSelectionPortrait: Image
    StartingBuilding: Object
    BaseSide: Opaque
    OldFaction: Bool
    ArmyTooltip: Label
    Features: Label
    EnabledImage: Image
    GeneralImage: Image
    FlagWaterMark: Image
    MedallionRegular: Image
    MedallionHilite: Image
    MedallionSelect: Image
    ScoreScreenMusic: Opaque
    PurchaseScienceCommandSetRank1: CommandSet
    PurchaseScienceCommandSetRank3: CommandSet
    PurchaseScienceCommandSetRank8: CommandSet
    SpecialPowerShortcutCommandSet: CommandSet
    SpecialPowerShortcutButtonCount: Int
    SpecialPowerShortcutWinName: Opaque


class CrateData(IniObject):
    key = None

    pass
    CrateObject: t.Opaque
    CreationChance: t.Float
    KilledByType: e.KindOf
    KillerScience: t.Opaque
    OwnedByMaker: t.Bool
    VeterancyLevel: e.VeterancyLevel


class StanceTemplate(IniObject):
    key = "stancetemplates"

    nested_attributes = {"Stance": ["Stance"]}  # class in `sage_ini.model.misc_blocks`
