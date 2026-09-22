"""Placed objects as models: the model a template shows, finding art by name, meshes as GPU
arrays, and where each copy stands. No Qt or OpenGL."""

import math
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from sage_ini.model.enums import LodLevel  # noqa: E402
from sage_w3d.render.scene import RenderMesh, Scene  # noqa: E402
from sage_worldbuilder.lod import (  # noqa: E402
    DEFAULT_LOD_LEVEL,
    current_model_lod,
    draw_is_visible,
)
from sage_worldbuilder.models import (  # noqa: E402
    ArtIndex,
    ObjectModel,
    ObjectModels,
    object_models,
)
from sage_worldbuilder.render.model_mesh import (  # noqa: E402
    ModelGeometry,
    ModelPart,
    aligned_to_terrain,
    instance_matrices,
    load_object_models,
    model_geometry,
    object_scale,
    ray_hit_instances,
    upright_rotations,
)


def state(*models):
    return SimpleNamespace(Model=list(models))


def draw(**groups):
    return SimpleNamespace(**groups)


def test_the_default_condition_state_model_is_shown_first():
    template = SimpleNamespace(
        Draw=[
            draw(
                ModelConditionState=[state("Damaged_SKN")],
                DefaultModelConditionState=[state("Pristine_SKN", "Extra_SKB ExtraMesh:Yes")],
            )
        ]
    )
    assert object_models(template) == (ObjectModel("Pristine_SKN"),)


def test_a_condition_state_model_stands_in_when_there_is_no_default():
    template = SimpleNamespace(Draw=[draw(ModelConditionState=[state(), state("Walls_SKN")])])
    assert object_models(template) == (ObjectModel("Walls_SKN"),)


def test_tree_draws_name_a_model_and_a_texture_and_none_shows_nothing():
    tree = SimpleNamespace(Draw=[draw(ModelName="PTOak01", TextureName="PTOak01.tga")])
    assert object_models(tree) == (ObjectModel("PTOak01", "PTOak01.tga"),)
    hidden = SimpleNamespace(Draw=[draw(DefaultModelConditionState=[state("None")])])
    assert object_models(hidden) == ()
    after_none = SimpleNamespace(
        Draw=[draw(DefaultModelConditionState=[state("None")]), draw(ModelName="Flag")]
    )
    assert object_models(after_none) == (ObjectModel("Flag"),)
    assert object_models(SimpleNamespace(Draw=[])) == ()
    assert object_models(SimpleNamespace()) == ()


def test_every_draw_shows_its_own_model_including_the_floor():
    """A building draws its model and the floor under it, as the engine draws both."""
    template = SimpleNamespace(
        Draw=[
            draw(DefaultModelConditionState=[state("GBBarracks")]),
            draw(ModelName="GBFoundationX"),
            draw(DefaultModelConditionState=[state("None")]),
            draw(ModelName="RBFoundationX"),
        ]
    )
    assert object_models(template) == (
        ObjectModel("GBBarracks"),
        ObjectModel("GBFoundationX"),
        ObjectModel("RBFoundationX"),
    )


_INHERITED_DRAWS = """
Object Parent
    Draw = W3DScriptedModelDraw ModuleTag_Draw
        DefaultModelConditionState
            Model = ParentModel
        End
    End
End

ChildObject PlainChild Parent
End

ChildObject GrandChild PlainChild
End

ChildObject Replacer Parent
    ReplaceModule ModuleTag_Draw
        Draw = W3DScriptedModelDraw ModuleTag_Replaced
            DefaultModelConditionState
                Model = ReplacedModel
            End
        End
    End
End

ChildObject Remover Parent
    RemoveModule ModuleTag_Draw
    Draw = W3DScriptedModelDraw ModuleTag_Own
        DefaultModelConditionState
            Model = OwnModel
        End
    End
End

ChildObject Adder Remover
    RemoveModule ModuleTag_Own
    AddModule
        Draw = W3DTreeDraw ModuleTag_Tree
            ModelName = TreeModel
        End
    End
End
"""


