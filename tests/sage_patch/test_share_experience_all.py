"""Data-free PE and executable x86 coverage of the multi-behavior XP dispatch."""

from __future__ import annotations

import itertools
import struct
from pathlib import Path

import pytest

from sage_patch import AutoDepositInflationPatch, MaintenanceCostPatch, ShareExperienceAllPatch
from sage_patch.addresses import SHARE_EXPERIENCE_DISPATCH, SHARE_EXPERIENCE_DISPATCH_BYTES
from sage_patch.patches import share_experience_all as share
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset
from tests.sage_patch.test_maintenance_cost import synthetic_image


@pytest.fixture
def image() -> bytearray:
    data = synthetic_image()
    for address, stock, _replacement in share._windows(0):
        off = va_to_offset(data, address)
        assert off is not None
        data[off : off + len(stock)] = stock
    return data


def test_registered_and_stable() -> None:
    assert PATCHES["share-experience-all"] is ShareExperienceAllPatch
    assert ShareExperienceAllPatch.author == "Ostkannit"
    assert ShareExperienceAllPatch.experimental is False
    assert ".experimental." not in ShareExperienceAllPatch.__module__


def test_signature_and_fallthrough() -> None:
    assert len(SHARE_EXPERIENCE_DISPATCH_BYTES) == 24
    displacement = struct.unpack_from("<i", SHARE_EXPERIENCE_DISPATCH_BYTES, 2)[0]
    assert SHARE_EXPERIENCE_DISPATCH + 6 + displacement == 0x0088305B
    assert SHARE_EXPERIENCE_DISPATCH + 24 == 0x006955A0


def test_apply_verify_and_only_local_edit(image: bytearray) -> None:
    before = bytes(image)
    patch = ShareExperienceAllPatch()
    assert patch.verify(image)
    patch.apply(image)
    assert patch.verify(image) == []
    assert isinstance(patch.detect(image), ShareExperienceAllPatch)
    off = va_to_offset(image, SHARE_EXPERIENCE_DISPATCH)
    assert off is not None
    _assert_only_windows_changed(before, image)
    located = find_section(image, share.SECTION_NAME)
    assert located is not None
    va, raw, size = located
    hook = bytes(image[off : off + 24])
    assert hook[:4] == bytes.fromhex("ff750856")
    assert hook[4] == 0xE8
    assert SHARE_EXPERIENCE_DISPATCH + 9 + struct.unpack_from("<i", hook, 5)[0] == va
    assert hook[9:] == bytes.fromhex("83c408") + b"\x90" * 12
    assert image[raw : raw + size] == share._assemble(va)
    e = struct.unpack_from("<I", image, 0x3C)[0]
    table = e + 24 + struct.unpack_from("<H", image, e + 20)[0]
    count = struct.unpack_from("<H", image, e + 6)[0]
    flags = struct.unpack_from("<I", image, table + (count - 1) * 40 + 36)[0]
    assert flags == 0x60000020


@pytest.mark.parametrize("index", range(24))
def test_signature_failure_is_atomic(image: bytearray, index: int) -> None:
    off = va_to_offset(image, SHARE_EXPERIENCE_DISPATCH)
    assert off is not None
    image[off + index] ^= 0xFF
    before = bytes(image)
    with pytest.raises(ValueError, match="expected"):
        ShareExperienceAllPatch().apply(image)
    assert image == before


def test_reapply_is_atomic(image: bytearray) -> None:
    patch = ShareExperienceAllPatch()
    patch.apply(image)
    before = bytes(image)
    with pytest.raises(ValueError, match="already carries"):
        patch.apply(image)
    assert image == before


