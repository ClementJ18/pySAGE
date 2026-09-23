"""Engine runtime: strings, INI parsing, file system, mods, debug and crash handling."""

from __future__ import annotations

__all__ = [
    "AMPERSAND_SCAN",
    "ARCHIVE_FILE_SYSTEM",
    "ARCHIVE_FILE_SYSTEM_LOAD_ARCHIVE",
    "ARCHIVE_FILE_SYSTEM_LOAD_ARCHIVE_SLOT",
    "ARCHIVE_FILE_SYSTEM_VTABLE",
    "ASCII_STRING_ASSIGN",
    "ASCII_STRING_CHARS_OFFSET",
    "ASCII_STRING_COMPARE",
    "ASCII_STRING_COPY",
    "ASCII_STRING_COPY_CTOR",
    "ASCII_STRING_CTOR",
    "ASCII_STRING_DTOR",
    "ASCII_STRING_FORMAT",
    "ASCII_STRING_IS_EMPTY",
    "ASCII_STRING_SET",
    "ASCII_STRING_SET_BYTES",
    "ASSET_CACHE_HAS_ASSET",
    "ASSET_CACHE_HAS_ASSET_BYTES",
    "ASSET_CACHE_LOAD",
    "ASSET_CACHE_LOAD_BYTES",
    "ASSET_CACHE_MOD_BIG_BRANCH",
    "ASSET_CACHE_MOD_BIG_BRANCH_BYTES",
    "ASSET_CACHE_MOD_BIG_TEST",
    "ASSET_CACHE_MOD_BIG_TEST_BYTES",
    "ASSET_CACHE_READ_FILE",
    "ASSET_CACHE_READ_FILE_BYTES",
    "ASSET_CACHE_REGISTER_GATE",
    "ASSET_CACHE_REGISTER_GATE_BYTES",
    "ASSET_CACHE_WORKING_DIR_ATTEMPT",
    "ASSET_CACHE_WORKING_DIR_ATTEMPT_BYTES",
    "ASSET_DAT_NAME",
    "ASSET_DAT_NAME_BYTES",
    "CLI_COUNT_REF",
    "CLI_DISPATCH",
    "CLI_TABLE",
    "CLI_TABLE_BYTES",
    "CLI_TABLE_ENTRIES",
    "CLI_TABLE_FINGERPRINT",
    "CLI_TABLE_REF",
    "COMMAND_LINE_MOD_HANDLER",
    "COMMAND_LINE_MOD_HANDLER_STORE",
    "COMMAND_LINE_MOD_HANDLER_STORE_BYTES",
    "COMMAND_LINE_MOD_HANDLER_TARGET",
    "COMMAND_LINE_MOD_HANDLER_TARGET_BYTES",
    "COMMAND_LINE_PARSE",
    "COMMAND_LINE_PARSE_AND_MOUNT_MODS",
    "COMMAND_LINE_SKIRMISH_SETUP",
    "COMMAND_LINE_SKIRMISH_SETUP_BYTES",
    "COMMAND_LINE_SKIRMISH_SETUP_RESUME",
    "COMMAND_LINE_STARTUP_TABLE",
    "COMMAND_LINE_STARTUP_TABLE_COUNT",
    "COORD3D_GET_LENGTH",
    "CRT_ATOI",
    "DEBUG_CRASH_EXCEPTION_CODE",
    "DEBUG_CRASH_MESSAGE_EBP",
    "DEBUG_CRASH_MESSAGE_READ",
    "DEBUG_CRASH_MESSAGE_READ_BYTES",
    "DEBUG_CRASH_MODE_EBP",
    "DEBUG_CRASH_RAISE",
    "DEBUG_CRASH_RAISE_BYTES",
    "DEBUG_CRASH_RAISE_RESUME",
    "DEBUG_CRASH_RAISE_RESUME_BYTES",
    "DEBUG_CRASH_TAG_EBP",
    "DEBUG_CRASH_TAG_STORE",
    "DEBUG_CRASH_TAG_STORE_BYTES",
    "DICT_SET_ASCII_STRING",
    "DICT_SET_ASCII_STRING_BYTES",
    "EMPTY_STRING",
    "FIELD_PARSE_STRIDE",
    "FILE_SYSTEM",
    "FILE_SYSTEM_CREATE_CALL",
    "FILE_SYSTEM_CREATE_CALL_BYTES",
    "FILE_SYSTEM_DOES_FILE_EXIST",
    "FILE_SYSTEM_GET_FILE_INFO",
    "FILE_SYSTEM_GET_FILE_LIST_IN_DIRECTORY",
    "FILE_SYSTEM_OPEN_FILE",
    "FLOAT_HUNDRED",
    "FLOAT_ONE",
    "FLOAT_ONE_PERCENT",
    "FLOAT_TEN",
    "FLOAT_TWO_PERCENT",
    "GET_PROC_ADDRESS_IAT",
    "GLOBAL_DATA",
    "GLOBAL_DATA_ACTIVE_MAP",
    "GLOBAL_DATA_ASSET_PROFILE",
    "GLOBAL_DATA_FPS_LIMIT",
    "GLOBAL_DATA_MOD_BIG",
    "GLOBAL_DATA_MOD_DIR",
    "GLOBAL_DATA_SHELL_MAP",
    "GLOBAL_DATA_STAGED_MAP",
    "GLOBAL_DATA_USE_FPS_LIMIT",
    "GLOBAL_DATA_VTABLE",
    "IMPORT_FCLOSE",
    "IMPORT_FFLUSH",
    "IMPORT_FOPEN",
    "IMPORT_FWRITE",
    "IMPORT_GET_LOCAL_TIME",
    "IMPORT_SWPRINTF",
    "INI_LOAD",
    "INI_LOAD_DIRECTORY",
    "INI_LOAD_INNER",
    "INI_MACRO_LOOKUP",
    "INI_MACRO_TABLE",
    "INI_NEXT_TOKEN_OR_NULL",
    "INI_PARSE_BOOL",
    "INI_PARSE_COORD3D",
    "INI_PARSE_COORD3D_BYTES",
    "INI_PARSE_DURATION",
    "INI_PARSE_FIELDS",
    "INI_PARSE_INT",
    "INI_PARSE_POSITIVE_REAL",
    "INI_PARSE_POSITIVE_REAL_BYTES",
    "INI_PARSE_REAL",
    "INI_PARSE_REAL_BYTES",
    "INI_PARSE_STRING_LIST",
    "INI_PARSE_STRING_LIST_BYTES",
    "INI_PARSE_UNSIGNED_SHORT",
    "INI_PARSE_UPGRADE_MASK",
    "INI_SCAN_INT",
    "LOAD_LIBRARY_A_IAT",
    "LOCAL_FILE_SYSTEM",
    "LOCAL_FILE_SYSTEM_DOES_FILE_EXIST_SLOT",
    "LOCAL_FILE_SYSTEM_GET_FILE_INFO_SLOT",
    "LOCAL_FILE_SYSTEM_GET_FILE_LIST_SLOT",
    "LOCAL_FILE_SYSTEM_OPEN_FILE_SLOT",
    "MATRIX3D_ROW_STRIDE",
    "MATRIX3D_TRANSLATION",
    "MINI_DUMP_ARGS",
    "MINI_DUMP_ARGS_BYTES",
    "MINI_DUMP_ARGS_RESUME",
    "MINI_DUMP_ARGS_RESUME_BYTES",
    "MINI_DUMP_EXCEPTION_INFO_EBP",
    "MINI_DUMP_FULL_DUMP_EBP",
    "MINI_DUMP_NULL_EDI",
    "MINI_DUMP_NULL_EDI_BYTES",
    "MOD_DIRECTORY",
    "MOD_MOUNT_DIRECTORY",
    "MOD_PATH_FORMAT",
    "MOD_PREFER_LOCAL_FLAG",
    "NAME_KEY_FROM_CSTR",
    "NAME_KEY_FROM_STRING",
    "NAME_KEY_TO_NAME",
    "OPERATOR_NEW",
    "QUERY_PERFORMANCE_COUNTER_IAT",
    "READ_BINARY_MODE",
    "READ_BINARY_MODE_BYTES",
    "REF_COUNT_RELEASE",
    "SPRINTF_SLOT",
    "STATIC_NAME_KEY_KEY",
    "STATIC_NAME_KEY_KEY_BYTES",
    "STRCMPI",
    "STRCPY",
    "STRICMP",
    "STRLEN",
    "SUBSYSTEM_INIT",
    "SUBSYSTEM_LEGEND",
    "SUBSYSTEM_LOAD_LEGEND_FILES",
    "SUBSYSTEM_REGISTER",
    "TEXT_SECTION_LEN",
    "TEXT_SECTION_VA",
    "WIDE_BLANK_LINE",
    "WIDE_BLANK_LINE_BYTES",
    "WIDE_NEWLINE",
    "WIDE_NEWLINE_BYTES",
    "WRITE_MINI_DUMP",
    "WRITE_MINI_DUMP_BYTES",
    "WRITE_MINI_DUMP_CALL_FILTER",
    "WRITE_MINI_DUMP_CALL_FILTER_BYTES",
    "YES_STRING",
]

