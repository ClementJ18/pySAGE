"""Tests for the spell-recharge-targets patch.

Structural checks first: every rewritten site, the relocated field table, the lifecycle. The
routines themselves are then run under an emulator against small stand-ins for the engine calls
they make - the team-object walk, the controlling-player getter, the INI tokenizer and the
special-power lookup - so that what is checked is the cave's own arithmetic and register contract:
which modules count, how levels group, what the two recharge sites leave behind, and that the
three bookkeeping routines either return or resume the stock body with the stock frame.
"""

from __future__ import annotations

import faulthandler
import struct
from pathlib import Path

import pytest

from sage_patch.addresses import (
    ASCII_STRING_CTOR,
    INI_NEXT_TOKEN_OR_NULL,
    OBJECT_GET_CONTROLLING_PLAYER,
    OBJECT_MODULE_LIST,
    OBJECT_STATUS,
    PLAYER_FOR_EACH_TEAM_OBJECT,
    THE_SPECIAL_POWER_STORE,
)
from sage_patch.patches.spell_recharge_targets import (
    ANCHORS,
    CAPACITY,
    CXX_THROW_EXCEPTION,
    EXCEPTION_FORMAT,
    FIELD_TABLE_PUSH_VA,
    FIND_SPECIAL_POWER_TEMPLATE,
    GATE1_STOCK,
    GATE1_VA,
    GATE2_STOCK,
    GATE2_VA,
    KEYWORD,
    LIST_COUNT,
    LIST_ENTRIES,
    LIST_SCRATCH,
    MODULE_UPGRADE_EXECUTED,
    MODULE_VTABLE,
    MODULEDATA_CTOR_CALL_VA,
    MODULEDATA_CTOR_VA,
    MODULEDATA_SIZE_VA,
    ON_CAPTURE_STOCK,
    ON_CAPTURE_TAIL_VA,
    ON_CAPTURE_VA,
    ON_DELETE_STOCK,
    ON_DELETE_VA,
    PATCHED_MODULEDATA_SIZE,
    PERCENTAGE_BEGIN,
    PERCENTAGE_END,
    PLAYER_GET_SPELL_RECHARGE_MODIFIER,
    SECTION_NAME,
    STOCK_MODULEDATA_SIZE,
    UPGRADE_IMPL_STOCK,
    UPGRADE_IMPL_VA,
    SpellRechargeTargetsPatch,
    _code,
    _data_layout,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import call_rel32, find_section, jmp_rel32, read_cstring, va_to_offset
from tests.sage_patch.synthetic import SPELL_RECHARGE_FIELD_ROWS, spell_recharge_targets_image


def _read(data: bytes | bytearray, va: int, n: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + n])


def _cave(data: bytes | bytearray) -> tuple[int, dict[str, int]]:
    located = find_section(data, SECTION_NAME)
    assert located is not None, f"no {SECTION_NAME} section"
    _strings, where = _data_layout(located[0])
    _code_bytes, labels = _code(where["code"], where)
    return located[0], {**where, **labels}


@pytest.fixture
def image() -> bytearray:
    return spell_recharge_targets_image()


@pytest.fixture
def patched() -> bytearray:
    data = spell_recharge_targets_image()
    SpellRechargeTargetsPatch().apply(data)
    return data


