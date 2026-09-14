"""The open map: a `sage_map.Map` with its file identity, undo stack and change notifications.

Every edit goes through `MapDocument.execute`, so it is undoable and every view hears about it.
The module is Qt-free; a view subscribes with a plain callback.
"""

from __future__ import annotations

import io
import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from sage_map.map import Map, parse_map, write_map
from sage_worldbuilder.changes import Change, ChangeKind
from sage_worldbuilder.commands import Command, UndoStack
from sage_worldbuilder.safeio import atomic_write
from sage_worldbuilder.selection import Selection

if TYPE_CHECKING:
    import numpy as np

    from sage_worldbuilder.terrain import TerrainGrid
    from sage_worldbuilder.terrain.cells import Layer

__all__ = ["MapDocument", "ReadOnlyMapError"]

_TERRAIN_CHANGES = (ChangeKind.TERRAIN, ChangeKind.WHOLE)
# The changes that can take a selected object or area off the map.
_SELECTABLE_CHANGES = (ChangeKind.OBJECTS, ChangeKind.WAYPOINTS, ChangeKind.AREAS, ChangeKind.WHOLE)
# The changes a base's castle templates are made from.
_CASTLE_CHANGES = (ChangeKind.OBJECTS, ChangeKind.AREAS, ChangeKind.WHOLE)

UNTITLED = "Untitled"


class ReadOnlyMapError(PermissionError):
    """The target cannot be written: a read-only file, or a map read out of an archive."""


