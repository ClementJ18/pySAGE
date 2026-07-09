# Field annotations are the typed converter aliases from sage_ini/model/types.py
# (`Annotated[PyType, converter]`): a checker reads each field's value type, while the
# converter runs at access time (see resolve_annotation).
# When a field's name equals its type's name (`Float: Float`), the field shadows the type for
# the rest of the class body. Qualify such types through a module alias (`e`=enums, `t`=types,
# `io`=ini_objects, `n`=nuggets): `Float: t.Float`, `Weapon: io.Weapon` - a field can never
# shadow `t.Float`, so field order no longer matters.
import sage_ini.model.enums as e
import sage_ini.model.ini_objects as io
import sage_ini.model.nuggets as n
import sage_ini.model.types as t
from sage_ini.model.data_blocks import FXParticleSystem
from sage_ini.model.enums import (
    AllowedWhenConditions,
    AModAuraCondition,
    ArmorSetFlags,
    CreateAtLocation,
    DamageType,
    EmotionTypes,
    FactionSide,
    FakeEnum,
    GeometryType,
    HealthOperation,
    HealthRatioType,
    KindOf,
    LocomotorSetType,
    ModelCondition,
    ModifierCategories,
    ObjectStatus,
    SlotTypes,
    SlowDeathPhase,
    SpecialPowerForbiddenUnpackConditions,
    SpecialPowerTriggerPosition,
    SpecialPowerUnpackConditions,
    StructureCollapsePhase,
    WeaponsetFlags,
    WeatherFlag,
)
from sage_ini.model.ini_objects import (
    CommandButton,
    CommandSet,
    ModifierList,
    Object,
    ObjectCreationList,
    Science,
    SpecialPower,
    Upgrade,
    Weapon,
)
from sage_ini.model.objects import Behavior
from sage_ini.model.types import (
    AnimAndDuration,
    Animation,
    AudioLoopCondition,
    Bone,
    Bool,
    ContainCondition,
    Coords,
    DamageTypeFilter,
    DeathTypeFilter,
    Degrees,
    EvaEvent,
    Float,
    FXList,
    GroupedByKey,
    Image,
    Int,
    KeyValuePair,
    Label,
    List,
    ModuleTag,
    ObjectFilter,
    Opaque,
    ParticleSystem,
    Sound,
    SubObject,
    Tuple,
    Untyped,
)


class SpecialPowerModuleBehavior(Behavior):
    SpecialPowerTemplate: SpecialPower
    StartsPaused: Bool
    UpdateModuleStartsAttack: Bool
    InitiateSound: Sound
    InitiateSound2: Sound
    AttributeModifier: ModifierList
    AttributeModifierAffectsSelf: Bool
    InitiateFX: FXList
    AntiCategory: List[ModifierCategories]
    AttributeModifierRange: Float
    AttributeModifierFX: FXList
    TriggerFX: FXList
    SetModelCondition: KeyValuePair
    SetModelConditionTime: Float
    AttributeModifierAffects: ObjectFilter
    AvailableAtStart: Bool
    TargetAllSides: Bool
    AffectAllies: Bool
    AttributeModifierWeatherBased: Bool
    TargetEnemy: Bool
    OnTriggerRechargeSpecialPower: SpecialPower
    DisableDuringAnimDuration: Bool
    RequirementsFilterMPSkirmish: ObjectFilter
    RequirementsFilterStrategic: ObjectFilter


class SpecialPowerModule(SpecialPowerModuleBehavior):
    pass


class HordeDispatchSpecialPower(SpecialPowerModuleBehavior):
    pass


class RepairSpecialPower(SpecialPowerModuleBehavior):
    pass


class SplitHordeSpecialPower(SpecialPowerModuleBehavior):
    pass


class UntamedAllegianceSpecialPower(SpecialPowerModuleBehavior):
    pass


class ManTheWallsSpecialPower(SpecialPowerModuleBehavior):
    pass


class DeflectSpecialPower(SpecialPowerModuleBehavior):
    pass


class SpecialPowerTimerRefreshSpecialPower(SpecialPowerModuleBehavior):
    pass


class EvacuateGarrisonSpecialPower(SpecialPowerModuleBehavior):
    pass


class CombineHordeSpecialPower(SpecialPowerModuleBehavior):
    ScanRange: Float


class ScavengerSpecialPower(SpecialPowerModuleBehavior):
    BountyPercent: Float


class PlayerUpgradeSpecialPower(SpecialPowerModuleBehavior):
    UpgradeName: Upgrade


class StopSpecialPower(SpecialPowerModuleBehavior):
    StopPowerTemplate: SpecialPower


class SiegeDeployHordeSpecialPower(SpecialPowerModuleBehavior):
    HordeDeploy: Bool


class DefectorSpecialPower(SpecialPowerModuleBehavior):
    FatCursorRadius: Float


class GrabPassengerSpecialPower(SpecialPowerModuleBehavior):
    AllowTree: Bool
    GrabRadius: Float


class CashHackSpecialPower(SpecialPowerModuleBehavior):
    UpgradeMoneyAmount: Tuple[Science, Int]
    MoneyAmount: Int


class DevastateSpecialPower(SpecialPowerModuleBehavior):
    Radius: Float
    TreeValueMultiplier: Float
    TreeValueTotalCap: Int
    FX: FXList
    FireWeapon: Weapon


class PlayerHealSpecialPower(SpecialPowerModuleBehavior):
    HealAffects: List[KindOf]
    HealAmount: Float
    HealRadius: Float
    HealFX: FXList
    HealOCL: ObjectCreationList
    HealAsPercent: Bool


class SiegeDeploySpecialPower(SpecialPowerModuleBehavior):
    LowerDelay: Int
    RaiseDelay: Int
    EvacuatePassengersOnDeploy: Bool
    SkipAdjustPosition: Bool
    WallSearchDistance: Float
    ExtraWallDistance: Float
    EvacuateCrewOnDeploy: Bool
    AwayFromWallWaitDist: Float


class DarknessSpecialPower(SpecialPowerModuleBehavior):
    AffectEvil: Bool
    WeatherDuration: Int
    ChangeWeather: WeatherFlag
    DarknessRadius: Float
    DarknessFX: FXList


class FreezingRainSpecialPower(SpecialPowerModuleBehavior):
    WeatherDuration: Int
    ChangeWeather: WeatherFlag
    BurnRateModifier: Int
    BurnDecayModifier: Int
    FreezingRainRadius: Float
    FreezingRainFX: FXList


class TaintSpecialPower(SpecialPowerModuleBehavior):
    TaintObject: Object
    TaintRadius: Float
    TaintFX: FXList
    TaintOCL: ObjectCreationList


class CloudBreakSpecialPower(SpecialPowerModuleBehavior):
    SunbeamObject: Object
    ObjectSpacing: Float
    AntiFX: FXList
    ReEnableAntiCategory: Bool
    WeatherDuration: Int
    ChangeWeather: WeatherFlag
    CloudBreakRadius: Float
    CloudBreakFX: FXList


class ElvenWoodSpecialPower(SpecialPowerModuleBehavior):
    ElvenGroveObject: Object
    ElvenWoodRadius: Float
    ElvenWoodFX: FXList
    ElvenWoodOCL: ObjectCreationList
    ElvenNumObjects: Int
    ElvenWoodObject: Object


class WeaponChangeSpecialPowerModule(SpecialPowerModuleBehavior):
    FlagsUsedForToggle: List[WeaponsetFlags]
    ToggleOnSleepFrames: Int
    ToggleOffSleepFrames: Int
    ToggleOnAttributeModifier: ModifierList
    ToggleOffAttributeModifier: ModifierList


class InvisibilitySpecialPower(SpecialPowerModuleBehavior):
    BroadcastRadius: Float
    InvisibilityNugget: n.InvisibilityNugget
    ObjectFilter: t.ObjectFilter
    Duration: Int


class OCLSpecialPower(SpecialPowerModuleBehavior):
    OCL: ObjectCreationList
    UpgradeOCL: Untyped  # `<upgrade> <ocl>` pair
    CreateLocation: CreateAtLocation
    ScriptedSpecialPowerOnly: Bool
    OCLAdjustPositionToPassable: Bool
    ReferenceObject: Object
    UpgradeName: Upgrade
    NearestSecondaryObjectFilter: ObjectFilter
    ReEnableAntiCategory: Bool
    WeatherDuration: Int
    ChangeWeather: WeatherFlag


class GiveOrRestoreUpgradeSpecialPower(SpecialPowerModuleBehavior):
    CommandButton: io.CommandButton
    UpgradeToGive: Upgrade
    FlagsUsedForToggle: WeaponsetFlags


class UnleashSpecialPower(SpecialPowerModuleBehavior):
    UnpackTime: Int
    AwardXPForTriggering: Int
    Instant: Bool


class ActivateModuleSpecialPower(SpecialPowerModuleBehavior):
    TriggerSpecialPower: List[Tuple[ModuleTag, SpecialPowerTriggerPosition]]
    UnpackTime: Int
    PreparationTime: Int
    PackTime: Int
    StartAbilityRange: Int
    MustFinishAbility: Bool
    UnpackingVariation: Int
    EffectRange: Float
    ApproachRequiresLOS: Bool
    ChainedButton: CommandButton


class StoreObjectsSpecialPower(SpecialPowerModuleBehavior):
    StartAbilityRange: Float
    ApproachRequiresLOS: Bool
    Radius: Float
    UnpackTime: Int
    PreparationTime: Int
    FreezeAfterTriggerDuration: Int
    ChainedButton: CommandButton


class CurseSpecialPower(SpecialPowerModuleBehavior):
    CursePercentage: Float
    UnpackingVariation: Int
    StartAbilityRange: Float
    UnpackTime: Int
    PreparationTime: Int
    FreezeAfterTriggerDuration: Int
    CursedFX: FXList
    TriggerModelCondition: t.AttributeModelCondition
    TriggerModelConditionDuration: Int
    PackTime: Int
    CustomAnimAndDuration: AnimAndDuration
    CurseFloat: Float
    AttributeModifierDuration: Int
    TriggerAttributeModifier: ModifierList


class TeleportToCasterSpecialPower(SpecialPowerModuleBehavior):
    UnpackingVariation: Int
    StartAbilityRange: Float
    ApproachRequiresLOS: Bool
    Radius: Float
    TargetFX: FXList
    MinDestinationRadius: Float
    MaxDestinationRadius: Float
    UnpackTime: Int
    PreparationTime: Int
    FreezeAfterTriggerDuration: Int


class DominateEnemySpecialPower(SpecialPowerModuleBehavior):
    UnpackingVariation: Int
    StartAbilityRange: Float
    DominateRadius: Float
    DominatedFX: FXList
    UnpackTime: Int
    PreparationTime: Int
    FreezeAfterTriggerDuration: Int
    PermanentlyConvert: Bool
    TriggerSound: Sound
    TriggerModelCondition: t.AttributeModelCondition
    TriggerModelConditionDuration: Int
    Instant: Bool


class LevelGrantSpecialPower(SpecialPowerModuleBehavior):
    UnpackingVariation: Int
    StartAbilityRange: Float
    UnpackTime: Int
    PreparationTime: Int
    FreezeAfterTriggerDuration: Int
    Experience: Int
    RadiusEffect: Float
    AcceptanceFilter: ObjectFilter
    LevelFX: FXList
    UseKindOf: Bool
    AffectsKindOf: List[KindOf]
    PackTime: Int


class UpgradeBehavior(Behavior):
    TriggeredBy: List[Upgrade]
    ConflictsWith: List[Upgrade]
    RequiresAllTriggers: Bool
    RequiresAllConflictingTriggers: Bool
    StartsActive: Bool
    Description: Label
    ActiveDuringConstruction: Bool
    CustomAnimAndDuration: AnimAndDuration
    Permanent: Bool


class AttributeModifierAuraUpdate(UpgradeBehavior):
    BonusName: ModifierList
    RefreshDelay: Int
    Range: Float
    TargetEnemy: Bool
    ObjectFilter: t.ObjectFilter
    RunWhileDead: Bool
    RequiredConditions: AModAuraCondition
    AntiCategory: List[ModifierCategories]
    AntiFX: FXList
    AllowSelf: Bool
    AllowPowerWhenAttacking: Bool
    MaxActiveRank: Int
    AffectContainedOnly: Bool
    AffectGood: Bool
    AffectEvil: Bool


class SpecialAbilityUpdate(Behavior):
    SpecialPowerTemplate: SpecialPower
    StartAbilityRange: Float
    AbilityAbortRange: Float
    PreparationTime: Int
    PersistentPrepTime: Int
    EffectDuration: Int
    EffectValue: Int
    DisableFXParticleSystem: ParticleSystem
    SpecialObject: Object
    SpecialObjectAttachToBone: Bone
    MaxSpecialObjects: Int
    SpecialObjectsPersistWhenOwnerDies: Bool
    AlwaysValidateSpecialObjects: Bool
    SpecialObjectsPersistent: Bool
    UniqueSpecialObjectTargets: Bool
    UnpackTime: Int
    PackTime: Int
    DoCaptureFX: Bool
    AwardXPForTriggering: Int
    SkipPackingWithNoTarget: Bool
    FlipOwnerAfterUnpacking: Bool
    FleeRangeAfterCompletion: Float
    PackSound: Sound
    UnpackSound: Sound
    TriggerSound: Sound
    PrepSoundLoop: Sound
    LoseStealthOnTrigger: Bool
    PreTriggerUnstealthTime: Int
    ApproachRequiresLOS: Bool
    NeedToFaceTarget: Bool
    PersistenceRequiresRecharge: Bool
    ChargeAttackSpeedBoost: Bool
    Instant: Bool
    CustomAnimAndDuration: AnimAndDuration
    ContactPointOverride: Untyped
    UnpackingVariation: Int
    TriggerAttributeModifier: ModifierList
    AttributeModifierDuration: Int
    KillAttributeModifierOnExit: Bool
    IgnoreFacingCheck: Bool
    EffectRange: Float
    GrabPassengerAnimAndDuration: AnimAndDuration
    GrabPassengerHealGainPercent: Float
    PersistentCount: Int
    RejectedConditions: SpecialPowerUnpackConditions
    RequiredConditions: SpecialPowerUnpackConditions
    KillAttributeModifierOnRejected: Bool
    TriggerModelCondition: t.AttributeModelCondition
    TriggerModelConditionDuration: Float
    FreezeAfterTriggerDuration: Int
    ChainedButton: CommandButton
    SkillPointsForTriggering: Int
    StopUnitBeforeActivating: Bool


class HeroModeSpecialAbilityUpdate(SpecialAbilityUpdate):
    HeroEffectDuration: Int
    HeroAttributeModifier: ModifierList


class SummonReplacementSpecialAbilityUpdate(SpecialAbilityUpdate):
    MountedTemplate: Object
    MustFinishAbility: Bool
    OpacityTarget: Float


class WeaponFireSpecialAbilityUpdate(SpecialAbilityUpdate):
    WhichSpecialWeapon: Int
    SkipContinue: Bool
    MustFinishAbility: Bool
    SpecialWeapon: Weapon
    BusyForDuration: Int
    PlayWeaponPreFireFX: Bool
    ApproachUntilMembersInRange: Bool
    NeedLivingTargets: Bool


class ScaleWallSpecialAbilityUpdate(SpecialAbilityUpdate):
    DelayAtFootOfWall: Int


