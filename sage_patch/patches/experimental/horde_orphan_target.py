"""Make stranded battalion members attackable again. **It does not work** and is deliberately not
registered.

A battalion sometimes fails to finish leaving its building: the container survives empty and its
units stand free, belonging to nothing, and nothing can target them. The patch gates the attack
redirect it believed was refusing the order, but tested against a save with the fault it changed
nothing: the order is never refused inside `aiAttackObject`. Kept because the reverse engineering
(the discriminator in particular) is sound.

Derivation: `../../docs/horde-formation-orphans.md`, section 6c.
"""

from __future__ import annotations

import struct

from ...addresses import OBJECT_PRODUCER_ID, OBJECT_TEST_STATUS, THE_GAME_LOGIC
from ...asm import JE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "FALLBACK_BYTES",
    "FALLBACK_VA",
    "FIND_OBJECT_BY_ID_VA",
    "HELPER_FALLBACK_BYTES",
    "HELPER_FALLBACK_VA",
    "HELPER_NONE_VA",
    "HELPER_RETURN_VA",
    "HELPER_VA",
    "KINDOF_MASK_DISP",
    "RESOLVE_ENTRY_VA",
    "SECTION_NAME",
    "STATUS_IS_LEAVING_FACTORY",
    "TARGET_CONTAINER_VA",
    "TARGET_VICTIM_VA",
    "TEST_STATUS_PROLOGUE",
    "HordeOrphanTargetPatch",
    "build_gate",
    "build_helper_gate",
]

#: `resolveAttackTarget(eax = victim, arg1 = attacker, arg2 = Bool *outIsHordeTarget)`. Called
#: only from `AIUpdateInterface::aiAttackObject` (vtable `+0x88`) and its force-attack sibling
#: (`+0x98`), both of which treat a NULL result as "cannot attack".
RESOLVE_ENTRY_VA = 0x00668167

#: The ancestry fallback: reached from the two `je`s below when `m_containedBy` is null or is
#: not a horde. Nothing else branches here and no imm32 in the image points into its interior,
#: so the whole block relocates.
FALLBACK_VA = 0x006681D0
FALLBACK_BYTES = bytes.fromhex(
    "ff7678"  # push dword [esi+0x78]        ; the producer id
    "8b0d2c41de00"  # mov  ecx, [0x00DE412C]        ; TheGameLogic
    "e8a314deff"  # call 0x00449681               ; GameLogic::findObjectByID
    "3bc3"  # cmp  eax, ebx                 ; found nothing?
    "74b7"  # je   0x00668199               ; -> target the victim itself
    "8b4804"  # mov  ecx, [eax+4]             ; its ThingTemplate
    "85b914010000"  # test [ecx+0x114], edi         ; KINDOF HORDE?
    "74ac"  # je   0x00668199               ; -> target the victim itself
    "eba8"  # jmp  0x00668197               ; -> target the container
)

#: Where the block's two exits land. `TARGET_VICTIM_VA` is the shared tail that writes the
#: out-flag and returns whatever is in `esi`; `TARGET_CONTAINER_VA` is the `mov esi, eax`
#: one instruction above it.
TARGET_CONTAINER_VA = 0x00668197
TARGET_VICTIM_VA = 0x00668199

FIND_OBJECT_BY_ID_VA = 0x00449681

#: `Object::getHorde(Bool useProducer)` -> the horde this object belongs to, or NULL:
#: itself if it is one, else `m_containedBy` if that is one, else - and this is the part that
#: strands units - whatever its producer id names, if *that* is one.
#:
#: **This is the shared helper, with 114 direct callers**, and it is why patching the inlined
#: copy in `resolveAttackTarget` alone changed nothing observable: a clicked attack resolves its
#: target through here long before the AI's own copy runs. Measured live - a hero ordered onto a
#: stranded goblin never entered an attack state at all (goal id 0), while the same order onto a
#: healthy goblin of the same template, team and distance killed it.
HELPER_VA = 0x00693A1A
#: The producer fallback inside it: the `useProducer` test and the lookup it guards. Reached only
#: by fall-through and one `je`, with no imm32 pointing into its interior, so it relocates whole.
HELPER_FALLBACK_VA = 0x00693A44
HELPER_FALLBACK_BYTES = bytes.fromhex(
    "807c240800"  # cmp  byte [esp+8], 0          ; the useProducer argument
    "741d"  # je   0x00693A68               ; -> no horde
    "ff7178"  # push dword [ecx+0x78]         ; the producer id
    "8b0d2c41de00"  # mov  ecx, [0x00DE412C]
    "e8285cdbff"  # call 0x00449681
    "85c0"  # test eax, eax
    "740b"  # je   0x00693A68
    "8b4804"  # mov  ecx, [eax+4]
    "85b114010000"  # test [ecx+0x114], esi        ; KINDOF HORDE?
    "7502"  # jne  0x00693A6A               ; -> that is the horde
)
#: Its two exits: `xor eax,eax` (no horde) and the shared `pop esi; ret 4`.
HELPER_NONE_VA = 0x00693A68
HELPER_RETURN_VA = 0x00693A6A

