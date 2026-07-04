"""Top-level non-`Object` data-definition blocks (art, audio, FX, terrain, UI, AI,
living-world). Registering each with its table `key` makes it a recognised typed object and
populates the cross-reference tables the `Reference` converters resolve against. Most carry
no field annotations — their values stay raw and lossless until a schema is needed.
"""

from typing import TYPE_CHECKING

import sage_ini.model.enums as e
import sage_ini.model.types as t
from sage_ini.model.objects import IniObject, NestedAttribute
from sage_ini.model.types import (
    RGBA,
    Bool,
    Coords,
    FlagList,
    Float,
    Image,
    Int,
    KeyValuePair,
    List,
    ObjectFilter,
    Opaque,
    Sound,
    Untyped,
)

if TYPE_CHECKING:
    from sage_ini.model.ini_objects import Object, Upgrade


class MappedImage(IniObject):
    key = "mappedimages"

    Texture: t.TextureFile
    TextureWidth: Int
    TextureHeight: Int
    Coords: KeyValuePair
    Status: e.MappedImageStatus


class AudioEvent(IniObject):
    key = "audioevents"

    Volume: Float
    MinVolume: Float
    Limit: Int
    MinRange: Float
    MaxRange: Float
    Priority: e.AudioPriority
    PlayPercent: Int
    Type: FlagList[e.AudioTypeFlags]
    SubmixSlider: e.AudioVolumeSlider
    Control: FlagList[e.AudioControlFlags]
    Sounds: List[Opaque]
    Attack: List[Opaque]
    Decay: List[Opaque]
    PitchShift: Untyped
    PerFilePitchShift: Untyped
    VolumeShift: Untyped
    PerFileVolumeShift: Untyped
    Delay: Untyped
    VolumeSliderMultiplier: t.VolumeSliderMultiplier
    ReverbEffectLevel: Float
    DryLevel: Float
    LowPassCutoff: Float
    ZoomedInOffscreenVolumePercent: Float
    ZoomedInOffscreenMinVolumePercent: Float
    ZoomedInOffscreenOcclusionPercent: Float
    LoopCount: Int
    # A nested `AudioEvent` sequence entry: one sound played at a delay from the act start.
    Sound: Opaque
    DelayFromActStart: Float


class FXParticleSystem(IniObject):
    key = "particlesystems"

    nested_attributes = {
        "System": ["System"],
        "Color": ["Color"],
        "Alpha": ["Alpha"],
        "Update": ["Update"],
        "Physics": ["Physics"],
        "EmissionVelocity": ["EmissionVelocity"],
        "EmissionVolume": ["EmissionVolume"],
        "Wind": ["Wind"],
        "Event": ["Event"],
        "Emitter": ["Emitter"],
    }
    BurstCount: t.RandomVariable
    BurstDelay: t.RandomVariable
    Draw: Opaque
    InitialDelay: t.RandomVariable
    IsEmitAboveGroundOnly: Bool
    IsGroundAligned: Bool
    IsOneShot: Bool
    IsParticleUpTowardsEmitter: Bool
    Lifetime: t.RandomVariable
    ParticleName: t.TextureFile
    PerParticleAttachedSystem: Opaque
    Priority: e.ParticleSystemPriority
    Shader: e.ParticleSystemShader
    ShroudEmitter: Bool
    Size: t.RandomVariable
    SlavePosOffset: Coords
    SlaveSystem: Opaque
    SortLevel: Int
    StartSizeRate: t.RandomVariable
    SystemLifetime: Int
    Type: e.ParticleSystemType
    UseMaximumHeight: Bool


class FXList(IniObject):
    key = "fxlists"

    PlayEvenIfShrouded: Bool
    ParticleSysBone: List[Untyped]
    CullingInfo: Untyped
    CursorParticleSystem: t.Opaque
    Tracer: t.Opaque

    nested_attributes = {
        "ParticleSystem": ["ParticleSystem"],
        "Sound": ["Sound"],
        "EvaEvent": ["EvaEvent"],
        "DynamicDecal": ["DynamicDecal"],
        "FXListAtBonePos": ["FXListAtBonePos"],
        "TerrainScorch": ["TerrainScorch"],
        "CameraShakerVolume": ["CameraShakerVolume"],
        "BuffNugget": ["BuffNugget"],
        "ViewShake": ["ViewShake"],
        "TintDrawable": ["TintDrawable"],
        "LightPulse": ["LightPulse"],
        "AttachedModel": ["AttachedModel"],
    }


class Terrain(IniObject):
    key = "terrains"

    Texture: t.TextureFile
    Class: Untyped
    BlendEdges: Bool
    RestrictConstruction: Bool
    TerrainObject: List[t.Tuple[t.ObjectRef, Int]]  # `<object> <density>`, one per repeat


class DialogEvent(IniObject):
    key = "dialogevents"

    Volume: Float
    DryLevel: Float
    ReverbEffectLevel: Float
    Filename: t.AudioFile
    Type: FlagList[e.AudioTypeFlags]
    SubmixSlider: e.AudioVolumeSlider
    Control: Opaque
    Delay: t.IntRange
    Limit: t.Int
    LowPassCutoff: t.Float
    MaxRange: t.Float
    MinRange: t.Float
    MinVolume: t.Float
    PerFilePitchShift: t.FloatRange
    PerFileVolumeShift: t.Float
    PitchShift: t.FloatRange
    PlayPercent: t.Float
    Priority: e.AudioPriority
    VolumeShift: t.Float
    VolumeSliderMultiplier: t.VolumeSliderMultiplier
    ZoomedInOffscreenMinVolumePercent: t.Float
    ZoomedInOffscreenOcclusionPercent: t.Float
    ZoomedInOffscreenVolumePercent: t.Float


class MusicTrack(IniObject):
    key = "musictracks"

    Filename: t.AudioFile
    Volume: Float
    DryLevel: Float
    ReverbEffectLevel: Float
    SubmixSlider: e.AudioVolumeSlider
    Type: FlagList[e.AudioTypeFlags]
    Control: FlagList[e.AudioControlFlags]
    Delay: t.IntRange
    Limit: t.Int
    LowPassCutoff: t.Float
    MaxRange: t.Float
    MinRange: t.Float
    MinVolume: t.Float
    PerFilePitchShift: t.FloatRange
    PerFileVolumeShift: t.Float
    PitchShift: t.FloatRange
    PlayPercent: t.Float
    Priority: e.AudioPriority
    VolumeShift: t.Float
    VolumeSliderMultiplier: t.VolumeSliderMultiplier
    ZoomedInOffscreenMinVolumePercent: t.Float
    ZoomedInOffscreenOcclusionPercent: t.Float
    ZoomedInOffscreenVolumePercent: t.Float


class Multisound(IniObject):
    key = "multisounds"

    Subsounds: List[t.MusicTrackRef]
    Control: FlagList[e.AudioControlFlags]


class SideSound(NestedAttribute):
    """A per-side sound binding in an EVA event (`SideSound { Side; Sound }`): which audio
    event plays for which faction, so one announcement voices differently per side."""

    Side: e.FactionSide
    Sound: Sound


class _EvaEventBase(IniObject):
    """Shared shape of the two EVA-event blocks: an announcement's timing/priority plus its
    per-side sounds. `NewEvaEvent` declares a fresh event; `PredefinedEvaEvent` parameterizes
    a built-in one — both register into `evaevents`."""

    key = "evaevents"

    Priority: Int
    TimeBetweenEventsMS: Int
    ExpirationTimeMS: Int
    AlwaysPlayFromHomeBase: Bool
    CountAsJumpToLocation: Bool

    nested_attributes = {"SideSound": ["SideSound"]}


class NewEvaEvent(_EvaEventBase):
    key = "evaevents"

    MillisecondsToWaitBeforePlaying: Int
    OtherEvaEventsToBlock: List[Opaque]


class Video(IniObject):
    key = "videos"

    Filename: Opaque
    Comment: Untyped
    Volume: Float
    IsDefault: Bool


class HouseColor(IniObject):
    key = "housecolors"

    BaseTexture: t.TextureFile
    HouseTexture: t.TextureFile


class LivingWorldPlayerArmy(IniObject):
    key = "livingworldplayerarmys"

    Name: Untyped
    DisplayNameTag: t.Label
    Color: t.RGB
    MinCommandPoints: t.Int
    NightColor: t.RGB
    ReplenishArmyName: t.Opaque

    nested_attributes = {"ArmyEntry": ["ArmyEntry"]}


class Rank(IniObject):
    key = "ranks"

    SkillPointsNeededDefault: Int
    SkillPointsNeededCampaign: Int
    SciencePurchasePointsGranted: Int
    RankName: t.Label
    SciencesGranted: t.Opaque
    SkillPointsNeeded: t.Int


class AutoResolveBody(IniObject):
    key = "autoresolvebodys"

    HitpointsAtLevel: KeyValuePair  # `Hitpoints:<n> Level:<n>`, one per repeat
    LeaveInArmySummary: Bool
    CanBeAttacked: Bool


class AIBase(IniObject):
    key = "aibases"
    unique_name = False

    Side: e.FactionSide
    Map: t.MapFile
    GameMapToUseOn: t.QuotedList[t.MapFile]
    PlayerPositions: Int
    AllowsArbirtaryRotation: Bool


class DebugCommandMap(IniObject):
    key = "debugcommandmaps"

    Key: Untyped
    Transition: Untyped
    Modifiers: Untyped
    UseableIn: Untyped
    Category: Untyped


class MouseCursor(IniObject):
    key = "cursors"

    Texture: t.TextureFile
    Image: t.TextureFile
    HotSpot: Coords
    Directions: Int


class LivingWorldIconObject(NestedAttribute):
    """A drawable sub-object of a strategic-map icon (`LivingWorldBuildingIcon`,
    `LivingWorldArmyIcon`, `LivingWorldBuildPlotIcon`): its own model, placement and fade
    behaviour. Shares the `Object` keyword with a game `Object` but is not one — it names an art
    layer (`Building`, `Scaffold`, `SelectedGlow`, …), not a battle unit, so it is held on its
    parent icon and never registers into `game.objects`."""

    key = None

    Model: Opaque
    SubObjects: Opaque
    AnimMode: Opaque
    ZOffset: Float
    OrientAngle: Float
    Scale: Float
    Clickable: Bool
    Pickbox: Opaque
    Shadow: Opaque
    HideWhenUnderConstruction: Bool
    HideWhenNotUnderConstruction: Bool
    HideWhenUnhilighted: Bool
    HideWhenUnselected: Bool
    HideWhenNotProducing: Bool
    ShowOnlyForAllies: Bool
    FadeMethod: Opaque
    FadeTypeForHilighting: Opaque
    FadeTypeForUnhilighting: Opaque
    FadeTypeForSelection: Opaque
    FadeTypeForShowing: Opaque
    FadeTypeForHiding: Opaque
    FadeHoldPercent: Float
    FadeInTime: Float
    FadeOutTime: Float
    # LivingWorldArmyIcon adds these to the shared drawable shape.
    DisplayAtRallyPoint: Bool
    ShowOnlyAfterMoveOrder: Bool
    UseHouseColor: Bool
    VisibleArmySizes: Opaque


class LivingWorldArmyIcon(IniObject):
    key = "livingworldarmyicons"

    nested_attributes = {"Object": ["LivingWorldIconObject"]}
    subblock_overrides = {"Object": LivingWorldIconObject}

    OnSelectedSound: Sound
    OnMovePlannedSound: Sound
    OnMoveStartedSound: Sound
    WelcomeReinforcementsSound: Sound
    KickOutReinforcementsSound: Sound
    DisbandUnitSound: Sound
    RetreatTeleportToHomeRegionEvaEvent: Opaque
    RetreatTeleportToNonHomeRegionEvaEvent: Opaque
    OnMoveSound: t.Opaque


class LivingWorldAnimObject(IniObject):
    key = "livingworldanimobjects"

    Model: Opaque
    Pos: Coords
    Shadow: Untyped
    HasAnim: Bool
    Xfer: Bool
    Frame: Float
    OrientAngle: Float


