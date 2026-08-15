"""Watch a replay play back on a live client and check every order against what its issuer
could actually see.

**Why this exists, and why it is the half that cannot be patched away.** Binary attestation
(`sage_patch`'s `binary-attest`) runs inside the client it is judging, so whoever can modify the
game can modify the check. This runs on the observer's machine, after the fact, over a recording
somebody else made - there is nothing in it for a cheater to edit. It is the weaker signal and
the stronger position.

**The method.** A replay records *inputs*, not state, so a replay alone cannot say what a player
could see. But the engine can: play the replay back on a real client and its own shroud grid is
reconstructed frame by frame, for every seat, exactly as it was. `sage_verify` reads the orders
from the file, reads the visibility from the running game through `sage_live`, and lines the two
up:

    order at frame F names object X    ->    was X inside the issuer's shroud at frame F?

You cannot click what you cannot see. An order naming an enemy object that its issuer has never
had line of sight on is not a play style, it is information that did not come from the game.

**What it is not.** It is a signal, not a proof, and the module is built to keep that distinction
visible rather than to produce a satisfying verdict:

- The engine's per-cell grid has **no explored-but-not-currently-seen state** (see
  `sage_live.api.shroud`), so remembering what a player has already scouted is this module's job,
  not the engine's. `Memory` does it by accumulating across the frames it actually samples -
  which means under-sampling invents false positives, and `--max-lag` is what refuses to judge
  rather than guess when the sampling fell behind.
- A verdict is only ever as good as the seat mapping. Replay slot numbering and the live
  `PlayerList` index are different spaces (`sage_patch/docs/message-stream.md` section 4c), so
  seats are matched by **name** and a seat that cannot be matched is reported unjudged.
- `Finding.confidence` is not decoration. An object-targeted order is near-conclusive; a
  ground-targeted one is circumstantial, because ground can be aimed at for many honest reasons.

Layout:

- `orders` - which order types carry a target, and how to pull it out of a chunk.
- `rules` - the pure judgement: a target, a visibility snapshot, a memory, a verdict.
- `watch` - the live loop: attach, follow frames, feed `rules`, collect findings.
- `report` - findings, and how they are printed.
"""

from __future__ import annotations

from sage_verify.orders import (
    OBJECT_TARGETED,
    POSITION_TARGETED,
    OrderTarget,
    order_name,
    target_of,
)
from sage_verify.report import Finding, Report, Verdict
from sage_verify.rules import Memory, Snapshot, judge
from sage_verify.watch import SeatMap, Watcher

__all__ = [
    "OBJECT_TARGETED",
    "POSITION_TARGETED",
    "Finding",
    "Memory",
    "OrderTarget",
    "Report",
    "SeatMap",
    "Snapshot",
    "Verdict",
    "Watcher",
    "judge",
    "order_name",
    "target_of",
]
