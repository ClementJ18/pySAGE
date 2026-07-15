"""The Edain replay overlay: the tracked-upgrade set, the dwarven-realm and Gondor-variant
faction refiners, and their injection into the shared aggregate CLI command."""

import argparse

from sage_edain.replay import (
    DORWINION_RECRUITS,
    DWARVEN_REALMS,
    GONDOR_VARIANTS,
    IGNORED_RECRUITS,
    LEUCHTFEUER_RECRUITS,
    LICHTBRINGER_ELEMENTS,
    LICHTBRINGER_RECRUITS,
    POWER_RECRUITS,
    TRACKED_UPGRADES,
    dwarven_realm_faction,
    edain_faction_refiner,
    edain_power_recruits,
    edain_upgrade_recruits,
    gondor_variant_faction,
)
from sage_replay.__main__ import add_aggregate_command
from sage_replay.stats import PlayerStats, StatEvent


def test_tracked_upgrades_span_economy_and_library():
    assert "Upgrade_EdainSiedlerWerkzeuge" in TRACKED_UPGRADES
    assert "Upgrade_EdainEconomyProduktionserhohungExtern" in TRACKED_UPGRADES
    assert "Upgrade_BibliothekAgrarkunst" in TRACKED_UPGRADES
    assert "Upgrade_BibliothekAgrarkunstEntwickelt" in TRACKED_UPGRADES
    assert len(TRACKED_UPGRADES) == 12


def _stats(events: list[StatEvent]) -> PlayerStats:
    return PlayerStats(player="P", events=events)


def test_dwarven_realm_refiner():
    assert set(DWARVEN_REALMS.values()) == {"Erebor", "Ered Luin", "Iron Hills"}

    pick = StatEvent(0.4, "upgrades", "Upgrade_ClanLangbarte")
    assert dwarven_realm_faction("FactionDwarves", _stats([pick])) == "Dwarves (Erebor)"
    fire = StatEvent(2.0, "upgrades", "Upgrade_ClanFeuerbarte")
    assert dwarven_realm_faction("FactionDwarves", _stats([fire])) == "Dwarves (Iron Hills)"
    broad = StatEvent(14.9, "upgrades", "Upgrade_ClanBreitschultern")
    assert dwarven_realm_faction("FactionDwarves", _stats([broad])) == "Dwarves (Ered Luin)"

    # Non-dwarves pass through untouched, whatever they research.
    assert dwarven_realm_faction("FactionMen", _stats([pick])) == "FactionMen"
    # The realm choice is permanent, so a late clan pick still identifies the realm - players
    # routinely take up to a minute to click their free clan at the citadel.
    late = StatEvent(47.0, "upgrades", "Upgrade_ClanLangbarte")
    assert dwarven_realm_faction("FactionDwarves", _stats([late])) == "Dwarves (Erebor)"
    # The first clan upgrade wins (there is no re-pick in-game anyway).
    two = [StatEvent(18.0, "upgrades", "Upgrade_ClanFeuerbarte"), late]
    assert dwarven_realm_faction("FactionDwarves", _stats(two)) == "Dwarves (Iron Hills)"
    # No clan upgrade at all (an unknowable realm) is marked unresolved, to be dropped.
    assert dwarven_realm_faction("FactionDwarves", _stats([])) == "?"

    # The stats-only refiner ignores the game/map arguments it is handed as a FactionRefiner.
    assert (
        dwarven_realm_faction("FactionDwarves", _stats([pick]), None, "maps/x")
        == "Dwarves (Erebor)"
    )


class _FakeData:
    """The slice of GameData the Gondor refiner consults: the FactionMen registration index
    and the per-map hero roster its map.ini declares (keyed by map file here)."""

    def __init__(self, rosters_by_map):
        self.faction_names = ["FactionCivilian", "FactionMen", "FactionDwarves"]
        self._rosters_by_map = rosters_by_map

    def hero_roster_for(self, map_file, faction_id):
        assert self.faction_names[faction_id] == "FactionMen"
        return self._rosters_by_map.get(map_file, [])


