"""The foundation-rebind patch: a structure replaced in place keeps the plot it stands on.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/foundation-rebind.md``.

**The defect.** A settlement flag *is* the plot: `FoundationAIUpdate` - and `CastleBehavior`,
which derives from it and shares its interface vtable - keeps the occupant as one `ObjectID` at
``module+0x28``, and `setBuiltOnObject` (``0x008582DE``) is the whole of the visual mechanic
around it. Non-zero hides the flag (status `UNSELECTABLE`, then a 10-frame fade-out); zero
brings it back (a 30-frame fade-in).

`ReplaceSelfUpgrade` destroys first and builds second, and the destroy frees the plot before the
replacement exists. `GameLogic::destroyObject` broadcasts `onDelete` to every module **inside the
same call**, and `GettingBuiltBehavior::onDelete` (``0x0085757F``) follows the dying object's
``Object+0x78`` to its plot and calls the interface's ``clearBuiltOn``. A slower mechanism agrees
with it: `FoundationAIUpdate::update` polls ``findObjectByID(m_builtOnID)`` every frame and clears
the link when the id stops resolving. **The engine's notion of "my building" is an id, and a
replacement gets a new id.**

Nothing re-adopts, either. The plot's "look around and see what is standing on me" scan
(``0x008583E3``) is fired once, on the module's first update, for structures the map places on
plots at load; a plot freed mid-match never looks again. So a mod that swaps a building for
another one on a settlement gets the flag back, and has to hide it by hand and stand a dummy
building on the plot to make it read as occupied again.

**What this does.** Two `call rel32` at the two moments that matter, and one cave:

- Before the destroy (``0x008BB6CC``), read the dying object's ``Object+0x78``, and *only* if
  that object really is a plot holding **this** object - it has a foundation interface and its
  ``m_builtOnID`` is our id - remember the pair and zero the link, so `onDelete` finds nothing
  and the flag never transitions.
- After the replacement is created (``0x008BB964``, the `call` that starts the wall walk), write
  the new object's id into the plot's ``m_builtOnID``, point the new object's ``Object+0x78`` at
  the plot, and refresh the plot's own ``Object+0x7C`` back-link.

**The field is written directly, not through the setter.** The plot goes occupied → occupied, so
there is nothing to transition: the status bit and the drawable are already in the state the patch
wants, because hook 1 stopped anything from changing them. Going through `setBuiltOnObject` would
reset the drawable's opacity to 1.0 before starting its fade-out (``0x00670A50``), which on an
already-hidden flag is a visible blink.

**Both mechanisms are covered.** Hook 2 commits when the plot is free (the usual case, `onDelete`
having run) **or** still names the object that was just destroyed (what a structure with no
`GettingBuiltBehavior` leaves behind, where the frame poll would have cleared it later). Anything
else - a plot that has meanwhile been claimed by someone else - is left alone.

**Why zeroing ``Object+0x78`` is safe.** That field is `m_producerID` generally, not a plot link:
on a unit it is the building that made it. Hook 1 clears it only after resolving it to an object
that has a foundation interface *and* is holding the dying object, which no barracks is and no
producer of anything but a plot-built structure can be.

**One module, both flavours of flag.** `FoundationAIUpdate` and `CastleBehavior` write the same
vtable ``0x00C30DE8`` into ``module+0x20`` and share ``module+0x28``, so a settlement plot and a
camp flag are the same four stores. A `CastleBehavior` that has *unpacked* tracks its keep in a
second field (``+0x38``, polled at ``0x00799B13``) which this patch does not touch: a keep that is
replaced rather than destroyed still repacks its castle.

**Scope.** `ReplaceSelfUpgrade` only. Objects destroyed any other way free their plot exactly as
today, including the replacement itself when it dies. When `ReplaceWith` names several objects the
**first** created takes the plot - a plot holds one occupant - and the rest are ordinary buildings.

**Destroying without creating degrades to stock rather than to a stuck plot.** The one path that
reaches the destroy and then bails - a `ReplaceWith` naming a template the `ThingFactory` does not
know (``0x008BB6F1``) - leaves the plot holding an id that no longer resolves and nothing to hand
it to. That is precisely the state `FoundationAIUpdate::update`'s poll exists for, so the flag
comes back a frame or two later, exactly as it does today.

**Re-entrancy.** The pair is parked in a four-slot ring in the cave and keyed on the **dying
object's id**, which hook 2 reads out of the stock frame slot the wall walk just filled
(``[ebp-0x3C]``). Keying rather than stacking is what makes the failure mode safe: a nested
`ReplaceSelfUpgrade` (a replacement whose creation triggers another one) takes its own slot, a
creation that fails leaves a slot behind that no later object can match, and a fifth level of
nesting loses a rebind rather than binding the wrong plot.

**Determinism.** Everything written is simulation state on the logic thread - the plot's occupant,
two id back-links - so **every peer needs the patched binary** and replays recorded on it will not
play back on a stock one.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. The two `call` displacements it rewrites are touched by no other
bundled patch, and it reads nothing another patch rewrites.
"""

