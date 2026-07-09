"""A human-readable diff of WorldBuilder `.map` files - between two parsed maps, two paths, or
the map files one git commit touches.

A `.map` is binary, so `git show` can only say "binary files differ". This module parses both
sides and compares the *content* the way a mapper thinks about it: placed objects
(matched by their script name where one is set, otherwise grouped by template with counts, so an
inserted object does not shift-flood the report), teams and players by name, scripts rendered as
`if/do/else` sentences and line-diffed, trigger areas, map settings, and a terrain summary
(counting changed heightmap cells rather than printing them). Assets with no curated section are
still equality-checked - with the `start_pos`/`end_pos` stream offsets stripped, since any earlier
size change shifts every later offset - and reported as a one-line "changed" note, so nothing is
silently ignored.

The git entry points (`diff_commit_maps` for one commit against its parent, `diff_range_maps`
for the net change between two revs) list the `.map`/`.bse` files touched via `git diff-tree`,
read each side's blob straight out of the object store (no worktree needed - maps are
self-contained, unlike the ini diff), and diff the parsed pair.
"""

import difflib
import io
import subprocess
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from sage_ini.parser.io import MAP_SUFFIXES
from sage_map.assets.player_scripts import Script, ScriptDerived
from sage_map.map import Map, parse_map, parse_map_from_path
from sage_map.model import _all_teams, _iter_scripts, _prop
from sage_map.scripts import typed_value

__all__ = [
    "ChangedEntry",
    "SectionDiff",
    "MapDiff",
    "MapFileChange",
    "MapFileDiff",
    "diff_maps",
    "diff_map_files",
    "commit_map_changes",
    "range_map_changes",
    "resolve_range",
    "diff_commit_maps",
    "diff_range_maps",
    "format_map_diff",
    "format_map_file_diffs",
    "format_map_file_diffs_md",
]


@dataclass
class ChangedEntry:
    """One changed thing: its display label and the indented detail lines under it (already
    rendered; empty for a self-contained `key: old -> new` label)."""

    label: str
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"label": self.label, "details": list(self.details)}


@dataclass
class SectionDiff:
    """One themed slice of the report (objects, teams, scripts, ...). `added`/`removed` hold
    rendered entry labels; `changed` pairs a label with its detail lines."""

    title: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[ChangedEntry] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "added": list(self.added),
            "removed": list(self.removed),
            "changed": [entry.to_dict() for entry in self.changed],
        }


@dataclass
class MapDiff:
    """Everything that differs between two parsed maps, as the non-empty sections in report
    order."""

    sections: list[SectionDiff]

    def is_empty(self) -> bool:
        return all(section.is_empty() for section in self.sections)

    def to_dict(self) -> dict:
        """The whole diff as JSON-ready data (a list of sections, mirroring the text report)."""
        return {"sections": [section.to_dict() for section in self.sections]}