# `.text`, as this build's section table maps it. The image carries no `.reloc` and does not opt
# into `DYNAMIC_BASE`, so the loader places it at `IMAGE_BASE` and never rewrites a byte of it:
# the code in memory is the code in the file. That is what lets `binary-attest` hash this range
# at runtime and lets the same hash be recomputed offline from the file - see
# `docs/binary-attest.md`.
TEXT_SECTION_VA = 0x00401000
TEXT_SECTION_LEN = 0x007CF000
# The tail of the `-file` auto-start's skirmish branch: `push 2` / `mov ecx, edi` /
# `GameMessage::appendIntegerArgument`, by which point the engine has finished building the
# `GameInfo` and filled slot 0. Nothing branches into these nine bytes.
COMMAND_LINE_SKIRMISH_SETUP = 0x0063CB7B
COMMAND_LINE_SKIRMISH_SETUP_BYTES = bytes.fromhex("6a028bcfe861460d00")
COMMAND_LINE_SKIRMISH_SETUP_RESUME = 0x0063CB84
OPERATOR_NEW = 0x0042F6E0
#: `INI::parseInt`, the stock `Int` field parser: cdecl `(INI*, void *instance, void *store,
#: const void *userData)`, writing to `store` == `instance + offset`. Both `UnitCost` entries
#: already use it, so a new `Int` field needs no parser of its own.
INI_PARSE_INT = 0x0042EC5E
#: Two wide literals the description builder already joins lines with: `L"\n"` (the separator the
#: `CONTROLBAR:Requirements` and `TOOLTIP:BuildDisabled` folds use) and `L"\n\n"` (the blank-line
#: separator the two "cannot buy this" messages use). Neither is owned by any one site.
WIDE_NEWLINE = 0x00BDBC40
WIDE_NEWLINE_BYTES = bytes.fromhex("0a000000")
WIDE_BLANK_LINE = 0x00C4F008
WIDE_BLANK_LINE_BYTES = bytes.fromhex("0a000a000000")
# `msvcr71.dll` imports, by IAT slot. The engine calls them exactly this way
# (`call dword ptr [slot]`, cdecl, caller cleans), so a cave can too.
IMPORT_FWRITE = 0x00BD053C
IMPORT_FFLUSH = 0x00BD065C
IMPORT_SWPRINTF = 0x00BD0490
# `kernel32!GetLocalTime(LPSYSTEMTIME)` - stdcall, so it cleans its own argument.
# `startRecording` already calls it (`0x0077EBB1`) for the header's timestamp.
IMPORT_GET_LOCAL_TIME = 0x00BD01D4
#: The `10.0f` the engine itself uses as "near enough to the same level", in both arms of
#: `WALL_LAYER_PROMOTION` (`0x006F07A4`, `0x006F084C`).
FLOAT_TEN = 0x00BD83D8
# `TheNameKeyGenerator::nameToKey(const char *)` - the C-string overload the `AsciiString` one
# calls through to (0x0049F483 loads a pointer to a lone NUL for an empty string, so the key is
# taken off a NUL-terminated buffer, never a stored length). `__thiscall` on
# `THE_NAME_KEY_GENERATOR`, `ret 4`. A caller holding raw chars keys them without building an
# `AsciiString` first, which is what lets the upgrade-alias cave hash a truncated name.
NAME_KEY_FROM_CSTR = 0x005487EC
# `TheNameKeyGenerator::nameToKey(const AsciiString *)` - `__thiscall` on
# `THE_NAME_KEY_GENERATOR`, `ret 4`, returning the interned key. The same interning the hero
# builder itself applies to these names at 0x009A08B6 and 0x009A0948, which is what makes a key
# taken at parse time comparable with one taken during a match.
NAME_KEY_FROM_STRING = 0x0049F474
# A module's INI fields are a 16-byte-stride array of `{const char *name, parseFn, userData,
# offset}`, walked to a NULL name pointer - never to a count, which is why adding a field needs
# no bound raised anywhere. `INI::parseBool` is the parser every `Bool` field names; its tail is
# `mov ecx,[esp+0xc]` / `mov byte [ecx], al`, a single byte store through the pointer the reader
# forms as `store + offset`, which is what lets a `Bool` live in a struct's padding byte.
FIELD_PARSE_STRIDE = 16
INI_PARSE_BOOL = 0x0042E558
# `INI::parseReal`, the parser every `Real` field names: it scans one token, converts it and
# does `fstp dword [store]`, a single 4-byte float store through the same `store + offset`
# pointer - so a new `Real` field needs an aligned 4-byte slot and nothing else.
INI_PARSE_REAL = 0x0042ED00
# `INI::parseAsciiStringVector`, the parser behind every list-of-names field. To change one field's
# syntax, repoint that field's row, not this function.
INI_PARSE_STRING_LIST = 0x0042EED6
INI_PARSE_STRING_LIST_BYTES = bytes.fromhex("568b742410ff7604")
#: Float constants the inflation arithmetic reads, reused verbatim by anything that recomputes it.
FLOAT_ONE = 0x00BD1908  # 1.0f  - the "no modifier" multiplier
FLOAT_ONE_PERCENT = 0x00BE5600  # 0.01f - a percentage table entry into a multiplier
FLOAT_TWO_PERCENT = 0x00BDC320  # 0.02f - the per-object slope past the end of the table
#: `INI::getNextTokenOrNull(seps)` and `INI::scanInt(token)` - both thiscall on the `INI`, both
#: `ret 4`. The pair the stock `ResourceModifierValues` parser (`0x005FD599`) loops over, and
#: the only engine help a variable-length `Int` list parser needs.
INI_NEXT_TOKEN_OR_NULL = 0x0042DBF5
INI_SCAN_INT = 0x0042E9D7
#: `INI::parseUnsignedShort`, the stock `UInt16` field parser: cdecl, same four arguments as
#: `INI_PARSE_INT`, but it range-checks `0..0xFFFF` and stores a **word** through `store`. That
#: word store is what lets a new field live in two bytes of a struct's alignment padding, the way
#: `INI_PARSE_BOOL`'s byte store does for one.
INI_PARSE_UNSIGNED_SHORT = 0x0042EC11
#: `AsciiString::format(this, fmt, ...)` - cdecl, caller-cleaned, so one more vararg costs one
#: more push and a `0x0C -> 0x10` on the cleanup. The narrow sibling of `UNICODE_STRING_FORMAT`:
#: the palantir's **resource** text is built as an `AsciiString` from an 8-bit `"%d"` and only
#: widened on the way into the movie, where the command-point text is `UnicodeString` throughout.
ASCII_STRING_FORMAT = 0x00437A90
# The shell's campaign start (`docs/campaign-select.md`): `AptMainMenu`'s callbacks, reached from
# the movie as `FSCommand:AptMainMenu::<func>`.