class LargeGroupAudioMap(IniObject):
    key = "largegroupaudiomaps"

    Size: Int
    StartThreshold: Int
    StopThreshold: Int
    HandOffModeDuration: Int
    MaximumAudioSpeed: Int
    ExcludedObjectStatusBits: Untyped
    ExcludedModelConditionFlags: Untyped
    RequiredModelConditionFlags: Untyped
    IgnoreStealthedUnits: Bool
    Sound: Sound


class ControlBarResizer(IniObject):
    key = "controlbarresizers"

    AltPosition: Coords
    AltSize: Coords


class Road(IniObject):
    key = "roads"

    Texture: t.TextureFile
    RoadWidth: Float
    RoadWidthInTexture: Float


class WindowTransition(IniObject):
    key = "windowtransitions"

    FireOnce: Bool

    nested_attributes = {"Window": ["Window"]}


class LivingWorldCampaign(IniObject):
    key = "livingworldcampaigns"

    nested_attributes = {"Act": ["Act"], "Scenario": ["Scenario"], "AddPlayer": ["AddPlayer"]}

    IsEvilCampaign: Bool
    IsScriptedCampaign: Bool
    SecondsPerReinforcement: Int
    StartingCashRTS: Int
    StartingCashRTSWithFort: Int
    InitialRevivalCostMultiplier: Float
    InitialRevivalTimeMultiplier: Float
    LocalPlayer: Opaque
    LivingWorldVictoryType: t.Opaque
    Tutorial: t.Opaque


class LoadSubsystem(IniObject):
    key = "loadsubsystems"

    Loader: e.SubsystemLoader
    InitFile: Opaque
    InitFileDebug: Opaque
    InitPath: Opaque
    ExcludePath: Opaque
    IncludePathCinematics: Opaque


class LivingWorldBuilding(IniObject):
    key = "livingworldbuildings"

    nested_attributes = {"BuildingNugget": ["BuildingNugget"]}

    AvailableTo: t.PlayerTemplateRef
    BattleThingTemplate: t.ObjectRef
    BuildingIcon: t.BuildingIconRef
    ConstructButtonImage: t.Label
    TurnsToBuild: Int
    Type: Untyped
    ConstructButtonTitle: t.Label
    ConstructButtonHelp: t.Label
    DisplayNameTag: t.Label
    DisplayDescriptionTag: t.Label
    CreateUnitDuringAutoResolve: Bool
    CanDefendTerritory: Bool
    StrategicResourceCost: t.Int


class LivingWorldBuildingIcon(IniObject):
    key = "livingworldbuildingicons"

    nested_attributes = {"Object": ["LivingWorldIconObject"]}
    subblock_overrides = {"Object": LivingWorldIconObject}

    OnSelectedSound: Sound
    OnConstructionBegunSound: Sound
    OnConstructionFinishedSound: Sound


class AmbientStream(IniObject):
    key = "ambientstreams"

    Filename: t.SoundFile
    Volume: Float
    MinRange: Float
    MaxRange: Float
    DryLevel: Float
    ReverbEffectLevel: Float
    Type: FlagList[e.AudioTypeFlags]
    Control: FlagList[e.AudioControlFlags]
    SubmixSlider: e.AudioVolumeSlider
    Delay: t.IntRange
    Limit: t.Int
    LowPassCutoff: t.Float
    MinVolume: t.Float
    PerFilePitchShift: t.FloatRange
    PerFileVolumeShift: t.Float
    PitchShift: t.FloatRange
    PlayPercent: t.Float
    Priority: e.AudioPriority
    VolumeShift: t.Float
    VolumeSliderMultiplier: t.VolumeSliderMultiplier
    ZoomedInOffscreenMinVolumePercent: t.Float
    ZoomedInOffscreenOcclusionPercent: t.Float
    ZoomedInOffscreenVolumePercent: t.Float


class LivingWorldSound(IniObject):
    key = "livingworldsounds"

    Sound: Sound
    Flags: Untyped
    Position: Coords
    ZoomRegionLow: Coords
    ZoomRegionHigh: Coords


class PredefinedEvaEvent(_EvaEventBase):
    key = "evaevents"

    QuietTimeMS: Int


class PlayerAIType(IniObject):
    key = "playeraitypes"

    LibraryMap: t.String


class DamageFX(IniObject):
    key = "damagefxs"

    # Per-`DamageType` FX bindings (`<DamageType> <value>`), each repeating once per type.
    ThrottleTime: List[Untyped]
    AmountForMajorFX: List[Untyped]
    MajorFX: List[Untyped]
    MinorFX: List[Untyped]
    VeterancyMajorFX: t.FXList
    VeterancyMinorFX: t.FXList


class FactionVictoryData(IniObject):
    key = "factionvictorydatas"

    AllyDeathScaleFactor: Float
    EnemyKillScaleFactor: Float
    VictoryThreshold: Float
    MajorUnitValue: Float
    MapToCellVictoryRatio: Float


class AutoResolveLeadership(IniObject):
    key = "autoresolveleaderships"

    Affects: List[Opaque]
    AffectsHigherLevelFirst: Bool

    nested_attributes = {"BonusForLevel": ["BonusForLevel"]}


class AutoResolveHandicapLevel(IniObject):
    key = "autoresolvehandicaplevels"

    GUIDisplayedLevel: Int
    WeaponMultiplier: Float
    ArmorMultiplier: Float
    ExperienceMultiplier: Float


class MultiplayerColor(IniObject):
    key = "multiplayercolors"

    RGBColor: RGBA
    RGBNightColor: RGBA
    LivingWorldColor: RGBA
    LivingWorldBannerColor: RGBA
    TooltipName: Untyped
    AvailableInWotR: Bool


class LivingWorldPlayerTemplate(IniObject):
    key = "livingworldplayertemplates"

    Faction: t.FactionRef
    Music: Opaque
    AutoResolveLoop: Opaque
    StartingWorldCP: Int
    MaxWorldCP: Int
    StartingHeroCP: Int
    MaxHeroCP: Int
    FactionIcon: t.String
    DefaultArmyIconName: t.String
    BuildPlotIconName: t.String
    BuildPlotSelectionPortraitName: t.String
    GarrisonSelectionPortraitName: t.String
    GarrisonDisplayNameTag: Untyped
    FactionDozerTemplateName: t.String
    FactionInnUnitTemplateName: t.String
    ScenarioMaxResources: t.Int
    ScenarioStartResources: t.Int


class BannerType(IniObject):
    key = "bannertypes"

    FlagObj: Opaque
    GlowObj: "Object"
    Icon: Image
    WipeFrame: t.Int
    WipeMovie: t.Opaque


class LivingWorldBuildPlotIcon(IniObject):
    key = "livingworldbuildploticons"

    nested_attributes = {"Object": ["LivingWorldIconObject"]}
    subblock_overrides = {"Object": LivingWorldIconObject}

    OnSelectedSound: Sound
    OnBuildingDestroyedSound: Sound


class SpawnArmy(IniObject):
    key = "spawnarmys"

    ScriptingName: Opaque
    SpawnForTemplates: t.PlayerTemplateRef
    PlayerArmy: Opaque
    Icon: t.ArmyIcon
    HeroTemplateName: t.ObjectRef
    Banner: t.BannerTypeRef
    InitialRegion: Opaque
    MoveSpeed: Float
    IsCity: Bool
    PalantirMovie: Opaque
    Position: Coords


class AIDozerAssignment(IniObject):
    key = "aidozerassignments"

    Side: e.FactionSide
    Unit: t.ObjectRef


class ArmyMemberDefinition(NestedAttribute):
    """One unit slot of an `ArmyDefinition` (`ArmyMemberDefinition <name>`): the unit and the
    share of the army it makes up at each skirmish-AI build phase."""

    Unit: "Object"
    PercentageOfArmyPhase1: Float
    PercentageOfArmyPhase2: Float
    PercentageOfArmyPhase3: Float


class UnitCategory(NestedAttribute):
    """A banner-UI unit grouping in an `ArmySummaryDescription`: its display names and the
    object filter that decides which units fall under it."""

    Name: t.Label
    PluralName: t.Label
    Filter: ObjectFilter


class ThingStat(NestedAttribute):
    """A tracked statistic in the `AwardSystem`: its id, display strings and the templates or
    kinds it counts."""

    StatName: Untyped
    NameTag: Untyped
    DescriptionTag: t.Label
    ThingTemplateNames: List["Object"]
    KindOf: List[e.KindOf]
    ExcludedKindOf: List[e.KindOf]


class CreateAHeroBling(NestedAttribute):
    """A Create-a-Hero "bling" option in `CreateAHeroSystem`: a cosmetic/weapon choice with
    its display strings, menu group and the upgrade that applies it."""

    NameTag: t.Label
    DescriptionTag: t.Label
    GroupName: Untyped
    BlingUpgradeName: "Upgrade"


class ArmyDefinition(IniObject):
    key = "armydefinitions"

    nested_attributes = {
        "ArmyMemberDefinition": ["ArmyMemberDefinition"],
        "AIEconomyAssigment": ["AIEconomyAssigment"],
        "AIWallNodeAssignment": ["AIWallNodeAssignment"],
    }

    Side: e.FactionSide

    MustUseCommandPointPercentage_Phase1: Float
    MustUseCommandPointPercentage_Phase2: Float
    MustUseCommandPointPercentage_Phase3: Float
    StructureRebuildPriorityModifier: Float
    DefaultUnitPriority: Float
    FortressRebuildPriority: Float
    LowUnitPriorityModifier_Rush: Float
    LowUnitPriorityModifier_MidGame: Float
    LowUnitPriorityModifier_EndGame: Float
    PhaseDuration_Rush: Float
    PhaseDuration_MidGame: Float

    EconomyBuilderMinFarmsOwned: Int
    EconomyBuilderMinMoney: Int
    EconomyBuilderPerFarmValue: Int
    EconomyBuilderPerSecPriorityIncreaseBase: Float
    EconomyBuilderMinTimeBetweenFarms_Rush: Float
    PercentToSave_Rush: Float
    PercentToSave_MidGame: Float
    PercentToSave_EndGame: Float

    ChanceForUnitsToUpgrade: Float
    UpgradeSciencePriorityNormalLow: Float
    UpgradeSciencePriorityNormalHigh: Float
    UpgradeSciencePriorityImportantLow: Float
    UpgradeSciencePriorityImportantHigh: Float
    UnitUpgradePriorityLow: Float
    UnitUpgradePriorityHigh: Float

    MaxThreatForOpportunityTargets: Float
    ValueToSetForMaxOnDefenseTeam: Int
    CombatChainSearchDepthForTeamRecruits_AttackTeams: Int
    CombatChainSearchDepthForTeamRecruits_DefenseTeams: Int
    CombatChainSearchDepthForTeamRecruits_ExploreTeams: Int
    TacticalAITargets: Untyped
    MaxTeamsPerTarget: Untyped
    SecondsTillTargetsCanExpire: Float
    ChanceForTargetToExpire: Float
    MaxBuildingsToBeDefensiveTarget_Small: Int
    MaxBuildingsToBeDefensiveTarget_Med: Int
    ChanceToUseAllUnitsForDefenseTarget_Small: Float
    ChanceToUseAllUnitsForDefenseTarget_Med: Float
    ChanceToUseAllUnitsForDefenseTarget_Large: Float

    HeroBuildOrder: List[t.ObjectRef]
    OffensiveBuildings: List[t.ObjectRef]
    ScavangedResourceBuildings: t.Opaque


