"""The upgrades a placed object starts the game with: WorldBuilder's Available Upgrades list.

WorldBuilder's Object Properties page carries a check list of upgrades (`IDD` 264, control 1100,
labelled *Available Upgrades:*) and stores the ticked ones in the object's `objectUpgradesList`
key, as one line of names each followed by a space, in the list's own order - the list box carries
`LBS_SORT`, so that order is alphabetical, ignoring case.

The list is not the whole game's upgrade table. WorldBuilder walks the selected object's template's
modules, collects the upgrades each one is triggered by, and resolves every name through
`TheUpgradeCenter`, dropping the ones no `Upgrade` block defines (`0x005575D0`); with several
objects selected it is the union over all of them. `sage_ini`'s `find_upgrades` reads those
triggers out of the typed model - every `TriggeredBy`, and `UpgradeRequired` with it, through a
`ChildObject`'s parent chain as the engine assembles the modules.

Reading the key back, WorldBuilder ticks each name it finds in the list and silently drops the
rest. Dropping would lose what the map stores the moment anything else is ticked, so a stored name
the template no longer offers is listed here as well, ticked, and is kept until it is unticked.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING

from sage_ini.model.state import find_upgrades
from sage_map.assets.object_list import Object
from sage_map.context import Property
from sage_utils.views.base import safe
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands import Command, CompositeCommand
from sage_worldbuilder.properties import OBJECT_SPECS, set_value

if TYPE_CHECKING:
    from sage_ini.model.game import Game

__all__ = [
    "UPGRADES_KEY",
    "UPGRADES_SPEC",
    "available_upgrades",
    "format_upgrades",
    "parse_upgrades",
    "set_upgrades",
    "stored_upgrades",
    "upgrade_choices",
]

UPGRADES_KEY = "objectUpgradesList"
UPGRADES_SPEC = next(spec for spec in OBJECT_SPECS if spec.name == UPGRADES_KEY)
_OBJECTS = Change(ChangeKind.OBJECTS)


def parse_upgrades(value: object) -> list[str]:
    """The names a stored `objectUpgradesList` holds, in the order it holds them."""
    return str(value or "").split()


def format_upgrades(names: Iterable[str]) -> str:
    """`names` as the key stores them: sorted ignoring case, each followed by a space, without
    the duplicates ticking two spellings of one name would give."""
    unique: dict[str, str] = {}
    for name in names:
        if name:
            unique.setdefault(name.casefold(), name)
    return "".join(f"{name} " for name in sorted(unique.values(), key=str.casefold))


def stored_upgrades(properties: Mapping[str, Property]) -> list[str]:
    stored = properties.get(UPGRADES_KEY)
    return parse_upgrades(stored["value"] if stored is not None else "")


def _template(game: Game, type_name: str) -> object | None:
    objects = getattr(game, "objects", None) or {}
    template = objects.get(type_name)
    if template is not None:
        return template
    folded = type_name.casefold()
    return next(
        (value for name, value in objects.items() if name.casefold() == folded),
        None,
    )


def available_upgrades(game: Game | None, type_names: Iterable[str]) -> list[str]:
    """Every upgrade the templates of `type_names` can be given, as the game defines it: the
    union over them, sorted ignoring case. Empty without game data."""
    if game is None:
        return []
    defined = {name.casefold(): name for name in getattr(game, "upgrades", None) or {}}
    found: dict[str, str] = {}
    for type_name in dict.fromkeys(type_names):
        template = _template(game, type_name)
        if template is None:
            continue
        # A template whose fields do not convert must not take the panel down with it.
        for name in safe(lambda template=template: find_upgrades(template), []) or []:
            defined_name = defined.get(name.casefold())
            if defined_name is not None:
                found.setdefault(defined_name.casefold(), defined_name)
    return sorted(found.values(), key=str.casefold)


def upgrade_choices(game: Game | None, objects: Sequence[Object]) -> list[str]:
    """The rows the check list shows for `objects`: the upgrades their templates offer, plus any
    name the first one already stores that they do not, so nothing stored is dropped unseen."""
    names = available_upgrades(game, [obj.type_name for obj in objects])
    known = {name.casefold() for name in names}
    stored = stored_upgrades(objects[0].properties) if objects else []
    extra = [name for name in stored if name.casefold() not in known]
    return sorted([*names, *extra], key=str.casefold)


def set_upgrades(objects: Sequence[Object], names: Iterable[str]) -> Command:
    """Store `names` as the upgrades of every one of `objects`, as one undo entry."""
    value = format_upgrades(names)
    return CompositeCommand(
        "Set Upgrades",
        [
            set_value(obj.properties, UPGRADES_SPEC, value, _OBJECTS, "Set Upgrades")
            for obj in objects
        ],
    )
