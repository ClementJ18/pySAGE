"""Scenario scripts: declaring them, compiling them into a map, and driving them in a game.

Data-free. Compilation runs against a blank map built in memory (`sage_worldbuilder.new_map`) and
is checked by writing that map and parsing it back. The driver runs against a fake process,
with the live script tree and the variables stubbed, since those readers have their own tests.
"""

from __future__ import annotations

import io
import struct

import pytest

from sage_live.backends.scripts import LiveScript, ScriptVariable
from sage_map import parse_map, write_map
from sage_map.assets.player_scripts import Script, ScriptArgumentType, ScriptGroup
from sage_map.map import Map
from sage_patch.addresses import (
    GAME_LOGIC_FRAME,
    GAME_LOGIC_GAME_MODE,
    SCRIPT_ACTIVE,
    SCRIPT_NEXT_FRAME,
    THE_GAME_LOGIC,
)
from sage_test import Scenario, Seat, act, any_of, cond
from sage_test import scripts as driver
from sage_test.compile import compile_into
from sage_test.script_compile import GROUP, ScriptCompileError, build_script, counter_name
from sage_test.scripts import ScriptControl, ScriptError
from sage_worldbuilder.document import MapDocument
from sage_worldbuilder.new_map import NewMapOptions, new_map
from sage_worldbuilder.players import add_player_with_team, new_player
from sage_worldbuilder.scripting import player_script_lists
from tests.sage_live.fake_process import FakeProcess

TEAM = "Player_2/teamPlayer_2"


def _scenario() -> Scenario:
    return Scenario(
        "t",
        seats=(
            Seat.human(faction=3, start_position=0),
            Seat.easy_ai(faction=10, start_position=1),
        ),
    )


def _map() -> Map:
    """A blank map with the neutral side and `Player_1`, as a template map has."""
    blank = new_map(NewMapOptions(width=24, height=24, border=2))
    add_player_with_team(blank, new_player("Player_1")).do(MapDocument(blank))
    return blank


def _ours(template: Map, side: str = "") -> list[Script]:
    lists = dict(player_script_lists(template))
    groups = [i for i in lists[side].items if isinstance(i, ScriptGroup) and i.name == GROUP]
    if not groups:
        return []
    return [i for i in groups[0].items if isinstance(i, Script)]


def _action_names(script: Script) -> list[str | None]:
    return [a.internal_name[2] if a.internal_name else None for a in script.actions_if_true]


class TestDeclaring:
    def test_a_trigger_needs_actions(self) -> None:
        with pytest.raises(ValueError, match="no actions"):
            _scenario().script("empty")

    def test_a_probe_needs_conditions(self) -> None:
        with pytest.raises(ValueError, match="no conditions"):
            _scenario().probe("empty")

    def test_names_are_unique_and_have_no_slash(self) -> None:
        scenario = _scenario()
        scenario.script("wave", act("NAMED_KILL", "x"))
        with pytest.raises(ValueError, match="twice"):
            scenario.script("Wave", act("NAMED_KILL", "x"))
        with pytest.raises(ValueError, match="free of '/'"):
            scenario.script("a/b", act("NAMED_KILL", "x"))

    def test_a_seat_side_must_be_one_of_the_seats(self) -> None:
        with pytest.raises(ValueError, match="seat 5"):
            _scenario().script("s", act("NAMED_KILL", "x"), side=5)

    def test_conditions_side_by_side_are_one_clause(self) -> None:
        a, b = cond("NAMED_DESTROYED", "a"), cond("NAMED_DESTROYED", "b")
        decl = _scenario().probe("p", a, b)
        assert decl.clauses == ((a, b),)

    def test_any_of_is_one_clause_per_alternative(self) -> None:
        a, b, c = (cond("NAMED_DESTROYED", n) for n in "abc")
        decl = _scenario().probe("p", any_of(a, (b, c)))
        assert decl.clauses == ((a,), (b, c))

    def test_any_of_does_not_mix_with_bare_conditions(self) -> None:
        a = cond("NAMED_DESTROYED", "a")
        with pytest.raises(ValueError, match="cannot be combined"):
            _scenario().probe("p", a, any_of(a))

    def test_an_area_from_a_rect_has_its_four_corners(self) -> None:
        area = _scenario().area("yard", rect=((10, 20), (30, 40)))
        assert area.points == ((10, 20), (30, 20), (30, 40), (10, 40))

    def test_an_area_takes_a_rect_or_points(self) -> None:
        with pytest.raises(ValueError, match="rect or points"):
            _scenario().area("yard")

    def test_a_renamed_copy_keeps_its_scripts_apart(self) -> None:
        scenario = _scenario()
        scenario.script("s", act("NAMED_KILL", "x"))
        copy = scenario.with_name("u")
        copy.script("t", act("NAMED_KILL", "x"))
        assert [s.name for s in scenario.scripts] == ["s"]


