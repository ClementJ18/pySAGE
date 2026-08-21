"""The production-split patch: four `ModifierList` keywords that separate the things
`PRODUCTION` currently means, plus the one it never meant.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/construction-speed-modifiers.md``.

**What `PRODUCTION` is today.** Type index 13 is read at eight sites and means four different
things at once: per-tick resource income (`AutoDepositUpdate`, `TerrainResourceBehavior`, the
`SlaughterHordeContain` cash-back path, `SupplyCenterDockUpdate`), per-frame progress on
*everything* in a production queue (`ProductionUpdate::update`), and - through three more sites -
what the AI thinks a building is worth. A mod that wants a unit to train faster has to write a
modifier that also multiplies farm output.

Structure construction is the fifth thing, and `PRODUCTION` does not reach it at all: a building
under construction advances in exactly one place, the `DozerAIUpdate` build state machine, which
divides `100` and `maxHealth` by the frame count `ThingTemplate::calcTimeToBuild` returns.

**What this adds.** Four names on the end of the modifier-type table - `PRODUCTION_MONEY`,
`PRODUCTION_UNIT`, `PRODUCTION_UPGRADE`, `PRODUCTION_CONSTRUCTION` (indices 28..31) - and six
`call rel32` repointed so each site consults the keyword that belongs to it.

**`PRODUCTION` is deliberately left alone.** Each new keyword multiplies *in addition to*
whatever type 13 already contributes at that site, and an absent modifier is 1.0, so applying
this patch to an install changes nothing until INI starts using the new names. That is what makes
it cheap to test and cheap to back out; repointing the sites' existing ``push 0x0D`` immediates
instead would be one byte smaller per site and would silently change every mod already shipping
`PRODUCTION`.

**The queue is one hook for two keywords.** `ProductionUpdate::update` accrues progress for
every queue entry at one call, and the entry's kind is a dword at ``entry+0x04``: 1 = unit,
2 = upgrade, 3 = hero. The hook reads that dword and picks `PRODUCTION_UNIT` or
`PRODUCTION_UPGRADE`.

**There is no hero keyword, and kind 3 is handed straight back to the stock callee.** Scaling the
accrual cannot speed a hero up. At ``0x008A1EF3`` the engine tests the kind and routes kind 3 to a
completely different completion test: it asks the player's hero ledger at ``Player+0x758`` for a
readiness fraction (``0x00780C9F``), which is pure wall clock -
``(currentFrame - startFrame) / totalFrames`` - and never reads the accrued ``entry+0x1c``. Only
kinds 1 and 2 reach the ``comiss`` at ``0x008A1F6B`` where accrued progress becomes completion.
Measured live on 2026-08-13: a hero keyword of 5.0 drove the queue entry's percentage to 480%
while the hero still arrived on its unscaled 150-frame schedule. A hero keyword that worked would
have to divide the frame count instead, at the `calcTimeToBuild` inside ``0x00780687``
(``0x007806DF``, which feeds both the ledger's denominator and the bar's) - a different hook with
a different shape, deliberately not in this patch. So kind 3 skips the widening entirely and
tail-jumps to `getModifierMultiplier`, leaving the site behaving exactly as if it were never
hooked, rather than offering a keyword that only moves a progress bar.

**Construction reads the structure being built**, not its builder. `edi` at the hooked call is
the object going up and survives the call; the builder is only reachable through a slot in the
caller's frame, which is a fragile dependency for a factor that reads just as naturally as "an
aura over the build site makes it go up faster".

**Nothing else has to grow.** There is no array indexed by modifier type anywhere in the engine:
`ModifierList::getValue` (``0x00805268``) is a linear scan comparing a stored dword, and the
holder walk above it is type-agnostic. The one structural cost is the name table itself, which is
a NULL-terminated ``const char *[28]`` at ``0x00DA6D28`` with the next enum's list starting four
bytes past its terminator - no slack, so it is rebuilt in the cave and its two references are
repointed.
"""

from __future__ import annotations

import argparse
import struct

from sage_ini.engine import Engine, EnumDelta

from ..asm import JBE, JE, JGE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset
from .utils import name_tables

__all__ = [
    "ANCHORS",
    "HOOKS",
    "NEW_TYPES",
    "SECTION_NAME",
    "STOCK_TYPE_COUNT",
    "TABLE_FINGERPRINT",
    "TYPE_TABLE_VA",
    "ProductionSplitPatch",
    "ProductionSplitWorldbuilderPatch",
    "build_section",
]


#: `Object::getModifierMultiplier(type, Real *out, ctx, flag)` - ``__thiscall``, ``ret 0x10``,
#: returns "any modifier contributed" in ``al`` and writes the **product** through ``out``, which
#: it seeds to 1.0 on entry (``0x00805007``). That seeding is why a cave that calls it twice has
#: to keep the first result somewhere other than ``*out``.
GET_MODIFIER_MULTIPLIER = 0x0068C82D

#: `ThingTemplate::calcTimeToBuild(Player*, Object *producer, Int overrideSeconds)` -
#: ``__thiscall``, ``ret 0xC``, returns the build time in frames.
CALC_TIME_TO_BUILD = 0x0073C39E

#: The stock modifier-type name table: a NULL-terminated ``const char *[28]`` whose index 0 is the
#: `ATTRIBUTE_NONE` sentinel (which the parser also uses as "name not found"). Referenced from
#: exactly two instructions, both inside the name walk at ``0x00804CAD``.
TYPE_TABLE_VA = 0x00DA6D28
STOCK_TYPE_COUNT = 28

