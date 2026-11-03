"""Reading a replay while the game is still writing it.

The recorder opens its file when the match starts and appends each frame's orders as the match
runs (`sage_patch/docs/skirmish-replay.md` section "Status" saw it on disk and growing
mid-skirmish), so the file on disk is always a finished header followed by a chunk stream that
may stop partway through a chunk. `ReplayTail` reads that file a little at a time: each `poll`
reads only the bytes added since the last one and hands back the chunks that are now complete,
leaving a half-written last chunk for the next poll.

The header's frame count and end time are only filled in when the recording finishes, so a live
header says nothing about how long the match has run; the newest chunk's timecode does.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from sage_replay.replay import ReplayChunk, ReplayHeader
from sage_utils.stream import BinaryStream

__all__ = ["ReplayTail", "TailRead"]

# What a read stopped short of the end raises: a fixed-size field cut off (`struct.error`), or
# a field whose value only makes sense with the bytes after it (`ValueError`).
_SHORT_READ = (struct.error, ValueError, EOFError, IndexError, UnicodeDecodeError)


@dataclass(frozen=True)
class TailRead:
    """What one `ReplayTail.poll` found."""

    # None until the file holds a whole header.
    header: ReplayHeader | None
    # The chunks completed since the last poll, oldest first.
    chunks: tuple[ReplayChunk, ...] = ()
    # The file was replaced by a new recording since the last poll (it shrank), so whatever was
    # read from it before belongs to another match.
    restarted: bool = False


@dataclass
class ReplayTail:
    """Follows one replay file as the game writes it.

    Nothing is held open between polls, so the game is never kept from writing, renaming or
    replacing the file. A file that shrinks has been overwritten by a new recording - the stock
    game reuses `Last Replay` for every match - and is read again from the start.
    """

    path: Path
    header: ReplayHeader | None = None
    # How far into the file the chunks read so far reach.
    offset: int = 0
    # Every chunk read so far, so a caller that joins late can catch up.
    chunks: list[ReplayChunk] = field(default_factory=list)

    def poll(self) -> TailRead:
        """Read whatever the game has added since the last poll.

        A file that cannot be read right now (missing, or locked for a moment) reads as nothing
        new rather than an error: the next poll will try again.
        """
        try:
            size = self.path.stat().st_size
        except OSError:
            return TailRead(self.header)
        restarted = size < self.offset
        if restarted:
            self.header = None
            self.offset = 0
            self.chunks.clear()
        if size == self.offset:
            return TailRead(self.header, restarted=restarted)
        try:
            with self.path.open("rb") as handle:
                handle.seek(self.offset)
                data = handle.read(size - self.offset)
        except OSError:
            return TailRead(self.header, restarted=restarted)
        stream = BinaryStream(BytesIO(data))
        if self.header is None:
            try:
                self.header = ReplayHeader.parse(stream)
            except _SHORT_READ:
                self.header = None
                return TailRead(None, restarted=restarted)
            self.offset += stream.tell()
            data = data[stream.tell() :]
            stream = BinaryStream(BytesIO(data))
        fresh: list[ReplayChunk] = []
        while stream.tell() < len(data):
            start = stream.tell()
            try:
                chunk = ReplayChunk.parse(stream)
            except _SHORT_READ:
                # The game has written part of this chunk; the rest comes with a later poll.
                stream.seek(start)
                break
            fresh.append(chunk)
        self.offset += stream.tell()
        self.chunks.extend(fresh)
        return TailRead(self.header, tuple(fresh), restarted)