class ControlBarScheme(IniObject):
    key = "controlbarschemes"

    nested_attributes = {"ImagePart": ["ImagePart"]}

    ScreenCreationRes: Untyped  # a `width height` pair
    Side: e.FactionSide
    CommandBarBorderColor: RGBA
    BuildUpClockColor: RGBA
    ButtonBorderBuildColor: RGBA
    ButtonBorderActionColor: RGBA
    ButtonBorderUpgradeColor: RGBA
    ButtonBorderSystemColor: RGBA
    ButtonBorderAlteredColor: RGBA
    BeaconButtonDisabled: t.Image
    BeaconButtonEnable: t.Image
    BeaconButtonHightlited: t.Image
    BeaconButtonPushed: t.Image
    BeaconLR: t.Coords
    BeaconUL: t.Coords
    BuddyButtonDisabled: t.Image
    BuddyButtonEnable: t.Image
    BuddyButtonHightlited: t.Image
    BuddyButtonPushed: t.Image
    ChatLR: t.Coords
    ChatUL: t.Coords
    CommandMarkerImage: t.Image
    ExpBarForegroundImage: t.Image
    GenArrow: t.Image
    GenBarButtonIn: t.Image
    GenBarButtonOn: t.Image
    GeneralButtonDisabled: t.Image
    GeneralButtonEnable: t.Image
    GeneralButtonHightlited: t.Image
    GeneralButtonPushed: t.Image
    GeneralLR: t.Coords
    GeneralUL: t.Coords
    IdleWorkerButtonDisabled: t.Image
    IdleWorkerButtonEnable: t.Image
    IdleWorkerButtonHightlited: t.Image
    IdleWorkerButtonPushed: t.Image
    MinMaxButtonEnable: t.Image
    MinMaxButtonHightlited: t.Image
    MinMaxButtonPushed: t.Image
    MinMaxLR: t.Coords
    MinMaxUL: t.Coords
    MoneyLR: t.Coords
    MoneyUL: t.Coords
    OptionsButtonDisabled: t.Image
    OptionsButtonEnable: t.Image
    OptionsButtonHightlited: t.Image
    OptionsButtonPushed: t.Image
    OptionsLR: t.Coords
    OptionsUL: t.Coords
    PowerBarLR: t.Coords
    PowerBarUL: t.Coords
    PowerPurchaseImage: t.Image
    QueueButtonImage: t.Image
    RightHUDImage: t.Image
    ToggleButtonDownIn: t.Image
    ToggleButtonDownOn: t.Image
    ToggleButtonDownPushed: t.Image
    ToggleButtonUpIn: t.Image
    ToggleButtonUpOn: t.Image
    ToggleButtonUpPushed: t.Image
    UAttackButtonEnable: t.Image
    UAttackButtonHightlited: t.Image
    UAttackButtonPushed: t.Image
    UAttackLR: t.Coords
    UAttackUL: t.Coords
    WorkerLR: t.Coords
    WorkerUL: t.Coords


class ConcurrentRegionBonus(IniObject):
    key = "concurrentregionbonus"

    Territory: t.Label
    EffectName: t.String
    Regions: List[Opaque]
    UnifiedEvaEvent: Opaque
    LostEvaEvent: Opaque
    LookAtCenter: Coords
    LookAtHeading: Float
    LookAtZoom: Float
    AttackBonus: Int
    DefenseBonus: Int
    ExperienceBonus: Int
    ArmyBonus: t.Int
    BuildingDiscountBonus: t.Int
    DiscountedBarracksUnitsBonus: t.Int
    DiscountedHeroUnitsBonus: t.Int
    DiscountedSeigeUnitsBonus: t.Int
    ExtraStartResourcesBonus: t.Int
    FreeBuilderBonus: t.Int
    FreeInnUnitsBonus: t.Int
    LegendaryBonus: t.Int
    ResourceBonus: t.Int


class CrowdResponse(IniObject):
    key = "crowdresponses"

    Weight: Int

    nested_attributes = {"Threshold": ["Threshold"]}


class LivingWorldObject(IniObject):
    key = "livingworldobjects"

    ObjectType: e.LivingWorldObjectType
    DefaultFlashValue: Float
    FlashVariation: Float


class WaterTextureList(IniObject):
    key = "watertexturelists"

    Texture: List[t.TextureFile]


class SkyboxTextureSet(IniObject):
    key = "skyboxtexturesets"

    SkyboxTextureN: Opaque
    SkyboxTextureE: Opaque
    SkyboxTextureS: Opaque
    SkyboxTextureW: Opaque
    SkyboxTextureT: Opaque


class LivingWorldRegionCampaign(IniObject):
    key = "livingworldregioncampaigns"

    nested_attributes = {"Region": ["Region"]}

    RegionConqueredSound: Sound
    RegionEffectsManagerName: t.String
    RegionBonusArmy: t.Label
    RegionBonusResource: t.Label
    RegionBonusLegendary: t.Label
    HeroOnlyArmyCommandPoints: Int
    SmallArmyCommandPoints: Int
    MediumArmyCommandPoints: Int
    ArmyRetreatRounds: Int
    ArmyPlacementPos: List[Coords]
    ConcurrentRegionBonus: t.Opaque
    ConqueredEffectEvenglow: t.Opaque
    ConqueredEffectFlareup: t.Opaque
    EnemyBordersEffect: t.Opaque
    FriendlyBordersEffect: t.Opaque
    HilightBordersEffect: t.Opaque
    MouseoutEffectFlareupContested: t.Opaque
    MouseoutEffectFlareupOwned: t.Opaque
    MouseoverEffectFlareupContested: t.Opaque
    MouseoverEffectFlareupOwned: t.Opaque
    RegionObject: t.Opaque
    RegionPopupDefaultColor: t.RGBA
    RegionPopupOverColor: t.RGBA
    ZOffset: t.Int


class WeatherData(IniObject):
    key = "weatherdatas"

    HasLightning: Bool
    WeatherSound: Sound


class AutoResolveCombatChain(IniObject):
    key = "autoresolvecombatchains"

    Target: List[Untyped]  # `Target:<unit> Priority:<n>`, one per repeat


class ExperienceScalarTable(IniObject):
    key = "experiencescalartables"

    Scalars: List[Float]


class WebpageURL(IniObject):
    key = "webpageurls"

    URL: Opaque


class DynamicGameLOD(IniObject):
    key = "dynamicgamelods"

    MinimumFPS: Int
    ParticleSkipMask: Int
    DebrisSkipMask: Int
    SlowDeathScale: Float
    MinParticlePriority: e.ParticleSystemPriority
    MinParticleSkipPriority: e.ParticleSystemPriority


class LinearCampaign(IniObject):
    key = "linearcampaigns"

    CampaignDisplayNameLabel: t.Label
    CarryoverUnit: t.ObjectRef
    OverallCampaignIntroMovie: Opaque

    nested_attributes = {"Mission": ["Mission"]}


class StaticGameLOD(IniObject):
    key = "staticgamelods"

    ModelLOD: Untyped
    EffectsLOD: Untyped
    ShadowLOD: Untyped
    WaterLOD: Untyped
    AnimationDetail: Untyped
    ShaderLOD: Untyped
    DecalLOD: Untyped
    MinParticlePriority: Untyped
    MinParticleSkipPriority: Untyped
    MaxParticleCount: Int
    MaxTankTrackEdges: Int
    MaxTankTrackOpaqueEdges: Int
    MaxTankTrackFadeDelay: Int
    TextureReductionFactor: Int
    UseShadowVolumes: Bool
    UseShadowDecals: Bool
    UseShadowMapping: Bool
    UseTerrainNormalMap: Bool
    UseDistanceDependantTerrainTextures: Bool
    ShowSoftWaterEdge: Bool
    ShowProps: Bool
    ShaderMaterialReplacement: Bool
    UseHeatEffects: Bool
    MinimumFPS: t.Int
    MinimumProcessorFps: t.Int
    SampleCount2D: t.Int
    SampleCount3D: t.Int
    StreamCount: t.Int
    UseAnisotropic: t.Bool
    UseBuildupScaffolds: t.Bool
    UseCloudMap: t.Bool
    UseEmissiveNightMaterials: t.Bool
    UseHighQualityVideo: t.Bool
    UseLightMap: t.Bool
    UsePixelShaders: t.Bool
    UseTreeSway: t.Bool


class AutoResolveReinforcementSchedule(IniObject):
    key = "autoresolvereinforcementschedules"

    numbered_slots = True  # `1 = Command_X` ... slots
    EachRemaining: Float