class TestBuilding:
    def test_a_trigger_is_inactive_one_shot_and_true(self) -> None:
        decl = _scenario().script("wave", act("NAMED_KILL", "TestScout"))
        script = build_script(decl)
        assert script.name == "sage_test.wave"
        assert (script.is_active, script.deactivate_upon_success) == (False, True)
        (clause,) = script.or_conditions
        assert [c.internal_name[2] for c in clause.conditions if c.internal_name] == [
            "CONDITION_TRUE"
        ]

    def test_every_script_ends_with_its_receipt(self) -> None:
        script = build_script(_scenario().script("wave", act("NAMED_KILL", "TestScout")))
        assert _action_names(script) == ["NAMED_KILL", "INCREMENT_COUNTER"]
        amount, counter = script.actions_if_true[-1].arguments
        assert (amount.int_value, counter.string_value) == (1, counter_name("wave"))

    def test_a_probe_is_active_and_keeps_its_conditions(self) -> None:
        decl = _scenario().probe(
            "seen",
            cond("NAMED_INSIDE_AREA", "TestScout", "Yard", inverted=True),
            once=False,
            every=2,
        )
        script = build_script(decl)
        assert (script.is_active, script.deactivate_upon_success) == (True, False)
        assert script.evaluation_interval == 2
        (condition,) = script.or_conditions[0].conditions
        assert condition.is_inverted is True
        assert [a.string_value for a in condition.arguments] == ["TestScout", "Yard"]
        assert _action_names(script) == ["INCREMENT_COUNTER"]

    def test_arguments_land_in_their_slots(self) -> None:
        decl = _scenario().script(
            "spawn", act("CREATE_OBJECT", "GondorSoldier", TEAM, (1700, 1650), 90)
        )
        template, team, position, angle = build_script(decl).actions_if_true[0].arguments
        assert template.string_value == "GondorSoldier"
        assert team.string_value == TEAM
        assert position.position_value == (1700.0, 1650.0, 0.0)
        assert (angle.type, angle.float_value) == (ScriptArgumentType.ANGLE, 90.0)

    def test_comparisons_and_enum_names(self) -> None:
        decl = _scenario().probe("c", cond("COUNTER", "n", ">=", 3), cond("FLAG", "f", "true"))
        counter, flag = build_script(decl).or_conditions[0].conditions
        assert counter.arguments[1].int_value == 3  # Greater Than or Equal To
        assert flag.arguments[1].int_value == 1

    @pytest.mark.parametrize(
        ("action", "message"),
        [
            (act("NO_SUCH_ACTION"), "no action template"),
            (act("NAMED_KILL"), "takes 1 arguments"),
            (act("NAMED_KILL", 7), "takes a name"),
            (act("NAMED_DAMAGE", "x", "lots"), "takes an integer"),
            (act("CREATE_OBJECT", "o", TEAM, 5, 0), "a position"),
        ],
    )
    def test_a_bad_declaration_names_what_is_wrong(self, action, message) -> None:
        with pytest.raises(ScriptCompileError, match=message):
            build_script(_scenario().script("bad", action))

    def test_an_unknown_comparison_is_refused(self) -> None:
        with pytest.raises(ScriptCompileError, match="is not one of"):
            build_script(_scenario().probe("c", cond("COUNTER", "n", "about", 3)))


