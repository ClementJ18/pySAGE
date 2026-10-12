"""The `wotr-battle-observers` cave, executed over a synthetic battle.

The sibling test file disassembles the cave and asserts it *says* the right thing. This one runs
it and asserts it *does* the right thing: which seats come out marked occupied, which comparison
each naming hook leaves for the caller's `jl`, and what name the assignment hook writes.

Every configuration below is one the live game has actually produced, and the first is the one
that took two network sessions and a memory dump to diagnose: three seats, two of them fighting,
the third a human who is not - the seat that kept being handed `PlyrCivilian`.
"""

from __future__ import annotations

import pathlib
import struct

import pytest

pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")

from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX,
    UC_X86_REG_EIP,
    UC_X86_REG_ESP,
)

from sage_patch import WotrBattleObserversPatch  # noqa: E402
from sage_patch import addresses as ad  # noqa: E402
from sage_patch.patches.wotr_battle_observers import (  # noqa: E402
    FRAME_SLOT_INDEX,
    NAME_OFFSET,
    OBSERVER_SIDE_NAME,
    SECTION_NAME,
    build_cave,
)
from sage_patch.utils import find_section  # noqa: E402
from tests.sage_patch.test_wotr_battle_observers import synthetic_image  # noqa: E402
from tests.sage_patch.wotr_world import (  # noqa: E402
    HEAP_BASE,
    HEAP_SIZE,
    Emulator,
    Seat,
    build_world,
)

#: Scratch at the top of the synthetic heap, clear of what `build_world` allocates from its bottom.
HEAP_SCRATCH = HEAP_BASE + HEAP_SIZE - 0x1000

REAL_GAME_DAT = pathlib.Path(__file__).resolve().parents[2] / "game.dat"


def _patched_image() -> bytes:
    """The patched bytes to execute.

    The real `game.dat` when this checkout has one, because that is what ships; the synthetic PE
    otherwise, so the run still happens in CI. Only the cave is executed either way - the detour
    sites are never entered - so the two agree on everything these tests assert.
    """
    source = REAL_GAME_DAT.read_bytes() if REAL_GAME_DAT.exists() else bytes(synthetic_image())
    data = bytearray(source)
    WotrBattleObserversPatch().apply(data)
    return bytes(data)


@pytest.fixture(scope="module")
def image() -> bytes:
    return _patched_image()


@pytest.fixture(scope="module")
def entries(image) -> dict[str, int]:
    located = find_section(image, SECTION_NAME)
    assert located is not None
    return build_cave(located[0])[1]


@pytest.fixture(scope="module")
def cave_va(image) -> int:
    located = find_section(image, SECTION_NAME)
    assert located is not None
    return located[0]


def _co_op(**overrides):
    """The measured configuration: two humans and an AI, the battle being human 1 against the AI.

    Seat 0 is the odd one out - a human whose living-world player is on neither side.
    """
    seats = [
        Seat(state=ad.GAME_SLOT_STATE_LOCAL_HUMAN, living_world_id=0, occupied=0, start_pos=-1),
        Seat(state=ad.GAME_SLOT_STATE_LOCAL_HUMAN, living_world_id=1, occupied=1, start_pos=2),
        Seat(state=5, living_world_id=2, occupied=1, start_pos=1),
    ]
    return build_world(seats, fighting=(1, 2), **overrides)


def test_the_seat_that_is_not_fighting_is_marked_occupied(image, entries):
    """The bug that survived two builds. The engine leaves `m_isOccupied` clear on a seat that is
    not in the battle, and both of `buildSidesFromGameInfo`'s loops skip such a slot - so no other
    hook was ever reached for it and the client was seated on `PlyrCivilian`."""
    world, mem = _co_op()
    emu = Emulator(image, world, mem)
    emu.call(entries["hook_prepare"], eax=world.game_info, ebx=0)
    assert emu.occupied(world.seats[0]) == 1, "the seat that is out of the battle is put back in"


def test_the_seats_that_are_fighting_are_left_alone(image, entries):
    world, mem = _co_op()
    emu = Emulator(image, world, mem)
    emu.call(entries["hook_prepare"], eax=world.game_info, ebx=0)
    assert emu.occupied(world.seats[1]) == 1, "already occupied, and still is"
    assert emu.occupied(world.seats[2]) == 1, "the AI seat is untouched"


