"""Add an `EXPERIENCE_AWARD` `ModifierType`: a `ModifierList` naming it scales the experience its
holder is worth when it is killed (50% is half, 0% is nothing).

The value a dying object grants is read in one place, `ExperienceTracker::getExperienceValue`
(`0x0079D1DB`), which has two callers: the killer's own experience and the killing player's
tally. Both calls are swapped for a wrapper that runs the stock function and multiplies what it
returns by the modifier on the tracker's owner - the victim. Unlike `EXPERIENCE` (read on the
killer, scaling what it earns) it is read on the object that dies.
`ExperienceAwardWorldbuilderPatch` teaches the editor the same token.

Derivation: `../docs/experience-award-modifier.md`.
"""

from __future__ import annotations

import argparse
import struct

from sage_ini.engine import Engine, EnumDelta

from ..asm import Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, call_rel32, find_section, va_to_offset
from .utils import modifier_types, name_tables

__all__ = [
    "ANCHORS",
    "CALL_SITES",
    "DEFAULT_KEYWORD",
    "GET_EXPERIENCE_VALUE",
    "GET_MODIFIER_MULTIPLIER",
    "SECTION_NAME",
    "TRACKER_OWNER_OFFSET",
    "WORLDBUILDER_SECTION_NAME",
    "ExperienceAwardPatch",
    "ExperienceAwardWorldbuilderPatch",
    "build_section",
    "build_stub",
]


#: `ExperienceTracker::getExperienceValue(Object *killer, Bool evenFromAllies)` - `__thiscall` on
#: the **victim's** tracker, `ret 8`, the award as an `Int` in `eax`. It answers 0 for an allied
#: killer unless the flag is set, and otherwise the current level's `ExperienceAward`, cached at
#: tracker `+0x14`.
GET_EXPERIENCE_VALUE = 0x0079D1DB

#: The tracker's owning `Object *`. `getExperienceValue` pushes it as the argument of the killer's
#: relationship test, which is what says it is the object the tracker belongs to.
TRACKER_OWNER_OFFSET = 0x34

#: Both callers of `GET_EXPERIENCE_VALUE`, as `(call VA, what it feeds)`. Each is a five-byte
#: `call rel32` and the only edit made at its site.
CALL_SITES: tuple[tuple[int, str], ...] = (
    (0x006954B5, "the killer's experience"),
    (0x006AB083, "the killing player's tally"),
)

#: `Object::getModifierMultiplier(Int type, Real *out, void *ctx, Int flag)` - `__thiscall`,
#: `ret 0x10`. It returns at its own holder guard without writing through `out` when the object
#: has never been modified, which is why the stub seeds the slot itself.
GET_MODIFIER_MULTIPLIER = 0x0068C82D

#: The keyword, overridable so a mod that already uses this name can pick another.
DEFAULT_KEYWORD = "EXPERIENCE_AWARD"

#: Byte windows the patch depends on. Three are its own - the function being wrapped and the code
#: around each of its two calls - and the rest are the modifier system's, shared with every patch
#: that appends a type.
ANCHORS: dict[int, bytes] = {
    # `getExperienceValue` whole: `this` kept in `esi`, the owner at `+0x34` handed to the
    # relationship test, the allied-killer zero, the award at `+0x14`, `ret 8`
    GET_EXPERIENCE_VALUE: bytes.fromhex(
        "568bf1ff76348b4c240ce8c105efff83f802750b807c240c00750433c0eb038b46145ec20800"
    ),
    # the kill-scoring routine from its argument push to the killer's own `EXPERIENCE` (type 6)
    # fold: the call, the Int -> Real conversion that consumes `eax`, and the share scalar
    0x006954AB: bytes.fromhex(
        "ff750c8b8f6c02000056e8217d1000f30f2ac0f30f594510f30f114508f30f10050819bd008bcef30f11450c"
        "e8ca6fffff85c074246a016a008d4d0c516a068bc8e80efb160084c0740ff30f10450cf30f594508"
        "f30f114508"
    ),
    # the player-side award: the victim's tracker loaded from `[esi+0x26c]`, the call, the same
    # conversion, and the `> 0` test that makes a zero award a no-op
    0x006AB07A: bytes.fromhex(
        "8b8e6c0200006a0057e853210f00f30f2ac0f30f5945100f2f0594b5c100f30f11450c"
    ),
    **modifier_types.ANCHORS,
}

