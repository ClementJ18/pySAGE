"""War of the Ring co-op: play the battles the engine auto-resolves, with the rest watching.

Targets the ROTWK SAGE-engine `game.dat` build ``2.01.2614.37001``. Every address here is derived
in ``../docs/living-campaign/mp-battle-participation.md``.

**The gap.** In multiplayer War of the Ring a battle is fought in real time only when the number of
armies in it is at least the number of humans in the session. With three or more people most
battles fall short of that and are auto-resolved, and the players who *were* in the battle never
get the choice. The rule is written down **twice**, from the same two counts - the battle's
participants and the session's active human living-world players:

- `LivingWorldLogic::onSetConflictResolutionMethod` strips the real-time bit out of the vote mask
  and forces the auto-resolve one when participants are fewer (`0x006BEBE5`, `>=`);
- `LivingWorldBattle::getAllowedResolutions` leaves the real-time bit out of the mask the battle
  prompt shifts into its buttons unless the two are equal (`0x007F67DB`, `==`), which is what
  greys the Real Time button before the vote is ever cast.

Both have to go, and the client one goes first in play: a greyed button means the logic gate never
runs at all.

**Why the gate is there.** Not networking - the vote travels through `TheMessageStream`, so every
peer already runs the same handler and enters the same battle. The problem is seating.
`GameLogic::buildSidesFromGameInfo` names each lobby slot's side by asking one question, *do you
own this region*: the owner gets `Player_1` and everybody else `Player_<slot index + 2>`. In a
three-human game the third player is named `Player_4` or `Player_5`, a side no War of the Ring map
declares, so nothing marks a side local for that peer and `PlayerList::newGame` falls through to a
loop that hands the client **the first player that is not `m_players[0]`** - somebody else's army.

**What this does.** Clears both gates, and gives the peers they let in somewhere to sit.

First it has to get the seat looked at. Both of `buildSidesFromGameInfo`'s loops skip a slot whose
`GameSlot::isOccupied` is false, and the engine leaves `m_isOccupied` clear on a seat that is not
in this battle - so a pre-pass at the top of the function marks those seats occupied, which is
what makes every hook below reachable for them.

Then: a human slot whose `LivingWorldPlayer` is not on any side of the battle is named
**`ReplayObserver`** and
built with `FactionObserver`, so it merges into the one side every game carries -
`GameLogic::startNewGame` adds it unconditionally at `0x00626E1F`. The local slot's record is the
one that carries `multiplayerIsLocal`, so `PlayerList::newGame` seats the client there and
`Player::initFromSide` copies the observer flag off that template into `Player+0x35A`/`+0x754`,
which is what `observer-switch` and `observer-command-range` already build on.

**Not `Observer_%d`.** That is the arm the engine's own lobby observers take, and it was the first
thing this patch tried. Measured live on 2026-09-06 it does not work for a battle: no War of the
Ring map declares an `Observer_N` side, a slot record only fills a side that already exists, and
the peer ended up with no side, no `multiplayerIsLocal` anywhere, and `newGame` falling through to
seat it on `PlyrCivilian` — watching the map through the neutral player's eyes.

A fourth hook numbers the seats that *are* fighting. Stock numbering is by slot index, so an
attacker sitting in slot 1 is named `Player_3` whether or not anybody else is in the battle; this
counts participants instead, so the defender keeps `Player_1` and the attackers take `Player_2`
upward in slot order.

Two more give the seat somewhere to look from. `startNewGame` hands the `ReplayObserver` player the
whole map, which is right for a replay and wrong for a peer who is in the session and has allies to
watch through, so that reveal is skipped whenever the pre-pass seated anybody. And the opening
camera is a `Player_%d_Start` waypoint built from the seat's own start position - which, on a seat
the engine gave no place on the map, names a waypoint no two-army battle map declares and drops the
camera in the map's corner. The observer borrows a participant's instead: an ally's where the lobby
team says which side it is on, otherwise the first participant's in slot order.

**What it does not do.** It does not change the auto-resolve path, the post-battle harvest or hero
permadeath, and it adds no network message: every peer computes the same vote mask from the same
replicated state and every peer already transitions to the battle map. It also does not touch the
lobby's own observer slots, which reach the same path on their own.

**No INI, `.str` or `.apt` change.** The sides, the faction and the observer UI are all engine-side
and already shipped.

**Unverified in play**, and the doc names the three readings that would change it if wrong: the
identification of the store the current battle is found in, whether stock numbering really is slot
ordered, and whether the observer seat survives a full War of the Ring turn. Expect to need
`desync-detection` on the first co-op battle.

**Composition.** Order-independent. The cave is allocated with
:func:`~..utils.allocate_section` past every existing section and :meth:`verify` finds it by name;
the nine sites rewritten are in `LivingWorldLogic::onSetConflictResolutionMethod`,
`LivingWorldBattle::getAllowedResolutions` and `GameLogic::buildSidesFromGameInfo`, none of which
any other bundled patch edits or reads. See the composition contract on
:class:`~..patcher.Patch`.
"""

from __future__ import annotations

import struct

from ..addresses import (
    GAME_INFO_GET_SLOT,
    GAME_INFO_SLOT_COUNT,
    GAME_LOGIC_LIVING_WORLD_TYPE,
    GAME_LOGIC_LIVING_WORLD_TYPE_MP_BATTLE,
    GAME_SLOT_IS_OCCUPIED,
    GAME_SLOT_LIVING_WORLD_PLAYER_ID,
    GAME_SLOT_MAP_PLAYER,
    GAME_SLOT_PLAYER_TEMPLATE,
    GAME_SLOT_START_POS,
    GAME_SLOT_STATE,
    GAME_SLOT_STATE_LOCAL_HUMAN,
    GAME_SLOT_TEAM,
    LIVING_WORLD_BATTLE_MEMBER_STRIDE,
    LIVING_WORLD_BATTLE_MEMBERS_BEGIN,
    LIVING_WORLD_BATTLE_MEMBERS_END,
    LIVING_WORLD_BATTLE_REGION,
    LIVING_WORLD_BATTLE_SIDE_STRIDE,
    LIVING_WORLD_BATTLE_SIDES_BEGIN,
    LIVING_WORLD_BATTLE_SIDES_END,
    LIVING_WORLD_CURRENT_REGION,
    LIVING_WORLD_FIND_PLAYER_BY_ID,
    LIVING_WORLD_LOGIC_BATTLE_STORE,
    LIVING_WORLD_LOGIC_CURRENT_REGION_ID,
    LIVING_WORLD_PLAYER_ID,
    LIVING_WORLD_REGION_ID,
    LIVING_WORLD_REGION_OWNER,
    LIVING_WORLD_STORE_BATTLES_BEGIN,
    LIVING_WORLD_STORE_BATTLES_END,
    THE_GAME_INFO,
    THE_GAME_LOGIC,
    THE_LIVING_WORLD_LOGIC,
)
from ..asm import JAE, JE, JGE, JL, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

