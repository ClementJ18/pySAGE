from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import ParsingContext, Property, WritingContext


@dataclass
class Team:
    properties: dict[str, "Property"]

    @classmethod
    def parse(cls, context: "ParsingContext"):
        properties = context.properties_to_dict(context.parse_properties())
        context.logger.debug(f"Parsed Team with properties: {properties}")
        return cls(
            properties=properties,
        )

    def write(self, context: "WritingContext"):
        context.write_properties(context.dict_to_properties(self.properties))


@dataclass
class Teams:
    asset_name = "Teams"

    version: int
    teams: list[Team]
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext"):
        with context.read_asset() as asset_ctx:
            teams = []
            team_count = context.stream.readUInt32()
            for _ in range(team_count):
                teams.append(Team.parse(context))

        context.logger.debug(f"Finished parsing {cls.asset_name}")
        return cls(
            version=asset_ctx.version,
            teams=teams,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext"):
        with context.write_asset(self.asset_name, self.version):
            context.stream.writeUInt32(len(self.teams))
            for team in self.teams:
                team.write(context)
