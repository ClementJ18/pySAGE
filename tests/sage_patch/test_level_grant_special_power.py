"""Signed XP, relationship filtering and the local parent-horde completion hook."""

import struct
from pathlib import Path

import pytest

from sage_ini.engine import STOCK
from sage_patch import (
    CommandSetLimitPatch,
    LevelGrantSpecialPowerPatch,
    apply_patches,
)
from sage_patch.__main__ import main
from sage_patch.addresses import (
    CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL,
    CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL_BYTES,
    EXPERIENCE_XP_CAP_WINDOWS,
    LEVEL_GRANT_SPECIAL_POWER_DISTRIBUTE_EXPERIENCE,
    LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_GATE,
    LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_GATE_BYTES,
    LEVEL_GRANT_SPECIAL_POWER_HORDE_ANCHORS,
    LEVEL_GRANT_SPECIAL_POWER_RELATIONSHIP_MASK_BYTES,
    LEVEL_GRANT_SPECIAL_POWER_RELATIONSHIP_MASK_INSTRUCTION,
    UPGRADE_MODULE_REMOVAL_WINDOWS,
)
from sage_patch.patches import experience_level_down as xp
from sage_patch.patches import level_grant_special_power as power
from sage_patch.registry import PATCHES
from sage_patch.utils import file_offset, find_section
from tests.sage_patch.test_experience_level_down import image
from tests.sage_patch.test_patching import _synthetic_game_dat, _tiny_pe

GATE = LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_GATE
STOCK_BYTES = LEVEL_GRANT_SPECIAL_POWER_EXPERIENCE_GATE_BYTES
PATCHED_BYTES = bytes.fromhex("0f8491000000")
MASK = LEVEL_GRANT_SPECIAL_POWER_RELATIONSHIP_MASK_INSTRUCTION
MASK_BYTES = LEVEL_GRANT_SPECIAL_POWER_RELATIONSHIP_MASK_BYTES
PATCHED_MASK = bytes.fromhex("c745b807000000")
WINDOWS = [(va, old) for va, (old, _new) in power._windows(0).items()]
_BINARY = Path(__file__).resolve().parents[2] / "game.dat"


def synthetic_image() -> bytearray:
    """Map native VAs into a data-free PE whose raw offset differs from its RVA."""
    data = image()
    for va, old in {**LEVEL_GRANT_SPECIAL_POWER_HORDE_ANCHORS, **dict(WINDOWS)}.items():
        off = file_offset(data, va)
        data[off : off + len(old)] = old
    return data


def test_apply_changes_only_local_windows_and_appends_cave() -> None:
    data = synthetic_image()
    before = bytes(data)
    off = file_offset(data, GATE)
    assert off == GATE - 0x401000 + 0x200
    patch = LevelGrantSpecialPowerPatch()
    assert patch.verify(data)
    assert patch.detect(data) is None
    patch.apply(data)
    assert len(data) > len(before)
    changed = {file_offset(before, va) + i for va, old in WINDOWS for i in range(len(old))}
    assert all(
        a == b or i in changed
        for i, (a, b) in enumerate(
            zip(before[0x200:], data[0x200 : len(before)], strict=True), 0x200
        )
    )
    assert before[off + 1] == 0x8E and data[off + 1] == 0x84
    assert bytes(data[off : off + 6]) == PATCHED_BYTES
    mask_off = file_offset(data, MASK)
    assert before[mask_off : mask_off + 7] == MASK_BYTES
    assert bytes(data[mask_off : mask_off + 7]) == PATCHED_MASK
    assert patch.verify(data) == []
    assert isinstance(patch.detect(data), type(patch))


@pytest.mark.parametrize("va,index", [(va, i) for va, old in WINDOWS for i in range(len(old))])
def test_every_original_byte_is_checked_before_writing(va: int, index: int) -> None:
    data = synthetic_image()
    data[file_offset(data, va) + index] ^= 0xFF
    before = bytes(data)
    with pytest.raises(ValueError, match="expected .* got"):
        LevelGrantSpecialPowerPatch().apply(data)
    assert bytes(data) == before


def test_unmapped_gate_is_rejected() -> None:
    data = _tiny_pe()
    before = bytes(data)
    patch = LevelGrantSpecialPowerPatch()
    with pytest.raises(ValueError, match="not mapped"):
        patch.apply(data)
    assert bytes(data) == before
    assert patch.verify(data)
    assert patch.detect(data) is None


@pytest.mark.parametrize("va", [*LEVEL_GRANT_SPECIAL_POWER_HORDE_ANCHORS, 0x873AAB])
def test_native_horde_contracts_checked_before_allocation(va: int) -> None:
    data = synthetic_image()
    data[file_offset(data, va)] ^= 0xFF
    before = bytes(data)
    with pytest.raises(ValueError, match="expected .* got"):
        LevelGrantSpecialPowerPatch().apply(data)
    assert data == before


