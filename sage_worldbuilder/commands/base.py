"""The command and undo-stack machinery every edit is built on.

A `Command` mutates the document in `do` and restores it in `undo`. The stack runs it, notifies
the document's listeners with the command's `changes()`, and records it. `merge` lets a run of
small edits (one brush stroke, typing into a field) collapse into one undo entry; `repeat` backs
Edit > Repeat. `UndoStack.group` bundles several commands into one entry, the way WorldBuilder's
`MultipleUndoable` does.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING

from sage_worldbuilder.changes import Change, ChangeKind

if TYPE_CHECKING:
    from sage_worldbuilder.document import MapDocument

__all__ = ["Command", "CompositeCommand", "SetAttribute", "UndoStack"]


class Command(ABC):
    """One undoable edit."""

    label: str = "Edit"

    @abstractmethod
    def do(self, document: MapDocument) -> None: ...

    @abstractmethod
    def undo(self, document: MapDocument) -> None: ...

    def redo(self, document: MapDocument) -> None:
        self.do(document)

    def changes(self) -> tuple[Change, ...]:
        """What this command touches; the stack reports it after do, undo and redo."""
        return (Change(ChangeKind.WHOLE),)

    def merge(self, following: Command) -> bool:
        """Absorb `following`, which has already been done, into this entry.

        Return True when merged: undoing this command must then undo both."""
        return False

    def repeat(self) -> Command | None:
        """A fresh command that applies the same edit again, or `None` if it cannot repeat."""
        return None


class CompositeCommand(Command):
    """Several commands that undo and redo as one entry."""

    def __init__(self, label: str, commands: Sequence[Command] = ()) -> None:
        self.label = label
        self.commands: list[Command] = list(commands)

    def do(self, document: MapDocument) -> None:
        for command in self.commands:
            command.do(document)

    def undo(self, document: MapDocument) -> None:
        for command in reversed(self.commands):
            command.undo(document)

    def redo(self, document: MapDocument) -> None:
        for command in self.commands:
            command.redo(document)

    def changes(self) -> tuple[Change, ...]:
        return tuple(dict.fromkeys(change for c in self.commands for change in c.changes()))

    def repeat(self) -> Command | None:
        repeats = [command.repeat() for command in self.commands]
        if not repeats or any(command is None for command in repeats):
            return None
        return CompositeCommand(self.label, [command for command in repeats if command])


_UNSET = object()


class SetAttribute(Command):
    """Set one attribute of a map object. Consecutive sets of the same attribute merge."""

    def __init__(
        self,
        target: object,
        name: str,
        value: object,
        change: Change,
        label: str | None = None,
    ) -> None:
        self.target = target
        self.name = name
        self.value = value
        self.change = change
        self.label = label or f"Set {name}"
        self._old: object = _UNSET

    def do(self, document: MapDocument) -> None:
        self._old = getattr(self.target, self.name)
        setattr(self.target, self.name, self.value)

    def undo(self, document: MapDocument) -> None:
        setattr(self.target, self.name, self._old)

    def changes(self) -> tuple[Change, ...]:
        return (self.change,)

    def merge(self, following: Command) -> bool:
        if not (
            isinstance(following, SetAttribute)
            and following.target is self.target
            and following.name == self.name
        ):
            return False
        self.value = following.value
        return True


class UndoStack:
    """The document's history: done commands, undone commands, and the saved (clean) point."""

    DEFAULT_LIMIT = 500

    def __init__(self, document: MapDocument, limit: int = DEFAULT_LIMIT) -> None:
        if limit < 1:
            raise ValueError("the undo limit must be at least 1")
        self.limit = limit
        self._document = document
        self._done: list[Command] = []
        self._undone: list[Command] = []
        # Length of `_done` at the saved state; None once that state can no longer be reached.
        self._clean: int | None = 0
        self._groups: list[CompositeCommand] = []
        self._listeners: list[Callable[[], None]] = []

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call `listener` whenever undo/redo availability or the clean state changes."""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    @property
    def can_undo(self) -> bool:
        return bool(self._done)

    @property
    def can_redo(self) -> bool:
        return bool(self._undone)

    @property
    def undo_label(self) -> str | None:
        return self._done[-1].label if self._done else None

    @property
    def redo_label(self) -> str | None:
        return self._undone[-1].label if self._undone else None

    @property
    def is_clean(self) -> bool:
        return self._clean == len(self._done)

    def push(self, command: Command) -> None:
        """Do `command` and record it (inside an open group, add it to the group)."""
        command.do(self._document)
        self._document.notify(*command.changes())
        if self._groups:
            self._groups[-1].commands.append(command)
            return
        self._record(command)

    def undo(self) -> bool:
        self._require_no_group("undo")
        if not self._done:
            return False
        command = self._done.pop()
        command.undo(self._document)
        self._document.notify(*command.changes())
        self._undone.append(command)
        self._changed()
        return True

    def redo(self) -> bool:
        self._require_no_group("redo")
        if not self._undone:
            return False
        command = self._undone.pop()
        command.redo(self._document)
        self._document.notify(*command.changes())
        self._done.append(command)
        self._changed()
        return True

    def repeat(self) -> bool:
        """Apply the last command again, as a new entry. False if there is nothing to repeat."""
        if not self._done:
            return False
        again = self._done[-1].repeat()
        if again is None:
            return False
        self.push(again)
        return True

    @contextmanager
    def group(self, label: str) -> Iterator[CompositeCommand]:
        """Record every command pushed inside the block as one entry.

        If the block raises, the commands it already did are undone and nothing is recorded."""
        composite = CompositeCommand(label)
        self._groups.append(composite)
        try:
            yield composite
        except BaseException:
            self._groups.pop()
            if composite.commands:
                composite.undo(self._document)
                self._document.notify(*composite.changes())
            raise
        self._groups.pop()
        if not composite.commands:
            return
        if self._groups:
            self._groups[-1].commands.append(composite)
        else:
            self._record(composite)

    def set_clean(self) -> None:
        """Mark the current state as saved."""
        self._clean = len(self._done)
        self._changed()

    def clear(self) -> None:
        self._require_no_group("clear")
        self._done.clear()
        self._undone.clear()
        self._clean = 0
        self._changed()

    def _record(self, command: Command) -> None:
        if self._clean is not None and self._clean > len(self._done):
            self._clean = None  # the saved state was in the redo history being discarded
        self._undone.clear()
        # Merging into the saved entry would change the saved state without marking it dirty.
        can_merge = bool(self._done) and self._clean != len(self._done)
        if not (can_merge and self._done[-1].merge(command)):
            self._done.append(command)
            self._trim()
        self._changed()

    def _trim(self) -> None:
        excess = len(self._done) - self.limit
        if excess <= 0:
            return
        del self._done[:excess]
        if self._clean is not None:
            self._clean = self._clean - excess if self._clean >= excess else None

    def _require_no_group(self, action: str) -> None:
        if self._groups:
            raise RuntimeError(f"cannot {action} while a command group is open")

    def _changed(self) -> None:
        for listener in list(self._listeners):
            listener()
