"""Concrete :class:`~sage_patch.patcher.Patch` implementations."""

from sage_patch.patches.ai_revive_gate import AiReviveGatePatch
from sage_patch.patches.cah_factions import CahFactionsPatch
from sage_patch.patches.commandset import CommandSetLimitPatch
from sage_patch.patches.desert_weather import DesertWeatherPatch
from sage_patch.patches.desert_weather_wb import DesertWeatherWorldbuilderPatch
from sage_patch.patches.live_bridge import LiveBridgePatch
from sage_patch.patches.production_condition import ProductionConditionPatch
from sage_patch.patches.replay_outcome import ReplayOutcomePatch
from sage_patch.patches.skirmish_replay import SkirmishReplayPatch
from sage_patch.patches.unique_production_id import UniqueProductionIdPatch

__all__ = [
    "AiReviveGatePatch",
    "CahFactionsPatch",
    "CommandSetLimitPatch",
    "DesertWeatherPatch",
    "DesertWeatherWorldbuilderPatch",
    "LiveBridgePatch",
    "ProductionConditionPatch",
    "ReplayOutcomePatch",
    "SkirmishReplayPatch",
    "UniqueProductionIdPatch",
]