class GameData(IniObject):
    key = "gamedatas"

    Wireframe: Bool
    StateMachineDebug: Bool
    UseCameraConstraints: Bool
    ShroudOn: Bool
    FogOfWarOn: Bool
    ShowCollisionExtents: Bool
    VTune: Bool

    DebugProjectileTileWidth: Int
    DebugProjectileTileDuration: Int
    DebugProjectileTileColor: RGBA
    DebugAerialTileWidth: Int
    DebugAerialTileDuration: Int
    DebugAerialTileColor: RGBA
    DebugVisibilityTileCount: Int
    DebugVisibilityTileWidth: Float
    DebugVisibilityTileDuration: Int
    DebugVisibilityTileTargettableColor: RGBA
    DebugVisibilityTileDeshroudColor: RGBA
    DebugVisibilityTileGapColor: RGBA
    DebugThreatMapTileDuration: Int
    MaxDebugThreatMapValue: Int
    DebugCashValueMapTileDuration: Int
    MaxDebugCashValueMapValue: Int
    AdjustCliffTextures: t.Bool
    AdvancedTutorialLoadScreenMusicTrack: t.Opaque
    AdvancedTutorialLoadScreenStillImage: t.Opaque
    AdvancedTutorialMap: t.Opaque
    AdvancedTutorialMillisecondsAfterStartToStartFadeUp: t.Int
    AdvancedTutorialObjective: t.Label
    AllowTreeFading: t.Bool
    AllowedHeightVariationForBuilding: t.Float
    AmbientStreamsOn: t.Bool
    AmmoPipScaleFactor: t.Float
    AmmoPipScreenOffset: t.Coords
    AmmoPipWorldOffset: t.Coords
    AnimationSharingCap: t.Int
    AnimationSharingDrasticThreshold: t.Float
    AnimationSharingFrameTolerance: t.Int
    AnimationSharingSpeedTolerance: t.Float
    AnimationSharingWorryThreshold: t.Float
    AnisotropicTerrainTex: t.Bool
    AttributeModifierArmorMaxBonus: t.Float
    AudioOn: t.Bool
    AutoAflameParticleMax: t.Int
    AutoAflameParticlePrefix: t.String
    AutoAflameParticleSystem: t.Opaque
    AutoFireParticleLargeMax: t.Int
    AutoFireParticleLargePrefix: t.String
    AutoFireParticleLargeSystem: t.Opaque
    AutoFireParticleMediumMax: t.Int
    AutoFireParticleMediumPrefix: t.String
    AutoFireParticleMediumSystem: t.Opaque
    AutoFireParticleSmallMax: t.Int
    AutoFireParticleSmallPrefix: t.String
    AutoFireParticleSmallSystem: t.Opaque
    AutoSmokeParticleLargeMax: t.Int
    AutoSmokeParticleLargePrefix: t.String
    AutoSmokeParticleLargeSystem: t.Opaque
    AutoSmokeParticleMediumMax: t.Int
    AutoSmokeParticleMediumPrefix: t.String
    AutoSmokeParticleMediumSystem: t.Opaque
    AutoSmokeParticleSmallMax: t.Int
    AutoSmokeParticleSmallPrefix: t.String
    AutoSmokeParticleSmallSystem: t.Opaque
    BaseRegenDelay: t.Opaque
    BaseRegenHealthPercentPerSecond: t.Float
    BasicTutorialLoadScreenMusicTrack: t.Opaque
    BasicTutorialLoadScreenStillImage: t.Opaque
    BasicTutorialMap: t.Opaque
    BasicTutorialMillisecondsAfterStartToStartFadeUp: t.Int
    BasicTutorialObjective: t.Label
    BilinearTerrainTex: t.Bool
    BuildSpeed: t.Float
    BuilderFadeInTime: t.Int
    BuilderFadeOutTime: t.Int
    BuilderMoveFromNewStructureDistance: t.Int
    CameraAdjustSpeed: t.Float
    CameraAudibleRadius: t.Int
    CameraHeight: t.Float
    CameraLockHeightDelta: t.Float
    CameraPitch: t.Float
    CameraTerrainSampleRadiusForHeight: t.Float
    CameraYaw: t.Float
    CamouflageDetectorObjectFilter: t.ObjectFilter
    ChipsetType: t.Int
    ClearAlpha: t.Int
    CommandCenterHealAmount: t.Float
    CommandCenterHealRange: t.Float
    ContainerPipScaleFactor: t.Float
    ContainerPipScreenOffset: t.Coords
    ContainerPipWorldOffset: t.Coords
    DamageRadiusMinimumForSplash: t.Float
    DebugAI: t.Bool
    DebugAIObstacles: t.Bool
    DefaultCameraMaxHeight: t.Float
    DefaultCameraMinHeight: t.Float
    DefaultCameraPitchAngle: t.Float
    DefaultCameraScrollSpeedScalar: t.Float
    DefaultCameraYawAngle: t.Float
    DefaultEngagedStateTimeout: t.Int
    DefaultMaxDistanceForEngaged: t.Int
    DefaultOcclusionDelay: t.Int
    DefaultStartingCash: t.Int
    DefaultStructureRepairBuffFxList: t.Opaque
    DefaultStructureRubbleHeight: t.Float
    DefaultUnitHealingBuffFxList: t.Opaque
    DefaultVoiceAttackChargeTimeout: t.Int
    DisablePixelShader: t.Bool
    DownwindAngle: t.Float
    DrawEntireTerrain: t.Bool
    DrawSkyBox: t.Bool
    ElvenWoodColor: t.RGB
    EnableHouseColor: t.Bool
    EnforceMaxCameraHeight: t.Bool
    EvilCommandPointLimit: t.Int
    EvilCommandPoints: t.Opaque
    EvilCommandPointsAI: t.Opaque
    EvilCommandPointsBonus: t.Int
    EvilCommandPointsMP2: t.Opaque
    EvilCommandPointsMP3: t.Opaque
    EvilCommandPointsMP4: t.Opaque
    EvilCommandPointsMP5: t.Opaque
    EvilCommandPointsMP56: t.Opaque
    EvilCommandPointsMP6: t.Opaque
    EvilCommandPointsMP7: t.Opaque
    EvilCommandPointsMP78: t.Opaque
    EvilCommandPointsMP8: t.Opaque
    FogAlpha: t.Int
    ForceModelsToFollowTimeOfDay: t.Bool
    ForceModelsToFollowWeather: t.Bool
    FramesPerSecondLimit: t.Int
    GarrisonedRangeMultiplier: t.Float
    GenericDamageFieldName: t.Opaque
    GenericDamageWarningName: t.Opaque
    GetHealedAnimationName: t.Opaque
    GetHealedAnimationTime: t.Float
    GetHealedAnimationZRise: t.Float
    GoodCommandPointLimit: t.Int
    GoodCommandPoints: t.Opaque
    GoodCommandPointsAI: t.Opaque
    GoodCommandPointsBonus: t.Int
    GoodCommandPointsMP2: t.Opaque
    GoodCommandPointsMP3: t.Opaque
    GoodCommandPointsMP4: t.Opaque
    GoodCommandPointsMP5: t.Opaque
    GoodCommandPointsMP56: t.Opaque
    GoodCommandPointsMP6: t.Opaque
    GoodCommandPointsMP7: t.Opaque
    GoodCommandPointsMP78: t.Opaque
    GoodCommandPointsMP8: t.Opaque
    Gravity: t.Float
    GroundStiffness: t.Float
    GroupMoveClickToGatherAreaFactor: t.Float
    GroupSelectMinSelectSize: t.Int
    GroupSelectVolumeBase: t.Float
    GroupSelectVolumeIncrement: t.Float
    HandicapBuildSpeed10: t.Float
    HandicapBuildSpeed100: t.Float
    HandicapBuildSpeed15: t.Float
    HandicapBuildSpeed20: t.Float
    HandicapBuildSpeed25: t.Float
    HandicapBuildSpeed30: t.Float
    HandicapBuildSpeed35: t.Float
    HandicapBuildSpeed40: t.Float
    HandicapBuildSpeed45: t.Float
    HandicapBuildSpeed5: t.Float
    HandicapBuildSpeed50: t.Float
    HandicapBuildSpeed55: t.Float
    HandicapBuildSpeed60: t.Float
    HandicapBuildSpeed65: t.Float
    HandicapBuildSpeed70: t.Float
    HandicapBuildSpeed75: t.Float
    HandicapBuildSpeed80: t.Float
    HandicapBuildSpeed85: t.Float
    HandicapBuildSpeed90: t.Float
    HandicapBuildSpeed95: t.Float
    HealthBonus_Elite: t.Float
    HealthBonus_Heroic: t.Float
    HealthBonus_Veteran: t.Float
    HideGarrisonFlags: t.Bool
    HistoricDamageLimit: t.Int
    HorizontalScrollSpeedFactor: t.Float
    HumanSoloPlayerHealthBonus_Easy: t.Float
    HumanSoloPlayerHealthBonus_Hard: t.Float
    HumanSoloPlayerHealthBonus_Normal: t.Float
    InfantryLightAfternoonScale: t.Float
    InfantryLightEveningScale: t.Float
    InfantryLightMorningScale: t.Float
    InfantryLightNightScale: t.Float
    InitialMaxRingLevel: t.Int
    InvisibilityOpacityCycleFrames: t.Int
    InvisibilityOpacityMax: t.Float
    InvisibilityOpacityMin: t.Float
    KeyboardCameraRotateSpeed: t.Float
    KeyboardScrollSpeedFactor: t.Float
    LevelGainAnimationName: t.Opaque
    LevelGainAnimationTime: t.Float
    LevelGainAnimationZRise: t.Float
    LowEnergyPenaltyModifier: t.Float
    MakeTrackMarks: t.Bool
    MapName: t.String
    MaxCameraHeight: t.Float
    MaxCastleRadius: t.Int
    MaxCellsAdjustDestination: t.Int
    MaxCellsAdjustHordeMeleeDestination: t.Int
    MaxCellsAdjustTargetDestination: t.Int
    MaxCellsAdjustToMeleeDestination: t.Int
    MaxCellsAdjustToNearestGroundCell: t.Int
    MaxCellsAdjustToNearestValidCell: t.Int
    MaxCellsAdjustToPossibleDestination: t.Int
    MaxCellsFindAttackPath: t.Int
    MaxCellsFindAttackPathSideways: t.Int
    MaxCellsFindMeleeEngagementLocation: t.Int
    MaxCellsFindPathLimit: t.Int
    MaxCellsPatchPath: t.Int
    MaxCellsToExamineTowardsGoal: t.Int
    MaxFieldParticleCount: t.Int
    MaxLineBuildObjects: t.Int
    MaxLowEnergyProductionSpeed: t.Float
    MaxParticleCount: t.Int
    MaxPathfindCellsPerFrame: t.Int
    MaxRoadIndex: t.Int
    MaxRoadSegments: t.Int
    MaxRoadTypes: t.Int
    MaxRoadVertex: t.Int
    MaxShakeIntensity: t.Float
    MaxShakeRange: t.Float
    MaxShellScreens: t.Int
    MaxTerrainTracks: t.Int
    MaxTunnelCapacity: t.Int
    MaxUnitSelectSounds: t.Int
    MinCameraHeight: t.Float
    MinDistFromEdgeOfMapForBuild: t.Float
    MinLowEnergyProductionSpeed: t.Float
    MoveHintName: t.String
    MovementPenaltyDamageState: e.BodyDamageType
    MultiPassTerrain: t.Bool
    MultiPlayBuildingSpeedMult: t.Opaque
    MultiPlayBuildingXPMult: t.Opaque
    MultiPlayMoneyMult: t.Opaque
    MultiPlayUnitSpeedMult: t.Opaque
    MultiPlayUnitXPMult: t.Opaque
    MultipleFactory: t.Float
    MusicOn: t.Bool
    NetworkCushionHistoryLength: t.Int
    NetworkDisconnectScreenNotifyTime: t.Int
    NetworkDisconnectTime: t.Int
    NetworkFPSHistoryLength: t.Int
    NetworkKeepAliveDelay: t.Int
    NetworkLatencyHistoryLength: t.Int
    NetworkPlayerTimeoutTime: t.Int
    NetworkRunAheadMetricsTime: t.Int
    NetworkRunAheadSlack: t.Int
    NumMinutesBeforePlayersCanTransferMoney: t.Int
    ObjectsThatScore: t.ObjectFilter
    OccludedColorLuminanceScale: t.Float
    OpacityOfSimpleMergeDecals: t.Float
    ParticleCursorAlpha: t.Int
    ParticleCursorAnim2DTemplateName: t.Opaque
    ParticleCursorBurstCount: t.Int
    ParticleCursorBurstFactor: t.RandomVariable
    ParticleCursorBurstFrequency: t.Int
    ParticleCursorDriftVelX: t.RandomVariable
    ParticleCursorDriftVelY: t.RandomVariable
    ParticleCursorOffset: t.Coords
    ParticleCursorParticleLife: t.RandomVariable
    ParticleCursorParticleSize: t.RandomVariable
    ParticleCursorPerFrameSize: t.Bool
    ParticleCursorStopBurstFactor: t.Float
    ParticleCursorSystemLife: t.RandomVariable
    ParticleCursorVelocityDrag: t.RandomVariable
    ParticleScale: t.Float
    PartitionCellSize: t.Float
    PlayIntro: t.Bool
    PowerLimit: t.Int
    ProgressMovieOffset: t.Coords
    ProgressMovieSize: t.Coords
    RefundPercent: t.Float
    ReinvisibityDelay: t.Int
    ResourceBonusMultiplier: t.Float
    ResourceMultiplierLimit: t.Float
    RightMouseAlwaysScrolls: t.Bool
    ScoreKeeper_HeroesVettedMultiplier: t.Int
    ScoreKeeper_NormalVictoryRequiredObjectivesPercentage: t.Int
    ScoreKeeper_NormalVictoryRequiredScore: t.Int
    ScoreKeeper_ObjectivesCompletedMultiplier: t.Int
    ScoreKeeper_PlayerEliminatedMultiplier: t.Float
    ScoreKeeper_PowerPointsMultiplier: t.Int
    ScoreKeeper_RegionCommandPointsMultiplier: t.Int
    ScoreKeeper_RegionPowerPointsMultiplier: t.Int
    ScoreKeeper_RegionResourcesMultiplier: t.Int
    ScoreKeeper_SkillPointsMultiplier: t.Float
    ScoreKeeper_StructuresBuiltMultiplier: t.Int
    ScoreKeeper_StructuresDestroyedMultiplier: t.Int
    ScoreKeeper_SuppliesCollectedMultiplier: t.Float
    ScoreKeeper_TimeTakenMaximumScore: t.Int
    ScoreKeeper_TimeTakenMinimumScore: t.Int
    ScoreKeeper_TimeTakenMultiplier: t.Int
    ScoreKeeper_TotalVictoryRequiredScore: t.Int
    ScoreKeeper_UnitsBuiltMultiplier: t.Int
    ScoreKeeper_UnitsDestroyedMultiplier: t.Int
    ScoreKeeper_UnitsVettedMultiplier: t.Int
    ScreenEdgeScrollRampTime: t.Float
    ScreenEdgeScrollSpeedFactor: t.Float
    ScrollAmountCutoff: t.Float
    SelectionFlashHouseColor: t.Bool
    SelectionFlashSaturationFactor: t.Float
    SellPercentage: t.Float
    ShakeCineExtremeIntensity: t.Float
    ShakeCineInsaneIntensity: t.Float
    ShakeNormalIntensity: t.Float
    ShakeSevereIntensity: t.Float
    ShakeStrongIntensity: t.Float
    ShakeSubtleIntensity: t.Float
    ShellMapName: t.String
    ShellMapOn: t.Bool
    ShowObjectHealth: t.Bool
    ShowProps: t.Bool
    ShowSelectedUnitMarker: t.Bool
    ShroudAlpha: t.Int
    ShroudColor: t.RGB
    SkipMapUnroll: t.Bool
    SkyBoxPositionZ: t.Float
    SkyBoxScale: t.Float
    Sounds3DOn: t.Bool
    SoundsOn: t.Bool
    SpecialPowerViewObject: t.Opaque
    SpeechOn: t.Bool
    StandardMinefieldDensity: t.Float
    StandardMinefieldDistance: t.Float
    StandardPublicBone: t.List[t.String]
    StealthFriendlyOpacity: t.Float
    StretchTerrain: t.Bool
    StructureStiffness: t.Float
    SupplyBoxesPerTree: t.Int
    SupplyBuildBorder: t.Float
    TaintAlpha: t.Int
    TaintColor: t.RGB
    TaintOn: t.Bool
    TerrainHeightAtEdgeOfMap: t.Float
    TerrainLOD: e.TerrainLod
    TerrainLODTargetTimeMS: t.Int
    TerrainLightingAfternoonAmbient: t.RGB
    TerrainLightingAfternoonAmbient2: t.RGB
    TerrainLightingAfternoonAmbient3: t.RGB
    TerrainLightingAfternoonDiffuse: t.RGB
    TerrainLightingAfternoonDiffuse2: t.RGB
    TerrainLightingAfternoonDiffuse3: t.RGB
    TerrainLightingAfternoonLightPos: t.Coords
    TerrainLightingAfternoonLightPos2: t.Coords
    TerrainLightingAfternoonLightPos3: t.Coords
    TerrainLightingEveningAmbient: t.RGB
    TerrainLightingEveningDiffuse: t.RGB
    TerrainLightingEveningLightPos: t.Coords
    TerrainLightingMorningAmbient: t.RGB
    TerrainLightingMorningDiffuse: t.RGB
    TerrainLightingMorningLightPos: t.Coords
    TerrainLightingNightAmbient: t.RGB
    TerrainLightingNightDiffuse: t.RGB
    TerrainLightingNightLightPos: t.Coords
    TerrainObjectsLightingAfternoonAmbient: t.RGB
    TerrainObjectsLightingAfternoonAmbient2: t.RGB
    TerrainObjectsLightingAfternoonAmbient3: t.RGB
    TerrainObjectsLightingAfternoonDiffuse: t.RGB
    TerrainObjectsLightingAfternoonDiffuse2: t.RGB
    TerrainObjectsLightingAfternoonDiffuse3: t.RGB
    TerrainObjectsLightingAfternoonLightPos: t.Coords
    TerrainObjectsLightingAfternoonLightPos2: t.Coords
    TerrainObjectsLightingAfternoonLightPos3: t.Coords
    TerrainObjectsLightingEveningAmbient: t.RGB
    TerrainObjectsLightingEveningDiffuse: t.RGB
    TerrainObjectsLightingEveningLightPos: t.Coords
    TerrainObjectsLightingMorningAmbient: t.RGB
    TerrainObjectsLightingMorningDiffuse: t.RGB
    TerrainObjectsLightingMorningLightPos: t.Coords
    TerrainObjectsLightingNightAmbient: t.RGB
    TerrainObjectsLightingNightDiffuse: t.RGB
    TerrainObjectsLightingNightLightPos: t.Coords
    TerrainResourceCellSize: t.Float
    TextureReductionFactor: t.Int
    TimeAfterDamageUntilRepairAllowed: t.Float
    TimeOfDay: e.TimeOfDay
    TintUnitIfPathingForMoreThan: t.Int
    TreeFadeObjectFilter: t.ObjectFilter
    TrilinearTerrainTex: t.Bool
    TutorialLoadMovie: t.Opaque
    TutorialMap: t.Opaque
    TutorialObjective: t.Label
    UnitDamagedThreshold: t.Float
    UnitReallyDamagedThreshold: t.Float
    UnlookPersistDuration: t.Int
    Use3WayTerrainBlends: t.Int
    UseBehindBuildingMarker: t.Bool
    UseCameraInReplay: t.Bool
    UseCloudMap: t.Bool
    UseCloudPlane: t.Bool
    UseFPSLimit: t.Bool
    UseHalfHeightMap: t.Bool
    UseHelpTextSystem: t.Bool
    UseHighQualityVideo: t.Bool
    UseLightMap: t.Bool
    UseShadowDecals: t.Bool
    UseShadowMapping: t.Bool
    UseShadowVolumes: t.Bool
    UseSimpleHordeDecals: t.Bool
    UseSimpleMergeDecals: t.Bool
    UseTrees: t.Bool
    UseWaterPlane: t.Bool
    UserDataLeafName: t.String
    ValuePerSupplyBox: t.Int
    VertexWaterAngle1: t.Int
    VertexWaterAngle2: t.Int
    VertexWaterAngle3: t.Int
    VertexWaterAngle4: t.Int
    VertexWaterAttenuationA1: t.Float
    VertexWaterAttenuationA2: t.Float
    VertexWaterAttenuationA3: t.Float
    VertexWaterAttenuationA4: t.Float
    VertexWaterAttenuationB1: t.Float
    VertexWaterAttenuationB2: t.Float
    VertexWaterAttenuationB3: t.Float
    VertexWaterAttenuationB4: t.Float
    VertexWaterAttenuationC1: t.Float
    VertexWaterAttenuationC2: t.Float
    VertexWaterAttenuationC3: t.Float
    VertexWaterAttenuationC4: t.Float
    VertexWaterAttenuationRange1: t.Float
    VertexWaterAttenuationRange2: t.Float
    VertexWaterAttenuationRange3: t.Float
    VertexWaterAttenuationRange4: t.Float
    VertexWaterAvailableMaps1: t.String
    VertexWaterAvailableMaps2: t.String
    VertexWaterAvailableMaps3: t.String
    VertexWaterAvailableMaps4: t.String
    VertexWaterGridSize1: t.Float
    VertexWaterGridSize2: t.Float
    VertexWaterGridSize3: t.Float
    VertexWaterGridSize4: t.Float
    VertexWaterHeightClampHi1: t.Float
    VertexWaterHeightClampHi2: t.Float
    VertexWaterHeightClampHi3: t.Float
    VertexWaterHeightClampHi4: t.Float
    VertexWaterHeightClampLow1: t.Float
    VertexWaterHeightClampLow2: t.Float
    VertexWaterHeightClampLow3: t.Float
    VertexWaterHeightClampLow4: t.Float
    VertexWaterXGridCells1: t.Int
    VertexWaterXGridCells2: t.Int
    VertexWaterXGridCells3: t.Int
    VertexWaterXGridCells4: t.Int
    VertexWaterXPosition1: t.Float
    VertexWaterXPosition2: t.Float
    VertexWaterXPosition3: t.Float
    VertexWaterXPosition4: t.Float
    VertexWaterYGridCells1: t.Int
    VertexWaterYGridCells2: t.Int
    VertexWaterYGridCells3: t.Int
    VertexWaterYGridCells4: t.Int
    VertexWaterYPosition1: t.Float
    VertexWaterYPosition2: t.Float
    VertexWaterYPosition3: t.Float
    VertexWaterYPosition4: t.Float
    VertexWaterZPosition1: t.Float
    VertexWaterZPosition2: t.Float
    VertexWaterZPosition3: t.Float
    VertexWaterZPosition4: t.Float
    VerticalScrollSpeedFactor: t.Float
    VeterancyPipDrawObjectFilter: t.ObjectFilter
    VictoryConditionStructureObjectFilter: t.ObjectFilter
    VictoryConditionUnitObjectFilter: t.ObjectFilter
    VideoOn: t.Bool
    WaterExtentX: t.Float
    WaterExtentY: t.Float
    WaterPositionX: t.Float
    WaterPositionY: t.Float
    WaterPositionZ: t.Float
    WaterType: t.Int
    WeaponBonus: t.List[
        t.Tuple[t.Untyped, t.Untyped, t.Untyped]
    ]  # `<condition> <field> <value>`, one per repeat
    Weather: e.MapWeatherType


