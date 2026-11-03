"""The local replay corpus the `full`-tier gates read, shared by the sage_replay test modules.

`PYSAGE_REPLAYS` names it when set; otherwise it is `<repo>/Replays`, or failing that the downloaded
corpora under `<repo>/downloads/replays` (one folder per mod version). Neither is committed.
Discovery is recursive, and test ids are paths relative to the root, since downloaded replays are
named by match id and a name alone says nothing about which corpus it came from."""

import os
from pathlib import Path

__all__ = ["CORPUS", "REPLAYS_DIR", "replay_id"]

_REPO = Path(__file__).resolve().parents[2]


def _root() -> Path:
    given = os.environ.get("PYSAGE_REPLAYS")
    if given:
        return Path(given)
    return next(
        (path for path in (_REPO / "Replays", _REPO / "downloads" / "replays") if path.is_dir()),
        _REPO / "Replays",
    )


REPLAYS_DIR = _root()
CORPUS = sorted(REPLAYS_DIR.rglob("*.BfME2Replay")) if REPLAYS_DIR.is_dir() else []


def replay_id(path: Path) -> str:
    return path.relative_to(REPLAYS_DIR).as_posix()
