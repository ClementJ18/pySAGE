"""Re-send the spellbook's button states once its movie can accept them.

`AptSpellStore::update` sends each button's state only when it differs from a cache it writes
whether or not the movie took the message, and `SpellStore.apt` silently refuses a state that
arrives before the button clip has finished its fade-in. One refused message is therefore
permanent, and the spellbook opens with nothing purchasable however many points the player has.
The race is the engine's, not a frame rate's: it reproduces on a stock binary with Edain's debug
`x2 speed`, and anything that changes how fast the movie plays against the engine's update -
`render-rate`, the accelerator's render-only frames - only makes it likelier.

The patch invalidates the cache when the panel initialises and holds the sends off for
`DEFER_MS`, so the first pass that does go out finds the movie built. Client-local. No INI change.

Derivation: `../docs/render-rate.md` §9.6.
"""

from __future__ import annotations

import struct

from ...asm import JB, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, jmp_rel32, va_to_offset

__all__ = [
    "ANCHORS",
    "DEFER_MS",
    "SECTION_NAME",
    "SpellStoreDeferralPatch",
    "cave_code",
    "defer_code",
    "defer_entry",
    "state_reset_code",
    "tick_stamp",
]

SECTION_NAME = ".spstore"  # 8 chars max: the PE name field truncates silently past 8
#: CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. Writable for the four
#: bytes of run-time state behind the code: the millisecond the panel was initialised at.
SECTION_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: `AptSpellStore::OnInitialized` (§9.6), the callback the movie fires once it is built. It
#: already resets this panel's cached state - `+0x2A2`, `+0x348`, `+0x34C`, `+0x350` and `+0x354`,
#: the last four to `-1` - and simply omits the twenty per-button state slots at `+0x2AC`. That
#: omission is the defect: `update` re-sends a button's state only when it differs from the value
#: cached there, and writes the cache whether or not the movie accepted the message. So a state
#: the movie refused - it drops one silently while the clip does not exist yet, and again while
#: the clip's `open` flag is false before frame 19 of `_fade_in` - is never repeated.
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
STORE_STATES = 0x2AC
STORE_STATES_END = 0x34C

#: `kernel32!GetTickCount` in the import table. The deferral is wall-clock rather than a count of
#: update passes on purpose: `update` runs off whatever pump is turning, and while the spell store
#: is up that is `GameEngine::update`'s modal `Sleep(5)` spin rather than the client frame - so a
#: pass count would mean a different wait at every frame rate.
GET_TICK_COUNT = 0x00BD02A0

#: How long `update` leaves the movie alone before it sends any button state. The engine has no
#: acknowledgement to wait on, so the only thing it can do is arrive late: the first send has to
#: land after the movie has built its button clips and run each one's ten-frame `_fade_in`. Not
#: derived from a measurement; if the book comes up blank and stays blank, raise this first.
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

#: Every site this patch reads or rewrites, holding the bytes the stock build holds there. The
#: tests plant exactly this to build a stand-in `game.dat`.
ANCHORS: dict[int, bytes] = {
    STATE_RESET: STATE_RESET_STOCK,
    **STATE_RESET_LANDING,
    UPDATE_LOOP: UPDATE_LOOP_STOCK,
    **UPDATE_LANDINGS,
}
_LANDINGS = {**STATE_RESET_LANDING, **UPDATE_LANDINGS}


