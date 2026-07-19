"""Reader for SAGE replay files - Generals `.rep`, BFME `.BfMEReplay`, BFME2 / RotWK
`.BfME2Replay`.

`replay` is the parse layer: a header (game, version, map, player slots) plus the recorded
order stream, needing no game install. `ids` builds on it to extract object-referencing
integer ids and align them to a hand-written label log. Outcome inference has two
independent sources: `winner` infers a verdict from session-end signals (a concession
heuristic), and `sidecar` reads the ladder metadata sidecar's own stated winner.

`narrate`, `stats`, `aggregate`, `translated` and `cache` resolve against a loaded game and
import `sage_ini`, so they are not re-exported here - import from their own modules. That
keeps this package root install-free: every name below works from the replay file alone.

The Generals path mirrors OpenSAGE's ReplayFile; the BFME2 layout was validated against a
corpus of real replays.
"""

from sage_replay.ids import (
    AlignRow,
    IdEvent,
    IdRun,
    LabelAction,
    Labels,
    OrderIdSummary,
    align,
    arg_equals,
    collapse_runs,
    id_events,
    order_id_summaries,
    parse_labels,
)
from sage_replay.replay import (
    Bfme2OrderType,
    GeneralsOrderType,
    Order,
    OrderArgument,
    OrderArgumentType,
    ReplayChunk,
    ReplayFile,
    ReplayGameType,
    ReplayHeader,
    ReplayMetadata,
    ReplaySlot,
    ReplaySlotDifficulty,
    ReplaySlotType,
    ReplayTimestamp,
    find_replays,
    parse_replay,
    parse_replay_from_path,
)
from sage_replay.serialize import serialize_replay, write_replay
from sage_replay.winner import PlayerSession, Side, WinnerVerdict, infer_winner

__all__ = [
    "AlignRow",
    "Bfme2OrderType",
    "GeneralsOrderType",
    "IdEvent",
    "IdRun",
    "LabelAction",
    "Labels",
    "Order",
    "OrderArgument",
    "OrderArgumentType",
    "OrderIdSummary",
    "PlayerSession",
    "ReplayChunk",
    "ReplayFile",
    "ReplayGameType",
    "ReplayHeader",
    "ReplayMetadata",
    "ReplaySlot",
    "ReplaySlotDifficulty",
    "ReplaySlotType",
    "ReplayTimestamp",
    "Side",
    "WinnerVerdict",
    "align",
    "arg_equals",
    "collapse_runs",
    "find_replays",
    "id_events",
    "infer_winner",
    "order_id_summaries",
    "parse_labels",
    "parse_replay",
    "parse_replay_from_path",
    "serialize_replay",
    "write_replay",
]
