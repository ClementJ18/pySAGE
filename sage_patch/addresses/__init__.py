"""Addresses of the supported engine binaries, in one place.

The primary target is the RotWK `game.dat` build `2.01.2614.37001` (11,346,944 bytes, ImageBase
`0x400000`, no ASLR, so a virtual address here is also where the byte sits in a running process).
Constants prefixed `WORLDBUILDER_` belong to RotWK 2.01's `Worldbuilder.exe` instead, which has its
own copies of engine functions. Both `sage_patch` and `sage_live` read their addresses from here.

Longer notes on how an address was found are in `docs/address-notes.md`, by constant name; the
engine globals and object layouts are derived in `docs/engine-globals.md`,
`docs/live-object-model.md` and `docs/message-stream.md`.
"""

from __future__ import annotations

from sage_patch.addresses import (
    ai,
    living_world,
    logic,
    objects,
    player,
    production,
    render,
    runtime,
    scripts,
    ui,
    worldbuilder,
)
from sage_patch.addresses.ai import *  # noqa: F403
from sage_patch.addresses.living_world import *  # noqa: F403
from sage_patch.addresses.logic import *  # noqa: F403
from sage_patch.addresses.objects import *  # noqa: F403
from sage_patch.addresses.player import *  # noqa: F403
from sage_patch.addresses.production import *  # noqa: F403
from sage_patch.addresses.render import *  # noqa: F403
from sage_patch.addresses.runtime import *  # noqa: F403
from sage_patch.addresses.scripts import *  # noqa: F403
from sage_patch.addresses.ui import *  # noqa: F403
from sage_patch.addresses.worldbuilder import *  # noqa: F403

__all__: list[str] = []
__all__ += worldbuilder.__all__
__all__ += living_world.__all__
__all__ += scripts.__all__
__all__ += ai.__all__
__all__ += ui.__all__
__all__ += render.__all__
__all__ += production.__all__
__all__ += player.__all__
__all__ += objects.__all__
__all__ += logic.__all__
__all__ += runtime.__all__