def test_child_objects_show_the_draws_they_inherit_with_their_edits(tmp_path):
    from sage_ini.loader import load_game  # noqa: PLC0415

    ini = tmp_path / "data" / "ini" / "object" / "inherited.ini"
    ini.parent.mkdir(parents=True)
    ini.write_text(_INHERITED_DRAWS, encoding="utf-8")
    models = ObjectModels(load_game(tmp_path).game)

    assert models.get("PlainChild") == (ObjectModel("ParentModel"),)
    assert models.get("GrandChild") == (ObjectModel("ParentModel"),)
    assert models.get("Replacer") == (ObjectModel("ReplacedModel"),)
    assert models.get("Remover") == (ObjectModel("OwnModel"),)
    assert models.get("Adder") == (ObjectModel("TreeModel"),)


def test_object_models_are_found_whatever_the_names_case():
    oak = SimpleNamespace(Draw=[draw(ModelName="PTOak01")])
    models = ObjectModels(SimpleNamespace(objects={"TreeOak": oak}))
    assert models.get("treeoak") == (ObjectModel("PTOak01"),)
    assert models.get("Missing") == ()


class FakeFileSystem:
    def __init__(self, files):
        self.files = files
        self.listed = []

    def listdir(self, folder):
        self.listed.append(folder)
        prefix = folder.lower() + "\\"
        return [
            SimpleNamespace(path=path) for path in self.files if path.lower().startswith(prefix)
        ]

    def read_bytes(self, entry):
        return self.files[entry]


def test_the_art_index_finds_textures_by_name_in_any_folder_and_lists_once():
    files = {
        "art\\compiledtextures\\pt\\PTOak01.dds": b"oak",
        "art\\w3d\\pt\\PTOak01.w3d": b"",
    }
    filesystem = FakeFileSystem(files)
    index = ArtIndex(filesystem)
    assert index.find_texture("ptoak01.tga") == b"oak"
    assert index.find_texture("elm.tga") is None
    assert index.model_path("PTOAK01") == "art\\w3d\\pt\\PTOak01.w3d"
    assert index.find_texture("PTOak01") == b"oak"
    assert filesystem.listed.count("art\\compiledtextures") == 1


