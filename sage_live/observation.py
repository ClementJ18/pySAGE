"""The observation model - one immutable snapshot of a running game.

An `Observation` is what a policy sees on a single logic frame. It is deliberately small:
an object names its `ThingTemplate`, and every static fact about that template - cost,
armour, weapons, build time, command points - is already available from `sage_ini` and
`sage_mods.edain`. The consumer joins against data it holds, rather than the engine
re-sending it every frame.

Snapshots are frozen: a policy that mutates last frame's world is a bug class this rules
out entirely.

Field semantics follow the live layouts recorded in
`sage_patch/docs/live-object-model.md` and `sage_patch/docs/engine-globals.md`.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass

__all__ = [
    "NON_PLAYING_FACTIONS",
    "GameObject",
    "Observation",
    "PlayerState",
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
    """Straight-line distance between two world positions, in engine units.

    Full 3D rather than ground plane. Height differences are small on most maps but real on
    the ones with cliffs, and a range check that ignores Z quietly overestimates there.
    """
    return math.dist(a, b)


@dataclass(frozen=True)
class PlayerState:
    """One player's economy and holdings.

    `faction` is the engine's `Side` token (`Men`, `Mordor`, `Wild`, ...), which is the same
    key `sage_ini` uses, so it joins directly against the faction tree. A running game always
    carries engine-managed sides - `Civilian`, `Creeps`, `Observer`, and an unnamed neutral
    slot - so a consumer must filter rather than assume every player is a participant.
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

    @property
    def spent(self) -> int:
        """Total resources spent so far, or 0 before any income is recorded."""
        return max(0, self.resources_collected - self.resources)

    @property
    def playing(self) -> bool:
        """Whether this is a contesting seat rather than one the engine runs itself.

        Every match carries `Civilian`, `Observer` and an unnamed neutral slot alongside the
        real players, so anything counting opponents has to filter on this.
        """
        return bool(self.faction) and self.faction.lower() not in NON_PLAYING_FACTIONS

    @property
    def command_points_free(self) -> int:
        """Army capacity still available. Never negative: a grant can push usage past the cap."""
        used, cap = self.command_points
        return max(0, cap - used)

    def can_afford(self, cost: int) -> bool:
        return self.resources >= cost

    def has(self, upgrade: str) -> bool:
        """Whether this player has completed a PLAYER-scoped upgrade, case-insensitively.

        Only faction-wide researches are here. A battalion's forged blades are OBJECT-scoped
        and answer on the object - see `GameObject.has`.
        """
        lowered = upgrade.lower()
        return any(name.lower() == lowered for name in self.upgrades)

    def researching(self, upgrade: str) -> bool:
        lowered = upgrade.lower()
        return any(name.lower() == lowered for name in self.upgrades_in_progress)

    def to_dict(self) -> dict[str, object]:
        """A JSON-safe view, including the computed fields.

        `dataclasses.asdict` alone is not enough twice over: it leaves the upgrade sets as
        `frozenset`, which `json.dumps` cannot encode, and it drops the derived properties,
        which are the ones worth reading.
        """
        return asdict(self) | {
            "upgrades": sorted(self.upgrades),
            "upgrades_in_progress": sorted(self.upgrades_in_progress),
            "spent": self.spent,
            "playing": self.playing,
            "command_points_free": self.command_points_free,
        }


