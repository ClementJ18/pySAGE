from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, cast

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext


@dataclass
class RiverArea:
    asset_name = "RiverArea"

    version: int
    unique_id: int
    name: str
    layer_name: str
    uv_scroll_speed: float
    use_additive_blending: bool
    river_texture: str
    noise_texture: str
    alpha_edge_texture: str
    sparkle_texture: str
    color: tuple[int, int, int]
    unused_color_a: int
    alpha: float
    water_height: int
    river_type: str | None
    minimum_water_lod: str
    lines: list[tuple[tuple[float, float], tuple[float, float]]]

    @classmethod
    def parse(cls, context: "ParsingContext", version: int) -> Self:
        unique_id = context.stream.readUInt32()
        name = context.stream.readUInt16PrefixedAsciiString()
        layer_name = context.stream.readUInt16PrefixedAsciiString()
        uv_scroll_speed = context.stream.readFloat()
        use_additive_blending = context.stream.readBool()
        river_texture = context.stream.readUInt16PrefixedAsciiString()
        noise_texture = context.stream.readUInt16PrefixedAsciiString()
        alpha_edge_texture = context.stream.readUInt16PrefixedAsciiString()
        sparkle_texture = context.stream.readUInt16PrefixedAsciiString()
        color = (
            context.stream.readUChar(),
            context.stream.readUChar(),
            context.stream.readUChar(),
        )

        unused_color_a = context.stream.readUChar()
        if unused_color_a != 0:
            raise ValueError(f"Expected unused color alpha to be 0, got {unused_color_a}")

        alpha = context.stream.readFloat()
        water_height = context.stream.readUInt32()

        river_type = None
        if version >= 3:
            river_type = context.stream.readUInt16PrefixedAsciiString()

        minimum_water_lod = context.stream.readUInt16PrefixedAsciiString()

        lines_count = context.stream.readUInt32()
        lines = []

        for _ in range(lines_count):
            lines.append((context.stream.readVector2(), context.stream.readVector2()))

        return cls(
            version=version,
            unique_id=unique_id,
            name=name,
            layer_name=layer_name,
            uv_scroll_speed=uv_scroll_speed,
            use_additive_blending=use_additive_blending,
            river_texture=river_texture,
            noise_texture=noise_texture,
            alpha_edge_texture=alpha_edge_texture,
            sparkle_texture=sparkle_texture,
            color=color,
            unused_color_a=unused_color_a,
            alpha=alpha,
            water_height=water_height,
            river_type=river_type,
            minimum_water_lod=minimum_water_lod,
            lines=lines,
        )

    def write(self, context: "WritingContext") -> None:
        context.stream.writeUInt32(self.unique_id)
        context.stream.writeUInt16PrefixedAsciiString(self.name)
        context.stream.writeUInt16PrefixedAsciiString(self.layer_name)
        context.stream.writeFloat(self.uv_scroll_speed)
        context.stream.writeBool(self.use_additive_blending)
        context.stream.writeUInt16PrefixedAsciiString(self.river_texture)
        context.stream.writeUInt16PrefixedAsciiString(self.noise_texture)
        context.stream.writeUInt16PrefixedAsciiString(self.alpha_edge_texture)
        context.stream.writeUInt16PrefixedAsciiString(self.sparkle_texture)
        context.stream.writeUChar(self.color[0])
        context.stream.writeUChar(self.color[1])
        context.stream.writeUChar(self.color[2])
        context.stream.writeUChar(self.unused_color_a)
        context.stream.writeFloat(self.alpha)
        context.stream.writeUInt32(self.water_height)

        if self.version >= 3:
            context.stream.writeUInt16PrefixedAsciiString(cast(str, self.river_type))

        context.stream.writeUInt16PrefixedAsciiString(self.minimum_water_lod)

        context.stream.writeUInt32(len(self.lines))
        for line in self.lines:
            context.stream.writeVector2(line[0])
            context.stream.writeVector2(line[1])


@dataclass
class RiverAreas:
    asset_name = "RiverAreas"

    version: int
    areas: list[RiverArea]
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        with context.read_asset() as asset_ctx:
            river_area_count = context.stream.readUInt32()
            areas = []
            for _ in range(river_area_count):
                areas.append(RiverArea.parse(context, asset_ctx.version))

        context.logger.debug(f"Finished parsing {cls.asset_name}")
        return cls(
            version=asset_ctx.version,
            areas=areas,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext") -> None:
        with context.write_asset(self.asset_name, self.version):
            context.stream.writeUInt32(len(self.areas))
            for area in self.areas:
                area.write(context)
