"""Add `TransferToReplacement` to `ReplaceSelfUpgrade` and `SummonReplacementSpecialAbilityUpdate`:
the object that replaces another keeps its upgrades, experience, health, selection, rally point and
production queue.

The keyword takes a list of flags, parsed by the engine's own bit-string parser:

    TransferToReplacement = UPGRADES EXPERIENCE HEALTH SELECTION RALLY PRODUCTION HORDE

- `UPGRADES` grants the new object every object upgrade the old one had, through
  `Object::giveUpgrade`, so the new object's own upgrade modules fire as if it had bought them.
- `EXPERIENCE` raises the new object's experience to the old one's, which re-derives its level
  from the new template's thresholds; level-up effects are suppressed, as the stock swaps do.
  Experience is only ever raised, never lowered. `SummonReplacementSpecialAbilityUpdate` already
  copies experience in stock, so there the flag changes nothing.
- `HEALTH` gives the new object the old one's health ratio of its own maximum. On the summon swap
  it replaces the stock absolute copy.
- `SELECTION` adds the new object to the control group the old one was in and, if the old one was
  selected, selects it instead. Only the owner's machine posts this. The summon swap already does
  it in stock, so there the flag changes nothing.
- `RALLY` copies a production building's rally point.
- `PRODUCTION` moves the production queue, with its progress and what was paid, instead of letting
  it be deleted unrefunded with the old building.
- `HORDE` hands a horde's members over: the new horde keeps only as many members as the old
  one had left (leader to leader, banner carrier to banner carrier, the rest in order), each at
  its old partner's health ratio, and each member group's experience rises to its partners'.

Absent, the field is empty and both modules behave as stock. A mod that writes the keyword will not
load on an unpatched binary, since an unknown field is an INI parse error.

Derivation: `../docs/replacement-transfer.md`.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from sage_ini.engine import Engine, FieldDelta

from ..addresses import (
    APPEND_MESSAGE_VTABLE_SLOT,
    ARG_APPENDERS,
    BODY_GET_HEALTH_RATIO_SLOT,
    BODY_GET_MAX_HEALTH_SLOT,
    BODY_SET_HEALTH_SLOT,
    CONTAIN_ITEM_LIST,
    CONTAIN_ITEM_LIST_NODE_OBJECT,
    DRAWABLE_SELECTED,
    EXIT_INTERFACE_GET_RALLY_POINT_SLOT,
    EXIT_INTERFACE_SET_RALLY_POINT_SLOT,
    EXPERIENCE_TRACKER_FEEDBACK,
    EXPERIENCE_TRACKER_SET_ABSOLUTE,
    EXPERIENCE_TRACKER_XP,
    FIELD_PARSE_STRIDE,
    FLOAT_HUNDRED,
    GAME_LOGIC_DESTROY_OBJECT,
    GAME_LOGIC_DESTROY_OBJECT_ENTRY,
    HORDE_EXPERIENCE_ADD,
    HORDE_EXPERIENCE_ADD_ENTRY,
    HORDE_EXPERIENCE_GROUP_LOOKUP_OR_INSERT,
    HORDE_EXPERIENCE_GROUP_LOOKUP_OR_INSERT_ENTRY,
    HORDE_EXPERIENCE_GROUPS_OFFSET,
    HORDE_IFACE_BANNER_CARRIER_ID,
    HORDE_IFACE_LEADER_ID,
    HORDE_IFACE_REMOVE_MEMBER,
    HORDE_IFACE_REMOVE_MEMBER_ENTRY,
    HORDE_IFACE_REMOVE_MEMBER_SLOT,
    HORDE_IFACE_VTABLE,
    IN_GAME_UI_DESELECT_DRAWABLE_SLOT,
    IN_GAME_UI_SELECT_DRAWABLE_SLOT,
    INI_PARSE_BIT_STRING_32,
    INI_PARSE_BIT_STRING_32_ENTRY,
    MSG_ADD_TO_TEAM0,
    MSG_CREATE_SELECTED_GROUP,
    OBJECT_BODY_MODULE,
    OBJECT_CONTAIN,
    OBJECT_EXPERIENCE_TRACKER,
    OBJECT_GET_CONTROLLING_PLAYER,
    OBJECT_GET_CONTROLLING_PLAYER_ENTRY,
    OBJECT_GET_DRAWABLE,
    OBJECT_GET_DRAWABLE_BYTES,
    OBJECT_GET_EXIT_INTERFACE,
    OBJECT_GET_EXIT_INTERFACE_ENTRY,
    OBJECT_GET_HORDE_IFACE,
    OBJECT_GET_HORDE_IFACE_ENTRY,
    OBJECT_GET_PRODUCTION_UPDATE_INTERFACE,
    OBJECT_GET_PRODUCTION_UPDATE_INTERFACE_ENTRY,
    OBJECT_GIVE_UPGRADE,
    OBJECT_ID,
    OBJECT_IS_LOCALLY_CONTROLLED,
    OBJECT_TEMPLATE_EXPERIENCE_GROUP_OFFSET,
    OBJECT_THING_TEMPLATE,
    OBJECT_UPGRADE_MASK,
    PLAYER_COMPLETED_UPGRADE_MASK_WORDS,
    PLAYER_FIND_SQUAD,
    PLAYER_FIND_SQUAD_ENTRY,
    PRODUCTION_ENTRY_NEXT,
    PRODUCTION_ENTRY_PREV,
    PRODUCTION_ENTRY_PROGRESS,
    PRODUCTION_INTERFACE_DOOR_HOLD,
    PRODUCTION_INTERFACE_ID_COUNTER,
    PRODUCTION_INTERFACE_OFFSET,
    PRODUCTION_INTERFACE_QUEUE_LENGTH,
    PRODUCTION_QUEUE_APPEND,
    PRODUCTION_QUEUE_APPEND_BYTES,
    PRODUCTION_QUEUE_HEAD,
    PRODUCTION_QUEUE_TAIL,
    REPLACE_SELF_FIELD_TABLE,
    REPLACE_SELF_FIELD_TABLE_PUSH,
    REPLACE_SELF_FIELD_TABLE_PUSH_BYTES,
    REPLACE_SELF_FIELD_TABLE_STOCK,
    REPLACE_SELF_FRAME_MODULE_DATA,
    REPLACE_SELF_FREE_OFFSET,
    REPLACE_SELF_MODULE_DATA_LIST_INIT,
    REPLACE_SELF_MODULE_DATA_LIST_INIT_BYTES,
    REPLACE_SELF_MODULE_DATA_LIST_INIT_RESUME,
    REPLACE_SELF_NAME_COPY,
    REPLACE_SELF_NAME_COPY_BYTES,
    REPLACE_SELF_NAME_COPY_RESUME,
    REPLACE_SELF_OLD_OBJECT_DISP,
    SUMMON_REPLACEMENT_DEFAULT_STORES,
    SUMMON_REPLACEMENT_DEFAULT_STORES_BYTES,
    SUMMON_REPLACEMENT_FIELD_TABLE,
    SUMMON_REPLACEMENT_FIELD_TABLE_PUSH,
    SUMMON_REPLACEMENT_FIELD_TABLE_PUSH_BYTES,
    SUMMON_REPLACEMENT_FIELD_TABLE_STOCK,
    SUMMON_REPLACEMENT_FRAME_MODULE,
    SUMMON_REPLACEMENT_FREE_OFFSET,
    SUMMON_REPLACEMENT_HEALTH_COPY_END,
    SUMMON_REPLACEMENT_HEALTH_COPY_END_BYTES,
    SUMMON_REPLACEMENT_XP_RESTORE,
    SUMMON_REPLACEMENT_XP_RESTORE_BYTES,
    SUMMON_REPLACEMENT_XP_RESTORE_RESUME,
    THE_GAME_LOGIC,
    THE_IN_GAME_UI,
    THE_MESSAGE_STREAM,
    THE_UPGRADE_CENTER,
    UPGRADE_CENTER_LIST,
    UPGRADE_TEMPLATE_INDEX,
    UPGRADE_TEMPLATE_NEXT,
)
from ..asm import JAE, JB, JBE, JE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, file_offset, find_section, jmp_rel32, u32

__all__ = [
    "ANCHORS",
    "BLOCKS",
    "FLAGS",
    "FLAG_EXPERIENCE",
    "FLAG_HEALTH",
    "FLAG_HORDE",
    "FLAG_PRODUCTION",
    "FLAG_RALLY",
    "FLAG_SELECTION",
    "FLAG_UPGRADES",
    "KEYWORD",
    "SECTION_NAME",
    "ReplacementTransferPatch",
    "build_section",
    "layout",
    "rewritten_summon_defaults",
]

SECTION_NAME = ".rpxfer"  # 7 chars: the PE name field is 8 bytes and truncates silently

KEYWORD = "TransferToReplacement"
#: The flag names, in bit order: the bit-string parser sets bit `i` for the `i`-th name.
FLAGS = ("UPGRADES", "EXPERIENCE", "HEALTH", "SELECTION", "RALLY", "PRODUCTION", "HORDE")
FLAG_UPGRADES = 1 << FLAGS.index("UPGRADES")
FLAG_EXPERIENCE = 1 << FLAGS.index("EXPERIENCE")
FLAG_HEALTH = 1 << FLAGS.index("HEALTH")
FLAG_SELECTION = 1 << FLAGS.index("SELECTION")
FLAG_RALLY = 1 << FLAGS.index("RALLY")
FLAG_PRODUCTION = 1 << FLAGS.index("PRODUCTION")
FLAG_HORDE = 1 << FLAGS.index("HORDE")

#: The modules that gain the keyword, as the INI block names a linter knows them by.
BLOCKS = ("ReplaceSelfUpgrade", "SummonReplacementSpecialAbilityUpdate")

#: Read, never rewritten: the routines the cave calls (so their signatures are the ones relied on),
#: and where the summon swap resumes when `HEALTH` replaces its own copy. `isLocallyControlled` is
#: called but not pinned: `shared-control-on-leave` hooks its entry, and only its contract matters.
ANCHORS: dict[int, bytes] = {
    INI_PARSE_BIT_STRING_32: INI_PARSE_BIT_STRING_32_ENTRY,
    OBJECT_GET_EXIT_INTERFACE: OBJECT_GET_EXIT_INTERFACE_ENTRY,
    OBJECT_GET_CONTROLLING_PLAYER: OBJECT_GET_CONTROLLING_PLAYER_ENTRY,
    OBJECT_GET_DRAWABLE: OBJECT_GET_DRAWABLE_BYTES,
    PLAYER_FIND_SQUAD: PLAYER_FIND_SQUAD_ENTRY,
    OBJECT_GET_HORDE_IFACE: OBJECT_GET_HORDE_IFACE_ENTRY,
    GAME_LOGIC_DESTROY_OBJECT: GAME_LOGIC_DESTROY_OBJECT_ENTRY,
    HORDE_EXPERIENCE_ADD: HORDE_EXPERIENCE_ADD_ENTRY,
    HORDE_EXPERIENCE_GROUP_LOOKUP_OR_INSERT: HORDE_EXPERIENCE_GROUP_LOOKUP_OR_INSERT_ENTRY,
    HORDE_IFACE_REMOVE_MEMBER: HORDE_IFACE_REMOVE_MEMBER_ENTRY,
    HORDE_IFACE_VTABLE + HORDE_IFACE_REMOVE_MEMBER_SLOT: u32(HORDE_IFACE_REMOVE_MEMBER),
    OBJECT_GET_PRODUCTION_UPDATE_INTERFACE: OBJECT_GET_PRODUCTION_UPDATE_INTERFACE_ENTRY,
    PRODUCTION_QUEUE_APPEND: PRODUCTION_QUEUE_APPEND_BYTES,
    FLOAT_HUNDRED: struct.pack("<f", 100.0),
    SUMMON_REPLACEMENT_HEALTH_COPY_END: SUMMON_REPLACEMENT_HEALTH_COPY_END_BYTES,
}

# CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ: strings, two tables and code; nothing is written
# at runtime.
_CHARACTERISTICS = 0x40 | 0x20000000 | 0x40000000

#: The queue's head and tail as interface offsets.
_HEAD = PRODUCTION_QUEUE_HEAD - PRODUCTION_INTERFACE_OFFSET
_TAIL = PRODUCTION_QUEUE_TAIL - PRODUCTION_INTERFACE_OFFSET

_APPEND_BOOLEAN = ARG_APPENDERS[2]
_APPEND_OBJECT_ID = ARG_APPENDERS[3]

_RSU_ROWS = len(REPLACE_SELF_FIELD_TABLE_STOCK) // FIELD_PARSE_STRIDE - 1
_SUMMON_ROWS = len(SUMMON_REPLACEMENT_FIELD_TABLE_STOCK) // FIELD_PARSE_STRIDE - 1

#: The six-byte `nop word [eax+eax+0]` that fills the second half of the widened store.
_NOP6 = bytes.fromhex("660f1f440000")


def rewritten_summon_defaults() -> bytes:
    """The summon `ModuleData` constructor's two byte stores from `ebx` (zero), as one dword
    store that also clears the new field at `+0xE6` and the pad byte after it."""
    new = b"\x89\x9e" + u32(SUMMON_REPLACEMENT_FREE_OFFSET - 2) + _NOP6
    assert len(new) == len(SUMMON_REPLACEMENT_DEFAULT_STORES_BYTES)
    return new


@dataclass(frozen=True)
class _Layout:
    keyword: int
    names: tuple[int, ...]
    name_list: int
    rsu_table: int
    summon_table: int
    code: int


def _strings() -> bytes:
    return b"".join(s.encode("ascii") + b"\x00" for s in (KEYWORD, *FLAGS))


def _layout(base_va: int) -> _Layout:
    at = base_va
    keyword = at
    at += len(KEYWORD) + 1
    names = []
    for name in FLAGS:
        names.append(at)
        at += len(name) + 1
    at += -at % 4
    name_list = at
    at += 4 * (len(FLAGS) + 1)
    rsu_table = at
    at += (_RSU_ROWS + 2) * FIELD_PARSE_STRIDE
    summon_table = at
    at += (_SUMMON_ROWS + 2) * FIELD_PARSE_STRIDE
    return _Layout(keyword, tuple(names), name_list, rsu_table, summon_table, at)


def _table(stock: bytes, rows: int, pieces: _Layout, parse_va: int, offset: int) -> bytes:
    """The stock rows verbatim (their pointers are absolute), the new row, the terminator."""
    row = struct.pack("<IIII", pieces.keyword, parse_va, pieces.name_list, offset)
    return stock[: rows * FIELD_PARSE_STRIDE] + row + bytes(FIELD_PARSE_STRIDE)


#: The most members `horde_copy` reads off either horde; past it, the rest are left as they are.
HORDE_MEMBER_CAP = 64

# `horde_copy`'s frame. Two member arrays below the scalars.
_H_OLD_IFACE = -0x04
_H_NEW_IFACE = -0x08
_H_OLD_COUNT = -0x0C
_H_OLD_NEXT = -0x10
_H_NEW_COUNT = -0x14
_H_OLD_LEADER = -0x18
_H_OLD_BANNER = -0x1C
_H_KEY = -0x20
_H_FEEDBACK = -0x24
_H_NEW = -0x30 - 4 * HORDE_MEMBER_CAP
_H_OLD = _H_NEW - 4 * HORDE_MEMBER_CAP
_H_FRAME = -_H_OLD


def _ebp(disp: int) -> bytes:
    """A `[ebp+disp]` mod/rm tail for register field 0 (OR the register in), disp8 or disp32."""
    if -0x80 <= disp < 0x80:
        return bytes([0x45]) + struct.pack("<b", disp)
    return bytes([0x85]) + struct.pack("<i", disp)


def _ebp_reg(reg: int, disp: int) -> bytes:
    tail = _ebp(disp)
    return bytes([tail[0] | reg << 3]) + tail[1:]


def _array(reg: int, index: int, disp: int) -> bytes:
    """`[ebp+index*4+disp32]` with `reg` in the register field."""
    return bytes([0x84 | reg << 3, 0x85 | index << 3]) + struct.pack("<i", disp)


EAX, ECX, EDX, EBX, ESP, EBP, ESI, EDI = range(8)


def _horde(a: Asm) -> None:
    """`horde_copy(old, new)`, `__stdcall`, `ret 8`: hand the old horde's members to the new one.

    Both member lists are read into arrays first. Each new member is then paired: the leader with
    the old leader, the banner carrier with the old banner carrier, every other member with the
    next old member that is neither. An unpaired new member leaves the horde the way the strength
    trim removes one (`HORDE_IFACE_REMOVE_MEMBER_SLOT`, then `destroyObject`), which frees its
    formation slot for a replenish. A paired one gets its partner's health ratio of its own
    maximum, and the experience account of its group is raised to its partner's experience. Last,
    `HORDE_EXPERIENCE_ADD(member, 0)` on every kept member sets the members to their accounts and
    the horde to the highest, with the horde's level-up feedback off. Keeps ebx, esi, edi, ebp."""
    a.label("horde_copy")
    a.emit(0x55, 0x8B, 0xEC)  # push ebp / mov ebp, esp
    a.emit(0x81, 0xEC, u32(_H_FRAME))  # sub esp, frame
    a.emit(0x53, 0x56, 0x57)  # push ebx / esi / edi
    for arg, slot in ((8, _H_OLD_IFACE), (0xC, _H_NEW_IFACE)):
        a.emit(0x8B, 0x4D, arg)  # mov ecx, [ebp+arg]
        a.call_absolute(OBJECT_GET_HORDE_IFACE)
        a.emit(0x85, 0xC0)  # test eax, eax
        a.jcc(JE, "h_done")
        a.emit(0x89, _ebp_reg(EAX, slot))  # mov [slot], eax
    for arg, array, count in ((8, _H_OLD, _H_OLD_COUNT), (0xC, _H_NEW, _H_NEW_COUNT)):
        a.emit(0x8B, 0x75, arg)  # mov esi, [ebp+arg]
        a.emit(0x8D, _ebp_reg(EDI, array))  # lea edi, [array]
        a.call("h_collect")
        a.emit(0x89, _ebp_reg(EAX, count))  # mov [count], eax
        a.emit(0x85, 0xC0)  # test eax, eax
        a.jcc(JE, "h_done")
    a.emit(0x8B, _ebp_reg(EAX, _H_OLD_IFACE))  # mov eax, [old iface]
    a.emit(0x8B, 0x88, u32(HORDE_IFACE_LEADER_ID))  # mov ecx, [eax+leader]
    a.emit(0x89, _ebp_reg(ECX, _H_OLD_LEADER))
    a.emit(0x8B, 0x88, u32(HORDE_IFACE_BANNER_CARRIER_ID))  # mov ecx, [eax+banner]
    a.emit(0x89, _ebp_reg(ECX, _H_OLD_BANNER))
    a.emit(0x83, _ebp_reg(4, _H_OLD_NEXT), 0x00)  # and dword [old next], 0
    a.emit(0x33, 0xDB)  # xor ebx, ebx                ; new member index

    a.label("h_pair_loop")
    a.emit(0x3B, _ebp_reg(EBX, _H_NEW_COUNT))  # cmp ebx, [new count]
    a.jcc(JAE, "h_sync")
    a.emit(0x8B, _array(EDI, EBX, _H_NEW))  # mov edi, [new + ebx*4]
    a.emit(0x8B, 0x47, OBJECT_ID)  # mov eax, [edi+0x74]
    a.emit(0x8B, _ebp_reg(ECX, _H_NEW_IFACE))  # mov ecx, [new iface]
    a.emit(0x3B, 0x81, u32(HORDE_IFACE_LEADER_ID))  # cmp eax, [ecx+leader]
    a.jcc(JNE, "h_not_leader")
    a.emit(0x8B, _ebp_reg(EAX, _H_OLD_LEADER))  # mov eax, [old leader]
    a.call("h_find")
    a.jmp("h_have")
    a.label("h_not_leader")
    a.emit(0x3B, 0x81, u32(HORDE_IFACE_BANNER_CARRIER_ID))  # cmp eax, [ecx+banner]
    a.jcc(JNE, "h_ordinary")
    a.emit(0x8B, _ebp_reg(EAX, _H_OLD_BANNER))  # mov eax, [old banner]
    a.call("h_find")
    a.jmp("h_have")
    a.label("h_ordinary")
    a.call("h_next")
    a.label("h_have")
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JNE, "h_paired")
    a.emit(0x57)  # push edi
    a.emit(0x8B, _ebp_reg(ECX, _H_NEW_IFACE))  # mov ecx, [new iface]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x50, HORDE_IFACE_REMOVE_MEMBER_SLOT)  # call [eax+0x34]   leaves the horde
    a.emit(0x57)  # push edi
    a.emit(0x8B, 0x0D, u32(THE_GAME_LOGIC))  # mov ecx, [TheGameLogic]
    a.call_absolute(GAME_LOGIC_DESTROY_OBJECT)
    a.emit(0x83, _array(4, EBX, _H_NEW), 0x00)  # and dword [new + ebx*4], 0   ; gone
    a.jmp("h_pair_next")
    a.label("h_paired")
    a.call("h_member")
    a.label("h_pair_next")
    a.emit(0x43)  # inc ebx
    a.jmp("h_pair_loop")

    # Sync: every kept member to its group account, the horde to the highest, feedback off.
    a.label("h_sync")
    a.emit(0x8B, 0x45, 0x0C)  # mov eax, [ebp+0xc]        ; the new horde
    a.emit(0x8B, 0x80, u32(OBJECT_EXPERIENCE_TRACKER))  # mov eax, [eax+0x26c]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "h_done")
    a.emit(0x0F, 0xB6, 0x48, EXPERIENCE_TRACKER_FEEDBACK)  # movzx ecx, byte [eax+0x3c]
    a.emit(0x89, _ebp_reg(ECX, _H_FEEDBACK))
    a.emit(0xC6, 0x40, EXPERIENCE_TRACKER_FEEDBACK, 0x00)  # mov byte [eax+0x3c], 0
    a.emit(0x33, 0xDB)  # xor ebx, ebx
    a.label("h_sync_loop")
    a.emit(0x3B, _ebp_reg(EBX, _H_NEW_COUNT))  # cmp ebx, [new count]
    a.jcc(JAE, "h_sync_end")
    a.emit(0x8B, _array(EAX, EBX, _H_NEW))  # mov eax, [new + ebx*4]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "h_sync_next")
    a.emit(0x6A, 0x00)  # push 0                       ; delta 0.0
    a.emit(0x50)  # push eax                      ; member
    a.emit(0x8B, _ebp_reg(ECX, _H_NEW_IFACE))  # mov ecx, [new iface]
    a.call_absolute(HORDE_EXPERIENCE_ADD)
    a.label("h_sync_next")
    a.emit(0x43)  # inc ebx
    a.jmp("h_sync_loop")
    a.label("h_sync_end")
    a.emit(0x8B, 0x45, 0x0C)  # mov eax, [ebp+0xc]
    a.emit(0x8B, 0x80, u32(OBJECT_EXPERIENCE_TRACKER))  # mov eax, [eax+0x26c]
    a.emit(0x8B, _ebp_reg(ECX, _H_FEEDBACK))  # mov ecx, [saved feedback]
    a.emit(0x88, 0x48, EXPERIENCE_TRACKER_FEEDBACK)  # mov [eax+0x3c], cl
    a.label("h_done")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi / esi / ebx
    a.emit(0xC9)  # leave
    a.emit(0xC2, 0x08, 0x00)  # ret 8

    # h_collect: esi an object, edi an array; eax = how many contained objects were copied.
    a.label("h_collect")
    a.emit(0x33, 0xC0)  # xor eax, eax
    a.emit(0x8B, 0x8E, u32(OBJECT_CONTAIN))  # mov ecx, [esi+0x258]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "h_collect_end")
    a.emit(0x8B, 0x49, CONTAIN_ITEM_LIST)  # mov ecx, [ecx+0x34]   ; the sentinel
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "h_collect_end")
    a.emit(0x8B, 0x11)  # mov edx, [ecx]              ; the first node
    a.label("h_collect_loop")
    a.emit(0x3B, 0xD1)  # cmp edx, ecx
    a.jcc(JE, "h_collect_end")
    a.emit(0x83, 0xF8, HORDE_MEMBER_CAP)  # cmp eax, cap
    a.jcc(JAE, "h_collect_end")
    a.emit(0xFF, 0x72, CONTAIN_ITEM_LIST_NODE_OBJECT)  # push [edx+8]
    a.emit(0x8F, 0x04, 0x87)  # pop [edi+eax*4]
    a.emit(0x40)  # inc eax
    a.emit(0x8B, 0x12)  # mov edx, [edx]
    a.jmp("h_collect_loop")
    a.label("h_collect_end")
    a.emit(0xC3)  # ret

    # h_find: eax an ObjectID; esi = the old member with it, or NULL (and NULL for id 0).
    a.label("h_find")
    a.emit(0x33, 0xF6)  # xor esi, esi
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "h_find_end")
    a.emit(0x33, 0xC9)  # xor ecx, ecx
    a.label("h_find_loop")
    a.emit(0x3B, _ebp_reg(ECX, _H_OLD_COUNT))  # cmp ecx, [old count]
    a.jcc(JAE, "h_find_end")
    a.emit(0x8B, _array(EDX, ECX, _H_OLD))  # mov edx, [old + ecx*4]
    a.emit(0x39, 0x42, OBJECT_ID)  # cmp [edx+0x74], eax
    a.jcc(JE, "h_find_hit")
    a.emit(0x41)  # inc ecx
    a.jmp("h_find_loop")
    a.label("h_find_hit")
    a.emit(0x8B, 0xF2)  # mov esi, edx
    a.label("h_find_end")
    a.emit(0xC3)  # ret

    # h_next: esi = the next old member that is neither the old leader nor its banner carrier.
    a.label("h_next")
    a.emit(0x33, 0xF6)  # xor esi, esi
    a.label("h_next_loop")
    a.emit(0x8B, _ebp_reg(ECX, _H_OLD_NEXT))  # mov ecx, [old next]
    a.emit(0x3B, _ebp_reg(ECX, _H_OLD_COUNT))  # cmp ecx, [old count]
    a.jcc(JAE, "h_next_end")
    a.emit(0xFF, _ebp_reg(0, _H_OLD_NEXT))  # inc dword [old next]
    a.emit(0x8B, _array(EDX, ECX, _H_OLD))  # mov edx, [old + ecx*4]
    a.emit(0x8B, 0x42, OBJECT_ID)  # mov eax, [edx+0x74]
    a.emit(0x3B, _ebp_reg(EAX, _H_OLD_LEADER))  # cmp eax, [old leader]
    a.jcc(JE, "h_next_loop")
    a.emit(0x3B, _ebp_reg(EAX, _H_OLD_BANNER))  # cmp eax, [old banner]
    a.jcc(JE, "h_next_loop")
    a.emit(0x8B, 0xF2)  # mov esi, edx
    a.label("h_next_end")
    a.emit(0xC3)  # ret

    # h_member: esi the old member, edi its new partner. Health ratio, then the group account.
    a.label("h_member")
    a.emit(0x8B, 0x8E, u32(OBJECT_BODY_MODULE))  # mov ecx, [esi+0x25c]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "h_member_xp")
    a.emit(0x83, 0xBF, u32(OBJECT_BODY_MODULE), 0x00)  # cmp dword [edi+0x25c], 0
    a.jcc(JE, "h_member_xp")
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x50, BODY_GET_HEALTH_RATIO_SLOT)  # call [eax+0x14]   old ratio
    a.emit(0x51)  # push ecx
    a.emit(0xD9, 0x1C, 0x24)  # fstp dword [esp]
    a.emit(0x8B, 0x8F, u32(OBJECT_BODY_MODULE))  # mov ecx, [edi+0x25c]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x50, BODY_GET_MAX_HEALTH_SLOT)  # call [eax+0x1c]   new maximum
    a.emit(0xD8, 0x0C, 0x24)  # fmul dword [esp]
    a.emit(0xD9, 0x1C, 0x24)  # fstp dword [esp]
    a.emit(0x0F, 0x57, 0xC0)  # xorps xmm0, xmm0
    a.emit(0x0F, 0x2F, 0x04, 0x24)  # comiss xmm0, [esp]
    a.jcc(JAE, "h_member_hnone")
    a.emit(0x8B, 0x8F, u32(OBJECT_BODY_MODULE))  # mov ecx, [edi+0x25c]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x90, u32(BODY_SET_HEALTH_SLOT))  # call [eax+0xac]   pops the value
    a.jmp("h_member_xp")
    a.label("h_member_hnone")
    a.emit(0x59)  # pop ecx
    a.label("h_member_xp")
    a.emit(0x8B, 0x86, u32(OBJECT_EXPERIENCE_TRACKER))  # mov eax, [esi+0x26c]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "h_member_end")
    a.emit(0xFF, 0x70, EXPERIENCE_TRACKER_XP)  # push [eax+0x10]       ; the partner's experience
    a.emit(0x8B, 0x47, OBJECT_THING_TEMPLATE)  # mov eax, [edi+4]
    a.emit(
        0x0F, 0xB7, 0x80, u32(OBJECT_TEMPLATE_EXPERIENCE_GROUP_OFFSET)
    )  # movzx eax, word [+0x5e8]
    a.emit(0x89, _ebp_reg(EAX, _H_KEY))  # mov [key], eax
    a.emit(0x8D, _ebp_reg(EAX, _H_KEY))  # lea eax, [key]
    a.emit(0x50)  # push eax
    a.emit(0x8B, _ebp_reg(ECX, _H_NEW_IFACE))  # mov ecx, [new iface]
    a.emit(0x81, 0xC1, u32(HORDE_EXPERIENCE_GROUPS_OFFSET))  # add ecx, 0x13c
    a.call_absolute(HORDE_EXPERIENCE_GROUP_LOOKUP_OR_INSERT)  # eax = &account
    a.emit(0xF3, 0x0F, 0x10, 0x04, 0x24)  # movss xmm0, [esp]
    a.emit(0x59)  # pop ecx
    a.emit(0x0F, 0x2F, 0x00)  # comiss xmm0, [eax]
    a.jcc(JBE, "h_member_end")  # never lower an account
    a.emit(0xF3, 0x0F, 0x11, 0x00)  # movss [eax], xmm0
    a.label("h_member_end")
    a.emit(0xC3)  # ret


