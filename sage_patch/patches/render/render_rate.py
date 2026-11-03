"""Draw at more than 30 fps without the game running faster.

SAGE simulates at 5 logic frames and draws at 30, but the wrap ending a logic frame (`0x0063264A`)
compares against a literal 6 instead of the rate ratio, so raising the frame limit speeds up the
simulation. The patch moves the client rate and that literal together, rederives four constants
folded from the client rate, and fixes what that breaks: the once-per-logic-frame latch, the
interpolation alpha's denominator, and the CPU and GPU particle rates. Pair it with
`spell-store-deferral`, which fixes a spellbook race this makes likelier (§9.6).
`FramesPerSecondLimit` in the mod's `GameData` must match. Edain's binary only. Played in network
matches with no desync.

Derivation: `../docs/render-rate.md`.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from ...asm import JE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, jmp_rel32, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "MAX_FPS",
    "MIN_FPS",
    "SECTION_NAME",
    "STOCK_CLIENT_RATE",
    "STOCK_LOGIC_RATE",
    "GPU_CLOCKS",
    "RenderRatePatch",
    "cave_code",
    "derived_floats",
    "gpu_clock_bytes",
    "latch_divisor",
    "particle_gate_code",
]

SECTION_NAME = ".fxrate"  # 8 chars max: the PE name field truncates silently past 8
#: CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ. The particle gate needs no writable
#: storage: the tick it compares lives in the manager.
SECTION_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000

#: The two rates, statically initialised in `.data` (§1). The setter that would fill that block,
#: `0x00644F11`, has zero callers in the image, so these are compile-time constants that happen to
#: live in writable memory - and `[0x00D9F60C]` holds whatever is written here for the life of the
#: process, which is what lets the cave read it rather than fold it in.
LOGIC_RATE = 0x00D9F608
CLIENT_RATE = 0x00D9F60C
STOCK_LOGIC_RATE = 5
STOCK_CLIENT_RATE = 30

#: Edain's latch-predicate divisor (§9.2). Stock has no such global: there `0x00632535` divides
#: the client rate by the *logic* rate. Exactly one instruction in the image reads it, so the edit
#: cannot reach anything else.
LATCH_DIVISOR = 0x00ECA400

#: `mov eax, [clientRate]` / `cdq` / `idiv dword [latchDivisor]` - the predicate head, and the
#: proof this is the Edain binary rather than a stock one. Read, never written.
PREDICATE = 0x0063252F
PREDICATE_BYTES = bytes.fromhex("a10cf6d90099f73d00a4ec00")

#: The wrap that ends a logic frame, and the recompute gate beside it (§3.2, §4). `83 F8 06` /
#: `83 F9 06`; the immediate is the third byte of each.
WRAP = 0x0063264A
RECOMPUTE_GATE = 0x00632604
#: The timecode stride (§3.5): `6B C0 0A` / `6B C9 0A`, immediate likewise at +2.
STRIDES = (0x0062ECC6, 0x00632631, 0x00632ACF)
IMM8 = 2

#: `fps` must be a multiple of the logic rate. The floor is 35 because at the stock ratio every
#: site recomputes its stock bytes; the ceiling is 635 because the ratio and the stride are
#: written as signed `imm8`s.
MIN_FPS, MAX_FPS = 35, 635

#: `ParticleSystemManager::update`'s rate gate (§9.4). The two tests this displaces read
#: `TheGlobalData` (`0x00DE4364`) and its `+0xD45` flag, and they *skip* the gate below when
#: either is unset - which on a normal launch is what happens, so the manager steps every system
#: on every call. `mov eax, [TheGlobalData]` / `cmp eax, ebx` / `je run` / `cmp byte [eax+0xD45],
#: bl` / `je run`: 17 bytes, entered only by the `je` at `0x005F5149`, containing no other branch
#: target, so the whole window can be taken over.
PARTICLE_GATE = 0x005F515F
PARTICLE_GATE_STOCK = bytes.fromhex("a16443de003bc374273898450d0000741f")

#: Where the cave rejoins: the stock `cmp eax, [edi+0x74]` / `je <return>` / `mov [edi+0x74], eax`
#: that already implements "same tick, nothing to do". The cave changes only *what* is compared,
#: so the skip and the store stay engine code.
PARTICLE_GATE_RESUME = 0x005F5183
#: The other exit: the body of the update, taken when there is no `TheGameClient` to ask - the one
#: case where stock would have run unconditionally, kept that way.
PARTICLE_GATE_RUN = 0x005F518F
#: Neither exit is inside the window this patch rewrites, so nothing else guards them, and a cave
#: landing in the middle of somebody else's edit is a crash rather than a wrong number.
PARTICLE_LANDINGS = {
    PARTICLE_GATE_RESUME: bytes.fromhex("3b47740f84d0000000894774"),
    PARTICLE_GATE_RUN: bytes.fromhex("895dcc"),
}

#: `TheGameClient` and the `getFrame` slot in its vtable, both as the displaced code used them.
GAME_CLIENT = 0x00DE4388
GET_FRAME_SLOT = 0x7C

#: The GPU particle module's own clock (§9.11), and the four sites that convert it.
#:
#: A `Type = GPU_PARTICLE` system is never aged by the walk `PARTICLE_GATE` sits in front of,
#: so §9.4's cave does not reach it. `GPUParticleSystemStorageModule` reads the W3D millisecond
#: clock at `0x00DD1E0C` and turns it into frames itself - `mov eax, [millis]` / `imul eax,
#: [clientRate]` / `fild` / `fmul 0.001` - which recovers the *client* frame count at any rate.
#: That is the defect: the content is authored in 30 Hz particle updates, so at 60 a GPU particle
#: ages, grows and dies twice as fast. Each site is followed by `test eax, eax`, so nothing reads
#: the flags the `imul` sets and the shorter form is a drop-in.
#:
#: Measured in a live paused match at rate 60 (§9.11): 1.920 GPU ticks per §9.4 tick, and
#: `BarrageExplosion`'s particles carrying a birth *client* frame with the authored lifetime of 30
#: beside it - 0.50 s of life where the author wrote 1.00 s.
GPU_CLOCKS = (0x007B1102, 0x007B1160, 0x007B12FE, 0x007B140B)
GPU_CLOCK_STOCK = bytes.fromhex("0faf050cf6d900")  # imul eax, dword [clientRate]

#: **Every site this patch reads or rewrites, holding the bytes the stock build holds there.**
#: The tests plant exactly this to build a stand-in `game.dat`, so an address this patch has wrong
#: has nothing at it in the stand-in and fails there the way it would fail on a real binary - and
#: `TestTheAnchorsAgreeWithTheEdits` checks the "old" side of every edit against this table, so a
#: stock constant mistyped in one place cannot agree with itself in the other.
ANCHORS: dict[int, bytes] = {
    LOGIC_RATE: struct.pack("<i", STOCK_LOGIC_RATE),
    CLIENT_RATE: struct.pack("<i", STOCK_CLIENT_RATE),
    LATCH_DIVISOR: struct.pack("<i", 8),
    PREDICATE: PREDICATE_BYTES,
    WRAP: bytes.fromhex("83f806"),  # cmp eax, 6
    RECOMPUTE_GATE: bytes.fromhex("83f906"),  # cmp ecx, 6
    STRIDES[0]: bytes.fromhex("6bc00a"),  # imul eax, eax, 10
    STRIDES[1]: bytes.fromhex("6bc90a"),  # imul ecx, ecx, 10
    STRIDES[2]: bytes.fromhex("6bc90a"),
    PARTICLE_GATE: PARTICLE_GATE_STOCK,
    **PARTICLE_LANDINGS,
    **dict.fromkeys(GPU_CLOCKS, GPU_CLOCK_STOCK),
}


def derived_floats(fps: int) -> dict[int, bytes]:
    """The four rate-derived constants of §1, computed the way the compiler folded them.

    Each is evaluated in double and narrowed to float32, which is what reproduces the shipped
    bytes exactly at 30 - `client/1000` included, where the setter's `mulss` against `0.001f`
    would land one ulp away. `apply` writes these against the stock bytes as the "old" side, so a
    build whose floats are not what deriving from 30 produces is refused rather than half-moved:
    four of the six numbers left behind while the others move gives a game that is subtly the
    wrong speed rather than one that crashes.
    """
    return {
        0x00D9F620: struct.pack("<f", 1000.0 / fps),  # ms per client frame
        0x00D9F624: struct.pack("<f", fps * 0.001),
        0x00D9F628: struct.pack("<f", float(fps)),
        0x00D9F62C: struct.pack("<f", 1.0 / fps),  # seconds per client frame
    }


#: The four §1 floats belong in `ANCHORS` too, and are folded in here rather than written
#: out: `derived_floats` is the one definition of what the compiler emitted, and a literal copy
#: beside it is a second one to keep in step.
ANCHORS.update(derived_floats(STOCK_CLIENT_RATE))


def gpu_clock_bytes() -> bytes:
    """`imul eax, eax, 30` - the authored rate in place of the live one (§9.11).

    Three bytes where the stock `imul eax, [clientRate]` is seven, `nop`-padded to fill the window
    rather than shuffling anything after it. The multiplier is the rate the *content* was authored
    at, so unlike §9.4's divisor there is nothing to read out of `.data`: this constant does not
    move when the client rate does, which is the entire point of the edit. It is also a byte-level
    identity in behaviour at rate 30, which makes it safe on a binary whose rate has not moved.

    **This does not make the GPU clock exact, and cannot.** The W3D millisecond clock it reads is
    itself rate-derived and truncating - `0x00BC146C` stores `1000 / clientRate` as an integer, so
    it accumulates 990 ms per real second at rate 30 and 960 at rate 60. The tick this produces
    therefore lands on 29.7 Hz at rate 30 and 28.8 Hz at rate 60, against the authored 30. That
    residual is §9.11's separately-named 4%; removing it means changing how the W3D clock is
    represented, which every other consumer of that clock would feel.
    """
    patched = bytes((0x6B, 0xC0, STOCK_CLIENT_RATE))  # imul eax, eax, 30
    return patched + b"\x90" * (len(GPU_CLOCK_STOCK) - len(patched))


def latch_divisor(fps: int) -> int:
    """`[0x00ECA400]`, chosen so the once-per-logic-frame latch keeps firing (§9.2).

    `0x0063252F` answers `subFrame == 6 / (clientRate / [0x00ECA400])`, or `subFrame == 1`
    once that quotient reaches 6 - and sub-frame 1 is never observable by client code on this
    build. Measured live over 373 client frames: the counter took 2..6 at rate 30 and 2..12 at
    rate 60, never 1. Keeping the quotient at 3 keeps the answer on sub-frame 2 at any rate, and
    the stock 8 is preserved wherever it already gives 3.
    """
    return 8 if fps // 8 == 3 else fps // 3


def particle_gate_code(base_va: int) -> bytes:
    """The cave: step particle systems at the authored rate rather than at the client rate (§9.4).

    The manager stamps `this+0x74` with a tick and skips its update when the tick has not moved.
    Stock puts the raw client frame there, so at 60 it steps twice as often as the content was
    authored for. This puts `clientFrame * 30 / clientRate` there instead and lets the engine's
    own compare and store do the rest.

    The divisor is read from `.data` rather than folded in, so the cave and the constant this
    patch writes cannot drift apart - and the arithmetic is an identity at 30, which is what makes
    the cave safe to lay over a binary whose rate has not moved.
    """
    a = Asm(base_va)
    a.emit(0x8B, 0x0D, struct.pack("<I", GAME_CLIENT))  # mov ecx, [TheGameClient]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "run")  # nothing to ask -> update, as stock does
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x50, GET_FRAME_SLOT)  # call [eax+0x7c]     GameClient::getFrame
    a.emit(0x6B, 0xC0, STOCK_CLIENT_RATE)  # imul eax, eax, 30   * the authored rate
    a.emit(0x33, 0xD2)  # xor edx, edx
    a.emit(0xF7, 0x35, struct.pack("<I", CLIENT_RATE))  # div dword [clientRate]
    a.jmp_absolute(PARTICLE_GATE_RESUME)
    a.label("run")
    a.jmp_absolute(PARTICLE_GATE_RUN)
    return a.finish()


def cave_code(base_va: int) -> bytes:
    """Everything `.fxrate` holds: the particle gate."""
    return particle_gate_code(base_va)


class RenderRatePatch(Patch):
    """Draw at `fps` client frames per second while the simulation stays at its own rate."""

    name = "render-rate"
    author = "officialNecro"
    runtime_verified = "yes"
    description = (
        "Draw at N frames per second instead of 30 without the simulation speeding up, "
        "interpolating drawables between logic frames. One INI change and it is required: set "
        "FramesPerSecondLimit in GameData to the same N, or the game runs at 30/N speed with no "
        "warning. Every peer in a match needs the same binary and the same N. Apply "
        "spell-store-deferral with it, or the spellbook can open with nothing purchasable"
    )

    def __init__(self, fps: int = 60):
        if fps % STOCK_LOGIC_RATE or not MIN_FPS <= fps <= MAX_FPS:
            raise ValueError(
                f"fps must be a multiple of {STOCK_LOGIC_RATE} in {MIN_FPS}..{MAX_FPS}, got {fps}"
            )
        self.fps = fps

    def __str__(self) -> str:
        return f"{self.name} (N={self.fps})"

    @property
    def ratio(self) -> int:
        """`clientRate / logicRate` - what the wrap counts to, in place of its literal 6."""
        return self.fps // STOCK_LOGIC_RATE

    def apply(self, data: bytearray) -> None:
        problems = self._anchor_problems(data)
        if problems:
            raise ValueError("; ".join(problems))
        cave_va = allocate_section(data, SECTION_NAME, cave_code, SECTION_CHARACTERISTICS)
        for file_off, old, new, note in self._edits(data, cave_va):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that `data` carries this patch at `fps` (an empty list ==
        verified). Locates the `.fxrate` cave, recomputes it and every edit from `fps`, and
        re-checks the anchors the patch reads but does not rewrite. Reads only via `struct` and
        the section table - no disassembler."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        cave_va, cave_off, _vsize = located

        try:
            content = cave_code(cave_va)
            edits = self._edits(data, cave_va)
        except (ValueError, struct.error) as exc:
            return [f"cannot recompute the expected edits (wrong build?): {exc}"]

        problems: list[str] = []
        got = bytes(data[cave_off : cave_off + len(content)])
        if got != content:
            problems.append(
                f"{SECTION_NAME} does not hold the expected gate "
                "(the cave differs, or was built for another base address)"
            )
        for file_off, _old, new, note in edits:
            found = bytes(data[file_off : file_off + len(new)])
            if found != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {found.hex()}")
        return problems + self._anchor_problems(data)

    @classmethod
    def detect(cls, data: bytes | bytearray) -> RenderRatePatch | None:
        """Recognise this patch **and recover its N** from `data`.

        The default probe cannot: it would ask `verify` about 60 and call every other rate absent.
        The client rate is a plain dword in `.data`, so N reads straight back out of it, and
        `verify` then checks the cave and all seven sites against that N."""
        if find_section(data, SECTION_NAME) is None:
            return None
        offset = va_to_offset(data, CLIENT_RATE)
        if offset is None:
            return None
        try:
            fps = struct.unpack_from("<i", data, offset)[0]
            patch = cls(fps)
        except (ValueError, struct.error):
            return None
        return None if patch.verify(data) else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--fps",
            type=int,
            default=60,
            metavar="N",
            help=(
                f"client frames per second ({MIN_FPS}..{MAX_FPS}, a multiple of "
                f"{STOCK_LOGIC_RATE}); default 60. GameData's FramesPerSecondLimit must be set to "
                "the same number"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> RenderRatePatch:
        return cls(fps=args.fps)

    def _anchor_problems(self, data: bytes | bytearray) -> list[str]:
        """The sites this patch depends on but does not rewrite: the logic rate the ratio is
        computed against, the predicate shape that says this is the Edain binary, and the two
        addresses the cave jumps to."""
        problems: list[str] = []
        offset = va_to_offset(data, LOGIC_RATE)
        if offset is None:
            return ["the logic rate is not mapped - is this a RotWK 2.01 game.dat?"]
        logic = struct.unpack_from("<i", data, offset)[0]
        if logic != STOCK_LOGIC_RATE:
            problems.append(
                f"the logic rate at 0x{LOGIC_RATE:08X} is {logic}, not {STOCK_LOGIC_RATE}, "
                f"so ratio = fps / {STOCK_LOGIC_RATE} is wrong for this build"
            )
        for va, expected, note in (
            (PREDICATE, PREDICATE_BYTES, "the latch predicate"),
            *((va, want, "a particle-cave landing") for va, want in PARTICLE_LANDINGS.items()),
        ):
            offset = va_to_offset(data, va)
            if offset is None:
                problems.append(f"{note} at 0x{va:08X} is not mapped")
                continue
            found = bytes(data[offset : offset + len(expected)])
            if found != expected:
                problems.append(
                    f"{note} at 0x{va:08X} is {found.hex()}, not {expected.hex()} - this is not "
                    "the Edain build this patch was derived against"
                )
        return problems

    def _edits(self, data: bytes | bytearray, cave_va: int) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte range this patch rewrites, as `(file offset, stock, patched, note)`.
        Shared by `apply`, which writes `patched` where `stock` matches, and
        `verify`, which asserts `patched` is there."""
        fps, ratio = self.fps, self.ratio
        stride = max(10, ratio)
        stock = derived_floats(STOCK_CLIENT_RATE)

        wide: list[tuple[int, bytes, bytes, str]] = [
            (CLIENT_RATE, struct.pack("<i", STOCK_CLIENT_RATE), struct.pack("<i", fps), "rate"),
            (
                LATCH_DIVISOR,
                struct.pack("<i", latch_divisor(STOCK_CLIENT_RATE)),
                struct.pack("<i", latch_divisor(fps)),
                "latch divisor",
            ),
            *(
                (va, stock[va], new, f"derived float 0x{va:08X}")
                for va, new in derived_floats(fps).items()
            ),
            (PARTICLE_GATE, PARTICLE_GATE_STOCK, b"", "particle rate gate -> the cave"),
            *(
                (va, GPU_CLOCK_STOCK, gpu_clock_bytes(), f"gpu particle clock 0x{va:08X}")
                for va in GPU_CLOCKS
            ),
        ]
        narrow: list[tuple[int, bytes, bytes, str]] = [
            (WRAP + IMM8, bytes([6]), bytes([ratio]), "the wrap"),
            # The gate takes the ratio, *not* 1 - the two must be the same number, which is the
            # relationship stock has (gate 6, wrap 6) and the one 9.10 measures the cost of
            # breaking. Keyed to 1 the recompute never fires, because the catch-up loop at
            # 0x00632A9B steps the sub-frame past 1 inside the same logic step; `+0x38` is then
            # left to `0x006323D2`'s one-way `inc`, which only runs on a networked peer. Measured
            # on both sides of one live match: ratio 14 on the host and 31 on the off-host against
            # a wrap of 12, a 4.0x and a 20.0x boundary spike where a correct build is 2.0x.
            (RECOMPUTE_GATE + IMM8, bytes([6]), bytes([ratio]), "recompute gate"),
            *(
                (va + IMM8, bytes([10]), bytes([stride]), f"timecode stride 0x{va:08X}")
                for va in STRIDES
            ),
        ]

        out: list[tuple[int, bytes, bytes, str]] = []
        for va, old, new, note in wide + narrow:
            offset = va_to_offset(data, va)
            if offset is None:
                raise ValueError(f"{note}: VA 0x{va:08X} is not mapped")
            if va == PARTICLE_GATE:
                new = jmp_rel32(PARTICLE_GATE, cave_va, len(PARTICLE_GATE_STOCK))
            out.append((offset, old, new, note))
        return out
