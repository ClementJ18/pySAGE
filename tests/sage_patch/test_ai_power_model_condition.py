"""Tests for the AI power model-condition patch.

Three layers, as for the other AI gates: the cave is disassembled back and asserted to say what it
was meant to say; the apply/verify round-trip runs against a synthetic image carrying the real
stock bytes at every anchor; and the gate is then *executed* under Unicorn against the engine's own
model-condition test and its two bitset helpers, with the button's and the object's masks planted.
"""

from __future__ import annotations

import faulthandler
import struct

import pytest

from sage_patch.addresses import (
    AI_POWER_NOT_CAST,
    AI_POWER_READY_WINDOW,
    AI_POWER_READY_WINDOW_BYTES,
    AI_POWER_TICK,
    AI_POWER_TICK_RESUME,
    AI_POWER_UPDATE_CTOR_VTABLE_WRITE_BYTES,
    AI_POWER_UPDATE_TICK_VTABLE,
    COMMAND_BUTTON_CONDITION_DISABLED,
    COMMAND_BUTTON_CONDITION_GATE,
    COMMAND_BUTTON_CONDITION_GATE_BODY,
)
from sage_patch.patches.experimental.ai_power_model_condition import (
    ANCHORS,
    HOOK_ORIGINAL,
    HOOK_VA,
    SECTION_NAME,
    AiPowerModelConditionPatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, va_to_offset

BASE = 0x00F00000
IMAGE_BASE = 0x400000

#: The two bitset helpers the model-condition test calls: `ModelConditionFlags::any()` and
#: `testAny(other)`, both over 19 dwords. Only needed by the emulator; the anchor pins the calls to
#: them through the gate's body.
ANY_VA = 0x004B3783
ANY_BODY = bytes.fromhex("33c0833c810075094083f81372f432c0c3b001c3")
TEST_ANY_VA = 0x006632E9
TEST_ANY_BODY = bytes.fromhex(
    "8b44240433d22bc1568b34088531750f4283c10483fa1372f032c05ec20400b001ebf8"
)


def synthetic_image() -> bytearray:
    """A PE32 image big enough to map the hook site and every anchor, with the real original
    bytes planted, so the whole apply + verify path runs without the copyrighted `game.dat`."""
    highest = max(HOOK_VA, *ANCHORS) - IMAGE_BASE + 0x100
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

    data[HOOK_VA - IMAGE_BASE : HOOK_VA - IMAGE_BASE + len(HOOK_ORIGINAL)] = HOOK_ORIGINAL
    for va, expected in ANCHORS.items():
        data[va - IMAGE_BASE : va - IMAGE_BASE + len(expected)] = expected
    return data


def disassemble(base: int = BASE):
    capstone = pytest.importorskip("capstone")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(build_code(base), base))


class TestTheChain:
    """The hooked function is identified by a chain the anchors check against the image."""

    def test_the_constructor_stamps_the_vtable_the_tick_is_taken_from(self):
        stamped = struct.unpack_from("<I", AI_POWER_UPDATE_CTOR_VTABLE_WRITE_BYTES, 3)[0]
        assert stamped == AI_POWER_UPDATE_TICK_VTABLE
        assert ANCHORS[AI_POWER_UPDATE_TICK_VTABLE] == struct.pack("<I", AI_POWER_TICK)

    def test_the_hook_sits_inside_the_ready_window(self):
        """The window is the stock run the hook overwrites part of; its bytes at the hook must be
        the displaced instructions, and the two anchored halves must rebuild it exactly."""
        at = HOOK_VA - AI_POWER_READY_WINDOW
        assert AI_POWER_READY_WINDOW_BYTES[at : at + len(HOOK_ORIGINAL)] == HOOK_ORIGINAL
        rebuilt = ANCHORS[AI_POWER_READY_WINDOW] + HOOK_ORIGINAL + ANCHORS[AI_POWER_TICK_RESUME]
        assert rebuilt == AI_POWER_READY_WINDOW_BYTES
        assert AI_POWER_TICK_RESUME == HOOK_VA + len(HOOK_ORIGINAL)

    def test_the_window_ends_in_the_call_to_the_cast_step(self):
        """The window's last instruction is `call 0x00993055`, the coin flip, picker and cast the
        gate sits in front of. Its rel32 is the target, so the anchor pins it."""
        call_va = AI_POWER_READY_WINDOW + len(AI_POWER_READY_WINDOW_BYTES) - 5
        assert AI_POWER_READY_WINDOW_BYTES[-5] == 0xE8
        rel = struct.unpack("<i", AI_POWER_READY_WINDOW_BYTES[-4:])[0]
        assert call_va + 5 + rel == 0x00993055

    def test_the_hook_is_inside_the_tick(self):
        assert AI_POWER_TICK < AI_POWER_READY_WINDOW < HOOK_VA < AI_POWER_NOT_CAST


