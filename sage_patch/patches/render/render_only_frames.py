"""Keep client code right when a frame is drawn without the client frame advancing.

The accelerator (`accel-module`) raises the frame rate by drawing *render-only* frames: the
engine's own scheduler draws them and runs the game-client update, but the client frame counter
stays at 30 a second. Engine code that assumes one client update per client frame then goes
wrong, and this patch fixes the cases measured to matter. On a stock binary every draw is a new
client frame, so each fix reduces to what stock does.

- **Locomotor rocking** (ships, wheels, treads, hover, wings). `Drawable::calcPhysicsXform`
  (`0x0067BDC0`) stamps the client frame it last ran on and answers "no physics transform" on a
  second call in the same client frame, so every render-only frame draws the hull level and the
  next one tilted again - a 30 Hz flicker. The patch keeps the last transform beside the
  drawable's locomotor state and re-applies it on that second call.
- **Scripted camera moves** (rotate - a victory spin - zoom, pitch, reset, move-to and spline
  paths - a shellmap). `W3DView` steps each once per view update, which the accelerator runs
  once per *drawn* frame: the frame-counted moves (`ms / [0x00DC7A8C]`, 33 at 30 fps, then an
  `inc` per update) and the path moves (a fixed 33 ms per update) all finish in half their
  scripted time. The patch counts them in milliseconds and steps them by the real time elapsed,
  which is right at any frame rate and as smooth as the frames are.
- **Script fades** (`CAMERA_FADE_*`, to white or black). The script engine steps the fade once per
  logic frame and the view blends the last two steps with the interpolation alpha; it takes the
  new step when the once-per-logic-frame latch (`0x0063252F`, sub-frame 2) fires. A render-only
  frame sees the same sub-frame as the frame after it, so the latch fires twice, the second time
  sets "previous" to "current", and the blend collapses into 200 ms steps. The patch lets the
  view take a step at most once per client frame.

Client-local. No INI change.

Derivation: `../docs/render-only-frames.md`.
"""

from __future__ import annotations

import struct

from ...asm import JBE, JE, JNE, JNZ, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, call_rel32, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "COUNTER_IDIVS",
    "COUNTER_IMULS",
    "COUNTER_STEPS",
    "ELAPSED_PUSHES",
    "LOCO_INFO_ALLOCS",
    "SECTION_NAME",
    "RenderOnlyFramesPatch",
    "cave_code",
    "counter_step_code",
    "elapsed_push_code",
    "fade_latch_code",
    "layout",
    "physics_wrapper_code",
]

