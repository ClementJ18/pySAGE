from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, cast

__all__ = [
    "RiverArea",
    "RiverAreas",
]

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
        unique_id = context.stream.read_uint32()
        name = context.stream.read_uint16_prefixed_ascii_string()
        layer_name = context.stream.read_uint16_prefixed_ascii_string()
        uv_scroll_speed = context.stream.read_float()
        use_additive_blending = context.stream.read_bool()
        river_texture = context.stream.read_uint16_prefixed_ascii_string()
        noise_texture = context.stream.read_uint16_prefixed_ascii_string()
        alpha_edge_texture = context.stream.read_uint16_prefixed_ascii_string()
        sparkle_texture = context.stream.read_uint16_prefixed_ascii_string()
        color = (
            context.stream.read_uchar(),
            context.stream.read_uchar(),
            context.stream.read_uchar(),
        )

        unused_color_a = context.stream.read_uchar()
        if unused_color_a != 0:
            raise ValueError(f"Expected unused color alpha to be 0, got {unused_color_a}")

        alpha = context.stream.read_float()
        water_height = context.stream.read_uint32()

        river_type = None
        if version >= 3:
            river_type = context.stream.read_uint16_prefixed_ascii_string()

        minimum_water_lod = context.stream.read_uint16_prefixed_ascii_string()

        lines_count = context.stream.read_uint32()
        lines = []

        for _ in range(lines_count):
            lines.append((context.stream.read_vector2(), context.stream.read_vector2()))

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
        context.stream.write_uint32(self.unique_id)
        context.stream.write_uint16_prefixed_ascii_string(self.name)
        context.stream.write_uint16_prefixed_ascii_string(self.layer_name)
        context.stream.write_float(self.uv_scroll_speed)
        context.stream.write_bool(self.use_additive_blending)
        context.stream.write_uint16_prefixed_ascii_string(self.river_texture)
        context.stream.write_uint16_prefixed_ascii_string(self.noise_texture)
        context.stream.write_uint16_prefixed_ascii_string(self.alpha_edge_texture)
        context.stream.write_uint16_prefixed_ascii_string(self.sparkle_texture)
        context.stream.write_uchar(self.color[0])
        context.stream.write_uchar(self.color[1])
        context.stream.write_uchar(self.color[2])
        context.stream.write_uchar(self.unused_color_a)
        context.stream.write_float(self.alpha)
        context.stream.write_uint32(self.water_height)

        if self.version >= 3:
            context.stream.write_uint16_prefixed_ascii_string(cast(str, self.river_type))

        context.stream.write_uint16_prefixed_ascii_string(self.minimum_water_lod)

        context.stream.write_uint32(len(self.lines))
        for line in self.lines:
            context.stream.write_vector2(line[0])
            context.stream.write_vector2(line[1])


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
            river_area_count = context.stream.read_uint32()
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
            context.stream.write_uint32(len(self.areas))
            for area in self.areas:
                area.write(context)
