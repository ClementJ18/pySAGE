"""Let damage cancel a structure's repair, including a repair its worker is doing.

`GettingBuiltBehavior::update` cancels a repair when the structure has taken damage in the last
four seconds, and the cancel has two holes:

- It is skipped when `SpawnTimer` is negative, which is how the data turns auto-heal off and what
  every castle, wall, gate, camp and outpost carries. The gate is erased.
- All it does is `stopRepair`, which clears the structure's own repairing flag. A structure with a
  `WorkerName` never sets that flag: its repair - or its rebuild out of rubble - is a spawned
  worker healing it, and the worker keeps going. A cave after `stopRepair` dismisses that worker
  the way the engine dismisses a finished one (`FADED`, then the structure's producer cleared),
  when the structure was damaged in the last four seconds, spawned the worker, and the worker is
  `WORKER_REPAIRING`.

Both the cancel and the dismissal ask the same question: was the structure hit in the last four
seconds. Any hit counts, so an arrow that a building's armour turns into a point of damage stops a
repair just as a ram does. With `min_damage` above zero, a routine in the same cave replaces the
step that turns `wasDamagedWithin`'s answer into the flag both read
(`GETTING_BUILT_RECENT_DAMAGE_RESULT`): the flag is set only when the body's last recorded hit
dealt at least `min_damage`, after armour and the body's damage scalar. The auto-repair countdown
asks `wasDamagedWithin` itself, so any hit still holds a new worker back. The body records one hit,
the last: a light hit landing after a heavy one, before the update reads it, hides the heavy one.

Derivation: `../docs/repair-damage-cancel.md`.
"""

from __future__ import annotations

import argparse
import struct

from ...addresses import (
    BODY_GET_LAST_DAMAGE_INFO_SLOT,
    DAMAGE_INFO_DAMAGE_DEALT,
    GAME_LOGIC_FIND_OBJECT_BY_ID,
    GETTING_BUILT_CANCEL_RESUME,
    GETTING_BUILT_CANCEL_STOP,
    GETTING_BUILT_CANCEL_STOP_BYTES,
    GETTING_BUILT_DAMAGE_CANCEL,
    GETTING_BUILT_DAMAGE_CANCEL_BYTES,
    GETTING_BUILT_DAMAGE_CANCEL_GATE,
    GETTING_BUILT_DAMAGE_CANCEL_GATE_BYTES,
    GETTING_BUILT_DISMISS_WORKER,
    GETTING_BUILT_DISMISS_WORKER_BYTES,
    GETTING_BUILT_RECENT_DAMAGE_PROBE,
    GETTING_BUILT_RECENT_DAMAGE_PROBE_BYTES,
    GETTING_BUILT_RECENT_DAMAGE_RESULT,
    GETTING_BUILT_RECENT_DAMAGE_RESULT_BYTES,
    GETTING_BUILT_RECENT_DAMAGE_RESUME,
    GETTING_BUILT_SPAWN_COUNTDOWN,
    GETTING_BUILT_SPAWN_TIMER,
    GETTING_BUILT_WORKER_SPAWNED,
    OBJECT_BODY_MODULE,
    OBJECT_KILL,
    OBJECT_MODEL_CONDITIONS_CHANGED,
    OBJECT_PRODUCER,
    OBJECT_SET_PRODUCER,
    OBJECT_STATUS_WORKER_REPAIRING,
    OBJECT_TEST_STATUS,
    THE_GAME_LOGIC,
)
from ...patcher import Patch
from ...utils import (
    allocate_section,
    apply_byte_patch,
    call_rel32,
    file_offset,
    find_section,
    jmp_rel32,
)

__all__ = [
    "ANCHORS",
    "FLAG_HOOK_WIDTH",
    "GATE_REPLACEMENT",
    "HOOK_WIDTH",
    "SECTION_NAME",
    "RepairDamageCancelPatch",
    "build_code",
    "build_flag_code",
]

SECTION_NAME = ".rdcan"  # 6 chars: the PE name field is 8 bytes and truncates silently

