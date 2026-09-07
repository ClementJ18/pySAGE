"""The `CommandSet` button-limit patch, as a :class:`~..patcher.Patch`.

Raises `MAX_COMMANDS_PER_COMMAND_SET` from its stock 33 to any ``count`` in 34..127 on the ROTWK
SAGE-engine `game.dat` build ``2.01.2614.37001`` (engine-level: it benefits every mod on that
build, not one in particular), so a `CommandSet` INI block may define more than 33 buttons. See
``../docs/commandset-button-limit.md`` for the derivation of every site.

**Composition.** Order-independent: it allocates its cave past every existing section and
:meth:`verify` finds it by name, it shares no edited byte with any other bundled patch, and it
derives its table only from the stock one, which nothing else rewrites. See the composition
contract on :class:`~..patcher.Patch`.

Three phases make up the patch:

* **Phase 1** grows the `CommandSet` object from ``0xA0`` to ``0x14 + count*4 + 8`` bytes. The
  ``m_command[]`` array stays at ``+0x14``; the trailing count/flag fields move from ``0x98/0x9c``
  to just past the enlarged array. Fourteen instruction immediates (the allocation size, the
  ctor's ``33`` fills, every field offset, and the AI's scan bound below) are rewritten.
* **Phase 2** builds a fresh ``count``-slot field-parse table plus the new ``"34".."count"`` slot
  names in an appended ``.cmdext`` PE section, and repoints the two code references to it.
* **Phase 3** appends a clamp routine to that same section and routes
  `ControlBar::populate`'s visible-range fetch through it, so a paging window that reaches past
  the array or past the 33 on-screen widgets is trimmed instead of crashing (below).

Together these let a `CommandSet` *define* and *store* up to ``count`` buttons. The ControlBar
still *draws* only 33 at a time; reach the rest by paging with ``PUSH_VISIBLE_COMMAND_RANGE``.
Widening the drawing loops instead is a dead end — those ``getCommandButton``-caller loops
populate the ControlBar's fixed 33-slot UI arrays, so raising their bounds overruns those arrays
and crashes. See ``../docs/push-visible-command-range.md``.

The visible-range clamp
-----------------------
`ControlBar::populate` reads the top ``{start, count}`` record of the paging stack once, at
`CONTROL_BAR_RANGE_FETCH`, then walks it in **three** loops. Only the first stops at the
ControlBar's 33 button widgets. The other two — the revive pass and the production pass — run
``count`` iterations whatever ``count`` is, and each steps through the 33-entry widget array at
``ControlBar+0xDC`` alongside the slot index. So an oversized record runs *two* arrays off their
ends: the widget array past 33, and ``m_command[]`` past ``count`` slots, where the object's own
count field gets dereferenced as a `CommandButton` and the game faults.

Both ways of writing an oversized record are ordinary INI. ``InitialVisible`` above 33 seeds the
record with ``{0, InitialVisible}`` directly, and a ``PUSH_VISIBLE_COMMAND_RANGE`` button whose
``CommandRangeStart + CommandRangeCount`` overshoots writes one on click.

Phase 3 trims the record in place, right where it is read, to ``0 <= start < count`` and
``0 <= visible <= min(33, count - start)``. Every loop downstream then walks a window that is
inside both arrays, out-of-range slots simply are not visited, and a page shows the buttons it
has. Clamping the fetch is also the cheap form: the three loops would otherwise need three hooks,
and two of them have no spare bytes.

The AI's scan bound
-------------------
One ``getCommandButton``-caller loop *is* widened, because it populates nothing:
``BuildAssistant::canMakeUnit`` walks a producer's set to decide whether the AI may build or
revive something, and reads each button rather than writing it into a fixed array. Left at 33 it
would make every button the rest of this patch newly allows - the paged ones - invisible to the
AI, so a mod paging its hero roster past slot 33 would get buildings the player can recruit from
and the AI cannot. ``getCommandButton`` is an unchecked ``[this + i*4 + 0x14]``, so the bound
*is* the bound: ``count`` visits indices ``0..count-1`` and stops one short of the count field
that Phase 1 places at index ``count``.

Why the ceiling is 127
----------------------
Six of the Phase-1 sites encode the limit as a **signed 8-bit immediate** (``6a NN`` ``push``,
``83 fa NN`` / ``83 fb NN`` / ``83 7d f8 NN`` ``cmp``), so 127 is the largest value that survives
sign extension: at 128 the byte ``0x80`` decodes as ``-128``, and since one of those pushes
supplies ``rep stosd``'s counter the constructor would zero ~4 billion dwords. Going beyond 127
means re-encoding those instructions as imm32, which is 3 bytes longer apiece and therefore needs
relocated code (a trampoline into a cave), not an in-place byte patch.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from sage_ini.engine import Engine, LimitDelta

from ..addresses import (
    CAN_MAKE_UNIT_SCAN_BOUND,
    CONTROL_BAR_GET_VISIBLE_RANGE,
    CONTROL_BAR_MAX_VISIBLE,
    CONTROL_BAR_RANGE_COUNT_EBP,
    CONTROL_BAR_RANGE_FETCH,
    CONTROL_BAR_RANGE_FETCH_BYTES,
    CONTROL_BAR_RANGE_FETCH_RESUME,
    CONTROL_BAR_RANGE_LOOP_PRODUCTION,
    CONTROL_BAR_RANGE_LOOP_PRODUCTION_BYTES,
    CONTROL_BAR_RANGE_LOOP_REVIVE,
    CONTROL_BAR_RANGE_LOOP_REVIVE_BYTES,
    CONTROL_BAR_RANGE_START_EBP,
    IMAGE_BASE,
)
from ..asm import JAE, JG, JLE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, image_base

if TYPE_CHECKING:
    import argparse

# --- fixed facts about the target build (VA, ImageBase 0x400000) ---
_TABLE_VA = 0xC4F3D8  # the original 34-entry CommandSet field-parse table
_PARSE_COMMAND_BUTTON = 0x0080C9E1  # parseCommandButton (fn of every slot entry)
_SECTION_NAME = ".cmdext"  # the cave holding the enlarged table + the new slot names
_PARSER_TABLE_REF = 0x32065C  # `push _TABLE_VA` - parser's table pointer (repointed in Phase 2)
_GETFIELDPARSE_REF = 0x31C2EE  # `mov eax, _TABLE_VA` - getFieldParse's table pointer (Phase 2)
_ORIGINAL_MAX = 33
_ORIGINAL_OBJ_SIZE = 0xA0
_ORIGINAL_COUNT_OFF = 0x98  # count / InitialVisible field in the 0xA0 object
_ORIGINAL_FLAG_OFF = 0x9C
_ARRAY_OFF = 0x14  # m_command[] base within the object (unchanged by the patch)

#: File offset of the `push <object size>` the allocator uses. It is the one Phase-1 site that
#: encodes the limit as a full imm32, which makes it the site `detect` reads the count back from.
_ALLOC_SIZE_SITE = 0x320298

# The AI's set-walk bound in `BuildAssistant::canMakeUnit` (see the module docstring). Taken from
# `..addresses` rather than written as an offset here, because `ai-revive-gate` patches the same
# function six bytes earlier and both must name one address. Raw offset equals `va - ImageBase`
# throughout this build's `.text`, which is what every offset below already assumes.
_AI_SCAN_BOUND = CAN_MAKE_UNIT_SCAN_BOUND - IMAGE_BASE

#: The visible-range fetch Phase 3 reroutes, and the sites that make the reroute meaningful. The
#: two loop heads are read-only anchors: they are what the clamp protects, so a build where they
#: are not the shape this patch was derived against must not be clamped silently.
_RANGE_FETCH_SITE = CONTROL_BAR_RANGE_FETCH - IMAGE_BASE
_RANGE_LOOP_ANCHORS = {
    CONTROL_BAR_RANGE_LOOP_REVIVE - IMAGE_BASE: CONTROL_BAR_RANGE_LOOP_REVIVE_BYTES,
    CONTROL_BAR_RANGE_LOOP_PRODUCTION - IMAGE_BASE: CONTROL_BAR_RANGE_LOOP_PRODUCTION_BYTES,
}

# IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ. The section carries the
# field-parse table and the slot names as data and the Phase-3 clamp as code, so it needs both.
_SECTION_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000

#: Largest limit this patch can install. Bounded by the signed-imm8 encoding of five Phase-1
#: sites (see the module docstring), not by the object layout or the new section.
MAX_COUNT = 127

#: Smallest limit worth installing - anything at or below the stock 33 is a no-op.
MIN_COUNT = _ORIGINAL_MAX + 1


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _imm8(value: int) -> bytes:
    """The limit as a signed 8-bit immediate, refusing values that would sign-extend negative."""
    if not 0 <= value <= 127:
        raise ValueError(
            f"{value} does not fit a signed imm8 (max 127); this patch site would encode it as "
            f"{value - 256}"
        )
    return bytes([value])


def _slot_names(n: int) -> bytes:
    """The NUL-terminated ``"34".."n"`` field names the enlarged table points at. Slots 1..33
    reuse the original table's pointers, so only the new ones need storing."""
    return b"".join(str(k).encode("ascii") + b"\x00" for k in range(_ORIGINAL_MAX + 1, n + 1))


