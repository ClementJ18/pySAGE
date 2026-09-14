"""What is selected in the map view.

Selecting is not an edit, as in WorldBuilder: it is not undoable and does not mark the map as
changed. The selection holds the map's own objects by identity, like the commands do, and forgets
any that leave the map.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator

__all__ = ["Selection"]


class Selection:
    def __init__(self) -> None:
        self._items: dict[int, object] = {}
        self._listeners: list[Callable[[], None]] = []
        # Lock Selection: clicks in the view no longer change what is selected.
        self.locked = False

    def __iter__(self) -> Iterator[object]:
        return iter(tuple(self._items.values()))

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        return bool(self._items)

    def __contains__(self, item: object) -> bool:
        return id(item) in self._items

    @property
    def items(self) -> tuple[object, ...]:
        """In the order they were selected; the first is the lead for Match Lead edits."""
        return tuple(self._items.values())

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def set(self, items: Iterable[object]) -> None:
        self._replace({id(item): item for item in items})

    def add(self, items: Iterable[object]) -> None:
        merged = dict(self._items)
        for item in items:
            merged.setdefault(id(item), item)
        self._replace(merged)

    def toggle(self, item: object) -> None:
        merged = dict(self._items)
        if id(item) in merged:
            del merged[id(item)]
        else:
            merged[id(item)] = item
        self._replace(merged)

    def clear(self) -> None:
        self._replace({})

    def keep_only(self, alive: Iterable[object]) -> None:
        """Forget what is no longer in `alive` (after a delete, or an undone add)."""
        present = {id(item) for item in alive}
        self._replace({key: item for key, item in self._items.items() if key in present})

    def _replace(self, items: dict[int, object]) -> None:
        if list(items) == list(self._items):
            return
        self._items = items
        for listener in list(self._listeners):
            listener()
