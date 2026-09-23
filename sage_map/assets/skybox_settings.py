from dataclasses import dataclass
from typing import TYPE_CHECKING

__all__ = [
    "SkyboxSettings",
]

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext


@dataclass
class SkyboxSettings:
    asset_name = "SkyboxSettings"

    version: int
    position: tuple[float, float, float]
    scale: float
    rotation: float
    texture_scheme: str
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext"):
        with context.read_asset() as asset_ctx:
            position = context.stream.read_vector3()
            scale = context.stream.read_float()
            rotation = context.stream.read_float()
            texture_scheme = context.stream.read_uint16_prefixed_ascii_string()

        return cls(
            version=asset_ctx.version,
            position=position,
            scale=scale,
            rotation=rotation,
            texture_scheme=texture_scheme,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext"):
        with context.write_asset(self.asset_name, self.version):
            context.stream.write_vector3(self.position)
            context.stream.write_float(self.scale)
            context.stream.write_float(self.rotation)
            context.stream.write_uint16_prefixed_ascii_string(self.texture_scheme)
