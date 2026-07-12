"""Resolve a `--game` command-line argument to an ini tree the loader can read.

Every CLI that loads a game from user input (`sage-replay narrate`, `sage-save check` /
`diagnose`) accepts the same three shapes and turns them into a `data/ini` root:

- an already-extracted `data/ini` dump (or a corpus dump that nests one),
- a mod's ini root passed directly (any folder that holds `.ini` files), or
- a live install folder holding `.big` archives - those are mounted into a scratch cache
  (default: a per-install folder under the system temp dir) and reused across runs.

Kept out of `cli.py` because mounting pulls in the dev-only `tools.mount_game` helper, imported
lazily so a plain `data/ini` run never depends on it.
"""

import tempfile
from collections.abc import Iterable
from pathlib import Path

__all__ = ["resolve_game_root", "resolve_game_roots"]


def resolve_game_root(game: str | Path, cache: Path | None = None) -> Path:
    """Return an ini tree to load. `game` may already be one (a `data/ini` dump, an extracted
    corpus, or a bare ini root), or a live install holding `.big` archives - those are mounted
    into `cache` (default: a per-install folder under the system temp dir), cached across runs."""
    game = Path(game)
    if (game / "data" / "ini").is_dir() or (game / "default" / "subsystemlegend.ini").is_file():
        return game
    if list(game.glob("*.big")):
        # tools/ is a dev-only, unpackaged helper; import it only when a live install must be
        # mounted, so a plain data/ini run never depends on it being importable.
        from tools.mount_game import mount_ini_tree  # noqa: PLC0415

        if cache is None:
            cache = Path(tempfile.gettempdir()) / "sage_mount" / game.resolve().name
        return mount_ini_tree(game, cache)
    if next(game.rglob("*.ini"), None) is not None:
        return game  # already an ini root (e.g. a mod's data/ini passed directly)
    raise SystemExit(f"{game} is neither an ini tree nor an install with .big archives")


def resolve_game_roots(
    games: Iterable[str | Path] | None, cache: Path | None = None
) -> tuple[Path, ...]:
    """`resolve_game_root` over a repeatable `--game` list (a `None`/empty list yields `()`)."""
    return tuple(resolve_game_root(game, cache) for game in games or ())