SECTION_NAME = ".xpawrd"  # 7 chars: the PE name field is 8 bytes and truncates silently
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ - the rebuilt name table and the stub
# that reads its index share one section.
SECTION_CHARACTERISTICS = name_tables.SECTION_CHARACTERISTICS

_CALL_WIDTH = 5
_ONE_F = struct.pack("<f", 1.0)

# x86 condition codes, as `Asm.jcc_short` takes them.
_JE = 0x4
_JNS = 0x9
_JLE = 0xE


def build_stub(base_va: int, type_index: int) -> bytes:
    """The wrapper both call sites reach instead of `getExperienceValue`, with its contract:
    `__thiscall` on the victim's tracker, two stack arguments, `ret 8`, the award in `eax`.

    It forwards both arguments to the stock function, and when that answers a positive award
    multiplies it by the owner's modifier, truncating back to the `Int` the callers convert. A
    zero award skips the query, so an allied kill stays exactly as stock. A negative product is
    clamped to zero: neither caller is written to take experience away.

    `esi` is saved and restored as the stock function does; `eax`, `ecx`, `edx` and `xmm0` are
    the callee's to clobber under the same convention, and both callers load `xmm0` from `eax`
    on the instruction after the call.
    """
    a = Asm(base_va)
    a.emit(0x56)  # push esi
    a.emit(b"\x8b\xf1")  # mov  esi, ecx              ; the victim's tracker
    a.emit(b"\xff\x74\x24\x0c")  # push [esp+0xc]     ; evenFromAllies
    a.emit(b"\xff\x74\x24\x0c")  # push [esp+0xc]     ; killer, one push further down
    a.call_absolute(GET_EXPERIENCE_VALUE)  # ret 8, `ecx` still the tracker
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(_JLE, "done")  # nothing to scale
    a.emit(b"\x8b\x4e", TRACKER_OWNER_OFFSET)  # mov ecx, [esi+0x34] ; the victim
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc_short(_JE, "done")
    a.emit(0x50)  # push eax                          ; the award, kept across the query
    a.emit(0x68, _ONE_F)  # push 1.0                  ; the out slot, seeded
    a.emit(b"\x6a\x01")  # push 1                     ; flag, as every stock site passes
    a.emit(b"\x6a\x00")  # push 0                     ; no ctx
    a.emit(b"\x8d\x54\x24\x08")  # lea  edx, [esp+8]  ; &out, two pushes below
    a.emit(0x52)  # push edx
    a.emit(modifier_types.push_type(type_index))
    a.call_absolute(GET_MODIFIER_MULTIPLIER)  # ret 0x10: it cleans all four arguments
    a.emit(b"\xf3\x0f\x2a\x44\x24\x04")  # cvtsi2ss xmm0, [esp+4]
    a.emit(b"\xf3\x0f\x59\x04\x24")  # mulss xmm0, [esp]
    a.emit(b"\xf3\x0f\x2c\xc0")  # cvttss2si eax, xmm0
    a.emit(b"\x83\xc4\x08")  # add  esp, 8
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc_short(_JNS, "done")
    a.emit(b"\x33\xc0")  # xor  eax, eax
    a.label("done")
    a.emit(0x5E)  # pop  esi
    a.emit(b"\xc2\x08\x00")  # ret  8
    return a.finish()


def build_section(
    base_va: int, existing_pointers: list[int], keyword: str
) -> tuple[bytes, int, int]:
    """`(section content, rebuilt table VA, stub VA)` for a cave based at `base_va`.

    Table first, so `ExperienceAwardPatch.verify` finds it at the section base without knowing
    how long the stub is, then the keyword string it points at, then the stub."""
    table, _name_vas, stub_va = name_tables.layout(existing_pointers, [keyword], base_va)
    return table + build_stub(stub_va, len(existing_pointers)), base_va, stub_va


