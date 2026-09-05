"""Registry of installable patches, keyed by :attr:`Patch.name`, that the ``sage-patch`` CLI
lists, applies and verifies. Add a patch here to expose it on the command line.

Patches imported from :mod:`sage_patch.patches.experimental` are **unstable and largely untested**
and set :attr:`Patch.experimental`, which is what makes `list` mark them and `apply` warn. They are
registered rather than hidden on purpose - a patch nobody can run is a patch nobody can find the
problem in, and the warning is the thing that makes offering it honest.

That attribute is also what orders them: the settled patches come first and the experimental ones
after, each block alphabetical (see :func:`_order`). Everything that walks the registry inherits
it, so a patch is added to :data:`_REGISTERED` wherever its import goes and lands in the right
place in every list on its own."""

from sage_patch.patcher import Patch
from sage_patch.patches.ai_command_null_target import AiCommandNullTargetPatch
from sage_patch.patches.ai_construction_gate import AiConstructionGatePatch
from sage_patch.patches.ai_flag_capture_gate import AiFlagCaptureGatePatch
from sage_patch.patches.ai_hero_build_delay import AiHeroBuildDelayPatch
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
from sage_patch.patches.deploy_before_attack import DeployBeforeAttackPatch
from sage_patch.patches.description_timers import DescriptionTimersPatch
from sage_patch.patches.desert_weather import (
    DesertWeatherPatch,
    DesertWeatherWorldbuilderPatch,
)
from sage_patch.patches.desync_debug import DesyncDebugPatch
from sage_patch.patches.detachable_rider_heal import DetachableRiderHealPatch
from sage_patch.patches.experimental.battle_school import BattleSchoolPatch
from sage_patch.patches.experimental.campaign_army_verbs import CampaignArmyVerbsPatch
from sage_patch.patches.experimental.campaign_select import CampaignSelectPatch
from sage_patch.patches.experimental.capture_the_flag import CaptureTheFlagPatch
from sage_patch.patches.experimental.command_line_skirmish import CommandLineSkirmishPatch
from sage_patch.patches.experimental.cooldown_through_death import CooldownThroughDeathPatch
from sage_patch.patches.experimental.headless import HeadlessPatch
from sage_patch.patches.experimental.hero_army_carryover import HeroArmyCarryoverPatch
from sage_patch.patches.experimental.hero_mana import HeroManaPatch
from sage_patch.patches.experimental.interpolation_alpha import InterpolationAlphaPatch
from sage_patch.patches.experimental.live_bridge import LiveBridgePatch
from sage_patch.patches.experimental.living_world_override import LivingWorldOverridePatch
from sage_patch.patches.experimental.recharge_rescale import RechargeRescalePatch
from sage_patch.patches.experimental.render_rate import RenderRatePatch
from sage_patch.patches.experimental.second_resource import SecondResourcePatch
from sage_patch.patches.experimental.smart_rally import SmartRallyPatch
from sage_patch.patches.experimental.special_power_charges import SpecialPowerChargesPatch
from sage_patch.patches.experimental.standalone_launcher import StandaloneLauncherPatch
from sage_patch.patches.experimental.unit_plate_option import UnitPlateOptionPatch
from sage_patch.patches.fire_at_attacker import FireAtAttackerPatch
from sage_patch.patches.foundation_rebind import FoundationRebindPatch
from sage_patch.patches.give_upgrade_all import GiveUpgradeAllPatch
from sage_patch.patches.healing_received import (
    HealingReceivedPatch,
    HealingReceivedWorldbuilderPatch,
)
from sage_patch.patches.hero_bar_slots import HeroBarSlotsPatch
from sage_patch.patches.hero_recruit_parallel import HeroRecruitParallelPatch
from sage_patch.patches.herobar import HeroBarPatch, HeroBarWorldbuilderPatch
from sage_patch.patches.horde_exit_absorption import HordeExitAbsorptionPatch
from sage_patch.patches.horde_member_speed import HordeMemberSpeedPatch
from sage_patch.patches.infantry_lighting import InfantryLightingPatch
from sage_patch.patches.inflation_readout import InflationReadoutPatch
from sage_patch.patches.large_group_bonus import LargeGroupBonusPatch
from sage_patch.patches.lifetime_fields import LifetimeFieldsPatch
from sage_patch.patches.maintenance_cost import MaintenanceCostPatch
from sage_patch.patches.multi_execute_gate import MultiExecuteGatePatch
from sage_patch.patches.multi_instance import MultiInstanceLauncherPatch, MultiInstancePatch
from sage_patch.patches.multi_select_group import MultiSelectGroupPatch
from sage_patch.patches.object_image_upgrade import (
    ObjectImageUpgradePatch,
    ObjectImageUpgradeWorldbuilderPatch,
)
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
from sage_patch.patches.scenario_player_factions import ScenarioPlayerFactionsPatch
from sage_patch.patches.science_prereqs import (
    SciencePrereqPatch,
    SciencePrereqWorldbuilderPatch,
)
from sage_patch.patches.skirmish_ai_fallback import SkirmishAiFallbackPatch
from sage_patch.patches.skirmish_replay import SkirmishReplayPatch
from sage_patch.patches.spawn_union import SpawnUnionPatch
from sage_patch.patches.spell_store_upgrade import SpellStoreUpgradePatch
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

