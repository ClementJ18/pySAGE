"""The wall-mesh-release patch: a destroyed wall gives back the pathfinding data it registered.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/raised-wall-mesh-removal.md``.

**The defect.** A walkable wall registers three separate things with the `Pathfinder`, in
``0x00935FAA``, and gives back none of them when it dies.

- The **walkable surface** named by `RaisedWallMesh` claims a slot in the sixteen-entry table at
  ``Pathfinder+0x60`` and pushes a render object onto that slot's list. `claimWallLayer`
  (``0x00768246``) and the list push beside it (``0x00768276``) have **exactly one caller each,
  and both are on the add path** - so this leg is not a removal that fails, it is a removal that
  was never written.
- The two **ramps** allocate a ``0xCC`` record each onto the list at ``Pathfinder+0x5C``. Their
  removal re-queries the drawable for `RampMesh1` / `RampMesh2` and matches the answer's geometry
  against the list (``0x009356DF``).
- The **bounds cells** named by `WallBoundsMesh` are marked into the pathfind grid. Their removal
  re-queries the drawable for that mesh too, and a NULL answer **returns from the function**
  (``0x009362AD``) before a single cell is unmarked.

The last two fail because a dying structure changes model before the teardown at ``0x00692313``
reaches the pathfinder, and a `RUBBLE` or `POST_RUBBLE` model does not contain the named
sub-objects. So the removal is not the inverse of the addition: it is the addition run again
against a model that no longer has anything to find. The symptom is units walking on air over a
wall that is gone, and fourteen wall-layer slots that are never given back for the rest of the
match.

**What this does.** The engine is made to *remember what it registered* instead of re-deriving it.
A ledger in the cave, keyed by `ObjectID`, is filled on the add path and consumed on the remove
path; where an entry exists it is authoritative, and where none does every path keeps the stock
answer exactly.

- **The walkable surface** is unlinked from the slot's list by the pointer that was recorded when
  it was pushed (the link is ``renderObj+0x3C``, the head is ``slot+0x38``), destroyed the way the
  engine destroys it, and - once the slot's list comes out empty - handed back through the
  engine's own ``0x00768AA7``. Slots are **shared between walls of equal height**, which is why
  the release is conditional on the list emptying rather than done once per wall.
- **The ramps** are unlinked by the recorded record pointer rather than by geometry, which answers
  the same question without needing a mesh to ask it of.
- **The bounds cells** need no new loop: the four frame slots holding the cell rectangle are
  restored from the ledger and control jumps to ``0x0093682F``, the head of the stock unmark loop,
  which reads exactly those four and dereferences no mesh.

**Why a ledger and not a stamped `ObjectID`.** Stamping the id into the layer slot cannot work:
the slot is shared, so it cannot say which of its members is dying. And nothing needs stamping -
``0x004BA693`` returns an object *derived* from the queried sub-object and releases the sub-object
itself, so what the slot holds is the pathfinder's own allocation, destroyed by ``0x00768AA7``. A
pointer recorded at add time therefore stays valid for exactly as long as the registration it
describes, and no engine structure has to grow.

**Both directions reach the bounds query.** ``0x00935FAA`` branches on `adding` at ``0x00935FDD``,
the two arms rejoin at ``0x0093629C``, and `adding` is read a *second* time at ``0x009365F9`` to
choose mark or unmark. The remove hook therefore sits on the query itself and tests `adding`
again, so an addition passes through it untouched.

**The ledger is cleared by the engine's own reset.** `Pathfinder::reset` (``0x006F5B03``) frees
the ramp list and releases all sixteen slots, so everything the ledger describes stops existing
between matches; the hook on its tail drops the table at the same moment, and nothing survives to
be matched against a recycled `ObjectID` in the next game.

**Bounded, and it degrades to stock rather than to a wrong answer.** The table describes
:data:`LEDGER_SLOTS` walls; a wall that does not fit registers exactly as it does today and is
removed exactly as it is today. The failure mode of a full table is the unpatched behaviour, not a
corrupt one - which is also the failure mode of a wall registered by some path this patch does not
see.

**Determinism.** This decides where units may walk, so **every peer must run the same patched
binary** and replays recorded on it will not play back on a stock one - the same rule as
`spawn-union` and `multi-execute-gate`.

**No INI surface.** There is no new keyword and no opt-in: the patch changes what an existing
`RaisedWallMesh` / `RampMesh1` / `RampMesh2` / `WallBoundsMesh` block does when its object is
removed. A mod needs no edit to benefit and cannot write anything to decline it.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. No other bundled patch touches ``0x00935FAA``, ``0x006F5B1F`` or
the slot accessors, and this patch reads nothing another patch rewrites.
"""

from __future__ import annotations

import struct

from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ENTRY_SIZE",
    "LEDGER_SLOTS",
    "SECTION_NAME",
    "WallMeshReleasePatch",
    "build_section",
]

# --- the engine ---------------------------------------------------------------------------------

#: `Drawable::getWallBoundsMesh` - iface `+0x98` through the draw-module walk. ``__thiscall``,
#: ``ret 4``, one out-parameter (the height). NULL when the current model has no such sub-object,
#: which is the early-out this patch hangs the removal on.
GET_WALL_BOUNDS_MESH = 0x006728D7

#: `Pathfinder::pushWallLayerMesh` - ``__thiscall``, ``ret 4``. Pushes a render object onto the
#: list headed at ``slot+0x38``, linking through the pushed object's own ``+0x3C``.
PUSH_WALL_LAYER_MESH = 0x00768276

