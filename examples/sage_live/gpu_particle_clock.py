"""Does the GPU particle clock advance at the authored 30, or at the client rate?

`Type = GPU_PARTICLE` systems never go through the gate `render-rate.md` §9.4 installs. They read
the W3D millisecond clock at `0x00DD1E0C` and convert it to frames with the *live* client rate -
`ms * clientRate * 0.001` - at four sites in the GPU particle storage module (§9.11). That
recovers the client frame count at any rate, which is the defect: the content is authored in 30 Hz
particle updates, so at rate 60 a GPU particle ages twice as fast, and anything with a `SizeRate`
grows twice as fast with it.

Everything read here is an **absolute** counter, so a paused game reads as well as a running one -
and better, because nothing moves between the reads. Pause with the effect on screen and run it.

    gpu ticks per §9.4 tick = 1.000   the two clocks agree
                              1.920   §9.11, at rate 60 (2.000, less the 4% truncation)

At rate 30 both are 1.000 by construction, so a 30 fps run is only the control that says the probe
reads the right words.

Read-only; needs a running match.

    python examples/sage_live/gpu_particle_clock.py
    python examples/sage_live/gpu_particle_clock.py --systems
    python examples/sage_live/gpu_particle_clock.py --particles EXFireScroll2
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

from sage_live.backends.memory import ProcessMemory, find_game_processes  # noqa: E402

#: The W3D millisecond clock the GPU particle module reads (§9.11). Its sole writer is the setter
#: at 0x00516E20, from an accumulator advanced once per client frame.
W3D_MILLIS = 0x00DD1E0C

#: The step that accumulator takes, `1000 / clientRate` truncated to an integer at 0x00BC146C -
#: 33 at rate 30 and 16 at rate 60, which is why the clock itself is 1% slow at 30 and 4% at 60.
MILLIS_PER_FRAME = 0x00DC7A8C

#: The manager, the stamp §9.4's cave redefines, and the system list it walks.
PARTICLE_MANAGER = 0x00DE3744
STAMP = 0x74
SYSTEM_LIST = 0x4C

#: `TheGameClient` and its frame counter.
GAME_CLIENT = 0x00DE4388
CLIENT_FRAME = 0x10

#: The client rate, and the rate the content was authored at.
CLIENT_RATE = 0x00D9F60C
AUTHORED_RATE = 30

#: `FXParticleSystem` carries its parsed `System` block inline (§9.11's live layout).
SYSTEM_VTABLE = 0x00BF7B48
SYS_TYPE = 0xC
SYS_PARTICLE_NAME = 0x10
SYS_LIFETIME = 0x18
SYS_SIZE = 0x2C

#: ...and embeds the GPU storage module, whose entries are `{float deadline, id, object *}`.
GPU_MODULE = 0x1E0
GPU_MODULE_VTABLE = 0x00C33B48
MODULE_COUNT = 0x10
MODULE_ENTRIES = 0x24
ENTRY_STRIDE = 12

#: A live particle. `+0x58` is the birth CLIENT FRAME, which is the whole finding in one word.
PARTICLE_LIFETIME = 0x34
PARTICLE_BIRTH_FRAME = 0x58

#: The engine's own `ParticleSystemType` order, read off the name table at 0x00C31A84.
TYPES = {
    0: "NONE",
    1: "PARTICLE",
    2: "DRAWABLE",
    3: "STREAK",
    4: "VOLUME_PARTICLE",
    5: "SMUDGE",
    6: "TERRAIN_PARTICLE",
    7: "GPU_PARTICLE",
    8: "GPU_TERRAINFIRE",
}


class Reader:
    """Just enough of the process to answer this one question."""

    def __init__(self, memory: ProcessMemory) -> None:
        self._memory = memory

    def _read(self, address: int, fmt: str) -> int | float:
        raw = self._memory.read(address, 4)
        if not raw:
            raise SystemExit(f"could not read 0x{address:08X}")
        return struct.unpack(fmt, raw)[0]

    def u32(self, address: int) -> int:
        return int(self._read(address, "<I"))

    def i32(self, address: int) -> int:
        return int(self._read(address, "<i"))

    def f32(self, address: int) -> float:
        return float(self._read(address, "<f"))

    def ascii_string(self, address: int) -> str:
        """An engine `AsciiString` keeps its characters at `+8`, not at `+4`."""
        pointer = self.u32(address)
        if not 0x00400000 < pointer < 0x40000000:
            return ""
        raw = self._memory.read(pointer + 8, 64)
        if not raw:
            return ""
        return raw.split(b"\x00")[0].decode("ascii", "replace")

    def systems(self) -> list[int]:
        """Every live `FXParticleSystem`, off the manager's own list."""
        manager = self.u32(PARTICLE_MANAGER)
        if not manager:
            raise SystemExit("TheParticleSystemManager is null - attach once a match is running")
        head = self.u32(manager + SYSTEM_LIST)
        node, found = self.u32(head), []
        while node and node != head:
            value = self.u32(node + 8)
            if value and self.u32(value) == SYSTEM_VTABLE:
                found.append(value)
            node = self.u32(node)
        return found


