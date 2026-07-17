"""Edain knowledge for `sage_replay`'s generic corpus tooling.

`sage_replay.aggregate` reports upgrade researches and depth-numbers repeatable purchases only
for a caller-supplied tracked set, because the raw streams are dominated by per-battalion gear
noise. This module holds Edain's sets - the researches worth timing and the fortress purchases
worth comparing - which `sage-edain replay-aggregate` injects into the shared aggregate command.
Names are raw ini code names (`sage_replay.stats` records upgrade events unlocalized to match).

It also holds Edain's faction refiner (`edain_faction_refiner`), splitting the two shared realm
factions: Dwarves into their realm (Erebor / Ered Luin / Iron Hills) by the free clan upgrade
bought at the citadel, and Men into Gondor / Arnor / Belfalas by the Gondor hero roster the
replay's map declares - see `dwarven_realm_faction` and `gondor_variant_faction` for the details.

It also holds Edain's power-recruit resolver (`edain_power_recruits`), a `PowerRecruits` hook for
`sage_replay.stats`: a handful of special powers permanently field an army rather than a buff or
a summon-and-despawn effect, and a build-order review should read those casts as recruitment - a
Mordor player's Haradrim call is as much a fielding decision as clicking the same units at a
barracks. `POWER_RECRUITS`, `DORWINION_RECRUITS`, and `LEUCHTFEUER_RECRUITS` cover Mordor's
summons, the Dwarves' Dorwinion calls, and Men's signal-fire calls respectively, each gated on
the caster's faction `Side` since one `SpecialPower` definition can serve several factions (see
`edain_power_recruits` for the exact gating rules).

`LICHTBRINGER_RECRUITS` covers the Imladris Loremaster ("Wissender"/Lichtbringer), the trickiest
case: a player fields it as an elementless `BruchtalLichtbringerHorde`, then toggles it to one of
four elements with `CommandButton`s whose `SpecialPower` fields, by copy-paste heritage, are
Angmar's `...ThrallMasterSummon...` powers - the very definitions Angmar (and Rohan / Lothlorien)
fire to summon units, so by raw code name a toggle is indistinguishable from an Angmar summon.
Only for an Imladris caster does the resolver read each of the four as a recruit of the matching
element-specific horde; `IGNORED_RECRUITS` drops the elementless placeholder from the normal
recruit stream so the same Loremaster is not counted twice.

For an *Angmar* caster those same four powers are genuine conversions, but of two different
units: each is fired both by the ThrallMaster's summon button (the thrall becomes a line horde)
and by the SiegeTroll horde's siege-conversion button (the trolls build a ram / sling / siege
tower). The two button families differ in their `Options` bitfield - only the SiegeTroll buttons
carry `OK_FOR_MULTI_EXECUTE OK_FOR_MULTI_SELECT` - and a cast order embeds the firing button's
Options as its second Integer, so `edain_power_recruits` splits Angmar casts on those bits
(`ANGMAR_THRALL_RECRUITS` vs `ANGMAR_SIEGE_TROLL_RECRUITS`; corpus-validated: all 197 Angmar
ram/sling/tower casts in the 4.8.4.3 corpus carry the MULTI bits, the 2 thrall casts don't).

Manual casts are the rare path, though: a dedication is normally bought as an `OBJECT_UPGRADE`
(`Upgrade_ThrallMaster*`, `Upgrade_Herold*`), whose `DoCommandUpgrade` behavior then presses the
summon button engine-side - never entering the order stream - so the player's only recorded
order is the `0x415` research. `edain_upgrade_recruits` (an `UpgradeRecruits` hook) reads those
researches as recruits of the resulting unit: Angmar's ThrallMaster dedications
(`ANGMAR_THRALL_UPGRADES`) and Rohan's Hauptmann/Herold dedications (`HAUPTMANN_UPGRADES`,
whose summon powers - fielding the loyal Getreue hordes - are Hauptmann-specific, so their
manual casts in `HAUPTMANN_RECRUITS` need no Options split).

Partly covered: **combo hordes**. Two Lichtbringer hordes merge into an element-pair combo by
clicking one horde onto another - a discrete `0x423` order, ground-truthed by the labelled
`tests/sage_replay/fixtures/combo replay.BfME2Replay`, so a combine *action* is countable and
attributable to a player. What is not recoverable is *which* combo formed: `0x423` carries only a
runtime ObjectId, not a static template id, so naming the result needs the unsolved runtime
ObjectId->template tracking. Neither the combine count nor the combo-usage signal (which also
leaks through combo-only power casts) is surfaced here yet.
"""

