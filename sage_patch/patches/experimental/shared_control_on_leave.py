"""Leave a leaver's army in place, under the command of their allies.

Stock, the leave order hands everything the leaver owns to their first undefeated ally and then
kills the leaver: one ally inherits a second army, its command points and its economy. With this
patch the leaver's `Player` keeps its objects, money, command points and upgrades, and every
allied human still in the game may select those objects and give them orders.

One bit per player index, `abandoned`, is the only new state. The leave order sets it, and that
order runs on every peer on the same frame, so the bit is lockstep state and needs no traffic of
its own. Player `P` may command an object of player `Q` when `Q` is abandoned, `P` is neither
dead nor an observer, and the two see each other as allies. Four edits:

- the leave order's transfer arm is replaced: while a living human ally remains the leaver is
  marked abandoned and nothing moves. When none does, the leaver and every abandoned ally of
  theirs are handed to a remaining ally (an AI, by then) or killed, as stock does for one player;
- `AIGroup::removeAnyObjectsNotOwnedByPlayer`, the one ownership check an order passes, keeps an
  object its sender may command;
- `Object::isLocallyControlled`, the client's "is this mine", answers the same relation for the
  local player, which is what lets the leaver's units be selected and ordered;
- `VictoryConditions::reset` clears the bits between games.

Derivation, and what is still unverified in a running game: `../../docs/shared-control-on-leave.md`.
"""

from __future__ import annotations

from ...addresses import (
    AIGROUP_REMOVE_NOT_OWNED_BY,
    AIGROUP_REMOVE_NOT_OWNED_BY_BYTES,
    AIGROUP_REMOVE_NOT_OWNED_BY_OWNER_CALL,
    AIGROUP_REMOVE_NOT_OWNED_BY_SENDER_ESP,
    OBJECT_GET_CONTROLLING_PLAYER,
    OBJECT_IS_LOCALLY_CONTROLLED,
    OBJECT_IS_LOCALLY_CONTROLLED_BYTES,
    PLAYER_DEFAULT_TEAM,
    PLAYER_GET_RELATIONSHIP,
    PLAYER_GET_RELATIONSHIP_ENTRY,
    PLAYER_INDEX,
    PLAYER_IS_DEFEATED,
    PLAYER_IS_OBSERVER,
    PLAYER_KILL_PLAYER,
    PLAYER_KILL_PLAYER_ENTRY,
    PLAYER_LIST_COUNT_OFFSET,
    PLAYER_LIST_GET_NTH,
    PLAYER_LIST_GET_NTH_BYTES,
    PLAYER_LIST_LOCAL_PLAYER,
    PLAYER_RELATIONSHIP_ALLIES,
    PLAYER_TRANSFER_ASSETS_FROM,
    PLAYER_TRANSFER_ASSETS_FROM_ENTRY,
    PLAYER_TYPE,
    PLAYER_TYPE_HUMAN,
    SELF_DESTRUCT_DONE,
    SELF_DESTRUCT_DONE_BYTES,
    SELF_DESTRUCT_LEAVER_EBP,
    SELF_DESTRUCT_SCRATCH_EBP,
    SELF_DESTRUCT_TRANSFER_ARM,
    SELF_DESTRUCT_TRANSFER_ARM_BYTES,
    THE_PLAYER_LIST,
    THE_VICTORY_CONDITIONS,
    VICTORY_CONDITIONS_HAS_BEEN_DEFEATED,
    VICTORY_CONDITIONS_HAS_BEEN_DEFEATED_ENTRY,
    VICTORY_CONDITIONS_HAS_BEEN_DEFEATED_SLOT,
    VICTORY_CONDITIONS_RESET,
    VICTORY_CONDITIONS_RESET_ENTRY,
    VICTORY_CONDITIONS_RESET_SLOT,
    VICTORY_CONDITIONS_VTABLE,
)
from ...asm import JAE, JB, JE, JGE, JNE, Asm
from ...patcher import Patch
from ...utils import (
    allocate_section,
    apply_byte_patch,
    call_rel32,
    file_offset,
    find_section,
    jmp_rel32,
    u32,
)

__all__ = [
    "ANCHORS",
    "SECTION_NAME",
    "SharedControlOnLeavePatch",
    "build_code",
    "edits",
    "layout",
]

SECTION_NAME = ".shctl"  # the PE name field is 8 bytes and truncates silently

# IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. Writable: the
# abandoned mask lives at the head of the cave.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

