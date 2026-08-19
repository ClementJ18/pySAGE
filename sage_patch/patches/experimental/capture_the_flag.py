"""Capture-the-flag by proximity: an `UpdateModule` that captures its own object for whichever
player holds a share of the units standing around it.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../../docs/capture-the-flag.md``.

**What the engine does today.** A capture flag carries no capture logic at all: stock
`Object CaptureFlag` is a `HighlanderBody`, a `DestroyDie`, an `AIUpdateInterface` and a draw.
Capture lives on the *capturing unit*, as a `SpecialAbilityUpdate` running
`SpecialAbilityCaptureBuilding` with a `PreparationTime`. So contested capture is "whose timer
finishes first", not a contest, and a flag cannot be taken by simply holding the ground.

**What this adds.** One behaviour on the flag itself::

    Behavior = ProximityCaptureUpdate ModuleTag_CTF
      ObjectFilter      = ANY +INFANTRY +CAVALRY
      Radius            = 150.0
      TickRate          = 500     ; milliseconds between evaluations
      TickAmount        = 4       ; progress added per tick, out of 100
      CaptureShare      = 50      ; percent of the present population needed to contend
      CountHordeMembers = Yes
    End

Every `TickRate` the module scans `Radius` around itself, buckets what it finds by
controlling player, and picks the player holding at least `CaptureShare` percent of that
population as the **contender**. The contender's progress rises by `TickAmount`; a different
contender drives it down instead, and at zero the claim passes to them and starts rising. At 100
the flag joins the contending units' team.

**An unheld flag gives itself back.** If nobody meets the share - an empty radius, a tie, or a
leader short of it - the bar falls at the same `TickAmount` it rose at, the art plays
`CANCEL_CAPTURE` so the banner lowers, and at zero the claim, the capturing id and every capture
condition clear together. A flag abandoned at 90% does not sit there forever waiting.

On capture the flag also hands over every **`LINKED_TO_FLAG`** object inside the same radius. A
`ShipWright` carries that kindof and, pointedly, **not** `CAPTURABLE` - it cannot be taken
directly, so a flag is its only route, and a capture that moved only the flag would leave the
thing the flag exists for sitting neutral. The stock ability propagates; so does this.

Ownership changes **only at 100**. The bar reaching zero transfers the claim, not the flag - which
is both what the mechanic asks for and what keeps the module away from assigning a null team, a
state no stock code path produces.

Adoption, not registration
--------------------------
The module is **`AutoFindHealingUpdate`, repurposed**. That name is registered by the engine's
`ModuleFactory` and referenced by nothing in any `.big` the install ships - stock or Edain - and
it is already an `UpdateModule` whose reason to exist is a periodic scan, with `ScanRate` and
`ScanRange` sitting at the two offsets this module wants for `TickRate` and `Radius`.

Registering a genuinely new module type would mean authoring a correct `UpdateModule` vtable from
nothing. Adopting this one costs three `imm32`s to rename the block, one dword in its own private
vtable to change what it does, and two allocation sizes. **The price is that
`AutoFindHealingUpdate` ceases to exist**; nothing in the shipped data uses it, but that is
irreversible for a mod that later wants it.

What this patch does not do
---------------------------
* **No `xfer`.** The module's crc/xfer/loadPostProcess slots are a bare ``ret`` in the stock build
  and stay that way, so a save records the flag's *team* (which is `Object` state, saved already)
  but not the accumulator. Loading resets progress to zero and the claim to nobody on **every**
  peer identically, so this is a fidelity loss across a save, not a desync.
* **No capture trimmings.** `InitialCaptureBonus`, the capture FX and the capture sounds the stock
  `SpecialAbilityUpdate` path pays out are not reproduced. The flag changes hands and sets its
  `CAPTURED` model condition; everything else the stock path does on capture is unclaimed - see
  the doc's §4.1, which is the one thing static reading could not close.
* **The command set on a captured structure is not re-evaluated.** A `CommandSetUpgrade` gates
  itself on a cached byte at `module+0x14`, set when its faction trigger is satisfied. A stock
  capture evaluates that trigger against the new owner and sets it; this module does not, so a
  captured `ShipWright` changes hands and keeps the neutral `GenericSelfRepairCommandSet`. The
  apply routine is already called on every captured object, which is the correct second half and
  is inert until the byte is set. Measured in a live match and written up in the doc's §6.025.
* **No AI.** `SkirmishAI` has no notion of this module and will not walk to a flag on purpose.

Composition
-----------
Order-independent: the cave is allocated with :func:`~...utils.allocate_section` past every
existing section and :meth:`verify` finds it by name, and no edited byte is shared with another
bundled patch. The one structure rebuilt - `AutoFindHealingUpdate`'s own field-parse table - is
private to a module nothing else touches.

**This is logic state.** The accumulator is read by the simulation every tick, so every peer must
run the same patched binary and replays do not cross. Progress is an integer on a 0..100 scale and
the share test is an integer cross-multiply, so no float rounding enters the comparison.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sage_ini.engine import BlockDelta, Engine, FieldDelta

from ...asm import JAE, JB, JE, JG, JGE, JL, JLE, JNE, Asm
from ...patcher import Patch
from ...utils import allocate_section, apply_byte_patch, find_section, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "DEFAULT_BLOCK",
    "FIELDS",
    "PATCHED_INSTANCE_SIZE",
    "PATCHED_MODULEDATA_SIZE",
    "SECTION_NAME",
    "STOCK_FIELD_TABLE",
    "STOCK_INSTANCE_SIZE",
    "STOCK_MODULEDATA_SIZE",
    "CaptureTheFlagPatch",
]

SECTION_NAME = ".ctflag"

#: The INI block name the adopted module answers to once renamed.
DEFAULT_BLOCK = "ProximityCaptureUpdate"

#: `AutoFindHealingUpdate`'s name string, and the three `imm32`s that name the block: the
#: `ModuleFactory::addModule` registration, the module's own name thunk, and the field-table
#: registration. All three must move together or the engine parses one name and registers another.
STOCK_NAME_VA = 0x00C0B874
NAME_REF_VAS = (0x00658B07 + 1, 0x00898815 + 1, 0x00898867 + 1)
NAME_REF_OPCODES = (b"\x68", b"\xb8", b"\x68")

#: ``push 0x24`` in `newModule` - the module instance. Grown to hold the accumulator.
INSTANCE_SIZE_VA = 0x0064DBAA
STOCK_INSTANCE_SIZE = 0x24
PATCHED_INSTANCE_SIZE = 0x30

#: ``push 0x18`` in `newModuleData`. Grown to hold the two new fields.
MODULEDATA_SIZE_VA = 0x0064DBE3
STOCK_MODULEDATA_SIZE = 0x18
PATCHED_MODULEDATA_SIZE = 0x20

#: The two constructor calls, redirected through cave shims: the instance ctor (which must zero
#: the accumulator `operator new` left uninitialised) and the `ModuleData` ctor (which must
#: default the new fields and, crucially, construct the `ObjectFilter` handle).
INSTANCE_CTOR_CALL_VA = 0x0064DBC6
INSTANCE_CTOR_VA = 0x008988C7
MODULEDATA_CTOR_CALL_VA = 0x0064DBF8
MODULEDATA_CTOR_VA = 0x00898887

#: The module's own `UpdateModule` vtable, stored at instance ``+0x10``. Both references to it in
#: the whole image are this class's constructor and destructor, so it is private and slot 0 - the
#: `update` entry point - can be repointed in place rather than copied.
UPDATE_VTABLE_VA = 0x00C6533C
STOCK_UPDATE_VA = 0x00898999

#: The 16-byte-stride field-parse table and the single `push` that loads it.
FIELD_TABLE_VA = 0x00C653A0
FIELD_TABLE_REF_VA = 0x008988BC + 1

#: The stock table, asserted before it is replaced: ``(keyword, parse fn, offset)``.
STOCK_FIELD_TABLE = (
    ("ScanRate", 0x0073A429, 0x08),
    ("ScanRange", 0x0042ED00, 0x0C),
    ("NeverHeal", 0x0042ED00, 0x10),
    ("AlwaysHeal", 0x0042ED00, 0x14),
)

#: INI field-parse functions, recovered from tables that already use them.
_PARSE_DURATION = 0x0073A429
_PARSE_REAL = 0x0042ED00
_PARSE_INT = 0x0042EC5E
_PARSE_BOOL = 0x0042E558
_PARSE_OBJECT_FILTER = 0x0076392F

#: The new table: ``(keyword, parse fn, ModuleData offset, model type)``. The first two keep the
#: offsets the stock fields already occupied, which is why nothing but the size literal moves.
#: The parse function and the model spelling are different things: `TickRate` is parsed by the
#: engine's `Duration` reader (which converts milliseconds to frames) and stored as an integer,
#: so the model - which describes the value, not the reader - types it `Int`.
FIELDS = (
    ("TickRate", _PARSE_DURATION, 0x08, "Int"),
    ("Radius", _PARSE_REAL, 0x0C, "Float"),
    ("TickAmount", _PARSE_INT, 0x10, "Int"),
    ("CaptureShare", _PARSE_INT, 0x14, "Int"),
    ("ObjectFilter", _PARSE_OBJECT_FILTER, 0x18, "ObjectFilter"),
    ("CountHordeMembers", _PARSE_BOOL, 0x1C, "Bool"),
)

#: What the `ModuleData` constructor shim writes, so an INI block that omits a keyword still gets
#: a flag that behaves. `Radius` is a float; the rest are integers.
#:
#: `TickRate` is written in the **stored** unit, which for a `Duration` field is logic frames -
#: the INI keyword itself takes milliseconds and the engine's parser converts. 15 frames is
#: about 500 ms, so the default flag re-evaluates twice a second and, at `TickAmount` 4, takes
#: 25 ticks - a little over twelve seconds - to capture against no opposition.
DEFAULTS = {
    "TickRate": 15,
    "Radius": 150.0,
    "TickAmount": 4,
    "CaptureShare": 50,
    "CountHordeMembers": True,
}

# Engine entry points the cave calls. Each is documented in ../../docs/capture-the-flag.md §4.
_THE_PARTITION_MANAGER = 0x00DE4354
_ITERATE_IN_RANGE = 0x00A39340
_ITER_NEXT = 0x00444F19
_ITER_RELEASE = 0x0044A2A5
_FILTER_ALIVE_VTABLE = 0x00C10E20
_GET_CONTROLLING_PLAYER = 0x0068B678
_GET_CONTAIN = 0x0068C866
#: `Object::setTeam`, ``__thiscall(ecx = Object*, Team*, Bool suppressNotify)``, ``ret 8``. It
#: early-outs when the team is unchanged and carries the whole ownership handover.
#:
#: **The second argument must be 0.** At `0x00697DB8` it reads ``cmp byte [ebp+0xC], 0 / jne``
#: around the call to `Object::onCapture` (`0x00696F0A`) - the routine that walks the object's
#: module array and calls vslot ``+0x24`` on every module with the old and new player, then marks
#: the UI dirty. Non-zero **skips all of it**: the team moves and nothing is told. That is right
#: for the one stock caller passing 1, which is savegame restore (`0x0069831E`) - modules are
#: being rebuilt from a snapshot rather than reacting to a live change - and wrong for everything
#: else. The public one-argument wrapper the game itself uses (`0x00698E6F`) passes 0.
#:
#: An early build of this patch copied the 1 from the restore path. Ownership moved, so it looked
#: correct; but no module was ever told, so a captured shipyard never re-ran `CommandSetUpgrade`
#: and kept its neutral command set.
_SET_TEAM = 0x00697C09
_PROPAGATE_MODEL_CONDITIONS = 0x0068B53C

#: `CommandSetUpgrade`'s apply routine, ``__thiscall(ecx = module + 0x10)``, no arguments. It
#: asks its own vslot 0 whether the trigger is satisfied and, if so, writes the module's
#: `CommandSet` (`ModuleData+0x138`) into **`Object+0x43C`** - the object's command-set override.
#: That is the whole of "a captured structure shows the new owner's buttons", and re-running it
#: after an ownership change is what re-evaluates the faction trigger against the new owner.
#:
#: Two things made this hard to reach, and both cost a live test each.
#:
#: **The subobject.** The routine is slot ``+0x20`` of the interface vtable at ``module+0x10``.
#: Everything that walks a module array generically - `Object::onCapture` (`0x00696F0A`), the
#: upgrade refresh at :data:`_REFRESH_UPGRADES` - dispatches through the vtable at ``module+0``,
#: a different table, so none of them can reach it.
#:
#: **The sibling class.** `0x00C6FD18` and `0x00C6DEF8` are two upgrade modules with an identical
#: interface layout, differing only at slots ``+0x18`` and ``+0x20``. Picking the wrong one gives
#: a vtable check that never matches and a routine that belongs to another class. The one on a
#: `ShipWright` is `0x00C6DEF8` - established by walking the live object's module array, where
#: seven of its thirty-four modules carry it, each with a non-null `CommandSet` at
#: `ModuleData+0x138`. It also sits directly below `CommandSetUpgrade`'s own `ModuleData` vtable
#: (`0x00C6DF40`) and field-parse table (`0x00C6DF70`), which is the static corroboration.
_REGISTER_COMMAND_SET = 0x008B7CFA
_COMMAND_SET_UPGRADE_VTABLE = 0x00C6DEF8
_OBJ_MODULES = 0x24C

#: `Object::refreshUpgradeState` (name inferred), ``__thiscall(ecx = Object*)``, no arguments.
#: Notifies the object's container, refreshes its drawable, then walks the module array calling
#: vslot ``+0x20`` on **every** module.
#:
#: That slot is where `CommandSetUpgrade` lives (`0x008BC821`), and what it does is the reason
#: this call is needed: it reads the object's **current** controlling player and registers the
#: module's `CommandSet` into a per-player registry at `Player+0x60`, keyed by the object's id.
#: The override is therefore filed against *a player*, not stored on the object - so an object
#: that changes hands leaves its entry behind with the old owner and falls back to its template's
#: default. `Object::onCapture` does not fix this: it calls vslot ``+0x24``, which
#: `CommandSetUpgrade` leaves as a stub.
#:
#: Every other module vtable examined stubs ``+0x20`` with `0x0063F3BF`, a bare ``ret``, so the
#: walk is cheap and inert for anything that does not care.
_REFRESH_UPGRADES = 0x006902FA
_FILTER_TEST = 0x00763543
_FILTER_WAS_SPECIFIED = 0x00762977
_FILTER_CTOR = 0x0076406F

#: `KINDOF_LINKED_TO_FLAG`, bit 50 of the `ThingTemplate`'s KindOf mask at ``+0x108`` - so byte
#: ``+0x10E``, mask ``0x04``. Both are read out of the engine's own KindOf name table rather than
#: hardcoded from a list, the same way every other name-table index in this package is.
#:
#: This is the whole of "capture the flag, get the shipyard". A `ShipWright` carries
#: `LINKED_TO_FLAG` and **not** `CAPTURABLE`: it cannot be captured directly, so it changes hands
#: only when a flag near it does. No map script is involved - the map that surfaced this carries
#: no ownership-transfer action at all.
_KINDOF_BYTE = 0x10E
_LINKED_TO_FLAG = 0x04

# Object and Player offsets.
#
# ``_OBJ_TEAM`` is `Object::m_team`, the field `getControllingPlayer` (`0x0068B678`) dereferences
# as its very first instruction. **It is not `+0x74`**: that is `Object::m_id`, measured live
# against 386 objects (see :data:`~...addresses.OBJECT_ID`), and an early draft of this patch had
# the two confused - which made it call `0x0068BC01` believing it to be `setTeam`. That routine is
# `Object::setID`: it unregisters the object from `TheGameLogic`'s id map, overwrites the id, and
# re-registers under the new one. Every capture therefore gave the flag a *unit's* id and
# clobbered that unit's entry in the lookup table, while the owner never changed at all.
_OBJ_TEMPLATE = 0x04
_OBJ_POSITION = 0x38
_OBJ_TEAM = 0x31C
_PLAYER_INDEX = 0x54

#: `Object::m_id`, the same field :data:`~...addresses.OBJECT_ID` names.
_OBJ_ID = 0x74

#: "The `ObjectID` of whoever is currently capturing me", read by the Lua binding
#: `ObjectCapturingObjectPlayerSide` (`0x0073684D`: `findObjectByID` on this field, then
#: `getControllingPlayer`, then the player's side name).
#:
#: **Nothing in the stock image writes it** - every store to `[reg+0x80]` in the `Object`
#: compiland is the constructor or destructor zeroing `+0x70`..`+0x80` in a run - so on a flag
#: this module is the only thing that ever can. It matters for the *animation*: `START_CAPTURE`
#: carries `LuaEvent = OnStateEnter`, and the script it fires raises the **capturing** player's
#: banner, which is what makes a stock capture read as a flag going up over the capture's
#: duration. Unset, the script falls back to the flag's own side - still the old owner mid-capture
#: - so the pole rises bare and the new banner appears already raised at the end.
_OBJ_CAPTURING_ID = 0x80

#: `Object`'s `ModelConditionFlags` start at ``+0x10C``. The four capture conditions are indices
#: 110, 111, 112 and 119 in the engine's own name table, so all four live in the fourth dword at
#: ``+0x118``.
#:
#: **Only three of them are worth setting**, and which three is decided by the *art*, not by the
#: state machine. The stock `CaptureFlag`'s `W3DScriptedModelDraw` defines exactly
#: `AnimationState = START_CAPTURE`, `= CANCEL_CAPTURE` and `= CAPTURED` (plus its idle) — there
#: is **no `CAPTURING` state**. A condition no `AnimationState` names does not select anything: it
#: leaves the drawable in `IdleUncaptured` with the flag down and, because `START_CAPTURE` is the
#: state carrying `LuaEvent = OnStateEnter`, it never runs the script that raises the flag.
#: `CAPTURING` is therefore cleared and never set.
_MODEL_CONDITION_DWORD = 0x118
_BIT_START_CAPTURE = 1 << (110 - 96)
_BIT_CANCEL_CAPTURE = 1 << (111 - 96)
_BIT_CAPTURING = 1 << (112 - 96)
_BIT_CAPTURED = 1 << (119 - 96)
_BIT_CLEAR_MASK = 0xFFFFFFFF & ~(
    _BIT_START_CAPTURE | _BIT_CANCEL_CAPTURE | _BIT_CAPTURING | _BIT_CAPTURED
)

#: `MAX_PLAYER_COUNT`. Every per-player array the engine embeds is this wide.
_MAX_PLAYERS = 20

#: The contain interface's "count my members matching this filter" vtable slot.
_CONTAIN_COUNT_SLOT = 0x180

_ROW_SIZE = 16


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _offset(data: bytes | bytearray, va: int) -> int:
    """`va_to_offset` that raises rather than returning None. Every address this patch touches is
    a fixed VA in a build it has already identified, so an unmapped one is a wrong-build error
    with a name attached, not a case to handle."""
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"{va:#010x} is not mapped - wrong build?")
    return off


@dataclass(frozen=True)
class _Layout:
    """Where each piece of the cave sits. Recomputed identically by `apply` and `verify`, so
    neither has to remember where the other put things."""

    update_va: int
    moduledata_ctor_va: int
    instance_ctor_va: int
    table_va: int
    name_va: int
    keyword_vas: tuple[int, ...]
    size: int


def _string_block(names: tuple[str, ...]) -> tuple[bytes, tuple[int, ...]]:
    """The NUL-terminated strings back to back, plus each one's offset within the block."""
    blob = bytearray()
    offsets: list[int] = []
    for name in names:
        offsets.append(len(blob))
        blob += name.encode("ascii") + b"\x00"
    while len(blob) % 4:
        blob += b"\x00"
    return bytes(blob), tuple(offsets)


