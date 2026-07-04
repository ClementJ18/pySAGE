from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext


@dataclass
class PolygonTrigger:
    asset_name = "PolygonTrigger"

    name: str
    layer_name: str | None
    trigger_id: int
    is_water: bool
    is_river: bool
    river_start: bool | None
    river_texture: str | None
    noise_texture: str | None
    alpha_edge_texture: str | None
    sparkle_texture: str | None
    bump_map_texture: str | None
    sky_texture: str | None
    use_additive_blending: bool
    river_color: tuple[int, int, int] | None
    unknown: int | None
    uv_scroll_speed: tuple[float, float] | None
    river_alpha: float | None
    points: list[tuple[int, int, int]]

    @classmethod
    def parse(cls, context: "ParsingContext", version: int) -> Self:
        name = context.stream.readUInt16PrefixedAsciiString()

        layer_name = None
        if version >= 4:
            layer_name = context.stream.readUInt16PrefixedAsciiString()

        trigger_id = context.stream.readUInt32()

        is_water = False
        if version >= 2:
            is_water = context.stream.readBool()

        is_river = False
        river_start = None
        if version >= 3:
            is_river = context.stream.readBool()
            river_start = context.stream.readBoolUInt32()

        river_texture = None
        noise_texture = None
        alpha_edge_texture = None
        sparkle_texture = None
        bump_map_texture = None
        sky_texture = None
        use_additive_blending = False
        river_color = None
        unknown = None
        uv_scroll_speed = None
        river_alpha = None
        if version >= 5:
            river_texture = context.stream.readUInt16PrefixedAsciiString()
            noise_texture = context.stream.readUInt16PrefixedAsciiString()
            alpha_edge_texture = context.stream.readUInt16PrefixedAsciiString()
            sparkle_texture = context.stream.readUInt16PrefixedAsciiString()
            bump_map_texture = context.stream.readUInt16PrefixedAsciiString()
            sky_texture = context.stream.readUInt16PrefixedAsciiString()
            use_additive_blending = context.stream.readBool()
            river_color = (
                context.stream.readUChar(),
                context.stream.readUChar(),
                context.stream.readUChar(),
            )
            unknown = context.stream.readUChar()
            uv_scroll_speed = context.stream.readVector2()
            river_alpha = context.stream.readFloat()

        point_count = context.stream.readUInt32()
        points = []
        for _ in range(point_count):
            points.append(
                (
                    context.stream.readInt32(),
                    context.stream.readInt32(),
                    context.stream.readInt32(),
                )
            )

        return cls(
            name,
            layer_name,
            trigger_id,
            is_water,
            is_river,
            river_start,
            river_texture,
            noise_texture,
            alpha_edge_texture,
            sparkle_texture,
            bump_map_texture,
            sky_texture,
            use_additive_blending,
            river_color,
            unknown,
            uv_scroll_speed,
            river_alpha,
            points,
        )

    def write(self, context: "WritingContext", version: int) -> None:
        context.stream.writeUInt16PrefixedAsciiString(self.name)

        if version >= 4:
            # version >= 4 always reads layer_name, so parse leaves it non-None.
            assert self.layer_name is not None
            context.stream.writeUInt16PrefixedAsciiString(self.layer_name)

        context.stream.writeUInt32(self.trigger_id)

        if version >= 2:
            context.stream.writeBool(self.is_water)

        if version >= 3:
            assert self.river_start is not None
            context.stream.writeBool(self.is_river)
            context.stream.writeBoolUInt32(self.river_start)

        if version >= 5:
            # version >= 5 reads every field below, so parse leaves none of them None.
            assert self.river_texture is not None
            assert self.noise_texture is not None
            assert self.alpha_edge_texture is not None
            assert self.sparkle_texture is not None
            assert self.bump_map_texture is not None
            assert self.sky_texture is not None
            assert self.river_color is not None
            assert self.unknown is not None
            assert self.uv_scroll_speed is not None
            assert self.river_alpha is not None

            context.stream.writeUInt16PrefixedAsciiString(self.river_texture)
            context.stream.writeUInt16PrefixedAsciiString(self.noise_texture)
            context.stream.writeUInt16PrefixedAsciiString(self.alpha_edge_texture)
            context.stream.writeUInt16PrefixedAsciiString(self.sparkle_texture)
            context.stream.writeUInt16PrefixedAsciiString(self.bump_map_texture)
            context.stream.writeUInt16PrefixedAsciiString(self.sky_texture)
            context.stream.writeBool(self.use_additive_blending)

            context.stream.writeUChar(self.river_color[0])
            context.stream.writeUChar(self.river_color[1])
            context.stream.writeUChar(self.river_color[2])

            context.stream.writeUChar(self.unknown)
            context.stream.writeVector2(self.uv_scroll_speed)
            context.stream.writeFloat(self.river_alpha)

        context.stream.writeUInt32(len(self.points))
        for point in self.points:
            context.stream.writeInt32(point[0])
            context.stream.writeInt32(point[1])
            context.stream.writeInt32(point[2])


@dataclass
class PolygonTriggers:
    asset_name = "PolygonTriggers"

    version: int
    polygon_triggers: list[PolygonTrigger]
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        with context.read_asset() as asset_ctx:
            polygon_triggers = []

            trigger_count = context.stream.readUInt32()
            max_trigger_id = 0
            for _ in range(trigger_count):
                trigger = PolygonTrigger.parse(context, asset_ctx.version)
                polygon_triggers.append(trigger)

                if trigger.trigger_id > max_trigger_id:
                    max_trigger_id = trigger.trigger_id

        context.logger.debug(f"Finished parsing {cls.asset_name}")
        return cls(
            version=asset_ctx.version,
            polygon_triggers=polygon_triggers,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext") -> None:
        with context.write_asset(self.asset_name, self.version):
            context.stream.writeUInt32(len(self.polygon_triggers))
            for trigger in self.polygon_triggers:
                trigger.write(context, self.version)