@pytest.mark.parametrize("where", ["hook", "padding", "helper", "size", "truncated"])
def test_verify_detects_damage(image: bytearray, where: str) -> None:
    patch = ShareExperienceAllPatch()
    patch.apply(image)
    located = find_section(image, share.SECTION_NAME)
    assert located is not None
    _va, raw, _size = located
    off = va_to_offset(image, SHARE_EXPERIENCE_DISPATCH)
    assert off is not None
    if where == "size":
        e = struct.unpack_from("<I", image, 0x3C)[0]
        table = e + 24 + struct.unpack_from("<H", image, e + 20)[0]
        count = struct.unpack_from("<H", image, e + 6)[0]
        struct.pack_into("<I", image, table + (count - 1) * 40 + 8, 1)
    elif where == "truncated":
        del image[raw + 3 :]
    else:
        at = {"hook": off + 5, "padding": off + 23, "helper": raw + 10}[where]
        image[at] ^= 0xFF
    assert patch.verify(image)
    assert patch.detect(image) is None


@pytest.mark.parametrize("order", tuple(itertools.permutations(range(3))))
def test_composition(image: bytearray, order: tuple[int, ...]) -> None:
    patches = (ShareExperienceAllPatch(), MaintenanceCostPatch(), AutoDepositInflationPatch())
    for index in order:
        patches[index].apply(image)
    for patch in patches:
        assert patch.verify(image) == [], (patch.name, order)


@pytest.mark.parametrize(
    "matches", [(), (False,), (True,), (True, True), (False, True, False, True)]
)
@pytest.mark.parametrize("xp", [0x42F78000, 0, 0x80000000, 0x3F800001, 0xBF800000])
def test_x86_dispatch_preserves_abi_and_original_bits(
    image: bytearray, matches: tuple[bool, ...], xp: int
) -> None:
    unicorn = pytest.importorskip("unicorn")
    regs = pytest.importorskip("unicorn.x86_const")
    patch = ShareExperienceAllPatch()
    patch.apply(image)
    located = find_section(image, share.SECTION_NAME)
    assert located is not None
    va, raw, size = located
    off = va_to_offset(image, SHARE_EXPERIENCE_DISPATCH)
    assert off is not None
    uc = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
    uc.mem_map(0x100000, 0x20000)
    uc.mem_map(0x690000, 0x10000)
    uc.mem_map(va & ~0xFFF, 0x1000)
    uc.mem_write(va, bytes(image[raw : raw + size]))
    uc.mem_write(SHARE_EXPERIENCE_DISPATCH, bytes(image[off : off + 24]))
    obj, modules, query_vtable, share_vtable = 0x100000, 0x101000, 0x102000, 0x103000
    query, dispatch, frame, stack = 0x104000, 0x104100, 0x110000, 0x10F000

    def write32(address: int, value: int) -> None:
        uc.mem_write(address, struct.pack("<I", value))

    def read32(address: int) -> int:
        return struct.unpack("<I", uc.mem_read(address, 4))[0]

    write32(obj + 0x24C, modules)
    write32(query_vtable + 0xA4, query)
    write32(share_vtable, dispatch)
    write32(frame + 8, xp)
    # Actual x86 returns enforce the virtual methods' distinct stack contracts.
    uc.mem_write(query, b"\xc3")
    uc.mem_write(dispatch, b"\xc2\x04\x00")
    answers: dict[int, int] = {}
    expected: list[int] = []
    for i, match in enumerate(matches):
        module = 0x105000 + i * 0x100
        iface = module + 0x20
        write32(modules + i * 4, module)
        write32(module + 0x0C, query_vtable)
        write32(iface, share_vtable)
        answers[module + 0x0C] = iface if match else 0
        if match:
            expected.append(iface)
    write32(modules + len(matches) * 4, 0)
    visited: list[int] = []
    received: list[tuple[int, int]] = []

    def callback(machine: object, address: int, insn_size: int, user_data: object) -> None:
        if address == query:
            this = uc.reg_read(regs.UC_X86_REG_ECX)
            visited.append(this)
            uc.reg_write(regs.UC_X86_REG_EAX, answers[this])
        elif address == dispatch:
            arg = uc.reg_read(regs.UC_X86_REG_ESP) + 4
            received.append((uc.reg_read(regs.UC_X86_REG_ECX), read32(arg)))
            write32(arg, 0xDEADBEEF)
            uc.reg_write(regs.UC_X86_REG_EAX, 0xDEADC0DE)
        else:
            return
        uc.reg_write(regs.UC_X86_REG_ECX, 0xBADCAFE)
        uc.reg_write(regs.UC_X86_REG_EDX, 0xBADF00D)

    uc.hook_add(unicorn.UC_HOOK_CODE, callback)
    preserved = {
        regs.UC_X86_REG_EBX: 0x12345678,
        regs.UC_X86_REG_ESI: obj,
        regs.UC_X86_REG_EDI: 0x87654321,
        regs.UC_X86_REG_EBP: frame,
        regs.UC_X86_REG_ESP: stack,
    }
    for reg, value in preserved.items():
        uc.reg_write(reg, value)
    uc.emu_start(SHARE_EXPERIENCE_DISPATCH, 0x006955A0, count=1000)
    assert uc.reg_read(regs.UC_X86_REG_EIP) == 0x006955A0
    assert visited == list(answers)
    assert received == [(iface, xp) for iface in expected]
    assert read32(frame + 8) == xp
    for reg, value in preserved.items():
        assert uc.reg_read(reg) == value