_RESET_SLOT = VICTORY_CONDITIONS_VTABLE + VICTORY_CONDITIONS_RESET_SLOT

#: Every window the patch edits or depends on, as `{va: stock bytes}`. The three code windows are
#: whole routines, so a build where anything around a hook moved fails here; the rest are the
#: entries of what the cave calls and the two vtable slots it reads or repoints.
ANCHORS: dict[int, bytes] = {
    SELF_DESTRUCT_TRANSFER_ARM: SELF_DESTRUCT_TRANSFER_ARM_BYTES,
    SELF_DESTRUCT_DONE: SELF_DESTRUCT_DONE_BYTES,
    AIGROUP_REMOVE_NOT_OWNED_BY: AIGROUP_REMOVE_NOT_OWNED_BY_BYTES,
    OBJECT_IS_LOCALLY_CONTROLLED: OBJECT_IS_LOCALLY_CONTROLLED_BYTES,
    _RESET_SLOT: u32(VICTORY_CONDITIONS_RESET),
    VICTORY_CONDITIONS_RESET: VICTORY_CONDITIONS_RESET_ENTRY,
    VICTORY_CONDITIONS_VTABLE + VICTORY_CONDITIONS_HAS_BEEN_DEFEATED_SLOT: u32(
        VICTORY_CONDITIONS_HAS_BEEN_DEFEATED
    ),
    VICTORY_CONDITIONS_HAS_BEEN_DEFEATED: VICTORY_CONDITIONS_HAS_BEEN_DEFEATED_ENTRY,
    OBJECT_GET_CONTROLLING_PLAYER: bytes.fromhex("8b891c030000"),  # mov ecx, [ecx+0x31c]
    PLAYER_GET_RELATIONSHIP: PLAYER_GET_RELATIONSHIP_ENTRY,
    PLAYER_TRANSFER_ASSETS_FROM: PLAYER_TRANSFER_ASSETS_FROM_ENTRY,
    PLAYER_KILL_PLAYER: PLAYER_KILL_PLAYER_ENTRY,
    PLAYER_LIST_GET_NTH: PLAYER_LIST_GET_NTH_BYTES,
}

_LEAVER = SELF_DESTRUCT_LEAVER_EBP & 0xFF
_SCRATCH = SELF_DESTRUCT_SCRATCH_EBP


def _mutual_allies(a: Asm) -> None:
    """`mutual_allies`: ZF set when players `ecx` and `edx` each see the other's default team as
    `ALLIES`. Keeps `ebx`, `esi` and `edi`."""
    a.label("mutual_allies")
    a.emit(0x56, 0x57)  # push esi / push edi
    a.emit(0x8B, 0xF1, 0x8B, 0xFA)  # mov esi, ecx / mov edi, edx
    a.emit(0xFF, 0xB7, u32(PLAYER_DEFAULT_TEAM))  # push dword [edi+0x30c]
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(PLAYER_GET_RELATIONSHIP)
    a.emit(0x83, 0xF8, PLAYER_RELATIONSHIP_ALLIES)  # cmp eax, ALLIES
    a.jcc(JNE, "mutual_allies_out")
    a.emit(0xFF, 0xB6, u32(PLAYER_DEFAULT_TEAM))  # push dword [esi+0x30c]
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(PLAYER_GET_RELATIONSHIP)
    a.emit(0x83, 0xF8, PLAYER_RELATIONSHIP_ALLIES)  # cmp eax, ALLIES
    a.label("mutual_allies_out")
    a.emit(0x5F, 0x5E, 0xC3)  # pop edi / pop esi / ret


def _may_command(a: Asm) -> None:
    """`may_command`: `eax` = 1 when player `ecx` may command the objects of another player
    `edx`, else 0. Either may be null. Reads nothing but latched player state, so the client may
    ask it at any rate. Keeps `ebx`, `esi` and `edi`."""
    a.label("may_command")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "may_command_out")
    a.emit(0x85, 0xD2)  # test edx, edx
    a.jcc(JE, "may_command_out")
    a.emit(0x8B, 0x42, PLAYER_INDEX)  # mov eax, [edx+0x54]
    a.emit(0x0F, 0xA3, 0x05, u32(a.label_va("mask")))  # bt [mask], eax    ; owner abandoned?
    a.jcc(JAE, "may_command_no")
    a.emit(0x80, 0xB9, u32(PLAYER_IS_DEFEATED), 0x00)  # cmp byte [ecx+0x754], 0
    a.jcc(JNE, "may_command_no")
    a.emit(0x80, 0xB9, u32(PLAYER_IS_OBSERVER), 0x00)  # cmp byte [ecx+0x35a], 0
    a.jcc(JNE, "may_command_no")
    a.call("mutual_allies")
    a.jcc(JNE, "may_command_no")
    a.emit(0xB8, u32(1))  # mov eax, 1
    a.emit(0xC3)  # ret
    a.label("may_command_no")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.label("may_command_out")
    a.emit(0xC3)  # ret


