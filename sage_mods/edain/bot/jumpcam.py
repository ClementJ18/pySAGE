"""A tiny window that lists where the action is and jumps the camera there on a click.

A proof of concept, and deliberately standalone. It shares one line with the bot that matters -
`Session.look_at`, the same hard camera cut `bot/director.py` drives through `CameraPan` - but it
does not run a bot. `Director.shots()` ranks a bot's own commitments (its parties, its groups, the
push it has decided on), none of which exist without a running policy; so rather than stand a whole
bot up to read them, this reads the live observation directly and clusters what is on the map into
the same three things a watcher cares about: a fight, an enemy force, one of your own.

That is enough for the one trick being shown off - a list of places worth looking, each with a
button that snaps the view to it - and it needs no ini load and no policy, so it attaches to any
running match (yours, a replay, a bot's) in a second.
"""

from __future__ import annotations

import math
from argparse import ArgumentParser
from dataclasses import dataclass, field
from functools import partial

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from sage_live.api.connect import AttachError, attach
from sage_live.api.observation import GameObject, Observation, Vec3
from sage_live.api.session import Session
from sage_utils.widgets import card, clear_layout, run_app

__all__ = ["Action", "compute_actions", "main"]

# How close two objects have to be to count as part of the same happening. A battle line and the
# base defending it are one shot; a raid on the far side of the map is another. Loose on purpose -
# a spotter over-merging is a shorter list, which is the right failure for a glance.
CLUSTER_RADIUS = 260.0
# Below this an on-map presence is not worth a row of its own - a single scout, a lone farm plot.
# A hero standing alone is size one and worth watching, but this is a PoC and the noise floor
# earns its keep more than the edge case does.
MIN_CLUSTER = 2
# The most rows to show. Ranked, so the cut falls on the least interesting.
MAX_ACTIONS = 20


@dataclass(frozen=True)
class Action:
    """One place worth looking at, and how it ranks against the others.

    The shape mirrors `director.Shot` on purpose - a position to aim at, a rank where lower wins,
    and a line to print - so the two read as the same idea seen from two sides.
    """

    position: Vec3
    label: str
    rank: int  # lower is more important; a fight outranks a march
    detail: str = ""


def _centre(objects: list[GameObject]) -> Vec3:
    """The mean position of a cluster - where a shot of it should be aimed."""
    n = len(objects)
    return (
        sum(o.position[0] for o in objects) / n,
        sum(o.position[1] for o in objects) / n,
        sum(o.position[2] for o in objects) / n,
    )


@dataclass
class _Cluster:
    at: Vec3
    members: list[GameObject] = field(default_factory=list)


def _cluster(objects: list[GameObject], radius: float) -> list[_Cluster]:
    """Greedily group objects that stand within `radius` of a running centroid.

    One pass, order-dependent, and none the worse for it here: the question is only "roughly
    where are the knots of activity", and an object landing in the neighbouring knot moves a
    caption, not a decision. A real policy would not cluster this way; a spotter can.
    """
    clusters: list[_Cluster] = []
    for obj in objects:
        for c in clusters:
            if math.dist(c.at[:2], obj.position[:2]) <= radius:
                c.members.append(obj)
                c.at = _centre(c.members)
                break
        else:
            clusters.append(_Cluster(obj.position, [obj]))
    return clusters


