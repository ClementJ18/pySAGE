from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext


@dataclass
class WaterSettings:
    asset_name = "GlobalWaterSettings"

    version: int
    reflection_on: bool
    reflection_plane_z: float
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext"):
        with context.read_asset() as asset_ctx:
            reflection_on = context.stream.read_bool()
            reflection_plane_z = context.stream.read_float()

        context.logger.debug(f"Finished parsing {cls.asset_name}")
        return cls(
            asset_ctx.version,
            reflection_on,
            reflection_plane_z,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext"):
        with context.write_asset(self.asset_name, self.version):
            context.stream.write_bool(self.reflection_on)
            context.stream.write_float(self.reflection_plane_z)
