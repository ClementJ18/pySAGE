"""A mesh drawn with an FX shader material names its texture, colour and alpha test among the
material's properties rather than in a material pass; the render scene reads them there."""

from types import SimpleNamespace

from sage_w3d.mesh import (
    GEOMETRY_TYPE_CAMERA_ALIGNED,
    GEOMETRY_TYPE_CAMERA_ORIENTED,
    GEOMETRY_TYPE_SKIN,
    GEOMETRY_TYPE_TWO_SIDED,
    Shader,
    ShaderMaterial,
    ShaderMaterialProperty,
    ShaderMaterials,
)
from sage_w3d.render.scene import (
    _mesh_additive,
    _mesh_alpha_test,
    _mesh_base_color,
    _mesh_texture_name,
    _mesh_two_sided,
    _mesh_unlit,
)


def prop(prop_type, name, value, length=None):
    return ShaderMaterialProperty(False, prop_type, len(name) + 1, name, length, value)


def mesh(*properties, passes=(), shaders=()):
    materials = ShaderMaterials(True, [ShaderMaterial(True, list(properties))])
    return SimpleNamespace(
        material_passes=list(passes),
        textures=None,
        shader_materials=materials if properties else None,
        vertex_materials=None,
        shaders=list(shaders),
    )


def blend(src, dest):
    """One fixed-pipeline shader record with these blend factors; the rest is left at zero."""
    values = [0] * 16
    values[3], values[7] = dest, src
    return Shader(*values)


def test_an_fx_shader_material_gives_the_texture_colour_and_alpha_test():
    fx = mesh(
        prop(1, "DiffuseTexture", "NBTrollLair.tga", 16),
        prop(1, "NormalMap", "NBTrollLair_NRM.tga", 20),
        prop(5, "DiffuseColor", (0.5, 0.25, 1.0, 1.0)),
        prop(7, "AlphaTestEnable", 1),
    )
    assert _mesh_texture_name(fx) == "NBTrollLair.tga"
    assert _mesh_base_color(fx) == (0.5, 0.25, 1.0, 1.0)
    assert _mesh_alpha_test(fx)


def test_a_mesh_with_neither_material_is_plain_white_and_not_alpha_tested():
    plain = mesh()
    assert _mesh_texture_name(plain) is None
    assert _mesh_base_color(plain) == (1.0, 1.0, 1.0, 1.0)
    assert not _mesh_alpha_test(plain)
    assert not _mesh_additive(plain)
    assert not _mesh_unlit(plain)


def test_a_numbered_texture_slot_names_the_texture_too():
    """`SkyDomeDrkCld1.w3d`: an emissive material whose one picture is `Texture_0`, not
    `DiffuseTexture`. Missing it leaves a sky dome untextured - a white wall over the map."""
    sky = mesh(
        prop(5, "ColorEmissive", (1.0, 1.0, 1.0, 0.0)),
        prop(1, "Texture_0", "SkyDomeDrkCld1.tga", 20),
        prop(7, "DepthWriteEnable", 1),
    )
    assert _mesh_texture_name(sky) == "SkyDomeDrkCld1.tga"
    assert _mesh_unlit(sky)


def test_a_lit_material_is_not_unlit_however_much_it_glows():
    lit = mesh(
        prop(1, "DiffuseTexture", "db_bld1.tga", 12),
        prop(5, "DiffuseColor", (1.0, 1.0, 1.0, 1.0)),
        prop(5, "ColorEmissive", (0.2, 0.2, 0.2, 0.0)),
    )
    assert not _mesh_unlit(lit)


def test_a_billboard_has_no_back_to_cull_but_a_skin_mesh_does():
    """The geometry type is a field inside `attrs`, and a skin mesh's value (0x20000) shares its
    bits with a camera-oriented one's (0x60000), so it has to be matched whole."""
    assert _mesh_two_sided(SimpleNamespace(attrs=GEOMETRY_TYPE_TWO_SIDED))
    assert _mesh_two_sided(SimpleNamespace(attrs=GEOMETRY_TYPE_CAMERA_ALIGNED))
    assert _mesh_two_sided(SimpleNamespace(attrs=GEOMETRY_TYPE_CAMERA_ORIENTED))
    assert not _mesh_two_sided(SimpleNamespace(attrs=GEOMETRY_TYPE_SKIN))
    assert not _mesh_two_sided(SimpleNamespace(attrs=0))
    assert not _mesh_two_sided(None)


def test_a_shader_that_adds_to_the_scene_is_additive_and_unlit():
    """`BB_torch.w3d`'s flame: source ONE onto destination ONE. Its picture is bright on opaque
    black, so mixed in by opacity it would paint a black card over the wall instead."""
    flame = mesh(shaders=[blend(src=1, dest=1)])
    assert _mesh_additive(flame)
    assert _mesh_unlit(flame)
    faded = mesh(shaders=[blend(src=2, dest=5)])
    assert not _mesh_additive(faded)
    assert not _mesh_unlit(faded)
