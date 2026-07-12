"""Download replay files from bfmeladder.com (BFME Arena) for parsing.

The site keeps a JSON index of every replay at /api/replays; each entry records
game, patch, version, gamemode, map, players, and the id used by the download
endpoint. This script fetches that index once, filters it, and downloads the
matching replay files (plus a sidecar .json with the index entry, which carries
ground truth such as IsWinner per player).

Filters mirror the dropdowns on https://www.bfmeladder.com/replays:
  --game      All games | BFME1 | BFME2 | RotWK
  --patch     patch name as shown in the dropdown (e.g. "Edain", "Edain
              Unchained", "Ennorath", "Patch 2.02") or a raw patch id
  --gamemode  All gamemodes | 1 versus 1 | 2 versus 2 | 3 versus 3 |
              4 versus 4 | FFA (short forms 1v1/2v2/3v3/4v4 accepted; other
              values like "3 versus 3 NM" are matched as-is)
  --version   any string, matched exactly against the replay's patch version

Usage: python tools/download_bfme_replays.py [options]
  --game NAME       filter by game (default: all)
  --patch NAME      filter by patch name or id (default: all)
  --version VER     filter by patch version, e.g. 4.8.4.3 (default: all)
  --gamemode NAME   filter by gamemode (default: all)
  --out DIR         output directory (default: replays_bfmeladder)
  --limit N         download at most N replays, newest first (default: all)
  --list-options    print the filter values present in the live index and exit
  --dry-run         list what would be downloaded without downloading
  --no-metadata     skip writing the <replay>.json sidecar files
  --delay SECONDS   pause between downloads (default: 0.5)
"""

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "https://www.bfmeladder.com"
INDEX_URL = f"{BASE_URL}/api/replays"
DOWNLOAD_URL = f"{BASE_URL}/api/replays/download?replayId="
USER_AGENT = "sage-replay-corpus-downloader (github ini_parser)"

# Dropdown short forms -> GamemodeName variants seen in the index. Anything
# not listed here is matched against GamemodeName verbatim.
GAMEMODE_ALIASES = {
    "1 versus 1": {"1 versus 1", "1v1"},
    "2 versus 2": {"2 versus 2", "2v2"},
    "3 versus 3": {"3 versus 3", "3v3"},
    "4 versus 4": {"4 versus 4", "4v4"},
    "1v1": {"1 versus 1", "1v1"},
    "2v2": {"2 versus 2", "2v2"},
    "3v3": {"3 versus 3", "3v3"},
    "4v4": {"4 versus 4", "4v4"},
}


def fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def patch_parts(entry: dict) -> tuple[str, str, str]:
    """(patch id, version, patch display name) for an index entry."""
    patch_id, _, version = (entry.get("PatchId") or "").partition(":")
    name = entry.get("PatchName") or ""
    # PatchName is "Edain (4.8.4.3)"; strip the trailing version.
    if version and name.endswith(f"({version})"):
        name = name[: -len(version) - 2].rstrip()
    return patch_id, version, name


def is_all(value: str | None) -> bool:
    return value is None or value.lower().startswith("all")


def matches(entry: dict, args: argparse.Namespace) -> bool:
    if not is_all(args.game) and (entry.get("GameName") or "").lower() != args.game.lower():
        return False
    patch_id, version, patch_name = patch_parts(entry)
    if not is_all(args.patch):
        want = args.patch.lower()
        if want not in (patch_id.lower(), patch_name.lower()):
            return False
    if args.version and version.lower() != args.version.lower():
        return False
    if not is_all(args.gamemode):
        allowed = GAMEMODE_ALIASES.get(
            args.gamemode.lower(), GAMEMODE_ALIASES.get(args.gamemode, {args.gamemode})
        )
        allowed = {g.lower() for g in allowed}
        if (entry.get("GamemodeName") or "").lower() not in allowed:
            return False
    return True


def list_options(index: dict) -> None:
    games, modes = set(), set()
    versions_by_patch: dict[str, set[str]] = {}
    for entry in index.values():
        games.add(entry.get("GameName") or "?")
        modes.add(entry.get("GamemodeName") or "?")
        _, version, name = patch_parts(entry)
        versions_by_patch.setdefault(name, set()).add(version)
    print("games:    " + ", ".join(sorted(games)))
    print("gamemodes: " + ", ".join(sorted(modes)))
    print("patches:")
    for name in sorted(versions_by_patch):
        versions = ", ".join(sorted(versions_by_patch[name]))
        print(f"  {name}: {versions}")


def download(replay_id: str, dest: Path) -> None:
    url = DOWNLOAD_URL + urllib.parse.quote(replay_id)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req) as resp:
        data = resp.read()
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(dest)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download replays from bfmeladder.com", add_help=True
    )
    parser.add_argument("--game", default=None, help="BFME1, BFME2, RotWK")
    parser.add_argument(
        "--patch", default=None, help="patch name (Edain, Ennorath, ...) or patch id"
    )
    parser.add_argument("--version", default=None, help="patch version, any string (e.g. 4.8.4.3)")
    parser.add_argument("--gamemode", default=None, help="1 versus 1, 2v2, FFA, ...")
    parser.add_argument("--out", default="replays_bfmeladder", type=Path)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--list-options", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-metadata", action="store_true")
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()

    print(f"fetching index {INDEX_URL} ...", file=sys.stderr)
    index = fetch_json(INDEX_URL)
    print(f"index has {len(index)} replays", file=sys.stderr)

    if args.list_options:
        list_options(index)
        return 0

    selected = [e for e in index.values() if matches(e, args)]
    selected.sort(key=lambda e: int(e.get("Date") or 0), reverse=True)
    if args.limit is not None:
        selected = selected[: args.limit]
    print(f"{len(selected)} replays match the filters", file=sys.stderr)

    if args.dry_run:
        for entry in selected:
            _, version, patch_name = patch_parts(entry)
            print(
                f"{entry['ReplayId']}  {entry.get('GameName')}  {patch_name} {version}  "
                f"{entry.get('GamemodeName')}  {entry.get('MapName')}  {entry.get('Duration')}"
            )
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    done = skipped = failed = 0
    for i, entry in enumerate(selected, 1):
        replay_id = entry["ReplayId"]
        dest = args.out / replay_id
        meta = dest.with_suffix(dest.suffix + ".json")
        if dest.exists():
            skipped += 1
        else:
            print(f"[{i}/{len(selected)}] {replay_id}", file=sys.stderr)
            try:
                download(replay_id, dest)
            except Exception as exc:  # noqa: BLE001
                print(f"  failed: {exc}", file=sys.stderr)
                failed += 1
                continue
            done += 1
            time.sleep(args.delay)
        if not args.no_metadata and not meta.exists():
            meta.write_text(json.dumps(entry, indent=2), encoding="utf-8")
    print(f"downloaded {done}, skipped {skipped} already present, {failed} failed", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
