"""What an agent can do to a map, as plain functions over a `MapDocument`.

This layer is free of Qt and of the MCP SDK: every tool takes and returns JSON-shaped values, and
every edit goes through `MapDocument.execute`, so it lands on the undo stack as one entry and any
view subscribed to the document hears about it. The stdio server in `server` wraps these
functions; a bridge into the running editor can wrap the same session around the editor's own
document.

Placed objects are addressed by their `uniqueID` property, which survives inserts and deletes
around them; an object without one is addressed as `#<index>` into the object list. The user
points at places with markers (`sage_worldbuilder.markers`): areas named A, B, C, ..., points P1,
P2, ... and paths through points L1, L2, ... The tools that take a rectangle also take an area's
name as `region`, and paint_path paints along a path.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import numpy as np

from sage_map.assets.blend_tile_data import BlendTileData, BlendTileTexture
from sage_map.assets.object_list import Object
from sage_map.context import AssetPropertyType, Property, PropertyValue
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands import SetAttribute
from sage_worldbuilder.commands.edits import SetProperty
from sage_worldbuilder.commands.objects import (
    DeleteObjects,
    MoveObjects,
    new_object,
    place_objects,
)
from sage_worldbuilder.commands.terrain import (
    PaintBlends,
    PaintTiles,
    PatchHeights,
    RenameTexture,
)
from sage_worldbuilder.document import MapDocument
from sage_worldbuilder.dressing import NEUTRAL_OWNER
from sage_worldbuilder.markers import (
    AreaMarker,
    Marker,
    MarkerError,
    MarkerKind,
    PathMarker,
    PointMarker,
    distance_to_polyline,
    path_length,
    polygon_contains,
)
from sage_worldbuilder.new_map import DEFAULT_CELL_SIZE
from sage_worldbuilder.render.topdown import tile_classes
from sage_worldbuilder.scene import WAYPOINT_PREFIX
from sage_worldbuilder.summary import map_summary
from sage_worldbuilder.teams import qualified_team_name, team_list
from sage_worldbuilder.terrain import FEET_PER_HEIGHT_UNIT, MAX_HEIGHT, WORLD_UNITS_PER_CELL
from sage_worldbuilder.terrain.apply_texture import ApplyTextureOptions, apply_texture
from sage_worldbuilder.terrain.blending import (
    BlendEdit,
    auto_edge_in,
    auto_edge_out,
    flood_fill,
)
from sage_worldbuilder.terrain.cells import TileLayer
from sage_worldbuilder.terrain.textures import (
    TextureCapacityError,
    paint_texture_block,
    planned_texture,
    texture_classes,
    texture_index,
    tiling_offset,
)

__all__ = ["MAX_PAGE", "MAX_SAMPLES", "TOOLS", "ToolError", "WorldBuilderSession"]

# The most rows one list call returns, and the most height samples one sample call returns.
MAX_PAGE = 200
MAX_SAMPLES = 4096
# A region description names its objects one by one up to this many, and its templates up to
# `_REGION_TEMPLATES`; past that, list_objects with the region pages through them.
_REGION_OBJECTS = 50
_REGION_TEMPLATES = 40
# blend_region edges at most this many texture areas, the largest first.
MAX_BLEND_AREAS = 100
# A point's description lists the objects within this many world units of it.
_POINT_NEARBY = 100.0
# A screenshot of a point or a thin path still shows at least this much ground round it.
MIN_SHOT_SPAN = 200.0

_OBJECTS = Change(ChangeKind.OBJECTS)

# The session methods an agent may call: the server registers these and the editor's bridge
# dispatches only these, never an arbitrary attribute.
TOOLS = (
    "open_map",
    "save_map",
    "map_info",
    "list_objects",
    "get_object",
    "list_teams",
    "place_object",
    "move_object",
    "rotate_object",
    "delete_objects",
    "set_object_property",
    "get_selection",
    "select_objects",
    "sample_heights",
    "set_terrain_height",
    "undo",
    "redo",
    "view_at",
    "screenshot",
    "get_markers",
    "describe_marker",
    "mark_area",
    "mark_point",
    "mark_path",
    "edit_marker",
    "delete_markers",
    "list_textures",
    "paint_texture",
    "paint_texture_by_terrain",
    "flood_fill_texture",
    "auto_blend",
    "blend_region",
    "paint_path",
)

Bounds = tuple[float, float, float, float]


class ToolError(ValueError):
    """A tool call the session cannot carry out; the message is meant for the agent."""


def _text(obj: Object, key: str) -> str:
    stored = obj.properties.get(key)
    return str(stored["value"]) if stored is not None and stored["value"] is not None else ""


def _brief(obj: Object, index: int) -> dict[str, Any]:
    x, y, z = obj.position
    return {
        "id": _text(obj, "uniqueID") or f"#{index}",
        "template": obj.type_name,
        "x": round(x, 2),
        "y": round(y, 2),
        "z": round(z, 2),
        "angle": round(math.degrees(obj.angle), 2),
        "owner": _text(obj, "originalOwner"),
        "layer": _text(obj, "objectLayer"),
    }


def _a(kind: MarkerKind) -> str:
    return f"an {kind.value}" if kind is MarkerKind.AREA else f"a {kind.value}"


def _area_info(area: AreaMarker) -> dict[str, Any]:
    x0, y0, x1, y1 = area.bounds
    return {
        "name": area.name,
        "kind": "area",
        "points": [list(point) for point in area.points],
        "bounds": [x0, y0, x1, y1],
        "size": [round(x1 - x0, 1), round(y1 - y0, 1)],
        "rectangle": area.is_rectangle,
    }


def _overlaps(points: list[tuple[float, float]], bounds: Bounds) -> bool:
    """Whether a polygon's bounding box meets a rectangle."""
    if not points:
        return False
    x0, y0, x1, y1 = bounds
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs) <= x1 and max(xs) >= x0 and min(ys) <= y1 and max(ys) >= y0


def _texture_shares(blend: BlendTileData, classes: np.ndarray) -> dict[str, float]:
    """Texture name -> the share of `classes` (texture indices) showing it, the most first."""
    painted = Counter(classes.ravel().tolist())
    total = max(sum(painted.values()), 1)
    return {
        blend.textures[index].name: round(count / total, 3)
        for index, count in painted.most_common()
        if 0 <= index < len(blend.textures)
    }


