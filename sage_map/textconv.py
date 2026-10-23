"""A `.map` / `.bse` file as diffable text - the git `textconv` filter behind `*.map diff=sage-map`.

Git diffs textconv output line by line, so the layout is the whole design. Every line is one fact
and nothing in it depends on where something else sits:

- **No stream offsets, no index tables.** A saved map is RefPack-compressed (`EAR\\0`), so one
  inserted script changes most of the file's bytes; and the parser's `start_pos`/`end_pos`, the
  uncompressed-size header and the asset name table all move with any earlier edit. None of them
  is printed - property keys come out by name.
- **No ids WorldBuilder renumbers.** `waypointID` runs 1..n without gaps, so deleting a waypoint
  renumbers every later one; waypoint links print by waypoint name instead, and `uniqueID` (a
  `<template> <N>` counter) is dropped from objects too.
- **No list indices in a line.** Nested structures print indented, with `-` for a list item, so
  inserting an item never rewrites its siblings.
- **Bulk arrays summarised per block.** The heightmap and the blend-tile arrays print one hash per
  32x32-cell block: a resculpt reports which blocks changed instead of megabytes of cells.

Scripts print in stored order (the order they evaluate in and WorldBuilder draws them), each as a
`script "<name>"` header carrying its non-default settings, its comments as `#` lines, then one
`if:` / `do:` / `else:` sentence per line. Paired with `xfuncname`, git's hunk headers then name
the script each change sits in.

`textconv_text` never raises: a file that will not parse prints an error line and the blob hash,
since a failing textconv breaks `git diff` for the whole repository.
"""

import hashlib
import io
from collections.abc import Iterator
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any

from sage_map.assets.player_scripts import Script, ScriptGroup
from sage_map.diff import _fmt, _props, _script_body
from sage_map.map import Map, parse_map
from sage_map.model import _all_teams, _prop

__all__ = ["XFUNCNAME", "dump_map", "textconv_text"]

#: The `diff.sage-map.xfuncname` pattern: the line git names in a hunk header - the nearest script
#: or group, else the `[section]` the change sits in. Git shows the first capture group, so it
#: spans the whole name.
XFUNCNAME = '^ *((script|group) ".*|\\[.*)$'

# Fields that move with any earlier edit, or that hold the file's own bookkeeping.
_SKIP_FIELDS = {"start_pos", "end_pos"}
_SKIP_SLOTS = {
    "compression_bytes",
    "asset_count",
    "assets",
    "ea_compression_header",
    "compressed",
    "chunk_names",
}
# Object properties WorldBuilder assigns from a counter; see the module docstring.
_VOLATILE_OBJECT_PROPS = {"uniqueID", "waypointID"}
# The slots printed by a dedicated section below; every other slot goes through `_generic`.
_DEDICATED_SLOTS = {
    "world_info",
    "sides_list",
    "teams",
    "library_map_lists",
    "player_scripts_list",
    "objects_list",
    "waypoints_list",
    "trigger_areas",
    "polygon_triggers",
    "height_map_data",
    "blend_tile_data",
}
_BLOCK = 32
# A list of plain values longer than this prints as its length and hash.
_INLINE_LIST_MAX = 16


def _hash(value: object) -> str:
    return hashlib.sha1(repr(value).encode()).hexdigest()[:12]


def _quote(name: object) -> str:
    return f'"{name}"'


def _prop_lines(props: dict[str, object], pad: str, skip: set[str] = frozenset()) -> list[str]:
    return [
        f"{pad}{key} = {_fmt(value)}" for key, value in sorted(props.items()) if key not in skip
    ]


def _section_world(m: Map) -> list[str]:
    if m.world_info is None:
        return []
    return ["[world]", *_prop_lines(_props(m.world_info), "  ")]


def _player_names(m: Map) -> list[str]:
    players = m.sides_list.players if m.sides_list is not None else []
    return [_prop(p, "playerName") or "" for p in players]


def _section_players(m: Map) -> list[str]:
    if m.sides_list is None:
        return []
    libraries = m.library_map_lists.lists if m.library_map_lists is not None else []
    out: list[str] = []
    for index, player in enumerate(m.sides_list.players):
        out.append(f"[player {_quote(_prop(player, 'playerName') or '')}]")
        out.extend(_prop_lines(_props(player), "  "))
        if index < len(libraries):
            out.extend(f"  library {_quote(path)}" for path in libraries[index].values)
        for item in player.build_list_items:
            flags = [
                flag
                for flag, on in (
                    ("built", item.is_initially_built),
                    ("whiner", item.whiner),
                    ("unsellable", item.unsellable),
                    ("repairable", item.repairable),
                )
                if on
            ]
            text = f"  build {_quote(item.build_name)} {item.template_name}"
            text += f" at {_fmt(item.location)} angle {_fmt(item.angle)}"
            text += f" health {item.health} rebuilds {item.num_rebuilds}"
            if item.script:
                text += f" script {_quote(item.script)}"
            if flags:
                text += " " + " ".join(flags)
            out.append(text)
    return out