from collections.abc import Sequence
from pathlib import Path

from sage_replay.aggregate import UNRESOLVED_FACTION
from sage_replay.narrate import GameData
from sage_replay.stats import PlayerStats

# The front-page faction emblems shipped alongside this module (webp), keyed by the aggregate
# faction label each renders under: the refined sub-faction labels for the two shared realm
# factions (Men -> Gondor / Arnor / Belfalas via `gondor_variant_faction`, Dwarves -> the three
# realms via `dwarven_realm_faction`), and the raw PlayerTemplate code name for every faction
# that isn't split. `tools/rebuild_aggregates.py` copies these into the generated site and hands
# the renderer a per-page-relative URL for each, so a faction's page, leaderboard row, header and
# matchup cells carry its emblem (the generic `sage_replay` core ships no art of its own).
ICONS_DIR = Path(__file__).resolve().parent / "icons"

FACTION_ICONS = {
    "FactionAngmar": "Angmar_frontpage.webp",
    "Arnor": "Arnor_frontpage.webp",
    "Belfalas": "Belfalas_frontpage.webp",
    "Dwarves (Erebor)": "Erebor_frontpage.webp",
    "Dwarves (Ered Luin)": "Ered-Luin_frontpage.webp",
    "Dwarves (Iron Hills)": "Iron_Hills_frontpage.webp",
    "Gondor": "Gondor_frontpage.webp",
    "FactionImladris": "Imladris_frontpage.webp",
    "FactionIsengard": "Isengard_frontpage.webp",
    "FactionElves": "Lothlorien_frontpage.webp",
    "FactionWild": "Misty_Mountains_frontpage.webp",
    "FactionMordor": "Mordor_frontpage.webp",
    "FactionRohan": "Rohan_frontpage.webp",
}

# The shared economy researches: the internal/external production increases and the two
# worker-tool upgrades.
_ECONOMY = (
    "Upgrade_EdainEconomyProduktionserhohung",
    "Upgrade_EdainEconomyProduktionserhohungExtern",
    "Upgrade_EdainHandwerkerWerkzeuge",
    "Upgrade_EdainSiedlerWerkzeuge",
)

# The library (Bibliothek) arts and their developed second tiers.
_LIBRARY = (
    "Upgrade_BibliothekSchmiedekunst",
    "Upgrade_BibliothekSchmiedekunstEntwickelt",
    "Upgrade_BibliothekMilitarkunst",
    "Upgrade_BibliothekMilitarkunstEntwickelt",
    "Upgrade_BibliothekMystickunst",
    "Upgrade_BibliothekMystickunstEntwickelt",
    "Upgrade_BibliothekAgrarkunst",
    "Upgrade_BibliothekAgrarkunstEntwickelt",
)

TRACKED_UPGRADES = frozenset(_ECONOMY + _LIBRARY)

# The repeatable fortress purchases whose depth a corpus review compares: the command-point
# increase bought at the citadel.
TRACKED_PURCHASES = frozenset({"CPObject"})

# Edain's Dwarves are really three factions: the realm is picked once at the starting
# citadel and recorded as a free clan-upgrade purchase. Clan -> realm follows the mod's own
# wiring (DwarvenFreeBuild.ini's ModelConditionUpgrade modules Upgrade_Ironhills /
# Upgrade_Erebor / Upgrade_EredLuin, triggered by these upgrades respectively).
DWARVEN_REALMS = {
    "Upgrade_ClanFeuerbarte": "Iron Hills",
    "Upgrade_ClanLangbarte": "Erebor",
    "Upgrade_ClanBreitschultern": "Ered Luin",
}


