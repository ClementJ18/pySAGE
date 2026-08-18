"""The cooldown-through-death patch: a hero's special-power cooldown survives being revived.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../../docs/cooldown-through-death.md``.

**The premise, corrected.** A hero has two ways back from death and they disagree about object
identity. `RespawnUpdate` respawning in place (``0x008B3B08``) teleports **the object that died**
to the keep and restores its health, so every module - and every cooldown - comes back untouched;
that path already does what this patch is for, in the ticking flavour. The citadel revive does not:
`ReviveMgr::reviveHero` (``0x0078142F``) builds a **brand-new** `Object` through
`TheThingFactory` (``0x007814C2``) and re-applies a snapshot taken at death, so a freshly
constructed `SpecialPowerModule` comes back with `readyFrame` zero and the power ready. That is the
path every `Command = REVIVE` hero takes, and the one this patch changes.

**Nothing resets a cooldown on death, so there is no gate to flip.** `setReadyFrame` - interface
slot ``+0x20``, the folded ``mov [ecx+8], eax; ret 4`` at ``0x0099344A`` - has exactly four callers
that reach it through `Object::getSpecialPowerModule`: three script-engine actions and
`HeroDie::onDie` (``0x008C64FE``), which clears the **one** power named on that module. The cooldown
is not cleared by dying; it is discarded with the object.

**What this does.** Extends the snapshot the engine already takes. Where `RespawnUpdate`'s die
handler adds the hero to the player's revive list (``0x008B3879``), each special power that is on
cooldown and flagged banks ``(readyFrame, duration, deathFrame)``; where `reviveHero` restores the
upgrade mask onto the new object (``0x00781592``), each flagged power reads it back. Two `call
rel32` sites, both already doing exactly this job for experience and upgrades.

Two `SpecialPower` booleans, and the second one is the absence of arithmetic
-------------------------------------------------------------------------------
``PersistCooldownOnDeath``   carry the cooldown across the revive at all. Default `No` - stock.

``CooldownTicksWhileDead``   whether the cooldown keeps *elapsing* while the hero is dead.

With ``now`` the frame of the revive::

    No   (frozen)   readyFrame = now + (stored readyFrame - stored deathFrame)
    Yes  (ticking)  readyFrame = stored readyFrame, and if that frame has already passed there
                    is nothing to write - the freshly built module is already ready

so "dead long enough clears it" costs no timer and no expiry sweep: it is the branch that writes
nothing. Both fields are restored, never just the ready frame, because `getPercentReady`
(``0x00896CF2``) is ``1 - (readyFrame - now) / duration`` and moving one without the other snaps the
button clock - the artefact [`recharge-rescale.md`](../../docs/recharge-rescale.md) §3.3 works
through.

Where the two booleans live
---------------------------
`SpecialPowerTemplate` is `0x88` bytes and puts two `Bool`s at ``+0x58`` (`PublicTimer`) and
``+0x59`` (`SharedSyncedTimer`) ahead of an `AsciiString` at ``+0x5C`` - so ``+0x5A`` and ``+0x5B``
are interior padding. Nothing names them in the field table, the constructor never writes them and
the copy constructor never copies them, which is exactly why they need three single-bit edits
rather than none:

* the constructor's ``mov byte [esi+0x58], bl`` becomes ``mov dword [esi+0x58], ebx`` - ``88`` to
  ``89``, three bytes for three - so both new fields read `No` when a mod never names them. `ebx` is
  the zero the surrounding stores already use. Without this they would start as heap garbage and
  the patch would change behaviour on data that never asked for it;
* the copy constructor's ``mov al, [ebp+0x58]`` / ``mov [ebx+0x58], al`` widen the same way
  (``8a``/``88`` to ``8b``/``89``), so a block naming a `DefaultSpecialPower` inherits them. `eax`
  is already the scratch register the copies either side use.

The field table is rebuilt in the cave with two appended `Bool` rows and its two `imm32` references
repointed - the smallest table repoint in this package.

The store
---------
A brand-new object cannot carry anything, so the cooldowns wait in a table in the cave: a fixed
1024 slots of ``(owner, hero template, power template, readyFrame, duration, deathFrame)``, scanned
linearly, an entry free when its power pointer is NULL. Keyed on the **hero's `ThingTemplate`**
rather than on the revive record, deliberately: a hero template is unique per player in this engine
and both ends hold it (``Object+0x04`` at death, the new object's own at revive), where the record's
identity is the one thing the RE left open - ``0x00781792`` appends unconditionally, so a hero
already listed from the player template may end up with two records.

An entry is consumed by the restore that reads it, so the table holds only heroes who are dead
right now, and a hero revived twice without dying in between gets stock behaviour. **Both ends fail
open**: a full table, an unrecognised module flavour, a `SharedSyncedTimer` power, a power not on
cooldown - every one of them writes nothing and leaves the engine exactly as it was.

**Not in a savegame.** The table is the patch's own memory and nothing `Xfer`s it, so a save and
load between the death and the revive loses the snapshot and the hero returns ready - stock
behaviour, not a corrupt one, and the table is rebuilt on every death. Putting it in the
``0xE8``-byte revive record instead would survive a load, at the cost of every stride constant, the
copy path, the constructor and the xfer; the doc's §4.2 is that trade.

**Determinism.** Both hooks run on the logic thread, over the object's module list in its own
order, from state every peer holds identically - so the table's contents are the same on every
machine. What that does *not* survive is a mixed lobby: `readyFrame` gates whether an ability can
fire, so an unpatched peer disagrees on the frame a revived hero's power comes back, and the keyword
is fatal on a stock build anyway - SAGE treats an unknown field in a known block as a parse error.

**Composition.** Order-independent. The cave is allocated past every existing section and `verify`
finds it by name; the field table is located from its live references, so it appends to whatever is
there. `hero-mana` rebuilds the *same* table and grows the same struct to `0x8C` - the two compose,
because this patch reads the live table rather than the stock one and never touches an allocation
site, the copy constructor's epilogue (`hero-mana`'s hook, ``0x007B1F53``, is 0x53 bytes past the
copy edits here) or the tail `hero-mana` adds. `recharge-rescale` rewrites the same two fields on a
*living* object from a per-frame sweep; the pair this patch restores is self-consistent, so its
comparison finds nothing to do on the frame after a revive.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, FieldDelta

from ...addresses import (
    FIELD_PARSE_STRIDE,
    GAME_LOGIC_FRAME,
    GET_FINAL_OVERRIDE,
    INI_PARSE_BOOL,
    OBJECT_THING_TEMPLATE,
    SPECIAL_POWER_FIELD_TABLE_REF_OPCODES,
    SPECIAL_POWER_FIELD_TABLE_REFS,
    THE_GAME_LOGIC,
)
from ...asm import JAE, JB, JBE, JE, JLE, JNE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset
from ..utils.field_tables import Entry, entries_before, read_field_table, resolve_table

if TYPE_CHECKING:
    import argparse

__all__ = [
    "DEFAULT_PERSIST_KEYWORD",
    "DEFAULT_TICKS_KEYWORD",
    "SECTION_NAME",
    "SLOTS",
    "CooldownThroughDeathPatch",
    "build_code",
    "build_table",
    "rewritten_copy_load",
    "rewritten_copy_store",
    "rewritten_ctor",
    "validate_keyword",
]

SECTION_NAME = ".ctd"  # the PE name field is 8 bytes and truncates silently

#: The INI keywords the two new `SpecialPower` fields are parsed under.
DEFAULT_PERSIST_KEYWORD = "PersistCooldownOnDeath"
DEFAULT_TICKS_KEYWORD = "CooldownTicksWhileDead"

#: CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. The cave holds the rebuilt
#: table and the routines, and - unlike every other patch in this package - a table it **writes**.
SECTION_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

# --- SpecialPowerTemplate ------------------------------------------------------------------

#: The two padding bytes between `SharedSyncedTimer` and the `AsciiString` at `+0x5C`.
TEMPLATE_PERSIST = 0x5A
TEMPLATE_TICKS = 0x5B
TEMPLATE_SHARED_SYNCED_TIMER = 0x59

#: The constructor's `PublicTimer` store, and the copy constructor's load/store pair for the same
#: byte. All three are widened from byte to dword in place - one opcode bit each, same length.
TEMPLATE_CTOR_BOOLS = 0x007B1FD0
TEMPLATE_CTOR_BOOLS_BYTES = bytes.fromhex("885e58")  # mov byte [esi+0x58], bl
TEMPLATE_COPY_LOAD = 0x007B1F00
TEMPLATE_COPY_LOAD_BYTES = bytes.fromhex("8a4558")  # mov al, [ebp+0x58]
TEMPLATE_COPY_STORE = 0x007B1F03
TEMPLATE_COPY_STORE_BYTES = bytes.fromhex("884358")  # mov [ebx+0x58], al

# --- the special-power module --------------------------------------------------------------

SPI_DURATION = 0x04
SPI_READY_FRAME = 0x08
SPI_VTABLE_TEMPLATE_SLOT = 0x18  # getSpecialPowerTemplate
SPI_VTABLE_RECHARGE_SLOT = 0x3C  # startPowerRecharge - the flavour discriminator
SPI_VTABLE = 0x00C64FF0

#: `SpecialAbilityUpdate::startPowerRecharge`, flavour 1: the implementation whose ready frame is at
#: interface `+0x08` and whose duration is at `+0x04`. The other one (``0x00991500``, three vtables)
#: keeps no duration at all, so there is nothing coherent to snapshot - the flavour test fails
#: closed on it and on anything else.
START_POWER_RECHARGE = 0x00896E31

MODULE_INTERFACE = 0x0C  # BehaviorModuleInterface subobject, module +0xC
GET_SPECIAL_POWER_SLOT = 0x20  # its getSpecialPower - the idiom at 0x008979F5
OBJECT_MODULES = 0x24C  # NULL-terminated BehaviorModule *[]

GET_CONTROLLING_PLAYER = 0x0068B678  # __thiscall, no args -> Player * or NULL

# --- the two hook sites --------------------------------------------------------------------

#: `RespawnUpdate`'s die handler, at the call that adds the hero to the player's revive list. Taken
#: rather than the experience store six instructions later because `ebx` is the dying `Object` here
#: and because the two tests in between - an experience tracker, a readable record - would otherwise
#: decide silently which heroes get a snapshot.
ADD_HERO_CALL = 0x008B3879
ADD_HERO_CALL_BYTES = bytes.fromhex("e814dfecff")  # call 0x781792
ADD_HERO = 0x00781792  # ReviveMgr::addHero(Object *, Bool), ret 8 -> the new record's index
ADD_HERO_RESUME = 0x008B387E

#: `ReviveMgr::reviveHero`, at the call that restores the upgrade mask onto the object it has just
#: built. `esi` is that new object, and its modules exist - it was constructed 0xD0 bytes earlier.
UPGRADE_MASK_CALL = 0x00781592
UPGRADE_MASK_CALL_BYTES = bytes.fromhex("e8d5b6f0ff")  # call 0x68cc6c
UPGRADE_MASK_RESTORE = 0x0068CC6C
UPGRADE_MASK_RESUME = 0x00781597

# --- the cave's own table ------------------------------------------------------------------

#: One banked cooldown. `power` NULL means the slot is free, which is also how a restore releases
#: one - so the table holds only heroes who are dead right now.
SLOT_OWNER = 0x00
SLOT_HERO = 0x04
SLOT_POWER = 0x08
SLOT_READY = 0x0C
SLOT_DURATION = 0x10
SLOT_DEATH = 0x14
SLOT_STRIDE = 0x18

#: How many cooldowns can be in flight at once. Eight players, twenty heroes each and four flagged
#: powers apiece is 640 in the worst case nobody plays; a full table is not an error, it is the
#: hero whose slot did not fit behaving exactly as it does on a stock binary.
SLOTS = 1024

#: Fields the live `SpecialPower` table must still carry at these offsets, or this is not the build
#: the padding claim was derived against. Checked by name, so another patch having appended to the
#: same table first is fine; `PublicTimer` and `SharedSyncedTimer` are the two the padding sits
#: behind and `PalantirMovie` is what closes it, so the three of them together are the claim.
FINGERPRINT = {
    "Flags": 0x18,
    "ReloadTime": 0x20,
    "PublicTimer": 0x58,
    "SharedSyncedTimer": TEMPLATE_SHARED_SYNCED_TIMER,
    "PalantirMovie": 0x5C,
}

#: Byte windows the patch depends on and does not rewrite, as ``{va: expected bytes}``. Every one of
#: them is silent when wrong. The first two pin the hooks in their context - which register holds
#: the object, and that the call being displaced is the one named. The next pin the layout the caves
#: read and write: the ready frame at `+0x08` and the duration at `+0x04` from the site that writes
#: them, and from `getPercentReady`'s denominator, which is why both have to move together. The
#: module walk and the flavour test each pin their own idiom, and the last says `reviveHero` still
#: builds an object rather than returning the one that died.
ANCHORS: dict[int, bytes] = {
    # the die handler: `push eax; push ebx; call addHero; mov ebx,[ebx+0x26c]` - ebx is the Object
    # on both sides of the call, which is the whole reason this is the site
    0x008B3877: bytes.fromhex("5053e814dfecff8b9b6c02000085db"),
    # reviveHero: the record copy is pushed, ecx is the new object's mask, then the displaced call
    0x00781585: bytes.fromhex("8d850cffffff508d8e8c020000e8d5b6f0ff"),
    # newObject through TheThingFactory - the fact that makes this patch necessary at all
    0x007814BA: bytes.fromhex("8b0d404ade005057e89701f5ff"),
    # startPowerRecharge's full-recharge stores: readyFrame at +0x08, duration at +0x04
    0x00896F75: bytes.fromhex("a12c41de008b404003c78946088b0d2c41de002b4140894604c6461800"),
    # getPercentReady's denominator - the second reader, and why both fields move together
    0x00896D8F: bytes.fromhex("8b4604db460485c07d06d8059886bd00def9d82d0819bd00"),
    # the SharedSyncedTimer divert: the byte the snapshot tests before storing anything
    0x00896E6C: bytes.fromhex("e8cb1edfff807859007410ff75f48b4d"),
    # `getSpecialPower`: [module+0xC] vtable slot +0x20, the query both walks copy
    0x008979F5: bytes.fromhex("83c00c8b108bc8ff5220"),
    # the curse fan-out - the canonical NULL-terminated Object+0x24C module walk
    0x0068BDD0: bytes.fromhex(
        "568bb14c020000eb16d94424088d480c8b0151d91c24ff90ac00000083c6048b0685c075e4"
    ),
    # one vtable of each flavour, at the slot the flavour test reads
    0x00C6502C: struct.pack("<I", START_POWER_RECHARGE),
    0x00C6512C: struct.pack("<I", 0x00991500),
    # the callees, each with the convention the caves call it with
    0x0068B678: bytes.fromhex("8b891c03000085c97405e9e846110033c0c3"),
    0x00688D3C: bytes.fromhex("8bc18b500485d2740e"),
    0x008969CA: bytes.fromhex("8b41f48b4008c3"),  # getSpecialPowerTemplate, plain ret
    # the constructor and copy constructor, either side of the three widened stores
    0x007B1FC6: bytes.fromhex("f30f114650f30f114654885e58885e59895e5c"),
    0x007B1EFA: bytes.fromhex("8b45548943548a45588843588a45598843598d455c"),
}

# An INI keyword is matched by exact compare, so anything the parser could never match is a typo
# rather than a choice. The engine's own field names are CamelCase with digits and underscores.
_KEYWORD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")


def validate_keyword(keyword: str) -> None:
    """Raise unless ``keyword`` is a token the engine's INI reader could ever match."""
    if not _KEYWORD_PATTERN.match(keyword):
        raise ValueError(
            "an INI keyword must be letters, digits and underscores starting with a letter "
            f"(the reader matches it by exact compare), got {keyword!r}"
        )


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