class WeaponSetSpecialAbilityUpdate(SpecialAbilityUpdate):
    WeaponsetEffectDuration: Int
    WhichWeaponSet: Int


class FlingPassengerSpecialAbilityUpdate(Behavior):
    SpecialPowerTemplate: SpecialPower
    UnpackTime: Int
    FlingPassengerVelocity: Coords
    FlingPassengerLandingWarhead: Weapon
    PackTime: Int
    CustomAnimAndDuration: AnimAndDuration
    MustFinishAbility: Bool


class ModelConditionSpecialAbilityUpdate(Behavior):
    SpecialPowerTemplate: SpecialPower
    UnpackingVariation: Int
    UnpackTime: Int
    PreparationTime: Int
    PersistentPrepTime: Int
    PackTime: Int
    AwardXPForTriggering: Int
    GenerateTerror: Bool
    EmotionPulseRadius: Float
    DisableWhenWearingTheRing: Bool
    WhichSpecialPower: Int
    ObjectFilter: t.ObjectFilter
    TriggerSound: Sound
    MustFinishAbility: Bool
    LoseStealthOnTrigger: Bool
    PreTriggerUnstealthTime: Int
    GenerateUncontrollableFear: Bool


class TeleportSpecialAbilityUpdate(Behavior):
    SpecialPowerTemplate: SpecialPower
    UnpackingVariation: Int
    UnpackTime: Int
    PackTime: Int
    ApproachRequiresLOS: Bool
    BusyForDuration: Int
    DestinationWeaponName: t.WeaponRef
    PreparationTime: Int
    SourceWeaponName: t.WeaponRef
    MaxDistance: Float


class ToggleDeploySpecialAbilityUpdate(Behavior):
    SpecialPowerTemplate: SpecialPower
    IgnoreFacingCheck: Bool
    SoundDeploy: Sound
    SoundUndeploy: Sound


class ToggleHiddenSpecialAbilityUpdate(Behavior):
    SpecialPowerTemplate: SpecialPower
    UnpackingVariation: Int
    StartAbilityRange: Float
    UnpackTime: Int
    PreparationTime: Int
    PersistentPrepTime: Int
    PackTime: Int
    AwardXPForTriggering: Int
    EffectDuration: Int
    ShowPalantirTimer: Bool


class ToggleMountedSpecialAbilityUpdate(Behavior):
    SpecialPowerTemplate: SpecialPower
    UnpackTime: Int
    PreparationTime: Int
    PersistentPrepTime: Int
    PackTime: Int
    AwardXPForTriggering: Int
    OpacityTarget: Float
    TriggerInstantlyOnCreate: Bool
    CancelDisguiseWhenDismounting: Bool
    StartAbilityRange: Float
    MountedTemplate: Object
    SynchronizeTimerOnSpecialPower: List[SpecialPower]
    IgnoreFacingCheck: Bool


class AutoHealBehavior(UpgradeBehavior):
    ForbiddenKindOf: List[e.KindOf]
    SkipSelfForHealing: Bool
    ButtonTriggered: Bool
    SingleBurst: Bool
    HealingAmount: Int
    HealingDelay: Int
    Radius: Int
    KindOf: List[e.KindOf]
    StartHealingDelay: Int
    AffectsWholePlayer: Bool
    AffectsContained: Bool
    HealOnlyIfNotUnderAttack: Bool
    HealOnlyIfNotInCombat: Bool
    HealOnlyOthers: Bool
    NonStackable: Bool
    RespawnNearbyHordeMembers: Bool
    RespawnMinimumDelay: Int
    UnitHealPulseFX: FXList
    RespawnFXList: FXList


class WallHubBehavior(Behavior):
    SegmentTemplateName: List[Object]
    DefaultSegmentTemplateName: Object
    HubCapTemplateName: Object
    CliffCapTemplateName: Object
    ShoreCapTemplateName: Object
    BorderCapTemplateName: Object
    ElevatedSegmentTemplateName: Object
    StaggeredBuildFactor: Int
    BuilderRadius: Float
    MaxBuildoutDistance: Float
    Options: List[e.Options]


class GettingBuiltBehavior(Behavior):
    WorkerName: Object
    EvilWorkerName: Object
    TestFaction: Bool
    SpawnTimer: Float
    RebuildWhenDead: Bool
    HealWeapon: Weapon
    RebuildTimeSeconds: Float
    PercentOfBuildCostToRebuildPristine: Float
    PercentOfBuildCostToRebuildDamaged: Float
    PercentOfBuildCostToRebuildReallyDamaged: Float
    PercentOfBuildCostToRebuildRubble: Float
    DisallowRebuildFilter: ObjectFilter
    DisallowRebuildRange: Float
    UseSpawnTimerWithoutWorker: Bool
    SelfBuildingLoop: Sound
    SelfRepairFromDamageLoop: Sound
    SelfRepairFromRubbleLoop: Sound


class CastleMemberBehavior(Behavior):
    UnderAttackEvaEventIfKeep: EvaEvent
    UnderAttackAllyEvaEventIfKeep: EvaEvent
    StoreUpgradePrice: Bool
    CountsForEvaCastleBreached: Bool
    CampDestroyedOwnerEvaEvent: EvaEvent
    CampDestroyedAllyEvaEvent: EvaEvent
    CampDestroyedAttackerEvaEvent: EvaEvent
    BeingBuiltSound: Sound


class BuildingBehavior(Behavior):
    NightWindowName: SubObject
    FireWindowName: SubObject
    GlowWindowName: SubObject
    FireName: SubObject


class BridgeScaffoldBehavior(Behavior):
    pass


class BridgeTowerBehavior(Behavior):
    pass


class RampageBehavior(Behavior):
    RampageHealthThreshold: Float
    RampageLifeTimer: Int
    RampageAngryLifeTimer: Int
    RampageResetTimer: Int
    RampageEnemyCheckRange: Float
    RampageEnemyThreshold: Int
    RequiredUpgrade: List[Upgrade]


class EnragedBehavior(Behavior):
    EnragedLifeTimer: Float


class EntEnragedUpdate(Behavior):
    EnragedLifeTimer: Float
    HatedObjectFilter: ObjectFilter
    FriendlyDeadFilter: ObjectFilter
    EnragedTime: Int
    TimeUntilCanRageAgain: Int
    EnragedTransitionTime: Int
    EnragedTransitionFX: FXList
    EnragedOnBuffFX: FXList
    EnragedOffBuffFX: FXList
    ScanDelayTime: Int
    ScanDistance: Float


class HitReactionBehavior(Behavior):
    HitReactionLifeTimer1: Int
    HitReactionLifeTimer2: Int
    HitReactionLifeTimer3: Int
    HitReactionThreshold1: Float
    HitReactionThreshold2: Float
    HitReactionThreshold3: Float
    FastHitsResetReaction: Bool
    HitsParalyze: Bool


class ClickReactionBehavior(Behavior):
    ClickReactionTimer: Int
    ReactionFrames1: Int
    ReactionFrames2: Int
    ReactionFrames3: Int
    ReactionFrames4: Int
    ReactionFrames5: Int


class SiegeDockingBehavior(Behavior):
    DUMMY: Int


class AutoAbilityBehavior(Behavior):
    SpecialAbility: SpecialPower
    MaxScanRange: Float
    MinScanRange: Float
    WorkingRadius: Float
    StartsActive: Bool
    BaseMaxRangeFromStartPos: Bool
    AdjustAttackMeleePosition: Bool
    Query: List[Tuple[Int, ObjectFilter]]
    AllowSelf: Bool
    IdleTimeSeconds: Float
    ForbiddenStatus: ObjectStatus


class DualWeaponBehavior(Behavior):
    SwitchWeaponOnCloseRangeDistance: Float
    UseCloseRangeWhileMounted: Bool
    MinimumSwitchTime: Int
    UseHordeRangeWeapon: Bool
    UseRealVictimRange: Bool


class AimWeaponBehavior(Behavior):
    AimLowThreshold: Float
    AimHighThreshold: Float
    AimNearDistance: Float
    AimFarDistance: Float


class BezierProjectileBehavior(Behavior):
    TumbleRandomly: Bool
    DetonateCallsKill: Bool
    PreLandingEmotionAffectsAllies: Bool
    OrientToFlightPath: Bool
    FirstHeight: Float
    SecondHeight: Float
    FirstPercentIndent: Float
    SecondPercentIndent: Float
    CrushStyle: Bool
    DieOnImpact: Bool
    FinalStuckTime: Int
    PreLandingStateTime: Int
    BounceCount: Int
    BounceDistance: Float
    BounceFirstHeight: Float
    BounceSecondHeight: Float
    BounceFirstPercentIndent: Float
    BounceSecondPercentIndent: Float
    GarrisonHitKillRequiredKindOf: List[KindOf]
    GarrisonHitKillForbiddenKindOf: List[KindOf]
    GarrisonHitKillCount: Int
    GroundHitWeapon: Weapon
    GroundBounceWeapon: Weapon
    FlightPathAdjustDistPerSecond: Float
    IgnoreTerrainHeight: Bool
    FirstPercentHeight: Float
    SecondPercentHeight: Float
    CurveFlattenMinDist: Float
    PreLandingEmotion: EmotionTypes
    PreLandingEmotionRadius: Float
    InvisibleFrames: Int
    FadeInTime: Int
    PostLandingStateTime: Int
    PostLandingEmotion: EmotionTypes
    PostLandingEmotionRadius: Float
    GarrisonHitKillFX: FXList
    GroundHitFX: FXList
    GroundBounceFX: FXList


class MissileUpdate(Behavior):
    TumbleRandomly: Bool
    DetonateCallsKill: Bool
    OrientToFlightPath: Bool
    FirstHeight: Float
    SecondHeight: Float
    FirstPercentIndent: Float
    SecondPercentIndent: Float
    CrushStyle: Bool
    DieOnImpact: Bool
    FinalStuckTime: Int
    PreLandingStateTime: Int
    BounceCount: Int
    BounceDistance: Float
    BounceFirstHeight: Float
    BounceSecondHeight: Float
    BounceFirstPercentIndent: Float
    BounceSecondPercentIndent: Float
    GarrisonHitKillRequiredKindOf: List[KindOf]
    GarrisonHitKillForbiddenKindOf: List[KindOf]
    GarrisonHitKillCount: Int
    GroundHitWeapon: Weapon
    GroundBounceWeapon: Weapon
    FlightPathAdjustDistPerSecond: Float
    IgnoreTerrainHeight: Bool
    FirstPercentHeight: Float
    SecondPercentHeight: Float
    CurveFlattenMinDist: Float
    PreLandingEmotion: EmotionTypes
    PreLandingEmotionRadius: Float
    InvisibleFrames: Int
    FadeInTime: Int
    PostLandingStateTime: Int
    PostLandingEmotion: EmotionTypes
    PostLandingEmotionRadius: Float
    FuelLifetime: Int
    IgnitionDelay: Int
    DistanceToTravelBeforeTurning: Float
    DistanceToTargetBeforeDiving: Float
    DetonateOnNoFuel: Bool
    ExhaustTemplate: FXParticleSystem
    GarrisonHitKillFX: FXList
    GroundHitFX: FXList
    GroundBounceFX: FXList
    IgnitionFX: FXList


class PhysicsBehavior(Behavior):
    Mass: Float
    AerodynamicFriction: Float
    ForwardFriction: Float
    LateralFriction: Float
    ZFriction: Float
    CenterOfMassOffset: Float
    AllowCollideForce: Bool
    PitchRollYawFactor: Float
    ShockResistance: Float
    ShockMaxYaw: Float
    ShockMaxPitch: Float
    ShockMaxRoll: Float
    MinFallHeightForDamage: Float
    FallHeightDamageFactor: Float
    TumbleRandomly: Bool
    AllowBouncing: Bool
    KillWhenRestingOnGround: Bool
    GravityMult: Float
    OrientToFlightPath: Bool
    ShockStunnedTimeLow: Int
    ShockStunnedTimeHigh: Int
    ShockStandingTime: Int
    FirstHeight: Float
    SecondHeight: Float
    FirstPercentIndent: Float
    SecondPercentIndent: Float
    BounceCount: Int
    BounceFirstHeight: Float
    BounceSecondHeight: Float
    BounceFirstPercentIndent: Float
    BounceSecondPercentIndent: Float
    IgnoreTerrainHeight: Bool
    FirstPercentHeight: Float
    SecondPercentHeight: Float
    CurveFlattenMinDist: Float
    GroundHitFX: FXList
    GroundBounceFX: FXList


class DieBehavior(Behavior):
    DeathType: DeathTypeFilter
    DeathTypes: DeathTypeFilter
    ExemptStatus: ObjectStatus
    RequiredStatus: ObjectStatus
    DamageAmountRequired: Float
    MinKillerAngle: Degrees
    MaxKillerAngle: Degrees


class InstantDeathBehavior(DieBehavior):
    OCL: ObjectCreationList
    Weapon: io.Weapon
    FX: FXList
    Sound: t.Sound


class SlowDeathBehavior(DieBehavior):
    SinkRate: Float
    ProbabilityModifier: Int
    ModifierBonusPerOverkillPercent: Float
    DeathFlags: e.DeathFlags
    FadeTime: Int
    FadeDelay: Int
    ShadowWhenDead: Bool
    SinkDelay: Int
    SinkDelayVariance: Int
    DestructionDelay: Int
    DestructionDelayVariance: Int
    DecayBeginTime: Int
    OCL: GroupedByKey[SlowDeathPhase, ObjectCreationList]
    Weapon: GroupedByKey[SlowDeathPhase, io.Weapon]
    FX: GroupedByKey[SlowDeathPhase, FXList]
    Sound: GroupedByKey[SlowDeathPhase, t.Sound]
    FlingForce: Int
    FlingForceVariance: Int
    FlingPitch: Int
    FlingPitchVariance: Int
    DoNotRandomizeMidpoint: Bool


class ShipSlowDeathBehavior(SlowDeathBehavior):
    pass


class BattleBusSlowDeathBehavior(SlowDeathBehavior):
    FXStartUndeath: FXList
    OCLStartUndeath: ObjectCreationList
    FXHitGround: FXList
    OCLHitGround: ObjectCreationList
    ThrowForce: Float
    PercentDamageToPassengers: Float
    EmptyHulkDestructionDelay: Int


class HelicopterSlowDeathBehavior(SlowDeathBehavior):
    SpiralOrbitTurnRate: Float
    SpiralOrbitForwardSpeed: Float
    SpiralOrbitForwardSpeedDamping: Float
    MaxBraking: Int
    SoundDeathLoop: Sound
    MinSelfSpin: Int
    MaxSelfSpin: Int
    SelfSpinUpdateDelay: Int
    SelfSpinUpdateAmount: Int
    FallHowFast: Float
    MinBladeFlyOffDelay: Int
    MaxBladeFlyOffDelay: Int
    AttachParticle: ParticleSystem
    AttachParticleBone: Bone
    BladeObjectName: Object
    BladeBoneName: Bone
    OCLEjectPilot: ObjectCreationList
    FXBlade: FXList
    OCLBlade: ObjectCreationList
    FXHitGround: FXList
    OCLHitGround: ObjectCreationList
    FXFinalBlowUp: FXList
    OCLFinalBlowUp: ObjectCreationList
    DelayFromGroundToFinalDeath: Int
    FinalRubbleObject: Object


