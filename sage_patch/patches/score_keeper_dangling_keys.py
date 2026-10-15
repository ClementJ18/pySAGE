"""Skip `ThingTemplate` count-map entries that fail, instead of crashing or refusing the save.

A War of the Ring player's `LivingWorldScoreKeeper` counts what the player built, lost and
destroyed across the whole campaign, keyed by `ThingTemplate *`, and every battle's score is merged
into it by pointer. A template that exists only in a battle map's `map.ini` is deleted when that
map ends (`ThingFactory::reset` -> `Overridable::deleteOverrides`), but its pointer stays in the
campaign keeper. The next save reads the key's name through it - an access violation that
`GameState::saveGame` swallows, leaving the file half-written - or writes garbage that no load can
resolve.

Every `std::map<const ThingTemplate *, Int>` the engine saves goes through one function,
`xferObjectCountMap`, and the campaign keeper's are filled by one merge. Four hooks make each of
them drop an entry that fails rather than fail with it:

- **merge**: a battle key whose resolution comes back NULL is not merged.
- **save, count**: the count written is the number of keys that are live templates - found in the
  `ThingFactory`'s template list or one of its templates' override chains, compared by pointer so
  a dead key is never dereferenced.
- **save, entries**: a key that is not a live template is not written.
- **load**: a name that is not a template is read and dropped instead of throwing, so a save that
  already carries one (an empty name, a `map.ini` object from an earlier battle) loads.

Live entries are untouched on every path.
Derivation: `../docs/living-campaign/wotr-save-failure.md`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    LIVING_WORLD_SCORE_KEEPER_MERGE_NEXT,
    LIVING_WORLD_SCORE_KEEPER_MERGE_NEXT_BYTES,
    LIVING_WORLD_SCORE_KEEPER_MERGE_STORE,
    LIVING_WORLD_SCORE_KEEPER_MERGE_STORE_BYTES,
    LIVING_WORLD_SCORE_KEEPER_MERGE_STORE_RESUME,
    LIVING_WORLD_SCORE_KEEPER_MERGE_STORE_RESUME_BYTES,
    OVERRIDABLE_NEXT_OVERRIDE,
    STD_MAP_ITERATOR_INCREMENT,
    THE_THING_FACTORY,
    THING_FACTORY_TEMPLATE_LIST,
    THING_TEMPLATE_NEXT,
    XFER_OBJECT_COUNT_MAP_COUNT,
    XFER_OBJECT_COUNT_MAP_COUNT_BYTES,
    XFER_OBJECT_COUNT_MAP_COUNT_RESUME,
    XFER_OBJECT_COUNT_MAP_COUNT_RESUME_BYTES,
    XFER_OBJECT_COUNT_MAP_DONE,
    XFER_OBJECT_COUNT_MAP_DONE_BYTES,
    XFER_OBJECT_COUNT_MAP_KEY_NAME,
    XFER_OBJECT_COUNT_MAP_KEY_NAME_BYTES,
    XFER_OBJECT_COUNT_MAP_KEY_NAME_RESUME,
    XFER_OBJECT_COUNT_MAP_KEY_NAME_RESUME_BYTES,
    XFER_OBJECT_COUNT_MAP_LOAD_COMPARE,
    XFER_OBJECT_COUNT_MAP_LOAD_COMPARE_BYTES,
    XFER_OBJECT_COUNT_MAP_LOAD_INT,
    XFER_OBJECT_COUNT_MAP_LOAD_INT_BYTES,
    XFER_OBJECT_COUNT_MAP_LOAD_NEXT,
    XFER_OBJECT_COUNT_MAP_LOAD_NEXT_BYTES,
    XFER_OBJECT_COUNT_MAP_NEXT,
    XFER_OBJECT_COUNT_MAP_NEXT_BYTES,
    XFER_OBJECT_COUNT_MAP_UNKNOWN_BRANCH,
    XFER_OBJECT_COUNT_MAP_UNKNOWN_BRANCH_BYTES,
    XFER_OBJECT_COUNT_MAP_UNKNOWN_THROW,
    XFER_OBJECT_COUNT_MAP_UNKNOWN_THROW_BYTES,
)
from ..asm import JB, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "HOOKS",
    "SECTION_NAME",
    "ScoreKeeperDanglingKeysPatch",
    "build_code",
    "entry_points",
]

SECTION_NAME = ".skkeys"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

_NOP = 0x90

#: `(hooked VA, the stock bytes there, the cave routine it jumps to)`. Each window is taken whole
#: and padded with `nop`s the cave never returns into.
HOOKS: tuple[tuple[int, bytes, str], ...] = (
    (LIVING_WORLD_SCORE_KEEPER_MERGE_STORE, LIVING_WORLD_SCORE_KEEPER_MERGE_STORE_BYTES, "merge"),
    (XFER_OBJECT_COUNT_MAP_COUNT, XFER_OBJECT_COUNT_MAP_COUNT_BYTES, "count"),
    (XFER_OBJECT_COUNT_MAP_KEY_NAME, XFER_OBJECT_COUNT_MAP_KEY_NAME_BYTES, "key"),
    (XFER_OBJECT_COUNT_MAP_UNKNOWN_THROW, XFER_OBJECT_COUNT_MAP_UNKNOWN_THROW_BYTES, "unknown"),
)

#: The code the caves return into or rely on, checked before anything is written: each resume
#: point, both loops' iterator steps, the load loop's head, compare and `xferInt` setup (which fix
#: `edi`, `[ebp-0x14]` and `[ebp-0x10]` as the cave uses them), the loops' common end, and the one
#: branch that reaches the throw the load hook replaces.
ANCHORS = {
    LIVING_WORLD_SCORE_KEEPER_MERGE_STORE_RESUME: (
        LIVING_WORLD_SCORE_KEEPER_MERGE_STORE_RESUME_BYTES
    ),
    LIVING_WORLD_SCORE_KEEPER_MERGE_NEXT: LIVING_WORLD_SCORE_KEEPER_MERGE_NEXT_BYTES,
    XFER_OBJECT_COUNT_MAP_COUNT_RESUME: XFER_OBJECT_COUNT_MAP_COUNT_RESUME_BYTES,
    XFER_OBJECT_COUNT_MAP_KEY_NAME_RESUME: XFER_OBJECT_COUNT_MAP_KEY_NAME_RESUME_BYTES,
    XFER_OBJECT_COUNT_MAP_NEXT: XFER_OBJECT_COUNT_MAP_NEXT_BYTES,
    XFER_OBJECT_COUNT_MAP_UNKNOWN_BRANCH: XFER_OBJECT_COUNT_MAP_UNKNOWN_BRANCH_BYTES,
    XFER_OBJECT_COUNT_MAP_LOAD_NEXT: XFER_OBJECT_COUNT_MAP_LOAD_NEXT_BYTES,
    XFER_OBJECT_COUNT_MAP_LOAD_INT: XFER_OBJECT_COUNT_MAP_LOAD_INT_BYTES,
    XFER_OBJECT_COUNT_MAP_LOAD_COMPARE: XFER_OBJECT_COUNT_MAP_LOAD_COMPARE_BYTES,
    XFER_OBJECT_COUNT_MAP_DONE: XFER_OBJECT_COUNT_MAP_DONE_BYTES,
}


def _emit(base_va: int) -> Asm:
    a = Asm(base_va)

    # merge: `eax` is the resolved template, NULL when the key was NULL or its name did not
    # resolve. The stock code would insert it; a NULL key is what the save would later read
    # through.
    a.label("merge")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "merge_skip")
    a.emit(LIVING_WORLD_SCORE_KEEPER_MERGE_STORE_BYTES)  # mov ecx, [ebp+8] / mov [ebp-0x14], eax
    a.jmp_absolute(LIVING_WORLD_SCORE_KEEPER_MERGE_STORE_RESUME)
    a.label("merge_skip")
    a.jmp_absolute(LIVING_WORLD_SCORE_KEEPER_MERGE_NEXT)  # the loop's own iterator step

    # count: the number of live keys, in place of `[ebx+4]`. Runs on load too, where the result is
    # overwritten by the count read; it never dereferences a key, so a stale map is harmless.
    # `edi` is saved because the stock code only sets it afterwards; `ecx`/`edx` are dead here.
    a.label("count")
    a.emit(0x57)  # push edi
    a.emit(0x6A, 0x00)  # push 0                 ; the running count, at [esp]
    a.emit(0x8B, 0x03)  # mov eax, [ebx]         ; the header node
    a.emit(0x8B, 0x78, 0x08)  # mov edi, [eax+8] ; begin
    a.label("count_loop")
    a.emit(0x3B, 0x3B)  # cmp edi, [ebx]         ; end is the header
    a.jcc(JE, "count_done")
    a.emit(0x8B, 0x47, 0x10)  # mov eax, [edi+0x10] ; the key
    a.call("is_live")
    a.emit(0x01, 0x04, 0x24)  # add [esp], eax
    a.emit(0x57)  # push edi
    a.call_absolute(STD_MAP_ITERATOR_INCREMENT)  # cdecl, as the stock loop calls it
    a.emit(0x83, 0xC4, 0x04)  # add esp, 4
    a.emit(0x8B, 0xF8)  # mov edi, eax
    a.jmp("count_loop")
    a.label("count_done")
    a.emit(0x58)  # pop eax                       ; the count
    a.emit(0x5F)  # pop edi
    a.emit(0x8D, 0x4D, 0xEC)  # lea ecx, [ebp-0x14] ; the displaced second instruction
    a.jmp_absolute(XFER_OBJECT_COUNT_MAP_COUNT_RESUME)

    # key: the save loop's head. A dead key goes straight to the iterator step, so neither its
    # name nor its count is written - matching what `count` left out.
    a.label("key")
    a.emit(0x8B, 0x47, 0x10)  # mov eax, [edi+0x10]
    a.call("is_live")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "key_skip")
    a.emit(XFER_OBJECT_COUNT_MAP_KEY_NAME_BYTES)  # mov eax, [edi+0x10] / add eax, 0x64
    a.jmp_absolute(XFER_OBJECT_COUNT_MAP_KEY_NAME_RESUME)
    a.label("key_skip")
    a.jmp_absolute(XFER_OBJECT_COUNT_MAP_NEXT)

    # unknown: the load loop found a name that is not a template. Consume its `Int` into the
    # stock scratch slot so the stream stays aligned, then continue the loop as its own tail does.
    a.label("unknown")
    a.emit(0x8B, 0x06)  # mov eax, [esi]
    a.emit(0x8D, 0x4D, 0xF0)  # lea ecx, [ebp-0x10]
    a.emit(0x51)  # push ecx
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.emit(0xFF, 0x50, 0x7C)  # call [eax+0x7c]   ; xferInt
    a.emit(0x47)  # inc edi
    a.emit(0x66, 0x3B, 0x7D, 0xEC)  # cmp di, [ebp-0x14]
    a.jcc(JB, "unknown_more")
    a.jmp_absolute(XFER_OBJECT_COUNT_MAP_DONE)
    a.label("unknown_more")
    a.jmp_absolute(XFER_OBJECT_COUNT_MAP_LOAD_NEXT)

    # is_live(eax = template pointer) -> eax = 1 if it is a live template, else 0. Walks every
    # template in the factory's list and each one's override chain, comparing pointers only.
    # Preserves every register but eax and the flags.
    a.label("is_live")
    a.emit(0x51)  # push ecx
    a.emit(0x52)  # push edx
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "dead")
    a.emit(0x8B, 0x0D, struct.pack("<I", THE_THING_FACTORY))  # mov ecx, [TheThingFactory]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "dead")
    a.emit(0x8B, 0x49, THING_FACTORY_TEMPLATE_LIST)  # mov ecx, [ecx+0xc]
    a.label("outer")
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "dead")
    a.emit(0x8B, 0xD1)  # mov edx, ecx
    a.label("inner")
    a.emit(0x3B, 0xD0)  # cmp edx, eax
    a.jcc(JE, "live")
    a.emit(0x8B, 0x52, OVERRIDABLE_NEXT_OVERRIDE)  # mov edx, [edx+4]
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JNE, "inner")
    a.emit(0x8B, 0x89, struct.pack("<I", THING_TEMPLATE_NEXT))  # mov ecx, [ecx+0x494]
    a.jmp("outer")
    a.label("live")
    a.emit(0xB8, struct.pack("<I", 1))  # mov eax, 1
    a.jmp("is_live_out")
    a.label("dead")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.label("is_live_out")
    a.emit(0x5A)  # pop edx
    a.emit(0x59)  # pop ecx
    a.emit(0xC3)  # ret
    return a


def build_code(base_va: int) -> bytes:
    return _emit(base_va).finish()


def entry_points(base_va: int) -> dict[str, int]:
    """Where each routine starts, for a cave at `base_va`."""
    asm = _emit(base_va)
    asm.finish()
    return {name: asm.label_va(name) for name in ("merge", "count", "key", "unknown", "is_live")}


def _hook_bytes(va: int, window: int, target: int) -> bytes:
    return b"\xe9" + struct.pack("<i", target - (va + 5)) + bytes([_NOP]) * (window - 5)


class ScoreKeeperDanglingKeysPatch(Patch):
    name = "score-keeper-dangling-keys"
    author = "officialNecro"
    description = (
        "Skip ThingTemplate count-map entries that fail instead of failing with them: a battle "
        "score key that resolves to nothing is not merged into the War of the Ring campaign "
        "score, a key whose template no longer exists (a map.ini object from an earlier battle) "
        "is not saved, and a saved name that is not a template is dropped on load instead of "
        "refusing the save. Stops War of the Ring saves stopping half-written, and loads saves "
        "that already carry such an entry. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        for va, _original, _routine in HOOKS:
            if va_to_offset(data, va) is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        entries = entry_points(section_va)
        for va, original, routine in HOOKS:
            off = va_to_offset(data, va)
            assert off is not None
            apply_byte_patch(
                data,
                off,
                original,
                _hook_bytes(va, len(original), entries[routine]),
                f"{routine} hook -> {self.name} cave",
            )

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the count-map "
                    "code is not this build's, so a cave would return into the wrong place"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located
        problems: list[str] = []
        code = build_code(section_va)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected code")
        entries = entry_points(section_va)
        for va, original, routine in HOOKS:
            off = va_to_offset(data, va)
            if off is None:
                problems.append(f"{va:#010x} is not mapped by any section")
                continue
            expected = _hook_bytes(va, len(original), entries[routine])
            if bytes(data[off : off + len(expected)]) != expected:
                problems.append(f"the {routine} hook at {va:#010x} is not installed")
        return problems
