"""Registry of installable patches, keyed by `Patch.name`, that the `sage-patch` CLI
lists, applies and verifies. Add a patch here to expose it on the command line.

Patches imported from `sage_patch.patches.experimental` are **unstable and largely untested**
and set `Patch.experimental`, which is what makes `list` mark them and `apply` warn. They are
registered rather than hidden on purpose - a patch nobody can run is a patch nobody can find the
problem in, and the warning is the thing that makes offering it honest.

That attribute is also what orders them: the settled patches come first and the experimental ones
after, each block alphabetical (see `_order`). Everything that walks the registry inherits
it, so a patch is added to `_REGISTERED` wherever its import goes and lands in the right
place in every list on its own."""

from sage_patch.patcher import Patch
from sage_patch.patches.ai.ai_ally_targets import (
    AiAllyTargetsPatch,
    AiAllyTargetsWorldbuilderPatch,
)
from sage_patch.patches.ai.ai_build_queue_skip import AiBuildQueueSkipPatch
from sage_patch.patches.ai.ai_construction_gate import AiConstructionGatePatch
from sage_patch.patches.ai.ai_disabled_regions import AiDisabledRegionsPatch
from sage_patch.patches.ai.ai_equivalent_build_gate import AiEquivalentBuildGatePatch
from sage_patch.patches.ai.ai_farm_kill_gate import AiFarmKillGatePatch
from sage_patch.patches.ai.ai_flag_capture_gate import AiFlagCaptureGatePatch
from sage_patch.patches.ai.ai_hero_build_delay import AiHeroBuildDelayPatch
from sage_patch.patches.ai.ai_plot_autobuild import AiPlotAutobuildPatch
from sage_patch.patches.ai.ai_rebuild_gate import AiRebuildGatePatch
from sage_patch.patches.ai.ai_revive_gate import AiReviveGatePatch
from sage_patch.patches.ai.ai_team_size import AiTeamSizePatch
from sage_patch.patches.ai.ai_tunnel_routing import AiTunnelRoutingPatch
from sage_patch.patches.ai.player_ai_type_reset import PlayerAiTypeResetPatch
from sage_patch.patches.ai.skirmish_ai_fallback import SkirmishAiFallbackPatch
from sage_patch.patches.campaign.call_in_reinforcements import CallInReinforcementsPatch
from sage_patch.patches.campaign.campaign_army_verbs import CampaignArmyVerbsPatch
from sage_patch.patches.campaign.hero_army_carryover import HeroArmyCarryoverPatch
from sage_patch.patches.campaign.scenario_player_factions import ScenarioPlayerFactionsPatch
from sage_patch.patches.campaign.summon_carryover import SummonCarryoverPatch
from sage_patch.patches.campaign.wotr_battle_hero_pool import WotrBattleHeroPoolPatch
from sage_patch.patches.campaign.wotr_battle_observers import WotrBattleObserversPatch
from sage_patch.patches.campaign.wotr_lobby_slots import WotrLobbySlotsPatch
from sage_patch.patches.combat.attack_requires_damage import AttackRequiresDamagePatch
from sage_patch.patches.combat.attribute_modifier_aura_conflicts import (
    AttributeModifierAuraConflictsPatch,
)
from sage_patch.patches.combat.damage_subtypes import (
    DamageSubtypesPatch,
    DamageSubtypesWorldbuilderPatch,
)
from sage_patch.patches.combat.deploy_before_attack import DeployBeforeAttackPatch
from sage_patch.patches.combat.drain_life_fix import DrainLifeFixPatch
from sage_patch.patches.combat.experience_award import (
    ExperienceAwardPatch,
    ExperienceAwardWorldbuilderPatch,
)
from sage_patch.patches.combat.experience_level_down import (
    ExperienceLevelDownPatch,
)
from sage_patch.patches.combat.fire_at_attacker import FireAtAttackerPatch
from sage_patch.patches.combat.healing_received import (
    HealingReceivedPatch,
    HealingReceivedWorldbuilderPatch,
)
from sage_patch.patches.combat.passive_aura_revive import PassiveAuraRevivePatch
from sage_patch.patches.combat.player_heal_filter import PlayerHealFilterPatch
from sage_patch.patches.combat.share_experience_all import ShareExperienceAllPatch
from sage_patch.patches.commandbar.commandset import CommandSetLimitPatch
from sage_patch.patches.commandbar.commandset_button_upgrade import CommandSetButtonUpgradePatch
from sage_patch.patches.commandbar.multi_select_group import MultiSelectGroupPatch
from sage_patch.patches.commandbar.revive_object_binding import ReviveObjectBindingPatch
from sage_patch.patches.commandbar.spell_store_deferral import SpellStoreDeferralPatch
from sage_patch.patches.commandbar.spell_store_upgrade import SpellStoreUpgradePatch
from sage_patch.patches.commandbar.spellbook_commandset_refresh import (
    SpellbookCommandSetRefreshPatch,
)
from sage_patch.patches.commandbar.visible_hotkeys import VisibleHotkeysPatch
from sage_patch.patches.diagnostics.asset_load_profile import AssetLoadProfilePatch
from sage_patch.patches.diagnostics.crash_dump import CrashDumpPatch
from sage_patch.patches.diagnostics.desync_debug import DesyncDebugPatch
from sage_patch.patches.diagnostics.live_bridge import LiveBridgePatch
from sage_patch.patches.diagnostics.perf_scope_skip import PerfScopeSkipPatch
from sage_patch.patches.diagnostics.perf_stage_readout import PerfStageReadoutPatch
from sage_patch.patches.diagnostics.quiet_exit import QuietExitPatch
from sage_patch.patches.diagnostics.script_debug_window import ScriptDebugWindowPatch
from sage_patch.patches.economy.auto_deposit_inflation import AutoDepositInflationPatch
from sage_patch.patches.economy.combo_horde_recruitment import ComboHordeRecruitmentPatch
from sage_patch.patches.economy.command_point_cost import CommandPointCostPatch
from sage_patch.patches.economy.command_point_override import CommandPointOverridePatch
from sage_patch.patches.economy.command_point_upkeep import CommandPointUpkeepPatch
from sage_patch.patches.economy.hero_recruit_parallel import HeroRecruitParallelPatch
from sage_patch.patches.economy.horde_exit_absorption import HordeExitAbsorptionPatch
from sage_patch.patches.economy.maintenance_cost import MaintenanceCostPatch
from sage_patch.patches.economy.player_upgrade_discount import PlayerUpgradeDiscountPatch
from sage_patch.patches.economy.production_condition import (
    ProductionConditionPatch,
    ProductionConditionWorldbuilderPatch,
)
from sage_patch.patches.economy.production_death_no_refund import ProductionDeathNoRefundPatch
from sage_patch.patches.economy.production_split import (
    ProductionSplitPatch,
    ProductionSplitWorldbuilderPatch,
)
from sage_patch.patches.economy.queue_ignore_cp import QueueIgnoreCpPatch
from sage_patch.patches.economy.terrain_resource_exp import TerrainResourceExpPatch
from sage_patch.patches.economy.unique_production_id import UniqueProductionIdPatch
from sage_patch.patches.experimental.ai_power_model_condition import AiPowerModelConditionPatch
from sage_patch.patches.experimental.battle_school import BattleSchoolPatch
from sage_patch.patches.experimental.campaign_select import CampaignSelectPatch
from sage_patch.patches.experimental.capture_the_flag import CaptureTheFlagPatch
from sage_patch.patches.experimental.castle_prefab import (
    CastlePrefabCommandButtonPatch,
    CastlePrefabPatch,
    CastlePrefabWorldbuilderPatch,
)
from sage_patch.patches.experimental.command_range_flyout import CommandRangeFlyoutPatch
from sage_patch.patches.experimental.cooldown_through_death import CooldownThroughDeathPatch
from sage_patch.patches.experimental.foggy_weather import (
    FoggyWeatherPatch,
    FoggyWeatherWorldbuilderPatch,
)
from sage_patch.patches.experimental.hero_horde_death import HeroHordeDeathPatch
from sage_patch.patches.experimental.hero_mana import HeroManaPatch
from sage_patch.patches.experimental.hide_selection_details import HideSelectionDetailsPatch
from sage_patch.patches.experimental.living_world_override import LivingWorldOverridePatch
from sage_patch.patches.experimental.map_transition import MapTransitionPatch
from sage_patch.patches.experimental.observer_all_commands import ObserverAllCommandsPatch
from sage_patch.patches.experimental.ranged_stand_off import RangedStandOffPatch
from sage_patch.patches.experimental.second_resource import SecondResourcePatch
from sage_patch.patches.experimental.shared_control_on_leave import SharedControlOnLeavePatch
from sage_patch.patches.experimental.smart_rally import SmartRallyPatch
from sage_patch.patches.experimental.special_power_charges import SpecialPowerChargesPatch
from sage_patch.patches.experimental.special_power_music import SpecialPowerMusicPatch
from sage_patch.patches.experimental.spellbook_hotkeys import SpellbookHotkeysPatch
from sage_patch.patches.experimental.unit_plate_option import UnitPlateOptionPatch
from sage_patch.patches.multiplayer.better_hud_toggle import BetterHudTogglePatch
from sage_patch.patches.multiplayer.binary_attest import BinaryAttestPatch
from sage_patch.patches.multiplayer.cah_factions import (
    CahFactionsPatch,
    CahFactionsWorldbuilderPatch,
)
from sage_patch.patches.multiplayer.command_point_modes import CommandPointModesPatch
from sage_patch.patches.multiplayer.faction_variants import FactionVariantsPatch
from sage_patch.patches.multiplayer.lan_join_bystanders import LanJoinBystandersPatch
from sage_patch.patches.multiplayer.lobby_faction_byte import LobbyFactionBytePatch
from sage_patch.patches.multiplayer.map_list_symbols import MapListSymbolsPatch
from sage_patch.patches.multiplayer.observer_command_range import ObserverCommandRangePatch
from sage_patch.patches.multiplayer.observer_switch import ObserverSwitchPatch
from sage_patch.patches.multiplayer.replay_annotations import ReplayAnnotationsPatch
from sage_patch.patches.multiplayer.replay_outcome import ReplayOutcomePatch
from sage_patch.patches.multiplayer.skirmish_replay import SkirmishReplayPatch
from sage_patch.patches.platform.accel_module import AccelModulePatch
from sage_patch.patches.platform.command_line_skirmish import CommandLineSkirmishPatch
from sage_patch.patches.platform.dll_import import DllImportPatch
from sage_patch.patches.platform.dll_load import DllLoadPatch
from sage_patch.patches.platform.headless import HeadlessPatch
from sage_patch.patches.platform.mod_load_order import ModLoadOrderPatch
from sage_patch.patches.platform.multi_instance import (
    MultiInstanceLauncherPatch,
    MultiInstancePatch,
)
from sage_patch.patches.platform.multi_mod import MultiModPatch
from sage_patch.patches.platform.null_guards import NullGuardsPatch
from sage_patch.patches.platform.os_name_fallback import OsNameFallbackPatch
from sage_patch.patches.platform.save_temp_file import SaveTempFilePatch
from sage_patch.patches.platform.score_keeper_dangling_keys import ScoreKeeperDanglingKeysPatch
from sage_patch.patches.platform.standalone_launcher import StandaloneLauncherPatch
from sage_patch.patches.platform.texture_any_extension import TextureAnyExtensionPatch
from sage_patch.patches.render.desert_weather import (
    DesertWeatherPatch,
    DesertWeatherWorldbuilderPatch,
)
from sage_patch.patches.render.draw_module_scale import DrawModuleScalePatch
from sage_patch.patches.render.hide_modifier_fx import HideModifierFxPatch
from sage_patch.patches.render.infantry_lighting import InfantryLightingPatch
from sage_patch.patches.render.interpolation_alpha import InterpolationAlphaPatch
from sage_patch.patches.render.render_only_frames import RenderOnlyFramesPatch
from sage_patch.patches.render.render_rate import RenderRatePatch
from sage_patch.patches.special_powers.level_grant_special_power import (
    LevelGrantSpecialPowerPatch,
)
from sage_patch.patches.special_powers.multi_execute_cooldown import MultiExecuteCooldownPatch
from sage_patch.patches.special_powers.multi_execute_gate import MultiExecuteGatePatch
from sage_patch.patches.special_powers.recharge_rescale import RechargeRescalePatch
from sage_patch.patches.special_powers.special_power_object_cap import SpecialPowerObjectCapPatch
from sage_patch.patches.special_powers.special_power_pause_button import (
    SpecialPowerPauseButtonPatch,
)
from sage_patch.patches.special_powers.special_power_refund_upgrade import (
    SpecialPowerRefundUpgradePatch,
    SpecialPowerRefundUpgradeWorldbuilderPatch,
)
from sage_patch.patches.special_powers.special_power_upgrade_filters import (
    SpecialPowerUpgradeFiltersPatch,
)
from sage_patch.patches.special_powers.spell_recharge_reset import SpellRechargeResetPatch
from sage_patch.patches.special_powers.spell_recharge_targets import SpellRechargeTargetsPatch
from sage_patch.patches.special_powers.trigger_recharge_list import TriggerRechargeListPatch
from sage_patch.patches.structures.castle_unpack_buttons import CastleUnpackButtonsPatch
from sage_patch.patches.structures.castle_unpack_clearance import CastleUnpackClearancePatch
from sage_patch.patches.structures.construction_initial_health import ConstructionInitialHealthPatch
from sage_patch.patches.structures.foundation_rebind import FoundationRebindPatch
from sage_patch.patches.structures.rebuild_hole_repair import RebuildHoleRepairPatch
from sage_patch.patches.structures.repair_damage_cancel import RepairDamageCancelPatch
from sage_patch.patches.structures.replace_self_rubble import ReplaceSelfRubblePatch
from sage_patch.patches.structures.wall_mesh_release import WallMeshReleasePatch
from sage_patch.patches.ui.description_timers import DescriptionTimersPatch
from sage_patch.patches.ui.hero_bar_slots import HeroBarSlotsPatch
from sage_patch.patches.ui.herobar import HeroBarPatch, HeroBarWorldbuilderPatch
from sage_patch.patches.ui.horde_herobar import HordeHerobarPatch
from sage_patch.patches.ui.inflation_readout import InflationReadoutPatch
from sage_patch.patches.ui.kill_count_tooltip import KillCountTooltipPatch
from sage_patch.patches.ui.model_condition_images import ModelConditionImagesPatch
from sage_patch.patches.ui.object_image_upgrade import (
    ObjectImageUpgradePatch,
    ObjectImageUpgradeWorldbuilderPatch,
)
from sage_patch.patches.ui.objectives_screen import ObjectivesScreenPatch
from sage_patch.patches.ui.radar_structure_discs import RadarStructureDiscsPatch
from sage_patch.patches.ui.text_entry_clipboard import TextEntryClipboardPatch
from sage_patch.patches.ui.upgrade_complete_skip_unnamed import UpgradeCompleteSkipUnnamedPatch
from sage_patch.patches.ui.upgrade_description import UpgradeDescriptionPatch
from sage_patch.patches.units.banner_filter import BannerFilterPatch
from sage_patch.patches.units.banner_modifier import BannerModifierPatch
from sage_patch.patches.units.contained_horde_respawn import ContainedHordeRespawnPatch
from sage_patch.patches.units.detachable_rider_heal import DetachableRiderHealPatch
from sage_patch.patches.units.evacuate_contained_heroes import EvacuateContainedHeroesPatch
from sage_patch.patches.units.gate_close_repath import GateCloseRepathPatch
from sage_patch.patches.units.horde_member_speed import HordeMemberSpeedPatch
from sage_patch.patches.units.horde_self_experience import HordeSelfExperiencePatch
from sage_patch.patches.units.large_group_bonus import LargeGroupBonusPatch
from sage_patch.patches.units.mount_health_ratio import MountHealthRatioPatch
from sage_patch.patches.units.mount_swap_eject import MountSwapEjectPatch
from sage_patch.patches.units.multi_contain import MultiContainPatch
from sage_patch.patches.units.pickup_stuff_enter import PickupStuffEnterPatch
from sage_patch.patches.units.pillage_module_extension import PillageModuleExtensionPatch
from sage_patch.patches.units.slaved_update_idle import SlavedUpdateIdlePatch
from sage_patch.patches.units.spawn_union import SpawnUnionPatch
from sage_patch.patches.units.wall_layer_promotion import WallLayerPromotionPatch
from sage_patch.patches.upgrades.give_upgrade_all import GiveUpgradeAllPatch
from sage_patch.patches.upgrades.grant_science_upgrade import (
    GrantScienceUpgradePatch,
    GrantScienceUpgradeWorldbuilderPatch,
)
from sage_patch.patches.upgrades.lifetime_fields import LifetimeFieldsPatch
from sage_patch.patches.upgrades.replacement_transfer import ReplacementTransferPatch
from sage_patch.patches.upgrades.science_prereqs import (
    SciencePrereqPatch,
    SciencePrereqWorldbuilderPatch,
)
from sage_patch.patches.upgrades.upgrade_alias import UpgradeAliasPatch
from sage_patch.patches.upgrades.upgrade_grant_lists import UpgradeGrantListsPatch
from sage_patch.patches.upgrades.upgrade_module_removal import UpgradeModuleRemovalPatch
from sage_patch.patches.worldbuilder.worldbuilder_label_assert import WorldbuilderLabelAssertPatch
from sage_patch.patches.worldbuilder.worldbuilder_mod import WorldbuilderModPatch
from sage_patch.patches.worldbuilder.worldbuilder_object_typeahead import (
    WorldbuilderObjectTypeaheadPatch,
)
from sage_patch.patches.worldbuilder.worldbuilder_silent_errors import (
    WorldbuilderSilentErrorsPatch,
)