class LivingWorldRegionEffects(IniObject):
    key = "livingworldregioneffects"

    RegionObject: Opaque
    NeutralRegionColor: RGBA
    RegionBorderColor: RGBA
    ShellStartPositionColor: RGBA

    nested_attributes = {
        name: [name]
        for name in (
            "BordersEffect",
            "FilledOwnershipEffect",
            "MouseoverEffectFlareup",
            "HomeRegionHighlight",
            "RegionSelectionEffect",
            "UnifiedEffect",
        )
    }


class WaterSet(IniObject):
    key = "watersets"

    SkyTexture: t.TextureFile
    WaterTexture: t.TextureFile
    Vertex00Color: RGBA
    Vertex10Color: RGBA
    Vertex01Color: RGBA
    Vertex11Color: RGBA
    DiffuseColor: RGBA
    TransparentDiffuseColor: RGBA
    UScrollPerMS: Float
    VScrollPerMS: Float
    SkyTexelsPerUnit: Float
    WaterRepeatCount: Int


class AIData(IniObject):
    key = "aidatas"

    nested_attributes = {"SideInfo": ["SideInfo"]}

    UseLowLODTrees: Bool
    LowLodTreeScale: Float
    LowLodTreeName: Opaque
    LowLodTreeNameNoGrab: Opaque
    LowLodTreeNameNoHarvest: Opaque

    StructureSeconds: Float
    TeamSeconds: Float
    Wealthy: Float
    Poor: Float
    StructuresWealthyRate: Float
    StructuresPoorRate: Float
    TeamsWealthyRate: Float
    TeamsPoorRate: Float
    TeamResourcesToStart: Float

    GuardInnerModifierAI: Float
    GuardOuterModifierAI: Float
    GuardInnerModifierHuman: Float
    GuardOuterModifierHuman: Float
    GuardChaseUnitsDuration: Float
    GuardEnemyScanRate: Float
    GuardEnemyReturnScanRate: Float

    AlertRangeModifier: Float
    AggressiveRangeModifier: Float
    AttackPriorityDistanceModifier: Float
    MaxRecruitRadius: Float
    ForceIdleMSEC: Float
    ForceSkirmishAI: Bool
    RotateSkirmishBases: Bool
    AttackUsesLineOfSight: Bool
    AttackIgnoreInsignificantBuildings: Bool
    AICrushesInfantry: Bool
    MaxRetaliateDistance: Float
    RetaliateFriendsRadius: Float
    ChaseFromBehindLimit: Float

    EnableRepulsors: Bool
    RepulsedDistance: Float
    WallHeight: Float

    SkirmishGroupFudgeDistance: Float
    InfantryPathfindDiameter: Float
    VehiclePathfindDiameter: Float
    SupplyCenterSafeRadius: Float
    RebuildDelayTimeSeconds: Float
    AIDozerBoredRadiusModifier: Float
    MeleeApproachDist: Float
    MeleeApproachTolerance: Float
    WadeWaterDepth: Float
    DeepWaterDepth: Float
    NarrowPassageScale: Float

    MinDistanceForGroup: Float
    FormationEnemyDistance: Float
    FormationColumnWidth: Float
    FormationRowDepth: Float
    FormationSquadSpacing: Float
    FormationColumns: Float
    UseFormations: Bool
    WaitForOthers: Bool
    HordesWaitForHordes: Bool
    AttackMoveUsesFormations: Bool

    ForceHordesToLowLOD: Bool
    AllowForestFires: Bool
    CastleSiegeStandBackDistance: Float

    BuildPhase1_PerSecondPriorityModifier: Float
    BuildPhase2_PerSecondPriorityModifier: Float
    BuildPhase3_PerSecondPriorityModifier: Float
    BuildPhaseN_PerSecondPriorityModifier: Float
    AltCameraPitchOverride: t.Float
    AltCameraZoomOverride: t.Float
    AttackPriority: t.Opaque
    DistanceRequiresGroup: t.Float
    MaxRetaliationDistance: t.Float
    MeleeAcquireLimitDist: t.Float
    MinClumpDensity: t.Int
    MinFlightHeight: t.Int
    MinInfantryForGroup: t.Int
    MinVehiclesForGroup: t.Int
    RetaliationFriendsRadius: t.Float
    SkirmishBaseDefenseExtraDistance: t.Float
    SkirmishBuildList: t.Opaque


class FontDefaultSettings(IniObject):
    key = "fontdefaultsettings"

    Antialiased: Bool


