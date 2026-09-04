"""Turning a :class:`~sage_test.scenario.Scenario` into map data.

A scenario is compiled **onto a template map**, never generated from nothing. A `.map` is not
only objects: it carries terrain, blend tiles, lighting, water, a sides list and the multiplayer
start positions, and a skirmish needs all of it. So the compiler takes a real map that already
plays - its start positions, its castle plots, its scripts - and appends the scenario's objects
to it. What a test declares is therefore *additional*, and everything that makes the map a map is
inherited.

The properties written are the ones WorldBuilder writes, with the values it defaults to, read
off a shipped map rather than guessed: an object the engine loads has to look like an object the
editor produced.

`originalOwner` is the load-bearing one. It names `Player_<startPos + 1>/team…`, which is what
binds a placed object to the seat sitting at that start position - see
`sage_patch/docs/game-info.md` on `GAME_SLOT_MAP_PLAYER`.
"""

from __future__ import annotations

from sage_map.assets.object_list import Object
from sage_map.context import AssetPropertyType, Property
from sage_map.map import Map
from sage_test.scenario import Placement, Scenario

__all__ = [
    "OBJECT_VERSION",
    "STANDARD_PROPERTIES",
    "compile_into",
    "placement_object",
    "placement_properties",
]

#: Every placed object in a shipped RotWK map carries version 3.
OBJECT_VERSION = 3

#: What WorldBuilder writes on every object, with its defaults. `objectInitialHealth` and
#: `originalOwner` are overridden per placement; the rest are what makes a generated object
#: indistinguishable from an authored one.
STANDARD_PROPERTIES: tuple[tuple[str, AssetPropertyType, bool | int | str], ...] = (
    ("objectInitialHealth", AssetPropertyType.Integer, 100),
    ("objectEnabled", AssetPropertyType.Boolean, True),
    ("objectIndestructible", AssetPropertyType.Boolean, False),
    ("objectUnsellable", AssetPropertyType.Boolean, False),
    ("objectPowered", AssetPropertyType.Boolean, True),
    ("objectRecruitableAI", AssetPropertyType.Boolean, True),
    ("objectTargetable", AssetPropertyType.Boolean, False),
    ("originalOwner", AssetPropertyType.AsciiString, "/team"),
    ("uniqueID", AssetPropertyType.AsciiString, ""),
    ("objectLayer", AssetPropertyType.AsciiString, ""),
)


def _prop(name: str, kind: AssetPropertyType, value: bool | int | str) -> Property:
    return Property(name=name, type=kind, value=value)


def placement_properties(
    scenario: Scenario, placement: Placement, unique_id: str
) -> dict[str, Property]:
    """The property dict for one placement, in the order WorldBuilder writes them."""
    properties: dict[str, Property] = {
        name: _prop(name, kind, value) for name, kind, value in STANDARD_PROPERTIES
    }
    properties["objectInitialHealth"] = _prop(
        "objectInitialHealth", AssetPropertyType.Integer, placement.health
    )
    properties["uniqueID"] = _prop("uniqueID", AssetPropertyType.AsciiString, unique_id)

    owner = scenario.owner_of(placement)
    if owner is not None:
        properties["originalOwner"] = _prop("originalOwner", AssetPropertyType.AsciiString, owner)

    # The three that only appear when they say something. A level or an upgrade list on an
    # object that has neither is noise the editor would not have written.
    if placement.level is not None:
        properties["objectExperienceLevel"] = _prop(
            "objectExperienceLevel", AssetPropertyType.Integer, placement.level
        )
    if placement.upgrades:
        # Space separated with a trailing space, which is the form shipped maps use.
        value = "".join(f"{upgrade} " for upgrade in placement.upgrades)
        properties["objectUpgradesList"] = _prop(
            "objectUpgradesList", AssetPropertyType.AsciiString, value
        )
    if placement.name is not None:
        properties["objectName"] = _prop(
            "objectName", AssetPropertyType.AsciiString, placement.name
        )
    return properties


def placement_object(scenario: Scenario, placement: Placement, unique_id: str) -> Object:
    """One placement as a `sage_map` `Object`, ready to append to an `ObjectsList`.

    `start_pos`/`end_pos` are parse-time bookkeeping - `Object.write` does not read them - so a
    synthesized object leaves them at zero rather than inventing file offsets it does not have.
    """
    return Object(
        version=OBJECT_VERSION,
        position=placement.at,
        angle=placement.angle,
        road_type=0,
        type_name=placement.template,
        properties=placement_properties(scenario, placement, unique_id),
        start_pos=0,
        end_pos=0,
    )


def _unique_id_of(obj: Object) -> str:
    """An object's `uniqueID`, or the empty string for one that carries none."""
    prop = obj.properties.get("uniqueID")
    return "" if prop is None else str(prop["value"])


def _unique_ids(scenario: Scenario, taken: set[str]) -> list[str]:
    """A `uniqueID` per placement that no object already on the map is using.

    Shipped maps use `"<template> <n>"`, so these do too; the counter simply walks past anything
    already claimed rather than assuming a range is free.
    """
    ids: list[str] = []
    counter = 0
    for placement in scenario.placements:
        while True:
            candidate = f"{placement.template} {counter}"
            counter += 1
            if candidate not in taken:
                break
        taken.add(candidate)
        ids.append(candidate)
    return ids


def compile_into(scenario: Scenario, template: Map) -> Map:
    """Append `scenario`'s placements to `template`'s object list, in place, and return it.

    In place, and returning the same object, because a `Map` is a large mutable parse tree and
    copying it would be both slow and a second thing to keep correct. Callers that want the
    template untouched parse it again - which is cheap next to what the engine then does with it.
    """
    if template.objects_list is None:
        raise ValueError("the template map has no ObjectsList to append to")

    taken = {_unique_id_of(obj) for obj in template.objects_list.object_list}
    for placement, unique_id in zip(scenario.placements, _unique_ids(scenario, taken), strict=True):
        template.objects_list.object_list.append(placement_object(scenario, placement, unique_id))
    return template
