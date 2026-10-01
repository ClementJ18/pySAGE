"""Stop a `ReplaceSelfUpgrade` destroying the rubble its replacement lands on.

The replacement is made by `BuildAssistant::buildObjectNow`, which first clears the site: every
object under the new footprint that `isRemovableForConstruction` accepts is destroyed, and that
predicate accepts anything effectively dead. A citadel at zero health is exactly that - rubble kept
by `KeepObjectDie` until it is rebuilt - so upgrading a wall or tower that overlaps it deletes the
citadel. One `call` in the clearing loop is repointed at a cave that answers "not removable" for an
effectively-dead object, but only when the call chain is `ReplaceSelfUpgrade` -> `buildObjectNow`
-> the clearing loop. `SHRUBBERY` and `CLEARED_BY_BUILD` are still cleared, and every other builder
is untouched.

Derivation: `../docs/replace-self-rubble.md`.
"""

from __future__ import annotations

from ..addresses import (
    BUILD_OBJECT_NOW,
    BUILD_OBJECT_NOW_PROLOGUE,
    BUILD_OBJECT_NOW_VTABLE_ENTRY,
    CLEAR_REMOVABLES,
    CLEAR_REMOVABLES_CALL,
    CLEAR_REMOVABLES_CALL_BYTES,
    CLEAR_REMOVABLES_LOOP,
    CLEAR_REMOVABLES_LOOP_BYTES,
    CLEAR_REMOVABLES_PREDICATE_CALL,
    CLEAR_REMOVABLES_PROLOGUE,
    CLEAR_REMOVABLES_RETURN,
    EH_PROLOG,
    EH_PROLOG_BYTES,
    IS_REMOVABLE_FOR_CONSTRUCTION,
    IS_REMOVABLE_FOR_CONSTRUCTION_BYTES,
    OBJECT_EFFECTIVELY_DEAD_FLAG,
    REPLACE_SELF_BUILD_CALL,
    REPLACE_SELF_BUILD_CALL_BYTES,
    REPLACE_SELF_BUILD_RETURN,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import (
    allocate_section,
    apply_byte_patch,
    call_rel32,
    file_offset,
    find_section,
)

__all__ = [
    "ANCHORS",
    "SECTION_NAME",
    "ReplaceSelfRubblePatch",
    "build_code",
]

SECTION_NAME = ".rsrubl"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

#: `Object::m_template`, and the two `KindOf` bits the stock predicate clears regardless of
#: death: `SHRUBBERY` (6, bit `0x40` of byte `+0`) and `CLEARED_BY_BUILD` (51, bit `0x08` of byte
#: `+6`), both in the mask at `template+0x108`.
_OBJECT_TEMPLATE = 0x04
_SHRUBBERY_BYTE, _SHRUBBERY_BIT = 0x108, 0x40
_CLEARED_BY_BUILD_BYTE, _CLEARED_BY_BUILD_BIT = 0x10E, 0x08

#: Byte windows the cave depends on and does not rewrite, as `{va: expected bytes}`. The loop
#: window carries the hooked `call`, which `verify` blanks before comparing.
ANCHORS: dict[int, bytes] = {
    # the clearing loop, whose `edx` the cave must leave alone
    CLEAR_REMOVABLES_LOOP: CLEAR_REMOVABLES_LOOP_BYTES,
    # the predicate the cave falls through to, and whose rules it narrows
    IS_REMOVABLE_FOR_CONSTRUCTION: IS_REMOVABLE_FOR_CONSTRUCTION_BYTES,
    # both frames the cave walks open with `__EH_prolog`, which is what puts the return address
    # at `[ebp+4]` and the caller's frame at `[ebp]`
    EH_PROLOG: EH_PROLOG_BYTES,
    CLEAR_REMOVABLES: CLEAR_REMOVABLES_PROLOGUE,
    BUILD_OBJECT_NOW: BUILD_OBJECT_NOW_PROLOGUE,
    # the two return addresses the cave compares against, each pinned by the `call` before it
    CLEAR_REMOVABLES_CALL: CLEAR_REMOVABLES_CALL_BYTES,
    REPLACE_SELF_BUILD_CALL: REPLACE_SELF_BUILD_CALL_BYTES,
    # and that `call [ebx+0x38]` there is `buildObjectNow`
    BUILD_OBJECT_NOW_VTABLE_ENTRY: BUILD_OBJECT_NOW.to_bytes(4, "little"),
}

_HOOK_OFFSET = CLEAR_REMOVABLES_PREDICATE_CALL - CLEAR_REMOVABLES_LOOP


def build_code(cave_va: int) -> bytes:
    """`isRemovableForConstruction`, answering false for rubble under a `ReplaceSelfUpgrade`.

    Entered by the repointed `call`, so `[esp+4]` is the object and `ebp` is the clearing loop's
    frame. `[ebp+4]` says who called the loop and `[[ebp]+4]` who called `buildObjectNow`; both
    are read only after the first matches, so the second read is always inside a
    `buildObjectNow` frame. Clobbers `eax` and `ecx` as the stock predicate does, and never `edx`,
    which the loop reads straight after."""
    a = Asm(cave_va)
    a.emit(b"\x81\x7d\x04", CLEAR_REMOVABLES_RETURN.to_bytes(4, "little"))  # cmp [ebp+4], ret
    a.jcc(JNE, "stock")  # the loop was not reached through buildObjectNow
    a.emit(b"\x8b\x45\x00")  # mov eax, [ebp]           ; buildObjectNow's frame
    a.emit(b"\x81\x78\x04", REPLACE_SELF_BUILD_RETURN.to_bytes(4, "little"))  # cmp [eax+4], ret
    a.jcc(JNE, "stock")  # buildObjectNow was not called by ReplaceSelfUpgrade
    a.emit(b"\x8b\x44\x24\x04")  # mov eax, [esp+4]      ; the object
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "stock")
    # test byte [eax+0x458], 1                   ; effectively dead?
    a.emit(b"\xf6\x80", OBJECT_EFFECTIVELY_DEAD_FLAG.to_bytes(4, "little"), 0x01)
    a.jcc(JE, "stock")  # alive: the stock rules
    a.emit(b"\x8b\x48", _OBJECT_TEMPLATE)  # mov ecx, [eax+4]
    a.emit(b"\xf6\x81", _SHRUBBERY_BYTE.to_bytes(4, "little"), _SHRUBBERY_BIT)
    a.jcc(JNE, "stock")  # a dead tree is still cleared
    a.emit(b"\xf6\x81", _CLEARED_BY_BUILD_BYTE.to_bytes(4, "little"), _CLEARED_BY_BUILD_BIT)
    a.jcc(JNE, "stock")
    a.emit(b"\x32\xc0")  # xor al, al                  ; rubble stays
    a.emit(b"\xc2\x04\x00")  # ret 4
    a.label("stock")
    a.jmp_absolute(IS_REMOVABLE_FOR_CONSTRUCTION)
    return a.finish()


