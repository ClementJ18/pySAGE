"""Add `-headless`, `-renderEvery`, `-maxfps` and `-uncapped`, and stop drawing when asked to.

The display is not removed (hundreds of unchecked references use it); `GameClient::update`'s call to
`Display::draw` runs only every Nth frame (`-renderEvery N`; `-headless` is never). The device is
still created and assets still load. `-headless` also clears `UseFPSLimit` so the loop runs
uncapped; the logic rate is untouched, so the simulation stays bit-identical.

Derivation: `../docs/headless.md`.
"""

from __future__ import annotations

import struct

from ...addresses import (
    CLI_COUNT_REF,
    CLI_DISPATCH,
    CLI_TABLE,
    CLI_TABLE_BYTES,
    CLI_TABLE_ENTRIES,
    CLI_TABLE_FINGERPRINT,
    CLI_TABLE_REF,
    CRT_ATOI,
    DISPLAY_DRAW_VTABLE_SLOT,
    GAME_CLIENT_DRAW,
    GAME_CLIENT_DRAW_BYTES,
    GLOBAL_DATA,
    GLOBAL_DATA_FPS_LIMIT,
    GLOBAL_DATA_USE_FPS_LIMIT,
    THE_DISPLAY,
)
from ...asm import JE, JLE, JNE, Asm
from ...patcher import Patch
from ...utils import (
    allocate_section,
    apply_byte_patch,
    file_offset,
    find_section,
    read_cstring,
    u32,
    va_to_offset,
)

__all__ = [
    "COUNTER_OFFSET",
    "DEFAULT_RENDER_EVERY",
    "HeadlessPatch",
    "OPTIONS",
    "RENDER_EVERY_OFFSET",
    "SECTION_NAME",
    "STATE_SIZE",
    "TABLE_ALIGNMENT",
    "TAG",
    "TAG_OFFSET",
    "build_code",
    "build_section",
    "table_offset_in_section",
]

SECTION_NAME = ".hless"

#: IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. The cave is
#: code *and* the two words the handlers write and the draw hook reads, so unlike a pure-code
#: cave it has to be writable.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

# The state block, at the section base
TAG_OFFSET = 0x00
RENDER_EVERY_OFFSET = 0x04
COUNTER_OFFSET = 0x08
STATE_SIZE = 0x10

#: The layout this cave was built to, so a reader computing these offsets from *this* module can
#: tell whether the binary in front of it was patched by the same one. Same reasoning as
#: `live_bridge`'s buffer tag: importing the offsets keeps one process consistent and says
#: nothing about a `game.dat` patched last month.
TAG = 0x484C5331  # "HLS1"

#: The interval the cave starts at: 1, meaning every frame, which is stock behaviour. An applied
#: patch that is never asked for anything on the command line therefore changes nothing.
DEFAULT_RENDER_EVERY = 1

#: The table is a plain array of 8-byte rows indexed by `[ebx+eax*8]`, so alignment is not
#: required - but a dword table read off a 4-byte boundary is a needless cost on every argument.
TABLE_ALIGNMENT = 4

#: The options this patch adds, as `(name, handler label)`. Order is the order they take in the
#: table, after the stock 16.
#:
#: Matching is `_strnicmp` over equal lengths, so a new name collides with a stock one only if it
#: is the same length *and* the same letters. None of these are: the only stock options of the
#: same length are `-Watchdog` (9, against `-headless` and `-uncapped`) and `-fullVersion` (12,
#: against `-renderEvery`), and all three differ in the first character.
OPTIONS: tuple[tuple[str, str], ...] = (
    ("-headless", "h_headless"),
    ("-renderEvery", "h_render_every"),
    ("-maxfps", "h_maxfps"),
    ("-uncapped", "h_uncapped"),
)


def _mov_byte_global(a: Asm, register_disp: int, value: int) -> None:
    """`mov byte [eax+disp32], imm8` - a `GlobalData` field, with `eax` holding the object."""
    a.emit(0xC6, 0x80, u32(register_disp), value)