#: A two-byte `nop` (`xchg ax, ax`) rather than two `0x90`s, so the site reads as one erased branch.
GATE_REPLACEMENT = bytes.fromhex("6690")

#: The `stopRepair` call the cave takes over: a `jmp` and three `nop`s.
HOOK_WIDTH = len(GETTING_BUILT_CANCEL_STOP_BYTES)

#: The flag store `min_damage` takes over (`test al, al / mov byte [ebp-1], 1 / jne`): a `jmp` and
#: three `nop`s.
FLAG_HOOK_WIDTH = len(GETTING_BUILT_RECENT_DAMAGE_RESULT_BYTES)

#: What the patch relies on and does not rewrite: the probe that makes `[ebp-1]` "damaged in the
#: last four seconds, and not repairing out of rubble", the cancel sequence the gate sits in, and
#: the engine's own worker dismissal the cave repeats (which also pins the helpers it calls).
ANCHORS: dict[int, bytes] = {
    GETTING_BUILT_RECENT_DAMAGE_PROBE: GETTING_BUILT_RECENT_DAMAGE_PROBE_BYTES,
    GETTING_BUILT_DAMAGE_CANCEL: GETTING_BUILT_DAMAGE_CANCEL_BYTES,
    GETTING_BUILT_DISMISS_WORKER: GETTING_BUILT_DISMISS_WORKER_BYTES,
}

#: `Object+0x128` bit `0x10000000`, the model condition the engine raises on a worker before it
#: fades it (`0x008572D2`).
_DISMISS_CONDITION_WORD = 0x128
_DISMISS_CONDITION_BIT = 0x10000000
_DAMAGE_UNRESISTABLE = 8
_DEATH_FADED = 0x16

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000


