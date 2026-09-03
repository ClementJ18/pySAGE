"""The persistent spellbook cache gate, tested without needing a running game."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest

from sage_patch import addresses as ad
from sage_patch.patches import commandset_button_upgrade as buttons
from sage_patch.patches.commandset_button_upgrade import CommandSetButtonUpgradePatch
from sage_patch.patches.experimental import spellbook_commandset_refresh as refresh
from sage_patch.registry import PATCHES
from sage_patch.utils import allocate_section, find_section, va_to_offset

from .synthetic import spellbook_commandset_refresh_image
from .test_commandset_button_upgrade import Cpu, Machine

_BASE = 0x03000000
_UI = 0x10000
_PLAYER = 0x20000
_OBJECT = 0x30000
_NAME = 0x40000
_STORE = 0x50000
_SET = 0x60000
_DIGEST = "948bac5ed89e33c605ac8b7e5c901e4b2554d953bc35b4ca3be4d7ff7c46cbd8"


def _at(data: bytes | bytearray, va: int, size: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None
    return bytes(data[off : off + size])


def test_surface() -> None:
    cls = refresh.SpellbookCommandSetRefreshPatch
    assert PATCHES[cls.name] is cls
    assert cls.experimental and cls().ini_surface().is_stock
    assert cls.detect(spellbook_commandset_refresh_image()) is None
    assert len(refresh.SECTION_NAME) <= 8
    assert "command-set-upgrade-drawable-guard" not in PATCHES


def test_review_does_not_change_the_live_tested_refresh_machine_code() -> None:
    code = refresh.build_guard(_BASE)
    assert len(code) == 75
    assert hashlib.sha256(code).hexdigest() == (
        "9b288e96b7f312d8b4567c2a5fcaa3b116a41ace3aea4c6d231346cdc45f6045"
    )


def test_round_trip_and_only_five_original_code_bytes_change() -> None:
    original = spellbook_commandset_refresh_image()
    data = bytearray(original)
    patch = refresh.SpellbookCommandSetRefreshPatch()
    patch.apply(data)
    assert patch.verify(data) == []
    assert patch.detect(data) is not None
    assert refresh.HOOK_BYTES == bytes.fromhex("3b7e287455")
    off = va_to_offset(data, ad.SPELLBOOK_UI_CACHE_HOOK)
    assert off is not None
    assert {i for i in range(0x400, len(original)) if original[i] != data[i]} <= set(
        range(off, off + 5)
    )
    before = bytes(data)
    with pytest.raises(ValueError, match="expected"):
        patch.apply(data)
    assert data == before


@pytest.mark.parametrize("offset", range(len(refresh.CACHE_BYTES)))
def test_any_changed_cache_byte_fails_closed_before_mutation(offset: int) -> None:
    data = spellbook_commandset_refresh_image()
    off = va_to_offset(data, ad.SPELLBOOK_UI_CACHE + offset)
    assert off is not None
    data[off] ^= 1
    before = bytes(data)
    with pytest.raises(ValueError, match="expected"):
        refresh.SpellbookCommandSetRefreshPatch().apply(data)
    assert data == before


@pytest.mark.parametrize("va", refresh.ANCHORS)
def test_changed_anchor_rejected_by_apply_and_verify(va: int) -> None:
    patch = refresh.SpellbookCommandSetRefreshPatch()
    for patched in (False, True):
        data = spellbook_commandset_refresh_image()
        if patched:
            patch.apply(data)
        off = va_to_offset(data, va)
        assert off is not None
        data[off] ^= 1
        if patched:
            assert patch.verify(data)
        else:
            with pytest.raises(ValueError, match="expected"):
                patch.apply(data)


def test_verify_checks_cave_and_jump_target_and_stock_marking_loop() -> None:
    patch = refresh.SpellbookCommandSetRefreshPatch()
    for va in (None, ad.SPELLBOOK_UI_CACHE_HOOK + 1, ad.SPELLBOOK_UI_CACHE_REBUILD):
        data = spellbook_commandset_refresh_image()
        patch.apply(data)
        section = find_section(data, refresh.SECTION_NAME)
        assert section is not None
        off = section[1] if va is None else va_to_offset(data, va)
        assert off is not None
        data[off] ^= 1
        assert patch.verify(data)


@pytest.mark.parametrize("padding", (False, True))
def test_dynamic_cave_allocation(padding: bool) -> None:
    data = spellbook_commandset_refresh_image()
    if padding:
        allocate_section(data, ".other", lambda _va: bytes(0x1800), 0x60000060)
    patch = refresh.SpellbookCommandSetRefreshPatch()
    patch.apply(data)
    assert patch.verify(data) == []
    section = find_section(data, refresh.SECTION_NAME)
    assert section is not None
    jump = _at(data, ad.SPELLBOOK_UI_CACHE_HOOK, 5)
    assert ad.SPELLBOOK_UI_CACHE_HOOK + 5 + struct.unpack("<i", jump[1:])[0] == section[0]


@pytest.mark.parametrize(
    "player,cached_player,obj,resolved,cached_set,exit_va,call_count",
    [
        (_PLAYER, _PLAYER, _OBJECT, _SET, _SET, ad.SPELLBOOK_UI_CACHE_RETURN, 3),
        (_PLAYER, _PLAYER, _OBJECT, _SET + 4, _SET, ad.SPELLBOOK_UI_CACHE_REBUILD, 3),
        (_PLAYER, _PLAYER + 4, _OBJECT, _SET, _SET, ad.SPELLBOOK_UI_CACHE_PLAYER_CHANGED, 0),
        (0, _PLAYER, 0, 0, _SET, ad.SPELLBOOK_UI_CACHE_PLAYER_CHANGED, 0),
        (0, 0, 0, 0, 0, ad.SPELLBOOK_UI_CACHE_RETURN, 0),
        (_PLAYER, _PLAYER, 0, 0, 0, ad.SPELLBOOK_UI_CACHE_RETURN, 1),
        (_PLAYER, _PLAYER, 0, 0, _SET, ad.SPELLBOOK_UI_CACHE_REBUILD, 1),
        (_PLAYER, _PLAYER, _OBJECT, 0, _SET, ad.SPELLBOOK_UI_CACHE_REBUILD, 3),
        (_PLAYER, _PLAYER, _OBJECT, 0, 0, ad.SPELLBOOK_UI_CACHE_RETURN, 3),
        (_PLAYER, _PLAYER, _OBJECT, _SET, 0, ad.SPELLBOOK_UI_CACHE_REBUILD, 3),
    ],
)
def test_execute_gate(
    player: int,
    cached_player: int,
    obj: int,
    resolved: int,
    cached_set: int,
    exit_va: int,
    call_count: int,
) -> None:
    m = Machine()
    m.regs.update(esi=_UI, edi=player, esp=0x90000, ebp=0x87654, ebx=0x1234)
    initial = dict(m.regs)
    m.write32(_UI + 0x28, cached_player)
    m.write32(_UI + 0x2C, cached_set)
    m.write(_UI + 0x30, bytes([0xAA]) * 34)
    m.write32(ad.THE_COMMAND_SET_STORE, _STORE)
    calls: list[int] = []

    class CacheCpu(Cpu):
        def engine_call(self, target: int) -> None:
            calls.append(target)
            if target == ad.PLAYER_GET_SPELLBOOK_OBJECT:
                assert m.regs["ecx"] == player != 0
                result = obj
            elif target == ad.OBJECT_GET_COMMAND_SET_STRING:
                assert m.regs["ecx"] == obj != 0
                result = _NAME
            else:
                assert target == ad.COMMAND_SET_STORE_FIND_COMMAND_SET
                assert m.regs["ecx"] == _STORE
                assert m.pop() == _NAME  # ret 4; the other two helpers take no arguments
                result = resolved
            m.regs.update(eax=result, ecx=0xBAD, edx=0xBAD)

    code = refresh.build_guard(_BASE)
    m.write(_BASE, code)
    cpu = CacheCpu(m, code, _BASE, _BASE)
    for _ in range(40):
        if not _BASE <= cpu.eip < _BASE + len(code):
            break
        cpu.step()
    else:
        pytest.fail("gate did not leave the cave")
    assert cpu.eip == exit_va
    assert len(calls) == call_count
    assert m.read32(_UI + 0x28) == cached_player
    assert m.read32(_UI + 0x2C) == cached_set  # only the original stock path writes it
    assert bytes(m.read8(_UI + 0x30 + i) for i in range(34)) == bytes([0xAA]) * 34
    for reg in ("esi", "edi", "esp", "ebp", "ebx"):
        assert m.regs[reg] == initial[reg]
    if exit_va == ad.SPELLBOOK_UI_CACHE_REBUILD:
        assert m.regs["eax"] == resolved


def test_stock_rebuild_and_guard_boundaries_are_whole_instructions() -> None:
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    ins = list(md.disasm(refresh.CACHE_BYTES, ad.SPELLBOOK_UI_CACHE))
    boundaries = {i.address for i in ins}
    assert {
        ad.SPELLBOOK_UI_CACHE_HOOK,
        ad.SPELLBOOK_UI_CACHE_PLAYER_CHANGED,
        ad.SPELLBOOK_UI_CACHE_REBUILD,
        ad.SPELLBOOK_UI_CACHE_RETURN,
    } <= boundaries
    tail = [i for i in ins if ad.SPELLBOOK_UI_CACHE_REBUILD <= i.address < 0x00931030]
    assert [(i.mnemonic, i.op_str) for i in tail[:4]] == [
        ("lea", "edi, [esi + 0x30]"),
        ("lea", "ecx, [esi + 0x51]"),
        ("cmp", "edi, ecx"),
        ("mov", "dword ptr [esi + 0x2c], eax"),
    ]
    assert any(i.mnemonic == "rep stosd" for i in tail)
    assert any(i.mnemonic == "rep stosb" for i in tail)
    assert 0x51 - 0x30 == 33
    assert refresh.CACHE_BYTES.endswith(bytes.fromhex("8366280083662c005f5ec3"))


class StockCacheCpu(Cpu):
    """Add only the stock cache's short branches and fill-loop instructions to the test CPU."""

    def step(self) -> None:
        m = self.machine
        op = m.read8(self.eip)
        if op in (0x74, 0x75, 0xEB):
            self.imm8()
            displacement = self.simm8()
            if op == 0xEB or self.condition(op & 0xF):
                self.eip += displacement
        elif op == 0x2B:
            self.imm8()
            reg, operand = self.modrm()
            left = self.load(("reg", reg))
            self.store(("reg", reg), m._sub_flags(left, self.load(operand)))
        elif op == 0xC1:
            self.imm8()
            group, operand = self.modrm()
            assert group == 5  # shr r/m32,imm8; its flags are not consumed by this loop
            self.store(operand, self.load(operand) >> self.imm8())
        elif op == 0xF3:
            self.imm8()
            second = self.imm8()
            assert second in (0xAB, 0xAA)
            width = 4 if second == 0xAB else 1
            for _ in range(m.regs["ecx"]):
                value = m.regs["eax"].to_bytes(4, "little")[:width]
                m.write(m.regs["edi"], value)
                m.regs["edi"] += width
            m.regs["ecx"] = 0
        else:
            super().step()