def dwarven_realm_faction(
    label: str, stats: PlayerStats, data: GameData | None = None, map_file: str | None = None
) -> str:
    """A `FactionRefiner` for `sage_replay.aggregate`: split FactionDwarves player-games
    into their realm by the clan upgrade the player bought. The realm choice is permanent -
    a Dwarves player picks one clan at the citadel and can't re-pick - so the first clan
    upgrade seen identifies the realm no matter how late the player clicked it (they take
    anywhere from a few seconds to a minute). A dwarf game with no clan purchase at all can't
    be placed in a realm, so it is marked unresolved - the aggregate drops it and lists it as
    a warning, like any other game whose faction couldn't be attributed. `data`/`map_file`
    are part of the `FactionRefiner` contract but unused here - the realm is a stats signal."""
    if label != "FactionDwarves":
        return label
    for event in stats.events:
        if event.category == "upgrades" and event.label in DWARVEN_REALMS:
            return f"Dwarves ({DWARVEN_REALMS[event.label]})"
    return UNRESOLVED_FACTION


# Edain's Gondor faction (the `FactionMen` PlayerTemplate) is really three sub-factions chosen
# per *map*, not per player: a map's `map.ini` re-opens FactionMen and swaps its whole roster
# (`BuildableHeroesMP`, starting units, spellbook) to the sub-faction the map is set for - so
# every FactionMen player on a given map plays the same one. The Gondor hero roster the map
# declares carries a tell-tale recruit that names the variant: Arnor's Malbeth-line captain, or
# Belfalas's Amrothos of Dol Amroth. A roster with neither is base Gondor.
GONDOR_FACTION = "FactionMen"
GONDOR_VARIANTS = {
    "ArnorCaptainStealthless_mod": "Arnor",
    "AmrothAmrothos": "Belfalas",
}


def gondor_variant_faction(
    label: str, stats: PlayerStats, data: GameData | None, map_file: str | None
) -> str:
    """A `FactionRefiner` for `sage_replay.aggregate`: split FactionMen player-games into
    Gondor / Arnor / Belfalas by the Gondor hero roster the replay's map declares. The variant
    is a property of the map (its `map.ini` re-opens FactionMen with the sub-faction's
    `BuildableHeroesMP`), so it is read off `data.hero_roster_for(map_file, <FactionMen id>)` -
    the same per-map roster override the revive model uses - rather than from the player's own
    orders. A map with no override (or an unknown FactionMen faction) is plain Gondor."""
    if label != GONDOR_FACTION or data is None:
        return label
    try:
        gondor_id = data.faction_names.index(GONDOR_FACTION)
    except ValueError:
        return "Gondor"
    roster = data.hero_roster_for(map_file, gondor_id)
    for marker, variant in GONDOR_VARIANTS.items():
        if marker in roster:
            return variant
    return "Gondor"


# Special powers that permanently field an army, rather than a buff, a self-effect, or a
# summon-and-despawn creature: a build-order review should read a cast of one of these as
# recruitment, since the units it yields are exactly as permanent as if bought at a barracks.
# Keyed by the power's raw code name (like every other cross-faction table in this module) and
# gated on the caster's Side, because - as the Lichtbringer paragraph in the module docstring
# documents - one `SpecialPower` definition can serve several factions.
_MORDOR_SIDE = "Mordor"

POWER_RECRUITS = {
    "SpellBookSBSummonEasterling": ("MordorRhunSwordHorde", "MordorEasterlingHordeMod"),
    "SpellBookSBSummonHaradrim": (
        "MordorMumakil",
        "MordorHaradrimRiderHordeMod",
        "MordorHaradrimRiderHordeMod",
    ),
}

