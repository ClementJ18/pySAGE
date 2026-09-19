"""Jump To Game: the command line that starts the game on the open map, and the match it starts.

The engine finds a user map by the absolute, lowercased path of its folder's parent plus the map's
file name (`sage_test.runner.install_map`), and a map inside the game's own file system by
`maps\\<name>.map`. A map that lives in neither place is copied into the user Maps folder first.

Each loaded mod travels as a `-mod` of its own, in load order. `-file` alone does not set up a match
on a stock `game.dat`, and a stock binary mounts `-mod` too late for its `GameData.ini` and honours
only the last one;
`launch_patch` gives the binary the patches for all three for the session.

**The match.** Without further arguments the patch starts its own two-seat game. `JumpMatch` is
the lobby the mapper sets instead - who sits where, their factions, AI difficulty, colours and
teams, the starting resources and the seed - and it travels as the patch's `-gameInfo` argument
(`sage_test.game_info`, and §7 of the same document). Seats name their faction and colour rather
than storing the engine's indices, because the indices are the loaded game's `PlayerTemplate` and
`MultiplayerColor` order: they are looked up at launch, so a mod that reorders its factions does
not quietly change who the mapper is playing.
"""

from __future__ import annotations

import random
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeGuard

from sage_test.game_info import SLOT_COUNT, LobbySettings, game_info_string
from sage_test.maps import file_argument
from sage_test.runner import launch_arguments
from sage_test.scenario import DIFFICULTIES, Seat
from sage_utils.views.base import safe
from sage_worldbuilder.gamedata import GameLayers

if TYPE_CHECKING:
    from sage_ini.model.game import Game

__all__ = [
    "DEFAULT_RESOLUTION",
    "DEFAULT_STARTING_RESOURCES",
    "MAX_RESOLUTION",
    "MIN_RESOLUTION",
    "SEAT_KINDS",
    "TEAM_COUNT",
    "JumpMatch",
    "JumpMatchError",
    "JumpOptions",
    "JumpPlan",
    "JumpSeat",
    "colour_names",
    "default_seats",
    "launch_name",
    "plan_jump",
    "playable_factions",
    "start_position_count",
]

_UNSAFE_NAME = re.compile(r'[<>:"/\\|?*]+')


def launch_name(name: str) -> str:
    """The name a map with no file of its own is copied to the user maps folder under, which is
    also the name the running game then reports for it."""
    return _UNSAFE_NAME.sub("_", name).strip() or "map"


#: Who takes a seat: the local human, or an AI of one of the lobby's difficulties.
SEAT_KINDS = ("human", *DIFFICULTIES)

#: The lobby offers four teams; the slot parser accepts 0..3, and -1 for none.
TEAM_COUNT = 4

DEFAULT_STARTING_RESOURCES = LobbySettings().starting_resources

#: The game window's size, `-xres` by `-yres`; it applies only to a windowed launch.
DEFAULT_RESOLUTION = (1024, 768)
MIN_RESOLUTION = (640, 480)
MAX_RESOLUTION = (7680, 4320)


class JumpMatchError(ValueError):
    """The match settings cannot be turned into a `-gameInfo` argument for the loaded game."""


@dataclass(frozen=True)
class JumpSeat:
    """One seat, by the names the game data uses. `start_position` is 0-based; `team` is 0-based,
    or -1 for no team."""

    kind: str = "human"
    faction: str = ""
    start_position: int = 0
    colour: str = ""
    team: int = -1

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "faction": self.faction,
            "start_position": self.start_position,
            "colour": self.colour,
            "team": self.team,
        }

    @classmethod
    def from_dict(cls, data: Any) -> JumpSeat | None:
        """The seat `data` describes, or `None` when it is not a usable seat at all."""
        if not isinstance(data, dict) or data.get("kind") not in SEAT_KINDS:
            return None
        faction, colour = data.get("faction"), data.get("colour")
        start, team = data.get("start_position"), data.get("team")
        return cls(
            kind=data["kind"],
            faction=faction if isinstance(faction, str) else "",
            start_position=start if _is_int(start) and 0 <= start < SLOT_COUNT else 0,
            colour=colour if isinstance(colour, str) else "",
            team=team if _is_int(team) and -1 <= team < TEAM_COUNT else -1,
        )