#: The two operands naming the table: the ``cmp [table], edi`` guard and the ``mov esi, table``
#: that starts the walk.
TABLE_REF_CMP_VA = 0x00804CB3
TABLE_REF_MOV_VA = 0x00804CBA

#: Indices whose spelling is asserted before the table is rebuilt. Four is enough to prove this is
#: the modifier table and not another name list that happens to sit at the same address in some
#: other build: the sentinel, the first real type, the one this patch is splitting, and the last.
TABLE_FINGERPRINT = {
    0: "ATTRIBUTE_NONE",
    1: "ARMOR",
    13: "PRODUCTION",
    27: "INVULNERABLE",
}

#: The existing type every new keyword multiplies alongside.
PRODUCTION_TYPE = 13

#: The new keywords, in the order they are appended to the table. Their indices are therefore
#: ``STOCK_TYPE_COUNT + position``, which is what :meth:`ProductionSplitPatch.ini_surface`
#: reports and what the cave pushes.
NEW_TYPES: tuple[str, ...] = (
    "PRODUCTION_MONEY",
    "PRODUCTION_UNIT",
    "PRODUCTION_UPGRADE",
    "PRODUCTION_CONSTRUCTION",
)
TYPE_MONEY, TYPE_UNIT, TYPE_UPGRADE, TYPE_CONSTRUCTION = (
    STOCK_TYPE_COUNT + index for index in range(len(NEW_TYPES))
)

#: `ProductionUpdate`'s queue-entry kind, at ``entry+0x04``, and the values the engine's own two
#: dispatches (``0x008A04F5`` for the total time, ``0x008A1F74`` at completion) branch on.
QUEUE_KIND_OFFSET = 0x04
QUEUE_KIND_UNIT = 1
QUEUE_KIND_UPGRADE = 2
QUEUE_KIND_HERO = 3

#: `Object::m_constructionPercent`. Not read by the cave - stated because the construction hook's
#: correctness rests on the hooked call's result being what the caller divides `100` and
#: `maxHealth` by, which the anchor window pins by carrying both divisions.
OBJECT_CONSTRUCTION_PERCENT = 0x288


#: Every hooked `call`, as ``(call VA, stock target, thunk, note)``. ``thunk`` names the cave
#: entry point, resolved once the section is laid out.
HOOKS: tuple[tuple[int, int, str, str], ...] = (
    (0x0089DC44, GET_MODIFIER_MULTIPLIER, "money", "AutoDepositUpdate income"),
    (0x0088559E, GET_MODIFIER_MULTIPLIER, "money", "TerrainResourceBehavior income"),
    (0x00883C4D, GET_MODIFIER_MULTIPLIER, "money", "SlaughterHordeContain cash back"),
    (0x008A4622, GET_MODIFIER_MULTIPLIER, "money", "SupplyCenterDockUpdate cargo value"),
    (0x008A1ED6, GET_MODIFIER_MULTIPLIER, "queue", "ProductionUpdate queue progress"),
    (0x0088DE6D, CALC_TIME_TO_BUILD, "construction", "DozerAIUpdate construction rate"),
)

#: The AI's own reading of how productive a building is: two valuation sites and one that picks
#: the object with the highest multiplier. Opt-in (``--ai-sites``) because the third **compares**
#: multipliers rather than accumulating one, so what a product means there is a balance question
#: rather than a mechanical one - and because leaving them stock only costs an AI that
#: under-values a `PRODUCTION_MONEY` building.
AI_HOOKS: tuple[tuple[int, int, str, str], ...] = (
    (0x009BB858, GET_MODIFIER_MULTIPLIER, "money", "AI building valuation"),
    (0x009BBC4F, GET_MODIFIER_MULTIPLIER, "money", "AI building valuation (second)"),
    (0x009E7594, GET_MODIFIER_MULTIPLIER, "money", "AI highest-multiplier pick"),
)


