"""The upgrade grant/remove lists: `ObjectCreationUpgrade` swaps **sets** of upgrades, not one each.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is
derived in ``../docs/upgrade-grant-lists.md``.

**What the engine does today.** `ObjectCreationUpgrade` is the module that fires when an object
gains an upgrade: it spawns its `UpgradeObject`, and then - once, at the end of the same function
- grants the single upgrade named by `GrantUpgrade` and removes the single one named by
`RemoveUpgrade`. Both are `AsciiString`s (`ModuleData+0x144` and `+0x140`), both are looked up in
`TheUpgradeCenter` by name at the moment they are used, and both name exactly one upgrade.

One is not enough for the thing this module is normally used for. An upgrade that supersedes a
tier wants the tiers below it gone, and a "the tech is now this" swap wants a set granted; today
that means either a chain of `ObjectCreationUpgrade`s, each with its own `TriggeredBy` bookkeeping
to make it fire, or an `Upgrade` object per combination.

**What this does.** Makes both keywords take **any number of names on the line**:

.. code-block:: none

    RemoveUpgrade = Upgrade_TierOne Upgrade_TierTwo
    GrantUpgrade  = Upgrade_TierThree Upgrade_Banner

Four edits, no structure growth, no constructor or destructor change:

* **The keywords.** The two entries' parse function - stock `INI::parseAsciiString`, which stores
  the *first* token and drops the rest - is repointed at the shared list parser in
  :mod:`.utils.token_lists`, which consumes every token on the line and stores them joined by
  single spaces. Two ``imm32``s; the entries' name pointers and `ModuleData` offsets are untouched,
  and the third `AsciiString` in the same table (`ThingToSpawn`) is deliberately left alone.
* **The two uses.** Each `UpgradeCenter::findUpgrade` call is repointed at a cave routine that
  walks the tokens, looks each one up and applies it, then returns **NULL** - which the caller's
  own ``test eax,eax / je`` reads as "no upgrade found" and skips its single-upgrade call. The
  stock give/remove path is therefore not deleted, it is simply never taken, and the bytes that
  make that true are asserted rather than assumed.

**Why the fields do not grow.** An `AsciiString` is one pointer to a refcounted buffer, so a list
of names is just a longer string - the same reason `trigger-recharge-list` is cheap, spelled out
in :mod:`.utils.token_lists`. `ObjectCreationUpgrade`'s `ModuleData` stays `0x174` bytes.

**A single name behaves exactly as it does today.** The parser stores one token byte-for-byte as
stock stored it, and the cave then looks up that one name and applies it to the same object
through the same two engine calls. An empty field skips the whole loop, exactly as the stock
NULL from `findUpgrade` skipped the call.

**Order.** Grants happen before removals, which is the stock order and is worth stating because
the two lists can now overlap: naming the same upgrade in both leaves the object without it.
Within a list, names are applied left to right.

Where the object comes from
---------------------------
The cave needs the `Object` to apply an upgrade to, and takes it the way the code it replaces
does: ``[edi-8]``, the `Object` behind the module interface `edi` holds. Three paths reach this
block - the fallthrough, which sets ``edi`` to the interface returned by `0x0068C327`, and two
jumps that arrive with the module's own ``edi`` untouched - and all three agree, because
`0x0068C327` walks ``Object+0x24C``, the module array of *that same object*, so both interfaces
sit on it. `ANCHORS` pins every instruction that argument depends on.

Composition
-----------
Order-independent. The cave is allocated with :func:`~..utils.allocate_section` past every
existing section and :meth:`verify` finds it by name; the four byte ranges it rewrites are touched
by no other bundled patch; and the field table is located through the reference that names it
(:func:`~.utils.field_tables.resolve_table`) rather than by its stock address, so a patch that
relocated it first would be followed rather than bypassed.
"""

from __future__ import annotations

import struct

from sage_ini.engine import Engine, FieldDelta

from ..addresses import THE_UPGRADE_CENTER
from ..asm import JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset
from .utils.field_tables import ROW_SIZE, read_field_table, resolve_table
from .utils.token_lists import (
    ASCII_STRING_CHARS,
    ASCII_STRING_DTOR,
    ASCII_STRING_SET,
    SEPARATOR,
    STOCK_ASCII_STRING_PARSER,
    build_list_parser,
)