#: `Pathfinder::claimWallLayer` - ``__thiscall``, ``ret 8`` (render object, layer index). Takes an
#: unused slot, refusing one whose ``+0x34`` or ``+0x38`` is set, and answers whether it took it.
CLAIM_WALL_LAYER = 0x00768246

#: `Pathfinder::releaseWallLayer` - ``__thiscall``, no arguments. Clears ``+0x34``, drops the
#: slot's cell data, destroys the render object at the head of ``+0x38``, and resets ``+0x18``
#: through ``+0x3C``. Identified by `Pathfinder::reset` looping it over all sixteen slots; it is
#: the inverse the RE document had recorded as not yet located.
RELEASE_WALL_LAYER = 0x00768AA7

#: The call inside `Pathfinder::reset` immediately after that loop, hooked so the ledger is
#: dropped at the one moment the engine drops everything the ledger describes.
RESET_TAIL_CALL_VA = 0x006F5B1F
RESET_TAIL_CALLEE = 0x00939F17

#: `operator delete` - ``__cdecl``, caller cleans. The engine pairs it with a scalar deleting
#: destructor called with a flag of 0, at ``0x00768AC1`` and again at ``0x006F5AF1``; both of this
#: patch's destroy sites reproduce that pair instruction for instruction.
OPERATOR_DELETE = 0x0042F6A0

#: `Object::m_id`.
OBJECT_ID_OFFSET = 0x74

#: The head of a wall-layer slot's render-object list, and the link field on the objects in it.
SLOT_LIST_HEAD_OFFSET = 0x38
RENDER_OBJ_NEXT_OFFSET = 0x3C

#: The other field `claimWallLayer` refuses a non-zero value in, alongside the list head. Read
#: only to reproduce that guard, so the add hook records exactly when the claim will succeed.
SLOT_IN_USE_OFFSET = 0x34

#: The head of the ramp-record list on the `Pathfinder`, and the link field on a ``0xCC`` record.
PATHFINDER_RAMP_LIST_OFFSET = 0x5C
RAMP_NEXT_OFFSET = 0x04

# --- the hooks ----------------------------------------------------------------------------------

#: `call PUSH_WALL_LAYER_MESH` on the add path's *share an existing slot* arm. ecx is the slot and
#: ``[esp+4]`` the render object.
HOOK_SHARE_SLOT_VA = 0x009360A1

#: `call CLAIM_WALL_LAYER` on the add path's *take a new slot* arm. ecx is the slot, ``[esp+4]``
#: the render object and ``[esp+8]`` the layer index.
HOOK_CLAIM_SLOT_VA = 0x009360CA

#: The two seven-byte windows immediately after each ramp record is constructed, where eax holds
#: the record (or 0 if the allocation failed). Both carry the identical pair
#: ``mov ecx,[esi+0x5C]; or dword [ebp-4],-1``, which is why one cave routine serves both.
HOOK_RAMP_WINDOWS: tuple[int, ...] = (0x00936138, 0x0093619B)
RAMP_WINDOW_STOCK = bytes.fromhex("8b4e5c834dfcff")

#: The call on the add path taken once the cell rectangle is final and before the marking loop
#: consumes it. `Object *` is in **edi** here, not ``[ebp+8]`` - the frame slot has already been
#: reused as scratch, by ``0x00936521``.
HOOK_RECT_VA = 0x00936617
HOOK_RECT_CALLEE = 0x00472958

#: `call GET_WALL_BOUNDS_MESH`, the query whose NULL answer abandons the removal. Both directions
#: reach it, so the cave tests `adding` itself.
HOOK_BOUNDS_VA = 0x009362A3

#: The head of the stock cell-unmark loop, which the removal jumps to with the object's id in eax
#: once the rectangle has been restored. Its only inputs are that id and the four frame slots -
#: everything else it touches it writes before reading, and unlike the *mark* branch it never
#: dereferences the bounds render object.
UNMARK_LOOP_VA = 0x0093682F

#: ``0x00935FAA``'s own frame slots, as displacements from its ebp. The rectangle is
#: ``i0``/``i1``/``j0``/``j1``; ``[ebp+8]`` is the `Object *` until ``0x00936521`` reuses it as
#: scratch, and ``[ebp+0xC]`` is `adding` until ``0x00936698`` does the same. Every hook here is
#: sited before its slot is reused, except the rectangle hook, which takes the object from edi.
FRAME_OBJECT = 0x08
FRAME_ADDING = 0x0C
FRAME_RECT_I0 = 0x38  # negative; emitted as a disp8 of -0x38
FRAME_RECT_I1 = 0x30
FRAME_RECT_J0 = 0x3C
FRAME_RECT_J1 = 0x34

