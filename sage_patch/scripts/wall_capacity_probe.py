"""Print the pathfinder's wall capacity state from a running game: the wall-height layers and the
16-slot raised-surface table. Read-only. Run from the repo root in an elevated shell:

    PYTHONPATH=. python sage_patch/scripts/wall_capacity_probe.py

Layout: `../docs/wall-layer-capacity.md`.
"""

from __future__ import annotations

import struct

from sage_live.backends.memory import ProcessMemory, find_game_processes

THE_AI = 0x00DE4B40
LAYER_COUNT = 0x1BEB8
LAYER_HEIGHTS = 0x1BEBC
SLOTS = 0x60
SLOT_STRIDE = 0x40
RAMP_LIST = 0x5C


def main() -> None:
    memory = ProcessMemory(find_game_processes()[0])

    def u32(address: int) -> int:
        return struct.unpack("<I", memory.read(address, 4))[0]

    def f32(address: int) -> float:
        return struct.unpack("<f", memory.read(address, 4))[0]

    pathfinder = u32(u32(THE_AI) + 0x10)
    count = u32(pathfinder + LAYER_COUNT)
    print(f"wall-height layers: {count} (cell stamps wrap past 46)")
    for i in range(count):
        layer = i + 17
        wrapped = "" if layer < 64 else f"  <- stamped as {layer & 0x3F}"
        print(f"  layer {layer:3d}  height {f32(pathfinder + LAYER_HEIGHTS + 4 * i):8.2f}{wrapped}")

    print("raised-surface slots (walls use 2..15; 15 is never classified):")
    for index in range(16):
        slot = pathfinder + SLOTS + index * SLOT_STRIDE
        bridge, head = u32(slot + 0x34), u32(slot + 0x38)
        if not (bridge or head):
            continue
        members, node = 0, head
        while node and members < 10000:
            members += 1
            node = u32(node + 0x3C)
        kind = "bridge" if bridge else f"wall x{members}"
        print(f"  slot {index:2d}  {kind:10s} height {u32(slot + 0x3C)}  grid {u32(slot + 8)}x{u32(slot + 0xC)}")

    ramps, node = 0, u32(pathfinder + RAMP_LIST)
    while node and ramps < 100000:
        ramps += 1
        node = u32(node + 4)
    print(f"ramp records: {ramps}")


if __name__ == "__main__":
    main()
