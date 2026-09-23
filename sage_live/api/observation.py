"""The observation model - one immutable snapshot of a running game.

An `Observation` is what a policy sees on one logic frame. It is deliberately small: an object names
its `ThingTemplate`, and static facts about that template come from `sage_ini` (see
`sage_live.utils.statics`). Snapshots are frozen.

Field meanings follow `sage_patch/docs/live-object-model.md` and
`sage_patch/docs/engine-globals.md`.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass, replace

from sage_live.api.shroud import ShroudGrid

__all__ = [
    "NON_PLAYING_FACTIONS",
    "GameObject",
    "Observation",
    "PlayerState",
    "ProductionItem",
    "SpecialPowerState",
    "Vec3",
    "distance",
]

# World-space position. The engine stores it as the translation column of the object's
# Matrix3D, so it is always three floats even for ground units.
Vec3 = tuple[float, float, float]

# Factions the engine runs itself. A player on one of these is never a human seat: `Civilian`
# owns map scenery and the shell map, `Observer` is the replay/spectator seat.
NON_PLAYING_FACTIONS = frozenset({"civilian", "observer"})


# How the engine spells an experience level in the object upgrade set: `Upgrade_ObjectLevel3`.
_LEVEL_PREFIX = "upgrade_objectlevel"


def distance(a: Vec3, b: Vec3) -> float:
    """Straight-line 3D distance between two world positions, in engine units."""
    return math.dist(a, b)


@dataclass(frozen=True)
class PlayerState:
    """One player's economy and holdings.

    `faction` is the engine's `Side` token (`Men`, `Mordor`, ...), the same key `sage_ini` uses. A
    running game always carries engine-managed seats (`Civilian`, `Creeps`, `Observer`, an unnamed
    neutral), so filter on `playing` rather than assume every player is a participant.
    """

    index: int
    name: str
    faction: str
    resources: int
    # Lifetime income, which only ever rises. Kept alongside `resources` because the
    # difference between them is total spend, and neither alone gives that.
    resources_collected: int = 0
    # Spendable spellbook points, not the lifetime total - the two are separate fields on the
    # engine's Player and only this one falls when a power is bought.
    power_points: int = 0
    # The sciences this player holds, by id: bought spellbook powers, the faction's intrinsic
    # science and the view sciences. The only way to tell whether a power was bought (a science is
    # not an upgrade). Ids, because naming them needs an ini load; the id is the one
    # `orders.purchase_power` sends, so test with `names.science("SCIENCE_RebuildMen") in
    # player.sciences`.
    sciences: frozenset[int] = frozenset()
    # Army capacity, as (in use, cap). **`in use` ramps**: a horde does not occupy capacity,
    # its members do, and they spawn one at a time roughly 300ms apart. So a sample taken just
    # after recruiting reads a figure that is still climbing (a 4-member horde at 15 each lands
    # as 60, but not all at once). Compare against the cap, not against a previous sample.
    command_points: tuple[int, int] = (0, 0)
    # Completed PLAYER-scoped upgrades, by code name - faction-wide researches (armoury tech, a
    # marketplace pick). Per-battalion and per-structure upgrades are **not** here: those are
    # OBJECT-scoped and recorded on the object that carries them, in `GameObject.upgrades`.
    upgrades: frozenset[str] = frozenset()
    # PLAYER-scoped upgrades currently being researched, so a policy does not order one twice.
    # Deliberately player-scoped only: the engine sets an object upgrade's in-progress bit here
    # too and then **never clears it**, so including those would report a battalion upgrade as
    # forever pending. An in-flight object upgrade is not observable; its completion is.
    upgrades_in_progress: frozenset[str] = frozenset()
    # The rank ladder that earns spellbook points: lifetime skill points, and the thresholds of
    # the rank the player holds and of the next one (`Rank.SkillPointsNeeded*`, per faction).
    # Each rank-up grants `SciencePurchasePointsGranted` spendable points, so these three are
    # "progress to the next power point". Zero when unread - see `power_point_progress`.
    skill_points: int = 0
    rank_floor: int = 0
    rank_next: int = 0
    # The name the lobby showed - the profile name for a human, the difficulty for an AI - where
    # `name` is the map-side `Player_N` token. Empty when unread.
    display_name: str = ""
    # The faction as the lobby named it - `Gondor`, `Evil Men` - read off the seat's
    # `PlayerTemplate`, where `faction` is the broad side several factions share (`Men`).
    faction_name: str = ""
    # The seat's colour as `0xRRGGBB`, the one the game draws the player's units and minimap
    # dots in. None when the engine was never given one (engine-managed sides are not).
    color: int | None = None
    # The seats this one is allied with, by player index, from the side's `playerAllies`. Empty
    # in a free-for-all, and when the sides list could not be read - so "no allies" is only
    # meaningful where some seat in the match does have them.
    allies: frozenset[int] = frozenset()
    # The engine's own match ledger: money spent by what it bought, and what was built and lost -
    # the figures the score screen is drawn from, kept by the engine as the match runs.
    spent_on_units: int = 0
    spent_on_structures: int = 0
    spent_on_heroes: int = 0
    units_created: int = 0
    units_lost: int = 0
    structures_created: int = 0
    structures_lost: int = 0

    @property
    def power_point_progress(self) -> float | None:
        """How far this player is towards their next rank, in [0, 1), or None when unknown (an
        unread field, or a player at the rank cap).
        """
        span = self.rank_next - self.rank_floor
        if span <= 0 or not (self.rank_floor <= self.skill_points < self.rank_next):
            return None
        return (self.skill_points - self.rank_floor) / span

    @property
    def spent(self) -> int:
        """Total resources spent so far, or 0 before any income is recorded."""
        return max(0, self.resources_collected - self.resources)

    @property
    def playing(self) -> bool:
        """Whether this is a contesting seat rather than one the engine runs itself."""
        return bool(self.faction) and self.faction.lower() not in NON_PLAYING_FACTIONS

    @property
    def command_points_free(self) -> int:
        """Army capacity still available, in command points: the cap (base plus bought bonus) minus
        usage.

        A recruit past the cap is silently discarded; `Session.confirm_queued` reports it directly.
        """
        used, cap = self.command_points
        return max(0, cap - used)

    def can_afford(self, cost: int) -> bool:
        return self.resources >= cost

    def has(self, upgrade: str) -> bool:
        """Whether this player has completed a PLAYER-scoped upgrade, case-insensitively.
        OBJECT-scoped upgrades are on the object (`GameObject.has`).
        """
        lowered = upgrade.lower()
        return any(name.lower() == lowered for name in self.upgrades)

    def researching(self, upgrade: str) -> bool:
        lowered = upgrade.lower()
        return any(name.lower() == lowered for name in self.upgrades_in_progress)

    def as_opponent(self) -> PlayerState:
        """This player as an opponent may see them: who they are (name, faction, colour), and
        nothing a real player could not read.
        """
        return PlayerState(
            index=self.index,
            name=self.name,
            faction=self.faction,
            resources=0,
            display_name=self.display_name,
            faction_name=self.faction_name,
            color=self.color,
            allies=self.allies,
        )

    def to_dict(self) -> dict[str, object]:
        """A JSON-safe view, with sets as lists and the computed properties included."""
        return asdict(self) | {
            "upgrades": sorted(self.upgrades),
            "upgrades_in_progress": sorted(self.upgrades_in_progress),
            "sciences": sorted(self.sciences),
            "allies": sorted(self.allies),
            "spent": self.spent,
            "playing": self.playing,
            "command_points_free": self.command_points_free,
            "power_point_progress": self.power_point_progress,
        }


@dataclass(frozen=True)
class ProductionItem:
    """One entry in a structure's production queue.

    Units and upgrades share the engine's single `ProductionUpdate` queue, told apart by `kind`.
    `name` is resolved by pointer identity against the backend's registries, so an entry this build
    cannot name answers `""` - the entry is still there.
    """

    # "unit", "upgrade" or "revive" - the engine's own kinds, 1, 2 and 3.
    kind: str
    name: str = ""
    # How far along this entry is, 0-100, as the engine itself recomputes it every logic frame
    # from the accumulator that decides completion. Only the head of a queue advances, so every
    # entry behind it reads 0 - and so does a head the engine has not ticked yet.
    percent: float = 0.0

    @property
    def is_upgrade(self) -> bool:
        return self.kind == "upgrade"


@dataclass(frozen=True)
class SpecialPowerState:
    """One special power on an object - a spellbook power or a hero's ability - with the engine's
    own recharge.

    It is ready once `ready_frame` is not in the future. `required_sciences` (by id, compared with
    `PlayerState.sciences`) unlock a spellbook power once all are held; a power asking for none is
    not a spellbook purchase.
    """

    name: str
    ready_frame: int
    required_sciences: frozenset[int] = frozenset()

    def unlocked_for(self, player: PlayerState) -> bool:
        return bool(self.required_sciences) and self.required_sciences <= player.sciences

    def seconds_left(self, frame: int, frames_per_second: float = 5.0) -> float:
        """Seconds of recharge remaining at `frame`, 0 when ready."""
        return max(0.0, (self.ready_frame - frame) / frames_per_second)


@dataclass(frozen=True)
class GameObject:
    """One live object: a unit, structure, plot flag or piece of map scenery.

    `health` is a fraction in [0, 1] and `max_health` the absolute figure; objects without a body
    (wall hubs, farm spots) report `max_health == 0`, meaning "not applicable".

    `owner_index` is the owning player, and is **not** the template's `template_side` - the two
    disagree in both directions, so find your units with `Observation.owned_by`. None means the
    owner could not be resolved, not "nobody".

    `upgrades` holds the OBJECT-scoped upgrades this object has completed (a battalion's blades, a
    structure's level). They appear nowhere else.
    """

    object_id: int
    template_name: str
    template_side: str
    position: Vec3
    angle: float
    health: float
    max_health: float
    owner_index: int | None = None
    # What contains this object (a battalion member's horde), or None. Orders go to objects where
    # this is None; a member ignores them. `Observation.orderable` applies it.
    parent_id: int | None = None
    # The object that produced this one. Unlike `parent_id` it survives the object leaving, and the
    # engine falls back to it. A member with no `parent_id` whose `producer_id` names a live horde
    # is the half-formed state in `sage_patch/docs/horde-formation-orphans.md`.
    producer_id: int | None = None
    # The engine's `ObjectStatus` bits (e.g. `HORDE_MEMBER`, `IS_LEAVING_FACTORY`). Empty when none
    # are set or the name table could not be read.
    status: frozenset[str] = frozenset()
    # Completed OBJECT-scoped upgrades, by code name. A horde and each of its members carry the
    # same set: the engine applies a battalion purchase to the container and to every member,
    # so a consumer counting upgrades across objects will see it once per member.
    upgrades: frozenset[str] = frozenset()
    # The engine's own `ModelConditionFlags` for this object: the states the game itself
    # tracks and animates from - `ACTIVELY_BEING_CONSTRUCTED`, `DAMAGED`, `RUBBLE`,
    # `GARRISONED`, `ATTACKING`, the `DOOR_*` production animations. Empty for an object in no
    # notable state, and empty when the name table could not be read.
    conditions: frozenset[str] = frozenset()
    # What this structure is currently making, in queue order. Empty for anything that is not
    # producing *and* for everything without a production module, which is most objects - use
    # `producing` rather than testing this against None.
    production: tuple[ProductionItem, ...] = ()
    # `KindOf HERO` and `KindOf SPELL_BOOK`, read off the template. The spellbook is the object
    # a player's spellbook powers live on, so it is how `Session.special_powers` finds them.
    is_hero: bool = False
    is_spellbook: bool = False
    # `KindOf STRUCTURE`, and what the template costs to build (`BuildCost`). A battalion carries
    # its own cost on the horde, so an army's value is the cost of what stands on its own.
    is_structure: bool = False
    build_cost: int = 0
    # `KindOf SELECTABLE`: whether a player can click it. A unit a player can own but never
    # select is machinery - the builder a structure spawns to animate its own construction is a
    # copy of the faction's worker, cost and all, with only this flag taken away.
    is_selectable: bool = False
    # The experience tracker's points and level. Read for heroes only, where it is worth the
    # extra read; None for everything else.
    experience: float | None = None
    experience_level: int | None = None
    # How far a structure going up has got, 0-100: the engine's own `Object+0x288`, the figure
    # the build-up animation is drawn from. None for anything not being built - the engine
    # stores -1 there - so a finished structure and a unit both answer None, never 100.
    construction_percent: float | None = None

    @property
    def has_body(self) -> bool:
        """Whether this object has readable hit points - false for map furniture such as wall hubs,
        farm spots and plot flags.
        """
        return self.max_health > 0.0

    @property
    def is_damaged(self) -> bool:
        return self.has_body and self.health < 1.0

    @property
    def under_construction(self) -> bool:
        """Whether this structure is still going up (`ACTIVELY_BEING_CONSTRUCTED`). Health cannot
        tell, since it ramps while building.
        """
        return self.is_in("ACTIVELY_BEING_CONSTRUCTED")

    @property
    def construction_progress(self) -> float | None:
        """How far this structure is through being built, in [0, 1], or None when it is not
        being built. See `construction_percent` for where the figure comes from."""
        if self.construction_percent is None:
            return None
        return self.construction_percent / 100.0

    @property
    def is_rubble(self) -> bool:
        """Whether this structure has been destroyed and stands as wreckage.

        A destroyed camp or castle keep stays on the map at zero health with the `RUBBLE` condition,
        and would otherwise read as the most damaged building on the map. Health alone cannot tell.
        """
        return self.is_in("RUBBLE")

    def is_in(self, condition: str) -> bool:
        """Whether the engine has this `ModelCondition` set, case-insensitively."""
        wanted = condition.lower()
        return any(name.lower() == wanted for name in self.conditions)

    def has_status(self, status: str) -> bool:
        """Whether the engine has this `ObjectStatus` bit set, case-insensitively."""
        wanted = status.lower()
        return any(name.lower() == wanted for name in self.status)

    @property
    def producing(self) -> bool:
        """Whether this structure is training a unit or researching an upgrade. False both when idle
        and when it has no production module - either way, do not send it work.
        """
        return bool(self.production)

    @property
    def hit_points(self) -> float:
        """Current hit points in absolute terms, or 0 for an object with no body."""
        return self.health * self.max_health

    def has(self, upgrade: str) -> bool:
        """Whether this object carries a completed OBJECT-scoped upgrade, case-insensitively. The
        only way to tell an upgraded battalion from a fresh one.
        """
        lowered = upgrade.lower()
        return any(name.lower() == lowered for name in self.upgrades)

    @property
    def veterancy(self) -> int:
        """Experience level, or 0 for an object that has none.

        Read from the highest `Upgrade_ObjectLevelN` in `upgrades`. A fresh battalion is level 1; 0
        means the concept does not apply (scenery, plots).
        """
        best = 0
        for name in self.upgrades:
            lowered = name.lower()
            if lowered.startswith(_LEVEL_PREFIX):
                tail = lowered[len(_LEVEL_PREFIX) :]
                if tail.isdigit():
                    best = max(best, int(tail))
        return best

    def distance_to(self, other: GameObject | Vec3) -> float:
        """Distance to another object or a bare world position, in engine units."""
        return distance(self.position, other.position if isinstance(other, GameObject) else other)

    def to_dict(self) -> dict[str, object]:
        """A JSON-safe view, including the computed fields. See `PlayerState.to_dict`."""
        return asdict(self) | {
            "upgrades": sorted(self.upgrades),
            "has_body": self.has_body,
            "is_damaged": self.is_damaged,
            "hit_points": self.hit_points,
            "veterancy": self.veterancy,
            "producing": self.producing,
            "conditions": sorted(self.conditions),
            "status": sorted(self.status),
            "under_construction": self.under_construction,
        }


@dataclass(frozen=True)
class Observation:
    """A whole-game snapshot at one logic frame.

    Not fog-filtered as produced: training on information a human never had should be a decision.
    `under_fog` makes it; `shroud` is what makes it possible.
    """

    frame: int
    local_player: int
    players: tuple[PlayerState, ...] = ()
    objects: tuple[GameObject, ...] = ()
    # True when the producer applied per-player visibility. False means whole-map.
    fogged: bool = False
    # The engine's visibility grid, when the backend could read one; kept through `under_fog`. Not
    # encoded over the wire, so a decoded observation has `shroud=None`.
    shroud: ShroudGrid | None = None
    # True when this snapshot still carries things a real player could never know. The
    # snapshot says so itself rather than leaving it to the consumer to remember how the
    # session was opened - a saved observation outlives the session that made it.
    godsight: bool = True

    @property
    def in_match(self) -> bool:
        """Whether this is a real match rather than the main menu's shell map.

        The menu is a running game on a real map, so frames advance and objects exist. What it lacks
        is a player: the local player is an observer, where in a match it is a faction.
        """
        player = self.me
        return player is not None and player.playing

    @property
    def me(self) -> PlayerState | None:
        """The local player, or None at the menu and in a replay watched as an observer."""
        return self.player(self.local_player)

    @property
    def mine(self) -> tuple[GameObject, ...]:
        """Objects the local player owns, map furniture included (by ownership, not
        `template_side`).
        """
        return self.owned_by(self.local_player)

    @property
    def opponents(self) -> tuple[PlayerState, ...]:
        """Contesting players other than the local one; engine-run seats (`Civilian`, `Observer`,
        neutral) are excluded.
        """
        return tuple(p for p in self.players if p.playing and p.index != self.local_player)

    def player(self, index: int) -> PlayerState | None:
        for p in self.players:
            if p.index == index:
                return p
        return None

    def obj(self, object_id: int) -> GameObject | None:
        """One object by id, or None if it is gone."""
        for o in self.objects:
            if o.object_id == object_id:
                return o
        return None

    def owned_by(self, index: int) -> tuple[GameObject, ...]:
        return tuple(o for o in self.objects if o.owner_index == index)

    def members(self, object_id: int) -> tuple[GameObject, ...]:
        """The objects contained by `object_id` - a horde's members, a garrison's occupants. The
        inverse of `GameObject.parent_id`.
        """
        return tuple(o for o in self.objects if o.parent_id == object_id)

    def orderable(self, index: int) -> tuple[GameObject, ...]:
        """A player's objects that an order should actually be addressed to.

        Horde members are excluded: their container drives them, and an order to a member is
        recorded and ignored. Uses `parent_id`, so it needs no game files.
        """
        return tuple(o for o in self.owned_by(index) if o.parent_id is None)

    def by_side(self, side: str) -> tuple[GameObject, ...]:
        return tuple(o for o in self.objects if o.template_side == side)

    def find(
        self,
        *,
        template: str | None = None,
        templates: frozenset[str] | set[str] | tuple[str, ...] | None = None,
        owner: int | None = None,
        side: str | None = None,
        upgrade: str | None = None,
        has_body: bool | None = None,
        damaged: bool | None = None,
        near: Vec3 | None = None,
        within: float | None = None,
    ) -> tuple[GameObject, ...]:
        """Objects matching every criterion given, in table order.

        String matching is case-insensitive. `near` with `within` is a radius query; `near` alone
        sorts by distance instead of filtering.
        """
        found = list(self.objects)
        if template is not None:
            lowered = template.lower()
            found = [o for o in found if o.template_name.lower() == lowered]
        if templates is not None:
            wanted = {t.lower() for t in templates}
            found = [o for o in found if o.template_name.lower() in wanted]
        if owner is not None:
            found = [o for o in found if o.owner_index == owner]
        if side is not None:
            lowered = side.lower()
            found = [o for o in found if o.template_side.lower() == lowered]
        if upgrade is not None:
            found = [o for o in found if o.has(upgrade)]
        if has_body is not None:
            found = [o for o in found if o.has_body == has_body]
        if damaged is not None:
            found = [o for o in found if o.is_damaged == damaged]
        if near is not None:
            if within is not None:
                found = [o for o in found if o.distance_to(near) <= within]
            found.sort(key=lambda o: o.distance_to(near))
        return tuple(found)

    def nearest(self, position: Vec3, **criteria: object) -> GameObject | None:
        """The closest object to `position` matching `find`'s criteria, or None. Passing `near` as
        well is an error, since `position` is the anchor.
        """
        if "near" in criteria:
            raise TypeError("nearest() already anchors on `position`; drop `near`")
        found = self.find(near=position, **criteria)  # type: ignore[arg-type]
        return found[0] if found else None

    def census(self, objects: tuple[GameObject, ...] | None = None) -> Counter[str]:
        """`{template name -> count}` for the whole map, or for the objects given (e.g. the result
        of `find`).
        """
        return Counter(o.template_name for o in (self.objects if objects is None else objects))

    def under_fog(self, viewer: int | None = None, keep_own: bool = True) -> Observation:
        """The same snapshot with everything `viewer` cannot currently see removed.

        This is visibility; `without_godsight` is knowledge. An object is kept when the viewer's
        shroud at its position is `CLEAR`. `keep_own` also keeps everything the viewer owns (a
        garrisoned unit reports its holder's position, which may not be on a revealed cell).

        Returns the snapshot unchanged, with `fogged` still False, when there is no grid or the
        match has fog off; check `fogged` if it matters.

        Limits: only the object's centre is tested, so a large structure appears slightly later than
        in the game. There is no memory of things seen before: the engine's grid has no
        explored-but-not-visible state, so a consumer that wants scouting memory keeps it across
        frames. See `sage_live.backends.shroud`.
        """
        seat = self.local_player if viewer is None else viewer
        if self.shroud is None or not self.shroud.fog_enabled:
            return self
        grid = self.shroud
        return replace(
            self,
            fogged=True,
            objects=tuple(
                o
                for o in self.objects
                if (keep_own and o.owner_index == seat) or grid.visible(o.position, seat)
            ),
        )

    def without_godsight(self, viewer: int | None = None) -> Observation:
        """The same snapshot with everything a real player could not know removed.

        Unlike fog, this is about what is knowable at all. It removes what opponents are producing
        and their economy (resources, spellbook and command points, researched upgrades); an
        opponent keeps only what the interface shows. Every object stays in the list, and `fogged`
        is not set.

        Allies are treated as opponents, since alliances are not read yet - the conservative
        direction.
        """
        seat = self.local_player if viewer is None else viewer
        return replace(
            self,
            godsight=False,
            players=tuple(p if p.index == seat else p.as_opponent() for p in self.players),
            objects=tuple(
                o if o.owner_index == seat else replace(o, production=()) for o in self.objects
            ),
        )

    def to_dict(self) -> dict[str, object]:
        """A JSON-safe view of the whole snapshot: the dataclass fields plus their derived
        properties, so a new field appears here automatically.
        """
        return {
            "frame": self.frame,
            "local_player": self.local_player,
            "fogged": self.fogged,
            "godsight": self.godsight,
            "in_match": self.in_match,
            "players": [p.to_dict() for p in self.players],
            "objects": [o.to_dict() for o in self.objects],
        }