class CaptureTheFlagPatch(Patch):
    name = "capture-the-flag"
    description = (
        "adds a ProximityCaptureUpdate behaviour that captures its own object for whichever "
        "player holds CaptureShare percent of the ObjectFilter-matching units within Radius, "
        "ticking TickAmount of 100 every TickRate frames and flipping ownership at 100 - the "
        "block name is --block-name (default ProximityCaptureUpdate) and it REPLACES the unused "
        "AutoFindHealingUpdate, which stops existing; capturing also hands over LINKED_TO_FLAG "
        "structures in the same radius, the way the stock ability does; no new art, string or "
        "map data is needed "
        "because the stock CaptureFlag already animates START_CAPTURE, CANCEL_CAPTURE and CAPTURED"
    )

    author = "officialNecro"
    experimental = True

    def __init__(self, block_name: str = DEFAULT_BLOCK) -> None:
        if not block_name.isidentifier() or not block_name.isascii():
            raise ValueError(f"block name {block_name!r} is not a plain ASCII identifier")
        self.block_name = block_name

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--block-name",
            default=DEFAULT_BLOCK,
            help=(
                "the INI block name the adopted module answers to "
                f"(default {DEFAULT_BLOCK}); AutoFindHealingUpdate stops existing either way"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> CaptureTheFlagPatch:
        return cls(block_name=args.block_name)

    def __str__(self) -> str:
        return f"{self.name} ({self.block_name})"

    # ---- layout -------------------------------------------------------------------------

    def _names(self) -> tuple[str, ...]:
        return (self.block_name, *(field[0] for field in FIELDS))

    def _layout(self, base_va: int) -> _Layout:
        """Where everything lands, given the cave's base. The code is emitted first because its
        size is what the table's alignment is measured from; the strings follow the table so the
        table's own rows are the only thing that has to know where they are."""
        asm = self._asm(base_va)
        code = asm.finish()
        table_va = (base_va + len(code) + 15) & ~15
        strings, offsets = _string_block(self._names())
        strings_va = table_va + (len(FIELDS) + 1) * _ROW_SIZE
        return _Layout(
            update_va=asm.label_va("update"),
            moduledata_ctor_va=asm.label_va("moduledata_ctor"),
            instance_ctor_va=asm.label_va("instance_ctor"),
            table_va=table_va,
            name_va=strings_va + offsets[0],
            keyword_vas=tuple(strings_va + off for off in offsets[1:]),
            size=(strings_va - base_va) + len(strings),
        )

    def _build(self, base_va: int) -> bytes:
        layout = self._layout(base_va)
        blob = bytearray(self._asm(base_va).finish())
        blob += b"\xcc" * (layout.table_va - base_va - len(blob))
        for (_, parse, offset, _type), keyword_va in zip(FIELDS, layout.keyword_vas, strict=True):
            blob += _u32(keyword_va) + _u32(parse) + _u32(0) + _u32(offset)
        blob += _u32(0) * 4
        blob += _string_block(self._names())[0]
        return bytes(blob)

    # ---- the cave -----------------------------------------------------------------------

    def _asm(self, base_va: int) -> Asm:
        asm = Asm(base_va)
        self._emit_update(asm)
        self._emit_command_sets(asm)
        self._emit_moduledata_ctor(asm)
        self._emit_instance_ctor(asm)
        asm.finish()
        return asm

    def _emit_update(self, a: Asm) -> None:
        """`UpdateModule::update`, entered with ecx = the module's `+0x10` subobject.

        Frame, all ebp-relative: ``-0x10``/``-0x0C`` the partition filter, ``-0x20`` the iterator,
        ``-0x24`` the population total, ``-0x28`` the leading count, ``-0x2C`` the leading player
        (``-1`` for none or a tie), ``-0x34`` the `Object`, ``-0x38`` the `ModuleData`, ``-0x3C``
        `this`, ``-0x40`` the candidate's player, ``-0x44`` whether `ObjectFilter` was written,
        ``-0x48`` the flag's own player, ``-0x4C`` whether the claim is being taken away this
        tick, ``-0x90`` twenty per-player counts and ``-0xE0`` twenty
        per-player teams.

        `iterateObjectsInRange` is **cdecl and does not clean its arguments** - both stock callers
        leak them and recover through the frame pointer - so the epilogue restores esp from ebp
        rather than popping."""
        a.label("update")
        a.emit(0x55)  # push ebp
        a.emit(b"\x89\xe5")  # mov ebp, esp
        a.emit(b"\x81\xec\xf0\x00\x00\x00")  # sub esp, 0xF0
        a.emit(0x53, 0x56, 0x57)  # push ebx / esi / edi
        a.emit(b"\x89\xce")  # mov esi, ecx           this
        a.emit(b"\x89\x75\xc4")  # mov [ebp-0x3C], esi
        a.emit(b"\x8b\x46\xf4")  # mov eax, [esi-0x0C]    ModuleData
        a.emit(b"\x89\x45\xc8")  # mov [ebp-0x38], eax
        a.emit(b"\x8b\x5e\xf8")  # mov ebx, [esi-0x08]    Object
        a.emit(b"\x89\x5d\xcc")  # mov [ebp-0x34], ebx
        a.emit(b"\x85\xdb")  # test ebx, ebx
        a.jcc(JE, "ret_one")

        # The stock module's own cadence: a countdown in the instance's one spare dword.
        a.emit(b"\x8b\x46\x10")  # mov eax, [esi+0x10]
        a.emit(b"\x85\xc0")  # test eax, eax
        a.jcc(JLE, "tick")
        a.emit(0x48)  # dec eax
        a.emit(b"\x89\x46\x10")  # mov [esi+0x10], eax
        a.jmp("ret_one")

        a.label("tick")
        a.emit(b"\x8b\x55\xc8")  # mov edx, [ebp-0x38]
        a.emit(b"\x8b\x42\x08")  # mov eax, [edx+0x08]    TickRate
        a.emit(b"\x89\x46\x10")  # mov [esi+0x10], eax
        a.emit(b"\x31\xc0")  # xor eax, eax
        a.emit(b"\xb9" + _u32(2 * _MAX_PLAYERS))  # mov ecx, 40
        a.emit(b"\x8d\xbd\x20\xff\xff\xff")  # lea edi, [ebp-0xE0]
        a.emit(b"\xf3\xab")  # rep stosd              counts and teams
        a.emit(b"\x89\x45\xdc")  # mov [ebp-0x24], eax    total = 0
        a.emit(b"\xc7\x85\x14\xff\xff\xff" + _u32(0))  # mov [ebp-0xEC], 0     not losing the claim

        # Whether the keyword was written, once per tick rather than once per candidate.
        a.emit(b"\x8b\x55\xc8")  # mov edx, [ebp-0x38]
        a.emit(b"\x8d\x4a\x18")  # lea ecx, [edx+0x18]
        a.call_absolute(_FILTER_WAS_SPECIFIED)
        a.emit(b"\x0f\xb6\xc0")  # movzx eax, al
        a.emit(b"\x89\x85\x1c\xff\xff\xff")  # mov [ebp-0xE4], eax

        # The flag's own controlling player, as the filter's *source*. Passing 0 there - which is
        # what every stock call site does - makes the evaluator reject unconditionally whenever a
        # relationship token is present, so ALLIES / ENEMIES / SAME_PLAYER would silently match
        # nothing at all. Sourced from the flag, they read relative to whoever holds it, which is
        # the only reading of "allied" a neutral piece of scenery can have.
        a.emit(b"\x89\xd9")  # mov ecx, ebx
        a.call_absolute(_GET_CONTROLLING_PLAYER)
        a.emit(b"\x89\x85\x18\xff\xff\xff")  # mov [ebp-0xE8], eax

        # One stock partition filter - "candidate is not dead" - and all other screening per
        # candidate, which is the shape PlayerHealSpecialPower's scan already uses.
        a.emit(b"\xc7\x45\xf0" + _u32(_FILTER_ALIVE_VTABLE))  # mov [ebp-0x10], vtable
        a.emit(b"\xc7\x45\xf4" + _u32(0))  # mov [ebp-0x0C], 0
        a.emit(b"\x8b\x55\xc8")  # mov edx, [ebp-0x38]
        a.emit(b"\xd9\x42\x0c")  # fld dword [edx+0x0C]   Radius
        a.emit(b"\x6a\x00")  # push 0                 list terminator
        a.emit(b"\x8d\x4d\xf0")  # lea ecx, [ebp-0x10]
        a.emit(0x51)  # push ecx                &filter
        a.emit(b"\x6a\x00")  # push 0
        a.emit(0x51)  # push ecx                the radius slot
        a.emit(b"\x8b\x0d" + _u32(_THE_PARTITION_MANAGER))  # mov ecx, ThePartitionManager
        a.emit(b"\xd9\x1c\x24")  # fstp dword [esp]
        a.emit(b"\x89\xd8")  # mov eax, ebx
        a.emit(b"\x83\xc0" + bytes([_OBJ_POSITION]))  # add eax, 0x38
        a.emit(0x50)  # push eax                &position
        a.emit(b"\x8d\x45\xe0")  # lea eax, [ebp-0x20]
        a.emit(0x50)  # push eax                &iterator
        a.call_absolute(_ITERATE_IN_RANGE)

        a.label("next")
        a.emit(b"\x8d\x4d\xe0")  # lea ecx, [ebp-0x20]
        a.call_absolute(_ITER_NEXT)
        a.emit(b"\x85\xc0")  # test eax, eax
        a.jcc(JE, "scan_done")
        a.emit(b"\x89\xc6")  # mov esi, eax           candidate
        a.emit(b"\x89\xf1")  # mov ecx, esi
        a.call_absolute(_GET_CONTROLLING_PLAYER)
        a.emit(b"\x85\xc0")  # test eax, eax
        a.jcc(JE, "next")
        a.emit(b"\x89\x45\xc0")  # mov [ebp-0x40], eax
        a.emit(b"\x83\xbd\x1c\xff\xff\xff\x00")  # cmp dword [ebp-0xE4], 0
        a.jcc(JE, "count")
        # The evaluator, not the wrapper: the wrapper hardcodes a null source.
        a.emit(b"\x8b\x55\xc8")  # mov edx, [ebp-0x38]
        a.emit(b"\xff\xb5\x18\xff\xff\xff")  # push [ebp-0xE8]        source: the flag's own player
        a.emit(0x50)  # push eax                candidate player
        a.emit(b"\x8b\x46" + bytes([_OBJ_TEMPLATE]))  # mov eax, [esi+0x04]
        a.emit(0x50)  # push eax                ThingTemplate
        a.emit(b"\x8d\x4a\x18")  # lea ecx, [edx+0x18]
        a.call_absolute(_FILTER_TEST)
        a.emit(b"\x84\xc0")  # test al, al
        a.jcc(JE, "next")

        a.label("count")
        a.emit(b"\xb8" + _u32(1))  # mov eax, 1             a bare object counts once
        a.emit(b"\x8b\x55\xc8")  # mov edx, [ebp-0x38]
        a.emit(b"\x80\x7a\x1c\x00")  # cmp byte [edx+0x1C], 0  CountHordeMembers
        a.jcc(JE, "bucket")
        a.emit(b"\x83\xbd\x1c\xff\xff\xff\x00")  # cmp dword [ebp-0xE4], 0
        a.jcc(JE, "bucket")
        a.emit(b"\x89\xf1")  # mov ecx, esi
        a.call_absolute(_GET_CONTAIN)
        a.emit(b"\x85\xc0")  # test eax, eax
        a.jcc(JE, "bucket_one")
        a.emit(b"\x8b\x55\xc8")  # mov edx, [ebp-0x38]
        a.emit(b"\x8d\x52\x18")  # lea edx, [edx+0x18]
        a.emit(0x52)  # push edx                &ObjectFilter
        a.emit(b"\x89\xc1")  # mov ecx, eax
        a.emit(b"\x8b\x00")  # mov eax, [eax]
        a.emit(b"\xff\x90" + _u32(_CONTAIN_COUNT_SLOT))  # call [eax+0x180]
        a.emit(b"\x85\xc0")  # test eax, eax
        a.jcc(JE, "next")  # a horde with no matching member contributes nothing
        a.jmp("bucket")
        a.label("bucket_one")
        a.emit(b"\xb8" + _u32(1))  # mov eax, 1

        a.label("bucket")
        a.emit(b"\x8b\x4d\xc0")  # mov ecx, [ebp-0x40]
        a.emit(b"\x8b\x49" + bytes([_PLAYER_INDEX]))  # mov ecx, [ecx+0x54]
        a.emit(b"\x83\xf9" + bytes([_MAX_PLAYERS]))  # cmp ecx, 20
        a.jcc(JAE, "next")  # unsigned, so a negative index is caught too
        a.emit(b"\x01\x84\x8d\x70\xff\xff\xff")  # add [ebp+ecx*4-0x90], eax
        a.emit(b"\x01\x45\xdc")  # add [ebp-0x24], eax
        # One representative *object* per player, not just its team. The team is one dereference
        # away (`+0x31C`) and so is the object id (`+0x74`), and the id is what the flag's Lua
        # wants while a capture is running - see the `+0x80` write in the rise arm.
        a.emit(b"\x89\xb4\x8d\x20\xff\xff\xff")  # mov [ebp+ecx*4-0xE0], esi
        a.jmp("next")

        a.label("scan_done")
        a.emit(b"\x8d\x4d\xe0")  # lea ecx, [ebp-0x20]
        a.call_absolute(_ITER_RELEASE)

        # The leader, and whether there is one: a tie between two non-zero counts is no contender.
        a.emit(b"\xc7\x45\xd8" + _u32(0))  # mov [ebp-0x28], 0
        a.emit(b"\xc7\x45\xd4" + _u32(0xFFFFFFFF))  # mov [ebp-0x2C], -1
        a.emit(b"\x31\xc9")  # xor ecx, ecx
        a.label("tally")
        a.emit(b"\x8b\x84\x8d\x70\xff\xff\xff")  # mov eax, [ebp+ecx*4-0x90]
        a.emit(b"\x3b\x45\xd8")  # cmp eax, [ebp-0x28]
        a.jcc(JB, "tally_equal")
        a.jcc(JE, "tally_equal")
        a.emit(b"\x89\x45\xd8")  # mov [ebp-0x28], eax
        a.emit(b"\x89\x4d\xd4")  # mov [ebp-0x2C], ecx
        a.jmp("tally_next")
        a.label("tally_equal")
        a.jcc(JNE, "tally_next")
        a.emit(b"\x85\xc0")  # test eax, eax
        a.jcc(JE, "tally_next")
        a.emit(b"\xc7\x45\xd4" + _u32(0xFFFFFFFF))  # mov [ebp-0x2C], -1
        a.label("tally_next")
        a.emit(0x41)  # inc ecx
        a.emit(b"\x83\xf9" + bytes([_MAX_PLAYERS]))  # cmp ecx, 20
        a.jcc(JB, "tally")

        # best * 100 >= total * CaptureShare, as integers: no division, no float. Each of the
        # three ways to fail means "nobody holds the ground" - an empty radius, a tie, or a
        # leader short of the share - and all three decay rather than freeze.
        a.emit(b"\x8b\x45\xd4")  # mov eax, [ebp-0x2C]
        a.emit(b"\x83\xf8\x00")  # cmp eax, 0
        a.jcc(JL, "decay")
        a.emit(b"\x8b\x4d\xdc")  # mov ecx, [ebp-0x24]    total
        a.emit(b"\x85\xc9")  # test ecx, ecx
        a.jcc(JLE, "decay")
        a.emit(b"\x8b\x45\xd8")  # mov eax, [ebp-0x28]    best
        a.emit(b"\x6b\xc0\x64")  # imul eax, eax, 100
        a.emit(b"\x8b\x55\xc8")  # mov edx, [ebp-0x38]
        a.emit(b"\x8b\x52\x14")  # mov edx, [edx+0x14]    CaptureShare
        a.emit(b"\x0f\xaf\xd1")  # imul edx, ecx
        a.emit(b"\x39\xd0")  # cmp eax, edx
        a.jcc(JGE, "contended")

        # Nobody holds the ground: give it back rather than freezing. The bar falls at the same
        # `TickAmount` it rose at, flying the losing-the-claim flag so the art plays
        # `CANCEL_CAPTURE` - the state whose animation *lowers* the banner - and at zero the
        # claim, the capturing id and every capture condition clear together, which is the flag
        # returning to how it started.
        a.label("decay")
        a.emit(b"\x8b\x75\xc4")  # mov esi, [ebp-0x3C]    this
        a.emit(b"\x83\x7e\x14\x00")  # cmp dword [esi+0x14], 0
        a.jcc(JLE, "decayed")  # already empty: just make sure it reads empty
        a.emit(
            b"\xc7\x85\x14\xff\xff\xff" + _u32(1)
        )  # mov [ebp-0xEC], 1     losing it -> CANCEL_CAPTURE
        a.emit(b"\x8b\x45\xc8")  # mov eax, [ebp-0x38]
        a.emit(b"\x8b\x40\x10")  # mov eax, [eax+0x10]    TickAmount
        a.emit(b"\x29\x46\x14")  # sub [esi+0x14], eax
        a.emit(b"\x83\x7e\x14\x00")  # cmp dword [esi+0x14], 0
        a.jcc(JG, "apply")  # still falling
        a.emit(b"\xc7\x46\x14" + _u32(0))  # mov dword [esi+0x14], 0

        a.label("decayed")
        a.emit(b"\x83\x4e\x18\xff")  # or dword [esi+0x18], -1   claimant = nobody
        a.emit(b"\x8b\x4d\xcc")  # mov ecx, [ebp-0x34]
        a.emit(b"\x83\xa1" + _u32(_OBJ_CAPTURING_ID) + b"\x00")  # and [ecx+0x80], 0
        a.jmp("apply")

        # The accumulator. Ownership moves only at 100; zero transfers the claim, not the flag.
        a.label("contended")
        a.emit(b"\x8b\x75\xc4")  # mov esi, [ebp-0x3C]    this
        a.emit(b"\x8b\x55\xd4")  # mov edx, [ebp-0x2C]    contender
        a.emit(b"\x8b\x4e\x18")  # mov ecx, [esi+0x18]    claimant
        a.emit(b"\x39\xd1")  # cmp ecx, edx
        a.jcc(JE, "rise")
        a.emit(b"\x83\xf9\xff")  # cmp ecx, -1
        a.jcc(JE, "rise")
        a.emit(b"\x8b\x45\xc8")  # mov eax, [ebp-0x38]
        a.emit(b"\x8b\x40\x10")  # mov eax, [eax+0x10]    TickAmount
        a.emit(
            b"\xc7\x85\x14\xff\xff\xff" + _u32(1)
        )  # mov [ebp-0xEC], 1     the claim is being taken
        a.emit(b"\x29\x46\x14")  # sub [esi+0x14], eax
        a.emit(b"\x83\x7e\x14\x00")  # cmp dword [esi+0x14], 0
        a.jcc(JG, "apply")
        a.emit(b"\xc7\x46\x14" + _u32(0))  # mov dword [esi+0x14], 0
        a.emit(b"\x89\x56\x18")  # mov [esi+0x18], edx    the claim passes over
        a.emit(b"\x8b\x4d\xcc")  # mov ecx, [ebp-0x34]
        a.emit(b"\x83\xa1" + _u32(_OBJ_CAPTURING_ID) + b"\x00")  # and [ecx+0x80], 0
        a.jmp("apply")

        a.label("rise")
        a.emit(b"\x89\x56\x18")  # mov [esi+0x18], edx
        a.emit(b"\x8b\x45\xc8")  # mov eax, [ebp-0x38]
        a.emit(b"\x8b\x40\x10")  # mov eax, [eax+0x10]    TickAmount
        a.emit(b"\x01\x46\x14")  # add [esi+0x14], eax

        # Who is taking it, published where the flag's own script looks for it. The art raises
        # the *capturing* player's banner while the bar fills - `START_CAPTURE` carries
        # `LuaEvent = OnStateEnter`, and `OnCaptureFlagGenericEvent` asks
        # `ObjectCapturingObjectPlayerSide` first, which reads this field. Leave it unset and the
        # script falls back to the flag's own side, which during a capture is still the *old*
        # owner - so the pole rises with no banner on it and the new one appears already up at
        # the end. Nothing in the stock image ever writes this field; on a flag, this module is
        # the only thing that can.
        a.emit(b"\x8b\x4d\xd4")  # mov ecx, [ebp-0x2C]     the contender
        a.emit(b"\x8b\x84\x8d\x20\xff\xff\xff")  # mov eax, [ebp+ecx*4-0xE0]  its representative
        a.emit(b"\x85\xc0")  # test eax, eax
        a.jcc(JE, "risen")
        a.emit(b"\x8b\x40" + bytes([_OBJ_ID]))  # mov eax, [eax+0x74]    its ObjectID
        a.emit(b"\x8b\x4d\xcc")  # mov ecx, [ebp-0x34]
        a.emit(b"\x89\x81" + _u32(_OBJ_CAPTURING_ID))  # mov [ecx+0x80], eax

        a.label("risen")
        a.emit(b"\x83\x7e\x14\x64")  # cmp dword [esi+0x14], 100
        a.jcc(JL, "apply")
        a.emit(b"\xc7\x46\x14" + _u32(100))  # mov dword [esi+0x14], 100
        # The contending units' own team is the team the flag joins - no player-to-team lookup.
        a.emit(b"\x8b\x4d\xd4")  # mov ecx, [ebp-0x2C]
        a.emit(b"\x8b\x94\x8d\x20\xff\xff\xff")  # mov edx, [ebp+ecx*4-0xE0]  the representative
        a.emit(b"\x85\xd2")  # test edx, edx
        a.jcc(JE, "apply")
        a.emit(b"\x8b\x92" + _u32(_OBJ_TEAM))  # mov edx, [edx+0x31C]   its team
        a.emit(b"\x85\xd2")  # test edx, edx
        a.jcc(JE, "apply")
        a.emit(b"\x8b\x45\xcc")  # mov eax, [ebp-0x34]    Object
        a.emit(b"\x39\x90" + _u32(_OBJ_TEAM))  # cmp [eax+0x31C], edx
        a.jcc(JE, "apply")
        a.emit(b"\x89\x95\x10\xff\xff\xff")  # mov [ebp-0xF0], edx   setTeam clobbers edx
        a.emit(b"\x6a\x00")  # push 0                 0 = notify; see _SET_TEAM
        a.emit(0x52)  # push edx                the new team
        a.emit(b"\x89\xc1")  # mov ecx, eax
        a.call_absolute(_SET_TEAM)  # ret 8 - it cleans both
        a.emit(b"\x8b\x4d\xcc")  # mov ecx, [ebp-0x34]
        a.call("command_sets")  # re-file the flag's own command set under the new owner

        # Then the structures the flag speaks for. A `ShipWright` carries `LINKED_TO_FLAG` and,
        # pointedly, **not** `CAPTURABLE` - it cannot be taken directly, so the flag is its only
        # route, and a capture that moves only the flag leaves the thing the flag exists for
        # sitting neutral. The stock ability propagates; so must this.
        #
        # A second scan rather than bookkeeping during the first: this runs on the one tick a
        # flag changes hands, where the cost is irrelevant, instead of adding per-candidate work
        # to every tick of every flag. `CaptureFlag` does not carry the bit itself, so the flag
        # cannot match its own sweep.
        a.emit(b"\xc7\x45\xf0" + _u32(_FILTER_ALIVE_VTABLE))  # mov [ebp-0x10], vtable
        a.emit(b"\xc7\x45\xf4" + _u32(0))  # mov [ebp-0x0C], 0
        a.emit(b"\x8b\x55\xc8")  # mov edx, [ebp-0x38]
        a.emit(b"\xd9\x42\x0c")  # fld dword [edx+0x0C]   the same Radius
        a.emit(b"\x6a\x00")  # push 0
        a.emit(b"\x8d\x4d\xf0")  # lea ecx, [ebp-0x10]
        a.emit(0x51)  # push ecx
        a.emit(b"\x6a\x00")  # push 0
        a.emit(0x51)  # push ecx
        a.emit(b"\x8b\x0d" + _u32(_THE_PARTITION_MANAGER))  # mov ecx, ThePartitionManager
        a.emit(b"\xd9\x1c\x24")  # fstp dword [esp]
        a.emit(b"\x8b\x45\xcc")  # mov eax, [ebp-0x34]
        a.emit(b"\x83\xc0" + bytes([_OBJ_POSITION]))  # add eax, 0x38
        a.emit(0x50)  # push eax
        a.emit(b"\x8d\x45\xe0")  # lea eax, [ebp-0x20]
        a.emit(0x50)  # push eax
        a.call_absolute(_ITERATE_IN_RANGE)

        a.label("linked_next")
        a.emit(b"\x8d\x4d\xe0")  # lea ecx, [ebp-0x20]
        a.call_absolute(_ITER_NEXT)
        a.emit(b"\x85\xc0")  # test eax, eax
        a.jcc(JE, "linked_done")
        a.emit(b"\x89\xc6")  # mov esi, eax           candidate
        a.emit(b"\x8b\x46" + bytes([_OBJ_TEMPLATE]))  # mov eax, [esi+0x04]
        a.emit(b"\xf6\x80" + _u32(_KINDOF_BYTE) + bytes([_LINKED_TO_FLAG]))  # test LINKED_TO_FLAG
        a.jcc(JE, "linked_next")
        a.emit(b"\x8b\x95\x10\xff\xff\xff")  # mov edx, [ebp-0xF0]   the new team
        a.emit(b"\x39\x96" + _u32(_OBJ_TEAM))  # cmp [esi+0x31C], edx
        a.jcc(JE, "linked_next")
        a.emit(b"\x6a\x00")  # push 0                 notify, as above
        a.emit(0x52)  # push edx
        a.emit(b"\x89\xf1")  # mov ecx, esi
        a.call_absolute(_SET_TEAM)
        a.emit(b"\x89\xf1")  # mov ecx, esi           it preserves esi
        a.call("command_sets")  # the shipyard's own CommandSetUpgrade

        # And mark it captured. Measured, not assumed: across two stock captures the linked
        # `ShipWright` came out with `+0x118` gaining `0x00800000` - `CAPTURED` - while a capture
        # done by this module left it clear. It is the one non-pointer difference between a
        # stock-captured and a module-captured structure, so whatever downstream reads it (the
        # engine ships a `MonitorConditionUpdate` whose whole job is swapping a command set on a
        # model condition) has been seeing an uncaptured building.
        a.emit(b"\x8b\x86" + _u32(_MODEL_CONDITION_DWORD))  # mov eax, [esi+0x118]
        a.emit(b"\x0d" + _u32(_BIT_CAPTURED))  # or eax, CAPTURED
        a.emit(b"\x89\x86" + _u32(_MODEL_CONDITION_DWORD))  # mov [esi+0x118], eax
        a.emit(b"\x89\xf1")  # mov ecx, esi
        a.call_absolute(_PROPAGATE_MODEL_CONDITIONS)
        a.jmp("linked_next")

        a.label("linked_done")
        a.emit(b"\x8d\x4d\xe0")  # lea ecx, [ebp-0x20]
        a.call_absolute(_ITER_RELEASE)

        # The three model conditions the stock CaptureFlag art actually animates, set only on a
        # change. The mapping is onto the *art's* states, not onto the accumulator's: a bar going
        # up is the flag being raised (`START_CAPTURE`, whose `OnStateEnter` Lua does the
        # raising), a bar going down is it being taken back off you (`CANCEL_CAPTURE`, which
        # lowers it), and a full bar is `CAPTURED`. A halt holds whichever it already was.
        a.label("apply")
        a.emit(b"\x8b\x75\xc4")  # mov esi, [ebp-0x3C]
        a.emit(b"\x8b\x5d\xcc")  # mov ebx, [ebp-0x34]
        a.emit(b"\x8b\x46\x14")  # mov eax, [esi+0x14]    progress
        a.emit(b"\x31\xd2")  # xor edx, edx
        a.emit(b"\x85\xc0")  # test eax, eax
        a.jcc(JLE, "conditions")  # empty bar: flag down, no bits
        a.emit(b"\x83\xbd\x14\xff\xff\xff\x00")  # cmp dword [ebp-0xEC], 0
        a.jcc(JE, "not_losing")
        a.emit(b"\xba" + _u32(_BIT_CANCEL_CAPTURE))  # mov edx, CANCEL_CAPTURE
        a.jmp("conditions")
        a.label("not_losing")
        a.emit(b"\x83\xf8\x64")  # cmp eax, 100
        a.jcc(JL, "raising")
        a.emit(b"\xba" + _u32(_BIT_CAPTURED))  # mov edx, CAPTURED
        a.jmp("conditions")
        a.label("raising")
        a.emit(b"\xba" + _u32(_BIT_START_CAPTURE))  # mov edx, START_CAPTURE
        a.label("conditions")
        a.emit(b"\x3b\x56\x1c")  # cmp edx, [esi+0x1C]
        a.jcc(JE, "ret_one")
        a.emit(b"\x89\x56\x1c")  # mov [esi+0x1C], edx
        a.emit(b"\x8b\x83" + _u32(_MODEL_CONDITION_DWORD))  # mov eax, [ebx+0x118]
        a.emit(b"\x25" + _u32(_BIT_CLEAR_MASK))  # and eax, ~(both bits)
        a.emit(b"\x09\xd0")  # or eax, edx
        a.emit(b"\x89\x83" + _u32(_MODEL_CONDITION_DWORD))  # mov [ebx+0x118], eax
        a.emit(b"\x89\xd9")  # mov ecx, ebx
        a.call_absolute(_PROPAGATE_MODEL_CONDITIONS)

        a.label("ret_one")
        a.emit(b"\x8d\xa5\x04\xff\xff\xff")  # lea esp, [ebp-0xFC]
        a.emit(0x5F, 0x5E, 0x5B)  # pop edi / esi / ebx
        a.emit(b"\x89\xec")  # mov esp, ebp
        a.emit(0x5D)  # pop ebp
        a.emit(b"\xb8" + _u32(1))  # mov eax, 1   "call me again next frame"
        a.emit(0xC3)  # ret

    def _emit_command_sets(self, a: Asm) -> None:
        """`__thiscall(ecx = Object*)` - re-file every `CommandSetUpgrade` on the object against
        its **current** owner. Called after each `setTeam`, on the flag and on every linked
        structure.

        A `CommandSetUpgrade` does not store its override on the object; it registers it into the
        controlling *player*, keyed by the object's id. So an object that changes hands leaves its
        entry behind with the old owner and shows its template default - which is a shipyard that
        changed hands and kept the neutral command set. Re-running the registration under the new
        owner is the fix, and the engine's own routine does it correctly because it re-reads
        `getControllingPlayer` each time.

        **The subobject offset is the whole difficulty.** `CommandSetUpgrade`'s constructor writes
        its interface vtable to ``module+0x10``, and the registration is slot ``+0x20`` of *that*
        vtable. Everything that walks a module array generically - `Object::onCapture`, the
        upgrade refresh at `0x006902FA` - dispatches through the vtable at ``module+0``, a
        different table, so none of them can reach it. That is why an earlier build calling
        `0x006902FA` changed nothing.

        Identity is checked rather than assumed: only a module whose ``+0x10`` holds
        :data:`_COMMAND_SET_UPGRADE_VTABLE` is called, so no other module can be entered by
        mistake."""
        a.label("command_sets")
        a.emit(0x56, 0x57)  # push esi / push edi
        a.emit(b"\x8b\xb9" + _u32(_OBJ_MODULES))  # mov edi, [ecx+0x24C]
        a.jmp("cs_test")
        a.label("cs_body")
        a.emit(b"\x81\x7e\x10" + _u32(_COMMAND_SET_UPGRADE_VTABLE))  # cmp [esi+0x10], vtable
        a.jcc(JNE, "cs_next")
        a.emit(b"\x8d\x4e\x10")  # lea ecx, [esi+0x10]   the interface subobject
        a.call_absolute(_REGISTER_COMMAND_SET)
        a.label("cs_next")
        a.emit(b"\x83\xc7\x04")  # add edi, 4
        a.label("cs_test")
        a.emit(b"\x8b\x37")  # mov esi, [edi]
        a.emit(b"\x85\xf6")  # test esi, esi
        a.jcc(JNE, "cs_body")
        a.emit(0x5F, 0x5E)  # pop edi / pop esi
        a.emit(0xC3)  # ret

    def _emit_moduledata_ctor(self, a: Asm) -> None:
        """`__thiscall(ecx = the allocation) -> eax = it`, replacing the stock ctor call.

        Runs the stock constructor, then writes the new defaults over the two heal fields it
        just initialised and constructs the `ObjectFilter` handle. That last step is not
        optional: the parse function releases whatever it finds in the slot unless it is ``-1``,
        so an unconstructed field hands `operator new`'s leftovers to the interned store."""
        a.label("moduledata_ctor")
        a.emit(0x56)  # push esi
        a.emit(b"\x89\xce")  # mov esi, ecx
        a.call_absolute(MODULEDATA_CTOR_VA)
        a.emit(b"\xc7\x46\x08" + _u32(int(DEFAULTS["TickRate"])))
        a.emit(b"\xc7\x46\x0c" + struct.pack("<f", float(DEFAULTS["Radius"])))
        a.emit(b"\xc7\x46\x10" + _u32(int(DEFAULTS["TickAmount"])))
        a.emit(b"\xc7\x46\x14" + _u32(int(DEFAULTS["CaptureShare"])))
        a.emit(b"\xc6\x46\x1c" + bytes([1 if DEFAULTS["CountHordeMembers"] else 0]))
        a.emit(b"\x8d\x4e\x18")  # lea ecx, [esi+0x18]
        a.call_absolute(_FILTER_CTOR)
        a.emit(b"\x89\xf0")  # mov eax, esi
        a.emit(0x5E)  # pop esi
        a.emit(0xC3)  # ret

    def _emit_instance_ctor(self, a: Asm) -> None:
        """`__thiscall(ecx = the allocation, arg1, arg2)`, ``ret 8`` - the stock signature.

        The stock constructor zeroes only ``+0x20``; the accumulator this patch adds at ``+0x24``
        is whatever `operator new` returned, so a flag would start life mid-capture for a garbage
        player. The claim starts at ``-1``, which is "nobody"."""
        a.label("instance_ctor")
        a.emit(0x55)  # push ebp
        a.emit(b"\x89\xe5")  # mov ebp, esp
        a.emit(0x56)  # push esi
        a.emit(b"\x89\xce")  # mov esi, ecx
        a.emit(b"\xff\x75\x0c")  # push [ebp+0x0C]
        a.emit(b"\xff\x75\x08")  # push [ebp+0x08]
        a.emit(b"\x89\xf1")  # mov ecx, esi
        a.call_absolute(INSTANCE_CTOR_VA)  # cleans its own two arguments
        a.emit(b"\x83\x66\x24\x00")  # and dword [esi+0x24], 0   progress
        a.emit(b"\x83\x4e\x28\xff")  # or  dword [esi+0x28], -1  claimant = nobody
        a.emit(b"\x83\x66\x2c\x00")  # and dword [esi+0x2C], 0   applied conditions
        a.emit(b"\x89\xf0")  # mov eax, esi
        a.emit(0x5E)  # pop esi
        a.emit(0x5D)  # pop ebp
        a.emit(b"\xc2\x08\x00")  # ret 8

    # ---- apply --------------------------------------------------------------------------

    def _assert_stock_table(self, data: bytearray) -> None:
        """The stock four rows plus terminator, checked before they are abandoned. Read from the
        live image rather than assumed, so a build that already relocated this table fails loudly
        instead of being silently replaced."""
        off = _offset(data, FIELD_TABLE_VA)
        for index, (keyword, parse, offset) in enumerate(STOCK_FIELD_TABLE):
            name_va, parse_va, _user, field_off = struct.unpack_from(
                "<IIII", data, off + index * _ROW_SIZE
            )
            name_off = _offset(data, name_va)
            end = data.index(b"\x00", name_off)
            got = bytes(data[name_off:end]).decode("latin1")
            if (got, parse_va, field_off) != (keyword, parse, offset):
                raise ValueError(
                    f"row {index}: expected ({keyword}, {parse:#x}, {offset:#x}), "
                    f"got ({got}, {parse_va:#x}, {field_off:#x})"
                )
        if struct.unpack_from("<I", data, off + len(STOCK_FIELD_TABLE) * _ROW_SIZE)[0] != 0:
            raise ValueError("the field-parse table is not terminated where it should be")

    def apply(self, data: bytearray) -> None:
        self._assert_stock_table(data)
        base_va = allocate_section(data, SECTION_NAME, self._build, 0x60000020)
        layout = self._layout(base_va)

        apply_byte_patch(
            data,
            _offset(data, INSTANCE_SIZE_VA),
            bytes([0x6A, STOCK_INSTANCE_SIZE]),
            bytes([0x6A, PATCHED_INSTANCE_SIZE]),
            "module instance size 0x24 -> 0x30",
        )
        apply_byte_patch(
            data,
            _offset(data, MODULEDATA_SIZE_VA),
            bytes([0x6A, STOCK_MODULEDATA_SIZE]),
            bytes([0x6A, PATCHED_MODULEDATA_SIZE]),
            "ModuleData size 0x18 -> 0x20",
        )
        self._repoint_call(data, INSTANCE_CTOR_CALL_VA, INSTANCE_CTOR_VA, layout.instance_ctor_va)
        self._repoint_call(
            data, MODULEDATA_CTOR_CALL_VA, MODULEDATA_CTOR_VA, layout.moduledata_ctor_va
        )
        apply_byte_patch(
            data,
            _offset(data, UPDATE_VTABLE_VA),
            _u32(STOCK_UPDATE_VA),
            _u32(layout.update_va),
            "UpdateModule vtable slot 0 -> the cave",
        )
        apply_byte_patch(
            data,
            _offset(data, FIELD_TABLE_REF_VA),
            _u32(FIELD_TABLE_VA),
            _u32(layout.table_va),
            "field-parse table -> the cave",
        )
        for va, opcode in zip(NAME_REF_VAS, NAME_REF_OPCODES, strict=True):
            apply_byte_patch(
                data,
                _offset(data, va - 1),
                opcode + _u32(STOCK_NAME_VA),
                opcode + _u32(layout.name_va),
                f"block name @{va - 1:#x} -> {self.block_name}",
            )

    @staticmethod
    def _repoint_call(data: bytearray, site_va: int, stock_target: int, new_target: int) -> None:
        off = _offset(data, site_va)
        old = b"\xe8" + struct.pack("<i", stock_target - (site_va + 5))
        new = b"\xe8" + struct.pack("<i", new_target - (site_va + 5))
        apply_byte_patch(data, off, old, new, f"call {stock_target:#x} -> the cave")

    # ---- verify / detect ----------------------------------------------------------------

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch for exactly this block name.

        Every address is recovered from where the cave actually landed rather than from where it
        would land on a clean image, so a build carrying other patches' sections verifies the
        same."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        base_va, _off, _vsize = located
        problems: list[str] = []
        try:
            layout = self._layout(base_va)
            problems += self._verify_sites(data, layout)
        except (ValueError, struct.error) as exc:
            problems.append(f"cannot read back the patch (wrong build?): {exc}")
        return problems

    def _verify_sites(self, data: bytes | bytearray, layout: _Layout) -> list[str]:
        problems: list[str] = []

        def dword(va: int) -> int:
            return int(struct.unpack_from("<I", data, _offset(data, va))[0])

        def byte(va: int) -> int:
            return data[_offset(data, va)]

        if byte(INSTANCE_SIZE_VA + 1) != PATCHED_INSTANCE_SIZE:
            problems.append("the module instance allocation was not grown")
        if byte(MODULEDATA_SIZE_VA + 1) != PATCHED_MODULEDATA_SIZE:
            problems.append("the ModuleData allocation was not grown")
        if dword(UPDATE_VTABLE_VA) != layout.update_va:
            problems.append("the UpdateModule vtable slot does not point at the cave")
        if dword(FIELD_TABLE_REF_VA) != layout.table_va:
            problems.append("the field-parse table reference does not point at the cave")
        for va in NAME_REF_VAS:
            if dword(va) != layout.name_va:
                problems.append(f"the block name at {va - 1:#x} does not point at the cave")

        for index, (keyword, parse, offset, _type) in enumerate(FIELDS):
            row = layout.table_va + index * _ROW_SIZE
            name_va, parse_va, _user, field_off = (dword(row + n * 4) for n in range(4))
            try:
                name_off = _offset(data, name_va)
            except ValueError:
                problems.append(f"row {index}: name pointer is unmapped")
                continue
            end = data.index(b"\x00", name_off)
            got = bytes(data[name_off:end]).decode("latin1")
            if (got, parse_va, field_off) != (keyword, parse, offset):
                problems.append(f"row {index}: expected {keyword}, got {got}")
        if dword(layout.table_va + len(FIELDS) * _ROW_SIZE) != 0:
            problems.append("the rebuilt field-parse table is not terminated")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> CaptureTheFlagPatch | None:
        """Recognise the patch, and the block name it was installed with, in a binary somebody
        else built. The name is read back out of the cave rather than guessed, so a build using a
        non-default `--block-name` is reported as what it actually is."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        base_va, _off, _vsize = located
        try:
            probe = cls()
            table_va = struct.unpack_from("<I", data, _offset(data, FIELD_TABLE_REF_VA) or 0)[0]
            if not base_va <= table_va < base_va + 0x10000:
                return None
            name_va = struct.unpack_from("<I", data, va_to_offset(data, NAME_REF_VAS[0]) or 0)[0]
            name_off = va_to_offset(data, name_va)
            if name_off is None:
                return None
            end = data.index(b"\x00", name_off)
            block = bytes(data[name_off:end]).decode("latin1")
            probe = cls(block_name=block)
        except (ValueError, struct.error, UnicodeDecodeError):
            return None
        return probe if not probe.verify(data) else None

    # ---- the INI surface ----------------------------------------------------------------

    def ini_surface(self) -> Engine:
        """The block this patch creates and the six keywords it carries.

        `AutoFindHealingUpdate` is **replaced**, not extended, so it is declared gone rather than
        left in the model: a mod that still writes it is writing a block the patched engine no
        longer registers, and saying so is more useful than letting its four keywords convert."""
        return Engine(
            blocks=(
                BlockDelta(self.block_name, base="Behavior", patch=self.name),
                BlockDelta("AutoFindHealingUpdate", removed=True, patch=self.name),
            ),
            fields=tuple(
                FieldDelta(self.block_name, keyword, type_name, DEFAULTS.get(keyword), self.name)
                for keyword, _parse, _offset, type_name in FIELDS
            ),
        )