def test_an_ai_seat_out_of_the_battle_is_not_promoted(image, entries):
    """Only human seats need somewhere to sit. An AI that is not fighting has no client behind it,
    and giving it a side would put an extra player on the map."""
    seats = [
        Seat(state=ad.GAME_SLOT_STATE_LOCAL_HUMAN, living_world_id=0, occupied=1),
        Seat(state=5, living_world_id=1, occupied=1),
        Seat(state=5, living_world_id=2, occupied=0),
    ]
    world, mem = build_world(seats, fighting=(0, 1))
    emu = Emulator(image, world, mem)
    emu.call(entries["hook_prepare"], eax=world.game_info, ebx=0)
    assert emu.occupied(world.seats[2]) == 0


def test_a_lobby_observer_seat_is_left_to_the_engine(image, entries):
    """A negative player template is already the engine's own observer seat; it reaches the same
    arms without help, and touching it would change shipped behaviour."""
    seats = [
        Seat(state=ad.GAME_SLOT_STATE_LOCAL_HUMAN, living_world_id=0, occupied=1),
        Seat(state=ad.GAME_SLOT_STATE_LOCAL_HUMAN, living_world_id=1, occupied=1),
        Seat(
            state=ad.GAME_SLOT_STATE_LOCAL_HUMAN,
            living_world_id=2,
            occupied=0,
            player_template=ad.GAME_SLOT_OBSERVER_TEMPLATE,
        ),
    ]
    world, mem = build_world(seats, fighting=(0, 1))
    emu = Emulator(image, world, mem)
    emu.call(entries["hook_prepare"], eax=world.game_info, ebx=0)
    assert emu.occupied(world.seats[2]) == 0


@pytest.mark.parametrize(
    ("note", "overrides"),
    [
        ("not a living-world multiplayer session", {"living_world_type": 3}),
        ("the strategic map, no battle being entered", {"current_region_id": -1}),
        ("a battle in some other region", {"current_region_id": 4242}),
    ],
)
def test_nothing_is_touched_outside_a_battle(image, entries, note, overrides):
    """The cave answers "no" to anything it cannot resolve, which is what keeps it inert in a
    skirmish, on the strategic map and in a replay."""
    world, mem = _co_op(**overrides)
    emu = Emulator(image, world, mem)
    emu.call(entries["hook_prepare"], eax=world.game_info, ebx=0)
    assert emu.occupied(world.seats[0]) == 0, note


def test_the_name_hook_forces_the_observer_arm_for_the_odd_seat(image, entries):
    """`jl` picks the observer arm, so the hook has to leave the sign flag set for that seat and
    reproduce the stock comparison for every other."""
    world, mem = _co_op()
    emu = Emulator(image, world, mem)
    assert Emulator.less_than(emu.call(entries["hook_name"], esi=world.seats[0].address, ebx=0))
    assert not Emulator.less_than(
        emu.call(entries["hook_name"], esi=world.seats[1].address, ebx=0)
    ), "a seat that is fighting takes the stock path"


def test_a_fighter_on_either_side_is_recognised(image, entries):
    """The one that gives the battle walk teeth. Each side carries a decoy member ahead of its
    fighter, so finding the second fighter needs the side stride, the member stride and both
    vector bounds to be right - a fixture with one member per side absorbs all four."""
    seats = [
        Seat(state=ad.GAME_SLOT_STATE_LOCAL_HUMAN, living_world_id=0, occupied=0, start_pos=-1),
        Seat(state=ad.GAME_SLOT_STATE_LOCAL_HUMAN, living_world_id=1, occupied=1),
        Seat(state=ad.GAME_SLOT_STATE_LOCAL_HUMAN, living_world_id=2, occupied=1),
    ]
    world, mem = build_world(seats, fighting=(1, 2))
    emu = Emulator(image, world, mem)
    assert Emulator.less_than(emu.call(entries["hook_name"], esi=world.seats[0].address, ebx=0)), (
        "the seat on neither side is the observer"
    )
    for index in (1, 2):
        assert not Emulator.less_than(
            emu.call(entries["hook_name"], esi=world.seats[index].address, ebx=0)
        ), f"seat {index} is fighting on side {index - 1} and must take the stock path"


def test_the_faction_hook_agrees_with_the_name_hook(image, entries):
    """They run in different loops over the same slots and must not disagree, or a seat gets an
    observer name with a faction template or the reverse."""
    world, mem = _co_op()
    emu = Emulator(image, world, mem)
    assert Emulator.less_than(emu.call(entries["hook_faction"], esi=world.seats[0].address))
    flags = emu.call(entries["hook_faction"], esi=world.seats[1].address)
    assert not Emulator.less_than(flags)
    assert emu.eax() == world.seats[1].player_template, "the index the store is indexed with"


