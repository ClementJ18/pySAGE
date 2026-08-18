"""The trigger-recharge list: `OnTriggerRechargeSpecialPower` takes several powers, not one.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/trigger-recharge-list.md``.

**What the engine does today.** `OnTriggerRechargeSpecialPower` - the keyword behind every
"using this ability also puts that one on cooldown" design - writes one `AsciiString` at
``ModuleData+0x6c``, and on activation the object's module array is walked and
``startPowerRecharge(1.0)`` called on the single module whose `SpecialPowerTemplate` carries that
name. Note the direction: "recharge" is the engine's word for **arming** the cooldown, not
clearing it, so the named power comes out as if it had just been cast.

Both the keyword and the walk belong to `SpecialAbilityUpdate`, not to one module: the field-parse
table at ``0x00C64DB0`` and `doSpecialPower` at ``0x00897987`` are shared by all **23**
special-power modules (`PlayerHealSpecialPower`, `OCLSpecialPower`, ...), so this patch changes
behaviour for every one of them.

It is already a name-matched special-power selector; what it is not is a *list*. A hero whose
ability should start two cooldowns needs two `SpecialPowerTimerRefreshSpecialPower` modules, each
with its own `SpecialPowerTemplate` to hang off - and there is only one power being used, so the
second module has nothing honest to point at.

**What this does.** Makes the same keyword take **any number of names on the line**:

.. code-block:: none

    OnTriggerRechargeSpecialPower = SpecialAbilityLeadership SpecialAbilityWarChant

Two edits, no cave allocation beyond the code itself, no structure growth, no constructor or
destructor change:

* **The keyword.** The field-parse table entry's parse function - stock `INI::parseAsciiString`,
  which stores the *first* token and drops the rest - is repointed at a cave routine that
  consumes every token on the line and stores them joined by single spaces. One ``imm32`` in
  ``.rdata``; the entry itself, its name pointer and its ``ModuleData`` offset are untouched.
* **The test.** The ``call`` to `AsciiString::compare` inside the module-walk loop is repointed at
  a cave routine that asks whether the candidate's power name is *one of the tokens* in that
  string, rather than whether it is the whole of it.

**Why the field does not grow.** An `AsciiString` is one pointer to a refcounted buffer, so the
four bytes at ``+0x6c`` already hold a string of any length; a list of names is a string. That is
what keeps this off the expensive path the other module-data patches take - no
``sizeof(ModuleData)`` literal to raise, no relocated field-parse table, no ctor shim to
default-construct a new member, and nothing for a savegame or a network peer to disagree about
that was not already there.

**A single name behaves exactly as it does today.** The parse joins one token to itself, so the
stored string is byte-for-byte what stock stored, and the walk's matcher accepts a one-token list
on exactly the names `AsciiString::compare` accepted. That also settles the *other* comparison in
this function, the one at `OWN_POWER_COMPARE_VA` that short-circuits the walk when the field names
the module's own power: a one-name list still compares equal to that name as a whole string, so
the early-out survives untouched and is left unpatched. A list of two never equals a single
template name - names cannot contain a space - so a list that happens to include the module's own
power reaches the walk and is recharged there, which is what naming it in a list asks for.

**Scope of the parse change.** The table at `FIELD_TABLE_VA` is `SpecialAbilityUpdate`'s, shared
by all 23 special-power modules, so all of them now parse the keyword as a list. Only
`SpecialPowerTimerRefreshSpecialPower` ever reads the field, so for the other 22 the change is the
difference between storing one token and storing all of them into a string nothing looks at.

**Composition.** Order-independent: the cave is allocated with
:func:`~..utils.allocate_section` past every existing section and :meth:`verify` finds it by name.
The two bytes ranges it rewrites - one parse-function slot, one ``call`` - are touched by no other
bundled patch, and it reads no structure another patch rebuilds. Note in particular that
`player-heal-filter` *reads* this same table (to reject a keyword it would shadow) and does not
write it, so the two compose in either order.

Quoted values
-------------
`INI::getNextAsciiString` is what both the stock parser and this one pull tokens with, so a
quoted value still arrives as one token, spaces and all - ``"Foo Bar"`` stores ``Foo Bar``. The
matcher then splits it back into two names that no template can be called. This is not a
regression: a `SpecialPower` block's name is a single INI token, so a quoted value never matched
anything under the stock compare either.

Determinism
-----------
Both routines are pure functions of `ModuleData` written at INI-parse time and of a template
name, run on the logic thread inside `doSpecialPower`. Nothing new enters the frame or the CRC -
but the *outcome* does change which powers get recharged, so this is a rule change like any
other: **every peer must run the same patched binary**, and a mod that writes a two-name value
needs it or the second name is silently dropped.
"""