class TestStructure:
    def test_the_module_data_grows_by_the_list(self, patched: bytearray) -> None:
        assert PATCHED_MODULEDATA_SIZE == STOCK_MODULEDATA_SIZE + 8 + 4 * CAPACITY
        assert _read(patched, MODULEDATA_SIZE_VA, 5) == b"\x68" + struct.pack(
            "<I", PATCHED_MODULEDATA_SIZE
        )

    def test_the_constructor_call_goes_to_the_cave(self, patched: bytearray) -> None:
        _base, where = _cave(patched)
        assert _read(patched, MODULEDATA_CTOR_CALL_VA, 5) == call_rel32(
            MODULEDATA_CTOR_CALL_VA, where["ctor"]
        )

    def test_the_field_table_keeps_the_stock_rows_and_adds_one(self, patched: bytearray) -> None:
        base, where = _cave(patched)
        assert _read(patched, FIELD_TABLE_PUSH_VA, 5) == b"\x68" + struct.pack("<I", base)
        rows = [struct.unpack("<4I", _read(patched, base + 16 * i, 16)) for i in range(5)]
        for (name_va, name, parse, offset), row in zip(
            SPELL_RECHARGE_FIELD_ROWS, rows, strict=False
        ):
            assert row == (name_va, parse, 0, offset)
            assert read_cstring(patched, row[0]) == name
        assert rows[3] == (where["keyword"], where["parse"], 0, LIST_COUNT)
        assert read_cstring(patched, rows[3][0]) == KEYWORD
        assert rows[4] == (0, 0, 0, 0)

    def test_the_three_writers_jump_to_the_cave(self, patched: bytearray) -> None:
        _base, where = _cave(patched)
        for va, label in (
            (ON_DELETE_VA, "on_delete"),
            (ON_CAPTURE_VA, "on_capture"),
            (UPGRADE_IMPL_VA, "upgrade_impl"),
        ):
            assert _read(patched, va, 5) == jmp_rel32(va, where[label])

    def test_the_recharge_sites_call_and_skip_the_rest(self, patched: bytearray) -> None:
        _base, where = _cave(patched)
        for va, stock, label in (
            (GATE1_VA, GATE1_STOCK, "gate1"),
            (GATE2_VA, GATE2_STOCK, "gate2"),
        ):
            got = _read(patched, va, len(stock))
            assert got[:5] == call_rel32(va, where[label])
            assert got[5:7] == bytes([0xEB, len(stock) - 7])  # jmp short past the window
            assert got[7:] == b"\x90" * (len(stock) - 7)

    def test_the_flag_test_before_the_first_site_is_untouched(self, patched: bytearray) -> None:
        """`description-timers` and `special-power-charges` anchor these eight bytes, and the
        cave reads the flags they leave."""
        assert _read(patched, 0x00896EBA, 8) == bytes.fromhex("8b4018c1e805a801")


class TestLifecycle:
    def test_apply_verify_detect(self, patched: bytearray) -> None:
        assert SpellRechargeTargetsPatch().verify(patched) == []
        assert isinstance(SpellRechargeTargetsPatch.detect(patched), SpellRechargeTargetsPatch)

    def test_an_unpatched_image_is_not_detected(self, image: bytearray) -> None:
        assert SpellRechargeTargetsPatch().verify(image) != []
        assert SpellRechargeTargetsPatch.detect(image) is None

    def test_a_second_apply_refuses(self, patched: bytearray) -> None:
        with pytest.raises(ValueError):
            SpellRechargeTargetsPatch().apply(patched)

    @pytest.mark.parametrize("va", [va for va, _blob, _what in ANCHORS], ids="0x{:08x}".format)
    def test_a_drifted_anchor_refuses_before_writing(self, image: bytearray, va: int) -> None:
        off = va_to_offset(image, va)
        assert off is not None
        image[off] ^= 0xFF
        before = bytes(image)
        with pytest.raises(ValueError, match="not the expected build"):
            SpellRechargeTargetsPatch().apply(image)
        assert bytes(image) == before

    def test_the_ini_surface_is_a_list_of_powers(self) -> None:
        (field,) = SpellRechargeTargetsPatch().ini_surface().fields
        assert (field.block, field.name, field.type) == (
            "SpellRechargeModifierUpgrade",
            KEYWORD,
            "Ref[]:specialpowers",
        )

    def test_registered_as_settled(self) -> None:
        assert PATCHES["spell-recharge-targets"] is SpellRechargeTargetsPatch
        assert not SpellRechargeTargetsPatch.experimental


unicorn = pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_ESP,
)

_PAGE = 0x1000
_HEAP = 0x20000000
_STACK = 0x30000000
_STUBS = 0x40000000
_RETURN = 0x50000000  # a `ret` lands here and the run stops

#: Where the stand-in `getControllingPlayer` reads an object's owner. Clear of every field the
#: cave reads (`+0x94`, `+0x24C`).
_OWNER = 0x100
_OBJECT_LIST = _STUBS + 0x800  # the NULL-terminated objects the stand-in walk visits