@pytest.mark.parametrize("resolved", (0, _SET, _SET + 4))
def test_execute_stock_cache_write_all_33_markers_and_epilogue(resolved: int) -> None:
    m = Machine()
    m.regs.update(esp=0x90000, ebp=0x80000, ebx=0x1234)
    m.write(_UI + 0x30, bytes([0xAA]) * 34)
    m.write32(_UI + 0x28, _PLAYER)
    m.push(0x0BADF00D)
    m.push(0x1111)  # saved ESI
    m.push(0x2222)  # saved EDI
    m.regs.update(esi=_UI, edi=_PLAYER, eax=resolved)
    m.write(ad.SPELLBOOK_UI_CACHE, refresh.CACHE_BYTES)
    cpu = StockCacheCpu(
        m, refresh.CACHE_BYTES, ad.SPELLBOOK_UI_CACHE, ad.SPELLBOOK_UI_CACHE_REBUILD
    )
    cpu.run(limit=40)
    assert m.read32(_UI + 0x2C) == resolved
    assert m.read32(_UI + 0x28) == _PLAYER
    assert bytes(m.read8(_UI + 0x30 + i) for i in range(34)) == bytes([1]) * 33 + b"\xaa"
    assert (m.regs["esi"], m.regs["edi"], m.regs["esp"], m.regs["ebp"], m.regs["ebx"]) == (
        0x1111,
        0x2222,
        0x90000,
        0x80000,
        0x1234,
    )


