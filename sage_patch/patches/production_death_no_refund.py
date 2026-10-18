"""Stop a destroyed producer from refunding its production queue.

When an object with a `ProductionUpdate` dies, its `onDie` cancels every queued unit, hero and
upgrade through `cancelAndRefundAllProduction`, and each cancel deposits what the entry cost back
into the owner's money. The patch keeps the cancel and drops the deposit, for deaths only.

The same cancel-all runs when a producer is sold, captured, or replaced, and those keep their
refund. Only the `onDie` thunk tells a death apart, so its vtable slot is pointed at a cave that
raises a flag around the stock thunk, and the two refund sites skip their deposit while it is up.
Everything else a cancel does still runs: the entry is removed, a hero's revive record is
released, and a player upgrade leaves its in-production state.

Derivation: `../docs/production-death-refund.md`.
"""

from __future__ import annotations

from ..addresses import (
    PRODUCTION_CANCEL_ALL,
    PRODUCTION_CANCEL_ALL_BYTES,
    PRODUCTION_CANCEL_UNIT_REFUND,
    PRODUCTION_CANCEL_UNIT_REFUND_BYTES,
    PRODUCTION_CANCEL_UNIT_REFUND_RESUME,
    PRODUCTION_CANCEL_UNIT_REFUND_SKIP,
    PRODUCTION_CANCEL_UPGRADE_REFUND,
    PRODUCTION_CANCEL_UPGRADE_REFUND_BYTES,
    PRODUCTION_CANCEL_UPGRADE_REFUND_RESUME,
    PRODUCTION_CANCEL_UPGRADE_REFUND_SKIP,
    PRODUCTION_ON_DIE,
    PRODUCTION_ON_DIE_BYTES,
    PRODUCTION_ON_DIE_SLOT,
    PRODUCTION_ON_LOSS,
    PRODUCTION_ON_LOSS_BYTES,
)
from ..asm import JNE, Asm
from ..patcher import Patch
from ..utils import (
    allocate_section,
    apply_byte_patch,
    file_offset,
    find_section,
    jmp_rel32,
    u32,
)

__all__ = [
    "ANCHORS",
    "FLAG_OFF",
    "SECTION_NAME",
    "UNIT_HOOK_WIDTH",
    "UPGRADE_HOOK_WIDTH",
    "ProductionDeathNoRefundPatch",
    "build_section",
    "layout",
]

SECTION_NAME = ".pdnoref"  # 8 chars: the PE name field is 8 bytes and truncates silently

#: The death flag: one byte, raised only while the stock `onDie` runs.
FLAG_OFF = 0x00
_CODE_OFF = 0x04

#: `mov eax,[ebp+8]` / `push 1`, the head of the upgrade refund.
UPGRADE_HOOK_WIDTH = PRODUCTION_CANCEL_UPGRADE_REFUND_RESUME - PRODUCTION_CANCEL_UPGRADE_REFUND
#: `cmp byte [ebp-1],0` / `mov edi,eax` / `jne`, the unit refund's own gate.
UNIT_HOOK_WIDTH = PRODUCTION_CANCEL_UNIT_REFUND_RESUME - PRODUCTION_CANCEL_UNIT_REFUND

#: What the patch relies on and does not rewrite: the stock thunk the cave calls, the slot it
#: calls into, and the cancel-all that slot reaches. A change to any of them could route a death
#: around the flag or reach the refunds another way.
ANCHORS: dict[int, bytes] = {
    PRODUCTION_ON_DIE: PRODUCTION_ON_DIE_BYTES,
    PRODUCTION_ON_LOSS: PRODUCTION_ON_LOSS_BYTES,
    PRODUCTION_CANCEL_ALL: PRODUCTION_CANCEL_ALL_BYTES,
}

# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE: the flag is written at
# runtime.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000


#: The routines `layout` reports, in emission order.
_ROUTINES = ("on_die", "upgrade_gate", "unit_gate")