class TestTheCave:
    def test_it_disassembles_cleanly_to_its_end(self):
        """Capstone stopping early means an invalid encoding, which would be a crash in-game."""
        insns = disassemble()
        assert sum(i.size for i in insns) == len(build_code(BASE))

    def test_it_asks_about_the_hooks_own_button_and_object(self):
        """stdcall pushes right to left: the object (`[esi-8]`) first, then the button read off
        the type behaviour (`[esi+0x14]`, then `+0xC`)."""
        text = [f"{i.mnemonic} {i.op_str}" for i in disassemble()]
        assert text[:4] == [
            "push dword ptr [esi - 8]",
            "mov eax, dword ptr [esi + 0x14]",
            "push dword ptr [eax + 0xc]",
            f"call {COMMAND_BUTTON_CONDITION_GATE:#x}",
        ]

    def test_disabled_leaves_by_the_not_cast_exit(self):
        insns = disassemble()
        cmp = next(i for i in insns if i.mnemonic == "cmp")
        assert cmp.op_str == f"eax, {COMMAND_BUTTON_CONDITION_DISABLED}"
        taken = next(i for i in insns if i.mnemonic == "je")
        target = next(i for i in insns if i.address == int(taken.op_str, 16))
        assert (target.mnemonic, int(target.op_str, 16)) == ("jmp", AI_POWER_NOT_CAST)

    def test_it_re_runs_the_instructions_it_displaced_before_resuming(self):
        insns = disassemble()
        resume = next(
            i for i in insns if i.mnemonic == "jmp" and int(i.op_str, 16) == AI_POWER_TICK_RESUME
        )
        displaced = b"".join(
            bytes(i.bytes)
            for i in insns
            if i.address > insns[4].address and i.address < resume.address and i.mnemonic == "mov"
        )
        assert displaced == HOOK_ORIGINAL

    def test_its_only_exits_are_the_resume_and_the_not_cast_edge(self):
        exits = {int(i.op_str, 16) for i in disassemble() if i.mnemonic == "jmp"}
        assert exits == {AI_POWER_TICK_RESUME, AI_POWER_NOT_CAST}

    def test_its_only_call_is_the_engines_model_condition_test(self):
        calls = {int(i.op_str, 16) for i in disassemble() if i.mnemonic == "call"}
        assert calls == {COMMAND_BUTTON_CONDITION_GATE}

    def test_it_writes_no_register_the_tick_needs(self):
        """`esi` is the module interface, `edi` its module data, `ebx` zero for the tick's
        compares. The cave may only write `eax` and `ecx`, both of which the displaced
        instructions set again."""
        written = set()
        for ins in disassemble():
            written |= {ins.reg_name(r) for r in ins.regs_access()[1]}
        assert not written & {"esi", "edi", "ebx", "ebp"}

    def test_it_relocates_with_its_section(self):
        a, b = build_code(BASE), build_code(BASE + 0x1000)
        assert a != b
        assert len(a) == len(b)


