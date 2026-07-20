"""The `manifest` command: load a base game and index it into a symbol manifest (see
`sage_ini.manifest`) - a JSON file capturing everything `sage_lint`'s rules read off base data.
Generating this once (and committing or sharing it) lets a mod be linted against the base game's
symbols later via `.sagelint`'s `base_manifest` / `lint --base-manifest`, with no base tree on
disk and none of the cost of loading one.
"""

import argparse


def run_manifest(args: argparse.Namespace) -> int:
    """Load the game named by `--game` (mounting `.big` archives into `--cache` as needed, same
    as every other game-consuming command) and write its symbol manifest to `args.output`
    (gzip-compressed when it ends in `.gz`), then print a summary - unless `--quiet`, which
    prints only the output path (the scriptable form: `sage_lint manifest ... -q > /dev/null` or
    piping the path onward). Diagnostics from loading the base game itself are not surfaced here:
    a base source loads silently everywhere else in `sage_lint` too, and a manifest is generated
    from data assumed to already be clean (or at least out of this tool's remit to fix).

    The heavy imports - the loader and the manifest build/write machinery - are lazy, so running
    any *other* `sage_lint` command never pays to import them.
    """
    from sage_ini.loader import load_game  # noqa: PLC0415 - lazy: only this command needs it
    from sage_ini.manifest import build_manifest, write_manifest  # noqa: PLC0415
    from sage_utils.gameroot import resolve_game_roots  # noqa: PLC0415

    roots = resolve_game_roots(args.game, args.cache)
    loaded = load_game(roots)
    data = build_manifest(loaded, roots)
    path = write_manifest(data, args.output)

    if args.quiet:
        print(path)
        return 0

    files = data["files"]
    definition_count = sum(len(records) for records in files.values())
    table_count = len({record["table"] for records in files.values() for record in records})
    print(
        f"indexed {definition_count} definition(s) across {len(files)} file(s) "
        f"({table_count} table(s))"
    )
    print(f"wrote manifest to {path}")
    return 0