def build_code(cave_va: int, min_damage: float = 0.0) -> bytes:
    """`stopRepair` as stock, then the worker dismissal; with `min_damage` above zero, followed
    by the flag routine (`build_flag_code`).

    The hook is reached two ways: the damage cancel, and every update of an effectively-dead
    structure (`Object+0x458` bit 0, a rubble rebuild). `[ebp-1]` - damaged in the last four
    seconds - is tested first so the second way only acts on a hit. In the update's frame `edi` is
    the structure and `[ebp-0x18]` its GettingBuilt interface; both survive the calls. `esi` is
    callee-saved and the epilogue pops it, so it is pushed around its use as the worker. The
    worker must be the structure's producer, must not be the structure, must have been spawned by
    this module (`+0x1C`) and must be `WORKER_REPAIRING` - anything else in the producer slot (a
    builder, a plot) is left alone. A dismissal also rewinds the auto-repair countdown, or the
    empty producer slot is refilled the next update."""
    code = bytearray()

    def here() -> int:
        return cave_va + len(code)

    code += GETTING_BUILT_CANCEL_STOP_BYTES  # mov ecx,[ebp-0x18]; mov eax,[ecx]; call [eax+0x14]
    code += b"\x80\x7d\xff\x00"  # cmp byte [ebp-1], 0   damaged in the last four seconds?
    je_done = [len(code)]
    code += b"\x74\x00"  # je .done
    code += b"\x8b\x45\xe8"  # mov eax, [ebp-0x18]        the interface
    code += b"\x80\x78" + bytes([GETTING_BUILT_WORKER_SPAWNED]) + b"\x00"  # cmp byte [eax+0x1c], 0
    je_done.append(len(code))
    code += b"\x74\x00"  # je .done
    code += b"\x56"  # push esi
    code += b"\xff\x77" + bytes([OBJECT_PRODUCER])  # push dword [edi+0x7c]   the producer id
    code += b"\x8b\x0d" + THE_GAME_LOGIC.to_bytes(4, "little")  # mov ecx, [TheGameLogic]
    code += call_rel32(here(), GAME_LOGIC_FIND_OBJECT_BY_ID)
    code += b"\x85\xc0"  # test eax, eax
    je_pop = [len(code)]
    code += b"\x74\x00"  # je .pop
    code += b"\x3b\xc7"  # cmp eax, edi                 not the structure itself
    je_pop.append(len(code))
    code += b"\x74\x00"  # je .pop
    code += b"\x8b\xf0"  # mov esi, eax                 the worker
    code += b"\x6a" + bytes([OBJECT_STATUS_WORKER_REPAIRING])  # push WORKER_REPAIRING
    code += b"\x8b\xce"  # mov ecx, esi
    code += call_rel32(here(), OBJECT_TEST_STATUS)
    code += b"\x84\xc0"  # test al, al
    je_pop.append(len(code))
    code += b"\x74\x00"  # je .pop
    # The engine's dismissal, as at 0x008572D2.
    code += b"\xb8" + _DISMISS_CONDITION_BIT.to_bytes(4, "little")  # mov eax, 0x10000000
    code += b"\x85\x86" + _DISMISS_CONDITION_WORD.to_bytes(4, "little")  # test [esi+0x128], eax
    code += b"\x75\x0d"  # jne .kill                    already raised
    code += b"\x09\x86" + _DISMISS_CONDITION_WORD.to_bytes(4, "little")  # or [esi+0x128], eax
    code += b"\x8b\xce"  # mov ecx, esi
    code += call_rel32(here(), OBJECT_MODEL_CONDITIONS_CHANGED)
    # .kill
    code += b"\x6a" + bytes([_DEATH_FADED])  # push FADED
    code += b"\x6a" + bytes([_DAMAGE_UNRESISTABLE])  # push UNRESISTABLE
    code += b"\x8b\xce"  # mov ecx, esi
    code += call_rel32(here(), OBJECT_KILL)
    code += b"\x6a\x00"  # push 0
    code += b"\x8b\xcf"  # mov ecx, edi
    code += call_rel32(here(), OBJECT_SET_PRODUCER)  # the structure no longer has a worker
    # Rewind the auto-repair countdown to SpawnTimer, as the update does at 0x00857EA4. Left at
    # zero, the countdown in 0x00857818 spawns a new worker the next update after this one.
    code += b"\x8b\x45\xf0"  # mov eax, [ebp-0x10]         moduleData
    code += b"\x8b\x40" + bytes([GETTING_BUILT_SPAWN_TIMER])  # mov eax, [eax+0x20]   SpawnTimer
    code += b"\x8b\x4d\xe8"  # mov ecx, [ebp-0x18]         the interface
    code += b"\x89\x41" + bytes([GETTING_BUILT_SPAWN_COUNTDOWN])  # mov [ecx+0x8], eax
    pop = len(code)
    code += b"\x5e"  # .pop: pop esi
    done = len(code)
    code += jmp_rel32(here(), GETTING_BUILT_CANCEL_RESUME)  # .done

    for at in je_pop:
        code[at + 1] = pop - (at + 2)
    for at in je_done:
        code[at + 1] = done - (at + 2)
    if min_damage > 0:
        code += build_flag_code(here(), min_damage)[0]
    return bytes(code)