def _section_teams(m: Map) -> list[str]:
    out: list[str] = []
    for team in _all_teams(m):
        owner = _prop(team, "teamOwner") or ""
        name = _prop(team, "teamName") or ""
        out.append(f"[team {_quote(f'{owner}/{name}' if owner else name)}]")
        out.extend(_prop_lines(_props(team), "  ", {"teamName", "teamOwner"}))
    return out


def _script_header(script: Script) -> str:
    """`script "<name>"` plus the settings that differ from a fresh WorldBuilder script."""
    flags: list[str] = []
    if not script.is_active:
        flags.append("inactive")
    if script.is_subroutine:
        flags.append("subroutine")
    if script.deactivate_upon_success:
        flags.append("once")
    difficulties = [
        name
        for name, on in (
            ("easy", script.active_in_easy),
            ("medium", script.active_in_medium),
            ("hard", script.active_in_hard),
        )
        if on
    ]
    if len(difficulties) < 3:
        flags.append("only:" + (",".join(difficulties) or "none"))
    if script.evaluation_interval:
        flags.append(f"every {script.evaluation_interval}s")
    if script.actions_fire_sequentially:
        target = (
            f" on {_quote(script.sequential_target_name)}" if script.sequential_target_name else ""
        )
        flags.append(f"sequential{target}")
    if script.loop_actions:
        flags.append(f"loop {script.loop_count}")
    return f"script {_quote(script.name)}" + "".join(f"  {flag}" for flag in flags)


def _comment_lines(label: str, text: str | None, pad: str) -> list[str]:
    if not text:
        return []
    return [f"{pad}#{label} {line}".rstrip() for line in text.splitlines()]


def _script_items(items: list, depth: int) -> Iterator[str]:
    pad = "  " * depth
    for item in items:
        if isinstance(item, ScriptGroup):
            flags = [
                f
                for f, on in (("inactive", not item.is_active), ("subroutine", item.is_subroutine))
                if on
            ]
            yield f"{pad}group {_quote(item.name)}" + "".join(f"  {flag}" for flag in flags)
            yield from _script_items(item.items, depth + 1)
        elif isinstance(item, Script):
            yield f"{pad}{_script_header(item)}"
            inner = pad + "  "
            yield from _comment_lines("", item.comment, inner)
            yield from _comment_lines(" if:", item.conditions_comment, inner)
            yield from _comment_lines(" do:", item.actions_comment, inner)
            yield from (f"{inner}{line}" for line in _script_body(item))


def _section_scripts(m: Map) -> list[str]:
    if m.player_scripts_list is None:
        return []
    names = _player_names(m)
    out: list[str] = []
    for index, script_list in enumerate(m.player_scripts_list.script_lists):
        owner = names[index] if index < len(names) else f"#{index}"
        out.append(f"[scripts {_quote(owner)}]")
        out.extend(_script_items(script_list.items, 1))
    return out


def _waypoint_names(m: Map) -> dict[int, str]:
    objects = m.objects_list.object_list if m.objects_list is not None else []
    result: dict[int, str] = {}
    for obj in objects:
        identity = _prop(obj, "waypointID")
        if isinstance(identity, int):
            result[identity] = _prop(obj, "waypointName") or f"<unnamed {obj.type_name}>"
    return result


def _section_objects(m: Map) -> list[str]:
    if m.objects_list is None:
        return []
    out = ["[objects]"]
    for obj in m.objects_list.object_list:
        text = f"  {obj.type_name} at {_fmt(obj.position)} angle {_fmt(obj.angle)}"
        if obj.road_type:
            text += f" road {obj.road_type}"
        props = _props(obj)
        text += "".join(
            f" {key}={_fmt(value)}"
            for key, value in sorted(props.items())
            if key not in _VOLATILE_OBJECT_PROPS
        )
        out.append(text)
    return out


def _section_waypoint_links(m: Map) -> list[str]:
    if m.waypoints_list is None or not m.waypoints_list.waypoint_paths:
        return []
    names = _waypoint_names(m)
    links = sorted(
        f"  {_quote(names.get(a, f'<id {a}>'))} -> {_quote(names.get(b, f'<id {b}>'))}"
        for a, b in m.waypoints_list.waypoint_paths
    )
    return ["[waypoint links]", *links]


def _section_areas(m: Map) -> list[str]:
    out: list[str] = []
    for area in m.trigger_areas.trigger_areas if m.trigger_areas is not None else []:
        out.append(f"[trigger area {_quote(area.name)}]")
        if area.layer_name:
            out.append(f"  layer = {area.layer_name}")
        out.append(f"  points = {_fmt(tuple(area.points))}")
    for polygon in m.polygon_triggers.polygon_triggers if m.polygon_triggers is not None else []:
        out.append(f"[polygon {_quote(polygon.name)}]")
        for f in fields(polygon):
            if f.name in ("name", "trigger_id", "points") or f.name in _SKIP_FIELDS:
                continue
            value = getattr(polygon, f.name)
            if value is not None:
                out.append(f"  {f.name} = {_fmt(value)}")
        out.append(f"  points = {_fmt(tuple(polygon.points))}")
    return out