def _assemble(code_va: int) -> Asm:
    a = Asm(code_va)

    # parse: `(ini, instance, store, nameList)`, `__cdecl` like every field parser. The stock
    # bit-string parser writes a dword, and the field is one byte, so it parses into a stack temp
    # seeded from the byte (for `+NAME` / `-NAME`) and the low byte is stored back.
    a.label("parse")
    a.emit(0x55)  # push ebp
    a.emit(0x8B, 0xEC)  # mov ebp, esp
    a.emit(0x51)  # push ecx                       ; the temp, [ebp-4]
    a.emit(0x8B, 0x45, 0x10)  # mov eax, [ebp+0x10]   ; store
    a.emit(0x0F, 0xB6, 0x00)  # movzx eax, byte [eax]
    a.emit(0x89, 0x45, 0xFC)  # mov [ebp-4], eax
    a.emit(0xFF, 0x75, 0x14)  # push [ebp+0x14]       ; nameList
    a.emit(0x8D, 0x45, 0xFC)  # lea eax, [ebp-4]
    a.emit(0x50)  # push eax                       ; the temp as the store
    a.emit(0xFF, 0x75, 0x0C)  # push [ebp+0xc]        ; instance
    a.emit(0xFF, 0x75, 0x08)  # push [ebp+8]          ; ini
    a.call_absolute(INI_PARSE_BIT_STRING_32)
    a.emit(0x83, 0xC4, 0x10)  # add esp, 0x10
    a.emit(0x8B, 0x45, 0x10)  # mov eax, [ebp+0x10]
    a.emit(0x8A, 0x4D, 0xFC)  # mov cl, [ebp-4]
    a.emit(0x88, 0x08)  # mov [eax], cl
    a.emit(0xC9)  # leave
    a.emit(0xC3)  # ret

    # transfer(old, new, flags): `__stdcall`, `ret 0xc`. Keeps ebx, esi, edi and ebp.
    a.label("transfer")
    a.emit(0x55)  # push ebp
    a.emit(0x8B, 0xEC)  # mov ebp, esp
    a.emit(0x53, 0x56, 0x57)  # push ebx / esi / edi
    a.emit(0x8B, 0x75, 0x08)  # mov esi, [ebp+8]      ; old
    a.emit(0x8B, 0x7D, 0x0C)  # mov edi, [ebp+0xc]    ; new
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JE, "done")
    a.emit(0x85, 0xFF)  # test edi, edi
    a.jcc(JE, "done")

    a.emit(0xF6, 0x45, 0x10, FLAG_EXPERIENCE)  # test byte [ebp+0x10], EXPERIENCE
    a.jcc(JE, "upgrades")
    a.emit(0x8B, 0x86, u32(OBJECT_EXPERIENCE_TRACKER))  # mov eax, [esi+0x26c]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "upgrades")
    a.emit(0x8B, 0x8F, u32(OBJECT_EXPERIENCE_TRACKER))  # mov ecx, [edi+0x26c]
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "upgrades")
    a.emit(0xF3, 0x0F, 0x10, 0x40, EXPERIENCE_TRACKER_XP)  # movss xmm0, [eax+0x10]  old XP
    a.emit(0x0F, 0x2F, 0x41, EXPERIENCE_TRACKER_XP)  # comiss xmm0, [ecx+0x10]       new XP
    a.jcc(JBE, "upgrades")  # never lower it
    a.emit(0x0F, 0xB6, 0x59, EXPERIENCE_TRACKER_FEEDBACK)  # movzx ebx, byte [ecx+0x3c]
    a.emit(0xC6, 0x41, EXPERIENCE_TRACKER_FEEDBACK, 0x00)  # mov byte [ecx+0x3c], 0
    a.emit(0x6A, 0x01)  # push 1
    a.emit(0x83, 0xEC, 0x04)  # sub esp, 4
    a.emit(0xF3, 0x0F, 0x11, 0x04, 0x24)  # movss [esp], xmm0
    a.call_absolute(EXPERIENCE_TRACKER_SET_ABSOLUTE)  # ecx = the new tracker
    a.emit(0x8B, 0x8F, u32(OBJECT_EXPERIENCE_TRACKER))  # mov ecx, [edi+0x26c]
    a.emit(0x88, 0x59, EXPERIENCE_TRACKER_FEEDBACK)  # mov [ecx+0x3c], bl

    a.label("upgrades")
    a.emit(0xF6, 0x45, 0x10, FLAG_UPGRADES)  # test byte [ebp+0x10], UPGRADES
    a.jcc(JE, "health")
    a.emit(0xA1, u32(THE_UPGRADE_CENTER))  # mov eax, [TheUpgradeCenter]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "health")
    a.emit(0x8B, 0x58, UPGRADE_CENTER_LIST)  # mov ebx, [eax+0xc]   ; first UpgradeTemplate
    a.label("walk")
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JE, "health")
    a.emit(0x8B, 0x53, UPGRADE_TEMPLATE_INDEX)  # mov edx, [ebx+0x38]  ; its mask index
    a.emit(0x8B, 0xCA)  # mov ecx, edx
    a.emit(0x83, 0xE1, 0x1F)  # and ecx, 31
    a.emit(0xB8, u32(1))  # mov eax, 1
    a.emit(0xD3, 0xE0)  # shl eax, cl
    a.emit(0xC1, 0xEA, 0x05)  # shr edx, 5
    a.emit(0x83, 0xFA, PLAYER_COMPLETED_UPGRADE_MASK_WORDS)  # cmp edx, 36
    a.jcc(JAE, "next")
    a.emit(0x85, 0x84, 0x96, u32(OBJECT_UPGRADE_MASK))  # test [esi+edx*4+0x28c], eax
    a.jcc(JE, "next")  # the old object does not have it
    a.emit(0x85, 0x84, 0x97, u32(OBJECT_UPGRADE_MASK))  # test [edi+edx*4+0x28c], eax
    a.jcc(JNE, "next")  # the new object already has it
    a.emit(0x53)  # push ebx
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(OBJECT_GIVE_UPGRADE)
    a.label("next")
    a.emit(0x8B, 0x5B, UPGRADE_TEMPLATE_NEXT)  # mov ebx, [ebx+0x64]
    a.jmp("walk")

    # HEALTH: the new body at the old body's health ratio of its own maximum. After experience and
    # upgrades, so the maximum already carries the level and upgrade bonuses. The ratio is parked
    # on the stack across the second call; a ratio of zero or less sets nothing.
    a.label("health")
    a.emit(0xF6, 0x45, 0x10, FLAG_HEALTH)  # test byte [ebp+0x10], HEALTH
    a.jcc(JE, "horde")
    a.emit(0x8B, 0x8E, u32(OBJECT_BODY_MODULE))  # mov ecx, [esi+0x25c]  old body
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "horde")
    a.emit(0x8B, 0x9F, u32(OBJECT_BODY_MODULE))  # mov ebx, [edi+0x25c]  new body
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JE, "horde")
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x50, BODY_GET_HEALTH_RATIO_SLOT)  # call [eax+0x14]   old ratio
    a.emit(0x51)  # push ecx
    a.emit(0xD9, 0x1C, 0x24)  # fstp dword [esp]
    a.emit(0x8B, 0xCB)  # mov ecx, ebx
    a.emit(0x8B, 0x03)  # mov eax, [ebx]
    a.emit(0xFF, 0x50, BODY_GET_MAX_HEALTH_SLOT)  # call [eax+0x1c]   new maximum
    a.emit(0xD8, 0x0C, 0x24)  # fmul dword [esp]
    a.emit(0xD9, 0x1C, 0x24)  # fstp dword [esp]
    a.emit(0x0F, 0x57, 0xC0)  # xorps xmm0, xmm0
    a.emit(0x0F, 0x2F, 0x04, 0x24)  # comiss xmm0, [esp]
    a.jcc(JAE, "health_none")  # 0 >= health: leave it
    a.emit(0x8B, 0xCB)  # mov ecx, ebx
    a.emit(0x8B, 0x03)  # mov eax, [ebx]
    a.emit(0xFF, 0x90, u32(BODY_SET_HEALTH_SLOT))  # call [eax+0xac]   setHealth, pops the value
    a.jmp("horde")
    a.label("health_none")
    a.emit(0x59)  # pop ecx

    # RALLY: the old exit interface's rally point, set on the new one through the same slot a
    # player's rally order uses.
    # HORDE: the old horde's members, member by member (see `_horde`).
    a.label("horde")
    a.emit(0xF6, 0x45, 0x10, FLAG_HORDE)  # test byte [ebp+0x10], HORDE
    a.jcc(JE, "rally")
    a.emit(0x57)  # push edi                      ; new
    a.emit(0x56)  # push esi                      ; old
    a.call("horde_copy")

    a.label("rally")
    a.emit(0xF6, 0x45, 0x10, FLAG_RALLY)  # test byte [ebp+0x10], RALLY
    a.jcc(JE, "production")
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(OBJECT_GET_EXIT_INTERFACE)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "production")
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.emit(0x8B, 0x00)  # mov eax, [eax]
    a.emit(0xFF, 0x50, EXIT_INTERFACE_GET_RALLY_POINT_SLOT)  # call [eax+0x20]  Coord3D * or NULL
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "production")
    a.emit(0x8B, 0xD8)  # mov ebx, eax
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(OBJECT_GET_EXIT_INTERFACE)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "production")
    a.emit(0x53)  # push ebx
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.emit(0x8B, 0x00)  # mov eax, [eax]
    a.emit(0xFF, 0x50, EXIT_INTERFACE_SET_RALLY_POINT_SLOT)  # call [eax+0x1c]

    # PRODUCTION: the old producer's queue moves to the new one with its progress and what was
    # paid, so nothing is refunded and nothing is lost. Each entry is unlinked and re-appended
    # through the stock `append`, which also wakes the new module. An entry whose finished unit is
    # held at the old door stays behind (the door state can't move). The new id counter is raised
    # to the old one's, so ids it mints later can't collide with a moved entry's.
    a.label("production")
    a.emit(0xF6, 0x45, 0x10, FLAG_PRODUCTION)  # test byte [ebp+0x10], PRODUCTION
    a.jcc(JE, "selection")
    a.emit(0x6A, 0x00)  # push 0
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(OBJECT_GET_PRODUCTION_UPDATE_INTERFACE)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "selection")
    a.emit(0x8B, 0xD8)  # mov ebx, eax                ; old interface
    a.emit(0x6A, 0x00)  # push 0
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(OBJECT_GET_PRODUCTION_UPDATE_INTERFACE)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "selection")
    a.emit(0x3B, 0xC3)  # cmp eax, ebx
    a.jcc(JE, "selection")
    a.emit(0x50)  # push eax                      ; [ebp-0x10] new interface
    a.emit(0x8B, 0x4B, PRODUCTION_INTERFACE_ID_COUNTER)  # mov ecx, [ebx+0x10]
    a.emit(0x3B, 0x48, PRODUCTION_INTERFACE_ID_COUNTER)  # cmp ecx, [eax+0x10]
    a.jcc(JBE, "prod_detach")
    a.emit(0x89, 0x48, PRODUCTION_INTERFACE_ID_COUNTER)  # mov [eax+0x10], ecx
    a.label("prod_detach")
    a.emit(0x8B, 0x4B, _HEAD)  # mov ecx, [ebx+8]           ; the old list
    a.emit(0x33, 0xD2)  # xor edx, edx
    a.emit(0x89, 0x53, _HEAD)  # mov [ebx+8], edx
    a.emit(0x89, 0x53, _TAIL)  # mov [ebx+0xc], edx
    a.emit(0x89, 0x53, PRODUCTION_INTERFACE_QUEUE_LENGTH)  # mov [ebx+0x14], edx
    a.label("prod_walk")
    a.emit(0x85, 0xC9)  # test ecx, ecx
    a.jcc(JE, "prod_end")
    a.emit(0xFF, 0x71, PRODUCTION_ENTRY_NEXT)  # push [ecx+0x48]   ; the next entry
    a.emit(0x83, 0x61, PRODUCTION_ENTRY_NEXT, 0x00)  # and dword [ecx+0x48], 0
    a.emit(0x83, 0x61, PRODUCTION_ENTRY_PREV, 0x00)  # and dword [ecx+0x4c], 0
    a.emit(0x8B, 0x45, 0xF0)  # mov eax, [ebp-0x10]      ; new interface
    a.emit(0xF3, 0x0F, 0x10, 0x41, PRODUCTION_ENTRY_PROGRESS)  # movss xmm0, [ecx+0x14]
    a.emit(0x0F, 0x2F, 0x05, u32(FLOAT_HUNDRED))  # comiss xmm0, [100.0]
    a.jcc(JB, "prod_append")
    a.emit(0x83, 0xBB, u32(PRODUCTION_INTERFACE_DOOR_HOLD), 0x00)  # cmp dword [ebx+0x100], 0
    a.jcc(JE, "prod_append")
    a.emit(0x8B, 0xC3)  # mov eax, ebx               ; held at the old door: put it back
    a.label("prod_append")
    a.emit(0x51)  # push ecx                      ; the entry
    a.emit(0x8D, 0x48, 0x100 - PRODUCTION_INTERFACE_OFFSET)  # lea ecx, [eax-0x20]  the module
    a.call_absolute(PRODUCTION_QUEUE_APPEND)
    a.emit(0x59)  # pop ecx                       ; the next entry
    a.jmp("prod_walk")
    a.label("prod_end")
    a.emit(0x58)  # pop eax

    # SELECTION: what the summon swap does in stock, but only on the owner's machine - the control
    # group the old object was in gains the new one, and a selected old object hands its selection
    # over. Both post the same messages a player's own click would.
    a.label("selection")
    a.emit(0xF6, 0x45, 0x10, FLAG_SELECTION)  # test byte [ebp+0x10], SELECTION
    a.jcc(JE, "done")
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(OBJECT_IS_LOCALLY_CONTROLLED)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(OBJECT_GET_CONTROLLING_PLAYER)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "select")
    a.emit(0x56)  # push esi
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.call_absolute(PLAYER_FIND_SQUAD)
    a.emit(0x83, 0xF8, 0xFF)  # cmp eax, -1
    a.jcc(JE, "select")
    a.emit(0x05, u32(MSG_ADD_TO_TEAM0))  # add eax, MSG_ADD_TO_TEAM0
    a.emit(0x50)  # push eax
    a.emit(0x8B, 0x0D, u32(THE_MESSAGE_STREAM))  # mov ecx, [TheMessageStream]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x50, APPEND_MESSAGE_VTABLE_SLOT)  # call [eax+0x48]
    a.emit(0xFF, 0x77, OBJECT_ID)  # push [edi+0x74]
    a.emit(0x8B, 0xC8)  # mov ecx, eax
    a.call_absolute(_APPEND_OBJECT_ID)
    a.label("select")
    a.emit(0x8B, 0xCE)  # mov ecx, esi
    a.call_absolute(OBJECT_GET_DRAWABLE)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")
    a.emit(0x80, 0xB8, u32(DRAWABLE_SELECTED), 0x00)  # cmp byte [eax+0x43c], 0
    a.jcc(JE, "done")
    a.emit(0x8B, 0xD8)  # mov ebx, eax                ; the old drawable
    a.emit(0x8B, 0xCF)  # mov ecx, edi
    a.call_absolute(OBJECT_GET_DRAWABLE)
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")
    a.emit(0x50)  # push eax                      ; the new drawable, for the select below
    a.emit(0x53)  # push ebx
    a.emit(0x8B, 0x0D, u32(THE_IN_GAME_UI))  # mov ecx, [TheInGameUI]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x90, u32(IN_GAME_UI_DESELECT_DRAWABLE_SLOT))  # call [eax+0x10c]
    a.emit(0x68, u32(MSG_CREATE_SELECTED_GROUP))  # push MSG_CREATE_SELECTED_GROUP
    a.emit(0x8B, 0x0D, u32(THE_MESSAGE_STREAM))  # mov ecx, [TheMessageStream]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x50, APPEND_MESSAGE_VTABLE_SLOT)  # call [eax+0x48]
    a.emit(0x8B, 0xD8)  # mov ebx, eax
    a.emit(0x6A, 0x00)  # push 0                       ; add to the current selection
    a.emit(0x8B, 0xCB)  # mov ecx, ebx
    a.call_absolute(_APPEND_BOOLEAN)
    a.emit(0xFF, 0x77, OBJECT_ID)  # push [edi+0x74]
    a.emit(0x8B, 0xCB)  # mov ecx, ebx
    a.call_absolute(_APPEND_OBJECT_ID)
    a.emit(0x8B, 0x0D, u32(THE_IN_GAME_UI))  # mov ecx, [TheInGameUI]
    a.emit(0x8B, 0x01)  # mov eax, [ecx]
    a.emit(0xFF, 0x90, u32(IN_GAME_UI_SELECT_DRAWABLE_SLOT))  # call [eax+0x108]  (the new drawable)
    a.label("done")
    a.emit(0x5F, 0x5E, 0x5B)  # pop edi / esi / ebx
    a.emit(0x5D)  # pop ebp
    a.emit(0xC2, 0x0C, 0x00)  # ret 0xc

    _horde(a)

    # rsu_ctor: from `ReplaceSelfUpgradeModuleData`'s constructor, `edi` the ModuleData.
    a.label("rsu_ctor")
    a.emit(0xC6, 0x87, u32(REPLACE_SELF_FREE_OFFSET), 0x00)  # mov byte [edi+0x137], 0
    a.emit(REPLACE_SELF_MODULE_DATA_LIST_INIT_BYTES)  # lea esi, [edi+0x138]   (stock)
    a.jmp_absolute(REPLACE_SELF_MODULE_DATA_LIST_INIT_RESUME)

    # rsu_replace: per replacement in `upgradeImplementation`. eax, ecx and edx are dead here:
    # the displaced pair rewrites eax and ecx, and the call after them owns edx.
    a.label("rsu_replace")
    a.emit(0x8B, 0x45, struct.pack("<b", REPLACE_SELF_FRAME_MODULE_DATA))  # mov eax, [ebp-0x50]
    a.emit(0x0F, 0xB6, 0x80, u32(REPLACE_SELF_FREE_OFFSET))  # movzx eax, byte [eax+0x137]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "rsu_stock")
    a.emit(0x50)  # push eax                      ; flags
    a.emit(0x57)  # push edi                      ; the new object
    a.emit(0xFF, 0x76, struct.pack("<b", REPLACE_SELF_OLD_OBJECT_DISP))  # push [esi-8]  ; old
    a.call("transfer")
    a.label("rsu_stock")
    a.emit(REPLACE_SELF_NAME_COPY_BYTES)  # lea eax, [ebp-0x24] / lea ecx, [edi+0x88]
    a.jmp_absolute(REPLACE_SELF_NAME_COPY_RESUME)

    # summon_replace: after the stock experience copy, `esi` the new object, `edi` the old.
    a.label("summon_replace")
    a.emit(SUMMON_REPLACEMENT_XP_RESTORE_BYTES)  # mov eax,[esi+0x26c] / mov byte [eax+0x3c],1
    a.emit(0x8B, 0x45, struct.pack("<b", SUMMON_REPLACEMENT_FRAME_MODULE))  # mov eax, [ebp-0x18]
    a.emit(0x8B, 0x40, 0x04)  # mov eax, [eax+4]                 ; ModuleData
    a.emit(0x0F, 0xB6, 0x80, u32(SUMMON_REPLACEMENT_FREE_OFFSET))  # movzx eax, byte [eax+0xe6]
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "summon_stock")
    a.emit(0x50)  # push eax                      ; kept for the HEALTH test below
    a.emit(0x24, 0xFF & ~FLAG_SELECTION)  # and al, ~SELECTION  ; the swap already does it
    a.emit(0x50)  # push eax                      ; flags
    a.emit(0x56)  # push esi                      ; the new object
    a.emit(0x57)  # push edi                      ; the old object
    a.call("transfer")
    a.emit(0x58)  # pop eax
    a.emit(0xA8, FLAG_HEALTH)  # test al, HEALTH
    a.jcc(JE, "summon_stock")
    a.jmp_absolute(SUMMON_REPLACEMENT_HEALTH_COPY_END)  # the ratio stands: skip the absolute copy
    a.label("summon_stock")
    a.jmp_absolute(SUMMON_REPLACEMENT_XP_RESTORE_RESUME)
    return a


