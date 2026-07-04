from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self, cast

from ..context import AssetPropertyType, Property
from .teams import Team

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext


@dataclass
class BuildListInfo:
    build_name: str
    template_name: str
    location: tuple[float, float, float]
    angle: float
    is_initially_built: bool
    num_rebuilds: int
    script: str
    health: int
    whiner: bool
    unsellable: bool
    repairable: bool
    unknown: bool | None = None

    @classmethod
    def parse(cls, context: "ParsingContext", version: int, has_asset_list: bool) -> Self:
        build_name = context.stream.readUInt16PrefixedAsciiString()
        template_name = context.stream.readUInt16PrefixedAsciiString()
        location = context.stream.readVector3()
        angle = context.stream.readFloat()
        is_initially_built = context.stream.readBool()

        unknown = None
        if version >= 6 and has_asset_list:
            unknown = context.stream.readBool()

        num_rebuilds = context.stream.readUInt32()
        script = context.stream.readUInt16PrefixedAsciiString()
        health = context.stream.readInt32()
        whiner = context.stream.readBool()
        unsellable = context.stream.readBool()
        repairable = context.stream.readBool()

        context.logger.debug(
            f"BuildListItem: {build_name}, Template: {template_name}, Health: {health}"
        )

        return cls(
            build_name=build_name,
            template_name=template_name,
            location=location,
            angle=angle,
            is_initially_built=is_initially_built,
            num_rebuilds=num_rebuilds,
            script=script,
            health=health,
            whiner=whiner,
            unsellable=unsellable,
            repairable=repairable,
            unknown=unknown,
        )

    def write(self, context: "WritingContext", has_asset_list: bool) -> None:
        context.stream.writeUInt16PrefixedAsciiString(self.build_name)
        context.stream.writeUInt16PrefixedAsciiString(self.template_name)
        context.stream.writeVector3(self.location)
        context.stream.writeFloat(self.angle)
        context.stream.writeBool(self.is_initially_built)

        if has_asset_list and self.unknown is not None:
            context.stream.writeBool(self.unknown)

        context.stream.writeUInt32(self.num_rebuilds)
        context.stream.writeUInt16PrefixedAsciiString(self.script)
        context.stream.writeInt32(self.health)
        context.stream.writeBool(self.whiner)
        context.stream.writeBool(self.unsellable)
        context.stream.writeBool(self.repairable)


@dataclass
class BuildList:
    asset_name = "BuildList"

    faction_name: str | None
    faction_name_property: tuple[AssetPropertyType, int, str | None] | None
    build_list: list[BuildListInfo]

    @classmethod
    def parse(cls, context: "ParsingContext", version: int, has_asset_list: bool) -> Self:
        faction_name = None
        faction_name_property = None
        if has_asset_list:
            faction_name = context.stream.readUInt16PrefixedAsciiString()
        else:
            faction_name_property = context.parse_asset_property_key()

        build_list = []
        build_list_count = context.stream.readUInt32()
        for _ in range(build_list_count):
            build_list.append(BuildListInfo.parse(context, version, has_asset_list))

        context.logger.debug(
            f"Parsed BuildList with {len(build_list)} items "
            f"for faction '{faction_name or faction_name_property}'"
        )
        return cls(
            faction_name=faction_name,
            faction_name_property=faction_name_property,
            build_list=build_list,
        )

    def write(self, context: "WritingContext", has_asset_list: bool) -> None:
        if has_asset_list:
            context.stream.writeUInt16PrefixedAsciiString(cast(str, self.faction_name))
        else:
            if self.faction_name_property is None:
                raise ValueError("faction_name_property must be set when has_asset_list is False")
            key_type, key_index, key_name = self.faction_name_property
            if key_name is None:
                raise ValueError("faction_name_property name must be set")
            context.write_asset_property_key((key_type, key_index, key_name))

        context.stream.writeUInt32(len(self.build_list))
        for item in self.build_list:
            item.write(context, has_asset_list)


@dataclass
class BuildLists:
    asset_name = "BuildLists"

    version: int
    build_lists: list[BuildList]
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext", has_asset_list: bool) -> Self:
        with context.read_asset() as asset_ctx:
            build_list_count = context.stream.readUInt32()
            build_lists = []
            for _ in range(build_list_count):
                item = BuildList.parse(context, asset_ctx.version, has_asset_list)
                build_lists.append(item)

        context.logger.debug("Finished parsing BuildLists")
        return cls(
            version=asset_ctx.version,
            build_lists=build_lists,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext", has_asset_list: bool) -> None:
        with context.write_asset(self.asset_name, self.version):
            context.stream.writeUInt32(len(self.build_lists))
            for item in self.build_lists:
                item.write(context, has_asset_list)


@dataclass
class Player:
    properties: dict[str, Property]
    build_list_items: dict[str, BuildListInfo]

    @classmethod
    def parse(cls, context: "ParsingContext", version: int, has_asset_list: bool) -> Self:
        properties = context.properties_to_dict(context.parse_properties())

        build_list_count = context.stream.readUInt32()
        build_lists = {}
        for _ in range(build_list_count):
            item = BuildListInfo.parse(context, version, has_asset_list)
            build_lists[item.build_name] = item

        context.logger.debug(f"Parsed Side with {len(build_lists)} build list items")

        return cls(
            properties=properties,
            build_list_items=build_lists,
        )

    def write(self, context: "WritingContext", has_asset_list: bool) -> None:
        context.write_properties(context.dict_to_properties(self.properties))
        context.stream.writeUInt32(len(self.build_list_items))
        for item in self.build_list_items.values():
            item.write(context, has_asset_list)


@dataclass
class SidesList:
    asset_name = "SidesList"

    version: int
    unknown1: bool
    players: list[Player]
    start_pos: int
    end_pos: int
    teams: list[Team] = field(default_factory=list)

    @classmethod
    def parse(cls, context: "ParsingContext", has_asset_list: bool) -> Self:
        with context.read_asset() as asset_ctx:
            unknown1 = False
            if asset_ctx.version >= 6:
                unknown1 = context.stream.readBool()

            player_count = context.stream.readUInt32()
            players = []
            for _ in range(player_count):
                players.append(Player.parse(context, asset_ctx.version, has_asset_list))

            if asset_ctx.version >= 5:
                teams: list[Team] = []
            else:
                teams = []
                if asset_ctx.version >= 2:
                    team_count = context.stream.readUInt32()
                    for _ in range(team_count):
                        teams.append(Team.parse(context))

                while context.stream.tell() < asset_ctx.end_pos:
                    asset_name = context.parse_asset_name()
                    if asset_name == "Team":
                        raise ValueError("Unexpected Team asset in SidesList")
                    else:
                        raise ValueError(f"Unexpected asset in {cls.asset_name}: {asset_name}")

        context.logger.debug(f"Finished parsing {cls.asset_name}")
        return cls(
            version=asset_ctx.version,
            unknown1=unknown1,
            players=players,
            teams=teams,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext", has_asset_list: bool) -> None:
        with context.write_asset(self.asset_name, self.version):
            if self.version >= 6:
                context.stream.writeBool(self.unknown1)

            context.stream.writeUInt32(len(self.players))
            for player in self.players:
                player.write(context, has_asset_list)

            if self.version < 5:
                if self.version < 2:
                    context.stream.writeUInt32(len(self.teams))
                for team in self.teams:
                    team.write(context)
