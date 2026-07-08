"""Resolve and crop SAGE button images from a set of texture sources.

A MappedImage names a `Texture` and a `Coords` rectangle into it; the pixels live
in a separate texture archive, the compiled `.dds` for `FileName.tga` sitting at
`art/compiledtextures/XX/FileName.dds` (`XX` = the name's first two letters). This
module indexes the sources, decodes the texture and crops out the rectangle. Qt-free
so it can run headless.
"""

import functools
import io
import sys
from collections.abc import Callable
from pathlib import Path

from PIL import Image
from pyBIG import InDiskArchive

from sage_utils.sources import norm_key  # source-relative path → lowercase forward-slash key
from sage_utils.views import portrait_mapped_images, safe

# A `Texture` names the source `.tga`, but the shipped file is the compiled `.dds`;
# the authored extension is ignored on lookup, `.dds` preferred over a `.tga` fallback.
TEXTURE_SUFFIXES = (".dds", ".tga")


class TextureSource:
    """An indexed set of folder / .big image sources, queried by texture name.

    Each texture is indexed by normalized path and file name; later sources override
    earlier ones, matching the game's load order. Bytes are read lazily so adding a
    huge texture archive only lists its entries, never buffers it whole.
    """

    def __init__(self, sources: list[tuple[str, str]]) -> None:
        self._loaders: dict[str, Callable[[], bytes]] = {}
        self._by_filename: dict[str, str] = {}
        for kind, path in sources:
            if kind == "folder":
                self._index_folder(Path(path))
            else:
                self._index_big(path)

    def _add(self, key: str, loader: Callable[[], bytes]) -> None:
        self._loaders[key] = loader
        self._by_filename[key.rsplit("/", 1)[-1]] = key

    def _index_folder(self, base: Path) -> None:
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() in TEXTURE_SUFFIXES:
                self._add(norm_key(path.relative_to(base)), path.read_bytes)

    def _index_big(self, big_path: str) -> None:
        archive = InDiskArchive(str(big_path))
        for name in archive.file_list():
            if Path(name).suffix.lower() in TEXTURE_SUFFIXES:
                self._add(norm_key(name), lambda n=name: archive.read_file(n))

    def __len__(self) -> int:
        return len(self._loaders)

    def texture_bytes(self, texture) -> bytes | None:
        """The texture bytes for a `Texture` name, or None.

        Each candidate extension (`.dds` first, then `.tga`) is tried at the
        conventional `art/compiledtextures/XX/<stem>.<ext>` path, then by file name
        anywhere, so a texture stored outside that layout still resolves.
        """
        if not texture:
            return None
        stem = Path(str(texture)).stem
        if not stem:
            return None
        xx = stem[:2].lower()
        for ext in TEXTURE_SUFFIXES:
            primary = f"art/compiledtextures/{xx}/{stem}{ext}".lower()
            loader = self._loaders.get(primary)
            if loader is None:
                key = self._by_filename.get(f"{stem.lower()}{ext}")
                loader = self._loaders.get(key) if key is not None else None
            if loader is not None:
                return loader()
        return None


def _coords_box(image, width: int, height: int) -> tuple[int, int, int, int] | None:
    """The crop box `(left, top, right, bottom)` for a MappedImage's Coords, or None
    when it carries no usable Coords.

    Coords are offsets into the texture as authored at TextureWidth x TextureHeight;
    when the .dds was compiled at a different size the box is scaled so the crop lines up.
    """
    coords = safe(lambda: image.Coords) or {}
    try:
        left = int(float(coords["Left"]))
        top = int(float(coords["Top"]))
        right = int(float(coords["Right"]))
        bottom = int(float(coords["Bottom"]))
    except (KeyError, TypeError, ValueError):
        return None
    tw = safe(lambda: image.TextureWidth)
    th = safe(lambda: image.TextureHeight)
    if tw and th and (tw != width or th != height):
        sx, sy = width / tw, height / th
        left, right = round(left * sx), round(right * sx)
        top, bottom = round(top * sy), round(bottom * sy)
    # Clamp to the texture and order the edges (an authored box may run a pixel
    # past an edge or list its corners reversed).
    left, right = sorted((max(0, min(width, left)), max(0, min(width, right))))
    top, bottom = sorted((max(0, min(height, top)), max(0, min(height, bottom))))
    return (left, top, right, bottom)


