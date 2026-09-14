"""The terrain textures a map paints, for the top-down view and the texture palette.

A map names each texture it uses by its Terrain.ini entry; the entry's `Texture` is a file under
`art\\terrain\\`. Each file is read once and reduced to its average colour (the view), its width
in 64-pixel texture cells (a texture added to a map), and a small preview (the palette). The
palette groups the entries by their `Class`: `Type <kind>`, optionally followed by
`NEXT Region <name>` clauses.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from pathlib import PureWindowsPath
from typing import TYPE_CHECKING, Protocol

import numpy as np

from sage_map.assets.blend_tile_data import BlendDescription, BlendTileData, BlendTileTexture
from sage_worldbuilder.render.topdown import (
    blend_kinds,
    blend_pixels,
    blended_colors,
    class_colors,
    height_colors,
    tile_classes,
)
from sage_worldbuilder.terrain.cells import TileLayer, layer_array

if TYPE_CHECKING:
    from sage_ini.model.game import Game
    from sage_utils.vfs import VfsEntry

__all__ = [
    "BlendTable",
    "TextureColors",
    "average_color",
    "base_colors",
    "blend_table",
    "patch_base_colors",
    "patch_picture_colors",
    "picture_colors",
    "preview_rgb",
    "terrain_class_group",
    "terrain_textures",
    "texture_palette",
]

Color = tuple[int, int, int]
# Per blend number: the kind of blend (`blend_kinds`) and the RGB of its texture.
BlendTable = tuple[np.ndarray, np.ndarray]
_TERRAIN_FOLDER = "art\\terrain\\"
_TEXTURE_CELL_PIXELS = 64
OTHER = "Other"


class _FileSystem(Protocol):
    def find(self, path: str) -> VfsEntry | None: ...

    def read_bytes(self, entry: VfsEntry | str) -> bytes: ...


def terrain_textures(game: Game) -> dict[str, str]:
    """Terrain.ini entry name -> its texture file (none when the game data has no terrains)."""
    return {
        name: str(terrain.Texture)
        for name, terrain in (getattr(game, "terrains", None) or {}).items()
        if getattr(terrain, "Texture", None)
    }


def terrain_class_group(value: str) -> tuple[str, str]:
    """The (type, first region) a Terrain.ini `Class` names; `Other` for no type, '' for no
    region."""
    tokens = str(value).split()
    kind, region = OTHER, ""
    for index, token in enumerate(tokens[:-1]):
        if token.lower() == "type" and kind == OTHER:
            kind = tokens[index + 1].capitalize()
        elif token.lower() == "region" and not region:
            region = tokens[index + 1]
    return kind, region


def texture_palette(game: Game) -> dict[str, dict[str, list[str]]]:
    """The game's terrain textures as type -> region ('' for none) -> names, all sorted. Terrain.ini
    spells some regions in more than one case (`FANGORN_FOREST`, `Fangorn_Forest`); they are one
    group, under the first spelling met."""
    groups: dict[str, dict[str, list[str]]] = {}
    spellings: dict[str, str] = {}
    for name, terrain in (getattr(game, "terrains", None) or {}).items():
        if not getattr(terrain, "Texture", None):
            continue
        kind, region = terrain_class_group(getattr(terrain, "Class", "") or "")
        region = spellings.setdefault(region.lower(), region)
        groups.setdefault(kind, {}).setdefault(region, []).append(name)
    return {
        kind: {region: sorted(names, key=str.lower) for region, names in sorted(regions.items())}
        for kind, regions in sorted(groups.items())
    }


def average_color(data: bytes) -> Color | None:
    """The mean colour of an image, or None when Pillow cannot read it."""
    try:
        from PIL import Image  # noqa: PLC0415 - lazy: only needed once a texture is read

        with Image.open(io.BytesIO(data)) as image:
            pixel = image.convert("RGB").resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
    except (ImportError, OSError, ValueError):
        return None
    assert isinstance(pixel, tuple)
    red, green, blue = pixel[:3]
    return int(red), int(green), int(blue)


def preview_rgb(data: bytes, size: int) -> tuple[bytes, int, int] | None:
    """A `size`-pixel-square RGB preview of an image: `(pixels, width, height)`, or None when
    Pillow cannot read it."""
    try:
        from PIL import Image  # noqa: PLC0415 - lazy

        with Image.open(io.BytesIO(data)) as image:
            small = image.convert("RGB").resize((size, size), Image.Resampling.BILINEAR)
            return small.tobytes(), size, size
    except (ImportError, OSError, ValueError):
        return None


def _image_width(data: bytes) -> int | None:
    try:
        from PIL import Image  # noqa: PLC0415 - lazy

        with Image.open(io.BytesIO(data)) as image:
            return int(image.size[0])
    except (ImportError, OSError, ValueError):
        return None


class TextureColors:
    """Average colours, sizes and image data by Terrain.ini name, read from `filesystem` on
    first use and kept."""

    def __init__(self, filesystem: _FileSystem, textures: Mapping[str, str]) -> None:
        self.filesystem = filesystem
        self._textures = {name.lower(): texture for name, texture in textures.items()}
        self._colors: dict[str, Color | None] = {}
        self._sizes: dict[str, int | None] = {}
        self._cells: dict[tuple[str, int, int], np.ndarray | None] = {}

    def cells(self, terrain: str, cell_size: int, pixels: int) -> np.ndarray | None:
        """The texture cut into its cells as the game reads it (`texture_cells`), kept."""
        from sage_worldbuilder.render.terrain_texturing import texture_cells  # noqa: PLC0415

        key = (terrain.lower(), cell_size, pixels)
        if key not in self._cells:
            data = self.image(key[0])
            self._cells[key] = texture_cells(data, cell_size, pixels) if data is not None else None
        return self._cells[key]

    def color(self, terrain: str) -> Color | None:
        key = terrain.lower()
        if key not in self._colors:
            data = self.image(key)
            self._colors[key] = average_color(data) if data is not None else None
        return self._colors[key]

    def cell_size(self, terrain: str) -> int | None:
        """The texture's width in 64-pixel texture cells, or None when its image is not found."""
        key = terrain.lower()
        if key not in self._sizes:
            data = self.image(key)
            width = _image_width(data) if data is not None else None
            self._sizes[key] = max(width // _TEXTURE_CELL_PIXELS, 1) if width else None
        return self._sizes[key]

    def image(self, terrain: str) -> bytes | None:
        """The texture's image file, or None when Terrain.ini or the files lack it."""
        texture = self._textures.get(terrain.lower())
        if texture is None:
            return None
        stem = PureWindowsPath(texture).stem
        for name in (texture, f"{stem}.tga", f"{stem}.dds"):
            entry = self.filesystem.find(_TERRAIN_FOLDER + name)
            if entry is not None:
                return self.filesystem.read_bytes(entry)
        return None


def base_colors(blend: BlendTileData, heights: np.ndarray, colors: TextureColors) -> np.ndarray:
    """RGB per heightmap sample from the texture painted there. A texture whose colour is
    unknown, and a map whose tiles do not match its heightmap, show the height ramp."""
    ramp = height_colors(heights)
    classes = tile_classes(blend)
    if classes.shape != heights.shape:
        return ramp
    palette = np.zeros((len(blend.textures), 3), dtype=np.uint8)
    unknown = []
    for index, texture in enumerate(blend.textures):
        color = colors.color(texture.name)
        if color is None:
            unknown.append(index)
        else:
            palette[index] = color
    if unknown:
        classes = np.where(np.isin(classes, unknown), -1, classes).astype(classes.dtype)
    return class_colors(classes, palette, ramp)


def patch_base_colors(
    base: np.ndarray,
    textures: list[BlendTileTexture],
    tiles: np.ndarray,
    colors: TextureColors,
    region: tuple[int, int, int, int],
) -> None:
    """Recolour the cells `x0 <= x < x1`, `y0 <= y < y1` of `base` (as `base_colors` makes it) by
    the textures now painted there; a texture whose colour is unknown leaves its cells as they
    were."""
    from sage_worldbuilder.terrain.textures import texture_classes  # noqa: PLC0415 - no cycle

    x0, y0, x1, y1 = region
    classes = texture_classes(tiles[y0:y1, x0:x1], textures)
    block = base[y0:y1, x0:x1]
    for index in np.unique(classes):
        if index < 0:
            continue
        color = colors.color(textures[int(index)].name)
        if color is not None:
            block[classes == index] = color


def blend_table(
    descriptions: list[BlendDescription],
    textures: list[BlendTileTexture],
    colors: TextureColors,
) -> BlendTable:
    """Per blend number (0 for none, then each description): its kind of blend, -1 where the
    texture it blends in has no known colour, and that colour."""
    from sage_worldbuilder.terrain.textures import texture_classes  # noqa: PLC0415 - no cycle

    kinds = blend_kinds(descriptions)
    table = np.zeros((len(descriptions) + 1, 3), dtype=np.uint8)
    if not descriptions:
        return kinds, table
    secondary = np.array([d.secondary_texture_tile for d in descriptions], dtype=np.int64)
    classes = texture_classes(secondary, textures)
    described_kinds, described_colors = kinds[1:], table[1:]
    described_kinds[classes < 0] = -1
    for index in np.unique(classes[classes >= 0]).tolist():
        chosen = classes == index
        color = colors.color(textures[index].name)
        if color is None:
            described_kinds[chosen] = -1
        else:
            described_colors[chosen] = color
    return kinds, table


def picture_colors(
    blend: BlendTileData, heights: np.ndarray, colors: TextureColors
) -> tuple[np.ndarray, np.ndarray, BlendTable]:
    """The map view's colours: RGB per sample (`base_colors`), the picture's RGB with its blends
    at `blend_pixels` pixels a cell side, and the blend table to patch the picture with."""
    base = base_colors(blend, heights, colors)
    table = blend_table(blend.blend_descriptions, blend.textures, colors)
    blends = layer_array(blend, TileLayer.BLENDS)
    three_way = layer_array(blend, TileLayer.THREE_WAY_BLENDS)
    shape = base.shape[:2]
    if blends is None or three_way is None or blends.shape != shape or three_way.shape != shape:
        return base, base.copy(), table
    picture = blended_colors(base, [blends, three_way], *table, blend_pixels(heights.shape))
    return base, picture, table


def patch_picture_colors(
    picture: np.ndarray,
    base: np.ndarray,
    blends: np.ndarray,
    three_way: np.ndarray,
    table: BlendTable,
    region: tuple[int, int, int, int],
) -> None:
    """Redraw the cells `x0 <= x < x1`, `y0 <= y < y1` of `picture` (as `picture_colors` makes
    it) from `base` and the blend layers."""
    x0, y0, x1, y1 = region
    pixels = picture.shape[0] // max(base.shape[0], 1)
    block = blended_colors(
        base[y0:y1, x0:x1],
        (blends[y0:y1, x0:x1], three_way[y0:y1, x0:x1]),
        *table,
        pixels,
    )
    picture[y0 * pixels : y1 * pixels, x0 * pixels : x1 * pixels] = block
