"""Publish a browsable repository of translated replays beside their originals.

A corpus already exists twice on disk: the recordings under `downloads/replays/` and their
translated documents under `downloads/cached/`. The aggregate pages read those documents but
never expose them, so a replay someone wants - to re-watch, to re-parse, to check a claim -
is not reachable from the published site. This builds the third tree, `build/replays/`, where
both copies of every replay are downloadable and the whole corpus is one filterable table.

Nothing here parses a replay. The table is read out of the documents (players, factions, map,
length, patch fingerprint, the recording's own sha256) and the ladder sidecars beside the
recordings (who won), so the site rebuilds from a corpus alone - no game install, no mount.

The two payload trees mirror the replay tree's own layout:

    build/replays/
      index.html                       the table, filtered in the browser
      files/<corpus>/<mode>/x.BfME2Replay        the recording, byte for byte
      docs/<corpus>/<mode>/x.BfME2Replay.json    its translated document

Payloads are hardlinked when the filesystem allows it, so republishing a 700 MB corpus costs
no disk; `--copy` forces real copies for a filesystem or a destination that cannot link.

Run from anywhere:  python tools/build_replay_site.py
`tools/rebuild_aggregates.py` calls `export_corpus` for each corpus it builds, so a rebuild
keeps this tree in step without a second command.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))  # allow running this file directly, not just as a module

from sage_utils import webtheme  # noqa: E402

__all__ = ["Replay", "collect", "export_corpus", "build"]

DEFAULT_REPLAY_ROOT = REPO / "downloads" / "replays"
DEFAULT_CACHE_ROOT = REPO / "downloads" / "cached"
DEFAULT_OUT = REPO / "build" / "replays"
REPLAY_SUFFIX = ".BfME2Replay"
MODE_FOLDER = re.compile(r"^\d+v\d+$", re.IGNORECASE)


def _read_json(path: Path) -> dict | None:
    """A hand-edited or generated JSON file, or None when it is missing or unreadable.

    `utf-8-sig` because the sidecars and settings are hand-edited, and a Windows editor
    saving a BOM must not take a corpus out of the site.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


class Replay:
    """One recording, its document and everything the table shows about it."""

    def __init__(
        self, path: Path, relative: Path, document: dict, sidecar: dict | None, corpus: str
    ) -> None:
        self.path = path
        self.relative = relative
        self.corpus = corpus
        self.document = document
        header = document.get("header") or {}
        self.sha256: str = document.get("sha256") or ""
        self.size: int = int(document.get("size") or path.stat().st_size)
        self.fingerprint: str = document.get("fingerprint") or ""
        self.map: str = Path(str(document.get("map") or "")).stem
        self.started: int | None = header.get("start_time")
        self.crashed: bool = bool(document.get("crashed"))
        frames = int(document.get("num_timecodes") or 0)
        self.seconds: float = frames * float(document.get("seconds_per_frame") or 0.0)
        self.players = self._players(document, sidecar)

    @staticmethod
    def _players(document: dict, sidecar: dict | None) -> list[dict]:
        """The competing slots, each with the faction it played and how it ended.

        The document knows who played what - including the faction a lobby Random rolled,
        which it read back from the player's own build orders - and the sidecar knows who
        won. A team flagged in the sidecar wins for everyone on it; with no sidecar the
        outcome stays unknown rather than guessed, since guessing is the aggregate's job.
        """
        won_teams: set[int] = set()
        seen_flag = False
        for entry in (sidecar or {}).get("Players") or []:
            if entry.get("IsObserver"):
                continue
            if entry.get("IsWinner"):
                won_teams.add(entry.get("Team"))
                seen_flag = True
        out = []
        for slot in document.get("players") or []:
            if slot.get("observer"):
                continue
            faction = slot.get("faction") or slot.get("inferred_faction") or ""
            team = slot.get("team")
            out.append(
                {
                    "name": slot.get("name") or ("AI" if slot.get("type") == "computer" else "?"),
                    "faction": faction,
                    "team": team if isinstance(team, int) else -1,
                    "won": (1 if team in won_teams else 0) if seen_flag else -1,
                    "ai": slot.get("type") == "computer",
                }
            )
        return out

    @property
    def mode(self) -> str:
        """`2v2` and the like: the folder when the corpus is filed by mode, else the shape
        of the teams that actually played."""
        for part in self.relative.parts[:-1]:
            if MODE_FOLDER.match(part):
                return part.lower()
        teams: dict[int, int] = {}
        for player in self.players:
            teams[player["team"]] = teams.get(player["team"], 0) + 1
        if not teams:
            return "?"
        return "v".join(str(n) for n in sorted(teams.values(), reverse=True))

    def row(self, corpus_label: str, patch: str, factions: dict[str, str]) -> dict:
        return {
            "p": self.relative.as_posix(),
            "c": self.corpus,
            "cl": corpus_label,
            "g": patch,
            "m": self.mode,
            "map": self.map,
            "d": self.started,
            "s": round(self.seconds),
            "sz": self.size,
            "h": self.sha256,
            "x": 1 if self.crashed else 0,
            "pl": [
                [
                    p["name"],
                    p["faction"],
                    factions.get(p["faction"], p["faction"]),
                    p["team"],
                    p["won"],
                    1 if p["ai"] else 0,
                ]
                for p in self.players
            ],
        }


