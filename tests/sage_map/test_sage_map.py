"""Phase 1: the typed script-argument layer over `sagemap`.

These are pure-data tests of `ARG_SPECS` / `typed_value` - no `Game`, no `.map` file needed.
"""

import pytest

from sage_map import ARG_SPECS, Scope, arg_spec, typed_value
from sage_map.assets.player_scripts import ScriptArgument, ScriptArgumentType


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
        (ScriptArgumentType.FACTION_NAME, Scope.GAME, "factions"),
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
