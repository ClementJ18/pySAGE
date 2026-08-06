"""Shared setup for the `sage_live` examples: attach, order, and name the local player's units.

Every example needs the same few things - a writable handle on the running game, the local
player, and some units to order about - so they live here rather than being copied four times.

The attaching itself is `sage_live.attach`; this only turns its typed failures into the
one-line exits a script wants.
"""

from __future__ import annotations

from pathlib import Path

from sage_ini import Game, parse_file
from sage_ini.stats import ini_root
from sage_live.api.connect import AttachError, open_backend
from sage_live.api.observation import GameObject, PlayerState, Vec3
from sage_live.backends.bridge import BridgeBackend
from sage_replay import Order
from sage_utils.gameroot import resolve_game_root
from sage_utils.views import faction_for_side, starting_units

# The files the engine's `ThePlayerTemplateStore` loads, lowest priority first - its `InitFile`
# lines in `default/subsystemlegend.ini`. Loading just these is what keeps the starting roster
# cheap to read: a `PlayerTemplate` names its units as plain tokens, so none of the object tree
# (a minute of parsing) is needed to resolve them.
_PLAYER_TEMPLATE_FILES = ("default/playertemplate.ini", "playertemplate.ini")


def attach() -> BridgeBackend:
    """A connected, writable bridge onto the first running game.

    Exits with a readable message for the three ways this normally fails: no game running, an
    unelevated shell, and a `game.dat` that is not carrying the live-bridge patch. `attach`
    already phrases all three; this only turns them into an exit rather than a traceback.
    """
    try:
        return open_backend(writable=True)
    except AttachError as exc:
        raise SystemExit(str(exc)) from exc


def issue(backend: BridgeBackend, order: Order, label: str) -> bool:
    """Send one order and confirm the hook consumed it, reporting why if it did not."""
    if backend.send([order]) != 1:
        print(f"  {label}: refused")
        for diagnostic in backend.diagnostics:
            print(f"    ! {diagnostic}")
        return False
    if not backend.wait_until_idle():
        print(f"  {label}: written but never consumed - is the game paused?")
        return False
    return True


def local_player(backend: BridgeBackend) -> PlayerState:
    """The local player's own state, or a one-line exit when there is not one (the menu)."""
    player = backend.observe().me
    if player is None:
        raise SystemExit("no local player - still at the menu?")
    return player


def my_units(backend: BridgeBackend) -> list[GameObject]:
    """The local player's objects that are real units, not inert map markers.

    Uses real ownership (`mine`), not the template's Side. Those disagree: matching Side
    against the player's faction misses objects you own whose template is `Civilian`, and claims
    creep-owned lairs whose template is `Neutral`.
    """
    observation = backend.observe()
    if observation.me is None:
        raise SystemExit("no local player - still at the menu?")
    units = list(observation.find(owner=observation.local_player, has_body=True))
    if not units:
        raise SystemExit(f"no units owned by {observation.me.name} - has the match started?")
    return units


def faction_roster(game: str | Path, side: str) -> list[str]:
    """The templates a player of `side` is spawned with, from that faction's `PlayerTemplate`.

    `game` is an install folder or an ini tree, the same argument every other script takes.
    Only the PlayerTemplate files are parsed (see `_PLAYER_TEMPLATE_FILES`), which is instant -
    the starting units are raw name tokens, so nothing else has to be loaded to read them.
    """
    root = ini_root(resolve_game_root(game))
    loaded = Game()
    for name in _PLAYER_TEMPLATE_FILES:
        path = root / name
        if path.is_file():
            document = parse_file(path, resolve_includes=True, include_layers=(root,)).document
            loaded.load_document(document)
    faction = faction_for_side(loaded, side)
    if faction is None:
        raise SystemExit(f"no playable PlayerTemplate with Side = {side} under {root}")
    return starting_units(faction)


def starter_units(backend: BridgeBackend, game: str | Path | None = None) -> list[GameObject]:
    """The units a skirmish hands the local player at frame zero.

    Read from the faction's `PlayerTemplate`: `StartingUnit0..9` is where the engine keeps the
    starting roster, and the objects on the map carrying those templates are that spawn. A
    battalion is one object here - the horde the slot names, which is also what an order
    selects; its members carry the member template and are not matched. A slot that spawns
    something else in turn is not followed either: Edain's `FreeBuildPorterEgg` hatches a
    porter, and the porter's own template is what stands on the map.

    Nothing on a spawned object marks it as a starting unit, so `game` is what makes this
    exact. Without one there is no honest answer and this falls back to the first two owned
    objects, which is enough to demonstrate an order but is not the roster.
    """
    units = my_units(backend)
    if game is None:
        print("  (no --game: ordering the first two owned objects, not the starting roster)")
        return units[:2]

    roster = faction_roster(game, local_player(backend).faction)
    wanted = {name.lower() for name in roster}
    starters = [o for o in units if o.template_name.lower() in wanted]
    if not starters:
        print(f"  (nothing left of the roster {', '.join(roster)}; using the first two owned)")
        return units[:2]
    return starters


def centre_of(units: list[GameObject]) -> Vec3:
    return (
        sum(u.position[0] for u in units) / len(units),
        sum(u.position[1] for u in units) / len(units),
        sum(u.position[2] for u in units) / len(units),
    )


def describe(backend: BridgeBackend) -> None:
    observation = backend.observe()
    player = observation.me
    name = f"{player.name} ({player.faction})" if player else "unknown"
    where = f" bridge at {backend.section[0]:#010x}," if backend.section else ""
    print(f"attached:{where} local player [{observation.local_player}] {name}")
    print(f"frame {observation.frame}, {len(observation.objects)} objects")
