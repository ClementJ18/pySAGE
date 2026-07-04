from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, cast

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext


@dataclass
class EnvironmentData:
    asset_name = "EnvironmentData"

    version: int
    water_max_alpha_depth: float | None
    deep_water_alpha: float | None
    is_macro_texture_stretched: bool | None
    macro_texture: str
    cloud_texture: str
    unknown_texture: str | None
    unknown_texture2: str | None
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        with context.read_asset() as asset_ctx:
            water_max_alpha_depth = None
            deep_water_alpha = None
            if asset_ctx.version >= 3:
                water_max_alpha_depth = context.stream.readFloat()
                deep_water_alpha = context.stream.readFloat()

            is_macro_texture_stretched = None
            if asset_ctx.version < 5:
                is_macro_texture_stretched = context.stream.readBool()

            macro_texture = context.stream.readUInt16PrefixedAsciiString()
            cloud_texture = context.stream.readUInt16PrefixedAsciiString()

            unknown_texture = None
            if asset_ctx.version >= 4:
                unknown_texture = context.stream.readUInt16PrefixedAsciiString()

            unknown_texture2 = None
            if asset_ctx.version >= 6 and context.stream.tell() < asset_ctx.end_pos:
                unknown_texture2 = context.stream.readUInt16PrefixedAsciiString()

        context.logger.debug(f"Finished parsing {cls.asset_name}")
        return cls(
            version=asset_ctx.version,
            water_max_alpha_depth=water_max_alpha_depth,
            deep_water_alpha=deep_water_alpha,
            is_macro_texture_stretched=is_macro_texture_stretched,
            macro_texture=macro_texture,
            cloud_texture=cloud_texture,
            unknown_texture=unknown_texture,
            unknown_texture2=unknown_texture2,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext") -> None:
        with context.write_asset(self.asset_name, self.version):
            if self.version >= 3:
                context.stream.writeFloat(cast(float, self.water_max_alpha_depth))
                context.stream.writeFloat(cast(float, self.deep_water_alpha))

            if self.version < 5:
                context.stream.writeBool(cast(bool, self.is_macro_texture_stretched))

            context.stream.writeUInt16PrefixedAsciiString(self.macro_texture)
            context.stream.writeUInt16PrefixedAsciiString(self.cloud_texture)

            if self.version >= 4:
                context.stream.writeUInt16PrefixedAsciiString(cast(str, self.unknown_texture))

            if self.version >= 6:
                context.stream.writeUInt16PrefixedAsciiString(cast(str, self.unknown_texture2))