from __future__ import annotations

import struct

from sage_ini.engine import Engine, FieldDelta

from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset
from .utils.field_tables import resolve_table
from .utils.token_lists import (
    ASCII_STRING_CHARS,
    SEPARATOR,
    STOCK_ASCII_STRING_PARSER,
    build_list_parser,
)

__all__ = [
    "ANCHORS",
    "ASCII_STRING_COMPARE",
    "FIELD_ENTRY_SIZE",
    "FIELD_INDEX",
    "FIELD_NAME",
    "FIELD_OFFSET",
    "FIELD_TABLE_REF_VA",
    "FIELD_TABLE_VA",
    "MATCH_CALL_VA",
    "OWN_POWER_COMPARE_VA",
    "SECTION_NAME",
    "TriggerRechargeListPatch",
    "build_match",
]

#: `SpecialAbilityUpdate`'s 35-entry field-parse table - the one every special-power module adds
#: to its `MultiIniFieldParse` - and the entry this patch repoints. The entry is fingerprinted by
#: name and `ModuleData` offset before anything is written, which is a far stronger build check
#: than the index alone.
#:
#: The base is taken from `FIELD_TABLE_REF_VA`, the ``push imm32`` inside `buildFieldParse` that
#: is the table's **only** reference in the image, rather than from the stock constant - so a
#: patch that relocated the table first would be found rather than silently bypassed. `..._VA` is
#: what that reference holds on a stock build.
FIELD_TABLE_VA = 0x00C64DB0
FIELD_TABLE_REF_VA = 0x008969A1
FIELD_ENTRY_SIZE = 16
FIELD_INDEX = 31
FIELD_NAME = "OnTriggerRechargeSpecialPower"
FIELD_OFFSET = 0x6C

#: The ``call`` inside `SpecialPowerTimerRefreshSpecialPower::doSpecialPower`'s module walk that
#: asks whether a candidate module's power is *the* named one, and the `AsciiString::compare` it
#: calls: ``__thiscall(ecx = &name, [esp+4] = &field)``, ``ret 4``, ``eax == 0`` means equal.
MATCH_CALL_VA = 0x00897A21
ASCII_STRING_COMPARE = 0x004065AA

#: The other comparison in the same function - the early-out that skips the walk when the field
#: names the module's own power. **Deliberately not patched**; asserted so that the reasoning
#: about it in this module's docstring stays true of the binary being written.
OWN_POWER_COMPARE_VA = 0x008979E1

#: Sites this patch depends on and does not itself rewrite. Nothing else would catch a mismatch -
#: the cave would simply read the wrong register or answer for the wrong field - so each is
#: asserted before anything is written, and again by :meth:`~TriggerRechargeListPatch.verify`.
ANCHORS = (
    (0x008979C5, b"\x8d\x73\x6c", "lea esi, [ebx+0x6c] (the field, read for its emptiness)"),
    (
        OWN_POWER_COMPARE_VA,
        b"\xe8" + struct.pack("<i", ASCII_STRING_COMPARE - (OWN_POWER_COMPARE_VA + 5)),
        "the own-power early-out's whole-string compare",
    ),
    (0x00897A18, b"\x8d\x4b\x6c", "lea ecx, [ebx+0x6c] (the field, as the walk's argument)"),
    (0x00897A1B, b"\x83\xc0\x10", "add eax, 0x10 (the candidate template's name)"),
    (0x00897A1E, b"\x51\x8b\xc8", "push ecx / mov ecx, eax (the two arguments)"),
)

SECTION_NAME = ".trglst"
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ. The cave is two routines and no data;
# nothing writes into it, so it needs no MEM_WRITE.
SECTION_CHARACTERISTICS = 0x60000060


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _call_bytes(from_va: int, to_va: int) -> bytes:
    """The five bytes of ``call rel32`` sited at ``from_va``."""
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