_ROUTINES = ("parse", "transfer", "horde_copy", "rsu_ctor", "rsu_replace", "summon_replace")


def build_section(base_va: int) -> bytes:
    """The whole cave: strings, the name list, both tables, then the code."""
    pieces = _layout(base_va)
    a = _assemble(pieces.code)
    parse_va = a.label_va("parse")
    blob = bytearray(_strings())
    blob += bytes(pieces.name_list - (base_va + len(blob)))
    blob += b"".join(u32(va) for va in pieces.names) + u32(0)
    blob += _table(
        REPLACE_SELF_FIELD_TABLE_STOCK, _RSU_ROWS, pieces, parse_va, REPLACE_SELF_FREE_OFFSET
    )
    blob += _table(
        SUMMON_REPLACEMENT_FIELD_TABLE_STOCK,
        _SUMMON_ROWS,
        pieces,
        parse_va,
        SUMMON_REPLACEMENT_FREE_OFFSET,
    )
    assert base_va + len(blob) == pieces.code, "the cave layout and its addresses disagree"
    return bytes(blob) + a.finish()


def layout(base_va: int) -> dict[str, int]:
    """Where each table and routine lands in a section based at `base_va`."""
    pieces = _layout(base_va)
    a = _assemble(pieces.code)
    return {
        "keyword": pieces.keyword,
        "name_list": pieces.name_list,
        "rsu_table": pieces.rsu_table,
        "summon_table": pieces.summon_table,
        **{name: a.label_va(name) for name in _ROUTINES},
    }