#: Byte windows the patch depends on, as ``{va: expected bytes}``. The five repointed `call`s are
#: blanked by :meth:`~WallMeshReleasePatch.verify` before comparing, so the same table checks a
#: patched image; the rest are read-only anchors that pin the offsets above.
ANCHORS: dict[int, bytes] = {
    # `mov esi, ecx` in the prologue, and the `[ebp+8]` read beside it: esi is the `Pathfinder`
    # for the whole function, which is what the removal reads it as, and `Object *` is the first
    # argument
    0x00935FBA: bytes.fromhex("53568bf18b4d0857e84c80ddff"),
    # the add path's slot scan: `push 2; pop edi` and the `cmp edi,0xF` that bounds it, which is
    # what pins the table at +0x60 with wall slots 2..15. Cut in two at ``0x00936000`` because the
    # `push`/`pop` pair straddles a page, which the sparse stand-in the tests build cannot map.
    0x00935FF8: bytes.fromhex("0f84ed0000006a02"),
    0x00936000: bytes.fromhex("5f8d4dc4518bc8e820eddaff"),
    0x00936056: bytes.fromhex("4783c34083ff0f7eb3"),
    # the share arm and the claim arm, each ending in the call this patch repoints
    0x00936095: bytes.fromhex("ff75ecc1e7068d7c37608bcfe8d021e3ff"),
    0x009360BB: bytes.fromhex("8bc7c1e00657ff75ec8d5c30608bcbe87721e3ff"),
    # `claimWallLayer` - the two-field guard the add hook reproduces, and the layout it writes
    0x00768246: bytes.fromhex("33d23951347524395138751f8b442404894138"),
    # `pushWallLayerMesh` - proves the link is the pushed object's own +0x3C
    0x00768276: bytes.fromhex("8b51388b44240489503c894138c20400"),
    # `releaseWallLayer` - the inverse, and the head it destroys
    0x00768AA7: bytes.fromhex("568bf183663400e8dcf9ffff8b4e38"),
    # `Pathfinder::reset`: the ramp-list free, the release over all sixteen slots (which is what
    # pins both the table base and its count), then the call this patch repoints
    0x006F5B03: bytes.fromhex("6a10895e5c8d7e605d8bcfe8942f070083c7404d75f3"),
    0x006F5B19: bytes.fromhex("8d8e60040000e8f3432400"),
    # the two ramp windows, in context: the failed-allocation join before, the list link after
    0x00936136: bytes.fromhex("33c08b4e5c834dfcff894804"),
    0x00936199: bytes.fromhex("33c08b4e5c834dfcff894804"),
    # the rectangle's last two clamps, `adding`'s second read, and the call this patch repoints
    0x009365EE: bytes.fromhex("8b46203945d07e038945d0807d0c008b47740f842902"),
    0x00936611: bytes.fromhex("8d8ec0c10100e83cc3b3ff"),
    # the bounds query, its NULL early-out, and the unmark loop the removal diverts to
    0x009362A3: bytes.fromhex("e82fc6d3ff85c08945b80f84b9080000"),
    0x0093682F: bytes.fromhex("8945088d45088dbec0c1010050"),
    # the unmark loop's four rectangle reads, which is the whole of what it needs restored
    0x00936853: bytes.fromhex("8b45d03945c80f8f09010000"),
    0x0093686E: bytes.fromhex("8b45cc3945c40f8fd8000000"),
}

# --- the cave -----------------------------------------------------------------------------------

SECTION_NAME = ".wallrl"  # 7 chars: the PE name field is 8 bytes and truncates silently
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. Writable because the
# ledger lives in the same section as the code that reads it.
SECTION_CHARACTERISTICS = 0xE0000060

#: How many registered walls the ledger can describe at once. Edain's largest maps place a few
#: hundred wall segments; 512 covers them with room, and overflowing degrades to stock.
LEDGER_SLOTS = 512

#: One ledger entry: the key, what was registered, and the cell rectangle.
ENTRY_KEY = 0x00
ENTRY_SLOT = 0x04
ENTRY_SURFACE = 0x08
ENTRY_RAMP1 = 0x0C
ENTRY_RAMP2 = 0x10
ENTRY_I0 = 0x14
ENTRY_I1 = 0x18
ENTRY_J0 = 0x1C
ENTRY_J1 = 0x20
ENTRY_RECT_VALID = 0x24
ENTRY_SIZE = 0x28

LEDGER_SIZE = LEDGER_SLOTS * ENTRY_SIZE

#: Two dwords of cave scratch after the ledger: the entry the removal is working on, and the
#: `Pathfinder *` it was reached with. Globals rather than registers because the removal calls
#: engine code that is not documented to preserve esi, and because none of these routines can be
#: reached reentrantly - every one runs inside a single call of ``0x00935FAA``.
SCRATCH_ENTRY = LEDGER_SIZE
SCRATCH_PATHFINDER = LEDGER_SIZE + 4
SCRATCH_SIZE = 8


def _call_bytes(from_va: int, to_va: int) -> bytes:
    """The five bytes of ``call rel32`` sited at ``from_va``."""
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


def _disp8(offset: int) -> int:
    """A negative ebp displacement as the byte the ModRM form encodes."""
    return (-offset) & 0xFF


