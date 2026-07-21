"""Command-line entry point: `python -m sage_asset <command>` (or `sage-asset`).

Reads and inspects `asset.dat`, the BFME2/RotWK asset cache index - no game data beyond the
file itself is required.

- `info <dat>` - version, file/asset/reference counts, per-type asset tallies, and the time
  range spanned by the source files' mtimes.
- `ls <dat> [--type TEX] [--files-only]` - list files and the assets each one provides.
- `deps <dat> <name>` - reference lists for assets matching `name` (a file or asset name,
  case-insensitive); `--reverse` lists the assets that reference `name` instead.
- `json <dat> [--out] [--compact]` - the full parsed structure (files, assets, references) as
  a JSON document.
- `check <dat> [--art <art_dir>]` - parse, re-write, and confirm the result is byte-identical
  to the input; reports section-2/section-1 consistency findings and dangling references as
  warnings, never failures. `--art` additionally compares the asset.dat against an art tree's
  current state (missing / stale / orphaned entries), failing on missing or stale.
- `diff <a> <b>` - files added, removed or changed (file_time or asset list differs) between
  two asset.dat files.
- `combine <base> <overlay> [<overlay> ...] -o <out> [--show-overrides]` - concatenate a base
  asset.dat with one or more overlays (base first, overlays after, in order), write the result,
  and report the shadowing it produced; `--show-overrides` lists each shadowed name.
- `build <art_dir> -o <out>` - scan an unpacked art tree (`compiledtextures/`, `w3d/`) and
  write the asset.dat it describes.
"""

import argparse
import json
import sys
from pathlib import Path

from sage_asset.assetdat import (
    AssetDat,
    AssetDatError,
    ShadowedEntry,
    combine_asset_dats,
    parse_asset_dat_from_path,
    shadowed_entries,
    write_asset_dat,
    write_asset_dat_to_path,
)
from sage_asset.builder import build_asset_dat, collect_art_index
from sage_utils.cli import existing_dir, existing_file, utf8_stdout


def _to_dict(ad: AssetDat) -> dict:
    return {
        "version": ad.version,
        "files": [
            {
                "name": entry.name,
                "file_time": entry.file_time,
                "modified": entry.modified.isoformat(),
                "assets": [
                    {"name": a.name, "type": a.type, "offset": a.offset, "size": a.size}
                    for a in entry.assets
                ],
            }
            for entry in ad.files
        ],
        "references": [
            {
                "file_name": r.file_name,
                "asset_name": r.asset_name,
                "references": list(r.references),
            }
            for r in ad.references
        ],
    }


def _run_info(args: argparse.Namespace) -> int:
    ad = parse_asset_dat_from_path(args.dat)
    total_assets = sum(len(entry.assets) for entry in ad.files)

    print(f"Version:    0x{ad.version:x}")
    print(f"Files:      {len(ad.files)}")
    print(f"Assets:     {total_assets}")
    print(f"References: {len(ad.references)}")

    counts = ad.asset_counts()
    if counts:
        print("\nAssets by type:")
        for type_, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {count:6} x {type_}")

    if ad.files:
        oldest = min(ad.files, key=lambda entry: entry.file_time)
        newest = max(ad.files, key=lambda entry: entry.file_time)
        print(f"\nFile times: {oldest.modified.isoformat()} .. {newest.modified.isoformat()}")

    return 0


def _run_ls(args: argparse.Namespace) -> int:
    ad = parse_asset_dat_from_path(args.dat)
    type_filter = args.type.upper() if args.type else None

    for entry in ad.files:
        assets = [a for a in entry.assets if type_filter is None or a.type == type_filter]
        if type_filter is not None and not assets:
            continue

        print(entry.name)
        if not args.files_only:
            for asset in assets:
                print(f"  {asset.type:<5} {asset.name}  offset={asset.offset} size={asset.size}")

    return 0


def _run_deps(args: argparse.Namespace) -> int:
    ad = parse_asset_dat_from_path(args.dat)
    needle = args.name.lower()

    if args.reverse:
        matched = False
        for record in ad.references:
            if any(ref.lower() == needle for ref in record.references):
                matched = True
                print(f"{record.file_name} / {record.asset_name}")
        if not matched:
            print(f"nothing references {args.name!r}")
            return 1
        return 0

    matches = [
        record
        for record in ad.references
        if record.file_name.lower() == needle or record.asset_name.lower() == needle
    ]
    if not matches:
        print(f"no matching file or asset: {args.name!r}")
        return 1

    for record in matches:
        print(f"{record.file_name} / {record.asset_name}:")
        for ref in record.references:
            print(f"  {ref}")

    return 0