#: Byte windows the patch depends on and does not rewrite, as ``{va: expected bytes}``. Each hook
#: window carries the `call` being repointed - :meth:`ProductionSplitPatch.verify` blanks those
#: five bytes, and the two table operands, before comparing, so the same table checks a patched
#: image.
ANCHORS: dict[int, bytes] = {
    # `AutoDepositUpdate`: 1.0 seeded into the out slot, `push 0xd`, the call, then the deposit
    0x0089DC2B: bytes.fromhex(
        "f30f10050819bd00576a0133db538d45f0506a0df30f1145f0e8e4ebdeff8b4ef8e827dadeff8bf8"
    ),
    # `TerrainResourceBehavior::update`, the same shape with the out slot zeroed rather than 1.0
    0x0088558A: bytes.fromhex("0f57c06a016a008d45f0506a0d8bcff30f1145f0e88a72e0ff8b4634"),
    # the slaughter cash-back path: the call, then `*value *= multiplier`
    0x00883C35: bytes.fromhex(
        "f30f10050819bd006a01578d45e0506a0d8bcbf30f1145e0e8db8be0ff84c0740f"
        "f30f1045e0f30f5945e8f30f1145e8"
    ),
    # `SupplyCenterDockUpdate`: the call, then the `ValueMultiplier` at ModuleData+0x10
    0x008A4609: bytes.fromhex(
        "f30f10050819bd008b4ee86a01538d45e8506a0df30f1145e8e80682deff8b46e4f30f1045e8f30f5945f0"
    ),
    # `ProductionUpdate::update`: the accrual. Pins ebx as the queue entry (`+0x1c` progress,
    # `+4` kind) and the total-time call the percentage is computed against.
    0x008A1EBC: bytes.fromhex(
        "f30f10050819bd008b4ef86a016a008d4598506a0df30f114598e852a9deff"
        "f30f10431cf30f5845988b4dd453f30f11431ce8e7e5ffff837b0403"
    ),
    # the kind dispatch that gives the three queue kinds their meaning: 1 -> calcTimeToBuild,
    # 2 -> the UpgradeTemplate's own time, 3 -> the hero ledger at Player+0x758. This is what
    # entitles the queue thunk to read `entry+0x04` as a kind at all, and to treat 3 as the hero
    # case it declines to widen.
    0x008A04ED: bytes.fromhex(
        "8b4c240885c974418b51044a74274a74164a7535ff7608ff71108d8858070000"
        "e86006eeffeb1dff76088b490c50e888ecdcffeb0f8b76088b49086aff5650"
    ),
    # the construction advance: edi is the structure, the hooked call returns frames, and both
    # `100 / frames` and `maxHealth / frames` are computed from it
    0x0088DE43: bytes.fromhex(
        "f30f1087880200000f2e05dc19bd009ff6c4440f8bfa0200008b4dec8b77046aff51e80ed8dfff50"
        "8bcee82ce5eafff30f100dd888bd008b8f5c020000f30f2ac0f30f1145e4f30f5ec8"
        "f30f108788020000f30f58c1f30f1187880200008b316a00894df0ff561cd875e4518b4df0d91c24ff9684"
    ),
    # the name walk: both table operands, the NULL terminator test, and the "index 0 == not
    # found" contract the new names rely on
    0x00804CAD: bytes.fromhex(
        "565733ff393d286dda007423be286dda008bc6ff74240cff30e87582230085c05959"
        "741283c60447833e008bc675e433c05f5ec204008bc7eb"
    ),
    # `Object::hasModifier` and `Object::getModifierMultiplier` - the thunk the cave forwards to,
    # and its `ret 0x10`
    0x0068C818: bytes.fromhex(
        "e889fcffff85c0750532c0c20c008bc8e90c871700e874fcffff85c0750532c0c210008bc8e9bd871700"
    ),
    # `calcTimeToBuild`'s head: `__thiscall`, three args, BuildTime read from template+0x4EC
    0x0073C39E: bytes.fromhex(
        "558bec837d10ff5356578bf1750fe88ffcfffff30f1080ec040000eb05f30f2a4510"
    ),
    # `ModifierList::getValue`: the linear scan over 0x14-byte entries comparing the type dword.
    # No table is indexed by type, which is why a new index needs nothing but a name.
    0x00805268: bytes.fromhex(
        "558bec568b318b490457eb0a8b063b4508740f83c6143bf175f232c05f5e5dc20c00837d10007428"
    ),
}

#: The AI windows, checked only when those sites are hooked.
AI_ANCHORS: dict[int, bytes] = {
    0x009BB832: bytes.fromhex(
        "6a016a008d4508f30f58d1f30f58d0f30f10050819bd00506a0d8bcff30f1155d0f30f114508"
        "e8d00fcdfff30f1045080f2f059c88bd00f30f59059c86bd00"
    ),
    0x009BBC29: bytes.fromhex(
        "6a016a008d4508f30f58d1f30f58d0f30f10050819bd00506a0d8bcff30f1155d0f30f114508"
        "e8d90bcdfff30f1045080f2f059c88bd00f30f59059c86bd00"
    ),
    0x009E757B: bytes.fromhex(
        "f30f10050819bd006a016a008d45fc506a0d8bcef30f1145fce89452cafff30f1045fc0f2f45f8"
    ),
}


SECTION_NAME = ".prodsp"  # 7 chars: the PE name field is 8 bytes and truncates silently
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. The rebuilt name table and
# the two float constants live in the same section as the code that reads them.
SECTION_CHARACTERISTICS = 0xE0000060

_ZERO_F = struct.pack("<f", 0.0)
_ONE_F = struct.pack("<f", 1.0)


def _call_bytes(from_va: int, to_va: int) -> bytes:
    """The five bytes of ``call rel32`` sited at ``from_va``."""
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


def _read_c_string(data: bytes | bytearray, va: int, limit: int = 64) -> str:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"VA 0x{va:08x} is not mapped")
    end = data.index(0, off, off + limit)
    return bytes(data[off:end]).decode("ascii", "replace")


def read_stock_table(data: bytes | bytearray) -> list[int]:
    """The stock table's ``STOCK_TYPE_COUNT`` name pointers, checked for shape and spelling.

    Raises if the table is not the one this patch expects: a pointer that is zero before the end,
    a terminator that is not zero, or a fingerprinted index that does not spell what it should.
    Reading the *names* rather than only the pointers is what makes the check meaningful - the
    pointers themselves are just plausible addresses, and ``.data`` holds some 135 identical
    copies of this array for the linker's own reasons."""
    off = va_to_offset(data, TYPE_TABLE_VA)
    if off is None:
        raise ValueError(f"the modifier-type table at 0x{TYPE_TABLE_VA:08x} is not mapped")
    pointers = list(struct.unpack_from(f"<{STOCK_TYPE_COUNT + 1}I", data, off))
    if pointers[STOCK_TYPE_COUNT] != 0:
        raise ValueError(
            f"the modifier-type table is not {STOCK_TYPE_COUNT} entries long: "
            f"index {STOCK_TYPE_COUNT} is 0x{pointers[STOCK_TYPE_COUNT]:08x}, expected the "
            "NULL terminator"
        )
    if 0 in pointers[:STOCK_TYPE_COUNT]:
        raise ValueError("the modifier-type table terminates early")
    for index, expected in TABLE_FINGERPRINT.items():
        got = _read_c_string(data, pointers[index])
        if got != expected:
            raise ValueError(f"modifier type {index} spells {got!r}, expected {expected!r}")
    return pointers[:STOCK_TYPE_COUNT]


