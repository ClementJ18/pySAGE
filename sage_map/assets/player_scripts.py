from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Self, cast

from ..context import AssetPropertyType

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext


class ScriptArgumentType(IntEnum):
    INTEGER = 0
    REAL_NUMBER = 1
    SCRIPT_NAME = 2
    TEAM_NAME = 3
    COUNTER_NAME = 4
    FLAG_NAME = 5
    COMPARISON = 6
    WAYPOINT_NAME = 7
    BOOLEAN = 8
    TRIGGER_AREA_NAME = 9
    TEXT = 10
    PLAYER_NAME = 11
    SOUND_NAME = 12
    SUBROUTINE_NAME = 13
    UNIT_NAME = 14
    OBJECT_NAME = 15
    POSITION_COORDINATE = 16
    ANGLE = 17
    TEAM_STATE = 18
    RELATION = 19
    AI_MOOD = 20
    SPEECH_NAME = 21
    MUSIC_NAME = 22
    MOVIE_NAME = 23
    WAYPOINT_PATH_NAME = 24
    LOCALIZED_STRING_NAME = 25
    BRIDGE_NAME = 26
    UNIT_OR_STRUCTURE_KIND = 27
    ATTACK_PRIORITY_SET_NAME = 28
    RADAR_EVENT_TYPE = 29
    SPECIAL_POWER_NAME = 30
    SCIENCE_NAME = 31
    UPGRADE_NAME = 32
    UNIT_ABILITY_NAME = 33
    BOUNDARY_NAME = 34
    BUILDABILITY = 35
    SURFACE_TYPE = 36
    CAMERA_SHAKE_INTENSITY = 37
    COMMAND_BUTTON_NAME = 38
    FONT_NAME = 39
    OBJECT_STATUS = 40
    TEAM_ABILITY_NAME = 41
    SKIRMISH_APPROACH_PATH = 42
    COLOR = 43
    EMOTICON_NAME = 44
    OBJECT_PANEL_FLAG = 45
    FACTION_NAME = 46
    OBJECT_TYPE_LIST_NAME = 47
    MAP_REVEAL_NAME = 48
    SCIENCE_AVAILABILITY_NAME = 49
    EVACUATE_CONTAINER_SIDE = 50
    PERCENTAGE = 51
    PERCENTAGE2 = 52
    UNIT_REFERENCE = 54
    TEAM_REFERENCE = 55
    NEAR_OR_FAR = 56
    MATH_OPERATOR = 57
    MODEL_CONDITION = 58
    AUDIO_NAME = 59
    REVERB_ROOM_TYPE = 60
    OBJECT_TYPE = 61
    HERO = 62
    EMOTION = 63
    UNKNOWN_1 = 64
    EVA = 76
    OBJECTIVE_COMPLETE = 77


@dataclass
class ScriptArgument:
    type: ScriptArgumentType
    int_value: int | None = None
    float_value: float | None = None
    string_value: str | None = None
    position_value: tuple[float, float, float] | None = None

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        argument_type = ScriptArgumentType(context.stream.readUInt32())
        int_value = None
        float_value = None
        string_value = None
        position_value = None

        if argument_type == ScriptArgumentType.POSITION_COORDINATE:
            position_value = (
                context.stream.readFloat(),
                context.stream.readFloat(),
                context.stream.readFloat(),
            )
        else:
            int_value = context.stream.readInt32()
            float_value = context.stream.readFloat()
            string_value = context.stream.readUInt16PrefixedAsciiString()

        return cls(
            type=argument_type,
            int_value=int_value,
            float_value=float_value,
            string_value=string_value,
            position_value=position_value,
        )

    def write(self, context: "WritingContext") -> None:
        context.stream.writeUInt32(self.type.value)

        if self.type == ScriptArgumentType.POSITION_COORDINATE:
            if self.position_value is None:
                raise ValueError("position_value must be set for Coordinate arguments")
            context.stream.writeFloat(self.position_value[0])
            context.stream.writeFloat(self.position_value[1])
            context.stream.writeFloat(self.position_value[2])
        else:
            if self.int_value is None or self.float_value is None or self.string_value is None:
                raise ValueError(
                    "int_value, float_value, and string_value must be set "
                    "for non-Coordinate arguments"
                )
            context.stream.writeInt32(self.int_value)
            context.stream.writeFloat(self.float_value)
            context.stream.writeUInt16PrefixedAsciiString(self.string_value)


