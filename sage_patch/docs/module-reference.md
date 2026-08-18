# Engine module reference - fields and compiled-in defaults

Generated from `game.dat` by [`../scripts/module_defaults.py`](../scripts/module_defaults.py);
regenerate rather than edit. **330 modules, 6563 fields, 5231 with a recovered default (80%).**

A listed default is what the ModuleData constructor writes, so it is the value in
force whenever an INI block omits that keyword. Field names and offsets come from
the engine's own 16-byte-stride INI field-parse tables; defaults come from linear
constant-tracking through each constructor.

## Reading this

- `-` in the default column means the constructor's write was not resolvable by
  constant-tracking - typically a container or string built by a member
  constructor, which is to say "empty". It does not mean the field is unset.
- `type` is derived from the field's parse function. 165 fields (3%) use a
  parse function that has not been identified and show its raw address instead.
- Offsets are into ModuleData, not into the module instance.
- Types are checked for internal consistency: no `Bool` resolves to a non-boolean.
  Two float fields carry implausible magnitudes - `AimWeaponBehavior.AimFarDistance`
  is a genuine `FLT_MAX`, `SlowDeathBehavior.FadeDelay` is a mis-tracked value.

## ActivateModuleSpecialPower

`sizeof(ModuleData)` = 0xdc, 61 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `TriggerSpecialPower` | SpecialPowerFlags | `0x0` | - |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |

## ActiveBody

`sizeof(ModuleData)` = 0x64, 21 fields

| field | type | offset | default |
|---|---|---|---|
| `BurningDeathBehavior` | Bool | `0x51` | `No` |
| `BurningDeathFX` | FXList | `0x54` | `0` |
| `CheerRadius` | Real | `0x4c` | `200` |
| `DamageCreationList` | DamageCreationList | `0x0` | - |
| `DamagedAttributeModifier` | AsciiString | `0x30` | `0` |
| `DodgePercent` | Percent | `0x18` | `0` |
| `EnteringDamagedTransitionTime` | Duration | `0x1c` | `0` |
| `EnteringReallyDamagedTransitionTime` | Duration | `0x20` | `0` |
| `GrabDamage` | Real | `0x3c` | `200` |
| `GrabFX` | FXList | `0x38` | `0` |
| `GrabObject` | AsciiString | `0x2c` | - |
| `GrabOffset` | Coord3D | `0x40` | `0` |
| `HealingBuffFx` | FXList | `0x48` | - |
| `InitialHealth` | Real | `0xc` | `-1` |
| `MaxHealth` | Real | `0x8` | `0` |
| `MaxHealthDamaged` | Real | `0x10` | `0` |
| `MaxHealthReallyDamaged` | Real | `0x14` | `0` |
| `ReallyDamagedAttributeModifier` | AsciiString | `0x34` | `0` |
| `RecoveryTime` | Duration | `0x24` | `0` |
| `RemoveUpgradesOnDeath` | Bool | `0x50` | `No` |
| `UseDefaultDamageSettings` | Bool | `0x28` | `Yes` |

## AIGateUpdate

`sizeof(ModuleData)` = 0x10, 2 fields

| field | type | offset | default |
|---|---|---|---|
| `TriggerWidthX` | Real | `0x8` | `0` |
| `TriggerWidthY` | Real | `0xc` | `0` |

## AimWeaponBehavior

`sizeof(ModuleData)` = 0x18, 4 fields

| field | type | offset | default |
|---|---|---|---|
| `AimFarDistance` | Real | `0x14` | `3.40282e+38` |
| `AimHighThreshold` | Real | `0xc` | `0.05` |
| `AimLowThreshold` | Real | `0x8` | `-0.05` |
| `AimNearDistance` | Real | `0x10` | `0` |

## AISpecialPowerUpdate

`sizeof(ModuleData)` = 0x1c, 6 fields

| field | type | offset | default |
|---|---|---|---|
| `CommandButtonName` | AsciiString | `0x8` | `0` |
| `RandomizeTargetLocation` | Bool | `0x18` | `No` |
| `SpecialPowerAIType` | SpecialPowerAIType | `0xc` | - |
| `SpecialPowerRadius` | Real | `0x10` | `-1` |
| `SpecialPowerRange` | Real | `0x14` | `-1` |
| `SpellMakesAStructure` | Bool | `0x19` | `No` |

## AIUpdateInterface

`sizeof(ModuleData)` = 0x64, 19 fields

| field | type | offset | default |
|---|---|---|---|
| `AILuaEventsList` | AsciiString | `0x2c` | `0` |
| `AttackPriority` | AsciiString | `0x44` | `"DefaultAttackPriority"` |
| `AutoAcquireEnemiesWhenIdle` | BitFlags | `0x1c` | `0` |
| `BurningDeathTime` | Duration | `0x40` | `0` |
| `CanAttackWhileContained` | Bool | `0x25` | `No` |
| `ComboLocoAttackDistance` | Real | `0x4c` | `80` |
| `ComboLocomotorSet` | Enum | `0x50` | `0` |
| `FadeOnPortals` | Bool | `0x54` | `No` |
| `HoldGroundCloseRangeDistance` | Real | `0x28` | `0` |
| `MaxCowerTime` | Duration | `0x30` | `0` |
| `MinCowerTime` | Duration | `0x34` | `0` |
| `MoodAttackCheckRate` | Duration | `0x18` | - |
| `RampageRequiresAflame` | Bool | `0x3c` | `No` |
| `RampageTime` | Duration | `0x38` | `0` |
| `SpecialContactPoints` | AsciiStringList | `0x58` | `0` |
| `StandGround` | Bool | `0x24` | `No` |
| `StopChaseDistance` | Real | `0x20` | `500` |
| `TimeToEjectPassengersOnRampage` | Duration | `0x48` | `0` |
| `Turret` | 0x006620a2 | `0x14` | `0` |

## AllowBannerSpawnUpgrade

`sizeof(ModuleData)` = 0x138, 6 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## AnimalAIUpdate

`sizeof(ModuleData)` = 0x80, 26 fields

| field | type | offset | default |
|---|---|---|---|
| `AfraidOfCastles` | Bool | `0x7c` | `Yes` |
| `AILuaEventsList` | AsciiString | `0x2c` | `0` |
| `AttackPriority` | AsciiString | `0x44` | `"DefaultAttackPriority"` |
| `AutoAcquireEnemiesWhenIdle` | BitFlags | `0x1c` | `0` |
| `BurningDeathTime` | Duration | `0x40` | `0` |
| `CanAttackWhileContained` | Bool | `0x25` | `No` |
| `ComboLocoAttackDistance` | Real | `0x4c` | `80` |
| `ComboLocomotorSet` | Enum | `0x50` | `0` |
| `FadeOnPortals` | Bool | `0x54` | `No` |
| `FleeDistance` | Int | `0x68` | `100` |
| `FleeRange` | Int | `0x64` | `20` |
| `HoldGroundCloseRangeDistance` | Real | `0x28` | `0` |
| `MaxCowerTime` | Duration | `0x30` | `0` |
| `MaxWanderDistance` | Int | `0x70` | - |
| `MaxWanderRadius` | Int | `0x74` | - |
| `MinCowerTime` | Duration | `0x34` | `0` |
| `MoodAttackCheckRate` | Duration | `0x18` | - |
| `RampageRequiresAflame` | Bool | `0x3c` | `No` |
| `RampageTime` | Duration | `0x38` | `0` |
| `SpecialContactPoints` | AsciiStringList | `0x58` | `0` |
| `StandGround` | Bool | `0x24` | `No` |
| `StopChaseDistance` | Real | `0x20` | `500` |
| `TimeToEjectPassengersOnRampage` | Duration | `0x48` | `0` |
| `Turret` | 0x006620a2 | `0x14` | `0` |
| `UpdateTimer` | Int | `0x78` | - |
| `WanderPercentage` | Int | `0x6c` | `50` |

## AnimationSoundClientBehavior

`sizeof(ModuleData)` = 0x18, 2 fields

| field | type | offset | default |
|---|---|---|---|
| `AnimationSound` | AnimationSound | `0x0` | - |
| `MaxUpdateRangeCap` | PositiveReal | `0x14` | `3.40282e+38` |

## AODCrushCollide

`sizeof(ModuleData)` = 0x48, 16 fields

| field | type | offset | default |
|---|---|---|---|
| `Damage` | Real | `0x28` | `0` |
| `DamageType` | Enum | `0x20` | `0` |
| `DeathType` | Enum | `0x24` | `0` |
| `LargeFXList` | FXList | `0x18` | `0` |
| `LargeObjectCreationList` | ObjectCreationList | `0x1c` | `0` |
| `MediumFXList` | FXList | `0x10` | `0` |
| `MediumObjectCreationList` | ObjectCreationList | `0x14` | `0` |
| `SelfDamage` | Real | `0x44` | `0` |
| `SelfDamageType` | Enum | `0x3c` | `0` |
| `SelfDeathType` | Enum | `0x40` | `0` |
| `SmallFXList` | FXList | `0x8` | `0` |
| `SmallObjectCreationList` | ObjectCreationList | `0xc` | `0` |
| `SpecialDamage` | Real | `0x38` | `0` |
| `SpecialDamageType` | Enum | `0x30` | `0` |
| `SpecialDeathType` | Enum | `0x34` | `0` |
| `SpecialObject` | KindOfFilter | `0x2c` | - |

## AODHordeContain

`sizeof(ModuleData)` = 0x2cc, 124 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowAlliesInside` | Bool | `0x7d` | `No` |
| `AllowEnemiesInside` | Bool | `0x7e` | `No` |
| `AllowNeutralInside` | Bool | `0x7f` | `No` |
| `AllowOwnPlayerInsideOverride` | Bool | `0x7c` | `No` |
| `AlternateFormation` | AsciiString | `0x1b0` | `0` |
| `AmplitudeRandomness` | Real | `0x290` | `0` |
| `AmplitudeRandomnessZ` | Real | `0x2a4` | `0` |
| `AmplitudeScale` | Real | `0x28c` | `0` |
| `AmplitudeScaleZ` | Real | `0x2a0` | `0` |
| `AttributeModifiers` | AsciiStringList | `0x22c` | `0` |
| `BackUpMaxDelayTime` | Duration | `0x1e0` | - |
| `BackUpMaxDistance` | Real | `0x1e8` | `5` |
| `BackUpMinDelayTime` | Duration | `0x1dc` | - |
| `BackUpMinDistance` | Real | `0x1e4` | `3` |
| `BackupPercentage` | Percent | `0x1ec` | `0.5` |
| `BannerCarrierDestroyHordeOnDeath` | Bool | `0x224` | `No` |
| `BannerCarrierHordeDeathType` | DeathTypeFlags | `0x228` | `0` |
| `BannerCarrierMinLevel` | UInt8 | `0x27c` | `1` |
| `BannerCarrierPosition` | BannerCarrierPosition | `0x20c` | `0` |
| `BannerCarriersAllowed` | AsciiStringList | `0x218` | `0` |
| `BoneSpecificConditionState` | 0x008678eb | `0x0` | - |
| `CanGrabStructure` | Bool | `0x13d` | `No` |
| `CollidePickup` | Bool | `0x81` | `No` |
| `ComboHorde` | ComboHorde | `0x198` | `0` |
| `ConditionForEntry` | ModelConditionFlag | `0x14c` | `-1` |
| `ContainMax` | Int | `0x70` | `-1` |
| `CowerRadius` | Real | `0x1f0` | `0` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DamagePercentToUnits` | Percent | `0x6c` | `0` |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DestroyRidersWhoAreNotFreeToExit` | Bool | `0x142` | `No` |
| `DoorOpenTime` | Duration | `0x78` | `0` |
| `EjectPassengersOnDeath` | Bool | `0x82` | `No` |
| `Enabled` | Bool | `0x84` | `No` |
| `EnterFadeTime` | Real | `0x170` | `0` |
| `EnterSound` | AudioEventRTS | `0x38` | `0` |
| `EvaEventLastMemberDeath` | EvaEvent | `0x250` | `-1` |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `ExitBone` | AsciiString | `0xa0` | `0` |
| `ExitDelay` | Duration | `0xac` | `0` |
| `ExitFadeTime` | Real | `0x174` | `0` |
| `ExitPitchRate` | AngularVelocityReal | `0x9c` | `0` |
| `ExitSound` | AudioEventRTS | `0x3c` | `0` |
| `FadeFilter` | KindOfFilter | `0x168` | - |
| `FadePassengerOnEnter` | Bool | `0x16c` | `No` |
| `FadePassengerOnExit` | Bool | `0x16d` | `No` |
| `FadeReverse` | Bool | `0x178` | `No` |
| `FireGrabWeaponOnVictim` | Bool | `0x148` | `Yes` |
| `FlankedDelay` | Duration | `0x268` | `0` |
| `FlankedDuration` | Duration | `0x26c` | - |
| `ForcedLocomotorSet` | Enum | `0x23c` | `-1` |
| `ForceOrientationContainer` | Bool | `0x13c` | `Yes` |
| `FrequencyRandomness` | Real | `0x288` | `0` |
| `FrequencyRandomnessZ` | Real | `0x29c` | `0` |
| `FrequencyScale` | Real | `0x284` | `0` |
| `FrequencyScaleZ` | Real | `0x298` | `0` |
| `FrontAngle` | Real | `0x264` | `360` |
| `GoAggressiveOnExit` | Bool | `0x140` | `No` |
| `GrabWeapon` | WeaponTemplate | `0x144` | `0` |
| `HealthRegen%PerSec` | Real | `0xa8` | `0` |
| `InitialPayload` | 0x0086af0a | `0x0` | - |
| `IsPorcupineFormation` | Bool | `0x238` | `No` |
| `KillPassengersOnDeath` | Bool | `0x83` | `No` |
| `LargeUnitHeightFactor` | Real | `0x2b0` | `0.45` |
| `LargeUnitMaxHeight` | Real | `0x2b8` | `999999` |
| `LargeUnitMinHeight` | Real | `0x2b4` | `0` |
| `LargeUnitTailOff` | Real | `0x2c0` | `1` |
| `LargeUnitTimeout` | Duration | `0x2bc` | `2` |
| `LeaderPosition` | Coord3D | `0x200` | - |
| `LeaderRank` | Int | `0x208` | `0` |
| `LeadersAllowed` | AsciiStringList | `0x1f4` | `0` |
| `LivingWorldOverloadTemplate` | AsciiString | `0x280` | `0` |
| `MachineAllowed` | Bool | `0x240` | `No` |
| `MachineType` | AsciiString | `0x244` | `0` |
| `ManualPickUpFilter` | KindOfFilter | `0x44` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MeleeAttackLeashDistance` | Real | `0x24c` | `60` |
| `MeleeBehavior` | MeleeBehavior | `0x260` | `0` |
| `MinimumHordeSize` | Int | `0x270` | `0` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `ModifierRequiredTime` | Duration | `0x94` | `100` |
| `ModifierToGiveOnExit` | AsciiStringList | `0x88` | - |
| `NotComboFormation` | Bool | `0x25c` | `No` |
| `NumberOfExitPaths` | Int | `0x74` | `0` |
| `OathFulfilledZFactor` | Real | `0x2ac` | `1` |
| `ObjectStatusOfContained` | ObjectStatusFlags | `0x58` | `0` |
| `OrientLikeContainerOnExit` | Bool | `0x13f` | `No` |
| `PassengerBonePrefix` | PassengerBonePrefix | `0x0` | - |
| `PassengerFilter` | KindOfFilter | `0x40` | - |
| `PassengersInTurret` | Bool | `0x85` | `No` |
| `PassengersTestCollisionHeight` | Real | `0x68` | `-1000` |
| `RandomOffset` | Coord3D | `0x1d0` | - |
| `RankInfo` | RankInfo | `0x18c` | `0` |
| `RankSplit` | Bool | `0x254` | `No` |
| `RanksThatStopAdvance` | 0x0086df0b | `0x1b4` | - |
| `RanksToJustFreeWhenAttacking` | 0x0086ded1 | `0x1c4` | - |
| `RanksToReleaseWhenAttacking` | 0x0086ded1 | `0x1b8` | - |
| `ReleaseSnappyness` | Real | `0x17c` | `0.7` |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `ResetMoodCheckTimeOnExit` | Bool | `0x141` | `Yes` |
| `ScatterNearbyOnExit` | Bool | `0x13e` | `Yes` |
| `ScatterRandomness` | Real | `0x2c8` | `0.4` |
| `ScatterSpeedFactor` | Real | `0x2c4` | `0.3` |
| `ShouldThrowOutPassengers` | Bool | `0x150` | `No` |
| `ShowPips` | Bool | `0x80` | `No` |
| `Slots` | Int | `0x98` | `0` |
| `SplitHorde` | SplitHorde | `0x1a4` | `0` |
| `SplitHordeNumber` | Int | `0x258` | `0` |
| `StillAmplitude` | Real | `0x294` | `0` |
| `StillAmplitudeZ` | Real | `0x2a8` | `0` |
| `ThisFormationIsTheMainFormation` | Bool | `0x1d8` | `Yes` |
| `ThrowOutPassengersDelay` | Duration | `0x154` | `0` |
| `ThrowOutPassengersLandingWarhead` | WeaponTemplate | `0x164` | `0` |
| `ThrowOutPassengersVelocity` | Coord3D | `0x158` | - |
| `TypeOneForWeaponSet` | KindOfFlags | `0xb0` | - |
| `TypeOneForWeaponState` | KindOfFlags | `0xe8` | - |
| `TypeThreeForWeaponState` | KindOfFlags | `0x120` | - |
| `TypeTwoForWeaponSet` | KindOfFlags | `0xcc` | `0` |
| `TypeTwoForWeaponState` | KindOfFlags | `0x104` | - |
| `UpgradeCreationTrigger` | 0x0086ba2c | `0x0` | - |
| `UseMarchingAnims` | Bool | `0x25d` | `No` |
| `UseSlowHordeMovement` | Bool | `0x248` | `Yes` |
| `VisionRearOverride` | Percent | `0x274` | `0` |
| `VisionSideOverride` | Percent | `0x278` | `0` |

## ArmorUpgrade

`sizeof(ModuleData)` = 0x140, 9 fields

| field | type | offset | default |
|---|---|---|---|
| `ArmorSetFlag` | Enum | `0x0` | - |
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `IgnoreArmorUpgrade` | Bool | `0x139` | `No` |
| `KillArmorUpgrade` | Bool | `0x138` | `No` |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## ArrowStormUpdate

`sizeof(ModuleData)` = 0xe8, 66 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `CanShootEmptyGround` | Bool | `0xe4` | `No` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxShots` | Int | `0xe0` | `0` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `ShotsPerBurst` | Int | `0xdc` | `0` |
| `ShotsPerTarget` | Int | `0xd8` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TargetRadius` | Real | `0xd4` | `0` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |
| `WeaponTemplate` | AsciiString | `0xd0` | `0` |

## AssaultTransportAIUpdate

`sizeof(ModuleData)` = 0x6c, 21 fields

| field | type | offset | default |
|---|---|---|---|
| `AILuaEventsList` | AsciiString | `0x2c` | `0` |
| `AttackPriority` | AsciiString | `0x44` | `"DefaultAttackPriority"` |
| `AutoAcquireEnemiesWhenIdle` | BitFlags | `0x1c` | `0` |
| `BurningDeathTime` | Duration | `0x40` | `0` |
| `CanAttackWhileContained` | Bool | `0x25` | `No` |
| `ClearRangeRequiredToContinueAttackMove` | Real | `0x68` | `50` |
| `ComboLocoAttackDistance` | Real | `0x4c` | `80` |
| `ComboLocomotorSet` | Enum | `0x50` | `0` |
| `FadeOnPortals` | Bool | `0x54` | `No` |
| `HoldGroundCloseRangeDistance` | Real | `0x28` | `0` |
| `MaxCowerTime` | Duration | `0x30` | `0` |
| `MembersGetHealedAtLifeRatio` | Real | `0x64` | `0` |
| `MinCowerTime` | Duration | `0x34` | `0` |
| `MoodAttackCheckRate` | Duration | `0x18` | - |
| `RampageRequiresAflame` | Bool | `0x3c` | `No` |
| `RampageTime` | Duration | `0x38` | `0` |
| `SpecialContactPoints` | AsciiStringList | `0x58` | `0` |
| `StandGround` | Bool | `0x24` | `No` |
| `StopChaseDistance` | Real | `0x20` | `500` |
| `TimeToEjectPassengersOnRampage` | Duration | `0x48` | `0` |
| `Turret` | 0x006620a2 | `0x14` | `0` |

## AssistedTargetingUpdate

`sizeof(ModuleData)` = 0x18, 4 fields

| field | type | offset | default |
|---|---|---|---|
| `AssistingClipSize` | Int | `0x8` | - |
| `AssistingWeaponSlot` | LookupList | `0xc` | - |
| `LaserFromAssisted` | 0x0073ad1f | `0x10` | - |
| `LaserToTarget` | 0x0073ad1f | `0x14` | - |

## AttachUpdate

`sizeof(ModuleData)` = 0x40, 12 fields

| field | type | offset | default |
|---|---|---|---|
| `AlwaysTeleport` | Bool | `0x20` | `Yes` |
| `AnchorToTopOfGeometry` | Bool | `0x21` | `No` |
| `AttachFX` | FXList | `0x30` | `0` |
| `ObjectFilter` | KindOfFilter | `0x8` | - |
| `ParentAllyAttachmentEvaEvent` | EvaEvent | `0x28` | - |
| `ParentAllyDiedEvaEvent` | EvaEvent | `0x38` | - |
| `ParentEnemyAttachmentEvaEvent` | EvaEvent | `0x2c` | - |
| `ParentEnemyDiedtEvaEvent` | EvaEvent | `0x3c` | - |
| `ParentOwnerAttachmentEvaEvent` | EvaEvent | `0x24` | - |
| `ParentOwnerDiedEvaEvent` | EvaEvent | `0x34` | - |
| `ParentStatus` | ObjectStatusFlags | `0xc` | - |
| `ScanRange` | Real | `0x1c` | `10` |

## AttributeModifierAuraUpdate

`sizeof(ModuleData)` = 0x174, 23 fields

| field | type | offset | default |
|---|---|---|---|
| `AffectContainedOnly` | Bool | `0x16c` | `No` |
| `AffectEvil` | Bool | `0x169` | `No` |
| `AffectGood` | Bool | `0x168` | `No` |
| `AffectsKindOf` | 0x0089ecd7 | `0x0` | - |
| `AllowPowerWhenAttacking` | Bool | `0x20` | `Yes` |
| `AllowSelf` | Bool | `0x16b` | `No` |
| `AntiCategory` | 0x0089f32d | `0x160` | - |
| `AntiFX` | FXList | `0x164` | `0` |
| `BonusName` | AsciiString | `0x8` | - |
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `MaxActiveRank` | Int | `0x170` | `0` |
| `ObjectFilter` | KindOfFilter | `0x24` | - |
| `Permanent` | Bool | `0x12e` | - |
| `Range` | Real | `0x1c` | `0` |
| `RefreshDelay` | Duration | `0x18` | `1` |
| `RequiredConditions` | BitFlags | `0x15c` | `0` |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | - |
| `RunWhileDead` | Bool | `0x16a` | `No` |
| `StartsActive` | Bool | `0x158` | `No` |
| `TargetEnemy` | Bool | `0x21` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## AttributeModifierUpgrade

`sizeof(ModuleData)` = 0x13c, 7 fields

| field | type | offset | default |
|---|---|---|---|
| `AttributeModifier` | AsciiString | `0x138` | `0` |
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## AudioLoopUpgrade

`sizeof(ModuleData)` = 0x174, 15 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `KillAfterMS` | Duration | `0xc` | `0` |
| `KillOnDeath` | Bool | `0x10` | `Yes` |
| `MaxKillerAngle` | AngleReal | `0x2c` | - |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | - |
| `SoundToPlay` | AudioEventRTS | `0x8` | `0` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## AutoAbilityBehavior

`sizeof(ModuleData)` = 0x60, 11 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustAttackMeleePosition` | Bool | `0x5e` | `No` |
| `AllowSelf` | Bool | `0x5f` | `Yes` |
| `BaseMaxRangeFromStartPos` | Bool | `0x5d` | `No` |
| `ForbiddenStatus` | ObjectStatusFlags | `0x1c` | - |
| `IdleTimeSeconds` | Real | `0x14` | `0` |
| `MaxScanRange` | Real | `0x8` | `0` |
| `MinScanRange` | Real | `0xc` | `0` |
| `Query` | 0x0085d29c | `0x2c` | - |
| `SpecialAbility` | AsciiString | `0x18` | `0` |
| `StartsActive` | Bool | `0x5c` | `No` |
| `WorkingRadius` | Real | `0x10` | `0` |

## AutoDepositUpdate

`sizeof(ModuleData)` = 0x24, 8 fields

| field | type | offset | default |
|---|---|---|---|
| `DepositAmount` | Int | `0xc` | `0` |
| `DepositTiming` | Duration | `0x8` | `0` |
| `GiveNoXP` | Bool | `0x20` | `No` |
| `InitialCaptureBonus` | Int | `0x10` | `0` |
| `OnlyWhenGarrisoned` | Bool | `0x21` | `No` |
| `Upgrade` | UpgradeTemplate | `0x14` | `0` |
| `UpgradeBonusPercent` | Percent | `0x18` | `1` |
| `UpgradeMustBePresent` | KindOfFilter | `0x1c` | - |

## AutoFindHealingUpdate

`sizeof(ModuleData)` = 0x18, 4 fields

| field | type | offset | default |
|---|---|---|---|
| `AlwaysHeal` | Real | `0x14` | `0.25` |
| `NeverHeal` | Real | `0x10` | `0.95` |
| `ScanRange` | Real | `0xc` | `0` |
| `ScanRate` | Duration | `0x8` | `0` |

## AutoHealBehavior

`sizeof(ModuleData)` = 0x180, 24 fields

| field | type | offset | default |
|---|---|---|---|
| `AffectsContained` | Bool | `0x14d` | `No` |
| `AffectsWholePlayer` | Bool | `0x14c` | `No` |
| `ButtonTriggered` | Bool | `0x139` | `No` |
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `HealingAmount` | Int | `0x13c` | `0` |
| `HealingDelay` | Duration | `0x140` | `-1` |
| `HealOnlyIfNotInCombat` | Bool | `0x14f` | `No` |
| `HealOnlyIfNotUnderAttack` | Bool | `0x14e` | `No` |
| `HealOnlyOthers` | Bool | `0x16c` | `No` |
| `KindOf` | KindOfFlags | `0x150` | - |
| `NonStackable` | Bool | `0x174` | `No` |
| `Permanent` | Bool | `0x12e` | - |
| `Radius` | Int | `0x148` | `0` |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `RespawnFXList` | FXList | `0x178` | `0` |
| `RespawnMinimumDelay` | Int | `0x17c` | `0` |
| `RespawnNearbyHordeMembers` | Bool | `0x175` | `No` |
| `SingleBurst` | Bool | `0x13a` | `No` |
| `StartHealingDelay` | Duration | `0x144` | `0` |
| `StartsActive` | Bool | `0x138` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |
| `UnitHealPulseFX` | FXList | `0x170` | `0` |

## AutoPickUpUpdate

`sizeof(ModuleData)` = 0x2c, 8 fields

| field | type | offset | default |
|---|---|---|---|
| `AutoThrowObject` | Bool | `0x20` | `No` |
| `CanScanWhileAttackingOrMoving` | Bool | `0x28` | `No` |
| `EatObjectEntry` | EatObjectEntry | `0x14` | `0` |
| `PickUpFilter` | KindOfFilter | `0xc` | - |
| `RunFromButton` | Bool | `0x21` | `No` |
| `RunFromButtonNumber` | Int | `0x24` | `0` |
| `ScanDelayTime` | Duration | `0x8` | - |
| `ScanDistance` | Real | `0x10` | `300` |

## BannerCarrierUpdate

`sizeof(ModuleData)` = 0x44, 12 fields

| field | type | offset | default |
|---|---|---|---|
| `BannerMorphFX` | FXList | `0x30` | `0` |
| `DiedRespawnTime` | Duration | `0x10` | - |
| `ExpLevelDraw` | ExpLevelDraw | `0x24` | - |
| `IdleSpawnRate` | Duration | `0x8` | - |
| `MeleeFreeBannerReSpawnTime` | Duration | `0x14` | - |
| `MeleeFreeUnitSpawnTime` | Duration | `0xc` | - |
| `MorphCondition` | MorphCondition | `0x18` | - |
| `ReplenishAllNearbyHordes` | Bool | `0x39` | `No` |
| `ReplenishNearbyHorde` | Bool | `0x38` | `No` |
| `ScanHordeDistance` | Real | `0x3c` | `0` |
| `UnitSpawnFX` | FXList | `0x34` | `0` |
| `UpgradeRequired` | AsciiString | `0x40` | `0` |

## BaseUpgrade

`sizeof(ModuleData)` = 0x144, 9 fields

| field | type | offset | default |
|---|---|---|---|
| `BuildingTemplateName` | AsciiString | `0x138` | `""` |
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `Permanent` | Bool | `0x12e` | - |
| `PlacementIndex` | Int | `0x140` | `0` |
| `PlacementPrefix` | AsciiString | `0x13c` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | `0` |

## BattlePlanUpdate

`sizeof(ModuleData)` = 0xa8, 28 fields

| field | type | offset | default |
|---|---|---|---|
| `BattlePlanChangeParalyzeTime` | Duration | `0x50` | `0` |
| `BombardmentAnnouncementName` | AudioEventRTS | `0x28` | `0` |
| `BombardmentMessageLabel` | AsciiString | `0x24` | `0` |
| `BombardmentPlanAnimationTime` | Duration | `0xc` | `0` |
| `BombardmentPlanPackSoundName` | AudioEventRTS | `0x20` | `0` |
| `BombardmentPlanUnpackSoundName` | AudioEventRTS | `0x1c` | `0` |
| `HoldTheLineAnnouncementName` | AudioEventRTS | `0x4c` | `0` |
| `HoldTheLineMessageLabel` | AsciiString | `0x48` | `0` |
| `HoldTheLinePlanAnimationTime` | Duration | `0x10` | `0` |
| `HoldTheLinePlanArmorDamageScalar` | Real | `0x8c` | `1` |
| `HoldTheLinePlanPackSoundName` | AudioEventRTS | `0x44` | `0` |
| `HoldTheLinePlanUnpackSoundName` | AudioEventRTS | `0x40` | `0` |
| `InvalidMemberKindOf` | KindOfFlags | `0x70` | - |
| `SearchAndDestroyAnnouncementName` | AudioEventRTS | `0x3c` | `0` |
| `SearchAndDestroyMessageLabel` | AsciiString | `0x38` | `0` |
| `SearchAndDestroyPlanAnimationTime` | Duration | `0x14` | `0` |
| `SearchAndDestroyPlanIdleLoopSoundName` | AudioEventRTS | `0x30` | `0` |
| `SearchAndDestroyPlanPackSoundName` | AudioEventRTS | `0x34` | `0` |
| `SearchAndDestroyPlanSightRangeScalar` | Real | `0x90` | `1` |
| `SearchAndDestroyPlanUnpackSoundName` | AudioEventRTS | `0x2c` | `0` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StrategyCenterHoldTheLineMaxHealthChangeType` | Enum | `0xa0` | `1` |
| `StrategyCenterHoldTheLineMaxHealthScalar` | Real | `0x9c` | `1` |
| `StrategyCenterSearchAndDestroyDetectsStealth` | Bool | `0x98` | `Yes` |
| `StrategyCenterSearchAndDestroySightRangeScalar` | Real | `0x94` | `1` |
| `TransitionIdleTime` | Duration | `0x18` | `0` |
| `ValidMemberKindOf` | KindOfFlags | `0x54` | - |
| `VisionObjectName` | AsciiString | `0xa4` | `0` |

## BeaconClientUpdate

`sizeof(ModuleData)` = 0x10, 2 fields

| field | type | offset | default |
|---|---|---|---|
| `RadarPulseDuration` | Duration | `0xc` | `15` |
| `RadarPulseFrequency` | Duration | `0x8` | `30` |

## BezierProjectileBehavior

`sizeof(ModuleData)` = 0xc0, 37 fields

| field | type | offset | default |
|---|---|---|---|
| `BounceCount` | Int | `0x1c` | `0` |
| `BounceDistance` | Real | `0x20` | `0` |
| `BounceFirstHeight` | Real | `0x24` | `0` |
| `BounceFirstPercentIndent` | Percent | `0x2c` | `0` |
| `BounceSecondHeight` | Real | `0x28` | `0` |
| `BounceSecondPercentIndent` | Percent | `0x30` | `0` |
| `CrushStyle` | Bool | `0x18` | `No` |
| `CurveFlattenMinDist` | Real | `0x34` | `0` |
| `DetonateCallsKill` | Bool | `0x4a` | `No` |
| `DieOnImpact` | Bool | `0x19` | `No` |
| `FadeInTime` | Int | `0x44` | `0` |
| `FinalStuckTime` | Duration | `0x38` | `0` |
| `FirstHeight` | Real | `0x8` | `0` |
| `FirstPercentHeight` | Percent | `0x94` | `0.33` |
| `FirstPercentIndent` | Percent | `0x10` | `0` |
| `FlightPathAdjustDistPerSecond` | VelocityReal | `0x8c` | `0` |
| `GarrisonHitKillCount` | Int | `0x4c` | `0` |
| `GarrisonHitKillForbiddenKindOf` | KindOfFlags | `0x6c` | - |
| `GarrisonHitKillFX` | FXList | `0x88` | `0` |
| `GarrisonHitKillRequiredKindOf` | KindOfFlags | `0x50` | - |
| `GroundBounceFX` | FXList | `0xa0` | `0` |
| `GroundBounceWeapon` | WeaponTemplate | `0xa8` | `0` |
| `GroundHitFX` | FXList | `0x9c` | `0` |
| `GroundHitWeapon` | WeaponTemplate | `0xa4` | `0` |
| `IgnoreTerrainHeight` | Bool | `0x90` | `No` |
| `InvisibleFrames` | Int | `0x40` | `0` |
| `OrientToFlightPath` | Bool | `0x49` | `Yes` |
| `PostLandingEmotion` | EmotionType | `0xb8` | `-1` |
| `PostLandingEmotionRadius` | Real | `0xbc` | `0` |
| `PostLandingStateTime` | Duration | `0xb4` | `0` |
| `PreLandingEmotion` | EmotionType | `0xac` | `-1` |
| `PreLandingEmotionRadius` | Real | `0xb0` | `0` |
| `PreLandingStateTime` | Duration | `0x3c` | `0` |
| `SecondHeight` | Real | `0xc` | `0` |
| `SecondPercentHeight` | Percent | `0x98` | `0.66` |
| `SecondPercentIndent` | Percent | `0x14` | `0` |
| `TumbleRandomly` | Bool | `0x48` | `No` |

## BloodthirstyUpdate

`sizeof(ModuleData)` = 0x18, 3 fields

| field | type | offset | default |
|---|---|---|---|
| `ExperienceModifier` | Real | `0xc` | `1` |
| `InitiateVoice` | AudioEventRTS | `0x10` | `-1` |
| `SacrificeFilter` | KindOfFilter | `0x8` | - |

## BoneFXUpdate

`sizeof(ModuleData)` = 0xd94, 99 fields

