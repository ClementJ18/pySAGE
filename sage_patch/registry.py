"""Registry of installable patches, keyed by :attr:`Patch.name`, that the ``sage-patch`` CLI
lists, applies and verifies. Add a patch here to expose it on the command line.

Patches imported from :mod:`sage_patch.patches.experimental` are **unstable and largely untested**
and set :attr:`Patch.experimental`, which is what makes `list` mark them and `apply` warn. They are
registered rather than hidden on purpose - a patch nobody can run is a patch nobody can find the
problem in, and the warning is the thing that makes offering it honest."""

from sage_patch.patcher import Patch
from sage_patch.patches.ai_construction_gate import AiConstructionGatePatch
from sage_patch.patches.ai_revive_gate import AiReviveGatePatch
from sage_patch.patches.asset_load_profile import AssetLoadProfilePatch
from sage_patch.patches.attack_requires_damage import AttackRequiresDamagePatch
from sage_patch.patches.auto_deposit_inflation import AutoDepositInflationPatch
from sage_patch.patches.banner_filter import BannerFilterPatch
from sage_patch.patches.banner_modifier import BannerModifierPatch
from sage_patch.patches.binary_attest import BinaryAttestPatch
from sage_patch.patches.cah_factions import CahFactionsPatch
from sage_patch.patches.combo_horde_recruitment import ComboHordeRecruitmentPatch
from sage_patch.patches.command_point_cost import CommandPointCostPatch
from sage_patch.patches.command_point_upkeep import CommandPointUpkeepPatch
from sage_patch.patches.commandset import CommandSetLimitPatch
from sage_patch.patches.commandset_button_upgrade import CommandSetButtonUpgradePatch
from sage_patch.patches.crash_dump import CrashDumpPatch
from sage_patch.patches.description_timers import DescriptionTimersPatch
from sage_patch.patches.desert_weather import (
    DesertWeatherPatch,
    DesertWeatherWorldbuilderPatch,
)
from sage_patch.patches.detachable_rider_heal import DetachableRiderHealPatch
from sage_patch.patches.experimental.campaign_select import CampaignSelectPatch
from sage_patch.patches.experimental.capture_the_flag import CaptureTheFlagPatch
from sage_patch.patches.experimental.cooldown_through_death import CooldownThroughDeathPatch
from sage_patch.patches.experimental.headless import HeadlessPatch
from sage_patch.patches.experimental.hero_mana import HeroManaPatch
from sage_patch.patches.experimental.live_bridge import LiveBridgePatch
from sage_patch.patches.experimental.living_world_override import LivingWorldOverridePatch
from sage_patch.patches.experimental.recharge_rescale import RechargeRescalePatch
from sage_patch.patches.experimental.render_rate import RenderRatePatch
from sage_patch.patches.experimental.second_resource import SecondResourcePatch
from sage_patch.patches.experimental.smart_rally import SmartRallyPatch
from sage_patch.patches.experimental.special_power_charges import SpecialPowerChargesPatch
from sage_patch.patches.experimental.spell_store_upgrade import SpellStoreUpgradePatch
from sage_patch.patches.experimental.standalone_launcher import StandaloneLauncherPatch
from sage_patch.patches.foundation_rebind import FoundationRebindPatch
from sage_patch.patches.hero_bar_slots import HeroBarSlotsPatch
from sage_patch.patches.hero_recruit_parallel import HeroRecruitParallelPatch
from sage_patch.patches.herobar import HeroBarPatch, HeroBarWorldbuilderPatch
from sage_patch.patches.horde_exit_absorption import HordeExitAbsorptionPatch
from sage_patch.patches.infantry_lighting import InfantryLightingPatch
from sage_patch.patches.inflation_readout import InflationReadoutPatch
from sage_patch.patches.large_group_bonus_filter import LargeGroupBonusFilterPatch
from sage_patch.patches.lifetime_extend_upgrade import LifetimeExtendUpgradePatch
from sage_patch.patches.maintenance_cost import MaintenanceCostPatch
from sage_patch.patches.multi_execute_gate import MultiExecuteGatePatch
from sage_patch.patches.multi_instance import MultiInstanceLauncherPatch, MultiInstancePatch
from sage_patch.patches.objectives_screen import ObjectivesScreenPatch
from sage_patch.patches.observer_command_range import ObserverCommandRangePatch
from sage_patch.patches.observer_switch import ObserverSwitchPatch
from sage_patch.patches.player_heal_filter import PlayerHealFilterPatch
from sage_patch.patches.production_condition import (
    ProductionConditionPatch,
    ProductionConditionWorldbuilderPatch,
)
from sage_patch.patches.production_split import (
    ProductionSplitPatch,
    ProductionSplitWorldbuilderPatch,
)
from sage_patch.patches.queue_ignore_cp import QueueIgnoreCpPatch
from sage_patch.patches.quiet_exit import QuietExitPatch
from sage_patch.patches.rebuild_hole_construction import RebuildHoleConstructionPatch
from sage_patch.patches.replay_annotations import ReplayAnnotationsPatch
from sage_patch.patches.replay_outcome import ReplayOutcomePatch
from sage_patch.patches.science_prereqs import (
    SciencePrereqPatch,
    SciencePrereqWorldbuilderPatch,
)
from sage_patch.patches.skirmish_ai_fallback import SkirmishAiFallbackPatch
from sage_patch.patches.skirmish_replay import SkirmishReplayPatch
from sage_patch.patches.spawn_union import SpawnUnionPatch
from sage_patch.patches.terrain_resource_exp import TerrainResourceExpPatch
from sage_patch.patches.trigger_recharge_list import TriggerRechargeListPatch
from sage_patch.patches.unique_production_id import UniqueProductionIdPatch
from sage_patch.patches.upgrade_description import UpgradeDescriptionPatch
from sage_patch.patches.upgrade_grant_lists import UpgradeGrantListsPatch
from sage_patch.patches.wall_mesh_release import WallMeshReleasePatch
from sage_patch.patches.worldbuilder_label_assert import WorldbuilderLabelAssertPatch
from sage_patch.patches.worldbuilder_mod import WorldbuilderModPatch
from sage_patch.patches.worldbuilder_object_typeahead import (
    WorldbuilderObjectTypeaheadPatch,
)
from sage_patch.patches.worldbuilder_silent_errors import (
    WorldbuilderSilentErrorsPatch,
)

