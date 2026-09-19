"""The scripts a player inherits from its library maps.

Every player carries a list of library maps (`LibraryMapLists`, stored as
`Libraries\\name\\name.map`). WorldBuilder reads each of them, takes the scripts of the library
map's **second** side - the one a library writes its scripts under - and shows them in that
player's script tree as read-only items marked `(imported)`. A library map lists library maps of
its own, so the lists chain, and a name two libraries both define is kept by the first one
reached: the losers stay in the tree, drawn as `(overridden)`.

The order is WorldBuilder's: the player's own items, then every imported group, then every
imported script, each library before the libraries it chains to. Groups come before scripts
because WorldBuilder keeps a list of each and draws the groups first; the player's own items are
left in the order the map stores them.

A name the map itself defines beats every library's, which is what `override` builds: the map's
own copy of an imported item takes its name off the library and can be edited.

This is `SidesList::linkLibraryMaps` (`0x00A88720` in `worldbuilder.exe`) and the name slots of
`ScriptSetBase`, written up in `sage_patch/docs/worldbuilder-library-maps.md`.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from sage_map.assets.player_scripts import ScriptGroup
from sage_map.map import Map
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands import Command, CompositeCommand
from sage_worldbuilder.commands.edits import InsertItem
from sage_worldbuilder.players import library_paths
from sage_worldbuilder.scripting import ScriptItem

__all__ = [
    "LIBRARY_SIDE",
    "ImportedItem",
    "ImportedScripts",
    "LibraryMaps",
    "MapLoader",
    "Override",
    "imported_scripts",
    "library_name",
    "override",
]

SCRIPTS = Change(ChangeKind.SCRIPTS)

#: The side a library map keeps its scripts on. WorldBuilder reads this one and no other,
#: warning when the library has more players than the two it expects.
LIBRARY_SIDE = 1

#: Reads a map at a game path (`Libraries\\name\\name.map`), or returns `None` when the game has
#: no such map or it cannot be read.
MapLoader = Callable[[str], Map | None]


@dataclass(frozen=True)
class ImportedItem:
    """One script or group a player inherits: the item itself - owned by the library map and
    never edited - which library it came from, the groups it sits in there, and the library that
    took its name when another one defines it first."""

    item: ScriptItem
    library: str
    overridden_by: str | None = None
    parents: tuple[ScriptGroup, ...] = ()

    @property
    def overridden(self) -> bool:
        return self.overridden_by is not None


@dataclass(frozen=True)
class ImportedScripts:
    """What a player inherits: the top-level items in the order WorldBuilder draws them, every
    item (those and the ones inside them) by identity, and the libraries that could not be read."""

    items: tuple[ImportedItem, ...] = ()
    by_item: dict[int, ImportedItem] = field(default_factory=dict)
    missing: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.items or self.missing)

    def of(self, item: ScriptItem) -> ImportedItem | None:
        """What `item` is, if it is an imported one: `None` for the map's own items."""
        return self.by_item.get(id(item))


@dataclass(frozen=True)
class Override:
    """What giving the map its own copy of an imported item comes to: the copy, the names of the
    library groups its path had to recreate, and the one command that adds them all - or, when the
    map already holds that name, why it cannot be done."""

    copy: ScriptItem | None = None
    mirrored: tuple[str, ...] = ()
    command: Command | None = None
    blocked: str | None = None


@dataclass
class LibraryMaps:
    """A loader that reads each library map once. WorldBuilder caches them the same way
    (`LibraryMapCache`), and holding on to the maps is what keeps an imported item's identity -
    and with it the tree's selection and open folders - stable between two reads."""

    load: MapLoader
    _maps: dict[str, Map | None] = field(default_factory=dict, repr=False)

    def __call__(self, path: str) -> Map | None:
        key = _key(path)
        if key not in self._maps:
            self._maps[key] = self.load(path)
        return self._maps[key]

    def clear(self) -> None:
        self._maps.clear()


def library_name(path: str) -> str:
    """The library's name as the Player List shows it: `Libraries\\KI Kern\\KI Kern.map` is
    `KI Kern`. A path that is not a stored library path is shown as it stands."""
    parts = path.replace("/", "\\").split("\\")
    return parts[1] if len(parts) == 3 else path