@dataclass(frozen=True)
class _Layout:
    """Where each piece of the cave sits, given its base address, the two keywords and how many
    rows the live field table turned out to have.

    Pure arithmetic on those, so :meth:`CooldownThroughDeathPatch.apply` and
    :meth:`CooldownThroughDeathPatch.verify` compute the same addresses from opposite directions.
    The slot table is laid out **before** the code and not after it, so that every address the code
    needs is known without first knowing how long the code is."""

    epoch_va: int
    persist_va: int
    ticks_va: int
    table_va: int
    slots_va: int
    code_va: int


#: The epoch opens the cave and the two keyword strings follow it, back to back, which is what lets
#: :meth:`CooldownThroughDeathPatch.detect` read them out of a binary it knows nothing else about.
_EPOCH_OFFSET = 0
_PERSIST_OFFSET = 4


def _layout(base_va: int, persist: str, ticks: str, rows: int) -> _Layout:
    persist_va = base_va + _PERSIST_OFFSET
    ticks_va = persist_va + len(persist) + 1
    end = ticks_va + len(ticks) + 1
    table_va = end + (-end % 4)  # keep the table's dwords aligned
    slots_va = table_va + (rows + 3) * FIELD_PARSE_STRIDE  # + two rows + the terminator
    return _Layout(
        base_va + _EPOCH_OFFSET,
        persist_va,
        ticks_va,
        table_va,
        slots_va,
        slots_va + SLOTS * SLOT_STRIDE,
    )


