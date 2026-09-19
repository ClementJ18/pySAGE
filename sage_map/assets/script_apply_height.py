from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext


@dataclass
class ScriptApplyHeight:
    """A `.scb`-only asset, written between an export's `HeightMapData` and `BlendTileData`:
    whether an import applies the exported heights (Export Options "Include terrain height"), or
    only the textures (`0x005350F3` writes it, `0x0053C040` reads it)."""

    asset_name = "ScriptApplyHeight"

    version: int
    apply_height: bool
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        with context.read_asset() as asset_ctx:
            apply_height = context.stream.readBool()

        return cls(
            version=asset_ctx.version,
            apply_height=apply_height,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext") -> None:
        with context.write_asset(self.asset_name, self.version):
            context.stream.writeBool(self.apply_height)
