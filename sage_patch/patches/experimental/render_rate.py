"""The render-rate patch: draw at more than 30 fps without the game running faster.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001`` **as Edain ships it**. Every
address below is derived in ``../../docs/render-rate.md``; §-references are to that document.

**What the engine does today.** SAGE simulates at 5 logic frames per second and draws at 30, and
the two are already decoupled: `TheGameEngine` keeps a sub-frame counter at ``+0x34``, a ratio at
``+0x38`` and an interpolation alpha at ``+0x3C`` that the render path lerps transforms with. What
welds them back together is one comparison — the wrap that ends a logic frame (``0x0063264A``) is
written against a **literal 6** rather than against the ratio the engine derives from the two
rates. So raising `FramesPerSecondLimit` alone does not buy frames; it makes the simulation run
faster, which is the complaint this patch exists to answer.

**What this does.** Moves the client rate and that literal together, rederives the four constants
the compiler folded from the client rate, and fixes the three things doing that breaks:

- the once-per-logic-frame latch (§9.2). Its predicate answers ``subFrame == 6 / (clientRate /
  [0x00ECA400])``, and at 60 that names sub-frame 1 — which is **never observable**, because the
  wrap sets the counter to 1 and Edain's always-running catch-up loop bumps it to 2 inside the
  same logic step. Every `previous = current` latch behind it stops firing and animations freeze.
  Holding the quotient at 3 keeps the answer on sub-frame 2 at any rate. One dword.
- the particle rate (§9.4). `ParticleSystemManager::update` runs once per client frame from the
  draw path, and particle lifetimes are counted in *updates*, so at 60 every effect in the game
  runs at double speed. The cave stamps the manager with ``clientFrame * 30 / clientRate`` instead
  of the raw frame — a tick that advances 30 times a second whatever the client rate is — and lets
  the engine's own compare and store do the rest. Measured live at 0.500 steps per client frame.
- the spell store (§9.6). `AptSpellStore::update` sends a button's state to the movie only when it
  differs from the value it cached at ``this+0x2AC``, and writes that cache whether or not the
  movie accepted the message — while the movie is entitled to drop one silently, both before the
  button clip exists and before its `open` flag is set at frame 19 of `_fade_in`. The losing side
  of that race is measured in *movie* frames, which advance with the client rate, so raising the
  rate leaves the spellbook showing nothing purchasable however many points the player has. The
  fix is two hooks: `AptSpellStore::OnInitialized` stamps all twenty slots with ``-1`` and records
  the millisecond, and `update`'s button loop then does nothing for :data:`DEFER_MS` before
  running for the first time — so the twenty sends go out once each, late enough for the movie to
  accept them. Diagnosed and proved by intervention in a live 60 fps match: writing that sentinel
  by hand, seconds after the panel opened, lit the book immediately and the next click bought the
  power.

  **The deferral is the half that does the work.** Invalidating on `OnInitialized` alone is a
  no-op, and was tried: that callback is what sets ``+0x2A0``, the flag `update` checks before it
  does anything, so the first update after it is the same pass the original send was already
  happening on. Nothing moves unless the loop is also held off.

**This is the Edain binary's patch, not stock SAGE's.** ``0x00ECA400`` does not exist on a stock
`game.dat`: there the same predicate divides by the logic rate and the catch-up loop is dormant, so
sub-frame 1 *is* observable and the latch needs no help — and a different edit besides. §0 of the
doc has the full diff. :meth:`_anchor_problems` refuses anything that is not the Edain shape rather
than writing a dword into whatever happens to live at that address.

**`FramesPerSecondLimit` in the mod's `GameData` must be set to the same number.** The patch owns
the client rate; the INI owns the pace, through `TheGameEngine+0x0C`, and it lives inside the
`.big` archives where no patch reaches it. Left at 30 against a 60 fps binary, **the whole game
runs at half speed** — measured 2.67 Hz logic against the 5.67 Hz it should have (§9.3). Nothing
warns, nothing crashes; it is just slow. This is the one thing a mod has to write.

**What is still wrong**, and why this is experimental rather than only untested. The simulation
runs **7–11% slow** at 60 (§9.5): Edain's always-running catch-up loop spends an extra sub-frame
per logic frame, and the frame limiter truncates ``1000/60`` to 16 ms. That shifts replay timing
and every peer's, so a match between a patched and an unpatched binary is not a match. A handful of
client-frame constants outside the §1 block are also unrescaled (§9.7), the visible one being an
animation blend weight that completes transitions in half the intended wall-clock time.

**Determinism.** The logic rate does not move and no simulation state depends on the sub-frame
index, so the patch is not *itself* a desync — but §9.5's slowdown is a real timing difference and
the whole lobby should run the same binary and the same `FramesPerSecondLimit`.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. No other bundled patch touches the pacing block, the wrap, the
timecode strides, `ParticleSystemManager::update` or `AptSpellStore::OnInitialized`.

**The spell store fix is not rate-specific**, and ships here because this is where the bug is
seen: the same race can tip on a stock 30 fps build, where nothing installs this. If it wants to
reach those installs it has to become a patch of its own.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from ...asm import JB, JE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "MAX_FPS",
    "MIN_FPS",
    "SECTION_NAME",
    "STOCK_CLIENT_RATE",
    "STOCK_LOGIC_RATE",
    "RenderRatePatch",
    "cave_code",
    "derived_floats",
    "latch_divisor",
    "particle_gate_code",
    "defer_code",
    "defer_entry",
    "state_reset_code",
    "state_reset_entry",
    "tick_stamp",
]

SECTION_NAME = ".fxrate"  # 8 chars max: the PE name field truncates silently past 8
#: CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. The particle gate needs
#: no writable storage - the tick it compares lives in the manager - but §9.6's deferral does: it
#: stamps the millisecond the spell store was initialised at and reads it back on every update,
#: which is four bytes of run-time state and the only reason this section is writable.
SECTION_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

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

#: `AptSpellStore::OnInitialized` (§9.6), the callback the movie fires once it is built. It
#: already resets this panel's cached state - `+0x2A2`, `+0x348`, `+0x34C`, `+0x350` and `+0x354`,
#: the last four to `-1` - and simply omits the twenty per-button state slots at `+0x2AC`. That
#: omission is the defect: `update` re-sends a button's state only when it differs from the value
#: cached there, and writes the cache whether or not the movie accepted the message. So a state
#: the movie refused - it drops one silently while the clip does not exist yet, and again while
#: the clip's `open` flag is false before frame 19 of `_fade_in` - is never repeated, and the
#: spellbook shows nothing purchasable however many points the player has.
#:
#: The window is the tail of that handler: `mov byte [ecx+0x2A0], 1`, seven bytes, with `ret 4`
#: behind it. Nothing in the image branches into either (checked for `call`/`jmp`/`jcc` and for
#: imm32 references), and the handler is straight-line from its single entry, so the whole window
#: can be taken over.
STATE_RESET = 0x00822890
STATE_RESET_STOCK = bytes.fromhex("c681a002000001")  # mov byte [ecx+0x2A0], 1
#: Where the cave rejoins: the handler's own `ret 4`, left as engine code.
STATE_RESET_RESUME = 0x00822897
STATE_RESET_LANDING = {STATE_RESET_RESUME: bytes.fromhex("c20400")}

#: `AptSpellStore` fields the cave walks. The button array runs `+0x2A8`..`+0x347` as twenty
#: `{CommandButton, state}` pairs, so the states are `+0x2AC` stride 8 and one past the last is
#: `+0x34C` - which is also the next field the handler resets, and the bound the loop compares to.
STORE_ENABLED = 0x2A0
STORE_STATES = 0x2AC
STORE_STATES_END = 0x34C

#: `kernel32!GetTickCount` in the import table. The deferral is wall-clock rather than a count of
#: update passes on purpose: `update` runs off whatever pump is turning, and while the spell store
#: is up that is `GameEngine::update`'s modal `Sleep(5)` spin rather than the client frame - so a
#: pass count would mean something different at every rate, which is the class of bug this whole
#: document is about.
GET_TICK_COUNT = 0x00BD02A0

#: How long `update` leaves the movie alone before it sends any button state (§9.6). The engine
#: has no acknowledgement to wait on, so the only thing it can do is arrive late: the first send
#: has to land after the movie has built its button clips and run each one's ten-frame `_fade_in`,
#: because a state that arrives before `open` is set is dropped and, being edge-triggered, never
#: repeated. Hanging the reset on `AptSpellStore::OnInitialized` alone does **not** do this - that
#: callback is what sets `+0x2A0`, so the first update after it is the same pass the original send
#: was already happening on, and invalidating the cache there moves nothing.
DEFER_MS = 500

#: The head of `update`'s button loop: `and dword [ebp-0x14], 0` / `lea edi, [esi+0x2AC]`, the
#: index and cursor the twenty iterations run on. Ten bytes, and the one branch that reaches it
#: (`je` at `0x00823154`) targets its **first** byte, so it lands on the hook and takes the same
#: path the fall-through does.
UPDATE_LOOP = 0x008231CA
UPDATE_LOOP_STOCK = bytes.fromhex("8365ec008dbeac020000")
#: The loop body, entered once the deferral has expired.
UPDATE_LOOP_TOP = 0x008231D4
#: Where the loop's own `jmp` goes when all twenty iterations are done - which is exactly what
#: "skip the loop this pass" has to look like, so the deferral borrows it rather than inventing an
#: exit. Everything before the loop in `update` (the layout, the help text, the description) still
#: runs; only the button states wait.
UPDATE_LOOP_DONE = 0x0082325E
UPDATE_LANDINGS = {
    UPDATE_LOOP_TOP: bytes.fromhex("8b47fc"),
    UPDATE_LOOP_DONE: bytes.fromhex("8b4df45f5e5b"),
}

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
    STATE_RESET: STATE_RESET_STOCK,
    **STATE_RESET_LANDING,
    UPDATE_LOOP: UPDATE_LOOP_STOCK,
    **UPDATE_LANDINGS,
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


#: The four §1 floats belong in :data:`ANCHORS` too, and are folded in here rather than written
#: out: `derived_floats` is the one definition of what the compiler emitted, and a literal copy
#: beside it is a second one to keep in step.
ANCHORS.update(derived_floats(STOCK_CLIENT_RATE))


def latch_divisor(fps: int) -> int:
    """`[0x00ECA400]`, chosen so the once-per-logic-frame latch keeps firing (§9.2).

    `0x0063252F` answers ``subFrame == 6 / (clientRate / [0x00ECA400])``, or ``subFrame == 1``
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
    authored for. This puts ``clientFrame * 30 / clientRate`` there instead and lets the engine's
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


