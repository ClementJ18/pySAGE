"""The detachable-rider-heal patch: a mount is healed by a flat amount when its rider comes off.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/detachable-rider-heal.md``.

**What the engine does today.** `DetachableRiderBody` overrides `attemptDamage`
(``0x008C5EF3``). When a hit would kill the object and the module is active, the override does
not let the death happen: it *rewrites the pending damage* so what lands leaves the object at
`HealthPercentageWhenRiderDies` of its maximum, clears the instant-kill flag, finds the object's
`DetachableRiderUpdate` by name and calls it (``0x008B2A46``) to take the rider off - then falls
into `ActiveBody::attemptDamage` (``0x008C3FA3``) to apply the amount it just wrote.

So the only lever a mod has over what the riderless object is worth is a **percentage of its own
maximum health**, spent out of the health it happened to have. There is no way to say "and give
it 200 hit points back", which is the natural way to price a mount that survives its rider:
`HealthPercentageWhenRiderDies` scales with the unit, a flat grant does not.

**What this does.** Adds one `Real` field, `HealOnDetach`, to the module. Default `0`, which is
stock behaviour; a positive value is added to the object's health, in hit points, at the moment
the rider is detached - after the rewritten damage has landed, so the two compose exactly as
written: the object comes out at `HealthPercentageWhenRiderDies` of maximum **plus**
`HealOnDetach`, capped by the engine's own clamp at maximum health.

**Why it heals rather than paying for itself out of the damage.** The obvious cheap edit is to
subtract the amount from the damage the override writes, and it would be wrong twice.
`ActiveBody::attemptDamage` runs the written amount through the armor of the object it lands
on, so a "raw" amount spent that way is scaled by whatever the mount's armor does to that damage
type - the grant would be worth a different number of hit points per damage source. And the
damage is applied *after* the rewrite, so a heal folded into it is bounded by the health the
object had when the killing blow arrived rather than by its maximum. Calling the engine's own
`ActiveBody::internalChangeHealth` (body vtable ``+0x84``, the routine `attemptHealing` and
`attemptDamage` both end at) sidesteps both: it takes hit points, not damage, and it carries the
clamp to maximum health and the damage-state bookkeeping with it.

**It heals when the rider actually comes off.** The hook sits on the detach call itself, so the
one path that does not detach - the object has a `DetachableRiderBody` but no
`DetachableRiderUpdate` to find, and the module walk comes back NULL - keeps the stock bytes and
grants nothing. And the heal is skipped when the object came out of the damage at zero health,
so `HealthPercentageWhenRiderDies = 0%` still kills: the field can top a survivor up, never
resurrect a corpse.

**The `ModuleData` grows.** Its three own fields sit at ``+0x194``, ``+0x198`` and ``+0x19C``,
and ``sizeof`` is ``0x1A0`` - the last field ends exactly at the end of the struct, so unlike
`terrain-resource-exp` there is no padding to move into. The class has **one** allocation, the
`push 0x1A0` in its `ModuleData` factory (``0x006514EA``), and **one** constructor call
(``0x00651502``); the patch widens the first to ``0x1A4`` and routes the second through a stub
that zeroes the new dword, because `operator new` does not. `operator delete` here takes only a
pointer, so nothing else has to learn the new size.

**Determinism.** Health is logic-side `Object` state and the engine CRCs it, so **every peer must
run the same patched binary**. And the keyword is fatal on a stock one: SAGE treats an unknown
field in a known block as a parse error, so a mod that writes `HealOnDetach` cannot load without
the patched `game.dat`. Savegames are unaffected - `ModuleData` is load-time configuration read
from `.ini` and never `Xfer`'d.

**Composition.** Order-independent: the cave is allocated past every existing section and
:meth:`verify` finds it by name. No other bundled patch touches the module's factory, its field
table or ``0x008C60``..; the nearest neighbour, `terrain-resource-exp`, adds its field to a
different module by the same three-step recipe and the two share no byte.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, FieldDelta

from ..addresses import FIELD_PARSE_STRIDE, INI_PARSE_REAL
from ..asm import JAE, JBE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "DEFAULT_KEYWORD",
    "FIELD_OFFSET",
    "INHERITED_KEYWORDS",
    "SECTION_NAME",
    "STOCK_FIELD_COUNT",
    "DetachableRiderHealPatch",
    "build_code",
    "build_table",
    "entry_points",
    "validate_keyword",
]

SECTION_NAME = ".rdheal"  # 7 chars: the PE name field is 8 bytes and truncates silently

#: The keyword the field is installed under unless the caller names another one.
DEFAULT_KEYWORD = "HealOnDetach"

#: `DetachableRiderBodyModuleData`'s stock size, and the size it is grown to. The new `Real`
#: lands at the old end of the struct, which is already 4-byte aligned.
STOCK_MODULE_DATA_SIZE = 0x1A0
PATCHED_MODULE_DATA_SIZE = 0x1A4
FIELD_OFFSET = STOCK_MODULE_DATA_SIZE

#: The `push` of that size in the `ModuleData` factory - the class's only allocation.
MODULE_DATA_SIZE_VA = 0x006514EA
MODULE_DATA_SIZE_STOCK = b"\x68" + struct.pack("<I", STOCK_MODULE_DATA_SIZE)
MODULE_DATA_SIZE_PATCHED = b"\x68" + struct.pack("<I", PATCHED_MODULE_DATA_SIZE)

#: `DetachableRiderBodyModuleData::DetachableRiderBodyModuleData` - ``__thiscall``, no arguments,
#: returns `this` in `eax`. It runs the `ActiveBody` base constructor, the `UpgradeMux` one at
#: ``+0x64``, and writes its own three defaults; it never touches the new dword, so the stub the
#: call is routed through has to.
MODULE_DATA_CTOR = 0x008C6035
MODULE_DATA_CTOR_CALL_VA = 0x00651502
MODULE_DATA_CTOR_CALL_STOCK = bytes.fromhex("e82e4b2700")  # call 0x008c6035

#: The module's own field table and the `push` that hands it to the reader, inside
#: `buildFieldParse` (``0x008C5D2B``). That `push` is the table's **only** reference in the image,
#: so relocating the table is a single 4-byte repoint - and the table is walked to its NULL
#: terminator rather than to a count, so no bound needs raising.
FIELD_TABLE = 0x00C72A0C
FIELD_TABLE_PUSH_VA = 0x008C5D47
FIELD_TABLE_PUSH_STOCK = b"\x68" + struct.pack("<I", FIELD_TABLE)

#: The whole stock table: three rows and the NULL name pointer that ends the walk. Its keyword
#: strings sit immediately before it and unrelated `.rdata` immediately after the terminating
#: dword - which is why the table cannot grow in place, and why this constant stops at that dword
#: rather than spanning a whole zero row. Rows in table order:
#: `HealthPercentageWhenRiderDies` +0x194 (Percent), `StartsActive` +0x198 (Bool),
#: `RiderlessDeathChance` +0x19C (Percent).
FIELD_TABLE_STOCK = bytes.fromhex(
    "ec29c700faee420000000000940100008466c00058e542000000000098010000"
    "d429c700faee4200000000009c01000000000000"
)

#: The names `DetachableRiderBody` already parses through the two tables it inherits - the
#: `ActiveBody` one and the `UpgradeMux` one - which the reader adds *before* the module's own.
#: A keyword duplicating one of these would be matched there and the new field would silently
#: never be written, so they are refused up front rather than found out in a game.
INHERITED_KEYWORDS = (
    "BurningDeathBehavior",
    "BurningDeathFX",
    "CheerRadius",
    "ConflictsWith",
    "CustomAnimAndDuration",
    "DamageCreationList",
    "DamagedAttributeModifier",
    "DodgePercent",
    "EnteringDamagedTransitionTime",
    "EnteringReallyDamagedTransitionTime",
    "GrabDamage",
    "GrabFX",
    "GrabObject",
    "GrabOffset",
    "HealingBuffFx",
    "InitialHealth",
    "MaxHealth",
    "MaxHealthDamaged",
    "MaxHealthReallyDamaged",
    "Permanent",
    "ReallyDamagedAttributeModifier",
    "RecoveryTime",
    "RemoveUpgradesOnDeath",
    "RequiresAllConflictingTriggers",
    "RequiresAllTriggers",
    "TriggeredBy",
    "UseDefaultDamageSettings",
)

#: The tail of the detach branch in `DetachableRiderBody::attemptDamage`: `mov ecx, eax` on the
#: `DetachableRiderUpdate` the module walk just returned, then the call that takes the rider off.
#: Seven bytes, entered only by falling through the `jne` that tested the walk's answer - nothing
#: in the image branches into the window.
DETACH_TAIL_VA = 0x008C6015
DETACH_TAIL_STOCK = bytes.fromhex("8bc8e82acafeff")  # mov ecx, eax; call 0x008b2a46
DETACH_RIDER = 0x008B2A46

#: Where the hooked branch rejoins: the instruction after the stock tail's call into
#: `ActiveBody::attemptDamage`, which the cave reproduces itself.
DETACH_TAIL_RESUME = 0x008C6024

#: `ActiveBody::attemptDamage` - ``__thiscall``, ``ret 4`` (the `DamageInfo *`). The base call
#: every arm of the override ends at, and the one the cave displaces for the detach arm only.
BASE_ATTEMPT_DAMAGE = 0x008C3FA3

#: `ActiveBody::internalChangeHealth(Real delta, DamageInfo *info)` - body-interface vtable slot
#: ``+0x84``, ``ret 8``. Adds `delta` to the health at interface ``+0x08``, clamps it to the
#: maximum at ``+0x10`` and to zero, and runs the damage-state and subdual bookkeeping. `info` is
#: unread by this implementation; it is passed anyway because both engine call sites pass theirs.
INTERNAL_CHANGE_HEALTH_SLOT = 0x84

#: Where the override keeps its two live pointers across the whole detach branch: `esi` is the
#: body interface (`this`), `edi` the `DamageInfo *` the function was called with. The
#: `ModuleData` is at interface ``-0x0C`` and the current health at interface ``+0x08``, both read
#: by the stock code either side of the hook.
MODULE_DATA_INTERFACE_OFFSET = -0x0C
HEALTH_INTERFACE_OFFSET = 0x08

#: Rows in the stock table, excluding the NULL name pointer that terminates it.
STOCK_FIELD_COUNT = (len(FIELD_TABLE_STOCK) - 4) // FIELD_PARSE_STRIDE

#: The sites the patch asserts before it writes anything, as ``VA -> stock bytes``.
ANCHORS = {
    MODULE_DATA_SIZE_VA: MODULE_DATA_SIZE_STOCK,
    MODULE_DATA_CTOR_CALL_VA: MODULE_DATA_CTOR_CALL_STOCK,
    FIELD_TABLE_PUSH_VA: FIELD_TABLE_PUSH_STOCK,
    DETACH_TAIL_VA: DETACH_TAIL_STOCK,
    FIELD_TABLE: FIELD_TABLE_STOCK,
}

# IMAGE_SCN_CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ. The cave holds the keyword, the rebuilt
# table and two routines, so it is both read as data and entered as code.
_CHARACTERISTICS = 0x40 | 0x20000000 | 0x40000000

# An INI keyword is matched by exact compare, so anything the parser could never match is a typo
# rather than a choice. The engine's own field names are CamelCase with digits and underscores.
_KEYWORD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")

#: The routines the cave holds, in the order it lays them out.
ROUTINES = ("ctor", "detach")


def validate_keyword(keyword: str) -> None:
    """Raise unless ``keyword`` is a token the engine's INI reader could ever match."""
    if not _KEYWORD_PATTERN.match(keyword):
        raise ValueError(
            "an INI keyword must be letters, digits and underscores starting with a letter "
            f"(the reader matches it by exact compare), got {keyword!r}"
        )
    if keyword in INHERITED_KEYWORDS:
        raise ValueError(
            f"DetachableRiderBody already parses {keyword!r} through an inherited table, where "
            "the reader would match it first - pick another keyword"
        )