def build_flag_code(va: int, min_damage: float) -> tuple[bytes, int]:
    """The "damaged recently" flag store, and the offset of `min_damage` inside it.

    Entered by `jmp` from `GETTING_BUILT_RECENT_DAMAGE_RESULT` with `al` the `wasDamagedWithin`
    answer and `edi` the structure. Writes `[ebp-1]` and leaves at
    `GETTING_BUILT_RECENT_DAMAGE_RESUME`, as both stock stores do. A body without a damage record
    (`InactiveBody`), no body at all and a NaN amount keep the stock answer. Clobbers `eax`, `ecx`,
    `edx`, `xmm0` and `xmm1`, which a call on either side of the hook frees.
    """
    code = bytearray()
    code += b"\x84\xc0"  # test al, al                  hit in the last four seconds?
    to_quiet = [len(code)]
    code += b"\x74\x00"  # je .quiet
    code += b"\x8b\x8f" + struct.pack("<I", OBJECT_BODY_MODULE)  # mov ecx, [edi+body]
    code += b"\x85\xc9"  # test ecx, ecx
    to_recent = [len(code)]
    code += b"\x74\x00"  # je .recent                    no body: the stock answer
    code += b"\x8b\x01"  # mov eax, [ecx]
    code += b"\xff\x50" + bytes([BODY_GET_LAST_DAMAGE_INFO_SLOT])  # call [eax+0x40]
    code += b"\x85\xc0"  # test eax, eax
    to_recent.append(len(code))
    code += b"\x74\x00"  # je .recent                    no record: the stock answer
    code += b"\xf3\x0f\x10\x40" + bytes([DAMAGE_INFO_DAMAGE_DEALT])  # movss xmm0, [eax+0x70]
    code += b"\xb8"  # mov eax, imm32                     min_damage
    min_damage_at = len(code)
    code += struct.pack("<f", min_damage)
    code += b"\x66\x0f\x6e\xc8"  # movd xmm1, eax
    code += b"\x0f\x2f\xc1"  # comiss xmm0, xmm1
    to_recent.append(len(code))
    code += b"\x7a\x00"  # jp .recent                    NaN: the stock answer
    to_quiet.append(len(code))
    code += b"\x72\x00"  # jb .quiet                     dealt less than min_damage
    recent = len(code)
    code += b"\xc6\x45\xff\x01"  # .recent: mov byte [ebp-1], 1
    code += jmp_rel32(va + len(code), GETTING_BUILT_RECENT_DAMAGE_RESUME)
    quiet = len(code)
    code += b"\xc6\x45\xff\x00"  # .quiet: mov byte [ebp-1], 0
    code += jmp_rel32(va + len(code), GETTING_BUILT_RECENT_DAMAGE_RESUME)
    for at in to_recent:
        code[at + 1] = recent - (at + 2)
    for at in to_quiet:
        code[at + 1] = quiet - (at + 2)
    return bytes(code), min_damage_at


