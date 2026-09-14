"""The shipped script template catalogue: lookups, sentences, and agreement with real maps and
with the WorldBuilder build it was extracted from."""

from pathlib import Path

import pytest

from sage_map import parse_map_from_path
from sage_map.assets.player_scripts import Script, ScriptArgumentType, ScriptDerived
from sage_worldbuilder.templates import (
    TemplateKind,
    parameter_values,
    script_templates,
    template,
    template_named,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MAPS = REPO_ROOT / "tests" / "sage_map" / "fixtures" / "maps"
T = ScriptArgumentType


def test_catalogue_size_and_unique_keys():
    templates = script_templates()
    actions = [entry for entry in templates if entry.kind is TemplateKind.ACTION]
    conditions = [entry for entry in templates if entry.kind is TemplateKind.CONDITION]
    assert (len(actions), len(conditions)) == (596, 196)
    for kind in TemplateKind:
        entries = [entry for entry in templates if entry.kind is kind]
        assert len({entry.id for entry in entries}) == len(entries)
        names = [entry.internal_name for entry in entries]
        duplicates = {name for name in names if names.count(name) > 1}
        assert duplicates == ({"MAP_REVEAL_IN_TRIGGER"} if kind is TemplateKind.ACTION else set())


def test_a_shared_name_selects_the_lowest_id():
    reveal = template_named(TemplateKind.ACTION, "MAP_REVEAL_IN_TRIGGER")
    assert reveal is not None and reveal.id == 552
    assert template(TemplateKind.ACTION, 553).ui_strings[0] == "The map is shrouded inside "


def test_ids_and_names_select_the_same_template():
    move = template(TemplateKind.ACTION, 38)
    assert move is not None
    assert move.internal_name == "MOVE_NAMED_UNIT_TO"
    assert move.parameters == (T.UNIT_NAME, T.WAYPOINT_NAME)
    assert move.path == ("Unit_", "Move", "Move a specific unit to a location.")
    assert template_named(TemplateKind.ACTION, "MOVE_NAMED_UNIT_TO") is move

    # Conditions number from 0 in their own space, which overlaps the actions'.
    assert template(TemplateKind.CONDITION, 1).internal_name == "COUNTER"
    assert template(TemplateKind.ACTION, 1).internal_name == "SET_FLAG"
    assert template(TemplateKind.ACTION, 10_000) is None


def test_sentence_interleaves_fragments_and_arguments():
    move = template_named(TemplateKind.ACTION, "MOVE_NAMED_UNIT_TO")
    assert move is not None
    assert move.sentence(["Gandalf", "Gate"]) == "Move Gandalf to Gate."
    assert move.sentence([]) == "Move  to ."


def test_unfilled_slots_and_unnamed_types_are_kept():
    blur = template_named(TemplateKind.ACTION, "CAMERA_MOTION_BLUR_FOLLOW")
    assert blur is not None and blur.parameters == (None,)
    region = template_named(TemplateKind.ACTION, "LIVING_WORLD_SET_REGION_REF_TO_ARMY_REGION")
    assert region is not None and region.parameters == (72, 69)
    assert region.flags == 2


def test_enum_parameter_value_names():
    assert parameter_values(T.COMPARISON) == (
        "Less Than",
        "Less Than or Equal",
        "Equal To",
        "Greater Than or Equal To",
        "Greater Than",
        "Not Equal To",
    )
    assert parameter_values(T.BOOLEAN) == ("FALSE", "TRUE")
    assert parameter_values(T.STANCE)[3] == "HoldGround"
    kinds = parameter_values(T.UNIT_OR_STRUCTURE_KIND)
    assert kinds is not None and len(kinds) == 222 and kinds[8] == "INFANTRY"
    assert parameter_values(T.TEXT) is None


def _script_items(scripts) -> list[tuple[TemplateKind, ScriptDerived]]:
    found: list[tuple[TemplateKind, ScriptDerived]] = []

    def visit(value) -> None:
        if isinstance(value, Script):
            for group in value.or_conditions:
                found.extend((TemplateKind.CONDITION, item) for item in group.conditions)
            found.extend(
                (TemplateKind.ACTION, item)
                for item in value.actions_if_true + value.actions_if_false
            )
        elif hasattr(value, "__dataclass_fields__"):
            for name in value.__dataclass_fields__:
                visit(getattr(value, name))
        elif isinstance(value, list | tuple):
            for element in value:
                visit(element)

    visit(scripts)
    return found


@pytest.mark.full
@pytest.mark.parametrize("map_path", sorted(MAPS.glob("*.map")), ids=lambda path: path.name)
def test_every_fixture_script_resolves(map_path):
    for kind, item in _script_items(parse_map_from_path(map_path).player_scripts_list):
        entry = template(kind, item.content_type)
        assert entry is not None, (kind, item.content_type)
        if item.internal_name is not None:
            assert entry.internal_name == item.internal_name[2]
        assert len(item.arguments) == len(entry.parameters), entry.internal_name
        for argument, expected in zip(item.arguments, entry.parameters, strict=True):
            assert expected is None or argument.type == expected, entry.internal_name


@pytest.mark.full
def test_catalogue_matches_the_exe():
    exe = REPO_ROOT / "worldbuilder.exe"
    if not exe.is_file():
        pytest.skip("worldbuilder.exe is not in the checkout")
    tool = pytest.importorskip("tools.extract_script_templates")

    shipped = (REPO_ROOT / "sage_worldbuilder" / "script_templates.json").read_text(
        encoding="utf-8"
    )
    assert tool.render_templates(tool.extract_templates(exe)) == shipped
