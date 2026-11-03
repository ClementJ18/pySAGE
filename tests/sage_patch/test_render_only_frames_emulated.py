"""`render-only-frames`, executed.

The two routines run under Unicorn, over the real `game.dat` when this checkout has one and the
stand-in otherwise. `calcPhysicsXform`, `GameClient::getFrame` and `timeGetTime` are answered in
Python, so each test sets the client frame and the clock and checks what the routine leaves.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")
pytest.importorskip("pefile", reason="the emulator harness maps the image with pefile")

from unicorn.x86_const import UC_X86_REG_ESP  # noqa: E402

from sage_patch.patches.render.render_only_frames import (  # noqa: E402
    CALC_PHYSICS_XFORM,
    COUNTER_STEPS,
    DRAWABLE_LOCO_INFO,
    FRAME_LENGTH,
    GAME_CLIENT,
    GET_FRAME_SLOT,
    LOCO_INFO_PATCHED_SIZE,
    LOGIC_LATCH,
    SECTION_NAME,
    STEP_CLAMP,
    TIME_GET_TIME,
    RenderOnlyFramesPatch,
    layout,
)
from sage_patch.utils import find_section  # noqa: E402

from .save_machine import REGISTERS, Machine  # noqa: E402
from .synthetic import render_only_frames_image  # noqa: E402

REAL_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"
TILT = (0.1, -0.2, 0.3, 4.0)


@pytest.fixture(scope="module")
def image() -> bytes:
    if REAL_GAME_DAT.exists():
        data = bytearray(REAL_GAME_DAT.read_bytes())
    else:
        data = render_only_frames_image()
    RenderOnlyFramesPatch().apply(data)
    return bytes(data)


@dataclass
class World:
    """One drawable with locomotor state, a game client with a frame, and a clock."""

    image: bytes
    frame: int = 100
    now: int = 50_000
    #: The stamp `calcPhysicsXform` keeps: it refuses a second call in the same client frame.
    stamp: int = -1
    calls: int = 0
    produce: bool = True
    latch: bool = True
    clobbered: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        m = self.m = Machine(self.image)
        self.cave = find_section(self.image, SECTION_NAME)[0]
        self.lay = layout(self.cave)
        self.loco = m.alloc(LOCO_INFO_PATCHED_SIZE, b"\xa5" * LOCO_INFO_PATCHED_SIZE)
        self.drawable = m.alloc(0x400, bytes(0x400))
        m.write32(self.drawable + DRAWABLE_LOCO_INFO, self.loco)
        vtable = m.alloc(0x100, bytes(0x100))
        m.write32(vtable + GET_FRAME_SLOT, m.stub(None, self._get_frame))
        client = m.alloc(0x10, bytes(0x10))
        m.write32(client, vtable)
        m.ensure(GAME_CLIENT)
        m.write32(GAME_CLIENT, client)
        m.ensure(TIME_GET_TIME)
        m.write32(TIME_GET_TIME, m.stub(None, self._time))
        m.stub(CALC_PHYSICS_XFORM, self._calc)
        m.stub(LOGIC_LATCH, self._latch)
        self.engine = m.alloc(0x40, bytes(0x40))
        m.ensure(FRAME_LENGTH)
        m.write32(FRAME_LENGTH, 33)  # what start-up stores there at 30 fps (0x00BC146C)
        self.view = m.alloc(0x400, bytes(0x400))

    def _clobber(self) -> None:
        self.m.uc.reg_write(REGISTERS["ecx"], 0xDEAD0001)
        self.m.uc.reg_write(REGISTERS["edx"], 0xDEAD0002)

    def _get_frame(self, m: Machine) -> None:
        self._clobber()
        m.ret(0, self.frame)

    def _time(self, m: Machine) -> None:
        self._clobber()
        m.ret(0, self.now)

    def _latch(self, m: Machine) -> None:
        assert m.reg("ecx") == self.engine, "the latch called on the wrong this"
        self._clobber()
        m.ret(0, 0xFFFFFF00 | int(self.latch))

    def fade_step_taken(self) -> bool:
        """What the fade's draw sees from its latch call."""
        return bool(self.m.call(self.lay.fade_latch, ecx=self.engine) & 0xFF)

    def _calc(self, m: Machine) -> None:
        assert m.reg("ecx") == self.drawable, "calcPhysicsXform called on the wrong this"
        info = m.arg(0)
        self.calls += 1
        answer = 0
        if self.produce and self.stamp != self.frame:
            self.stamp = self.frame
            m.uc.mem_write(info, struct.pack("<4f", *TILT))
            answer = 1
        self._clobber()
        m.ret(4, answer)

    def apply_physics(self) -> tuple[int, tuple[float, ...]]:
        """What the caller sees: the answer in `al` and the info it handed in, zeroed first."""
        info = self.m.alloc(0x10, bytes(0x10))
        answer = self.m.call(self.cave, info, ecx=self.drawable, ebx=0xB0B0, esi=0x5151, edi=0xD1D1)
        assert self.m.stopped_at is not None, "the wrapper did not return"
        for name, value in (("ebx", 0xB0B0), ("esi", 0x5151), ("edi", 0xD1D1)):
            assert self.m.reg(name) == value, f"{name} not preserved"
        return answer & 0xFF, struct.unpack("<4f", bytes(self.m.uc.mem_read(info, 0x10)))

    def step(self, index: int = 0) -> int:
        """Run counter step `index` (0 is the rotation) and return its counter after it."""
        self.m.call(self.lay.counter_steps[index], esi=self.view, eax=0xA, ecx=0xC, edx=0xD)
        for name, value in (("eax", 0xA), ("ecx", 0xC), ("edx", 0xD), ("esi", self.view)):
            assert self.m.reg(name) == value, f"{name} not preserved"
        return self.m.read32(self.view + COUNTER_STEPS[index][1])

    def pushed(self, index: int = 0) -> int:
        """Run path push `index` as its call site does and return what it left on the stack.

        The routine is entered by a `call` from a stand-in site that is followed by a stop, so the
        test sees the stack exactly as the instruction after the push would."""
        m = self.m
        site = m.alloc(0x20, bytes(0x20))
        after = site + 5
        m.uc.mem_write(site, b"\xe8" + struct.pack("<i", self.lay.elapsed_pushes[index] - after))
        m.stop_at(after)
        esp = m.frame() + 0x40
        m.write32(esp - 4, 0x5EED5EED)  # what the push overwrites must not leak through
        m.run(site, esp, eax=0xA, ecx=0xC, edx=0xD)
        assert m.stopped_at == after, "the routine did not return to the site"
        sp = m.uc.reg_read(UC_X86_REG_ESP)
        assert sp == esp - 4, "the stack is not where a push leaves it"
        for name, value in (("eax", 0xA), ("ecx", 0xC), ("edx", 0xD)):
            assert m.reg(name) == value, f"{name} not preserved"
        return m.read32(sp)


