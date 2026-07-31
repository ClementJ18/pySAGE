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

from sage_live import heroes as _heroes
from sage_live import orders as _orders
from sage_live.backend import Backend
from sage_live.heroes import ReviveLookup
from sage_live.naming import NameLookup, NoNameLookup
from sage_live.observation import GameObject, Observation, PlayerState, Vec3
from sage_live.protocol import DiagnosticLog, Handshake
from sage_replay.replay import Order

__all__ = [
    "BUILD_CONFIRM",
    "DEFAULT_APM_CAP",
    "DEFAULT_CONFIRM",
    "APMLimiter",
    "IllegitimateOrder",
    "NoReviveLookup",
    "NoSelection",
    "Sent",
    "Session",
]

# Roughly the ceiling of human play in this engine; well above a typical ladder player, so
# it throttles only agents that were never going to be plausible.
DEFAULT_APM_CAP = 300

# How long `wait_for_match` gives a launch before giving up. Generous: a cold start has to
# load the engine, the mod's ini tree and the map, and on a slow disk that is most of a minute.
DEFAULT_WAIT = 120.0

# How long to give the engine to act on an order before deciding it did nothing. Comfortably
# more than a logic frame, and short enough that a decision cycle stays responsive.
DEFAULT_CONFIRM = 1.5
# Builds get longer: the order goes through the placement interface and the foundation has to
# be laid before anything is observable, which is more than one frame's work.
BUILD_CONFIRM = 4.0
# How often to re-read while confirming. Below a logic frame is wasted work.
_CONFIRM_POLL = 0.15


class NoSelection(Exception):
    """A selection-dependent order was issued with an empty selection."""


class NoReviveLookup(RuntimeError):
    """A hero order was issued, but this session has nothing to resolve the revive system with.

    Deliberately not optional. A revive index means nothing without the roster it indexes, and
    an unchecked one is the single easiest way to buy the wrong hero at full price - which is
    exactly what happened before the index space was identified. Attach a lookup with
    `session.revives = Statics.from_root(...)`.
    """


class IllegitimateOrder(Exception):
    """An order the game's own interface would never have offered.

    The engine does not ask where an order came from, so it will act on plenty of things a
    human could not have clicked. Refusing those is what separates automation from cheating,
    and hero recruitment is where it matters most: the engine's own revive gate matches a slot
    by counting and never reads the button, so a well-formed order can recruit a hero the
    control bar hides. See `sage_live.heroes` and `sage_patch/patches/ai_revive_gate.py`.
    """