def build_match(base_va: int) -> bytes:
    """Is the candidate's power name one of the tokens in the field?

    Stands in for `AsciiString::compare` at exactly its call site, so it takes that function's
    arguments and answers in its convention: ``__thiscall`` with ``ecx`` the candidate template's
    name and ``[esp+4]`` the field, ``ret 4``, and **``eax == 0`` means match** - which is what
    the caller's existing ``test eax,eax / jne`` reads.

    The comparison is byte-for-byte and case-sensitive, the same as the `memcmp` the function it
    replaces ends in: a `SpecialPower` name that differs in case did not match before this patch
    either.

    ``ebx``, ``esi`` and ``edi`` are preserved because the loop this sits inside keeps its module
    cursor, its module and its `ModuleData` in them, exactly as the ``__thiscall`` being replaced
    did."""
    a = Asm(base_va)
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    a.emit(0x53)  # push ebx

    a.emit(b"\x8b\x01")  # mov eax, [ecx]         ; the name's buffer
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "no")  # je .no                 ; an unnamed template matches nothing
    a.emit(b"\x8d\x78", bytes([ASCII_STRING_CHARS]))  # lea edi, [eax+8]  ; the name

    a.emit(b"\x8b\x44\x24\x10")  # mov eax, [esp+0x10]    ; the field (past three pushes)
    a.emit(b"\x8b\x00")  # mov eax, [eax]         ; its buffer
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "no")  # je .no                 ; an empty list matches nothing
    a.emit(b"\x8d\x70", bytes([ASCII_STRING_CHARS]))  # lea esi, [eax+8]  ; the list

    a.label("token")  # skip the separators before a token
    a.emit(b"\x8a\x06")  # mov al, [esi]
    a.emit(b"\x3c", bytes([SEPARATOR]))  # cmp al, ' '
    a.jcc(JNE, "compare")  # jne .compare
    a.emit(0x46)  # inc esi
    a.jmp("token")  # jmp .token

    a.label("compare")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "no")  # je .no                 ; end of the list
    a.emit(b"\x8b\xdf")  # mov ebx, edi           ; restart the name

    a.label("chars")
    a.emit(b"\x8a\x06")  # mov al, [esi]
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "ended")  # je .ended
    a.emit(b"\x3c", bytes([SEPARATOR]))  # cmp al, ' '
    a.jcc(JE, "ended")  # je .ended
    a.emit(b"\x8a\x13")  # mov dl, [ebx]
    a.emit(b"\x3a\xc2")  # cmp al, dl
    a.jcc(JNE, "skip")  # jne .skip
    a.emit(0x46)  # inc esi
    a.emit(0x43)  # inc ebx
    a.jmp("chars")  # jmp .chars

    a.label("ended")  # the token ended - a match iff the name did too
    a.emit(b"\x80\x3b\x00")  # cmp byte [ebx], 0
    a.jcc(JE, "yes")  # je .yes

    a.label("skip")  # run to the end of this token and try the next
    a.emit(b"\x8a\x06")  # mov al, [esi]
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "no")  # je .no
    a.emit(b"\x3c", bytes([SEPARATOR]))  # cmp al, ' '
    a.jcc(JE, "token")  # je .token
    a.emit(0x46)  # inc esi
    a.jmp("skip")  # jmp .skip

    a.label("yes")
    a.emit(b"\x33\xc0")  # xor eax, eax           ; 0 == "equal", as compare says it
    a.jmp("out")  # jmp .out

    a.label("no")
    a.emit(b"\x33\xc0")  # xor eax, eax
    a.emit(0x40)  # inc eax

    a.label("out")
    a.emit(0x5B)  # pop ebx
    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi
    a.emit(b"\xc2\x04\x00")  # ret 4
    return a.finish()


