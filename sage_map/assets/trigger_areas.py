from dataclasses import dataclass
from typing import TYPE_CHECKING

__all__ = [
    "TriggerArea",
    "TriggerAreas",
]

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext


@dataclass
class TriggerArea:
    asset_name = "TriggerArea"

    name: str
    layer_name: str
    area_id: int
    points: list[tuple[float, float]]
    unknown2: int

    @classmethod
    def parse(cls, context: "ParsingContext"):
        name = context.stream.read_uint16_prefixed_ascii_string()
        layer_name = context.stream.read_uint16_prefixed_ascii_string()
        area_id = context.stream.read_uint32()

        point_count = context.stream.read_uint32()
        points = []
        for _ in range(point_count):
            points.append(context.stream.read_vector2())

        unknown2 = context.stream.read_uint32()
        if unknown2 != 0:
            raise ValueError("Invalid data in 'unknown2'")

        return cls(
            name=name,
            layer_name=layer_name,
            area_id=area_id,
            points=points,
            unknown2=unknown2,
        )

    def write(self, context: "WritingContext"):
        context.stream.write_uint16_prefixed_ascii_string(self.name)
        context.stream.write_uint16_prefixed_ascii_string(self.layer_name)
        context.stream.write_uint32(self.area_id)

        context.stream.write_uint32(len(self.points))
        for point in self.points:
            context.stream.write_vector2(point)

        context.stream.write_uint32(self.unknown2)


@dataclass
class TriggerAreas:
    asset_name = "TriggerAreas"

    version: int
    trigger_areas: list[TriggerArea]
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext"):
        with context.read_asset() as asset_ctx:
            trigger_areas = []
            area_count = context.stream.read_uint32()
            for _ in range(area_count):
                trigger_areas.append(TriggerArea.parse(context))

        context.logger.debug(f"Finished parsing {cls.asset_name}")
        return cls(
            version=asset_ctx.version,
            trigger_areas=trigger_areas,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext"):
        with context.write_asset(self.asset_name, self.version):
            context.stream.write_uint32(len(self.trigger_areas))
            for area in self.trigger_areas:
                area.write(context)
