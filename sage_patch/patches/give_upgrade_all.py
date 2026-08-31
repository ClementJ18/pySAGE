"""The give-upgrade-all patch: a porter delivers every upgrade it carries, not the first one.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/give-upgrade-all.md``.

**The limit.** `GiveUpgradeUpdate` treats "the upgrade this porter carries" as a singular. Three
sites ask `UpgradeCenter::firstSetIn` (``0x0066F468``) for *the* upgrade set in the porter's own
object-upgrade mask (`Object+0x28C`, which is what `GrantUpgradeCreate` writes), and everything
downstream is decided by that one answer: whether the cursor accepts a target
(`GiveUpgradeUpdate::canGiveTo`, ``0x0089FE64``), whom a `DeliverUpgrade = Yes` porter walks to
(the filter predicate ``0x00660E04``), and what the recipient is handed
(`GiveUpgradeUpdate::trigger`, the pick at ``0x008A021B``). The registry list is newest-first, so
"the" upgrade is whichever of them the ini declared **last** - a fact nobody writing
`GrantUpgradeCreate` rows is tracking.

So a porter carrying `A B C` delivers exactly one of them, and is refused - invalid cursor, no
diagnostic - by every unit that can take `B` or `C` but not `A`. Acceptance is
`Object::canAcceptUpgrade` (``0x00694914``): a module `TriggeredBy` that exact upgrade, plus the
player satisfying the upgrade's `RequiredObjectFilter`. For a battalion the question is asked of
the horde through `HordeContain::anyMemberCanAccept` (``0x0086ECAB``), so the whole battalion
turns invalid on one upgrade nobody in it uses.

**What this does.** Appends an ``.upgall`` PE section holding four routines and rewrites four
windows, so that all three sites become plural:

- ``0x0089FE64`` `canGiveTo` -> `can_give_any`: the same predicate, over every upgrade in the mask
  rather than the first, with the recipient resolved exactly as stock resolves it.
- ``0x008A021B`` the trigger's pick -> `grant_rest`: returns what the picker returned so the
  twenty instructions after it are untouched, except that it returns the first **acceptable**
  upgrade rather than the first present one, and grants every other acceptable one itself first.
- ``0x0089FF17`` `mov [ebp-0x24], ebx` -> `mov [ebp-0x24], esi`: parks the owning porter in the
  search filter's `+4` slot, which is dead in stock (both constructions of that functor zero it,
  nothing reads it).
- ``0x00660E04`` the filter predicate -> `filter_any`: a candidate that can take *any* carried
  upgrade is a match, so the auto-deliver walks to it. Falls back to the exact stock predicate
  when `+4` is null, so a functor built by a path this patch did not edit is unaffected.

**What the recipient sees.** The extra upgrades go through the engine's own entry points -
`HordeContain::giveUpgradeToMembers(u, force=0)` for a horde, `Object::giveUpgrade` for a lone
object - each gated by the same acceptance test first, so nothing is granted that stock would have
refused. The flash FX, the delivery sound and `GiveUpgradeEffect` fire once for the upgrade the
engine itself hands over, not once per upgrade.

**Registers.** `grant_rest` replaces a `call`, not a function entry, so it reads three of the
caller's registers: `ebx` the owning porter, `edi` the target, `esi` the module. Each is pinned by
an anchor asserted before anything is written - `GIVE_UPGRADE_TRIGGER_OWNER`,
`GIVE_UPGRADE_TRIGGER_TARGET_ARM` and `GIVE_UPGRADE_TRIGGER_MEMBER_ARM` are the instructions that
put them there and use them. The cave saves and restores all four callee-saved registers and
cleans the one argument the picker's `ret 4` cleaned.

**Nothing acceptable.** `grant_rest` returns 0, which is the picker's own "this porter carries
nothing" answer: the trigger takes its `je 0x008A02BB` edge to ``0x0089FE01``, plays `SpawnOutFX`
and fades the porter out. That path is stock and reachable today.

**Determinism.** Every edited site is logic-side, inside a special power's own execution, which
each peer evaluates on the same frame from the same object state. The cave reads two bitsets and
the upgrade registry - no timing, no local player, no rendering - and produces upgrade masks
through the engine's own grant functions. Replay- and network-safe by the same argument as the
stock delivery it extends.

**Blast radius.** `GiveUpgradeUpdate` only. `canGiveTo` has two callers, both on this module's own
paths; the redirected picker call is one of thirteen and the other twelve are untouched; the
filter predicate is unreachable except through a vtable this class builds. An object with no
`GiveUpgradeUpdate` module reaches none of it. For a porter carrying exactly one upgrade - every
vanilla porter, which is handed its upgrade at spawn rather than by `GrantUpgradeCreate` - the
patched path computes stock's answers.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. The four windows it edits are touched by no other bundled patch.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator

from ..addresses import (
    GIVE_UPGRADE_CAN_GIVE,
    GIVE_UPGRADE_CAN_GIVE_BODY,
    GIVE_UPGRADE_CAN_GIVE_BODY_BYTES,
    GIVE_UPGRADE_CAN_GIVE_ENTRY,
    GIVE_UPGRADE_PRODUCER_HORDE_IFACE,
    GIVE_UPGRADE_PRODUCER_HORDE_IFACE_ENTRY,
    GIVE_UPGRADE_SEARCH_FILTER_OWNER,
    GIVE_UPGRADE_SEARCH_FILTER_OWNER_BYTES,
    GIVE_UPGRADE_SEARCH_FILTER_VTABLE,
    GIVE_UPGRADE_SEARCH_FILTER_VTABLE_BYTES,
    GIVE_UPGRADE_SEARCH_OWNER_LOAD,
    GIVE_UPGRADE_SEARCH_OWNER_LOAD_BYTES,
    GIVE_UPGRADE_TRIGGER_MEMBER_ARM,
    GIVE_UPGRADE_TRIGGER_MEMBER_ARM_BYTES,
    GIVE_UPGRADE_TRIGGER_OWNER,
    GIVE_UPGRADE_TRIGGER_OWNER_BYTES,
    GIVE_UPGRADE_TRIGGER_PICK,
    GIVE_UPGRADE_TRIGGER_PICK_BYTES,
    GIVE_UPGRADE_TRIGGER_TARGET_ARM,
    GIVE_UPGRADE_TRIGGER_TARGET_ARM_BYTES,
    HORDE_IFACE_ANY_MEMBER_ACCEPTS_SLOT,
    HORDE_IFACE_GIVE_UPGRADE_SLOT,
    KINDOF_HORDE_BIT,
    KINDOF_HORDE_BYTE,
    OBJECT_CAN_ACCEPT_UPGRADE,
    OBJECT_CONTAINED_BY,
    OBJECT_GET_HORDE_IFACE,
    OBJECT_GIVE_UPGRADE,
    OBJECT_HAS_UPGRADE,
    OBJECT_UPGRADE_MASK,
    THE_UPGRADE_CENTER,
    UPGRADE_CENTER_LIST,
    UPGRADE_FILTER_BODY,
    UPGRADE_FILTER_BODY_BYTES,
    UPGRADE_FILTER_OWNER_SLOT,
    UPGRADE_FILTER_PREDICATE,
    UPGRADE_FILTER_PREDICATE_ENTRY,
    UPGRADE_FILTER_UPGRADE_SLOT,
    UPGRADE_FIRST_SET,
    UPGRADE_FIRST_SET_ENTRY,
    UPGRADE_TEMPLATE_INDEX,
    UPGRADE_TEMPLATE_NEXT,
)
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "SECTION_NAME",
    "GiveUpgradeAllPatch",
    "build_code",
]

SECTION_NAME = ".upgall"  # 7 chars: the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | MEM_EXECUTE | MEM_READ - the cave is pure code and is never written.
_CHARACTERISTICS = 0x20 | 0x20000000 | 0x40000000

#: The first bytes at each address the cave depends on but does not rewrite, as a `{va: bytes}`
#: map. These are the two function bodies the hooks displace the entry of, the picker whose
#: contract `next_upgrade` reimplements, the horde-interface resolver both caves call, and the
#: three instructions that pin which register holds the porter, the target and the module at the
#: trigger's pick. A build whose layout moved fails here rather than on a wild call or a cave that
#: reads the wrong register.
ANCHORS = {
    GIVE_UPGRADE_CAN_GIVE_BODY: GIVE_UPGRADE_CAN_GIVE_BODY_BYTES,
    GIVE_UPGRADE_PRODUCER_HORDE_IFACE: GIVE_UPGRADE_PRODUCER_HORDE_IFACE_ENTRY,
    GIVE_UPGRADE_SEARCH_OWNER_LOAD: GIVE_UPGRADE_SEARCH_OWNER_LOAD_BYTES,
    GIVE_UPGRADE_SEARCH_FILTER_VTABLE: GIVE_UPGRADE_SEARCH_FILTER_VTABLE_BYTES,
    GIVE_UPGRADE_TRIGGER_OWNER: GIVE_UPGRADE_TRIGGER_OWNER_BYTES,
    GIVE_UPGRADE_TRIGGER_TARGET_ARM: GIVE_UPGRADE_TRIGGER_TARGET_ARM_BYTES,
    GIVE_UPGRADE_TRIGGER_MEMBER_ARM: GIVE_UPGRADE_TRIGGER_MEMBER_ARM_BYTES,
    UPGRADE_FILTER_BODY: UPGRADE_FILTER_BODY_BYTES,
    UPGRADE_FIRST_SET: UPGRADE_FIRST_SET_ENTRY,
}


def build_code(base_va: int) -> Asm:
    """The four routines the hooks reach, plus the two the cave calls itself.

    Emitted in one buffer so the internal calls resolve as labels; the entry points are read back
    out with :meth:`Asm.label_va` rather than by counting bytes twice.
    """
    a = Asm(base_va)
    _emit_can_give_any(a)
    _emit_grant_rest(a)
    _emit_filter_any(a)
    _emit_filter_test(a)
    _emit_next_upgrade(a)
    return a


def _emit_can_give_any(a: Asm) -> None:
    """`bool canGiveTo(Object *target)` — thiscall, `ret 4`, replacing the whole stock function.

    Stock asks whether the recipient accepts the one carried upgrade; this asks whether it accepts
    any of them. The recipient is resolved as stock resolves it: a target with a container
    (`+0x27C`) is a battalion member and the question belongs to its horde, anything else answers
    for itself. Every other stock outcome survives, including "the member's horde is gone -> no".
    """
    a.label("can_give_any")
    a.emit(0x53, 0x56, 0x57)  # push ebx / esi / edi
    a.emit(0x50)  # push eax - the recipient-interface slot, [esp]
    a.emit(0x8B, 0xF1)  # mov esi, ecx           ; the module
    a.emit(0x8B, 0x7C, 0x24, 0x14)  # mov edi, [esp+0x14]    ; the target
    a.emit(0x8B, 0x5E, 0x08)  # mov ebx, [esi+8]       ; the owning porter
    a.emit(0x81, 0xC3, struct.pack("<I", OBJECT_UPGRADE_MASK))  # add ebx, 0x28c
    a.emit(0x33, 0xC0)  # xor eax, eax           ; no interface == a lone object
    a.emit(0x83, 0xBF, struct.pack("<I", OBJECT_CONTAINED_BY), 0x00)  # cmp dword [edi+0x27c], 0
    a.jcc_short(JE, "cga_have")
    a.emit(0x57)  # push edi
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(GIVE_UPGRADE_PRODUCER_HORDE_IFACE)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "cga_false")

    a.label("cga_have")
    a.emit(0x89, 0x04, 0x24)  # mov [esp], eax
    a.emit(0x33, 0xF6)  # xor esi, esi           ; the upgrade cursor
    a.label("cga_loop")
    a.emit(0x8B, 0xC6)  # mov eax, esi
    a.emit(0x8B, 0xD3)  # mov edx, ebx
    a.call("next_upgrade")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "cga_false")  # nothing left -> no
    a.emit(0x8B, 0xF0)  # mov esi, eax
    a.emit(0x8B, 0x04, 0x24)  # mov eax, [esp]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "cga_plain")
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0x10)  # mov edx, [eax]
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.emit(0xFF, 0x92, struct.pack("<I", HORDE_IFACE_ANY_MEMBER_ACCEPTS_SLOT))
    a.jmp_short("cga_tested")
    a.label("cga_plain")
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(OBJECT_CAN_ACCEPT_UPGRADE)
    a.label("cga_tested")
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc_short(JE, "cga_loop")  # this one is refused - try the next
    a.emit(0xB0, 0x01)  # mov al, 1
    a.jmp_short("cga_out")

    a.label("cga_false")
    a.emit(0x32, 0xC0)  # xor al, al
    a.label("cga_out")
    a.emit(0x59)  # pop ecx - drop the interface slot
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi / esi / ebx
    a.emit(0xC2, 0x04, 0x00)  # ret 4


def _emit_grant_rest(a: Asm) -> None:
    """Stands in for the trigger's `call UpgradeCenter::firstSetIn` — same contract, `ret 4`.

    Returns the first upgrade the recipient **accepts** instead of the first one present, and
    grants every other acceptable one on the way, so the engine's own two arms below the call
    deliver one upgrade they were always going to be able to deliver. Returning 0 is the picker's
    own "carries nothing" answer and lands on a path stock already runs.

    Reads `ebx` (the porter), `edi` (the target) and `esi` (the module) out of the caller; the
    module docstring says which anchor pins each.
    """
    a.label("grant_rest")
    a.emit(0x53, 0x56, 0x57, 0x55)  # push ebx / esi / edi / ebp
    a.emit(0x83, 0xEC, 0x08)  # sub esp, 8   ; [esp] recipient, [esp+4] mask
    a.emit(0x8B, 0x44, 0x24, 0x1C)  # mov eax, [esp+0x1c]  ; the mask argument
    a.emit(0x89, 0x44, 0x24, 0x04)  # mov [esp+4], eax

    # The recipient, resolved the way the trigger resolves it sixteen bytes later: a target that
    # is itself a horde answers through its own interface, anything else through its producer's.
    a.emit(0x8B, 0x47, 0x04)  # mov eax, [edi+4]   ; the target's template
    a.emit(0xF6, 0x80, struct.pack("<I", KINDOF_HORDE_BYTE), KINDOF_HORDE_BIT)
    a.jcc_short(JE, "gr_member")
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(OBJECT_GET_HORDE_IFACE)
    a.jmp_short("gr_have")
    a.label("gr_member")
    a.emit(0x57)  # push edi
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(GIVE_UPGRADE_PRODUCER_HORDE_IFACE)
    a.label("gr_have")
    a.emit(0x89, 0x04, 0x24)  # mov [esp], eax
    a.emit(0x33, 0xED)  # xor ebp, ebp      ; the upgrade stock will hand over
    a.emit(0x33, 0xC0)  # xor eax, eax      ; the upgrade cursor

    a.label("gr_loop")
    a.emit(0x8B, 0x54, 0x24, 0x04)  # mov edx, [esp+4]
    a.call("next_upgrade")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "gr_out")
    a.emit(0x8B, 0xF0)  # mov esi, eax      ; esi is the current upgrade from here on
    a.emit(0x8B, 0x04, 0x24)  # mov eax, [esp]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "gr_plain_test")
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0x10)  # mov edx, [eax]
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.emit(0xFF, 0x92, struct.pack("<I", HORDE_IFACE_ANY_MEMBER_ACCEPTS_SLOT))
    a.jmp_short("gr_tested")
    a.label("gr_plain_test")
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(OBJECT_CAN_ACCEPT_UPGRADE)
    a.label("gr_tested")
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc_short(JE, "gr_step")  # refused: grant nothing, and do not choose it
    a.emit(0x85, 0xED)  # test ebp, ebp
    a.jcc_short(JNE, "gr_give")
    a.emit(0x8B, 0xEE)  # mov ebp, esi      ; the first acceptable one is the engine's to give
    a.jmp_short("gr_step")

    a.label("gr_give")
    a.emit(0x8B, 0x04, 0x24)  # mov eax, [esp]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "gr_give_plain")
    a.emit(0x6A, 0x00)  # push 0            ; force = false: gate every member
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0x10)  # mov edx, [eax]
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.emit(0xFF, 0x92, struct.pack("<I", HORDE_IFACE_GIVE_UPGRADE_SLOT))
    a.jmp_short("gr_step")
    a.label("gr_give_plain")
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(OBJECT_GIVE_UPGRADE)

    a.label("gr_step")
    a.emit(0x8B, 0xC6)  # mov eax, esi      ; continue from the upgrade just considered
    a.jmp("gr_loop")

    a.label("gr_out")
    a.emit(0x8B, 0xC5)  # mov eax, ebp
    a.emit(0x83, 0xC4, 0x08)  # add esp, 8
    a.emit(0x5D, 0x5F, 0x5E, 0x5B)  # pop ebp / edi / esi / ebx
    a.emit(0xC2, 0x04, 0x00)  # ret 4


def _emit_filter_any(a: Asm) -> None:
    """`bool UpgradeFilter::operator()(Object *candidate)` — thiscall, `ret 4`.

    The auto-deliver's search predicate. With a porter parked in the functor's `+4` slot it
    accepts a candidate that can take any carried upgrade; with `+4` null - a functor built by a
    path this patch did not edit - it is the stock predicate over the captured upgrade at `+8`.
    """
    a.label("filter_any")
    a.emit(0x53, 0x56, 0x57)  # push ebx / esi / edi
    a.emit(0x8B, 0xF1)  # mov esi, ecx           ; the filter
    a.emit(0x8B, 0x7C, 0x24, 0x10)  # mov edi, [esp+0x10]    ; the candidate
    a.emit(0x8B, 0x5E, UPGRADE_FILTER_OWNER_SLOT)  # mov ebx, [esi+4]
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc_short(JE, "fa_single")
    a.emit(0x81, 0xC3, struct.pack("<I", OBJECT_UPGRADE_MASK))  # add ebx, 0x28c
    a.emit(0x33, 0xF6)  # xor esi, esi           ; the upgrade cursor

    a.label("fa_loop")
    a.emit(0x8B, 0xC6)  # mov eax, esi
    a.emit(0x8B, 0xD3)  # mov edx, ebx
    a.call("next_upgrade")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "fa_false")
    a.emit(0x8B, 0xF0)  # mov esi, eax
    a.call("filter_test")
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc_short(JE, "fa_loop")
    a.jmp_short("fa_true")

    a.label("fa_single")
    a.emit(0x8B, 0x76, UPGRADE_FILTER_UPGRADE_SLOT)  # mov esi, [esi+8]
    a.call("filter_test")
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc_short(JE, "fa_false")

    a.label("fa_true")
    a.emit(0xB0, 0x01)  # mov al, 1
    a.jmp_short("fa_out")
    a.label("fa_false")
    a.emit(0x32, 0xC0)  # xor al, al
    a.label("fa_out")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi / esi / ebx
    a.emit(0xC2, 0x04, 0x00)  # ret 4


def _emit_filter_test(a: Asm) -> None:
    """`esi` the upgrade, `edi` the candidate -> `al`. The stock predicate's own two questions,
    in its own order: can this object take the upgrade, and does it not already have it."""
    a.label("filter_test")
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(OBJECT_CAN_ACCEPT_UPGRADE)
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc_short(JE, "ft_no")
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(OBJECT_HAS_UPGRADE)
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc_short(JNE, "ft_no")
    a.emit(0xB0, 0x01)  # mov al, 1
    a.emit(0xC3)  # ret
    a.label("ft_no")
    a.emit(0x32, 0xC0)  # xor al, al
    a.emit(0xC3)  # ret


def _emit_next_upgrade(a: Asm) -> None:
    """`eax` the current template or 0, `edx` the mask -> the next template set in it, or 0.

    `UpgradeCenter::firstSetIn` with a resumable cursor: same list (`TheUpgradeCenter+0x0C`, linked
    through `+0x64`), same bit selection (`UpgradeTemplate+0x38`, word `index >> 5`, bit
    `index & 31`). Passing 0 starts at the head, which makes it answer exactly what the picker
    this patch redirects would have answered. Preserves every register but `eax`.
    """
    a.label("next_upgrade")
    a.emit(0x53, 0x51)  # push ebx / ecx
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JNE, "nu_step")
    a.emit(0xA1, struct.pack("<I", THE_UPGRADE_CENTER))  # mov eax, [TheUpgradeCenter]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "nu_none")
    a.emit(0x8B, 0x40, UPGRADE_CENTER_LIST)  # mov eax, [eax+0x0c]
    a.jmp_short("nu_check")
    a.label("nu_step")
    a.emit(0x8B, 0x40, UPGRADE_TEMPLATE_NEXT)  # mov eax, [eax+0x64]
    a.label("nu_check")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "nu_none")
    a.emit(0x8B, 0x48, UPGRADE_TEMPLATE_INDEX)  # mov ecx, [eax+0x38]
    a.emit(0x8B, 0xD9)  # mov ebx, ecx
    a.emit(0x83, 0xE1, 0x1F)  # and ecx, 0x1f
    a.emit(0xC1, 0xEB, 0x05)  # shr ebx, 5
    a.emit(0x8B, 0x1C, 0x9A)  # mov ebx, [edx+ebx*4]
    a.emit(0xD3, 0xEB)  # shr ebx, cl
    a.emit(0xF6, 0xC3, 0x01)  # test bl, 1
    a.jcc_short(JNE, "nu_done")
    a.jmp_short("nu_step")
    a.label("nu_none")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.label("nu_done")
    a.emit(0x59, 0x5B)  # pop ecx / ebx
    a.emit(0xC3)  # ret


class GiveUpgradeAllPatch(Patch):
    """Make `GiveUpgradeUpdate` deliver every upgrade its porter carries."""

    name = "give-upgrade-all"
    author = "officialNecro"
    description = (
        "A porter delivers every upgrade it carries instead of only the one the upgrade registry "
        "happens to list first, and is a valid target-of-opportunity for anything that can accept "
        "any of them - so GrantUpgradeCreate on a GiveUpgradeUpdate carrier becomes a list rather "
        "than a one-of, and a battalion that can take the second upgrade but not the first stops "
        "showing the invalid cursor. Auto-deliver (DeliverUpgrade = Yes) searches for a recipient "
        "of any carried upgrade too. No INI change: the same GrantUpgradeCreate and "
        "GiveUpgradeUpdate keywords, read plurally"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        section_va = allocate_section(
            data, SECTION_NAME, lambda va: build_code(va).finish(), _CHARACTERISTICS
        )
        for file_off, old, new, note in self._edits(data, build_code(section_va)):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch (an empty list == verified).

        Locates the cave, rebuilds the code its base VA implies, and compares that and all four
        rewritten windows against what is on disk. Needs no disassembler.
        """
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located

        problems: list[str] = []
        code = build_code(section_va)
        content = code.finish()
        if bytes(data[section_off : section_off + len(content)]) != content:
            problems.append(f"the {SECTION_NAME} cave does not hold the expected routines")

        try:
            edits = list(self._edits(data, code))
        except ValueError as exc:
            return [*problems, f"cannot locate the patched sites (wrong build?): {exc}"]
        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")

        try:
            self._check_anchors(data)
        except ValueError as exc:
            problems.append(str(exc))
        return problems

    def _edits(self, data: bytes | bytearray, code: Asm) -> Iterator[tuple[int, bytes, bytes, str]]:
        """The four windows, as ``(file offset, stock bytes, patched bytes, note)``.

        One list, used by both :meth:`apply` and :meth:`verify`, so the two cannot disagree about
        what this patch writes.
        """
        can_give = code.label_va("can_give_any")
        grant_rest = code.label_va("grant_rest")
        filter_any = code.label_va("filter_any")

        # The `nop` keeps the six-byte window an integral number of instructions: the entry is
        # `push esi` / `mov esi, ecx` / `mov eax, [esi+8]` and a `jmp rel32` covers only five.
        yield (
            self._offset(data, GIVE_UPGRADE_CAN_GIVE),
            GIVE_UPGRADE_CAN_GIVE_ENTRY,
            _jmp(GIVE_UPGRADE_CAN_GIVE, can_give) + b"\x90",
            "GiveUpgradeUpdate::canGiveTo -> can_give_any",
        )
        yield (
            self._offset(data, GIVE_UPGRADE_TRIGGER_PICK),
            GIVE_UPGRADE_TRIGGER_PICK_BYTES,
            _call(GIVE_UPGRADE_TRIGGER_PICK, grant_rest),
            "the trigger's UpgradeCenter::firstSetIn -> grant_rest",
        )
        # `mov [ebp-0x24], esi` for `mov [ebp-0x24], ebx`: the filter's dead `+4` slot gains the
        # owning porter, which is the only thing `filter_any` needs and cannot otherwise reach.
        yield (
            self._offset(data, GIVE_UPGRADE_SEARCH_FILTER_OWNER),
            GIVE_UPGRADE_SEARCH_FILTER_OWNER_BYTES,
            bytes.fromhex("8975dc"),
            "the search filter's +4 slot carries the porter",
        )
        yield (
            self._offset(data, UPGRADE_FILTER_PREDICATE),
            UPGRADE_FILTER_PREDICATE_ENTRY,
            _jmp(UPGRADE_FILTER_PREDICATE, filter_any),
            "UpgradeFilter::operator() -> filter_any",
        )

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"{va:#010x} is not mapped - not the expected build")
        return off

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{va:#010x} is not mapped - not the expected build")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the porter's "
                    "upgrade delivery is not laid out as this patch reads it, so the cave would "
                    "call the wrong function or read the wrong register"
                )


def _jmp(site_va: int, target_va: int) -> bytes:
    return b"\xe9" + struct.pack("<i", target_va - (site_va + 5))


def _call(site_va: int, target_va: int) -> bytes:
    return b"\xe8" + struct.pack("<i", target_va - (site_va + 5))