#: `AsciiString::set(const char *)` - `strlen`s its argument and hands both to the buffer assign
#: at `0x004360C0`, which releases or reuses whatever the string already held. Safe to call on a
#: never-constructed (zeroed) `AsciiString` as well: the assign tests `m_data` against NULL first.
#: `ret 4`, so it cleans its own argument; `esi`/`edi` are pushed and popped.
ASCII_STRING_SET = 0x004050E6
ASCII_STRING_SET_BYTES = bytes.fromhex("568b74240885f6578bf9740956e8187e6300")
# The command-line table (`{name, handler}` rows) and the two instructions giving its address and
# length; repointing both extends it in six bytes. A handler returns how many arguments it used. See
# `docs/headless.md` section 1.
CLI_TABLE = 0x00C35DA8
CLI_TABLE_ENTRIES = 16
CLI_TABLE_BYTES = CLI_TABLE_ENTRIES * 8
CLI_DISPATCH = 0x007BA7E1
CLI_TABLE_REF = 0x007BAA4B  # mov ebx, 0x00C35DA8
CLI_COUNT_REF = 0x007BAA54  # push 0x10
#: The options at four positions of the stock table, as `{index: name}`. Enough to prove the
#: table being copied is this build's - a table that has moved, or a build whose option list
#: differs, fails here rather than being copied verbatim into the cave and dispatched to.
CLI_TABLE_FINGERPRINT = {
    0: "-noshellmap",
    5: "-win",
    14: "-resumeGame",
    15: "-randomSeed",
}
#: `msvcr71.dll!atoi`, as its import-address-table slot. The stock `-xres` handler
#: (`0x007BA104`) calls through this slot, which is how a new handler reads a numeric argument.
CRT_ATOI = 0x00BD0628
# `TheWritableGlobalData` and the frame-rate fields `UseFPSLimit` (`+0x26`) and
# `FramesPerSecondLimit` (`+0x28`). argv is parsed after `GameData.ini`, so a command-line handler
# wins.
GLOBAL_DATA = 0x00DE4364
GLOBAL_DATA_USE_FPS_LIMIT = 0x26
GLOBAL_DATA_FPS_LIMIT = 0x28
# The asset-load profiler's switch: in `GlobalData`, but reachable from no INI or command line
# (`docs/asset-demand-load.md`). Writable at run time.
GLOBAL_DATA_ASSET_PROFILE = 0x123D
#: Where an `AsciiString`'s characters begin, past its length and reference fields.
ASCII_STRING_CHARS_OFFSET = 0x08
#: `INI::parseFields(instance, table)` - the shared driver every block parser hands its field
#: table to, and the two engine parsers a new table's rows can point at directly. A row is called
#: `__cdecl parse(INI *ini, void *instance, void *store, const void *userData)`.
INI_PARSE_FIELDS = 0x0042DB80
#: `AsciiString::compare` - zero when equal, so the engine's own matching semantics are inherited
#: rather than re-implemented.
ASCII_STRING_COMPARE = 0x004065AA
#: `RefCountable::releaseRef` on an embedded count: `--[ecx+4]`, deleting through the vtable at
#: zero.
REF_COUNT_RELEASE = 0x0047D8B0
#: `Dict::setAsciiString(NameKey, const AsciiString&)` - `__thiscall`, `ret 8`, key pushed last.
DICT_SET_ASCII_STRING = 0x00715028
DICT_SET_ASCII_STRING_BYTES = bytes.fromhex("566a03ff7424")
#: `StaticNameKey::key()` - `__thiscall`, no arguments, `ret`, interns on first use and caches into
#: `[this]`. A `StaticNameKey` is `{ NameKey m_key; const char *m_name; }`, so `+4` is the name and
#: the key slot reads zero in the file.
STATIC_NAME_KEY_KEY = 0x00548930
STATIC_NAME_KEY_KEY_BYTES = bytes.fromhex("568bf1833e00")
#: `writeMiniDump(EXCEPTION_POINTERS *ep, BOOL fullDump)` - `cdecl`, two stack arguments, called
#: from the unhandled-exception filter at `0x0043D610`. It resolves `MiniDumpWriteDump` out of the
#: `dbghelp.dll` handle at `0x00DC62EC`, builds the file name, opens it, takes `SeDebugPrivilege`
#: and calls through. `docs/crash-dump-quality.md` derives the whole body.
WRITE_MINI_DUMP = 0x0043BE80
WRITE_MINI_DUMP_BYTES = bytes.fromhex("558bec81ec50010000a1ec62dc00")
#: `xor edi, edi` inside it, at the point the file name has been formatted. Every `push edi` from
#: here to the `MiniDumpWriteDump` call is therefore a literal `NULL`, which is what makes the two
#: at `MINI_DUMP_ARGS` the null user-stream and callback parameters rather than live values.
MINI_DUMP_NULL_EDI = 0x0043BF24
MINI_DUMP_NULL_EDI_BYTES = bytes.fromhex("33ff57576a02")
#: `writeMiniDump`'s frame slots. `..._FULL_DUMP_EBP` is the second argument, the `fulldump` debug
#: flag the engine reads off `Debug+0x9F56`; `..._EXCEPTION_INFO_EBP` is the
#: `MINIDUMP_EXCEPTION_INFORMATION` the function fills at `0x0043BF9D`..`0x0043BFB7`.
MINI_DUMP_FULL_DUMP_EBP = 0x0C
MINI_DUMP_EXCEPTION_INFO_EBP = -0x10
#: The eighteen bytes that push `MiniDumpWriteDump`'s last four arguments: `CallbackParam` and
#: `UserStreamParam` (both `push edi`, both `NULL`), `ExceptionParam`, and the dump type - which
#: the stock code derives as `1` or `2` from the `fulldump` flag and nothing else. `..._RESUME` is
#: the `push esi` that follows with the file handle, the first byte the window does not cover.
MINI_DUMP_ARGS = 0x0043C001
MINI_DUMP_ARGS_BYTES = bytes.fromhex("8a550c33c984d20f95c157578d45f0504151")
MINI_DUMP_ARGS_RESUME = 0x0043C013
MINI_DUMP_ARGS_RESUME_BYTES = bytes.fromhex("56ff154401bd00")
#: The engine's own "Game crash" exception code, raised at `DEBUG_CRASH_RAISE` and recognised by
#: the unhandled-exception filter at `0x0043D673`. Four of the six dumps found in the install root
#: carry it, which is why its (stock, empty) parameter block is worth filling.
DEBUG_CRASH_EXCEPTION_CODE = 0x04560123
#: `Debug::crash(mode)`'s frame slots: the formatted crash text (a heap pointer), the tag literal,
#: and `mode` (1 for an assertion).
DEBUG_CRASH_MESSAGE_EBP = -0x04
DEBUG_CRASH_TAG_EBP = -0x08
DEBUG_CRASH_MODE_EBP = 0x08
#: `mov dword [ebp-8], 0x00BD4BAC` - the assertion arm of the tag choice, which is what pins
#: `DEBUG_CRASH_TAG_EBP` to a slot holding a pointer rather than a count.
DEBUG_CRASH_TAG_STORE = 0x0043A89B
DEBUG_CRASH_TAG_STORE_BYTES = bytes.fromhex("c745f8ac4bbd00")
#: `mov ecx, [ebp-4]` - the engine's own read of the message pointer, feeding the `MessageBoxA`
#: five instructions later. It sits on the only path that reaches the raise, so asserting it is
#: what says `DEBUG_CRASH_MESSAGE_EBP` is live there.
DEBUG_CRASH_MESSAGE_READ = 0x0043AC2A
DEBUG_CRASH_MESSAGE_READ_BYTES = bytes.fromhex("8b4dfc6810100100")
#: `push edi ; push edi ; push edi ; push 0x04560123` - `RaiseException`'s four arguments, in
#: which `lpArguments` and `nNumberOfArguments` are both zero, so the exception record reaches the
#: dump with an empty `ExceptionInformation[]`. `..._RESUME` is the `call RaiseException` itself,
#: the first byte the window does not cover.
DEBUG_CRASH_RAISE = 0x0043AC57
DEBUG_CRASH_RAISE_BYTES = bytes.fromhex("5757576823015604")
DEBUG_CRASH_RAISE_RESUME = 0x0043AC5F
DEBUG_CRASH_RAISE_RESUME_BYTES = bytes.fromhex("ff15d801bd00")
#: The `call writeMiniDump` in the unhandled-exception filter, where every shutdown dump comes from;
#: `quiet-exit` redirects it.
WRITE_MINI_DUMP_CALL_FILTER = 0x0043D74E
WRITE_MINI_DUMP_CALL_FILTER_BYTES = bytes.fromhex("e82de7ffff")
#: `AsciiString`'s constructor-from-`const char *` and its destructor, and the CRT `stricmp` thunk
#: (`jmp dword [0x00BD06B4]`). All three are called from more than one cave.
ASCII_STRING_CTOR = 0x004374E0
ASCII_STRING_DTOR = 0x00435D50
#: `AsciiString`'s copy constructor - `__thiscall`, the source `AsciiString *` on the stack,
#: `ret 4`. It takes a reference rather than copying characters, which is how every by-value
#: `AsciiString` argument is built: reserve the slot, point `ecx` at it, call this.
ASCII_STRING_COPY_CTOR = 0x00435F30
STRICMP = 0x00A3CF40
#: The two string literals the boolean accessors compare against and fall back to.
YES_STRING = 0x00BD3D80
EMPTY_STRING = 0x00BD0C3F
COMMAND_LINE_PARSE_AND_MOUNT_MODS = 0x007BAA44
COMMAND_LINE_PARSE = 0x007BA7E1
COMMAND_LINE_STARTUP_TABLE = 0x00C35DA8
COMMAND_LINE_STARTUP_TABLE_COUNT = 0x10
COMMAND_LINE_MOD_HANDLER = 0x007BADB9
#: The end of the `-mod` handler: the store a second `-mod` overwrites. See `docs/multi-mod.md`.
COMMAND_LINE_MOD_HANDLER_TARGET = 0x007BAF06
COMMAND_LINE_MOD_HANDLER_TARGET_BYTES = bytes.fromhex(
    "8b0d6443de0081c1380d0000eb0c8b0d6443de0081c13c0d00008d45f050"
)
COMMAND_LINE_MOD_HANDLER_STORE = 0x007BAF24
COMMAND_LINE_MOD_HANDLER_STORE_BYTES = bytes.fromhex("e8c7ccc7ff")
SUBSYSTEM_LEGEND = 0x00DE337C
SUBSYSTEM_REGISTER = 0x00636404
SUBSYSTEM_INIT = 0x005B4A7C
SUBSYSTEM_LOAD_LEGEND_FILES = 0x005B4B9A
GLOBAL_DATA_VTABLE = 0x00C04220
#: Where `-mod` lands: a directory in `GLOBAL_DATA_MOD_DIR`, a file in `GLOBAL_DATA_MOD_BIG`.
#: `MOD_MOUNT_DIRECTORY` mounts every `*.BIG` under a directory.
GLOBAL_DATA_MOD_DIR = 0xD38
GLOBAL_DATA_MOD_BIG = 0xD3C
MOD_MOUNT_DIRECTORY = 0x00A14313
MOD_PREFER_LOCAL_FLAG = 0x00DEC490
MOD_DIRECTORY = 0x00DEC498
#: How the asset cache finds `asset.dat` (not through `TheFileSystem`): only the last `-mod` is
#: consulted, and within the cache the first registration wins.
ASSET_CACHE_LOAD = 0x0052C9B0
ASSET_CACHE_LOAD_BYTES = bytes.fromhex("b8c098b700e836055100")
ASSET_CACHE_READ_FILE = 0x0052C577
ASSET_CACHE_READ_FILE_BYTES = bytes.fromhex("b89698b700e86f095100")
ASSET_CACHE_MOD_BIG_TEST = 0x0052CA0C
ASSET_CACHE_MOD_BIG_TEST_BYTES = bytes.fromhex("8b450c85c0")
ASSET_CACHE_MOD_BIG_BRANCH = 0x0052CA11
ASSET_CACHE_MOD_BIG_BRANCH_BYTES = bytes.fromhex("0f84af0100006683780400")
ASSET_CACHE_REGISTER_GATE = 0x0052C6EF
ASSET_CACHE_REGISTER_GATE_BYTES = bytes.fromhex("8d85b4feffff50e88566500084c05959")
ASSET_CACHE_HAS_ASSET = 0x00A32D80
ASSET_CACHE_HAS_ASSET_BYTES = bytes.fromhex("8b44240485c07411")
#: The `asset.dat` name and `fopen` mode strings and their CRT slots; the third attempt's window is
#: the anchor that pins all four.
ASSET_DAT_NAME = 0x00BE8408
ASSET_DAT_NAME_BYTES = b"asset.dat\x00"
READ_BINARY_MODE = 0x00BE83EC
READ_BINARY_MODE_BYTES = b"rb\x00"
IMPORT_FOPEN = 0x00BD0554
IMPORT_FCLOSE = 0x00BD0560
ASSET_CACHE_WORKING_DIR_ATTEMPT = 0x0052CC1F
ASSET_CACHE_WORKING_DIR_ATTEMPT_BYTES = bytes.fromhex(
    "56ff156005bd0083c40c8d4df0c645fc01e87b9bf0ff8b1d5405bd0068ec83be00bf0884be0057ffd3"
)
#: The three file-system singletons and the two `TheFileSystem` entry points that consult the mod
#: directory. `FILE_SYSTEM_OPEN_FILE` tries `<modDir>\<file>` before the archives and restores the
#: logical name on a hit; `FILE_SYSTEM_GET_FILE_LIST_IN_DIRECTORY` merges the mod listing into the
#: same set under logical names, so a file present both loosely and in a `.big` is enumerated once.
FILE_SYSTEM = 0x00DEC598
LOCAL_FILE_SYSTEM = 0x00DEC9AC
ARCHIVE_FILE_SYSTEM = 0x00DEC9A4
ARCHIVE_FILE_SYSTEM_LOAD_ARCHIVE_SLOT = 0x14
FILE_SYSTEM_OPEN_FILE = 0x00A149A2
FILE_SYSTEM_GET_FILE_LIST_IN_DIRECTORY = 0x00A14D2B
FILE_SYSTEM_DOES_FILE_EXIST = 0x00A14AEB
FILE_SYSTEM_GET_FILE_INFO = 0x00A14BA8
#: `TheLocalFileSystem`'s vtable slots, as each of those four reaches them. Every mod branch ends
#: in one of these calls on the path it just formatted, which is what makes the branches
#: interchangeable enough to be rewritten as one loop. Derived in `docs/multi-mod.md`.
LOCAL_FILE_SYSTEM_OPEN_FILE_SLOT = 0x0C
LOCAL_FILE_SYSTEM_DOES_FILE_EXIST_SLOT = 0x14
LOCAL_FILE_SYSTEM_GET_FILE_LIST_SLOT = 0x18
LOCAL_FILE_SYSTEM_GET_FILE_INFO_SLOT = 0x28
#: `TheArchiveFileSystem`'s class vtable and the function its mount slot holds. `loadArchive`
#: takes the archive path and an **overwrite** flag; at `0x00A18384` an entry already in the
#: shared file map is kept when that flag is clear and replaced when it is set, and every mod
#: mount passes it set - so several mounted archives stack, last one winning.
ARCHIVE_FILE_SYSTEM_VTABLE = 0x00C9341C
ARCHIVE_FILE_SYSTEM_LOAD_ARCHIVE = 0x00A183AA
#: `GameEngine::init`'s call to the routine that builds `TheLocalFileSystem` and
#: `TheArchiveFileSystem` (`0x00A14275`). It runs long before either the subsystem registration or
#: the startup parse, which is what makes it safe to mount a mod from inside a switch handler.
FILE_SYSTEM_CREATE_CALL = 0x0063AE22
FILE_SYSTEM_CREATE_CALL_BYTES = bytes.fromhex("e84e943d00")
#: `sprintf`'s import slot and the format the file system builds every mod path with - note the
#: separator, which is why a mod directory is stored with a trailing one and the result carries
#: two. `AsciiString::operator=` is the assignment the `-mod` handler ends on.
SPRINTF_SLOT = 0x00BD06C0
MOD_PATH_FORMAT = 0x00BF5128
ASCII_STRING_ASSIGN = 0x00437BF0
#: The CRT thunks the caves call, each a `jmp` through the import table. `STRCMPI` is the
#: case-insensitive comparison (`_strcmpi`); `STRICMP` above, despite its name, thunks `strcmp`.
STRLEN = 0x00A3CF10
STRCPY = 0x00A3CF16
STRCMPI = 0x00A3D79A
#: `INI::load`. `INI_LOAD` is the public wrapper (`AsciiString` by value, load type, `Xfer *`);
#: `INI_LOAD_INNER` is where the work happens, including the `#define` pre-pass that fills
#: `INI_MACRO_TABLE` - a `std::map<AsciiString, AsciiString>` whose `insert` keeps the first
#: value, so a redefinition throws rather than replacing. `INI_MACRO_LOOKUP` is the read side.
INI_LOAD = 0x0042D97D
INI_LOAD_INNER = 0x0042CFC9
INI_LOAD_DIRECTORY = 0x0042DA40
INI_MACRO_TABLE = 0x00DC51D4
INI_MACRO_LOOKUP = 0x0042CDB1
#: `AsciiString::isEmpty` - null data pointer or zero length. The test the mod mount uses on both
#: `GlobalData` path fields.
ASCII_STRING_IS_EMPTY = 0x00401E64
GLOBAL_DATA_ACTIVE_MAP = 0xC
GLOBAL_DATA_STAGED_MAP = 0xAC0
NAME_KEY_TO_NAME = 0x00548700
#: `AsciiString::operator=(const AsciiString &)` - thiscall on the destination, one argument,
#: `ret 4`. It is what `GAME_LOGIC_START_NEW_GAME` uses at `0x007794DA` to promote the staged map
#: name over the active one. Distinct from `ASCII_STRING_ASSIGN`, which takes a `char *`.
ASCII_STRING_COPY = 0x00436030
#: `GameData`'s `ShellMapName`. Copying it over the active map name is how to ask for the shell map.
GLOBAL_DATA_SHELL_MAP = 0xAEC
#: `INI::parseUpgradeMask`, the parse function the engine's own `TriggeredBy` row names.
INI_PARSE_UPGRADE_MASK = 0x0066F603
#: The duration parser `MinLifetime` and `MaxLifetime` use: **milliseconds in, frames out**, scaled
#: by the live logic rate (`0x00D9F610`, written from the frame rate at `0x00644F11`). Naming it
#: here is what makes the bonus authorable in the same units as the lifetime it extends, and
#: rate-independent without the patch doing any arithmetic.
INI_PARSE_DURATION = 0x0073A429
COORD3D_GET_LENGTH = 0x004054F5
#: The comparison that is the whole authoring rule, inside that scan: the wide character the
#: shortcut is read from is the one after the first `&` in the fetched string.
#:
#:     0075a6b8  cmp ax, 0x26        ; L'&'
#:     0075a6bc  je  0x0075a6e1      ; take the next wide character
AMPERSAND_SCAN = 0x0075A6B0
#: `INI::parsePositiveNonZeroReal` - cdecl `(INI *, void *instance, void *store, const void *)`,
#: the sibling of `INI_PARSE_REAL` that stores the value and then throws the engine's INI
#: error when it is not above zero (`0x0042ED3D`). `AlphaCameraFadeOuterRadius` names it.
INI_PARSE_POSITIVE_REAL = 0x0042ED1C
INI_PARSE_POSITIVE_REAL_BYTES = bytes.fromhex("558bec51518b4d08")
#: `Matrix3D` as the engine lays it out: three rows of four floats, the rotation in the first
#: three of each row and the translation in the fourth. `0x004B135C` scaling exactly the nine
#: rotation entries and no translation is what fixes it.
MATRIX3D_ROW_STRIDE = 0x10
MATRIX3D_TRANSLATION = 0x0C
#: `INI::parseCoord3D` - cdecl `(INI *, void *instance, void *store, const void *)` like the other
#: field parsers, reading `X:`/`Y:`/`Z:` (the tokens at `0x00BD43F8`, `0x00BD43F4`, `0x00BD43F0`)
#: into three floats. 120 recovered fields name it, `AttachModel`'s own `Offset` among them.
INI_PARSE_COORD3D = 0x0042F247
INI_PARSE_COORD3D_BYTES = bytes.fromhex("56578b7c240c68f843bd00")
#: `INI_PARSE_REAL`'s opening bytes, for a patch that wraps it to assert it is still there.
INI_PARSE_REAL_BYTES = bytes.fromhex("8b4c24046a00e894efffff")
#: `100.0f`, the scale both percent derivations and the `DozerAIUpdate` ramp share.
FLOAT_HUNDRED = 0x00BD88D8
#: `kernel32!LoadLibraryA` in the IAT, which the engine calls for `D3D9.DLL` at `0x00525176`. The
#: `accel-module` cave calls it the same way for `sage_accel.dll`.
LOAD_LIBRARY_A_IAT = 0x00BD0188
#: `kernel32!GetProcAddress` in the IAT - how the probe reaches `D3DPERF_GetStatus`, which the
#: engine itself never resolves.
GET_PROC_ADDRESS_IAT = 0x00BD018C
#: `kernel32!QueryPerformanceCounter` in the IAT. Already called from seventeen engine sites, so
#: the indirect-call form a cave needs is a pattern the image already carries.
QUERY_PERFORMANCE_COUNTER_IAT = 0x00BD02E8
