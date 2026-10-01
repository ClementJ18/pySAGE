"""Tests for the castle-unpack-buttons patch.

The cave replaces a `__thiscall` helper, so what could be wrong without raising is its contract: the
answer in `eax`, `ret 4` leaving the stack where the stock call would, `esi` (the bar's selected
object) surviving, and each helper called on the right `this`. The cave is run under an emulator
with the helpers stubbed, over one case per way the castle lookup can end.
"""

from __future__ import annotations

import faulthandler
import struct
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from sage_patch.addresses import (
    CASTLE_BEHAVIOR_NAME_STRING,
    CASTLE_BEHAVIOR_START_FADE,
    CASTLE_BEHAVIOR_STATE,
    CASTLE_MEMBER_BEHAVIOR_NAME_STRING,
    CASTLE_MEMBER_CASTLE_ID,
    CASTLE_STATE_FADING,
    CONTROL_BAR_BASE_BUILD_TEST,
    GAME_LOGIC_FIND_OBJECT_BY_ID,
    MODEL_CONDITION_BASE_BUILD,
    NAME_KEY_FROM_CSTR,
    OBJECT_FIND_MODULE,
    OBJECT_TEST_MODEL_CONDITION,
    THE_GAME_LOGIC,
    THE_NAME_KEY_GENERATOR,
)
from sage_patch.patches.castle_unpack_buttons import (
    ANCHORS,
    HOOK_ORIGINAL,
    HOOK_VA,
    SECTION_NAME,
    CastleUnpackButtonsPatch,
    build_code,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import call_rel32, find_section, va_to_offset
from tests.sage_patch.synthetic import castle_unpack_buttons_image


def _read(data: bytes | bytearray, va: int, n: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + n])


def _cave_va(data: bytes | bytearray) -> int:
    located = find_section(data, SECTION_NAME)
    assert located is not None, f"no {SECTION_NAME} section"
    return located[0]


@pytest.fixture
def image() -> bytearray:
    return castle_unpack_buttons_image()


@pytest.fixture
def patched() -> bytearray:
    data = castle_unpack_buttons_image()
    CastleUnpackButtonsPatch().apply(data)
    return data


class TestStructure:
    def test_the_hook_is_the_base_build_test(self) -> None:
        assert HOOK_ORIGINAL == bytes.fromhex("e8a5fad4ff")
        assert HOOK_VA == CONTROL_BAR_BASE_BUILD_TEST + 7
        # push 0xdb: the index the cave forwards is BASE_BUILD's.
        assert ANCHORS[CONTROL_BAR_BASE_BUILD_TEST][:5] == b"\x68" + struct.pack(
            "<I", MODEL_CONDITION_BASE_BUILD
        )

    def test_the_hook_calls_the_cave(self, patched: bytearray) -> None:
        assert _read(patched, HOOK_VA, 5) == call_rel32(HOOK_VA, _cave_va(patched))

    def test_the_rest_of_the_test_is_untouched(self, image: bytearray, patched: bytearray) -> None:
        assert _read(patched, CONTROL_BAR_BASE_BUILD_TEST, 7) == _read(
            image, CONTROL_BAR_BASE_BUILD_TEST, 7
        )
        assert _read(patched, HOOK_VA + 5, 8) == _read(image, HOOK_VA + 5, 8)

    def test_the_state_it_reads_is_the_one_the_update_writes(self) -> None:
        # `mov [esi+0x24], 2` with `esi` the update interface at module +0x10.
        start_fade = ANCHORS[CASTLE_BEHAVIOR_START_FADE]
        assert start_fade[4:11] == bytes([0xC7, 0x46, CASTLE_BEHAVIOR_STATE - 0x10, 2, 0, 0, 0])
        assert CASTLE_STATE_FADING == 2

    def test_the_cave_decodes_as_written(self) -> None:
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        base = 0x01000000
        listing = [f"{i.mnemonic} {i.op_str}" for i in md.disasm(build_code(base), base)]
        assert listing[:6] == [
            "push esi",
            "mov esi, ecx",
            "push dword ptr [esp + 8]",
            f"call {OBJECT_TEST_MODEL_CONDITION:#x}",
            "test eax, eax",
            f"jne {base + 0x80:#x}",
        ]
        assert "cmp dword ptr [eax + 0x34], 2" in listing
        assert listing[-2:] == ["pop esi", "ret 4"]


