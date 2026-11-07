"""Concrete `Patch` implementations."""

from sage_patch.patches.ai.ai_build_queue_skip import AiBuildQueueSkipPatch
from sage_patch.patches.ai.ai_construction_gate import AiConstructionGatePatch
from sage_patch.patches.ai.ai_equivalent_build_gate import AiEquivalentBuildGatePatch
from sage_patch.patches.ai.ai_farm_kill_gate import AiFarmKillGatePatch
from sage_patch.patches.ai.ai_flag_capture_gate import AiFlagCaptureGatePatch
from sage_patch.patches.ai.ai_revive_gate import AiReviveGatePatch
from sage_patch.patches.ai.ai_team_size import AiTeamSizePatch
from sage_patch.patches.ai.player_ai_type_reset import PlayerAiTypeResetPatch
from sage_patch.patches.campaign.summon_carryover import SummonCarryoverPatch
from sage_patch.patches.campaign.wotr_battle_observers import WotrBattleObserversPatch
from sage_patch.patches.campaign.wotr_lobby_slots import WotrLobbySlotsPatch
from sage_patch.patches.combat.damage_subtypes import (
    DamageSubtypesPatch,
    DamageSubtypesWorldbuilderPatch,
)
from sage_patch.patches.combat.experience_award import ExperienceAwardPatch
from sage_patch.patches.combat.experience_level_down import (
    ExperienceLevelDownPatch,
)
from sage_patch.patches.combat.fire_at_attacker import FireAtAttackerPatch
from sage_patch.patches.combat.healing_received import HealingReceivedPatch
from sage_patch.patches.combat.player_heal_filter import PlayerHealFilterPatch
from sage_patch.patches.combat.share_experience_all import ShareExperienceAllPatch
from sage_patch.patches.commandbar.commandset import CommandSetLimitPatch
from sage_patch.patches.commandbar.multi_select_group import MultiSelectGroupPatch
from sage_patch.patches.commandbar.revive_object_binding import ReviveObjectBindingPatch
from sage_patch.patches.commandbar.spell_store_upgrade import SpellStoreUpgradePatch
from sage_patch.patches.commandbar.spellbook_commandset_refresh import (
    SpellbookCommandSetRefreshPatch,
)
from sage_patch.patches.diagnostics.live_bridge import LiveBridgePatch
from sage_patch.patches.economy.auto_deposit_inflation import AutoDepositInflationPatch
from sage_patch.patches.economy.command_point_cost import CommandPointCostPatch
from sage_patch.patches.economy.command_point_upkeep import CommandPointUpkeepPatch
from sage_patch.patches.economy.cost_modifier_upgrade_groups import (
    CostModifierUpgradeGroupsPatch,
    CostModifierUpgradeGroupsWorldbuilderPatch,
)
from sage_patch.patches.economy.maintenance_cost import MaintenanceCostPatch
from sage_patch.patches.economy.player_upgrade_discount import PlayerUpgradeDiscountPatch
from sage_patch.patches.economy.production_condition import ProductionConditionPatch
from sage_patch.patches.economy.production_split import ProductionSplitPatch
from sage_patch.patches.economy.queue_ignore_cp import QueueIgnoreCpPatch
from sage_patch.patches.economy.terrain_resource_exp import TerrainResourceExpPatch
from sage_patch.patches.economy.unique_production_id import UniqueProductionIdPatch
from sage_patch.patches.experimental.foggy_weather import (
    FoggyWeatherPatch,
    FoggyWeatherWorldbuilderPatch,
)
from sage_patch.patches.experimental.hero_mana import HeroManaPatch
from sage_patch.patches.experimental.horde_orphan_target import HordeOrphanTargetPatch
from sage_patch.patches.experimental.living_world_override import LivingWorldOverridePatch
from sage_patch.patches.experimental.map_transition import MapTransitionPatch
from sage_patch.patches.experimental.second_resource import SecondResourcePatch
from sage_patch.patches.experimental.smart_rally import SmartRallyPatch
from sage_patch.patches.experimental.special_power_music import SpecialPowerMusicPatch
from sage_patch.patches.experimental.spellbook_hotkeys import SpellbookHotkeysPatch
from sage_patch.patches.experimental.unit_plate_option import UnitPlateOptionPatch
from sage_patch.patches.multiplayer.cah_factions import (
    CahFactionsPatch,
    CahFactionsWorldbuilderPatch,
)
from sage_patch.patches.multiplayer.faction_variants import FactionVariantsPatch
from sage_patch.patches.multiplayer.map_list_symbols import MapListSymbolsPatch
from sage_patch.patches.multiplayer.replay_outcome import ReplayOutcomePatch
from sage_patch.patches.multiplayer.skirmish_replay import SkirmishReplayPatch
from sage_patch.patches.platform.headless import HeadlessPatch
from sage_patch.patches.platform.null_guards import NullGuardsPatch
from sage_patch.patches.platform.os_name_fallback import OsNameFallbackPatch
from sage_patch.patches.platform.save_temp_file import SaveTempFilePatch
from sage_patch.patches.platform.score_keeper_dangling_keys import ScoreKeeperDanglingKeysPatch
from sage_patch.patches.render.ash_weather import (
    AshWeatherPatch,
    AshWeatherWorldbuilderPatch,
)
from sage_patch.patches.render.desert_weather import (
    DesertWeatherPatch,
    DesertWeatherWorldbuilderPatch,
)
from sage_patch.patches.render.hide_modifier_fx import HideModifierFxPatch
from sage_patch.patches.special_powers.level_grant_special_power import (
    LevelGrantSpecialPowerPatch,
)
from sage_patch.patches.special_powers.multi_execute_gate import MultiExecuteGatePatch
from sage_patch.patches.special_powers.recharge_rescale import RechargeRescalePatch
from sage_patch.patches.special_powers.special_power_object_cap import SpecialPowerObjectCapPatch
from sage_patch.patches.special_powers.special_power_palantir_movie import (
    SpecialPowerPalantirMoviePatch,
)
from sage_patch.patches.special_powers.special_power_pause_button import (
    SpecialPowerPauseButtonPatch,
)
from sage_patch.patches.special_powers.special_power_refund_upgrade import (
    SpecialPowerRefundUpgradePatch,
    SpecialPowerRefundUpgradeWorldbuilderPatch,
)
from sage_patch.patches.special_powers.spell_recharge_targets import SpellRechargeTargetsPatch
from sage_patch.patches.special_powers.trigger_recharge_list import TriggerRechargeListPatch
from sage_patch.patches.structures.castle_unpack_clearance import CastleUnpackClearancePatch
from sage_patch.patches.structures.construction_initial_health import ConstructionInitialHealthPatch
from sage_patch.patches.structures.foundation_rebind import FoundationRebindPatch
from sage_patch.patches.structures.repair_damage_cancel import RepairDamageCancelPatch
from sage_patch.patches.structures.replace_self_rubble import ReplaceSelfRubblePatch
from sage_patch.patches.ui.hero_bar_slots import HeroBarSlotsPatch
from sage_patch.patches.ui.inflation_readout import InflationReadoutPatch
from sage_patch.patches.ui.object_image_upgrade import (
    ObjectImageUpgradePatch,
    ObjectImageUpgradeWorldbuilderPatch,
)
from sage_patch.patches.ui.objectives_screen import ObjectivesScreenPatch
from sage_patch.patches.ui.radar_structure_discs import RadarStructureDiscsPatch
from sage_patch.patches.ui.text_entry_clipboard import TextEntryClipboardPatch
from sage_patch.patches.ui.upgrade_description import UpgradeDescriptionPatch
from sage_patch.patches.units.banner_filter import BannerFilterPatch
from sage_patch.patches.units.large_group_bonus import LargeGroupBonusPatch
from sage_patch.patches.units.mount_health_ratio import MountHealthRatioPatch
from sage_patch.patches.units.mount_swap_eject import MountSwapEjectPatch
from sage_patch.patches.units.multi_contain import MultiContainPatch
from sage_patch.patches.units.pickup_stuff_enter import PickupStuffEnterPatch
from sage_patch.patches.units.pillage_module_extension import PillageModuleExtensionPatch
from sage_patch.patches.units.slaved_update_idle import SlavedUpdateIdlePatch
from sage_patch.patches.units.spawn_union import SpawnUnionPatch
from sage_patch.patches.upgrades.give_upgrade_all import GiveUpgradeAllPatch
from sage_patch.patches.upgrades.grant_science_upgrade import (
    GrantScienceUpgradePatch,
    GrantScienceUpgradeWorldbuilderPatch,
)
from sage_patch.patches.upgrades.lifetime_fields import LifetimeFieldsPatch
from sage_patch.patches.upgrades.science_prereqs import SciencePrereqPatch
from sage_patch.patches.upgrades.upgrade_alias import UpgradeAliasPatch
from sage_patch.patches.upgrades.upgrade_grant_lists import UpgradeGrantListsPatch
from sage_patch.patches.upgrades.upgrade_module_conflicts import UpgradeModuleConflictsPatch
from sage_patch.patches.upgrades.upgrade_module_removal import UpgradeModuleRemovalPatch

