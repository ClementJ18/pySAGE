"""Tests for the AI plot-autobuild patch.

Four layers. The apply/verify round trip and the edits run against the repo's real `game.dat`
when it is present (the patch reads a field table and seven call targets, which a synthetic
image would have to fake one by one). The rebuilt field table is decoded row by row. And the
update stub - the plot's state machine and the build call - is *executed* under Unicorn, with
every engine callee replaced by a stub whose answer the test picks, so each branch of the timer
and each refusal is proved on the bytes the game will run.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from sage_patch.addresses import (
    BUILD_OBJECT_NOW_SLOT,
    CAN_MAKE_UNIT_PRODUCTION_GATE_SLOT,
    COMMAND_SET_STORE_FIND_COMMAND_SET,
    FOUNDATION_AI_ALLOC,
    FOUNDATION_AI_ALLOC_BYTES,
    FOUNDATION_AI_DATA_ALLOC,
    FOUNDATION_AI_DATA_ALLOC_BYTES,
    FOUNDATION_AI_FIELD_TABLE,
    FOUNDATION_AI_FIELD_TABLE_REF,
    FOUNDATION_AI_STOCK_FIELDS,
    FOUNDATION_AI_UPDATE_JOIN,
    FOUNDATION_AI_UPDATE_JOIN_BYTES,
    FOUNDATION_AI_UPDATE_JOIN_RESUME,
    FOUNDATION_AI_VTABLE,
    GAME_LOGIC_FIND_OBJECT_BY_ID,
    INI_PARSE_BOOL,
    INI_PARSE_DURATION,
    OBJECT_GET_COMMAND_SET_STRING,
    OBJECT_GET_CONTROLLING_PLAYER,
    THE_BUILD_ASSISTANT,
    THE_COMMAND_SET_STORE,
    THE_GAME_LOGIC,
)
from sage_patch.patches.ai_plot_autobuild import (
    AUTO_BUILD_OFFSET,
    INITIAL_DELAY_OFFSET,
    INSTANCE_SIZE,
    KEYWORDS,
    MODULE_DATA_SIZE,
    NEXT_FRAME_OFFSET,
    REBUILD_DELAY_OFFSET,
    SECTION_NAME,
    STATE_OFFSET,
    AiPlotAutobuildPatch,
    _build_update,
    layout,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import find_section, read_cstring, va_to_offset

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"

needs_game_dat = pytest.mark.skipif(
    not _GAME_DAT.exists(), reason="requires a local game.dat (gitignored, absent in CI)"
)


def at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + count])


class TestTheLayout:
    def test_registered(self) -> None:
        assert PATCHES["ai-plot-autobuild"] is AiPlotAutobuildPatch

    def test_the_fields_sit_past_the_stock_structures(self) -> None:
        assert AUTO_BUILD_OFFSET >= 0x10 and INITIAL_DELAY_OFFSET + 4 <= MODULE_DATA_SIZE
        assert NEXT_FRAME_OFFSET >= 0x30 and STATE_OFFSET < INSTANCE_SIZE

    def test_the_hook_windows_fit_a_jump(self) -> None:
        for window in (
            FOUNDATION_AI_ALLOC_BYTES,
            FOUNDATION_AI_DATA_ALLOC_BYTES,
            FOUNDATION_AI_UPDATE_JOIN_BYTES,
        ):
            assert len(window) >= 5


@needs_game_dat
class TestInstalledBinary:
    @pytest.fixture(scope="class")
    @classmethod
    def real(cls) -> bytes:
        return _GAME_DAT.read_bytes()

    @pytest.fixture(scope="class")
    @classmethod
    def patched(cls, real: bytes) -> bytearray:
        data = bytearray(real)
        AiPlotAutobuildPatch().apply(data)
        return data

    def test_the_stock_binary_is_not_patched(self, real: bytes) -> None:
        assert AiPlotAutobuildPatch.detect(real) is None

    def test_apply_then_verify_and_detect(self, patched: bytearray) -> None:
        assert AiPlotAutobuildPatch().verify(patched) == []
        assert AiPlotAutobuildPatch.detect(patched) is not None

    def test_every_site_becomes_a_jump_into_the_cave(self, patched: bytearray) -> None:
        section = find_section(patched, SECTION_NAME)
        assert section is not None
        pieces = layout(section[0])
        for site, target in (
            (FOUNDATION_AI_ALLOC, pieces.alloc_va),
            (FOUNDATION_AI_DATA_ALLOC, pieces.data_alloc_va),
            (FOUNDATION_AI_UPDATE_JOIN, pieces.update_va),
        ):
            jump = at(patched, site, 5)
            assert jump[0] == 0xE9
            assert site + 5 + struct.unpack("<i", jump[1:])[0] == target

    def test_only_the_foundation_reference_moves_to_the_new_table(
        self, real: bytes, patched: bytearray
    ) -> None:
        """`CastleBehavior` names the same table; it keeps the stock one."""
        pieces = layout(find_section(patched, SECTION_NAME)[0])
        assert struct.unpack("<I", at(patched, FOUNDATION_AI_FIELD_TABLE_REF + 1, 4))[0] == (
            pieces.table_va
        )
        castle_ref = 0x0079D0E8
        assert at(patched, castle_ref, 8) == at(real, castle_ref, 8)

    def test_the_rebuilt_table(self, patched: bytearray) -> None:
        pieces = layout(find_section(patched, SECTION_NAME)[0])
        rows = []
        for index in range(len(FOUNDATION_AI_STOCK_FIELDS) + len(KEYWORDS) + 1):
            rows.append(struct.unpack("<4I", at(patched, pieces.table_va + 16 * index, 16)))
        names = [read_cstring(patched, row[0]) if row[0] else None for row in rows]
        assert names == [n for n, _ in FOUNDATION_AI_STOCK_FIELDS] + list(KEYWORDS) + [None]
        stock = [
            struct.unpack("<4I", at(patched, FOUNDATION_AI_FIELD_TABLE + 16 * i, 16))
            for i in range(2)
        ]
        assert rows[:2] == stock
        assert [(row[1], row[3]) for row in rows[2:5]] == [
            (INI_PARSE_BOOL, AUTO_BUILD_OFFSET),
            (INI_PARSE_DURATION, REBUILD_DELAY_OFFSET),
            (INI_PARSE_DURATION, INITIAL_DELAY_OFFSET),
        ]
        assert rows[5] == (0, 0, 0, 0)

    def test_the_ini_surface(self) -> None:
        fields = {f.name: (f.block, f.type) for f in AiPlotAutobuildPatch().ini_surface().fields}
        assert fields == {
            "AIAutoBuild": ("FoundationAIUpdate", "Bool"),
            "AIRebuildDelay": ("FoundationAIUpdate", "Int"),
            "AIInitialBuildDelay": ("FoundationAIUpdate", "Int"),
        }


# --- the update stub, executed --------------------------------------------------------------

unicorn = pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_EDI,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

_ENGINE = 0x00400000  # the engine's range, for the callees and the singletons
_ENGINE_SIZE = 0x00C00000
_CAVE = 0x01000000
_DATA = 0x02000000
_STACK = 0x03000000

_MODULE = _DATA + 0x000  # module base; the UpdateModule subobject is +0x10
_IFACE = _MODULE + 0x10
_MODULE_DATA = _DATA + 0x100
_PLOT = _DATA + 0x200
_PLAYER = _DATA + 0x800
_LOGIC = _DATA + 0x900
_SET = _DATA + 0xA00
_BUTTON = _DATA + 0xB00
_TEMPLATE = _DATA + 0xC00
_ASSISTANT = _DATA + 0xD00
_ASSISTANT_VTABLE = _DATA + 0xE00
_CONTROL_BAR = _DATA + 0xF00

#: Stubs for the vtable callees, in the engine range so a `call [reg+slot]` lands somewhere real.
_GATE_STUB = 0x00F00000
_BUILD_STUB = 0x00F00100

#: Each callee as `mov eax, <answer>; ret <bytes>`; the answer's offset is +1.
_RETS = {
    GAME_LOGIC_FIND_OBJECT_BY_ID: 4,
    OBJECT_GET_CONTROLLING_PLAYER: 0,
    OBJECT_GET_COMMAND_SET_STRING: 0,
    COMMAND_SET_STORE_FIND_COMMAND_SET: 4,
    _GATE_STUB: 0xC,
    _BUILD_STUB: 0x14,
}


def _stub(answer: int, ret: int) -> bytes:
    tail = b"\xc3" if ret == 0 else b"\xc2" + struct.pack("<H", ret)
    return b"\xb8" + struct.pack("<I", answer) + tail


@dataclass
class Plot:
    """One tick's world. Defaults: an AI plot declaring the keyword, empty, due, on its frame."""

    vtable: int = FOUNDATION_AI_VTABLE
    auto_build: int = 1
    rebuild_delay: int = 300
    initial_delay: int = 10
    built_on: int = 0
    built_on_alive: bool = False
    next_frame: int = 0
    state: int = 2
    frame: int = 1000
    object_id: int = 8  # (id + frame) & 7 == 0: this plot's frame
    player_type: int = 1
    owned: bool = True
    command: int = 1
    gate: int = 0
    builds: list[tuple[int, ...]] = field(default_factory=list)


