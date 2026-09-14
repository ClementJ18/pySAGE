"""Script item construction, sentences, the generic list/property edits, and that a map with new
scripts written by these builders reads back as the same data."""

import io

from sage_map.assets.player_scripts import (
    PlayerScriptsList,
    ScriptArgumentType,
    ScriptList,
)
from sage_map.context import AssetPropertyType
from sage_map.map import Map, parse_map, write_map
from sage_worldbuilder import Change, ChangeKind, MapDocument
from sage_worldbuilder.commands.edits import (
    InsertItem,
    MoveItem,
    RemoveItem,
    ReplaceItem,
    SetProperty,
)
from sage_worldbuilder.scripting import (
    argument_choices,
    argument_text,
    item_template,
    item_text,
    iter_script_items,
    map_symbols,
    new_argument,
    new_group,
    new_item,
    new_script,
    retarget,
    script_matches,
    sentence_parts,
    unique_script_name,
)
from sage_worldbuilder.templates import TemplateKind, template_named

SCRIPTS = Change(ChangeKind.SCRIPTS)


def action(name: str):
    entry = template_named(TemplateKind.ACTION, name)
    assert entry is not None
    return entry


def condition(name: str):
    entry = template_named(TemplateKind.CONDITION, name)
    assert entry is not None
    return entry


def map_with_scripts() -> Map:
    map = Map()
    script = new_script("Intro")
    script.or_conditions[0].conditions.append(new_item(condition("NAMED_NOT_DESTROYED")))
    move = new_item(action("MOVE_NAMED_UNIT_TO"))
    move.arguments[0].string_value = "Gandalf"
    move.arguments[1].string_value = "Gate"
    script.actions_if_true.append(move)
    group = new_group("Act One")
    group.items.append(script)
    map.player_scripts_list = PlayerScriptsList(
        version=1,
        script_lists=[ScriptList(version=1, items=[group], start_pos=0, end_pos=0)],
        start_pos=0,
        end_pos=0,
    )
    return map


def test_new_items_follow_their_templates():
    move = new_item(action("MOVE_NAMED_UNIT_TO"))
    assert move.content_type == 38
    assert move.internal_name == (AssetPropertyType.AsciiString, 0, "MOVE_NAMED_UNIT_TO")
    assert [argument.type for argument in move.arguments] == [
        ScriptArgumentType.UNIT_NAME,
        ScriptArgumentType.WAYPOINT_NAME,
    ]
    assert move.is_inverted is None

    alive = new_item(condition("NAMED_NOT_DESTROYED"))
    assert alive.version == 6 and alive.is_inverted is False


def test_unfilled_template_slot_defaults_to_integer():
    blur = new_item(action("CAMERA_MOTION_BLUR_FOLLOW"))
    assert blur.arguments[0].type is ScriptArgumentType.INTEGER
    assert new_argument(ScriptArgumentType.POSITION_COORDINATE).position_value == (0.0, 0.0, 0.0)


def test_sentences_read_like_worldbuilder():
    move = new_item(action("MOVE_NAMED_UNIT_TO"))
    move.arguments[0].string_value = "Gandalf"
    move.arguments[1].string_value = "Gate"
    assert item_text(move, TemplateKind.ACTION) == "Move Gandalf to Gate."

    alive = new_item(condition("NAMED_NOT_DESTROYED"))
    alive.arguments[0].string_value = "Gandalf"
    alive.is_inverted = True
    assert item_text(alive, TemplateKind.CONDITION) == "NOT Gandalf exists and is alive."

    assert sentence_parts(move, TemplateKind.ACTION) == [
        ("Move ", None),
        ("Gandalf", 0),
        (" to ", None),
        ("Gate", 1),
        (".", None),
    ]
    assert sentence_parts(alive, TemplateKind.CONDITION) == [
        ("NOT ", None),
        ("Gandalf", 0),
        (" exists and is alive.", None),
    ]

    move.content_type = 99_999
    assert item_template(move, TemplateKind.ACTION) is not None  # found by name instead
    move.internal_name = None
    assert item_text(move, TemplateKind.ACTION) == "[unknown action 99999]"
    assert argument_text(new_argument(ScriptArgumentType.BOOLEAN)) == "FALSE"
    comparison = new_argument(ScriptArgumentType.COMPARISON)
    comparison.int_value = 4
    assert argument_text(comparison) == "Greater Than"
    comparison.int_value = 99
    assert argument_text(comparison) == "99"


def test_retarget_keeps_fitting_arguments():
    move = new_item(action("MOVE_NAMED_UNIT_TO"))
    move.arguments[0].string_value = "Gandalf"
    move.is_enabled = False
    attack_move = retarget(move, action("ATTACK_MOVE_NAMED_UNIT_TO"))

    assert attack_move.internal_name[2] == "ATTACK_MOVE_NAMED_UNIT_TO"
    assert attack_move.arguments[0].string_value == "Gandalf"
    assert attack_move.is_enabled is False