PATCHES: dict[str, type[Patch]] = {
    CommandSetLimitPatch.name: CommandSetLimitPatch,
    CommandSetButtonUpgradePatch.name: CommandSetButtonUpgradePatch,
    CahFactionsPatch.name: CahFactionsPatch,
    AiReviveGatePatch.name: AiReviveGatePatch,
    AiConstructionGatePatch.name: AiConstructionGatePatch,
    ProductionConditionPatch.name: ProductionConditionPatch,
    ProductionConditionWorldbuilderPatch.name: ProductionConditionWorldbuilderPatch,
    DesertWeatherPatch.name: DesertWeatherPatch,
    DesertWeatherWorldbuilderPatch.name: DesertWeatherWorldbuilderPatch,
    UniqueProductionIdPatch.name: UniqueProductionIdPatch,
    ReplayOutcomePatch.name: ReplayOutcomePatch,
    ReplayAnnotationsPatch.name: ReplayAnnotationsPatch,
    SkirmishReplayPatch.name: SkirmishReplayPatch,
    SkirmishAiFallbackPatch.name: SkirmishAiFallbackPatch,
    ObjectivesScreenPatch.name: ObjectivesScreenPatch,
    ObserverSwitchPatch.name: ObserverSwitchPatch,
    ObserverCommandRangePatch.name: ObserverCommandRangePatch,
    LiveBridgePatch.name: LiveBridgePatch,
    LivingWorldOverridePatch.name: LivingWorldOverridePatch,
    TerrainResourceExpPatch.name: TerrainResourceExpPatch,
    HeroManaPatch.name: HeroManaPatch,
    CommandPointUpkeepPatch.name: CommandPointUpkeepPatch,
    BannerFilterPatch.name: BannerFilterPatch,
    BannerModifierPatch.name: BannerModifierPatch,
    PlayerHealFilterPatch.name: PlayerHealFilterPatch,
    LargeGroupBonusFilterPatch.name: LargeGroupBonusFilterPatch,
    LifetimeExtendUpgradePatch.name: LifetimeExtendUpgradePatch,
    SecondResourcePatch.name: SecondResourcePatch,
    InflationReadoutPatch.name: InflationReadoutPatch,
    SciencePrereqPatch.name: SciencePrereqPatch,
    SciencePrereqWorldbuilderPatch.name: SciencePrereqWorldbuilderPatch,
    HeroBarPatch.name: HeroBarPatch,
    HeroBarWorldbuilderPatch.name: HeroBarWorldbuilderPatch,
    HeroBarSlotsPatch.name: HeroBarSlotsPatch,
    InfantryLightingPatch.name: InfantryLightingPatch,
    MultiExecuteGatePatch.name: MultiExecuteGatePatch,
    AttackRequiresDamagePatch.name: AttackRequiresDamagePatch,
    SpawnUnionPatch.name: SpawnUnionPatch,
    QueueIgnoreCpPatch.name: QueueIgnoreCpPatch,
    HeroRecruitParallelPatch.name: HeroRecruitParallelPatch,
    RebuildHoleConstructionPatch.name: RebuildHoleConstructionPatch,
    HordeExitAbsorptionPatch.name: HordeExitAbsorptionPatch,
    ComboHordeRecruitmentPatch.name: ComboHordeRecruitmentPatch,
    MultiInstancePatch.name: MultiInstancePatch,
    MultiInstanceLauncherPatch.name: MultiInstanceLauncherPatch,
    StandaloneLauncherPatch.name: StandaloneLauncherPatch,
    CampaignSelectPatch.name: CampaignSelectPatch,
    FoundationRebindPatch.name: FoundationRebindPatch,
    HeadlessPatch.name: HeadlessPatch,
    ProductionSplitPatch.name: ProductionSplitPatch,
    ProductionSplitWorldbuilderPatch.name: ProductionSplitWorldbuilderPatch,
    BinaryAttestPatch.name: BinaryAttestPatch,
    UpgradeDescriptionPatch.name: UpgradeDescriptionPatch,
    TriggerRechargeListPatch.name: TriggerRechargeListPatch,
    UpgradeGrantListsPatch.name: UpgradeGrantListsPatch,
    DescriptionTimersPatch.name: DescriptionTimersPatch,
    RechargeRescalePatch.name: RechargeRescalePatch,
    CooldownThroughDeathPatch.name: CooldownThroughDeathPatch,
    CrashDumpPatch.name: CrashDumpPatch,
    QuietExitPatch.name: QuietExitPatch,
    CaptureTheFlagPatch.name: CaptureTheFlagPatch,
    WorldbuilderModPatch.name: WorldbuilderModPatch,
    WorldbuilderLabelAssertPatch.name: WorldbuilderLabelAssertPatch,
    WorldbuilderSilentErrorsPatch.name: WorldbuilderSilentErrorsPatch,
    WorldbuilderObjectTypeaheadPatch.name: WorldbuilderObjectTypeaheadPatch,
    MaintenanceCostPatch.name: MaintenanceCostPatch,
    AutoDepositInflationPatch.name: AutoDepositInflationPatch,
    WallMeshReleasePatch.name: WallMeshReleasePatch,
    SmartRallyPatch.name: SmartRallyPatch,
    SpellStoreUpgradePatch.name: SpellStoreUpgradePatch,
    CommandPointCostPatch.name: CommandPointCostPatch,
    DetachableRiderHealPatch.name: DetachableRiderHealPatch,
    SpecialPowerChargesPatch.name: SpecialPowerChargesPatch,
    RenderRatePatch.name: RenderRatePatch,
    AssetLoadProfilePatch.name: AssetLoadProfilePatch,
}

__all__ = ["PATCHES"]