def test_the_assign_hook_writes_the_replay_observer_literal(image, entries, cave_va):
    """The whole point of the seat: a name that resolves to a side the game always carries."""
    world, mem = _co_op()
    emu = Emulator(image, world, mem)
    emu.call(entries["hook_name"], esi=world.seats[0].address, ebx=0)
    emu.call(entries["hook_assign"], esi=world.seats[0].address)
    assert emu.assignments == [(pytest.approx(emu.assignments[0][0]), cave_va + NAME_OFFSET)]


@pytest.mark.parametrize("slot", [0, 3, 7])
def test_each_observer_seat_gets_a_side_name_of_its_own(image, entries, cave_va, slot):
    """`ReplayObserver<slot + 1>`: every lookup from a side to a player is by name, so two seats
    with one name resolve to one player - measured as two black screens and one observer seeing
    every army."""
    world, mem = _co_op()
    emu = Emulator(image, world, mem)
    emu.uc.mem_write(Emulator.FRAME - FRAME_SLOT_INDEX, struct.pack("<I", slot))
    emu.call(entries["hook_name"], esi=world.seats[0].address, ebx=0)
    emu.call(entries["hook_assign"], esi=world.seats[0].address)
    name = bytes(emu.uc.mem_read(cave_va + NAME_OFFSET, 16))
    assert name == OBSERVER_SIDE_NAME + str(slot + 1).encode() + b"\x00"


def _ascii_string(emu: Emulator, text: bytes | None) -> int:
    """An `AsciiString` holding `text` (null for None), returned as the address of its handle."""
    handle = HEAP_SCRATCH
    if text is None:
        emu.uc.mem_write(handle, struct.pack("<I", 0))
        return handle
    data = handle + 0x10
    body = struct.pack("<IHH", 1, len(text), len(text) + 1) + text + b"\x00"
    emu.uc.mem_write(data, body)
    emu.uc.mem_write(handle, struct.pack("<I", data))
    return handle


@pytest.mark.parametrize(
    ("name", "observer"),
    [
        (b"ReplayObserver", True),  # the stock side, as a replay seats it
        (b"ReplayObserver1", True),
        (b"ReplayObserver8", True),
        (b"ReplayObserver12", False),
        (b"ReplayObserve", False),
        (b"Player_2", False),
        (b"replayobserver", False),  # the stock compare is case-sensitive, and so is this
        (b"", False),
        (None, False),
    ],
)
def test_the_observer_test_accepts_the_stem_and_one_more_character(
    image, entries, cave_va, name, observer
):
    world, mem = _co_op()
    emu = Emulator(image, world, mem)
    emu.uc.mem_write(HEAP_SCRATCH + 0x200, OBSERVER_SIDE_NAME + b"\x00")
    literal = HEAP_SCRATCH + 0x200
    handle = _ascii_string(emu, name)
    emu.call(entries["hook_observer_name"], ecx=handle, args=(literal,))
    # The stock callee is a compare: 0 for a match. `initFromSide` skips a human seat's set-up on 0.
    assert (emu.eax() == 0) is observer
    assert emu.uc.reg_read(UC_X86_REG_ESP) == Emulator.FRAME - 0x80, "ret 4, as the stock callee"


#: The callee the hook stands in for, `AsciiString::compare(const char *)`, and the two
#: `msvcr71` import thunks it reaches: `strlen` and `memcmp`, both cdecl.
STOCK_OBSERVER_NAME_TEST = 0x00406585
CRT_STRLEN_THUNK = 0x00A3CF10
CRT_MEMCMP_THUNK = 0x00A3D01A


def _answer_the_crt(emu: Emulator) -> None:
    """`strlen` and `memcmp` in Python: the imports are not mapped, the routine around them is."""
    uc = emu.uc

    def arg(i: int) -> int:
        esp = uc.reg_read(UC_X86_REG_ESP)
        return struct.unpack("<I", uc.mem_read(esp + 4 + i * 4, 4))[0]

    def ret(value: int) -> None:
        esp = uc.reg_read(UC_X86_REG_ESP)
        uc.reg_write(UC_X86_REG_EIP, struct.unpack("<I", uc.mem_read(esp, 4))[0])
        uc.reg_write(UC_X86_REG_ESP, esp + 4)
        uc.reg_write(UC_X86_REG_EAX, value & 0xFFFFFFFF)

    def strlen(_uc, _address, _size, _user) -> None:
        ret(bytes(uc.mem_read(arg(0), 0x100)).index(0))

    def memcmp(_uc, _address, _size, _user) -> None:
        left, right = (bytes(uc.mem_read(arg(i), arg(2))) for i in (0, 1))
        ret((left > right) - (left < right))

    for va, handler in ((CRT_STRLEN_THUNK, strlen), (CRT_MEMCMP_THUNK, memcmp)):
        uc.hook_add(1 << 2, handler, begin=va, end=va)  # UC_HOOK_CODE