def _run_json(args: argparse.Namespace) -> int:
    ad = parse_asset_dat_from_path(args.dat)
    text = json.dumps(_to_dict(ad), indent=None if args.compact else 2)
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


def _run_check(args: argparse.Namespace) -> int:
    try:
        ad = parse_asset_dat_from_path(args.dat)
    except AssetDatError as exc:
        print(f"parse failed: {exc}")
        return 1

    original = Path(args.dat).read_bytes()
    rewritten = write_asset_dat(ad)
    if rewritten != original:
        print(
            f"round-trip mismatch: wrote {len(rewritten)} bytes, original is {len(original)} bytes"
        )
        return 1
    print(f"round-trip OK ({len(original)} bytes)")

    section1_pairs = {
        (entry.name.lower(), asset.name.lower()) for entry in ad.files for asset in entry.assets
    }
    seen: dict[tuple[str, str], int] = {}
    missing = 0
    for record in ad.references:
        key = (record.file_name.lower(), record.asset_name.lower())
        seen[key] = seen.get(key, 0) + 1
        if key not in section1_pairs:
            missing += 1
    duplicates = sum(1 for count in seen.values() if count > 1)

    if missing:
        print(f"warning: {missing} section-2 pairs have no matching section-1 asset")
    if duplicates:
        print(f"warning: {duplicates} duplicate (file, asset) pairs in section 2")

    resolvable = {entry.name.lower() for entry in ad.files}
    resolvable.update(asset.name.lower() for entry in ad.files for asset in entry.assets)
    dangling: dict[str, int] = {}
    for record in ad.references:
        for ref in record.references:
            ref_key = ref.lower()
            if ref_key not in resolvable:
                dangling[ref_key] = dangling.get(ref_key, 0) + 1
    if dangling:
        total = sum(dangling.values())
        examples = ", ".join(sorted(dangling)[:5])
        print(
            f"warning: {len(dangling)} dangling reference name(s), {total} occurrence(s) - "
            f"well-formed asset.dats have none (e.g. {examples})"
        )

    if args.art is None:
        return 0
    return _check_art(ad, args.art)


def _check_art(ad: AssetDat, art_dir: Path) -> int:
    """Compare `ad` against `art_dir`'s current state: entries the tree would produce but the
    asset.dat lacks (missing), entries whose recorded file_time no longer matches the source
    file's current one (stale), and entries whose source file is no longer in the tree
    (orphaned). Exits 1 on missing or stale - the classic "art changed, asset.dat wasn't
    rebuilt" failure - but not on orphaned alone, since a combined asset.dat legitimately
    carries base-game entries this mod's own art tree never had."""
    index = collect_art_index(art_dir)
    by_name = {entry.name.lower(): entry for entry in ad.files}

    missing = sorted(name for name in index if name not in by_name)
    stale = sorted(
        name
        for name, (_, filetime) in index.items()
        if name in by_name and by_name[name].file_time != filetime
    )
    orphaned = sorted(name for name in by_name if name not in index)

    def _report(label: str, names: list[str], note: str = "") -> None:
        examples = f" (e.g. {', '.join(names[:5])})" if names else ""
        print(f"{label}: {len(names)}{examples}{note}")

    _report("missing", missing)
    _report("stale", stale)
    _report(
        "orphaned",
        orphaned,
        " - fine for a combined asset.dat; --art is meant for a mod's own asset.dat against "
        "its own art tree"
        if orphaned
        else "",
    )

    return 1 if missing or stale else 0


def _run_diff(args: argparse.Namespace) -> int:
    a = parse_asset_dat_from_path(args.dat_a)
    b = parse_asset_dat_from_path(args.dat_b)

    a_by_name = {entry.name.lower(): entry for entry in a.files}
    b_by_name = {entry.name.lower(): entry for entry in b.files}

    added = sorted(set(b_by_name) - set(a_by_name))
    removed = sorted(set(a_by_name) - set(b_by_name))
    changed = sorted(
        name
        for name in set(a_by_name) & set(b_by_name)
        if a_by_name[name].file_time != b_by_name[name].file_time
        or a_by_name[name].assets != b_by_name[name].assets
    )

    for name in added:
        print(f"+ {b_by_name[name].name}")
    for name in removed:
        print(f"- {a_by_name[name].name}")
    for name in changed:
        print(f"~ {a_by_name[name].name}")

    print(
        f"\n{len(added)} added, {len(removed)} removed, {len(changed)} changed "
        f"({len(a.files)} -> {len(b.files)} files)"
    )
    return 0