__all__ = [
    "ANCHORS",
    "FIELDS",
    "FIELD_TABLE_REF_VA",
    "FIELD_TABLE_VA",
    "FIND_UPGRADE",
    "GRANT_CALL_VA",
    "MAX_NAME",
    "OBJECT_GIVE_UPGRADE",
    "OBJECT_REMOVE_UPGRADE",
    "REMOVE_CALL_VA",
    "SECTION_NAME",
    "STOCK_GRANT_CALL_VA",
    "STOCK_REMOVE_CALL_VA",
    "UpgradeGrantListsPatch",
    "build_apply",
]

#: `ObjectCreationUpgrade`'s own 11-entry field-parse table, and the ``push imm32`` inside its
#: `buildFieldParse` that is the table's **only** reference in the image. The base is taken from
#: the reference rather than from the constant, so a patch that relocated the table first is
#: followed instead of bypassed; `..._VA` is what that reference holds on a stock build.
FIELD_TABLE_VA = 0x00C6E2F8
FIELD_TABLE_REF_VA = 0x008B8205

#: The two keywords this patch re-types, as ``(name, ModuleData offset)``. Located in the table
#: **by name**, with the offset checked against this - which is what says the entry being
#: repointed is the one the code at `GRANT_CALL_VA` / `REMOVE_CALL_VA` reads.
#:
#: `ThingToSpawn`, the third `AsciiString` in the same table, is not here on purpose: it names an
#: object template rather than an upgrade, and the single spawn it drives is a different feature.
FIELDS = (
    ("RemoveUpgrade", 0x140),
    ("GrantUpgrade", 0x144),
)

#: `UpgradeCenter::findUpgrade(const AsciiString &)` - ``__thiscall`` on the center, ``ret 4``,
#: NULL when no upgrade has that name. It keys through `TheNameKeyGenerator`, so the lookup cost
#: is a name-key hash and a list walk, not a string compare per upgrade.
FIND_UPGRADE = 0x0066F5E5

#: `Object::giveUpgrade(UpgradeTemplate *)` and `Object::removeUpgrade(UpgradeTemplate *)` - both
#: ``__thiscall``, ``ret 4``. These are the calls the stock code makes with the one template it
#: found, and the cave makes them per name rather than replacing them.
OBJECT_GIVE_UPGRADE = 0x0069388B
OBJECT_REMOVE_UPGRADE = 0x00691438

#: The two `findUpgrade` calls inside `ObjectCreationUpgrade`'s upgrade step - the only two in the
#: module - and what each one's result is used for.
GRANT_CALL_VA = 0x008B871A
REMOVE_CALL_VA = 0x008B8739

#: The two calls the stock code makes with the one template it found. They are **not** rewritten:
#: the cave's NULL return steers the ``je`` just before each of them, so they stay in the binary
#: and stop being reached. Asserted all the same, because "the caller skips its own call" is only
#: true if these are the calls - a build that had them the other way round would grant what it
#: was told to remove.
STOCK_GRANT_CALL_VA = 0x008B8727
STOCK_REMOVE_CALL_VA = 0x008B8746

#: The longest name the cave will look up. Tokens are copied into a frame buffer to be
#: NUL-terminated, and this bounds it; a longer token is truncated, which simply fails the lookup.
#: No real upgrade name comes close: the longest one Edain declares is 46 characters.
MAX_NAME = 0xFF


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _call_bytes(from_va: int, to_va: int) -> bytes:
    """The five bytes of ``call rel32`` sited at ``from_va``."""
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