def state_reset_code(base_va: int, tick_va: int) -> bytes:
    """The first half: invalidate the state cache and start the clock.

    Entered from the tail of `AptSpellStore::OnInitialized` with `ecx = this`. It writes `-1` over
    all twenty state slots - the same thing the surrounding handler already does to every other
    cached field, and a value no computed state (0..5) can equal - and stamps `tick_va` with the
    millisecond the panel was initialised at.

    **The stamp is the point.** Invalidating the cache here is on its own a no-op: this callback
    is what sets `+0x2A0`, the flag `update` checks before it does anything, so the first update
    after it is the same pass the original send was already happening on. What makes the
    invalidation matter is `defer_code` holding the loop off for `DEFER_MS` after this stamp.

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

    Runs in place of the loop's head. Until `DEFER_MS` has passed since the stamp, it takes the
    loop's own "all twenty done" exit, so `update` finishes the pass having sent nothing and the
    cache stays at the `-1` `state_reset_code` wrote. On the first pass after that it performs the
    two displaced instructions and drops into the loop, which finds a mismatch on every slot and
    sends the lot - once each, so every button's state animation plays normally.

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


def _layout(base_va: int) -> tuple[int, int]:
    """Where the deferral and the tick stamp land, given the section base (the reset is first).

    Every branch is `rel32` or a fixed-width `rel8`, so neither routine changes length with its
    address or with the stamp's - which is what lets the stamp's address be resolved by laying the
    code out once against a placeholder and measuring it.
    """
    defer_va = base_va + len(state_reset_code(base_va, 0))
    tick_va = defer_va + len(defer_code(defer_va, 0))
    return defer_va, tick_va


def cave_code(base_va: int) -> bytes:
    """Everything `.spstore` holds: the state reset, the deferral, the stamp."""
    defer_va, tick_va = _layout(base_va)
    return (
        state_reset_code(base_va, tick_va)
        + defer_code(defer_va, tick_va)
        + bytes(4)  # the tick stamp, written at run time by the state reset
    )


def defer_entry(cave_va: int) -> int:
    """Where `defer_code` starts, given the section base."""
    return _layout(cave_va)[0]


def tick_stamp(cave_va: int) -> int:
    """Where the four bytes of run-time state live: the tick the panel initialised at."""
    return _layout(cave_va)[1]


class SpellStoreDeferralPatch(Patch):
    """Invalidate the spellbook's button-state cache on open and defer the first send."""

    name = "spell-store-deferral"
    author = "officialNecro"
    runtime_verified = "yes"
    description = (
        "Fix the spellbook sometimes opening with nothing purchasable: the engine sends each "
        "button's state once and the movie silently drops one that arrives before the button has "
        "faded in. The patch re-sends every state half a second after the book opens, so the "
        "buttons are blank for that half-second. Happens at any frame rate, much more often above "
        "30 fps (render-rate, the accelerator). Client-local. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        problems = self._anchor_problems(data)
        if problems:
            raise ValueError("; ".join(problems))
        cave_va = allocate_section(data, SECTION_NAME, cave_code, SECTION_CHARACTERISTICS)
        for file_off, old, new, note in self._edits(data, cave_va):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
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
        # The stamp is run-time state, so only the code in front of it is compared.
        code = content[:-4]
        if bytes(data[cave_off : cave_off + len(code)]) != code:
            problems.append(f"{SECTION_NAME} does not hold the expected routines")
        for file_off, _old, new, note in edits:
            found = bytes(data[file_off : file_off + len(new)])
            if found != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {found.hex()}")
        return problems + self._anchor_problems(data)

    @staticmethod
    def _anchor_problems(data: bytes | bytearray) -> list[str]:
        """The two handler landings the routines jump to, which this patch does not rewrite."""
        problems: list[str] = []
        for va, expected in _LANDINGS.items():
            offset = va_to_offset(data, va)
            if offset is None:
                problems.append(f"the landing at 0x{va:08X} is not mapped")
                continue
            found = bytes(data[offset : offset + len(expected)])
            if found != expected:
                problems.append(
                    f"the landing at 0x{va:08X} is {found.hex()}, not {expected.hex()} - this is "
                    "not the build this patch was derived against"
                )
        return problems

    @staticmethod
    def _edits(data: bytes | bytearray, cave_va: int) -> list[tuple[int, bytes, bytes, str]]:
        """The two hooks, as `(file offset, stock, patched, note)`."""
        out: list[tuple[int, bytes, bytes, str]] = []
        for va, stock, target, note in (
            (STATE_RESET, STATE_RESET_STOCK, cave_va, "spell store state reset -> the cave"),
            (UPDATE_LOOP, UPDATE_LOOP_STOCK, defer_entry(cave_va), "spell store update loop"),
        ):
            offset = va_to_offset(data, va)
            if offset is None:
                raise ValueError(f"{note}: VA 0x{va:08X} is not mapped")
            out.append((offset, stock, jmp_rel32(va, target, len(stock)), note))
        return out
