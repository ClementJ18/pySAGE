"""`HEALING_RECEIVED` - an `AttributeModifier` that scales the healing a target takes.

The reverse engineering behind this is [`../docs/healing-received-modifier.md`](
../docs/healing-received-modifier.md). Targets the ROTWK SAGE-engine `game.dat` build
``2.01.2614.37001``.

Every heal in the engine becomes a `DamageInfo` with ``m_damageType == 7`` and lands in
`ActiveBody::attemptHealing` (``0x008C2FC1``), which is shared by nine body vtables. Inside it the
amount exists exactly once, in the dword `Armor::adjustDamage` returns:

    008c3061  call 0x5d893c               ; Armor::adjustDamage - returns type 7 unscaled
    008c3066  fstp dword [ebp-4]          ; <- THE AMOUNT, and this patch's hook
    008c3069  fldz
    008c306b  fld  dword [ebp-4]
    008c306e  fcompi st(1)
    008c3070  fstp st(0)
    008c3072  jbe  0x8c3195               ; <= 0: nothing happens at all
    008c308a  call [eax+0x84]             ; internalChangeHealth(amount, info)
    008c3095  movss [ebx+0x70], xmm0      ; info.out.m_actualDamageDealt

So one five-byte swap covers every source - `AutoHealBehavior`, `OpenContain`'s
`HealthRegen%PerSec`, bridge repair, `PlayerHealSpecialPower`, a `DamageType = HEALING` weapon
nugget and the rest - because they all reach this dword rather than each other.

Three things make the site cheap rather than merely convenient:

* **The healed object is already in `edi`** (``0x008C2FDD``, still live at ``0x008C30C2``), which
  is what `getModifierMultiplier` wants for `this`. No reload, no walk back to the owner.
* **The `<= 0` test is downstream.** A multiplier of zero makes the whole tail of the function
  disappear - no health change, no `out.m_actualDamageDealt`, no healing observers - so immunity
  to healing falls out of the arithmetic instead of needing an arm of its own. A NaN takes the
  same exit, since `fcompi` leaves an unordered compare and `jbe` is taken.
* **`Armor::adjustDamage` passes type 7 through unscaled** (``0x005D8963``), so the hooked dword
  is the raw amount the source asked for and this is the first thing that ever scales it.

The value is a plain multiplier: `getModifierMultiplier` seeds its out parameter to 1.0 and
multiplies each active list's value into it, and the `ModifierList` parser divides a detached
``%`` token by 100. So ``HEALING_RECEIVED 25%`` is a quarter of the healing and ``200%`` is
double, and several active lists multiply together.

**Complementary to `AUTO_HEAL`, not a duplicate of it.** `AUTO_HEAL` is additive, read once, by
`AutoHealBehavior` at ``0x008557B4``, and read on the *healer*. This is multiplicative, read on
every *target*, for every source.

What it does not reach - correctly - is anything that is not a heal: construction and repair
health go through `internalChangeHealth` directly (``0x0088DEB5``), as do respawn, level-up and
`HEALTH`/`HEALTH_MULT` max-health changes (``0x008C1C3D``, ``0x008C1D23``, ``0x008C1D49``), and so
does `detachable-rider-heal`'s `HealOnDetach`. `InactiveBody` has its own slot ``+0x04``
(``0x008C191D``) that discards healing before any of this.

Composing
---------
The keyword is a name in the modifier-type table, which `production-split` also appends to. Both
read the **live** table and copy it through by pointer, so they compose in either order and the
indices simply follow whatever was already there - see :mod:`.utils.modifier_types`.

This is **simulation state**: every peer needs the same patched binary, and a replay recorded on
it will not play back on a stock one. INI naming the keyword also fails to load on an unpatched
`game.dat`, since index 0 of the name walk doubles as "not found".
"""

from __future__ import annotations

import argparse
import struct

from sage_ini.engine import Engine, EnumDelta

from ..asm import Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset
from .utils import modifier_types, name_tables

__all__ = [
    "ANCHORS",
    "DEFAULT_KEYWORD",
    "GET_MODIFIER_MULTIPLIER",
    "HOOK_STOCK_BYTES",
    "HOOK_VA",
    "SECTION_NAME",
    "WORLDBUILDER_SECTION_NAME",
    "HealingReceivedPatch",
    "HealingReceivedWorldbuilderPatch",
    "build_section",
]


