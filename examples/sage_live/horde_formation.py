"""Order a battalion **while it is still forming**, and watch whether it comes apart.

The bug this reproduces: a horde given an order before it has finished coming out of the
building that made it can end up as loose units that nothing can attack - only trample or
splash damage touches them. `sage_patch/docs/horde-formation-orphans.md` traces the symptom to
the engine's attack-target resolution and says what the broken state should look like from
outside:

    a unit whose `parent_id` is empty while its `producer_id` still names a live horde

Two modes, because the deliberate one turned out to have a ceiling.

**Trials** recruit a battalion, wait a chosen number of logic frames after the horde object
appears, order it to move, and sample every frame - reporting when the membership changes.
`--sweep` walks the delay down to ordering on the very frame it spawns.

**`--observe`** orders nothing and needs no game files: it watches every battalion in the match
and reports any unit that stays un-contained past forming, whoever owns it.

Measured on RotWK 2.01 + Edain, 2026-08-05, and worth knowing before running either:

* Forming looks like the bug. The container appears empty; members are created one per logic
  frame, each un-contained and flagged `IS_LEAVING_FACTORY`; all fifteen become members
  together sixteen frames in. Only an orphan that *outlives* that is a break, which is what
  `--settle` is for.
* **Trials cannot interrupt forming.** Orders aimed at a horde still leaving its building are
  accepted into the message stream and then dropped by logic - the container does not move at
  all, while the same order after forming moves it hundreds of units. The reported bug is about
  hordes the AI makes, and the AI drives `AIUpdate` directly rather than through selection, so
  it can order what the player cannot. `--observe` is the mode that can still catch it.

Run from the repo root, in an elevated shell, with a match running and a patched `game.dat`:

    python examples/sage_live/horde_formation.py --observe 600
    python examples/sage_live/horde_formation.py --game "C:/.../rotwk" --unit MordorOrcHorde \
        --sweep --step 5

A trial run mounts the install's `.big` archives and parses the ini tree, which takes about a
minute; the mount is cached, the parse is not. `--observe` skips all of it.
"""

import sys
import time
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

from _common import attach, describe, issue, my_units  # noqa: E402

from sage_live import orders  # noqa: E402
from sage_live.api.observation import GameObject, Observation  # noqa: E402
from sage_live.backends.bridge import BridgeBackend  # noqa: E402
from sage_live.utils.resolve import Resolver, UnknownDefinition  # noqa: E402
from sage_utils.gameroot import resolve_game_root  # noqa: E402

# The two status bits that say where in forming a unit is. Read from the engine's own table, so
# a build that renames one reports it renamed rather than silently dropping it.
MEMBER = "HORDE_MEMBER"
LEAVING = "IS_LEAVING_FACTORY"


@dataclass(frozen=True)
class Sample:
    """What one logic frame looked like from outside, for one horde."""

    frame: int
    members: tuple[int, ...]  # ids the horde currently contains
    loose: tuple[int, ...]  # ids it produced that it no longer contains
    leaving: int  # how many of either are still flagged as leaving the factory
    horde_alive: bool
    # Where the container is. An order the engine drops and an order it obeys look identical
    # from the membership alone, so the trial has to watch the horde actually go somewhere.
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)

    @property
    def shape(self) -> tuple:
        """What has to change for the sample to be worth printing."""
        return (len(self.members), self.loose, self.leaving, self.horde_alive)


def family(observation: Observation, horde_id: int) -> Sample:
    """The horde and everything it produced, split by whether it still contains them.

    `producer_id` is the link that survives a unit leaving, which is the whole point: members
    and orphans are told apart by `parent_id` alone, and both are found through the producer.
    """
    kin = [o for o in observation.objects if o.producer_id == horde_id]
    members = tuple(sorted(o.object_id for o in kin if o.parent_id == horde_id))
    loose = tuple(sorted(o.object_id for o in kin if o.parent_id is None))
    leaving = sum(1 for o in kin if o.has_status(LEAVING))
    horde = observation.obj(horde_id)
    return Sample(
        frame=observation.frame,
        members=members,
        loose=loose,
        leaving=leaving,
        horde_alive=horde is not None,
        position=horde.position if horde is not None else (0.0, 0.0, 0.0),
    )


