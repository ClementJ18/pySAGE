"""Why an upgrade is never offered to a horde member, only to its container.

A battalion arrives in an observation as its fifteen soldiers plus a container, and the soldiers
carry the same command set - so every upgrade button reads as available on each of them. The
engine accepts the order and logic discards it: the same silent refusal `World.army` records for
movement, in a different order type.

The cost is much worse than one wasted order, because `_upgrade_key` deliberately remembers a
refusal *per object* so that one battalion's failure does not retire an upgrade everywhere. That
is right, and it means every member carries its own `UPGRADE_ATTEMPTS` budget: a seat holding 21
`GondorSpearman` and 78 `PelegirSpearmen` members has a hundred of them to burn before the real
container is reached. Measured live, 65 of one run's 86 research orders were
`Upgrade_GondorBasicTraining on GondorSpearman`, all 65 refused, while the match banked 28,964
gold and its spearmen carried no upgrades at all.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.economy import Economy

MEMBERS = {"GondorSpearman", "PelegirSpearmen", "GondorFighter"}


def _button(upgrade: str, cost: int = 200, player_scope: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        upgrade=upgrade,
        cost=cost,
        player_scope=player_scope,
        needed_upgrades=(),
        enabled_for=lambda held: True,
    )


def _owned(template: str, upgrades: tuple[str, ...] = ()) -> SimpleNamespace:
    return SimpleNamespace(
        template_name=template,
        upgrades=upgrades,
        under_construction=False,
        production=(),
    )


class Base(Economy):
    """`upgrade_options` over an army whose containers and members are both present."""

    upgrade_options = Economy.upgrade_options

    def __init__(self, owned: list) -> None:
        self._owned = owned
        self.statics = SimpleNamespace(
            has_kind=lambda name, *flags: False,
            is_horde_member=lambda name: name in MEMBERS,
            upgrade_buttons=lambda name, held: (_button("Upgrade_GondorBasicTraining"),),
        )

    @property
    def observation(self) -> SimpleNamespace:
        return SimpleNamespace(
            mine=self._owned,
            me=SimpleNamespace(upgrades=(), researching=lambda name: False),
        )

    def queued_upgrades(self, obj: SimpleNamespace) -> int:
        return 0


def _targets(options: list) -> list[str]:
    return [target.template_name for target, _ in options]


def test_a_horde_member_is_never_an_upgrade_target() -> None:
    """The bug in one line: the members carry the button and the engine will not take it."""
    base = Base([_owned("GondorSpearmanHorde"), _owned("GondorSpearman")])
    assert _targets(base.upgrade_options()) == ["GondorSpearmanHorde"]


def test_every_member_of_a_full_battalion_is_skipped() -> None:
    """A horde is fifteen soldiers, and each one used to be its own candidate with its own
    retry budget - which is how 65 refusals came out of a single upgrade."""
    owned = [_owned("GondorSpearmanHorde")] + [_owned("GondorSpearman") for _ in range(15)]
    assert _targets(Base(owned).upgrade_options()) == ["GondorSpearmanHorde"]


def test_containers_of_every_kind_are_still_offered() -> None:
    """The filter must not narrow this to one battalion type, or the rest of the army stops
    being upgraded at all."""
    owned = [
        _owned("GondorSpearmanHorde"),
        _owned("PelegirSpearmenHorde"),
        _owned("GondorFighterHorde"),
    ]
    assert len(Base(owned).upgrade_options()) == 3


def test_a_building_is_not_a_horde_member_and_stays_a_target() -> None:
    """Structures are where the faction techs are bought, and nothing here may touch them."""
    base = Base([_owned("GondorBarracks"), _owned("GondorFighter")])
    assert _targets(base.upgrade_options()) == ["GondorBarracks"]


def test_an_upgrade_already_held_is_still_not_re_offered() -> None:
    """The existing per-object check keeps working alongside the new one."""
    base = Base([_owned("GondorSpearmanHorde", upgrades=("Upgrade_GondorBasicTraining",))])
    assert base.upgrade_options() == []