class ReplaceSelfRubblePatch(Patch):
    name = "replace-self-rubble"
    author = "officialNecro"
    description = (
        "Stop a ReplaceSelfUpgrade destroying the rubble its replacement is placed on - a "
        "destroyed citadel waiting to be rebuilt disappeared when a wall or tower overlapping it "
        "was upgraded. Dead objects under the replacement are left alone; trees, bushes and "
        "CLEARED_BY_BUILD props are still cleared, and ordinary construction is unchanged. "
        "Logic-side: every peer needs the same binary. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        self._check_sites(data)
        cave_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        apply_byte_patch(
            data,
            file_offset(data, CLEAR_REMOVABLES_PREDICATE_CALL),
            call_rel32(CLEAR_REMOVABLES_PREDICATE_CALL, IS_REMOVABLE_FOR_CONSTRUCTION),
            call_rel32(CLEAR_REMOVABLES_PREDICATE_CALL, cave_va),
            "clear-removables predicate -> keep rubble under a ReplaceSelfUpgrade",
        )

    @staticmethod
    def _problems(data: bytes | bytearray, hooked: bool) -> list[str]:
        """Every anchor that does not hold its stock bytes. With `hooked`, the predicate `call`
        inside the loop window is left out of the comparison."""
        problems: list[str] = []
        for va, want in ANCHORS.items():
            off = file_offset(data, va)
            got = bytes(data[off : off + len(want)])
            if hooked and va == CLEAR_REMOVABLES_LOOP:
                end = _HOOK_OFFSET + 5
                got, want = got[:_HOOK_OFFSET] + got[end:], want[:_HOOK_OFFSET] + want[end:]
            if got != want:
                problems.append(f"@0x{va:08x}: expected {want.hex()}, got {got.hex()}")
        return problems

    @classmethod
    def _check_sites(cls, data: bytes | bytearray) -> None:
        problems = cls._problems(data, hooked=False)
        if problems:
            raise ValueError(
                "; ".join(problems) + " - the file is not the expected build, or already carries "
                "this patch"
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        cave_va, cave_off, vsize = located
        problems = self._problems(data, hooked=True)
        code = build_code(cave_va)
        if vsize < len(code) or bytes(data[cave_off : cave_off + len(code)]) != code:
            problems.append(f"the routine in {SECTION_NAME} is not the one this patch builds")
        want = call_rel32(CLEAR_REMOVABLES_PREDICATE_CALL, cave_va)
        off = file_offset(data, CLEAR_REMOVABLES_PREDICATE_CALL)
        got = bytes(data[off : off + len(want)])
        if got != want:
            problems.append(
                f"@0x{CLEAR_REMOVABLES_PREDICATE_CALL:08x}: the predicate call does not reach "
                f"{SECTION_NAME} (holds {got.hex()})"
            )
        return problems