def test_gondor_variant_refiner():
    assert set(GONDOR_VARIANTS.values()) == {"Arnor", "Belfalas"}

    stats = _stats([])
    data = _FakeData(
        {
            "maps/map edain arnor kaltfelsen": ["CreateAHero", "ArnorCaptainStealthless_mod"],
            "maps/map edain linhir": ["CreateAHero", "AmrothAmrothos", "AmrothElphir"],
            "maps/map edain minas tirith": ["CreateAHero", "GondorBoromir_mod"],
        }
    )
    # The map's Gondor roster names the sub-faction: an Arnor captain, an Amrothos, or neither.
    assert (
        gondor_variant_faction("FactionMen", stats, data, "maps/map edain arnor kaltfelsen")
        == "Arnor"
    )
    assert gondor_variant_faction("FactionMen", stats, data, "maps/map edain linhir") == "Belfalas"
    assert (
        gondor_variant_faction("FactionMen", stats, data, "maps/map edain minas tirith") == "Gondor"
    )
    # A map with no FactionMen roster override (or an unknown map) is plain Gondor.
    assert gondor_variant_faction("FactionMen", stats, data, "maps/vanilla") == "Gondor"

    # Every other faction passes through untouched, whatever the map declares.
    assert (
        gondor_variant_faction("FactionDwarves", stats, data, "maps/map edain linhir")
        == "FactionDwarves"
    )
    # No game/map context (the stats-only call form) leaves the label untouched.
    assert gondor_variant_faction("FactionMen", stats, None, None) == "FactionMen"


def test_edain_refiner_composes_both_splits():
    data = _FakeData({"maps/map edain linhir": ["CreateAHero", "AmrothAmrothos"]})
    # Men are split by the map's Gondor roster...
    assert (
        edain_faction_refiner("FactionMen", _stats([]), data, "maps/map edain linhir") == "Belfalas"
    )
    # ...and Dwarves by the opening clan upgrade, in the one refiner.
    clan = StatEvent(0.4, "upgrades", "Upgrade_ClanLangbarte")
    assert (
        edain_faction_refiner("FactionDwarves", _stats([clan]), data, "maps/x")
        == "Dwarves (Erebor)"
    )
    # An unrelated faction is unchanged.
    assert edain_faction_refiner("FactionMordor", _stats([]), data, "maps/x") == "FactionMordor"


def test_lichtbringer_recruits_are_the_element_hordes():
    # The four toggle powers cover all four elements.
    assert set(LICHTBRINGER_ELEMENTS.values()) == {"Earth", "Light", "Water", "Air"}
    # Each toggle fields the element-specific Loremaster horde it selects (Light -> the "Feuer"
    # horde: the internal German name and the player-facing element diverge).
    assert LICHTBRINGER_RECRUITS == {
        "SpecialAbilityAngmarThrallMasterSummonRhudaurSlingers": "BruchtalLichtbringerErdeHorde",
        "SpecialAbilityAngmarThrallMasterSummonOrc": "BruchtalLichtbringerFeuerHorde",
        "SpecialAbilityAngmarThrallMasterSummonWolfRiders": "BruchtalLichtbringerWasserHorde",
        "SpecialAbilityAngmarThrallMasterSummonRhudaurSpearmen": "BruchtalLichtbringerLuftHorde",
    }


def test_edain_power_recruits_lichtbringer_gates_on_imladris():
    shared = "SpecialAbilityAngmarThrallMasterSummonOrc"  # the Lichtbringer "Light" (Feuer) toggle
    # An Imladris caster: the toggle fields its element-specific Loremaster horde.
    assert edain_power_recruits("Imladris", [], shared) == ("BruchtalLichtbringerFeuerHorde",)
    # The same power cast by a Side without a conversion table fields nothing here (a
    # Rohan/Lothlorien peasant toggle is reversible, not a fielding).
    assert edain_power_recruits("Mordor", [], shared) == ()
    assert edain_power_recruits("Lothlorien", [], shared) == ()
    assert edain_power_recruits(None, [], shared) == ()


def test_edain_power_recruits_angmar_splits_on_the_buttons_options_bits():
    # An Angmar cast of a shared ThrallMaster power is a real conversion of one of two units:
    # the firing button's Options bitfield (the cast's second Integer) carries the SiegeTroll
    # buttons' MULTI bits for a siege build and not for a ThrallMaster summon.
    thrall_options = 0x40000000 | 0x1000000  # ON_GROUND_ONLY | TOGGLE_IMAGE_ON_WEAPONSET
    troll_options = thrall_options | 0x100000 | 0x100  # + OK_FOR_MULTI_EXECUTE|_SELECT
    shared = "SpecialAbilityAngmarThrallMasterSummonOrc"
    assert edain_power_recruits("Angmar", [], shared, thrall_options) == ("AngmarOrcWarriors",)
    assert edain_power_recruits("Angmar", [], shared, troll_options) == ("AngmarBatteringRam",)
    assert edain_power_recruits(
        "Angmar", [], "SpecialAbilityAngmarThrallMasterSummonWolfRiders", troll_options
    ) == ("AngmarTrollSling",)
    assert edain_power_recruits(
        "Angmar", [], "SpecialAbilityAngmarThrallMasterSummonRhudaurSpearmen", troll_options
    ) == ("AngmarSiegeTower",)
    # The slingers power has no SiegeTroll button, so MULTI-bit casts of it field nothing.
    assert (
        edain_power_recruits(
            "Angmar", [], "SpecialAbilityAngmarThrallMasterSummonRhudaurSlingers", troll_options
        )
        == ()
    )
    assert edain_power_recruits(
        "Angmar", [], "SpecialAbilityAngmarThrallMasterSummonRhudaurSlingers", thrall_options
    ) == ("AngmarRhudaurSlingers",)
    # The Black Guard's dedication power is ThrallMaster-specific but flows the same way.
    assert edain_power_recruits(
        "Angmar", [], "SpecialAbilityAngmarThrallMasterSummonOrkSchlachter", thrall_options
    ) == ("AngmarOrkSchlachterHorde",)
    # An Imladris toggle is unaffected by whatever bits its button carries.
    assert edain_power_recruits("Imladris", [], shared, thrall_options) == (
        "BruchtalLichtbringerFeuerHorde",
    )