def _run_combine(args: argparse.Namespace) -> int:
    base = parse_asset_dat_from_path(args.base)
    print(f"{args.base}: {len(base.files)} files, {len(base.references)} references")

    overlays = []
    for path in args.overlay:
        overlay = parse_asset_dat_from_path(path)
        print(f"{path}: {len(overlay.files)} files, {len(overlay.references)} references")
        overlays.append(overlay)

    combined = combine_asset_dats(base, *overlays)
    write_asset_dat_to_path(combined, args.out)

    shadowed = shadowed_entries(combined)
    identical = sum(1 for s in shadowed if s.identical)
    print(
        f"{args.out}: {len(combined.files)} files, {len(combined.references)} references, "
        f"{len(shadowed)} duplicate file names (later entries override earlier ones)"
    )
    if shadowed:
        print(
            f"shadowed: {len(shadowed)} entries ({identical} identical, "
            f"{len(shadowed) - identical} changed)"
        )
        if args.show_overrides:
            _print_shadowed(shadowed)

    return 0


def _print_shadowed(shadowed: list[ShadowedEntry]) -> None:
    for entry in shadowed:
        tag = "identical" if entry.identical else "changed"
        print(f"  {entry.name}  [{tag}]")


def _run_build(args: argparse.Namespace) -> int:
    ad = build_asset_dat(args.art_dir)
    write_asset_dat_to_path(ad, args.out)

    total_assets = sum(len(entry.assets) for entry in ad.files)
    print(
        f"{args.out}: {len(ad.files)} files, {total_assets} assets, {len(ad.references)} references"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    parser = argparse.ArgumentParser(prog="sage-asset", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    info = subparsers.add_parser("info", help="version / count / type-tally summary")
    info.add_argument("dat", type=existing_file)
    info.set_defaults(func=_run_info)

    ls = subparsers.add_parser("ls", help="list files and their assets")
    ls.add_argument("dat", type=existing_file)
    ls.add_argument("--type", default=None, help="only assets of this type (e.g. TEX)")
    ls.add_argument("--files-only", action="store_true", help="list file names only")
    ls.set_defaults(func=_run_ls)

    deps = subparsers.add_parser("deps", help="reference lists for a file or asset name")
    deps.add_argument("dat", type=existing_file)
    deps.add_argument("name", help="file or asset name to look up (case-insensitive)")
    deps.add_argument(
        "--reverse", action="store_true", help="list assets that reference name instead"
    )
    deps.set_defaults(func=_run_deps)

    to_json = subparsers.add_parser("json", help="the parsed asset.dat as a JSON document")
    to_json.add_argument("dat", type=existing_file)
    to_json.add_argument("--out", type=Path, default=None, help="write to a file instead of stdout")
    to_json.add_argument("--compact", action="store_true", help="single-line JSON")
    to_json.set_defaults(func=_run_json)

    check = subparsers.add_parser("check", help="round-trip and consistency check")
    check.add_argument("dat", type=existing_file)
    check.add_argument(
        "--art",
        type=existing_dir,
        default=None,
        help="also compare against this art tree's current state (missing/stale/orphaned)",
    )
    check.set_defaults(func=_run_check)

    diff = subparsers.add_parser("diff", help="files added / removed / changed between two files")
    diff.add_argument("dat_a", type=existing_file)
    diff.add_argument("dat_b", type=existing_file)
    diff.set_defaults(func=_run_diff)

    combine = subparsers.add_parser(
        "combine", help="concatenate a base asset.dat with one or more overlays"
    )
    combine.add_argument("base", type=existing_file)
    combine.add_argument("overlay", type=existing_file, nargs="+")
    combine.add_argument("-o", "--out", type=Path, required=True, help="where to write the result")
    combine.add_argument(
        "--show-overrides",
        action="store_true",
        help="list each shadowed file name with an identical/changed tag",
    )
    combine.set_defaults(func=_run_combine)

    build = subparsers.add_parser("build", help="build an asset.dat from an unpacked art tree")
    build.add_argument("art_dir", type=existing_dir)
    build.add_argument("-o", "--out", type=Path, required=True, help="where to write the result")
    build.set_defaults(func=_run_build)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