def _along(points: list[tuple[float, float]], step: float) -> list[tuple[float, float]]:
    """Positions every `step` world units along a line through `points`, both ends included."""
    samples = [points[0]] if points else []
    for (ax, ay), (bx, by) in zip(points, points[1:], strict=False):
        count = max(1, math.ceil(math.dist((ax, ay), (bx, by)) / step))
        samples += [
            (ax + (bx - ax) * i / count, ay + (by - ay) * i / count) for i in range(1, count + 1)
        ]
    return samples


def _areas_in(classes: np.ndarray, open_cells: np.ndarray) -> list[tuple[int, int, int]]:
    """Each 4-connected area of one texture among the `open_cells` of a block: its size and a
    cell `(x, y)` in it, the largest first."""
    rows, columns = classes.shape
    seen = ~open_cells
    areas: list[tuple[int, int, int]] = []
    for row in range(rows):
        for column in range(columns):
            if seen[row, column]:
                continue
            texture = classes[row, column]
            seen[row, column] = True
            pending, size = [(row, column)], 0
            while pending:
                y, x = pending.pop()
                size += 1
                for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if (
                        0 <= ny < rows
                        and 0 <= nx < columns
                        and not seen[ny, nx]
                        and classes[ny, nx] == texture
                    ):
                        seen[ny, nx] = True
                        pending.append((ny, nx))
            areas.append((size, column, row))
    areas.sort(key=lambda area: -area[0])
    return areas


def _property_type(value: PropertyValue) -> AssetPropertyType:
    # bool first: it is an int subclass.
    if isinstance(value, bool):
        return AssetPropertyType.Boolean
    if isinstance(value, int):
        return AssetPropertyType.Integer
    if isinstance(value, float):
        return AssetPropertyType.RealNumber
    return AssetPropertyType.AsciiString


def _coerce(kind: AssetPropertyType, value: PropertyValue) -> PropertyValue:
    if kind is AssetPropertyType.Boolean:
        return bool(value)
    if kind is AssetPropertyType.Integer:
        return int(value)
    if kind is AssetPropertyType.RealNumber:
        return float(value)
    return str(value)


