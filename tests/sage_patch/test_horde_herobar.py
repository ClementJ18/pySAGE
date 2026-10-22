"""Patch integrity, composition and executable x87 tests for the CE-derived UI hook."""

from __future__ import annotations

import itertools
import json
import struct
from pathlib import Path

import pytest

from sage_patch.patches.combo_horde_recruitment import (
    ANCHORS as PAYLOAD_ANCHORS,
)
from sage_patch.patches.combo_horde_recruitment import (
    HORDE_CONTAIN_PRODUCED_GATE,
    HORDE_CONTAIN_PRODUCED_GATE_BYTES,
    ComboHordeRecruitmentPatch,
)
from sage_patch.patches.experimental.hero_horde_death import (
    ANCHORS as DEATH_ANCHORS,
)
from sage_patch.patches.experimental.hero_horde_death import (
    HOOK as DEATH_HOOK,
)
from sage_patch.patches.experimental.hero_horde_death import (
    ORIGINAL as DEATH_ORIGINAL,
)
from sage_patch.patches.experimental.hero_horde_death import HeroHordeDeathPatch
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
from tools import build_hero_horde_patch as builder

from .synthetic import _sparse_image


def test_install_repeat_and_tamper():
    data = _sparse_image({**ANCHORS, HOOK: ORIGINAL})
    p = HordeHerobarPatch()
    p.apply(data)
    assert not p.verify(data)
    assert p.detect(data) is not None
    once = bytes(data)
    p.apply(data)
    assert data == once
    _, off, _ = find_section(data, SECTION_NAME)
    data[off + 30] ^= 1
    before = bytes(data)
    assert p.verify(data)
    with pytest.raises(ValueError):
        p.apply(data)
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
            **DEATH_ANCHORS,
            HOOK: ORIGINAL,
            DEATH_HOOK: DEATH_ORIGINAL,
            HORDE_CONTAIN_PRODUCED_GATE: HORDE_CONTAIN_PRODUCED_GATE_BYTES,
        }
    )
    patches = [HeroHordeDeathPatch(), ComboHordeRecruitmentPatch(), HordeHerobarPatch()]
    for i in order:
        patches[i].apply(data)
    for p in patches:
        assert not p.verify(data)


