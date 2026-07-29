"""The backend interface, and the in-process implementation of it.

One `Backend` protocol, several implementations. `LoopbackBackend` is fed scripted
observations and needs no game; a memory backend reads a live process; a bridge backend
talks to an injected DLL. Everything above this line - `Session`, policies, tooling - is
written once against the protocol.

`poll` and `step` are both here from the start even though only `poll` (async) is
implemented for now. The difference between "a bot" and "an RL environment" is exactly
whether the engine waits for the agent, and retrofitting a blocking contract through an
async-shaped API is a rewrite rather than an addition.

Backends are constructed explicitly and any platform check belongs in the constructor,
never at import: this package must import cleanly on a machine with no game and no Windows.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol, runtime_checkable

from sage_live.observation import Observation
from sage_live.protocol import (
    Diagnostic,
    Handshake,
    MessageType,
    decode_frames,
    decode_observation,
    encode_frame,
    encode_observation,
)
from sage_replay.replay import Order

__all__ = ["Backend", "ConnectionRefused", "LoopbackBackend"]


class ConnectionRefused(Exception):
    """The handshake gate rejected the peer. Raised by `connect`, never by decoding."""


@runtime_checkable
class Backend(Protocol):
    """What a source of observations and a sink for orders must provide."""

    def connect(self) -> Handshake:
        """Perform the handshake. Raises `ConnectionRefused` on a mismatch."""
        ...

    def close(self) -> None: ...

    def poll(self) -> Observation | None:
        """The most recent observation, or None if none has arrived. Never blocks."""
        ...

    def step(self, timeout: float | None = None) -> Observation | None:
        """Advance one logic frame and return its observation.

        Only meaningful where the backend can hold the logic loop. Implementations that
        cannot should say so rather than silently behaving like `poll`.
        """
        ...

    def send(self, orders: Sequence[Order]) -> int:
        """Submit orders. Returns how many were accepted."""
        ...

    @property
    def diagnostics(self) -> Sequence[Diagnostic]: ...


class LoopbackBackend:
    """An in-process backend driven by a scripted list of observations.

    Not a stub: every observation is encoded to the wire format and decoded back before
    being handed out, so a test that drives a policy through this backend is also a
    conformance test for the codec. A shape that cannot survive the round trip fails here,
    on a laptop, rather than against a live game.
    """

    def __init__(
        self,
        observations: Iterable[Observation] = (),
        handshake: Handshake | None = None,
        expect: Handshake | None = None,
    ) -> None:
        self._script = list(observations)
        self._cursor = 0
        self._handshake = handshake or Handshake()
        self._expect = expect
        self._latest: Observation | None = None
        self._diagnostics: list[Diagnostic] = []
        self._connected = False
        self.sent: list[Order] = []

    @property
    def diagnostics(self) -> Sequence[Diagnostic]:
        return tuple(self._diagnostics)

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def remaining(self) -> int:
        return max(0, len(self._script) - self._cursor)

    def connect(self) -> Handshake:
        if self._expect is not None:
            ok, why = self._expect.accepts(self._handshake)
            if not ok:
                raise ConnectionRefused(why)
        self._connected = True
        return self._handshake

    def close(self) -> None:
        self._connected = False

    def _advance(self) -> Observation | None:
        """Take the next scripted observation through a full encode/decode round trip."""
        if self._cursor >= len(self._script):
            return None
        obs = self._script[self._cursor]
        self._cursor += 1
        wire = encode_frame(MessageType.OBSERVATION, encode_observation(obs))
        frames, tail, diags = decode_frames(wire)
        self._diagnostics.extend(diags)
        if tail:
            self._diagnostics.append(Diagnostic("frame did not consume its buffer"))
        if not frames:
            self._diagnostics.append(Diagnostic("observation frame did not decode"))
            return None
        decoded, diags = decode_observation(frames[0].payload)
        self._diagnostics.extend(diags)
        if decoded is not None:
            self._latest = decoded
        return decoded

    def poll(self) -> Observation | None:
        return self._advance() or self._latest

    def step(self, timeout: float | None = None) -> Observation | None:
        return self._advance()

    def send(self, orders: Sequence[Order]) -> int:
        if not self._connected:
            self._diagnostics.append(Diagnostic("send before connect"))
            return 0
        self.sent.extend(orders)
        return len(orders)
