"""The Edain faction ownership graph (sage_edain).

Fast tests build a tiny synthetic game and exercise the whole walk through the single-structure
start-point path (no `.bse`/sagemap needed). A `--full`-gated acceptance test builds Gondor from
the Edain corpus when it is present.
"""

import http.server
import json
import threading
import urllib.request
from functools import partial
from pathlib import Path

import pytest

import sage_ini.model.definitions  # noqa: F401  (register model classes)
from sage_edain import (
    StartPointKind,
    StructureRole,
    build_faction_graph,
    build_faction_graphs,
    find_faction,
    playable_factions,
)
from sage_edain.__main__ import _payload
from sage_edain.__main__ import main as cli_main
from sage_edain.diff import diff_graphs, format_mod_diff
from sage_edain.report import _clean, render_report, render_roster_table
from sage_edain.server import _Handler
from sage_ini.loader import load_game
from sage_ini.model.game import Game
from sage_ini.parser.blockparser import parse
from sage_utils.factiongraph.bases import BaseLayout, find_base_file, resolve_base_layout
from sage_utils.views import recruited_hero_names

# A faction whose settlement flag drops a single citadel; the citadel constructs a barracks that
# trains a soldier, recruits two heroes by REVIVE index (the second locked behind NEED_UPGRADE) and
# researches an upgrade. A second flag unpacks a foreign-side structure to exercise the Side filter.
FIXTURE = """
PlayerTemplate FactionTest
    PlayableSide = Yes
    Side = TestSide
    BuildableHeroesMP = TestHero1 TestHero2
    SpellBookMp = TestSpellBook
End

Object TestSpellBook
    CommandSet = TestSpellBookCS
    Behavior = OCLSpecialPower ModuleTag_Summon
        SpecialPowerTemplate = SpecialPowerTest
        OCL = OCL_TestSummon
    End
End
CommandSet TestSpellBookCS
    1 = Command_TestPower
End
CommandButton Command_TestPower
    Command = SPELL_BOOK
    SpecialPower = SpecialPowerTest
End
SpecialPower SpecialPowerTest
    ReloadTime = 30000
End
ObjectCreationList OCL_TestSummon
    CreateObject
        ObjectNames = TestSummonedUnit
        Count       = 1
    End
End
Object TestSummonedUnit
    KindOf = INFANTRY
End

Object TestSettlementFlag
    Behavior = CastleBehavior ModuleTag_Castle
        CastleToUnpackForFaction = TestSide TestCitadel 500
    End
End

Object TestCitadel
    Side = TestSide
    KindOf = STRUCTURE CASTLE_KEEP
    CommandSet = TestCitadelCS
End
CommandSet TestCitadelCS
    1 = Command_BuildBarracks
    2 = Command_ReviveHero1
    3 = Command_ReviveHero2
    4 = Command_ResearchUpgrade
    5 = Command_BuildHouse
End
CommandButton Command_BuildBarracks
    Command = FOUNDATION_CONSTRUCT
    Object = TestBarracks
End
CommandButton Command_BuildHouse
    Command = FOUNDATION_CONSTRUCT
    Object = TestHouse
End

; A build shell: no Body, only BuildVariations. Its real command set lives on the variation.
Object TestHouse
    Side = TestSide
    KindOf = STRUCTURE
    CommandSet = TestHouseShellCS
    BuildVariations = TestHouse01
End
CommandSet TestHouseShellCS
    1 = Command_HouseSell
End
CommandButton Command_HouseSell
    Command = SELL
End
Object TestHouse01
    Side = TestSide
    KindOf = STRUCTURE
    CommandSet = TestHouseRealCS
    Body = StructureBody ModuleTag_Body
        MaxHealth = 100
    End
End
CommandSet TestHouseRealCS
    1 = Command_ResearchHouseUpgrade
End
CommandButton Command_ResearchHouseUpgrade
    Command = OBJECT_UPGRADE
    Upgrade = Upgrade_House
End
Upgrade Upgrade_House
End
CommandButton Command_ReviveHero1
    Command = REVIVE
End
CommandButton Command_ReviveHero2
    Command = REVIVE
    Options = NEED_UPGRADE
End
CommandButton Command_ResearchUpgrade
    Command = OBJECT_UPGRADE
    Upgrade = Upgrade_Test
End

Object TestBarracks
    Side = TestSide
    KindOf = STRUCTURE
    CommandSet = TestBarracksCS
End
CommandSet TestBarracksCS
    1 = Command_TrainSoldier
End
CommandButton Command_TrainSoldier
    Command = UNIT_BUILD
    Object = TestSoldier
End

Object TestSoldier
    KindOf = INFANTRY
    WeaponSet
        Conditions = None
        Weapon = PRIMARY TestSoldierSword
    End
End
Weapon TestSoldierSword
    DamageNugget
        Damage = 20
        DamageType = SLASH
    End
    DamageNugget
        Damage = 10
        DamageType = SLASH
        RequiredUpgradeNames = Upgrade_Test
    End
End
Object TestHero1
End
Object TestHero2
End
Upgrade Upgrade_Test
End

Object OtherSettlementFlag
    Behavior = CastleBehavior ModuleTag_Castle
        CastleToUnpackForFaction = TestSide OtherStructure 300
    End
End
Object OtherStructure
    Side = OtherSide
    KindOf = STRUCTURE
End

Object TestEconomyFlag
    Side = TestSide
    KindOf = STRUCTURE BASE_FOUNDATION
    CommandSet = TestEconomyDefaultCS
    Behavior = CommandSetUpgrade ModuleTag_FactionEconomy
        TriggeredBy = Upgrade_TestSideFaction
        CommandSet  = TestEconomyFactionCS
    End
    Behavior = CastleBehavior ModuleTag_Castle
        CastleToUnpackForFaction = TestSide TestFarmBase 0
    End
End
CommandSet TestEconomyDefaultCS
    1 = Command_UnpackEconomy
End
CommandButton Command_UnpackEconomy
    Command = CASTLE_UNPACK
End
CommandSet TestEconomyFactionCS
    1 = Command_BuildFarm
End
CommandButton Command_BuildFarm
    Command = CASTLE_UNPACK_EXPLICIT_OBJECT
    Object = TestFarm
End
Object TestFarm
    Side = TestSide
    KindOf = STRUCTURE
End
"""