class MultiplayerSettings(IniObject):
    key = "multiplayersettings"

    InitialCreditsVeryLow: Int
    InitialCreditsLow: Int
    InitialCreditsMedium: Int
    InitialCreditsHigh: Int
    InitialCreditsVeryHigh: Int
    StartCountdownTimer: Int
    MaxBeaconsPerPlayer: Int
    UseShroud: Bool
    ShowRandomPlayerTemplate: Bool
    ShowRandomStartPos: Bool
    ShowRandomColor: Bool
    InitialCreditsMax: t.Int
    InitialCreditsMin: t.Int


class VictorySystemData(IniObject):
    key = "victorysystemdatas"

    CellSize: Float
    ScalePerLogicFrame: Float
    SubtractPerLogicFrame: Float
    CellBonusRadius: Float


class ArmySummaryDescription(IniObject):
    key = "armysummarydescriptions"

    HeroFilter: ObjectFilter

    nested_attributes = {"UnitCategory": ["UnitCategory"]}


class AudioLOD(IniObject):
    key = "audiolods"

    AllowDolby: Bool
    AllowReverb: Bool
    MaximumAmbientStreams: Int


class AwardSystem(IniObject):
    key = "awardsystems"

    nested_attributes = {"ThingStat": ["ThingStat"], "ObjectAward": ["ObjectAward"]}


class Bridge(IniObject):
    key = "bridges"

    BridgeScale: Float
    RadarColor: RGBA
    BridgeModelName: t.ModelFile
    Texture: t.TextureFile
    BridgeModelNameDamaged: t.ModelFile
    TextureDamaged: t.TextureFile
    BridgeModelNameReallyDamaged: t.ModelFile
    TextureReallyDamaged: t.TextureFile
    BridgeModelNameBroken: t.ModelFile
    TextureBroken: t.TextureFile
    TowerObjectNameFromLeft: t.ObjectRef
    TowerObjectNameFromRight: t.ObjectRef
    TowerObjectNameToLeft: t.ObjectRef
    TowerObjectNameToRight: t.ObjectRef
    ScaffoldObjectName: Opaque
    ScaffoldSupportObjectName: Opaque
    DamagedToSound: t.Opaque
    NumFXPerType: t.Int
    RepairedToSound: t.Opaque
    TransitionEffectsHeight: t.Float
    TransitionToFX: t.FXList
    TransitionToOCL: t.Opaque


class CommandMap(IniObject):
    key = "commandmaps"

    Key: Untyped
    Transition: Untyped
    Modifiers: Untyped
    UseableIn: Untyped
    Category: Untyped
    Description: t.Label
    DisplayName: t.Label


class CreateAHeroSystem(IniObject):
    key = "createaherosystems"

    nested_attributes = {
        "CreateAHeroBling": ["CreateAHeroBling"],
        "CreateAHeroBlingBinder": ["CreateAHeroBlingBinder"],
    }

    CreateAHeroMapModeUpgradeName: "Upgrade"
    CreateAHeroGameModeUpgradeName: "Upgrade"
    CanBuildCreateAHeroUpgradeName: "Upgrade"
    CommandSetTemplate: Opaque
    WeaponGroupName: t.String

    StratigicDefeatStatName: t.String
    StratigicVictoryStatName: t.String
    StratigicMPDefeatStatName: t.String
    StratigicMPVictoryStatName: t.String
    SkirmishDefeatStatName: t.String
    SkirmishVictoryStatName: t.String
    OpenPlayDefeatStatName: t.String
    OpenPlayVictoryStatName: t.String
    StratigicCampainVictoryStatName: t.String

    SelectedCheerAninName: t.String
    ExamineWeaponAninName: t.String
    ExamineSelfAninName: t.String
    SpecialAnimPercentChance: Float
    CreateAHeroClass: t.Opaque
    ExamineAnimTweakValue: t.Int
    HeroRevivalDiscount: t.Float
    SpecialPowerDiscountPerLevel: t.Float


class Credits(IniObject):
    key = "credits"

    ScrollRate: Int
    ScrollRateEveryFrames: Int
    ScrollDown: Bool
    TitleColor: RGBA
    MinorTitleColor: RGBA
    NormalColor: RGBA
    Style: List[Untyped]
    Text: List[Untyped]
    Blank: List[Opaque]


class FormationAssistant(IniObject):
    key = "formationassistants"

    RowPadding: Float
    ColumnPadding: Float
    ActivationDragDistance: Float
    FacingArrowHeadTemplate: Opaque
    FacingArrowBodyTemplate: Opaque
    FacingArrowBaseTemplate: Opaque
    ActivationTime: t.Float
    DefaultPreviewObject: t.Opaque
    ValidObjectFilter: t.ObjectFilter

    nested_attributes = {
        "FormationTemplate": ["FormationTemplate"],
        "UnitDefinition": ["UnitDefinition"],
        "FormationSelection": ["FormationSelection"],
    }


class InGameNotificationBox(IniObject):
    key = "ingamenotificationboxs"

    DefaultMessageFont: Untyped
    DefaultMessageColor: RGBA
    DefaultOpenAudio: Sound
    Font: t.Opaque

    nested_attributes = {"NotificationType": ["NotificationType"]}


class InGameUI(IniObject):
    key = "ingameuis"

    nested_attributes = {"RadiusCursorTemplate": ["RadiusCursorTemplate"]}

    MaxSelectionSize: Int

    MessageColor1: RGBA
    MessageColor2: RGBA
    MessagePosition: Coords
    MessagePositionLW: Coords
    MessageFont: Untyped
    MessagePointSize: Int
    MessageDelayMS: Int

    MilitaryCaptionColor: RGBA
    MilitaryCaptionPosition: Coords
    MilitaryCaptionCentered: Bool
    MilitaryCaptionTitleFont: Untyped
    MilitaryCaptionTitlePointSize: Int
    MilitaryCaptionTitleBold: Bool
    MilitaryCaptionFont: Untyped
    MilitaryCaptionPointSize: Int
    MilitaryCaptionBold: Bool
    MilitaryCaptionDelayMS: Int

    DrawableCaptionFont: Untyped
    DrawableCaptionPointSize: Int
    DrawableCaptionBold: Bool
    DrawableCaptionColor: RGBA

    SuperweaponCountdownPosition: Coords
    SuperweaponCountdownFlashDuration: Int
    SuperweaponCountdownFlashColor: RGBA
    SuperweaponCountdownNormalFont: Untyped
    SuperweaponCountdownNormalPointSize: Int
    SuperweaponCountdownNormalBold: Bool
    SuperweaponCountdownReadyFont: Untyped
    SuperweaponCountdownReadyPointSize: Int
    SuperweaponCountdownReadyBold: Bool

    NamedTimerCountdownPosition: Coords
    NamedTimerCountdownFlashDuration: Int
    NamedTimerCountdownFlashColor: RGBA
    NamedTimerCountdownNormalFont: Untyped
    NamedTimerCountdownNormalPointSize: Int
    NamedTimerCountdownNormalBold: Bool
    NamedTimerCountdownNormalColor: RGBA
    NamedTimerCountdownReadyFont: Untyped
    NamedTimerCountdownReadyPointSize: Int
    NamedTimerCountdownReadyBold: Bool
    NamedTimerCountdownReadyColor: RGBA

    HelpBoxNameFont: Untyped
    HelpBoxNamePointSize: Int
    HelpBoxNameBold: Bool
    HelpBoxNameColor: RGBA
    HelpBoxCostFont: Untyped
    HelpBoxCostPointSize: Int
    HelpBoxCostBold: Bool
    HelpBoxCostColor: RGBA
    HelpBoxShortcutFont: Untyped
    HelpBoxShortcutPointSize: Int
    HelpBoxShortcutBold: Bool
    HelpBoxShortcutColor: RGBA
    HelpBoxDescriptionFont: Untyped
    HelpBoxDescriptionPointSize: Int
    HelpBoxDescriptionBold: Bool
    HelpBoxDescriptionColor: RGBA

    FloatingTextTimeOut: Int
    FloatingTextMoveUpSpeed: Int
    FloatingTextVanishRate: Int

    DrawRMBScrollAnchor: Bool
    MoveRMBScrollAnchor: Bool
    UnitHelpTextDelay: Float
    SelectNearestBuilderCycleTimeOut: Int

    TerrainResourceClaimDecal: Opaque
    PlaceTerrainResourceClaimantDecal: Opaque
    PlaceTerrainResourceClaimantFont: Untyped
    PlaceTerrainResourceClaimantFontColor: RGBA

    HeroInitialSpawnNotificationMessage: t.Label
    HeroInitialSpawnNotificationTimeout: Float
    HeroRespawnNotificationMessage: t.Label
    HeroRespawnNotificationTimeout: Float
    HeroDeathNotificationMessage: t.Label
    HeroDeathNotificationTimeout: Float
    HeroEarnedAwardNotificationMessage: t.Label
    HeroEarnedAwardNotificationTimeout: Float

    RadiusCursorUseWeaponScatterRadius: Opaque
    A10StrikeRadiusCursor: t.Opaque
    AmbulanceRadiusCursor: t.Opaque
    AmbushRadiusCursor: t.Opaque
    AnthraxBombRadiusCursor: t.Opaque
    ArcheryTrainingRadiusCursor: t.Opaque
    ArmyOfTheDeadRadiusCursor: t.Opaque
    ArrowStormRadiusCursor: t.Opaque
    ArtilleryRadiusCursor: t.Opaque
    AthelasRadiusCursor: t.Opaque
    AttackContinueAreaRadiusCursor: t.Opaque
    AttackDamageAreaRadiusCursor: t.Opaque
    AttackScatterAreaRadiusCursor: t.Opaque
    CaptainOfGondorRadiusCursor: t.Opaque
    CarpetBombRadiusCursor: t.Opaque
    ClearMinesRadiusCursor: t.Opaque
    ClusterMinesRadiusCursor: t.Opaque
    DaisyCutterRadiusCursor: t.Opaque
    DevastationRadiusCursor: t.Opaque
    DominateRadiusCursor: t.Opaque
    EMPPulseRadiusCursor: t.Opaque
    EagleAlliesRadiusCursor: t.Opaque
    EagleSwoopRadiusCursor: t.Opaque
    ElvenAlliesRadiusCursor: t.Opaque
    ElvenWoodRadiusCursor: t.Opaque
    EmergencyRepairRadiusCursor: t.Opaque
    EntAlliesRadiusCursor: t.Opaque
    EyeOfSauronRadiusCursor: t.Opaque
    FellBeastSwoopRadiusCursor: t.Opaque
    FireBreathRadiusCursor: t.Opaque
    FrenzyRadiusCursor: t.Opaque
    FriendlySpecialPowerRadiusCursor: t.Opaque
    GuardAreaRadiusCursor: t.Opaque
    HealRadiusCursor: t.Opaque
    HelixNapalmBombRadiusCursor: t.Opaque
    IndustryRadiusCursor: t.Opaque
    KingsFavorRadiusCursor: t.Opaque
    LeapRadiusCursor: t.Opaque
    LightningSwordRadiusCursor: t.Opaque
    MessageBold: t.Bool
    MilitaryCaptionRandomizeTyping: t.Bool
    NapalmStrikeRadiusCursor: t.Opaque
    NuclearMissileRadiusCursor: t.Opaque
    OffensiveSpecialPowerRadiusCursor: t.Opaque
    PalantirVisionRadiusCursor: t.Opaque
    ParadropRadiusCursor: t.Opaque
    ParticleCannonRadiusCursor: t.Opaque
    PopupMessageColor: t.RGBA
    RadarRadiusCursor: t.Opaque
    RohanAlliesRadiusCursor: t.Opaque
    ScudStormRadiusCursor: t.Opaque
    SpectreGunshipRadiusCursor: t.Opaque
    SpeechCraftRadiusCursor: t.Opaque
    SpyDroneRadiusCursor: t.Opaque
    SpySatelliteRadiusCursor: t.Opaque
    SummonBalrogRadiusCursor: t.Opaque
    SummonOathBreakersRadiusCursor: t.Opaque
    SuperweaponScatterAreaRadiusCursor: t.Opaque
    TaintRadiusCursor: t.Opaque
    TrainingRadiusCursor: t.Opaque
    WarChantRadiusCursor: t.Opaque