def build_code(base_va: int) -> Asm:
    """The cave's routines, assembled at `base_va`.

    Returned un-finished so the caller can read back each routine's address with
    `label_va` - the table needs them, and counting the bytes a second
    time by hand is exactly the arithmetic the assembler exists to remove.
    """
    render_every = base_va - STATE_SIZE + RENDER_EVERY_OFFSET
    counter = base_va - STATE_SIZE + COUNTER_OFFSET
    a = Asm(base_va)

    # The draw hook
    # Reached by `call` from `GameClient::update`, in place of the three instructions that fetch
    # `TheDisplay` and call its `draw`. The stock sequence already clobbers eax and ecx, and the
    # thiscall it makes clobbers edx, so all three are free here; nothing else is touched.
    a.label("draw_hook")
    a.emit(0x8B, 0x0D, u32(render_every))  # mov  ecx, [render_every]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc_short(JE, "draw_done")  # 0 -> never draw
    a.emit(0xA1, u32(counter))  # mov  eax, [counter]
    a.emit(0x40)  # inc  eax
    a.emit(0xA3, u32(counter))  # mov  [counter], eax
    a.emit(0x33, 0xD2)  # xor  edx, edx
    a.emit(0xF7, 0xF1)  # div  ecx           ; edx = counter % n
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc_short(JNE, "draw_done")  # not this frame's turn
    # The displaced instructions, verbatim.
    a.emit(0x8B, 0x0D, u32(THE_DISPLAY))  # mov  ecx, [TheDisplay]
    a.emit(0x8B, 0x01)  # mov  eax, [ecx]
    a.emit(0xFF, 0x50, DISPLAY_DRAW_VTABLE_SLOT)  # call [eax+0x30]
    a.label("draw_done")
    a.emit(0xC3)  # ret

    # -headless
    # Never draw, and stop pacing the loop against the wall clock. Deliberately not a bundle of
    # the stock options: `-noshellmap` and `-noaudio` do more than write the fields they name,
    # and reproducing them here would reproduce them wrongly.
    a.label("h_headless")
    a.emit(0x83, 0x25, u32(render_every), 0x00)  # and  dword [render_every], 0
    a.emit(0xA1, u32(GLOBAL_DATA))  # mov  eax, [TheWritableGlobalData]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "headless_out")
    _mov_byte_global(a, GLOBAL_DATA_USE_FPS_LIMIT, 0)  # UseFPSLimit = No
    a.label("headless_out")
    a.emit(0xB8, u32(1))  # mov  eax, 1        ; one argument consumed
    a.emit(0xC3)  # ret

    # -renderEvery <n>
    a.label("h_render_every")
    a.emit(0x83, 0x7C, 0x24, 0x08, 0x01)  # cmp  dword [esp+8], 1
    a.jcc_short(JLE, "render_every_bare")  # no argument follows
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov  eax, [esp+4]  ; &argv[i]
    a.emit(0xFF, 0x70, 0x04)  # push dword [eax+4]  ; argv[i+1]
    a.emit(0xFF, 0x15, u32(CRT_ATOI))  # call [atoi]
    a.emit(0x59)  # pop  ecx
    a.emit(0xA3, u32(render_every))  # mov  [render_every], eax
    a.emit(0xB8, u32(2))  # mov  eax, 2
    a.emit(0xC3)  # ret
    a.label("render_every_bare")
    a.emit(0xB8, u32(1))  # mov  eax, 1
    a.emit(0xC3)  # ret

    # -maxfps <n>
    a.label("h_maxfps")
    a.emit(0x83, 0x7C, 0x24, 0x08, 0x01)  # cmp  dword [esp+8], 1
    a.jcc_short(JLE, "maxfps_bare")
    a.emit(0x8B, 0x44, 0x24, 0x04)  # mov  eax, [esp+4]
    a.emit(0xFF, 0x70, 0x04)  # push dword [eax+4]
    a.emit(0xFF, 0x15, u32(CRT_ATOI))  # call [atoi]
    a.emit(0x59)  # pop  ecx
    a.emit(0x8B, 0x0D, u32(GLOBAL_DATA))  # mov  ecx, [TheWritableGlobalData]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc_short(JE, "maxfps_out")
    a.emit(0x89, 0x41, GLOBAL_DATA_FPS_LIMIT)  # mov  [ecx+0x28], eax
    a.emit(0xC6, 0x41, GLOBAL_DATA_USE_FPS_LIMIT, 0x01)  # mov  byte [ecx+0x26], 1
    a.label("maxfps_out")
    a.emit(0xB8, u32(2))  # mov  eax, 2
    a.emit(0xC3)  # ret
    a.label("maxfps_bare")
    a.emit(0xB8, u32(1))  # mov  eax, 1
    a.emit(0xC3)  # ret

    # -uncapped
    a.label("h_uncapped")
    a.emit(0xA1, u32(GLOBAL_DATA))  # mov  eax, [TheWritableGlobalData]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc_short(JE, "uncapped_out")
    _mov_byte_global(a, GLOBAL_DATA_USE_FPS_LIMIT, 0)  # UseFPSLimit = No
    a.label("uncapped_out")
    a.emit(0xB8, u32(1))  # mov  eax, 1
    a.emit(0xC3)  # ret

    return a


