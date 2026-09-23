"""A lobby seat: the player in one slot, their faction, team and start position."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DIFFICULTIES", "Seat"]

#: The AI levels the lobby offers, which the engine's slot parser turns into slot states 2-5.
DIFFICULTIES = ("easy", "medium", "hard", "brutal")


@dataclass(frozen=True)
class Seat:
    """One player slot: who they are, and where they start.

    `faction` is an index into the loaded mod's `playertemplate.ini` order, which is what the
    engine's `GameSlot` carries and what `command-line-skirmish` writes - not a name, because the
    ordering is the mod's and no fixed enum survives a mod change.

    `start_position` is load-bearing beyond where the camera opens: a seat binds to the map-side
    player `Player_<start_position + 1>`, and that is the player a scenario's objects must be
    owned by for the seat to own them. `map_player` is that name.
    """

    faction: int
    start_position: int = 0
    colour: int = 0
    #: 0-based, or -1 for the lobby's "no team". The default is -1 so that seats which declare
    #: nothing play against each other: a shared default team would make them allies.
    team: int = -1
    #: False means the local human - the seat a test drives. True means an AI of `difficulty`.
    ai: bool = False
    #: One of `DIFFICULTIES`. Ignored for the human seat.
    difficulty: str = "easy"

    def __post_init__(self) -> None:
        if self.difficulty not in DIFFICULTIES:
            raise ValueError(f"difficulty {self.difficulty!r} is not one of {DIFFICULTIES}")

    @classmethod
    def human(cls, faction: int, start_position: int = 0, **kwargs) -> Seat:
        return cls(faction=faction, start_position=start_position, ai=False, **kwargs)

    @classmethod
    def easy_ai(cls, faction: int, start_position: int = 1, **kwargs) -> Seat:
        return cls(faction=faction, start_position=start_position, ai=True, **kwargs)

    @classmethod
    def computer(
        cls, faction: int, difficulty: str = "medium", start_position: int = 1, **kwargs
    ) -> Seat:
        return cls(
            faction=faction,
            start_position=start_position,
            ai=True,
            difficulty=difficulty,
            **kwargs,
        )

    @property
    def map_player(self) -> str:
        """The map-side player this seat binds to, which follows the start position."""
        return f"Player_{self.start_position + 1}"

    @property
    def map_team(self) -> str:
        """The qualified owner an object of this seat's is written under."""
        return f"{self.map_player}/team{self.map_player}"