class JetSlowDeathBehavior(SlowDeathBehavior):
    FXOnGroundDeath: FXList
    OCLOnGroundDeath: ObjectCreationList
    RollRate: Float
    RollRateDelta: Float
    PitchRate: Float
    FallHowFast: Float
    FXInitialDeath: FXList
    OCLInitialDeath: ObjectCreationList
    DelaySecondaryFromInitialDeath: Int
    FXSecondary: FXList
    OCLSecondary: ObjectCreationList
    FXHitGround: FXList
    OCLHitGround: ObjectCreationList
    DelayFinalBlowUpFromHitGround: Int
    FXFinalBlowUp: FXList
    OCLFinalBlowUp: ObjectCreationList


class NeutronMissileSlowDeathBehavior(SlowDeathBehavior):
    ScorchMarkSize: Int
    FXList: t.FXList
    Blast1Enabled: Bool
    Blast1Delay: Int
    Blast1ScorchDelay: Int
    Blast1InnerRadius: Float
    Blast1OuterRadius: Float
    Blast1MaxDamage: Float
    Blast1MinDamage: Float
    Blast1ToppleSpeed: Float
    Blast1PushForce: Float
    Blast2Enabled: Bool
    Blast2Delay: Int
    Blast2ScorchDelay: Int
    Blast2InnerRadius: Float
    Blast2OuterRadius: Float
    Blast2MaxDamage: Float
    Blast2MinDamage: Float
    Blast2ToppleSpeed: Float
    Blast2PushForce: Float
    Blast3Enabled: Bool
    Blast3Delay: Int
    Blast3ScorchDelay: Int
    Blast3InnerRadius: Float
    Blast3OuterRadius: Float
    Blast3MaxDamage: Float
    Blast3MinDamage: Float
    Blast3ToppleSpeed: Float
    Blast3PushForce: Float
    Blast4Enabled: Bool
    Blast4Delay: Int
    Blast4ScorchDelay: Int
    Blast4InnerRadius: Float
    Blast4OuterRadius: Float
    Blast4MaxDamage: Float
    Blast4MinDamage: Float
    Blast4ToppleSpeed: Float
    Blast4PushForce: Float
    Blast5Enabled: Bool
    Blast5Delay: Int
    Blast5ScorchDelay: Int
    Blast5InnerRadius: Float
    Blast5OuterRadius: Float
    Blast5MaxDamage: Float
    Blast5MinDamage: Float
    Blast5ToppleSpeed: Float
    Blast5PushForce: Float
    Blast6Enabled: Bool
    Blast6Delay: Int
    Blast6ScorchDelay: Int
    Blast6InnerRadius: Float
    Blast6OuterRadius: Float
    Blast6MaxDamage: Float
    Blast6MinDamage: Float
    Blast6ToppleSpeed: Float
    Blast6PushForce: Float
    Blast7Enabled: Bool
    Blast7Delay: Int
    Blast7ScorchDelay: Int
    Blast7InnerRadius: Float
    Blast7OuterRadius: Float
    Blast7MaxDamage: Float
    Blast7MinDamage: Float
    Blast7ToppleSpeed: Float
    Blast7PushForce: Float
    Blast8Enabled: Bool
    Blast8Delay: Int
    Blast8ScorchDelay: Int
    Blast8InnerRadius: Float
    Blast8OuterRadius: Float
    Blast8MaxDamage: Float
    Blast8MinDamage: Float
    Blast8ToppleSpeed: Float
    Blast8PushForce: Float
    Blast9Enabled: Bool
    Blast9Delay: Int
    Blast9ScorchDelay: Int
    Blast9InnerRadius: Float
    Blast9OuterRadius: Float
    Blast9MaxDamage: Float
    Blast9MinDamage: Float
    Blast9ToppleSpeed: Float
    Blast9PushForce: Float


class SpawnBehavior(UpgradeBehavior):
    SlavesHaveFreeWill: Bool
    DeathType: DeathTypeFilter
    ExemptStatus: ObjectStatus
    RequiredStatus: ObjectStatus
    DamageAmountRequired: Float
    MinKillerAngle: Degrees
    MaxKillerAngle: Degrees
    SpawnNumber: Int
    SpawnReplaceDelay: Int
    OneShot: Bool
    CanReclaimOrphans: Bool
    AggregateHealth: Bool
    ExitByBudding: Bool
    SpawnTemplateName: List[Object]
    SpawnedRequireSpawner: Bool
    PropagateDamageTypesToSlavesWhenExisting: DamageTypeFilter
    InitialBurst: Int
    RespectCommandLimit: Bool
    FadeInTime: Int
    KillSpawnsBasedOnModelConditionState: Bool
    ShareUpgrades: Bool
    SpawnInsideBuilding: Bool
    DeathTypes: DeathTypeFilter


class GiantBirdSlowDeathBehavior(SlowDeathBehavior):
    OCLHitGround: ObjectCreationList
    DelayFromGroundToFinalDeath: Int
    CrashAvoidKindOfs: List[KindOf]
    CrashAvoidRadius: Float
    CrashAvoidStrength: Float
    NeedToMaintainFlailingHeight: Bool
    FXHitGround: FXList


class ContainBehavior(Behavior):
    """Marker base for every contain module; carries no keys of its own."""


class ParachuteContain(ContainBehavior):
    PitchRateMax: Int
    RollRateMax: Int
    LowAltitudeDamping: Float
    ParachuteOpenDist: Float
    AllowInsideKindOf: List[KindOf]
    ParachuteOpenSound: Sound


class OpenContain(ContainBehavior):
    AllowInsideKindOf: List[KindOf]
    ForbidInsideKindOf: List[KindOf]
    ContainMax: Int
    EnterSound: Sound
    ExitSound: Sound
    DamagePercentToUnits: Float
    PassengersInTurret: Bool
    AllowAlliesInside: Bool
    AllowNeutralInside: Bool
    AllowEnemiesInside: Bool
    ShouldDrawPips: Bool


class GarrisonContain(OpenContain):
    MobileGarrison: Bool
    InitialRoster: Tuple[Object, Int]
    ImmuneToClearBuildingAttacks: Bool
    IsEnclosingContainer: Bool
    ObjectStatusOfContained: List[ObjectStatus]
    PassengerFilter: ObjectFilter


class HealContain(GarrisonContain):
    TimeForFullHeal: Int


class TunnelContain(GarrisonContain):
    TimeForFullHeal: Int
    PassengerBonePrefix: List[KeyValuePair]
    EntryPosition: Coords
    EntryOffset: Coords
    ExitOffset: Coords
    KillPassengersOnDeath: Bool
    ShowPips: Bool
    ExitDelay: Int
    NumberOfExitPaths: Int
    AllowOwnPlayerInsideOverride: Bool
    EjectPassengersOnDeath: Bool


class TransportContain(OpenContain):
    PassengersAllowedToFire: Bool
    Slots: Int
    BurnedDeathToUnits: Bool
    ExitDelay: Int
    GoAggressiveOnExit: Bool
    DoorOpenTime: Int
    ScatterNearbyOnExit: Bool
    OrientLikeContainerOnExit: Bool
    KeepContainerVelocityOnExit: Bool
    ExitPitchRate: Int
    ExitBone: Bone
    DestroyRidersWhoAreNotFreeToExit: Bool
    InitialPayload: List[Tuple[Object, Int]]
    NumberOfExitPaths: Int
    ArmedRidersUpgradeMyWeaponSet: Bool
    WeaponBonusPassedToPassengers: Bool
    DelayExitInAir: Bool
    ObjectStatusOfContained: List[ObjectStatus]
    PassengerFilter: ObjectFilter
    ShowPips: Bool
    TypeOneForWeaponSet: KindOf
    TypeTwoForWeaponSet: KindOf
    TypeOneForWeaponState: KindOf
    TypeTwoForWeaponState: KindOf
    PassengerBonePrefix: List[KeyValuePair]
    KillPassengersOnDeath: Bool
    ManualPickUpFilter: ObjectFilter
    EjectPassengersOnDeath: Bool
    CanGrabStructure: Bool
    GrabWeapon: Weapon
    FireGrabWeaponOnVictim: Bool
    ReleaseSnappyness: Float
    ForceOrientationContainer: Bool
    CollidePickup: Bool
    AllowOwnPlayerInsideOverride: Bool
    BoneSpecificConditionState: List[Untyped]
    FadeFilter: ObjectFilter
    UpgradeCreationTrigger: List[Tuple[Upgrade, Object, Int]]
    FadePassengerOnEnter: Bool
    EnterFadeTime: Int
    FadePassengerOnExit: Bool
    ExitFadeTime: Int
    ConditionForEntry: ContainCondition


class HelixContain(TransportContain):
    pass


class InternetHackContain(TransportContain):
    pass


class RailedTransportContain(TransportContain):
    pass


class OverlordContain(TransportContain):
    PayloadTemplateName: Object
    ExperienceSinkForRider: Bool


class RiderChangeContain(TransportContain):
    # `Rider1`..`Rider7` are `<object> <modelCondition> <weaponState> <status> <commandSet>
    # <locomotorSet>` tuples; kept raw for now.
    Rider1: Untyped
    Rider2: Untyped
    Rider3: Untyped
    Rider4: Untyped
    Rider5: Untyped
    Rider6: Untyped
    Rider7: Untyped
    ScuttleDelay: Int
    ScuttleStatus: ObjectStatus
    KillRiderWhenVehicleDies: Bool
    ObjectStatusOfCrew: List[ObjectStatus]
    InitialCrew: Tuple[Object, Int]
    CrewFilter: ObjectFilter
    CrewMax: Int
    TransferSelection: Bool


class HordeContain(ContainBehavior):
    nested_attributes = {"MeleeBehavior": ["MeleeBehavior"]}  # class in `model.misc_blocks`

    ObjectStatusOfContained: List[ObjectStatus]
    InitialPayload: List[Tuple[Object, Int]]
    Slots: Int
    PassengerFilter: ObjectFilter
    ShowPips: Bool
    ThisFormationIsTheMainFormation: Bool
    BannerCarriersAllowed: List[Object]
    BannerCarrierPosition: t.BannerCarrierPosition
    RankInfo: t.RankInfo
    RanksToReleaseWhenAttacking: List[Int]
    ComboHordes: t.ComboHorde
    ComboHorde: t.ComboHorde
    UseSlowHordeMovement: Bool
    MeleeAttackLeashDistance: Int
    MachineAllowed: Bool
    MachineType: Object
    AlternateFormation: Object
    BackUpMinDelayTime: Int
    BackUpMaxDelayTime: Int
    BackUpMinDistance: Int
    BackUpMaxDistance: Int
    BackupPercentage: Float
    AttributeModifiers: List[ModifierList]
    RanksThatStopAdvance: List[Int]
    RanksToJustFreeWhenAttacking: List[Int]
    NotComboFormation: Bool
    UsePorcupineBody: Bool
    SplitHorde: List[KeyValuePair]
    UseMarchingAnims: Bool
    ForcedLocomotorSet: LocomotorSetType
    UpdateWeaponSetFlagsOnHordeToo: Bool
    RankSplit: Bool
    SplitHordeNumber: Int
    FrontAngle: Float
    FlankedDelay: Int
    IsPorcupineFormation: Bool
    MinimumHordeSize: Int
    VisionRearOverride: Float
    VisionSideOverride: Float
    BannerCarrierMinLevel: Int
    BannerCarrierDestroyHordeOnDeath: Bool
    BannerCarrierHordeDeathType: DeathTypeFilter
    LivingWorldOverloadTemplate: Object
    ConditionForEntry: ContainCondition
    RandomOffset: Coords


class HorseHordeContain(HordeContain):
    pass


class AODHordeContain(HordeContain):
    FrequencyScale: Float
    FrequencyRandomness: Float
    AmplitudeScale: Int
    AmplitudeRandomness: Float
    StillAmplitude: Float
    FrequencyScaleZ: Float
    FrequencyRandomnessZ: Float
    AmplitudeScaleZ: Int
    AmplitudeRandomnessZ: Float
    StillAmplitudeZ: Float
    LargeUnitHeightFactor: Float
    LargeUnitMinHeight: Float
    LargeUnitMaxHeight: Float
    LargeUnitTimeout: Int
    LargeUnitTailOff: Float
    ScatterSpeedFactor: Float
    ScatterRandomness: Float


class HordeTransportContain(ContainBehavior):
    ObjectStatusOfContained: List[ObjectStatus]
    Slots: Int
    EnterSound: Sound
    ExitSound: Sound
    DamagePercentToUnits: Float
    PassengerFilter: ObjectFilter
    AllowEnemiesInside: Bool
    AllowNeutralInside: Bool
    AllowAlliesInside: Bool
    AllowOwnPlayerInsideOverride: Bool
    ExitDelay: Int
    NumberOfExitPaths: Int
    ForceOrientationContainer: Bool
    PassengerBonePrefix: List[KeyValuePair]
    EjectPassengersOnDeath: Bool
    ShowPips: Bool
    FadeFilter: ObjectFilter
    FadePassengerOnEnter: Bool
    EnterFadeTime: Int
    FadePassengerOnExit: Bool
    ExitFadeTime: Int
    KillPassengersOnDeath: Bool
    InitialPayload: List[Tuple[Object, Int]]
    ConditionForEntry: ContainCondition


class HordeGarrisonContain(HordeTransportContain):
    ContainMax: Int
    MaxHordeCapacity: Int
    EntryPosition: Coords
    EntryOffset: Coords
    ExitOffset: Coords


class SiegeEngineContain(ContainBehavior):
    ObjectStatusOfCrew: List[ObjectStatus]
    Slots: Int
    DamagePercentToUnits: Float
    PassengerFilter: ObjectFilter
    KillPassengersOnDeath: Bool
    AllowAlliesInside: Bool
    AllowEnemiesInside: Bool
    AllowNeutralInside: Bool
    CrewFilter: ObjectFilter
    CrewMax: Int
    InitialCrew: Tuple[Object, Int]
    ExitDelay: Int
    NumberOfExitPaths: Int
    GoAggressiveOnExit: Bool
    TypeOneForWeaponSet: KindOf
    EjectPassengersOnDeath: Bool
    PassengerBonePrefix: List[KeyValuePair]
    BoneSpecificConditionState: List[Untyped]
    ObjectStatusOfContained: List[ObjectStatus]
    ShowPips: Bool
    SpeedPercentPerCrew: Float
    ConditionForEntry: ContainCondition
    TransferSelection: Bool
    EnterSound: Sound
    ExitSound: Sound
    UpgradeCreationTrigger: List[Tuple[Upgrade, Object, Int]]


class HordeSiegeEngineContain(SiegeEngineContain):
    FadeFilter: ObjectFilter
    FadePassengerOnEnter: Bool
    EnterFadeTime: Int
    FadePassengerOnExit: Bool
    ExitFadeTime: Int
    FadeReverse: Bool


class ProductionQueueHordeContain(ContainBehavior):
    ObjectStatusOfContained: List[ObjectStatus]
    ContainMax: Int
    DamagePercentToUnits: Float
    PassengerFilter: ObjectFilter
    AllowEnemiesInside: Bool
    AllowNeutralInside: Bool
    AllowAlliesInside: Bool
    NumberOfExitPaths: Int
    PassengerBonePrefix: List[KeyValuePair]
    EntryPosition: Coords
    EntryOffset: Coords
    ExitOffset: Coords
    EnterSound: Sound
    DestinationTemplate: Tuple[Object, ObjectFilter]