| field | type | offset | default |
|---|---|---|---|
| `DamagedFXList1` | FXList | `0x12c` | - |
| `DamagedFXList2` | FXList | `0x150` | - |
| `DamagedFXList3` | FXList | `0x174` | - |
| `DamagedFXList4` | FXList | `0x198` | - |
| `DamagedFXList5` | FXList | `0x1bc` | - |
| `DamagedFXList6` | FXList | `0x1e0` | - |
| `DamagedFXList7` | FXList | `0x204` | - |
| `DamagedFXList8` | FXList | `0x228` | - |
| `DamagedOCL1` | ObjectCreationList | `0x5b0` | - |
| `DamagedOCL2` | ObjectCreationList | `0x5d4` | - |
| `DamagedOCL3` | ObjectCreationList | `0x5f8` | - |
| `DamagedOCL4` | ObjectCreationList | `0x61c` | - |
| `DamagedOCL5` | ObjectCreationList | `0x640` | - |
| `DamagedOCL6` | ObjectCreationList | `0x664` | - |
| `DamagedOCL7` | ObjectCreationList | `0x688` | - |
| `DamagedOCL8` | ObjectCreationList | `0x6ac` | - |
| `DamagedParticleSystem1` | ParticleSystem | `0xa34` | - |
| `DamagedParticleSystem2` | ParticleSystem | `0xa58` | - |
| `DamagedParticleSystem3` | ParticleSystem | `0xa7c` | - |
| `DamagedParticleSystem4` | ParticleSystem | `0xaa0` | - |
| `DamagedParticleSystem5` | ParticleSystem | `0xac4` | - |
| `DamagedParticleSystem6` | ParticleSystem | `0xae8` | - |
| `DamagedParticleSystem7` | ParticleSystem | `0xb0c` | - |
| `DamagedParticleSystem8` | ParticleSystem | `0xb30` | - |
| `DamageFXTypes` | DamageTypeFlags | `0x8` | `-1` |
| `DamageOCLTypes` | DamageTypeFlags | `0x48c` | `-1` |
| `DamageParticleTypes` | DamageTypeFlags | `0x910` | `-1` |
| `PristineFXList1` | FXList | `0xc` | - |
| `PristineFXList2` | FXList | `0x30` | - |
| `PristineFXList3` | FXList | `0x54` | - |
| `PristineFXList4` | FXList | `0x78` | - |
| `PristineFXList5` | FXList | `0x9c` | - |
| `PristineFXList6` | FXList | `0xc0` | - |
| `PristineFXList7` | FXList | `0xe4` | - |
| `PristineFXList8` | FXList | `0x108` | - |
| `PristineOCL1` | ObjectCreationList | `0x490` | - |
| `PristineOCL2` | ObjectCreationList | `0x4b4` | - |
| `PristineOCL3` | ObjectCreationList | `0x4d8` | - |
| `PristineOCL4` | ObjectCreationList | `0x4fc` | - |
| `PristineOCL5` | ObjectCreationList | `0x520` | - |
| `PristineOCL6` | ObjectCreationList | `0x544` | - |
| `PristineOCL7` | ObjectCreationList | `0x568` | - |
| `PristineOCL8` | ObjectCreationList | `0x58c` | - |
| `PristineParticleSystem1` | ParticleSystem | `0x914` | - |
| `PristineParticleSystem2` | ParticleSystem | `0x938` | - |
| `PristineParticleSystem3` | ParticleSystem | `0x95c` | - |
| `PristineParticleSystem4` | ParticleSystem | `0x980` | - |
| `PristineParticleSystem5` | ParticleSystem | `0x9a4` | - |
| `PristineParticleSystem6` | ParticleSystem | `0x9c8` | - |
| `PristineParticleSystem7` | ParticleSystem | `0x9ec` | - |
| `PristineParticleSystem8` | ParticleSystem | `0xa10` | - |
| `ReallyDamagedFXList1` | FXList | `0x24c` | - |
| `ReallyDamagedFXList2` | FXList | `0x270` | - |
| `ReallyDamagedFXList3` | FXList | `0x294` | - |
| `ReallyDamagedFXList4` | FXList | `0x2b8` | - |
| `ReallyDamagedFXList5` | FXList | `0x2dc` | - |
| `ReallyDamagedFXList6` | FXList | `0x300` | - |
| `ReallyDamagedFXList7` | FXList | `0x324` | - |
| `ReallyDamagedFXList8` | FXList | `0x348` | - |
| `ReallyDamagedOCL1` | ObjectCreationList | `0x6d0` | - |
| `ReallyDamagedOCL2` | ObjectCreationList | `0x6f4` | - |
| `ReallyDamagedOCL3` | ObjectCreationList | `0x718` | - |
| `ReallyDamagedOCL4` | ObjectCreationList | `0x73c` | - |
| `ReallyDamagedOCL5` | ObjectCreationList | `0x760` | - |
| `ReallyDamagedOCL6` | ObjectCreationList | `0x784` | - |
| `ReallyDamagedOCL7` | ObjectCreationList | `0x7a8` | - |
| `ReallyDamagedOCL8` | ObjectCreationList | `0x7cc` | - |
| `ReallyDamagedParticleSystem1` | ParticleSystem | `0xb54` | - |
| `ReallyDamagedParticleSystem2` | ParticleSystem | `0xb78` | - |
| `ReallyDamagedParticleSystem3` | ParticleSystem | `0xb9c` | - |
| `ReallyDamagedParticleSystem4` | ParticleSystem | `0xbc0` | - |
| `ReallyDamagedParticleSystem5` | ParticleSystem | `0xbe4` | - |
| `ReallyDamagedParticleSystem6` | ParticleSystem | `0xc08` | - |
| `ReallyDamagedParticleSystem7` | ParticleSystem | `0xc2c` | - |
| `ReallyDamagedParticleSystem8` | ParticleSystem | `0xc50` | - |
| `RubbleFXList1` | FXList | `0x36c` | - |
| `RubbleFXList2` | FXList | `0x390` | - |
| `RubbleFXList3` | FXList | `0x3b4` | - |
| `RubbleFXList4` | FXList | `0x3d8` | - |
| `RubbleFXList5` | FXList | `0x3fc` | - |
| `RubbleFXList6` | FXList | `0x420` | - |
| `RubbleFXList7` | FXList | `0x444` | - |
| `RubbleFXList8` | FXList | `0x468` | - |
| `RubbleOCL1` | ObjectCreationList | `0x7f0` | - |
| `RubbleOCL2` | ObjectCreationList | `0x814` | - |
| `RubbleOCL3` | ObjectCreationList | `0x838` | - |
| `RubbleOCL4` | ObjectCreationList | `0x85c` | - |
| `RubbleOCL5` | ObjectCreationList | `0x880` | - |
| `RubbleOCL6` | ObjectCreationList | `0x8a4` | - |
| `RubbleOCL7` | ObjectCreationList | `0x8c8` | - |
| `RubbleOCL8` | ObjectCreationList | `0x8ec` | - |
| `RubbleParticleSystem1` | ParticleSystem | `0xc74` | - |
| `RubbleParticleSystem2` | ParticleSystem | `0xc98` | - |
| `RubbleParticleSystem3` | ParticleSystem | `0xcbc` | - |
| `RubbleParticleSystem4` | ParticleSystem | `0xce0` | - |
| `RubbleParticleSystem5` | ParticleSystem | `0xd04` | - |
| `RubbleParticleSystem6` | ParticleSystem | `0xd28` | - |
| `RubbleParticleSystem7` | ParticleSystem | `0xd4c` | - |
| `RubbleParticleSystem8` | ParticleSystem | `0xd70` | - |

## BoredUpdate

`sizeof(ModuleData)` = 0x1c, 5 fields

| field | type | offset | default |
|---|---|---|---|
| `BoredFilter` | KindOfFilter | `0x10` | - |
| `CanScanWhileAttackingOrMoving` | Bool | `0x14` | `No` |
| `ScanDelayTime` | Duration | `0x8` | - |
| `ScanDistance` | Real | `0xc` | `300` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x18` | `0` |

## BridgeBehavior

`sizeof(ModuleData)` = 0x18, 4 fields

| field | type | offset | default |
|---|---|---|---|
| `BridgeDieFX` | 0x0085b11b | `0x10` | - |
| `BridgeDieOCL` | 0x0085b1c5 | `0x14` | - |
| `LateralScaffoldSpeed` | VelocityReal | `0x8` | `1` |
| `VerticalScaffoldSpeed` | VelocityReal | `0xc` | `1` |

## BroadcastStealthUpdate

`sizeof(ModuleData)` = 0x164, 10 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowKindOf` | KindOfFlags | `0x8` | - |
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `DelayBetweenUpdates` | Int | `0x28` | `0` |
| `Permanent` | Bool | `0x12e` | - |
| `PersistantConditions` | BitFlags | `0x160` | `0` |
| `Radius` | Real | `0x24` | `100` |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | - |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## BuildableHeroListUpgrade

`sizeof(ModuleData)` = 0x138, 6 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## BuildingBehavior

`sizeof(ModuleData)` = 0x38, 4 fields

| field | type | offset | default |
|---|---|---|---|
| `FireName` | AsciiStringList | `0x2c` | - |
| `FireWindowName` | AsciiStringList | `0x14` | - |
| `GlowWindowName` | AsciiStringList | `0x20` | - |
| `NightWindowName` | AsciiStringList | `0x8` | - |

## CallHelpOnDamage

`sizeof(ModuleData)` = 0x1c, 5 fields

| field | type | offset | default |
|---|---|---|---|
| `CallDelay` | Duration | `0x10` | - |
| `CallRadius` | Real | `0xc` | `100` |
| `DamageTypes` | DamageTypeFlags | `0x8` | `-1` |
| `MoveToAttacker` | Bool | `0x14` | `No` |
| `ValidObjects` | KindOfFilter | `0x18` | - |

## CashHackSpecialPower

`sizeof(ModuleData)` = 0x8c, 37 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `GiveLevels` | Int | `0x58` | `0` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `MoneyAmount` | Int | `0x88` | `0` |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UpgradeMoneyAmount` | 0x008c6b1e | `0x7c` | `0` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## CastleBehavior

`sizeof(ModuleData)` = 0x78, 25 fields

| field | type | offset | default |
|---|---|---|---|
| `BuildTime` | Real | `0x24` | `5` |
| `BuildVariation` | Int | `0xc` | `0` |
| `CastleToUnpackForFaction` | 0x0079bd2f | `0x68` | `0` |
| `CrewPrepareFX` | FXList | `0x44` | `0` |
| `CrewPrepareInterval` | Duration | `0x40` | `10` |
| `CrewPrepareTime` | Duration | `0x38` | `18` |
| `CrewReleaseFX` | FXList | `0x48` | `0` |
| `DecalName` | AsciiString | `0x14` | `""` |
| `DecalSize` | Real | `0x18` | `1` |
| `DisableStructureRotation` | Bool | `0x74` | `No` |
| `EvaEnemyCastleSightedEvent` | EvaEvent | `0x4c` | `-1` |
| `FactionDecal` | 0x0079ca81 | `0x5c` | `0` |
| `FadeTime` | Real | `0x1c` | `2` |
| `FilterCrew` | KindOfFilter | `0x34` | `0` |
| `FilterValidOwnedEntries` | KindOfFilter | `0x30` | - |
| `InstantUnpack` | Bool | `0x3c` | `No` |
| `KeepDeathKillsEverything` | Bool | `0x3d` | `No` |
| `MaxCastleRadius` | Real | `0x2c` | `0` |
| `PreBuiltList` | 0x0079ca18 | `0x50` | `0` |
| `PreBuiltPlyr` | AsciiString | `0x10` | `""` |
| `RepairHealthPercentPerSecond` | Percent | `0x8` | `0` |
| `ScanDistance` | Real | `0x28` | `100` |
| `Summoned` | Bool | `0x3e` | `No` |
| `TransferFoundationHealthToCastleUponUnpack` | Bool | `0x75` | `Yes` |
| `UnpackDelayTime` | Real | `0x20` | `2` |

## CastleMemberBehavior

`sizeof(ModuleData)` = 0x1c, 6 fields

| field | type | offset | default |
|---|---|---|---|
| `BeingBuiltSound` | AudioEventRTS | `0x14` | `0` |
| `CampDestroyedAllyEvaEvent` | EvaEvent | `0xc` | `10` |
| `CampDestroyedAttackerEvaEvent` | EvaEvent | `0x10` | `8` |
| `CampDestroyedOwnerEvaEvent` | EvaEvent | `0x8` | `9` |
| `CountsForEvaCastleBreached` | Bool | `0x19` | `No` |
| `StoreUpgradePrice` | Bool | `0x18` | `No` |

## CastleUpgrade

`sizeof(ModuleData)` = 0x140, 8 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |
| `Upgrade` | AsciiString | `0x138` | `0` |
| `WallUpgradeRadius` | Real | `0x13c` | `0` |

## CaveContain

`sizeof(ModuleData)` = 0x9c, 31 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowAlliesInside` | Bool | `0x7d` | `No` |
| `AllowEnemiesInside` | Bool | `0x7e` | `No` |
| `AllowNeutralInside` | Bool | `0x7f` | `No` |
| `AllowOwnPlayerInsideOverride` | Bool | `0x7c` | `No` |
| `BoneSpecificConditionState` | 0x008678eb | `0x0` | - |
| `CaveIndex` | Int | `0x98` | `0` |
| `CollidePickup` | Bool | `0x81` | `No` |
| `ContainMax` | Int | `0x70` | `-1` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DamagePercentToUnits` | Percent | `0x6c` | `0` |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DoorOpenTime` | Duration | `0x78` | `0` |
| `EjectPassengersOnDeath` | Bool | `0x82` | `No` |
| `Enabled` | Bool | `0x84` | `No` |
| `EnterSound` | AudioEventRTS | `0x38` | `0` |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `ExitSound` | AudioEventRTS | `0x3c` | `0` |
| `KillPassengersOnDeath` | Bool | `0x83` | `No` |
| `ManualPickUpFilter` | KindOfFilter | `0x44` | `0` |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `ModifierRequiredTime` | Duration | `0x94` | `100` |
| `ModifierToGiveOnExit` | AsciiStringList | `0x88` | - |
| `NumberOfExitPaths` | Int | `0x74` | `0` |
| `ObjectStatusOfContained` | ObjectStatusFlags | `0x58` | `0` |
| `PassengerBonePrefix` | PassengerBonePrefix | `0x0` | - |
| `PassengerFilter` | KindOfFilter | `0x40` | - |
| `PassengersInTurret` | Bool | `0x85` | `No` |
| `PassengersTestCollisionHeight` | Real | `0x68` | `-1000` |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `ShowPips` | Bool | `0x80` | `No` |

## CitadelSlaughterHordeContain

`sizeof(ModuleData)` = 0x110, 46 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowAlliesInside` | Bool | `0x7d` | `No` |
| `AllowEnemiesInside` | Bool | `0x7e` | `No` |
| `AllowNeutralInside` | Bool | `0x7f` | `No` |
| `AllowOwnPlayerInsideOverride` | Bool | `0x7c` | `No` |
| `BoneSpecificConditionState` | 0x008678eb | `0x0` | - |
| `CanAlwaysEnter` | KindOfFilter | `0xd8` | - |
| `CashBackPercent` | Percent | `0xd4` | `0.5` |
| `CollidePickup` | Bool | `0x81` | `No` |
| `ContainMax` | Int | `0x70` | `-1` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DamagePercentToUnits` | Percent | `0x6c` | `0` |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DoorOpenTime` | Duration | `0x78` | `0` |
| `EjectPassengersOnDeath` | Bool | `0x82` | `No` |
| `Enabled` | Bool | `0x84` | `No` |
| `EnterSound` | AudioEventRTS | `0x38` | `0` |
| `EntryOffset` | Coord3D | `0xb0` | - |
| `EntryPosition` | Coord3D | `0xbc` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `ExitDelay` | Duration | `0xac` | `0` |
| `ExitOffset` | Coord3D | `0xc8` | `1` |
| `ExitSound` | AudioEventRTS | `0x3c` | `0` |
| `FXForRingEntry` | FXList | `0x10c` | `0` |
| `HealObjects` | Bool | `0x98` | `No` |
| `ImmuneToClearBuildingAttacks` | Bool | `0xa1` | `No` |
| `InitialRoster` | 0x00653381 | `0x0` | - |
| `KillPassengersOnDeath` | Bool | `0x83` | `No` |
| `ManualPickUpFilter` | KindOfFilter | `0x44` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `MobileGarrison` | Bool | `0xa0` | `No` |
| `ModifierRequiredTime` | Duration | `0x94` | `100` |
| `ModifierToGiveOnExit` | AsciiStringList | `0x88` | - |
| `NumberOfExitPaths` | Int | `0x74` | `0` |
| `ObjectStatusOfContained` | ObjectStatusFlags | `0x58` | - |
| `ObjectToDestroyForRingEntry` | KindOfFilter | `0xfc` | - |
| `PassengerBonePrefix` | PassengerBonePrefix | `0x0` | - |
| `PassengerFilter` | KindOfFilter | `0x40` | - |
| `PassengersInTurret` | Bool | `0x85` | `No` |
| `PassengersTestCollisionHeight` | Real | `0x68` | `-1000` |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `ShowPips` | Bool | `0x80` | `No` |
| `StatusForRingEntry` | ObjectStatusFlags | `0xec` | - |
| `StatusRequiredForCanAlwaysEnter` | ObjectStatusFlags | `0xdc` | - |
| `TimeForFullHeal` | DurationReal | `0x9c` | `1` |
| `UpgradeForRingEntry` | AsciiStringList | `0x100` | `0` |

## CivilianSpawnCollide

`sizeof(ModuleData)` = 0xc, 1 field

| field | type | offset | default |
|---|---|---|---|
| `DeleteObjectFilter` | KindOfFilter | `0x8` | - |

## CivilianSpawnUpdate

`sizeof(ModuleData)` = 0x20, 4 fields

| field | type | offset | default |
|---|---|---|---|
| `Civilian` | AsciiStringList | `0x14` | `0` |
| `MaximumDistance` | Int | `0x10` | `300` |
| `RunToFilter` | KindOfFilter | `0xc` | - |
| `SpawnDelayTime` | Duration | `0x8` | - |

## ClearanceTestingSlowDeathBehavior

`sizeof(ModuleData)` = 0x208, 38 fields

| field | type | offset | default |
|---|---|---|---|
| `ClearanceGeometry` | GeometryType | `0x190` | - |
| `ClearanceGeometryHeight` | 0x00ad2b60 | `0x190` | - |
| `ClearanceGeometryIsSmall` | 0x00ad2b30 | `0x190` | - |
| `ClearanceGeometryMajorRadius` | 0x00ad2bc0 | `0x190` | - |
| `ClearanceGeometryMinorRadius` | 0x00ad2c10 | `0x190` | - |
| `ClearanceGeometryOffset` | Coord3D | `0x1ec` | - |
| `ClearanceGeometryRotationAnchorOffset` | 0x00ad14c0 | `0x190` | - |
| `ClearanceMaxHeight` | NonNegativeReal | `0x1f8` | `20` |
| `ClearanceMaxHeightFraction` | NonNegativeReal | `0x1fc` | `1.1` |
| `ClearanceMinHeight` | NonPositiveReal | `0x200` | `-20` |
| `ClearanceMinHeightFraction` | NonNegativeReal | `0x204` | `1.1` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DeathFlags` | 0x008612e7 | `0x0` | - |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DecayBeginTime` | Duration | `0x54` | `0` |
| `DestructionDelay` | Duration | `0x4c` | `0` |
| `DestructionDelayVariance` | Duration | `0x50` | `0` |
| `DoNotRandomizeMidpoint` | Bool | `0x18e` | `No` |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `FadeDelay` | Duration | `0x188` | `4207599104` |
| `FadeTime` | Duration | `0x184` | `6` |
| `FlingForce` | Real | `0x118` | `0` |
| `FlingForceVariance` | Real | `0x11c` | `0` |
| `FlingPitch` | AngleReal | `0x120` | `0` |
| `FlingPitchVariance` | AngleReal | `0x124` | `0` |
| `FX` | MomentFXList | `0x0` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `ModifierBonusPerOverkillPercent` | Percent | `0x40` | `0` |
| `OCL` | MomentOCL | `0x0` | - |
| `ProbabilityModifier` | Int | `0x3c` | `10` |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `ShadowWhenDead` | Bool | `0x18d` | `No` |
| `SinkDelay` | Duration | `0x44` | `0` |
| `SinkDelayVariance` | Duration | `0x48` | `0` |
| `SinkRate` | VelocityReal | `0x38` | `0` |
| `Sound` | MomentSound | `0x0` | - |
| `Weapon` | MomentWeapon | `0x0` | - |

## ClickReactionBehavior

`sizeof(ModuleData)` = 0x20, 6 fields

| field | type | offset | default |
|---|---|---|---|
| `ClickReactionTimer` | Int | `0x8` | `600` |
| `ReactionFrames1` | Int | `0xc` | - |
| `ReactionFrames2` | Int | `0x10` | - |
| `ReactionFrames3` | Int | `0x14` | - |
| `ReactionFrames4` | Int | `0x18` | - |
| `ReactionFrames5` | Int | `0x1c` | - |

## CloudBreakSpecialPower

`sizeof(ModuleData)` = 0x8c, 39 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `CloudBreakFX` | FXList | `0x80` | `0` |
| `CloudBreakRadius` | Real | `0x7c` | `10` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `GiveLevels` | Int | `0x58` | `0` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `ObjectSpacing` | Real | `0x88` | `100` |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `SunbeamObject` | AsciiString | `0x84` | `0` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## CombineHordeSpecialPower

`sizeof(ModuleData)` = 0x80, 36 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `GiveLevels` | Int | `0x58` | `0` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `ScanRange` | Real | `0x7c` | `100` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## CommandButtonHuntUpdate

`sizeof(ModuleData)` = 0x10, 2 fields

| field | type | offset | default |
|---|---|---|---|
| `ScanRange` | Real | `0xc` | `9999` |
| `ScanRate` | Duration | `0x8` | - |

## CommandPointsUpgrade

`sizeof(ModuleData)` = 0x140, 8 fields

| field | type | offset | default |
|---|---|---|---|
| `CommandPoints` | Int | `0x138` | `0` |
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RequiredObject` | KindOfFilter | `0x13c` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## CommandSetUpgrade

`sizeof(ModuleData)` = 0x13c, 7 fields

| field | type | offset | default |
|---|---|---|---|
| `CommandSet` | AsciiString | `0x138` | `""` |
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | `0` |

## CostModifierUpgrade

`sizeof(ModuleData)` = 0x15c, 13 fields

| field | type | offset | default |
|---|---|---|---|
| `ApplyToTheseUpgrades` | AsciiStringList | `0x150` | `0` |
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `LabelForPalantirString` | AsciiString | `0x14c` | - |
| `ObjectFilter` | KindOfFilter | `0x138` | - |
| `Percentage` | 0x008ba26f | `0x13c` | `0` |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `Slaughter` | Bool | `0x14a` | `No` |
| `StartsActive` | Bool | `0x149` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |
| `UpgradeDiscount` | Bool | `0x148` | `No` |

## CreateCrateDie

`sizeof(ModuleData)` = 0x3c, 7 fields

| field | type | offset | default |
|---|---|---|---|
| `CrateData` | 0x00888b65 | `0x0` | - |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |

## CreateObjectDie

`sizeof(ModuleData)` = 0x4c, 9 fields

| field | type | offset | default |
|---|---|---|---|
| `CreationList` | ObjectCreationList | `0x38` | `0` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DebrisPortionOfSelf` | AsciiString | `0x3c` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `UpgradeRequired` | AsciiStringList | `0x40` | `0` |

## CreateObjectDieIfEldestKindof

`sizeof(ModuleData)` = 0x50, 10 fields

| field | type | offset | default |
|---|---|---|---|
| `CreationList` | ObjectCreationList | `0x38` | `0` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DebrisPortionOfSelf` | AsciiString | `0x3c` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `ObjectFilter` | KindOfFilter | `0x4c` | - |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `UpgradeRequired` | AsciiStringList | `0x40` | `0` |

## CritterEmitterUpdate

`sizeof(ModuleData)` = 0x24, 3 fields

| field | type | offset | default |
|---|---|---|---|
| `FX` | FXList | `0x8` | `0` |
| `ReloadTime` | Duration | `0x20` | `0` |
| `SpawnObject` | 0x008cd3a8 | `0x0` | - |

## CrushDie

`sizeof(ModuleData)` = 0x58, 12 fields

| field | type | offset | default |
|---|---|---|---|
| `BackEndCrushSound` | AudioEventRTS | `0x3c` | - |
| `BackEndCrushSoundPercent` | Int | `0x4c` | - |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `FrontEndCrushSound` | AudioEventRTS | `0x40` | - |
| `FrontEndCrushSoundPercent` | Int | `0x50` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `TotalCrushSound` | AudioEventRTS | `0x38` | - |
| `TotalCrushSoundPercent` | Int | `0x48` | - |

## CurseSpecialPower

`sizeof(ModuleData)` = 0xdc, 63 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CursedFX` | FXList | `0xd4` | `0` |
| `CursePercentage` | Percent | `0xd8` | `1` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerFX` | FXList | `0xd0` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |

## DamageFieldUpdate

`sizeof(ModuleData)` = 0x1c, 7 fields

| field | type | offset | default |
|---|---|---|---|
| `AliveOnly` | Bool | `0xe` | `No` |
| `ChargingModeTrigger` | Bool | `0xd` | `No` |
| `FireWeaponNugget` | FireWeaponNugget | `0x0` | - |
| `HeroModeTrigger` | Bool | `0xc` | `No` |
| `ObjectFilter` | KindOfFilter | `0x14` | - |
| `Radius` | Int | `0x10` | `0` |
| `RequiredUpgrade` | AsciiString | `0x18` | `0` |

## DamageFilteredCreateObjectDie

`sizeof(ModuleData)` = 0x48, 10 fields

| field | type | offset | default |
|---|---|---|---|
| `CreationList` | ObjectCreationList | `0x38` | `0` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DamageTypeTriggersForDuration` | Enum | `0x40` | - |
| `DamageTypeTriggersInstantly` | Enum | `0x3c` | - |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `PostFilterTriggeredDuration` | Duration | `0x44` | `0` |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |

## DarknessSpecialPower

`sizeof(ModuleData)` = 0x84, 37 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `DarknessFX` | FXList | `0x80` | `0` |
| `DarknessRadius` | Real | `0x7c` | `10` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `GiveLevels` | Int | `0x58` | `0` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## DefaultProductionExitUpdate

`sizeof(ModuleData)` = 0x20, 2 fields

| field | type | offset | default |
|---|---|---|---|
| `NaturalRallyPoint` | Coord3D | `0x14` | - |
| `UnitCreatePoint` | Coord3D | `0x8` | - |

## DefectorSpecialPower

`sizeof(ModuleData)` = 0x80, 36 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `FatCursorRadius` | Real | `0x7c` | `0` |
| `GiveLevels` | Int | `0x58` | `0` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## DeflectSpecialPower

`sizeof(ModuleData)` = 0x18, 3 fields

| field | type | offset | default |
|---|---|---|---|
| `InitiateSound` | AudioEventRTS | `0xc` | `-1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0x14` | `No` |

## DelayedDeathBody

`sizeof(ModuleData)` = 0x80, 28 fields

| field | type | offset | default |
|---|---|---|---|
| `BurningDeathBehavior` | Bool | `0x51` | `No` |
| `BurningDeathFX` | FXList | `0x54` | `0` |
| `CanRespawn` | Bool | `0x68` | `Yes` |
| `CheerRadius` | Real | `0x4c` | `200` |
| `DamageCreationList` | DamageCreationList | `0x0` | - |
| `DamagedAttributeModifier` | AsciiString | `0x30` | `0` |
| `DelayedDeathPrerequisiteUpgrade` | UpgradeTemplate | `0x7c` | `0` |
| `DelayedDeathTime` | Duration | `0x6c` | `0` |
| `DodgePercent` | Percent | `0x18` | `0` |
| `DoHealthCheck` | Bool | `0x78` | `Yes` |
| `EnteringDamagedTransitionTime` | Duration | `0x1c` | `0` |
| `EnteringReallyDamagedTransitionTime` | Duration | `0x20` | `0` |
| `GrabDamage` | Real | `0x3c` | `200` |
| `GrabFX` | FXList | `0x38` | `0` |
| `GrabObject` | AsciiString | `0x2c` | - |
| `GrabOffset` | Coord3D | `0x40` | `0` |
| `HealingBuffFx` | FXList | `0x48` | - |
| `ImmortalUntilDeathTime` | Bool | `0x70` | `Yes` |
| `InitialHealth` | Real | `0xc` | `-1` |
| `InvulnerableFX` | FXList | `0x74` | `0` |
| `MaxHealth` | Real | `0x8` | `0` |
| `MaxHealthDamaged` | Real | `0x10` | `0` |
| `MaxHealthReallyDamaged` | Real | `0x14` | `0` |
| `PermanentlyKilledByFilter` | KindOfFilter | `0x64` | - |
| `ReallyDamagedAttributeModifier` | AsciiString | `0x34` | `0` |
| `RecoveryTime` | Duration | `0x24` | `0` |
| `RemoveUpgradesOnDeath` | Bool | `0x50` | `No` |
| `UseDefaultDamageSettings` | Bool | `0x28` | `Yes` |

## DelayedUpgrade

`sizeof(ModuleData)` = 0x13c, 7 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `DelayTime` | Duration | `0x138` | `0` |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## DeletionUpdate

`sizeof(ModuleData)` = 0x10, 2 fields

| field | type | offset | default |
|---|---|---|---|
| `MaxLifetime` | Duration | `0xc` | - |
| `MinLifetime` | Duration | `0x8` | - |

## DemoTrapUpdate

`sizeof(ModuleData)` = 0x40, 10 fields

| field | type | offset | default |
|---|---|---|---|
| `AutoDetonationWithFriendsInvolved` | Bool | `0x3d` | `No` |
| `DefaultProximityMode` | Bool | `0x3c` | `No` |
| `DetonateWhenKilled` | Bool | `0x3e` | `No` |
| `DetonationWeapon` | WeaponTemplate | `0x8` | `0` |
| `DetonationWeaponSlot` | LookupList | `0x2c` | `0` |
| `IgnoreTargetTypes` | KindOfFlags | `0xc` | - |
| `ManualModeWeaponSlot` | LookupList | `0x28` | `0` |
| `ProximityModeWeaponSlot` | LookupList | `0x30` | `0` |
| `ScanRate` | Duration | `0x38` | `0` |
| `TriggerDetonationRange` | Real | `0x34` | `0` |

## DeployStyleAIUpdate

`sizeof(ModuleData)` = 0x74, 26 fields

| field | type | offset | default |
|---|---|---|---|
| `AILuaEventsList` | AsciiString | `0x2c` | `0` |
| `AttackPriority` | AsciiString | `0x44` | `"DefaultAttackPriority"` |
| `AutoAcquireEnemiesWhenIdle` | BitFlags | `0x1c` | `0` |
| `BurningDeathTime` | Duration | `0x40` | `0` |
| `CanAttackWhileContained` | Bool | `0x25` | `No` |
| `ComboLocoAttackDistance` | Real | `0x4c` | `80` |
| `ComboLocomotorSet` | Enum | `0x50` | `0` |
| `DeployedAttributeModifier` | AsciiString | `0x70` | `0` |
| `FadeOnPortals` | Bool | `0x54` | `No` |
| `HoldGroundCloseRangeDistance` | Real | `0x28` | `0` |
| `MaxCowerTime` | Duration | `0x30` | `0` |
| `MinCowerTime` | Duration | `0x34` | `0` |
| `MoodAttackCheckRate` | Duration | `0x18` | - |
| `MustDeployToAttack` | Bool | `0x6f` | `Yes` |
| `PackTime` | Duration | `0x68` | `0` |
| `RampageRequiresAflame` | Bool | `0x3c` | `No` |
| `RampageTime` | Duration | `0x38` | `0` |
| `ResetTurretBeforePacking` | Bool | `0x6c` | `No` |
| `SpecialContactPoints` | AsciiStringList | `0x58` | `0` |
| `StandGround` | Bool | `0x24` | `No` |
| `StopChaseDistance` | Real | `0x20` | `500` |
| `TimeToEjectPassengersOnRampage` | Duration | `0x48` | `0` |
| `Turret` | 0x006620a2 | `0x14` | `0` |
| `TurretsFunctionOnlyWhenDeployed` | Bool | `0x6d` | `No` |
| `TurretsMustCenterBeforePacking` | Bool | `0x6e` | `No` |
| `UnpackTime` | Duration | `0x64` | `0` |

## DestroyDie

`sizeof(ModuleData)` = 0x38, 6 fields

| field | type | offset | default |
|---|---|---|---|
| `DamageAmountRequired` | Real | `0x24` | - |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |

## DestroyEnvironmentUpdate

`sizeof(ModuleData)` = 0x10, 2 fields

| field | type | offset | default |
|---|---|---|---|
| `DestructionTime` | Duration | `0xc` | `100` |
| `StartTime` | Duration | `0x8` | `0` |

## DetachableRiderBody

`sizeof(ModuleData)` = 0x1a0, 30 fields

| field | type | offset | default |
|---|---|---|---|
| `BurningDeathBehavior` | Bool | `0x51` | `No` |
| `BurningDeathFX` | FXList | `0x54` | `0` |
| `CheerRadius` | Real | `0x4c` | `200` |
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `DamageCreationList` | DamageCreationList | `0x0` | - |
| `DamagedAttributeModifier` | AsciiString | `0x30` | `0` |
| `DodgePercent` | Percent | `0x18` | `0` |
| `EnteringDamagedTransitionTime` | Duration | `0x1c` | `0` |
| `EnteringReallyDamagedTransitionTime` | Duration | `0x20` | `0` |
| `GrabDamage` | Real | `0x3c` | `200` |
| `GrabFX` | FXList | `0x38` | `0` |
| `GrabObject` | AsciiString | `0x2c` | - |
| `GrabOffset` | Coord3D | `0x40` | `0` |
| `HealingBuffFx` | FXList | `0x48` | - |
| `HealthPercentageWhenRiderDies` | Percent | `0x194` | `1` |
| `InitialHealth` | Real | `0xc` | `-1` |
| `MaxHealth` | Real | `0x8` | `0` |
| `MaxHealthDamaged` | Real | `0x10` | `0` |
| `MaxHealthReallyDamaged` | Real | `0x14` | `0` |
| `Permanent` | Bool | `0x12e` | - |
| `ReallyDamagedAttributeModifier` | AsciiString | `0x34` | `0` |
| `RecoveryTime` | Duration | `0x24` | `0` |
| `RemoveUpgradesOnDeath` | Bool | `0x50` | `No` |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | - |
| `RiderlessDeathChance` | Percent | `0x19c` | `0` |
| `StartsActive` | Bool | `0x198` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |
| `UseDefaultDamageSettings` | Bool | `0x28` | `Yes` |

## DetachableRiderUpdate

`sizeof(ModuleData)` = 0x28, 5 fields

| field | type | offset | default |
|---|---|---|---|
| `DeathEntry` | DeathEntry | `0x8` | `0` |
| `RemoveRiderlessFromHorde` | Bool | `0x25` | `No` |
| `RiderlessHordeFlees` | Bool | `0x24` | `No` |
| `RiderlessWeaponSlot` | LookupList | `0x20` | `0` |
| `RiderSubObjects` | AsciiStringList | `0x14` | `0` |

## DevastateSpecialPower

`sizeof(ModuleData)` = 0x90, 40 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `FireWeapon` | AsciiString | `0x8c` | `""` |
| `FX` | FXList | `0x80` | `0` |
| `GiveLevels` | Int | `0x58` | `0` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `Radius` | Real | `0x7c` | `0` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `TreeValueMultiplier` | Percent | `0x84` | `0` |
| `TreeValueTotalCap` | Real | `0x88` | `0` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## DoCommandUpgrade

`sizeof(ModuleData)` = 0x140, 8 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `GetUpgradeCommandButtonName` | AsciiString | `0x138` | `0` |
| `Permanent` | Bool | `0x12e` | - |
| `RemoveUpgradeCommandButtonName` | AsciiString | `0x13c` | `0` |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## DominateEnemySpecialPower

`sizeof(ModuleData)` = 0xe4, 65 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierAffects` | KindOfFilter | `0xe0` | - |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `DominatedFX` | FXList | `0xd8` | `0` |
| `DominateRadius` | Real | `0xd0` | `0` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PermanentlyConvert` | Bool | `0xdc` | `No` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerFX` | FXList | `0xd4` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |

## DozerAIUpdate

`sizeof(ModuleData)` = 0x70, 22 fields

| field | type | offset | default |
|---|---|---|---|
| `AILuaEventsList` | AsciiString | `0x2c` | `0` |
| `AttackPriority` | AsciiString | `0x44` | `"DefaultAttackPriority"` |
| `AutoAcquireEnemiesWhenIdle` | BitFlags | `0x1c` | `0` |
| `BoredRange` | Real | `0x6c` | `0` |
| `BoredTime` | DurationReal | `0x68` | `0` |
| `BurningDeathTime` | Duration | `0x40` | `0` |
| `CanAttackWhileContained` | Bool | `0x25` | `No` |
| `ComboLocoAttackDistance` | Real | `0x4c` | `80` |
| `ComboLocomotorSet` | Enum | `0x50` | `0` |
| `FadeOnPortals` | Bool | `0x54` | `No` |
| `HoldGroundCloseRangeDistance` | Real | `0x28` | `0` |
| `MaxCowerTime` | Duration | `0x30` | `0` |
| `MinCowerTime` | Duration | `0x34` | `0` |
| `MoodAttackCheckRate` | Duration | `0x18` | - |
| `RampageRequiresAflame` | Bool | `0x3c` | `No` |
| `RampageTime` | Duration | `0x38` | `0` |
| `RepairHealthPercentPerSecond` | Percent | `0x64` | `0` |
| `SpecialContactPoints` | AsciiStringList | `0x58` | `0` |
| `StandGround` | Bool | `0x24` | `No` |
| `StopChaseDistance` | Real | `0x20` | `500` |
| `TimeToEjectPassengersOnRampage` | Duration | `0x48` | `0` |
| `Turret` | 0x006620a2 | `0x14` | `0` |

## DualWeaponBehavior

`sizeof(ModuleData)` = 0x18, 5 fields

| field | type | offset | default |
|---|---|---|---|
| `MinimumSwitchTime` | Duration | `0x10` | `0` |
| `SwitchWeaponOnCloseRangeDistance` | Real | `0x8` | `0` |
| `UseCloseRangeWhileMounted` | Bool | `0xc` | `No` |
| `UseHordeRangeWeapon` | Bool | `0x14` | `No` |
| `UseRealVictimRange` | Bool | `0x15` | `No` |

## DynamicPortalBehaviour

`sizeof(ModuleData)` = 0x17c, 18 fields

