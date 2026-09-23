"""Add a model condition (`PRODUCING` by default) that is set while a building's production queue is
non-empty.

The engine has none: the `DOOR_n_*` conditions only cover a finished unit walking out. The patch
appends the name to the `ModelConditionFlags` table, so it parses wherever a model condition does,
and hooks `ProductionUpdate::update` to keep the bit equal to "queue non-empty". Optionally the same
state drives a weapon-set flag and a locomotor set. `ProductionConditionWorldbuilderPatch` teaches
the editor the token. A save taken while anything is producing will not load on a stock binary.

Derivation: `../docs/production-model-condition.md`.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, EnumDelta

from ..asm import JE, JNE, JNZ, JZ, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, file_offset, find_section, u32, va_to_offset
from .utils import locomotor_sets, model_conditions, name_tables, weapon_set_flags

if TYPE_CHECKING:
    import argparse

__all__ = [
    "MASK_OFFSET",
    "NEW_BIT",
    "STOCK_BIT_COUNT",
    "ProductionConditionPatch",
    "ProductionConditionWorldbuilderPatch",
]

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
#: is the default for `build_hook_code`, not an invariant of the installed patch.
NEW_BIT = STOCK_BIT_COUNT

#: `Object`'s `ModelConditionFlags`. 19 dwords, so 0x10C..0x158 - it ends exactly where the second
#: `Matrix3D` copy documented in `../docs/live-object-model.md` begins.
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

    Every field but `code_va` is None when its option was not asked for, and the sizes are
    fixed by the names alone - so the same arithmetic recovers them in `verify`."""

    weapon_table_va: int | None
    locomotor_table_va: int | None
    mask_va: int | None
    code_va: int


def _table_block_size(entries: int, name: str) -> int:
    """The bytes a rebuilt table and its one new name occupy: the pointer array including its
    terminator, then the string, padded to keep whatever follows dword-aligned."""
    string = len(name) + 1
    return (entries + 1) * 4 + string + (-string % 4)


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

    `weapon` is `(bit, VA of its 4-dword mask constant)` and `locomotor` a set index; each is
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
    a.emit(0xF7, 0x80, u32(word_offset), u32(mask))  # test dword [eax+off], mask
    a.jcc(JNZ, "done")
    a.emit(0x81, 0x88, u32(word_offset), u32(mask))  # or   dword [eax+off], mask
    a.jmp("propagate")

    # Idle.
    a.label("clear")
    _emit_weapon_block(a, weapon, producing=False)
    _emit_locomotor_block(a, locomotor, producing=False)
    # Clear the bit, unless it is already clear.
    a.emit(0xF7, 0x80, u32(word_offset), u32(mask))  # test dword [eax+off], mask
    a.jcc(JZ, "done")
    a.emit(0x81, 0xA0, u32(word_offset), u32(~mask & 0xFFFFFFFF))  # and dword [eax+off], ~mask

    a.label("propagate")
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.call_absolute(_PROPAGATE_VA)  # call Object::onModelConditionFlagsChanged

    a.label("done")
    a.emit(0x59)  # pop ecx
    a.emit(_UPDATE_ENTRY)  # the displaced instruction
    a.jmp_absolute(_UPDATE_VA + len(_UPDATE_ENTRY))
    return a.finish()


