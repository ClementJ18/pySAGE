"""Using translated-replay documents as a parse cache.

The document itself - one replay's parse with every id already resolved to code names, so it
can be consumed (or shared) without any game install - is `sage_replay.translated`'s
`TranslatedReplay`. Caching one is an explicit step the *caller* takes (nothing in sage_replay
writes a cache as a side effect): the caller decides where documents live and when to produce
them, and this module supplies the policy pieces that make a tree of them work as a cache -
the mirrored-path convention, the trust checks, and the outcome refresh on load.

`cache_path` maps a replay to its document in a *mirrored* cache tree: the same folder
structure under a separate cache root (`tools/rebuild_aggregates.py` mirrors
`downloads/replays/` into `downloads/cached/`), so the cache never pollutes the replay tree
itself and a whole corpus's documents can be browsed, shipped, or deleted as one folder.

A document is trusted (`cached_document`) when it reads back at all (`FORMAT_VERSION` gates
the schema - bump it after a stats-pipeline or mod-overlay hook change, which the other checks
can't see), when its recorded size and content hash still match the replay file (identity that
survives copying a corpus between machines, unlike an mtime), and when it was written under
the same `assume_pov_won` assumption the caller wants. Anything else reads as a miss: the
caller re-translates and rewrites, so a stale document self-heals.

Match outcomes are deliberately not baked into the document. The ladder sidecar beside a
replay (`sidecar.py`) is hand-edited - a winner filled in days after the replay was first
cached must still take effect on the next rebuild - so `load_replay_cache` re-derives the
outcome at *load* time from whatever sidecar sits beside the replay now, mapped by the
document's cached `(name, lobby team)` pairs exactly as a fresh parse would
(`sidecar_team_outcomes`). Only when the sidecar is missing or untrustworthy does a player's
outcome fall back to the document's frozen `heuristic_outcome` - the concession-heuristic
verdict from parse time, kept precisely because it can't be recomputed from an order stream
the document doesn't retain.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sage_replay.aggregate import PlayerGame
from sage_replay.replay import ReplayFile
from sage_replay.sidecar import sidecar_team_outcomes
from sage_replay.translated import TranslatedReplay

__all__ = [
    "CachedReplay",
    "cache_path",
    "cached_document",
    "load_replay_cache",
    "write_replay_cache",
]


def cache_path(replay_path: Path, replay_root: Path, cache_root: Path) -> Path:
    """Where `replay_path`'s document lives in the cache tree at `cache_root` that mirrors the
    replay tree at `replay_root`: the same relative folders, `<replay name>.json`. Raises
    `ValueError` when the replay does not live under `replay_root` - a mirror has no place for
    an outside path."""
    relative = replay_path.relative_to(replay_root)
    return cache_root / relative.parent / (replay_path.name + ".json")


@dataclass(slots=True)
class CachedReplay:
    """One cache hit: the raw `player_games()`-shaped games (pre-scrub - a faction or an
    opponent may still read `"?"`, so `aggregate._absorb` can filter and scrub identically to
    a fresh parse) and the document's label -> Side lookups, for a caller
    (`tools/rebuild_aggregates.py`'s `_side_annotator`) that would otherwise need the loaded
    game to answer them."""

    games: list[PlayerGame]
    sides: dict[str, str]


def write_replay_cache(
    replay_path: Path,
    replay: ReplayFile,
    games: list[PlayerGame],
    *,
    cache_file: Path,
    heuristic_outcomes: dict[str, str],
    side_of: Callable[[str], str | None],
    assume_pov_won: bool,
) -> Path:
    """Write the translated document for a fresh parse of `replay_path`
    (`TranslatedReplay.from_parse`; see its docstring for the arguments) to `cache_file` -
    typically `cache_path(...)` - creating its folders if needed, and return where it landed."""
    document = TranslatedReplay.from_parse(
        replay_path,
        replay,
        games,
        heuristic_outcomes=heuristic_outcomes,
        side_of=side_of,
        assume_pov_won=assume_pov_won,
    )
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    document.write(cache_file)
    return cache_file


def cached_document(
    replay_path: Path, cache_file: Path, *, assume_pov_won: bool
) -> TranslatedReplay | None:
    """The trusted document at `cache_file` for `replay_path`, or None when there is none or
    it isn't trusted: a missing/unreadable/unsupported document (`TranslatedReplay.read`), a
    replay file that no longer matches the document's size and content hash, or a document
    written under a different `assume_pov_won` assumption than this call's. The caller's
    "does this replay still need translating?" check, shared by `load_replay_cache`."""
    if not cache_file.is_file():
        return None
    try:
        document = TranslatedReplay.read(cache_file)
    except (OSError, ValueError):
        return None
    if document.assume_pov_won != assume_pov_won:
        return None
    if not document.matches_replay(replay_path):
        return None
    return document


def load_replay_cache(
    replay_path: Path, cache_file: Path, *, assume_pov_won: bool
) -> CachedReplay | None:
    """The cached parse for `replay_path`, or None when `cache_file` holds no trusted document
    for it (`cached_document`). On a hit, each player's outcome is re-resolved from the sidecar
    sitting beside `replay_path` *now*, falling back to the document's frozen
    `heuristic_outcome` (see the module docstring)."""
    document = cached_document(replay_path, cache_file, assume_pov_won=assume_pov_won)
    if document is None:
        return None
    outcomes = sidecar_team_outcomes(replay_path, document.player_teams)
    return CachedReplay(games=document.to_player_games(outcomes), sides=dict(document.sides))