class TestApply:
    def test_apply_then_verify(self):
        data = synthetic_image()
        AiPowerModelConditionPatch().apply(data)
        assert AiPowerModelConditionPatch().verify(data) == []

    def test_the_hook_is_a_jmp_to_the_cave_then_a_nop(self):
        data = synthetic_image()
        AiPowerModelConditionPatch().apply(data)
        section_va, _off, _vsize = find_section(data, SECTION_NAME)
        off = va_to_offset(data, HOOK_VA)
        site = bytes(data[off : off + len(HOOK_ORIGINAL)])
        assert site[0] == 0xE9
        assert HOOK_VA + 5 + struct.unpack_from("<i", site, 1)[0] == section_va
        assert site[5] == 0x90

    def test_the_section_name_survives_the_eight_byte_pe_field(self):
        assert len(SECTION_NAME) <= 8
        data = synthetic_image()
        AiPowerModelConditionPatch().apply(data)
        assert find_section(data, SECTION_NAME) is not None

    def test_refuses_to_apply_twice(self):
        data = synthetic_image()
        AiPowerModelConditionPatch().apply(data)
        with pytest.raises(ValueError, match="expected"):
            AiPowerModelConditionPatch().apply(data)

    @pytest.mark.parametrize("va", sorted(ANCHORS), ids=lambda va: f"{va:#010x}")
    def test_a_moved_anchor_refuses_to_apply(self, va):
        data = synthetic_image()
        off = va - IMAGE_BASE
        data[off : off + len(ANCHORS[va])] = b"\xcc" * len(ANCHORS[va])
        with pytest.raises(ValueError, match="not this build's"):
            AiPowerModelConditionPatch().apply(data)

    def test_verify_reports_an_unpatched_image(self):
        assert AiPowerModelConditionPatch().verify(synthetic_image()) == [
            f"{SECTION_NAME} section is absent"
        ]

    def test_registered_as_experimental(self):
        """It has not been seen in a match yet, so it lives in `patches/experimental/`."""
        assert PATCHES["ai-power-model-condition"] is AiPowerModelConditionPatch
        assert AiPowerModelConditionPatch.experimental


unicorn = pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

_CAVE = 0x00ED3000
_HEAP = 0x20000000
_STACK = 0x30000000
_PAGE = 0x1000
_OBJECT = _HEAP + 0x1000
_BUTTON = _HEAP + 0x2000
_BEHAVIOUR = _HEAP + 0x3000
_MODULE = _HEAP + 0x4000  # the module; the tick's `esi` is its interface at +0x10
_MODULE_DATA = _HEAP + 0x5000  # the tick's `edi`

_OBJECT_CONDITIONS = 0x10C
_ENABLE = 0x194
_DISABLE = 0x1E0
_MASK_DWORDS = 19

#: What the tick holds in the registers the cave must hand back unchanged.
_LIVE = {
    UC_X86_REG_ESI: _MODULE + 0x10,
    UC_X86_REG_EDI: _MODULE_DATA,
    UC_X86_REG_EBX: 0,
    UC_X86_REG_EBP: 0xB0B0B0B0,
}

#: `INVISIBLE_CAMOUFLAGE`'s place in the mask does not matter to the test; any bit does, and
#: bits past the first dword prove the helpers walk the whole 19-dword mask.
CAMOUFLAGE = 200
OTHER = 7


def _mask(bits: tuple[int, ...]) -> bytes:
    words = [0] * _MASK_DWORDS
    for bit in bits:
        words[bit >> 5] |= 1 << (bit & 31)
    return struct.pack(f"<{_MASK_DWORDS}I", *words)


