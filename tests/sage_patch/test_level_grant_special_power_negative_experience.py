"""The signed XP gate is a one-byte edit, independent of other patches."""

import struct
from pathlib import Path

import pytest

from sage_ini.engine import STOCK
from sage_patch import (
    CommandSetLimitPatch,
    LevelGrantSpecialPowerNegativeExperiencePatch,
    apply_patches,
)
from sage_patch.__main__ import main
from sage_patch.addresses import (
    LEVEL_GRANT_SPECIAL_POWER_DISTRIBUTE_EXPERIENCE,
    LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_GATE,
    LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_GATE_BYTES,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import file_offset
from tests.sage_patch.test_patching import _synthetic_game_dat, _tiny_pe

GATE = LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_GATE
STOCK_BYTES = LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_GATE_BYTES
PATCHED_BYTES = bytes.fromhex("0f8491000000")
_BINARY = Path(__file__).resolve().parents[2] / "tools" / "BFME-FILES" / "game.dat.backup"


def synthetic_image() -> bytearray:
    """Map the real VA into a small PE whose raw offset deliberately differs from its RVA."""
    data = _tiny_pe()
    struct.pack_into("<I", data, 0x178 + 12, 0x4C6E00)  # .text RVA
    off = file_offset(data, GATE)
    data[off : off + len(STOCK_BYTES)] = STOCK_BYTES
    return data


def test_apply_changes_only_the_condition_byte() -> None:
    data = synthetic_image()
    before = bytes(data)
    off = file_offset(data, GATE)
    assert off == 0x295
    patch = LevelGrantSpecialPowerNegativeExperiencePatch()
    assert patch.verify(data)
    assert patch.detect(data) is None
    patch.apply(data)
    assert len(data) == len(before)
    assert [i for i, (old, new) in enumerate(zip(before, data, strict=True)) if old != new] == [
        off + 1
    ]
    assert before[off + 1] == 0x8E and data[off + 1] == 0x84
    assert bytes(data[off : off + 6]) == PATCHED_BYTES
    assert patch.verify(data) == []
    assert isinstance(patch.detect(data), type(patch))


@pytest.mark.parametrize("index", range(6))
def test_every_original_byte_is_checked_before_writing(index: int) -> None:
    data = synthetic_image()
    data[file_offset(data, GATE) + index] ^= 0xFF
    before = bytes(data)
    with pytest.raises(ValueError, match="expected .* got"):
        LevelGrantSpecialPowerNegativeExperiencePatch().apply(data)
    assert bytes(data) == before


def test_unmapped_gate_is_rejected() -> None:
    data = _tiny_pe()
    before = bytes(data)
    patch = LevelGrantSpecialPowerNegativeExperiencePatch()
    with pytest.raises(ValueError, match="not mapped"):
        patch.apply(data)
    assert bytes(data) == before
    assert patch.verify(data)
    assert patch.detect(data) is None


def test_reapplication_is_rejected() -> None:
    data = synthetic_image()
    patch = LevelGrantSpecialPowerNegativeExperiencePatch()
    patch.apply(data)
    before = bytes(data)
    with pytest.raises(ValueError, match="expected .* got"):
        patch.apply(data)
    assert bytes(data) == before


@pytest.mark.parametrize("index", range(6))
def test_verify_checks_the_complete_patched_instruction(index: int) -> None:
    data = synthetic_image()
    patch = LevelGrantSpecialPowerNegativeExperiencePatch()
    patch.apply(data)
    data[file_offset(data, GATE) + index] ^= 0xFF
    assert patch.verify(data)
    assert patch.detect(data) is None


def test_instruction_length_and_jump_target_are_preserved() -> None:
    capstone = pytest.importorskip("capstone")
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    assert LEVEL_GRANT_SPECIAL_POWER_DISTRIBUTE_EXPERIENCE == 0x008C6E82
    for blob, mnemonic in [(STOCK_BYTES, "jle"), (PATCHED_BYTES, "je")]:
        instructions = list(decoder.disasm(blob, GATE))
        assert len(instructions) == 1
        instruction = instructions[0]
        assert (instruction.mnemonic, instruction.size, int(instruction.op_str, 16)) == (
            mnemonic,
            6,
            0x008C6F2C,
        )
        assert GATE + len(blob) + struct.unpack("<i", blob[2:])[0] == 0x008C6F2C


@pytest.mark.parametrize("experience", [-2147483648, -250, -1, 0, 1, 250, 2147483647])
def test_x86_skips_only_zero(experience: int) -> None:
    unicorn = pytest.importorskip("unicorn")
    regs = pytest.importorskip("unicorn.x86_const")
    data = synthetic_image()
    LevelGrantSpecialPowerNegativeExperiencePatch().apply(data)
    off = file_offset(data, GATE)
    machine = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
    machine.mem_map(GATE & ~0xFFF, 0x1000)
    # The confirmed TEST EAX,EAX sets the flags consumed by the patched branch.
    machine.mem_write(GATE - 2, b"\x85\xc0" + bytes(data[off : off + 6]))
    machine.reg_write(regs.UC_X86_REG_EAX, experience & 0xFFFFFFFF)
    expected = 0x008C6F2C if experience == 0 else GATE + 6
    machine.emu_start(GATE - 2, expected, count=2)
    assert machine.reg_read(regs.UC_X86_REG_EIP) == expected


def test_registered_regular_patch_and_cli_roundtrip(tmp_path: Path) -> None:
    patch = LevelGrantSpecialPowerNegativeExperiencePatch()
    assert PATCHES[patch.name] is type(patch)
    assert not patch.experimental
    assert patch.runtime_verified == ""
    assert patch.ini_surface() is STOCK
    assert patch.options() == {}
    source, output = tmp_path / "stock.dat", tmp_path / "patched.dat"
    source.write_bytes(synthetic_image())
    before = source.read_bytes()
    assert main(["apply", patch.name, "--in", str(source), "--out", str(output)]) == 0
    assert main(["verify", patch.name, str(output)]) == 0
    assert source.read_bytes() == before


def test_failed_apply_does_not_write_output(tmp_path: Path) -> None:
    source, output = tmp_path / "stock.dat", tmp_path / "patched.dat"
    data = synthetic_image()
    data[file_offset(data, GATE) + 5] ^= 0xFF
    source.write_bytes(data)
    output.write_bytes(b"existing output")
    with pytest.raises(ValueError):
        apply_patches(source, [LevelGrantSpecialPowerNegativeExperiencePatch()], output)
    assert source.read_bytes() == data
    assert output.read_bytes() == b"existing output"


@pytest.mark.parametrize("reverse", [False, True])
def test_composes_with_commandset_without_changing_its_result(reverse: bool) -> None:
    data = _synthetic_game_dat()
    size = len(data) - 0x1000
    struct.pack_into("<IIII", data, 0x178 + 8, size, 0x1000, size, 0x1000)
    off = file_offset(data, GATE)
    data[off : off + 6] = STOCK_BYTES
    expected = bytearray(data)
    other = CommandSetLimitPatch(count=64)
    other.apply(expected)
    patches = [other, LevelGrantSpecialPowerNegativeExperiencePatch()]
    for patch in reversed(patches) if reverse else patches:
        patch.apply(data)
    assert all(patch.verify(data) == [] for patch in patches)
    assert [i for i, (a, b) in enumerate(zip(expected, data, strict=True)) if a != b] == [off + 1]


@pytest.mark.full
@pytest.mark.skipif(
    not _BINARY.is_file(),
    reason="requires the local unpatched RotWK 2.01.2614.37001 game.dat.backup",
)
def test_real_binary_changes_only_one_byte(tmp_path: Path) -> None:
    source = _BINARY
    before = source.read_bytes()
    patch = LevelGrantSpecialPowerNegativeExperiencePatch()
    output = apply_patches(source, [patch], tmp_path / "game.dat")
    after = output.read_bytes()
    assert patch.verify(after) == []
    assert len(after) == len(before)
    changed = [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b]
    assert changed == [file_offset(before, GATE) + 1]
    assert source.read_bytes() == before