#: `ActiveBody::attemptHealing`'s `fstp` of the amount, and the `fldz` after it: five bytes with
#: nothing branching into them, which is the whole hook.
HOOK_VA = 0x008C3066
HOOK_STOCK_BYTES = bytes.fromhex("d95dfcd9ee")

#: The displaced halves, re-emitted around the query so the caller sees the stock sequence.
_DISPLACED_FSTP = bytes.fromhex("d95dfc")  # fstp dword [ebp-4]
_DISPLACED_FLDZ = bytes.fromhex("d9ee")  # fldz

#: `Object::getModifierMultiplier(Int type, Real *out, void *ctx, Int flag)` - ``__thiscall``,
#: ``ret 0x10``. Seeds ``*out`` to 1.0 and multiplies each active list's value into it, but
#: returns at its own holder guard without writing through ``out`` at all when the object has
#: never been modified - which is why the stub seeds the slot itself, exactly as every engine
#: call site does.
GET_MODIFIER_MULTIPLIER = 0x0068C82D

#: The keyword, overridable so a mod that already uses this name can pick another.
DEFAULT_KEYWORD = "HEALING_RECEIVED"

#: Byte windows the patch depends on. Two are its own - the healing path around the hook, which
#: pins `edi` as the healed object, the amount as `[ebp-4]` and the `<= 0` bail below it - and the
#: rest are the modifier system's, shared with every patch that appends a type.
ANCHORS: dict[int, bytes] = {
    # `ActiveBody::attemptHealing` from its damage-type guard to the `out` store: the type 7 test
    # and its hand-off to attemptDamage, `edi` as the object, the armor call whose result is
    # hooked, the compare that makes a zero multiplier a no-op, and internalChangeHealth
    0x008C3005: bytes.fromhex(
        "837b1007740c8b06538bceff10e9870100008b470480b842060000007521f6801a01000040"
        "751866f7800a0100004001750df68758040000010f855a0100000f57c0f30f114370f30f11"
        "43748b46f86a00508d4304508d8ee8000000e8d658d1ffd95dfcd9eed945fcdff1ddd80f86"
        "1d0100008b4620d945fc53518945f8d91c248b068bceff9084000000f30f1045fcf30f1143"
        "70f30f10460c"
    ),
    # `Object::attemptHealing`: the helper most sources go through, building the DamageInfo whose
    # type dword the hooked function tests. Not rewritten - it is what says type 7 is a heal.
    0x00690532: bytes.fromhex(
        "558bec83ec7c568bb15c02000085f6743c8d4d84e81331fdff8b450c85c0c74594070000"
        "00c745a00100000074058b4074eb0233c0f30f1045088d4d8489458c8b06518bcef30f1145a4ff5004"
    ),
    **modifier_types.ANCHORS,
}

SECTION_NAME = ".healrx"  # 7 chars: the PE name field is 8 bytes and truncates silently
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ - the rebuilt name table and the stub
# that reads its index share one section.
SECTION_CHARACTERISTICS = name_tables.SECTION_CHARACTERISTICS

_ONE_F = struct.pack("<f", 1.0)


def _call_bytes(from_va: int, to_va: int) -> bytes:
    """The five bytes of ``call rel32`` sited at ``from_va``."""
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


