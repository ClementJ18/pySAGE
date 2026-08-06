"""Names to ids, without requiring a game install.

`sage_live.api.orders` takes resolved integers, and something has to turn `"MordorFighterHorde"`
into one. There are two sources for that mapping and they are not equivalent:

- **the engine's own registries**, read out of the running process. Exact for whatever mod is
  loaded, needs no files on disk, and cannot disagree with the game it is describing.
- **an ini load**, via `sage_live.utils.resolve.Resolver`. Works offline and covers all four id
  spaces, but reconstructs the numbering rather than reading it.

`NameLookup` is the interface both satisfy, so `Session` depends on neither. That matters for
more than tidiness: `resolve` imports `sage_ini`, and this package's root must stay
install-free, so `Session` cannot import the concrete resolver at all.

`LiveNames` is the live half. Two of the four registries are walked by `sage_live.backends.memory` -
`TheUpgradeCenter` and `TheThingFactory` - so upgrade and template names need nothing on disk.
`TheSpecialPowerStore` is walked too - it is a `std::vector` rather than a linked list, which
is why the first pass missed it. `TheScienceStore` has not been walked and says so plainly
rather than guessing; when it is, it lands here and every caller gains it without a change.

The two halves are not equally sure of themselves. An upgrade template carries its own index,
so its id is *read*; a thing template does not, so its id is its position in the walked list.
`thing` documents what corroborates that and what has not been checked.

**Express policies over code names, never raw ids.** Edain renumbers its tables every release,
so an id baked into a policy silently means something different after an update, while a name
either resolves or fails loudly.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol, runtime_checkable

from sage_replay.idspace import POWER_OFFSET, THING_OFFSET

__all__ = [
    "SPACES",
    "LiveNames",
    "LiveSource",
    "NameLookup",
    "NoNameLookup",
    "UnknownDefinition",
    "nearby",
]

# The four id spaces, named as `NameLookup` methods. `Session` resolves through these names,
# so adding a space is one entry here plus the method.
SPACES = ("thing", "upgrade", "power", "science")


class UnknownDefinition(KeyError):
    """A name this build does not define.

    Raised rather than resolved to a default: emitting an order with a wrong id would build
    the wrong thing and look like a policy bug, which is far harder to find than a failure at
    the point of the mistake.
    """

    def __init__(self, space: str, name: str, near: Sequence[str] = ()) -> None:
        hint = f" Did you mean: {', '.join(near)}?" if near else ""
        super().__init__(f"no {space} named {name!r} in this build.{hint}")
        self.space = space
        self.name = name


class NoNameLookup(RuntimeError):
    """An order was given a name, but this session has no way to resolve one.

    Distinct from `UnknownDefinition`: that one means the build does not define the name,
    this one means nothing was asked. Conflating them sends a caller hunting for a typo in a
    name that is perfectly correct.
    """


@runtime_checkable
class NameLookup(Protocol):
    """Name to id for one build, in each of the four spaces.

    Every method raises `UnknownDefinition` rather than returning a sentinel. A lookup that
    covers only some spaces raises it for the rest, so a partial source is usable without the
    caller having to ask what it supports.
    """

    def thing(self, name: str) -> int: ...

    def upgrade(self, name: str) -> int: ...

    def power(self, name: str) -> int: ...

    def science(self, name: str) -> int: ...


class UpgradeRow(Protocol):
    """The two fields `LiveNames` reads off a row of the engine's upgrade table.

    Declared read-only, as properties rather than variables: the concrete row is a *frozen*
    dataclass, and a protocol asking for a settable attribute is not satisfied by one.
    """

    @property
    def upgrade_id(self) -> int: ...

    @property
    def name(self) -> str: ...


class LiveSource(Protocol):
    """The two registries `LiveNames` reads.

    Stated structurally rather than as `MemoryBackend`, so this module stays independent of
    `ctypes` and of any particular backend - a test satisfies it with a dictionary and a tuple.
    """

    def upgrade_table(self) -> Mapping[int, UpgradeRow]: ...

    def thing_order(self) -> Sequence[str]: ...

    def power_order(self) -> Sequence[str]: ...


class LiveNames:
    """A `NameLookup` backed by the running game's own registries.

    Built from anything satisfying `LiveSource` - `MemoryBackend` and `BridgeBackend` both do.
    The names it answers with are the ones the loaded mod actually registered, so there is no
    way for it to drift from the process it is describing.

    Lookup is case-insensitive because ini identifiers are, and a policy written against the
    ini files should not fail on a capital the modder changed.
    """

    def __init__(self, source: LiveSource) -> None:
        self.source = source
        self._by_name: dict[str, int] | None = None
        self._spelled: list[str] = []
        self._things: dict[str, int] | None = None
        self._thing_names: Sequence[str] = ()
        self._powers: dict[str, int] | None = None
        self._power_names: Sequence[str] = ()

    @property
    def upgrades(self) -> dict[str, int]:
        """`{lowercased code name -> engine upgrade id}`, read once and cached.

        The engine's table is fixed once ini parsing is done, so this cannot go stale while
        the game runs.
        """
        if self._by_name is None:
            rows = list(self.source.upgrade_table().values())
            self._by_name = {row.name.lower(): row.upgrade_id for row in rows}
            # Kept as registered so a "did you mean" hint offers the real spelling.
            self._spelled = [row.name for row in rows]
        return self._by_name

    def upgrade(self, name: str) -> int:
        found = self.upgrades.get(name.lower())
        if found is None:
            raise UnknownDefinition("upgrade", name, nearby(name, self._spelled))
        return found

    @property
    def things(self) -> dict[str, int]:
        """`{lowercased template name -> order id}`, read once and cached.

        The id is the walk position plus `THING_OFFSET`, taken from `sage_replay.idspace` so
        the live path and the ini path cannot disagree about the rule.
        """
        if self._things is None:
            self._thing_names = self.source.thing_order()
            self._things = {
                name.lower(): index + THING_OFFSET for index, name in enumerate(self._thing_names)
            }
        return self._things

    def thing(self, name: str) -> int:
        """The order id for a `ThingTemplate` name.

        **Corroborated against the ini table, and the divergence is confined to the tail.**
        Measured in a live RotWK+Edain match (2026-07-30): this walk reads 11,142 templates
        against the ini tree's 11,132, and the two are *identical* up to index 11,086 - where
        the live walk has `FrmPrev_Inf` and the ini tree `SalvageCrate`. All 69 templates
        present in that match agreed exactly, spanning ids 3 to 10,994, so nothing in play was
        anywhere near the divergence.

        That matters because the two are independent reconstructions - one walks the engine's
        own `TheThingFactory`, the other parses ini - and agreement across that range is much
        stronger evidence than either gives alone. The ini rule is separately corpus-validated
        (491/491 `FOUNDATION_CONSTRUCT` orders, `order_space_map.md` section A).

        Still not a round trip: no order carrying an id from *this* table has been watched to
        build the thing it names. `sage_live.utils.resolve.Resolver` remains the path to prefer when
        a game tree is available, since only its rule has corpus backing - but a template
        below index 11,086 now resolves to the same number either way.
        """
        if not self.things:
            raise self._unwalked("thing", "TheThingFactory")
        found = self.things.get(name.lower())
        if found is None:
            raise UnknownDefinition("thing", name, nearby(name, self._thing_names))
        return found

    @property
    def powers(self) -> dict[str, int]:
        """`{lowercased power name -> order id}`, read once and cached."""
        if self._powers is None:
            self._power_names = self.source.power_order()
            self._powers = {
                name.lower(): index + POWER_OFFSET for index, name in enumerate(self._power_names)
            }
        return self._powers

    def power(self, name: str) -> int:
        """The order id for a `SpecialPower` name.

        **Corroborated exactly**, which is more than `thing` can claim. Measured live
        (2026-07-31): the engine's own `TheSpecialPowerStore` walks out 1,566 powers and the
        ini reconstruction reads 1,566, and the two agree position by position on **every one**
        - no empty name, no duplicate, no divergence anywhere including the tail. Two
        independent reconstructions agreeing completely is the strongest evidence this package
        has for any id space.
        """
        if not self.powers:
            raise self._unwalked("power", "TheSpecialPowerStore")
        found = self.powers.get(name.lower())
        if found is None:
            raise UnknownDefinition("power", name, nearby(name, self._power_names))
        return found

    def science(self, name: str) -> int:
        raise self._unwalked("science", "TheScienceStore")

    @staticmethod
    def _unwalked(space: str, store: str) -> NoNameLookup:
        return NoNameLookup(
            f"{space} names are not readable from the process yet ({store} has not been "
            f"walked). Attach a `sage_live.utils.resolve.Resolver` for {space} names, or pass "
            "an id."
        )


def nearby(name: str, names: Iterable[str], limit: int = 3) -> list[str]:
    """Candidates that contain `name`, or failing that share its first few characters.

    A typo in a template name is the common failure and the tables run to five figures, so a
    plain "not found" leaves the caller grepping. Deliberately cheap - substring matching, not
    an edit-distance pass over eleven thousand names.
    """
    lowered = name.lower()
    candidates = list(names)
    hits = [c for c in candidates if lowered in c.lower()]
    if not hits:
        head = lowered[:6]
        hits = [c for c in candidates if c.lower().startswith(head)]
    return hits[:limit]