def state_reset_code(base_va: int, tick_va: int) -> bytes:
    """The first half of §9.6's fix: invalidate the state cache and start the clock.

    Entered from the tail of `AptSpellStore::OnInitialized` with `ecx = this`. It writes `-1` over
    all twenty state slots - the same thing the surrounding handler already does to every other
    cached field, and a value no computed state (0..5) can equal - and stamps `tick_va` with the
    millisecond the panel was initialised at.

    **The stamp is the point.** Invalidating the cache here is on its own a no-op: this callback
    is what sets `+0x2A0`, the flag `update` checks before it does anything, so the first update
    after it is the same pass the original send was already happening on. What makes the
    invalidation matter is :func:`defer_code` holding the loop off for :data:`DEFER_MS` after this
    stamp, so that when the twenty sends finally go out the movie is built and can accept them.

    `ecx` is saved across the call because it is `this` and the loop below needs it; `eax` is the
    handler's return value and `-1` is what stock leaves there.
    """
    a = Asm(base_va)
    a.emit(STATE_RESET_STOCK)  # mov byte [ecx+0x2A0], 1   the displaced instruction
    a.emit(0x51)  # push ecx
    a.emit(0xFF, 0x15, struct.pack("<I", GET_TICK_COUNT))  # call [GetTickCount]
    a.emit(0x59)  # pop  ecx
    a.emit(0xA3, struct.pack("<I", tick_va))  # mov  [tick], eax
    a.emit(0x83, 0xC8, 0xFF)  # or   eax, -1     the sentinel
    a.emit(0x8D, 0x91, struct.pack("<I", STORE_STATES))  # lea edx, [ecx+0x2AC]  first slot
    a.emit(0x8D, 0x89, struct.pack("<I", STORE_STATES_END))  # lea ecx, [ecx+0x34C]  one past
    a.label("next")
    a.emit(0x89, 0x02)  # mov [edx], eax
    a.emit(0x83, 0xC2, 0x08)  # add edx, 8            stride over the button pointer
    a.emit(0x3B, 0xD1)  # cmp edx, ecx
    a.jcc(JB, "next")
    a.jmp_absolute(STATE_RESET_RESUME)
    return a.finish()


