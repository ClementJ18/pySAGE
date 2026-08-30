"""Parser for the APT image-map `.dat` file (`AptToBigc` output).

The `.dat` sitting beside a `.apt`/`.const` pair maps each `image` character to the
texture it samples and the sub-rectangle it crops out of that texture's atlas. Two record
kinds, one per line (`;`-prefixed lines are comments):

    <imageId>-><textureId>      the image samples texture `apt_<Movie>_<textureId>`
    <imageId>=<x> <y> <w> <h>   the image crops this pixel rectangle from that texture

The two rows are independent, and a movie can ship either or both - `apt/gadgettimer.big`
has only rectangles, `apt/mainmenu.big` only assignments, `apt/ingamenotificationbox.big`
some of each. What an image samples when it has no `->` row therefore depends on whether it
has a rectangle: **a rectangle implies a texture of the image's own name**, which is what
every rect row in the corpus does (each of the nineteen ROTWK movies with one, and BFME1's
`MainMenu`, ships an `apt_<Movie>_<key>` per key and no atlas holding them); an image with
neither row falls back to texture 1, the single atlas the `->` rows all point at. An image
with no rectangle has no known size, so the viewer keeps drawing it as a placeholder.

Stdlib-only - decoding the texture itself needs the optional `[apt]`/`[ui]` extras (see
`sage_apt.textures`)."""

from pathlib import Path


class ImageMap:
    """The parsed `.dat`: per-image texture assignments and crop rectangles."""

    DEFAULT_TEXTURE = 1

    def __init__(self):
        self.textures: dict[int, int] = {}  # image id -> texture id
        self.rects: dict[int, tuple[int, int, int, int]] = {}  # image id -> (x, y, w, h)

    def texture_of(self, image_id: int) -> int:
        """The texture id an image samples.

        An explicit `->` row wins. Failing that, an image with a **rectangle** row samples a
        texture of its own, named after itself: across the nineteen ROTWK movies that ship rect
        rows, and BFME1's `MainMenu`, every rect key has a matching `apt_<Movie>_<key>` beside it
        and there is no shared atlas holding them. Only an image with neither row falls back to
        texture 1, which is the single atlas the `->` rows all point at.
        """
        if image_id in self.textures:
            return self.textures[image_id]
        return image_id if image_id in self.rects else self.DEFAULT_TEXTURE

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
