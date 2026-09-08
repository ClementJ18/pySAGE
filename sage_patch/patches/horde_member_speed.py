"""The horde member-speed patch: a battalion respects the `SPEED` modifiers on its members.

The reverse engineering behind this is [`../docs/horde-member-speed.md`](
../docs/horde-member-speed.md). Targets the ROTWK SAGE-engine `game.dat` build
``2.01.2614.37001``.

**The defect.** A `ModifierList` carrying ``Modifier = SPEED n%``, applied to the *member* of a
battalion, changes nothing a player can see. A battalion is two kinds of object and only one of
them is moving: the horde container declares its own `LocomotorSet`, pathfinds, and sets the pace;
the members are formation slots being dragged along behind it. `SPEED` is folded in per object by
`Locomotor::getMaxSpeed`, from the speed of *the object it was asked about* - so a member's
modifier scales the member, which already had headroom it was not using.

Stock RotWK says so in its own tuning. `NORMAL_FOOT_MED_HORDE_SPEED` is 50 and
`NORMAL_FOOT_MED_MEMBER_SPEED` is 55, the member's deliberately the larger "so when the formation
wheels the unit can catch up". Raising the 55 buys more catch-up headroom; the 50 is the pace.

**What this does.** Replaces the five bytes of `getMaxSpeed`'s `SPEED` query
(`LOCOMOTOR_SPEED_MODIFIER_CALL`) with a ``call`` into a cave that forwards to the same
`Object::getModifierMultiplier` for the object itself and then, **only** for a `KINDOF HORDE`
object with a contain module, walks the contained-items list and folds in the members' answer to
the same question. The result the caller sees is ``own x aggregate``.

Members are filtered on `ObjectStatus HORDE_MEMBER`, which `HordeContain::addToContain` clears for
a `MACHINE`, `HERO` or `SIEGE_TOWER` joining the battalion - so a hero who has joined, carrying
none of the battalion's upgrades, cannot drag a minimum back down to 1.0.

**The aggregate.** ``min`` by default: a formation moves at the pace of its slowest rank, and
``SPEED 0%`` is how RotWK's own `attributemodifier.ini` writes "cannot move", where a battalion
that keeps marching because eleven of twelve members are unrooted is the worse failure.
``--aggregate max`` is the mirror-image reading, and the safer choice for a mod whose speed buffs
reach members through something that can miss one.

**It changes nothing where it finds nothing.** With no contributing member the cave takes the
stock ``al = 0`` arm and the caller skips the multiply byte for byte; a horde whose own modifier
is the only active one gets ``own x 1.0f``, which is exact. Only a horde with a modifier-carrying
member sees a different number, which is the whole point.

What it deliberately does not reach: `MinSpeed`, `MinTurnSpeed` and `BackingUpSpeed`, which scale
the same cached speed and apply no modifier at all in stock either; any modifier type but the one
the site pushes; and a horde inside a horde, since the walk goes one level.

**Every peer must run the same patched binary.** Movement is simulation state, so a patched and an
unpatched client diverge the first frame a modified battalion moves, and replays do not cross.

**Composition.** One cave, allocated with :func:`~..utils.allocate_section`; five bytes rewritten
at an address no other bundled patch touches. It reads the modifier system through the same public
entry point every other patch does and rewrites none of it, so it is order-independent with
`healing-received`, `production-split` and anything else that appends a modifier type - the cave
forwards whatever type the site pushes rather than naming one.
"""

from __future__ import annotations

import argparse
import struct

