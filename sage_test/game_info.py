"""The `-gameInfo` argument: a whole skirmish lobby on one command-line argument.

`command-line-skirmish` hands the argument to the engine's own `ParseAsciiStringToGameInfo`, so
the format is the lobby's own - the string a replay header and `Skirmish.ini` carry, which
`sage_replay.ReplayMetadata` already reads and writes. This builds one from `Seat`s, with each slot
serialized by `sage_replay.ReplaySlot`, whose output is round-trip-tested against the replay corpus.

What the parser insists on, read out of the binary (`sage_patch/docs/game-info.md` §7), and so
what this refuses to produce:

- **Every key** - `M MC MS SD GSID GT SI GR S` - or it commits nothing at all. A key it does not
  know, `SC` included, fails the whole string the same way.
- **Eight slot tokens**, the unused ones closed (`X`).
- Colour and faction no lower than -1 and -2, team -1..3, and a handicap between -100 and 0.

The parser is all-or-nothing, and a rejected string does not stop the game: the patch falls back to
its built-in two seats and records the rejection in its section. So validating here, where the
error can name the seat, is worth more than it looks.

**The map keys are placeholders on purpose.** The patch puts back the map identity the `-file`
start set - that is the map the engine is actually loading - so what `M`, `MC` and `MS` say is
never used; they exist because the parser will not commit without them. `GSID` and `SI` are
restored the same way.

Nothing here needs a game, an install or `sage_map`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sage_replay.replay import ReplaySlot, ReplaySlotDifficulty, ReplaySlotType
from sage_test.scenario import Seat

__all__ = [
    "DEFAULT_RULES",
    "OPTION",
    "SLOT_COUNT",
    "LobbySettings",
    "game_info_string",
]

#: The command-line switch the patch looks for.
OPTION = "-gameInfo"

#: `GameInfo` holds eight slots, and the parser reads exactly eight tokens.
SLOT_COUNT = 8

#: A menu skirmish's `GR`, as every replay in the corpus records it. Rule 4 is the starting
#: resources - it lands at `GameInfo+0x70`, the field writing 1000 into gave both players exactly
#: 1000. Rule 3 (100) is not identified; the trailing five are unset.
DEFAULT_RULES = (0, 0, 1, 100, 1000, -1, -1, -1, -1, -1)
_STARTING_RESOURCES_RULE = 4

_DIFFICULTIES = {
    "easy": ReplaySlotDifficulty.Easy,
    "medium": ReplaySlotDifficulty.Medium,
    "hard": ReplaySlotDifficulty.Hard,
    "brutal": ReplaySlotDifficulty.Brutal,
}

#: The display name the human seat gets. Plain letters: the parser unescapes names, so anything
#: that looks like an escape would arrive as something else.
HUMAN_NAME = "Player"

#: Characters that end a key, a value, a slot or a field in the parser's tokenizer.
_DELIMITERS = set(";=:,\n")

_MAP_PLACEHOLDER = "maps/command line"


@dataclass(frozen=True)
class LobbySettings:
    """Everything about a match that is not a seat.

    `rules` is the raw `GR` list; `starting_resources` is written over its fifth entry, because
    that is the one field of it anyone has confirmed and the one a test most often wants to set.
    The default matches the patch's own fallback, which is enough to unpack an Edain fortress.
    """

    starting_resources: int = 5000
    seed: int = 0
    rules: tuple[int, ...] = DEFAULT_RULES

    def game_rules(self) -> tuple[int, ...]:
        if len(self.rules) != len(DEFAULT_RULES):
            raise ValueError(f"GR takes {len(DEFAULT_RULES)} rules, not {len(self.rules)}")
        rules = list(self.rules)
        rules[_STARTING_RESOURCES_RULE] = self.starting_resources
        return tuple(rules)


def _slot(seat: Seat) -> ReplaySlot:
    """One seat in the lobby's wire form.

    The field after the team is a handicap (-100..0) for both kinds; a human then carries two more
    and an AI one, which is what `reserved` holds - the values every replay in the corpus has.
    """
    # `Any`, not the inferred `int`: these go out as `**common` into fields of several types.
    common: dict[str, Any] = {
        "color": seat.colour,
        "faction": seat.faction,
        "start_position": seat.start_position,
        "team": seat.team,
        "nat_behavior": 0,
    }
    if seat.ai:
        return ReplaySlot(
            slot_type=ReplaySlotType.Computer,
            computer_difficulty=_DIFFICULTIES[seat.difficulty],
            reserved=(0,),
            **common,
        )
    return ReplaySlot(
        slot_type=ReplaySlotType.Human,
        human_name=HUMAN_NAME,
        port=0,
        accepted=True,
        has_map=True,
        reserved=(1, 0),
        **common,
    )


def _check(seats: Sequence[Seat]) -> None:
    if not 1 <= len(seats) <= SLOT_COUNT:
        raise ValueError(f"a skirmish has 1 to {SLOT_COUNT} seats, not {len(seats)}")
    humans = [seat for seat in seats if not seat.ai]
    if len(humans) != 1:
        # Every `H` slot the parser reads becomes state 6, the local human, so a second one is
        # not a second player - it is a second claim to be this machine.
        raise ValueError(f"exactly one seat must be the human, not {len(humans)}")
    taken: dict[int, int] = {}
    for index, seat in enumerate(seats):
        # A random start position (-1) or faction or colour is legal lobby data, but nothing has
        # shown a `-file` start resolving one, and a seat with no start position binds to no
        # map player - so this refuses them rather than launching a match that is not the one
        # declared.
        if not 0 <= seat.start_position < SLOT_COUNT:
            raise ValueError(f"seat {index}: start position {seat.start_position} is not 0..7")
        if seat.start_position in taken:
            raise ValueError(
                f"seats {taken[seat.start_position]} and {index} both start at position "
                f"{seat.start_position}"
            )
        taken[seat.start_position] = index
        if seat.faction < 0:
            raise ValueError(f"seat {index}: faction {seat.faction} is a random or observer pick")
        if seat.colour < 0:
            raise ValueError(f"seat {index}: colour {seat.colour} is a random pick")
        if not -1 <= seat.team <= 3:
            raise ValueError(f"seat {index}: team {seat.team} is not -1..3")


def game_info_string(
    seats: Sequence[Seat],
    settings: LobbySettings | None = None,
    *,
    map_file: str = _MAP_PLACEHOLDER,
) -> str:
    """The `-gameInfo` value for `seats`.

    The human takes slot 0 and the AI seats follow in order, whatever order they were declared
    in: the slot index is not what binds a seat to the map (the start position is), and slot 0 is
    the one the engine's own `setSlot` special-cases for a local human.
    """
    settings = settings or LobbySettings()
    _check(seats)
    if _DELIMITERS & set(map_file) or len(map_file) == 0:
        raise ValueError(f"map_file {map_file!r} is empty or holds a delimiter")

    ordered = [seat for seat in seats if not seat.ai] + [seat for seat in seats if seat.ai]
    slots = [_slot(seat).serialize() for seat in ordered]
    slots += ["X"] * (SLOT_COUNT - len(slots))

    keys = (
        ("M", f"000{map_file}"),
        ("MC", "0"),
        ("MS", "0"),
        ("SD", str(settings.seed)),
        ("GSID", "0"),
        ("GT", "0"),
        ("SI", "-1"),
        ("GR", " ".join(str(rule) for rule in settings.game_rules())),
        ("S", "".join(f"{slot}:" for slot in slots)),
    )
    return "".join(f"{key}={value};" for key, value in keys)
