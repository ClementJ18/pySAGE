"""Integrity, composition and native x87 tests for the two health sources."""

from __future__ import annotations

import itertools
import os
import struct
from pathlib import Path
from typing import Literal

import pytest

from sage_patch.patches.combo_horde_recruitment import (
    ANCHORS as PAYLOAD_ANCHORS,
)
from sage_patch.patches.combo_horde_recruitment import (
    HORDE_CONTAIN_PRODUCED_GATE,
    HORDE_CONTAIN_PRODUCED_GATE_BYTES,
    ComboHordeRecruitmentPatch,
)
from sage_patch.patches.experimental import hero_horde_death as death
from sage_patch.patches.horde_herobar import (
    ANCHORS,
    FIND_OBJECT_BY_ID,
    HOOK,
    ORIGINAL,
    RESUME,
    SECTION_NAME,
    THE_GAME_LOGIC,
    HordeHerobarPatch,
    build_code,
)
from sage_patch.utils import file_offset, find_section

from .synthetic import _sparse_image


def test_install_repeat_and_tamper():
    data = _sparse_image({**ANCHORS, HOOK: ORIGINAL})
    patch = HordeHerobarPatch()
    patch.apply(data)
    assert not patch.verify(data)
    assert patch.detect(data) is not None
    once = bytes(data)
    patch.apply(data)
    assert data == once
    _, off, _ = find_section(data, SECTION_NAME)
    data[off + 30] ^= 1
    before = bytes(data)
    assert patch.verify(data)
    with pytest.raises(ValueError):
        patch.apply(data)
    assert data == before


@pytest.mark.parametrize("va", [HOOK, *ANCHORS])
def test_signature_failure_is_transactional(va):
    data = _sparse_image({**ANCHORS, HOOK: ORIGINAL})
    data[file_offset(data, va)] ^= 1
    before = bytes(data)
    with pytest.raises(ValueError):
        HordeHerobarPatch().apply(data)
    assert data == before


@pytest.mark.parametrize("order", list(itertools.permutations(range(3))))
def test_death_payload_and_ui_compose(order):
    data = _sparse_image(
        {
            **ANCHORS,
            **PAYLOAD_ANCHORS,
            **death.ANCHORS,
            HOOK: ORIGINAL,
            death.HOOK: death.ORIGINAL,
            HORDE_CONTAIN_PRODUCED_GATE: HORDE_CONTAIN_PRODUCED_GATE_BYTES,
        }
    )
    patches = [death.HeroHordeDeathPatch(), ComboHordeRecruitmentPatch(), HordeHerobarPatch()]
    for i in order:
        patches[i].apply(data)
    for patch in patches:
        assert not patch.verify(data)


@pytest.mark.full
def test_real_backup():
    configured = os.environ.get("PYSAGE_ROTWK_GAME_DAT")
    if not configured:
        pytest.skip("set PYSAGE_ROTWK_GAME_DAT to test a supplied original executable")
    path = Path(configured)
    original = path.read_bytes()
    data = bytearray(original)
    patch = HordeHerobarPatch()
    patch.apply(data)
    assert not patch.verify(data)
    assert path.read_bytes() == original


