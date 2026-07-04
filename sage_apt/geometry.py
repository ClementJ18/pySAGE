"""Parser for APT shape geometry (`<Movie>_geometry/<id>.ru`, `AptToBigc` output).

A `shape` character carries a `geometry` id naming a `.ru` file that describes how the
shape is filled: a list of fills, each a run of triangles sharing one style. Line-based:

    c                              start of a new sub-shape (a fresh style block)
    s s:<r>:<g>:<b>:<a>            solid-colour fill (RGBA 0-255)
    s tc:<r>:<g>:<b>:<a>:<img>:<a>:<b>:<c>:<d>:<tx>:<ty>
                                   textured fill: RGBA tint, the `image` character id whose
                                   `.dat` texture supplies the atlas, and a 2x3 matrix that
                                   maps vertex position -> texture pixel (uv = M * pos)
    s l:<w>:<r>:<g>:<b>:<a>        line-stroke style (thin outlines; not filled)
    t <x1>:<y1>:<x2>:<y2>:<x3>:<y3>   a triangle in the current fill
    l <x1>:<y1>:<x2>:<y2>          a stroked line segment

The renderer needs the solid and textured fills (the real artwork); line styles/segments
are kept out of the fills as they are hairline outlines. Stdlib-only — the atlas decode
lives in `sage_apt.textures`."""

from dataclasses import dataclass, field
from pathlib import Path

Triangle = tuple[float, float, float, float, float, float]


@dataclass
class Fill:
    """One style block: a colour (and, when textured, an image id + pos->uv matrix) plus
    the triangles it covers."""

    kind: str  # "solid" | "textured"
    color: tuple[int, int, int, int]
    triangles: list[Triangle] = field(default_factory=list)
    image_id: int | None = None
    matrix: tuple[float, float, float, float, float, float] | None = None


def invert_matrix(
    m: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float, float, float] | None:
    """Invert a 2x3 affine `(a, b, c, d, tx, ty)` (SVG matrix order). A textured fill's
    matrix maps position -> texture uv; the inverse maps uv -> position, which is the
    transform the renderer applies to the atlas image. None when the matrix is singular."""
    a, b, c, d, tx, ty = m
    det = a * d - b * c
    if det == 0:
        return None
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    return (ia, ib, ic, id_, -(ia * tx + ic * ty), -(ib * tx + id_ * ty))


def parse_geometry(text: str) -> list[Fill]:
    """Parse a `.ru` geometry file into its solid/textured fills (line styles skipped)."""
    fills: list[Fill] = []
    current: Fill | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        head = line[0]
        if head == "s" and line[1:2] == " ":
            parts = line[2:].split(":")
            style = parts[0]
            try:
                if style == "tc":
                    color = tuple(int(p) for p in parts[1:5])
                    image_id = int(parts[5])
                    matrix = tuple(float(p) for p in parts[6:12])
                    if len(matrix) != 6:
                        current = None
                        continue
                    current = Fill("textured", color, image_id=image_id, matrix=matrix)  # type: ignore[arg-type]
                    fills.append(current)
                elif style == "s":
                    color = tuple(int(p) for p in parts[1:5])
                    current = Fill("solid", color)  # type: ignore[arg-type]
                    fills.append(current)
                else:  # "l" line style or anything else: no fill
                    current = None
            except (ValueError, IndexError):
                current = None
        elif head == "t" and line[1:2] == " ":
            if current is not None:
                try:
                    nums = tuple(float(p) for p in line[2:].split(":"))
                except ValueError:
                    continue
                if len(nums) == 6:
                    current.triangles.append(nums)  # type: ignore[arg-type]
        # 'c' (new sub-shape) and 'l' (line segment) carry nothing the renderer needs.
    return [f for f in fills if f.triangles]


def load_geometry_dir(geometry_dir) -> dict[int, list[Fill]]:
    """Parse every `<id>.ru` in a `_geometry` directory into `{geometry id: fills}`.
    Returns an empty map when the directory is absent."""
    base = Path(geometry_dir)
    if not base.is_dir():
        return {}
    out: dict[int, list[Fill]] = {}
    for ru in base.glob("*.ru"):
        try:
            gid = int(ru.stem)
        except ValueError:
            continue
        out[gid] = parse_geometry(ru.read_text("latin-1"))
    return out