SECTION_NAME = ".rofr"  # 8 chars max: the PE name field truncates silently past 8
#: CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. The cached transforms
#: live on the heap beside each drawable; the section holds the camera steps' clocks, the constant
#: 1 the moves' conversions are pointed at, and the client frame the fade last stepped on.
SECTION_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: `TheGameClient` and the `getFrame` slot in its vtable (the same pair `render-rate`'s particle
#: gate and `calcPhysicsXform` itself use).
GAME_CLIENT = 0x00DE4388
GET_FRAME_SLOT = 0x7C

#: `Drawable::calcPhysicsXform(PhysicsXformInfo&)`, `__thiscall`, `ret 4`, returning in `al`
#: whether it produced a transform. It reads the client frame, compares it with the stamp at
#: `+0xAC` of the object's current locomotor, and returns 0 at once when they are equal; otherwise
#: it stores the stamp and dispatches on `Locomotor.Appearance` (`+0x74`) to the per-appearance
#: integrator (`SHIP`, case 9, is `0x006732DC`).
CALC_PHYSICS_XFORM = 0x0067BDC0
#: Its one caller, inside `Drawable::applyPhysicsXform` (`0x0067BE90`): the caller zeroes the
#: four-float info on its stack, calls, and on 0 skips applying anything to the matrix.
CALC_CALL = 0x0067BF39
CALC_CALL_STOCK = call_rel32(CALC_CALL, CALC_PHYSICS_XFORM)
#: The `test al, al` / `je` the caller performs on the answer, asserted so the wrapper's contract
#: (result in `al`) is the one the caller reads.
CALC_RESULT_TEST = 0x0067BF3E
CALC_RESULT_TEST_BYTES = bytes.fromhex("84c00f84")

#: `Drawable+0x13C` is the drawable's `DrawableLocoInfo`, the per-drawable state the integrators
#: keep (wave phases, pitch and roll springs). Every one of its five allocation sites is
#: `push 0x58` / `call operator new` followed by its constructor `0x00670392`, and the
#: constructor has no other caller, so these five are every `DrawableLocoInfo` in the game.
DRAWABLE_LOCO_INFO = 0x13C
LOCO_INFO_ALLOCS = (0x00670B28, 0x006732F8, 0x00677042, 0x0067A8E0, 0x0067B7C6)
LOCO_INFO_SIZE = 0x58
#: The tail this patch adds: the four-float transform, the client frame it was computed on, and
#: that frame xor `CACHE_CHECK`. The heap does not zero the block, so the check is what keeps a
#: tail of leftover bytes from being taken for a transform of this frame.
CACHE = LOCO_INFO_SIZE
CACHE_FRAME = CACHE + 0x10
CACHE_CHECK_FIELD = CACHE + 0x14
CACHE_CHECK = 0x52304652  # "RF0R"
LOCO_INFO_PATCHED_SIZE = CACHE + 0x18

#: `TheW3DFrameLengthInMsec`: `1000 / clientRate` as an integer, stored once at start-up
#: (`0x00BC146C`). 33 at the stock rate.
FRAME_LENGTH = 0x00DC7A8C
#: `winmm!timeGetTime` in the import table.
TIME_GET_TIME = 0x00BD0920

#: The timed camera moves on `W3DView`. Each keeps a frame count and a frame counter, and its
#: per-update step only ever reads them as a ratio (`cur / num`, and `cur >= num (+ hold)` to
#: finish); every ease curve is built from the raw milliseconds. So each can be counted in
#: milliseconds instead of frames, as long as every writer and reader of the pair agrees.
#:
#: `(step VA, counter offset, what)`. Each step is `inc dword [esi+counter]`, six bytes, with
#: `esi` the view; the setups that size them are `COUNTER_IDIVS`.
COUNTER_STEPS = (
    (0x0048A420, 0x1B0, "rotation"),  # rotateCamera / toward object / toward position
    (0x00486615, 0x20C, "zoom"),  # +0xEC, ZOOM_CAMERA
    (0x004866AE, 0x230, "view +0xF0 move"),
    (0x0048675F, 0x1E4, "pitch"),  # +0xF4, PITCH_CAMERA
    (0x004867F8, 0x25C, "view +0xF8 move"),
    (0x004865E1, 0x1A0, "reset"),  # +0xC8, RESET_CAMERA
)
INC_STOCK = bytes.fromhex("ff86")

#: The conversions into and out of those frames, each an operand that reads `FRAME_LENGTH`.
#: `idiv` in the setups: `rotateCamera` (view vtable `+0xCC`), `rotateCameraTowardObject`
#: (`+0xD0`, duration and hold), `rotateCameraTowardPosition` (`+0xD4`), `+0xEC`, `+0xF0`,
#: `+0xF4`, `+0xF8` and `+0xC8`. `imul` in the rotation's two time-remaining getters (`+0x7C`,
#: `+0x88`). The patch points each operand at a 1, which makes the counters milliseconds and
#: leaves the instructions in place.
COUNTER_IDIVS = (
    0x00485DD4,
    0x00485E7A,
    0x00485E9A,
    0x004886B1,
    0x004887F4,
    0x0048887A,
    0x0048892E,
    0x004889B2,
    0x0048D3C5,
)
IDIV_STOCK = bytes.fromhex("f73d") + struct.pack("<I", FRAME_LENGTH)
COUNTER_IMULS = (0x00485F62, 0x00486279)
IMUL_STOCK = bytes.fromhex("0faf05") + struct.pack("<I", FRAME_LENGTH)

#: The path moves (`MOVE_CAMERA_TO`, `MOVE_CAMERA_ALONG_SPLINE_PATH` and its locator twin) keep
#: milliseconds already: their steps, `0x00489817(ms, locator)` and `0x0048688A(ms)`, add their
#: argument to an elapsed total. What is wrong is the argument: the view update hands them a
#: fixed `push [FRAME_LENGTH]` per call. Each of these three becomes a call that leaves the real
#: elapsed milliseconds on the stack in the push's place.
ELAPSED_PUSHES = (0x0048A9F2, 0x0048AAE5, 0x0048AB06)
PUSH_STOCK = bytes.fromhex("ff35") + struct.pack("<I", FRAME_LENGTH)

#: The most one step may advance, in milliseconds - one logic frame. A counter step past it
#: advances by this much; a path step past it (which has no "first step" to recognise) advances by
#: one stock frame, which is also what its first step after an idle gap looks like.
STEP_CLAMP = 200

#: The once-per-logic-frame latch (`render-rate.md` §9.2): true while `TheGameEngine`'s sub-frame
#: (`+0x34`) is 2. `__thiscall` on `TheGameEngine`, no arguments, answer in `al`.
LOGIC_LATCH = 0x0063252F
#: Its call in `W3DView::draw`, where a true answer takes the script engine's new fade step:
#: `previous (+0xCC) = current (+0xD0)`, `current = TheScriptEngine+0x1A248`. The draw then
#: blends the two with `TheGameEngine+0x3C` (`0x0048E3AD`).
FADE_LATCH_CALL = 0x0048E2D3
FADE_LATCH_CALL_STOCK = call_rel32(FADE_LATCH_CALL, LOGIC_LATCH)
#: `mov ecx, [TheGameEngine]` in front of it and `test al, al` / `je` behind it, asserted so the
#: wrapper is entered with the `this` and read for the answer it expects.
FADE_LATCH_SETUP = 0x0048E2CD
FADE_LATCH_SETUP_BYTES = bytes.fromhex("8b0d2443de00")
FADE_LATCH_TEST = 0x0048E2D8
FADE_LATCH_TEST_BYTES = bytes.fromhex("84c0745b")

#: Every site this patch reads or rewrites, holding the bytes the stock build holds there.
ANCHORS: dict[int, bytes] = {
    CALC_CALL: CALC_CALL_STOCK,
    CALC_RESULT_TEST: CALC_RESULT_TEST_BYTES,
    **{va: bytes((0x6A, LOCO_INFO_SIZE)) for va in LOCO_INFO_ALLOCS},
    **dict.fromkeys(COUNTER_IDIVS, IDIV_STOCK),
    **dict.fromkeys(COUNTER_IMULS, IMUL_STOCK),
    **{va: INC_STOCK + struct.pack("<I", field) for va, field, _what in COUNTER_STEPS},
    **dict.fromkeys(ELAPSED_PUSHES, PUSH_STOCK),
    FADE_LATCH_CALL: FADE_LATCH_CALL_STOCK,
    FADE_LATCH_SETUP: FADE_LATCH_SETUP_BYTES,
    FADE_LATCH_TEST: FADE_LATCH_TEST_BYTES,
}
#: The anchors this patch reads and does not rewrite.
_READ_ONLY = {
    CALC_RESULT_TEST: CALC_RESULT_TEST_BYTES,
    FADE_LATCH_SETUP: FADE_LATCH_SETUP_BYTES,
    FADE_LATCH_TEST: FADE_LATCH_TEST_BYTES,
}


def physics_wrapper_code(base_va: int) -> bytes:
    """Stand in for `calcPhysicsXform` at its one call site: call it, then cache or re-apply.

    `__thiscall` with the info pointer on the stack and `ret 4`, like the function it wraps, with
    the answer in `al`. After the real call:

    - **It produced a transform:** copy the four floats into the locomotor state's tail and stamp
      the tail with this client frame (and its check).
    - **It did not:** if the tail holds a transform computed *in this client frame*, copy it back
      into the info and answer 1. The only way `calcPhysicsXform` refuses after succeeding in the
      same client frame is its own same-frame stamp, so a refusal for any other reason (no
      locomotor, an appearance without physics) is left alone.

    `ebx`, `esi` and `edi` are saved; `ecx` and `edx` are free under `__thiscall`.
    """
    a = Asm(base_va)
    a.emit(0x53, 0x56, 0x57)  # push ebx / push esi / push edi
    a.emit(0x8B, 0xF9)  # mov edi, ecx            the drawable
    a.emit(0x8B, 0x74, 0x24, 0x10)  # mov esi, [esp+0x10]  the info
    a.emit(0x56)  # push esi
    a.call_absolute(CALC_PHYSICS_XFORM)  # ecx is still the drawable
    a.emit(0x8B, 0x9F, struct.pack("<I", DRAWABLE_LOCO_INFO))  # mov ebx, [edi+0x13C]
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JE, "out")  # no locomotor state: nothing to keep
    a.emit(0x50)  # push eax                  the answer
    a.emit(0x8B, 0x0D, struct.pack("<I", GAME_CLIENT))  # mov ecx, [TheGameClient]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "no_client")
    a.emit(0x8B, 0x11)  # mov edx, [ecx]
    a.emit(0xFF, 0x52, GET_FRAME_SLOT)  # call [edx+0x7C]   GameClient::getFrame
    a.emit(0x8B, 0xC8)  # mov ecx, eax            the client frame
    a.emit(0x58)  # pop eax
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "miss")
    for field in range(0, 0x10, 4):  # copy the transform into the cache
        a.emit(0x8B, 0x56, field)  # mov edx, [esi+field]
        a.emit(0x89, 0x93, struct.pack("<I", CACHE + field))  # mov [ebx+CACHE+field], edx
    a.emit(0x89, 0x8B, struct.pack("<I", CACHE_FRAME))  # mov [ebx+frame], ecx
    a.emit(0x81, 0xF1, struct.pack("<I", CACHE_CHECK))  # xor ecx, CHECK
    a.emit(0x89, 0x8B, struct.pack("<I", CACHE_CHECK_FIELD))  # mov [ebx+check], ecx
    a.jmp("out")
    a.label("miss")
    a.emit(0x3B, 0x8B, struct.pack("<I", CACHE_FRAME))  # cmp ecx, [ebx+frame]
    a.jcc(JNE, "out")  # not computed this client frame
    a.emit(0x81, 0xF1, struct.pack("<I", CACHE_CHECK))  # xor ecx, CHECK
    a.emit(0x3B, 0x8B, struct.pack("<I", CACHE_CHECK_FIELD))  # cmp ecx, [ebx+check]
    a.jcc(JNE, "out")  # leftover bytes, not a cache
    for field in range(0, 0x10, 4):  # copy the cache back into the info
        a.emit(0x8B, 0x93, struct.pack("<I", CACHE + field))  # mov edx, [ebx+CACHE+field]
        a.emit(0x89, 0x56, field)  # mov [esi+field], edx
    a.emit(0xB0, 0x01)  # mov al, 1
    a.jmp("out")
    a.label("no_client")
    a.emit(0x58)  # pop eax
    a.label("out")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi / pop esi / pop ebx
    a.emit(0xC2, 0x04, 0x00)  # ret 4
    return a.finish()


