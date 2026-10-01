"""Let `EVACUATE` empty a tunnel or garrison of passengers that carry a non-horde contain.

The exit-all loop sends a passenger that has its own contain module out only if that contain is a
horde; one that is anything else - a ring hero's `CitadelSlaughterHordeContain` - is skipped, so
the hero stays inside when the rest leave. A hook on the horde test sends such a passenger down the
`aiExit` arm instead, the one a passenger without a contain already takes.

Derivation: `../docs/evacuate-contained-heroes.md`.
"""

from __future__ import annotations

from ..addresses import (
    CONTAIN_EXIT_ALL_HORDE_TEST,
    CONTAIN_EXIT_ALL_LOOP,
    CONTAIN_EXIT_ALL_LOOP_BYTES,
    CONTAIN_EXIT_ALL_ORDER_EXIT,
    CONTAIN_EXIT_ALL_PASSENGERS,
    CONTAIN_EXIT_ALL_WRAPPER_CALLS,
)
from ..patcher import Patch
from ..utils import (
    allocate_section,
    apply_byte_patch,
    call_rel32,
    file_offset,
    find_section,
    jmp_rel32,
)

__all__ = [
    "EvacuateContainedHeroesPatch",
    "HOOK_WIDTH",
    "SECTION_NAME",
    "STOCK_HOOK",
    "build_code",
]

SECTION_NAME = ".evacht"  # 7 chars: the PE name field is 8 bytes and truncates silently

#: `test eax, eax / je next / push [ebp+0x10]` - replaced by a `jmp` into the cave and two `nop`s.
HOOK_WIDTH = 7
_HOOK = CONTAIN_EXIT_ALL_HORDE_TEST - CONTAIN_EXIT_ALL_LOOP
STOCK_HOOK = CONTAIN_EXIT_ALL_LOOP_BYTES[_HOOK : _HOOK + HOOK_WIDTH]
#: Where the horde arm resumes once the cave has done its `push`: `mov edx, [eax]`.
_HORDE_RESUME = CONTAIN_EXIT_ALL_HORDE_TEST + HOOK_WIDTH

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000


def build_code(cave_va: int) -> bytes:
    """The horde test, with the no-horde case sent to the `aiExit` arm rather than past it.

    `eax` is the horde interface (or null) and `esi` the list node, whose `+8` is the passenger.
    The horde arm is the stock one, `push` included; the other reloads the passenger into `eax`,
    which is what the `aiExit` arm expects there - it is also where a passenger without a contain
    arrives, with the same register."""
    code = bytearray()
    code += b"\x85\xc0"  # test eax, eax
    code += b"\x74\x08"  # je   .no_horde
    code += b"\xff\x75\x10"  # push dword [ebp+0x10]   the instruction the hook displaced
    code += jmp_rel32(cave_va + len(code), _HORDE_RESUME)
    # .no_horde
    code += b"\x8b\x46\x08"  # mov eax, [esi+8]         the passenger
    code += jmp_rel32(cave_va + len(code), CONTAIN_EXIT_ALL_ORDER_EXIT)
    return bytes(code)


class EvacuateContainedHeroesPatch(Patch):
    name = "evacuate-contained-heroes"
    author = "officialNecro"
    description = (
        "Make EVACUATE (the exit-all button) on a TunnelContain or garrison also send out a "
        "passenger that carries a non-horde contain module of its own - every ring-bearing hero, "
        "whose ring pickup is a CitadelSlaughterHordeContain - instead of leaving it inside. It "
        "leaves by the same aiExit a plain unit gets. Logic-side: every peer needs the same "
        "binary. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        self._check_sites(data)
        cave_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        apply_byte_patch(
            data,
            file_offset(data, CONTAIN_EXIT_ALL_HORDE_TEST),
            STOCK_HOOK,
            jmp_rel32(CONTAIN_EXIT_ALL_HORDE_TEST, cave_va, HOOK_WIDTH),
            "exit-all horde test -> non-horde passengers take aiExit",
        )

    @staticmethod
    def _check_sites(data: bytes | bytearray) -> None:
        """Raise unless the whole loop body is stock, not just the hooked bytes - the cave jumps
        into it at two places and relies on `esi` and `[ebp+0x10]` meaning what the loop makes
        them mean - and unless both wrappers still call the loop."""
        off = file_offset(data, CONTAIN_EXIT_ALL_LOOP)
        got = bytes(data[off : off + len(CONTAIN_EXIT_ALL_LOOP_BYTES)])
        if got != CONTAIN_EXIT_ALL_LOOP_BYTES:
            raise ValueError(
                f"@0x{CONTAIN_EXIT_ALL_LOOP:08x}: expected the stock exit-all loop "
                f"{CONTAIN_EXIT_ALL_LOOP_BYTES.hex()}, got {got.hex()} - the file is not the "
                "expected build, or already carries this patch"
            )
        for site in CONTAIN_EXIT_ALL_WRAPPER_CALLS:
            want = call_rel32(site, CONTAIN_EXIT_ALL_PASSENGERS)
            off = file_offset(data, site)
            got = bytes(data[off : off + len(want)])
            if got != want:
                raise ValueError(
                    f"@0x{site:08x}: expected a call to the exit-all loop ({want.hex()}), got "
                    f"{got.hex()} - not the expected build"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        cave_va, cave_off, vsize = located
        problems: list[str] = []
        code = build_code(cave_va)
        if vsize < len(code) or bytes(data[cave_off : cave_off + len(code)]) != code:
            problems.append(f"the routine in {SECTION_NAME} is not the one this patch builds")
        want = jmp_rel32(CONTAIN_EXIT_ALL_HORDE_TEST, cave_va, HOOK_WIDTH)
        off = file_offset(data, CONTAIN_EXIT_ALL_HORDE_TEST)
        got = bytes(data[off : off + HOOK_WIDTH])
        if got != want:
            problems.append(
                f"@0x{CONTAIN_EXIT_ALL_HORDE_TEST:08x}: the horde test does not jump to "
                f"{SECTION_NAME} (holds {got.hex()})"
            )
        return problems
