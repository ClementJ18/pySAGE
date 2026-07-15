"""Using translated-replay documents as a parse cache.

The document itself - one replay's parse with every version-coupled id already resolved to code
names, so it can be consumed (or shared) against any paired game whose templates share those
names - is `sage_replay.translated`'s `TranslatedReplay`. Caching one is an explicit step the
*caller* takes (nothing in sage_replay writes a cache as a side effect): the caller decides
where documents live and when to produce them, and this module supplies the policy pieces that
make a tree of them work as a cache - the mirrored-path convention (`cache_path`), the trust
checks (`cached_document`), and the whole load-time pipeline that turns a document back into
player-games (`load_replay_cache`).

A whole corpus's documents live in a *mirrored* cache tree - the same folder structure under a
separate cache root (`tools/rebuild_aggregates.py` mirrors `downloads/replays/` into
`downloads/cached/`) - so the cache never pollutes the replay tree and can be browsed, shipped,
or deleted as one folder. A document that fails any trust check reads as a miss: the caller
re-translates and rewrites, so a stale document self-heals.

Producing a document needs only the recording build's `GameData` (the id-space knowledge);
everything analysis-shaped - KindOf bucketing, cancel netting, the faction/power overlay hooks,
the winner heuristic - runs at *load* time against the paired game the caller holds, so a
pipeline or overlay change never invalidates a document. Match outcomes are likewise not baked
in: the ladder sidecar beside a replay (`sidecar.py`) is hand-edited - a winner filled in days
after the replay was first cached must still take effect on the next rebuild - so a load
re-derives each outcome from whatever sidecar sits beside the replay now, falling back to the
concession heuristic (`assume_pov_won` layered over it) only when no trustworthy sidecar exists.
"""

from __future__ import annotations

from pathlib import Path

from sage_replay.aggregate import FactionRefiner, PlayerGame, player_games
from sage_replay.narrate import GameData
from sage_replay.replay import ReplayFile
from sage_replay.sidecar import sidecar_outcomes
from sage_replay.stats import PowerLabeler, PowerRecruits, UpgradeRecruits
from sage_replay.translated import TranslatedReplay

__all__ = [
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


def write_replay_cache(
    replay_path: Path,
    replay: ReplayFile,
    data: GameData,
    *,
    cache_file: Path,
) -> Path:
    """Translate a freshly parsed `replay` (read from `replay_path`) against the recording
    build's `data` and write the resulting document to `cache_file` - typically `cache_path(...)`
    - creating its folders if needed, and return where it landed. Translation is the only
    production step: ids resolve to code names now, and every analysis and outcome decision is
    deferred to `load_replay_cache`."""
    document = TranslatedReplay.from_replay(replay_path, replay, data)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    document.write(cache_file)
    return cache_file


def cached_document(replay_path: Path, cache_file: Path) -> TranslatedReplay | None:
    """The trusted document at `cache_file` for `replay_path`, or None when there is none or it
    isn't trusted: a missing/unreadable/unsupported document (`TranslatedReplay.read`), or a
    replay file that no longer matches the document's size and content hash. The caller's "does
    this replay still need translating?" check, shared by `load_replay_cache`."""
    if not cache_file.is_file():
        return None
    try:
        document = TranslatedReplay.read(cache_file)
    except (OSError, ValueError):
        return None
    if not document.matches_replay(replay_path):
        return None
    return document


def load_replay_cache(
    replay_path: Path,
    cache_file: Path,
    data: GameData,
    *,
    assume_pov_won: bool = False,
    refine_faction: FactionRefiner | None = None,
    relabel_power: PowerLabeler | None = None,
    power_recruits: PowerRecruits | None = None,
    upgrade_recruits: UpgradeRecruits | None = None,
    ignore_recruits: frozenset[str] = frozenset(),
) -> list[PlayerGame] | None:
    """The cached parse for `replay_path` as player-games, or None when `cache_file` holds no
    trusted document for it (`cached_document`). On a hit the document is rehydrated into a
    `ReplayFile` against `data` (the paired game whose templates share the recording's names) and
    fed to the same `player_games` pipeline a fresh parse takes: each player's outcome is
    re-resolved from the sidecar sitting beside `replay_path` *now* (`sidecar_outcomes`), falling
    back inside `player_games` to the concession heuristic (`assume_pov_won` layered over it)
    when no trustworthy sidecar exists. The overlay hooks (`refine_faction`, `relabel_power`,
    `power_recruits`, `upgrade_recruits`, `ignore_recruits`) thread through unchanged, so an
    overlay sharpens the corpus at load time without any re-translation."""
    document = cached_document(replay_path, cache_file)
    if document is None:
        return None
    replay = document.to_replay(data)
    outcomes = sidecar_outcomes(replay, replay_path)
    return player_games(
        replay,
        data,
        source=document.replay,
        assume_pov_won=assume_pov_won,
        outcomes=outcomes,
        refine_faction=refine_faction,
        relabel_power=relabel_power,
        power_recruits=power_recruits,
        upgrade_recruits=upgrade_recruits,
        ignore_recruits=ignore_recruits,
    )