@dataclass
class ScriptDerived:
    asset_name_true = "ScriptAction"
    asset_name_false = "ScriptActionFalse"

    version: int
    content_type: int
    internal_name: tuple[AssetPropertyType, int, str | None] | None
    arguments: list[ScriptArgument]
    is_enabled: bool | None
    is_inverted: bool | None
    has_internal_name_version: int
    has_is_enabled_version: int
    has_is_inverted: bool

    @classmethod
    def parse(
        cls,
        context: "ParsingContext",
        has_internal_name_version: int,
        has_is_enabled_version: int,
        has_is_inverted: bool,
    ) -> Self:
        with context.read_asset() as asset_ctx:
            content_type = context.stream.readUInt32()

            internal_name = None
            if asset_ctx.version >= has_internal_name_version:
                internal_name = context.parse_asset_property_key()

            num_arguments = context.stream.readUInt32()
            arguments = []
            for _ in range(num_arguments):
                arguments.append(ScriptArgument.parse(context))

            is_enabled = None
            is_inverted = None
            if asset_ctx.version >= has_is_enabled_version:
                is_enabled = context.stream.readBoolUInt32()

                if has_is_inverted:
                    is_inverted = context.stream.readBoolUInt32()

        context.logger.debug("Finished parsing ScriptDerived")
        return cls(
            version=asset_ctx.version,
            content_type=content_type,
            internal_name=internal_name,
            arguments=arguments,
            is_enabled=is_enabled,
            is_inverted=is_inverted,
            has_internal_name_version=has_internal_name_version,
            has_is_enabled_version=has_is_enabled_version,
            has_is_inverted=has_is_inverted,
        )

    def write(self, context: "WritingContext", asset_name: str) -> None:
        with context.write_asset(asset_name, self.version):
            context.stream.writeUInt32(self.content_type)

            if self.version >= self.has_internal_name_version:
                if self.internal_name is None:
                    raise ValueError("internal_name must be set when the version includes it")
                key_type, key_index, key_name = self.internal_name
                if key_name is None:
                    raise ValueError("internal_name property key name must be set")
                context.write_asset_property_key((key_type, key_index, key_name))

            context.stream.writeUInt32(len(self.arguments))
            for argument in self.arguments:
                argument.write(context)

            if self.version >= self.has_is_enabled_version:
                context.stream.writeBoolUInt32(cast(bool, self.is_enabled))

                if self.has_is_inverted:
                    context.stream.writeBoolUInt32(cast(bool, self.is_inverted))