def _block_hashes(width: int, height: int, grids: list[list[list[Any]]]) -> Iterator[str]:
    """One `block (bx,by) <hash>` line per _BLOCK-cell square, hashing every grid's cells in it."""
    for by in range(0, height, _BLOCK):
        for bx in range(0, width, _BLOCK):
            cells = [[row[bx : bx + _BLOCK] for row in grid[by : by + _BLOCK]] for grid in grids]
            yield f"  block ({bx // _BLOCK},{by // _BLOCK}) {_hash(cells)}"


def _grid_size(grid: list[list[Any]]) -> tuple[int, int]:
    return (len(grid[0]) if grid else 0, len(grid))


def _section_terrain(m: Map) -> list[str]:
    out: list[str] = []
    hm = m.height_map_data
    if hm is not None:
        out.append(f"[heightmap {hm.width}x{hm.height} border {hm.border_width}]")
        out.extend(f"  border at {_fmt(b.position)}" for b in hm.borders)
        width, height = _grid_size(hm.elevations)
        out.extend(_block_hashes(width, height, [hm.elevations]))
    blend = m.blend_tile_data
    if blend is not None:
        out.append("[blend tiles]")
        out.extend(f"  texture {_quote(t.name)} cells {t.cell_count}" for t in blend.textures)
        # Cells hold ints, bools and enums, whose repr is stable; normalising millions of them
        # would dominate the run.
        grids = []
        for f in fields(blend):
            value = getattr(blend, f.name)
            if isinstance(value, list) and value and isinstance(value[0], list):
                grids.append(value)
        if grids:
            width, height = _grid_size(grids[0])
            out.extend(_block_hashes(width, height, grids))
        rest = {
            "blend_descriptions": blend.blend_descriptions,
            "cliff_texture_mappings": blend.cliff_texture_mappings,
        }
        out.extend(
            f"  {name} {len(value)} {_hash(_normalize(value))}" for name, value in rest.items()
        )
    return out


def _normalize(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _normalize(getattr(value, f.name))
            for f in fields(value)
            if f.name not in _SKIP_FIELDS
        }
    if isinstance(value, dict):
        return {str(_normalize(k)): _normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, bytes):
        return value.hex()
    return value


def _is_plain(value: Any) -> bool:
    return not isinstance(value, (dict, list))


def _generic(value: Any, pad: str) -> Iterator[str]:
    """An indented dump of a normalized value: `key = value` for plain fields, nested blocks for
    structures, `-` per list item, and long plain lists as their length and hash."""
    if isinstance(value, dict):
        for key in sorted(value):
            item = value[key]
            if _is_plain(item):
                yield f"{pad}{key} = {_fmt(item)}"
            elif isinstance(item, list) and all(_is_plain(x) for x in item):
                yield f"{pad}{key} = {_plain_list(item)}"
            else:
                yield f"{pad}{key}:"
                yield from _generic(item, pad + "  ")
    elif isinstance(value, list):
        for item in value:
            if _is_plain(item):
                yield f"{pad}- {_fmt(item)}"
            elif isinstance(item, list) and all(_is_plain(x) for x in item):
                yield f"{pad}- {_plain_list(item)}"
            else:
                yield f"{pad}-"
                yield from _generic(item, pad + "  ")
    else:
        yield f"{pad}{_fmt(value)}"


def _plain_list(items: list) -> str:
    if len(items) > _INLINE_LIST_MAX:
        return f"<{len(items)} values {_hash(items)}>"
    return "[" + ", ".join(_fmt(x) for x in items) + "]"


def _section_other(m: Map) -> list[str]:
    out: list[str] = []
    for slot in Map.__annotations__:
        if slot in _DEDICATED_SLOTS or slot in _SKIP_SLOTS:
            continue
        value = getattr(m, slot, None)
        if value is None:
            continue
        out.append(f"[{slot}]")
        out.extend(_generic(_normalize(value), "  "))
    return out


def dump_map(m: Map) -> str:
    """The whole map as canonical diffable text (see the module docstring for the layout)."""
    lines: list[str] = []
    for section in (
        _section_world,
        _section_players,
        _section_teams,
        _section_scripts,
        _section_objects,
        _section_waypoint_links,
        _section_areas,
        _section_terrain,
        _section_other,
    ):
        lines.extend(section(m))
    return "\n".join(lines) + "\n"


def textconv_text(data: bytes) -> str:
    """`dump_map` of raw map bytes, or an error line plus the content hash if they do not parse."""
    try:
        return dump_map(parse_map(io.BytesIO(data)))
    except Exception as exc:  # noqa: BLE001 - a textconv must never fail; see the module docstring
        digest = hashlib.sha1(data).hexdigest()
        return f"unparseable map ({len(data)} bytes, sha1 {digest}): {type(exc).__name__}: {exc}\n"
