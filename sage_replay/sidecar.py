"""Read a replay's match outcome from its ladder metadata sidecar.

A replay downloaded from the ladder carries a `<replay>.json` sidecar beside it - the
ladder's own record of the game. Unlike the order stream, that record names the winner
outright: each entry in its `Players` array carries a `Team`, an `IsWinner` flag, and an
`IsObserver` flag. Where `winner.py` can only *infer* an outcome from concession signals
(and often gives up with `undetermined`), the sidecar states it - and `sage_replay.aggregate`
prefers it, falling back to the heuristic only when no trustworthy sidecar sits beside the
replay.

The winner in the sidecar is a *team* fact: every player on the winning team is flagged, so
`sidecar_team_outcomes` maps it onto the replay's human slots by their own lobby team - robust
to a slot the replay itself can't resolve (a lobby Random pick records faction -1, but its
team is still recorded).

`sidecar_outcomes` is deliberately strict: it declines (returns None, so the heuristic
stands) unless the sidecar plainly corresponds to the replay - a stale sidecar, or even one
describing a different game, is trusted only when:

- there is at least one flagged winner, and no team is both a winner and a loser;
- every human slot in the replay is teamed (team >= 0), so it can be placed by team at all;
- every human slot's team appears among the sidecar's teams, so a sidecar for a differently
  shaped game is refused rather than mapped by coincidence.

The sidecar's fields are the ladder's schema, not the mod's, so this stays engine-generic.

A hand-collected corpus (a tournament played off the ladder) has no sidecars at all, and the
winner lives only in the match's name and the caster's memory. `ensure_sidecars` crawls such a
corpus and writes a stub sidecar beside every replay that lacks one, filled in from what the
replay header already knows (players, factions, teams, map, length) with `IsWinner` left false
for a human to set. It reports which sidecars still have no winner so the caller can fill them
in before doing any expensive work.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sage_replay.replay import ReplayFile, ReplaySlotType, parse_replay_from_path
from sage_utils.clock import hms

__all__ = [
    "SidecarReport",
    "build_sidecar_stub",
    "ensure_sidecars",
    "sidecar_has_winner",
    "sidecar_outcomes",
    "sidecar_path",
    "sidecar_team_outcomes",
]


def sidecar_path(replay_path: Path) -> Path:
    """The metadata sidecar beside a replay: `<replay>.BfME2Replay.json`."""
    return replay_path.with_name(replay_path.name + ".json")


def sidecar_team_outcomes(
    replay_path: Path, players: Sequence[tuple[str, int]]
) -> dict[str, str] | None:
    """Each name's outcome ("won"/"lost") from the sidecar beside `replay_path`, mapped by the
    `(human name, lobby team)` pairs in `players`. `sidecar_outcomes` extracts those pairs from
    a freshly parsed replay's human slots; `cache.load_replay_cache` instead reuses the pairs a
    cached parse recorded, so re-reading a cache re-derives the outcome from whatever the
    sidecar says *now* rather than what it said when the cache was written. Declines (returns
    None, so the caller's heuristic stands) unless the sidecar plainly matches - see the module
    docstring's trust checks, applied here verbatim: at least one flagged winner with no team on
    both sides, `players` non-empty, and every given team non-negative and present among the
    sidecar's own teams."""
    path = sidecar_path(replay_path)
    if not path.is_file():
        return None
    try:
        # utf-8-sig, not utf-8: a sidecar re-saved by a Windows editor may carry a BOM.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None

    sidecar_players = [p for p in (data.get("Players") or []) if not p.get("IsObserver")]
    if not sidecar_players:
        return None
    won_teams: set = set()
    lost_teams: set = set()
    for player in sidecar_players:
        (won_teams if player.get("IsWinner") else lost_teams).add(player.get("Team"))
    # A real result flags at least one winner, and no team straddles both sides.
    if not won_teams or (won_teams & lost_teams):
        return None

    sidecar_teams = won_teams | lost_teams
    # Every given player must be teamed and match one of the sidecar's teams; otherwise the
    # sidecar can't be mapped onto this replay (an unteamed FFA slot, or a sidecar for another
    # game).
    if not players or any(team < 0 or team not in sidecar_teams for _, team in players):
        return None
    return {name: ("won" if team in won_teams else "lost") for name, team in players}


def sidecar_outcomes(replay: ReplayFile, replay_path: Path) -> dict[str, str] | None:
    """Each human slot's outcome ("won"/"lost") from the replay's ladder sidecar, or None when
    no sidecar sits beside `replay_path` or it doesn't trustworthily describe `replay` (see the
    module docstring's checks). Keyed by human name, exactly as `aggregate._outcomes` is, so it
    drops straight into `player_games` in place of the heuristic verdict. A thin wrapper over
    `sidecar_team_outcomes`: it just extracts the `(name, lobby team)` pairs from the replay's
    human, non-observer slots."""
    humans = [
        (slot.human_name, slot.team)
        for slot in replay.header.metadata.players
        if slot.slot_type is ReplaySlotType.Human and slot.human_name and not slot.is_observer
    ]
    return sidecar_team_outcomes(replay_path, humans)


# The instruction the human filling a generated stub reads: it opens right at the top of the
# file. Kept out of the ladder schema (a real sidecar has no such key) so a stub is easy to tell
# from a downloaded record.
_STUB_NOTE = 'Auto-generated stub. Set "IsWinner": true for each player on the winning team.'


def _mode_label(teams: list[int]) -> str:
    """A best-effort `GamemodeName` from the competing players' teams: `2v2` for two teams of
    two, and so on; empty when the shape isn't a clean team-vs-team split (an FFA, or a lone
    side), since the header can't tell those apart with certainty."""
    if not teams or any(team < 0 for team in teams):
        return ""
    sizes = sorted((teams.count(team) for team in set(teams)), reverse=True)
    return "v".join(str(size) for size in sizes) if len(sizes) >= 2 else ""


def build_sidecar_stub(replay: ReplayFile, replay_path: Path) -> dict[str, object]:
    """A sidecar stub for `replay` (read from `replay_path`): the ladder schema's shape filled
    from the replay header alone - each human slot's name, faction index and team, the map, and
    the match length - with `IsWinner` left false for a human to set, the observers flagged, and
    the faction names left blank (naming a faction index needs a loaded game, which stub writing
    deliberately avoids). AI slots issue no orders and are omitted."""
    metadata = replay.header.metadata
    players = [
        {
            "DisplayName": slot.human_name,
            "FactionIndex": slot.faction,
            "FactionName": "",
            "Team": slot.team,
            "IsWinner": False,
            "IsObserver": slot.is_observer,
        }
        for slot in metadata.players
        if slot.slot_type is ReplaySlotType.Human and slot.human_name
    ]
    competitor_teams = [
        slot.team
        for slot in metadata.players
        if slot.slot_type is ReplaySlotType.Human and slot.human_name and not slot.is_observer
    ]
    return {
        "_note": _STUB_NOTE,
        "ReplayId": replay_path.name,
        "MapName": metadata.map_file,
        "GamemodeName": _mode_label(competitor_teams),
        "Duration": hms(replay.header.num_timecodes * replay.seconds_per_frame),
        "Players": players,
        "IsValid": True,
    }


def sidecar_has_winner(path: Path) -> bool:
    """Whether the sidecar at `path` records a winner: a non-observer player flagged `IsWinner`.
    False for a missing/unreadable file or a stub nobody has filled in yet."""
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    return any(
        player.get("IsWinner")
        for player in (data.get("Players") or [])
        if not player.get("IsObserver")
    )


@dataclass
class SidecarReport:
    """The outcome of an `ensure_sidecars` sweep over a corpus."""

    generated: list[Path] = field(default_factory=list)  # replays a stub was newly written for
    needs_winner: list[Path] = field(default_factory=list)  # replays whose sidecar has no winner
    # replays whose header couldn't be parsed, so no stub could be built:
    failed: list[tuple[Path, str]] = field(default_factory=list)


def ensure_sidecars(replays: Iterable[Path]) -> SidecarReport:
    """Write a stub sidecar (`build_sidecar_stub`) beside every replay in `replays` that has
    none, and report which sidecars - freshly written or already present - still record no
    winner (`sidecar_has_winner`). A replay whose header can't be parsed to build a stub is
    listed in `failed` rather than aborting the sweep. Only the header is read, so this needs no
    game install and can run before any is loaded."""
    report = SidecarReport()
    for path in replays:
        sidecar = sidecar_path(path)
        if not sidecar.is_file():
            try:
                replay = parse_replay_from_path(path, only_header=True)
            except Exception as error:  # noqa: BLE001 - an unparseable replay just can't get a stub
                report.failed.append((path, str(error)))
                continue
            sidecar.write_text(
                json.dumps(build_sidecar_stub(replay, path), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            report.generated.append(path)
        if not sidecar_has_winner(sidecar):
            report.needs_winner.append(path)
    return report