def _fmt(value: object) -> str:
    """A display form of a property or argument payload. Floats go through `%g` so the float32
    read noise (0.1 stored as 0.10000000149...) does not masquerade as precision."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return format(value, "g")
    if isinstance(value, tuple):
        return "(" + ", ".join(_fmt(item) for item in value) + ")"
    return str(value)


def _props(asset: Any) -> dict[str, object]:
    """The bare `name -> value` view of a map asset properties dict (dropping the type wrapper)."""
    if asset is None:
        return {}
    return {key: prop["value"] for key, prop in asset.properties.items()}


def _flat_details(old: dict[str, object], new: dict[str, object]) -> list[str]:
    """Rendered change lines for a flat name->value dict: `+ key = v`, `- key = v`,
    `key: old -> new`."""
    lines: list[str] = []
    for key in sorted(old.keys() | new.keys()):
        if key not in new:
            lines.append(f"- {key} = {_fmt(old[key])}")
        elif key not in old:
            lines.append(f"+ {key} = {_fmt(new[key])}")
        elif old[key] != new[key]:
            lines.append(f"{key}: {_fmt(old[key])} -> {_fmt(new[key])}")
    return lines


def _flat_section(title: str, old: dict[str, object], new: dict[str, object]) -> SectionDiff:
    """A section whose entries *are* the keys of a flat dict (map settings)."""
    section = SectionDiff(title)
    for key in sorted(old.keys() | new.keys()):
        if key not in new:
            section.removed.append(f"{key} = {_fmt(old[key])}")
        elif key not in old:
            section.added.append(f"{key} = {_fmt(new[key])}")
        elif old[key] != new[key]:
            section.changed.append(ChangedEntry(f"{key}: {_fmt(old[key])} -> {_fmt(new[key])}"))
    return section


# Stream offsets recorded by the parser: any earlier asset growing or shrinking shifts every
# later one, so they must never count as a content change.
_OFFSET_FIELDS = {"start_pos", "end_pos"}


def _normalize(value: Any) -> Any:
    """A comparable form of any parsed asset: dataclasses become dicts with the stream offsets
    dropped, recursively."""
    if is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _normalize(getattr(value, f.name))
            for f in fields(value)
            if f.name not in _OFFSET_FIELDS
        }
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, Enum):
        return value.name
    return value


def _diff_keyed(
    title: str,
    old: dict[str, Any],
    new: dict[str, Any],
    details: Callable[[Any, Any], list[str]],
) -> SectionDiff:
    """A section over two name-keyed tables: names only in one side are added/removed, shared
    names whose `details(old_item, new_item)` is non-empty are changed."""
    section = SectionDiff(title)
    for name in sorted(old.keys() | new.keys()):
        if name not in new:
            section.removed.append(name)
        elif name not in old:
            section.added.append(name)
        else:
            lines = details(old[name], new[name])
            if lines:
                section.changed.append(ChangedEntry(name, lines))
    return section


def _diff_players(old: Map, new: Map) -> SectionDiff:
    def players(map_obj: Map) -> dict[str, object]:
        sides = getattr(map_obj, "sides_list", None)
        result: dict[str, object] = {}
        for player in sides.players if sides is not None else []:
            name = _prop(player, "playerName")
            if name:
                result.setdefault(name, player)
        return result

    def details(old_player, new_player) -> list[str]:
        lines = _flat_details(_props(old_player), _props(new_player))
        if _normalize(old_player.build_list_items) != _normalize(new_player.build_list_items):
            lines.append("build list changed")
        return lines

    return _diff_keyed("players", players(old), players(new), details)


def _diff_teams(old: Map, new: Map) -> SectionDiff:
    def teams(map_obj: Map) -> dict[str, object]:
        result: dict[str, object] = {}
        for team in _all_teams(map_obj):
            name = _prop(team, "teamName")
            if not name:
                continue
            owner = _prop(team, "teamOwner") or ""
            result.setdefault(f"{owner}/{name}" if owner else name, team)
        return result

    def details(old_team, new_team) -> list[str]:
        return _flat_details(_props(old_team), _props(new_team))

    return _diff_keyed("teams", teams(old), teams(new), details)


# The instance properties that give a placed object a script-visible identity; used to pair the
# same object across the two versions so an edit reports as a change, not a remove + add.
_OBJECT_NAME_KEYS = ("objectName", "waypointName")


def _object_name(obj: Any) -> str | None:
    for key in _OBJECT_NAME_KEYS:
        name = _prop(obj, key)
        if name:
            return name
    return None


def _object_signature(obj: Any) -> tuple:
    """Everything that makes two placed objects the same object; compared exactly (the raw parsed
    values), rounded only for display."""
    return (
        obj.type_name,
        obj.position,
        obj.angle,
        obj.road_type,
        tuple(sorted(_props(obj).items())),
    )


def _diff_objects(old: Map, new: Map) -> SectionDiff:
    """Placed objects. Identical placements cancel out first, so only the touched objects remain;
    the leftovers pair by their unique script name (reported as moves / property edits), and the
    rest - the typical mass of unnamed scenery - is grouped per template with counts."""
    section = SectionDiff("objects")

    def objects(map_obj: Map) -> list:
        objects_list = getattr(map_obj, "objects_list", None)
        return list(objects_list.object_list) if objects_list is not None else []

    old_buckets: dict[tuple, list] = defaultdict(list)
    new_buckets: dict[tuple, list] = defaultdict(list)
    for obj in objects(old):
        old_buckets[_object_signature(obj)].append(obj)
    for obj in objects(new):
        new_buckets[_object_signature(obj)].append(obj)

    old_left = [
        obj
        for sig, bucket in old_buckets.items()
        for obj in bucket[len(new_buckets.get(sig, ())) :]
    ]
    new_left = [
        obj
        for sig, bucket in new_buckets.items()
        for obj in bucket[len(old_buckets.get(sig, ())) :]
    ]

    def named(objs: list) -> dict[str, Any]:
        counts: dict[str, int] = defaultdict(int)
        for obj in objs:
            if (name := _object_name(obj)) is not None:
                counts[name] += 1
        return {
            name: obj
            for obj in objs
            if (name := _object_name(obj)) is not None and counts[name] == 1
        }

    old_named, new_named = named(old_left), named(new_left)
    paired = old_named.keys() & new_named.keys()
    for name in sorted(paired):
        old_obj, new_obj = old_named[name], new_named[name]
        details: list[str] = []
        if old_obj.type_name != new_obj.type_name:
            details.append(f"type: {old_obj.type_name} -> {new_obj.type_name}")
        if old_obj.position != new_obj.position:
            details.append(f"moved {_fmt(old_obj.position)} -> {_fmt(new_obj.position)}")
        if old_obj.angle != new_obj.angle:
            details.append(f"angle: {_fmt(old_obj.angle)} -> {_fmt(new_obj.angle)}")
        details.extend(_flat_details(_props(old_obj), _props(new_obj)))
        section.changed.append(ChangedEntry(f"{name} ({new_obj.type_name})", details))

    def render_leftovers(objs: list, into: list[str]) -> None:
        by_type: dict[str, int] = defaultdict(int)
        singles: list[str] = []
        for obj in objs:
            name = _object_name(obj)
            if name is not None and name in paired:
                continue  # reported above as a change (paired names are unique per side)
            if name is not None:
                singles.append(f"{name} ({obj.type_name}) at {_fmt(obj.position)}")
            else:
                by_type[obj.type_name] += 1
        into.extend(sorted(singles))
        for type_name in sorted(by_type):
            count = by_type[type_name]
            into.append(type_name if count == 1 else f"{count} x {type_name}")

    render_leftovers(old_left, section.removed)
    render_leftovers(new_left, section.added)
    return section


def _diff_areas(old: Map, new: Map) -> SectionDiff:
    """Trigger areas and polygon triggers (water/river surfaces), both keyed by name. Geometry is
    summarised - an outline's points are coordinates nobody reads line by line."""

    def outline_details(old_points: list, new_points: list) -> list[str]:
        if len(old_points) != len(new_points):
            return [f"outline: {len(old_points)} -> {len(new_points)} points"]
        if old_points != new_points:
            return [f"outline moved ({len(new_points)} points)"]
        return []

    def trigger_details(old_area, new_area) -> list[str]:
        lines = []
        if old_area.layer_name != new_area.layer_name:
            lines.append(f"layer: {old_area.layer_name} -> {new_area.layer_name}")
        lines.extend(outline_details(old_area.points, new_area.points))
        return lines

    def polygon_details(old_poly, new_poly) -> list[str]:
        old_fields = {k: v for k, v in _normalize(old_poly).items() if k != "points"}
        new_fields = {k: v for k, v in _normalize(new_poly).items() if k != "points"}
        lines = _flat_details(old_fields, new_fields)
        lines.extend(outline_details(old_poly.points, new_poly.points))
        return lines

    def by_name(asset: Any, attr: str) -> dict[str, Any]:
        items = getattr(asset, attr) if asset is not None else []
        result: dict[str, Any] = {}
        for item in items:
            result.setdefault(item.name, item)
        return result

    section = _diff_keyed(
        "areas",
        by_name(getattr(old, "trigger_areas", None), "trigger_areas"),
        by_name(getattr(new, "trigger_areas", None), "trigger_areas"),
        trigger_details,
    )
    polygons = _diff_keyed(
        "areas",
        by_name(getattr(old, "polygon_triggers", None), "polygon_triggers"),
        by_name(getattr(new, "polygon_triggers", None), "polygon_triggers"),
        polygon_details,
    )
    section.added.extend(polygons.added)
    section.removed.extend(polygons.removed)
    section.changed.extend(polygons.changed)
    return section


