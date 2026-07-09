# Field annotations are the typed converter aliases from sage_ini/model/types.py
# (`Annotated[PyType, converter]`): a checker reads each field's value type, while the
# converter runs at access time (see resolve_annotation).
from typing import TYPE_CHECKING

# `e` qualifies an enum whose name a field shadows (`DamageType: e.DamageType`).
import sage_ini.model.enums as e
from sage_ini.model.enums import (
    EmotionTypes,
    KindOf,
    LogicTypes,
    ModelCondition,
    ObjectStatus,
    WeaponsetFlags,
)
from sage_ini.model.objects import Nugget
from sage_ini.model.types import (
    Bool,
    Coords,
    Float,
    FXList,
    Int,
    List,
    ObjectFilter,
    ScaledObjectFilter,
    Untyped,
)

if TYPE_CHECKING:
    # Cross-module field types are named as string forward-refs (`List["Upgrade"]`) and
    # resolved at runtime through the class REGISTRY - importing them for real would create
    # an import cycle. Under TYPE_CHECKING there is no runtime import, so checkers can resolve
    # the names while the cycle stays broken.
    from sage_ini.model.ini_objects import (
        ModifierList,
        Object,
        ObjectCreationList,
        Upgrade,
        Weapon,
    )


class WeaponEffectNugget(Nugget):
    SpecialObjectFilter: ObjectFilter
    ForbiddenUpgradeNames: List["Upgrade"] = []
    RequiredUpgradeNames: List["Upgrade"] = []


class DamageNugget(WeaponEffectNugget):
    Damage: Float
    Radius: Float
    DamageFXType: e.DamageFXType
    DelayTime: Float
    DamageScalar: ScaledObjectFilter
    DamageArc: Float
    FlankingBonus: Float
    AcceptDamageAdd: Bool
    DamageTaperOff: Float
    DamageSpeed: Float
    DamageSubType: e.DamageType
    DrainLife: Bool
    DrainLifeMultiplier: Float
    CylinderAOE: Bool
    DamageMaxHeight: Float
    DamageArcInverted: Bool
    ForceKillObjectFilter: ObjectFilter
    DamageMaxHeightAboveTerrain: Float
    DamageType: e.DamageType
    DeathType: e.DeathType
    MinRadius: Float
    LostLeadershipUselessAgainst: KindOf


class MetaImpactNugget(WeaponEffectNugget):
    AffectHordes: Bool
    HeroResist: Float
    ShockWaveClearRadius: Bool
    ShockWaveClearMult: Float
    ShockWaveClearFlingHeight: Float
    InvertShockWave: Bool
    CyclonicFactor: Float
    FlipDirection: Bool
    ShockWaveArcInverted: Bool
    ShockWaveAmount: Float
    ShockWaveRadius: Float
    ShockWaveArc: Float
    ShockWaveTaperOff: Float
    ShockWaveSpeed: Float
    ShockWaveZMult: Float
    KillObjectFilter: ObjectFilter
    OnlyWhenJustDied: Bool
    DelayTime: Float


class ProjectileNugget(WeaponEffectNugget):
    WarheadTemplateName: "Weapon"
    WeaponLaunchBoneSlotOverride: Untyped
    ProjectileTemplateName: "Object"
    # WeaponLaunchBoneSlotOverride : SECONDARY
    AlwaysAttackHereOffset: Coords
    UseAlwaysAttackOffset: Bool


class WeaponOCLNugget(WeaponEffectNugget):
    WeaponOCLName: List["ObjectCreationList"] = []


class AttributeModifierNugget(WeaponEffectNugget):
    AttributeModifier: "ModifierList"
    AntiCategories: Untyped
    Radius: Float
    DamageFXType: e.DamageFXType
    AffectHordeMembers: Bool


class StealMoneyNugget(WeaponEffectNugget):
    AmountStolenPerAttack: Float


class DOTNugget(DamageNugget):
    DamageInterval: Float
    DamageDuration: Float


class ParalyzeNugget(WeaponEffectNugget):
    Radius: Float
    Duration: Float
    FreezeAnimation: Bool
    AffectHordeMembers: Bool
    ParalyzeFX: FXList


class EmotionWeaponNugget(WeaponEffectNugget):
    EmotionType: EmotionTypes
    Radius: Float
    Duration: Float


class FireLogicNugget(DamageNugget):
    LogicType: LogicTypes
    MinMaxBurnRate: Float
    MinDecay: Float
    MaxResistance: Float


class SpecialModelConditionNugget(WeaponEffectNugget):
    ModelConditionNames: List[ModelCondition] = []
    ModelConditionDuration: Float


class ClearNuggets(Nugget):
    # Written as a bare one-liner (`ClearNuggets`) with no body - it wipes the nuggets defined
    # so far when a weapon is re-opened, taking no fields of its own.
    bare_directive = True


class DamageFieldNugget(WeaponEffectNugget):
    WeaponTemplateName: "Weapon"
    Duration: Float


class HordeAttackNugget(WeaponEffectNugget):
    LockWeaponSlot: Untyped


class SpawnAndFadeNugget(WeaponEffectNugget):
    ObjectTargetFilter: ObjectFilter
    SpawnedObjectName: "Object"
    SpawnOffset: Coords


class GrabNugget(WeaponEffectNugget):
    RemoveTargetFromOtherContain: Bool
    ContainTargetOnEffect: Bool
    ImpactTargetOnEffect: Bool
    ShockWaveAmount: Float
    ShockWaveRadius: Float
    ShockWaveTaperOff: Float
    ShockWaveZMult: Float


class LuaEventNugget(WeaponEffectNugget):
    LuaEvent: List[Untyped]  # `Frame:N Data:<event>`, repeats
    Radius: Float
    SendToEnemies: Bool
    SendToAllies: Bool
    SendToNeutral: Bool


class SlaveAttackNugget(WeaponEffectNugget):
    pass


class DamageContainedNugget(DamageNugget):
    KillCount: Float
    KillKindof: List[KindOf] = []
    KillKindofNot: List[KindOf] = []


class OpenGateNugget(WeaponEffectNugget):
    Radius: Float


WEAPON_NUGGETS = [
    AttributeModifierNugget,
    ClearNuggets,
    DOTNugget,
    DamageContainedNugget,
    DamageFieldNugget,
    DamageNugget,
    EmotionWeaponNugget,
    FireLogicNugget,
    GrabNugget,
    HordeAttackNugget,
    LuaEventNugget,
    MetaImpactNugget,
    OpenGateNugget,
    ParalyzeNugget,
    ProjectileNugget,
    SlaveAttackNugget,
    SpawnAndFadeNugget,
    SpecialModelConditionNugget,
    StealMoneyNugget,
    WeaponOCLNugget,
]


class InvisibilityNugget(Nugget):
    ForbiddenWeaponConditions: List[WeaponsetFlags]
    InvisibilityType: Untyped
    ForbiddenConditions: Untyped
    Options: e.InvisibilityOptions
    DetectionRange: Float
    IgnoreTreeCheckUpgrades: List["Upgrade"]
    BecomeStealthedFX: FXList
    ExitStealthFX: FXList
    HintDetectableConditions: ObjectStatus


class FireWeaponNugget(Nugget):
    WeaponName: "Weapon"
    Offset: Coords
    FireDelay: Int
    OneShot: Bool
