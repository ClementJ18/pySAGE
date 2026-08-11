"""Turn code names into a specific build's integer ids, so a policy can talk in names.

`sage_live.api.orders` deliberately takes resolved integers: the package root stays install-free
and works with no game on disk. This module is the other half, and it is **not** re-exported
from `sage_live` because it imports `sage_ini` through `narrate.GameData` - import it from
here explicitly, the same split `sage_replay` uses for its own game-loading modules.

**Express policies over code names, never raw ids.** Edain renumbers its tables every release,
so an id baked into a policy silently means something different after an update, while a name
either resolves or fails loudly. That is why `retarget` exists for replays, and it is the same
argument live.

The id-space rules themselves live in `sage_replay.idspace`, shared with `narrate` (which
reads ids) and `retarget` (which writes them for another build). One rule, three callers.

`Resolver` satisfies `sage_live.utils.naming.NameLookup`, so it can be handed straight to a
`Session` - `session.names = Resolver.from_root(...)` - and the session gains names in all
four spaces without importing anything from here.
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
    """Name → id for one loaded build, plus order constructors that take names.

    **Matching is case-insensitive where that is unambiguous**, because ini identifiers are and
    because every other name surface in `sage_live` already honours it - `Statics` and
    `Observation.find` both lowercase. Without this a name accepted by one half of the library
    is rejected by the other: `GondorMarketplace` classifies fine and resolves to nothing,
    and the real template is `GondorMarketPlace`.

    Where it is *not* unambiguous the exact spelling is still required. A table may hold two
    names differing only in case, and RotWK + Edain holds one such pair - `SCIENCE_IMLADRIS`
    and `SCIENCE_Imladris` are different sciences with different ids. Folding those together
    would answer with whichever came first, so a colliding name keeps failing with its
    suggestions instead.
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

        A live install must be mounted first - its data lives in `.big` archives; see
        `tools/mount_game.py`.

        **Loads the tree itself, so a caller that also wants `Statics` should not use this** -
        both would parse the same eleven thousand definitions independently. Load once and use
        `from_game` for that; see its note.
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
        """Build over an already-loaded `Game`, without rebuilding the object model.

        The pairing this exists for is `Resolver` and `Statics` over one tree: `Statics` has
        always taken a `Game`, and this is the other half, so a live session can have names and
        static facts for the price of one load rather than two.

        `root` is still needed for the `ThingTemplate` registration order every id resolves
        through - see `GameData.from_game`, which explains why a `Game` cannot supply it.
        """
        return cls(GameData.from_game(game, root, bases=bases), player_index)

    def _names(self, space: str) -> Sequence[str]:
        """The registration order behind one id space, or empty for a space that has none.

        One mapping, so `knows` cannot answer a different question from `thing` - which is the
        same class of split this resolver's case handling exists to close.
        """
        return {
            "things": self.game.object_order,
            "upgrades": self.game.upgrades,
            "powers": self.game.specialpowers,
            "sciences": self.game.sciences,
        }.get(space, ())

    def _unambiguous(self, space: str, names: Sequence[str]) -> dict[str, int]:
        """Lowercased name → id, for names this build spells exactly one way.

        A name with two spellings is left out entirely rather than mapped to either, so an
        ambiguous lookup fails as it always did. Built once per space and cached: the tables
        run to five figures and a policy resolves the same handful of names every cycle.
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
        """Whether this build defines `name` in `space`, without raising.

        Answers exactly what `thing`/`upgrade`/`power`/`science` would, case handling included:
        a `knows` that said yes to a name the resolver then refused is how a startup check
        passes and the first order fails.
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