def build_stub(base_va: int, type_index: int) -> bytes:
    """The hook body: scale ``[ebp-4]`` by the healed object's `HEALING_RECEIVED`.

    Entered by a `call` that replaced the `fstp`/`fldz` pair, so both are re-emitted around the
    query and the caller resumes on a stack and an x87 state it cannot tell from stock. The x87
    stack is empty from the displaced `fstp` until the displaced `fldz`, so the call sits in an
    x87-neutral window.

    ``eax``, ``ecx``, ``edx`` and ``xmm0`` are all dead across the window - ``eax`` is reloaded at
    ``0x008C3078``, the `push ecx` at ``0x008C307F`` reserves a stack slot rather than passing a
    value, ``xmm0`` is reloaded at ``0x008C3090`` - and ``ebx``/``esi``/``edi`` are callee-saved
    by the stdcall callee, which is what lets the stub keep the healed object in ``edi``.
    """
    a = Asm(base_va)
    a.emit(_DISPLACED_FSTP)  # fstp dword [ebp-4]      ; displaced
    a.emit(b"\x83\xec\x04")  # sub  esp, 4             ; the out slot
    a.emit(b"\xc7\x04\x24", _ONE_F)  # mov dword [esp], 1.0
    a.emit(b"\x6a\x01")  # push 1                      ; flag, as every stock site passes
    a.emit(b"\x6a\x00")  # push 0                      ; no ctx
    a.emit(b"\x8d\x44\x24\x08")  # lea  eax, [esp+8]   ; &out, two pushes below
    a.emit(0x50)  # push eax
    a.emit(modifier_types.push_type(type_index))
    a.emit(b"\x8b\xcf")  # mov  ecx, edi               ; the healed object
    a.call_absolute(GET_MODIFIER_MULTIPLIER)  # ret 0x10: it cleans all four arguments
    a.emit(b"\xf3\x0f\x10\x04\x24")  # movss xmm0, [esp]
    a.emit(b"\xf3\x0f\x59\x45\xfc")  # mulss xmm0, [ebp-4]
    a.emit(b"\xf3\x0f\x11\x45\xfc")  # movss [ebp-4], xmm0
    a.emit(b"\x83\xc4\x04")  # add  esp, 4
    a.emit(_DISPLACED_FLDZ)  # fldz                    ; displaced
    a.emit(0xC3)  # ret
    return a.finish()


def build_section(
    base_va: int, existing_pointers: list[int], keyword: str
) -> tuple[bytes, int, int]:
    """``(section content, rebuilt table VA, stub VA)`` for a cave based at ``base_va``.

    Table first, so :meth:`HealingReceivedPatch.verify` finds it at the section base without
    knowing how long the stub is, then the keyword string it points at, then the stub."""
    table, _name_vas, stub_va = name_tables.layout(existing_pointers, [keyword], base_va)
    return table + build_stub(stub_va, len(existing_pointers)), base_va, stub_va


