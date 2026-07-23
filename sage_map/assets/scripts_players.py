from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from ..context import ParsingContext, Property, WritingContext


@dataclass
class ScriptPlayer:
    """One player slot in a `.scb`'s `ScriptsPlayers` asset. `properties` is `None` exactly when
    the enclosing asset's `has_properties` is unset - WorldBuilder's "export selected scripts"
    mode writes a single pseudo-player named `**SELECTION**` with no property bag at all, while
    "export all" (`has_properties` set) writes every real player with its full bag."""

    name: str
    properties: dict[str, "Property"] | None

    @classmethod
    def parse(cls, context: "ParsingContext", has_properties: bool) -> Self:
        name = context.stream.readUInt16PrefixedAsciiString()
        properties = None
        if has_properties:
            properties = context.properties_to_dict(context.parse_properties())

        return cls(name=name, properties=properties)

    def write(self, context: "WritingContext", has_properties: bool) -> None:
        context.stream.writeUInt16PrefixedAsciiString(self.name)
        if has_properties:
            if self.properties is None:
                raise ValueError("player properties must be set when has_properties is set")
            context.write_properties(context.dict_to_properties(self.properties))
        elif self.properties is not None:
            raise ValueError("player properties must be None when has_properties is unset")


@dataclass
class ScriptsPlayers:
    """A `.scb`-only asset: the players a script library was exported for. `has_properties` is
    stored as the raw int read (0 or 1), not coerced to bool, so a byte-exact rewrite does not
    depend on guessing the original encoding."""

    asset_name = "ScriptsPlayers"

    version: int
    has_properties: int
    players: list[ScriptPlayer]
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        with context.read_asset() as asset_ctx:
            has_properties = context.stream.readUInt32()
            player_count = context.stream.readUInt32()
            players = []
            for _ in range(player_count):
                players.append(ScriptPlayer.parse(context, has_properties != 0))

        context.logger.debug(f"Finished parsing {cls.asset_name}")
        return cls(
            version=asset_ctx.version,
            has_properties=has_properties,
            players=players,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext") -> None:
        with context.write_asset(self.asset_name, self.version):
            context.stream.writeUInt32(self.has_properties)
            context.stream.writeUInt32(len(self.players))
            for player in self.players:
                player.write(context, self.has_properties != 0)