def compute_actions(obs: Observation) -> list[Action]:
    """Rank what is on the map into places worth looking, most important first.

    The ranking is `director.shots()` stripped to what a single frame can answer without a bot:

    - a **fight** - a cluster holding both your objects and a live opponent's - leads, because it
      is the only kind where something irreversible is happening while you watch something else;
    - an **enemy force** next, because it is where the next fight will be;
    - **your own** forces last, as a floor, so the list is never empty while you have a unit alive.
    """
    playing = {p.index for p in obs.players if p.playing}
    me = obs.local_player
    # Bodied objects only, so plot flags, wall hubs and other map furniture stay out - and only
    # objects owned by a contesting seat, so the shell map's civilians never show.
    on_map = [o for o in obs.objects if o.has_body and o.owner_index in playing]

    actions: list[Action] = []
    for c in _cluster(on_map, CLUSTER_RADIUS):
        if len(c.members) < MIN_CLUSTER:
            continue
        mine = sum(1 for o in c.members if o.owner_index == me)
        theirs = len(c.members) - mine
        if mine and theirs:
            actions.append(
                Action(c.at, f"⚔ Battle - {mine} yours vs {theirs} enemy", 0, _where(c.at))
            )
        elif theirs:
            actions.append(Action(c.at, f"Enemy force - {theirs} objects", 2, _where(c.at)))
        else:
            actions.append(Action(c.at, f"Your force - {mine} objects", 3, _where(c.at)))

    # Rank first, then size within a rank, so the biggest fight is the top row.
    actions.sort(key=lambda a: (a.rank, _size(a.label)))
    return actions[:MAX_ACTIONS]


def _size(label: str) -> int:
    """A big presence sorts above a small one within its rank - read the first count off the
    label rather than carrying a separate field the UI never shows. Negated so larger is first."""
    for token in label.replace("-", " ").split():
        if token.isdigit():
            return -int(token)
    return 0


def _where(position: Vec3) -> str:
    return f"({position[0]:.0f}, {position[1]:.0f})"


class JumpCam(QMainWindow):
    """The whole PoC: poll the game on a timer, list the action, snap the camera on a click."""

    def __init__(self, session: Session, interval: float) -> None:
        super().__init__()
        self.session = session
        self.setWindowTitle("Jump Cam - where's the action?")
        self.resize(420, 560)

        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        self.status = QLabel("attaching…")
        self.status.setObjectName("muted")
        outer.addWidget(self.status)

        frame, self._list = card("Actions")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(frame)
        outer.addWidget(scroll, 1)

        self.setCentralWidget(root)

        # A plain timer on the UI thread: `observe()` is a memory read of a few milliseconds and
        # `look_at` is one write, so neither is worth a worker thread, and staying single-threaded
        # keeps the camera write and the list on the same clock.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(int(interval * 1000))
        self.refresh()

    def refresh(self) -> None:
        obs = self.session.poll()
        if obs is None:
            self.status.setText("connected, waiting for the first frame…")
            return
        if not obs.in_match:
            self.status.setText("at the menu - start a match (the shell map is a running game)")
            clear_layout(self._list)
            return

        actions = compute_actions(obs)
        me = obs.me
        who = f"{me.name} ({me.faction})" if me is not None else "spectating"
        self.status.setText(f"frame {obs.frame} · {who} · {len(actions)} spots")
        self._render(actions)

    def _render(self, actions: list[Action]) -> None:
        clear_layout(self._list)
        if not actions:
            self._list.addWidget(QLabel("nothing on the map yet"))
            return
        for action in actions:
            self._list.addWidget(self._row(action))
        self._list.addStretch(1)

    def _row(self, action: Action) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        text = QLabel(f"{action.label}\n{action.detail}")
        text.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(text, 1)

        jump = QPushButton("Jump")
        jump.setObjectName("primary")
        jump.clicked.connect(partial(self._jump, action))
        layout.addWidget(jump)
        return row

    def _jump(self, action: Action) -> None:
        """Snap the view to the action. `look_at` is a hard cut - no easing, so it is instant."""
        moved = self.session.look_at(action.position)
        self.status.setText(
            f"jumped to {action.label}" if moved else "could not move the camera (bridge refused)"
        )


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--pid",
        type=int,
        help="target game.dat (default: the first one found)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.5,
        help="seconds between polls of the game (default 1.5)",
    )
    args = parser.parse_args(argv)

    try:
        # Writable, because moving the camera goes through the live-bridge patch - the same
        # attach the bot uses. Reading alone cannot move a view.
        session = attach(args.pid, writable=True)
    except AttachError as exc:
        raise SystemExit(str(exc)) from exc

    run_app(lambda: JumpCam(session, args.interval), app_name="jump-cam")
    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
