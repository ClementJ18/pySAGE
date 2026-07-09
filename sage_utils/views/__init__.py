"""Pure (non-Qt) read helpers turning typed game objects into the dicts/values a UI
renders. Lazy conversion can raise, so every getter degrades to a default (`safe`)
rather than abort the view.

Split by subject - `weapons` (damage/DPS/armor), `powers` (special powers, summon
chains, modifiers), `text` (localization/display names), `buttons` (command buttons,
sets and their images), `factions` (playable factions, hero recruitment, the builder
index), `objects` (economy and detail summaries) - over the shared primitives in
`base`. Everything public is re-exported here; import from `sage_utils.views`.
"""

from sage_utils.views.base import (
    all_modules,
    find_behavior,
    fmt_stat,
    percent,
    safe,
    upgrade_names,
)
from sage_utils.views.buttons import (
    command_button_images,
    command_button_view,
    command_buttons_view,
    command_set_buttons,
    flatten_button_images,
    object_button_image,
    portrait_mapped_images,
    select_portrait_image,
)
from sage_utils.views.factions import (
    builder_index,
    builders_of,
    building_faction,
    faction_for_side,
    playable_faction_objects,
    playable_factions,
    recruited_hero_names,
    revive_order,
)
from sage_utils.views.objects import (
    build_cost_view,
    object_detail,
    resource_production_view,
)
from sage_utils.views.powers import (
    modifier_view,
    mounted_template,
    special_power_cooldown,
    special_power_view,
)
from sage_utils.views.text import (
    clean_text,
    description,
    display_name,
    display_name_index,
    localize,
    upgrade_label,
    upgrade_toggle_labels,
)
from sage_utils.views.weapons import (
    FilterSignature,
    armorset_view,
    clip_reload_time,
    effective_health,
    effective_health_against,
    filter_signature,
    weapon_attack_interval,
    weapon_damage_breakdown,
    weapon_damage_per_shot,
    weapon_dps,
    weapon_nuggets,
    weapon_radius,
    weapon_set_view,
    weapon_top_nugget,
    weapon_upgrade_triggers,
)

__all__ = [
    "FilterSignature",
    "all_modules",
    "armorset_view",
    "build_cost_view",
    "builder_index",
    "builders_of",
    "building_faction",
    "clean_text",
    "clip_reload_time",
    "command_button_images",
    "command_button_view",
    "command_buttons_view",
    "command_set_buttons",
    "description",
    "display_name",
    "display_name_index",
    "effective_health",
    "effective_health_against",
    "faction_for_side",
    "filter_signature",
    "find_behavior",
    "flatten_button_images",
    "fmt_stat",
    "localize",
    "modifier_view",
    "mounted_template",
    "object_button_image",
    "object_detail",
    "percent",
    "playable_faction_objects",
    "playable_factions",
    "portrait_mapped_images",
    "recruited_hero_names",
    "resource_production_view",
    "revive_order",
    "safe",
    "select_portrait_image",
    "special_power_cooldown",
    "special_power_view",
    "upgrade_label",
    "upgrade_names",
    "upgrade_toggle_labels",
    "weapon_attack_interval",
    "weapon_damage_breakdown",
    "weapon_damage_per_shot",
    "weapon_dps",
    "weapon_nuggets",
    "weapon_radius",
    "weapon_set_view",
    "weapon_top_nugget",
    "weapon_upgrade_triggers",
]
