"""Corpus acceptance gate: parses and re-writes every real `.w3d` fixture in
`tests/sage_w3d/fixtures/w3d/**` (BFME2 and RotWK's W3D.big archives, unpacked - not committed),
byte-exact, so it belongs in the opt-in `--full` tier.

Two properties are checked per file:
- `write_w3d(parse_w3d(data)) == data` unconditionally (the self-check degrade rule guarantees
  this even for chunks this package cannot fully model).
- No chunk of a type this package *claims* to model shows up as an `UnknownChunk` - that would
  mean the typed model failed its own self-check against a real file (a transcription gap), not
  that the chunk was deliberately left raw. `_DEGRADATION_ALLOWLIST` is the escape hatch while
  bringing the corpus green; the goal is for it to stay empty.
"""

from pathlib import Path

import pytest

from sage_w3d.chunks import (
    CHUNK_NAMES,
    W3D_CHUNK_AGGREGATE,
    W3D_CHUNK_COLLECTION,
    W3D_CHUNK_DEFORM,
    W3D_CHUNK_EMITTER,
    W3D_CHUNK_HMODEL,
    W3D_CHUNK_LIGHT,
    W3D_CHUNK_LIGHTSCAPE,
    W3D_CHUNK_LODMODEL,
    W3D_CHUNK_MORPH_ANIMATION,
    W3D_CHUNK_NULL_OBJECT,
    W3D_CHUNK_POINTS,
    W3D_CHUNK_PS2_SHADERS,
    W3D_CHUNK_SOUNDROBJ,
    UnknownChunk,
)
from sage_w3d.w3d import parse_w3d, write_w3d

pytestmark = pytest.mark.full

# Kept as named raw chunks by design (no field model in v1 - see sage_w3d/README.md); an
# UnknownChunk with one of these ids is expected, not a degrade.
_RAW_BY_DESIGN = frozenset(
    {
        W3D_CHUNK_MORPH_ANIMATION,
        W3D_CHUNK_HMODEL,
        W3D_CHUNK_LODMODEL,
        W3D_CHUNK_COLLECTION,
        W3D_CHUNK_POINTS,
        W3D_CHUNK_LIGHT,
        W3D_CHUNK_EMITTER,
        W3D_CHUNK_AGGREGATE,
        W3D_CHUNK_NULL_OBJECT,
        W3D_CHUNK_LIGHTSCAPE,
        W3D_CHUNK_SOUNDROBJ,
        W3D_CHUNK_DEFORM,
        W3D_CHUNK_PS2_SHADERS,
    }
)

# Every chunk id this package has a name for, minus the ones kept raw by design: what's left is
# what it *claims* to model, at any nesting depth.
_MODELED_CHUNK_TYPES = frozenset(CHUNK_NAMES) - _RAW_BY_DESIGN

# fixture filename -> count of tolerated degradations of a modeled chunk type, each entry
# justified by a comment above it. Empty is the goal - see the module docstring.
#
# All seven entries below were traced byte-by-byte (chunk headers, not just leaf payloads) and
# every one diverges mid-structure: the first sub-chunk(s) decode to plausible values (a sane
# bone name and identity transform, small early animation keyframes, ...), then the bytes abruptly
# become denormalized-float noise or an outsized declared sub-chunk size with no sane chunk id -
# not a shape our field layout gets wrong, since the earlier sub-chunks of the very same
# container parse and self-check cleanly. This is data corruption already present in the shipped
# archive, not a parser gap; the round trip still holds byte-exact via the raw fallback (verified
# for the whole 14,614-file corpus - see the gate report). The two file families involved -
# cuwyrm_cld_sk{l,n} (an unused "cold wyrm" creature: skeleton + mesh, both broken) and
# lwbanh{fllbst,nazgul,wtchkng}/guhbtshfb_cin{b,c} (the Witch King's Fell Beast mount set and a
# leader's cinematic-only animation) - read as cut or cinematic-exclusive content that was never
# exercised by a real playthrough, matching the ten genuinely zero-byte fixtures elsewhere in the
# corpus (see w3d.py's empty-file handling) as further evidence the game's own asset pipeline
# tolerates broken entries for content it never loads.
_DEGRADATION_ALLOWLIST: dict[str, int] = {
    "cuwyrm_cld_skl.w3d": 1,  # HIERARCHY: pivot #2's transform is noise past its (sane) name
    "cuwyrm_cld_skn.w3d": 3,  # MESH + the HLOD referencing it, same broken creature
    "guhbtshfb_cinb.w3d": 1,  # COMPRESSED_ANIMATION: cinematic-only animation, noise mid-channel
    "guhbtshfb_cinc.w3d": 1,  # same as guhbtshfb_cinb.w3d
    "lwbanhfllbst.w3d": 1,  # COMPRESSED_ANIMATION: shared Fell Beast mount rig, noise mid-channel
    "lwbanhnazgul.w3d": 1,  # same broken rig as lwbanhfllbst.w3d
    "lwbanhwtchkng.w3d": 1,  # same broken rig as lwbanhfllbst.w3d
}

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "w3d"


def _fixture_paths() -> list[Path]:
    if not _FIXTURES_DIR.is_dir():
        return []
    return sorted(_FIXTURES_DIR.rglob("*.w3d"))


def _params() -> list:
    paths = _fixture_paths()
    if not paths:
        return [pytest.param(None, marks=pytest.mark.skip(reason="no w3d fixtures present"))]
    return paths


def _fixture_id(path: Path | None) -> str:
    if path is None:
        return "no-fixtures"
    return path.relative_to(_FIXTURES_DIR).as_posix()


def _collect_degradations(chunks: list, out: list[int]) -> None:
    for chunk in chunks:
        if isinstance(chunk, UnknownChunk):
            if chunk.chunk_type in _MODELED_CHUNK_TYPES:
                out.append(chunk.chunk_type)
            continue
        children = getattr(chunk, "chunks", None)
        if children is not None:
            _collect_degradations(children, out)


@pytest.mark.parametrize("w3d_path", _params(), ids=_fixture_id)
def test_parse_and_round_trip(w3d_path: Path):
    data = w3d_path.read_bytes()
    w3d = parse_w3d(data)
    assert write_w3d(w3d) == data


@pytest.mark.parametrize("w3d_path", _params(), ids=_fixture_id)
def test_no_degradation_for_modeled_chunk_types(w3d_path: Path):
    data = w3d_path.read_bytes()
    w3d = parse_w3d(data)

    degraded: list[int] = []
    _collect_degradations(w3d.chunks, degraded)

    allowed = _DEGRADATION_ALLOWLIST.get(w3d_path.name, 0)
    assert len(degraded) <= allowed, (
        f"{w3d_path.name}: {len(degraded)} modeled chunk(s) degraded to raw: "
        f"{[hex(t) for t in degraded]}"
    )