def test_nonidentity_file_mapping(image: bytearray) -> None:
    # Give the text section a raw offset different from its RVA.
    data = image[:0x800] + image[0x1000:]
    e = struct.unpack_from("<I", data, 0x3C)[0]
    table = e + 24 + struct.unpack_from("<H", data, e + 20)[0]
    struct.pack_into("<I", data, table + 20, 0x800)
    off = va_to_offset(data, SHARE_EXPERIENCE_DISPATCH)
    assert off == SHARE_EXPERIENCE_DISPATCH - 0x400000 - 0x800
    patch = ShareExperienceAllPatch()
    patch.apply(data)
    assert patch.verify(data) == []
    assert data[off : off + 4] == bytes.fromhex("ff750856")


@pytest.mark.full
def test_real_baseline_apply_verify() -> None:
    path = Path(__file__).resolve().parents[2] / "tools/BFME-FILES/game.dat.backup"
    if not path.is_file():
        pytest.skip("no ROTWK baseline present")
    data = bytearray(path.read_bytes())
    before = bytes(data)
    patch = ShareExperienceAllPatch()
    patch.apply(data)
    assert patch.verify(data) == []
    off = va_to_offset(data, SHARE_EXPERIENCE_DISPATCH)
    assert off is not None
    _assert_only_windows_changed(before, data)


def _assert_only_windows_changed(before: bytes, after: bytearray) -> None:
    restored = bytearray(after[: len(before)])
    for address, stock, _replacement in share._windows(0):
        off = va_to_offset(before, address)
        assert off is not None
        restored[off : off + len(stock)] = before[off : off + len(stock)]
    assert restored[0x400:] == before[0x400:]


@pytest.mark.parametrize("window", [1, 2])
def test_new_signatures_fail_atomically(image: bytearray, window: int) -> None:
    address, stock, _replacement = share._windows(0)[window]
    off = va_to_offset(image, address)
    assert off is not None
    for index in range(len(stock)):
        damaged = bytearray(image)
        damaged[off + index] ^= 0xFF
        before = bytes(damaged)
        with pytest.raises(ValueError, match="expected"):
            ShareExperienceAllPatch().apply(damaged)
        assert damaged == before


@pytest.mark.parametrize("window", [1, 2])
def test_new_hooks_detect_corruption(image: bytearray, window: int) -> None:
    patch = ShareExperienceAllPatch()
    patch.apply(image)
    address, stock, _replacement = share._windows(0)[window]
    off = va_to_offset(image, address)
    assert off is not None
    for index in range(len(stock)):
        damaged = bytearray(image)
        damaged[off + index] ^= 0xFF
        assert patch.verify(damaged)


