"""Unit tests for sage_ini.walk (AST and typed-layer traversal)."""

from sage_ini.model.game import Game
from sage_ini.model.objects import IniObject
from sage_ini.parser.ast import Attribute, Comment
from sage_ini.parser.blockparser import parse
from sage_ini.walk import walk_blocks, walk_nodes, walk_objects

NESTED = """\
; banner
Object MordorFighter
    BuildCost = 500
    Behavior = AutoHealBehavior Tag
        HealingAmount = 10
    End
    WeaponSet
        Weapon = PRIMARY MordorFighterSword
    End
End
"""


def _load(text: str) -> Game:
    game = Game()
    game.load_document(parse(text, file="t.ini").document)
    return game


class TestWalkNodes:
    def test_yields_every_node_depth_first(self):
        doc = parse(NESTED, file="t.ini").document
        kinds = [type(n).__name__ for n in walk_nodes(doc)]

        assert kinds[0] == "Comment"  # the banner
        assert kinds[1] == "Block"  # Object
        # the Object's first child is the BuildCost attribute
        assert "Attribute" in kinds
        assert kinds.count("Block") == 3  # Object, Behavior, WeaponSet

    def test_descends_into_nested_blocks(self):
        doc = parse(NESTED, file="t.ini").document
        keys = [n.key for n in walk_nodes(doc) if isinstance(n, Attribute)]

        assert keys == ["BuildCost", "HealingAmount", "Weapon"]

    def test_node_root_yields_itself_first(self):
        block = parse("Object A\n    K = 1\nEnd\n", file="t.ini").document.children[0]
        nodes = list(walk_nodes(block))

        assert nodes[0] is block
        assert isinstance(nodes[1], Attribute)

    def test_comment_only_node_has_no_children(self):
        comment = Comment(text="; x", span=parse("; x\n").document.children[0].span)
        assert list(walk_nodes(comment)) == [comment]


class TestWalkBlocks:
    def test_filters_by_header_name(self):
        doc = parse(NESTED, file="t.ini").document
        names = [b.name for b in walk_blocks(doc)]

        assert names == ["Object", "Behavior", "WeaponSet"]
        assert [b.name for b in walk_blocks(doc, name="Behavior")] == ["Behavior"]


class TestWalkObjects:
    def test_yields_top_level_and_nested(self):
        game = _load(NESTED)
        names = sorted(type(o).__name__ for o in walk_objects(game))

        # the Object plus its nested behavior and weapon-set objects
        assert "Object" in names
        assert len(list(walk_objects(game))) >= 3

    def test_filters_by_class(self):
        game = _load(NESTED)
        objects = list(walk_objects(game, cls=IniObject))

        assert objects  # everything is an IniObject
        assert all(isinstance(o, IniObject) for o in objects)

    def test_object_subtree_root(self):
        game = _load(NESTED)
        obj = game.objects["MordorFighter"]
        subtree = list(walk_objects(obj))

        assert subtree[0] is obj
        assert len(subtree) >= 3