class SlaughterHordeContain(ContainBehavior, UpgradeBehavior):
    PassengerFilter: ObjectFilter
    ObjectStatusOfContained: List[ObjectStatus]
    CashBackPercent: Float
    ContainMax: Int
    MaxHordeCapacity: Int
    AllowAlliesInside: Bool
    AllowEnemiesInside: Bool
    AllowNeutralInside: Bool
    EnterSound: Sound
    EntryOffset: Coords
    ExitOffset: Coords
    EntryPosition: Coords


class CitadelSlaughterHordeContain(SlaughterHordeContain):
    AllowOwnPlayerInsideOverride: Bool
    StatusForRingEntry: ObjectStatus
    UpgradeForRingEntry: Upgrade
    ObjectToDestroyForRingEntry: ObjectFilter
    FXForRingEntry: FXList


class CaveContain(OpenContain):
    CaveIndex: Int


class SpawnUnitBehavior(Behavior):
    UnitName: Object
    UnitCommand: CommandButton
    SpawnOnce: Bool


class WargBehavior(Behavior):
    pass


class DynamicPortalBehaviour(UpgradeBehavior):
    NumberOfBones: Int
    GenerateNow: Bool
    AboveWall: Int
    TopAttackPos: Coords
    TopAttackRadius: Float
    AllowEnemies: Bool
    ActivationDelaySeconds: Float
    ObjectFilter: t.ObjectFilter
    BonePrefix: Untyped
    WayPoint: List[KeyValuePair]
    Link: List[KeyValuePair]
    WallBoundsMesh: Untyped


class FakePathfindPortalBehaviour(UpgradeBehavior):
    AllowEnemies: Bool
    AllowNonSkirmishAIUnits: Bool


class MineshaftPortalBehaviour(UpgradeBehavior):
    AllowEnemies: Bool
    AllowNonSkirmishAIUnits: Bool


class CritterEmitterUpdate(Behavior):
    FX: FXList
    SpawnObject: Object
    ReloadTime: Int


class StancesBehavior(Behavior):
    StanceTemplate: io.StanceTemplate


class PropagandaTowerBehavior(Behavior):
    AffectsSelf: Bool
    Radius: Float
    DelayBetweenUpdates: Int
    HealPercentEachSecond: Float
    UpgradedHealPercentEachSecond: Float
    UpgradeRequired: Upgrade
    PulseFX: FXList
    UpgradedPulseFX: FXList


class TerrainResourceBehavior(Behavior):
    Radius: Float
    MaxIncome: Int
    IncomeInterval: Int
    HighPriority: Bool
    Visible: Bool
    Upgrade: io.Upgrade
    UpgradeBonusPercent: Float
    UpgradeMustBePresent: ObjectFilter


class FireWeaponWhenDamagedBehavior(Behavior):
    StartsActive: Bool
    ReactionWeaponPristine: Weapon
    ReactionWeaponDamaged: Weapon
    ReactionWeaponReallyDamaged: Weapon
    ReactionWeaponRubble: Weapon
    ContinuousWeaponPristine: Weapon
    ContinuousWeaponDamaged: Weapon
    ContinuousWeaponReallyDamaged: Weapon
    ContinuousWeaponRubble: Weapon
    DamageTypes: DamageTypeFilter
    DamageAmount: Float
    TriggeredBy: List[Upgrade]
    ConflictsWith: List[Upgrade]
    RequiresAllTriggers: Bool
    RequiresAllConflictingTriggers: Bool
    Permanent: Bool
    CustomAnimAndDuration: AnimAndDuration


class FireWeaponWhenDeadBehavior(Behavior):
    StartsActive: Bool
    ActiveDuringConstruction: Bool
    DelayTime: Int
    DeathWeapon: Weapon
    WeaponOffset: Coords
    TriggeredBy: List[Upgrade]
    ConflictsWith: List[Upgrade]
    RequiresAllTriggers: Bool
    RequiresAllConflictingTriggers: Bool
    Permanent: Bool
    DeathType: DeathTypeFilter
    ExemptStatus: ObjectStatus
    RequiredStatus: ObjectStatus
    DamageAmountRequired: Float
    MinKillerAngle: Degrees
    MaxKillerAngle: Degrees
    CustomAnimAndDuration: AnimAndDuration
    DeathTypes: DeathTypeFilter


class PoisonedBehavior(Behavior):
    PoisonDamageInterval: Int
    PoisonDuration: Int


class RebuildHoleBehavior(Behavior):
    WorkerObjectName: Object
    WorkerRespawnDelay: Int
    HoleHealthRegen_PerSecond: Float

    # The engine key carries a literal `%` (`HoleHealthRegen%PerSecond = 0.5%`), not a valid
    # Python identifier; alias it to the field above (the `%` value converts as a fraction).
    field_aliases = {"HoleHealthRegen%PerSecond": "HoleHealthRegen_PerSecond"}


class SupplyWarehouseCripplingBehavior(Behavior):
    SelfHealSupression: Int
    SelfHealDelay: Int
    SelfHealAmount: Float


class ClearanceTestingSlowDeathBehavior(SlowDeathBehavior):
    ClearanceGeometryMajorRadius: Float
    ClearanceGeometryMinorRadius: Float
    ClearanceGeometryRotationAnchorOffset: Coords
    ClearanceGeometryHeight: Float
    ClearanceGeometryIsSmall: Bool
    ClearanceGeometryOffset: Coords
    ClearanceMaxHeight: Float
    ClearanceMaxHeightFraction: Float
    ClearanceMinHeight: Float
    ClearanceMinHeightFraction: Float
    ClearanceGeometry: GeometryType


class RunOffMapBehavior(Behavior):
    RunToLocation: Coords
    RequiresSpecificTrigger: Bool
    RunOffMapWaypointName: Untyped
    DieOnMap: Bool


class ReplenishUnitsBehavior(Behavior):
    StartsActive: Bool
    ReplenishDelay: Int
    ReplenishRadius: Float
    NoReplenishIfEnemyWithinRadius: Float
    ReplenishStatii: ObjectStatus
    ReplenishHordeMembersOnly: Bool
    TriggeredBy: List[Upgrade]
    ConflictsWith: List[Upgrade]
    RequiresAllTriggers: Bool
    RequiresAllConflictingTriggers: Bool
    Permanent: Bool
    ReplenishFXList: FXList
    CustomAnimAndDuration: AnimAndDuration


class SlaveWatcherBehavior(Behavior):
    RemoveUpgrade: Upgrade
    GrantUpgrade: Upgrade
    ShareUpgrades: Bool
    LetSlaveLive: Bool


class AnnounceBirthAndDeathBehavior(Behavior):
    pass


class DestroyDie(DieBehavior):
    pass


class FXListDie(DieBehavior):
    OrientToObject: Bool
    DeathFX: FXList
    StartsActive: Bool
    ConflictsWith: List[Upgrade]
    TriggeredBy: List[Upgrade]


class CrushDie(DieBehavior):
    TotalCrushSoundPercent: Int
    BackEndCrushSoundPercent: Int
    FrontEndCrushSoundPercent: Int
    TotalCrushSound: Sound
    BackEndCrushSound: Sound
    FrontEndCrushSound: Sound


class HeroDie(DieBehavior):
    SpecialPowerTemplate: SpecialPower


class CreateCrateDie(DieBehavior):
    CrateData: io.CrateData


class RefundDie(DieBehavior):
    UpgradeRequired: Upgrade
    BuildingRequired: ObjectFilter
    RefundPercent: Float


class CreateObjectDieBehavior(DieBehavior):
    CreationList: ObjectCreationList


class CreateObjectDie(CreateObjectDieBehavior):
    UpgradeRequired: List[Upgrade]
    DebrisPortionOfSelf: Object
    TransferPreviousHealth: Bool


class CreateObjectDieIfEldestKindof(CreateObjectDie):
    ObjectFilter: t.ObjectFilter


class DamageFilteredCreateObjectDie(CreateObjectDieBehavior):
    DamageTypeTriggersInstantly: DamageType
    DamageTypeTriggersForDuration: DamageType
    PostFilterTriggeredDuration: Int


class SpecialPowerCompletionDie(DieBehavior):
    SpecialPowerTemplate: SpecialPower


class RebuildHoleExposeDie(DieBehavior):
    HoleName: Object
    HoleMaxHealth: Float
    TransferAttackers: Bool
    FadeInTimeSeconds: Float


class UpgradeDie(DieBehavior):
    UpgradeToRemove: Upgrade


class KeepObjectDie(DieBehavior):
    CollapsingTime: Int
    StayOnRadar: Bool


class EjectPilotDie(DieBehavior):
    GroundCreationList: ObjectCreationList
    AirCreationList: ObjectCreationList
    VeterancyLevels: List[Untyped]


class DamDie(DieBehavior):
    pass


class AssistedTargetingUpdate(Behavior):
    AssistingClipSize: Int
    LaserFromAssisted: Object
    LaserToTarget: Object
    AssistingWeaponSlot: SlotTypes


class AutoFindHealingUpdate(Behavior):
    ScanRate: Int
    ScanRange: Float
    NeverHeal: Float
    AlwaysHeal: Float


class StealthDetectorUpdate(Behavior):
    DetectionRate: Int
    InitiallyDisabled: Bool
    DetectionRange: Float
    CanDetectWhileGarrisoned: Bool
    CanDetectWhileContained: Bool
    ExtraRequiredKindOf: List[KindOf]
    PingSound: Sound
    LoudPingSound: Sound
    IRParticleSysName: ParticleSystem
    IRBrightParticleSysName: ParticleSystem
    IRGridParticleSysName: ParticleSystem
    IRBeaconParticleSysName: ParticleSystem
    IRParticleSysBone: Bone
    CancelOneRingEffect: Bool
    RequiredUpgrade: Upgrade
    ExtraForbiddenKindOf: List[KindOf]


class BroadcastStealthUpdate(UpgradeBehavior):
    AllowKindOf: List[KindOf]
    Radius: Float
    DelayBetweenUpdates: Int
    PersistantConditions: ModelCondition


class StealthUpdate(Behavior):
    StealthDelay: Int
    StealthForbiddenConditions: List[ModelCondition]
    HintDetectableConditions: ObjectStatus
    FriendlyOpacityMin: Float
    FriendlyOpacityMax: Float
    PulseFrequency: Int
    MoveThresholdSpeed: Float
    InnateStealth: Bool
    OrderIdleEnemiesToAttackMeUponReveal: Bool
    DisguisesAsTeam: Bool
    RevealDistanceFromTarget: Float
    DisguiseFX: FXList
    DisguiseRevealFX: FXList
    DisguiseTransitionTime: Int
    DisguiseRevealTransitionTime: Int
    GrantedBySpecialPower: Bool
    EnemyDetectionEvaEvent: Opaque
    OwnDetectionEvaEvent: Opaque
    UseRiderStealth: Bool
    DetectedByAnyoneRange: Float
    RemoveTerrainRestrictionOnUpgrade: List[Upgrade]
    RevealWeaponSets: List[WeaponsetFlags]
    StartsActive: Bool
    DetectedByFriendliesOnly: Bool
    VoiceMoveToStealthyArea: Sound
    VoiceEnterStateMoveToStealthyArea: Sound
    OneRingDelayOn: Int
    OneRingDelayOff: Int
    RingAnimTimeOn: Int
    RingAnimTimeOff: Int
    RingDelayAfterRemoving: Int
    BecomeStealthedFX: FXList
    ExitStealthFX: FXList
    BecomeStealthedOneRingFX: FXList
    ExitStealthOneRingFX: FXList
    RequiredUpgradeNames: List[Upgrade]
    EvaEventDetectedEnemy: EvaEvent
    EvaEventDetectedAlly: EvaEvent
    EvaEventDetectedOwner: EvaEvent
    ForbiddenUpgradeNames: List[t.UpgradeRef]


class EvaAnnounceClientCreate(Behavior):
    DelayBeforeAnnouncementMS: Int
    OnlyIfVisible: Bool
    CountAsFirstSightedAnnoucement: Bool
    UseObjectsPosition: Bool
    CreateFakeRadarEvent: Bool
    AnnouncementEventEnemy: EvaEvent
    AnnouncementEventAlly: EvaEvent
    AnnouncementEventOwner: EvaEvent


class TerrainResourceClientBehavior(Behavior):
    pass


class ModelConditionAudioLoopClientBehavior(Behavior):
    ModelCondition: AudioLoopCondition


class RandomSoundSelectorClientBehavior(Behavior):
    Chance: Float
    RerollOnEveryFrame: Bool
    UnitSpecificSounds: Untyped
    VoicePriority: Int
    VoiceSelect: Sound
    VoiceSelectUnderConstruction: Sound
    VoiceSelectBattle: Sound
    VoiceMove: Sound
    VoiceMoveToHigherGround: Sound
    VoiceMoveOverWalls: Sound
    VoiceAttack: Sound
    VoiceAttackCharge: Sound
    VoiceFear: Sound
    VoiceCreated: List[Sound]
    VoiceTaskComplete: Sound
    VoiceDefect: Sound
    VoiceAttackAir: Sound
    VoiceGuard: Sound
    VoiceAlert: Sound
    VoiceFullyCreated: List[Sound]
    VoiceRetreatToCastle: Sound
    VoiceMoveToCamp: Sound
    VoiceAttackStructure: Sound
    VoiceAttackMachine: Sound
    VoiceMoveWhileAttacking: Sound
    VoiceCombineWithHorde: Sound
    VoiceEnterStateAttack: Sound
    VoiceEnterStateAttackCharge: Sound
    VoiceEnterStateAttackAir: Sound
    VoiceEnterStateAttackStructure: Sound
    VoiceEnterStateAttackMachine: Sound
    VoiceEnterStateMove: Sound
    VoiceEnterStateMoveToHigherGround: Sound
    VoiceEnterStateMoveOverWalls: Sound
    VoiceEnterStateRetreatToCastle: Sound
    VoiceEnterStateMoveToCamp: Sound
    VoiceEnterStateMoveWhileAttacking: Sound
    SoundMoveStart: Sound
    SoundMoveStartDamaged: Sound
    SoundMoveLoop: Sound
    SoundMoveLoopDamaged: Sound
    SoundAmbient: Sound
    SoundAmbientDamaged: Sound
    SoundAmbientReallyDamaged: Sound
    SoundAmbientRubble: Sound
    SoundAmbientBattle: Sound
    SoundStealthOn: Sound
    SoundStealthOff: Sound
    SoundCreated: Sound
    SoundOnDamaged: Sound
    SoundOnReallyDamaged: Sound
    SoundEnter: Sound
    SoundExit: Sound
    SoundPromotedVeteran: Sound
    SoundPromotedElite: Sound
    SoundPromotedHero: Sound
    SoundFallingFromPlane: Sound
    SoundImpact: Sound
    SoundImpactCyclonic: Sound
    SoundCrushing: Sound


class ListUpgradeoundSelectorClientBehavior(Behavior):
    pass


class ModelConditionSoundSelectorClientBehavior(Behavior):
    nested_attributes = {"SoundState": ["SoundState"]}  # class in `model.misc_blocks`


