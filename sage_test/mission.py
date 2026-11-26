"""Campaign mission tests: start a mission map, watch its scripts, read its objectives screen.

The method is `docs/mission-testing.md`. A mission map is started as a **skirmish** off a copy in
the user Maps folder (`sage_test.plugin.user_map_runner`), because the `-file` auto-start refuses a
map its mod lists as single-player. That costs fidelity, and each mission test should say how
much: no carryover units, no campaign save, sides rebuilt.

What this adds over a scenario:

- `prepare_map`: the copy to install, with objects the campaign would have carried over placed
  into it (a skirmish start has no carryover, and a mission whose lose condition counts a
  carried hero ends on frame one without them).
- `ScriptWatch`: the playbook's name-keyed watch (its section 2). It records every script the game
  fires through the trace hooks and names them through the live script tree.
- `Mission`: the running game with both handles - the ordering `Session` and the script
  debugger's `LiveSession` - and the objectives screen read straight from the engine's tracker.
- `hold_skirmish_defeat`: the one rule a War of the Ring battle has and a skirmish start of the
  same map does not.
"""

from __future__ import annotations

import copy
import io
import shutil
import struct
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from sage_live.api.observation import GameObject, Observation, Vec3
from sage_live.api.orders import OrderType
from sage_live.api.session import Session
from sage_live.backends.live_patch import WindowsProcess
from sage_live.backends.script_trace import EventKind
from sage_live.backends.scripts import LiveScript, ScriptVariable
from sage_map import parse_map, write_map
from sage_map.assets.player_scripts import ScriptGroup
from sage_patch.addresses import (
    GLOBAL_DATA,
    GLOBAL_DATA_SECONDS_BEFORE_BASE_CHECK,
    LOGIC_FRAMES_PER_SECOND,
    MAX_PLAYER_COUNT,
    MISSION_OBJECTIVE_LIST_OFFSET,
    MISSION_OBJECTIVE_TRACKER,
    PLAYER_DEFEAT_FRAME,
    PLAYER_INDEX,
    PLAYER_IS_DEFEATED,
    THE_VICTORY_CONDITIONS,
    VICTORY_CONDITIONS_IS_DEFEATED,
    VICTORY_CONDITIONS_PLAYERS,
)
from sage_replay.replay import Order, OrderArgument, OrderArgumentType
from sage_test.compile import compile_into
from sage_test.scenario import Scenario
from sage_worldbuilder.ids import next_waypoint_id
from sage_worldbuilder.live import LiveAttachError, LiveIndex, LiveSession, LiveSnapshot
from sage_worldbuilder.scripting import iter_script_items, player_script_lists

__all__ = [
    "WOTR_ANCHOR",
    "Carryover",
    "Defeat",
    "GameEnded",
    "Mission",
    "Objective",
    "ScriptWatch",
    "hold_skirmish_defeat",
    "prepare_map",
    "read_defeats",
    "read_objectives",
]

Reader = Callable[[int, int], bytes | None]

#: A tracker entry is 8 bytes: the label pointer, a bonus flag, then shown and ticked. Read from
#: the setters `0x00835FAE` (SHOW/HIDE write +5) and `0x00836097` (MARK write +6).
_ENTRY_SIZE, _BONUS, _SHOWN, _TICKED = 8, 4, 5, 6

#: What `hold_skirmish_defeat` puts the base check off to: never, in any match a test runs.
_NEVER = 1.0e9


@dataclass(frozen=True, slots=True)
class Carryover:
    """An object the campaign would have brought into the mission, placed into the copy.

    `indestructible` is for the War of the Ring start's own placeholder, which a skirmish needs
    to keep: see `WOTR_ANCHOR`.
    """

    template: str
    at: Vec3
    owner: str
    name: str | None = None
    indestructible: bool = False


