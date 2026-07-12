"""Per-player match statistics from a replay's order stream, resolved against a loaded game.

Each occupied slot gets the counts a build-order review wants: structures built (the
`0x419`/`0x41A` build family, `0x463` wall segments, and `0x43F` plot unpacks/builds - all
standard thing-template ids; a template whose CastleBehavior unpacks a base for the player's
faction is labelled `... (unpacks <base>)`), recruits split into heroes / units /
other purchases by the recruited template's effective `KindOf` (climbing the `ChildObject`
parent chain: `HERO` → hero, `SELECTABLE` non-structure → unit, anything else → other, e.g.
the CPObject command-point purchase), fortress heroes recruited by command slot (`0x417`
flag=True - the slot is a dynamic revive-submenu position, so only the slot number is known),
upgrades researched at an object (`0x415`, kept by raw code name), the special-power casts
(`0x410`/`0x411`/`0x412`/`0x456`, kept by the power's raw code name in a `powers` bucket - hero
abilities, summons, unit toggles), horde combines (`0x423`, the Edain horde-merge - counted as
one action, since its only argument is a runtime target-horde ObjectId), and the spellbook
sciences in purchase order (`0x414`).

A `relabel_power` hook lets a mod overlay rewrite a power's label from the caster's faction
`Side`, since one `SpecialPower` definition can serve several factions (Edain's four shared
`...ThrallMasterSummon...` powers are Angmar summons, but the Imladris Lichtbringer's element
toggle - Earth/Light/Water/Air - fires the very same four; only the caster's Side tells them
apart). The core stays faction-agnostic and records the raw code name when no hook is given.

Counts are *net of cancels*: a `0x418` unit cancel, `0x416` upgrade cancel, or `0x41B` build
cancel removes the issuing player's most-recent not-yet-cancelled matching order (LIFO) - unit
and upgrade cancels match by template/upgrade id, build cancels are id-less so purely
most-recent. A cancel with nothing left to match is ignored (never produces a negative count).
AI players show empty stats (they issue no recorded orders).

Every counted order is kept as a clocked `StatEvent` (seconds, category, label); the
per-category counters are views over that timeline, so downstream consumers (the `aggregate`
corpus command) can ask *when* a choice was made, not just how often.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from sage_replay.narrate import _POWER_ORDERS, GameData, _first_bool, _integers, _player_label
from sage_replay.replay import ReplayFile

__all__ = ["PlayerStats", "PowerLabeler", "StatEvent", "compute_stats", "render_stats"]

# A mod overlay's power relabeler: given the caster's faction `Side` token (or None when
# unknown) and the power's raw code name, returns the label to record - so a shared power
# reads faction-appropriately (Imladris's Lichtbringer element toggle vs an Angmar summon).
PowerLabeler = Callable[[str | None, str], str]

# The build-family orders whose first Integer is the built structure's template id.
_BUILD_ORDERS = {0x419, 0x41A, 0x463}


def _effective_kindof(objects: dict, name: str | None) -> frozenset[str]:
    """A template's effective `KindOf` tokens: the nearest explicit definition up the
    `ChildObject` parent chain, with `+X`/`-X` modifier tokens applied over the parent's set."""
    chain = []
    obj = objects.get(name) if name is not None else None
    while obj is not None:
        chain.append(obj)
        obj = getattr(obj, "parent", None)

    kinds: set[str] = set()
    for owner in reversed(chain):  # root first, so a child's override/modifiers win
        raw = owner._fields.get("KindOf")
        if raw is None:
            continue
        values = raw if isinstance(raw, list) else [raw]
        tokens = [t.upper() for v in values for t in str(v).split()]
        if not any(t.startswith(("+", "-")) for t in tokens):
            kinds = set()  # a full redefinition replaces the inherited set
        for token in tokens:
            if token.startswith("-"):
                kinds.discard(token[1:])
            else:
                kinds.add(token.lstrip("+"))
    kinds.discard("NONE")
    return frozenset(kinds)


def _bucket(kinds: frozenset[str]) -> str:
    """Which stats bucket a recruited template belongs to. `SELECTABLE` gates units so that
    system purchases riding the recruit order (CPObject) land in `other`, not `units`."""
    if "HERO" in kinds:
        return "heroes"
    if "STRUCTURE" in kinds:
        return "buildings"
    if "SELECTABLE" in kinds:
        return "units"
    return "other"


@dataclass(slots=True, frozen=True)
class StatEvent:
    """One counted order, clocked in match seconds. `label` is a template label for the
    template categories, and the command-slot number (an int) for `fortress_hero_slots`."""

    seconds: float
    # "buildings" | "units" | "heroes" | "other" | "fortress_hero_slots" | "sciences" |
    # "upgrades" | "powers" | "combines"
    category: str
    label: str | int


