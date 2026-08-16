"""Buying a passive is two orders, and the bot was only ever sending one.

A spell store's purchase button may carry a `CommandTrigger` naming a second button, and the
engine fires that one as well - so the click a player makes is a purchase *and* a cast. For the
passive powers that second half is where the entire effect lives: the science grants nothing on
its own, and the bonus aura is `StartsActive = No`, waiting on an upgrade only the triggered
`SpecialPower` hands out.

Sending the purchase alone therefore fails in the worst available way. The science is genuinely
held, so the purchase confirms, the store shows the power as bought, and `power_options` never
offers it again - while no battalion ever gets the bonus. Measured live: a whole match holding
`SCIENCE_FormationenGondors` with the formation aura never once active.
"""

from __future__ import annotations

from types import SimpleNamespace

from sage_live.api.orders import CAST_SELF
from sage_live.utils.statics import PowerButton
from sage_mods.edain.bot.powers import Powers

BOOK = 4242


def _power(science: str, triggers: str | None = None) -> PowerButton:
    return PowerButton(
        command_slot=1, button=f"Command_Purchase{science}", science=science, triggers=triggers
    )


class Store(Powers):
    """`apply_purchase` over a stub session, recording what it cast."""

    apply_purchase = Powers.apply_purchase

    def __init__(self, sends: bool = True) -> None:
        self._sends = sends
        self.cast: list[tuple] = []
        self.reported: list[tuple[str, bool]] = []
        self.session = SimpleNamespace(cast=self._cast)

    def _cast(self, power, form, source_id=0, **rest):
        self.cast.append((power, form, source_id))
        return self._sends

    def spellbook_id(self) -> int:
        return BOOK

    def _issue(self, label, act):
        return act()

    def _report(self, label, ok, good, bad) -> bool:
        self.reported.append((label, ok))
        return ok


def test_a_passive_fires_the_power_its_button_triggers() -> None:
    """The fix. The purchase is already sent; this is the half that was missing."""
    store = Store()
    said = store.apply_purchase(_power("SCIENCE_FormationenGondors", "SpellBookFormationenGondors"))
    assert store.cast == [("SpellBookFormationenGondors", CAST_SELF, BOOK)]
    assert said is not None and "SpellBookFormationenGondors" in said


def test_a_power_with_no_trigger_sends_nothing() -> None:
    """**Only the passives need this.** An active power is bought here and cast by `stage_cast`
    on its own recharge; firing it now would spend the first cast on nothing."""
    store = Store()
    assert store.apply_purchase(_power("SCIENCE_RebuildMen")) is None
    assert store.cast == []


def test_the_spellbook_is_named_as_the_source() -> None:
    """A book power cast with the source slot left at 0 is taken by the stream and discarded by
    logic in silence - which here would look exactly like the bug being fixed."""
    store = Store()
    store.apply_purchase(_power("SCIENCE_X", "SpellBookX"))
    assert store.cast[0][2] == BOOK


def test_a_refused_trigger_is_reported_rather_than_swallowed() -> None:
    """The science is bought and the points are gone, so nothing can retry this. Saying so is
    the whole remedy available, and it is what stops a silent no-op."""
    store = Store(sends=False)
    said = store.apply_purchase(_power("SCIENCE_X", "SpellBookX"))
    assert said is not None and "REFUSED" in said
    assert ("power trigger", False) in store.reported
