"""Tests for `experience-award`, a `ModifierList` keyword that scales the experience its holder
grants when killed.

Four things can go wrong here and none of them raises on its own.

The first is the **wrapper's contract**. Both call sites expected `getExperienceValue`:
`__thiscall`, two stack arguments, `ret 8`, an `Int` in `eax`, `esi` preserved. The stub nests two
calls with different argument counts inside that, so it is run under an emulator against
stand-ins for both callees rather than only read.

The second is **which object is asked**. The multiplier belongs to the object that dies - the
tracker's owner at `+0x34` - not the killer, which is the stack argument and what `EXPERIENCE`
already scales.

The third is **the unmodified case**. `getModifierMultiplier` leaves its out parameter alone for
an object that has never been modified, so the award has to come back untouched there, and an
allied kill (award 0) has to stay 0 without the query running at all.

The fourth is the **shared name table**. `healing-received` appends to it too, so the index the
stub pushes is not a constant: whichever patch is applied second appends after the first.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

pytest.importorskip("capstone", reason="the [patch] extra (capstone) is not installed")
from capstone import CS_ARCH_X86, CS_MODE_32, Cs  # noqa: E402 - after the importorskip guard

from sage_ini.engine import Engine  # noqa: E402
from sage_ini.model.enums import ModifierType  # noqa: E402
from sage_patch.patches.experience_award import (  # noqa: E402
    ANCHORS,
    CALL_SITES,
    DEFAULT_KEYWORD,
    GET_EXPERIENCE_VALUE,
    GET_MODIFIER_MULTIPLIER,
    SECTION_NAME,
    TRACKER_OWNER_OFFSET,
    WORLDBUILDER_SECTION_NAME,
    ExperienceAwardPatch,
    ExperienceAwardWorldbuilderPatch,
    build_stub,
)
from sage_patch.patches.healing_received import (  # noqa: E402
    DEFAULT_KEYWORD as HEALING_KEYWORD,
)
from sage_patch.patches.healing_received import (  # noqa: E402
    HealingReceivedPatch,
    HealingReceivedWorldbuilderPatch,
)
from sage_patch.patches.utils import modifier_types  # noqa: E402
from sage_patch.utils import call_rel32, find_section, va_to_offset  # noqa: E402

from .synthetic import experience_award_image, modifier_type_worldbuilder_image  # noqa: E402

_GAME_DAT = Path(__file__).resolve().parents[2] / "game.dat"


@pytest.fixture
def image() -> bytearray:
    return experience_award_image()


def _patched(image: bytearray, keyword: str = DEFAULT_KEYWORD) -> bytearray:
    data = bytearray(image)
    ExperienceAwardPatch(keyword=keyword).apply(data)
    return data


def _call_target(data: bytes | bytearray, call_va: int) -> int:
    off = va_to_offset(data, call_va)
    assert off is not None
    assert data[off] == 0xE8, f"0x{call_va:08x} is not a call rel32"
    target: int = call_va + 5 + struct.unpack_from("<i", data, off + 1)[0]
    return target


def _stub_va(data: bytes | bytearray) -> int:
    """Where the calls actually go, read off the rewritten operands rather than recomputed."""
    targets = {_call_target(data, call_va) for call_va, _feeds in CALL_SITES}
    assert len(targets) == 1, "the two callers reach different wrappers"
    return targets.pop()


def _text(data: bytes | bytearray, va: int, limit: int = 0x60) -> list[str]:
    off = va_to_offset(data, va)
    assert off is not None
    out = []
    for insn in Cs(CS_ARCH_X86, CS_MODE_32).disasm(bytes(data[off : off + limit]), va):
        out.append(f"{insn.mnemonic} {insn.op_str}".strip())
        if insn.mnemonic == "ret":
            break
    return out


def test_both_call_sites_hold_a_call_to_the_stock_function_before_the_patch(
    image: bytearray,
) -> None:
    for call_va, _feeds in CALL_SITES:
        assert _call_target(image, call_va) == GET_EXPERIENCE_VALUE


def test_both_call_sites_reach_the_one_wrapper(image: bytearray) -> None:
    """Either caller left on the stock function would make the modifier scale the killer's
    experience and not the player's tally, or the reverse."""
    data = _patched(image)
    located = find_section(data, SECTION_NAME)
    assert located is not None
    section_va, _off, vsize = located
    assert section_va <= _stub_va(data) < section_va + vsize


