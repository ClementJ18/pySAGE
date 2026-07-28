"""Build the landing page that sits at the root of the published bucket.

Two static sites are published side by side: the engine reference (`build/wiki`, from
`sage_patch/scripts/build_wiki.py`) and the replay corpora (`build/aggregate`, from
`tools/rebuild_aggregates.py`). Neither knows about the other, so this writes the one
page above them that does.

The links are bucket keys, not local paths - `--wiki` and `--aggregate` name the
prefixes the two trees are uploaded under. What the page says about each comes from
whatever is on disk: the module and block counts from the reference's own JSON, the
corpus list from the aggregate tree.

Run from anywhere:  python tools/build_bucket_index.py
Then upload it to the bucket root:

    python tools/upload_aggregates.py --bucket <space> --region <region> \\
        --prefix "" --dir build/site-root

Keep `--delete` away from an empty prefix: it would treat the whole bucket as the
prefix's contents.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO / "build" / "site-root" / "index.html"
DEFAULT_AGGREGATE_DIR = REPO / "build" / "aggregate"
DEFAULT_REPLAY_DIR = REPO / "build" / "replays"
MODULE_JSON = REPO / "sage_patch" / "docs" / "module-reference.json"
TYPE_JSON = REPO / "sage_patch" / "docs" / "ini-types.json"

__all__ = ["build", "render"]

CSS = """
:root {
  --bg: #ffffff; --fg: #1c2024; --muted: #626b75; --line: #e3e7eb;
  --panel: #f7f8fa; --accent: #2f5bd0;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14171a; --fg: #e6e9ec; --muted: #98a2ad; --line: #262c33;
    --panel: #1a1e22; --accent: #7aa2f7;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 8vh 24px 60px; background: var(--bg); color: var(--fg);
  font-family: var(--sans); font-size: 15px; line-height: 1.6;
}
main { max-width: 860px; margin: 0 auto; }
h1 { font-size: 30px; margin: 0 0 6px; letter-spacing: -.4px; }
.sub { color: var(--muted); margin: 0 0 34px; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
code { font-family: var(--mono); font-size: 12.5px; background: var(--panel);
       padding: 1px 5px; border-radius: 4px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
.card {
  display: block; border: 1px solid var(--line); border-radius: 12px; padding: 20px 22px;
  background: var(--panel); color: var(--fg);
}
.card:hover { border-color: var(--accent); }
.card h2 { font-size: 19px; margin: 0 0 6px; }
.card h2 a { color: var(--fg); }
.card h2 a:hover { color: var(--accent); }
.card p { margin: 0 0 12px; color: var(--muted); font-size: 14px; }
.card .facts { font-size: 12.5px; color: var(--muted); font-family: var(--mono); }
.links { margin-top: 12px; display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 13px; }
.none { color: var(--muted); font-size: 13px; }
footer { margin-top: 44px; color: var(--muted); font-size: 12.5px;
         border-top: 1px solid var(--line); padding-top: 14px; }
"""


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def reference_facts() -> str:
    """Modules, block types and fields, from the reference's own data."""
    try:
        with open(MODULE_JSON, encoding="utf-8") as fh:
            modules = json.load(fh)
        with open(TYPE_JSON, encoding="utf-8") as fh:
            types = json.load(fh)
    except (OSError, ValueError):
        return ""
    blocks = types.get("ini_blocks", {})
    fields = sum(len(m["fields"]) for m in modules) + sum(len(b["fields"]) for b in blocks.values())
    return (
        f"{len(modules)} modules &middot; {len(blocks)} block types &middot; "
        f"{fields} fields &middot; {len(types.get('name_tables', {}))} enumerations"
    )


def replay_count(directory: Path) -> int:
    """How many replays the replay repository publishes, from the per-corpus manifests it
    writes; zero when it has never been built."""
    total = 0
    for manifest in sorted((directory / "manifests").glob("*.json")) if directory.is_dir() else []:
        data = _read_json(manifest)
        total += len(data.get("rows") or []) if data else 0
    return total


def corpora(directory: Path) -> list[str]:
    """The corpus folders in an aggregate tree, in the order the index lists them."""
    if not directory.is_dir():
        return []
    return sorted(
        child.name
        for child in directory.iterdir()
        if child.is_dir() and (child / "index.html").is_file()
    )


def render(
    wiki_prefix: str,
    aggregate_prefix: str,
    replay_prefix: str,
    found: list[str],
    replays: int,
    facts: str,
    title: str,
) -> str:
    wiki = f"{wiki_prefix}/index.html" if wiki_prefix else "index.html"
    aggregate = f"{aggregate_prefix}/index.html" if aggregate_prefix else "index.html"
    replay_page = f"{replay_prefix}/index.html" if replay_prefix else "index.html"
    sub_links = "\n".join(
        f'<a href="{esc(wiki_prefix)}/{page}">{label}</a>'
        for page, label in (
            ("modules.html", "Modules"),
            ("blocks.html", "Blocks"),
            ("types.html", "Types"),
            ("enums.html", "Enumerations"),
            ("check.html", "Check a block"),
        )
    )
    listed = (
        "\n".join(
            f'<a href="{esc(aggregate_prefix)}/{esc(name)}/index.html">{esc(name)}</a>'
            for name in found
        )
        or '<span class="none">no corpora published yet</span>'
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>{esc(title)}</h1>
<p class="sub">Two things live here: what the engine does with the data you write, and
what players actually did with it.</p>

<div class="cards">
  <div class="card">
    <h2><a href="{esc(wiki)}">Engine reference</a></h2>
    <p>Every module the engine registers and every block type its INI loader dispatches
    on, with the keywords each accepts, the type of every keyword and the value it holds
    when you leave the line out - read out of the binary rather than transcribed.</p>
    <div class="facts">{facts}</div>
    <div class="links">{sub_links}</div>
  </div>
  <div class="card">
    <h2><a href="{esc(aggregate)}">Replay corpora</a></h2>
    <p>Faction-by-faction aggregates over recorded games: what gets built, researched and
    bought, split by player count and matchup.</p>
    <div class="links">{listed}</div>
  </div>
  <div class="card">
    <h2><a href="{esc(replay_page)}">Replays</a></h2>
    <p>The recordings themselves, each beside the translated document it was parsed into -
    filterable by game, patch, mode, faction and player, and downloadable either way.</p>
    <div class="facts">{f"{replays} replays" if replays else "not published yet"}</div>
  </div>
</div>

<footer>
Static pages, no tracking, nothing to sign in to. The reference is generated from a
ROTWK <code>game.dat</code> and carries no game assets.
</footer>
</main>
</body>
</html>
"""


def build(
    out: Path,
    wiki_prefix: str,
    aggregate_prefix: str,
    replay_prefix: str,
    aggregate_dir: Path,
    replay_dir: Path,
    title: str,
) -> Path:
    page = render(
        wiki_prefix.strip("/"),
        aggregate_prefix.strip("/"),
        replay_prefix.strip("/"),
        corpora(aggregate_dir),
        replay_count(replay_dir),
        reference_facts(),
        title,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"where to write the page (default: {DEFAULT_OUT})",
    )
    ap.add_argument(
        "--wiki",
        default="wiki",
        help="bucket prefix the reference is uploaded under (default: wiki)",
    )
    ap.add_argument(
        "--aggregate",
        default="aggregate",
        help="bucket prefix the corpora are uploaded under (default: aggregate)",
    )
    ap.add_argument(
        "--aggregate-dir",
        type=Path,
        default=DEFAULT_AGGREGATE_DIR,
        help="local aggregate tree, read only to list the corpora "
        f"(default: {DEFAULT_AGGREGATE_DIR})",
    )
    ap.add_argument(
        "--replays",
        default="replays",
        help="bucket prefix the replay repository is uploaded under (default: replays)",
    )
    ap.add_argument(
        "--replays-dir",
        type=Path,
        default=DEFAULT_REPLAY_DIR,
        help=f"local replay repository, read only for its count (default: {DEFAULT_REPLAY_DIR})",
    )
    ap.add_argument("--title", default="BFME / SAGE", help="page heading (default: BFME / SAGE)")
    args = ap.parse_args(argv)

    written = build(
        args.out,
        args.wiki,
        args.aggregate,
        args.replays,
        args.aggregate_dir,
        args.replays_dir,
        args.title,
    )
    found = corpora(args.aggregate_dir)
    print(f"wrote {written}")
    print(
        f"links: {args.wiki}/index.html, {args.aggregate}/index.html, "
        f"{args.replays}/index.html"
        + (
            f" ({len(found)} corpora listed, {replay_count(args.replays_dir)} replays)"
            if found
            else " (no corpora found locally)"
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