__all__ = [
    "ANCHORS",
    "ASCII_STRING_ASSIGN",
    "ASSIGN_NAME_BYTES",
    "ASSIGN_NAME_VA",
    "CODE_OFFSET",
    "FACTION_TEST_BYTES",
    "FACTION_TEST_VA",
    "NO_CURRENT_REGION",
    "NUMBER_BYTES",
    "NUMBER_VA",
    "OBSERVER_SIDE_NAME",
    "PREPARE_BYTES",
    "PREPARE_VA",
    "QUORUM_BRANCH_BYTES",
    "QUORUM_BRANCH_PATCHED",
    "QUORUM_BRANCH_VA",
    "RESOLUTION_ALLOW_RTS_BYTES",
    "RESOLUTION_ALLOW_RTS_VA",
    "RESOLUTION_EQUAL_BRANCH_BYTES",
    "RESOLUTION_EQUAL_BRANCH_VA",
    "RESOLUTION_MASK_BYTES",
    "RESOLUTION_MASK_PATCHED",
    "RESOLUTION_MASK_VA",
    "REVEAL_CALL_BYTES",
    "REVEAL_CALL_VA",
    "SEATED_OFFSET",
    "SECTION_NAME",
    "SHROUD_REVEAL_ALL",
    "SLOT_KIND_TEST_BYTES",
    "SLOT_KIND_TEST_VA",
    "START_POSITION_BYTES",
    "START_POSITION_VA",
    "WotrBattleObserversPatch",
    "build_cave",
]

# The top of `GameLogic::buildSidesFromGameInfo`, before either loop: `mov [ebp-0x20], eax` /
# `mov [ebp-0x18], ebx`, the `GameInfo` it just proved non-null and the loop counter it is about
# to zero. The pre-pass goes here because **both loops skip a slot whose `GameSlot::isOccupied`
# is false**, and a seat that is not in the battle has `m_isOccupied` clear - so without this the
# other hooks are never reached for it at all.
PREPARE_VA = 0x00627C41
PREPARE_BYTES = bytes.fromhex("8945e0895de8")

SECTION_NAME = ".wotrobs"
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. The cave holds the routines
# and a handful of scratch dwords they write.
SECTION_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000


# The gate, in `LivingWorldLogic::onSetConflictResolutionMethod`. `jge` skips the downgrade when
# the battle has enough participants; `jmp` skips it always. Two bytes, no cave.
QUORUM_BRANCH_VA = 0x006BEBE5
QUORUM_BRANCH_BYTES = bytes.fromhex("7d0b")
QUORUM_BRANCH_PATCHED = bytes.fromhex("eb0b")

# The **client's** copy of the same rule, in `LivingWorldBattle::getAllowedResolutions`
# (`0x007F662B`), whose result the battle prompt shifts into the enabled state of its three
# buttons - bit 1 AutoResolve, bit 2 Retreat, bit 3 RealTime:
#
#     007f67cb  call 0x006B5E3E            ; active human living-world players
#     007f67d4  call 0x007F5ECF            ; this battle's participants
#     007f67d9  cmp  eax, esi
#     007f67db  je   0x007F67BD            ; equal -> mask |= 8, the RealTime button lights
#     007f67dd  or   [ebp-8], 2            ; otherwise -> AutoResolve only, RealTime greyed
#
# Stricter than the logic gate, which asks `>=` rather than `==`, and reached first: without this
# the player can never vote for the battle the logic gate would now let them fight. Widening the
# constant to `2 | 8` offers both rather than replacing one with the other, which leaves the
# `AutoResolveType` lobby rule above it (`GameInfo+0x7C`, `1` = auto-resolve only) still able to
# grey the button on purpose.
RESOLUTION_MASK_VA = 0x007F67DD
RESOLUTION_MASK_BYTES = bytes.fromhex("834df802")
RESOLUTION_MASK_PATCHED = bytes.fromhex("834df80a")

# The `je` immediately above it, and the `or [ebp-8], 8` it lands on. Asserted, never written: they
# are what says the byte being widened is the arm that denies real time rather than some other
# `or`, and that bit 3 is the bit the arm above sets.
RESOLUTION_EQUAL_BRANCH_VA = 0x007F67D9
RESOLUTION_EQUAL_BRANCH_BYTES = bytes.fromhex("3bc674e0")
RESOLUTION_ALLOW_RTS_VA = 0x007F67BD
RESOLUTION_ALLOW_RTS_BYTES = bytes.fromhex("834df808")

#: What `LIVING_WORLD_LOGIC_CURRENT_REGION_ID` holds when no battle is being entered. Read live on
#: the strategic map of a three-player session, 2026-09-06, where it is the **only** thing keeping
#: the seating hooks inert: `GAME_LOGIC_LIVING_WORLD_TYPE` is 1 there too, so it does not by itself
#: mean "in a battle". Tested explicitly rather than left to the region lookup failing, because
#: whether the field is reset on the way back out of a battle has not been observed.
NO_CURRENT_REGION = -1


# `GameLogic::buildSidesFromGameInfo`, first loop: `cmp [esi+0x18], ebx` / `mov [ebp-4], ebx`,
# feeding the `jl` that picks the `Observer_%d` name. `ebx` is zero throughout the function, so the
# cave reproduces the comparison verbatim and only changes what it compares in the observer case.
SLOT_KIND_TEST_VA = 0x00627C6E
SLOT_KIND_TEST_BYTES = bytes.fromhex("395e18895dfc")

# The `jl` those flags feed. Asserted, never written: a build that shaped the branch differently
# would send the cave's forced-negative result somewhere else entirely.
SLOT_KIND_BRANCH_VA = 0x00627C74
SLOT_KIND_BRANCH_BYTES = bytes.fromhex("7c5f")

# The non-owner's side number: `mov eax, [ebp-0x18]` / `add eax, 2`, the slot index plus two.
# Reached only by the `jne` at `0x00627CB0`, which targets the first byte of the detour.
NUMBER_VA = 0x00627CC1
NUMBER_BYTES = bytes.fromhex("8b45e883c002")