def rewritten_ctor() -> bytes:
    """The constructor's `PublicTimer` store, widened to zero the two new fields as well.

    ``mov byte [esi+0x58], bl`` becomes ``mov dword [esi+0x58], ebx``: one opcode bit, three bytes
    for three, so there is no hook and no displaced instruction. `ebx` is zero throughout the
    constructor - it is what `SharedSyncedTimer` is defaulted with three bytes later, and that
    store stays exactly where it is, redundant and harmless."""
    return bytes([0x89]) + TEMPLATE_CTOR_BOOLS_BYTES[1:]


def rewritten_copy_load() -> bytes:
    """The copy constructor's ``mov al, [ebp+0x58]``, widened to a dword load. `ebp` is the
    *source* template in this routine, not a frame pointer."""
    return bytes([0x8B]) + TEMPLATE_COPY_LOAD_BYTES[1:]


def rewritten_copy_store() -> bytes:
    """Its matching ``mov [ebx+0x58], al``, widened to a dword store. `eax` is already the scratch
    register the copies either side of it use, so nothing else has to move."""
    return bytes([0x89]) + TEMPLATE_COPY_STORE_BYTES[1:]


def build_table(entries: tuple[Entry, ...], persist_va: int, ticks_va: int) -> bytes:
    """The rebuilt field-parse table: the live rows verbatim, the two new `Bool`s, the terminator.

    The live rows are copied rather than rewritten because every pointer in them is absolute -
    their keyword strings stay where they are - and only the two new rows point into the cave."""
    table = bytearray()
    for entry in entries:
        table += struct.pack("<IIII", *entry)
    table += struct.pack("<IIII", persist_va, INI_PARSE_BOOL, 0, TEMPLATE_PERSIST)
    table += struct.pack("<IIII", ticks_va, INI_PARSE_BOOL, 0, TEMPLATE_TICKS)
    return bytes(table) + bytes(FIELD_PARSE_STRIDE)