def _build_code(base_va: int, ledger_va: int) -> tuple[bytes, dict[str, int]]:
    """The cave's code, and the virtual address of each hook entry point.

    Laid out as one :class:`~..asm.Asm` so the helpers can be reached with `call rel32` to a
    label - their addresses are not known until the whole body has been emitted, which is exactly
    what labels exist for. The returned mapping is read with
    :meth:`~..asm.Asm.label_va`, so the entry addresses come from the layout that was actually
    emitted rather than from counting the bytes a second time."""
    entry_va = ledger_va + SCRATCH_ENTRY
    pathfinder_va = ledger_va + SCRATCH_PATHFINDER
    a = Asm(base_va)

    # --- helpers -------------------------------------------------------------------------------

    # _find: eax = ObjectID -> eax = entry, or 0. Never called with 0, which would match a free
    # slot; every caller tests the id first.
    a.label("_find")
    a.emit(0x51)  # push ecx
    a.emit(0x52)  # push edx
    a.emit(b"\xba", struct.pack("<I", ledger_va))  # mov edx, <ledger>
    a.emit(b"\xb9", struct.pack("<I", LEDGER_SLOTS))  # mov ecx, LEDGER_SLOTS
    a.label("_find.scan")
    a.emit(b"\x39\x02")  # cmp [edx], eax
    a.jcc_short(JE, "_find.hit")
    a.emit(b"\x81\xc2", struct.pack("<I", ENTRY_SIZE))  # add edx, ENTRY_SIZE
    a.emit(0x49)  # dec ecx
    a.jcc_short(JNE, "_find.scan")
    a.emit(b"\x33\xd2")  # xor edx, edx
    a.label("_find.hit")
    a.emit(b"\x8b\xc2")  # mov eax, edx
    a.emit(0x5A)  # pop edx
    a.emit(0x59)  # pop ecx
    a.emit(0xC3)  # ret

    # _alloc: eax = ObjectID -> eax = entry, or 0 when the table is full. Returns the existing
    # entry when there is one, so the four add hooks fill one row between them.
    a.label("_alloc")
    a.emit(0x52)  # push edx
    a.emit(0x51)  # push ecx
    a.emit(0x53)  # push ebx
    a.emit(b"\x8b\xd8")  # mov ebx, eax           ; the key, across the search for it
    a.call("_find")
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JNE, "_alloc.out")
    a.emit(b"\xba", struct.pack("<I", ledger_va))  # mov edx, <ledger>
    a.emit(b"\xb9", struct.pack("<I", LEDGER_SLOTS))  # mov ecx, LEDGER_SLOTS
    a.label("_alloc.scan")
    a.emit(b"\x83\x3a\x00")  # cmp dword [edx], 0    ; a free row has a zero key
    a.jcc_short(JE, "_alloc.take")
    a.emit(b"\x81\xc2", struct.pack("<I", ENTRY_SIZE))  # add edx, ENTRY_SIZE
    a.emit(0x49)  # dec ecx
    a.jcc_short(JNE, "_alloc.scan")
    a.emit(b"\x33\xd2")  # xor edx, edx          ; full: the caller falls back to stock
    a.jmp_short("_alloc.done")
    a.label("_alloc.take")
    # Zero the row before handing it out, then key it. A row is released by having its key
    # cleared and nothing else, so its other fields still describe whatever registered last.
    a.emit(b"\x33\xc9")  # xor ecx, ecx
    for field in range(0, ENTRY_SIZE, 4):
        a.emit(b"\x89\x4a", field)  # mov [edx+field], ecx
    a.emit(b"\x89\x5a", ENTRY_KEY)  # mov [edx+ENTRY_KEY], ebx
    a.label("_alloc.done")
    a.emit(b"\x8b\xc2")  # mov eax, edx
    a.label("_alloc.out")
    a.emit(0x5B)  # pop ebx
    a.emit(0x59)  # pop ecx
    a.emit(0x5A)  # pop edx
    a.emit(0xC3)  # ret

    # _object_id: eax = the current Object's id, or 0. Reads [ebp+8], which every hook but the
    # rectangle one is sited before the reuse of.
    a.label("_object_id")
    a.emit(b"\x8b\x45", FRAME_OBJECT)  # mov eax, [ebp+8]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JE, "_object_id.out")
    a.emit(b"\x8b\x40", OBJECT_ID_OFFSET)  # mov eax, [eax+0x74]
    a.label("_object_id.out")
    a.emit(0xC3)  # ret

    # _destroy: ecx = the object to destroy. The engine's own pair, as `releaseWallLayer` writes
    # it: the scalar deleting destructor with a flag of 0 (which destroys but does not free, and
    # returns `this`), then `operator delete` on what it returned.
    a.label("_destroy")
    a.emit(b"\x8b\x01")  # mov eax, [ecx]         ; vtable
    a.emit(b"\x6a\x00")  # push 0
    a.emit(b"\xff\x10")  # call [eax]             ; ret 4
    a.emit(0x50)  # push eax
    a.call_absolute(OPERATOR_DELETE)
    a.emit(0x59)  # pop ecx                ; __cdecl: the caller cleans
    a.emit(0xC3)  # ret

    # --- add hooks -----------------------------------------------------------------------------

    # H1a: the share-an-existing-slot arm. Entered by the repointed `call`, so [esp+4] is the
    # render object and ecx the slot; ends by tail-jumping to the routine it replaced, whose
    # `ret 4` returns to the instruction after the hooked call.
    a.label("share_slot")
    a.emit(0x50)  # push eax
    a.emit(0x51)  # push ecx                ; the slot, for the record and the tail jump
    a.emit(0x52)  # push edx
    a.call("_object_id")
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "share_slot.out")
    a.call("_alloc")
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "share_slot.out")
    a.emit(b"\x8b\x54\x24\x04")  # mov edx, [esp+4]     ; the saved slot
    a.emit(b"\x89\x50", ENTRY_SLOT)  # mov [eax+ENTRY_SLOT], edx
    a.emit(b"\x8b\x54\x24\x10")  # mov edx, [esp+0x10]  ; the render object argument
    a.emit(b"\x89\x50", ENTRY_SURFACE)  # mov [eax+ENTRY_SURFACE], edx
    a.label("share_slot.out")
    a.emit(0x5A)  # pop edx
    a.emit(0x59)  # pop ecx
    a.emit(0x58)  # pop eax
    a.jmp_absolute(PUSH_WALL_LAYER_MESH)

    # H1b: the take-a-new-slot arm. The same record, behind `claimWallLayer`'s own guard - the
    # claim is refused for a slot whose +0x34 or +0x38 is set, and a refused claim registers
    # nothing, so recording it would leave a row describing a slot this wall is not in.
    a.label("claim_slot")
    a.emit(0x50)  # push eax
    a.emit(0x51)  # push ecx
    a.emit(0x52)  # push edx
    a.emit(b"\x83\x79", SLOT_IN_USE_OFFSET, 0x00)  # cmp dword [ecx+0x34], 0
    a.jcc(JNE, "claim_slot.out")
    a.emit(b"\x83\x79", SLOT_LIST_HEAD_OFFSET, 0x00)  # cmp dword [ecx+0x38], 0
    a.jcc(JNE, "claim_slot.out")
    a.call("_object_id")
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "claim_slot.out")
    a.call("_alloc")
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "claim_slot.out")
    a.emit(b"\x8b\x54\x24\x04")  # mov edx, [esp+4]     ; the saved slot
    a.emit(b"\x89\x50", ENTRY_SLOT)  # mov [eax+ENTRY_SLOT], edx
    a.emit(b"\x8b\x54\x24\x10")  # mov edx, [esp+0x10]  ; the render object argument
    a.emit(b"\x89\x50", ENTRY_SURFACE)  # mov [eax+ENTRY_SURFACE], edx
    a.label("claim_slot.out")
    a.emit(0x5A)  # pop edx
    a.emit(0x59)  # pop ecx
    a.emit(0x58)  # pop eax
    a.jmp_absolute(CLAIM_WALL_LAYER)

    # H2: both ramp records. Entered by a `call` from a seven-byte window, with eax holding the
    # record just constructed (or 0 if the allocation failed), and ends by re-emitting the two
    # displaced instructions. eax has to survive: the caller's next instruction links the record
    # through it.
    a.label("ramp_record")
    a.emit(0x50)  # push eax
    a.emit(0x51)  # push ecx
    a.emit(0x52)  # push edx
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "ramp_record.out")
    a.emit(b"\x8b\xd0")  # mov edx, eax           ; the record
    a.call("_object_id")
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "ramp_record.out")
    a.emit(0x52)  # push edx
    a.call("_alloc")
    a.emit(0x5A)  # pop edx
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "ramp_record.out")
    a.emit(b"\x83\x78", ENTRY_RAMP1, 0x00)  # cmp dword [eax+ENTRY_RAMP1], 0
    a.jcc_short(JNE, "ramp_record.second")
    a.emit(b"\x89\x50", ENTRY_RAMP1)  # mov [eax+ENTRY_RAMP1], edx
    a.jmp_short("ramp_record.out")
    a.label("ramp_record.second")
    a.emit(b"\x89\x50", ENTRY_RAMP2)  # mov [eax+ENTRY_RAMP2], edx
    a.label("ramp_record.out")
    a.emit(0x5A)  # pop edx
    a.emit(0x59)  # pop ecx
    a.emit(0x58)  # pop eax
    # the displaced pair, last so that its flags reach the caller exactly as they did
    a.emit(b"\x8b\x4e", PATHFINDER_RAMP_LIST_OFFSET)  # mov ecx, [esi+0x5C]
    a.emit(b"\x83\x4d\xfc\xff")  # or dword [ebp-4], -1
    a.emit(0xC3)  # ret

    # H3: the cell rectangle, recorded once it is final and before the marking loop consumes it.
    # The object comes from edi, not [ebp+8] - that slot has been reused as scratch by now.
    a.label("record_rect")
    a.emit(0x50)  # push eax
    a.emit(0x51)  # push ecx
    a.emit(0x52)  # push edx
    a.emit(b"\x85\xff")  # test edi, edi
    a.jcc(JE, "record_rect.out")
    a.emit(b"\x8b\x47", OBJECT_ID_OFFSET)  # mov eax, [edi+0x74]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "record_rect.out")
    a.call("_alloc")
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "record_rect.out")
    for frame_slot, entry_field in (
        (FRAME_RECT_I0, ENTRY_I0),
        (FRAME_RECT_I1, ENTRY_I1),
        (FRAME_RECT_J0, ENTRY_J0),
        (FRAME_RECT_J1, ENTRY_J1),
    ):
        a.emit(b"\x8b\x55", _disp8(frame_slot))  # mov edx, [ebp-slot]
        a.emit(b"\x89\x50", entry_field)  # mov [eax+field], edx
    a.emit(b"\xc7\x40", ENTRY_RECT_VALID, struct.pack("<I", 1))  # mov dword [eax+..], 1
    a.label("record_rect.out")
    a.emit(0x5A)  # pop edx
    a.emit(0x59)  # pop ecx
    a.emit(0x58)  # pop eax
    a.jmp_absolute(HOOK_RECT_CALLEE)

    # --- the removal ---------------------------------------------------------------------------

    # _release_surface: unlink [entry+SURFACE] from [entry+SLOT]'s list and destroy it; if that
    # empties the list, hand the slot back through the engine's own release. Conditional because
    # slots are shared by height - another wall may still be standing on this one.
    a.label("_release_surface")
    a.emit(0x50)  # push eax
    a.emit(0x51)  # push ecx
    a.emit(0x52)  # push edx
    a.emit(b"\xa1", struct.pack("<I", entry_va))  # mov eax, [entry]
    a.emit(b"\x8b\x48", ENTRY_SLOT)  # mov ecx, [eax+ENTRY_SLOT]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "_release_surface.out")
    a.emit(b"\x8b\x40", ENTRY_SURFACE)  # mov eax, [eax+ENTRY_SURFACE]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "_release_surface.out")
    a.emit(b"\x39\x41", SLOT_LIST_HEAD_OFFSET)  # cmp [ecx+0x38], eax
    a.jcc(JNE, "_release_surface.search")
    a.emit(b"\x8b\x50", RENDER_OBJ_NEXT_OFFSET)  # mov edx, [eax+0x3C]
    a.emit(b"\x89\x51", SLOT_LIST_HEAD_OFFSET)  # mov [ecx+0x38], edx
    a.jmp("_release_surface.destroy")
    a.label("_release_surface.search")
    a.emit(b"\x8b\x51", SLOT_LIST_HEAD_OFFSET)  # mov edx, [ecx+0x38]
    a.label("_release_surface.walk")
    a.emit(b"\x85\xd2")  # test edx, edx
    a.jcc(JE, "_release_surface.out")  # not on this slot: leave everything alone
    a.emit(b"\x39\x42", RENDER_OBJ_NEXT_OFFSET)  # cmp [edx+0x3C], eax
    a.jcc_short(JE, "_release_surface.unlink")
    a.emit(b"\x8b\x52", RENDER_OBJ_NEXT_OFFSET)  # mov edx, [edx+0x3C]
    a.jmp("_release_surface.walk")
    a.label("_release_surface.unlink")
    a.emit(0x53)  # push ebx
    a.emit(b"\x8b\x58", RENDER_OBJ_NEXT_OFFSET)  # mov ebx, [eax+0x3C]
    a.emit(b"\x89\x5a", RENDER_OBJ_NEXT_OFFSET)  # mov [edx+0x3C], ebx
    a.emit(0x5B)  # pop ebx
    a.label("_release_surface.destroy")
    a.emit(0x51)  # push ecx                ; the slot, across the destructor
    a.emit(b"\x8b\xc8")  # mov ecx, eax
    a.call("_destroy")
    a.emit(0x59)  # pop ecx
    a.emit(b"\x83\x79", SLOT_LIST_HEAD_OFFSET, 0x00)  # cmp dword [ecx+0x38], 0
    a.jcc(JNE, "_release_surface.out")  # still shared: keep the slot
    a.call_absolute(RELEASE_WALL_LAYER)  # ecx = the slot
    a.label("_release_surface.out")
    a.emit(0x5A)  # pop edx
    a.emit(0x59)  # pop ecx
    a.emit(0x58)  # pop eax
    a.emit(0xC3)  # ret

    # _release_ramps: unlink each recorded record from the Pathfinder's list and destroy it. The
    # list is walked to prove the record is still on it, because the stock removal runs earlier in
    # the same function and may already have taken one by geometry.
    a.label("_release_ramps")
    a.emit(0x50)  # push eax
    a.emit(0x51)  # push ecx
    a.emit(0x52)  # push edx
    a.emit(0x53)  # push ebx
    for entry_field in (ENTRY_RAMP1, ENTRY_RAMP2):
        tag = f"_release_ramps.{entry_field:x}"
        a.emit(b"\xa1", struct.pack("<I", entry_va))  # mov eax, [entry]
        a.emit(b"\x8b\x58", entry_field)  # mov ebx, [eax+field]
        a.emit(b"\x85\xdb")  # test ebx, ebx
        a.jcc(JE, f"{tag}.done")
        a.emit(b"\x8b\x0d", struct.pack("<I", pathfinder_va))  # mov ecx, [pathfinder]
        a.emit(b"\x85\xc9")  # test ecx, ecx
        a.jcc(JE, f"{tag}.done")
        a.emit(b"\x8b\x51", PATHFINDER_RAMP_LIST_OFFSET)  # mov edx, [ecx+0x5C]  ; head
        a.emit(b"\x3b\xd3")  # cmp edx, ebx
        a.jcc(JNE, f"{tag}.search")
        a.emit(b"\x8b\x43", RAMP_NEXT_OFFSET)  # mov eax, [ebx+4]
        a.emit(b"\x89\x41", PATHFINDER_RAMP_LIST_OFFSET)  # mov [ecx+0x5C], eax
        a.jmp(f"{tag}.destroy")
        a.label(f"{tag}.search")
        a.label(f"{tag}.walk")
        a.emit(b"\x85\xd2")  # test edx, edx
        a.jcc(JE, f"{tag}.done")  # already off the list: stock took it
        a.emit(b"\x39\x5a", RAMP_NEXT_OFFSET)  # cmp [edx+4], ebx
        a.jcc_short(JE, f"{tag}.unlink")
        a.emit(b"\x8b\x52", RAMP_NEXT_OFFSET)  # mov edx, [edx+4]
        a.jmp(f"{tag}.walk")
        a.label(f"{tag}.unlink")
        a.emit(b"\x8b\x43", RAMP_NEXT_OFFSET)  # mov eax, [ebx+4]
        a.emit(b"\x89\x42", RAMP_NEXT_OFFSET)  # mov [edx+4], eax
        a.label(f"{tag}.destroy")
        a.emit(b"\x8b\xcb")  # mov ecx, ebx
        a.call("_destroy")
        a.label(f"{tag}.done")
    a.emit(0x5B)  # pop ebx
    a.emit(0x5A)  # pop edx
    a.emit(0x59)  # pop ecx
    a.emit(0x58)  # pop eax
    a.emit(0xC3)  # ret

    # H4: the bounds query, and the whole of the removal. Entered by the repointed `call`, so
    # [esp] is the return address, [esp+4] the caller's out-parameter and ecx the drawable.
    a.label("bounds_query")
    a.emit(0x51)  # push ecx
    a.emit(b"\x8b\x44\x24\x08")  # mov eax, [esp+8]      ; the caller's argument
    a.emit(0x50)  # push eax
    a.call_absolute(GET_WALL_BOUNDS_MESH)  # ret 4: cleans the copy just pushed
    a.emit(0x59)  # pop ecx                ; the drawable, restored
    # An addition, or a removal the engine can still do by itself, is nothing to do with us.
    a.emit(b"\x80\x7d", FRAME_ADDING, 0x00)  # cmp byte [ebp+0xC], 0
    a.jcc(JNE, "bounds_query.pass")
    a.emit(0x50)  # push eax               ; the query's answer
    a.emit(0x52)  # push edx
    a.emit(b"\x89\x35", struct.pack("<I", pathfinder_va))  # mov [pathfinder], esi
    # Clear the scratch entry first. Every exit below releases whatever it names, so a value left
    # behind by an earlier removal would be released a second time on behalf of this one.
    a.emit(b"\x83\x25", struct.pack("<I", entry_va), 0x00)  # and dword [entry], 0
    a.call("_object_id")
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "bounds_query.done")
    a.call("_find")
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "bounds_query.done")  # no ledger row: stock, exactly as today
    a.emit(b"\xa3", struct.pack("<I", entry_va))  # mov [entry], eax
    a.call("_release_surface")
    a.call("_release_ramps")
    a.emit(b"\xa1", struct.pack("<I", entry_va))  # mov eax, [entry]
    # With the mesh still there the stock path unmarks the cells itself, and with no rectangle
    # recorded there is nothing to divert to. Either way the row has done its work.
    a.emit(b"\x8b\x54\x24\x04")  # mov edx, [esp+4]      ; the saved answer
    a.emit(b"\x85\xd2")  # test edx, edx
    a.jcc(JNE, "bounds_query.done")
    a.emit(b"\x83\x78", ENTRY_RECT_VALID, 0x00)  # cmp dword [eax+RECT_VALID], 0
    a.jcc(JE, "bounds_query.done")
    for frame_slot, entry_field in (
        (FRAME_RECT_I0, ENTRY_I0),
        (FRAME_RECT_I1, ENTRY_I1),
        (FRAME_RECT_J0, ENTRY_J0),
        (FRAME_RECT_J1, ENTRY_J1),
    ):
        a.emit(b"\x8b\x50", entry_field)  # mov edx, [eax+field]
        a.emit(b"\x89\x55", _disp8(frame_slot))  # mov [ebp-slot], edx
    a.emit(b"\x83\x20\x00")  # and dword [eax], 0    ; release the row
    a.emit(0x5A)  # pop edx
    a.emit(0x58)  # pop eax                ; discard the saved answer
    a.emit(b"\x83\xc4\x08")  # add esp, 8            ; our return address and the caller's argument
    a.call("_object_id")  # the unmark loop wants the id in eax
    a.jmp_absolute(UNMARK_LOOP_VA)
    a.label("bounds_query.done")
    a.emit(b"\xa1", struct.pack("<I", entry_va))  # mov eax, [entry]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JE, "bounds_query.restore")
    a.emit(b"\x83\x20\x00")  # and dword [eax], 0    ; release the row
    a.emit(b"\x83\x25", struct.pack("<I", entry_va), 0x00)  # and dword [entry], 0
    a.label("bounds_query.restore")
    a.emit(0x5A)  # pop edx
    a.emit(0x58)  # pop eax                ; the query's answer, back where the caller wants it
    a.label("bounds_query.pass")
    a.emit(b"\xc2\x04\x00")  # ret 4

    # H5: `Pathfinder::reset`'s tail. Everything the ledger describes has just stopped existing,
    # so the table goes with it - which is what stops a recycled ObjectID in the next match
    # matching a row from this one.
    a.label("drop_ledger")
    a.emit(0x50)  # push eax
    a.emit(0x51)  # push ecx
    a.emit(0x52)  # push edx
    a.emit(b"\xb8", struct.pack("<I", ledger_va))  # mov eax, <ledger>
    a.emit(b"\xb9", struct.pack("<I", LEDGER_SLOTS))  # mov ecx, LEDGER_SLOTS
    a.emit(b"\x33\xd2")  # xor edx, edx
    a.label("drop_ledger.scan")
    a.emit(b"\x89\x10")  # mov [eax], edx        ; the key is what makes a row live
    a.emit(b"\x05", struct.pack("<I", ENTRY_SIZE))  # add eax, ENTRY_SIZE
    a.emit(0x49)  # dec ecx
    a.jcc_short(JNE, "drop_ledger.scan")
    a.emit(b"\x89\x15", struct.pack("<I", entry_va))  # mov [entry], edx
    a.emit(0x5A)  # pop edx
    a.emit(0x59)  # pop ecx
    a.emit(0x58)  # pop eax
    a.jmp_absolute(RESET_TAIL_CALLEE)

    code = a.finish()
    entries = {
        name: a.label_va(name)
        for name in (
            "share_slot",
            "claim_slot",
            "ramp_record",
            "record_rect",
            "bounds_query",
            "drop_ledger",
        )
    }
    return code, entries


