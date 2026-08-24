"""The rebuild-hole construction patch: a structure destroyed while it is being rebuilt leaves
its rebuild hole behind again, instead of vanishing for good.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/rebuild-hole-construction.md``.

**The defect.** A creep lair's whole loop hangs off its hole. `RebuildHoleExposeDie` puts a hole
where the lair stood; the hole's `CreateObjectDie` is what pays out treasure when a player breaks
it; and if nobody breaks it, `RebuildHoleBehavior` puts the lair back and the hole retires with
DeathType `FADED` (`REBUILD_HOLE_SELF_KILL`) so that retiring pays nothing. Break the lair, get a
hole. Break the hole, get treasure. Leave it alone, get the lair back.

The loop has one hole in it, at `REBUILD_HOLE_CONSTRUCTION_GATE`. `RebuildHoleExposeDie::onDie`
refuses to create anything when the dying object is `UNDER_CONSTRUCTION` — and the object a hole
rebuilds is `UNDER_CONSTRUCTION` for the whole time it is rising, which is precisely the state
`RebuildHoleBehavior::update` keys its own babysitting on. So a lair killed between "the hole
started rebuilding it" and "the rebuild finished" leaves nothing: the old hole was already
destroyed the frame the rebuild began, and no new one is made. The lair is gone permanently, and
with it every future payout, because the treasure was never on the lair to begin with.

**What this does.** Erases those six bytes. The gate's two neighbours — the "one particular
player owns it" test at `0x00889AE7` and the per-player predicate at `0x00889AFD` — are left
stock, as is everything downstream, which reads only the dying object's position, angle, team, id
and template and so behaves identically for a half-built lair and a finished one.

**The rule moves into the INI rather than disappearing.** Every die module opens with
`DIE_MODULE_IS_APPLICABLE`, whose shared filter already evaluates the module's `ExemptStatus`
against the dying object's live `ObjectStatus` bits — `UNDER_CONSTRUCTION` among them. So an
object that wants the stock behaviour back writes it::

    Behavior = RebuildHoleExposeDie ModuleTag_ExposeDie
        ExemptStatus = SOLD UNDER_CONSTRUCTION
        HoleName     = WargLairHole
        ...
    End

That is the opt-out, and it is worth knowing about, because the patch is global: it reaches every
object with a `RebuildHoleExposeDie`, including the Goblin faction's own lairs, whose *initial*
construction becomes hole-leaving too. Whether that is wanted is a data decision, and this is
where a mod makes it.

**Why the branch is deleted rather than narrowed.** "Rebuilt, not placed" has no discriminator to
test. `RECONSTRUCTING` (status 21) is the flag that would name it exactly — the engine reads it as
"this one was never paid for" when suppressing sell refunds — but no call to `Object::setStatus`
in the image ever *sets* it; it is cleared in three places and set in none. The rebuilt
structure's producer is the hole (`0x00886B27`), but that is stored as an `ObjectID` and the hole
is dead by the time the structure dies, so it no longer resolves.

**Every peer must run the same patched binary.** Creating an object is logic state, so a patched
and an unpatched client diverge the first time anybody kills a rebuilding structure, and replays
do not cross. That is the same requirement `production-condition` and `multi-execute-gate` carry.

**Composition.** No cave and nothing read from another patch's output: six bytes rewritten in
place, at an address no other bundled patch touches — they sit at ``0x0079``, ``0x008A``,
``0x0094``, ``0x009A`` and ``0x00DA``. Order-independent with everything.

**Runtime caveat (see docs §6).** Confirmed on a running game: the hole *is* created, so the fix
works as far as this patch goes. But ``onDie`` stamps the hole with the dying object's live
position, and a lair killed mid-rebuild has already been sunk by its ``StructureCollapseUpdate``
(``CollapseHeight``), so the hole spawns ~120 units underground — buried, unclickable, un-lootable,
though it still rebuilds the lair. Fixing that (snap the hole's Z to terrain height) is a separate
follow-up patch; the claim above that everything downstream "behaves identically for a half-built
lair and a finished one" is wrong on exactly this point — the *position* differs.
"""

from __future__ import annotations

