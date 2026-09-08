"""A synthetic War of the Ring battle, and an emulator that runs the patch's cave over it.

The cave in `wotr-battle-observers` reads five engine structures and decides, per lobby seat,
whether that seat is fighting the battle the map is loading for. Every bug it has had so far was
of one kind: a field read at the wrong offset, a comparison with the wrong polarity, a register
clobbered across a call. None of those raise. They produce a patched binary that verifies clean,
applies clean, and then seats a player on the wrong army - which until now took a three-player
network game and a memory dump to find out.

So this builds the world in memory, maps the **real patched bytes** over it, and executes them.
`build_world` lays out a `GameInfo`, its slots, the living-world players and a battle at the
offsets `sage_patch.addresses` declares; `Emulator` maps the patched image plus that world into
Unicorn and runs one cave routine at a time.

**What it catches and what it cannot.** It runs the cave, so it catches everything the cave gets
wrong. It does not run `GameLogic::buildSidesFromGameInfo`, so it cannot catch the engine never
*reaching* a hook - which is exactly what the `m_isOccupied` skip was. For that class the fixture
is a lie by construction: it is written at the offsets we believe, so a wrong belief and a wrong
fixture cancel out. The answer to that half is a reading of the real thing:
`sage_patch/scripts/capture_wotr_battle.py` dumps every field these tests fabricate out of a
live battle, so a belief can be re-checked without another network session.
"""

from __future__ import annotations

import faulthandler
import struct
from dataclasses import dataclass, field

import pefile
from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
from unicorn.x86_const import (
    UC_X86_REG_EAX,
    UC_X86_REG_EBP,
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_EFLAGS,
    UC_X86_REG_EIP,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)

from sage_patch import addresses as ad

__all__ = ["Emulator", "Seat", "World", "build_world"]

#: Where the synthetic objects live. Far above the image, so a stray read of a real address faults
#: instead of quietly finding a structure.
HEAP_BASE = 0x20000000
HEAP_SIZE = 0x00100000
STACK_BASE = 0x30000000
STACK_SIZE = 0x00010000
#: The return address pushed for the routine under test. Mapped but never executable code, so
#: reaching it is how a run ends.
DONE = 0x40000000

_SF = 1 << 7
_OF = 1 << 11
_ZF = 1 << 6


@dataclass
class Seat:
    """One lobby slot, in the terms the patch cares about."""

    state: int = ad.GAME_SLOT_STATE_LOCAL_HUMAN
    player_template: int = 3
    living_world_id: int = 0
    team: int = 0
    start_pos: int = 0
    occupied: int = 1
    #: Filled in by :func:`build_world`.
    address: int = 0


@dataclass
class World:
    """The synthetic battle, and where everything landed."""

    seats: list[Seat]
    game_info: int
    game_logic: int
    living_world: int
    battle: int
    region: int
    players: dict[int, int] = field(default_factory=dict)


class _Bump:
    def __init__(self, base: int) -> None:
        self.next = base

    def alloc(self, size: int, align: int = 0x10) -> int:
        at = (self.next + align - 1) & ~(align - 1)
        self.next = at + size
        return at