#: A `thiscall forEachTeamObject(fn, ctx)`, `ret 8`, over `_OBJECT_LIST`.
_FOR_EACH = bytes.fromhex(
    "5657"  # push esi / push edi
    "be"
    + struct.pack("<I", _OBJECT_LIST).hex()  # mov esi, <list>
    + "8b06"  # .loop: mov eax, [esi]
    "85c0"  # test eax, eax
    "7411"  # je .done
    "ff742410"  # push dword [esp+0x10]   ; ctx
    "50"  # push eax
    "ff542414"  # call dword [esp+0x14]   ; fn
    "83c408"  # add esp, 8
    "83c604"  # add esi, 4
    "ebe9"  # jmp .loop
    "5f5e"  # .done: pop edi / pop esi
    "c20800"  # ret 8
)
_STUB_CODE = {
    PLAYER_FOR_EACH_TEAM_OBJECT: _FOR_EACH,
    OBJECT_GET_CONTROLLING_PLAYER: b"\x8b\x81" + struct.pack("<I", _OWNER) + b"\xc3",
    PLAYER_GET_SPELL_RECHARGE_MODIFIER: bytes.fromhex("d98118070000c3"),
    MODULEDATA_CTOR_VA: b"\x8b\xc1\xc3",  # mov eax, ecx / ret
    # The parser's calls. The tokenizer hands out a NULL-terminated list of char pointers; the
    # string "constructor" stores the char pointer; the lookup reads the template planted in
    # the dword before a token's characters (0 for an unknown one).
    INI_NEXT_TOKEN_OR_NULL: bytes.fromhex("a1f007004083c004a3f00700408b00c20400"),
    ASCII_STRING_CTOR: bytes.fromhex("8b4424048901c20400"),
    FIND_SPECIAL_POWER_TEMPLATE: bytes.fromhex("8b4424048b40fcc20400"),
    # Records the format it was handed, so a test can tell the two errors apart.
    EXCEPTION_FORMAT: bytes.fromhex("8b44240ca3e0070040c3"),
    CXX_THROW_EXCEPTION: b"\xf4",  # hlt; the run stops at this address first
}
_TOKEN_CURSOR = _STUBS + 0x7F0  # the tokenizer's position, one slot before the next token
_THROWN_FORMAT = _STUBS + 0x7E0