def build_section(base_va: int, stock_table: bytes) -> bytes:
    """The whole cave: state block, routines, option names, then the extended table.

    `stock_table` is the engine's own 16 rows, read out of the image being patched rather than
    written down here - their name pointers are absolute addresses into `.rdata`, so copying the
    bytes is both simpler and more honest than rebuilding rows this patch does not own.
    """
    state = bytearray(STATE_SIZE)
    struct.pack_into("<III", state, 0, TAG, DEFAULT_RENDER_EVERY, 0)

    asm = build_code(base_va + STATE_SIZE)
    code = asm.finish()

    strings = bytearray()
    string_vas: dict[str, int] = {}
    strings_va = base_va + STATE_SIZE + len(code)
    for name, _ in OPTIONS:
        string_vas[name] = strings_va + len(strings)
        strings.extend(name.encode("ascii") + b"\x00")

    table_va = strings_va + len(strings)
    padding = -table_va % TABLE_ALIGNMENT
    table_va += padding

    table = bytearray(stock_table)
    for name, label in OPTIONS:
        table.extend(struct.pack("<II", string_vas[name], asm.label_va(label)))

    return bytes(state) + code + bytes(strings) + b"\x00" * padding + bytes(table)


def table_offset_in_section(base_va: int, stock_table: bytes) -> int:
    """Where `build_section` puts the table, as an offset from the section base.

    Recomputed by laying the section out rather than remembered, so `HeadlessPatch.apply`
    and `HeadlessPatch.verify` cannot disagree about it.
    """
    return len(build_section(base_va, stock_table)) - len(stock_table) - len(OPTIONS) * 8