@pytest.mark.skipif(not REAL_GAME_DAT.exists(), reason="runs the engine's own compare")
@pytest.mark.parametrize(
    "name", [b"ReplayObserver", b"ReplayObserve", b"ReplayObserver12", b"Player_2", b"", None]
)
def test_the_observer_test_answers_in_the_sense_the_stock_callee_does(image, entries, name):
    """Every name the hook does not widen gets the answer the engine's routine gives it, zero or
    not - the caller branches on that, so the sense is the contract."""
    world, mem = _co_op()
    answers = []
    for routine in (STOCK_OBSERVER_NAME_TEST, entries["hook_observer_name"]):
        emu = Emulator(image, world, mem)
        _answer_the_crt(emu)
        emu.uc.mem_write(HEAP_SCRATCH + 0x200, OBSERVER_SIDE_NAME + b"\x00")
        emu.call(routine, ecx=_ascii_string(emu, name), args=(HEAP_SCRATCH + 0x200,))
        answers.append(emu.eax() == 0)
    assert answers[0] == answers[1]
    assert answers[0] is (name == OBSERVER_SIDE_NAME)


def test_the_assign_hook_leaves_a_fighting_seat_named_as_the_engine_named_it(image, entries):
    world, mem = _co_op()
    emu = Emulator(image, world, mem)
    emu.call(entries["hook_name"], esi=world.seats[1].address, ebx=0)
    emu.call(entries["hook_assign"], esi=world.seats[1].address)
    assert emu.assignments == [], "no rename for a seat that is fighting"


def test_the_number_hook_counts_participants_not_slots(image, entries):
    """Stock numbering is `slot index + 2`, so an attacker outside slot 0 is named `Player_3` and
    the map has no such side. Seat 1 is the only fighting non-defender before seat 2, so seat 2
    would collide under stock numbering and does not here."""
    seats = [
        Seat(state=ad.GAME_SLOT_STATE_LOCAL_HUMAN, living_world_id=0, occupied=0, start_pos=-1),
        Seat(state=ad.GAME_SLOT_STATE_LOCAL_HUMAN, living_world_id=1, occupied=1),
        Seat(state=ad.GAME_SLOT_STATE_LOCAL_HUMAN, living_world_id=2, occupied=1),
    ]
    world, mem = build_world(seats, fighting=(1, 2))
    emu = Emulator(image, world, mem)
    # The frame slot the hook reads its slot index from is [ebp-0x18]; `call` sets ebp for us and
    # the index defaults to 0, so seat 0 is the one being named here.
    emu.call(entries["hook_number"])
    assert emu.eax() == 2, "the first seat to be numbered is always Player_2"


def _prepared(image, entries, world, mem) -> Emulator:
    """An emulator whose pre-pass has already run, which is what fills the observer mask.

    The start-position hook is the one hook that depends on state an *earlier* hook left behind,
    so calling it on a fresh emulator would test the inert path and nothing else.
    """
    emu = Emulator(image, world, mem)
    emu.call(entries["hook_prepare"])
    return emu


def test_the_observer_borrows_a_participants_start_position(image, entries):
    """The bug this hook exists for. Seat 0 is the observer, and its own `m_startPos` of 5 names
    `Player_6_Start` - a waypoint no two-army battle map has, which is what drops the camera in
    the map's bottom-left corner. Seat 1 is fighting on the observer's team, so its start is one
    the map really has; seat 2 is the AI army it is fighting."""
    seats = [
        Seat(living_world_id=0, occupied=0, start_pos=5, team=0),
        Seat(living_world_id=1, occupied=1, start_pos=2, team=0),
        Seat(state=5, living_world_id=2, occupied=1, start_pos=1, team=1),
    ]
    world, mem = build_world(seats, fighting=(1, 2))
    emu = _prepared(image, entries, world, mem)
    emu.call(entries["hook_start_pos"], esi=world.seats[0].address)
    assert emu.eax() == 3, "seat 1's start position, plus the one the format string wants"