class TestCompiling:
    def test_scripts_go_into_the_group_on_their_side(self) -> None:
        scenario = _scenario()
        scenario.script("neutral", act("NAMED_KILL", "x"))
        scenario.script("mine", act("NAMED_KILL", "x"), side=0)
        template = compile_into(scenario, _map())
        assert [s.name for s in _ours(template)] == ["sage_test.neutral"]
        assert [s.name for s in _ours(template, "Player_1")] == ["sage_test.mine"]

    def test_a_missing_side_fails_before_anything_is_added(self) -> None:
        scenario = _scenario()
        scenario.waypoint("Spawn", (100, 100, 0))
        scenario.script("theirs", act("NAMED_KILL", "x"), side=1)  # Player_2: not on the map
        template = _map()
        before = len(template.objects_list.object_list)
        with pytest.raises(ScriptCompileError, match="no side 'Player_2'"):
            compile_into(scenario, template)
        assert len(template.objects_list.object_list) == before
        assert _ours(template) == []

    def test_waypoints_and_areas_carry_their_names(self) -> None:
        scenario = _scenario()
        scenario.waypoint("Spawn", (100, 120, 0))
        scenario.area("Yard", rect=((10, 10), (50, 50)))
        template = compile_into(scenario, _map())
        (waypoint,) = [
            o for o in template.objects_list.object_list if o.type_name == "*Waypoints/Waypoint"
        ]
        assert waypoint.properties["waypointName"]["value"] == "Spawn"
        assert waypoint.properties["uniqueID"]["value"] == "Spawn"
        assert waypoint.position == (100, 120, 0)
        (area,) = template.trigger_areas.trigger_areas
        assert area.name == "Yard"
        assert area.points == [(10.0, 10.0), (50.0, 10.0), (50.0, 50.0), (10.0, 50.0)]

    def test_a_waypoint_the_map_already_has_is_refused(self) -> None:
        scenario = _scenario()
        scenario.waypoint("Spawn", (100, 120, 0))
        template = compile_into(scenario, _map())
        with pytest.raises(ScriptCompileError, match="already has a waypoint"):
            compile_into(scenario.with_name("again"), template)

    def test_the_map_round_trips(self) -> None:
        scenario = _scenario()
        scenario.waypoint("Spawn", (100, 120, 0))
        scenario.script(
            "wave", act("CREATE_NAMED_ON_TEAM_AT_WAYPOINT", "Orc1", "MordorOrc", TEAM, "Spawn")
        )
        scenario.probe("dead", cond("NAMED_DESTROYED", "Orc1"))
        written = write_map(compile_into(scenario, _map()), compress=False)
        parsed = parse_map(io.BytesIO(written))
        wave, dead = _ours(parsed)
        assert (wave.name, wave.is_active, wave.deactivate_upon_success) == (
            "sage_test.wave",
            False,
            True,
        )
        assert _action_names(wave) == ["CREATE_NAMED_ON_TEAM_AT_WAYPOINT", "INCREMENT_COUNTER"]
        assert [a.string_value for a in wave.actions_if_true[0].arguments] == [
            "Orc1",
            "MordorOrc",
            TEAM,
            "Spawn",
        ]
        assert (dead.name, dead.is_active) == ("sage_test.dead", True)

    def test_a_scenario_without_scripts_leaves_the_lists_alone(self) -> None:
        template = _map()
        before = write_map(template, compress=False)
        compile_into(_scenario(), template)
        assert write_map(template, compress=False) == before


LOGIC = 0x10000000
SCRIPT = 0x20000000


def _live(name: str, address: int = SCRIPT, path: tuple[str, ...] = (GROUP,)) -> LiveScript:
    return LiveScript(
        name=name,
        address=address,
        active=False,
        authored_active=False,
        one_shot=True,
        subroutine=False,
        easy=True,
        normal=True,
        hard=True,
        delay_seconds=0,
        sequential=False,
        next_frame=500,
        path=path,
    )