class HeadlessPatch(Patch):
    name = "headless"
    author = "officialNecro"
    runtime_verified = "yes"
    experimental = True
    description = (
        "Add -headless / -renderEvery / -maxfps / -uncapped, and stop drawing when asked to. "
        "Command-line flags on game.dat, no INI change"
    )

    def apply(self, data: bytearray) -> None:
        stock_table = self._stock_table(data)
        self._check_sites(data)

        base_va = allocate_section(
            data, SECTION_NAME, lambda base: build_section(base, stock_table), _CHARACTERISTICS
        )
        table_va = base_va + table_offset_in_section(base_va, stock_table)
        hook_va = base_va + STATE_SIZE  # `draw_hook` is the cave's first routine

        table_ref = file_offset(data, CLI_TABLE_REF, "the command-line table pointer")
        count_ref = file_offset(data, CLI_COUNT_REF, "the command-line table length")
        draw = file_offset(data, GAME_CLIENT_DRAW, "the Display::draw call")

        apply_byte_patch(
            data,
            table_ref,
            b"\xbb" + u32(CLI_TABLE),
            b"\xbb" + u32(table_va),
            f"command-line table -> the {SECTION_NAME} copy",
        )
        apply_byte_patch(
            data,
            count_ref,
            bytes((0x6A, CLI_TABLE_ENTRIES)),
            bytes((0x6A, CLI_TABLE_ENTRIES + len(OPTIONS))),
            f"command-line table length -> {CLI_TABLE_ENTRIES + len(OPTIONS)}",
        )
        apply_byte_patch(
            data,
            draw,
            GAME_CLIENT_DRAW_BYTES,
            self._draw_redirect(hook_va),
            f"GameClient::update Display::draw -> the {SECTION_NAME} hook",
        )

    @staticmethod
    def _draw_redirect(hook_va: int) -> bytes:
        """`call <hook>` padded with `nop` to the length of the sequence it replaces."""
        call = b"\xe8" + struct.pack("<i", hook_va - (GAME_CLIENT_DRAW + 5))
        return call + b"\x90" * (len(GAME_CLIENT_DRAW_BYTES) - len(call))

    @staticmethod
    def _stock_table(data: bytes | bytearray) -> bytes:
        """The engine's 16 rows, checked against four of their names before being copied.

        A build whose table has moved, or whose option list differs, fails here - rather than
        having whatever sits at `0x00C35DA8` copied into the cave and dispatched to.
        """
        off = va_to_offset(data, CLI_TABLE)
        if off is None:
            raise ValueError(f"{CLI_TABLE:#010x} is not mapped - not the expected build")
        table = bytes(data[off : off + CLI_TABLE_BYTES])
        if len(table) != CLI_TABLE_BYTES:
            raise ValueError("the command-line table runs past the end of the image")
        for index, expected in CLI_TABLE_FINGERPRINT.items():
            name_va = struct.unpack_from("<I", table, index * 8)[0]
            got = read_cstring(data, name_va)
            if got != expected:
                raise ValueError(
                    f"command-line table row {index} names {got!r}, expected {expected!r} - "
                    f"{CLI_TABLE:#010x} is not this build's option table"
                )
        return table

    @staticmethod
    def _check_sites(data: bytes | bytearray) -> None:
        """Raise unless both of the things the cave is built around still hold.

        Everything here is checked **before** the section is allocated, so a wrong build leaves
        the image untouched rather than carrying an orphaned cave. `apply_byte_patch` asserts the
        two edited sites again on the way past, which is what makes the failure name the site.
        """
        off = file_offset(data, CLI_DISPATCH, "the command-line dispatcher")
        if bytes(data[off : off + 3]) != bytes.fromhex("558bec"):  # push ebp / mov ebp, esp
            raise ValueError(
                f"{CLI_DISPATCH:#010x} is not a function entry - the command-line dispatcher is "
                "not this build's, so the extended table would be handed to the wrong code"
            )
        off = file_offset(data, GAME_CLIENT_DRAW, "the Display::draw call")
        got = bytes(data[off : off + len(GAME_CLIENT_DRAW_BYTES)])
        if got != GAME_CLIENT_DRAW_BYTES:
            raise ValueError(
                f"{GAME_CLIENT_DRAW:#010x} holds {got.hex()}, expected "
                f"{GAME_CLIENT_DRAW_BYTES.hex()} - GameClient::update's draw call is not this "
                "build's, so the hook would displace the wrong instructions"
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        problems: list[str] = []
        section = find_section(data, SECTION_NAME)
        if section is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        base_va, _, _ = section

        try:
            stock_table = self._stock_table(data)
        except ValueError as exc:
            return [f"cannot read the stock command-line table: {exc}"]

        table_va = base_va + table_offset_in_section(base_va, stock_table)
        hook_va = base_va + STATE_SIZE
        expected_count = CLI_TABLE_ENTRIES + len(OPTIONS)

        for va, expected, what in (
            (CLI_TABLE_REF, b"\xbb" + u32(table_va), "the command-line table pointer"),
            (CLI_COUNT_REF, bytes((0x6A, expected_count)), "the command-line table length"),
            (GAME_CLIENT_DRAW, self._draw_redirect(hook_va), "the Display::draw redirect"),
        ):
            off = va_to_offset(data, va)
            got = None if off is None else bytes(data[off : off + len(expected)])
            if got != expected:
                problems.append(
                    f"{what} @{va:#010x}: expected {expected.hex()}, got "
                    f"{'unmapped' if got is None else got.hex()}"
                )

        table_off = va_to_offset(data, table_va)
        if table_off is None:
            problems.append(f"the {SECTION_NAME} table @{table_va:#010x} is not mapped")
            return problems

        copied = bytes(data[table_off : table_off + CLI_TABLE_BYTES])
        if copied != stock_table:
            problems.append(
                f"the {SECTION_NAME} copy of the stock 16 rows does not match "
                f"{CLI_TABLE:#010x} - the table was built from a different image"
            )
        for index, (option, _) in enumerate(OPTIONS):
            row = table_off + CLI_TABLE_BYTES + index * 8
            name_va, handler_va = struct.unpack_from("<II", data, row)
            if read_cstring(data, name_va) != option:
                problems.append(f"appended row {index} does not name {option!r}")
            if not base_va <= handler_va < table_va:
                problems.append(
                    f"appended row {index} ({option}) dispatches to {handler_va:#010x}, which is "
                    f"outside the {SECTION_NAME} code"
                )
        return problems
