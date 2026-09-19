"""Tests for the `-gameInfo` lobby string a scenario's seats are launched with.

Data-free. The string is checked against the grammar the engine's `ParseAsciiStringToGameInfo`
accepts (`sage_patch/docs/game-info.md` §7) - which is all-or-nothing, and whose rejection the game
survives by starting a *different* match - so every refusal here is one the engine would make
silently.
"""

from __future__ import annotations

import pytest

from sage_replay.replay import (
    ReplayGameType,
    ReplayMetadata,
    ReplaySlotDifficulty,
    ReplaySlotType,
)
from sage_test.game_info import DEFAULT_RULES, LobbySettings, game_info_string
from sage_test.scenario import Seat

_REQUIRED_KEYS = ("M", "MC", "MS", "SD", "GSID", "GT", "SI", "GR", "S")


def _pairs(text: str) -> dict[str, str]:
    assert text.endswith(";")
    return dict(entry.split("=", 1) for entry in text[:-1].split(";"))


def _slots(text: str) -> list[str]:
    value = _pairs(text)["S"]
    assert value.endswith(":")
    return value[:-1].split(":")


def _two_seats(**human) -> tuple[Seat, Seat]:
    return Seat.human(faction=3, start_position=0, **human), Seat.easy_ai(faction=10)


class TestTheKeys:
    def test_every_key_the_parser_requires_is_present(self):
        assert tuple(_pairs(game_info_string(_two_seats()))) == _REQUIRED_KEYS

    def test_starting_credits_is_never_written(self):
        """`SC` is a key replays can carry and the parser does not know - and an unknown key
        fails the whole string."""
        assert "SC" not in _pairs(game_info_string(_two_seats()))

    def test_the_seed_is_carried(self):
        text = game_info_string(_two_seats(), LobbySettings(seed=1234))
        assert _pairs(text)["SD"] == "1234"

    def test_starting_resources_is_the_fifth_rule(self):
        text = game_info_string(_two_seats(), LobbySettings(starting_resources=12345))
        rules = [int(rule) for rule in _pairs(text)["GR"].split()]
        assert len(rules) == 10
        assert rules[4] == 12345
        assert rules[:4] + rules[5:] == list(DEFAULT_RULES[:4] + DEFAULT_RULES[5:])

    def test_a_rules_list_of_the_wrong_length_is_refused(self):
        with pytest.raises(ValueError, match="10 rules"):
            game_info_string(_two_seats(), LobbySettings(rules=(0, 0, 1)))

    def test_the_map_placeholder_is_long_enough_for_the_mask(self):
        """The parser skips three hex digits of `M=` before the path and refuses anything
        shorter."""
        assert len(_pairs(game_info_string(_two_seats()))["M"]) > 3

    def test_a_map_name_holding_a_delimiter_is_refused(self):
        with pytest.raises(ValueError, match="delimiter"):
            game_info_string(_two_seats(), map_file="maps/a;b")


class TestTheSlots:
    def test_there_are_always_eight(self):
        slots = _slots(game_info_string(_two_seats()))
        assert len(slots) == 8
        assert slots[2:] == ["X"] * 6

    def test_the_human_takes_slot_zero_whatever_the_declaration_order(self):
        seats = (
            Seat.easy_ai(faction=10, start_position=0),
            Seat.human(faction=3, start_position=1),
        )
        slots = _slots(game_info_string(seats))
        assert slots[0].startswith("H")
        assert slots[1].startswith("CE")

    def test_the_field_counts_match_the_parser(self):
        """A human reads eleven comma fields and an AI seven: one field short and the parser
        runs out of tokens and rejects the string."""
        human, ai = _slots(game_info_string(_two_seats()))[:2]
        assert len(human.split(",")) == 11
        assert len(ai.split(",")) == 7

    @pytest.mark.parametrize(
        ("difficulty", "letter"),
        [("easy", "CE"), ("medium", "CM"), ("hard", "CH"), ("brutal", "CB")],
    )
    def test_each_difficulty_has_its_letter(self, difficulty, letter):
        seats = (Seat.human(faction=3), Seat.computer(faction=10, difficulty=difficulty))
        assert _slots(game_info_string(seats))[1].split(",")[0] == letter

    def test_the_handicap_is_in_the_parsers_range(self):
        """The field after the team is range-checked to -100..0 on both kinds of slot."""
        human, ai = _slots(game_info_string(_two_seats()))[:2]
        assert -100 <= int(human.split(",")[8]) <= 0
        assert -100 <= int(ai.split(",")[5]) <= 0

    def test_it_reads_back_as_the_seats_that_were_declared(self):
        seats = (
            Seat.human(faction=3, start_position=4, colour=9, team=0),
            Seat.computer(faction=10, difficulty="hard", start_position=2, colour=1, team=1),
            Seat.computer(faction=7, difficulty="brutal", start_position=0, colour=2, team=1),
        )
        metadata = ReplayMetadata.from_string(game_info_string(seats), ReplayGameType.Bfme2)
        players = metadata.players
        assert [slot.slot_type for slot in players] == [
            ReplaySlotType.Human,
            ReplaySlotType.Computer,
            ReplaySlotType.Computer,
        ]
        assert [(s.faction, s.start_position, s.color, s.team) for s in players] == [
            (3, 4, 9, 0),
            (10, 2, 1, 1),
            (7, 0, 2, 1),
        ]
        assert players[1].computer_difficulty is ReplaySlotDifficulty.Hard
        assert players[2].computer_difficulty is ReplaySlotDifficulty.Brutal


class TestWhatItRefuses:
    def test_no_seats(self):
        with pytest.raises(ValueError, match="1 to 8"):
            game_info_string(())

    def test_more_than_eight(self):
        seats = [Seat.human(faction=3, start_position=0)]
        seats += [Seat.easy_ai(faction=10, start_position=p) for p in range(1, 9)]
        with pytest.raises(ValueError, match="1 to 8"):
            game_info_string(seats)

    def test_no_human(self):
        with pytest.raises(ValueError, match="exactly one"):
            game_info_string((Seat.easy_ai(faction=10, start_position=0),))

    def test_two_humans(self):
        """Every `H` slot becomes the local human, so a second one is a second claim to be
        this machine rather than a second player."""
        seats = (Seat.human(faction=3, start_position=0), Seat.human(faction=3, start_position=1))
        with pytest.raises(ValueError, match="exactly one"):
            game_info_string(seats)

    def test_a_shared_start_position(self):
        seats = (
            Seat.human(faction=3, start_position=1),
            Seat.easy_ai(faction=10, start_position=1),
        )
        with pytest.raises(ValueError, match="both start at position 1"):
            game_info_string(seats)

    @pytest.mark.parametrize("position", [-1, 8])
    def test_a_start_position_that_binds_no_map_player(self, position):
        with pytest.raises(ValueError, match="start position"):
            game_info_string((Seat.human(faction=3, start_position=position),))

    @pytest.mark.parametrize("faction", [-1, -2])
    def test_a_random_or_observer_faction(self, faction):
        with pytest.raises(ValueError, match="faction"):
            game_info_string((Seat.human(faction=faction),))

    def test_a_random_colour(self):
        with pytest.raises(ValueError, match="colour"):
            game_info_string((Seat.human(faction=3, colour=-1),))

    def test_a_team_the_parser_rejects(self):
        with pytest.raises(ValueError, match="team"):
            game_info_string((Seat.human(faction=3, team=4),))