@pytest.fixture
def world(image: bytes) -> World:
    return World(image)


def _close(got: tuple[float, ...]) -> bool:
    return all(abs(a - b) < 1e-6 for a, b in zip(got, TILT, strict=True))


class TestPhysics:
    def test_a_fresh_transform_passes_through(self, world: World) -> None:
        answer, info = world.apply_physics()
        assert answer == 1
        assert _close(info)

    def test_a_second_draw_in_the_same_client_frame_gets_the_same_transform(
        self, world: World
    ) -> None:
        """The render-only frame: stock answers 0 here and the hull is drawn level."""
        world.apply_physics()
        answer, info = world.apply_physics()
        assert world.calls == 2, "the real function must still be asked"
        assert answer == 1
        assert _close(info)

    def test_a_new_client_frame_computes_afresh(self, world: World) -> None:
        world.apply_physics()
        world.frame += 1
        answer, info = world.apply_physics()
        assert answer == 1 and _close(info)
        assert world.stamp == world.frame

    def test_a_cache_from_an_earlier_frame_is_not_reused(self, world: World) -> None:
        """A refusal for another reason (no locomotor any more) in a later frame stays a refusal."""
        world.apply_physics()
        world.frame += 1
        world.produce = False
        answer, info = world.apply_physics()
        assert answer == 0
        assert info == (0.0, 0.0, 0.0, 0.0)

    def test_leftover_heap_bytes_are_not_taken_for_a_cache(self, world: World) -> None:
        """The heap does not zero the block. Plant a tail whose frame matches but whose check
        does not, and refuse."""
        world.produce = False
        world.m.write32(world.loco + 0x68, world.frame)
        answer, _info = world.apply_physics()
        assert answer == 0

    def test_no_locomotor_state_is_left_alone(self, world: World) -> None:
        world.m.write32(world.drawable + DRAWABLE_LOCO_INFO, 0)
        world.produce = False
        answer, _info = world.apply_physics()
        assert answer == 0