class ExperienceAwardPatch(Patch):
    """A `ModifierList` keyword that scales the experience its holder grants when killed."""

    name = "experience-award"
    author = "officialNecro"
    description = (
        "an EXPERIENCE_AWARD ModifierType: name it on a ModifierList's Modifier line and the "
        "experience that object grants when it is killed is multiplied by it - 50% is half, 200% "
        "is double, 0% is nothing. Scales both what the killer earns and what the killing player "
        "is credited. Nothing changes until INI uses the name; needs no .str/.csf key and no map "
        "data"
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
        edits = self._call_edits(data, stub_va)
        edits += modifier_types.relocation_edits(data, table, table_va)
        for file_off, old, new, note in edits:
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that `data` carries this patch (an empty list == verified).

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
            edits = self._call_edits(data, stub_va)
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

        for file_off, _old, new, note in edits:
            found = bytes(data[file_off : file_off + len(new)])
            if found != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {found.hex()}")

        problems += self._live_table_problems(data, len(existing))
        problems += self._anchor_problems(data, patched=True)
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> ExperienceAwardPatch | None:
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
    def from_cli_args(cls, args: argparse.Namespace) -> ExperienceAwardPatch:
        return cls(keyword=args.keyword)

    @staticmethod
    def _call_edits(data: bytes | bytearray, stub_va: int) -> list[tuple[int, bytes, bytes, str]]:
        """The two `call rel32` operands this patch rewrites in `.text`, one per caller."""
        edits = []
        for call_va, feeds in CALL_SITES:
            off = va_to_offset(data, call_va)
            if off is None:
                raise ValueError(f"the experience call at 0x{call_va:08x} is not mapped")
            edits.append(
                (
                    off,
                    call_rel32(call_va, GET_EXPERIENCE_VALUE),
                    call_rel32(call_va, stub_va),
                    f"getExperienceValue for {feeds} -> experience-award stub",
                )
            )
        return edits

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

        `patched` blanks the two calls this patch rewrites. The two modifier-table operands are
        blanked unconditionally: any type-appending patch owns them, so their value says nothing
        about this one either way, and `modifier_types.read` checks what they point at far
        more tightly than a byte compare would."""
        blank = list(modifier_types.VOLATILE_SPANS)
        if patched:
            blank += [(call_va, _CALL_WIDTH) for call_va, _feeds in CALL_SITES]

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
            raise ValueError(f"experience-award: this is not the expected build: {joined}")


#: The PE section name field is 8 bytes and truncates silently.
WORLDBUILDER_SECTION_NAME = ".wbxpaw"

# CNT_INITIALIZED_DATA | MEM_READ - a pointer table and one string, no code.
_WORLDBUILDER_CHARACTERISTICS = 0x40000040


class ExperienceAwardWorldbuilderPatch(Patch):
    """Teach **Worldbuilder** the `EXPERIENCE_AWARD` modifier type.

    **This patch targets `Worldbuilder.exe`, not `game.dat`.** It is the authoring half of
    `experience-award`: the editor resolves `Modifier = <ModifierType> <value>` through its own
    copy of the name table, and a token that copy does not hold throws during INI load and ends
    the editor. Give both binaries the same name.

    Parsing only - the editor awards no experience and needs no behaviour.
    """

    name = "experience-award-wb"
    author = "officialNecro"
    description = (
        "Worldbuilder.exe (not game.dat): add the EXPERIENCE_AWARD ModifierType name to the "
        "editor's own name table, so attribute modifiers using it parse instead of throwing on an "
        "unknown token and ending the editor's load. Pass the same name given to game.dat's "
        "experience-award; the editor gains no behaviour, only the ability to read it"
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
    def detect(cls, data: bytes | bytearray) -> ExperienceAwardWorldbuilderPatch | None:
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
    def from_cli_args(cls, args: argparse.Namespace) -> ExperienceAwardWorldbuilderPatch:
        return cls(keyword=args.keyword)
