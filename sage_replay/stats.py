"""Per-player match statistics from a replay's order stream, resolved against a loaded game.

Each occupied slot gets the counts a build-order review wants: structures built (the
`0x419`/`0x41A` build family, `0x463` wall segments, and `0x43F` plot unpacks/builds - all
standard thing-template ids; a template whose CastleBehavior unpacks a base for the player's
faction is labelled `... (unpacks <base>)`), recruits split into heroes / units /
other purchases: a template on some faction's `BuildableHeroesMP` list is a hero; otherwise
the recruited template's effective `KindOf` (climbing the `ChildObject` parent chain) decides -
`STRUCTURE` → building, `SELECTABLE` or a bare `HERO` KindOf → unit (a summoned/hero-like unit
is not a recruitable hero), anything else → other (e.g. the CPObject command-point purchase),
fortress heroes recruited by revive-submenu position
(`0x417` flag=True - resolved to hero names through each player's `ReviveList` when the
faction's roster is known, counting under `heroes`; an unresolvable position falls back to
the raw slot number in `fortress_hero_slots`),
upgrades researched at an object (`0x415`, kept by raw code name), the special-power casts
(`0x410`/`0x411`/`0x412`/`0x456`, kept by the power's raw code name in a `powers` bucket - hero
abilities, summons, unit toggles), horde combines (`0x423`, the Edain horde-merge - counted as
one action, since its only argument is a runtime target-horde ObjectId), and the spellbook
sciences in purchase order (`0x414`).

Four hooks let a mod overlay reshape the recruit/power picture without the core knowing any
mod-specific names: `relabel_power` rewrites a shared power's label from the caster's faction
`Side` (see the `PowerLabeler` alias), `power_recruits` records a power cast's permanently
fielded units as ordinary recruits instead of leaving them invisible inside `powers` (see the
`PowerRecruits` alias), `upgrade_recruits` does the same for an upgrade research that converts
the buyer into a unit engine-side (see the `UpgradeRecruits` alias), and `ignore_recruits`
drops raw template names whose real recruit signal is a later power cast (see `compute_stats`).
The core stays faction-agnostic and records raw code names when no hook is given.

Counts are *net of cancels*: a `0x418` unit cancel, `0x416` upgrade cancel, or `0x41B` build
cancel removes the issuing player's most-recent not-yet-cancelled matching order (LIFO) - unit
and upgrade cancels match by template/upgrade id, build cancels are id-less so purely
most-recent. A flag=True `0x418` cancels a hero revive: it resolves through the same
`ReviveList` (whose queued production it also clears) and matches the recruit by hero name -
or by raw slot number when both stayed unresolved. A cancel with nothing left to match is
ignored (never produces a negative count). AI players show empty stats (they issue no
recorded orders).

Every counted order is kept as a clocked `StatEvent` (seconds, category, label); the
per-category counters are views over that timeline, so downstream consumers (the `aggregate`
corpus command) can ask *when* a choice was made, not just how often.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from sage_ini.model.ini_objects import Object
from sage_replay.heroes import ReviveList
from sage_replay.narrate import POWER_ORDERS, GameData, player_label, revive_resolver
from sage_replay.replay import ReplayChunk, ReplayFile, first_bool, integer_arguments
from sage_utils.clock import clock

__all__ = [
    "PlayerStats",
    "PowerLabeler",
    "PowerRecruits",
    "StatEvent",
    "UpgradeRecruits",
    "compute_stats",
    "render_stats",
]

# A mod overlay's power relabeler: given the caster's faction `Side` token (or None when
# unknown) and the power's raw code name, returns the label to record - so a shared power
# reads faction-appropriately (Imladris's Lichtbringer element toggle vs an Angmar summon).
PowerLabeler = Callable[[str | None, str], str]

# A mod overlay's power-recruit resolver: given the caster's faction `Side` token (or None
# when unknown), that faction's per-map hero roster (`GameData.hero_roster_for`), the power's
# raw code name, and the cast's `Options` bitfield (the order's second Integer - the firing
# `CommandButton`'s Options, so two buttons that share one power definition on the same Side
# can still field different units, e.g. Angmar's SiegeTroll ram vs ThrallMaster orc summon),
# returns the template names the cast permanently fields (a name repeated expresses
# multiplicity; [] means the power fields nothing). The roster - not a `Side` - is what tells
# apart a mod's map-scoped sub-factions that share one power definition.
PowerRecruits = Callable[[str | None, Sequence[str], str, int], Sequence[str]]

# A mod overlay's upgrade-recruit resolver: given the purchaser's faction `Side` token (or
# None when unknown) and the researched upgrade's raw code name, returns the template names
# the purchase permanently fields. This covers conversions whose only player order is the
# `0x415` research itself: a `DoCommandUpgrade` behavior then presses the summon button
# engine-side (never entering the order stream), e.g. Edain's Angmar ThrallMaster and Rohan
# Hauptmann dedications. A cancelled research (`0x416`) takes its fielded units back with it.
UpgradeRecruits = Callable[[str | None, str], Sequence[str]]

# The build-family orders whose first Integer is the built structure's template id.
_BUILD_ORDERS = {0x419, 0x41A, 0x463}


def _effective_kindof(objects: dict[str, Object], name: str | None) -> frozenset[str]:
    """A template's effective `KindOf` tokens: the nearest explicit definition up the
    `ChildObject` parent chain, with `+X`/`-X` modifier tokens applied over the parent's set."""
    chain: list[Object] = []
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


