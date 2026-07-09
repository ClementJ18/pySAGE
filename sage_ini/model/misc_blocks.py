"""Assorted nested sub-blocks scattered across the game files (object threat/flammability,
particle events, melee/sound/production module blocks, AI and formation data, etc.). Each is
typed by its parent's `nested_attributes`; the parents live in `behaviors`, `data_blocks`,
`ini_objects` and `particles`. Fields are typed conservatively - voice/sound names as soft
`Sound` references, filters as `ObjectFilter`, plain numbers as Int/Float/Bool, and anything
uncertain as a raw string - so recognizing a block never introduces a conversion error.
"""

from typing import TYPE_CHECKING

import sage_ini.model.enums as e
import sage_ini.model.types as t
from sage_ini.model.objects import NestedAttribute

if TYPE_CHECKING:
    from sage_ini.model.ini_objects import Weapon


class ThreatBreakdown(NestedAttribute):
    """An object's per-`AIKindOf` threat weighting, used by the skirmish AI.

    The block takes a plain module tag (`ThreatBreakdown ThreatBreakdown_ModuleTag`). The engine
    also tolerates the `=` form (`ThreatBreakdown = <tag>`), so `keyed_by_label` lets it parse,
    but `equals_is_spurious` has the linter flag the stray `=` (the `spurious-block-label` rule)."""

    keyed_by_label = True
    equals_is_spurious = True

    AIKindOf: t.Untyped


class Flammability(NestedAttribute):
    """How readily an object catches and spreads fire."""

    Fuel: t.Int
    MaxBurnRate: t.Int
    Decay: t.Int
    Resistance: t.Int
    FuelFactor: t.Float


class FormationPreviewDecal(NestedAttribute):
    """The ground decal previewing where a formation will stand."""

    Texture: t.TextureFile
    Width: t.Float
    Height: t.Float


class FormationPreviewItemDecal(FormationPreviewDecal):
    """The per-unit variant of `FormationPreviewDecal`."""


class Event(NestedAttribute):
    """A `Event = <variant>` block in an `FXParticleSystem`: an FXList fired at a point in the
    system's life."""

    keyed_by_label = True

    EventFX: t.FXList
    HeightOffset: t.Untyped  # a min/max pair, not a scalar
    OrientFXToTerrain: t.Bool
    PerParticle: t.Bool
    KillAfterEvent: t.Bool


class Emitter(NestedAttribute):
    """An `Emitter = <variant>` block in an `FXParticleSystem`: the velocity/volume shape
    particles spawn with (the newer combined form of EmissionVelocity/EmissionVolume)."""

    keyed_by_label = True

    VelocityType: t.Untyped
    VolumeType: t.Untyped
    IsHollow: t.Bool
    VelOrthoX: t.Untyped
    VelOrthoY: t.Untyped
    VelOrthoZ: t.Untyped
    VolCylinderRadius: t.Float
    VolCylinderLength: t.Float
    VolLineStart: t.Coords
    VolLineEnd: t.Coords
    VelOutwardOther: t.List[t.Float]


class MeleeBehavior(NestedAttribute):
    """A `MeleeBehavior = <type>` block on a horde contain: the melee formation behavior
    (`Amoeba`, ...) and its facing/range tuning."""

    keyed_by_label = True

    FacingBonus: t.Float
    AngleLimitCos: t.Float
    InnerRange: t.Float
    OuterRange: t.Float
    OuterRangeBuildings: t.Float


class AddEmotion(NestedAttribute):
    """An `AddEmotion = <emotion>` block on an `EmotionTrackerUpdate`: an emotion the object
    can enter, keyed by the emotion name."""

    keyed_by_label = True

    Duration: t.Int
    AILockDuration: t.Int


class ProductionModifier(NestedAttribute):
    """A cost/time modifier on a `ProductionUpdate`, gated by an upgrade and object filter."""

    RequiredUpgrade: t.UpgradeRef
    ModifierFilter: t.ObjectFilter
    CostMultiplier: t.Float
    TimeMultiplier: t.Float
    HeroPurchase: t.Bool
    HeroRevive: t.Bool


