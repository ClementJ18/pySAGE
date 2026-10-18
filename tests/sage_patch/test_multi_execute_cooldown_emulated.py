"""`multi-execute-cooldown`, executed.

The sibling file reads the cave back as text. This one runs its two routines under Unicorn, over
the real `game.dat` when this checkout has one and the synthetic stand-in otherwise (the cave
bytes are the same either way). The control bar's availability evaluator and
`CommandButton::isReady` are answered in Python per object, and `TheInGameUI`'s selection is a
real `std::list` laid out in memory, so each case is a selection with some members ready and some
recharging.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")
pytest.importorskip("pefile", reason="the emulator harness maps the image with pefile")

from sage_patch.addresses import (  # noqa: E402
    COMMAND_BUTTON_COMMAND,
    COMMAND_BUTTON_IS_READY,
    COMMAND_BUTTON_OPTION_MULTI_EXECUTE,
    COMMAND_BUTTON_OPTIONS,
    CONTROL_BAR_GET_COMMAND_AVAILABILITY,
    DRAWABLE_OBJECT,
    GAME_WINDOW_GET_COMMAND_BUTTON,
    GUI_COMMAND_SPECIAL_POWER,
    IN_GAME_UI_GET_ALL_SELECTED_DRAWABLES_SLOT,
    SELECTION_LIST_DRAWABLE,
    THE_IN_GAME_UI,
)
from sage_patch.patches.multi_execute_cooldown import (  # noqa: E402
    SECTION_NAME,
    MultiExecuteCooldownPatch,
    layout,
)
from sage_patch.utils import find_section  # noqa: E402

from .save_machine import Machine  # noqa: E402
from .synthetic import multi_execute_cooldown_image  # noqa: E402

REAL_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

READY, AVAILABLE, RECHARGING, DISABLED = 1, 2, 5, 3
CONTROL_BAR = 0x0C0C0C0C
WINDOW = 0x0D0D0D0D
FLAG = 0x0E


@pytest.fixture(scope="module")
def image() -> bytes:
    if REAL_GAME_DAT.exists():
        source = REAL_GAME_DAT.read_bytes()
    else:
        source = bytes(multi_execute_cooldown_image())
    data = bytearray(source)
    MultiExecuteCooldownPatch().apply(data)
    return bytes(data)


@dataclass
class Bar:
    """A selection and the per-object answers the two stock routines give."""

    m: Machine
    #: `{object: (availability, progress)}` for the evaluator, `{object: bool}` for `isReady`.
    availability: dict[int, tuple[int, float]] = field(default_factory=dict)
    ready: dict[int, bool] = field(default_factory=dict)
    asked: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        m = self.m
        self.at = layout(find_section(m.image, SECTION_NAME)[0])
        self.list = m.alloc(16, bytes(16))
        self.sentinel = m.alloc(16, bytes(16))
        m.write32(self.list, self.sentinel)
        m.write32(self.sentinel, self.sentinel)  # empty: next is itself
        vtable = m.alloc(0x200, bytes(0x200))
        ui = m.alloc(16, bytes(16))
        m.write32(ui, vtable)
        m.write32(
            vtable + IN_GAME_UI_GET_ALL_SELECTED_DRAWABLES_SLOT,
            m.stub(None, lambda mm: mm.ret(0, self.list)),
        )
        m.ensure(THE_IN_GAME_UI)
        m.write32(THE_IN_GAME_UI, ui)
        m.stub(CONTROL_BAR_GET_COMMAND_AVAILABILITY, self._availability)
        m.stub(COMMAND_BUTTON_IS_READY, self._is_ready)

    def button(self, command: int = GUI_COMMAND_SPECIAL_POWER, multi: bool = True) -> int:
        button = self.m.alloc(0x200, bytes(0x200))
        self.m.write32(button + COMMAND_BUTTON_COMMAND, command)
        self.m.write32(button + COMMAND_BUTTON_OPTIONS, COMMAND_BUTTON_OPTION_MULTI_EXECUTE * multi)
        return button

    def select(self, *answers: tuple[int, float, bool]) -> list[int]:
        """Append one selected unit per `(availability, progress, ready)`; return the objects."""
        objects = []
        last = self.sentinel
        while self.m.read32(last) != self.sentinel:
            last = self.m.read32(last)
        for availability, progress, ready in answers:
            obj = self.m.alloc(0x200, bytes(0x200))
            drawable = self.m.alloc(0x200, bytes(0x200))
            self.m.write32(drawable + DRAWABLE_OBJECT, obj)
            node = self.m.alloc(16, bytes(16))
            self.m.write32(node + SELECTION_LIST_DRAWABLE, drawable)
            self.m.write32(node, self.sentinel)
            self.m.write32(last, node)
            last = node
            self.availability[obj] = (availability, progress)
            self.ready[obj] = ready
            objects.append(obj)
        return objects

    def _availability(self, m: Machine) -> None:
        assert m.reg("ecx") == CONTROL_BAR
        button, window, obj, progress = (m.arg(i) for i in range(4))
        assert window == WINDOW
        self.asked.append(obj)
        answer, fraction = self.availability.get(obj, (DISABLED, 1.0))
        m.uc.mem_write(progress, struct.pack("<f", fraction))
        m.ret(0x14, answer)

    def _is_ready(self, m: Machine) -> None:
        self.asked.append(m.arg(0))
        m.ret(4, int(self.ready.get(m.arg(0), False)))

    def availability_of(self, button: int, obj: int) -> tuple[int, float]:
        progress = self.m.alloc(4, struct.pack("<f", 1.0))
        answer = self.m.call(
            self.at["availability_any"], button, WINDOW, obj, progress, FLAG, ecx=CONTROL_BAR
        )
        return answer, struct.unpack("<f", self.m.uc.mem_read(progress, 4))[0]

    def is_ready(self, button: int, obj: int) -> bool:
        return bool(self.m.call(self.at["ready_any"], obj, ecx=button) & 0xFF)


@pytest.fixture
def bar(image: bytes) -> Bar:
    return Bar(Machine(image))


class TestThePaint:
    def test_a_usable_answer_is_passed_through_without_asking_anyone_else(self, bar: Bar):
        first, _second = bar.select((READY, 1.0, True), (RECHARGING, 0.125, False))
        assert bar.availability_of(bar.button(), first) == (READY, 1.0)
        assert bar.asked == [first]

    def test_a_recharging_unit_shows_ready_when_another_is(self, bar: Bar):
        used, fresh = bar.select((RECHARGING, 0.375, False), (AVAILABLE, 1.0, True))
        assert bar.availability_of(bar.button(), used) == (AVAILABLE, 1.0)
        assert bar.asked == [used, fresh]

    def test_with_everyone_recharging_the_clock_is_the_one_closest_to_ready(self, bar: Bar):
        a, b, c = bar.select(
            (RECHARGING, 0.25, False), (RECHARGING, 0.75, False), (RECHARGING, 0.5, False)
        )
        answer, progress = bar.availability_of(bar.button(), a)
        assert (answer, progress) == (RECHARGING, 0.75)
        assert bar.asked == [a, b, c]

    def test_a_disabled_member_does_not_count_as_ready(self, bar: Bar):
        used, _other = bar.select((RECHARGING, 0.5, False), (DISABLED, 1.0, False))
        assert bar.availability_of(bar.button(), used) == (RECHARGING, 0.5)

    @pytest.mark.parametrize(
        ("command", "multi"), [(GUI_COMMAND_SPECIAL_POWER, False), (0x17, True), (0x02, True)]
    )
    def test_only_multi_execute_special_powers_look_at_the_group(
        self, bar: Bar, command: int, multi: bool
    ):
        used, _fresh = bar.select((RECHARGING, 0.375, False), (READY, 1.0, True))
        assert bar.availability_of(bar.button(command, multi), used) == (RECHARGING, 0.375)
        assert bar.asked == [used]

    def test_a_lone_unit_keeps_its_own_clock(self, bar: Bar):
        (used,) = bar.select((RECHARGING, 0.625, False))
        assert bar.availability_of(bar.button(), used) == (RECHARGING, 0.625)


class TestTheClick:
    def test_a_ready_unit_passes_without_asking_anyone_else(self, bar: Bar):
        fresh, _used = bar.select((READY, 1.0, True), (RECHARGING, 0.125, False))
        assert bar.is_ready(bar.button(), fresh)
        assert bar.asked == [fresh]

    def test_a_recharging_unit_passes_when_another_is_ready(self, bar: Bar):
        used, _fresh = bar.select((RECHARGING, 0.375, False), (READY, 1.0, True))
        assert bar.is_ready(bar.button(), used)

    def test_nobody_ready_still_refuses(self, bar: Bar):
        used, other = bar.select((RECHARGING, 0.375, False), (RECHARGING, 0.875, False))
        assert not bar.is_ready(bar.button(), used)
        assert bar.asked == [used, used, other]  # itself through the stock call, then the walk

    def test_a_button_without_multi_execute_keeps_the_stock_answer(self, bar: Bar):
        used, _fresh = bar.select((RECHARGING, 0.375, False), (READY, 1.0, True))
        assert not bar.is_ready(bar.button(multi=False), used)
        assert bar.asked == [used]


#: The window's status word and its data-record pointer, as `clearStatus` and `getData` read them.
WINDOW_STATUS = 0x08
WINDOW_DATA = 0x2C
STATUS_RECHARGING = 0x400000
STOCK_MASK = 0x1000000


class TestTheUsablePaint:
    """The mixed-selection final pass, for a slot some member can use. `clearStatus` and the
    window-data getter are the image's own; the window's button is answered in Python."""

    def paint(
        self,
        image: bytes,
        command: int = GUI_COMMAND_SPECIAL_POWER,
        multi: bool = True,
        kind: int = 2,
        has_button: bool = True,
    ) -> tuple[int, int]:
        m = Machine(image)
        at = layout(find_section(image, SECTION_NAME)[0])
        target = Bar(m).button(command, multi) if has_button else 0
        record = m.alloc(0x38, bytes([kind]) + bytes(0x37))
        window = m.alloc(0x40, bytes(0x40))
        m.write32(window + WINDOW_STATUS, STATUS_RECHARGING | STOCK_MASK | 0x80000000 | 0x8)
        m.write32(window + WINDOW_DATA, record)
        m.stub(GAME_WINDOW_GET_COMMAND_BUTTON, lambda mm: mm.ret(0, target))
        m.call(at["usable_paint"], STOCK_MASK, ecx=window)
        return m.read32(window + WINDOW_STATUS), m.uc.mem_read(record, 1)[0]

    def test_a_multi_execute_power_drops_the_clock_and_the_recharge_bit(self, image: bytes):
        status, kind = self.paint(image)
        assert status == 0x80000000 | 0x8
        assert kind == 0

    def test_any_other_command_drops_them_too(self, image: bytes):
        status, kind = self.paint(image, command=0x08, multi=False)
        assert (status & STATUS_RECHARGING, kind) == (0, 0)

    @pytest.mark.parametrize(
        ("command", "multi"), [(GUI_COMMAND_SPECIAL_POWER, False), (0x17, True)]
    )
    def test_a_power_whose_click_needs_everyone_keeps_its_clock(
        self, image: bytes, command: int, multi: bool
    ):
        status, kind = self.paint(image, command, multi)
        assert status == STATUS_RECHARGING | 0x80000000 | 0x8  # only the stock mask went
        assert kind == 2

    def test_another_overlay_is_not_touched(self, image: bytes):
        _status, kind = self.paint(image, kind=1)
        assert kind == 1

    def test_no_button_is_the_stock_clear_alone(self, image: bytes):
        status, kind = self.paint(image, has_button=False)
        assert status == STATUS_RECHARGING | 0x80000000 | 0x8
        assert kind == 2
