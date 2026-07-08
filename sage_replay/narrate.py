"""Turn a replay's order stream into English by resolving every content-bearing id
against a loaded game.

The order-space map (see `order_space_map.md`) pins how each order type's integer id
resolves to a definition: recruit (`0x417`) and build (`0x41A`) carry a ThingTemplate id
(`thing_template_order` index + 1); special powers (`0x410`/`0x411`/`0x412`/`0x456`) index
`game.specialpowers` + 1; a spellbook purchase (`0x414`) carries the science in its second
integer; a building upgrade (`0x415`) indexes `game.upgrades` with a +3 offset. `GameData`
loads those tables once from a game root (use `tools/mount_game.py` to mount a live install's
`.big` archives into one), and `narrate` walks the stream turning each recognised order into a
timecoded English line. Control/camera/selection orders carry no static id and are skipped.

A cast order's **second integer is the firing button's `Options` bitfield**; its `NEED_TARGET_*`
bits say what the power targets (the engine picks the order type to match): `NEED_TARGET_POS` (32)
→ a ground **location** (`0x411`, carrying a Position); `NEED_TARGET_ENEMY`/`NEUTRAL`/`ALLY_OBJECT`
(1/2/4) → a **target object** of that allegiance (`0x412`, carrying the target ObjectId + its
Position); no target bits → **self** (`0x410`) or a **global** cast (`0x456`). `_target_phrase`
decodes it. The trailing ObjectId is the casting source; naming the actual target object still
needs runtime ObjectId→template tracking.

Validated on RotWK+Edain: recruits, builds, powers, sciences and upgrades all resolve to
faction-consistent definitions (see the module test / the `narrate` CLI command).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from sage_ini.loader import load_game
from sage_ini.subsystems import thing_template_order
from sage_replay.replay import OrderArgumentType, ReplayChunk, ReplayFile

__all__ = ["GameData", "NarrationEvent", "narrate", "render"]

# Upgrade ids sit 3 above their `game.upgrades` index (order_space_map.md, `0x415`).
_UPGRADE_OFFSET = 3

# Order types whose first integer is a `game.specialpowers` id (self / at-location / at-object
# / untargeted). They differ only in targeting, which the argument list still carries.
_POWER_ORDERS = {0x410, 0x411, 0x412, 0x456}

# A special-power order's second integer is the firing `CommandButton`'s Options bitfield; its
# NEED_TARGET_* bits say what the power targets (and the engine picks the order type to match).
# Bit values validated against a RotWK/Edain replay ↔ each button's `Options` text.
_OPT_ENEMY = 0x1
_OPT_NEUTRAL = 0x2
_OPT_ALLY = 0x4
_OPT_POS = 0x20
_OPT_OBJECT = _OPT_ENEMY | _OPT_NEUTRAL | _OPT_ALLY


@dataclass(slots=True)
class GameData:
    """The resolution tables a narration needs, loaded once from a game root."""

    object_order: list[str]  # ThingTemplate registration order; replay id = index + 1
    objects: dict  # name -> Object, for Side
    specialpowers: list[str]
    sciences: list[str]
    upgrades: list[str]
    displaynames: dict[str, str]  # definition code-name -> localized DisplayName (when it has one)

    @classmethod
    def from_root(cls, root: str | Path) -> GameData:
        """Build from a game root holding `data/ini` (a live install must be mounted first;
        see `tools/mount_game.py`)."""
        game = load_game(root).game
        strings = {label.upper(): value for label, value in game.strings.items()}

        def localized(table) -> dict[str, str]:
            names: dict[str, str] = {}
            for name, obj in table.items():
                key = obj._fields.get("DisplayName")
                if isinstance(key, str) and key.upper() in strings:
                    names[name] = strings[key.upper()]
            return names

        return cls(
            object_order=thing_template_order(root),
            objects=dict(game.objects),
            specialpowers=list(game.specialpowers),
            sciences=list(game.sciences),
            upgrades=list(game.upgrades),
            # Objects and upgrades carry a localized DisplayName; special powers and sciences do
            # not, so they fall back to their raw code name (see `label`) — never prettified.
            displaynames={**localized(game.objects), **localized(game.upgrades)},
        )

    @staticmethod
    def _at(table: list[str], one_based: int) -> str | None:
        return table[one_based - 1] if 1 <= one_based <= len(table) else None

    def object_name(self, replay_id: int) -> str | None:
        return self._at(self.object_order, replay_id)

    def special_power(self, replay_id: int) -> str | None:
        return self._at(self.specialpowers, replay_id)

    def science(self, replay_id: int) -> str | None:
        return self._at(self.sciences, replay_id)

    def upgrade(self, replay_id: int) -> str | None:
        return self._at(self.upgrades, replay_id - _UPGRADE_OFFSET)

    def side_of(self, name: str) -> str | None:
        obj = self.objects.get(name)
        return obj._fields.get("Side") if obj is not None else None

    def label(self, name: str | None) -> str | None:
        """A definition's player-facing name: its localized DisplayName when it has one, else the
        raw code name exactly as written in the ini (never prettified). None passes through."""
        return self.displaynames.get(name, name) if name is not None else None

    def object_label(self, replay_id: int) -> str:
        """A recruited/built object's label — localized DisplayName or the raw template name (or a
        `<id ?>` marker when the id is out of range)."""
        name = self.object_name(replay_id)
        return (
            self.displaynames.get(name, name) if name is not None else f"<object id {replay_id}?>"
        )


def _allegiance(options: int) -> str:
    """The target's permitted allegiance from the `Options` bits, as a word ("enemy"/"friendly"
    /"" for any) — enemy or neutral reads as enemy; ally-only as friendly (Edain mind-control)."""
    hostile = options & (_OPT_ENEMY | _OPT_NEUTRAL)
    ally = options & _OPT_ALLY
    if ally and not hostile:
        return "friendly "
    if hostile and not ally:
        return "enemy "
    return ""


def _target_phrase(order_type: int, options: int, position, target: int | None) -> str:
    """How a special power is aimed, showing the raw target: at-location casts print the ground
    `Position` (x, y, z); at-object casts print the target ObjectId (with its allegiance); self /
    global casts carry no target. Order type gates it, with the `Options` bits as a fallback."""
    if order_type == 0x411 or options & _OPT_POS:
        if position is None:
            return " (at a location)"
        return f" at ({position[0]:.0f}, {position[1]:.0f}, {position[2]:.0f})"
    if order_type == 0x412 or options & _OPT_OBJECT:
        if not target:
            return " (on a target)"
        return f" on {_allegiance(options)}object #{target}"
    return ""  # 0x410 self / 0x456 global — no target


def _integers(chunk: ReplayChunk) -> list[int]:
    return [
        a.value
        for a in chunk.order.arguments
        if a.argument_type is OrderArgumentType.Integer and isinstance(a.value, int)
    ]


def _first_bool(chunk: ReplayChunk) -> bool | None:
    for a in chunk.order.arguments:
        if a.argument_type is OrderArgumentType.Boolean:
            return bool(a.value)
    return None


def _first_of(chunk: ReplayChunk, arg_type: OrderArgumentType):
    """The value of the first argument of `arg_type` (the `0x412` target is the first ObjectId,
    the `0x411` ground point the first Position), or None."""
    for a in chunk.order.arguments:
        if a.argument_type is arg_type:
            return a.value
    return None


def _describe(chunk: ReplayChunk, data: GameData) -> str | None:
    """The English clause for one content-bearing order, or None if it carries no static id
    (control/camera/selection, or an unmapped order type)."""
    order = chunk.order_type
    ints = _integers(chunk)

    if order == 0x417:  # recruit unit / buy upgrade, or (flag=True) fortress hero by slot
        if not ints:
            return None
        if _first_bool(chunk):  # hero mode: the id is a command-slot, not a template
            return f"recruits a fortress hero (command slot {ints[0]})"
        return f"recruits {data.object_label(ints[0])}"

    if order == 0x41A and ints:  # build structure
        return f"builds {data.object_label(ints[0])}"

    if order in _POWER_ORDERS and ints:
        power = data.label(data.special_power(ints[0])) or f"special power {ints[0]}?"
        options = ints[1] if len(ints) > 1 else 0
        position = _first_of(chunk, OrderArgumentType.Position)
        target = _first_of(chunk, OrderArgumentType.ObjectId)
        return f"uses {power}{_target_phrase(order, options, position, target)}"

    if order == 0x414 and len(ints) >= 2:  # spellbook power purchase — id is the 2nd integer
        science = data.label(data.science(ints[1])) or f"science {ints[1]}?"
        return f"acquires the spellbook power {science}"

    if order == 0x415 and ints:  # research an upgrade at a building
        upgrade = data.label(data.upgrade(ints[0])) or f"upgrade {ints[0]}?"
        return f"researches {upgrade}"

    if order == 0x457:  # toggle weapon set (bow<->sword etc.); target is a runtime unit
        return "switches weapon set"

    return None


@dataclass(slots=True)
class NarrationEvent:
    timecode: int
    seconds: float
    player: str
    text: str
    count: int = 1  # consecutive identical actions collapsed into one line

    @property
    def clock(self) -> str:
        return f"{int(self.seconds) // 60:d}:{int(self.seconds) % 60:02d}"


def _player_label(replay: ReplayFile, chunk: ReplayChunk) -> str:
    slot = replay.slot_for(chunk)
    if slot is None:
        return f"#{chunk.number}"
    return slot.human_name or (
        slot.computer_difficulty.name if slot.computer_difficulty else f"#{chunk.number}"
    )


def narrate(replay: ReplayFile, data: GameData) -> list[NarrationEvent]:
    """Every content-bearing order as a `NarrationEvent`, in replay order, with consecutive
    identical actions by the same player collapsed (`recruits 3x Orc Warriors`)."""
    spf = replay.seconds_per_frame
    events: list[NarrationEvent] = []
    for chunk in replay.chunks:
        text = _describe(chunk, data)
        if text is None:
            continue
        player = _player_label(replay, chunk)
        last = events[-1] if events else None
        if last is not None and last.player == player and last.text == text:
            last.count += 1
            continue
        events.append(NarrationEvent(chunk.timecode, chunk.timecode * spf, player, text))
    return events


def _faction_label(replay: ReplayFile, data: GameData, slot_index: int) -> str:
    """The engine Side most of a player's recruited units belong to — a data-driven faction
    tag (`Mordor`, `Wild`, ...) without hard-coding any mod's faction names."""
    sides: Counter[str] = Counter()
    for chunk in replay.chunks:
        if chunk.order_type != 0x417 or replay.slot_index(chunk) != slot_index:
            continue
        if _first_bool(chunk):
            continue
        ints = _integers(chunk)
        name = data.object_name(ints[0]) if ints else None
        side = data.side_of(name) if name else None
        if side:
            sides[side] += 1
    return sides.most_common(1)[0][0] if sides else "?"


def render(replay: ReplayFile, data: GameData) -> Iterator[str]:
    """The full narration as text lines: a header (game, map, duration, players and their
    inferred factions) followed by the timecoded event log."""
    header = replay.header
    duration = header.end_time - header.start_time
    yield f"{header.game_type.name} replay — {header.metadata.map_file}"
    yield f"Duration: {duration} ({header.num_timecodes} frames)"
    yield "Players:"
    for index, slot in enumerate(header.metadata.players):
        faction = _faction_label(replay, data, index)
        yield f"  {slot.human_name}  [{faction}]  (faction id {slot.faction}, team {slot.team})"
    yield ""

    for event in narrate(replay, data):
        times = f" x{event.count}" if event.count > 1 else ""
        yield f"[{event.clock}] {event.player}: {event.text}{times}"
