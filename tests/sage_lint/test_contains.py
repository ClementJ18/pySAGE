"""Tests for the `unreachable-contain` rule: which earlier contain the multi-contain patch can
reach, and silence on an engine without it."""

import pytest

from sage_ini.engine import Engine, LimitDelta
from sage_ini.model.game import Game
from sage_ini.parser.blockparser import parse
from sage_ini.parser.diagnostics import Severity
from sage_lint.rules.base import run_rules
from sage_lint.rules.contains import UnreachableContainRule
from sage_patch import MultiContainPatch

_PATCHED = Engine(limits=(LimitDelta("contain.secondary_slaughter", 1),))


def _load(text: str) -> Game:
    game = Game()
    game.load_document(parse(text, file="t.ini").document)
    return game


def _object(*modules: str, name: str = "Lair", parent: str | None = None) -> str:
    header = f"ChildObject {name} {parent}" if parent else f"Object {name}"
    body = "".join(f"    Behavior = {module}\n    End\n" for module in modules)
    return f"{header}\n{body}End\n"


def _run(text: str, engine: Engine = _PATCHED) -> list:
    with engine.activate():
        return list(run_rules(_load(text), [UnreachableContainRule]))


class TestUnreachableContainRule:
    def test_the_patch_publishes_the_limit_the_rule_reads(self) -> None:
        assert MultiContainPatch().ini_surface() == Engine(
            limits=(LimitDelta("contain.secondary_slaughter", 1, "multi-contain"),)
        )

    def test_slaughter_before_tunnel_is_what_the_patch_wants(self) -> None:
        text = _object(
            "SlaughterHordeContain ModuleTag_SlaughterMe", "TunnelContain ModuleTag_Contain"
        )
        assert not _run(text)

    @pytest.mark.parametrize("slaughter", ["SlaughterHordeContain", "CitadelSlaughterHordeContain"])
    def test_every_slaughter_class_can_come_first(self, slaughter: str) -> None:
        text = _object(
            f"{slaughter} ModuleTag_A",
            "SlaughterHordeContain ModuleTag_B",
            "TransportContain ModuleTag_Keep",
        )
        assert not _run(text)

    def test_tunnel_before_slaughter_is_flagged_with_the_reorder(self) -> None:
        text = _object(
            "TunnelContain ModuleTag_Contain", "SlaughterHordeContain ModuleTag_SlaughterMe"
        )
        diags = _run(text)
        assert len(diags) == 1
        assert diags[0].code == "unreachable-contain"
        assert diags[0].severity is Severity.WARNING
        assert diags[0].extra == {
            "object": "Lair",
            "module": "TunnelContain",
            "tag": "ModuleTag_Contain",
            "stored_module": "SlaughterHordeContain",
            "stored_tag": "ModuleTag_SlaughterMe",
        }
        assert "declaring TunnelContain ModuleTag_Contain after" in diags[0].message

    def test_two_contains_that_keep_passengers(self) -> None:
        text = _object("TransportContain ModuleTag_Hobbit", "TunnelContain ModuleTag_Contain")
        diags = _run(text)
        assert [d.extra["tag"] for d in diags] == ["ModuleTag_Hobbit"]
        assert "only one contain that keeps its passengers" in diags[0].message

    def test_one_contain_is_silent(self) -> None:
        assert not _run(_object("TunnelContain ModuleTag_Contain"))

    def test_a_stock_engine_is_silent(self) -> None:
        text = _object(
            "TunnelContain ModuleTag_Contain", "SlaughterHordeContain ModuleTag_SlaughterMe"
        )
        assert not _run(text, Engine())

    def test_inheritance_and_remove_module_are_resolved(self) -> None:
        """Edain's lair today: the child drops the parent's slaughter before adding a tunnel, so
        one contain is left. Keeping the slaughter is the patched shape, and silent too."""
        parent = _object("SlaughterHordeContain ModuleTag_SlaughterMe", name="Parent")
        removed = (
            "ChildObject Lair Parent\n    RemoveModule ModuleTag_SlaughterMe\n"
            "    Behavior = TunnelContain ModuleTag_Contain\n    End\nEnd\n"
        )
        kept = _object("TunnelContain ModuleTag_Contain", parent="Parent")
        assert not _run(parent + removed)
        assert not _run(parent + kept)

    def test_an_inherited_order_is_judged_on_the_child(self) -> None:
        """A tunnel parent with a slaughter child puts the tunnel first on the child only."""
        parent = _object("TunnelContain ModuleTag_Contain", name="Parent")
        child = _object("SlaughterHordeContain ModuleTag_SlaughterMe", parent="Parent")
        diags = _run(parent + child)
        assert [(d.extra["object"], d.extra["tag"]) for d in diags] == [
            ("Lair", "ModuleTag_Contain")
        ]