from ..addresses import (
    AI_UPDATE_SET_LOCOMOTOR_SET_SPEED_STORE,
    CONTAIN_ITEM_LIST,
    CONTAIN_ITEM_LIST_NODE_OBJECT,
    CONTAIN_ITEM_LIST_WALK,
    CONTAIN_ITEM_LIST_WALK_ENTRY,
    KINDOF_HORDE_BIT,
    KINDOF_HORDE_BYTE,
    LOCOMOTOR_GET_MAX_SPEED,
    LOCOMOTOR_GET_MAX_SPEED_ENTRY,
    LOCOMOTOR_SPEED_MODIFIER_CALL,
    LOCOMOTOR_SPEED_MODIFIER_CALL_BYTES,
    LOCOMOTOR_SPEED_MODIFIER_FOLD,
    LOCOMOTOR_SPEED_MODIFIER_FOLD_BYTES,
    LOCOMOTOR_SPEED_MODIFIER_SETUP,
    LOCOMOTOR_SPEED_MODIFIER_SETUP_BYTES,
    OBJECT_CONTAIN,
    OBJECT_GET_MODIFIER_MULTIPLIER,
    OBJECT_STATUS,
    OBJECT_STATUS_HORDE_MEMBER,
    OBJECT_TEST_STATUS,
    OBJECT_THING_TEMPLATE,
)
from ..asm import JAE, JBE, JE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "AGGREGATES",
    "ANCHORS",
    "DEFAULT_AGGREGATE",
    "SECTION_NAME",
    "HordeMemberSpeedPatch",
    "build_section",
]

SECTION_NAME = ".hrdspd"  # 7 chars: the PE name field is 8 bytes and truncates silently
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ - the cave holds one stub.
SECTION_CHARACTERISTICS = 0x60000060

#: How a member's multiplier is combined with the running aggregate, as the condition that
#: **skips** the store. ``min`` keeps the smaller, so it skips when the member's is already the
#: larger or equal; ``max`` is its mirror.
AGGREGATES: dict[str, int] = {"min": JAE, "max": JBE}
DEFAULT_AGGREGATE = "min"

