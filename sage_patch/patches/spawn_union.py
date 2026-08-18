"""Let an object's `SPAWNS_ARE_THE_WEAPONS` spawns come from **every** `SpawnBehavior` it has.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../docs/spawn-behavior-union.md``.

**What the engine does today.** `Object::getSpawnBehaviorInterface` (:data:`GETTER_VA`) walks the
NULL-terminated `BehaviorModule *` array at `Object+0x24C` and **returns on the first module that
answers**, so an object with two `SpawnBehavior`s uses the first one for everything the interface
reaches: ordering slaves to attack, asking whether any slave can attack, finding the closest slave,
and - the part that is a plain bug rather than a missing feature - being told that a slave died.
`onSpawnDeath` (`0x00862DAB`) opens with a `find` over its *own* slave list and returns having done
nothing when the id is not in it, so the second behavior's slaves die without a list removal, a
live-count decrement, or a respawn timer. The second behavior still *spawns*; that is its own
update, and nothing routes it through this getter.

**What this does.** Replaces the getter with one that counts the modules answering. Nothing (return
NULL) and exactly one (return it) are the stock answers, byte for byte, which is every object in
the game bar a handful. Two or more returns a **proxy**: `{void *vtbl; Object *obj;}` living in the
cave, whose sixteen-slot vtable re-walks the module list and aggregates. That works because every
caller uses the pointer the way the disassembly shows - ``mov edx,[eax] / mov ecx,eax /
call [edx+N]`` - and none of the thirteen stores it past its own basic block.

Aggregation is per slot, in :data:`IFACE_SLOTS`: `void` methods **broadcast** to every behavior,
predicates are **OR**ed, and `getClosestSlave` re-runs the distance comparison the stock
implementation does internally (`0x0086292C` keeps a running minimum of :data:`DISTANCE_SQUARED_2D`)
because "the first behavior's closest slave" is the original bug with extra steps.

Nothing short-circuits. Every predicate here is pure - each only reads its own slave list - but
calling all of them regardless costs two indirect calls on an object that has two behaviors and
removes the assumption entirely.

Three slots (`+0x34`, `+0x38`, `+0x3C`) are snapshot and update machinery reached through the
*module*, never through this getter: no caller of :data:`GETTER_VA` touches them. Their proxy
entries are an `int3`, so an assumption that turns out to be wrong stops at the instruction that
was wrong instead of silently returning a plausible value into a savegame.

**Reentrancy.** Ordering slaves runs slave AI that can re-enter the getter, so a single static
proxy would be clobbered mid-call. The cave holds a ring of :data:`RING_SIZE`; the proxy carries no
state but the `Object *`, so a nested call simply gets the next slot.

**This is a simulation change.** Unlike `replay-outcome` and `skirmish-replay` it changes what
units do, so it has to be on **every peer**, and a replay recorded against it will not play back on
a stock build. It is deterministic: the module list is in INI order, which is identical everywhere.

**Composition.** Order-independent: the cave is allocated with
:func:`~..utils.allocate_section` past every existing section and :meth:`verify` finds it by name,
the only edited bytes are the five at the head of :data:`GETTER_VA`, and the three structures read
and not written - the getter's own body, `SpawnBehavior`'s interface vtable, and its second-vtable
answer - are ones nothing else rewrites. See the composition contract on
:class:`~..patcher.Patch`.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from ..asm import JBE, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "ANY",
    "BROADCAST",
    "CLOSEST",
    "DISTANCE_SQUARED_2D",
    "GETTER_VA",
    "IFACE_SLOTS",
    "IFACE_VTABLE_VA",
    "MODULE_LIST",
    "RING_SIZE",
    "SECOND_VTABLE",
    "SECTION_NAME",
    "SPAWN_ANSWER_THUNK",
    "SPAWN_IFACE_SLOT",
    "SPAWN_SECOND_VTABLE_VA",
    "STOCK_GETTER",
    "STOCK_IFACE_VTABLE",
    "UNREACHABLE",
    "SpawnUnionPatch",
    "build_section",
]

#: `Object::getSpawnBehaviorInterface`. 32 bytes, `__thiscall`, no stack arguments, plain `ret`;
#: the next function starts at `0x0068C3C3`. Thirteen `call` sites and **no other reference**, so
#: replacing its head reaches every user.
GETTER_VA = 0x0068C3A3
STOCK_GETTER = bytes.fromhex(
    "56"  # push esi
    "8bb14c020000"  # mov  esi, [ecx+0x24c]
    "eb0f"  # jmp  .next
    "8d480c"  # lea  ecx, [eax+0xc]
    "8b01"  # mov  eax, [ecx]
    "ff5078"  # call [eax+0x78]
    "85c0"  # test eax, eax
    "7509"  # jne  .done
    "83c604"  # add  esi, 4
    "8b06"  # mov  eax, [esi]
    "85c0"  # test eax, eax
    "75eb"  # jne  .ask
    "5e"  # pop  esi
    "c3"  # ret
)

#: `Object+0x24C` is the NULL-terminated `BehaviorModule *` array; a module's second vtable is at
#: `module+0x0C`, and its interface getters are slots of that. Also in `live-object-model.md`.
MODULE_LIST = 0x24C
SECOND_VTABLE = 0x0C
SPAWN_IFACE_SLOT = 0x78

#: `SpawnBehavior`'s second vtable, and what it answers with: the folded thunk
#: ``lea eax,[ecx-0xc] / add ecx,0x14 / neg / sbb / and`` - "`this` ? `this+0x14` : NULL", and
#: `(module+0x0C)+0x14` is `module+0x20`, whose vtable is :data:`IFACE_VTABLE_VA`.
SPAWN_SECOND_VTABLE_VA = 0x00C58DD8
SPAWN_ANSWER_THUNK = 0x008A18E0

#: `SpawnBehaviorInterface`'s vtable as `SpawnBehavior` fills it, sixteen slots. Used as a
#: fingerprint: all sixteen must match before anything is written, which pins the class, the slot
#: layout and the build at once.
IFACE_VTABLE_VA = 0x00C58D94
STOCK_IFACE_VTABLE = (
    0x00862351,
    0x00862DAB,
    0x0086292C,
    0x008637BE,
    0x00863807,
    0x00862990,
    0x008629ED,
    0x00862A4E,
    0x00863850,
    0x008623D6,
    0x00862E4F,
    0x0086277F,
    0x0086327C,
    0x008633A4,
    0x006530FA,
    0x00850C4E,
)

#: `Object::getDistanceSquared2D(const Coord3D *)` - `__thiscall`, `ret 4`, result in `st0`. The
#: helper `getClosestSlave` uses internally, reused so the merged minimum is computed the same way.
DISTANCE_SQUARED_2D = 0x0066137C
STOCK_DISTANCE_HELPER = bytes.fromhex(
    "8b442404"  # mov eax, [esp+4]
    "d94138"  # fld dword [ecx+0x38]
    "d820"  # fsub dword [eax]
    "d9413c"  # fld dword [ecx+0x3c]
    "d86004"  # fsub dword [eax+4]
)

BROADCAST = "broadcast"
CLOSEST = "closest"
ANY = "any"
UNREACHABLE = "unreachable"

#: The interface, slot by slot: ``(slot, stack argument count, aggregation, what it is)``. Argument
#: counts are read off the call sites rather than guessed, and match each implementation's `ret n`.
IFACE_SLOTS = (
    (0x00, 1, ANY, "maySpawnSelfTaskAI(Real)"),
    (0x04, 2, BROADCAST, "onSpawnDeath(ObjectID, DamageInfo *)"),
    (0x08, 1, CLOSEST, "getClosestSlave(const Coord3D *)"),
    (0x0C, 3, BROADCAST, "order the slaves to attack an object"),
    (0x10, 3, BROADCAST, "order the slaves to attack a position"),
    (0x14, 3, ANY, "can any slave attack this target"),
    (0x18, 4, ANY, "can any slave use a weapon against this target"),
    (0x1C, 0, ANY, "is any slave able to attack at all"),
    (0x20, 1, BROADCAST, "pass an order down to every slave's AI"),
    (0x24, 0, BROADCAST, "clear the behavior's own flag"),
    (0x28, 0, BROADCAST, "tell each slave who its spawner is"),
    (0x2C, 0, ANY, "read the behavior's own flag"),
    (0x30, 0, BROADCAST, "run the respawn timers"),
    (0x34, None, UNREACHABLE, "the module's own update"),
    (0x38, None, UNREACHABLE, "Snapshot::xfer"),
    (0x3C, None, UNREACHABLE, "Snapshot::loadPostProcess"),
)

#: How many proxies the ring holds. One per level of reentrancy that is live at once; ordering
#: slaves runs slave AI that comes back through the getter, and eight is far past that depth.
RING_SIZE = 8

SECTION_NAME = ".spwnun"
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE - the ring is written.
_CHARACTERISTICS = 0xE0000060


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _jmp_bytes(from_va: int, to_va: int) -> bytes:
    return b"\xe9" + struct.pack("<i", to_va - (from_va + 5))


def _walk_head(a: Asm, tag: str, zero_edi: bool) -> None:
    """Emit a stub's prologue and the head of the module walk, up to the interface in `eax`.

    Every stub saves `esi` and `edi` whether or not it uses both, so one displacement rule covers
    all of them: with the return address and two saved registers below it, argument *i* sits at
    ``[esp + 0x0c + 4i]``, and the reverse pushes that forward it all use the single displacement
    :func:`_arg_displacement` returns."""
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    a.emit(b"\x8b\x71\x04")  # mov esi, [ecx+4]        ; the proxy's Object *
    a.emit(b"\x8b\xb6", _u32(MODULE_LIST))  # mov esi, [esi+0x24c]
    if zero_edi:
        a.emit(b"\x33\xff")  # xor edi, edi        ; the OR accumulator
    a.label(f"{tag}_next")
    a.emit(b"\x8b\x06")  # mov  eax, [esi]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, f"{tag}_done")
    a.emit(b"\x8d\x48\x0c")  # lea  ecx, [eax+0xc]
    a.emit(b"\x8b\x01")  # mov  eax, [ecx]
    a.emit(b"\xff\x50", SPAWN_IFACE_SLOT)  # call [eax+0x78]  ; the interface, or NULL
    a.emit(b"\x85\xc0")  # test eax, eax


def _arg_displacement(nargs: int, saved: int) -> int:
    """Where a stub's arguments sit while it is pushing them back out.

    ``saved`` counts the dwords the stub pushed below them. Pushing argument *j* as the *k*-th push
    puts it at ``base + 4j + 4k`` and the reverse order makes ``j + k`` the constant ``nargs - 1``,
    which is why the engine's own forwarding loops repeat one displacement."""
    return 4 + 4 * saved + 4 * (nargs - 1)


