"""Draw module registry. A `Draw = W3DScriptedModelDraw Tag` header names a draw module in
its first label token; each known module is a `Draw` subclass so the block is typed into an
object's `Draw` group.

A model draw's body is a state machine: model-condition states (`ModelConditionState =
DAMAGED`) pick the model/skeleton/bones to show, and animation states (`AnimationState =
MOVING`) bind animations to those conditions. These state blocks are typed *by their name*
with the condition flags as a key (`keyed_by_label`), and collected into the nested groups
declared on the base `Draw`; each animation state in turn holds typed `Animation` clips.
"""

import sage_ini.model.enums as e
import sage_ini.model.types as t
from sage_ini.model.objects import Draw, NestedAttribute


class Animation(NestedAttribute):
    """One animation clip bound in an `AnimationState` (`Animation = GUFaramir_IDLC`): the
    `SKL.anim` asset, how it plays, and its timing. Named by the clip id in its label."""

    keyed_by_label = True

    AnimationName: t.List[t.Animation]
    AnimationMode: e.AnimationMode
    AnimationBlendTime: t.Int
    AnimationPriority: t.Int
    AnimationSpeedFactorRange: t.List[t.Float]
    AnimationMustCompleteCount: t.Int
    UseWeaponTiming: t.Bool
    DistanceCovered: t.Float
    Distance: t.Float
    AnimationMustCompleteBlend: t.Bool
    FadeBeginFrame: t.Float
    FadeEndFrame: t.Float
    FadingIn: t.Bool
    AnimationDelay: t.Int
    Image: t.Image
    NumberImages: t.Int
    RandomizeStartFrame: t.Bool


class ModelConditionState(NestedAttribute):
    """A `ModelConditionState = <flags>` block: the model, skeleton and bone bindings shown
    while the object's model conditions match the flag set in the label (the key)."""

    keyed_by_label = True

    # `Model` repeats when extra meshes are attached (`Model = <name> ExtraMesh:Yes`), so it
    # reads as a list of the raw lines; a state with a single model is a one-element list.
    Model: t.RawList
    Skeleton: t.ModelFile
    Flags: t.FlagList[e.AnimationFlag]
    TransitionKey: t.Untyped
    WaitForStateToFinishIfPossible: t.Untyped

    # Per-state overrides shared by `ModelConditionState` and `DefaultModelConditionState`.
    # Bone/effect bindings repeat (one line per slot), so they read as lists.
    ParticleSysBone: t.List[t.Untyped]
    WeaponLaunchBone: t.List[t.Tuple[e.SlotTypes, t.Bone]]
    WeaponFireFXBone: t.List[t.Tuple[e.SlotTypes, t.Bone]]
    FXEvent: t.List[t.Untyped]
    Texture: t.List[t.TextureFile]
    RetainSubObjects: t.Bool
    ModelAnimationPrefix: t.String
    PortraitImageName: t.String
    ButtonImageName: t.String
    OverrideTooltip: t.Label
    Turret: t.Opaque
    TurretArtAngle: t.Float

    Shadow: e.ObjectShadowType
    ShadowSizeX: t.Int
    ShadowSizeY: t.Int
    ShadowTexture: t.TextureFile
    ShadowMaxHeight: t.Float
    ShadowOverrideLODVisibility: t.Bool
    ShadowOpacityStart: t.Int
    ShadowOpacityPeak: t.Int
    ShadowOpacityEnd: t.Int
    ShadowOpacityFadeInTime: t.Int
    ShadowOpacityFadeOutTime: t.Int
    AltTurret: t.Opaque
    AltTurretPitch: t.Opaque
    StateName: t.String
    TurretPitch: t.Opaque
    WeaponHideShowBone: t.Opaque
    WeaponMuzzleFlash: t.Opaque
    WeaponRecoilBone: t.Opaque


class DefaultModelConditionState(ModelConditionState):
    """The `DefaultModelConditionState` block (no flag key): the model shown when no other
    `ModelConditionState` matches."""


class AnimationState(NestedAttribute):
    """An `AnimationState = <flags>` block: the animations played while the model conditions
    match the flag set in the label, plus the state's name and the `Animation` clips it binds."""

    keyed_by_label = True

    nested_attributes = {"Animation": ["Animation"]}

    StateName: t.String
    Flags: t.FlagList[e.AnimationFlag]
    FrameForPristineBonePositions: t.Int
    SimilarRestart: t.Bool
    EnteringStateFX: t.FXList
    ShareAnimation: t.Bool
    AllowRepeatInRandomPick: t.Bool
    # Bone/effect/script bindings fired during the state; each repeats (one per slot/frame).
    ParticleSysBone: t.List[t.Untyped]
    FXEvent: t.List[t.Untyped]
    LuaEvent: t.List[t.Untyped]
    BeginScript: t.Opaque


class DefaultAnimationState(AnimationState):
    """The `DefaultAnimationState` block (no flag key): the fallback animation state."""


class IdleAnimationState(AnimationState):
    """An `IdleAnimationState` block: the animation(s) played while the object is idle."""