def _derived_text(item: ScriptDerived) -> str:
    """One action or condition as a readable call: `MoveTeamTo('TeamA', 'WP_1')`. The name comes
    from the binary's own internal-name record when present (a `(type, index, name)` property-key
    tuple), else the numeric action id."""
    internal_name = item.internal_name
    name = internal_name[2] if isinstance(internal_name, tuple) else internal_name
    if not name:
        name = f"<action {item.content_type}>"
    args = []
    for argument in item.arguments:
        value = typed_value(argument).value
        args.append(f"'{value}'" if isinstance(value, str) else _fmt(value))
    text = f"{name}({', '.join(args)})"
    if item.is_inverted:
        text = f"NOT {text}"
    if item.is_enabled is False:
        text = f"[disabled] {text}"
    return text


def _script_body(script: Script) -> list[str]:
    """A script rendered as one sentence per line - `if:` blocks (conditions within a block AND
    together, blocks OR together), then `do:`/`else:` actions - the unit the body diff compares."""
    lines: list[str] = []
    for index, or_condition in enumerate(script.or_conditions):
        clause = " AND ".join(_derived_text(c) for c in or_condition.conditions)
        lines.append(f"{'or if' if index else 'if'}: {clause}")
    lines.extend(f"do: {_derived_text(action)}" for action in script.actions_if_true)
    lines.extend(f"else: {_derived_text(action)}" for action in script.actions_if_false)
    return lines