def _next_player(a: Asm, done: str, skip: str) -> None:
    """The head of a walk over `ThePlayerList` counted in the dispatcher's scratch slot: `edi` =
    the next player, leaving through `done` past the last and through `skip` for an empty seat."""
    a.emit(0x8B, 0x0D, u32(THE_PLAYER_LIST))  # mov ecx, [ThePlayerList]
    a.emit(0x8B, 0x45, _SCRATCH)  # mov eax, [ebp+8]
    a.emit(0x3B, 0x41, PLAYER_LIST_COUNT_OFFSET)  # cmp eax, [ecx+0x14]
    a.jcc(JGE, done)
    a.emit(0x50)  # push eax
    a.call_absolute(PLAYER_LIST_GET_NTH)
    a.emit(0x8B, 0xF8)  # mov edi, eax
    a.emit(0x85, 0xFF)  # test edi, edi
    a.jcc(JE, skip)


def _find_ally(a: Asm) -> None:
    """`find_ally(Bool humansOnly)`: `eax` = the leaver's first mutual ally that has neither left
    nor been defeated, or 0; `ret 4`. Runs in the dispatcher's frame, and clobbers `edi` and the
    scratch slot. `hasBeenDefeated` is asked exactly as the stock arm asks it."""
    a.label("find_ally")
    a.emit(0x83, 0x65, _SCRATCH, 0x00)  # and dword [ebp+8], 0
    a.label("find_ally_loop")
    _next_player(a, "find_ally_none", "find_ally_next")
    a.emit(0x3B, 0x7D, _LEAVER)  # cmp edi, [ebp-0x14]
    a.jcc(JE, "find_ally_next")
    a.emit(0x83, 0x7C, 0x24, 0x04, 0x00)  # cmp dword [esp+4], 0   ; humansOnly?
    a.jcc(JE, "find_ally_any_type")
    a.emit(0x83, 0x7F, PLAYER_TYPE, PLAYER_TYPE_HUMAN)  # cmp dword [edi+0x5c], HUMAN
    a.jcc(JNE, "find_ally_next")
    a.label("find_ally_any_type")
    a.emit(0x8B, 0x47, PLAYER_INDEX)  # mov eax, [edi+0x54]
    a.emit(0x0F, 0xA3, 0x05, u32(a.label_va("mask")))  # bt [mask], eax    ; already left?
    a.jcc(JB, "find_ally_next")
    a.emit(0x8B, 0x4D, _LEAVER)  # mov ecx, [ebp-0x14]
    a.emit(0x8B, 0xD7)  # mov edx, edi
    a.call("mutual_allies")
    a.jcc(JNE, "find_ally_next")
    a.emit(0x8B, 0x0D, u32(THE_VICTORY_CONDITIONS))  # mov ecx, [TheVictoryConditions]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0x57)  # push edi
    a.emit(0xFF, 0x50, VICTORY_CONDITIONS_HAS_BEEN_DEFEATED_SLOT)  # call [eax+0x40]
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JNE, "find_ally_next")
    a.emit(0x8B, 0xC7)  # mov eax, edi
    a.emit(0xC2, 0x04, 0x00)  # ret 4
    a.label("find_ally_next")
    a.emit(0xFF, 0x45, _SCRATCH)  # inc dword [ebp+8]
    a.jmp("find_ally_loop")
    a.label("find_ally_none")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.emit(0xC2, 0x04, 0x00)  # ret 4