def test_the_wrapper_forwards_both_arguments_to_the_stock_function(image: bytearray) -> None:
    data = _patched(image)
    text = _text(data, _stub_va(data))
    assert text[:4] == [
        "push esi",
        "mov esi, ecx",
        "push dword ptr [esp + 0xc]",
        "push dword ptr [esp + 0xc]",
    ]
    assert text[4] == f"call {hex(GET_EXPERIENCE_VALUE)}"
    assert text[-2:] == ["pop esi", "ret 8"]


def test_the_wrapper_asks_the_tracker_owner_not_the_killer(image: bytearray) -> None:
    """`this` is the victim's tracker and its owner is at `+0x34`. The killer is a stack argument;
    asking it would duplicate `EXPERIENCE`."""
    data = _patched(image)
    text = _text(data, _stub_va(data))
    assert f"mov ecx, dword ptr [esi + {hex(TRACKER_OWNER_OFFSET)}]" in text
    assert text.index(f"mov ecx, dword ptr [esi + {hex(TRACKER_OWNER_OFFSET)}]") < text.index(
        f"call {hex(GET_MODIFIER_MULTIPLIER)}"
    )


def test_the_wrapper_pushes_the_index_the_table_gave_the_keyword(image: bytearray) -> None:
    data = _patched(image)
    index = modifier_types.read(data).index_of(data, DEFAULT_KEYWORD)
    assert index == modifier_types.STOCK_TYPE_COUNT
    assert f"push {hex(index)}" in _text(data, _stub_va(data))


def test_the_rebuilt_table_keeps_every_stock_name_at_its_stock_index(image: bytearray) -> None:
    data = _patched(image)
    names = modifier_types.names(data, modifier_types.read(data))
    assert len(names) == modifier_types.STOCK_TYPE_COUNT + 1
    for index, name in modifier_types.TABLE_FINGERPRINT.items():
        assert names[index] == name
    assert names[-1] == DEFAULT_KEYWORD


def test_the_keyword_is_configurable(image: bytearray) -> None:
    data = _patched(image, keyword="KILL_VALUE")
    assert modifier_types.read(data).index_of(data, "KILL_VALUE") is not None
    patch = ExperienceAwardPatch.detect(data)
    assert patch is not None
    assert patch.keyword == "KILL_VALUE"


def test_a_name_the_ini_parser_could_never_match_is_refused() -> None:
    with pytest.raises(ValueError, match="uppercase letters"):
        ExperienceAwardPatch(keyword="Experience Award")


def test_applying_twice_is_refused(image: bytearray) -> None:
    data = _patched(image)
    with pytest.raises(ValueError, match="not the expected build"):
        ExperienceAwardPatch().apply(data)


def test_apply_verify_detect_round_trip(image: bytearray) -> None:
    data = _patched(image)
    assert ExperienceAwardPatch().verify(data) == []
    found = ExperienceAwardPatch.detect(data)
    assert found is not None and found.keyword == DEFAULT_KEYWORD
    assert ExperienceAwardPatch.detect(image) is None


@pytest.mark.parametrize("call_va", [va for va, _feeds in CALL_SITES])
def test_verify_notices_a_caller_left_on_the_stock_function(image: bytearray, call_va: int) -> None:
    data = _patched(image)
    off = va_to_offset(data, call_va)
    assert off is not None
    data[off : off + 5] = call_rel32(call_va, GET_EXPERIENCE_VALUE)
    assert ExperienceAwardPatch().verify(data)


