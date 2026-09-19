"""A model without its own hierarchy is posed on a skeleton named by the caller before the one
its HLOD names: a game object's condition state binds a skinned model to a skeleton."""

from types import SimpleNamespace

from sage_w3d.mesh import VertexInfluence
from sage_w3d.render.scene import _influence_pair, _resolve_hierarchy


def test_an_influence_with_no_weights_follows_its_bone_fully():
    rigid = VertexInfluence(bone_idx=3, xtra_idx=0, bone_weight_raw=0, xtra_weight_raw=0)
    assert _influence_pair(rigid, 5) == (3, 1.0, 0, 0.0)
    past = VertexInfluence(bone_idx=9, xtra_idx=0, bone_weight_raw=0, xtra_weight_raw=0)
    assert _influence_pair(past, 5) == (0, 0.0, 0, 0.0)
    weighted = VertexInfluence(bone_idx=2, xtra_idx=0, bone_weight_raw=100, xtra_weight_raw=0)
    assert _influence_pair(weighted, 5) == (2, 1.0, 0, 0.0)


class Resolver:
    def __init__(self, **hierarchies):
        self.hierarchies = hierarchies
        self.asked = []

    def find_hierarchy(self, name):
        self.asked.append(name)
        found = self.hierarchies.get(name)
        return SimpleNamespace(hierarchy=found) if found is not None else None

    def find_texture(self, name):
        return None


def skinned(hlod_name):
    header = SimpleNamespace(hierarchy_name=SimpleNamespace(value=hlod_name))
    return SimpleNamespace(hierarchy=None, hlod=SimpleNamespace(header=header))


def test_the_named_skeleton_comes_before_the_hlods_hierarchy():
    resolver = Resolver(MUMount_SKL="mount", HLODName="hlod")
    assert _resolve_hierarchy(skinned("HLODName"), resolver, "MUMount_SKL") == "mount"


def test_an_unknown_skeleton_falls_back_to_the_hlods_hierarchy():
    resolver = Resolver(HLODName="hlod")
    assert _resolve_hierarchy(skinned("HLODName"), resolver, "Missing_SKL") == "hlod"
    assert resolver.asked == ["Missing_SKL", "HLODName"]


def test_a_hierarchy_inside_the_file_wins():
    model = SimpleNamespace(hierarchy="own", hlod=None)
    assert _resolve_hierarchy(model, Resolver(MUMount_SKL="mount"), "MUMount_SKL") == "own"