def imported_scripts(map: Map, index: int, load: MapLoader) -> ImportedScripts:
    """What player `index` inherits from its library maps. `load` reads a library map by its
    stored path; one that cannot be read is reported in `missing` rather than raising, and a
    chain that leads back to a library already read stops there."""
    found: list[tuple[str, ScriptItem]] = []
    missing: list[str] = []
    read: set[str] = set()
    for path in library_paths(map, index) or []:
        _collect(path, load, read, found, missing)

    # A name belongs to the first item that claims it. The player's own items claim theirs first,
    # so an imported item never takes a name off the map itself.
    holder: dict[tuple[bool, str], str] = {}
    for own, _parents in _walk(_items(map, index)):
        holder.setdefault(_name(own), "")
    groups: list[ImportedItem] = []
    scripts: list[ImportedItem] = []
    by_item: dict[int, ImportedItem] = {}
    for library, item in found:
        for each, parents in _walk([item]):
            held = holder.setdefault(_name(each), library)
            imported = ImportedItem(each, library, held if held != library else None, parents)
            by_item[id(each)] = imported
        top = by_item[id(item)]
        (groups if isinstance(item, ScriptGroup) else scripts).append(top)
    return ImportedScripts(tuple(groups + scripts), by_item, tuple(missing))


def override(map: Map, index: int, imported: ImportedItem) -> Override:
    """Give player `index` its own copy of an imported item, at the path it has in its library
    map, so it can be edited: the copy keeps the name, which is what takes that name off the
    library (`ScriptSetBase::allocateEntry`, `0x00AB4630`).

    The groups of the path the player does not have yet are recreated to hold the copy, empty and
    with the library group's own flags; those names come off their library too, which is what
    `mirrored` names. A name the player already owns is not overridable - WorldBuilder renames the
    copy in that case rather than replacing what the map itself defines - so nothing is built and
    `blocked` says which item stands in the way."""
    target = _list_of(map, index)
    if target is None:
        return Override(blocked="the map has no script list for this player")
    taken = {_name(item): item for item, _parents in _walk(_items(map, index))}
    clash = taken.get(_name(imported.item))
    if clash is not None:
        kind = "group" if isinstance(clash, ScriptGroup) else "script"
        return Override(blocked=f"the map already has a {kind} called {clash.name}")

    commands: list[Command] = []
    mirrored: list[str] = []
    for group in imported.parents:
        held = taken.get(_name(group))
        if isinstance(held, ScriptGroup):
            target = held.items
            continue
        mirror = copy.copy(group)
        mirror.items = []
        mirrored.append(group.name)
        commands.append(InsertItem(target, len(target), mirror, SCRIPTS))
        target = mirror.items

    duplicate = copy.deepcopy(imported.item)
    commands.append(InsertItem(target, len(target), duplicate, SCRIPTS))
    label = f"Override {imported.item.name}"
    return Override(duplicate, tuple(mirrored), CompositeCommand(label, commands))


def _key(path: str) -> str:
    return path.replace("/", "\\").casefold()


def _list_of(map: Map, index: int) -> list[ScriptItem] | None:
    """The script list player `index` owns, the one an override is added to."""
    lists = map.player_scripts_list.script_lists if map.player_scripts_list is not None else []
    return lists[index].items if 0 <= index < len(lists) else None


def _items(map: Map, index: int) -> list[ScriptItem]:
    """The script list of player `index`, empty when the map has no such list."""
    lists = map.player_scripts_list.script_lists if map.player_scripts_list is not None else []
    return list(lists[index].items) if 0 <= index < len(lists) else []


def _walk(
    items: list[ScriptItem], parents: tuple[ScriptGroup, ...] = ()
) -> Iterator[tuple[ScriptItem, tuple[ScriptGroup, ...]]]:
    """Every item under `items` with the groups it sits in, each item before its own."""
    for item in items:
        yield item, parents
        if isinstance(item, ScriptGroup):
            yield from _walk(item.items, (*parents, item))


def _name(item: ScriptItem) -> tuple[bool, str]:
    """What two items have to share to override each other: their kind and their name, which
    WorldBuilder's name slots compare without case."""
    return isinstance(item, ScriptGroup), item.name.casefold()


def _collect(
    path: str,
    load: MapLoader,
    read: set[str],
    found: list[tuple[str, ScriptItem]],
    missing: list[str],
) -> None:
    """Add the items of the library at `path`, then the ones of the libraries it chains to."""
    key = _key(path)
    if key in read:
        return
    read.add(key)
    library = load(path)
    if library is None:
        missing.append(path)
        return
    name = library_name(path)
    for item in _items(library, LIBRARY_SIDE):
        found.append((name, item))
    for nested in library_paths(library, LIBRARY_SIDE) or []:
        _collect(nested, load, read, found, missing)
