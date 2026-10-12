"""Execute the native availability branch/epilogue and its UI-only detour."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch import (
    ExperienceLevelDownPatch,
    ExperienceXpCapPatch,
    LevelGrantSpecialPowerNegativeExperiencePatch,
    SpecialPowerPauseButtonPatch,
    UpgradeModuleRemovalPatch,
)
from sage_patch.__main__ import main
from sage_patch.addresses import (
    CONTROL_BAR_SPECIAL_POWER_PAUSE_ANCHORS,
    CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL,
    CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL_BYTES,
)
from sage_patch.patches import special_power_pause_button as ui
from sage_patch.utils import file_offset, find_section
from tests.sage_patch.test_experience_follow_up import UpgradeWorld, upgrade_image


def image() -> bytearray:
    data = upgrade_image()
    for va, blob in {
        **CONTROL_BAR_SPECIAL_POWER_PAUSE_ANCHORS,
        CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL: CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL_BYTES,
    }.items():
        off = file_offset(data, va)
        data[off : off + len(blob)] = blob
    return data


def test_originals_registration_single_window_and_repeat_rejection() -> None:
    data = image()
    original = bytes(data)
    patch = SpecialPowerPauseButtonPatch()
    assert not patch.experimental and not patch.runtime_verified
    assert patch.detect(data) is None
    patch.apply(data)
    assert patch.verify(data) == []
    assert isinstance(patch.detect(data), type(patch))
    hook = file_offset(original, CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL)
    assert all(
        a == b or hook <= n < hook + 7
        for n, (a, b) in enumerate(
            zip(original[0x200:], data[0x200 : len(original)], strict=True), 0x200
        )
    )
    snapshot = bytes(data)
    with pytest.raises(ValueError, match="already carries"):
        patch.apply(data)
    assert data == snapshot


@pytest.mark.parametrize(
    "va", [*CONTROL_BAR_SPECIAL_POWER_PAUSE_ANCHORS, CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL]
)
def test_fingerprint_failure_is_atomic(va: int) -> None:
    data = image()
    data[file_offset(data, va)] ^= 0xFF
    snapshot = bytes(data)
    with pytest.raises(ValueError, match="unexpected build"):
        SpecialPowerPauseButtonPatch().apply(data)
    assert data == snapshot


@pytest.mark.parametrize("va", [CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL, 0x009438C8, 0])
def test_modified_hook_anchor_or_cave_is_rejected(va: int) -> None:
    data = image()
    patch = SpecialPowerPauseButtonPatch()
    patch.apply(data)
    located = find_section(data, ui.SECTION_NAME)
    assert located is not None
    off = file_offset(data, va) if va else located[1]
    data[off] ^= 0xFF
    assert patch.verify(data)
    assert patch.detect(data) is None


@pytest.mark.parametrize("base", [0x00ED3000, 0x00F80000])
def test_relative_targets_and_displaced_x87_call(base: int) -> None:
    capstone = pytest.importorskip("capstone")
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    code = ui.build_code(base)
    instructions = list(decoder.disasm(code, base))
    assert sum(i.size for i in instructions) == len(code)
    addresses = {i.address for i in instructions}
    targets = {
        int(i.op_str, 16)
        for i in instructions
        if i.mnemonic.startswith("j") and i.op_str.startswith("0x")
    }
    assert targets - addresses == {0x0094358C, 0x009438C8}
    assert code.count(CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL_BYTES) == 1
    assert not any(i.mnemonic.startswith(("fld", "fst", "fpop")) for i in instructions)
    replacement = ui._replacement(base)
    assert replacement == b"\xe9" + struct.pack("<i", base - (0x00943585 + 5)) + b"\x90\x90"
    assert sum(i.size for i in decoder.disasm(replacement, 0x00943585)) == 7


def test_cli_and_registry(tmp_path: Path) -> None:
    source, output = tmp_path / "stock.dat", tmp_path / "patched.dat"
    original = image()
    source.write_bytes(original)
    assert (
        main(["apply", "special-power-pause-button", "--in", str(source), "--out", str(output)])
        == 0
    )
    assert main(["verify", "special-power-pause-button", str(output)]) == 0
    assert SpecialPowerPauseButtonPatch().verify(output.read_bytes()) == []
    assert source.read_bytes() == original


class AvailabilityWorld(UpgradeWorld):
    """Native UI cooldown/status-zero branches, with a modeled ready continuation."""

    frame = 0x1107000
    ui_stack = 0x1106F00
    progress = 0x102B000
    percent = 0x102B004
    percent_calls = 0x102B008

    def __init__(self, *, permanent: bool | None = None, patched: bool = True) -> None:
        super().__init__(permanent=permanent)
        self.uc.mem_map(0, 0x1000)  # fs:[0] restored by the native SEH epilogue
        for va, blob in CONTROL_BAR_SPECIAL_POWER_PAUSE_ANCHORS.items():
            self.uc.mem_write(va, blob)
        self.uc.mem_write(0x943585, CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL_BYTES)
        if patched:
            base = 0xF40000
            self.uc.mem_write(base, ui.build_code(base))
            self.uc.mem_write(0x943585, ui._replacement(base))
        self.w32(0x1026200 + 0x3C, 0x896E31)
        self.w32(0x1026200 + 8, 0xF18000)
        self.w32(0x1026200 + 0xC, 0xF18020)
        self.services[0xF18020] = (0, lambda args: 0)
        self.services[0x942490] = (2, lambda args: 0)
        self.uc.mem_write(
            0xF18000,
            b"\xff\x05"
            + struct.pack("<I", self.percent_calls)
            + b"\xd9\x05"
            + struct.pack("<I", self.percent)
            + b"\xc3",
        )
        self.wfloat(0xBD1908, 1)
        # The ready branch is unmodified; model only its subsequent non-pause checks.
        self.uc.mem_write(
            0x9435D7, b"\xb8\x01\x00\x00\x00\xe9" + struct.pack("<i", 0x942C60 - 0x9435E1)
        )

    def evaluate(
        self,
        *,
        ready: bool | None = None,
        percent: float = 0.5,
        entry: int = 0x94357A,
        expected_top: int = 0,
    ) -> int:
        if ready is not None:
            self.w32(0x1026200 + 4, 0xF18040)
            self.services[0xF18040] = (0, lambda args: int(ready))
        else:
            self.w32(0x1026200 + 4, 0x896C72)
        self.wfloat(self.percent, percent)
        self.wfloat(self.progress, 1)
        self.w32(self.frame, 0x12345678)
        self.w32(self.frame + 4, self.stop)
        self.w32(self.frame + 0x14, self.progress)
        self.w32(self.frame - 0xC, 0x43215678)
        for n, saved in enumerate([0x22345678, 0x32345678, 0x42345678]):
            self.w32(self.ui_stack + n * 4, saved)
        self.uc.reg_write(self.regs.UC_X86_REG_EBP, self.frame)
        self.uc.reg_write(self.regs.UC_X86_REG_ESP, self.ui_stack)
        self.uc.reg_write(self.regs.UC_X86_REG_ESI, self.power)
        self.uc.reg_write(self.regs.UC_X86_REG_EBX, self.object)
        self.uc.reg_write(self.regs.UC_X86_REG_EDI, 0x102C000)
        self.uc.emu_start(entry, self.stop, count=50000)
        assert self.uc.reg_read(self.regs.UC_X86_REG_EIP) == self.stop
        assert self.uc.reg_read(self.regs.UC_X86_REG_ESP) == self.frame + 28
        assert self.uc.reg_read(self.regs.UC_X86_REG_EBP) == 0x12345678
        assert self.uc.reg_read(self.regs.UC_X86_REG_EDI) == 0x22345678
        assert self.uc.reg_read(self.regs.UC_X86_REG_EBX) == 0x32345678
        assert self.uc.reg_read(self.regs.UC_X86_REG_ESI) == 0x42345678
        assert self.r32(0) == 0x43215678
        assert (self.uc.reg_read(self.regs.UC_X86_REG_FPSW) >> 11) & 7 == expected_top
        return self.uc.reg_read(self.regs.UC_X86_REG_EAX)


@pytest.mark.parametrize("layout", ["ordinary", "update", "unknown"])
@pytest.mark.parametrize("pause", [0, 1, 2, 0x7FFFFFFF, -1])
def test_not_ready_ui_and_layout_specific_counter(layout: str, pause: int) -> None:
    world = AvailabilityWorld()
    offset = 0xC if layout != "update" else 8
    world.w32(world.power + offset, pause)
    if layout == "update":
        world.w32(0x1026200 + 0x3C, 0x991500)
        world.w32(world.power + 0xC, 99999)  # timestamp, not this interface's pause count
    elif layout == "ordinary":
        world.w32(world.power + 8, 99999)  # ready frame, not this interface's pause count
    else:
        world.w32(0x1026200 + 0x3C, 0xF18100)
    disabled = pause > 0 and layout != "unknown"
    state = bytes(world.uc.mem_read(world.power, 0x40))
    assert world.evaluate(ready=False) == (0 if disabled else 5)
    assert world.r32(world.percent_calls) == int(not disabled)
    assert bytes(world.uc.mem_read(world.power, 0x40)) == state


def test_ready_branch_bypasses_pause_hook() -> None:
    world = AvailabilityWorld()
    world.w32(world.power + 0xC, 2)
    assert world.evaluate(ready=True) == 1
    assert world.r32(world.percent_calls) == 0


@pytest.mark.parametrize("percent", [0, 0.25, 0.75, 1])
def test_unpaused_cooldown_matches_original_and_balances_x87(percent: float) -> None:
    stock = AvailabilityWorld(patched=False)
    patched = AvailabilityWorld()
    for world in [stock, patched]:
        world.w32(world.power + 0xC, 0)
    assert stock.evaluate(ready=False, percent=percent) == patched.evaluate(
        ready=False, percent=percent
    )
    assert stock.uc.mem_read(stock.progress, 4) == patched.uc.mem_read(patched.progress, 4)
    assert patched.r32(patched.percent_calls) == 1


@pytest.mark.parametrize("paused", [False, True])
def test_both_paths_preserve_a_preexisting_x87_stack_value(paused: bool) -> None:
    world = AvailabilityWorld()
    world.w32(world.power + 0xC, int(paused))
    value, entry, consume = 0x102D000, 0xF19000, 0xF19020
    world.wfloat(value, 123.25)
    world.uc.mem_write(
        entry,
        b"\xd9\x05"
        + struct.pack("<I", value)
        + b"\xe9"
        + struct.pack("<i", 0x94357A - (entry + 11)),
    )
    assert world.evaluate(ready=False, entry=entry, expected_top=7) == (0 if paused else 5)
    world.uc.mem_write(
        consume,
        b"\xd9\x1d"
        + struct.pack("<I", value)
        + b"\xe9"
        + struct.pack("<i", world.stop - (consume + 11)),
    )
    world.uc.emu_start(consume, world.stop, count=100)
    assert struct.unpack("<f", world.uc.mem_read(value, 4))[0] == 123.25
    assert (world.uc.reg_read(world.regs.UC_X86_REG_FPSW) >> 11) & 7 == 0


@pytest.mark.parametrize("permanent", [None, False, True])
def test_real_upgrade_lifecycle_and_ui_status(permanent: bool | None) -> None:
    world = AvailabilityWorld(permanent=permanent)
    assert world.evaluate() == 0
    world.unlock()
    assert world.evaluate() == 1
    world.w32(world.power + 8, 500)
    assert world.evaluate() == 5
    world.add(-300)  # real XP loss and native UnpauseSpecialPowerUpgrade removal
    assert world.rank == 2
    assert world.evaluate() == (5 if permanent else 0)
    assert world.r32(world.power + 0xC) == int(not permanent)
    world.unlock()
    assert world.evaluate() == 5  # native cooldown survives the unlock
    world.w32(world.now + 0x40, 500)
    assert world.evaluate() == 1


_BINARY = Path(__file__).resolve().parents[2] / "tools" / "BFME-FILES" / "game.dat.backup"


@pytest.mark.full
@pytest.mark.skipif(not _BINARY.is_file(), reason="requires the local supported RotWK binary")
@pytest.mark.parametrize("ui_first", [False, True])
def test_supported_binary_and_all_level_down_companions_compose(ui_first: bool) -> None:
    original = _BINARY.read_bytes()
    data = bytearray(original)
    patches = [
        LevelGrantSpecialPowerNegativeExperiencePatch(),
        ExperienceLevelDownPatch(),
        UpgradeModuleRemovalPatch(),
        ExperienceXpCapPatch(),
    ]
    if ui_first:
        patches.insert(0, SpecialPowerPauseButtonPatch())
    else:
        patches.append(SpecialPowerPauseButtonPatch())
    for patch in patches:
        patch.apply(data)
    assert all(patch.verify(data) == [] for patch in patches)
    assert _BINARY.read_bytes() == original