def _run(
    *,
    object_bits: tuple[int, ...],
    enable: tuple[int, ...] = (),
    disable: tuple[int, ...] = (),
) -> tuple[int, dict[int, int], int, int, int]:
    """Run the cave once. Returns where it left for, the live registers, `eax`, `cl` and how far
    `esp` moved."""
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    code = build_code(_CAVE)

    pages = {_HEAP, _OBJECT, _BUTTON, _BEHAVIOUR, _MODULE, _MODULE_DATA, _STACK, _STACK + _PAGE}
    pages |= {(_CAVE + off) & ~0xFFF for off in range(0, len(code) + _PAGE, _PAGE)}
    pages |= {COMMAND_BUTTON_CONDITION_GATE & ~0xFFF, ANY_VA & ~0xFFF, TEST_ANY_VA & ~0xFFF}
    pages |= {AI_POWER_TICK_RESUME & ~0xFFF, AI_POWER_NOT_CAST & ~0xFFF}
    # `mem_map` raises and catches an SEH access violation inside Unicorn on Windows; every map
    # still succeeds, but the fault handler would print a stack for each one.
    was_enabled = faulthandler.is_enabled()
    faulthandler.disable()
    try:
        for page in sorted(pages):
            uc.mem_map(page, _PAGE)
    finally:
        if was_enabled:
            faulthandler.enable()

    uc.mem_write(_CAVE, code)
    uc.mem_write(COMMAND_BUTTON_CONDITION_GATE, COMMAND_BUTTON_CONDITION_GATE_BODY)
    uc.mem_write(ANY_VA, ANY_BODY)
    uc.mem_write(TEST_ANY_VA, TEST_ANY_BODY)

    uc.mem_write(_OBJECT + _OBJECT_CONDITIONS, _mask(object_bits))
    uc.mem_write(_BUTTON + _ENABLE, _mask(enable))
    uc.mem_write(_BUTTON + _DISABLE, _mask(disable))
    uc.mem_write(_BEHAVIOUR + 0xC, struct.pack("<I", _BUTTON))
    uc.mem_write(_MODULE + 0x08, struct.pack("<I", _OBJECT))
    uc.mem_write(_MODULE + 0x24, struct.pack("<I", _BEHAVIOUR))
    uc.mem_write(_MODULE_DATA + 0x18, b"\x01\xa5")

    sp = _STACK + _PAGE - 0x100
    uc.reg_write(UC_X86_REG_ESP, sp)
    uc.reg_write(UC_X86_REG_EAX, 0xDEADBEEF)
    uc.reg_write(UC_X86_REG_ECX, 0xDEADBEEF)
    for reg, value in _LIVE.items():
        uc.reg_write(reg, value)

    landed: list[int] = []

    def watch(u, address, size, _user):  # noqa: ANN001
        if address in (AI_POWER_TICK_RESUME, AI_POWER_NOT_CAST):
            landed.append(address)
            u.emu_stop()

    uc.hook_add(UC_HOOK_CODE, watch)
    uc.emu_start(_CAVE, 0, count=400)
    assert landed, "the cave reached neither exit"
    live = {reg: uc.reg_read(reg) for reg in _LIVE}
    return (
        landed[0],
        live,
        uc.reg_read(UC_X86_REG_EAX),
        uc.reg_read(UC_X86_REG_ECX) & 0xFF,
        uc.reg_read(UC_X86_REG_ESP) - sp,
    )


class TestTheGateRuns:
    """The cave executed against the engine's own model-condition test."""

    def test_an_ungated_button_casts(self):
        where, *_ = _run(object_bits=())
        assert where == AI_POWER_TICK_RESUME

    def test_an_enable_condition_the_object_has_casts(self):
        where, *_ = _run(object_bits=(CAMOUFLAGE,), enable=(CAMOUFLAGE,))
        assert where == AI_POWER_TICK_RESUME

    def test_an_enable_condition_the_object_lacks_does_not(self):
        """The Wood-elf Ambush case: `EnableOnModelCondition = INVISIBLE_CAMOUFLAGE` on a unit
        that is not camouflaged."""
        where, *_ = _run(object_bits=(OTHER,), enable=(CAMOUFLAGE,))
        assert where == AI_POWER_NOT_CAST

    def test_a_disable_condition_the_object_has_does_not(self):
        where, *_ = _run(object_bits=(OTHER,), disable=(OTHER,))
        assert where == AI_POWER_NOT_CAST

    def test_disable_wins_over_enable(self):
        where, *_ = _run(object_bits=(CAMOUFLAGE, OTHER), enable=(CAMOUFLAGE,), disable=(OTHER,))
        assert where == AI_POWER_NOT_CAST

    def test_any_one_enable_condition_is_enough(self):
        where, *_ = _run(object_bits=(OTHER,), enable=(CAMOUFLAGE, OTHER))
        assert where == AI_POWER_TICK_RESUME

    def test_the_cast_path_arrives_with_the_displaced_loads_done(self):
        """At the resume the tick pushes `ecx` (with `cl` = `[edi+0x19]`) and then `eax` (the
        object) as the cast step's arguments."""
        _where, _live, eax, cl, _moved = _run(object_bits=())
        assert eax == _OBJECT
        assert cl == 0xA5

    @pytest.mark.parametrize(
        "kwargs",
        [{"object_bits": ()}, {"object_bits": (), "enable": (CAMOUFLAGE,)}],
        ids=["cast", "not-cast"],
    )
    def test_registers_and_stack_come_back_untouched(self, kwargs):
        _where, live, _eax, _cl, moved = _run(**kwargs)
        assert live == _LIVE
        assert moved == 0, "the gate is stdcall and must clean both arguments"
