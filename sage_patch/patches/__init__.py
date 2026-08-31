"""Concrete :class:`~sage_patch.patcher.Patch` implementations."""

from sage_patch.patches.ai_command_null_target import AiCommandNullTargetPatch
from sage_patch.patches.ai_construction_gate import AiConstructionGatePatch
from sage_patch.patches.ai_flag_capture_gate import AiFlagCaptureGatePatch
from sage_patch.patches.ai_revive_gate import AiReviveGatePatch
from sage_patch.patches.auto_deposit_inflation import AutoDepositInflationPatch
from sage_patch.patches.banner_filter import BannerFilterPatch
from sage_patch.patches.cah_factions import CahFactionsPatch
from sage_patch.patches.command_point_cost import CommandPointCostPatch
from sage_patch.patches.command_point_upkeep import CommandPointUpkeepPatch
from sage_patch.patches.commandset import CommandSetLimitPatch
from sage_patch.patches.desert_weather import (
    DesertWeatherPatch,
    DesertWeatherWorldbuilderPatch,
)
from sage_patch.patches.experimental.headless import HeadlessPatch
from sage_patch.patches.experimental.hero_mana import HeroManaPatch
from sage_patch.patches.experimental.horde_orphan_target import HordeOrphanTargetPatch
from sage_patch.patches.experimental.live_bridge import LiveBridgePatch
from sage_patch.patches.experimental.living_world_override import LivingWorldOverridePatch
from sage_patch.patches.experimental.recharge_rescale import RechargeRescalePatch
from sage_patch.patches.experimental.second_resource import SecondResourcePatch
from sage_patch.patches.experimental.smart_rally import SmartRallyPatch
from sage_patch.patches.experimental.unit_plate_option import UnitPlateOptionPatch
from sage_patch.patches.fire_at_attacker import FireAtAttackerPatch
from sage_patch.patches.foundation_rebind import FoundationRebindPatch
from sage_patch.patches.give_upgrade_all import GiveUpgradeAllPatch
from sage_patch.patches.healing_received import HealingReceivedPatch
from sage_patch.patches.hero_bar_slots import HeroBarSlotsPatch
from sage_patch.patches.inflation_readout import InflationReadoutPatch
from sage_patch.patches.large_group_bonus import LargeGroupBonusPatch
from sage_patch.patches.lifetime_fields import LifetimeFieldsPatch
from sage_patch.patches.maintenance_cost import MaintenanceCostPatch
from sage_patch.patches.multi_execute_gate import MultiExecuteGatePatch
from sage_patch.patches.object_image_upgrade import (
    ObjectImageUpgradePatch,
    ObjectImageUpgradeWorldbuilderPatch,
)
from sage_patch.patches.multi_select_group import MultiSelectGroupPatch
from sage_patch.patches.objectives_screen import ObjectivesScreenPatch
from sage_patch.patches.player_heal_filter import PlayerHealFilterPatch
from sage_patch.patches.production_condition import ProductionConditionPatch
from sage_patch.patches.production_split import ProductionSplitPatch
from sage_patch.patches.queue_ignore_cp import QueueIgnoreCpPatch
from sage_patch.patches.replay_outcome import ReplayOutcomePatch
from sage_patch.patches.science_prereqs import SciencePrereqPatch
from sage_patch.patches.skirmish_replay import SkirmishReplayPatch
from sage_patch.patches.spawn_union import SpawnUnionPatch
from sage_patch.patches.spell_store_upgrade import SpellStoreUpgradePatch
from sage_patch.patches.terrain_resource_exp import TerrainResourceExpPatch
from sage_patch.patches.trigger_recharge_list import TriggerRechargeListPatch
from sage_patch.patches.unique_production_id import UniqueProductionIdPatch
from sage_patch.patches.upgrade_description import UpgradeDescriptionPatch
from sage_patch.patches.upgrade_grant_lists import UpgradeGrantListsPatch

__all__ = [
    "AiCommandNullTargetPatch",
    "AiConstructionGatePatch",
    "AiFlagCaptureGatePatch",
    "AiReviveGatePatch",
    "AutoDepositInflationPatch",
    "BannerFilterPatch",
    "CahFactionsPatch",
    "CommandPointCostPatch",
    "CommandPointUpkeepPatch",
    "CommandSetLimitPatch",
    "DesertWeatherPatch",
    "DesertWeatherWorldbuilderPatch",
    "FireAtAttackerPatch",
    "FoundationRebindPatch",
    "GiveUpgradeAllPatch",
    "HeadlessPatch",
    "HealingReceivedPatch",
    "HeroBarSlotsPatch",
    "HeroManaPatch",
    "HordeOrphanTargetPatch",
    "InflationReadoutPatch",
    "LargeGroupBonusPatch",
    "LifetimeFieldsPatch",
    "LiveBridgePatch",
    "LivingWorldOverridePatch",
    "MaintenanceCostPatch",
    "MultiExecuteGatePatch",
    "MultiSelectGroupPatch",
    "ObjectivesScreenPatch",
    "ObjectImageUpgradePatch",
    "ObjectImageUpgradeWorldbuilderPatch",
    "PlayerHealFilterPatch",
    "ProductionConditionPatch",
    "ProductionSplitPatch",
    "QueueIgnoreCpPatch",
    "RechargeRescalePatch",
    "ReplayOutcomePatch",
    "SciencePrereqPatch",
    "SecondResourcePatch",
    "SkirmishReplayPatch",
    "SmartRallyPatch",
    "SpawnUnionPatch",
    "SpellStoreUpgradePatch",
    "TerrainResourceExpPatch",
    "TriggerRechargeListPatch",
    "UniqueProductionIdPatch",
    "UnitPlateOptionPatch",
    "UpgradeDescriptionPatch",
    "UpgradeGrantListsPatch",
]
