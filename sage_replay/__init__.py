"""Reader for SAGE replay files — Generals `.rep`, BFME `.BfMEReplay`, BFME2 / RotWK
`.BfME2Replay`.

`sage_replay.replay` parses a replay into a header (game, version, map, player slots)
and the recorded order stream: one `ReplayChunk` per issued command, carrying its
logic-frame timecode, the issuing player, and typed arguments (object ids, positions,
screen rectangles, ...). The Generals path mirrors OpenSAGE's ReplayFile; the BFME2
layout was validated against a real replay. What the format still hides is tracked in
sage_replay/TODO.md.
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
    parse_replay,
    parse_replay_from_path,
)

__all__ = [
    "AlignRow",
    "GeneralsOrderType",
    "IdEvent",
    "IdRun",
    "LabelAction",
    "Labels",
    "Order",
    "OrderArgument",
    "OrderArgumentType",
    "OrderIdSummary",
    "ReplayChunk",
    "ReplayFile",
    "ReplayGameType",
    "ReplayHeader",
    "ReplayMetadata",
    "ReplaySlot",
    "ReplaySlotDifficulty",
    "ReplaySlotType",
    "ReplayTimestamp",
    "align",
    "arg_equals",
    "collapse_runs",
    "id_events",
    "order_id_summaries",
    "parse_labels",
    "parse_replay",
    "parse_replay_from_path",
]