@pytest.mark.parametrize(
    "active,blocked,player,valid",
    [
        (False, False, _PLAYER, True),
        (True, True, _PLAYER, True),
        (True, False, _PLAYER, False),
        (True, False, 0, False),
    ],
)
def test_existing_game_state_and_player_gates_remain_effective(
    active: bool,
    blocked: bool,
    player: int,
    valid: bool,
) -> None:
    m = Machine()
    m.regs.update(esp=0x90000, ecx=_UI, esi=0x1111, edi=0x2222)
    m.write32(_UI + 0x28, _PLAYER)
    m.write32(_UI + 0x2C, _SET)
    m.write(_UI + 0x30, bytes([0xAA]) * 33)
    m.write32(0x00DE4950, 0x7777)  # optional pre-game gate receiver
    data = spellbook_commandset_refresh_image()
    refresh.SpellbookCommandSetRefreshPatch().apply(data)
    section = find_section(data, refresh.SECTION_NAME)
    assert section is not None
    va, off, size = section
    m.write(va, bytes(data[off : off + size]))
    m.write(ad.SPELLBOOK_UI_CACHE, _at(data, ad.SPELLBOOK_UI_CACHE, len(refresh.CACHE_BYTES)))

    class PrecheckCpu(StockCacheCpu):
        def engine_call(self, target: int) -> None:
            results = {
                0x00441B60: int(active),
                0x00441E4A: int(blocked),
                0x006A8839: player,
                0x006AAC52: int(valid),
            }
            assert target in results, "invalid state reached a spellbook/Object lookup"
            m.regs.update(eax=results[target], ecx=0xBAD, edx=0xBAD)

    m.push(0x0BADF00D)
    cpu = PrecheckCpu(m, bytes(data[off : off + size]), va, ad.SPELLBOOK_UI_CACHE)
    cpu.run(limit=80)
    assert m.read32(_UI + 0x28) == m.read32(_UI + 0x2C) == 0
    assert bytes(m.read8(_UI + 0x30 + i) for i in range(33)) == bytes([0xAA]) * 33
    assert (m.regs["esi"], m.regs["edi"], m.regs["esp"]) == (0x1111, 0x2222, 0x90000)