#: Sites this patch depends on and does not itself rewrite: the registers the cave reads, the
#: ``test eax,eax / je`` that its NULL return steers, and the two calls it stands in front of.
#: Nothing else would catch a mismatch - the cave would apply upgrades to whatever ``[edi-8]``
#: happened to hold - so each is asserted before anything is written, and again by
#: :meth:`~UpgradeGrantListsPatch.verify`.
ANCHORS = (
    (
        0x0068C328,
        b"\x8b\xb1\x4c\x02\x00\x00",
        "mov esi, [ecx+0x24c] (the interface search walks the same object's modules)",
    ),
    (
        0x008B84C8,
        b"\x8b\x4f\xf8\x6a\x00",
        "mov ecx, [edi-8] / push 0 (edi is the module interface, [edi-8] its Object)",
    ),
    (
        0x008B84D2,
        b"\x85\xc0\x89\x45\xf0\x0f\x84\x30\x02\x00\x00",
        "the no-interface path into the upgrade step, with edi left as the module's",
    ),
    (
        0x008B84FD,
        b"\x0f\x85\x0a\x02\x00\x00",
        "the second path into the upgrade step, with edi left as the module's",
    ),
    (
        0x008B870A,
        b"\x8b\x7d\xf0\x8b\x0d\xa0\x45\xde\x00\x8d\x83\x44\x01\x00\x00\x50",
        "mov edi, [ebp-0x10] / TheUpgradeCenter / lea eax, [ebx+0x144] / push (the grant lookup)",
    ),
    (
        0x008B871F,
        b"\x85\xc0\x74\x09\x8b\x4f\xf8\x50" + _call_bytes(STOCK_GRANT_CALL_VA, OBJECT_GIVE_UPGRADE),
        "test eax,eax / je / mov ecx, [edi-8] / push / call giveUpgrade (the stock single grant)",
    ),
    (
        0x008B872C,
        b"\x8b\x0d\xa0\x45\xde\x00\x81\xc3\x40\x01\x00\x00\x53",
        "TheUpgradeCenter / add ebx, 0x140 / push (the removal lookup)",
    ),
    (
        0x008B873E,
        b"\x85\xc0\x74\x09\x8b\x4f\xf8\x50"
        + _call_bytes(STOCK_REMOVE_CALL_VA, OBJECT_REMOVE_UPGRADE),
        "test eax,eax / je / mov ecx, [edi-8] / push / call removeUpgrade (the stock removal)",
    ),
)

SECTION_NAME = ".upglst"
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ. The cave is three routines and no
# data - the token buffer lives in the cave routine's own frame - so it needs no MEM_WRITE.
SECTION_CHARACTERISTICS = 0x60000060


def _read_cstring(data: bytes | bytearray, va: int, limit: int = 64) -> str | None:
    off = va_to_offset(data, va)
    if off is None:
        return None
    end = bytes(data[off : off + limit]).find(b"\x00")
    return None if end < 0 else bytes(data[off : off + end]).decode("latin1")


