"""Play the existing PalantirMovie on direct powers without updates and PlayerUpgrade powers.

The no-update fallback is limited to UpdateModuleStartsAttack=No. Existing update-driven movie
requests, all audio and gameplay triggers retain their native paths. No new INI fields or state.
Derivation: ../docs/special-power-palantir-movie.md and
../docs/special-power-presentation-research.md.
"""

from __future__ import annotations

from ...addresses import (
    GET_FINAL_OVERRIDE,
    SPECIAL_POWER_PALANTIR_ANCHORS,
    SPECIAL_POWER_PALANTIR_CLIENT,
    SPECIAL_POWER_PALANTIR_GLOBAL,
    SPECIAL_POWER_PALANTIR_INTENT_DONE,
    SPECIAL_POWER_PALANTIR_INTENT_FOUND,
    SPECIAL_POWER_PALANTIR_INTENT_GATE,
    SPECIAL_POWER_PALANTIR_PLAYER_UPGRADE_CALL,
    SPECIAL_POWER_PALANTIR_WINDOWS,
    SPECIAL_POWER_TRIGGER,
)
from ...asm import JE, JNE, Asm
from ...patcher import Patch
from ...utils import (
    allocate_section,
    apply_byte_patch,
    call_rel32,
    file_offset,
    find_section,
    jmp_rel32,
    u32,
)

__all__ = ["SECTION_NAME", "SpecialPowerPalantirMoviePatch", "build_code"]

SECTION_NAME = ".spmovie"


def _assemble(base_va: int) -> Asm:
    a = Asm(base_va)
    a.label("intent")
    a.jcc(JNE, "found")  # preserve the displaced JE's flags from cmp [ebp-0x10],0
    a.emit(b"\x8b\x46\x04\x80\x78\x0c\x00")
    a.jcc(JNE, "done")  # no update with StartsAttack=Yes: do not invent an ability start
    a.emit(b"\x8b\xce")  # module base in esi
    a.call("request")
    a.label("done")
    a.jmp_absolute(SPECIAL_POWER_PALANTIR_INTENT_DONE)
    a.label("found")
    a.jmp_absolute(SPECIAL_POWER_PALANTIR_INTENT_FOUND)

    a.label("player_upgrade")
    a.call("request")
    # Tail call: retain the original return address, ECX and pending NULL argument exactly.
    a.jmp_absolute(SPECIAL_POWER_TRIGGER)

    # Borrow &finalTemplate->PalantirMovie only during the synchronous native request. The
    # client copies the string (0x92B7FE), so there is no extra owned AsciiString to unwind/free.
    # Preserve complete machine state around the additional presentation work, including SIMD.
    a.label("request")
    a.emit(b"\x9c\x60\x8b\xdc\x81\xec\x10\x02\x00\x00\x83\xe4\xf0")
    a.emit(b"\x0f\xae\x04\x24\x8b\xf4")  # fxsave [esp]; mov esi,esp
    a.emit(b"\x8b\x49\x04\x85\xc9")  # ModuleData
    a.jcc(JE, "request_done")
    a.emit(b"\x8b\x49\x08\x85\xc9")  # template
    a.jcc(JE, "request_done")
    a.call_absolute(GET_FINAL_OVERRIDE)
    a.emit(b"\x85\xc0")
    a.jcc(JE, "request_done")
    a.emit(b"\x8b\x50\x5c\x85\xd2")
    a.jcc(JE, "request_done")
    a.emit(b"\x66\x83\x7a\x04\x00")  # same nonempty test as the stock movie path
    a.jcc(JE, "request_done")
    a.emit(b"\x8b\x0d", u32(SPECIAL_POWER_PALANTIR_GLOBAL), b"\x85\xc9")
    a.jcc(JE, "request_done")
    a.emit(b"\x6a\x00\x83\xc0\x5c\x50")
    a.call_absolute(SPECIAL_POWER_PALANTIR_CLIENT)
    a.label("request_done")
    a.emit(b"\x0f\xae\x0e\x8b\xe3\x61\x9d\xc3")
    return a


def build_code(base_va: int) -> bytes:
    return _assemble(base_va).finish()


def _windows(base_va: int) -> dict[int, bytes]:
    a = _assemble(base_va)
    return {
        SPECIAL_POWER_PALANTIR_INTENT_GATE: jmp_rel32(
            SPECIAL_POWER_PALANTIR_INTENT_GATE, a.label_va("intent"), 6
        ),
        SPECIAL_POWER_PALANTIR_PLAYER_UPGRADE_CALL: call_rel32(
            SPECIAL_POWER_PALANTIR_PLAYER_UPGRADE_CALL, a.label_va("player_upgrade")
        ),
    }


class SpecialPowerPalantirMoviePatch(Patch):
    name = "special-power-palantir-movie"
    author = "Ostkannit"
    description = (
        "Play PalantirMovie on direct SpecialPowers without matching updates and on "
        "PlayerUpgradeSpecialPower; preserve existing movie timing, audio and gameplay. "
        "No INI changes"
    )

    def apply(self, data: bytearray) -> None:
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError(f"the file already carries a {SECTION_NAME} section")
        for va, old in {**SPECIAL_POWER_PALANTIR_ANCHORS, **SPECIAL_POWER_PALANTIR_WINDOWS}.items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(old)])
            if got != old:
                raise ValueError(f"unexpected build at {va:#010x}: {got.hex()} != {old.hex()}")
        out = bytearray(data)
        base = allocate_section(out, SECTION_NAME, build_code, 0x60000020)
        for va, new in _windows(base).items():
            apply_byte_patch(out, file_offset(out, va), SPECIAL_POWER_PALANTIR_WINDOWS[va], new)
        data[:] = out

    def verify(self, data: bytes | bytearray) -> list[str]:
        section = find_section(data, SECTION_NAME)
        if section is None:
            return [f"no {SECTION_NAME} section"]
        base, off, size = section
        problems = []
        if size != len(build_code(base)) or bytes(data[off : off + size]) != build_code(base):
            problems.append(f"unexpected {SECTION_NAME} helper body")
        for va, expected in {**SPECIAL_POWER_PALANTIR_ANCHORS, **_windows(base)}.items():
            try:
                at = file_offset(data, va)
                if bytes(data[at : at + len(expected)]) != expected:
                    problems.append(f"unexpected bytes at {va:#010x}")
            except ValueError as exc:
                problems.append(str(exc))
        return problems