@dataclass(slots=True)
class PlayerStats:
    """One player's tallies, kept as the clocked `events` timeline (in order-stream order).
    The category accessors are views over it: counters map a template label to how many
    orders were issued; `sciences` keeps purchase order as (seconds, label);
    `fortress_hero_slots` counts the `0x417` flag=True recruits per command slot (the hero
    behind a slot is runtime state)."""

    player: str
    events: list[StatEvent] = field(default_factory=list)

    def _counter(self, category: str) -> Counter:
        return Counter(e.label for e in self.events if e.category == category)

    @property
    def buildings(self) -> Counter:
        return self._counter("buildings")

    @property
    def units(self) -> Counter:
        return self._counter("units")

    @property
    def heroes(self) -> Counter:
        return self._counter("heroes")

    @property
    def other(self) -> Counter:
        return self._counter("other")

    @property
    def upgrades(self) -> Counter:
        return self._counter("upgrades")

    @property
    def powers(self) -> Counter:
        return self._counter("powers")

    @property
    def combines(self) -> Counter:
        return self._counter("combines")

    @property
    def fortress_hero_slots(self) -> Counter:
        return self._counter("fortress_hero_slots")

    @property
    def sciences(self) -> list[tuple[float, str]]:
        return [(e.seconds, str(e.label)) for e in self.events if e.category == "sciences"]

    def to_dict(self) -> dict:
        return {
            "player": self.player,
            "buildings": dict(self.buildings.most_common()),
            "units": dict(self.units.most_common()),
            "heroes": dict(self.heroes.most_common()),
            "other": dict(self.other.most_common()),
            "upgrades": dict(self.upgrades.most_common()),
            "powers": dict(self.powers.most_common()),
            "combines": dict(self.combines.most_common()),
            "fortress_hero_slots": {
                str(slot): count for slot, count in sorted(self.fortress_hero_slots.items())
            },
            "sciences": [{"seconds": seconds, "science": name} for seconds, name in self.sciences],
            "timeline": [
                {"seconds": e.seconds, "category": e.category, "label": e.label}
                for e in self.events
            ],
        }


def _drop(events: list[StatEvent], event: StatEvent) -> None:
    """Remove the StatEvent object `event` (by identity, not equality - two recruits of the
    same template in the same second compare equal) from `events`."""
    for i, existing in enumerate(events):
        if existing is event:
            del events[i]
            return


def _pop_by_id(stack: list[tuple[int, StatEvent]] | None, target: int) -> StatEvent | None:
    """Pop the most-recent entry in `stack` whose id equals `target` (LIFO id match), or None
    if the stack is empty or has no match."""
    if not stack:
        return None
    for i in range(len(stack) - 1, -1, -1):
        if stack[i][0] == target:
            return stack.pop(i)[1]
    return None


def _pop_last(stack: list[StatEvent] | None) -> StatEvent | None:
    """Pop the most-recent entry off an id-less LIFO `stack`, or None if it's empty."""
    return stack.pop() if stack else None