def _assemble(base_va: int) -> Asm:
    """The three routines, laid out after the flag. Hand-encoded; `Asm` resolves the branches."""
    flag = u32(base_va + FLAG_OFF)
    a = Asm(base_va + _CODE_OFF)

    # on_die: the new vtable target. `__thiscall` on the DieModuleInterface sub-object with one
    # stack argument (the DamageInfo), which is passed through to the stock thunk; the thunk's
    # `ret 4` pops that copy, so ours pops the caller's.
    a.label("on_die")
    a.emit(0xC6, 0x05, flag, 0x01)  # mov byte [flag], 1
    a.emit(0xFF, 0x74, 0x24, 0x04)  # push dword [esp+4]        the DamageInfo
    a.call_absolute(PRODUCTION_ON_DIE)  # the stock onDie       ecx untouched
    a.emit(0xC6, 0x05, flag, 0x00)  # mov byte [flag], 0
    a.emit(0xC2, 0x04, 0x00)  # ret 4

    # upgrade_gate: from `cancelUpgrade`, before anything is pushed for the deposit.
    a.label("upgrade_gate")
    a.emit(0x80, 0x3D, flag, 0x00)  # cmp byte [flag], 0
    a.jcc(JNE, "upgrade_skip")
    a.emit(0x8B, 0x45, 0x08)  # mov eax, [ebp+8]          (stock)
    a.emit(0x6A, 0x01)  # push 1                    (stock)
    a.jmp_absolute(PRODUCTION_CANCEL_UPGRADE_REFUND_RESUME)
    a.label("upgrade_skip")
    a.jmp_absolute(PRODUCTION_CANCEL_UPGRADE_REFUND_SKIP)

    # unit_gate: from `cancelUnitCreate`. The stock gate first, then the flag; both skip to the
    # same place, past the deposit and the tally.
    a.label("unit_gate")
    a.emit(0x8B, 0xF8)  # mov edi, eax              (stock) the owner
    a.emit(0x80, 0x7D, 0xFF, 0x00)  # cmp byte [ebp-1], 0       (stock) waiting at the door
    a.jcc(JNE, "unit_skip")
    a.emit(0x80, 0x3D, flag, 0x00)  # cmp byte [flag], 0
    a.jcc(JNE, "unit_skip")
    a.jmp_absolute(PRODUCTION_CANCEL_UNIT_REFUND_RESUME)
    a.label("unit_skip")
    a.jmp_absolute(PRODUCTION_CANCEL_UNIT_REFUND_SKIP)
    return a


def build_section(base_va: int) -> bytes:
    """The section's bytes: the flag (zero), then the routines."""
    return bytes(_CODE_OFF) + _assemble(base_va).finish()


def layout(base_va: int) -> dict[str, int]:
    """The VA of the flag and of each routine in a section based at `base_va`."""
    a = _assemble(base_va)
    return {"flag": base_va + FLAG_OFF, **{name: a.label_va(name) for name in _ROUTINES}}


def _hooks(base_va: int) -> list[tuple[int, bytes, bytes, str]]:
    """Every in-place edit as `(va, stock, replacement, note)`."""
    at = layout(base_va)
    return [
        (
            PRODUCTION_ON_DIE_SLOT,
            u32(PRODUCTION_ON_DIE),
            u32(at["on_die"]),
            "ProductionUpdate onDie vtable slot -> raise the death flag around the stock thunk",
        ),
        (
            PRODUCTION_CANCEL_UPGRADE_REFUND,
            PRODUCTION_CANCEL_UPGRADE_REFUND_BYTES[:UPGRADE_HOOK_WIDTH],
            jmp_rel32(PRODUCTION_CANCEL_UPGRADE_REFUND, at["upgrade_gate"], UPGRADE_HOOK_WIDTH),
            "cancelUpgrade refund -> skipped on death",
        ),
        (
            PRODUCTION_CANCEL_UNIT_REFUND,
            PRODUCTION_CANCEL_UNIT_REFUND_BYTES[:UNIT_HOOK_WIDTH],
            jmp_rel32(PRODUCTION_CANCEL_UNIT_REFUND, at["unit_gate"], UNIT_HOOK_WIDTH),
            "cancelUnitCreate refund -> skipped on death",
        ),
    ]


class ProductionDeathNoRefundPatch(Patch):
    name = "production-death-no-refund"
    author = "officialNecro"
    description = (
        "Stop a destroyed building (or any producer that dies) from refunding its production "
        "queue: queued units, heroes and upgrades are cancelled as before, but their cost is "
        "lost. Selling, capturing or replacing a producer still refunds. Logic-side: every peer "
        "needs the same binary. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        for va, expected in ANCHORS.items():
            self._check_stock(data, va, expected)
        self._check_stock(
            data, PRODUCTION_CANCEL_UPGRADE_REFUND, PRODUCTION_CANCEL_UPGRADE_REFUND_BYTES
        )
        self._check_stock(data, PRODUCTION_CANCEL_UNIT_REFUND, PRODUCTION_CANCEL_UNIT_REFUND_BYTES)
        self._check_stock(data, PRODUCTION_ON_DIE_SLOT, u32(PRODUCTION_ON_DIE))
        base_va = allocate_section(data, SECTION_NAME, build_section, _CHARACTERISTICS)
        for va, stock, replacement, note in _hooks(base_va):
            apply_byte_patch(data, file_offset(data, va), stock, replacement, note)

    @staticmethod
    def _check_stock(data: bytes | bytearray, va: int, expected: bytes) -> None:
        off = file_offset(data, va)
        got = bytes(data[off : off + len(expected)])
        if got != expected:
            raise ValueError(
                f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the file is not "
                "the expected build, or already carries this patch"
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        base_va, section_off, vsize = located
        problems: list[str] = []
        expected = build_section(base_va)
        got = bytes(data[section_off : section_off + len(expected)])
        if vsize < len(expected) or got[_CODE_OFF:] != expected[_CODE_OFF:]:
            problems.append(f"the routines in {SECTION_NAME} are not the ones this patch builds")
        for va, _stock, replacement, note in _hooks(base_va):
            off = file_offset(data, va)
            here = bytes(data[off : off + len(replacement)])
            if here != replacement:
                problems.append(f"@{va:#010x}: {note} is not installed (holds {here.hex()})")
        return problems