def test_cave_and_untouched_horde_guard_are_verified() -> None:
    data = synthetic_image()
    patch = LevelGrantSpecialPowerPatch()
    patch.apply(data)
    section = find_section(data, power.SECTION_NAME)
    assert section is not None
    for off in [section[1], file_offset(data, 0x873AAB)]:
        damaged = bytearray(data)
        damaged[off] ^= 0xFF
        assert patch.verify(damaged) and patch.detect(damaged) is None


def test_horde_cave_disassembles_and_preserves_whole_iterator_call() -> None:
    capstone = pytest.importorskip("capstone")
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    base = 0xF40000
    code = power.build_code(base)
    decoded = list(decoder.disasm(code, base))
    assert sum(i.size for i in decoded) == len(code)
    assert code[:6] == bytes.fromhex("ff9010010000")
    assert any(i.mnemonic == "fxsave" for i in decoded)
    assert any(i.mnemonic == "fxrstor" for i in decoded)
    for va, (old, new) in power._windows(base).items():
        assert sum(i.size for i in decoder.disasm(old, va)) == len(old) == len(new)
        assert sum(i.size for i in decoder.disasm(new, va)) == len(new)


def test_reapplication_is_rejected() -> None:
    data = synthetic_image()
    patch = LevelGrantSpecialPowerPatch()
    patch.apply(data)
    before = bytes(data)
    with pytest.raises(ValueError, match="already carries"):
        patch.apply(data)
    assert bytes(data) == before


def test_xp_only_image_is_not_accepted_as_the_combined_patch() -> None:
    data = synthetic_image()
    off = file_offset(data, GATE)
    data[off : off + 6] = PATCHED_BYTES
    before = bytes(data)
    patch = LevelGrantSpecialPowerPatch()
    assert patch.verify(data) and patch.detect(data) is None
    with pytest.raises(ValueError, match="expected .* got"):
        patch.apply(data)
    assert bytes(data) == before


def test_companion_hook_windows_do_not_overlap() -> None:
    own = {va + n for va, old in WINDOWS for n in range(len(old))}
    for windows in [
        xp._WINDOWS,
        EXPERIENCE_XP_CAP_WINDOWS,
        UPGRADE_MODULE_REMOVAL_WINDOWS,
        {CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL: CONTROL_BAR_SPECIAL_POWER_PERCENT_CALL_BYTES},
    ]:
        assert own.isdisjoint(va + n for va, old in windows.items() for n in range(len(old)))


@pytest.mark.parametrize("va,index", [(va, i) for va, old in WINDOWS for i in range(len(old))])
def test_verify_checks_the_complete_patched_instruction(va: int, index: int) -> None:
    data = synthetic_image()
    patch = LevelGrantSpecialPowerPatch()
    patch.apply(data)
    data[file_offset(data, va) + index] ^= 0xFF
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
    for blob, value in [(MASK_BYTES, 4), (PATCHED_MASK, 7)]:
        (instruction,) = decoder.disasm(blob, MASK)
        assert instruction.size == 7 and instruction.mnemonic == "mov"
        assert instruction.op_str == f"dword ptr [ebp - 0x48], {value}"


@pytest.mark.parametrize("relationship", [0, 1, 2])
@pytest.mark.parametrize("patched", [False, True])
def test_native_relationship_bit_test(relationship: int, patched: bool) -> None:
    unicorn = pytest.importorskip("unicorn")
    regs = pytest.importorskip("unicorn.x86_const")
    machine = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
    machine.mem_map(0x1000, 0x3000)
    # Execute the construction and the native allow() tail after getRelationship returns.
    machine.mem_write(0x1000, PATCHED_MASK if patched else MASK_BYTES)
    machine.reg_write(regs.UC_X86_REG_EBP, 0x2048)
    machine.emu_start(0x1000, 0x1007)
    mask = struct.unpack("<I", machine.mem_read(0x2000, 4))[0]
    machine.mem_write(0x201C, struct.pack("<I", mask))
    machine.mem_write(0x1100, bytes.fromhex("33d2428bc8d3e285560c5e0f95c0"))
    machine.reg_write(regs.UC_X86_REG_ESI, 0x2010)
    machine.reg_write(regs.UC_X86_REG_ESP, 0x3000)
    machine.reg_write(regs.UC_X86_REG_EAX, relationship)
    machine.emu_start(0x1100, 0x110E)
    assert machine.reg_read(regs.UC_X86_REG_EAX) & 0xFF == int(patched or relationship == 2)