def corpus_settings(corpus_dir: Path) -> tuple[str, dict[str, str]]:
    """A corpus's display name and its code-name map, from the same files the aggregate
    reads: `settings.json` points at a `names` file, whose entries relabel the corpus itself
    and every faction code name it renders."""
    settings = _read_json(corpus_dir / "settings.json") or {}
    names: dict[str, str] = {}
    pointer = settings.get("names")
    if isinstance(pointer, str):
        target = Path(pointer)
        resolved = target if target.is_absolute() else corpus_dir / target
        names = {k: v for k, v in (_read_json(resolved) or {}).items() if v}
    return names.get(corpus_dir.name) or corpus_dir.name, names


def patch_labels(corpus_dir: Path) -> dict[str, str]:
    """The corpus's hand-filled `versions.json`, mapping a patch fingerprint to its version
    name. Absent or blank entries leave the fingerprint to speak for itself."""
    return {k: v for k, v in (_read_json(corpus_dir / "versions.json") or {}).items() if v}


def collect(corpus_dir: Path, replay_root: Path, cache_root: Path) -> Iterator[Replay]:
    """Every recording in a corpus that has a document to go with it.

    A recording whose document is missing, unreadable or stale is skipped rather than listed
    without one: the table's whole point is that both halves are downloadable.
    """
    for path in sorted(corpus_dir.rglob("*" + REPLAY_SUFFIX)):
        if not path.is_file():
            continue
        relative = path.relative_to(replay_root)
        document = _read_json(cache_root / relative.parent / (path.name + ".json"))
        if not document or not document.get("sha256"):
            continue
        if int(document.get("size") or -1) != path.stat().st_size:
            continue  # the document describes a different file than the one on disk
        sidecar = _read_json(path.with_name(path.name + ".json"))
        yield Replay(path, relative, document, sidecar, corpus_dir.name)


