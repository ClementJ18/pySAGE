"""Pointing the camera at whatever is worth watching.

**The one layer that changes nothing about the match.** The camera is client state: no logic
reads it, no order carries it, it never enters the message stream and it costs no APM. So this
cannot desync a game, cannot alter what the policy is allowed to see, and cannot be the reason a
run wins or loses - which is exactly why it sits above every stage that can.

What it is for is that a bot playing well and a bot playing badly look identical from a camera
parked on the base. Every diagnosis in this package so far came from reading a log after the
fact; watching the match while it happens is the other half, and it needs the view to be
somewhere useful without a human driving it.

**Ranked, not scored.** "Interesting" is a priority order over things the bot already knows it is
doing, rather than a heuristic over the object table: the base being overrun outranks a fight at a
farm, which outranks a march. Nothing here computes a new fact about the world - if the director
wants to know whether a force is fighting, it asks `in_contact`, the same test `settle_groups`
uses to decide whether to release a group.

**It moves the camera and nothing else** - and specifically, it never writes the zoom. That is
not restraint, it is the only way: `View::setLocation` writes all four scalars every call and
cannot reproduce the zoom it reports, so a re-aim that went through it moved the live zoom by
about 0.047 and the client hauled it back over the next 0.6 seconds, every cycle, forever.
`Session.look_at` now writes the view's position field alone. An earlier version of this file
also chose a zoom per shot - closer for fights, wider for marches - which was wrong for a
separate reason: the engine interpolates nothing, so each change was a snap, and a viewer reads a
snap as a fault rather than as emphasis. Whatever zoom the watcher has set is better than one
this file guessed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sage_live.api.observation import GameObject, Vec3
from sage_mods.edain.bot.tuning import SHOT_DWELL
from sage_mods.edain.bot.warfare import Warfare

__all__ = ["Director", "Shot"]


@dataclass(frozen=True)
class Shot:
    """One thing worth looking at: where it is, and how much it outranks the alternatives.

    **`label` is identity and `caption` is description, and merging the two was a real bug.** The
    first version labelled shots `"party 0 marching"` and `"party 0 fighting"`, so a force whose
    contact flickered - an enemy drifting either side of `DEFEND_CONTACT` - stopped matching its
    own label and was treated as a brand new subject. That forced a cut on a force that had not
    moved, which from the outside is the camera jumping to the same place over and over. Identity
    must survive everything about a subject except it ceasing to exist.

    `rank` is free to change from cycle to cycle for the same label; that is a shot getting more
    urgent, not a different shot.
    """

    position: Vec3
    label: str  # identity across cycles - the party or group, never its state
    rank: int  # lower is more important
    caption: str = ""  # what to print; falls back to the label

    def described(self) -> str:
        return self.caption or self.label


class Director(Warfare):
    """Where the camera should be looking, and getting it there without jitter."""

    def stage_camera(self) -> str | None:
        """Hold the current shot, or cut to a better one, and hand its position to the pan.

        **Dwell, so that a cut means something.** Re-deciding from scratch every cycle would cut
        every time two subjects tie, which at a two-second interval is a slideshow. A shot is held
        for `SHOT_DWELL` unless something *strictly* more important appears - the base falling
        under siege interrupts a farm skirmish, another farm skirmish does not.

        **This decides where, and `CameraPan` decides how.** An earlier version eased the camera
        itself, one step per cycle, and that is a jump every two seconds however small the step -
        which is precisely what a viewer reads as snapping. Moving the camera is thousands of
        times cheaper than deciding what to point it at, so the two run on their own clocks: the
        pan closes on whatever target it was last given, at its own rate, between cycles.

        **The zoom is never touched** - see the module docstring.

        Gated here rather than by dropping the stage from `decide`'s lists, so that "the camera
        is off" stays one fact in one place instead of two tuples that have to agree.
        """
        if not self.camera:
            return None

        shots = self.shots()
        if not shots:
            return None

        now = time.monotonic()
        best = shots[0]
        held = next((s for s in shots if s.label == self._shot_label), None)
        if held is not None and now - self._shot_since < SHOT_DWELL and best.rank >= held.rank:
            chosen = held
        else:
            chosen = best

        if chosen.label != self._shot_label:
            self._shot_label = chosen.label
            self._shot_since = now

        self.pan.aim(chosen.position)
        return f"camera: {chosen.described()}"

    def shots(self) -> list[Shot]:
        """Everything worth looking at this cycle, most important first.

        The order is the argument, and it is about stakes rather than spectacle:

        - **The base under siege** leads because it is the only shot where the match can end
          while you are watching something else. `besieged` is already the bot's own test for
          "more raiders than the army can meet", so this is not a second opinion about danger.
        - **Anything in contact** next - a defence group or a field party actually fighting.
          These are where units die, which is the only thing on the map that is irreversible.
        - **A party marching** after that: less urgent, but it is the bot doing its job and it is
          where the next fight will be.
        - **The army as a whole** last, as a floor, so the camera is never parked on nothing.

        A force whose battalions have all died drops out by having no members rather than by any
        cleanup: `army()` is re-read each cycle and the ids simply stop matching.
        """
        army = self.army()
        if not army:
            return []
        standing = {o.object_id: o for o in army}
        found: list[Shot] = []

        if self.besieged():
            found.append(Shot(self.base_centre(), "the base", 0, "the base under siege"))

        # **The push outranks every fight except the base falling**, because it is the only shot
        # where the match can be *won* while the camera is somewhere else. It is also one force
        # with one destination, so unlike a party it needs no per-group entry - and it is aimed
        # at the target rather than at the army, so the arrival is what gets framed.
        if self._pushing:
            target = self.push_target()
            where = target.position if target is not None else self.push_aim()
            if where is not None:
                found.append(Shot(where, "the push", 1, "the push going in"))

        for key, ids in self._groups.items():
            force = [standing[i] for i in ids if i in standing]
            if force and self.in_contact(force):
                found.append(Shot(_centre(force), f"group {key}", 1, f"group {key} holding"))

        for party, ids in self._parties.items():
            force = [standing[i] for i in ids if i in standing]
            if not force:
                continue
            # **One shot per party whatever it is doing**, so that starting a fight changes this
            # party's rank rather than replacing it with a different subject. The label carries no
            # state for exactly that reason - see `Shot`.
            fighting = self.in_contact(force)
            found.append(
                Shot(
                    _centre(force),
                    f"party {party}",
                    2 if fighting else 3,
                    f"party {party} {'fighting' if fighting else 'marching'}",
                )
            )

        found.append(Shot(_centre(army), "the army", 4))
        return sorted(found, key=lambda shot: shot.rank)


def _centre(force: list[GameObject]) -> Vec3:
    """The mean position of a force - what a shot of it should be pointed at."""
    count = len(force)
    return (
        sum(o.position[0] for o in force) / count,
        sum(o.position[1] for o in force) / count,
        sum(o.position[2] for o in force) / count,
    )
