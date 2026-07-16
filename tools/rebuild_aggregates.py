"""Rebuild Edain replay-corpora's aggregate HTML pages.

A corpus is a subfolder of `downloads/replays/` (e.g. `edain-4.8.4.3`); pass one or more
folder names as positional arguments and each is built in turn. Corpora of different mods
require a different game version installed at C:\\BFME2 / C:\\RotWK, and every corpus in one
run resolves against the same install (loaded once and shared), so only build folders together
when they share the installed game version (e.g. edain-4.8.4.3 and loriencup, both Edain).
Each corpus's pages land under its own folder name inside the output dir (`aggregate/` by
default), which is the shared ROOT all corpora build into:

    aggregate/
      index.html                       global index over every corpus built here (this
                                        script also regenerates it every run, scanning disk)
      <folder>/                        one corpus, e.g. edain-4.8.4.3/
        index.html                     navigation index (corpus tiles, leaderboard, matrix)
        aggregate.html                 the combined report over every faction
        corpus.json                    summary metadata read back by the global index
        factions/<slug>.html           one page per faction, filtered to just that faction
        <mode>/                        the same tree over one player count (1v1/ 2v2/ 3v3/ 4v4/)
          index.html                   its own index, cross-linked to the corpus and siblings
          aggregate.html               combined report over that mode
          factions/<slug>.html         one page per faction within that mode

Within a corpus, the overall index is the whole corpus plus a nav row to each per-count index
(and an "All corpora" pill back up to the global index); each per-count index links on to that
count's per-faction pages. The player-count splits mirror the corpus layout: the replays live
in `<corpus>/<mode>/` subfolders, one per player count.

A corpus is resolved against the live BFME2 + RotWK/Edain installs. This mirrors `sage-edain
replay-aggregate --html` with Edain's knowledge injected (economy/library research rows,
CP-purchase depth, Dwarves split into their realm, Men split into Gondor/Arnor/Belfalas by the
map's Gondor roster, Imladris's Lichtbringer element toggles nested under the Loremaster, and
the Mordor summons / Leuchtfeuer signal-fire casts that field permanent units counted as
ordinary recruits) and `--matchups` on.

Most corpora are one mod version, resolved against that version installed at the `--game` roots
in a single pass. A tournament played across two Edain releases is instead one corpus whose
replays span two patches, and recordings from different patches do not simulate identically, so
each patch must be parsed under its own installed game version. Such a corpus carries a
hand-maintained `versions.json` beside its replays (so the label map travels with the corpus): the
first run over a multi-patch corpus generates it with one blank entry per patch fingerprint and
stops, reporting each fingerprint's replay count and a couple of example filenames so you can fill
every entry with its version name (e.g. "Edain 4.8.5"). A rerun then makes one pass per version,
prompting you to switch the install(s) at the `--game` roots to that version before each pass
(just press Enter when the first version is already installed), and pools every pass into the one
aggregate tree - pooling across patches is the whole point of a tournament corpus. Each version's
mounted ini tree is cached separately under the system temp dir (`sage_mount/<root>@<version>`), so
switching a root back on a later rerun is a free cache hit and no pass poisons another's mount. A
single-version corpus needs neither versions.json nor a prompt and rebuilds exactly as before.

Each game's winner comes from a `<replay>.BfME2Replay.json` sidecar (see `sage_replay.sidecar`).
Before anything is loaded - and before any version-switch prompt - this script writes a stub
sidecar beside every replay that lacks one (filled from the header: players, factions, teams,
map, length), then stops and lists every sidecar that still records no winner. Set `IsWinner` on
the winning team in each and rerun; once all winners are in, the build proceeds. So a
hand-collected off-ladder tournament (whose winner lives only in the match's name) gets its
sidecars built up front rather than falling back to the point-of-view guess, which is meaningless
here anyway - the recording player is often a caster/observer.

The build is two explicit phases over the translated-document cache (`sage_replay.translated`
via `sage_replay.cache`), a tree at `--cache-root` (default `downloads/cached/`) mirroring the
corpus root's folder structure - `downloads/replays/<corpus>/<mode>/x.BfME2Replay` caches to
`downloads/cached/<corpus>/<mode>/x.BfME2Replay.json`. Phase one caches: every replay lacking
a trusted document is translated - ids resolved against whichever game version is mounted for
its patch - and its document written into the mirror; a version group whose replays are all
already cached loads no install and prompts no version switch. Phase two aggregates: every
document under the corpus's mirror folder is rehydrated against the currently mounted install
and run through the load-time pipeline, so a freshly translated replay and a years-old document
flow through one path. All analysis lives at load time - KindOf bucketing, the faction/power
overlay, and the winner: since the sidecar is hand-edited, reading a document re-resolves the
outcome against whatever sidecar sits beside its replay *now*, falling back only to the
concession heuristic. Documents are tied to their replays by content hash, not mtime, so replay
and cache trees copied between machines rebuild there without the game versions that produced
them. Pass `--no-cache` to re-translate every replay even when its document looks fine - after
an id-space change, or when one is suspected stale (the rewritten documents are still what the
aggregate reads).

Code names (faction names and every pick-table entry) are shown through a hand-maintained
localisation file: a `{code name: display string}` map. Each corpus picks its file through the
`settings.json` beside its replays - a single `"names"` key whose path resolves relative to the
corpus folder (an absolute path passes through) - and the files live under `downloads/names/`,
one per mod: hand translations carry over between corpora of the same mod, whose code names
recur release to release (edain-4.8.4.3 and loriencup share edain_names.json), but not across
mods, whose code names diverge. `--names` overrides the settings.json for one run. Each
rebuild adds any code name it renders that the file is missing, with an empty string to fill
in by hand. A filled entry renders as `display string (code name)` - the raw code name stays
visible in brackets - while an empty (or absent) one falls back to the bare code name, so
pages always render. The corpus folder name itself is one of those code names: fill in its
entry to give the whole corpus a custom display name, used for its page titles (next rebuild)
and its row on the global index (any regeneration, see --index-only).

After building the corpus tree, the script writes `<out>/<folder>/corpus.json` (summary
counts the global index reads) and regenerates `<out>/index.html`: a landing page listing every
corpus folder found on disk under `<out>/` (each one this script has ever built), pulling its
headline numbers from its own corpus.json when present.

Run from anywhere:  python tools/rebuild_aggregates.py edain-4.8.4.3 [loriencup ...]
Override the paths with --corpus-root / --game / --out if your installs live elsewhere;
--names bypasses the corpus's settings.json for one run, and --title overrides the
folder-derived default corpus title. `--index-only` regenerates just the global index from
what is already on disk - no folder argument, no names file and no game install needed; each
corpus's display name resolves through its own names file (its corpus.json `"name"` when that
fails), so a corpus renamed in its names file shows up without a full rebuild.
`--no-cache` re-translates every replay even when its cached document looks fine - use it after
a stats-pipeline change too small to warrant bumping `FORMAT_VERSION`, or when a document is
simply suspected stale; `--cache-root` moves the whole document tree.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from datetime import datetime
from html import escape
from os.path import relpath
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))  # allow running this file directly, not just as a module

from sage_edain.replay import (  # noqa: E402
    FACTION_ICONS,
    ICONS_DIR,
    IGNORED_RECRUITS,
    TRACKED_PURCHASES,
    TRACKED_UPGRADES,
    edain_faction_refiner,
    edain_power_recruits,
    edain_upgrade_recruits,
)
from sage_replay.aggregate import (  # noqa: E402
    _HTML_STYLE,
    Corpus,
    _absorb,
    aggregate,
    command_point_weights,
    patch_groups,
    render_aggregate_html,
    render_index_html,
    version_groups,
    version_labels,
)
from sage_replay.cache import (  # noqa: E402
    cache_path,
    cached_document,
    load_replay_cache,
    write_replay_cache,
)
from sage_replay.narrate import GameData  # noqa: E402
from sage_replay.replay import find_replays, parse_replay_from_path  # noqa: E402
from sage_replay.sidecar import ensure_sidecars, sidecar_path  # noqa: E402
from sage_utils.clock import clock  # noqa: E402
from sage_utils.gameroot import resolve_game_root, resolve_game_roots  # noqa: E402

DEFAULT_CORPUS_ROOT = REPO / "downloads" / "replays"
DEFAULT_CACHE_ROOT = REPO / "downloads" / "cached"
DEFAULT_GAME = [Path(r"C:\BFME2"), Path(r"C:\RotWK")]
DEFAULT_OUT = REPO / "aggregate"

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


def _rel(path: Path) -> Path:
    """`path` repo-relative for printing, or as-is when it lives outside the repo
    (`--out`/`--names` pointed somewhere else)."""
    try:
        return path.relative_to(REPO)
    except ValueError:
        return path


_SETTINGS_SHAPE = (
    'expected {"names": "../../names/<mod>_names.json", "edain": true|false, '
    '"factions": {"<code>": "<display>", ...}}'
)


def _load_settings(corpus_dir: Path) -> dict:
    """The corpus's `settings.json` beside its replays, as a dict. Read as utf-8-sig, not
    utf-8: the file is hand-edited, and a Windows editor (or a PowerShell redirect) that saves
    a UTF-8 BOM must not crash the build. Raises ValueError - naming the file and the shape it
    should carry - when it is missing, unreadable, invalid JSON, or not a JSON object."""
    settings_path = corpus_dir / "settings.json"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    except OSError as error:
        raise ValueError(f"cannot read {settings_path} ({error}); {_SETTINGS_SHAPE}") from error
    except ValueError as error:
        raise ValueError(f"invalid JSON in {settings_path} ({error}); {_SETTINGS_SHAPE}") from error
    if not isinstance(settings, dict):
        raise ValueError(f"{settings_path} is not a JSON object; {_SETTINGS_SHAPE}")
    return settings


def _resolve_names_path(corpus_dir: Path) -> Path:
    """The names file the corpus at `corpus_dir` uses: the single `"names"` key of the
    `settings.json` beside its replays, resolved against the corpus folder when relative (an
    absolute path is used as-is), so a corpus and its names file move together. Raises
    ValueError - naming the settings.json and the shape it should carry - when the file is
    missing, unreadable, invalid JSON, or lacks the key."""
    settings = _load_settings(corpus_dir)
    value = settings.get("names")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'no "names" key in {corpus_dir / "settings.json"}; {_SETTINGS_SHAPE}')
    path = Path(value)
    return path if path.is_absolute() else (corpus_dir / path).resolve()


def _faction_relabeler(mapping: dict[str, str]):
    """A generic `FactionRefiner` for a non-Edain corpus: relabel a raw faction code name to
    the display name the corpus's `settings.json` `factions` map gives it, so the aggregation
    key is the shown faction name (a code the map doesn't list passes through unchanged). Unlike
    Edain's refiner it reads no stats/map/game - a vanilla faction is fixed at the lobby pick."""

    def refine(label: str, stats, data, map_file) -> str:
        return mapping.get(label, label)

    return refine


def _drop_excluded(corpus: Corpus, exclude: frozenset[str]) -> int:
    """Drop every player-game in `corpus` whose faction is in `exclude` - a corpus's
    `settings.json` `exclude` list of aggregation labels that aren't real playable factions (a
    neutral/observer `FactionCivilian` slot) - and scrub those labels from the surviving games'
    opponent lists (so an excluded faction never appears as a faction row, page, or matchup
    column), returning how many games were dropped. Applied to the games loaded from the cache,
    so excluding a faction needs no re-translation. `corpus.replays` is left as-is: a replay that
    parsed is still a replay that parsed, exactly as an unresolved-faction drop leaves it."""
    if not exclude:
        return 0
    kept = []
    dropped = 0
    for game in corpus.games:
        if game.faction in exclude:
            dropped += 1
            continue
        if any(opponent in exclude for opponent in game.opponents):
            game.opponents = tuple(o for o in game.opponents if o not in exclude)
        kept.append(game)
    corpus.games = kept
    return dropped


def _copy_icons(dest: Path, faction_icons: dict[str, str]) -> int:
    """Copy the faction emblems (`sage_edain/icons/*.webp`) named in `faction_icons` into the
    site at `dest`, returning how many landed. They live once per corpus, beside its indexes, so
    a corpus stays a movable, self-relative unit; a missing source file is skipped so a partial
    icon set still builds. A non-Edain corpus ships no emblems (`faction_icons` empty), so
    nothing is copied."""
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name in sorted(set(faction_icons.values())):
        src = ICONS_DIR / name
        if src.is_file():
            shutil.copy2(src, dest / name)
            copied += 1
    return copied


def _icon_urls(page_dir: Path, icons_dir: Path, faction_icons: dict[str, str]):
    """A `FactionIcon` for a page living in `page_dir`: a faction label -> its emblem's URL
    relative to that page (`""` when the faction ships no icon), so the same shared `icons_dir`
    is addressed correctly from the corpus root, a mode split, or a `factions/` subfolder. With
    an empty `faction_icons` (a non-Edain corpus) every label resolves to no icon."""
    prefix = relpath(icons_dir, page_dir).replace("\\", "/")

    def icon(label: str) -> str:
        name = faction_icons.get(label)
        return f"{prefix}/{name}" if name else ""

    return icon


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
            # The standard-outpost milestone is named by the unpacked base (dunedain_outpost);
            # surface that base as its own code name so it can be hand-translated.
            if agg.outpost is not None and agg.outpost.label:
                labels.add(agg.outpost.label)
            walk(agg.matchups.values())

    walk(factions)
    return labels


def _load_names(
    path: Path, labels: set[str], defaults: dict[str, str] | None = None
) -> tuple[dict[str, str], int]:
    """Load the localisation map, adding a blank entry for any rendered code name it is
    missing, and rewrite it (sorted) so new names surface for hand-translation. Returns the
    map and how many entries were newly added. `defaults` seeds a missing or still-blank
    entry's display string from the game's own data (an upgrade's localized DisplayName);
    a hand-filled value always wins over it."""
    names: dict[str, str] = {}
    if path.exists():
        # utf-8-sig, not utf-8: the map is hand-edited, so a Windows editor or PowerShell
        # redirect that saved a UTF-8 BOM must not crash the build (rewritten below without one).
        names = json.loads(path.read_text(encoding="utf-8-sig"))
    before = len(names)
    changed = False
    for label in labels:
        seeded = (defaults or {}).get(label, "")
        if label not in names:
            names[label] = seeded
            changed = True
        elif not names[label] and seeded:
            names[label] = seeded
            changed = True
    if changed or not path.exists():
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
    icon=None,
    weight=None,
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
            icon=icon,
            weight=weight,
        )
    )
    path.write_text(html, encoding="utf-8")
    print(f"wrote {_rel(path)}  ({len(factions)} faction(s))")