def _bucket(kinds: frozenset[str], is_buildable_hero: bool) -> str:
    """Which stats bucket a recruited template belongs to. Only a template on a faction's
    `BuildableHeroesMP` list counts as a hero; a template that merely carries the HERO KindOf
    (a summoned hero, a hero-like unit) is a unit. `SELECTABLE` gates units so that system
    purchases riding the recruit order (CPObject) land in `other`, not `units`."""
    if is_buildable_hero:
        return "heroes"
    if "STRUCTURE" in kinds:
        return "buildings"
    if "SELECTABLE" in kinds or "HERO" in kinds:
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
    `fortress_hero_slots` counts only the `0x417` flag=True recruits whose revive-submenu
    position stayed unresolved (no faction roster, or an ambiguous dead-hero tail slot) -
    resolved ones count under `heroes` by name."""

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


def _pop_by_id[StackEntry: tuple](
    stack: list[StackEntry] | None, target: str | int
) -> StackEntry | None:
    """Pop and return the most-recent entry in `stack` whose key (first element) equals
    `target` (LIFO match; a template/upgrade id, or a hero-revive's resolved name). Entries are
    `(key, event, ...)` tuples - recruits and hero revives are plain pairs, the upgrades stack
    carries the research's injected recruit events as a third element. None if the stack is
    empty or has no match."""
    if not stack:
        return None
    for i in range(len(stack) - 1, -1, -1):
        if stack[i][0] == target:
            return stack.pop(i)
    return None


def _pop_last(stack: list[StatEvent] | None) -> StatEvent | None:
    """Pop the most-recent entry off an id-less LIFO `stack`, or None if it's empty."""
    return stack.pop() if stack else None


def compute_stats(
    replay: ReplayFile,
    data: GameData,
    *,
    relabel_power: PowerLabeler | None = None,
    power_recruits: PowerRecruits | None = None,
    upgrade_recruits: UpgradeRecruits | None = None,
    ignore_recruits: frozenset[str] = frozenset(),
    faction_overrides: dict[str, int] | None = None,
) -> list[PlayerStats]:
    """Per-player stats in slot order (players who issued no counted orders are included so a
    silent slot - an AI, a spectator-ish player - is visible as empty rather than missing).
    `relabel_power`, if given, rewrites each power cast's label from the caster's faction
    `Side` (see the module docstring); without it powers record as their raw code name.
    `power_recruits`, if given, additionally injects a recruit-like `StatEvent` for every
    permanent unit a power cast fields (see the module docstring); without it a power cast
    only ever records under `powers`. `upgrade_recruits` does the same for a `0x415` research
    that converts the buyer into a unit engine-side; its injected events ride the upgrade's
    cancel-stack entry, so a `0x416` cancel removes them along with the research (unlike a
    power cast, a queued research can be cancelled). `ignore_recruits` (raw template code
    names) drops those
    recruits entirely: an overlay whose real recruit signal is a later power cast can suppress
    the elementless placeholder the player first fields (Edain's `BruchtalLichtbringerHorde`,
    whose Loremaster element is only known once its `power_recruits` toggle fires).
    `faction_overrides` (player name -> faction id) supplies
    the hero-roster faction for a player whose slot doesn't know it - a lobby Random records
    faction -1, so the aggregate path infers the rolled faction from the first pass's orders
    and recomputes with it."""
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
    # StatEvent it cancels; an upgrade entry also carries the recruit events its
    # `upgrade_recruits` injected, so a cancel takes the fielded units back with the research.
    # Builds are id-less, so the stack holds just the event. Hero-revive entries are keyed by
    # resolved hero name (the submenu position shifts between recruit and cancel), falling
    # back to the raw slot number when unresolved.
    recruits: dict[str, list[tuple[str | int, StatEvent]]] = {}
    upgrades: dict[str, list[tuple[str | int, StatEvent, tuple[StatEvent, ...]]]] = {}
    builds: dict[str, list[StatEvent]] = {}
    fortress: dict[str, list[tuple[str | int, StatEvent]]] = {}
    # Each player's revive submenu, replayed order by order (heroes.py).
    revives: dict[str, ReviveList | None] = {}

    def caster_faction_and_side(chunk: ReplayChunk, player: str) -> tuple[int | None, str | None]:
        """The issuing slot's faction id (with `faction_overrides` applied) and its `Side`
        token, either None when unknown - the gates the recruit hooks key on."""
        chunk_slot = replay.slot_for(chunk)
        faction_id = chunk_slot.faction if chunk_slot is not None else None
        if faction_overrides and player in faction_overrides:
            faction_id = faction_overrides[player]
        side = data.faction_side(faction_id) if faction_id is not None else None
        return faction_id, side

    for chunk in replay.chunks:
        ints = integer_arguments(chunk)
        player = player_label(replay, chunk)
        per = stats.setdefault(player, PlayerStats(player=player))
        seconds = chunk.timecode * spf

        if (chunk.order_type in _BUILD_ORDERS or chunk.order_type == 0x43F) and ints:
            # The 0x419/0x41A/0x463 build family and the 0x43F plot unpack/build all carry
            # standard thing-template ids (order_space_map.md `0x43F`). A template whose
            # CastleBehavior unpacks a base for the player's faction is counted under the
            # base's name too, so outpost/camp claims are visible as their own row.
            name = data.object_name(ints[0])
            label = (data.label(name) if name else None) or f"<object id {ints[0]}?>"
            chunk_slot = replay.slot_for(chunk)
            side: str | None = (
                data.faction_side(chunk_slot.faction) if chunk_slot is not None else None
            )
            base = data.castle_base(name, side)
            if base:
                label = f"{label} (unpacks {base})"
            event = StatEvent(seconds, "buildings", label)
            per.events.append(event)
            builds.setdefault(player, []).append(event)
        elif chunk.order_type == 0x417 and ints:
            if first_bool(chunk):
                hero = ints[0]
                if isinstance(hero, str):
                    # A translated replay stores the hero already resolved to its template name;
                    # it counts under `heroes` directly and keys the cancel stack by that name.
                    event = StatEvent(seconds, "heroes", data.label(hero) or hero)
                    key: str | int = hero
                elif replay.translated:
                    # A translated replay's unresolved slot stayed a raw int at translation time
                    # (no roster, or an ambiguous tail): keep it as an unresolved slot number
                    # rather than run the resolver, whose list state cannot be rebuilt here.
                    event = StatEvent(seconds, "fortress_hero_slots", hero)
                    key = hero
                else:
                    resolver = revive_resolver(revives, replay, chunk, data, faction_overrides)
                    name = resolver.recruit(seconds, hero) if resolver is not None else None
                    if name is not None:
                        event = StatEvent(seconds, "heroes", data.label(name) or name)
                    else:
                        event = StatEvent(seconds, "fortress_hero_slots", hero)
                    key = name if name is not None else hero
                per.events.append(event)
                fortress.setdefault(player, []).append((key, event))
            else:
                name = data.object_name(ints[0])
                if name in ignore_recruits:
                    # An overlay suppresses this template as a recruit: its real recruit
                    # signal arrives later as a power cast (Edain's elementless
                    # BruchtalLichtbringerHorde, whose Loremaster element - and so its row -
                    # is only fixed once the toggle its `power_recruits` reads fires).
                    continue
                label = data.object_label(ints[0])
                bucket = _bucket(
                    _effective_kindof(data.objects, name), data.is_buildable_hero(name)
                )
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
            # A dedication research converts the buyer into a unit engine-side (Edain's
            # ThrallMaster/Hauptmann - see the `UpgradeRecruits` alias): record the fielded
            # units as ordinary recruits, attached to the upgrade's cancel-stack entry so a
            # 0x416 cancel takes them back with the research.
            fielded: tuple[StatEvent, ...] = ()
            if upgrade_recruits is not None:
                _, side = caster_faction_and_side(chunk, player)
                fielded = tuple(
                    StatEvent(
                        seconds,
                        _bucket(
                            _effective_kindof(data.objects, name), data.is_buildable_hero(name)
                        ),
                        data.label(name) or name,
                    )
                    for name in upgrade_recruits(side, upgrade)
                )
                per.events.extend(fielded)
            upgrades.setdefault(player, []).append((ints[0], event, fielded))
        elif chunk.order_type == 0x414 and len(ints) >= 2:
            science = data.label(data.science(ints[1])) or f"science {ints[1]}?"
            per.events.append(StatEvent(seconds, "sciences", science))
        elif chunk.order_type in POWER_ORDERS and ints:
            # A special-power cast (self / at-location / at-object / global). The power id is
            # the first Integer; keep the raw code name so an overlay's `relabel_power` and its
            # tracked sets match, then let the overlay rename it from the caster's faction Side.
            raw_power = data.special_power(ints[0]) or f"<power id {ints[0]}?>"
            power = raw_power
            faction_id: int | None = None
            side = None
            if relabel_power is not None or power_recruits is not None:
                faction_id, side = caster_faction_and_side(chunk, player)
            if relabel_power is not None:
                power = relabel_power(side, raw_power)
            per.events.append(StatEvent(seconds, "powers", power))
            if power_recruits is not None:
                # A power that permanently fields units (an Edain summon, a Leuchtfeuer
                # signal fire) counts them as ordinary recruits, so they merge with normal
                # recruits of the same template downstream. They never join the `recruits`
                # cancel stack: a cast cannot be cancelled, and a later 0x418 unit-cancel
                # must not consume one. The second Integer is the firing CommandButton's
                # `Options` bitfield (order_space_map.md), which is what lets the hook tell
                # two same-Side buttons sharing one power definition apart.
                roster = (
                    data.hero_roster_for(replay.header.metadata.map_file, faction_id)
                    if faction_id is not None
                    else []
                )
                # The Options bitfield is never an id, so translation leaves it an int.
                options = ints[1] if len(ints) > 1 and isinstance(ints[1], int) else 0
                for name in power_recruits(side, roster, raw_power, options):
                    label = data.label(name) or name
                    bucket = _bucket(
                        _effective_kindof(data.objects, name), data.is_buildable_hero(name)
                    )
                    per.events.append(StatEvent(seconds, bucket, label))
        elif chunk.order_type == 0x423:
            # Combine hordes (Edain horde-merge). The only argument is a runtime ObjectId
            # (the target/primary horde), so there is nothing to name - count the action
            # itself under a constant label (order_space_map.md `0x423`).
            per.events.append(StatEvent(seconds, "combines", "horde combine"))
        elif chunk.order_type == 0x418 and ints:
            if first_bool(chunk):
                # Cancel a queued hero revive (flag=True): the id is the hero's *current*
                # submenu position, so resolve it through the same ReviveList - which also
                # un-queues the production, keeping later fielding-collapses correct - and
                # match the recruit by hero name (raw slot when both stayed unresolved). A
                # translated replay already carries the resolved name (pop by name) or an
                # unresolved slot number (pop by slot), so its resolver is skipped.
                hero = ints[0]
                if isinstance(hero, str) or replay.translated:
                    key = hero
                else:
                    resolver = revive_resolver(revives, replay, chunk, data, faction_overrides)
                    name = resolver.cancel(seconds, hero) if resolver is not None else None
                    key = name if name is not None else hero
                cancelled = _pop_by_id(fortress.get(player), key)
            else:
                # Cancel a queued non-fortress recruit: pop the issuing player's most-recent
                # not-yet-cancelled 0x417 (flag=False) recruit with a matching template id.
                cancelled = _pop_by_id(recruits.get(player), ints[0])
            if cancelled is not None:
                _drop(per.events, cancelled[1])
        elif chunk.order_type == 0x416 and ints:
            # Cancel a queued upgrade research: pop the most-recent not-yet-cancelled 0x415
            # research with a matching upgrade id - and take back any recruit events its
            # `upgrade_recruits` fielded (the cancelled conversion never happens).
            popped = _pop_by_id(upgrades.get(player), ints[0])
            if popped is not None:
                _drop(per.events, popped[1])
                for fielded_event in popped[2]:
                    _drop(per.events, fielded_event)
        elif chunk.order_type == 0x41B:
            # Cancel a queued build (0x419/0x41A/0x463/0x43F family). Genuinely id-less, so
            # this pops whatever build is most recent in the issuing player's stack.
            build_event = _pop_last(builds.get(player))
            if build_event is not None:
                _drop(per.events, build_event)

    return list(stats.values())


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
            f"    {i:2d}. [{clock(seconds)}] {science}"
            for i, (seconds, science) in enumerate(per.sciences, start=1)
        )
        lines.append("")
    return lines