from __future__ import annotations

import struct

from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "FOUNDATION_BUILT_ON_OFFSET",
    "RING_SLOTS",
    "SECTION_NAME",
    "FoundationRebindPatch",
    "build_section",
]

# --- the engine ---------------------------------------------------------------------------------

#: `TheGameLogic`, the singleton both hooks reload rather than trusting a register across a call.
THE_GAME_LOGIC = 0x00DE412C

#: `GameLogic::findObjectByID(ObjectID)` - ``__thiscall``, ``ret 4``, 0 for id 0 and for an id
#: that no longer resolves. The same address `herobar` and `horde-orphan-target` call.
FIND_OBJECT_BY_ID = 0x00449681

#: `Object::getFoundationInterface()` - ``__thiscall``, no arguments, no stack cleanup. Walks the
#: ``Object+0x24C`` module list asking each module's ``+0xC`` vtable slot ``+0x98``, and returns
#: the first non-NULL: the ``module+0x20`` subobject of `FoundationAIUpdate` or `CastleBehavior`.
GET_FOUNDATION_INTERFACE = 0x0068C3C3

#: `GameLogic::destroyObject(Object*)` - ``__thiscall``, ``ret 4``. Hook 1 tail-jumps to it, so
#: its own ``ret 4`` returns straight to the instruction after the hooked `call`.
DESTROY_OBJECT = 0x0062BBAB

#: `GameLogic::getFirstObject()` - ``__thiscall``, no arguments, ``mov eax, [ecx+0xAC]; ret``.
#: Hook 2's tail-jump, for the same reason.
GET_FIRST_OBJECT = 0x0097338F

#: `Object::m_id`. Also :data:`~..addresses.OBJECT_ID`; restated here so this patch's assembly
#: reads without a second file open.
OBJECT_ID_OFFSET = 0x74

#: `Object::m_producerID` - on a plot-built structure, the plot. Set by the build path at
#: ``0x00857AEA`` and by the foundation's own first-update scan at ``0x008584C7``; read by
#: `GettingBuiltBehavior::onDelete` to decide which plot to free.
OBJECT_PRODUCER_ID_OFFSET = 0x78

#: The plot's own back-link to what stands on it, written beside the producer link at
#: ``0x00857AF2``. Not what any teardown path consults - they all go through ``m_builtOnID`` -
#: but leaving it naming a destroyed object would be a lie this patch is in a position to avoid.
#: Rewritten only when it still names the object being replaced, because that is the only case in
#: which this patch can prove whose field it is.
OBJECT_BUILT_BACK_LINK_OFFSET = 0x7C

#: ``m_builtOnID`` from the interface pointer: the interface is ``module+0x20`` and the field is
#: ``module+0x28``. This is the offset `isOccupied` (``0x0097031D``) itself reads, as
#: ``cmp [ecx+8], eax``.
FOUNDATION_BUILT_ON_OFFSET = 0x08

# --- the hooks ----------------------------------------------------------------------------------

#: The `call GameLogic::destroyObject` inside `ReplaceSelfUpgrade::upgradeImplementation`
#: (``0x008BB5FA``), with the dying object already pushed and `TheGameLogic` already in ecx.
HOOK_DESTROY_CALL_VA = 0x008BB6CC

#: The `call GameLogic::getFirstObject` that starts the stock wall-rebind walk, one instruction
#: after the frame slot holding the dying object's id is filled. The replacement exists by then.
HOOK_WALK_CALL_VA = 0x008BB964