def counter_step_code(base_va: int, field: int, last_va: int) -> bytes:
    """Advance a camera move's counter by the milliseconds since its last step, in place of `inc`.

    Called from the step's `inc` with `esi = this`. A move's first step (its setup zeroes the
    counter) advances one stock frame, `FRAME_LENGTH`, as the `inc` would have; every later one
    advances by `timeGetTime` minus the time of this counter's step before, clamped to
    `STEP_CLAMP`. Each counter keeps its own time, because several moves can run at once. The
    subtraction is unsigned, so it is right across the clock's wrap. `eax`, `ecx` and `edx` are
    preserved.
    """
    a = Asm(base_va)
    a.emit(0x50, 0x51, 0x52)  # push eax / push ecx / push edx
    a.emit(0xFF, 0x15, struct.pack("<I", TIME_GET_TIME))  # call [timeGetTime]
    a.emit(0x83, 0xBE, struct.pack("<I", field), 0x00)  # cmp dword [esi+field], 0
    a.jcc(JNZ, "running")
    a.emit(0x8B, 0x0D, struct.pack("<I", FRAME_LENGTH))  # mov ecx, [FRAME_LENGTH]
    a.jmp("advance")
    a.label("running")
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.emit(0x2B, 0x0D, struct.pack("<I", last_va))  # sub ecx, [last]
    a.emit(0x81, 0xF9, struct.pack("<I", STEP_CLAMP))  # cmp ecx, CLAMP
    a.jcc(JBE, "advance")
    a.emit(0xB9, struct.pack("<I", STEP_CLAMP))  # mov ecx, CLAMP
    a.label("advance")
    a.emit(0xA3, struct.pack("<I", last_va))  # mov [last], eax
    a.emit(0x01, 0x8E, struct.pack("<I", field))  # add [esi+field], ecx
    a.emit(0x5A, 0x59, 0x58)  # pop edx / pop ecx / pop eax
    a.emit(0xC3)  # ret
    return a.finish()


