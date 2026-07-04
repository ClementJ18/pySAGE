"""Parser for the APT image-map `.dat` file (`AptToBigc` output).

The `.dat` sitting beside a `.apt`/`.const` pair maps each `image` character to the
texture it samples and the sub-rectangle it crops out of that texture's atlas. Two record
kinds, one per line (`;`-prefixed lines are comments):

    <imageId>-><textureId>      the image samples texture `apt_<Movie>_<textureId>`
    <imageId>=<x> <y> <w> <h>   the image crops this pixel rectangle from that texture

An image with no assignment defaults to texture 1 (the movies observed only ever ship a
single `apt_<Movie>_1` atlas); an image with no rectangle has no known size, so the viewer
keeps drawing it as a placeholder. Stdlib-only — decoding the texture itself needs the
optional `[apt]`/`[ui]` extras (see `sage_apt.textures`)."""

from pathlib import Path


class ImageMap:
    """The parsed `.dat`: per-image texture assignments and crop rectangles."""

    DEFAULT_TEXTURE = 1

    def __init__(self):
        self.textures: dict[int, int] = {}  # image id -> texture id
        self.rects: dict[int, tuple[int, int, int, int]] = {}  # image id -> (x, y, w, h)

    def texture_of(self, image_id: int) -> int:
        """The texture id an image samples (falls back to texture 1)."""
        return self.textures.get(image_id, self.DEFAULT_TEXTURE)

    def rect_of(self, image_id: int) -> tuple[int, int, int, int] | None:
        """The (x, y, w, h) crop rectangle for an image, or None when unmapped."""
        return self.rects.get(image_id)

    def __bool__(self) -> bool:
        return bool(self.textures or self.rects)


def parse_image_map(text: str) -> ImageMap:
    """Parse the text of a `.dat` image map. Malformed lines are skipped."""
    imap = ImageMap()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if "->" in line:
            left, _, right = line.partition("->")
            try:
                imap.textures[int(left)] = int(right)
            except ValueError:
                continue
        elif "=" in line:
            left, _, right = line.partition("=")
            parts = right.split()
            if len(parts) != 4:
                continue
            try:
                imap.rects[int(left)] = tuple(int(p) for p in parts)  # type: ignore[assignment]
            except ValueError:
                continue
    return imap


def load_image_map(dat_path) -> ImageMap:
    """Parse the `.dat` at `dat_path`, or an empty map when it does not exist."""
    path = Path(dat_path)
    if not path.exists():
        return ImageMap()
    return parse_image_map(path.read_text("latin-1"))