class TestLifecycle:
    def test_apply_verify_detect(self, patched: bytearray) -> None:
        assert CastleUnpackButtonsPatch().verify(patched) == []
        assert isinstance(CastleUnpackButtonsPatch.detect(patched), CastleUnpackButtonsPatch)

    def test_an_unpatched_image_is_not_detected(self, image: bytearray) -> None:
        assert CastleUnpackButtonsPatch().verify(image) != []
        assert CastleUnpackButtonsPatch.detect(image) is None

    def test_a_second_apply_refuses_before_writing(self, patched: bytearray) -> None:
        before = bytes(patched)
        with pytest.raises(ValueError, match="already carries this patch"):
            CastleUnpackButtonsPatch().apply(patched)
        assert bytes(patched) == before

    @pytest.mark.parametrize("va", sorted(ANCHORS), ids=lambda va: f"{va:#010x}")
    def test_a_drifted_anchor_refuses_before_writing(self, image: bytearray, va: int) -> None:
        off = va_to_offset(image, va)
        assert off is not None
        image[off] ^= 0xFF
        before = bytes(image)
        with pytest.raises(ValueError, match="layout is not this build's"):
            CastleUnpackButtonsPatch().apply(image)
        assert bytes(image) == before

    def test_registered_as_settled(self) -> None:
        assert PATCHES["castle-unpack-buttons"] is CastleUnpackButtonsPatch
        assert not CastleUnpackButtonsPatch.experimental


unicorn = pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX,
    UC_X86_REG_ECX,
    UC_X86_REG_EIP,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

_PAGE = 0x1000
_CAVE = 0x01000000
_HEAP = 0x20000000
_STACK = 0x30000000
_RETURN = 0x40000000
_NAME_KEYS, _GAME_LOGIC = 0x0BADC0DE, 0x06A3E106
_CALLER_ESI = 0x5E5E5E5E

_SELECTED, _FLAG = _HEAP + 0x100, _HEAP + 0x200
_MEMBER_MODULE, _CASTLE_MODULE = _HEAP + 0x400, _HEAP + 0x500


@dataclass
class World:
    """The selected object and the flag that unpacked it, as the stubs see them."""

    base_build: bool = False
    member: bool = True
    castle_id: int = 0x1234
    flag_alive: bool = True
    castle_behavior: bool = True
    state: int = CASTLE_STATE_FADING
    calls: list[tuple[str, int, tuple[int, ...]]] = field(default_factory=list)


