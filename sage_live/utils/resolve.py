"""Turn code names into a specific build's integer ids, so a policy can talk in names.

`sage_live.api.orders` takes resolved integers; this is the other half. It imports `sage_ini`, so it
is not re-exported from `sage_live` - import it from here.

Write policies in names, never raw ids: Edain renumbers its tables every release, and a name either
resolves or fails loudly. The id-space rules are `sage_replay.idspace`'s. `Resolver` satisfies
`sage_live.utils.naming.NameLookup`, so it can be handed to a `Session` (`session.names =
Resolver.from_root(...)`).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sage_ini.model.game import Game
from sage_live.api.observation import Vec3
from sage_live.api.orders import (
    DEFAULT_CAST_OPTIONS,
    build_at,
    cast_at_location,
    cast_at_object,
    cast_self,
    purchase_power,
    recruit,
    research,
)
from sage_live.utils.naming import UnknownDefinition, nearby
from sage_replay.idspace import IdSpaces, id_spaces
from sage_replay.narrate import GameData
from sage_replay.replay import Order

__all__ = ["Resolver", "UnknownDefinition"]


class Resolver:
    """Name to id for one loaded build, plus order constructors that take names.

    Matching is case-insensitive where that is unambiguous, like every other name lookup in
    `sage_live`. A name the table spells two ways (RotWK + Edain has `SCIENCE_IMLADRIS` and
    `SCIENCE_Imladris`, different sciences) still needs the exact spelling.
    """

    def __init__(self, game: GameData, player_index: int = 0) -> None:
        self.game = game
        self.player_index = player_index
        self._folded: dict[str, dict[str, int]] = {}
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

        Mount a live install's `.big` archives first (`tools/mount_game.py`). To use `Statics` as
        well, load the game once and use `from_game` for both.
        """
        return cls(GameData.from_root(root, bases=bases), player_index)

    @classmethod
    def from_game(
        cls,
        game: Game,
        root: str | Path | Sequence[str | Path],
        bases: Sequence[str | Path] = (),
        player_index: int = 0,
    ) -> Resolver:
        """Build over an already-loaded `Game`, so `Resolver` and `Statics` share one load.

        `root` is still needed for the `ThingTemplate` registration order (see
        `GameData.from_game`).
        """
        return cls(GameData.from_game(game, root, bases=bases), player_index)

    def _names(self, space: str) -> Sequence[str]:
        """The registration order behind one id space, or empty for a space that has none. One
        mapping, so `knows` and the lookups cannot disagree.
        """
        return {
            "things": self.game.object_order,
            "upgrades": self.game.upgrades,
            "powers": self.game.specialpowers,
            "sciences": self.game.sciences,
        }.get(space, ())

    def _unambiguous(self, space: str, names: Sequence[str]) -> dict[str, int]:
        """Lowercased name to id, for names this build spells exactly one way; names with two
        spellings are left out. Cached per space.
        """
        cached = self._folded.get(space)
        if cached is None:
            table = getattr(self.spaces, space)
            seen: dict[str, int | None] = {}
            for name in names:
                key = name.lower()
                # Second sighting: mark it ambiguous rather than letting the first win.
                seen[key] = None if key in seen else table.to_id(name)
            cached = {k: v for k, v in seen.items() if v is not None}
            self._folded[space] = cached
        return cached

    def _resolve(self, space: str, name: str) -> int | None:
        """`name`'s id in `space`: exact first, then case-insensitive where unambiguous."""
        table = getattr(self.spaces, space, None)
        if table is None:
            return None
        resolved = table.to_id(name)
        if resolved is None:
            resolved = self._unambiguous(space, self._names(space)).get(name.lower())
        return resolved

    def _lookup(self, space: str, names: Sequence[str], name: str) -> int:
        resolved = self._resolve(space, name)
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
        """Whether this build defines `name` in `space`, without raising - answering exactly what
        the matching lookup would, case handling included.
        """
        return self._resolve(space, name) is not None

    # Order constructors, mirroring `sage_live.api.orders` but taking names.

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