class _SoundSet(NestedAttribute):
    """Shared base for the voice/sound selector blocks: the `Voice*` lines common to all of
    them (each names an audio event), plus the nested `UnitSpecificSounds` block."""

    nested_attributes = {"UnitSpecificSounds": ["UnitSpecificSounds"]}

    VoiceSelect: t.Sound
    VoiceSelectBattle: t.Sound
    VoiceMove: t.Sound
    VoiceMoveToCamp: t.Sound
    VoiceMoveWhileAttacking: t.Sound
    VoiceAttack: t.Sound
    VoiceAttackCharge: t.Sound
    VoiceAttackMachine: t.Sound
    VoiceAttackStructure: t.Sound
    VoiceGuard: t.Sound
    VoiceFear: t.Sound
    VoiceRetreatToCastle: t.Sound
    SoundImpact: t.Sound
    VoicePriority: t.Int


class SoundUpgrade(_SoundSet):
    """An `UpgradeSoundSelectorClientBehavior` voice set, keyed by the upgrade trigger."""

    keyed_by_label = True

    VoiceAttackAir: t.Sound
    VoiceCreated: t.Sound
    VoiceFullyCreated: t.Sound
    ExcludedUpgrades: t.List[t.UpgradeRef]
    RequiredModelConditions: t.Untyped


class SoundState(_SoundSet):
    """A `ModelConditionSoundSelectorClientBehavior` voice set, keyed by model condition."""

    keyed_by_label = True

    VoiceEnterStateMove: t.Sound
    VoiceEnterStateMoveToCamp: t.Sound
    VoiceEnterStateMoveWhileAttacking: t.Sound
    SoundMoveLoop: t.Sound
    SoundMoveStart: t.Sound
    VoiceCreated: t.Sound
    VoiceEnterStateAttackCharge: t.Sound
    VoiceFullyCreated: t.Sound
    VoiceMove2: t.Sound
    VoiceSelect2: t.Sound
    VoiceSelectBattle2: t.Sound


class Threshold(_SoundSet):
    """A `CrowdResponse` threshold: the voices played once a crowd reaches a size."""


class Turret(NestedAttribute):
    """A `Turret` sub-module on an AI update: an independently-rotating mount, its turn/pitch
    rates and the weapon slots it controls."""

    TurretTurnRate: t.Int
    TurretPitchRate: t.Int
    ControlledWeaponSlots: t.Untyped
    AllowsPitch: t.Bool
    RecenterTime: t.Int
    InitialDirection: t.Untyped
    FiresWhileTurning: t.Bool
    MinIdleScanInterval: t.Int
    MaxIdleScanInterval: t.Int
    NaturalTurretAngle: t.Degrees
    TurretMaxDeflectionCW: t.Degrees
    TurretMaxDeflectionACW: t.Degrees


class Stance(NestedAttribute):
    """One stance of a `StanceTemplate`: the attribute modifier it applies and its melee
    behavior tuning."""

    AttributeModifier: t.ModifierRef

    nested_attributes = {"MeleeBehavior": ["MeleeBehavior"]}


class CreateDebris(NestedAttribute):
    """A `CreateDebris` nugget of an `ObjectCreationList`: models flung out with a force."""

    ModelNames: t.Untyped
    Count: t.Int
    Disposition: t.Untyped
    Offset: t.Coords
    MinForceMagnitude: t.Float
    MaxForceMagnitude: t.Float
    MinForcePitch: t.Float
    MaxForcePitch: t.Float
    DispositionIntensity: t.Float


class FireWeapon(NestedAttribute):
    """A `FireWeapon` nugget of an `ObjectCreationList`: fire a named weapon when created."""

    Weapon: "Weapon"


class ApplyRandomForce(NestedAttribute):
    """An `ApplyRandomForce` nugget: shove the created object with a random impulse."""