def place(source: Path, target: Path, copy: bool) -> None:
    """Put `source` at `target`, by hardlink where that works and by copy where it does not.

    A replay corpus is hundreds of megabytes and never changes once recorded, so linking it
    into the published tree is free; a cross-device destination falls back on its own.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.stat().st_size == source.stat().st_size:
            return
        target.unlink()
    if not copy:
        try:
            os.link(source, target)
            return
        except OSError:
            pass
    shutil.copy2(source, target)


def export_corpus(
    corpus_dir: Path,
    out_dir: Path = DEFAULT_OUT,
    *,
    replay_root: Path = DEFAULT_REPLAY_ROOT,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    copy: bool = False,
) -> int:
    """Publish one corpus's recordings and documents, and rewrite the site index.

    The index is rebuilt over every corpus already published under `out_dir`, not just this
    one, so a rebuild of a single corpus never drops the others off the page.
    """
    label, names = corpus_settings(corpus_dir)
    labels = patch_labels(corpus_dir)
    rows = []
    for replay in collect(corpus_dir, replay_root, cache_root):
        place(replay.path, out_dir / "files" / replay.relative, copy)
        document = cache_root / replay.relative.parent / (replay.path.name + ".json")
        place(
            document, out_dir / "docs" / replay.relative.parent / (replay.path.name + ".json"), copy
        )
        rows.append(replay.row(label, labels.get(replay.fingerprint) or replay.fingerprint, names))
    write_manifest(out_dir, corpus_dir.name, label, rows)
    build(out_dir)
    return len(rows)


def write_manifest(out_dir: Path, corpus: str, label: str, rows: list[dict]) -> None:
    """One corpus's rows, kept as their own file so the next corpus's build reads them back
    instead of re-walking a tree it was not asked about."""
    path = out_dir / "manifests" / f"{corpus}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"corpus": corpus, "label": label, "rows": rows}, ensure_ascii=False),
        encoding="utf-8",
    )


def manifests(out_dir: Path) -> list[dict]:
    directory = out_dir / "manifests"
    if not directory.is_dir():
        return []
    found = [_read_json(path) for path in sorted(directory.glob("*.json"))]
    return [m for m in found if m and m.get("rows")]


def esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


def build(out_dir: Path) -> int:
    """Write the page and its data over every corpus published under `out_dir`."""
    published = manifests(out_dir)
    rows = [row for manifest in published for row in manifest["rows"]]
    data = {
        "corpora": [{"c": m["corpus"], "l": m["label"], "n": len(m["rows"])} for m in published],
        "rows": rows,
    }
    (out_dir / "assets").mkdir(parents=True, exist_ok=True)
    (out_dir / "assets" / "replays.js").write_text(
        "window.REPLAYS = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    (out_dir / "assets" / "site.css").write_text(CSS.lstrip(), encoding="utf-8")
    (out_dir / "assets" / "site.js").write_text(JS.lstrip(), encoding="utf-8")
    (out_dir / "index.html").write_text(page(len(rows), len(published)), encoding="utf-8")
    return len(rows)


def page(total: int, corpora: int) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Replays</title>
<link rel="stylesheet" href="assets/site.css">
</head>
<body>
<header>
  <h1>Replays</h1>
  <p class="sub">{total} recordings from {corpora} corpus{"" if corpora == 1 else "es"},
  each with the translated document it was parsed into. Both are downloadable; the checksum
  is the recording's own, as the document recorded it.</p>
</header>
<section class="filters">
  <label>Game <select id="f-corpus"><option value="">any</option></select></label>
  <label>Patch <select id="f-patch"><option value="">any</option></select></label>
  <label>Mode <select id="f-mode"><option value="">any</option></select></label>
  <label>Faction <select id="f-faction"><option value="">any</option></select></label>
  <label>Player <input id="f-player" type="search" placeholder="name" spellcheck="false"></label>
  <label>Search <input id="f-text" type="search" placeholder="map, file, checksum"
         spellcheck="false"></label>
  <button id="f-reset" type="button">Reset</button>
</section>
<p id="count" class="count"></p>
<table id="table">
<thead><tr>
  <th data-sort="d">Date</th>
  <th data-sort="cl">Game</th>
  <th data-sort="g">Patch</th>
  <th data-sort="m">Mode</th>
  <th data-sort="map">Map</th>
  <th>Players</th>
  <th data-sort="s">Length</th>
  <th data-sort="sz">Size</th>
  <th data-sort="h">Checksum</th>
  <th>Download</th>
</tr></thead>
<tbody></tbody>
</table>
<div class="more"><button id="more" type="button" hidden>Show more</button></div>
<footer>
  A recording is listed only when its translated document is present, so every row has both
  halves. The document carries the parse with every version-coupled id already resolved to a
  code name, which is what makes it readable without the game version that recorded it.
</footer>
<script src="assets/replays.js"></script>
<script src="assets/site.js"></script>
</body>
</html>
"""