#: A War of the Ring battle gives each army an `ObjectRingkriegStartScript`: no model, an empty
#: command set, and `MP_COUNT_FOR_VICTORY`, with a 10 s `LifetimeUpdate`. A skirmish start has
#: none, and a mission whose start-up scripts `TEAM_KILL` the player's starting army leaves
#: nothing that counts - the skirmish victory check then defeats the player and the game exits.
#: Placed indestructible, so the lifetime cannot remove it, it holds the match open as the battle
#: would.
WOTR_ANCHOR = "ObjectRingkriegStartScript"


def prepare_map(
    source: Path,
    workdir: Path,
    carryover: Sequence[Carryover],
    disable_scripts: Sequence[str] = (),
    waypoints: Sequence[tuple[str, Vec3]] = (),
) -> Path:
    """A copy of the map folder `source` under `workdir`, with `carryover` placed into its `.map`
    and the scripts named in `disable_scripts` switched off (an intro movie, say).

    `waypoints` adds named waypoints the map lacks, copied from its first one. A skirmish needs a
    `Player_N_Start` for each seat, and some campaign maps have none.

    The copy keeps the folder's name, which `install_map_folder` requires of its source; the
    installed name is chosen when it is installed. Written uncompressed: the engine reads either.
    """
    target = workdir / source.name
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(source, target)
    map_file = target / f"{source.name}.map"
    parsed = parse_map(io.BytesIO(map_file.read_bytes()))
    if parsed.objects_list is None:
        raise ValueError(f"{source.name} has no object list to place carryover into")

    scenario = Scenario(source.name)
    for item in carryover:
        scenario.place(item.template, at=item.at, seat=None, owner=item.owner, name=item.name)
    before = len(parsed.objects_list.object_list)
    compile_into(scenario, parsed)
    for item, placed in zip(carryover, parsed.objects_list.object_list[before:], strict=True):
        placed.properties["objectIndestructible"]["value"] = item.indestructible

    objects = parsed.objects_list.object_list
    existing = [o for o in objects if "waypointName" in o.properties]
    for name, at in waypoints:
        if any(o.properties["waypointName"]["value"] == name for o in existing):
            raise ValueError(f"{source.name} already has a waypoint {name!r}")
        if not existing:
            raise ValueError(f"{source.name} has no waypoint to copy for {name!r}")
        waypoint = copy.deepcopy(existing[0])
        waypoint.position = at
        for key, value in (
            ("waypointName", name),
            ("uniqueID", name),
            ("waypointID", next_waypoint_id(parsed)),
        ):
            waypoint.properties[key] = {**waypoint.properties[key], "value": value}
        objects.append(waypoint)

    wanted = set(disable_scripts)
    for _, listed in player_script_lists(parsed):
        for location in iter_script_items(listed.items):
            found = location.item
            if not isinstance(found, ScriptGroup) and found.name in wanted:
                found.is_active = False
                wanted.discard(found.name)
    if wanted:
        raise ValueError(f"{source.name} has no script {sorted(wanted)}")

    map_file.write_bytes(write_map(parsed, compress=False))
    return target


class GameEnded(RuntimeError):
    """The game is gone: a defeat or a victory exits a skirmish, and so does a crash."""


def _u32(read: Reader, address: int) -> int:
    raw = read(address, 4)
    return struct.unpack("<I", raw)[0] if raw and len(raw) == 4 else 0