def test_repeated_updates_upgrade_revoke_object_loss_and_player_switch() -> None:
    """Run the emitted detour plus the entire stock function over successive UI updates."""
    m = Machine()
    data = spellbook_commandset_refresh_image()
    refresh.SpellbookCommandSetRefreshPatch().apply(data)
    section = find_section(data, refresh.SECTION_NAME)
    assert section is not None
    va, off, size = section
    m.write(va, bytes(data[off : off + size]))
    m.write(ad.SPELLBOOK_UI_CACHE, _at(data, ad.SPELLBOOK_UI_CACHE, len(refresh.CACHE_BYTES)))
    m.write32(ad.THE_COMMAND_SET_STORE, _STORE)
    m.write32(0x00DE4950, 0)  # optional blocked-state gate is absent
    player, obj, resolved = _PLAYER, _OBJECT, _SET

    class UpdateCpu(StockCacheCpu):
        def engine_call(self, target: int) -> None:
            if target == ad.PLAYER_GET_SPELLBOOK_OBJECT:
                assert m.regs["ecx"] == player != 0
                result = obj
            elif target == ad.OBJECT_GET_COMMAND_SET_STRING:
                assert m.regs["ecx"] == obj != 0
                result = _NAME
            elif target == ad.COMMAND_SET_STORE_FIND_COMMAND_SET:
                assert m.regs["ecx"] == _STORE
                assert m.pop() == _NAME
                result = resolved
            else:
                results = {0x00441B60: 1, 0x006A8839: player, 0x006AAC52: 1}
                assert target in results
                result = results[target]
            m.regs.update(eax=result, ecx=0xBAD, edx=0xBAD)

    for player, _obj, resolved, marked in (
        (_PLAYER, _OBJECT, _SET, True),
        (_PLAYER, _OBJECT, _SET, False),
        (_PLAYER, _OBJECT, _SET + 4, True),
        (_PLAYER, _OBJECT, _SET + 4, False),
        (_PLAYER, _OBJECT, _SET, True),  # revoke the upgrade
        (_PLAYER, 0, 0, True),
        (_PLAYER, 0, 0, False),
        (_PLAYER, _OBJECT, _SET, True),
        (_PLAYER + 4, _OBJECT, _SET, True),  # stock rebuilds even for the same set
        (0, 0, 0, False),  # stock null-Player path does not mark
        (0, 0, 0, False),
        (_PLAYER, _OBJECT, _SET, True),
    ):
        # The real update consumes the marks each frame. An in-place button edit must not
        # spuriously invalidate pointer identity; that limitation is documented explicitly.
        obj = _obj
        m.write(_UI + 0x30, bytes(33) + b"\xaa")
        m.write32(_SET + 0x14, m.read32(_SET + 0x14) + 1)
        m.regs.update(esp=0x90000, ebp=0x80000, ebx=0x1234, esi=0x1111, edi=0x2222, ecx=_UI)
        m.push(0x0BADF00D)
        cpu = UpdateCpu(m, bytes(data[off : off + size]), va, ad.SPELLBOOK_UI_CACHE)
        cpu.run(limit=100)
        assert m.read32(_UI + 0x28) == player
        assert m.read32(_UI + 0x2C) == resolved
        assert bytes(m.read8(_UI + 0x30 + i) for i in range(34)) == (
            bytes([int(marked)]) * 33 + b"\xaa"
        )
        assert (m.regs["esi"], m.regs["edi"], m.regs["esp"], m.regs["ebp"], m.regs["ebx"]) == (
            0x1111,
            0x2222,
            0x90000,
            0x80000,
            0x1234,
        )


