from dataclasses import dataclass
from typing import TYPE_CHECKING

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
            position = context.stream.readVector3()
            scale = context.stream.readFloat()
            rotation = context.stream.readFloat()
            texture_scheme = context.stream.readUInt16PrefixedAsciiString()

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
            context.stream.writeVector3(self.position)
            context.stream.writeFloat(self.scale)
            context.stream.writeFloat(self.rotation)
            context.stream.writeUInt16PrefixedAsciiString(self.texture_scheme)