__all__ = [
    "CostModifierUpgradeGroupsPatch",
    "CostModifierUpgradeGroupsWorldbuilderPatch",
    "UpgradeModuleConflictsPatch",
    "SlavedUpdateIdlePatch",
    "TextEntryClipboardPatch",
    "AiBuildQueueSkipPatch",
    "AiConstructionGatePatch",
    "AiEquivalentBuildGatePatch",
    "AiFarmKillGatePatch",
    "AiFlagCaptureGatePatch",
    "AiReviveGatePatch",
    "AiTeamSizePatch",
    "AshWeatherPatch",
    "AshWeatherWorldbuilderPatch",
    "AutoDepositInflationPatch",
    "BannerFilterPatch",
    "CahFactionsPatch",
    "CahFactionsWorldbuilderPatch",
    "CastleUnpackClearancePatch",
    "CommandPointCostPatch",
    "CommandPointUpkeepPatch",
    "CommandSetLimitPatch",
    "ConstructionInitialHealthPatch",
    "DamageSubtypesPatch",
    "DamageSubtypesWorldbuilderPatch",
    "DesertWeatherPatch",
    "DesertWeatherWorldbuilderPatch",
    "FactionVariantsPatch",
    "ExperienceLevelDownPatch",
    "UpgradeModuleRemovalPatch",
    "SpecialPowerObjectCapPatch",
    "SpecialPowerPalantirMoviePatch",
    "SpecialPowerPauseButtonPatch",
    "FireAtAttackerPatch",
    "FoundationRebindPatch",
    "FoggyWeatherPatch",
    "FoggyWeatherWorldbuilderPatch",
    "GiveUpgradeAllPatch",
    "GrantScienceUpgradePatch",
    "GrantScienceUpgradeWorldbuilderPatch",
    "HeadlessPatch",
    "HealingReceivedPatch",
    "ExperienceAwardPatch",
    "HideModifierFxPatch",
    "HeroBarSlotsPatch",
    "HeroManaPatch",
    "SpecialPowerMusicPatch",
    "HordeOrphanTargetPatch",
    "InflationReadoutPatch",
    "LargeGroupBonusPatch",
    "PickupStuffEnterPatch",
    "PillageModuleExtensionPatch",
    "LevelGrantSpecialPowerPatch",
    "LifetimeFieldsPatch",
    "LiveBridgePatch",
    "MapTransitionPatch",
    "LivingWorldOverridePatch",
    "MaintenanceCostPatch",
    "MapListSymbolsPatch",
    "MountHealthRatioPatch",
    "MountSwapEjectPatch",
    "MultiContainPatch",
    "MultiExecuteGatePatch",
    "MultiSelectGroupPatch",
    "NullGuardsPatch",
    "ObjectivesScreenPatch",
    "OsNameFallbackPatch",
    "ObjectImageUpgradePatch",
    "ObjectImageUpgradeWorldbuilderPatch",
    "PlayerAiTypeResetPatch",
    "PlayerHealFilterPatch",
    "PlayerUpgradeDiscountPatch",
    "ProductionConditionPatch",
    "ProductionSplitPatch",
    "QueueIgnoreCpPatch",
    "RadarStructureDiscsPatch",
    "RepairDamageCancelPatch",
    "RechargeRescalePatch",
    "ReplaceSelfRubblePatch",
    "ReplayOutcomePatch",
    "ReviveObjectBindingPatch",
    "SaveTempFilePatch",
    "SciencePrereqPatch",
    "ScoreKeeperDanglingKeysPatch",
    "SecondResourcePatch",
    "ShareExperienceAllPatch",
    "SkirmishReplayPatch",
    "SmartRallyPatch",
    "SpawnUnionPatch",
    "SpecialPowerRefundUpgradePatch",
    "SpecialPowerRefundUpgradeWorldbuilderPatch",
    "SpellStoreUpgradePatch",
    "SpellRechargeTargetsPatch",
    "SpellbookCommandSetRefreshPatch",
    "SpellbookHotkeysPatch",
    "SummonCarryoverPatch",
    "TerrainResourceExpPatch",
    "TriggerRechargeListPatch",
    "UniqueProductionIdPatch",
    "UnitPlateOptionPatch",
    "UpgradeDescriptionPatch",
    "UpgradeAliasPatch",
    "UpgradeGrantListsPatch",
    "WotrBattleObserversPatch",
    "WotrLobbySlotsPatch",
]