#: `ObjectStatus` bit 38 as the byte and mask `OBJECT_TEST_STATUS` would index, derived rather
#: than written down so it cannot drift from the encoding that function documents.
_HORDE_MEMBER_BYTE = OBJECT_STATUS + (OBJECT_STATUS_HORDE_MEMBER // 32) * 4
_HORDE_MEMBER_MASK = 1 << (OBJECT_STATUS_HORDE_MEMBER % 8)

_ONE_F = struct.pack("<f", 1.0)

# The cave's stack frame, as displacements off `ebp`.
_OWN = 0xFC  # [ebp-4]   the object's own multiplier, 1.0 until something contributes
_OUT = 0xF8  # [ebp-8]   the private out slot every query writes into
_AGG = 0xF4  # [ebp-0xC] the aggregate over the members, 1.0 until something contributes

# The caller's four arguments, as displacements off `ebp` once the cave has framed.
_ARG_TYPE = 0x08
_ARG_OUT = 0x0C
_ARG_CTX = 0x10
_ARG_FLAG = 0x14

#: Byte windows this patch depends on and does not write. The `getMaxSpeed` entry pins the
#: function - its prologue, `edi` as the object argument and the read of the AI's cached set speed
#: - the setup pins that the hooked call is the `SPEED` query on that object with `&out` at
#: `[ebp-8]`, the fold pins that "nothing contributed" still means "leave the speed alone", the
#: `AIUpdate` store pins that the speed a horde moves at is its container's `LocomotorSet` and not
#: its members', the contain walk pins the member-list layout the cave reads, and `testStatus`
#: pins the bit encoding the `HORDE_MEMBER` filter open-codes.
ANCHORS: dict[int, bytes] = {
    LOCOMOTOR_GET_MAX_SPEED: LOCOMOTOR_GET_MAX_SPEED_ENTRY,
    LOCOMOTOR_SPEED_MODIFIER_SETUP: LOCOMOTOR_SPEED_MODIFIER_SETUP_BYTES,
    LOCOMOTOR_SPEED_MODIFIER_FOLD: LOCOMOTOR_SPEED_MODIFIER_FOLD_BYTES,
    AI_UPDATE_SET_LOCOMOTOR_SET_SPEED_STORE: bytes.fromhex("d99ef8010000"),
    CONTAIN_ITEM_LIST_WALK: CONTAIN_ITEM_LIST_WALK_ENTRY,
    OBJECT_TEST_STATUS: bytes.fromhex(
        "8b54240433c0568bf1408bca83e11fd3e0c1ea05238496940000005ef7d81bc0f7d8c20400"
    ),
}


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _call_bytes(from_va: int, to_va: int) -> bytes:
    """The five bytes of ``call rel32`` sited at ``from_va``."""
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


def _query(a: Asm) -> Asm:
    """Emit one `Object::getModifierMultiplier` call on whatever is already in ``ecx``.

    The type, the ctx and the flag are the caller's own arguments, forwarded rather than named, so
    the cave is a widening of the query the site already makes and not a differently-shaped second
    one. The out pointer is the cave's private slot: the caller's `Real*` is written once, at the
    end, from the finished product."""
    a.emit(b"\xff\x75", _ARG_FLAG)  # push dword [ebp+0x14]   ; flag
    a.emit(b"\xff\x75", _ARG_CTX)  # push dword [ebp+0x10]    ; ctx
    a.emit(b"\x8d\x45", _OUT)  # lea  eax, [ebp-8]
    a.emit(0x50)  # push eax                                  ; &out, the cave's own slot
    a.emit(b"\xff\x75", _ARG_TYPE)  # push dword [ebp+8]      ; the type the site asked for
    a.call_absolute(OBJECT_GET_MODIFIER_MULTIPLIER)  # ret 0x10: it cleans all four
    return a


def build_section(base_va: int, aggregate: str = DEFAULT_AGGREGATE) -> bytes:
    """Return the cave's bytes for a section based at ``base_va``.

    One stub, entered at ``base_va`` by the ``call`` that replaced the stock query, and returning
    the way the stock callee does - ``al`` for "something contributed", the product through the
    caller's out pointer, ``ret 0x10``.

    The caller reads ``al``, ``[ebp-8]`` and ``[ebp-4]`` and keeps ``ebx``, ``esi``, ``edi`` and
    ``ebp`` live across the call, so the stub saves the three it uses and restores ``esp`` from
    ``ebp``. The accumulators live on the stack rather than in XMM registers because every XMM
    register is volatile across the two calls the stub makes, and ``ecx`` is re-established from
    the list node on every iteration because `getModifierMultiplier` does not preserve it."""
    skip = AGGREGATES[aggregate]
    a = Asm(base_va)

    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov  ebp, esp
    a.emit(b"\x83\xec\x10")  # sub  esp, 0x10          ; own, out, aggregate
    a.emit(0x53, 0x56, 0x57)  # push ebx / esi / edi
    a.emit(b"\x8b\xf9")  # mov  edi, ecx               ; the Object the site asked about
    a.emit(b"\xc7\x45", _OWN, _ONE_F)  # mov dword [ebp-4], 1.0
    a.emit(b"\xc7\x45", _AGG, _ONE_F)  # mov dword [ebp-0xC], 1.0
    a.emit(b"\x33\xdb")  # xor  ebx, ebx               ; nothing has contributed yet

    # The object's own modifier - the query this cave replaced, unchanged in meaning.
    a.emit(b"\x8b\xcf")  # mov  ecx, edi
    _query(a)
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc_short(JE, "horde")
    a.emit(b"\xbb", _u32(1))  # mov ebx, 1
    a.emit(b"\xf3\x0f\x10\x45", _OUT)  # movss xmm0, [ebp-8]
    a.emit(b"\xf3\x0f\x11\x45", _OWN)  # movss [ebp-4], xmm0

    # Only a horde has members to ask, and only a horde that contains something has a list.
    a.label("horde")
    a.emit(b"\x8b\x47", OBJECT_THING_TEMPLATE)  # mov eax, [edi+4]
    a.emit(b"\xf6\x80", _u32(KINDOF_HORDE_BYTE), KINDOF_HORDE_BIT)  # test byte [eax+0x115], 0x20
    a.jcc(JE, "done")
    a.emit(b"\x8b\xbf", _u32(OBJECT_CONTAIN))  # mov edi, [edi+0x258]  ; ContainModuleInterface*
    a.emit(b"\x85\xff")  # test edi, edi
    a.jcc(JE, "done")
    a.emit(b"\x8b\x77", CONTAIN_ITEM_LIST)  # mov esi, [edi+0x34]     ; the sentinel node
    a.emit(b"\x85\xf6")  # test esi, esi
    a.jcc(JE, "done")
    a.emit(b"\x8b\x3e")  # mov  edi, [esi]                            ; the first node

    a.label("loop")
    a.emit(b"\x3b\xfe")  # cmp  edi, esi                              ; back at the sentinel?
    a.jcc(JE, "done")
    a.emit(b"\x8b\x47", CONTAIN_ITEM_LIST_NODE_OBJECT)  # mov eax, [edi+8]  ; the member
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JE, "next")
    # HORDE_MEMBER: cleared for a MACHINE, HERO or SIEGE_TOWER that joined the battalion, so this
    # is the engine's own answer to "is this one of the rank and file".
    a.emit(b"\xf6\x80", _u32(_HORDE_MEMBER_BYTE), _HORDE_MEMBER_MASK)
    a.jcc_short(JE, "next")
    a.emit(b"\x8b\xc8")  # mov  ecx, eax
    _query(a)
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc_short(JE, "next")
    a.emit(b"\xbb", _u32(1))  # mov ebx, 1
    a.emit(b"\xf3\x0f\x10\x45", _OUT)  # movss  xmm0, [ebp-8]
    a.emit(b"\x0f\x2f\x45", _AGG)  # comiss xmm0, [ebp-0xC]
    a.jcc_short(skip, "next")  # min: keep the aggregate when the member's is not smaller
    a.emit(b"\xf3\x0f\x11\x45", _AGG)  # movss [ebp-0xC], xmm0

    a.label("next")
    a.emit(b"\x8b\x3f")  # mov  edi, [edi]                            ; the next node
    a.jmp("loop")

    a.label("done")
    a.emit(b"\x85\xdb")  # test ebx, ebx
    a.jcc_short(JE, "none")
    a.emit(b"\x8b\x45", _ARG_OUT)  # mov eax, [ebp+0xC]              ; the caller's Real*
    a.emit(b"\xf3\x0f\x10\x45", _OWN)  # movss xmm0, [ebp-4]
    a.emit(b"\xf3\x0f\x59\x45", _AGG)  # mulss xmm0, [ebp-0xC]
    a.emit(b"\xf3\x0f\x11\x00")  # movss [eax], xmm0
    a.emit(b"\xb0\x01")  # mov  al, 1
    a.jmp_short("epilogue")

    # Nothing contributed anywhere: the stock answer, out pointer untouched, so the caller skips
    # its multiply exactly as it always has.
    a.label("none")
    a.emit(b"\x32\xc0")  # xor  al, al

    a.label("epilogue")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi / esi / ebx
    a.emit(b"\x8b\xe5")  # mov  esp, ebp
    a.emit(0x5D)  # pop  ebp
    a.emit(b"\xc2\x10\x00")  # ret 0x10
    return a.finish()


