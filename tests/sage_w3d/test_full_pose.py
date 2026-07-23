"""Full-tier acceptance gate for `sage_w3d.render.pose` over the real `.w3d` corpus: for every
file carrying an animation chunk (uncompressed or compressed, any flavor), resolve the skeleton
the animation's header names and evaluate three frames (first, middle, last) - every world
matrix entry finite, one visibility flag per pivot, no exceptions. `test_render_pose.py`'s
hand-built cases prove the sampling/composition math is right in isolation; this proves
`PoseEvaluator` survives the real corpus's channel kinds, frame counts, and skeleton-name lookups
at scale - the acceptance gate for the whole animation-playback feature.

One `DirectoryResolver` is built per top-level fixture directory (`bfme2`, `rotwk` - each is
itself flat, so every file's own directory is one of exactly these two) and reused across every
file parametrized against it, mirroring `test_full_render.py`'s resolver cache."""

import math
from pathlib import Path

import pytest

from sage_w3d.hierarchy import Hierarchy
from sage_w3d.render.pose import AnimationSource, PoseEvaluator
from sage_w3d.render.scene import DirectoryResolver
from sage_w3d.w3d import W3DFile, parse_w3d_from_path

pytestmark = pytest.mark.full

_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "w3d"

_resolver_cache: dict[Path, DirectoryResolver] = {}


def _resolver_for(directory: Path) -> DirectoryResolver:
    if directory not in _resolver_cache:
        _resolver_cache[directory] = DirectoryResolver(directory)
    return _resolver_cache[directory]


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


def _resolve_skeleton(
    model: W3DFile, sources: list[AnimationSource], directory: Path
) -> Hierarchy | None:
    if model.hierarchy is not None:
        return model.hierarchy
    resolver = _resolver_for(directory)
    for source in sources:
        header = source.header
        name = header.hierarchy_name.value if header is not None else ""
        if not name:
            continue
        found = resolver.find_hierarchy(name)
        if found is not None and found.hierarchy is not None:
            return found.hierarchy
    return None


@pytest.mark.parametrize("w3d_path", _params(), ids=_fixture_id)
def test_pose_evaluates_across_the_corpus(w3d_path: Path | None):
    if w3d_path is None:
        return

    model = parse_w3d_from_path(w3d_path)
    sources: list[AnimationSource] = [*model.animations, *model.compressed_animations]
    if not sources:
        pytest.skip("file carries no animation chunk - outside this gate's scope")

    hierarchy = _resolve_skeleton(model, sources, w3d_path.parent)
    if hierarchy is None:
        pytest.skip("animation's hierarchy did not resolve - outside this gate's scope")

    num_pivots = len(hierarchy.pivots)
    for source in sources:
        evaluator = PoseEvaluator(hierarchy, source)
        last_frame = float(max(evaluator.num_frames - 1, 0))
        for frame in (0.0, last_frame / 2, last_frame):
            pose = evaluator.evaluate(frame)
            assert len(pose.world_matrices) == num_pivots, f"{w3d_path.name}: matrix count"
            assert len(pose.pivot_visible) == num_pivots, f"{w3d_path.name}: visibility count"
            for matrix in pose.world_matrices:
                for row in matrix:
                    assert all(math.isfinite(v) for v in row), (
                        f"{w3d_path.name}: non-finite matrix entry at frame {frame}"
                    )
