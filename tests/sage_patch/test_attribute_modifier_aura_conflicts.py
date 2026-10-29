"""Fingerprint, generic-interface scope and executed conflict-removal coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_patch import addresses as ad
from sage_patch.patches.combat.attribute_modifier_aura_conflicts import (
    SECTION_NAME,
    AttributeModifierAuraConflictsPatch,
    _assemble,
)
from sage_patch.patches.upgrades.upgrade_module_removal import UpgradeModuleRemovalPatch
from sage_patch.registry import PATCHES
from sage_patch.utils import file_offset, find_section

from .synthetic import _sparse_image


def image() -> bytearray:
    return _sparse_image(
        {
            **ad.UPGRADE_MODULE_CONFLICT_ANCHORS,
            ad.OBJECT_DISPATCH_UPGRADES: ad.OBJECT_DISPATCH_UPGRADES_BYTES,
        }
    )


def composition_image() -> bytearray:
    return _sparse_image(
        {
            **ad.UPGRADE_MODULE_REMOVAL_ANCHORS,
            **ad.UPGRADE_MODULE_CONFLICT_ANCHORS,
            ad.OBJECT_DISPATCH_UPGRADES: ad.OBJECT_DISPATCH_UPGRADES_BYTES,
        }
    )


def test_registration_apply_verify_and_scope() -> None:
    assert PATCHES[AttributeModifierAuraConflictsPatch.name] is AttributeModifierAuraConflictsPatch
    data = image()
    before = bytes(data)
    patch = AttributeModifierAuraConflictsPatch()
    patch.apply(data)
    assert patch.verify(data) == []
    located = find_section(data, SECTION_NAME)
    assert located is not None

    changed = {
        ad.OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE,
        ad.OBJECT_DISPATCH_UPGRADES_CALLBACK,
    }
    for va, size in (
        (
            ad.OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE,
            len(ad.OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE_BYTES),
        ),
        (ad.OBJECT_DISPATCH_UPGRADES_CALLBACK, len(ad.OBJECT_DISPATCH_UPGRADES_CALLBACK_BYTES)),
    ):
        off = file_offset(data, va)
        assert bytes(data[off : off + size]) != before[off : off + size]
    for va, expected in ad.UPGRADE_MODULE_CONFLICT_ANCHORS.items():
        assert va not in changed
        off = file_offset(data, va)
        assert bytes(data[off : off + len(expected)]) == expected

    with pytest.raises(ValueError, match="already carries"):
        patch.apply(data)


@pytest.mark.parametrize("va", [*ad.UPGRADE_MODULE_CONFLICT_ANCHORS, ad.OBJECT_DISPATCH_UPGRADES])
def test_wrong_build_is_rejected_before_mutation(va: int) -> None:
    data = image()
    off = file_offset(data, va)
    data[off] ^= 1
    before = bytes(data)
    with pytest.raises(ValueError, match="unexpected build"):
        AttributeModifierAuraConflictsPatch().apply(data)
    assert data == before


@pytest.mark.parametrize("damage", ["code", "gate", "callback", "anchor"])
def test_verify_detects_corruption(damage: str) -> None:
    data = image()
    patch = AttributeModifierAuraConflictsPatch()
    patch.apply(data)
    located = find_section(data, SECTION_NAME)
    assert located is not None
    off = {
        "code": located[1],
        "gate": file_offset(data, ad.OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE),
        "callback": file_offset(data, ad.OBJECT_DISPATCH_UPGRADES_CALLBACK),
        "anchor": file_offset(data, ad.UPGRADE_MODULE_ON_ADDED),
    }[damage]
    data[off] ^= 1
    assert patch.verify(data)


@pytest.mark.parametrize("all_conflicts", [False, True])
@pytest.mark.parametrize(
    "held,conflicts,removed",
    [(0, 0, False), (7, 0, False), (0, 3, False), (1, 3, True), (3, 3, True)],
)
@pytest.mark.parametrize("word", [0, 35])
def test_active_helper_uses_virtual_triggeredby_removal(
    all_conflicts: bool, held: int, conflicts: int, removed: bool, word: int
) -> None:
    pytest.importorskip("unicorn.x86_const")
    pytest.importorskip("pefile")
    from .save_machine import Machine  # noqa: PLC0415

    data = image()
    patch = AttributeModifierAuraConflictsPatch()
    patch.apply(data)
    located = find_section(data, SECTION_NAME)
    assert located is not None
    base = located[0]  # the active helper is the cave's first routine
    m = Machine(bytes(data))
    iface = m.alloc(0x20)
    vtable = m.alloc(0x40)
    m.write32(iface, vtable)
    m.uc.mem_write(iface + 4, b"\x01")
    mask = m.alloc(0x90, bytes(0x90))
    m.write32(mask + word * 4, held)
    trigger = 1 << 7
    removal_calls: list[tuple[int, int]] = []
    effect_calls: list[int] = []

    def init(machine: Machine) -> None:
        machine.uc.mem_write(machine.reg("ecx"), bytes(0x90))
        machine.ret(value=machine.reg("ecx"))

    def build(machine: Machine) -> None:
        machine.write32(machine.arg(0) + word * 4, trigger)
        machine.write32(machine.arg(1) + word * 4, conflicts)
        machine.ret(8)

    def requires_all(machine: Machine) -> None:
        machine.ret(value=int(all_conflicts))

    def on_removed(machine: Machine) -> None:
        removal_calls.append((machine.reg("ecx"), machine.read32(machine.arg(0) + word * 4)))
        machine.uc.mem_write(machine.reg("ecx") + 4, b"\x00")
        machine.ret(4, 1)

    def remove_effects(machine: Machine) -> None:
        target = machine.arg(0)
        effect_calls.append(target)
        assert bytes(machine.uc.mem_read(target + 4, 1)) == b"\x01"
        machine.ret()

    m.stub(ad.UPGRADE_MASK_INIT, init)
    m.stub(ad.UPGRADE_MODULE_REMOVE_EFFECTS, remove_effects)
    m.write32(vtable + 0x0C, m.stub(None, on_removed))
    m.write32(vtable + 0x2C, m.stub(None, build))
    m.write32(vtable + 0x38, m.stub(None, requires_all))

    expected = removed and (not all_conflicts or held & conflicts == conflicts)
    m.call(base, mask, ecx=iface, ebx=0x1234, esi=0x2345, edi=0x3456)
    assert not m.faults
    assert removal_calls == ([(iface, trigger)] if expected else [])
    assert effect_calls == ([iface] if expected else [])
    assert bytes(m.uc.mem_read(iface + 4, 1)) == (b"\x00" if expected else b"\x01")


@pytest.mark.parametrize(
    "active,specialised,expected",
    [(False, False, "build"), (True, False, "build"), (True, True, "post")],
)
def test_dispatch_gate_only_admits_the_standard_contract(
    active: bool, specialised: bool, expected: str
) -> None:
    pytest.importorskip("unicorn.x86_const")
    pytest.importorskip("pefile")
    from .save_machine import Machine  # noqa: PLC0415

    data = image()
    AttributeModifierAuraConflictsPatch().apply(data)
    base = find_section(data, SECTION_NAME)
    assert base is not None
    gate = _assemble(base[0]).label_va("gate")
    m = Machine(bytes(data))
    iface = m.alloc(0x20)
    vtable = m.alloc(0x40)
    m.write32(iface, vtable)
    m.uc.mem_write(iface + 4, bytes([active]))
    m.write32(vtable + 0x00, ad.UPGRADE_INTERFACE_GET_FLAG)
    m.write32(vtable + 0x04, 0x11111111 if specialised else ad.UPGRADE_MODULE_ON_ADDED)
    m.write32(vtable + 0x0C, ad.UPGRADE_MODULE_REMOVAL)
    m.write32(vtable + 0x24, ad.UPGRADE_MODULE_SET_FLAG)
    m.write32(vtable + 0x2C, 0x11111111)
    m.write32(vtable + 0x38, 0x11111111)
    reached: list[str] = []
    m.stub(
        ad.OBJECT_DISPATCH_UPGRADES_BUILD_MASK,
        lambda machine: (reached.append("build"), machine.ret()),
    )
    m.stub(
        ad.OBJECT_DISPATCH_UPGRADES_POST_CALLBACK,
        lambda machine: (reached.append("post"), machine.ret()),
    )
    m.call(gate, ebx=iface)
    assert not m.faults
    assert reached == [expected]


def test_callback_preserves_the_stock_inactive_virtual_call() -> None:
    pytest.importorskip("unicorn.x86_const")
    pytest.importorskip("pefile")
    from .save_machine import Machine  # noqa: PLC0415

    data = image()
    AttributeModifierAuraConflictsPatch().apply(data)
    section = find_section(data, SECTION_NAME)
    assert section is not None
    callback = _assemble(section[0]).label_va("callback")
    m = Machine(bytes(data))
    iface = m.alloc(0x20, bytes(0x20))
    vtable = m.alloc(0x40, bytes(0x40))
    frame = m.frame()
    held = frame - 0x98
    m.write32(iface, vtable)
    delegated: list[tuple[int, int]] = []

    def on_added(machine: Machine) -> None:
        delegated.append((machine.reg("ecx"), machine.arg(0)))
        machine.ret(4, 1)

    m.write32(vtable + 4, m.stub(None, on_added))
    m.stub(ad.OBJECT_DISPATCH_UPGRADES_POST_CALLBACK, lambda machine: machine.ret())
    m.call(callback, ebx=iface, ebp=frame)
    assert not m.faults
    assert delegated == [(iface, held)]


@pytest.mark.parametrize("order", ["removal-first", "conflicts-first"])
def test_composes_with_upgrade_module_removal_in_both_orders(order: str) -> None:
    data = composition_image()
    removal = UpgradeModuleRemovalPatch()
    conflicts = AttributeModifierAuraConflictsPatch()
    patches = [removal, conflicts] if order == "removal-first" else [conflicts, removal]
    for patch in patches:
        patch.apply(data)
    assert removal.verify(data) == []
    assert conflicts.verify(data) == []


@pytest.mark.full
def test_real_binary() -> None:
    path = Path(__file__).resolve().parents[2] / "game.dat"
    if not path.exists():
        pytest.skip("repository game.dat fixture is absent")
    data = bytearray(path.read_bytes())
    patch = AttributeModifierAuraConflictsPatch()
    patch.apply(data)
    assert patch.verify(data) == []