def _clamp_offset(n: int) -> int:
    """Where the Phase-3 routine starts within the ``.cmdext`` section: past the ``n``-slot table
    and the slot names it points into."""
    return (n + 2) * 16 + len(_slot_names(n))


def build_clamp(base_va: int, n: int) -> bytes:
    """`ControlBar::populate`'s visible-range fetch, plus the clamp that makes it safe.

    Replaces `CONTROL_BAR_RANGE_FETCH` whole, so it begins by doing exactly what those eleven
    bytes did - ``getVisibleRange(&range)`` on the ControlBar in ``ebx`` - and returns to
    `CONTROL_BAR_RANGE_FETCH_RESUME` with the record trimmed:

    * ``start`` outside ``0 .. n-1`` leaves nothing to draw, so the count goes to zero. The
      test is unsigned, which folds a negative ``CommandRangeStart`` into the same arm.
    * the count is capped at the ControlBar's 33 widgets and at ``n - start``, whichever binds
      first, and a negative one becomes zero.

    ``start`` itself is left alone: with a zero count no loop reads it. Only ``eax``, ``ecx``,
    ``edx`` and the flags are touched, all of which the stock ``call`` already clobbered, and
    ``ebx`` - the ControlBar the caller keeps using - is only read."""
    start, count = CONTROL_BAR_RANGE_START_EBP & 0xFF, CONTROL_BAR_RANGE_COUNT_EBP & 0xFF
    a = Asm(base_va)
    a.emit(0x8D, 0x45, start)  # lea  eax, [ebp+start]   ; the displaced fetch, verbatim
    a.emit(0x50)  # push eax
    a.emit(0x8B, 0xCB)  # mov  ecx, ebx           ; the ControlBar
    a.call_absolute(CONTROL_BAR_GET_VISIBLE_RANGE)  # call getVisibleRange(&range)

    a.emit(0x8B, 0x45, start)  # mov  eax, [ebp+start]
    a.emit(0x8B, 0x4D, count)  # mov  ecx, [ebp+count]
    a.emit(0x83, 0xF8, _imm8(n))  # cmp  eax, n
    a.jcc(JAE, "empty")  # start past the array (or negative) -> draw nothing

    a.emit(0x83, 0xF9, _imm8(CONTROL_BAR_MAX_VISIBLE))  # cmp  ecx, 33
    a.jcc(JLE, "fits_screen")
    a.emit(0xB9, _u32(CONTROL_BAR_MAX_VISIBLE))  # mov  ecx, 33
    a.label("fits_screen")

    a.emit(0xBA, _u32(n))  # mov  edx, n
    a.emit(0x2B, 0xD0)  # sub  edx, eax           ; slots left after start
    a.emit(0x3B, 0xCA)  # cmp  ecx, edx
    a.jcc(JLE, "fits_array")
    a.emit(0x8B, 0xCA)  # mov  ecx, edx
    a.label("fits_array")

    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JG, "store")  # a negative count falls through to zero
    a.label("empty")
    a.emit(0x33, 0xC9)  # xor  ecx, ecx
    a.label("store")
    a.emit(0x89, 0x4D, count)  # mov  [ebp+count], ecx
    a.jmp_absolute(CONTROL_BAR_RANGE_FETCH_RESUME)
    return a.finish()