def _emit_weapon_block(a: Asm, weapon: tuple[int, int] | None, producing: bool) -> None:
    """Bring `Object+0x38C`'s copy of the flag into line with `producing`, if one is installed.

    The guard is the flag's *own* bit rather than the model condition's, so the block is a no-op
    on every frame but the one that changes it - which matters, because the call it guards is
    `Object::setWeaponSetFlags`, and that re-runs `WeaponSet::updateWeaponSet` and rebuilds the
    object's `Weapon`s. Both helpers are `thiscall` taking a whole mask and cleaning their own
    argument (`ret 4`)."""
    if weapon is None:
        return
    flag_bit, mask_va = weapon
    word_offset = weapon_set_flags.MASK_OFFSET + (flag_bit // 32) * 4
    mask = 1 << (flag_bit % 32)
    label = f"weapon_{'set' if producing else 'clear'}_done"

    a.emit(0xF7, 0x80, u32(word_offset), u32(mask))  # test dword [eax+off], mask
    a.jcc(JNZ if producing else JZ, label)  # already agrees: nothing to do
    a.emit(0x50)  # push eax                    ; the call clobbers it
    a.emit(0x68, u32(mask_va))  # push <mask>  ; the 4-dword constant in this cave
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

    a.emit(0x8B, 0x88, u32(locomotor_sets.AI_MODULE_OFFSET))  # mov ecx, [eax+0x260]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JZ, label)  # no AI: no locomotor to choose
    a.emit(0x81, 0xB9, u32(locomotor_sets.CURRENT_SET_OFFSET), u32(locomotor))  # cmp [ecx+..], n
    a.jcc(JE if producing else JNE, label)
    a.emit(0x50)  # push eax
    a.emit(0x68, u32(want))  # push <set>
    a.emit(0x8B, 0x11)  # mov edx, [ecx]        ; the AI module's vtable
    a.emit(0xFF, 0x92, u32(locomotor_sets.CHOOSE_SET_SLOT))  # call [edx+0x238]
    a.emit(0x58)  # pop eax
    a.label(label)


class ProductionConditionPatch(Patch):
    """Name the first unused `ModelConditionFlags` bit and drive it from the production queue."""

    name = "production-condition"
    author = "officialNecro"
    description = (
        "Add a model condition that is active while a building's production queue is non-empty "
        "(training a unit or researching an upgrade). The new PRODUCING token (--condition) "
        "parses anywhere a model condition does - ModelConditionState, DisableOnModelCondition, "
        "HideSubObject; --weapon-set-flag NAME and --locomotor-set NAME add a WeaponSetFlag and "
        "a LocomotorSetType off the same trigger, for WeaponSet Conditions = NAME and Locomotor "
        "= NAME <template>"
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

        The two optional tables are read and cleared *before* `model_conditions.extend`
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
                file_offset(data, _UPDATE_VA),
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
        code. The layout is a pure function of `tail_va` and the two entry counts, which is what
        lets `verify` recover every address from the cave itself."""
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
        (the stock count plus this patch's own name). Pure arithmetic, so `apply` and
        `verify` compute the same addresses from opposite directions."""
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
        """Structural check that `data` carries this patch for exactly this condition name.
        Reads only via `struct` and the section table, so it needs no disassembler.

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

        off = file_offset(data, _UPDATE_VA)
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
            code_off = file_offset(data, code_va)
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
        appends to `problems` rather than raising."""
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
            mask_off = file_offset(data, pieces.mask_va)
            if bytes(data[mask_off : mask_off + len(want_mask)]) != want_mask:
                problems.append(
                    f"the weapon-set mask constant at 0x{pieces.mask_va:08x} is not the "
                    f"{weapon_set_flags.MASK_DWORDS}-dword mask for flag {flag_bit}"
                )
        for table_va, ref_vas, what in (
            (pieces.weapon_table_va, weapon_set_flags.TABLE_REF_VAS, "weapon-set-flag"),
            # Asked of the image rather than taken as a constant: one locomotor-set reference is a
            # field descriptor another patch can have moved into a cave of its own.
            (pieces.locomotor_table_va, locomotor_sets.ref_vas(data), "locomotor-set"),
        ):
            if table_va is None:
                continue
            for ref_va in ref_vas:
                got = struct.unpack_from("<I", data, file_offset(data, ref_va))[0]
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
        """The pointers of one rebuilt table in the cave, checking its last entry is `name`."""
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
    def detect(cls, data: bytes | bytearray) -> ProductionConditionPatch | None:
        """Recognise this patch **and recover all three of its settings**.

        The default probe only ever recognises `PRODUCING` with neither optional table, so a
        binary carrying any other condition name - or either extra name at all - reads as
        unpatched. Each setting is recoverable from the image's own evidence rather than guessed:
        the cave opens with the model-condition table this patch wrote, whose last entry is the
        condition, and each optional table was *relocated* into the cave, so whether the live
        weapon-set-flag and locomotor-set tables point inside this section is exactly whether that
        option was used - and if it was, that table's last entry is its name."""
        located = find_section(data, _SECTION_NAME)
        if located is None:
            return None
        section_va, _section_off, vsize = located
        try:
            pointers = name_tables.read_terminated(
                data, section_va, f"the model-condition table in {_SECTION_NAME}"
            )
            condition = name_tables.read_cstring(data, pointers[-1]) if pointers else None
            if condition is None:
                return None

            extras: list[str | None] = []
            for ref_vas in (weapon_set_flags.TABLE_REF_VAS, locomotor_sets.TABLE_REF_VAS):
                table_va = struct.unpack_from("<I", data, file_offset(data, ref_vas[0]))[0]
                if not section_va <= table_va < section_va + vsize:
                    extras.append(None)  # still the stock table: this patch did not rebuild it
                    continue
                entries = name_tables.read_terminated(data, table_va, _SECTION_NAME)
                name = name_tables.read_cstring(data, entries[-1]) if entries else None
                if name is None:
                    return None
                extras.append(name)

            patch = cls(condition, weapon_set_flag=extras[0], locomotor_set=extras[1])
        except (ValueError, IndexError, struct.error):
            return None
        return None if patch.verify(data) else patch

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


# The Worldbuilder half.
#
# The editor parses the same object INI, so `ModelConditionState = PRODUCING`,
# `WeaponSet Conditions = PLAYER_PRODUCING` and `Locomotor = SET_PRODUCING <template>` all reach
# Worldbuilder's **own** copies of the three name tables. A name none of them holds is an unknown
# token in a mask parse, which throws, and a throw during INI load ends the editor's startup.
#
# The three tables differ in whether a count has to move with them, exactly as they do in
# `game.dat`, and for the same reason - it is the same source read twice:
#
# * `ModelConditionFlags` bakes its count into loop bounds, **nine** of them here. Three are the
#   mask parser's own forms, and they hard-bound the lookup's result the way the kindof parser
#   does, so the name would be found and then rejected by the compare if the bounds did not move:
#
#       00956867  call 0x006CD120           ; name -> index
#       00956872  cmp  dword [ebp-8], 0x24f ; 591
#       00956879  jb   0x009568D6           ; index >= 591 falls into the error path
#
#   The other six are enumeration loops that index the table immediately after the compare.
# * `WeaponSetFlags` and `LocomotorSetType` are read **only through their terminator** and bake no
#   count at all - the same finding `weapon_set_flags` and `locomotor_sets` record for
#   the game binary - so those two need their references repointed and nothing else.
#
# All three rebuilt tables share one cave, laid out end to end, because they are added or not added
# together and one section is easier to find than three.
#
# Scope: parsing only. The editor gets no production trigger and needs none - it does not simulate
# a queue. What it gets is the ability to read templates that mention these names.

#: Worldbuilder's own copies of the three tables.
WORLDBUILDER_CONDITION_TABLE_VA = 0x02231078
WORLDBUILDER_WEAPON_SET_TABLE_VA = 0x0222FE20
WORLDBUILDER_LOCOMOTOR_TABLE_VA = 0x02233CA8

#: Every reference to the model-condition table: 27 bare imm32/disp32 operands. `0x0095685C`,
#: `0x00956947` and `0x00956A3E` are the mask parser's three forms (`+NAME`, `-NAME`, bare `NAME`).
WORLDBUILDER_CONDITION_REF_VAS = (
    0x005DFD3C,
    0x0094C871,
    0x0094E5DC,
    0x0095257A,
    0x00955D33,
    0x0095685C,
    0x00956947,
    0x00956A3E,
    0x0096AC65,
    0x0097776D,
    0x009777A7,
    0x009777D1,
    0x00C04E27,
    0x00C0746C,
    0x00FF3FFA,
    0x0101A46E,
    0x0101A5A3,
    0x01024E4A,
    0x010B3407,
    0x010ED939,
    0x010EDAD3,
    0x011695D3,
    0x011C229A,
    0x011C236F,
    0x011FA0A3,
    0x01240172,
    0x01253493,
)

#: Every site encoding the model-condition count, as ``(instruction VA, the bytes before its
#: imm32)``. The prefix is asserted as well as the immediate: 591 is not a rare constant in this
#: image, and proximity alone matches hundreds of unrelated compares. Each of these was confirmed
#: by disassembly to either index the table in the instruction after the compare, or to be one of
#: the mask parser's three bounds-check-then-report sites.
WORLDBUILDER_CONDITION_COUNT_SITES = (
    (0x005DFD2D, bytes.fromhex("817df0")),  # enumeration loop, indexes the table
    (0x0095256B, bytes.fromhex("817dfc")),  # bound then terminator test on the table
    (0x00956872, bytes.fromhex("817df8")),  # mask parser, `+NAME`
    (0x0095695D, bytes.fromhex("817df4")),  # mask parser, `-NAME`
    (0x00956A51, bytes.fromhex("817df0")),  # mask parser, bare `NAME`
    (0x00956BD3, bytes.fromhex("817da4")),  # outer guard on the same local as the next
    (0x00956BE0, bytes.fromhex("817da4")),  # inner bound before the report
    (0x0101A45F, bytes.fromhex("817de0")),  # enumeration loop, indexes the table
    (0x0101A594, bytes.fromhex("817de0")),  # enumeration loop, indexes the table
)

#: The weapon-set and locomotor tables carry no count anywhere, so these are references only.
WORLDBUILDER_WEAPON_SET_REF_VAS = (
    0x00BC5AB9,
    0x00BC5AF3,
    0x00BC618C,
    0x00BC6274,
    0x00BC6368,
    0x00BC64E7,
    0x011C22B8,
)
WORLDBUILDER_LOCOMOTOR_REF_VAS = (
    0x00AF3F34,
    0x00E3AE84,
    0x011C2314,
    0x01203F65,
    0x01ED03F0,
    0x01EEB2B8,
    0x01EEB2C8,
    0x01F1FEA8,
)

#: Names at these indices fingerprint the build far more tightly than the counts alone.
WORLDBUILDER_CONDITION_FINGERPRINT = {0: "TOPPLED", 1: "FRONTCRUSHED", 590: "SPECIAL_WEAPON_SIX"}
WORLDBUILDER_WEAPON_SET_FINGERPRINT = {
    0: "VETERAN",
    1: "ELITE",
    103: "WEAPONSET_CREATE_A_HERO_WS_64",
}
WORLDBUILDER_LOCOMOTOR_FINGERPRINT = {0: "SET_NORMAL", 16: "SET_BURNINGDEATH"}

#: The PE section name field is 8 bytes and truncates silently.
WORLDBUILDER_SECTION_NAME = ".wbprodc"

# CNT_INITIALIZED_DATA | MEM_READ - three pointer tables and their new strings, and no code.
_WORLDBUILDER_CHARACTERISTICS = 0x40000040

_WORLDBUILDER_STOCK_CONDITION_COUNT = 591


class ProductionConditionWorldbuilderPatch(Patch):
    """Teach **Worldbuilder** the production condition, weapon-set flag and locomotor set names.

    **This patch targets `Worldbuilder.exe`, not `game.dat`.** It is the authoring half of
    `production-condition`; pass it the same names, since the index is what the parsed data stores.
    Names not given to the game half should not be given here either - an editor that accepts a
    token the game rejects is a worse failure than one that rejects it too.
    """

    name = "production-condition-wb"
    author = "officialNecro"
    description = (
        "Worldbuilder.exe (not game.dat): add the PRODUCING model condition (--condition) and "
        "optionally a WeaponSetFlag (--weapon-set-flag) and LocomotorSetType (--locomotor-set) to "
        "the editor's own name tables, so templates using them parse instead of throwing and "
        "ending the editor's load. Pass the same names given to game.dat's production-condition; "
        "the editor gains no production trigger, only the ability to read the templates"
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
        for label, value in (
            ("model condition name", self.condition),
            ("weapon set flag name", self.weapon_set_flag),
            ("locomotor set name", self.locomotor_set),
        ):
            if value is not None:
                name_tables.validate_name(value, label)

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

    def _plan(self) -> list[tuple[str, tuple[int, ...], str]]:
        """`(what, reference VAs, the single name to append)` for each table in play."""
        plan: list[tuple[str, tuple[int, ...], str]] = [
            ("model condition", WORLDBUILDER_CONDITION_REF_VAS, self.condition)
        ]
        if self.weapon_set_flag is not None:
            plan.append(("weapon set flag", WORLDBUILDER_WEAPON_SET_REF_VAS, self.weapon_set_flag))
        if self.locomotor_set is not None:
            plan.append(("locomotor set", WORLDBUILDER_LOCOMOTOR_REF_VAS, self.locomotor_set))
        return plan

    def apply(self, data: bytearray) -> None:
        name_tables.check_not_rebased(data)
        tables = self._read(data)
        for (what, _refs, new_name), table in zip(self._plan(), tables, strict=True):
            if table.index_of(data, new_name) is not None:
                raise ValueError(f"{new_name!r} is already a {what} in this Worldbuilder")

        section_va = allocate_section(
            data,
            WORLDBUILDER_SECTION_NAME,
            lambda base_va: self._cave(tables, base_va),
            _WORLDBUILDER_CHARACTERISTICS,
        )
        for file_off, old, new, note in self._edits(data, tables, section_va):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, WORLDBUILDER_SECTION_NAME)
        if located is None:
            return [f"no {WORLDBUILDER_SECTION_NAME} section: the file does not carry this patch"]
        section_va, _section_off, _vsize = located

        problems: list[str] = []
        base = section_va
        try:
            for (what, refs, new_name), _ in zip(self._plan(), self._plan(), strict=True):
                names = self._read_names(data, base)
                if names[-1] != new_name:
                    problems.append(
                        f"the rebuilt {what} table ends {names[-1]!r}, expected {new_name!r}"
                    )
                for va in refs:
                    held = struct.unpack_from("<I", data, _wbc_offset(data, va))[0]
                    if held != base:
                        problems.append(
                            f"{what} table ref @0x{va:08x} holds 0x{held:08x}, "
                            f"expected 0x{base:08x}"
                        )
                base = self._table_end(base, len(names), new_name)
        except (ValueError, struct.error) as exc:
            return [f"cannot read back the {WORLDBUILDER_SECTION_NAME} cave (wrong build?): {exc}"]

        raised = _WORLDBUILDER_STOCK_CONDITION_COUNT + 1
        for va, prefix in WORLDBUILDER_CONDITION_COUNT_SITES:
            off = _wbc_offset(data, va)
            got = bytes(data[off : off + len(prefix) + 4])
            want = prefix + struct.pack("<I", raised)
            if got != want:
                problems.append(
                    f"model condition count bound @0x{va:08x} is {got.hex()}, expected {want.hex()}"
                )
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> Patch | None:
        """Recognise this patch. The cave holds one to three rebuilt tables laid end to end, and
        which of the optional two are present is recovered from how many the references point at."""
        located = find_section(data, WORLDBUILDER_SECTION_NAME)
        if located is None:
            return None
        section_va = located[0]
        try:
            condition = cls._read_names(data, section_va)[-1]
            weapon = cls._appended_name(data, WORLDBUILDER_WEAPON_SET_REF_VAS, section_va)
            locomotor = cls._appended_name(data, WORLDBUILDER_LOCOMOTOR_REF_VAS, section_va)
            patch = cls(condition=condition, weapon_set_flag=weapon, locomotor_set=locomotor)
        except (ValueError, IndexError, struct.error):
            return None
        return None if patch.verify(data) else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--condition",
            default=DEFAULT_NAME,
            metavar="NAME",
            help=f"model condition name to add (default {DEFAULT_NAME}); must match the one given "
            "to game.dat's production-condition",
        )
        parser.add_argument(
            "--weapon-set-flag",
            default=None,
            metavar="NAME",
            help="WeaponSetFlag name to add; pass it only if the game half was given it too",
        )
        parser.add_argument(
            "--locomotor-set",
            default=None,
            metavar="NAME",
            help="LocomotorSetType name to add; pass it only if the game half was given it too",
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> Patch:
        return cls(
            condition=args.condition,
            weapon_set_flag=args.weapon_set_flag,
            locomotor_set=args.locomotor_set,
        )

    @staticmethod
    def _table_end(base_va: int, count: int, new_name: str) -> int:
        """Where the table that starts at `base_va` and holds `count` names ends."""
        size = (count + 1) * 4
        strings = len(new_name.encode("ascii")) + 1
        return base_va + size + strings + (-strings % 4)

    def _cave(self, tables: list[name_tables.NameTable], base_va: int) -> bytes:
        """The rebuilt tables, laid out end to end in one section."""
        blob = b""
        cursor = base_va
        for (_what, _refs, new_name), table in zip(self._plan(), tables, strict=True):
            content, _name_vas, end = name_tables.layout(table.pointers, [new_name], cursor)
            blob += content
            cursor = end
        return blob

    def _read(self, data: bytes | bytearray) -> list[name_tables.NameTable]:
        """Each table in play, read live from its references rather than from the stock base."""
        specs = [
            (WORLDBUILDER_CONDITION_REF_VAS, WORLDBUILDER_CONDITION_FINGERPRINT, "model condition"),
            (
                WORLDBUILDER_WEAPON_SET_REF_VAS,
                WORLDBUILDER_WEAPON_SET_FINGERPRINT,
                "weapon set flag",
            ),
            (WORLDBUILDER_LOCOMOTOR_REF_VAS, WORLDBUILDER_LOCOMOTOR_FINGERPRINT, "locomotor set"),
        ]
        wanted = {refs for _what, refs, _name in self._plan()}
        out: list[name_tables.NameTable] = []
        for refs, fingerprint, what in specs:
            if refs not in wanted:
                continue
            base_va = name_tables.resolve_base(data, refs, f"Worldbuilder {what} table")
            pointers = name_tables.read_terminated(
                data, base_va, f"Worldbuilder {what} table", limit=4096
            )
            name_tables.check_fingerprint(data, pointers, fingerprint, f"Worldbuilder {what}")
            out.append(name_tables.NameTable(base_va=base_va, pointers=pointers))
        return out

    @staticmethod
    def _read_names(data: bytes | bytearray, base_va: int) -> list[str]:
        pointers = name_tables.read_terminated(data, base_va, "Worldbuilder table", limit=4096)
        names = [name_tables.read_cstring(data, pointer) for pointer in pointers]
        if any(entry is None for entry in names):
            raise ValueError("a table entry points at unmapped memory")
        return [entry for entry in names if entry is not None]

    @classmethod
    def _appended_name(
        cls, data: bytes | bytearray, refs: tuple[int, ...], section_va: int
    ) -> str | None:
        """The name this patch appended to the table `refs` names, or None if it did not touch
        it - which is what an optional table not given a name looks like."""
        base = struct.unpack_from("<I", data, _wbc_offset(data, refs[0]))[0]
        located = find_section(data, WORLDBUILDER_SECTION_NAME)
        if located is None or not section_va <= base:
            return None
        try:
            return cls._read_names(data, base)[-1]
        except (ValueError, IndexError, struct.error):
            return None

    def _edits(
        self, data: bytes | bytearray, tables: list[name_tables.NameTable], section_va: int
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every reference moved onto its rebuilt table, plus the nine model-condition bounds."""
        edits: list[tuple[int, bytes, bytes, str]] = []
        cursor = section_va
        for (what, refs, new_name), table in zip(self._plan(), tables, strict=True):
            edits += name_tables.ref_edits(
                data, refs, table.base_va, cursor, f"Worldbuilder {what} table"
            )
            cursor = self._table_end(cursor, table.count + 1, new_name)

        stock = _WORLDBUILDER_STOCK_CONDITION_COUNT
        for va, prefix in WORLDBUILDER_CONDITION_COUNT_SITES:
            edits.append(
                (
                    _wbc_offset(data, va),
                    prefix + struct.pack("<I", stock),
                    prefix + struct.pack("<I", stock + 1),
                    f"Worldbuilder model condition count bound @0x{va:08x}",
                )
            )
        return edits


def _wbc_offset(data: bytes | bytearray, va: int) -> int:
    off = va_to_offset(data, va)
    if off is None:
        raise ValueError(f"VA 0x{va:08x} is not mapped - not the expected build")
    return off