def _forward(a: Asm, slot: int, nargs: int, saved: int) -> None:
    """Call slot ``slot`` on the interface in `eax`, with this stub's own arguments."""
    displacement = _arg_displacement(nargs, saved)
    for _ in range(nargs):
        a.emit(b"\xff\x74\x24", displacement)  # push dword [esp+d]
    a.emit(b"\x8b\x10")  # mov  edx, [eax]
    a.emit(b"\x8b\xc8")  # mov  ecx, eax
    a.emit(b"\xff\x52", slot)  # call [edx+slot]   ; callee-cleaned


def _tail(a: Asm, nargs: int) -> None:
    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi
    if nargs:
        a.emit(0xC2, struct.pack("<H", 4 * nargs))  # ret 4n
    else:
        a.emit(0xC3)  # ret


def _broadcast_stub(a: Asm, slot: int, nargs: int) -> None:
    """Call this slot on every `SpawnBehavior` the object has, and return nothing."""
    tag = f"s{slot:02x}"
    _walk_head(a, tag, zero_edi=False)
    a.jcc(JE, f"{tag}_skip")
    _forward(a, slot, nargs, saved=2)
    a.label(f"{tag}_skip")
    a.emit(b"\x83\xc6\x04")  # add esi, 4
    a.jmp(f"{tag}_next")
    a.label(f"{tag}_done")
    _tail(a, nargs)


