"""Generic AI objects: new ones as WorldBuilder's tool makes them, and editing their values."""

import io

import pytest

from sage_map.map import parse_map, write_map
from sage_worldbuilder.document import MapDocument
from sage_worldbuilder.generic_ai import (
    GENERIC_AI_OBJECT,
    GenericAIType,
    generic_ai_objects,
    generic_ai_values,
    new_generic_ai_object,
    set_generic_ai,
)
from sage_worldbuilder.objects import place_objects
from sage_worldbuilder.scene import MarkerKind, marker_kind

pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_worldbuilder.new_map import NewMapOptions, new_map  # noqa: E402

# The property order all 222 corpus generic AI objects store.
CORPUS_ORDER = [
    "objectInitialHealth",
    "objectEnabled",
    "objectIndestructible",
    "objectUnsellable",
    "objectPowered",
    "objectRecruitableAI",
    "objectTargetable",
    "objectBasePriority",
    "objectBasePhase",
    "originalOwner",
    "uniqueID",
    "objectLayer",
    "GenericAIObjectType",
    "GenericAIObjectID",
    "GenericAIObjectName",
    "GenericAIObjectWallHubNumber",
]


def _document():
    return MapDocument(new_map(NewMapOptions(width=32, height=32, border=2)))


def test_a_new_generic_ai_object_takes_the_corpus_form():
    document = _document()
    obj = new_generic_ai_object(
        document.map, (100.0, 120.0, 0.0), GenericAIType.EXPANSION_LOCATOR, 2
    )

    assert obj.type_name == GENERIC_AI_OBJECT
    assert marker_kind(obj) is MarkerKind.GENERIC_AI
    assert list(obj.properties) == CORPUS_ORDER
    assert obj.properties["originalOwner"]["value"] == "/team"
    assert obj.angle == 0.0 and obj.road_type == 0
    assert generic_ai_values(obj) == ("GenericAIObject 1", GenericAIType.EXPANSION_LOCATOR, 2, 1)


def test_names_and_ids_follow_the_objects_already_placed():
    document = _document()
    first = new_generic_ai_object(document.map, (10.0, 10.0, 0.0))
    document.execute(place_objects(document.map, [first]))
    second = new_generic_ai_object(document.map, (20.0, 10.0, 0.0))
    document.execute(place_objects(document.map, [second]))
    document.execute(set_generic_ai([first], name="_WallHub_A"))

    third = new_generic_ai_object(document.map, (30.0, 10.0, 0.0))

    assert generic_ai_values(second)[0] == "GenericAIObject 2"
    assert generic_ai_values(third)[0] == "GenericAIObject 1"
    assert generic_ai_values(third)[3] == 3
    assert generic_ai_objects(document.map) == [first, second]


def test_options_edits_are_one_undoable_step_and_round_trip():
    document = _document()
    obj = new_generic_ai_object(document.map, (10.0, 10.0, 0.0))
    document.execute(place_objects(document.map, [obj]))

    assert (
        set_generic_ai([obj], name="GenericAIObject 1", kind=GenericAIType.WALL_HUB, wall_hub=0)
        is None
    )
    document.execute(
        set_generic_ai([obj], name="_WallHub_C", kind=GenericAIType.EXPANSION_LOCATOR, wall_hub=3)
    )
    assert generic_ai_values(obj)[:3] == ("_WallHub_C", GenericAIType.EXPANSION_LOCATOR, 3)
    assert list(obj.properties) == CORPUS_ORDER

    reread = parse_map(io.BytesIO(write_map(document.map, compress=False)))
    assert generic_ai_values(generic_ai_objects(reread)[0])[:3] == (
        "_WallHub_C",
        GenericAIType.EXPANSION_LOCATOR,
        3,
    )

    document.stack.undo()
    assert generic_ai_values(obj)[:3] == ("GenericAIObject 1", GenericAIType.WALL_HUB, 0)


def test_an_unlisted_type_number_is_shown_as_it_is():
    document = _document()
    obj = new_generic_ai_object(document.map, (10.0, 10.0, 0.0))
    obj.properties["GenericAIObjectType"]["value"] = 7
    assert generic_ai_values(obj)[1] == 7