def elapsed_push_code(base_va: int, last_va: int, scratch_va: int) -> bytes:
    """Leave the milliseconds since this site last ran on the stack, in place of `push [len]`.

    Entered by a `call` where the push was, so the return address sits where the pushed value
    must: the routine writes the value over it and returns by jumping to the saved address, which
    leaves the stack exactly as the push did. A gap longer than `STEP_CLAMP` (a new move, or a
    hitch) counts as one stock frame. Every register is preserved; the flags are not, and no site
    reads them after the push.
    """
    a = Asm(base_va)
    a.emit(0x50, 0x51, 0x52)  # push eax / push ecx / push edx
    a.emit(0xFF, 0x15, struct.pack("<I", TIME_GET_TIME))  # call [timeGetTime]
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.emit(0x2B, 0x0D, struct.pack("<I", last_va))  # sub ecx, [last]
    a.emit(0xA3, struct.pack("<I", last_va))  # mov [last], eax
    a.emit(0x81, 0xF9, struct.pack("<I", STEP_CLAMP))  # cmp ecx, CLAMP
    a.jcc(JBE, "value")
    a.emit(0x8B, 0x0D, struct.pack("<I", FRAME_LENGTH))  # mov ecx, [FRAME_LENGTH]
    a.label("value")
    a.emit(0x8B, 0x54, 0x24, 0x0C)  # mov edx, [esp+0xC]   the return address
    a.emit(0x89, 0x4C, 0x24, 0x0C)  # mov [esp+0xC], ecx   the value, where the push puts it
    a.emit(0x89, 0x15, struct.pack("<I", scratch_va))  # mov [scratch], edx
    a.emit(0x5A, 0x59, 0x58)  # pop edx / pop ecx / pop eax
    a.emit(0xFF, 0x25, struct.pack("<I", scratch_va))  # jmp [scratch]
    return a.finish()