def _emit_widen(a: Asm, push_type: bytes) -> None:
    """The body both widening thunks share: ask for the stock type, ask for the new one, and
    hand the caller the product of the two.

    Entered by a repointed `call` to `getModifierMultiplier`, so the four arguments are still on
    the stack exactly as the site pushed them and ``ecx`` is the `Object`. Leaves through the same
    ``ret 0x10`` the stock callee would have, with ``al`` set if **either** query contributed.

    ``push_type`` is the one instruction that differs: an immediate for the money sites, a frame
    slot for the queue site, which resolves its type from the entry kind first."""
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov  ebp, esp        ; +8 type, +0xc out, +0x10 ctx, +0x14 flag
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    a.emit(b"\x83\xec\x08")  # sub  esp, 8      ; -0x10 saved product, -0x14 the new type
    a.emit(b"\x8b\xf1")  # mov  esi, ecx        ; the Object, clobbered by the first call
    a.emit(b"\x8b\x7d\x0c")  # mov  edi, [ebp+0xc]  ; the caller's out slot

    a.emit(b"\xff\x75\x14")  # push [ebp+0x14]  ; flag
    a.emit(b"\xff\x75\x10")  # push [ebp+0x10]  ; ctx
    a.emit(0x57)  # push edi                    ; out
    a.emit(b"\xff\x75\x08")  # push [ebp+8]     ; the stock type, unchanged
    a.emit(b"\x8b\xce")  # mov  ecx, esi
    a.call_absolute(GET_MODIFIER_MULTIPLIER)
    a.emit(b"\x8a\xd8")  # mov  bl, al
    # `*out` is re-seeded to 1.0 by the next call, so the first product goes to a local.
    a.emit(b"\x8b\x07")  # mov  eax, [edi]
    a.emit(b"\x89\x45\xf0")  # mov  [ebp-0x10], eax

    a.emit(b"\xff\x75\x14")  # push [ebp+0x14]
    a.emit(b"\xff\x75\x10")  # push [ebp+0x10]
    a.emit(0x57)  # push edi
    a.emit(push_type)
    a.emit(b"\x8b\xce")  # mov  ecx, esi
    a.call_absolute(GET_MODIFIER_MULTIPLIER)
    a.emit(b"\x0a\xd8")  # or   bl, al

    a.emit(b"\xf3\x0f\x10\x07")  # movss xmm0, [edi]
    a.emit(b"\xf3\x0f\x59\x45\xf0")  # mulss xmm0, [ebp-0x10]
    a.emit(b"\xf3\x0f\x11\x07")  # movss [edi], xmm0
    a.emit(b"\x0f\xb6\xc3")  # movzx eax, bl
    a.emit(b"\x83\xc4\x08")  # add  esp, 8
    a.emit(0x5F)  # pop  edi
    a.emit(0x5E)  # pop  esi
    a.emit(0x5B)  # pop  ebx
    a.emit(0x5D)  # pop  ebp
    a.emit(b"\xc2\x10\x00")  # ret  0x10


def _build_money(base_va: int) -> bytes:
    """The income thunk: `PRODUCTION` times `PRODUCTION_MONEY`, for the four deposit sites (and
    the AI's valuation sites, which read the same thing)."""
    a = Asm(base_va)
    _emit_widen(a, bytes([0x6A, TYPE_MONEY]))  # push TYPE_MONEY
    return a.finish()


def _build_queue(base_va: int) -> bytes:
    """The queue thunk: the same widening, with the second type chosen from the entry kind.

    ``ebx`` is `ProductionUpdate::update`'s queue entry and is callee-saved, so it still holds the
    entry here - the kind is read before anything is clobbered and parked in the frame slot the
    shared body pushes. A kind the engine does not currently produce falls to `PRODUCTION_UNIT`,
    which is the queue's own default shape.

    **Kind 3 leaves before the prologue.** A hero's completion is decided by the player's hero
    ledger rather than by this accrual (see the module docstring), so there is no keyword that
    could honestly apply here. The test is the first thing the thunk does, while the arguments and
    ``ecx`` are still exactly as the site pushed them, and the exit is a ``jmp`` rather than a
    ``call`` so the stock callee returns straight to the site - byte for byte the behaviour of an
    unhooked engine."""
    a = Asm(base_va)
    a.emit(b"\x83\x7b", QUEUE_KIND_OFFSET, QUEUE_KIND_HERO)  # cmp dword [ebx+4], 3
    a.jcc(JNE, "widen")
    a.jmp_absolute(GET_MODIFIER_MULTIPLIER)  # a hero: nothing to widen, tail-call the stock callee

    a.label("widen")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov  ebp, esp
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    a.emit(b"\x83\xec\x08")  # sub  esp, 8
    a.emit(b"\x8b\x43", QUEUE_KIND_OFFSET)  # mov eax, [ebx+4]   ; the queue entry's kind
    a.emit(b"\x83\xf8", QUEUE_KIND_UPGRADE)  # cmp eax, 2
    a.jcc_short(JE, "upgrade")
    a.emit(b"\xb8", struct.pack("<I", TYPE_UNIT))  # mov eax, TYPE_UNIT
    a.jmp_short("chosen")
    a.label("upgrade")
    a.emit(b"\xb8", struct.pack("<I", TYPE_UPGRADE))
    a.label("chosen")
    a.emit(b"\x89\x45\xec")  # mov [ebp-0x14], eax

    # The shared body, minus the prologue this thunk has already emitted for itself. It is
    # assembled against a base **behind** the current address by exactly that prologue, so the
    # bytes that survive the trim land on the addresses their `call rel32` displacements were
    # computed for.
    tail = Asm(a.va - _WIDEN_PROLOGUE)
    _emit_widen(tail, b"\xff\x75\xec")  # push [ebp-0x14]
    a.emit(tail.finish()[_WIDEN_PROLOGUE:])
    return a.finish()