def hold_skirmish_defeat(live: LiveSession) -> float:
    """Keep the skirmish defeat check from ever starting, as a War of the Ring battle does.

    `SecondsBeforeBaseCheckActive` holds the check off for its first seconds. A War of the Ring
    battle exempts everyone from it anyway - its census (`0x00809404`) answers "not defeated"
    while the living world is active (`0x00441E4A`) - so a mission's start-up scripts can leave
    the player with nothing the skirmish census counts, and a `-file` skirmish, which has no
    living world, then defeats the player the moment the check starts. Pushing the delay out of
    reach gives the battle's rule.

    Must run before the delay passes; returns the value it replaced. Writes the running game
    only - the mod's `gamedata.ini` is untouched.
    """
    read = live.memory.read
    data = _u32(read, GLOBAL_DATA)
    if not data:
        raise LiveAttachError("TheWritableGlobalData is not up yet")
    field_at = data + GLOBAL_DATA_SECONDS_BEFORE_BASE_CHECK
    raw = read(field_at, 4)
    if raw is None or len(raw) != 4:
        raise LiveAttachError("could not read SecondsBeforeBaseCheckActive")
    (before,) = struct.unpack("<f", raw)
    rate = _u32(read, LOGIC_FRAMES_PER_SECOND) or 5
    frame = live.backend.frame()
    if frame >= before * rate:
        raise LiveAttachError(f"too late: frame {frame} is past the base check at {before}s")
    writer = WindowsProcess(live.pid)
    try:
        if not writer.write(field_at, struct.pack("<f", _NEVER)):
            raise LiveAttachError("could not write SecondsBeforeBaseCheckActive")
    finally:
        writer.close()
    return before


@dataclass(frozen=True, slots=True)
class Objective:
    """One line of the objectives screen as the engine's tracker holds it."""

    #: 1-based, the number the map's scripts use.
    slot: int
    bonus: bool
    shown: bool
    ticked: bool


def read_objectives(read: Reader) -> list[Objective]:
    """The objectives screen, in `MissionObjectiveList` order; empty when no mission is up."""
    tracker = _u32(read, MISSION_OBJECTIVE_TRACKER)
    listed = _u32(read, tracker + MISSION_OBJECTIVE_LIST_OFFSET) if tracker else 0
    if not listed:
        return []
    begin, end = _u32(read, listed + 4), _u32(read, listed + 8)
    found = []
    for slot, at in enumerate(range(begin, end, _ENTRY_SIZE), start=1):
        raw = read(at, _ENTRY_SIZE) or bytes(_ENTRY_SIZE)
        found.append(Objective(slot, bool(raw[_BONUS]), bool(raw[_SHOWN]), bool(raw[_TICKED])))
    return found


@dataclass(frozen=True, slots=True)
class Defeat:
    """What the victory conditions hold about one player they track."""

    #: The player's `PlayerList` index.
    player: int
    #: The subsystem's own `m_isDefeated` latch: once set, the player has lost.
    latched: bool
    #: The player's own defeated flag, set alongside the latch.
    flagged: bool
    #: The frame the defeat was recorded on; 0 while the player stands.
    frame: int


def read_defeats(read: Reader) -> list[Defeat]:
    """Every player `TheVictoryConditions` tracks, with its defeat state; empty when there are
    none (at the menus). How a test sees a defeat before the game exits because of it."""
    conditions = _u32(read, THE_VICTORY_CONDITIONS)
    if not conditions:
        return []
    latches = read(conditions + VICTORY_CONDITIONS_IS_DEFEATED, MAX_PLAYER_COUNT)
    latches = latches or bytes(MAX_PLAYER_COUNT)
    found = []
    for slot in range(MAX_PLAYER_COUNT):
        player = _u32(read, conditions + VICTORY_CONDITIONS_PLAYERS + 4 * slot)
        if not player:
            continue
        own = read(player + PLAYER_IS_DEFEATED, 1) or b"\0"
        found.append(
            Defeat(
                player=_u32(read, player + PLAYER_INDEX),
                latched=bool(latches[slot]),
                flagged=bool(own[0]),
                frame=_u32(read, player + PLAYER_DEFEAT_FRAME),
            )
        )
    return found


