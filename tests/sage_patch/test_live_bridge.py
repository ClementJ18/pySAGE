"""Tests for the live-bridge patch.

The cave is hand-assembled x86 that cannot be executed here, so the important test
disassembles it back and asserts it says what it was meant to say. A wrong byte in a hook
does not raise - it crashes the game - so encoding errors have to be caught statically.
"""

from __future__ import annotations

import struct

import pytest

from sage_patch.addresses import (
    THE_TACTICAL_VIEW,
    VIEW_GET_LOCATION_VTABLE_SLOT,
    VIEW_LOCATION_SIZE,
    VIEW_SET_LOCATION_VTABLE_SLOT,
)
from sage_patch.patches.live_bridge import (
    ARG_APPENDERS,
    ARG_STRIDE,
    ARGS_OFF,
    BUFFER_TAG,
    BY_POINTER,
    CAMERA_OFF,
    CODE_OFF,
    GAME_LOGIC_UPDATE_VTABLE_SLOT,
    HOOK_ORIGINAL,
    HOOK_RETURN_VA,
    HOOK_VA,
    LOCATION_OFF,
    MAX_ARGS,
    SECTION_NAME,
    TABLE_OFF,
    TAG_OFF,
    THE_MESSAGE_STREAM,
    LiveBridgePatch,
    build_section,
)
from sage_patch.utils import find_section

BASE = 0x00F00000

IMAGE_BASE = 0x400000