def build_apply(base_va: int, action_va: int) -> bytes:
    """Apply ``action_va`` to every upgrade named in the list, then answer "nothing found".

    Stands in for `UpgradeCenter::findUpgrade` at its call site, so it takes that function's
    arguments and answers in its convention: ``[esp+4]`` the `AsciiString` field, ``ret 4``, and
    ``eax`` the `UpgradeTemplate` the caller would then apply. It always returns **NULL**, so the
    caller's existing ``test eax,eax / je`` skips its own single-upgrade call - the work has
    already been done here, once per name.

    ``ecx`` is ignored on entry and `TheUpgradeCenter` re-read from its global instead, which
    costs six bytes and removes a dependency on what the caller happened to leave in a register.
    The `Object` is taken from ``[edi-8]`` **before** anything else, because the copy loop below
    uses ``edi``; see the module docstring for why that is the object on all three paths in.

    The frame is one `AsciiString` at ``[ebp-4]``, the `Object` at ``[ebp-8]``, and a
    :data:`MAX_NAME`-plus-one byte buffer below them. Tokens are copied into that buffer because
    `findUpgrade` wants a NUL-terminated string and the list's own separator is not one - which is
    also why this cannot simply hand it a pointer into the field.
    """
    buffer = MAX_NAME + 1 + 8  # the buffer, plus the two dword locals above it
    a = Asm(base_va)
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x81\xec", _u32(buffer))  # sub esp, <frame>
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    a.emit(b"\x83\x65\xfc\x00")  # and dword [ebp-4], 0   ; the name, empty
    a.emit(b"\x8b\x47\xf8")  # mov eax, [edi-8]       ; the Object
    a.emit(b"\x89\x45\xf8")  # mov [ebp-8], eax
    a.emit(b"\x8b\x75\x08")  # mov esi, [ebp+8]       ; the AsciiString field
    a.emit(b"\x8b\x36")  # mov esi, [esi]         ; its buffer
    a.emit(b"\x85\xf6")  # test esi, esi
    a.jcc(JE, "done")  # je .done               ; never written: nothing to do
    a.emit(b"\x83\xc6", bytes([ASCII_STRING_CHARS]))  # add esi, 8   ; its characters

    a.label("token")  # skip the separators before a token
    a.emit(b"\x8a\x06")  # mov al, [esi]
    a.emit(b"\x3c", bytes([SEPARATOR]))  # cmp al, ' '
    a.jcc(JNE, "copy_start")  # jne .copy_start
    a.emit(0x46)  # inc esi
    a.jmp("token")  # jmp .token

    a.label("copy_start")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "done")  # je .done               ; end of the list
    a.emit(b"\x8d\xbd", _u32((-(MAX_NAME + 1 + 8)) & 0xFFFFFFFF))  # lea edi, [ebp-<buffer>]
    a.emit(b"\xb9", _u32(MAX_NAME))  # mov ecx, MAX_NAME      ; the copy bound

    a.label("copy")
    a.emit(b"\x8a\x06")  # mov al, [esi]
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "lookup")  # je .lookup
    a.emit(b"\x3c", bytes([SEPARATOR]))  # cmp al, ' '
    a.jcc(JE, "lookup")  # je .lookup
    a.emit(b"\x88\x07")  # mov [edi], al
    a.emit(0x46)  # inc esi
    a.emit(0x47)  # inc edi
    a.emit(0x49)  # dec ecx
    a.jcc(JNE, "copy")  # jne .copy              ; full: take what we have

    a.label("lookup")
    a.emit(b"\xc6\x07\x00")  # mov byte [edi], 0
    a.emit(b"\x8d\x85", _u32((-(MAX_NAME + 1 + 8)) & 0xFFFFFFFF))  # lea eax, [ebp-<buffer>]
    a.emit(0x50)  # push eax
    a.emit(b"\x8d\x4d\xfc")  # lea ecx, [ebp-4]
    a.call_absolute(ASCII_STRING_SET)  # call <AsciiString::set> ; ret 4
    a.emit(b"\x8d\x45\xfc")  # lea eax, [ebp-4]
    a.emit(0x50)  # push eax
    a.emit(b"\x8b\x0d", _u32(THE_UPGRADE_CENTER))  # mov ecx, [TheUpgradeCenter]
    a.call_absolute(FIND_UPGRADE)  # call <findUpgrade>      ; ret 4
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "advance")  # je .advance            ; no such upgrade: skip it
    a.emit(0x50)  # push eax
    a.emit(b"\x8b\x4d\xf8")  # mov ecx, [ebp-8]       ; the Object
    a.call_absolute(action_va)  # call <give/remove>      ; ret 4

    a.label("advance")  # run to the end of this token, then take the next
    a.emit(b"\x8a\x06")  # mov al, [esi]
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "done")  # je .done
    a.emit(b"\x3c", bytes([SEPARATOR]))  # cmp al, ' '
    a.jcc(JE, "token")  # je .token
    a.emit(0x46)  # inc esi
    a.jmp("advance")  # jmp .advance

    a.label("done")
    a.emit(b"\x8d\x4d\xfc")  # lea ecx, [ebp-4]
    a.call_absolute(ASCII_STRING_DTOR)  # call <~AsciiString>
    a.emit(b"\x33\xc0")  # xor eax, eax           ; "no template" - the caller skips its own call
    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi
    a.emit(0xC9)  # leave
    a.emit(b"\xc2\x04\x00")  # ret 4
    return a.finish()


