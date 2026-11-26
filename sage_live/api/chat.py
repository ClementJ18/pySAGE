"""`ChatLine` - one line of the match's message log, as the in-game chat window replays it.

Every chat line a client receives is kept in that log after it is shown, already formatted
`[sender] text` and in the sender's colour, beside a few system lines the engine adds itself. The
log is client state: a line only reaches the clients its sender addressed, so an observer reads the
lines sent to everyone or to the observers, and a replay has none (chat is not recorded). Details:
`MESSAGE_LOG_IN_GAME` in `sage_patch/addresses/ui.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ChatLine"]


@dataclass(frozen=True)
class ChatLine:
    """A line as the log holds it: the whole text, sender included, and its colour as `0xRRGGBB`."""

    text: str
    color: int
