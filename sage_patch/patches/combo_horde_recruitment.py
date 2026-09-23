"""Let a horde with several `InitialPayload` lines be recruited, arriving as the mix it declares.

A map-placed horde fills itself from its whole payload list, but a produced one is filled by the
building from a production entry that carries one template, so a combo horde comes out empty. A cave
at the producer check in `HordeContain::onObjectCreated` lets a multi-payload horde fill itself.
Single-payload hordes are unaffected. Logic-side: every peer needs the same binary.

Derivation: `../docs/combo-horde-recruitment.md`.
"""

from __future__ import annotations

from ..addresses import (
    HORDE_CONTAIN_CREATE_PAYLOAD_CALL,
    HORDE_CONTAIN_CREATE_PAYLOAD_CALL_BYTES,
    HORDE_CONTAIN_FULL_STRENGTH_INIT,
    HORDE_CONTAIN_FULL_STRENGTH_INIT_BYTES,
    HORDE_CONTAIN_ON_OBJECT_CREATED,
    HORDE_CONTAIN_ON_OBJECT_CREATED_ENTRY,
    HORDE_CONTAIN_PAYLOAD_NAME,
    HORDE_CONTAIN_PAYLOAD_NAME_ENTRY,
    HORDE_CONTAIN_PAYLOAD_NAME_SINGLETON_TEST,
    HORDE_CONTAIN_PAYLOAD_NAME_SINGLETON_TEST_BYTES,
    HORDE_CONTAIN_PRODUCED_GATE,
    HORDE_CONTAIN_PRODUCED_GATE_BYTES,
    HORDE_CONTAIN_PRODUCED_GATE_TEST,
    HORDE_CONTAIN_PRODUCED_GATE_TEST_BYTES,
    MODULE_MODULE_DATA,
    MODULE_OWNING_OBJECT,
    OBJECT_PRODUCER_ID,
    PRODUCTION_HORDE_PAYLOAD_CALL,
    PRODUCTION_HORDE_PAYLOAD_CALL_BYTES,
    TRANSPORT_CONTAIN_CREATE_PAYLOAD,
    TRANSPORT_CONTAIN_CREATE_PAYLOAD_ENTRY,
    TRANSPORT_CONTAIN_INITIAL_PAYLOAD,
)
from ..asm import JE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, call_rel32, find_section, u32, va_to_offset

__all__ = [
    "ANCHORS",
    "SECTION_NAME",
    "ComboHordeRecruitmentPatch",
    "build_section",
]

SECTION_NAME = ".cmbhrd"
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ - the cave holds one stub.
SECTION_CHARACTERISTICS = 0x60000060

#: The first bytes at each address that has to still mean what this patch assumes, as a
#: `{va: bytes}` map. Nothing here is written; all of it is asserted before the single edit, so
#: a build whose layout moved fails loudly rather than turning six unknown bytes into a call.
#:
#: The prologue pins the function; the test pins that the value the cave returns is still what
#: decides whether the body runs; the `createPayload` call and its callee pin that falling through
#: really does reach the multi-payload fill; the getter and its `cmp esi,1` pin the defect this
#: is a fix for, and its one call site pins that recruitment is the only thing that reads it; and
#: the strength-percent initialiser pins that the trim a combo horde now runs is a no-op.
ANCHORS = {
    HORDE_CONTAIN_ON_OBJECT_CREATED: HORDE_CONTAIN_ON_OBJECT_CREATED_ENTRY,
    HORDE_CONTAIN_PRODUCED_GATE_TEST: HORDE_CONTAIN_PRODUCED_GATE_TEST_BYTES,
    HORDE_CONTAIN_CREATE_PAYLOAD_CALL: HORDE_CONTAIN_CREATE_PAYLOAD_CALL_BYTES,
    TRANSPORT_CONTAIN_CREATE_PAYLOAD: TRANSPORT_CONTAIN_CREATE_PAYLOAD_ENTRY,
    HORDE_CONTAIN_PAYLOAD_NAME: HORDE_CONTAIN_PAYLOAD_NAME_ENTRY,
    HORDE_CONTAIN_PAYLOAD_NAME_SINGLETON_TEST: HORDE_CONTAIN_PAYLOAD_NAME_SINGLETON_TEST_BYTES,
    PRODUCTION_HORDE_PAYLOAD_CALL: PRODUCTION_HORDE_PAYLOAD_CALL_BYTES,
    HORDE_CONTAIN_FULL_STRENGTH_INIT: HORDE_CONTAIN_FULL_STRENGTH_INIT_BYTES,
}