#: The two `je 0x6681D0` that enter the block. Not rewritten - asserted, because a build whose
#: branch A is shaped differently would send control somewhere this cave cannot stand in for.
ENTRY_BRANCHES = ((0x0066818A, b"\x74\x44"), (0x00668195, b"\x74\x39"))

#: `Object::testStatus(bit)` - `__thiscall`, one stack argument, `ret 4`. It clobbers only
#: `eax`/`ecx`/`edx` and preserves `ebx`/`esi`/`edi`, which is exactly what the
#: relocated block still needs (the victim, zero, and the `KINDOF HORDE` mask), so the gate needs
#: to save nothing around the call. The prologue is asserted because the cave calls it.
TEST_STATUS_VA = OBJECT_TEST_STATUS
TEST_STATUS_PROLOGUE = bytes.fromhex("8b54240433c0568bf1408bca83e11f")

#: `OBJECT_STATUS_IS_LEAVING_FACTORY`, bit 90 of `Object::m_status`.
STATUS_IS_LEAVING_FACTORY = 0x5A

#: The displacement of the `KindOf` dword holding `HORDE`, as the relocated `test` encodes it.
KINDOF_MASK_DISP = 0x114

SECTION_NAME = ".hordefx"
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ - the cave holds one code stub.
SECTION_CHARACTERISTICS = 0x60000060

#: What the detour leaves behind: five bytes of `jmp rel32` and `int3` to the block's end, so
#: a stray entry faults rather than running half an instruction.
_DETOUR_FILL = 0xCC