#: Every registered patch, in class-name order so a new one is added beside its import. This is
#: **not** the order they are presented in: `PATCHES` is built from this by sorting, and
#: every command that walks the registry - `list`, the `apply` and `verify` sub-command lists,
#: `sagepatch` - inherits that order rather than an order maintained by hand here.
_REGISTERED: tuple[type[Patch], ...] = (
    SlavedUpdateIdlePatch,
    AccelModulePatch,
    AiAllyTargetsPatch,
    AiAllyTargetsWorldbuilderPatch,
    AiBuildQueueSkipPatch,
    AiConstructionGatePatch,
    AiDisabledRegionsPatch,
    AiEquivalentBuildGatePatch,
    AiFarmKillGatePatch,
    AiFlagCaptureGatePatch,
    AiHeroBuildDelayPatch,
    AiPlotAutobuildPatch,
    AiPowerModelConditionPatch,
    AiRebuildGatePatch,
    AiReviveGatePatch,
    AiTeamSizePatch,
    AiTunnelRoutingPatch,
    AssetLoadProfilePatch,
    AttributeModifierAuraConflictsPatch,
    AttackRequiresDamagePatch,
    AutoDepositInflationPatch,
    BannerFilterPatch,
    BannerModifierPatch,
    BattleSchoolPatch,
    BetterHudTogglePatch,
    BinaryAttestPatch,
    CahFactionsPatch,
    CahFactionsWorldbuilderPatch,
    CallInReinforcementsPatch,
    CampaignArmyVerbsPatch,
    CampaignSelectPatch,
    CaptureTheFlagPatch,
    CastlePrefabCommandButtonPatch,
    CastlePrefabPatch,
    CastlePrefabWorldbuilderPatch,
    CastleUnpackButtonsPatch,
    CastleUnpackClearancePatch,
    FoggyWeatherPatch,
    FoggyWeatherWorldbuilderPatch,
    ComboHordeRecruitmentPatch,
    CommandLineSkirmishPatch,
    CommandPointCostPatch,
    CommandPointModesPatch,
    CommandPointOverridePatch,
    CommandPointUpkeepPatch,
    CommandSetButtonUpgradePatch,
    CommandSetLimitPatch,
    ConstructionInitialHealthPatch,
    CommandRangeFlyoutPatch,
    CooldownThroughDeathPatch,
    ContainedHordeRespawnPatch,
    CrashDumpPatch,
    DamageSubtypesPatch,
    DamageSubtypesWorldbuilderPatch,
    DeployBeforeAttackPatch,
    DescriptionTimersPatch,
    DesertWeatherPatch,
    DesertWeatherWorldbuilderPatch,
    DesyncDebugPatch,
    DetachableRiderHealPatch,
    DllImportPatch,
    DllLoadPatch,
    DrainLifeFixPatch,
    DrawModuleScalePatch,
    EvacuateContainedHeroesPatch,
    FactionVariantsPatch,
    ExperienceLevelDownPatch,
    UpgradeModuleRemovalPatch,
    SpecialPowerPauseButtonPatch,
    SpecialPowerObjectCapPatch,
    FireAtAttackerPatch,
    FoundationRebindPatch,
    GateCloseRepathPatch,
    GiveUpgradeAllPatch,
    GrantScienceUpgradePatch,
    GrantScienceUpgradeWorldbuilderPatch,
    HeadlessPatch,
    HealingReceivedPatch,
    HealingReceivedWorldbuilderPatch,
    ExperienceAwardPatch,
    ExperienceAwardWorldbuilderPatch,
    HeroArmyCarryoverPatch,
    HeroBarPatch,
    HeroBarSlotsPatch,
    HeroBarWorldbuilderPatch,
    HeroHordeDeathPatch,
    HordeHerobarPatch,
    HeroManaPatch,
    HeroRecruitParallelPatch,
    HideModifierFxPatch,
    HordeSelfExperiencePatch,
    HideSelectionDetailsPatch,
    HordeExitAbsorptionPatch,
    HordeMemberSpeedPatch,
    InfantryLightingPatch,
    InflationReadoutPatch,
    InterpolationAlphaPatch,
    KillCountTooltipPatch,
    LargeGroupBonusPatch,
    LevelGrantSpecialPowerPatch,
    LifetimeFieldsPatch,
    LiveBridgePatch,
    MapTransitionPatch,
    LivingWorldOverridePatch,
    LanJoinBystandersPatch,
    LobbyFactionBytePatch,
    MaintenanceCostPatch,
    MapListSymbolsPatch,
    ModLoadOrderPatch,
    ModelConditionImagesPatch,
    MountHealthRatioPatch,
    MountSwapEjectPatch,
    MultiContainPatch,
    MultiExecuteCooldownPatch,
    MultiExecuteGatePatch,
    MultiInstanceLauncherPatch,
    MultiInstancePatch,
    MultiModPatch,
    MultiSelectGroupPatch,
    NullGuardsPatch,
    ObjectImageUpgradePatch,
    ObjectImageUpgradeWorldbuilderPatch,
    ObjectivesScreenPatch,
    ObserverAllCommandsPatch,
    ObserverCommandRangePatch,
    ObserverSwitchPatch,
    OsNameFallbackPatch,
    PassiveAuraRevivePatch,
    PerfScopeSkipPatch,
    PerfStageReadoutPatch,
    PickupStuffEnterPatch,
    PillageModuleExtensionPatch,
    PlayerAiTypeResetPatch,
    PlayerHealFilterPatch,
    PlayerUpgradeDiscountPatch,
    ProductionConditionPatch,
    ProductionConditionWorldbuilderPatch,
    ProductionDeathNoRefundPatch,
    ProductionSplitPatch,
    ProductionSplitWorldbuilderPatch,
    QueueIgnoreCpPatch,
    QuietExitPatch,
    RadarStructureDiscsPatch,
    RebuildHoleRepairPatch,
    RepairDamageCancelPatch,
    ReplacementTransferPatch,
    RangedStandOffPatch,
    RechargeRescalePatch,
    RenderOnlyFramesPatch,
    RenderRatePatch,
    ReplaceSelfRubblePatch,
    ReplayAnnotationsPatch,
    ReplayOutcomePatch,
    ReviveObjectBindingPatch,
    SaveTempFilePatch,
    ScenarioPlayerFactionsPatch,
    SciencePrereqPatch,
    SciencePrereqWorldbuilderPatch,
    ScoreKeeperDanglingKeysPatch,
    ScriptDebugWindowPatch,
    SecondResourcePatch,
    ShareExperienceAllPatch,
    SharedControlOnLeavePatch,
    SkirmishAiFallbackPatch,
    SkirmishReplayPatch,
    SmartRallyPatch,
    SpawnUnionPatch,
    SpecialPowerChargesPatch,
    SpecialPowerMusicPatch,
    SpecialPowerRefundUpgradePatch,
    SpecialPowerRefundUpgradeWorldbuilderPatch,
    SpecialPowerUpgradeFiltersPatch,
    SpellbookCommandSetRefreshPatch,
    SpellbookHotkeysPatch,
    SpellRechargeResetPatch,
    SpellRechargeTargetsPatch,
    SpellStoreDeferralPatch,
    SpellStoreUpgradePatch,
    StandaloneLauncherPatch,
    SummonCarryoverPatch,
    TerrainResourceExpPatch,
    TextEntryClipboardPatch,
    TextureAnyExtensionPatch,
    TriggerRechargeListPatch,
    UniqueProductionIdPatch,
    UnitPlateOptionPatch,
    UpgradeDescriptionPatch,
    UpgradeCompleteSkipUnnamedPatch,
    UpgradeAliasPatch,
    UpgradeGrantListsPatch,
    VisibleHotkeysPatch,
    WallLayerPromotionPatch,
    WallMeshReleasePatch,
    WorldbuilderLabelAssertPatch,
    WorldbuilderModPatch,
    WorldbuilderObjectTypeaheadPatch,
    WorldbuilderSilentErrorsPatch,
    WotrBattleHeroPoolPatch,
    WotrBattleObserversPatch,
    WotrLobbySlotsPatch,
)


def _order(cls: type[Patch]) -> tuple[bool, str]:
    """Settled patches first, then the experimental ones, each block alphabetical by name.

    The split is the point of the ordering: somebody reading a list top to bottom meets everything
    that has been played before anything that has not, and the `exp` rows arrive together instead
    of scattered through the settled ones where a marker is easy to read past. Alphabetical within
    each block is what makes a name findable once the reader knows what they are looking for."""
    return (cls.experimental, cls.name)


#: The name -> patch map the CLI dispatches over, in the order everything lists them: see
#: `_order`. Dicts keep insertion order, so iterating this is already sorted.
PATCHES: dict[str, type[Patch]] = {cls.name: cls for cls in sorted(_REGISTERED, key=_order)}

__all__ = ["PATCHES"]