def build_world(
    seats: list[Seat],
    *,
    fighting: tuple[int, ...] = (),
    living_world_type: int = ad.GAME_LOGIC_LIVING_WORLD_TYPE_MP_BATTLE,
    current_region_id: int = 79,
    region_id: int = 79,
    region_owner: int = -1,
) -> tuple[World, dict[int, bytes]]:
    """Lay out the world, and return it with the bytes to map.

    ``fighting`` names the living-world player ids on the battle's two sides - one per side, which
    is the shape every War of the Ring battle observed so far has had.
    """
    heap = _Bump(HEAP_BASE)
    mem: dict[int, bytes] = {}

    def put(at: int, blob: bytes) -> None:
        mem[at] = blob

    def u32(v: int) -> bytes:
        return struct.pack("<I", v & 0xFFFFFFFF)

    game_logic = heap.alloc(0x200)
    gl = bytearray(0x200)
    struct.pack_into("<i", gl, ad.GAME_LOGIC_LIVING_WORLD_TYPE, living_world_type)
    put(game_logic, bytes(gl))

    living_world = heap.alloc(0x100)
    store = heap.alloc(0x40)
    region = heap.alloc(0x200)
    rg = bytearray(0x200)
    struct.pack_into("<i", rg, ad.LIVING_WORLD_REGION_ID, region_id)
    struct.pack_into("<i", rg, ad.LIVING_WORLD_REGION_OWNER, region_owner)
    put(region, bytes(rg))

    # One LivingWorldPlayer per distinct id the seats name.
    players: dict[int, int] = {}
    for seat in seats:
        if seat.living_world_id < 0 or seat.living_world_id in players:
            continue
        at = heap.alloc(0x500)
        blob = bytearray(0x500)
        struct.pack_into("<i", blob, ad.LIVING_WORLD_PLAYER_ID, seat.living_world_id)
        # control type 0 == human; anything else is an AI as far as the patch is concerned
        struct.pack_into("<i", blob, 0x44, 0 if seat.state == ad.GAME_SLOT_STATE_LOCAL_HUMAN else 1)
        put(at, bytes(blob))
        players[seat.living_world_id] = at

    player_vec = heap.alloc(max(4 * len(players), 4))
    put(player_vec, b"".join(u32(players[k]) for k in sorted(players)))

    # The battle: one side record per fighter. Each side carries a **decoy member first** and the
    # real fighter second, so a wrong member stride lands on the decoy and a wrong side stride
    # lands on the wrong side - both of which a single-member fixture would silently absorb.
    decoy = heap.alloc(0x500)
    decoy_blob = bytearray(0x500)
    struct.pack_into("<i", decoy_blob, ad.LIVING_WORLD_PLAYER_ID, 0x7EEE)
    put(decoy, bytes(decoy_blob))

    per_side = 2
    sides = heap.alloc(max(ad.LIVING_WORLD_BATTLE_SIDE_STRIDE * len(fighting), 4))
    side_blob = bytearray(ad.LIVING_WORLD_BATTLE_SIDE_STRIDE * max(len(fighting), 1))
    for i, pid in enumerate(fighting):
        members = heap.alloc(ad.LIVING_WORLD_BATTLE_MEMBER_STRIDE * per_side)
        member_blob = bytearray(ad.LIVING_WORLD_BATTLE_MEMBER_STRIDE * per_side)
        struct.pack_into("<I", member_blob, 0, decoy)
        struct.pack_into("<I", member_blob, ad.LIVING_WORLD_BATTLE_MEMBER_STRIDE, players[pid])
        put(members, bytes(member_blob))
        base = i * ad.LIVING_WORLD_BATTLE_SIDE_STRIDE
        struct.pack_into("<I", side_blob, base + ad.LIVING_WORLD_BATTLE_MEMBERS_BEGIN, members)
        struct.pack_into(
            "<I",
            side_blob,
            base + ad.LIVING_WORLD_BATTLE_MEMBERS_END,
            members + ad.LIVING_WORLD_BATTLE_MEMBER_STRIDE * per_side,
        )
    put(sides, bytes(side_blob))

    battle = heap.alloc(0x40)
    bt = bytearray(0x40)
    struct.pack_into("<I", bt, ad.LIVING_WORLD_BATTLE_SIDES_BEGIN, sides)
    struct.pack_into(
        "<I",
        bt,
        ad.LIVING_WORLD_BATTLE_SIDES_END,
        sides + ad.LIVING_WORLD_BATTLE_SIDE_STRIDE * len(fighting),
    )
    struct.pack_into("<I", bt, ad.LIVING_WORLD_BATTLE_REGION, region)
    put(battle, bytes(bt))

    battle_vec = heap.alloc(4)
    put(battle_vec, u32(battle))
    st = bytearray(0x40)
    struct.pack_into("<I", st, ad.LIVING_WORLD_STORE_BATTLES_BEGIN, battle_vec)
    struct.pack_into("<I", st, ad.LIVING_WORLD_STORE_BATTLES_END, battle_vec + 4)
    put(store, bytes(st))

    lw = bytearray(0x100)
    struct.pack_into("<I", lw, ad.LIVING_WORLD_PLAYERS_BEGIN, player_vec)
    struct.pack_into("<I", lw, ad.LIVING_WORLD_PLAYERS_END, player_vec + 4 * len(players))
    struct.pack_into("<I", lw, ad.LIVING_WORLD_LOGIC_BATTLE_STORE, store)
    struct.pack_into("<i", lw, ad.LIVING_WORLD_LOGIC_CURRENT_REGION_ID, current_region_id)
    put(living_world, bytes(lw))

    game_info = heap.alloc(0x200)
    gi = bytearray(0x200)
    for i, seat in enumerate(seats):
        at = heap.alloc(0x1C0)
        seat.address = at
        blob = bytearray(0x1C0)
        struct.pack_into("<i", blob, ad.GAME_SLOT_STATE, seat.state)
        struct.pack_into("<i", blob, ad.GAME_SLOT_START_POS, seat.start_pos)
        struct.pack_into("<i", blob, ad.GAME_SLOT_PLAYER_TEMPLATE, seat.player_template)
        struct.pack_into("<i", blob, ad.GAME_SLOT_TEAM, seat.team)
        struct.pack_into("<i", blob, ad.GAME_SLOT_LIVING_WORLD_PLAYER_ID, seat.living_world_id)
        blob[ad.GAME_SLOT_IS_OCCUPIED] = seat.occupied
        put(at, bytes(blob))
        struct.pack_into("<I", gi, ad.GAME_INFO_SLOT_ARRAY + i * 4, at)
    put(game_info, bytes(gi))

    world = World(
        seats=seats,
        game_info=game_info,
        game_logic=game_logic,
        living_world=living_world,
        battle=battle,
        region=region,
        players=players,
    )
    return world, mem