class AnimationSoundClientBehavior(Behavior):
    MaxUpdateRangeCap: Int
    AnimationSound: KeyValuePair


class RadarMarkerClientUpdate(Behavior):
    MarkerType: Untyped


class BeaconClientUpdate(Behavior):
    RadarPulseFrequency: Int
    RadarPulseDuration: Int


class SwayClientUpdate(Behavior):
    pass


class AnimatedParticleSysBoneClientUpdate(Behavior):
    pass


class SpecialPowerBehavior(Behavior):
    SpecialPowerTemplate: SpecialPower
    StartAbilityRange: Float
    AbilityAbortRange: Float
    PreparationTime: Int
    PersistentPrepTime: Int
    PersistentCount: Int
    PackTime: Int
    UnpackTime: Int
    PreTriggerUnstealthTime: Int
    SkipPackingWithNoTarget: Bool
    PackUnpackVariationFactor: Float
    ParalyzeDurationWhenCompleted: Int
    ParalyzeDurationWhenAborted: Int
    SpecialObject: Object
    SpecialObjectAttachToBone: Object
    MaxSpecialObjects: Int
    SpecialObjectsPersistent: Bool
    EffectDuration: Int
    EffectValue: Int
    EffectRange: Float
    UniqueSpecialObjectTargets: Bool
    SpecialObjectsPersistWhenOwnerDies: Bool
    AlwaysValidateSpecialObjects: Bool
    FlipOwnerAfterPacking: Bool
    FlipOwnerAfterUnpacking: Bool
    FleeRangeAfterCompletion: Float
    DisableFXParticleSystem: ParticleSystem
    DoCaptureFX: Bool
    PackSound: Sound
    UnpackSound: Sound
    PrepSoundLoop: Sound
    TriggerSound: Sound
    ActiveLoopSound: Sound
    LoseStealthOnTrigger: Bool
    AwardXPForTriggering: Int
    SkillPointsForTriggering: Int
    ApproachRequiresLOS: Bool
    ChargeAttackSpeedBoost: Bool
    CustomAnimAndDuration: AnimAndDuration
    GrabPassengerAnimAndDuration: AnimAndDuration
    GrabPassengerHealGainPercent: Float
    UnpackingVariation: Int
    MustFinishAbility: Bool
    FreezeAfterTriggerDuration: Int
    DisableWhenWearingTheRing: Bool
    RequiredConditions: SpecialPowerUnpackConditions
    RejectedConditions: SpecialPowerUnpackConditions
    ContactPointOverride: Untyped
    TriggerAttributeModifier: ModifierList
    AttributeModifierDuration: Int
    KillAttributeModifierOnExit: Bool
    KillAttributeModifierOnRejected: Bool
    Instant: Bool
    NeedCollisionBeforeTrigger: Bool
    ChainedButton: CommandButton
    SuppressForHordes: Bool
    ApproachUntilMembersInRange: Bool
    IgnoreFacingCheck: Bool
    TriggerModelCondition: t.AttributeModelCondition
    TriggerModelConditionDuration: Float


class FellBeastSwoopPower(SpecialPowerModuleBehavior):
    SpecialWeapon: Weapon
    WhichSpecialWeapon: Int
    StartAbilityRange: Float
    UnpackTime: Int
    AwardXPForTriggering: Int


class WoundArrowUpdate(SpecialPowerBehavior):
    FleeDistance: Float
    ForbiddenConditions: SpecialPowerForbiddenUnpackConditions


class ProductionSpeedBonus(SpecialPowerModuleBehavior):
    NumberOfFrames: Int
    SpeedMulitplier: Float
    Type: List[Object]


# Body modules: `Body` is the marker base, `ActiveBody` carries the health/damage keys,
# and the health-bearing bodies extend it. `InactiveBody` parses nothing.


class Body(Behavior):
    """Marker base for body modules; no keys of its own."""


class ActiveBody(Body):
    MaxHealth: Float
    InitialHealth: Float
    MaxHealthDamaged: Float
    MaxHealthReallyDamaged: Float
    RecoveryTime: Float
    SubdualDamageCap: Float
    SubdualDamageHealRate: Int
    SubdualDamageHealAmount: Float
    GrabObject: Object
    GrabOffset: Coords
    # `<OCL> <damage-source> [<destroyed-side>]`, repeating: the debris OCL, the damage that
    # triggers it, and an optional side (the latter two open mod tokens, `CATAPULT_ROCK`, …).
    DamageCreationList: List[Tuple[ObjectCreationList, FakeEnum, FakeEnum]]
    GrabFX: FXList
    GrabDamage: Float
    CheerRadius: Float
    DodgePercent: Float
    UseDefaultDamageSettings: Bool
    EnteringDamagedTransitionTime: Int
    HealingBuffFx: FXList
    BurningDeathBehavior: Bool
    BurningDeathFX: FXList
    DamagedAttributeModifier: ModifierList
    ReallyDamagedAttributeModifier: ModifierList


class InactiveBody(Body):
    pass


class HighlanderBody(ActiveBody):
    pass


class ImmortalBody(ActiveBody):
    pass


class StructureBody(ActiveBody):
    pass


class OathbreakerBody(ActiveBody):
    pass


class RespawnBody(ActiveBody):
    PermanentlyKilledByFilter: ObjectFilter
    CanRespawn: Bool


class SymbioticStructuresBody(ActiveBody):
    Symbiote: SubObject


class UndeadBody(ActiveBody):
    SecondLifeMaxHealth: Float


class HiveStructureBody(ActiveBody):
    PropagateDamageTypesToSlavesWhenExisting: DamageTypeFilter
    SwallowDamageTypesIfSlavesNotExisting: DamageTypeFilter


class PorcupineFormationBodyModule(ActiveBody):
    DamageWeaponTemplate: Weapon
    CrushDamageWeaponTemplate: Weapon
    CrusherLevelResisted: Int


class DetachableRiderBody(ActiveBody):
    HealthPercentageWhenRiderDies: Float
    StartsActive: Bool
    TriggeredBy: List[Upgrade]


class FreeLifeBody(ActiveBody):
    FreeLifeHealthPercent: Float
    FreeLifeTime: Int
    FreeLifeInvincible: Bool
    FreeLifePrerequisiteUpgrade: Upgrade
    FreeLifeAnimAndDuration: AnimAndDuration


class DelayedDeathBody(ActiveBody):
    DelayedDeathTime: Int
    CanRespawn: Bool
    DoHealthCheck: Bool
    ImmortalUntilDeathTime: Bool
    DelayedDeathPrerequisiteUpgrade: Upgrade
    InvulnerableFX: FXList
    PermanentlyKilledByFilter: ObjectFilter


class CivilianSpawnCollide(Behavior):
    DeleteObjectFilter: ObjectFilter


class CrateCollide(Behavior):
    RequiredKindOf: List[KindOf]
    ForbiddenKindOf: List[KindOf]
    ForbidOwnerPlayer: Bool
    BuildingPickup: Bool
    HumanOnly: Bool
    FXList: t.FXList
    PickupScience: Science
    ExecuteFX: t.FXList
    ExecuteAnimation: Animation
    ExecuteAnimationTime: Float
    ExecuteAnimationZRise: Float
    ExecuteAnimationFades: Bool


class SalvageCrateCollide(CrateCollide):
    WeaponChance: Float
    LevelChance: Float
    MoneyChance: Float
    MinMoney: Int
    MaxMoney: Int
    PorterChance: Float
    BannerChance: Float
    LevelUpChance: Float
    LevelUpRadius: Float
    ResourceChance: Float
    Upgrade: io.Upgrade
    MinResource: Int
    MaxResource: Int
    AllowAIPickup: Bool


class VeterancyCrateCollide(CrateCollide):
    EffectRange: Int
    AddsOwnerVeterancy: Bool
    IsPilot: Bool
    AffectsUpToLevel: Int


class UnitCrateCollide(CrateCollide):
    UnitCount: Int
    UnitName: Object


class ShroudCrateCollide(Behavior):
    pass


class MoneyCrateCollide(CrateCollide):
    MoneyProvided: Int
    UpgradedBoost: Untyped


class ConvertToCarBombCrateCollide(CrateCollide):
    pass


class ConvertToHijackedVehicleCrateCollide(CrateCollide):
    pass


class SabotageCommandCenterCrateCollide(CrateCollide):
    pass


class SabotageFakeBuildingCrateCollide(CrateCollide):
    pass


class SabotageSuperweaponCrateCollide(CrateCollide):
    pass


class SabotageInternetCenterCrateCollide(CrateCollide):
    SabotageDuration: Int


class SabotageMilitaryFactoryCrateCollide(CrateCollide):
    SabotageDuration: Int


class SabotagePowerPlantCrateCollide(CrateCollide):
    SabotagePowerDuration: Int


class SabotageSupplyCenterCrateCollide(CrateCollide):
    StealCashAmount: Int


class HealCrateCollide(CrateCollide):
    pass


class HordeMemberCollide(Behavior):
    pass


class AODCrushCollide(Behavior):
    SmallObjectCreationList: ObjectCreationList
    MediumObjectCreationList: ObjectCreationList
    LargeObjectCreationList: ObjectCreationList
    Damage: Float
    SpecialDamage: Float
    SpecialDamageType: e.DamageType
    SpecialDeathType: e.DeathType
    SelfDamage: Float
    SelfDamageType: e.DamageType
    SelfDeathType: e.DeathType
    SpecialObject: ObjectFilter
    SmallFXList: FXList
    MediumFXList: FXList
    LargeFXList: FXList
    DamageType: e.DamageType
    DeathType: e.DeathType


class SquishCollide(Behavior):
    pass


class FireWeaponCollide(Behavior):
    CollideWeapon: Weapon
    FireOnce: Bool
    RequiredStatus: ObjectStatus
    ForbiddenStatus: ObjectStatus


class CallHelpOnDamage(Behavior):
    DamageTypes: DamageTypeFilter
    CallRadius: Float
    CallDelay: Int
    MoveToAttacker: Bool
    ValidObjects: ObjectFilter


class HordeTransportContainDamage(Behavior):
    pass


class EvacuateDamage(Behavior):
    WeaponThatCausesEvacuation: Weapon
    DamageTypeToTrack: DamageType
    DamageToPanicThreshold: Float
    TrackingTimeSpan: Int


class ReflectDamage(Behavior):
    DamageTypesToReflect: DamageTypeFilter
    ReflectDamageFloat: Float
    MinimumDamageToReflect: Float
    ReflectDamagePercentage: Float


class TransitionDamageFX(Behavior):
    DamageFXTypes: DamageTypeFilter
    DamageOCLTypes: DamageTypeFilter
    DamageParticleTypes: DamageTypeFilter
    DamagedOCL1: ObjectCreationList
    DamagedOCL2: ObjectCreationList
    DamagedOCL3: ObjectCreationList
    DamagedOCL4: ObjectCreationList
    DamagedOCL5: ObjectCreationList
    DamagedOCL6: ObjectCreationList
    DamagedOCL7: ObjectCreationList
    DamagedOCL8: ObjectCreationList
    DamagedOCL9: ObjectCreationList
    DamagedOCL10: ObjectCreationList
    DamagedOCL11: ObjectCreationList
    DamagedOCL12: ObjectCreationList
    ReallyDamagedOCL1: ObjectCreationList
    ReallyDamagedOCL2: ObjectCreationList
    ReallyDamagedOCL3: ObjectCreationList
    ReallyDamagedOCL4: ObjectCreationList
    ReallyDamagedOCL5: ObjectCreationList
    ReallyDamagedOCL6: ObjectCreationList
    ReallyDamagedOCL7: ObjectCreationList
    ReallyDamagedOCL8: ObjectCreationList
    ReallyDamagedOCL9: ObjectCreationList
    ReallyDamagedOCL10: ObjectCreationList
    ReallyDamagedOCL11: ObjectCreationList
    ReallyDamagedOCL12: ObjectCreationList
    RubbleOCL1: ObjectCreationList
    RubbleOCL2: ObjectCreationList
    RubbleOCL3: ObjectCreationList
    RubbleOCL4: ObjectCreationList
    RubbleOCL5: ObjectCreationList
    RubbleOCL6: ObjectCreationList
    RubbleOCL7: ObjectCreationList
    RubbleOCL8: ObjectCreationList
    RubbleOCL9: ObjectCreationList
    RubbleOCL10: ObjectCreationList
    RubbleOCL11: ObjectCreationList
    RubbleOCL12: ObjectCreationList
    PristineShowSubObject: List[SubObject]
    PristineHideSubObject: List[SubObject]
    DamagedShowSubObject: List[SubObject]
    DamagedHideSubObject: List[SubObject]
    ReallyDamagedShowSubObject: List[SubObject]
    ReallyDamagedHideSubObject: List[SubObject]
    RubbleShowSubObject: List[SubObject]
    RubbleHideSubObject: List[SubObject]
    DamagedFXList1: FXList
    DamagedFXList2: FXList
    DamagedFXList3: FXList
    DamagedFXList4: FXList
    DamagedFXList5: FXList
    DamagedFXList6: FXList
    DamagedFXList7: FXList
    DamagedFXList8: FXList
    DamagedFXList9: FXList
    DamagedFXList10: FXList
    DamagedFXList11: FXList
    DamagedFXList12: FXList
    ReallyDamagedFXList1: FXList
    ReallyDamagedFXList2: FXList
    ReallyDamagedFXList3: FXList
    ReallyDamagedFXList4: FXList
    ReallyDamagedFXList5: FXList
    ReallyDamagedFXList6: FXList
    ReallyDamagedFXList7: FXList
    ReallyDamagedFXList8: FXList
    ReallyDamagedFXList9: FXList
    ReallyDamagedFXList10: FXList
    ReallyDamagedFXList11: FXList
    ReallyDamagedFXList12: FXList
    RubbleFXList1: FXList
    RubbleFXList2: FXList
    RubbleFXList3: FXList
    RubbleFXList4: FXList
    RubbleFXList5: FXList
    RubbleFXList6: FXList
    RubbleFXList7: FXList
    RubbleFXList8: FXList
    RubbleFXList9: FXList
    RubbleFXList10: FXList
    RubbleFXList11: FXList
    RubbleFXList12: FXList
    DamagedParticleSystem1: ParticleSystem
    DamagedParticleSystem2: ParticleSystem
    DamagedParticleSystem3: ParticleSystem
    DamagedParticleSystem4: ParticleSystem
    DamagedParticleSystem5: ParticleSystem
    DamagedParticleSystem6: ParticleSystem
    DamagedParticleSystem7: ParticleSystem
    DamagedParticleSystem8: ParticleSystem
    DamagedParticleSystem9: ParticleSystem
    DamagedParticleSystem10: ParticleSystem
    DamagedParticleSystem11: ParticleSystem
    DamagedParticleSystem12: ParticleSystem
    ReallyDamagedParticleSystem1: ParticleSystem
    ReallyDamagedParticleSystem2: ParticleSystem
    ReallyDamagedParticleSystem3: ParticleSystem
    ReallyDamagedParticleSystem4: ParticleSystem
    ReallyDamagedParticleSystem5: ParticleSystem
    ReallyDamagedParticleSystem6: ParticleSystem
    ReallyDamagedParticleSystem7: ParticleSystem
    ReallyDamagedParticleSystem8: ParticleSystem
    ReallyDamagedParticleSystem9: ParticleSystem
    ReallyDamagedParticleSystem10: ParticleSystem
    ReallyDamagedParticleSystem11: ParticleSystem
    ReallyDamagedParticleSystem12: ParticleSystem
    RubbleParticleSystem1: ParticleSystem
    RubbleParticleSystem2: ParticleSystem
    RubbleParticleSystem3: ParticleSystem
    RubbleParticleSystem4: ParticleSystem
    RubbleParticleSystem5: ParticleSystem
    RubbleParticleSystem6: ParticleSystem
    RubbleParticleSystem7: ParticleSystem
    RubbleParticleSystem8: ParticleSystem
    RubbleParticleSystem9: ParticleSystem
    RubbleParticleSystem10: ParticleSystem
    RubbleParticleSystem11: ParticleSystem
    RubbleParticleSystem12: ParticleSystem
    RubbleNeighbor: Untyped