# The Dwarves' Dorwinion calls, another set of permanently-fielding powers (gated on the caster's
# Side exactly like the Mordor summons above): the two "Loyal Protectors" tiers field a mix of
# Dorwinion sword and bow hordes - the second tier is the doubled-up version - and "Fist of
# Dorwinion" fields a Purple Guard horde.
_DWARVEN_SIDE = "Dwarves"

DORWINION_RECRUITS = {
    "SpecialAbilityLoyalProtectors": (
        "DwarvenDorwinionSwordmanHorde",
        "DwarvenDorwinionBowmanHorde",
    ),
    "SpecialAbilityLoyalProtectors2": (
        "DwarvenDorwinionSwordmanHorde",
        "DwarvenDorwinionSwordmanHorde",
        "DwarvenDorwinionBowmanHorde",
        "DwarvenDorwinionBowmanHorde",
    ),
    "SpecialAbilityFistOfDorwinion": ("DwarvenDorwinionPurpleGuardHorde",),
}

# The signal-fire (Leuchtfeuer) powers: Men's regional beacon calls, each fielding two hordes
# of a region's line unit, plus `...Lehen`, the all-in-one call that lights every region's
# beacon at once. Gondor and Belfalas (Dol Amroth) fire the SAME power/CommandButton
# definitions (only a `_DA` button variant differs), so which hordes actually spawn depends on
# the map's Gondor variant - read off the caster's per-map hero roster, the same signal
# `gondor_variant_faction` reads, since Gondor/Arnor/Belfalas all report Side "Men" alike. Each
# entry pairs (Gondor hordes, Belfalas hordes).
_MEN_SIDE = "Men"

# The roster marker that picks the Belfalas hordes, reused from `GONDOR_VARIANTS` so this table
# reads a roster exactly the way `gondor_variant_faction` does rather than hardcoding the name
# again.
_BELFALAS_MARKER = next(
    marker for marker, variant in GONDOR_VARIANTS.items() if variant == "Belfalas"
)

LEUCHTFEUER_RECRUITS = {
    "SpecialAbilityLeuchtfeuerRingVale": (
        ("RingValeSwordsmanHorde", "RingValeSwordsmanHorde"),
        ("LamedonSwordsmenHorde", "LamedonSwordsmenHorde"),
    ),
    "SpecialAbilityLeuchtfeuerLossarnach": (
        ("LehenLossarnachAxteHorde", "LehenLossarnachAxteHorde"),
        ("LehenNimrassimRavensHorde", "LehenNimrassimRavensHorde"),
    ),
    "SpecialAbilityLeuchtfeuerMorthond": (
        ("MorthondBowmenHorde", "MorthondBowmenHorde"),
        ("AndrastArcherHorde", "AndrastArcherHorde"),
    ),
    "SpecialAbilityLeuchtfeuerPelagir": (
        ("PelegirSpearmenHorde", "PelegirSpearmenHorde"),
        ("TolFalasSpearmenHorde", "TolFalasSpearmenHorde"),
    ),
    "SpecialAbilityLeuchtfeuerLehen": (
        (
            "RingValeSwordsmanHorde",
            "LehenLossarnachAxteHorde",
            "MorthondBowmenHorde",
            "PelegirSpearmenHorde",
        ),
        (
            "LamedonSwordsmenHorde",
            "LehenNimrassimRavensHorde",
            "AndrastArcherHorde",
            "TolFalasSpearmenHorde",
        ),
    ),
}

# The Imladris Loremaster's four element toggles (raw `...ThrallMasterSummon...` power code names,
# by copy-paste heritage) -> the element each selects. Keyed by raw power name so it survives the
# id/registration shifts between patches; "Feuer" toggles the Light ("Wissender des Lichts") form -
# the internal name and the player-facing element diverge.
LICHTBRINGER_ELEMENTS = {
    "SpecialAbilityAngmarThrallMasterSummonRhudaurSlingers": "Earth",  # ...ToggleLichtbringerErde
    "SpecialAbilityAngmarThrallMasterSummonOrc": "Light",  # ...ToggleLichtbringerFeuer
    "SpecialAbilityAngmarThrallMasterSummonWolfRiders": "Water",  # ...ToggleLichtbringerWasser
    "SpecialAbilityAngmarThrallMasterSummonRhudaurSpearmen": "Air",  # ...ToggleLichtbringerLuft
}

