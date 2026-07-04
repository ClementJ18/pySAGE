from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext


@dataclass
class NamedCamera:
    look_at_point: tuple[float, float, float]
    name: str
    pitch: float
    roll: float
    yaw: float
    zoom: float
    fov: float
    unknown: float

    @classmethod
    def parse(cls, context: "ParsingContext"):
        look_at_point = context.stream.readVector3()
        name = context.stream.readUInt16PrefixedAsciiString()
        pitch = context.stream.readFloat()
        roll = context.stream.readFloat()
        yaw = context.stream.readFloat()
        zoom = context.stream.readFloat()
        fov = context.stream.readFloat()
        unknown = context.stream.readFloat()

        context.logger.debug(
            f"NamedCamera: {name}, LookAt: {look_at_point}, Pitch: {pitch}, "
            f"Roll: {roll}, Yaw: {yaw}, Zoom: {zoom}, FOV: {fov}"
        )
        return cls(
            look_at_point=look_at_point,
            name=name,
            pitch=pitch,
            roll=roll,
            yaw=yaw,
            zoom=zoom,
            fov=fov,
            unknown=unknown,
        )

    def write(self, context: "WritingContext"):
        context.stream.writeVector3(self.look_at_point)
        context.stream.writeUInt16PrefixedAsciiString(self.name)
        context.stream.writeFloat(self.pitch)
        context.stream.writeFloat(self.roll)
        context.stream.writeFloat(self.yaw)
        context.stream.writeFloat(self.zoom)
        context.stream.writeFloat(self.fov)
        context.stream.writeFloat(self.unknown)


@dataclass
class NamedCameras:
    asset_name = "NamedCameras"

    version: int
    cameras: list[NamedCamera]
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext"):
        with context.read_asset() as asset_ctx:
            cameras = []
            camera_count = context.stream.readUInt32()
            for _ in range(camera_count):
                cameras.append(NamedCamera.parse(context))

        context.logger.debug(f"Finished parsing {cls.asset_name}")
        return cls(
            version=asset_ctx.version,
            cameras=cameras,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext"):
        with context.write_asset(self.asset_name, self.version):
            context.stream.writeUInt32(len(self.cameras))
            for camera in self.cameras:
                camera.write(context)