class CommandSetLimitPatch(Patch):
    """Raise the `CommandSet` button limit from the stock 33 to ``count`` (34..127)."""

    name = "commandset-limit"
    author = "officialNecro"
    description = (
        "Raise the CommandSet button limit from 33 to N, so a CommandSet block may list N "
        "buttons. The ControlBar still draws 33 at a time: reach the rest with "
        "PUSH_VISIBLE_COMMAND_RANGE paging buttons. A paging window or an InitialVisible that "
        "overshoots is trimmed to what fits instead of crashing the game"
    )

    def __init__(self, count: int = 64):
        if not MIN_COUNT <= count <= MAX_COUNT:
            hint = (
                " (128+ would need imm32 re-encoding of five sites, which does not fit in place)"
                if count > MAX_COUNT
                else ""
            )
            raise ValueError(f"count must be in {MIN_COUNT}..{MAX_COUNT}, got {count}{hint}")
        self.count = count

    def __str__(self) -> str:
        return f"{self.name} (N={self.count})"

    def apply(self, data: bytearray) -> None:
        n = self.count
        self._check_loop_anchors(data)
        new_base_va = allocate_section(
            data,
            _SECTION_NAME,
            lambda section_va: self._compute_section(data, section_va, n),
            _SECTION_CHARACTERISTICS,
        )
        self._link_table(data, new_base_va)
        apply_byte_patch(
            data,
            _RANGE_FETCH_SITE,
            CONTROL_BAR_RANGE_FETCH_BYTES,
            self._clamp_jump(new_base_va, n),
            "P3 visible-range fetch -> .cmdext clamp",
        )
        for file_off, old, new, note in self._phase1_edits(n):
            apply_byte_patch(data, file_off, old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Structural check that ``data`` already carries this patch at ``count`` (an empty list
        == verified). Locates the ``.cmdext`` cave, recomputes its content, the two repointed
        references, the Phase-3 jump and the Phase-1 site bytes for ``count``, and compares them
        to what is on disk. Reads only via ``struct`` + the section table, so it needs no
        disassembler."""
        n = self.count
        problems: list[str] = []
        located = find_section(data, _SECTION_NAME)
        if located is None:
            return [f"no {_SECTION_NAME} section: the file does not carry this patch"]
        new_base_va, table_off, _vsize = located

        try:
            content = self._compute_section(data, new_base_va, n)
        except (ValueError, struct.error) as exc:
            return [f"cannot recompute the expected table (wrong build?): {exc}"]

        if bytes(data[table_off : table_off + len(content)]) != content:
            problems.append(
                f"the {_SECTION_NAME} field-parse table / slot names / clamp do not match N={n}"
            )

        for ref_off, label in (
            (_PARSER_TABLE_REF, "parser table ref"),
            (_GETFIELDPARSE_REF, "getFieldParse ref"),
        ):
            got = struct.unpack_from("<I", data, ref_off + 1)[0]
            if got != new_base_va:
                problems.append(
                    f"{label} @0x{ref_off:x} -> 0x{got:08x}, expected 0x{new_base_va:08x}"
                )

        expected = self._clamp_jump(new_base_va, n)
        got = bytes(data[_RANGE_FETCH_SITE : _RANGE_FETCH_SITE + len(expected)])
        if got != expected:
            problems.append(
                f"P3 visible-range fetch @0x{_RANGE_FETCH_SITE:x}: expected {expected.hex()}, "
                f"got {got.hex()}"
            )

        for file_off, _old, new, note in self._phase1_edits(n):
            got = bytes(data[file_off : file_off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{file_off:x}: expected {new.hex()}, got {got.hex()}")
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> CommandSetLimitPatch | None:
        """Recognise this patch **and recover its N** from ``data``.

        The default probe cannot: it would ask `verify` about N=64 and call every other limit
        absent. The allocator's ``push <object size>`` is an imm32 holding
        ``0x14 + N*4 + 8``, so N reads straight back out of it, and `verify` then checks all
        fourteen sites against that N."""
        if find_section(data, _SECTION_NAME) is None:
            return None
        try:
            obj_size = struct.unpack_from("<I", data, _ALLOC_SIZE_SITE + 1)[0]
        except struct.error:
            return None
        count, remainder = divmod(obj_size - _ARRAY_OFF - 8, 4)
        if remainder or not MIN_COUNT <= count <= MAX_COUNT:
            return None
        patch = cls(count)
        return None if patch.verify(data) else patch

    def ini_surface(self) -> Engine:
        """The raised ceiling and the Phase-3 clamp, as the engine limits the lint rules read.
        The ControlBar's separate 33-button *display* ceiling is untouched, so it is not named
        here and stays at its stock value."""
        return Engine(
            limits=(
                LimitDelta("commandset.max_slots", self.count, self.name),
                LimitDelta("commandset.range_clamped", 1, self.name),
            )
        )

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--count",
            type=int,
            default=64,
            metavar="N",
            help=f"new CommandSet button limit ({MIN_COUNT}..{MAX_COUNT}); default 64",
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> CommandSetLimitPatch:
        return cls(count=args.count)

    def _compute_section(self, data: bytes | bytearray, section_va: int, n: int) -> bytes:
        """Return the ``.cmdext`` content for ``n`` slots placed at ``section_va``: the enlarged
        field-parse table, the ``"34".."n"`` slot names it points into, and the Phase-3 clamp.
        Reads the original 34-entry table to reuse its slot-name pointers and parse fn; raises on
        an unrecognised build (slot 0's parse fn not where this build keeps it)."""
        tab_foff = _TABLE_VA - image_base(data)
        original = [struct.unpack_from("<IIII", data, tab_foff + i * 16) for i in range(34)]
        parse_fn = original[0][1]
        if parse_fn != _PARSE_COMMAND_BUTTON:
            raise ValueError(
                f"unexpected build: slot 0 parse fn is 0x{parse_fn:08x}, "
                f"expected 0x{_PARSE_COMMAND_BUTTON:08x}"
            )
        initial_visible = original[33]  # the "InitialVisible" field entry

        table_size = (n + 2) * 16  # n slots + InitialVisible + NULL terminator
        str_area_va = section_va + table_size

        # slot name strings "34".."n" (slots 1..33 reuse the original pointers)
        str_bytes = bytearray()
        str_va: dict[int, int] = {}
        for k in range(_ORIGINAL_MAX + 1, n + 1):
            str_va[k] = str_area_va + len(str_bytes)
            str_bytes += str(k).encode("ascii") + b"\x00"

        initvis_off = _ARRAY_OFF + n * 4
        table = bytearray()
        for i in range(n):
            name_ptr = original[i][0] if i < _ORIGINAL_MAX else str_va[i + 1]
            table += struct.pack("<IIII", name_ptr, parse_fn, i, _ARRAY_OFF)
        table += struct.pack("<IIII", initial_visible[0], initial_visible[1], 0, initvis_off)
        table += struct.pack("<IIII", 0, 0, 0, 0)  # terminator
        assert len(table) == table_size
        assert bytes(str_bytes) == _slot_names(n)
        content = bytes(table) + bytes(str_bytes)
        assert len(content) == _clamp_offset(n)
        return content + build_clamp(section_va + _clamp_offset(n), n)

    @staticmethod
    def _clamp_jump(section_va: int, n: int) -> bytes:
        """The eleven bytes that replace the stock visible-range fetch: a ``jmp`` to the clamp,
        then ``nop`` out to the end of the displaced span. The span is a whole number of
        instructions with no inbound branch past its first byte, so the padding is never
        executed and only keeps the site the length `verify` expects."""
        clamp_va = section_va + _clamp_offset(n)
        jump = b"\xe9" + struct.pack("<i", clamp_va - (CONTROL_BAR_RANGE_FETCH + 5))
        return jump.ljust(len(CONTROL_BAR_RANGE_FETCH_BYTES), b"\x90")

    @staticmethod
    def _check_loop_anchors(data: bytes | bytearray) -> None:
        """Refuse to clamp a build whose uncapped range loops are not the ones this was derived
        against. Nothing else in the patch would notice: the clamp would apply cleanly and simply
        guard code that is no longer there."""
        for file_off, expected in _RANGE_LOOP_ANCHORS.items():
            got = bytes(data[file_off : file_off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"unexpected build: ControlBar range loop @0x{file_off:x} is "
                    f"{got.hex()}, expected {expected.hex()}"
                )

    def _link_table(self, data: bytearray, new_base_va: int) -> None:
        """Repoint the two code references from the old table VA to the new ``.cmdext`` table."""
        new_ptr, old_ptr = _u32(new_base_va), _u32(_TABLE_VA)
        apply_byte_patch(
            data,
            _PARSER_TABLE_REF,
            b"\x68" + old_ptr,
            b"\x68" + new_ptr,
            "P2 parser table push -> .cmdext",
        )
        apply_byte_patch(
            data,
            _GETFIELDPARSE_REF,
            b"\xb8" + old_ptr,
            b"\xb8" + new_ptr,
            "P2 getFieldParse mov -> .cmdext",
        )

    def _phase1_edits(self, n: int) -> list[tuple[int, bytes, bytes, str]]:
        """The 15 ``(file_offset, original bytes, patched bytes, note)`` edits that grow the
        object for ``n`` slots and let the AI walk all of them. Shared by :meth:`apply` (writes
        ``patched`` if ``original`` matches) and :meth:`verify` (asserts ``patched`` is
        present)."""
        count_off = _ARRAY_OFF + n * 4  # trailing count field, just past the array
        flag_off = count_off + 4
        obj_size = count_off + 8
        nb = _imm8(n)  # the five sites below encode the limit as a signed byte
        old_count, new_count = _u32(_ORIGINAL_COUNT_OFF), _u32(count_off)
        old_flag, new_flag = _u32(_ORIGINAL_FLAG_OFF), _u32(flag_off)

        return [
            (
                0x320298,
                b"\x68" + _u32(_ORIGINAL_OBJ_SIZE),
                b"\x68" + _u32(obj_size),
                "P1 alloc size",
            ),
            (0x40C97E, b"\x6a\x21", b"\x6a" + nb, "P1 ctor count/stosd push"),
            (0x40C987, b"\x89\x8e" + old_count, b"\x89\x8e" + new_count, "P1 ctor count store"),
            (0x40C980, b"\x89\x86" + old_flag, b"\x89\x86" + new_flag, "P1 ctor flag store"),
            (0x40C8FC, b"\x83\xfa\x21", b"\x83\xfa" + nb, "P1 set bound"),
            (0x40C909, b"\x8d\x81" + old_count, b"\x8d\x81" + new_count, "P1 set &count"),
            (
                0x40C8EF,
                b"\x83\xb9" + old_flag + b"\x01",
                b"\x83\xb9" + new_flag + b"\x01",
                "P1 set flag guard",
            ),
            (
                0x40C8DB,
                b"\x83\xa1" + old_count + b"\x00",
                b"\x83\xa1" + new_count + b"\x00",
                "P1 reset count",
            ),
            (
                0x40C8D2,
                b"\x83\xb9" + old_flag + b"\x01",
                b"\x83\xb9" + new_flag + b"\x01",
                "P1 reset flag guard",
            ),
            (0x40C8C6, b"\x83\xfb\x21", b"\x83\xfb" + nb, "P1 slot-scan bound"),
            (0x40C8E3, b"\x6a\x21", b"\x6a" + nb, "P1 clear stosd"),
            (0x40C91D, b"\x6a\x21", b"\x6a" + nb, "P1 reset stosd"),
            # The only consumer that reads the count field rather than a literal bound.
            # `[ebp-0x18]` here is the `CommandSet` `TheCommandSetStore` (0x00DE7744 ->
            # 0x0071EFA2) just returned. Do not widen this to every `push [reg+0x98]` the
            # image holds: 0x009A025E looks identical and is an `UpgradeTemplate`'s
            # `SkirmishAIHeuristic`, whose object is only 0x9C bytes - rewriting it reads
            # past the allocation and feeds garbage to `AIScience::setHeuristic`, which
            # eventually frees a shared heuristic singleton and purecalls the skirmish AI.
            (0x543DF9, b"\xff\xb0" + old_count, b"\xff\xb0" + new_count, "P1 consumer count read"),
            (_AI_SCAN_BOUND, b"\x83\x7d\xf8\x21", b"\x83\x7d\xf8" + nb, "P1 AI scan bound"),
        ]