def test_verify_notices_a_stub_that_pushes_a_stale_index(image: bytearray) -> None:
    """The cave's immediate and the live table have to agree, and they are two separate places in
    the file."""
    data = _patched(image)
    stub_off = va_to_offset(data, _stub_va(data))
    assert stub_off is not None
    push = bytes(data).index(b"\x6a" + bytes([modifier_types.STOCK_TYPE_COUNT]), stub_off)
    data[push + 1] = modifier_types.STOCK_TYPE_COUNT + 1
    assert ExperienceAwardPatch().verify(data)


def test_a_moved_award_function_stops_the_patch(image: bytearray) -> None:
    """The wrapper reads `+0x34` on the strength of this function doing the same."""
    data = bytearray(image)
    off = va_to_offset(data, GET_EXPERIENCE_VALUE)
    assert off is not None
    data[off + 5] ^= 0xFF
    with pytest.raises(ValueError, match="not the expected build"):
        ExperienceAwardPatch().apply(data)


def test_the_stub_is_a_pure_function_of_its_address_and_index() -> None:
    a = build_stub(0x00E00000, 28)
    b = build_stub(0x00E00010, 28)
    assert len(a) == len(b)
    assert a != b
    assert build_stub(0x00E00000, 29) != a


def test_ini_surface_names_the_keyword_and_claims_no_index() -> None:
    surface = ExperienceAwardPatch().ini_surface()
    assert [(d.enum, d.name, d.value, d.patch) for d in surface.enum_members] == [
        ("ModifierType", DEFAULT_KEYWORD, None, ExperienceAwardPatch.name)
    ]


def test_the_ini_surface_actually_applies_to_the_model() -> None:
    surface: Engine = ExperienceAwardPatch().ini_surface()
    with surface.activate() as problems:
        assert problems == []
        assert DEFAULT_KEYWORD in ModifierType.__members__
    assert DEFAULT_KEYWORD not in ModifierType.__members__


_CAVE = 0x00E00000
_HEAP = 0x02000000
_STACK = 0x03000000
_RETURN = 0x04000000
_PAGE = 0x1000
_TYPE = 28

# Stand-in for `getExperienceValue`: answer the dword at tracker `+0x14`, as the stock function
# does for a hostile killer.
_FAKE_GET_VALUE = bytes.fromhex("8b4114c20800")  # mov eax, [ecx+0x14]; ret 8

# Stand-in for `getModifierMultiplier`. It records the type it was asked for at `this+0x18`, and
# writes the dword at `this+0x10` through `out` only when `this+0x14` is set - an object with
# that flag clear behaves like one with no modifier holder, whose `out` is never written.
_FAKE_GET_MULTIPLIER = bytes.fromhex(
    "8b542404"  # mov edx, [esp+4]
    "895118"  # mov [ecx+0x18], edx
    "83791400"  # cmp dword [ecx+0x14], 0
    "740e"  # je  skip
    "8b442408"  # mov eax, [esp+8]
    "8b5110"  # mov edx, [ecx+0x10]
    "8910"  # mov [eax], edx
    "b001"  # mov al, 1
    "c21000"  # ret 0x10
    "32c0"  # skip: xor al, al
    "c21000"  # ret 0x10
)