def _emit_find(a: Asm, slots_va: int) -> None:
    """``find(eax = power template, esi = Object, edi = Player, dl = allocate) -> eax = slot|NULL``.

    A linear scan, because it runs on a hero's death and on a hero's revive and nowhere else -
    twice a minute in a busy match, against a table three orders of magnitude smaller than the
    object list `GameLogic::update` already walks every frame. The first free slot is remembered on
    the way past, so an allocating call never needs a second pass.

    Preserves ebx, esi, edi and ebp; clobbers eax, ecx and edx."""
    a.label("find")
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(b"\x8b\x5e", OBJECT_THING_TEMPLATE)  # mov ebx, [esi+4]   ; the hero's ThingTemplate
    a.emit(0xBE, _u32(slots_va))  # mov esi, <slots>              ; the cursor
    a.emit(b"\x33\xc9")  # xor ecx, ecx                           ; the first free slot seen

    a.label("find_loop")
    a.emit(0x81, 0xFE, _u32(slots_va + SLOTS * SLOT_STRIDE))  # cmp esi, <end>
    a.jcc(JAE, "find_miss")
    a.emit(b"\x83\x7e", SLOT_POWER, 0x00)  # cmp dword [esi+8], 0
    a.jcc_short(JE, "find_free")
    a.emit(b"\x39\x3e")  # cmp [esi], edi                         ; the owning Player
    a.jcc_short(JNE, "find_next")
    a.emit(b"\x39\x5e", SLOT_HERO)  # cmp [esi+4], ebx            ; the hero
    a.jcc_short(JNE, "find_next")
    a.emit(b"\x39\x46", SLOT_POWER)  # cmp [esi+8], eax           ; the power
    a.jcc_short(JNE, "find_next")
    a.emit(b"\x8b\xc6")  # mov eax, esi
    a.jmp("find_out")

    a.label("find_free")
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc_short(JNE, "find_next")
    a.emit(b"\x8b\xce")  # mov ecx, esi                           ; remember the first one only

    a.label("find_next")
    a.emit(b"\x83\xc6", SLOT_STRIDE)  # add esi, 0x18
    a.jmp("find_loop")

    a.label("find_miss")
    a.emit(b"\x84\xd2")  # test dl, dl                            ; allocating?
    a.jcc_short(JE, "find_fail")
    a.emit(b"\x85\xc9")  # test ecx, ecx                          ; was there a free slot?
    a.jcc_short(JE, "find_fail")
    a.emit(b"\x89\x39")  # mov [ecx], edi
    a.emit(b"\x89\x59", SLOT_HERO)  # mov [ecx+4], ebx
    a.emit(b"\x89\x41", SLOT_POWER)  # mov [ecx+8], eax
    a.emit(b"\x8b\xc1")  # mov eax, ecx
    a.jmp_short("find_out")

    a.label("find_fail")
    a.emit(b"\x33\xc0")  # xor eax, eax                           ; full: the caller does nothing

    a.label("find_out")
    a.emit(0x5E)  # pop esi
    a.emit(0x5B)  # pop ebx
    a.emit(0xC3)  # ret


def _emit_sync(a: Asm, epoch_va: int, slots_va: int) -> None:
    """``sync()`` - drop everything banked if the logic clock is not the one that banked it.

    The table is the patch's own memory and the engine never clears it, so without this it outlives
    the match that filled it. That matters because two of its three key components survive a match
    too: `ThingTemplate`s are owned by the factory for the life of the process, and a new match's
    `Player` can land on the address an old one had. A hero who died in one match and was never
    revived would then hand a cooldown to whoever matched that key in the next one.

    A logic frame that has gone **backwards** is the signal, and it is exact for both ways this
    happens: a new match restarts the counter, and loading a savegame rewinds it - and after a load,
    anything banked belongs to a timeline that no longer exists, so wiping is what that case wants
    too. Cheap by construction: it runs twice per hero death, compares two dwords, and only touches
    the table on the frame the answer changes.

    Clobbers eax, ecx and edx; called from inside `pushad`."""
    a.label("sync")
    a.emit(0xA1, _u32(THE_GAME_LOGIC))  # mov eax, [TheGameLogic]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "sync_out")
    a.emit(b"\x8b\x40", GAME_LOGIC_FRAME)  # mov eax, [eax+0x40]   ; now
    a.emit(0x3B, 0x05, _u32(epoch_va))  # cmp eax, [epoch]
    a.jcc(JAE, "sync_keep")  # the clock moved forward, as it does on every other call

    a.emit(0xB9, _u32(slots_va))  # mov ecx, <slots>
    a.label("sync_wipe")
    a.emit(b"\x83\x61", SLOT_POWER, 0x00)  # and dword [ecx+8], 0  ; free, without clearing a key
    a.emit(b"\x83\xc1", SLOT_STRIDE)  # add ecx, 0x18
    a.emit(0x81, 0xF9, _u32(slots_va + SLOTS * SLOT_STRIDE))  # cmp ecx, <end>
    a.jcc(JB, "sync_wipe")

    a.label("sync_keep")
    a.emit(0xA3, _u32(epoch_va))  # mov [epoch], eax
    a.label("sync_out")
    a.emit(0xC3)  # ret


def _emit_flavour(a: Asm, out: str) -> None:
    """The flavour test, shared by both per-power routines: is this the implementation whose ready
    frame is at ``+0x08``? Anything else - flavour 2, or a module type this reading has never heard
    of - leaves with the interface untouched. ``ebx`` is the interface."""
    a.emit(b"\x8b\x03")  # mov eax, [ebx]                         ; its vtable
    a.emit(b"\x8b\x40", SPI_VTABLE_RECHARGE_SLOT)  # mov eax, [eax+0x3c]
    a.emit(0x3D, _u32(START_POWER_RECHARGE))  # cmp eax, <startPowerRecharge>
    a.jcc(JNE, out)


def _emit_template(a: Asm, out: str) -> None:
    """``eax = getFinalOverride(getSpecialPowerTemplate(ebx))``, or leave via ``out``.

    Through the override chain on both ends, so the pointer the snapshot keys on is the same one
    the restore looks up, and so the two flag bytes are read off whatever override is current."""
    a.emit(b"\x8b\x13")  # mov edx, [ebx]
    a.emit(b"\x8b\xcb")  # mov ecx, ebx
    a.emit(b"\xff\x52", SPI_VTABLE_TEMPLATE_SLOT)  # call [edx+0x18]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, out)
    a.emit(b"\x8b\xc8")  # mov ecx, eax
    a.call_absolute(GET_FINAL_OVERRIDE)
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, out)