def _run(world: World) -> tuple[int, World]:
    """Call the cave as the bar calls `testModelCondition(BASE_BUILD)` and return its answer."""
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    pages = {_CAVE, _HEAP, _STACK, _RETURN, CASTLE_MEMBER_BEHAVIOR_NAME_STRING & ~0xFFF}
    pages |= {THE_NAME_KEY_GENERATOR & ~0xFFF, THE_GAME_LOGIC & ~0xFFF}
    pages |= {
        fn & ~0xFFF
        for fn in (
            OBJECT_TEST_MODEL_CONDITION,
            NAME_KEY_FROM_CSTR,
            OBJECT_FIND_MODULE,
            GAME_LOGIC_FIND_OBJECT_BY_ID,
        )
    }
    # `mem_map` raises and catches an SEH access violation inside Unicorn on Windows; every map
    # still succeeds, but the fault handler would print a stack for each one.
    was_enabled = faulthandler.is_enabled()
    faulthandler.disable()
    try:
        for page in sorted(pages):
            uc.mem_map(page, _PAGE)
    finally:
        if was_enabled:
            faulthandler.enable()

    uc.mem_write(_CAVE, build_code(_CAVE))
    uc.mem_write(CASTLE_MEMBER_BEHAVIOR_NAME_STRING, b"CastleMemberBehavior\x00")
    uc.mem_write(CASTLE_BEHAVIOR_NAME_STRING, b"CastleBehavior\x00")
    uc.mem_write(THE_NAME_KEY_GENERATOR, struct.pack("<I", _NAME_KEYS))
    uc.mem_write(THE_GAME_LOGIC, struct.pack("<I", _GAME_LOGIC))
    uc.mem_write(_MEMBER_MODULE + CASTLE_MEMBER_CASTLE_ID, struct.pack("<I", world.castle_id))
    uc.mem_write(_CASTLE_MODULE + CASTLE_BEHAVIOR_STATE, struct.pack("<I", world.state))

    keys = {"CastleMemberBehavior": 0x111, "CastleBehavior": 0x222}
    modules = {
        (_SELECTED, keys["CastleMemberBehavior"]): _MEMBER_MODULE if world.member else 0,
        (_FLAG, keys["CastleBehavior"]): _CASTLE_MODULE if world.castle_behavior else 0,
    }

    def answer(name: str, this: int, args: tuple[int, ...]) -> int:
        if name == "testModelCondition":
            return int(world.base_build and args[0] == MODEL_CONDITION_BASE_BUILD)
        if name == "nameKey":
            text = bytes(uc.mem_read(args[0], 32)).split(b"\x00")[0].decode()
            return keys[text]
        if name == "findModule":
            return modules.get((this, args[0]), 0)
        assert name == "findObjectByID"
        return _FLAG if args[0] == world.castle_id and args[0] and world.flag_alive else 0

    stubs = {
        OBJECT_TEST_MODEL_CONDITION: "testModelCondition",
        NAME_KEY_FROM_CSTR: "nameKey",
        OBJECT_FIND_MODULE: "findModule",
        GAME_LOGIC_FIND_OBJECT_BY_ID: "findObjectByID",
    }

    def on_code(emu: Uc, address: int, _size: int, _user: object) -> None:
        name = stubs.get(address)
        if name is None:
            return
        # Every helper is `__thiscall` with one stack argument and `ret 4`.
        esp = emu.reg_read(UC_X86_REG_ESP)
        ret, arg = struct.unpack("<II", bytes(emu.mem_read(esp, 8)))
        this = emu.reg_read(UC_X86_REG_ECX)
        world.calls.append((name, this, (arg,)))
        emu.reg_write(UC_X86_REG_EAX, answer(name, this, (arg,)))
        emu.reg_write(UC_X86_REG_ESP, esp + 8)
        emu.reg_write(UC_X86_REG_EIP, ret)

    uc.hook_add(UC_HOOK_CODE, on_code)

    esp = _STACK + 0x800
    esp -= 4
    uc.mem_write(esp, struct.pack("<I", MODEL_CONDITION_BASE_BUILD))
    esp -= 4
    uc.mem_write(esp, struct.pack("<I", _RETURN))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ECX, _SELECTED)
    uc.reg_write(UC_X86_REG_ESI, _CALLER_ESI)
    uc.emu_start(_CAVE, _RETURN, count=200)

    assert uc.reg_read(UC_X86_REG_ESP) == esp + 8, "ret 4 must leave the caller's stack level"
    assert uc.reg_read(UC_X86_REG_ESI) == _CALLER_ESI, "the bar's esi must survive"
    return uc.reg_read(UC_X86_REG_EAX), world


class TestTheCaveAnswers:
    def test_base_build_answers_without_looking_further(self) -> None:
        answer, world = _run(World(base_build=True, member=False))
        assert answer == 1
        assert world.calls == [("testModelCondition", _SELECTED, (MODEL_CONDITION_BASE_BUILD,))]

    def test_a_member_of_a_fading_castle_is_building(self) -> None:
        answer, world = _run(World())
        assert answer == 1
        assert [(name, this) for name, this, _ in world.calls] == [
            ("testModelCondition", _SELECTED),
            ("nameKey", _NAME_KEYS),
            ("findModule", _SELECTED),
            ("findObjectByID", _GAME_LOGIC),
            ("nameKey", _NAME_KEYS),
            ("findModule", _FLAG),
        ]

    @pytest.mark.parametrize("state", [0, 1, 3, 4, 5])
    def test_any_other_castle_state_is_not(self, state: int) -> None:
        assert _run(World(state=state))[0] == 0

    @pytest.mark.parametrize(
        "world",
        [
            World(member=False),
            World(castle_id=0),
            World(flag_alive=False),
            World(castle_behavior=False),
        ],
        ids=["not a castle member", "never stamped", "flag gone", "flag has no CastleBehavior"],
    )
    def test_a_broken_chain_is_not_building(self, world: World) -> None:
        assert _run(world)[0] == 0


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

    def test_every_site_is_stock(self, which: str) -> None:
        stock = self._stock(which)
        assert _read(stock, HOOK_VA, 5) == HOOK_ORIGINAL
        for va, expected in ANCHORS.items():
            assert _read(stock, va, len(expected)) == expected, f"{va:#010x}"

    def test_apply_verify_detect_round_trip(self, which: str) -> None:
        data = bytearray(self._stock(which))
        CastleUnpackButtonsPatch().apply(data)
        assert CastleUnpackButtonsPatch().verify(data) == []
        assert isinstance(CastleUnpackButtonsPatch.detect(data), CastleUnpackButtonsPatch)
