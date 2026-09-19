"""An in-memory stand-in for a live game process, for the patcher, gate and trace tests."""

from __future__ import annotations

import struct

from sage_live.backends.live_patch import ProcessGone


class FakeProcess:
    """Sparse memory with page-protection-free code writes, and a suspend count to audit them."""

    def __init__(self) -> None:
        self.mem: dict[int, int] = {}
        self.suspended = 0
        self.code_writes_while_running = 0
        self.freed: list[int] = []
        self._next = 0x30000000
        # A process that has exited: every read fails and it can no longer be suspended.
        self.gone = False

    def read(self, address: int, size: int) -> bytes | None:
        if self.gone:
            return None
        try:
            return bytes(self.mem[address + i] for i in range(size))
        except KeyError:
            return None

    def write(self, address: int, data: bytes) -> bool:
        for i, b in enumerate(data):
            self.mem[address + i] = b
        return True

    def write_code(self, address: int, data: bytes) -> bool:
        if not self.suspended:
            self.code_writes_while_running += 1
        return self.write(address, data)

    def alloc(self, size: int) -> int:
        address = self._next
        self._next += 0x10000
        self.write(address, bytes(size))
        return address

    def free(self, address: int) -> None:
        self.freed.append(address)

    def suspend(self) -> None:
        if self.gone:
            raise ProcessGone("the game has exited")
        self.suspended += 1

    def resume(self) -> None:
        self.suspended -= 1

    def close(self) -> None:
        pass

    def u32(self, address: int, value: int) -> None:
        self.write(address, struct.pack("<I", value))
