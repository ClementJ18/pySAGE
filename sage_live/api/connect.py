"""`attach` - find the running game and hand back a connected `Session`.

The module is `connect` rather than `attach` so that the far more commonly used *function*
can own the short name at the package root: `sage_live.attach()` is the front door, and a
module of the same name would shadow it.

It collapses what a caller would otherwise do by hand: find the pid, open the process, choose a
backend, connect it, and pick a player index. Five steps and four failure modes worth
distinguishing - and the player index is the one that fails quietly, since defaulting it to 0 is
wrong for every seat but the first.

**The local player is read, not assumed.** `PlayerList+0x10` names it, and orders are attributed
to whoever the session says it is, so guessing here means a policy issues orders as someone
else. `attach` reads it once at connect time; it does not change during a match.

**Read-only by default.** `writable=True` is what asks for the `BridgeBackend`, and therefore
for a `game.dat` carrying the `live-bridge` patch and a `PROCESS_VM_WRITE` handle. The plain
observation path opens the process read-only and cannot modify the game even by mistake.

Failures are typed and their messages say what to do about them, because all four are things
a user hits on the first run: no game, an unelevated shell, a game sitting at the menu, and a
game without the patch.
"""

from __future__ import annotations

from typing import Literal, overload

from sage_live.api.session import DEFAULT_APM_CAP, Session
from sage_live.backends.base import ConnectionRefused
from sage_live.backends.bridge import BridgeBackend, BridgeUnavailable
from sage_live.backends.memory import (
    LAYOUT_ROTWK_201,
    EngineLayout,
    MemoryBackend,
    ProcessMemory,
    find_game_processes,
)
from sage_live.utils.heroes import ReviveLookup
from sage_live.utils.naming import LiveNames

__all__ = ["AttachError", "NoGameRunning", "NotPermitted", "attach", "open_backend"]


class AttachError(RuntimeError):
    """Could not attach to a running game. The message says which step failed and why."""


class NoGameRunning(AttachError):
    """No `game.dat` process was found."""


class NotPermitted(AttachError):
    """The process exists but could not be opened - almost always an unelevated shell."""


@overload
def open_backend(
    pid: int | None = ...,
    *,
    writable: Literal[False] = ...,
    layout: EngineLayout = ...,
) -> MemoryBackend: ...


@overload
def open_backend(
    pid: int | None = ...,
    *,
    writable: Literal[True],
    layout: EngineLayout = ...,
) -> BridgeBackend: ...


# A `writable` only known at runtime narrows to the common base, which `BridgeBackend` is.
@overload
def open_backend(
    pid: int | None = ...,
    *,
    writable: bool,
    layout: EngineLayout = ...,
) -> MemoryBackend: ...


def open_backend(
    pid: int | None = None,
    *,
    writable: bool = False,
    layout: EngineLayout = LAYOUT_ROTWK_201,
) -> MemoryBackend:
    """A connected backend on the running game: `BridgeBackend` if `writable`, else read-only.

    The lower half of `attach`, for a caller that wants the backend itself - the CLI reads
    with no session, and `BridgeBackend`'s acknowledgement helpers are not on `Session`.

    The overloads are what make `writable=True` a *typed* promise of a `BridgeBackend`, so a
    caller reaching for `wait_until_idle` needs no cast and no runtime check.
    """
    if pid is None:
        found = find_game_processes()
        if not found:
            raise NoGameRunning(
                "no running game.dat - launch the game and start a match, or pass an explicit pid"
            )
        pid = found[0]

    try:
        source = ProcessMemory(pid, writable=writable)
    except PermissionError as exc:
        raise NotPermitted(
            f"{exc}\nthe game runs as administrator, so this shell must be elevated too"
        ) from exc
    except RuntimeError as exc:
        raise AttachError(str(exc)) from exc

    backend = BridgeBackend(source, layout=layout) if writable else MemoryBackend(source, layout)
    try:
        backend.connect()
    except BridgeUnavailable as exc:
        source.close()
        raise AttachError(
            f"{exc}\napply it with:  sage-patch apply live-bridge --in game.dat"
            "\n(live-bridge is experimental; keep the unpatched binary. Reading needs no patch - "
            "attach without writable=True.)"
        ) from exc
    except ConnectionRefused as exc:
        source.close()
        raise AttachError(f"cannot attach: {exc}") from exc
    return backend


def attach(
    pid: int | None = None,
    *,
    writable: bool = False,
    layout: EngineLayout = LAYOUT_ROTWK_201,
    apm_cap: int = DEFAULT_APM_CAP,
    player_index: int | None = None,
    godsight: bool = True,
    fog: bool = False,
    revives: ReviveLookup | None = None,
) -> Session:
    """A connected `Session` on the running game.

    ```python
    with sage_live.attach() as game:            # read-only
        print(game.observe().me.resources)

    with sage_live.attach(writable=True) as game:   # needs the live-bridge patch
        game.wait_for_match()
        game.select([o.object_id for o in game.observe().mine])
        game.move((1200.0, 880.0, 0.0))
    ```

    `player_index` overrides the seat read from the game, which is only useful for driving a
    game as another player - and only meaningful in a skirmish, where every seat is local.

    Upgrade names work immediately: the session is given a `LiveNames` reading the engine's own
    `TheUpgradeCenter`, so `research("Upgrade_MordorForgedBlades", id)` needs no game files.
    Thing, power and science names still need a `sage_live.utils.resolve.Resolver`; attach one with
    `session.names = resolver`.

    `fog=True` hides what the seat cannot currently see, so a policy has to scout for an
    opponent's army instead of reading it off the object table. It is off by default because it
    changes what every existing consumer observes; `godsight=False` is the companion switch and
    the two are independent - one drops objects, the other strips fields from the ones that
    remain. See `Observation.under_fog`.

    `revives` is the revive system's static half, which hero recruitment needs and which needs
    an ini load - pass a `sage_live.utils.statics.Statics`, or set `session.revives` later. Without
    it the session reads and orders everything else normally and refuses hero recruits.
    """
    backend = open_backend(pid, writable=writable, layout=layout)
    session = Session(
        backend,
        player_index=backend.local_player_index() if player_index is None else player_index,
        apm_cap=apm_cap,
        names=LiveNames(backend),
        godsight=godsight,
        fog=fog,
        revives=revives,
    )
    session.connect()
    return session
