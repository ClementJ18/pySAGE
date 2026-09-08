"""The running half: bind what a scenario declared to what the engine created, and assert on it.

A :class:`~sage_test.scenario.Handle` names an object that did not exist when the test was
written. Once the match is up, every declared object *does* exist - at the position the scenario
put it, carrying the template it named - so binding is a lookup rather than a guess: the live
object of that template nearest that position, within a tolerance tight enough that two
placements cannot be confused.

That is deliberately not clever. The alternative is deriving the runtime `ObjectId` from the
placement's index in the map's object list, which is exact but couples a test to how the engine
numbers pre-placed objects; position matching only needs the scenario to not stack two objects of
the same template on the same spot, which is a rule a test can see it is following.

`Match` is a thin façade: everything it does not define itself is `sage_live.Session`, which
already has the ordering, the confirmations and the observation queries.
"""

from __future__ import annotations

import math
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sage_live.api.observation import GameObject, Observation
from sage_live.api.session import Session
from sage_test.scenario import Handle, Scenario

__all__ = [
    "DEFAULT_TOLERANCE",
    "BindingError",
    "Match",
    "bind_handles",
    "match_from",
]

#: How far a live object may be from where the scenario placed it and still be it. Generous
#: enough for the engine settling a unit onto terrain, far tighter than anything a test would
#: reasonably place two same-template objects apart.
DEFAULT_TOLERANCE = 60.0


class BindingError(LookupError):
    """A declared object could not be found in the running match."""


def _distance_2d(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """Ground distance. The z the scenario declares is not the z the engine puts the object at -
    it drops them onto the terrain - so height is not part of the match."""
    return math.hypot(a[0] - b[0], a[1] - b[1])


def bind_handles(
    scenario: Scenario,
    observation: Observation,
    tolerance: float = DEFAULT_TOLERANCE,
) -> dict[int, int]:
    """`{handle index: ObjectId}` for every placement, or raise saying which one is missing.

    Each live object is claimed at most once, so two placements of the same template near each
    other bind to two different objects rather than both to whichever is nearest.
    """
    claimed: set[int] = set()
    bindings: dict[int, int] = {}
    for index, placement in enumerate(scenario.placements):
        candidates = [
            obj
            for obj in observation.objects
            if obj.object_id not in claimed
            and obj.template_name.lower() == placement.template.lower()
            and _distance_2d(obj.position, placement.at) <= tolerance
        ]
        if not candidates:
            raise BindingError(
                f"placement {index} ({placement.template} at {placement.at}) matched no live "
                f"object within {tolerance} - it may have died, or never been created"
            )
        nearest = min(candidates, key=lambda obj: _distance_2d(obj.position, placement.at))
        claimed.add(nearest.object_id)
        bindings[index] = nearest.object_id
    return bindings


@dataclass
class Match:
    """A running scenario. `session` is the live game; `bindings` ties handles to object ids."""

    scenario: Scenario
    session: Session
    bindings: dict[int, int]

    def id_of(self, handle: Handle) -> int:
        """The live `ObjectId` a handle bound to."""
        try:
            return self.bindings[handle.index]
        except KeyError:  # pragma: no cover - only reachable with a handle from another scenario
            raise BindingError(f"{handle.template} is not bound in this match") from None

    def __getitem__(self, handle: Handle) -> GameObject:
        """The declared object as it is **now** - re-observed, not cached.

        Re-observing on every access is what makes `match[hall].upgrades` mean "the upgrades it
        has at this moment"; a cached object would silently answer with the state it had when
        the match started, which is the state a test is usually trying to prove has changed.
        """
        object_id = self.id_of(handle)
        found = self.session.observe().obj(object_id)
        if found is None:
            raise BindingError(
                f"{handle.template} (id {object_id}) is no longer in the game - it died, "
                "or was consumed by something that replaced it"
            )
        return found

    def wait_until(self, predicate, timeout: float = 30.0, poll: float = 0.25) -> Observation:
        """Advance until `predicate(match)` holds, or raise. The predicate takes the match, so it
        can index handles - which is what a test wants to wait on."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            observation = self.session.observe()
            if predicate(self):
                return observation
            time.sleep(poll)
        raise TimeoutError(f"condition still false after {timeout}s")

    def cast_and_confirm(
        self,
        power: str,
        caster_id: int,
        *,
        form: str,
        position: tuple[float, float, float] | None = None,
        target_id: int = 0,
        source_id: int | None = None,
        timeout: float = 30.0,
        retry_every: float = 2.0,
    ) -> int:
        """Cast `power` from `caster_id` and return the recharge it went onto, or raise.

        **A cast is not reliably accepted the first time and the engine says nothing when it is
        not.** An order sent before whatever settles after a selection has settled is discarded in
        silence: no recharge, no effect, and the bridge still reports that the hook consumed it.
        How long that takes is not a constant - it is about a second on a map loaded from `.big`
        archives and several on an uncompiled `-mod` tree, because everything is slower there.

        So this retries rather than sleeping on a guess, and confirms against the **recharge**: a
        special power the engine accepts and executes goes onto its `ReloadTime`, and the caster's
        own module clock is what `power_cooldowns` reads. That is the only signal here that
        distinguishes "the order landed" from "the order vanished".

        The caster is selected once, up front; re-selecting per attempt would be the obvious thing
        to do and is wrong, because a selection order is itself subject to the same delay.
        """
        self.session.select([caster_id])
        before = self.session.power_cooldowns(caster_id).get(power)
        deadline = time.monotonic() + timeout
        attempts = 0
        while time.monotonic() < deadline:
            attempts += 1
            self.session.cast(
                power,
                form=form,
                position=position,
                target_id=target_id,
                source_id=caster_id if source_id is None else source_id,
            )
            until = min(time.monotonic() + retry_every, deadline)
            while time.monotonic() < until:
                now = self.session.power_cooldowns(caster_id).get(power)
                if now and now != before:
                    return now
                time.sleep(0.1)
        raise TimeoutError(
            f"{power} never went on recharge after {attempts} attempt(s) in {timeout}s - "
            "the ability is paused, out of range, or the cast is malformed"
        )

    def __getattr__(self, name: str):
        """Everything else is the `sage_live.Session` underneath."""
        return getattr(self.session, name)


@contextmanager
def match_from(
    scenario: Scenario,
    session: Session,
    tolerance: float = DEFAULT_TOLERANCE,
) -> Iterator[Match]:
    """Bind `scenario` against an already-running `session` and yield the match.

    Kept separate from launching so that a test can attach to a game somebody started by hand -
    which is how a scenario gets debugged when it does not behave.
    """
    yield Match(scenario, session, bind_handles(scenario, session.observe(), tolerance))
