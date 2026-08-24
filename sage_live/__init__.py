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

Everything a consumer needs is re-exported here, so the short name is the supported one:
`sage_live.attach`, `sage_live.Session`, `sage_live.Observation`. The three layers below are
for reading the source and for the rarer imports, not for everyday use.

- `sage_live.api` - the interface: `connect`, `session`, `observation`, `orders`.
- `sage_live.backends` - where the bytes come from: `base` (and `LoopbackBackend`), `memory`,
  `bridge`, and the `protocol` / `identity` / `snapshot` support beneath them.
- `sage_live.utils` - the lookups: `naming`, `heroes`, and the two ini-backed ones, `resolve`
  and `statics`.

`Session` sits on a `Backend`. `LoopbackBackend` is scripted and in-process, so the whole
Python surface is exercised with no game, no Windows and no reverse-engineering; other
backends read a live process or talk to an injected bridge. Backends are constructed
explicitly and check their platform in the constructor, never at import.

This package root is **install-free**: nothing re-exported below needs a game on disk. Two
modules do, and are therefore reachable only from their own module:

```python
from sage_live.utils.resolve import Resolver   # code names -> this build's integer ids
from sage_live.utils.statics import Statics    # a template name -> the ini facts about it
```

`statics` is how a live object is classified at all: a build plot, a horde container, a thing
that counts for victory. Upgrade and template names need no such load - the engine's own
registries are readable, and `attach` fits a `LiveNames` to the session automatically.

The live layouts these backends read are documented in `sage_patch/docs/engine-globals.md`,
`sage_patch/docs/live-object-model.md` and `sage_patch/docs/message-stream.md`.
"""

from sage_live.api import orders
from sage_live.api.camera import CameraPan, ViewLocation
from sage_live.api.connect import (
    AttachError,
    NoGameRunning,
    NotPermitted,
    attach,
    open_backend,
)
from sage_live.api.desync import (
    DEFAULT_HISTORY,
    DesyncWatcher,
    Divergence,
    Sample,
    compare,
    read_log,
)
from sage_live.api.observation import (
    GameObject,
    Observation,
    PlayerState,
    ProductionItem,
    Vec3,
    distance,
)
from sage_live.api.orders import OrderType
from sage_live.api.session import (
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
from sage_live.backends.base import Backend, ConnectionRefused, GameExited, LoopbackBackend
from sage_live.backends.bridge import BridgeBackend, BridgeUnavailable
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
from sage_live.utils.heroes import ReviveLookup, ReviveSlot
from sage_live.utils.naming import (
    LiveNames,
    NameLookup,
    NoNameLookup,
    UnknownDefinition,
)

__all__ = [
    "BUILD_CONFIRM",
    "DEFAULT_APM_CAP",
    "DEFAULT_CONFIRM",
    "DEFAULT_HISTORY",
    "LAYOUT_ROTWK_201",
    "OBSERVATION_STRUCT_VERSION",
    "PROTOCOL_VERSION",
    "APMLimiter",
    "AttachError",
    "Backend",
    "BridgeBackend",
    "BridgeUnavailable",
    "CameraPan",
    "ConnectionRefused",
    "Diagnostic",
    "DiagnosticLog",
    "DesyncWatcher",
    "Divergence",
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
    "Sample",
    "Sent",
    "Session",
    "SnapshotSource",
    "UnknownDefinition",
    "UpgradeDefinition",
    "Vec3",
    "ViewLocation",
    "attach",
    "compare",
    "decode_frames",
    "decode_handshake",
    "decode_observation",
    "distance",
    "encode_frame",
    "encode_handshake",
    "encode_observation",
    "find_game_processes",
    "open_backend",
    "orders",
    "read_log",
]
