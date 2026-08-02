"""Registry of installable patches, keyed by :attr:`Patch.name`, that the ``sage-patch`` CLI
lists, applies and verifies. Add a patch here to expose it on the command line."""

from sage_patch.patcher import Patch
from sage_patch.patches.ai_revive_gate import AiReviveGatePatch
from sage_patch.patches.cah_factions import CahFactionsPatch
from sage_patch.patches.command_point_upkeep import CommandPointUpkeepPatch
from sage_patch.patches.commandset import CommandSetLimitPatch
from sage_patch.patches.desert_weather import DesertWeatherPatch
from sage_patch.patches.desert_weather_wb import DesertWeatherWorldbuilderPatch
from sage_patch.patches.hero_mana import HeroManaPatch
from sage_patch.patches.live_bridge import LiveBridgePatch
from sage_patch.patches.production_condition import ProductionConditionPatch
from sage_patch.patches.replay_outcome import ReplayOutcomePatch
from sage_patch.patches.skirmish_replay import SkirmishReplayPatch
from sage_patch.patches.terrain_resource_exp import TerrainResourceExpPatch
from sage_patch.patches.unique_production_id import UniqueProductionIdPatch

PATCHES: dict[str, type[Patch]] = {
    CommandSetLimitPatch.name: CommandSetLimitPatch,
    CahFactionsPatch.name: CahFactionsPatch,
    AiReviveGatePatch.name: AiReviveGatePatch,
    ProductionConditionPatch.name: ProductionConditionPatch,
    DesertWeatherPatch.name: DesertWeatherPatch,
    DesertWeatherWorldbuilderPatch.name: DesertWeatherWorldbuilderPatch,
    UniqueProductionIdPatch.name: UniqueProductionIdPatch,
    ReplayOutcomePatch.name: ReplayOutcomePatch,
    SkirmishReplayPatch.name: SkirmishReplayPatch,
    LiveBridgePatch.name: LiveBridgePatch,
    TerrainResourceExpPatch.name: TerrainResourceExpPatch,
    HeroManaPatch.name: HeroManaPatch,
    CommandPointUpkeepPatch.name: CommandPointUpkeepPatch,
}

__all__ = ["PATCHES"]
