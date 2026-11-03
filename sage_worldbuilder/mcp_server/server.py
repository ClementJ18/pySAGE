"""The MCP server: the session's tools over stdio.

Each tool is a thin wrapper over a session - a `WorldBuilderSession` editing a map headlessly, or a
`BridgeSession` forwarding to the running editor. A `ToolError` reaches the agent as the tool's
error message.
"""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError as McpToolError

from sage_worldbuilder.mcp_server.tools import ToolError, WorldBuilderSession

if TYPE_CHECKING:
    from sage_worldbuilder.mcp_server.bridge import BridgeSession

__all__ = ["build_server"]

# The marker prompt pictures at most this many markers: each one may move the editor's view.
_PROMPT_SCREENSHOTS = 4

INSTRUCTIONS = """\
Edits SAGE (Battle for Middle-earth) .map files. Call map_info first (open_map if no map is
open) for the units and the playable extent. Positions are world units (10 per heightmap cell),
heights are feet, angles are degrees. Objects are addressed by the id list_objects returns. Every
edit is one undo entry; nothing is written to disk until save_map. Connected to the editor, the
user sees each edit as it happens, and screenshot shows what the view shows.

The user points at places with markers drawn in the editor's Markers panel: areas (rectangles
or polygons) named A, B, C, ..., points P1, P2, ... and paths through points L1, L2, ... (they
may rename them). When they say "here", "this area", "the marked area", "the path" or name a
marker, call get_markers (and describe_marker) instead of guessing coordinates. Pass an area's
name as `region` to the tools that take a rectangle; paint_path paints along a path. To check
you mean the same place, or to propose one, mark_area / mark_point / mark_path show it to the
user, and edit_marker changes a marker in place.

Texturing: list_textures names what can be painted (the game's textures only when connected to
the editor with game data). Painting (paint_texture, paint_texture_by_terrain) leaves hard
edges; follow it with blend_region over the same place to blend them, as a mapper would.
paint_path blends its band itself unless told not to."""