@dataclass(frozen=True)
class GameObject:
    """One live object: a unit, structure, plot flag or piece of map scenery.

    `health` is a fraction in [0, 1]; `max_health` carries the absolute figure. Not every
    object has a body - inert map markers such as wall hubs and farm spots have none - and
    those report `max_health == 0`, which means "not applicable" rather than "dead".

    `owner_index` is the *owning player*, and it is **not** derivable from the template:
    `template_side` is the template's declared `Side`, and the two really do disagree. Measured
    in one live match: the creeps owned 18 objects whose Side is `Neutral`, and the local player
    owned one whose Side is `Civilian`. Filtering by Side to find "my units" therefore both
    misses things you own and claims things you do not - use `Observation.owned_by`.

    None means the owner could not be resolved (an object on a script team), not "nobody".

    `upgrades` carries the OBJECT-scoped upgrades this object has completed - a battalion's
    forged blades, a structure's level 2. These are invisible in every other field: they do not
    change `template_name`, and they are not in `PlayerState.upgrades`, which holds only the
    faction-wide researches. A battalion that has bought heavy armour differs from one that has
    not by its `max_health` and by this set, and by nothing else.
    """

    object_id: int
    template_name: str
    template_side: str
    position: Vec3
    angle: float
    health: float
    max_health: float
    owner_index: int | None = None
    # Horde membership. The engine links members through the parent container, and this is
    # information the replay order stream cannot express, since its arguments are opaque
    # runtime handles.
    parent_id: int | None = None
    # Completed OBJECT-scoped upgrades, by code name. A horde and each of its members carry the
    # same set: the engine applies a battalion purchase to the container and to every member,
    # so a consumer counting upgrades across objects will see it once per member.
    upgrades: frozenset[str] = frozenset()

    @property
    def has_body(self) -> bool:
        """Whether this object has readable hit points at all.

        The practical use is telling a real object from map furniture: wall hubs, farm spots
        and plot flags have no body, and a policy counting "things I own" wants them out.
        """
        return self.max_health > 0.0

    @property
    def is_damaged(self) -> bool:
        return self.has_body and self.health < 1.0

    @property
    def hit_points(self) -> float:
        """Current hit points in absolute terms, or 0 for an object with no body."""
        return self.health * self.max_health

    def has(self, upgrade: str) -> bool:
        """Whether this object carries a completed OBJECT-scoped upgrade, case-insensitively.

        The only way to ask. An upgraded battalion is not renamed and does not appear in the
        player's upgrade set, so without this it is indistinguishable from an unupgraded one
        except by a hit-point figure the caller would have to know in advance.
        """
        lowered = upgrade.lower()
        return any(name.lower() == lowered for name in self.upgrades)

    @property
    def veterancy(self) -> int:
        """Experience level, or 0 for an object that has none.

        The engine records a level as an ordinary OBJECT-scoped upgrade named
        `Upgrade_ObjectLevelN`, so it needs no separate field: it is already in `upgrades`, and
        this reads the highest N present. A fresh battalion carries `Upgrade_ObjectLevel1`, so
        1 is the normal floor for anything that gains experience at all, and 0 means the
        concept does not apply - map scenery, plot flags, foundations.
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
        }


@dataclass(frozen=True)
class Observation:
    """A whole-game snapshot at one logic frame.

    Nothing here is fog-filtered. The engine knows what each player can see, but that filter
    belongs on the game side and must be applied deliberately - training a policy on
    information a human never had should be a decision, not an accident.
    """

    frame: int
    local_player: int
    players: tuple[PlayerState, ...] = ()
    objects: tuple[GameObject, ...] = ()
    # True when the producer applied per-player visibility. False means whole-map.
    fogged: bool = False

    @property
    def in_match(self) -> bool:
        """Whether this is a real match, as opposed to the main menu's shell map.

        **The menu is a running game.** BFME2 renders its main menu over a "shell map" - an
        actual map, simulated by the same `GameLogic`, with a looping camera script. So the
        frame counter advances, objects exist, and every naive "is a game running?" check says
        yes while the player is still sitting in the menu.

        What the shell map does not have is a player: its roster is `PlyrCivilian` and
        `ReplayObserver`, and the local player *is* the observer. A real match makes the local
        player a faction. That is the difference this tests, rather than counting objects or
        watching the frame counter, because it is the one that says something meaningful.
        """
        player = self.me
        return player is not None and player.playing

    @property
    def me(self) -> PlayerState | None:
        """The local player, or None at the menu and in a replay watched as an observer."""
        return self.player(self.local_player)

    @property
    def mine(self) -> tuple[GameObject, ...]:
        """Objects the local player owns, map furniture included.

        Ownership, not `template_side` - the two genuinely disagree in both directions, so
        filtering by faction both misses objects you own and claims objects you do not.
        """
        return self.owned_by(self.local_player)

    @property
    def opponents(self) -> tuple[PlayerState, ...]:
        """Contesting players other than the local one.

        Filters out `Civilian`, `Observer` and the unnamed neutral slot, which are seats the
        engine runs itself and which a policy treating them as enemies will attack.
        """
        return tuple(p for p in self.players if p.playing and p.index != self.local_player)

    def player(self, index: int) -> PlayerState | None:
        for p in self.players:
            if p.index == index:
                return p
        return None

    def obj(self, object_id: int) -> GameObject | None:
        """One object by id, or None if it is gone.

        Ids are the currency of the order stream, and an object a policy targeted last frame
        may have died since - so this answers None rather than raising.
        """
        for o in self.objects:
            if o.object_id == object_id:
                return o
        return None

    def owned_by(self, index: int) -> tuple[GameObject, ...]:
        return tuple(o for o in self.objects if o.owner_index == index)

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

        One place for the filtering every consumer writes by hand, and keyword-only so a call
        reads as its own documentation. All string matching is case-insensitive, because ini
        identifiers are and a policy should not break on a capital a modder changed.

        `near` with `within` is a radius query; `near` alone sorts by distance instead of
        filtering, which is how you ask for "the closest few".
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
        """The closest object to `position` matching `find`'s criteria, or None.

        Passing `near` here is a mistake worth catching rather than silently overriding:
        `position` already is the anchor.
        """
        if "near" in criteria:
            raise TypeError("nearest() already anchors on `position`; drop `near`")
        found = self.find(near=position, **criteria)  # type: ignore[arg-type]
        return found[0] if found else None

    def census(self, objects: tuple[GameObject, ...] | None = None) -> Counter[str]:
        """`{template name -> count}`, most common first when iterated via `most_common`.

        Defaults to the whole map; pass the result of `find` to count a subset. This is the
        cheapest honest summary of an army, given that horde membership is not yet readable
        and every battalion therefore appears as its individual members.
        """
        return Counter(o.template_name for o in (self.objects if objects is None else objects))

    def to_dict(self) -> dict[str, object]:
        """A JSON-safe view of the whole snapshot.

        The schema is the field names of these three dataclasses plus their derived
        properties, so adding a field to the model adds it here with no further work - which
        is the point: an exporter that has to be updated by hand is one that silently omits
        the newest thing you added.
        """
        return {
            "frame": self.frame,
            "local_player": self.local_player,
            "fogged": self.fogged,
            "in_match": self.in_match,
            "players": [p.to_dict() for p in self.players],
            "objects": [o.to_dict() for o in self.objects],
        }
