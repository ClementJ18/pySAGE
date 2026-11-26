"""Laying out an army for a measurement, following it, and logging the result.

A performance scenario is a crowd: hundreds of objects placed in a block, marched or thrown at
another block, with a pace measured over it (`sage_test.pace`). What every such test needs beside
the sampler is here - where the objects go, where the bulk of them is now, and one line per run
appended to a log that the next run is compared against.
"""

from __future__ import annotations

import json
import math
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path

__all__ = ["append_row", "formation", "median_centre"]

Point = tuple[float, float, float]


def formation(centre: Point, count: int, columns: int, rows: int, spacing: float) -> list[Point]:
    """`count` spots on a `columns` x `rows` grid around `centre`, nearest the centre first, so a
    small army is a compact block rather than a corner of a large one. Raises when the grid
    holds fewer than `count` spots."""
    x0 = centre[0] - (columns - 1) * spacing / 2
    y0 = centre[1] - (rows - 1) * spacing / 2
    spots = [(x0 + c * spacing, y0 + r * spacing, 0.0) for r in range(rows) for c in range(columns)]
    if count > len(spots):
        raise ValueError(f"{count} objects for {len(spots)} spots")
    spots.sort(key=lambda p: math.hypot(p[0] - centre[0], p[1] - centre[1]))
    return spots[:count]


def median_centre(points: Sequence[Point]) -> Point:
    """The median position, height included.

    The median keeps a camera on the bulk of an army rather than on empty ground between it and
    a few stragglers, and the height matters because the camera aims at a point on the terrain:
    aimed at z 0, a view over high ground looks under the surface and the army sits off-centre.
    """
    if not points:
        raise ValueError("no points to centre on")
    x, y, z = (statistics.median(p[axis] for p in points) for axis in range(3))
    return x, y, z


def append_row(path: Path, row: Mapping[str, object]) -> None:
    """Append `row` to a JSON-lines log, creating the file and its folder on first use."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as out:
        out.write(json.dumps(row) + "\n")