# element -> the element-specific Loremaster horde each toggle transforms the elementless base
# into. The German element stems (Erde/Feuer/Wasser/Luft) are the object code names; the English
# labels are only for reading the toggle table above (Light selects the "Feuer" horde).
_LICHTBRINGER_ELEMENT_HORDES = {
    "Earth": "BruchtalLichtbringerErdeHorde",
    "Light": "BruchtalLichtbringerFeuerHorde",
    "Water": "BruchtalLichtbringerWasserHorde",
    "Air": "BruchtalLichtbringerLuftHorde",
}

# Raw toggle power -> the element-specific Loremaster horde it fields, for an Imladris caster.
LICHTBRINGER_RECRUITS = {
    power: _LICHTBRINGER_ELEMENT_HORDES[element] for power, element in LICHTBRINGER_ELEMENTS.items()
}

# The faction `Side` token whose casts of the four shared powers are Lichtbringer toggles.
_IMLADRIS_SIDE = "Imladris"

# The faction `Side` token whose casts of the shared powers are real unit conversions.
_ANGMAR_SIDE = "Angmar"

# The `CommandButton` Options bits that mark an Angmar cast as the SiegeTroll's siege
# conversion rather than a ThrallMaster summon: OK_FOR_MULTI_SELECT | OK_FOR_MULTI_EXECUTE
# (order_space_map.md's confirmed bit table). Only the SiegeTroll's three conversion buttons
# carry them; every ThrallMaster summon button is bare TOGGLE_IMAGE_ON_WEAPONSET ON_GROUND_ONLY.
_SIEGE_TROLL_OPTION_BITS = 0x100 | 0x100000

# Angmar ThrallMaster summon powers -> the line horde the thrall becomes (each module's
# `SummonReplacementSpecialAbilityUpdate` MountedTemplate). The four shared powers plus the
# Black Guard's Orks-vom-Berg-Gram dedication, whose power is ThrallMaster-specific.
ANGMAR_THRALL_RECRUITS = {
    "SpecialAbilityAngmarThrallMasterSummonOrc": "AngmarOrcWarriors",
    "SpecialAbilityAngmarThrallMasterSummonWolfRiders": "AngmarWolfRiders",
    "SpecialAbilityAngmarThrallMasterSummonRhudaurSpearmen": "AngmarRhudaurSpearmen",
    "SpecialAbilityAngmarThrallMasterSummonRhudaurSlingers": "AngmarRhudaurSlingers",
    "SpecialAbilityAngmarThrallMasterSummonOrkSchlachter": "AngmarOrkSchlachterHorde",
}

# The same powers fired from the SiegeTroll horde's buttons (the MULTI Options bits) -> the
# siege engine the trolls build. The horde's modules mount an `...Egg` that hatches into the
# engine; the engine is what the player fielded, so that is the recruit recorded. The slingers
# power has no SiegeTroll button, so it has no row here.
ANGMAR_SIEGE_TROLL_RECRUITS = {
    "SpecialAbilityAngmarThrallMasterSummonOrc": "AngmarBatteringRam",
    "SpecialAbilityAngmarThrallMasterSummonWolfRiders": "AngmarTrollSling",
    "SpecialAbilityAngmarThrallMasterSummonRhudaurSpearmen": "AngmarSiegeTower",
}

