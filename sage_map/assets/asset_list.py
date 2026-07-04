from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext


@dataclass
class AssetListItem:
    type_id: int
    instance_id: int

    @classmethod
    def parse(cls, context: "ParsingContext"):
        type_id = context.stream.readUInt32()
        instance_id = context.stream.readUInt32()

        context.logger.debug(
            f"Parsed AssetListItem: Type ID: {type_id}, Instance ID: {instance_id}"
        )
        return cls(
            type_id=type_id,
            instance_id=instance_id,
        )

    def write(self, context: "WritingContext"):
        context.stream.writeUInt32(self.type_id)
        context.stream.writeUInt32(self.instance_id)


@dataclass
class AssetList:
    asset_name = "AssetList"

    version: int
    asset_names: list[AssetListItem]
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext"):
        with context.read_asset() as asset_ctx:
            asset_count = context.stream.readUInt32()
            asset_names = [AssetListItem.parse(context) for _ in range(asset_count)]

        context.logger.debug(f"Finished parsing {cls.asset_name}")
        return cls(
            version=asset_ctx.version,
            asset_names=asset_names,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext"):
        with context.write_asset(self.asset_name, self.version):
            context.stream.writeUInt32(len(self.asset_names))
            for item in self.asset_names:
                item.write(context)
