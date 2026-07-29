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

This package root is **install-free**: nothing below needs a game on disk. `resolve` turns
code names into a specific build's integer ids, needs `sage_ini`, and is therefore not
re-exported - import it from its own module. Upgrade names need no such load at all: the
engine's own registry is readable, and `attach` fits it to the session automatically.

The live layouts these backends read are documented in `sage_patch/docs/engine-globals.md`,
`sage_patch/docs/live-object-model.md` and `sage_patch/docs/message-stream.md`.
"""

from sage_live.backend import Backend, ConnectionRefused, LoopbackBackend
from sage_live.bridge import BridgeBackend, BridgeUnavailable
from sage_live.connect import (
    AttachError,
    NoGameRunning,
    NotPermitted,
    attach,
    open_backend,
)
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
from sage_live.observation import GameObject, Observation, PlayerState, Vec3, distance
from sage_live.orders import OrderType
from sage_live.protocol import (
    OBSERVATION_STRUCT_VERSION,
    PROTOCOL_VERSION,
    Diagnostic,
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
from sage_live.session import DEFAULT_APM_CAP, APMLimiter, NoSelection, Session

__all__ = [
    "DEFAULT_APM_CAP",
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
    "EngineLayout",
    "Frame",
    "GameObject",
    "Handshake",
    "LiveNames",
    "LoopbackBackend",
    "MemoryBackend",
    "MemorySource",
    "MessageType",
    "NameLookup",
    "NoGameRunning",
    "NoNameLookup",
    "NoSelection",
    "NotPermitted",
    "Observation",
    "OrderType",
    "PlayerState",
    "ProcessMemory",
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
