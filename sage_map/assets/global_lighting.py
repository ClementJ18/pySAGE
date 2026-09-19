"""The `GlobalLighting` chunk: the time of day, the lights for each time of day, and the settings
stored after them.

For the versions BFME2's WorldBuilder reads (up to 8), the layout follows its reader
(`GlobalLightingDataChunkParser::parse`, `0x00774170` in `worldbuilder.exe`). Each time of day
stores its lights as the terrain sun and the objects' sun (every version), the objects' two accents
(version 2 on), the terrain's two accents (version 3 on) and the infantry's sun and two accents
(version 4 on; before that WorldBuilder copies the objects' lights). After the four times of day
come the 2X overbright scale (version 5 on), the bloom flag and the infantry's bloom colour
(version 6 on), the terrain's and objects' bloom colours (version 7 on), the shadow colour when the
chunk has bytes left, and the no-cloud factor (version 8 on). Global Light Options edits them:
its slider handlers (`0x005098D0`) name the bloom rows by control id.

Versions 10 and later keep the terrain lights only; versions 9 and later store their other fields
in the order this module read before the BFME2 layout was decoded, which is kept unchanged.
"""

import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, cast

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext

Vector3 = tuple[float, float, float]

# The last version laid out as BFME2's WorldBuilder reads it.
_BFME2_LAST_VERSION = 8


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
    ambient: Vector3
    color: Vector3
    direction: Vector3

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


# The order of each version's lights, as attribute names.
def _light_order(version: int) -> tuple[str, ...]:
    if version >= 10:
        return ("terrain_sun", "terrain_accent1", "terrain_accent2")
    order: tuple[str, ...] = ("terrain_sun", "object_sun")
    if version >= 2:
        order += ("object_accent1", "object_accent2")
    if version >= 3:
        order += ("terrain_accent1", "terrain_accent2")
    if version >= 4:
        order += ("infantry_sun", "infantry_accent1", "infantry_accent2")
    return order


_LIGHTS = (
    "terrain_sun",
    "object_sun",
    "infantry_sun",
    "terrain_accent1",
    "object_accent1",
    "infantry_accent1",
    "terrain_accent2",
    "object_accent2",
    "infantry_accent2",
)


@dataclass
class GlobalLightingConfiguration:
    """One time of day's lights: a sun and two accents each for the terrain, for objects and for
    infantry. A light the chunk's version does not store is None."""

    terrain_sun: GlobalLight
    object_sun: GlobalLight | None
    infantry_sun: GlobalLight | None
    terrain_accent1: GlobalLight | None
    object_accent1: GlobalLight | None
    infantry_accent1: GlobalLight | None
    terrain_accent2: GlobalLight | None
    object_accent2: GlobalLight | None
    infantry_accent2: GlobalLight | None

    @classmethod
    def parse(cls, context: "ParsingContext", version: int) -> Self:
        lights: dict[str, GlobalLight | None] = dict.fromkeys(_LIGHTS)
        for name in _light_order(version):
            lights[name] = GlobalLight.parse(context)
        return cls(**lights)  # type: ignore[arg-type]

    def write(self, context: "WritingContext", version: int) -> None:
        for name in _light_order(version):
            cast(GlobalLight, getattr(self, name)).write(context)


@dataclass
class GlobalLighting:
    asset_name = "GlobalLighting"

    version: int
    time_of_the_day: TimeOfTheDay
    lighting_configurations: dict[TimeOfTheDay, GlobalLightingConfiguration]
    # Global Light Options' 2X overbright scale: 2.0 with it on, 1.0 off (versions 5-8).
    overbright: float | None
    # Enable Bloom Lighting Effect, stored as a 32-bit 0 or 1 (versions 6-8).
    bloom_enabled: int | None
    bloom_infantry: Vector3 | None
    bloom_terrain: Vector3 | None
    bloom_objects: Vector3 | None
    shadow_color: MapColorArgb | None
    # Versions 9 and 10: 4 bytes after the shadow colour, not decoded.
    unknown: bytes | None
    unknown2: Vector3 | None
    unknown3: MapColorArgb | None
    no_cloud_factor: Vector3 | None
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        with context.read_asset() as asset_ctx:
            version = asset_ctx.version
            time = TimeOfTheDay(context.stream.readUInt32())
            lighting_configurations = {}

            for member in TimeOfTheDay:
                lighting_configurations[member] = GlobalLightingConfiguration.parse(
                    context, version
                )

            overbright = None
            bloom_enabled = None
            bloom_infantry = bloom_terrain = bloom_objects = None
            shadow_color = None
            unknown = None
            unknown2 = None
            unknown3 = None
            if version <= _BFME2_LAST_VERSION:
                if version >= 5:
                    overbright = context.stream.readFloat()
                if version >= 6:
                    bloom_enabled = context.stream.readUInt32()
                    bloom_infantry = context.stream.readVector3()
                if version >= 7:
                    bloom_terrain = context.stream.readVector3()
                    bloom_objects = context.stream.readVector3()
                if context.stream.tell() < asset_ctx.end_pos:
                    shadow_color = MapColorArgb.parse(context)
            else:
                shadow_color = MapColorArgb.parse(context)
                if version < 11:
                    unknown = context.stream.readBytes(4)
                if version >= 12:
                    unknown2 = context.stream.readVector3()
                    unknown3 = MapColorArgb.parse(context)

            no_cloud_factor = None
            if version >= 8:
                no_cloud_factor = context.stream.readVector3()

        context.logger.debug(f"Finished parsing {cls.asset_name}")
        return cls(
            version=version,
            time_of_the_day=time,
            lighting_configurations=lighting_configurations,
            overbright=overbright,
            bloom_enabled=bloom_enabled,
            bloom_infantry=bloom_infantry,
            bloom_terrain=bloom_terrain,
            bloom_objects=bloom_objects,
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

            if self.version <= _BFME2_LAST_VERSION:
                if self.version >= 5:
                    context.stream.writeFloat(cast(float, self.overbright))
                if self.version >= 6:
                    context.stream.writeUInt32(cast(int, self.bloom_enabled))
                    context.stream.writeVector3(cast(Vector3, self.bloom_infantry))
                if self.version >= 7:
                    context.stream.writeVector3(cast(Vector3, self.bloom_terrain))
                    context.stream.writeVector3(cast(Vector3, self.bloom_objects))
                # Optional: parse reads it only when the chunk has bytes left.
                if self.shadow_color is not None:
                    self.shadow_color.write(context)
            else:
                cast(MapColorArgb, self.shadow_color).write(context)
                if self.version < 11:
                    context.stream.writeBytes(cast(bytes, self.unknown))
                if self.version >= 12:
                    context.stream.writeVector3(cast(Vector3, self.unknown2))
                    cast(MapColorArgb, self.unknown3).write(context)

            if self.version >= 8:
                context.stream.writeVector3(cast(Vector3, self.no_cloud_factor))