def fade_latch_code(base_va: int, last_va: int) -> bytes:
    """Stand in for the latch at the fade's call: true at most once per client frame.

    Calls the real latch (`ecx` is `TheGameEngine`, as the caller set it). A true answer is passed
    on only if the client frame differs from the one stored at `last_va`, which it then becomes.
    On a stock binary every draw is a new client frame, so the answer is the latch's own.
    `ecx` and `edx` are free under `__thiscall`; the caller reads only `al`.
    """
    a = Asm(base_va)
    a.call_absolute(LOGIC_LATCH)
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "out")  # not the latch's sub-frame
    a.emit(0x8B, 0x0D, struct.pack("<I", GAME_CLIENT))  # mov ecx, [TheGameClient]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "yes")  # nothing to ask: the latch's own answer
    a.emit(0x8B, 0x11)  # mov edx, [ecx]
    a.emit(0xFF, 0x52, GET_FRAME_SLOT)  # call [edx+0x7C]   GameClient::getFrame
    a.emit(0x3B, 0x05, struct.pack("<I", last_va))  # cmp eax, [last]
    a.jcc(JE, "no")  # already stepped in this client frame
    a.emit(0xA3, struct.pack("<I", last_va))  # mov [last], eax
    a.label("yes")
    a.emit(0xB0, 0x01)  # mov al, 1
    a.emit(0xC3)  # ret
    a.label("no")
    a.emit(0x32, 0xC0)  # xor al, al
    a.label("out")
    a.emit(0xC3)  # ret
    return a.finish()


