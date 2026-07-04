from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext


@dataclass
class StandingWaveArea:
    asset_name = "StandingWaveArea"

    unique_id: int
    name: str
    layer_name: str
    uv_scroll_speed: float
    use_adaptive_blending: bool
    points: list[tuple[float, float]]
    unknown: int
    final_width: int | None
    final_height: int | None
    initial_width_fraction: int | None
    initial_height_fraction: int | None
    initial_velocity: int | None
    time_to_fade: int | None
    time_to_compress: int | None
    time_offset_2nd_wave: int | None
    distance_from_shore: int | None
    texture: str | None
    enable_pca_wave: bool | None
    wave_particle_fx_name: str | None

    @classmethod
    def parse(cls, context: "ParsingContext", version: int) -> Self:
        unique_id = context.stream.readUInt32()
        name = context.stream.readUInt16PrefixedAsciiString()
        layer_name = context.stream.readUInt16PrefixedAsciiString()
        uv_scroll_speed = context.stream.readFloat()
        use_adaptive_blending = context.stream.readBool()

        point_count = context.stream.readUInt32()
        points = []
        for _ in range(point_count):
            points.append(context.stream.readVector2())

        unknown = context.stream.readUInt32()
        if unknown != 0:
            raise ValueError(f"Expected unknown field to be 0, got {unknown}")

        final_width = None
        final_height = None
        initial_width_fraction = None
        initial_height_fraction = None
        initial_velocity = None
        time_to_fade = None
        time_to_compress = None
        time_offset_2nd_wave = None
        distance_from_shore = None
        texture = None
        if version < 3:
            final_width = context.stream.readUInt32()
            final_height = context.stream.readUInt32()
            initial_width_fraction = context.stream.readUInt32()
            initial_height_fraction = context.stream.readUInt32()
            initial_velocity = context.stream.readUInt32()
            time_to_fade = context.stream.readUInt32()
            time_to_compress = context.stream.readUInt32()
            time_offset_2nd_wave = context.stream.readUInt32()
            distance_from_shore = context.stream.readUInt32()
            texture = context.stream.readUInt16PrefixedAsciiString()

        enable_pca_wave = None
        if version == 2:
            enable_pca_wave = context.stream.readBoolUInt32()

        wave_particle_fx_name = None
        if version >= 4:
            wave_particle_fx_name = context.stream.readUInt16PrefixedAsciiString()

        return cls(
            unique_id=unique_id,
            name=name,
            layer_name=layer_name,
            uv_scroll_speed=uv_scroll_speed,
            use_adaptive_blending=use_adaptive_blending,
            points=points,
            unknown=unknown,
            final_width=final_width,
            final_height=final_height,
            initial_width_fraction=initial_width_fraction,
            initial_height_fraction=initial_height_fraction,
            initial_velocity=initial_velocity,
            time_to_fade=time_to_fade,
            time_to_compress=time_to_compress,
            time_offset_2nd_wave=time_offset_2nd_wave,
            distance_from_shore=distance_from_shore,
            texture=texture,
            enable_pca_wave=enable_pca_wave,
            wave_particle_fx_name=wave_particle_fx_name,
        )

    def write(self, context: "WritingContext", version: int) -> None:
        context.stream.writeUInt32(self.unique_id)
        context.stream.writeUInt16PrefixedAsciiString(self.name)
        context.stream.writeUInt16PrefixedAsciiString(self.layer_name)
        context.stream.writeFloat(self.uv_scroll_speed)
        context.stream.writeBool(self.use_adaptive_blending)

        context.stream.writeUInt32(len(self.points))
        for point in self.points:
            context.stream.writeVector2(point)

        context.stream.writeUInt32(self.unknown)

        if version < 3:
            # version < 3 reads every field below, so parse leaves none of them None.
            assert self.final_width is not None
            assert self.final_height is not None
            assert self.initial_width_fraction is not None
            assert self.initial_height_fraction is not None
            assert self.initial_velocity is not None
            assert self.time_to_fade is not None
            assert self.time_to_compress is not None
            assert self.time_offset_2nd_wave is not None
            assert self.distance_from_shore is not None
            assert self.texture is not None

            context.stream.writeUInt32(self.final_width)
            context.stream.writeUInt32(self.final_height)
            context.stream.writeUInt32(self.initial_width_fraction)
            context.stream.writeUInt32(self.initial_height_fraction)
            context.stream.writeUInt32(self.initial_velocity)
            context.stream.writeUInt32(self.time_to_fade)
            context.stream.writeUInt32(self.time_to_compress)
            context.stream.writeUInt32(self.time_offset_2nd_wave)
            context.stream.writeUInt32(self.distance_from_shore)
            context.stream.writeUInt16PrefixedAsciiString(self.texture)

        if version == 2:
            assert self.enable_pca_wave is not None
            context.stream.writeBoolUInt32(self.enable_pca_wave)

        if version >= 4:
            assert self.wave_particle_fx_name is not None
            context.stream.writeUInt16PrefixedAsciiString(self.wave_particle_fx_name)


@dataclass
class StandingWaveAreas:
    asset_name = "StandingWaveAreas"

    version: int
    areas: list[StandingWaveArea]
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        with context.read_asset() as asset_ctx:
            area_count = context.stream.readUInt32()
            areas = []

            for _ in range(area_count):
                areas.append(StandingWaveArea.parse(context, asset_ctx.version))

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
                area.write(context, self.version)