@pytest.mark.parametrize("patched", [False, True])
def test_native_player_mask_includes_all_relationships(patched: bool) -> None:
    unicorn = pytest.importorskip("unicorn")
    regs = pytest.importorskip("unicorn.x86_const")
    machine = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
    machine.mem_map(0x1000, 0x3000)
    machine.mem_write(0x200C, struct.pack("<I", 7 if patched else 4))
    # Native fragment at 0x00660B52..0x00660B6F; relative branches stay internal.
    code = bytes.fromhex("8b4e0c33d2f6c10474036a035af6c101740383ca04f6c102740383ca08")
    machine.mem_write(0x1000, code)
    machine.reg_write(regs.UC_X86_REG_ESI, 0x2000)
    machine.reg_write(regs.UC_X86_REG_ESP, 0x3000)
    machine.emu_start(0x1000, 0x1000 + len(code))
    assert machine.reg_read(regs.UC_X86_REG_EDX) == (15 if patched else 3)


@pytest.mark.parametrize("experience", [-2147483648, -250, -1, 0, 1, 250, 2147483647])
def test_x86_skips_only_zero(experience: int) -> None:
    unicorn = pytest.importorskip("unicorn")
    regs = pytest.importorskip("unicorn.x86_const")
    data = synthetic_image()
    LevelGrantSpecialPowerPatch().apply(data)
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
    patch = LevelGrantSpecialPowerPatch()
    assert PATCHES[patch.name] is type(patch)
    assert "level-grant-special-power-negative-experience" not in PATCHES
    assert sum(cls is type(patch) for cls in PATCHES.values()) == 1
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
        apply_patches(source, [LevelGrantSpecialPowerPatch()], output)
    assert source.read_bytes() == data
    assert output.read_bytes() == b"existing output"


@pytest.mark.parametrize("reverse", [False, True])
def test_composes_with_commandset_without_changing_its_result(reverse: bool) -> None:
    data = _synthetic_game_dat()
    size = len(data) - 0x1000
    struct.pack_into("<IIII", data, 0x178 + 8, size, 0x1000, size, 0x1000)
    off = file_offset(data, GATE)
    data[off : off + 6] = STOCK_BYTES
    mask_off = file_offset(data, MASK)
    data[mask_off : mask_off + 7] = MASK_BYTES
    for va, old in {**LEVEL_GRANT_SPECIAL_POWER_HORDE_ANCHORS, **dict(WINDOWS)}.items():
        site = file_offset(data, va)
        data[site : site + len(old)] = old
    expected = bytearray(data)
    other = CommandSetLimitPatch(count=64)
    other.apply(expected)
    patches = [other, LevelGrantSpecialPowerPatch()]
    for patch in reversed(patches) if reverse else patches:
        patch.apply(data)
    assert all(patch.verify(data) == [] for patch in patches)
    detected = other.detect(data)
    assert detected is not None and detected.count == 64
    if not reverse:
        changed = {file_offset(expected, va) + i for va, old in WINDOWS for i in range(len(old))}
        assert all(
            a == b or i in changed
            for i, (a, b) in enumerate(
                zip(expected[0x200:], data[0x200 : len(expected)], strict=True), 0x200
            )
        )


@pytest.mark.full
@pytest.mark.skipif(
    not _BINARY.is_file(),
    reason="requires the local unpatched RotWK 2.01.2614.37001 game.dat.backup",
)
def test_real_binary_changes_only_local_windows_and_appends_verified_cave(tmp_path: Path) -> None:
    source = _BINARY
    before = source.read_bytes()
    # Confirm the copied native fragments and ModuleData evidence against the supplied image.
    assert before[file_offset(before, 0x00660BA3) : file_offset(before, 0x00660BA3) + 14] == (
        bytes.fromhex("33d2428bc8d3e285560c5e0f95c0")
    )
    assert struct.unpack_from("<III", before, file_offset(before, 0x00C11DC0)) == (
        0x00893738,
        0x00660B85,
        0x00660B3E,
    )
    assert struct.unpack_from("<I", before, file_offset(before, 0x00C735E4))[0] == 0x008C6FA4
    table = file_offset(before, 0x00C73550)
    assert [struct.unpack_from("<I", before, table + i * 16 + 12)[0] for i in range(4)] == (
        [0xD0, 0xD4, 0xDC, 0xD8]
    )
    patch = LevelGrantSpecialPowerPatch()
    output = apply_patches(source, [patch], tmp_path / "game.dat")
    after = output.read_bytes()
    assert patch.verify(after) == []
    assert len(after) > len(before)
    changed = {file_offset(before, va) + i for va, old in WINDOWS for i in range(len(old))}
    assert all(
        a == b or i in changed
        for i, (a, b) in enumerate(
            zip(before[0x1000:], after[0x1000 : len(before)], strict=True), 0x1000
        )
    )
    assert after[file_offset(after, 0x873AAB) : file_offset(after, 0x873AAB) + 2] == b"\x76\x2f"
    assert find_section(after, power.SECTION_NAME) is not None
    assert source.read_bytes() == before