# The ThrallMaster dedication researches -> the unit the thrall becomes. Buying one is the
# player's actual conversion order: its `DoCommandUpgrade` presses the summon button
# engine-side, so no power cast enters the stream (the dominant path - every Angmar replay in
# the 4.8.4.3 corpus converts thralls this way).
ANGMAR_THRALL_UPGRADES = {
    "Upgrade_ThrallMasterOrcWarriors": "AngmarOrcWarriors",
    "Upgrade_ThrallMasterWolfRiders": "AngmarWolfRiders",
    "Upgrade_ThrallMasterRhudaurSpearmen": "AngmarRhudaurSpearmen",
    "Upgrade_ThrallMasterRhudaurSlingers": "AngmarRhudaurSlingers",
    "Upgrade_ThrallMasterOrksBergGram": "AngmarOrkSchlachterHorde",
}

# The faction `Side` token whose Hauptmann/Herold dedications convert into Getreue hordes.
_ROHAN_SIDE = "Rohan"

# Rohan's Hauptmann (Herold) summon powers -> the loyal Getreue horde the Hauptmann fields.
# Unlike Angmar's, these powers are Hauptmann-specific, so the power name alone names the unit.
HAUPTMANN_RECRUITS = {
    "SpecialAbilityHeroldSummonWestfoldWachter": "GetreueSchwertHordeHauptmann",
    "SpecialAbilityHeroldSummonWestfoldSpearmen": "GetreueSpeerHordeHauptmann",
    "SpecialAbilityHeroldSummonIsenfurtReiterHorde": "GetreueReiterHordeHauptmann",
}

# The Hauptmann dedication researches -> the Getreue horde they field; like the ThrallMaster
# dedications, the research's `DoCommandUpgrade` fires the summon engine-side, so the `0x415`
# purchase is the player's only recorded order (no manual cast appears in the 4.8.4.3 corpus).
HAUPTMANN_UPGRADES = {
    "Upgrade_HeroldRohanWestfoldWachter": "GetreueSchwertHordeHauptmann",
    "Upgrade_HeroldRohanWestfoldSpearmen": "GetreueSpeerHordeHauptmann",
    "Upgrade_HeroldIsenfurtReiterHorde": "GetreueReiterHordeHauptmann",
}

# Recruit templates to drop from the normal recruit stream (a `sage_replay.stats` ignore set): the
# elementless Loremaster placeholder, whose element - and so its recruit row - only becomes known
# from the toggle `edain_power_recruits` reads. Counting the placeholder too would field every
# Loremaster twice, once elementless and once per element.
IGNORED_RECRUITS = frozenset({"BruchtalLichtbringerHorde"})


def edain_power_recruits(
    side: str | None, roster: Sequence[str], power: str, options: int = 0
) -> Sequence[str]:
    """A `PowerRecruits` for `sage_replay.stats`: the template names a Mordor summon, a Dwarven
    Dorwinion call, a Men Leuchtfeuer call, an Imladris Loremaster element toggle, an Angmar
    ThrallMaster/SiegeTroll conversion, or a Rohan Hauptmann dedication permanently fields, or
    `()` when `power` is not one of Edain's fielding powers, or the caster's Side doesn't gate
    it open. The Side gates matter because one `SpecialPower` definition can serve several
    factions in Edain - a non-Mordor cast of a Mordor summon, a non-Dwarves cast of a Dorwinion
    call, a non-Men cast of a Leuchtfeuer power, or a Lothlorien peasant-toggle cast of a shared
    ThrallMaster power fields nothing here. A Leuchtfeuer call's actual hordes depend on the
    caster's per-map Gondor roster, not their Side: Belfalas when `_BELFALAS_MARKER` is on it,
    Gondor (and Arnor, which shares Gondor's line units) otherwise.

    The four shared `...ThrallMasterSummon...` powers split three ways: an Imladris cast is a
    Loremaster toggle fielding the element-specific horde (`LICHTBRINGER_RECRUITS`; the
    elementless placeholder it upgrades from is dropped separately by `IGNORED_RECRUITS`), and
    an Angmar cast is a real conversion whose *button* decides the unit - `options` (the cast's
    CommandButton Options bitfield, threaded through by `compute_stats`) carries the SiegeTroll
    buttons' MULTI bits for a ram/sling/tower build (`ANGMAR_SIEGE_TROLL_RECRUITS`) and not for
    a ThrallMaster summon (`ANGMAR_THRALL_RECRUITS`). Any other Side's cast of them is a
    reversible toggle, not a fielding."""
    if power in POWER_RECRUITS:
        return POWER_RECRUITS[power] if side == _MORDOR_SIDE else ()
    if power in DORWINION_RECRUITS:
        return DORWINION_RECRUITS[power] if side == _DWARVEN_SIDE else ()
    if power in LEUCHTFEUER_RECRUITS:
        if side != _MEN_SIDE:
            return ()
        gondor, belfalas = LEUCHTFEUER_RECRUITS[power]
        return belfalas if _BELFALAS_MARKER in roster else gondor
    if power in HAUPTMANN_RECRUITS:
        return (HAUPTMANN_RECRUITS[power],) if side == _ROHAN_SIDE else ()
    if power in ANGMAR_THRALL_RECRUITS:
        if side == _IMLADRIS_SIDE and power in LICHTBRINGER_RECRUITS:
            return (LICHTBRINGER_RECRUITS[power],)
        if side == _ANGMAR_SIDE:
            table = (
                ANGMAR_SIEGE_TROLL_RECRUITS
                if options & _SIEGE_TROLL_OPTION_BITS
                else ANGMAR_THRALL_RECRUITS
            )
            name = table.get(power)
            return (name,) if name is not None else ()
        return ()
    return ()


