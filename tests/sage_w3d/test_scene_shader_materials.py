"""A mesh drawn with an FX shader material names its texture, colour and alpha test among the
material's properties rather than in a material pass; the render scene reads them there."""

from types import SimpleNamespace

from sage_w3d.mesh import ShaderMaterial, ShaderMaterialProperty, ShaderMaterials
from sage_w3d.render.scene import _mesh_alpha_test, _mesh_base_color, _mesh_texture_name


def prop(prop_type, name, value, length=None):
    return ShaderMaterialProperty(False, prop_type, len(name) + 1, name, length, value)


def mesh(*properties, passes=()):
    materials = ShaderMaterials(True, [ShaderMaterial(True, list(properties))])
    return SimpleNamespace(
        material_passes=list(passes),
        textures=None,
        shader_materials=materials if properties else None,
        vertex_materials=None,
        shaders=[],
    )


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