def _any_stub(a: Asm, slot: int, nargs: int) -> None:
    """OR this predicate across every `SpawnBehavior`, asking all of them.

    `edi` carries the accumulator, which is why it is a saved register rather than the padding it
    is in :func:`_broadcast_stub`. The whole of `eax` is set on the way out: the stock
    implementations disagree about whether they write `al` or `eax`, and a caller that compares the
    full register (`0x006C8A1D` does) must not read the high bytes of a leftover pointer."""
    tag = f"s{slot:02x}"
    _walk_head(a, tag, zero_edi=True)
    a.jcc(JE, f"{tag}_skip")
    _forward(a, slot, nargs, saved=2)
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, f"{tag}_skip")
    a.emit(0xBF, _u32(1))  # mov edi, 1
    a.label(f"{tag}_skip")
    a.emit(b"\x83\xc6\x04")  # add esi, 4
    a.jmp(f"{tag}_next")
    a.label(f"{tag}_done")
    a.emit(b"\x8b\xc7")  # mov eax, edi
    _tail(a, nargs)


def _closest_stub(a: Asm, slot: int) -> None:
    """`getClosestSlave`, merged: the nearest of each behavior's nearest.

    The stock implementation (`0x0086292C`) keeps a running minimum over its own slaves, so taking
    the first behavior's answer would reproduce exactly the bug this patch exists to remove. The
    comparison is the stock one, `comiss` and `jbe` included, so an unordered result keeps the
    incumbent the way the engine's own loop does.

    Locals, from `esp` on entry to the loop body: `[esp]` the candidate's distance, `[esp+4]` the
    best distance so far. `ebx` holds the candidate across the distance call, `edi` the best object
    (also the "have one yet" flag, since a NULL slave is never a candidate)."""
    tag = f"s{slot:02x}"
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    a.emit(b"\x6a\x00")  # push 0             ; best distance
    a.emit(b"\x6a\x00")  # push 0             ; this candidate's distance
    a.emit(b"\x8b\x71\x04")  # mov esi, [ecx+4]
    a.emit(b"\x8b\xb6", _u32(MODULE_LIST))  # mov esi, [esi+0x24c]
    a.emit(b"\x33\xff")  # xor edi, edi       ; no candidate yet
    displacement = _arg_displacement(1, saved=5)  # 3 saved registers + 2 locals

    a.label(f"{tag}_next")
    a.emit(b"\x8b\x06")  # mov  eax, [esi]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, f"{tag}_done")
    a.emit(b"\x8d\x48\x0c")  # lea  ecx, [eax+0xc]
    a.emit(b"\x8b\x01")  # mov  eax, [ecx]
    a.emit(b"\xff\x50", SPAWN_IFACE_SLOT)  # call [eax+0x78]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, f"{tag}_skip")

    a.emit(b"\xff\x74\x24", displacement)  # push dword [esp+d]   ; the Coord3D *
    a.emit(b"\x8b\x10")  # mov  edx, [eax]
    a.emit(b"\x8b\xc8")  # mov  ecx, eax
    a.emit(b"\xff\x52", slot)  # call [edx+8]         ; -> Object *, or NULL
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, f"{tag}_skip")

    a.emit(b"\x8b\xd8")  # mov  ebx, eax        ; the candidate
    a.emit(b"\xff\x74\x24", displacement)  # push dword [esp+d]
    a.emit(b"\x8b\xcb")  # mov  ecx, ebx
    a.call_absolute(DISTANCE_SQUARED_2D)  # call <getDistanceSquared2D>
    a.emit(b"\xd9\x1c\x24")  # fstp dword [esp]     ; the candidate's distance
    a.emit(b"\x85\xff")  # test edi, edi
    a.jcc(JE, f"{tag}_take")
    a.emit(b"\xf3\x0f\x10\x4c\x24\x04")  # movss  xmm1, [esp+4]  ; the best so far
    a.emit(b"\x0f\x2f\x0c\x24")  # comiss xmm1, [esp]
    a.jcc(JBE, f"{tag}_skip")  # best <= candidate (or unordered): keep it
    a.label(f"{tag}_take")
    a.emit(b"\x8b\x04\x24")  # mov  eax, [esp]
    a.emit(b"\x89\x44\x24\x04")  # mov  [esp+4], eax
    a.emit(b"\x8b\xfb")  # mov  edi, ebx

    a.label(f"{tag}_skip")
    a.emit(b"\x83\xc6\x04")  # add esi, 4
    a.jmp(f"{tag}_next")
    a.label(f"{tag}_done")
    a.emit(b"\x8b\xc7")  # mov  eax, edi
    a.emit(b"\x83\xc4\x08")  # add  esp, 8
    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi
    a.emit(0x5B)  # pop ebx
    a.emit(0xC2, struct.pack("<H", 4))  # ret 4