class _Machine:
    """The wrapper, run against stand-ins for the two engine functions it calls."""

    TRACKER = _HEAP
    VICTIM = _HEAP + 0x100
    KILLER = _HEAP + 0x200

    def __init__(self) -> None:
        unicorn = pytest.importorskip("unicorn")
        self.regs = pytest.importorskip("unicorn.x86_const")
        self.uc = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
        for base in (_CAVE, _HEAP, _STACK, _RETURN):
            self.uc.mem_map(base, 0x10000)
        for va, code in (
            (GET_EXPERIENCE_VALUE, _FAKE_GET_VALUE),
            (GET_MODIFIER_MULTIPLIER, _FAKE_GET_MULTIPLIER),
        ):
            self.uc.mem_map(va & ~(_PAGE - 1), _PAGE)
            self.uc.mem_write(va, code)
        self.uc.mem_write(_CAVE, build_stub(_CAVE, _TYPE))

    def award(self, value: int, multiplier: float | None, owner: bool = True) -> int:
        """What the wrapper returns for a stock award of `value`; `multiplier=None` is a victim
        that has never been modified."""
        self._write(self.TRACKER + 0x14, value)
        self._write(self.TRACKER + TRACKER_OWNER_OFFSET, self.VICTIM if owner else 0)
        bits = struct.unpack("<I", struct.pack("<f", multiplier or 0.0))[0]
        self._write(self.VICTIM + 0x10, bits)
        self._write(self.VICTIM + 0x14, int(multiplier is not None))
        self._write(self.VICTIM + 0x18, 0xFFFFFFFF)

        esp = _STACK + 0x8000
        for offset, word in ((0, _RETURN), (4, self.KILLER), (8, 0)):
            self._write(esp + offset, word)
        self.uc.reg_write(self.regs.UC_X86_REG_ESP, esp)
        self.uc.reg_write(self.regs.UC_X86_REG_ECX, self.TRACKER)
        self.uc.reg_write(self.regs.UC_X86_REG_ESI, 0x5E515E51)
        self.uc.emu_start(_CAVE, _RETURN, count=1000)

        assert self.uc.reg_read(self.regs.UC_X86_REG_EIP) == _RETURN
        assert self.uc.reg_read(self.regs.UC_X86_REG_ESP) == esp + 12, "ret 8, like the original"
        assert self.uc.reg_read(self.regs.UC_X86_REG_ESI) == 0x5E515E51, "esi is callee-saved"
        signed: int = struct.unpack("<i", self._read(self.regs.UC_X86_REG_EAX))[0]
        return signed

    def asked_type(self) -> int:
        """The modifier type the victim was queried for, or `0xFFFFFFFF` if it never was."""
        asked: int = struct.unpack("<I", bytes(self.uc.mem_read(self.VICTIM + 0x18, 4)))[0]
        return asked

    def _write(self, va: int, value: int) -> None:
        self.uc.mem_write(va, struct.pack("<I", value))

    def _read(self, register: int) -> bytes:
        return struct.pack("<I", self.uc.reg_read(register))


class TestTheWrapperRuns:
    @pytest.fixture
    def machine(self) -> _Machine:
        return _Machine()

    @pytest.mark.parametrize(
        ("value", "multiplier", "expected"),
        [(40, 0.5, 20), (40, 2.0, 80), (40, 1.0, 40), (40, 0.0, 0), (5, 0.5, 2), (40, 0.25, 10)],
    )
    def test_the_award_is_multiplied_and_truncated(
        self, machine: _Machine, value: int, multiplier: float, expected: int
    ) -> None:
        assert machine.award(value, multiplier) == expected
        assert machine.asked_type() == _TYPE, "the victim was asked for the appended type"

    def test_an_unmodified_victim_grants_its_stock_award(self, machine: _Machine) -> None:
        """The callee never wrote `out`; the seed has to be what multiplies."""
        assert machine.award(40, None) == 40

    def test_a_zero_award_is_not_queried(self, machine: _Machine) -> None:
        """An allied kill answers 0 and stays 0, whatever the victim carries."""
        assert machine.award(0, 3.0) == 0
        assert machine.asked_type() == 0xFFFFFFFF

    def test_a_negative_product_is_clamped_to_nothing(self, machine: _Machine) -> None:
        assert machine.award(40, -1.0) == 0

    def test_a_tracker_without_an_owner_grants_its_stock_award(self, machine: _Machine) -> None:
        assert machine.award(40, 0.5, owner=False) == 40