def test_calc_control_flow_and_private_scratch() -> None:
    capstone = pytest.importorskip("capstone")
    cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    instructions = list(cs.disasm(share._assemble_scaling(0x200000), 0x200000))
    calls = [int(i.op_str, 16) for i in instructions if i.mnemonic == "call"]
    assert calls == [
        share.SHARE_EXPERIENCE_GET_DROPOFF,
        share.EXPERIENCE_TRACKER_ADD_EXPERIENCE_POINTS,
    ]
    assert instructions[-1].mnemonic == "jmp"
    assert int(instructions[-1].op_str, 16) == share.SHARE_EXPERIENCE_CALC_RESUME
    assert [i.op_str for i in instructions if i.mnemonic == "fstp" and "ptr" in i.op_str] == [
        "dword ptr [esp]",
        "dword ptr [esp]",
        "dword ptr [esp]",
    ]


@pytest.mark.parametrize("strength", [-1.0, 0.0, 0.25, 0.5, 1.0, 2.0])
@pytest.mark.parametrize(
    "position", [(0.0, 0.0, 0.0), (3.0, 4.0, 0.0), (0.0, 0.0, 5.0), (12.0, 16.0, 0.0)]
)
@pytest.mark.parametrize("radius", [10.0, 0.0])
def test_x86_dropoff(strength: float, position: tuple[float, float, float], radius: float) -> None:
    unicorn = pytest.importorskip("unicorn")
    regs = pytest.importorskip("unicorn.x86_const")
    uc = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
    uc.mem_map(0x100000, 0x20000)
    uc.mem_map(0x200000, 0x2000)
    uc.mem_map(0x400000, 0xA00000)
    uc.mem_write(share.FLOAT_ONE, struct.pack("<f", 1.0))
    uc.mem_write(share.SHARE_EXPERIENCE_GET_DROPOFF, share.SHARE_EXPERIENCE_GET_DROPOFF_BYTES)
    # Same x87 float-return contract as Coord3D::GetLength, consuming all three coordinates.
    uc.mem_write(
        share.COORD3D_GET_LENGTH, bytes.fromhex("d901d809d94104d84904dec1d94108d84908dec1d9fac3")
    )
    uc.mem_write(0x200000, share._assemble_dropoff(0x200000))
    uc.mem_write(0x201000, bytes.fromhex("d91d00031100"))  # fstp [0x110300]
    behavior, data, source, recipient, stack = 0x100000, 0x101000, 0x102000, 0x103000, 0x110000
    uc.mem_write(behavior + 4, struct.pack("<I", data))
    uc.mem_write(data + 8, struct.pack("<ff", radius, strength))
    uc.mem_write(recipient + share.OBJECT_POSITION, struct.pack("<fff", *position))

    def run(entry: int) -> bytes:
        uc.mem_write(stack, struct.pack("<III", 0x201000, source, recipient))
        preserved = {
            regs.UC_X86_REG_EBP: 0x112000,
            regs.UC_X86_REG_ESI: 0x12345678,
            regs.UC_X86_REG_EDI: 0x87654321,
            regs.UC_X86_REG_EBX: 0x23456789,
        }
        for reg, value in preserved.items():
            uc.reg_write(reg, value)
        uc.reg_write(regs.UC_X86_REG_ESP, stack)
        uc.reg_write(regs.UC_X86_REG_ECX, behavior)
        uc.emu_start(entry, 0x201006, count=500)
        assert uc.reg_read(regs.UC_X86_REG_EIP) == 0x201006
        assert uc.reg_read(regs.UC_X86_REG_ESP) == stack + 12
        assert (uc.reg_read(regs.UC_X86_REG_FPSW) >> 11) & 7 == 0
        for reg, value in preserved.items():
            assert uc.reg_read(reg) == value
        return bytes(uc.mem_read(0x110300, 4))

    got = run(0x200000)
    if radius == 0 or strength in (0, 1):
        assert got == run(share.SHARE_EXPERIENCE_GET_DROPOFF)
    if radius:
        distance = sum(x * x for x in position) ** 0.5
        expected = 1 - min(distance / radius, 1) * min(max(strength, 0), 1)
        assert struct.unpack("<f", got)[0] == pytest.approx(expected)