class _Layout:
    """Where every routine and dword of `.rofr` lands, given the section base.

    Code first: the physics wrapper, one counter step per `COUNTER_STEPS` entry, one elapsed push
    per `ELAPSED_PUSHES` entry, the fade latch. Then the constant 1, and last the run-time dwords:
    the fade's client frame, the push routines' return slot, and one clock per counter and per
    push. Every branch is `rel32` or a fixed-width `rel8`, so no routine changes length with its
    address, which is what lets the data addresses be measured from placeholder layouts.
    """

    def __init__(self, base_va: int) -> None:
        at = base_va + len(physics_wrapper_code(base_va))
        self.counter_steps: list[int] = []
        for _va, field, _what in COUNTER_STEPS:
            self.counter_steps.append(at)
            at += len(counter_step_code(at, field, 0))
        self.elapsed_pushes: list[int] = []
        for _va in ELAPSED_PUSHES:
            self.elapsed_pushes.append(at)
            at += len(elapsed_push_code(at, 0, 0))
        self.fade_latch = at
        at += len(fade_latch_code(at, 0))
        self.one = at
        self.fade_frame = at + 4
        self.scratch = at + 8
        clocks = at + 12
        self.counter_clocks = [clocks + 4 * i for i in range(len(COUNTER_STEPS))]
        clocks += 4 * len(COUNTER_STEPS)
        self.push_clocks = [clocks + 4 * i for i in range(len(ELAPSED_PUSHES))]


#: The run-time dwords at the end of the section, which `verify` does not compare.
RUNTIME_BYTES = 4 * (2 + len(COUNTER_STEPS) + len(ELAPSED_PUSHES))


def layout(cave_va: int) -> _Layout:
    """Where everything in `.rofr` lands, given the section base."""
    return _Layout(cave_va)


def cave_code(base_va: int) -> bytes:
    """Everything `.rofr` holds."""
    lay = _Layout(base_va)
    code = physics_wrapper_code(base_va)
    for (_va, field, _what), at, clock in zip(
        COUNTER_STEPS, lay.counter_steps, lay.counter_clocks, strict=True
    ):
        code += counter_step_code(at, field, clock)
    for at, clock in zip(lay.elapsed_pushes, lay.push_clocks, strict=True):
        code += elapsed_push_code(at, clock, lay.scratch)
    code += fade_latch_code(lay.fade_latch, lay.fade_frame)
    code += struct.pack("<I", 1)  # what the counters' conversions divide and multiply by
    code += struct.pack("<I", 0xFFFFFFFF)  # the client frame the fade last stepped on: none yet
    return code + bytes(RUNTIME_BYTES - 4)  # the return slot and the clocks