def defer_code(base_va: int, tick_va: int) -> bytes:
    """The second half: hold `update`'s button loop off until the movie can accept a state.

    Runs in place of the loop's head. Until :data:`DEFER_MS` has passed since the stamp, it takes
    the loop's own "all twenty done" exit, so `update` finishes the pass having sent nothing and
    the cache stays at the `-1` :func:`state_reset_code` wrote. On the first pass after that it
    performs the two displaced instructions and drops into the loop, which finds a mismatch on
    every slot and sends the lot - once each, so every button's state animation plays normally.

    The subtraction is unsigned and so is the compare, which is what makes it correct across
    `GetTickCount`'s 49-day wrap. `eax`, `ecx` and `edx` are dead here - the preceding call's
    return value is unused and the loop sets up `edi` itself - and a stdcall import preserves the
    rest.
    """
    a = Asm(base_va)
    a.emit(0xFF, 0x15, struct.pack("<I", GET_TICK_COUNT))  # call [GetTickCount]
    a.emit(0x2B, 0x05, struct.pack("<I", tick_va))  # sub  eax, [tick]
    a.emit(0x3D, struct.pack("<I", DEFER_MS))  # cmp  eax, DEFER_MS
    a.jcc(JB, "defer")
    a.emit(UPDATE_LOOP_STOCK)  # the displaced index and cursor set-up
    a.jmp_absolute(UPDATE_LOOP_TOP)
    a.label("defer")
    a.jmp_absolute(UPDATE_LOOP_DONE)
    return a.finish()


