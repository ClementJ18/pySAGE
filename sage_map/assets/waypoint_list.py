from dataclasses import dataclass
from typing import Self

from ..context import ParsingContext, WritingContext

__all__ = [
    "WaypointsList",
]


@dataclass
class WaypointsList:
    asset_name = "WaypointsList"

    version: int
    waypoint_paths: list[tuple[int, int]]
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        with context.read_asset() as asset_ctx:
            waypoint_paths = []
            waypoint_count = context.stream.read_uint32()
            for _ in range(waypoint_count):
                start_waypoint_id = context.stream.read_uint32()
                end_waypoint_id = context.stream.read_uint32()

                waypoint_paths.append((start_waypoint_id, end_waypoint_id))

        context.logger.debug(f"Finished parsing {cls.asset_name}")
        return cls(
            version=asset_ctx.version,
            waypoint_paths=waypoint_paths,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext") -> None:
        with context.write_asset(self.asset_name, self.version):
            context.stream.write_uint32(len(self.waypoint_paths))
            for start_id, end_id in self.waypoint_paths:
                context.stream.write_uint32(start_id)
                context.stream.write_uint32(end_id)