def _entry(a: Asm, ring_index_va: int, ring_va: int, vtable_va: int) -> None:
    """The replacement getter: stock for none and for one, a ring proxy for two or more.

    `ebx` holds the object, `esi` the module cursor, `edi` the first interface found. Finding a
    second one leaves the walk immediately - what the count is past two does not change the
    answer."""
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    a.emit(b"\x8b\xd9")  # mov  ebx, ecx
    a.emit(b"\x8b\xb3", _u32(MODULE_LIST))  # mov  esi, [ebx+0x24c]
    a.emit(b"\x33\xff")  # xor  edi, edi
    a.label("entry_next")
    a.emit(b"\x8b\x06")  # mov  eax, [esi]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "entry_done")
    a.emit(b"\x8d\x48\x0c")  # lea  ecx, [eax+0xc]
    a.emit(b"\x8b\x01")  # mov  eax, [ecx]
    a.emit(b"\xff\x50", SPAWN_IFACE_SLOT)  # call [eax+0x78]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "entry_skip")
    a.emit(b"\x85\xff")  # test edi, edi
    a.jcc(JNE, "entry_proxy")  # a second one: aggregate
    a.emit(b"\x8b\xf8")  # mov  edi, eax
    a.label("entry_skip")
    a.emit(b"\x83\xc6\x04")  # add  esi, 4
    a.jmp("entry_next")

    a.label("entry_done")
    a.emit(b"\x8b\xc7")  # mov  eax, edi        ; NULL, or the only one
    a.label("entry_return")
    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi
    a.emit(0x5B)  # pop ebx
    a.emit(0xC3)  # ret

    a.label("entry_proxy")
    a.emit(0xA1, _u32(ring_index_va))  # mov  eax, [ring_index]
    a.emit(0x40)  # inc  eax
    a.emit(b"\x83\xe0", RING_SIZE - 1)  # and  eax, RING_SIZE-1
    a.emit(0xA3, _u32(ring_index_va))  # mov  [ring_index], eax
    a.emit(b"\xc1\xe0\x03")  # shl  eax, 3          ; 8 bytes per proxy
    a.emit(0x05, _u32(ring_va))  # add  eax, <ring>
    a.emit(b"\xc7\x00", _u32(vtable_va))  # mov  dword [eax], <vtable>
    a.emit(b"\x89\x58\x04")  # mov  [eax+4], ebx    ; the object
    a.jmp("entry_return")