# `GameLogic::buildSidesFromGameInfo`, second loop: `mov eax, [esi+0x18]` / `test eax, eax`,
# feeding the `jl` that picks `FactionObserver` over an indexed `PlayerTemplate`.
FACTION_TEST_VA = 0x00627E20
FACTION_TEST_BYTES = bytes.fromhex("8b461885c0")
FACTION_BRANCH_VA = 0x00627E25
FACTION_BRANCH_BYTES = bytes.fromhex("7c0e")

# Where the formatted side name is copied into `GameSlot::m_mapPlayer`: `lea eax, [ebp-0x1c]` /
# `lea ecx, [esi+0x34]`, the point all three naming arms converge on. The seat's name is replaced
# with the literal `ReplayObserver` here rather than at the arm that formats it, because
# `Observer_%d` names a side **no War of the Ring map declares** - measured live 2026-09-06, where
# it left the peer with no side, no `multiplayerIsLocal` anywhere, and `PlayerList::newGame`
# falling through to seat it on `PlyrCivilian`. `ReplayObserver` is the one side that always
# exists: `0x00626E1F` adds it to every game unconditionally.
ASSIGN_NAME_VA = 0x00627CEB
ASSIGN_NAME_BYTES = bytes.fromhex("8d45e48d4e34")

#: `AsciiString::operator=(const char *)` - thiscall, one stack argument, `ret 4`. The same helper
#: the `Player_1` arm just above the hook uses (`0x00627CB2`).
ASCII_STRING_ASSIGN = 0x004050E6

#: `ShroudManager::revealMapForPlayer` - thiscall on `TheShroudManager` (`0x00DE4358`), one stack
#: argument (the player index at `Player+0x54`), `ret 4`. A two-instruction thunk onto `0x00B4F5D0`,
#: which walks every shroud cell for that player.
SHROUD_REVEAL_ALL = 0x00B4D940

# `GameLogic::startNewGame`, just before the per-slot loop: the whole map handed to the player
# named `ReplayObserver` (`0x00BFD4A8`, resolved through the name key at `0x0062FE23`). Right for a
# replay, where the observer is the audience and there is nobody to watch through; wrong for a War
# of the Ring battle, where the peer is seated on that same side but is a player in the session and
# should see what its allies see. Retargeted rather than removed, because the pre-pass is the only
# thing that knows which of the two this game is.
REVEAL_CALL_VA = 0x0062FE3D
REVEAL_CALL_BYTES = bytes.fromhex("e8feda5100")

# The seat's start position, on its way into `Player_%d_Start` (`0x00BFDA18`) at `0x006311A0` -
# `mov eax, [esi+0x10]` / `inc eax` / `push eax`, where `esi` is the local `GameSlot`. That waypoint
# is where the camera opens, and a seat the engine gave no place on the map carries a start position
# no two-army battle map declares - which drops the camera in the map's corner. The hook lends the
# observer a participant's.
START_POSITION_VA = 0x006311D3
START_POSITION_BYTES = bytes.fromhex("8b46104050")

#: The side every game carries, and the seat a peer with no side of its own belongs in.
OBSERVER_SIDE_NAME = b"ReplayObserver"

# The routines the cave calls, fingerprinted by their prologues so a build where one of them moved
# fails here instead of calling something else with a living-world player id.
ANCHORS: tuple[tuple[int, bytes, str], ...] = (
    (SLOT_KIND_BRANCH_VA, SLOT_KIND_BRANCH_BYTES, "the `jl` into the Observer_%d name"),
    (FACTION_BRANCH_VA, FACTION_BRANCH_BYTES, "the `jl` into FactionObserver"),
    (
        RESOLUTION_EQUAL_BRANCH_VA,
        RESOLUTION_EQUAL_BRANCH_BYTES,
        "the participant-count comparison the prompt's RealTime button hangs off",
    ),
    (
        RESOLUTION_ALLOW_RTS_VA,
        RESOLUTION_ALLOW_RTS_BYTES,
        "the arm that sets the RealTime bit",
    ),
    (
        LIVING_WORLD_FIND_PLAYER_BY_ID,
        bytes.fromhex("568b74240833c083feff7439"),
        "LivingWorldLogic::findPlayerById",
    ),
    (
        LIVING_WORLD_CURRENT_REGION,
        bytes.fromhex("ffb1b80000008b89b0000000e8acb3f5ffc3"),
        "LivingWorldLogic::getCurrentRegion",
    ),
    (
        GAME_INFO_GET_SLOT,
        bytes.fromhex("8d411885c074138b44240485c07c0b83f808"),
        "GameInfo::getSlot",
    ),
    (
        ASCII_STRING_ASSIGN,
        bytes.fromhex("568b74240885f6578bf97409"),
        "AsciiString::operator=(const char *)",
    ),
    (
        SHROUD_REVEAL_ALL,
        bytes.fromhex("8b4910e9881c0000"),
        "ShroudManager::revealMapForPlayer",
    ),
)


# The cave's scratch dwords, at the head of the section so `verify` can read the code back at a
# fixed offset. Only `FLAG`, `RESULT`, `SEATED` and `SP_RESULT` cross a `popad`; the rest are loop
# state that never outlives the routine that writes it.
DATA_SIZE = 0x40
NAME_OFFSET = 0x40
#: Where the code starts, past the scratch dwords and the literal they are followed by.
CODE_OFFSET = 0x50
FLAG_OFFSET = 0x00
RESULT_OFFSET = 0x04
SLOT_INDEX_OFFSET = 0x08
BATTLE_OFFSET = 0x0C
OWNER_OFFSET = 0x10
INFO_OFFSET = 0x14
NUMBER_OFFSET = 0x18
PREP_INDEX_OFFSET = 0x1C

#: Whether the pre-pass seated anybody as an observer, and so the one thing that says this game is
#: a War of the Ring battle with somebody watching rather than a replay or an ordinary skirmish.
#: The two hooks that run after `buildSidesFromGameInfo` read it and do nothing at all when it is
#: clear.
#:
#: The cave outlives a game, so it is cleared at the top of every pre-pass rather than left to the
#: next run to overwrite. That covers every game the pre-pass sees, which is every game with a
#: `TheGameInfo` - the `je` at `0x0062FB0A` - and so every replay and every lobby game. A game with
#: no `GameInfo` at all (a campaign mission) skips the pre-pass and inherits the previous game's
#: answer; all that costs is the map-wide reveal for a `ReplayObserver` side no client is seated on.
SEATED_OFFSET = 0x20
SP_RESULT_OFFSET = 0x24
SP_INDEX_OFFSET = 0x28
SP_BEST_OFFSET = 0x2C
SP_ALLY_OFFSET = 0x30
SP_TEAM_OFFSET = 0x34