def synthetic_image() -> bytearray:
    """A PE32 image big enough to map the hook site and the GameLogic vtable slot, with the
    real original bytes planted, so the whole apply + verify path runs without the
    copyrighted `game.dat`."""
    highest = max(HOOK_VA, GAME_LOGIC_UPDATE_VTABLE_SLOT) - IMAGE_BASE + 0x100
    data = bytearray(((highest + 0x400) // 0x200 + 1) * 0x200)

    data[0:2] = b"MZ"
    e = 0x80
    struct.pack_into("<I", data, 0x3C, e)
    data[e : e + 4] = b"PE\x00\x00"
    struct.pack_into("<H", data, e + 4, 0x14C)  # Machine (i386)
    struct.pack_into("<H", data, e + 6, 1)  # NumberOfSections
    struct.pack_into("<H", data, e + 20, 0xE0)  # SizeOfOptionalHeader
    opt = e + 24
    struct.pack_into("<H", data, opt, 0x10B)  # PE32 magic
    struct.pack_into("<I", data, opt + 28, IMAGE_BASE)
    struct.pack_into("<I", data, opt + 32, 0x1000)  # SectionAlignment
    struct.pack_into("<I", data, opt + 36, 0x200)  # FileAlignment
    struct.pack_into("<I", data, opt + 56, 0x2000000)  # SizeOfImage
    struct.pack_into("<I", data, opt + 60, 0x400)  # SizeOfHeaders, room for a 2nd header
    header = bytearray(40)
    header[0:8] = b".text\x00\x00\x00"
    size = len(data) - 0x1000
    struct.pack_into("<IIII", header, 8, size, 0x1000, size, 0x1000)
    data[opt + 0xE0 : opt + 0xE0 + 40] = header

    data[HOOK_VA - IMAGE_BASE : HOOK_VA - IMAGE_BASE + 5] = HOOK_ORIGINAL
    struct.pack_into("<I", data, GAME_LOGIC_UPDATE_VTABLE_SLOT - IMAGE_BASE, HOOK_VA)
    return data


def code_bytes(base: int = BASE) -> bytes:
    return build_section(base)[CODE_OFF:]


def disassemble(base: int = BASE):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(code_bytes(base), base + CODE_OFF))


def test_section_layout_is_buffer_then_table_then_code():
    section = build_section(BASE)
    assert len(section) > CODE_OFF
    table = struct.unpack_from(f"<{len(ARG_APPENDERS)}I", section, TABLE_OFF)
    assert table == ARG_APPENDERS
    # the command buffer starts zeroed, so a freshly patched game has no pending order
    assert section[:ARGS_OFF] == b"\x00" * ARGS_OFF


def test_the_buffer_carries_its_layout_tag():
    """The writer computes its offsets from this module; the cave it addresses was built by
    whichever version patched the binary. The tag is how those two are told apart."""
    section = build_section(BASE)
    assert struct.unpack_from("<I", section, TAG_OFF)[0] == BUFFER_TAG


def test_the_camera_block_starts_idle_and_fits_a_view_location():
    section = build_section(BASE)
    assert struct.unpack_from("<I", section, CAMERA_OFF)[0] == 0
    assert LOCATION_OFF + VIEW_LOCATION_SIZE == CODE_OFF
    assert section[LOCATION_OFF:CODE_OFF] == b"\x00" * VIEW_LOCATION_SIZE


def test_the_camera_block_calls_both_view_accessors_through_the_vtable():
    """One call each way, and both on the view rather than on anything else the cave holds."""
    calls = [i for i in disassemble() if i.mnemonic == "call"]
    setters = [i for i in calls if hex(VIEW_SET_LOCATION_VTABLE_SLOT) in i.op_str]
    getters = [i for i in calls if hex(VIEW_GET_LOCATION_VTABLE_SLOT) in i.op_str]
    assert len(setters) == len(getters) == 1
    assert setters[0].op_str == f"dword ptr [edx + {VIEW_SET_LOCATION_VTABLE_SLOT:#x}]"
    assert getters[0].op_str == f"dword ptr [edx + {VIEW_GET_LOCATION_VTABLE_SLOT:#x}]"


def test_the_camera_block_reads_the_tactical_view_global():
    ops = [i.op_str for i in disassemble()]
    assert any(f"[0x{THE_TACTICAL_VIEW:x}]" in op for op in ops)


def test_a_camera_command_pushes_the_location_and_never_adjusts_the_stack():
    """`setLocation` and `getLocation` are thiscall and clean their own argument. An
    `add esp, 4` after either would unbalance the stack under the hook's pushad."""
    insns = disassemble()
    location = BASE + LOCATION_OFF
    pushes = [i for i in insns if i.mnemonic == "push" and i.op_str == hex(location)]
    assert len(pushes) == 2, "one push of the location per direction"
    assert not [i for i in insns if i.mnemonic == "add" and i.op_str == "esp, 4"]


def test_argument_area_holds_max_args():
    assert TABLE_OFF - ARGS_OFF == MAX_ARGS * ARG_STRIDE


def test_every_by_pointer_tag_is_a_real_appender_index():
    assert all(0 <= tag < len(ARG_APPENDERS) for tag in BY_POINTER)


def test_the_code_disassembles_cleanly_to_its_end():
    """Capstone stopping early means an invalid encoding, which would be a crash in-game."""
    insns = disassemble()
    consumed = sum(i.size for i in insns)
    assert consumed == len(code_bytes()), "the cave contains bytes that do not decode"


def test_flags_and_registers_are_saved_and_restored():
    # capstone spells the 0x60/0x61 pair `pushal`/`popal`; the encoding is what matters
    insns = disassemble()
    opcodes = [ins.bytes[0] for ins in insns]
    assert opcodes[0] == 0x9C, "pushfd first"
    assert opcodes[1] == 0x60, "pushad second"
    assert opcodes.count(0x9C) == opcodes.count(0x9D) == 1, "pushfd/popfd must pair"
    assert opcodes.count(0x60) == opcodes.count(0x61) == 1, "pushad/popad must pair"
    # popad must come before popfd, mirroring the push order
    assert opcodes.index(0x61) < opcodes.index(0x9D)


def test_it_calls_append_message_through_the_vtable_slot():
    calls = [i for i in disassemble() if i.mnemonic == "call" and "0x48" in i.op_str]
    assert len(calls) == 1
    assert calls[0].op_str == "dword ptr [eax + 0x48]"


def test_it_reads_the_message_stream_global():
    ops = [i.op_str for i in disassemble()]
    assert any(f"[0x{THE_MESSAGE_STREAM:x}]" in op for op in ops)


def test_arguments_dispatch_through_the_appender_table():
    table_va = BASE + TABLE_OFF
    calls = [i for i in disassemble() if i.mnemonic == "call" and "eax*4" in i.op_str]
    assert len(calls) == 1, "argument appending should go through one indexed call"
    assert f"0x{table_va:x}" in calls[0].op_str


def test_it_ends_by_replaying_the_displaced_instruction_then_returning():
    insns = disassemble()
    tail = insns[-2:]
    assert tail[0].mnemonic == "mov" and tail[0].op_str == "eax, 0xb841da"
    assert bytes(tail[0].bytes) == HOOK_ORIGINAL
    assert tail[1].mnemonic == "jmp"
    assert int(tail[1].op_str, 16) == HOOK_RETURN_VA


def test_every_branch_stays_inside_the_cave():
    """A displacement computed wrong would jump into arbitrary engine code."""
    insns = disassemble()
    lo, hi = BASE + CODE_OFF, BASE + CODE_OFF + len(code_bytes())
    for ins in insns:
        if not ins.mnemonic.startswith("j"):
            continue
        target = int(ins.op_str, 16)
        if target == HOOK_RETURN_VA:
            continue  # the one deliberate exit
        assert lo <= target < hi, f"{ins.mnemonic} at {ins.address:#x} leaves the cave"


def test_the_buffer_addresses_are_all_inside_the_section():
    """Every absolute data reference must point at our own buffer, not at engine memory."""
    insns = disassemble()
    section_lo, section_hi = BASE, BASE + CODE_OFF
    seen = set()
    for ins in insns:
        for token in ins.op_str.replace(",", " ").split():
            if not token.startswith("[0x") or not token.endswith("]"):
                continue
            value = int(token[1:-1], 16)
            seen.add(value)
    engine_globals = {THE_MESSAGE_STREAM, THE_TACTICAL_VIEW}
    for value in seen - engine_globals:
        assert section_lo <= value < section_hi, f"{value:#010x} is outside the command buffer"
    assert seen & engine_globals == engine_globals


def test_relocating_the_cave_moves_every_reference():
    """The section VA is chosen at apply time, so nothing may be baked in."""
    a, b = code_bytes(0x00F00000), code_bytes(0x01A00000)
    assert a != b, "the code must depend on its own base address"
    assert len(a) == len(b), "moving the cave must not change its size"


def test_verify_rejects_an_unpatched_image():
    patch = LiveBridgePatch()
    problems = patch.verify(bytearray(0x1000))
    assert problems and SECTION_NAME in problems[0]


def test_hook_site_bytes_are_the_documented_instruction():
    # `mov eax, 0xB841DA` - exactly the five bytes a jmp rel32 needs
    assert len(HOOK_ORIGINAL) == 5
    assert HOOK_ORIGINAL[0] == 0xB8
    assert HOOK_RETURN_VA == HOOK_VA + 5


def test_apply_refuses_a_site_the_vtable_does_not_dispatch_to():
    """GameLogic::update is virtual, so it has no call xrefs and the entry cannot be found by
    following calls. Hooking a function nothing dispatches to installs perfectly and simply
    never fires - indistinguishable from success until an injected order is ignored."""
    image = synthetic_image()
    struct.pack_into("<I", image, GAME_LOGIC_UPDATE_VTABLE_SLOT - IMAGE_BASE, 0x00401000)
    with pytest.raises(ValueError, match="would never fire"):
        LiveBridgePatch().apply(image)


def test_apply_then_verify_round_trips():
    image = synthetic_image()
    patch = LiveBridgePatch()
    patch.apply(image)
    assert patch.verify(image) == []


def test_verify_reports_a_cave_built_to_another_layout():
    """A patched-but-stale binary is the one case the import-the-offsets rule cannot cover."""
    image = synthetic_image()
    patch = LiveBridgePatch()
    patch.apply(image)
    located = find_section(image, SECTION_NAME)
    assert located is not None
    struct.pack_into("<I", image, located[1] + TAG_OFF, BUFFER_TAG - 1)
    assert any("re-applied" in problem for problem in patch.verify(image))


def test_apply_refuses_an_image_whose_hook_site_is_not_the_expected_bytes():
    image = synthetic_image()
    image[HOOK_VA - IMAGE_BASE] = 0x90
    with pytest.raises(ValueError):
        LiveBridgePatch().apply(image)
