from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext


@dataclass
class HeightMapBorder:
    corner1: tuple[int, int]
    position: tuple[int, int]

    @classmethod
    def parse(cls, context: "ParsingContext", version: int) -> Self:
        if version >= 6:
            corner1X = context.stream.readUInt32()
            corner1Y = context.stream.readUInt32()
        else:
            corner1X = 0
            corner1Y = 0

        x = context.stream.readUInt32()
        y = context.stream.readUInt32()

        return cls(corner1=(corner1X, corner1Y), position=(x, y))

    def write(self, context: "WritingContext", version: int) -> None:
        if version >= 6:
            context.stream.writeUInt32(self.corner1[0])
            context.stream.writeUInt32(self.corner1[1])

        context.stream.writeUInt32(self.position[0])
        context.stream.writeUInt32(self.position[1])


@dataclass
class HeightMapData:
    asset_name = "HeightMapData"

    version: int
    width: int
    height: int
    border_width: int
    borders: list[HeightMapBorder]
    area: int
    min_height: int | None
    max_height: int | None
    elevations: list[list[int]]
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        with context.read_asset() as asset_ctx:
            width = context.stream.readUInt32()
            height = context.stream.readUInt32()
            border_width = context.stream.readUInt32()

            border_count = context.stream.readUInt32()
            borders = []
            for _ in range(border_count):
                borders.append(HeightMapBorder.parse(context, asset_ctx.version))

            area = context.stream.readUInt32()
            if area != width * height:
                raise ValueError(f"Invalid area: {area}, expected: {width * height}")

            min_height = None
            max_height = None
            elevations = [[0 for _ in range(width)] for _ in range(height)]
            for y in range(height):
                for x in range(width):
                    if asset_ctx.version >= 5:
                        elevation = context.stream.readUInt16()
                    else:
                        elevation = context.stream.readUChar()
                    flipped_y = height - 1 - y
                    elevations[flipped_y][x] = elevation
                    if min_height is None or elevation < min_height:
                        min_height = elevation
                    if max_height is None or elevation > max_height:
                        max_height = elevation

        context.logger.debug(f"Finished parsing {cls.asset_name}")
        return cls(
            asset_ctx.version,
            width,
            height,
            border_width,
            borders,
            area,
            min_height,
            max_height,
            elevations,
            asset_ctx.start_pos,
            asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext") -> None:
        with context.write_asset(self.asset_name, self.version):
            context.stream.writeUInt32(self.width)
            context.stream.writeUInt32(self.height)
            context.stream.writeUInt32(self.border_width)

            context.stream.writeUInt32(len(self.borders))
            for border in self.borders:
                border.write(context, self.version)

            context.stream.writeUInt32(self.area)

            for y in range(self.height):
                for x in range(self.width):
                    flipped_y = self.height - 1 - y
                    elevation = self.elevations[flipped_y][x]
                    if self.version >= 5:
                        context.stream.writeUInt16(elevation)
                    else:
                        context.stream.writeUChar(elevation)
