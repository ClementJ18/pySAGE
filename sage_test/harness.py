"""The running half: bind what a scenario declared to what the engine created, and assert on it.

A `Handle` names an object that did not exist when the test was
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

import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, field

from sage_live.api.observation import GameObject, Observation, ground_distance
from sage_live.api.session import Session
from sage_live.backends import game_speed
from sage_live.backends.game_speed import FAST_FORWARD
from sage_live.backends.live_patch import LivePatchError, WindowsProcess
from sage_test.scenario import Handle, Scenario
from sage_test.scripts import ScriptControl

__all__ = [
    "DEFAULT_TOLERANCE",
    "FAST_SLICE_S",
    "BindingError",
    "Match",
    "ObjectRef",
    "bind_handles",
    "match_from",
    "recharged",
]

#: How far a live object may be from where the scenario placed it and still be it. Generous
#: enough for the engine settling a unit onto terrain, far tighter than anything a test would
#: reasonably place two same-template objects apart.
DEFAULT_TOLERANCE = 60.0

#: How long `Match.harass` runs fast between orders. Long enough that fast-forwarding pays for
#: itself, short enough that attackers whose target walked off are pointed at it again.
FAST_SLICE_S = 3.0

#: Something a `Match` can name an object by: a declared handle, or a live id.
ObjectRef = Handle | int


class BindingError(LookupError):
    """A declared object could not be found in the running match."""


def recharged(before: int | None, now: int | None, frame: int) -> bool:
    """Whether a power's ready frame says it was cast since `before` was read.

    A cast moves the ready frame into the future. A frame that changed but is not ahead of
    `frame` is a recharge being rescaled or cleared, not a cast - which is what an AI's cast
    looks like from outside, since nothing else announces it.
    """
    return now is not None and now != before and now > frame


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
        if not placement.bind:
            continue
        candidates = [
            obj
            for obj in observation.objects
            if obj.object_id not in claimed
            and obj.template_name.lower() == placement.template.lower()
            and ground_distance(obj.position, placement.live_at) <= tolerance
        ]
        if not candidates:
            raise BindingError(
                f"placement {index} ({placement.template} at {placement.live_at}) matched no live "
                f"object within {tolerance} - it may have died, or never been created"
            )
        nearest = min(candidates, key=lambda obj: ground_distance(obj.position, placement.live_at))
        claimed.add(nearest.object_id)
        bindings[index] = nearest.object_id
    return bindings


@dataclass
class Match:
    """A running scenario. `session` is the live game; `bindings` ties handles to object ids."""

    scenario: Scenario
    session: Session
    bindings: dict[int, int]
    #: The game's process id, for what the session does not reach - the frame cap `fast` raises.
    #: None for a match built around a session nobody launched here.
    pid: int | None = None
    _scripts: ScriptControl | None = field(default=None, init=False, repr=False)
    _process: WindowsProcess | None = field(default=None, init=False, repr=False)

    @property
    def scripts(self) -> ScriptControl:
        """The scenario's map scripts in the game: `fire`, `wait_fired`, `run`, `count`, ...

        Opened on first use, over the process handle `close` releases."""
        if self._scripts is None:
            if self.pid is None:
                raise RuntimeError("this match has no process id, so its scripts cannot be reached")
            self._process = WindowsProcess(self.pid)
            self._scripts = ScriptControl(self._process)
        return self._scripts

    def close(self) -> None:
        """Release the process handle `scripts` opened. The game itself is the runner's to end."""
        if self._process is not None:
            self._process.close()
        self._process = None
        self._scripts = None

    @contextmanager
    def fast(self, multiplier: int = FAST_FORWARD) -> Iterator[None]:
        """Run the game `multiplier` times faster for the block, then at normal speed again.

        For the waits - a timer running out, a unit walking - where a test only watches. It raises
        the frame cap the main loop paces itself to (`sage_live.backends.game_speed`), so every
        duration is still counted in logic frames and the simulation does exactly what it would
        have; only the wall clock shrinks. Normal speed comes back on the way out whatever the
        block did, before the test goes on to give orders at a human pace. A machine that cannot
        draw that many frames runs as fast as it can rather than `multiplier` times."""
        if self.pid is None:
            raise RuntimeError("this match has no process id, so its speed cannot be changed")
        process = WindowsProcess(self.pid)
        try:
            game_speed.set_speed(process, multiplier)
            yield
        finally:
            try:
                game_speed.set_speed(process, 1)
            except LivePatchError:
                pass  # the game is gone, and with it the speed
            process.close()

    def _id(self, ref: ObjectRef) -> int:
        return ref if isinstance(ref, int) else self.id_of(ref)

    def alive(self, refs: Iterable[ObjectRef]) -> list[int]:
        """The ids of `refs` still in the game, in the order given."""
        observation = self.session.observe()
        ids = (self._id(ref) for ref in refs)
        return [object_id for object_id in ids if observation.obj(object_id) is not None]

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
        reselect: bool = False,
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

        The caster is selected once, up front, because a selection order is itself subject to the
        same delay. Except right after the launch: a selection sent in a match's first frames is
        dropped as well, and every attempt after it then has no caster. `reselect` selects again
        before each attempt, with a second for it to settle.
        """
        self.session.select([caster_id])
        before = self.session.power_cooldowns(caster_id).get(power)
        deadline = time.monotonic() + timeout
        attempts = 0
        while time.monotonic() < deadline:
            attempts += 1
            if reselect and attempts > 1:
                self.session.select([caster_id])
                time.sleep(1.0)
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

    def toggle_until(
        self,
        ref: ObjectRef,
        power: str,
        condition: str,
        timeout: float = 30.0,
    ) -> bool:
        """Cast the self-targeted `power` on an object until it shows `condition`; whether it did.

        For a toggle whose effect is a model condition - a hero's mounted state - where the power's
        recharge says nothing and casting it again flips it back. So it is cast once per attempt,
        and the condition checked before each one.
        """
        object_id = self._id(ref)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = self.session.observe().obj(object_id)
            if found is not None and found.is_in(condition):
                return True
            self.session.select([object_id])
            time.sleep(1.0)
            self.session.cast(power, form="self", source_id=object_id)
            time.sleep(3.0)
        return False

    def harass(
        self,
        attackers: Iterable[ObjectRef] | Callable[[Observation], Iterable[ObjectRef]],
        target: ObjectRef | Callable[[Observation], GameObject | None],
        until: Callable[[Observation], bool],
        timeout: float,
        *,
        fast: bool = True,
        slice_s: float = FAST_SLICE_S,
        poll: float = 0.1,
    ) -> str:
        """Send `attackers` at `target` until `until` holds of an observation; return why it
        stopped, "" when `until` held.

        How a test makes an AI react - cast a power, swing a weapon - when it only does so under
        attack. The order is re-sent every `slice_s`, because a target walks and attackers drift
        onto whatever else is in reach; between orders the game runs fast (`Match.fast`) unless
        `fast` is off, which is what a check needing every frame - a weapon slot in use - wants.

        Either side may be a function of the observation, for a target chosen as the fight goes
        (the weakest hero) or attackers released as it goes (a reserve).
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            observation = self.session.observe()
            if callable(target):
                aimed = target(observation)
            else:
                aimed = observation.obj(self._id(target))
            if aimed is None:
                return "the target is gone"
            sent = attackers(observation) if callable(attackers) else attackers
            standing = self.alive(sent)
            if not standing:
                return "the attackers are gone"
            self.session.select(standing)
            self.session.attack(aimed.object_id, aimed.position)
            pace: AbstractContextManager[None] = self.fast() if fast else nullcontext()
            with pace:
                slice_end = min(time.monotonic() + slice_s, deadline)
                while time.monotonic() < slice_end:
                    if until(self.session.observe()):
                        return ""
                    time.sleep(poll)
        return f"nothing within {timeout:.0f}s"

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
