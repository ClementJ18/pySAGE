import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, cast

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext


class TimeOfTheDay(enum.Enum):
    Morning = 1
    Afternoon = 2
    Evening = 3
    Night = 4

    def map_to_str(self) -> str:
        times = {
            TimeOfTheDay.Morning: "MORNING",
            TimeOfTheDay.Afternoon: "AFTERNOON",
            TimeOfTheDay.Evening: "EVENING",
            TimeOfTheDay.Night: "NIGHT",
        }

        return times[self]


@dataclass
class MapColorArgb:
    a: int
    r: int
    g: int
    b: int

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        value = context.stream.readUInt32()
        a = (value >> 24) & 0xFF
        r = (value >> 16) & 0xFF
        g = (value >> 8) & 0xFF
        b = value & 0xFF

        return cls(
            a=a,
            r=r,
            g=g,
            b=b,
        )

    def write(self, context: "WritingContext") -> None:
        value = (self.a << 24) | (self.r << 16) | (self.g << 8) | self.b
        context.stream.writeUInt32(value)


@dataclass
class GlobalLight:
    ambient: tuple[float, float, float]
    color: tuple[float, float, float]
    direction: tuple[float, float, float]

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        ambient = context.stream.readVector3()
        color = context.stream.readVector3()
        direction = context.stream.readVector3()

        return cls(
            ambient=ambient,
            color=color,
            direction=direction,
        )

    def write(self, context: "WritingContext") -> None:
        context.stream.writeVector3(self.ambient)
        context.stream.writeVector3(self.color)
        context.stream.writeVector3(self.direction)


@dataclass
class GlobalLightingConfiguration:
    terrain_sun: GlobalLight
    object_sun: GlobalLight | None
    infantry_sun: GlobalLight | None
    terrain_accent1: GlobalLight
    object_accent1: GlobalLight | None
    infantry_accent1: GlobalLight | None
    terrain_accent2: GlobalLight
    object_accent2: GlobalLight | None
    infantry_accent2: GlobalLight | None

    @classmethod
    def parse(cls, context: "ParsingContext", version: int) -> Self:
        terrain_sun = GlobalLight.parse(context)

        object_sun = None
        infantry_sun = None
        if version < 10:
            object_sun = GlobalLight.parse(context)

            if version >= 7:
                infantry_sun = GlobalLight.parse(context)

        terrain_accent1 = GlobalLight.parse(context)

        object_accent1 = None
        infantry_accent1 = None
        if version < 10:
            object_accent1 = GlobalLight.parse(context)

            if version >= 7:
                infantry_accent1 = GlobalLight.parse(context)

        terrain_accent2 = GlobalLight.parse(context)

        object_accent2 = None
        infantry_accent2 = None
        if version < 10:
            object_accent2 = GlobalLight.parse(context)

            if version >= 7:
                infantry_accent2 = GlobalLight.parse(context)

        return cls(
            terrain_sun=terrain_sun,
            object_sun=object_sun,
            infantry_sun=infantry_sun,
            terrain_accent1=terrain_accent1,
            object_accent1=object_accent1,
            infantry_accent1=infantry_accent1,
            terrain_accent2=terrain_accent2,
            object_accent2=object_accent2,
            infantry_accent2=infantry_accent2,
        )

    def write(self, context: "WritingContext", version: int) -> None:
        self.terrain_sun.write(context)

        if version < 10:
            cast(GlobalLight, self.object_sun).write(context)

            if version >= 7:
                cast(GlobalLight, self.infantry_sun).write(context)

        self.terrain_accent1.write(context)

        if version < 10:
            cast(GlobalLight, self.object_accent1).write(context)

            if version >= 7:
                cast(GlobalLight, self.infantry_accent1).write(context)

        self.terrain_accent2.write(context)

        if version < 10:
            cast(GlobalLight, self.object_accent2).write(context)

            if version >= 7:
                cast(GlobalLight, self.infantry_accent2).write(context)


@dataclass
class GlobalLighting:
    asset_name = "GlobalLighting"

    version: int
    time_of_the_day: TimeOfTheDay
    lighting_configurations: dict[TimeOfTheDay, GlobalLightingConfiguration]
    shadow_color: MapColorArgb
    unknown: bytes | None
    unknown2: tuple[float, float, float] | None
    unknown3: MapColorArgb | None
    no_cloud_factor: tuple[float, float, float] | None
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        with context.read_asset() as asset_ctx:
            time = TimeOfTheDay(context.stream.readUInt32())
            lighting_configurations = {}

            for member in TimeOfTheDay:
                lighting_configurations[member] = GlobalLightingConfiguration.parse(
                    context, asset_ctx.version
                )

            shadow_color = MapColorArgb.parse(context)

            unknown = None
            if asset_ctx.version >= 7 and asset_ctx.version < 11:
                unknown = context.stream.readBytes(4 if asset_ctx.version >= 9 else 44)

            unknown2 = None
            unknown3 = None
            if asset_ctx.version >= 12:
                unknown2 = context.stream.readVector3()
                unknown3 = MapColorArgb.parse(context)

            no_cloud_factor = None
            if asset_ctx.version >= 8:
                no_cloud_factor = context.stream.readVector3()

        context.logger.debug(f"Finished parsing {cls.asset_name}")
        return cls(
            version=asset_ctx.version,
            time_of_the_day=time,
            lighting_configurations=lighting_configurations,
            shadow_color=shadow_color,
            unknown=unknown,
            unknown2=unknown2,
            unknown3=unknown3,
            no_cloud_factor=no_cloud_factor,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext") -> None:
        with context.write_asset(self.asset_name, self.version):
            context.stream.writeUInt32(self.time_of_the_day.value)

            for member in TimeOfTheDay:
                config = self.lighting_configurations[member]
                config.write(context, self.version)

            self.shadow_color.write(context)

            if self.version >= 7 and self.version < 11:
                context.stream.writeBytes(cast(bytes, self.unknown))

            if self.version >= 12:
                context.stream.writeVector3(cast(tuple[float, float, float], self.unknown2))
                cast(MapColorArgb, self.unknown3).write(context)

            if self.version >= 8:
                context.stream.writeVector3(cast(tuple[float, float, float], self.no_cloud_factor))
