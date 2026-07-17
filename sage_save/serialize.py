"""The lossless JSON layer: `value_to_json`/`value_from_json` convert any decoded chunk
dataclass to and from a plain JSON-compatible structure driven purely by runtime type
information (`dataclasses.fields`, `typing.get_type_hints`), and `json_to_save_full` rebuilds
an exact `.sav` byte string from that JSON with no access to the source file.

Schema: `"format": "sage_save.lossless.v1"`. Every `bytes` field rides as `{"b64": ...}` -
always, even when empty, so the deserializer never has to guess whether an absent key means
"empty" or "not decoded". An unregistered chunk (no `ChunkCodec` in `CHUNK_CODECS`) rides as one
raw base64 blob under `"raw"` - a first-class encoding, not a fallback - so a save with chunks
this module doesn't understand still round-trips byte-exactly.

This is the sibling of `sage_save.export`'s lossy, human-readable summary: where that module
throws bulk data away for readability, this one keeps everything, so it produces a JSON
document roughly the size of the source file (opaque regions ride as base64) but reconstructs
it exactly. `float` fields ride as plain JSON numbers, except a NaN - which JSON's single "NaN"
token cannot distinguish by sign or payload - rides as `{"nan_bits": <hex double>}` instead.
"""

import base64
import dataclasses
import math
import struct
import types
import typing
from datetime import datetime
from pathlib import Path
from typing import Any

from sage_save.chunks import CHUNK_CODECS, ChunkCodec
from sage_save.save import BLOCK_MARKER, HEADER_SIZE, Chunk, SaveFile, SaveHeader, write_save

LOSSLESS_FORMAT = "sage_save.lossless.v1"


def value_to_json(value: Any) -> Any:
    """Convert a decoded chunk value (or any of its parts) to a JSON-compatible structure,
    driven entirely by the runtime type of `value` - no annotations are consulted. `bytes`
    always becomes `{"b64": ...}`, even when empty, so the deserializer can rely on the key
    always being present rather than inferring emptiness from its absence."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: value_to_json(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, bytes):
        return {"b64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [value_to_json(item) for item in value]
    if isinstance(value, dict):
        # keys are int or str in every decoded chunk; str(k) preserves insertion order, which
        # is file order
        return {str(k): value_to_json(v) for k, v in value.items()}
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and math.isnan(value):
        # A raw xfer float can be a NaN with a specific sign/payload (observed in a WotR
        # living-world save's TacticalView - presumably a never-set camera), but JSON's "NaN"
        # token collapses every NaN to the same canonical value, losing that bit pattern. Ride
        # the exact double bits instead so `json_to_save_full` reproduces them byte-for-byte.
        return {"nan_bits": struct.pack("<d", value).hex()}
    if isinstance(value, (str, int, float)) or value is None:
        return value
    raise TypeError(f"value_to_json: unsupported type {type(value).__name__}")


def value_from_json(annotation: Any, data: Any) -> Any:
    """The inverse of `value_to_json`, driven by `annotation` (a dataclass field's resolved type
    hint) rather than by inspecting `data`'s shape - so an empty list and an empty dict are never
    confused, and an `int` dict key is restored as `int` rather than left as the JSON string
    key. Forward references (e.g. `Campaign.heroes: list["CampaignHero"]`) are expected to
    already be resolved via `typing.get_type_hints` before recursing into a dataclass field."""
    if annotation is bytes:
        return base64.b64decode(data["b64"])
    if annotation is datetime:
        return datetime.fromisoformat(data)
    if dataclasses.is_dataclass(annotation) and isinstance(annotation, type):
        hints = typing.get_type_hints(annotation)
        fields = {
            f.name: value_from_json(hints[f.name], data[f.name])
            for f in dataclasses.fields(annotation)
        }
        return annotation(**fields)

    origin = typing.get_origin(annotation)
    if origin is types.UnionType or origin is typing.Union:
        # the only unions in the decoded chunk dataclasses are `X | None`
        if data is None:
            return None
        (arm,) = (a for a in typing.get_args(annotation) if a is not type(None))
        return value_from_json(arm, data)
    if origin is list:
        (element_type,) = typing.get_args(annotation)
        return [value_from_json(element_type, item) for item in data]
    if origin is tuple:
        args = typing.get_args(annotation)
        if len(args) == 2 and args[1] is Ellipsis:  # homogeneous tuple[T, ...]
            return tuple(value_from_json(args[0], item) for item in data)
        return tuple(value_from_json(arg, item) for arg, item in zip(args, data, strict=True))
    if origin is dict:
        key_type, val_type = typing.get_args(annotation)
        return {
            (int(k) if key_type is int else k): value_from_json(val_type, v)
            for k, v in data.items()
        }

    if annotation is bool:  # checked before int/float: bool is an int subtype
        return data
    if annotation is float:
        if isinstance(data, dict):  # the NaN-bits escape from value_to_json
            return struct.unpack("<d", bytes.fromhex(data["nan_bits"]))[0]
        return float(data)
    if annotation in (int, str):
        return data
    raise TypeError(f"value_from_json: unsupported annotation {annotation!r}")


def codec_to_json(codec: ChunkCodec, value: Any) -> dict[str, Any]:
    """`codec.to_json` if the chunk needs a hand-written serializer, else the generic
    `value_to_json`."""
    if codec.to_json is not None:
        return codec.to_json(value)
    return value_to_json(value)


def codec_from_json(codec: ChunkCodec, data: dict[str, Any]) -> Any:
    """`codec.from_json` if the chunk needs a hand-written deserializer (a DERIVED-VIEW field
    that must be rebuilt via encode-then-decode rather than read straight from JSON), else the
    generic `value_from_json` keyed on `codec.value_type`."""
    if codec.from_json is not None:
        return codec.from_json(data)
    return value_from_json(codec.value_type, data)


def json_to_save_full(data: dict[str, Any]) -> bytes:
    """Rebuild the exact `.sav` bytes a `save_to_json_full` document was produced from, with no
    access to the source file. Each chunk's `"version"` key is informational only (it mirrors
    `payload[0]`, already carried inside `"decoded"`/`"raw"`) and is ignored here."""
    if data.get("format") != LOSSLESS_FORMAT:
        raise ValueError(
            f"not a {LOSSLESS_FORMAT!r} document (found format {data.get('format')!r})"
        )

    header_data = data["header"]
    eala_part, rts_part = header_data["container_id"].split(" ")
    magic_eala = eala_part.encode("latin-1")[::-1]
    magic_rts = rts_part.encode("latin-1")[::-1]
    value1, value2 = header_data["values"]
    header = SaveHeader(magic_eala, magic_rts, value1, value2)

    chunks: list[Chunk] = []
    offset = HEADER_SIZE
    for entry in data["chunks"]:
        name = entry["name"]
        if ("decoded" in entry) == ("raw" in entry):
            raise ValueError(f"chunk {name!r}: exactly one of 'decoded'/'raw' must be present")
        if "raw" in entry:
            payload = base64.b64decode(entry["raw"]["b64"])
        else:
            codec = CHUNK_CODECS.get(name)
            if codec is None or codec.encode is None:
                raise ValueError(f"chunk {name!r}: no encoder registered to reconstruct it")
            payload = codec.encode(codec_from_json(codec, entry["decoded"]))
        chunks.append(Chunk(name, payload, offset))
        offset += 1 + len(name) + len(BLOCK_MARKER) + 4 + len(payload)

    return write_save(SaveFile(header, chunks))


def json_to_save_full_to_path(data: dict[str, Any], path: str | Path) -> None:
    Path(path).write_bytes(json_to_save_full(data))