| field | type | offset | default |
|---|---|---|---|
| `AboveWall` | Int | `0x160` | `-1` |
| `ActivationDelaySeconds` | Real | `0x174` | `0` |
| `AllowEnemies` | Bool | `0x15d` | `No` |
| `BonePrefix` | AsciiString | `0x13c` | - |
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `GenerateNow` | Bool | `0x15c` | `No` |
| `Link` | Link | `0x14c` | `0` |
| `NumberOfBones` | Int | `0x138` | `0` |
| `ObjectFilter` | KindOfFilter | `0x178` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TopAttackPos` | Coord3D | `0x164` | - |
| `TopAttackRadius` | Real | `0x170` | `5` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |
| `WallBoundsMesh` | AsciiString | `0x158` | `""` |
| `WayPoint` | WayPoint | `0x140` | - |

## DynamicShroudClearingRangeUpdate

`sizeof(ModuleData)` = 0x5c, 8 fields

| field | type | offset | default |
|---|---|---|---|
| `ChangeInterval` | Duration | `0x1c` | `0` |
| `FinalVision` | Real | `0x18` | `0` |
| `GridDecalTemplate` | GridDecalTemplate | `0x28` | - |
| `GrowDelay` | Duration | `0x10` | `0` |
| `GrowInterval` | Duration | `0x20` | `0` |
| `GrowTime` | Duration | `0x14` | `0` |
| `ShrinkDelay` | Duration | `0x8` | `0` |
| `ShrinkTime` | Duration | `0xc` | `0` |

## ElvenWoodSpecialPower

`sizeof(ModuleData)` = 0x9c, 41 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `ElvenGroveObject` | AsciiString | `0x88` | `0` |
| `ElvenNumObjects` | Int | `0x8c` | `0` |
| `ElvenWoodFX` | FXList | `0x94` | `0` |
| `ElvenWoodObject` | 0x008c81cd | `0x0` | - |
| `ElvenWoodOCL` | ObjectCreationList | `0x98` | `0` |
| `ElvenWoodRadius` | Real | `0x90` | `10` |
| `GiveLevels` | Int | `0x58` | `0` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## EmotionTrackerUpdate

`sizeof(ModuleData)` = 0x40, 12 fields

| field | type | offset | default |
|---|---|---|---|
| `AddEmotion` | AddEmotion | `0x0` | - |
| `AfraidOf` | KindOfFilter | `0x14` | - |
| `AlwaysAfraidOf` | KindOfFilter | `0x18` | `0` |
| `FearScanDistance` | Real | `0x24` | `0` |
| `HeroScanDistance` | Real | `0x20` | `0` |
| `IgnoreVeterancy` | Bool | `0x2c` | `No` |
| `ImmuneToFearLevel` | Int | `0x30` | `5` |
| `PointAt` | KindOfFilter | `0x1c` | `0` |
| `QuarrelProbability` | Percent | `0x28` | `0` |
| `TauntAndPointDistance` | Real | `0x8` | `0` |
| `TauntAndPointExcluded` | KindOfFilter | `0x10` | - |
| `TauntAndPointUpdateDelay` | Duration | `0xc` | `0` |

## EnragedBehavior

`sizeof(ModuleData)` = 0xc, 1 field

| field | type | offset | default |
|---|---|---|---|
| `EnragedLifeTimer` | Real | `0x8` | `99999` |

## EntEnragedUpdate

`sizeof(ModuleData)` = 0x30, 10 fields

| field | type | offset | default |
|---|---|---|---|
| `EnragedOffBuffFX` | FXList | `0x2c` | `0` |
| `EnragedOnBuffFX` | FXList | `0x28` | `0` |
| `EnragedTime` | Duration | `0xc` | `0` |
| `EnragedTransitionFX` | FXList | `0x24` | `0` |
| `EnragedTransitionTime` | Duration | `0x20` | `0` |
| `FriendlyDeadFilter` | KindOfFilter | `0x18` | - |
| `HatedObjectFilter` | KindOfFilter | `0x1c` | `0` |
| `ScanDelayTime` | Duration | `0x8` | - |
| `ScanDistance` | Real | `0x14` | `300` |
| `TimeUntilCanRageAgain` | Duration | `0x10` | `0` |

## EvaAnnounceClientCreate

`sizeof(ModuleData)` = 0x1c, 8 fields

| field | type | offset | default |
|---|---|---|---|
| `AnnouncementEventAlly` | EvaEvent | `0xc` | `-1` |
| `AnnouncementEventEnemy` | EvaEvent | `0x8` | `-1` |
| `AnnouncementEventOwner` | EvaEvent | `0x10` | `-1` |
| `CountAsFirstSightedAnnoucement` | Bool | `0x19` | `No` |
| `CreateFakeRadarEvent` | Bool | `0x1b` | `No` |
| `DelayBeforeAnnouncementMS` | Duration | `0x14` | `0` |
| `OnlyIfVisible` | Bool | `0x18` | `No` |
| `UseObjectsPosition` | Bool | `0x1a` | `No` |

## EvacuateDamage

`sizeof(ModuleData)` = 0x18, 4 fields

| field | type | offset | default |
|---|---|---|---|
| `DamageToPanicThreshold` | Percent | `0x10` | `0.1` |
| `DamageTypeToTrack` | Enum | `0xc` | `3` |
| `TrackingTimeSpan` | Duration | `0x14` | `6` |
| `WeaponThatCausesEvacuation` | 0x008bedf8 | `0x0` | `0` |

## EvacuateGarrisonSpecialPower

`sizeof(ModuleData)` = 0xd0, 60 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |

## ExperienceLevelCreate

`sizeof(ModuleData)` = 0x10, 2 fields

| field | type | offset | default |
|---|---|---|---|
| `LevelToGrant` | Int | `0x8` | `-1` |
| `MPOnly` | Bool | `0xc` | `No` |

## ExperienceScalarUpgrade

`sizeof(ModuleData)` = 0x13c, 7 fields

| field | type | offset | default |
|---|---|---|---|
| `AddXPScalar` | Real | `0x138` | `0` |
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## FadeAndDieOrnamentUpdate

`sizeof(ModuleData)` = 0x38, 3 fields

| field | type | offset | default |
|---|---|---|---|
| `AttachToTargetBone` | AsciiString | `0x8` | - |
| `Envelope` | OpacityEnvelope | `0xc` | - |
| `FollowTarget` | OpacityEnvelope | `0x34` | `1` |

## FakePathfindPortalBehaviour

`sizeof(ModuleData)` = 0x13c, 8 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowEnemies` | Bool | `0x138` | `No` |
| `AllowNonSkirmishAIUnits` | Bool | `0x139` | `No` |
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## FellBeastSwoopPower

`sizeof(ModuleData)` = 0xd8, 62 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `SpecialWeapon` | WeaponTemplate | `0xd0` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |
| `WhichSpecialWeapon` | Int | `0xd4` | `0` |

## FireSpreadUpdate

`sizeof(ModuleData)` = 0x18, 4 fields

| field | type | offset | default |
|---|---|---|---|
| `MaxSpreadDelay` | Duration | `0x10` | `0` |
| `MinSpreadDelay` | Duration | `0xc` | `0` |
| `OCLEmbers` | ObjectCreationList | `0x8` | `0` |
| `SpreadTryRange` | Real | `0x14` | `0` |

## FireWeaponCollide

`sizeof(ModuleData)` = 0x30, 4 fields

| field | type | offset | default |
|---|---|---|---|
| `CollideWeapon` | WeaponTemplate | `0x8` | `0` |
| `FireOnce` | Bool | `0x2c` | `No` |
| `ForbiddenStatus` | ObjectStatusFlags | `0x1c` | - |
| `RequiredStatus` | ObjectStatusFlags | `0xc` | - |

## FireWeaponUpdate

`sizeof(ModuleData)` = 0x10, 4 fields

| field | type | offset | default |
|---|---|---|---|
| `AliveOnly` | Bool | `0xe` | `No` |
| `ChargingModeTrigger` | Bool | `0xd` | `No` |
| `FireWeaponNugget` | FireWeaponNugget | `0x0` | - |
| `HeroModeTrigger` | Bool | `0xc` | `No` |

## FireWeaponWhenDamagedBehavior

`sizeof(ModuleData)` = 0x164, 17 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `ContinuousWeaponDamaged` | WeaponTemplate | `0x158` | `0` |
| `ContinuousWeaponPristine` | WeaponTemplate | `0x154` | `0` |
| `ContinuousWeaponReallyDamaged` | WeaponTemplate | `0x15c` | `0` |
| `ContinuousWeaponRubble` | WeaponTemplate | `0x160` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `DamageAmount` | Real | `0x140` | `0` |
| `DamageTypes` | DamageTypeFlags | `0x13c` | `-1` |
| `Permanent` | Bool | `0x12e` | - |
| `ReactionWeaponDamaged` | WeaponTemplate | `0x148` | `0` |
| `ReactionWeaponPristine` | WeaponTemplate | `0x144` | `0` |
| `ReactionWeaponReallyDamaged` | WeaponTemplate | `0x14c` | `0` |
| `ReactionWeaponRubble` | WeaponTemplate | `0x150` | `0` |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `StartsActive` | Bool | `0x138` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## FireWeaponWhenDeadBehavior

`sizeof(ModuleData)` = 0x180, 17 fields

| field | type | offset | default |
|---|---|---|---|
| `ActiveDuringConstruction` | Bool | `0x139` | `No` |
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DeathWeapon` | WeaponTemplate | `0x17c` | `0` |
| `DelayTime` | Duration | `0x13c` | `0` |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | - |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `StartsActive` | Bool | `0x138` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |
| `WeaponOffset` | Coord3D | `0x140` | - |

## FlammableUpdate

`sizeof(ModuleData)` = 0x58, 21 fields

| field | type | offset | default |
|---|---|---|---|
| `AflameDamageAmount` | Int | `0x14` | `0` |
| `AflameDamageDelay` | Duration | `0x10` | `0` |
| `AflameDuration` | Duration | `0xc` | `0` |
| `BurnContained` | Bool | `0x39` | `No` |
| `BurnedDelay` | Duration | `0x8` | `0` |
| `BurningSoundName` | AudioEventRTS | `0x18` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x4c` | `-1` |
| `DamageType` | Enum | `0x24` | `6` |
| `FireFXList` | 0x00890cd9 | `0x0` | - |
| `FlameDamageExpiration` | Duration | `0x20` | - |
| `FlameDamageLimit` | Real | `0x1c` | `20` |
| `PanicLocomotorWhileAflame` | Bool | `0x48` | `No` |
| `RunToWater` | Bool | `0x3a` | `No` |
| `RunToWaterDepth` | Real | `0x3c` | `0` |
| `RunToWaterSearchIncrement` | Real | `0x44` | `60` |
| `RunToWaterSearchRadius` | Real | `0x40` | `200` |
| `SetBurnedStatus` | Bool | `0x34` | `Yes` |
| `SwapModelWhenAflame` | Bool | `0x35` | `No` |
| `SwapModelWhenQuenched` | Bool | `0x36` | `No` |
| `SwapTextureWhenAflame` | Bool | `0x37` | `No` |
| `SwapTextureWhenQuenhed` | Bool | `0x38` | `No` |

## FlingPassengerSpecialAbilityUpdate

`sizeof(ModuleData)` = 0xe0, 62 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlingPassengerLandingWarhead` | WeaponTemplate | `0xdc` | `0` |
| `FlingPassengerVelocity` | Coord3D | `0xd0` | - |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |

## FloatUpdate

`sizeof(ModuleData)` = 0xc, 1 field

| field | type | offset | default |
|---|---|---|---|
| `Enabled` | Bool | `0x8` | `No` |

## FloodUpdate

`sizeof(ModuleData)` = 0x14, 3 fields

| field | type | offset | default |
|---|---|---|---|
| `AngleOfFlow` | AngleReal | `0xc` | - |
| `DirectionIsRelative` | Bool | `0x10` | - |
| `FloodMember` | FloodMember | `0x0` | - |

## FoundationAIUpdate

`sizeof(ModuleData)` = 0x10, 2 fields

| field | type | offset | default |
|---|---|---|---|
| `BuildVariation` | Int | `0xc` | - |
| `RepairHealthPercentPerSecond` | Percent | `0x8` | - |

## FreeLifeBody

`sizeof(ModuleData)` = 0x88, 28 fields

| field | type | offset | default |
|---|---|---|---|
| `BurningDeathBehavior` | Bool | `0x51` | `No` |
| `BurningDeathFX` | FXList | `0x54` | `0` |
| `CanRespawn` | Bool | `0x68` | `Yes` |
| `CheerRadius` | Real | `0x4c` | `200` |
| `DamageCreationList` | DamageCreationList | `0x0` | - |
| `DamagedAttributeModifier` | AsciiString | `0x30` | `0` |
| `DodgePercent` | Percent | `0x18` | `0` |
| `EnteringDamagedTransitionTime` | Duration | `0x1c` | `0` |
| `EnteringReallyDamagedTransitionTime` | Duration | `0x20` | `0` |
| `FreeLifeAnimAndDuration` | AnimAndDuration | `0x78` | - |
| `FreeLifeHealthPercent` | Percent | `0x6c` | `0` |
| `FreeLifeInvincible` | Bool | `0x74` | `No` |
| `FreeLifePrerequisiteUpgrade` | UpgradeTemplate | `0x84` | `0` |
| `FreeLifeTime` | Duration | `0x70` | `0` |
| `GrabDamage` | Real | `0x3c` | `200` |
| `GrabFX` | FXList | `0x38` | `0` |
| `GrabObject` | AsciiString | `0x2c` | - |
| `GrabOffset` | Coord3D | `0x40` | `0` |
| `HealingBuffFx` | FXList | `0x48` | - |
| `InitialHealth` | Real | `0xc` | `-1` |
| `MaxHealth` | Real | `0x8` | `0` |
| `MaxHealthDamaged` | Real | `0x10` | `0` |
| `MaxHealthReallyDamaged` | Real | `0x14` | `0` |
| `PermanentlyKilledByFilter` | KindOfFilter | `0x64` | - |
| `ReallyDamagedAttributeModifier` | AsciiString | `0x34` | `0` |
| `RecoveryTime` | Duration | `0x24` | `0` |
| `RemoveUpgradesOnDeath` | Bool | `0x50` | `No` |
| `UseDefaultDamageSettings` | Bool | `0x28` | `Yes` |

## FreezingRainSpecialPower

`sizeof(ModuleData)` = 0x88, 38 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `BurnRateModifier` | Int | `0x84` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `FreezingRainFX` | FXList | `0x80` | `0` |
| `FreezingRainRadius` | Real | `0x7c` | `10` |
| `GiveLevels` | Int | `0x58` | `0` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## FXListDie

`sizeof(ModuleData)` = 0x40, 8 fields

| field | type | offset | default |
|---|---|---|---|
| `DamageAmountRequired` | Real | `0x24` | - |
| `DeathFX` | FXList | `0x38` | `0` |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `OrientToObject` | Bool | `0x3c` | `Yes` |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |

## GarrisonContain

`sizeof(ModuleData)` = 0xac, 35 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowAlliesInside` | Bool | `0x7d` | `No` |
| `AllowEnemiesInside` | Bool | `0x7e` | `No` |
| `AllowNeutralInside` | Bool | `0x7f` | `No` |
| `AllowOwnPlayerInsideOverride` | Bool | `0x7c` | `No` |
| `BoneSpecificConditionState` | 0x008678eb | `0x0` | - |
| `CollidePickup` | Bool | `0x81` | `No` |
| `ContainMax` | Int | `0x70` | `-1` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DamagePercentToUnits` | Percent | `0x6c` | `0` |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DoorOpenTime` | Duration | `0x78` | `0` |
| `EjectPassengersOnDeath` | Bool | `0x82` | `No` |
| `Enabled` | Bool | `0x84` | `No` |
| `EnterSound` | AudioEventRTS | `0x38` | `0` |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `ExitSound` | AudioEventRTS | `0x3c` | `0` |
| `HealObjects` | Bool | `0x98` | `No` |
| `ImmuneToClearBuildingAttacks` | Bool | `0xa1` | `No` |
| `InitialRoster` | 0x00653381 | `0x0` | - |
| `KillPassengersOnDeath` | Bool | `0x83` | `No` |
| `ManualPickUpFilter` | KindOfFilter | `0x44` | `0` |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `MobileGarrison` | Bool | `0xa0` | `No` |
| `ModifierRequiredTime` | Duration | `0x94` | `100` |
| `ModifierToGiveOnExit` | AsciiStringList | `0x88` | - |
| `NumberOfExitPaths` | Int | `0x74` | `0` |
| `ObjectStatusOfContained` | ObjectStatusFlags | `0x58` | `0` |
| `PassengerBonePrefix` | PassengerBonePrefix | `0x0` | - |
| `PassengerFilter` | KindOfFilter | `0x40` | - |
| `PassengersInTurret` | Bool | `0x85` | `No` |
| `PassengersTestCollisionHeight` | Real | `0x68` | `-1000` |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `ShowPips` | Bool | `0x80` | `No` |
| `TimeForFullHeal` | DurationReal | `0x9c` | `1` |

## GarrisonUpgrade

`sizeof(ModuleData)` = 0x138, 6 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## GateOpenAndCloseBehavior

`sizeof(ModuleData)` = 0x4c, 13 fields

| field | type | offset | default |
|---|---|---|---|
| `GeometryForClosed` | AsciiStringList | `0x38` | - |
| `GeometryForOpen` | AsciiStringList | `0x2c` | - |
| `OpenByDefault` | Bool | `0x8` | `No` |
| `PercentOpenForPathing` | Int | `0x10` | `0` |
| `Proxy` | AsciiString | `0x14` | `0` |
| `RepelCollidingUnits` | Bool | `0x18` | `Yes` |
| `ResetTimeInMilliseconds` | Duration | `0xc` | `0` |
| `SoundClosingGateLoop` | AudioEventRTS | `0x24` | `0` |
| `SoundFinishedClosingGate` | AudioEventRTS | `0x28` | `0` |
| `SoundFinishedOpeningGate` | AudioEventRTS | `0x20` | `0` |
| `SoundOpeningGateLoop` | AudioEventRTS | `0x1c` | `0` |
| `TimeBeforePlayingClosedSound` | Duration | `0x48` | - |
| `TimeBeforePlayingOpenSound` | Duration | `0x44` | - |

## GateProxyBehavior

`sizeof(ModuleData)` = 0x4c, 13 fields

| field | type | offset | default |
|---|---|---|---|
| `GeometryForClosed` | AsciiStringList | `0x38` | - |
| `GeometryForOpen` | AsciiStringList | `0x2c` | - |
| `OpenByDefault` | Bool | `0x8` | `No` |
| `PercentOpenForPathing` | Int | `0x10` | `0` |
| `Proxy` | AsciiString | `0x14` | `0` |
| `RepelCollidingUnits` | Bool | `0x18` | `Yes` |
| `ResetTimeInMilliseconds` | Duration | `0xc` | `0` |
| `SoundClosingGateLoop` | AudioEventRTS | `0x24` | `0` |
| `SoundFinishedClosingGate` | AudioEventRTS | `0x28` | `0` |
| `SoundFinishedOpeningGate` | AudioEventRTS | `0x20` | `0` |
| `SoundOpeningGateLoop` | AudioEventRTS | `0x1c` | `0` |
| `TimeBeforePlayingClosedSound` | Duration | `0x48` | - |
| `TimeBeforePlayingOpenSound` | Duration | `0x44` | - |

## GeometryUpgrade

`sizeof(ModuleData)` = 0x15c, 11 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `HideGeometry` | AsciiStringList | `0x144` | `0` |
| `Permanent` | Bool | `0x12e` | - |
| `RampMesh1` | AsciiString | `0x154` | - |
| `RampMesh2` | AsciiString | `0x158` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `ShowGeometry` | AsciiStringList | `0x138` | `0` |
| `TriggeredBy` | UpgradeMask | `0x0` | `0` |
| `WallBoundsMesh` | AsciiString | `0x150` | - |

## GettingBuiltBehavior

`sizeof(ModuleData)` = 0x4c, 17 fields

| field | type | offset | default |
|---|---|---|---|
| `DisallowRebuildFilter` | KindOfFilter | `0x40` | - |
| `DisallowRebuildRange` | Real | `0x44` | `0` |
| `EvilWorkerName` | AsciiString | `0x18` | `""` |
| `HealWeapon` | WeaponTemplate | `0x28` | `0` |
| `PercentOfBuildCostToRebuildDamaged` | Percent | `0x34` | `0.5` |
| `PercentOfBuildCostToRebuildPristine` | Percent | `0x30` | `0.25` |
| `PercentOfBuildCostToRebuildReallyDamaged` | Percent | `0x38` | `0.75` |
| `PercentOfBuildCostToRebuildRubble` | Percent | `0x3c` | `1` |
| `RebuildTimeSeconds` | Real | `0x24` | `60` |
| `RebuildWhenDead` | Bool | `0x2c` | `No` |
| `SelfBuildingLoop` | AudioEventRTS | `0x8` | `0` |
| `SelfRepairFromDamageLoop` | AudioEventRTS | `0xc` | `0` |
| `SelfRepairFromRubbleLoop` | AudioEventRTS | `0x10` | `0` |
| `SpawnTimer` | Real | `0x20` | `30` |
| `TestFaction` | Bool | `0x1c` | `No` |
| `UseSpawnTimerWithoutWorker` | Bool | `0x48` | `No` |
| `WorkerName` | AsciiString | `0x14` | `""` |

## GiantBirdAIUpdate

`sizeof(ModuleData)` = 0x84, 27 fields

| field | type | offset | default |
|---|---|---|---|
| `AILuaEventsList` | AsciiString | `0x2c` | `0` |
| `AttackLocomotorType` | Enum | `0x64` | `0` |
| `AttackPriority` | AsciiString | `0x44` | `"DefaultAttackPriority"` |
| `AutoAcquireEnemiesWhenIdle` | BitFlags | `0x1c` | `0` |
| `BurningDeathTime` | Duration | `0x40` | `0` |
| `CanAttackWhileContained` | Bool | `0x25` | `No` |
| `ComboLocoAttackDistance` | Real | `0x4c` | `80` |
| `ComboLocomotorSet` | Enum | `0x50` | `0` |
| `FadeOnPortals` | Bool | `0x54` | `No` |
| `FollowThroughCheckStep` | Real | `0x78` | `10` |
| `FollowThroughDistance` | Real | `0x74` | `100` |
| `FollowThroughGradient` | Real | `0x7c` | `1` |
| `GrabTossHeightTrigger` | Real | `0x70` | `0` |
| `GrabTossTimeTrigger` | Real | `0x6c` | `0` |
| `HoldGroundCloseRangeDistance` | Real | `0x28` | `0` |
| `MaxCowerTime` | Duration | `0x30` | `0` |
| `MinCowerTime` | Duration | `0x34` | `0` |
| `MoodAttackCheckRate` | Duration | `0x18` | - |
| `RampageRequiresAflame` | Bool | `0x3c` | `No` |
| `RampageTime` | Duration | `0x38` | `0` |
| `ReturnForAmmoLocomotorType` | Enum | `0x68` | `0` |
| `SpecialContactPoints` | AsciiStringList | `0x58` | `0` |
| `StandGround` | Bool | `0x24` | `No` |
| `StopChaseDistance` | Real | `0x20` | `500` |
| `TimeToEjectPassengersOnRampage` | Duration | `0x48` | `0` |
| `TossFX` | FXList | `0x80` | `0` |
| `Turret` | 0x006620a2 | `0x14` | `0` |

## GiantBirdSlowDeathBehavior

`sizeof(ModuleData)` = 0x1c4, 34 fields

| field | type | offset | default |
|---|---|---|---|
| `CrashAvoidKindOfs` | KindOfFlags | `0x19c` | - |
| `CrashAvoidRadius` | Real | `0x1b8` | `800` |
| `CrashAvoidStrength` | Real | `0x1bc` | `0.1` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DeathFlags` | 0x008612e7 | `0x0` | - |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DecayBeginTime` | Duration | `0x54` | `0` |
| `DelayFromGroundToFinalDeath` | DurationReal | `0x198` | `0` |
| `DestructionDelay` | Duration | `0x4c` | `0` |
| `DestructionDelayVariance` | Duration | `0x50` | `0` |
| `DoNotRandomizeMidpoint` | Bool | `0x18e` | `No` |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `FadeDelay` | Duration | `0x188` | `4207599104` |
| `FadeTime` | Duration | `0x184` | `6` |
| `FlingForce` | Real | `0x118` | `0` |
| `FlingForceVariance` | Real | `0x11c` | `0` |
| `FlingPitch` | AngleReal | `0x120` | `0` |
| `FlingPitchVariance` | AngleReal | `0x124` | `0` |
| `FX` | MomentFXList | `0x0` | - |
| `FXHitGround` | FXList | `0x190` | `0` |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `ModifierBonusPerOverkillPercent` | Percent | `0x40` | `0` |
| `NeedToMaintainFlailingHeight` | Bool | `0x1c0` | `No` |
| `OCL` | MomentOCL | `0x0` | - |
| `OCLHitGround` | ObjectCreationList | `0x194` | `0` |
| `ProbabilityModifier` | Int | `0x3c` | `10` |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `ShadowWhenDead` | Bool | `0x18d` | `No` |
| `SinkDelay` | Duration | `0x44` | `0` |
| `SinkDelayVariance` | Duration | `0x48` | `0` |
| `SinkRate` | VelocityReal | `0x38` | `0` |
| `Sound` | MomentSound | `0x0` | - |
| `Weapon` | MomentWeapon | `0x0` | - |

## GiveOrRestoreUpgradeSpecialPower

`sizeof(ModuleData)` = 0xe8, 63 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `CommandButton` | AsciiString | `0xd0` | `0` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FlagsUsedForToggle` | WeaponSetFlags | `0xd8` | - |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |
| `UpgradeToGive` | AsciiString | `0xd4` | `0` |

## GiveUpgradeUpdate

`sizeof(ModuleData)` = 0xec, 64 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DeliverUpgrade` | Bool | `0xe8` | `No` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FadeOutSpeed` | Real | `0xe4` | `0.025` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GiveUpgradeEffect` | FXList | `0xdc` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpawnOutFX` | FXList | `0xe0` | `0` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |

## GloriousChargeUpdate

`sizeof(ModuleData)` = 0xdc, 63 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `BonusRadius` | Real | `0xd0` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `SpeechDuration` | Duration | `0xd4` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |
| `UpdateInterval` | Duration | `0xd8` | `0` |

## GrabPassengerSpecialPower

`sizeof(ModuleData)` = 0x84, 37 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AllowTree` | Bool | `0x80` | `Yes` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `GiveLevels` | Int | `0x58` | `0` |
| `GrabRadius` | Real | `0x7c` | `0` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## GrantUpgradeCreate

`sizeof(ModuleData)` = 0x20, 3 fields

| field | type | offset | default |
|---|---|---|---|
| `ExemptStatus` | ObjectStatusFlags | `0xc` | - |
| `GiveOnBuildComplete` | Bool | `0x1c` | `No` |
| `UpgradeToGrant` | AsciiString | `0x8` | - |

## HealContain

`sizeof(ModuleData)` = 0x9c, 31 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowAlliesInside` | Bool | `0x7d` | `No` |
| `AllowEnemiesInside` | Bool | `0x7e` | `No` |
| `AllowNeutralInside` | Bool | `0x7f` | `No` |
| `AllowOwnPlayerInsideOverride` | Bool | `0x7c` | `No` |
| `BoneSpecificConditionState` | 0x008678eb | `0x0` | - |
| `CollidePickup` | Bool | `0x81` | `No` |
| `ContainMax` | Int | `0x70` | `-1` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DamagePercentToUnits` | Percent | `0x6c` | `0` |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DoorOpenTime` | Duration | `0x78` | `0` |
| `EjectPassengersOnDeath` | Bool | `0x82` | `No` |
| `Enabled` | Bool | `0x84` | `No` |
| `EnterSound` | AudioEventRTS | `0x38` | `0` |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `ExitSound` | AudioEventRTS | `0x3c` | `0` |
| `KillPassengersOnDeath` | Bool | `0x83` | `No` |
| `ManualPickUpFilter` | KindOfFilter | `0x44` | `0` |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `ModifierRequiredTime` | Duration | `0x94` | `100` |
| `ModifierToGiveOnExit` | AsciiStringList | `0x88` | - |
| `NumberOfExitPaths` | Int | `0x74` | `0` |
| `ObjectStatusOfContained` | ObjectStatusFlags | `0x58` | `0` |
| `PassengerBonePrefix` | PassengerBonePrefix | `0x0` | - |
| `PassengerFilter` | KindOfFilter | `0x40` | - |
| `PassengersInTurret` | Bool | `0x85` | `No` |
| `PassengersTestCollisionHeight` | Real | `0x68` | `-1000` |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `ShowPips` | Bool | `0x80` | `No` |
| `TimeForFullHeal` | Duration | `0x98` | `0` |

## HealCrateCollide

`sizeof(ModuleData)` = 0x5c, 11 fields

| field | type | offset | default |
|---|---|---|---|
| `BuildingPickup` | Bool | `0x41` | `No` |
| `ExecuteAnimation` | AsciiString | `0x4c` | - |
| `ExecuteAnimationFades` | Bool | `0x58` | `Yes` |
| `ExecuteAnimationTime` | Real | `0x50` | `0` |
| `ExecuteAnimationZRise` | Real | `0x54` | `0` |
| `ExecuteFX` | FXList | `0x48` | `0` |
| `ForbiddenKindOf` | KindOfFlags | `0x24` | - |
| `ForbidOwnerPlayer` | Bool | `0x40` | `No` |
| `HumanOnly` | Bool | `0x42` | `No` |
| `PickupScience` | ScienceType | `0x44` | `-1` |
| `RequiredKindOf` | KindOfFlags | `0x8` | - |

## HeightDieUpdate

`sizeof(ModuleData)` = 0x1c, 6 fields

| field | type | offset | default |
|---|---|---|---|
| `DestroyAttachedParticlesAtHeight` | Real | `0x10` | `-1` |
| `InitialDelay` | Duration | `0x18` | `0` |
| `OnlyWhenMovingDown` | Bool | `0xd` | `No` |
| `SnapToGroundOnDeath` | Bool | `0x14` | `No` |
| `TargetHeight` | Real | `0x8` | `0` |
| `TargetHeightIncludesStructures` | Bool | `0xc` | `No` |

## HeroDie

`sizeof(ModuleData)` = 0x3c, 7 fields

| field | type | offset | default |
|---|---|---|---|
| `DamageAmountRequired` | Real | `0x24` | - |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |

## HeroModeSpecialAbilityUpdate

`sizeof(ModuleData)` = 0xdc, 64 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `HeroAttributeModifier` | AsciiString | `0xd0` | `""` |
| `HeroEffectDuration` | Duration | `0xd4` | `0` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `StopUnitBeforeActivating` | Bool | `0xd9` | `No` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |
| `UseUSERModelcondition` | Bool | `0xd8` | `No` |

## HighlanderBody

`sizeof(ModuleData)` = 0x64, 21 fields

| field | type | offset | default |
|---|---|---|---|
| `BurningDeathBehavior` | Bool | `0x51` | `No` |
| `BurningDeathFX` | FXList | `0x54` | `0` |
| `CheerRadius` | Real | `0x4c` | `200` |
| `DamageCreationList` | DamageCreationList | `0x0` | - |
| `DamagedAttributeModifier` | AsciiString | `0x30` | `0` |
| `DodgePercent` | Percent | `0x18` | `0` |
| `EnteringDamagedTransitionTime` | Duration | `0x1c` | `0` |
| `EnteringReallyDamagedTransitionTime` | Duration | `0x20` | `0` |
| `GrabDamage` | Real | `0x3c` | `200` |
| `GrabFX` | FXList | `0x38` | `0` |
| `GrabObject` | AsciiString | `0x2c` | - |
| `GrabOffset` | Coord3D | `0x40` | `0` |
| `HealingBuffFx` | FXList | `0x48` | - |
| `InitialHealth` | Real | `0xc` | `-1` |
| `MaxHealth` | Real | `0x8` | `0` |
| `MaxHealthDamaged` | Real | `0x10` | `0` |
| `MaxHealthReallyDamaged` | Real | `0x14` | `0` |
| `ReallyDamagedAttributeModifier` | AsciiString | `0x34` | `0` |
| `RecoveryTime` | Duration | `0x24` | `0` |
| `RemoveUpgradesOnDeath` | Bool | `0x50` | `No` |
| `UseDefaultDamageSettings` | Bool | `0x28` | `Yes` |

## HijackerUpdate

`sizeof(ModuleData)` = 0x10, 2 fields

| field | type | offset | default |
|---|---|---|---|
| `AttachToTargetBone` | AsciiString | `0x8` | - |
| `ParachuteName` | AsciiString | `0xc` | - |

## HitReactionBehavior

`sizeof(ModuleData)` = 0x24, 8 fields

| field | type | offset | default |
|---|---|---|---|
| `FastHitsResetReaction` | Bool | `0x20` | `No` |
| `HitReactionLifeTimer1` | Duration | `0x8` | - |
| `HitReactionLifeTimer2` | Duration | `0xc` | - |
| `HitReactionLifeTimer3` | Duration | `0x10` | - |
| `HitReactionThreshold1` | Real | `0x14` | - |
| `HitReactionThreshold2` | Real | `0x18` | - |
| `HitReactionThreshold3` | Real | `0x1c` | - |
| `HitsParalyze` | Bool | `0x21` | `No` |

## HordeAIUpdate

`sizeof(ModuleData)` = 0x64, 19 fields

| field | type | offset | default |
|---|---|---|---|
| `AILuaEventsList` | AsciiString | `0x2c` | `0` |
| `AttackPriority` | AsciiString | `0x44` | `"DefaultAttackPriority"` |
| `AutoAcquireEnemiesWhenIdle` | BitFlags | `0x1c` | `0` |
| `BurningDeathTime` | Duration | `0x40` | `0` |
| `CanAttackWhileContained` | Bool | `0x25` | `No` |
| `ComboLocoAttackDistance` | Real | `0x4c` | `80` |
| `ComboLocomotorSet` | Enum | `0x50` | `0` |
| `FadeOnPortals` | Bool | `0x54` | `No` |
| `HoldGroundCloseRangeDistance` | Real | `0x28` | `0` |
| `MaxCowerTime` | Duration | `0x30` | `0` |
| `MinCowerTime` | Duration | `0x34` | `0` |
| `MoodAttackCheckRate` | Duration | `0x18` | - |
| `RampageRequiresAflame` | Bool | `0x3c` | `No` |
| `RampageTime` | Duration | `0x38` | `0` |
| `SpecialContactPoints` | AsciiStringList | `0x58` | `0` |
| `StandGround` | Bool | `0x24` | `No` |
| `StopChaseDistance` | Real | `0x20` | `500` |
| `TimeToEjectPassengersOnRampage` | Duration | `0x48` | `0` |
| `Turret` | 0x006620a2 | `0x14` | `0` |

## HordeContain

`sizeof(ModuleData)` = 0x284, 106 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowAlliesInside` | Bool | `0x7d` | `No` |
| `AllowEnemiesInside` | Bool | `0x7e` | `No` |
| `AllowNeutralInside` | Bool | `0x7f` | `No` |
| `AllowOwnPlayerInsideOverride` | Bool | `0x7c` | `No` |
| `AlternateFormation` | AsciiString | `0x1b0` | `0` |
| `AttributeModifiers` | AsciiStringList | `0x22c` | `0` |
| `BackUpMaxDelayTime` | Duration | `0x1e0` | - |
| `BackUpMaxDistance` | Real | `0x1e8` | `5` |
| `BackUpMinDelayTime` | Duration | `0x1dc` | - |
| `BackUpMinDistance` | Real | `0x1e4` | `3` |
| `BackupPercentage` | Percent | `0x1ec` | `0.5` |
| `BannerCarrierDestroyHordeOnDeath` | Bool | `0x224` | `No` |
| `BannerCarrierHordeDeathType` | DeathTypeFlags | `0x228` | `0` |
| `BannerCarrierMinLevel` | UInt8 | `0x27c` | `1` |
| `BannerCarrierPosition` | BannerCarrierPosition | `0x20c` | `0` |
| `BannerCarriersAllowed` | AsciiStringList | `0x218` | `0` |
| `BoneSpecificConditionState` | 0x008678eb | `0x0` | - |
| `CanGrabStructure` | Bool | `0x13d` | `No` |
| `CollidePickup` | Bool | `0x81` | `No` |
| `ComboHorde` | ComboHorde | `0x198` | `0` |
| `ConditionForEntry` | ModelConditionFlag | `0x14c` | `-1` |
| `ContainMax` | Int | `0x70` | `-1` |
| `CowerRadius` | Real | `0x1f0` | `0` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DamagePercentToUnits` | Percent | `0x6c` | `0` |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DestroyRidersWhoAreNotFreeToExit` | Bool | `0x142` | `No` |
| `DoorOpenTime` | Duration | `0x78` | `0` |
| `EjectPassengersOnDeath` | Bool | `0x82` | `No` |
| `Enabled` | Bool | `0x84` | `No` |
| `EnterFadeTime` | Real | `0x170` | `0` |
| `EnterSound` | AudioEventRTS | `0x38` | `0` |
| `EvaEventLastMemberDeath` | EvaEvent | `0x250` | `-1` |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `ExitBone` | AsciiString | `0xa0` | `0` |
| `ExitDelay` | Duration | `0xac` | `0` |
| `ExitFadeTime` | Real | `0x174` | `0` |
| `ExitPitchRate` | AngularVelocityReal | `0x9c` | `0` |
| `ExitSound` | AudioEventRTS | `0x3c` | `0` |
| `FadeFilter` | KindOfFilter | `0x168` | - |
| `FadePassengerOnEnter` | Bool | `0x16c` | `No` |
| `FadePassengerOnExit` | Bool | `0x16d` | `No` |
| `FadeReverse` | Bool | `0x178` | `No` |
| `FireGrabWeaponOnVictim` | Bool | `0x148` | `Yes` |
| `FlankedDelay` | Duration | `0x268` | `0` |
| `FlankedDuration` | Duration | `0x26c` | - |
| `ForcedLocomotorSet` | Enum | `0x23c` | `-1` |
| `ForceOrientationContainer` | Bool | `0x13c` | `Yes` |
| `FrontAngle` | Real | `0x264` | `360` |
| `GoAggressiveOnExit` | Bool | `0x140` | `No` |
| `GrabWeapon` | WeaponTemplate | `0x144` | `0` |
| `HealthRegen%PerSec` | Real | `0xa8` | `0` |
| `InitialPayload` | 0x0086af0a | `0x0` | - |
| `IsPorcupineFormation` | Bool | `0x238` | `No` |
| `KillPassengersOnDeath` | Bool | `0x83` | `No` |
| `LeaderPosition` | Coord3D | `0x200` | - |
| `LeaderRank` | Int | `0x208` | `0` |
| `LeadersAllowed` | AsciiStringList | `0x1f4` | `0` |
| `LivingWorldOverloadTemplate` | AsciiString | `0x280` | `0` |
| `MachineAllowed` | Bool | `0x240` | `No` |
| `MachineType` | AsciiString | `0x244` | `0` |
| `ManualPickUpFilter` | KindOfFilter | `0x44` | `0` |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MeleeAttackLeashDistance` | Real | `0x24c` | `60` |
| `MeleeBehavior` | MeleeBehavior | `0x260` | `0` |
| `MinimumHordeSize` | Int | `0x270` | `0` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `ModifierRequiredTime` | Duration | `0x94` | `100` |
| `ModifierToGiveOnExit` | AsciiStringList | `0x88` | - |
| `NotComboFormation` | Bool | `0x25c` | `No` |
| `NumberOfExitPaths` | Int | `0x74` | `0` |
| `ObjectStatusOfContained` | ObjectStatusFlags | `0x58` | `0` |
| `OrientLikeContainerOnExit` | Bool | `0x13f` | `No` |
| `PassengerBonePrefix` | PassengerBonePrefix | `0x0` | - |
| `PassengerFilter` | KindOfFilter | `0x40` | - |
| `PassengersInTurret` | Bool | `0x85` | `No` |
| `PassengersTestCollisionHeight` | Real | `0x68` | `-1000` |
| `RandomOffset` | Coord3D | `0x1d0` | - |
| `RankInfo` | RankInfo | `0x18c` | `0` |
| `RankSplit` | Bool | `0x254` | `No` |
| `RanksThatStopAdvance` | 0x0086df0b | `0x1b4` | - |
| `RanksToJustFreeWhenAttacking` | 0x0086ded1 | `0x1c4` | - |
| `RanksToReleaseWhenAttacking` | 0x0086ded1 | `0x1b8` | - |
| `ReleaseSnappyness` | Real | `0x17c` | `0.7` |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `ResetMoodCheckTimeOnExit` | Bool | `0x141` | `Yes` |
| `ScatterNearbyOnExit` | Bool | `0x13e` | `Yes` |
| `ShouldThrowOutPassengers` | Bool | `0x150` | `No` |
| `ShowPips` | Bool | `0x80` | `No` |
| `Slots` | Int | `0x98` | `0` |
| `SplitHorde` | SplitHorde | `0x1a4` | `0` |
| `SplitHordeNumber` | Int | `0x258` | `0` |
| `ThisFormationIsTheMainFormation` | Bool | `0x1d8` | `Yes` |
| `ThrowOutPassengersDelay` | Duration | `0x154` | `0` |
| `ThrowOutPassengersLandingWarhead` | WeaponTemplate | `0x164` | `0` |
| `ThrowOutPassengersVelocity` | Coord3D | `0x158` | - |
| `TypeOneForWeaponSet` | KindOfFlags | `0xb0` | - |
| `TypeOneForWeaponState` | KindOfFlags | `0xe8` | - |
| `TypeThreeForWeaponState` | KindOfFlags | `0x120` | - |
| `TypeTwoForWeaponSet` | KindOfFlags | `0xcc` | `0` |
| `TypeTwoForWeaponState` | KindOfFlags | `0x104` | - |
| `UpgradeCreationTrigger` | 0x0086ba2c | `0x0` | - |
| `UseMarchingAnims` | Bool | `0x25d` | `No` |
| `UseSlowHordeMovement` | Bool | `0x248` | `Yes` |
| `VisionRearOverride` | Percent | `0x274` | `0` |
| `VisionSideOverride` | Percent | `0x278` | `0` |

## HordeDispatchSpecialPower

`sizeof(ModuleData)` = 0x7c, 35 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `GiveLevels` | Int | `0x58` | `0` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## HordeGarrisonContain

`sizeof(ModuleData)` = 0xd4, 39 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowAlliesInside` | Bool | `0x7d` | `No` |
| `AllowEnemiesInside` | Bool | `0x7e` | `No` |
| `AllowNeutralInside` | Bool | `0x7f` | `No` |
| `AllowOwnPlayerInsideOverride` | Bool | `0x7c` | `No` |
| `BoneSpecificConditionState` | 0x008678eb | `0x0` | - |
| `CollidePickup` | Bool | `0x81` | `No` |
| `ContainMax` | Int | `0x70` | `-1` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DamagePercentToUnits` | Percent | `0x6c` | `0` |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DoorOpenTime` | Duration | `0x78` | `0` |
| `EjectPassengersOnDeath` | Bool | `0x82` | `No` |
| `Enabled` | Bool | `0x84` | `No` |
| `EnterSound` | AudioEventRTS | `0x38` | `0` |
| `EntryOffset` | Coord3D | `0xb0` | - |
| `EntryPosition` | Coord3D | `0xbc` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `ExitDelay` | Duration | `0xac` | `0` |
| `ExitOffset` | Coord3D | `0xc8` | `1` |
| `ExitSound` | AudioEventRTS | `0x3c` | `0` |
| `HealObjects` | Bool | `0x98` | `No` |
| `ImmuneToClearBuildingAttacks` | Bool | `0xa1` | `No` |
| `InitialRoster` | 0x00653381 | `0x0` | - |
| `KillPassengersOnDeath` | Bool | `0x83` | `No` |
| `ManualPickUpFilter` | KindOfFilter | `0x44` | `0` |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `MobileGarrison` | Bool | `0xa0` | `No` |
| `ModifierRequiredTime` | Duration | `0x94` | `100` |
| `ModifierToGiveOnExit` | AsciiStringList | `0x88` | - |
| `NumberOfExitPaths` | Int | `0x74` | `0` |
| `ObjectStatusOfContained` | ObjectStatusFlags | `0x58` | `0` |
| `PassengerBonePrefix` | PassengerBonePrefix | `0x0` | - |
| `PassengerFilter` | KindOfFilter | `0x40` | - |
| `PassengersInTurret` | Bool | `0x85` | `No` |
| `PassengersTestCollisionHeight` | Real | `0x68` | `-1000` |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `ShowPips` | Bool | `0x80` | `No` |
| `TimeForFullHeal` | DurationReal | `0x9c` | `1` |

