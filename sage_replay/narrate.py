"""Turn a replay's order stream into English by resolving every content-bearing id
against a loaded game.

The order-space map (see `order_space_map.md`) pins how each order type's integer id
resolves to a definition: recruit (`0x417`), placement build (`0x419`), mobile-builder build
(`0x41A`), wall segment (`0x463`) and the plot unpack/build (`0x43F` - settlement/outpost
unpacks and other fixed-spot creates, no placement UI) all carry a ThingTemplate id in their
first integer (`thing_template_order` index + 1);
special powers (`0x410`/`0x411`/`0x412`/`0x456`) index
`game.specialpowers` + 1; a spellbook purchase (`0x414`) carries the science in its second
integer; a building upgrade (`0x415`) indexes `game.upgrades` with a +3 offset. `GameData`
loads those tables once from a game root (use `tools/mount_game.py` to mount a live install's
`.big` archives into one), and `narrate` walks the stream turning each recognised order into a
timecoded English line. Control/camera/selection orders carry no static id and are skipped.

The horde-combine order (`0x423`, Edain horde-merge) has no static id either - its ObjectId is a
runtime handle of the target/primary horde - but it names a deliberate action, so it is narrated
("combines hordes into object #N") from that ObjectId alone.

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

from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sage_ini.loader import load_game
from sage_ini.model.behaviors import CastleBehavior
from sage_ini.model.enums import CommandTypes
from sage_ini.subsystems import thing_template_order
from sage_replay.replay import OrderArgumentType, ReplayChunk, ReplayFile

__all__ = ["GameData", "NarrationEvent", "narrate", "render"]

# Upgrade ids sit 3 above their 0-based `game.upgrades` index (DefaultUpgrade = id 3;
# order_space_map.md, `0x415`). Ground-truthed by an in-game replay survey - the earlier
# reading was one higher because the Mordor FireArrows/ForgedBlades anchor pair matches
# as a set under both offsets.
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

# A template is player-buildable when some CommandButton with one of these `Command`s targets it
# through its `Object` field; `GameData.build_commands` records which of them reach each template.
_BUILD_COMMANDS = frozenset(
    {
        CommandTypes.DOZER_CONSTRUCT,
        CommandTypes.FOUNDATION_CONSTRUCT,
        CommandTypes.CASTLE_UNPACK,
        CommandTypes.CASTLE_UNPACK_EXPLICIT_OBJECT,
    }
)

# The two commands that unpack a pre-placed castle/camp rather than raise a new structure; a
# template reached only through these narrates as "unpacks" instead of "builds".
_UNPACK_COMMANDS = frozenset({"CASTLE_UNPACK", "CASTLE_UNPACK_EXPLICIT_OBJECT"})


@dataclass(slots=True)
class GameData:
    """The resolution tables a narration needs, loaded once from a game root."""

    object_order: list[str]  # ThingTemplate registration order; replay id = index + 1
    objects: dict  # name -> Object, for Side
    specialpowers: list[str]
    sciences: list[str]
    upgrades: list[str]
    displaynames: dict[str, str]  # definition code-name -> localized DisplayName (when it has one)
    # PlayerTemplate registration order -> a display label (localized faction name, else engine
    # Side); the replay slot's `faction id` indexes straight into it.
    faction_labels: list[str] = field(default_factory=list)
    # Template code name -> the build command-type names ("DOZER_CONSTRUCT", "FOUNDATION_CONSTRUCT",
    # "CASTLE_UNPACK", "CASTLE_UNPACK_EXPLICIT_OBJECT") whose CommandButtons target it. A template
    # absent here (wall pieces, castle-expansion pads) is still buildable, just not via a button.
    build_commands: dict[str, frozenset[str]] = field(default_factory=dict)
    # PlayerTemplate registration order -> the faction's `Side` token ("Men", "Imladris"), the
    # key `CastleToUnpackForFaction` rows use. Parallel to `faction_labels`.
    faction_sides: list[str] = field(default_factory=list)
    # Castle/camp/outpost plot template -> lowercased Side -> the base-layout name its
    # CastleBehavior unpacks for that faction (`CastleToUnpackForFaction = Men gondor_castle ...`).
    castle_bases: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def from_root(
        cls,
        root: str | Path | Sequence[str | Path],
        bases: Sequence[str | Path] = (),
        localize: bool = False,
    ) -> GameData:
        """Build from a game root holding `data/ini` (a live install must be mounted first;
        see `tools/mount_game.py`). `root` may be an ascending-priority sequence of roots (a later
        one shadows an earlier at the file level). `bases` are lower-priority base-game roots the
        mod layers over - needed when the mod relies on the base game's SubsystemLegend.ini and
        object tree (its own defs and references still win).

        `localize` resolves each definition's localized DisplayName from the string table
        ("Misty Mountains"); it is off by default, so every label stays the raw ini code name
        ("FactionWild") - deterministic and independent of the string table."""
        game = load_game(root, bases=tuple(bases)).game
        strings = {label.upper(): value for label, value in game.strings.items()}

        def localized(table) -> dict[str, str]:
            if not localize:
                return {}  # labels fall back to the raw code name
            names: dict[str, str] = {}
            for name, obj in table.items():
                key = obj._fields.get("DisplayName")
                if isinstance(key, str) and key.upper() in strings:
                    names[name] = strings[key.upper()]
            return names

        faction_names = localized(game.factions)  # code name -> localized name, when it resolves

        # A modded button's `Command` may not convert to a known member; skip those rather than
        # let one bad definition sink the whole table.
        built_by: dict[str, set[str]] = defaultdict(set)
        for btn in game.commandbuttons.values():
            try:
                cmd = btn.Command
            except Exception:  # noqa: BLE001 - unknown/odd Command token; not this template's build
                continue
            if cmd in _BUILD_COMMANDS:
                target = btn._fields.get("Object")
                if isinstance(target, str):
                    built_by[target].add(cmd.name)

        # Castle/camp/outpost plot templates: their CastleBehavior's per-faction unpack rows
        # (`CastleToUnpackForFaction = Men gondor_castle <cost>`). The target names a base
        # layout, not an ini object; macro-resolve it so an unpack order can name the base
        # the clicking player's faction actually gets.
        castle_bases: dict[str, dict[str, str]] = {}
        for obj_name, obj in game.objects.items():
            for module in getattr(obj, "modules", ()):
                if not isinstance(module, CastleBehavior):
                    continue
                raw = module._fields.get("CastleToUnpackForFaction")
                if raw is None:
                    continue
                rows: dict[str, str] = {}
                for entry in raw if isinstance(raw, list) else [raw]:
                    tokens = str(entry).split()
                    if len(tokens) >= 2:
                        target = str(game.get_macro(tokens[1])).split()[0]
                        rows.setdefault(tokens[0].lower(), target)
                if rows:
                    castle_bases[obj_name] = rows

        return cls(
            object_order=thing_template_order(root, bases=tuple(bases)),
            objects=dict(game.objects),
            specialpowers=list(game.specialpowers),
            sciences=list(game.sciences),
            upgrades=list(game.upgrades),
            # With `localize`, objects and upgrades carry a localized DisplayName (special powers
            # and sciences never do); otherwise every lookup falls back to the raw code name.
            displaynames={**localized(game.objects), **localized(game.upgrades)},
            # A faction's localized DisplayName ("Misty Mountains") under `localize`, else its raw
            # PlayerTemplate code name ("FactionWild") - in registration order.
            faction_labels=[faction_names.get(name, name) for name, _ in game.factions.items()],
            build_commands={name: frozenset(cmds) for name, cmds in built_by.items()},
            faction_sides=[
                str(template._fields.get("Side") or "") for _, template in game.factions.items()
            ],
            castle_bases=castle_bases,
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
        index = replay_id - _UPGRADE_OFFSET  # 0-based, unlike the 1-based spaces `_at` serves
        return self.upgrades[index] if 0 <= index < len(self.upgrades) else None

    def side_of(self, name: str) -> str | None:
        obj = self.objects.get(name)
        return obj._fields.get("Side") if obj is not None else None

    def effective_side(self, name: str | None) -> str | None:
        """The template's roster `Side`, inherited up the `ChildObject` chain when the
        template sets none of its own (`RohanKnechtHorde_Heerschau` -> `Rohan`), or None
        when unknown or the name is not a template."""
        obj = self.objects.get(name) if name is not None else None
        while obj is not None:
            side = obj._fields.get("Side")
            if side:
                return side
            obj = getattr(obj, "parent", None)
        return None

    def faction_label(self, faction_id: int) -> str:
        """The player's faction for display. The replay slot's `faction id` indexes the
        PlayerTemplate registration order directly (0 = Civilian ... 5 = Rohan, 12 = Angmar);
        out-of-range or an unloaded factions table yields `?`."""
        if 0 <= faction_id < len(self.faction_labels):
            return self.faction_labels[faction_id]
        return "?"

    def faction_side(self, faction_id: int) -> str | None:
        """The player's faction `Side` token ("Men", "Imladris"...) - the key
        `CastleToUnpackForFaction` rows use - or None when unknown."""
        if 0 <= faction_id < len(self.faction_sides):
            return self.faction_sides[faction_id] or None
        return None

    def castle_base(self, name: str | None, side: str | None) -> str | None:
        """The base-layout name that unpacking template `name` yields for a player of
        `side` (its CastleBehavior's `CastleToUnpackForFaction` row), or None when the
        template carries no castle table or the side has no row."""
        if name is None or side is None:
            return None
        return self.castle_bases.get(name, {}).get(side.lower())

    def label(self, name: str | None) -> str | None:
        """A definition's player-facing name: its localized DisplayName when it has one, else the
        raw code name exactly as written in the ini (never prettified). None passes through."""
        return self.displaynames.get(name, name) if name is not None else None

    def object_label(self, replay_id: int) -> str:
        """A recruited/built object's label - localized DisplayName or the raw template name (or a
        `<id ?>` marker when the id is out of range)."""
        name = self.object_name(replay_id)
        return (
            self.displaynames.get(name, name) if name is not None else f"<object id {replay_id}?>"
        )


def _allegiance(options: int) -> str:
    """The target's permitted allegiance from the `Options` bits, as a word ("enemy"/"friendly"
    /"" for any) - enemy or neutral reads as enemy; ally-only as friendly (Edain mind-control)."""
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
    return ""  # 0x410 self / 0x456 global - no target


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


def _positions(chunk: ReplayChunk) -> list:
    """Every Position argument in order (a wall segment carries two: its endpoints)."""
    return [a.value for a in chunk.order.arguments if a.argument_type is OrderArgumentType.Position]


def _build_verb(code_name: str | None, build_commands: dict[str, frozenset[str]]) -> str:
    """The verb for a build order: "unpacks" when a template is reached only through a castle/camp
    unpack command, else "builds" - the default for foundation/dozer builds, mixed command sets,
    and templates with no button entry (wall pieces, castle-expansion pads)."""
    commands = build_commands.get(code_name, frozenset()) if code_name is not None else frozenset()
    if commands & _UNPACK_COMMANDS and not commands - _UNPACK_COMMANDS:
        return "unpacks"
    return "builds"


def _at_clause(position) -> str:
    """The ` at (x, y)` placement clause for a build order (2-D, int-rounded; the z terrain height
    is dropped), or empty when the order carries no Position."""
    if position is None:
        return ""
    return f" at ({position[0]:.0f}, {position[1]:.0f})"


def _wall_span(chunk: ReplayChunk) -> str:
    """The ` from (x, y) to (x, y)` clause across a wall segment's two endpoint Positions (2-D,
    int-rounded), or empty when the endpoints are missing."""
    points = _positions(chunk)
    if len(points) < 2:
        return ""
    a, b = points[0], points[1]
    return f" from ({a[0]:.0f}, {a[1]:.0f}) to ({b[0]:.0f}, {b[1]:.0f})"


def _base_clause(data: GameData, name: str | None, side: str | None) -> str:
    """When a built/unpacked template carries a CastleBehavior, the base layout the issuing
    player's faction gets (`" - unpacks the dunedain_outpost base"`), else nothing."""
    base = data.castle_base(name, side)
    return f" - unpacks the {base} base" if base else ""