#: `upgradeImplementation`'s own frame slots, as displacements from its ``ebp`` (which it sets to
#: ``esp-0x78`` on entry and never moves). ``[ebp-0x20]`` is the object just created - written at
#: ``0x008BB8E0`` and read by the stock wall walk at ``0x008BB9A6`` - and ``[ebp-0x3C]`` is the
#: dying object's id, written by the instruction immediately before hook 2.
FRAME_NEW_OBJECT = -0x20
FRAME_OLD_ID = -0x3C

#: Byte windows the patch depends on and does not rewrite, as ``{va: expected bytes}``. The two
#: hook windows carry the `call` being repointed, which :meth:`~FoundationRebindPatch.verify`
#: blanks before comparing so the same table checks a patched image.
ANCHORS: dict[int, bytes] = {
    # the two hook sites, in context: `push [esi-8]; mov ecx, [TheGameLogic]; call destroyObject`
    0x008BB6C3: bytes.fromhex("ff76f88b0d2c41de00e8da04d7ff"),
    # `mov eax,[esi-8]; mov eax,[eax+0x74]; mov ecx,[TheGameLogic]; mov [ebp-0x3c],eax; call ...`
    0x008BB955: bytes.fromhex("8b46f88b40748b0d2c41de008945c4e8267a0b008bf8"),
    # the creation call and the frame slot it fills: `call [ebx+0x38]; mov edi,eax; test edi,edi;
    # mov [ebp-0x20],edi`. Both of hook 2's frame reads are pinned by a window, so a mistyped
    # displacement is caught here rather than by reading the neighbouring local at runtime.
    0x008BB8D9: bytes.fromhex("ff53388bf885ff897de00f841e010000"),
    # `FoundationAIUpdate::setBuiltOnObject` - proves `m_builtOnID` is `module+0x28` and that the
    # setter early-outs on an unchanged id
    0x008582DE: bytes.fromhex("8b442404568bf13946280f84e600000085c08b4e085357894628"),
    # its freed branch: the `WALL_UPGRADE` skip, then `setStatus(UNSELECTABLE, false)`
    0x0085838B: bytes.fromhex("8b4104bb0000400085981801000075376a006a03"),
    # `Object::getFoundationInterface` - the module walk and the `+0x98` slot it asks for
    0x0068C3C3: bytes.fromhex(
        "568bb14c020000eb128d480c8b01ff909800000085c0750983c6048b0685c075e85ec3"
    ),
    # `isOccupied` - `return [iface+8] != 0`, which is what pins FOUNDATION_BUILT_ON_OFFSET
    0x0097031D: bytes.fromhex("33c03941080f95c0c3"),
    # `GettingBuiltBehavior::onDelete` - producer id -> findObjectByID -> getFoundationInterface,
    # the path hook 1 exists to make a no-op
    0x0085757F: bytes.fromhex("568bf18b4608ff70788b0d2c41de00e8ee20bfff85c0741d8bc8e8254ee3ff"),
    # `FoundationAIUpdate::update`'s liveness poll and its clear - the backstop hook 2 satisfies
    0x008585EC: bytes.fromhex(
        "8b461885c074148b0d2c41de0050e88210bfff85c00f85e80000006a008d4ef0e8cdfcffff"
    ),
    # the two tail-jump targets
    0x0062BBAB: bytes.fromhex("53578b7c240c85ff8bd9746cf6"),
    0x0097338F: bytes.fromhex("8b81ac000000c3"),
}

# --- the cave -----------------------------------------------------------------------------------

SECTION_NAME = ".fndrbd"  # 7 chars: the PE name field is 8 bytes and truncates silently
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. Writable because the ring
# lives in the same section as the code that reads it.
SECTION_CHARACTERISTICS = 0xE0000060

#: How many ``(dying object id, plot id)`` pairs the cave can hold at once. One is enough for the
#: flat case; four covers a replacement whose creation triggers another `ReplaceSelfUpgrade`.
RING_SLOTS = 4
RING_SLOT_SIZE = 8
RING_SIZE = RING_SLOTS * RING_SLOT_SIZE


def _call_bytes(from_va: int, to_va: int) -> bytes:
    """The five bytes of ``call rel32`` sited at ``from_va``."""
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