## HordeNotifyTargetsOfImminentProbableCrushingUpdate

`sizeof(ModuleData)` = 0x18, 4 fields

| field | type | offset | default |
|---|---|---|---|
| `ScanAheadTimeMS` | Duration | `0x4` | - |
| `ScanHeight` | Real | `0x8` | - |
| `ScanWidth` | Real | `0xc` | - |
| `TimeBetweenUpdatesMS` | Duration | `0x0` | - |

## HordeSiegeEngineContain

`sizeof(ModuleData)` = 0x1b4, 6 fields

| field | type | offset | default |
|---|---|---|---|
| `CrewAllowedToFire` | Bool | `0x1a0` | `No` |
| `CrewFilter` | KindOfFilter | `0x18c` | `0` |
| `CrewMax` | Int | `0x190` | `0` |
| `InitialCrew` | 0x0087ec0b | `0x0` | - |
| `ObjectStatusOfCrew` | ObjectStatusFlags | `0x1a4` | `0` |
| `SpeedPercentPerCrew` | Percent | `0x19c` | `1` |

## HordeWorkerAIUpdate

`sizeof(ModuleData)` = 0x64, 19 fields

| field | type | offset | default |
|---|---|---|---|
| `AILuaEventsList` | AsciiString | `0x2c` | `0` |
| `AttackPriority` | AsciiString | `0x44` | `"DefaultAttackPriority"` |
| `AutoAcquireEnemiesWhenIdle` | BitFlags | `0x1c` | `0` |
| `BurningDeathTime` | Duration | `0x40` | `0` |
| `CanAttackWhileContained` | Bool | `0x25` | `No` |
| `ComboLocoAttackDistance` | Real | `0x4c` | `80` |
| `ComboLocomotorSet` | Enum | `0x50` | `0` |
| `FadeOnPortals` | Bool | `0x54` | `No` |
| `HoldGroundCloseRangeDistance` | Real | `0x28` | `0` |
| `MaxCowerTime` | Duration | `0x30` | `0` |
| `MinCowerTime` | Duration | `0x34` | `0` |
| `MoodAttackCheckRate` | Duration | `0x18` | - |
| `RampageRequiresAflame` | Bool | `0x3c` | `No` |
| `RampageTime` | Duration | `0x38` | `0` |
| `SpecialContactPoints` | AsciiStringList | `0x58` | `0` |
| `StandGround` | Bool | `0x24` | `No` |
| `StopChaseDistance` | Real | `0x20` | `500` |
| `TimeToEjectPassengersOnRampage` | Duration | `0x48` | `0` |
| `Turret` | 0x006620a2 | `0x14` | `0` |

## HorseHordeContain

`sizeof(ModuleData)` = 0x284, 106 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowAlliesInside` | Bool | `0x7d` | `No` |
| `AllowEnemiesInside` | Bool | `0x7e` | `No` |
| `AllowNeutralInside` | Bool | `0x7f` | `No` |
| `AllowOwnPlayerInsideOverride` | Bool | `0x7c` | `No` |
| `AlternateFormation` | AsciiString | `0x1b0` | `0` |
| `AttributeModifiers` | AsciiStringList | `0x22c` | `0` |
| `BackUpMaxDelayTime` | Duration | `0x1e0` | - |
| `BackUpMaxDistance` | Real | `0x1e8` | `5` |
| `BackUpMinDelayTime` | Duration | `0x1dc` | - |
| `BackUpMinDistance` | Real | `0x1e4` | `3` |
| `BackupPercentage` | Percent | `0x1ec` | `0.5` |
| `BannerCarrierDestroyHordeOnDeath` | Bool | `0x224` | `No` |
| `BannerCarrierHordeDeathType` | DeathTypeFlags | `0x228` | `0` |
| `BannerCarrierMinLevel` | UInt8 | `0x27c` | `1` |
| `BannerCarrierPosition` | BannerCarrierPosition | `0x20c` | `0` |
| `BannerCarriersAllowed` | AsciiStringList | `0x218` | `0` |
| `BoneSpecificConditionState` | 0x008678eb | `0x0` | - |
| `CanGrabStructure` | Bool | `0x13d` | `No` |
| `CollidePickup` | Bool | `0x81` | `No` |
| `ComboHorde` | ComboHorde | `0x198` | `0` |
| `ConditionForEntry` | ModelConditionFlag | `0x14c` | `-1` |
| `ContainMax` | Int | `0x70` | `-1` |
| `CowerRadius` | Real | `0x1f0` | `0` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DamagePercentToUnits` | Percent | `0x6c` | `0` |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DestroyRidersWhoAreNotFreeToExit` | Bool | `0x142` | `No` |
| `DoorOpenTime` | Duration | `0x78` | `0` |
| `EjectPassengersOnDeath` | Bool | `0x82` | `No` |
| `Enabled` | Bool | `0x84` | `No` |
| `EnterFadeTime` | Real | `0x170` | `0` |
| `EnterSound` | AudioEventRTS | `0x38` | `0` |
| `EvaEventLastMemberDeath` | EvaEvent | `0x250` | `-1` |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `ExitBone` | AsciiString | `0xa0` | `0` |
| `ExitDelay` | Duration | `0xac` | `0` |
| `ExitFadeTime` | Real | `0x174` | `0` |
| `ExitPitchRate` | AngularVelocityReal | `0x9c` | `0` |
| `ExitSound` | AudioEventRTS | `0x3c` | `0` |
| `FadeFilter` | KindOfFilter | `0x168` | - |
| `FadePassengerOnEnter` | Bool | `0x16c` | `No` |
| `FadePassengerOnExit` | Bool | `0x16d` | `No` |
| `FadeReverse` | Bool | `0x178` | `No` |
| `FireGrabWeaponOnVictim` | Bool | `0x148` | `Yes` |
| `FlankedDelay` | Duration | `0x268` | `0` |
| `FlankedDuration` | Duration | `0x26c` | - |
| `ForcedLocomotorSet` | Enum | `0x23c` | `-1` |
| `ForceOrientationContainer` | Bool | `0x13c` | `Yes` |
| `FrontAngle` | Real | `0x264` | `360` |
| `GoAggressiveOnExit` | Bool | `0x140` | `No` |
| `GrabWeapon` | WeaponTemplate | `0x144` | `0` |
| `HealthRegen%PerSec` | Real | `0xa8` | `0` |
| `InitialPayload` | 0x0086af0a | `0x0` | - |
| `IsPorcupineFormation` | Bool | `0x238` | `No` |
| `KillPassengersOnDeath` | Bool | `0x83` | `No` |
| `LeaderPosition` | Coord3D | `0x200` | - |
| `LeaderRank` | Int | `0x208` | `0` |
| `LeadersAllowed` | AsciiStringList | `0x1f4` | `0` |
| `LivingWorldOverloadTemplate` | AsciiString | `0x280` | `0` |
| `MachineAllowed` | Bool | `0x240` | `No` |
| `MachineType` | AsciiString | `0x244` | `0` |
| `ManualPickUpFilter` | KindOfFilter | `0x44` | `0` |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MeleeAttackLeashDistance` | Real | `0x24c` | `60` |
| `MeleeBehavior` | MeleeBehavior | `0x260` | `0` |
| `MinimumHordeSize` | Int | `0x270` | `0` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `ModifierRequiredTime` | Duration | `0x94` | `100` |
| `ModifierToGiveOnExit` | AsciiStringList | `0x88` | - |
| `NotComboFormation` | Bool | `0x25c` | `No` |
| `NumberOfExitPaths` | Int | `0x74` | `0` |
| `ObjectStatusOfContained` | ObjectStatusFlags | `0x58` | `0` |
| `OrientLikeContainerOnExit` | Bool | `0x13f` | `No` |
| `PassengerBonePrefix` | PassengerBonePrefix | `0x0` | - |
| `PassengerFilter` | KindOfFilter | `0x40` | - |
| `PassengersInTurret` | Bool | `0x85` | `No` |
| `PassengersTestCollisionHeight` | Real | `0x68` | `-1000` |
| `RandomOffset` | Coord3D | `0x1d0` | - |
| `RankInfo` | RankInfo | `0x18c` | `0` |
| `RankSplit` | Bool | `0x254` | `No` |
| `RanksThatStopAdvance` | 0x0086df0b | `0x1b4` | - |
| `RanksToJustFreeWhenAttacking` | 0x0086ded1 | `0x1c4` | - |
| `RanksToReleaseWhenAttacking` | 0x0086ded1 | `0x1b8` | - |
| `ReleaseSnappyness` | Real | `0x17c` | `0.7` |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `ResetMoodCheckTimeOnExit` | Bool | `0x141` | `Yes` |
| `ScatterNearbyOnExit` | Bool | `0x13e` | `Yes` |
| `ShouldThrowOutPassengers` | Bool | `0x150` | `No` |
| `ShowPips` | Bool | `0x80` | `No` |
| `Slots` | Int | `0x98` | `0` |
| `SplitHorde` | SplitHorde | `0x1a4` | `0` |
| `SplitHordeNumber` | Int | `0x258` | `0` |
| `ThisFormationIsTheMainFormation` | Bool | `0x1d8` | `Yes` |
| `ThrowOutPassengersDelay` | Duration | `0x154` | `0` |
| `ThrowOutPassengersLandingWarhead` | WeaponTemplate | `0x164` | `0` |
| `ThrowOutPassengersVelocity` | Coord3D | `0x158` | - |
| `TypeOneForWeaponSet` | KindOfFlags | `0xb0` | - |
| `TypeOneForWeaponState` | KindOfFlags | `0xe8` | - |
| `TypeThreeForWeaponState` | KindOfFlags | `0x120` | - |
| `TypeTwoForWeaponSet` | KindOfFlags | `0xcc` | `0` |
| `TypeTwoForWeaponState` | KindOfFlags | `0x104` | - |
| `UpgradeCreationTrigger` | 0x0086ba2c | `0x0` | - |
| `UseMarchingAnims` | Bool | `0x25d` | `No` |
| `UseSlowHordeMovement` | Bool | `0x248` | `Yes` |
| `VisionRearOverride` | Percent | `0x274` | `0` |
| `VisionSideOverride` | Percent | `0x278` | `0` |

## ImmortalBody

`sizeof(ModuleData)` = 0x64, 21 fields

| field | type | offset | default |
|---|---|---|---|
| `BurningDeathBehavior` | Bool | `0x51` | `No` |
| `BurningDeathFX` | FXList | `0x54` | `0` |
| `CheerRadius` | Real | `0x4c` | `200` |
| `DamageCreationList` | DamageCreationList | `0x0` | - |
| `DamagedAttributeModifier` | AsciiString | `0x30` | `0` |
| `DodgePercent` | Percent | `0x18` | `0` |
| `EnteringDamagedTransitionTime` | Duration | `0x1c` | `0` |
| `EnteringReallyDamagedTransitionTime` | Duration | `0x20` | `0` |
| `GrabDamage` | Real | `0x3c` | `200` |
| `GrabFX` | FXList | `0x38` | `0` |
| `GrabObject` | AsciiString | `0x2c` | - |
| `GrabOffset` | Coord3D | `0x40` | `0` |
| `HealingBuffFx` | FXList | `0x48` | - |
| `InitialHealth` | Real | `0xc` | `-1` |
| `MaxHealth` | Real | `0x8` | `0` |
| `MaxHealthDamaged` | Real | `0x10` | `0` |
| `MaxHealthReallyDamaged` | Real | `0x14` | `0` |
| `ReallyDamagedAttributeModifier` | AsciiString | `0x34` | `0` |
| `RecoveryTime` | Duration | `0x24` | `0` |
| `RemoveUpgradesOnDeath` | Bool | `0x50` | `No` |
| `UseDefaultDamageSettings` | Bool | `0x28` | `Yes` |

## InheritUpgradeCreate

`sizeof(ModuleData)` = 0xa0, 3 fields

| field | type | offset | default |
|---|---|---|---|
| `ObjectFilter` | KindOfFilter | `0x9c` | - |
| `Radius` | Real | `0x8` | `0` |
| `Upgrade` | UpgradeMask | `0xc` | - |

## InstantDeathBehavior

`sizeof(ModuleData)` = 0x68, 10 fields

| field | type | offset | default |
|---|---|---|---|
| `DamageAmountRequired` | Real | `0x24` | - |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `FX` | FXList | `0x38` | `0` |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `OCL` | 0x008601eb | `0x0` | - |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `Sound` | 0x00860324 | `0x0` | - |
| `Weapon` | 0x0086022e | `0x0` | - |

## InvisibilitySpecialPower

`sizeof(ModuleData)` = 0x150, 39 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BroadcastRadius` | Real | `0x144` | `0` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `Duration` | Duration | `0x14c` | `0` |
| `GiveLevels` | Int | `0x58` | `0` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `InvisibilityNugget` | InvisibilityNugget | `0x7c` | `0` |
| `ObjectFilter` | KindOfFilter | `0x148` | - |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## InvisibilityUpdate

`sizeof(ModuleData)` = 0x20c, 10 fields

| field | type | offset | default |
|---|---|---|---|
| `Broadcast` | Bool | `0x1f4` | `No` |
| `BroadcastObjectFilter` | KindOfFilter | `0x1f8` | - |
| `BroadcastRange` | Real | `0x1fc` | `0` |
| `ForbiddenUpgrades` | UpgradeMask | `0x164` | - |
| `InvisibilityNugget` | InvisibilityNugget | `0x8` | `0` |
| `RequiredUpgrades` | UpgradeMask | `0xd4` | - |
| `StartsActive` | Bool | `0x200` | `No` |
| `UnitSpecificSoundNameToUseAsVoiceEnterStateMoveToStealthyArea` | AsciiString | `0x208` | `0` |
| `UnitSpecificSoundNameToUseAsVoiceMoveToStealthyArea` | AsciiString | `0x204` | `0` |
| `UpdatePeriod` | Duration | `0xd0` | `10` |

## KeepObjectDie

`sizeof(ModuleData)` = 0x40, 8 fields

| field | type | offset | default |
|---|---|---|---|
| `CollapsingTime` | Duration | `0x38` | `25` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `StayOnRadar` | Bool | `0x3c` | `No` |

## LargeGroupAudioUpdate

`sizeof(ModuleData)` = 0x20, 4 fields

| field | type | offset | default |
|---|---|---|---|
| `Key` | 0x007eec77 | `0x8` | `0` |
| `TimeBetweenUpdatesMin` | Duration | `0x14` | - |
| `TimeBetweenUpdatesVariation` | Duration | `0x18` | `1` |
| `UnitWeight` | UInt16 | `0x1c` | `1` |

## LargeGroupBonusUpdate

`sizeof(ModuleData)` = 0x30, 8 fields

| field | type | offset | default |
|---|---|---|---|
| `AlliesOnly` | Bool | `0x18` | `Yes` |
| `AttributeModifier` | AsciiString | `0x2c` | `0` |
| `Count` | Int | `0x10` | `0` |
| `FlagSubObjectNames` | AsciiStringList | `0x20` | `0` |
| `HordeMemberFilter` | KindOfFilter | `0xc` | - |
| `Radius` | Real | `0x14` | `0` |
| `RubOffRadius` | Real | `0x1c` | `20` |
| `UpdateRate` | Duration | `0x8` | - |

## LaserUpdate

`sizeof(ModuleData)` = 0x1c, 5 fields

| field | type | offset | default |
|---|---|---|---|
| `LaserLifetime` | Real | `0x18` | `0` |
| `MuzzleParticleSystem` | AsciiString | `0x8` | `0` |
| `ParentFireBoneName` | AsciiString | `0xc` | `0` |
| `ParentFireBoneOnTurret` | Bool | `0x10` | `No` |
| `TargetParticleSystem` | AsciiString | `0x14` | `0` |

## LevelGrantSpecialPower

`sizeof(ModuleData)` = 0xe0, 64 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `AcceptanceFilter` | KindOfFilter | `0xd8` | - |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `Experience` | Int | `0xd0` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LevelFX` | FXList | `0xdc` | `0` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RadiusEffect` | Real | `0xd4` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |

## LevelUpUpgrade

`sizeof(ModuleData)` = 0x140, 8 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `LevelCap` | Int | `0x13c` | `0` |
| `LevelsToGain` | Int | `0x138` | `0` |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## LifetimeUpdate

`sizeof(ModuleData)` = 0x18, 5 fields

| field | type | offset | default |
|---|---|---|---|
| `DeathType` | Enum | `0x14` | `0` |
| `MaxLifetime` | Duration | `0xc` | `0` |
| `MinLifetime` | Duration | `0x8` | `0` |
| `ScoreKill` | Bool | `0x11` | `No` |
| `WaitForWakeUp` | Bool | `0x10` | `No` |

## LockWeaponCreate

`sizeof(ModuleData)` = 0xc, 1 field

| field | type | offset | default |
|---|---|---|---|
| `SlotToLock` | LookupList | `0x8` | `0` |

## LocomotorSetUpgrade

`sizeof(ModuleData)` = 0x13c, 7 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `KillLocomotorUpgrade` | Bool | `0x138` | `No` |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## MaxHealthUpgrade

`sizeof(ModuleData)` = 0x140, 8 fields

| field | type | offset | default |
|---|---|---|---|
| `AddMaxHealth` | Real | `0x138` | `0` |
| `ChangeType` | Enum | `0x13c` | `0` |
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## MineshaftPortalBehaviour

`sizeof(ModuleData)` = 0x13c, 8 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowEnemies` | Bool | `0x138` | `No` |
| `AllowNonSkirmishAIUnits` | Bool | `0x139` | `No` |
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## MissileUpdate

`sizeof(ModuleData)` = 0x11c, 44 fields

| field | type | offset | default |
|---|---|---|---|
| `BounceCount` | Int | `0x1c` | `0` |
| `BounceDistance` | Real | `0x20` | `0` |
| `BounceFirstHeight` | Real | `0x24` | `0` |
| `BounceFirstPercentIndent` | Percent | `0x2c` | `0` |
| `BounceSecondHeight` | Real | `0x28` | `0` |
| `BounceSecondPercentIndent` | Percent | `0x30` | `0` |
| `CrushStyle` | Bool | `0x18` | `No` |
| `CurveFlattenMinDist` | Real | `0x34` | `0` |
| `DetonateCallsKill` | Bool | `0x4a` | `No` |
| `DetonateOnNoFuel` | Bool | `0xd4` | `No` |
| `DieOnImpact` | Bool | `0x19` | `No` |
| `DistanceToTargetBeforeDiving` | Real | `0xcc` | `0` |
| `DistanceToTravelBeforeTurning` | Real | `0xc8` | `0` |
| `ExhaustTemplate` | AsciiString | `0x118` | `""` |
| `FadeInTime` | Int | `0x44` | `0` |
| `FinalStuckTime` | Duration | `0x38` | `0` |
| `FirstHeight` | Real | `0x8` | `0` |
| `FirstPercentHeight` | Percent | `0x94` | `0.33` |
| `FirstPercentIndent` | Percent | `0x10` | `0` |
| `FlightPathAdjustDistPerSecond` | VelocityReal | `0x8c` | `0` |
| `FuelLifetime` | Duration | `0xc0` | `0` |
| `GarrisonHitKillCount` | Int | `0x4c` | `0` |
| `GarrisonHitKillForbiddenKindOf` | KindOfFlags | `0x6c` | - |
| `GarrisonHitKillFX` | FXList | `0x88` | `0` |
| `GarrisonHitKillRequiredKindOf` | KindOfFlags | `0x50` | - |
| `GroundBounceFX` | FXList | `0xa0` | `0` |
| `GroundBounceWeapon` | WeaponTemplate | `0xa8` | `0` |
| `GroundHitFX` | FXList | `0x9c` | `0` |
| `GroundHitWeapon` | WeaponTemplate | `0xa4` | `0` |
| `IgnitionDelay` | Duration | `0xc4` | `0` |
| `IgnitionFX` | FXList | `0xd0` | `0` |
| `IgnoreTerrainHeight` | Bool | `0x90` | `No` |
| `InvisibleFrames` | Int | `0x40` | `0` |
| `OrientToFlightPath` | Bool | `0x49` | `Yes` |
| `PostLandingEmotion` | EmotionType | `0xb8` | `-1` |
| `PostLandingEmotionRadius` | Real | `0xbc` | `0` |
| `PostLandingStateTime` | Duration | `0xb4` | `0` |
| `PreLandingEmotion` | EmotionType | `0xac` | `-1` |
| `PreLandingEmotionRadius` | Real | `0xb0` | `0` |
| `PreLandingStateTime` | Duration | `0x3c` | `0` |
| `SecondHeight` | Real | `0xc` | `0` |
| `SecondPercentHeight` | Percent | `0x98` | `0.66` |
| `SecondPercentIndent` | Percent | `0x14` | `0` |
| `TumbleRandomly` | Bool | `0x48` | `No` |

## ModelConditionAudioLoopClientBehavior

`sizeof(ModuleData)` = 0x14, 1 field

| field | type | offset | default |
|---|---|---|---|
| `ModelCondition` | ModelConditionAudio | `0x8` | `0` |

## ModelConditionSoundSelectorClientBehavior

`sizeof(ModuleData)` = 0x14, 1 field

| field | type | offset | default |
|---|---|---|---|
| `SoundState` | SoundState | `0x0` | - |

## ModelConditionSpecialAbilityUpdate

`sizeof(ModuleData)` = 0xe0, 65 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `EmotionPulseRadius` | Real | `0xd8` | `50` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GenerateTerror` | Bool | `0xd4` | `No` |
| `GenerateUncontrollableFear` | Bool | `0xd5` | `No` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `ObjectFilter` | KindOfFilter | `0xdc` | - |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |
| `WhichSpecialPower` | Int | `0xd0` | `1` |

## ModelConditionUpgrade

`sizeof(ModuleData)` = 0x1d8, 11 fields

| field | type | offset | default |
|---|---|---|---|
| `AddConditionFlags` | ModelConditionFlags | `0x138` | - |
| `AddTempConditionFlag` | ModelConditionFlag | `0x1d0` | `-1` |
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RemoveConditionFlags` | ModelConditionFlags | `0x184` | - |
| `RemoveConditionFlagsInRange` | ModelConditionFlagRange | `0x184` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TempConditionTime` | Real | `0x1d4` | `0` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## MoneyCrateCollide

`sizeof(ModuleData)` = 0x60, 12 fields

| field | type | offset | default |
|---|---|---|---|
| `BuildingPickup` | Bool | `0x41` | `No` |
| `ExecuteAnimation` | AsciiString | `0x4c` | - |
| `ExecuteAnimationFades` | Bool | `0x58` | `Yes` |
| `ExecuteAnimationTime` | Real | `0x50` | `0` |
| `ExecuteAnimationZRise` | Real | `0x54` | `0` |
| `ExecuteFX` | FXList | `0x48` | `0` |
| `ForbiddenKindOf` | KindOfFlags | `0x24` | - |
| `ForbidOwnerPlayer` | Bool | `0x40` | `No` |
| `HumanOnly` | Bool | `0x42` | `No` |
| `MoneyProvided` | Int | `0x5c` | `0` |
| `PickupScience` | ScienceType | `0x44` | `-1` |
| `RequiredKindOf` | KindOfFlags | `0x8` | - |

## MonitorConditionUpdate

`sizeof(ModuleData)` = 0x6c, 4 fields

| field | type | offset | default |
|---|---|---|---|
| `ModelConditionCommandSet` | AsciiString | `0x54` | `0` |
| `ModelConditionFlags` | ModelConditionFlags | `0x8` | - |
| `WeaponSetFlags` | WeaponSetFlags | `0x58` | - |
| `WeaponToggleCommandSet` | AsciiString | `0x68` | `0` |

## MonsterDockUpdate

`sizeof(ModuleData)` = 0x18, 4 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowsPassthrough` | Bool | `0xc` | `Yes` |
| `DockableObjectFilter` | KindOfFilter | `0x10` | - |
| `DockedAnimationTime` | Duration | `0x14` | `0` |
| `NumberApproachPositions` | Int | `0x8` | `0` |

## NotifyTargetsOfImminentProbableCrushingUpdate

`sizeof(ModuleData)` = 0x18, 4 fields

| field | type | offset | default |
|---|---|---|---|
| `ScanAheadTimeMS` | Duration | `0x4` | - |
| `ScanHeight` | Real | `0x8` | - |
| `ScanWidth` | Real | `0xc` | - |
| `TimeBetweenUpdatesMS` | Duration | `0x0` | - |

## OathbreakerBody

`sizeof(ModuleData)` = 0x64, 21 fields

| field | type | offset | default |
|---|---|---|---|
| `BurningDeathBehavior` | Bool | `0x51` | `No` |
| `BurningDeathFX` | FXList | `0x54` | `0` |
| `CheerRadius` | Real | `0x4c` | `200` |
| `DamageCreationList` | DamageCreationList | `0x0` | - |
| `DamagedAttributeModifier` | AsciiString | `0x30` | `0` |
| `DodgePercent` | Percent | `0x18` | `0` |
| `EnteringDamagedTransitionTime` | Duration | `0x1c` | `0` |
| `EnteringReallyDamagedTransitionTime` | Duration | `0x20` | `0` |
| `GrabDamage` | Real | `0x3c` | `200` |
| `GrabFX` | FXList | `0x38` | `0` |
| `GrabObject` | AsciiString | `0x2c` | - |
| `GrabOffset` | Coord3D | `0x40` | `0` |
| `HealingBuffFx` | FXList | `0x48` | - |
| `InitialHealth` | Real | `0xc` | `-1` |
| `MaxHealth` | Real | `0x8` | `0` |
| `MaxHealthDamaged` | Real | `0x10` | `0` |
| `MaxHealthReallyDamaged` | Real | `0x14` | `0` |
| `ReallyDamagedAttributeModifier` | AsciiString | `0x34` | `0` |
| `RecoveryTime` | Duration | `0x24` | `0` |
| `RemoveUpgradesOnDeath` | Bool | `0x50` | `No` |
| `UseDefaultDamageSettings` | Bool | `0x28` | `Yes` |

## OathbreakersFadeAwayBehavior

`sizeof(ModuleData)` = 0xc, 1 field

| field | type | offset | default |
|---|---|---|---|
| `FadeOutTime` | Duration | `0x8` | - |

## ObjectCreationUpgrade

`sizeof(ModuleData)` = 0x174, 17 fields

| field | type | offset | default |
|---|---|---|---|
| `Angle` | AngleReal | `0x158` | `0` |
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `DeathAnimAndDuration` | AnimAndDuration | `0x160` | - |
| `Delay` | Duration | `0xc` | `0` |
| `DestroyWhenSold` | Bool | `0x15c` | `No` |
| `FadeInTime` | Int | `0x16c` | `0` |
| `GrantUpgrade` | AsciiString | `0x144` | `0` |
| `Offset` | Coord3D | `0x14c` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RemoveUpgrade` | AsciiString | `0x140` | `0` |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | - |
| `ThingToSpawn` | AsciiString | `0x148` | `0` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |
| `UpgradeObject` | ObjectCreationList | `0x8` | `0` |
| `UseBuildingProduction` | Bool | `0x170` | `No` |

## OCLSpecialPower

`sizeof(ModuleData)` = 0xa0, 40 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `CreateLocation` | Enum | `0x8c` | `0` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `GiveLevels` | Int | `0x58` | `0` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `NearestSecondaryObjectFilter` | KindOfFilter | `0x9c` | - |
| `OCL` | ObjectCreationList | `0x88` | `0` |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UpgradeName` | 0x008c7acc | `0x90` | `0` |
| `UpgradeOCL` | 0x008c7a8f | `0x7c` | `0` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## OCLUpdate

`sizeof(ModuleData)` = 0x1c, 5 fields

| field | type | offset | default |
|---|---|---|---|
| `Amount` | Int | `0x14` | `-1` |
| `CreateAtEdge` | Bool | `0x18` | `No` |
| `MaxDelay` | Duration | `0x10` | `0` |
| `MinDelay` | Duration | `0xc` | `0` |
| `OCL` | ObjectCreationList | `0x8` | `0` |

## OilSpillUpdate

`sizeof(ModuleData)` = 0x20, 8 fields

| field | type | offset | default |
|---|---|---|---|
| `AliveOnly` | Bool | `0xe` | `No` |
| `BreadcrumbName` | AsciiString | `0x10` | `0` |
| `ChargingModeTrigger` | Bool | `0xd` | `No` |
| `FireWeaponNugget` | FireWeaponNugget | `0x0` | - |
| `HeroModeTrigger` | Bool | `0xc` | `No` |
| `IgnitionWeaponName` | AsciiString | `0x14` | `0` |
| `IgnitionWeaponSpacing` | Real | `0x18` | `0` |
| `OilSpillFX` | FXList | `0x1c` | `0` |

## OneRingPenaltyUpdate

`sizeof(ModuleData)` = 0x24, 7 fields

| field | type | offset | default |
|---|---|---|---|
| `DiscoveredSound` | AudioEventRTS | `0x20` | `0` |
| `RingTimeBeforeSpawning` | Duration | `0xc` | `0` |
| `SpecialObjectName` | AsciiString | `0x8` | `0` |
| `StartingDistanceFromMe` | Real | `0x18` | `0` |
| `TimeFrozenFromPenalty` | Duration | `0x1c` | `0` |
| `TimeRingPowerSuppressed` | Duration | `0x14` | `0` |
| `TimeSpentRoamingAround` | Duration | `0x10` | `0` |

## OpenContain

