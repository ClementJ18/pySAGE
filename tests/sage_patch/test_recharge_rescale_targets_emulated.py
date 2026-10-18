"""`recharge-rescale` on top of `spell-recharge-targets`, under an emulator.

With that patch applied, the cast-time player discount is `spell-recharge-targets`' gate, which
reads `startPowerRecharge`'s own frame. The sweep recomputes the discount by building that frame
in `targeted` and calling the same gate. If the two disagree by a single ULP, the recomputed
duration differs from the stored one and the sweep rescales a cooldown nothing changed, every
frame. So the factor `targeted` returns is compared **exactly** with the one the engine's own
recharge site computes, on the same machine and the same world.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.patches.recharge_rescale import build_asm
from sage_patch.patches.spell_recharge_targets import GATE1_VA, SpellRechargeTargetsPatch

from .synthetic import spell_recharge_targets_image

pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn.x86_const import UC_X86_REG_ESP  # noqa: E402

from .test_spell_recharge_targets import _STACK, _Machine  # noqa: E402

#: Where the rescale cave and the call into it are planted: clear of the stand-in's heap, stack,
#: stubs and return page.
_RESCALE_BASE = 0x60000000
_DRIVER = 0x61000000
_RESULT = 0x61000800
#: The four arguments, read by the driver rather than baked into it: unicorn keeps running its
#: translation of code it has already run, so a driver rewritten with new immediates at the same
#: address would push the previous call's arguments.
_ARGS = 0x61000810


@pytest.fixture
def machine() -> _Machine:
    data = spell_recharge_targets_image()
    SpellRechargeTargetsPatch().apply(data)
    return _Machine(data)


def _targeted(machine: _Machine, player: int, template: int, raw: int) -> float:
    """`targeted(gate, player, template, raw)` as the sweep calls it, read back as a Real."""
    a = build_asm(_RESCALE_BASE)
    machine.write(_RESCALE_BASE, a.finish())
    machine.write(_ARGS, struct.pack("<4I", machine.where["gate1"], player, template, raw))
    driver = (
        b"\xff\x35" + struct.pack("<I", _ARGS + 12)  # push dword [raw]
        + b"\xff\x35" + struct.pack("<I", _ARGS + 8)  # push dword [template]
        + b"\xff\x35" + struct.pack("<I", _ARGS + 4)  # push dword [player]
        + b"\xff\x35" + struct.pack("<I", _ARGS)  # push dword [gate]
        + b"\xe8" + struct.pack("<i", a.label_va("targeted") - (_DRIVER + 29))
        + b"\xd9\x1d" + struct.pack("<I", _RESULT)  # fstp dword [result]
        + b"\xf4"  # hlt
    )  # fmt: skip
    machine.write(_DRIVER, driver)
    machine.write(_RESULT, bytes(4))
    esp = _STACK + 0x700
    machine.uc.reg_write(UC_X86_REG_ESP, esp)
    machine.uc.emu_start(_DRIVER, _DRIVER + len(driver) - 1, count=100_000)
    assert machine.uc.reg_read(UC_X86_REG_ESP) == esp  # `ret 0x10` took its arguments
    return machine.f32(_RESULT)


def _engine(machine: _Machine, player: int, template: int) -> float:
    return machine.recharge_multiplier(GATE1_VA, player, template)


class TestTargetedMatchesTheRechargeSite:
    def test_nothing_targeted(self, machine: _Machine) -> None:
        machine.set_any(0)
        player = machine.player(modifier=-0.2)
        for template in (machine.template(flagged=True), machine.template()):
            assert _targeted(machine, player, template, template) == _engine(
                machine, player, template
            )

    def test_a_named_power_and_another(self, machine: _Machine) -> None:
        machine.set_any(1)
        player = machine.player()
        named, other = machine.template(), machine.template()
        md = machine.module_data([named], [-0.25, -0.5])
        machine.team([machine.obj(player, [machine.module(md)])])
        assert _targeted(machine, player, named, named) == pytest.approx(0.75)
        assert _targeted(machine, player, named, named) == _engine(machine, player, named)
        assert _targeted(machine, player, other, other) == _engine(machine, player, other) == 1.0

    def test_the_stock_discount_alongside(self, machine: _Machine) -> None:
        """A third of a percent off in each factor, so a product rounded at the wrong moment
        would show."""
        machine.set_any(1)
        player = machine.player(modifier=-0.1003)
        power = machine.template(flagged=True)
        md = machine.module_data([power], [-0.2507])
        machine.team([machine.obj(player, [machine.module(md)])])
        assert _targeted(machine, player, power, power) == _engine(machine, player, power)

    def test_the_flag_is_read_from_the_template_and_the_target_from_the_raw_one(
        self, machine: _Machine
    ) -> None:
        """As at the cast site: the discount flag comes from the final override, and the
        targeted lookup matches the raw template the ability's `ModuleData` names."""
        machine.set_any(1)
        player = machine.player(modifier=-0.2)
        override, raw = machine.template(flagged=True), machine.template()
        md = machine.module_data([raw], [-0.25])
        machine.team([machine.obj(player, [machine.module(md)])])
        assert _targeted(machine, player, override, raw) == pytest.approx(0.8 * 0.75)
        assert _targeted(machine, player, raw, override) == pytest.approx(1.0)