def find_new(observation: Observation, template: str, known: set[int]) -> GameObject | None:
    for obj in observation.objects:
        if obj.template_name == template and obj.object_id not in known:
            return obj
    return None


def await_horde(backend: BridgeBackend, template: str, known: set[int], seconds: float):
    """Watch for the horde container the recruit will produce."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        observation = backend.observe()
        found = find_new(observation, template, known)
        if found is not None:
            return found, observation.frame
    return None, 0


def watch(backend: BridgeBackend, horde_id: int, until_frame: int, order_at: int, send) -> list:
    """Sample every frame from now to `until_frame`, sending the order at `order_at`.

    Sampled as fast as the reader goes and de-duplicated by frame, because the logic ticks at
    30 Hz and a poll loop does not line up with it. One sample per frame is what makes "the
    frame it broke" a real answer rather than the frame we happened to look.
    """
    seen: dict[int, Sample] = {}
    sent = False
    # A paused game never reaches the frame, so the loop is bounded by the clock as well. The
    # frames are the measurement; this only stops the script hanging on a paused match.
    deadline = time.monotonic() + (until_frame - order_at) / 30.0 + 30.0
    while time.monotonic() < deadline:
        observation = backend.observe()
        if not sent and observation.frame >= order_at:
            send()
            sent = True
        seen.setdefault(observation.frame, family(observation, horde_id))
        if observation.frame >= until_frame:
            break
    return [seen[f] for f in sorted(seen)]


def report(samples: list, order_at: int, settle: int) -> bool:
    """Print the frames where the shape changed. True when the battalion came apart.

    **A unit with no container is not yet a broken one.** Measured live: a forming battalion
    creates its members one per logic frame, and each one exists un-contained and flagged
    `IS_LEAVING_FACTORY` for the frames between being created and being put into the horde - a
    15-strong battalion spends about 15 frames with orphans in it and is then whole. Calling
    that a break reports every healthy recruit as the bug.

    So an orphan counts only if it *persists*: still loose in the last sample, or loose for
    more than `settle` frames. That is the difference between coming out and coming apart.
    """
    print(f"  {'frame':>7}  {'members':>7}  {'loose':>5}  {'leaving':>7}  horde")
    last = None
    marked = False
    for s in samples:
        if s.shape == last:
            continue
        last = s.shape
        mark = ""
        if not marked and s.frame >= order_at:
            mark, marked = " <- ordered", True
        alive = "alive" if s.horde_alive else "GONE"
        print(
            f"  {s.frame:>7}  {len(s.members):>7}  {len(s.loose):>5}  {s.leaving:>7}  {alive}{mark}"
        )

    final = samples[-1]
    after = [s for s in samples if s.frame >= order_at and s.horde_alive]
    if after:
        start = after[0].position
        moved = max(
            ((s.position[0] - start[0]) ** 2 + (s.position[1] - start[1]) ** 2) ** 0.5
            for s in after
        )
        verdict = "the order was obeyed" if moved > 5.0 else "THE ORDER DID NOTHING"
        print(f"  the container moved {moved:.0f} units after the order - {verdict}")
    peak = max(len(s.members) for s in samples)
    whole = next((s for s in samples if len(s.members) == peak and not s.loose), None)
    if whole is not None:
        print(f"  formed up by frame {whole.frame}: {peak} members, none loose")

    frames_loose: dict[int, int] = {}
    for s in samples:
        for oid in s.loose:
            frames_loose[oid] = frames_loose.get(oid, 0) + 1
    stuck = sorted({o for o, n in frames_loose.items() if n > settle} | set(final.loose))
    if frames_loose:
        longest = max(frames_loose.values())
        print(
            f"  {len(frames_loose)} unit(s) were briefly un-contained while leaving the factory "
            f"(longest {longest} frames)"
        )
    if not stuck:
        print("  no orphan outlived forming: the battalion came out whole")
        return False

    print(f"\n  BROKE: {len(stuck)} unit(s) never made it into the battalion")
    print(f"  stuck ids: {', '.join(str(i) for i in stuck)}")
    print(f"  by frame {final.frame}: {len(final.members)} member(s), {len(final.loose)} loose")
    if not final.members and final.horde_alive:
        print("  the container is still alive with no members - the state the patch is about")
    return True


def dump(backend: BridgeBackend, horde_id: int) -> None:
    """The per-object reading `horde-formation-orphans.md` section 6 asks for."""
    observation = backend.observe()
    horde = observation.obj(horde_id)
    print("\n  what the objects actually say now:")
    if horde is None:
        print(f"    horde {horde_id} is gone")
    else:
        flags = ", ".join(sorted(horde.status)) or "-"
        print(f"    horde  {horde.object_id:>6} {horde.template_name:<28} status: {flags}")
    stranded = 0
    for obj in observation.objects:
        if obj.producer_id != horde_id or obj.object_id == horde_id:
            continue
        where = "inside" if obj.parent_id == horde_id else "LOOSE "
        flags = ", ".join(sorted(obj.status)) or "-"
        print(f"    {where} {obj.object_id:>6} {obj.template_name:<28} status: {flags}")
        if obj.parent_id is None and obj.has_status(MEMBER):
            stranded += 1
    if stranded:
        print(f"    {stranded} loose unit(s) still carry {MEMBER} with nothing containing them")


def trial(backend: BridgeBackend, resolver: Resolver, args, delay: int) -> bool | None:
    """One recruit-order-watch cycle. True if it broke, None if it could not be run."""
    print(f"\ndelay {delay} frames after the horde appears")

    producers = [u for u in my_units(backend) if args.building.lower() in u.template_name.lower()]
    if not producers:
        print(f"  no owned building matching {args.building!r} - try --building")
        return None
    producer = producers[0]

    known = {o.object_id for o in backend.observe().objects if o.template_name == args.unit}
    if not issue(backend, orders.select(resolver.player_index, [producer.object_id]), "select"):
        return None
    if not issue(backend, resolver.recruit(args.unit), "recruit"):
        return None

    horde, appeared = await_horde(backend, args.unit, known, args.timeout)
    if horde is None:
        print(f"  no {args.unit} appeared within {args.timeout:.0f}s - unaffordable, or blocked?")
        return None
    print(f"  horde {horde.object_id} appeared at frame {appeared}")

    target = (horde.position[0] + args.distance, horde.position[1], horde.position[2])

    go = orders.attack_move if args.attack_move else orders.move

    def send() -> None:
        issue(backend, orders.select(resolver.player_index, [horde.object_id]), "select horde")
        issue(backend, go(resolver.player_index, target), "move")

    samples = watch(backend, horde.object_id, appeared + args.watch, appeared + delay, send)
    broke = report(samples, appeared + delay, args.settle)
    if broke:
        dump(backend, horde.object_id)
    return broke


def observe(backend: BridgeBackend, seconds: float, settle: int) -> int:
    """Watch **every** battalion in the match, ordering nothing. No game files needed.

    The reported bug is about hordes the *AI* makes, and the AI does not order through
    selection and the message stream the way this script's trials do - so the deliberate path
    cannot make the AI's mistake for it. This mode instead watches for the state itself,
    wherever it comes from: a unit that stays un-contained, past forming, while the horde that
    produced it is still alive.

    Cheap enough to leave running: it costs no resources, sends nothing, and touches no unit.
    """
    print(f"watching every horde in the match for {seconds:.0f}s, ordering nothing")
    loose_since: dict[int, int] = {}
    reported: set[int] = set()
    frames = 0
    deadline = time.monotonic() + seconds
    first = last = 0
    while time.monotonic() < deadline:
        observation = backend.observe()
        if not first:
            first = observation.frame
        last = observation.frame
        frames += 1
        for obj in observation.objects:
            if obj.parent_id is not None or not obj.producer_id:
                loose_since.pop(obj.object_id, None)
                continue
            producer = observation.obj(obj.producer_id)
            if producer is None or not obj.has_status(MEMBER):
                continue
            since = loose_since.setdefault(obj.object_id, observation.frame)
            if observation.frame - since <= settle or obj.object_id in reported:
                continue
            reported.add(obj.object_id)
            members = observation.members(obj.producer_id)
            owner = observation.player(obj.owner_index) if obj.owner_index is not None else None
            print(f"\n  ORPHAN at frame {observation.frame}, loose since {since}")
            print(
                f"    {obj.object_id} {obj.template_name} owned by {owner.name if owner else '?'}"
            )
            print(f"    status: {sorted(obj.status)}")
            print(
                f"    producer {producer.object_id} {producer.template_name} "
                f"with {len(members)} member(s), status {sorted(producer.status)}"
            )

    print(f"\nsampled {frames} observations over frames {first}-{last}")
    if not reported:
        print(f"no unit stayed un-contained for more than {settle} frames. The state did not")
        print("occur in this window - leave it running longer, or across a battle.")
        return 1
    print(f"{len(reported)} orphan(s) seen: {sorted(reported)}")
    return 0


def main() -> int:
    parser = ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--game", help="install folder, or an extracted ini tree")
    parser.add_argument("--unit", help="the horde template to recruit")
    parser.add_argument(
        "--observe",
        type=float,
        default=0.0,
        help="seconds to watch every horde in the match instead of running trials",
    )
    parser.add_argument("--building", default="Pit", help="substring of the producing building")
    parser.add_argument(
        "--delay", type=int, default=30, help="logic frames to wait before ordering (30 = 1s)"
    )
    parser.add_argument("--watch", type=int, default=300, help="frames to keep watching for")
    parser.add_argument(
        "--settle", type=int, default=60, help="frames a unit may be un-contained while forming"
    )
    parser.add_argument("--distance", type=float, default=600.0, help="how far to order it")
    parser.add_argument(
        "--attack-move", action="store_true", help="A-move instead of move, as an AI push does"
    )
    parser.add_argument("--timeout", type=float, default=60.0, help="seconds to wait for the unit")
    parser.add_argument(
        "--sweep", action="store_true", help="repeat with the delay falling to zero"
    )
    parser.add_argument("--step", type=int, default=5, help="frames to shorten the delay by")
    args = parser.parse_args()

    backend = attach()
    describe(backend)

    if args.observe:
        return observe(backend, args.observe, args.settle)
    if not args.game or not args.unit:
        raise SystemExit("--game and --unit are required unless --observe is given")

    print(f"\nloading the game tables from {args.game} (about a minute the first time)")
    started = time.time()
    resolver = Resolver.from_root(
        resolve_game_root(args.game), player_index=backend.observe().local_player
    )
    print(f"  loaded {len(resolver.game.object_order)} templates in {time.time() - started:.0f}s")
    try:
        resolver.recruit(args.unit)
    except UnknownDefinition as exc:
        raise SystemExit(str(exc)) from exc

    delays = range(args.delay, -1, -args.step) if args.sweep else [args.delay]
    broke_at = [d for d in delays if trial(backend, resolver, args, d)]

    print()
    if not broke_at:
        print("no trial produced an orphan. Either the delay never landed inside forming -")
        print("try --sweep, which walks it down to ordering on the very frame it appears - or")
        print("this build does not break the way the report describes.")
        return 1
    print(f"orphans at delays: {', '.join(str(d) for d in broke_at)} frames")
    print("Read the loose units' status above. HORDE_MEMBER still set with no parent is the")
    print("half-formed state; the container surviving with no members is what swallows attack")
    print("orders aimed at them - see sage_patch/docs/horde-formation-orphans.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