def load(text: str) -> Game:
    game = Game()
    result = parse(text, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    return game


# The synthetic flags aren't the canonical three, so the fixture names them explicitly (the same
# `start_flags` seam the production default `_START_FLAGS` uses).
_FIXTURE_FLAGS = ("TestSettlementFlag", "OtherSettlementFlag", "TestEconomyFlag")


@pytest.fixture
def graph():
    game = load(FIXTURE)
    faction = find_faction(game, "TestSide")
    assert faction is not None
    return build_faction_graph(game, faction, start_flags=_FIXTURE_FLAGS)


def test_find_faction_by_side_and_name():
    game = load(FIXTURE)
    assert find_faction(game, "TestSide").name == "FactionTest"
    assert find_faction(game, "FactionTest").name == "FactionTest"
    assert find_faction(game, "Nope") is None
    assert [f.name for f in playable_factions(game)] == ["FactionTest"]


def test_graph_identity_and_spellbook(graph):
    assert graph.name == "FactionTest"
    assert graph.side == "TestSide"
    assert graph.spellbook is not None
    assert graph.spellbook.name == "TestSpellBook"
    powers = {p.name: p for p in graph.spellbook.powers}
    assert "SpecialPowerTest" in powers
    assert powers["SpecialPowerTest"].cooldown == 30.0  # 30000 ms -> 30 s


def test_spellbook_power_resolves_summon(graph):
    # The spellbook power's OCLSpecialPower resolves to the object it creates, with a "summon" kind.
    power = next(p for p in graph.spellbook.powers if p.name == "SpecialPowerTest")
    assert power.kind == "summon"
    assert "TestSummonedUnit" in [name for name, _display in power.creates]
    assert power.to_dict()["creates"][0]["name"] == "TestSummonedUnit"


def test_created_object_is_navigable(graph):
    # An object a power creates (not built/recruited) becomes its own node with a profile, so the
    # power's link resolves to a real page.
    assert "TestSummonedUnit" in graph.created
    node = graph.created["TestSummonedUnit"]
    assert node.profile is not None
    assert "TestSummonedUnit" in graph.to_dict()["created"]


def test_start_point_single_structure_and_side_filter(graph):
    # The TestSide-owned settlement flag is a start point; the flag unpacking a foreign-side
    # structure is filtered out even though it lists a TestSide row.
    points = {p.flag: p for p in graph.start_points}
    assert "TestSettlementFlag" in points
    assert "OtherSettlementFlag" not in points
    point = points["TestSettlementFlag"]
    assert point.kind is StartPointKind.SETTLEMENT
    assert point.structure == "TestCitadel"
    assert point.cost == 500.0
    assert "OtherStructure" not in graph.structures


def test_economy_plot_faction_commandset_and_explicit_unpack(graph):
    # The economy plot flag is a BASE_FOUNDATION, so it is walked; its faction CommandSetUpgrade
    # (triggered by Upgrade_TestSideFaction) swaps in the command set whose
    # CASTLE_UNPACK_EXPLICIT_OBJECT button drops the farm.
    assert "TestEconomyFlag" in graph.structures
    assert "TestFarm" in graph.structures
    assert graph.structures["TestFarm"].role is StructureRole.FOUNDATION_BUILDING


def test_structure_walk_reaches_foundation_building(graph):
    # The citadel constructs the barracks (FOUNDATION_CONSTRUCT), which is walked into and trains
    # the soldier (UNIT_BUILD).
    assert "TestCitadel" in graph.structures
    assert "TestBarracks" in graph.structures
    assert graph.structures["TestBarracks"].role is StructureRole.FOUNDATION_BUILDING
    assert "TestSoldier" in graph.units


def test_unit_carries_producer_edge(graph):
    soldier = graph.units["TestSoldier"]
    assert [(p.structure, p.button) for p in soldier.producers] == [
        ("TestBarracks", "Command_TrainSoldier")
    ]


def test_unit_has_profile(graph):
    # Every produced unit carries a stat profile (mirrors sage_ui), serialisable to JSON.
    soldier = graph.units["TestSoldier"]
    assert soldier.profile is not None
    data = soldier.profile.to_dict()
    assert set(data) >= {"health", "speed", "weapons", "defenses", "abilities"}


def test_hero_recruit_index_skips_need_upgrade(graph):
    # REVIVE slots map by index onto BuildableHeroesMP; the second hero's button is NEED_UPGRADE.
    assert "TestHero1" in graph.heroes
    assert "TestHero2" not in graph.heroes
    assert [p.structure for p in graph.heroes["TestHero1"].producers] == ["TestCitadel"]


def test_upgrade_is_researchable(graph):
    assert "Upgrade_Test" in graph.upgrades
    assert graph.upgrades["Upgrade_Test"].producers[0].structure == "TestCitadel"


def test_upgrade_affects_names_the_gated_unit(graph):
    # TestSoldier's second weapon nugget is gated on Upgrade_Test, so the upgrade's `affects`
    # names it; the house upgrade gates nothing in the roster, so its list stays empty.
    affected = [name for name, _display in graph.upgrades["Upgrade_Test"].affects]
    assert affected == ["TestSoldier"]
    assert graph.upgrades["Upgrade_House"].affects == []
    assert graph.to_dict()["upgrades"]["Upgrade_Test"]["affects"] == [
        {"name": "TestSoldier", "display": "TestSoldier"}
    ]


def test_report_upgrades_table_lists_affects(graph):
    report = render_report(graph)
    lines = [line for line in report.splitlines() if "Upgrade_Test" in line and "|" in line]
    assert lines and "TestSoldier" in lines[0]


def test_build_shell_resolves_variation(graph):
    # TestHouse is a build shell (no Body, only BuildVariations); its real command set lives on
    # TestHouse01, so its researched upgrade is read from there and the variation is recorded.
    assert "TestHouse" in graph.structures
    assert graph.structures["TestHouse"].variation == "TestHouse01"
    assert "Upgrade_House" in graph.upgrades
    assert graph.upgrades["Upgrade_House"].producers[0].structure == "TestHouse"


def test_recruited_hero_names_matches_graph():
    game = load(FIXTURE)
    assert recruited_hero_names(game, game.objects["TestCitadel"]) == ["TestHero1"]


def test_build_faction_graphs_covers_all_playable():
    game = load(FIXTURE)
    graphs = build_faction_graphs(game)
    assert [g.name for g in graphs] == ["FactionTest"]


class TestFactionDiff:
    """Faction-level changelog between two versions (sage_edain.diff)."""

    def _graphs(self, text: str):
        game = load(text)
        faction = find_faction(game, "TestSide")
        return [build_faction_graph(game, faction, start_flags=_FIXTURE_FLAGS)]

    def test_identical_versions_are_empty(self):
        diff = diff_graphs(self._graphs(FIXTURE), self._graphs(FIXTURE))
        assert diff.is_empty()
        assert "No faction-level differences" in format_mod_diff(diff, "a", "b")

    def test_stat_and_roster_changes_are_reported(self):
        # New version: the upgrade gets a cost, the soldier's sword hits harder, and the
        # barracks trains a second unit.
        new_text = (
            FIXTURE.replace(
                "Upgrade Upgrade_Test\nEnd",
                "Upgrade Upgrade_Test\n    BuildCost = 300\nEnd",
            )
            .replace(
                "CommandSet TestBarracksCS\n    1 = Command_TrainSoldier\nEnd",
                "CommandSet TestBarracksCS\n"
                "    1 = Command_TrainSoldier\n"
                "    2 = Command_TrainArcher\n"
                "End\n"
                "CommandButton Command_TrainArcher\n"
                "    Command = UNIT_BUILD\n"
                "    Object = TestArcher\n"
                "End\n"
                "Object TestArcher\n"
                "    KindOf = INFANTRY\n"
                "End",
            )
            .replace("Damage = 20", "Damage = 30")
        )

        diff = diff_graphs(self._graphs(FIXTURE), self._graphs(new_text))
        assert not diff.is_empty()
        (faction,) = diff.factions_changed

        assert [name for name, _ in faction.units.added] == ["TestArcher"]
        (changed_upgrade,) = faction.upgrades.changed
        assert changed_upgrade.name == "Upgrade_Test"
        assert [(c.stat, c.old, c.new) for c in changed_upgrade.changes] == [("cost", 0, 300)]
        (changed_unit,) = faction.units.changed
        assert changed_unit.name == "TestSoldier"
        assert any(c.stat == "weapon damage" and c.new == 30.0 for c in changed_unit.changes)

        text = format_mod_diff(diff, "v1", "v2")
        assert "TestArcher" in text and "weapon damage 20 → 30" in text

        payload = diff.to_dict()
        (faction_payload,) = payload["factions_changed"]
        assert faction_payload["units"]["added"] == [
            {"name": "TestArcher", "display": "TestArcher"}
        ]

    def test_removed_faction_is_reported(self):
        no_faction = FIXTURE.replace("PlayableSide = Yes", "PlayableSide = No")
        game = load(no_faction)
        diff = diff_graphs(self._graphs(FIXTURE), build_faction_graphs(game))
        assert [name for name, _ in diff.factions_removed] == ["FactionTest"]


class TestSchemaCommand:
    def test_graph_schema_documents_every_model_class(self, capsys):
        assert cli_main(["schema"]) == 0
        out = capsys.readouterr().out
        for name in (
            "FactionGraph",
            "Spellbook",
            "StartPoint",
            "Structure",
            "ProducedUnit",
            "RecruitedHero",
            "ResearchableUpgrade",
            "Power",
            "Weapon",
            "Profile",
            "Producer",
            "CreatedObject",
        ):
            assert f"{name}:" in out
        assert "affects: [{name, display}]" in out
        assert '"castle" | "camp"' in out  # enums list their tokens

    def test_diff_schema_documents_the_changelog(self, capsys):
        assert cli_main(["schema", "diff"]) == 0
        out = capsys.readouterr().out
        assert "ModDiff:" in out and "RosterDiff:" in out and "StatChange:" in out


class TestDiffCommand:
    def _write(self, folder: Path, text: str) -> Path:
        folder.mkdir(exist_ok=True)
        (folder / "data.ini").write_text(text, encoding="utf-8")
        return folder

    def test_diff_command_json(self, tmp_path, capsys):
        # The CLI walks the canonical Edain start flags, which the synthetic fixture doesn't
        # use, so assert on a spellbook change — resolved regardless of start plots.
        old = self._write(tmp_path / "old", FIXTURE)
        new = self._write(
            tmp_path / "new", FIXTURE.replace("ReloadTime = 30000", "ReloadTime = 60000")
        )
        assert cli_main(["diff", "--json", str(old), str(new), "TestSide"]) == 0
        payload = json.loads(capsys.readouterr().out)
        (faction,) = payload["factions_changed"]
        (power,) = faction["spellbook"]["changed"]
        assert power["changes"] == [{"stat": "cooldown", "old": 30.0, "new": 60.0}]


def test_payload_single_vs_multi(graph):
    single = _payload([graph], all_factions=False)
    assert single["name"] == "FactionTest"  # a bare graph dict
    multi = _payload([graph], all_factions=True)
    assert list(multi) == ["factions"]  # the wrapper the UI turns into a picker
    assert multi["factions"][0]["name"] == "FactionTest"


def test_to_dict_is_json_safe(graph):
    data = graph.to_dict()
    json.dumps(data)  # StrEnum roles/kinds must serialize as plain strings
    assert data["start_points"][0]["kind"] == "settlement"


# The Markdown report is the agent-facing view: a single document covering every part of the graph.


def test_report_covers_every_section(graph):
    report = render_report(graph)
    assert report.startswith("# FactionTest - faction report")
    # Roster tally, then a section per part of the graph.
    assert "**Roster:** 5 structures - 1 units" in report
    assert "## Spellbook - TestSpellBook" in report
    assert "**SpecialPowerTest**" in report and "summons: TestSummonedUnit" in report
    assert "## Start points" in report
    assert "## Structures (5)" in report and "`TestBarracks`" in report
    # The unit/hero/upgrade tables list their leaves with a built-at column.
    assert "## Units (1)" in report and "| TestSoldier |" in report
    assert "## Heroes (1)" in report and "| TestHero1 |" in report
    assert "## Upgrades (2)" in report and "| Upgrade_Test |" in report


def test_report_is_pure_ascii(graph):
    # Rendered to stdout on a Windows console, so the template stays ASCII (display names may not).
    render_report(graph).encode("ascii")


def test_clean_collapses_engine_linebreaks():
    # In-game text uses literal "\n" markers and real newlines; both collapse to single spaces so a
    # description sits on one Markdown line.
    assert _clean("Repairs buildings \\n\\n Left click on\nthe target") == (
        "Repairs buildings Left click on the target"
    )


def test_roster_table_has_a_row_per_faction(graph):
    table = render_roster_table([graph])
    assert "| Faction | Side |" in table
    assert "| FactionTest | TestSide | 5 | 1 | 1 | 2 | 1 |" in table


# --- web UI server ---------------------------------------------------------------------------


def test_server_serves_ui_and_graph(graph):
    # The serve handler returns the bundled UI files and the graph at /graph.json.
    payload = json.dumps(graph.to_dict()).encode("utf-8")
    httpd = http.server.HTTPServer(("127.0.0.1", 0), partial(_Handler, graph_bytes=payload))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as response:
            assert response.status == 200
            assert b"sage_edain" in response.read()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/graph.json") as response:
            assert json.loads(response.read())["name"] == "FactionTest"
    finally:
        httpd.shutdown()
        httpd.server_close()


# --- base-layout resolver (no sagemap needed for these) --------------------------------------


def test_resolve_base_layout_without_bases_dir_is_empty():
    game = load(FIXTURE)
    layout = resolve_base_layout(game, None, "gondor_castle")
    assert layout == BaseLayout(name="gondor_castle")


def test_find_base_file_missing(tmp_path: Path):
    assert find_base_file(tmp_path, "nope") is None


def test_find_base_file_in_named_folder(tmp_path: Path):
    folder = tmp_path / "gondor_castle"
    folder.mkdir()
    bse = folder / "gondor_castle.bse"
    bse.write_bytes(b"")
    assert find_base_file(tmp_path, "gondor_castle") == bse


# --- corpus acceptance (full suite only) -----------------------------------------------------


def _edain_root() -> Path | None:
    roots_file = Path(__file__).resolve().parent / "corpus_roots.txt"
    if not roots_file.is_file():
        return None
    for line in roots_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        label, path = line.split("=", 1)
        if label.strip() == "edain":
            root = Path(path.strip())
            return root if root.is_dir() else None
    return None


@pytest.mark.full
def test_gondor_graph_against_corpus():
    root = _edain_root()
    if root is None:
        pytest.skip("Edain corpus root not present")
    # Load from the mod folder (root is .../_mod/data/ini) so the recursive scan picks up
    # _mod/Lotr.csv and display names / descriptions resolve.
    mod = root.parents[1]
    game = load_game(mod).game
    faction = find_faction(game, "Men")
    assert faction is not None
    graph = build_faction_graph(game, faction, mod / "bases")
    # Gondor's roster, recruitment and tech tree should all be linked from the start flags.
    assert "GondorArcherHorde" in graph.units
    assert "GondorKnightHorde" in graph.units
    assert "GondorBoromir_mod" in graph.heroes
    assert "Upgrade_TechnologyGondorForgedBlades" in graph.upgrades
    # The archer horde is recruited from the archer range it is constructed in.
    producers = {p.structure for p in graph.units["GondorArcherHorde"].producers}
    assert "GondorArcherRange" in producers
    # Base decomposition (needs sagemap) found the citadel keep.
    assert any(p.citadel == "GondorCastleBaseKeep" for p in graph.start_points)
    # Economy and expansion plots are start points; the faction CommandSetUpgrade + explicit-unpack
    # buttons surface their buildings, and the outpost recruits a fiefdom unit.
    flags = {p.flag for p in graph.start_points}
    assert {"WirtschaftPlotFlag_Real", "ExpansionPlotFlag"} <= flags
    assert "GondorFarm_Extern" in graph.structures  # via CASTLE_UNPACK_EXPLICIT_OBJECT
    assert "LehenLossarnachAxteHorde" in graph.units  # a fiefdom unit from the outpost
    # Each object carries its localized Description / RecruitText.
    assert "elite archers" in graph.units["GondorRangerHorde"].description
    # Stat profile mirrors sage_ui: the knight horde resolves its combat stats from the contained
    # rider (health + a melee attack), and a hero surfaces its abilities.
    knight = graph.units["GondorKnightHorde"].profile
    assert knight.health and knight.health > 0
    assert knight.weapons and knight.weapons[0].kind == "melee"
    boromir = graph.heroes["GondorBoromir_mod"].profile
    assert any(a.cooldown and a.cooldown >= 1 for a in boromir.abilities)
    # Special powers resolve their effect: a spellbook summon links the objects it creates,
    # and a hero ability surfaces the stat buff it grants.
    eagles = next(p for p in graph.spellbook.powers if p.name == "SpellBookAdler")
    assert "Gwaihir" in [display for _name, display in eagles.creates]
    horn = next(a for a in boromir.abilities if a.name == "SpecialAbilityHornOfGondor")
    assert horn.modifiers  # e.g. ("SPEED", "125%")