class _Machine:
    def __init__(self, data: bytes | bytearray) -> None:
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.mapped: set[int] = set()
        self.heap = _HEAP
        base, self.where = _cave(data)
        located = find_section(data, SECTION_NAME)
        assert located is not None
        _va, off, size = located
        self.write(base, bytes(data[off : off + size]))
        for va in (GATE1_VA, GATE2_VA, ON_DELETE_VA, ON_CAPTURE_VA, UPGRADE_IMPL_VA):
            self.write(va, _read(data, va, 0x20))
        for va, code in _STUB_CODE.items():
            self.write(va, code)
        self.write(0x00BD1908, struct.pack("<f", 1.0))
        self.write(_OBJECT_LIST, bytes(4))
        self.write(_RETURN, b"\xf4")
        self.write(_STACK, bytes(_PAGE))

    def _map(self, va: int, size: int) -> None:
        was_enabled = faulthandler.is_enabled()
        faulthandler.disable()
        try:
            for page in range(va & ~0xFFF, va + size, _PAGE):
                if page not in self.mapped:
                    self.uc.mem_map(page, _PAGE)
                    self.mapped.add(page)
        finally:
            if was_enabled:
                faulthandler.enable()

    def write(self, va: int, blob: bytes) -> None:
        self._map(va, len(blob))
        self.uc.mem_write(va, blob)

    def u32(self, va: int) -> int:
        return struct.unpack("<I", bytes(self.uc.mem_read(va, 4)))[0]

    def f32(self, va: int) -> float:
        return struct.unpack("<f", bytes(self.uc.mem_read(va, 4)))[0]

    def alloc(self, size: int, blob: bytes = b"") -> int:
        va = self.heap
        self.heap += (size + 0xF) & ~0xF
        self.write(va, blob.ljust(size, b"\x00"))
        return va

    def set_any(self, value: int) -> None:
        self.write(self.where["any"], bytes([value]))

    # The world the discount walk sees.

    def player(self, modifier: float = 0.0) -> int:
        return self.alloc(0x720, bytes(0x718) + struct.pack("<f", modifier))

    def template(self, flagged: bool = False) -> int:
        return self.alloc(0x60, bytes(0x18) + struct.pack("<I", 0x20 if flagged else 0))

    def module_data(self, powers: list[int], percentages: list[float]) -> int:
        values = self.alloc(
            4 * max(1, len(percentages)), struct.pack(f"<{len(percentages)}f", *percentages)
        )
        md = self.alloc(PATCHED_MODULEDATA_SIZE)
        self.write(md + PERCENTAGE_BEGIN, struct.pack("<I", values))
        self.write(md + PERCENTAGE_END, struct.pack("<I", values + 4 * len(percentages)))
        self.write(md + LIST_COUNT, struct.pack("<I", len(powers)))
        self.write(md + LIST_ENTRIES, struct.pack(f"<{len(powers)}I", *powers))
        return md

    def module(self, md: int, executed: bool = True) -> int:
        m = self.alloc(0x24)
        self.write(m, struct.pack("<II", MODULE_VTABLE, md))
        self.write(m + MODULE_UPGRADE_EXECUTED, bytes([int(executed)]))
        return m

    def obj(self, owner: int, modules: list[int], destroyed: bool = False) -> int:
        array = self.alloc(4 * (len(modules) + 1), struct.pack(f"<{len(modules)}I", *modules))
        o = self.alloc(0x300)
        self.write(o + _OWNER, struct.pack("<I", owner))
        self.write(o + OBJECT_MODULE_LIST, struct.pack("<I", array))
        self.write(o + OBJECT_STATUS, bytes([int(destroyed)]))
        return o

    def team(self, objects: list[int]) -> None:
        self.write(_OBJECT_LIST, struct.pack(f"<{len(objects) + 1}I", *objects, 0))

    # Running things.

    def _frame(self) -> tuple[int, int]:
        """A caller frame: `ebp` with room below it, `esp` holding `_RETURN`."""
        ebp = _STACK + 0x800
        esp = ebp - 0x40
        self.write(esp, struct.pack("<I", _RETURN))
        return ebp, esp

    def recharge_multiplier(self, site: int, player: int, template: int) -> float:
        """The discount multiplier `startPowerRecharge` would use, run from the stock code before
        each hook to the instruction after it."""
        ebp, esp = self._frame()
        self.write(ebp - 8, struct.pack("<f", 1.0))
        self.write(ebp - 4, struct.pack("<I", player))
        ability_md = self.alloc(0x10, bytes(8) + struct.pack("<I", template))
        self.uc.reg_write(UC_X86_REG_EBP, ebp)
        self.uc.reg_write(UC_X86_REG_ESP, esp)
        if site == GATE1_VA:
            # From the flag test, with eax the final template and edi the ability's ModuleData.
            self.write(0x00896EBA, bytes.fromhex("8b4018c1e805a801"))
            self.uc.reg_write(UC_X86_REG_EAX, template)
            self.uc.reg_write(UC_X86_REG_EDI, ability_md)
            self.uc.emu_start(0x00896EBA, GATE1_VA + len(GATE1_STOCK), count=100_000)
            assert self.uc.reg_read(UC_X86_REG_ESP) == esp
            return self.f32(ebp - 8)
        # Flavour 2 keeps the raw template in edi and leaves the multiplier in st(0); the stock
        # `fstp [ebp-4]` two instructions later is stood in for here.
        after = GATE2_VA + len(GATE2_STOCK)
        self.write(after, b"\xd9\x5d\xfc")
        self.uc.reg_write(UC_X86_REG_EDI, template)
        self.uc.emu_start(GATE2_VA, after + 3, count=100_000)
        assert self.uc.reg_read(UC_X86_REG_ESP) == esp
        return self.f32(ebp - 4)


@pytest.fixture
def machine(patched: bytearray) -> _Machine:
    return _Machine(patched)


SITES = pytest.mark.parametrize("site", [GATE1_VA, GATE2_VA], ids=("flavour1", "flavour2"))