class TestFadeLatch:
    def test_off_the_latch_sub_frame_nothing_is_taken(self, world: World) -> None:
        world.latch = False
        assert not world.fade_step_taken()

    def test_the_first_draw_on_the_latch_takes_the_step(self, world: World) -> None:
        assert world.fade_step_taken()

    def test_the_second_draw_in_the_same_client_frame_does_not(self, world: World) -> None:
        """The render-only frame and the frame after it share the sub-frame and the client
        frame; stock takes the step twice, which zeroes the blend."""
        assert world.fade_step_taken()
        assert not world.fade_step_taken()

    def test_the_next_logic_frame_takes_its_step(self, world: World) -> None:
        assert world.fade_step_taken()
        world.frame += 6
        assert world.fade_step_taken()

    def test_one_draw_per_client_frame_is_stock(self, world: World) -> None:
        """Without the accelerator every draw is a new client frame, and the answer is always
        the latch's own."""
        for latch in (True, False, False, True, False, True):
            world.latch = latch
            world.frame += 1
            assert world.fade_step_taken() is latch


class TestPathPush:
    def test_a_gap_counts_as_one_stock_frame(self, world: World) -> None:
        """The first step of a move: its clock is from the last move, long ago."""
        assert world.pushed() == 33

    def test_later_steps_push_the_elapsed_time(self, world: World) -> None:
        world.pushed()
        world.now += 16
        assert world.pushed() == 16
        world.now += 17
        assert world.pushed() == 17

    def test_a_hitch_counts_as_one_stock_frame(self, world: World) -> None:
        world.pushed()
        world.now += 5_000
        assert world.pushed() == 33

    def test_each_site_keeps_its_own_clock(self, world: World) -> None:
        world.pushed(0)
        world.now += 20
        assert world.pushed(1) == 33, "site 1 must not see site 0's clock"
        world.now += 20
        assert world.pushed(0) == 40

    def test_thirty_and_sixty_updates_a_second_cover_the_same_path(self, image: bytes) -> None:
        totals = []
        for rate in (30, 60):
            world = World(image)
            total = world.pushed()
            for _ in range(rate):
                world.now += 1000 // rate
                total += world.pushed()
            totals.append(total)
        assert abs(totals[0] - totals[1]) <= 40


class TestCounterSteps:
    @pytest.mark.parametrize("index", range(len(COUNTER_STEPS)))
    def test_every_counter_steps_in_milliseconds(self, world: World, index: int) -> None:
        assert world.step(index) == 33
        world.now += 16
        assert world.step(index) == 49

    def test_counters_running_together_each_see_the_full_interval(self, world: World) -> None:
        """Rotation and zoom both stepping each update."""
        world.step(0), world.step(1)
        world.now += 16
        assert (world.step(0), world.step(1)) == (49, 49)


class TestCameraStep:
    def test_the_first_step_advances_one_stock_frame(self, world: World) -> None:
        assert world.step() == 33

    def test_later_steps_advance_by_elapsed_time(self, world: World) -> None:
        first = world.step()
        world.now += 16
        assert world.step() == first + 16
        world.now += 17
        assert world.step() == first + 33

    def test_two_steps_in_one_millisecond_advance_nothing(self, world: World) -> None:
        first = world.step()
        assert world.step() == first

    def test_a_hitch_is_clamped(self, world: World) -> None:
        first = world.step()
        world.now += 5_000
        assert world.step() == first + STEP_CLAMP

    def test_the_clock_wrapping_is_an_ordinary_step(self, world: World) -> None:
        world.now = 0xFFFFFFF0
        first = world.step()
        world.now = 0x10  # 32 ms later, across the wrap
        assert world.step() == first + 0x20

    def test_sixty_steps_a_second_and_thirty_take_the_same_time(self, image: bytes) -> None:
        """The defect, stated as what the fix buys: the rotation's progress after one second does
        not depend on how many times a second the view updates."""
        progress = []
        for rate in (30, 60):
            world = World(image)
            world.step()
            for _ in range(rate):
                world.now += 1000 // rate
                world.step()
            progress.append(world.m.read32(world.view + COUNTER_STEPS[0][1]))
        assert abs(progress[0] - progress[1]) <= 40
