"""Unit tests for the typed object layer (sage_ini.model.objects, sage_ini.model.game).

Fields are declared as annotations and stored raw at construction; conversion
happens lazily when a field is read. These tests use small local classes to
pin the machinery independent of the ported game-data definitions.
"""

import pytest

from sage_ini.model.enums import GeometryType
from sage_ini.model.game import Game
from sage_ini.model.ini_objects import ChildObject, Object
from sage_ini.model.objects import REGISTRY, IniObject, MarkerGroup, NestedAttribute, get_class
from sage_ini.model.types import Bool, Float, Int, List, String
from sage_ini.parser.ast import Block
from sage_ini.parser.blockparser import parse
from sage_ini.parser.diagnostics import Severity


class PlayThing(IniObject):
    key = "playthings"

    Cost: Int = 0
    Speed: Float
    Enabled: Bool = False
    Label: String
    Tags: List[String]


class PlayGizmo(IniObject):
    key = "playgizmos"

    Owner: "PlayThing"


class Keyless(IniObject):
    Note: String


class PlayPart(IniObject):
    Strength: Int


class PlayModule(IniObject):
    Power: Int


class PlaySpecialModule(PlayModule):
    Extra: Int


class PlayMachine(IniObject):
    key = "playmachines"

    nested_attributes = {"Parts": [PlayPart]}

    Title: String


class PlayAliased(IniObject):
    key = "playaliased"

    Regen_PerSecond: Float

    # The engine key has a literal `%`, not a valid Python identifier.
    field_aliases = {"Regen%PerSecond": "Regen_PerSecond"}


def block_of(text: str):
    result = parse(text, file="t.ini")
    assert not result.diagnostics
    return result.document.children[0]


def build(cls, text: str, game: Game | None = None):
    return cls.from_block(game or Game(), block_of(text))


class TestRegistry:
    def test_subclasses_register_by_name(self):
        assert REGISTRY["PlayThing"] is PlayThing
        assert get_class("PlayGizmo") is PlayGizmo

    def test_unknown_name_is_none(self):
        assert get_class("NoSuchClass") is None

    def test_key_defaults_to_none(self):
        assert IniObject.key is None
        assert Keyless.key is None


class TestConstruction:
    def test_name_from_label(self):
        obj = build(PlayThing, "PlayThing Sword\n    Cost = 5\nEnd")
        assert obj.name == "Sword"

    def test_registers_into_game_table(self):
        game = Game()
        obj = build(PlayThing, "PlayThing Sword\nEnd", game)
        assert game.tables["playthings"]["Sword"] is obj

    def test_keyless_object_does_not_register_and_does_not_raise(self):
        game = Game()
        obj = build(Keyless, "Keyless Foo\n    Note = hi\nEnd", game)
        assert obj.name == "Foo"
        assert game.tables == {}

    def test_construction_never_converts(self):
        # a malformed Int value must not raise at construction, only on access
        obj = build(PlayThing, "PlayThing Sword\n    Cost = notanumber\nEnd")
        assert isinstance(obj, PlayThing)
        with pytest.raises(ValueError):
            _ = obj.Cost


class TestLazyConversion:
    def test_int_float_bool_string(self):
        obj = build(
            PlayThing,
            """\
            PlayThing Sword
                Cost = 5
                Speed = 12.5
                Enabled = Yes
                Label = OBJECT:Sword
            End
            """,
        )
        assert obj.Cost == 5
        assert obj.Speed == 12.5
        assert obj.Enabled is True
        assert obj.Label == "OBJECT:Sword"

    def test_list_field_splits(self):
        obj = build(PlayThing, "PlayThing Sword\n    Tags = alpha beta gamma\nEnd")
        assert obj.Tags == ["alpha", "beta", "gamma"]

    def test_default_used_when_absent(self):
        obj = build(PlayThing, "PlayThing Sword\nEnd")
        assert obj.Cost == 0
        assert obj.Enabled is False

    def test_annotated_but_absent_without_default_is_none(self):
        obj = build(PlayThing, "PlayThing Sword\nEnd")
        assert obj.Speed is None
        assert obj.Label is None

    def test_present_value_overrides_default(self):
        obj = build(PlayThing, "PlayThing Sword\n    Cost = 9\nEnd")
        assert obj.Cost == 9

    def test_unannotated_attribute_raises_attributeerror(self):
        obj = build(PlayThing, "PlayThing Sword\nEnd")
        with pytest.raises(AttributeError):
            _ = obj.NotAField


