"""Engine ThingTemplate registration order (sage_ini.subsystems).

The replay object id of a template is its registration index + 1. The order follows
`SubsystemLegend.ini`, not an alphabetical walk: InitFiles before InitPaths, then the engine's
`INI::loadDirectory` two-pass file order - the files directly in the InitPath first, then every
subdirectory file (any depth) as one flat path-sorted list - with the `-cinematics` path pruned
and `#include`s expanded. These tests pin that machinery on a tiny synthetic game tree;
`test_thing_ids.py` validates it against a real BFME2 install.
"""

from pathlib import Path

import pytest

from sage_ini.subsystems import OBJECT_BLOCKS, parse_subsystem_legend, thing_template_order

LEGEND = """\
LoadSubsystem TheThingFactory
  Loader = INI
  InitFile = Data\\INI\\Default\\Object.ini
  InitPath = Data\\INI\\Object
  ExcludePath = Data\\INI\\Object\\Skip\\skipped.ini
  IncludePathCinematics = Data\\INI\\Object\\Cinematic\\
End

LoadSubsystem TheCrateSystem
  Loader = INI
  InitFile = Data\\INI\\Crate.ini
End
"""


def _write(root: Path, rel: str, *objects: str) -> None:
    path = root / "data" / "ini" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n\n".join(f"Object {name}\n  Side = test\nEnd" for name in objects)
    path.write_text(body + "\n", encoding="latin-1")


@pytest.fixture
def game(tmp_path: Path) -> Path:
    _write(tmp_path, "default/object.ini", "DefaultThingTemplate")
    # A top-level file (zeta) that sorts *after* a subdirectory (aaa_sub): the engine's pass 1
    # loads every top-level file before any subdirectory file, so Zeta registers before Inner.
    _write(tmp_path, "object/zeta.ini", "Zeta")
    _write(tmp_path, "object/aaa_sub/inner.ini", "Inner")
    # Below the top level, files and subdirectories interleave by full path (NOT files-first): in
    # aaa_sub/, the sub-subdir mmm/ sorts before the file zzz.ini, so SubInner precedes SubZeta.
    _write(tmp_path, "object/aaa_sub/zzz.ini", "SubZeta")
    _write(tmp_path, "object/aaa_sub/mmm/inner2.ini", "SubInner")
    _write(tmp_path, "object/cinematic/cine.ini", "CineOnly")
    _write(tmp_path, "object/skip/skipped.ini", "Skipped")  # pruned via ExcludePath
    # A redefinition of an existing name keeps its first position (no new id).
    _write(tmp_path, "object/dup.ini", "Zeta")
    # An object pulled in through #include registers at the include point.
    (tmp_path / "data/ini/object/withinc.ini").write_text(
        'Object Host\n  Side = test\nEnd\n#include "shared.inc"\n', encoding="latin-1"
    )
    (tmp_path / "data/ini/object/shared.inc").write_text(
        "Object FromInclude\n  Side = test\nEnd\n", encoding="latin-1"
    )
    _write(tmp_path, "crate.ini", "SalvageCrate")
    (tmp_path / "data/ini/default/subsystemlegend.ini").write_text(LEGEND, encoding="latin-1")
    return tmp_path


def test_object_blocks_are_the_id_consuming_types():
    assert OBJECT_BLOCKS == frozenset({"Object", "ChildObject", "ObjectReskin"})


def test_parse_subsystem_legend_orders_and_classifies():
    subs = parse_subsystem_legend(LEGEND)
    assert [s.name for s in subs] == ["TheThingFactory", "TheCrateSystem"]
    tf = subs[0]
    assert tf.loads == [("file", "Data\\INI\\Default\\Object.ini"), ("path", "Data\\INI\\Object")]
    assert tf.cinematics == ["data/ini/object/cinematic"]
    assert tf.excludes == ["data/ini/object/skip/skipped.ini"]


def test_default_template_is_id_one(game):
    order = thing_template_order(game)
    assert order[0] == "DefaultThingTemplate"  # index 0 → replay id 1


def test_top_level_files_registered_before_subdirectory_files(game):
    order = thing_template_order(game)
    # zeta.ini (top-level) sorts after aaa_sub/ alphabetically, yet its object registers first
    # because the engine loads every top-level file (pass 1) before any subdirectory file (pass 2).
    assert order.index("Zeta") < order.index("Inner")


def test_subdirectory_files_and_dirs_interleave_by_path(game):
    order = thing_template_order(game)
    # Below the top level there is no files-before-subdirs rule: aaa_sub/mmm/inner2.ini sorts
    # before aaa_sub/zzz.ini, so SubInner (in the sub-subdir) registers before SubZeta (a file).
    assert order.index("SubInner") < order.index("SubZeta")


def test_cinematic_path_excluded_by_default_included_on_request(game):
    assert "CineOnly" not in thing_template_order(game)
    assert "CineOnly" in thing_template_order(game, cinematics=True)


def test_exclude_path_is_pruned(game):
    assert "Skipped" not in thing_template_order(game)


def test_includes_are_expanded(game):
    assert "FromInclude" in thing_template_order(game)


def test_redefinition_keeps_first_position(game):
    order = thing_template_order(game)
    assert order.count("Zeta") == 1


def test_later_subsystem_objects_take_higher_ids(game):
    order = thing_template_order(game)
    # TheCrateSystem loads after TheThingFactory, so its object lands after every object one.
    assert order.index("SalvageCrate") > order.index("Inner")


def test_id_numbering_is_dense_and_one_based(game):
    order = thing_template_order(game)
    assert order[0] == "DefaultThingTemplate"
    # No duplicates: a dense 1..N id space.
    assert len(order) == len(set(order))