class TestSharingTheNameTable:
    """`healing-received` appends to the same table, so the pair has to compose in either order."""

    @pytest.mark.parametrize("award_first", [True, False], ids=["award-first", "healing-first"])
    def test_both_patches_verify_in_either_order(self, image: bytearray, award_first: bool) -> None:
        award, healing = ExperienceAwardPatch(), HealingReceivedPatch()
        for patch in (award, healing) if award_first else (healing, award):
            patch.apply(image)

        assert award.verify(image) == []
        assert healing.verify(image) == []
        names = modifier_types.names(image, modifier_types.read(image))
        expected = [DEFAULT_KEYWORD, HEALING_KEYWORD]
        if not award_first:
            expected.reverse()
        assert names[modifier_types.STOCK_TYPE_COUNT :] == expected

    def test_the_stub_pushes_the_index_it_ended_up_with(self, image: bytearray) -> None:
        HealingReceivedPatch().apply(image)
        ExperienceAwardPatch().apply(image)
        index = modifier_types.read(image).index_of(image, DEFAULT_KEYWORD)
        assert index == modifier_types.STOCK_TYPE_COUNT + 1
        assert f"push {hex(index)}" in _text(image, _stub_va(image))


class TestWorldbuilder:
    """The authoring half: the editor throws on a token its own table does not hold."""

    @pytest.fixture
    def image(self) -> bytearray:
        return modifier_type_worldbuilder_image()

    def test_apply_verify_detect_round_trip(self, image: bytearray) -> None:
        patch = ExperienceAwardWorldbuilderPatch()
        patch.apply(image)
        assert patch.verify(image) == []
        found = ExperienceAwardWorldbuilderPatch.detect(image)
        assert found is not None and found.keyword == DEFAULT_KEYWORD
        assert find_section(image, WORLDBUILDER_SECTION_NAME) is not None
        assert find_section(image, SECTION_NAME) is None

    @pytest.mark.parametrize("award_first", [True, False], ids=["award-first", "healing-first"])
    def test_both_twins_compose_in_either_order(self, image: bytearray, award_first: bool) -> None:
        award, healing = ExperienceAwardWorldbuilderPatch(), HealingReceivedWorldbuilderPatch()
        for patch in (award, healing) if award_first else (healing, award):
            patch.apply(image)
        assert award.verify(image) == []
        assert healing.verify(image) == []


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs the real game.dat")
class TestInstalledBinary:
    """Against the real binary, which is the only thing that can say the addresses are right."""

    @pytest.fixture(scope="class")
    def stock(self) -> bytes:
        return _GAME_DAT.read_bytes()

    def test_every_anchor_holds_its_stock_bytes(self, stock: bytes) -> None:
        for va, expected in ANCHORS.items():
            off = va_to_offset(stock, va)
            assert off is not None, f"0x{va:08x} is not mapped"
            assert bytes(stock[off : off + len(expected)]) == expected, f"0x{va:08x}"

    def test_the_two_patched_calls_are_the_only_callers(self, stock: bytes) -> None:
        """A third caller would be a path the modifier silently does not cover."""
        located = find_section(stock, ".text")
        assert located is not None
        text_va, text_off, text_size = located
        found = []
        start = text_off
        end = text_off + text_size
        while (at := stock.find(b"\xe8", start, end)) != -1:
            va = text_va + (at - text_off)
            if stock[at : at + 5] == call_rel32(va, GET_EXPERIENCE_VALUE):
                found.append(va)
            start = at + 1
        assert found == [va for va, _feeds in CALL_SITES]

    def test_apply_verify_detect_round_trip(self, stock: bytes) -> None:
        data = bytearray(stock)
        patch = ExperienceAwardPatch()
        patch.apply(data)
        assert patch.verify(data) == []
        assert ExperienceAwardPatch.detect(data) is not None

    @pytest.mark.parametrize("award_first", [True, False], ids=["award-first", "healing-first"])
    def test_it_composes_with_healing_received(self, stock: bytes, award_first: bool) -> None:
        data = bytearray(stock)
        award, healing = ExperienceAwardPatch(), HealingReceivedPatch()
        for patch in (award, healing) if award_first else (healing, award):
            patch.apply(data)
        assert award.verify(data) == []
        assert healing.verify(data) == []