#: The frame slots the hooks read, in `buildSidesFromGameInfo`'s frame: the loop's slot index and
#: the flag byte the displaced `mov` clears.
FRAME_GAME_INFO = 0x20  # [ebp-0x20], the GameInfo both loops read the slots from
FRAME_SLOT_INDEX = 0x18  # [ebp-0x18]
FRAME_NAME_BUFFER = 0x1C  # [ebp-0x1c], the AsciiString the naming arms format into
FRAME_NAME_GUARD = 0x04  # [ebp-4]

#: What a `call` detour leaves in the byte it does not use, and what a `jmp` detour leaves in the
#: bytes nothing can reach.
_NOP = 0x90
_INT3 = 0xCC


def _imm(value: int) -> bytes:
    return struct.pack("<I", value)


def build_cave(section_va: int) -> tuple[bytes, dict[str, int]]:
    """The whole cave, and the virtual address of each of its entry points.

    The hooks share one predicate, so they are laid out as helpers first and entry points
    after; the caller needs the entry addresses to write the detours, and the only honest source
    for those is the layout that was actually emitted.
    """
    flag = section_va + FLAG_OFFSET
    result = section_va + RESULT_OFFSET
    slot_index = section_va + SLOT_INDEX_OFFSET
    battle = section_va + BATTLE_OFFSET
    owner = section_va + OWNER_OFFSET
    info = section_va + INFO_OFFSET
    number = section_va + NUMBER_OFFSET
    side_name = section_va + NAME_OFFSET
    prep_index = section_va + PREP_INDEX_OFFSET
    seated = section_va + SEATED_OFFSET
    sp_result = section_va + SP_RESULT_OFFSET
    sp_index = section_va + SP_INDEX_OFFSET
    sp_best = section_va + SP_BEST_OFFSET
    sp_ally = section_va + SP_ALLY_OFFSET
    sp_team = section_va + SP_TEAM_OFFSET

    a = Asm(section_va + CODE_OFFSET)

    # find_battle() -> eax, the battle being fought in the region the map is loading for, or NULL.
    # `enterRealtimeBattle` stashed that region's id on the logic before the load, and a battle
    # names its region, so the two meet here. Clobbers eax/ebx/ecx/edx/ebp; leaves esi/edi alone.
    a.label("find_battle")
    a.emit(b"\x8b\x0d", _imm(THE_LIVING_WORLD_LOGIC))  # mov  ecx, [TheLivingWorldLogic]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "fb_miss")
    a.emit(b"\x8b\x91", _imm(LIVING_WORLD_LOGIC_BATTLE_STORE))  # mov edx, [ecx+0xb0]
    a.emit(b"\x85\xd2")  # test edx, edx
    a.jcc(JE, "fb_miss")
    a.emit(b"\x8b\xa9", _imm(LIVING_WORLD_LOGIC_CURRENT_REGION_ID))  # mov ebp, [ecx+0xb8]
    a.emit(b"\x83\xfd", NO_CURRENT_REGION & 0xFF)  # cmp  ebp, -1
    a.jcc(JE, "fb_miss")  # no battle is being entered
    a.emit(b"\x8b\x5a", LIVING_WORLD_STORE_BATTLES_BEGIN)  # mov  ebx, [edx+0x14]
    a.emit(b"\x8b\x52", LIVING_WORLD_STORE_BATTLES_END)  # mov  edx, [edx+0x18]
    a.label("fb_loop")
    a.emit(b"\x3b\xda")  # cmp  ebx, edx
    a.jcc(JAE, "fb_miss")
    a.emit(b"\x8b\x03")  # mov  eax, [ebx]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "fb_next")
    a.emit(b"\x8b\x48", LIVING_WORLD_BATTLE_REGION)  # mov  ecx, [eax+0x24]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "fb_next")
    a.emit(b"\x39\xa9", _imm(LIVING_WORLD_REGION_ID))  # cmp  [ecx+0x14c], ebp
    a.jcc(JE, "fb_done")  # eax is the battle
    a.label("fb_next")
    a.emit(b"\x83\xc3\x04")  # add  ebx, 4
    a.jmp("fb_loop")
    a.label("fb_miss")
    a.emit(b"\x33\xc0")  # xor  eax, eax
    a.label("fb_done")
    a.emit(0xC3)  # ret

    # battle_has_player(edi = battle, eax = LivingWorldPlayer*) -> al. Two nested vectors, striding
    # exactly as `0x007F6403` and `0x007F5D2B` do. Clobbers eax/ebx/ecx/edx/ebp.
    a.label("has_player")
    a.emit(b"\x8b\x57", LIVING_WORLD_BATTLE_SIDES_BEGIN)  # mov  edx, [edi+0x18]
    a.emit(b"\x8b\x4f", LIVING_WORLD_BATTLE_SIDES_END)  # mov  ecx, [edi+0x1c]
    a.label("hp_side")
    a.emit(b"\x3b\xd1")  # cmp  edx, ecx
    a.jcc(JAE, "hp_absent")
    a.emit(b"\x8b\x5a", LIVING_WORLD_BATTLE_MEMBERS_BEGIN)  # mov  ebx, [edx+4]
    a.emit(b"\x8b\x6a", LIVING_WORLD_BATTLE_MEMBERS_END)  # mov  ebp, [edx+8]
    a.label("hp_member")
    a.emit(b"\x3b\xdd")  # cmp  ebx, ebp
    a.jcc(JAE, "hp_next")
    a.emit(b"\x39\x03")  # cmp  [ebx], eax
    a.jcc(JE, "hp_found")
    a.emit(b"\x83\xc3", LIVING_WORLD_BATTLE_MEMBER_STRIDE)  # add  ebx, 0x30
    a.jmp("hp_member")
    a.label("hp_next")
    a.emit(b"\x83\xc2", LIVING_WORLD_BATTLE_SIDE_STRIDE)  # add  edx, 0x1c
    a.jmp("hp_side")
    a.label("hp_found")
    a.emit(b"\xb0\x01")  # mov  al, 1
    a.emit(0xC3)  # ret
    a.label("hp_absent")
    a.emit(b"\x33\xc0")  # xor  eax, eax
    a.emit(0xC3)  # ret

    # needs_observer(esi = GameSlot*) -> al. The one predicate all three seating hooks ask. Every
    # way of not knowing the answer - not a multiplayer battle, not a human seat, no battle, no
    # living-world player - answers "no" and leaves the stock path exactly as it was.
    a.label("needs_observer")
    a.emit(b"\x8b\x0d", _imm(THE_GAME_LOGIC))  # mov  ecx, [TheGameLogic]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "no_observer")
    a.emit(b"\x83\xb9", _imm(GAME_LOGIC_LIVING_WORLD_TYPE))  # cmp  [ecx+0x114],
    a.emit(GAME_LOGIC_LIVING_WORLD_TYPE_MP_BATTLE)  #      1
    a.jcc(JNE, "no_observer")
    a.emit(b"\x85\xf6")  # test esi, esi
    a.jcc(JE, "no_observer")
    a.emit(b"\x83\x7e", GAME_SLOT_STATE, GAME_SLOT_STATE_LOCAL_HUMAN)  # cmp [esi+4], 6
    a.jcc(JNE, "no_observer")
    a.emit(b"\x83\x7e", GAME_SLOT_PLAYER_TEMPLATE, 0x00)  # cmp  [esi+0x18], 0
    a.jcc(JL, "no_observer")  # already an observer seat
    a.call("find_battle")
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "no_observer")
    a.emit(b"\x8b\xf8")  # mov  edi, eax
    a.emit(b"\x8b\x0d", _imm(THE_LIVING_WORLD_LOGIC))  # mov  ecx, [TheLivingWorldLogic]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "no_observer")
    a.emit(b"\x6a\x00")  # push 0                  ; no out-index
    a.emit(b"\xff\x76", GAME_SLOT_LIVING_WORLD_PLAYER_ID)  # push [esi+0x4c]
    a.call_absolute(LIVING_WORLD_FIND_PLAYER_BY_ID)  # call findPlayerById  ; ret 8
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "no_observer")
    a.call("has_player")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JNE, "no_observer")  # fighting: leave the seat alone
    a.emit(b"\xb0\x01")  # mov  al, 1
    a.emit(0xC3)  # ret
    a.label("no_observer")
    a.emit(b"\x33\xc0")  # xor  eax, eax
    a.emit(0xC3)  # ret

    # is_participant(esi = GameSlot*) -> al. The other half of the same question, and not the
    # negation of it: `needs_observer` also answers "no" for an AI seat, an empty one and the
    # lobby's own observers, none of which have an army in the battle to borrow anything from.
    # Only a human seat whose living-world player is actually on one of the sides counts.
    a.label("is_participant")
    a.emit(b"\x85\xf6")  # test esi, esi
    a.jcc(JE, "not_participant")
    a.emit(b"\x83\x7e", GAME_SLOT_STATE, GAME_SLOT_STATE_LOCAL_HUMAN)  # cmp [esi+4], 6
    a.jcc(JNE, "not_participant")
    a.emit(b"\x83\x7e", GAME_SLOT_PLAYER_TEMPLATE, 0x00)  # cmp  [esi+0x18], 0
    a.jcc(JL, "not_participant")  # an observer seat fields no army
    a.call("find_battle")
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "not_participant")
    a.emit(b"\x8b\xf8")  # mov  edi, eax
    a.emit(b"\x8b\x0d", _imm(THE_LIVING_WORLD_LOGIC))  # mov  ecx, [TheLivingWorldLogic]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "not_participant")
    a.emit(b"\x6a\x00")  # push 0                  ; no out-index
    a.emit(b"\xff\x76", GAME_SLOT_LIVING_WORLD_PLAYER_ID)  # push [esi+0x4c]
    a.call_absolute(LIVING_WORLD_FIND_PLAYER_BY_ID)  # call findPlayerById  ; ret 8
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "not_participant")
    a.jmp("has_player")  # its `ret` is this one's
    a.label("not_participant")
    a.emit(b"\x33\xc0")  # xor  eax, eax
    a.emit(0xC3)  # ret

    # hook_name: the displaced `cmp`/`mov`, with the comparison forced negative for a seat that is
    # not in the battle so the caller's `jl` takes the `Observer_%d` arm. The `mov` goes first
    # because it sets no flags and the `cmp` must be the last thing before the `ret`.
    # hook_prepare: run before either loop, and the reason the rest of the cave is reachable at
    # all. `buildSidesFromGameInfo` skips a slot whose `isOccupied` is false, and the engine leaves
    # `m_isOccupied` clear on a seat that is not in this battle - so the seat is never named, never
    # built into a side, and the client lands on `PlyrCivilian`. Marking it occupied is what puts
    # it back in both loops; the other hooks then decide what it becomes.
    a.label("hook_prepare")
    a.emit(b"\x89\x45", 0x100 - FRAME_GAME_INFO)  # mov  [ebp-0x20], eax   (displaced)
    a.emit(b"\x89\x5d", 0x100 - FRAME_SLOT_INDEX)  # mov  [ebp-0x18], ebx   (displaced)
    a.emit(0x60)  # pushad
    a.emit(b"\x83\x25", _imm(prep_index), 0x00)  # and  dword [prep], 0
    a.emit(b"\x83\x25", _imm(seated), 0x00)  # and  dword [seated], 0
    a.label("prep_loop")
    a.emit(b"\x83\x3d", _imm(prep_index), GAME_INFO_SLOT_COUNT)  # cmp dword [prep], 8
    a.jcc(JAE, "prep_done")
    a.emit(b"\x8b\x0d", _imm(THE_GAME_INFO))  # mov  ecx, [TheGameInfo]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "prep_done")
    a.emit(b"\xff\x35", _imm(prep_index))  # push dword [prep]
    a.call_absolute(GAME_INFO_GET_SLOT)  # call getSlot          ; ret 4
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "prep_next")
    a.emit(b"\x8b\xf0")  # mov  esi, eax         ; the predicate reads esi
    a.call("needs_observer")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "prep_next")
    a.emit(b"\xc6\x86", _imm(GAME_SLOT_IS_OCCUPIED), 0x01)  # mov byte [esi+0x1ac], 1
    a.emit(b"\xc6\x05", _imm(seated), 0x01)  # mov  byte [seated], 1
    a.label("prep_next")
    a.emit(b"\xff\x05", _imm(prep_index))  # inc  dword [prep]
    a.jmp("prep_loop")
    a.label("prep_done")
    a.emit(0x61)  # popad
    a.emit(0xC3)  # ret

    a.label("hook_name")
    a.emit(b"\x89\x5d", 0x100 - FRAME_NAME_GUARD)  # mov  [ebp-4], ebx
    a.emit(0x60)  # pushad
    a.call("needs_observer")
    a.emit(b"\xa2", _imm(flag))  # mov  [flag], al
    a.emit(0x61)  # popad
    a.emit(b"\x80\x3d", _imm(flag), 0x00)  # cmp  byte [flag], 0
    a.jcc(JNE, "hook_name_observer")
    a.emit(b"\x39\x5e", GAME_SLOT_PLAYER_TEMPLATE)  # cmp  [esi+0x18], ebx
    a.emit(0xC3)  # ret
    a.label("hook_name_observer")
    a.emit(b"\xb8\xff\xff\xff\xff")  # mov  eax, -1
    a.emit(b"\x83\xf8\x00")  # cmp  eax, 0     ; SF set, OF clear
    a.emit(0xC3)  # ret

    # hook_faction: the same answer, shaped for `test eax, eax` and a `jl`. `eax` still has to
    # carry the template index on the way out, because the stock arm indexes the store with it.
    a.label("hook_faction")
    a.emit(0x60)  # pushad
    a.call("needs_observer")
    a.emit(b"\xa2", _imm(flag))  # mov  [flag], al
    a.emit(0x61)  # popad
    a.emit(b"\x80\x3d", _imm(flag), 0x00)  # cmp  byte [flag], 0
    a.jcc(JNE, "hook_faction_observer")
    a.emit(b"\x8b\x46", GAME_SLOT_PLAYER_TEMPLATE)  # mov  eax, [esi+0x18]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.emit(0xC3)  # ret
    a.label("hook_faction_observer")
    a.emit(b"\xb8\xff\xff\xff\xff")  # mov  eax, -1
    a.emit(b"\x85\xc0")  # test eax, eax
    a.emit(0xC3)  # ret

    # hook_assign: the seat's name, on its way into `GameSlot::m_mapPlayer`. `hook_name` has
    # already answered for this slot earlier in the same iteration, so the flag is current; when it
    # said observer, whatever the arms formatted is thrown away and the name becomes the one side
    # that is always there to receive it. `pushad` because the helper's register discipline is not
    # this patch's to assume, and the two displaced `lea`s have to come after it to survive.
    a.label("hook_assign")
    a.emit(b"\x80\x3d", _imm(flag), 0x00)  # cmp  byte [flag], 0
    a.jcc(JE, "hook_assign_stock")
    a.emit(0x60)  # pushad
    a.emit(0x68, _imm(side_name))  # push <"ReplayObserver">
    a.emit(b"\x8d\x4d", 0x100 - FRAME_NAME_BUFFER)  # lea  ecx, [ebp-0x1c]
    a.call_absolute(ASCII_STRING_ASSIGN)  # call AsciiString::operator= ; ret 4
    a.emit(0x61)  # popad
    a.label("hook_assign_stock")
    a.emit(b"\x8d\x45", 0x100 - FRAME_NAME_BUFFER)  # lea  eax, [ebp-0x1c]
    a.emit(b"\x8d\x4e", GAME_SLOT_MAP_PLAYER)  # lea  ecx, [esi+0x34]
    a.emit(0xC3)  # ret

    # hook_number -> eax, the `Player_%d` number for the seat being named. Counts the human seats
    # before this one that are in the battle and are not its defender, so the attackers come out
    # 2, 3, 4 in slot order instead of following the slot index. Any doubt falls back to the stock
    # `slot + 2`, which is written before anything else can go wrong.
    a.label("hook_number")
    a.emit(0x60)  # pushad
    a.emit(b"\x8b\x45", 0x100 - FRAME_SLOT_INDEX)  # mov  eax, [ebp-0x18]
    a.emit(b"\xa3", _imm(slot_index))  # mov  [slot_index], eax
    a.emit(b"\x83\xc0\x02")  # add  eax, 2
    a.emit(b"\xa3", _imm(result))  # mov  [result], eax
    a.emit(b"\x8b\x0d", _imm(THE_GAME_LOGIC))  # mov  ecx, [TheGameLogic]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "hn_out")
    a.emit(b"\x83\xb9", _imm(GAME_LOGIC_LIVING_WORLD_TYPE))  # cmp  [ecx+0x114],
    a.emit(GAME_LOGIC_LIVING_WORLD_TYPE_MP_BATTLE)  #      1
    a.jcc(JNE, "hn_out")
    a.call("find_battle")
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "hn_out")
    a.emit(b"\xa3", _imm(battle))  # mov  [battle], eax
    a.emit(b"\x8b\x0d", _imm(THE_LIVING_WORLD_LOGIC))  # mov  ecx, [TheLivingWorldLogic]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "hn_out")
    a.call_absolute(LIVING_WORLD_CURRENT_REGION)  # call getCurrentRegion
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "hn_out")
    a.emit(b"\x8b\x80", _imm(LIVING_WORLD_REGION_OWNER))  # mov  eax, [eax+0x15c]
    a.emit(b"\xa3", _imm(owner))  # mov  [owner], eax
    a.emit(b"\xa1", _imm(THE_GAME_INFO))  # mov  eax, [TheGameInfo]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "hn_out")
    a.emit(b"\xa3", _imm(info))  # mov  [info], eax
    a.emit(b"\xc7\x05", _imm(number), _imm(2))  # mov  dword [number], 2
    a.emit(b"\x33\xf6")  # xor  esi, esi
    a.label("hn_loop")
    a.emit(b"\x3b\x35", _imm(slot_index))  # cmp  esi, [slot_index]
    a.jcc(JAE, "hn_done")
    a.emit(b"\x8b\x0d", _imm(info))  # mov  ecx, [info]
    a.emit(0x56)  # push esi
    a.call_absolute(GAME_INFO_GET_SLOT)  # call getSlot         ; ret 4
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "hn_next")
    a.emit(b"\x83\x78", GAME_SLOT_STATE, GAME_SLOT_STATE_LOCAL_HUMAN)  # cmp [eax+4], 6
    a.jcc(JNE, "hn_next")
    a.emit(b"\x83\x78", GAME_SLOT_PLAYER_TEMPLATE, 0x00)  # cmp  [eax+0x18], 0
    a.jcc(JL, "hn_next")  # an observer seat takes no number
    a.emit(b"\x8b\x40", GAME_SLOT_LIVING_WORLD_PLAYER_ID)  # mov  eax, [eax+0x4c]
    a.emit(b"\x8b\x0d", _imm(THE_LIVING_WORLD_LOGIC))  # mov  ecx, [TheLivingWorldLogic]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "hn_next")
    a.emit(b"\x6a\x00")  # push 0
    a.emit(0x50)  # push eax
    a.call_absolute(LIVING_WORLD_FIND_PLAYER_BY_ID)  # call findPlayerById  ; ret 8
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "hn_next")
    a.emit(b"\x8b\x48", LIVING_WORLD_PLAYER_ID)  # mov  ecx, [eax+0x14]
    a.emit(b"\x3b\x0d", _imm(owner))  # cmp  ecx, [owner]
    a.jcc(JE, "hn_next")  # the defender took Player_1
    a.emit(b"\x8b\x3d", _imm(battle))  # mov  edi, [battle]
    a.call("has_player")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "hn_next")
    a.emit(b"\xff\x05", _imm(number))  # inc  dword [number]
    a.label("hn_next")
    a.emit(0x46)  # inc  esi
    a.jmp("hn_loop")
    a.label("hn_done")
    a.emit(b"\xa1", _imm(number))  # mov  eax, [number]
    a.emit(b"\xa3", _imm(result))  # mov  [result], eax
    a.label("hn_out")
    a.emit(0x61)  # popad
    a.emit(b"\xa1", _imm(result))  # mov  eax, [result]
    a.emit(0xC3)  # ret

    # hook_reveal: the map-wide reveal `startNewGame` hands the `ReplayObserver` player. That is
    # right for a replay, where the side is the audience and there is nobody to watch through, and
    # wrong here: the peer is a player in this session, seated on the same side only because it is
    # the one side that always exists. Skipping it leaves the observer on the ordinary shroud,
    # which its allies then lift for it. The flag is what tells the two apart, so a replay played
    # on a patched build still gets the whole map.
    a.label("hook_reveal")
    a.emit(b"\x80\x3d", _imm(seated), 0x00)  # cmp  byte [seated], 0
    a.jcc(JNE, "hook_reveal_skip")
    a.jmp_absolute(SHROUD_REVEAL_ALL)  # its `ret 4` returns to startNewGame
    a.label("hook_reveal_skip")
    a.emit(b"\xc2\x04\x00")  # ret  4    ; the callee's own cleanup

    # hook_start_pos -> eax, and the same value pushed under the return address, because the three
    # instructions displaced are `mov eax, [esi+0x10]` / `inc eax` / `push eax` and the `%d` that
    # follows consumes the push. `esi` is the local seat.
    #
    # A seat that is not in the battle has no place on the map, and the start position the engine
    # left on it names a `Player_N_Start` waypoint no two-army battle map declares - which opens
    # the camera in the map's corner. It borrows one from a participant instead: an ally's if the
    # lobby team says which side it is on, otherwise the first participant in slot order. Every way
    # of not knowing - no observer seated, this seat is fighting, nobody to borrow from - falls back
    # to the stock answer, which is written before anything else can go wrong.
    a.label("hook_start_pos")
    a.emit(0x60)  # pushad
    a.emit(b"\x8b\x46", GAME_SLOT_START_POS)  # mov  eax, [esi+0x10]
    a.emit(0x40)  # inc  eax
    a.emit(b"\xa3", _imm(sp_result))  # mov  [sp_result], eax
    a.emit(b"\x80\x3d", _imm(seated), 0x00)  # cmp  byte [seated], 0
    a.jcc(JE, "sp_out")
    a.call("needs_observer")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "sp_out")  # this seat is fighting: it has its own place
    a.emit(b"\x8b\x46", GAME_SLOT_TEAM)  # mov  eax, [esi+0x1c]
    a.emit(b"\xa3", _imm(sp_team))  # mov  [sp_team], eax
    a.emit(b"\xc7\x05", _imm(sp_best), _imm(0xFFFFFFFF))  # mov  dword [sp_best], -1
    a.emit(b"\xc7\x05", _imm(sp_ally), _imm(0xFFFFFFFF))  # mov  dword [sp_ally], -1
    a.emit(b"\x83\x25", _imm(sp_index), 0x00)  # and  dword [sp_index], 0
    a.label("sp_loop")
    a.emit(b"\x83\x3d", _imm(sp_index), GAME_INFO_SLOT_COUNT)  # cmp dword [sp_index], 8
    a.jcc(JAE, "sp_done")
    a.emit(b"\x8b\x0d", _imm(THE_GAME_INFO))  # mov  ecx, [TheGameInfo]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "sp_done")
    a.emit(b"\xff\x35", _imm(sp_index))  # push dword [sp_index]
    a.call_absolute(GAME_INFO_GET_SLOT)  # call getSlot          ; ret 4
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "sp_next")
    a.emit(b"\x8b\xf0")  # mov  esi, eax         ; the predicate reads esi
    a.call("is_participant")
    a.emit(b"\x84\xc0")  # test al, al
    a.jcc(JE, "sp_next")
    a.emit(b"\x83\x3d", _imm(sp_best), 0x00)  # cmp  dword [sp_best], 0
    a.jcc(JGE, "sp_have_first")  # the first one in slot order wins
    a.emit(b"\x8b\x46", GAME_SLOT_START_POS)  # mov  eax, [esi+0x10]
    a.emit(b"\xa3", _imm(sp_best))  # mov  [sp_best], eax
    a.label("sp_have_first")
    a.emit(b"\x83\x3d", _imm(sp_ally), 0x00)  # cmp  dword [sp_ally], 0
    a.jcc(JGE, "sp_next")
    a.emit(b"\x83\x3d", _imm(sp_team), 0x00)  # cmp  dword [sp_team], 0
    a.jcc(JL, "sp_next")  # -1 is the lobby's no-team: nobody to prefer
    a.emit(b"\x8b\x46", GAME_SLOT_TEAM)  # mov  eax, [esi+0x1c]
    a.emit(b"\x3b\x05", _imm(sp_team))  # cmp  eax, [sp_team]
    a.jcc(JNE, "sp_next")
    a.emit(b"\x8b\x46", GAME_SLOT_START_POS)  # mov  eax, [esi+0x10]
    a.emit(b"\xa3", _imm(sp_ally))  # mov  [sp_ally], eax
    a.label("sp_next")
    a.emit(b"\xff\x05", _imm(sp_index))  # inc  dword [sp_index]
    a.jmp("sp_loop")
    a.label("sp_done")
    a.emit(b"\xa1", _imm(sp_ally))  # mov  eax, [sp_ally]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JGE, "sp_take")
    a.emit(b"\xa1", _imm(sp_best))  # mov  eax, [sp_best]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JL, "sp_out")  # nothing better than the engine's own answer
    a.label("sp_take")
    a.emit(0x40)  # inc  eax
    a.emit(b"\xa3", _imm(sp_result))  # mov  [sp_result], eax
    a.label("sp_out")
    a.emit(0x61)  # popad
    a.emit(b"\xa1", _imm(sp_result))  # mov  eax, [sp_result]
    a.emit(0x5A)  # pop  edx              ; the return address
    a.emit(0x50)  # push eax              ; the displaced `push eax`
    a.emit(0x52)  # push edx
    a.emit(0xC3)  # ret

    code = a.finish()
    entries = {
        name: a.label_va(name)
        for name in (
            "hook_prepare",
            "hook_name",
            "hook_faction",
            "hook_assign",
            "hook_number",
            "hook_reveal",
            "hook_start_pos",
        )
    }
    blob = bytearray(CODE_OFFSET)
    terminated = OBSERVER_SIDE_NAME + bytes(1)
    blob[NAME_OFFSET : NAME_OFFSET + len(terminated)] = terminated
    return bytes(blob) + code, entries