def _emit_snapshot_power(a: Asm) -> None:
    """``snap(eax = SpecialPowerModuleInterface *, esi = Object *, edi = Player *)``.

    Banks one cooldown, if there is one worth banking. The frame, as displacements from ``ebp``:
    ``-0x04`` the current frame, ``-0x08`` the ready frame, ``-0x0C`` the duration.

    Every exit is a case where the patch has nothing to carry: the other flavour, no logic, not on
    cooldown, never recharged, a `SharedSyncedTimer` power whose timer lives on the `Player` and
    which death never touched, the keyword absent, or a full table. ``ebx`` comes back from its slot
    rather than by `pop` and the frame from `leave`, so the epilogue is correct for any esp - the
    one failure mode of a routine with this many early exits."""
    a.label("snap")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x83\xec\x10")  # sub esp, 0x10
    a.emit(0x53)  # push ebx
    a.emit(b"\x8b\xd8")  # mov ebx, eax                           ; the interface

    _emit_flavour(a, "snap_out")

    a.emit(0xA1, _u32(THE_GAME_LOGIC))  # mov eax, [TheGameLogic]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "snap_out")
    a.emit(b"\x8b\x40", GAME_LOGIC_FRAME)  # mov eax, [eax+0x40]  ; now
    a.emit(b"\x89\x45\xfc")  # mov [ebp-4], eax

    a.emit(b"\x8b\x53", SPI_READY_FRAME)  # mov edx, [ebx+8]
    a.emit(b"\x3b\xd0")  # cmp edx, eax
    a.jcc(JBE, "snap_out")  # ready, or overdue - nothing to carry
    a.emit(b"\x89\x55\xf8")  # mov [ebp-8], edx

    a.emit(b"\x8b\x4b", SPI_DURATION)  # mov ecx, [ebx+4]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JLE, "snap_out")  # never recharged: the clock would have nothing to divide by
    a.emit(b"\x89\x4d\xf4")  # mov [ebp-0xc], ecx

    _emit_template(a, "snap_out")
    a.emit(b"\x80\x78", TEMPLATE_SHARED_SYNCED_TIMER, 0x00)  # cmp byte [eax+0x59], 0
    a.jcc(JNE, "snap_out")
    a.emit(b"\x80\x78", TEMPLATE_PERSIST, 0x00)  # cmp byte [eax+0x5a], 0
    a.jcc(JE, "snap_out")  # the keyword is absent: stock

    a.emit(b"\xb2\x01")  # mov dl, 1                              ; allocate if it is new
    a.call("find")
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "snap_out")  # the table is full - see SLOTS
    a.emit(b"\x8b\x4d\xf8")  # mov ecx, [ebp-8]
    a.emit(b"\x89\x48", SLOT_READY)  # mov [eax+0x0c], ecx
    a.emit(b"\x8b\x4d\xf4")  # mov ecx, [ebp-0xc]
    a.emit(b"\x89\x48", SLOT_DURATION)  # mov [eax+0x10], ecx
    a.emit(b"\x8b\x4d\xfc")  # mov ecx, [ebp-4]
    a.emit(b"\x89\x48", SLOT_DEATH)  # mov [eax+0x14], ecx

    a.label("snap_out")
    a.emit(b"\x8b\x5d\xec")  # mov ebx, [ebp-0x14]                ; where the push put it
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret


def _emit_restore_power(a: Asm) -> None:
    """``rest(eax = SpecialPowerModuleInterface *, esi = Object *, edi = Player *)``.

    Reads one cooldown back onto a module that has just been built. The frame: ``-0x04`` the
    template, ``-0x08`` the slot.

    The two modes are the two branches, and the ticking one writes nothing when its stored frame
    has already passed - which is the whole of "dead long enough clears the cooldown". Both fields
    are written together or not at all. The slot is released either way, so the entry cannot be
    read twice and the table holds only heroes who are dead right now."""
    a.label("rest")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x83\xec\x10")  # sub esp, 0x10
    a.emit(0x53)  # push ebx
    a.emit(b"\x8b\xd8")  # mov ebx, eax                           ; the interface

    _emit_flavour(a, "rest_out")
    _emit_template(a, "rest_out")
    a.emit(b"\x80\x78", TEMPLATE_PERSIST, 0x00)  # cmp byte [eax+0x5a], 0
    a.jcc(JE, "rest_out")
    a.emit(b"\x89\x45\xfc")  # mov [ebp-4], eax                   ; the template

    a.emit(b"\x33\xd2")  # xor edx, edx                           ; look up, never allocate
    a.call("find")
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "rest_out")  # this hero did not die with this power on cooldown
    a.emit(b"\x89\x45\xf8")  # mov [ebp-8], eax

    a.emit(0xA1, _u32(THE_GAME_LOGIC))  # mov eax, [TheGameLogic]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "rest_out")
    a.emit(b"\x8b\x40", GAME_LOGIC_FRAME)  # mov eax, [eax+0x40]  ; now

    a.emit(b"\x8b\x4d\xf8")  # mov ecx, [ebp-8]                   ; the slot
    a.emit(b"\x8b\x55\xfc")  # mov edx, [ebp-4]                   ; the template
    a.emit(b"\x80\x7a", TEMPLATE_TICKS, 0x00)  # cmp byte [edx+0x5b], 0
    a.jcc(JNE, "rest_ticks")

    # Frozen: the remaining frames are banked at death and resumed here.
    a.emit(b"\x8b\x51", SLOT_READY)  # mov edx, [ecx+0x0c]
    a.emit(b"\x2b\x51", SLOT_DEATH)  # sub edx, [ecx+0x14]
    a.jcc(JBE, "rest_clear")  # nothing was left - defensive; the snapshot refuses this
    a.emit(b"\x03\xd0")  # add edx, eax                           ; now + remaining
    a.jmp("rest_write")

    # Ticking: the stored frame is absolute and stays absolute.
    a.label("rest_ticks")
    a.emit(b"\x8b\x51", SLOT_READY)  # mov edx, [ecx+0x0c]
    a.emit(b"\x3b\xd0")  # cmp edx, eax
    a.jcc(JBE, "rest_clear")  # dead long enough: the fresh module is already right

    a.label("rest_write")
    a.emit(b"\x89\x53", SPI_READY_FRAME)  # mov [ebx+8], edx
    a.emit(b"\x8b\x51", SLOT_DURATION)  # mov edx, [ecx+0x10]
    a.emit(b"\x89\x53", SPI_DURATION)  # mov [ebx+4], edx         ; both, or the clock jumps

    a.label("rest_clear")
    a.emit(b"\x83\x61", SLOT_POWER, 0x00)  # and dword [ecx+8], 0 ; release the slot

    a.label("rest_out")
    a.emit(b"\x8b\x5d\xec")  # mov ebx, [ebp-0x14]
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret


def _emit_walk(a: Asm, prefix: str, power: str) -> None:
    """``<prefix>(esi = Object *, edi = Player *)`` - offer every module's special power to
    ``power``.

    The cursor is the NULL-terminated array of `BehaviorModule *` at ``Object+0x24C``, walked
    exactly as ``0x0068BDD0`` walks it, and the interface comes out of the module's own vtable
    rather than an assumed offset - so a module with no special power costs one indirect call and
    nothing else."""
    a.label(prefix)
    a.emit(0x53)  # push ebx
    a.emit(b"\x8b\x9e", _u32(OBJECT_MODULES))  # mov ebx, [esi+0x24c]
    a.emit(b"\x85\xdb")  # test ebx, ebx
    a.jcc(JE, f"{prefix}_out")

    a.label(f"{prefix}_loop")
    a.emit(b"\x8b\x03")  # mov eax, [ebx]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, f"{prefix}_out")  # the terminator
    a.emit(b"\x8d\x48", MODULE_INTERFACE)  # lea ecx, [eax+0xc]
    a.emit(b"\x8b\x11")  # mov edx, [ecx]
    a.emit(b"\xff\x52", GET_SPECIAL_POWER_SLOT)  # call [edx+0x20] ; getSpecialPower
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(JE, f"{prefix}_next")
    a.call(power)
    a.label(f"{prefix}_next")
    a.emit(b"\x83\xc3\x04")  # add ebx, 4
    a.jmp(f"{prefix}_loop")

    a.label(f"{prefix}_out")
    a.emit(0x5B)  # pop ebx
    a.emit(0xC3)  # ret