`sizeof(ModuleData)` = 0x98, 30 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowAlliesInside` | Bool | `0x7d` | `No` |
| `AllowEnemiesInside` | Bool | `0x7e` | `No` |
| `AllowNeutralInside` | Bool | `0x7f` | `No` |
| `AllowOwnPlayerInsideOverride` | Bool | `0x7c` | `No` |
| `BoneSpecificConditionState` | 0x008678eb | `0x0` | - |
| `CollidePickup` | Bool | `0x81` | `No` |
| `ContainMax` | Int | `0x70` | `-1` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DamagePercentToUnits` | Percent | `0x6c` | `0` |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DoorOpenTime` | Duration | `0x78` | `0` |
| `EjectPassengersOnDeath` | Bool | `0x82` | `No` |
| `Enabled` | Bool | `0x84` | `No` |
| `EnterSound` | AudioEventRTS | `0x38` | `0` |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `ExitSound` | AudioEventRTS | `0x3c` | `0` |
| `KillPassengersOnDeath` | Bool | `0x83` | `No` |
| `ManualPickUpFilter` | KindOfFilter | `0x44` | `0` |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `ModifierRequiredTime` | Duration | `0x94` | `100` |
| `ModifierToGiveOnExit` | AsciiStringList | `0x88` | - |
| `NumberOfExitPaths` | Int | `0x74` | `0` |
| `ObjectStatusOfContained` | ObjectStatusFlags | `0x58` | `0` |
| `PassengerBonePrefix` | PassengerBonePrefix | `0x0` | - |
| `PassengerFilter` | KindOfFilter | `0x40` | - |
| `PassengersInTurret` | Bool | `0x85` | `No` |
| `PassengersTestCollisionHeight` | Real | `0x68` | `-1000` |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `ShowPips` | Bool | `0x80` | `No` |

## PartTheHeavensUpdate

`sizeof(ModuleData)` = 0x94, 5 fields

| field | type | offset | default |
|---|---|---|---|
| `Angle` | 0x0073b723 | `0x68` | `0` |
| `Color` | RGBAColor | `0xc` | `0` |
| `Opacity` | 0x0073b723 | `0x3c` | - |
| `Radius` | 0x0073b723 | `0x10` | - |
| `Texture` | AsciiString | `0x8` | `0` |

## PassiveAreaEffectBehavior

`sizeof(ModuleData)` = 0x38, 10 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowFilter` | KindOfFilter | `0x20` | - |
| `AntiCategories` | 0x0089f32d | `0x2c` | `0` |
| `AntiFX` | FXList | `0x30` | `0` |
| `EffectRadius` | Real | `0x8` | `200` |
| `HealFX` | FXList | `0x34` | `0` |
| `HealPercentPerSecond` | Percent | `0xc` | `0` |
| `ModifierName` | AsciiStringList | `0x14` | - |
| `NonStackable` | Bool | `0x28` | `No` |
| `PingDelay` | Duration | `0x10` | `15` |
| `UpgradeRequired` | AsciiString | `0x24` | `0` |

## PhysicsBehavior

`sizeof(ModuleData)` = 0x5c, 23 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowBouncing` | Bool | `0x58` | `No` |
| `BounceCount` | Int | `0x24` | `2` |
| `BounceFirstHeight` | Real | `0x2c` | `1.3` |
| `BounceFirstPercentIndent` | Percent | `0x34` | `0.33` |
| `BounceSecondHeight` | Real | `0x30` | `1.3` |
| `BounceSecondPercentIndent` | Percent | `0x38` | `0.66` |
| `CurveFlattenMinDist` | Real | `0x3c` | `0` |
| `FirstHeight` | Real | `0x8` | `1.3` |
| `FirstPercentHeight` | Percent | `0x44` | `0.33` |
| `FirstPercentIndent` | Percent | `0x10` | `0.33` |
| `GravityMult` | Real | `0x4c` | `1` |
| `GroundBounceFX` | FXList | `0x54` | `0` |
| `GroundHitFX` | FXList | `0x50` | `0` |
| `IgnoreTerrainHeight` | Bool | `0x42` | `No` |
| `KillWhenRestingOnGround` | Bool | `0x59` | `No` |
| `OrientToFlightPath` | Bool | `0x41` | `No` |
| `SecondHeight` | Real | `0xc` | `1.3` |
| `SecondPercentHeight` | Percent | `0x48` | `0.66` |
| `SecondPercentIndent` | Percent | `0x14` | `0.66` |
| `ShockStandingTime` | Duration | `0x20` | - |
| `ShockStunnedTimeHigh` | Duration | `0x1c` | - |
| `ShockStunnedTimeLow` | Duration | `0x18` | - |
| `TumbleRandomly` | Bool | `0x40` | `No` |

## PickupStuffUpdate

`sizeof(ModuleData)` = 0x18, 4 fields

| field | type | offset | default |
|---|---|---|---|
| `ScanIntervalSeconds` | Real | `0x14` | `0.5` |
| `ScanRange` | Real | `0xc` | `200` |
| `SkirmishAIOnly` | Bool | `0x8` | `Yes` |
| `StuffToPickUp` | KindOfFilter | `0x10` | - |

## PillageModule

`sizeof(ModuleData)` = 0x14, 3 fields

| field | type | offset | default |
|---|---|---|---|
| `NumDamageEventsPerPillage` | Int | `0xc` | `0` |
| `PillageAmount` | Int | `0x8` | `0` |
| `PillageFilter` | KindOfFilter | `0x10` | - |

## PlayerHealSpecialPower

`sizeof(ModuleData)` = 0xac, 41 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `GiveLevels` | Int | `0x58` | `0` |
| `HealAffects` | KindOfFlags | `0x88` | - |
| `HealAmount` | Real | `0x7c` | `0` |
| `HealAsPercent` | Bool | `0x80` | `Yes` |
| `HealFX` | FXList | `0xa4` | `0` |
| `HealOCL` | ObjectCreationList | `0xa8` | `0` |
| `HealRadius` | Real | `0x84` | `100` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## PlayerUpgradeSpecialPower

`sizeof(ModuleData)` = 0x88, 36 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `GiveLevels` | Int | `0x58` | `0` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UpgradeName` | 0x008cc228 | `0x7c` | `0` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## PoisonedBehavior

`sizeof(ModuleData)` = 0x10, 2 fields

| field | type | offset | default |
|---|---|---|---|
| `PoisonDamageInterval` | Duration | `0x8` | `0` |
| `PoisonDuration` | Duration | `0xc` | `0` |

## PorcupineFormationBodyModule

`sizeof(ModuleData)` = 0x70, 24 fields

| field | type | offset | default |
|---|---|---|---|
| `BurningDeathBehavior` | Bool | `0x51` | `No` |
| `BurningDeathFX` | FXList | `0x54` | `0` |
| `CheerRadius` | Real | `0x4c` | `200` |
| `CrushDamageWeaponTemplate` | WeaponTemplate | `0x68` | `0` |
| `CrusherLevelResisted` | Int8 | `0x6c` | `0` |
| `DamageCreationList` | DamageCreationList | `0x0` | - |
| `DamagedAttributeModifier` | AsciiString | `0x30` | `0` |
| `DamageWeaponTemplate` | WeaponTemplate | `0x64` | `0` |
| `DodgePercent` | Percent | `0x18` | `0` |
| `EnteringDamagedTransitionTime` | Duration | `0x1c` | `0` |
| `EnteringReallyDamagedTransitionTime` | Duration | `0x20` | `0` |
| `GrabDamage` | Real | `0x3c` | `200` |
| `GrabFX` | FXList | `0x38` | `0` |
| `GrabObject` | AsciiString | `0x2c` | - |
| `GrabOffset` | Coord3D | `0x40` | `0` |
| `HealingBuffFx` | FXList | `0x48` | - |
| `InitialHealth` | Real | `0xc` | `-1` |
| `MaxHealth` | Real | `0x8` | `0` |
| `MaxHealthDamaged` | Real | `0x10` | `0` |
| `MaxHealthReallyDamaged` | Real | `0x14` | `0` |
| `ReallyDamagedAttributeModifier` | AsciiString | `0x34` | `0` |
| `RecoveryTime` | Duration | `0x24` | `0` |
| `RemoveUpgradesOnDeath` | Bool | `0x50` | `No` |
| `UseDefaultDamageSettings` | Bool | `0x28` | `Yes` |

## ProductionQueueHordeContain

`sizeof(ModuleData)` = 0xe0, 40 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowAlliesInside` | Bool | `0x7d` | `No` |
| `AllowEnemiesInside` | Bool | `0x7e` | `No` |
| `AllowNeutralInside` | Bool | `0x7f` | `No` |
| `AllowOwnPlayerInsideOverride` | Bool | `0x7c` | `No` |
| `BoneSpecificConditionState` | 0x008678eb | `0x0` | - |
| `CollidePickup` | Bool | `0x81` | `No` |
| `ContainMax` | Int | `0x70` | `-1` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DamagePercentToUnits` | Percent | `0x6c` | `0` |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DestinationTemplate` | 0x0088494c | `0xd4` | `0` |
| `DoorOpenTime` | Duration | `0x78` | `0` |
| `EjectPassengersOnDeath` | Bool | `0x82` | `No` |
| `Enabled` | Bool | `0x84` | `No` |
| `EnterSound` | AudioEventRTS | `0x38` | `0` |
| `EntryOffset` | Coord3D | `0xb0` | - |
| `EntryPosition` | Coord3D | `0xbc` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `ExitDelay` | Duration | `0xac` | `0` |
| `ExitOffset` | Coord3D | `0xc8` | `1` |
| `ExitSound` | AudioEventRTS | `0x3c` | `0` |
| `HealObjects` | Bool | `0x98` | `No` |
| `ImmuneToClearBuildingAttacks` | Bool | `0xa1` | `No` |
| `InitialRoster` | 0x00653381 | `0x0` | - |
| `KillPassengersOnDeath` | Bool | `0x83` | `No` |
| `ManualPickUpFilter` | KindOfFilter | `0x44` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `MobileGarrison` | Bool | `0xa0` | `No` |
| `ModifierRequiredTime` | Duration | `0x94` | `100` |
| `ModifierToGiveOnExit` | AsciiStringList | `0x88` | - |
| `NumberOfExitPaths` | Int | `0x74` | `0` |
| `ObjectStatusOfContained` | ObjectStatusFlags | `0x58` | `0` |
| `PassengerBonePrefix` | PassengerBonePrefix | `0x0` | - |
| `PassengerFilter` | KindOfFilter | `0x40` | - |
| `PassengersInTurret` | Bool | `0x85` | `No` |
| `PassengersTestCollisionHeight` | Real | `0x68` | `-1000` |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `ShowPips` | Bool | `0x80` | `No` |
| `TimeForFullHeal` | DurationReal | `0x9c` | `1` |

## ProductionSpeedBonus

`sizeof(ModuleData)` = 0x90, 38 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `GiveLevels` | Int | `0x58` | `0` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `NumberOfFrames` | Int | `0x7c` | `0` |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `SpeedMulitplier` | Real | `0x80` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `Type` | AsciiStringList | `0x84` | - |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## ProductionUpdate

`sizeof(ModuleData)` = 0x50, 17 fields

| field | type | offset | default |
|---|---|---|---|
| `BonusForType` | AsciiString | `0x44` | `""` |
| `ConstructionCompleteDuration` | Duration | `0x18` | `0` |
| `DisabledTypesToProcess` | DisabledTypeFlags | `0x2c` | - |
| `DoorCloseTime` | Duration | `0x14` | `0` |
| `DoorOpeningTime` | Duration | `0xc` | `0` |
| `DoorWaitOpenTime` | Duration | `0x10` | `0` |
| `GiveNoXP` | Bool | `0x30` | `No` |
| `MaxQueueEntries` | Int | `0x28` | `20` |
| `NumDoorAnimations` | Int | `0x8` | `0` |
| `ProductionModifier` | ProductionModifier | `0x0` | - |
| `QuantityModifier` | 0x008a3633 | `0x1c` | - |
| `SecondaryQueue` | Bool | `0x4c` | `No` |
| `SetBonusModelConditionOnSpeedBonus` | Bool | `0x41` | `No` |
| `SpecialPrepModelconditionTime` | Duration | `0x38` | `0` |
| `SpeedBonusAudioLoop` | AudioEventRTS | `0x48` | `0` |
| `UnitInvulnerableTime` | Duration | `0x34` | `0` |
| `VeteranUnitsFromVeteranFactory` | Bool | `0x40` | `No` |

## ProneUpdate

`sizeof(ModuleData)` = 0xc, 1 field

| field | type | offset | default |
|---|---|---|---|
| `DamageToFramesRatio` | Real | `0x8` | `1` |

## PropagandaTowerBehavior

`sizeof(ModuleData)` = 0x24, 7 fields

| field | type | offset | default |
|---|---|---|---|
| `DelayBetweenUpdates` | Duration | `0xc` | `15` |
| `HealPercentEachSecond` | Percent | `0x10` | `0.01` |
| `PulseFX` | FXList | `0x14` | `0` |
| `Radius` | Real | `0x8` | `200` |
| `UpgradedHealPercentEachSecond` | Percent | `0x1c` | `0.02` |
| `UpgradedPulseFX` | FXList | `0x20` | `0` |
| `UpgradeRequired` | AsciiString | `0x18` | `0` |

## QueueProductionExitUpdate

`sizeof(ModuleData)` = 0x34, 9 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowAirborneCreation` | Bool | `0x24` | `No` |
| `CanRallyToSlaughter` | Bool | `0x31` | `No` |
| `ExitDelay` | Duration | `0x20` | `0` |
| `InitialBurst` | Int | `0x28` | `0` |
| `NaturalRallyPoint` | Coord3D | `0x14` | `0` |
| `NoExitPath` | Bool | `0x30` | `No` |
| `PlacementViewAngle` | AngleReal | `0x2c` | `0` |
| `UnitCreatePoint` | Coord3D | `0x8` | `0` |
| `UseReturnToFormation` | Bool | `0x32` | `Yes` |

## RadarMarkerClientUpdate

`sizeof(ModuleData)` = 0xc, 1 field

| field | type | offset | default |
|---|---|---|---|
| `MarkerType` | AsciiString | `0x8` | `0` |

## RadarUpdate

`sizeof(ModuleData)` = 0xc, 1 field

| field | type | offset | default |
|---|---|---|---|
| `RadarExtendTime` | DurationReal | `0x8` | `0` |

## RadarUpgrade

`sizeof(ModuleData)` = 0x13c, 7 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `DisableProof` | Bool | `0x138` | `No` |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## RadiateFearUpdate

`sizeof(ModuleData)` = 0x150, 14 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `EmotionPulseInterval` | Duration | `0x18` | `0` |
| `EmotionPulseRadius` | Real | `0x14` | `0` |
| `GenerateFear` | Bool | `0x11` | `No` |
| `GenerateTerror` | Bool | `0x10` | `No` |
| `GenerateUncontrollableFear` | Bool | `0x12` | `No` |
| `InitiallyActive` | Bool | `0x8` | `No` |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | - |
| `TriggeredBy` | UpgradeMask | `0x0` | - |
| `VictimFilter` | KindOfFilter | `0x1c` | - |
| `WhichSpecialPower` | Int | `0xc` | `-1` |

## RainOfFireUpdate

`sizeof(ModuleData)` = 0x30, 9 fields

| field | type | offset | default |
|---|---|---|---|
| `DarknessFadeTime` | Duration | `0xc` | `120` |
| `DarknessLevel` | PositiveReal | `0x14` | `0.25` |
| `DPSMax` | PositiveReal | `0x20` | `1` |
| `DPSMin` | PositiveReal | `0x1c` | `1` |
| `DPSRampupTime` | DurationReal | `0x24` | `0` |
| `JitterRadius` | Real | `0x18` | `0` |
| `RainEmitterHeight` | PositiveReal | `0x10` | `100` |
| `RainOffset` | Coord3D | `0x28` | `0` |
| `StartRainTime` | Duration | `0x8` | `150` |

## RampageBehavior

`sizeof(ModuleData)` = 0x2c, 7 fields

| field | type | offset | default |
|---|---|---|---|
| `RampageAngryLifeTimer` | Int | `0x1c` | `0` |
| `RampageEnemyCheckRange` | Real | `0x24` | `0` |
| `RampageEnemyThreshold` | Int | `0x28` | `0` |
| `RampageHealthThreshold` | Real | `0x14` | - |
| `RampageLifeTimer` | Int | `0x18` | `0` |
| `RampageResetTimer` | Int | `0x20` | `0` |
| `RequiredUpgrade` | AsciiStringList | `0x8` | - |

## RandomSoundSelectorClientBehavior

`sizeof(ModuleData)` = 0x1e0, 60 fields

| field | type | offset | default |
|---|---|---|---|
| `Chance` | Percent | `0x1d4` | `0.5` |
| `RerollOnEveryFrame` | Bool | `0x1dd` | `Yes` |
| `SoundAmbient` | AudioEventRTS | `0x128` | - |
| `SoundAmbientBattle` | AudioEventRTS | `0x148` | - |
| `SoundAmbientDamaged` | AudioEventRTS | `0x130` | - |
| `SoundAmbientReallyDamaged` | AudioEventRTS | `0x138` | - |
| `SoundAmbientRubble` | AudioEventRTS | `0x140` | - |
| `SoundCreated` | AudioEventRTS | `0x160` | - |
| `SoundCrushing` | AudioEventRTS | `0x1b8` | - |
| `SoundEnter` | AudioEventRTS | `0x178` | - |
| `SoundExit` | AudioEventRTS | `0x180` | - |
| `SoundFallingFromPlane` | AudioEventRTS | `0x1a0` | - |
| `SoundImpact` | AudioEventRTS | `0x1a8` | - |
| `SoundImpactCyclonic` | AudioEventRTS | `0x1b0` | - |
| `SoundMoveLoop` | AudioEventRTS | `0x118` | - |
| `SoundMoveLoopDamaged` | AudioEventRTS | `0x120` | - |
| `SoundMoveStart` | AudioEventRTS | `0x108` | - |
| `SoundMoveStartDamaged` | AudioEventRTS | `0x110` | - |
| `SoundOnDamaged` | AudioEventRTS | `0x168` | - |
| `SoundOnReallyDamaged` | AudioEventRTS | `0x170` | - |
| `SoundPromotedElite` | AudioEventRTS | `0x190` | - |
| `SoundPromotedHero` | AudioEventRTS | `0x198` | - |
| `SoundPromotedVeteran` | AudioEventRTS | `0x188` | - |
| `SoundStealthOff` | AudioEventRTS | `0x158` | - |
| `SoundStealthOn` | AudioEventRTS | `0x150` | - |
| `UnitSpecificSounds` | 0x0073f684 | `0x1c8` | - |
| `VoiceAlert` | AudioEventRTS | `0x70` | - |
| `VoiceAttack` | AudioEventRTS | `0x30` | - |
| `VoiceAttackAir` | AudioEventRTS | `0x60` | - |
| `VoiceAttackCharge` | AudioEventRTS | `0x38` | - |
| `VoiceAttackMachine` | AudioEventRTS | `0x98` | - |
| `VoiceAttackStructure` | AudioEventRTS | `0x90` | - |
| `VoiceCombineWithHorde` | AudioEventRTS | `0xa8` | - |
| `VoiceCreated` | AudioEventRTS | `0x48` | - |
| `VoiceDefect` | AudioEventRTS | `0x58` | - |
| `VoiceEnterStateAttack` | AudioEventRTS | `0xb0` | - |
| `VoiceEnterStateAttackAir` | AudioEventRTS | `0xc0` | - |
| `VoiceEnterStateAttackCharge` | AudioEventRTS | `0xb8` | - |
| `VoiceEnterStateAttackMachine` | AudioEventRTS | `0xd0` | - |
| `VoiceEnterStateAttackStructure` | AudioEventRTS | `0xc8` | - |
| `VoiceEnterStateMove` | AudioEventRTS | `0xd8` | - |
| `VoiceEnterStateMoveOverWalls` | AudioEventRTS | `0xe8` | - |
| `VoiceEnterStateMoveToCamp` | AudioEventRTS | `0xf8` | - |
| `VoiceEnterStateMoveToHigherGround` | AudioEventRTS | `0xe0` | - |
| `VoiceEnterStateMoveWhileAttacking` | AudioEventRTS | `0x100` | - |
| `VoiceEnterStateRetreatToCastle` | AudioEventRTS | `0xf0` | - |
| `VoiceFear` | AudioEventRTS | `0x40` | - |
| `VoiceFullyCreated` | AudioEventRTS | `0x78` | - |
| `VoiceGuard` | AudioEventRTS | `0x68` | - |
| `VoiceMove` | AudioEventRTS | `0x18` | - |
| `VoiceMoveOverWalls` | AudioEventRTS | `0x28` | - |
| `VoiceMoveToCamp` | AudioEventRTS | `0x88` | - |
| `VoiceMoveToHigherGround` | AudioEventRTS | `0x20` | - |
| `VoiceMoveWhileAttacking` | AudioEventRTS | `0xa0` | - |
| `VoicePriority` | 0x008d000e | `0x1d8` | `0` |
| `VoiceRetreatToCastle` | AudioEventRTS | `0x80` | - |
| `VoiceSelect` | AudioEventRTS | `0x0` | - |
| `VoiceSelectBattle` | AudioEventRTS | `0x10` | - |
| `VoiceSelectUnderConstruction` | AudioEventRTS | `0x8` | - |
| `VoiceTaskComplete` | AudioEventRTS | `0x50` | - |

## RebuildHoleBehavior

`sizeof(ModuleData)` = 0x14, 3 fields

| field | type | offset | default |
|---|---|---|---|
| `HoleHealthRegen%PerSecond` | Percent | `0xc` | `0.1` |
| `WorkerObjectName` | AsciiString | `0x10` | `0` |
| `WorkerRespawnDelay` | DurationReal | `0x8` | `0` |

## RebuildHoleExposeDie

`sizeof(ModuleData)` = 0x48, 10 fields

| field | type | offset | default |
|---|---|---|---|
| `DamageAmountRequired` | Real | `0x24` | - |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `FadeInTimeSeconds` | Real | `0x40` | `0` |
| `HoleMaxHealth` | Real | `0x3c` | `0` |
| `HoleName` | AsciiString | `0x38` | `0` |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `TransferAttackers` | Bool | `0x44` | `Yes` |

## ReflectDamage

`sizeof(ModuleData)` = 0x14, 3 fields

| field | type | offset | default |
|---|---|---|---|
| `DamageTypesToReflect` | DamageTypeFlags | `0x8` | `0` |
| `MinimumDamageToReflect` | Real | `0x10` | `0` |
| `ReflectDamagePercentage` | Percent | `0xc` | `0` |

## RefundDie

`sizeof(ModuleData)` = 0x44, 9 fields

| field | type | offset | default |
|---|---|---|---|
| `BuildingRequired` | KindOfFilter | `0x40` | - |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `RefundPercent` | Percent | `0x3c` | `0` |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `UpgradeRequired` | UpgradeTemplate | `0x38` | `0` |

## RemoveUpgradeUpgrade

`sizeof(ModuleData)` = 0x154, 10 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RemoveFromAllPlayerObjects` | Bool | `0x151` | `No` |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `SuppressEvaEventForRemoval` | Bool | `0x150` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |
| `UpgradeGroupsToRemove` | AsciiStringList | `0x144` | `0` |
| `UpgradeToRemove` | AsciiStringList | `0x138` | `0` |

## RepairDockUpdate

`sizeof(ModuleData)` = 0x14, 3 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowsPassthrough` | Bool | `0xc` | `Yes` |
| `NumberApproachPositions` | Int | `0x8` | `0` |
| `TimeForFullHeal` | DurationReal | `0x10` | `1` |

## RepairSpecialPower

`sizeof(ModuleData)` = 0x7c, 35 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `GiveLevels` | Int | `0x58` | `0` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## ReplaceObjectUpdate

`sizeof(ModuleData)` = 0xe8, 64 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `ReplaceFX` | FXList | `0xe0` | `0` |
| `ReplaceObject` | ReplaceObject | `0x0` | - |
| `ReplaceRadius` | Real | `0xdc` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `Scatter` | Bool | `0xe4` | `No` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |

## ReplaceSelfUpgrade

`sizeof(ModuleData)` = 0x144, 8 fields

| field | type | offset | default |
|---|---|---|---|
| `AndThenAddA` | AsciiStringList | `0x138` | - |
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `Permanent` | Bool | `0x12e` | - |
| `ReplaceWith` | AsciiStringList | `0x138` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## ReplenishUnitsBehavior

`sizeof(ModuleData)` = 0x15c, 13 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `NoReplenishIfEnemyWithinRadius` | Real | `0x13c` | `0` |
| `Permanent` | Bool | `0x12e` | - |
| `ReplenishDelay` | Duration | `0x154` | - |
| `ReplenishFXList` | FXList | `0x140` | `0` |
| `ReplenishHordeMembersOnly` | Bool | `0x159` | `No` |
| `ReplenishRadius` | Real | `0x138` | `100` |
| `ReplenishStatii` | ObjectStatusFlags | `0x144` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `StartsActive` | Bool | `0x158` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## RespawnBody

`sizeof(ModuleData)` = 0x6c, 23 fields

| field | type | offset | default |
|---|---|---|---|
| `BurningDeathBehavior` | Bool | `0x51` | `No` |
| `BurningDeathFX` | FXList | `0x54` | `0` |
| `CanRespawn` | Bool | `0x68` | `Yes` |
| `CheerRadius` | Real | `0x4c` | `200` |
| `DamageCreationList` | DamageCreationList | `0x0` | - |
| `DamagedAttributeModifier` | AsciiString | `0x30` | `0` |
| `DodgePercent` | Percent | `0x18` | `0` |
| `EnteringDamagedTransitionTime` | Duration | `0x1c` | `0` |
| `EnteringReallyDamagedTransitionTime` | Duration | `0x20` | `0` |
| `GrabDamage` | Real | `0x3c` | `200` |
| `GrabFX` | FXList | `0x38` | `0` |
| `GrabObject` | AsciiString | `0x2c` | - |
| `GrabOffset` | Coord3D | `0x40` | `0` |
| `HealingBuffFx` | FXList | `0x48` | - |
| `InitialHealth` | Real | `0xc` | `-1` |
| `MaxHealth` | Real | `0x8` | `0` |
| `MaxHealthDamaged` | Real | `0x10` | `0` |
| `MaxHealthReallyDamaged` | Real | `0x14` | `0` |
| `PermanentlyKilledByFilter` | KindOfFilter | `0x64` | - |
| `ReallyDamagedAttributeModifier` | AsciiString | `0x34` | `0` |
| `RecoveryTime` | Duration | `0x24` | `0` |
| `RemoveUpgradesOnDeath` | Bool | `0x50` | `No` |
| `UseDefaultDamageSettings` | Bool | `0x28` | `Yes` |

## RespawnUpdate

`sizeof(ModuleData)` = 0x120, 14 fields

| field | type | offset | default |
|---|---|---|---|
| `AutoRespawnAtObjectFilter` | KindOfFilter | `0x8` | - |
| `ButtonImage` | AsciiString | `0x118` | `0` |
| `DeathAnim` | ModelConditionFlags | `0xc` | `0` |
| `DeathAnimationTime` | Duration | `0xfc` | `0` |
| `DeathFX` | FXList | `0xf0` | `0` |
| `InitialSpawnAnim` | ModelConditionFlags | `0xa4` | - |
| `InitialSpawnAnimationTime` | Duration | `0x104` | `0` |
| `InitialSpawnFX` | FXList | `0xf8` | `0` |
| `RespawnAnim` | ModelConditionFlags | `0x58` | - |
| `RespawnAnimationTime` | Duration | `0x100` | `0` |
| `RespawnAsTemplate` | AsciiString | `0x11c` | `0` |
| `RespawnEntry` | RespawnEntry | `0x10c` | - |
| `RespawnFX` | FXList | `0xf4` | `0` |
| `RespawnRules` | RespawnRules | `0x10c` | - |

## RiderChangeContain

`sizeof(ModuleData)` = 0x284, 80 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowAlliesInside` | Bool | `0x7d` | `No` |
| `AllowEnemiesInside` | Bool | `0x7e` | `No` |
| `AllowNeutralInside` | Bool | `0x7f` | `No` |
| `AllowOwnPlayerInsideOverride` | Bool | `0x7c` | `No` |
| `BoneSpecificConditionState` | 0x008678eb | `0x0` | - |
| `CanGrabStructure` | Bool | `0x13d` | `No` |
| `CollidePickup` | Bool | `0x81` | `No` |
| `ConditionForEntry` | ModelConditionFlag | `0x14c` | `-1` |
| `ContainMax` | Int | `0x70` | `-1` |
| `CrewAllowedToFire` | Bool | `0x1a0` | `No` |
| `CrewFilter` | KindOfFilter | `0x18c` | `0` |
| `CrewMax` | Int | `0x190` | `0` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DamagePercentToUnits` | Percent | `0x6c` | `0` |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DestroyRidersWhoAreNotFreeToExit` | Bool | `0x142` | `No` |
| `DoorOpenTime` | Duration | `0x78` | `0` |
| `EjectPassengersOnDeath` | Bool | `0x82` | `No` |
| `Enabled` | Bool | `0x84` | `No` |
| `EnterFadeTime` | Real | `0x170` | `0` |
| `EnterSound` | AudioEventRTS | `0x38` | `0` |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `ExitBone` | AsciiString | `0xa0` | `0` |
| `ExitDelay` | Duration | `0xac` | `0` |
| `ExitFadeTime` | Real | `0x174` | `0` |
| `ExitPitchRate` | AngularVelocityReal | `0x9c` | `0` |
| `ExitSound` | AudioEventRTS | `0x3c` | `0` |
| `FadeFilter` | KindOfFilter | `0x168` | - |
| `FadePassengerOnEnter` | Bool | `0x16c` | `No` |
| `FadePassengerOnExit` | Bool | `0x16d` | `No` |
| `FadeReverse` | Bool | `0x178` | `No` |
| `FireGrabWeaponOnVictim` | Bool | `0x148` | `Yes` |
| `ForceOrientationContainer` | Bool | `0x13c` | `Yes` |
| `GoAggressiveOnExit` | Bool | `0x140` | `No` |
| `GrabWeapon` | WeaponTemplate | `0x144` | `0` |
| `HealthRegen%PerSec` | Real | `0xa8` | `0` |
| `InitialCrew` | 0x0087ec0b | `0x0` | - |
| `InitialPayload` | 0x0086af0a | `0x0` | - |
| `KillPassengersOnDeath` | Bool | `0x83` | `No` |
| `ManualPickUpFilter` | KindOfFilter | `0x44` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `ModifierRequiredTime` | Duration | `0x94` | `100` |
| `ModifierToGiveOnExit` | AsciiStringList | `0x88` | - |
| `NumberOfExitPaths` | Int | `0x74` | `0` |
| `ObjectStatusOfContained` | ObjectStatusFlags | `0x58` | `0` |
| `ObjectStatusOfCrew` | ObjectStatusFlags | `0x1a4` | `0` |
| `OrientLikeContainerOnExit` | Bool | `0x13f` | `No` |
| `PassengerBonePrefix` | PassengerBonePrefix | `0x0` | - |
| `PassengerFilter` | KindOfFilter | `0x40` | - |
| `PassengersInTurret` | Bool | `0x85` | `No` |
| `PassengersTestCollisionHeight` | Real | `0x68` | `-1000` |
| `ReleaseSnappyness` | Real | `0x17c` | `0.7` |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `ResetMoodCheckTimeOnExit` | Bool | `0x141` | `Yes` |
| `Rider1` | RiderInfo | `0x1b8` | - |
| `Rider2` | RiderInfo | `0x1d0` | - |
| `Rider3` | RiderInfo | `0x1e8` | `3` |
| `Rider4` | RiderInfo | `0x200` | - |
| `Rider5` | RiderInfo | `0x218` | `0` |
| `Rider6` | RiderInfo | `0x230` | - |
| `Rider7` | RiderInfo | `0x248` | - |
| `Rider8` | RiderInfo | `0x260` | - |
| `ScatterNearbyOnExit` | Bool | `0x13e` | `Yes` |
| `ScuttleDelay` | Duration | `0x278` | `0` |
| `ScuttleStatus` | Enum | `0x0` | - |
| `ShouldThrowOutPassengers` | Bool | `0x150` | `No` |
| `ShowPips` | Bool | `0x80` | `No` |
| `Slots` | Int | `0x98` | `0` |
| `SpeedPercentPerCrew` | Percent | `0x19c` | `1` |
| `ThrowOutPassengersDelay` | Duration | `0x154` | `0` |
| `ThrowOutPassengersLandingWarhead` | WeaponTemplate | `0x164` | `0` |
| `ThrowOutPassengersVelocity` | Coord3D | `0x158` | - |
| `TransferSelection` | Bool | `0x1b4` | `No` |
| `TypeOneForWeaponSet` | KindOfFlags | `0xb0` | - |
| `TypeOneForWeaponState` | KindOfFlags | `0xe8` | - |
| `TypeThreeForWeaponState` | KindOfFlags | `0x120` | - |
| `TypeTwoForWeaponSet` | KindOfFlags | `0xcc` | `0` |
| `TypeTwoForWeaponState` | KindOfFlags | `0x104` | - |
| `UpgradeCreationTrigger` | 0x0086ba2c | `0x0` | - |

## RousingSpeechUpdate

`sizeof(ModuleData)` = 0x100, 70 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `BonusRadius` | Real | `0xd0` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CreateWave` | Bool | `0xe4` | `No` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FollowerFX` | FXList | `0xe0` | `0` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LeaderFX` | FXList | `0xdc` | `0` |
| `LevelUp` | Bool | `0xf8` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `ModifierName` | AsciiStringList | `0xec` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `ObjectFilter` | KindOfFilter | `0xfc` | - |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `SpeechDuration` | Duration | `0xd4` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |
| `UpdateInterval` | Duration | `0xd8` | `0` |
| `WaveWidth` | Real | `0xe8` | `0` |

## RubbleRiseUpdate

`sizeof(ModuleData)` = 0xd8, 16 fields

| field | type | offset | default |
|---|---|---|---|
| `BigBurstFrequency` | Int | `0x48` | `0` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `FXList` | MomentFXList | `0x0` | - |
| `MaxBurstDelay` | Duration | `0x44` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MaxRubbleRiseDelay` | Duration | `0x3c` | `0` |
| `MaxShudder` | Real | `0x54` | `0` |
| `MinBurstDelay` | Duration | `0x40` | `9999` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `MinRubbleRiseDelay` | Duration | `0x38` | `0` |
| `OCL` | MomentOCL | `0x0` | - |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `RubbleHeight` | Real | `0x50` | `0` |
| `RubbleRiseDamping` | Real | `0x4c` | `0` |

## RunOffMapBehavior

`sizeof(ModuleData)` = 0x1c, 4 fields

| field | type | offset | default |
|---|---|---|---|
| `DieOnMap` | Bool | `0x18` | `No` |
| `RequiresSpecificTrigger` | Bool | `0x10` | `No` |
| `RunOffMapWaypointName` | AsciiString | `0x14` | `""` |
| `RunToLocation` | Coord3D | `0x8` | `10` |

## SalvageCrateCollide

`sizeof(ModuleData)` = 0x80, 20 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowAIPickup` | Bool | `0x7c` | `No` |
| `BannerChance` | Percent | `0x60` | `0` |
| `BuildingPickup` | Bool | `0x41` | `No` |
| `ExecuteAnimation` | AsciiString | `0x4c` | - |
| `ExecuteAnimationFades` | Bool | `0x58` | `Yes` |
| `ExecuteAnimationTime` | Real | `0x50` | `0` |
| `ExecuteAnimationZRise` | Real | `0x54` | `0` |
| `ExecuteFX` | FXList | `0x48` | `0` |
| `ForbiddenKindOf` | KindOfFlags | `0x24` | - |
| `ForbidOwnerPlayer` | Bool | `0x40` | `No` |
| `HumanOnly` | Bool | `0x42` | `No` |
| `LevelUpChance` | Percent | `0x64` | `0.5` |
| `LevelUpRadius` | Percent | `0x68` | `100` |
| `MaxResource` | Int | `0x74` | `5000` |
| `MinResource` | Int | `0x70` | `100` |
| `PickupScience` | ScienceType | `0x44` | `-1` |
| `PorterChance` | Percent | `0x5c` | `0` |
| `RequiredKindOf` | KindOfFlags | `0x8` | - |
| `ResourceChance` | Percent | `0x6c` | `0.5` |
| `Upgrade` | AsciiString | `0x78` | `0` |

## ScaleWallSpecialAbilityUpdate

`sizeof(ModuleData)` = 0xd4, 61 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DelayAtFootOfWall` | Duration | `0xd0` | `0` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |

## ScavengerSpecialPower

`sizeof(ModuleData)` = 0x80, 36 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BountyPercent` | Real | `0x7c` | `0` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `GiveLevels` | Int | `0x58` | `0` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## ShareExperienceBehavior

`sizeof(ModuleData)` = 0x18, 4 fields

| field | type | offset | default |
|---|---|---|---|
| `DropOff` | Real | `0xc` | `0` |
| `ObjectFilter` | KindOfFilter | `0x14` | - |
| `Percentage` | Real | `0x10` | `1` |
| `Radius` | Real | `0x8` | `0` |

## ShipSlowDeathBehavior

`sizeof(ModuleData)` = 0x190, 27 fields