class MapDocument:
    def __init__(
        self,
        map: Map,
        path: str | Path | None = None,
        *,
        read_only: bool = False,
        name: str | None = None,
        undo_limit: int = UndoStack.DEFAULT_LIMIT,
    ) -> None:
        self.map = map
        self.path = Path(path) if path is not None else None
        self.read_only = read_only
        # The title for a map with no file of its own, such as one read out of an archive.
        self.name = name
        # Save re-compresses exactly when the source was compressed, unless told otherwise.
        self.compressed = map.compressed
        # Bumped on every notification, so anything caching a view of the map can tell it is stale.
        self.revision = 0
        self._listeners: list[Callable[[Change], None]] = []
        self._castle_edited = False
        self._terrain: TerrainGrid | None = None
        self._cells: dict[Layer, np.ndarray | None] = {}
        self.selection = Selection()
        self.stack = UndoStack(self, limit=undo_limit)

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        path: str | Path | None = None,
        *,
        read_only: bool = False,
        name: str | None = None,
    ) -> MapDocument:
        return cls(parse_map(io.BytesIO(data)), path, read_only=read_only, name=name)

    @classmethod
    def open(cls, path: str | Path) -> MapDocument:
        path = Path(path)
        return cls.from_bytes(path.read_bytes(), path, read_only=not os.access(path, os.W_OK))

    @property
    def title(self) -> str:
        if self.path is not None:
            return self.path.stem
        return self.name or UNTITLED

    @property
    def dirty(self) -> bool:
        return not self.stack.is_clean

    @property
    def castle_templates_stale(self) -> bool:
        """Whether saving this map as a base must rebuild its castle templates: it has none, or
        its objects or trigger areas changed since it was loaded or last saved."""
        return self._castle_edited or self.map.castle_templates is None

    def subscribe(self, listener: Callable[[Change], None]) -> Callable[[], None]:
        """Call `listener` with every change; returns the function that unsubscribes it."""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    @property
    def terrain(self) -> TerrainGrid | None:
        """The heightmap as an array, built on first use and again after a terrain change.
        None for a map without a heightmap."""
        if self._terrain is None and self.map.height_map_data is not None:
            from sage_worldbuilder.terrain import TerrainGrid  # noqa: PLC0415 - lazy: numpy

            self._terrain = TerrainGrid.from_height_map(self.map.height_map_data)
        return self._terrain

    def cells(self, layer: Layer) -> np.ndarray | None:
        """A cell attribute layer as a read-only `[cell_y, cell_x]` array, built on first use and
        again after a terrain change. None when the map has no such layer."""
        if layer not in self._cells:
            blend = self.map.blend_tile_data
            values = None
            if blend is not None:
                from sage_worldbuilder.terrain.cells import layer_array  # noqa: PLC0415 - numpy

                values = layer_array(blend, layer)
                if values is not None:
                    values.flags.writeable = False
            self._cells[layer] = values
        return self._cells[layer]

    def write_cells(self, layer: Layer, x0: int, y0: int, values: np.ndarray) -> None:
        """Store a rectangle of one attribute layer, `values[row, column]` from cell `(x0, y0)`,
        into the map and into the cached array."""
        blend = self.map.blend_tile_data
        if blend is None:
            raise ValueError("the map has no blend tile data")
        from sage_worldbuilder.terrain.cells import write_layer  # noqa: PLC0415 - numpy

        write_layer(blend, layer, x0, y0, values)
        cached = self._cells.get(layer)
        if cached is not None:
            rows, columns = values.shape
            cached.flags.writeable = True
            try:
                cached[y0 : y0 + rows, x0 : x0 + columns] = values
            finally:
                cached.flags.writeable = False

    def write_heights(self, x0: int, y0: int, values: np.ndarray) -> None:
        """Store a rectangle of heights, `values[row, column]` from sample `(x0, y0)` counted from
        the bottom-left, into the map and into the cached array. Only the touched rows of the
        saved form are rewritten, so an unedited map still saves byte-identically."""
        height_map = self.map.height_map_data
        if height_map is None:
            raise ValueError("the map has no heightmap")
        top = height_map.height - 1
        for offset, row in enumerate(values.tolist()):
            height_map.elevations[top - (y0 + offset)][x0 : x0 + len(row)] = row
        if self._terrain is not None:
            self._terrain.patch(x0, y0, values)

    def notify(self, *changes: Change) -> None:
        self.revision += 1
        if any(change.kind in _CASTLE_CHANGES for change in changes):
            self._castle_edited = True
        # A terrain change with a region was written into the cached array already.
        if any(
            change.kind in _TERRAIN_CHANGES
            and (change.kind is ChangeKind.WHOLE or change.region is None)
            for change in changes
        ):
            self._terrain = None
            self._cells.clear()
        if self.selection and any(change.kind in _SELECTABLE_CHANGES for change in changes):
            self.selection.keep_only(self._selectable())
        for change in changes:
            for listener in list(self._listeners):
                listener(change)

    def _selectable(self) -> list[object]:
        items: list[object] = []
        if self.map.objects_list is not None:
            items += self.map.objects_list.object_list
        if self.map.trigger_areas is not None:
            items += self.map.trigger_areas.trigger_areas
        return items

    def execute(self, command: Command) -> None:
        self.stack.push(command)

    def to_bytes(self, compress: bool | None = None) -> bytes:
        return write_map(self.map, self.compressed if compress is None else compress)

    def save_target(self, path: str | Path | None = None) -> Path:
        """The file a save to `path` (default: where the map came from) would write.

        Raises `ReadOnlyMapError` when that file cannot be written, so the caller can offer
        Save As, and `ValueError` for a map with no file of its own saved without a path."""
        target = Path(path) if path is not None else self.path
        if target is None:
            raise ValueError("a map with no file of its own needs a path")
        same_file = self.path is not None and _same_path(target, self.path)
        if (self.read_only and same_file) or (target.exists() and not os.access(target, os.W_OK)):
            raise ReadOnlyMapError(f"{target} is read-only")
        return target

    def save(
        self,
        path: str | Path | None = None,
        *,
        compress: bool | None = None,
        data: bytes | None = None,
    ) -> Path:
        """Write the map to `path` (default: where it came from) and mark it clean.

        `data`, when given, is the map already serialized with the same `compress` setting: a UI
        serializes on a worker (the slow part) and then commits here on its own thread. Raises
        as `save_target` does."""
        target = self.save_target(path)
        if compress is not None:
            self.compressed = compress
        atomic_write(target, data if data is not None else self.to_bytes())
        self.path = target
        self.read_only = False
        self._castle_edited = False
        self.stack.set_clean()
        return target


def _same_path(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