class TestUnknownContent:
    def test_unknown_attributes_are_kept_not_dropped(self):
        obj = build(
            PlayThing,
            "PlayThing Sword\n    Cost = 5\n    Mystery = 42\nEnd",
        )
        assert "Mystery" not in type(obj)._fieldspec
        assert obj.fields["Mystery"] == "42"

    def test_unknown_sub_blocks_are_kept_in_extras(self):
        obj = build(
            PlayThing,
            "PlayThing Sword\n    SomeBlock\n        X = 1\n    End\nEnd",
        )
        kept = [n for n in obj.extras if isinstance(n, Block)]
        assert [b.name for b in kept] == ["SomeBlock"]


class TestFieldAliases:
    def test_non_identifier_key_is_stored_under_its_alias(self):
        obj = build(PlayAliased, "PlayAliased X\n    Regen%PerSecond = 0.5%\nEnd")
        assert "Regen_PerSecond" in obj.fields
        assert "Regen%PerSecond" not in obj.fields  # the raw key is renamed, not duplicated

    def test_aliased_field_converts(self):
        obj = build(PlayAliased, "PlayAliased X\n    Regen%PerSecond = 0.5%\nEnd")
        assert obj.Regen_PerSecond == 0.005  # `%` value converts as a fraction

    def test_alias_is_accumulated_into_field_aliases(self):
        assert PlayAliased._field_aliases == {"Regen%PerSecond": "Regen_PerSecond"}

    def test_aliased_field_drives_validation_without_error(self):
        game = Game()
        build(PlayAliased, "PlayAliased X\n    Regen%PerSecond = 0.5%\nEnd", game)
        diagnostics = game.validate()
        assert not diagnostics  # the field converts cleanly: no conversion-error


class TestRepeatedKeys:
    def test_repeated_key_becomes_list_of_raws(self):
        obj = build(PlayThing, "PlayThing Sword\n    Tags = a\n    Tags = b\nEnd")
        assert obj.Tags == ["a", "b"]


class TestCrossReference:
    def test_reference_resolves_through_game_table(self):
        game = Game()
        sword = build(PlayThing, "PlayThing Sword\nEnd", game)
        gizmo = build(PlayGizmo, "PlayGizmo Hilt\n    Owner = Sword\nEnd", game)
        assert gizmo.Owner is sword

    def test_dangling_reference_raises_on_access(self):
        game = Game()
        gizmo = build(PlayGizmo, "PlayGizmo Hilt\n    Owner = Missing\nEnd", game)
        with pytest.raises(KeyError):
            _ = gizmo.Owner


MACHINE = """\
PlayMachine Big
    Title = OBJECT:Big
    PlayPart Alpha
        Strength = 3
    End
    Behavior = PlayModule Tag1
        Power = 9
    End
    Behavior = PlaySpecialModule Tag2
        Power = 4
        Extra = 1
    End
    UnknownThing Z
        Q = 1
    End
End
"""