@SITES
class TestTheDiscount:
    def test_nothing_targeted_is_stock(self, machine: _Machine, site: int) -> None:
        """With no module declaring the keyword the walk never runs: flavour 1 applies the player
        modifier to a flagged power only, flavour 2 to every power, as stock."""
        machine.set_any(0)
        player = machine.player(modifier=-0.2)
        flagged, plain = machine.template(flagged=True), machine.template()
        assert machine.recharge_multiplier(site, player, flagged) == pytest.approx(0.8)
        expected_plain = 1.0 if site == GATE1_VA else 0.8
        assert machine.recharge_multiplier(site, player, plain) == pytest.approx(expected_plain)

    def test_a_named_power_is_discounted_and_another_is_not(
        self, machine: _Machine, site: int
    ) -> None:
        machine.set_any(1)
        player = machine.player()
        named, other = machine.template(), machine.template()
        md = machine.module_data([named], [-0.25, -0.5])
        machine.team([machine.obj(player, [machine.module(md)])])
        assert machine.recharge_multiplier(site, player, named) == pytest.approx(0.75)
        assert machine.recharge_multiplier(site, player, other) == pytest.approx(1.0)

    def test_copies_of_one_module_are_levels_clamped_to_the_list(
        self, machine: _Machine, site: int
    ) -> None:
        machine.set_any(1)
        player = machine.player()
        power = machine.template()
        md = machine.module_data([power], [-0.25, -0.5])
        fires = [machine.obj(player, [machine.module(md)]) for _ in range(3)]
        machine.team(fires[:2])
        assert machine.recharge_multiplier(site, player, power) == pytest.approx(0.5)
        machine.team(fires)
        assert machine.recharge_multiplier(site, player, power) == pytest.approx(0.5)
        assert machine.u32(md + LIST_SCRATCH) == 0  # the walk leaves the counter clean

    def test_separate_modules_multiply(self, machine: _Machine, site: int) -> None:
        machine.set_any(1)
        player = machine.player()
        power, other = machine.template(), machine.template()
        a = machine.module_data([other, power], [-0.5])
        b = machine.module_data([power], [-0.2])
        machine.team([machine.obj(player, [machine.module(a), machine.module(b)])])
        assert machine.recharge_multiplier(site, player, power) == pytest.approx(0.5 * 0.8)

    def test_the_stock_discount_still_applies_alongside(self, machine: _Machine, site: int) -> None:
        machine.set_any(1)
        player = machine.player(modifier=-0.2)
        power = machine.template(flagged=True)
        md = machine.module_data([power], [-0.25])
        machine.team([machine.obj(player, [machine.module(md)])])
        assert machine.recharge_multiplier(site, player, power) == pytest.approx(0.8 * 0.75)

    def test_what_does_not_count(self, machine: _Machine, site: int) -> None:
        """An unexecuted module, a destroyed object, another player's object, a module with no
        Percentage and a module of another class all leave the power alone."""
        machine.set_any(1)
        player, rival = machine.player(), machine.player()
        power = machine.template()
        md = machine.module_data([power], [-0.5])
        empty = machine.module_data([power], [])
        stranger = machine.module(md)
        machine.write(stranger, struct.pack("<I", MODULE_VTABLE + 4))
        machine.team(
            [
                machine.obj(player, [machine.module(md, executed=False)]),
                machine.obj(player, [machine.module(md)], destroyed=True),
                machine.obj(rival, [machine.module(md)]),
                machine.obj(player, [machine.module(empty), stranger]),
            ]
        )
        assert machine.recharge_multiplier(site, player, power) == pytest.approx(1.0)