def test_real_backup():
    path = Path(__file__).resolve().parents[2] / "tools/BFME-FILES/game.dat.backup"
    if not path.exists():
        pytest.skip("local game binary is not distributed")
    original = path.read_bytes()
    data = bytearray(original)
    p = HordeHerobarPatch()
    p.apply(data)
    assert not p.verify(data)
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "ratios,slots,case,expected",
    [
        ([1.0] * 5, 5, "normal", 1.0),
        ([1.0] * 3, 5, "normal", 0.6),
        ([1.0], 5, "normal", 0.2),
        ([0.1], 5, "normal", 0.02),
        ([], 5, "normal", 0.0),
        ([1.0, 0.5, 0.25], 3, "normal", 1.75 / 3),
        ([None, 1.0], 5, "normal", 0.2),
        ([1.0, 0.5], 5, "missing_body", 0.2),
        ([1.0] * 128, 128, "normal", 1.0),
        ([1.0], 0, "normal", 0.73),
        ([1.0], -1, "normal", 0.73),
        ([1.0], 129, "normal", 0.73),
        ([1.0] * 129, 5, "normal", 0.73),
        ([1.0], 5, "cycle", 0.73),
        ([1.0], 5, "null_node", 0.73),
        ([1.0], 5, "null_object", 0.73),
        ([1.0], 5, "null_template", 0.73),
        ([1.0], 5, "nonhorde", 0.73),
        ([1.0], 5, "melee_horde", 0.73),
        ([1.0], 5, "melee_only", 0.73),
        ([1.0] * 12, 12, "banner_health", 0.25),
        ([1.0] * 12, 12, "banner_native", 0.25),
        ([1.0], 5, "banner_zero", 0.0),
        ([1.0], 5, "banner_full", 1.0),
        ([1.0], 5, "banner_no_logic", 1.0),
        ([1.0], 5, "banner_no_contain", 1.0),
        ([1.0], 5, "banner_no_data", 1.0),
        ([1.0], 5, "banner_no_iface", 1.0),
        ([1.0], 5, "banner_no_id", 1.0),
        ([1.0], 5, "banner_missing", 1.0),
        ([1.0], 5, "banner_self", 1.0),
        ([1.0], 5, "banner_no_body", 1.0),
        ([1.0], 5, "nonmelee_with_banner", 0.2),
        ([1.0], 5, "null_contain", 0.73),
        ([1.0], 5, "no_horde_iface", 0.73),
        ([1.0], 5, "null_data", 0.73),
        ([1.0], 5, "null_sentinel", 0.73),
    ],
)
def test_execute_x87(ratios, slots, case, expected):
    unicorn = pytest.importorskip("unicorn")
    x = pytest.importorskip("unicorn.x86_const")
    u = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
    u.mem_map(0x400000, 0xB00000)
    u.mem_map(0x10000000, 0x40000)
    u.mem_map(0x20000000, 0x20000)
    cave, getter, iface_getter, boot = 0xE00000, 0xE01000, 0xE01100, 0xE01200
    obj, template, contain = 0x10000000, 0x10001000, 0x10002020
    data, sentinel, vtable, body_vtable = 0x10003000, 0x10004000, 0x10005000, 0x10006000
    body, frame, stack = 0x10007000, 0x20018000, 0x20010000
    result, old, old_value = 0x10008000, 0x10008004, 0x10008008

    def word(va, n):
        u.mem_write(va, struct.pack("<I", n & 0xFFFFFFFF))

    def floating(va, f):
        u.mem_write(va, struct.pack("<f", f))

    word(frame - 0x20, 0 if case == "null_object" else obj)
    word(obj + 4, 0 if case == "null_template" else template)
    word(template + 0x114, 0 if case in {"nonhorde", "melee_only"} else 0x2000)
    # MELEE_HORDE is bit 23 of dword Template+114 (byte +116, mask 80).
    if case in {"melee_horde", "melee_only"} or case.startswith("banner_"):
        existing = int.from_bytes(u.mem_read(template + 0x114, 4), "little")
        word(template + 0x114, existing | 0x800000)
    word(obj + 0x258, 0 if case in {"null_contain", "banner_no_contain"} else contain)
    word(contain, vtable)
    word(vtable + 0x7C, iface_getter)
    word(contain - 0x1C, 0 if case in {"null_data", "banner_no_data"} else data)
    word(data + 0x98, slots)
    word(contain + 0x34, 0 if case == "null_sentinel" else sentinel)
    word(body, body_vtable)
    word(body_vtable + 0x14, getter)
    floating(body + 4, 1.0 if case.startswith("banner_") else 0.73)
    banner, banner_body = 0x1000A000, 0x1000B000
    word(data + 0x224, int(case.startswith("banner_") or case == "nonmelee_with_banner"))
    word(contain + 0xFC + 0x150, 0 if case == "banner_no_id" else 42)
    word(THE_GAME_LOGIC, 0 if case == "banner_no_logic" else 0x10009000)
    word(banner + 0x25C, 0 if case == "banner_no_body" else banner_body)
    word(banner_body, body_vtable)
    floating(
        banner_body + 4, 0.0 if case == "banner_zero" else 1.0 if case == "banner_full" else 0.25
    )
    found = 0 if case == "banner_missing" else obj if case == "banner_self" else banner
    u.mem_write(
        FIND_OBJECT_BY_ID, b"\xb8" + struct.pack("<I", found) + bytes.fromhex("31c931d2c20400")
    )
    floating(old_value, 42.0)
    nodes = [0x10010000 + i * 0x100 for i in range(len(ratios))]
    word(sentinel, nodes[0] if nodes else sentinel)
    for i, (node, ratio) in enumerate(zip(nodes, ratios, strict=True)):
        member, member_body = 0x10020000 + i * 0x300, node + 0x40
        following = nodes[i + 1] if i + 1 < len(nodes) else sentinel
        word(node, node if case == "cycle" else 0 if case == "null_node" else following)
        word(node + 8, 0 if ratio is None else member)
        word(member + 0x25C, 0 if case == "missing_body" and i == 1 else member_body)
        word(member_body, body_vtable)
        floating(member_body + 4, ratio or 0)
    # Native stubs deliberately clobber volatile GPRs/flags, preserving callee-saved loop regs.
    if case == "banner_native":
        # Reproduce the reported full ImmortalBody versus damaged banner using the real getter,
        # not a stub that already returns the desired ratio.
        getter = 0x008C1D75
        u.mem_write(getter, ANCHORS[getter])
        word(body_vtable + 0x14, getter)
        floating(body + 8, 1000.0)
        floating(body + 0x10, 1000.0)
        floating(banner_body + 8, 250.0)
        floating(banner_body + 0x10, 1000.0)
    else:
        u.mem_write(getter, bytes.fromhex("d94104b8adde000031c931d2c3"))
    returned_iface = 0 if case in {"no_horde_iface", "banner_no_iface"} else contain + 0xFC
    u.mem_write(
        iface_getter, b"\xb8" + struct.pack("<I", returned_iface) + bytes.fromhex("31c931d2c3")
    )
    u.mem_write(cave, build_code(cave))
    u.mem_write(boot, b"\xd9\x05" + struct.pack("<I", old_value))
    # Consume result and a preexisting x87 value, proving one net push and no leaked partial sum.
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
    original_calls = []
    contain_calls = []
    banner_calls = []
    looked_up = []
    observed = []

    def trace(uc, address, size, user):
        if address == FIND_OBJECT_BY_ID:
            esp = uc.reg_read(x.UC_X86_REG_ESP)
            looked_up.append(int.from_bytes(uc.mem_read(esp + 4, 4), "little"))
            assert uc.reg_read(x.UC_X86_REG_ECX) == 0x10009000
        if address == getter and uc.reg_read(x.UC_X86_REG_ECX) == banner_body:
            banner_calls.append(address)
        if address == iface_getter:
            contain_calls.append(address)
        if address == getter and uc.reg_read(x.UC_X86_REG_ECX) == body:
            original_calls.append(address)
        if address == RESUME:
            observed.append(([uc.reg_read(r) for r in regs], uc.reg_read(x.UC_X86_REG_EFLAGS)))

    u.hook_add(unicorn.UC_HOOK_CODE, trace)
    before = bytes(u.mem_read(0x10000000, 0x40000))
    u.emu_start(cave, RESUME + len(finish), count=10000)
    assert u.reg_read(x.UC_X86_REG_EIP) == RESUME + len(finish)
    actual = struct.unpack("<f", u.mem_read(result, 4))[0]
    assert actual == pytest.approx(expected, abs=1e-6)
    assert struct.unpack("<f", u.mem_read(old, 4))[0] == 42.0
    assert u.reg_read(x.UC_X86_REG_ESP) == stack
    banner_success = case in {"banner_health", "banner_native", "banner_zero", "banner_full"}
    fallback = expected == 0.73 or (case.startswith("banner_") and not banner_success)
    assert len(banner_calls) == int(banner_success)
    if banner_success:
        assert looked_up == [42]
    assert len(original_calls) == int(fallback)
    if case in {"nonhorde", "melee_horde", "melee_only"}:
        assert not contain_calls  # exclusion happens before even asking for a HordeInterface
    saved, flags = observed[0]
    if fallback:
        assert saved == [0xDEAD, values[1], 0, 0, *values[4:]]
    else:
        assert saved == values
        assert flags == 0x247
    after = bytes(u.mem_read(0x10000000, 0x40000))
    # Only the test's two result words changed; no object/member/contain/HP writes by the cave.
    assert after[:0x8000] == before[:0x8000]
    assert after[0x8008:] == before[0x8008:]


