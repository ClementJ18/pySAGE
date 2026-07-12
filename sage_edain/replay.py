"""Edain knowledge for `sage_replay`'s generic corpus tooling.

`sage_replay.aggregate` reports upgrade researches (`0x415`) only for a caller-supplied
tracked set, because the raw research stream is dominated by per-battalion gear purchases;
likewise it depth-numbers a repeatable system purchase (CPObject1, CPObject2, ...) only for
a caller-supplied set. This module holds Edain's sets - the researches whose timing a
corpus review asks about, and the fortress purchases whose depth is worth comparing - which
`sage-edain replay-aggregate` injects into the shared aggregate command. Names are raw ini
code names (`sage_replay.stats` records upgrade events unlocalized so they match; purchase
labels are raw under the default unlocalized aggregation).

It also holds Edain's faction refiner: Dwarves player-games split into their realm (Erebor
/ Ered Luin / Iron Hills) by the free clan upgrade the player bought at the citadel - see
`dwarven_realm_faction`.

And Edain's power relabeler (`lichtbringer_power_label`): the Imladris Lichtbringer ("Wissender")
toggles its element with four `CommandButton`s whose `SpecialPower` fields, by copy-paste
heritage, are Angmar's `...ThrallMasterSummon...` powers - the very same definitions Angmar (and
Rohan / Lothlorien) fire to summon units. In the order stream a toggle is an ordinary
special-power cast, so it counts in `sage_replay.stats`' `powers` bucket, but by raw code name it
is indistinguishable from an Angmar summon. This relabeler reads them as
`Lichtbringer -> Earth/Light/Water/Air` *only for an Imladris caster* (by faction `Side`), leaving
every other faction's cast of the same power untouched. Validated against the edain-4.8.4.3 ladder
corpus: the four powers fire as `0x410` casts in 106 of 767 replays.

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

from sage_replay.aggregate import UNRESOLVED_FACTION

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


def dwarven_realm_faction(label: str, stats) -> str:
    """A `FactionRefiner` for `sage_replay.aggregate`: split FactionDwarves player-games
    into their realm by the clan upgrade the player bought. The realm choice is permanent -
    a Dwarves player picks one clan at the citadel and can't re-pick - so the first clan
    upgrade seen identifies the realm no matter how late the player clicked it (they take
    anywhere from a few seconds to a minute). A dwarf game with no clan purchase at all can't
    be placed in a realm, so it is marked unresolved - the aggregate drops it and lists it as
    a warning, like any other game whose faction couldn't be attributed."""
    if label != "FactionDwarves":
        return label
    for event in stats.events:
        if event.category == "upgrades" and event.label in DWARVEN_REALMS:
            return f"Dwarves ({DWARVEN_REALMS[event.label]})"
    return UNRESOLVED_FACTION


# The Imladris Lichtbringer's four element-toggle buttons and the (shared, misleadingly-named)
# SpecialPower each fires -> the element it selects. Keyed by the power's raw code name so it
# survives id/registration shifts between patches; the button that fires each is
# Command_SpecialAbilityToggleLichtbringer{Erde,Feuer,Wasser,Luft}. "Feuer" toggles the Light
# ("Wissender des Lichts") form - the internal name and the player-facing element diverge.
LICHTBRINGER_ELEMENTS = {
    "SpecialAbilityAngmarThrallMasterSummonRhudaurSlingers": "Earth",  # ...ToggleLichtbringerErde
    "SpecialAbilityAngmarThrallMasterSummonOrc": "Light",  # ...ToggleLichtbringerFeuer
    "SpecialAbilityAngmarThrallMasterSummonWolfRiders": "Water",  # ...ToggleLichtbringerWasser
    "SpecialAbilityAngmarThrallMasterSummonRhudaurSpearmen": "Air",  # ...ToggleLichtbringerLuft
}

# The faction `Side` token whose casts of the four shared powers are Lichtbringer toggles.
_IMLADRIS_SIDE = "Imladris"


def lichtbringer_power_label(side: str | None, power: str) -> str:
    """A `PowerLabeler` for `sage_replay.aggregate`: rename the four shared toggle powers to
    `Lichtbringer -> <Element>` when the caster's faction `Side` is Imladris, so an Imladris
    player's element switches read as transforms in the `powers` pick tables. Every other
    faction (Angmar/Rohan/Lothlorien fire the same definitions to summon units) is left with
    the raw power name, as is any power outside the map."""
    if side == _IMLADRIS_SIDE and power in LICHTBRINGER_ELEMENTS:
        return f"Lichtbringer -> {LICHTBRINGER_ELEMENTS[power]}"
    return power


__all__ = [
    "DWARVEN_REALMS",
    "LICHTBRINGER_ELEMENTS",
    "TRACKED_PURCHASES",
    "TRACKED_UPGRADES",
    "dwarven_realm_faction",
    "lichtbringer_power_label",
]