class LivingWorldAITemplate(IniObject):
    key = "livingworldaitemplates"

    DesiredSoldierRatio: Int
    DesiredArcherRatio: Int
    DesiredPikemenRatio: Int
    DesiredCavalryRatio: Int
    DesiredMonsterRatio: Int
    DesiredHeroRatio: Int
    DesiredFortressRatio: Int

    BuildingScoreArmory: Int
    BuildingScoreBarracks: Int
    BuildingScoreCastle: Int
    BuildingScoreFarm: Int
    BonusPreferenceResource: Int
    BonusPreferenceArmy: Int
    BonusPreferenceLegendary: Int
    BonusPreferenceAttack: Int
    BonusPreferenceDefense: Int
    BonusPreferenceExperience: Int
    BonusPreferenceTreasury: t.Int
    DesiredSiegeRatio: t.Int
    DesiredSupportRatio: t.Int


class LivingWorldAutoResolveResourceBonus(IniObject):
    key = "livingworldautoresolveresourcebonus"

    Sides: List[t.PlayerTemplateRef]

    nested_attributes = {"Bonus": ["Bonus"]}


class LivingWorldAutoResolveSciencePurchasePointBonus(IniObject):
    key = "livingworldautoresolvesciencepurchasepointbonus"

    Sides: List[t.PlayerTemplateRef]

    nested_attributes = {"Bonus": ["Bonus"]}


class LivingWorldMapInfo(IniObject):
    key = "livingworldmapinfos"

    MapObject: Opaque
    NumWorldTiles: Int
    CloudBorderSubObject: Opaque
    TextLayerSubObject: Opaque
    AddShadowSubObject: Opaque

    Center: Coords
    Extent: Coords
    AptCenter: Coords
    AptZoom: Float
    AptPitch: Float

    CameraBoundX: Float
    CameraBoundY: Float
    ClickScrollThreshold: Float
    MouseWheelZoomPerTick: Float
    MouseWheelZoomDampenFactor: Float
    AutoScrollSpeed: Float
    MaxAutoScrollTime: Float

    NumPointsPerArmyLine: Int
    ArmyLineHeightBias: Float
    ArmyLineWidth: Float
    ArmyLineColorAttacking: RGBA
    ArmyLineColorNeutral: RGBA
    ArmyLineColorAllied: RGBA
    ArmyLineTextureName: t.TextureFile

    Ambient: RGBA
    SunDir: Coords
    SunRGB: RGBA
    Accent1Dir: Coords
    Accent1RGB: RGBA
    Accent2Dir: Coords
    Accent2RGB: RGBA

    MenBanner: Opaque
    ElvesBanner: Opaque
    DwarvesBanner: Opaque
    IsengardBanner: Opaque
    MordorBanner: Opaque
    WildBanner: Opaque
    NeutralBanner: Opaque
    MenAnts: Opaque
    ElvesAnts: Opaque
    DwarvesAnts: Opaque
    IsengardAnts: Opaque
    MordorAnts: Opaque
    WildAnts: Opaque
    NeutralAnts: Opaque

    BannerScaleSpeed: Float
    BannerMaxScale: Float
    BannerTiltAngle: Float
    BannerHeight: Float
    ArmyHeight: Float
    BeaconHeight: Float
    DefaultArmyMoveSpeed: Float
    HeroArmyIconDiameter: Float

    BattleMarker: Opaque
    PalantirMarker: Opaque
    RegionAwardDisputeMarker: Opaque
    BattleMarkerCreatedSound: Sound
    EnterMapSound: Sound

    AnimRays: Opaque
    AnimRaysColor: RGBA
    AnimRaysPartSysOffset: Coords
    AnimRaysColorScale: Float
    AnimRaysEffectShells: Int
    AnimRaysEffectDiameter: Int
    AnimRaysEffectLifetime: Int
    AnimRaysCreateSound: Sound

    AnimCloud: Opaque
    AnimCloudPartSys: Opaque
    NumAnimClouds: Int
    AnimCloudRegionMin: Coords
    AnimCloudRegionMax: Coords
    AnimCloudLifetime: Int
    EmbersPartSys: Opaque
    CloudPos: Coords
    CloudGrowthPos: Coords
    ShadowColor: RGBA

    ArmySelectedFadeInStart: Int
    ArmySelectedFadeInEnd: Int
    ArmySelectedFadeOutStart: Int
    ArmySelectedFadeOutEnd: Int
    ArmyHilightedFadeInTime: Int
    ArmyHilightedFadeOutTime: Int
    AngmarAnts: t.Opaque
    AngmarBanner: t.Opaque
    AnimRaysPartSys: t.Opaque
    ArmyHilightedIconObject: t.Opaque
    ArmySelectedIconObject: t.Opaque
    ArmySoldierLarge: t.Opaque
    ArmySoldierMedium: t.Opaque
    ArmySoldierSmall: t.Opaque
    CloudGrowthRate: t.Int
    CloudGrowthSize: t.Float
    CloudInitialOpacity: t.Float
    CloudInitialSize: t.Float
    EnableMapShadows: t.Bool
    EyeTower: t.Opaque
    GondorAnts: t.Opaque
    GondorBanner: t.Opaque
    MordorCloud: t.Opaque
    RohanAnts: t.Opaque
    RohanBanner: t.Opaque


class MiscEvaData(IniObject):
    key = "miscevadatas"

    EnemySightedMaxVoicePositionScanRange: Int
    EnemyCampDestroyedDamageTimeoutMS: Int
    FriendlyCampDestroyedDamageTimeoutMS: Int
    MaxMillisecondsToKeepJumpToEvents: Int
    MaxMillisecondsBeforeResettingLastJumpTo: Int
    MinDistanceBetweenJumpToEvents: Int


class Mouse(IniObject):
    key = "mouses"

    TooltipFontName: Untyped
    TooltipFontSize: Int
    TooltipFontIsBold: Bool
    TooltipAnimateBackground: Bool
    TooltipFillTime: Int
    TooltipDelayTime: Int
    TooltipTextColor: RGBA
    TooltipHighlightColor: RGBA
    TooltipShadowColor: RGBA
    TooltipBorderColor: RGBA
    TooltipBackgroundColor: RGBA
    TooltipWidth: Int
    UseTooltipAltTextColor: Bool
    UseTooltipAltBackColor: Bool
    AdjustTooltipAltColor: Bool

    OrthoCamera: Bool
    OrthoZoom: Float
    DragTolerance: Int
    DragTolerance3D: Int
    DragToleranceMS: Int


class OnlineChatColors(IniObject):
    key = "onlinechatcolors"

    Default: RGBA
    CurrentRoom: RGBA
    ChatRoom: RGBA
    Game: RGBA
    GameFull: RGBA
    GameCRCMismatch: RGBA
    PlayerNormal: RGBA
    PlayerOwner: RGBA
    PlayerBuddy: RGBA
    OfflinePlayerBuddy: RGBA
    PlayerSelf: RGBA
    PlayerIgnored: RGBA
    OfflinePlayerIgnored: RGBA
    ChatNormal: RGBA
    ChatEmote: RGBA
    ChatOwner: RGBA
    ChatOwnerEmote: RGBA
    ChatPriv: RGBA
    ChatPrivEmote: RGBA
    ChatPrivOwner: RGBA
    ChatPrivOwnerEmote: RGBA
    ChatBuddy: RGBA
    ChatSelf: RGBA
    AcceptTrue: RGBA
    AcceptFalse: RGBA
    MapSelected: RGBA
    MapUnselected: RGBA
    MOTD: RGBA
    MOTDHeading: RGBA


class OptionGroup(IniObject):
    key = "optiongroups"


class RegionCampain(IniObject):
    key = "regioncampains"

    RegionObject: Opaque

    nested_attributes = {"Region": ["Region"]}


class ScoredKillEvaAnnouncer(IniObject):
    key = "scoredkillevaannouncers"

    EvaEvent: Opaque
    ObjectFilter: ObjectFilter
    CountOnlyKillsByLocalPlayer: Bool
    CountOnlyKillsAgainstLocalPlayer: Bool
    MinimumCountForAnnouncement: Int
    MaximumTimeForAnnouncementMS: Int


class SkirmishAIData(IniObject):
    key = "skirmishaidatas"

    nested_attributes = {"CombatChainDefinition": ["CombatChainDefinition"]}

    DefaultTargetThreatRadius: Float
    TeamIdleCheckRadius: Float
    TeamTimeUntilConsideredIdle: Float
    DefenseTreeNodeRadius: Float

    DisableBaseBuilding: Bool
    DisableEconomyBuilding: Bool
    DisableUnitBuilding: Bool
    DisableScienceUpgrading: Bool
    DisableUnitUpgrading: Bool
    DisableTacticalAI: Bool
    DisableTeamBuilding: Bool
    DisableWallBuilding: Bool
    MakeAllSkirmishSidesAIControlled: Bool
    AnyTypeTemplateDisabledSlots: t.Int
    ArmyQualityBias: t.Int
    ArmyQuantityBias: t.Int
    BaseStrengthBias: t.Int
    BrutalDifficultyCheats: t.Opaque
    DifficultyTuning: t.Opaque
    FarmingThreshold: t.Int
    HeroQualityBias: t.Int
    LogicFrameBetweenRetreatChecks: t.Int
    LogicFramesTillAISelfDestructs: t.Int
    LogicFramesTillRetreatChecksStart: t.Int
    MapControlBias: t.Int
    RingOwnershipBias: t.Int


class AnimationSoundClientBehaviorGlobalSetting(IniObject):
    key = "animationsoundclientbehaviorglobalsettings"

    MinMicrophoneDistanceToDirty: Int


class AptButtonTooltipMap(IniObject):
    key = "aptbuttontooltipmaps"

    ButtonMap: Opaque


class AudioSettings(IniObject):
    key = "audiosettings"

    AudioRoot: t.String
    SoundsFolder: t.String
    MusicFolder: t.String
    StreamingFolder: t.String
    AmbientStreamFolder: t.String
    SoundsExtension: t.String
    MusicScriptLibraryName: Opaque

    UseDigital: Bool
    UseMidi: Bool
    OutputRate: Int
    OutputBits: Int
    OutputChannels: Int
    MixaheadLatency: Int
    MixaheadLatencyDuringMovies: Int
    LoopBufferLengthMS: Int
    LoopBufferCallbackCallsPerBufferLength: Int
    ForceResetTimeSeconds: Int
    EmergencyResetTimeSeconds: Int

    AutomaticSubtitleDurationMS: Int
    AutomaticSubtitleWindowWidth: Int
    AutomaticSubtitleLines: Int
    AutomaticSubtitleWindowColor: RGBA
    AutomaticSubtitleTextColor: RGBA

    PositionDeltaForReverbRecheck: Int
    SampleCount2D: Int
    SampleCount3D: Int
    StreamCount: Int
    GlobalMinRange: Int
    GlobalMaxRange: Int
    TimeToFadeAudio: Int
    AudioFootprintInBytes: Int
    MinSampleVolume: Int
    AmbientStreamHysteresisVolume: Int
    MillisecondsPriorToPlayingToReadSoundFile: Int
    SuppressOcclusion: Bool
    MinOcclusion: Float

    DefaultSoundVolume: Float
    DefaultAmbientVolume: Float
    DefaultMovieVolume: Float
    DefaultVoiceVolume: Float
    DefaultMusicVolume: Float

    ZoomFadeDistanceForMaxEffect: Int
    ZoomFadeZeroEffectEdgeLength: Int
    ZoomFadeFullEffectEdgeLength: Int
    ZoomMinDistance: Float
    ZoomMaxDistance: Float
    ZoomSoundVolumePercentageAmount: Float

    GlobalPaddedCellReverbMultiplier: Float
    GlobalRoomReverbMultiplier: Float
    GlobalBathroomReverbMultiplier: Float
    GlobalLivingRoomReverbMultiplier: Float
    GlobalStoneRoomReverbMultiplier: Float
    GlobalAuditoriumReverbMultiplier: Float
    GlobalConcertHallReverbMultiplier: Float
    GlobalCaveReverbMultiplier: Float
    GlobalArenaReverbMultiplier: Float
    GlobalHangarReverbMultiplier: Float
    GlobalCarpetedHallwayReverbMultiplier: Float
    GlobalHallwayReverbMultiplier: Float
    GlobalStoneCorridorReverbMultiplier: Float
    GlobalAlleyReverbMultiplier: Float
    GlobalForestReverbMultiplier: Float
    GlobalCityReverbMultiplier: Float
    GlobalMountainsReverbMultiplier: Float
    GlobalQuarryReverbMultiplier: Float
    GlobalPlainReverbMultiplier: Float
    GlobalParkingLotReverbMultiplier: Float
    GlobalSewerPipeReverbMultiplier: Float
    GlobalUnderwaterReverbMultiplier: Float
    GlobalDruggedReverbMultiplier: Float
    GlobalDizzyReverbMultiplier: Float
    GlobalPsychoticReverbMultiplier: Float

    MicrophonePreferredFractionCameraToGround: Float
    MicrophoneMinDistanceToCamera: Int
    MicrophoneMaxDistanceToCamera: Int
    MicrophonePullTowardsTerrainLookAtPointPercent: Float
    LivingWorldMicrophonePreferredFractionCameraToGround: Float
    LivingWorldMicrophoneMaxDistanceToCamera: Int
    LivingWorldZoomMaxDistance: Float

    VoiceMoveToCampMaxCampnessAtStartPoint: Int
    VoiceMoveToCampMinCampnessAtEndPoint: Int
    MinDelayBetweenEnterStateVoiceMS: Int
    Default2DSpeakerType: t.String
    Default3DSoundVolume: Float
    Default3DSpeakerType: t.String
    DefaultSpeechVolume: Float
    MicrophoneDesiredHeightAboveTerrain: Float
    MicrophoneMaxPercentageBetweenGroundAndCamera: Float
    Preferred3DHW1: t.String
    Preferred3DHW2: t.String
    Preferred3DSW: t.String
    Relative2DVolume: Float
    TimeBetweenDrawableSounds: Int


