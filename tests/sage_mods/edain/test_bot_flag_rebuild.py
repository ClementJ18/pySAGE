"""Building on a claimed flag: the two things that make the ground refuse, and neither is a failure.

A flag is unbuildable for about twelve game seconds after whatever stood on it is gone, and it is
unbuildable while something hostile is standing on it. The two are **independent** - different
rules on different clocks - so a flag can be inside its cooldown and contested at once, and
clearing one is not clearing the other.

Both are checked in `raise_settlement`, where the order actually goes out, and not in
`external_plots`. That list is a *walk target* chosen many cycles before the build: a flag being
fought over is precisely the flag the bot should be marching at, and dropping a resting one would
strand a party mid-march for a cooldown that expires long before it arrives.

And both are a **wait**, not a refusal. `_strike` benches a flag after three failures, on the
reading that an order refused three times is never going to work; these are orders that are not
going to work *yet*, and counting them would bench the settlement the bot just paid a battalion
to take.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_mods.edain.bot.warfare import Warfare

FLAG_ID = 214


def _flag() -> SimpleNamespace:
    return SimpleNamespace(
        object_id=FLAG_ID,
        template_name="WirtschaftPlotFlag_Real",
        position=(900.0, 0.0, 0.0),
        owner_index=1,
        distance_to=lambda other: abs(other[0] - 900.0),
    )


class Raiser:
    """`raise_settlement` with the order path stubbed, recording whether it was reached."""

    raise_settlement = Warfare.raise_settlement

    def __init__(self, resting: bool = False, contested: bool = False) -> None:
        self._resting = resting
        self._contested = contested
        self.sent: list[str] = []
        self.strikes: list[tuple[str, bool]] = []
        self.dropped: list[int] = []
        self.released = False

    # --- the two ground rules under test -------------------------------------------------
    def resting(self, plot) -> bool:
        return self._resting

    def contested(self, plot) -> bool:
        return self._contested

    # --- everything else the method touches ----------------------------------------------
    def unpack_plot(self, flag):
        return (lambda: True, "unpack Farm_Exte", "GondorFarm_Extern")

    def afford(self, template, purpose="") -> bool:
        return True

    def select(self, objects) -> bool:
        return True

    def external_family(self, template):
        return None

    def _issue(self, label, act):
        self.sent.append(label)
        return act()

    def _report(self, label, ok, good, bad) -> bool:
        return ok

    def _strike(self, key, ok, seconds=0.0) -> bool:
        self.strikes.append((key, ok))
        return ok

    def _cold(self, key) -> bool:
        return False

    def drop_flag(self, flag, why, party=None) -> None:
        self.dropped.append(flag.object_id)

    def release(self, purpose) -> None:
        self.released = True

    @property
    def session(self):
        return SimpleNamespace(confirm_appeared=lambda act, near, within: bool(act()))

    _closest: dict = {}
    _stalled: dict = {}
    _spent: dict = {}
    _party_flag: dict = {}


def test_a_clear_flag_is_built_on():
    raiser = Raiser()
    said = raiser.raise_settlement(_flag())
    assert raiser.sent == ["unpack Farm_Exte"]
    assert "unpack Farm_Exte" in said


def test_a_resting_flag_is_waited_out_rather_than_ordered():
    raiser = Raiser(resting=True)
    said = raiser.raise_settlement(_flag())
    assert raiser.sent == []
    assert "cooldown" in said


def test_a_contested_flag_is_waited_out_rather_than_ordered():
    raiser = Raiser(contested=True)
    said = raiser.raise_settlement(_flag())
    assert raiser.sent == []
    assert "standing on it" in said


def test_both_at_once_is_still_just_a_wait():
    """The case the two rules being independent is about."""
    raiser = Raiser(resting=True, contested=True)
    raiser.raise_settlement(_flag())
    assert raiser.sent == []


def test_waiting_never_strikes_the_flag_or_drops_it():
    """The distinction `_strike` draws: this is not going to work *yet*, which is not the same
    as an order that is never going to work. Striking here benches a settlement the bot has
    already paid a battalion to capture."""
    for raiser in (Raiser(resting=True), Raiser(contested=True)):
        raiser.raise_settlement(_flag())
        assert raiser.strikes == []
        assert raiser.dropped == []
        assert raiser.released is False