_ROSTER_ATTRS = ("buildings", "units", "heroes")


def _faction_own_side(agg, side_of) -> str | None:
    """The faction's own roster Side: the effective Side most of its unit/building/hero picks
    carry (weighted by games). Robust to the odd cross-faction pick, and needs no faction/Side
    table - it reads the faction back off what it actually fields. `side_of` is a label -> Side
    lookup (the paired game's `effective_side`; see `main`'s `side_of`)."""
    counts: Counter[str] = Counter()
    for attribute in _ROSTER_ATTRS:
        for label, choice in getattr(agg, attribute).items():
            side = side_of(label)
            if side:
                counts[side] += choice.games
    return counts.most_common(1)[0][0] if counts else None


def _side_annotator(combined, side_of):
    """A `render_aggregate_html` annotator that badges a pick whose unit Side is a *different*
    faction's than the one whose page it is on - the tell-tale of a disconnected ally's roster
    built from their inherited base (see the corpus's rare 3v3 late-game takeovers). Side is
    not identity, so the pick is kept and flagged rather than dropped. `side_of` is the paired
    game's `effective_side` label -> Side lookup (see `main`'s `side_of`)."""
    own_side = {agg.faction: _faction_own_side(agg, side_of) for agg in combined}
    faction_sides = {side for side in own_side.values() if side}

    def annotate(owner: str, label: str) -> str:
        side = side_of(label)
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
        # id="replays" so the single-faction page's contents box (render_aggregate_html) links here.
        f'<h3 id="replays">Replays ({len(ordered)})</h3>',
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
            f'<td class="dim">{clock(game.duration)}</td>'
            f'<td class="rep">{escape(game.replay)}</td></tr>'
        )
    lines.extend(["</tbody>", "</table></div>"])
    return lines


