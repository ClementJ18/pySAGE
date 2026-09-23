from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context import ParsingContext


@dataclass
class SkippedAsset:
    asset_name = "SkippedAsset"

    version: int
    datasize: int
    data: bytes
    name: str

    @classmethod
    def parse(cls, context: "ParsingContext", name: str):
        version = context.stream.read_uint16()
        datasize = context.stream.read_uint32()
        data = context.stream.read_bytes(datasize)

        context.logger.debug(
            f"Skipped asset: {name}, Version: {version}, Data Size: {datasize} bytes"
        )
        return cls(
            version=version,
            datasize=datasize,
            data=data,
            name=name,
        )