def build_section(base_va: int) -> tuple[bytes, dict[str, int]]:
    """Return ``(section content, {label: VA})`` for a cave based at ``base_va``.

    Laid out so nothing refers forward: the ring first (addressed as link-time constants), then the
    per-slot stubs, then the vtable that names them, then the entry point that names the vtable."""
    a = Asm(base_va)
    a.label("ring_index")
    a.emit(bytes(4))
    a.label("ring")
    a.emit(bytes(8 * RING_SIZE))

    a.label("dead")
    a.emit(0xCC)  # int3 - see the module docstring on the three unreachable slots

    for slot, nargs, mode, _note in IFACE_SLOTS:
        if mode == UNREACHABLE:
            continue
        if nargs is None:  # only an unreachable slot may leave its stack size unstated
            raise ValueError(f"slot +0x{slot:02x} is {mode} but has no argument count")
        a.label(f"slot_{slot:02x}")
        if mode == BROADCAST:
            _broadcast_stub(a, slot, nargs)
        elif mode == ANY:
            _any_stub(a, slot, nargs)
        else:
            _closest_stub(a, slot)

    while (a.va - base_va) % 4:
        a.emit(0x90)  # nop, so the vtable is dword-aligned
    a.label("vtable")
    for slot, _nargs, mode, _note in IFACE_SLOTS:
        label = "dead" if mode == UNREACHABLE else f"slot_{slot:02x}"
        a.emit(_u32(a.label_va(label)))

    a.label("entry")
    _entry(a, a.label_va("ring_index"), a.label_va("ring"), a.label_va("vtable"))

    labels = {
        name: a.label_va(name)
        for name in ("ring_index", "ring", "dead", "vtable", "entry", "entry_proxy")
    }
    labels.update(
        {
            f"slot_{slot:02x}": a.label_va(f"slot_{slot:02x}")
            for slot, _n, mode, _note in IFACE_SLOTS
            if mode != UNREACHABLE
        }
    )
    return a.finish(), labels