@pytest.mark.full
def test_real_binary_and_command_button_composition() -> None:
    path = Path(__file__).resolve().parents[2] / "tools/BFME-FILES/game.dat.backup"
    if not path.exists():
        pytest.skip("local pristine backup unavailable")
    original = path.read_bytes()
    assert len(original) == 11_346_944
    assert hashlib.sha256(original).hexdigest() == _DIGEST
    for patches in (
        [refresh.SpellbookCommandSetRefreshPatch()],
        [refresh.SpellbookCommandSetRefreshPatch(), CommandSetButtonUpgradePatch()],
        [CommandSetButtonUpgradePatch(), refresh.SpellbookCommandSetRefreshPatch()],
    ):
        data = bytearray(original)
        for patch in patches:
            patch.apply(data)
        assert all(patch.verify(data) == [] for patch in patches)
        assert find_section(data, ".csudraw") is None
        assert _at(data, 0x008B7C87, 24) == _at(original, 0x008B7C87, 24)
    assert path.read_bytes() == original


@pytest.mark.full
def test_all_used_addresses_against_the_clean_game_binary() -> None:
    path = Path(__file__).resolve().parents[2] / "tools/BFME-FILES/game.dat.backup"
    if not path.exists():
        pytest.skip("local pristine backup unavailable")
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == _DIGEST
    assert _at(data, ad.SPELLBOOK_UI_CACHE, len(refresh.CACHE_BYTES)) == refresh.CACHE_BYTES
    for site, target in (
        (0x00930FF0, ad.PLAYER_GET_SPELLBOOK_OBJECT),
        (0x00930FFB, ad.OBJECT_GET_COMMAND_SET_STRING),
        (0x00931007, ad.COMMAND_SET_STORE_FIND_COMMAND_SET),
        (ad.SPELLBOOK_UI_UPDATE_CACHE_CALL, ad.SPELLBOOK_UI_CACHE),
        (0x00931351, buttons.GET_COMMAND_BUTTON),
        (0x008B7C82, buttons.SET_COMMAND_SET_STRING_OVERRIDE),
        (0x008B7C8E, buttons.UI_DESELECT),
        (0x008B7C9A, buttons.UI_RESELECT),
    ):
        code = _at(data, site, 5)
        assert code[0] == 0xE8
        assert site + 5 + struct.unpack("<i", code[1:])[0] == target
    assert ad.SPELLBOOK_UI_CACHE_HOOK == 0x00930FDE
    assert ad.SPELLBOOK_UI_CACHE_PLAYER_CHANGED == ad.SPELLBOOK_UI_CACHE_HOOK + 5
    short_branch = _at(data, ad.SPELLBOOK_UI_CACHE_HOOK + 3, 2)
    assert short_branch[0] == 0x74
    assert ad.SPELLBOOK_UI_CACHE_HOOK + 5 + short_branch[1] == ad.SPELLBOOK_UI_CACHE_RETURN
    assert ad.SPELLBOOK_UI_CACHE_REBUILD == 0x00931007 + 5
    assert _at(data, ad.SPELLBOOK_UI_UPDATE_COMMAND_BUTTON, 4) == bytes.fromhex("8b4b2c56")
    assert _at(data, 0x00931000, 6) == b"\x8b\x0d" + struct.pack("<I", ad.THE_COMMAND_SET_STORE)
    assert _at(data, 0x008B7C87, 6) == b"\x8b\x0d" + struct.pack("<I", buttons.SELECTION_UI)
    assert _at(data, 0x008B7C9F, 5) == b"\xa1" + struct.pack("<I", ad.THE_COMMAND_SET_STORE)
    assert ad.THE_IN_GAME_UI == 0x00DE4830 != ad.THE_COMMAND_SET_STORE
    assert _at(data, 0x00C6DF20, 4) == struct.pack("<I", buttons.UPGRADE_IMPL_VA)
    assert _at(data, 0x00C6DF18, 4) == struct.pack("<I", buttons.UNUPGRADE_IMPL_VA)
    getter = _at(data, ad.OBJECT_GET_COMMAND_SET_STRING, 0x44)
    assert bytes.fromhex("8dbe3c040000") in getter  # the override at Object+43C
    assert getter.endswith(bytes.fromhex("5f5ec3"))
    assert ad.COMMAND_SET_STORE_FIND_COMMAND_SET == buttons.FIND_COMMAND_SET
    assert path.read_bytes() == data