# The browser spans every corpus and every faction at once, so the page itself stays on steel;
# the one faction-specific thing on it is the faction beside a player's name, which takes that
# faction's own trim colour (`webtheme.faction_accents`) rather than restyling the page.
CSS = (
    webtheme.site_tokens(webtheme.STEEL)
    + webtheme.faction_accents(".fac")
    + """
* { box-sizing: border-box; }
body {
  margin: 0; padding: 30px 26px 70px; background: var(--bg); color: var(--fg);
  font-family: var(--sans); font-size: 14.5px; line-height: 1.55;
}
header, .filters, .count, table, .more, footer { max-width: 1500px; margin-inline: auto; }
h1 { font-size: 26px; margin: 0 0 4px; letter-spacing: -.3px; }
.sub { color: var(--muted); margin: 0 0 20px; max-width: 80ch; font-size: 14px; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.filters { display: flex; flex-wrap: wrap; gap: 10px 16px; align-items: flex-end;
           padding-bottom: 14px; border-bottom: 1px solid var(--line); }
.filters label { display: flex; flex-direction: column; font-size: 11.5px;
                 text-transform: uppercase; letter-spacing: .5px; color: var(--muted); gap: 4px; }
.filters select, .filters input {
  border: 1px solid var(--line); border-radius: 7px; background: var(--bg); color: var(--fg);
  padding: 6px 9px; font-size: 13px; font-family: var(--sans); min-width: 150px;
}
.filters select:focus, .filters input:focus {
  outline: 2px solid var(--accent); border-color: transparent;
}
.filters button, .more button {
  border: 1px solid var(--line); border-radius: 7px; background: var(--panel); color: var(--fg);
  padding: 7px 14px; font-size: 13px; cursor: pointer;
}
.filters button:hover, .more button:hover { border-color: var(--accent); color: var(--accent); }
.count { color: var(--muted); font-size: 13px; margin: 12px 0 6px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--line);
         vertical-align: top; }
th { font-size: 11px; text-transform: uppercase; letter-spacing: .5px; color: var(--muted);
     position: sticky; top: 0; background: var(--bg); cursor: pointer; user-select: none; }
th[data-sort]:hover { color: var(--accent); }
tbody tr:hover { background: var(--panel); }
td.date, td.len, td.size { white-space: nowrap; font-family: var(--mono); font-size: 12px; }
td.map { max-width: 200px; }
.teams { display: flex; flex-wrap: wrap; gap: 4px 10px; }
.team { display: flex; gap: 6px; align-items: baseline; }
.team + .team::before { content: "vs"; color: var(--muted); font-size: 11px; margin-right: 4px; }
.player { white-space: nowrap; }
.player .fac { color: var(--muted); font-size: 11.5px; }
.player.won { color: var(--win); font-weight: 600; }
.player.lost { color: var(--loss); }
.player.ai::after { content: " (AI)"; color: var(--muted); font-size: 11px; }
td.hash code { font-family: var(--mono); font-size: 11.5px; cursor: copy; }
td.dl { white-space: nowrap; }
td.dl a { margin-right: 10px; font-size: 12.5px; }
.crashed { color: var(--loss); font-size: 11px; margin-left: 6px; }
.more { text-align: center; margin-top: 18px; }
footer { margin-top: 40px; padding-top: 14px; border-top: 1px solid var(--line);
         color: var(--muted); font-size: 12.5px; max-width: 90ch; }
@media (max-width: 900px) { td.map, th:nth-child(5) { display: none; } }
"""
)