@dataclass(frozen=True)
class _Layout:
    """Where each piece of the cave sits, given its base address and the keyword.

    Pure arithmetic on the keyword's length, so :meth:`DetachableRiderHealPatch.apply` and
    :meth:`DetachableRiderHealPatch.verify` compute the same addresses from opposite
    directions."""

    keyword_va: int
    table_va: int
    code_va: int


def _layout(base_va: int, keyword: str) -> _Layout:
    string = len(keyword) + 1
    table_va = base_va + string + (-string % 4)  # keep the table's dwords aligned
    code_va = table_va + (STOCK_FIELD_COUNT + 2) * FIELD_PARSE_STRIDE  # + the row + the terminator
    return _Layout(base_va, table_va, code_va)


def build_table(keyword_va: int) -> bytes:
    """The rebuilt field-parse table: the stock rows verbatim, the new `Real`, the terminator.

    The stock rows are copied rather than rewritten because every pointer in them is absolute -
    their keyword strings stay where they are, in `.rdata`, and only the new row points into the
    cave."""
    rows = FIELD_TABLE_STOCK[: STOCK_FIELD_COUNT * FIELD_PARSE_STRIDE]
    new_row = struct.pack("<IIII", keyword_va, INI_PARSE_REAL, 0, FIELD_OFFSET)
    return rows + new_row + bytes(FIELD_PARSE_STRIDE)