class Emulator:
    """The patched image plus a synthetic world, in Unicorn, one routine at a time."""

    def __init__(self, image: bytes, world: World, mem: dict[int, bytes]) -> None:
        self.world = world
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        pe = pefile.PE(data=bytes(image), fast_load=True)
        base = pe.OPTIONAL_HEADER.ImageBase
        span = 0
        for section in pe.sections:
            end = section.VirtualAddress + max(section.Misc_VirtualSize, len(section.get_data()))
            span = max(span, end)

        # `mem_map` raises and catches an SEH access violation inside Unicorn 2.1.4 on Windows -
        # every map still succeeds, but Python's fault handler prints a stack for each one, which
        # would bury the test output. Silenced around the mapping only.
        was_enabled = faulthandler.is_enabled()
        faulthandler.disable()
        try:
            self.uc.mem_map(base, (span + 0xFFF) & ~0xFFF)
            self.uc.mem_map(HEAP_BASE, HEAP_SIZE)
            self.uc.mem_map(STACK_BASE, STACK_SIZE)
            self.uc.mem_map(DONE, 0x1000)
        finally:
            if was_enabled:
                faulthandler.enable()

        for section in pe.sections:
            self.uc.mem_write(base + section.VirtualAddress, section.get_data())
        for at, blob in mem.items():
            self.uc.mem_write(at, blob)

        # The globals the cave dereferences, pointed at the synthetic objects.
        for global_va, value in (
            (ad.THE_GAME_LOGIC, world.game_logic),
            (ad.THE_GAME_INFO, world.game_info),
            (ad.THE_LIVING_WORLD_LOGIC, world.living_world),
        ):
            self.uc.mem_write(global_va, struct.pack("<I", value))

        #: Every `AsciiString::operator=` the run made, as ``(this, source)``.
        self.assignments: list[tuple[int, int]] = []
        self._install_stubs()

    def _install_stubs(self) -> None:
        """The four engine routines the cave calls, answered in Python.

        Emulating them rather than executing them keeps the run to the bytes under test: the real
        ones reach the allocator, the name-key table and the `Dict` machinery, none of which this
        fixture has.
        """
        uc = self.uc

        def ret(n: int, value: int | None = None) -> None:
            esp = uc.reg_read(UC_X86_REG_ESP)
            uc.reg_write(UC_X86_REG_EIP, struct.unpack("<I", uc.mem_read(esp, 4))[0])
            uc.reg_write(UC_X86_REG_ESP, esp + 4 + n)
            if value is not None:
                uc.reg_write(UC_X86_REG_EAX, value)

        def arg(i: int) -> int:
            esp = uc.reg_read(UC_X86_REG_ESP)
            return struct.unpack("<I", uc.mem_read(esp + 4 + i * 4, 4))[0]

        def read32(at: int) -> int:
            return struct.unpack("<I", uc.mem_read(at, 4))[0]

        def get_slot(_uc, _address, _size, _user) -> None:
            index = arg(0)
            this = uc.reg_read(UC_X86_REG_ECX)
            found = 0
            if 0 <= index < ad.GAME_INFO_SLOT_COUNT:
                found = read32(this + ad.GAME_INFO_SLOT_ARRAY + index * 4)
            ret(4, found)

        def find_player(_uc, _address, _size, _user) -> None:
            wanted = arg(0)
            this = uc.reg_read(UC_X86_REG_ECX)
            found = 0
            if wanted != 0xFFFFFFFF:
                begin = read32(this + ad.LIVING_WORLD_PLAYERS_BEGIN)
                end = read32(this + ad.LIVING_WORLD_PLAYERS_END)
                for at in range(begin, end, 4):
                    candidate = read32(at)
                    if candidate and read32(candidate + ad.LIVING_WORLD_PLAYER_ID) == wanted:
                        found = candidate
                        break
            ret(8, found)

        def current_region(_uc, _address, _size, _user) -> None:
            ret(0, self.world.region)

        def assign(_uc, _address, _size, _user) -> None:
            self.assignments.append((uc.reg_read(UC_X86_REG_ECX), arg(0)))
            ret(4)

        for va, handler in (
            (ad.GAME_INFO_GET_SLOT, get_slot),
            (ad.LIVING_WORLD_FIND_PLAYER_BY_ID, find_player),
            (ad.LIVING_WORLD_CURRENT_REGION, current_region),
            (0x004050E6, assign),
        ):
            uc.hook_add(1 << 2, handler, begin=va, end=va)  # UC_HOOK_CODE

    def call(self, entry: int, *, esi: int = 0, eax: int = 0, ebx: int = 0) -> int:
        """Run one routine to its `ret`, and return the flags it left."""
        uc = self.uc
        frame = STACK_BASE + STACK_SIZE // 2
        uc.reg_write(UC_X86_REG_EBP, frame)
        uc.reg_write(UC_X86_REG_ESP, frame - 0x80)
        esp = uc.reg_read(UC_X86_REG_ESP) - 4
        uc.mem_write(esp, struct.pack("<I", DONE))
        uc.reg_write(UC_X86_REG_ESP, esp)
        uc.reg_write(UC_X86_REG_ESI, esi)
        uc.reg_write(UC_X86_REG_EAX, eax)
        uc.reg_write(UC_X86_REG_EBX, ebx)
        uc.reg_write(UC_X86_REG_EFLAGS, 2)
        uc.emu_start(entry, DONE)
        return uc.reg_read(UC_X86_REG_EFLAGS)

    def occupied(self, seat: Seat) -> int:
        return self.uc.mem_read(seat.address + ad.GAME_SLOT_IS_OCCUPIED, 1)[0]

    def eax(self) -> int:
        return self.uc.reg_read(UC_X86_REG_EAX)

    def top_of_stack(self) -> int:
        """The dword the run left at `esp`.

        A hook that displaces a `push` has to reproduce it *under* its own return address, so the
        only way to see that it did is to look at the stack the routine handed back rather than at
        a register."""
        esp = self.uc.reg_read(UC_X86_REG_ESP)
        return struct.unpack("<I", self.uc.mem_read(esp, 4))[0]

    @staticmethod
    def less_than(flags: int) -> bool:
        """What a `jl` would do with these flags - the branch both naming hooks feed."""
        return bool(flags & _SF) != bool(flags & _OF)