def single(value: float) -> float:
    """Round through IEEE single, the way the engine's `fstp` does."""
    return float(struct.unpack("<f", struct.pack("<f", value))[0])


def report_particles(read: Reader, system: int, frame: int, rate: int) -> None:
    """One GPU system's live particles, each against the age it should have had."""
    module = system + GPU_MODULE
    begin, end = read.u32(module + MODULE_ENTRIES), read.u32(module + MODULE_ENTRIES + 4)
    low, high = read.f32(system + SYS_SIZE), read.f32(system + SYS_SIZE + 4)
    print("       #   birth    age  should be  life used      size now       size wanted")
    for index in range((end - begin) // ENTRY_STRIDE):
        particle = read.u32(begin + index * ENTRY_STRIDE + 8)
        if not particle:
            continue
        birth = read.u32(particle + PARTICLE_BIRTH_FRAME)
        life = read.u32(particle + PARTICLE_LIFETIME) or 1
        age = frame - birth
        wanted = age * AUTHORED_RATE / rate
        print(
            f"      {index:2d} {birth:7d} {age:6d}    {wanted:7.1f}    {age / life * 100:5.1f}%"
            f"   {low + age:6.1f}-{high + age:<7.1f} {low + wanted:6.1f}-{high + wanted:<7.1f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--systems", action="store_true", help="list every live particle system")
    parser.add_argument(
        "--particles",
        metavar="NAME",
        help="also dump the live particles of GPU systems whose ParticleName contains NAME",
    )
    args = parser.parse_args()

    pids = find_game_processes()
    if not pids:
        raise SystemExit("no game.dat running - start a match first")
    try:
        memory = ProcessMemory(pids[0])
    except PermissionError as exc:
        raise SystemExit(f"{exc}\nrun this from an elevated shell") from exc
    read = Reader(memory)

    rate = read.i32(CLIENT_RATE)
    step = read.i32(MILLIS_PER_FRAME)
    millis = read.u32(W3D_MILLIS)
    client = read.u32(GAME_CLIENT)
    manager = read.u32(PARTICLE_MANAGER)
    if not client or not manager:
        raise SystemExit("the client or the manager is null - attach once a match is running")
    frame = read.u32(client + CLIENT_FRAME)
    tick = read.u32(manager + STAMP)

    # Exactly what 0x007B12F9..0x007B1322 computes, in the order it computes it.
    gpu = single(single(float(millis * rate)) * single(0.001))

    print(f"pid {pids[0]}  client rate {rate}  ms per client frame {step} (1000/{rate} truncated)")
    print(f"  W3D millis {millis}   client frame {frame}   §9.4 tick {tick}   GPU clock {gpu:.2f}")
    if tick:
        print(f"\n  gpu ticks per §9.4 tick    = {gpu / tick:.3f}")
        print(f"    1.000 = both clocks agree;  {rate / AUTHORED_RATE:.3f} = §9.11, at rate {rate}")
    if frame:
        print(f"  gpu ticks per client frame = {gpu / frame:.3f}   (1.000, less the truncation)")

    systems = read.systems()
    if not (args.systems or args.particles):
        gpus = sum(1 for system in systems if read.u32(system + SYS_TYPE) in (7, 8))
        print(f"\n  {len(systems)} live systems, {gpus} of them GPU - --systems to list them")
        memory.close()
        return

    print(f"\n{len(systems)} live particle systems:")
    for system in systems:
        kind = read.u32(system + SYS_TYPE)
        name = read.ascii_string(system + SYS_PARTICLE_NAME)
        lifetime = read.f32(system + SYS_LIFETIME)
        low, high = read.f32(system + SYS_SIZE), read.f32(system + SYS_SIZE + 4)
        is_gpu = read.u32(system + GPU_MODULE) == GPU_MODULE_VTABLE
        count = f"  particles {read.u32(system + GPU_MODULE + MODULE_COUNT)}" if is_gpu else ""
        print(
            f"  0x{system:08X}  {TYPES.get(kind, f'?{kind}'):16s} {name:24s}"
            f" Lifetime {lifetime:g}  Size {low:g} {high:g}{count}"
        )
        if is_gpu and args.particles and args.particles.lower() in name.lower():
            report_particles(read, system, frame, rate)
    memory.close()


if __name__ == "__main__":
    main()
