"""The cross-reference graph: a field resolving to another registered object is an edge.
`Xref` drives that resolution once over the whole game and records both directions, so a
consumer can ask what an object references (forward) or what references it (reverse). The
nodes are the registered objects; references anywhere inside an object's subtree are
attributed to it.
"""

import enum
from collections import defaultdict
from collections.abc import Iterator

from sage_ini.model.game import Game
from sage_ini.model.objects import REGISTRY, IniObject, resolve_annotation
from sage_ini.model.types import KeyedRecord, Reference
from sage_ini.walk import walk_objects

__all__ = ["Xref", "referenceable_keys"]

# Converted values that hold no reference and must not be descended into.
_SCALAR = (str, bytes, bool, int, float, enum.Enum)


def _collect_keys(converter, keys: set[str], seen: set[int]) -> None:
    """Add every Game table key `converter` (or anything nested in it) can reference. Mirrors
    the converter shapes `references.py::_iter_refs` walks: a `Reference` names its target table,
    a field typed directly as a definition class names that class's table, and the list/tuple/
    nullable wrappers and `KeyedRecord` keys are descended. A definition class is an endpoint —
    its own fields are visited when `REGISTRY` reaches that class, so descent stops there (which
    also breaks the forward-reference cycle a class field back to its own type would form)."""
    if converter is None or id(converter) in seen:
        return
    seen.add(id(converter))
    if isinstance(converter, Reference):
        keys.add(converter.key)
        return
    if isinstance(converter, type) and issubclass(converter, KeyedRecord):
        for annotation in converter._keyspec.values():
            _resolve_into(annotation, keys, seen)
        return
    if isinstance(converter, type) and issubclass(converter, IniObject):
        if converter.key:
            keys.add(converter.key)
        return
    for attr in ("element", "inner"):
        nested = getattr(converter, attr, None)
        if nested is not None:
            _resolve_into(nested, keys, seen)
    for annotation in getattr(converter, "element_types", None) or ():
        _resolve_into(annotation, keys, seen)


def _resolve_into(annotation, keys: set[str], seen: set[int]) -> None:
    """Resolve one field annotation to its converter and fold its reference keys in."""
    try:
        _collect_keys(resolve_annotation(annotation), keys, seen)
    except (KeyError, TypeError):
        pass  # a name with no registered class is not a reference target


def referenceable_keys() -> frozenset[str]:
    """Every Game table key some typed field can point at — a `Reference`'s target table, or the
    table of a field typed directly as a definition class. A definition whose *kind* never appears
    here is an engine entry point that nothing in the data names (a faction, the game data, a
    terrain): the engine loads it directly, so an unused-definition check cannot judge it and must
    skip it. A kind that does appear is a genuine reference target whose unreferenced members are
    worth flagging. Schema-derived, so the answer is the same for any loaded game."""
    keys: set[str] = set()
    for cls in REGISTRY.values():
        for annotation in getattr(cls, "_fieldspec", {}).values():
            _resolve_into(annotation, keys, set())
    return frozenset(keys)


def _registered(game: Game, obj: IniObject) -> bool:
    """Whether `obj` is the object registered under its (key, name) in the game."""
    return obj.key is not None and game.tables.get(obj.key, {}).get(obj.name) is obj


def _referenced_objects(value, game: Game, seen: set[int]) -> Iterator[IniObject]:
    """Every registered object reachable inside a converted field value (which may be an
    object, a container of them, or a converter object holding them as attributes). Descent
    stops at a registered object (an edge endpoint) and at scalars/enums."""
    if isinstance(value, _SCALAR) or value is None:
        return
    if id(value) in seen:
        return
    seen.add(id(value))
    if isinstance(value, IniObject):
        if _registered(game, value):
            yield value  # an edge endpoint; its own fields are its own node's edges
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from _referenced_objects(item, game, seen)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _referenced_objects(item, game, seen)
    elif hasattr(value, "__dict__"):
        # A converter object holds its references as instance attributes.
        for item in vars(value).values():
            yield from _referenced_objects(item, game, seen)


class Xref:
    """The forward/reverse reference graph of a loaded `Game`, built once."""

    def __init__(self, game: Game):
        self.game = game
        self._forward: dict[IniObject, set[IniObject]] = defaultdict(set)
        self._reverse: dict[IniObject, set[IniObject]] = defaultdict(set)
        self._build()

    @classmethod
    def for_game(cls, game: Game) -> "Xref":
        """The graph for `game`, built once and cached on it. Several rules ask the same game
        what references what; building the whole graph per rule would walk it repeatedly, so the
        first caller builds it and the rest reuse it. The cache lives for the game's lifetime —
        each lint run assembles a fresh game, so there is nothing stale to invalidate."""
        cached = game.__dict__.get("_xref")
        if cached is None:
            cached = cls(game)
            game.__dict__["_xref"] = cached
        return cached

    def _build(self) -> None:
        for table in self.game.tables.values():
            for root in table.values():
                for target in self._references_of(root):
                    self._forward[root].add(target)
                    self._reverse[target].add(root)

    def _references_of(self, root: IniObject) -> set[IniObject]:
        """The registered objects referenced anywhere in `root`'s subtree (not self)."""
        found: set[IniObject] = set()
        for node in walk_objects(root):
            fieldspec = type(node)._fieldspec
            for key in node.fields:
                if key not in fieldspec:
                    continue
                try:
                    value = getattr(node, key)
                except (ValueError, KeyError, TypeError, IndexError):
                    continue  # a bad value is the validate/lint pass's diagnostic
                found.update(_referenced_objects(value, self.game, set()))
            # Digit-keyed slots (`1 = Command_X`) are dynamic, so no typed field carries them;
            # fold their resolved targets in directly (a command set's buttons are real edges).
            for target in node.numbered_slot_targets():
                found.update(_referenced_objects(target, self.game, set()))
        found.discard(root)
        return found

    def references(self, obj: IniObject) -> frozenset[IniObject]:
        """The objects `obj` references (forward edges)."""
        return frozenset(self._forward.get(obj, ()))

    def referenced_by(self, obj: IniObject) -> frozenset[IniObject]:
        """The objects that reference `obj` (reverse edges)."""
        return frozenset(self._reverse.get(obj, ()))

    def is_referenced(self, obj: IniObject) -> bool:
        """Whether anything references `obj`."""
        return bool(self._reverse.get(obj))