@pytest.mark.parametrize("percentage", [0.0, 0.5, 1.0, 2.0])
@pytest.mark.parametrize("xp", [0.0, -10.0, 100.0])
@pytest.mark.parametrize("reverse", [False, True])
def test_x86_recipients_do_not_compound(percentage: float, xp: float, reverse: bool) -> None:
    unicorn = pytest.importorskip("unicorn")
    regs = pytest.importorskip("unicorn.x86_const")
    uc = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
    uc.mem_map(0x100000, 0x20000)
    uc.mem_map(0x200000, 0x1000)
    uc.mem_map(0x400000, 0xA00000)
    uc.mem_write(0x200000, share._assemble(0x200000))
    for address, _stock, replacement in share._windows(0x200000):
        uc.mem_write(address, replacement)
    uc.mem_write(share.FLOAT_ONE, struct.pack("<f", 1))
    uc.mem_write(
        share.COORD3D_GET_LENGTH, bytes.fromhex("d901d809d94104d84904dec1d94108d84908dec1d9fac3")
    )
    uc.mem_write(share.EXPERIENCE_TRACKER_ADD_EXPERIENCE_POINTS, b"\xc2\x14\x00")
    frame, stack, data, behavior, recipient, tracker = (
        0x110000,
        0x10F000,
        0x100000,
        0x101000,
        0x102000,
        0x103000,
    )
    uc.mem_write(frame + 8, struct.pack("<f", xp))
    uc.mem_write(frame - 0x18, struct.pack("<II", tracker, behavior + 0x20))
    uc.mem_write(behavior + 4, struct.pack("<I", data))
    uc.mem_write(data + 8, struct.pack("<fff", 10, 0.5, percentage))
    calls: list[float] = []

    def callback(machine: object, address: int, size: int, user_data: object) -> None:
        if address == share.EXPERIENCE_TRACKER_ADD_EXPERIENCE_POINTS:
            sp = uc.reg_read(regs.UC_X86_REG_ESP)
            value, *flags = struct.unpack("<f4I", uc.mem_read(sp + 4, 20))
            assert flags == [1, 1, 1, 0]
            assert uc.reg_read(regs.UC_X86_REG_ECX) == tracker
            calls.append(value)
            for reg in [regs.UC_X86_REG_EAX, regs.UC_X86_REG_ECX, regs.UC_X86_REG_EDX]:
                uc.reg_write(reg, 0xDEADBEEF)

    uc.hook_add(unicorn.UC_HOOK_CODE, callback)
    distances = [0.0, 5.0, 10.0, 20.0, 3.0]
    if reverse:
        distances.reverse()
    for distance in distances:
        uc.mem_write(recipient + share.OBJECT_POSITION, struct.pack("<fff", distance, 0, 0))
        preserved = {
            regs.UC_X86_REG_EBP: frame,
            regs.UC_X86_REG_ESI: recipient,
            regs.UC_X86_REG_EDI: data,
            regs.UC_X86_REG_EBX: 0x12345678,
            regs.UC_X86_REG_ESP: stack,
        }
        for reg, value in preserved.items():
            uc.reg_write(reg, value)
        uc.emu_start(share.SHARE_EXPERIENCE_CALC, share.SHARE_EXPERIENCE_CALC_RESUME, count=500)
        assert uc.reg_read(regs.UC_X86_REG_EIP) == share.SHARE_EXPERIENCE_CALC_RESUME
        assert bytes(uc.mem_read(frame + 8, 4)) == struct.pack("<f", xp)
        assert (uc.reg_read(regs.UC_X86_REG_FPSW) >> 11) & 7 == 0
        for reg, value in preserved.items():
            assert uc.reg_read(reg) == value
    expected = [xp * percentage * (1 - min(d / 10, 1) * 0.5) for d in distances]
    assert calls == pytest.approx([x for x in expected if x > 0])