def edain_upgrade_recruits(side: str | None, upgrade: str) -> Sequence[str]:
    """An `UpgradeRecruits` for `sage_replay.stats`: the unit an Angmar ThrallMaster or a Rohan
    Hauptmann dedication research converts its buyer into, or `()` for every other upgrade.
    These conversions' only player order is the `0x415` research - its `DoCommandUpgrade`
    presses the summon button engine-side - so this is where the dominant recruit signal lives
    (the module docstring's manual-cast paragraph). Side-gated like every power table: the
    upgrade names are faction-specific today, but a future patch reusing one must not leak a
    conversion into another faction's stats."""
    if upgrade in ANGMAR_THRALL_UPGRADES:
        return (ANGMAR_THRALL_UPGRADES[upgrade],) if side == _ANGMAR_SIDE else ()
    if upgrade in HAUPTMANN_UPGRADES:
        return (HAUPTMANN_UPGRADES[upgrade],) if side == _ROHAN_SIDE else ()
    return ()


def edain_faction_refiner(
    label: str, stats: PlayerStats, data: GameData | None = None, map_file: str | None = None
) -> str:
    """Edain's combined `FactionRefiner`: split the two shared realm factions into their
    sub-factions - Dwarves into Erebor / Ered Luin / Iron Hills by the opening clan upgrade,
    and Men into Gondor / Arnor / Belfalas by the map's Gondor hero roster. Every other faction
    passes through unchanged."""
    label = dwarven_realm_faction(label, stats, data, map_file)
    return gondor_variant_faction(label, stats, data, map_file)


__all__ = [
    "ANGMAR_SIEGE_TROLL_RECRUITS",
    "ANGMAR_THRALL_RECRUITS",
    "ANGMAR_THRALL_UPGRADES",
    "DWARVEN_REALMS",
    "FACTION_ICONS",
    "ICONS_DIR",
    "GONDOR_VARIANTS",
    "HAUPTMANN_RECRUITS",
    "HAUPTMANN_UPGRADES",
    "IGNORED_RECRUITS",
    "LEUCHTFEUER_RECRUITS",
    "LICHTBRINGER_ELEMENTS",
    "LICHTBRINGER_RECRUITS",
    "POWER_RECRUITS",
    "TRACKED_PURCHASES",
    "TRACKED_UPGRADES",
    "dwarven_realm_faction",
    "edain_faction_refiner",
    "edain_power_recruits",
    "edain_upgrade_recruits",
    "gondor_variant_faction",
]