class UpgradeGrantListsPatch(Patch):
    """Let `ObjectCreationUpgrade` grant and remove several upgrades instead of one each."""

    name = "upgrade-grant-lists"
    author = "officialNecro"
    description = (
        "ObjectCreationUpgrade's GrantUpgrade and RemoveUpgrade take lists of upgrades, not "
        "one. Write the upgrade names space-separated on the one line - grants still run before "
        "removals, 255 characters per name - and a mod writing two needs this patch, since a "
        "stock build silently keeps only the first"
    )

    def apply(self, data: bytearray) -> None:
        self._check_anchors(data)
        self._check_field_entries(data)
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
        the cave, recomputes the three routines its base VA implies, and compares them and all
        four repointed sites to what is on disk. Reads only via ``struct`` and the section table,
        so verification needs no disassembler."""
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
            problems.append(f"{SECTION_NAME} does not hold the expected parser and two appliers")

        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")

        try:
            self._check_anchors(data)
            self._check_field_entries(data, patched=True)
        except ValueError as exc:
            problems.append(str(exc))
        return problems

    def ini_surface(self) -> Engine:
        """Both keywords, re-typed as lists of upgrade references. No default is stated: an absent
        keyword leaves the field empty, and an empty field is what makes the loop a no-op."""
        return Engine(
            fields=tuple(
                FieldDelta("ObjectCreationUpgrade", name, "Ref[]:upgrades", None, self.name)
                for name, _offset in FIELDS
            )
        )

    def _compute_section(self, section_va: int) -> tuple[bytes, tuple[int, int, int]]:
        """Return ``(section content, (parse VA, grant VA, remove VA))`` for a cave based at
        ``section_va``.

        Layout: the shared list parser (both keywords point at the one copy), then the granting
        applier, then the removing one. The order is arbitrary but fixed, because `verify`
        recomputes all three from the section's base address alone."""
        parse = build_list_parser(section_va)
        grant_va = section_va + len(parse)
        grant = build_apply(grant_va, OBJECT_GIVE_UPGRADE)
        remove_va = grant_va + len(grant)
        remove = build_apply(remove_va, OBJECT_REMOVE_UPGRADE)
        return parse + grant + remove, (section_va, grant_va, remove_va)

    def _field_entries(self, data: bytes | bytearray) -> list[tuple[int, str, int]]:
        """``(file offset of the entry, keyword, parse function)`` for each of :data:`FIELDS`.

        Located by name in the live table, and cross-checked against the `ModuleData` offset the
        module's code reads - the pair is what says the entry about to be repointed is the field
        the cave walks."""
        base_va = resolve_table(data, (FIELD_TABLE_REF_VA,), (0x68,), "ObjectCreationUpgrade")
        entries = read_field_table(data, base_va)
        names = [_read_cstring(data, entry[0]) for entry in entries]

        found: list[tuple[int, str, int]] = []
        for name, offset in FIELDS:
            if name not in names:
                raise ValueError(
                    f"the ObjectCreationUpgrade field table has no {name!r} entry - this is not "
                    f"the expected build"
                )
            index = names.index(name)
            _name_va, parse_fn, _userdata, field_off = entries[index]
            if field_off != offset:
                raise ValueError(
                    f"{name} is parsed into ModuleData+0x{field_off:x}, not 0x{offset:x} - the "
                    f"cave would walk another field"
                )
            entry_va = base_va + index * ROW_SIZE
            entry_off = va_to_offset(data, entry_va)
            if entry_off is None:
                raise ValueError(f"the {name} entry at 0x{entry_va:08x} is not mapped")
            found.append((entry_off, name, parse_fn))
        return found

    def _check_field_entries(self, data: bytes | bytearray, patched: bool = False) -> None:
        """Assert both entries are the keywords', in this build's table. ``patched`` says which
        parse function to expect - the stock one before the write, anything but it afterwards,
        since where the cave landed is `verify`'s business."""
        for _entry_off, name, parse_fn in self._field_entries(data):
            if not patched and parse_fn != STOCK_ASCII_STRING_PARSER:
                raise ValueError(
                    f"{name} parses with 0x{parse_fn:08x}, not the stock "
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
        self, data: bytes | bytearray, stubs: tuple[int, int, int]
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte range this patch rewrites, as ``(file offset, old, new, note)``."""
        parse_va, grant_va, remove_va = stubs
        edits: list[tuple[int, bytes, bytes, str]] = [
            (
                entry_off + 4,
                _u32(STOCK_ASCII_STRING_PARSER),
                _u32(parse_va),
                f"{name} parse function -> cave",
            )
            for entry_off, name, _parse_fn in self._field_entries(data)
        ]

        for call_va, cave_va, note in (
            (GRANT_CALL_VA, grant_va, "the grant lookup -> cave"),
            (REMOVE_CALL_VA, remove_va, "the removal lookup -> cave"),
        ):
            call_off = va_to_offset(data, call_va)
            if call_off is None:
                raise ValueError(f"{note}: VA 0x{call_va:08x} is not mapped")
            edits.append(
                (
                    call_off,
                    _call_bytes(call_va, FIND_UPGRADE),
                    _call_bytes(call_va, cave_va),
                    note,
                )
            )
        return edits
