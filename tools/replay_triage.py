"""A game-free integrity sweep over a tournament replay corpus.

`sage_replay.aggregate` trusts every replay's sidecar (or, failing that, the concession
heuristic) equally; one wrong hand-filled winner, or a sidecar copied beside the wrong
replay, silently poisons the whole corpus aggregate. This tool finds those problems before
aggregation runs, using only the replay header, its order stream, and its sidecar - no game
root, so it works standalone against a downloaded corpus.

Each replay is scored against a fixed set of checks (parse health, duration, slot shape,
patch fingerprint, sidecar presence/consistency, sidecar-vs-replay name agreement, and
whether the sidecar's stated winner agrees with the session-end heuristic and did not
themselves leave early) and collects zero or more flags. The text report groups flags per
replay and ranks a worst-first summary table; `--json` emits the same data for scripting.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))  # allow running this file directly, not just as a module

from sage_replay.replay import (  # noqa: E402
    ReplayFile,
    ReplaySlot,
    ReplaySlotType,
    find_replays,
    parse_replay_from_path,
)
from sage_replay.sidecar import sidecar_path  # noqa: E402
from sage_replay.winner import infer_winner  # noqa: E402
from sage_utils.cli import utf8_stdout  # noqa: E402
from sage_utils.clock import clock, hms  # noqa: E402

# Below this many seconds a "game" is more likely a lobby abort or connection test than a
# real match; above it, likely a stalled/AFK recording rather than a genuinely long game.
_SHORT_GAME_SECONDS = 180.0
_LONG_GAME_SECONDS = 7200.0

# A winner who departed more than this fraction of the recording's frames before it ended
# is strong evidence their IsWinner flag is inverted, not a graceful late-game exit.
_EARLY_DEPARTURE_FRACTION = 0.2

# Flag codes ranked most to least severe, for the worst-first summary sort. Codes not
# possible to reach (defensive) simply never appear; codes below all listed ones (there are
# none left over) would sort last via the dict's fallback in `_severity`.
_SEVERITY = (
    "parse-error",
    "winner-disagrees",
    "sidecar-name-mismatch",
    "winner-left-early",
    "sidecar-no-winner",
    "sidecar-invalid",
    "sidecar-missing",
    "crashed",
    "bad-shape",
    "short-game",
    "long-game",
    "unknown-fingerprint",
    "winner-undetermined",
)
_SEVERITY_RANK = {code: rank for rank, code in enumerate(_SEVERITY)}


@dataclass(slots=True)
class Flag:
    code: str
    detail: str


@dataclass(slots=True)
class ReplayReport:
    path: Path
    version_label: str = ""
    fingerprint: str | None = None
    duration_seconds: float | None = None
    competitor_count: int | None = None
    mode: str = ""
    flags: list[Flag] = field(default_factory=list)
    heuristic: dict[str, object] | None = None
    sidecar_winners: list[str] | None = None  # raw IsWinner=true names, or None if unreadable

    @property
    def name(self) -> str:
        return self.path.name

    def add(self, code: str, detail: str) -> None:
        self.flags.append(Flag(code, detail))


def _mode_label(competitors: list[ReplaySlot]) -> str:
    """A `2v2`-style shape label from the competitors' lobby teams, or `""` when the shape
    isn't a clean team split (an FFA, or a team assignment missing)."""
    teams = [c.team for c in competitors]
    if not teams or any(t < 0 for t in teams):
        return ""
    sizes = sorted((teams.count(t) for t in set(teams)), reverse=True)
    return "v".join(str(n) for n in sizes) if len(sizes) >= 2 else str(sizes[0])


def _competitors(replay: ReplayFile) -> list[ReplaySlot]:
    return [
        slot
        for slot in replay.header.metadata.players
        if slot.slot_type is ReplaySlotType.Human and slot.human_name and not slot.is_observer
    ]


def _check_shape(report: ReplayReport, replay: ReplayFile) -> list[ReplaySlot]:
    competitors = _competitors(replay)
    report.competitor_count = len(competitors)
    report.mode = _mode_label(competitors)
    if len(competitors) != 4 or any(c.team < 0 for c in competitors):
        report.add(
            "bad-shape",
            f"{len(competitors)} competitors, mode={report.mode or 'irregular'}",
        )
    return competitors


def _check_duration(report: ReplayReport, replay: ReplayFile) -> None:
    duration = replay.header.num_timecodes * replay.seconds_per_frame
    report.duration_seconds = duration
    if duration < _SHORT_GAME_SECONDS:
        report.add("short-game", f"duration {clock(duration)} (< {clock(_SHORT_GAME_SECONDS)})")
    elif duration > _LONG_GAME_SECONDS:
        report.add("long-game", f"duration {hms(duration)} (> {hms(_LONG_GAME_SECONDS)})")


