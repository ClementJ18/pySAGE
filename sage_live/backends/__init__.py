"""Where the bytes come from, and the wire format they arrive in.

One `Backend` protocol and three implementations of it, so everything above this line -
`Session`, policies, tooling - is written once and runs against any of them:

- `base` - the protocol itself, plus `LoopbackBackend`, which is fed scripted observations
  and needs no game.
- `memory` - `MemoryBackend`, `OpenProcess` + `ReadProcessMemory` and nothing else. Reads a
  live game; cannot order it.
- `bridge` - `BridgeBackend`, the same reads plus the write half, against a `game.dat`
  carrying `sage_patch`'s live-bridge patch.

Two supporting modules sit under those and are rarely imported directly:

- `protocol` - framing, the handshake gate, and the observation codec.
- `identity` - which build is running, read out of the mapped PE header. Every address here
  is build-specific, and pointing them at another build reports nonsense rather than
  failing, so the handshake refuses a mismatch.
- `snapshot` - a `MemorySource` that replays a recorded process, so a real match can be
  decoded with no game, no Windows and no elevation.

Backends are constructed explicitly and any platform check belongs in the constructor,
never at import: this package imports cleanly on a machine with no game and no Windows.
"""

from __future__ import annotations

from sage_live.backends.base import Backend, ConnectionRefused, GameExited, LoopbackBackend
from sage_live.backends.bridge import BridgeBackend, BridgeUnavailable
from sage_live.backends.identity import BuildIdentity, read_identity
from sage_live.backends.memory import (
    LAYOUT_ROTWK_201,
    EngineLayout,
    MemoryBackend,
    MemorySource,
    ProcessMemory,
    UpgradeDefinition,
    find_game_processes,
)
from sage_live.backends.protocol import (
    OBSERVATION_STRUCT_VERSION,
    PROTOCOL_VERSION,
    Diagnostic,
    DiagnosticLog,
    Frame,
    Handshake,
    MessageType,
    decode_frames,
    decode_handshake,
    decode_observation,
    encode_frame,
    encode_handshake,
    encode_observation,
)
from sage_live.backends.snapshot import RecordingSource, SnapshotSource

__all__ = [
    "LAYOUT_ROTWK_201",
    "OBSERVATION_STRUCT_VERSION",
    "PROTOCOL_VERSION",
    "Backend",
    "BridgeBackend",
    "BridgeUnavailable",
    "BuildIdentity",
    "ConnectionRefused",
    "Diagnostic",
    "DiagnosticLog",
    "EngineLayout",
    "Frame",
    "GameExited",
    "Handshake",
    "LoopbackBackend",
    "MemoryBackend",
    "MemorySource",
    "MessageType",
    "ProcessMemory",
    "RecordingSource",
    "SnapshotSource",
    "UpgradeDefinition",
    "decode_frames",
    "decode_handshake",
    "decode_observation",
    "encode_frame",
    "encode_handshake",
    "encode_observation",
    "find_game_processes",
    "read_identity",
]
