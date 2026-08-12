"""Registry of installable patches, keyed by :attr:`Patch.name`, that the ``sage-patch`` CLI
lists, applies and verifies. Add a patch here to expose it on the command line."""

from sage_patch.patcher import Patch
from sage_patch.patches.ai_construction_gate import AiConstructionGatePatch
from sage_patch.patches.ai_revive_gate import AiReviveGatePatch
from sage_patch.patches.banner_filter import BannerFilterPatch
from sage_patch.patches.cah_factions import CahFactionsPatch
from sage_patch.patches.campaign_select import CampaignSelectPatch
from sage_patch.patches.command_point_upkeep import CommandPointUpkeepPatch
from sage_patch.patches.commandset import CommandSetLimitPatch
from sage_patch.patches.desert_weather import DesertWeatherPatch
from sage_patch.patches.desert_weather_wb import DesertWeatherWorldbuilderPatch
from sage_patch.patches.foundation_rebind import FoundationRebindPatch
from sage_patch.patches.headless import HeadlessPatch
from sage_patch.patches.hero_bar_slots import HeroBarSlotsPatch
from sage_patch.patches.hero_mana import HeroManaPatch
from sage_patch.patches.herobar import HeroBarPatch
from sage_patch.patches.inflation_readout import InflationReadoutPatch
from sage_patch.patches.live_bridge import LiveBridgePatch
from sage_patch.patches.living_world_override import LivingWorldOverridePatch
from sage_patch.patches.multi_execute_gate import MultiExecuteGatePatch
from sage_patch.patches.multi_instance import MultiInstanceLauncherPatch, MultiInstancePatch
from sage_patch.patches.objectives_screen import ObjectivesScreenPatch
from sage_patch.patches.observer_switch import ObserverSwitchPatch
from sage_patch.patches.production_condition import ProductionConditionPatch
from sage_patch.patches.queue_ignore_cp import QueueIgnoreCpPatch
from sage_patch.patches.replay_outcome import ReplayOutcomePatch
from sage_patch.patches.science_prereqs import SciencePrereqPatch
from sage_patch.patches.second_resource import SecondResourcePatch
from sage_patch.patches.skirmish_replay import SkirmishReplayPatch
from sage_patch.patches.spawn_union import SpawnUnionPatch
from sage_patch.patches.standalone_launcher import StandaloneLauncherPatch
from sage_patch.patches.terrain_resource_exp import TerrainResourceExpPatch
from sage_patch.patches.unique_production_id import UniqueProductionIdPatch

# `horde-orphan-target` is deliberately absent: it applies and verifies cleanly but does not
# fix the fault it was written for, so it must not be offered on the CLI as though it did.
PATCHES: dict[str, type[Patch]] = {
    CommandSetLimitPatch.name: CommandSetLimitPatch,
    CahFactionsPatch.name: CahFactionsPatch,
    AiReviveGatePatch.name: AiReviveGatePatch,
    AiConstructionGatePatch.name: AiConstructionGatePatch,
    ProductionConditionPatch.name: ProductionConditionPatch,
    DesertWeatherPatch.name: DesertWeatherPatch,
    DesertWeatherWorldbuilderPatch.name: DesertWeatherWorldbuilderPatch,
    UniqueProductionIdPatch.name: UniqueProductionIdPatch,
    ReplayOutcomePatch.name: ReplayOutcomePatch,
    SkirmishReplayPatch.name: SkirmishReplayPatch,
    ObjectivesScreenPatch.name: ObjectivesScreenPatch,
    ObserverSwitchPatch.name: ObserverSwitchPatch,
    LiveBridgePatch.name: LiveBridgePatch,
    LivingWorldOverridePatch.name: LivingWorldOverridePatch,
    TerrainResourceExpPatch.name: TerrainResourceExpPatch,
    HeroManaPatch.name: HeroManaPatch,
    CommandPointUpkeepPatch.name: CommandPointUpkeepPatch,
    BannerFilterPatch.name: BannerFilterPatch,
    SecondResourcePatch.name: SecondResourcePatch,
    InflationReadoutPatch.name: InflationReadoutPatch,
    SciencePrereqPatch.name: SciencePrereqPatch,
    HeroBarPatch.name: HeroBarPatch,
    HeroBarSlotsPatch.name: HeroBarSlotsPatch,
    MultiExecuteGatePatch.name: MultiExecuteGatePatch,
    SpawnUnionPatch.name: SpawnUnionPatch,
    QueueIgnoreCpPatch.name: QueueIgnoreCpPatch,
    MultiInstancePatch.name: MultiInstancePatch,
    MultiInstanceLauncherPatch.name: MultiInstanceLauncherPatch,
    StandaloneLauncherPatch.name: StandaloneLauncherPatch,
    CampaignSelectPatch.name: CampaignSelectPatch,
    FoundationRebindPatch.name: FoundationRebindPatch,
    HeadlessPatch.name: HeadlessPatch,
}

__all__ = ["PATCHES"]