def _edits(base_va: int) -> list[tuple[int, bytes, bytes, str]]:
    """Every in-place edit as `(va, stock, replacement, note)`."""
    at = layout(base_va)
    return [
        (
            REPLACE_SELF_FIELD_TABLE_PUSH,
            REPLACE_SELF_FIELD_TABLE_PUSH_BYTES,
            b"\x68" + u32(at["rsu_table"]),
            f"ReplaceSelfUpgrade field table -> {SECTION_NAME} (+ {KEYWORD})",
        ),
        (
            REPLACE_SELF_MODULE_DATA_LIST_INIT,
            REPLACE_SELF_MODULE_DATA_LIST_INIT_BYTES,
            jmp_rel32(
                REPLACE_SELF_MODULE_DATA_LIST_INIT,
                at["rsu_ctor"],
                len(REPLACE_SELF_MODULE_DATA_LIST_INIT_BYTES),
            ),
            f"ReplaceSelfUpgradeModuleData ctor -> {KEYWORD} defaults to empty",
        ),
        (
            REPLACE_SELF_NAME_COPY,
            REPLACE_SELF_NAME_COPY_BYTES,
            jmp_rel32(REPLACE_SELF_NAME_COPY, at["rsu_replace"], len(REPLACE_SELF_NAME_COPY_BYTES)),
            "ReplaceSelfUpgrade::upgradeImplementation -> transfer to each replacement",
        ),
        (
            SUMMON_REPLACEMENT_FIELD_TABLE_PUSH,
            SUMMON_REPLACEMENT_FIELD_TABLE_PUSH_BYTES,
            b"\x68" + u32(at["summon_table"]),
            f"SummonReplacementSpecialAbilityUpdate field table -> {SECTION_NAME} (+ {KEYWORD})",
        ),
        (
            SUMMON_REPLACEMENT_DEFAULT_STORES,
            SUMMON_REPLACEMENT_DEFAULT_STORES_BYTES,
            rewritten_summon_defaults(),
            f"SummonReplacementSpecialAbilityUpdateModuleData ctor -> {KEYWORD} defaults to empty",
        ),
        (
            SUMMON_REPLACEMENT_XP_RESTORE,
            SUMMON_REPLACEMENT_XP_RESTORE_BYTES,
            jmp_rel32(
                SUMMON_REPLACEMENT_XP_RESTORE,
                at["summon_replace"],
                len(SUMMON_REPLACEMENT_XP_RESTORE_BYTES),
            ),
            "SummonReplacementSpecialAbilityUpdate replacement -> transfer upgrades",
        ),
    ]