class ScriptWatch:
    """Every script the running game fires, by name and by the player whose side ran it.

    Firing comes from the trace ring (`LiveSession.set_recording`), not from the script tree: a
    one-shot that is inactive in the map and fired after an ENABLE looks the same in the tree as
    one that was never enabled. The ring is drained on every `refresh`, so poll often while the
    game is fast-forwarded; `dropped` says how many events were lost to a full ring.
    """

    def __init__(self, live: LiveSession) -> None:
        self.live = live
        self.fired_at: dict[tuple[str, str], list[int]] = {}
        self.dropped = 0
        self.snapshot: LiveSnapshot | None = None
        live.set_recording(True)

    def refresh(self) -> LiveSnapshot | None:
        snapshot = self.live.poll()
        if snapshot is None:
            return self.snapshot
        index = LiveIndex(snapshot)
        for event in snapshot.trace:
            if event.kind is EventKind.FALSE_ACTIONS:
                continue
            found = index.at(event.script)
            if found is not None:
                player, script = found
                self.fired_at.setdefault((player, script.name), []).append(event.frame)
        self.dropped += snapshot.dropped
        self.snapshot = snapshot
        return snapshot

    def frames(self, name: str, player: str | None = None) -> list[int]:
        return sorted(
            frame
            for (owner, script), frames in self.fired_at.items()
            if script == name and (player is None or owner == player)
            for frame in frames
        )

    def fired(self, name: str, player: str | None = None) -> bool:
        return bool(self.frames(name, player))

    def first(self, name: str, player: str | None = None) -> int | None:
        frames = self.frames(name, player)
        return frames[0] if frames else None

    def timeline(self) -> list[tuple[int, str, str]]:
        """Every firing seen, in frame order: (frame, player, script)."""
        return sorted(
            (frame, player, name)
            for (player, name), frames in self.fired_at.items()
            for frame in frames
        )