from ..addresses import (
    DIE_MODULE_IS_APPLICABLE,
    DIE_MODULE_IS_APPLICABLE_ENTRY,
    DIE_MUX_IS_APPLICABLE,
    DIE_MUX_IS_APPLICABLE_ENTRY,
    REBUILD_HOLE_CONSTRUCTION_GATE,
    REBUILD_HOLE_CONSTRUCTION_GATE_BYTES,
    REBUILD_HOLE_CONSTRUCTION_TEST,
    REBUILD_HOLE_CONSTRUCTION_TEST_BYTES,
    REBUILD_HOLE_ON_DIE,
    REBUILD_HOLE_ON_DIE_ENTRY,
    REBUILD_HOLE_SELF_KILL,
    REBUILD_HOLE_SELF_KILL_BYTES,
    REBUILD_HOLE_START_REBUILD,
    REBUILD_HOLE_START_REBUILD_BYTES,
)
from ..patcher import Patch
from ..utils import apply_byte_patch, va_to_offset

__all__ = [
    "ANCHORS",
    "HOOK_ORIGINAL",
    "HOOK_REPLACEMENT",
    "HOOK_VA",
    "RebuildHoleConstructionPatch",
]

HOOK_VA = REBUILD_HOLE_CONSTRUCTION_GATE
HOOK_ORIGINAL = REBUILD_HOLE_CONSTRUCTION_GATE_BYTES

#: A single six-byte ``nop word ptr [eax+eax]`` rather than six ``0x90``s. Both fall through
#: identically, but one instruction is what the site now *is* - a disassembler, and `verify`,
#: read one erased branch instead of six pad bytes that could equally be leftovers.
HOOK_REPLACEMENT = bytes.fromhex("660f1f440000")

#: The first bytes at each address that has to still mean what the patch assumes, as a
#: ``{va: bytes}`` map. Nothing here is written; they are asserted before the one edit, so a
#: build whose layout moved fails loudly rather than erasing whatever branch now sits at
#: `HOOK_VA`. `onDie`'s prologue and the status test pin the function and the branch's subject;
#: the die filter pins the `ExemptStatus` opt-out this patch's contract rests on; `startRebuild`
#: pins that this really is the module that arms a rebuild; and the hole's `FADED` self-kill
#: pins the other half of the loop, the part that makes the gate reachable at all.
ANCHORS = {
    REBUILD_HOLE_ON_DIE: REBUILD_HOLE_ON_DIE_ENTRY,
    REBUILD_HOLE_CONSTRUCTION_TEST: REBUILD_HOLE_CONSTRUCTION_TEST_BYTES,
    REBUILD_HOLE_START_REBUILD: REBUILD_HOLE_START_REBUILD_BYTES,
    REBUILD_HOLE_SELF_KILL: REBUILD_HOLE_SELF_KILL_BYTES,
    DIE_MODULE_IS_APPLICABLE: DIE_MODULE_IS_APPLICABLE_ENTRY,
    DIE_MUX_IS_APPLICABLE: DIE_MUX_IS_APPLICABLE_ENTRY,
}


class RebuildHoleConstructionPatch(Patch):
    name = "rebuild-hole-construction"
    author = "officialNecro"
    description = (
        "Let a structure destroyed while it is being rebuilt leave its rebuild hole again, so a "
        "creep lair killed mid-rebuild still drops treasure. No INI change; add "
        "UNDER_CONSTRUCTION to a RebuildHoleExposeDie's ExemptStatus to keep the stock behaviour "
        "for that object"
    )

    def apply(self, data: bytearray) -> None:
        off = va_to_offset(data, HOOK_VA)
        if off is None:
            raise ValueError(f"{HOOK_VA:#010x} is not mapped - not the expected build")
        self._check_anchors(data)
        apply_byte_patch(
            data,
            off,
            HOOK_ORIGINAL,
            HOOK_REPLACEMENT,
            "RebuildHoleExposeDie::onDie UNDER_CONSTRUCTION gate -> nop",
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
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the rebuild-hole "
                    "death path is not this build's, so the six bytes at the gate are not the "
                    "branch this patch means to erase"
                )

    def verify(self, data: bytes | bytearray) -> list[str]:
        off = va_to_offset(data, HOOK_VA)
        if off is None:
            return [f"{HOOK_VA:#010x} is not mapped by any section"]
        got = bytes(data[off : off + len(HOOK_REPLACEMENT)])
        if got == HOOK_ORIGINAL:
            return [f"{HOOK_VA:#010x} still holds the UNDER_CONSTRUCTION gate"]
        if got != HOOK_REPLACEMENT:
            return [
                f"{HOOK_VA:#010x} holds {got.hex()}, expected {HOOK_REPLACEMENT.hex()} - "
                "something else has rewritten the gate"
            ]
        return []