def _check_crash(report: ReplayReport, replay: ReplayFile) -> None:
    if replay.crashed or replay.header.abnormal_end_frame is not None:
        report.add("crashed", f"abnormal end at frame {replay.header.abnormal_end_frame}")


def _check_fingerprint(
    report: ReplayReport, replay: ReplayFile, versions: dict[str, str] | None
) -> None:
    report.fingerprint = replay.header.patch_fingerprint
    if versions is None:
        return
    label = versions.get(report.fingerprint)
    report.version_label = label or ""
    if report.fingerprint not in versions:
        report.add("unknown-fingerprint", f"fingerprint {report.fingerprint} not in versions.json")


def _load_sidecar(path: Path) -> dict | None | str:
    """The sidecar JSON beside `path`, `None` if there is none, or the error string if it
    exists but fails to parse."""
    sc = sidecar_path(path)
    if not sc.is_file():
        return None
    try:
        # utf-8-sig, not utf-8: a sidecar re-saved by a Windows editor may carry a BOM.
        return json.loads(sc.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        return str(error)


def _check_sidecar(
    report: ReplayReport, replay: ReplayFile, competitors: list[ReplaySlot], path: Path
) -> None:
    data = _load_sidecar(path)
    if data is None:
        report.add("sidecar-missing", "no sidecar file beside replay")
        return
    if isinstance(data, str):
        report.add("sidecar-invalid", data)
        return

    players = [p for p in (data.get("Players") or []) if not p.get("IsObserver")]
    winners = [p.get("DisplayName") for p in players if p.get("IsWinner")]
    won_teams = {p.get("Team") for p in players if p.get("IsWinner")}
    lost_teams = {p.get("Team") for p in players if not p.get("IsWinner")}

    if not won_teams:
        report.add(
            "sidecar-no-winner", "no non-observer player flagged IsWinner (stub not filled in)"
        )
    elif won_teams & lost_teams:
        overlap = sorted(str(t) for t in (won_teams & lost_teams))
        report.add(
            "sidecar-no-winner",
            f"team(s) {', '.join(overlap)} contain both IsWinner=true and IsWinner=false players",
        )
    else:
        report.sidecar_winners = sorted(winners)

    sidecar_names = {p.get("DisplayName") for p in players}
    # `_competitors` already filters to slots carrying a name; the inline check just narrows
    # the type for mypy so `sorted()` below doesn't have to handle `None`.
    replay_names = {c.human_name for c in competitors if c.human_name is not None}
    if sidecar_names != replay_names:
        report.add(
            "sidecar-name-mismatch",
            f"sidecar names {sorted(sidecar_names)} != "
            f"replay competitor names {sorted(replay_names)}",
        )


def _check_winner(report: ReplayReport, replay: ReplayFile) -> None:
    verdict = infer_winner(replay)
    report.heuristic = {
        "outcome": verdict.outcome,
        "reason": verdict.reason,
        "winner": verdict.winner,
        "winner_names": list(verdict.winner_names),
        "confidence": verdict.confidence,
        "recorder": verdict.recorder,
    }

    if verdict.outcome == "decided" and report.sidecar_winners:
        heuristic_names = sorted(verdict.winner_names)
        if heuristic_names != report.sidecar_winners:
            report.add(
                "winner-disagrees",
                f"sidecar says {report.sidecar_winners} won, heuristic says {heuristic_names} won "
                f"({verdict.reason}; confidence={verdict.confidence})",
            )
    elif verdict.outcome != "decided":
        report.add("winner-undetermined", verdict.reason)

    if not report.sidecar_winners or not replay.chunks:
        return
    end = replay.chunks[-1].timecode
    for name in report.sidecar_winners:
        session = next((s for s in verdict.sessions if s.name == name), None)
        if session is None:
            continue
        # An explicit leave right at the end is just the normal quit-to-menu once the match
        # is decided; only a departure well before the recording ended indicts the flag.
        departed = session.departed_at(end)
        if session.left_at is not None:
            departed = session.left_at if departed is None else min(departed, session.left_at)
        if departed is None or (end - departed) <= _EARLY_DEPARTURE_FRACTION * end:
            continue
        seconds = departed * replay.seconds_per_frame
        reason = "left the game" if session.left_at is not None else "session went silent"
        report.add(
            "winner-left-early",
            f"sidecar winner {name!r} {reason} at frame {departed} (~{clock(seconds)}), "
            f"{clock((end - departed) * replay.seconds_per_frame)} before the recording ended",
        )


def triage_replay(path: Path, versions: dict[str, str] | None) -> ReplayReport:
    report = ReplayReport(path=path)
    try:
        replay = parse_replay_from_path(path)
    except Exception as error:  # noqa: BLE001 - any parse failure is itself the finding
        report.add("parse-error", str(error))
        return report

    _check_crash(report, replay)
    _check_duration(report, replay)
    competitors = _check_shape(report, replay)
    _check_fingerprint(report, replay, versions)
    _check_sidecar(report, replay, competitors, path)
    _check_winner(report, replay)
    return report


def _severity(report: ReplayReport) -> int:
    if not report.flags:
        return len(_SEVERITY)
    return min(_SEVERITY_RANK.get(f.code, len(_SEVERITY)) for f in report.flags)


def _default_versions_path(paths: list[Path]) -> Path | None:
    """`<corpus root>/versions.json` when one of the given paths is (or is inside) a
    directory carrying it directly - checked non-recursively, since the corpus root is
    passed as one of the CLI arguments, not discovered by searching upward."""
    for raw in paths:
        base = raw if raw.is_dir() else raw.parent
        candidate = base / "versions.json"
        if candidate.is_file():
            return candidate
    return None


def render_text(reports: list[ReplayReport], versions_path: Path | None) -> list[str]:
    lines: list[str] = []
    flagged = [r for r in reports if r.flags]
    clean = [r for r in reports if not r.flags]

    lines.append(f"Replay triage over {len(reports)} replays")
    lines.append(f"Versions file: {versions_path if versions_path else 'none'}")
    lines.append(f"{len(clean)} clean, {len(flagged)} flagged")
    lines.append("")

    ranked = sorted(reports, key=lambda r: (_severity(r), -len(r.flags), r.name))
    for report in ranked:
        if not report.flags:
            continue
        lines.append(f"== {report.name}")
        for f in report.flags:
            lines.append(f"  {f.code}: {f.detail}")
        lines.append("")

    lines.append("Summary (worst first):")
    name_width = max((len(r.name) for r in reports), default=4)
    version_width = max((len(r.version_label) for r in reports), default=7)
    header = (
        f"  {'name':{name_width}s}  {'version':{version_width}s}  {'dur':>7s}  "
        f"{'#flags':>6s}  codes"
    )
    lines.append(header)
    for report in ranked:
        duration = clock(report.duration_seconds) if report.duration_seconds is not None else "?"
        codes = ",".join(f.code for f in report.flags) if report.flags else "-"
        lines.append(
            f"  {report.name:{name_width}s}  {report.version_label:{version_width}s}  "
            f"{duration:>7s}  {len(report.flags):>6d}  {codes}"
        )
    return lines


def _to_json(reports: list[ReplayReport], versions_path: Path | None) -> dict:
    return {
        "versions_file": str(versions_path) if versions_path else None,
        "total": len(reports),
        "clean": sum(1 for r in reports if not r.flags),
        "flagged": sum(1 for r in reports if r.flags),
        "replays": [
            {
                "path": str(r.path),
                "name": r.name,
                "version_label": r.version_label,
                "fingerprint": r.fingerprint,
                "duration_seconds": r.duration_seconds,
                "competitor_count": r.competitor_count,
                "mode": r.mode,
                "flags": [{"code": f.code, "detail": f.detail} for f in r.flags],
                "heuristic": r.heuristic,
                "sidecar_winners": r.sidecar_winners,
            }
            for r in sorted(reports, key=lambda r: (_severity(r), -len(r.flags), r.name))
        ],
    }


def main() -> int:
    utf8_stdout()
    parser = argparse.ArgumentParser(
        description="Game-free integrity sweep over a tournament replay corpus "
        "(header/order-stream/sidecar only - no game install needed)."
    )
    parser.add_argument("paths", nargs="+", type=Path, help="replay files or corpus directories")
    parser.add_argument(
        "--json", action="store_true", help="emit a machine-readable JSON dump instead of text"
    )
    parser.add_argument(
        "--versions",
        type=Path,
        default=None,
        help="fingerprint -> patch label map (default: <corpus root>/versions.json when present)",
    )
    args = parser.parse_args()

    versions_path = args.versions or _default_versions_path(args.paths)
    versions: dict[str, str] | None = None
    if versions_path is not None and versions_path.is_file():
        # utf-8-sig: the file is hand-edited and may carry a BOM from a Windows editor.
        versions = json.loads(versions_path.read_text(encoding="utf-8-sig"))

    replay_paths = find_replays(args.paths)
    if not replay_paths:
        print("no replay files found", file=sys.stderr)
        return 1

    reports = [triage_replay(path, versions) for path in replay_paths]

    if args.json:
        print(json.dumps(_to_json(reports, versions_path), ensure_ascii=False, indent=2))
    else:
        for line in render_text(reports, versions_path):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