@dataclass
class OrCondition:
    asset_name = "OrCondition"

    version: int
    conditions: list[ScriptDerived]
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        with context.read_asset() as asset_ctx:
            conditions = []

            while context.stream.tell() < asset_ctx.end_pos:
                asset_name = context.parse_asset_name()
                if asset_name != "Condition":
                    raise ValueError(f"Expected Condition asset, got {asset_name}")

                condition = ScriptDerived.parse(context, 4, 5, True)
                conditions.append(condition)

        context.logger.debug("Finished parsing OrCondition")
        return cls(
            version=asset_ctx.version,
            conditions=conditions,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext") -> None:
        with context.write_asset(self.asset_name, self.version):
            for condition in self.conditions:
                context.write_asset_name("Condition")
                condition.write(context, "Condition")


@dataclass
class Script:
    asset_name = "Script"

    name: str
    comment: str
    conditions_comment: str
    actions_comment: str
    is_active: bool
    deactivate_upon_success: bool
    active_in_easy: bool
    active_in_medium: bool
    active_in_hard: bool
    is_subroutine: bool
    version: int
    start_pos: int
    end_pos: int
    evaluation_interval: int | None = None
    uses_evaluation_interval_type: bool = False
    evaluation_interval_type: int = 6
    actions_fire_sequentially: bool | None = None
    loop_actions: bool | None = None
    loop_count: int | None = None
    sequential_target_type: bool | None = None
    sequential_target_name: str | None = None
    unknown: str | None = None
    unknown2: int | None = None
    unknown3: int | None = None
    or_conditions: list[OrCondition] = field(default_factory=list)
    actions_if_true: list[ScriptDerived] = field(default_factory=list)
    actions_if_false: list[ScriptDerived] = field(default_factory=list)

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        with context.read_asset() as asset_ctx:
            name = context.stream.readUInt16PrefixedAsciiString()
            context.logger.info(f"Parsing script: {name}")
            comment = context.stream.readUInt16PrefixedAsciiString()
            conditions_comment = context.stream.readUInt16PrefixedAsciiString()
            actions_comment = context.stream.readUInt16PrefixedAsciiString()

            is_active = context.stream.readBool()
            deactivate_upon_success = context.stream.readBool()

            active_in_easy = context.stream.readBool()
            active_in_medium = context.stream.readBool()
            active_in_hard = context.stream.readBool()

            is_subroutine = context.stream.readBool()

            evaluation_interval = None
            uses_evaluation_interval_type = False
            evaluation_interval_type = 6
            if asset_ctx.version >= 2:
                evaluation_interval = context.stream.readUInt32()

                if asset_ctx.version == 5:
                    uses_evaluation_interval_type = context.stream.readBool()
                    evaluation_interval_type = context.stream.readUInt32()

            actions_fire_sequentially = None
            loop_actions = None
            loop_count = None
            sequential_target_type = None
            sequential_target_name = None
            if asset_ctx.version >= 3:
                actions_fire_sequentially = context.stream.readBool()
                loop_actions = context.stream.readBool()
                loop_count = context.stream.readInt32()
                sequential_target_type = context.stream.readBool()
                sequential_target_name = context.stream.readUInt16PrefixedAsciiString()

            unknown = None
            unknown2 = None
            unknown3 = None
            if asset_ctx.version >= 4:
                unknown = context.stream.readUInt16PrefixedAsciiString()
                if unknown not in ("ALL", "Planning", "X"):
                    raise ValueError("Invalid data in 'unknown'")

            if asset_ctx.version >= 6:
                unknown2 = context.stream.readInt32()
                unknown3 = context.stream.readUInt16()
                if unknown3 != 0:
                    raise ValueError("Invalid data in 'unknown3'")

            or_conditions = []
            actions_if_true = []
            actions_if_false = []
            while context.stream.tell() < asset_ctx.end_pos:
                asset_name = context.parse_asset_name()
                if asset_name == OrCondition.asset_name:
                    or_conditions.append(OrCondition.parse(context))
                elif asset_name == ScriptDerived.asset_name_true:
                    actions_if_true.append(ScriptDerived.parse(context, 2, 3, False))
                elif asset_name == ScriptDerived.asset_name_false:
                    actions_if_false.append(ScriptDerived.parse(context, 2, 3, False))
                else:
                    raise ValueError(f"Unexpected asset in script: {asset_name}")

        context.logger.debug("Finished parsing Script")
        return cls(
            name=name,
            comment=comment,
            conditions_comment=conditions_comment,
            actions_comment=actions_comment,
            is_active=is_active,
            deactivate_upon_success=deactivate_upon_success,
            active_in_easy=active_in_easy,
            active_in_medium=active_in_medium,
            active_in_hard=active_in_hard,
            is_subroutine=is_subroutine,
            version=asset_ctx.version,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
            evaluation_interval=evaluation_interval,
            uses_evaluation_interval_type=uses_evaluation_interval_type,
            evaluation_interval_type=evaluation_interval_type,
            actions_fire_sequentially=actions_fire_sequentially,
            loop_actions=loop_actions,
            loop_count=loop_count,
            sequential_target_type=sequential_target_type,
            sequential_target_name=sequential_target_name,
            unknown=unknown,
            unknown2=unknown2,
            unknown3=unknown3,
            or_conditions=or_conditions,
            actions_if_true=actions_if_true,
            actions_if_false=actions_if_false,
        )

    def write(self, context: "WritingContext") -> None:
        with context.write_asset(self.asset_name, self.version):
            context.stream.writeUInt16PrefixedAsciiString(self.name)
            context.stream.writeUInt16PrefixedAsciiString(self.comment)
            context.stream.writeUInt16PrefixedAsciiString(self.conditions_comment)
            context.stream.writeUInt16PrefixedAsciiString(self.actions_comment)

            context.stream.writeBool(self.is_active)
            context.stream.writeBool(self.deactivate_upon_success)

            context.stream.writeBool(self.active_in_easy)
            context.stream.writeBool(self.active_in_medium)
            context.stream.writeBool(self.active_in_hard)

            context.stream.writeBool(self.is_subroutine)

            if self.version >= 2:
                context.stream.writeUInt32(cast(int, self.evaluation_interval))

                if self.version == 5:
                    context.stream.writeBool(self.uses_evaluation_interval_type)
                    context.stream.writeUInt32(self.evaluation_interval_type)

            if self.version >= 3:
                context.stream.writeBool(cast(bool, self.actions_fire_sequentially))
                context.stream.writeBool(cast(bool, self.loop_actions))
                context.stream.writeInt32(cast(int, self.loop_count))
                context.stream.writeBool(cast(bool, self.sequential_target_type))
                context.stream.writeUInt16PrefixedAsciiString(
                    cast(str, self.sequential_target_name)
                )

            if self.version >= 4:
                context.stream.writeUInt16PrefixedAsciiString(cast(str, self.unknown))

            if self.version >= 6:
                context.stream.writeInt32(cast(int, self.unknown2))
                context.stream.writeUInt16(cast(int, self.unknown3))

            for or_condition in self.or_conditions:
                context.write_asset_name(OrCondition.asset_name)
                or_condition.write(context)

            for action in self.actions_if_true:
                context.write_asset_name(ScriptDerived.asset_name_true)
                action.write(context, ScriptDerived.asset_name_true)

            for action in self.actions_if_false:
                context.write_asset_name(ScriptDerived.asset_name_false)
                action.write(context, ScriptDerived.asset_name_false)


@dataclass
class ScriptGroup:
    asset_name = "ScriptGroup"

    version: int
    name: str
    is_active: bool
    is_subroutine: bool
    start_pos: int
    end_pos: int
    items: list["ScriptGroup | Script"] = field(default_factory=list)

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        with context.read_asset() as asset_ctx:
            name = context.stream.readUInt16PrefixedAsciiString()
            is_active = context.stream.readBool()
            is_subroutine = context.stream.readBool()

            items = []

            while context.stream.tell() < asset_ctx.end_pos:
                item = ScriptGroup.parse_script_list(context)
                items.append(item)

        context.logger.debug("Finished parsing ScriptGroup")
        return cls(
            version=asset_ctx.version,
            name=name,
            is_active=is_active,
            is_subroutine=is_subroutine,
            items=items,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    @staticmethod
    def parse_script_list(
        context: "ParsingContext",
    ) -> "ScriptGroup | Script":
        asset_name = context.parse_asset_name()

        if asset_name == "ScriptGroup":
            return ScriptGroup.parse(context)
        elif asset_name == "Script":
            return Script.parse(context)
        else:
            raise ValueError(f"Expected ScriptGroup or Script asset, got {asset_name}")

    def write(self, context: "WritingContext") -> None:
        with context.write_asset(self.asset_name, self.version):
            context.stream.writeUInt16PrefixedAsciiString(self.name)
            context.stream.writeBool(self.is_active)
            context.stream.writeBool(self.is_subroutine)

            for item in self.items:
                if isinstance(item, ScriptGroup):
                    context.write_asset_name(ScriptGroup.asset_name)
                    item.write(context)
                else:  # Script
                    context.write_asset_name(Script.asset_name)
                    item.write(context)


@dataclass
class ScriptList:
    asset_name = "ScriptList"

    version: int
    items: list["ScriptGroup | Script"]
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        with context.read_asset() as asset_ctx:
            if asset_ctx.version != 1:
                raise ValueError(f"Unexpected ScriptList version: {asset_ctx.version}")

            items = []

            while context.stream.tell() < asset_ctx.end_pos:
                item = ScriptGroup.parse_script_list(context)
                items.append(item)

        context.logger.debug("Finished parsing ScriptList")
        return cls(
            version=asset_ctx.version,
            items=items,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext") -> None:
        with context.write_asset(self.asset_name, self.version):
            for item in self.items:
                if isinstance(item, ScriptGroup):
                    context.write_asset_name(ScriptGroup.asset_name)
                    item.write(context)
                else:  # Script
                    context.write_asset_name(Script.asset_name)
                    item.write(context)


@dataclass
class PlayerScriptsList:
    asset_name = "PlayerScriptsList"

    version: int
    script_lists: list[ScriptList]
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        with context.read_asset() as asset_ctx:
            script_lists = []
            while context.stream.tell() < asset_ctx.end_pos:
                asset_name = context.parse_asset_name()
                if asset_name != ScriptList.asset_name:
                    raise ValueError(f"Expected {ScriptList.asset_name} asset, got {asset_name}")

                script_lists.append(ScriptList.parse(context))

        context.logger.debug(f"Finished parsing {cls.asset_name}")
        return cls(
            version=asset_ctx.version,
            script_lists=script_lists,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext") -> None:
        with context.write_asset(self.asset_name, self.version):
            for script_list in self.script_lists:
                context.write_asset_name(ScriptList.asset_name)
                script_list.write(context)
