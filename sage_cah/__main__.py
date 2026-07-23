"""Command-line entry point: `python -m sage_cah <command>` (or `sage-cah`).

Reads and inspects `.cah` files (BFME2/RotWK Create-a-Hero saves) - no game data beyond the
file itself is required.

- `info <cah>` - name, class/sub-class (mapped display name + raw index), obj_id, colors, the
  non-empty powers, bling (stat groups shown as a value, visual groups as a raw index), guid,
  system-hero flag, and whether the stored checksum matches the current fields.
- `json <cah> [--out FILE] [--compact]` - the full parsed structure as a JSON document, all 15
  power slots included.
- `check <path>` - a .cah file, or a directory (recursively, `*.cah`/`*.CAH`): parse, re-write,
  and confirm the result is byte-identical to the input, and that the stored checksum is valid.
  Exits 1 if any file fails to parse, round-trips differently, or has a checksum mismatch.
- `fix <cah> -o OUT [--new-guid]` - rewrite with a refreshed checksum (`--new-guid` also assigns
  a fresh GUID first); prints the old and new checksum. The companion for hand-edited or
  `json`-driven changes, whose checksum would otherwise go stale.
"""

import argparse
import json
import sys
from pathlib import Path

from sage_cah.cah import (
    BLING_STAT_GROUPS,
    CLASS_NAMES,
    SUB_CLASS_NAMES,
    CahError,
    CustomHero,
    compute_checksum,
    new_guid,
    parse_cah,
    parse_cah_from_path,
    write_cah,
    write_cah_to_path,
)
from sage_utils.cli import existing_file, existing_path, utf8_stdout


def _to_dict(hero: CustomHero) -> dict:
    return {
        "header_unk1": hero.header_unk1,
        "header_unk2": hero.header_unk2,
        "version": hero.version,
        "obj_id": hero.obj_id,
        "name": hero.name,
        "class_index": hero.class_index,
        "sub_class_index": hero.sub_class_index,
        "reserved1": hero.reserved1,
        "reserved2": hero.reserved2,
        "color1": hero.color1,
        "color2": hero.color2,
        "color3": hero.color3,
        "powers": [
            {
                "command_button": p.command_button,
                "exp_level": p.exp_level,
                "button_index": p.button_index,
            }
            for p in hero.powers
        ],
        "blings": [{"group_name": b.group_name, "bling_index": b.bling_index} for b in hero.blings],
        "guid": hero.guid,
        "is_system_hero": hero.is_system_hero,
        "checksum": hero.checksum,
    }


def _run_info(args: argparse.Namespace) -> int:
    hero = parse_cah_from_path(args.cah)

    class_name = CLASS_NAMES.get(hero.class_index, str(hero.class_index))
    sub_class_name = SUB_CLASS_NAMES.get(hero.class_index, {}).get(
        hero.sub_class_index, str(hero.sub_class_index)
    )

    print(f"Name:        {hero.name}")
    print(
        f"Class:       {class_name} ({hero.class_index}) / "
        f"{sub_class_name} ({hero.sub_class_index})"
    )
    print(f"Obj ID:      {hero.obj_id}")
    print(f"Colors:      0x{hero.color1:08X} 0x{hero.color2:08X} 0x{hero.color3:08X}")

    print("\nPowers:")
    for i, power in enumerate(hero.powers):
        if power.is_empty:
            continue
        print(f"  level {power.level}: {power.command_button} (slot {i})")

    print("\nBling:")
    for bling in hero.blings:
        if bling.group_name in BLING_STAT_GROUPS:
            print(f"  {bling.group_name}: value {bling.value}")
        else:
            print(f"  {bling.group_name}: {bling.bling_index}")

    print(f"\nGUID:        {hero.guid}")
    print(f"System hero: {hero.is_system_hero}")
    if hero.checksum_valid:
        print(f"checksum OK (0x{hero.checksum:08x})")
    else:
        print(
            f"checksum MISMATCH: stored 0x{hero.checksum:08x} != "
            f"computed 0x{compute_checksum(hero):08x}"
        )

    return 0


def _run_json(args: argparse.Namespace) -> int:
    hero = parse_cah_from_path(args.cah)
    text = json.dumps(_to_dict(hero), indent=None if args.compact else 2)
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


def _iter_cah_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() == ".cah")


def _run_check(args: argparse.Namespace) -> int:
    files = _iter_cah_files(args.path)
    if not files:
        print(f"no .cah files found under {args.path}")
        return 0

    failures = 0
    for path in files:
        data = path.read_bytes()
        try:
            hero = parse_cah(data)
        except CahError as exc:
            print(f"FAIL {path}: parse error: {exc}")
            failures += 1
            continue

        rewritten = write_cah(hero)
        if rewritten != data:
            print(f"FAIL {path}: round-trip mismatch ({len(rewritten)} vs {len(data)} bytes)")
            failures += 1
            continue

        if not hero.checksum_valid:
            print(
                f"FAIL {path}: checksum mismatch: stored 0x{hero.checksum:08x} != "
                f"computed 0x{compute_checksum(hero):08x}"
            )
            failures += 1
            continue

        print(f"ok   {path}")

    print(f"\n{len(files)} file(s), {failures} failure(s)")
    return 1 if failures else 0


def _run_fix(args: argparse.Namespace) -> int:
    hero = parse_cah_from_path(args.cah)
    old_checksum = hero.checksum
    if args.new_guid:
        hero.guid = new_guid()

    write_cah_to_path(hero, args.out, refresh_checksum=True)

    new_checksum = compute_checksum(hero)
    print(f"{args.cah}: checksum 0x{old_checksum:08x} -> 0x{new_checksum:08x}")
    print(f"wrote {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    parser = argparse.ArgumentParser(prog="sage-cah", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    info = subparsers.add_parser("info", help="identity / class / powers / bling summary")
    info.add_argument("cah", type=existing_file)
    info.set_defaults(func=_run_info)

    to_json = subparsers.add_parser("json", help="the parsed structure as a JSON document")
    to_json.add_argument("cah", type=existing_file)
    to_json.add_argument("--out", type=Path, default=None, help="write to a file instead of stdout")
    to_json.add_argument("--compact", action="store_true", help="single-line JSON")
    to_json.set_defaults(func=_run_json)

    check = subparsers.add_parser(
        "check", help="round-trip and checksum check a file or a directory of them"
    )
    check.add_argument("path", type=existing_path)
    check.set_defaults(func=_run_check)

    fix = subparsers.add_parser(
        "fix", help="rewrite with a refreshed checksum (and optionally a new GUID)"
    )
    fix.add_argument("cah", type=existing_file)
    fix.add_argument("-o", "--out", type=Path, required=True, help="where to write the result")
    fix.add_argument("--new-guid", action="store_true", help="assign a fresh GUID before writing")
    fix.set_defaults(func=_run_fix)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