class WorldBuilderSession:
    """One agent's handle on one open map at a time."""

    def __init__(self, document: MapDocument | None = None) -> None:
        self.document = document

    @property
    def _doc(self) -> MapDocument:
        if self.document is None:
            raise ToolError("no map is open; call open_map first")
        return self.document

    @contextmanager
    def _edit(self, label: str) -> Iterator[None]:
        """Run the block as one undo entry; a failure inside it leaves the map as it was."""
        try:
            with self._doc.stack.group(label):
                yield
        except (KeyError, IndexError, TypeError) as error:
            raise ToolError(str(error)) from error

    def _objects(self) -> list[Object]:
        listed = self._doc.map.objects_list
        return listed.object_list if listed is not None else []

    def _find(self, object_id: str) -> tuple[int, Object]:
        objects = self._objects()
        if object_id.startswith("#"):
            try:
                index = int(object_id[1:])
                return index, objects[index]
            except (ValueError, IndexError):
                raise ToolError(f"no object at {object_id}") from None
        for index, obj in enumerate(objects):
            if _text(obj, "uniqueID") == object_id:
                return index, obj
        raise ToolError(f"no object with id {object_id!r}")

    def _id_of(self, obj: Object) -> str:
        for index, candidate in enumerate(self._objects()):
            if candidate is obj:
                return _brief(obj, index)["id"]
        raise ToolError("the object is not on the map")

    def open_map(self, path: str) -> dict[str, Any]:
        try:
            self.document = MapDocument.open(path)
        except OSError as error:
            raise ToolError(f"cannot open {path}: {error}") from error
        return self.map_info()

    def save_map(self, path: str | None = None) -> dict[str, Any]:
        try:
            target = self._doc.save(path)
        except (OSError, ValueError) as error:
            raise ToolError(str(error)) from error
        return {"saved": str(target)}

    def map_info(self) -> dict[str, Any]:
        doc = self._doc
        info: dict[str, Any] = {
            "title": doc.title,
            "path": str(doc.path) if doc.path is not None else None,
            "read_only": doc.read_only,
            "dirty": doc.dirty,
            "summary": dict(map_summary(doc.map)),
            "units": {
                "world_units_per_cell": WORLD_UNITS_PER_CELL,
                "height": "feet (world units), stored as uint16 x 10/256",
                "angle": "degrees (the map stores radians)",
                "origin": "world (0, 0) is the bottom-left corner of the playable area",
            },
        }
        grid = doc.terrain
        if grid is not None:
            border = grid.border
            info["playable_extent"] = {
                "x": [0.0, (grid.width - 1 - 2 * border) * WORLD_UNITS_PER_CELL],
                "y": [0.0, (grid.height - 1 - 2 * border) * WORLD_UNITS_PER_CELL],
            }
        info["undo"] = doc.stack.undo_label
        info["redo"] = doc.stack.redo_label
        return info

    def list_objects(
        self,
        name_filter: str = "",
        bounds: Bounds | None = None,
        include_waypoints: bool = False,
        offset: int = 0,
        limit: int = 50,
        region: str | None = None,
    ) -> dict[str, Any]:
        """Placed objects whose template contains `name_filter` (ignoring case), optionally only
        those inside `bounds` (`x0, y0, x1, y1` in world units) or a marked `region`, one page at
        a time."""
        area = self._region(region) if region is not None else None
        if area is not None:
            bounds = area.bounds
        needle = name_filter.lower()
        limit = max(1, min(limit, MAX_PAGE))
        matches: list[dict[str, Any]] = []
        for index, obj in enumerate(self._objects()):
            if not include_waypoints and obj.type_name.startswith(WAYPOINT_PREFIX):
                continue
            if needle and needle not in obj.type_name.lower():
                continue
            if bounds is not None:
                x0, y0, x1, y1 = bounds
                x, y, _ = obj.position
                if not (min(x0, x1) <= x <= max(x0, x1) and min(y0, y1) <= y <= max(y0, y1)):
                    continue
                if area is not None and not area.is_rectangle and not area.contains(x, y):
                    continue
            matches.append(_brief(obj, index))
        page = matches[offset : offset + limit]
        return {"total": len(matches), "offset": offset, "objects": page}

    def get_object(self, object_id: str) -> dict[str, Any]:
        index, obj = self._find(object_id)
        result = _brief(obj, index)
        result["properties"] = {
            name: {"type": AssetPropertyType(prop["type"]).name, "value": prop["value"]}
            for name, prop in obj.properties.items()
        }
        return result

    def list_teams(self) -> list[str]:
        """The owner names `place_object` accepts; `/team` is the neutral owner."""
        return [qualified_team_name(team) for team in team_list(self._doc.map) or []]

    def place_object(
        self,
        template: str,
        x: float,
        y: float,
        angle: float = 0.0,
        owner: str = NEUTRAL_OWNER,
        layer: str = "",
    ) -> dict[str, Any]:
        doc = self._doc
        if doc.map.objects_list is None:
            raise ToolError("the map has no object list")
        teams = self.list_teams()
        if owner != NEUTRAL_OWNER and owner not in teams:
            raise ToolError(f"unknown owner {owner!r}; list_teams gives the valid ones")
        obj = new_object(doc.map, template, (x, y, 0.0), math.radians(angle), owner, layer)
        with self._edit(f"Place {template}"):
            doc.execute(place_objects(doc.map, [obj]))
        return self.get_object(self._id_of(obj))

    def move_object(
        self, object_id: str, x: float, y: float, z: float | None = None
    ) -> dict[str, Any]:
        """Move an object to `x, y`; `z`, when given, is its height above the ground."""
        index, obj = self._find(object_id)
        old_x, old_y, old_z = obj.position
        dz = 0.0 if z is None else z - old_z
        command = MoveObjects([obj], x - old_x, y - old_y, dz=dz)
        command.closed = True
        with self._edit("Move"):
            self._doc.execute(command)
        return _brief(obj, index)

    def rotate_object(self, object_id: str, angle: float) -> dict[str, Any]:
        index, obj = self._find(object_id)
        with self._edit("Rotate"):
            self._doc.execute(SetAttribute(obj, "angle", math.radians(angle), _OBJECTS, "Rotate"))
        return _brief(obj, index)

    def delete_objects(self, object_ids: list[str]) -> dict[str, Any]:
        objects = [self._find(object_id)[1] for object_id in object_ids]
        with self._edit("Delete"):
            self._doc.execute(DeleteObjects(objects))
        return {"deleted": len(objects)}

    def set_object_property(
        self, object_id: str, name: str, value: PropertyValue | None
    ) -> dict[str, Any]:
        """Set one property, keeping its stored type when it has one; `None` removes it."""
        _, obj = self._find(object_id)
        new: Property | None = None
        if value is not None:
            existing = obj.properties.get(name)
            if existing is not None:
                kind = AssetPropertyType(existing["type"])
            else:
                kind = _property_type(value)
            try:
                new = {"name": name, "type": kind, "value": _coerce(kind, value)}
            except (TypeError, ValueError) as error:
                raise ToolError(f"{name} is {kind.name}: {error}") from error
        with self._edit(f"Set {name}"):
            self._doc.execute(SetProperty(obj.properties, name, new, _OBJECTS))
        return self.get_object(object_id)

    def _marker(self, name: str) -> Marker:
        marker = self._doc.markers.get(name)
        if marker is None:
            marked = ", ".join(m.name for m in self._doc.markers) or "none"
            raise ToolError(f"no marker {name!r} (marked: {marked})")
        return marker

    def _region(self, name: str) -> AreaMarker:
        """A marked area, for the tools that take a `region`."""
        marker = self._doc.markers.get(name)
        if marker is None:
            marked = ", ".join(a.name for a in self._doc.markers.areas()) or "none"
            raise ToolError(f"no marked area {name!r} (marked areas: {marked})")
        if not isinstance(marker, AreaMarker):
            hint = "; paint along it with paint_path" if isinstance(marker, PathMarker) else ""
            raise ToolError(f"{marker.name} is {_a(marker.kind)}, not an area{hint}")
        return marker

    def _path(self, name: str) -> tuple[PathMarker, list[tuple[float, float]]]:
        marker = self._marker(name)
        if not isinstance(marker, PathMarker):
            raise ToolError(f"{marker.name} is {_a(marker.kind)}, not a path")
        return marker, self._doc.markers.path_points(marker)

    def _marker_bounds(self, name: str) -> Bounds:
        """The ground a marker covers, for a picture of it: an area's bounds, or a point's or
        path's with room round it, at least `MIN_SHOT_SPAN` across."""
        marker = self._marker(name)
        if isinstance(marker, AreaMarker):
            return marker.bounds
        points = (
            [marker.position]
            if isinstance(marker, PointMarker)
            else self._doc.markers.path_points(marker)
        )
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        grow_x = max(0.0, MIN_SHOT_SPAN - (x1 - x0)) / 2
        grow_y = max(0.0, MIN_SHOT_SPAN - (y1 - y0)) / 2
        return x0 - grow_x, y0 - grow_y, x1 + grow_x, y1 + grow_y

    def _cell_positions(self, block: tuple[int, int, int, int]) -> tuple[np.ndarray, np.ndarray]:
        """The world position of each cell of a half-open cell block, as two arrays."""
        grid = self._doc.terrain
        assert grid is not None
        x0, y0, x1, y1 = block
        columns, rows = np.meshgrid(np.arange(x0, x1), np.arange(y0, y1))
        return (
            (columns - grid.border) * WORLD_UNITS_PER_CELL,
            (rows - grid.border) * WORLD_UNITS_PER_CELL,
        )

    def _area_mask(
        self, area: AreaMarker | None, block: tuple[int, int, int, int]
    ) -> np.ndarray | None:
        """Which cells of a block lie in an area; None for no area or a rectangle (all of
        them)."""
        if area is None or area.is_rectangle:
            return None
        return polygon_contains(area.points, *self._cell_positions(block))

    def _bounds(
        self,
        x0: float | None,
        y0: float | None,
        x1: float | None,
        y1: float | None,
        region: str | None,
    ) -> Bounds:
        """A rectangle given as corners or as a marked region's name."""
        if region is not None:
            return self._region(region).bounds
        if x0 is None or y0 is None or x1 is None or y1 is None:
            raise ToolError("give the rectangle as x0, y0, x1, y1 or as a marked region")
        return x0, y0, x1, y1

    def _sample_rect(self, x0: float, y0: float, x1: float, y1: float) -> tuple[int, int, int, int]:
        grid = self._doc.terrain
        if grid is None:
            raise ToolError("the map has no heightmap")
        first = grid.world_to_cell(min(x0, x1), min(y0, y1))
        last = grid.world_to_cell(max(x0, x1), max(y0, y1))
        column0 = max(0, math.floor(first[0] + 0.5))
        row0 = max(0, math.floor(first[1] + 0.5))
        column1 = min(grid.width - 1, math.floor(last[0] + 0.5))
        row1 = min(grid.height - 1, math.floor(last[1] + 0.5))
        if column1 < column0 or row1 < row0:
            raise ToolError("the rectangle is off the heightmap")
        return column0, row0, column1, row1

    def sample_heights(
        self,
        x0: float | None = None,
        y0: float | None = None,
        x1: float | None = None,
        y1: float | None = None,
        step: float = WORLD_UNITS_PER_CELL,
        region: str | None = None,
    ) -> dict[str, Any]:
        """Ground heights in feet over a rectangle or a marked region, every `step` world units,
        as rows from the bottom up. The step grows when there would be too many samples."""
        grid = self._doc.terrain
        column0, row0, column1, row1 = self._sample_rect(*self._bounds(x0, y0, x1, y1, region))
        stride = max(1, round(step / WORLD_UNITS_PER_CELL))
        while ((column1 - column0) // stride + 1) * ((row1 - row0) // stride + 1) > MAX_SAMPLES:
            stride += 1
        assert grid is not None
        block = grid.heights[row0 : row1 + 1 : stride, column0 : column1 + 1 : stride]
        origin = grid.cell_to_world(column0, row0)
        return {
            "origin": [origin[0], origin[1]],
            "step": stride * WORLD_UNITS_PER_CELL,
            "rows": [[round(float(v) * FEET_PER_HEIGHT_UNIT, 2) for v in row] for row in block],
        }

    def set_terrain_height(
        self,
        x0: float | None = None,
        y0: float | None = None,
        x1: float | None = None,
        y1: float | None = None,
        height: float = 0.0,
        region: str | None = None,
    ) -> dict[str, Any]:
        """Flatten a rectangle (world units) or a marked area to `height` feet."""
        column0, row0, column1, row1 = self._sample_rect(*self._bounds(x0, y0, x1, y1, region))
        stored = round(height / FEET_PER_HEIGHT_UNIT)
        if not 0 <= stored <= MAX_HEIGHT:
            raise ToolError(f"height must be 0 to {MAX_HEIGHT * FEET_PER_HEIGHT_UNIT:.1f} feet")
        values = np.full((row1 - row0 + 1, column1 - column0 + 1), stored, dtype=np.uint16)
        area = self._region(region) if region is not None else None
        mask = self._area_mask(area, (column0, row0, column1 + 1, row1 + 1))
        if mask is not None:
            grid = self._doc.terrain
            assert grid is not None
            current = grid.heights[row0 : row1 + 1, column0 : column1 + 1]
            values = np.where(mask, values, current).astype(np.uint16)
        command = PatchHeights(column0, row0, values, label="Set Height")
        command.closed = True
        with self._edit("Set Height"):
            self._doc.execute(command)
        samples = int(mask.sum()) if mask is not None else int(values.size)
        return {"samples": samples, "height": stored * FEET_PER_HEIGHT_UNIT}

    def get_selection(self) -> list[dict[str, Any]]:
        """The selected placed objects (in the editor, what the user has selected)."""
        chosen = {id(item) for item in self._doc.selection}
        return [_brief(obj, i) for i, obj in enumerate(self._objects()) if id(obj) in chosen]

    def select_objects(self, object_ids: list[str]) -> list[dict[str, Any]]:
        """Replace the selection with these objects; an empty list clears it."""
        self._doc.selection.set([self._find(object_id)[1] for object_id in object_ids])
        return self.get_selection()

    def view_at(self, x: float, y: float, zoom: float = 1.0) -> dict[str, Any]:
        """Centre the editor's view on a world position; headless there is no view."""
        raise ToolError("there is no view to move: the server is not connected to the editor")

    def screenshot(self, max_width: int = 1280, marker: str | None = None) -> dict[str, Any]:
        """The editor's view as a base64 PNG, or the part of it showing a marker; headless there
        is no view."""
        raise ToolError("there is no view to capture: the server is not connected to the editor")

    # Markers: areas, points and paths the user (or the agent) drew to name places.

    @contextmanager
    def _marking(self) -> Iterator[None]:
        try:
            yield
        except MarkerError as error:
            raise ToolError(str(error)) from error

    def _kind(self, kind: str | None) -> MarkerKind | None:
        if kind is None:
            return None
        try:
            return MarkerKind(kind.strip().lower())
        except ValueError:
            raise ToolError("kind is one of area, point, path") from None

    def _height_at(self, x: float, y: float) -> float | None:
        grid = self._doc.terrain
        stored = grid.elevation_at(x, y) if grid is not None else None
        return round(stored * FEET_PER_HEIGHT_UNIT, 2) if stored is not None else None

    def _marker_info(self, marker: Marker) -> dict[str, Any]:
        markers = self._doc.markers
        if isinstance(marker, AreaMarker):
            return _area_info(marker)
        if isinstance(marker, PointMarker):
            info: dict[str, Any] = {"name": marker.name, "kind": "point", "x": marker.x}
            info["y"] = marker.y
            height = self._height_at(marker.x, marker.y)
            if height is not None:
                info["height"] = height
            paths = [path.name for path in markers.paths_through(marker.name)]
            if paths:
                info["paths"] = paths
            return info
        points = markers.path_points(marker)
        return {
            "name": marker.name,
            "kind": "path",
            "stops": list(marker.stops),
            "points": [list(point) for point in points],
            "length": round(path_length(points), 1),
        }

    def get_markers(self, kind: str | None = None) -> list[dict[str, Any]]:
        """The markers in the order they were made: areas (polygons), points, and paths through
        points; or only one `kind`."""
        wanted = self._kind(kind)
        return [
            self._marker_info(marker)
            for marker in self._doc.markers
            if wanted is None or marker.kind is wanted
        ]

    def describe_marker(self, name: str) -> dict[str, Any]:
        """What a marker covers. An area: its objects, waypoints and trigger areas, its terrain's
        heights and slope, and its textures. A point: its height and texture and the objects
        near it. A path: its length and the ground along it (heights, steepest grade,
        textures)."""
        marker = self._marker(name)
        if isinstance(marker, AreaMarker):
            return self._describe_area(marker)
        if isinstance(marker, PointMarker):
            return self._describe_point(marker)
        return self._describe_path(marker)

    def _describe_area(self, area: AreaMarker) -> dict[str, Any]:
        doc = self._doc
        info = _area_info(area)
        info["cells"] = [round(size / WORLD_UNITS_PER_CELL, 1) for size in info["size"]]
        objects: list[dict[str, Any]] = []
        waypoints: list[str] = []
        for index, obj in enumerate(self._objects()):
            x, y, _ = obj.position
            if not area.contains(x, y):
                continue
            if obj.type_name.startswith(WAYPOINT_PREFIX):
                waypoints.append(_text(obj, "waypointName") or f"#{index}")
            else:
                objects.append(_brief(obj, index))
        templates = Counter(obj["template"] for obj in objects)
        listed: dict[str, Any] = {
            "total": len(objects),
            "by_template": dict(templates.most_common(_REGION_TEMPLATES)),
        }
        if len(objects) <= _REGION_OBJECTS:
            listed["list"] = objects
        info["objects"] = listed
        info["waypoints"] = waypoints
        areas = doc.map.trigger_areas
        info["trigger_areas"] = [
            trigger.name
            for trigger in (areas.trigger_areas if areas is not None else [])
            if _overlaps(trigger.points, area.bounds)
        ]
        terrain = self._area_terrain(area)
        if terrain is not None:
            info["terrain"] = terrain
        return info

    def _area_terrain(self, area: AreaMarker) -> dict[str, Any] | None:
        doc = self._doc
        grid = doc.terrain
        if grid is None:
            return None
        try:
            column0, row0, column1, row1 = self._sample_rect(*area.bounds)
        except ToolError:
            return None
        block = grid.heights[row0 : row1 + 1, column0 : column1 + 1] * FEET_PER_HEIGHT_UNIT
        mask = self._area_mask(area, (column0, row0, column1 + 1, row1 + 1))
        if mask is None:
            mask = np.ones(block.shape, dtype=bool)
        if not mask.any():
            return None
        inside = block[mask]
        terrain: dict[str, Any] = {
            "min_height": round(float(inside.min()), 2),
            "max_height": round(float(inside.max()), 2),
            "mean_height": round(float(inside.mean()), 2),
        }
        if block.shape[0] > 1 and block.shape[1] > 1:
            rise_y, rise_x = np.gradient(block, WORLD_UNITS_PER_CELL)
            slope = np.degrees(np.arctan(np.hypot(rise_x, rise_y)))[mask]
            terrain["max_slope_degrees"] = round(float(slope.max()), 1)
            terrain["mean_slope_degrees"] = round(float(slope.mean()), 1)
        blend = doc.map.blend_tile_data
        if blend is not None:
            classes = tile_classes(blend)
            if classes.shape == grid.heights.shape:
                under = classes[row0 : row1 + 1, column0 : column1 + 1][mask]
                terrain["textures"] = _texture_shares(blend, under)
        return terrain

    def _describe_point(self, point: PointMarker) -> dict[str, Any]:
        info = self._marker_info(point)
        texture = self._texture_at([point.position])
        if texture:
            info["texture"] = next(iter(texture))
        near: list[tuple[float, dict[str, Any]]] = []
        for index, obj in enumerate(self._objects()):
            x, y, _ = obj.position
            distance = math.dist((x, y), point.position)
            if distance <= _POINT_NEARBY:
                brief = _brief(obj, index)
                brief["distance"] = round(distance, 1)
                near.append((distance, brief))
        near.sort(key=lambda item: item[0])
        info["nearby_objects"] = [brief for _, brief in near[:_REGION_OBJECTS]]
        info["nearby_radius"] = _POINT_NEARBY
        return info

    def _describe_path(self, path: PathMarker) -> dict[str, Any]:
        info = self._marker_info(path)
        points = self._doc.markers.path_points(path)
        info["segments"] = [
            round(math.dist(a, b), 1) for a, b in zip(points, points[1:], strict=False)
        ]
        samples = _along(points, WORLD_UNITS_PER_CELL)
        heights = [self._height_at(x, y) for x, y in samples]
        known = [(s, h) for s, h in zip(samples, heights, strict=True) if h is not None]
        if known:
            values = [h for _, h in known]
            ground: dict[str, Any] = {
                "start_height": values[0],
                "end_height": values[-1],
                "min_height": min(values),
                "max_height": max(values),
            }
            grades = [
                math.degrees(math.atan2(abs(h1 - h0), math.dist(p0, p1)))
                for (p0, h0), (p1, h1) in zip(known, known[1:], strict=False)
                if math.dist(p0, p1) > 0
            ]
            if grades:
                ground["steepest_grade_degrees"] = round(max(grades), 1)
            info["ground"] = ground
        textures = self._texture_at(samples)
        if textures:
            info["textures"] = textures
        return info

    def _texture_at(self, positions: list[tuple[float, float]]) -> dict[str, float]:
        """The share of each texture under some world positions."""
        doc = self._doc
        grid, blend = doc.terrain, doc.map.blend_tile_data
        if grid is None or blend is None:
            return {}
        classes = tile_classes(blend)
        if classes.shape != grid.heights.shape:
            return {}
        cells = [grid.nearest_cell(x, y) for x, y in positions]
        under = np.array([classes[row, column] for column, row in filter(None, cells)])
        return _texture_shares(blend, under) if under.size else {}

    def _xy(self, value: Any, what: str = "a position") -> tuple[float, float]:
        try:
            x, y = value
            return float(x), float(y)
        except (TypeError, ValueError):
            raise ToolError(f"{what} is [x, y] in world units, not {value!r}") from None

    def mark_area(
        self,
        points: list[list[float]] | None = None,
        x0: float | None = None,
        y0: float | None = None,
        x1: float | None = None,
        y1: float | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Mark an area for the user to see: a polygon through `points` ([x, y] corners, at
        least three) or the rectangle x0, y0, x1, y1; under `name` (replacing an area of that
        name) or the next free letter."""
        markers = self._doc.markers
        with self._marking():
            if points is not None:
                area = markers.mark_area([self._xy(point) for point in points], name)
            elif x0 is None or y0 is None or x1 is None or y1 is None:
                raise ToolError("give an area's corners as points, or a rectangle as x0..y1")
            elif x0 == x1 or y0 == y1:
                raise ToolError("an area needs a width and a height")
            else:
                area = markers.mark_rectangle(x0, y0, x1, y1, name)
        return _area_info(area)

    def mark_point(self, x: float, y: float, name: str | None = None) -> dict[str, Any]:
        """Mark a point for the user to see, under `name` (moving a point of that name) or the
        next free P name."""
        with self._marking():
            point = self._doc.markers.mark_point(x, y, name)
        return self._marker_info(point)

    def _with_stops(self, stops: list[Any], make: Any) -> Marker:
        """Run `make` on a path's stop names, after marking a point for each stop given as a
        position; those points go again when `make` fails."""
        markers = self._doc.markers
        names: list[str | tuple[float, float]] = []
        for stop in stops:
            if isinstance(stop, str):
                point = markers.get(stop)
                if not isinstance(point, PointMarker):
                    raise ToolError(f"{stop.strip().upper()} is not a marked point")
                names.append(point.name)
            else:
                names.append(self._xy(stop, "a path stop"))
        created: list[str] = []
        try:
            with self._marking():
                resolved = []
                for stop in names:
                    if isinstance(stop, tuple):
                        stop = markers.mark_point(*stop).name
                        created.append(stop)
                    resolved.append(stop)
                return make(resolved)
        except ToolError:
            for name in created:
                markers.remove(name)
            raise

    def mark_path(self, stops: list[Any], name: str | None = None) -> dict[str, Any]:
        """Mark a path for the user to see, through `stops` in order: each a point's name or an
        [x, y] position, which marks a new point there. Under `name` (replacing a path of that
        name) or the next free L name."""
        markers = self._doc.markers
        path = self._with_stops(stops, lambda names: markers.mark_path(names, name))
        return self._marker_info(path)

    def edit_marker(
        self,
        name: str,
        new_name: str | None = None,
        points: list[Any] | None = None,
        x: float | None = None,
        y: float | None = None,
        offset: list[float] | None = None,
    ) -> dict[str, Any]:
        """Change a marker in place: `offset` [dx, dy] moves any marker (a path takes its
        points along); `points` gives an area new corners or a path new stops (names or
        [x, y]); `x`, `y` move a point (and so its paths); `new_name` renames it."""
        marker = self._marker(name)
        markers = self._doc.markers
        if new_name is None and points is None and x is None and y is None and offset is None:
            raise ToolError("nothing to change: give new_name, points, x and y, or offset")
        if (x is None) != (y is None):
            raise ToolError("move a point with both x and y")
        if x is not None and not isinstance(marker, PointMarker):
            raise ToolError("x and y move a point; move an area or a path with offset or points")
        if points is not None and isinstance(marker, PointMarker):
            raise ToolError("a point has no corners or stops: move it with x and y")
        with self._marking():
            if offset is not None:
                markers.move(marker.name, *self._xy(offset, "offset"))
            if points is not None and isinstance(marker, AreaMarker):
                markers.set_corners(marker.name, [self._xy(point) for point in points])
            elif points is not None:
                self._with_stops(points, lambda names: markers.set_stops(marker.name, names))
            if x is not None and y is not None:
                markers.set_position(marker.name, x, y)
            if new_name is not None:
                marker = markers.rename(marker.name, new_name)
        return self._marker_info(self._marker(marker.name))

    def delete_markers(
        self, names: list[str] | None = None, kind: str | None = None
    ) -> dict[str, Any]:
        """Remove the named markers, or every marker (of one `kind`). A removed point leaves the
        paths through it, and a path left with one point goes too."""
        markers = self._doc.markers
        if names is None:
            return {"deleted": markers.clear(self._kind(kind))}
        missing = [name for name in names if markers.get(name) is None]
        if missing:
            raise ToolError(f"no marker {', '.join(missing)}")
        before = len(markers)
        for name in names:
            markers.remove(name)
        return {"deleted": before - len(markers)}

    # Textures and blends. The game's terrain textures come from its game data, which only the
    # editor loads; headless, only the textures already on the map can be painted.

    def _game_textures(self) -> dict[str, str] | None:
        """The game's terrain textures, name -> group ("type/region"); None without game data."""
        return None

    def _texture_cell_size(self, name: str) -> int | None:
        """A game texture's size in texture cells; None when unknown."""
        return None

    def _blend(self) -> BlendTileData:
        blend = self._doc.map.blend_tile_data
        if blend is None or self._doc.cells(TileLayer.TILES) is None:
            raise ToolError("the map has no texture tiles")
        return blend

    def _layers(self) -> dict[TileLayer, np.ndarray]:
        return {layer: self._doc.cells(layer) for layer in TileLayer}  # type: ignore[misc]

    def _texture(self, name: str) -> tuple[BlendTileTexture, BlendTileTexture | None]:
        """The table entry to paint `name` with, and the same entry again when the map does not
        have it yet (painting adds it)."""
        blend = self._blend()
        index = texture_index(blend, name)
        if index is not None:
            return blend.textures[index], None
        game = self._game_textures()
        if game is None:
            on_map = ", ".join(texture.name for texture in blend.textures)
            raise ToolError(
                f"{name!r} is not on the map, and without the editor's game data only the "
                f"map's own textures can be painted: {on_map}"
            )
        spelled = {known.lower(): known for known in game}.get(name.lower())
        if spelled is None:
            raise ToolError(f"the game has no terrain texture {name!r}; see list_textures")
        try:
            size = self._texture_cell_size(spelled) or DEFAULT_CELL_SIZE
            planned = planned_texture(blend, spelled, size)
        except TextureCapacityError as error:
            raise ToolError(str(error)) from error
        return planned, planned

    def _cell_block(self, bounds: Bounds) -> tuple[int, int, int, int]:
        """The texture cells (`x0, y0, x1, y1`, half-open) under a world rectangle."""
        column0, row0, column1, row1 = self._sample_rect(*bounds)
        rows, columns = self._layers()[TileLayer.TILES].shape
        return column0, row0, min(column1 + 1, columns), min(row1 + 1, rows)

    def _cell_at(self, x: float, y: float) -> tuple[int, int]:
        grid = self._doc.terrain
        cell = grid.nearest_cell(x, y) if grid is not None else None
        if cell is None:
            raise ToolError(f"({x}, {y}) is off the map")
        return cell

    def _execute_blend(self, edit: BlendEdit | None, label: str) -> bool:
        if edit is None:
            return False
        command = PaintBlends(edit.x0, edit.y0, edit.layers, edit.descriptions, label, edit.texture)
        command.closed = True
        self._doc.execute(command)
        return True

    def list_textures(
        self, name_filter: str = "", include_game: bool = False, limit: int = 100
    ) -> dict[str, Any]:
        """The textures on the map with the share of cells each covers; with `include_game`, the
        game's terrain textures too (connected to the editor with game data loaded)."""
        blend = self._blend()
        needle = name_filter.lower()
        classes = texture_classes(self._layers()[TileLayer.TILES], blend.textures)
        counts = np.bincount(classes[classes >= 0].ravel(), minlength=len(blend.textures))
        total = max(int(counts.sum()), 1)
        result: dict[str, Any] = {
            "on_map": [
                {
                    "name": texture.name,
                    "share": round(int(counts[index]) / total, 3),
                    "cell_size": texture.cell_size,
                }
                for index, texture in enumerate(blend.textures)
                if needle in texture.name.lower()
            ]
        }
        if include_game:
            game = self._game_textures()
            if game is None:
                result["game"] = None
                result["note"] = "no game data: only the map's own textures can be painted"
            else:
                matches = [
                    {"name": name, "group": group}
                    for name, group in sorted(game.items(), key=lambda item: item[0].lower())
                    if needle in name.lower() or needle in group.lower()
                ]
                limit = max(1, min(limit, MAX_PAGE))
                result["game"] = matches[:limit]
                result["game_total"] = len(matches)
        return result

    def paint_texture(
        self,
        texture: str,
        x0: float | None = None,
        y0: float | None = None,
        x1: float | None = None,
        y1: float | None = None,
        region: str | None = None,
        only_over: str | None = None,
    ) -> dict[str, Any]:
        """Paint a texture over a rectangle or a marked area, only over the cells showing
        `only_over` when given. Painting clears the blends there, as the brushes do."""
        self._blend()
        block = self._cell_block(self._bounds(x0, y0, x1, y1, region))
        area = self._region(region) if region is not None else None
        return self._paint(texture, block, self._area_mask(area, block), only_over, "Paint Texture")

    def _paint(
        self,
        texture: str,
        block: tuple[int, int, int, int],
        mask: np.ndarray | None,
        only_over: str | None,
        label: str,
    ) -> dict[str, Any]:
        """Paint the cells of a block (where `mask` is True, when given) as one undo entry."""
        blend = self._blend()
        entry, new = self._texture(texture)
        layers = self._layers()
        tiles = layers[TileLayer.TILES]
        bx0, by0, bx1, by1 = block
        if only_over is not None:
            under = texture_index(blend, only_over)
            if under is None:
                raise ToolError(f"{only_over!r} is not on the map")
            over = texture_classes(tiles[by0:by1, bx0:bx1], blend.textures) == under
            mask = over if mask is None else mask & over
        offset = (0, 0) if new is not None else tiling_offset(tiles, entry)
        painted = paint_texture_block(layers, block, entry, mask, offset)
        cells = int(mask.sum()) if mask is not None else (bx1 - bx0) * (by1 - by0)
        if painted is None:
            return {"texture": entry.name, "cells": 0, "added_to_map": False}
        command = PaintTiles(bx0, by0, painted, new, label)
        command.closed = True
        with self._edit(label):
            self._doc.execute(command)
        return {"texture": entry.name, "cells": cells, "added_to_map": new is not None}

    def paint_texture_by_terrain(
        self,
        texture: str,
        min_slope: int = 0,
        max_slope: int = 89,
        min_height: int | None = None,
        max_height: int | None = None,
        coverage: int = 100,
        region: str | None = None,
        bounds: Bounds | None = None,
    ) -> dict[str, Any]:
        """Apply To Tiles: paint a texture on the playable cells whose corners lie between two
        slopes (degrees) and two heights (feet), each at a `coverage` percent chance; over the
        whole map, or only a marked `region` or `bounds`."""
        blend = self._blend()
        grid = self._doc.terrain
        height_map = self._doc.map.height_map_data
        if grid is None or height_map is None:
            raise ToolError("the map has no heightmap")
        block = None
        area = self._region(region) if region is not None else None
        if area is not None:
            block = self._cell_block(area.bounds)
        elif bounds is not None:
            block = self._cell_block(bounds)
        entry, new = self._texture(texture)
        options = ApplyTextureOptions(
            use_slopes=True,
            slopes=(min_slope, max_slope),
            use_heights=min_height is not None or max_height is not None,
            heights=(min_height or 0, max_height if max_height is not None else 255),
            use_saturation=True,
            saturation=max(0, min(coverage, 100)),
        )
        painted = apply_texture(
            self._layers(),
            grid.heights,
            blend.textures,
            entry,
            height_map.border_width,
            options,
            block=block,
        )
        if painted is None:
            return {"texture": entry.name, "cells": 0, "added_to_map": False}
        px, py, layers = painted
        if area is not None and not area.is_rectangle:
            layers = self._masked_layers(px, py, layers, area)
            if not layers:
                return {"texture": entry.name, "cells": 0, "added_to_map": False}
        tiles = layers.get(TileLayer.TILES)
        cells = 0
        if tiles is not None:
            rows, columns = tiles.shape
            old = self._layers()[TileLayer.TILES][py : py + rows, px : px + columns]
            cells = int(np.count_nonzero(tiles != old))
        command = PaintTiles(px, py, layers, new, "Apply Texture to Tiles")
        command.closed = True
        with self._edit("Apply Texture to Tiles"):
            self._doc.execute(command)
        return {"texture": entry.name, "cells": cells, "added_to_map": new is not None}

    def _masked_layers(
        self, px: int, py: int, layers: dict[TileLayer, np.ndarray], area: AreaMarker
    ) -> dict[TileLayer, np.ndarray]:
        """Painted layers put back as they were outside an area's polygon; the unchanged ones
        left out."""
        current = self._layers()
        kept: dict[TileLayer, np.ndarray] = {}
        for layer, values in layers.items():
            rows, columns = values.shape
            mask = polygon_contains(
                area.points, *self._cell_positions((px, py, px + columns, py + rows))
            )
            old = current[layer][py : py + rows, px : px + columns]
            new = np.where(mask, values, old).astype(values.dtype)
            if not np.array_equal(new, old):
                kept[layer] = new
        return kept

    def flood_fill_texture(
        self, texture: str, x: float, y: float, replace_all: bool = False
    ) -> dict[str, Any]:
        """Flood Fill: paint a texture over the area of the texture at x, y joined to it, or with
        `replace_all` every cell of that texture on the map. Blends are kept."""
        blend = self._blend()
        cell = self._cell_at(x, y)
        entry, new = self._texture(texture)
        layers = self._layers()
        column, row = cell
        under = int(
            texture_classes(
                layers[TileLayer.TILES][row : row + 1, column : column + 1], blend.textures
            )[0, 0]
        )
        with self._edit("Flood Fill"):
            if (
                replace_all
                and new is not None
                and under >= 0
                and blend.textures[under].cell_size == new.cell_size
            ):
                # A texture the map lacks takes over the replaced one's table entry when it is
                # the same size, so every cell and blend keeps its tile, as the editor does.
                old = blend.textures[under].name
                self._doc.execute(RenameTexture(under, new.name))
                return {"texture": new.name, "replaced": old}
            edit = flood_fill(
                layers,
                blend.textures,
                blend.blend_descriptions,
                cell,
                entry,
                replace_all=replace_all,
            )
            changed = self._execute_blend(edit, "Flood Fill")
        return {"texture": entry.name, "changed": changed}

    def auto_blend(
        self, x: float, y: float, outward: bool = True, whole_map: bool = False
    ) -> dict[str, Any]:
        """Auto Edge: blend the edge of the texture area at x, y, onto its neighbours (`outward`,
        Auto Edge Out) or the neighbours onto it (Auto Edge In); `whole_map` edges every area of
        that texture."""
        blend = self._blend()
        cell = self._cell_at(x, y)
        routine = auto_edge_out if outward else auto_edge_in
        label = "Auto Edge Out" if outward else "Auto Edge In"
        with self._edit(label):
            edit = routine(
                self._layers(),
                blend.textures,
                blend.blend_descriptions,
                cell,
                whole_map=whole_map,
            )
            changed = self._execute_blend(edit, label)
        return {"changed": changed}

    def blend_region(
        self,
        region: str | None = None,
        x0: float | None = None,
        y0: float | None = None,
        x1: float | None = None,
        y1: float | None = None,
        outward: bool = True,
    ) -> dict[str, Any]:
        """Auto Edge every unblended texture area in a rectangle or a marked area, the largest
        first, as one undo entry. A texture area reaching out of it is edged whole."""
        self._blend()
        block = self._cell_block(self._bounds(x0, y0, x1, y1, region))
        area = self._region(region) if region is not None else None
        with self._edit("Blend Region"):
            return self._blend_block(block, self._area_mask(area, block), outward)

    def _blend_block(
        self, block: tuple[int, int, int, int], mask: np.ndarray | None, outward: bool
    ) -> dict[str, Any]:
        """Auto Edge each unblended texture area among a block's cells (those in `mask`)."""
        blend = self._blend()
        bx0, by0, bx1, by1 = block
        layers = self._layers()
        classes = texture_classes(layers[TileLayer.TILES][by0:by1, bx0:bx1], blend.textures)
        blends = layers[TileLayer.BLENDS]
        open_cells = classes >= 0
        if blends is not None:
            open_cells &= blends[by0:by1, bx0:bx1] == 0
        if mask is not None:
            open_cells &= mask
        areas = _areas_in(classes, open_cells)
        routine = auto_edge_out if outward else auto_edge_in
        label = "Auto Edge Out" if outward else "Auto Edge In"
        edged = 0
        for _, column, row in areas[:MAX_BLEND_AREAS]:
            edit = routine(
                self._layers(),
                blend.textures,
                blend.blend_descriptions,
                (bx0 + column, by0 + row),
            )
            edged += self._execute_blend(edit, label)
        return {
            "areas": len(areas),
            "edged": edged,
            "skipped": max(0, len(areas) - MAX_BLEND_AREAS),
        }

    def paint_path(
        self,
        texture: str,
        path: str,
        width: float = 40.0,
        blend: bool = True,
        only_over: str | None = None,
        outward: bool = True,
    ) -> dict[str, Any]:
        """Paint a texture in a band `width` world units wide along a marked path (only over the
        cells showing `only_over` when given), then, with `blend`, Auto Edge the band so it
        fades into the ground beside it. One undo entry."""
        marker, points = self._path(path)
        if len(points) < 2:
            raise ToolError(f"{marker.name} runs through fewer than two points")
        if width <= 0:
            raise ToolError("width must be more than 0")
        self._blend()
        # Never thinner than a cell and a half, or a diagonal band breaks into separate cells.
        half = max(width / 2, WORLD_UNITS_PER_CELL * 0.75)
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        block = self._cell_block((min(xs) - half, min(ys) - half, max(xs) + half, max(ys) + half))
        band = distance_to_polyline(points, *self._cell_positions(block)) <= half
        with self._edit("Paint Path"):
            result = self._paint(texture, block, band, only_over, "Paint Texture")
            if blend and result["cells"]:
                edges = self._blend_block(block, band, outward)
                result["blended_areas"] = edges["edged"]
        result["path"] = marker.name
        result["width"] = round(half * 2, 1)
        result["length"] = round(path_length(points), 1)
        return result

    def undo(self) -> dict[str, Any]:
        label = self._doc.stack.undo_label
        if not self._doc.stack.undo():
            raise ToolError("nothing to undo")
        return {"undid": label}

    def redo(self) -> dict[str, Any]:
        label = self._doc.stack.redo_label
        if not self._doc.stack.redo():
            raise ToolError("nothing to redo")
        return {"redid": label}
