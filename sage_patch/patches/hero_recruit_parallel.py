"""The hero-recruit-parallel patch: a hero being recruited stops freezing the production queued
behind it.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/hero-recruit-parallel.md``.

**The defect.** A `ProductionUpdate` keeps units, upgrades and hero revives in one list, appended
at the tail, and `ProductionUpdate::update` advances **exactly one entry per frame** - whichever
`PRODUCTION_UPDATE_PICK_ENTRY` returns. The picker has four rules: an entry whose batch is already
part-produced, a `DOZER`, a revive whose clock has reached 1.0, and - failing all three - **the
head, whatever it is**.

A revive's clock is not the queue's. `queueCreateUnit` calls `REVIVE_MGR_START`, which stamps the
current logic frame into the hero's roster record at `Player+0x758`, and the entry finishes when
``(now - start) / totalFrames >= 1.0``. That runs on the game frame no matter where the entry sits.

Those two facts produce the report exactly. A hero queued **behind** other entries finishes on
time anyway, because the third rule scans the whole list and returns a ready revive out of order -
the parallelism players see. A hero at the **head** of the queue is returned by the fourth rule
every frame, fails the completion test, and `update` returns - so everything queued after it is
frozen for the rest of the revive.

**What this does.** Appends a `.hqueue` PE section holding a rewritten fallback, and redirects the
fallback's seven-byte entry into it. The rewrite returns the first entry that is **not** a revive,
and falls back to the head only when the queue holds nothing but revives.

**Why skipping a revive there loses nothing.** `update`'s three effects on a selected revive are
the command-point stall, the progress accrual into `entry+0x1C`, and the completion test. The
accrual and the test are dead for a revive, because completion reads the player's clock instead;
and the stall is separately done for *every* revive in the queue, wherever it sits, by
`PRODUCTION_UPDATE_REVIVE_COMMAND_POINT_DELAY` at the top of the same tick. A revive that really is
ready is still returned by the third rule, which runs first and reaches the whole list - so no
hero completes later than it does today.

**Why the fallback and not the rule that picks a ready revive.** The two rules answer different
questions and only one of them is wrong. "A ready hero may jump the queue" is the behaviour the
report calls parallel and wants kept; "a waiting hero owns the frame" is the behaviour it calls
blocking. Editing the fallback changes the second and leaves the first byte-for-byte.

**Revive timing is untouched.** The clock is armed at `queueCreateUnit` and read from
`TheGameLogic`'s frame; this patch reads neither and writes neither. A hero recruited into an empty
queue completes on exactly the frame it does today.

**Every peer must run the same patched binary.** Which entry advances is logic state feeding the
per-frame CRC, so a patched and an unpatched client diverge the first frame a hero sits at the head
of a non-empty queue, and replays do not cross. That is the same requirement `production-condition`
and `rebuild-hole-construction` carry.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. The only engine bytes it edits are the seven at
`PRODUCTION_UPDATE_PICK_FALLBACK`, which no other bundled patch touches - `queue-ignore-cp` and
`unique-production-id` are the two that reach into this module and they take `0x008A1E27`,
`0x008A12A2` and the interface vtable, none of them inside the picker.
"""

from __future__ import annotations

import struct

from ..addresses import (
    PRODUCTION_ENTRY_KIND,
    PRODUCTION_ENTRY_KIND_REVIVE,
    PRODUCTION_ENTRY_NEXT,
    PRODUCTION_QUEUE_HEAD,
    PRODUCTION_UPDATE_PICK_CALL,
    PRODUCTION_UPDATE_PICK_CALL_BYTES,
    PRODUCTION_UPDATE_PICK_ENTRY,
    PRODUCTION_UPDATE_PICK_ENTRY_BYTES,
    PRODUCTION_UPDATE_PICK_FALLBACK,
    PRODUCTION_UPDATE_PICK_FALLBACK_BYTES,
    PRODUCTION_UPDATE_PICK_RETURN,
    PRODUCTION_UPDATE_PICK_RETURN_BYTES,
    PRODUCTION_UPDATE_PICK_REVIVE_READY,
    PRODUCTION_UPDATE_PICK_REVIVE_READY_BYTES,
    PRODUCTION_UPDATE_PICK_REVIVE_SCAN,
    PRODUCTION_UPDATE_PICK_REVIVE_SCAN_BYTES,
    REVIVE_MGR_PROGRESS,
    REVIVE_MGR_PROGRESS_BYTES,
    REVIVE_MGR_START,
    REVIVE_MGR_START_BYTES,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "HOOK_ORIGINAL",
    "HOOK_VA",
    "REVIVE_READY_TARGET",
    "SECTION_NAME",
    "HeroRecruitParallelPatch",
    "build_code",
]

SECTION_NAME = ".hqueue"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

HOOK_VA = PRODUCTION_UPDATE_PICK_FALLBACK
HOOK_ORIGINAL = PRODUCTION_UPDATE_PICK_FALLBACK_BYTES

#: Where the revive rule's readiness call actually goes, decoded from its own bytes rather than
#: written down. The patch's correctness rests on that rule catching every ready revive one rule
#: ahead of the fallback it rewrites, so "the rule asks the player's revive clock" is a *derived*
#: fact an anchor enforces rather than a comment nobody rechecks.
REVIVE_READY_TARGET = (
    PRODUCTION_UPDATE_PICK_REVIVE_READY
    + 5
    + struct.unpack("<i", PRODUCTION_UPDATE_PICK_REVIVE_READY_BYTES[1:5])[0]
)

