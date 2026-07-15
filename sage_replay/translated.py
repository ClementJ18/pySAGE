"""The translated-replay document: one replay's parse with every id already resolved.

A raw replay is not portable analysis data: its order stream carries integer ids that only
resolve against the exact game build that recorded it (template ids by ini load order, hero
recruits by revive-menu position, faction indices by PlayerTemplate order), so consuming a
corpus spanning mod patches normally means installing and mounting each patch in turn (see
`tools/rebuild_aggregates.py`). This module defines the document that removes that coupling:
every id already a template code name, every faction its (possibly overlay-refined) label,
every event clocked in match seconds - meaningful against any game version whose templates
share those names, so the exact recording build is only needed once, by whoever produces it.

`TranslatedReplay` is the document, `TranslatedPlayer` one human competitor in it, and each
event is a `stats.StatEvent` (seconds, category, label - the label stays an `int` only for the
`fortress_hero_slots` category, an unresolved revive-menu position). The JSON schema, version
`FORMAT_VERSION`:

    {
      "format": "sage-replay/translated",   # the document's magic, for shared files
      "format_version": 1,
      "replay": "<replay file name>",       # the source name player-games report
      "size": 123456,                       # the replay file's byte size ...
      "sha256": "<hex digest>",             # ... and content hash: identity that survives
                                            # copying (an mtime would not), so a document
                                            # shared alongside its replay stays verifiable
      "fingerprint": "<patch fingerprint>", # which recording patch produced it (provenance;
                                            # ReplayHeader.patch_fingerprint)
      "assume_pov_won": true,               # the heuristic-outcome assumption it was
                                            # computed under (aggregate's --winner-pov)
      "duration": 1830.5,                   # recorded sim seconds (the last order's clock)
      "players": [
        {"name": "...", "team": 0,          # lobby team, for mapping a sidecar verdict
         "faction": "<refined label>",
         "opponents": ["<label>", ...],
         "heuristic_outcome": "won",        # the parse-time concession verdict, the fallback
                                            # when no trustworthy sidecar is beside the replay
         "events": [[seconds, category, label], ...]},
        ...
      ],
      "sides": {"<label>": "<Side>", ...}   # each event label's faction Side, so consumers
                                            # (the cross-faction badge) need no game either
    }

Match outcomes are deliberately soft in this document: `heuristic_outcome` is the frozen
parse-time concession verdict (it cannot be recomputed without the order stream), and the
authoritative winner is the hand-edited ladder sidecar beside the replay, which
`to_player_games` accepts as an override - see its docstring for the fallback contract, and
`cache.load_replay_cache` for where the two get wired together.

`from_dict` and `matches_replay` document their own validation and verification contracts; both
are what let a consumer trust a shared replay+document pair without re-parsing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sage_replay.aggregate import PlayerGame
from sage_replay.replay import ReplayFile
from sage_replay.stats import PlayerStats, StatEvent

__all__ = ["FORMAT", "FORMAT_VERSION", "TranslatedPlayer", "TranslatedReplay"]

# The document magic and schema version. Bump the version on any change to what the fields
# mean or how a fresh parse fills them (a stats-pipeline change, a mod-overlay hook change) -
# every existing document then reads as stale rather than silently wrong.
FORMAT = "sage-replay/translated"
FORMAT_VERSION = 1

# A player-game outcome, as aggregate.py records it.
_OUTCOMES = ("won", "lost", "undetermined")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(slots=True)
class TranslatedPlayer:
    """One human competitor's translated parse: identity, the labels their slot resolved to,
    and their clocked event timeline. `team` is the lobby team, kept so a sidecar's
    team-level verdict can be mapped onto the player without the replay (see
    `sidecar.sidecar_team_outcomes`); `heuristic_outcome` is the parse-time concession
    verdict, the fallback when no sidecar speaks for the game."""

    name: str
    team: int
    faction: str
    opponents: tuple[str, ...] = ()
    heuristic_outcome: str = "undetermined"
    events: list[StatEvent] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "team": self.team,
            "faction": self.faction,
            "opponents": list(self.opponents),
            "heuristic_outcome": self.heuristic_outcome,
            "events": [[e.seconds, e.category, e.label] for e in self.events],
        }

    @classmethod
    def from_dict(cls, payload: dict) -> TranslatedPlayer:
        try:
            name = payload["name"]
            team = payload["team"]
            faction = payload["faction"]
        except (TypeError, KeyError) as error:
            raise ValueError(f"translated player is missing {error}") from error
        outcome = payload.get("heuristic_outcome", "undetermined")
        if outcome not in _OUTCOMES:
            raise ValueError(f"unknown heuristic_outcome {outcome!r} for player {name!r}")
        try:
            events = [
                StatEvent(seconds, category, label)
                for seconds, category, label in payload.get("events", [])
            ]
        except (TypeError, ValueError) as error:
            raise ValueError(f"malformed events for player {name!r}: {error}") from error
        return cls(
            name=name,
            team=team,
            faction=faction,
            opponents=tuple(payload.get("opponents", ())),
            heuristic_outcome=outcome,
            events=events,
        )


@dataclass(slots=True)
class TranslatedReplay:
    """One replay's translated parse - see the module docstring for the schema and the
    portability contract. `size`/`sha256` identify the replay file the document was produced
    from; `fingerprint` records the patch that recording simulates under; `assume_pov_won`
    records the assumption each `heuristic_outcome` was computed with, so a consumer wanting
    the other assumption knows to reparse rather than reuse."""

    replay: str
    size: int
    sha256: str
    fingerprint: str
    assume_pov_won: bool
    duration: float
    players: list[TranslatedPlayer] = field(default_factory=list)
    sides: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_parse(
        cls,
        replay_path: Path,
        replay: ReplayFile,
        games: list[PlayerGame],
        *,
        heuristic_outcomes: dict[str, str],
        side_of: Callable[[str], str | None],
        assume_pov_won: bool,
    ) -> TranslatedReplay:
        """The document for a fresh parse: `games` is the raw `player_games()` output for
        `replay` (read from `replay_path`), `heuristic_outcomes` the concession-heuristic
        verdict (`aggregate._outcomes`) frozen in as each player's fallback, and `side_of`
        (typically `GameData.effective_side`) is asked for every distinct string event label
        so the Side lookups travel with the document."""
        teams = {
            slot.human_name: slot.team for slot in replay.header.metadata.players if slot.human_name
        }
        sides: dict[str, str] = {}
        players = []
        for game in games:
            for event in game.stats.events:
                if isinstance(event.label, str) and event.label not in sides:
                    side = side_of(event.label)
                    if side is not None:
                        sides[event.label] = side
            players.append(
                TranslatedPlayer(
                    name=game.player,
                    team=teams.get(game.player, -1),
                    faction=game.faction,
                    opponents=game.opponents,
                    heuristic_outcome=heuristic_outcomes.get(game.player, "undetermined"),
                    events=list(game.stats.events),
                )
            )
        stat = replay_path.stat()
        return cls(
            replay=games[0].replay if games else replay_path.name,
            size=stat.st_size,
            sha256=_sha256(replay_path),
            fingerprint=replay.header.patch_fingerprint,
            assume_pov_won=assume_pov_won,
            duration=games[0].duration if games else 0.0,
            players=players,
            sides=sides,
        )

    def to_dict(self) -> dict:
        return {
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "replay": self.replay,
            "size": self.size,
            "sha256": self.sha256,
            "fingerprint": self.fingerprint,
            "assume_pov_won": self.assume_pov_won,
            "duration": self.duration,
            "players": [player.to_dict() for player in self.players],
            "sides": dict(self.sides),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> TranslatedReplay:
        """The document `payload` describes, or `ValueError` when it isn't one this reader
        understands: a different magic, a `format_version` other than `FORMAT_VERSION`
        (older AND newer - the schema has no compatibility promise across versions), or a
        missing/malformed field. Unknown extra keys are ignored, so a same-version producer
        may annotate documents freely."""
        if not isinstance(payload, dict):
            raise ValueError("translated replay document must be a JSON object")
        if payload.get("format", FORMAT) != FORMAT:
            raise ValueError(f"not a {FORMAT} document: format={payload.get('format')!r}")
        version = payload.get("format_version")
        if version != FORMAT_VERSION:
            raise ValueError(f"unsupported format_version {version!r} (reader is {FORMAT_VERSION})")
        try:
            return cls(
                replay=payload["replay"],
                size=payload["size"],
                sha256=payload["sha256"],
                fingerprint=payload["fingerprint"],
                assume_pov_won=payload["assume_pov_won"],
                duration=payload["duration"],
                players=[TranslatedPlayer.from_dict(p) for p in payload.get("players", [])],
                sides=dict(payload.get("sides") or {}),
            )
        except KeyError as error:
            raise ValueError(f"translated replay document is missing {error}") from error

    def write(self, path: Path) -> None:
        """Serialize to `path` (UTF-8 JSON, compact). The caller owns the location - the
        `_cache` convention lives in `cache.py`, and a shared document can go anywhere."""
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    @classmethod
    def read(cls, path: Path) -> TranslatedReplay:
        """Deserialize the document at `path`. Raises `OSError` for an unreadable file and
        `ValueError` for one that isn't a supported translated-replay document."""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"{path.name}: not JSON: {error}") from error
        return cls.from_dict(payload)

    @property
    def player_teams(self) -> list[tuple[str, int]]:
        """Each competitor as `(name, lobby team)` - the shape `sidecar.sidecar_team_outcomes`
        maps a sidecar's team verdict onto, replay-free."""
        return [(player.name, player.team) for player in self.players]

    def matches_replay(self, replay_path: Path) -> bool:
        """Whether the file at `replay_path` is the replay this document was produced from:
        size first (a cheap reject), then the content hash. Copying a replay to another
        machine preserves both, so a shared replay+document pair verifies anywhere."""
        try:
            stat = replay_path.stat()
        except OSError:
            return False
        return stat.st_size == self.size and _sha256(replay_path) == self.sha256

    def to_player_games(self, outcomes: dict[str, str] | None = None) -> list[PlayerGame]:
        """The document's players as `PlayerGame`s, ready for `aggregate._absorb`/
        `aggregate.aggregate` - raw exactly as `player_games()` produced them (an unresolved
        `"?"` faction or opponent included, so downstream filtering behaves identically to a
        fresh parse). `outcomes` (a `{name: "won"|"lost"}` map, e.g. the current sidecar's
        verdict) overrides every player's outcome when given; without it each player falls
        back to their frozen `heuristic_outcome`."""
        games = []
        for player in self.players:
            if outcomes is not None:
                outcome = outcomes.get(player.name, "undetermined")
            else:
                outcome = player.heuristic_outcome
            games.append(
                PlayerGame(
                    replay=self.replay,
                    player=player.name,
                    faction=player.faction,
                    outcome=outcome,
                    duration=self.duration,
                    stats=PlayerStats(player=player.name, events=list(player.events)),
                    opponents=player.opponents,
                )
            )
        return games