# The script header settings worth reporting; None (a version that lacks the field) and the
# empty comment are treated as unset so they never diff against each other.
_SCRIPT_SETTINGS = (
    "comment",
    "is_active",
    "is_subroutine",
    "deactivate_upon_success",
    "active_in_easy",
    "active_in_medium",
    "active_in_hard",
    "evaluation_interval",
    "actions_fire_sequentially",
    "loop_actions",
    "loop_count",
)


def _script_settings(script: Script) -> dict[str, object]:
    settings = {name: getattr(script, name) for name in _SCRIPT_SETTINGS}
    return {name: value for name, value in settings.items() if value not in (None, "")}


def _script_details(old_script: Script, new_script: Script) -> list[str]:
    lines = _flat_details(_script_settings(old_script), _script_settings(new_script))
    old_body, new_body = _script_body(old_script), _script_body(new_script)
    matcher = difflib.SequenceMatcher(a=old_body, b=new_body, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        lines.extend(f"- {line}" for line in old_body[i1:i2])
        lines.extend(f"+ {line}" for line in new_body[j1:j2])
    return lines


def _diff_scripts(old: Map, new: Map) -> SectionDiff:
    """Leaf scripts keyed by name (group nesting dropped, as the symbol harvest does). Duplicate
    names pair off in declaration order; the surplus reports as added/removed."""
    section = SectionDiff("scripts")

    def buckets(map_obj: Map) -> dict[str, list[Script]]:
        result: dict[str, list[Script]] = defaultdict(list)
        for ref in _iter_scripts(map_obj):
            result[ref.script_name].append(ref.script)
        return result

    old_scripts, new_scripts = buckets(old), buckets(new)
    for name in sorted(old_scripts.keys() | new_scripts.keys()):
        old_list = old_scripts.get(name, [])
        new_list = new_scripts.get(name, [])
        for old_script, new_script in zip(old_list, new_list, strict=False):
            details = _script_details(old_script, new_script)
            if details:
                section.changed.append(ChangedEntry(name, details))
        section.removed.extend(name for _ in old_list[len(new_list) :])
        section.added.extend(name for _ in new_list[len(old_list) :])
    return section


def _diff_terrain(old: Map, new: Map) -> SectionDiff:
    """The bulk arrays, summarised: cell counts for the heightmap, a one-liner for the texture
    blend data - a mapper wants to know the terrain was resculpted, not see the cells."""
    section = SectionDiff("terrain")
    old_height = getattr(old, "height_map_data", None)
    new_height = getattr(new, "height_map_data", None)
    if old_height is not None and new_height is not None:
        old_size = (old_height.width, old_height.height)
        new_size = (new_height.width, new_height.height)
        if old_size != new_size:
            section.changed.append(
                ChangedEntry(
                    f"heightmap resized {old_size[0]}x{old_size[1]} -> {new_size[0]}x{new_size[1]}"
                )
            )
        elif old_height.elevations != new_height.elevations:
            cells = sum(
                1
                for old_row, new_row in zip(
                    old_height.elevations, new_height.elevations, strict=True
                )
                for old_cell, new_cell in zip(old_row, new_row, strict=True)
                if old_cell != new_cell
            )
            total = new_size[0] * new_size[1]
            section.changed.append(ChangedEntry(f"heightmap: {cells} of {total} cells changed"))

    old_blend = getattr(old, "blend_tile_data", None)
    new_blend = getattr(new, "blend_tile_data", None)
    if (old_blend is None) != (new_blend is None):
        (section.added if old_blend is None else section.removed).append("texture blending")
    elif old_blend is not None and _normalize(old_blend) != _normalize(new_blend):
        section.changed.append(ChangedEntry("texture blending changed"))
    return section


# The Map slots the curated sections above already cover; every other annotated asset slot gets
# the catch-all equality check so a change there is at least named, never silently dropped.
_DETAILED_SLOTS = {
    "world_info",
    "sides_list",
    "teams",
    "objects_list",
    "trigger_areas",
    "polygon_triggers",
    "player_scripts_list",
    "height_map_data",
    "blend_tile_data",
}


def _diff_other_assets(old: Map, new: Map) -> SectionDiff:
    section = SectionDiff("other assets")
    for slot in Map.__annotations__:
        if slot in _DETAILED_SLOTS:
            continue
        old_asset = getattr(old, slot, None)
        new_asset = getattr(new, slot, None)
        if old_asset is None and new_asset is None:
            continue
        if old_asset is None:
            section.added.append(slot)
        elif new_asset is None:
            section.removed.append(slot)
        elif _normalize(old_asset) != _normalize(new_asset):
            section.changed.append(ChangedEntry(f"{slot} changed"))
    return section


def diff_maps(old: Map, new: Map) -> MapDiff:
    """Diff two parsed maps into the non-empty report sections."""
    sections = [
        _flat_section(
            "settings",
            _props(getattr(old, "world_info", None)),
            _props(getattr(new, "world_info", None)),
        ),
        _diff_players(old, new),
        _diff_teams(old, new),
        _diff_objects(old, new),
        _diff_areas(old, new),
        _diff_scripts(old, new),
        _diff_terrain(old, new),
        _diff_other_assets(old, new),
    ]
    return MapDiff([section for section in sections if not section.is_empty()])


def diff_map_files(old_path: str | Path, new_path: str | Path) -> MapDiff:
    """Parse and diff two `.map`/`.bse` files on disk."""
    return diff_maps(parse_map_from_path(str(old_path)), parse_map_from_path(str(new_path)))


def _render_sections(diff: MapDiff, lines: list[str], heading: str) -> None:
    for section in diff.sections:
        lines.append(f"{heading} {section.title}")
        lines.extend(f"+ {entry}" for entry in section.added)
        lines.extend(f"- {entry}" for entry in section.removed)
        for entry in section.changed:
            lines.append(f"~ {entry.label}")
            lines.extend(f"    {detail}" for detail in entry.details)
        lines.append("")


def format_map_diff(diff: MapDiff, old_label: str, new_label: str) -> str:
    """Render one map's diff as a standalone changelog."""
    lines = [f"# map diff: {old_label} -> {new_label}", ""]
    if diff.is_empty():
        lines.append("(no differences)")
    else:
        _render_sections(diff, lines, "##")
    return "\n".join(lines).rstrip() + "\n"


@dataclass(frozen=True)
class MapFileChange:
    """One map file a commit (or rev range) touches. `status` is the git kind - "A" added,
    "D" deleted, "M" modified, "R" renamed (`old_path` set) - with copies folded into "A"."""

    status: str
    path: str
    old_path: str | None = None


def _git(repo: str | Path, *args: str) -> bytes:
    """Run git against `repo` and return raw stdout - bytes, because blob content is binary."""
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def _list_changes(repo: str | Path, revs: tuple[str, ...]) -> list[MapFileChange]:
    """The map files `git diff-tree` reports changed - for one commit (against its parents;
    `--root` so an initial commit lists its maps as additions) or between two endpoint revs."""
    out = _git(
        repo, "diff-tree", "-r", "--root", "--no-commit-id", "--name-status", "-M", "-z", *revs
    ).decode("utf-8", errors="replace")
    tokens = out.split("\0")
    changes: list[MapFileChange] = []
    index = 0
    while index < len(tokens) and tokens[index]:
        kind = tokens[index][0]
        if kind in ("R", "C"):
            old_path, path = tokens[index + 1], tokens[index + 2]
            index += 3
            change = MapFileChange("A" if kind == "C" else "R", path, old_path)
        else:
            change = MapFileChange(kind, tokens[index + 1])
            index += 2
        if Path(change.path).suffix.lower() in MAP_SUFFIXES:
            changes.append(change)
    return changes


def commit_map_changes(repo: str | Path, commit: str = "HEAD") -> list[MapFileChange]:
    """The `.map`/`.bse` files `commit` adds, removes, modifies or renames."""
    return _list_changes(repo, (commit,))


def range_map_changes(repo: str | Path, old: str, new: str) -> list[MapFileChange]:
    """The `.map`/`.bse` files that differ between two revs - the *net* change over a range, so
    a map touched by several commits reports once, and one changed then reverted not at all."""
    return _list_changes(repo, (old, new))


def resolve_range(repo: str | Path, spec: str) -> tuple[str, str] | None:
    """Split a git range `old..new` / `old...new` into its endpoint revs, or return None when
    `spec` is a single commit. An empty side defaults to HEAD, and the three-dot form diffs from
    the merge base, matching `git diff` semantics ("what did new change since it forked off
    old"). Ref names cannot contain `..`, so the split is unambiguous."""
    if "..." in spec:
        old, _, new = spec.partition("...")
        old, new = old or "HEAD", new or "HEAD"
        return _git(repo, "merge-base", old, new).decode().strip()[:12], new
    if ".." in spec:
        old, _, new = spec.partition("..")
        return old or "HEAD", new or "HEAD"
    return None


def _parse_blob(data: bytes) -> Map:
    return parse_map(io.BytesIO(data))


def _map_at(repo: str | Path, ref: str, path: str) -> Map:
    return _parse_blob(_git(repo, "cat-file", "blob", f"{ref}:{path}"))


def _map_summary(map_obj: Map) -> str:
    """A one-line profile of a whole map, for files that were added or deleted outright."""
    parts = []
    height_map = getattr(map_obj, "height_map_data", None)
    if height_map is not None:
        parts.append(f"{height_map.width}x{height_map.height}")
    objects_list = getattr(map_obj, "objects_list", None)
    count = len(objects_list.object_list) if objects_list is not None else 0
    parts.append(f"{count} object(s)")
    parts.append(f"{sum(1 for _ in _iter_scripts(map_obj))} script(s)")
    return ", ".join(parts)


@dataclass
class MapFileDiff:
    """The report for one changed map file: a content diff for a modified/renamed one, a one-line
    summary for an added/deleted one, or the parse error that prevented either."""

    change: MapFileChange
    diff: MapDiff | None = None
    summary: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        """JSON-ready data for one file, the change flattened in; `sections` is None for an
        added/deleted map (see `summary`) or a parse failure (see `error`)."""
        return {
            "status": self.change.status,
            "path": self.change.path,
            "old_path": self.change.old_path,
            "summary": self.summary,
            "error": self.error,
            "sections": self.diff.to_dict()["sections"] if self.diff is not None else None,
        }


def _diff_changes(
    repo: str | Path, changes: list[MapFileChange], old_ref: str, new_ref: str
) -> list[MapFileDiff]:
    """Diff each listed map file between `old_ref` and `new_ref`. A file that fails to parse
    (either side) reports its error instead of aborting the batch."""
    results: list[MapFileDiff] = []
    for change in changes:
        try:
            if change.status == "A":
                summary = _map_summary(_map_at(repo, new_ref, change.path))
                results.append(MapFileDiff(change, summary=summary))
            elif change.status == "D":
                summary = _map_summary(_map_at(repo, old_ref, change.path))
                results.append(MapFileDiff(change, summary=summary))
            else:
                old = _map_at(repo, old_ref, change.old_path or change.path)
                new = _map_at(repo, new_ref, change.path)
                results.append(MapFileDiff(change, diff=diff_maps(old, new)))
        except Exception as exc:  # noqa: BLE001 - one unreadable binary map must not abort the batch
            results.append(MapFileDiff(change, error=str(exc)))
    return results


def diff_commit_maps(repo: str | Path, commit: str = "HEAD") -> list[MapFileDiff]:
    """Diff every map file `commit` touches against the commit's parent. A bad commit or repo
    raises `subprocess.CalledProcessError` from the initial listing."""
    return _diff_changes(repo, commit_map_changes(repo, commit), f"{commit}^", commit)


def diff_range_maps(repo: str | Path, old: str, new: str) -> list[MapFileDiff]:
    """Diff every map file that changed between two revs - the net change over the whole
    range, endpoint against endpoint."""
    return _diff_changes(repo, range_map_changes(repo, old, new), old, new)


def format_map_file_diffs(results: list[MapFileDiff], old_label: str, new_label: str) -> str:
    """Render a set of per-file map diffs as one changelog, a `##` block per file."""
    lines = [
        f"# map diff: {old_label} -> {new_label}",
        f"{len(results)} map file(s) changed",
        "",
    ]
    if not results:
        lines[-1] = "(no map files changed)"
        return "\n".join(lines).rstrip() + "\n"

    for result in results:
        change = result.change
        if change.status == "A":
            lines.append(f"## + {change.path}")
            lines.append(f"new map: {result.summary}" if result.error is None else "new map")
        elif change.status == "D":
            lines.append(f"## - {change.path}")
            removed = f"removed map: {result.summary}" if result.error is None else "removed map"
            lines.append(removed)
        else:
            renamed = f" (renamed from {change.old_path})" if change.old_path else ""
            lines.append(f"## {change.path}{renamed}")
            if result.diff is not None and result.diff.is_empty():
                lines.append("(bytes differ but the parsed content matches)")
            elif result.diff is not None:
                lines.append("")
                _render_sections(result.diff, lines, "###")
        if result.error is not None:
            lines.append(f"failed to parse: {result.error}")
        if lines[-1]:
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _md(text: str) -> str:
    """A value quoted as markdown code, so names like `*Waypoints/Waypoint` or `GG_ENDING`
    render literally instead of as emphasis."""
    return f"`{text}`"


def _render_sections_md(diff: MapDiff, lines: list[str], heading: str) -> None:
    for section in diff.sections:
        lines.append(f"{heading} {section.title}")
        lines.append("")
        lines.extend(f"- **Added:** {_md(entry)}" for entry in section.added)
        lines.extend(f"- **Removed:** {_md(entry)}" for entry in section.removed)
        for entry in section.changed:
            lines.append(f"- **Changed:** {_md(entry.label)}")
            lines.extend(f"  - {_md(detail)}" for detail in entry.details)
        lines.append("")


def format_map_file_diffs_md(results: list[MapFileDiff], old_label: str, new_label: str) -> str:
    """Render a set of per-file map diffs as GitHub-flavoured markdown - the same report as
    `format_map_file_diffs`, restructured as headed bullet lists with values code-quoted, so it
    pastes cleanly into a PR description or wiki page."""
    lines = [f"# Map diff: {_md(old_label)} -> {_md(new_label)}", ""]
    if not results:
        lines.append("_No map files changed._")
        return "\n".join(lines).rstrip() + "\n"
    lines.extend([f"{len(results)} map file(s) changed", ""])

    for result in results:
        change = result.change
        if change.status == "A":
            lines.extend([f"## {_md(change.path)} (added)", ""])
            if result.error is None:
                lines.append(f"New map: {result.summary}.")
        elif change.status == "D":
            lines.extend([f"## {_md(change.path)} (removed)", ""])
            if result.error is None:
                lines.append(f"Removed map: {result.summary}.")
        else:
            renamed = f" (renamed from {_md(change.old_path)})" if change.old_path else ""
            lines.extend([f"## {_md(change.path)}{renamed}", ""])
            if result.diff is not None and result.diff.is_empty():
                lines.append("_Bytes differ but the parsed content matches._")
            elif result.diff is not None:
                _render_sections_md(result.diff, lines, "###")
        if result.error is not None:
            lines.append(f"_Failed to parse: {result.error}_")
        if lines[-1]:
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
