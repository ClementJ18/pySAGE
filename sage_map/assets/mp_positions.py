from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext


@dataclass
class MPPosition:
    asset_name = "MPPositionInfo"

    version: int
    is_human: bool
    is_computer: bool
    load_ai_script: bool
    team: int
    side_restrictions: list[str]
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext"):
        with context.read_asset() as asset_ctx:
            is_human = context.stream.readBool()
            is_computer = context.stream.readBool()
            load_ai_script = False
            if asset_ctx.version > 0:
                load_ai_script = context.stream.readBool()

            team = context.stream.readUInt32()
            side_restrictions = []
            if asset_ctx.version > 0:
                side_restriction_count = context.stream.readUInt32()
                for _ in range(side_restriction_count):
                    side_restrictions.append(context.stream.readUInt16PrefixedAsciiString())

        context.logger.debug(f"Finished parsing {cls.asset_name}")
        return cls(
            asset_ctx.version,
            is_human,
            is_computer,
            load_ai_script,
            team,
            side_restrictions,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext"):
        with context.write_asset(self.asset_name, self.version):
            context.stream.writeBool(self.is_human)
            context.stream.writeBool(self.is_computer)
            if self.version > 0:
                context.stream.writeBool(self.load_ai_script)

            context.stream.writeUInt32(self.team)
            if self.version > 0:
                context.stream.writeUInt32(len(self.side_restrictions))
                for restriction in self.side_restrictions:
                    context.stream.writeUInt16PrefixedAsciiString(restriction)


@dataclass
class MPPositionList:
    asset_name = "MPPositionList"

    version: int
    positions: list[MPPosition]
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext"):
        with context.read_asset() as asset_ctx:
            positions = []
            while context.stream.tell() < asset_ctx.end_pos:
                name = context.parse_asset_name()
                if name != MPPosition.asset_name:
                    raise ValueError(f"Expected {MPPosition.asset_name} asset, got {name}")

                positions.append(MPPosition.parse(context))

        context.logger.debug(f"Finished parsing {cls.asset_name}")
        return cls(
            version=asset_ctx.version,
            positions=positions,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext"):
        with context.write_asset(self.asset_name, self.version):
            for position in self.positions:
                context.write_asset_name(position.asset_name)
                position.write(context)