def _assemble(base_va: int) -> Asm:
    """Both routines, laid out in one buffer so their addresses come from the layout itself."""
    a = Asm(base_va)

    # The constructor stub. The stock constructor returns `this` in eax and the factory reads it
    # from there, so zeroing the new field costs one instruction and disturbs nothing else.
    a.label("ctor")
    a.call_absolute(MODULE_DATA_CTOR)
    a.emit(0x83, 0xA0, struct.pack("<I", FIELD_OFFSET), 0x00)  # and dword [eax+0x1a0], 0
    a.emit(0xC3)  # ret

    # The detach arm, from the call that takes the rider off through to the base damage call the
    # stock tail makes - reproduced here so the heal can land after the damage rather than before
    # it, which is what keeps the grant clear of the clamp at maximum health.
    a.label("detach")
    a.emit(DETACH_TAIL_STOCK[:2])  # mov ecx, eax          (displaced)
    a.call_absolute(DETACH_RIDER)  # call DetachableRiderUpdate  (displaced)
    a.emit(0x57)  # push edi                               the DamageInfo
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(BASE_ATTEMPT_DAMAGE)  # ActiveBody::attemptDamage, the stock tail
    a.emit(0x8B, 0x46, MODULE_DATA_INTERFACE_OFFSET & 0xFF)  # mov eax, [esi-0xc]  the ModuleData
    a.emit(0xF3, 0x0F, 0x10, 0x80, struct.pack("<I", FIELD_OFFSET))  # movss xmm0, [eax+0x1a0]
    a.emit(0x0F, 0x57, 0xC9)  # xorps xmm1, xmm1
    a.emit(0x0F, 0x2F, 0xC1)  # comiss xmm0, xmm1
    a.jcc_short(JBE, "done")  # nothing to grant, and a NaN counts as nothing
    a.emit(0x0F, 0x2F, 0x4E, HEALTH_INTERFACE_OFFSET)  # comiss xmm1, [esi+8]   zero vs health
    a.jcc_short(JAE, "done")  # the damage killed it anyway - the field tops up, never revives
    a.emit(0x57)  # push edi                               the DamageInfo, as the engine passes it
    a.emit(0x51)  # push ecx                               the float's slot
    a.emit(0xF3, 0x0F, 0x11, 0x04, 0x24)  # movss [esp], xmm0
    a.emit(0x8B, 0x06)  # mov eax, [esi]                   the body-interface vtable
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.emit(0xFF, 0x90, struct.pack("<I", INTERNAL_CHANGE_HEALTH_SLOT))  # call [eax+0x84]
    a.label("done")
    a.jmp_absolute(DETACH_TAIL_RESUME)
    return a