# The faction -> skin map, baked in so the page resolves a label the same way the aggregate
# does: webtheme owns the spellings, and the JS normalises identically.
JS = (
    """
(function () {
  var FACTION_SKINS = """
    + json.dumps(webtheme.label_slugs(), sort_keys=True)
    + """;
  function normalise(name) {
    return String(name == null ? '' : name).toLowerCase().replace(/[^a-z0-9]/g, '');
  }
  var DATA = window.REPLAYS || { rows: [], corpora: [] };
  var rows = DATA.rows, page = 200, shown = page;
  var body = document.querySelector('#table tbody');
  var count = document.getElementById('count');
  var more = document.getElementById('more');
  var sortKey = 'd', sortDir = -1;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function options(select, values) {
    values.forEach(function (v) {
      var o = document.createElement('option');
      o.value = v[0];
      o.textContent = v[1];
      select.appendChild(o);
    });
  }

  // the filter lists are whatever the corpus actually contains, counted as we go
  var byCorpus = {}, byPatch = {}, byMode = {}, byFaction = {};
  rows.forEach(function (r) {
    byCorpus[r.c] = r.cl;
    byPatch[r.g] = (byPatch[r.g] || 0) + 1;
    byMode[r.m] = (byMode[r.m] || 0) + 1;
    r.pl.forEach(function (p) { if (p[1]) byFaction[p[1]] = p[2] || p[1]; });
  });
  options(document.getElementById('f-corpus'),
          Object.keys(byCorpus).sort().map(function (c) { return [c, byCorpus[c]]; }));
  options(document.getElementById('f-patch'),
          Object.keys(byPatch).sort().map(function (g) {
            return [g, g + ' (' + byPatch[g] + ')'];
          }));
  options(document.getElementById('f-mode'),
          Object.keys(byMode).sort().map(function (m) { return [m, m + ' (' + byMode[m] + ')']; }));
  options(document.getElementById('f-faction'),
          Object.keys(byFaction).sort(function (a, b) {
            return byFaction[a].localeCompare(byFaction[b]);
          }).map(function (f) { return [f, byFaction[f]]; }));

  function value(id) { return document.getElementById(id).value.trim().toLowerCase(); }

  function matches(r) {
    var corpus = value('f-corpus'), patch = value('f-patch'), mode = value('f-mode');
    var faction = value('f-faction'), player = value('f-player'), text = value('f-text');
    if (corpus && r.c.toLowerCase() !== corpus) return false;
    if (patch && r.g.toLowerCase() !== patch) return false;
    if (mode && r.m.toLowerCase() !== mode) return false;
    if (faction && !r.pl.some(function (p) { return (p[1] || '').toLowerCase() === faction; }))
      return false;
    if (player && !r.pl.some(function (p) {
      return (p[0] || '').toLowerCase().indexOf(player) >= 0;
    })) return false;
    if (text) {
      var hay = (r.map + ' ' + r.p + ' ' + r.h + ' ' + r.cl + ' ' + r.g).toLowerCase();
      if (hay.indexOf(text) < 0) return false;
    }
    return true;
  }

  function date(seconds) {
    if (!seconds) return '';
    var d = new Date(seconds * 1000);
    return d.toISOString().slice(0, 10);
  }

  function length(seconds) {
    // H:MM:SS, the same shape the aggregate pages use for a match length
    var total = Math.round(seconds), h = Math.floor(total / 3600);
    var m = Math.floor(total % 3600 / 60), s = total % 60;
    return h + ':' + (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
  }

  function size(bytes) {
    return bytes < 1024 * 1024 ? Math.round(bytes / 1024) + ' KB'
                               : (bytes / 1048576).toFixed(1) + ' MB';
  }

  function teams(r) {
    var wrap = el('div', 'teams'), grouped = {};
    r.pl.forEach(function (p) { (grouped[p[3]] = grouped[p[3]] || []).push(p); });
    Object.keys(grouped).sort().forEach(function (team) {
      var box = el('div', 'team');
      grouped[team].forEach(function (p) {
        var outcome = p[4] === 1 ? ' won' : p[4] === 0 ? ' lost' : '';
        var cls = 'player' + outcome + (p[5] ? ' ai' : '');
        var span = el('span', cls);
        span.appendChild(document.createTextNode(p[0]));
        if (p[2]) {
          var fac = el('span', 'fac', ' ' + p[2]);
          // the faction's own colour, keyed off the raw label so a corpus that renames it
          // in its display map still lands on the right skin
          var slug = FACTION_SKINS[normalise(p[1])] || FACTION_SKINS[normalise(p[2])];
          if (slug) fac.setAttribute('data-fac', slug);
          span.appendChild(fac);
        }
        box.appendChild(span);
      });
      wrap.appendChild(box);
    });
    return wrap;
  }

  function link(href, label, name) {
    var a = el('a', null, label);
    a.href = href.split('/').map(encodeURIComponent).join('/');
    a.setAttribute('download', name);
    return a;
  }

  function render() {
    var found = rows.filter(matches);
    found.sort(function (a, b) {
      var x = a[sortKey], y = b[sortKey];
      if (typeof x === 'string' || typeof y === 'string')
        return String(x || '').localeCompare(String(y || '')) * sortDir;
      return ((x || 0) - (y || 0)) * sortDir;
    });
    body.innerHTML = '';
    found.slice(0, shown).forEach(function (r) {
      var tr = document.createElement('tr');
      tr.appendChild(el('td', 'date', date(r.d)));
      tr.appendChild(el('td', null, r.cl));
      tr.appendChild(el('td', null, r.g));
      tr.appendChild(el('td', null, r.m));
      var map = el('td', 'map', r.map);
      if (r.x) map.appendChild(el('span', 'crashed', 'crashed'));
      tr.appendChild(map);
      var players = document.createElement('td');
      players.appendChild(teams(r));
      tr.appendChild(players);
      tr.appendChild(el('td', 'len', length(r.s)));
      tr.appendChild(el('td', 'size', size(r.sz)));
      var hash = el('td', 'hash');
      var code = el('code', null, (r.h || '').slice(0, 12));
      code.title = r.h + ' (click to copy)';
      code.addEventListener('click', function () {
        if (navigator.clipboard) navigator.clipboard.writeText(r.h);
        code.textContent = 'copied';
        setTimeout(function () { code.textContent = (r.h || '').slice(0, 12); }, 1000);
      });
      hash.appendChild(code);
      tr.appendChild(hash);
      var name = r.p.split('/').pop();
      var dl = el('td', 'dl');
      dl.appendChild(link('files/' + r.p, 'replay', name));
      dl.appendChild(link('docs/' + r.p + '.json', 'translated', name + '.json'));
      tr.appendChild(dl);
      body.appendChild(tr);
    });
    count.textContent = found.length === rows.length
      ? found.length + ' replays'
      : found.length + ' of ' + rows.length + ' replays';
    more.hidden = found.length <= shown;
    more.textContent = 'Show more (' + (found.length - shown) + ' left)';
  }

  ['f-corpus', 'f-patch', 'f-mode', 'f-faction', 'f-player', 'f-text'].forEach(function (id) {
    var node = document.getElementById(id);
    node.addEventListener('input', function () { shown = page; render(); });
    node.addEventListener('change', function () { shown = page; render(); });
  });
  document.getElementById('f-reset').addEventListener('click', function () {
    ['f-corpus', 'f-patch', 'f-mode', 'f-faction', 'f-player', 'f-text'].forEach(function (id) {
      document.getElementById(id).value = '';
    });
    shown = page;
    render();
  });
  more.addEventListener('click', function () { shown += page; render(); });
  document.querySelectorAll('th[data-sort]').forEach(function (th) {
    th.addEventListener('click', function () {
      var key = th.getAttribute('data-sort');
      sortDir = key === sortKey ? -sortDir : (key === 'd' ? -1 : 1);
      sortKey = key;
      render();
    });
  });
  render();
})();
"""
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("corpus", nargs="*", help="corpus folder names (default: every one found)")
    ap.add_argument("--replay-root", type=Path, default=DEFAULT_REPLAY_ROOT)
    ap.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--copy", action="store_true", help="copy the payloads instead of hardlinking them"
    )
    ap.add_argument(
        "--index-only",
        action="store_true",
        help="rebuild the page from the manifests already published",
    )
    args = ap.parse_args(argv)

    if args.index_only:
        print(f"wrote {args.out / 'index.html'}: {build(args.out)} replays")
        return 0

    folders: Iterable[Path]
    if args.corpus:
        folders = [args.replay_root / name for name in args.corpus]
    else:
        folders = sorted(p for p in args.replay_root.iterdir() if p.is_dir())
    total = 0
    for folder in folders:
        if not folder.is_dir():
            print(f"no such corpus: {folder}", file=sys.stderr)
            return 1
        published = export_corpus(
            folder,
            args.out,
            replay_root=args.replay_root,
            cache_root=args.cache_root,
            copy=args.copy,
        )
        total += published
        print(f"{folder.name}: {published} replay(s) published")
    print(
        f"wrote {args.out / 'index.html'}: {total} replay(s) over {len(list(folders))} corpus(es)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
