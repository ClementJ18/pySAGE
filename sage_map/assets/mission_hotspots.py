from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext


@dataclass
class MissionHotSpot:
    id: str
    title: str
    description: str

    @classmethod
    def parse(cls, context: "ParsingContext"):
        id = context.stream.readUInt16PrefixedAsciiString()
        title = context.stream.readUInt16PrefixedAsciiString()
        description = context.stream.readUInt16PrefixedAsciiString()

        return cls(
            id=id,
            title=title,
            description=description,
        )

    def write(self, context: "WritingContext"):
        context.stream.writeUInt16PrefixedAsciiString(self.id)
        context.stream.writeUInt16PrefixedAsciiString(self.title)
        context.stream.writeUInt16PrefixedAsciiString(self.description)


@dataclass
class MissionHotSpots:
    asset_name = "MissionHotSpots"

    version: int
    mission_hotspots: list[MissionHotSpot]
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext"):
        with context.read_asset() as asset_ctx:
            mission_hotspots_count = context.stream.readUInt32()
            mission_hotspots = []
            for _ in range(mission_hotspots_count):
                mission_hotspots.append(MissionHotSpot.parse(context))

        return cls(
            version=asset_ctx.version,
            mission_hotspots=mission_hotspots,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext"):
        with context.write_asset(self.asset_name, self.version):
            context.stream.writeUInt32(len(self.mission_hotspots))
            for hotspot in self.mission_hotspots:
                hotspot.write(context)
