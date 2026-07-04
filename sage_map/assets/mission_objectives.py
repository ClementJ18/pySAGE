import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext


class MissionObjectiveType(enum.IntEnum):
    Attack = 0
    Unknown1 = 1
    Unknown2 = 2
    Build = 3
    Capture = 4
    Protect = 5


@dataclass
class MissionObjective:
    id: str
    text: str
    description: str
    is_bonus_objective: bool
    objective_type: MissionObjectiveType

    @classmethod
    def parse(cls, context: "ParsingContext"):
        id = context.stream.readUInt16PrefixedAsciiString()
        text = context.stream.readUInt16PrefixedAsciiString()
        description = context.stream.readUInt16PrefixedAsciiString()
        is_bonus_objective = context.stream.readBool()
        objective_type = MissionObjectiveType(context.stream.readUInt32())

        return cls(
            id=id,
            text=text,
            description=description,
            is_bonus_objective=is_bonus_objective,
            objective_type=objective_type,
        )

    def write(self, context: "WritingContext"):
        context.stream.writeUInt16PrefixedAsciiString(self.id)
        context.stream.writeUInt16PrefixedAsciiString(self.text)
        context.stream.writeUInt16PrefixedAsciiString(self.description)
        context.stream.writeBool(self.is_bonus_objective)
        context.stream.writeUInt32(self.objective_type.value)


@dataclass
class MissionObjectives:
    asset_name = "MissionObjectives"

    version: int
    objectives: list[MissionObjective]
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext"):
        with context.read_asset() as asset_ctx:
            objective_count = context.stream.readUInt32()
            objectives = []
            for _ in range(objective_count):
                objectives.append(MissionObjective.parse(context))

            return cls(
                version=asset_ctx.version,
                objectives=objectives,
                start_pos=asset_ctx.start_pos,
                end_pos=asset_ctx.end_pos,
            )

    def write(self, context: "WritingContext"):
        with context.write_asset(self.asset_name, self.version):
            context.stream.writeUInt32(len(self.objectives))
            for objective in self.objectives:
                objective.write(context)