def _widen_prologue_length() -> int:
    """How many bytes of :func:`_emit_widen` are the prologue the queue thunk emits itself
    (through the ``sub esp, 8``). Derived rather than counted, so it cannot drift from the body."""
    probe = Asm(0)
    _emit_widen(probe, b"\x6a\x00")
    return probe.finish().index(b"\x83\xec\x08") + 3


_WIDEN_PROLOGUE = _widen_prologue_length()


def _build_construction(base_va: int, zero_va: int) -> bytes:
    """The construction thunk: divide the build time by `PRODUCTION_CONSTRUCTION`.

    Entered by the repointed `call` to `calcTimeToBuild`, so the three arguments are on the stack
    and ``ecx`` is the `ThingTemplate`; leaves through the same ``ret 0xC``. ``edi`` is the
    structure going up - the caller loaded it before the call and it is callee-saved.

    The frame count is what the caller divides both `100` and `maxHealth` by, so scaling it here
    scales the progress bar and the health ramp together. A multiplier that is not greater than
    zero (or a NaN) is ignored rather than trusted, and the result never goes below one frame:
    the caller divides by it."""
    a = Asm(base_va)
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov  ebp, esp       ; +8 player, +0xc producer, +0x10 override
    a.emit(0x53)  # push ebx
    a.emit(b"\x83\xec\x04")  # sub  esp, 4     ; -8, the multiplier
    # ecx still holds the ThingTemplate: nothing above touches it.
    a.emit(b"\xff\x75\x10")  # push [ebp+0x10]
    a.emit(b"\xff\x75\x0c")  # push [ebp+0xc]
    a.emit(b"\xff\x75\x08")  # push [ebp+8]
    a.call_absolute(CALC_TIME_TO_BUILD)
    a.emit(b"\x8b\xd8")  # mov  ebx, eax       ; frames, the value we may scale

    a.emit(b"\x85\xff")  # test edi, edi
    a.jcc(JE, "done")  # no structure in hand: leave the stock answer alone
    a.emit(b"\xc7\x45\xf8", _ONE_F)  # mov dword [ebp-8], 1.0
    a.emit(b"\x6a\x01")  # push 1              ; flag, as every stock site passes
    a.emit(b"\x6a\x00")  # push 0              ; ctx
    a.emit(b"\x8d\x45\xf8")  # lea  eax, [ebp-8]
    a.emit(0x50)  # push eax
    a.emit(b"\x6a", TYPE_CONSTRUCTION)  # push TYPE_CONSTRUCTION
    a.emit(b"\x8b\xcf")  # mov  ecx, edi       ; the structure being built
    a.call_absolute(GET_MODIFIER_MULTIPLIER)

    a.emit(b"\xf3\x0f\x10\x45\xf8")  # movss xmm0, [ebp-8]
    a.emit(b"\x0f\x2f\x05", struct.pack("<I", zero_va))  # comiss xmm0, [zero]
    a.jcc(JBE, "done")  # <= 0, or unordered: not a multiplier
    a.emit(b"\xf3\x0f\x2a\xcb")  # cvtsi2ss xmm1, ebx
    a.emit(b"\xf3\x0f\x5e\xc8")  # divss xmm1, xmm0
    a.emit(b"\xf3\x0f\x2c\xc1")  # cvttss2si eax, xmm1
    a.emit(b"\x83\xf8\x01")  # cmp  eax, 1
    a.jcc_short(JGE, "store")
    a.emit(b"\xb8", struct.pack("<I", 1))  # mov eax, 1
    a.label("store")
    a.emit(b"\x8b\xd8")  # mov  ebx, eax

    a.label("done")
    a.emit(b"\x8b\xc3")  # mov  eax, ebx
    a.emit(b"\x83\xc4\x04")  # add  esp, 4
    a.emit(0x5B)  # pop  ebx
    a.emit(0x5D)  # pop  ebp
    a.emit(b"\xc2\x0c\x00")  # ret  0xc
    return a.finish()


def build_section(base_va: int, stock_pointers: list[int]) -> tuple[bytes, dict[str, int], int]:
    """``(section content, {thunk name: VA}, rebuilt table VA)`` for a cave based at ``base_va``.

    The layout is data first, code second, so the table and the constants sit at addresses the
    code can name and :meth:`ProductionSplitPatch.verify` can find without knowing how long the
    code is: two floats, then the rebuilt ``STOCK_TYPE_COUNT + len(NEW_TYPES)`` pointer table and
    its terminator, then the new name strings the tail of that table points at, then the thunks.
    """
    zero_va = base_va
    table_va = base_va + len(_ZERO_F) + len(_ONE_F)
    table_entries = STOCK_TYPE_COUNT + len(NEW_TYPES) + 1  # + the NULL terminator
    strings_va = table_va + table_entries * 4

    strings = bytearray()
    new_pointers = []
    for name in NEW_TYPES:
        new_pointers.append(strings_va + len(strings))
        strings += name.encode("ascii") + b"\x00"

    table = struct.pack(f"<{table_entries}I", *stock_pointers, *new_pointers, 0)
    data = _ZERO_F + _ONE_F + table + bytes(strings)

    thunks: dict[str, int] = {}
    code = bytearray()
    for thunk_name, build in (
        ("money", _build_money),
        ("queue", _build_queue),
        ("construction", lambda va: _build_construction(va, zero_va)),
    ):
        thunk_va = base_va + len(data) + len(code)
        thunks[thunk_name] = thunk_va
        code += build(thunk_va)

    return data + bytes(code), thunks, table_va