def execute(
    members: list[tuple[float, float] | None],
    *,
    banner_destroys: bool = False,
    banner: tuple[float, float] = (25.0, 100.0),
    kindof: int = 0x2000,
    slots: int = 5,
    fault: str = "",
    native: bool = False,
    path: Literal["members", "banner", "original"] = "members",
) -> float:
    unicorn = pytest.importorskip("unicorn")
    x = pytest.importorskip("unicorn.x86_const")
    u = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
    u.mem_map(0x400000, 0xB00000)
    u.mem_map(0x10000000, 0x40000)
    u.mem_map(0x20000000, 0x20000)
    cave, iface_getter, boot = 0xE00000, 0xE01100, 0xE01200
    obj, template, contain = 0x10000000, 0x10001000, 0x10002020
    data, sentinel, vtable, body_vtable = 0x10003000, 0x10004000, 0x10005000, 0x10006000
    body, frame, stack = 0x10007000, 0x20018000, 0x20010000
    result, old, old_value = 0x10008000, 0x10008004, 0x10008008
    banner_obj, banner_body = 0x1000A000, 0x1000B000
    current_getter, max_getter, ratio_getter = 0x005F2D41, 0x006AA274, 0x008C1D75

    def word(va: int, value: int) -> None:
        u.mem_write(va, struct.pack("<I", value & 0xFFFFFFFF))

    def floating(va: int, value: float) -> None:
        u.mem_write(va, struct.pack("<f", value))

    def make_body(va: int, values: tuple[float, float]) -> None:
        word(va, body_vtable)
        floating(va + 8, values[0])
        floating(va + 0x10, values[1])

    word(frame - 0x20, 0 if fault == "null_object" else obj)
    word(obj + 4, template)
    word(template + 0x114, kindof)
    word(obj + 0x258, 0 if fault == "null_contain" else contain)
    word(contain, vtable)
    word(vtable + 0x7C, iface_getter)
    word(contain - 0x1C, 0 if fault == "null_data" else data)
    word(data + 0x98, slots)
    word(data + 0x224, int(banner_destroys))
    word(contain + 0x34, 0 if fault == "null_sentinel" else sentinel)
    word(contain + 0xFC + 0x150, 0 if fault == "banner_no_id" else 42)
    word(THE_GAME_LOGIC, 0 if fault == "no_logic" else 0x10009000)
    word(banner_obj + 0x25C, 0 if fault == "banner_no_body" else banner_body)
    word(body_vtable + 0x10, current_getter)
    word(body_vtable + 0x1C, max_getter)
    word(body_vtable + 0x14, ratio_getter)
    make_body(body, (73.0, 100.0))
    make_body(banner_body, banner)
    floating(old_value, 42.0)
    found = 0 if fault == "banner_missing" else obj if fault == "banner_self" else banner_obj
    u.mem_write(
        FIND_OBJECT_BY_ID, b"\xb8" + struct.pack("<I", found) + bytes.fromhex("31c931d2c20400")
    )
    nodes = [0x10010000 + i * 0x100 for i in range(len(members))]
    word(sentinel, nodes[0] if nodes else sentinel)
    for i, (node, values) in enumerate(zip(nodes, members, strict=True)):
        member, member_body = 0x10020000 + i * 0x300, node + 0x40
        following = nodes[i + 1] if i + 1 < len(nodes) else sentinel
        word(node, node if fault == "cycle" else 0 if fault == "null_node" else following)
        word(node + 8, member if values is not None else 0)
        word(member + 0x25C, 0 if fault == "missing_body" else member_body)
        make_body(member_body, values or (0.0, 0.0))

    if native:
        for va in (current_getter, max_getter, ratio_getter):
            u.mem_write(va, ANCHORS[va])
    else:
        # The ABI permits volatile registers/flags to change during every virtual call.
        clobber = bytes.fromhex("b8adde000031c931d2c3")
        u.mem_write(current_getter, bytes.fromhex("d94108") + clobber)
        u.mem_write(max_getter, bytes.fromhex("d94110") + clobber)
        u.mem_write(ratio_getter, bytes.fromhex("d94108d87110") + clobber)
    returned_iface = 0 if fault == "no_horde_iface" else contain + 0xFC
    u.mem_write(
        iface_getter, b"\xb8" + struct.pack("<I", returned_iface) + bytes.fromhex("31c931d2c3")
    )
    u.mem_write(cave, build_code(cave))
    u.mem_write(boot, b"\xd9\x05" + struct.pack("<I", old_value))
    finish = b"\xd9\x1d" + struct.pack("<I", result) + b"\xd9\x1d" + struct.pack("<I", old)
    u.mem_write(RESUME, finish)
    regs = [
        x.UC_X86_REG_EAX,
        x.UC_X86_REG_EBX,
        x.UC_X86_REG_ECX,
        x.UC_X86_REG_EDX,
        x.UC_X86_REG_ESI,
        x.UC_X86_REG_EDI,
        x.UC_X86_REG_EBP,
    ]
    values = [0x1111, 0x2222, body, 0x4444, 0x5555, 0x6666, frame]
    for r, v in zip(regs, values, strict=True):
        u.reg_write(r, v)
    u.reg_write(x.UC_X86_REG_ESP, stack)
    u.reg_write(x.UC_X86_REG_EFLAGS, 0x247)
    u.reg_write(x.UC_X86_REG_FPCW, 0x37F)
    u.emu_start(boot, boot + 6)
    ratio_reads, current_reads, looked_up, observed = [], [], [], []

    def trace(uc, address, size, user):
        if address == FIND_OBJECT_BY_ID:
            esp = uc.reg_read(x.UC_X86_REG_ESP)
            looked_up.append(int.from_bytes(uc.mem_read(esp + 4, 4), "little"))
            assert uc.reg_read(x.UC_X86_REG_ECX) == 0x10009000
        if address == ratio_getter:
            ratio_reads.append(uc.reg_read(x.UC_X86_REG_ECX))
        if address == current_getter:
            current_reads.append(uc.reg_read(x.UC_X86_REG_ECX))
        if address == RESUME:
            observed.append(([uc.reg_read(r) for r in regs], uc.reg_read(x.UC_X86_REG_EFLAGS)))

    u.hook_add(unicorn.UC_HOOK_CODE, trace)
    before = bytes(u.mem_read(0x10000000, 0x40000))
    u.emu_start(cave, RESUME + len(finish), count=30000)
    assert u.reg_read(x.UC_X86_REG_EIP) == RESUME + len(finish)
    ratio = struct.unpack("<f", u.mem_read(result, 4))[0]
    assert struct.unpack("<f", u.mem_read(old, 4))[0] == 42.0
    assert u.reg_read(x.UC_X86_REG_ESP) == stack
    assert u.reg_read(x.UC_X86_REG_FPCW) == 0x37F
    assert ratio_reads == {"members": [], "banner": [banner_body], "original": [body]}[path]
    if path == "banner":
        assert looked_up == [42]
        assert not current_reads
    if path == "members":
        assert not looked_up
    saved, flags = observed[0]
    if path == "original" and not native:
        assert saved == [0xDEAD, values[1], 0, 0, *values[4:]]
    elif path != "original":
        assert saved == values
        assert flags == 0x247
    after = bytes(u.mem_read(0x10000000, 0x40000))
    assert after[:0x8000] == before[:0x8000]
    assert after[0x8008:] == before[0x8008:]
    return ratio


