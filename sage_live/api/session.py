"""`Session` - selection state, the APM cap, and the loop a policy drives.

- **Selection is tracked**, because several orders only mean something against it (the same
  button-slot order recruits a hero or unpacks an outpost depending on what is selected); a
  selection-dependent order with nothing selected is refused.
- **The APM cap is on by default**, so an agent cannot order faster than a human could.
- **Orders take names or ids.** Names resolve through the session's `NameLookup`, a protocol, so
  this module imports nothing from `sage_ini`.

The waiting helpers distinguish "a game is running" from "a match has started": the main menu runs a
shell map on the same `GameLogic`.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from sage_live.api import orders as _orders
from sage_live.api.camera import ViewLocation
from sage_live.api.observation import (
    GameObject,
    Observation,
    PlayerState,
    SpecialPowerState,
    Vec3,
)
from sage_live.api.orders import CAST_LOCATION, CAST_OBJECT, CAST_SELF
from sage_live.backends.base import Backend
from sage_live.backends.protocol import DiagnosticLog, Handshake
from sage_live.utils import heroes as _heroes
from sage_live.utils.heroes import ReviveLookup
from sage_live.utils.naming import NameLookup, NoNameLookup
from sage_patch.patches.experimental.live_bridge import MAX_ARGS
from sage_replay.replay import Order

__all__ = [
    "BUILD_CONFIRM",
    "DEFAULT_APM_CAP",
    "DEFAULT_CONFIRM",
    "MAX_SELECTION",
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

# How many objects fit in one selection order: the bridge buffer's `MAX_ARGS`, less the
# replace/extend flag. An order over it is refused whole and the previous selection stays, which is
# why `select` splits large selections.
MAX_SELECTION = MAX_ARGS - 1

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
    """A hero order was issued, but this session has no revive lookup to check it against. Attach
    one with `session.revives = Statics.from_root(...)`.
    """


class IllegitimateOrder(Exception):
    """An order the game's own interface would never have offered.

    The engine acts on orders a human could not have clicked - notably a hero from a slot the
    control bar hides (see `sage_live.utils.heroes`). Refusing them separates automation from
    cheating.
    """


class Sent(int):
    """How many orders the backend took, and why the rest did not go.

    An `int`, so `if not sent` works. It also says whether a missing order was **throttled** (held
    back by the APM cap) or **refused** (offered and not taken, which means something is wrong).
    Neither says the game acted on it; that is `Session.confirm`.
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
        fog: bool = False,
        revives: ReviveLookup | None = None,
    ) -> None:
        self.backend = backend
        self.player_index = player_index
        # Whether observations may carry what a real player could not know - an opponent's
        # economy, and what their buildings are making. Applied to every observation this
        # session hands out, so a policy cannot read privileged state by forgetting to filter.
        # **This is not fog**: it removes knowledge, not visibility.
        self.godsight = godsight
        # Whether observations are cut down to what this session's player can see (`godsight` strips
        # fields; this drops objects). Off by default for compatibility; `attach(fog=True)` turns it
        # on.
        self.fog = fog
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
        # The same snapshot as `latest` before the fog filter. Reading it is using privileged
        # information and needs a reason; the one today is deciding the match is over, which a
        # fogged view cannot show.
        self.latest_unfogged: Observation | None = None
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
        """Whether the game is still running. Prefer this as the loop condition: a crash and a
        finished match look the same in an observation.
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
        """Every observation passes through here, so the fog filter cannot be skipped."""
        if obs is None:
            return None
        # Kept before either filter runs, so the one question fog makes undecidable - whether
        # the match is over - still has a snapshot that can answer it. See `latest_unfogged`.
        self.latest_unfogged = obs
        # Fog first: `without_godsight` walks every object, and there is no point stripping
        # production from objects that are about to be hidden anyway. The two are independent -
        # fog decides *which* objects survive, godsight decides what each surviving one says.
        if self.fog:
            obs = obs.under_fog(self.player_index)
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
        """The current snapshot, raising where `poll` would return None before the first
        observation.
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
        """Poll until `predicate` holds and return that observation; raises `TimeoutError` rather
        than returning None.
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
        """Block until a real match is under way (`Observation.in_match`), then re-read the local
        player, which at the menu is the observer seat.
        """
        obs = self.wait_until(lambda o: o.in_match, timeout=timeout, poll=poll)
        self.player_index = obs.local_player
        return obs

    # A consumed order is not an accepted order: game logic silently discards malformed or
    # unaffordable orders after the stream takes them. The confirmations below watch the right side
    # effect for each kind of order (gold, plots vanishing and horde members moving are all
    # misleading).

    def confirm(
        self,
        changed: Callable[[Observation], bool],
        timeout: float = DEFAULT_CONFIRM,
        poll: float = _CONFIRM_POLL,
    ) -> bool:
        """Whether `changed` becomes true of a fresh observation within `timeout` - the non-raising
        sibling of `wait_until`, since "it did nothing" is a real answer. Reads after sleeping,
        since nothing changes before a logic frame runs.
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
        """Issue a production order and confirm the building's queue grew.

        Prefer this to `confirm_spend` for recruits, research and revives: it watches what the order
        was meant to do, which nothing else can forge. Needs a backend reading production state.
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

        The fallback oracle, unsound both ways: gold can be stolen (false positive) or granted in
        bulk (false negative). Use it only for spends with no other visible effect, and treat one
        result as evidence, not proof.
        """
        player = self.observe().player(self.player_index)
        before = 0 if player is None else player.resources
        if not act():
            return False
        return self.confirm(
            lambda o: (p := o.player(self.player_index)) is not None and p.resources < before,
            timeout,
        )

    def confirm_power(
        self,
        act: Callable[[], Sent],
        science: int | str,
        timeout: float = DEFAULT_CONFIRM,
    ) -> bool:
        """Buy a spellbook power and confirm the player now holds its science.

        Points are no oracle: they accrue on their own and a row of the book costs the same. A power
        granted for free confirms too, since the question is whether it can be cast.
        """
        wanted = self.resolve("science", science)
        if not act():
            return False
        return self.confirm(
            lambda o: (p := o.player(self.player_index)) is not None and wanted in p.sciences,
            timeout,
        )

    def confirm_moved(
        self,
        act: Callable[[], Sent],
        object_ids: Sequence[int],
        distance: float = 5.0,
        timeout: float = DEFAULT_CONFIRM,
    ) -> bool:
        """Issue a movement order and confirm at least one of `object_ids` moved at least `distance`
        (a floor, since standing units jostle).
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
        """Issue a build order and confirm something new stands where it was aimed - by position,
        since a `BuildVariations` stand-in never carries the ordered name.
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
        """Drop selected ids that no longer exist. Only against an unfogged observation, where
        absence means dead rather than out of sight.
        """
        if obs.fogged or not self._selection:
            return
        alive = {o.object_id for o in obs.objects}
        self._selection = tuple(i for i in self._selection if i in alive)

    def send(self, *order: Order) -> Sent:
        """Submit orders, subject to the APM cap. Returns a `Sent`; being taken is not being obeyed,
        so use `confirm` to test what an order did.
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
        """Select objects, in as many orders as the command buffer needs.

        A selection over `MAX_SELECTION` is split: the first chunk replaces (or extends) the
        selection and the rest extend it, like shift-click. It stops at the first chunk that fails,
        so a short count means a partial selection; `selection` says which ids landed.
        """
        ids = list(dict.fromkeys(object_ids))
        if not ids:
            # Select-none is a real order the engine acts on, and it carries no ids to chunk.
            return self._select_chunk((), additive)
        accepted = throttled = refused = 0
        for start in range(0, len(ids), MAX_SELECTION):
            sent = self._select_chunk(ids[start : start + MAX_SELECTION], additive or start > 0)
            accepted += int(sent)
            throttled += sent.throttled
            refused += sent.refused
            if not sent:
                break
        return Sent(accepted, throttled=throttled, refused=refused)

    def _select_chunk(self, object_ids: Sequence[int], additive: bool) -> Sent:
        """One selection order, recording only the ids that actually went."""
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
        """An id for `value`, which may already be one. Raises `NoNameLookup` (not
        `UnknownDefinition`) when given a name with no lookup attached.
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

    def toggle_formation(self, horde_id: int) -> Sent:
        """Flip one battalion between its two formations (see `orders.toggle_formation`).

        Sends the horde and requires it selected, as a click does. There is no way to ask for a
        named formation; read the current one first (`Statics.alternate_formation`, or the members'
        `ALTERNATE_FORMATION` model condition).
        """
        self._require_selection()
        return self.send(_orders.toggle_formation(self.player_index, horde_id))

    def attack(self, target_id: int, position: Vec3) -> Sent:
        """`position` is where the target is - the engine records one on every attack order,
        and the caller has it from the observation it picked the target out of."""
        self._require_selection()
        return self.send(_orders.attack_object(self.player_index, target_id, position))

    def recruit(self, template: int | str) -> Sent:
        self._require_selection()
        return self.send(_orders.recruit(self.player_index, self.resolve("thing", template)))

    #
    # Hero recruitment is its own order shape and its own index space, and both are easy to get
    # wrong: the engine takes a `CommandSet` slot number happily and buys a different hero with
    # it. The derivation is in `sage_live.utils.heroes`; what lives here
    # is the part a single observation cannot answer - the list mutates as heroes field and die.

    def _track_heroes(self, obs: Observation) -> None:
        """Follow the revive list across frames: a hero seen alive and now gone has rejoined at the
        tail. Skipped under fog, where gone may mean unseen.
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
        """`hero`'s current position in the revive list - the number an order carries - or None when
        it is not in the list (for example, on the map). Exact unless a hero died after being
        fielded before this session started watching.
        """
        return _heroes.revive_index(
            self.hero_roster(), hero, self._hero_alive, tuple(self._hero_dead)
        )

    def recruit_hero(self, hero: int | str, building_id: int | None = None) -> Sent:
        """Recruit a hero at the selected building.

        `hero` is a template name or a revive-list index; `building_id` defaults to the first
        selected object. The engine's revive gate never checks the button it matched, so it will
        recruit heroes the control bar hides:

        - `godsight=True` allows any hero the building's revive block reaches - the engine's real
          behaviour.
        - `godsight=False` allows only a slot that exists here and is enabled - what a human could
          click.

        An index beyond the building's slots is always refused, since the engine would silently
        discard it. Raises `IllegitimateOrder` rather than returning a falsy `Sent`: it is a policy
        bug, not a game outcome.
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
        """Refuse a hero order the producer cannot serve or a human could not give. The two bounds
        differ by one: the engine counts slots from 0, the control bar's slot 0 is the Ring hero.
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

    def sell(self) -> Sent:
        """Sell the selected structure - see `orders.sell`.

        Takes nothing: the button carries no target and no price, so the engine reads both off
        the selection.
        """
        return self.send(_orders.sell(self.player_index))

    def start_self_repair(self) -> Sent:
        """Start the selected structure repairing itself - see `orders.start_self_repair`.

        Takes nothing: the button carries no cost and no target, so the engine prices it off the
        structure and applies it to whatever is selected.
        """
        return self.send(_orders.start_self_repair(self.player_index))

    def castle_unpack(self) -> Sent:
        """Claim the selected outpost, castle or camp, letting the engine choose what rises (see
        `orders.castle_unpack`).

        Usually not the one you want: a plot in your own base offers explicit buttons, which send
        `unpack`. Ask the plot with `Statics.unpack_buttons(template, upgrades)` rather than its
        static `CommandSet` field, and only send this where it offers a `CASTLE_UNPACK` button - the
        engine accepts the order even where the interface no longer offers it. The plot must already
        be yours (`Observation.obj(id).owner_index`); ownership comes from standing units by the
        flag with no enemy near.
        """
        self._require_selection()
        return self.send(_orders.castle_unpack(self.player_index))

    def unpack(self, template: int | str) -> Sent:
        """Build at the currently selected plot, naming what to build - the common unpack, and what
        a player's own plot buttons send. Needs a selection, which is the location.
        """
        self._require_selection()
        return self.send(_orders.unpack(self.player_index, self.resolve("thing", template)))

    def purchase_power(self, science: int | str) -> Sent:
        """Spend spellbook points on a power from the faction's spell store. Needs no selection.

        Order only what the store sells (`Statics.spell_store(faction)` filtered by
        `PowerButton.enabled_for(held)`); anything else is silently discarded or is cheating.
        Confirm with `confirm_power`, not the points.
        """
        return self.send(
            _orders.purchase_power(self.player_index, self.resolve("science", science))
        )

    def special_powers(self, object_id: int) -> tuple[SpecialPowerState, ...]:
        """Every special power on one object with its recharge and required sciences, or empty where
        the backend cannot say. On a spellbook object, `SpecialPowerState.unlocked_for` says which
        the player has bought.
        """
        reader = getattr(self.backend, "special_powers", None)
        return reader(object_id) if callable(reader) else ()

    def power_button_names(self, object_id: int) -> dict[str, str]:
        """`{special power name -> in-game button text}` for the buttons one object offers, or
        empty where the backend cannot read them. On a spellbook, these are the names its bar
        shows - a power has no display name of its own, only the button that fires it does."""
        reader = getattr(self.backend, "power_button_names", None)
        return reader(object_id) if callable(reader) else {}

    def thing_display_name(self, name: str) -> str:
        """The in-game name of a template, or "" where the backend cannot read one.

        What the game itself shows, localised, for whatever mod and language it runs. Only a
        backend reading the process can answer, so a caller keeps its code name on "".
        """
        reader = getattr(self.backend, "thing_display_name", None)
        return reader(name) if callable(reader) else ""

    def upgrade_display_name(self, name: str) -> str:
        """The in-game name of an upgrade, or "" where the backend cannot resolve one."""
        reader = getattr(self.backend, "upgrade_display_name", None)
        return reader(name) if callable(reader) else ""

    def science_display_name(self, science: int) -> str:
        """The in-game name of a science by id - the name a spellbook power is sold under - or
        "" where the backend cannot prove which entry it is."""
        reader = getattr(self.backend, "science_display_name", None)
        return reader(science) if callable(reader) else ""

    def power_cooldowns(self, object_id: int) -> dict[str, int]:
        """`{power name -> the frame it is next usable on}`, or empty where the backend cannot say.

        Empty means unknown, never "all ready": only a backend reading the process can answer. A
        power is ready when its frame is not after `Observation.frame`.
        """
        reader = getattr(self.backend, "power_cooldowns", None)
        return reader(object_id) if callable(reader) else {}

    #
    # The camera is not an order and is kept apart from them on purpose. It never enters the
    # message stream, no logic reads it, and it spends no APM - a policy that frames what it is
    # doing is not playing faster, it is being watchable. Only a bridge-backed session can move
    # it; every other backend answers None or False rather than pretending.

    def camera(self) -> ViewLocation | None:
        """Where the camera is now, or None where the backend cannot say.

        None is "unknown", never a default placement: a backend that reads a recording or a
        script has no camera, and the client may not have built one yet at a loading screen.
        """
        reader = getattr(self.backend, "capture_camera", None)
        return reader() if callable(reader) else None

    def set_camera(self, location: ViewLocation) -> bool:
        """Place the camera outright. False where the backend cannot move it.

        The whole placement, so nothing is left to be inferred - `look_at` is the form to
        prefer when only part of it is being changed.
        """
        setter = getattr(self.backend, "set_camera", None)
        return bool(setter(location)) if callable(setter) else False

    def look_at(
        self,
        position: Vec3,
        zoom: float | None = None,
        angle: float | None = None,
        pitch: float | None = None,
    ) -> bool:
        """Point the camera at `position`, keeping the rest of the view.

        Moves only the aim where the backend can, since `setLocation` always rewrites the zoom (see
        `BridgeBackend.move_camera`); passing `zoom`, `angle` or `pitch` takes that path
        deliberately. False when the camera could not be moved or read. The move is a jump;
        interpolate by calling repeatedly.
        """
        if zoom is None and angle is None and pitch is None:
            mover = getattr(self.backend, "move_camera", None)
            if callable(mover):
                return bool(mover(position))

        current = self.camera()
        if current is None:
            return False
        return self.set_camera(
            ViewLocation(
                position=position,
                angle=current.angle if angle is None else angle,
                pitch=current.pitch if pitch is None else pitch,
                zoom=current.zoom if zoom is None else zoom,
                extra=current.extra,
            )
        )

    def cast(
        self,
        power: int | str,
        form: str = CAST_LOCATION,
        position: Vec3 | None = None,
        target_id: int = 0,
        source_id: int = 0,
    ) -> Sent:
        """Fire a special power through whichever of the three cast orders it takes.

        `form` comes from the firing button (`CastablePower.form` from `Statics.spell_book`); the
        wrong one is silently discarded, and `CAST_PASSIVE` raises, since a passive power has
        nothing to cast. `source_id` must be the player's `SpellBookMp` object for a spellbook power
        (`Statics.spell_book_object(faction)`); with 0, powers that place something do nothing.
        """
        power_id = self.resolve("power", power)
        if form == CAST_SELF:
            return self.send(_orders.cast_self(self.player_index, power_id, source_id=source_id))
        if form == CAST_OBJECT:
            if position is None:
                raise ValueError("an object-targeted cast carries the target's position too")
            return self.send(
                _orders.cast_at_object(self.player_index, power_id, target_id, position)
            )
        if form == CAST_LOCATION:
            if position is None:
                raise ValueError("a ground-targeted cast needs a position")
            return self.send(
                _orders.cast_at_location(self.player_index, power_id, position, source_id=source_id)
            )
        raise IllegitimateOrder(
            f"{power} is {form}: it fired when it was bought and is not an order. "
            "The control bar shows no button to press for one of these."
        )