class TestTheBookkeeping:
    """The three writers of `Player+0x718` return for a targeted module and otherwise resume
    their stock body with the frame their displaced prologue built."""

    def _enter(self, machine: _Machine, va: int, ecx: int) -> tuple[int, int]:
        ebp, esp = machine._frame()
        machine.uc.reg_write(UC_X86_REG_EBP, ebp)
        machine.uc.reg_write(UC_X86_REG_ESP, esp)
        machine.uc.reg_write(UC_X86_REG_ECX, ecx)
        machine.uc.reg_write(UC_X86_REG_EBX, 0x1234)
        return ebp, esp

    @pytest.mark.parametrize(
        ("va", "stock"),
        [(ON_DELETE_VA, ON_DELETE_STOCK), (UPGRADE_IMPL_VA, UPGRADE_IMPL_STOCK)],
        ids=("onDelete", "upgradeImplementation"),
    )
    def test_interface_writers(self, machine: _Machine, va: int, stock: bytes) -> None:
        """Both are entered with `ecx` = the upgrade-mux interface at module `+0x10`, which puts
        the `ModuleData` at `[ecx-0xC]`."""
        resume = va + len(stock)
        machine.write(resume, b"\xf4")
        for targeted in (True, False):
            md = machine.module_data([machine.template()] if targeted else [], [-0.5])
            ebp, esp = self._enter(machine, va, machine.module(md) + 0x10)
            machine.uc.emu_start(va, _RETURN if targeted else resume, count=1000)
            if targeted:
                assert machine.uc.reg_read(UC_X86_REG_ESP) == esp + 4  # returned
            else:
                # push ebp / mov ebp, esp / push ecx / push ecx
                new_esp = machine.uc.reg_read(UC_X86_REG_ESP)
                assert new_esp == esp - 12
                assert machine.uc.reg_read(UC_X86_REG_EBP) == esp - 4
                assert machine.u32(esp - 4) == ebp

    def test_on_capture(self, machine: _Machine) -> None:
        resume = ON_CAPTURE_VA + len(ON_CAPTURE_STOCK)
        machine.write(resume, b"\xf4")
        machine.write(ON_CAPTURE_TAIL_VA, b"\xf4")
        for targeted in (True, False):
            md = machine.module_data([machine.template()] if targeted else [], [-0.5])
            m = machine.module(md)
            ebp, esp = self._enter(machine, ON_CAPTURE_VA, m)
            machine.uc.emu_start(
                ON_CAPTURE_VA, ON_CAPTURE_TAIL_VA if targeted else resume, count=1000
            )
            assert machine.uc.reg_read(UC_X86_REG_EBP) == esp - 4
            assert machine.u32(esp - 4) == ebp
            assert machine.u32(esp - 12) == 0x1234  # the caller's ebx, saved
            if targeted:
                # ...then esi and edi, and ebx = the module, as the tail's epilogue expects.
                assert machine.uc.reg_read(UC_X86_REG_ESP) == esp - 20
                assert machine.uc.reg_read(UC_X86_REG_EBX) == m
            else:
                assert machine.uc.reg_read(UC_X86_REG_ESP) == esp - 12