@pytest.mark.parametrize(
    "flags,expected",
    [
        (["--only-herobar"], ["horde-herobar"]),
        (
            ["--herobar", "--payload"],
            ["hero-horde-death", "combo-horde-recruitment", "horde-herobar"],
        ),
    ],
)
def test_safe_build_options_and_restore(tmp_path, monkeypatch, flags, expected):
    source = tmp_path / "game.dat.backup"
    target = tmp_path / "patched" / "game.dat"
    source.write_bytes(
        _sparse_image(
            {
                **ANCHORS,
                **PAYLOAD_ANCHORS,
                **DEATH_ANCHORS,
                HOOK: ORIGINAL,
                DEATH_HOOK: DEATH_ORIGINAL,
                HORDE_CONTAIN_PRODUCED_GATE: HORDE_CONTAIN_PRODUCED_GATE_BYTES,
            }
        )
    )
    original = source.read_bytes()
    monkeypatch.setattr(builder, "SOURCE_SHA256", builder.digest(original))
    argv = ["build", "--in", str(source), "--out", str(target), *flags]
    monkeypatch.setattr("sys.argv", argv)
    builder.main()
    manifest_path = target.with_name("game.dat.json")
    manifest = json.loads(manifest_path.read_text())
    assert manifest["patches"] == expected
    assert not HordeHerobarPatch().verify(target.read_bytes())
    if flags == ["--only-herobar"]:
        assert (
            target.read_bytes()[file_offset(target.read_bytes(), DEATH_HOOK) :][:6]
            == DEATH_ORIGINAL
        )
    once, mtime = target.read_bytes(), target.stat().st_mtime_ns
    builder.main()
    assert target.read_bytes() == once
    assert target.stat().st_mtime_ns == mtime
    restored = tmp_path / "restored" / "game.dat"
    monkeypatch.setattr(
        "sys.argv",
        ["build", "--in", str(source), "--out", str(restored), "--restore", str(manifest_path)],
    )
    builder.main()
    assert restored.read_bytes() == original == source.read_bytes()