class ButtonSet(IniObject):
    key = "buttonsets"

    numbered_slots = True  # `1 = Command_X` ... command-button slots, like CommandSet

    Mode: Untyped


class CloudEffect(IniObject):
    key = "cloudeffects"

    CloudTexture: Opaque
    DarkCloudTexture: Opaque
    AlphaTexture: Opaque
    DissipateTexture: Opaque
    PropagateSpeed: Float
    Angle: Float
    CloudScrollSpeed: Float

    DarkeningFactor: RGBA
    DarkeningRate: Int
    LighteningRate: Int
    DissipateStartLevel: Float
    DissipateSpeed: Float
    DissipateRateScale: Float

    # Lightning flashes (chance/frequency are per-tick; duration/intensity are `min max` ranges).
    LightningShadows: Bool
    JitterLightningLightIntensity: Bool
    JitterLightningLightPosition: Bool
    LightningChance: Float
    LightningDuration: Untyped
    LightningFrequency: Float
    LightningIntensity: Untyped
    LightningShadowColor: RGBA
    LightningShadowIntensity: Float
    LightningLightPosition1: Coords
    LightningLightPosition2: Coords
    LightningLightPosition3: Coords
    LightningFX: t.FXList


class CreateAHeroClass(IniObject):
    key = "createaheroclass"

    NameTag: Untyped
    DescriptionTag: Untyped
    PowersDescTag: t.Label
    UpgradeName: t.UpgradeRef
    IconImage: Opaque

    nested_attributes = {"SubClass": ["SubClass"]}


class DrawGroupInfo(IniObject):
    key = "drawgroupinfos"

    # Styling of the per-unit draw-group number label.
    UsePlayerColor: Bool
    ColorForText: RGBA
    ColorForTextDropShadow: RGBA
    DropShadowOffsetX: Int
    DropShadowOffsetY: Int
    FontName: Untyped
    FontSize: Int
    FontIsBold: Bool
    DrawPositionXPercent: Float
    DrawPositionYPixel: Int


class Fire(IniObject):
    key = "fires"

    AnimationName: t.ModelFile
    AnimationMode: Untyped
    AnimationSpeedFactorRange: List[Float]
    BurntTerrainColor: t.RGB
    EnableScorches: t.Bool
    FuelIndicatorColor: t.RGB
    ScorchFrequency: t.RandomVariable
    ScorchIntensity: t.Float
    ScorchSize: t.Float
    TerrainFireSystem: t.Opaque
    TerrainSmokeSystem: t.Opaque


class FireEffect(IniObject):
    key = "fireeffects"

    Scale: Float
    Blend: Float
    BaseColor: RGBA
    EffectColor: RGBA
    EffectSaturation: Float
    BaseSaturation: Float
    Velocity: Float
    TextureCross: Int
    TextureRepeatCount: Int


class FireLogicSystem(IniObject):
    key = "firelogicsystems"

    MaxCellsBurning: Int

    nested_attributes = {"TerrainCellType": ["TerrainCellType"]}


class FontSubstitution(IniObject):
    key = "fontsubstitutions"

    Size: Int


class GlowEffect(IniObject):
    key = "gloweffects"

    GlowEnabled: Bool
    GlowDiameter: Int
    GlowIntensity: Float
    GlowTextureWidth: Int
    RadiusScale1: Float
    Amplitude1: Float
    RadiusScale2: Float
    Amplitude2: Float
    TerrainGlow: Bool
    MultipassGlowEnabled: Bool


class LargeGroupAudioUnusedKnownKeys(IniObject):
    key = "largegroupaudiounusedknownkeys"

    Key: List[Untyped]


class LightPointLevel(IniObject):
    key = "lightpointlevels"

    Name: t.String
    SpecialAbilities: Opaque


class MiscAudio(IniObject):
    key = "miscaudios"

    # Every field names the audio event played for a UI / gameplay notification (a soft
    # reference; `NoSound` and any unknown name pass through as the raw token).
    RadarNotifyHarvesterUnderAttackSound: Sound
    RadarNotifyStructureUnderAttackSound: Sound
    RadarNotifyInfiltrationSound: Sound
    RadarNotifyOnlineSound: Sound
    RadarNotifyOfflineSound: Sound
    GenericRadarEvent: Sound
    BeaconPlacedSound: Sound
    BeaconPlacementFailed: Sound
    DefectorTimerTickSound: Sound
    DefectorTimerDingSound: Sound
    AllCheerSound: Sound
    NoCanDoSound: Sound
    StealthDiscoveredSound: Sound
    StealthNeutralizedSound: Sound
    MoneyDepositSound: Sound
    MoneyWithdrawSound: Sound
    BuildingDisabled: Sound
    BuildingReenabled: Sound
    VehicleDisabled: Sound
    VehicleReenabled: Sound
    SplatterVehiclePilotsBrain: Sound
    CrateHeal: Sound
    CrateShroud: Sound
    CrateFreeUnit: Sound
    CrateMoney: Sound
    UnitPromoted: Sound
    RepairSparks: Sound
    EnterCloseCombat: Sound
    ExitCloseCombat: Sound
    IncomingChatNotification: Sound
    PrivateMessageNotification: Sound
    BuddyMessageNotification: Sound
    GameSpyCommunicatorOpen: Sound
    EnabledHotKeyPressed: Sound
    DisabledHotKeyPressed: Sound
    DisabledButtonClicked: Sound
    LowLODShellMusic: Sound
    HighLODShellMusic: Sound
    ScoreScreenMusic: Sound
    ShellMapLoadMusic: Sound
    FullScreenSubMenuMusic: Sound
    SaveFileLoadMusic: Sound
    CreditsMusic: Sound
    VolumeSampleMusic: Sound
    VolumeSampleSoundFX: Sound
    VolumeSampleVoice: Sound
    VolumeSampleAmbient: Sound
    VolumeSampleMovie: Sound
    MissionBriefingCharacterClick: Sound
    ComboBoxClick: Sound
    RIFThingTemplateReloadedSound: Sound
    RIFObjectsRefreshedSound: Sound
    FastForwardModeOn: Sound
    FastForwardModeOff: Sound
    RallyPointSet: Sound
    UnableToSetRallyPoint: Sound
    PlanningModeOrderGiven: Sound
    BuildingPlacementSound: Sound
    BadBuildingPlacementSound: Sound
    WallPlacementSound: Sound
    TargetObjectWithSpecialPowerSound: Sound
    AircraftWheelScreech: Opaque
    BattleCrySound: Opaque
    CrateSalvage: Opaque
    GUIClickSound: Sound
    LockonTickSound: Opaque
    RadarNotifyUnderAttackSound: Opaque
    RadarNotifyUnitUnderAttackSound: Opaque
    SabotageResetTimeBuilding: Opaque
    SabotageShutDownBuilding: Opaque
    TerroristInCarAttackVoice: Opaque
    TerroristInCarMoveVoice: Opaque
    TerroristInCarSelectVoice: Opaque


class Pathfinder(IniObject):
    key = "pathfinders"

    SlopeLimits: List[Float]


class RingEffect(IniObject):
    key = "ringeffects"

    Scale: Float
    Blend: Float
    BaseColor: RGBA
    EffectColor: RGBA
    EffectSaturation: Float
    BaseSaturation: Float
    Velocity: Float
    TextureCross: Int
    TextureRepeatCount: Int
    EffectBlurDiameter: Int
    BaseBlurDiameter: Int


class ShadowMap(IniObject):
    key = "shadowmaps"

    MapSize: Int
    MaxViewDistance: Float
    MinShadowedTerrainHeight: Float


class ShellMenuScheme(IniObject):
    key = "shellmenuschemes"


class StrategicHUD(IniObject):
    key = "strategichuds"
    ArmyDetailsPanel: t.Opaque
    BattleResolver: t.Opaque
    BuildQueueDetailsPanel: t.Opaque
    CancelArmyMemberMoveButton: t.Opaque
    CancelArmyMoveButton: t.Opaque
    CancelBuildingConstructionButton: t.Opaque
    Checklist: t.Opaque
    DestroyBuildingButton: t.Opaque
    DisbandArmyButton: t.Opaque
    DisbandArmyMemberButton: t.Opaque
    DynamicAutoResolveDialog: t.Opaque
    ObjectivesButton: t.Opaque
    OptionsButton: t.Opaque
    RegionDetailsPanelStructuresPage: t.Opaque
    RegionDisplay: t.Opaque
    StatsDisplay: t.Opaque
    ToggleSelectionDetailsButton: t.Opaque
    TypeImages: t.Opaque
    UpgradeUnitButton: t.Opaque


class StreamedSound(IniObject):
    key = "streamedsounds"

    # A streamed (music/ambient) track: its file and playback parameters (mirrors AudioEvent).
    Control: Untyped
    Filename: Opaque
    Priority: e.AudioPriority
    Limit: Int
    Volume: Float
    Type: Untyped
    SubmixSlider: e.AudioVolumeSlider
    Delay: t.IntRange
    DryLevel: t.Float
    LowPassCutoff: t.Float
    MaxRange: t.Float
    MinRange: t.Float
    MinVolume: t.Float
    PerFilePitchShift: t.FloatRange
    PerFileVolumeShift: t.Float
    PitchShift: t.FloatRange
    PlayPercent: t.Float
    ReverbEffectLevel: t.Float
    VolumeShift: t.Float
    VolumeSliderMultiplier: t.VolumeSliderMultiplier
    ZoomedInOffscreenMinVolumePercent: t.Float
    ZoomedInOffscreenOcclusionPercent: t.Float
    ZoomedInOffscreenVolumePercent: t.Float


class WaterTransparency(IniObject):
    key = "watertransparencys"

    TransparentWaterMinOpacity: Float
    TransparentWaterDepth: Float
    RiverTransparencyMultiplier: Float
    StandingWaterColor: RGBA
    StandingWaterTexture: Opaque
    AdditiveBlending: Bool
    RadarWaterColor: RGBA
    ReflectionPlaneZ: Float
    ReflectionOn: Bool
    ReflectionGuard: t.Coords
    SkyboxTextureE: t.Opaque
    SkyboxTextureN: t.Opaque
    SkyboxTextureS: t.Opaque
    SkyboxTextureT: t.Opaque
    SkyboxTextureW: t.Opaque
