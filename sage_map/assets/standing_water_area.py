from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

__all__ = [
    "StandingWaterArea",
    "StandingWaterAreas",
]

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext


@dataclass
class StandingWaterArea:
    asset_name = "StandingWaterArea"

    unique_id: int
    name: str
    layer_name: str
    uv_scroll_speed: float
    use_adaptive_blending: bool
    bump_map_texture: str
    sky_texture: str
    points: list[tuple[float, float]]
    water_height: int
    fx_shader: str
    depth_color: str

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        unique_id = context.stream.read_uint32()
        name = context.stream.read_uint16_prefixed_ascii_string()
        layer_name = context.stream.read_uint16_prefixed_ascii_string()
        uv_scroll_speed = context.stream.read_float()
        use_adaptive_blending = context.stream.read_bool()
        bump_map_texture = context.stream.read_uint16_prefixed_ascii_string()
        sky_texture = context.stream.read_uint16_prefixed_ascii_string()

        point_count = context.stream.read_uint32()
        points = []
        for _ in range(point_count):
            points.append(context.stream.read_vector2())

        water_height = context.stream.read_uint32()
        fx_shader = context.stream.read_uint16_prefixed_ascii_string()
        depth_color = context.stream.read_uint16_prefixed_ascii_string()

        return cls(
            unique_id=unique_id,
            name=name,
            layer_name=layer_name,
            uv_scroll_speed=uv_scroll_speed,
            use_adaptive_blending=use_adaptive_blending,
            bump_map_texture=bump_map_texture,
            sky_texture=sky_texture,
            points=points,
            water_height=water_height,
            fx_shader=fx_shader,
            depth_color=depth_color,
        )

    def write(self, context: "WritingContext") -> None:
        context.stream.write_uint32(self.unique_id)
        context.stream.write_uint16_prefixed_ascii_string(self.name)
        context.stream.write_uint16_prefixed_ascii_string(self.layer_name)
        context.stream.write_float(self.uv_scroll_speed)
        context.stream.write_bool(self.use_adaptive_blending)
        context.stream.write_uint16_prefixed_ascii_string(self.bump_map_texture)
        context.stream.write_uint16_prefixed_ascii_string(self.sky_texture)

        context.stream.write_uint32(len(self.points))
        for point in self.points:
            context.stream.write_vector2(point)

        context.stream.write_uint32(self.water_height)
        context.stream.write_uint16_prefixed_ascii_string(self.fx_shader)
        context.stream.write_uint16_prefixed_ascii_string(self.depth_color)


@dataclass
class StandingWaterAreas:
    asset_name = "StandingWaterAreas"

    version: int
    areas: list[StandingWaterArea]
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        with context.read_asset() as asset_ctx:
            area_count = context.stream.read_uint32()
            areas = []

            for _ in range(area_count):
                areas.append(StandingWaterArea.parse(context))

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