def test_a_seat_that_is_fighting_keeps_its_own_start_position(image, entries):
    """Everybody goes through this hook, not just the observer, so the stock answer has to
    survive for the seats the patch is not there to help."""
    seats = [
        Seat(living_world_id=0, occupied=0, start_pos=5),
        Seat(living_world_id=1, occupied=1, start_pos=2),
        Seat(state=5, living_world_id=2, occupied=1, start_pos=1),
    ]
    world, mem = build_world(seats, fighting=(1, 2))
    emu = _prepared(image, entries, world, mem)
    emu.call(entries["hook_start_pos"], esi=world.seats[1].address)
    assert emu.eax() == 3, "seat 1's own start position, untouched"


def test_the_observer_prefers_an_ally_over_the_first_participant(image, entries):
    """Two armies are fighting and the observer is on one side of it. Borrowing the *enemy's*
    start would open the battle looking at the wrong base, and on a map where the two are far
    apart the ally's vision is not there to see - so the lobby team number decides, even though
    the enemy is the participant the scan reaches first."""
    seats = [
        Seat(living_world_id=0, occupied=0, start_pos=5, team=1),
        Seat(living_world_id=1, occupied=1, start_pos=0, team=0),
        Seat(living_world_id=2, occupied=1, start_pos=3, team=1),
    ]
    world, mem = build_world(seats, fighting=(1, 2))
    emu = _prepared(image, entries, world, mem)
    emu.call(entries["hook_start_pos"], esi=world.seats[0].address)
    assert emu.eax() == 4, "seat 2 shares the observer's team; seat 1 would have answered 1"


def test_an_observer_with_no_team_falls_back_to_the_first_participant(image, entries):
    """`-1` is the lobby's no-team value and the engine reads it as *everyone is an enemy*. There
    is no ally to prefer, and the map corner is still worse than somebody's base."""
    seats = [
        Seat(living_world_id=0, occupied=0, start_pos=5, team=-1),
        Seat(living_world_id=1, occupied=1, start_pos=0, team=0),
        Seat(living_world_id=2, occupied=1, start_pos=3, team=1),
    ]
    world, mem = build_world(seats, fighting=(1, 2))
    emu = _prepared(image, entries, world, mem)
    emu.call(entries["hook_start_pos"], esi=world.seats[0].address)
    assert emu.eax() == 1, "seat 1, the first participant in slot order"


def test_it_is_inert_when_the_pre_pass_seated_nobody(image, entries):
    """A skirmish, a replay, a battle everybody is in: the mask is empty and every seat keeps the
    start position the engine gave it. This is the path most games take."""
    seats = [
        Seat(living_world_id=1, occupied=1, start_pos=5),
        Seat(living_world_id=2, occupied=1, start_pos=2),
    ]
    world, mem = build_world(seats, fighting=(1, 2))
    emu = _prepared(image, entries, world, mem)
    emu.call(entries["hook_start_pos"], esi=world.seats[0].address)
    assert emu.eax() == 6, "seat 0's own start position"


def test_an_observer_with_no_participant_to_borrow_from_keeps_the_stock_answer(image, entries):
    """Nothing here can be better than the engine's own answer, so it has to be left alone rather
    than replaced with a zero - which would silently mean `Player_1_Start` for everybody."""
    seats = [
        Seat(living_world_id=0, occupied=0, start_pos=5),
        Seat(living_world_id=1, occupied=0, start_pos=2),
    ]
    world, mem = build_world(seats, fighting=())
    emu = _prepared(image, entries, world, mem)
    emu.call(entries["hook_start_pos"], esi=world.seats[0].address)
    assert emu.eax() == 6, "seat 0's own start position: neither seat is fighting"


def test_it_reproduces_the_push_the_format_string_consumes(image, entries):
    """The hook displaces `push eax` as well as the two instructions that compute it, so the
    argument has to be put back *under* the return address. Get this wrong and the format string
    reads the return address as its `%d` and the stack unwinds one dword out."""
    seats = [
        Seat(living_world_id=0, occupied=0, start_pos=5),
        Seat(living_world_id=1, occupied=1, start_pos=2),
    ]
    world, mem = build_world(seats, fighting=(1,))
    emu = _prepared(image, entries, world, mem)
    emu.call(entries["hook_start_pos"], esi=world.seats[0].address)
    assert emu.top_of_stack() == emu.eax() == 3