| field | type | offset | default |
|---|---|---|---|
| `DamageAmountRequired` | Real | `0x24` | - |
| `DeathFlags` | 0x008612e7 | `0x0` | - |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DecayBeginTime` | Duration | `0x54` | `0` |
| `DestructionDelay` | Duration | `0x4c` | `0` |
| `DestructionDelayVariance` | Duration | `0x50` | `0` |
| `DoNotRandomizeMidpoint` | Bool | `0x18e` | `No` |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `FadeDelay` | Duration | `0x188` | `4207599104` |
| `FadeTime` | Duration | `0x184` | `6` |
| `FlingForce` | Real | `0x118` | `0` |
| `FlingForceVariance` | Real | `0x11c` | `0` |
| `FlingPitch` | AngleReal | `0x120` | `0` |
| `FlingPitchVariance` | AngleReal | `0x124` | `0` |
| `FX` | MomentFXList | `0x0` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `ModifierBonusPerOverkillPercent` | Percent | `0x40` | `0` |
| `OCL` | MomentOCL | `0x0` | - |
| `ProbabilityModifier` | Int | `0x3c` | `10` |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `ShadowWhenDead` | Bool | `0x18d` | `No` |
| `SinkDelay` | Duration | `0x44` | `0` |
| `SinkDelayVariance` | Duration | `0x48` | `0` |
| `SinkRate` | VelocityReal | `0x38` | `0` |
| `Sound` | MomentSound | `0x0` | - |
| `Weapon` | MomentWeapon | `0x0` | - |

## ShroudCrateCollide

`sizeof(ModuleData)` = 0x5c, 11 fields

| field | type | offset | default |
|---|---|---|---|
| `BuildingPickup` | Bool | `0x41` | `No` |
| `ExecuteAnimation` | AsciiString | `0x4c` | - |
| `ExecuteAnimationFades` | Bool | `0x58` | `Yes` |
| `ExecuteAnimationTime` | Real | `0x50` | `0` |
| `ExecuteAnimationZRise` | Real | `0x54` | `0` |
| `ExecuteFX` | FXList | `0x48` | `0` |
| `ForbiddenKindOf` | KindOfFlags | `0x24` | - |
| `ForbidOwnerPlayer` | Bool | `0x40` | `No` |
| `HumanOnly` | Bool | `0x42` | `No` |
| `PickupScience` | ScienceType | `0x44` | `-1` |
| `RequiredKindOf` | KindOfFlags | `0x8` | - |

## SiegeAIUpdate

`sizeof(ModuleData)` = 0x64, 19 fields

| field | type | offset | default |
|---|---|---|---|
| `AILuaEventsList` | AsciiString | `0x2c` | `0` |
| `AttackPriority` | AsciiString | `0x44` | `"DefaultAttackPriority"` |
| `AutoAcquireEnemiesWhenIdle` | BitFlags | `0x1c` | `0` |
| `BurningDeathTime` | Duration | `0x40` | `0` |
| `CanAttackWhileContained` | Bool | `0x25` | `No` |
| `ComboLocoAttackDistance` | Real | `0x4c` | `80` |
| `ComboLocomotorSet` | Enum | `0x50` | `0` |
| `FadeOnPortals` | Bool | `0x54` | `No` |
| `HoldGroundCloseRangeDistance` | Real | `0x28` | `0` |
| `MaxCowerTime` | Duration | `0x30` | `0` |
| `MinCowerTime` | Duration | `0x34` | `0` |
| `MoodAttackCheckRate` | Duration | `0x18` | - |
| `RampageRequiresAflame` | Bool | `0x3c` | `No` |
| `RampageTime` | Duration | `0x38` | `0` |
| `SpecialContactPoints` | AsciiStringList | `0x58` | `0` |
| `StandGround` | Bool | `0x24` | `No` |
| `StopChaseDistance` | Real | `0x20` | `500` |
| `TimeToEjectPassengersOnRampage` | Duration | `0x48` | `0` |
| `Turret` | 0x006620a2 | `0x14` | `0` |

## SiegeDeployHordeSpecialPower

`sizeof(ModuleData)` = 0x1c, 4 fields

| field | type | offset | default |
|---|---|---|---|
| `HordeDeploy` | Bool | `0x18` | `No` |
| `InitiateSound` | AudioEventRTS | `0xc` | `-1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0x14` | `No` |

## SiegeDeploySpecialPower

`sizeof(ModuleData)` = 0x30, 11 fields

| field | type | offset | default |
|---|---|---|---|
| `AwayFromWallWaitDist` | Real | `0x28` | `200` |
| `EvacuateCrewOnDeploy` | Bool | `0x21` | `No` |
| `EvacuatePassengersOnDeploy` | Bool | `0x20` | `Yes` |
| `ExtraWallDistance` | Real | `0x2c` | `0` |
| `InitiateSound` | AudioEventRTS | `0xc` | `-1` |
| `LowerDelay` | Duration | `0x18` | `0` |
| `RaiseDelay` | Duration | `0x1c` | `0` |
| `SkipAdjustPosition` | Bool | `0x22` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0x14` | `No` |
| `WallSearchDistance` | Real | `0x24` | `500` |

## SiegeDockingBehavior

`sizeof(ModuleData)` = 0xc, 1 field

| field | type | offset | default |
|---|---|---|---|
| `DUMMY` | Int | `0x8` | `0` |

## SiegeEngineContain

`sizeof(ModuleData)` = 0x1b8, 70 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowAlliesInside` | Bool | `0x7d` | `No` |
| `AllowEnemiesInside` | Bool | `0x7e` | `No` |
| `AllowNeutralInside` | Bool | `0x7f` | `No` |
| `AllowOwnPlayerInsideOverride` | Bool | `0x7c` | `No` |
| `BoneSpecificConditionState` | 0x008678eb | `0x0` | - |
| `CanGrabStructure` | Bool | `0x13d` | `No` |
| `CollidePickup` | Bool | `0x81` | `No` |
| `ConditionForEntry` | ModelConditionFlag | `0x14c` | `-1` |
| `ContainMax` | Int | `0x70` | `-1` |
| `CrewAllowedToFire` | Bool | `0x1a0` | `No` |
| `CrewFilter` | KindOfFilter | `0x18c` | `0` |
| `CrewMax` | Int | `0x190` | `0` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DamagePercentToUnits` | Percent | `0x6c` | `0` |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DestroyRidersWhoAreNotFreeToExit` | Bool | `0x142` | `No` |
| `DoorOpenTime` | Duration | `0x78` | `0` |
| `EjectPassengersOnDeath` | Bool | `0x82` | `No` |
| `Enabled` | Bool | `0x84` | `No` |
| `EnterFadeTime` | Real | `0x170` | `0` |
| `EnterSound` | AudioEventRTS | `0x38` | `0` |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `ExitBone` | AsciiString | `0xa0` | `0` |
| `ExitDelay` | Duration | `0xac` | `0` |
| `ExitFadeTime` | Real | `0x174` | `0` |
| `ExitPitchRate` | AngularVelocityReal | `0x9c` | `0` |
| `ExitSound` | AudioEventRTS | `0x3c` | `0` |
| `FadeFilter` | KindOfFilter | `0x168` | - |
| `FadePassengerOnEnter` | Bool | `0x16c` | `No` |
| `FadePassengerOnExit` | Bool | `0x16d` | `No` |
| `FadeReverse` | Bool | `0x178` | `No` |
| `FireGrabWeaponOnVictim` | Bool | `0x148` | `Yes` |
| `ForceOrientationContainer` | Bool | `0x13c` | `Yes` |
| `GoAggressiveOnExit` | Bool | `0x140` | `No` |
| `GrabWeapon` | WeaponTemplate | `0x144` | `0` |
| `HealthRegen%PerSec` | Real | `0xa8` | `0` |
| `InitialCrew` | 0x0087ec0b | `0x0` | - |
| `InitialPayload` | 0x0086af0a | `0x0` | - |
| `KillPassengersOnDeath` | Bool | `0x83` | `No` |
| `ManualPickUpFilter` | KindOfFilter | `0x44` | `0` |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `ModifierRequiredTime` | Duration | `0x94` | `100` |
| `ModifierToGiveOnExit` | AsciiStringList | `0x88` | - |
| `NumberOfExitPaths` | Int | `0x74` | `0` |
| `ObjectStatusOfContained` | ObjectStatusFlags | `0x58` | `0` |
| `ObjectStatusOfCrew` | ObjectStatusFlags | `0x1a4` | `0` |
| `OrientLikeContainerOnExit` | Bool | `0x13f` | `No` |
| `PassengerBonePrefix` | PassengerBonePrefix | `0x0` | - |
| `PassengerFilter` | KindOfFilter | `0x40` | - |
| `PassengersInTurret` | Bool | `0x85` | `No` |
| `PassengersTestCollisionHeight` | Real | `0x68` | `-1000` |
| `ReleaseSnappyness` | Real | `0x17c` | `0.7` |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `ResetMoodCheckTimeOnExit` | Bool | `0x141` | `Yes` |
| `ScatterNearbyOnExit` | Bool | `0x13e` | `Yes` |
| `ShouldThrowOutPassengers` | Bool | `0x150` | `No` |
| `ShowPips` | Bool | `0x80` | `No` |
| `Slots` | Int | `0x98` | `0` |
| `SpeedPercentPerCrew` | Percent | `0x19c` | `1` |
| `ThrowOutPassengersDelay` | Duration | `0x154` | `0` |
| `ThrowOutPassengersLandingWarhead` | WeaponTemplate | `0x164` | `0` |
| `ThrowOutPassengersVelocity` | Coord3D | `0x158` | - |
| `TransferSelection` | Bool | `0x1b4` | `No` |
| `TypeOneForWeaponSet` | KindOfFlags | `0xb0` | - |
| `TypeOneForWeaponState` | KindOfFlags | `0xe8` | - |
| `TypeThreeForWeaponState` | KindOfFlags | `0x120` | - |
| `TypeTwoForWeaponSet` | KindOfFlags | `0xcc` | `0` |
| `TypeTwoForWeaponState` | KindOfFlags | `0x104` | - |
| `UpgradeCreationTrigger` | 0x0086ba2c | `0x0` | - |

## SlaughterHordeContain

`sizeof(ModuleData)` = 0xec, 42 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowAlliesInside` | Bool | `0x7d` | `No` |
| `AllowEnemiesInside` | Bool | `0x7e` | `No` |
| `AllowNeutralInside` | Bool | `0x7f` | `No` |
| `AllowOwnPlayerInsideOverride` | Bool | `0x7c` | `No` |
| `BoneSpecificConditionState` | 0x008678eb | `0x0` | - |
| `CanAlwaysEnter` | KindOfFilter | `0xd8` | - |
| `CashBackPercent` | Percent | `0xd4` | `0.5` |
| `CollidePickup` | Bool | `0x81` | `No` |
| `ContainMax` | Int | `0x70` | `-1` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DamagePercentToUnits` | Percent | `0x6c` | `0` |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DoorOpenTime` | Duration | `0x78` | `0` |
| `EjectPassengersOnDeath` | Bool | `0x82` | `No` |
| `Enabled` | Bool | `0x84` | `No` |
| `EnterSound` | AudioEventRTS | `0x38` | `0` |
| `EntryOffset` | Coord3D | `0xb0` | - |
| `EntryPosition` | Coord3D | `0xbc` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `ExitDelay` | Duration | `0xac` | `0` |
| `ExitOffset` | Coord3D | `0xc8` | `1` |
| `ExitSound` | AudioEventRTS | `0x3c` | `0` |
| `HealObjects` | Bool | `0x98` | `No` |
| `ImmuneToClearBuildingAttacks` | Bool | `0xa1` | `No` |
| `InitialRoster` | 0x00653381 | `0x0` | - |
| `KillPassengersOnDeath` | Bool | `0x83` | `No` |
| `ManualPickUpFilter` | KindOfFilter | `0x44` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `MobileGarrison` | Bool | `0xa0` | `No` |
| `ModifierRequiredTime` | Duration | `0x94` | `100` |
| `ModifierToGiveOnExit` | AsciiStringList | `0x88` | - |
| `NumberOfExitPaths` | Int | `0x74` | `0` |
| `ObjectStatusOfContained` | ObjectStatusFlags | `0x58` | `0` |
| `PassengerBonePrefix` | PassengerBonePrefix | `0x0` | - |
| `PassengerFilter` | KindOfFilter | `0x40` | - |
| `PassengersInTurret` | Bool | `0x85` | `No` |
| `PassengersTestCollisionHeight` | Real | `0x68` | `-1000` |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `ShowPips` | Bool | `0x80` | `No` |
| `StatusRequiredForCanAlwaysEnter` | ObjectStatusFlags | `0xdc` | - |
| `TimeForFullHeal` | DurationReal | `0x9c` | `1` |

## SlavedUpdate

`sizeof(ModuleData)` = 0x70, 26 fields

| field | type | offset | default |
|---|---|---|---|
| `AttackRange` | Int | `0x14` | `0` |
| `AttackWanderRange` | Int | `0x18` | `0` |
| `DieOnMastersDeath` | Bool | `0x55` | `No` |
| `DistToTargetToGrantRangeBonus` | Int | `0x24` | `0` |
| `FadeOutRange` | Int | `0x64` | `0` |
| `FadeTime` | Duration | `0x68` | `0` |
| `GuardMaxRange` | Int | `0xc` | `0` |
| `GuardPositionOffset` | Coord3D | `0x58` | `0` |
| `GuardWanderRange` | Int | `0x10` | - |
| `LeashRange` | Int | `0x8` | `0` |
| `MarkUnselectable` | Bool | `0x6c` | `Yes` |
| `RepairMaxAltitude` | Real | `0x30` | `0` |
| `RepairMaxReadyTime` | Duration | `0x40` | `0` |
| `RepairMaxWeldTime` | Duration | `0x48` | `0` |
| `RepairMinAltitude` | Real | `0x2c` | `0` |
| `RepairMinReadyTime` | Duration | `0x3c` | `0` |
| `RepairMinWeldTime` | Duration | `0x44` | `0` |
| `RepairRange` | Int | `0x28` | - |
| `RepairRatePerSecond` | Real | `0x34` | `0` |
| `RepairWeldingFXBone` | AsciiString | `0x50` | `0` |
| `RepairWeldingSys` | AsciiString | `0x4c` | `0` |
| `RepairWhenBelowHealth%` | Int | `0x38` | `0` |
| `ScoutRange` | Int | `0x1c` | `0` |
| `ScoutWanderRange` | Int | `0x20` | `0` |
| `StayOnSameLayerAsMaster` | Bool | `0x54` | `No` |
| `UseSlaverAsControlForEvaObjectSightedEvents` | Bool | `0x6d` | `No` |

## SlaveWatcherBehavior

`sizeof(ModuleData)` = 0x14, 4 fields

| field | type | offset | default |
|---|---|---|---|
| `GrantUpgrade` | AsciiString | `0x8` | `0` |
| `LetSlaveLive` | Bool | `0x11` | `No` |
| `RemoveUpgrade` | AsciiString | `0xc` | `0` |
| `ShareUpgrades` | Bool | `0x10` | `No` |

## SlowDeathBehavior

`sizeof(ModuleData)` = 0x190, 27 fields

| field | type | offset | default |
|---|---|---|---|
| `DamageAmountRequired` | Real | `0x24` | - |
| `DeathFlags` | 0x008612e7 | `0x0` | - |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DecayBeginTime` | Duration | `0x54` | `0` |
| `DestructionDelay` | Duration | `0x4c` | `0` |
| `DestructionDelayVariance` | Duration | `0x50` | `0` |
| `DoNotRandomizeMidpoint` | Bool | `0x18e` | `No` |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `FadeDelay` | Duration | `0x188` | `4207599104` |
| `FadeTime` | Duration | `0x184` | `6` |
| `FlingForce` | Real | `0x118` | `0` |
| `FlingForceVariance` | Real | `0x11c` | `0` |
| `FlingPitch` | AngleReal | `0x120` | `0` |
| `FlingPitchVariance` | AngleReal | `0x124` | `0` |
| `FX` | MomentFXList | `0x0` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `ModifierBonusPerOverkillPercent` | Percent | `0x40` | `0` |
| `OCL` | MomentOCL | `0x0` | - |
| `ProbabilityModifier` | Int | `0x3c` | `10` |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `ShadowWhenDead` | Bool | `0x18d` | `No` |
| `SinkDelay` | Duration | `0x44` | `0` |
| `SinkDelayVariance` | Duration | `0x48` | `0` |
| `SinkRate` | VelocityReal | `0x38` | `0` |
| `Sound` | MomentSound | `0x0` | - |
| `Weapon` | MomentWeapon | `0x0` | - |

## SpawnBehavior

`sizeof(ModuleData)` = 0x194, 27 fields

| field | type | offset | default |
|---|---|---|---|
| `AggregateHealth` | Bool | `0x16` | `No` |
| `CanReclaimOrphans` | Bool | `0x15` | `No` |
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `ExitByBudding` | Bool | `0x17` | `No` |
| `FadeInTime` | Int | `0x18c` | `0` |
| `InitialBurst` | Int | `0x10` | `0` |
| `KillSpawnsBasedOnModelConditionState` | Bool | `0x190` | `No` |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `OneShot` | Bool | `0x14` | `No` |
| `Permanent` | Bool | `0x12e` | - |
| `PropagateDamageTypesToSlavesWhenExisting` | DamageTypeFlags | `0x1c` | - |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | `0` |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | - |
| `RespectCommandLimit` | Bool | `0x19` | `No` |
| `ShareUpgrades` | Bool | `0x191` | `No` |
| `SpawnedRequireSpawner` | Bool | `0x18` | `No` |
| `SpawnInsideBuilding` | Bool | `0x192` | `No` |
| `SpawnNumber` | Int | `0x8` | `0` |
| `SpawnReplaceDelay` | Duration | `0xc` | `0` |
| `SpawnTemplateName` | AsciiStringList | `0x20` | - |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## SpawnedModelConditionCreate

`sizeof(ModuleData)` = 0x14, 1 field

| field | type | offset | default |
|---|---|---|---|
| `SpawnerTrigger` | 0x007a7b81 | `0x0` | - |

## SpawnPointProductionExitUpdate

`sizeof(ModuleData)` = 0xc, 1 field

| field | type | offset | default |
|---|---|---|---|
| `SpawnPointBoneName` | AsciiString | `0x8` | - |

## SpawnUnitBehavior

`sizeof(ModuleData)` = 0x20, 3 fields

| field | type | offset | default |
|---|---|---|---|
| `SpawnOnce` | Bool | `0x1c` | `No` |
| `UnitCommand` | AsciiString | `0xc` | - |
| `UnitName` | AsciiString | `0x8` | `""` |

## SpecialAbilityUpdate

`sizeof(ModuleData)` = 0xd0, 60 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |

## SpecialDisguiseUpdate

`sizeof(ModuleData)` = 0xe8, 66 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DisguiseAsTemplate` | AsciiString | `0xd8` | `0` |
| `DisguisedAsTemplate_EnemyPerspective` | AsciiString | `0xdc` | `0` |
| `DisguiseFX` | FXList | `0xe0` | `0` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `ForceMountedWhenDisguising` | Bool | `0xe4` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `OpacityTarget` | Real | `0xd4` | `0` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerInstantlyOnCreate` | Bool | `0xd0` | `No` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |

## SpecialEnemySenseUpdate

`sizeof(ModuleData)` = 0x14, 3 fields

| field | type | offset | default |
|---|---|---|---|
| `ScanInterval` | Duration | `0x10` | `1` |
| `ScanRange` | Real | `0xc` | `0` |
| `SpecialEnemyFilter` | KindOfFilter | `0x8` | - |

## SpecialPowerCompletionDie

`sizeof(ModuleData)` = 0x3c, 7 fields

| field | type | offset | default |
|---|---|---|---|
| `DamageAmountRequired` | Real | `0x24` | - |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |

## SpecialPowerModule

`sizeof(ModuleData)` = 0x7c, 35 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `GiveLevels` | Int | `0x58` | `0` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## SpecialPowerTimerRefreshSpecialPower

`sizeof(ModuleData)` = 0x7c, 35 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `GiveLevels` | Int | `0x58` | `0` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## SpellRechargeModifierUpgrade

`sizeof(ModuleData)` = 0x14c, 9 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `LabelForPalantirString` | AsciiString | `0x148` | `">UNSPECIFIED<"` |
| `Percentage` | 0x008ba26f | `0x138` | `0` |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `StartsActive` | Bool | `0x144` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | `0` |

## StancesBehavior

`sizeof(ModuleData)` = 0xc, 1 field

| field | type | offset | default |
|---|---|---|---|
| `StanceTemplate` | 0x00548990 | `0x8` | `0` |

## StatusBitsUpgrade

`sizeof(ModuleData)` = 0x158, 8 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `StatusToClear` | ObjectStatusFlags | `0x148` | - |
| `StatusToSet` | ObjectStatusFlags | `0x138` | - |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## StatusBitsUpgradeIfEldestKindof

`sizeof(ModuleData)` = 0x15c, 9 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `ObjectFilter` | KindOfFilter | `0x158` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `StatusToClear` | ObjectStatusFlags | `0x148` | - |
| `StatusToSet` | ObjectStatusFlags | `0x138` | - |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## StealthDetectorUpdate

`sizeof(ModuleData)` = 0x70, 16 fields

| field | type | offset | default |
|---|---|---|---|
| `CancelOneRingEffect` | Bool | `0x6a` | `No` |
| `CanDetectWhileContained` | Bool | `0x69` | `No` |
| `CanDetectWhileGarrisoned` | Bool | `0x68` | `No` |
| `DetectionRange` | Real | `0xc` | `0` |
| `DetectionRate` | Duration | `0x8` | `1` |
| `ExtraForbiddenKindOf` | KindOfFlags | `0x4c` | - |
| `ExtraRequiredKindOf` | KindOfFlags | `0x30` | - |
| `InitiallyDisabled` | Bool | `0x10` | `No` |
| `IRBeaconParticleSysName` | ParticleSystem | `0x1c` | `0` |
| `IRBrightParticleSysName` | ParticleSystem | `0x24` | `0` |
| `IRGridParticleSysName` | ParticleSystem | `0x28` | `0` |
| `IRParticleSysBone` | AsciiString | `0x2c` | `0` |
| `IRParticleSysName` | ParticleSystem | `0x20` | `0` |
| `LoudPingSound` | AudioEventRTS | `0x18` | `0` |
| `PingSound` | AudioEventRTS | `0x14` | `0` |
| `RequiredUpgrade` | AsciiString | `0x6c` | `0` |

## StealthUpdate

`sizeof(ModuleData)` = 0xc8, 36 fields

| field | type | offset | default |
|---|---|---|---|
| `BecomeStealthedFX` | FXList | `0x44` | `0` |
| `BecomeStealthedOneRingFX` | FXList | `0x4c` | `0` |
| `DetectedByAnyoneRange` | Real | `0x60` | `0` |
| `DetectedByFriendliesOnly` | Bool | `0x56` | `No` |
| `DisguiseFX` | FXList | `0x40` | `0` |
| `DisguiseRevealFX` | FXList | `0x3c` | `0` |
| `DisguiseRevealTransitionTime` | Duration | `0x5c` | `0` |
| `DisguisesAsTeam` | Bool | `0x30` | `No` |
| `DisguiseTransitionTime` | Duration | `0x58` | `0` |
| `EvaEventDetectedAlly` | EvaEvent | `0xa8` | `-1` |
| `EvaEventDetectedEnemy` | EvaEvent | `0xa4` | `-1` |
| `EvaEventDetectedOwner` | EvaEvent | `0xac` | `-1` |
| `ExitStealthFX` | FXList | `0x48` | `0` |
| `ExitStealthOneRingFX` | FXList | `0x50` | `0` |
| `ForbiddenUpgradeNames` | AsciiStringList | `0xbc` | `0` |
| `FriendlyOpacityMax` | Percent | `0x28` | `1` |
| `FriendlyOpacityMin` | Percent | `0x24` | `0.5` |
| `HintDetectableConditions` | ObjectStatusFlags | `0x10` | - |
| `InnateStealth` | Bool | `0x55` | `Yes` |
| `MoveThresholdSpeed` | VelocityReal | `0x20` | `0` |
| `OneRingDelayOff` | Duration | `0x94` | - |
| `OneRingDelayOn` | Duration | `0x90` | - |
| `OrderIdleEnemiesToAttackMeUponReveal` | Bool | `0x38` | `No` |
| `PulseFrequency` | Duration | `0x2c` | `30` |
| `RemoveTerrainRestrictionOnUpgrade` | AsciiStringList | `0x74` | - |
| `RequiredUpgradeNames` | AsciiStringList | `0xb0` | `0` |
| `RevealDistanceFromTarget` | Real | `0x34` | `0` |
| `RevealWeaponSets` | WeaponSetFlags | `0x64` | - |
| `RingAnimTimeOff` | Duration | `0x9c` | `0` |
| `RingAnimTimeOn` | Duration | `0x98` | `0` |
| `RingDelayAfterRemoving` | Duration | `0xa0` | `0` |
| `StartsActive` | Bool | `0x54` | `Yes` |
| `StealthDelay` | Duration | `0x8` | `-1` |
| `StealthForbiddenConditions` | BitFlags | `0xc` | `0` |
| `VoiceEnterStateMoveToStealthyArea` | AudioEventRTS | `0x88` | `-1` |
| `VoiceMoveToStealthyArea` | AudioEventRTS | `0x80` | `-1` |

## StealthUpgrade

`sizeof(ModuleData)` = 0x138, 6 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## StopSpecialPower

`sizeof(ModuleData)` = 0x80, 36 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `GiveLevels` | Int | `0x58` | `0` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `StopPowerTemplate` | SpecialPowerTemplate | `0x7c` | `0` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## StoreObjectsSpecialPower

`sizeof(ModuleData)` = 0xd4, 61 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `Radius` | Real | `0xd0` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |

## StrafeAreaUpdate

`sizeof(ModuleData)` = 0x20, 6 fields

| field | type | offset | default |
|---|---|---|---|
| `InitialSweepPhase` | Real | `0x1c` | `0` |
| `Slope` | Real | `0x18` | `50` |
| `StrafeAreaRadius` | Real | `0xc` | `150` |
| `SweepAmplitude` | Real | `0x14` | `100` |
| `Sweepfrequency` | Real | `0x10` | `0.4` |
| `WeaponName` | AsciiString | `0x8` | - |

## StructureBody

`sizeof(ModuleData)` = 0x64, 21 fields

| field | type | offset | default |
|---|---|---|---|
| `BurningDeathBehavior` | Bool | `0x51` | `No` |
| `BurningDeathFX` | FXList | `0x54` | `0` |
| `CheerRadius` | Real | `0x4c` | `200` |
| `DamageCreationList` | DamageCreationList | `0x0` | - |
| `DamagedAttributeModifier` | AsciiString | `0x30` | `0` |
| `DodgePercent` | Percent | `0x18` | `0` |
| `EnteringDamagedTransitionTime` | Duration | `0x1c` | `0` |
| `EnteringReallyDamagedTransitionTime` | Duration | `0x20` | `0` |
| `GrabDamage` | Real | `0x3c` | `200` |
| `GrabFX` | FXList | `0x38` | `0` |
| `GrabObject` | AsciiString | `0x2c` | - |
| `GrabOffset` | Coord3D | `0x40` | `0` |
| `HealingBuffFx` | FXList | `0x48` | - |
| `InitialHealth` | Real | `0xc` | `-1` |
| `MaxHealth` | Real | `0x8` | `0` |
| `MaxHealthDamaged` | Real | `0x10` | `0` |
| `MaxHealthReallyDamaged` | Real | `0x14` | `0` |
| `ReallyDamagedAttributeModifier` | AsciiString | `0x34` | `0` |
| `RecoveryTime` | Duration | `0x24` | `0` |
| `RemoveUpgradesOnDeath` | Bool | `0x50` | `No` |
| `UseDefaultDamageSettings` | Bool | `0x28` | `Yes` |

## StructureCollapseUpdate

`sizeof(ModuleData)` = 0xfc, 17 fields

| field | type | offset | default |
|---|---|---|---|
| `BigBurstFrequency` | Int | `0x48` | `0` |
| `CollapseDamping` | Real | `0x4c` | `0` |
| `CollapseHeight` | Real | `0xf8` | `0` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DestroyObjectWhenDone` | Bool | `0xf4` | `No` |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `FXList` | MomentFXList | `0x0` | - |
| `MaxBurstDelay` | Duration | `0x44` | - |
| `MaxCollapseDelay` | Duration | `0x3c` | `0` |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MaxShudder` | Real | `0x50` | `0` |
| `MinBurstDelay` | Duration | `0x40` | `9999` |
| `MinCollapseDelay` | Duration | `0x38` | `0` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `OCL` | MomentOCL | `0x0` | - |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |

## StructureToppleUpdate

`sizeof(ModuleData)` = 0xbc, 23 fields

| field | type | offset | default |
|---|---|---|---|
| `AngleFX` | AngleFXList | `0x0` | - |
| `CrushingFX` | FXList | `0x60` | `0` |
| `CrushingWeaponName` | AsciiString | `0x64` | `""` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DamageFXTypes` | DamageTypeFlags | `0x4c` | `-1` |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `ForceToppleAngle` | Real | `0xb8` | `-9.87654` |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MaxToppleBurstDelay` | Duration | `0x6c` | `0` |
| `MaxToppleDelay` | Duration | `0x3c` | `0` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `MinToppleBurstDelay` | Duration | `0x68` | `0` |
| `MinToppleDelay` | Duration | `0x38` | `0` |
| `OCL` | MomentOCL | `0x0` | - |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `StructuralDecay` | Real | `0x44` | `0` |
| `StructuralIntegrity` | Real | `0x40` | `0.1` |
| `ToppleAccelerationFactor` | Real | `0x48` | `0.06` |
| `ToppleDelayFX` | FXList | `0x54` | `0` |
| `ToppleDoneFX` | FXList | `0x5c` | `0` |
| `ToppleStartFX` | FXList | `0x50` | `0` |
| `TopplingFX` | FXList | `0x58` | `0` |

## SubObjectsUpgrade

`sizeof(ModuleData)` = 0x174, 16 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `ExcludeSubobjects` | AsciiStringList | `0x150` | `0` |
| `FadeTimeInSeconds` | Real | `0x168` | `0.5` |
| `HideSubObjects` | AsciiStringList | `0x144` | `0` |
| `HideSubObjectsOnRemove` | Bool | `0x172` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RecolorHouse` | Bool | `0x170` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `ShowSubObjects` | AsciiStringList | `0x138` | `0` |
| `SkipFadeOnCreate` | Bool | `0x171` | - |
| `TriggeredBy` | UpgradeMask | `0x0` | - |
| `UnHideSubObjectsOnRemove` | Bool | `0x173` | - |
| `UpgradeTexture` | 0x008b9420 | `0x15c` | `0` |
| `WaitBeforeFadeInSeconds` | Real | `0x16c` | `0` |

## SummonReplacementSpecialAbilityUpdate

`sizeof(ModuleData)` = 0xf8, 70 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `CancelDisguiseWhenDismounting` | Bool | `0xe5` | `No` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `EmotionPulseRadius` | Real | `0xd8` | `50` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GenerateTerror` | Bool | `0xd4` | `No` |
| `GenerateUncontrollableFear` | Bool | `0xd5` | `No` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MountedTemplate` | AsciiString | `0xe8` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `ObjectFilter` | KindOfFilter | `0xdc` | - |
| `OpacityTarget` | Real | `0xe0` | `0` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `SynchronizeTimerOnSpecialPower` | AsciiStringList | `0xec` | `0` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerInstantlyOnCreate` | Bool | `0xe4` | `No` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |
| `WhichSpecialPower` | Int | `0xd0` | `1` |

## SupplyCenterDockUpdate

`sizeof(ModuleData)` = 0x1c, 5 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowsPassthrough` | Bool | `0xc` | `Yes` |
| `BonusScience` | ScienceType | `0x14` | `-1` |
| `BonusScienceMultiplier` | Percent | `0x18` | `1` |
| `NumberApproachPositions` | Int | `0x8` | `0` |
| `ValueMultiplier` | Real | `0x10` | `1` |

## SupplyCenterProductionExitUpdate

`sizeof(ModuleData)` = 0x20, 2 fields

| field | type | offset | default |
|---|---|---|---|
| `NaturalRallyPoint` | Coord3D | `0x14` | - |
| `UnitCreatePoint` | Coord3D | `0x8` | - |

## SupplyTruckAIUpdate

`sizeof(ModuleData)` = 0x84, 27 fields

| field | type | offset | default |
|---|---|---|---|
| `AILuaEventsList` | AsciiString | `0x2c` | `0` |
| `AttackPriority` | AsciiString | `0x44` | `"DefaultAttackPriority"` |
| `AutoAcquireEnemiesWhenIdle` | BitFlags | `0x1c` | `0` |
| `BurningDeathTime` | Duration | `0x40` | `0` |
| `CanAttackWhileContained` | Bool | `0x25` | `No` |
| `ComboLocoAttackDistance` | Real | `0x4c` | `80` |
| `ComboLocomotorSet` | Enum | `0x50` | `0` |
| `FadeOnPortals` | Bool | `0x54` | `No` |
| `HarvestActionTime` | Duration | `0x80` | `0` |
| `HarvestActivationRange` | Real | `0x78` | `50` |
| `HarvestPreparationTime` | Duration | `0x7c` | `0` |
| `HarvestTrees` | Bool | `0x74` | `No` |
| `HoldGroundCloseRangeDistance` | Real | `0x28` | `0` |
| `MaxBoxes` | Int | `0x64` | `0` |
| `MaxCowerTime` | Duration | `0x30` | `0` |
| `MinCowerTime` | Duration | `0x34` | `0` |
| `MoodAttackCheckRate` | Duration | `0x18` | - |
| `RampageRequiresAflame` | Bool | `0x3c` | `No` |
| `RampageTime` | Duration | `0x38` | `0` |
| `SpecialContactPoints` | AsciiStringList | `0x58` | `0` |
| `StandGround` | Bool | `0x24` | `No` |
| `StopChaseDistance` | Real | `0x20` | `500` |
| `SupplyCenterActionDelay` | Duration | `0x68` | `0` |
| `SupplyWarehouseActionDelay` | Duration | `0x6c` | `0` |
| `SupplyWarehouseScanDistance` | Real | `0x70` | `100` |
| `TimeToEjectPassengersOnRampage` | Duration | `0x48` | `0` |
| `Turret` | 0x006620a2 | `0x14` | `0` |

## SupplyWarehouseCripplingBehavior

`sizeof(ModuleData)` = 0x14, 3 fields

| field | type | offset | default |
|---|---|---|---|
| `SelfHealAmount` | Real | `0x10` | `0` |
| `SelfHealDelay` | Duration | `0xc` | `0` |
| `SelfHealSupression` | Duration | `0x8` | `0` |

## SupplyWarehouseDockUpdate

`sizeof(ModuleData)` = 0x18, 4 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowsPassthrough` | Bool | `0xc` | `Yes` |
| `DeleteWhenEmpty` | Bool | `0x14` | `No` |
| `NumberApproachPositions` | Int | `0x8` | `0` |
| `StartingBoxes` | Int | `0x10` | `1` |

## SymbioticStructuresBody

`sizeof(ModuleData)` = 0x68, 22 fields

| field | type | offset | default |
|---|---|---|---|
| `BurningDeathBehavior` | Bool | `0x51` | `No` |
| `BurningDeathFX` | FXList | `0x54` | `0` |
| `CheerRadius` | Real | `0x4c` | `200` |
| `DamageCreationList` | DamageCreationList | `0x0` | `0` |
| `DamagedAttributeModifier` | AsciiString | `0x30` | `0` |
| `DodgePercent` | Percent | `0x18` | `0` |
| `EnteringDamagedTransitionTime` | Duration | `0x1c` | `0` |
| `EnteringReallyDamagedTransitionTime` | Duration | `0x20` | `0` |
| `GrabDamage` | Real | `0x3c` | `200` |
| `GrabFX` | FXList | `0x38` | `0` |
| `GrabObject` | AsciiString | `0x2c` | - |
| `GrabOffset` | Coord3D | `0x40` | `0` |
| `HealingBuffFx` | FXList | `0x48` | - |
| `InitialHealth` | Real | `0xc` | `-1` |
| `MaxHealth` | Real | `0x8` | `0` |
| `MaxHealthDamaged` | Real | `0x10` | `0` |
| `MaxHealthReallyDamaged` | Real | `0x14` | `0` |
| `ReallyDamagedAttributeModifier` | AsciiString | `0x34` | `0` |
| `RecoveryTime` | Duration | `0x24` | `0` |
| `RemoveUpgradesOnDeath` | Bool | `0x50` | `No` |
| `Symbiote` | AsciiString | `0x64` | `"Not likely to duplicate this name, is he, Fred?"` |
| `UseDefaultDamageSettings` | Bool | `0x28` | `Yes` |

## TaintSpecialPower

`sizeof(ModuleData)` = 0x8c, 39 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `GiveLevels` | Int | `0x58` | `0` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `TaintFX` | FXList | `0x84` | `0` |
| `TaintObject` | AsciiString | `0x7c` | `0` |
| `TaintOCL` | ObjectCreationList | `0x88` | `0` |
| `TaintRadius` | Real | `0x80` | `10` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## TeleportSpecialAbilityUpdate

`sizeof(ModuleData)` = 0xe0, 64 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `BusyForDuration` | Duration | `0xd0` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DestinationWeaponName` | AsciiString | `0xd4` | `0` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxDistance` | Real | `0xdc` | `-1` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SourceWeaponName` | AsciiString | `0xd8` | `0` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |

## TeleportToCasterSpecialPower

`sizeof(ModuleData)` = 0xe4, 65 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxDestinationRadius` | Real | `0xd8` | `0` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MinDestinationRadius` | Real | `0xd4` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `Radius` | Real | `0xd0` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TargetFX` | FXList | `0xe0` | `0` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerFX` | FXList | `0xdc` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |

