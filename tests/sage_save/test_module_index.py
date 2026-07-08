"""Step 4 — the per-object behavior-module index.

Each `CHUNK_GameLogic` object body is a self-delimiting `ModuleTag_* + KOLB` tree, so
`object_modules` walks it with the container's own block framing — no per-module `xfer` decode,
no dependence on a forked serializer. These tests pin that the walk yields clean module-tag names
for every object across the corpus (the guard against false `KOLB` matches) and that the module
index lines up with the objects it belongs to."""

from collections import Counter
from pathlib import Path

import pytest

from sage_save import iter_objects, object_modules, parse_save_from_path, save_to_dict
from tests.sage_save.corpus import ALL_SKIRMISH, FIXTURES, fixture_id

SKIRMISH = FIXTURES / "Saved Game 4.BfME2Skirmish"


def _require(path: Path) -> Path:
    if not path.is_file():
        pytest.skip(f"fixture not present: {path.name}")
    return path


def _named_tags(obj) -> list[str]:
    return [b.name for b in object_modules(obj) if b.name is not None and b.depth == 0]


def test_object_has_its_module_tags():
    objects = iter_objects(parse_save_from_path(_require(SKIRMISH)))
    tags = _named_tags(objects[0])
    # every object carries the standard helper modules
    assert "ModuleTag_SMCHelper" in tags
    assert all(t.startswith("ModuleTag_") for t in tags)
    # each module block sits inside its object's body byte-range
    for block in object_modules(objects[0]):
        assert 0 <= block.payload_start <= block.end <= len(objects[0].body)


@pytest.mark.parametrize("path", ALL_SKIRMISH, ids=fixture_id)
def test_module_walk_is_clean_for_every_object(path):
    # no false KOLB match should produce a non-identifier module tag anywhere in the corpus
    objects = iter_objects(parse_save_from_path(_require(path)))
    total_named = 0
    for obj in objects:
        for tag in _named_tags(obj):
            assert tag.replace("_", "").isalnum(), f"garbage module tag {tag!r}"
            total_named += 1
    # a populated save has many module blocks (each object owns a dozen-plus)
    assert total_named > 5 * len(objects)


def test_module_tag_frequency_matches_objects():
    objects = iter_objects(parse_save_from_path(_require(SKIRMISH)))
    counts = Counter(tag for o in objects for tag in _named_tags(o))
    # the universal helper modules appear exactly once per object
    assert counts["ModuleTag_SMCHelper"] == len(objects)
    assert counts["ModuleTag_RecoveryHelper"] == len(objects)


def test_export_includes_module_tag_summary():
    document = save_to_dict(parse_save_from_path(_require(SKIRMISH)), include_objects=False)
    module_tags = document["game_logic"]["module_tags"]
    assert module_tags["ModuleTag_SMCHelper"] == document["game_logic"]["object_count"]
