"""Resolve an APT `image` character to real artwork (a cropped PNG data-URI).

Ties the stdlib `.dat` image map (`sage_apt.imagemap`) to the shared texture decoder
(`sage_utils.textures.TextureSource`): an image samples texture `apt_<Movie>_<id>` and
crops the rectangle the `.dat` records out of it. Everything here needs the optional
`[apt]`/`[ui]` extras (Pillow + pyBIG); the core `sage_apt` stays stdlib-only, so this
module is imported lazily via `build_resolver`, which returns None whenever the extras or
the game textures are missing and the viewer/editor should fall back to placeholders."""

import base64
import io
from pathlib import Path

from PIL import Image

from sage_apt.geometry import Fill, invert_matrix, load_geometry_dir
from sage_apt.imagemap import ImageMap, load_image_map
from sage_utils.textures import TextureSource


class AptTextureResolver:
    """Crops `image` characters out of a movie's `apt_<Movie>_<id>` atlas textures, and -
    when a `_geometry` directory was loaded - supplies the per-shape textured/solid fills
    plus the whole atlas so `shape` characters can be drawn with real artwork.

    `movie` is the movie base name (e.g. `FactionFrame`); `image_map` supplies the
    per-image texture id and crop rectangle; `source` decodes the atlas bytes; `geometry`
    maps a shape's geometry id to its fills. Decoded atlases and encoded PNGs are cached,
    since many images/shapes share one texture."""

    def __init__(
        self,
        movie: str,
        image_map: ImageMap,
        source: TextureSource,
        geometry: dict[int, list[Fill]] | None = None,
    ):
        self.movie = movie
        self.image_map = image_map
        self.source = source
        self.geometry = geometry or {}
        self._atlas: dict[int, Image.Image | None] = {}
        self._atlas_png: dict[int, bytes | None] = {}

    def _atlas_for(self, texture_id: int) -> Image.Image | None:
        if texture_id not in self._atlas:
            data = self.source.texture_bytes(f"apt_{self.movie}_{texture_id}")
            picture: Image.Image | None = None
            if data is not None:
                try:
                    picture = Image.open(io.BytesIO(data))
                    picture.load()
                    picture = picture.convert("RGBA")
                except Exception:  # noqa: BLE001 - an undecodable atlas just disables its images
                    picture = None
            self._atlas[texture_id] = picture
        return self._atlas[texture_id]

    def image_png(self, image_id: int) -> bytes | None:
        """The cropped PNG bytes for an `image` character, or None when it can't be
        resolved (no crop rectangle, missing texture, undecodable atlas)."""
        rect = self.image_map.rect_of(image_id)
        if rect is None:
            return None  # without a rectangle the on-screen size is unknown
        atlas = self._atlas_for(self.image_map.texture_of(image_id))
        if atlas is None:
            return None
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            return None
        left = max(0, min(atlas.width, x))
        top = max(0, min(atlas.height, y))
        right = max(left, min(atlas.width, x + w))
        bottom = max(top, min(atlas.height, y + h))
        crop = atlas.crop((left, top, right, bottom))
        out = io.BytesIO()
        crop.save(out, format="PNG")
        return out.getvalue()

    def image_data_uri(self, image_id: int) -> str | None:
        """`image_png` as a `data:image/png;base64,...` URI, or None."""
        png = self.image_png(image_id)
        if png is None:
            return None
        return "data:image/png;base64," + base64.b64encode(png).decode("ascii")

    def rect_of(self, image_id: int) -> tuple[int, int, int, int] | None:
        """The image's on-screen (x, y, w, h) - passthrough to the image map."""
        return self.image_map.rect_of(image_id)

    # --- shape geometry ---

    def shape_fills(self, geometry_id: int) -> list[Fill]:
        """The parsed fills for a shape's geometry id (empty when none/unloaded)."""
        return self.geometry.get(geometry_id, [])

    def atlas_size(self, image_id: int) -> tuple[int, int] | None:
        """The (width, height) of the atlas texture an image samples, or None."""
        atlas = self._atlas_for(self.image_map.texture_of(image_id))
        return atlas.size if atlas is not None else None

    def atlas_png_by_texture(self, texture_id: int) -> bytes | None:
        """The whole atlas for a texture id, PNG-encoded (cached), or None."""
        if texture_id not in self._atlas_png:
            atlas = self._atlas_for(texture_id)
            if atlas is None:
                self._atlas_png[texture_id] = None
            else:
                out = io.BytesIO()
                atlas.save(out, format="PNG")
                self._atlas_png[texture_id] = out.getvalue()
        return self._atlas_png[texture_id]

    def atlas_png(self, image_id: int) -> bytes | None:
        """The whole atlas texture an image samples, PNG-encoded (cached), or None."""
        return self.atlas_png_by_texture(self.image_map.texture_of(image_id))

    def geometry_manifest(self) -> dict[str, list[dict]]:
        """A JSON-friendly `{geometry id: [fill, ...]}` for the editor: solid fills carry
        their colour, textured fills carry the texture id, atlas size, the uv->position
        inverse matrix, and their triangles. Only fills that actually resolve are kept."""
        out: dict[str, list[dict]] = {}
        for gid, fills in self.geometry.items():
            entries: list[dict] = []
            for fill in fills:
                if fill.kind == "solid":
                    entries.append(
                        {
                            "kind": "solid",
                            "color": list(fill.color),
                            "tris": [list(t) for t in fill.triangles],
                        }
                    )
                elif fill.kind == "textured" and fill.image_id is not None and fill.matrix:
                    inv = invert_matrix(fill.matrix)
                    size = self.atlas_size(fill.image_id)
                    if inv is None or size is None:
                        continue
                    entries.append(
                        {
                            "kind": "textured",
                            "tex": self.image_map.texture_of(fill.image_id),
                            "w": size[0],
                            "h": size[1],
                            "inv": list(inv),
                            "tris": [list(t) for t in fill.triangles],
                        }
                    )
            if entries:
                out[str(gid)] = entries
        return out

    def atlas_data_uri(self, image_id: int) -> str | None:
        """`atlas_png` as a `data:image/png;base64,...` URI, or None."""
        png = self.atlas_png(image_id)
        if png is None:
            return None
        return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def build_resolver(apt_or_xml_path, game_dir) -> AptTextureResolver | None:
    """Build a resolver for the movie at `apt_or_xml_path`, sourcing textures from
    `game_dir` (a folder scanned for `.dds`/`.tga`, including `compiledtextures`). Returns
    None when `game_dir` is falsy, the `.dat` image map yields nothing usable, or no
    matching atlas texture is found - the caller then keeps its placeholder rendering.

    Imported lazily by the CLI/editor so `import sage_apt` never needs the `[apt]` extra."""
    if not game_dir:
        return None
    path = Path(apt_or_xml_path)
    movie = path.stem
    image_map = load_image_map(path.with_suffix(".dat"))
    geometry = load_geometry_dir(path.with_name(f"{movie}_geometry"))
    if not image_map and not geometry:
        return None
    source = TextureSource([("folder", str(game_dir))])
    resolver = AptTextureResolver(movie, image_map, source, geometry)
    # Offer the resolver only if something actually resolves to artwork: a cropped image,
    # or a textured shape fill whose atlas is present.
    if any(resolver.image_png(i) is not None for i in image_map.rects):
        return resolver
    for fills in geometry.values():
        for fill in fills:
            if fill.kind == "textured" and fill.image_id is not None:
                if resolver.atlas_png(fill.image_id) is not None:
                    return resolver
    return None
