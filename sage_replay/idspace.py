"""The four name↔id spaces a replay order references, and the offsets that relate them.

A content-bearing order carries an integer that indexes one of four registration orders -
thing templates, upgrades, special powers, sciences - each with its own constant offset. The
rules are derived in [`order_space_map.md`](order_space_map.md) section A.

**This module is the single place those offsets live.** Both directions need them: `narrate`
turns an id into a name, `retarget` turns a name into another build's id, and a live session
does the same thing against the running game. Holding one rule in three places is how a
correction gets applied twice and missed once.

Nothing here imports `sage_ini`; it works on plain sequences of names. `id_spaces` is the
convenience that reads them off a loaded `narrate.GameData`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

__all__ = [
    "POWER_OFFSET",
    "SCIENCE_OFFSET",
    "THING_OFFSET",
    "UPGRADE_OFFSET",
    "IdSpace",
    "IdSpaces",
    "id_spaces",
]

# Thing templates, special powers and sciences are a plain 1-based index into their
# registration order.
THING_OFFSET = 1
POWER_OFFSET = 1
SCIENCE_OFFSET = 1

# Upgrade ids sit 3 above their 0-based `upgrades` index (DefaultUpgrade = id 3;
# ground-truthed by an in-game replay survey - order_space_map.md, `0x415`).
#
# **The 3 is three upgrades the ini tree does not contain.** A replay carries the engine's own
# registration index, and the engine registers `Upgrade_Veterancy_VETERAN`, `_ELITE` and
# `_HEROIC` as indices 0-2 before parsing any `Upgrade` block - none of the three is defined in
# ini anywhere. So this offset exists only because the table is rebuilt from ini; a consumer
# reading `TheUpgradeCenter` out of a running game needs no offset (see `sage_live.memory`).
# Confirmed live: 976/976 templates satisfy `engine index == ini index + 3`.
UPGRADE_OFFSET = 3


@dataclass(frozen=True)
class IdSpace:
    """One registration order plus the offset between an index and a replay id.

    Resolution is total in both directions: an id outside the table, or a name the build does
    not define, answers None rather than raising. A replay routinely references definitions a
    differently-modded install has never heard of, and that is a diagnostic, not an error.
    """

    names: Sequence[str]
    offset: int

    def to_id(self, name: str) -> int | None:
        """The replay id for `name`, or None when this build does not define it."""
        index = self._index.get(name)
        return None if index is None else index + self.offset

    def to_name(self, replay_id: int) -> str | None:
        """The definition `replay_id` names, or None when it falls outside the table."""
        index = replay_id - self.offset
        return self.names[index] if 0 <= index < len(self.names) else None

    def __len__(self) -> int:
        return len(self.names)

    @property
    def _index(self) -> dict[str, int]:
        # Built on demand and cached on the frozen instance; the tables run to five figures,
        # and retargeting a corpus asks for the same lookup thousands of times.
        cached = self.__dict__.get("_index_cache")
        if cached is None:
            cached = {name: i for i, name in enumerate(self.names)}
            object.__setattr__(self, "_index_cache", cached)
        return cached


@dataclass(frozen=True)
class IdSpaces:
    """All four spaces for one build."""

    things: IdSpace
    upgrades: IdSpace
    powers: IdSpace
    sciences: IdSpace


def id_spaces(
    object_order: Sequence[str],
    upgrades: Sequence[str],
    specialpowers: Sequence[str],
    sciences: Sequence[str],
) -> IdSpaces:
    """Build the four spaces from a build's registration orders.

    Takes plain sequences rather than a `GameData` so this stays usable from anything that
    can name definitions in order - a loaded game, a live process, or a test.
    """
    return IdSpaces(
        things=IdSpace(object_order, THING_OFFSET),
        upgrades=IdSpace(upgrades, UPGRADE_OFFSET),
        powers=IdSpace(specialpowers, POWER_OFFSET),
        sciences=IdSpace(sciences, SCIENCE_OFFSET),
    )