def test_map_with_new_scripts_round_trips():
    written = write_map(map_with_scripts(), compress=False)
    reread = parse_map(io.BytesIO(written))

    group = reread.player_scripts_list.script_lists[0].items[0]
    script = group.items[0]
    assert (group.name, script.name) == ("Act One", "Intro")
    move = script.actions_if_true[0]
    assert item_text(move, TemplateKind.ACTION) == "Move Gandalf to Gate."
    assert write_map(reread, compress=False) == written


def test_tree_walk_and_unique_names():
    map = map_with_scripts()
    items = map.player_scripts_list.script_lists[0].items
    assert [(location.item.name, location.depth) for location in iter_script_items(items)] == [
        ("Act One", 0),
        ("Intro", 1),
    ]
    assert unique_script_name(map, "Intro") == "Intro (2)"
    assert unique_script_name(map, "Outro") == "Outro"


def test_search_matches_names_sentences_and_whole_values():
    map = map_with_scripts()
    group = map.player_scripts_list.script_lists[0].items[0]
    script = group.items[0]

    assert script_matches(script, "intro")
    assert script_matches(script, "gandalf")
    assert script_matches(script, "move_named")
    assert script_matches(script, "Gandalf", whole=True)
    assert not script_matches(script, "Gand", whole=True)
    assert not script_matches(group, "gandalf")
    assert script_matches(group, "")


def test_argument_choices_follow_the_argument_scope():
    symbols = {"waypoints": ["Gate", "Keep"], "teams": ["Plyr/Army"]}

    class FakeGame:
        tables = {"sciences": {"SCIENCE_b": object(), "SCIENCE_A": object()}}
        strings = {"MAP:Title": "Title"}

    game = FakeGame()
    assert argument_choices(ScriptArgumentType.WAYPOINT_NAME, symbols, None) == ["Gate", "Keep"]
    assert argument_choices(ScriptArgumentType.SCIENCE_NAME, symbols, None) == []
    assert argument_choices(ScriptArgumentType.SCIENCE_NAME, symbols, game) == [
        "SCIENCE_A",
        "SCIENCE_b",
    ]
    assert argument_choices(ScriptArgumentType.LOCALIZED_STRING_NAME, symbols, game) == [
        "MAP:Title"
    ]
    assert argument_choices(ScriptArgumentType.INTEGER, symbols, game) == []
    assert argument_choices(999, symbols, game) == []


def test_map_symbols_lists_pickable_names_as_written():
    map = map_with_scripts()
    script = map.player_scripts_list.script_lists[0].items[0].items[0]
    counter = new_item(action("SET_COUNTER"))
    counter.arguments[0].string_value = "WaveCount"
    script.actions_if_true.append(counter)

    symbols = map_symbols(map)

    assert symbols["scripts"] == ["Act One", "Intro"]
    assert symbols["counters"] == ["WaveCount"]
    assert symbols["teams"] == [] and symbols["units"] == []


def test_list_edits_undo_to_the_same_objects():
    document = MapDocument(Map())
    items = ["a", "b", "c"]
    other: list[str] = []

    document.execute(InsertItem(items, 1, "x", SCRIPTS))
    assert items == ["a", "x", "b", "c"]
    document.execute(RemoveItem(items, 0, SCRIPTS))
    document.execute(MoveItem(items, 0, other, 0, SCRIPTS))
    document.execute(ReplaceItem(items, 0, "z", SCRIPTS))
    assert (items, other) == (["z", "c"], ["x"])

    while document.stack.undo():
        pass
    assert (items, other) == (["a", "b", "c"], [])


def test_set_property_restores_order_and_merges():
    document = MapDocument(Map())
    properties = {
        "a": {"name": "a", "type": AssetPropertyType.Integer, "value": 1},
        "b": {"name": "b", "type": AssetPropertyType.Integer, "value": 2},
    }
    document.execute(SetProperty(properties, "a", None, SCRIPTS))
    document.execute(
        SetProperty(
            properties, "a", {"name": "a", "type": AssetPropertyType.Integer, "value": 3}, SCRIPTS
        )
    )
    assert list(properties) == ["b", "a"]

    document.stack.undo()
    document.stack.undo()
    assert list(properties) == ["a", "b"] and properties["a"]["value"] == 1

    document.execute(
        SetProperty(
            properties, "b", {"name": "b", "type": AssetPropertyType.Integer, "value": 5}, SCRIPTS
        )
    )
    document.execute(
        SetProperty(
            properties, "b", {"name": "b", "type": AssetPropertyType.Integer, "value": 6}, SCRIPTS
        )
    )
    document.stack.undo()
    assert properties["b"]["value"] == 2