def _describe(chunk: ReplayChunk, data: GameData, side: str | None = None) -> str | None:
    """The English clause for one content-bearing order, or None if it carries no static id
    (control/camera/selection, or an unmapped order type). `side` is the issuing player's
    faction Side token, used to name the base a castle/camp/outpost plot unpacks."""
    order = chunk.order_type
    ints = _integers(chunk)

    if order == 0x417:  # recruit unit / buy upgrade, or (flag=True) fortress hero by slot
        if not ints:
            return None
        if _first_bool(chunk):  # hero mode: the id is a command-slot, not a template
            return f"recruits a fortress hero (command slot {ints[0]})"
        return f"recruits {data.object_label(ints[0])}"

    if order in (0x419, 0x41A) and ints:  # placement build / mobile-builder construct
        name = data.object_name(ints[0])
        verb = _build_verb(name, data.build_commands)
        location = _at_clause(_first_of(chunk, OrderArgumentType.Position))
        return f"{verb} {data.object_label(ints[0])}{location}{_base_clause(data, name, side)}"

    if order == 0x43F and ints:  # unpack/build at a selected plot - no placement UI
        # Standard thing-template ids, same space as 0x419 (the earlier +2 reading was an
        # adjacent-anchor miscalibration; order_space_map.md `0x43F`).
        name = data.object_name(ints[0])
        label = data.label(name) if name is not None else f"<object id {ints[0]}?>"
        return f"{_build_verb(name, data.build_commands)} {label}{_base_clause(data, name, side)}"

    if order == 0x463 and ints:  # wall segment: a template raised between two endpoints
        return f"builds a wall segment: {data.object_label(ints[0])}{_wall_span(chunk)}"

    if order in _POWER_ORDERS and ints:
        power = data.label(data.special_power(ints[0])) or f"special power {ints[0]}?"
        options = ints[1] if len(ints) > 1 else 0
        position = _first_of(chunk, OrderArgumentType.Position)
        target = _first_of(chunk, OrderArgumentType.ObjectId)
        return f"uses {power}{_target_phrase(order, options, position, target)}"

    if order == 0x414 and len(ints) >= 2:  # spellbook power purchase - id is the 2nd integer
        science = data.label(data.science(ints[1])) or f"science {ints[1]}?"
        return f"acquires the spellbook power {science}"

    if order == 0x415 and ints:  # research an upgrade at a building
        upgrade = data.label(data.upgrade(ints[0])) or f"upgrade {ints[0]}?"
        return f"researches {upgrade}"

    if order == 0x457:  # toggle weapon set (bow<->sword etc.); target is a runtime unit
        return "switches weapon set"

    if order == 0x423:  # combine hordes (Edain horde-merge); arg is the target/primary horde
        target = _first_of(chunk, OrderArgumentType.ObjectId)
        return f"combines hordes into object #{target}" if target else "combines hordes"

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
        slot = replay.slot_for(chunk)
        side = data.faction_side(slot.faction) if slot is not None else None
        text = _describe(chunk, data, side)
        if text is None:
            continue
        player = _player_label(replay, chunk)
        last = events[-1] if events else None
        if last is not None and last.player == player and last.text == text:
            last.count += 1
            continue
        events.append(NarrationEvent(chunk.timecode, chunk.timecode * spf, player, text))
    return events


def render(replay: ReplayFile, data: GameData) -> Iterator[str]:
    """The full narration as text lines: a header (game, map, duration, players and their
    factions) followed by the timecoded event log."""
    header = replay.header
    duration = header.end_time - header.start_time
    yield f"{header.game_type.name} replay - {header.metadata.map_file}"
    yield f"Duration: {duration} ({header.num_timecodes} frames)"
    yield "Players:"
    for slot in header.metadata.players:
        faction = data.faction_label(slot.faction)
        yield f"  {slot.human_name}  [{faction}]  (faction id {slot.faction}, team {slot.team})"
    yield ""

    for event in narrate(replay, data):
        times = f" x{event.count}" if event.count > 1 else ""
        yield f"[{event.clock}] {event.player}: {event.text}{times}"