def run(plot: Plot) -> tuple[Plot, dict[str, int]]:
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in (
        (_ENGINE, _ENGINE_SIZE),
        (_CAVE, 0x10000),
        (_DATA, 0x10000),
        (_STACK, 0x10000),
    ):
        uc.mem_map(base, size)
    code = _build_update(_CAVE)
    uc.mem_write(_CAVE, code)

    answers = {
        GAME_LOGIC_FIND_OBJECT_BY_ID: _DATA + 0x5000 if plot.built_on_alive else 0,
        OBJECT_GET_CONTROLLING_PLAYER: _PLAYER if plot.owned else 0,
        OBJECT_GET_COMMAND_SET_STRING: _DATA + 0x6000,
        COMMAND_SET_STORE_FIND_COMMAND_SET: _SET,
        _GATE_STUB: plot.gate,
        _BUILD_STUB: _DATA + 0x7000,
    }
    for va, ret in _RETS.items():
        uc.mem_write(va, _stub(answers[va], ret))
    uc.mem_write(FOUNDATION_AI_UPDATE_JOIN_RESUME, b"\xf4")  # hlt: the end of the run

    def u32(va: int, value: int) -> None:
        uc.mem_write(va, struct.pack("<I", value))

    u32(_MODULE, plot.vtable)
    u32(_MODULE + 4, _MODULE_DATA)
    u32(_MODULE + 8, _PLOT)
    u32(_MODULE + 0x28, plot.built_on)
    u32(_MODULE + NEXT_FRAME_OFFSET, plot.next_frame)
    uc.mem_write(_MODULE + STATE_OFFSET, bytes((plot.state,)))
    uc.mem_write(_MODULE_DATA + AUTO_BUILD_OFFSET, bytes((plot.auto_build,)))
    u32(_MODULE_DATA + REBUILD_DELAY_OFFSET, plot.rebuild_delay)
    u32(_MODULE_DATA + INITIAL_DELAY_OFFSET, plot.initial_delay)
    u32(_PLOT + 0x74, plot.object_id)
    u32(_PLOT + 0x38, 0x3F800000)
    u32(_PLOT + 0x44, 0x40490FDB)  # pi, as the plot's angle
    u32(_PLAYER + 0x5C, plot.player_type)
    u32(THE_GAME_LOGIC, _LOGIC)
    u32(_LOGIC + 0x40, plot.frame)
    u32(THE_COMMAND_SET_STORE, _CONTROL_BAR)
    u32(_SET + 0x14 + 4 * 2, _BUTTON)  # the plot's one button, in slot 2
    u32(_BUTTON + 0x14, plot.command)
    u32(_BUTTON + 0x20, _TEMPLATE)
    u32(THE_BUILD_ASSISTANT, _ASSISTANT)
    u32(_ASSISTANT, _ASSISTANT_VTABLE)
    u32(_ASSISTANT_VTABLE + CAN_MAKE_UNIT_PRODUCTION_GATE_SLOT, _GATE_STUB)
    u32(_ASSISTANT_VTABLE + BUILD_OBJECT_NOW_SLOT, _BUILD_STUB)

    def on_build(uc: Uc, address: int, size: int, user) -> None:
        esp = uc.reg_read(UC_X86_REG_ESP)
        plot.builds.append(struct.unpack("<6I", uc.mem_read(esp, 24))[1:])

    uc.hook_add(UC_HOOK_CODE, on_build, begin=_BUILD_STUB, end=_BUILD_STUB)
    esp = _STACK + 0x8000
    for reg, value in (
        (UC_X86_REG_ESP, esp),
        (UC_X86_REG_ESI, _IFACE),
        (UC_X86_REG_EBX, 0x1111),
        (UC_X86_REG_EBP, 0x2222),
        (UC_X86_REG_EDI, 0x3333),
    ):
        uc.reg_write(reg, value)
    uc.emu_start(_CAVE, FOUNDATION_AI_UPDATE_JOIN_RESUME)
    plot.next_frame = struct.unpack("<I", uc.mem_read(_MODULE + NEXT_FRAME_OFFSET, 4))[0]
    plot.state = uc.mem_read(_MODULE + STATE_OFFSET, 1)[0]
    regs = {
        "esp": uc.reg_read(UC_X86_REG_ESP) - esp,
        "esi": uc.reg_read(UC_X86_REG_ESI),
        "ebx": uc.reg_read(UC_X86_REG_EBX),
        "ebp": uc.reg_read(UC_X86_REG_EBP),
        "edi": uc.reg_read(UC_X86_REG_EDI),
    }
    return plot, regs


