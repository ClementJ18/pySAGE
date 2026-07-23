from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from .teams import Team

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext


@dataclass
class ScriptTeams:
    """A `.scb`-only asset: the map's teams re-exported for WorldBuilder's script library. Unlike
    the map's `Teams` asset, there is no leading count - the payload is a plain sequence of `Team`
    property bags read until the asset's datasize is exhausted (empty payload = no teams)."""

    asset_name = "ScriptTeams"

    version: int
    teams: list[Team]
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        with context.read_asset() as asset_ctx:
            teams = []
            while context.stream.tell() < asset_ctx.end_pos:
                teams.append(Team.parse(context))

        context.logger.debug(f"Finished parsing {cls.asset_name}")
        return cls(
            version=asset_ctx.version,
            teams=teams,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext") -> None:
        with context.write_asset(self.asset_name, self.version):
            for team in self.teams:
                team.write(context)