class SpawnUnionPatch(Patch):
    """Aggregate every `SpawnBehavior` on an object instead of using only the first."""

    name = "spawn-union"
    author = "officialNecro"
    description = (
        "SPAWNS_ARE_THE_WEAPONS uses every SpawnBehavior's spawns, not just the first. No INI "
        "change - declaring a second SpawnBehavior is all it takes"
    )

    def apply(self, data: bytearray) -> None:
        self._check_getter(data)
        self._check_interface(data)
        self._check_distance_helper(data)
        section_va = allocate_section(
            data, SECTION_NAME, lambda va: build_section(va)[0], _CHARACTERISTICS
        )
        # The layout is a pure function of the base VA, so re-deriving it costs nothing and keeps
        # `build_section` a plain callable.
        _content, labels = build_section(section_va)
        for file_off, old, new, note in self._edits(data, labels):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch (an empty list == verified). Locates
        the cave, recomputes what it should hold, and compares it and the repointed getter to what
        is on disk. Reads only via ``struct`` + the section table, so verification needs no
        disassembler."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located

        problems: list[str] = []
        try:
            content, labels = build_section(section_va)
            edits = self._edits(data, labels)
        except (ValueError, struct.error) as exc:
            return [f"cannot recompute the expected cave (wrong build?): {exc}"]

        got = bytes(data[section_off : section_off + len(content)])
        if got != content:
            # The ring is written at runtime, so a live process legitimately differs there.
            ring_end = labels["ring"] - section_va + 8 * RING_SIZE
            if got[ring_end:] != content[ring_end:]:
                problems.append(f"{SECTION_NAME} does not hold this patch's stubs")

        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")
        return problems

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """No parameters. Which behaviors an object has is the mod's business, and there is no
        useful half of this to switch off: the first-only rule is either in force or it is not."""

    def _check_getter(self, data: bytes | bytearray) -> None:
        """Assert the getter is still the whole 32-byte walk this patch replaces.

        The strongest single fingerprint available: the module-list offset, the second-vtable hop
        and the interface slot are all immediates inside it, so one comparison pins every constant
        the cave reuses."""
        off = va_to_offset(data, GETTER_VA)
        if off is None:
            raise ValueError(f"getSpawnBehaviorInterface 0x{GETTER_VA:08x} is not mapped")
        got = bytes(data[off : off + len(STOCK_GETTER)])
        if got != STOCK_GETTER:
            raise ValueError(
                f"getSpawnBehaviorInterface @0x{GETTER_VA:08x}: expected {STOCK_GETTER.hex()}, "
                f"got {got.hex()} - this is not the expected build"
            )

    def _check_interface(self, data: bytes | bytearray) -> None:
        """Assert `SpawnBehavior` still answers with the vtable whose slots the proxy mirrors.

        Two halves, and both are needed. The second-vtable entry says *which* subobject the getter
        hands back, and the interface vtable says what its sixteen slots are - a build that kept
        the getter but reordered the interface would otherwise be patched into calling the wrong
        method with the wrong argument count."""
        off = va_to_offset(data, SPAWN_SECOND_VTABLE_VA + SPAWN_IFACE_SLOT)
        if off is None:
            raise ValueError(
                f"SpawnBehavior's second vtable 0x{SPAWN_SECOND_VTABLE_VA:08x} is not mapped"
            )
        answer = struct.unpack_from("<I", data, off)[0]
        if answer != SPAWN_ANSWER_THUNK:
            raise ValueError(
                f"SpawnBehavior's interface slot +0x{SPAWN_IFACE_SLOT:x} is 0x{answer:08x}, "
                f"not the 0x{SPAWN_ANSWER_THUNK:08x} thunk this patch's slot map is derived from"
            )

        off = va_to_offset(data, IFACE_VTABLE_VA)
        if off is None:
            raise ValueError(f"the interface vtable 0x{IFACE_VTABLE_VA:08x} is not mapped")
        for index, expected in enumerate(STOCK_IFACE_VTABLE):
            got = struct.unpack_from("<I", data, off + index * 4)[0]
            if got != expected:
                raise ValueError(
                    f"SpawnBehaviorInterface slot +0x{index * 4:02x}: expected 0x{expected:08x}, "
                    f"found 0x{got:08x} - the interface is not the one this patch mirrors"
                )

    def _check_distance_helper(self, data: bytes | bytearray) -> None:
        """Assert the distance helper still takes its `Coord3D` on the stack and the object in
        `ecx`. The merged `getClosestSlave` calls it directly, and a helper of a different shape
        would compare two numbers computed from the wrong fields rather than fail."""
        off = va_to_offset(data, DISTANCE_SQUARED_2D)
        if off is None:
            raise ValueError(f"the distance helper 0x{DISTANCE_SQUARED_2D:08x} is not mapped")
        got = bytes(data[off : off + len(STOCK_DISTANCE_HELPER)])
        if got != STOCK_DISTANCE_HELPER:
            raise ValueError(
                f"the distance helper @0x{DISTANCE_SQUARED_2D:08x}: expected "
                f"{STOCK_DISTANCE_HELPER.hex()}, got {got.hex()} - this is not the expected build"
            )

    def _edits(
        self, data: bytes | bytearray, labels: dict[str, int]
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte range this patch rewrites, as ``(file offset, old, new, note)``.

        One: five bytes at the head of the getter. Its remaining 27 go dead - nothing branches into
        the middle of it, and the thirteen `call` sites all name its first byte."""
        off = va_to_offset(data, GETTER_VA)
        if off is None:
            raise ValueError(f"getSpawnBehaviorInterface 0x{GETTER_VA:08x} is not mapped")
        return [
            (
                off,
                STOCK_GETTER[:5],
                _jmp_bytes(GETTER_VA, labels["entry"]),
                "getSpawnBehaviorInterface -> cave",
            )
        ]
