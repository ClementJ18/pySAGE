"""Rebuild the Edain replay-corpus aggregate HTML pages.

Everything lands under one output dir (`aggregate/` by default):

    aggregate/
      index.html               navigation index (corpus tiles, leaderboard, matchup matrix)
      aggregate.html           the combined report over every faction
      aggregate_names.json     hand-maintained localisation map (tracked; see below)
      factions/<slug>.html     one page per faction, filtered to just that faction

All of it is built from the `downloads/replays/edain-4.8.4.3` corpus resolved against the live
BFME2 + RotWK/Edain installs. This mirrors `sage-edain replay-aggregate --html` with Edain's
knowledge injected (economy/library research rows, CP-purchase depth, Dwarves split into their
realm) and `--matchups` on.

Code names (faction names and every pick-table entry) are shown through the hand-maintained
localisation file: a `{code name: display string}` map. Each rebuild adds any code name it
renders that the file is missing, with an empty string to fill in by hand. A filled entry
renders as `display string (code name)` - the raw code name stays visible in brackets - while
an empty (or absent) one falls back to the bare code name, so pages always render.

Run from anywhere:  python tools/rebuild_aggregates.py
Override the paths with --corpus / --game / --out / --names if your installs live elsewhere.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from html import escape
from os.path import relpath
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))  # allow running this file directly, not just as a module

from sage_edain.replay import (  # noqa: E402
    TRACKED_PURCHASES,
    TRACKED_UPGRADES,
    dwarven_realm_faction,
)
from sage_replay.aggregate import (  # noqa: E402
    aggregate,
    collect,
    render_aggregate_html,
    render_index_html,
)
from sage_replay.narrate import GameData  # noqa: E402
from sage_replay.stats import _clock  # noqa: E402
from sage_utils.gameroot import resolve_game_roots  # noqa: E402

DEFAULT_CORPUS = REPO / "downloads" / "replays" / "edain-4.8.4.3"
DEFAULT_GAME = [Path(r"C:\BFME2"), Path(r"C:\RotWK")]
DEFAULT_OUT = REPO / "aggregate"
DEFAULT_NAMES = DEFAULT_OUT / "aggregate_names.json"
TITLE = "Edain 4.8.4.3 replay corpus"

# The FactionAggregate attributes whose ChoiceStat labels are rendered code names.
_LABEL_CATEGORIES = (
    "sciences",
    "first_science",
    "buildings",
    "units",
    "heroes",
    "upgrades",
    "other",
)


def _slug(label: str) -> str:
    """A faction label's output filename stem: `FactionMen` -> `men`,
    `Dwarves (Ered Luin)` -> `dwarves-ered-luin`, the unresolved `?` -> `random`."""
    stem = re.sub(r"^Faction", "", label)
    stem = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return stem or "random"


def _collect_labels(factions) -> set[str]:
    """Every distinct code name the aggregate renders: each faction name plus every
    pick-table entry, recursing through the per-matchup sub-aggregates."""
    labels: set[str] = set()

    def walk(aggs) -> None:
        for agg in aggs:
            labels.add(agg.faction)
            for attribute in _LABEL_CATEGORIES:
                labels.update(getattr(agg, attribute))
            walk(agg.matchups.values())

    walk(factions)
    return labels


def _load_names(path: Path, labels: set[str]) -> tuple[dict[str, str], int]:
    """Load the localisation map, adding a blank entry for any rendered code name it is
    missing, and rewrite it (sorted) so new names surface for hand-translation. Returns the
    map and how many entries were newly added."""
    names: dict[str, str] = {}
    if path.exists():
        names = json.loads(path.read_text(encoding="utf-8"))
    before = len(names)
    for label in labels:
        names.setdefault(label, "")
    if len(names) != before or not path.exists():
        text = json.dumps(names, ensure_ascii=False, indent=2, sort_keys=True)
        path.write_text(text + "\n", encoding="utf-8")
    return names, len(names) - before


def _write(
    path: Path,
    corpus,
    factions,
    title: str,
    translate,
    extra=None,
    annotate=None,
    index_href=None,
) -> None:
    html = "\n".join(
        render_aggregate_html(
            corpus,
            factions,
            title=title,
            translate=translate,
            extra=extra,
            annotate=annotate,
            index_href=index_href,
        )
    )
    path.write_text(html, encoding="utf-8")
    print(f"wrote {path.relative_to(REPO)}  ({len(factions)} faction(s))")


_ROSTER_ATTRS = ("buildings", "units", "heroes")


def _faction_own_side(agg, data) -> str | None:
    """The faction's own roster Side: the effective Side most of its unit/building/hero picks
    carry (weighted by games). Robust to the odd cross-faction pick, and needs no faction/Side
    table - it reads the faction back off what it actually fields."""
    counts: Counter[str] = Counter()
    for attribute in _ROSTER_ATTRS:
        for label, choice in getattr(agg, attribute).items():
            side = data.effective_side(label)
            if side:
                counts[side] += choice.games
    return counts.most_common(1)[0][0] if counts else None


def _side_annotator(combined, data):
    """A `render_aggregate_html` annotator that badges a pick whose unit Side is a *different*
    faction's than the one whose page it is on - the tell-tale of a disconnected ally's roster
    built from their inherited base (see the corpus's rare 3v3 late-game takeovers). Side is
    not identity, so the pick is kept and flagged rather than dropped."""
    own_side = {agg.faction: _faction_own_side(agg, data) for agg in combined}
    faction_sides = {side for side in own_side.values() if side}

    def annotate(owner: str, label: str) -> str:
        side = data.effective_side(label)
        expected = own_side.get(owner)
        if side and expected and side in faction_sides and side != expected:
            return (
                f'<span class="badge" title="this unit&#39;s Side is {escape(side)}, not '
                f'{escape(owner)} - likely built from a disconnected ally&#39;s base">'
                f"{escape(side)}?</span>"
            )
        return ""

    return annotate


_RESULT = {"won": ("Win", "win"), "lost": ("Loss", "loss")}


def _replay_rows(games, display) -> list[str]:
    """A faction's player-games as a table: who played it, the faction(s) they faced, the
    result, the match length, and the replay file - wins first, then longest games."""
    if not games:
        return []
    rank = {"won": 0, "lost": 1, "undetermined": 2}
    ordered = sorted(games, key=lambda g: (rank.get(g.outcome, 3), -g.duration))
    lines = [
        f"<h3>Replays ({len(ordered)})</h3>",
        '<div class="tablewrap"><table>',
        "<thead><tr><th>Player</th><th>Versus</th><th>Result</th>"
        "<th>Length</th><th>Replay</th></tr></thead>",
        "<tbody>",
    ]
    for game in ordered:
        versus = ", ".join(escape(display(o)) for o in game.opponents) or "&mdash;"
        label, cls = _RESULT.get(game.outcome, ("&mdash;", "dim"))
        lines.append(
            f"<tr><td>{escape(game.player)}</td><td>{versus}</td>"
            f'<td class="{cls}">{label}</td>'
            f'<td class="dim">{_clock(game.duration)}</td>'
            f'<td class="rep">{escape(game.replay)}</td></tr>'
        )
    lines.extend(["</tbody>", "</table></div>"])
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS, help="replay corpus dir")
    parser.add_argument(
        "--game",
        type=Path,
        action="append",
        default=None,
        help="game root (repeatable, base first); defaults to C:\\BFME2 then C:\\RotWK",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output dir for all pages")
    parser.add_argument("--title", default=TITLE, help="page title / corpus label")
    parser.add_argument(
        "--names",
        type=Path,
        default=DEFAULT_NAMES,
        help="localisation map (code name -> display string); grown with new names each run",
    )
    args = parser.parse_args(argv)

    game_roots = args.game or DEFAULT_GAME
    print(f"loading game from {', '.join(str(g) for g in game_roots)} ...")
    data = GameData.from_root(resolve_game_roots(game_roots, None), localize=False)

    print(f"collecting corpus from {args.corpus} ...")
    # The corpus is uploaded winners' replays, so decide otherwise-undetermined games in favour
    # of the recording player's team (the CLI's --winner-pov / infer_winner's assume_pov_won).
    corpus = collect(
        args.corpus and [args.corpus],
        data,
        refine_faction=dwarven_realm_faction,
        assume_pov_won=True,
    )
    print(f"  {corpus.replays} replays -> {len(corpus.games)} player-games")
    for warning in corpus.warnings:
        print(f"  warning: {warning}")

    # `collect` has already dropped unresolved-faction ("?") player-games into the warnings
    # above and scrubbed "?" from every surviving game's opponents, so nothing here needs to.

    def _aggregate(games):
        return aggregate(
            games,
            tracked_upgrades=TRACKED_UPGRADES,
            tracked_purchases=TRACKED_PURCHASES,
            matchups=True,
        )

    # The combined page over the whole corpus (its aggregate also drives the index's
    # leaderboard and matchup matrix, so compute it once).
    combined = _aggregate(corpus.games)

    # Grow the hand-maintained localisation map with any newly-rendered code name, then
    # resolve each code name to its display string (blank/absent -> the raw code name).
    names, added = _load_names(args.names, _collect_labels(combined))
    untranslated = sum(1 for value in names.values() if not value)
    print(
        f"names: {len(names)} keys ({added} new, {untranslated} untranslated) "
        f"-> {args.names.relative_to(REPO)}"
    )

    def display(code: str) -> str:
        # A translated entry shows its display string with the raw code name in brackets
        # ("Hall of the King's Men (AngmarBarracks)"); a blank/absent one is just the code name.
        name = names.get(code)
        return f"{name} ({code})" if name else code

    # Badge any pick whose unit Side is a different faction's than the page it sits on - a
    # disconnected ally's roster the surviving teammate built from the inherited base.
    annotate = _side_annotator(combined, data)

    # Everything lands under the output dir: the combined report at its root, the per-faction
    # pages in a factions/ subfolder.
    factions_dir = args.out / "factions"
    factions_dir.mkdir(parents=True, exist_ok=True)
    for stale in factions_dir.glob("*.html"):  # a faction that dropped out keeps no stale page
        stale.unlink()

    index_path = args.out / "index.html"

    def _index_href(page: Path) -> str:
        """The index href for a page, relative to that page's own folder, so the whole
        output dir can move as a unit (`index.html` from the root, `../index.html` from
        the factions/ subfolder)."""
        return relpath(index_path, page.parent).replace("\\", "/")

    combined_page = args.out / "aggregate.html"
    _write(
        combined_page,
        corpus,
        combined,
        args.title,
        display,
        annotate=annotate,
        index_href=_index_href(combined_page),
    )

    # One page per faction label, filtered to just that faction's player-games. Each page
    # also lists that faction's replays and the opponent faced (rendered after its aggregate
    # block via the `extra` hook); the combined page above omits the lists.
    games_by_faction: dict[str, list] = defaultdict(list)
    for game in corpus.games:
        games_by_faction[game.faction].append(game)

    labels = sorted(games_by_faction)
    for label in labels:
        games = games_by_faction[label]
        filtered = type(corpus)(games=games, replays=corpus.replays, warnings=corpus.warnings)
        title = f"{display(label)} - {args.title}"
        page = factions_dir / f"{_slug(label)}.html"

        def extra(agg, games=games):  # noqa: B008 - the faction's replay list, appended per page
            return _replay_rows(games, display)

        _write(
            page,
            filtered,
            _aggregate(games),
            title,
            display,
            extra,
            annotate,
            index_href=_index_href(page),
        )

    # The navigation index sits at the output-dir root; hrefs are relative to it, so the
    # whole dir can move as a unit.
    def _href(target: Path) -> str:
        return relpath(target, args.out).replace("\\", "/")

    links = {agg.faction: _href(factions_dir / f"{_slug(agg.faction)}.html") for agg in combined}
    index = render_index_html(
        corpus,
        combined,
        links,
        title=args.title,
        combined_href=_href(args.out / "aggregate.html"),
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
        translate=display,
    )
    index_path.write_text("\n".join(index), encoding="utf-8")
    print(f"wrote {index_path.relative_to(REPO)}")

    print(f"done: index + 1 combined + {len(labels)} per-faction pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