class HordeMemberSpeedPatch(Patch):
    """Let a battalion's pace follow the `SPEED` modifiers on its members."""

    name = "horde-member-speed"
    author = "officialNecro"
    description = (
        "A SPEED ModifierList on a battalion's members changes how fast the battalion moves, "
        "instead of doing nothing. Members are aggregated with min (the slowest sets the pace) "
        "or max; the horde's own SPEED modifier still applies and multiplies with it. No INI "
        "keyword, and nothing changes for an object with no modified members"
    )

    def __init__(self, aggregate: str = DEFAULT_AGGREGATE) -> None:
        if aggregate not in AGGREGATES:
            raise ValueError(
                f"unknown aggregate {aggregate!r}: expected one of {sorted(AGGREGATES)}"
            )
        self.aggregate = aggregate

    def __str__(self) -> str:
        return f"{self.name} ({self.aggregate})"

    def apply(self, data: bytearray) -> None:
        off = va_to_offset(data, LOCOMOTOR_SPEED_MODIFIER_CALL)
        if off is None:
            raise ValueError(
                f"{LOCOMOTOR_SPEED_MODIFIER_CALL:#010x} is not mapped - not the expected build"
            )
        self._check_anchors(data)
        section_va = allocate_section(
            data,
            SECTION_NAME,
            lambda va: build_section(va, self.aggregate),
            SECTION_CHARACTERISTICS,
        )
        apply_byte_patch(
            data,
            off,
            LOCOMOTOR_SPEED_MODIFIER_CALL_BYTES,
            _call_bytes(LOCOMOTOR_SPEED_MODIFIER_CALL, section_va),
            "Locomotor::getMaxSpeed SPEED query -> horde member-speed cave",
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
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the speed and "
                    "horde-containment paths are not this build's, so the five bytes at the "
                    "modifier query are not the call this patch means to replace"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch (an empty list == verified). Finds
        the cave by name, recomputes what it should hold from its own base VA, and compares it and
        the hook to what is on disk."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located

        problems: list[str] = []
        content = build_section(section_va, self.aggregate)
        got = bytes(data[section_off : section_off + len(content)])
        if got != content:
            problems.append(
                f"{SECTION_NAME} does not hold this patch's stub built with "
                f"--aggregate {self.aggregate}"
            )

        off = va_to_offset(data, LOCOMOTOR_SPEED_MODIFIER_CALL)
        if off is None:
            return [
                *problems,
                f"{LOCOMOTOR_SPEED_MODIFIER_CALL:#010x} is not mapped by any section",
            ]
        expected = _call_bytes(LOCOMOTOR_SPEED_MODIFIER_CALL, section_va)
        found = bytes(data[off : off + len(expected)])
        if found == LOCOMOTOR_SPEED_MODIFIER_CALL_BYTES:
            problems.append(
                f"{LOCOMOTOR_SPEED_MODIFIER_CALL:#010x} still holds the stock modifier query"
            )
        elif found != expected:
            problems.append(
                f"the SPEED query @{LOCOMOTOR_SPEED_MODIFIER_CALL:#010x}: expected "
                f"{expected.hex()}, got {found.hex()}"
            )

        for va in (LOCOMOTOR_SPEED_MODIFIER_SETUP, LOCOMOTOR_SPEED_MODIFIER_FOLD):
            anchor_off = va_to_offset(data, va)
            expected_anchor = ANCHORS[va]
            if anchor_off is None or (
                bytes(data[anchor_off : anchor_off + len(expected_anchor)]) != expected_anchor
            ):
                problems.append(f"{va:#010x} no longer holds the query it brackets")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> HordeMemberSpeedPatch | None:
        """Recognise this patch **and recover the aggregate it was applied with**, by asking each
        candidate to verify: the two differ by one branch condition inside the cave, which is what
        `verify` recomputes and compares."""
        for aggregate in AGGREGATES:
            patch = cls(aggregate)
            if not patch.verify(data):
                return patch
        return None

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--aggregate",
            choices=sorted(AGGREGATES),
            default=DEFAULT_AGGREGATE,
            help=(
                "how the members' SPEED multipliers combine into the battalion's "
                f"(default: {DEFAULT_AGGREGATE}, the slowest member sets the pace)"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> HordeMemberSpeedPatch:
        return cls(aggregate=args.aggregate)