class TestTheConstructorAndParser:
    def test_the_constructor_zeroes_the_list(self, machine: _Machine) -> None:
        md = machine.alloc(PATCHED_MODULEDATA_SIZE, b"\xaa" * PATCHED_MODULEDATA_SIZE)
        ebp, esp = machine._frame()
        machine.uc.reg_write(UC_X86_REG_ESP, esp)
        machine.uc.reg_write(UC_X86_REG_ECX, md)
        machine.uc.emu_start(machine.where["ctor"], _RETURN, count=1000)
        assert machine.uc.reg_read(UC_X86_REG_EAX) == md
        tail = bytes(machine.uc.mem_read(md + LIST_COUNT, PATCHED_MODULEDATA_SIZE - LIST_COUNT))
        assert tail == bytes(len(tail))
        assert bytes(machine.uc.mem_read(md, LIST_COUNT)) == b"\xaa" * LIST_COUNT

    def _tokens(self, machine: _Machine, names: list[tuple[str, int]]) -> None:
        """Plant each token with its template (0 = unknown) in the dword before it."""
        pointers = []
        for name, template in names:
            at = machine.alloc(4 + len(name) + 1, struct.pack("<I", template) + name.encode())
            pointers.append(at + 4)
        table = machine.alloc(4 * (len(pointers) + 1), struct.pack(f"<{len(pointers)}I", *pointers))
        machine.write(_TOKEN_CURSOR, struct.pack("<I", table - 4))
        machine.write(THE_SPECIAL_POWER_STORE, struct.pack("<I", 0x12345678))

    def _parse(self, machine: _Machine, md: int, until: int = _RETURN) -> int:
        """Run the parser on `md`'s field; return how far `esp` moved."""
        _ebp, esp = machine._frame()
        machine.write(esp, struct.pack("<5I", _RETURN, 0x777, md, md + LIST_COUNT, 0))
        machine.uc.reg_write(UC_X86_REG_ESP, esp)
        machine.uc.emu_start(machine.where["parse"], until, count=100_000)
        return machine.uc.reg_read(UC_X86_REG_ESP) - esp

    def test_every_name_is_resolved_and_stored(self, machine: _Machine) -> None:
        a, b = machine.template(), machine.template()
        md = machine.alloc(PATCHED_MODULEDATA_SIZE)
        machine.write(md + LIST_COUNT, struct.pack("<I", 5))  # a previous line: replaced
        self._tokens(machine, [("SpellA", a), ("SpellB", b)])
        machine.set_any(0)
        assert self._parse(machine, md) == 4  # cdecl: only the return address popped
        assert machine.u32(md + LIST_COUNT) == 2
        assert machine.u32(md + LIST_ENTRIES) == a
        assert machine.u32(md + LIST_ENTRIES + 4) == b
        assert machine.u32(machine.where["any"]) & 0xFF == 1

    def test_an_empty_line_clears_the_list(self, machine: _Machine) -> None:
        md = machine.alloc(PATCHED_MODULEDATA_SIZE)
        machine.write(md + LIST_COUNT, struct.pack("<I", 3))
        self._tokens(machine, [])
        machine.set_any(0)
        self._parse(machine, md)
        assert machine.u32(md + LIST_COUNT) == 0
        assert machine.u32(machine.where["any"]) & 0xFF == 0

    def _thrown(self, machine: _Machine, md: int) -> str:
        """Run the parser to the engine's throw; return the message format it raised."""
        machine.write(_THROWN_FORMAT, bytes(4))
        self._parse(machine, md, until=CXX_THROW_EXCEPTION)
        esp = machine.uc.reg_read(UC_X86_REG_ESP)
        assert machine.u32(esp + 8) == 0x00D17000  # the stock ThrowInfo
        raw = bytes(machine.uc.mem_read(machine.u32(_THROWN_FORMAT), 128))
        return raw.split(b"\x00", 1)[0].decode("ascii")

    def test_an_unknown_name_is_an_ini_error(self, machine: _Machine) -> None:
        md = machine.alloc(PATCHED_MODULEDATA_SIZE)
        self._tokens(machine, [("SpellA", machine.template()), ("Typo", 0)])
        assert self._thrown(machine, md) == f"{KEYWORD}: unknown special power '%s'"

    def test_one_name_too_many_is_an_ini_error(self, machine: _Machine) -> None:
        md = machine.alloc(PATCHED_MODULEDATA_SIZE)
        self._tokens(machine, [(f"Spell{i}", machine.template()) for i in range(CAPACITY + 1)])
        assert self._thrown(machine, md).startswith(f"{KEYWORD}: more than {CAPACITY}")
        assert machine.u32(md + LIST_COUNT) == CAPACITY


#: Both copies a checkout can hold; neither is committed, so each check skips when absent.
_BINARIES = {
    "repo": Path(__file__).resolve().parents[2] / "game.dat",
    "clean": Path(__file__).resolve().parents[2] / "sage_patch" / "engine" / "game.dat.backup",
}


@pytest.mark.parametrize("which", sorted(_BINARIES))
class TestStockBinaries:
    def _stock(self, which: str) -> bytes:
        path = _BINARIES[which]
        if not path.exists():
            pytest.skip(f"needs {path.name}")
        return path.read_bytes()

    def test_the_stand_in_matches_the_binary(self, which: str) -> None:
        stock = self._stock(which)
        stand_in = spell_recharge_targets_image()
        for name_va, name, _parse, _offset in SPELL_RECHARGE_FIELD_ROWS:
            assert read_cstring(stock, name_va) == name
        for va in (MODULEDATA_CTOR_CALL_VA, GATE1_VA, GATE2_VA, ON_CAPTURE_VA):
            assert _read(stock, va, 5) == _read(stand_in, va, 5)

    def test_apply_verify_detect_round_trip(self, which: str) -> None:
        data = bytearray(self._stock(which))
        SpellRechargeTargetsPatch().apply(data)
        assert SpellRechargeTargetsPatch().verify(data) == []
        assert isinstance(SpellRechargeTargetsPatch.detect(data), SpellRechargeTargetsPatch)
