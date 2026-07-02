"""The `diff` command: a human-readable changelog of game-data changes between two git refs,
each assembled the way `lint` builds a game (config-aware, base game merged in).
"""

import argparse
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path

from sage_ini.diff import diff_games, format_game_diff, git_worktree
from sage_lint.commands.common import base_source, config_path
from sage_lint.config import Config, load_config
from sage_lint.linter import assemble_with_bases


def run_diff(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Changelog of game-data changes between two git refs, assembled the way `lint` builds a
    game: the `.sagelint` config (root, base) is read from the repo working dir, then each ref is
    checked out into a temp worktree and assembled WITH the base-game archives merged in, so an
    `#include` into the base resolves on both sides and the diff reports real changes, not
    unresolved-include load artifacts."""
    config_dir = (args.dir or Path.cwd()).resolve()
    config = Config() if args.no_config else load_config(config_dir)
    for warning in config.warnings:
        print(warning, file=sys.stderr)

    bases = list(args.base) if args.base else [config_path(config_dir, b) for b in config.base]
    base_sources = tuple(base_source(Path(b)) for b in bases)
    rel_root = config.root if config.root and not Path(config.root).is_absolute() else None

    def game_at(ref: str, stack: ExitStack):
        tree = stack.enter_context(git_worktree(config_dir, ref))
        root = tree / rel_root if rel_root else tree
        if not root.is_dir():
            parser.error(f"root {root.name!r} not found at ref {ref!r}")
        loaded, base_layer = assemble_with_bases(root, base_sources)
        if base_layer is not None:
            stack.callback(base_layer.cleanup)
        return loaded.game

    try:
        with ExitStack() as stack:
            old_game = game_at(args.old, stack)
            new_game = game_at(args.new, stack)
            diff = diff_games(old_game, new_game, strings=args.strings)
            print(format_game_diff(diff, args.old, args.new), end="")
    except subprocess.CalledProcessError as exc:
        print(f"git failed: {exc.stderr or exc}", file=sys.stderr)
        return 2
    return 0