class TriggerRechargeListPatch(Patch):
    """Let `OnTriggerRechargeSpecialPower` name several special powers instead of one."""

    name = "trigger-recharge-list"
    author = "officialNecro"
    description = "OnTriggerRechargeSpecialPower takes a list of special powers, not just one"

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        self._check_field_entry(data)
        section_va = allocate_section(
            data,
            SECTION_NAME,
            lambda va: self._compute_section(va)[0],
            SECTION_CHARACTERISTICS,
        )
        # The layout is a pure function of the base VA, so re-deriving it costs nothing and keeps
        # the callable above a plain bytes-returning one.
        _content, stubs = self._compute_section(section_va)
        for file_off, old, new, note in self._edits(data, stubs):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch (an empty list == verified). Locates
        the cave, recomputes the two routines its base VA implies, and compares them and both
        repointed sites to what is on disk. Reads only via ``struct`` and the section table, so
        verification needs no disassembler."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located

        problems: list[str] = []
        try:
            content, stubs = self._compute_section(section_va)
            edits = self._edits(data, stubs)
        except (ValueError, struct.error) as exc:
            return [f"cannot recompute the expected cave (wrong build?): {exc}"]

        got = bytes(data[section_off : section_off + len(content)])
        if got != content:
            problems.append(f"{SECTION_NAME} does not hold the expected parse and match routines")

        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")

        try:
            self._check_anchors(data)
            self._check_field_entry(data, patched=True)
        except ValueError as exc:
            problems.append(str(exc))
        return problems

    def ini_surface(self) -> Engine:
        """The keyword's new type, declared on the base every special-power module derives from -
        which mirrors the binary, where all 23 of them read the one shared field-parse table.

        The default is unchanged and unstated: an absent keyword leaves the field empty, and an
        empty field is what makes the whole walk a no-op."""
        return Engine(
            fields=(
                FieldDelta(
                    "SpecialPowerModuleBehavior",
                    FIELD_NAME,
                    "Ref[]:specialpowers",
                    None,
                    self.name,
                ),
            )
        )

    def _compute_section(self, section_va: int) -> tuple[bytes, tuple[int, int]]:
        """Return ``(section content, (parse VA, match VA))`` for a cave based at ``section_va``.

        Layout: the parse routine, then the matcher. Neither refers to the other, so the order is
        arbitrary - but it has to be *fixed*, because `verify` recomputes both from the section's
        base address alone."""
        parse = build_list_parser(section_va)
        match_va = section_va + len(parse)
        match = build_match(match_va)
        return parse + match, (section_va, match_va)

    def _field_entry(self, data: bytes | bytearray) -> tuple[int, tuple[int, int, int, int]]:
        """The `OnTriggerRechargeSpecialPower` table entry, as ``(file offset, fields)``.

        The table's base is read from the reference that names it rather than from
        `FIELD_TABLE_VA`, so a patch that relocated the table into a cave first is followed
        instead of bypassed - the failure that repointing the stock copy would otherwise cause is
        silent, because the stale table still holds the bytes this one asserts."""
        base_va = resolve_table(data, (FIELD_TABLE_REF_VA,), (0x68,), "SpecialAbilityUpdate")
        entry_va = base_va + FIELD_INDEX * FIELD_ENTRY_SIZE
        off = va_to_offset(data, entry_va)
        if off is None:
            raise ValueError(f"the field table entry at 0x{entry_va:08x} is not mapped")
        name_va, parse_fn, userdata, field_off = struct.unpack_from("<4I", data, off)
        return off, (name_va, parse_fn, userdata, field_off)

    def _check_field_entry(self, data: bytes | bytearray, patched: bool = False) -> None:
        """Assert the entry being repointed is the keyword's, in this build's table.

        The index alone is not evidence: it is the name and the `ModuleData` offset that say the
        four bytes about to be rewritten are the parse function of the field the matcher reads.
        ``patched`` says which parse function to expect - the stock one before the write, anything
        but the stock one after it, since where the cave landed is `verify`'s business."""
        off, (name_va, parse_fn, _userdata, field_off) = self._field_entry(data)
        name_off = va_to_offset(data, name_va)
        name = None
        if name_off is not None:
            end = bytes(data[name_off : name_off + len(FIELD_NAME) + 1]).find(b"\x00")
            if end >= 0:
                name = bytes(data[name_off : name_off + end]).decode("latin1")
        if name != FIELD_NAME:
            raise ValueError(
                f"field table entry {FIELD_INDEX} is {name!r}, not {FIELD_NAME!r} - this is not "
                f"the expected build"
            )
        if field_off != FIELD_OFFSET:
            raise ValueError(
                f"{FIELD_NAME} is parsed into ModuleData+0x{field_off:x}, not "
                f"0x{FIELD_OFFSET:x} - the matcher would read another field"
            )
        if not patched and parse_fn != STOCK_ASCII_STRING_PARSER:
            raise ValueError(
                f"{FIELD_NAME} parses with 0x{parse_fn:08x}, not the stock "
                f"0x{STOCK_ASCII_STRING_PARSER:08x} - the file is already patched, or is "
                f"another build"
            )

    def _check_anchors(self, data: bytes | bytearray) -> None:
        for va, expected, what in ANCHORS:
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{what}: VA 0x{va:08x} is not mapped")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"{what} @0x{va:08x}: expected {expected.hex()}, got {got.hex()} - this is "
                    f"not the expected build"
                )

    def _edits(
        self, data: bytes | bytearray, stubs: tuple[int, int]
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte range this patch rewrites, as ``(file offset, old, new, note)``."""
        parse_va, match_va = stubs
        entry_off, _fields = self._field_entry(data)

        call_off = va_to_offset(data, MATCH_CALL_VA)
        if call_off is None:
            raise ValueError(f"the walk's compare at 0x{MATCH_CALL_VA:08x} is not mapped")

        return [
            (
                entry_off + 4,
                _u32(STOCK_ASCII_STRING_PARSER),
                _u32(parse_va),
                f"{FIELD_NAME} parse function -> cave",
            ),
            (
                call_off,
                _call_bytes(MATCH_CALL_VA, ASCII_STRING_COMPARE),
                _call_bytes(MATCH_CALL_VA, match_va),
                "the module walk's name compare -> cave",
            ),
        ]