class BoneFXDamage(Behavior):
    pass


class InheritUpgradeCreate(Behavior):
    Radius: Float
    Upgrade: List[io.Upgrade]
    ObjectFilter: t.ObjectFilter


class ExperienceLevelCreate(Behavior):
    LevelToGrant: Int
    MPOnly: Bool


class GrantUpgradeCreate(Behavior):
    UpgradeToGrant: Upgrade
    ExemptStatus: ObjectStatus
    GiveOnBuildComplete: Bool


class SpecialPowerCreate(Behavior):
    pass


class SupplyWarehouseCreate(Behavior):
    pass


class SupplyCenterCreate(Behavior):
    pass


class PreorderCreate(Behavior):
    pass


class LockWeaponCreate(Behavior):
    SlotToLock: SlotTypes


class PillageModule(Behavior):
    PillageAmount: Int
    NumDamageEventsPerPillage: Int
    PillageFilter: ObjectFilter


class TemporarilyDefectUpdate(Behavior):
    DefectDuration: Int


class PassiveAreaEffectBehavior(Behavior):
    EffectRadius: Float
    PingDelay: Int
    HealPercentPerSecond: Float
    ModifierName: List[ModifierList]
    AllowFilter: ObjectFilter
    UpgradeRequired: List[Upgrade]
    NonStackable: Bool
    AntiCategories: ModifierCategories
    AntiFX: FXList
    HealFX: FXList


class CommandPointsUpgrade(UpgradeBehavior):
    CommandPoints: Int
    RequiredObject: ObjectFilter


class AllowBannerSpawnUpgrade(UpgradeBehavior):
    pass


class BuildableHeroListUpgrade(UpgradeBehavior):
    pass


class RemoveUpgradeUpgrade(UpgradeBehavior):
    UpgradeToRemove: List[Upgrade]
    SuppressEvaEventForRemoval: Bool
    RemoveFromAllPlayerObjects: Bool
    UpgradeGroupsToRemove: List[t.String]


class AudioLoopUpgrade(UpgradeBehavior):
    DeathType: DeathTypeFilter
    ExemptStatus: ObjectStatus
    RequiredStatus: ObjectStatus
    DamageAmountRequired: Float
    MinKillerAngle: Degrees
    MaxKillerAngle: Degrees
    KillAfterMS: Int
    KillOnDeath: Bool
    DeathTypes: DeathTypeFilter
    SoundToPlay: Sound


class TooltipUpgrade(UpgradeBehavior):
    DisplayName: Label


class GarrisonUpgrade(UpgradeBehavior):
    pass


class ReplaceSelfUpgrade(UpgradeBehavior):
    ReplaceWith: Object
    AndThenAddA: List[Upgrade]


class GeometryUpgrade(UpgradeBehavior):
    ShowGeometry: List[Untyped]
    HideGeometry: List[Untyped]
    WallBoundsMesh: SubObject
    RampMesh1: SubObject
    RampMesh2: SubObject


class CastleUpgrade(UpgradeBehavior):
    Upgrade: io.Upgrade
    WallUpgradeRadius: Float


class AttributeModifierUpgrade(UpgradeBehavior):
    AttributeModifier: ModifierList


class ModelConditionUpgrade(UpgradeBehavior):
    ConditionFlag: ModelCondition
    AddConditionFlags: List[ModelCondition]
    RemoveConditionFlags: List[ModelCondition]
    RemoveConditionFlagsInRange: Tuple[ModelCondition, ModelCondition]
    TempConditionTime: Float
    AddTempConditionFlag: KeyValuePair


class MaxHealthUpgrade(UpgradeBehavior):
    AddMaxHealth: Float
    ChangeType: HealthOperation


class ExperienceScalarUpgrade(UpgradeBehavior):
    AddXPScalar: Float


class WeaponSetUpgrade(UpgradeBehavior):
    WeaponCondition: WeaponsetFlags


class WeaponBonusUpgrade(UpgradeBehavior):
    pass


class UnpauseSpecialPowerUpgrade(UpgradeBehavior):
    SpecialPowerTemplate: SpecialPower
    ObeyRechageOnTrigger: Bool


class ObjectCreationUpgrade(UpgradeBehavior):
    UpgradeObject: Object
    Delay: Int
    RemoveUpgrade: Upgrade
    GrantUpgrade: Upgrade
    ThingToSpawn: Object
    Offset: Coords
    Angle: Degrees
    DestroyWhenSold: Bool
    FadeInTime: Int
    UseBuildingProduction: Bool
    DeathAnimAndDuration: AnimAndDuration


class LocomotorSetUpgrade(UpgradeBehavior):
    KillLocomotorUpgrade: Bool


class RadarUpgrade(UpgradeBehavior):
    DisableProof: Bool


class StealthUpgrade(UpgradeBehavior):
    pass


class SubObjectsUpgrade(UpgradeBehavior):
    FXListUpgrade: FXList
    FadeTimeInSeconds: Float
    WaitBeforeFadeInSeconds: Float
    RecolorHouse: Bool
    SkipFadeOnCreate: Bool
    HideSubObjectsOnRemove: Bool
    UnHideSubObjectsOnRemove: Bool
    ShowSubObjects: List[SubObject]
    HideSubObjects: List[SubObject]
    UpgradeTexture: List[Tuple[Untyped, Int, Untyped]]
    ExcludeSubobjects: List[SubObject]


class ArmorUpgrade(UpgradeBehavior):
    ArmorSetFlag: ArmorSetFlags
    IgnoreArmorUpgrade: Bool


class DoCommandUpgrade(UpgradeBehavior):
    GetUpgradeCommandButtonName: CommandButton
    RemoveUpgradeCommandButtonName: CommandButton


class StatusBitsUpgradeIfEldestKindof(UpgradeBehavior):
    StatusToSet: List[ObjectStatus]
    StatusToClear: List[ObjectStatus]
    ObjectFilter: t.ObjectFilter


class StatusBitsUpgrade(UpgradeBehavior):
    StatusToSet: List[ObjectStatus]
    StatusToClear: List[ObjectStatus]


class LevelUpUpgrade(UpgradeBehavior):
    LevelsToGain: Int
    LevelCap: Int


class DelayedUpgrade(UpgradeBehavior):
    DelayTime: Int


class CommandSetUpgrade(UpgradeBehavior):
    CommandSet: io.CommandSet
    CommandSetAlt: io.CommandSet
    TriggerAlt: Opaque
    RemovesUpgrades: List[Upgrade]


class BaseUpgrade(UpgradeBehavior):
    BuildingTemplateName: Object
    PlacementPrefix: Untyped
    PlacementIndex: Int


class SpellRechargeModifierUpgrade(UpgradeBehavior):
    LabelForPalantirString: Label
    ObjectFilter: t.ObjectFilter
    UpgradeDiscount: Bool
    ApplyToTheseUpgrades: List[Upgrade]
    Slaughter: Bool
    Percentage: t.Float
    Float: t.Float


class ReplaceObjectUpdate(Behavior):
    nested_attributes = {"ReplaceObject": ["ReplaceObject"]}

    SpecialPowerTemplate: SpecialPower
    SkipContinue: Bool
    UnpackingVariation: Int
    UnpackTime: Int
    PreparationTime: Int
    PersistentPrepTime: Int
    PackTime: Int
    AwardXPForTriggering: Int
    StartAbilityRange: Float
    MustFinishAbility: Bool
    ReplaceRadius: Float
    ReplaceFX: FXList
    Scatter: Bool


class ProjectileStreamUpdate(Behavior):
    pass


class ThreatFinderUpdate(Behavior):
    DefaultRadius: Float


class EmotionTrackerUpdate(Behavior):
    nested_attributes = {"AddEmotion": ["AddEmotion"]}  # class in `model.misc_blocks`

    TauntAndPointDistance: Float
    TauntAndPointUpdateDelay: Int
    TauntAndPointExcluded: ObjectFilter
    AfraidOf: ObjectFilter
    AlwaysAfraidOf: ObjectFilter
    PointAt: ObjectFilter
    HeroScanDistance: Float
    FearScanDistance: Float
    QuarrelProbability: Float
    IgnoreVeterancy: Bool
    ImmuneToFearLevel: Int
    AddEmotion: List[t.Emotion]


class SpecialDisguiseUpdate(Behavior):
    SpecialPowerTemplate: SpecialPower
    UnpackTime: Int
    PreparationTime: Int
    PersistentPrepTime: Int
    PackTime: Int
    OpacityTarget: Float
    AwardXPForTriggering: Int
    DisguiseAsTemplate: Object
    DisguisedAsTemplate_EnemyPerspective: t.ObjectRef
    DisguiseFX: FXList
    ForceMountedWhenDisguising: Bool
    TriggerInstantlyOnCreate: Bool
    DisguisedAsTemplate_EnemyPerspec: Object


class AttributeModifierPoolUpdate(Behavior):
    pass


class BloodthirstyUpdate(Behavior):
    SacrificeFilter: ObjectFilter
    NumToSacrifice: Int
    InitiateVoice: Sound
    InitiateVoice2: Opaque
    ExperienceModifier: Float


class RespawnUpdate(Behavior):
    DeathAnim: ModelCondition
    DeathFX: FXList
    DeathAnimationTime: Int
    InitialSpawnFX: FXList
    RespawnAnim: ModelCondition
    RespawnFX: FXList
    RespawnAnimationTime: Int
    AutoRespawnAtObjectFilter: ObjectFilter
    ButtonImage: Image
    RespawnRules: t.RespawnRules
    RespawnEntry: List[KeyValuePair[Int, Int, Int]]
    RespawnAsTemplate: Object
    InitialSpawnAnim: ModelCondition
    InitialSpawnAnimationTime: Int


class DetachableRiderUpdate(Behavior):
    RiderSubObjects: List[SubObject]
    RiderlessWeaponSlot: SlotTypes
    RiderlessHordeFlees: Bool
    DeathEntry: t.DeathEntry
    RemoveRiderlessFromHorde: Bool


class WallUpgradeUpdate(Behavior):
    pass


class AIUpdateBehavior(Behavior):
    # `Turret`/`AltTurret` are sub-blocks (Turret class in `model.misc_blocks`).
    nested_attributes = {"Turret": ["Turret"], "AltTurret": ["Turret"]}

    TurretsLinked: Bool
    AutoAcquireEnemiesWhenIdle: List[AllowedWhenConditions]
    MoodAttackCheckRate: Int
    ForbidPlayerCommands: Bool
    AILuaEventsList: Untyped
    HoldGroundCloseRangeDistance: Float
    MinCowerTime: Int
    MaxCowerTime: Int
    CanAttackWhileContained: Bool
    RampageTime: Int
    TimeToEjectPassengersOnRampage: Int
    AttackPriority: io.AttackPriority
    SpecialContactPoints: List[Untyped]
    FadeOnPortals: Bool
    StopChaseDistance: Float
    RampageRequiresAflame: Bool
    MoveForNoOne: Bool
    StandGround: Bool
    BurningDeathTime: Int


class AIGateUpdate(AIUpdateBehavior):
    TriggerWidthX: Float
    TriggerWidthY: Float


class AIUpdateInterface(AIUpdateBehavior):
    pass


class TransportAIUpdate(AIUpdateBehavior):
    pass


class SiegeAIUpdate(AIUpdateBehavior):
    pass


class WanderAIUpdate(AIUpdateBehavior):
    pass


class AssaultTransportAIUpdate(AIUpdateBehavior):
    MembersGetHealedAtLifeRatio: Float


class FoundationAIUpdate(AIUpdateBehavior):
    BuildVariation: Int


class AISpecialPowerUpdate(AIUpdateBehavior):
    CommandButtonName: CommandButton
    SpecialPowerRadius: Float
    SpecialPowerRange: Float
    RandomizeTargetLocation: Bool
    SpellMakesAStructure: Bool
    SpecialPowerAIType: e.SpecialPowerAIType


class CastleBehavior(FoundationAIUpdate):
    SidesAllowed: List[Untyped]
    UseSecondaryBuildList: Bool
    UseTheNewCastleSystemInsteadOfTheClunkyBuildList: Bool
    RepairHealthPercentPerSecond: Float
    FilterValidOwnedEntries: ObjectFilter
    FilterCrew: ObjectFilter
    FadeTime: Float
    UnpackDelayTime: Float
    BuildTime: Float
    ScanDistance: Float
    MaxCastleRadius: Float
    CrewPrepareTime: Int
    InstantUnpack: Bool
    KeepDeathKillsEverything: Bool
    CrewPrepareInterval: Int
    DisableStructureRotation: Bool
    Summoned: Bool
    TransferFoundationHealthToCastleUponUnpack: Bool
    CastleToUnpackForFaction: GroupedByKey[FactionSide, Untyped]
    FactionDecal: Untyped
    PreBuiltList: List[Tuple[t.ObjectRef, Int]]
    PreBuiltPlyr: Untyped
    DecalName: Untyped
    DecalSize: Float
    CrewReleaseFX: FXList
    CrewPrepareFX: FXList
    EvaEnemyCastleSightedEvent: EvaEvent


class HordeAIUpdate(AIUpdateBehavior):
    ComboLocomotorSet: LocomotorSetType
    ComboLocoAttackDistance: Int


class HordeWorkerAIUpdate(AIUpdateBehavior):
    ComboLocomotorSet: LocomotorSetType
    ComboLocoAttackDistance: Int


class AnimalAIUpdate(AIUpdateBehavior):
    FleeRange: Int
    FleeDistance: Int
    WanderPercentage: Float
    MaxWanderDistance: Int
    MaxWanderRadius: Int
    UpdateTimer: Int
    AfraidOfCastles: Bool


class DozerAIUpdate(AIUpdateBehavior):
    RepairHealthPercentPerSecond: Float
    BoredTime: Int
    BoredRange: Int


class DeployStyleAIUpdate(AIUpdateBehavior):
    PackTime: Int
    UnpackTime: Int
    TurretsFunctionOnlyWhenDeployed: Bool
    TurretsMustCenterBeforePacking: Bool
    ManualDeployAnimations: Bool
    MustDeployToAttack: Bool
    DeployedAttributeModifier: ModifierList


class GiantBirdAIUpdate(AIUpdateBehavior):
    FollowThroughDistance: Int
    FollowThroughCheckStep: Int
    FollowThroughGradient: Float
    GrabTossTimeTrigger: Float
    GrabTossHeightTrigger: Float
    TossFX: FXList