#: The first bytes at each address the cave jumps to, plus the ones that pin what the picker is
#: and how it is reached, as a ``{va: bytes}`` map. The fallback's own seven are asserted by
#: `apply_byte_patch`. A build whose layout moved fails here instead of on a wild jump.
ANCHORS = {
    # the picker's prologue, and `update`'s once-per-tick call to it
    PRODUCTION_UPDATE_PICK_ENTRY: PRODUCTION_UPDATE_PICK_ENTRY_BYTES,
    PRODUCTION_UPDATE_PICK_CALL: PRODUCTION_UPDATE_PICK_CALL_BYTES,
    # the two points the cave branches to: the revive rule's loop body and the epilogue
    PRODUCTION_UPDATE_PICK_REVIVE_SCAN: PRODUCTION_UPDATE_PICK_REVIVE_SCAN_BYTES,
    PRODUCTION_UPDATE_PICK_RETURN: PRODUCTION_UPDATE_PICK_RETURN_BYTES,
    # the revive rule's readiness call, and the two manager methods that make it mean what
    # this patch assumes: the clock is armed at queue time and read off the logic frame
    PRODUCTION_UPDATE_PICK_REVIVE_READY: PRODUCTION_UPDATE_PICK_REVIVE_READY_BYTES,
    REVIVE_MGR_PROGRESS: REVIVE_MGR_PROGRESS_BYTES,
    REVIVE_MGR_START: REVIVE_MGR_START_BYTES,
}


def build_code(base_va: int) -> bytes:
    """The rewritten fallback. Reached only from the hook, and never returns to it.

    `esi` holds the `ProductionUpdate` module base and is read, not written. `eax` is the only
    register touched, and it is the return value - `ebx`, `edi` and `esi` are restored by the pops
    at `PRODUCTION_UPDATE_PICK_RETURN`, which is where every path here ends.
    """
    a = Asm(base_va)
    # The displaced loop condition, unchanged: still going round the revive rule's scan?
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc_short(JE, "fallback")
    a.jmp_absolute(PRODUCTION_UPDATE_PICK_REVIVE_SCAN)

    # No rule fired. Stock returns the head; this returns the first entry that is not a revive,
    # so a hero waiting on its own clock no longer owns the frame.
    a.label("fallback")
    a.emit(0x8B, 0x46, PRODUCTION_QUEUE_HEAD)  # mov eax, [esi+0x28]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "done")  # empty queue: NULL, as stock

    a.label("scan")
    a.emit(0x83, 0x78, PRODUCTION_ENTRY_KIND, PRODUCTION_ENTRY_KIND_REVIVE)  # cmp [eax+4], 3
    a.jcc_short(JNE, "done")
    a.emit(0x8B, 0x40, PRODUCTION_ENTRY_NEXT)  # mov eax, [eax+0x48]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JNE, "scan")
    # Nothing but revives in the queue: the stock answer, so a queue of heroes is unchanged.
    a.emit(0x8B, 0x46, PRODUCTION_QUEUE_HEAD)  # mov eax, [esi+0x28]

    a.label("done")
    a.jmp_absolute(PRODUCTION_UPDATE_PICK_RETURN)
    return a.finish()


class HeroRecruitParallelPatch(Patch):
    name = "hero-recruit-parallel"
    author = "officialNecro"
    description = (
        "Stop a hero being recruited from freezing the units and upgrades queued behind it at "
        "the same building. The hero's own revive time is unchanged; a ready hero still jumps "
        "the queue to appear. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        hook_off = va_to_offset(data, HOOK_VA)
        if hook_off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        # Prove the function being edited is the one `update` calls once a tick, that the points
        # the cave jumps back into still hold the instructions they are chosen for, and that the
        # rule this patch relies on still asks the player's revive clock.
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        jump = b"\xe9" + struct.pack("<i", section_va - (HOOK_VA + 5)) + b"\x90\x90"
        apply_byte_patch(
            data,
            hook_off,
            HOOK_ORIGINAL,
            jump,
            "ProductionUpdate entry picker fallback -> hero-recruit-parallel cave",
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
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the production "
                    "queue's entry picker is not this build's, so the cave would jump into the "
                    "wrong place or skip the wrong entries"
                )
        if REVIVE_READY_TARGET != REVIVE_MGR_PROGRESS:
            raise ValueError(
                f"the revive rule calls {REVIVE_READY_TARGET:#010x}, not the revive manager's "
                f"progress at {REVIVE_MGR_PROGRESS:#010x} - a ready hero would not be picked up "
                "one rule ahead of the fallback this patch rewrites"
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"{SECTION_NAME} section is absent"]
        section_va, section_off, _ = located
        off = va_to_offset(data, HOOK_VA)
        if off is None:
            return [f"{HOOK_VA:#010x} is not mapped by any section"]
        if data[off] != 0xE9:
            return [f"{HOOK_VA:#010x} is not a jmp - the hook is not installed"]
        target = HOOK_VA + 5 + struct.unpack_from("<i", data, off + 1)[0]
        if target != section_va:
            problems.append(f"hook jumps to {target:#010x}, expected {section_va:#010x}")
        if bytes(data[off + 5 : off + len(HOOK_ORIGINAL)]) != b"\x90\x90":
            problems.append(f"{HOOK_VA + 5:#010x} is not the two-byte pad the hook leaves")
        code = build_code(section_va)
        if bytes(data[section_off : section_off + len(code)]) != code:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected fallback")
        return problems
