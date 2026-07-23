from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext


@dataclass
class ScriptImportSize:
    """A `.scb`-only asset: the WorldBuilder "Export Scripts" dialog's persisted size. Not
    load-sourced from anything the game reads back - values seen across fixtures range from
    (1, 1) to (560, 410)."""

    asset_name = "ScriptImportSize"

    version: int
    width: int
    height: int
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        with context.read_asset() as asset_ctx:
            width = context.stream.readUInt32()
            height = context.stream.readUInt32()

        context.logger.debug(f"Finished parsing {cls.asset_name}")
        return cls(
            version=asset_ctx.version,
            width=width,
            height=height,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext") -> None:
        with context.write_asset(self.asset_name, self.version):
            context.stream.writeUInt32(self.width)
            context.stream.writeUInt32(self.height)
