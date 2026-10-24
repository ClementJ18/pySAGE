"""`special-power-object-cap`, executed.

The cave runs under Unicorn, over the real `game.dat` when this checkout has one and the stand-in
otherwise, with the four engine routines it calls answered in Python: the cap rule itself, then
each hook entered at its stock address, checked for where it leaves to and that the registers and
stack it leaves with are the ones the engine expects there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")
pytest.importorskip("pefile", reason="the emulator harness maps the image with pefile")

from unicorn.x86_const import UC_X86_REG_ESP  # noqa: E402

from sage_patch.addresses import (  # noqa: E402
    COMMAND_BUTTON_COMMAND,
    COMMAND_BUTTON_GET_THING_TEMPLATE,
    CONTROL_BAR_DO_COMMAND_REFUSE,
    CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_DISPATCH,
    CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_DISPATCH_RESUME,
    CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_GATE,
    CONTROL_BAR_SPECIAL_POWER_READY,
    CONTROL_BAR_SPECIAL_POWER_READY_RESUME,
    CONTROL_BAR_UNAVAILABLE,
    GUI_COMMAND_SPECIAL_POWER,
    OBJECT_GET_CONTROLLING_PLAYER,
    PLAYER_COUNT_OBJECTS_BY_THING_TEMPLATE,
    PLAYER_LIST_GET_LOCAL_PLAYER,
    THE_PLAYER_LIST,
    THING_TEMPLATE_MAX_SIMULTANEOUS_OF_TYPE,
)
from sage_patch.patches.special_power_object_cap import (  # noqa: E402
    SECTION_NAME,
    SpecialPowerObjectCapPatch,
    entry_points,
)
from sage_patch.utils import find_section  # noqa: E402

from .save_machine import REGISTERS, Machine  # noqa: E402
from .synthetic import special_power_object_cap_image  # noqa: E402

REAL_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


MOD_PLAYER = 0x0A0A0A0A


@pytest.fixture(scope="module")
def image() -> bytes:
    if REAL_GAME_DAT.exists():
        data = bytearray(REAL_GAME_DAT.read_bytes())
    else:
        data = special_power_object_cap_image()
    SpecialPowerObjectCapPatch().apply(data)
    return bytes(data)


@dataclass
class World:
    """Buttons, templates, objects and players, and the answers the engine routines give."""

    image: bytes
    #: `{button: template or 0}`, `{object: player}`, `{(player, template): count}`.
    objects_of: dict[int, int] = field(default_factory=dict)
    templates: dict[int, int] = field(default_factory=dict)
    owners: dict[int, int] = field(default_factory=dict)
    counts: dict[tuple[int, int], int] = field(default_factory=dict)
    local: int = 0
    asked: list[tuple[int, int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        m = self.m = Machine(self.image)
        self.at = entry_points(find_section(self.image, SECTION_NAME)[0])
        self.player_list = m.alloc(0x40, bytes(0x40))
        m.ensure(THE_PLAYER_LIST)
        m.write32(THE_PLAYER_LIST, self.player_list)
        m.stub(COMMAND_BUTTON_GET_THING_TEMPLATE, self._template_of)
        m.stub(OBJECT_GET_CONTROLLING_PLAYER, self._owner)
        m.stub(PLAYER_LIST_GET_LOCAL_PLAYER, self._local)
        m.stub(PLAYER_COUNT_OBJECTS_BY_THING_TEMPLATE, self._count)

    def _clobber(self) -> None:
        # What the real routines may leave behind: the cave must not rely on ecx or edx.
        self.m.uc.reg_write(self._reg("ecx"), 0xDEAD0001)
        self.m.uc.reg_write(self._reg("edx"), 0xDEAD0002)

    @staticmethod
    def _reg(name: str) -> int:
        return REGISTERS[name]

    def _template_of(self, m: Machine) -> None:
        template = self.templates.get(m.reg("ecx"), 0)
        self._clobber()
        m.ret(0, template)

    def _owner(self, m: Machine) -> None:
        player = self.owners.get(m.reg("ecx"), 0)
        self._clobber()
        m.ret(0, player)

    def _local(self, m: Machine) -> None:
        assert m.reg("ecx") == self.player_list
        self._clobber()
        m.ret(0, self.local)

    def _count(self, m: Machine) -> None:
        player = m.reg("ecx")
        number, things, ignore_dead, counts, ignore_under_construction = (
            m.arg(i) for i in range(5)
        )
        # The OCL's own arguments (`0x005F125A`): one template, dead ignored, built ones only.
        assert (number, ignore_dead, ignore_under_construction) == (1, 1, 0)
        template = m.read32(things)
        self.asked.append((player, template))
        m.write32(counts, self.counts.get((player, template), 0))
        self._clobber()
        m.ret(0x14)

    def template(self, cap: int) -> int:
        at = self.m.alloc(0x600, bytes(0x600))
        self.m.uc.mem_write(at + THING_TEMPLATE_MAX_SIMULTANEOUS_OF_TYPE, cap.to_bytes(2, "little"))
        return at

    def button(self, template: int = 0, command: int = GUI_COMMAND_SPECIAL_POWER) -> int:
        at = self.m.alloc(0x200, bytes(0x200))
        self.m.write32(at + COMMAND_BUTTON_COMMAND, command)
        self.templates[at] = template
        return at

    def capped(self, button: int, player: int) -> bool:
        return bool(self.m.call(self.at["capped"], button, player))


@pytest.fixture
def world(image: bytes) -> World:
    return World(image)


@pytest.mark.parametrize(
    ("cap", "count", "expected"),
    [(0, 5, False), (3, 0, False), (3, 2, False), (3, 3, True), (3, 7, True), (1, 1, True)],
)
def test_capped_follows_the_ocl_rule(world: World, cap: int, count: int, expected: bool) -> None:
    tmpl = world.template(cap)
    world.counts[(MOD_PLAYER, tmpl)] = count
    assert world.capped(world.button(tmpl), MOD_PLAYER) is expected
    # No cap, no count: the cave asks only when the template declares one.
    assert world.asked == ([(MOD_PLAYER, tmpl)] if cap else [])


def test_capped_ignores_what_is_not_a_capped_special_power(world: World) -> None:
    tmpl = world.template(1)
    world.counts[(MOD_PLAYER, tmpl)] = 1
    assert not world.capped(world.button(tmpl, command=0x03), MOD_PLAYER)  # UNIT_BUILD
    assert not world.capped(world.button(0), MOD_PLAYER)  # no Object
    assert not world.capped(world.button(tmpl), 0)  # no player
    assert not world.capped(0, MOD_PLAYER)
    assert world.asked == []


GENERAL = ("eax", "ebx", "esi", "edi", "ebp")


def _run_hook(world: World, va: int, stops: tuple[int, ...], **regs: int) -> tuple[int, dict]:
    m = world.m
    m.stop_at(*stops)
    ebp = m.frame()
    m.write32(ebp - 0x14, 0x0C0C0C0C)  # the evaluator's ControlBar slot
    esp = m.frame() - 0x40
    regs = {"ebp": ebp, **regs}
    m.run(va, esp, **regs)
    after = {name: m.reg(name) for name in (*GENERAL, "ecx")}
    after["esp"] = m.uc.reg_read(UC_X86_REG_ESP)
    return esp, after


@pytest.mark.parametrize(("count", "capped"), [(1, False), (2, True)])
def test_available_hook_greys_only_at_the_cap(world: World, count: int, capped: bool) -> None:
    obj = 0x0B0B0B0B
    world.owners[obj] = MOD_PLAYER
    tmpl = world.template(2)
    world.counts[(MOD_PLAYER, tmpl)] = count
    button = world.button(tmpl)
    regs = {"eax": 1, "ebx": obj, "esi": 0x5E5E5E5E, "edi": button}
    esp, after = _run_hook(
        world,
        CONTROL_BAR_SPECIAL_POWER_READY,
        (CONTROL_BAR_SPECIAL_POWER_READY_RESUME, CONTROL_BAR_UNAVAILABLE),
        **regs,
    )
    for name, value in regs.items():
        assert after[name] == value, name
    if capped:
        assert world.m.stopped_at == CONTROL_BAR_UNAVAILABLE
        assert after["esp"] == esp
    else:
        # The displaced `mov ecx, [ebp-0x14]; push ebx; push edi`, then back into the arm.
        assert world.m.stopped_at == CONTROL_BAR_SPECIAL_POWER_READY_RESUME
        assert after["ecx"] == 0x0C0C0C0C
        assert after["esp"] == esp - 8
        assert world.m.read32(esp - 8) == button
        assert world.m.read32(esp - 4) == obj
    assert world.asked == [(MOD_PLAYER, tmpl)]


@pytest.mark.parametrize("context", [True, False])
@pytest.mark.parametrize(("count", "capped"), [(0, False), (1, True)])
def test_click_hook_refuses_only_at_the_cap(
    world: World, context: bool, count: int, capped: bool
) -> None:
    obj = 0x0B0B0B0B if context else 0
    world.owners[obj] = MOD_PLAYER
    world.local = MOD_PLAYER  # the mixed context has no object: the local player is asked
    tmpl = world.template(1)
    world.counts[(MOD_PLAYER, tmpl)] = count
    button = world.button(tmpl)
    regs = {"eax": GUI_COMMAND_SPECIAL_POWER, "ebx": obj, "esi": button, "edi": 0x7E7E7E7E}
    esp, after = _run_hook(
        world,
        CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_DISPATCH,
        (
            CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_GATE,
            CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_DISPATCH_RESUME,
            CONTROL_BAR_DO_COMMAND_REFUSE,
        ),
        **regs,
    )
    expected = (
        CONTROL_BAR_DO_COMMAND_REFUSE if capped else CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_GATE
    )
    assert world.m.stopped_at == expected
    assert after["esp"] == esp
    for name, value in regs.items():
        assert after[name] == value, name


def test_click_hook_passes_other_commands_through_untouched(world: World) -> None:
    button = world.button(world.template(1), command=0x03)
    regs = {"eax": 0x03, "ebx": 0, "esi": button, "edi": 0}
    esp, after = _run_hook(
        world,
        CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_DISPATCH,
        (
            CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_GATE,
            CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_DISPATCH_RESUME,
        ),
        **regs,
    )
    assert world.m.stopped_at == CONTROL_BAR_DO_COMMAND_SPECIAL_POWER_DISPATCH_RESUME
    assert after["esp"] == esp
    assert world.asked == []