class RepairDamageCancelPatch(Patch):
    name = "repair-damage-cancel"
    author = "officialNecro"
    runtime_verified = "yes"
    description = (
        "Make damage cancel a structure's repair. Stock, the cancel only clears the structure's "
        "own repair flag, so a structure with a GettingBuiltBehavior WorkerName keeps being "
        "repaired by its spawned worker; the patch now dismisses that worker (faded, as when a "
        "repair finishes). It also removes the stock exemption for SpawnTimer < 0 (castles, "
        "walls, gates, camps, outposts). Any damage in the last four seconds cancels, including a "
        "worker's rebuild out of rubble; with --min-damage, only a hit dealing at least that "
        "much after armor (the last recorded hit is what is measured). Logic-side: every peer "
        "needs the same binary. No INI change"
    )

    def __init__(self, min_damage: float = 0.0):
        if not min_damage >= 0:
            raise ValueError(f"min_damage must be zero or more, not {min_damage}")
        self.min_damage = float(min_damage)

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        self._check_stock(data, GETTING_BUILT_CANCEL_STOP, GETTING_BUILT_CANCEL_STOP_BYTES)
        self._check_stock(
            data, GETTING_BUILT_RECENT_DAMAGE_RESULT, GETTING_BUILT_RECENT_DAMAGE_RESULT_BYTES
        )
        cave_va = allocate_section(
            data, SECTION_NAME, lambda va: build_code(va, self.min_damage), _CHARACTERISTICS
        )
        apply_byte_patch(
            data,
            file_offset(data, GETTING_BUILT_DAMAGE_CANCEL_GATE),
            GETTING_BUILT_DAMAGE_CANCEL_GATE_BYTES,
            GATE_REPLACEMENT,
            "GettingBuiltBehavior::update SpawnTimer < 0 damage-cancel exemption -> nop",
        )
        apply_byte_patch(
            data,
            file_offset(data, GETTING_BUILT_CANCEL_STOP),
            GETTING_BUILT_CANCEL_STOP_BYTES,
            jmp_rel32(GETTING_BUILT_CANCEL_STOP, cave_va, HOOK_WIDTH),
            "GettingBuiltBehavior::update damage cancel -> also dismiss the repair worker",
        )
        if self.min_damage > 0:
            apply_byte_patch(
                data,
                file_offset(data, GETTING_BUILT_RECENT_DAMAGE_RESULT),
                GETTING_BUILT_RECENT_DAMAGE_RESULT_BYTES,
                self._flag_hook(cave_va),
                "GettingBuiltBehavior::update damaged-recently flag -> only a hit of min_damage",
            )

    @staticmethod
    def _flag_hook(cave_va: int) -> bytes:
        """The jump to the flag routine, which follows the dismissal in the cave."""
        flag_va = cave_va + len(build_code(cave_va))
        return jmp_rel32(GETTING_BUILT_RECENT_DAMAGE_RESULT, flag_va, FLAG_HOOK_WIDTH)

    @staticmethod
    def _check_stock(data: bytes | bytearray, va: int, expected: bytes) -> None:
        off = file_offset(data, va)
        got = bytes(data[off : off + len(expected)])
        if got != expected:
            raise ValueError(
                f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the file is not "
                "the expected build, or already carries this patch"
            )

    @classmethod
    def _check_anchors(cls, data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            cls._check_stock(data, va, expected)

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        off = file_offset(data, GETTING_BUILT_DAMAGE_CANCEL_GATE)
        got = bytes(data[off : off + len(GATE_REPLACEMENT)])
        if got != GATE_REPLACEMENT:
            problems.append(
                f"@{GETTING_BUILT_DAMAGE_CANCEL_GATE:#010x}: the SpawnTimer gate is not erased "
                f"(holds {got.hex()})"
            )
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [*problems, f"no {SECTION_NAME} section: the file does not carry this patch"]
        cave_va, cave_off, vsize = located
        code = build_code(cave_va, self.min_damage)
        if vsize < len(code) or bytes(data[cave_off : cave_off + len(code)]) != code:
            problems.append(f"the routine in {SECTION_NAME} is not the one this patch builds")
        want = jmp_rel32(GETTING_BUILT_CANCEL_STOP, cave_va, HOOK_WIDTH)
        off = file_offset(data, GETTING_BUILT_CANCEL_STOP)
        got = bytes(data[off : off + HOOK_WIDTH])
        if got != want:
            problems.append(
                f"@{GETTING_BUILT_CANCEL_STOP:#010x}: the damage cancel does not jump to "
                f"{SECTION_NAME} (holds {got.hex()})"
            )
        want = (
            self._flag_hook(cave_va)
            if self.min_damage > 0
            else GETTING_BUILT_RECENT_DAMAGE_RESULT_BYTES
        )
        off = file_offset(data, GETTING_BUILT_RECENT_DAMAGE_RESULT)
        got = bytes(data[off : off + FLAG_HOOK_WIDTH])
        if got != want:
            problems.append(
                f"@{GETTING_BUILT_RECENT_DAMAGE_RESULT:#010x}: the damaged-recently flag store is "
                f"not the one min_damage={self.min_damage:g} expects (holds {got.hex()})"
            )
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> RepairDamageCancelPatch | None:
        """Recognise the patch and recover `min_damage`: zero when the flag store is stock, else
        the immediate in the flag routine."""
        try:
            located = find_section(data, SECTION_NAME)
            if located is None:
                return None
            cave_va, cave_off, _ = located
            off = file_offset(data, GETTING_BUILT_RECENT_DAMAGE_RESULT)
            min_damage = 0.0
            if bytes(data[off : off + FLAG_HOOK_WIDTH]) == cls._flag_hook(cave_va):
                _, min_damage_at = build_flag_code(0, 1.0)
                at = cave_off + len(build_code(cave_va)) + min_damage_at
                min_damage = round(struct.unpack_from("<f", data, at)[0], 3)
            patch = cls(min_damage=min_damage)
            problems = patch.verify(data)
        except (ValueError, KeyError, IndexError, TypeError, struct.error):
            return None
        return None if problems else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--min-damage",
            type=float,
            default=0.0,
            metavar="DAMAGE",
            help=(
                "the least damage, after armor, a hit must deal to cancel a structure's repair "
                "(default 0: any hit)"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> RepairDamageCancelPatch:
        return cls(min_damage=args.min_damage)