class JetAIUpdate(AIUpdateBehavior):
    OutOfAmmoDamagePerSecond: Float
    TakeoffSpeedForMaxLift: Float
    TakeoffDistForMaxLift: Float
    TakeoffPause: Int
    MinHeight: Int
    NeedsRunway: Bool
    KeepsParkingSpaceWhenAirborne: Bool
    SneakyOffsetWhenAttacking: Float
    AttackLocomotorType: LocomotorSetType
    AttackLocomotorPersistTime: Int
    AttackersMissPersistTime: Int
    ReturnForAmmoLocomotorType: LocomotorSetType
    ParkingOffset: Int
    ReturnToBaseIdleTime: Int


class MissileAIUpdate(AIUpdateBehavior):
    TryToFollowTarget: Bool
    FuelLifetime: Int
    DetonateOnNoFuel: Bool
    InitialVelocity: Float
    IgnitionDelay: Int
    DistanceToTravelBeforeTurning: Int
    DistanceToTargetBeforeDiving: Int
    DistanceToTargetForLock: Int
    GarrisonHitKillRequiredKindOf: KindOf
    GarrisonHitKillForbiddenKindOf: KindOf
    GarrisonHitKillCount: Int
    GarrisonHitKillFX: FXList
    DetonateCallsKill: Bool
    IgnitionFX: FXList
    KillSelfDelay: Int
    DistanceScatterWhenJammed: Int


class DeliverPayloadAIUpdate(AIUpdateBehavior):
    DoorDelay: Int
    MaxAttempts: Int
    DropOffset: Coords
    DropDelay: Int
    PutInContainer: Object
    DeliveryDistance: Int


class HackInternetAIUpdate(AIUpdateBehavior):
    UnpackTime: Int
    PackTime: Int
    CashUpdateDelay: Int
    CashUpdateDelayFast: Int
    RegularCashAmount: Int
    VeteranCashAmount: Int
    EliteCashAmount: Int
    HeroicCashAmount: Int
    XpPerCashUpdate: Int
    PackUnpackVariationFactor: Float


class RailedTransportAIUpdate(AIUpdateBehavior):
    PathPrefixName: Opaque


class SupplyAIUpdate(AIUpdateBehavior):
    MaxBoxes: Int
    SupplyCenterActionDelay: Int
    SupplyWarehouseActionDelay: Int
    SupplyWarehouseScanDistance: Float
    SuppliesDepletedVoice: Sound


class SupplyTruckAIUpdate(SupplyAIUpdate):
    pass


class ChinookAIUpdate(SupplyTruckAIUpdate):
    NumRopes: Int
    PerRopeDelayMin: Int
    PerRopeDelayMax: Int
    RopeWidth: Float
    RopeColor: Untyped
    RopeWobbleLen: Int
    RopeWobbleAmplitude: Float
    RopeWobbleRate: Int
    RopeFinalHeight: Int
    RappelSpeed: Int
    MinDropHeight: Int
    UpgradedSupplyBoost: Int
    RotorWashParticleSystem: ParticleSystem


class WorkerAIUpdate(SupplyAIUpdate):
    RepairHealthPercentPerSecond: Float
    BoredTime: Int
    BoredRange: Int
    UpgradedSupplyBoost: Int
    HarvestTrees: Bool
    HarvestActivationRange: Int
    HarvestPreparationTime: Int
    HarvestActionTime: Int


class RadarUpdate(Behavior):
    RadarExtendTime: Int


class BoneFXUpdate(Behavior):
    DamageFXTypes: DamageTypeFilter
    RubbleFXList1: FXList
    DamageParticleTypes: DamageTypeFilter
    PristineParticleSystem1: ParticleSystem
    RubbleParticleSystem1: ParticleSystem
    PristineParticleSystem2: ParticleSystem
    PristineParticleSystem3: ParticleSystem
    PristineParticleSystem4: ParticleSystem
    PristineParticleSystem5: ParticleSystem
    PristineParticleSystem6: ParticleSystem
    DamageOCLTypes: DamageTypeFilter
    PristineOCL1: ObjectCreationList
    PristineOCL2: ObjectCreationList
    PristineOCL3: ObjectCreationList
    PristineOCL4: ObjectCreationList
    PristineOCL5: ObjectCreationList
    PristineOCL6: ObjectCreationList
    PristineOCL7: ObjectCreationList
    PristineOCL8: ObjectCreationList
    DamagedOCL1: ObjectCreationList
    DamagedOCL2: ObjectCreationList
    DamagedOCL3: ObjectCreationList
    DamagedOCL4: ObjectCreationList
    DamagedOCL5: ObjectCreationList
    DamagedOCL6: ObjectCreationList
    DamagedOCL7: ObjectCreationList
    DamagedOCL8: ObjectCreationList
    ReallyDamagedOCL1: ObjectCreationList
    ReallyDamagedOCL2: ObjectCreationList
    ReallyDamagedOCL3: ObjectCreationList
    ReallyDamagedOCL4: ObjectCreationList
    ReallyDamagedOCL5: ObjectCreationList
    ReallyDamagedOCL6: ObjectCreationList
    ReallyDamagedOCL7: ObjectCreationList
    ReallyDamagedOCL8: ObjectCreationList
    RubbleOCL1: ObjectCreationList
    RubbleOCL2: ObjectCreationList
    RubbleOCL3: ObjectCreationList
    RubbleOCL4: ObjectCreationList
    RubbleOCL5: ObjectCreationList
    RubbleOCL6: ObjectCreationList
    RubbleOCL7: ObjectCreationList
    RubbleOCL8: ObjectCreationList
    PristineFXList1: FXList
    PristineFXList2: FXList
    PristineFXList3: FXList
    PristineFXList4: FXList
    PristineFXList5: FXList
    PristineFXList6: FXList
    PristineFXList7: FXList
    PristineFXList8: FXList
    DamagedFXList1: FXList
    DamagedFXList2: FXList
    DamagedFXList3: FXList
    DamagedFXList4: FXList
    DamagedFXList5: FXList
    DamagedFXList6: FXList
    DamagedFXList7: FXList
    DamagedFXList8: FXList
    ReallyDamagedFXList1: FXList
    ReallyDamagedFXList2: FXList
    ReallyDamagedFXList3: FXList
    ReallyDamagedFXList4: FXList
    ReallyDamagedFXList5: FXList
    ReallyDamagedFXList6: FXList
    ReallyDamagedFXList7: FXList
    ReallyDamagedFXList8: FXList
    RubbleFXList2: FXList
    RubbleFXList3: FXList
    RubbleFXList4: FXList
    RubbleFXList5: FXList
    RubbleFXList6: FXList
    RubbleFXList7: FXList
    RubbleFXList8: FXList
    PristineParticleSystem7: ParticleSystem
    PristineParticleSystem8: ParticleSystem
    DamagedParticleSystem1: ParticleSystem
    DamagedParticleSystem2: ParticleSystem
    DamagedParticleSystem3: ParticleSystem
    DamagedParticleSystem4: ParticleSystem
    DamagedParticleSystem5: ParticleSystem
    DamagedParticleSystem6: ParticleSystem
    DamagedParticleSystem7: ParticleSystem
    DamagedParticleSystem8: ParticleSystem
    ReallyDamagedParticleSystem1: ParticleSystem
    ReallyDamagedParticleSystem2: ParticleSystem
    ReallyDamagedParticleSystem3: ParticleSystem
    ReallyDamagedParticleSystem4: ParticleSystem
    ReallyDamagedParticleSystem5: ParticleSystem
    ReallyDamagedParticleSystem6: ParticleSystem
    ReallyDamagedParticleSystem7: ParticleSystem
    ReallyDamagedParticleSystem8: ParticleSystem
    RubbleParticleSystem2: ParticleSystem
    RubbleParticleSystem3: ParticleSystem
    RubbleParticleSystem4: ParticleSystem
    RubbleParticleSystem5: ParticleSystem
    RubbleParticleSystem6: ParticleSystem
    RubbleParticleSystem7: ParticleSystem
    RubbleParticleSystem8: ParticleSystem


class RubbleRiseUpdate(Behavior):
    MinRubbleRiseDelay: Int
    MaxRubbleRiseDelay: Int
    RubbleRiseDamping: Float
    RubbleHeight: Float
    MaxShudder: Float
    MinBurstDelay: Int
    MaxBurstDelay: Int
    BigBurstFrequency: Int
    FXList: t.FXList
    OCL: ObjectCreationList
    DeathType: DeathTypeFilter
    ExemptStatus: ObjectStatus
    RequiredStatus: ObjectStatus
    DamageAmountRequired: Float
    MinKillerAngle: Degrees
    MaxKillerAngle: Degrees
    DeathTypes: DeathTypeFilter


class StructureCollapseUpdate(Behavior):
    MinCollapseDelay: Int
    MaxCollapseDelay: Int
    CollapseDamping: Float
    MaxShudder: Float
    MinBurstDelay: Int
    MaxBurstDelay: Int
    BigBurstFrequency: Int
    OCL: GroupedByKey[StructureCollapsePhase, ObjectCreationList]
    FXList: GroupedByKey[StructureCollapsePhase, t.FXList]
    DestroyObjectWhenDone: Bool
    CollapseHeight: Float
    DeathType: DeathTypeFilter
    ExemptStatus: ObjectStatus
    RequiredStatus: ObjectStatus
    DamageAmountRequired: Float
    MinKillerAngle: Degrees
    MaxKillerAngle: Degrees
    DeathTypes: DeathTypeFilter


class StructureToppleUpdate(Behavior):
    MinToppleDelay: Int
    MaxToppleDelay: Int
    MinToppleBurstDelay: Int
    MaxToppleBurstDelay: Int
    StructuralIntegrity: Float
    StructuralDecay: Float
    DamageFXTypes: DamageTypeFilter
    ToppleStartFX: FXList
    ToppleDelayFX: FXList
    CrushingFX: FXList
    AngleFX: FXList
    ToppleDoneFX: FXList
    CrushingWeaponName: Weapon
    ToppleAccelerationFactor: Float
    ForceToppleAngle: Float
    OCL: ObjectCreationList
    DeathType: DeathTypeFilter
    ExemptStatus: ObjectStatus
    RequiredStatus: ObjectStatus
    DamageAmountRequired: Float
    MinKillerAngle: Degrees
    MaxKillerAngle: Degrees
    TopplingFX: FXList
    DeathTypes: DeathTypeFilter


class FadeAndDieOrnamentUpdate(Behavior):
    Envelope: Untyped


class HijackerUpdate(Behavior):
    ParachuteName: Opaque
    AttachToTargetBone: Bone


class ProneUpdate(Behavior):
    DamageToFramesRatio: Float


class ProductionUpdate(Behavior):
    nested_attributes = {"ProductionModifier": ["ProductionModifier"]}  # class in `misc_blocks`

    NumDoorAnimations: Int
    DoorOpeningTime: Int
    DoorWaitOpenTime: Int
    DoorCloseTime: Int
    ConstructionCompleteDuration: Int
    MaxQueueEntries: Int
    QuantityModifier: Opaque
    DisabledTypesToProcess: List[Untyped]
    VeteranUnitsFromVeteranFactory: Bool
    SetBonusModelConditionOnSpeedBonus: Bool
    BonusForType: List[Object]
    SpeedBonusAudioLoop: Sound
    UnitInvulnerableTime: Int
    GiveNoXP: Bool
    SpecialPrepModelconditionTime: Int
    SetBonusModelConditionOnSpeedBon: Bool
    SecondaryQueue: Bool


class GloriousChargeUpdate(SpecialPowerBehavior):
    BonusRadius: Float
    SpeechDuration: Int
    UpdateInterval: Int


class RousingSpeechUpdate(Behavior):
    SpecialPowerTemplate: SpecialPower
    RequiredConditions: SpecialPowerUnpackConditions
    StartAbilityRange: Float
    UpdateInterval: Int
    ApproachRequiresLOS: Bool
    BonusRadius: Float
    SpeechDuration: Int
    LeaderFX: FXList
    FollowerFX: FXList
    CreateWave: Bool
    WaveWidth: Float
    ModifierName: List[ModifierList]
    ObjectFilter: t.ObjectFilter
    LevelUp: Bool


class MonsterDockUpdate(Behavior):
    NumberApproachPositions: Int
    AllowsPassthrough: Bool
    DockableObjectFilter: ObjectFilter
    DockedAnimationTime: Int


class SupplyWarehouseDockUpdate(Behavior):
    NumberApproachPositions: Int
    AllowsPassthrough: Bool
    StartingBoxes: Int
    DeleteWhenEmpty: Bool


class SupplyCenterDockUpdate(Behavior):
    GrantTemporaryStealth: Int
    BonusScience: Science
    BonusScienceMultiplier: Float
    ValueMultiplier: Float
    NumberApproachPositions: Int
    AllowsPassthrough: Bool


class SupplyCenterProductionExitUpdate(Behavior):
    UnitCreatePoint: Coords
    NaturalRallyPoint: Coords
    GrantTemporaryStealth: Int


class RadiateFearUpdate(UpgradeBehavior):
    InitiallyActive: Bool
    WhichSpecialPower: Int
    GenerateTerror: Bool
    GenerateFear: Bool
    EmotionPulseRadius: Float
    EmotionPulseInterval: Int
    VictimFilter: ObjectFilter
    GenerateUncontrollableFear: Bool
    EmotionPulseRadiusl: Float


class OCLUpdate(Behavior):
    OCL: ObjectCreationList
    MinDelay: Int
    MaxDelay: Int
    CreateAtEdge: Bool
    FactionTriggered: Bool
    FactionOCL: ObjectCreationList
    Amount: Int


class SlavedUpdate(Behavior):
    GuardMaxRange: Int
    GuardWanderRange: Int
    AttackRange: Int
    AttackWanderRange: Int
    ScoutRange: Int
    ScoutWanderRange: Int
    RepairRange: Int
    RepairMinAltitude: Float
    RepairMaxAltitude: Float
    RepairRatePerSecond: Float
    RepairMinReadyTime: Int
    RepairMaxReadyTime: Int
    RepairMinWeldTime: Int
    RepairMaxWeldTime: Int
    RepairWeldingSys: FXParticleSystem
    RepairWeldingFXBone: Bone
    DistToTargetToGrantRangeBonus: Int
    StayOnSameLayerAsMaster: Bool
    LeashRange: Int
    UseSlaverAsControlForEvaObjectSightedEvents: Bool
    DieOnMastersDeath: Bool
    MarkUnselectable: Bool
    GuardPositionOffset: Coords
    FadeOutRange: Int
    FadeTime: Int
    RepairWhenBelowHealth_: Int


class SpawnPointProductionExitUpdate(Behavior):
    SpawnPointBoneName: Bone


class DefaultProductionExitUpdate(Behavior):
    UnitCreatePoint: Coords
    NaturalRallyPoint: Coords
    UseSpawnRallyPoint: Bool


class PickupStuffUpdate(Behavior):
    SkirmishAIOnly: Bool
    ScanRange: Float
    StuffToPickUp: ObjectFilter
    ScanIntervalSeconds: Float