## TemporarilyDefectUpdate

`sizeof(ModuleData)` = 0xc, 1 field

| field | type | offset | default |
|---|---|---|---|
| `DefectDuration` | Duration | `0x8` | - |

## TerrainResourceBehavior

`sizeof(ModuleData)` = 0x24, 8 fields

| field | type | offset | default |
|---|---|---|---|
| `HighPriority` | Bool | `0x14` | `No` |
| `IncomeInterval` | Duration | `0x10` | `-1` |
| `MaxIncome` | Int | `0xc` | `0` |
| `Radius` | Real | `0x8` | `0` |
| `Upgrade` | UpgradeTemplate | `0x1c` | `0` |
| `UpgradeBonusPercent` | Percent | `0x20` | `1` |
| `UpgradeMustBePresent` | KindOfFilter | `0x18` | - |
| `Visible` | Bool | `0x15` | `Yes` |

## ThreatFinderUpdate

`sizeof(ModuleData)` = 0xc, 1 field

| field | type | offset | default |
|---|---|---|---|
| `DefaultRadius` | Real | `0x8` | `0` |

## ToggleDeploySpecialAbilityUpdate

`sizeof(ModuleData)` = 0xd8, 62 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SoundDeploy` | AudioEventRTS | `0xd0` | `0` |
| `SoundUndeploy` | AudioEventRTS | `0xd4` | `0` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |

## ToggleHiddenSpecialAbilityUpdate

`sizeof(ModuleData)` = 0xd4, 61 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `ShowPalantirTimer` | Bool | `0xd0` | `No` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |

## ToggleMountedSpecialAbilityUpdate

`sizeof(ModuleData)` = 0xe8, 65 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `CancelDisguiseWhenDismounting` | Bool | `0xd5` | `No` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MountedTemplate` | AsciiString | `0xd8` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `OpacityTarget` | Real | `0xd0` | `0` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `SynchronizeTimerOnSpecialPower` | AsciiStringList | `0xdc` | `0` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerInstantlyOnCreate` | Bool | `0xd4` | `No` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |

## TooltipUpgrade

`sizeof(ModuleData)` = 0x140, 8 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `Description` | AsciiString | `0x13c` | - |
| `DisplayName` | AsciiString | `0x138` | `""` |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | `0` |

## ToppleUpdate

`sizeof(ModuleData)` = 0x2c, 12 fields

| field | type | offset | default |
|---|---|---|---|
| `BounceFX` | FXList | `0xc` | `0` |
| `BounceVelocityPercent` | Percent | `0x1c` | `0.2` |
| `InitialAccelPercent` | Percent | `0x18` | `0.01` |
| `InitialVelocityPercent` | Percent | `0x14` | `0.2` |
| `KillStumpWhenToppled` | Bool | `0x26` | `No` |
| `KillWhenFinishedToppling` | Bool | `0x24` | `Yes` |
| `KillWhenStartToppling` | Bool | `0x25` | `No` |
| `MinimumToppleSpeed` | PositiveReal | `0x20` | `0.5` |
| `ReorientToppledRubble` | Bool | `0x28` | `No` |
| `StumpName` | AsciiString | `0x10` | - |
| `ToppleFX` | FXList | `0x8` | `0` |
| `ToppleLeftOrRightOnly` | Bool | `0x27` | `No` |

## TransitionDamageFX

`sizeof(ModuleData)` = 0x1040, 120 fields

| field | type | offset | default |
|---|---|---|---|
| `DamagedFXList1` | FXList | `0x15c` | - |
| `DamagedFXList10` | FXList | `0x258` | - |
| `DamagedFXList11` | FXList | `0x274` | - |
| `DamagedFXList12` | FXList | `0x290` | - |
| `DamagedFXList2` | FXList | `0x178` | - |
| `DamagedFXList3` | FXList | `0x194` | - |
| `DamagedFXList4` | FXList | `0x1b0` | - |
| `DamagedFXList5` | FXList | `0x1cc` | - |
| `DamagedFXList6` | FXList | `0x1e8` | - |
| `DamagedFXList7` | FXList | `0x204` | - |
| `DamagedFXList8` | FXList | `0x220` | - |
| `DamagedFXList9` | FXList | `0x23c` | - |
| `DamagedHideSubObject` | AsciiStringList | `0xfe0` | - |
| `DamagedOCL1` | ObjectCreationList | `0x6a0` | - |
| `DamagedOCL10` | ObjectCreationList | `0x79c` | - |
| `DamagedOCL11` | ObjectCreationList | `0x7b8` | - |
| `DamagedOCL12` | ObjectCreationList | `0x7d4` | - |
| `DamagedOCL2` | ObjectCreationList | `0x6bc` | - |
| `DamagedOCL3` | ObjectCreationList | `0x6d8` | - |
| `DamagedOCL4` | ObjectCreationList | `0x6f4` | - |
| `DamagedOCL5` | ObjectCreationList | `0x710` | - |
| `DamagedOCL6` | ObjectCreationList | `0x72c` | - |
| `DamagedOCL7` | ObjectCreationList | `0x748` | - |
| `DamagedOCL8` | ObjectCreationList | `0x764` | - |
| `DamagedOCL9` | ObjectCreationList | `0x780` | - |
| `DamagedParticleSystem1` | ParticleSystem | `0xbe4` | - |
| `DamagedParticleSystem10` | ParticleSystem | `0xce0` | - |
| `DamagedParticleSystem11` | ParticleSystem | `0xcfc` | - |
| `DamagedParticleSystem12` | ParticleSystem | `0xd18` | - |
| `DamagedParticleSystem2` | ParticleSystem | `0xc00` | - |
| `DamagedParticleSystem3` | ParticleSystem | `0xc1c` | - |
| `DamagedParticleSystem4` | ParticleSystem | `0xc38` | - |
| `DamagedParticleSystem5` | ParticleSystem | `0xc54` | - |
| `DamagedParticleSystem6` | ParticleSystem | `0xc70` | - |
| `DamagedParticleSystem7` | ParticleSystem | `0xc8c` | - |
| `DamagedParticleSystem8` | ParticleSystem | `0xca8` | - |
| `DamagedParticleSystem9` | ParticleSystem | `0xcc4` | - |
| `DamagedShowSubObject` | AsciiStringList | `0x1010` | - |
| `DamageFXTypes` | DamageTypeFlags | `0x8` | `-1` |
| `DamageOCLTypes` | DamageTypeFlags | `0x54c` | `-1` |
| `DamageParticleTypes` | DamageTypeFlags | `0xa90` | `-1` |
| `PristineHideSubObject` | AsciiStringList | `0xfd4` | - |
| `PristineShowSubObject` | AsciiStringList | `0x1004` | - |
| `ReallyDamagedFXList1` | FXList | `0x2ac` | - |
| `ReallyDamagedFXList10` | FXList | `0x3a8` | - |
| `ReallyDamagedFXList11` | FXList | `0x3c4` | - |
| `ReallyDamagedFXList12` | FXList | `0x3e0` | - |
| `ReallyDamagedFXList2` | FXList | `0x2c8` | - |
| `ReallyDamagedFXList3` | FXList | `0x2e4` | - |
| `ReallyDamagedFXList4` | FXList | `0x300` | - |
| `ReallyDamagedFXList5` | FXList | `0x31c` | - |
| `ReallyDamagedFXList6` | FXList | `0x338` | - |
| `ReallyDamagedFXList7` | FXList | `0x354` | - |
| `ReallyDamagedFXList8` | FXList | `0x370` | - |
| `ReallyDamagedFXList9` | FXList | `0x38c` | - |
| `ReallyDamagedHideSubObject` | AsciiStringList | `0xfec` | - |
| `ReallyDamagedOCL1` | ObjectCreationList | `0x7f0` | - |
| `ReallyDamagedOCL10` | ObjectCreationList | `0x8ec` | - |
| `ReallyDamagedOCL11` | ObjectCreationList | `0x908` | - |
| `ReallyDamagedOCL12` | ObjectCreationList | `0x924` | - |
| `ReallyDamagedOCL2` | ObjectCreationList | `0x80c` | - |
| `ReallyDamagedOCL3` | ObjectCreationList | `0x828` | - |
| `ReallyDamagedOCL4` | ObjectCreationList | `0x844` | - |
| `ReallyDamagedOCL5` | ObjectCreationList | `0x860` | - |
| `ReallyDamagedOCL6` | ObjectCreationList | `0x87c` | - |
| `ReallyDamagedOCL7` | ObjectCreationList | `0x898` | - |
| `ReallyDamagedOCL8` | ObjectCreationList | `0x8b4` | - |
| `ReallyDamagedOCL9` | ObjectCreationList | `0x8d0` | - |
| `ReallyDamagedParticleSystem1` | ParticleSystem | `0xd34` | - |
| `ReallyDamagedParticleSystem10` | ParticleSystem | `0xe30` | - |
| `ReallyDamagedParticleSystem11` | ParticleSystem | `0xe4c` | - |
| `ReallyDamagedParticleSystem12` | ParticleSystem | `0xe68` | - |
| `ReallyDamagedParticleSystem2` | ParticleSystem | `0xd50` | - |
| `ReallyDamagedParticleSystem3` | ParticleSystem | `0xd6c` | - |
| `ReallyDamagedParticleSystem4` | ParticleSystem | `0xd88` | - |
| `ReallyDamagedParticleSystem5` | ParticleSystem | `0xda4` | - |
| `ReallyDamagedParticleSystem6` | ParticleSystem | `0xdc0` | - |
| `ReallyDamagedParticleSystem7` | ParticleSystem | `0xddc` | - |
| `ReallyDamagedParticleSystem8` | ParticleSystem | `0xdf8` | - |
| `ReallyDamagedParticleSystem9` | ParticleSystem | `0xe14` | - |
| `ReallyDamagedShowSubObject` | AsciiStringList | `0x101c` | - |
| `RubbleFXList1` | FXList | `0x3fc` | - |
| `RubbleFXList10` | FXList | `0x4f8` | - |
| `RubbleFXList11` | FXList | `0x514` | - |
| `RubbleFXList12` | FXList | `0x530` | - |
| `RubbleFXList2` | FXList | `0x418` | - |
| `RubbleFXList3` | FXList | `0x434` | - |
| `RubbleFXList4` | FXList | `0x450` | - |
| `RubbleFXList5` | FXList | `0x46c` | - |
| `RubbleFXList6` | FXList | `0x488` | - |
| `RubbleFXList7` | FXList | `0x4a4` | - |
| `RubbleFXList8` | FXList | `0x4c0` | - |
| `RubbleFXList9` | FXList | `0x4dc` | - |
| `RubbleHideSubObject` | AsciiStringList | `0xff8` | - |
| `RubbleNeighbor` | RubbleNeighbor | `0x1034` | - |
| `RubbleOCL1` | ObjectCreationList | `0x940` | - |
| `RubbleOCL10` | ObjectCreationList | `0xa3c` | - |
| `RubbleOCL11` | ObjectCreationList | `0xa58` | - |
| `RubbleOCL12` | ObjectCreationList | `0xa74` | - |
| `RubbleOCL2` | ObjectCreationList | `0x95c` | - |
| `RubbleOCL3` | ObjectCreationList | `0x978` | - |
| `RubbleOCL4` | ObjectCreationList | `0x994` | - |
| `RubbleOCL5` | ObjectCreationList | `0x9b0` | - |
| `RubbleOCL6` | ObjectCreationList | `0x9cc` | - |
| `RubbleOCL7` | ObjectCreationList | `0x9e8` | - |
| `RubbleOCL8` | ObjectCreationList | `0xa04` | - |
| `RubbleOCL9` | ObjectCreationList | `0xa20` | - |
| `RubbleParticleSystem1` | ParticleSystem | `0xe84` | - |
| `RubbleParticleSystem10` | ParticleSystem | `0xf80` | - |
| `RubbleParticleSystem11` | ParticleSystem | `0xf9c` | - |
| `RubbleParticleSystem12` | ParticleSystem | `0xfb8` | - |
| `RubbleParticleSystem2` | ParticleSystem | `0xea0` | - |
| `RubbleParticleSystem3` | ParticleSystem | `0xebc` | - |
| `RubbleParticleSystem4` | ParticleSystem | `0xed8` | - |
| `RubbleParticleSystem5` | ParticleSystem | `0xef4` | - |
| `RubbleParticleSystem6` | ParticleSystem | `0xf10` | - |
| `RubbleParticleSystem7` | ParticleSystem | `0xf2c` | - |
| `RubbleParticleSystem8` | ParticleSystem | `0xf48` | - |
| `RubbleParticleSystem9` | ParticleSystem | `0xf64` | - |
| `RubbleShowSubObject` | AsciiStringList | `0x1028` | - |

## TransportAIUpdate

`sizeof(ModuleData)` = 0x64, 19 fields

| field | type | offset | default |
|---|---|---|---|
| `AILuaEventsList` | AsciiString | `0x2c` | `0` |
| `AttackPriority` | AsciiString | `0x44` | `"DefaultAttackPriority"` |
| `AutoAcquireEnemiesWhenIdle` | BitFlags | `0x1c` | `0` |
| `BurningDeathTime` | Duration | `0x40` | `0` |
| `CanAttackWhileContained` | Bool | `0x25` | `No` |
| `ComboLocoAttackDistance` | Real | `0x4c` | `80` |
| `ComboLocomotorSet` | Enum | `0x50` | `0` |
| `FadeOnPortals` | Bool | `0x54` | `No` |
| `HoldGroundCloseRangeDistance` | Real | `0x28` | `0` |
| `MaxCowerTime` | Duration | `0x30` | `0` |
| `MinCowerTime` | Duration | `0x34` | `0` |
| `MoodAttackCheckRate` | Duration | `0x18` | - |
| `RampageRequiresAflame` | Bool | `0x3c` | `No` |
| `RampageTime` | Duration | `0x38` | `0` |
| `SpecialContactPoints` | AsciiStringList | `0x58` | `0` |
| `StandGround` | Bool | `0x24` | `No` |
| `StopChaseDistance` | Real | `0x20` | `500` |
| `TimeToEjectPassengersOnRampage` | Duration | `0x48` | `0` |
| `Turret` | 0x006620a2 | `0x14` | `0` |

## TransportContain

`sizeof(ModuleData)` = 0x18c, 63 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowAlliesInside` | Bool | `0x7d` | `No` |
| `AllowEnemiesInside` | Bool | `0x7e` | `No` |
| `AllowNeutralInside` | Bool | `0x7f` | `No` |
| `AllowOwnPlayerInsideOverride` | Bool | `0x7c` | `No` |
| `BoneSpecificConditionState` | 0x008678eb | `0x0` | - |
| `CanGrabStructure` | Bool | `0x13d` | `No` |
| `CollidePickup` | Bool | `0x81` | `No` |
| `ConditionForEntry` | ModelConditionFlag | `0x14c` | `-1` |
| `ContainMax` | Int | `0x70` | `-1` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DamagePercentToUnits` | Percent | `0x6c` | `0` |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DestroyRidersWhoAreNotFreeToExit` | Bool | `0x142` | `No` |
| `DoorOpenTime` | Duration | `0x78` | `0` |
| `EjectPassengersOnDeath` | Bool | `0x82` | `No` |
| `Enabled` | Bool | `0x84` | `No` |
| `EnterFadeTime` | Real | `0x170` | `0` |
| `EnterSound` | AudioEventRTS | `0x38` | `0` |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `ExitBone` | AsciiString | `0xa0` | `0` |
| `ExitDelay` | Duration | `0xac` | `0` |
| `ExitFadeTime` | Real | `0x174` | `0` |
| `ExitPitchRate` | AngularVelocityReal | `0x9c` | `0` |
| `ExitSound` | AudioEventRTS | `0x3c` | `0` |
| `FadeFilter` | KindOfFilter | `0x168` | - |
| `FadePassengerOnEnter` | Bool | `0x16c` | `No` |
| `FadePassengerOnExit` | Bool | `0x16d` | `No` |
| `FadeReverse` | Bool | `0x178` | `No` |
| `FireGrabWeaponOnVictim` | Bool | `0x148` | `Yes` |
| `ForceOrientationContainer` | Bool | `0x13c` | `Yes` |
| `GoAggressiveOnExit` | Bool | `0x140` | `No` |
| `GrabWeapon` | WeaponTemplate | `0x144` | `0` |
| `HealthRegen%PerSec` | Real | `0xa8` | `0` |
| `InitialPayload` | 0x0086af0a | `0x0` | - |
| `KillPassengersOnDeath` | Bool | `0x83` | `No` |
| `ManualPickUpFilter` | KindOfFilter | `0x44` | `0` |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `ModifierRequiredTime` | Duration | `0x94` | `100` |
| `ModifierToGiveOnExit` | AsciiStringList | `0x88` | - |
| `NumberOfExitPaths` | Int | `0x74` | `0` |
| `ObjectStatusOfContained` | ObjectStatusFlags | `0x58` | `0` |
| `OrientLikeContainerOnExit` | Bool | `0x13f` | `No` |
| `PassengerBonePrefix` | PassengerBonePrefix | `0x0` | - |
| `PassengerFilter` | KindOfFilter | `0x40` | - |
| `PassengersInTurret` | Bool | `0x85` | `No` |
| `PassengersTestCollisionHeight` | Real | `0x68` | `-1000` |
| `ReleaseSnappyness` | Real | `0x17c` | `0.7` |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `ResetMoodCheckTimeOnExit` | Bool | `0x141` | `Yes` |
| `ScatterNearbyOnExit` | Bool | `0x13e` | `Yes` |
| `ShouldThrowOutPassengers` | Bool | `0x150` | `No` |
| `ShowPips` | Bool | `0x80` | `No` |
| `Slots` | Int | `0x98` | `0` |
| `ThrowOutPassengersDelay` | Duration | `0x154` | `0` |
| `ThrowOutPassengersLandingWarhead` | WeaponTemplate | `0x164` | `0` |
| `ThrowOutPassengersVelocity` | Coord3D | `0x158` | - |
| `TypeOneForWeaponSet` | KindOfFlags | `0xb0` | - |
| `TypeOneForWeaponState` | KindOfFlags | `0xe8` | - |
| `TypeThreeForWeaponState` | KindOfFlags | `0x120` | - |
| `TypeTwoForWeaponSet` | KindOfFlags | `0xcc` | `0` |
| `TypeTwoForWeaponState` | KindOfFlags | `0x104` | - |
| `UpgradeCreationTrigger` | 0x0086ba2c | `0x0` | - |

## TunnelContain

`sizeof(ModuleData)` = 0xd8, 39 fields

| field | type | offset | default |
|---|---|---|---|
| `AllowAlliesInside` | Bool | `0x7d` | `No` |
| `AllowEnemiesInside` | Bool | `0x7e` | `No` |
| `AllowNeutralInside` | Bool | `0x7f` | `No` |
| `AllowOwnPlayerInsideOverride` | Bool | `0x7c` | `No` |
| `BoneSpecificConditionState` | 0x008678eb | `0x0` | - |
| `CollidePickup` | Bool | `0x81` | `No` |
| `ContainMax` | Int | `0x70` | `-1` |
| `DamageAmountRequired` | Real | `0x24` | - |
| `DamagePercentToUnits` | Percent | `0x6c` | `0` |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `DoorOpenTime` | Duration | `0x78` | `0` |
| `EjectPassengersOnDeath` | Bool | `0x82` | `No` |
| `Enabled` | Bool | `0x84` | `No` |
| `EnterSound` | AudioEventRTS | `0x38` | `0` |
| `EntryOffset` | Coord3D | `0xb0` | - |
| `EntryPosition` | Coord3D | `0xbc` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `ExitDelay` | Duration | `0xac` | `0` |
| `ExitOffset` | Coord3D | `0xc8` | `1` |
| `ExitSound` | AudioEventRTS | `0x3c` | `0` |
| `HealObjects` | Bool | `0x98` | `No` |
| `ImmuneToClearBuildingAttacks` | Bool | `0xa1` | `No` |
| `InitialRoster` | 0x00653381 | `0x0` | - |
| `KillPassengersOnDeath` | Bool | `0x83` | `No` |
| `ManualPickUpFilter` | KindOfFilter | `0x44` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `MobileGarrison` | Bool | `0xa0` | `No` |
| `ModifierRequiredTime` | Duration | `0x94` | `100` |
| `ModifierToGiveOnExit` | AsciiStringList | `0x88` | - |
| `NumberOfExitPaths` | Int | `0x74` | `0` |
| `ObjectStatusOfContained` | ObjectStatusFlags | `0x58` | `0` |
| `PassengerBonePrefix` | PassengerBonePrefix | `0x0` | - |
| `PassengerFilter` | KindOfFilter | `0x40` | - |
| `PassengersInTurret` | Bool | `0x85` | `No` |
| `PassengersTestCollisionHeight` | Real | `0x68` | `-1000` |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `ShowPips` | Bool | `0x80` | `No` |
| `TimeForFullHeal` | DurationReal | `0x9c` | `1` |

## UnitCrateCollide

`sizeof(ModuleData)` = 0x64, 13 fields

| field | type | offset | default |
|---|---|---|---|
| `BuildingPickup` | Bool | `0x41` | `No` |
| `ExecuteAnimation` | AsciiString | `0x4c` | - |
| `ExecuteAnimationFades` | Bool | `0x58` | `Yes` |
| `ExecuteAnimationTime` | Real | `0x50` | `0` |
| `ExecuteAnimationZRise` | Real | `0x54` | `0` |
| `ExecuteFX` | FXList | `0x48` | `0` |
| `ForbiddenKindOf` | KindOfFlags | `0x24` | - |
| `ForbidOwnerPlayer` | Bool | `0x40` | `No` |
| `HumanOnly` | Bool | `0x42` | `No` |
| `PickupScience` | ScienceType | `0x44` | `-1` |
| `RequiredKindOf` | KindOfFlags | `0x8` | - |
| `UnitCount` | Int | `0x5c` | `0` |
| `UnitName` | AsciiString | `0x60` | `""` |

## UnleashSpecialPower

`sizeof(ModuleData)` = 0xd0, 60 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |

## UnpauseSpecialPowerUpgrade