def crop_mapped_image(source: TextureSource, image) -> Image.Image | None:
    """The cropped button image for a MappedImage, or None when its texture isn't
    found or can't be decoded.

    With no usable Coords the whole texture is returned. Always RGBA so it saves to
    PNG with transparency and renders in Qt without per-format handling.
    """
    data = source.texture_bytes(safe(lambda: image.Texture))
    if data is None:
        return None
    try:
        picture = Image.open(io.BytesIO(data))
        picture.load()
    except Exception:  # noqa: BLE001  (a non-image / undecodable entry shouldn't abort)
        return None
    box = _coords_box(image, picture.width, picture.height)
    cropped = picture if box is None else picture.crop(box)
    return cropped.convert("RGBA")


@functools.cache
def _asset_image(name: str) -> Image.Image | None:
    """A bundled `sage_utils/assets/<name>` image as RGBA, or None when missing/undecodable.

    Resolves under `sys._MEIPASS` in a PyInstaller build. Cached, since the assets are
    static; callers that mutate must copy first.
    """
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    path = base / "assets" / name
    if not path.exists():
        return None
    try:
        image = Image.open(path)
        image.load()
    except Exception:  # noqa: BLE001 — a missing/bad asset just disables what uses it
        return None
    return image.convert("RGBA")


def default_background() -> Image.Image | None:
    """The bundled parchment portrait background as RGBA, or None when missing/undecodable."""
    return _asset_image("background.png")


# The frame drawn around a command icon: the active frame for a pressable button, the
# passive frame for a non-pressable one. Keyed by `button_overlay_kind`'s return values.
_OVERLAY_FILES = {"active": "active_overlay.png", "passive": "passive_overlay.png"}


def ability_overlay(kind: str | None) -> Image.Image | None:
    """The bundled ability frame overlay for `kind` (`"active"`/`"passive"`) as RGBA, or
    None for any other kind or when the asset is missing."""
    name = _OVERLAY_FILES.get(kind)
    return _asset_image(name) if name is not None else None


def frame_icon(icon: Image.Image, overlay: Image.Image, size: int = 58) -> Image.Image:
    """`icon` scaled to `size`x`size` and centered on a transparent canvas the size of
    `overlay`, with `overlay` (a decorative frame) composited on top. The result is
    overlay-sized."""
    canvas = Image.new("RGBA", overlay.size, (0, 0, 0, 0))
    resized = icon.convert("RGBA").resize((size, size), Image.LANCZOS)
    ow, oh = overlay.size
    offset = ((ow - size) // 2, (oh - size) // 2)
    canvas.alpha_composite(resized, offset)
    canvas.alpha_composite(overlay)
    return canvas


def composite_on_background(portrait: Image.Image, background: Image.Image) -> Image.Image:
    """`portrait` scaled to fit (keeping aspect ratio) and alpha-composited centered
    over a copy of `background`. The result is background-sized."""
    base = background.convert("RGBA").copy()
    bw, bh = base.size
    pw, ph = portrait.size
    if not pw or not ph:
        return base
    scale = min(bw / pw, bh / ph)
    size = (max(1, round(pw * scale)), max(1, round(ph * scale)))
    resized = portrait.convert("RGBA").resize(size, Image.LANCZOS)
    offset = ((bw - size[0]) // 2, (bh - size[1]) // 2)
    base.alpha_composite(resized, offset)
    return base


def render_portrait(source: TextureSource, obj, background: Image.Image | None = None):
    """The object's portrait cropped from `source`, composited centered on `background`
    when one is given; None when the object defines no portrait or its texture isn't in
    `source`. The shared core of the desktop portrait preview and the wiki image upload —
    each caller converts the returned Pillow image to a pixmap or PNG."""
    images = portrait_mapped_images(obj)
    if not images:
        return None
    picture = crop_mapped_image(source, images[0])
    if picture is None:
        return None
    if background is not None:
        picture = composite_on_background(picture, background)
    return picture