@pytest.mark.parametrize("kindof", [0, 0x2000, 0x4000, 0x800000, 0x802000, 0x804000, 0x806000])
@pytest.mark.parametrize("banner_destroys", [False, True])
def test_only_banner_configuration_selects_health_source(kindof, banner_destroys):
    actual = execute(
        [(100, 100), (0, 900)],
        kindof=kindof,
        banner_destroys=banner_destroys,
        path="banner" if banner_destroys else "members",
    )
    assert actual == pytest.approx(0.25 if banner_destroys else 0.1)


@pytest.mark.parametrize(
    "members,expected",
    [
        ([(100, 100), (100, 900)], 0.2),
        ([(50, 100), (0, 900)], 0.05),
        ([(10, 100)], 0.1),
        ([(100, 100)] * 3, 1.0),
        ([], 0.0),
        ([None, (25, 100)], 0.25),
        ([(20, 0), (20, -10), (50, 100)], 0.5),
        ([(20, float("nan")), (50, 100)], 0.5),
        ([(20, 0), (20, -10)], 0.0),
        ([(1, 1)] * 128, 1.0),
    ],
)
@pytest.mark.parametrize("native", [False, True])
def test_combined_current_and_maximum_health(members, expected, native):
    assert execute(members, native=native) == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("slots", [-1, 0, 5, 129])
def test_slots_do_not_affect_the_result(slots):
    assert execute([(10, 100)], slots=slots) == pytest.approx(0.1)


def test_missing_bodies_do_not_contribute_either_sum():
    assert execute([(10, 100)], fault="missing_body") == 0.0


@pytest.mark.parametrize(
    "fault",
    [
        "null_object",
        "null_contain",
        "no_horde_iface",
        "null_data",
        "null_sentinel",
        "cycle",
        "null_node",
    ],
)
def test_invalid_aggregate_input_uses_original(fault):
    assert execute([(10, 100)], fault=fault, path="original") == pytest.approx(0.73)


def test_overbudget_list_discards_partial_sum():
    assert execute([(1, 1)] * 129, path="original") == pytest.approx(0.73)


@pytest.mark.parametrize("banner,expected", [((0, 100), 0.0), ((25, 100), 0.25), ((100, 100), 1.0)])
@pytest.mark.parametrize("native", [False, True])
def test_banner_health_ignores_members(banner, expected, native):
    assert execute(
        [(1, 1)] * 12,
        banner_destroys=True,
        banner=banner,
        native=native,
        fault="cycle",
        path="banner",
    ) == pytest.approx(expected)


@pytest.mark.parametrize(
    "fault",
    [
        "null_contain",
        "no_horde_iface",
        "null_data",
        "no_logic",
        "banner_no_id",
        "banner_missing",
        "banner_self",
        "banner_no_body",
    ],
)
def test_invalid_banner_input_uses_original(fault):
    assert execute([(1, 1)], banner_destroys=True, fault=fault, path="original") == pytest.approx(
        0.73
    )
