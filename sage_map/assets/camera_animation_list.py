from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from ..context import ParsingContext, WritingContext


@dataclass
class FreeCameraAnimationCameraFrame:
    frame_index: int
    interpolation_type: str
    position: tuple[float, float, float]
    rotation: tuple[float, float, float, float]
    fov: float

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        frame_index = context.stream.readUInt32()
        interpolation_type = context.stream.readFourCc()[::-1]  # Big endian, so reverse
        if interpolation_type not in ["catm", "line"]:
            raise ValueError(f"Invalid interpolation type: {interpolation_type}")

        position = context.stream.readVector3()
        rotation = context.stream.readVector4()
        fov = context.stream.readFloat()

        return cls(
            frame_index=frame_index,
            interpolation_type=interpolation_type,
            position=position,
            rotation=rotation,
            fov=fov,
        )

    def write(self, context: "WritingContext") -> None:
        context.stream.writeUInt32(self.frame_index)
        context.stream.writeFourCc(self.interpolation_type[::-1])  # Reverse back to big endian
        context.stream.writeVector3(self.position)
        context.stream.writeVector4(self.rotation)
        context.stream.writeFloat(self.fov)


@dataclass
class FreeCameraAnimationFrameData:
    frames: list[FreeCameraAnimationCameraFrame]

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        camera_frames_count = context.stream.readUInt32()
        camera_frames = []
        for _ in range(camera_frames_count):
            camera_frames.append(FreeCameraAnimationCameraFrame.parse(context))

        return cls(
            frames=camera_frames,
        )

    def write(self, context: "WritingContext") -> None:
        context.stream.writeUInt32(len(self.frames))
        for frame in self.frames:
            frame.write(context)


@dataclass
class LookAtCameraAnimationLookAtFrame:
    frame_index: int
    interpolation_type: str
    look_at_point: tuple[float, float, float]

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        frame_index = context.stream.readUInt32()
        interpolation_type = context.stream.readFourCc()[::-1]
        if interpolation_type not in ["catm", "line"]:
            raise ValueError(f"Invalid interpolation type: {interpolation_type}")

        look_at = context.stream.readVector3()

        return cls(
            frame_index=frame_index,
            interpolation_type=interpolation_type,
            look_at_point=look_at,
        )

    def write(self, context: "WritingContext") -> None:
        context.stream.writeUInt32(self.frame_index)
        context.stream.writeFourCc(self.interpolation_type[::-1])
        context.stream.writeVector3(self.look_at_point)


@dataclass
class LookAtCameraAnimationCameraFrame:
    frame_index: int
    interpolation_type: str
    position: tuple[float, float, float]
    roll: float
    fov: float

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        frame_index = context.stream.readUInt32()
        interpolation_type = context.stream.readFourCc()[::-1]
        if interpolation_type not in ["catm", "line"]:
            raise ValueError(f"Invalid interpolation type: {interpolation_type}")

        position = context.stream.readVector3()
        roll = context.stream.readFloat()
        fov = context.stream.readFloat()

        return cls(
            frame_index=frame_index,
            interpolation_type=interpolation_type,
            position=position,
            roll=roll,
            fov=fov,
        )

    def write(self, context: "WritingContext") -> None:
        context.stream.writeUInt32(self.frame_index)
        context.stream.writeFourCc(self.interpolation_type[::-1])
        context.stream.writeVector3(self.position)
        context.stream.writeFloat(self.roll)
        context.stream.writeFloat(self.fov)


@dataclass
class LookAtCameraAnimationFrameData:
    camera_frames: list[LookAtCameraAnimationCameraFrame]
    look_at_frames: list[LookAtCameraAnimationLookAtFrame]

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        camera_frames_count = context.stream.readUInt32()
        camera_frames = []
        for _ in range(camera_frames_count):
            camera_frames.append(LookAtCameraAnimationCameraFrame.parse(context))

        look_at_frames_count = context.stream.readUInt32()
        look_at_frames = []
        for _ in range(look_at_frames_count):
            look_at_frames.append(LookAtCameraAnimationLookAtFrame.parse(context))

        return cls(
            camera_frames=camera_frames,
            look_at_frames=look_at_frames,
        )

    def write(self, context: "WritingContext") -> None:
        context.stream.writeUInt32(len(self.camera_frames))
        for frame in self.camera_frames:
            frame.write(context)

        context.stream.writeUInt32(len(self.look_at_frames))
        for look_at_frame in self.look_at_frames:
            look_at_frame.write(context)


@dataclass
class CameraAnimation:
    animation_type: str
    name: str
    num_frames: int
    start_offset: int
    frame_data: FreeCameraAnimationFrameData | LookAtCameraAnimationFrameData

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        animation_type = context.stream.readFourCc()[::-1]
        if animation_type not in ["free", "look"]:
            raise ValueError(f"Unknown camera animation type: {animation_type}")

        name = context.stream.readUInt16PrefixedAsciiString()
        num_frames = context.stream.readUInt32()
        start_offset = context.stream.readUInt32()

        frame_data: FreeCameraAnimationFrameData | LookAtCameraAnimationFrameData
        if animation_type == "free":
            frame_data = FreeCameraAnimationFrameData.parse(context)
        elif animation_type == "look":
            frame_data = LookAtCameraAnimationFrameData.parse(context)
        else:
            raise ValueError(f"Unhandled camera animation type: {animation_type}")

        context.logger.debug(
            f"CameraAnimation: {name}, Type: {animation_type}, "
            f"Frames: {num_frames}, StartOffset: {start_offset}"
        )
        return cls(
            animation_type=animation_type,
            name=name,
            num_frames=num_frames,
            start_offset=start_offset,
            frame_data=frame_data,
        )

    def write(self, context: "WritingContext") -> None:
        context.stream.writeFourCc(self.animation_type[::-1])
        context.stream.writeUInt16PrefixedAsciiString(self.name)
        context.stream.writeUInt32(self.num_frames)
        context.stream.writeUInt32(self.start_offset)

        self.frame_data.write(context)


@dataclass
class CameraAnimationList:
    asset_name = "CameraAnimationList"

    version: int
    animations: list[CameraAnimation]
    start_pos: int
    end_pos: int

    @classmethod
    def parse(cls, context: "ParsingContext") -> Self:
        with context.read_asset() as asset_ctx:
            animations = []
            animation_count = context.stream.readUInt32()
            for _ in range(animation_count):
                animations.append(CameraAnimation.parse(context))

        context.logger.debug(f"Finished parsing {cls.asset_name}")
        return cls(
            version=asset_ctx.version,
            animations=animations,
            start_pos=asset_ctx.start_pos,
            end_pos=asset_ctx.end_pos,
        )

    def write(self, context: "WritingContext") -> None:
        with context.write_asset(self.asset_name, self.version):
            context.stream.writeUInt32(len(self.animations))
            for animation in self.animations:
                animation.write(context)