@dataclass
class Mission:
    """The running mission: the ordering session, the script debugger, and what was seen."""

    session: Session
    live: LiveSession
    watch: ScriptWatch
    log: list[str] = field(default_factory=list)

    def observe(self) -> Observation:
        return self.session.observe()

    def refresh(self) -> Observation:
        self.watch.refresh()
        return self.observe()

    def objectives(self) -> list[Objective]:
        """The objectives screen as the engine holds it - see `read_objectives`."""
        return read_objectives(self.live.memory.read)

    def objective(self, slot: int) -> Objective:
        return self.objectives()[slot - 1]

    def defeats(self) -> list[Defeat]:
        """The victory conditions' view of every player - see `read_defeats`."""
        return read_defeats(self.live.memory.read)

    def variables(self) -> dict[str, ScriptVariable]:
        snapshot = self.watch.snapshot or self.watch.refresh()
        return {variable.key: variable for variable in snapshot.variables} if snapshot else {}

    def flag(self, name: str, scope: str = "") -> bool:
        found = self.variables().get(f"{scope}/{name}")
        return bool(found and found.value)

    def script(self, name: str, player: str | None = None) -> LiveScript:
        snapshot = self.watch.snapshot or self.watch.refresh()
        if snapshot is not None:
            for side, script in snapshot.tree.find(name):
                if player is None or snapshot.players.get(side, "") == player:
                    return script
        raise KeyError(f"no live script {name!r}" + (f" on {player}" if player else ""))

    def mine(self, *templates: str) -> list[GameObject]:
        """The local player's objects, optionally only these templates (case-insensitive)."""
        wanted = {t.lower() for t in templates}
        return [o for o in self.observe().mine if not wanted or o.template_name.lower() in wanted]

    def built(self, *templates: str) -> list[GameObject]:
        """The local player's finished objects of these templates (not still going up)."""
        return [o for o in self.mine(*templates) if not o.under_construction]

    def theirs(self, owner_index: int, *templates: str) -> list[GameObject]:
        wanted = {t.lower() for t in templates}
        return [
            o
            for o in self.observe().owned_by(owner_index)
            if not wanted or o.template_name.lower() in wanted
        ]

    def resources(self) -> int:
        me = self.observe().me
        return me.resources if me else 0

    def order_until(
        self,
        what: str,
        issue: Callable[[Mission], None],
        done: Callable[[Mission], bool],
        timeout: float,
        every: float = 8.0,
    ) -> None:
        """Issue an order, and again every `every` seconds until `done` - at normal speed.

        An order the bridge reports sent is not one the engine carried out: a selection takes
        seconds to settle on a `-mod` run and a dropped order says nothing. So each step is
        confirmed against the world and re-sent until it is. `done` should be the order *taking*
        (a site appearing, a unit queued), and the wait for its result a separate,
        fast-forwarded `wait_until`.
        """
        last = [0.0]

        def tick(mission: Mission) -> None:
            if time.monotonic() - last[0] >= every:
                issue(mission)
                last[0] = time.monotonic()

        self.note(f"{what}: ordering ({self.resources()} resources)")
        tick(self)
        self.wait_until(done, timeout, what=what, tick=tick)
        self.note(f"{what}: taken ({self.resources()} resources)")

    def dozer_build(self, builder_id: int, template: str, at: Vec3, angle: float = 0.0) -> None:
        """Have a mobile builder (a porter, a digger) put up `template` at `at`.

        Not `Session.build`: that sends `FOUNDATION_CONSTRUCT`, the placement-UI build a plot
        takes, and a builder refuses it without a word - nothing placed, no gold taken. A
        human's click on the builder's button is recorded as `DOZER_CONSTRUCT` with the same
        arguments, and the position carries the terrain's height, never 0.
        """
        self.session.select([builder_id])
        time.sleep(2.0)  # a selection takes a moment to settle on a `-mod` run
        thing = self.session.resolve("thing", template)
        self.session.send(
            Order(
                self.session.player_index,
                OrderType.DOZER_CONSTRUCT,
                [
                    OrderArgument(OrderArgumentType.Integer, thing),
                    OrderArgument(OrderArgumentType.Position, at),
                    OrderArgument(OrderArgumentType.Float, angle),
                ],
            )
        )

    def attack(self, units: Sequence[GameObject], target: GameObject) -> None:
        """Send `units` at `target`. One selection, one attack order; the caller repeats it -
        an attack ends when the path is blocked or the unit is pulled into another fight."""
        if not units:
            return
        self.session.select([u.object_id for u in units])
        time.sleep(1.0)
        self.session.attack(target.object_id, target.position)

    def attack_move(self, units: Sequence[GameObject], at: Vec3) -> None:
        if not units:
            return
        self.session.select([u.object_id for u in units])
        time.sleep(1.0)
        self.session.attack_move(at)

    def wait_until(
        self,
        done: Callable[[Mission], bool],
        timeout: float,
        poll: float = 0.5,
        what: str = "the condition",
        tick: Callable[[Mission], None] | None = None,
    ) -> None:
        """Poll the watch and the world until `done`, calling `tick` between polls (to re-issue
        orders, say). Times out with `what` named."""
        deadline = time.monotonic() + timeout
        while True:
            if not self.live.alive():
                raise GameEnded(f"the game exited while waiting for {what}")
            self.watch.refresh()
            if done(self):
                return
            if time.monotonic() > deadline:
                raise TimeoutError(f"{what} not reached within {timeout:.0f}s")
            if tick is not None:
                tick(self)
            time.sleep(poll)

    def wait_for_script(self, name: str, timeout: float, player: str | None = None) -> int:
        self.wait_until(lambda m: m.watch.fired(name, player), timeout, what=f"script {name!r}")
        frame = self.watch.first(name, player)
        if frame is None:  # pragma: no cover - `fired` held, so a frame was recorded
            raise RuntimeError(f"{name} fired with no frame recorded")
        self.note(f"{name} fired at frame {frame}")
        return frame

    def note(self, text: str) -> None:
        line = f"[frame {self.session.frame}] {text}"
        self.log.append(line)
        print(line, flush=True)

    @contextmanager
    def fast(self, multiplier: int = 10) -> Iterator[None]:
        """Run the game `multiplier` times faster for the block, through the script debugger's
        speed control; normal speed again on the way out, unless the game is gone."""
        self.live.set_speed(multiplier)
        try:
            yield
        finally:
            try:
                self.live.set_speed(1)
            except LiveAttachError:
                if self.live.alive():
                    raise
