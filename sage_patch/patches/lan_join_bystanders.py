"""Let only the host answer a LAN join request, so copies of the game sharing its IP stay silent.

The host's `MSG_REQUEST_JOIN` handler takes a request as addressed to it when the target's IP
matches its own, ignoring the port. Every other copy of the game on the host's machine therefore
handles the request too, finds it is not hosting, and replies with a denial whose reason is "game
gone" - shown as "Game has already started". The joiner acts on whichever reply arrives first, so
with several instances on one machine a join fails at random, or succeeds and is then undone by a
late denial. The three not-hosting branches are retargeted from the denial to the handler's
existing ignore exit, the one the IP test already takes for a request meant for another machine.

The cost is on a real LAN: a request addressed to a machine that has stopped hosting now times out
("Connection timed out") instead of failing at once.

Derivation: `../docs/multi-instance.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    LAN_REQUEST_JOIN_DENY_GONE,
    LAN_REQUEST_JOIN_IGNORE,
    LAN_REQUEST_JOIN_NOT_HOSTING,
)
from ..patcher import Patch
from ..utils import apply_byte_patch, va_to_offset

__all__ = ["LanJoinBystandersPatch", "jcc_target", "retargeted"]

#: Size of the `jcc rel32` each site ends in: `0F 8x` and four bytes of displacement.
_JCC32 = 6


def jcc_target(site: int, stock: bytes) -> int:
    """Where the `jcc rel32` that ends `stock`, placed at `site`, jumps to."""
    end = site + len(stock)
    return end + struct.unpack("<i", stock[-4:])[0]


def retargeted(site: int, stock: bytes) -> bytes:
    """`stock` with its final `jcc rel32` aimed at the handler's ignore exit."""
    end = site + len(stock)
    return stock[:-4] + struct.pack("<i", LAN_REQUEST_JOIN_IGNORE - end)


class LanJoinBystandersPatch(Patch):
    name = "lan-join-bystanders"
    author = "officialNecro"
    description = (
        "Let only the hosting copy of the game answer a LAN join request. Stock, every copy on the "
        "host's IP answers, and the ones not hosting refuse with 'Game has already started', so "
        "with several instances on one machine joins fail at random or are undone a moment later. "
        "No INI change"
    )

    def apply(self, data: bytearray) -> None:
        for site, stock in LAN_REQUEST_JOIN_NOT_HOSTING:
            self._check_site(data, site, stock)
        for site, stock in LAN_REQUEST_JOIN_NOT_HOSTING:
            apply_byte_patch(
                data,
                self._offset(data, site),
                stock,
                retargeted(site, stock),
                f"join request {site:#010x}: not hosting -> ignore",
            )

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        return off

    @classmethod
    def _check_site(cls, data: bytes | bytearray, site: int, stock: bytes) -> None:
        """Raise unless the test before the displacement is the stock one. The displacement is
        left out so this holds on a patched image too."""
        off = cls._offset(data, site)
        got = bytes(data[off : off + len(stock)])
        if got[:-4] != stock[:-4]:
            raise ValueError(
                f"{site:#010x} holds {got.hex()}, not {stock.hex()} - this is not the LAN join "
                "handler of the expected build"
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        for site, stock in LAN_REQUEST_JOIN_NOT_HOSTING:
            try:
                self._check_site(data, site, stock)
            except ValueError as exc:
                problems.append(str(exc))
                continue
            off = self._offset(data, site)
            got = bytes(data[off : off + len(stock)])
            if got != retargeted(site, stock):
                which = (
                    "the stock denial"
                    if jcc_target(site, got) == LAN_REQUEST_JOIN_DENY_GONE
                    else "somewhere else"
                )
                problems.append(
                    f"{site:#010x} still branches to {which}: the file does not carry this patch"
                )
        return problems