def compute_stats(
    replay: ReplayFile, data: GameData, *, relabel_power: PowerLabeler | None = None
) -> list[PlayerStats]:
    """Per-player stats in slot order (players who issued no counted orders are included so a
    silent slot - an AI, a spectator-ish player - is visible as empty rather than missing).
    `relabel_power`, if given, rewrites each power cast's label from the caster's faction
    `Side` (see the module docstring); without it powers record as their raw code name."""
    spf = replay.seconds_per_frame
    stats: dict[str, PlayerStats] = {}
    for slot in replay.header.metadata.players:
        name = slot.human_name or (
            slot.computer_difficulty.name if slot.computer_difficulty else None
        )
        if name:
            stats[name] = PlayerStats(player=name)

    # LIFO match stacks for the cancel orders (0x418/0x416/0x41B), keyed by player. Recruits
    # and upgrades are id-matched, so each entry keeps the template/upgrade id alongside the
    # StatEvent it cancels; builds are id-less, so the stack holds just the event.
    recruits: dict[str, list[tuple[int, StatEvent]]] = {}
    upgrades: dict[str, list[tuple[int, StatEvent]]] = {}
    builds: dict[str, list[StatEvent]] = {}

    for chunk in replay.chunks:
        ints = _integers(chunk)
        player = _player_label(replay, chunk)
        per = stats.setdefault(player, PlayerStats(player=player))
        seconds = chunk.timecode * spf

        if (chunk.order_type in _BUILD_ORDERS or chunk.order_type == 0x43F) and ints:
            # The 0x419/0x41A/0x463 build family and the 0x43F plot unpack/build all carry
            # standard thing-template ids (0x43F's earlier +2 reading was an adjacent-anchor
            # miscalibration; order_space_map.md `0x43F`). A template whose CastleBehavior
            # unpacks a base for the player's faction is counted under the base's name too,
            # so outpost/camp claims are visible as their own row.
            name = data.object_name(ints[0])
            label = (data.label(name) if name else None) or f"<object id {ints[0]}?>"
            chunk_slot = replay.slot_for(chunk)
            side = data.faction_side(chunk_slot.faction) if chunk_slot is not None else None
            base = data.castle_base(name, side)
            if base:
                label = f"{label} (unpacks {base})"
            event = StatEvent(seconds, "buildings", label)
            per.events.append(event)
            builds.setdefault(player, []).append(event)
        elif chunk.order_type == 0x417 and ints:
            if _first_bool(chunk):
                per.events.append(StatEvent(seconds, "fortress_hero_slots", ints[0]))
            else:
                name = data.object_name(ints[0])
                label = data.object_label(ints[0])
                bucket = _bucket(_effective_kindof(data.objects, name))
                event = StatEvent(seconds, bucket, label)
                per.events.append(event)
                recruits.setdefault(player, []).append((ints[0], event))
        elif chunk.order_type == 0x415 and ints:
            # Research an upgrade at a building/battalion. The label is the raw code name,
            # never the localized DisplayName, so `aggregate`'s tracked-upgrade set (raw
            # ini names) matches whatever `--localized` says.
            upgrade = data.upgrade(ints[0]) or f"<upgrade id {ints[0]}?>"
            event = StatEvent(seconds, "upgrades", upgrade)
            per.events.append(event)
            upgrades.setdefault(player, []).append((ints[0], event))
        elif chunk.order_type == 0x414 and len(ints) >= 2:
            science = data.label(data.science(ints[1])) or f"science {ints[1]}?"
            per.events.append(StatEvent(seconds, "sciences", science))
        elif chunk.order_type in _POWER_ORDERS and ints:
            # A special-power cast (self / at-location / at-object / global). The power id is
            # the first Integer; keep the raw code name so an overlay's `relabel_power` and its
            # tracked sets match, then let the overlay rename it from the caster's faction Side.
            power = data.special_power(ints[0]) or f"<power id {ints[0]}?>"
            if relabel_power is not None:
                chunk_slot = replay.slot_for(chunk)
                side = data.faction_side(chunk_slot.faction) if chunk_slot is not None else None
                power = relabel_power(side, power)
            per.events.append(StatEvent(seconds, "powers", power))
        elif chunk.order_type == 0x423:
            # Combine hordes (Edain horde-merge). The only argument is a runtime ObjectId
            # (the target/primary horde), so there is nothing to name - count the action
            # itself under a constant label (order_space_map.md `0x423`).
            per.events.append(StatEvent(seconds, "combines", "horde combine"))
        elif chunk.order_type == 0x418 and ints:
            # Cancel a queued non-fortress recruit: pop the issuing player's most-recent
            # not-yet-cancelled 0x417 (flag=False) recruit with a matching template id.
            cancelled = _pop_by_id(recruits.get(player), ints[0])
            if cancelled is not None:
                _drop(per.events, cancelled)
        elif chunk.order_type == 0x416 and ints:
            # Cancel a queued upgrade research: pop the most-recent not-yet-cancelled 0x415
            # research with a matching upgrade id.
            cancelled = _pop_by_id(upgrades.get(player), ints[0])
            if cancelled is not None:
                _drop(per.events, cancelled)
        elif chunk.order_type == 0x41B:
            # Cancel a queued build (0x419/0x41A/0x463/0x43F family). Genuinely id-less, so
            # this pops whatever build is most recent in the issuing player's stack.
            cancelled = _pop_last(builds.get(player))
            if cancelled is not None:
                _drop(per.events, cancelled)

    return list(stats.values())


def _clock(seconds: float) -> str:
    return f"{int(seconds) // 60:d}:{int(seconds) % 60:02d}"


def _counter_lines(title: str, counter: Counter) -> list[str]:
    total = sum(counter.values())
    plural = "s" if len(counter) != 1 else ""
    lines = [f"  {title}: {total} ({len(counter)} type{plural})"]
    lines.extend(f"    {count:3d}x {label}" for label, count in counter.most_common())
    return lines


def render_stats(replay: ReplayFile, data: GameData) -> list[str]:
    """The stats as text lines: a per-player block of building/unit/hero counts and the
    ordered science purchases."""
    lines: list[str] = []
    for per in compute_stats(replay, data):
        slot = next((s for s in replay.header.metadata.players if s.human_name == per.player), None)
        faction = data.faction_label(slot.faction) if slot is not None else "?"
        lines.append(f"== {per.player}  [{faction}]")
        lines.extend(_counter_lines("Buildings", per.buildings))
        lines.extend(_counter_lines("Units", per.units))
        hero_total = sum(per.heroes.values()) + sum(per.fortress_hero_slots.values())
        lines.append(f"  Heroes: {hero_total}")
        lines.extend(f"    {count:3d}x {label}" for label, count in per.heroes.most_common())
        lines.extend(
            f"    {count:3d}x fortress hero (command slot {slot_index})"
            for slot_index, count in sorted(per.fortress_hero_slots.items())
        )
        if per.other:
            lines.extend(_counter_lines("Other purchases", per.other))
        if per.upgrades:
            lines.extend(_counter_lines("Upgrades", per.upgrades))
        if per.powers:
            lines.extend(_counter_lines("Powers", per.powers))
        if per.combines:
            lines.append(f"  Horde combines: {sum(per.combines.values())}")
        lines.append(f"  Sciences ({len(per.sciences)}, in order):")
        lines.extend(
            f"    {i:2d}. [{_clock(seconds)}] {science}"
            for i, (seconds, science) in enumerate(per.sciences, start=1)
        )
        lines.append("")
    return lines