class TestTheUpdateStub:
    def test_it_rejoins_as_the_displaced_code_would(self) -> None:
        """Stack balanced, callee-saved registers back, and `edi` = the plot as `mov edi,
        [esi-8]` leaves it."""
        _, regs = run(Plot())
        assert regs == {"esp": 0, "esi": _IFACE, "ebx": 0x1111, "ebp": 0x2222, "edi": _PLOT}

    def test_a_due_ai_plot_builds_its_button_at_its_own_position_and_angle(self) -> None:
        plot, _ = run(Plot())
        assert plot.builds == [(_PLOT, _TEMPLATE, _PLOT + 0x38, 0x40490FDB, _PLAYER)]

    @pytest.mark.parametrize(
        ("change", "why"),
        [
            ({"vtable": 0x00C30DE8}, "a CastleBehavior shares the tick"),
            ({"auto_build": 0}, "the keyword is not declared"),
            ({"player_type": 0}, "a human's plot"),
            ({"owned": False}, "an unowned plot"),
            ({"gate": 2}, "the gate refuses: not affordable"),
            ({"gate": 1}, "the gate refuses: not in the set"),
            ({"command": 3}, "a UNIT_BUILD button is not a plot build"),
            ({"object_id": 9}, "not this plot's throttled frame"),
            ({"next_frame": 1001}, "the delay has not run out"),
        ],
    )
    def test_no_build(self, change: dict, why: str) -> None:
        plot, _ = run(Plot(**change))
        assert plot.builds == [], why

    def test_a_fresh_plot_arms_the_initial_delay_and_waits(self) -> None:
        plot, _ = run(Plot(state=0))
        assert (plot.state, plot.next_frame, plot.builds) == (2, 1000 + 10, [])

    def test_an_occupied_plot_is_remembered(self) -> None:
        plot, _ = run(Plot(built_on=77, built_on_alive=True))
        assert (plot.state, plot.builds) == (1, [])

    def test_a_dead_occupant_counts_as_empty(self) -> None:
        """The id is stale: the plot is free, and the rebuild delay starts."""
        plot, _ = run(Plot(built_on=77, built_on_alive=False, state=1))
        assert (plot.state, plot.next_frame, plot.builds) == (2, 1000 + 300, [])

    def test_the_rebuild_delay_follows_the_building(self) -> None:
        """Occupied, then empty: the rebuild delay, not the initial one; then a build when due."""
        plot, _ = run(Plot(state=1))
        assert (plot.state, plot.next_frame) == (2, 1300)
        plot, _ = run(Plot(state=2, next_frame=1300, frame=1296))  # its frame, not yet due
        assert plot.builds == []
        plot, _ = run(Plot(state=2, next_frame=1300, frame=1304))  # its next frame, due
        assert len(plot.builds) == 1

    def test_a_stock_plot_keeps_no_state(self) -> None:
        plot, _ = run(Plot(auto_build=0, state=0))
        assert (plot.state, plot.next_frame) == (0, 0)