# The player-count splits, in display order. Each is a `<corpus>/<mode>/` subfolder of
# replays and a mirroring `<out>/<folder>/<mode>/` subtree of pages.
MODES = ("1v1", "2v2", "3v3", "4v4")


def _partition_by_mode(files: Iterable[Path], corpus_dir: Path) -> dict[str, list[Path]]:
    """Split a version's replay files into the mode subtree each sits under - keyed by the mode
    folder that begins its path relative to `corpus_dir` - with a root-level or off-mode replay
    falling into the flat "" bucket that only feeds the overall tree. A file lands under exactly
    one key, so collecting the buckets parses nothing twice."""
    buckets: dict[str, list[Path]] = {}
    for path in files:
        try:
            parts = path.relative_to(corpus_dir).parts
        except ValueError:
            parts = ()
        mode = parts[0] if len(parts) > 1 and parts[0] in MODES else ""
        buckets.setdefault(mode, []).append(path)
    return buckets


def _merge_corpora(corpora: Iterable[Corpus]) -> Corpus:
    """Pool several collected corpora into one - concatenating their player-games, summing their
    replay counts, and gathering their warnings - so the per-mode partitions fold into the overall
    tree without reading a single document twice."""
    merged = Corpus()
    for sub in corpora:
        merged.games.extend(sub.games)
        merged.replays += sub.replays
        merged.warnings.extend(sub.warnings)
    return merged


def _unparseable(files: list[Path], groups: dict[str, list[Path]]) -> list[str]:
    """The replays `find_replays` returned that no patch group claimed. `patch_groups` skips any
    file it cannot header-parse, and the version passes feed `collect` explicit per-group file
    lists, so such a file would otherwise vanish without a trace. Reparse each to recover the same
    `<name>: <error>` warning `collect` raises for a broken replay, so it both prints here and
    reaches the built pages' warning list."""
    claimed = {path for paths in groups.values() for path in paths}
    warnings: list[str] = []
    for path in files:
        if path in claimed:
            continue
        try:
            parse_replay_from_path(path)
            warnings.append(f"{path.name}: unreadable replay header")
        except Exception as error:  # noqa: BLE001 - mirror collect's parse-failure warning
            warnings.append(f"{path.name}: {error}")
    return warnings


