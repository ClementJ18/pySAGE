"""Forward references in `PrerequisiteSciences`: let a science name one that is defined later.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address below is derived
in ``../docs/science-forward-references.md``.

**What the engine does today.** `PrerequisiteSciences` has its own parse function,
`0x0073BCBF` - the only one that understands the `OR` token, and the only field in the game that
uses it. It resolves each token through a shared four-instruction thunk at `THUNK_VA`, which calls
`ScienceStore::getScienceFromInternalName`. That function computes the token's name key, *then*
checks the key names a science that already exists, and throws
``"Science name %s not known! (Did you define it in Science.ini?)"`` if it does not. So a mutual
pair - `C` requiring `A or D` while `D` requires `B or C` - cannot be written in one file, and the
second half has to be injected from `map.ini`.

**Why this is cheap.** `ScienceType` **is** a `NameKeyType`, and the check contributes nothing to
the value: `getScienceFromInternalName` returns the key it computed *before* validating.
`NameKeyGenerator::nameToKey` interns and mints on a miss, so naming `D` early creates `D`'s key
and `Science D`'s own block header later resolves to the same integer. A forward reference and a
backward reference therefore store the identical dword - the permissive build produces exactly the
value the working case produces, not a degraded one something must repair.

A key that never gets a definition stays benign too. `ScienceStore::playerHasPrereqsForScience`
evaluates a group by asking whether the player *holds* each key; a key no science defines is one no
player can hold, so the group is simply unsatisfiable. Nothing resolves a prerequisite key back to
a `ScienceInfo`.

**Composition.** Order-independent: the cave is allocated with
:func:`~..utils.allocate_section` past every existing section and :meth:`verify` finds it by name,
no edited byte is shared with another bundled patch, and the only structure read - the stock
`Science` field-parse table - is one nothing else rewrites. See the composition contract on
:class:`~..patcher.Patch`. Note that `cah-factions` edits `0x0073BD9E`, `0x0073BDBF` and
`0x0073BDD1`, inside `getSideIndex` - the function immediately after the prerequisite parser, which
ends at `0x0073BD9C`. Adjacent compiland, disjoint bytes.

The patch has two parts, the second optional.

* **The permissive lookup** (always). One `rel32`: the `call` at `PREREQ_CALL_VA` is redirected at
  a cave shim that calls `nameToKey` directly and skips the validation. Sixteen bytes, no frame -
  `nameToKey` is `__thiscall` with one stack argument and cleans it, so the shim's `ret` lands back
  at the caller's own `pop ecx`.
* **The deferred report** (``report_missing``, on by default). The shim additionally asks
  `ScienceStore::isValidScience` and records the key of every name that did not resolve. A detour
  at `INIT_DETOUR_VA` - immediately after the `initSubsystem` call that creates and loads
  `TheScienceStore` - walks that list, re-checks each key, and throws the engine's own exception,
  with the engine's own message, for the first one still missing.

Why the report has to be deferred rather than moved
---------------------------------------------------
There is nowhere earlier to put it. `initSubsystem` is passed no INI path
(`0x0063B1FD` pushes three NULLs); the files are read by the subsystem's own vtable `+8` override,
which walks the global per-subsystem path lists keyed by the name ``"TheScienceStore"``. Whatever
files a mod routes there, all of them are read by the time `0x0063B21E` returns, and none of them
before it is called.

The report is thrown from `GameEngine::init` rather than from inside `INI`'s field loop, which
costs less than it looks: the four ``"Error parsing field/block … in file '%s', line %i."`` format
strings at `0x00BD3EBB`, `0x00BD3F00`, `0x00BD3F4C` and `0x00BD3FA5` have **no imm32 reference
anywhere in the image**, so this build's INI handler never adds file and line to begin with. The
text a modder sees is the exception's own string, which is byte-identical either way.

Two limits worth stating rather than glossing. A `map.ini` that defines a `Science` block runs long
after startup and is never re-checked - a strict improvement on today, where it cannot be checked
at all, but not a complete net. And the name comparison behind `nameToKey` is a `strcmp`, so
`SCIENCE_D` and `Science_D` are different keys: with ``report_missing`` off, a case-mismatched
prerequisite becomes a silently dead one where today it is a load error.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from ..asm import JAE, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "FIELD_TABLE_VA",
    "INIT_DETOUR_VA",
    "PENDING_CAPACITY",
    "PREREQ_CALL_VA",
    "PREREQ_PARSE_VA",
    "SECTION_NAME",
    "STOCK_FIELDS",
    "THUNK_VA",
    "SciencePrereqPatch",
    "build_section",
    "stock_thunk",
]

# The `Science` block, as this build lays it out (VA, ImageBase 0x400000).

#: The 16-byte-stride field-parse table `INI::parseScienceDefinition` initialises from.
FIELD_TABLE_VA = 0x00BF8788
#: The OR-group parser `PrerequisiteSciences` alone uses.
PREREQ_PARSE_VA = 0x0073BCBF
#: The ``call`` inside it that turns a token into a `ScienceType`. The one byte range part 1 edits.
PREREQ_CALL_VA = 0x0073BD45

#: The shared name-to-science thunk: ``push [esp+4] / mov ecx, [TheScienceStore] / call / ret``.
#: Four callers - both science-vector parsers, the single-science parser and `0x00740483`.
THUNK_VA = 0x0073A386
GET_SCIENCE_FROM_INTERNAL_NAME = 0x005FEEC7  # __thiscall(name), ret 4 -> key, or throws
IS_VALID_SCIENCE = 0x005FED95  # __thiscall(key), ret 4 -> bool

#: The stock table, in table order, as ``(name, ScienceInfo offset)``. Used as a fingerprint: all
#: six names *and* offsets must match, and the `PrerequisiteSciences` entry must still name
#: :data:`PREREQ_PARSE_VA`, before anything is written.
STOCK_FIELDS = (
    ("PrerequisiteSciences", 0x1C),
    ("SciencePurchasePointCost", 0x28),
    ("SciencePurchasePointCostMP", 0x2C),
    ("IsGrantable", 0x30),
    ("DisplayName", 0x14),
    ("Description", 0x18),
)
FIELD_ENTRY_SIZE = 16

# The interning name table. `nameToKey` mints a key for a name it has not seen, which is the whole
# reason a forward reference is representable at all.

THE_NAME_KEY_GENERATOR = 0x00DD90E4
NAME_TO_KEY = 0x005487EC  # __thiscall(char *), ret 4 -> NameKeyType
KEY_TO_NAME = 0x00548700  # __thiscall(NameKeyType), ret 4 -> AsciiString *
THE_SCIENCE_STORE = 0x00DE3B20
#: The shared empty string `AsciiString` hands back for a buffer that was never allocated.
EMPTY_STRING = 0x00BD0C3F

# The deferred report.

#: ``initSubsystem(&TheScienceStore, …)``, and the ``add esp, 0x1c / push 0x24`` pair after it that
#: part 2 replaces with its detour. Both instructions are re-emitted in the cave.
INIT_CALL_VA = 0x0063B21E
INIT_DETOUR_VA = 0x0063B223
INIT_RESUME_VA = 0x0063B228
STOCK_DETOUR_BYTES = b"\x83\xc4\x1c\x6a\x24"

#: `AsciiString`-free exception builder: ``cdecl(Exception *out, int code, const char *fmt, …)``
#: where `Exception` is ``{char *message; int code;}``. `3` is the code both stock INI throw sites
#: pass.
EXCEPTION_FORMAT = 0x0042F3C1
EXCEPTION_CODE = 3
CXX_THROW_EXCEPTION = 0x00A3CE04
THROW_INFO = 0x00D17000
#: ``"Science name %s not known! (Did you define it in Science.ini?)"`` - the stock message, reused
#: verbatim so a deferred report is indistinguishable from the parse-time one it replaces.
UNKNOWN_SCIENCE_FORMAT = 0x00BF86AC

#: How many unresolved keys the cave can hold. Far past any plausible mod; the report says so
#: rather than pretending the list was complete if it ever overflows.
PENDING_CAPACITY = 256

SECTION_NAME = ".scipre"
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ, plus MEM_WRITE when the pending list
# is present - the recorder writes into the cave.
_BASE_CHARACTERISTICS = 0x60000060
_MEM_WRITE = 0x80000000


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _call_bytes(from_va: int, to_va: int) -> bytes:
    """The five bytes of ``call rel32`` sited at ``from_va``."""
    return b"\xe8" + struct.pack("<i", to_va - (from_va + 5))


def _jmp_bytes(from_va: int, to_va: int) -> bytes:
    return b"\xe9" + struct.pack("<i", to_va - (from_va + 5))


def _read_cstring(data: bytes | bytearray, va: int, limit: int = 64) -> str | None:
    off = va_to_offset(data, va)
    if off is None:
        return None
    end = bytes(data[off : off + limit]).find(b"\x00")
    return None if end < 0 else bytes(data[off : off + end]).decode("latin1")


def stock_thunk() -> bytes:
    """The sixteen bytes of the unpatched name-to-science thunk.

    The shim reproduces this thunk's ABI exactly - `cdecl`, the token at ``[esp+4]``, the key in
    ``eax``, the caller pops - so a build whose thunk is shaped differently must not be patched."""
    return (
        b"\xff\x74\x24\x04"  # push dword [esp+4]
        + b"\x8b\x0d"
        + _u32(THE_SCIENCE_STORE)  # mov ecx, [TheScienceStore]
        + _call_bytes(THUNK_VA + 10, GET_SCIENCE_FROM_INTERNAL_NAME)
        + b"\xc3"  # ret
    )


def build_section(base_va: int, report_missing: bool) -> tuple[bytes, dict[str, int]]:
    """Return ``(section content, {label: VA})`` for a cave based at ``base_va``.

    Layout: the pending list (when there is one) first, so the code that follows can address it as
    a link-time constant, then `science_key`, then - only with ``report_missing`` - `validate` and
    the `after_load` detour body."""
    a = Asm(base_va)
    count_va = pending_va = 0

    if report_missing:
        a.label("count")
        a.emit(bytes(4))
        a.label("pending")
        a.emit(bytes(4 * PENDING_CAPACITY))
        count_va = a.label_va("count")
        pending_va = a.label_va("pending")

    # `science_key`: cdecl(char *name) -> NameKeyType in eax, the caller pops. What the stock thunk
    # does, minus the validation - and, when asked, plus a note of what did not resolve.
    #
    # `ebx`, `esi` and `edi` are live in the caller across this call; every callee here is
    # `__thiscall` and preserves them, and the body itself touches only eax/ecx/edx.
    a.label("science_key")
    a.emit(b"\x8b\x0d", _u32(THE_NAME_KEY_GENERATOR))  # mov ecx, [TheNameKeyGenerator]
    a.emit(b"\xff\x74\x24\x04")  # push dword [esp+4]
    a.call_absolute(NAME_TO_KEY)  # call <nameToKey>    ; eax = key, arg popped
    if report_missing:
        a.emit(b"\x8b\x0d", _u32(THE_SCIENCE_STORE))  # mov ecx, [TheScienceStore]
        a.emit(b"\x85\xc9")  # test ecx, ecx
        a.jcc(JE, "key_done")  # je .done            ; no store yet, nothing to ask
        a.emit(0x50)  # push eax            ; save the key across the call
        a.emit(0x50)  # push eax            ; the argument
        a.call_absolute(IS_VALID_SCIENCE)  # call <isValidScience>
        a.emit(b"\x84\xc0")  # test al, al
        a.emit(0x58)  # pop eax             ; (does not touch flags)
        a.jcc(JNE, "key_done")  # jne .done           ; already defined
        a.emit(b"\x8b\x15", _u32(count_va))  # mov edx, [count]
        a.emit(b"\x81\xfa", _u32(PENDING_CAPACITY))  # cmp edx, PENDING_CAPACITY
        a.jcc(JAE, "key_done")  # jae .done           ; full: drop, the report says so
        a.emit(b"\x89\x04\x95", _u32(pending_va))  # mov [pending + edx*4], eax
        a.emit(0x42)  # inc edx
        a.emit(b"\x89\x15", _u32(count_va))  # mov [count], edx
        a.label("key_done")
    a.emit(0xC3)  # ret

    if report_missing:
        # `validate`: walk the pending keys, re-ask the store, and throw on the first survivor.
        # Runs inside the caller's `pushad`, so it may use any register.
        a.label("validate")
        a.emit(b"\x33\xf6")  # xor esi, esi
        a.label("scan")
        a.emit(b"\x3b\x35", _u32(count_va))  # cmp esi, [count]
        a.jcc(JAE, "scan_done")  # jae .done
        a.emit(b"\x8b\x1c\xb5", _u32(pending_va))  # mov ebx, [pending + esi*4]
        a.emit(b"\x8b\x0d", _u32(THE_SCIENCE_STORE))  # mov ecx, [TheScienceStore]
        a.emit(0x53)  # push ebx
        a.call_absolute(IS_VALID_SCIENCE)  # call <isValidScience>
        a.emit(b"\x84\xc0")  # test al, al
        a.jcc(JE, "missing")  # je .missing         ; still unknown
        a.emit(0x46)  # inc esi
        a.jmp("scan")
        a.label("scan_done")
        a.emit(0xC3)  # ret

        # The key is all that was recorded - the token pointer would dangle, since the tokenizer
        # reuses its buffer - so the name comes back from the key->node map.
        a.label("missing")
        a.emit(0x53)  # push ebx
        a.emit(b"\x8b\x0d", _u32(THE_NAME_KEY_GENERATOR))  # mov ecx, [TheNameKeyGenerator]
        a.call_absolute(KEY_TO_NAME)  # call <keyToName>    ; -> AsciiString*
        a.emit(b"\x8b\x00")  # mov eax, [eax]      ; its buffer
        a.emit(b"\x85\xc0")  # test eax, eax
        a.jcc(JE, "no_name")  # je .no_name
        a.emit(b"\x83\xc0\x08")  # add eax, 8          ; -> the chars
        a.jmp("throw")
        a.label("no_name")
        a.emit(0xB8, _u32(EMPTY_STRING))  # mov eax, <"">

        # The stock throw, byte for byte: build `{char *message; int code;}` on the stack from the
        # stock format string, then hand it to the runtime. Does not return.
        a.label("throw")
        a.emit(b"\x83\xec\x08")  # sub esp, 8          ; the exception object
        a.emit(0x50)  # push eax            ; the %s
        a.emit(0x68, _u32(UNKNOWN_SCIENCE_FORMAT))  # push <format>
        a.emit(0x6A, EXCEPTION_CODE)  # push 3
        a.emit(b"\x8d\x44\x24\x0c")  # lea eax, [esp+0xc]  ; &exception
        a.emit(0x50)  # push eax
        a.call_absolute(EXCEPTION_FORMAT)  # call <format>
        a.emit(b"\x83\xc4\x10")  # add esp, 0x10
        a.emit(0x68, _u32(THROW_INFO))  # push <throwinfo>
        a.emit(b"\x8d\x44\x24\x04")  # lea eax, [esp+4]    ; &exception
        a.emit(0x50)  # push eax
        a.call_absolute(CXX_THROW_EXCEPTION)  # call <_CxxThrowException>
        a.emit(0xCC)  # int3                ; unreachable

        # `after_load`: the two instructions the detour displaced, with the walk between them.
        # `pushad` because the detour site sits mid-`GameEngine::init` with live ebx/esi/edi.
        a.label("after_load")
        a.emit(b"\x83\xc4\x1c")  # add esp, 0x1c       ; initSubsystem's 7 args
        a.emit(0x60)  # pushad
        a.call("validate")
        a.emit(0x61)  # popad
        a.emit(b"\x6a\x24")  # push 0x24
        a.jmp_absolute(INIT_RESUME_VA)

    labels = {"science_key": a.label_va("science_key")}
    if report_missing:
        labels["validate"] = a.label_va("validate")
        labels["after_load"] = a.label_va("after_load")
    return a.finish(), labels


class SciencePrereqPatch(Patch):
    """Let `PrerequisiteSciences` name a science that has not been defined yet."""

    name = "science-prereqs"
    description = "Allow forward references (and so mutual prerequisites) in PrerequisiteSciences"

    def __init__(self, report_missing: bool = True, all_keywords: bool = False):
        self.report_missing = report_missing
        self.all_keywords = all_keywords
        self._validate()

    def __str__(self) -> str:
        scope = "every science keyword" if self.all_keywords else "PrerequisiteSciences"
        report = "reports what stayed missing" if self.report_missing else "no deferred report"
        return f"{self.name} ({scope}, {report})"

    def _validate(self) -> None:
        if self.all_keywords and not self.report_missing:
            raise ValueError(
                "all_keywords without report_missing would silence every science-name typo in "
                "the game, with no diagnostic anywhere - RequiredSciences on a misspelt science "
                "would simply never fire. Keep the deferred report, or narrow to "
                "PrerequisiteSciences."
            )

    def apply(self, data: bytearray) -> None:
        self._check_field_table(data)
        if not self.all_keywords:
            self._check_thunk(data)
        section_va = allocate_section(
            data,
            SECTION_NAME,
            lambda va: build_section(va, self.report_missing)[0],
            _BASE_CHARACTERISTICS | (_MEM_WRITE if self.report_missing else 0),
        )
        # The layout is a pure function of the base VA and the settings, so re-deriving it costs
        # nothing and keeps `build_section` a plain callable.
        _content, labels = build_section(section_va, self.report_missing)
        for file_off, old, new, note in self._edits(data, labels):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` carries this patch with exactly these settings (an empty
        list == verified). Locates the cave, recomputes the stubs the settings imply, and compares
        them and every repointed site to what is on disk. Reads only via ``struct`` + the section
        table, so verification needs no disassembler."""
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located

        problems: list[str] = []
        try:
            content, labels = build_section(section_va, self.report_missing)
            edits = self._edits(data, labels)
        except (ValueError, struct.error) as exc:
            return [f"cannot recompute the expected cave (wrong build?): {exc}"]

        got = bytes(data[section_off : section_off + len(content)])
        if got != content:
            problems.append(
                f"{SECTION_NAME} does not match report_missing={self.report_missing} "
                "(the pending list or the stubs differ)"
            )

        for file_off, _old, new, note in edits:
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> SciencePrereqPatch | None:
        """Recognise this patch **and recover its settings**.

        The default probe only ever recognises the defaults, and this patch's two flags change
        both the cave and which site is repointed - so probe the three legal combinations and
        return the one whose `verify` is clean."""
        if find_section(data, SECTION_NAME) is None:
            return None
        for report_missing, all_keywords in ((True, False), (True, True), (False, False)):
            patch = cls(report_missing=report_missing, all_keywords=all_keywords)
            try:
                problems = patch.verify(data)
            except (ValueError, KeyError, IndexError, TypeError, struct.error):
                continue
            if not problems:
                return patch
        return None

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--no-report-missing",
            dest="report_missing",
            action="store_false",
            help=(
                "skip the deferred check. Forward references are then simply permitted, and a "
                "science name that is misspelt everywhere becomes a prerequisite nothing can "
                "satisfy instead of a load error"
            ),
        )
        parser.add_argument(
            "--all-keywords",
            action="store_true",
            help=(
                "relax every science-name keyword (RequiredSciences, IntrinsicSciences, "
                "SciencesGranted, CommandButton's Science) rather than PrerequisiteSciences "
                "alone, by repointing the shared thunk. Requires the deferred report, which is "
                "what gives those keywords their typo diagnostic back"
            ),
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> SciencePrereqPatch:
        return cls(report_missing=args.report_missing, all_keywords=args.all_keywords)

    def _check_field_table(self, data: bytes | bytearray) -> None:
        """Assert this really is this build's `Science` field-parse table: every name, every
        `ScienceInfo` offset, the parse function of the field being relaxed, and the terminator.

        A far stronger build check than the edit sites alone, and free - the patch has to be sure
        `PrerequisiteSciences` is still the OR-group parser it thinks it is redirecting inside."""
        off = va_to_offset(data, FIELD_TABLE_VA)
        if off is None:
            raise ValueError(f"the Science field table VA 0x{FIELD_TABLE_VA:08x} is not mapped")

        size = len(STOCK_FIELDS) * FIELD_ENTRY_SIZE
        entries = bytes(data[off : off + size])
        if len(entries) != size:
            raise ValueError("the Science field table runs past the end of the image")

        for index, (name, offset) in enumerate(STOCK_FIELDS):
            name_va, parse, _userdata, field_off = struct.unpack_from(
                "<4I", entries, index * FIELD_ENTRY_SIZE
            )
            got = _read_cstring(data, name_va)
            if got != name:
                raise ValueError(f"Science field entry {index}: expected {name!r}, found {got!r}")
            if field_off != offset:
                raise ValueError(
                    f"Science field {name!r}: expected offset 0x{offset:x}, found 0x{field_off:x}"
                )
            if name == "PrerequisiteSciences" and parse != PREREQ_PARSE_VA:
                raise ValueError(
                    f"PrerequisiteSciences is parsed by 0x{parse:08x}, not the OR-group parser "
                    f"0x{PREREQ_PARSE_VA:08x} this patch edits inside"
                )

        terminator = bytes(data[off + size : off + size + FIELD_ENTRY_SIZE])
        if terminator != bytes(FIELD_ENTRY_SIZE):
            raise ValueError(
                f"the Science field table is not NULL-terminated after {len(STOCK_FIELDS)} "
                f"entries (found {terminator.hex()})"
            )

    def _check_thunk(self, data: bytes | bytearray) -> None:
        """Assert the shared thunk is still the shape the shim replaces.

        Only needed when the thunk is *not* the thing being rewritten: the shim reproduces its
        calling convention, and nothing else would catch a build where that convention differs -
        the patch would apply cleanly and hand the parser a key computed from the wrong stack
        slot."""
        expected = stock_thunk()
        off = va_to_offset(data, THUNK_VA)
        if off is None:
            raise ValueError(f"the science-name thunk 0x{THUNK_VA:08x} is not mapped")
        got = bytes(data[off : off + len(expected)])
        if got != expected:
            raise ValueError(
                f"the science-name thunk @0x{THUNK_VA:08x}: expected {expected.hex()}, "
                f"got {got.hex()} - this is not the expected build"
            )

    def _edits(
        self, data: bytes | bytearray, labels: dict[str, int]
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte range this patch rewrites, as ``(file offset, old, new, note)``."""
        edits: list[tuple[int, bytes, bytes, str]] = []

        def at(va: int, old: bytes, new: bytes, note: str) -> None:
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"{note}: VA 0x{va:08x} is not mapped")
            edits.append((off, old, new, note))

        if self.all_keywords:
            # A plain `jmp` works because the shim has the thunk's own signature: the token is
            # still at [esp+4] and the caller still pops. The thunk's remaining bytes go dead.
            at(
                THUNK_VA,
                stock_thunk()[:5],
                _jmp_bytes(THUNK_VA, labels["science_key"]),
                "science-name thunk -> cave",
            )
        else:
            at(
                PREREQ_CALL_VA,
                _call_bytes(PREREQ_CALL_VA, THUNK_VA),
                _call_bytes(PREREQ_CALL_VA, labels["science_key"]),
                "PrerequisiteSciences name lookup -> cave",
            )

        if self.report_missing:
            at(
                INIT_DETOUR_VA,
                STOCK_DETOUR_BYTES,
                _jmp_bytes(INIT_DETOUR_VA, labels["after_load"]),
                "after the science store loads -> cave",
            )
        return edits
