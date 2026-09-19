"""Utility functions for working with height maps and object positions.

Every function here takes **cell coordinates**: an object's world position divided by 10 (the
world units per heightmap cell), with (0, 0) at the inner corner of the border. A radius is in
cells too. So an object at world (1200, 800) is at cells (120, 80).
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..map import Map


def is_flat_at_position(map_obj: "Map", cell_x: float, cell_y: float, radius: float) -> bool:
    """
    Check if all height data within a radius of a position is at the same level.

    Args:
        map_obj: The Map object containing height map data
        cell_x: x in cells from the border's bottom-left corner
        cell_y: y in cells from the border's bottom-left corner
        radius: Radius in cells to check around the position

    Returns:
        True if all heights within radius are the same, False otherwise

    Note:
        - Position (0,0) is at the world border's bottom-left corner
        - This corresponds to heightmap position (border_width, border_width)
        - Heightmap rows start at the top, positions count up from the bottom
    """
    height_map = map_obj.height_map_data
    assert height_map is not None
    border = height_map.border_width
    world_height = height_map.height - 2 * border

    hm_x = cell_x + border
    hm_y = border + (world_height - cell_y - 1)

    center_x_int = int(round(hm_x))
    center_y_int = int(round(hm_y))

    if not (0 <= center_x_int < height_map.width and 0 <= center_y_int < height_map.height):
        return False

    center_height = height_map.elevations[center_y_int][center_x_int]

    radius_int = int(radius) + 1

    for dy in range(-radius_int, radius_int + 1):
        for dx in range(-radius_int, radius_int + 1):
            distance = (dx**2 + dy**2) ** 0.5
            if distance > radius:
                continue

            sample_x = center_x_int + dx
            sample_y = center_y_int + dy

            if not (0 <= sample_x < height_map.width and 0 <= sample_y < height_map.height):
                continue

            if height_map.elevations[sample_y][sample_x] != center_height:
                return False

    return True


def flatten_position_in_radius(map_obj: "Map", cell_x: float, cell_y: float, radius: float) -> None:
    """Set every height within `radius` cells of the position to the height at its centre."""
    height_map = map_obj.height_map_data
    assert height_map is not None
    border = height_map.border_width
    world_height = height_map.height - 2 * border

    hm_x = cell_x + border
    hm_y = border + (world_height - cell_y - 1)

    center_x_int = int(round(hm_x))
    center_y_int = int(round(hm_y))

    if not (0 <= center_x_int < height_map.width and 0 <= center_y_int < height_map.height):
        return

    center_height = height_map.elevations[center_y_int][center_x_int]

    radius_int = int(radius) + 1

    for dy in range(-radius_int, radius_int + 1):
        for dx in range(-radius_int, radius_int + 1):
            distance = (dx**2 + dy**2) ** 0.5
            if distance > radius:
                continue

            sample_x = center_x_int + dx
            sample_y = center_y_int + dy

            if not (0 <= sample_x < height_map.width and 0 <= sample_y < height_map.height):
                continue

            if height_map.elevations[sample_y][sample_x] != center_height:
                height_map.elevations[sample_y][sample_x] = center_height


def get_height_at_position(map_obj: "Map", cell_x: float, cell_y: float) -> int | None:
    """
    Get the height value at a position.

    Args:
        map_obj: The Map object containing height map data
        cell_x: x in cells from the border's bottom-left corner
        cell_y: y in cells from the border's bottom-left corner

    Returns:
        The height value at that position, or None if out of bounds
    """
    height_map = map_obj.height_map_data
    assert height_map is not None
    border = height_map.border_width
    world_height = height_map.height - 2 * border

    hm_x = int(round(cell_x + border))
    hm_y = int(round(border + (world_height - cell_y - 1)))

    if not (0 <= hm_x < height_map.width and 0 <= hm_y < height_map.height):
        return None

    return height_map.elevations[hm_y][hm_x]


def world_to_heightmap_coords(map_obj: "Map", cell_x: float, cell_y: float) -> tuple[int, int]:
    """
    Convert a position (bottom-left origin) to indices into `elevations` (top-left origin).

    Args:
        map_obj: The Map object containing height map data
        cell_x: x in cells from the border's bottom-left corner
        cell_y: y in cells from the border's bottom-left corner

    Returns:
        Tuple of (heightmap_x, heightmap_y) coordinates
    """
    height_map = map_obj.height_map_data
    assert height_map is not None
    border = height_map.border_width
    world_height = height_map.height - 2 * border

    hm_x = int(round(cell_x + border))
    hm_y = int(round(border + (world_height - cell_y - 1)))

    return (hm_x, hm_y)


def get_flatness_percentage(map_obj: "Map", cell_x: float, cell_y: float, radius: float) -> float:
    """
    Calculate the percentage of terrain within a radius that is at the same height as the center.

    Args:
        map_obj: The Map object containing height map data
        cell_x: x in cells from the border's bottom-left corner
        cell_y: y in cells from the border's bottom-left corner
        radius: Radius in cells to check around the position

    Returns:
        Percentage (0.0 to 1.0) of points within radius that match the center height
    """
    height_map = map_obj.height_map_data
    assert height_map is not None
    border = height_map.border_width
    world_height = height_map.height - 2 * border

    hm_x = cell_x + border
    hm_y = border + (world_height - cell_y - 1)

    center_x_int = int(round(hm_x))
    center_y_int = int(round(hm_y))

    if not (0 <= center_x_int < height_map.width and 0 <= center_y_int < height_map.height):
        return 0.0

    center_height = height_map.elevations[center_y_int][center_x_int]

    radius_int = int(radius) + 1
    total_points = 0
    matching_points = 0

    for dy in range(-radius_int, radius_int + 1):
        for dx in range(-radius_int, radius_int + 1):
            distance = (dx**2 + dy**2) ** 0.5
            if distance > radius:
                continue

            sample_x = center_x_int + dx
            sample_y = center_y_int + dy

            if not (0 <= sample_x < height_map.width and 0 <= sample_y < height_map.height):
                continue

            total_points += 1

            if height_map.elevations[sample_y][sample_x] == center_height:
                matching_points += 1

    if total_points == 0:
        return 0.0

    return matching_points / total_points
