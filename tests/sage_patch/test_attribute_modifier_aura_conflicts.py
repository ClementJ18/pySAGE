"""Fingerprint, scope and executed ABI coverage for aura conflict handling."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch import addresses as ad
from sage_patch.patches.attribute_modifier_aura_conflicts import (
    SECTION_NAME,
    AttributeModifierAuraConflictsPatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import allocate_section, file_offset, find_section

from .synthetic import _sparse_image


def image() -> bytearray:
    return _sparse_image(
        {
            **ad.ATTRIBUTE_MODIFIER_AURA_CONFLICT_ANCHORS,
            ad.OBJECT_DISPATCH_UPGRADES: ad.OBJECT_DISPATCH_UPGRADES_BYTES,
        }
    )


def test_registration_and_scope() -> None:
    assert AttributeModifierAuraConflictsPatch.name in PATCHES
    data = image()
    before = bytes(data)
    patch = AttributeModifierAuraConflictsPatch()
    assert patch.verify(data)
    patch.apply(data)
    assert patch.verify(data) == []
    for va, expected in ad.ATTRIBUTE_MODIFIER_AURA_CONFLICT_ANCHORS.items():
        off = file_offset(data, va)
        if va == ad.ATTRIBUTE_MODIFIER_AURA_UPGRADE_VTABLE:
            assert data[off : off + 4] == before[off : off + 4]
            assert data[off + 8 : off + len(expected)] == before[off + 8 : off + len(expected)]
        else:
            assert data[off : off + len(expected)] == expected
    start = ad.OBJECT_DISPATCH_UPGRADES
    gate = ad.OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE
    off = file_offset(data, start)
    prefix = gate - start
    end = prefix + len(ad.OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE_BYTES)
    assert data[off : off + prefix] == ad.OBJECT_DISPATCH_UPGRADES_BYTES[:prefix]
    assert (
        data[off + end : off + len(ad.OBJECT_DISPATCH_UPGRADES_BYTES)]
        == (ad.OBJECT_DISPATCH_UPGRADES_BYTES[end:])
    )
    with pytest.raises(ValueError, match="already carries"):
        patch.apply(data)


@pytest.mark.parametrize(
    "va", [*ad.ATTRIBUTE_MODIFIER_AURA_CONFLICT_ANCHORS, ad.OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE]
)
def test_wrong_build_is_rejected_before_mutation(va: int) -> None:
    data = image()
    off = file_offset(data, va)
    data[off + (4 if va == ad.ATTRIBUTE_MODIFIER_AURA_UPGRADE_VTABLE else 0)] ^= 1
    before = bytes(data)
    with pytest.raises(ValueError, match="unexpected build"):
        AttributeModifierAuraConflictsPatch().apply(data)
    assert data == before


@pytest.mark.parametrize("damage", ["pointer", "code", "global_evaluator", "dispatcher"])
def test_verify_detects_corruption(damage: str) -> None:
    data = image()
    patch = AttributeModifierAuraConflictsPatch()
    patch.apply(data)
    located = find_section(data, SECTION_NAME)
    assert located is not None
    off = {
        "pointer": file_offset(data, ad.ATTRIBUTE_MODIFIER_AURA_UPGRADE_VTABLE + 4),
        "code": located[1],
        "global_evaluator": file_offset(data, ad.UPGRADE_MODULE_EVALUATE),
        "dispatcher": file_offset(data, ad.OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE),
    }[damage]
    data[off] ^= 1
    assert patch.verify(data)


@pytest.mark.parametrize("active", [0, 1, 2])
@pytest.mark.parametrize("all_conflicts", [False, True])
@pytest.mark.parametrize("held,conflicts", [(0, 0), (1, 0), (0, 3), (1, 3), (3, 3), (7, 3)])
@pytest.mark.parametrize("word", [0, 35])
def test_executed_wrapper(
    active: int, all_conflicts: bool, held: int, conflicts: int, word: int
) -> None:
    x86 = pytest.importorskip("unicorn.x86_const")
    pytest.importorskip("pefile")
    # Optional emulator dependencies are absent on a minimal installation.
    from .save_machine import STACK, STACK_SIZE, Machine  # noqa: PLC0415

    data = image()
    AttributeModifierAuraConflictsPatch().apply(data)
    m = Machine(bytes(data))
    obj = m.alloc(0x40) + 0x20
    module_data = m.alloc(0x160)
    m.write32(obj - 0x1C, module_data)
    m.write32(obj, ad.ATTRIBUTE_MODIFIER_AURA_UPGRADE_VTABLE)
    m.uc.mem_write(obj + 4, bytes([active]))
    # TriggeredBy is deliberately empty: the active arm must not evaluate it.
    m.write32(module_data + 0xB8 + word * 4, conflicts)
    m.uc.mem_write(module_data + 0x155, bytes([all_conflicts]))
    mask = m.alloc(0x90)
    m.write32(mask + word * 4, held)
    initialized: list[int] = []
    delegated: list[int] = []

    def init(machine: Machine) -> None:
        initialized.append(machine.reg("ecx"))
        machine.uc.mem_write(machine.reg("ecx"), bytes(0x90))
        machine.ret(value=machine.reg("ecx"))

    def stock(machine: Machine) -> None:
        assert machine.reg("ecx") == obj
        delegated.append(machine.arg(0))
        machine.ret(4, 0xA5)

    m.stub(ad.UPGRADE_MASK_INIT, init)
    m.stub(ad.UPGRADE_MODULE_ON_ADDED, stock)
    entry = m.read32(ad.ATTRIBUTE_MODIFIER_AURA_UPGRADE_VTABLE + 4)
    saved = dict(esi=0x1234, edi=0x2345, ebx=0x3456, ebp=0x4567)
    result = m.call(entry, mask, ecx=obj, **saved)
    assert m.uc.reg_read(x86.UC_X86_REG_ESP) == STACK + STACK_SIZE - 0x1000
    assert {r: m.reg(r) for r in saved} == saved
    assert not m.faults
    if active == 0:
        assert delegated == [mask]
        assert initialized == []
        assert result == 0xA5
        expected = 0
    else:
        assert delegated == []
        assert len(initialized) == 2
        assert result == 0
        conflict = bool(conflicts) and (
            held & conflicts == conflicts if all_conflicts else bool(held & conflicts)
        )
        expected = 0 if conflict else active
    assert bytes(m.uc.mem_read(obj + 4, 1)) == bytes([expected])


@pytest.mark.full
def test_real_binary() -> None:
    path = Path(__file__).resolve().parents[2] / "game.dat"
    if not path.exists():
        pytest.skip("repository game.dat fixture is absent")
    data = bytearray(path.read_bytes())
    patch = AttributeModifierAuraConflictsPatch()
    patch.apply(data)
    assert patch.verify(data) == []


@pytest.mark.parametrize("dispatcher_fix", [False, True])
@pytest.mark.parametrize("module_kind", ["aura", "other", "no_upgrade_interface"])
@pytest.mark.parametrize("conflict_source", ["object", "player", "related_object"])
@pytest.mark.parametrize("all_conflicts", [False, True])
def test_native_dispatcher_lifecycle(
    dispatcher_fix: bool, module_kind: str, conflict_source: str, all_conflicts: bool
) -> None:
    """A grant activates; a later B grant reaches only the corrected aura dispatcher.

    Restoring the stock dispatcher reproduces the slot-only patch's blind spot.
    Execute its native mask merging and the native evaluator/bool comparisons;
    model ownership, memory copying, scheduling and the virtual interface query.
    """
    x86 = pytest.importorskip("unicorn.x86_const")
    pytest.importorskip("pefile")
    from .save_machine import STACK, STACK_SIZE, Machine  # noqa: PLC0415

    data = image()
    AttributeModifierAuraConflictsPatch().apply(data)
    if not dispatcher_fix:
        off = file_offset(data, ad.OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE)
        data[off : off + 10] = ad.OBJECT_DISPATCH_UPGRADES_ACTIVE_GATE_BYTES
    m = Machine(bytes(data))
    obj = m.alloc(0x500)
    player = m.alloc(0x200)
    related = m.alloc(0x500)
    relation = m.alloc(0x20)
    m.write32(relation + 0x14, 123)
    m.ensure(ad.THE_GAME_LOGIC)
    m.write32(ad.THE_GAME_LOGIC, m.alloc(0x50))
    module = m.alloc(0x40)
    iface = module + 0x20
    module_data = m.alloc(0x160)
    m.write32(iface - 0x1C, module_data)
    vtable = ad.ATTRIBUTE_MODIFIER_AURA_UPGRADE_VTABLE
    if module_kind == "other":
        # An unrelated type may share the stock callback but must retain its active skip.
        vtable = m.alloc(0x40, bytes(m.uc.mem_read(vtable, 0x40)))
        m.write32(vtable + 4, ad.UPGRADE_MODULE_ON_ADDED)
    m.write32(iface, vtable)
    m.write32(obj + 0x24C, m.alloc(8))
    m.write32(m.read32(obj + 0x24C), module)
    query_table = m.alloc(0x30)
    m.write32(module + 0xC, query_table)
    queried = 0 if module_kind == "no_upgrade_interface" else iface
    m.write32(query_table + 0x28, m.stub(None, lambda machine: machine.ret(value=queried)))
    m.stub(ad.OBJECT_GET_CONTROLLING_PLAYER, lambda machine: machine.ret(value=player))
    m.stub(0x00797BEF, lambda machine: machine.ret(value=relation))
    m.stub(0x00449681, lambda machine: machine.ret(4, related))

    # Copy constructor is a CRT memcpy wrapper; the union loop itself executes natively.
    def copy_mask(machine: Machine) -> None:
        machine.uc.mem_write(machine.reg("ecx"), bytes(machine.uc.mem_read(machine.arg(0), 0x90)))
        machine.ret(4)

    def init_mask(machine: Machine) -> None:
        machine.uc.mem_write(machine.reg("ecx"), bytes(0x90))
        machine.ret()

    m.stub(0x00444DB3, copy_mask)
    m.stub(ad.UPGRADE_MASK_INIT, init_mask)
    m.ensure(ad.OBJECT_APPLY_UPGRADE_LIST)
    # Use the exact stock union loop (edx counts words).
    m.uc.mem_write(
        ad.OBJECT_APPLY_UPGRADE_LIST,
        bytes.fromhex("8b4424046a245a2bc1568b3408093183c1044a75f55ec20400"),
    )
    notifications: list[int] = []

    def post_callback(machine: Machine) -> None:
        notifications.append(machine.reg("ecx"))
        machine.ret()

    m.stub(0x0063F3BF, post_callback)
    activations: list[int] = []

    def activate(machine: Machine) -> None:
        activations.append(machine.reg("ecx"))
        machine.uc.mem_write(machine.reg("ecx") + 4, b"\x01")
        machine.ret()

    m.stub(0x00855388, activate)
    # A=TriggeredBy, B/C=ConflictsWith. RequiresAllTriggers is false as in the Beorn INI.
    m.write32(module_data + 0x28, 1)
    m.write32(module_data + 0xB8, 6 if all_conflicts else 2)
    m.uc.mem_write(module_data + 0x155, bytes([all_conflicts]))
    saved = dict(esi=0x1234, edi=0x2345, ebx=0x3456, ebp=0x4567)

    def dispatch() -> int:
        m.call(ad.OBJECT_DISPATCH_UPGRADES, ecx=obj, **saved)
        assert m.uc.reg_read(x86.UC_X86_REG_ESP) == STACK + STACK_SIZE - 0x1000
        assert {r: m.reg(r) for r in saved} == saved
        assert not m.faults
        return bytes(m.uc.mem_read(iface + 4, 1))[0]

    m.write32(obj + 0x28C, 1)
    expected_active = int(module_kind != "no_upgrade_interface")
    assert dispatch() == expected_active
    conflict_mask = {
        "object": obj + 0x28C,
        "player": player + 0x14C,
        "related_object": related + 0x28C,
    }[conflict_source]
    m.write32(conflict_mask, m.read32(conflict_mask) | 2)
    if all_conflicts:
        assert dispatch() == expected_active  # B alone is insufficient
        m.write32(conflict_mask, m.read32(conflict_mask) | 4)
    disabled = dispatcher_fix and module_kind == "aura"
    assert dispatch() == (0 if disabled else expected_active)
    assert activations == ([iface] if expected_active else [])
    assert len(notifications) == ((3 if all_conflicts else 2) if expected_active else 0)


def test_legacy_slot_only_patch_is_not_reported_as_fixed() -> None:
    data = image()
    # The shipped slot-only cave is 148 bytes; it is the unchanged conflict wrapper prefix.
    base = allocate_section(data, SECTION_NAME, lambda va: build_code(va)[:148], 0x60000020)
    struct.pack_into(
        "<I", data, file_offset(data, ad.ATTRIBUTE_MODIFIER_AURA_UPGRADE_VTABLE + 4), base
    )
    problems = AttributeModifierAuraConflictsPatch().verify(data)
    assert any("legacy slot-only" in problem for problem in problems)
    assert any("0x006936fe" in problem for problem in problems)
