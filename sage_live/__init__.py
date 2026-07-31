"""A Python API for a running BFME2 / RotWK game - observe it, and issue orders to it.

The shape mirrors `sage_replay`: one reads recorded games, the other reads and drives live
ones. The action space is deliberately the same object - `sage_replay.Order` - so an action
this package emits can be written by the byte-exact serializer the replay corpus already
gates, and a session's output can be checked against the replay the engine recorded of that
same session.

`attach()` is the front door:

```python
import sage_live

with sage_live.attach() as game:
    observation = game.observe()
    print(observation.me.resources, len(observation.mine))
```

`Session` sits on a `Backend`. `LoopbackBackend` is scripted and in-process, so the whole
Python surface is exercised with no game, no Windows and no reverse-engineering; other
backends read a live process or talk to an injected bridge. Backends are constructed
explicitly and check their platform in the constructor, never at import.

This package root is **install-free**: nothing below needs a game on disk. Two modules do and
are therefore not re-exported - import them from their own module:

- `resolve` turns code names into a specific build's integer ids.
- `statics` turns a template name into the ini facts about it, which is how a live object is
  classified at all: a build plot, a horde container, a thing that counts for victory.

Upgrade and template names need no such load: the engine's own registries are readable, and
`attach` fits a `LiveNames` to the session automatically.

The live layouts these backends read are documented in `sage_patch/docs/engine-globals.md`,
`sage_patch/docs/live-object-model.md` and `sage_patch/docs/message-stream.md`.
"""

from sage_live.backend import Backend, ConnectionRefused, GameExited, LoopbackBackend
from sage_live.bridge import BridgeBackend, BridgeUnavailable
from sage_live.connect import (
    AttachError,
    NoGameRunning,
    NotPermitted,
    attach,
    open_backend,
)
from sage_live.heroes import ReviveLookup, ReviveSlot
from sage_live.memory import (
    LAYOUT_ROTWK_201,
    EngineLayout,
    MemoryBackend,
    MemorySource,
    ProcessMemory,
    UpgradeDefinition,
    find_game_processes,
)
from sage_live.naming import (
    LiveNames,
    NameLookup,
    NoNameLookup,
    UnknownDefinition,
)
from sage_live.observation import (
    GameObject,
    Observation,
    PlayerState,
    ProductionItem,
    Vec3,
    distance,
)
from sage_live.orders import OrderType
from sage_live.protocol import (
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
from sage_live.session import (
    BUILD_CONFIRM,
    DEFAULT_APM_CAP,
    DEFAULT_CONFIRM,
    APMLimiter,
    IllegitimateOrder,
    NoReviveLookup,
    NoSelection,
    Sent,
    Session,
)
from sage_live.snapshot import RecordingSource, SnapshotSource

__all__ = [
    "BUILD_CONFIRM",
    "DEFAULT_APM_CAP",
    "DEFAULT_CONFIRM",
    "LAYOUT_ROTWK_201",
    "OBSERVATION_STRUCT_VERSION",
    "PROTOCOL_VERSION",
    "APMLimiter",
    "AttachError",
    "Backend",
    "BridgeBackend",
    "BridgeUnavailable",
    "ConnectionRefused",
    "Diagnostic",
    "DiagnosticLog",
    "EngineLayout",
    "Frame",
    "GameExited",
    "GameObject",
    "Handshake",
    "IllegitimateOrder",
    "LiveNames",
    "LoopbackBackend",
    "MemoryBackend",
    "MemorySource",
    "MessageType",
    "NameLookup",
    "NoGameRunning",
    "NoNameLookup",
    "NoReviveLookup",
    "NoSelection",
    "NotPermitted",
    "Observation",
    "OrderType",
    "PlayerState",
    "ProcessMemory",
    "ProductionItem",
    "RecordingSource",
    "ReviveLookup",
    "ReviveSlot",
    "Sent",
    "SnapshotSource",
    "Session",
    "UnknownDefinition",
    "UpgradeDefinition",
    "Vec3",
    "attach",
    "distance",
    "find_game_processes",
    "open_backend",
    "decode_frames",
    "decode_handshake",
    "decode_observation",
    "encode_frame",
    "encode_handshake",
    "encode_observation",
]