def _leave(a: Asm) -> None:
    """`leave`: the transfer arm of the leave order. Entered by `jmp` with the dispatcher's frame
    and leaves to `SELF_DESTRUCT_DONE`, as both stock paths do. Clobbers `edi` and the scratch
    slot, which the stock arm clobbers too, and keeps `ebx` and `esi`."""
    a.label("leave")
    a.emit(0x6A, 0x01)  # push 1                     ; humans only
    a.call("find_ally")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "leave_last_human")
    # A human ally stays: the leaver keeps everything, and is marked for that ally to command.
    a.emit(0x8B, 0x45, _LEAVER)  # mov eax, [ebp-0x14]
    a.emit(0x8B, 0x40, PLAYER_INDEX)  # mov eax, [eax+0x54]
    a.emit(0x0F, 0xAB, 0x05, u32(a.label_va("mask")))  # bts [mask], eax
    a.jmp_absolute(SELF_DESTRUCT_DONE)

    # Nobody is left to command anything: the leaver and each abandoned ally of theirs go to a
    # remaining ally when there is one, and are killed either way.
    a.label("leave_last_human")
    a.emit(0x6A, 0x00)  # push 0                     ; any type
    a.call("find_ally")
    a.emit(0x50)  # push eax                         ; the heir, or 0
    a.emit(0x83, 0x65, _SCRATCH, 0x00)  # and dword [ebp+8], 0
    a.label("leave_loop")
    _next_player(a, "leave_end", "leave_next")
    a.emit(0x3B, 0x7D, _LEAVER)  # cmp edi, [ebp-0x14]
    a.jcc(JE, "leave_hand_over")
    a.emit(0x8B, 0x47, PLAYER_INDEX)  # mov eax, [edi+0x54]
    a.emit(0x0F, 0xA3, 0x05, u32(a.label_va("mask")))  # bt [mask], eax
    a.jcc(JAE, "leave_next")
    a.emit(0x8B, 0x4D, _LEAVER)  # mov ecx, [ebp-0x14]
    a.emit(0x8B, 0xD7)  # mov edx, edi
    a.call("mutual_allies")
    a.jcc(JNE, "leave_next")
    a.label("leave_hand_over")
    a.emit(0x8B, 0x47, PLAYER_INDEX)  # mov eax, [edi+0x54]
    a.emit(0x0F, 0xB3, 0x05, u32(a.label_va("mask")))  # btr [mask], eax
    a.emit(0x8B, 0x0C, 0x24)  # mov ecx, [esp]           ; the heir
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "leave_kill")
    a.emit(0x6A, 0x01)  # push 1
    a.emit(0x57)  # push edi
    a.call_absolute(PLAYER_TRANSFER_ASSETS_FROM)
    a.label("leave_kill")
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(PLAYER_KILL_PLAYER)
    a.label("leave_next")
    a.emit(0xFF, 0x45, _SCRATCH)  # inc dword [ebp+8]
    a.jmp("leave_loop")
    a.label("leave_end")
    a.emit(0x58)  # pop eax
    a.jmp_absolute(SELF_DESTRUCT_DONE)


def _owner(a: Asm) -> None:
    """`owner`: `Object::getControllingPlayer` for the order filter, which compares the answer
    with the sender. Answers the sender itself for an object the sender may command, so the
    filter keeps it. Called in place of the getter, with the filter's frame under it."""
    sender = AIGROUP_REMOVE_NOT_OWNED_BY_SENDER_ESP + 4  # past this call's return address
    a.label("owner")
    a.call_absolute(OBJECT_GET_CONTROLLING_PLAYER)
    a.emit(0x8B, 0x4C, 0x24, sender)  # mov ecx, [esp+0x14]
    a.emit(0x3B, 0xC1)  # cmp eax, ecx
    a.jcc(JE, "owner_out")
    a.emit(0x50)  # push eax
    a.emit(0x8B, 0xD0)  # mov edx, eax
    a.call("may_command")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.emit(0x58)  # pop eax                          ; the real owner; flags survive
    a.jcc(JE, "owner_out")
    a.emit(0x8B, 0x44, 0x24, sender)  # mov eax, [esp+0x14]
    a.label("owner_out")
    a.emit(0xC3)  # ret


def _local(a: Asm) -> None:
    """`local`: `Object::isLocallyControlled`, whole. `eax` = 1 for the local player's own
    objects and for those the local player may command."""
    a.label("local")
    a.call_absolute(OBJECT_GET_CONTROLLING_PLAYER)
    a.emit(0x8B, 0x0D, u32(THE_PLAYER_LIST))  # mov ecx, [ThePlayerList]
    a.emit(0x8B, 0x49, PLAYER_LIST_LOCAL_PLAYER)  # mov ecx, [ecx+0x10]
    a.emit(0x3B, 0xC1)  # cmp eax, ecx
    a.jcc(JE, "local_yes")
    a.emit(0x8B, 0xD0)  # mov edx, eax
    a.jmp("may_command")
    a.label("local_yes")
    a.emit(0xB8, u32(1))  # mov eax, 1
    a.emit(0xC3)  # ret


