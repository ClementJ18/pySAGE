"""`Session` - selection state, the APM cap, and the loop a policy actually drives.

Three things here are not conveniences.

**Selection is mandatory state.** Several orders are meaningless without it: the engine's
"press command-button slot N" order is byte-identical whether it recruits a fortress hero or
unpacks an outpost, and only the current selection disambiguates. A session that does not
track selection cannot issue those orders correctly, so it tracks selection and refuses a
selection-dependent order when nothing is selected.

**The APM cap is on by default.** An unthrottled agent emits orders at a rate no human could
and that the engine was never tested against. `sage_replay`'s own statistics give a realistic
distribution to calibrate against.

**Orders take names or ids.** A name is resolved through the session's `NameLookup`, which is
a protocol rather than a concrete class precisely so this module keeps importing nothing from
`sage_ini` - `sage_live.attach` fits the engine's own live registry, and
`sage_live.resolve.Resolver` fits an ini load, and neither is a dependency here.

The waiting helpers matter more than they look. The main menu is a *running game* - the shell
map ticks the same `GameLogic` - so "a game is running" is not the same question as "a match
has started", and every consumer was answering it by hand.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from sage_live import orders as _orders
from sage_live.backend import Backend
from sage_live.naming import NameLookup, NoNameLookup
from sage_live.observation import GameObject, Observation, PlayerState, Vec3
from sage_live.protocol import Diagnostic, Handshake
from sage_replay.replay import Order

__all__ = ["DEFAULT_APM_CAP", "APMLimiter", "NoSelection", "Session"]

# Roughly the ceiling of human play in this engine; well above a typical ladder player, so
# it throttles only agents that were never going to be plausible.
DEFAULT_APM_CAP = 300

# How long `wait_for_match` gives a launch before giving up. Generous: a cold start has to
# load the engine, the mod's ini tree and the map, and on a slow disk that is most of a minute.
DEFAULT_WAIT = 120.0


class NoSelection(Exception):
    """A selection-dependent order was issued with an empty selection."""


@dataclass
class APMLimiter:
    """A sliding-window rate limit in actions per minute. `cap <= 0` disables it."""

    cap: int = DEFAULT_APM_CAP
    clock: Callable[[], float] = time.monotonic
    _stamps: list[float] = field(default_factory=list)

    def allow(self, n: int = 1) -> int:
        """How many of `n` actions may be issued now, recording those that may."""
        if self.cap <= 0:
            return n
        now = self.clock()
        cutoff = now - 60.0
        self._stamps = [t for t in self._stamps if t > cutoff]
        room = max(0, self.cap - len(self._stamps))
        granted = min(n, room)
        self._stamps.extend([now] * granted)
        return granted

    @property
    def current_apm(self) -> int:
        cutoff = self.clock() - 60.0
        return sum(1 for t in self._stamps if t > cutoff)


class Session:
    """A connected game, with the state a policy needs between frames."""

    def __init__(
        self,
        backend: Backend,
        player_index: int = 0,
        apm_cap: int = DEFAULT_APM_CAP,
        clock: Callable[[], float] = time.monotonic,
        names: NameLookup | None = None,
    ) -> None:
        self.backend = backend
        self.player_index = player_index
        self.clock = clock
        self.limiter = APMLimiter(apm_cap, clock)
        # Name to id for the four order id spaces. Assignable after construction so a caller
        # can attach an ini-backed resolver to a session that started with the live registry.
        self.names = names
        self.handshake: Handshake | None = None
        self.latest: Observation | None = None
        self._selection: tuple[int, ...] = ()
        self._throttled = 0

    def __enter__(self) -> Session:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def selection(self) -> tuple[int, ...]:
        return self._selection

    @property
    def connected(self) -> bool:
        return self.handshake is not None

    @property
    def throttled(self) -> int:
        """Orders dropped by the APM cap so far."""
        return self._throttled

    @property
    def diagnostics(self) -> Sequence[Diagnostic]:
        return self.backend.diagnostics

    def connect(self) -> Handshake:
        """Perform the handshake, or return the one already agreed.

        Idempotent so that `attach`, which connects to read the local player's seat, and a
        `with` block, which connects on entry, do not gate one behind the other.
        """
        if self.handshake is None:
            self.handshake = self.backend.connect()
        return self.handshake

    def close(self) -> None:
        self.backend.close()
        self.handshake = None

    def poll(self) -> Observation | None:
        obs = self.backend.poll()
        if obs is not None:
            self.latest = obs
            self._prune_selection(obs)
        return obs

    def step(self, timeout: float | None = None) -> Observation | None:
        obs = self.backend.step(timeout)
        if obs is not None:
            self.latest = obs
            self._prune_selection(obs)
        return obs

    def observe(self) -> Observation:
        """The current snapshot, raising rather than answering None.

        `poll` returns None before the first observation arrives, which is the honest answer
        for a loop but a nuisance for the far more common "read the game and act on it". This
        is the same call with that one case turned into an error.
        """
        obs = self.poll()
        if obs is None:
            raise LookupError(
                "no observation available - the backend has produced none yet"
                + ("" if self.connected else " (this session is not connected)")
            )
        return obs

    @property
    def me(self) -> PlayerState | None:
        """This session's own player, from the latest observation."""
        return None if self.latest is None else self.latest.player(self.player_index)

    @property
    def mine(self) -> tuple[GameObject, ...]:
        """Objects this session's player owns, from the latest observation."""
        return () if self.latest is None else self.latest.owned_by(self.player_index)

    @property
    def frame(self) -> int:
        """The logic frame of the latest observation, or 0 before the first."""
        return 0 if self.latest is None else self.latest.frame

    def wait_until(
        self,
        predicate: Callable[[Observation], bool],
        timeout: float = DEFAULT_WAIT,
        poll: float = 0.25,
    ) -> Observation:
        """Poll until `predicate` holds, and return that observation.

        Raises `TimeoutError` rather than returning None: a caller that waited for a state and
        did not get it has nothing useful to do with a null, and a silent skip here shows up
        much later as an order issued into the menu.
        """
        deadline = self.clock() + timeout
        while True:
            obs = self.poll()
            if obs is not None and predicate(obs):
                return obs
            if self.clock() >= deadline:
                raise TimeoutError(f"the game did not reach the expected state within {timeout}s")
            time.sleep(poll)

    def wait_for_match(self, timeout: float = DEFAULT_WAIT, poll: float = 0.25) -> Observation:
        """Block until a real match is under way, and adopt its local player.

        **The menu is a running game.** BFME2 draws its main menu over a shell map simulated by
        the same `GameLogic`, so the frame counter advances and objects exist while the player
        is still choosing a faction. `Observation.in_match` is the test that means something -
        whether the local player is a faction rather than the observer seat.

        The seat is re-read on arrival: at the menu the local player *is* the observer, so a
        session that fixed its index before the match started fixed it on the wrong player.
        """
        obs = self.wait_until(lambda o: o.in_match, timeout=timeout, poll=poll)
        self.player_index = obs.local_player
        return obs

    def _prune_selection(self, obs: Observation) -> None:
        """Drop selected ids that no longer exist, so selection cannot go stale.

        Only prunes against an unfogged observation: under fog, an object's absence means
        "not visible", not "dead", and pruning on that would silently discard a live
        selection the moment it left vision.
        """
        if obs.fogged or not self._selection:
            return
        alive = {o.object_id for o in obs.objects}
        self._selection = tuple(i for i in self._selection if i in alive)

    def send(self, *order: Order) -> int:
        """Submit orders, subject to the APM cap. Returns how many were accepted."""
        batch = list(order)
        granted = self.limiter.allow(len(batch))
        self._throttled += len(batch) - granted
        if not granted:
            return 0
        return self.backend.send(batch[:granted])

    def select(self, object_ids: Sequence[int], additive: bool = False) -> int:
        sent = self.send(_orders.select(self.player_index, object_ids, additive))
        if sent:
            self._selection = (
                tuple(dict.fromkeys((*self._selection, *object_ids)))
                if additive
                else tuple(object_ids)
            )
        return sent

    def deselect(self) -> int:
        sent = self.send(_orders.deselect(self.player_index))
        if sent:
            self._selection = ()
        return sent

    def _require_selection(self) -> None:
        if not self._selection:
            raise NoSelection("this order acts on the current selection, which is empty")

    def resolve(self, space: str, value: int | str) -> int:
        """An id for `value`, which may already be one.

        Raises `NoNameLookup` when a name is given and this session has no lookup - explicitly
        distinct from `UnknownDefinition`, so a caller is not sent hunting for a typo in a name
        that was never going to be looked up.
        """
        if isinstance(value, int):
            return value
        if self.names is None:
            raise NoNameLookup(
                f"cannot resolve the {space} name {value!r}: this session has no name lookup. "
                "Attach one with `session.names = ...`, or pass an id."
            )
        resolver: Callable[[str], int] = getattr(self.names, space)
        return resolver(value)

    def move(self, position: Vec3) -> int:
        self._require_selection()
        return self.send(_orders.move(self.player_index, position))

    def attack_move(self, position: Vec3) -> int:
        """Move to a point, engaging what is met on the way. Not yet live-verified - see
        `orders.attack_move`."""
        self._require_selection()
        return self.send(_orders.attack_move(self.player_index, position))

    def stop(self) -> int:
        self._require_selection()
        return self.send(_orders.stop(self.player_index))

    def attack(self, target_id: int, position: Vec3) -> int:
        """`position` is where the target is - the engine records one on every attack order,
        and the caller has it from the observation it picked the target out of."""
        self._require_selection()
        return self.send(_orders.attack_object(self.player_index, target_id, position))

    def recruit(self, template: int | str) -> int:
        self._require_selection()
        return self.send(_orders.recruit(self.player_index, self.resolve("thing", template)))

    def research(self, upgrade: int | str, building_id: int) -> int:
        """Buy an upgrade at `building_id`, which must be named - see `orders.research`.

        Selecting the building is not enough and 0 is not a wildcard, so there is nothing for
        `_require_selection` to check here: the building is an argument, not implied state.
        """
        return self.send(
            _orders.research(self.player_index, self.resolve("upgrade", upgrade), building_id)
        )

    def build(self, template: int | str, position: Vec3, angle: float = 0.0) -> int:
        return self.send(
            _orders.build_at(self.player_index, self.resolve("thing", template), position, angle)
        )

    def unpack(self, template: int | str) -> int:
        """Build at the currently selected plot, with no placement interface.

        Selection-dependent in the strong sense: the plot *is* the location, so this carries no
        position and an empty selection has nothing to build on. Not yet live-verified - see
        `orders.unpack`.
        """
        self._require_selection()
        return self.send(_orders.unpack(self.player_index, self.resolve("thing", template)))

    def purchase_power(self, science: int | str) -> int:
        return self.send(
            _orders.purchase_power(self.player_index, self.resolve("science", science))
        )
