"""Concrete :class:`~sage_patch.patcher.Patch` implementations."""

from sage_patch.patches.ai_construction_gate import AiConstructionGatePatch
from sage_patch.patches.ai_revive_gate import AiReviveGatePatch
from sage_patch.patches.banner_filter import BannerFilterPatch
from sage_patch.patches.cah_factions import CahFactionsPatch
from sage_patch.patches.command_point_upkeep import CommandPointUpkeepPatch
from sage_patch.patches.commandset import CommandSetLimitPatch
from sage_patch.patches.desert_weather import DesertWeatherPatch
from sage_patch.patches.desert_weather_wb import DesertWeatherWorldbuilderPatch
from sage_patch.patches.experimental.headless import HeadlessPatch
from sage_patch.patches.experimental.hero_mana import HeroManaPatch
from sage_patch.patches.experimental.horde_orphan_target import HordeOrphanTargetPatch
from sage_patch.patches.experimental.second_resource import SecondResourcePatch
from sage_patch.patches.foundation_rebind import FoundationRebindPatch
from sage_patch.patches.hero_bar_slots import HeroBarSlotsPatch
from sage_patch.patches.inflation_readout import InflationReadoutPatch
from sage_patch.patches.large_group_bonus_filter import LargeGroupBonusFilterPatch
from sage_patch.patches.lifetime_extend_upgrade import LifetimeExtendUpgradePatch
from sage_patch.patches.live_bridge import LiveBridgePatch
from sage_patch.patches.living_world_override import LivingWorldOverridePatch
from sage_patch.patches.multi_execute_gate import MultiExecuteGatePatch
from sage_patch.patches.objectives_screen import ObjectivesScreenPatch
from sage_patch.patches.player_heal_filter import PlayerHealFilterPatch
from sage_patch.patches.production_condition import ProductionConditionPatch
from sage_patch.patches.production_split import ProductionSplitPatch
from sage_patch.patches.queue_ignore_cp import QueueIgnoreCpPatch
from sage_patch.patches.replay_outcome import ReplayOutcomePatch
from sage_patch.patches.science_prereqs import SciencePrereqPatch
from sage_patch.patches.skirmish_replay import SkirmishReplayPatch
from sage_patch.patches.spawn_union import SpawnUnionPatch
from sage_patch.patches.terrain_resource_exp import TerrainResourceExpPatch
from sage_patch.patches.unique_production_id import UniqueProductionIdPatch
from sage_patch.patches.upgrade_description import UpgradeDescriptionPatch

__all__ = [
    "AiConstructionGatePatch",
    "AiReviveGatePatch",
    "BannerFilterPatch",
    "CahFactionsPatch",
    "CommandPointUpkeepPatch",
    "CommandSetLimitPatch",
    "DesertWeatherPatch",
    "DesertWeatherWorldbuilderPatch",
    "FoundationRebindPatch",
    "HeadlessPatch",
    "HeroBarSlotsPatch",
    "HeroManaPatch",
    "HordeOrphanTargetPatch",
    "InflationReadoutPatch",
    "LargeGroupBonusFilterPatch",
    "LifetimeExtendUpgradePatch",
    "LiveBridgePatch",
    "LivingWorldOverridePatch",
    "MultiExecuteGatePatch",
    "ObjectivesScreenPatch",
    "PlayerHealFilterPatch",
    "ProductionConditionPatch",
    "ProductionSplitPatch",
    "QueueIgnoreCpPatch",
    "ReplayOutcomePatch",
    "SciencePrereqPatch",
    "SecondResourcePatch",
    "SkirmishReplayPatch",
    "SpawnUnionPatch",
    "TerrainResourceExpPatch",
    "UniqueProductionIdPatch",
    "UpgradeDescriptionPatch",
]