`sizeof(ModuleData)` = 0x140, 8 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `ObeyRechageOnTrigger` | Bool | `0x13c` | `No` |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x138` | `0` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## UntamedAllegianceSpecialPower

`sizeof(ModuleData)` = 0x7c, 35 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `GiveLevels` | Int | `0x58` | `0` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## UpgradeDie

`sizeof(ModuleData)` = 0x3c, 7 fields

| field | type | offset | default |
|---|---|---|---|
| `DamageAmountRequired` | Real | `0x24` | - |
| `DeathTypes` | DeathTypeFlags | `0x0` | - |
| `ExemptStatus` | ObjectStatusFlags | `0x4` | - |
| `MaxKillerAngle` | AngleReal | `0x2c` | `-1` |
| `MinKillerAngle` | AngleReal | `0x28` | - |
| `RequiredStatus` | ObjectStatusFlags | `0x14` | - |
| `UpgradeToRemove` | AsciiString | `0x38` | `0` |

## UpgradeSoundSelectorClientBehavior

`sizeof(ModuleData)` = 0x14, 1 field

| field | type | offset | default |
|---|---|---|---|
| `SoundUpgrade` | SoundUpgrade | `0x0` | - |

## VeterancyCrateCollide

`sizeof(ModuleData)` = 0x68, 15 fields

| field | type | offset | default |
|---|---|---|---|
| `AddsOwnerVeterancy` | Bool | `0x60` | `No` |
| `AffectsUpToLevel` | Int | `0x64` | `10` |
| `BuildingPickup` | Bool | `0x41` | `No` |
| `EffectRange` | Int | `0x5c` | `0` |
| `ExecuteAnimation` | AsciiString | `0x4c` | - |
| `ExecuteAnimationFades` | Bool | `0x58` | `Yes` |
| `ExecuteAnimationTime` | Real | `0x50` | `0` |
| `ExecuteAnimationZRise` | Real | `0x54` | `0` |
| `ExecuteFX` | FXList | `0x48` | `0` |
| `ForbiddenKindOf` | KindOfFlags | `0x24` | - |
| `ForbidOwnerPlayer` | Bool | `0x40` | `No` |
| `HumanOnly` | Bool | `0x42` | `No` |
| `IsPilot` | Bool | `0x61` | `No` |
| `PickupScience` | ScienceType | `0x44` | `-1` |
| `RequiredKindOf` | KindOfFlags | `0x8` | - |

## W3DBoatWakeModelDraw

`sizeof(ModuleData)` = 0x18, 2 fields

| field | type | offset | default |
|---|---|---|---|
| `ModelName` | AsciiString | `0x8` | `0` |
| `Offset` | Coord3D | `0xc` | `0` |

## W3DBuffDraw

`sizeof(ModuleData)` = 0x10, 2 fields

| field | type | offset | default |
|---|---|---|---|
| `ModelName` | AsciiString | `0x8` | `0` |
| `PreDraw` | Bool | `0xc` | `No` |

## W3DFloorDraw

`sizeof(ModuleData)` = 0x30, 8 fields

| field | type | offset | default |
|---|---|---|---|
| `DistanceFog` | Bool | `0xc` | `Yes` |
| `FloorFadeRateOnObjectDeath` | Real | `0x20` | `0` |
| `ForceToBack` | Bool | `0x1d` | - |
| `HideIfModelConditions` | 0x004cef06 | `0x0` | - |
| `ModelName` | AsciiString | `0x8` | `0` |
| `StartHidden` | Bool | `0x1e` | - |
| `StaticModelLODMode` | Bool | `0x1c` | - |
| `WeatherTexture` | 0x004cf066 | `0x10` | `0` |

## W3DHordeModelDraw

`sizeof(ModuleData)` = 0x1c4, 1 field

| field | type | offset | default |
|---|---|---|---|
| `LodOptions` | LodOptions | `0x0` | - |

## W3DLaserDraw

`sizeof(ModuleData)` = 0x74, 16 fields

| field | type | offset | default |
|---|---|---|---|
| `ArcHeight` | Real | `0x3c` | `0` |
| `Envelope` | OpacityEnvelope | `0x4c` | - |
| `FadeLifetime` | Duration | `0x28` | `0` |
| `FanWidth` | Real | `0x48` | `0` |
| `InnerBeamWidth` | Real | `0x10` | `0` |
| `InnerColor` | RGBAColor | `0x8` | `-1` |
| `MaxIntensityLifetime` | Duration | `0x24` | `0` |
| `NumBeams` | Int | `0x20` | `0` |
| `OuterBeamWidth` | Real | `0x14` | `1` |
| `OuterColor` | RGBAColor | `0xc` | `-1` |
| `ScrollRate` | Real | `0x18` | `0` |
| `SegmentOverlapRatio` | Real | `0x40` | `0` |
| `Segments` | Int | `0x38` | `0` |
| `Texture` | AsciiStringList | `0x2c` | `0` |
| `Tile` | Bool | `0x1c` | `No` |
| `TilingScalar` | Real | `0x44` | `1` |

## W3DLightDraw

`sizeof(ModuleData)` = 0x48, 10 fields

| field | type | offset | default |
|---|---|---|---|
| `Ambient` | RGBColor | `0x8` | `0` |
| `AttachToBoneInAnotherModule` | AsciiString | `0x44` | `0` |
| `Diffuse` | RGBColor | `0x14` | `0` |
| `FlickerAmplitude` | Real | `0x34` | `0` |
| `FlickerFrequency` | Real | `0x38` | `0` |
| `Intensity` | Real | `0x30` | `1` |
| `PulseAmplitude` | Real | `0x3c` | `0` |
| `PulseFrequency` | Real | `0x40` | `0` |
| `Radius` | Real | `0x2c` | `20` |
| `Specular` | RGBColor | `0x20` | `0` |

## W3DProjectileStreamDraw

`sizeof(ModuleData)` = 0x1c, 5 fields

| field | type | offset | default |
|---|---|---|---|
| `MaxSegments` | Int | `0x18` | `0` |
| `ScrollRate` | Real | `0x14` | `0` |
| `Texture` | AsciiString | `0x8` | `""` |
| `TileFactor` | Real | `0x10` | `0` |
| `Width` | Real | `0xc` | `0` |

## W3DPropDraw

`sizeof(ModuleData)` = 0x10, 2 fields

| field | type | offset | default |
|---|---|---|---|
| `DistanceFog` | Bool | `0xc` | `Yes` |
| `ModelName` | AsciiString | `0x8` | `0` |

## W3DQuadrupedDraw

`sizeof(ModuleData)` = 0x198, 61 fields

| field | type | offset | default |
|---|---|---|---|
| `AffectedByStealth` | Bool | `0x15e` | `Yes` |
| `AlphaCameraAtInnerRadius` | Percent | `0x14c` | `1` |
| `AlphaCameraFadeInnerRadius` | PositiveReal | `0x148` | `0` |
| `AlphaCameraFadeOuterRadius` | PositiveReal | `0x144` | `0` |
| `AlphaRefAnimated` | Bool | `0x139` | `No` |
| `AlphaRefRange` | IntRange | `0x13c` | - |
| `AnimationsRequirePower` | Bool | `0x6b` | `Yes` |
| `AnimationState` | AnimationState | `0x0` | - |
| `AttachModel` | AttachModel | `0x0` | - |
| `AttachToBoneInAnotherModule` | 0x004b65ba | `0x40` | `0` |
| `BirthFadeAdditive` | Bool | `0x154` | `No` |
| `BirthFadeTime` | Duration | `0x150` | `0` |
| `BurntTexture` | 0x004c3321 | `0x0` | - |
| `DefaultModelConditionState` | ModelConditionState | `0x0` | - |
| `DependencySharedModelFlags` | ModelConditionFlags | `0xbc` | - |
| `EmbedPortal` | 0x004c30bd | `0x11c` | `0` |
| `ExtraPublicBone` | AsciiStringList | `0x30` | `0` |
| `GlowEmissive` | Bool | `0x129` | `No` |
| `GlowEnabled` | Bool | `0x128` | `No` |
| `HighDetailLODThreshold` | Real | `0x12c` | `0` |
| `HighDetailOnly` | Bool | `0x15f` | `No` |
| `IdleAnimationState` | AnimationState | `0x0` | - |
| `InitialRecoilSpeed` | VelocityReal | `0x54` | `2` |
| `LeftFrontFootBone` | AsciiString | `0x188` | - |
| `LeftRearFootBone` | AsciiString | `0x190` | - |
| `LowDetailLODThreshold` | Real | `0x130` | `0` |
| `MaxRecoilDistance` | Real | `0x58` | `3` |
| `MinLODRequired` | Enum | `0x64` | `0` |
| `ModelConditionState` | ModelConditionState | `0x0` | - |
| `MultiPlayerOnly` | Bool | `0x15d` | `No` |
| `NoRotate` | Bool | `0x69` | `No` |
| `OkToChangeModelColor` | Bool | `0x68` | `No` |
| `ParticleBonesCheckDrawable` | Bool | `0x12a` | `No` |
| `ParticlesAttachedToAnimatedBones` | Bool | `0x108` | `No` |
| `ProjectileBoneFeedbackEnabledSlots` | BitFlags | `0x50` | `0` |
| `RaisedWallMesh` | AsciiString | `0x110` | `0` |
| `RampMesh1` | AsciiString | `0x114` | `0` |
| `RampMesh2` | AsciiString | `0x118` | `0` |
| `RandomTexture` | 0x004c7c56 | `0x0` | - |
| `RandomTextureFixedRandomIndex` | Bool | `0x88` | `No` |
| `RecoilDamping` | Real | `0x5c` | `0.4` |
| `RecoilSettleSpeed` | VelocityReal | `0x60` | `0.065` |
| `RightFrontFootBone` | AsciiString | `0x18c` | - |
| `RightRearFootBone` | AsciiString | `0x194` | - |
| `ShadowForceDisable` | Bool | `0x12b` | `No` |
| `ShowShadowWhileContained` | Bool | `0x136` | `No` |
| `StaticModelLODMode` | Bool | `0x135` | `No` |
| `StaticSortLevelWhileFading` | Int | `0x158` | `-1` |
| `SwitchModelLODMode` | Bool | `0x134` | `No` |
| `TimeOfDayTexture` | 0x004c42a8 | `0x0` | - |
| `TrackMarks` | 0x004b65ba | `0x3c` | `0` |
| `TrackMarksLeftBone` | AsciiString | `0x44` | `0` |
| `TrackMarksRightBone` | AsciiString | `0x48` | `0` |
| `TransitionState` | AnimationState | `0x0` | - |
| `UseDefaultAnimation` | Bool | `0x138` | `No` |
| `UseFiringArcRotation` | Bool | `0x6a` | `No` |
| `UseProducerTexture` | Bool | `0xb8` | `No` |
| `UseStandardModelNames` | Bool | `0x137` | `No` |
| `WadingParticleSys` | AsciiString | `0x14` | `0` |
| `WallBoundsMesh` | AsciiString | `0x10c` | `0` |
| `ZWriteDisableOverride` | Bool | `0x15c` | `No` |

## W3DSailModelDraw

`sizeof(ModuleData)` = 0x194, 60 fields

| field | type | offset | default |
|---|---|---|---|
| `AboutDamping` | Real | `0x190` | `0.05` |
| `AffectedByStealth` | Bool | `0x15e` | `Yes` |
| `AlphaCameraAtInnerRadius` | Percent | `0x14c` | `1` |
| `AlphaCameraFadeInnerRadius` | PositiveReal | `0x148` | `0` |
| `AlphaCameraFadeOuterRadius` | PositiveReal | `0x144` | `0` |
| `AlphaRefAnimated` | Bool | `0x139` | `No` |
| `AlphaRefRange` | IntRange | `0x13c` | - |
| `AnimationsRequirePower` | Bool | `0x6b` | `Yes` |
| `AnimationState` | AnimationState | `0x0` | - |
| `AttachModel` | AttachModel | `0x0` | - |
| `AttachToBoneInAnotherModule` | 0x004b65ba | `0x40` | `0` |
| `BirthFadeAdditive` | Bool | `0x154` | `No` |
| `BirthFadeTime` | Duration | `0x150` | `0` |
| `BlowingThresholdDegrees` | AngleReal | `0x18c` | `0.25` |
| `BurntTexture` | 0x004c3321 | `0x0` | - |
| `DefaultModelConditionState` | ModelConditionState | `0x0` | - |
| `DependencySharedModelFlags` | ModelConditionFlags | `0xbc` | - |
| `EmbedPortal` | 0x004c30bd | `0x11c` | `0` |
| `ExtraPublicBone` | AsciiStringList | `0x30` | `0` |
| `GlowEmissive` | Bool | `0x129` | `No` |
| `GlowEnabled` | Bool | `0x128` | `No` |
| `HighDetailLODThreshold` | Real | `0x12c` | `0` |
| `HighDetailOnly` | Bool | `0x15f` | `No` |
| `IdleAnimationState` | AnimationState | `0x0` | - |
| `InitialRecoilSpeed` | VelocityReal | `0x54` | `2` |
| `LowDetailLODThreshold` | Real | `0x130` | `0` |
| `MaxRecoilDistance` | Real | `0x58` | `3` |
| `MaxRotationDegrees` | AngleReal | `0x188` | `0` |
| `MinLODRequired` | Enum | `0x64` | `0` |
| `ModelConditionState` | ModelConditionState | `0x0` | - |
| `MultiPlayerOnly` | Bool | `0x15d` | `No` |
| `NoRotate` | Bool | `0x69` | `No` |
| `OkToChangeModelColor` | Bool | `0x68` | `No` |
| `ParticleBonesCheckDrawable` | Bool | `0x12a` | `No` |
| `ParticlesAttachedToAnimatedBones` | Bool | `0x108` | `No` |
| `ProjectileBoneFeedbackEnabledSlots` | BitFlags | `0x50` | `0` |
| `RaisedWallMesh` | AsciiString | `0x110` | `0` |
| `RampMesh1` | AsciiString | `0x114` | `0` |
| `RampMesh2` | AsciiString | `0x118` | `0` |
| `RandomTexture` | 0x004c7c56 | `0x0` | - |
| `RandomTextureFixedRandomIndex` | Bool | `0x88` | `No` |
| `RecoilDamping` | Real | `0x5c` | `0.4` |
| `RecoilSettleSpeed` | VelocityReal | `0x60` | `0.065` |
| `ShadowForceDisable` | Bool | `0x12b` | `No` |
| `ShowShadowWhileContained` | Bool | `0x136` | `No` |
| `StaticModelLODMode` | Bool | `0x135` | `No` |
| `StaticSortLevelWhileFading` | Int | `0x158` | `-1` |
| `SwitchModelLODMode` | Bool | `0x134` | `No` |
| `TimeOfDayTexture` | 0x004c42a8 | `0x0` | - |
| `TrackMarks` | 0x004b65ba | `0x3c` | `0` |
| `TrackMarksLeftBone` | AsciiString | `0x44` | `0` |
| `TrackMarksRightBone` | AsciiString | `0x48` | `0` |
| `TransitionState` | AnimationState | `0x0` | - |
| `UseDefaultAnimation` | Bool | `0x138` | `No` |
| `UseFiringArcRotation` | Bool | `0x6a` | `No` |
| `UseProducerTexture` | Bool | `0xb8` | `No` |
| `UseStandardModelNames` | Bool | `0x137` | `No` |
| `WadingParticleSys` | AsciiString | `0x14` | `0` |
| `WallBoundsMesh` | AsciiString | `0x10c` | `0` |
| `ZWriteDisableOverride` | Bool | `0x15c` | `No` |

## W3DScriptedModelDraw

`sizeof(ModuleData)` = 0x188, 57 fields

| field | type | offset | default |
|---|---|---|---|
| `AffectedByStealth` | Bool | `0x15e` | `Yes` |
| `AlphaCameraAtInnerRadius` | Percent | `0x14c` | `1` |
| `AlphaCameraFadeInnerRadius` | PositiveReal | `0x148` | `0` |
| `AlphaCameraFadeOuterRadius` | PositiveReal | `0x144` | `0` |
| `AlphaRefAnimated` | Bool | `0x139` | `No` |
| `AlphaRefRange` | IntRange | `0x13c` | - |
| `AnimationsRequirePower` | Bool | `0x6b` | `Yes` |
| `AnimationState` | AnimationState | `0x0` | - |
| `AttachModel` | AttachModel | `0x0` | - |
| `AttachToBoneInAnotherModule` | 0x004b65ba | `0x40` | `0` |
| `BirthFadeAdditive` | Bool | `0x154` | `No` |
| `BirthFadeTime` | Duration | `0x150` | `0` |
| `BurntTexture` | 0x004c3321 | `0x0` | - |
| `DefaultModelConditionState` | ModelConditionState | `0x0` | - |
| `DependencySharedModelFlags` | ModelConditionFlags | `0xbc` | - |
| `EmbedPortal` | 0x004c30bd | `0x11c` | `0` |
| `ExtraPublicBone` | AsciiStringList | `0x30` | `0` |
| `GlowEmissive` | Bool | `0x129` | `No` |
| `GlowEnabled` | Bool | `0x128` | `No` |
| `HighDetailLODThreshold` | Real | `0x12c` | `0` |
| `HighDetailOnly` | Bool | `0x15f` | `No` |
| `IdleAnimationState` | AnimationState | `0x0` | - |
| `InitialRecoilSpeed` | VelocityReal | `0x54` | `2` |
| `LowDetailLODThreshold` | Real | `0x130` | `0` |
| `MaxRecoilDistance` | Real | `0x58` | `3` |
| `MinLODRequired` | Enum | `0x64` | `0` |
| `ModelConditionState` | ModelConditionState | `0x0` | - |
| `MultiPlayerOnly` | Bool | `0x15d` | `No` |
| `NoRotate` | Bool | `0x69` | `No` |
| `OkToChangeModelColor` | Bool | `0x68` | `No` |
| `ParticleBonesCheckDrawable` | Bool | `0x12a` | `No` |
| `ParticlesAttachedToAnimatedBones` | Bool | `0x108` | `No` |
| `ProjectileBoneFeedbackEnabledSlots` | BitFlags | `0x50` | `0` |
| `RaisedWallMesh` | AsciiString | `0x110` | `0` |
| `RampMesh1` | AsciiString | `0x114` | `0` |
| `RampMesh2` | AsciiString | `0x118` | `0` |
| `RandomTexture` | 0x004c7c56 | `0x0` | - |
| `RandomTextureFixedRandomIndex` | Bool | `0x88` | `No` |
| `RecoilDamping` | Real | `0x5c` | `0.4` |
| `RecoilSettleSpeed` | VelocityReal | `0x60` | `0.065` |
| `ShadowForceDisable` | Bool | `0x12b` | `No` |
| `ShowShadowWhileContained` | Bool | `0x136` | `No` |
| `StaticModelLODMode` | Bool | `0x135` | `No` |
| `StaticSortLevelWhileFading` | Int | `0x158` | `-1` |
| `SwitchModelLODMode` | Bool | `0x134` | `No` |
| `TimeOfDayTexture` | 0x004c42a8 | `0x0` | - |
| `TrackMarks` | 0x004b65ba | `0x3c` | `0` |
| `TrackMarksLeftBone` | AsciiString | `0x44` | `0` |
| `TrackMarksRightBone` | AsciiString | `0x48` | `0` |
| `TransitionState` | AnimationState | `0x0` | - |
| `UseDefaultAnimation` | Bool | `0x138` | `No` |
| `UseFiringArcRotation` | Bool | `0x6a` | `No` |
| `UseProducerTexture` | Bool | `0xb8` | `No` |
| `UseStandardModelNames` | Bool | `0x137` | `No` |
| `WadingParticleSys` | AsciiString | `0x14` | `0` |
| `WallBoundsMesh` | AsciiString | `0x10c` | `0` |
| `ZWriteDisableOverride` | Bool | `0x15c` | `No` |

## W3DStreakDraw

`sizeof(ModuleData)` = 0x34, 7 fields

| field | type | offset | default |
|---|---|---|---|
| `Additive` | Bool | `0x10` | `Yes` |
| `Color` | RGBColor | `0x14` | `1` |
| `Length` | Real | `0x8` | `50` |
| `NumSegments` | Int | `0x20` | `5` |
| `Texture` | AsciiString | `0x24` | `0` |
| `WeatherTexture` | 0x004cfeb9 | `0x28` | `0` |
| `Width` | Real | `0xc` | `0.5` |

## W3DSupplyDraw

`sizeof(ModuleData)` = 0x18c, 58 fields

| field | type | offset | default |
|---|---|---|---|
| `AffectedByStealth` | Bool | `0x15e` | `Yes` |
| `AlphaCameraAtInnerRadius` | Percent | `0x14c` | `1` |
| `AlphaCameraFadeInnerRadius` | PositiveReal | `0x148` | `0` |
| `AlphaCameraFadeOuterRadius` | PositiveReal | `0x144` | `0` |
| `AlphaRefAnimated` | Bool | `0x139` | `No` |
| `AlphaRefRange` | IntRange | `0x13c` | - |
| `AnimationsRequirePower` | Bool | `0x6b` | `Yes` |
| `AnimationState` | AnimationState | `0x0` | - |
| `AttachModel` | AttachModel | `0x0` | - |
| `AttachToBoneInAnotherModule` | 0x004b65ba | `0x40` | `0` |
| `BirthFadeAdditive` | Bool | `0x154` | `No` |
| `BirthFadeTime` | Duration | `0x150` | `0` |
| `BurntTexture` | 0x004c3321 | `0x0` | - |
| `DefaultModelConditionState` | ModelConditionState | `0x0` | - |
| `DependencySharedModelFlags` | ModelConditionFlags | `0xbc` | - |
| `EmbedPortal` | 0x004c30bd | `0x11c` | `0` |
| `ExtraPublicBone` | AsciiStringList | `0x30` | `0` |
| `GlowEmissive` | Bool | `0x129` | `No` |
| `GlowEnabled` | Bool | `0x128` | `No` |
| `HighDetailLODThreshold` | Real | `0x12c` | `0` |
| `HighDetailOnly` | Bool | `0x15f` | `No` |
| `IdleAnimationState` | AnimationState | `0x0` | - |
| `InitialRecoilSpeed` | VelocityReal | `0x54` | `2` |
| `LowDetailLODThreshold` | Real | `0x130` | `0` |
| `MaxRecoilDistance` | Real | `0x58` | `3` |
| `MinLODRequired` | Enum | `0x64` | `0` |
| `ModelConditionState` | ModelConditionState | `0x0` | - |
| `MultiPlayerOnly` | Bool | `0x15d` | `No` |
| `NoRotate` | Bool | `0x69` | `No` |
| `OkToChangeModelColor` | Bool | `0x68` | `No` |
| `ParticleBonesCheckDrawable` | Bool | `0x12a` | `No` |
| `ParticlesAttachedToAnimatedBones` | Bool | `0x108` | `No` |
| `ProjectileBoneFeedbackEnabledSlots` | BitFlags | `0x50` | `0` |
| `RaisedWallMesh` | AsciiString | `0x110` | `0` |
| `RampMesh1` | AsciiString | `0x114` | `0` |
| `RampMesh2` | AsciiString | `0x118` | `0` |
| `RandomTexture` | 0x004c7c56 | `0x0` | - |
| `RandomTextureFixedRandomIndex` | Bool | `0x88` | `No` |
| `RecoilDamping` | Real | `0x5c` | `0.4` |
| `RecoilSettleSpeed` | VelocityReal | `0x60` | `0.065` |
| `ShadowForceDisable` | Bool | `0x12b` | `No` |
| `ShowShadowWhileContained` | Bool | `0x136` | `No` |
| `StaticModelLODMode` | Bool | `0x135` | `No` |
| `StaticSortLevelWhileFading` | Int | `0x158` | `-1` |
| `SupplyBonePrefix` | AsciiString | `0x188` | `0` |
| `SwitchModelLODMode` | Bool | `0x134` | `No` |
| `TimeOfDayTexture` | 0x004c42a8 | `0x0` | - |
| `TrackMarks` | 0x004b65ba | `0x3c` | `0` |
| `TrackMarksLeftBone` | AsciiString | `0x44` | `0` |
| `TrackMarksRightBone` | AsciiString | `0x48` | `0` |
| `TransitionState` | AnimationState | `0x0` | - |
| `UseDefaultAnimation` | Bool | `0x138` | `No` |
| `UseFiringArcRotation` | Bool | `0x6a` | `No` |
| `UseProducerTexture` | Bool | `0xb8` | `No` |
| `UseStandardModelNames` | Bool | `0x137` | `No` |
| `WadingParticleSys` | AsciiString | `0x14` | `0` |
| `WallBoundsMesh` | AsciiString | `0x10c` | `0` |
| `ZWriteDisableOverride` | Bool | `0x15c` | `No` |

## W3DTankDraw

`sizeof(ModuleData)` = 0x19c, 62 fields

| field | type | offset | default |
|---|---|---|---|
| `AffectedByStealth` | Bool | `0x15e` | `Yes` |
| `AlphaCameraAtInnerRadius` | Percent | `0x14c` | `1` |
| `AlphaCameraFadeInnerRadius` | PositiveReal | `0x148` | `0` |
| `AlphaCameraFadeOuterRadius` | PositiveReal | `0x144` | `0` |
| `AlphaRefAnimated` | Bool | `0x139` | `No` |
| `AlphaRefRange` | IntRange | `0x13c` | - |
| `AnimationsRequirePower` | Bool | `0x6b` | `Yes` |
| `AnimationState` | AnimationState | `0x0` | - |
| `AttachModel` | AttachModel | `0x0` | - |
| `AttachToBoneInAnotherModule` | 0x004b65ba | `0x40` | `0` |
| `BirthFadeAdditive` | Bool | `0x154` | `No` |
| `BirthFadeTime` | Duration | `0x150` | `0` |
| `BurntTexture` | 0x004c3321 | `0x0` | - |
| `DefaultModelConditionState` | ModelConditionState | `0x0` | - |
| `DependencySharedModelFlags` | ModelConditionFlags | `0xbc` | - |
| `EmbedPortal` | 0x004c30bd | `0x11c` | `0` |
| `ExtraPublicBone` | AsciiStringList | `0x30` | `0` |
| `GlowEmissive` | Bool | `0x129` | `No` |
| `GlowEnabled` | Bool | `0x128` | `No` |
| `HighDetailLODThreshold` | Real | `0x12c` | `0` |
| `HighDetailOnly` | Bool | `0x15f` | `No` |
| `IdleAnimationState` | AnimationState | `0x0` | - |
| `InitialRecoilSpeed` | VelocityReal | `0x54` | `2` |
| `LowDetailLODThreshold` | Real | `0x130` | `0` |
| `MaxRecoilDistance` | Real | `0x58` | `3` |
| `MinLODRequired` | Enum | `0x64` | `0` |
| `ModelConditionState` | ModelConditionState | `0x0` | - |
| `MultiPlayerOnly` | Bool | `0x15d` | `No` |
| `NoRotate` | Bool | `0x69` | `No` |
| `OkToChangeModelColor` | Bool | `0x68` | `No` |
| `ParticleBonesCheckDrawable` | Bool | `0x12a` | `No` |
| `ParticlesAttachedToAnimatedBones` | Bool | `0x108` | `No` |
| `ProjectileBoneFeedbackEnabledSlots` | BitFlags | `0x50` | `0` |
| `RaisedWallMesh` | AsciiString | `0x110` | `0` |
| `RampMesh1` | AsciiString | `0x114` | `0` |
| `RampMesh2` | AsciiString | `0x118` | `0` |
| `RandomTexture` | 0x004c7c56 | `0x0` | - |
| `RandomTextureFixedRandomIndex` | Bool | `0x88` | `No` |
| `RecoilDamping` | Real | `0x5c` | `0.4` |
| `RecoilSettleSpeed` | VelocityReal | `0x60` | `0.065` |
| `ShadowForceDisable` | Bool | `0x12b` | `No` |
| `ShowShadowWhileContained` | Bool | `0x136` | `No` |
| `StaticModelLODMode` | Bool | `0x135` | `No` |
| `StaticSortLevelWhileFading` | Int | `0x158` | `-1` |
| `SwitchModelLODMode` | Bool | `0x134` | `No` |
| `TimeOfDayTexture` | 0x004c42a8 | `0x0` | - |
| `TrackMarks` | 0x004b65ba | `0x3c` | `0` |
| `TrackMarksLeftBone` | AsciiString | `0x44` | `0` |
| `TrackMarksRightBone` | AsciiString | `0x48` | `0` |
| `TransitionState` | AnimationState | `0x0` | - |
| `TreadAnimationRate` | VelocityReal | `0x190` | `0` |
| `TreadDebrisLeft` | AsciiString | `0x188` | `"TrackDebrisDirtLeft"` |
| `TreadDebrisRight` | AsciiString | `0x18c` | `"TrackDebrisDirtRight"` |
| `TreadDriveSpeedFraction` | Real | `0x198` | `0.3` |
| `TreadPivotSpeedFraction` | Real | `0x194` | `0.6` |
| `UseDefaultAnimation` | Bool | `0x138` | `No` |
| `UseFiringArcRotation` | Bool | `0x6a` | `No` |
| `UseProducerTexture` | Bool | `0xb8` | `No` |
| `UseStandardModelNames` | Bool | `0x137` | `No` |
| `WadingParticleSys` | AsciiString | `0x14` | `0` |
| `WallBoundsMesh` | AsciiString | `0x10c` | `0` |
| `ZWriteDisableOverride` | Bool | `0x15c` | `No` |

## W3DTornadoDraw

`sizeof(ModuleData)` = 0x44, 3 fields

| field | type | offset | default |
|---|---|---|---|
| `DecalCount` | Int | `0x3c` | `0` |
| `DecalMaxRadius` | Real | `0x40` | `200` |
| `DecalTemplate` | DecalTemplate | `0x8` | - |

## W3DTreeDraw

`sizeof(ModuleData)` = 0x64, 24 fields

| field | type | offset | default |
|---|---|---|---|
| `BounceFX` | FXList | `0x24` | `0` |
| `BounceVelocityPercent` | Percent | `0x34` | `0.3` |
| `DarkeningFactor` | Real | `0x1c` | `0` |
| `DoTopple` | Bool | `0x3d` | `No` |
| `FadeDistance` | Real | `0x60` | `40` |
| `FadeRate` | Int | `0x58` | `5` |
| `FadeTarget` | Int | `0x5c` | `105` |
| `InitialAccelPercent` | Percent | `0x30` | `0.01` |
| `InitialVelocityPercent` | Percent | `0x2c` | `0.2` |
| `KillWhenFinishedToppling` | Bool | `0x3c` | `Yes` |
| `MinimumToppleSpeed` | PositiveReal | `0x38` | `0.5` |
| `ModelName` | AsciiString | `0x8` | `0` |
| `MorphFX` | FXList | `0x50` | `0` |
| `MorphTime` | Duration | `0x4c` | - |
| `MorphTree` | AsciiString | `0x48` | `0` |
| `MoveInwardTime` | Duration | `0x14` | `0` |
| `MoveOutwardDistanceFactor` | Real | `0x18` | `1` |
| `MoveOutwardTime` | Duration | `0x10` | `0` |
| `SinkDistance` | PositiveReal | `0x44` | `20` |
| `SinkTime` | Duration | `0x40` | - |
| `StumpName` | AsciiString | `0x28` | - |
| `TaintedTree` | Bool | `0x54` | `No` |
| `TextureName` | AsciiString | `0xc` | `0` |
| `ToppleFX` | FXList | `0x20` | `0` |

## W3DTruckDraw

`sizeof(ModuleData)` = 0x1f0, 83 fields

| field | type | offset | default |
|---|---|---|---|
| `AffectedByStealth` | Bool | `0x15e` | `Yes` |
| `AlphaCameraAtInnerRadius` | Percent | `0x14c` | `1` |
| `AlphaCameraFadeInnerRadius` | PositiveReal | `0x148` | `0` |
| `AlphaCameraFadeOuterRadius` | PositiveReal | `0x144` | `0` |
| `AlphaRefAnimated` | Bool | `0x139` | `No` |
| `AlphaRefRange` | IntRange | `0x13c` | - |
| `AnimationsRequirePower` | Bool | `0x6b` | `Yes` |
| `AnimationState` | AnimationState | `0x0` | - |
| `AttachModel` | AttachModel | `0x0` | - |
| `AttachToBoneInAnotherModule` | 0x004b65ba | `0x40` | `0` |
| `BirthFadeAdditive` | Bool | `0x154` | `No` |
| `BirthFadeTime` | Duration | `0x150` | `0` |
| `BurntTexture` | 0x004c3321 | `0x0` | - |
| `CabBone` | AsciiString | `0x1d4` | `0` |
| `CabRotationMultiplier` | Real | `0x1dc` | `1` |
| `DefaultModelConditionState` | ModelConditionState | `0x0` | - |
| `DependencySharedModelFlags` | ModelConditionFlags | `0xbc` | - |
| `DirtSpray` | AsciiString | `0x18c` | `0` |
| `Dust` | AsciiString | `0x188` | `0` |
| `EmbedPortal` | 0x004c30bd | `0x11c` | `0` |
| `ExtraPublicBone` | AsciiStringList | `0x30` | `0` |
| `GlowEmissive` | Bool | `0x129` | `No` |
| `GlowEnabled` | Bool | `0x128` | `No` |
| `HighDetailLODThreshold` | Real | `0x12c` | `0` |
| `HighDetailOnly` | Bool | `0x15f` | `No` |
| `IdleAnimationState` | AnimationState | `0x0` | - |
| `InitialRecoilSpeed` | VelocityReal | `0x54` | `2` |
| `LeftFrontTireBone` | AsciiString | `0x194` | `0` |
| `LeftFrontTireBone2` | AsciiString | `0x1bc` | `0` |
| `LeftRearTireBone` | AsciiString | `0x19c` | `0` |
| `LeftRearTireBone2` | AsciiString | `0x1c4` | `0` |
| `LowDetailLODThreshold` | Real | `0x130` | `0` |
| `MaxRecoilDistance` | Real | `0x58` | `3` |
| `MidLeftFrontTireBone` | AsciiString | `0x1a4` | `0` |
| `MidLeftMidTireBone` | AsciiString | `0x1b4` | `0` |
| `MidLeftMidTireBone2` | AsciiString | `0x1cc` | `0` |
| `MidLeftRearTireBone` | AsciiString | `0x1ac` | `0` |
| `MidRightFrontTireBone` | AsciiString | `0x1a8` | `0` |
| `MidRightMidTireBone` | AsciiString | `0x1b8` | `0` |
| `MidRightMidTireBone2` | AsciiString | `0x1d0` | `0` |
| `MidRightRearTireBone` | AsciiString | `0x1b0` | `0` |
| `MinLODRequired` | Enum | `0x64` | `0` |
| `ModelConditionState` | ModelConditionState | `0x0` | - |
| `MultiPlayerOnly` | Bool | `0x15d` | `No` |
| `NoRotate` | Bool | `0x69` | `No` |
| `OkToChangeModelColor` | Bool | `0x68` | `No` |
| `ParticleBonesCheckDrawable` | Bool | `0x12a` | `No` |
| `ParticlesAttachedToAnimatedBones` | Bool | `0x108` | `No` |
| `PowerslideRotationAddition` | Real | `0x1ec` | `0` |
| `PowerslideSpray` | AsciiString | `0x190` | `0` |
| `ProjectileBoneFeedbackEnabledSlots` | BitFlags | `0x50` | `0` |
| `RaisedWallMesh` | AsciiString | `0x110` | `0` |
| `RampMesh1` | AsciiString | `0x114` | `0` |
| `RampMesh2` | AsciiString | `0x118` | `0` |
| `RandomTexture` | 0x004c7c56 | `0x0` | - |
| `RandomTextureFixedRandomIndex` | Bool | `0x88` | `No` |
| `RecoilDamping` | Real | `0x5c` | `0.4` |
| `RecoilSettleSpeed` | VelocityReal | `0x60` | `0.065` |
| `RightFrontTireBone` | AsciiString | `0x198` | `0` |
| `RightFrontTireBone2` | AsciiString | `0x1c0` | `0` |
| `RightRearTireBone` | AsciiString | `0x1a0` | `0` |
| `RightRearTireBone2` | AsciiString | `0x1c8` | `0` |
| `RotationDamping` | Real | `0x1e4` | `1` |
| `ShadowForceDisable` | Bool | `0x12b` | `No` |
| `ShowShadowWhileContained` | Bool | `0x136` | `No` |
| `StaticModelLODMode` | Bool | `0x135` | `No` |
| `StaticSortLevelWhileFading` | Int | `0x158` | `-1` |
| `SwitchModelLODMode` | Bool | `0x134` | `No` |
| `TimeOfDayTexture` | 0x004c42a8 | `0x0` | - |
| `TireRotationMultiplier` | Real | `0x1e8` | `1` |
| `TrackMarks` | 0x004b65ba | `0x3c` | `0` |
| `TrackMarksLeftBone` | AsciiString | `0x44` | `0` |
| `TrackMarksRightBone` | AsciiString | `0x48` | `0` |
| `TrailerBone` | AsciiString | `0x1d8` | `0` |
| `TrailerRotationMultiplier` | Real | `0x1e0` | `1` |
| `TransitionState` | AnimationState | `0x0` | - |
| `UseDefaultAnimation` | Bool | `0x138` | `No` |
| `UseFiringArcRotation` | Bool | `0x6a` | `No` |
| `UseProducerTexture` | Bool | `0xb8` | `No` |
| `UseStandardModelNames` | Bool | `0x137` | `No` |
| `WadingParticleSys` | AsciiString | `0x14` | `0` |
| `WallBoundsMesh` | AsciiString | `0x10c` | `0` |
| `ZWriteDisableOverride` | Bool | `0x15c` | `No` |

## WallHubBehavior

`sizeof(ModuleData)` = 0x3c, 11 fields

| field | type | offset | default |
|---|---|---|---|
| `BorderCapTemplateName` | AsciiString | `0x24` | `0` |
| `BuilderRadius` | Real | `0x2c` | `9.876` |
| `CliffCapTemplateName` | AsciiString | `0x1c` | `0` |
| `DefaultSegmentTemplateName` | AsciiString | `0x18` | `0` |
| `ElevatedSegmentTemplateName` | AsciiString | `0x28` | `0` |
| `HubCapTemplateName` | AsciiString | `0x14` | `0` |
| `MaxBuildoutDistance` | Real | `0x30` | `54321` |
| `Options` | BitFlags | `0x34` | `0` |
| `SegmentTemplateName` | AsciiStringList | `0x8` | - |
| `ShoreCapTemplateName` | AsciiString | `0x20` | `0` |
| `StaggeredBuildFactor` | Int | `0x38` | `5` |

## WanderAIUpdate

`sizeof(ModuleData)` = 0x74, 23 fields

| field | type | offset | default |
|---|---|---|---|
| `AILuaEventsList` | AsciiString | `0x2c` | `0` |
| `AttackPriority` | AsciiString | `0x44` | `"DefaultAttackPriority"` |
| `AutoAcquireEnemiesWhenIdle` | BitFlags | `0x1c` | `0` |
| `BurningDeathTime` | Duration | `0x40` | `0` |
| `CanAttackWhileContained` | Bool | `0x25` | `No` |
| `ComboLocoAttackDistance` | Real | `0x4c` | `80` |
| `ComboLocomotorSet` | Enum | `0x50` | `0` |
| `ConditionForEntry` | ModelConditionFlag | `0x68` | `-1` |
| `FadeOnPortals` | Bool | `0x54` | `No` |
| `HoldGroundCloseRangeDistance` | Real | `0x28` | `0` |
| `MaxCowerTime` | Duration | `0x30` | `0` |
| `MinCowerTime` | Duration | `0x34` | `0` |
| `MoodAttackCheckRate` | Duration | `0x18` | - |
| `RampageRequiresAflame` | Bool | `0x3c` | `No` |
| `RampageTime` | Duration | `0x38` | `0` |
| `Selectable` | Bool | `0x6c` | `Yes` |
| `SpecialContactPoints` | AsciiStringList | `0x58` | `0` |
| `StandGround` | Bool | `0x24` | `No` |
| `StopChaseDistance` | Real | `0x20` | `500` |
| `TimeToEjectPassengersOnRampage` | Duration | `0x48` | `0` |
| `Turret` | 0x006620a2 | `0x14` | `0` |
| `WanderDistance` | Int | `0x70` | `30` |
| `WildBeast` | Bool | `0x64` | `No` |

## WeaponBonusUpgrade

`sizeof(ModuleData)` = 0x138, 6 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## WeaponBonusUpgrade

`sizeof(ModuleData)` = 0x138, 6 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |

## WeaponChangeSpecialPowerModule

`sizeof(ModuleData)` = 0x9c, 40 fields

| field | type | offset | default |
|---|---|---|---|
| `AdjustVictim` | Bool | `0x68` | `No` |
| `AffectAllies` | Bool | `0x60` | `Yes` |
| `AffectEvil` | Bool | `0x5f` | `No` |
| `AffectGood` | Bool | `0x5e` | `No` |
| `AntiCategory` | 0x0089f32d | `0x34` | `0` |
| `AntiFX` | FXList | `0x4c` | `0` |
| `AttributeModifier` | AsciiString | `0x18` | `""` |
| `AttributeModifierAffects` | KindOfFilter | `0x24` | - |
| `AttributeModifierAffectsSelf` | Bool | `0x20` | `No` |
| `AttributeModifierFX` | FXList | `0x28` | `0` |
| `AttributeModifierRange` | Real | `0x1c` | `0` |
| `AttributeModifierWeatherBased` | Bool | `0x2c` | `No` |
| `AvailableAtStart` | Bool | `0x61` | `Yes` |
| `BurnDecayModifier` | Int | `0x70` | `0` |
| `ChangeWeather` | WeatherType | `0x64` | `5` |
| `DisableDuringAnimDuration` | Bool | `0x5c` | `No` |
| `DistanceFromCommandCenter` | Real | `0x78` | `0` |
| `FlagsUsedForToggle` | WeaponSetFlags | `0x7c` | `0` |
| `GiveLevels` | Int | `0x58` | `0` |
| `IdleWhenStartingPower` | Bool | `0x5d` | `No` |
| `InitiateFX` | FXList | `0x44` | `0` |
| `InitiateSound` | AudioEventRTS | `0x10` | `-1` |
| `OnTriggerRechargeSpecialPower` | AsciiString | `0x6c` | `""` |
| `ReEnableAntiCategory` | Bool | `0x42` | `No` |
| `RequirementsFilterMPSkirmish` | KindOfFilter | `0x38` | - |
| `RequirementsFilterStrategic` | KindOfFilter | `0x3c` | `0` |
| `SetModelCondition` | ModelConditionFlag | `0x50` | `-1` |
| `SetModelConditionTime` | Real | `0x54` | `1` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0xd` | `No` |
| `TargetAllSides` | Bool | `0x41` | `No` |
| `TargetEnemy` | Bool | `0x40` | `No` |
| `ToggleOffAttributeModifier` | AsciiString | `0x98` | - |
| `ToggleOffSleepFrames` | Int | `0x90` | `0` |
| `ToggleOnAttributeModifier` | AsciiString | `0x94` | - |
| `ToggleOnSleepFrames` | Int | `0x8c` | `0` |
| `TriggerFX` | FXList | `0x48` | `0` |
| `UpdateModuleStartsAttack` | Bool | `0xc` | `No` |
| `UseDistanceFromCommandCenter` | Bool | `0x74` | `No` |
| `WeatherDuration` | Duration | `0x30` | `0` |

## WeaponFireSpecialAbilityUpdate

`sizeof(ModuleData)` = 0xe4, 66 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `BusyForDuration` | Duration | `0xdc` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `NeedLivingTargets` | Bool | `0xe0` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PlayWeaponPreFireFX` | Bool | `0xe1` | `No` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipContinue` | Bool | `0xd8` | `No` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `SpecialWeapon` | AsciiString | `0xd0` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |
| `WhichSpecialWeapon` | Int | `0xd4` | `0` |

## WeaponModeSpecialPowerUpdate

`sizeof(ModuleData)` = 0x34, 7 fields

| field | type | offset | default |
|---|---|---|---|
| `AttributeModifier` | AsciiString | `0x18` | `0` |
| `Duration` | Duration | `0x1c` | `0` |
| `InitiateSound` | AudioEventRTS | `0xc` | `-1` |
| `LockWeaponSlot` | LookupList | `0x20` | `5` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x8` | `0` |
| `StartsPaused` | Bool | `0x14` | `No` |
| `WeaponSetFlags` | WeaponSetFlags | `0x24` | - |

## WeaponSetSpecialAbilityUpdate

`sizeof(ModuleData)` = 0xd8, 62 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |
| `WeaponsetEffectDuration` | Duration | `0xd0` | `0` |
| `WhichWeaponSet` | Int | `0xd4` | `0` |

## WeaponSetUpgrade

`sizeof(ModuleData)` = 0x148, 7 fields

| field | type | offset | default |
|---|---|---|---|
| `ConflictsWith` | UpgradeMask | `0x90` | - |
| `CustomAnimAndDuration` | AnimAndDuration | `0x120` | - |
| `Permanent` | Bool | `0x12e` | - |
| `RequiresAllConflictingTriggers` | Bool | `0x12d` | - |
| `RequiresAllTriggers` | Bool | `0x12c` | `No` |
| `TriggeredBy` | UpgradeMask | `0x0` | - |
| `WeaponCondition` | WeaponSetFlags | `0x138` | - |

## WorkerAIUpdate

`sizeof(ModuleData)` = 0x94, 31 fields

| field | type | offset | default |
|---|---|---|---|
| `AILuaEventsList` | AsciiString | `0x2c` | `0` |
| `AttackPriority` | AsciiString | `0x44` | `"DefaultAttackPriority"` |
| `AutoAcquireEnemiesWhenIdle` | BitFlags | `0x1c` | `0` |
| `BoredRange` | Real | `0x70` | `0` |
| `BoredTime` | DurationReal | `0x6c` | `0` |
| `BurningDeathTime` | Duration | `0x40` | `0` |
| `CanAttackWhileContained` | Bool | `0x25` | `No` |
| `ComboLocoAttackDistance` | Real | `0x4c` | `80` |
| `ComboLocomotorSet` | Enum | `0x50` | `0` |
| `FadeOnPortals` | Bool | `0x54` | `No` |
| `HarvestActionTime` | Duration | `0x8c` | `0` |
| `HarvestActivationRange` | Real | `0x84` | `50` |
| `HarvestPreparationTime` | Duration | `0x88` | `0` |
| `HarvestTrees` | Bool | `0x80` | `No` |
| `HoldGroundCloseRangeDistance` | Real | `0x28` | `0` |
| `MaxBoxes` | Int | `0x64` | `0` |
| `MaxCowerTime` | Duration | `0x30` | `0` |
| `MinCowerTime` | Duration | `0x34` | `0` |
| `MoodAttackCheckRate` | Duration | `0x18` | - |
| `RampageRequiresAflame` | Bool | `0x3c` | `No` |
| `RampageTime` | Duration | `0x38` | `0` |
| `RepairHealthPercentPerSecond` | Percent | `0x68` | `0` |
| `SpecialContactPoints` | AsciiStringList | `0x58` | `0` |
| `StandGround` | Bool | `0x24` | `No` |
| `StopChaseDistance` | Real | `0x20` | `500` |
| `SuppliesDepletedVoice` | AudioEventRTS | `0x90` | `0` |
| `SupplyCenterActionDelay` | Duration | `0x74` | `0` |
| `SupplyWarehouseActionDelay` | Duration | `0x78` | `0` |
| `SupplyWarehouseScanDistance` | Real | `0x7c` | `100` |
| `TimeToEjectPassengersOnRampage` | Duration | `0x48` | `0` |
| `Turret` | 0x006620a2 | `0x14` | `0` |

## WoundArrowUpdate

`sizeof(ModuleData)` = 0xd8, 62 fields

| field | type | offset | default |
|---|---|---|---|
| `AbilityAbortRange` | Real | `0x50` | `1e+07` |
| `ActiveLoopSound` | AudioEventRTS | `0x34` | `0` |
| `AlwaysValidateSpecialObjects` | Bool | `0xae` | `No` |
| `ApproachRequiresLOS` | Bool | `0xb1` | `No` |
| `ApproachUntilMembersInRange` | Bool | `0xc5` | `No` |
| `AttributeModifierDuration` | Duration | `0x98` | `0` |
| `AwardXPForTriggering` | Int | `0x64` | `0` |
| `ChainedButton` | AsciiString | `0xc0` | `""` |
| `ChargeAttackSpeedBoost` | Bool | `0xb2` | `No` |
| `ContactPointOverride` | AsciiString | `0xbc` | `0` |
| `CustomAnimAndDuration` | AnimAndDuration | `0x18` | `-1` |
| `DisableFXParticleSystem` | ParticleSystem | `0x3c` | `0` |
| `DisableWhenWearingTheRing` | Bool | `0xb6` | `No` |
| `DoCaptureFX` | Bool | `0xaf` | `No` |
| `EffectDuration` | Duration | `0x7c` | `0` |
| `EffectRange` | Real | `0x60` | `0` |
| `EffectValue` | Int | `0x5c` | `0` |
| `FleeDistance` | Real | `0xd0` | `100` |
| `FleeRangeAfterCompletion` | Real | `0x58` | `0` |
| `FlipOwnerAfterPacking` | Bool | `0xac` | `No` |
| `FlipOwnerAfterUnpacking` | Bool | `0xad` | `No` |
| `ForbiddenConditions` | BitFlags | `0xd4` | `0` |
| `FreezeAfterTriggerDuration` | Duration | `0x9c` | `0` |
| `GrabPassengerAnimAndDuration` | AnimAndDuration | `0x24` | `-1` |
| `GrabPassengerHealGainPercent` | NonNegativeReal | `0x30` | `100` |
| `IgnoreFacingCheck` | Bool | `0xc6` | `No` |
| `Instant` | Bool | `0xb7` | `No` |
| `KillAttributeModifierOnExit` | Bool | `0xb3` | `No` |
| `KillAttributeModifierOnRejected` | Bool | `0xb4` | `No` |
| `LoseStealthOnTrigger` | Bool | `0xb0` | `No` |
| `MaxSpecialObjects` | Int | `0x80` | `0` |
| `MustFinishAbility` | Bool | `0xb5` | `No` |
| `NeedCollisionBeforeTrigger` | Bool | `0xb8` | `No` |
| `PackSound` | AudioEventRTS | `0x8` | `0` |
| `PackTime` | Duration | `0x84` | `0` |
| `PackUnpackVariationFactor` | Real | `0x54` | `0` |
| `ParalyzeDurationWhenAborted` | Duration | `0x94` | `0` |
| `ParalyzeDurationWhenCompleted` | Duration | `0x90` | `0` |
| `PersistentCount` | Int | `0x70` | `-1` |
| `PersistentPrepTime` | Duration | `0x78` | `0` |
| `PreparationTime` | Duration | `0x74` | `0` |
| `PrepSoundLoop` | AudioEventRTS | `0x10` | `0` |
| `PreTriggerUnstealthTime` | Duration | `0x8c` | `0` |
| `RejectedConditions` | BitFlags | `0xa4` | `0` |
| `RequiredConditions` | BitFlags | `0xa0` | `0` |
| `SkillPointsForTriggering` | Int | `0x68` | `-1` |
| `SkipPackingWithNoTarget` | Bool | `0xa8` | `No` |
| `SpecialObject` | AsciiString | `0x40` | `0` |
| `SpecialObjectAttachToBone` | AsciiString | `0x44` | `0` |
| `SpecialObjectsPersistent` | Bool | `0xa9` | `No` |
| `SpecialObjectsPersistWhenOwnerDies` | Bool | `0xab` | `No` |
| `SpecialPowerTemplate` | SpecialPowerTemplate | `0x38` | `0` |
| `StartAbilityRange` | Real | `0x4c` | `1e+07` |
| `SuppressForHordes` | Bool | `0xc4` | `No` |
| `TriggerAttributeModifier` | AsciiString | `0x48` | `0` |
| `TriggerModelCondition` | ModelConditionFlag | `0xc8` | `-1` |
| `TriggerModelConditionDuration` | Real | `0xcc` | `0` |
| `TriggerSound` | AudioEventRTS | `0x14` | `0` |
| `UniqueSpecialObjectTargets` | Bool | `0xaa` | `No` |
| `UnpackingVariation` | Int | `0x6c` | `0` |
| `UnpackSound` | AudioEventRTS | `0xc` | `0` |
| `UnpackTime` | Duration | `0x88` | `0` |
