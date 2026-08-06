"""Name to id without a game install, and the two failures a caller must be able to tell apart.

`LiveNames` reads the engine's own upgrade registry, so these run against a fake source rather
than a process - the point being that nothing about the mapping needs a game on disk.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sage_live import LiveNames, NameLookup, NoNameLookup, Session, UnknownDefinition
from sage_live.backends.base import LoopbackBackend
from sage_live.utils.naming import nearby


@dataclass(frozen=True)
class Row:
    upgrade_id: int
    name: str
    player_scoped: bool = True


class FakeRegistries:
    """The registries `LiveNames` reads, plus a count of how often each was asked."""

    def __init__(
        self,
        *rows: Row,
        things: tuple[str, ...] = (),
        powers: tuple[str, ...] = (),
    ) -> None:
        self.rows = rows
        self.things = things
        self.powers = powers
        self.reads = 0
        self.thing_reads = 0
        self.power_reads = 0

    def upgrade_table(self) -> dict[int, Row]:
        self.reads += 1
        return {row.upgrade_id: row for row in self.rows}

    def thing_order(self) -> tuple[str, ...]:
        self.thing_reads += 1
        return self.things

    def power_order(self) -> tuple[str, ...]:
        self.power_reads += 1
        return self.powers


@pytest.fixture
def names() -> LiveNames:
    return LiveNames(
        FakeRegistries(
            Row(0, "Upgrade_Veterancy_VETERAN"),
            Row(3, "Upgrade_DefaultUpgrade"),
            Row(412, "Upgrade_MordorForgedBlades"),
            Row(413, "Upgrade_MordorHeavyArmor"),
            things=("DefaultThingTemplate", "MordorFighterHorde", "GondorBarracks"),
        )
    )


def test_an_upgrade_resolves_to_the_engines_own_id(names):
    assert names.upgrade("Upgrade_MordorForgedBlades") == 412


def test_id_zero_is_a_real_upgrade_not_a_miss(names):
    """`Upgrade_Veterancy_VETERAN` is registered first, at index 0, so a falsy id is valid."""
    assert names.upgrade("Upgrade_Veterancy_VETERAN") == 0


def test_lookup_is_case_insensitive(names):
    assert names.upgrade("upgrade_mordorheavyarmor") == 413


def test_the_table_is_read_once(names):
    source = names.source
    names.upgrade("Upgrade_DefaultUpgrade")
    names.upgrade("Upgrade_MordorForgedBlades")
    assert source.reads == 1


def test_an_unknown_upgrade_raises_with_the_registered_spelling(names):
    with pytest.raises(UnknownDefinition) as caught:
        names.upgrade("Upgrade_MordorForgedBlade")
    message = str(caught.value)
    assert "Upgrade_MordorForgedBlades" in message, "the hint should offer the real spelling"
    assert caught.value.space == "upgrade"


def test_the_unwalked_space_says_so_rather_than_guessing(names):
    """`TheScienceStore` is the one registry still not walked. Saying so is not the same
    answer as "this build has no such science", and conflating them sends a caller hunting
    for a typo in a perfectly good name."""
    with pytest.raises(NoNameLookup) as caught:
        names.science("AnythingAtAll")
    assert "Resolver" in str(caught.value), "the message should name the way forward"


def test_a_power_with_no_store_walked_says_so_too(names):
    """The `names` fixture supplies no powers, which is the empty-store case."""
    with pytest.raises(NoNameLookup):
        names.power("SpecialAbilityAnything")


def test_a_power_resolves_to_its_walk_position_plus_the_offset():
    """`DefaultSpecialPower` is registered first, exactly as `DefaultThingTemplate` is in the
    thing table, which is what corroborates a 1-based space rather than assuming one."""
    lookup = LiveNames(
        FakeRegistries(
            powers=("DefaultSpecialPower", "SpecialAbilitySarumanMagiestoss", "SpecialAbilityX")
        )
    )
    assert lookup.power("DefaultSpecialPower") == 1
    assert lookup.power("specialabilitysarumanmagiestoss") == 2
    assert lookup.power("SpecialAbilityX") == 3


def test_an_unknown_power_offers_a_hint():
    lookup = LiveNames(
        FakeRegistries(powers=("DefaultSpecialPower", "SpecialAbilitySarumanMagiestoss"))
    )
    with pytest.raises(UnknownDefinition) as caught:
        lookup.power("SarumanMagie")
    assert caught.value.space == "power"


def test_the_power_store_is_read_once():
    source = FakeRegistries(powers=("DefaultSpecialPower", "SpecialAbilityX"))
    lookup = LiveNames(source)
    lookup.power("SpecialAbilityX")
    lookup.power("DefaultSpecialPower")
    assert source.power_reads == 1


def test_a_thing_resolves_to_its_walk_position_plus_the_offset(names):
    """`DefaultThingTemplate` is registered first, and an id space that starts at 1 puts it
    at 1 - which is what corroborates the offset rather than assuming it."""
    assert names.thing("DefaultThingTemplate") == 1
    assert names.thing("MordorFighterHorde") == 2
    assert names.thing("gondorbarracks") == 3


def test_the_thing_table_is_read_once(names):
    names.thing("MordorFighterHorde")
    names.thing("GondorBarracks")
    assert names.source.thing_reads == 1


def test_an_unknown_thing_raises_with_a_hint(names):
    with pytest.raises(UnknownDefinition) as caught:
        names.thing("MordorFighterHord")
    assert "MordorFighterHorde" in str(caught.value)


def test_an_empty_thing_table_says_the_factory_was_not_walked():
    empty = LiveNames(FakeRegistries(Row(3, "Upgrade_DefaultUpgrade")))
    with pytest.raises(NoNameLookup) as caught:
        empty.thing("Anything")
    assert "TheThingFactory" in str(caught.value)


def test_live_names_satisfies_the_protocol(names):
    assert isinstance(names, NameLookup)


def test_a_session_resolves_names_through_its_lookup(names):
    session = Session(LoopbackBackend(), player_index=3, names=names)
    session.connect()
    assert session.resolve("upgrade", "Upgrade_MordorHeavyArmor") == 413
    assert session.resolve("upgrade", 999) == 999, "an id passes straight through"


def test_a_session_with_no_lookup_says_that_rather_than_unknown_name():
    """The two failures must not be confused: one is a typo, the other is a missing resolver."""
    session = Session(LoopbackBackend(), player_index=3)
    session.connect()
    with pytest.raises(NoNameLookup):
        session.research("Upgrade_MordorForgedBlades", building_id=42)
    assert session.resolve("upgrade", 412) == 412, "ids still work with no lookup at all"


def test_research_by_name_reaches_the_backend(names):
    backend = LoopbackBackend()
    session = Session(backend, player_index=3, names=names)
    session.connect()
    assert session.research("Upgrade_MordorForgedBlades", building_id=42) == 1
    values = [argument.value for argument in backend.sent[-1].arguments]
    assert 412 in values and 42 in values


def test_nearby_prefers_substring_then_prefix():
    names = ["MordorFighterHorde", "MordorArcherHorde", "GondorFighterHorde"]
    assert nearby("Archer", names) == ["MordorArcherHorde"]
    assert nearby("Mordor", names) == ["MordorFighterHorde", "MordorArcherHorde"]
    assert nearby("Gondor_Typo", names) == ["GondorFighterHorde"]
    assert nearby("zzz", names) == []
