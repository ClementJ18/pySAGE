"""Edain knowledge for `sage_replay`'s generic corpus tooling.

`sage_replay.aggregate` reports upgrade researches (`0x415`) only for a caller-supplied
tracked set, because the raw research stream is dominated by per-battalion gear purchases;
likewise it depth-numbers a repeatable system purchase (CPObject1, CPObject2, ...) only for
a caller-supplied set. This module holds Edain's sets - the researches whose timing a
corpus review asks about, and the fortress purchases whose depth is worth comparing - which
`sage-edain replay-aggregate` injects into the shared aggregate command. Names are raw ini
code names (`sage_replay.stats` records upgrade events unlocalized so they match; purchase
labels are raw under the default unlocalized aggregation).

It also holds Edain's faction refiner (`edain_faction_refiner`), which splits the two shared
realm factions into their sub-factions: Dwarves player-games into their realm (Erebor / Ered
Luin / Iron Hills) by the free clan upgrade the player bought at the citadel
(`dwarven_realm_faction`), and Men player-games into Gondor / Arnor / Belfalas by the Gondor hero
roster the replay's map declares (`gondor_variant_faction`).

It also holds Edain's power-recruit resolver (`edain_power_recruits`), a `PowerRecruits` hook
for `sage_replay.stats`: a handful of special powers permanently field an army rather than a
buff or a summon-and-despawn effect, and a build-order review should read those casts as
recruitment - a Mordor player's Haradrim call is as much a fielding decision as clicking the
same units at a barracks. `POWER_RECRUITS` covers Mordor's two summon powers (gated on the
caster's Side, since one `SpecialPower` definition can serve several factions - the Imladris trap
below is exactly that); `DORWINION_RECRUITS` covers the Dwarves' two Loyal Protectors tiers and
Fist of Dorwinion, Dwarves-gated the same way; `LEUCHTFEUER_RECRUITS` covers Men's four
signal-fire calls plus their all-in-one variant, each keyed to a (Gondor hordes, Belfalas hordes)
pair because Gondor and Belfalas fire the very same `CommandButton`/`SpecialPower` definitions -
only the caster's per-map Gondor hero roster (the same one `gondor_variant_faction` reads) tells
the two apart.

`LICHTBRINGER_RECRUITS` covers the Imladris Loremaster ("Wissender"/Lichtbringer). A player fields
it as an elementless `BruchtalLichtbringerHorde`, then toggles it to one of four elements with
`CommandButton`s whose `SpecialPower` fields, by copy-paste heritage, are Angmar's
`...ThrallMasterSummon...` powers - the very definitions Angmar (and Rohan / Lothlorien) fire to
summon units, so by raw code name a toggle is indistinguishable from an Angmar summon. The toggle
is what fixes the Loremaster's element, so - *only for an Imladris caster* (by faction `Side`) -
the resolver reads each of the four as a recruit of the matching element-specific horde
(`BruchtalLichtbringer{Erde,Feuer,Wasser,Luft}Horde`), and `IGNORED_RECRUITS` drops the elementless
`BruchtalLichtbringerHorde` placeholder from the normal recruit stream so the same Loremaster is
not counted twice. The four powers fire as `0x410` casts in 106 of 767 replays of the
edain-4.8.4.3 ladder corpus.

Partly covered: **combo hordes**. Two Lichtbringer hordes merge into an element-pair combo
(WaterWater, ErdeFeuer, ...) by clicking one horde onto another. The merge IS a discrete order -
`0x423`, ground-truthed by the labelled `tests/sage_replay/fixtures/combo replay.BfME2Replay`
(build two Lichtbringer hordes, toggle each, then one `0x423` at the merge frame). So a combine
*action* is countable and attributable to a player. What is not recoverable is *which* element-pair
combo formed: `0x423` carries only a runtime ObjectId (a live handle in the just-merged cluster),
not a static template id, so naming the WaterWater vs ErdeFeuer result needs the unsolved runtime
ObjectId->template tracking. Combo *usage* also leaks indirectly through the combo-only abilities
that resolve as normal power casts (WasserdesBruinen = Water+Water, HauchValinors = Air+Air,
VorbotedesTelperion = Earth+Earth). Neither the combine count nor the combo-usage signal is
surfaced here yet.
"""

from pathlib import Path

from sage_replay.aggregate import UNRESOLVED_FACTION

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


def dwarven_realm_faction(label: str, stats, data=None, map_file=None) -> str:
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


def gondor_variant_faction(label: str, stats, data, map_file) -> str:
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

# Recruit templates to drop from the normal recruit stream (a `sage_replay.stats` ignore set): the
# elementless Loremaster placeholder, whose element - and so its recruit row - only becomes known
# from the toggle `edain_power_recruits` reads. Counting the placeholder too would field every
# Loremaster twice, once elementless and once per element.
IGNORED_RECRUITS = frozenset({"BruchtalLichtbringerHorde"})


def edain_power_recruits(side: str | None, roster, power: str):
    """A `PowerRecruits` for `sage_replay.stats`: the template names a Mordor summon, a Dwarven
    Dorwinion call, a Men Leuchtfeuer call, or an Imladris Loremaster element toggle permanently
    fields, or `()` when `power` is not one of Edain's fielding powers, or the caster's Side doesn't
    gate it open. The Side gates matter because one `SpecialPower` definition can serve several
    factions in Edain - a non-Mordor cast of a Mordor summon, a non-Dwarves cast of a Dorwinion
    call, a non-Men cast of a Leuchtfeuer power, or a non-Imladris cast of a Loremaster toggle
    (Angmar/Rohan/Lothlorien fire the same four to summon units) fields nothing here. A Leuchtfeuer
    call's actual hordes depend on the caster's per-map Gondor roster, not their Side: Belfalas when
    `_BELFALAS_MARKER` is on it, Gondor (and Arnor, which shares
    Gondor's line units) otherwise. A Loremaster toggle fields the element-specific horde it selects
    (`LICHTBRINGER_RECRUITS`); the elementless placeholder it upgrades from is dropped separately by
    `IGNORED_RECRUITS`."""
    if power in POWER_RECRUITS:
        return POWER_RECRUITS[power] if side == _MORDOR_SIDE else ()
    if power in DORWINION_RECRUITS:
        return DORWINION_RECRUITS[power] if side == _DWARVEN_SIDE else ()
    if power in LEUCHTFEUER_RECRUITS:
        if side != _MEN_SIDE:
            return ()
        gondor, belfalas = LEUCHTFEUER_RECRUITS[power]
        return belfalas if _BELFALAS_MARKER in roster else gondor
    if power in LICHTBRINGER_RECRUITS:
        return (LICHTBRINGER_RECRUITS[power],) if side == _IMLADRIS_SIDE else ()
    return ()


def edain_faction_refiner(label: str, stats, data=None, map_file=None) -> str:
    """Edain's combined `FactionRefiner`: split the two shared realm factions into their
    sub-factions - Dwarves into Erebor / Ered Luin / Iron Hills by the opening clan upgrade,
    and Men into Gondor / Arnor / Belfalas by the map's Gondor hero roster. Every other faction
    passes through unchanged."""
    label = dwarven_realm_faction(label, stats, data, map_file)
    return gondor_variant_faction(label, stats, data, map_file)


__all__ = [
    "DWARVEN_REALMS",
    "FACTION_ICONS",
    "ICONS_DIR",
    "GONDOR_VARIANTS",
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
    "gondor_variant_faction",
]