def _build_stash(base_va: int, ring_va: int) -> bytes:
    """Hook 1: remember the plot the dying object stands on, and cut the object's link to it.

    Entered by the repointed `call`, so ``[esp+4]`` is the `Object*` `destroyObject` is about to
    be given and ecx is `TheGameLogic`. Ends by tail-jumping to `destroyObject`, whose ``ret 4``
    returns to the instruction after the hooked `call`.

    The guard is the whole point: the producer link is only followed when it resolves to an object
    that has a foundation interface *and* whose ``m_builtOnID`` is the dying object's own id. A
    unit's producer is a barracks, which answers no foundation interface, so nothing here fires on
    anything but a structure standing on a plot."""
    a = Asm(base_va)
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(0x51)  # push ecx                    ; TheGameLogic, for the tail jump
    a.emit(b"\x8b\x5c\x24\x10")  # mov ebx, [esp+0x10]         ; the dying Object *
    a.emit(b"\x85\xdb")  # test ebx, ebx
    a.jcc(JE, "out")
    a.emit(b"\x8b\x43", OBJECT_PRODUCER_ID_OFFSET)  # mov eax, [ebx+0x78]  ; m_producerID
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "out")  # not built on anything

    a.emit(0x50)  # push eax
    a.emit(b"\x8b\x0d", struct.pack("<I", THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.call_absolute(FIND_OBJECT_BY_ID)  # call findObjectByID   ; ret 4
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "out")  # the producer is gone
    a.emit(b"\x8b\xc8")  # mov ecx, eax
    a.call_absolute(GET_FOUNDATION_INTERFACE)  # call getFoundationInterface
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "out")  # the producer is not a plot

    a.emit(b"\x8b\x53", OBJECT_ID_OFFSET)  # mov edx, [ebx+0x74]   ; the dying object's id
    a.emit(b"\x39\x50", FOUNDATION_BUILT_ON_OFFSET)  # cmp [eax+8], edx
    a.jcc(JNE, "out")  # the plot is holding somebody else

    # Commit: park (dying id, plot id) in the first free ring slot, and cut the link `onDelete`
    # would otherwise follow. edx still holds the dying object's id.
    a.emit(b"\xb9", struct.pack("<I", RING_SLOTS))  # mov ecx, RING_SLOTS
    a.emit(b"\xbe", struct.pack("<I", ring_va))  # mov esi, <ring>
    a.label("scan")
    a.emit(b"\x83\x3e\x00")  # cmp dword [esi], 0
    a.jcc_short(JE, "take")
    a.emit(b"\x83\xc6", RING_SLOT_SIZE)  # add esi, 8
    a.emit(0x49)  # dec ecx
    a.jcc_short(JNE, "scan")
    a.emit(b"\xbe", struct.pack("<I", ring_va))  # mov esi, <ring>  ; full: reuse slot 0
    a.label("take")
    a.emit(b"\x89\x16")  # mov [esi], edx                ; the key
    a.emit(b"\x8b\x43", OBJECT_PRODUCER_ID_OFFSET)  # mov eax, [ebx+0x78]
    a.emit(b"\x89\x46", RING_SLOT_SIZE // 2)  # mov [esi+4], eax     ; the plot
    a.emit(b"\x83\x63", OBJECT_PRODUCER_ID_OFFSET, 0x00)  # and dword [ebx+0x78], 0

    a.label("out")
    a.emit(0x59)  # pop ecx
    a.emit(0x5E)  # pop esi
    a.emit(0x5B)  # pop ebx
    a.jmp_absolute(DESTROY_OBJECT)
    return a.finish()


def _build_rebind(base_va: int, ring_va: int) -> bytes:
    """Hook 2: hand the remembered plot to the object that replaced its occupant.

    Entered by the repointed `call` that starts the stock wall walk, so ecx is `TheGameLogic`,
    ``[ebp-0x3C]`` is the dying object's id and ``[ebp-0x20]`` is the replacement. Ends by
    tail-jumping to `getFirstObject`, which is what the `call` was for.

    Commits when the plot is free - the usual case, `onDelete` having already run - or when it
    still names the object that was just destroyed, which is what the frame poll would otherwise
    clear a frame or two later. A plot that has meanwhile been claimed by anybody else is left
    exactly as it is."""
    a = Asm(base_va)
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    a.emit(0x51)  # push ecx                    ; TheGameLogic, for the tail jump

    a.emit(b"\x8b\x7d", FRAME_OLD_ID & 0xFF)  # mov edi, [ebp-0x3c]   ; the ring key
    a.emit(b"\x85\xff")  # test edi, edi
    a.jcc(JE, "out")

    a.emit(b"\xb9", struct.pack("<I", RING_SLOTS))  # mov ecx, RING_SLOTS
    a.emit(b"\xbe", struct.pack("<I", ring_va))  # mov esi, <ring>
    a.label("scan")
    a.emit(b"\x39\x3e")  # cmp [esi], edi
    a.jcc_short(JE, "found")
    a.emit(b"\x83\xc6", RING_SLOT_SIZE)  # add esi, 8
    a.emit(0x49)  # dec ecx
    a.jcc_short(JNE, "scan")
    a.jmp("out")  # nothing was stashed for this object

    a.label("found")
    a.emit(b"\x8b\x5e", RING_SLOT_SIZE // 2)  # mov ebx, [esi+4]      ; the plot id
    a.emit(b"\x83\x26\x00")  # and dword [esi], 0    ; consume it either way
    a.emit(b"\x85\xdb")  # test ebx, ebx
    a.jcc(JE, "out")
    a.emit(b"\x8b\x75", FRAME_NEW_OBJECT & 0xFF)  # mov esi, [ebp-0x20]   ; the replacement
    a.emit(b"\x85\xf6")  # test esi, esi
    a.jcc(JE, "out")

    a.emit(0x53)  # push ebx
    a.emit(b"\x8b\x0d", struct.pack("<I", THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.call_absolute(FIND_OBJECT_BY_ID)  # call findObjectByID   ; ret 4
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "out")  # the plot is gone too
    a.emit(b"\x8b\xc8")  # mov ecx, eax
    a.emit(0x50)  # push eax
    a.call_absolute(GET_FOUNDATION_INTERFACE)  # call getFoundationInterface
    a.emit(0x59)  # pop ecx                       ; ecx = the plot
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "out")

    a.emit(b"\x8b\x50", FOUNDATION_BUILT_ON_OFFSET)  # mov edx, [eax+8]  ; current occupant
    a.emit(b"\x85\xd2")  # test edx, edx
    a.jcc_short(JE, "commit")  # freed by onDelete
    a.emit(b"\x3b\xd7")  # cmp edx, edi
    a.jcc(JNE, "out")  # somebody else's now

    a.label("commit")
    a.emit(b"\x8b\x56", OBJECT_ID_OFFSET)  # mov edx, [esi+0x74]   ; the replacement's id
    a.emit(b"\x89\x50", FOUNDATION_BUILT_ON_OFFSET)  # mov [eax+8], edx   ; occupied again
    a.emit(b"\x89\x5e", OBJECT_PRODUCER_ID_OFFSET)  # mov [esi+0x78], ebx ; and it owns the plot
    # The plot's own back-link, and only when it is provably stale - it names the object that has
    # just been destroyed. Anything else there was not this pairing's to rewrite.
    a.emit(b"\x39\x79", OBJECT_BUILT_BACK_LINK_OFFSET)  # cmp [ecx+0x7c], edi
    a.jcc(JNE, "out")
    a.emit(b"\x89\x51", OBJECT_BUILT_BACK_LINK_OFFSET)  # mov [ecx+0x7c], edx

    a.label("out")
    a.emit(0x59)  # pop ecx
    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi
    a.emit(0x5B)  # pop ebx
    a.jmp_absolute(GET_FIRST_OBJECT)
    return a.finish()


def build_section(base_va: int) -> tuple[bytes, int, int]:
    """``(section content, stash thunk VA, rebind thunk VA)`` for a cave based at ``base_va``.

    The ring goes first, at the section's own base, so both thunks reach it by a resolved address
    and :meth:`~FoundationRebindPatch.verify` can check it is zero-initialised without knowing how
    long the code is."""
    ring_va = base_va
    stash_va = base_va + RING_SIZE
    stash = _build_stash(stash_va, ring_va)
    rebind_va = stash_va + len(stash)
    rebind = _build_rebind(rebind_va, ring_va)
    return bytes(RING_SIZE) + stash + rebind, stash_va, rebind_va


# --- the patch ----------------------------------------------------------------------------------


class FoundationRebindPatch(Patch):
    """Hand a settlement plot from the object `ReplaceSelfUpgrade` destroys to the one it
    creates, so the flag never resurfaces."""

    name = "foundation-rebind"
    author = "officialNecro"
    description = "A ReplaceSelfUpgrade keeps the settlement plot instead of freeing its flag"

    # --- apply / verify ----------------------------------------------------------------------

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        section_va = allocate_section(
            data,
            SECTION_NAME,
            lambda va: build_section(va)[0],
            SECTION_CHARACTERISTICS,
        )
        _content, stash_va, rebind_va = build_section(section_va)
        for file_off, old, new, note in self._edits(data, stash_va, rebind_va):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch (an empty list == verified).

        Recomputes the cave and both repointed ``call``s from the section base found on disk and
        compares them byte for byte, then re-checks every window the patch reads but does not
        rewrite. Reads only via ``struct`` and the section table - no disassembler."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located

        problems: list[str] = []
        try:
            content, stash_va, rebind_va = build_section(section_va)
            edits = self._edits(data, stash_va, rebind_va)
        except (ValueError, struct.error) as exc:
            return [f"cannot recompute the expected cave (wrong build?): {exc}"]

        got = bytes(data[section_off : section_off + len(content)])
        if got != content:
            problems.append(
                f"{SECTION_NAME} does not hold the expected ring and two thunks "
                "(the cave differs, or was built for another base address)"
            )
        for file_off, _old, new, note in edits:
            found = bytes(data[file_off : file_off + len(new)])
            if found != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {found.hex()}")

        problems += self._anchor_problems(data, skip_call_bytes=True)
        return problems

    # --- layout ------------------------------------------------------------------------------

    def _edits(
        self, data: bytes | bytearray, stash_va: int, rebind_va: int
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte range this patch rewrites, as ``(file offset, old, new, note)`` - two
        ``call rel32`` displacements, and nothing else."""
        edits: list[tuple[int, bytes, bytes, str]] = []
        for call_va, stock_va, thunk_va, note in (
            (
                HOOK_DESTROY_CALL_VA,
                DESTROY_OBJECT,
                stash_va,
                "ReplaceSelfUpgrade's destroyObject -> stash the plot",
            ),
            (
                HOOK_WALK_CALL_VA,
                GET_FIRST_OBJECT,
                rebind_va,
                "ReplaceSelfUpgrade's object walk -> rebind the plot",
            ),
        ):
            off = va_to_offset(data, call_va)
            if off is None:
                raise ValueError(f"{note}: VA 0x{call_va:08x} is not mapped")
            edits.append(
                (off, _call_bytes(call_va, stock_va), _call_bytes(call_va, thunk_va), note)
            )
        return edits

    # --- the build fingerprint ----------------------------------------------------------------

    def _anchor_problems(self, data: bytes | bytearray, skip_call_bytes: bool = False) -> list[str]:
        """Everything the patch depends on and does not rewrite.

        Three kinds, all silent when wrong: the two hook windows say the `call`s being repointed
        are the ones inside `upgradeImplementation` and that the frame slots hook 2 reads are still
        filled where it thinks; the foundation windows say ``m_builtOnID`` is still
        ``module+0x28`` and still reached through the ``+0x98`` interface query; and the two
        teardown windows say the paths this patch pre-empts are still the ones that free a plot.

        ``skip_call_bytes`` blanks the five bytes of each hooked `call`, which is what lets the
        same table check an already-patched image."""
        problems: list[str] = []
        hooked = {HOOK_DESTROY_CALL_VA, HOOK_WALK_CALL_VA}
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                problems.append(f"anchor 0x{va:08x} is not mapped - not the expected build")
                continue
            got = bytearray(data[off : off + len(expected)])
            want = bytearray(expected)
            if skip_call_bytes:
                for call_va in hooked:
                    at = call_va - va
                    if 0 <= at <= len(expected) - 5:
                        got[at : at + 5] = want[at : at + 5] = b"\x00" * 5
            if bytes(got) != bytes(want):
                problems.append(
                    f"anchor 0x{va:08x}: expected {bytes(want).hex()}, got {bytes(got).hex()}"
                )
        return problems

    def _check_anchors(self, data: bytes | bytearray) -> None:
        problems = self._anchor_problems(data)
        if problems:
            joined = "; ".join(problems)
            raise ValueError(f"foundation-rebind: this is not the expected build: {joined}")