class Attack(NestedAttribute):
    """An `Attack` nugget: have the created object attack a target (with the attack animation
    binding the engine reads here)."""

    AnimationName: t.Untyped
    AnimationMode: t.Untyped
    AnimationBlendTime: t.Int
    UseWeaponTiming: t.Bool


class DeliverPayload(NestedAttribute):
    """A `DeliverPayload` nugget: a transport that delivers its contents on creation."""


class DecalTemplate(NestedAttribute):
    """A ground decal template on a draw module (e.g. a tornado's shadow)."""

    Texture: t.TextureFile
    Style: t.Untyped
    OpacityMin: t.Float
    OpacityMax: t.Float
    MaxRadius: t.Float
    Color: t.RGBA
    OnlyVisibleToOwningPlayer: t.Bool
    RotationsPerMinute: t.Float
    SpiralAcceleration: t.Float


class AddPlayer(NestedAttribute):
    """A scripted player slot in a `LivingWorldCampaign`."""

    PlayerTemplate: t.PlayerTemplateRef
    BaseRegion: t.Untyped
    MP_SlotColorIndex: t.Int
    TeamNumber: t.Int
    AITemplate: t.Untyped
    IsDumb: t.Bool


class Trigger(NestedAttribute):
    """The condition that grants an `ObjectAward`."""

    StatName: t.Untyped
    Stat: t.String
    Threshold: t.Int


class ObjectAward(NestedAttribute):
    """An award in the `AwardSystem`: its display strings, image and the trigger that earns it."""

    AwardName: t.Untyped
    ImageName: t.Image
    NameTag: t.Untyped
    DescriptionTag: t.Untyped

    nested_attributes = {"Trigger": ["Trigger"]}


class NotificationType(NestedAttribute):
    """One notification kind in an `InGameNotificationBox`: its title and icon."""

    Title: t.Untyped
    Icon: t.Untyped


class ImagePart(NestedAttribute):
    """One image piece of a `ControlBarScheme`: its placement and texture."""

    Position: t.Coords
    Size: t.Coords
    ImageName: t.Image
    Layer: t.Int


class SideInfo(NestedAttribute):
    """Per-side economy tuning in `AIData`."""

    ResourceGatherersEasy: t.Int
    ResourceGatherersNormal: t.Int
    ResourceGatherersHard: t.Int


class Structure(NestedAttribute):
    """One building of a `SkirmishBuildList` (`Structure <name>`): where the AI places it and
    how it rebuilds."""

    Location: t.Coords
    Rebuilds: t.Int
    Angle: t.Float
    InitiallyBuilt: t.Bool
    AutomaticallyBuild: t.Bool


class SkirmishBuildList(NestedAttribute):
    """A faction's skirmish-AI build order in `AIData` (`SkirmishBuildList <side>`): the
    ordered `Structure` placements the AI follows."""

    nested_attributes = {"Structure": ["Structure"]}


class DifficultyTuning(NestedAttribute):
    """A per-difficulty tuning profile in `SkirmishAIData` (`DifficultyTuning <name>`). The
    `* : *` probability fields are odds, kept raw."""

    Difficulty: t.Opaque
    EconomyMaxFarms: t.Int
    EconomyUpgradeProbability: t.Untyped
    SpecialPowerActivationProbability: t.Untyped
    OffensiveTacticActivationProbability: t.Untyped


class BrutalDifficultyCheats(NestedAttribute):
    """The brutal-AI handicap in `SkirmishAIData`: percentage reductions to build cost/time."""

    BuildCostReduction: t.Float
    BuildTimeReduction: t.Float


class GridDecalTemplate(NestedAttribute):
    """A ground decal on an update module (e.g. a shroud-clearing range marker): its texture,
    blend style, opacity envelope and tint."""

    Texture: t.Opaque
    Style: t.Opaque
    OpacityMin: t.Float
    OpacityMax: t.Float
    OpacityThrobTime: t.Int
    Color: t.RGBA