def _available_corpora(root: Path) -> list[str]:
    """The corpus folder names present under `root` (a non-existent root has none)."""
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def _corpora_on_disk(out: Path) -> list[tuple[str, dict | None]]:
    """Every corpus this script has built under `out`, sorted by folder name: a subfolder
    counts as built once it carries an index.html. Each entry pairs the folder name with its
    corpus.json metadata (None when a build hasn't reached writing one yet, or predates this
    script version), so the global index can still show a bare link row for it."""
    entries: list[tuple[str, dict | None]] = []
    if not out.is_dir():
        return entries
    for sub in sorted(out.iterdir(), key=lambda p: p.name):
        if not sub.is_dir() or not (sub / "index.html").is_file():
            continue
        meta_path = sub / "corpus.json"
        meta = None
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = None
        entries.append((sub.name, meta))
    return entries


def _corpus_row(folder: str, meta: dict | None, display_names: dict[str, str]) -> str:
    """One `<tr>` of the global index's corpus table: the corpus.json headline numbers when
    `meta` is given, else a bare link row (a folder built by an older script version, or one
    still mid-build). The link text is the folder name through `display_names` (each folder's
    display name, resolved by the caller through that corpus's own names file) - the usual
    `display string (code name)` when a name is known, the bare folder otherwise - so renaming
    a corpus in its names file takes effect on the next index regeneration without rebuilding
    the corpus itself."""
    href = f"{folder}/index.html"
    name = display_names.get(folder)
    label = escape(f"{name} ({folder})" if name else folder)
    if meta is None:
        cells = '<td class="dim">-</td>' * 6
        return f'<tr><td><a href="{escape(href)}">{label}</a></td>{cells}</tr>'
    modes = ", ".join(meta.get("modes") or []) or "&mdash;"
    return (
        f'<tr><td><a href="{escape(href)}">{label}</a></td>'
        f"<td>{meta.get('replays', '-')}</td>"
        f"<td>{meta.get('player_games', '-')}</td>"
        f"<td>{meta.get('decided_games', '-')}</td>"
        f"<td>{meta.get('factions', '-')}</td>"
        f'<td class="dim">{escape(modes)}</td>'
        f'<td class="dim">{escape(str(meta.get("generated") or "-"))}</td></tr>'
    )