def build_section(base_va: int) -> tuple[bytes, dict[str, int]]:
    """``(section content, {hook name: entry VA})`` for a cave based at ``base_va``.

    The ledger and the two scratch dwords go first, at the section's own base, so the code reaches
    them by a resolved address and :meth:`~WallMeshReleasePatch.verify` can check they are
    zero-initialised without knowing how long the code is."""
    ledger_va = base_va
    code_va = base_va + LEDGER_SIZE + SCRATCH_SIZE
    code, entries = _build_code(code_va, ledger_va)
    return bytes(LEDGER_SIZE + SCRATCH_SIZE) + code, entries


# --- the patch ----------------------------------------------------------------------------------


class WallMeshReleasePatch(Patch):
    """Give back the wall-layer slot, ramp records and pathfind cells a destroyed wall
    registered, instead of leaking them for the rest of the match."""

    name = "wall-mesh-release"
    author = "officialNecro"
    description = (
        "A destroyed WALK_ON_TOP_OF_WALL wall releases the pathfinding data it registered - its "
        "wall-layer slot, its two ramp records and its walkable cells - instead of leaving them "
        "behind because the removal re-queries a model that has already changed. No INI change "
        "and no opt-in: it fixes what an existing RaisedWallMesh / RampMesh1 / RampMesh2 / "
        "WallBoundsMesh block already does"
    )

    #: The five `call rel32` sites this patch repoints, as ``(va, stock callee, cave entry, note)``
    #: keyed by the entry name :func:`build_section` returns.
    _CALL_HOOKS: tuple[tuple[int, int, str, str], ...] = (
        (HOOK_SHARE_SLOT_VA, PUSH_WALL_LAYER_MESH, "share_slot", "share a wall-layer slot"),
        (HOOK_CLAIM_SLOT_VA, CLAIM_WALL_LAYER, "claim_slot", "claim a wall-layer slot"),
        (HOOK_RECT_VA, HOOK_RECT_CALLEE, "record_rect", "record the cell rectangle"),
        (HOOK_BOUNDS_VA, GET_WALL_BOUNDS_MESH, "bounds_query", "the bounds query, and the removal"),
        (
            RESET_TAIL_CALL_VA,
            RESET_TAIL_CALLEE,
            "drop_ledger",
            "Pathfinder::reset drops the ledger",
        ),
    )

    # --- apply / verify ----------------------------------------------------------------------

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        section_va = allocate_section(
            data,
            SECTION_NAME,
            lambda va: build_section(va)[0],
            SECTION_CHARACTERISTICS,
        )
        _content, entries = build_section(section_va)
        for file_off, old, new, note in self._edits(data, entries):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch (an empty list == verified).

        Recomputes the cave and every rewritten site from the section base found on disk and
        compares them byte for byte, then re-checks every window the patch reads but does not
        rewrite. Reads only via ``struct`` and the section table - no disassembler."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located

        problems: list[str] = []
        try:
            content, entries = build_section(section_va)
            edits = self._edits(data, entries)
        except (ValueError, struct.error) as exc:
            return [f"cannot recompute the expected cave (wrong build?): {exc}"]

        got = bytes(data[section_off : section_off + len(content)])
        if got != content:
            problems.append(
                f"{SECTION_NAME} does not hold the expected ledger and hooks "
                "(the cave differs, or was built for another base address)"
            )
        for file_off, _old, new, note in edits:
            found = bytes(data[file_off : file_off + len(new)])
            if found != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {found.hex()}")

        problems += self._anchor_problems(data, patched=True)
        return problems

    # --- layout ------------------------------------------------------------------------------

    def _edits(
        self, data: bytes | bytearray, entries: dict[str, int]
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte range this patch rewrites, as ``(file offset, old, new, note)``: five
        ``call rel32`` displacements, and the two seven-byte ramp windows."""
        edits: list[tuple[int, bytes, bytes, str]] = []
        for call_va, stock_va, entry, note in self._CALL_HOOKS:
            off = va_to_offset(data, call_va)
            if off is None:
                raise ValueError(f"{note}: VA 0x{call_va:08x} is not mapped")
            edits.append(
                (off, _call_bytes(call_va, stock_va), _call_bytes(call_va, entries[entry]), note)
            )
        # Each ramp window is a `call` to the cave plus two `nop`s: the routine re-emits the pair
        # it displaced, so nothing of the original is lost.
        replacement_tail = b"\x90\x90"
        for window_va in HOOK_RAMP_WINDOWS:
            off = va_to_offset(data, window_va)
            if off is None:
                raise ValueError(f"ramp window: VA 0x{window_va:08x} is not mapped")
            new = _call_bytes(window_va, entries["ramp_record"]) + replacement_tail
            edits.append((off, RAMP_WINDOW_STOCK, new, f"record a ramp record @0x{window_va:08x}"))
        return edits

    # --- the build fingerprint ----------------------------------------------------------------

    def _anchor_problems(self, data: bytes | bytearray, patched: bool = False) -> list[str]:
        """Everything the patch depends on and does not rewrite.

        Four kinds, all silent when wrong: the add-path windows say the two slot arms are still
        the ones this patch records from; the slot-accessor windows say the list head is still
        ``+0x38`` and the link still the pushed object's own ``+0x3C``, which is what the removal
        walks; `Pathfinder::reset` pins the table's base and count and the call the ledger is
        dropped from; and the removal windows say the bounds query, its early-out and the unmark
        loop's four rectangle reads are all where the cave believes.

        ``patched`` blanks the bytes this patch rewrites, which is what lets the same table check
        an already-patched image."""
        problems: list[str] = []
        rewritten: list[tuple[int, int]] = [(va, 5) for va, _s, _e, _n in self._CALL_HOOKS]
        rewritten += [(va, len(RAMP_WINDOW_STOCK)) for va in HOOK_RAMP_WINDOWS]
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                problems.append(f"anchor 0x{va:08x} is not mapped - not the expected build")
                continue
            got = bytearray(data[off : off + len(expected)])
            want = bytearray(expected)
            if patched:
                for site_va, length in rewritten:
                    at = site_va - va
                    if 0 <= at <= len(expected) - length:
                        got[at : at + length] = want[at : at + length] = b"\x00" * length
            if bytes(got) != bytes(want):
                problems.append(
                    f"anchor 0x{va:08x}: expected {bytes(want).hex()}, got {bytes(got).hex()}"
                )
        return problems

    def _check_anchors(self, data: bytes | bytearray) -> None:
        problems = self._anchor_problems(data)
        if problems:
            joined = "; ".join(problems)
            raise ValueError(f"wall-mesh-release: this is not the expected build: {joined}")