def test_edain_power_recruits_hauptmann_summons_gate_on_rohan():
    # The Hauptmann (Herold) powers are Hauptmann-specific, so the power name alone names the
    # Getreue horde; only a Rohan caster fields it.
    assert edain_power_recruits("Rohan", [], "SpecialAbilityHeroldSummonWestfoldWachter") == (
        "GetreueSchwertHordeHauptmann",
    )
    assert edain_power_recruits("Rohan", [], "SpecialAbilityHeroldSummonWestfoldSpearmen") == (
        "GetreueSpeerHordeHauptmann",
    )
    assert edain_power_recruits("Rohan", [], "SpecialAbilityHeroldSummonIsenfurtReiterHorde") == (
        "GetreueReiterHordeHauptmann",
    )
    assert edain_power_recruits("Angmar", [], "SpecialAbilityHeroldSummonWestfoldWachter") == ()


def test_edain_upgrade_recruits_dedications():
    # The dominant conversion path: the dedication research's DoCommandUpgrade fires the summon
    # engine-side, so the 0x415 purchase is the recruit signal - Side-gated like the powers.
    assert edain_upgrade_recruits("Angmar", "Upgrade_ThrallMasterOrcWarriors") == (
        "AngmarOrcWarriors",
    )
    assert edain_upgrade_recruits("Angmar", "Upgrade_ThrallMasterWolfRiders") == (
        "AngmarWolfRiders",
    )
    assert edain_upgrade_recruits("Angmar", "Upgrade_ThrallMasterRhudaurSpearmen") == (
        "AngmarRhudaurSpearmen",
    )
    assert edain_upgrade_recruits("Angmar", "Upgrade_ThrallMasterRhudaurSlingers") == (
        "AngmarRhudaurSlingers",
    )
    assert edain_upgrade_recruits("Angmar", "Upgrade_ThrallMasterOrksBergGram") == (
        "AngmarOrkSchlachterHorde",
    )
    assert edain_upgrade_recruits("Rohan", "Upgrade_HeroldRohanWestfoldWachter") == (
        "GetreueSchwertHordeHauptmann",
    )
    assert edain_upgrade_recruits("Rohan", "Upgrade_HeroldRohanWestfoldSpearmen") == (
        "GetreueSpeerHordeHauptmann",
    )
    assert edain_upgrade_recruits("Rohan", "Upgrade_HeroldIsenfurtReiterHorde") == (
        "GetreueReiterHordeHauptmann",
    )
    # Wrong Side or an unmapped upgrade fields nothing.
    assert edain_upgrade_recruits("Rohan", "Upgrade_ThrallMasterOrcWarriors") == ()
    assert edain_upgrade_recruits("Angmar", "Upgrade_HeroldRohanWestfoldWachter") == ()
    assert edain_upgrade_recruits("Angmar", "Upgrade_ForgedBlades") == ()
    assert edain_upgrade_recruits(None, "Upgrade_ThrallMasterOrcWarriors") == ()


def test_ignored_recruits_drops_the_elementless_placeholder():
    # The elementless Loremaster horde is dropped from the normal recruit stream: its element -
    # and so its recruit row - only becomes known from the toggle cast tracked above.
    assert IGNORED_RECRUITS == {"BruchtalLichtbringerHorde"}
    # The element-specific hordes the toggles field are not ignored (they are the recruit rows).
    for horde in LICHTBRINGER_RECRUITS.values():
        assert horde not in IGNORED_RECRUITS


def test_edain_power_recruits_mordor_summons():
    assert edain_power_recruits("Mordor", [], "SpellBookSBSummonEasterling") == (
        "MordorRhunSwordHorde",
        "MordorEasterlingHordeMod",
    )
    # Mumakil once, the rider horde twice.
    assert edain_power_recruits("Mordor", [], "SpellBookSBSummonHaradrim") == (
        "MordorMumakil",
        "MordorHaradrimRiderHordeMod",
        "MordorHaradrimRiderHordeMod",
    )