class TestNesting:
    def test_named_subblock_routes_into_declared_group(self):
        machine = build(PlayMachine, MACHINE)
        assert [type(p).__name__ for p in machine.Parts] == ["PlayPart"]
        assert machine.Parts[0].Strength == 3

    def test_module_block_types_from_label_token(self):
        # `Behavior = PlayModule Tag` -> the type is the first label token
        machine = build(PlayMachine, MACHINE)
        assert [type(m).__name__ for m in machine.modules] == [
            "PlayModule",
            "PlaySpecialModule",
        ]
        assert machine.modules[0].Power == 9
        assert machine.modules[1].Extra == 1

    def test_unrecognized_subblock_stays_generic(self):
        machine = build(PlayMachine, MACHINE)
        assert [b.name for b in machine.extras if isinstance(b, Block)] == ["UnknownThing"]

    def test_empty_group_returns_empty_list(self):
        machine = build(PlayMachine, "PlayMachine Bare\nEnd")
        assert machine.Parts == []
        assert machine.modules == []

    def test_subclass_in_group_allowed_list_matches(self):
        # a group listing a base class also collects subclass instances
        class PlayKit(IniObject):
            key = None
            nested_attributes = {"Mods": [PlayModule]}

        kit = build(
            PlayKit,
            "PlayKit K\n    Behavior = PlaySpecialModule T\n        Power = 1\n    End\nEnd",
        )
        assert [type(m).__name__ for m in kit.Mods] == ["PlaySpecialModule"]

    def test_subblock_override_reclassifies_child_and_skips_global_table(self):
        # A child block sharing a keyword with a registered global type (`PlayThing`) is built
        # as the class the parent claims for it, and never registers into the global table.
        class PlayThingArt(NestedAttribute):
            nested_attributes = {}  # keyless: not a standalone object
            Note: String

        class PlayFrame(IniObject):
            key = "playframes"
            nested_attributes = {"PlayThing": [PlayThingArt]}
            subblock_overrides = {"PlayThing": PlayThingArt}

        game = Game()
        frame = build(
            PlayFrame,
            "PlayFrame F\n    PlayThing Decor\n        Note = hi\n    End\nEnd",
            game,
        )
        # routed into the declared group as the override type, not the global PlayThing...
        assert [type(o).__name__ for o in frame.PlayThing] == ["PlayThingArt"]
        assert frame.PlayThing[0].Note == "hi"
        # ...and it did not leak into the global `playthings` table.
        assert "playthings" not in game.tables

    def test_child_without_override_still_registers_globally(self):
        # Without a declared override, a child block keyed to a registered type builds and
        # registers it as usual — the override is opt-in per parent.
        class PlainFrame(IniObject):
            key = "plainframes"

        game = Game()
        build(PlainFrame, "PlainFrame F\n    PlayThing Real\n        Cost = 2\n    End\nEnd", game)
        assert "Real" in game.tables["playthings"]


class PlayShapes(IniObject):
    key = "playshapes"

    Size: Int

    marker_groups = {
        "shapes": MarkerGroup(
            markers=("Shape", "AddShape"),
            keys=("ShapeName", "ShapeRadius", "ShapeHeight"),
        ),
    }


SHAPES = """\
PlayShapes Tower
    Size = 3
    Shape = CYLINDER
        ShapeRadius = 15
        ShapeHeight = 100
    AddShape = BOX
        ShapeName = Closed
        ShapeRadius = 16
    AddShape = BOX
        ShapeName = Open
        ShapeHeight = 40
End
"""