class AttachUpdate(Behavior):
    ObjectFilter: t.ObjectFilter
    ScanRange: Float
    ParentStatus: ObjectStatus
    ParentOwnerAttachmentEvaEvent: EvaEvent
    ParentEnemyAttachmentEvaEvent: EvaEvent
    ParentOwnerDiedEvaEvent: EvaEvent
    AlwaysTeleport: Bool
    AnchorToTopOfGeometry: Bool
    ParentAllyAttachmentEvaEvent: EvaEvent
    AttachFX: FXList
    ParentAllyDiedEvaEvent: EvaEvent
    ParentEnemyDiedtEvaEvent: EvaEvent


class HordeNotifyTargetsOfImminentProbableCrushingUpdate(Behavior):
    ScanWidth: Float
    TimeBetweenUpdatesMS: Int
    ScanAheadTimeMS: Int
    ScanHeight: Float


class NotifyTargetsOfImminentProbableCrushingUpdate(Behavior):
    TimeBetweenUpdatesMS: Int
    ScanAheadTimeMS: Int
    ScanHeight: Float
    ScanWidth: Float


class LargeGroupAudioUpdate(Behavior):
    UnitWeight: Int
    Key: Untyped


class GiveUpgradeUpdate(Behavior):
    SpecialPowerTemplate: SpecialPower
    StartAbilityRange: Float
    UnpackTime: Int
    PreparationTime: Int
    PersistentPrepTime: Int
    PackTime: Int
    ApproachRequiresLOS: Bool
    SpawnOutFX: FXList
    DeliverUpgrade: Bool
    FadeOutSpeed: Float
    GiveUpgradeEffect: FXList


class StrafeAreaUpdate(Behavior):
    WeaponName: Weapon
    StrafeAreaRadius: Float
    Sweepfrequency: Float
    SweepAmplitude: Float
    Slope: Float
    InitialSweepPhase: Float


class WeaponModeSpecialPowerUpdate(Behavior):
    SpecialPowerTemplate: SpecialPower
    StartsPaused: Bool
    Duration: Int
    AttributeModifier: ModifierList
    LockWeaponSlot: SlotTypes
    WeaponSetFlags: WeaponsetFlags
    InitiateSound: Sound


class ArrowStormUpdate(Behavior):
    SpecialPowerTemplate: SpecialPower
    StartAbilityRange: Float
    UnpackingVariation: Int
    UnpackTime: Int
    PreparationTime: Int
    PersistentPrepTime: Int
    PackTime: Int
    ApproachRequiresLOS: Bool
    AwardXPForTriggering: Int
    ActiveLoopSound: Sound
    WeaponTemplate: Weapon
    TargetRadius: Float
    ShotsPerTarget: Int
    ShotsPerBurst: Int
    MaxShots: Int
    ParalyzeDurationWhenAborted: Int
    ParalyzeDurationWhenCompleted: Int
    CanShootEmptyGround: Bool
    RequiredConditions: SpecialPowerUnpackConditions


class RepairDockUpdate(Behavior):
    NumberApproachPositions: Int
    AllowsPassthrough: Bool
    TimeForFullHeal: Int


class QueueProductionExitUpdate(Behavior):
    UnitCreatePoint: Coords
    NaturalRallyPoint: Coords
    ExitDelay: Int
    InitialBurst: Int
    PlacementViewAngle: Degrees
    NoExitPath: Bool
    AllowAirborneCreation: Bool
    UseReturnToFormation: Bool
    CanRallyToSlaughter: Bool


class GateBehavior(Behavior):
    OpenByDefault: Bool
    ResetTimeInMilliseconds: Int
    PercentOpenForPathing: Int
    Proxy: Untyped
    RepelCollidingUnits: Bool
    GeometryForOpen: List[Untyped]
    GeometryForClosed: List[Untyped]
    SoundOpeningGateLoop: Sound
    SoundFinishedOpeningGate: Sound
    SoundClosingGateLoop: Sound
    SoundFinishedClosingGate: Sound
    TimeBeforePlayingOpenSound: Int
    TimeBeforePlayingClosedSound: Int


class GateProxyBehavior(GateBehavior):
    pass


class GateOpenAndCloseBehavior(GateBehavior):
    pass


class BattlePlanUpdate(Behavior):
    SpecialPowerTemplate: SpecialPower
    BombardmentPlanAnimationTime: Int
    HoldTheLinePlanAnimationTime: Int
    SearchAndDestroyPlanAnimationTime: Int
    TransitionIdleTime: Int
    ValidMemberKindOf: List[KindOf]
    InvalidMemberKindOf: List[KindOf]
    BattlePlanChangeParalyzeTime: Int
    HoldTheLinePlanArmorDamageScalar: Float
    SearchAndDestroyPlanSightRangeScalar: Float
    StrategyCenterSearchAndDestroySightRangeScalar: Float
    StrategyCenterSearchAndDestroyDetectsStealth: Bool
    StrategyCenterHoldTheLineMaxHealthScalar: Float
    StrategyCenterHoldTheLineMaxHealthChangeType: HealthRatioType
    VisionObjectName: Object
    BombardmentPlanUnpackSoundName: Sound
    BombardmentPlanPackSoundName: Sound
    BombardmentMessageLabel: Untyped
    BombardmentAnnouncementName: Sound
    SearchAndDestroyPlanUnpackSoundName: Sound
    SearchAndDestroyPlanIdleLoopSoundName: Sound
    SearchAndDestroyPlanPackSoundName: Sound
    SearchAndDestroyMessageLabel: Untyped
    SearchAndDestroyAnnouncementName: Sound
    HoldTheLinePlanUnpackSoundName: Sound
    HoldTheLinePlanPackSoundName: Sound
    HoldTheLineMessageLabel: Untyped
    HoldTheLineAnnouncementName: Sound


class BannerCarrierUpdate(Behavior):
    IdleSpawnRate: Int
    MeleeFreeUnitSpawnTime: Int
    DiedRespawnTime: Int
    MeleeFreeBannerReSpawnTime: Int
    BannerMorphFX: FXList
    UnitSpawnFX: FXList
    MorphCondition: List[KeyValuePair]
    ReplenishNearbyHorde: Bool
    ScanHordeDistance: Float
    ReplenishAllNearbyHordes: Bool
    UpgradeRequired: Upgrade
    ExpLevelDraw: List[KeyValuePair]


class ShareExperienceBehavior(Behavior):
    Radius: t.Float
    DropOff: t.Float
    Percentage: t.Float
    Float: t.Float
    ObjectFilter: t.ObjectFilter


class CivilianSpawnUpdate(Behavior):
    SpawnDelayTime: Int
    MaximumDistance: Int
    RunToFilter: ObjectFilter
    Civilian: List[Object]


class BoredUpdate(Behavior):
    ScanDelayTime: Int
    ScanDistance: Float
    BoredFilter: ObjectFilter
    SpecialPowerTemplate: SpecialPower
    CanScanWhileAttackingOrMoving: Bool


class AutoPickUpUpdate(Behavior):
    ScanDelayTime: Int
    PickUpKindOf: List[Untyped]
    ScanDistance: Float
    EatObjectEntry: List[KeyValuePair]
    Bored: Bool
    BoredFilter: ObjectFilter
    RunFromButton: Bool
    RunFromButtonNumber: Int
    PickUpFilter: ObjectFilter
    AutoThrowObject: Bool
    CanScanWhileAttackingOrMoving: Bool


class DemoTrapUpdate(Behavior):
    DefaultProximityMode: Bool
    DetonationWeaponSlot: SlotTypes
    ProximityModeWeaponSlot: SlotTypes
    ManualModeWeaponSlot: SlotTypes
    TriggerDetonationRange: Float
    IgnoreTargetTypes: List[KindOf]
    AutoDetonationWithFriendsInvolved: Bool
    DetonateWhenKilled: Bool
    ScanRate: Int
    AutoDetonationWithFriendsInvolve: Bool
    DetonationWeapon: Weapon


class CommandButtonHuntUpdate(Behavior):
    ScanRate: Int
    ScanRange: Float


class LaserUpdate(Behavior):
    MuzzleParticleSystem: ParticleSystem
    ParentFireBoneName: Bone
    ParentFireBoneOnTurret: Bool
    TargetParticleSystem: ParticleSystem
    PunchThroughScalar: Float
    LaserLifetime: Float


class HeightDieUpdate(Behavior):
    TargetHeight: Float
    TargetHeightIncludesStructures: Bool
    OnlyWhenMovingDown: Bool
    DestroyAttachedParticlesAtHeight: Float
    SnapToGroundOnDeath: Bool
    InitialDelay: Int


class FloodUpdate(Behavior):
    AngleOfFlow: Degrees
    DirectionIsRelative: Bool

    nested_attributes = {"FloodMember": ["FloodMember"]}


class FloatUpdate(Behavior):
    Enabled: Bool


class FlammableUpdate(Behavior):
    FlameDamageLimit: Float
    FlameDamageExpiration: Int
    AflameDuration: Int
    AflameDamageAmount: Int
    AflameDamageDelay: Int
    BurnedDelay: Int
    BurningSoundName: Sound
    BurnContained: Bool
    FireFXList: List[KeyValuePair]
    SwapModelWhenAflame: Bool
    SwapModelWhenQuenched: Bool
    RunToWater: Bool
    RunToWaterDepth: Float
    RunToWaterSearchRadius: Float
    RunToWaterSearchIncrement: Float
    PanicLocomotorWhileAflame: Bool
    CustomAnimAndDuration: AnimAndDuration
    SetBurnedStatus: Bool
    DamageType: e.DamageType
    SwapTextureWhenAflame: Bool
    SwapTextureWhenQuenhed: Bool


class MonitorConditionUpdate(Behavior):
    ModelConditionCommandSet: CommandSet
    WeaponSetFlags: WeaponsetFlags
    WeaponToggleCommandSet: CommandSet
    ModelConditionFlags: List[ModelCondition]


class DamageFieldUpdate(Behavior):
    nested_attributes = {"FireWeaponNugget": ["FireWeaponNugget"]}

    Radius: Int
    ObjectFilter: t.ObjectFilter
    RequiredUpgrade: Upgrade
    HeroModeTrigger: Bool
    ChargingModeTrigger: Bool
    AliveOnly: Bool


class OilSpillUpdate(Behavior):
    nested_attributes = {"FireWeaponNugget": ["FireWeaponNugget"]}

    BreadcrumbName: Object
    IgnitionWeaponSpacing: Float
    AliveOnly: Bool
    OilSpillFX: FXList
    HeroModeTrigger: Bool
    ChargingModeTrigger: Bool
    IgnitionWeaponName: Weapon


class FireWeaponUpdate(Behavior):
    nested_attributes = {"FireWeaponNugget": ["FireWeaponNugget"]}

    Weapon: Weapon
    ExclusiveWeaponDelay: Int
    InitialDelay: Int
    ChargingModeTrigger: Bool
    AliveOnly: Bool
    HeroModeTrigger: Bool


class FireSpreadUpdate(Behavior):
    OCLEmbers: ObjectCreationList
    MinSpreadDelay: Int
    MaxSpreadDelay: Int
    SpreadTryRange: Float


class AutoDepositUpdate(Behavior):
    DepositTiming: Int
    DepositAmount: Int
    InitialCaptureBonus: Int
    ActualMoney: Bool
    UpgradedBoost: Opaque
    Upgrade: io.Upgrade
    UpgradeBonusPercent: Float
    UpgradeMustBePresent: ObjectFilter
    GiveNoXP: Bool
    OnlyWhenGarrisoned: Bool


class PartTheHeavensUpdate(Behavior):
    nested_attributes = {"Radius": ["FCurve"], "Opacity": ["FCurve"], "Angle": ["FCurve"]}

    Texture: Image
    Color: t.RGBA


class DestroyEnvironmentUpdate(Behavior):
    StartTime: Int
    DestructionTime: Int


class RainOfFireUpdate(Behavior):
    StartRainTime: Int
    DarknessFadeTime: Int
    RainEmitterHeight: Float
    DarknessLevel: Float
    JitterRadius: Float
    DPSMin: Float
    DPSMax: Float
    DPSRampupTime: Int
    RainOffset: Coords


class RadiusDecalUpdate(Behavior):
    pass


class SpecialEnemySenseUpdate(Behavior):
    SpecialEnemyFilter: ObjectFilter
    ScanRange: Float
    ScanInterval: Int


class OneRingPenaltyUpdate(Behavior):
    SpecialObjectName: Object
    RingTimeBeforeSpawning: Int
    TimeSpentRoamingAround: Int
    TimeRingPowerSuppressed: Int
    StartingDistanceFromMe: Float
    TimeFrozenFromPenalty: Int
    DiscoveredSound: Sound


class LifetimeUpdate(Behavior):
    MinLifetime: Int
    MaxLifetime: Int
    WaitForWakeUp: Bool
    DeathType: e.DeathType
    ScoreKill: Bool


class DelayedLuaEventUpdate(Behavior):
    pass


class ToppleUpdate(Behavior):
    ToppleFX: FXList
    BounceFX: FXList
    KillWhenStartToppling: Bool
    KillWhenFinishedToppling: Bool
    KillStumpWhenToppled: Bool
    ToppleLeftOrRightOnly: Bool
    ReorientToppledRubble: Bool
    BounceVelocityPercent: Float
    InitialAccelPercent: Float
    StumpName: Object
    InitialVelocityPercent: Float
    MinimumToppleSpeed: Float


class LargeGroupBonusUpdate(Behavior):
    UpdateRate: Int
    HordeMemberFilter: ObjectFilter
    Count: Int
    Radius: Float
    RubOffRadius: Float
    AlliesOnly: Bool
    AttributeModifier: ModifierList
    FlagSubObjectNames: List[Untyped]


class DynamicShroudClearingRangeUpdate(Behavior):
    ChangeInterval: Int
    GrowInterval: Int
    ShrinkDelay: Int
    ShrinkTime: Int
    GrowDelay: Int
    GrowTime: Int
    FinalVision: Float
    GridDecalTemplate: Untyped


class DeletionUpdate(Behavior):
    MinLifetime: Int
    MaxLifetime: Int


class DelayedWeaponSetUpgradeUpdate(Behavior):
    pass


class InvisibilityUpdate(Behavior):
    UpdatePeriod: Int
    RequiredUpgrades: List[Upgrade]
    ForbiddenUpgrades: List[Upgrade]
    Broadcast: Bool
    BroadcastObjectFilter: ObjectFilter
    BroadcastRange: Float
    StartsActive: Bool

    nested_attributes = {"InvisibilityNugget": ["InvisibilityNugget"]}
    UnitSpecificSoundNameToUseAsVoiceMoveToStealthyArea: Sound
    UnitSpecificSoundNameToUseAsVoiceEnterStateMoveToStealthyArea: Sound


class CostModifierUpgrade(UpgradeBehavior):
    LabelForPalantirString: Label
    UpgradeDiscount: Bool
    ApplyToTheseUpgrades: List[Upgrade]
    EffectKindOf: KindOf
    Percentage: List[Float]
    ObjectFilter: t.ObjectFilter
    Slaughter: Bool


class OathbreakersFadeAwayBehavior(Behavior):
    FadeOutTime: Int


class BridgeBehavior(Behavior):
    BridgeDieFX: Untyped
    BridgeDieOCL: Untyped
    LateralScaffoldSpeed: Float
    VerticalScaffoldSpeed: Float


class UpgradeSoundSelectorClientBehavior(Behavior):
    nested_attributes = {"SoundUpgrade": ["SoundUpgrade"]}  # class in `model.misc_blocks`