class RenderOnlyFramesPatch(Patch):
    """Fix client code that assumes every drawn frame is a new client frame."""

    name = "render-only-frames"
    author = "officialNecro"
    description = (
        "Companion to accel-module: fix what the accelerator's extra render-only frames break, "
        "where a frame is drawn without the client frame advancing. Ships and other rocking "
        "vehicles no longer flicker level every other frame; scripted camera moves (rotate, "
        "zoom, pitch, reset, move-to, spline paths: a victory spin, a shellmap) take their "
        "scripted time instead of half of it; and script fades to white or black blend smoothly "
        "instead of in 200 ms steps. Does nothing visible without the accelerator. "
        "Client-local. No INI change"
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
        code = content[:-RUNTIME_BYTES]
        if bytes(data[cave_off : cave_off + len(code)]) != code:
            problems.append(f"{SECTION_NAME} does not hold the expected routines")
        for file_off, _old, new, note in edits:
            found = bytes(data[file_off : file_off + len(new)])
            if found != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {found.hex()}")
        return problems + self._anchor_problems(data)

    @staticmethod
    def _anchor_problems(data: bytes | bytearray) -> list[str]:
        """The code around the two wrapped calls, which the wrappers' contracts depend on and
        which this patch does not rewrite."""
        problems: list[str] = []
        for va, expected in _READ_ONLY.items():
            offset = va_to_offset(data, va)
            if offset is None:
                problems.append(f"0x{va:08X} is not mapped")
                continue
            found = bytes(data[offset : offset + len(expected)])
            if found != expected:
                problems.append(
                    f"the anchor at 0x{va:08X} is {found.hex()}, not {expected.hex()} - this is "
                    "not the build this patch was derived against"
                )
        return problems

    @staticmethod
    def _edits(data: bytes | bytearray, cave_va: int) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte range this patch rewrites, as `(file offset, stock, patched, note)`."""
        lay = _Layout(cave_va)
        wanted = [
            (CALC_CALL, CALC_CALL_STOCK, call_rel32(CALC_CALL, cave_va), "calcPhysicsXform call"),
            *(
                (
                    va,
                    bytes((0x6A, LOCO_INFO_SIZE)),
                    bytes((0x6A, LOCO_INFO_PATCHED_SIZE)),
                    f"DrawableLocoInfo size 0x{va:08X}",
                )
                for va in LOCO_INFO_ALLOCS
            ),
            *(
                (
                    va,
                    IDIV_STOCK,
                    IDIV_STOCK[:2] + struct.pack("<I", lay.one),
                    f"ms -> frames {va:#x}",
                )
                for va in COUNTER_IDIVS
            ),
            *(
                (
                    va,
                    IMUL_STOCK,
                    IMUL_STOCK[:3] + struct.pack("<I", lay.one),
                    f"frames -> ms {va:#x}",
                )
                for va in COUNTER_IMULS
            ),
            *(
                (
                    va,
                    INC_STOCK + struct.pack("<I", field),
                    call_rel32(va, at) + b"\x90",
                    f"{what} step",
                )
                for (va, field, what), at in zip(COUNTER_STEPS, lay.counter_steps, strict=True)
            ),
            *(
                (va, PUSH_STOCK, call_rel32(va, at) + b"\x90", f"path step time {va:#x}")
                for va, at in zip(ELAPSED_PUSHES, lay.elapsed_pushes, strict=True)
            ),
            (
                FADE_LATCH_CALL,
                FADE_LATCH_CALL_STOCK,
                call_rel32(FADE_LATCH_CALL, lay.fade_latch),
                "fade latch call",
            ),
        ]
        out: list[tuple[int, bytes, bytes, str]] = []
        for va, old, new, note in wanted:
            offset = va_to_offset(data, va)
            if offset is None:
                raise ValueError(f"{note}: VA 0x{va:08X} is not mapped")
            out.append((offset, old, new, note))
        return out