def _emit_snapshot_hook(a: Asm) -> None:
    """The die-handler hook, standing in for the `call` that adds the hero to the revive list.

    The displaced call runs first, so a hero is on the list before anything here can fail, and
    `pushad`/`popad` carries its return value - the record's index, which the caller pushes four
    instructions later - back untouched. ``ebx`` is the dying `Object` across the call."""
    a.label("snap_hook")
    a.call_absolute(ADD_HERO)  # the displaced call; ret 8, so esp comes back by itself
    a.emit(0x60)  # pushad
    a.call("sync")
    a.emit(b"\x85\xdb")  # test ebx, ebx
    a.jcc(JE, "snap_hook_out")
    a.emit(b"\x8b\xf3")  # mov esi, ebx                           ; the Object
    a.emit(b"\x8b\xcb")  # mov ecx, ebx
    a.call_absolute(GET_CONTROLLING_PLAYER)
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "snap_hook_out")  # a hero with no player owns no slot
    a.emit(b"\x8b\xf8")  # mov edi, eax
    a.call("snap_walk")
    a.label("snap_hook_out")
    a.emit(0x61)  # popad
    a.jmp_absolute(ADD_HERO_RESUME)


def _emit_restore_hook(a: Asm) -> None:
    """The `reviveHero` hook, standing in for the call that restores the upgrade mask.

    Runs after it, so the object is as complete as the engine intends before any cooldown lands on
    it - and after `pushad`, so the caller keeps `esi` (the new object, live for another 0x100
    bytes) and everything else."""
    a.label("rest_hook")
    a.call_absolute(UPGRADE_MASK_RESTORE)  # the displaced call
    a.emit(0x60)  # pushad
    a.call("sync")
    a.emit(b"\x85\xf6")  # test esi, esi
    a.jcc(JE, "rest_hook_out")
    a.emit(b"\x8b\xce")  # mov ecx, esi                           ; the new Object
    a.call_absolute(GET_CONTROLLING_PLAYER)
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "rest_hook_out")
    a.emit(b"\x8b\xf8")  # mov edi, eax
    a.call("rest_walk")
    a.label("rest_hook_out")
    a.emit(0x61)  # popad
    a.jmp_absolute(UPGRADE_MASK_RESUME)


def build_code(code_va: int, epoch_va: int, slots_va: int) -> Asm:
    """The cave's eight routines, laid out at the address they will occupy.

    Returned as the :class:`~sage_patch.asm.Asm` rather than as bytes so the caller can take each
    hook's address from the same layout that produced them."""
    a = Asm(code_va)
    _emit_sync(a, epoch_va, slots_va)
    _emit_find(a, slots_va)
    _emit_snapshot_power(a)
    _emit_restore_power(a)
    _emit_walk(a, "snap_walk", "snap")
    _emit_walk(a, "rest_walk", "rest")
    _emit_snapshot_hook(a)
    _emit_restore_hook(a)
    return a


def _hook(site_va: int, window: bytes, target_va: int) -> bytes:
    """`jmp rel32` to ``target_va``, padded with `nop` to the width of ``window``."""
    jump = b"\xe9" + struct.pack("<i", target_va - (site_va + 5))
    if len(window) < len(jump):
        raise ValueError(f"the window at 0x{site_va:08x} is too small for a jmp rel32")
    return jump + b"\x90" * (len(window) - len(jump))


def _offset(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"VA 0x{va:08x} is not mapped - not the expected build")
    return off


def _cstring(data: bytes | bytearray, va: int, limit: int = 64) -> str | None:
    """The NUL-terminated ASCII string at ``va``, or None if it is unmapped or not one."""
    off = va_to_offset(data, va)
    if off is None:
        return None
    end = bytes(data).find(b"\x00", off, off + limit)
    if end < 0:
        return None
    try:
        return data[off:end].decode("ascii")
    except UnicodeDecodeError:
        return None


