"""The public interface: what a policy, a bot or a notebook actually touches.

Four modules, in the order a consumer meets them:

- `connect` - `attach()`, the front door, and `open_backend()` under it.
- `session` - `Session`, the connected game: selection state, the APM cap, name resolution,
  the waiting and confirmation helpers.
- `observation` - the immutable snapshot a session hands out, and the queries over it.
- `orders` - the order constructors, for a caller assembling actions without a session.

Everything here is **install-free**: no game on disk, no Windows, no reverse-engineering.
The layer below is `sage_live.backends`, which fetches the bytes; the layer beside it is
`sage_live.utils`, which turns names into ids and templates into static facts.

These names are all re-exported from `sage_live` itself, so `sage_live.attach` and
`sage_live.api.connect.attach` are the same function. Prefer the short form.
"""

from __future__ import annotations

from sage_live.api import orders
from sage_live.api.connect import (
    AttachError,
    NoGameRunning,
    NotPermitted,
    attach,
    open_backend,
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

__all__ = [
    "BUILD_CONFIRM",
    "DEFAULT_APM_CAP",
    "DEFAULT_CONFIRM",
    "APMLimiter",
    "AttachError",
    "GameObject",
    "IllegitimateOrder",
    "NoGameRunning",
    "NoReviveLookup",
    "NoSelection",
    "NotPermitted",
    "Observation",
    "OrderType",
    "PlayerState",
    "ProductionItem",
    "Sent",
    "Session",
    "Vec3",
    "attach",
    "distance",
    "open_backend",
    "orders",
]