class TestMarkerGroups:
    def test_each_marker_starts_a_new_item(self):
        obj = build(PlayShapes, SHAPES)
        assert [s.value for s in obj.shapes] == ["CYLINDER", "BOX", "BOX"]
        assert [s.marker for s in obj.shapes] == ["Shape", "AddShape", "AddShape"]

    def test_grouped_keys_attach_to_current_item_without_collapsing(self):
        obj = build(PlayShapes, SHAPES)
        # Repeated keys across shapes stay distinct instead of overwriting.
        assert obj.shapes[0].fields == {"ShapeRadius": "15", "ShapeHeight": "100"}
        assert obj.shapes[1].fields == {"ShapeName": "Closed", "ShapeRadius": "16"}
        assert obj.shapes[2].fields == {"ShapeName": "Open", "ShapeHeight": "40"}

    def test_grouped_keys_are_kept_out_of_flat_fields(self):
        obj = build(PlayShapes, SHAPES)
        assert "ShapeRadius" not in obj.fields
        assert obj.fields == {"Size": "3"}
        assert obj.Size == 3

    def test_absent_group_returns_empty_list(self):
        obj = build(PlayShapes, "PlayShapes Bare\n    Size = 1\nEnd")
        assert obj.shapes == []

    def test_real_object_geometry_is_typed_per_shape(self):
        obj = build(
            Object,
            """\
            Object Pillars
                Geometry = CYLINDER
                GeometryMajorRadius = 15.0
                GeometryOffset = X:0 Y:60 Z:0
                AdditionalGeometry = CYLINDER
                GeometryMajorRadius = 15.0
                GeometryOffset = X:0 Y:-60 Z:0
                AdditionalGeometry = BOX
                GeometryName = Closed
                GeometryMinorRadius = 115.0
                GeometryIsSmall = No
            End
            """,
        )
        assert [s.type for s in obj.geometry] == [
            GeometryType.CYLINDER,
            GeometryType.CYLINDER,
            GeometryType.BOX,
        ]
        assert [s.is_primary for s in obj.geometry] == [True, False, False]
        # Per-shape values convert with their declared types.
        assert obj.geometry[0].GeometryMajorRadius == 15.0
        assert obj.geometry[0].GeometryOffset == [0.0, 60.0, 0.0]
        assert obj.geometry[2].GeometryName == "Closed"
        assert obj.geometry[2].GeometryMinorRadius == 115.0
        # An unset per-shape field is None, not inherited from another shape.
        assert obj.geometry[1].GeometryName is None
        # GeometryIsSmall is a per-shape key: it scopes to the shape it follows
        # (here the third) and is None on shapes that did not set it.
        assert obj.geometry[2].GeometryIsSmall is False
        assert obj.geometry[0].GeometryIsSmall is None

    def test_bogus_geometry_type_is_diagnosed_on_validate(self):
        game = Game()
        build(Object, "Object X\n    Geometry = PYRAMID\n    GeometryHeight = 5\nEnd", game)
        diags = list(game.validate())
        assert "conversion-error" in [d.code for d in diags]
        assert any("GeometryShape.type" in d.message for d in diags)

    def test_valid_geometry_type_produces_no_diagnostic(self):
        game = Game()
        build(Object, "Object X\n    Geometry = BOX\n    GeometryHeight = 5\nEnd", game)
        assert list(game.validate()) == []


class TestHeaderExtras:
    def test_extra_header_token_names_by_first_and_warns(self):
        # `Object Foo Bar` declares an object named Foo; the engine ignores the
        # trailing `Bar`, and we flag it rather than misname the object "Foo Bar".
        game = Game()
        obj = build(Object, "Object Foo Bar\nEnd", game)
        assert obj.name == "Foo"
        assert "Foo" in game.objects
        extras = [d for d in game.validate() if d.code == "extra-header-tokens"]
        assert len(extras) == 1
        assert extras[0].severity is Severity.WARNING
        assert "Bar" in extras[0].message

    def test_single_token_header_has_no_extras(self):
        game = Game()
        build(Object, "Object Foo\nEnd", game)
        assert [d for d in game.validate() if d.code == "extra-header-tokens"] == []

    def test_child_object_parent_token_is_not_extra(self):
        # `ChildObject Name Parent` consumes two tokens by design; only a third
        # would be flagged.
        game = Game()
        obj = build(ChildObject, "ChildObject Foo Parent\nEnd", game)
        assert obj.name == "Foo"
        assert obj.parent_name == "Parent"
        assert [d for d in game.validate() if d.code == "extra-header-tokens"] == []

    def test_child_object_third_token_is_extra(self):
        game = Game()
        build(ChildObject, "ChildObject Foo Parent Junk\nEnd", game)
        extras = [d for d in game.validate() if d.code == "extra-header-tokens"]
        assert len(extras) == 1
        assert "Junk" in extras[0].message


class TestLoadDocument:
    def test_builds_known_top_level_blocks(self):
        game = Game()
        game.load_document(
            parse("PlayThing A\nEnd\nPlayThing B\nEnd\nUnknownThing C\nEnd").document
        )
        assert set(game.tables["playthings"]) == {"A", "B"}

    def test_macro_definitions_are_recorded(self):
        game = Game()
        game.load_document(parse("#define BIG 500\n").document)
        assert game.macros["BIG"] == "500"