def render_corpora_index(out: Path, display_names: dict[str, str]) -> str:
    """The global landing page over every corpus built under `out` (one run of this script per
    corpus folder): a stat tile for how many are present and a table row per corpus linking to
    its own index.html, pulling headline numbers from its corpus.json and its label from
    `display_names` (folder -> display name, resolved per corpus by the caller). Rendered here
    rather than in `sage_replay.aggregate` - the corpora list is this script's concern (it scans
    disk for what earlier runs left behind), not the aggregation library's - but it reuses the
    library's stylesheet so the page matches the corpus pages it links to."""
    entries = _corpora_on_disk(out)
    lines = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Replay corpora</title>",
        f"<style>{_HTML_STYLE}</style>",
        "</head>",
        "<body><main>",
        "<h1>Replay corpora</h1>",
        '<p class="meta">Every replay corpus built under this output folder.</p>',
        '<div class="tiles"><div class="tile"><div class="k">Corpora</div>'
        f'<div class="v">{len(entries)}</div></div></div>',
    ]
    if not entries:
        lines.append(
            '<p class="meta">No corpus has been built here yet - run this script with a '
            "corpus folder name (e.g. edain-4.8.4.3) to build one.</p>"
        )
    else:
        lines.extend(
            [
                '<div class="tablewrap"><table>',
                "<thead><tr><th>Corpus</th><th>Replays</th><th>Player-games</th>"
                "<th>Decided</th><th>Factions</th><th>Modes</th>"
                "<th>Generated</th></tr></thead>",
                "<tbody>",
                *[_corpus_row(folder, meta, display_names) for folder, meta in entries],
                "</tbody>",
                "</table></div>",
            ]
        )
    lines.extend(["</main>", "</body>", "</html>"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "folders",
        nargs="*",
        metavar="folder",
        help="corpus subfolder(s) under --corpus-root to build, in order (e.g. edain-4.8.4.3 "
        "loriencup); folders built together must share the installed game version",
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=DEFAULT_CORPUS_ROOT,
        help="directory of corpus subfolders, one per mod version (default: downloads/replays)",
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=DEFAULT_CACHE_ROOT,
        help="root of the translated-document tree mirroring --corpus-root's folder structure "
        "(default: downloads/cached); the aggregate is built from what lands here",
    )
    parser.add_argument(
        "--game",
        type=Path,
        action="append",
        default=None,
        help="game root (repeatable, base first); defaults to C:\\BFME2 then C:\\RotWK",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output root for all corpora")
    parser.add_argument(
        "--title",
        default=None,
        help="page title / corpus label (default: derived from folder); single folder only",
    )
    parser.add_argument(
        "--names",
        type=Path,
        default=None,
        help="localisation map (code name -> display string); overrides the one the corpus's "
        "settings.json points at",
    )
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="only regenerate the global index from what is on disk (no folder, no game load)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="re-translate every replay from the installs even when a trusted cached document "
        "exists (the rewritten documents are still what the aggregate is built from)",
    )
    args = parser.parse_args(argv)

    def _display_names() -> dict[str, str]:
        """Each built corpus folder's display name for the global index: the folder's entry in
        its own corpus's names file (resolved through --corpus-root/<folder>/settings.json, so
        filling the entry and rerunning with --index-only renames the row). A blank or absent
        entry keeps the bare folder name, like any untranslated code name; only when the names
        file itself cannot be resolved - a corpus whose replay folder is gone - does the "name"
        its corpus.json recorded label the row instead."""
        display: dict[str, str] = {}
        for folder, meta in _corpora_on_disk(args.out):
            try:
                names_file = _resolve_names_path(args.corpus_root / folder)
                loaded = json.loads(names_file.read_text(encoding="utf-8-sig"))
                name = loaded.get(folder) if isinstance(loaded, dict) else None
            except (OSError, ValueError):
                name = (meta or {}).get("name")
            if name:
                display[folder] = str(name)
        return display

    def _write_global_index() -> None:
        args.out.mkdir(parents=True, exist_ok=True)
        global_index = args.out / "index.html"
        global_index.write_text(render_corpora_index(args.out, _display_names()), encoding="utf-8")
        print(f"wrote {_rel(global_index)}")

    # A names-file edit (e.g. giving a corpus folder its display name) shows up on the global
    # index without rebuilding any corpus - regenerating it is a pure disk scan.
    if args.index_only:
        _write_global_index()
        return 0

    available = _available_corpora(args.corpus_root)
    if not args.folders:
        parser.error(
            "at least one corpus folder is required; available under "
            f"{args.corpus_root}: {', '.join(available) or '(none)'}"
        )
    missing = [folder for folder in args.folders if not (args.corpus_root / folder).is_dir()]
    if missing:
        parser.error(
            f"no corpus folder(s) {', '.join(missing)} under {args.corpus_root}; "
            f"available: {', '.join(available) or '(none)'}"
        )
    if args.title is not None and len(args.folders) > 1:
        parser.error("--title names a single corpus; drop it when building several folders")

    # One paired game for the whole run, resolved once against the currently mounted install
    # and memoized: every corpus's translate pass and phase two share it (so the game is never
    # mounted twice), which is why the folders built together must share the installed game
    # version - per the corpus workflow, the current mount is assumed to carry every
    # document's names, whatever recording patch each one holds.
    game_roots = args.game or DEFAULT_GAME
    current: list[GameData | None] = [None]

    def current_game() -> GameData:
        if current[0] is None:
            print(f"loading game from {', '.join(str(g) for g in game_roots)} ...")
            current[0] = GameData.from_root(resolve_game_roots(game_roots, None), localize=False)
        return current[0]

    needs_input = []
    for folder in args.folders:
        if _build_corpus(parser, args, folder, game_roots, current_game):
            needs_input.append(folder)

    # The global index is a pure disk scan (no game data needed), so it's cheap to regenerate
    # in full once at the end - the corpora just built plus every sibling a previous run left.
    _write_global_index()

    if needs_input:
        print(f"not built (fill in the reported items and rerun): {', '.join(needs_input)}")
        return 1
    return 0


def _build_corpus(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    folder: str,
    game_roots: list[Path],
    current_game: Callable[[], GameData],
) -> int:
    """Build the one corpus at `--corpus-root/<folder>` into `--out/<folder>`: the whole
    single-corpus flow - sidecars, phase-one caching, phase-two aggregation, page tree.
    Returns 1 without building when the corpus stops for hand-input (sidecar winners, blank
    version labels); a malformed settings.json is still a usage error through `parser`.
    `current_game` is the run-wide memoized game load every corpus's phase two shares."""
    print(f"building {folder} ...")
    corpus_dir = args.corpus_root / folder
    out_root = args.out / folder
    cache_dir = args.cache_root / folder

    # The corpus's localisation map: --names when given, else the file its settings.json
    # points at (a settings problem is a usage error - the message says what shape to add).
    if args.names is not None:
        names_path = args.names
    else:
        try:
            names_path = _resolve_names_path(corpus_dir)
        except ValueError as error:
            parser.error(str(error))
    print(f"names file: {_rel(names_path)}")

    # The corpus's overlay, from its settings.json: `edain` true injects Edain's faction refiner,
    # fielding-power recruits, ignored recruit, and tracked upgrade/purchase tables (and its
    # shipped emblems); false is a generic corpus that only relabels raw faction code names to
    # the display names in the `factions` map (see `_faction_relabeler`) and tracks nothing
    # Edain-specific. --names overrides the names file but not the overlay - that is a property
    # of the corpus, not the run.
    try:
        settings = _load_settings(corpus_dir)
    except ValueError as error:
        parser.error(str(error))
    edain = bool(settings.get("edain", False))
    faction_map = settings.get("factions") or {}
    if not isinstance(faction_map, dict):
        parser.error(f'"factions" in {corpus_dir / "settings.json"} must be a code -> name object')
    # Aggregation labels to drop entirely - slots that aren't real playable factions (a
    # neutral/observer FactionCivilian). Matched against the label a game aggregates under, so an
    # entry is a raw code unless the `factions` map relabels it. Applied after the cache load
    # (see `_drop_excluded`), so excluding one needs no re-translation.
    exclude = settings.get("exclude") or []
    if not isinstance(exclude, list) or not all(isinstance(item, str) for item in exclude):
        parser.error(f'"exclude" in {corpus_dir / "settings.json"} must be a list of labels')
    exclude = frozenset(exclude)
    # Upgrade code names (raw) never to give an Upgrades row. A `Type = PLAYER` upgrade is
    # auto-tracked via `data.player_upgrades`, but a mod can implement a client option that
    # way (2.02's CE-graphics toggle) - purchase noise, not a strategic pick.
    ignore_upgrades = settings.get("ignore_upgrades") or []
    if not isinstance(ignore_upgrades, list) or not all(
        isinstance(item, str) for item in ignore_upgrades
    ):
        parser.error(
            f'"ignore_upgrades" in {corpus_dir / "settings.json"} must be a list of '
            "upgrade code names"
        )
    ignore_upgrades = frozenset(ignore_upgrades)
    if edain:
        refine_faction = edain_faction_refiner
        power_recruits = edain_power_recruits
        upgrade_recruits = edain_upgrade_recruits
        ignore_recruits = IGNORED_RECRUITS
        tracked_upgrades = TRACKED_UPGRADES
        tracked_purchases = TRACKED_PURCHASES
        faction_icons = FACTION_ICONS
        print(
            "overlay: Edain (refiner, power/upgrade recruits, tracked upgrades/purchases, emblems)"
        )
    else:
        refine_faction = _faction_relabeler(faction_map)
        power_recruits = None
        upgrade_recruits = None
        ignore_recruits = frozenset()
        tracked_upgrades = frozenset()
        tracked_purchases = frozenset()
        faction_icons = {}
        print(f"overlay: generic ({len(faction_map)} faction name(s), no Edain-specific tracking)")

    def _cache_file(replay_path: Path) -> Path:
        """The replay's document in the mirrored cache tree: `<cache root>/<same relative
        path>/<replay name>.json` (relative to the corpus *root*, so the corpus folder itself
        is mirrored too)."""
        return cache_path(replay_path, args.corpus_root, args.cache_root)

    def _ensure_version_cached(files, load_game) -> tuple[int, int, int, list[str]]:
        """The explicit caching step for one game version's replay files: every replay lacking
        a trusted document in the mirrored cache tree (all of them under `--no-cache`) is
        translated under `load_game()`'s mounted install - only versions with something to
        translate ever prompt for an install switch - and its document written. Translation is
        the whole step: ids resolve to code names now, while every analysis and outcome decision
        waits for phase two, so a fresh parse and a cache hit flow through the same load-time
        path. Returns (already cached, newly translated, failed to translate, warnings) - the
        warnings are only the parse failures, since anything document-related resurfaces when
        the documents are read back."""
        misses = [
            path
            for path in files
            if args.no_cache or cached_document(path, _cache_file(path)) is None
        ]
        if not misses:
            return len(files), 0, 0, []

        data = load_game()
        translated = 0
        warnings: list[str] = []
        for path in misses:
            try:
                replay = parse_replay_from_path(path)
            except Exception as error:  # noqa: BLE001 - any parse failure becomes a warning
                warnings.append(f"{path.name}: {error}")
                continue
            write_replay_cache(path, replay, data, cache_file=_cache_file(path))
            translated += 1
        already = len(files) - len(misses)
        return already, translated, len(misses) - translated, warnings

    def _load_cached_corpora(data: GameData) -> tuple[dict[str, Corpus], list[str]]:
        """Build the corpus from the cache tree: every document under the corpus's mirror
        folder, whatever wrote it, rehydrated against the paired `data` and run through the
        load-time pipeline with the corpus's overlay hooks, its outcome re-resolved against the
        sidecar beside its replay. The mirror maps each document back to its replay path, so the
        mode partition follows the same subfolder rule as the replay tree. A document whose
        replay is gone or changed loads as nothing and is reported - recache (or delete the
        orphan) to clear it. Returns the per-mode corpora (the flat "" bucket for a root-level
        replay) and those warnings."""
        by_replay: dict[Path, Path] = {}
        if cache_dir.is_dir():
            for cache_file in sorted(cache_dir.rglob("*.json")):
                relative = cache_file.relative_to(cache_dir)
                by_replay[corpus_dir / relative.with_suffix("")] = cache_file
        corpora: dict[str, Corpus] = {}
        warnings: list[str] = []
        for mode, replay_paths in _partition_by_mode(by_replay, corpus_dir).items():
            corpus = corpora.setdefault(mode, Corpus())
            for replay_path in replay_paths:
                # The corpus is uploaded winners' replays, so decide otherwise-undetermined
                # games in favour of the recording player's team (assume_pov_won).
                games = load_replay_cache(
                    replay_path,
                    by_replay[replay_path],
                    data,
                    assume_pov_won=True,
                    refine_faction=refine_faction,
                    relabel_power=None,
                    power_recruits=power_recruits,
                    upgrade_recruits=upgrade_recruits,
                    ignore_recruits=ignore_recruits,
                )
                if games is None:
                    warnings.append(
                        f"{by_replay[replay_path].name}: stale or orphaned cached document "
                        "(its replay is missing or changed) - recache or delete it"
                    )
                    continue
                corpus.replays += 1
                _absorb(corpus, replay_path.name, games)
        return corpora, warnings

    # Group the corpus's replays by recording patch before any game loads - a header-only read.
    # One fingerprint is the ordinary single-version corpus; several mean a tournament played
    # across mod patches, each of which must parse under its own installed game version (see the
    # module docstring's multi-patch workflow). Any file find_replays returned that no group
    # claimed failed even a header parse; surface it here, since the per-group file lists fed to
    # collect below would otherwise drop it silently.
    print(f"scanning replays under {corpus_dir} ...")
    all_replays = find_replays([corpus_dir])

    # The winner comes from each replay's sidecar (see sage_replay.sidecar); a hand-collected
    # (off-ladder) tournament corpus arrives with none. Write a stub beside every replay that
    # lacks one - filled from the header, with the winner left for a human - and stop for the
    # winners to be filled in, all before any game install is loaded or a version switch is
    # asked for. A corpus whose sidecars all already name a winner sails straight through.
    sidecars = ensure_sidecars(all_replays)
    if sidecars.generated:
        print(f"  generated {len(sidecars.generated)} missing sidecar(s) from replay headers")
    for path, error in sidecars.failed:
        print(f"  warning: could not generate a sidecar for {path.name}: {error}")
    if sidecars.needs_winner:
        print(
            f"{len(sidecars.needs_winner)} replay(s) have no recorded winner yet - set "
            '"IsWinner": true for each player on the winning team in these sidecars, then rerun:'
        )
        for path in sorted(sidecars.needs_winner, key=lambda p: p.name):
            print(f"  {sidecar_path(path).name}")
        return 1

    groups = patch_groups(all_replays)
    unparseable = _unparseable(all_replays, groups)
    for warning in unparseable:
        print(f"  warning: {warning}")

    # Phase one: the explicit caching step. Every replay gets a translated document in the
    # mirrored cache tree, and a game install is loaded only for versions that still have
    # something to translate. Phase two below builds the whole aggregate from the cache tree
    # alone, so a freshly translated replay and an already-cached one flow through one path.
    version_counts: dict[str, int] = {}
    cache_warnings: list[str] = []
    multi_version = len(groups) > 1

    def _report(files, already: int, translated: int, failed: int, note: str) -> str:
        cached = f"{already} already cached, {translated} newly translated"
        failures = f", {failed} failed to translate" if failed else ""
        skip = note if already == len(files) else ""
        return f"{len(files)} replay(s): {cached}{failures}{skip}"

    if multi_version:
        labels = version_labels(corpus_dir / "versions.json", groups)
        blank = [fingerprint for fingerprint in groups if not labels.get(fingerprint)]
        if blank:
            versions_path = _rel(corpus_dir / "versions.json")
            print(
                f"this corpus spans {len(groups)} game patches - label each in {versions_path} "
                "before it can be built:"
            )
            for fingerprint in sorted(groups):
                paths = groups[fingerprint]
                examples = ", ".join(p.name for p in paths[:3])
                mark = "" if labels.get(fingerprint) else "   <- fill in"
                print(
                    f"  {fingerprint}: {len(paths)} replay(s) "
                    f'[{examples}] = "{labels.get(fingerprint, "")}"{mark}'
                )
            print(
                'fill each blank label with its version name (e.g. "Edain 4.8.5"), then rerun to '
                "build the pooled corpus."
            )
            return 1

        roots = ", ".join(str(root) for root in game_roots)
        for label, files in version_groups(groups, labels).items():

            def load_game(label=label):
                input(f'switch the game install(s) at {roots} to "{label}", then press Enter ... ')
                # A per-version mount cache keeps each patch's mounted ini tree apart, so passes
                # never poison one another and switching a root back on a rerun is a free cache
                # hit. The singular resolve_game_root per root avoids the shared-cache collision
                # the plural resolve_game_roots would cause by pointing every root at one cache dir.
                slug = _slug(label)
                mount = Path(tempfile.gettempdir()) / "sage_mount"
                roots_resolved = tuple(
                    resolve_game_root(root, mount / f"{Path(root).name}@{slug}")
                    for root in game_roots
                )
                print(f'loading "{label}" game from {roots} ...')
                return GameData.from_root(roots_resolved, localize=False)

            already, translated, failed, version_warnings = _ensure_version_cached(files, load_game)
            cache_warnings.extend(version_warnings)
            # Count replays with a document (a trusted document was a successful parse by
            # construction) - a replay that fails to translate becomes a warning, not a count.
            version_counts[label] = already + translated
            print(
                f"  {label}: "
                + _report(files, already, translated, failed, " - no install switch needed")
            )
    else:
        files = next(iter(groups.values())) if groups else []
        already, translated, failed, version_warnings = _ensure_version_cached(files, current_game)
        cache_warnings.extend(version_warnings)
        if files:
            print("  " + _report(files, already, translated, failed, " (no game install needed)"))

    # Phase two: the aggregate is built from the cache tree, every document under the corpus's
    # mirror folder rehydrated against the currently mounted install and run through the
    # load-time pipeline, its outcome re-resolved against the sidecars as they are now.
    # `side_of` is the paired game's `effective_side`, what `_build_tree`'s `_side_annotator`
    # uses to look up unit Sides for the advisory cross-faction badge.
    data = current_game()
    side_of = data.effective_side
    # The Units timelines' CP-share weights: pick label -> the template's CommandPoints,
    # resolved against the currently mounted install like everything else in phase two.
    weight = command_point_weights(data)
    # Player-level upgrade researches (`Type = PLAYER` - armory tech, a clan pick) always earn
    # Upgrades rows; the overlay's hand-tracked set extends them, and the corpus's
    # `ignore_upgrades` drop the ones that are really client options.
    tracked_upgrades = (tracked_upgrades | data.player_upgrades) - ignore_upgrades
    corpora, stale_warnings = _load_cached_corpora(data)
    cache_warnings.extend(stale_warnings)
    # Drop excluded slots (a neutral FactionCivilian) from every mode partition before the
    # overall corpus pools them, so they never surface as a faction row, page, or matchup column.
    if exclude:
        excluded = sum(_drop_excluded(sub, exclude) for sub in corpora.values())
        print(f"excluded {excluded} player-game(s): {', '.join(sorted(exclude))}")

    # Each present player count is its own mode subtree; the overall corpus pools every
    # partition (all modes plus any flat root-level replays), so no document is read twice. A
    # flat corpus with no split subfolders collapses to just the overall tree.
    print(f"collected corpus from {_rel(cache_dir)}:")
    mode_corpora: dict[str, Corpus] = {}
    for mode in MODES:
        sub = corpora.get(mode)
        if sub is not None and sub.replays:
            mode_corpora[mode] = sub
            print(f"  {mode}: {sub.replays} replays -> {len(sub.games)} player-games")
    corpus = _merge_corpora(corpora.values())
    print(f"  overall: {corpus.replays} replays -> {len(corpus.games)} player-games")
    # The caching step's parse failures and any stale/orphaned documents join the documents'
    # own warnings (an unresolved faction) in the pooled stream.
    corpus.warnings.extend(cache_warnings)
    for warning in corpus.warnings:
        print(f"  warning: {warning}")
    # The unparseable replays are already printed above; add them to the pooled corpus so the
    # built index pages list them in their warning stream alongside the rest.
    corpus.warnings.extend(unparseable)

    def _aggregate(games):
        return aggregate(
            games,
            tracked_upgrades=tracked_upgrades,
            tracked_purchases=tracked_purchases,
            matchups=True,
        )

    # Grow the hand-maintained localisation map with any newly-rendered code name, then resolve
    # each to its display string (blank/absent -> the raw code name). The per-mode splits are
    # subsets of the overall corpus, so the overall aggregate already carries every label.
    combined = _aggregate(corpus.games)
    # The names file translates pick labels (buildings/units/...). A non-Edain corpus already
    # names its factions through the settings `factions` map, so those display names are the
    # aggregation labels themselves and don't belong in the names file - drop every faction label
    # (each aggregate's own, plus every matchup enemy) so it isn't re-added there as a blank.
    labels = _collect_labels(combined)
    if not edain:
        faction_labels = {agg.faction for agg in combined}
        faction_labels |= {enemy for agg in combined for enemy in agg.matchups}
        labels -= faction_labels
    # The corpus folder name is itself a translatable code name (its blank entry surfaces here
    # like any pick label), so the whole corpus can be given a display name by hand. Tracked
    # upgrade rows seed their display string from the upgrade's own DisplayName, so they never
    # need hand-translation (a hand-filled entry still wins).
    names, added = _load_names(names_path, labels | {folder}, data.upgrade_displaynames)
    untranslated = sum(1 for value in names.values() if not value)
    print(
        f"names: {len(names)} keys ({added} new, {untranslated} untranslated) -> {_rel(names_path)}"
    )

    # The corpus title: --title wins, then the folder's filled-in display name, then a
    # readable default derived from the folder name itself.
    corpus_name = names.get(folder) or folder.replace("-", " ").title()
    title = args.title or f"{corpus_name} replay corpus"

    def display(code: str) -> str:
        # A translated entry shows its display string with the raw code name in brackets
        # ("Hall of the King's Men (AngmarBarracks)"); a blank/absent one is just the code name.
        name = names.get(code)
        return f"{name} ({code})" if name else code

    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    present = list(mode_corpora)

    def _nav(current: str | None) -> list[tuple[str, str]]:
        """The index nav pills for the tree at `current` (a mode, or None for the corpus's own
        overall tree): a leading pill back up to the global corpora index (one level up from
        the corpus root, two from inside a mode split), then the overall index plus every
        present split, hrefs relative to `current`'s own folder, the current entry left inert
        (empty href)."""
        row: list[tuple[str, str]] = [
            ("All corpora", "../index.html" if current is None else "../../index.html")
        ]
        for label, target in [("Overall", None), *((m, m) for m in present)]:
            if target == current:
                row.append((label, ""))
            elif current is None:  # at <out>/ pointing down into a mode
                row.append((label, f"{target}/index.html"))
            elif target is None:  # from a mode back up to the overall index
                row.append((label, "../index.html"))
            else:  # between two modes
                row.append((label, f"../{target}/index.html"))
        return row

    def _build_tree(out: Path, tree: Corpus, title: str, nav: list[tuple[str, str]]) -> None:
        """Write one aggregate tree under `out`: the combined report, one page per faction
        (each with its replay list), and the navigation index carrying `nav`."""
        tree_combined = _aggregate(tree.games)
        # Badge any pick whose unit Side is a different faction's than the page it sits on - a
        # disconnected ally's roster the surviving teammate built from the inherited base.
        annotate = _side_annotator(tree_combined, side_of)

        factions_dir = out / "factions"
        factions_dir.mkdir(parents=True, exist_ok=True)
        for stale in factions_dir.glob("*.html"):  # a faction that dropped out keeps no page
            stale.unlink()
        index_path = out / "index.html"

        # The faction emblems live once at `icons_dir` (the corpus root); each page addresses
        # them relative to its own depth - the tree root and index, and a level deeper for the
        # per-faction pages under factions/.
        root_icon = _icon_urls(out, icons_dir, faction_icons)
        faction_icon = _icon_urls(factions_dir, icons_dir, faction_icons)

        def _index_href(page: Path) -> str:
            """This tree's index, relative to `page`'s own folder, so the tree can move as a
            unit (`index.html` from the tree root, `../index.html` from factions/)."""
            return relpath(index_path, page.parent).replace("\\", "/")

        combined_page = out / "aggregate.html"
        _write(
            combined_page,
            tree,
            tree_combined,
            title,
            display,
            annotate=annotate,
            index_href=_index_href(combined_page),
            icon=root_icon,
            weight=weight,
        )

        # One page per faction label, filtered to just that faction's player-games, with its
        # replay list appended via the `extra` hook (the combined page omits the lists).
        games_by_faction: dict[str, list] = defaultdict(list)
        for game in tree.games:
            games_by_faction[game.faction].append(game)

        for label in sorted(games_by_faction):
            games = games_by_faction[label]
            filtered = type(tree)(games=games, replays=tree.replays, warnings=tree.warnings)
            page = factions_dir / f"{_slug(label)}.html"

            def extra(agg, games=games):  # noqa: B008 - the faction's replay list, per page
                return _replay_rows(games, display)

            _write(
                page,
                filtered,
                _aggregate(games),
                f"{display(label)} - {title}",
                display,
                extra,
                annotate,
                index_href=_index_href(page),
                icon=faction_icon,
                weight=weight,
            )

        # The index sits at the tree root; its hrefs are relative to it, so the tree can move
        # as a unit (`aggregate.html` and `factions/<slug>.html` beside/below it).
        links = {agg.faction: f"factions/{_slug(agg.faction)}.html" for agg in tree_combined}
        index = render_index_html(
            tree,
            tree_combined,
            links,
            title=title,
            combined_href="aggregate.html",
            generated=generated,
            translate=display,
            nav=nav,
            icon=root_icon,
        )
        index_path.write_text("\n".join(index), encoding="utf-8")
        print(f"wrote {_rel(index_path)}")

    # The faction emblems, copied once into the corpus root; every page in the tree (and its
    # mode splits) links them from here, relative to its own depth (see `_icon_urls`).
    icons_dir = out_root / "icons"
    print(f"copied {_copy_icons(icons_dir, faction_icons)} faction icon(s) -> {_rel(icons_dir)}")

    # The overall tree at this corpus's own output root (everything, plus the nav to each
    # split and back up to the global corpora index), then one mirroring subtree per present
    # player count.
    _build_tree(out_root, corpus, title, _nav(None))
    for mode, sub in mode_corpora.items():
        _build_tree(out_root / mode, sub, f"{title} - {mode}", _nav(mode))

    # Summary metadata the global index reads back without needing to load any game data -
    # it only ever scans what earlier runs of this script left on disk.
    decided = sum(1 for g in corpus.games if g.outcome != "undetermined")
    corpus_meta = {
        "folder": folder,
        # The bare display name (no "replay corpus" suffix): the global index's label for this
        # folder when its corpus's names file cannot be resolved at regeneration time.
        "name": corpus_name,
        "title": title,
        "replays": corpus.replays,
        "player_games": len(corpus.games),
        "decided_games": decided,
        "factions": len(combined),
        "modes": list(mode_corpora),
        "generated": generated,
    }
    # A tournament corpus pooled several game versions; record each version's replay count so the
    # global index can show which patches it spans (a single-version corpus carries no such key).
    if multi_version:
        corpus_meta["versions"] = version_counts
    (out_root / "corpus.json").write_text(
        json.dumps(corpus_meta, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {_rel(out_root / 'corpus.json')}")

    print(f"done: {folder} - overall tree + {len(mode_corpora)} player-count split(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
