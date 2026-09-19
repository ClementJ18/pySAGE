"""Undoable edits to the lists and property dictionaries a map is made of.

A map's data is plain mutable dataclasses, lists and dicts, so these commands hold references to
the containers themselves. Undo puts back the very same objects, which keeps every other command
that refers to them valid.
"""

from __future__ import annotations

from collections.abc import MutableSequence
from typing import TYPE_CHECKING, Any

from sage_map.context import Property
from sage_worldbuilder.changes import Change
from sage_worldbuilder.commands.base import Command

if TYPE_CHECKING:
    from sage_worldbuilder.document import MapDocument

__all__ = ["InsertItem", "MoveItem", "RemoveItem", "ReplaceItem", "SetProperty"]


class _ChangeCommand(Command):
    def __init__(self, change: Change, label: str) -> None:
        self.change = change
        self.label = label

    def changes(self) -> tuple[Change, ...]:
        return (self.change,)


class InsertItem(_ChangeCommand):
    def __init__(
        self,
        items: MutableSequence[Any],
        index: int,
        item: Any,
        change: Change,
        label: str = "Insert",
    ) -> None:
        super().__init__(change, label)
        self.items = items
        self.index = index
        self.item = item

    def do(self, document: MapDocument) -> None:
        self.items.insert(self.index, self.item)

    def undo(self, document: MapDocument) -> None:
        del self.items[self.index]


class RemoveItem(_ChangeCommand):
    def __init__(
        self, items: MutableSequence[Any], index: int, change: Change, label: str = "Delete"
    ) -> None:
        super().__init__(change, label)
        self.items = items
        self.index = index
        self.item: Any = None

    def do(self, document: MapDocument) -> None:
        self.item = self.items.pop(self.index)

    def undo(self, document: MapDocument) -> None:
        self.items.insert(self.index, self.item)


class MoveItem(_ChangeCommand):
    """Move an item between (or within) lists. `target_index` is its index once it is in the
    target list, counted after it has left the source."""

    def __init__(
        self,
        source: MutableSequence[Any],
        source_index: int,
        target: MutableSequence[Any],
        target_index: int,
        change: Change,
        label: str = "Move",
    ) -> None:
        super().__init__(change, label)
        self.source = source
        self.source_index = source_index
        self.target = target
        self.target_index = target_index

    def do(self, document: MapDocument) -> None:
        self.target.insert(self.target_index, self.source.pop(self.source_index))

    def undo(self, document: MapDocument) -> None:
        self.source.insert(self.source_index, self.target.pop(self.target_index))


class ReplaceItem(_ChangeCommand):
    def __init__(
        self,
        items: MutableSequence[Any],
        index: int,
        item: Any,
        change: Change,
        label: str = "Edit",
    ) -> None:
        super().__init__(change, label)
        self.items = items
        self.index = index
        self.item = item
        self.previous: Any = None

    def do(self, document: MapDocument) -> None:
        self.previous = self.items[self.index]
        self.items[self.index] = self.item

    def undo(self, document: MapDocument) -> None:
        self.items[self.index] = self.previous


class SetProperty(_ChangeCommand):
    """Set, or with `value=None` remove, one entry of a property dictionary. Undo restores the
    whole dictionary, key order included, since the order is what a save writes."""

    def __init__(
        self,
        properties: dict[str, Property],
        name: str,
        value: Property | None,
        change: Change,
        label: str | None = None,
    ) -> None:
        super().__init__(change, label or f"Set {name}")
        self.properties = properties
        self.name = name
        self.value = value
        self._before: list[tuple[str, Property]] = []

    def do(self, document: MapDocument) -> None:
        self._before = list(self.properties.items())
        if self.value is None:
            self.properties.pop(self.name, None)
        else:
            self.properties[self.name] = self.value

    def undo(self, document: MapDocument) -> None:
        self.properties.clear()
        self.properties.update(self._before)

    def merge(self, following: Command) -> bool:
        if not (
            isinstance(following, SetProperty)
            and following.properties is self.properties
            and following.name == self.name
        ):
            return False
        self.value = following.value
        return True