class CombatChainDefinition(NestedAttribute):
    """A skirmish-AI combat-chain entry: a unit and its target priorities."""

    Unit: e.CombatChainUnitType
    TargetTypes: t.Untyped
    TargetPriorityModifiers: t.Untyped


class AIEconomyAssigment(NestedAttribute):
    """A skirmish-AI economy build assignment (a template to build)."""

    TemplateName: t.ObjectRef


class AIWallNodeAssignment(NestedAttribute):
    """A skirmish-AI wall-node build assignment."""

    TemplateName: t.ObjectRef


class TerrainCellType(NestedAttribute):
    """A terrain cell's fire properties in a `FireLogicSystem`."""

    Name: t.Untyped
    Color: t.RGB
    Fuel: t.Int
    MaxBurnRate: t.Int
    Decay: t.Int
    Resistance: t.Int


class CreateAHeroBlingBinder(NestedAttribute):
    """Binds a Create-a-Hero bling option to a UI slot in `CreateAHeroSystem`."""

    GroupName: t.Untyped
    LabelTag: t.Untyped
    DescriptionTag: t.Untyped
    UISlot: t.Int
    BlingType: t.Untyped


class Attribute(NestedAttribute):
    """One tunable attribute of a `SubClass`: its group and the upgrades that bound it."""

    GroupName: t.Untyped
    MinValueUpgrade: t.UpgradeRef
    MaxValueUpgrade: t.UpgradeRef
    DefaultValueUpgrade: t.UpgradeRef


class ViewInfo(NestedAttribute):
    """The camera framing of a `SubClass` (near/far pitch, zoom, floor, ...)."""

    FarPitch: t.Float
    FarZoom: t.Float
    FarFloor: t.Float
    FarDist: t.Float
    FarShift: t.Float
    NearPitch: t.Float
    NearZoom: t.Float
    NearFloor: t.Float
    NearDist: t.Float
    NearShift: t.Float
    CloseUpPitch: t.Float
    CloseUpZoom: t.Float
    CloseUpFloor: t.Float
    CloseUpDist: t.Float
    CloseUpShift: t.Float
    PortraitPitch: t.Float
    PortraitZoom: t.Float
    PortraitFloor: t.Float
    PortraitDist: t.Float
    PortraitShift: t.Float
    CameraAngle: t.Float
    MapLocation: t.Int
    NormalCam: t.Float


class SubClass(NestedAttribute):
    """A Create-a-Hero class variant in `CreateAHeroClass`: its stats, bling and awards."""

    NameTag: t.Untyped
    DescriptionTag: t.Untyped
    UpgradeName: t.UpgradeRef
    IconImage: t.Untyped
    ButtonImage: t.Image
    Stats: t.List[t.Untyped]
    BlingUpgrades: t.List[t.UpgradeRef]
    Awards: t.List[t.Untyped]
    SpendableAttributePoints: t.Int
    UsableFactions: t.Untyped
    DefaultFaction: t.Untyped
    DefaultPrimaryColor: t.RGBA
    DefaultSecondaryColor: t.RGBA
    DefaultTertiaryColor: t.RGBA
    PowersDescTag: t.Label

    nested_attributes = {"Attribute": ["Attribute"], "ViewInfo": ["ViewInfo"]}


class Rows(NestedAttribute):
    """The row layout of a `FormationTemplate`."""

    Row: t.List[t.Untyped]


class FormationTemplate(NestedAttribute):
    """One formation shape in the `FormationAssistant`."""

    nested_attributes = {"Rows": ["Rows"]}


class UnitDefinition(NestedAttribute):
    """A unit slot in the `FormationAssistant`: which object it previews."""

    ObjectFilter: t.ObjectFilter
    PreviewObject: t.ObjectRef


class FormationSelection(NestedAttribute):
    """Drag-selection tuning in the `FormationAssistant`."""

    MaxDragLength: t.Float
    MaxUnitsSelected: t.Int