class _Side:
    def __init__(self, index: int, scripts: list[LiveScript]) -> None:
        self.index = index
        self._scripts = scripts

    def all_scripts(self) -> list[LiveScript]:
        return self._scripts


class _Tree:
    def __init__(self, *sides: _Side) -> None:
        self.sides = sides


@pytest.fixture
def game(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeProcess, dict[str, int]]:
    """A skirmish at frame 100 with one scenario script and one of the map's own. The counters
    are a dict the test changes, standing in for the engine raising one."""
    process = FakeProcess()
    process.u32(THE_GAME_LOGIC, LOGIC)
    process.u32(LOGIC + GAME_LOGIC_FRAME, 100)
    process.u32(LOGIC + GAME_LOGIC_GAME_MODE, 2)
    process.write(SCRIPT, bytes(0x48))
    process.u32(SCRIPT + SCRIPT_NEXT_FRAME, 500)
    counters: dict[str, int] = {}
    tree = _Tree(_Side(0, [_live("sage_test.wave"), _live("Map Intro", 0x21000000, ())]))
    monkeypatch.setattr(driver, "read_script_tree", lambda read: tree)
    monkeypatch.setattr(
        driver,
        "read_script_variables",
        lambda read: [
            ScriptVariable("counter", "", name, value, address=0x22000000)
            for name, value in counters.items()
        ],
    )
    return process, counters


class TestDriving:
    def test_only_scenario_scripts_are_listed(self, game) -> None:
        process, _ = game
        assert ScriptControl(process).names() == ["wave"]

    def test_fire_re_arms_and_switches_on(self, game) -> None:
        process, counters = game
        counters[counter_name("wave")] = 2
        assert ScriptControl(process).fire("wave") == 2
        assert process.read(SCRIPT + SCRIPT_ACTIVE, 1) == b"\x01"
        assert process.read(SCRIPT + SCRIPT_NEXT_FRAME, 4) == struct.pack("<I", 0)

    def test_count_is_zero_before_the_counter_exists(self, game) -> None:
        process, _ = game
        assert ScriptControl(process).count("wave") == 0

    def test_wait_fired_returns_once_the_count_moves(self, game, monkeypatch) -> None:
        process, counters = game
        control = ScriptControl(process)
        before = control.fire("wave")

        def engine_runs_it(_: float) -> None:
            counters[counter_name("wave")] = before + 1

        monkeypatch.setattr(driver.time, "sleep", engine_runs_it)
        assert control.wait_fired("wave", after=before, timeout=5) == 1

    def test_a_script_that_never_runs_says_why(self, game) -> None:
        process, _ = game
        control = ScriptControl(process)
        control.fire("wave")
        with pytest.raises(ScriptError, match="active True, due at frame 0, game at frame 100"):
            control.wait_fired("wave", after=0, timeout=0.1)

    def test_an_unknown_script_lists_the_ones_there_are(self, game) -> None:
        process, _ = game
        with pytest.raises(
            ScriptError, match=r"'nope' is not in the game \(scenario scripts: wave"
        ):
            ScriptControl(process).fire("nope")

    def test_a_network_game_is_refused(self, game) -> None:
        process, _ = game
        process.u32(LOGIC + GAME_LOGIC_GAME_MODE, 1)
        with pytest.raises(ScriptError, match="network game"):
            ScriptControl(process).fire("wave")
        assert process.read(SCRIPT + SCRIPT_ACTIVE, 1) == b"\x00"

    def test_set_counter_writes_one_that_exists(self, game) -> None:
        process, counters = game
        counters["sage_test.wave_size"] = 1
        process.write(0x22000000, bytes(8))
        ScriptControl(process).set_counter("sage_test.wave_size", 3)
        assert process.read(0x22000000, 4) == struct.pack("<i", 3)

    def test_set_counter_refuses_one_no_script_touched(self, game) -> None:
        process, _ = game
        with pytest.raises(ScriptError, match="only once a script"):
            ScriptControl(process).set_counter("nothing", 3)
