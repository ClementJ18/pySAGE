"""A model condition that is set while a building's production queue is non-empty.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/production-model-condition.md``.

**The gap.** The engine has no model condition meaning "this structure is currently making
something". `ProductionUpdate` drives the `DOOR_n_*` conditions, but those run *after* a unit
finishes, as the buffer during which it walks out - so they say "a unit just completed", not
"a unit is being trained". `ModelConditionUpgrade` likewise fires on an upgrade's *completion*.
Neither expresses the state a mod actually wants to draw: queue non-empty, from the frame the
order lands to the frame the queue drains.

**What this does.** Adds one entry to the engine's `ModelConditionFlags` name table (so the new
token parses anywhere a model condition is accepted - `ModelConditionState`,
`DisableOnModelCondition`, `HideSubObject`, ...) and hooks `ProductionUpdate::update` to keep its
bit equal to "this module's production queue is non-empty".

Both halves of the requirement land on one bit, because units and upgrades share one queue:
`ProductionUpdate` holds a single linked list whose entries carry their kind at ``+0x04``, and
both `queueCreateUnit` and `queueUpgrade` prepend to it. The condition is therefore true while
the building is training a unit **or** researching an upgrade, or both.

Two optional extras, off the same trigger
-----------------------------------------
``--weapon-set-flag`` and ``--locomotor-set`` add a `WeaponSetFlags` name and a `LocomotorSetType`
name driven by the same "queue non-empty" test, so a mod can give a producer a different weapon
loadout and a different locomotor while it is busy. Both are opt-in and independent: neither is
installed unless named, and the patch without them is byte-for-byte what it always was.

They are cheaper than the model condition rather than more expensive, because both tables are read
through their terminator and never through a count - see :mod:`.weapon_set_flags` and
:mod:`.locomotor_sets`, which own the two tables the way :mod:`.model_conditions` owns this one.
What each costs at the *object* is one engine call on the frame the state changes:
`Object::setWeaponSetFlags` already calls `WeaponSet::updateWeaponSet`, and `chooseLocomotorSet`
already refuses when the template declares no locomotor for the set.

**All three blocks are level-triggered**, each guarding on its own state rather than on the model
condition's edge. That is not symmetry for its own sake: the model-condition bit *is* saved (by
name, through `xfer`) and the weapon-set bit is *not*, so a hook that acted only on the transition
would come back from a savegame with the condition set and the weapon set flag lost, and never
correct itself. Reading each piece of state per frame is what makes the three agree again on the
first frame after a load - and, for the locomotor, what lets "producing" outrank a set the engine
chose meanwhile, instead of silently losing to it.

Why one condition, and what a second would cost
-----------------------------------------------
`ModelConditionFlags` is 19 dwords (``0x4C`` bytes) holding **591** named bits, so 17 bit slots
are already allocated and unnamed - no structure grows to hold a 592nd.

Serialisation does not bound it either, contrary to what this docstring said before the `xfer`
branches were followed. ``ModelConditionFlags::xfer`` (``0x004BAEE4``) has three paths: a
**74-byte packed blob** (``0x004B8D87``, taken when ``[Xfer+0x10]``, and not the save/load path),
**save as a list of names**, and **load by resolving names** through the same parser this patch's
table feeds. Savegames therefore carry no bit layout and no length constant, and are unaffected by
the count.

What is left is the blob, whose 74 bytes are 592 bits *exactly* - so bit 591 is the last one it
covers. Bits 592-607 would parse, set, draw and save/load correctly but fall outside it unless the
two ``push 0x4a`` are widened (the packer's buffer is already ``sub esp, 0x4c`` = 608 bits, so
nothing grows). Past 608 the mask itself must grow, and ``Object+0x10C`` is immediately followed
by ``+0x158`` - an `Object` layout change, not a byte patch.

One condition is what this patch installs because one trigger is what it implements, not because
a second bit is expensive. See ``../docs/production-model-condition.md`` §2a.

Why the count and the table must move together
----------------------------------------------
Two of the ten count-bounded loops (``0x00446103``, ``0x004BAF80``) walk ``0..count`` calling the
single-bit-name helper at ``0x00444DFB``, which indexes the table with **no bound check**. Raising
the count without extending the table would hand a NULL string pointer to `AsciiString`
concatenation. :meth:`apply` writes both or raises, and :meth:`verify` checks both.

**Loading a save on a stock binary.** The load path aborts on a name it cannot resolve
(``0x004BAFDC`` falls into ``int3`` at ``0x004BB022``), and a save only names bits that are *set*.
So a save taken while some object is producing fails **fatally** on an unpatched `game.dat`; one
taken with nothing producing loads fine.

**Determinism.** The mask patched is on the logic-side `Object` (``+0x10C``), not the `Drawable`,
and it is part of what the engine CRCs - so every peer must run the same patched binary. That is
stricter than the other bundled patches, which are data-shape changes: a patched and an unpatched
client desync the moment a building starts producing, and a replay recorded on one will not play
back on the other. Nothing in the order stream changes.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. The 5-byte entry of `ProductionUpdate::update` is touched by no
other bundled patch. The name table and the ten counts **are** shared - `desert-weather` adds a
condition too - so both go through :mod:`sage_patch.patches.model_conditions`, which reads the
live table out of the image instead of assuming the stock one. Applied after another such patch
this one lands on the next free bit rather than 591, which is why :meth:`verify` reads the bit
back out of the table instead of hardcoding it.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, EnumDelta

from ..asm import JE, JNE, JNZ, JZ, Asm
from ..patcher import Patch
from ..utils import apply_byte_patch, find_section, va_to_offset
from . import locomotor_sets, model_conditions, name_tables, weapon_set_flags

if TYPE_CHECKING:
    import argparse

__all__ = ["MASK_OFFSET", "NEW_BIT", "STOCK_BIT_COUNT", "ProductionConditionPatch"]

# The name table, its 16 references, the 10 count sites and the mask offset are shared with any
# other patch that names a condition, so they live in `model_conditions` and are re-exported here.

_NAME_TABLE_VA = model_conditions.NAME_TABLE_VA
_TABLE_REF_VAS = model_conditions.TABLE_REF_VAS
_COUNT_SITES = model_conditions.COUNT_SITES
_TABLE_FINGERPRINT = model_conditions.TABLE_FINGERPRINT

#: Named bits in the stock table. Also `getBitCount()`'s answer, and every loop bound below.
STOCK_BIT_COUNT = model_conditions.STOCK_BIT_COUNT

#: The bit this patch names on a stock binary: the first unnamed slot, and the last one `xfer`
#: already transmits. Applied on top of another condition-adding patch it is one higher, so this
#: is the default for :func:`build_hook_code`, not an invariant of the installed patch.
NEW_BIT = STOCK_BIT_COUNT

#: `Object`'s `ModelConditionFlags`. 19 dwords, so 0x10C..0x158 - it ends exactly where the second
#: `Matrix3D` copy documented in ``../docs/live-object-model.md`` begins.
MASK_OFFSET = model_conditions.MASK_OFFSET

#: `Object::onModelConditionFlagsChanged` - pushes the mask to the `Drawable` and notifies the
#: module at `Object+0x260`. Called with ecx = the `Object`. `ProductionUpdate::update` already
#: calls it three times, which is what makes it safe to call from the same frame position.
_PROPAGATE_VA = 0x0068B53C

#: `ProductionUpdate::update`, slot 0 of the `UpdateModule` vtable the module stores at +0x10.
#: Its 5-byte entry is an SEH-prolog `mov eax, imm32`, which is exactly a `jmp rel32`.
_UPDATE_VA = 0x008A1B9F
_UPDATE_ENTRY = bytes.fromhex("b88820ba00")  # mov eax, 0xba2088 - exactly 5 bytes
_UPDATE_VTABLE = 0x00C67E2C
_UPDATE_VTABLE_SLOT = 0x00

#: Offsets from `update`'s `this` (which is the module base + 0x10, the `UpdateModule` subobject).
#: `Object*` sits at module+0x08 and the production queue head at module+0x28; both are confirmed
#: three ways in the doc, including by the accessors at 0x008A072F and 0x008A0669.
_THIS_TO_OBJECT = -0x08  # [ecx - 0x08] -> Object*
_THIS_TO_QUEUE_HEAD = +0x18  # [ecx + 0x18] -> the first ProductionEntry, or NULL

_SECTION_NAME = ".prodmc"

DEFAULT_NAME = "PRODUCING"


@dataclass(frozen=True)
class _TailLayout:
    """Where each optional piece of the cave sits, past the model-condition table and its name.

    Every field but :attr:`code_va` is None when its option was not asked for, and the sizes are
    fixed by the names alone - so the same arithmetic recovers them in :meth:`verify`."""

    weapon_table_va: int | None
    locomotor_table_va: int | None
    mask_va: int | None
    code_va: int


def _table_block_size(entries: int, name: str) -> int:
    """The bytes a rebuilt table and its one new name occupy: the pointer array including its
    terminator, then the string, padded to keep whatever follows dword-aligned."""
    string = len(name) + 1
    return (entries + 1) * 4 + string + (-string % 4)


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _offset(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"VA 0x{va:08x} is not mapped")
    return off


def build_hook_code(
    base_va: int,
    bit: int = NEW_BIT,
    weapon: tuple[int, int] | None = None,
    locomotor: int | None = None,
) -> bytes:
    """The cave body. Entered from `ProductionUpdate::update`'s first instruction, and returns to
    the second; it runs *before* the function's SEH prologue, so it must leave the stack exactly
    as it found it and must not disturb `ecx` (the `this` the prologue's caller still needs).

    `eax`, `ecx` and `edx` are the only registers it may clobber: `ebx`/`esi`/`edi` are callee-
    saved and `update` has not pushed them yet, so corrupting them here would corrupt the
    *caller's* copies. `ecx` is preserved across the propagate call for that reason; `eax` is dead
    on entry and is reloaded by the displaced instruction on the way out. `eax` holds the `Object`
    for the whole body, so the optional blocks below save it around their calls rather than
    reloading it.

    The read-before-write is not an optimisation for its own sake: without it every producing
    building would push its mask to the `Drawable` on every logic frame. The engine's own two
    condition writes inside `update` test first for the same reason.

    ``weapon`` is ``(bit, VA of its 4-dword mask constant)`` and ``locomotor`` a set index; each is
    None when not installed, and with both None this emits exactly the bytes it emitted before
    either existed. Each optional block sits *before* the model-condition block on its path and
    guards on its own state, so the three are independent - see the module docstring for why that
    matters across a save/load."""
    word_offset = MASK_OFFSET + (bit // 32) * 4
    mask = 1 << (bit % 32)

    a = Asm(base_va)
    a.emit(0x51)  # push ecx                      ; `this`, needed by the prologue
    a.emit(0x8B, 0x41, struct.pack("<b", _THIS_TO_OBJECT))  # mov eax, [ecx-8]  ; Object *
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JZ, "done")  # no object: nothing to flag
    a.emit(0x83, 0x79, _THIS_TO_QUEUE_HEAD, 0x00)  # cmp dword [ecx+0x18], 0   ; queue head
    a.jcc(JZ, "clear")

    # Producing.
    _emit_weapon_block(a, weapon, producing=True)
    _emit_locomotor_block(a, locomotor, producing=True)
    # Set the bit, unless it is already set.
    a.emit(0xF7, 0x80, _u32(word_offset), _u32(mask))  # test dword [eax+off], mask
    a.jcc(JNZ, "done")
    a.emit(0x81, 0x88, _u32(word_offset), _u32(mask))  # or   dword [eax+off], mask
    a.jmp("propagate")

    # Idle.
    a.label("clear")
    _emit_weapon_block(a, weapon, producing=False)
    _emit_locomotor_block(a, locomotor, producing=False)
    # Clear the bit, unless it is already clear.
    a.emit(0xF7, 0x80, _u32(word_offset), _u32(mask))  # test dword [eax+off], mask
    a.jcc(JZ, "done")
    a.emit(0x81, 0xA0, _u32(word_offset), _u32(~mask & 0xFFFFFFFF))  # and dword [eax+off], ~mask

    a.label("propagate")
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.call_absolute(_PROPAGATE_VA)  # call Object::onModelConditionFlagsChanged

    a.label("done")
    a.emit(0x59)  # pop ecx
    a.emit(_UPDATE_ENTRY)  # the displaced instruction
    a.jmp_absolute(_UPDATE_VA + len(_UPDATE_ENTRY))
    return a.finish()


def _emit_weapon_block(a: Asm, weapon: tuple[int, int] | None, producing: bool) -> None:
    """Bring `Object+0x38C`'s copy of the flag into line with ``producing``, if one is installed.

    The guard is the flag's *own* bit rather than the model condition's, so the block is a no-op
    on every frame but the one that changes it - which matters, because the call it guards is
    `Object::setWeaponSetFlags`, and that re-runs `WeaponSet::updateWeaponSet` and rebuilds the
    object's `Weapon`s. Both helpers are `thiscall` taking a whole mask and cleaning their own
    argument (``ret 4``)."""
    if weapon is None:
        return
    flag_bit, mask_va = weapon
    word_offset = weapon_set_flags.MASK_OFFSET + (flag_bit // 32) * 4
    mask = 1 << (flag_bit % 32)
    label = f"weapon_{'set' if producing else 'clear'}_done"

    a.emit(0xF7, 0x80, _u32(word_offset), _u32(mask))  # test dword [eax+off], mask
    a.jcc(JNZ if producing else JZ, label)  # already agrees: nothing to do
    a.emit(0x50)  # push eax                    ; the call clobbers it
    a.emit(0x68, _u32(mask_va))  # push <mask>  ; the 4-dword constant in this cave
    a.emit(0x8B, 0xC8)  # mov ecx, eax          ; the Object
    a.call_absolute(weapon_set_flags.SET_FLAGS_VA if producing else weapon_set_flags.CLEAR_FLAGS_VA)
    a.emit(0x58)  # pop eax
    a.label(label)


def _emit_locomotor_block(a: Asm, locomotor: int | None, producing: bool) -> None:
    """Ask the AI for the new set while producing, and put `SET_NORMAL` back afterwards.

    Three guards, in order: no AI module at all (most structures), the set already being what we
    want, and - on the way out only - the current set no longer being ours, which means something
    else has chosen since and reverting would stomp it. `chooseLocomotorSet` itself refuses when
    the template declares no locomotor for the set, so an object whose INI never mentions it is
    untouched by the call this makes every frame."""
    if locomotor is None:
        return
    want = locomotor if producing else locomotor_sets.NORMAL_SET
    label = f"locomotor_{'set' if producing else 'clear'}_done"

    a.emit(0x8B, 0x88, _u32(locomotor_sets.AI_MODULE_OFFSET))  # mov ecx, [eax+0x260]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JZ, label)  # no AI: no locomotor to choose
    a.emit(0x81, 0xB9, _u32(locomotor_sets.CURRENT_SET_OFFSET), _u32(locomotor))  # cmp [ecx+..], n
    a.jcc(JE if producing else JNE, label)
    a.emit(0x50)  # push eax
    a.emit(0x68, _u32(want))  # push <set>
    a.emit(0x8B, 0x11)  # mov edx, [ecx]        ; the AI module's vtable
    a.emit(0xFF, 0x92, _u32(locomotor_sets.CHOOSE_SET_SLOT))  # call [edx+0x238]
    a.emit(0x58)  # pop eax
    a.label(label)


class ProductionConditionPatch(Patch):
    """Name the first unused `ModelConditionFlags` bit and drive it from the production queue."""

    name = "production-condition"
    author = "officialNecro"
    description = (
        "Add a model condition that is active while a building's production queue is non-empty "
        "(training a unit or researching an upgrade)"
    )

    def __init__(
        self,
        condition: str = DEFAULT_NAME,
        weapon_set_flag: str | None = None,
        locomotor_set: str | None = None,
    ):
        self.condition = condition
        self.weapon_set_flag = weapon_set_flag
        self.locomotor_set = locomotor_set
        self._validate()

    def __str__(self) -> str:
        extras = "".join(
            f", {label} {name}"
            for label, name in (
                ("weapon set flag", self.weapon_set_flag),
                ("locomotor set", self.locomotor_set),
            )
            if name is not None
        )
        return f"{self.name} ({self.condition}{extras})"

    def _validate(self) -> None:
        model_conditions.validate_name(self.condition)
        if self.weapon_set_flag is not None:
            name_tables.validate_name(self.weapon_set_flag, "weapon set flag name")
        if self.locomotor_set is not None:
            name_tables.validate_name(self.locomotor_set, "locomotor set name")

    def apply(self, data: bytearray) -> None:
        """Install the cave and repoint every table it rebuilt.

        The two optional tables are read and cleared *before* :func:`model_conditions.extend`
        writes anything, so a name that is already taken stops the patch with the image
        untouched rather than half-applied."""
        self._check_dispatch(data)
        weapon_table = locomotor_table = None
        if self.weapon_set_flag is not None:
            weapon_table = weapon_set_flags.read(data)
            weapon_set_flags.check_free(weapon_table, data, [self.weapon_set_flag])
        if self.locomotor_set is not None:
            locomotor_table = locomotor_sets.read(data)
            locomotor_sets.check_free(locomotor_table, data, [self.locomotor_set])

        extension = model_conditions.extend(
            data,
            _SECTION_NAME,
            [self.condition],
            lambda tail_va, bits: self._tail(tail_va, bits[0], weapon_table, locomotor_table),
        )
        pieces = self._tail_pieces(
            extension.tail_va,
            None if weapon_table is None else weapon_table.count + 1,
            None if locomotor_table is None else locomotor_table.count + 1,
        )

        edits: list[tuple[int, bytes, bytes, str]] = []
        if weapon_table is not None:
            assert pieces.weapon_table_va is not None
            edits += weapon_set_flags.relocation_edits(data, weapon_table, pieces.weapon_table_va)
        if locomotor_table is not None:
            assert pieces.locomotor_table_va is not None
            edits += locomotor_sets.relocation_edits(
                data, locomotor_table, pieces.locomotor_table_va
            )
        edits.append(
            (
                _offset(data, _UPDATE_VA),
                _UPDATE_ENTRY,
                b"\xe9" + struct.pack("<i", pieces.code_va - (_UPDATE_VA + 5)),
                "ProductionUpdate::update -> production-condition cave",
            )
        )
        for file_off, old, new, note in edits:
            apply_byte_patch(data, file_off, old, new, note)

    def _tail(
        self,
        tail_va: int,
        condition_bit: int,
        weapon_table: name_tables.NameTable | None,
        locomotor_table: name_tables.NameTable | None,
    ) -> bytes:
        """Everything this patch puts in the cave after the model-condition table and its name:
        the two optional tables with their new names, the weapon-set mask constant, and the hook
        code. The layout is a pure function of ``tail_va`` and the two entry counts, which is what
        lets :meth:`verify` recover every address from the cave itself."""
        pieces = self._tail_pieces(
            tail_va,
            None if weapon_table is None else weapon_table.count + 1,
            None if locomotor_table is None else locomotor_table.count + 1,
        )
        blob = b""
        weapon = locomotor = None
        if weapon_table is not None:
            assert self.weapon_set_flag is not None
            assert pieces.weapon_table_va is not None and pieces.mask_va is not None
            content, _vas, _end = name_tables.layout(
                weapon_table.pointers, [self.weapon_set_flag], pieces.weapon_table_va
            )
            blob += content
            weapon = (weapon_table.count, pieces.mask_va)
        if locomotor_table is not None:
            assert self.locomotor_set is not None
            assert pieces.locomotor_table_va is not None
            content, _vas, _end = name_tables.layout(
                locomotor_table.pointers, [self.locomotor_set], pieces.locomotor_table_va
            )
            blob += content
            locomotor = locomotor_table.count
        if weapon_table is not None:
            blob += weapon_set_flags.mask_bytes(weapon_table.count)
        assert tail_va + len(blob) == pieces.code_va, "the tail layout and its addresses disagree"
        return blob + build_hook_code(pieces.code_va, condition_bit, weapon, locomotor)

    def _tail_pieces(
        self, tail_va: int, weapon_entries: int | None, locomotor_entries: int | None
    ) -> _TailLayout:
        """Where each piece of the tail sits, given how many entries each rebuilt table holds
        (the stock count plus this patch's own name). Pure arithmetic, so :meth:`apply` and
        :meth:`verify` compute the same addresses from opposite directions."""
        va = tail_va
        weapon_table_va = locomotor_table_va = mask_va = None
        if weapon_entries is not None:
            assert self.weapon_set_flag is not None
            weapon_table_va = va
            va += _table_block_size(weapon_entries, self.weapon_set_flag)
        if locomotor_entries is not None:
            assert self.locomotor_set is not None
            locomotor_table_va = va
            va += _table_block_size(locomotor_entries, self.locomotor_set)
        if weapon_entries is not None:
            mask_va = va
            va += weapon_set_flags.MASK_DWORDS * 4
        return _TailLayout(weapon_table_va, locomotor_table_va, mask_va, va)

    def ini_surface(self) -> Engine:
        """The tokens this patch teaches the INI parser: the model condition, plus the weapon-set
        flag and locomotor set when those extras were installed. Each maps to the model enum that
        types the fields it can appear in - a `ModelConditionState` label, a `WeaponSet`
        `Conditions` token, a `Locomotor = SET_X` selector.

        No indices are stated: which bit a name landed on depends on what else the binary already
        carries, so the generator reads them back from the live tables instead."""
        return Engine(
            enum_members=tuple(
                EnumDelta(enum=enum, name=token, patch=self.name)
                for enum, token in (
                    ("ModelCondition", self.condition),
                    ("WeaponSetConditions", self.weapon_set_flag),
                    ("LocomotorSetType", self.locomotor_set),
                )
                if token is not None
            )
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch for exactly this condition name.
        Reads only via ``struct`` and the section table, so it needs no disassembler.

        The bit is read back out of the live name table rather than assumed to be 591, because a
        second condition-adding patch shifts it - and the hook body encodes the bit it was built
        for, so the two have to be checked against each other rather than against a constant. The
        two optional tables are read back out of **the cave's own copy** rather than out of the
        live image, for the same reason: a later patch that appends to either table becomes the
        live one, and this patch is still correctly installed."""
        located = find_section(data, _SECTION_NAME)
        if located is None:
            return [f"no {_SECTION_NAME} section: the file does not carry this patch"]
        section_va, _section_off, vsize = located

        try:
            table = model_conditions.read(data)
        except (ValueError, struct.error) as exc:
            return [f"cannot read the model-condition name table (wrong build?): {exc}"]

        problems: list[str] = []
        bit = table.index_of(data, self.condition)
        if bit is None:
            problems.append(
                f"{self.condition!r} is not in the model-condition name table at "
                f"0x{table.base_va:08x}"
            )

        try:
            pieces, weapon, locomotor = self._read_cave(data, section_va, problems)
        except (ValueError, struct.error) as exc:
            return [*problems, f"cannot read back the {_SECTION_NAME} cave: {exc}"]

        off = _offset(data, _UPDATE_VA)
        if data[off] != 0xE9:
            problems.append(
                f"ProductionUpdate::update @0x{_UPDATE_VA:08x} does not start with a jmp: "
                f"{bytes(data[off : off + 5]).hex()}"
            )
            return problems
        code_va = _UPDATE_VA + 5 + struct.unpack_from("<i", data, off + 1)[0]
        if not section_va <= code_va < section_va + vsize:
            problems.append(
                f"ProductionUpdate::update jumps to 0x{code_va:08x}, outside {_SECTION_NAME}"
            )
        elif code_va != pieces.code_va:
            problems.append(
                f"ProductionUpdate::update jumps to 0x{code_va:08x}, but the cave's layout puts "
                f"the hook body at 0x{pieces.code_va:08x}"
            )
        elif bit is not None:
            want = build_hook_code(code_va, bit, weapon, locomotor)
            code_off = _offset(data, code_va)
            got = bytes(data[code_off : code_off + len(want)])
            if got != want:
                problems.append(
                    f"the hook body in {_SECTION_NAME} is not the cave for "
                    f"{self.condition!r} = bit {bit}"
                )
        return problems

    def _read_cave(
        self, data: bytes | bytearray, section_va: int, problems: list[str]
    ) -> tuple[_TailLayout, tuple[int, int] | None, int | None]:
        """Recover the cave's layout and the two optional arguments the hook body was built with.

        The section starts with the model-condition table this patch wrote, so its terminator says
        where the tail begins; each optional table then follows in turn, and its own terminator
        says how many entries it holds. Every check that can fail without stopping the read
        appends to ``problems`` rather than raising."""
        pointers = name_tables.read_terminated(
            data, section_va, f"the model-condition table in {_SECTION_NAME}"
        )
        tail_va = section_va + _table_block_size(len(pointers), self.condition)

        va = tail_va
        weapon_entries = locomotor_entries = None
        weapon = locomotor = None
        if self.weapon_set_flag is not None:
            names = self._read_table(data, va, self.weapon_set_flag, "weapon set flag", problems)
            weapon_entries = len(names)
            va += _table_block_size(weapon_entries, self.weapon_set_flag)
        if self.locomotor_set is not None:
            names = self._read_table(data, va, self.locomotor_set, "locomotor set", problems)
            locomotor_entries = len(names)
            locomotor = locomotor_entries - 1

        pieces = self._tail_pieces(tail_va, weapon_entries, locomotor_entries)
        if weapon_entries is not None:
            assert pieces.mask_va is not None
            flag_bit = weapon_entries - 1
            weapon = (flag_bit, pieces.mask_va)
            want_mask = weapon_set_flags.mask_bytes(flag_bit)
            mask_off = _offset(data, pieces.mask_va)
            if bytes(data[mask_off : mask_off + len(want_mask)]) != want_mask:
                problems.append(
                    f"the weapon-set mask constant at 0x{pieces.mask_va:08x} is not the "
                    f"{weapon_set_flags.MASK_DWORDS}-dword mask for flag {flag_bit}"
                )
        for table_va, ref_vas, what in (
            (pieces.weapon_table_va, weapon_set_flags.TABLE_REF_VAS, "weapon-set-flag"),
            (pieces.locomotor_table_va, locomotor_sets.TABLE_REF_VAS, "locomotor-set"),
        ):
            if table_va is None:
                continue
            for ref_va in ref_vas:
                got = struct.unpack_from("<I", data, _offset(data, ref_va))[0]
                if got != table_va:
                    problems.append(
                        f"{what} name table ref @0x{ref_va:08x} points at 0x{got:08x}, not the "
                        f"table this patch built at 0x{table_va:08x}"
                    )
        return pieces, weapon, locomotor

    @staticmethod
    def _read_table(
        data: bytes | bytearray, base_va: int, name: str, what: str, problems: list[str]
    ) -> tuple[int, ...]:
        """The pointers of one rebuilt table in the cave, checking its last entry is ``name``."""
        pointers = name_tables.read_terminated(
            data, base_va, f"the {what} table in {_SECTION_NAME}"
        )
        got = name_tables.read_cstring(data, pointers[-1]) if pointers else None
        if got != name:
            problems.append(
                f"the last entry of the {what} table at 0x{base_va:08x} is {got!r}, not {name!r}"
            )
        return pointers

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--condition",
            default=DEFAULT_NAME,
            metavar="NAME",
            help=(
                f"name of the model condition to add (default {DEFAULT_NAME}); uppercase letters, "
                "digits and underscores, and must not already be a model condition"
            ),
        )
        parser.add_argument(
            "--weapon-set-flag",
            metavar="NAME",
            help=(
                "also add a WeaponSetFlag of this name, set while the queue is non-empty, so a "
                "`WeaponSet Conditions = NAME` block can give a producer a different loadout "
                "(off unless given)"
            ),
        )
        parser.add_argument(
            "--locomotor-set",
            metavar="NAME",
            help=(
                "also add a LocomotorSetType of this name, chosen while the queue is non-empty, "
                "so `Locomotor = NAME <template>` can give a producer a different locomotor; "
                "objects that declare none for it are unaffected (off unless given)"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> ProductionConditionPatch:
        return cls(
            condition=args.condition,
            weapon_set_flag=args.weapon_set_flag,
            locomotor_set=args.locomotor_set,
        )

    @staticmethod
    def _check_dispatch(data: bytes | bytearray) -> None:
        """Raise unless the `UpdateModule` vtable still names the function being hooked. `update`
        is virtual, so it has no `call rel32` xrefs: a hook installed on the wrong function would
        verify clean and simply never fire."""
        slot_va = _UPDATE_VTABLE + _UPDATE_VTABLE_SLOT
        slot_off = va_to_offset(data, slot_va)
        if slot_off is None:
            raise ValueError("the ProductionUpdate vtable is not mapped - not the expected build")
        target = struct.unpack_from("<I", data, slot_off)[0]
        if target != _UPDATE_VA:
            raise ValueError(
                f"vtable slot {slot_va:#010x} dispatches to {target:#010x}, not "
                f"{_UPDATE_VA:#010x} - the function being hooked is not ProductionUpdate::update"
            )