class ReplacementTransferPatch(Patch):
    name = "replacement-transfer"
    author = "officialNecro"
    description = (
        "Add TransferToReplacement to ReplaceSelfUpgrade and "
        "SummonReplacementSpecialAbilityUpdate: write TransferToReplacement = UPGRADES EXPERIENCE "
        "HEALTH SELECTION RALLY PRODUCTION HORDE (any subset) and the replacement keeps the old "
        "object's "
        "object upgrades (granted, so its own upgrade modules fire), its experience and level "
        "(only ever raised), its health ratio, its control group and selection, its rally point "
        "and its production queue; a horde keeps its surviving member count, each member's health "
        "ratio and member experience. Empty, the default, is stock. Logic-side: every peer needs "
        "the same binary. A mod that writes the keyword will not load on an unpatched binary"
    )

    def apply(self, data: bytearray) -> None:
        for va, expected in ANCHORS.items():
            self._check_stock(data, va, expected)
        self._check_stock(data, REPLACE_SELF_FIELD_TABLE, REPLACE_SELF_FIELD_TABLE_STOCK)
        self._check_stock(
            data, SUMMON_REPLACEMENT_FIELD_TABLE, SUMMON_REPLACEMENT_FIELD_TABLE_STOCK
        )
        for va, stock, _new, _note in _edits(0):  # the stock half does not depend on the base
            self._check_stock(data, va, stock)
        base_va = allocate_section(data, SECTION_NAME, build_section, _CHARACTERISTICS)
        for va, stock, new, note in _edits(base_va):
            apply_byte_patch(data, file_offset(data, va), stock, new, note)

    @staticmethod
    def _check_stock(data: bytes | bytearray, va: int, expected: bytes) -> None:
        off = file_offset(data, va)
        got = bytes(data[off : off + len(expected)])
        if got != expected:
            raise ValueError(
                f"{va:#010x} holds {got.hex()}, expected {expected.hex()} - the file is not "
                "the expected build, or already carries this patch"
            )

    def ini_surface(self) -> Engine:
        """One flag list on each of the two modules. The names are this patch's own (`UPGRADES`,
        `EXPERIENCE`, ...), not an engine enum, so they are declared opaque; empty is stock."""
        return Engine(
            fields=tuple(
                FieldDelta(block, KEYWORD, "Opaque[]", None, self.name) for block in BLOCKS
            )
        )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        base_va, section_off, vsize = located
        problems: list[str] = []
        expected = build_section(base_va)
        got = bytes(data[section_off : section_off + len(expected)])
        if vsize < len(expected) or got != expected:
            problems.append(f"the {SECTION_NAME} cave is not the one this patch builds")
        for va, _stock, new, note in _edits(base_va):
            off = file_offset(data, va)
            here = bytes(data[off : off + len(new)])
            if here != new:
                problems.append(f"@{va:#010x}: {note} is not installed (holds {here.hex()})")
        return problems
