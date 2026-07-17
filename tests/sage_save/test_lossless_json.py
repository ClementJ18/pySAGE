"""The lossless-JSON acceptance gate: `save_to_json_full(save)` round-tripped through
`json.loads`/`json_to_save_full` must reproduce the original file bytes exactly, for every
fixture in the corpus - including the WotR saves the other corpus-wide tests exclude, since
this format makes no BFME2-only assumptions."""

import json

import pytest

from sage_save import (
    CHUNK_CODECS,
    LOSSLESS_FORMAT,
    json_to_save_full,
    parse_save,
    save_to_dict_full,
    save_to_json_full,
)
from tests.sage_save.corpus import ALL_SAVES, WOTR_PARSEABLE, fixture_id

CORPUS = sorted([*ALL_SAVES, *WOTR_PARSEABLE])


def _require(path):
    if not path.is_file():
        pytest.skip(f"fixture save not present: {path.name}")
    return path


@pytest.mark.parametrize("save_path", CORPUS, ids=[fixture_id(p) for p in CORPUS])
def test_lossless_round_trip_is_byte_exact(save_path):
    raw = _require(save_path).read_bytes()
    save = parse_save(raw)
    text = save_to_json_full(save)  # would raise if stray bytes leak into the dict
    data = json.loads(text)
    assert json_to_save_full(data) == raw


@pytest.mark.parametrize("save_path", CORPUS, ids=[fixture_id(p) for p in CORPUS])
def test_lossless_schema(save_path):
    raw = _require(save_path).read_bytes()
    save = parse_save(raw)
    data = save_to_dict_full(save)
    assert data["format"] == LOSSLESS_FORMAT
    assert [e["name"] for e in data["chunks"]] == [c.name for c in save.chunks]
    for entry in data["chunks"]:
        assert ("decoded" in entry) != ("raw" in entry)
        if entry["name"] in CHUNK_CODECS:
            assert "decoded" in entry
        else:
            assert "raw" in entry


def test_json_to_save_full_rejects_wrong_format():
    with pytest.raises(ValueError):
        json_to_save_full({"format": "something.else"})
