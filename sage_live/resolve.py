"""Turn code names into a specific build's integer ids, so a policy can talk in names.

`sage_live.orders` deliberately takes resolved integers: the package root stays install-free
and works with no game on disk. This module is the other half, and it is **not** re-exported
from `sage_live` because it imports `sage_ini` through `narrate.GameData` - import it from
here explicitly, the same split `sage_replay` uses for its own game-loading modules.

**Express policies over code names, never raw ids.** Edain renumbers its tables every release,
so an id baked into a policy silently means something different after an update, while a name
either resolves or fails loudly. That is why `retarget` exists for replays, and it is the same
argument live.

The id-space rules themselves live in `sage_replay.idspace`, shared with `narrate` (which
reads ids) and `retarget` (which writes them for another build). One rule, three callers.

`Resolver` satisfies `sage_live.naming.NameLookup`, so it can be handed straight to a
`Session` - `session.names = Resolver.from_root(...)` - and the session gains names in all
four spaces without importing anything from here.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sage_live.naming import UnknownDefinition, nearby
from sage_live.observation import Vec3
from sage_live.orders import (
    DEFAULT_CAST_OPTIONS,
    build_at,
    cast_at_location,
    cast_at_object,
    cast_self,
    purchase_power,
    recruit,
    research,
)
from sage_replay.idspace import IdSpaces, id_spaces
from sage_replay.narrate import GameData
from sage_replay.replay import Order

__all__ = ["Resolver", "UnknownDefinition"]


class Resolver:
    """Name → id for one loaded build, plus order constructors that take names."""

    def __init__(self, game: GameData, player_index: int = 0) -> None:
        self.game = game
        self.player_index = player_index
        self.spaces: IdSpaces = id_spaces(
            game.object_order, game.upgrades, game.specialpowers, game.sciences
        )

    @classmethod
    def from_root(
        cls,
        root: str | Path | Sequence[str | Path],
        bases: Sequence[str | Path] = (),
        player_index: int = 0,
    ) -> Resolver:
        """Load a game tree and build a resolver over it.

        A live install must be mounted first - its data lives in `.big` archives; see
        `tools/mount_game.py`.
        """
        return cls(GameData.from_root(root, bases=bases), player_index)

    def _lookup(self, space: str, names: Sequence[str], name: str) -> int:
        table = getattr(self.spaces, space)
        resolved = table.to_id(name)
        if resolved is None:
            raise UnknownDefinition(space, name, nearby(name, names))
        return resolved

    def thing(self, name: str) -> int:
        return self._lookup("things", self.game.object_order, name)

    def upgrade(self, name: str) -> int:
        return self._lookup("upgrades", self.game.upgrades, name)

    def power(self, name: str) -> int:
        return self._lookup("powers", self.game.specialpowers, name)

    def science(self, name: str) -> int:
        return self._lookup("sciences", self.game.sciences, name)

    def knows(self, space: str, name: str) -> bool:
        """Whether this build defines `name` in `space`, without raising."""
        table = getattr(self.spaces, space, None)
        return table is not None and table.to_id(name) is not None

    # Order constructors, mirroring `sage_live.orders` but taking names.

    def recruit(self, template: str) -> Order:
        return recruit(self.player_index, self.thing(template))

    def build(self, template: str, position: Vec3, angle: float = 0.0) -> Order:
        return build_at(self.player_index, self.thing(template), position, angle)

    def research(self, upgrade: str, building_id: int) -> Order:
        """`building_id` must name the building; 0 is silently discarded (see `orders.research`)."""
        return research(self.player_index, self.upgrade(upgrade), building_id)

    def purchase_power(self, science: str) -> Order:
        return purchase_power(self.player_index, self.science(science))

    def cast(self, power: str, options: int = 0, source_id: int = 0) -> Order:
        return cast_self(self.player_index, self.power(power), options, source_id)

    def cast_at(
        self,
        power: str,
        position: Vec3,
        options: int = DEFAULT_CAST_OPTIONS,
        source_id: int = 0,
    ) -> Order:
        return cast_at_location(self.player_index, self.power(power), position, options, source_id)

    def cast_on(self, power: str, target_id: int, position: Vec3, options: int = 1) -> Order:
        """`position` is where the target is; the engine records one on every object cast.

        No `source_id`: naming the caster stops the order working (see `orders.cast_at_object`).
        """
        return cast_at_object(self.player_index, self.power(power), target_id, position, options)