def build_section(base_va: int) -> bytes:
    """Return the cave's bytes for a section based at `base_va`.

    One stub, entered at `base_va`. It reproduces the two instructions it replaced and then,
    only for a horde that has a producer *and* declares two or more payloads, reports `0` so
    the caller's `jne` falls through into `createPayload`.

    The list at `ModuleData+0xA4` is an MSVC `std::list` head: one pointer to a sentinel node
    whose `next` is the first element and is the sentinel itself when the list is empty. So
    "two or more entries" is "the first element's `next` is not the sentinel either", which is
    two dereferences and needs no counting loop."""
    a = Asm(base_va)
    a.emit(b"\x8b\x46", MODULE_OWNING_OBJECT)  # mov eax, [esi+8]        ; the Object
    a.emit(b"\x8b\x40", OBJECT_PRODUCER_ID)  # mov eax, [eax+0x78]     ; m_producerID
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JE, "done")  # je .done                ; no producer -> stock (eax == 0)

    a.emit(b"\x8b\x4e", MODULE_MODULE_DATA)  # mov ecx, [esi+4]        ; the ModuleData
    a.emit(b"\x8b\x89", u32(TRANSPORT_CONTAIN_INITIAL_PAYLOAD))  # mov ecx, [ecx+0xa4]
    a.emit(b"\x8b\x11")  # mov edx, [ecx]          ; the first node
    a.emit(b"\x3b\xd1")  # cmp edx, ecx
    a.jcc_short(JE, "done")  # je .done                ; no payload at all -> stock skip
    a.emit(b"\x8b\x12")  # mov edx, [edx]          ; the second node
    a.emit(b"\x3b\xd1")  # cmp edx, ecx
    a.jcc_short(JE, "done")  # je .done                ; exactly one -> stock skip
    a.emit(b"\x33\xc0")  # xor eax, eax            ; two or more -> fill myself

    a.label("done")
    a.emit(0xC3)  # ret
    return a.finish()


class ComboHordeRecruitmentPatch(Patch):
    """Let a horde with several `InitialPayload` lines be recruited as the mix it declares."""

    name = "combo-horde-recruitment"
    author = "officialNecro"
    description = (
        "A horde declaring two or more InitialPayload lines can be recruited and arrives as the "
        "mix it declares, instead of being produced empty. No INI change; single-payload hordes "
        "keep the stock building-driven fill"
    )

    def apply(self, data: bytearray) -> None:
        off = va_to_offset(data, HORDE_CONTAIN_PRODUCED_GATE)
        if off is None:
            raise ValueError(
                f"{HORDE_CONTAIN_PRODUCED_GATE:#010x} is not mapped - not the expected build"
            )
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_section, SECTION_CHARACTERISTICS)
        apply_byte_patch(
            data,
            off,
            HORDE_CONTAIN_PRODUCED_GATE_BYTES,
            self._hook_bytes(section_va),
            "HordeContain::onObjectCreated producer gate -> combo-horde cave",
        )

    @staticmethod
    def _hook_bytes(section_va: int) -> bytes:
        """The six bytes that replace the producer read: a `call` and one pad byte.

        The pad is a `nop` rather than a second instruction, so the replacement is exactly as
        long as what it replaces and the `test`/`jne` that follows keeps its address - which
        is what lets the branch be left stock and asserted rather than rewritten."""
        return call_rel32(HORDE_CONTAIN_PRODUCED_GATE, section_va) + b"\x90"

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the horde "
                    "creation and recruitment paths are not this build's, so the six bytes at "
                    "the producer gate are not the read this patch means to replace"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that `data` carries this patch (an empty list == verified). Finds
        the cave by name, recomputes what it should hold from its own base VA, and compares it and
        the hook to what is on disk."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located

        problems: list[str] = []
        content = build_section(section_va)
        got = bytes(data[section_off : section_off + len(content)])
        if got != content:
            problems.append(f"{SECTION_NAME} does not hold this patch's stub")

        off = va_to_offset(data, HORDE_CONTAIN_PRODUCED_GATE)
        if off is None:
            return [*problems, f"{HORDE_CONTAIN_PRODUCED_GATE:#010x} is not mapped by any section"]
        expected = self._hook_bytes(section_va)
        got = bytes(data[off : off + len(expected)])
        if got == HORDE_CONTAIN_PRODUCED_GATE_BYTES:
            problems.append(
                f"{HORDE_CONTAIN_PRODUCED_GATE:#010x} still holds the stock producer read"
            )
        elif got != expected:
            problems.append(
                f"the producer gate @{HORDE_CONTAIN_PRODUCED_GATE:#010x}: expected "
                f"{expected.hex()}, got {got.hex()}"
            )
        return problems
