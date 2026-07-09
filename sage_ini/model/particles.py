"""FXParticleSystem sub-blocks. A particle system's body is a fixed set of named blocks -
`System` (emitter + lifetime), `Color`/`Alpha` (keyframed tint and fade), `Update`/`Physics`
(per-particle motion), `EmissionVelocity`/`EmissionVolume` (where/how fast particles spawn)
and `Wind`. Each `= <variant>` block is typed by its name with the variant token as its key
(`keyed_by_label`); `System` carries no variant. Collected via `nested_attributes` on
`FXParticleSystem`.

Fields are typed conservatively: clearly numeric pairs as number lists, and the `X:Y:Z:`
coordinate/keyframe values as strings (a passthrough, so no conversion error is introduced
for a format not yet given a converter). Unmodelled inner keys surface as INFO coverage.
"""

import sage_ini.model.enums as e
import sage_ini.model.types as t
from sage_ini.model.objects import NestedAttribute


class System(NestedAttribute):
    """The `System` block: the emitter, the particle texture and the system/particle
    lifetimes - the spine every FXParticleSystem opens with."""

    keyed_by_label = True

    Priority: t.Untyped
    Shader: t.Untyped
    Type: e.ParticleSystemType
    ParticleName: t.Untyped
    SystemLifetime: t.Int
    SortLevel: t.Int
    IsOneShot: t.Bool
    IsGroundAligned: t.Bool
    Lifetime: t.List[t.Int]
    Size: t.List[t.Float]
    StartSizeRate: t.List[t.Float]
    BurstDelay: t.List[t.Float]
    BurstCount: t.List[t.Int]
    InitialDelay: t.List[t.Int]
    Gravity: t.Float
    IsEmitAboveGroundOnly: t.Bool
    IsParticleUpTowardsEmitter: t.Bool
    UseMaximumHeight: t.Bool
    ShroudEmitter: t.Bool
    PerParticleAttachedSystem: t.Opaque
    SlaveSystem: t.Opaque
    SlavePosOffset: t.Coords


class Color(NestedAttribute):
    """The `Color = <variant>` block: keyframed particle tint (`Color1`..`ColorN` as
    `R:.. G:.. B:.. <frame>`), kept raw, plus an overall `ColorScale`."""

    keyed_by_label = True

    Color1: t.Untyped
    Color2: t.Untyped
    Color3: t.Untyped
    Color4: t.Untyped
    Color5: t.Untyped
    Color6: t.Untyped
    Color7: t.Untyped
    Color8: t.Untyped
    ColorScale: t.List[t.Float]


class Alpha(NestedAttribute):
    """The `Alpha = <variant>` block: keyframed opacity (`Alpha1`..`AlphaN` as
    `<min> <max> <frame>`)."""

    keyed_by_label = True

    Alpha1: t.List[t.Float]
    Alpha2: t.List[t.Float]
    Alpha3: t.List[t.Float]
    Alpha4: t.List[t.Float]
    Alpha5: t.List[t.Float]
    Alpha6: t.List[t.Float]
    Alpha7: t.List[t.Float]
    Alpha8: t.List[t.Float]


class Update(NestedAttribute):
    """The `Update = <variant>` block: per-frame size and spin of each particle."""

    keyed_by_label = True

    SizeRate: t.List[t.Float]
    SizeRateDamping: t.List[t.Float]
    AngleZ: t.List[t.Float]
    AngularRateZ: t.List[t.Float]
    AngularDamping: t.List[t.Float]
    AngularDampingXY: t.List[t.Float]
    Rotation: t.Untyped
    # Per-axis start size and size damping/rate; each a `min max` range read as a float list.
    StartSizeX: t.List[t.Float]
    StartSizeY: t.List[t.Float]
    StartSizeZ: t.List[t.Float]
    SizeDampingX: t.List[t.Float]
    SizeDampingY: t.List[t.Float]
    SizeDampingZ: t.List[t.Float]
    SizeRateX: t.List[t.Float]
    SizeRateY: t.List[t.Float]
    SizeRateZ: t.List[t.Float]
    AngleXY: t.List[t.Float]
    AngularRateXY: t.List[t.Float]


class Physics(NestedAttribute):
    """The `Physics = <variant>` block: particle velocity damping, drift and gravity."""

    keyed_by_label = True

    VelocityDamping: t.List[t.Float]
    DriftVelocity: t.Coords
    Gravity: t.Float
    Swirly: t.Bool
    ParticlesAttachToBone: t.Bool


class EmissionVelocity(NestedAttribute):
    """The `EmissionVelocity = <variant>` block: the speed range particles launch at, by
    axis or as a scalar `Speed`."""

    keyed_by_label = True

    X: t.List[t.Float]
    Y: t.List[t.Float]
    Z: t.List[t.Float]
    Speed: t.List[t.Float]
    OtherSpeed: t.List[t.Float]
    Normal: t.List[t.Float]
    Radial: t.List[t.Float]  # a `min max` range (a `Yes/No` toggle in some non-Edain variants)


class EmissionVolume(NestedAttribute):
    """The `EmissionVolume = <variant>` block: the shape particles spawn within (box, sphere,
    cylinder, line, point), with its dimensions."""

    keyed_by_label = True

    IsHollow: t.Bool
    HalfSize: t.Coords
    Radius: t.Float
    Length: t.Float
    Width: t.Float
    Height: t.Float
    StartPoint: t.Coords
    EndPoint: t.Coords
    Offset: t.Coords
    RadiusRate: t.Float
    CellEmissionChance: t.Float
    # Wobble parameters (amplitude/frequency/phase per axis) and per-axis offset ranges,
    # each a `min max` range read as a float list.
    Amplitude1: t.List[t.Float]
    Amplitude2: t.List[t.Float]
    Amplitude3: t.List[t.Float]
    Frequency1: t.List[t.Float]
    Frequency2: t.List[t.Float]
    Frequency3: t.List[t.Float]
    Phase1: t.List[t.Float]
    Phase2: t.List[t.Float]
    Phase3: t.List[t.Float]
    Xoffset: t.List[t.Float]
    Yoffset: t.List[t.Float]
    Zoffset: t.List[t.Float]


class Wind(NestedAttribute):
    """The `Wind` block: how wind perturbs the particles over time."""

    keyed_by_label = True

    WindMotion: t.Untyped
    WindAngleChangeMin: t.Float
    WindAngleChangeMax: t.Float
    WindPingPongStartAngleMin: t.Float
    WindPingPongStartAngleMax: t.Float
    WindPingPongEndAngleMin: t.Float
    WindPingPongEndAngleMax: t.Float
    WindStrength: t.Float
    TurbulenceAmplitude: t.Float
    TurbulenceFrequency: t.Float
    WindFullStrengthDist: t.Float
    WindZeroStrengthDist: t.Float
