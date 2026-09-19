"""The scripts a player inherits from its library maps: what is imported, in which order, and
which duplicate name loses to which."""

from sage_map.assets.library_map_lists import LibraryMapLists
from sage_map.assets.library_map_lists import LibraryMaps as LibraryMapValues
from sage_map.assets.player_scripts import PlayerScriptsList, ScriptList
from sage_map.map import Map
from sage_worldbuilder.document import MapDocument
from sage_worldbuilder.libraries import (
    LibraryMaps,
    Override,
    imported_scripts,
    library_name,
    override,
)
from sage_worldbuilder.players import library_map_path
from sage_worldbuilder.scripting import new_group, new_script


def built(items_by_player: list[list], libraries_by_player: list[list[str]]) -> Map:
    """A map with one script list and one library list per player."""
    map = Map()
    map.player_scripts_list = PlayerScriptsList(
        version=1,
        script_lists=[
            ScriptList(version=1, items=items, start_pos=0, end_pos=0) for items in items_by_player
        ],
        start_pos=0,
        end_pos=0,
    )
    map.library_map_lists = LibraryMapLists(
        version=1,
        lists=[
            LibraryMapValues(version=1, values=list(values), start_pos=0, end_pos=0)
            for values in libraries_by_player
        ],
        start_pos=0,
        end_pos=0,
    )
    return map


def library(items: list, chains: list[str] | None = None) -> Map:
    """A library map: nothing on its first side, its scripts on its second."""
    return built([[], items], [[], [library_map_path(name) for name in chains or []]])


def loader(maps: dict[str, Map]):
    named = {library_map_path(name).casefold(): map for name, map in maps.items()}

    def load(path: str) -> Map | None:
        return named.get(path.casefold())

    return load


def test_library_name_is_the_folder():
    assert library_name("Libraries\\KI Kern\\KI Kern.map") == "KI Kern"
    assert library_name("elsewhere.map") == "elsewhere.map"


def test_imports_the_second_side_of_the_library():
    map = built([[], [new_group("Own")]], [[], [library_map_path("Core")]])
    core = library([new_group("Build"), new_script("Timer")])
    # The first side is what a library map leaves empty; only the second one is read.
    core.player_scripts_list.script_lists[0].items.append(new_group("Ignored"))

    inherited = imported_scripts(map, 1, loader({"Core": core}))

    assert [item.item.name for item in inherited.items] == ["Build", "Timer"]
    assert [item.library for item in inherited.items] == ["Core", "Core"]
    assert not any(item.overridden for item in inherited.items)
    assert inherited.missing == ()


def test_groups_come_before_scripts():
    map = built([[]], [[library_map_path("Core")]])
    core = library([new_script("First"), new_group("Second")])

    inherited = imported_scripts(map, 0, loader({"Core": core}))

    assert [item.item.name for item in inherited.items] == ["Second", "First"]


def test_chained_libraries_follow_the_one_that_names_them():
    map = built([[]], [[library_map_path("Core"), library_map_path("Spells")]])
    core = library([new_group("Build")])
    spells = library([new_group("Spellbook")], chains=["Timings"])
    timings = library([new_group("Upgrades")])

    inherited = imported_scripts(
        map, 0, loader({"Core": core, "Spells": spells, "Timings": timings})
    )

    assert [item.item.name for item in inherited.items] == ["Build", "Spellbook", "Upgrades"]
    assert [item.library for item in inherited.items] == ["Core", "Spells", "Timings"]


def test_the_first_library_reached_keeps_the_name():
    map = built([[]], [[library_map_path("Spells"), library_map_path("Timings")]])
    spells = library([new_group("Spellbook")])
    timings = library([new_group("Spellbook")])

    inherited = imported_scripts(map, 0, loader({"Spells": spells, "Timings": timings}))

    first, second = inherited.items
    assert (first.library, first.overridden) == ("Spells", False)
    assert (second.library, second.overridden_by) == ("Timings", "Spells")


def test_the_map_keeps_its_own_names():
    map = built([[new_group("Spellbook")]], [[library_map_path("Spells")]])
    spells = library([new_group("Spellbook")])

    inherited = imported_scripts(map, 0, loader({"Spells": spells}))

    # An empty holder is the map itself, which never shows as imported or overridden.
    assert inherited.items[0].overridden_by == ""
    assert inherited.items[0].overridden


def test_a_group_and_a_script_of_the_same_name_do_not_clash():
    map = built([[]], [[library_map_path("Core"), library_map_path("Spells")]])
    core = library([new_group("Spellbook")])
    spells = library([new_script("Spellbook")])

    inherited = imported_scripts(map, 0, loader({"Core": core, "Spells": spells}))

    assert not any(item.overridden for item in inherited.items)


