from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, cast

from ..context import AssetPropertyType

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext


@dataclass
class CastleTemplate:
    name: str
    template_name: str
    offset: tuple[float, float, float]
    angle: float
    priority: int | None
    phase: int | None

    @classmethod
    def parse(cls, context: "ParsingContext", version: int) -> Self:
        name = context.stream.readUInt16PrefixedAsciiString()
        template_name = context.stream.readUInt16PrefixedAsciiString()
        offset = context.stream.readVector3()
        angle = context.stream.readFloat()

        priority = None
        phase = None
        if version >= 4:
            priority = context.stream.readUInt32()
            phase = context.stream.readUInt32()

        return cls(
            name=name,
            template_name=template_name,
            offset=offset,
            angle=angle,
            priority=priority,
            phase=phase,
        )

    def write(self, context: "WritingContext", version: int) -> None:
        context.stream.writeUInt16PrefixedAsciiString(self.name)
        context.stream.writeUInt16PrefixedAsciiString(self.template_name)
        context.stream.writeVector3(self.offset)
        context.stream.writeFloat(self.angle)

        if version >= 4:
            context.stream.writeUInt32(cast(int, self.priority))
            context.stream.writeUInt32(cast(int, self.phase))


@dataclass
class PerimeterPoint:
    x: float
    y: float
    z: float

    @classmethod
    def parse(cls, context: "ParsingContext", version: int) -> Self:
        if version >= 3:
            x = context.stream.readFloat()
            y = context.stream.readFloat()
            z = 0.0
        else:
            x = context.stream.readInt32()
            y = context.stream.readInt32()
            z = context.stream.readInt32()

        return cls(
            x=x,
            y=y,
            z=z,
        )

    def write(self, context: "WritingContext", version: int) -> None:
        if version >= 3:
            context.stream.writeFloat(self.x)
            context.stream.writeFloat(self.y)
        else:
            context.stream.writeInt32(int(self.x))
            context.stream.writeInt32(int(self.y))
            context.stream.writeInt32(int(self.z))


@dataclass
class CastlePerimeter:
    has_perimeter: bool
    name: str | None
    perimeter_points: list[PerimeterPoint]

    @classmethod
    def parse(cls, context: "ParsingContext", version: int) -> Self:
        has_perimeter = context.stream.readBoolUInt32Checked()

        name = None
        perimeter_points = []

        if has_perimeter:
            # the version is a tentative guess as this field does not exist in the OpenSAGE parser
            if version >= 5:
                name = context.stream.readUInt16PrefixedAsciiString()

            perimeter_point_count = context.stream.readUInt32()

            for _ in range(perimeter_point_count):
                perimeter_points.append(PerimeterPoint.parse(context, version))

        return cls(
            has_perimeter=has_perimeter,
            name=name,
            perimeter_points=perimeter_points,
        )

    def write(self, context: "WritingContext", version: int) -> None:
        context.stream.writeBoolUInt32Checked(self.has_perimeter)
        if self.has_perimeter:
            # the version is a tentative guess as this field does not exist in the OpenSAGE parser
            if version >= 5:
                context.stream.writeUInt16PrefixedAsciiString(cast(str, self.name))

            context.stream.writeUInt32(len(self.perimeter_points))
            for point in self.perimeter_points:
                point.write(context, version)


@dataclass
class CastleTemplates:
    asset_name = "CastleTemplates"

    version: int
    property_key: tuple[AssetPropertyType, int, str | None]
    templates: list[CastleTemplate]
    perimeter: CastlePerimeter | None
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        with context.read_asset() as asset_ctx:
            property_key = context.parse_asset_property_key()
            template_count = context.stream.readUInt32()

            templates = []
            for _ in range(template_count):
                templates.append(CastleTemplate.parse(context, asset_ctx.version))

            perimeter = None
            if asset_ctx.version >= 2:
                perimeter = CastlePerimeter.parse(context, asset_ctx.version)

        return cls(
            version=asset_ctx.version,
            property_key=property_key,
            templates=templates,
            perimeter=perimeter,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext") -> None:
        with context.write_asset(self.asset_name, self.version):
            key_type, key_index, key_name = self.property_key
            if key_name is None:
                raise ValueError("property_key name must be set to write CastleTemplates")
            context.write_asset_property_key((key_type, key_index, key_name))
            context.stream.writeUInt32(len(self.templates))
            for template in self.templates:
                template.write(context, self.version)

            if self.version >= 2:
                cast(CastlePerimeter, self.perimeter).write(context, self.version)
