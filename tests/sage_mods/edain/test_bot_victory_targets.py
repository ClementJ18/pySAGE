"""What the bot is allowed to call "a thing whose destruction ends the match".

**This exists because the previous answer was unreachable code.** `raid_target`'s last-resort
branch asked for `hostile(o) and counts_for_victory(o)`, and `hostile` excludes everything
`STRUCTURE` or `IMMOBILE`. Checked against the game's own data, **573 of the 574 templates
carrying `MP_COUNT_FOR_VICTORY` are structures** - the one exception is `testherohacksreal`, a
debug template. So the intersection was empty by construction, the branch behind it could never
fire, and a run could raze every lair, hold 94% of the map with a full army and 105,012 gold, and
never attack anything capable of ending the match.

Two rounds of documented corrections were made to that branch's *gate* while its target list was
empty either way, which is the argument for pinning the list itself.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.world import World


class Field:
    """`victory_targets` over a supplied set of enemy buildings."""

    victory_targets = World.victory_targets

    def __init__(self, structures: list[SimpleNamespace], counting: set[str]) -> None:
        self._structures = structures
        self.statics = SimpleNamespace(
            counts_for_victory=lambda name: name in counting,
        )

    def enemy_structures(self) -> list[SimpleNamespace]:
        return self._structures


def _building(name: str, object_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(object_id=object_id, template_name=name)


def test_an_enemy_keep_is_a_victory_target() -> None:
    """The case the old test could never produce: a structure that counts."""
    field = Field([_building("GondorCastleKeep", 7)], counting={"GondorCastleKeep"})
    assert [o.object_id for o in field.victory_targets()] == [7]


def test_an_economy_building_is_not() -> None:
    """`IGNORE_FOR_VICTORY` is on economy buildings precisely so razing them does not count -
    which is why `finished` cannot simply count buildings, and neither can this."""
    field = Field(
        [_building("GondorWohnhaus", 3), _building("GondorCastleKeep", 7)],
        counting={"GondorCastleKeep"},
    )
    assert [o.object_id for o in field.victory_targets()] == [7]


def test_the_list_is_whatever_enemy_structures_already_allows() -> None:
    """Built on `enemy_structures` rather than re-deriving, so the two exclusions that matter
    come for free: `UNTOUCHABLE`, and build sites - a foundation carries `MP_COUNT_FOR_VICTORY`
    *and* an `ImmortalBody`, so it counts toward their survival and cannot be attacked out of the
    way. That asymmetry is real, and it is why holding the map is not the same as winning it.
    """
    field = Field([], counting={"GondorCastleKeep"})
    assert field.victory_targets() == []