def build_code(base_va: int) -> bytes:
    """The cave's code, laid out at ``base_va``."""
    return _assemble(base_va).finish()


def entry_points(base_va: int) -> dict[str, int]:
    """Where each routine starts, given the address the code is laid out at."""
    code = _assemble(base_va)
    code.finish()
    return {name: code.label_va(name) for name in ROUTINES}


def _hook_bytes(code_va: int) -> bytes:
    """`jmp rel32` to the detach routine, padded to the 7 bytes of the two it displaces."""
    jump = b"\xe9" + struct.pack("<i", code_va - (DETACH_TAIL_VA + 5))
    return jump + b"\x90" * (len(DETACH_TAIL_STOCK) - len(jump))


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


class DetachableRiderHealPatch(Patch):
    """Add a `HealOnDetach` real to `DetachableRiderBody`, granting it at the detach."""

    name = "detachable-rider-heal"
    author = "officialNecro"
    description = (
        "Add a HealOnDetach real to DetachableRiderBody, healing the object by that many hit "
        "points at the moment its rider is detached - on top of whatever "
        "HealthPercentageWhenRiderDies leaves it at, and capped by its maximum health. Write "
        "HealOnDetach = <hit points> on the module (0, the default, is stock); a mod that writes "
        "the keyword will not load on an unpatched binary, since an unknown field is an INI "
        "parse error"
    )

    def __init__(self, keyword: str = DEFAULT_KEYWORD):
        self.keyword = keyword
        validate_keyword(keyword)

    def __str__(self) -> str:
        return f"{self.name} ({self.keyword})"

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        self._check_keyword_free(data)

        base_va = allocate_section(data, SECTION_NAME, self._build, _CHARACTERISTICS)
        pieces = _layout(base_va, self.keyword)
        routines = entry_points(pieces.code_va)

        for va, old, new, note in (
            (
                MODULE_DATA_SIZE_VA,
                MODULE_DATA_SIZE_STOCK,
                MODULE_DATA_SIZE_PATCHED,
                f"the ModuleData factory allocates 0x{PATCHED_MODULE_DATA_SIZE:x} bytes",
            ),
            (
                MODULE_DATA_CTOR_CALL_VA,
                MODULE_DATA_CTOR_CALL_STOCK,
                b"\xe8" + struct.pack("<i", routines["ctor"] - (MODULE_DATA_CTOR_CALL_VA + 5)),
                f"the constructor call -> the stub that defaults {self.keyword} to 0",
            ),
            (
                FIELD_TABLE_PUSH_VA,
                FIELD_TABLE_PUSH_STOCK,
                b"\x68" + struct.pack("<I", pieces.table_va),
                f"buildFieldParse -> the {SECTION_NAME} field table",
            ),
            (
                DETACH_TAIL_VA,
                DETACH_TAIL_STOCK,
                _hook_bytes(routines["detach"]),
                f"the detach call -> the {self.keyword} grant",
            ),
        ):
            apply_byte_patch(data, _offset(data, va), old, new, note)

    def _build(self, base_va: int) -> bytes:
        """The cave: the keyword string, the rebuilt table, the two routines."""
        pieces = _layout(base_va, self.keyword)
        blob = self.keyword.encode("ascii") + b"\x00"
        blob += bytes(pieces.table_va - (base_va + len(blob)))
        blob += build_table(pieces.keyword_va)
        assert base_va + len(blob) == pieces.code_va, "the cave layout and its addresses disagree"
        return blob + build_code(pieces.code_va)

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        """Raise unless every site still holds its stock bytes.

        Checked before anything is written, because the table is copied into the cave rather than
        read row by row and the two struct sites have to agree with each other: a build whose
        factory allocates a different size would be grown wrong and silently."""
        for va, stock in ANCHORS.items():
            off = _offset(data, va)
            got = bytes(data[off : off + len(stock)])
            if got != stock:
                raise ValueError(
                    f"@0x{va:08x}: expected the stock DetachableRiderBody bytes {stock.hex()}, "
                    f"got {got.hex()} - the file is not the expected build, or already carries "
                    "this patch"
                )

    def _check_keyword_free(self, data: bytes | bytearray) -> None:
        """Raise if the module's own table already parses this keyword.

        A duplicate row would parse - the reader takes the first match and the engine would never
        complain - so the field would exist and silently do nothing. The inherited names are
        refused by :func:`validate_keyword`, which needs no image to know them."""
        for index in range(STOCK_FIELD_COUNT):
            name_va = struct.unpack_from("<I", FIELD_TABLE_STOCK, index * FIELD_PARSE_STRIDE)[0]
            if _cstring(data, name_va) == self.keyword:
                raise ValueError(
                    f"DetachableRiderBody already has a {self.keyword!r} field - pick "
                    "another keyword"
                )

    @classmethod
    def detect(cls, data: bytes | bytearray) -> DetachableRiderHealPatch | None:
        """Recognise this patch **and recover its keyword** from ``data``.

        The default probe would only ever recognise the default keyword. The keyword string is
        the first thing in the cave (`_layout` puts it at the section base), so it reads straight
        back out; `verify` then checks the whole cave against it."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        keyword = _cstring(data, located[0])
        if keyword is None:
            return None
        try:
            patch = cls(keyword)
        except ValueError:
            return None  # not a keyword this patch could have written
        return None if patch.verify(data) else patch

    def ini_surface(self) -> Engine:
        """The one `Real` this patch adds to `DetachableRiderBody`, under whatever keyword it was
        installed with. The constructor stub zeroes it, so the default is `0` - stock behaviour,
        which is what makes the field opt-in."""
        return Engine(
            fields=(FieldDelta("DetachableRiderBody", self.keyword, "Float", 0.0, self.name),)
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Return the structural problems that mean ``data`` does not carry this patch for
        exactly this keyword. Reads only via ``struct`` and the section table, so it needs no
        disassembler.

        Every address is recovered from where the cave actually landed rather than from where it
        would land on a clean image, so a build carrying another patch's section too verifies the
        same."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, _section_off, vsize = located
        pieces = _layout(section_va, self.keyword)

        problems: list[str] = []
        try:
            problems += self._verify_cave(data, pieces, section_va, vsize)
            problems += self._verify_sites(data, pieces)
        except (ValueError, struct.error) as exc:
            problems.append(f"cannot read back the patch (wrong build?): {exc}")
        return problems

    def _verify_cave(
        self, data: bytes | bytearray, pieces: _Layout, section_va: int, vsize: int
    ) -> list[str]:
        problems: list[str] = []
        code = build_code(pieces.code_va)
        if pieces.code_va + len(code) > section_va + vsize:
            problems.append(
                f"{SECTION_NAME} holds {vsize} bytes, too few for the table and the routines"
            )
            return problems
        got_keyword = _cstring(data, pieces.keyword_va)
        if got_keyword != self.keyword:
            problems.append(
                f"the keyword in {SECTION_NAME} is {got_keyword!r}, not {self.keyword!r}"
            )
        want_table = build_table(pieces.keyword_va)
        table_off = _offset(data, pieces.table_va)
        if bytes(data[table_off : table_off + len(want_table)]) != want_table:
            problems.append(
                f"the field table at 0x{pieces.table_va:08x} is not the stock "
                f"{STOCK_FIELD_COUNT} rows plus a Real at ModuleData+0x{FIELD_OFFSET:x}"
            )
        code_off = _offset(data, pieces.code_va)
        if bytes(data[code_off : code_off + len(code)]) != code:
            problems.append(
                f"the routines at 0x{pieces.code_va:08x} are not the ones this patch builds"
            )
        return problems

    def _verify_sites(self, data: bytes | bytearray, pieces: _Layout) -> list[str]:
        routines = entry_points(pieces.code_va)
        checks = (
            (
                MODULE_DATA_SIZE_VA,
                MODULE_DATA_SIZE_PATCHED,
                f"the ModuleData factory does not allocate 0x{PATCHED_MODULE_DATA_SIZE:x} bytes",
            ),
            (
                MODULE_DATA_CTOR_CALL_VA,
                b"\xe8" + struct.pack("<i", routines["ctor"] - (MODULE_DATA_CTOR_CALL_VA + 5)),
                f"the constructor call does not reach the {SECTION_NAME} stub",
            ),
            (
                FIELD_TABLE_PUSH_VA,
                b"\x68" + struct.pack("<I", pieces.table_va),
                f"buildFieldParse does not push the {SECTION_NAME} field table",
            ),
            (
                DETACH_TAIL_VA,
                _hook_bytes(routines["detach"]),
                f"the detach call is not hooked to the {SECTION_NAME} grant",
            ),
        )
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
            default=DEFAULT_KEYWORD,
            metavar="NAME",
            help=(
                f"name of the INI field to add (default {DEFAULT_KEYWORD}); letters, digits and "
                "underscores, and must not already be a DetachableRiderBody field, inherited "
                "ones included"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> DetachableRiderHealPatch:
        return cls(keyword=args.keyword)