class TransitionState(AnimationState):
    """A `TransitionState = <from> <to>` block: the animation played while moving between two
    animation states, keyed by the pair of state names in its label."""


class LodOptions(NestedAttribute):
    """A `LodOptions = <level>` block: per-LOD caps on a draw module (how many models,
    textures and animations to vary), keyed by the LOD level (`LOW`, `MEDIUM`, `HIGH`). The
    values are usually `#define` macros, so they are kept as raw strings."""

    keyed_by_label = True

    AllowMultipleModels: t.Bool
    MaxRandomTextures: t.Int
    MaxRandomAnimations: t.Int
    MaxAnimFrameDelta: t.Int


class W3DModelDraw(Draw):
    IgnoreConditionStates: t.Untyped
    OkToChangeModelColor: t.Bool
    ReceivesDynamicLights: t.Bool
    ProjectileBoneFeedbackEnabledSlots: t.FlagList[e.SlotTypes]
    AnimationsRequirePower: t.Bool
    ParticlesAttachedToAnimatedBones: t.Bool
    MinLODRequired: e.LodLevel
    ExtraPublicBone: t.List[t.Bone]
    AttachToBoneInAnotherModule: t.Bone
    TrackMarks: t.TextureFile
    TrackMarksLeftBone: t.Bone
    TrackMarksRightBone: t.Bone
    InitialRecoilSpeed: t.Float
    MaxRecoilDistance: t.Float
    RecoilSettleSpeed: t.Float


class W3DScriptedModelDraw(W3DModelDraw):
    UseStandardModelNames: t.Bool
    StaticModelLODMode: t.Bool
    MultiPlayerOnly: t.Bool
    AffectedByStealth: t.Bool
    GlowEnabled: t.Bool
    GlowEmissive: t.Bool
    ShowShadowWhileContained: t.Bool
    UseProducerTexture: t.Bool
    UseDefaultAnimation: t.Bool
    NoRotate: t.Bool
    RandomTextureFixedRandomIndex: t.Bool
    HighDetailOnly: t.Bool
    ShadowForceDisable: t.Bool
    RandomTexture: t.List[t.Opaque]  # repeats: texture-swap variants
    WallBoundsMesh: t.SubObject
    RaisedWallMesh: t.SubObject
    RampMesh1: t.SubObject
    RampMesh2: t.SubObject
    WadingParticleSys: t.ParticleSystem
    DependencySharedModelFlags: t.FlagList[e.ModelCondition]
    AlphaCameraFadeOuterRadius: t.Int
    AlphaCameraFadeInnerRadius: t.Int
    AlphaCameraAtInnerRadius: t.Float
    StaticSortLevelWhileFading: t.Int
    BirthFadeAdditive: t.Bool
    BirthFadeTime: t.Int
    TimeOfDayTexture: t.List[t.Tuple[t.TextureFile, e.TimeOfDay, t.Int]]


class W3DHordeModelDraw(W3DScriptedModelDraw):
    pass


class W3DDefaultDraw(Draw):
    pass


class DefaultDraw(Draw):
    pass


class W3DFloorDraw(Draw):
    FloorFadeRateOnObjectDeath: t.Float
    ModelName: t.ModelFile
    HideIfModelConditions: t.List[t.ModelCondition]
    WeatherTexture: t.List[t.Tuple[e.MapWeatherType, t.TextureFile]]
    StaticModelLODMode: t.Bool
    StartHidden: t.Bool
    ForceToBack: t.Bool


class W3DTreeDraw(Draw):
    DoShadow: t.Bool
    ModelName: t.ModelFile
    TextureName: t.TextureFile
    MorphTree: t.String
    SinkTime: t.Int  # a `#define`d duration
    DoTopple: t.Bool
    KillWhenFinishedToppling: t.Bool
    TaintedTree: t.Bool
    ToppleFX: t.FXList
    BounceFX: t.FXList
    MorphFX: t.FXList
    DarkeningFactor: t.RGBA
    SinkDistance: t.Float
    MoveOutwardDistanceFactor: t.Float
    FadeDistance: t.Float
    FadeTarget: t.Float
    MoveOutwardTime: t.Int
    MoveInwardTime: t.Int
    MorphTime: t.Int


class RenderObjectDraw(Draw):
    Shader1: e.W3DShader


class GpuDraw(Draw):
    FramesPerRow: t.Int
    TotalFrames: t.Int
    SpeedMultiplier: t.Float
    DetailTexture: t.TextureFile


class W3DPropDraw(Draw):
    ModelName: t.ModelFile


class W3DStreakDraw(Draw):
    Length: t.Float
    Width: t.Float
    NumSegments: t.Int
    Color: t.RGBA
    Texture: t.TextureFile
    Additive: t.Bool
    WeatherTexture: t.List[t.Tuple[e.MapWeatherType, t.TextureFile]]


class StreakDraw(Draw):
    pass


