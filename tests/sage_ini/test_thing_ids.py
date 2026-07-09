"""Validate the engine ThingTemplate order against a real BFME2 install (full-marked).

Two anchor sets, both recorded from controlled BFME2 replays: `ANCHORS` are recruit ids (`0x417`,
one unit per faction, `Replay 2`, ids 2002–2863); `BUILD_ANCHORS` are build ids (`0x41A`, one
structure per faction, `Replay 4`) - the finished-building template mapped to its build integer.
Both spaces are the same `thing_template_order` index + 1, so every anchor must land at
`thing_template_order(...).index(name) + 1`. The build anchors in particular pin the engine's
`INI::loadDirectory` two-pass file order (an earlier files-before-subdirs walk put the structures
2–3 ids late). Skips when no BFME2 tree is configured (`bfme2=` in `tests/corpus_roots.txt`).
"""

from pathlib import Path

import pytest

from sage_ini.stats import ini_root
from sage_ini.subsystems import thing_template_order
from tests.conftest import corpus_roots

pytestmark = pytest.mark.full

# replay object id → BFME2 template (recruited unit), spanning all six factions.
ANCHORS = {
    2002: "IsengardFighterHorde",
    2004: "IsengardPikemanHorde",
    2010: "IsengardUrukCrossbowHorde",
    2011: "IsengardWargRiderHorde",
    2012: "MordorFighterHorde",
    2014: "MordorArcherHorde",
    2019: "MordorCorsairsOfUmbarHorde",
    2025: "MordorEasterlingHorde",
    2027: "GoblinFighterHorde",
    2029: "GoblinArcherHorde",
    2032: "WildSpiderlingHorde",
    2216: "IsengardBatteringRam",
    2218: "MordorBatteringRam",
    2219: "IsengardBeserker",
    2239: "MordorAttackTroll",
    2241: "MordorCatapult",
    2247: "MordorDrummerTroll",
    2276: "MordorMountainTroll",
    2291: "GoblinCaveTroll",
    2502: "DwarvenGuardianHorde",
    2503: "DwarvenAxeThrowerHorde",
    2504: "DwarvenPhalanxHorde",
    2514: "ElvenMirkwoodArcherHorde",
    2515: "ElvenRivendellLancerHorde",
    2516: "ElvenLorienWarriorHorde",
    2517: "ElvenMithlondSentryHorde",
    2519: "ElvenLorienArcherHorde",
    2520: "GondorFighterHorde",
    2523: "GondorTowerShieldGuardHorde",
    2526: "GondorArcherHorde",
    2528: "GondorRangerHorde",
    2531: "GondorKnightHorde",
    2533: "RohanRohirrimHorde",
    2755: "DwarvenDemolisher",
    2801: "RohanGenericEnt",
    2863: "GondorTrebuchet",
}

# build id (0x41A integer) → finished-building template, one structure per faction (`Replay 4`).
# Includes the Wild/Goblin buildings whose id already matched (gap 0) as controls, plus Men (+2)
# and Elven/Dwarven/Isengard/Mordor (+3) structures that only land right under the two-pass order.
BUILD_ANCHORS = {
    2181: "WildMineShaft",
    2185: "WildTreasureTrove",
    2154: "GoblinCave",
    2155: "GoblinFissure",
    2184: "WildSpiderPit",
    2549: "DwarfBarracks",
    2567: "DwarvenStatue",
    2568: "DwarvenArcheryRange",
    2080: "IsengardSiegeWorks",
    2091: "IsengardWargPit",
    2092: "IsengardWargSentry",
    2090: "IsengardUrukPit",
    2632: "GondorArcherRange",
    2634: "GondorBarracks",
    2724: "GondorWell",
    2698: "GondorForge",
    2038: "MordorHaradrimPalace",
    2139: "MordorTavern",
    2039: "MordorMumakilPen",
    2147: "MordorTrollCage",
    2626: "EregionForge",
    2627: "ElvenMirrorOfGaladriel",
    2611: "ElvenFortress",
    2604: "ElvenEntMoot",
    2623: "ElvenStatue",
}

# A file unique to a vanilla BFME2 object tree, used to pick the right corpus root.
_MARKER = "object/goodfaction/hordes/elven/elvenhordes.ini"


def _bfme2_root() -> Path | None:
    for root in corpus_roots().values():
        base = ini_root(root)
        if (base / "default" / "subsystemlegend.ini").is_file() and (base / _MARKER).is_file():
            return root
    return None


@pytest.mark.parametrize("anchors", [ANCHORS, BUILD_ANCHORS], ids=["recruit", "build"])
def test_ids_match_registration_order(anchors):
    root = _bfme2_root()
    if root is None:
        pytest.skip("no BFME2 corpus root (set bfme2=<path> in tests/corpus_roots.txt)")
    index = {name: i for i, name in enumerate(thing_template_order(root))}
    mismatches = {
        rid: (template, index.get(template))
        for rid, template in anchors.items()
        if index.get(template) != rid - 1
    }
    assert not mismatches, f"replay id != registration index + 1 for: {mismatches}"