def build_server(session: WorldBuilderSession | BridgeSession | None = None) -> MCPServer:
    session = session or WorldBuilderSession()
    server = MCPServer("sage-worldbuilder", instructions=INSTRUCTIONS)

    def call(method: str, *args: Any, **kwargs: Any) -> Any:
        try:
            return getattr(session, method)(*args, **kwargs)
        except ToolError as error:
            raise McpToolError(str(error)) from error

    @server.tool()
    def open_map(path: str) -> dict[str, Any]:
        """Open a .map file from disk, replacing any map already open (unsaved edits are lost)."""
        return call("open_map", path)

    @server.tool()
    def save_map(path: str | None = None) -> dict[str, Any]:
        """Save the open map, to where it came from or to `path`."""
        return call("save_map", path)

    @server.tool()
    def map_info() -> dict[str, Any]:
        """The open map's summary, units, playable extent and undo/redo state."""
        return call("map_info")

    @server.tool()
    def list_objects(
        name_filter: str = "",
        bounds: list[float] | None = None,
        include_waypoints: bool = False,
        offset: int = 0,
        limit: int = 50,
        region: str | None = None,
    ) -> dict[str, Any]:
        """Placed objects whose template name contains `name_filter`, optionally only those inside
        `bounds` [x0, y0, x1, y1] (world units) or a marked area (`region`). Paged: at most 200 per
        call."""
        rect = tuple(bounds) if bounds is not None else None
        if rect is not None and len(rect) != 4:
            raise McpToolError("bounds is [x0, y0, x1, y1]")
        return call("list_objects", name_filter, rect, include_waypoints, offset, limit, region)

    @server.tool()
    def get_object(object_id: str) -> dict[str, Any]:
        """One placed object with all of its properties."""
        return call("get_object", object_id)

    @server.tool()
    def list_teams() -> list[str]:
        """The owner names place_object accepts; "/team" is the neutral owner."""
        return call("list_teams")

    @server.tool()
    def place_object(
        template: str,
        x: float,
        y: float,
        angle: float = 0.0,
        owner: str = "/team",
        layer: str = "",
    ) -> dict[str, Any]:
        """Place a new object of `template` (an INI Object name) at x, y on the ground."""
        return call("place_object", template, x, y, angle, owner, layer)

    @server.tool()
    def move_object(object_id: str, x: float, y: float, z: float | None = None) -> dict[str, Any]:
        """Move an object to x, y; `z`, when given, is its height above the ground."""
        return call("move_object", object_id, x, y, z)

    @server.tool()
    def rotate_object(object_id: str, angle: float) -> dict[str, Any]:
        """Set an object's facing, in degrees."""
        return call("rotate_object", object_id, angle)

    @server.tool()
    def delete_objects(object_ids: list[str]) -> dict[str, Any]:
        """Delete placed objects (one undo entry)."""
        return call("delete_objects", object_ids)

    @server.tool()
    def set_object_property(
        object_id: str, name: str, value: str | int | float | bool | None
    ) -> dict[str, Any]:
        """Set one object property (keeping its stored type when it exists); null removes it."""
        return call("set_object_property", object_id, name, value)

    @server.tool()
    def sample_heights(
        x0: float | None = None,
        y0: float | None = None,
        x1: float | None = None,
        y1: float | None = None,
        step: float = 10.0,
        region: str | None = None,
    ) -> dict[str, Any]:
        """Ground heights in feet over a rectangle (x0, y0, x1, y1) or a marked area's bounding
        box (`region`), rows
        from the bottom upward. The step grows past the one asked for when there would be more
        than 4096 samples."""
        return call("sample_heights", x0, y0, x1, y1, step, region)

    @server.tool()
    def set_terrain_height(
        height: float,
        x0: float | None = None,
        y0: float | None = None,
        x1: float | None = None,
        y1: float | None = None,
        region: str | None = None,
    ) -> dict[str, Any]:
        """Flatten a rectangle of terrain (x0, y0, x1, y1, world units) or a marked area
        (`region`, rectangle or polygon) to
        `height` feet."""
        return call("set_terrain_height", x0, y0, x1, y1, height, region)

    @server.tool()
    def undo() -> dict[str, Any]:
        """Undo the last edit."""
        return call("undo")

    @server.tool()
    def redo() -> dict[str, Any]:
        """Redo the last undone edit."""
        return call("redo")

    @server.tool()
    def get_selection() -> list[dict[str, Any]]:
        """The selected objects; connected to the editor, what the user has selected there."""
        return call("get_selection")

    @server.tool()
    def select_objects(object_ids: list[str]) -> list[dict[str, Any]]:
        """Replace the selection with these objects; an empty list clears it."""
        return call("select_objects", object_ids)

    @server.tool()
    def view_at(x: float, y: float, zoom: float = 1.0) -> dict[str, Any]:
        """Centre the editor's view on x, y, zoomed to at least `zoom` pixels per world unit.
        Needs the editor (--bridge)."""
        return call("view_at", x, y, zoom)

    @server.tool()
    def screenshot(max_width: int = 1280, marker: str | None = None) -> Image:
        """What the editor's view shows now, top-down or 3D; with `marker`, only the ground
        round that marker (the view moves to it when it is not all on screen). Needs the editor
        (--bridge)."""
        return image(call("screenshot", max_width, marker))

    @server.tool()
    def get_markers(kind: str | None = None) -> list[dict[str, Any]]:
        """The markers in the editor (Markers panel), in the order made: areas (name, corner
        `points`, `bounds` [x0, y0, x1, y1], size, whether a rectangle), points (x, y, ground
        height, the paths through them) and paths (`stops` by point name, their positions,
        length), in world units. `kind` (area, point or path) lists only that kind."""
        return call("get_markers", kind)

    @server.tool()
    def describe_marker(name: str) -> dict[str, Any]:
        """What a marker covers. An area: objects by template, waypoints, trigger areas, terrain
        heights and slope, textures. A point: its height, texture and the objects near it. A
        path: its segments, the ground's heights and steepest grade along it, and the textures
        it crosses."""
        return call("describe_marker", name)

    @server.tool()
    def mark_area(
        points: list[list[float]] | None = None,
        x0: float | None = None,
        y0: float | None = None,
        x1: float | None = None,
        y1: float | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Show an area to the user: a polygon through `points` ([[x, y], ...], three or more
        corners) or the rectangle x0, y0, x1, y1 (world units); as `name` or the next free
        letter, replacing an area of that name. Not saved with the map."""
        return call("mark_area", points, x0, y0, x1, y1, name)

    @server.tool()
    def mark_point(x: float, y: float, name: str | None = None) -> dict[str, Any]:
        """Show a point to the user at x, y (world units), as `name` or the next free P name; a
        point of that name moves there, and the paths through it follow. Not saved with the
        map."""
        return call("mark_point", x, y, name)

    @server.tool()
    def mark_path(stops: list[str | list[float]], name: str | None = None) -> dict[str, Any]:
        """Show a path to the user through `stops` in order, each a marked point's name or an
        [x, y] position (which marks a new point there); as `name` or the next free L name,
        replacing a path of that name. Not saved with the map."""
        return call("mark_path", stops, name)

    @server.tool()
    def edit_marker(
        name: str,
        new_name: str | None = None,
        points: list[str | list[float]] | None = None,
        x: float | None = None,
        y: float | None = None,
        offset: list[float] | None = None,
    ) -> dict[str, Any]:
        """Change a marker in place. `offset` [dx, dy] moves any marker (a path takes its points
        along); `points` gives an area new corners ([[x, y], ...]) or a path new stops (point
        names or [x, y]); `x` and `y` move a point, reshaping its paths; `new_name` renames it
        (paths follow a renamed point)."""
        return call("edit_marker", name, new_name, points, x, y, offset)

    @server.tool()
    def delete_markers(names: list[str] | None = None, kind: str | None = None) -> dict[str, Any]:
        """Remove the named markers, or all of them (or all of one `kind`: area, point, path).
        A removed point drops out of its paths; a path left with one point goes too."""
        return call("delete_markers", names, kind)

    @server.tool()
    def list_textures(
        name_filter: str = "", include_game: bool = False, limit: int = 100
    ) -> dict[str, Any]:
        """The terrain textures on the map, with the share of cells each covers; with
        `include_game`, also the game's terrain textures that can be painted (needs the editor
        with game data loaded), filtered by name or group."""
        return call("list_textures", name_filter, include_game, limit)

    @server.tool()
    def paint_texture(
        texture: str,
        x0: float | None = None,
        y0: float | None = None,
        x1: float | None = None,
        y1: float | None = None,
        region: str | None = None,
        only_over: str | None = None,
    ) -> dict[str, Any]:
        """Paint a terrain texture over a rectangle (x0, y0, x1, y1) or a marked area (`region`,
        rectangle or polygon), only
        over the cells showing the texture `only_over` when given. Clears the blends there: run
        blend_region afterwards to soften the edges."""
        return call("paint_texture", texture, x0, y0, x1, y1, region, only_over)

    @server.tool()
    def paint_texture_by_terrain(
        texture: str,
        min_slope: int = 0,
        max_slope: int = 89,
        min_height: int | None = None,
        max_height: int | None = None,
        coverage: int = 100,
        region: str | None = None,
        bounds: list[float] | None = None,
    ) -> dict[str, Any]:
        """Apply To Tiles: paint a texture where the ground's slope (degrees) and height (feet)
        are within limits, on each such cell at a `coverage` percent chance (below 100 scatters
        it). Over the whole playable map, or only a marked area (`region`) or `bounds`
        [x0, y0, x1, y1]."""
        rect = tuple(bounds) if bounds is not None else None
        if rect is not None and len(rect) != 4:
            raise McpToolError("bounds is [x0, y0, x1, y1]")
        return call(
            "paint_texture_by_terrain",
            texture,
            min_slope,
            max_slope,
            min_height,
            max_height,
            coverage,
            region,
            rect,
        )

    @server.tool()
    def flood_fill_texture(
        texture: str, x: float, y: float, replace_all: bool = False
    ) -> dict[str, Any]:
        """Flood Fill: paint a texture over the area of the texture at x, y that joins it, or
        with `replace_all` over every cell of that texture on the map. Keeps the blends."""
        return call("flood_fill_texture", texture, x, y, replace_all)

    @server.tool()
    def auto_blend(
        x: float, y: float, outward: bool = True, whole_map: bool = False
    ) -> dict[str, Any]:
        """Auto Edge the texture area at x, y: blend it onto its neighbours (`outward`, Auto
        Edge Out) or them onto it (Auto Edge In); `whole_map` does every area of that
        texture."""
        return call("auto_blend", x, y, outward, whole_map)

    @server.tool()
    def blend_region(
        region: str | None = None,
        x0: float | None = None,
        y0: float | None = None,
        x1: float | None = None,
        y1: float | None = None,
        outward: bool = True,
    ) -> dict[str, Any]:
        """Soften texture edges: Auto Edge every unblended texture area in a marked area
        (`region`) or a rectangle, largest first (at most 100), as one undo entry."""
        return call("blend_region", region, x0, y0, x1, y1, outward)

    @server.tool()
    def paint_path(
        texture: str,
        path: str,
        width: float = 40.0,
        blend: bool = True,
        only_over: str | None = None,
        outward: bool = True,
    ) -> dict[str, Any]:
        """Paint a terrain texture in a band `width` world units wide along a marked path (a
        road, a trail, a river bank), only over the texture `only_over` when given. With `blend`
        (the default) the band's edges are Auto Edged so it fades into the ground beside it
        (`outward`: the band over its neighbours; false: them over it). One undo entry."""
        return call("paint_path", texture, path, width, blend, only_over, outward)

    @server.resource(
        "markers://all",
        name="markers",
        title="Markers",
        description="The areas, points and paths marked in the editor, with what each covers.",
        mime_type="application/json",
    )
    def markers() -> str:
        return json.dumps(describe_all(), indent=1)

    @server.resource(
        "marker://{name}",
        name="marker",
        title="Marker",
        description="One marked area, point or path, with what it covers.",
        mime_type="application/json",
    )
    def marker(name: str) -> str:
        return json.dumps(call("describe_marker", name), indent=1)

    @server.prompt(
        name="marker",
        title="Attach marker",
        description="Attach a marker (or every one) with a picture of it, as the place the "
        "request is about.",
    )
    def marker_prompt(name: str = "") -> list[Any]:
        if name:
            described = [call("describe_marker", name)]
        else:
            described = describe_all()
        if not described:
            return [
                "I meant to point at a place on the map, but nothing is marked yet. Ask me to "
                "mark it in the editor's Markers panel."
            ]
        names = ", ".join(entry["name"] for entry in described)
        content: list[Any] = [
            f"Marker {names} is the place my next request is about. What it covers:\n"
            + json.dumps(described, indent=1)
        ]
        for entry in described[:_PROMPT_SCREENSHOTS]:
            try:
                content.append(image(session.screenshot(1024, entry["name"])))
            except ToolError:
                break  # headless: there is no view to show
        return content

    def describe_all() -> list[dict[str, Any]]:
        return [call("describe_marker", entry["name"]) for entry in call("get_markers")]

    return server


def image(shot: dict[str, Any]) -> Image:
    return Image(data=base64.b64decode(shot["data"]), format=shot["format"])
