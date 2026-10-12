"""Tests for the shared-control-on-leave patch.

Four edits and one bit of state per player, so what can go wrong without raising is the relation
the three routines share and the bookkeeping around it: who counts as an ally still playing, when
the leaver is marked and when everything is handed over instead, and that the order filter and
the client predicate agree. So the real filter loop, the real predicate and the real stock leave
arm are run beside the cave over small worlds of players, with the engine calls answered from a
model.
"""

from __future__ import annotations

import faulthandler
import struct
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from sage_patch.addresses import (
    AIGROUP_REMOVE_NOT_OWNED_BY,
    AIGROUP_REMOVE_NOT_OWNED_BY_BYTES,
    AIGROUP_REMOVE_NOT_OWNED_BY_OWNER_CALL,
    OBJECT_GET_CONTROLLING_PLAYER,
    OBJECT_IS_LOCALLY_CONTROLLED,
    PLAYER_DEFAULT_TEAM,
    PLAYER_GET_RELATIONSHIP,
    PLAYER_INDEX,
    PLAYER_IS_DEFEATED,
    PLAYER_IS_OBSERVER,
    PLAYER_KILL_PLAYER,
    PLAYER_LIST_COUNT_OFFSET,
    PLAYER_LIST_LOCAL_PLAYER,
    PLAYER_TRANSFER_ASSETS_FROM,
    PLAYER_TYPE,
    SELF_DESTRUCT_DONE,
    SELF_DESTRUCT_LEAVER_EBP,
    SELF_DESTRUCT_TRANSFER_ARM,
    SELF_DESTRUCT_TRANSFER_ARM_BYTES,
    THE_PLAYER_LIST,
    THE_VICTORY_CONDITIONS,
    VICTORY_CONDITIONS_HAS_BEEN_DEFEATED,
    VICTORY_CONDITIONS_RESET,
    VICTORY_CONDITIONS_RESET_SLOT,
    VICTORY_CONDITIONS_VTABLE,
)
from sage_patch.patches.experimental.shared_control_on_leave import (
    ANCHORS,
    SECTION_NAME,
    SharedControlOnLeavePatch,
    build_code,
    edits,
    layout,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import call_rel32, find_section, va_to_offset
from tests.sage_patch.synthetic import shared_control_on_leave_image

_RESET_SLOT = VICTORY_CONDITIONS_VTABLE + VICTORY_CONDITIONS_RESET_SLOT


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
    return shared_control_on_leave_image()


@pytest.fixture
def patched() -> bytearray:
    data = shared_control_on_leave_image()
    SharedControlOnLeavePatch().apply(data)
    return data


class TestStructure:
    def test_the_owner_hook_is_the_getter_call(self) -> None:
        at = AIGROUP_REMOVE_NOT_OWNED_BY_OWNER_CALL - AIGROUP_REMOVE_NOT_OWNED_BY
        assert AIGROUP_REMOVE_NOT_OWNED_BY_BYTES[at : at + 5] == call_rel32(
            AIGROUP_REMOVE_NOT_OWNED_BY_OWNER_CALL, OBJECT_GET_CONTROLLING_PLAYER
        )

    def test_the_arm_ends_where_its_paths_meet(self) -> None:
        end = SELF_DESTRUCT_TRANSFER_ARM + len(SELF_DESTRUCT_TRANSFER_ARM_BYTES)
        assert end == SELF_DESTRUCT_DONE

    def test_every_edit_lands(self, patched: bytearray) -> None:
        for va, (new, _what) in edits(_cave_va(patched)).items():
            assert _read(patched, va, len(new)) == new, f"0x{va:08x}"

    def test_nothing_else_moves(self, image: bytearray, patched: bytearray) -> None:
        """Outside the four edits and the new section, the image is the stock one."""
        before, after = bytearray(image), bytearray(patched[: len(image)])
        for va, (new, _what) in edits(_cave_va(patched)).items():
            off = va_to_offset(image, va)
            assert off is not None
            before[off : off + len(new)] = after[off : off + len(new)] = bytes(len(new))
        for va, stock in ANCHORS.items():
            off = va_to_offset(image, va)
            assert off is not None
            assert before[off : off + len(stock)] == after[off : off + len(stock)], f"0x{va:08x}"

    def test_the_mask_starts_clear(self, patched: bytearray) -> None:
        cave = _cave_va(patched)
        assert layout(cave).label_va("mask") == cave
        assert _read(patched, cave, 4) == bytes(4)

    def test_the_cave_decodes_whole(self, patched: bytearray) -> None:
        """A linear sweep from the first routine reaches the last byte: no instruction is cut
        short, and nothing but the mask is data."""
        capstone = pytest.importorskip("capstone")
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        cave = _cave_va(patched)
        code = build_code(cave)
        assert _read(patched, cave, len(code)) == code
        decoded = sum(i.size for i in md.disasm(code[4:], cave + 4))
        assert decoded == len(code) - 4


class TestLifecycle:
    def test_apply_verify_detect(self, patched: bytearray) -> None:
        assert SharedControlOnLeavePatch().verify(patched) == []
        assert isinstance(SharedControlOnLeavePatch.detect(patched), SharedControlOnLeavePatch)

    def test_an_unpatched_image_is_not_detected(self, image: bytearray) -> None:
        assert SharedControlOnLeavePatch().verify(image) != []
        assert SharedControlOnLeavePatch.detect(image) is None

    def test_a_second_apply_refuses(self, patched: bytearray) -> None:
        with pytest.raises(ValueError, match="already carries this patch"):
            SharedControlOnLeavePatch().apply(patched)

    @pytest.mark.parametrize("va", sorted(ANCHORS), ids=lambda va: f"{va:08x}")
    def test_every_anchor_is_load_bearing(self, image: bytearray, va: int) -> None:
        """Disturb one window: `apply` refuses before writing, and a patched image stops
        verifying."""
        off = va_to_offset(image, va)
        assert off is not None
        # the last byte: every edit sits at the start or in the middle of its window, except the
        # repointed vtable slot, which is the whole of its own
        image[off + len(ANCHORS[va]) - 1] ^= 0xFF
        before = bytes(image)
        with pytest.raises(ValueError, match=f"@0x{va:08x}"):
            SharedControlOnLeavePatch().apply(image)
        assert bytes(image) == before

        data = shared_control_on_leave_image()
        SharedControlOnLeavePatch().apply(data)
        off = va_to_offset(data, va)
        assert off is not None
        data[off + len(ANCHORS[va]) - 1] ^= 0xFF
        assert SharedControlOnLeavePatch().verify(data) != []

    def test_registered_as_experimental(self) -> None:
        assert PATCHES["shared-control-on-leave"] is SharedControlOnLeavePatch
        assert SharedControlOnLeavePatch.experimental


unicorn = pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EDI,
    UC_X86_REG_EIP,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

_PAGE = 0x1000
_HEAP = 0x20000000
_STACK = 0x30000000
_EBP = _STACK + 0x800
#: Where a routine entered by `call` returns to: an address nothing else is mapped near.
_RETURN = 0x40000000

_PLAYER_LIST = _HEAP
_VICTORY = _HEAP + 0x100
_MESSAGE = _HEAP + 0x200
_GROUP = _HEAP + 0x300
_NODES = _HEAP + 0x400
_OBJECTS = _HEAP + 0x800
_PLAYERS = _HEAP + 0x10000  # a page each
_TEAM = 0xF00  # each stand-in player's default team sits at this offset inside it

#: `AIGroup::remove(Object *)`, the filter's other callee.
_AIGROUP_REMOVE = 0x0076EC79

HUMAN, COMPUTER = 0, 1

#: What each stubbed engine routine takes off the stack besides its return address.
_ARGS = {
    OBJECT_GET_CONTROLLING_PLAYER: 0,
    PLAYER_GET_RELATIONSHIP: 1,
    PLAYER_TRANSFER_ASSETS_FROM: 2,
    PLAYER_KILL_PLAYER: 0,
    VICTORY_CONDITIONS_HAS_BEEN_DEFEATED: 1,
    _AIGROUP_REMOVE: 1,
}


@dataclass
class Seat:
    team: int
    kind: int = HUMAN
    defeated: bool = False  # what `hasBeenDefeated` answers
    dead: bool = False  # `Player::m_isPlayerDead`, the hard flag `killPlayer` sets
    observer: bool = False


@dataclass
class World:
    """Seats by `ThePlayerList` index, the abandoned mask as it stands, and what the engine was
    asked to do. Two seats are allies when their `team` matches, unless `one_way` names the pair
    as `(who, whom)` for a `who` that no longer sees `whom` as one."""

    seats: list[Seat | None]
    mask: int = 0
    one_way: set[tuple[int, int]] = field(default_factory=set)
    did: list[tuple[str, int, int]] = field(default_factory=list)

    def player(self, index: int | None) -> int:
        return 0 if index is None else _PLAYERS + index * _PAGE

    def index(self, player: int) -> int:
        index, rest = divmod(player - _PLAYERS, _PAGE)
        assert rest == 0 and self.seats[index] is not None, f"{player:#x} is not a player"
        return index

    def abandoned(self) -> list[int]:
        return [i for i in range(len(self.seats)) if self.mask >> i & 1]


def _emulator(data: bytes | bytearray, world: World, objects: list[int | None]) -> Uc:
    """An emulator holding every planted window of `data`, the cave if there is one, and
    `world` laid out the way the routines read it. `objects` are owner seats, by object."""
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    cave = find_section(data, SECTION_NAME)
    pages = {va & ~0xFFF for va in (*ANCHORS, *_ARGS, THE_PLAYER_LIST, THE_VICTORY_CONDITIONS)}
    pages |= {_HEAP, _STACK, _RETURN}
    pages |= {_PLAYERS + i * _PAGE for i in range(len(world.seats))}
    if cave is not None:
        pages.add(cave[0] & ~0xFFF)
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

    for va, stock in ANCHORS.items():
        uc.mem_write(va, _read(data, va, len(stock)))
    if cave is not None:
        uc.mem_write(cave[0], _read(data, cave[0], len(build_code(cave[0]))))
        uc.mem_write(cave[0], struct.pack("<I", world.mask))

    uc.mem_write(THE_PLAYER_LIST, struct.pack("<I", _PLAYER_LIST))
    uc.mem_write(THE_VICTORY_CONDITIONS, struct.pack("<I", _VICTORY))
    uc.mem_write(_VICTORY, struct.pack("<I", VICTORY_CONDITIONS_VTABLE))
    uc.mem_write(_PLAYER_LIST + PLAYER_LIST_COUNT_OFFSET, struct.pack("<I", len(world.seats)))
    for index, seat in enumerate(world.seats):
        if seat is None:
            continue
        player = world.player(index)
        uc.mem_write(_PLAYER_LIST + 0x18 + index * 4, struct.pack("<I", player))
        uc.mem_write(player + PLAYER_INDEX, struct.pack("<I", index))
        uc.mem_write(player + PLAYER_TYPE, struct.pack("<I", seat.kind))
        uc.mem_write(player + PLAYER_DEFAULT_TEAM, struct.pack("<I", player + _TEAM))
        uc.mem_write(player + PLAYER_IS_DEFEATED, bytes([seat.dead]))
        uc.mem_write(player + PLAYER_IS_OBSERVER, bytes([seat.observer]))

    def answer(fn: int, this: int, args: tuple[int, ...]) -> int:
        if fn == OBJECT_GET_CONTROLLING_PLAYER:
            return world.player(objects[(this - _OBJECTS) // 0x10])
        if fn == PLAYER_GET_RELATIONSHIP:
            who, whom = world.index(this), world.index(args[0] - _TEAM)
            a, b = world.seats[who], world.seats[whom]
            assert a is not None and b is not None
            return 2 if a.team == b.team and (who, whom) not in world.one_way else 0
        if fn == VICTORY_CONDITIONS_HAS_BEEN_DEFEATED:
            assert this == _VICTORY
            seat = world.seats[world.index(args[0])]
            assert seat is not None
            return int(seat.defeated or seat.dead)
        if fn == PLAYER_TRANSFER_ASSETS_FROM:
            assert args[1] == 1
            world.did.append(("transfer", world.index(this), world.index(args[0])))
            return 0
        if fn == PLAYER_KILL_PLAYER:
            index = world.index(this)
            seat = world.seats[index]
            assert seat is not None
            seat.dead = True
            uc.mem_write(this + PLAYER_IS_DEFEATED, b"\x01")
            world.did.append(("kill", index, index))
            return 0
        assert fn == _AIGROUP_REMOVE and this == _GROUP
        world.did.append(("remove", (args[0] - _OBJECTS) // 0x10, 0))
        return 0  # the group has not emptied

    def on_code(emu: Uc, address: int, _size: int, _user: object) -> None:
        if address in (_RETURN, SELF_DESTRUCT_DONE, VICTORY_CONDITIONS_RESET):
            emu.emu_stop()
            return
        if address not in _ARGS:
            return
        n = _ARGS[address]
        esp = emu.reg_read(UC_X86_REG_ESP)
        ret, *args = struct.unpack(f"<{n + 1}I", bytes(emu.mem_read(esp, 4 * (n + 1))))
        result = answer(address, emu.reg_read(UC_X86_REG_ECX), tuple(args))
        emu.reg_write(UC_X86_REG_EAX, result)
        # an engine routine keeps none of the scratch registers
        emu.reg_write(UC_X86_REG_ECX, 0xCCCCCCCC)
        emu.reg_write(UC_X86_REG_ESP, esp + 4 * (n + 1))
        emu.reg_write(UC_X86_REG_EIP, ret)

    uc.hook_add(UC_HOOK_CODE, on_code)
    return uc


def _finish(uc: Uc, data: bytes | bytearray, world: World) -> None:
    cave = find_section(data, SECTION_NAME)
    if cave is not None:
        world.mask = struct.unpack("<I", bytes(uc.mem_read(cave[0], 4)))[0]


def _leave(data: bytes | bytearray, world: World, leaver: int) -> list[tuple[str, int, int]]:
    """Run the leave order's transfer arm for `leaver` and return what it asked of the engine."""
    uc = _emulator(data, world, [])
    uc.mem_write(_MESSAGE + 0x14, struct.pack("<I", leaver))
    uc.mem_write(_EBP + SELF_DESTRUCT_LEAVER_EBP, struct.pack("<I", world.player(leaver)))
    esp = _EBP - 0x100
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_EBP, _EBP)
    uc.reg_write(UC_X86_REG_EBX, 0)
    uc.reg_write(UC_X86_REG_ESI, _MESSAGE)
    world.did.clear()
    uc.emu_start(SELF_DESTRUCT_TRANSFER_ARM, 0, count=5000)
    assert uc.reg_read(UC_X86_REG_EIP) == SELF_DESTRUCT_DONE, "the arm did not reach its exit"
    assert uc.reg_read(UC_X86_REG_ESP) == esp, "the stack did not come back level"
    assert uc.reg_read(UC_X86_REG_EBX) == 0, "ebx, the dispatcher's zero, was clobbered"
    assert uc.reg_read(UC_X86_REG_ESI) == _MESSAGE, "esi, the message, was clobbered"
    _finish(uc, data, world)
    return list(world.did)


def _kept(data: bytes | bytearray, world: World, sender: int, owners: list[int | None]) -> list:
    """Run the order filter over a selection of objects owned by `owners`, and return the
    positions it kept."""
    uc = _emulator(data, world, owners)
    # a circular list headed by a sentinel: `[node]` the next node, `[node+8]` the object
    nodes = [_NODES + i * 0x10 for i in range(len(owners) + 1)]
    uc.mem_write(_GROUP + 4, struct.pack("<I", nodes[0]))
    for i, node in enumerate(nodes):
        obj = _OBJECTS + (i - 1) * 0x10 if i else 0
        uc.mem_write(node, struct.pack("<III", nodes[(i + 1) % len(nodes)], 0, obj))
    esp = _STACK + 0x400
    uc.mem_write(esp, struct.pack("<II", _RETURN, world.player(sender)))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ECX, _GROUP)
    uc.reg_write(UC_X86_REG_EBX, 0x0B0B0B0B)
    uc.reg_write(UC_X86_REG_ESI, 0x05050505)
    uc.reg_write(UC_X86_REG_EDI, 0x0D0D0D0D)
    world.did.clear()
    uc.emu_start(AIGROUP_REMOVE_NOT_OWNED_BY, 0, count=5000)
    assert uc.reg_read(UC_X86_REG_EIP) == _RETURN, "the filter did not return"
    assert uc.reg_read(UC_X86_REG_ESP) == esp + 8, "the filter did not pop its argument"
    assert uc.reg_read(UC_X86_REG_EBX) == 0x0B0B0B0B
    assert uc.reg_read(UC_X86_REG_ESI) == 0x05050505
    assert uc.reg_read(UC_X86_REG_EDI) == 0x0D0D0D0D
    removed = {obj for what, obj, _ in world.did if what == "remove"}
    return [i for i in range(len(owners)) if i not in removed]


def _local(data: bytes | bytearray, world: World, local: int | None, owner: int | None) -> bool:
    """`Object::isLocallyControlled` for an object of `owner`, with `local` at the keyboard."""
    uc = _emulator(data, world, [owner])
    uc.mem_write(_PLAYER_LIST + PLAYER_LIST_LOCAL_PLAYER, struct.pack("<I", world.player(local)))
    esp = _STACK + 0x400
    uc.mem_write(esp, struct.pack("<I", _RETURN))
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ECX, _OBJECTS)
    uc.reg_write(UC_X86_REG_EBX, 0x0B0B0B0B)
    uc.reg_write(UC_X86_REG_ESI, 0x05050505)
    uc.reg_write(UC_X86_REG_EDI, 0x0D0D0D0D)
    uc.emu_start(OBJECT_IS_LOCALLY_CONTROLLED, 0, count=5000)
    assert uc.reg_read(UC_X86_REG_EIP) == _RETURN, "the predicate did not return"
    assert uc.reg_read(UC_X86_REG_ESP) == esp + 4
    assert uc.reg_read(UC_X86_REG_EBX) == 0x0B0B0B0B
    assert uc.reg_read(UC_X86_REG_ESI) == 0x05050505
    assert uc.reg_read(UC_X86_REG_EDI) == 0x0D0D0D0D
    answer = uc.reg_read(UC_X86_REG_EAX)
    assert answer in (0, 1), "callers test the whole register"
    return bool(answer)


def _two_on_two() -> World:
    return World([Seat(1), Seat(1), Seat(2), Seat(2)])


class TestLeaving:
    def test_a_leaver_with_a_human_ally_keeps_everything(self, patched: bytearray) -> None:
        world = _two_on_two()
        assert _leave(patched, world, 0) == []
        assert world.abandoned() == [0]

    def test_stock_hands_the_same_leaver_to_that_ally(self, image: bytearray) -> None:
        assert _leave(image, _two_on_two(), 0) == [("transfer", 1, 0), ("kill", 0, 0)]

    def test_the_last_human_takes_the_team_with_them(self, patched: bytearray) -> None:
        world = _two_on_two()
        _leave(patched, world, 0)
        assert _leave(patched, world, 1) == [("kill", 0, 0), ("kill", 1, 1)]
        assert world.abandoned() == []

    def test_the_other_team_is_left_alone(self, patched: bytearray) -> None:
        world = _two_on_two()
        _leave(patched, world, 0)
        _leave(patched, world, 2)
        assert world.abandoned() == [0, 2]
        assert _leave(patched, world, 3) == [("kill", 2, 2), ("kill", 3, 3)]
        assert world.abandoned() == [0]

    def test_a_remaining_ai_inherits_from_every_leaver(self, patched: bytearray) -> None:
        world = World([Seat(1), Seat(1), Seat(1, COMPUTER), Seat(2)])
        assert _leave(patched, world, 1) == []
        assert _leave(patched, world, 0) == [
            ("transfer", 2, 0),
            ("kill", 0, 0),
            ("transfer", 2, 1),
            ("kill", 1, 1),
        ]
        assert world.abandoned() == []

    def test_an_ai_ally_is_not_someone_to_share_with(
        self, image: bytearray, patched: bytearray
    ) -> None:
        """With only an AI beside them the leaver is handed over, exactly as stock."""
        want = [("transfer", 1, 0), ("kill", 0, 0)]
        for data in (image, patched):
            world = World([Seat(1), Seat(1, COMPUTER), Seat(2)])
            assert _leave(data, world, 0) == want
            assert world.abandoned() == []

    @pytest.mark.parametrize(
        "world",
        [
            World([Seat(1), Seat(2)]),
            World([Seat(1), Seat(1, defeated=True), Seat(2)]),
            World([Seat(1), Seat(1), Seat(2)], one_way={(1, 0)}),
            World([Seat(1), Seat(1), Seat(2)], one_way={(0, 1)}),
            World([Seat(1), None, Seat(2)]),
        ],
        ids=["alone", "ally defeated", "ally turned", "leaver turned", "empty seat"],
    )
    def test_with_nobody_to_share_with_the_leaver_dies_as_stock(
        self, image: bytearray, patched: bytearray, world: World
    ) -> None:
        for data in (image, patched):
            assert _leave(data, world, 0) == [("kill", 0, 0)]
            assert world.abandoned() == []
            seat = world.seats[0]
            assert seat is not None
            seat.dead = False

    def test_an_abandoned_ally_does_not_count_as_one_still_playing(
        self, patched: bytearray
    ) -> None:
        """Three humans: the second leaver still has the third, the third has nobody."""
        world = World([Seat(1), Seat(1), Seat(1), Seat(2)])
        assert _leave(patched, world, 0) == []
        assert _leave(patched, world, 2) == []
        assert world.abandoned() == [0, 2]
        assert _leave(patched, world, 1) == [("kill", 0, 0), ("kill", 1, 1), ("kill", 2, 2)]

    def test_the_heir_is_never_a_leaver(self, patched: bytearray) -> None:
        """The stock search would pick seat 0, the first undefeated ally, though it has left."""
        world = World([Seat(1), Seat(1), Seat(2), Seat(1, COMPUTER)])
        _leave(patched, world, 0)
        assert _leave(patched, world, 1)[0] == ("transfer", 3, 0)


#: Who is asking, against an object of seat 0, which has left: `(asker seat, may command)`.
_ASKERS = {
    "ally": (Seat(1), True),
    "enemy": (Seat(2), False),
    "dead ally": (Seat(1, dead=True), False),
    "observing ally": (Seat(1, observer=True), False),
    "ai ally": (Seat(1, COMPUTER), True),
}


class TestCommanding:
    def test_stock_keeps_only_the_senders_objects(self, image: bytearray) -> None:
        assert _kept(image, _two_on_two(), 1, [1, 0, None, 2, 1]) == [0, 4]

    def test_nobody_has_left(self, patched: bytearray) -> None:
        assert _kept(patched, _two_on_two(), 1, [1, 0, None, 2, 1]) == [0, 4]

    def test_an_ally_commands_what_the_leaver_left(self, patched: bytearray) -> None:
        world = _two_on_two()
        _leave(patched, world, 0)
        assert _kept(patched, world, 1, [1, 0, None, 2, 1]) == [0, 1, 4]
        assert _kept(patched, world, 2, [1, 0, None, 2, 3]) == [3]

    @pytest.mark.parametrize("who", sorted(_ASKERS))
    def test_who_may_command(self, patched: bytearray, who: str) -> None:
        asker, allowed = _ASKERS[who]
        world = World([Seat(1), asker, Seat(2)], mask=0b001)
        assert _kept(patched, world, 1, [0]) == ([0] if allowed else [])
        assert _local(patched, world, 1, 0) is allowed

    @pytest.mark.parametrize("pair", [(1, 0), (0, 1)])
    def test_the_alliance_has_to_hold_both_ways(
        self, patched: bytearray, pair: tuple[int, int]
    ) -> None:
        world = World([Seat(1), Seat(1), Seat(2)], mask=0b001, one_way={pair})
        assert _kept(patched, world, 1, [0]) == []
        assert not _local(patched, world, 1, 0)

    def test_a_leaver_commands_nothing_of_a_playing_ally(self, patched: bytearray) -> None:
        world = World([Seat(1), Seat(1), Seat(2)], mask=0b001)
        assert _kept(patched, world, 0, [1]) == []

    @pytest.mark.parametrize("local", [0, 1, 2, None])
    @pytest.mark.parametrize("owner", [0, 1, 2, None])
    def test_the_predicate_is_stock_until_somebody_leaves(
        self, image: bytearray, patched: bytearray, local: int | None, owner: int | None
    ) -> None:
        world = World([Seat(1), Seat(1), Seat(2)])
        assert _local(patched, world, local, owner) is _local(image, world, local, owner)
        assert _local(image, world, local, owner) is (local == owner)

    def test_the_local_player_sees_the_leavers_objects_as_theirs(self, patched: bytearray) -> None:
        world = _two_on_two()
        _leave(patched, world, 0)
        assert [_local(patched, world, 1, owner) for owner in (0, 1, 2, 3, None)] == [
            True,
            True,
            False,
            False,
            False,
        ]
        assert not _local(patched, world, None, 0)


class TestReset:
    def test_a_new_game_forgets_who_left(self, patched: bytearray) -> None:
        world = World([Seat(1), Seat(1)], mask=0b11)
        uc = _emulator(patched, world, [])
        target = struct.unpack("<I", bytes(uc.mem_read(_RESET_SLOT, 4)))[0]
        uc.reg_write(UC_X86_REG_ESP, _STACK + 0x400)
        uc.reg_write(UC_X86_REG_ECX, _VICTORY)
        uc.emu_start(target, 0, count=100)
        assert uc.reg_read(UC_X86_REG_EIP) == VICTORY_CONDITIONS_RESET
        assert uc.reg_read(UC_X86_REG_ECX) == _VICTORY, "reset lost its `this`"
        assert uc.reg_read(UC_X86_REG_ESP) == _STACK + 0x400
        _finish(uc, patched, world)
        assert world.abandoned() == []


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

    def test_every_anchor_is_stock(self, which: str) -> None:
        stock = self._stock(which)
        for va, want in ANCHORS.items():
            assert _read(stock, va, len(want)) == want, f"0x{va:08x}"

    def test_apply_verify_detect_round_trip(self, which: str) -> None:
        data = bytearray(self._stock(which))
        SharedControlOnLeavePatch().apply(data)
        assert SharedControlOnLeavePatch().verify(data) == []
        assert isinstance(SharedControlOnLeavePatch.detect(data), SharedControlOnLeavePatch)
