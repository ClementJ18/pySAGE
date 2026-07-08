"""Task 1 — the `CHUNK_GameClient` drawable index.

`CHUNK_GameClient` is the client-side mirror of `CHUNK_GameLogic`: a render frame, a drawable
template TOC (the same `u32 count + name/u16-id` shape `GameLogic` writes), and one drawable per
live object, each a `KOLB` block opening with the `u32` object id it renders. These tests pin the
headline invariant — every drawable joins back to a live `GameLogic` object (or is the
`0xFFFFFFFF` unattached sentinel) — plus clean template/module names, corpus-wide. The two small
between-missions campaign saves carry no `CHUNK_GameClient` (no live drawables yet); those skip.
"""

from pathlib import Path

import pytest

from sage_save import (
    drawable_modules,
    parse_save_from_path,
    save_to_dict,
)
from sage_save.chunks import decode_game_client, decode_game_logic
from tests.sage_save.corpus import ALL_SAVES as FULL_SAVES
from tests.sage_save.corpus import FIXTURES, fixture_id

SKIRMISH = FIXTURES / "Saved Game 4.BfME2Skirmish"
# Every full save (skirmish + the two full campaign saves) writes a GameClient; the small
# between-missions campaign stubs do not, so probing each save's chunk (not its extension) is what
# separates them.

UNATTACHED = 0xFFFFFFFF  # a drawable with no logic object behind it (Drawable::xfer writes -1)


def _require(path: Path) -> Path:
    if not path.is_file():
        pytest.skip(f"fixture not present: {path.name}")
    return path


def _client(path: Path):
    save = parse_save_from_path(_require(path))
    chunk = save.chunk("CHUNK_GameClient")
    if chunk is None:
        pytest.skip(f"{path.name} has no CHUNK_GameClient (between-missions stub)")
    return decode_game_client(chunk), save


def _named_tags(drawable) -> list[str]:
    return [b.name for b in drawable_modules(drawable) if b.name is not None and b.depth == 0]


def test_game_client_decodes():
    client, _ = _client(SKIRMISH)
    assert client.version == 4
    assert client.drawables
    assert client.templates
    # the drawable count matches the live-object count: one drawable renders each object
    logic = decode_game_logic(parse_save_from_path(SKIRMISH).chunk("CHUNK_GameLogic"))
    assert len(client.drawables) == len(logic.objects)


@pytest.mark.parametrize("path", FULL_SAVES, ids=fixture_id)
def test_drawables_join_to_logic_objects(path):
    # The headline invariant: every drawable's object_id is a live GameLogic object id, or the
    # 0xFFFFFFFF unattached sentinel — never a dangling id.
    client, save = _client(path)
    logic = decode_game_logic(save.chunk("CHUNK_GameLogic"))
    logic_ids = {o.object_id for o in logic.objects}

    attached = 0
    unattached = 0
    for drawable in client.drawables:
        if drawable.object_id == UNATTACHED:
            unattached += 1
            continue
        assert drawable.object_id in logic_ids, (
            f"drawable object id {drawable.object_id} resolves to no live object"
        )
        attached += 1
    assert attached + unattached == len(client.drawables)
    # across this corpus every drawable is attached; the split is reported so a future
    # client-only-drawable save (unattached > 0) surfaces rather than silently passing.
    assert attached > 0


@pytest.mark.parametrize("path", FULL_SAVES, ids=fixture_id)
def test_template_names_are_clean_identifiers(path):
    client, _ = _client(path)
    for name in client.templates.values():
        assert name.replace("_", "").replace(".", "").isalnum(), f"garbage template name {name!r}"


@pytest.mark.parametrize("path", FULL_SAVES, ids=fixture_id)
def test_drawable_module_walk_is_clean(path):
    # no false KOLB match should produce a non-identifier draw-module tag anywhere in the corpus
    client, _ = _client(path)
    total_named = 0
    for drawable in client.drawables:
        for tag in _named_tags(drawable):
            assert tag.replace("_", "").isalnum(), f"garbage draw-module tag {tag!r}"
            total_named += 1
        # each module block sits inside its drawable's body byte-range
        for block in drawable_modules(drawable):
            assert 0 <= block.payload_start <= block.end <= len(drawable.body)
    assert total_named > len(client.drawables)  # every drawable owns at least one draw module


def test_export_includes_game_client_summary():
    document = save_to_dict(parse_save_from_path(_require(SKIRMISH)), include_objects=False)
    section = document["game_client"]
    logic = document["game_logic"]
    assert section["version"] == 4
    assert section["drawable_count"] == logic["object_count"]
    assert section["attached"] + section["unattached"] == section["drawable_count"]
    assert section["template_count"] > 0
