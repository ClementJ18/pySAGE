"""The undo stack: do / undo / redo, merging, groups, the clean point and the depth limit."""

from dataclasses import dataclass

import pytest

from sage_map.map import Map
from sage_worldbuilder import (
    Change,
    ChangeKind,
    Command,
    CompositeCommand,
    MapDocument,
    SetAttribute,
)


@dataclass
class Target:
    value: int = 0


SETTINGS = Change(ChangeKind.SETTINGS)


def make_document(limit: int = 500) -> MapDocument:
    return MapDocument(Map(), undo_limit=limit)


def set_value(target: Target, value: int) -> SetAttribute:
    return SetAttribute(target, "value", value, SETTINGS)


class Append(Command):
    """Appends to a shared log; never merges, repeats as itself."""

    def __init__(self, log: list[str], item: str) -> None:
        self.log = log
        self.item = item
        self.label = f"Append {item}"

    def do(self, document: MapDocument) -> None:
        self.log.append(self.item)

    def undo(self, document: MapDocument) -> None:
        self.log.remove(self.item)

    def repeat(self) -> Command | None:
        return Append(self.log, self.item)


def test_do_undo_redo():
    document = make_document()
    target = Target()
    document.execute(Append([], "a"))
    document.execute(set_value(target, 5))

    assert target.value == 5
    assert document.stack.undo()
    assert target.value == 0
    assert document.stack.redo()
    assert target.value == 5
    assert document.stack.undo_label == "Set value"


def test_undo_and_redo_on_empty_history_do_nothing():
    stack = make_document().stack
    assert not stack.undo()
    assert not stack.redo()
    assert stack.undo_label is None


def test_new_command_discards_redo_history():
    document = make_document()
    log: list[str] = []
    document.execute(Append(log, "a"))
    document.stack.undo()
    document.execute(Append(log, "b"))

    assert not document.stack.can_redo
    assert log == ["b"]


def test_consecutive_sets_merge_into_one_entry():
    document = make_document()
    target = Target()
    for value in (1, 2, 3):
        document.execute(set_value(target, value))

    document.stack.undo()
    assert target.value == 0
    assert not document.stack.can_undo


def test_no_merge_into_the_saved_entry():
    document = make_document()
    target = Target()
    document.execute(set_value(target, 1))
    document.stack.set_clean()
    document.execute(set_value(target, 2))

    assert document.dirty
    document.stack.undo()
    assert target.value == 1
    assert not document.dirty


def test_clean_point_tracks_undo_and_redo():
    document = make_document()
    log: list[str] = []
    document.execute(Append(log, "a"))
    document.stack.set_clean()
    assert not document.dirty

    document.stack.undo()
    assert document.dirty
    document.stack.redo()
    assert not document.dirty


def test_clean_point_lost_when_its_redo_branch_is_discarded():
    document = make_document()
    log: list[str] = []
    document.execute(Append(log, "a"))
    document.stack.set_clean()
    document.stack.undo()
    document.execute(Append(log, "b"))
    document.stack.undo()

    assert document.dirty  # back at the empty state, which was never saved


def test_limit_drops_oldest_entries():
    document = make_document(limit=2)
    log: list[str] = []
    for item in "abc":
        document.execute(Append(log, item))

    assert document.stack.undo() and document.stack.undo()
    assert not document.stack.undo()
    assert log == ["a"]


def test_limit_trimming_past_the_clean_point_makes_it_unreachable():
    document = make_document(limit=1)
    log: list[str] = []
    document.stack.set_clean()
    document.execute(Append(log, "a"))
    document.execute(Append(log, "b"))
    document.stack.undo()

    assert document.dirty


def test_group_undoes_as_one_entry():
    document = make_document()
    log: list[str] = []
    with document.stack.group("Both"):
        document.execute(Append(log, "a"))
        document.execute(Append(log, "b"))

    assert document.stack.undo_label == "Both"
    document.stack.undo()
    assert log == []
    assert not document.stack.can_undo
    document.stack.redo()
    assert log == ["a", "b"]


def test_failed_group_rolls_back_and_records_nothing():
    document = make_document()
    log: list[str] = []
    with pytest.raises(ValueError), document.stack.group("Broken"):
        document.execute(Append(log, "a"))
        raise ValueError("boom")

    assert log == []
    assert not document.stack.can_undo


def test_empty_group_records_nothing():
    document = make_document()
    with document.stack.group("Nothing"):
        pass
    assert not document.stack.can_undo


def test_undo_inside_open_group_is_refused():
    document = make_document()
    with pytest.raises(RuntimeError), document.stack.group("Open"):
        document.stack.undo()


def test_repeat_pushes_a_fresh_copy():
    document = make_document()
    log: list[str] = []
    document.execute(Append(log, "a"))

    assert document.stack.repeat()
    assert log == ["a", "a"]
    target = Target()
    document.execute(set_value(target, 1))
    assert not document.stack.repeat()  # SetAttribute does not repeat


def test_composite_repeat_needs_every_child_to_repeat():
    log: list[str] = []
    assert CompositeCommand("x", [Append(log, "a")]).repeat() is not None
    assert CompositeCommand("x", [Append(log, "a"), set_value(Target(), 1)]).repeat() is None


def test_listeners_hear_changes_and_state():
    document = make_document()
    heard: list[Change] = []
    states: list[bool] = []
    document.subscribe(heard.append)
    unsubscribe = document.stack.subscribe(lambda: states.append(document.stack.can_undo))

    document.execute(set_value(Target(), 1))
    document.stack.undo()
    unsubscribe()
    document.stack.redo()

    assert heard == [SETTINGS, SETTINGS, SETTINGS]
    assert states == [True, False]
    assert document.revision == 3


def test_limit_must_be_positive():
    with pytest.raises(ValueError):
        make_document(limit=0)
