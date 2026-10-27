"""Synthetic patch checks and x86 cave execution with ABI-aware native stubs.

Engine side effects and a live revive are deliberately not simulated as proof of game behavior.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from sage_patch.patches.combo_horde_recruitment import (
    ANCHORS as payload_anchors,
)
from sage_patch.patches.combo_horde_recruitment import (
    HORDE_CONTAIN_PRODUCED_GATE,
    HORDE_CONTAIN_PRODUCED_GATE_BYTES,
    ComboHordeRecruitmentPatch,
)
from sage_patch.patches.experimental.hero_horde_death import (
    ANCHORS,
    DEATH_PREPARATION,
    FIND_MODULE,
    HOOK,
    IMMORTAL_BODY_VTABLE,
    NAME_GENERATOR,
    NAME_KEY,
    ORIGINAL,
    RESPAWN_VTABLE,
    RESUME,
    RULE_LOOKUP,
    SECTION_NAME,
    HeroHordeDeathPatch,
    build_code,
)
from sage_patch.utils import file_offset, find_section

from .synthetic import _sparse_image


def image():
    return _sparse_image({**ANCHORS, HOOK: ORIGINAL})


def test_apply_idempotent_and_detect_tampering():
    data = image()
    patch = HeroHordeDeathPatch()
    patch.apply(data)
    assert not patch.verify(data)
    assert patch.detect(data) is not None
    once = bytes(data)
    patch.apply(data)
    assert data == once
    _, off, _ = find_section(data, SECTION_NAME)
    data[off + 17] ^= 1
    before = bytes(data)
    assert patch.verify(data)
    with pytest.raises(ValueError):
        patch.apply(data)
    assert data == before


@pytest.mark.parametrize("va", [HOOK, *ANCHORS])
def test_wrong_build_is_rejected_without_mutation(va):
    data = image()
    data[file_offset(data, va)] ^= 1
    before = bytes(data)
    with pytest.raises(ValueError):
        HeroHordeDeathPatch().apply(data)
    assert data == before


@pytest.mark.full
def test_real_backup():
    configured = os.environ.get("PYSAGE_ROTWK_GAME_DAT")
    if not configured:
        pytest.skip("set PYSAGE_ROTWK_GAME_DAT to test a supplied original executable")
    path = Path(configured)
    original = path.read_bytes()
    assert hashlib.sha256(original).hexdigest() == (
        "5481de75b63e22483660ea8097478faef594f90b9ade7de893e092256ba68a26"
    )
    data = bytearray(original)
    patch = HeroHordeDeathPatch()
    patch.apply(data)
    assert not patch.verify(data)
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "case",
    [
        "success",
        "state4",
        "fallback",
        "null_owner",
        "null_template",
        "nonhero",
        "nonhorde",
        "dead",
        "null_body",
        "other_body",
        "null_xp",
        "null_generator",
        "no_module",
        "wrong_module",
        "wrong_owner",
        "state1",
        "null_data",
        "null_tree",
        "no_rule",
        "auto",
    ],
)
def test_cave_execution(case):
    ucmod = pytest.importorskip("unicorn")
    x = pytest.importorskip("unicorn.x86_const")
    u = ucmod.Uc(ucmod.UC_ARCH_X86, ucmod.UC_MODE_32)
    # Actual engine addresses plus synthetic object memory and stack.
    u.mem_map(0x400000, 0xB00000)
    u.mem_map(0x10000000, 0x20000)
    u.mem_map(0x20000000, 0x20000)
    cave = 0xE00000
    owner, template, body = 0x10000000, 0x10001000, 0x10002000
    xp, runtime, data, tree, rule = (0x10003000, 0x10004000, 0x10005000, 0x10006000, 0x10007000)
    contain, stack = 0x1000811C, 0x20010000

    def write(va, value):
        u.mem_write(va, int(value).to_bytes(4, "little"))

    write(contain - 0x114, 0 if case == "null_owner" else owner)
    write(owner + 4, 0 if case == "null_template" else template)
    write(template + 0x110, 0 if case == "nonhero" else 0x04000000)
    write(template + 0x114, 0 if case == "nonhorde" else 0x2000)
    write(owner + 0x458, case == "dead")
    write(owner + 0x25C, 0 if case == "null_body" else body)
    write(body, 123 if case == "other_body" else IMMORTAL_BODY_VTABLE)
    write(owner + 0x26C, 0 if case == "null_xp" else xp)
    write(xp + 0x24, 3)
    write(NAME_GENERATOR, 0 if case == "null_generator" else 0x10009000)
    write(runtime, 123 if case == "wrong_module" else RESPAWN_VTABLE)
    write(runtime + 8, owner + 1 if case == "wrong_owner" else owner)
    write(runtime + 4, 0 if case == "null_data" else data)
    write(runtime + 0x2C, 1 if case == "state1" else 4 if case == "state4" else 0)
    write(data + 0x10C, 0 if case == "null_tree" else tree)
    write(rule + 0x20, case == "auto")
    u.mem_write(cave, build_code(cave))
    for va, code in {
        NAME_KEY: b"\xc2\x04\x00",
        FIND_MODULE: b"\xc2\x04\x00",
        RULE_LOOKUP: b"\xc2\x04\x00",
        DEATH_PREPARATION: b"\xc3",
    }.items():
        u.mem_write(va, code)
    regs = [
        x.UC_X86_REG_EAX,
        x.UC_X86_REG_EBX,
        x.UC_X86_REG_ECX,
        x.UC_X86_REG_EDX,
        x.UC_X86_REG_ESI,
        x.UC_X86_REG_EDI,
        x.UC_X86_REG_EBP,
    ]
    initial = [0x1111, 0x2222, 0x3333, 0x4444, contain, 0x6666, 0x7777]
    for reg, value in zip(regs, initial, strict=True):
        u.reg_write(reg, value)
    u.reg_write(x.UC_X86_REG_ESP, stack)
    u.reg_write(x.UC_X86_REG_EFLAGS, 0x247)
    u.reg_write(x.UC_X86_REG_FPCW, 0x37F)
    u.reg_write(x.UC_X86_REG_MXCSR, 0x1F80)
    u.reg_write(x.UC_X86_REG_XMM0, 0x1234567890ABCDEF)
    calls, ranks = [], []

    def hook(uc, address, size, user):
        esp = uc.reg_read(x.UC_X86_REG_ESP)
        if address == RESUME:
            uc.emu_stop()
        elif address == NAME_KEY:
            uc.reg_write(x.UC_X86_REG_EAX, 77)
        elif address == FIND_MODULE:
            assert uc.reg_read(x.UC_X86_REG_ECX) == owner
            uc.reg_write(x.UC_X86_REG_EAX, 0 if case == "no_module" else runtime)
        elif address == RULE_LOOKUP:
            assert uc.reg_read(x.UC_X86_REG_ECX) == data + 0x10C
            ptr = int.from_bytes(uc.mem_read(esp + 4, 4), "little")
            ranks.append(int.from_bytes(uc.mem_read(ptr, 4), "little"))
            absent = case == "no_rule" or (case == "fallback" and len(ranks) == 1)
            uc.reg_write(x.UC_X86_REG_EAX, tree if absent else rule)
        elif address == DEATH_PREPARATION:
            assert uc.reg_read(x.UC_X86_REG_ECX) == runtime
            calls.append(address)
            # Exercise restoration after native code clobbers caller-saved registers and FP state.
            uc.reg_write(x.UC_X86_REG_EAX, 0xDEAD)
            uc.reg_write(x.UC_X86_REG_ECX, 0xDEAD)
            uc.reg_write(x.UC_X86_REG_EDX, 0xDEAD)
            uc.reg_write(x.UC_X86_REG_XMM0, 0)
            uc.reg_write(x.UC_X86_REG_MXCSR, 0x3F80)
            write(owner + 0x458, 1)  # real setEffectivelyDead's once-only gate

    u.hook_add(ucmod.UC_HOOK_CODE, hook)
    u.emu_start(cave, RESUME + 1, count=2000)
    assert u.reg_read(x.UC_X86_REG_EIP) == RESUME
    assert [u.reg_read(reg) for reg in regs] == initial
    assert u.reg_read(x.UC_X86_REG_EFLAGS) == 0x247
    assert u.reg_read(x.UC_X86_REG_XMM0) == 0x1234567890ABCDEF
    assert u.reg_read(x.UC_X86_REG_MXCSR) == 0x1F80
    assert u.reg_read(x.UC_X86_REG_FPCW) == 0x37F
    assert u.reg_read(x.UC_X86_REG_ESP) == stack - 4
    expected_owner = 0 if case == "null_owner" else owner
    assert int.from_bytes(u.mem_read(stack - 4, 4), "little") == expected_owner
    assert len(calls) == (case in {"success", "state4", "fallback"})
    if case == "fallback":
        assert ranks == [3, 1]
    if calls:
        # A second invocation on the same effectively-dead owner must not create another record.
        u.reg_write(x.UC_X86_REG_ESP, stack)
        u.emu_start(cave, RESUME + 1, count=2000)
        assert len(calls) == 1


def test_composes_with_payload_patch_in_both_orders():
    planted = {
        **ANCHORS,
        **payload_anchors,
        HOOK: ORIGINAL,
        HORDE_CONTAIN_PRODUCED_GATE: HORDE_CONTAIN_PRODUCED_GATE_BYTES,
    }
    for patches in (
        [HeroHordeDeathPatch(), ComboHordeRecruitmentPatch()],
        [ComboHordeRecruitmentPatch(), HeroHordeDeathPatch()],
    ):
        data = _sparse_image(planted)
        for patch in patches:
            patch.apply(data)
        for patch in patches:
            assert not patch.verify(data)