@dataclass(frozen=True)
class JumpMatch:
    """The lobby Jump To Game starts. `enabled` off launches the patch's own default match.
    `seed` `None` draws a new one for every launch, as the lobby does."""

    enabled: bool = False
    seats: tuple[JumpSeat, ...] = field(default_factory=tuple)
    starting_resources: int = DEFAULT_STARTING_RESOURCES
    seed: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "seats": [seat.to_dict() for seat in self.seats],
            "starting_resources": self.starting_resources,
            "seed": self.seed,
        }

    @classmethod
    def from_dict(cls, data: Any) -> JumpMatch:
        if not isinstance(data, dict):
            return cls()
        rows = data.get("seats")
        seats = [JumpSeat.from_dict(row) for row in rows] if isinstance(rows, list) else []
        resources, seed = data.get("starting_resources"), data.get("seed")
        return cls(
            enabled=data.get("enabled") is True,
            seats=tuple(seat for seat in seats if seat is not None)[:SLOT_COUNT],
            starting_resources=(
                resources if _is_int(resources) and resources >= 0 else DEFAULT_STARTING_RESOURCES
            ),
            seed=seed if _is_int(seed) and 0 <= seed < 2**31 else None,
        )

    def game_info(self, game: Game | None, rng: random.Random | None = None) -> str:
        """The `-gameInfo` value for this match against `game`'s factions and colours.

        Raises `JumpMatchError`, worded for the mapper, when the game data is not loaded, a seat
        names something the game does not have, or the seats break a rule the engine's lobby
        parser would reject the whole string for.
        """
        if game is None:
            raise JumpMatchError(
                "The game data is not loaded yet, so the seats' factions and colours cannot be "
                "looked up."
            )
        # The two rules a mapper breaks by editing rows, checked here so the message counts seats
        # and positions from 1, as the dialog shows them; the rest `game_info_string` enforces.
        humans = sum(seat.kind == "human" for seat in self.seats)
        if self.seats and humans != 1:
            raise JumpMatchError(f"Exactly one seat must be the human, not {humans}.")
        taken: dict[int, int] = {}
        for number, seat in enumerate(self.seats, start=1):
            if seat.start_position in taken:
                raise JumpMatchError(
                    f"Seats {taken[seat.start_position]} and {number} both start at Position "
                    f"{seat.start_position + 1}."
                )
            taken[seat.start_position] = number
        factions = _table(game, "factions")
        colours = _table(game, "multiplayercolors")
        seats = []
        for number, seat in enumerate(self.seats, start=1):
            faction = _index(factions, seat.faction, f"Seat {number}'s faction")
            colour = _index(colours, seat.colour, f"Seat {number}'s colour")
            ai = seat.kind != "human"
            seats.append(
                Seat(
                    faction=faction,
                    start_position=seat.start_position,
                    colour=colour,
                    team=seat.team,
                    ai=ai,
                    difficulty=seat.kind if ai else DIFFICULTIES[0],
                )
            )
        seed = self.seed if self.seed is not None else (rng or random).randrange(1, 2**31)
        settings = LobbySettings(starting_resources=self.starting_resources, seed=seed)
        try:
            return game_info_string(seats, settings)
        except ValueError as exc:
            raise JumpMatchError(f"{str(exc)[:1].upper()}{str(exc)[1:]}.") from exc


def _is_int(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _table(game: Game, key: str) -> dict[str, Any]:
    table = safe(lambda: game.tables.get(key))
    return table if isinstance(table, dict) else {}


def _index(table: dict[str, Any], name: str, what: str) -> int:
    """`name`'s position in `table` - the engine's registration order, which is what the lobby
    string indexes."""
    if not name:
        raise JumpMatchError(f"{what} is not chosen.")
    for index, key in enumerate(table):
        if key.lower() == name.lower():
            return index
    raise JumpMatchError(f"{what}, {name}, is not in the loaded game data.")


def playable_factions(game: Game | None) -> list[str]:
    """The factions a lobby offers (`PlayableSide`), in the game's order."""
    if game is None:
        return []
    return [
        name
        for name, template in _table(game, "factions").items()
        if safe(lambda template=template: template.PlayableSide)
    ]


def colour_names(game: Game | None) -> list[str]:
    """Every `MultiplayerColor`, in the game's order."""
    return [] if game is None else list(_table(game, "multiplayercolors"))


def default_seats(game: Game | None) -> tuple[JumpSeat, ...]:
    """A human against an easy AI at the first two start positions, on no team, with the first
    two playable factions and colours - what a mapper most often wants to try a map with."""
    factions = playable_factions(game) or [""]
    colours = colour_names(game) or [""]
    return (
        JumpSeat("human", factions[0], 0, colours[0], -1),
        JumpSeat("easy", factions[min(1, len(factions) - 1)], 1, colours[min(1, len(colours) - 1)]),
    )


def start_position_count(map: Any) -> int:
    """How many multiplayer start positions `map` declares, 0 when it has none."""
    positions = getattr(getattr(map, "mp_positions_list", None), "positions", None)
    return len(positions) if isinstance(positions, list) else 0


@dataclass(frozen=True)
class JumpOptions:
    windowed: bool = True
    script_debug: bool = False
    extra_arguments: str = ""
    resolution: tuple[int, int] = DEFAULT_RESOLUTION
    # The `-gameInfo` value choosing the match, or `None` for the patch's default one.
    game_info: str | None = None


@dataclass(frozen=True)
class JumpPlan:
    arguments: list[str]
    working_directory: Path
    # Where the map must be written before launching, when the game cannot find it where it is.
    install_to: Path | None


def _within(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
    except ValueError:
        return False
    return True


def _in_own_folder(path: Path) -> bool:
    return path.parent.name.lower() == path.stem.lower()


def plan_jump(
    map_path: Path | None,
    name: str,
    layers: GameLayers,
    user_files: Path,
    options: JumpOptions,
) -> JumpPlan:
    """How to launch the game on a map saved at `map_path` (`None` for one with no file, such as
    a map read from an archive), whose copy would be called `name`."""
    user_maps = user_files / "Maps"
    install_to = None
    # The mod whose maps folder holds the map, looked for from the last loaded down.
    holder = None
    if map_path is not None and _in_own_folder(map_path):
        holder = next(
            (mod for mod in reversed(layers.mods) if _within(map_path, mod / "maps")), None
        )
    if map_path is not None and _in_own_folder(map_path) and _within(map_path, user_maps):
        argument = str(map_path.parent.parent / map_path.name).lower()
    elif map_path is not None and holder is not None:
        relative = map_path.resolve().relative_to(holder.resolve())
        argument = file_argument(str(relative).replace("/", "\\"))
    else:
        safe_name = launch_name(name)
        install_to = user_maps / safe_name / f"{safe_name}.map"
        argument = str(user_maps / f"{safe_name}.map").lower()
    game_dat = layers.install / "game.dat"
    arguments = launch_arguments(
        argument,
        game_dat,
        game_info=options.game_info,
        mod=layers.mods,
        windowed=options.windowed,
        resolution=options.resolution,
        script_debug=options.script_debug,
        extra=tuple(shlex.split(options.extra_arguments, posix=False)),
    )
    return JumpPlan(arguments, layers.install, install_to)
