"""The typed script-argument layer over `sagemap`.

These are pure-data tests of `ARG_SPECS` / `typed_value` - no `Game`, no `.map` file needed.
"""

import pytest

from sage_map import ARG_SPECS, Scope, arg_spec, build_symbols, typed_value
from sage_map.assets.player_scripts import ScriptArgument, ScriptArgumentType
from sage_map.map import Map


def test_every_argument_type_has_a_spec():
    """`arg_spec` is total over the enum: an unmapped type falls back to a non-resolving literal."""
    for arg_type in ScriptArgumentType:
        spec = arg_spec(arg_type)
        assert isinstance(spec.scope, Scope)
        # The fallback never claims a resolvable scope it has no target for.
        if spec.scope in (Scope.GAME, Scope.MAP, Scope.ENUM):
            assert spec.target, f"{arg_type.name} is {spec.scope} but has no target"


def test_reference_scopes_read_the_string_slot():
    """Every GAME/MAP/STRINGS argument resolves a name, so it must read `string_value`."""
    for arg_type, spec in ARG_SPECS.items():
        if spec.scope in (Scope.GAME, Scope.MAP, Scope.STRINGS):
            assert spec.field == "string_value", arg_type.name


@pytest.mark.parametrize(
    "arg_type, scope, target",
    [
        (ScriptArgumentType.OBJECT_TYPE, Scope.GAME, "objects"),
        (ScriptArgumentType.SCIENCE_NAME, Scope.GAME, "sciences"),
        (ScriptArgumentType.UPGRADE_NAME, Scope.GAME, "upgrades"),
        (ScriptArgumentType.COMMAND_BUTTON_NAME, Scope.GAME, "commandbuttons"),
        (ScriptArgumentType.SPECIAL_POWER_NAME, Scope.GAME, "specialpowers"),
        # The two ability-argument types both name a CommandButton, and HERO names a template.
        (ScriptArgumentType.UNIT_ABILITY_NAME, Scope.GAME, "commandbuttons"),
        (ScriptArgumentType.TEAM_ABILITY_NAME, Scope.GAME, "commandbuttons"),
        (ScriptArgumentType.HERO, Scope.GAME, "objects"),
        # Created by the action that first names them, so untracked rather than dangling.
        (ScriptArgumentType.OBJECT_TYPE_LIST_NAME, Scope.MAP, "object_type_lists"),
        (ScriptArgumentType.MAP_REVEAL_NAME, Scope.MAP, "map_reveals"),
        # A side name (`Rohan`), not a PlayerTemplate name - a named set, not a game table.
        (ScriptArgumentType.FACTION_NAME, Scope.ENUM, "Side"),
        (ScriptArgumentType.TEAM_NAME, Scope.MAP, "teams"),
        (ScriptArgumentType.WAYPOINT_NAME, Scope.MAP, "waypoints"),
        (ScriptArgumentType.SCRIPT_NAME, Scope.MAP, "scripts"),
        (ScriptArgumentType.LOCALIZED_STRING_NAME, Scope.STRINGS, None),
    ],
)
def test_known_mappings(arg_type, scope, target):
    spec = arg_spec(arg_type)
    assert spec.scope is scope
    assert spec.target == target


def _arg(arg_type, *, int_value=0, float_value=0.0, string_value="", position_value=None):
    return ScriptArgument(
        type=arg_type,
        int_value=int_value,
        float_value=float_value,
        string_value=string_value,
        position_value=position_value,
    )


def test_typed_value_selects_the_string_payload_for_references():
    arg = _arg(ScriptArgumentType.OBJECT_TYPE, string_value="GondorFighter", int_value=99)
    resolved = typed_value(arg)
    assert resolved.spec.scope is Scope.GAME
    assert resolved.value == "GondorFighter"


def test_typed_value_selects_numeric_and_position_payloads():
    integer = typed_value(_arg(ScriptArgumentType.INTEGER, int_value=42, string_value="x"))
    assert integer.value == 42 and integer.spec.scope is Scope.LITERAL

    coord = _arg(ScriptArgumentType.POSITION_COORDINATE, position_value=(1.0, 2.0, 3.0))
    assert typed_value(coord).value == (1.0, 2.0, 3.0)


def test_script_created_targets_are_not_resolvable():
    """An object-type list and a permanent map reveal are named by the action that creates them,
    so a name the map does not otherwise declare is not a dangling reference."""
    symbols = build_symbols(Map())
    assert symbols.resolve("object_type_lists", "GG-EvilUnits") is None
    assert symbols.resolve("map_reveals", "Reveal_the_sky") is None
    assert symbols.resolve("attack_priority_sets", "anything") is None


def test_every_argument_type_is_accounted_for():
    """A type absent from ARG_SPECS falls back to a plain string literal, which silently skips
    it. Only the types with no corpus evidence may do that."""
    unmapped = {t.name for t in ScriptArgumentType if t not in ARG_SPECS}
    assert unmapped == {
        "BRIDGE_NAME",
        "SKIRMISH_APPROACH_PATH",
        "THREAT_FINDER_NAME",
        "STANCE",
        "EVA",
        "UNKNOWN_29",
        "UNKNOWN_53",
        "UNKNOWN_65",
        "UNKNOWN_66",
        "UNKNOWN_69",
        "UNKNOWN_70",
        "UNKNOWN_71",
        "UNKNOWN_72",
        "UNKNOWN_73",
        "UNKNOWN_74",
        "UNKNOWN_75",
    }