def test_edain_power_recruits_dorwinion_calls():
    # The two Loyal Protectors tiers field a Dorwinion sword/bow mix; the second tier doubles it.
    assert edain_power_recruits("Dwarves", [], "SpecialAbilityLoyalProtectors") == (
        "DwarvenDorwinionSwordmanHorde",
        "DwarvenDorwinionBowmanHorde",
    )
    assert edain_power_recruits("Dwarves", [], "SpecialAbilityLoyalProtectors2") == (
        "DwarvenDorwinionSwordmanHorde",
        "DwarvenDorwinionSwordmanHorde",
        "DwarvenDorwinionBowmanHorde",
        "DwarvenDorwinionBowmanHorde",
    )
    # Fist of Dorwinion fields the Purple Guard horde.
    assert edain_power_recruits("Dwarves", [], "SpecialAbilityFistOfDorwinion") == (
        "DwarvenDorwinionPurpleGuardHorde",
    )


def test_edain_power_recruits_gates_on_side():
    # One SpecialPower definition can serve several factions in Edain - a non-Mordor cast of a
    # Mordor summon, a non-Dwarves cast of a Dorwinion call, or a non-Men cast of a Leuchtfeuer
    # power, fields nothing.
    for power in POWER_RECRUITS:
        assert edain_power_recruits("Isengard", [], power) == ()
    for power in DORWINION_RECRUITS:
        assert edain_power_recruits("Isengard", [], power) == ()
    for power in LEUCHTFEUER_RECRUITS:
        assert edain_power_recruits("Isengard", [], power) == ()


def test_edain_power_recruits_leuchtfeuer_reads_the_map_roster():
    # Gondor and Belfalas fire the same power definitions; only the caster's per-map Gondor
    # roster (the same marker gondor_variant_faction reads) tells them apart.
    belfalas_roster = ["CreateAHero", "AmrothAmrothos", "AmrothElphir"]
    assert edain_power_recruits("Men", belfalas_roster, "SpecialAbilityLeuchtfeuerRingVale") == (
        "LamedonSwordsmenHorde",
        "LamedonSwordsmenHorde",
    )
    # Without the Belfalas marker (Arnor's roster, or plain Gondor) it defaults to Gondor.
    assert edain_power_recruits("Men", [], "SpecialAbilityLeuchtfeuerRingVale") == (
        "RingValeSwordsmanHorde",
        "RingValeSwordsmanHorde",
    )
    # The all-in-one call fields all four regions' hordes at once.
    assert edain_power_recruits("Men", [], "SpecialAbilityLeuchtfeuerLehen") == (
        "RingValeSwordsmanHorde",
        "LehenLossarnachAxteHorde",
        "MorthondBowmenHorde",
        "PelegirSpearmenHorde",
    )
    assert edain_power_recruits("Men", belfalas_roster, "SpecialAbilityLeuchtfeuerLehen") == (
        "LamedonSwordsmenHorde",
        "LehenNimrassimRavensHorde",
        "AndrastArcherHorde",
        "TolFalasSpearmenHorde",
    )


def test_edain_power_recruits_unmapped_power():
    assert edain_power_recruits("Mordor", [], "SpecialAbilityForcePush") == ()
    assert edain_power_recruits("Men", [], "SpecialAbilityForcePush") == ()
    assert edain_power_recruits(None, [], "SpecialAbilityForcePush") == ()


def test_replay_aggregate_injects_the_edain_set():
    parser = argparse.ArgumentParser()
    add_aggregate_command(
        parser.add_subparsers(),
        name="replay-aggregate",
        tracked_upgrades=TRACKED_UPGRADES,
        refine_faction=edain_faction_refiner,
        power_recruits=edain_power_recruits,
        upgrade_recruits=edain_upgrade_recruits,
        ignore_recruits=IGNORED_RECRUITS,
    )
    args = parser.parse_args(["replay-aggregate", "replays", "--game", "root"])
    assert args.tracked_upgrades == TRACKED_UPGRADES
    assert args.refine_faction is edain_faction_refiner
    assert args.power_recruits is edain_power_recruits
    assert args.upgrade_recruits is edain_upgrade_recruits
    assert args.ignore_recruits is IGNORED_RECRUITS
    # --track-upgrade / --track-power extend the injected sets at run time (see
    # _run_aggregate); here just check the flags parse alongside the injection.
    args = parser.parse_args(
        [
            "replay-aggregate",
            "replays",
            "--game",
            "root",
            "--track-upgrade",
            "Upgrade_X",
            "--track-power",
            "Power_Y",
        ]
    )
    assert args.track_upgrade == ["Upgrade_X"]
    assert args.track_power == ["Power_Y"]