class CooldownThroughDeathPatch(Patch):
    """Carry a hero's special-power cooldowns across a citadel revive, under two new
    `SpecialPower` booleans."""

    name = "cooldown-through-death"
    author = "officialNecro"
    experimental = True
    description = (
        "Carry a special-power cooldown across a hero's death (SpecialPower "
        "PersistCooldownOnDeath = Yes), optionally letting it keep elapsing while the hero is "
        "dead (CooldownTicksWhileDead) so a long enough death clears it. Both default to off, "
        "and only Command = REVIVE heroes are affected - a RespawnUpdate hero already keeps its "
        "cooldowns"
    )

    def __init__(
        self,
        persist_keyword: str = DEFAULT_PERSIST_KEYWORD,
        ticks_keyword: str = DEFAULT_TICKS_KEYWORD,
    ):
        self.persist_keyword = persist_keyword
        self.ticks_keyword = ticks_keyword
        validate_keyword(persist_keyword)
        validate_keyword(ticks_keyword)
        if persist_keyword == ticks_keyword:
            raise ValueError(
                "the two fields need two names - the INI reader takes the first row that matches, "
                f"so a shared {persist_keyword!r} would make the second unreachable"
            )

    def __str__(self) -> str:
        return f"{self.name} ({self.persist_keyword}, {self.ticks_keyword})"

    def apply(self, data: bytearray) -> None:
        # Before the anchors, because applying rewrites bytes two of them cover: a second run would
        # otherwise fail as "not the build this patch was derived against", which is true of the
        # bytes and misleading about the cause.
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError(
                f"this image already carries a {SECTION_NAME} section - the patch is already "
                "applied, and applying it twice would install a second copy of both fields"
            )
        self._check_anchors(data)
        self._check_dispatch(data)
        table_va = self._resolve(data)
        entries = self._check_table(data, table_va)

        base_va = allocate_section(
            data, SECTION_NAME, lambda base: self._build(base, entries), SECTION_CHARACTERISTICS
        )
        pieces = self._pieces(base_va, len(entries))
        code = build_code(pieces.code_va, pieces.epoch_va, pieces.slots_va)

        for file_off, old, new, note in self._edits(data, pieces, code):
            apply_byte_patch(data, file_off, old, new, note)

    def _pieces(self, base_va: int, rows: int) -> _Layout:
        return _layout(base_va, self.persist_keyword, self.ticks_keyword, rows)

    def _build(self, base_va: int, entries: tuple[Entry, ...]) -> bytes:
        """The cave: the epoch, the two keywords, the rebuilt table, the slot table, the code.

        The epoch and the slots are written out as zeros rather than left as uninitialised virtual
        size, so the section's raw data says what the table starts as and `verify` can read it
        back. Zero is also the right starting epoch: the first logic frame either hook sees is at
        least that, so a fresh image never wipes a table that is already empty."""
        pieces = self._pieces(base_va, len(entries))
        blob = bytearray(_PERSIST_OFFSET)  # the epoch, zero at load
        blob += self.persist_keyword.encode("ascii") + b"\x00"
        blob += self.ticks_keyword.encode("ascii") + b"\x00"
        blob += bytes(pieces.table_va - (base_va + len(blob)))
        blob += build_table(entries, pieces.persist_va, pieces.ticks_va)
        assert base_va + len(blob) == pieces.slots_va, "the cave layout and its addresses disagree"
        blob += bytes(SLOTS * SLOT_STRIDE)
        assert base_va + len(blob) == pieces.code_va, "the cave layout and its addresses disagree"
        return bytes(blob) + build_code(pieces.code_va, pieces.epoch_va, pieces.slots_va).finish()

    def _edits(
        self, data: bytes | bytearray, pieces: _Layout, code: Asm
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte this patch writes outside its own cave, as
        ``(file offset, expected, replacement, note)``."""
        edits: list[tuple[int, bytes, bytes, str]] = [
            (
                _offset(data, TEMPLATE_CTOR_BOOLS),
                TEMPLATE_CTOR_BOOLS_BYTES,
                rewritten_ctor(),
                f"SpecialPowerTemplate ctor -> {self.persist_keyword} defaults to No",
            ),
            (
                _offset(data, TEMPLATE_COPY_LOAD),
                TEMPLATE_COPY_LOAD_BYTES,
                rewritten_copy_load(),
                "SpecialPowerTemplate copy ctor -> load the padding too",
            ),
            (
                _offset(data, TEMPLATE_COPY_STORE),
                TEMPLATE_COPY_STORE_BYTES,
                rewritten_copy_store(),
                "SpecialPowerTemplate copy ctor -> store the padding too",
            ),
            (
                _offset(data, ADD_HERO_CALL),
                ADD_HERO_CALL_BYTES,
                _hook(ADD_HERO_CALL, ADD_HERO_CALL_BYTES, code.label_va("snap_hook")),
                f"the revive-list add -> the {SECTION_NAME} snapshot",
            ),
            (
                _offset(data, UPGRADE_MASK_CALL),
                UPGRADE_MASK_CALL_BYTES,
                _hook(UPGRADE_MASK_CALL, UPGRADE_MASK_CALL_BYTES, code.label_va("rest_hook")),
                f"the upgrade-mask restore -> the {SECTION_NAME} restore",
            ),
        ]
        table_ref = _u32(pieces.table_va)
        for ref_va, opcode in zip(
            SPECIAL_POWER_FIELD_TABLE_REFS, SPECIAL_POWER_FIELD_TABLE_REF_OPCODES, strict=True
        ):
            off = _offset(data, ref_va)
            edits.append(
                (
                    off,
                    bytes(data[off : off + 5]),
                    bytes([opcode]) + table_ref,
                    f"SpecialPower field table reference 0x{ref_va:08x} -> {SECTION_NAME}",
                )
            )
        return edits

    @staticmethod
    def _resolve(data: bytes | bytearray) -> int:
        """The `SpecialPower` field table's base VA, as the image currently holds it.

        Read from the two references that name it rather than from the stock constant, so the patch
        appends to whatever is live - which is what makes it compose with `hero-mana`, and what
        makes applying it twice fail cleanly instead of installing a second copy of both fields."""
        return resolve_table(
            data,
            SPECIAL_POWER_FIELD_TABLE_REFS,
            SPECIAL_POWER_FIELD_TABLE_REF_OPCODES,
            "SpecialPower",
        )

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        """Raise unless every window in :data:`ANCHORS` still holds its stock bytes.

        These are the reads the caves are built on and never rewrite. A build where one has moved
        would still take the patch and still verify - and then bank a cooldown off the wrong field,
        or hook a call that no longer adds a hero to anything."""
        for va, want in ANCHORS.items():
            off = va_to_offset(data, va)
            got = None if off is None else bytes(data[off : off + len(want)])
            if got != want:
                raise ValueError(
                    f"0x{va:08x} holds {'nothing mapped' if got is None else got.hex()}, expected "
                    f"{want.hex()} - this is not the build this patch was derived against"
                )

    @staticmethod
    def _check_dispatch(data: bytes | bytearray) -> None:
        """Raise unless the flavour-1 interface vtable still names `startPowerRecharge` at the slot
        the caves test. The test is the only thing keeping this patch off a layout where the ready
        frame is somewhere else, so a moved slot has to be a refusal rather than a guess."""
        slot_va = SPI_VTABLE + SPI_VTABLE_RECHARGE_SLOT
        target = struct.unpack_from("<I", data, _offset(data, slot_va))[0]
        if target != START_POWER_RECHARGE:
            raise ValueError(
                f"vtable slot 0x{slot_va:08x} dispatches to 0x{target:08x}, not "
                f"0x{START_POWER_RECHARGE:08x} - the flavour test would match nothing"
            )

    def _check_table(self, data: bytes | bytearray, table_va: int) -> tuple[Entry, ...]:
        """The live rows, once the table has been checked for the build and for both keywords.

        A duplicate row would parse - the reader takes the first match - so the field would exist
        and silently do nothing."""
        entries = read_field_table(data, table_va)
        by_name = {_cstring(data, name): offset for name, _fn, _ud, offset in entries}
        for field, want in FINGERPRINT.items():
            got = by_name.get(field)
            if got != want:
                raise ValueError(
                    f"unexpected build: SpecialPower.{field} is at "
                    f"{'absent' if got is None else hex(got)}, expected {want:#x}"
                )
        for offset in (TEMPLATE_PERSIST, TEMPLATE_TICKS):
            claimed = [name for name, at in by_name.items() if at == offset]
            if claimed:
                raise ValueError(
                    f"SpecialPower+{offset:#x} is already parsed as {claimed[0]!r} - this patch is "
                    "already applied, or another patch has taken the padding it uses"
                )
        for keyword in (self.persist_keyword, self.ticks_keyword):
            if keyword in by_name:
                raise ValueError(
                    f"SpecialPower already has a {keyword!r} field - this patch is already "
                    "applied, or another patch has added the same field"
                )
        return entries

    @classmethod
    def detect(cls, data: bytes | bytearray) -> CooldownThroughDeathPatch | None:
        """Recognise this patch **and recover both keywords** from ``data``.

        The default probe would only ever recognise the default names. The two strings open the
        cave, back to back, so they read straight back out; `verify` then checks the whole cave
        against them."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        persist = _cstring(data, located[0] + _PERSIST_OFFSET)
        if persist is None:
            return None
        ticks = _cstring(data, located[0] + _PERSIST_OFFSET + len(persist) + 1)
        if ticks is None:
            return None
        try:
            patch = cls(persist, ticks)
        except ValueError:
            return None  # not a pair of keywords this patch could have written
        return None if patch.verify(data) else patch

    def ini_surface(self) -> Engine:
        """The two `Bool`s this patch adds to `SpecialPower`, under whatever names it was installed
        with. The constructor zeroes the padding they live in, so both default to `No` - stock
        behaviour, which is what makes them opt-in."""
        return Engine(
            fields=(
                FieldDelta("SpecialPower", self.persist_keyword, "Bool", False, self.name),
                FieldDelta("SpecialPower", self.ticks_keyword, "Bool", False, self.name),
            )
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch for exactly these two keywords. Reads
        only via ``struct`` and the section table, so it needs no disassembler.

        Every address is recovered from where the cave actually landed rather than from where it
        would land on a clean image, so a build carrying another patch's section too verifies the
        same."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, _section_off, vsize = located

        try:
            table_va = self._resolve(data)
            rebuilt = read_field_table(data, table_va)
            preceding = entries_before(data, rebuilt, self.persist_keyword)
            if preceding is None:
                return [f"the live SpecialPower table does not name {self.persist_keyword!r}"]
            pieces = self._pieces(section_va, len(preceding))
            problems = self._verify_cave(data, pieces, preceding, section_va, vsize)
            problems += self._verify_live_rows(data, rebuilt, pieces)
            problems += self._verify_sites(data, pieces)
        except (ValueError, struct.error) as exc:
            return [f"cannot read back the patch (wrong build?): {exc}"]
        return problems

    def _verify_cave(
        self,
        data: bytes | bytearray,
        pieces: _Layout,
        preceding: tuple[Entry, ...],
        section_va: int,
        vsize: int,
    ) -> list[str]:
        problems: list[str] = []
        code = build_code(pieces.code_va, pieces.epoch_va, pieces.slots_va).finish()
        if pieces.code_va + len(code) > section_va + vsize:
            return [
                f"{SECTION_NAME} holds {vsize} bytes, too few for the table, the slots and the code"
            ]
        for keyword, va in (
            (self.persist_keyword, pieces.persist_va),
            (self.ticks_keyword, pieces.ticks_va),
        ):
            got = _cstring(data, va)
            if got != keyword:
                problems.append(f"the keyword at 0x{va:08x} is {got!r}, not {keyword!r}")
        want_table = build_table(preceding, pieces.persist_va, pieces.ticks_va)
        table_off = _offset(data, pieces.table_va)
        if bytes(data[table_off : table_off + len(want_table)]) != want_table:
            problems.append(
                f"the field table at 0x{pieces.table_va:08x} is not the live rows plus Bools at "
                f"SpecialPower+0x{TEMPLATE_PERSIST:02x} and +0x{TEMPLATE_TICKS:02x}"
            )
        code_off = _offset(data, pieces.code_va)
        if bytes(data[code_off : code_off + len(code)]) != code:
            problems.append(f"the code at 0x{pieces.code_va:08x} is not what this patch builds")
        return problems

    def _verify_live_rows(
        self, data: bytes | bytearray, live: tuple[Entry, ...], pieces: _Layout
    ) -> list[str]:
        """Both fields are still parsed, out of whatever table the engine now reads.

        Deliberately *not* "the references still name this patch's own table". A later patch that
        rebuilds the same table copies these two rows into its own and repoints the references at
        that - `hero-mana` does exactly this, and the result is a binary that parses both fields
        perfectly. What has to hold is that the live table still carries them, pointing at the
        keyword strings in this cave and writing the padding bytes this cave's code reads; where
        that table lives is the business of whoever built it last.

        The references not agreeing with *each other* is already a refusal: `_resolve` raises."""
        problems: list[str] = []
        for keyword, keyword_va, offset in (
            (self.persist_keyword, pieces.persist_va, TEMPLATE_PERSIST),
            (self.ticks_keyword, pieces.ticks_va, TEMPLATE_TICKS),
        ):
            row = next((entry for entry in live if _cstring(data, entry[0]) == keyword), None)
            if row is None:
                problems.append(f"the live SpecialPower table no longer parses {keyword!r}")
            elif (row[0], row[1], row[3]) != (keyword_va, INI_PARSE_BOOL, offset):
                problems.append(
                    f"the live {keyword!r} row is not this patch's Bool at "
                    f"SpecialPower+0x{offset:02x} (holds name 0x{row[0]:08x}, fn 0x{row[1]:08x}, "
                    f"offset 0x{row[3]:02x})"
                )
        return problems

    def _verify_sites(self, data: bytes | bytearray, pieces: _Layout) -> list[str]:
        code = build_code(pieces.code_va, pieces.epoch_va, pieces.slots_va)
        checks: list[tuple[int, bytes, str]] = [
            (
                TEMPLATE_CTOR_BOOLS,
                rewritten_ctor(),
                f"the ctor does not default {self.persist_keyword} to No",
            ),
            (
                TEMPLATE_COPY_LOAD,
                rewritten_copy_load(),
                "the copy ctor does not load the padding the two fields live in",
            ),
            (
                TEMPLATE_COPY_STORE,
                rewritten_copy_store(),
                "the copy ctor does not store the padding the two fields live in",
            ),
            (
                ADD_HERO_CALL,
                _hook(ADD_HERO_CALL, ADD_HERO_CALL_BYTES, code.label_va("snap_hook")),
                f"the revive-list add is not hooked to the {SECTION_NAME} snapshot",
            ),
            (
                UPGRADE_MASK_CALL,
                _hook(UPGRADE_MASK_CALL, UPGRADE_MASK_CALL_BYTES, code.label_va("rest_hook")),
                f"the upgrade-mask restore is not hooked to the {SECTION_NAME} restore",
            ),
        ]
        problems: list[str] = []
        for va, want, complaint in checks:
            off = _offset(data, va)
            got = bytes(data[off : off + len(want)])
            if got != want:
                problems.append(f"@0x{va:08x}: {complaint} (holds {got.hex()})")
        return problems

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--keyword",
            default=DEFAULT_PERSIST_KEYWORD,
            metavar="NAME",
            help=(
                f"name of the SpecialPower field that turns the feature on (default "
                f"{DEFAULT_PERSIST_KEYWORD}); letters, digits and underscores, and must not "
                "already be a SpecialPower field"
            ),
        )
        parser.add_argument(
            "--ticks-keyword",
            default=DEFAULT_TICKS_KEYWORD,
            metavar="NAME",
            help=(
                f"name of the SpecialPower field that lets the cooldown keep elapsing while the "
                f"hero is dead (default {DEFAULT_TICKS_KEYWORD})"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> CooldownThroughDeathPatch:
        return cls(persist_keyword=args.keyword, ticks_keyword=args.ticks_keyword)