def _layout(base_va: int) -> tuple[bytes, int, int, int]:
    """Where each routine and the tick stamp land, given the section base.

    Every branch in the three routines is `rel32` or a fixed-width `rel8`, so none of them changes
    length with its address or with the stamp's - which is what lets the stamp's own address be
    resolved by laying the code out once against a placeholder and measuring it.
    """
    gate = particle_gate_code(base_va)
    state_va = base_va + len(gate)
    defer_va = state_va + len(state_reset_code(state_va, 0))
    tick_va = defer_va + len(defer_code(defer_va, 0))
    return gate, state_va, defer_va, tick_va


def cave_code(base_va: int) -> bytes:
    """Everything `.fxrate` holds: the particle gate, the state reset, the deferral, the stamp."""
    gate, state_va, defer_va, tick_va = _layout(base_va)
    return (
        gate
        + state_reset_code(state_va, tick_va)
        + defer_code(defer_va, tick_va)
        + bytes(4)  # the tick stamp, written at run time by the state reset
    )


def state_reset_entry(cave_va: int) -> int:
    """Where :func:`state_reset_code` starts, given the section base."""
    return _layout(cave_va)[1]


def defer_entry(cave_va: int) -> int:
    """Where :func:`defer_code` starts, given the section base."""
    return _layout(cave_va)[2]


def tick_stamp(cave_va: int) -> int:
    """Where the four bytes of run-time state live: the tick the panel initialised at."""
    return _layout(cave_va)[3]


def _hook(site_va: int, cave_va: int, width: int) -> bytes:
    """`jmp rel32` to the cave, `nop`-padded to the width of the window it replaces."""
    jump = b"\xe9" + struct.pack("<i", cave_va - (site_va + 5))
    if width < len(jump):
        raise ValueError(f"the window at 0x{site_va:08X} is too narrow for a near jump")
    return jump + b"\x90" * (width - len(jump))


class RenderRatePatch(Patch):
    """Draw at ``fps`` client frames per second while the simulation stays at its own rate."""

    name = "render-rate"
    author = "officialNecro"
    description = (
        "Draw at N frames per second instead of 30 without the simulation speeding up, "
        "interpolating drawables between logic frames. One INI change and it is required: set "
        "FramesPerSecondLimit in GameData to the same N, or the game runs at 30/N speed with no "
        "warning. Every peer in a match needs the same binary and the same N"
    )
    experimental = True

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
        """Structural check that ``data`` carries this patch at ``fps`` (an empty list ==
        verified). Locates the ``.fxrate`` cave, recomputes it and every edit from ``fps``, and
        re-checks the anchors the patch reads but does not rewrite. Reads only via ``struct`` and
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
        """Recognise this patch **and recover its N** from ``data``.

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
            *((va, want, "the state-reset landing") for va, want in STATE_RESET_LANDING.items()),
            *((va, want, "an update-loop landing") for va, want in UPDATE_LANDINGS.items()),
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
        """Every byte range this patch rewrites, as ``(file offset, stock, patched, note)``.
        Shared by :meth:`apply`, which writes ``patched`` where ``stock`` matches, and
        :meth:`verify`, which asserts ``patched`` is there."""
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
            (STATE_RESET, STATE_RESET_STOCK, b"", "spell store state reset -> the cave"),
            (UPDATE_LOOP, UPDATE_LOOP_STOCK, b"", "spell store update loop -> the cave"),
        ]
        narrow: list[tuple[int, bytes, bytes, str]] = [
            (WRAP + IMM8, bytes([6]), bytes([ratio]), "the wrap"),
            (RECOMPUTE_GATE + IMM8, bytes([6]), bytes([1]), "recompute gate"),
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
                new = _hook(PARTICLE_GATE, cave_va, len(PARTICLE_GATE_STOCK))
            elif va == STATE_RESET:
                new = _hook(STATE_RESET, state_reset_entry(cave_va), len(STATE_RESET_STOCK))
            elif va == UPDATE_LOOP:
                new = _hook(UPDATE_LOOP, defer_entry(cave_va), len(UPDATE_LOOP_STOCK))
            out.append((offset, old, new, note))
        return out
