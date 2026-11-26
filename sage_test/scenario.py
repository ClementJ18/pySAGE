"""What a system test declares: the seats, and the objects on the map before anything happens.

A scenario is **static**. Everything here is compiled into a `.map` before the engine starts,
because that is the only way to put a level-7 hero next to a finished building without asking the
engine to do something a player could not: `objectExperienceLevel`, `objectUpgradesList` and
`originalOwner` are ordinary WorldBuilder object properties, so a scenario is legal map data
rather than an injected cheat.

That is why declaration and execution are separate phases, and why `place` hands back a
`Handle` rather than anything you can act on. The handle names an object that does not
exist yet; `sage_test.harness` binds it to a live `ObjectId` once the match is up.

    scenario = Scenario("edict", seats=(Seat.human(faction=3), Seat.easy_ai(faction=10)))
    hero = scenario.place("AngmarMorgomir", at=(400, 400), level=7)
    hall = scenario.place("AngmarHallOfKingsMen", at=(520, 400))

Nothing here imports `sage_map` or needs a game on disk, so a scenario can be built,
inspected and tested with neither present.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field, replace
from os import PathLike

from sage_live.launch.seats import DIFFICULTIES, Seat

__all__ = [
    "DIFFICULTIES",
    "Action",
    "AnyOf",
    "Area",
    "Condition",
    "Handle",
    "Placement",
    "Scenario",
    "ScriptDecl",
    "Seat",
    "Waypoint",
    "act",
    "any_of",
    "cond",
]

Vec3 = tuple[float, float, float]
#: A script argument as a test writes it. `sage_test.script_compile` converts it to the slot the
#: template's parameter type stores: a name, a number, an enum value by name, or a position.
Value = str | int | float | bool | tuple[float, float] | tuple[float, float, float]


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
    #: `objectIndestructible`, WorldBuilder's "Indestructible" box: the object takes no fatal damage.
    indestructible: bool = False
    #: `objectName`, the WorldBuilder label. Scripts address objects by this; tests do not need
    #: it, but a scenario that wants to be openable in WorldBuilder does.
    name: str | None = None
    #: A map-side owner that is not a seat, such as `PlyrCreeps/teamPlyrCreeps`: one of the
    #: template map's own players. Overrides `seat`. An enemy no skirmish AI gives orders to.
    owner: str | None = None
    #: Where the engine puts the object, when that is not `at`: a castle piece with
    #: `GeometryRotationAnchorOffset` is stored at its castle's centre and moved out along its
    #: facing. Only binding reads it; the map is written with `at`.
    expect_at: Vec3 | None = None
    #: False writes the object to the map but never binds it: scenery a test does not address,
    #: such as the rest of a castle prefab, whose pieces may move or die as the match starts.
    bind: bool = True

    @property
    def live_at(self) -> Vec3:
        """Where the harness looks for the live object."""
        return self.expect_at if self.expect_at is not None else self.at


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


@dataclass(frozen=True, slots=True)
class Action:
    """A script action by its WorldBuilder internal name (`CREATE_OBJECT`, `NAMED_KILL`, ...)."""

    name: str
    args: tuple[Value, ...] = ()


@dataclass(frozen=True, slots=True)
class Condition:
    """A script condition by its WorldBuilder internal name (`NAMED_INSIDE_AREA`, ...)."""

    name: str
    args: tuple[Value, ...] = ()
    inverted: bool = False


@dataclass(frozen=True, slots=True)
class AnyOf:
    """Clauses ORed together; the conditions inside one clause are ANDed, as the map stores them."""

    clauses: tuple[tuple[Condition, ...], ...]


def act(name: str, *args: Value) -> Action:
    return Action(name, args)


def cond(name: str, *args: Value, inverted: bool = False) -> Condition:
    return Condition(name, args, inverted)


def any_of(*clauses: Condition | tuple[Condition, ...]) -> AnyOf:
    """`any_of(a, (b, c))` holds when `a` holds, or when `b` and `c` both do."""
    return AnyOf(tuple(c if isinstance(c, tuple) else (c,) for c in clauses))


#: Which script list a script goes on: None is the neutral side, an int is a seat (its
#: `Player_<start + 1>`), a string names any side of the template map.
Side = int | str | None


@dataclass(frozen=True, slots=True)
class ScriptDecl:
    """One map script a scenario adds, in the `sage_test` group of its side's script list.

    A **trigger** (`Scenario.script`) is written switched off: the test switches it on
    (`Match.scripts.fire`), it runs once when its conditions hold - straight away for one without
    any - and switches itself off again. A **probe** (`Scenario.probe`) is written switched on and
    only records each time its conditions held. Either way the last action adds one to the
    counter `sage_test.<name>`, which is how the harness knows a run happened.
    """

    name: str
    actions: tuple[Action, ...]
    #: The clauses, ORed; empty is the engine's `CONDITION_TRUE`.
    clauses: tuple[tuple[Condition, ...], ...] = ()
    probe: bool = False
    #: Switches itself off when it fires. A trigger always does; a probe with `once` False
    #: records every evaluation its conditions hold on.
    once: bool = True
    #: Seconds between evaluations; 0 is every logic frame.
    every: int = 0
    side: Side = None


@dataclass(frozen=True, slots=True)
class Waypoint:
    name: str
    at: Vec3


@dataclass(frozen=True, slots=True)
class Area:
    """A trigger area: a polygon in world units, x and y."""

    name: str
    points: tuple[tuple[float, float], ...]


def _clauses(when: tuple[Condition | AnyOf, ...]) -> tuple[tuple[Condition, ...], ...]:
    """Conditions given side by side are one ANDed clause; an `AnyOf` has to stand alone, since
    spreading an AND over an OR is a choice the test should make where it can be seen."""
    if not when:
        return ()
    if len(when) == 1 and isinstance(when[0], AnyOf):
        return when[0].clauses
    if any(isinstance(item, AnyOf) for item in when):
        raise ValueError("any_of(...) cannot be combined with other conditions; nest them in it")
    return (tuple(item for item in when if isinstance(item, Condition)),)


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
    #: The text of a `map.ini` written next to the generated map, which the engine loads on top
    #: of the mod's ini when the match starts. Empty writes none. It is an override file, so a
    #: new module on an existing Object goes through `AddModule` - see `override`.
    map_ini: str = ""
    #: Files or folders copied next to that `map.ini`, for its relative `#include`s: the map
    #: lives in the user files, so an include is resolved from there and not from the mod tree.
    map_ini_includes: tuple[str | PathLike[str], ...] = ()
    #: Map scripts the scenario adds, and the waypoints and trigger areas they name.
    scripts: list[ScriptDecl] = field(default_factory=list)
    waypoints: list[Waypoint] = field(default_factory=list)
    areas: list[Area] = field(default_factory=list)

    def script(
        self,
        name: str,
        *actions: Action,
        when: Condition | AnyOf | tuple[Condition | AnyOf, ...] = (),
        side: Side = None,
    ) -> ScriptDecl:
        """Declare a trigger: switched off until the test fires it, then run once.

        Its arguments are fixed here; what the test picks at run time is which script and when.
        `when` makes a fired trigger wait for its conditions rather than run straight away.
        """
        if not actions:
            raise ValueError(f"script {name!r} has no actions")
        decl = ScriptDecl(name, tuple(actions), self._when(when), side=side)
        return self._add_script(decl)

    def probe(
        self,
        name: str,
        *when: Condition | AnyOf,
        actions: tuple[Action, ...] = (),
        once: bool = True,
        every: int = 0,
        side: Side = None,
    ) -> ScriptDecl:
        """Declare a probe: switched on from the start, counting each time `when` held - the
        engine's own judgement of "unit X is in area A", read back as `Match.scripts.count`."""
        if not when:
            raise ValueError(f"probe {name!r} has no conditions")
        decl = ScriptDecl(name, actions, _clauses(when), True, once, every, side)
        return self._add_script(decl)

    def waypoint(self, name: str, at: Vec3) -> Waypoint:
        self._unique(name, [w.name for w in self.waypoints], "waypoint")
        waypoint = Waypoint(name, at)
        self.waypoints.append(waypoint)
        return waypoint

    def area(
        self,
        name: str,
        rect: tuple[tuple[float, float], tuple[float, float]] | None = None,
        points: tuple[tuple[float, float], ...] = (),
    ) -> Area:
        """A trigger area, as a rectangle `((x0, y0), (x1, y1))` or a polygon of `points`."""
        if (rect is None) == (not points):
            raise ValueError(f"area {name!r} takes a rect or points, not both or neither")
        if rect is not None:
            (x0, y0), (x1, y1) = rect
            points = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
        if len(points) < 3:
            raise ValueError(f"area {name!r} needs at least three points")
        self._unique(name, [a.name for a in self.areas], "area")
        area = Area(name, tuple(points))
        self.areas.append(area)
        return area

    @staticmethod
    def _when(
        when: Condition | AnyOf | tuple[Condition | AnyOf, ...],
    ) -> tuple[tuple[Condition, ...], ...]:
        return _clauses(when if isinstance(when, tuple) else (when,))

    @staticmethod
    def _unique(name: str, taken: list[str], kind: str) -> None:
        if not name or "/" in name:
            raise ValueError(f"{kind} name {name!r} must be non-empty and free of '/'")
        if name.lower() in (t.lower() for t in taken):
            raise ValueError(f"{kind} {name!r} is declared twice")

    def _add_script(self, decl: ScriptDecl) -> ScriptDecl:
        self._unique(decl.name, [s.name for s in self.scripts], "script")
        if isinstance(decl.side, int) and not 0 <= decl.side < len(self.seats):
            raise ValueError(f"script {decl.name!r}: seat {decl.side} is not one of the seats")
        self.scripts.append(decl)
        return decl

    def place(self, template: str, at: Vec3, seat: int | None = 0, **kwargs) -> Handle:
        """Declare an object, and return the handle a test refers to it by."""
        if seat is not None and kwargs.get("owner") is None and not 0 <= seat < len(self.seats):
            raise ValueError(f"seat {seat} is not one of this scenario's {len(self.seats)} seats")
        placement = Placement(template=template, at=at, seat=seat, **kwargs)
        self.placements.append(placement)
        return Handle(index=len(self.placements) - 1, placement=placement)

    def override(self, ini: str, *includes: str | PathLike[str]) -> None:
        """Add `ini` to the scenario's `map.ini`, and `includes` to what is copied beside it.

        Per-test ini edits without touching the mod: the engine loads it once, as the map loads,
        so it is fixed for the match - a different edit is a different launch::

            scenario.override('''
            Object EntEntling
                AddModule ModuleTag_WallMelee
                    Behavior = WeaponSetUpgrade ModuleTag_WallMelee
                        TriggeredBy = Upgrade_X
                    End
                End
            End
            ''')

        Indentation common to every line is removed, so the text can sit in the test as written.
        """
        text = textwrap.dedent(ini).strip("\r\n")
        if text:
            joined = f"{self.map_ini.rstrip()}\n\n{text}" if self.map_ini else text
            self.map_ini = f"{joined}\n"
        self.map_ini_includes = (*self.map_ini_includes, *includes)

    def owner_of(self, placement: Placement) -> str | None:
        """The qualified map-side owner to write for `placement`, or None when it is neutral."""
        if placement.owner is not None:
            return placement.owner
        if placement.seat is None:
            return None
        return self.seats[placement.seat].map_team

    @property
    def human(self) -> Seat | None:
        """The seat a test drives, which is the first non-AI one."""
        return next((seat for seat in self.seats if not seat.ai), None)

    def with_name(self, name: str) -> Scenario:
        """A copy under another name - one scenario, several generated maps."""
        return replace(
            self,
            name=name,
            placements=list(self.placements),
            scripts=list(self.scripts),
            waypoints=list(self.waypoints),
            areas=list(self.areas),
        )