#: Every registered patch, in class-name order so a new one is added beside its import. This is
#: **not** the order they are presented in: :data:`PATCHES` is built from this by sorting, and
#: every command that walks the registry - `list`, the `apply` and `verify` sub-command lists,
#: `sagepatch` - inherits that order rather than an order maintained by hand here.
_REGISTERED: tuple[type[Patch], ...] = (
    AiCommandNullTargetPatch,
    AiConstructionGatePatch,
    AiFlagCaptureGatePatch,
    AiHeroBuildDelayPatch,
    AiReviveGatePatch,
    AssetLoadProfilePatch,
    AttackRequiresDamagePatch,
    AutoDepositInflationPatch,
    BannerFilterPatch,
    BannerModifierPatch,
    BattleSchoolPatch,
    BinaryAttestPatch,
    CahFactionsPatch,
    CampaignArmyVerbsPatch,
    CampaignSelectPatch,
    CaptureTheFlagPatch,
    ComboHordeRecruitmentPatch,
    CommandLineSkirmishPatch,
    CommandPointCostPatch,
    CommandPointUpkeepPatch,
    CommandSetButtonUpgradePatch,
    CommandSetLimitPatch,
    CooldownThroughDeathPatch,
    CrashDumpPatch,
    DeployBeforeAttackPatch,
    DescriptionTimersPatch,
    DesertWeatherPatch,
    DesertWeatherWorldbuilderPatch,
    DesyncDebugPatch,
    DetachableRiderHealPatch,
    FireAtAttackerPatch,
    FoundationRebindPatch,
    GiveUpgradeAllPatch,
    HeadlessPatch,
    HealingReceivedPatch,
    HealingReceivedWorldbuilderPatch,
    HeroArmyCarryoverPatch,
    HeroBarPatch,
    HeroBarSlotsPatch,
    HeroBarWorldbuilderPatch,
    HeroManaPatch,
    HeroRecruitParallelPatch,
    HordeExitAbsorptionPatch,
    HordeMemberSpeedPatch,
    InfantryLightingPatch,
    InflationReadoutPatch,
    InterpolationAlphaPatch,
    LargeGroupBonusPatch,
    LifetimeFieldsPatch,
    LiveBridgePatch,
    LivingWorldOverridePatch,
    MaintenanceCostPatch,
    MultiExecuteGatePatch,
    MultiInstanceLauncherPatch,
    MultiInstancePatch,
    MultiSelectGroupPatch,
    ObjectImageUpgradePatch,
    ObjectImageUpgradeWorldbuilderPatch,
    ObjectivesScreenPatch,
    ObserverCommandRangePatch,
    ObserverSwitchPatch,
    PlayerHealFilterPatch,
    ProductionConditionPatch,
    ProductionConditionWorldbuilderPatch,
    ProductionSplitPatch,
    ProductionSplitWorldbuilderPatch,
    QueueIgnoreCpPatch,
    QuietExitPatch,
    RebuildHoleConstructionPatch,
    RechargeRescalePatch,
    RenderRatePatch,
    ReplayAnnotationsPatch,
    ReplayOutcomePatch,
    ScenarioPlayerFactionsPatch,
    SciencePrereqPatch,
    SciencePrereqWorldbuilderPatch,
    SecondResourcePatch,
    SkirmishAiFallbackPatch,
    SkirmishReplayPatch,
    SmartRallyPatch,
    SpawnUnionPatch,
    SpecialPowerChargesPatch,
    SpellStoreUpgradePatch,
    StandaloneLauncherPatch,
    TerrainResourceExpPatch,
    TriggerRechargeListPatch,
    UniqueProductionIdPatch,
    UnitPlateOptionPatch,
    UpgradeDescriptionPatch,
    UpgradeGrantListsPatch,
    WallMeshReleasePatch,
    WorldbuilderLabelAssertPatch,
    WorldbuilderModPatch,
    WorldbuilderObjectTypeaheadPatch,
    WorldbuilderSilentErrorsPatch,
)


def _order(cls: type[Patch]) -> tuple[bool, str]:
    """Settled patches first, then the experimental ones, each block alphabetical by name.

    The split is the point of the ordering: somebody reading a list top to bottom meets everything
    that has been played before anything that has not, and the `exp` rows arrive together instead
    of scattered through the settled ones where a marker is easy to read past. Alphabetical within
    each block is what makes a name findable once the reader knows what they are looking for."""
    return (cls.experimental, cls.name)


#: The name -> patch map the CLI dispatches over, in the order everything lists them: see
#: :func:`_order`. Dicts keep insertion order, so iterating this is already sorted.
PATCHES: dict[str, type[Patch]] = {cls.name: cls for cls in sorted(_REGISTERED, key=_order)}

__all__ = ["PATCHES"]
