"""What a system test declares: the seats, and the objects on the map before anything happens.

A scenario is **static**. Everything here is compiled into a `.map` before the engine starts,
because that is the only way to put a level-7 hero next to a finished building without asking the
engine to do something a player could not: `objectExperienceLevel`, `objectUpgradesList` and
`originalOwner` are ordinary WorldBuilder object properties, so a scenario is legal map data
rather than an injected cheat.

That is why declaration and execution are separate phases, and why `place` hands back a
:class:`Handle` rather than anything you can act on. The handle names an object that does not
exist yet; :mod:`sage_test.harness` binds it to a live `ObjectId` once the match is up.

    scenario = Scenario("edict", seats=(Seat.human(faction=3), Seat.easy_ai(faction=10)))
    hero = scenario.place("AngmarMorgomir", at=(400, 400), level=7)
    hall = scenario.place("AngmarHallOfKingsMen", at=(520, 400))

Nothing here imports `sage_map`, `sage_live` or anything that needs a game on disk, so a
scenario can be built, inspected and tested with none of that present.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

__all__ = [
    "Handle",
    "Placement",
    "Scenario",
    "Seat",
]

Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class Seat:
    """One player slot: who they are, and where they start.

    `faction` is an index into the loaded mod's `playertemplate.ini` order, which is what the
    engine's `GameSlot` carries and what `command-line-skirmish` writes - not a name, because the
    ordering is the mod's and no fixed enum survives a mod change.

    `start_position` is load-bearing beyond where the camera opens: a seat binds to the map-side
    player `Player_<start_position + 1>`, and that is the player a scenario's objects must be
    owned by for the seat to own them. :attr:`map_player` is that name.
    """

    faction: int
    start_position: int = 0
    colour: int = 0
    team: int = 0
    #: False means the local human - the seat a test drives. True means an easy AI.
    ai: bool = False

    @classmethod
    def human(cls, faction: int, start_position: int = 0, **kwargs) -> Seat:
        return cls(faction=faction, start_position=start_position, ai=False, **kwargs)

    @classmethod
    def easy_ai(cls, faction: int, start_position: int = 1, **kwargs) -> Seat:
        return cls(faction=faction, start_position=start_position, ai=True, **kwargs)

    @property
    def map_player(self) -> str:
        """The map-side player this seat binds to, which follows the start position."""
        return f"Player_{self.start_position + 1}"

    @property
    def map_team(self) -> str:
        """The qualified owner an object of this seat's is written under."""
        return f"{self.map_player}/team{self.map_player}"


@dataclass(frozen=True)
class Placement:
    """One object on the map before the match starts.

    `seat` indexes into the scenario's seats; `None` leaves the object neutral, which is what
    scenery and unclaimed plots are. Everything else mirrors a WorldBuilder object property, and
    a field left at its default is simply not written, so a placement costs only what it states.
    """

    template: str
    at: Vec3
    seat: int | None = 0
    angle: float = 0.0
    #: `objectExperienceLevel`. A hero placed at level 7 is level 7 from frame one.
    level: int | None = None
    #: `objectUpgradesList` - upgrades the object already owns when the match begins.
    upgrades: tuple[str, ...] = ()
    #: `objectInitialHealth`, as a percentage the way the map format stores it.
    health: int = 100
    #: `objectName`, the WorldBuilder label. Scripts address objects by this; tests do not need
    #: it, but a scenario that wants to be openable in WorldBuilder does.
    name: str | None = None


@dataclass(frozen=True)
class Handle:
    """A reference to something a scenario declared, before it exists.

    Compared and hashed by identity of position in the scenario, so a handle stays valid across
    a scenario being copied, and cannot be confused with an `ObjectId` - which is the point. The
    binding to a live object happens once, in the harness, against the position the object was
    placed at.
    """

    index: int
    placement: Placement

    @property
    def template(self) -> str:
        return self.placement.template

    @property
    def at(self) -> Vec3:
        return self.placement.at


@dataclass
class Scenario:
    """A declared match: its name, its seats, and everything placed on the map.

    The name is what the generated map is called on disk, so it has to be usable as a folder and
    file name; it is also how a test tells its scenario apart from another test's in the game's
    map list.
    """

    name: str
    seats: tuple[Seat, ...] = ()
    placements: list[Placement] = field(default_factory=list)

    def place(self, template: str, at: Vec3, seat: int | None = 0, **kwargs) -> Handle:
        """Declare an object, and return the handle a test refers to it by."""
        if seat is not None and not 0 <= seat < len(self.seats):
            raise ValueError(f"seat {seat} is not one of this scenario's {len(self.seats)} seats")
        placement = Placement(template=template, at=at, seat=seat, **kwargs)
        self.placements.append(placement)
        return Handle(index=len(self.placements) - 1, placement=placement)

    def owner_of(self, placement: Placement) -> str | None:
        """The qualified map-side owner to write for `placement`, or None when it is neutral."""
        if placement.seat is None:
            return None
        return self.seats[placement.seat].map_team

    @property
    def human(self) -> Seat | None:
        """The seat a test drives, which is the first non-AI one."""
        return next((seat for seat in self.seats if not seat.ai), None)

    def with_name(self, name: str) -> Scenario:
        """A copy under another name - one scenario, several generated maps."""
        return replace(self, name=name, placements=list(self.placements))
