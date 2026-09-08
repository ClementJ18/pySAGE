"""Tests for reading the engine's map cache and spelling a map on a command line.

Data-free: a `mapcache.ini` is text and the `-file` argument is string arithmetic. Both have a
rule that is silent when broken - an entry the cache does not carry is a map no command line can
start, and an argument that names the map's real folder makes the lookup miss - so both are worth
pinning without a game.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_test.maps import (
    MapEntry,
    decode_cache_key,
    file_argument,
    load_map_cache,
    parse_map_cache,
    read_map_cache,
)

#: Two entries in the form Edain's hand-maintained file uses: aligned `=`, `End` in mixed case,
#: comment lines between blocks.
CACHE = """
;Edain-mod Mapcache
; This INI file is NOT auto-generated - !do! modify :P

MapCache maps_5Cmap_20mp_20harlindon_5Cmap_20mp_20harlindon_2Emap
    fileSize      = 487138
    fileCRC       = 1690668198
    isOfficial    = yes
    isMultiplayer = yes
    isScenarioMP  = no
    numPlayers    = 4
    extentMin     = X:0.00 Y:0.00 Z:0.00
End

;
MapCache maps_5Cmap_20edain_20wor_20andrast_5Cmap_20edain_20wor_20andrast_2Emap
    fileSize      = 100
    isOfficial    = no
    isMultiplayer = no
    numPlayers    = 2
END
"""


class TestDecodeCacheKey:
    def test_the_escapes_are_hex_bytes(self):
        assert decode_cache_key("maps_5Ca_20b_2Emap") == "maps\\a b.map"

    def test_an_underscore_in_a_name_is_itself_escaped(self):
        """`_5F` and not a bare underscore, so unescaping cannot eat part of a name."""
        assert decode_cache_key("a_5Fb") == "a_b"

    def test_anything_unescaped_is_left_alone(self):
        assert decode_cache_key("shellmap1") == "shellmap1"


class TestFileArgument:
    def test_the_argument_drops_the_folder_the_engine_inserts(self):
        """The engine's path builder puts the map's own stem back as a directory, so the argument
        that resolves to `maps\\x\\x.map` is `maps\\x.map` - a path that exists nowhere."""
        assert file_argument("maps\\x\\x.map") == "maps\\x.map"

    def test_names_with_spaces_survive_intact(self):
        argument = file_argument("maps\\map mp harlindon\\map mp harlindon.map")
        assert argument == "maps\\map mp harlindon.map"

    def test_a_folder_that_is_not_the_stem_is_left_alone(self):
        """The builder only rewrites what it can; inventing a parent for anything else would be a
        guess, and a wrong guess is a silent cache miss."""
        assert file_argument("maps\\somewhere\\other.map") == "maps\\somewhere\\other.map"

    def test_a_bare_name_is_left_alone(self):
        assert file_argument("x.map") == "x.map"


class TestParseMapCache:
    def test_every_block_becomes_an_entry(self):
        assert len(parse_map_cache(CACHE)) == 2

    def test_the_key_decodes_to_the_path_the_engine_keys_by(self):
        first = parse_map_cache(CACHE)[0]
        assert first.path == "maps\\map mp harlindon\\map mp harlindon.map"

    def test_the_fields_that_gate_a_launch_are_read(self):
        harlindon, andrast = parse_map_cache(CACHE)
        assert (harlindon.is_multiplayer, harlindon.num_players) == (True, 4)
        assert (andrast.is_multiplayer, andrast.is_official) == (False, False)

    def test_end_is_matched_whatever_its_case(self):
        """The shipped files spell it `End` and the auto-generated ones `END`."""
        assert [entry.name for entry in parse_map_cache(CACHE)] == [
            "map mp harlindon",
            "map edain wor andrast",
        ]

    def test_unknown_fields_are_ignored_rather_than_fatal(self):
        """These files are hand-edited in some mods; refusing to enumerate maps over a field we
        do not know is worse than ignoring it."""
        text = "MapCache a_5Ca_2Emap\n  whoKnows = 3\n  isMultiplayer = yes\nEND\n"
        assert parse_map_cache(text)[0].is_multiplayer

    def test_a_block_with_no_fields_is_still_an_entry(self):
        entry = parse_map_cache("MapCache maps_5Cx_5Cx_2Emap\nEND\n")[0]
        assert (entry.path, entry.is_multiplayer, entry.num_players) == ("maps\\x\\x.map", False, 0)

    def test_an_unterminated_block_is_dropped(self):
        """A truncated file gives fewer maps to launch, never a half-read entry claiming to be
        multiplayer."""
        assert parse_map_cache("MapCache maps_5Cx_5Cx_2Emap\n  isMultiplayer = yes\n") == []

    def test_a_missing_end_costs_one_map_and_not_the_rest_of_the_file(self):
        """The blocks after it still parse. A hand-edited file loses the map somebody broke;
        losing every map below it would be a silent hole in the sweep."""
        text = "MapCache maps_5Ca_5Ca_2Emap\n" + CACHE
        assert [entry.name for entry in parse_map_cache(text)] == [
            "map mp harlindon",
            "map edain wor andrast",
        ]

    def test_comments_are_not_fields(self):
        text = "MapCache maps_5Cx_5Cx_2Emap\n; isMultiplayer = yes\nEND\n"
        assert not parse_map_cache(text)[0].is_multiplayer


class TestMapEntry:
    def test_the_name_is_the_folder_a_player_sees(self):
        entry = MapEntry(path="maps\\map mp harlindon\\map mp harlindon.map")
        assert entry.name == "map mp harlindon"

    def test_the_argument_is_not_the_path(self):
        entry = MapEntry(path="maps\\map mp harlindon\\map mp harlindon.map")
        assert entry.argument == "maps\\map mp harlindon.map"


class TestLoadMapCache:
    def test_an_uncompiled_mod_tree_wins_over_the_install(self, tmp_path: Path):
        """`-mod` sets `preferLocalFiles`, so the tree's cache is the one the engine reads - and
        therefore the one a run with `--mod` is actually testing."""
        tree = tmp_path / "_mod"
        (tree / "maps").mkdir(parents=True)
        (tree / "maps" / "mapcache.ini").write_text(CACHE, encoding="latin-1")
        assert len(load_map_cache(install=tmp_path / "install", mod=tree)) == 2

    def test_nothing_to_read_is_an_error_not_an_empty_list(self, tmp_path: Path):
        """An empty list would silently deselect every map and pass."""
        with pytest.raises(FileNotFoundError):
            load_map_cache(mod=tmp_path)


class TestReadMapCache:
    def test_a_file_that_is_not_utf8_still_reads(self, tmp_path: Path):
        """Names are hex-escaped, so only comments carry high bytes - and a suite must not fail
        to enumerate maps over a comment."""
        path = tmp_path / "mapcache.ini"
        path.write_bytes("; Grünquell\n".encode("windows-1252") + CACHE.encode("latin-1"))
        assert len(read_map_cache(path)) == 2