def _reset(a: Asm) -> None:
    """`reset`: `VictoryConditions::reset`, after forgetting who left the game before it."""
    a.label("reset")
    a.emit(0x83, 0x25, u32(a.label_va("mask")), 0x00)  # and dword [mask], 0
    a.jmp_absolute(VICTORY_CONDITIONS_RESET)


def layout(base_va: int) -> Asm:
    """The cave: the abandoned mask, a bit per `Player` index, then the routines."""
    a = Asm(base_va)
    a.label("mask")
    a.emit(u32(0))
    _mutual_allies(a)
    _may_command(a)
    _find_ally(a)
    _leave(a)
    _owner(a)
    _local(a)
    _reset(a)
    return a


def build_code(base_va: int) -> bytes:
    return layout(base_va).finish()


def edits(base_va: int) -> dict[int, tuple[bytes, str]]:
    """`{va: (new bytes, what it is)}` for a cave at `base_va`."""
    a = layout(base_va)
    arm, call, local = (
        SELF_DESTRUCT_TRANSFER_ARM,
        AIGROUP_REMOVE_NOT_OWNED_BY_OWNER_CALL,
        OBJECT_IS_LOCALLY_CONTROLLED,
    )
    return {
        # over `mov ecx, [ThePlayerList]`; the rest of the arm is no longer reached
        arm: (jmp_rel32(arm, a.label_va("leave"), 6), "leave order transfer arm -> leave"),
        call: (call_rel32(call, a.label_va("owner")), "order filter owner -> owner"),
        # over `mov eax, [ThePlayerList]`; the cave returns to the caller itself
        local: (jmp_rel32(local, a.label_va("local"), 5), "isLocallyControlled -> local"),
        _RESET_SLOT: (u32(a.label_va("reset")), "VictoryConditions reset slot -> reset"),
    }


def _windows(base_va: int | None) -> dict[int, bytes]:
    """`ANCHORS` as they read in a stock image, or with the edits for a cave at `base_va`."""
    windows = dict(ANCHORS)
    if base_va is None:
        return windows
    for va, (new, _what) in edits(base_va).items():
        start = next(w for w in windows if w <= va < w + len(windows[w]))
        at = va - start
        windows[start] = windows[start][:at] + new + windows[start][at + len(new) :]
    return windows


def _problems(data: bytes | bytearray, base_va: int | None) -> list[str]:
    problems: list[str] = []
    for va, want in _windows(base_va).items():
        off = file_offset(data, va)
        got = bytes(data[off : off + len(want)])
        if got != want:
            problems.append(f"@0x{va:08x}: expected {want.hex()}, got {got.hex()}")
    return problems


class SharedControlOnLeavePatch(Patch):
    name = "shared-control-on-leave"
    author = "officialNecro"
    experimental = True
    description = (
        "When a player leaves a multiplayer game, keep their army, buildings, money and command "
        "points with their own seat instead of handing everything to the first ally, and let "
        "every allied human still playing select and command what they left, as Warcraft III "
        "shares a leaver's units. Production at the leaver's buildings spends the leaver's "
        "money. When the last human of a team leaves, what the team's leavers still own goes to "
        "a remaining AI ally or is destroyed. Logic-side: every peer needs the same binary. A "
        "savegame made after a leave forgets who left. No INI change"
    )

    def apply(self, data: bytearray) -> None:
        problems = _problems(data, None)
        if problems:
            raise ValueError(
                "; ".join(problems) + " - the file is not the expected build, or already carries "
                "this patch"
            )
        cave_va = allocate_section(data, SECTION_NAME, build_code, _CHARACTERISTICS)
        stock = _windows(None)
        for va, (new, what) in edits(cave_va).items():
            start = next(w for w in stock if w <= va < w + len(stock[w]))
            old = stock[start][va - start : va - start + len(new)]
            apply_byte_patch(data, file_offset(data, va), old, new, what)

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        cave_va, cave_off, vsize = located
        problems = _problems(data, cave_va)
        code = build_code(cave_va)
        if vsize < len(code) or bytes(data[cave_off : cave_off + len(code)]) != code:
            problems.append(f"the routines in {SECTION_NAME} are not the ones this patch builds")
        return problems