class Sent(int):
    """How many orders the backend took, and why the rest did not go.

    An `int`, because that is what every caller already does with the answer - `if not sent`,
    a count in a log - and widening it would break them for no gain. What it adds is the
    distinction between the two ways an order fails to leave: **throttled** means the APM cap
    held it back and it was never offered to the game, **refused** means the backend was
    offered it and would not take it. Only the second one means something is wrong, and a
    caller guessing between them from `session.throttled` gets it wrong the moment a cap has
    ever fired.

    Note that neither says the game *acted* on the order. Nothing here does; that is what
    `Session.confirm` is for.
    """

    throttled: int
    refused: int

    def __new__(cls, accepted: int, throttled: int = 0, refused: int = 0) -> Sent:
        self = super().__new__(cls, accepted)
        self.throttled = throttled
        self.refused = refused
        return self

    @property
    def reason(self) -> str:
        """Why nothing went, for a log line. Empty when something did."""
        if self:
            return ""
        if self.throttled:
            return f"the APM cap held back {self.throttled}"
        if self.refused:
            return f"the backend refused {self.refused}"
        return "nothing was sent"


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
        godsight: bool = True,
        revives: ReviveLookup | None = None,
    ) -> None:
        self.backend = backend
        self.player_index = player_index
        # Whether observations may carry what a real player could not know - an opponent's
        # economy, and what their buildings are making. Applied to every observation this
        # session hands out, so a policy cannot read privileged state by forgetting to filter.
        # **This is not fog**: it removes knowledge, not visibility, and `Observation.fogged`
        # stays False until the shroud is read.
        self.godsight = godsight
        self.clock = clock
        self.limiter = APMLimiter(apm_cap, clock)
        # Name to id for the four order id spaces. Assignable after construction so a caller
        # can attach an ini-backed resolver to a session that started with the live registry.
        self.names = names
        # The revive system's static half - hero rosters and a producer's REVIVE slots. Needs
        # an ini load, so it is injected rather than imported; `Statics` satisfies it.
        self.revives = revives
        self.handshake: Handshake | None = None
        self.latest: Observation | None = None
        self._selection: tuple[int, ...] = ()
        self._throttled = 0
        # The revive list is not the roster: a fielded hero leaves it and a killed one rejoins
        # at the tail. Neither is readable from one frame, so they are accumulated here.
        self._roster: tuple[str, ...] | None = None
        self._hero_alive: frozenset[str] = frozenset()
        self._hero_dead: list[str] = []

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
    def alive(self) -> bool:
        """Whether the game is still running.

        The loop condition to prefer over anything derived from an observation. A crashed
        game and a finished match produce the *same* empty observation - no objects, no local
        player - so a policy that infers the end from what it can see reports a crash as a
        result. This asks the process instead.
        """
        return self.backend.alive

    @property
    def throttled(self) -> int:
        """Orders dropped by the APM cap so far."""
        return self._throttled

    @property
    def diagnostics(self) -> DiagnosticLog:
        """The backend's diagnostics - bounded, logged, and drainable; see `DiagnosticLog`."""
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

    def _received(self, obs: Observation | None) -> Observation | None:
        """The one place every observation passes through, so the filter cannot be skipped.

        `observe`, `poll`, `step`, every `confirm_*` helper and `wait_until` all read through
        here. A filter applied at some call sites and not others is worse than none: it makes
        privileged data look absent right up until the one path that leaks it.
        """
        if obs is None:
            return None
        if not self.godsight:
            obs = obs.without_godsight(self.player_index)
        self.latest = obs
        self._prune_selection(obs)
        self._track_heroes(obs)
        return obs

    def poll(self) -> Observation | None:
        return self._received(self.backend.poll())

    def step(self, timeout: float | None = None) -> Observation | None:
        return self._received(self.backend.step(timeout))

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

    # ---- did the order actually do anything? -------------------------------------------
    #
    # **A consumed order is not an accepted order.** Game logic discards a malformed or
    # unaffordable order *after* the message stream has taken it, and reports nothing at all:
    # no error, no diagnostic, and the order still reaches the replay. So `send` returning 1
    # means the game received it, not that the game did it.
    #
    # The only honest confirmations are the side effects, and there are three. They live here
    # rather than in each consumer because every consumer needs them and the obvious version of
    # each is wrong: gold is not the oracle for a build (the balance moves for other reasons in
    # the same window), a plot vanishing is not the oracle either (building on a plot does not
    # consume it), and a horde member moving is not the oracle for a move order (the members
    # are dragged by the container's AI whatever you ordered).

    def confirm(
        self,
        changed: Callable[[Observation], bool],
        timeout: float = DEFAULT_CONFIRM,
        poll: float = _CONFIRM_POLL,
    ) -> bool:
        """Whether `changed` becomes true of a fresh observation within `timeout`.

        The non-raising sibling of `wait_until`: waiting for a state you expect is an error
        when it does not arrive, but confirming an order is a *question*, and "it did nothing"
        is a real answer that a policy acts on rather than crashes over.

        Reads after sleeping rather than before: nothing can have changed until a logic frame
        has run, so an immediate first read only ever measures the previous state.
        """
        deadline = self.clock() + timeout
        while True:
            time.sleep(poll)
            obs = self.poll()
            if obs is not None and changed(obs):
                return True
            if self.clock() >= deadline:
                return False

    def confirm_queued(
        self,
        act: Callable[[], Sent],
        building_id: int,
        timeout: float = DEFAULT_CONFIRM,
    ) -> bool:
        """Issue a production order, and confirm the building's queue actually grew.

        **Prefer this to `confirm_spend` for anything that enters a queue** - a recruit, a
        research, a hero revive. It watches the thing the order was supposed to do rather than
        a side effect, so nothing else in the match can forge the answer.

        The queue is the honest signal precisely where money is not: gold moves for reasons
        that have nothing to do with this order, in both directions (see `confirm_spend`).
        Needs a backend reading production state; with `read_production=False` no queue is
        visible and this can only ever answer False.
        """
        building = self.observe().obj(building_id)
        before = 0 if building is None else len(building.production)
        if not act():
            return False
        return self.confirm(
            lambda o: (found := o.obj(building_id)) is not None and len(found.production) > before,
            timeout,
        )

    def confirm_spend(self, act: Callable[[], Sent], timeout: float = DEFAULT_CONFIRM) -> bool:
        """Issue an order that must cost resources, and confirm the balance fell.

        **This oracle is unsound in both directions, and it is the fallback rather than the
        first choice.** Gold is a shared, contested number:

        - an enemy ability can *steal* it, so a fall can appear with no spend of yours - a
          false positive;
        - an ability can *grant* 500-1000 at once, so a real spend can hide under a net rise -
          a false negative.

        Neither is rare enough to ignore in a real match. Use `confirm_queued` for anything
        that enters a production queue, which is most of what costs money; keep this for
        spends with no other visible effect, and read a single result as evidence rather than
        proof.
        """
        player = self.observe().player(self.player_index)
        before = 0 if player is None else player.resources
        if not act():
            return False
        return self.confirm(
            lambda o: (p := o.player(self.player_index)) is not None and p.resources < before,
            timeout,
        )

    def confirm_moved(
        self,
        act: Callable[[], Sent],
        object_ids: Sequence[int],
        distance: float = 5.0,
        timeout: float = DEFAULT_CONFIRM,
    ) -> bool:
        """Issue a movement order, and confirm at least one of `object_ids` moved.

        A move costs nothing, so the resource oracle says nothing about it and positions are
        all there is. `distance` is a floor rather than a target: units jostle and settle by a
        unit or two while standing still, and this must not read that as obedience.
        """
        origin = {o.object_id: o.position for o in self.observe().objects}
        watched = {i: origin[i] for i in object_ids if i in origin}
        if not act():
            return False

        def moved(obs: Observation) -> bool:
            return any(
                (found := obs.obj(i)) is not None and found.distance_to(was) > distance
                for i, was in watched.items()
            )

        return self.confirm(moved, timeout)

    def confirm_appeared(
        self,
        act: Callable[[], Sent],
        near: Vec3 | None = None,
        within: float = 60.0,
        timeout: float = BUILD_CONFIRM,
    ) -> bool:
        """Issue a build order, and confirm something new is standing where it was aimed.

        The only direct evidence a structure went up, and the only one immune to
        `BuildVariations` - ordering a `GondorWohnhaus` places a `GondorWohnhaus01`, so nothing
        that matches on the ordered name will ever see it. This asks what *appeared*, not what
        it is called.
        """
        before = {o.object_id for o in self.observe().objects}
        if not act():
            return False

        def appeared(obs: Observation) -> bool:
            return any(
                o.object_id not in before
                and o.owner_index == self.player_index
                and (near is None or o.distance_to(near) < within)
                for o in obs.objects
            )

        return self.confirm(appeared, timeout)

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

    def send(self, *order: Order) -> Sent:
        """Submit orders, subject to the APM cap.

        The count of orders the backend took, carrying why the rest did not go - see `Sent`.
        Being taken is not being obeyed: game logic discards a malformed or unaffordable order
        *after* the stream has accepted it, and reports nothing. `confirm` is the only honest
        test of what an order did.
        """
        batch = list(order)
        granted = self.limiter.allow(len(batch))
        throttled = len(batch) - granted
        self._throttled += throttled
        if not granted:
            return Sent(0, throttled=throttled)
        accepted = self.backend.send(batch[:granted])
        return Sent(accepted, throttled=throttled, refused=granted - accepted)

    def select(self, object_ids: Sequence[int], additive: bool = False) -> Sent:
        sent = self.send(_orders.select(self.player_index, object_ids, additive))
        if sent:
            self._selection = (
                tuple(dict.fromkeys((*self._selection, *object_ids)))
                if additive
                else tuple(object_ids)
            )
        return sent

    def deselect(self) -> Sent:
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

    def move(self, position: Vec3) -> Sent:
        self._require_selection()
        return self.send(_orders.move(self.player_index, position))

    def attack_move(self, position: Vec3) -> Sent:
        """Move to a point, engaging what is met on the way. Not yet live-verified - see
        `orders.attack_move`."""
        self._require_selection()
        return self.send(_orders.attack_move(self.player_index, position))

    def stop(self) -> Sent:
        self._require_selection()
        return self.send(_orders.stop(self.player_index))

    def attack(self, target_id: int, position: Vec3) -> Sent:
        """`position` is where the target is - the engine records one on every attack order,
        and the caller has it from the observation it picked the target out of."""
        self._require_selection()
        return self.send(_orders.attack_object(self.player_index, target_id, position))

    def recruit(self, template: int | str) -> Sent:
        self._require_selection()
        return self.send(_orders.recruit(self.player_index, self.resolve("thing", template)))

    # ---- heroes ---------------------------------------------------------------------------
    #
    # Hero recruitment is its own order shape and its own index space, and both were got wrong
    # before they were identified: the engine takes a `CommandSet` slot number happily and buys
    # a different hero with it. The derivation is in `sage_live.heroes`; what lives here is the
    # part a single observation cannot answer - the list mutates as heroes field and die.

    def _track_heroes(self, obs: Observation) -> None:
        """Follow the revive list's two mutations across frames.

        A hero standing on the map has left the list; one that was standing there and is gone
        has rejoined it at the tail. Only the second needs history, and only this sees enough
        frames to have any.

        Skipped under fog, for the same reason `_prune_selection` is: an object's absence means
        "not visible" there, and reading that as a death would send the next recruit to a
        position that has not actually moved.
        """
        if self.revives is None or obs.fogged:
            return
        roster = self.hero_roster()
        if not roster:
            return
        wanted = {h.lower() for h in roster}
        alive = frozenset(
            o.template_name.lower()
            for o in obs.owned_by(self.player_index)
            if o.template_name.lower() in wanted
        )
        for hero in self._hero_alive - alive:
            if hero not in self._hero_dead:
                self._hero_dead.append(hero)
        for hero in alive:
            if hero in self._hero_dead:
                self._hero_dead.remove(hero)
        self._hero_alive = alive

    def hero_roster(self) -> tuple[str, ...]:
        """This player's `BuildableHeroesMP`, cached. Empty without a revive lookup."""
        if self._roster is None:
            player = None if self.latest is None else self.latest.player(self.player_index)
            if self.revives is None or player is None:
                return ()
            self._roster = self.revives.hero_roster(player.faction)
        return self._roster

    def revive_index(self, hero: str) -> int | None:
        """`hero`'s current position in the revive list - the number an order carries.

        None when the hero is not in the list, which is a real state rather than an error: a
        hero already on the map has left it, and ordering the position it used to hold would
        recruit whoever slid into that place.

        **Accurate for a hero that has never been fielded, which is the ordinary case.** The
        one part that needs history is a hero killed after fielding: it rejoins at the tail, in
        death order, and this can only know that from frames it has seen. A session that
        started mid-match has not seen them.
        """
        return _heroes.revive_index(
            self.hero_roster(), hero, self._hero_alive, tuple(self._hero_dead)
        )

    def recruit_hero(self, hero: int | str, building_id: int | None = None) -> Sent:
        """Recruit a hero at the selected building.

        `hero` is a template name resolved against the current revive list, or an index into
        that list if you have already worked it out. `building_id` defaults to the first
        selected object, which is the building the order will act on anyway.

        **What this refuses, and why it depends on `godsight`.** The engine's own revive gate
        matches a slot by counting REVIVE buttons and never reads the button it matched, so it
        will happily recruit a hero whose slot the control bar hides - that is how a
        `GondorBarracks` was made to produce Imrahil, a hero it does not offer. Nothing in the
        game reports that as an error.

        - `godsight=True`: any hero from any building carrying a revive block, which is the
          engine's real behaviour and the useful one for exploration and for measuring what the
          gate actually allows.
        - `godsight=False`: only a hero whose slot at *this* building exists and is **enabled**
          - its `NeededUpgrade` satisfied by the player's or the building's own upgrades. That
          is the set a human's control bar would have shown, so a policy under it is playing
          the game rather than exploiting a known-broken gate.

        Either way an index the producer's slot block cannot reach is refused outright: the
        engine consumes that order and discards it in silence, which is indistinguishable from
        a malformed one.

        Raises `IllegitimateOrder` rather than returning a falsy `Sent`, because an order the
        interface would never have offered is a bug in the policy, not a game outcome the way
        "the queue was full" is.
        """
        self._require_selection()
        if building_id is None:
            building_id = self._selection[0]
        if isinstance(hero, int):
            index = hero
        else:
            found = self.revive_index(hero)
            if found is None:
                raise LookupError(
                    f"{hero!r} is not in this player's revive list - it is either not a hero of "
                    "this faction, or already on the map"
                )
            index = found
        self._check_revive(index, building_id)
        return self.send(_orders.recruit_hero(self.player_index, index))

    def _check_revive(self, index: int, building_id: int) -> None:
        """Refuse a hero order the producer cannot serve, or that a human could not have given.

        The two bounds differ by one on purpose. The engine's gate counts every REVIVE button
        from zero and accepts when the count reaches the index, so it needs `index + 1` slots.
        The control bar's mapping is offset - position 0 is the Ring-hero slot - so the slot a
        human would have clicked for `index` is at position `index + 1`, and needs one more.
        """
        if self.revives is None:
            raise NoReviveLookup(
                f"cannot check a hero recruit at building {building_id}: this session has no "
                "revive lookup. Attach one with `session.revives = Statics.from_root(...)`."
            )
        # The observation already in hand, not a fresh one: this is a check on an order about
        # to go out, and polling here would both cost a read and move the state the caller
        # decided against out from under them.
        obs = self.latest if self.latest is not None else self.observe()
        building = obs.obj(building_id)
        if building is None:
            raise IllegitimateOrder(f"object {building_id} is not in the current observation")
        template = building.template_name
        slots = self.revives.revive_slots(template)
        if not slots:
            raise IllegitimateOrder(
                f"{template} has no REVIVE buttons at all, so it cannot recruit a hero"
            )
        if index < 0 or index >= len(slots):
            raise IllegitimateOrder(
                f"{template} carries {len(slots)} REVIVE slots, which cannot reach revive "
                f"index {index} - the engine would consume this order and discard it"
            )
        if self.godsight:
            return

        slot = next((s for s in slots if s.roster_index == index), None)
        if slot is None:
            raise IllegitimateOrder(
                f"{template} has no revive slot serving index {index}; without godsight only "
                "the heroes this building actually offers may be recruited"
            )
        player = obs.player(self.player_index)
        held = {u.lower() for u in (player.upgrades if player is not None else frozenset())}
        held |= {u.lower() for u in building.upgrades}
        if not slot.enabled_for(held):
            raise IllegitimateOrder(
                f"{slot.button} on {template} is disabled - it needs one of "
                f"{', '.join(slot.needed_upgrades)}, which neither the player nor the building "
                "holds. The control bar would not have shown this hero."
            )

    def research(self, upgrade: int | str, building_id: int) -> Sent:
        """Buy an upgrade at `building_id`, which must be named - see `orders.research`.

        Selecting the building is not enough and 0 is not a wildcard, so there is nothing for
        `_require_selection` to check here: the building is an argument, not implied state.
        """
        return self.send(
            _orders.research(self.player_index, self.resolve("upgrade", upgrade), building_id)
        )

    def build(self, template: int | str, position: Vec3, angle: float = 0.0) -> Sent:
        return self.send(
            _orders.build_at(self.player_index, self.resolve("thing", template), position, angle)
        )

    def castle_unpack(self) -> Sent:
        """Unpack the selected castle plot, camp or settlement flag into whatever it becomes.

        Takes no template: the engine reads that off the target's own `CastleBehavior`, for the
        issuing player's faction. This is what the game's own button sends, and it is the
        verified path - see `orders.castle_unpack`.

        **The plot must already be yours.** An order against a plot you do not own is consumed
        and discarded in silence, which is indistinguishable from a malformed one.
        `Observation.obj(id).owner_index` is the check - the engine's own answer.

        Ownership is taken by standing your units by the flag with no enemy near it. The
        distances (about 10 to claim, about 50 for an enemy to deny) are aims to move toward
        rather than thresholds to test: treat them as approximate and let ownership itself be
        the signal.

        **Only send this to a target whose `CommandSet` actually offers a `CASTLE_UNPACK`
        button.** The engine will act on an order the interface would never have presented, so
        an agent that skips that check is not playing the game a human plays - it is cheating.
        The check is a static one: `Statics.field(template, "CommandSet")`, then the buttons of
        that set. See the note at the top of `orders`.
        """
        self._require_selection()
        return self.send(_orders.castle_unpack(self.player_index))

    def unpack(self, template: int | str) -> Sent:
        """Build at the currently selected plot, naming what to build.

        Selection-dependent in the strong sense: the plot *is* the location, so this carries no
        position and an empty selection has nothing to build on. **Prefer `castle_unpack`** -
        this is the rarer explicit-template order and is still unverified; see `orders.unpack`.
        """
        self._require_selection()
        return self.send(_orders.unpack(self.player_index, self.resolve("thing", template)))

    def purchase_power(self, science: int | str) -> Sent:
        return self.send(
            _orders.purchase_power(self.player_index, self.resolve("science", science))
        )