def test_items_inside_an_imported_group_are_imported_too():
    map = built([[]], [[library_map_path("Core")]])
    group = new_group("Build")
    group.items.append(new_script("Farm"))
    core = library([group])

    inherited = imported_scripts(map, 0, loader({"Core": core}))

    assert inherited.of(group) is inherited.items[0]
    inside = inherited.of(group.items[0])
    assert inside is not None and inside.library == "Core"


def test_a_library_the_game_does_not_have_is_reported():
    map = built([[]], [[library_map_path("Gone"), library_map_path("Core")]])
    core = library([new_group("Build")])

    inherited = imported_scripts(map, 0, loader({"Core": core}))

    assert inherited.missing == (library_map_path("Gone"),)
    assert [item.item.name for item in inherited.items] == ["Build"]


def test_a_chain_that_leads_back_stops():
    map = built([[]], [[library_map_path("Core")]])
    core = library([new_group("Build")], chains=["Core"])

    inherited = imported_scripts(map, 0, loader({"Core": core}))

    assert [item.item.name for item in inherited.items] == ["Build"]


def test_a_player_without_libraries_inherits_nothing():
    map = built([[new_group("Own")]], [[]])

    inherited = imported_scripts(map, 0, loader({}))

    assert not inherited


def test_each_library_map_is_read_once():
    reads: list[str] = []
    core = library([new_group("Build")])

    def load(path: str) -> Map | None:
        reads.append(path)
        return core

    maps = LibraryMaps(load)
    path = library_map_path("Core")
    assert maps(path) is core
    assert maps(path.upper()) is core
    assert reads == [path]

    maps.clear()
    assert maps(path) is core
    assert reads == [path, path]


def overriding(map: Map, index: int, name: str, load) -> tuple[Override, MapDocument]:
    """Override the imported item called `name`, and hand back the document it was done on."""
    inherited = imported_scripts(map, index, load)
    imported = next(item for item in inherited.by_item.values() if item.item.name == name)
    document = MapDocument(map)
    result = override(map, index, imported)
    if result.command is not None:
        document.execute(result.command)
    return result, document


def test_override_copies_the_script_the_map_can_edit():
    map = built([[]], [[library_map_path("Core")]])
    script = new_script("Timer")
    script.comment = "from the library"
    core = library([script])
    load = loader({"Core": core})

    result, document = overriding(map, 0, "Timer", load)

    items = map.player_scripts_list.script_lists[0].items
    assert [item.name for item in items] == ["Timer"]
    assert items[0] is result.copy
    assert items[0] is not script and items[0].comment == "from the library"
    # The map holds the name now, so the library's script is the one drawn as overridden.
    inherited = imported_scripts(map, 0, load)
    assert inherited.items[0].overridden_by == ""
    assert document.stack.can_undo


def test_override_rebuilds_the_path_it_needs():
    map = built([[]], [[library_map_path("Core")]])
    inner = new_group("basewahl")
    inner.is_subroutine = True
    inner.items.append(new_script("Erster Bau"))
    outer = new_group("Bau")
    outer.items.append(inner)
    load = loader({"Core": library([outer])})

    result, _document = overriding(map, 0, "Erster Bau", load)

    assert result.mirrored == ("Bau", "basewahl")
    items = map.player_scripts_list.script_lists[0].items
    assert [item.name for item in items] == ["Bau"]
    rebuilt = items[0].items[0]
    assert rebuilt.name == "basewahl" and rebuilt.is_subroutine
    assert [item.name for item in rebuilt.items] == ["Erster Bau"]
    # The mirrored groups hold the copy alone; the library keeps its own.
    assert len(inner.items) == 1 and inner.items[0] is not rebuilt.items[0]


def test_override_uses_the_groups_the_map_already_has():
    own = new_group("Bau")
    map = built([[own]], [[library_map_path("Core")]])
    group = new_group("Bau")
    group.items.append(new_script("Erster Bau"))
    load = loader({"Core": library([group])})

    result, _document = overriding(map, 0, "Erster Bau", load)

    assert result.mirrored == ()
    assert [item.name for item in own.items] == ["Erster Bau"]


def test_override_of_a_group_takes_what_is_inside_it():
    map = built([[]], [[library_map_path("Core")]])
    group = new_group("Spellbook")
    group.items.append(new_script("Spell__1"))
    load = loader({"Core": library([group])})

    result, _document = overriding(map, 0, "Spellbook", load)

    copied = map.player_scripts_list.script_lists[0].items[0]
    assert copied is result.copy and copied.name == "Spellbook"
    assert [item.name for item in copied.items] == ["Spell__1"]


def test_a_name_the_map_owns_cannot_be_overridden():
    map = built([[new_script("Timer")]], [[library_map_path("Core")]])
    load = loader({"Core": library([new_script("Timer")])})

    result, _document = overriding(map, 0, "Timer", load)

    assert result.command is None and result.copy is None
    assert result.blocked == "the map already has a script called Timer"
    assert len(map.player_scripts_list.script_lists[0].items) == 1
