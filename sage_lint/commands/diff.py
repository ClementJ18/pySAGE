"""The `diff` command: a human-readable changelog of game-data changes between two git refs,
each assembled the way `lint` builds a game (config-aware, base game merged in). Also the
`diff-maps` command: a content changelog of the binary `.map`/`.bse` files one commit touches,
parsed straight out of the object store — no game assembly or config involved.
"""

import argparse
import json
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path

from sage_ini.diff import diff_games, format_game_diff, git_worktree
from sage_ini.player_diff import format_player_diff
from sage_lint.commands.common import base_source, config_path
from sage_lint.config import Config, load_config
from sage_lint.linter import assemble_with_bases
from sage_utils.cli import utf8_stdout


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
            if args.player:
                utf8_stdout()  # localized display names are non-ASCII (Lothlórien, Éomer)
                print()
                print(format_player_diff(diff, old_game, new_game, args.old, args.new), end="")
    except subprocess.CalledProcessError as exc:
        print(f"git failed: {exc.stderr or exc}", file=sys.stderr)
        return 2
    return 0


def run_diff_maps(args: argparse.Namespace) -> int:
    """Changelog of the `.map`/`.bse` files `commit` touches — a single commit diffed against
    its parent, or a git range (`old..new` / `old...new`) diffed endpoint against endpoint —
    each side parsed out of git and compared structurally (objects, teams, scripts, terrain),
    the report git's binary-file diff cannot give. `sage_map` is imported lazily so `sage_lint`
    runs without the optional `[map]` extra installed."""
    try:
        from sage_map.diff import (  # noqa: PLC0415 — lazy: the [map] extra is optional
            diff_commit_maps,
            diff_range_maps,
            format_map_file_diffs,
            format_map_file_diffs_md,
            resolve_range,
        )
    except ImportError:
        print(
            "sage_lint: map diffing needs the optional 'map' extra (pip install 'pysage[map]')",
            file=sys.stderr,
        )
        return 2

    repo = (args.dir or Path.cwd()).resolve()
    try:
        endpoints = resolve_range(repo, args.commit)
        if endpoints is not None:
            old_label, new_label = endpoints
            results = diff_range_maps(repo, old_label, new_label)
        else:
            old_label, new_label = f"{args.commit}^", args.commit
            results = diff_commit_maps(repo, args.commit)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        print(f"git failed: {(stderr or '').strip() or exc}", file=sys.stderr)
        return 2

    if args.output_format == "json":
        report = {
            "old": old_label,
            "new": new_label,
            "files": [result.to_dict() for result in results],
        }
        print(json.dumps(report, indent=2))
    elif args.output_format == "md":
        print(format_map_file_diffs_md(results, old_label, new_label), end="")
    else:
        print(format_map_file_diffs(results, old_label, new_label), end="")
    return 0