def build_gate(base_va: int, status_bit: int = STATUS_IS_LEAVING_FACTORY) -> bytes:
    """The relocated fallback, with the status test in front of it.

    On entry `esi` is the victim, `ebx` is zero and `edi` holds the `KINDOF HORDE` mask -
    the three registers branch A is carrying when it reaches the fallback. The gate returns to
    the function through the same two exits the original block used, so nothing downstream can
    tell the difference except in the case it is here to change.
    """
    a = Asm(base_va)
    a.emit(0x6A, status_bit)  # push <bit>
    a.emit(b"\x8b\xce")  # mov  ecx, esi          ; the victim
    a.call_absolute(TEST_STATUS_VA)  # call Object::testStatus ; -> al
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "victim")  # je   .victim           ; stranded: it is its own target

    # From here down, the stock block verbatim - only its three branches are retargeted.
    a.emit(b"\xff\x76", OBJECT_PRODUCER_ID)  # push dword [esi+0x78]
    a.emit(b"\x8b\x0d", struct.pack("<I", THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.call_absolute(FIND_OBJECT_BY_ID_VA)  # call findObjectByID
    a.emit(b"\x3b\xc3")  # cmp  eax, ebx
    a.jcc(JE, "victim")  # je   .victim
    a.emit(b"\x8b\x48\x04")  # mov  ecx, [eax+4]
    a.emit(b"\x85\xb9", struct.pack("<I", KINDOF_MASK_DISP))  # test [ecx+0x114], edi
    a.jcc(JE, "victim")  # je   .victim
    a.jmp_absolute(TARGET_CONTAINER_VA)  # jmp  <target the container>

    a.label("victim")
    a.jmp_absolute(TARGET_VICTIM_VA)  # jmp  <target the victim>
    return a.finish()


def detour_bytes(from_va: int, to_va: int, width: int) -> bytes:
    """`jmp rel32` to the cave, then `int3` out to `width`."""
    jump = b"\xe9" + struct.pack("<i", to_va - (from_va + 5))
    return jump + bytes([_DETOUR_FILL]) * (width - len(jump))


def build_helper_gate(base_va: int, status_bit: int = STATUS_IS_LEAVING_FACTORY) -> bytes:
    """`Object::getHorde`'s producer fallback, behind the same status test.

    On entry `ecx` is the object, `esi` holds the `KINDOF HORDE` mask, and `[esp+8]` is the
    caller's `useProducer` flag - the frame the relocated block reads. The gate is reached by a
    `jmp`, so that frame is untouched and the flag stays where the block expects it.

    `this` has to be saved across the call: `Object::testStatus` takes it in `ecx` and leaves
    it clobbered, and the relocated block still needs it for `[ecx+0x78]`. It does preserve
    `esi`, so the mask needs no saving.
    """
    a = Asm(base_va)
    a.emit(0x51)  # push ecx               ; save `this`
    a.emit(0x6A, status_bit)  # push <bit>
    a.call_absolute(TEST_STATUS_VA)  # call Object::testStatus ; ret 4, ecx = this
    a.emit(0x59)  # pop  ecx               ; restore `this`
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "none")  # je   .none            ; stranded: it has no horde

    # From here down, the stock block verbatim - only its branches are retargeted.
    a.emit(b"\x80\x7c\x24\x08\x00")  # cmp  byte [esp+8], 0   ; useProducer?
    a.jcc(JE, "none")
    a.emit(b"\xff\x71", OBJECT_PRODUCER_ID)  # push dword [ecx+0x78]
    a.emit(b"\x8b\x0d", struct.pack("<I", THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.call_absolute(FIND_OBJECT_BY_ID_VA)  # call findObjectByID
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "none")
    a.emit(b"\x8b\x48\x04")  # mov  ecx, [eax+4]
    a.emit(b"\x85\xb1", struct.pack("<I", KINDOF_MASK_DISP))  # test [ecx+0x114], esi
    a.jcc(JE, "none")
    a.jmp_absolute(HELPER_RETURN_VA)  # jmp  <return eax>

    a.label("none")
    a.jmp_absolute(HELPER_NONE_VA)  # jmp  <return NULL>
    return a.finish()


class HordeOrphanTargetPatch(Patch):
    """Let a stranded battalion member be attacked as itself instead of through its dead horde."""

    name = "horde-orphan-target"
    author = "officialNecro"
    experimental = True
    description = "Make units stranded by a broken battalion attackable again. No INI change"

    def apply(self, data: bytearray) -> None:
        self._check_sites(data)
        section_va = allocate_section(
            data,
            SECTION_NAME,
            self._cave,
            SECTION_CHARACTERISTICS,
        )
        for site, stock, cave_va, note in self._edits(section_va):
            off = va_to_offset(data, site)
            if off is None:
                raise ValueError(f"0x{site:08x} is not mapped: not this build")
            apply_byte_patch(data, off, stock, detour_bytes(site, cave_va, len(stock)), note)

    def _cave(self, base_va: int) -> bytes:
        gate = build_gate(base_va)
        return gate + build_helper_gate(base_va + len(gate))

    def _edits(self, section_va: int) -> list[tuple[int, bytes, int, str]]:
        """`(site, stock bytes, where its gate lives, note)` for both relocated blocks."""
        helper_va = section_va + len(build_gate(section_va))
        return [
            (
                FALLBACK_VA,
                FALLBACK_BYTES,
                section_va,
                "the AI resolver's inlined ancestry fallback -> its status-gated cave",
            ),
            (
                HELPER_FALLBACK_VA,
                HELPER_FALLBACK_BYTES,
                helper_va,
                "Object::getHorde's producer fallback -> its status-gated cave",
            ),
        ]

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that `data` carries this patch (an empty list == verified).

        Locates the cave, recomputes the gate its base VA implies, and compares that and the
        detour to what is on disk. Reads only via `struct` + the section table, so verification
        needs no disassembler.
        """
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located

        problems: list[str] = []
        expected = self._cave(section_va)
        got = bytes(data[section_off : section_off + len(expected)])
        if got != expected:
            problems.append(f"{SECTION_NAME} does not hold the expected gates")

        for site, stock, cave_va, _note in self._edits(section_va):
            off = va_to_offset(data, site)
            if off is None:
                problems.append(f"0x{site:08x} is not mapped")
                continue
            want = detour_bytes(site, cave_va, len(stock))
            got = bytes(data[off : off + len(want)])
            if got != want:
                problems.append(
                    f"the fallback at 0x{site:08x} does not jump to the cave: "
                    f"expected {want.hex()}, got {got.hex()}"
                )

        problems.extend(self._site_problems(data))
        return problems

    # Build fingerprint

    def _check_sites(self, data: bytes | bytearray) -> None:
        problems = self._site_problems(data)
        if problems:
            raise ValueError("; ".join(problems))

    def _site_problems(self, data: bytes | bytearray) -> list[str]:
        """The two things this patch reads but never writes: the branches that enter the block,
        and the prologue of the function the cave calls. Both must be this build's."""
        problems: list[str] = []
        for va, expected in ENTRY_BRANCHES:
            off = va_to_offset(data, va)
            if off is None or bytes(data[off : off + len(expected)]) != expected:
                problems.append(
                    f"0x{va:08x} is not the expected `je` into the fallback "
                    f"({expected.hex()}): branch A is shaped differently in this build"
                )
        off = va_to_offset(data, TEST_STATUS_VA)
        if (
            off is None
            or bytes(data[off : off + len(TEST_STATUS_PROLOGUE)]) != TEST_STATUS_PROLOGUE
        ):
            problems.append(
                f"0x{TEST_STATUS_VA:08x} is not Object::testStatus: the cave would call "
                f"something else with a status bit"
            )
        return problems
