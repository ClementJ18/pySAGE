from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext

# The per-cell values in stored order, by the `BlendTileData` attribute each one comes from; the
# second number is the first chunk version that stores it.
LAYERS = (
    ("impassability", 1),
    ("impassability_to_players", 1),
    ("taintability", 1),
    ("passage_widths", 1),
    ("extra_passability", 1),
    ("flammability", 2),
    ("visibility", 3),
)


@dataclass
class ScriptPassability:
    """A `.scb`-only asset: an exported map's cell attributes, which WorldBuilder's Export Options
    writes when "Include passability" is checked (`0x005350F3`) and an import paints back at its
    offset (`0x0053C800`).

    The chunk has no size of its own: it runs over the width and height `ScriptImportSize` gives.
    For each x, then each y, it stores one int32 per layer in `LAYERS` that its version has.
    `cells[name][x][y]` holds them as stored."""

    asset_name = "ScriptPassability"

    version: int
    cells: dict[str, list[list[int]]]
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext", width: int, height: int) -> Self:
        with context.read_asset() as asset_ctx:
            names = [name for name, since in LAYERS if asset_ctx.version >= since]
            cells: dict[str, list[list[int]]] = {name: [] for name in names}
            for _ in range(width):
                columns: dict[str, list[int]] = {name: [] for name in names}
                for _ in range(height):
                    for name in names:
                        columns[name].append(context.stream.readInt32())
                for name in names:
                    cells[name].append(columns[name])

        return cls(
            version=asset_ctx.version,
            cells=cells,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext") -> None:
        names = [name for name, since in LAYERS if self.version >= since]
        width = len(self.cells[names[0]])
        height = len(self.cells[names[0]][0]) if width else 0
        with context.write_asset(self.asset_name, self.version):
            for x in range(width):
                for y in range(height):
                    for name in names:
                        context.stream.writeInt32(self.cells[name][x][y])
