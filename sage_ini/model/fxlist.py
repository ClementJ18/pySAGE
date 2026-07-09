"""FXList nuggets. An `FXList` is a bag of effect blocks played together - particles, sounds,
camera shakes, decals, tints - each a named block that may repeat. They are typed by name and
collected into the per-kind groups declared on `FXList`. None take a label key.

Fields are typed conservatively (soft references for asset names, numbers where clearly
numeric, raw strings for `R:G:B:`/`X:Y:Z:` and object-template names) so recognizing a block
never introduces a `conversion-error`; unmodelled inner keys surface as INFO coverage.
"""

import sage_ini.model.types as t
from sage_ini.model.objects import NestedAttribute


class ParticleSystem(NestedAttribute):
    """A `ParticleSystem` nugget: spawn a named `FXParticleSystem` at a bone/offset."""

    Name: t.ParticleSystem
    Count: t.Int
    Offset: t.Coords
    Height: t.Float
    Radius: t.Float
    InitialDelay: t.Untyped  # a `min max DISTRIBUTION` triple, not a scalar
    OrientToObject: t.Bool
    OnlyIfOnLand: t.Bool
    OnlyIfOnWater: t.Bool
    Ricochet: t.Bool
    AttachToObject: t.Bool
    CreateBoneOverride: t.Bone
    TargetBoneOverride: t.Bone
    UseTargetOffset: t.Bool
    TargetOffset: t.Coords
    SetTargetMatrix: t.Bool
    CreateAtGroundHeight: t.Bool
    AttachToBone: t.Bone
    ObjectFilter: t.ObjectFilter
    Weather: t.Untyped
    TargetCoeff: t.Float
    SystemLife: t.Int


class Sound(NestedAttribute):
    """A `Sound` nugget: play a named audio event, optionally gated by object filters."""

    Name: t.Sound
    Sound: t.Sound
    Key: t.Opaque
    Duck: t.Untyped  # an `AudioMap:<map> Sound:<event>` ducking spec
    StopIfNuggetPlayed: t.Bool
    SourceObjectFilter: t.Untyped  # uses an `S:<name>` source-object form, not a KindOf filter
    ObjectFilter: t.ObjectFilter
    RequiredSourceModelConditions: t.Untyped
    ExcludedSourceModelConditions: t.Untyped


class EvaEvent(NestedAttribute):
    """An `EvaEvent` nugget: fire an EVA announcement to owner/ally/enemy."""

    EvaEventOwner: t.Untyped
    EvaEventAlly: t.Untyped
    EvaEventEnemy: t.Untyped
    RequiredSourceModelConditions: t.Untyped
    ExcludedSourceModelConditions: t.Untyped
    AlwaysPlayFromHomeBase: t.Bool
    CountAsJumpToLocation: t.Bool
    ExpirationTimeMS: t.Int
    MillisecondsToWaitBeforePlaying: t.Int
    OtherEvaEventsToBlock: t.Opaque
    Priority: t.Int
    QuietTimeMS: t.Int
    SideSound: t.Opaque
    SideSounds: t.Opaque
    TimeBetweenChecksMS: t.Int
    TimeBetweenEventsMS: t.Int


class DynamicDecal(NestedAttribute):
    """A `DynamicDecal` nugget: a ground texture that fades in and out."""

    DecalName: t.Untyped
    Offset: t.Coords
    Size: t.Float
    Color: t.RGB
    Shader: t.Untyped
    OpacityStart: t.Int
    OpacityPeak: t.Int
    OpacityPeakTime: t.Int
    OpacityFadeTimeOne: t.Int
    OpacityFadeTimeTwo: t.Int
    OpacityEnd: t.Int
    StartingDelay: t.Int
    Lifetime: t.Int


class FXListAtBonePos(NestedAttribute):
    """An `FXListAtBonePos` nugget: play another `FXList` at a named bone."""

    FX: t.FXList
    BoneName: t.Bone
    Weather: t.Untyped


class TerrainScorch(NestedAttribute):
    """A `TerrainScorch` nugget: burn a scorch mark into the terrain."""

    Type: t.Untyped
    Weather: t.Untyped
    RandomRange: t.Coords
    Radius: t.Float


class CameraShakerVolume(NestedAttribute):
    """A `CameraShakerVolume` nugget: shake the camera within a radius."""

    Radius: t.Float
    Duration_Seconds: t.Float
    Amplitude_Degrees: t.Float


class BuffNugget(NestedAttribute):
    """A `BuffNugget`: apply a buff, with per-kind replacement templates."""

    BuffType: t.Untyped
    BuffName: t.Untyped
    BuffShipTemplate: t.Opaque
    BuffLifeTime: t.Int
    IsComplexBuff: t.Bool
    FXList: t.FXList
    Color: t.RGB
    Extrusion: t.Float
    BuffInfantryTemplate: t.ObjectRef
    BuffCavalryTemplate: t.ObjectRef
    BuffTrollTemplate: t.ObjectRef
    BuffOrcTemplate: t.ObjectRef
    BuffMonsterTemplate: t.ObjectRef
    BuffThingTemplate: t.ObjectRef


class ViewShake(NestedAttribute):
    """A `ViewShake` nugget: a preset camera shake, optionally object-filtered."""

    Type: t.String
    ObjectFilter: t.ObjectFilter


class TintDrawable(NestedAttribute):
    """A `TintDrawable` nugget: tint the drawable a colour over a timed envelope."""

    Color: t.RGB
    PreColorTime: t.Int
    PostColorTime: t.Int
    SustainedColorTime: t.Int
    Frequency: t.Float
    Amplitude: t.Float


class LightPulse(NestedAttribute):
    """A `LightPulse` nugget: a coloured light that grows then fades."""

    Color: t.RGB
    Radius: t.Float
    IncreaseTime: t.Int
    DecreaseTime: t.Int


class AttachedModel(NestedAttribute):
    """An `AttachedModel` nugget: attach a model to the object for the effect."""

    Modelname: t.Untyped
