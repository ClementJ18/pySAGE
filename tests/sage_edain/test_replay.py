"""The Edain replay overlay: the tracked-upgrade set, the dwarven-realm faction refiner,
and their injection into the shared aggregate CLI command."""

import argparse

from sage_edain.replay import (
    DWARVEN_REALMS,
    LICHTBRINGER_ELEMENTS,
    TRACKED_UPGRADES,
    dwarven_realm_faction,
    lichtbringer_power_label,
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


def test_lichtbringer_power_label_is_faction_aware():
    # The four toggle powers cover all four elements.
    assert set(LICHTBRINGER_ELEMENTS.values()) == {"Earth", "Light", "Water", "Air"}

    shared = "SpecialAbilityAngmarThrallMasterSummonOrc"  # the Lichtbringer "Light" toggle
    # An Imladris caster: read the shared power as the element it selects.
    assert lichtbringer_power_label("Imladris", shared) == "Lichtbringer -> Light"
    # The same power cast by any other faction stays raw (Angmar fires it to summon Orcs).
    assert lichtbringer_power_label("Angmar", shared) == shared
    assert lichtbringer_power_label("Mordor", shared) == shared
    assert lichtbringer_power_label(None, shared) == shared
    # A power outside the map is untouched even for Imladris.
    other = "SpecialAbilityForcePush"
    assert lichtbringer_power_label("Imladris", other) == other


def test_replay_aggregate_injects_the_edain_set():
    parser = argparse.ArgumentParser()
    add_aggregate_command(
        parser.add_subparsers(),
        name="replay-aggregate",
        tracked_upgrades=TRACKED_UPGRADES,
        refine_faction=dwarven_realm_faction,
        relabel_power=lichtbringer_power_label,
    )
    args = parser.parse_args(["replay-aggregate", "replays", "--game", "root"])
    assert args.tracked_upgrades == TRACKED_UPGRADES
    assert args.refine_faction is dwarven_realm_faction
    assert args.relabel_power is lichtbringer_power_label
    # --track-upgrade extends the injected set at run time (see _run_aggregate); here just
    # check the flag parses alongside the injection.
    args = parser.parse_args(
        ["replay-aggregate", "replays", "--game", "root", "--track-upgrade", "Upgrade_X"]
    )
    assert args.track_upgrade == ["Upgrade_X"]