def _call_detour(from_va: int, to_va: int, width: int) -> bytes:
    """``call rel32`` to the cave, padded with ``nop`` - the pad is executed on the way back."""
    call = b"\xe8" + struct.pack("<i", to_va - (from_va + 5))
    return call + bytes([_NOP]) * (width - len(call))


def _jmp_detour(from_va: int, to_va: int, width: int) -> bytes:
    """``jmp rel32`` to the cave, padded with ``int3`` - the pad is unreachable."""
    jump = b"\xe9" + struct.pack("<i", to_va - (from_va + 5))
    return jump + bytes([_INT3]) * (width - len(jump))


class WotrBattleObserversPatch(Patch):
    """Let a War of the Ring co-op battle be fought, with the players not in it watching."""

    name = "wotr-battle-observers"
    author = "officialNecro"
    description = (
        "Stop multiplayer War of the Ring auto-resolving a battle just because not everyone is "
        "in it, and seat the players who are not as observers instead of on somebody else's "
        "army. Also numbers the attackers by participation rather than by lobby slot. No INI, "
        ".str or .apt change"
    )

    def apply(self, data: bytearray) -> None:
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError(
                f"this image already carries a {SECTION_NAME} section - the patch is already "
                "applied, and applying it twice would install a second copy of the cave"
            )
        self._check_anchors(data)
        section_va = allocate_section(
            data, SECTION_NAME, lambda base: build_cave(base)[0], SECTION_CHARACTERISTICS
        )
        for site, stock, new, note in self._edits(section_va):
            off = va_to_offset(data, site)
            if off is None:
                raise ValueError(f"0x{site:08x} is not mapped: not this build")
            apply_byte_patch(data, off, stock, new, note)

    def _edits(self, section_va: int) -> list[tuple[int, bytes, bytes, str]]:
        """``(site, stock bytes, replacement, note)`` for all nine rewritten sites."""
        entries = build_cave(section_va)[1]
        return [
            (
                QUORUM_BRANCH_VA,
                QUORUM_BRANCH_BYTES,
                QUORUM_BRANCH_PATCHED,
                "the participant-count gate: skip the forced auto-resolve always",
            ),
            (
                RESOLUTION_MASK_VA,
                RESOLUTION_MASK_BYTES,
                RESOLUTION_MASK_PATCHED,
                "the battle prompt's button mask: offer RealTime beside AutoResolve",
            ),
            (
                PREPARE_VA,
                PREPARE_BYTES,
                _call_detour(PREPARE_VA, entries["hook_prepare"], len(PREPARE_BYTES)),
                "put the seats that are not in this battle back into both loops",
            ),
            (
                SLOT_KIND_TEST_VA,
                SLOT_KIND_TEST_BYTES,
                _call_detour(SLOT_KIND_TEST_VA, entries["hook_name"], len(SLOT_KIND_TEST_BYTES)),
                "the side-name test -> the participation cave",
            ),
            (
                NUMBER_VA,
                NUMBER_BYTES,
                _call_detour(NUMBER_VA, entries["hook_number"], len(NUMBER_BYTES)),
                "the attacker's side number: slot index -> participation order",
            ),
            (
                FACTION_TEST_VA,
                FACTION_TEST_BYTES,
                _call_detour(FACTION_TEST_VA, entries["hook_faction"], len(FACTION_TEST_BYTES)),
                "the side's faction test -> the participation cave",
            ),
            (
                ASSIGN_NAME_VA,
                ASSIGN_NAME_BYTES,
                _call_detour(ASSIGN_NAME_VA, entries["hook_assign"], len(ASSIGN_NAME_BYTES)),
                "the seat's name -> the ReplayObserver side",
            ),
            (
                REVEAL_CALL_VA,
                REVEAL_CALL_BYTES,
                _call_detour(REVEAL_CALL_VA, entries["hook_reveal"], len(REVEAL_CALL_BYTES)),
                "the ReplayObserver map reveal: keep it for a replay, skip it for a battle",
            ),
            (
                START_POSITION_VA,
                START_POSITION_BYTES,
                _call_detour(
                    START_POSITION_VA, entries["hook_start_pos"], len(START_POSITION_BYTES)
                ),
                "the opening camera: lend the observer a participant's start position",
            ),
        ]

    def verify(self, data: bytes | bytearray) -> list[str]:
        """Return the structural problems that mean ``data`` does not carry this patch.

        Locates the cave, rebuilds it against the base VA it actually landed on, and compares
        that and all nine edits with what is on disk. Reads only via ``struct`` and the section
        table, so verification needs no disassembler.
        """
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located

        problems: list[str] = []
        expected, _entries = build_cave(section_va)
        if bytes(data[section_off : section_off + len(expected)]) != expected:
            problems.append(f"{SECTION_NAME} does not hold the expected cave")

        for site, _stock, new, note in self._edits(section_va):
            off = va_to_offset(data, site)
            if off is None:
                problems.append(f"0x{site:08x} is not mapped")
                continue
            got = bytes(data[off : off + len(new)])
            if got != new:
                problems.append(f"{note}: 0x{site:08x} expected {new.hex()}, got {got.hex()}")

        problems.extend(self._anchor_problems(data))
        return problems

    def _check_anchors(self, data: bytes | bytearray) -> None:
        problems = self._anchor_problems(data)
        if problems:
            raise ValueError("; ".join(problems))

    def _anchor_problems(self, data: bytes | bytearray) -> list[str]:
        """The sites this patch reads but never writes: the two branches its forced comparisons
        feed, and the prologues of the routines its cave calls or jumps to."""
        problems: list[str] = []
        for va, expected, what in ANCHORS:
            off = va_to_offset(data, va)
            if off is None or bytes(data[off : off + len(expected)]) != expected:
                problems.append(
                    f"0x{va:08x} is not {what} ({expected.hex()}): not the expected build"
                )
        return problems