def mesh(**overrides):
    fields = {
        "name": "part",
        "positions": [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        "normals": [0.0, 0.0, 1.0] * 3,
        "uvs": [0.0, 0.0, 1.0, 0.0, 0.0, 1.0],
        "indices": [0, 1, 2],
        "texture": "own.tga",
        "color": (1.0, 1.0, 1.0, 1.0),
        "two_sided": False,
        "translucent": False,
        "sort_level": 0,
    }
    fields.update(overrides)
    return RenderMesh(**fields)


def scene(*meshes):
    return Scene(list(meshes), ((0.0, 0.0, 0.0), (1.0, 1.0, 0.0)), [], [])


def test_model_geometry_makes_arrays_and_leaves_out_broken_meshes():
    geometry = model_geometry(
        scene(
            mesh(alpha_test=True),
            mesh(name="empty", indices=[]),
            mesh(name="past", indices=[0, 1, 7]),
            mesh(name="plain", uvs=None, texture="unused.tga"),
        )
    )
    assert len(geometry.parts) == 2
    first, plain = geometry.parts
    assert first.positions.shape == (3, 3) and first.positions.dtype == np.float32
    assert first.uvs.shape == (3, 2) and first.indices.dtype == np.uint32
    assert first.texture == "own.tga" and first.alpha_test
    assert plain.uvs is None and plain.texture is None
    assert geometry.textures() == {"own.tga"}


def test_a_tree_texture_replaces_the_models_own():
    geometry = model_geometry(scene(mesh(), mesh(uvs=None)), texture="bark.tga")
    assert [part.texture for part in geometry.parts] == ["bark.tga", None]


def test_an_objects_scale_is_its_prototype_scale_or_one():
    def placed(value=None):
        properties = {} if value is None else {"objectPrototypeScale": {"value": value}}
        return SimpleNamespace(properties=properties)

    assert object_scale(placed(2.5)) == 2.5
    assert object_scale(placed()) == 1.0
    assert object_scale(placed(0.0)) == 1.0
    assert object_scale(placed("big")) == 1.0


def test_instance_matrices_scale_turn_and_move_a_model():
    matrices = instance_matrices(
        np.array([100.0]),
        np.array([50.0]),
        np.array([12.0]),
        np.array([math.pi / 2]),
        np.array([2.0]),
    )
    assert matrices.shape == (1, 4, 4) and matrices.dtype == np.float32
    tip = matrices[0] @ np.array([1.0, 0.0, 1.0, 1.0])
    # +x turned a quarter anticlockwise is +y; scale 2, then moved.
    assert tip == pytest.approx([100.0, 52.0, 14.0, 1.0], abs=1e-5)


def test_align_to_terrain_is_read_off_the_object():
    def placed(value=None):
        properties = {} if value is None else {"alignToTerrain": {"value": value}}
        return SimpleNamespace(properties=properties)

    assert aligned_to_terrain(placed(True)) is True
    assert aligned_to_terrain(placed(1)) is True
    assert aligned_to_terrain(placed(False)) is False
    assert aligned_to_terrain(placed()) is False


def test_the_upright_rotation_stands_a_model_out_of_a_slope():
    # A slope falling away to the east: its normal leans east, and so does what was straight up.
    normal = np.array([[math.sin(math.radians(30.0)), 0.0, math.cos(math.radians(30.0))]])
    (rotation,) = upright_rotations(normal)
    assert rotation @ np.array([0.0, 0.0, 1.0]) == pytest.approx(normal[0], abs=1e-6)
    # It is a rotation: lengths and angles are kept, and it turns by the slope's own 30 degrees.
    assert rotation @ rotation.T == pytest.approx(np.eye(3), abs=1e-6)
    assert np.linalg.det(rotation) == pytest.approx(1.0)
    # The one axis across the slope is left where it was.
    assert rotation @ np.array([0.0, 1.0, 0.0]) == pytest.approx([0.0, 1.0, 0.0], abs=1e-6)
    # Level ground leaves the model upright.
    assert upright_rotations(np.array([[0.0, 0.0, 1.0]]))[0] == pytest.approx(np.eye(3))


def test_an_aligned_copy_leans_along_the_slope_and_keeps_its_heading():
    slope = math.radians(30.0)
    normals = np.array([[math.sin(slope), 0.0, math.cos(slope)], [0.0, 0.0, 1.0]])
    matrices = instance_matrices(
        np.array([0.0, 0.0]),
        np.array([0.0, 0.0]),
        np.array([0.0, 0.0]),
        np.array([0.0, 0.0]),
        np.array([1.0, 1.0]),
        normals,
    )
    # The aligned copy's up is the slope's normal; the other stands straight up.
    assert matrices[0] @ np.array([0.0, 0.0, 1.0, 0.0]) == pytest.approx(
        [*normals[0], 0.0], abs=1e-6
    )
    assert matrices[1] @ np.array([0.0, 0.0, 1.0, 0.0]) == pytest.approx([0, 0, 1, 0], abs=1e-6)
    # Without normals the matrices are the upright ones, unchanged.
    plain = instance_matrices(
        np.array([7.0]), np.array([3.0]), np.array([1.0]), np.array([0.5]), np.array([2.0])
    )
    assert plain == pytest.approx(
        instance_matrices(
            np.array([7.0]),
            np.array([3.0]),
            np.array([1.0]),
            np.array([0.5]),
            np.array([2.0]),
            np.array([[0.0, 0.0, 1.0]]),
        ),
        abs=1e-6,
    )


def box_geometry(additive=False):
    """A unit cube centred on the origin, as twelve triangles."""
    corners = np.array(
        [(x, y, z) for x in (-0.5, 0.5) for y in (-0.5, 0.5) for z in (-0.5, 0.5)],
        dtype=np.float32,
    )
    faces = [
        (0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5),
        (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6),
        (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3),
    ]  # fmt: skip
    part = ModelPart(
        positions=corners,
        normals=np.zeros_like(corners),
        uvs=None,
        indices=np.array(faces, dtype=np.uint32).ravel(),
        texture=None,
        color=(1.0, 1.0, 1.0, 1.0),
        two_sided=False,
        translucent=False,
        alpha_test=False,
        additive=additive,
    )
    return ModelGeometry((part,))


def cubes(*placements):
    xs, ys, zs, scales = (
        np.array(values, dtype=np.float64) for values in zip(*placements, strict=True)
    )
    return instance_matrices(xs, ys, zs, np.zeros_like(xs), scales)


def test_a_ray_picks_the_nearest_copy_of_a_model_it_passes_through():
    matrices = cubes((0, 0, 0, 1), (10, 0, 0, 1), (5, 0, 0, 1))
    down = np.array([0.0, 0.0, -1.0])
    assert ray_hit_instances(box_geometry(), matrices, np.array([10.0, 0.2, 20.0]), down) == (
        1,
        pytest.approx(19.5),
    )
    # Along the row from the -x side, the cube at x=0 stands first.
    along = np.array([1.0, 0.0, 0.0])
    assert ray_hit_instances(box_geometry(), matrices, np.array([-20.0, 0.0, 0.1]), along) == (
        0,
        pytest.approx(19.5),
    )
    assert ray_hit_instances(box_geometry(), matrices, np.array([2.5, 0.0, 20.0]), down) is None


def test_a_ray_meets_a_copy_as_it_is_scaled_and_placed():
    matrices = cubes((0, 0, 3, 4))
    hit = ray_hit_instances(
        box_geometry(), matrices, np.array([1.8, 0.0, 20.0]), np.array([0.0, 0.0, -1.0])
    )
    # The cube is four units wide about z=3, so its top is at z=5.
    assert hit == (0, pytest.approx(15.0))
    behind = ray_hit_instances(
        box_geometry(), matrices, np.array([0.0, 0.0, 20.0]), np.array([0.0, 0.0, 1.0])
    )
    assert behind is None


def test_a_glow_is_not_something_a_click_lands_on():
    matrices = cubes((0, 0, 0, 1))
    origin, down = np.array([0.0, 0.0, 5.0]), np.array([0.0, 0.0, -1.0])
    assert ray_hit_instances(box_geometry(additive=True), matrices, origin, down) is None


def named_state(flags, *models, skeleton=None):
    state = SimpleNamespace(name=flags, Model=list(models))
    if skeleton is not None:
        state.Skeleton = skeleton
    return state


def test_a_world_builder_state_is_shown_over_the_default_with_its_skeleton():
    template = SimpleNamespace(
        Draw=[
            draw(DefaultModelConditionState=[named_state(None, "Pristine_SKN")]),
            draw(
                DefaultModelConditionState=[named_state(None, "None")],
                ModelConditionState=[
                    named_state("DAMAGED", "Damaged_SKN"),
                    named_state("WORLD_BUILDER", "Mounted_SKN", skeleton="MUMount_SKL"),
                ],
            ),
        ]
    )
    assert object_models(template) == (
        ObjectModel("Pristine_SKN"),
        ObjectModel("Mounted_SKN", skeleton="MUMount_SKL"),
    )


def test_a_world_builder_state_showing_nothing_leaves_the_other_draws():
    template = SimpleNamespace(
        Draw=[
            draw(ModelConditionState=[named_state("WORLD_BUILDER", "None")]),
            draw(DefaultModelConditionState=[named_state(None, "Flag", skeleton="Flag_SKL")]),
        ]
    )
    assert object_models(template) == (ObjectModel("Flag", skeleton="Flag_SKL"),)


def test_with_the_world_builder_toggle_off_every_draw_shows_its_default():
    template = SimpleNamespace(
        Draw=[
            draw(
                DefaultModelConditionState=[named_state(None, "Pristine_SKN", skeleton="Foot_SKL")],
                ModelConditionState=[named_state("WORLD_BUILDER", "Mounted_SKN")],
            ),
        ]
    )
    assert object_models(template, world_builder=False) == (
        ObjectModel("Pristine_SKN", skeleton="Foot_SKL"),
    )
    models = ObjectModels(SimpleNamespace(objects={"Rider": template}), world_builder=False)
    assert models.get("Rider") == (ObjectModel("Pristine_SKN", skeleton="Foot_SKL"),)
    assert ObjectModels(SimpleNamespace(objects={"Rider": template})).get("Rider") == (
        ObjectModel("Mounted_SKN"),
    )


def test_a_draw_whose_minlodrequired_outranks_the_model_lod_is_left_out():
    template = SimpleNamespace(
        Draw=[
            draw(DefaultModelConditionState=[state("Base")]),
            draw(DefaultModelConditionState=[state("Detail")], MinLODRequired=LodLevel.High),
        ]
    )
    assert object_models(template, model_lod=LodLevel.Medium) == (ObjectModel("Base"),)
    assert object_models(template, model_lod=LodLevel.High) == (
        ObjectModel("Base"),
        ObjectModel("Detail"),
    )
    # No model_lod given: DEFAULT_LOD_LEVEL is Ultra High, which shows every draw - today's
    # behaviour, unchanged for a caller that never asks about LOD.
    assert object_models(template) == (ObjectModel("Base"), ObjectModel("Detail"))


def test_minlodrequired_ranks_backwards_from_lodlevels_own_member_order():
    """0x0222EEBC, not `LodLevel`'s own member order: VeryLow sorts last, so a draw that
    requires it shows only at the VeryLow model LOD itself, not at anything above Low."""
    template = SimpleNamespace(
        Draw=[draw(DefaultModelConditionState=[state("Coarse")], MinLODRequired=LodLevel.VeryLow)]
    )
    for hidden_at in (LodLevel.Low, LodLevel.Medium, LodLevel.High, LodLevel.UltraHigh):
        assert object_models(template, model_lod=hidden_at) == ()
    assert object_models(template, model_lod=LodLevel.VeryLow) == (ObjectModel("Coarse"),)


def test_a_draw_with_no_minlodrequired_always_shows():
    template = SimpleNamespace(Draw=[draw(DefaultModelConditionState=[state("Plain")])])
    assert object_models(template, model_lod=LodLevel.VeryLow) == (ObjectModel("Plain"),)


def test_draw_is_visible_ignores_a_value_that_is_not_a_lodlevel():
    assert draw_is_visible(None, LodLevel.Low) is True
    assert draw_is_visible("High", LodLevel.Low) is True


def test_current_model_lod_falls_back_to_ultra_high_with_nothing_to_read():
    assert current_model_lod(None, LodLevel.VeryLow) is DEFAULT_LOD_LEVEL
    # A minimal game double with no `tables` at all - the shape every `ObjectModels` test above
    # already constructs with `SimpleNamespace(objects=...)` - falls back the same way.
    assert current_model_lod(SimpleNamespace(), LodLevel.VeryLow) is DEFAULT_LOD_LEVEL
    no_bucket = SimpleNamespace(tables={"staticgamelods": {}})
    assert current_model_lod(no_bucket, LodLevel.VeryLow) is DEFAULT_LOD_LEVEL
    no_field = SimpleNamespace(tables={"staticgamelods": {"VeryLow": SimpleNamespace()}})
    assert current_model_lod(no_field, LodLevel.VeryLow) is DEFAULT_LOD_LEVEL


def test_current_model_lod_reads_the_bucket_named_after_the_level():
    # gamelod.ini's own StaticGameLOD = VeryLow bucket sets ModelLOD = Low, not VeryLow.
    bucket = SimpleNamespace(ModelLOD=LodLevel.Low)
    game = SimpleNamespace(tables={"staticgamelods": {"VeryLow": bucket}})
    assert current_model_lod(game, LodLevel.VeryLow) is LodLevel.Low


def test_object_models_resolves_the_model_lod_from_the_game_and_filters_through_it():
    template = SimpleNamespace(
        Draw=[
            draw(DefaultModelConditionState=[state("Base")]),
            draw(DefaultModelConditionState=[state("Detail")], MinLODRequired=LodLevel.High),
        ]
    )
    bucket = SimpleNamespace(ModelLOD=LodLevel.Medium)
    game = SimpleNamespace(objects={"Tower": template}, tables={"staticgamelods": {"Low": bucket}})
    models = ObjectModels(game, level=LodLevel.Low)
    assert models.model_lod is LodLevel.Medium
    assert models.get("Tower") == (ObjectModel("Base"),)


def test_the_state_that_best_fits_the_conditions_is_shown():
    from sage_worldbuilder.models import model_key  # noqa: PLC0415

    template = SimpleNamespace(
        Draw=[
            draw(
                DefaultModelConditionState=[named_state(None, "Pristine")],
                ModelConditionState=[
                    named_state("DAMAGED", "Damaged"),
                    named_state("NIGHT", "Night"),
                    named_state("DAMAGED NIGHT", "DamagedNight"),
                    named_state("GARRISONED", "Garrisoned"),
                    named_state("NIGHT SNOW", "NightSnow"),
                ],
            )
        ]
    )
    shown = {
        flags: object_models(template, conditions=frozenset(flags.split()))[0].model
        for flags in ("", "DAMAGED", "NIGHT", "DAMAGED NIGHT", "GARRISONED", "SNOW", "RUBBLE")
    }
    assert shown == {
        "": "Pristine",
        "DAMAGED": "Damaged",
        "NIGHT": "Night",
        "DAMAGED NIGHT": "DamagedNight",
        "GARRISONED": "Garrisoned",
        # SNOW alone fits NIGHT SNOW by one flag, more than the default's none.
        "SNOW": "NightSnow",
        "RUBBLE": "Pristine",
    }
    models = ObjectModels(SimpleNamespace(objects={"Tower": template}))
    key = model_key("Tower", frozenset({"NIGHT", "DAMAGED"}))
    assert models.get(key)[0].model == "DamagedNight"
    assert model_key("Tower", frozenset()) == "Tower"


def test_an_objects_model_conditions_follow_its_health_time_weather_and_the_map():
    from sage_worldbuilder.models import MapConditions, model_conditions  # noqa: PLC0415

    def stored(**values):
        return {key: {"name": key, "type": None, "value": value} for key, value in values.items()}

    plain = MapConditions()
    assert model_conditions({}, plain) == frozenset()
    assert model_conditions(stored(objectInitialHealth=50), plain) == {"DAMAGED"}
    assert model_conditions(stored(objectInitialHealth=51), plain) == frozenset()
    assert model_conditions(stored(objectInitialHealth=10), plain) == {"REALLYDAMAGED"}
    assert model_conditions(stored(objectInitialHealth=0), plain) == {"RUBBLE"}
    assert model_conditions(stored(objectTime=2, objectWeather=2), plain) == {"NIGHT", "SNOW"}
    # An object's own day does not undo the map's night.
    night = MapConditions(night=True, garrisoned=True)
    assert model_conditions(stored(objectTime=1), night) == {"NIGHT", "GARRISONED"}
    data = SimpleNamespace(UnitDamagedThreshold=0.7, UnitReallyDamagedThreshold=0.3)
    game = SimpleNamespace(tables={"gamedatas": {"GameData": data}})
    thresholds = MapConditions.of_game(game)
    assert (thresholds.damaged, thresholds.really_damaged) == (0.7, 0.3)
    assert model_conditions(stored(objectInitialHealth=30), thresholds) == {"REALLYDAMAGED"}


def test_an_object_draws_the_meshes_of_every_model_it_shows():
    """The building and the floor under it are one mesh list at the object's own place; a draw
    whose model is missing is left out and the others still draw."""

    class Models:
        def get(self, name):
            return (
                ObjectModel("GBBarracks"),
                ObjectModel("GBFoundationX", texture="floor.tga"),
                ObjectModel("Missing"),
            )

    class Art:
        def find_model(self, name):
            return None if name == "Missing" else name

        def find_texture(self, name):  # noqa: ARG002
            return None

    def build(model, art, skeleton):  # noqa: ARG001
        return scene(mesh(name=model), mesh(name=f"{model}2"))

    import sage_worldbuilder.render.model_mesh as module  # noqa: PLC0415

    built = module.build_scene
    module.build_scene = build
    try:
        geometry, textures = load_object_models(["GondorBarracks"], Models(), Art())
    finally:
        module.build_scene = built

    parts = geometry["GondorBarracks"].parts
    assert len(parts) == 4
    # The second model's `TextureName` replaces its own meshes' textures, not the first model's.
    assert [part.texture for part in parts] == ["own.tga", "own.tga", "floor.tga", "floor.tga"]
    assert set(textures) == {"own.tga", "floor.tga"}


def test_an_object_whose_every_model_is_missing_has_no_geometry():
    class Models:
        def get(self, name):
            return (ObjectModel("Missing"),)

    class Art:
        def find_model(self, name):
            return None

    geometry, _ = load_object_models(["Ghost"], Models(), Art())
    assert geometry["Ghost"] is None