class W3DTruckDraw(W3DModelDraw):
    StaticModelLODMode: t.Bool
    TireRotationMultiplier: t.Float
    PowerslideRotationAddition: t.Float
    WadingParticleSys: t.String
    DependencySharedModelFlags: t.FlagList[e.ModelCondition]
    # Wheel/tire bones, front-to-rear, left/right, with a second row of `*2` variants.
    LeftFrontTireBone: t.Bone
    RightFrontTireBone: t.Bone
    LeftRearTireBone: t.Bone
    RightRearTireBone: t.Bone
    LeftFrontTireBone2: t.Bone
    RightFrontTireBone2: t.Bone
    LeftRearTireBone2: t.Bone
    RightRearTireBone2: t.Bone
    MidLeftMidTireBone: t.Bone
    MidLeftMidTireBone2: t.Bone
    MidRightMidTireBone: t.Bone
    MidRightMidTireBone2: t.Bone
    MidLeftFrontTireBone: t.Bone
    MidRightFrontTireBone: t.Bone
    MidLeftRearTireBone: t.Bone
    MidRightRearTireBone: t.Bone
    CabBone: t.Bone
    TrailerBone: t.Bone
    CabRotationMultiplier: t.Float
    TrailerRotationMultiplier: t.Float
    RotationDamping: t.Float
    Dust: t.ParticleSystem
    DirtSpray: t.ParticleSystem
    PowerslideSpray: t.ParticleSystem
    RandomTexture: t.List[t.Opaque]


class LightningDraw(Draw):
    OffsetX: t.List[t.Float]
    OffsetY: t.List[t.Float]
    OffsetZ: t.List[t.Float]


class W3DBuffDraw(W3DModelDraw):
    ModelName: t.ModelFile
    PreDraw: t.Bool
    StaticModelLODMode: t.Bool


class W3DLightDraw(Draw):
    Ambient: t.RGBA
    Diffuse: t.RGBA
    Radius: t.Float
    Intensity: t.Float
    AttachToBoneInAnotherModule: t.Bone
    FlickerAmplitude: t.Float
    FlickerFrequency: t.Float


class W3DSailModelDraw(W3DModelDraw):
    RandomTexture: t.List[t.Opaque]
    MaxRotationDegrees: t.Float
    BlowingThresholdDegrees: t.Float
    AboutDamping: t.Float


class ButterflyDraw(Draw):
    pass


class W3DTornadoDraw(W3DModelDraw):
    DecalTemplate: t.Untyped
    DecalCount: t.Int
    DecalMaxRadius: t.Float


class W3DQuadrupedDraw(W3DModelDraw):
    StaticModelLODMode: t.Bool
    LeftFrontFootBone: t.Bone
    RightFrontFootBone: t.Bone
    LeftRearFootBone: t.Bone
    RightRearFootBone: t.Bone


class QuadDraw(Draw):
    pass


class W3DLaserDraw(Draw):
    ArcHeight: t.Float
    Envelope: t.Untyped
    Texture: t.TextureFile
    NumBeams: t.Int
    Segments: t.Int
    InnerBeamWidth: t.Float
    OuterBeamWidth: t.Float
    SegmentOverlapRatio: t.Float
    TilingScalar: t.Float
    FanWidth: t.Float
    ScrollRate: t.Float
    InnerColor: t.RGBA
    OuterColor: t.RGBA
    Tile: t.Bool


class W3DProjectileStreamDraw(Draw):
    Texture: t.TextureFile
    Width: t.Float
    TileFactor: t.Float
    ScrollRate: t.Float
    MaxSegments: t.Int


class W3DDebrisDraw(Draw):
    pass


class W3DTankDraw(W3DModelDraw):
    TreadDebrisLeft: t.ParticleSystem
    TreadDebrisRight: t.ParticleSystem
    TreadAnimationRate: t.Float
    TreadDriveSpeedFraction: t.Float
    TreadPivotSpeedFraction: t.Float


class W3DBoatWakeModelDraw(Draw):
    pass


class W3DSupplyDraw(W3DModelDraw):
    SupplyBonePrefix: t.String


class W3DRopeDraw(Draw):
    pass


class W3DScienceModelDraw(W3DModelDraw):
    RequiredScience: t.Opaque


class W3DDependencyModelDraw(W3DModelDraw):
    AttachToBoneInContainer: t.Bone


class W3DPoliceCarDraw(W3DModelDraw):
    PowerslideRotationAddition: t.Float
    TireRotationMultiplier: t.Float
    RightFrontTireBone: t.Bone
    LeftFrontTireBone: t.Bone
    RightRearTireBone: t.Bone
    LeftRearTireBone: t.Bone


class W3DOverlordTankDraw(W3DTankDraw):
    pass


class W3DOverlordTruckDraw(W3DTruckDraw):
    pass


class W3DTankTruckDraw(W3DTruckDraw):
    TreadAnimationRate: t.Float
    TreadDriveSpeedFraction: t.Float
    TreadPivotSpeedFraction: t.Float


class W3DTracerDraw(Draw):
    pass