class HealingReceivedPatch(Patch):
    """A `ModifierList` keyword that scales how much healing its target takes."""

    name = "healing-received"
    author = "officialNecro"
    description = (
        "a HEALING_RECEIVED ModifierType: name it on a ModifierList's Modifier line and every "
        "heal that target takes is multiplied by it, from any source - 25% is a quarter, 200% is "
        "double, 0% is immune to healing. Nothing changes until INI uses the name; needs no "
        ".str/.csf key and no map data"
    )

    def __init__(self, keyword: str = DEFAULT_KEYWORD) -> None:
        name_tables.validate_name(keyword, "modifier type name")
        self.keyword = keyword

    def __str__(self) -> str:
        return f"{self.name} ({self.keyword})"

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        name_tables.check_not_rebased(data)
        table = modifier_types.read(data)
        modifier_types.check_free(table, data, [self.keyword])
        existing = list(table.pointers)

        section_va = allocate_section(
            data,
            SECTION_NAME,
            lambda va: build_section(va, existing, self.keyword)[0],
            SECTION_CHARACTERISTICS,
        )
        _content, table_va, stub_va = build_section(section_va, existing, self.keyword)
        edits = [self._hook_edit(data, stub_va)]
        edits += modifier_types.relocation_edits(data, table, table_va)
        for file_off, old, new, note in edits:
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch (an empty list == verified).

        The index the stub pushes is recovered from the cave's own table rather than assumed,
        because another type-appending patch shifts it - and then cross-checked against the
        **live** table, which is the invariant that survives either application order. What is
        deliberately not checked is that the name walk points at *this* cave: whichever appender
        ran last owns those two operands, and this patch is still correctly installed."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, vsize = located

        try:
            added = modifier_types.appended_names(data, section_va, vsize)
            existing = self._copied_pointers(data, section_va, len(added))
            content, _table_va, stub_va = build_section(section_va, existing, self.keyword)
        except (ValueError, struct.error, IndexError) as exc:
            return [f"cannot recompute the expected cave (wrong build?): {exc}"]

        problems: list[str] = []
        if added != [self.keyword]:
            problems.append(
                f"the table in {SECTION_NAME} appends {added}, expected [{self.keyword!r}]"
            )
        got = bytes(data[section_off : section_off + len(content)])
        if got != content:
            problems.append(
                f"{SECTION_NAME} does not hold the expected table and stub "
                "(the cave differs, or was built for another base address)"
            )

        file_off, _old, new, note = self._hook_edit(data, stub_va)
        found = bytes(data[file_off : file_off + len(new)])
        if found != new:
            problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {found.hex()}")

        problems += self._live_table_problems(data, len(existing))
        problems += self._anchor_problems(data, patched=True)
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> HealingReceivedPatch | None:
        """Recognise this patch **and recover the keyword it was applied with**, which is the one
        name in the cave's table whose string lives inside the cave."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return None
        section_va, _section_off, vsize = located
        try:
            added = modifier_types.appended_names(data, section_va, vsize)
            if len(added) != 1:
                return None
            patch = cls(keyword=added[0])
        except (ValueError, IndexError, struct.error):
            return None
        return None if patch.verify(data) else patch

    def ini_surface(self) -> Engine:
        """The one token this patch adds to the `ModifierList` `Modifier` name table.

        No index is claimed: the name goes at the end of whatever table the image had, so it
        depends on what else has been applied, and `sagepatch` reads the index off the live table
        and fuses it with the provenance this reports."""
        return Engine(enum_members=(EnumDelta("ModifierType", self.keyword, None, self.name),))

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--keyword",
            default=DEFAULT_KEYWORD,
            help=f"the ModifierType name to add (default: {DEFAULT_KEYWORD})",
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> HealingReceivedPatch:
        return cls(keyword=args.keyword)

    def _hook_edit(self, data: bytes | bytearray, stub_va: int) -> tuple[int, bytes, bytes, str]:
        """The one five-byte range this patch rewrites in `.text`."""
        off = va_to_offset(data, HOOK_VA)
        if off is None:
            raise ValueError(f"the healing hook at 0x{HOOK_VA:08x} is not mapped")
        return (
            off,
            HOOK_STOCK_BYTES,
            _call_bytes(HOOK_VA, stub_va),
            "ActiveBody::attemptHealing amount -> healing-received stub",
        )

    @staticmethod
    def _copied_pointers(data: bytes | bytearray, section_va: int, added: int) -> list[int]:
        """The name pointers this cave copied through, from its own rebuilt table."""
        pointers = name_tables.read_terminated(
            data, section_va, f"the modifier-type table in {SECTION_NAME}"
        )
        if len(pointers) <= added:
            raise ValueError(
                f"the table in {SECTION_NAME} holds {len(pointers)} entries, too few to carry "
                "the name this patch appends"
            )
        return list(pointers[: len(pointers) - added])

    def _live_table_problems(self, data: bytes | bytearray, index: int) -> list[str]:
        """The live table has to give the keyword the index the stub pushes."""
        try:
            live = modifier_types.read(data)
        except (ValueError, struct.error) as exc:
            return [f"cannot read the live modifier-type table: {exc}"]
        got = live.index_of(data, self.keyword)
        if got != index:
            return [
                f"the live modifier-type table at 0x{live.base_va:08x} puts {self.keyword!r} at "
                f"{got}, but this cave's stub pushes {index}"
            ]
        return []

    def _anchor_problems(self, data: bytes | bytearray, patched: bool = False) -> list[str]:
        """Everything the patch depends on and does not rewrite.

        ``patched`` blanks the five bytes this patch rewrites. The two modifier-table operands are
        blanked unconditionally: any type-appending patch owns them, so their value says nothing
        about this one either way, and :func:`.modifier_types.read` checks what they point at far
        more tightly than a byte compare would."""
        blank = list(modifier_types.VOLATILE_SPANS)
        if patched:
            blank.append((HOOK_VA, len(HOOK_STOCK_BYTES)))

        problems: list[str] = []
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                problems.append(f"anchor 0x{va:08x} is not mapped - not the expected build")
                continue
            got = bytearray(data[off : off + len(expected)])
            want = bytearray(expected)
            for site_va, width in blank:
                at = site_va - va
                if 0 <= at <= len(expected) - width:
                    got[at : at + width] = want[at : at + width] = b"\x00" * width
            if bytes(got) != bytes(want):
                problems.append(
                    f"anchor 0x{va:08x}: expected {bytes(want).hex()}, got {bytes(got).hex()}"
                )
        return problems

    def _check_anchors(self, data: bytes | bytearray) -> None:
        problems = self._anchor_problems(data)
        if problems:
            joined = "; ".join(problems)
            raise ValueError(f"healing-received: this is not the expected build: {joined}")


#: The PE section name field is 8 bytes and truncates silently.
WORLDBUILDER_SECTION_NAME = ".wbheal"

# CNT_INITIALIZED_DATA | MEM_READ - a pointer table and one string, no code.
_WORLDBUILDER_CHARACTERISTICS = 0x40000040


class HealingReceivedWorldbuilderPatch(Patch):
    """Teach **Worldbuilder** the `HEALING_RECEIVED` modifier type.

    **This patch targets `Worldbuilder.exe`, not `game.dat`.** It is the authoring half of
    `healing-received`: the editor resolves `Modifier = <ModifierType> <value>` through its own
    copy of the name table, and a token that copy does not hold throws during INI load and ends
    the editor. Give both binaries the same name.

    Parsing only - the editor gains no healing behaviour and needs none.
    """

    name = "healing-received-wb"
    author = "officialNecro"
    description = (
        "Worldbuilder.exe (not game.dat): add the HEALING_RECEIVED ModifierType name to the "
        "editor's own name table, so attribute modifiers using it parse instead of throwing on an "
        "unknown token and ending the editor's load. Pass the same name given to game.dat's "
        "healing-received; the editor gains no healing behaviour, only the ability to read it"
    )

    def __init__(self, keyword: str = DEFAULT_KEYWORD) -> None:
        name_tables.validate_name(keyword, "modifier type name")
        self.keyword = keyword

    def __str__(self) -> str:
        return f"{self.name} ({self.keyword})"

    def apply(self, data: bytearray) -> None:
        name_tables.check_not_rebased(data)
        table = modifier_types.read_worldbuilder(data)
        modifier_types.check_free(table, data, [self.keyword])
        section_va = allocate_section(
            data,
            WORLDBUILDER_SECTION_NAME,
            lambda base_va: name_tables.layout(table.pointers, [self.keyword], base_va)[0],
            _WORLDBUILDER_CHARACTERISTICS,
        )
        for file_off, old, new, note in modifier_types.worldbuilder_relocation_edits(
            data, table, section_va
        ):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, WORLDBUILDER_SECTION_NAME)
        if located is None:
            return [f"no {WORLDBUILDER_SECTION_NAME} section: the file does not carry this patch"]
        section_va, _section_off, vsize = located
        try:
            added = modifier_types.appended_names(data, section_va, vsize)
            live = modifier_types.read_worldbuilder(data)
        except (ValueError, struct.error) as exc:
            return [f"cannot read back the {WORLDBUILDER_SECTION_NAME} cave (wrong build?): {exc}"]

        problems: list[str] = []
        if added != [self.keyword]:
            problems.append(f"the rebuilt type table appends {added}, expected [{self.keyword!r}]")
        # Not "the refs point here": a second type-appending patch owns them once applied, and
        # this one is still installed. What has to hold either way is that the editor's lookup
        # reaches a table naming this type.
        if live.index_of(data, self.keyword) is None:
            problems.append(
                f"the live type table at 0x{live.base_va:08x} does not name {self.keyword!r}"
            )
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> HealingReceivedWorldbuilderPatch | None:
        """Recognise this patch **and recover the name it was applied with**."""
        located = find_section(data, WORLDBUILDER_SECTION_NAME)
        if located is None:
            return None
        section_va, _section_off, vsize = located
        try:
            added = modifier_types.appended_names(data, section_va, vsize)
            if len(added) != 1:
                return None
            patch = cls(keyword=added[0])
        except (ValueError, IndexError, struct.error):
            return None
        return None if patch.verify(data) else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--keyword",
            default=DEFAULT_KEYWORD,
            help=f"the ModifierType name to add (default: {DEFAULT_KEYWORD})",
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> HealingReceivedWorldbuilderPatch:
        return cls(keyword=args.keyword)