class ProductionSplitPatch(Patch):
    """Split `PRODUCTION` into four keywords: money, unit, upgrade and construction."""

    name = "production-split"
    author = "officialNecro"
    description = (
        "PRODUCTION_MONEY / _UNIT / _UPGRADE / _CONSTRUCTION modifiers, each affecting only its "
        "own share of what PRODUCTION means today. Name them on a ModifierList's Modifier line; "
        "PRODUCTION itself is untouched and still stacks, so nothing changes until INI uses the "
        "new names"
    )

    def __init__(self, ai_sites: bool = False) -> None:
        self.ai_sites = bool(ai_sites)

    def __str__(self) -> str:
        return f"{self.name} (ai-sites={'yes' if self.ai_sites else 'no'})"

    @property
    def hooks(self) -> tuple[tuple[int, int, str, str], ...]:
        return HOOKS + AI_HOOKS if self.ai_sites else HOOKS

    @property
    def anchors(self) -> dict[int, bytes]:
        """Both tables, always. The AI windows carry the three `call`s this patch repoints only
        when asked, and :meth:`_anchor_problems` blanks a hooked `call` before comparing - so
        checking them unconditionally is what makes the two configurations tell each other apart:
        with ``ai_sites`` off, those windows assert the sites are **still stock**, which is
        otherwise unverifiable and would let `detect` report the wrong configuration."""
        return {**ANCHORS, **AI_ANCHORS}

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        stock = read_stock_table(data)
        section_va = allocate_section(
            data,
            SECTION_NAME,
            lambda va: build_section(va, stock)[0],
            SECTION_CHARACTERISTICS,
        )
        _content, thunks, table_va = build_section(section_va, stock)
        for file_off, old, new, note in self._edits(data, thunks, table_va):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch (an empty list == verified).

        The rebuilt table is read back out of the cave rather than recomputed from the stock
        table, because the stock table's pointers are exactly what the patch copies - recomputing
        from them would only ever confirm the copy against itself. So: the cave's table must keep
        the stock names in their stock indices, spell the four new ones after them, and terminate;
        every hooked `call` must land on the thunk it belongs to; and the walk must name the
        cave's table rather than the stock one."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located

        problems: list[str] = []
        try:
            stock = self._stock_pointers_from_cave(data, section_va)
            content, thunks, table_va = build_section(section_va, stock)
            edits = self._edits(data, thunks, table_va)
        except (ValueError, struct.error, IndexError) as exc:
            return [f"cannot recompute the expected cave (wrong build?): {exc}"]

        got = bytes(data[section_off : section_off + len(content)])
        if got != content:
            problems.append(
                f"{SECTION_NAME} does not hold the expected table and three thunks "
                "(the cave differs, or was built for another base address)"
            )
        for file_off, _old, new, note in edits:
            found = bytes(data[file_off : file_off + len(new)])
            if found != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {found.hex()}")

        problems += self._table_problems(data, table_va)
        problems += self._anchor_problems(data, patched=True)
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> ProductionSplitPatch | None:
        """Recover the patch **with its parameter**: the AI sites are opt-in, so a probe built
        with the default reports an image that hooks them as not carrying the patch at all."""
        for ai_sites in (False, True):
            try:
                patch = cls(ai_sites=ai_sites)
                if not patch.verify(data):
                    return patch
            except (ValueError, KeyError, IndexError, TypeError, struct.error):
                continue
        return None

    def ini_surface(self) -> Engine:
        """The four tokens this patch adds to the `ModifierList` `Modifier` name table, at the
        indices the rebuilt table gives them. Multiplicative, like the `PRODUCTION` they split:
        the engine decides that per call site, and every site this patch touches multiplies."""
        return Engine(
            enum_members=tuple(
                EnumDelta("ModifierType", name, STOCK_TYPE_COUNT + index, self.name)
                for index, name in enumerate(NEW_TYPES)
            )
        )

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--ai-sites",
            action="store_true",
            help="also let the AI's three valuation sites read PRODUCTION_MONEY (default: no, "
            "which leaves an AI that under-values a PRODUCTION_MONEY building)",
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> ProductionSplitPatch:
        return cls(ai_sites=args.ai_sites)

    def _stock_pointers_from_cave(self, data: bytes | bytearray, section_va: int) -> list[int]:
        """The stock name pointers as the cave's own rebuilt table records them."""
        table_va = section_va + len(_ZERO_F) + len(_ONE_F)
        off = va_to_offset(data, table_va)
        if off is None:
            raise ValueError(f"the rebuilt table at 0x{table_va:08x} is not mapped")
        return list(struct.unpack_from(f"<{STOCK_TYPE_COUNT}I", data, off))

    def _table_problems(self, data: bytes | bytearray, table_va: int) -> list[str]:
        """What the rebuilt table has to spell: the fingerprinted stock names still at their stock
        indices, and the four new ones after them."""
        problems: list[str] = []
        off = va_to_offset(data, table_va)
        if off is None:
            return [f"the rebuilt table at 0x{table_va:08x} is not mapped"]
        total = STOCK_TYPE_COUNT + len(NEW_TYPES)
        pointers = struct.unpack_from(f"<{total + 1}I", data, off)
        if pointers[total] != 0:
            problems.append("the rebuilt modifier-type table is not NULL-terminated")
        expected = dict(TABLE_FINGERPRINT)
        expected.update({STOCK_TYPE_COUNT + index: name for index, name in enumerate(NEW_TYPES)})
        for index, name in expected.items():
            try:
                got = _read_c_string(data, pointers[index])
            except (ValueError, IndexError) as exc:
                problems.append(f"modifier type {index} is unreadable: {exc}")
                continue
            if got != name:
                problems.append(f"modifier type {index} spells {got!r}, expected {name!r}")
        return problems

    def _edits(
        self, data: bytes | bytearray, thunks: dict[str, int], table_va: int
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte range this patch rewrites: one `call rel32` displacement per hook, and the
        two operands that name the modifier-type name table."""
        edits: list[tuple[int, bytes, bytes, str]] = []
        for call_va, stock_va, thunk, note in self.hooks:
            off = va_to_offset(data, call_va)
            if off is None:
                raise ValueError(f"{note}: VA 0x{call_va:08x} is not mapped")
            edits.append(
                (
                    off,
                    _call_bytes(call_va, stock_va),
                    _call_bytes(call_va, thunks[thunk]),
                    f"{note} -> {thunk} thunk",
                )
            )
        for ref_va, note in (
            (TABLE_REF_CMP_VA, "modifier-name walk: the empty-table guard"),
            (TABLE_REF_MOV_VA, "modifier-name walk: the table it scans"),
        ):
            off = va_to_offset(data, ref_va)
            if off is None:
                raise ValueError(f"{note}: VA 0x{ref_va:08x} is not mapped")
            edits.append(
                (
                    off,
                    struct.pack("<I", TYPE_TABLE_VA),
                    struct.pack("<I", table_va),
                    note,
                )
            )
        return edits

    def _anchor_problems(self, data: bytes | bytearray, patched: bool = False) -> list[str]:
        """Everything the patch depends on and does not rewrite.

        The hook windows say each repointed `call` is the one inside the function this patch
        thinks it is, and carry the surrounding arithmetic that gives its result meaning - the
        queue window pins ``ebx`` as the entry and its kind field, the construction window pins
        both divisions by the frame count. The rest say the modifier system still works the way
        a new type index depends on: names resolved by a NULL-terminated walk, values found by a
        linear scan rather than an indexed table.

        ``patched`` blanks the bytes this patch rewrites, which is what lets the same table check
        an already-patched image."""
        rewritten = [(call_va, 5) for call_va, _stock, _thunk, _note in self.hooks]
        rewritten += [(TABLE_REF_CMP_VA, 4), (TABLE_REF_MOV_VA, 4)]

        problems: list[str] = []
        for va, expected in self.anchors.items():
            off = va_to_offset(data, va)
            if off is None:
                problems.append(f"anchor 0x{va:08x} is not mapped - not the expected build")
                continue
            got = bytearray(data[off : off + len(expected)])
            want = bytearray(expected)
            if patched:
                for site_va, width in rewritten:
                    at = site_va - va
                    if 0 <= at <= len(expected) - width:
                        got[at : at + width] = want[at : at + width] = b"\x00" * width
            if bytes(got) != bytes(want):
                problems.append(
                    f"anchor 0x{va:08x}: expected {bytes(want).hex()}, got {bytes(got).hex()}"
                )
        return problems

    def _check_anchors(self, data: bytes | bytearray) -> None:
        problems = self._anchor_problems(data)
        if problems:
            joined = "; ".join(problems)
            raise ValueError(f"production-split: this is not the expected build: {joined}")


# The Worldbuilder half.
#
# The editor parses `attributemodifier.ini` too, and `Modifier = <ModifierType> <value>` resolves
# its first token through Worldbuilder's own copy of the type name table. A name that copy does not
# hold is an unknown token in a lookup, which throws, and a throw during INI load ends the editor.
#
# Worldbuilder's table is at `0x022343E0` and is **terminator-driven**, exactly like `game.dat`'s:
#
#     00e983a4  cmp dword [eax*4 + 0x022343E0], 0   ; walk to the NULL
#     00e983ac  je  0x00E983D3
#     00e983b5  mov eax, [edx*4 + 0x022343E0]       ; else compare this name
#     00e983bd  call 0x016C37DE                     ; stricmp
#
# so there is **no count to raise** - the only two references in the image are the two above, both
# inside that one loop. Relocating the table and repointing them is the whole patch, which makes
# this the smallest of the Worldbuilder twins.
#
# Scope: parsing only. The editor gains no production behaviour and needs none; this exists so the
# object and modifier data loads.

#: Worldbuilder's own copy of the `ModifierType` name table.
WORLDBUILDER_TYPE_TABLE_VA = 0x022343E0

#: Both references, as ``(operand VA, the bytes before it)``. Both sit in the single lookup loop -
#: the terminator test and the name fetch - so asserting the encoding pins them to that loop.
WORLDBUILDER_TABLE_REF_SITES = (
    (0x00E983A7, bytes.fromhex("833c85")),  # cmp dword [eax*4 + <table>], 0
    (0x00E983B8, bytes.fromhex("8b0495")),  # mov eax, [edx*4 + <table>]
)

#: Names at these indices fingerprint the build far more tightly than the count alone.
WORLDBUILDER_TABLE_FINGERPRINT = {
    0: "ATTRIBUTE_NONE",
    1: "ARMOR",
    STOCK_TYPE_COUNT - 1: "INVULNERABLE",
}

#: The PE section name field is 8 bytes and truncates silently.
WORLDBUILDER_SECTION_NAME = ".wbprod"

# CNT_INITIALIZED_DATA | MEM_READ - a pointer table and four strings, no code.
_WORLDBUILDER_CHARACTERISTICS = 0x40000040


class ProductionSplitWorldbuilderPatch(Patch):
    """Teach **Worldbuilder** the four production modifier types.

    **This patch targets `Worldbuilder.exe`, not `game.dat`.** It is the authoring half of
    `production-split`; give both binaries the same four names, since the index is what a parsed
    modifier stores.
    """

    name = "production-split-wb"
    author = "officialNecro"
    description = (
        "Worldbuilder.exe (not game.dat): add the four PRODUCTION_* ModifierType names to the "
        "editor's own name table, so attribute modifiers using them parse instead of throwing on "
        "an unknown token and ending the editor's load. Pass the same names given to game.dat's "
        "production-split; the editor gains no production behaviour, only the ability to read it"
    )

    def __init__(self, types: tuple[str, ...] = NEW_TYPES):
        self.types = tuple(types)
        for name in self.types:
            name_tables.validate_name(name, "modifier type name")

    def __str__(self) -> str:
        return f"{self.name} ({', '.join(self.types)})"

    def apply(self, data: bytearray) -> None:
        name_tables.check_not_rebased(data)
        table = self._read(data)
        for name in self.types:
            if table.index_of(data, name) is not None:
                raise ValueError(f"{name!r} is already a modifier type in this Worldbuilder")
        if len(set(self.types)) != len(self.types):
            raise ValueError(f"duplicate names in {list(self.types)}")

        section_va = allocate_section(
            data,
            WORLDBUILDER_SECTION_NAME,
            lambda base_va: name_tables.layout(table.pointers, self.types, base_va)[0],
            _WORLDBUILDER_CHARACTERISTICS,
        )
        for file_off, old, new, note in self._edits(data, table, section_va):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, WORLDBUILDER_SECTION_NAME)
        if located is None:
            return [f"no {WORLDBUILDER_SECTION_NAME} section: the file does not carry this patch"]
        section_va, _section_off, _vsize = located
        try:
            names = self._read_names(data, section_va)
        except (ValueError, struct.error) as exc:
            return [f"cannot read back the {WORLDBUILDER_SECTION_NAME} cave (wrong build?): {exc}"]

        problems: list[str] = []
        added = len(self.types)
        if tuple(names[-added:]) != self.types:
            problems.append(
                f"the rebuilt type table ends {names[-added:]}, expected {list(self.types)}"
            )
        for va, _prefix in WORLDBUILDER_TABLE_REF_SITES:
            off = _wb_offset(data, va)
            got = bytes(data[off : off + 4])
            if got != struct.pack("<I", section_va):
                problems.append(
                    f"modifier type table ref @0x{va:08x} holds {got.hex()}, "
                    f"expected 0x{section_va:08x}"
                )
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> Patch | None:
        """Recognise this patch **and recover the names it was applied with**."""
        located = find_section(data, WORLDBUILDER_SECTION_NAME)
        if located is None:
            return None
        try:
            names = cls._read_names(data, located[0])
            if len(names) <= STOCK_TYPE_COUNT:
                return None
            patch = cls(types=tuple(names[STOCK_TYPE_COUNT:]))
        except (ValueError, IndexError, struct.error):
            return None
        return None if patch.verify(data) else patch

    @staticmethod
    def _read(data: bytes | bytearray) -> name_tables.NameTable:
        """The live table, taken from the references rather than from the stock constant."""
        bases = set()
        for va, prefix in WORLDBUILDER_TABLE_REF_SITES:
            off = _wb_offset(data, va)
            got = bytes(data[off - len(prefix) : off])
            if got != prefix:
                raise ValueError(
                    f"modifier type table ref @0x{va:08x} is encoded as {got.hex()}, expected "
                    f"{prefix.hex()} - not the expected build"
                )
            bases.add(struct.unpack_from("<I", data, off)[0])
        if len(bases) != 1:
            raise ValueError(f"the modifier type table refs disagree: {[hex(b) for b in bases]}")
        base_va = bases.pop()
        pointers = name_tables.read_terminated(
            data, base_va, "Worldbuilder modifier type table", limit=256
        )
        if len(pointers) < STOCK_TYPE_COUNT:
            raise ValueError(
                f"the modifier type table holds {len(pointers)} names, below the stock "
                f"{STOCK_TYPE_COUNT}"
            )
        name_tables.check_fingerprint(
            data, pointers, WORLDBUILDER_TABLE_FINGERPRINT, "Worldbuilder modifier type"
        )
        return name_tables.NameTable(base_va=base_va, pointers=pointers)

    @staticmethod
    def _read_names(data: bytes | bytearray, base_va: int) -> list[str]:
        pointers = name_tables.read_terminated(
            data, base_va, "Worldbuilder modifier type table", limit=256
        )
        names = [name_tables.read_cstring(data, pointer) for pointer in pointers]
        if any(entry is None for entry in names):
            raise ValueError("a modifier type entry points at unmapped memory")
        return [entry for entry in names if entry is not None]

    def _edits(
        self, data: bytes | bytearray, table: name_tables.NameTable, section_va: int
    ) -> list[tuple[int, bytes, bytes, str]]:
        """The two reference edits. There is no count edit: the lookup walks to the terminator."""
        return name_tables.ref_edits(
            data,
            [va for va, _prefix in WORLDBUILDER_TABLE_REF_SITES],
            table.base_va,
            section_va,
            "Worldbuilder modifier type table",
        )


def _wb_offset(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"VA 0x{va:08x} is not mapped - not the expected build")
    return off
