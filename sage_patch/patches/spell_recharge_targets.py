"""Let a `SpellRechargeModifierUpgrade` name the special powers it discounts.

Stock, the module is one float per player (`Player+0x718`): every active module writes it, and
`startPowerRecharge` multiplies it into any power flagged `RESPECT_RECHARGE_TIME_DISCOUNT` - the
whole spellbook at once. The patch adds `AffectedSpecialPowers = <power> ...`. A module that
declares it leaves the player's float and level counter alone and discounts only the powers it
names, whether or not they carry the flag. A module without it is stock.

The discount of a targeted module is not stored anywhere. When a power starts recharging, the
cave walks the owner's objects, counts the executed targeted modules that name the power (per
`ModuleData`, so three copies of one building are level 3 of that building's `Percentage` list),
and multiplies `1 + Percentage[level]` for each group into the cooldown. Nothing is added to the
`Player`, so save games, capture and deletion need no bookkeeping.

Derivation: `../docs/spell-recharge-targets.md`.
"""

from __future__ import annotations

import struct

from sage_ini.engine import Engine, FieldDelta

from ..addresses import (
    ASCII_STRING_CTOR,
    FLOAT_ONE,
    INI_NEXT_TOKEN_OR_NULL,
    OBJECT_GET_CONTROLLING_PLAYER,
    OBJECT_MODULE_LIST,
    OBJECT_STATUS,
    PLAYER_FOR_EACH_TEAM_OBJECT,
    THE_SPECIAL_POWER_STORE,
)
from ..asm import JAE, JE, JLE, JNE, Asm
from ..patcher import Patch
from ..utils import (
    allocate_section,
    apply_byte_patch,
    call_rel32,
    file_offset,
    find_section,
    jmp_rel32,
    read_cstring,
    u32,
)

__all__ = [
    "CAPACITY",
    "KEYWORD",
    "PATCHED_MODULEDATA_SIZE",
    "SECTION_NAME",
    "STOCK_FIELDS",
    "STOCK_MODULEDATA_SIZE",
    "SpellRechargeTargetsPatch",
]

KEYWORD = "AffectedSpecialPowers"

SECTION_NAME = ".sprtgt"
# CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE: the parser sets the
# "some module is targeted" flag in the cave.
SECTION_CHARACTERISTICS = 0xE0000060

#: `newModuleData`'s `push 0x14C` and its call to the `ModuleData` constructor.
MODULEDATA_SIZE_VA = 0x00650148
MODULEDATA_CTOR_CALL_VA = 0x00650160
MODULEDATA_CTOR_VA = 0x008BA1AB
STOCK_MODULEDATA_SIZE = 0x14C

#: The module's own field table, and the `push` in `buildFieldParse` that hands it to
#: `MultiIniFieldParse::add`. The upgrade-mux table is added before it, from a different push.
FIELD_TABLE_VA = 0x00C6F0D0
FIELD_TABLE_PUSH_VA = 0x008BA2AB
FIELD_ENTRY_SIZE = 16
STOCK_FIELDS = (
    ("Percentage", 0x138),
    ("StartsActive", 0x144),
    ("LabelForPalantirString", 0x148),
)
#: The keywords the upgrade-mux table contributes to the same `MultiIniFieldParse`, which is
#: searched first. `KEYWORD` must not be one of them.
MUX_FIELDS = (
    "TriggeredBy",
    "ConflictsWith",
    "RequiresAllTriggers",
    "RequiresAllConflictingTriggers",
    "Permanent",
    "CustomAnimAndDuration",
)

#: `Percentage`, a `vector<float>`: begin and end.
PERCENTAGE_BEGIN = 0x138
PERCENTAGE_END = 0x13C

#: The new `ModuleData` tail: how many powers are named, a scratch counter the discount walk
#: leaves at zero, and the resolved `SpecialPowerTemplate` pointers.
CAPACITY = 16
LIST_COUNT = STOCK_MODULEDATA_SIZE
LIST_SCRATCH = LIST_COUNT + 4
LIST_ENTRIES = LIST_COUNT + 8
PATCHED_MODULEDATA_SIZE = LIST_ENTRIES + 4 * CAPACITY

#: The module's primary vtable, which the discount walk identifies it by, and the upgrade-mux
#: interface it installs at `+0x10`, whose `+0x04` byte is `isAlreadyUpgraded`.
MODULE_VTABLE = 0x00C6F020
MODULE_DATA = 0x04
MODULE_UPGRADE_EXECUTED = 0x14

#: The three routines that maintain `Player+0x718` / `+0x71C`, each taken over at its first five
#: bytes: `onDelete` and `upgradeImplementation` (`ecx` = the mux interface, `ModuleData` at
#: `[ecx-0xC]`) and `onCapture` (`ecx` = the module, `ModuleData` at `[ecx+4]`).
ON_DELETE_VA = 0x008B9FE0
ON_DELETE_STOCK = bytes.fromhex("558bec5151")
UPGRADE_IMPL_VA = 0x008BA139
UPGRADE_IMPL_STOCK = bytes.fromhex("558bec5151")
ON_CAPTURE_VA = 0x008BA05E
ON_CAPTURE_STOCK = bytes.fromhex("558bec5153")
#: `onCapture`'s tail: `setUpgradeExecuted(1)` and the epilogue, reached with `ebx` = the module.
ON_CAPTURE_TAIL_VA = 0x008BA128

#: `startPowerRecharge`, flavour 1 (23 module vtables): from the `je` that skips the player
#: discount to the instruction after its `fstp [ebp-8]`. `edi` is the `ModuleData`, `[ebp-4]` the
#: player, and the flags are those of `test al, 1` on `RESPECT_RECHARGE_TIME_DISCOUNT`.
GATE1_VA = 0x00896EC2
GATE1_STOCK = bytes.fromhex("74118b4dfce8063ce1ffd8050819bd00d95df8")
#: Flavour 2 (`SpecialPowerUpdateModule` family): `mov ecx, [ebp-4] / call getModifier /
#: fadd 1.0`, with no flag test. `edi` is the raw template, `[ebp-4]` the player.
GATE2_VA = 0x00991569
GATE2_STOCK = bytes.fromhex("8b4dfce86195d1ffd8050819bd00")

PLAYER_GET_SPELL_RECHARGE_MODIFIER = 0x006AAAD2
FIND_SPECIAL_POWER_TEMPLATE = 0x0069C146
#: The engine's INI error: format `{char *message; int code;}` and throw it, as
#: `science-prereqs` does.
EXCEPTION_FORMAT = 0x0042F3C1
EXCEPTION_CODE = 3
CXX_THROW_EXCEPTION = 0x00A3CE04
THROW_INFO = 0x00D17000

#: Engine bytes the caves depend on without rewriting them, as `(VA, bytes, what)`.
ANCHORS = (
    (0x00896E3B, bytes.fromhex("8b7ef4"), "flavour 1: edi = [esi-0xC], the ModuleData"),
    (0x00896E5D, bytes.fromhex("8945fc"), "flavour 1: [ebp-4] = the controlling player"),
    (0x00896EAD, bytes.fromhex("8b4f08"), "flavour 1: the raw template is [edi+8]"),
    (0x00896EBA, bytes.fromhex("8b4018c1e805a801"), "flavour 1: the discount flag test"),
    (0x0099152C, bytes.fromhex("8945fc"), "flavour 2: [ebp-4] = the controlling player"),
    (0x00991535, bytes.fromhex("8b7f08"), "flavour 2: edi = the raw template"),
    (0x008B9F6E, bytes.fromhex("c70620f0c600"), "the module's vtable"),
    (0x008B9F7B, bytes.fromhex("c74610d8efc600"), "the upgrade-mux interface at +0x10"),
    (0x00C6EFD8, struct.pack("<I", 0x004986C4), "mux slot 0: isAlreadyUpgraded"),
    (0x004986C4, bytes.fromhex("8a4104c3"), "isAlreadyUpgraded reads +4"),
    (0x00C6EFFC, struct.pack("<I", 0x005B462D), "mux slot 9: setUpgradeExecuted"),
    (0x005B462D, bytes.fromhex("8a442404884104c20400"), "setUpgradeExecuted writes +4"),
    (0x008553A0, bytes.fromhex("6a018bceff5024"), "giveSelfUpgrade sets the flag itself"),
    (0x008BA171, bytes.fromhex("8b863c0100002b8638010000"), "Percentage is a vector at +0x138"),
    (0x008BA128, bytes.fromhex("8d4b108b016a01ff50245f5e5bc9c20800"), "onCapture's tail"),
    (0x008BA05A, bytes.fromhex("5e5fc9c3"), "onDelete returns with a plain ret"),
    (0x008BA1A7, bytes.fromhex("5f5ec9c3"), "upgradeImplementation returns with a plain ret"),
    (PLAYER_GET_SPELL_RECHARGE_MODIFIER, bytes.fromhex("d98118070000c3"), "fld [Player+0x718]"),
    (PLAYER_FOR_EACH_TEAM_OBJECT, bytes.fromhex("56578bf98b874c0300008b30"), "forEachTeamObject"),
    (FIND_SPECIAL_POWER_TEMPLATE, bytes.fromhex("b8208fb800"), "findSpecialPowerTemplate"),
    (INI_NEXT_TOKEN_OR_NULL, bytes.fromhex("b8420bb700"), "INI::getNextTokenOrNull"),
)

UNKNOWN_FORMAT = f"{KEYWORD}: unknown special power '%s'"
OVERFLOW_FORMAT = f"{KEYWORD}: more than {CAPACITY} special powers (at '%s')"


def _cstring(text: str) -> bytes:
    blob = text.encode("ascii") + b"\x00"
    return blob + bytes(-len(blob) % 4)


def _data_layout(section_va: int) -> tuple[bytes, dict[str, int]]:
    """The strings and the flag, laid out after the relocated table. Returns their bytes and
    each one's VA."""
    table_size = (len(STOCK_FIELDS) + 2) * FIELD_ENTRY_SIZE
    va = section_va + table_size
    blob = bytearray()
    where: dict[str, int] = {}
    for key, chunk in (
        ("keyword", _cstring(KEYWORD)),
        ("unknown", _cstring(UNKNOWN_FORMAT)),
        ("overflow", _cstring(OVERFLOW_FORMAT)),
        ("any", bytes(4)),
    ):
        where[key] = va + len(blob)
        blob += chunk
    where["code"] = va + len(blob)
    return bytes(blob), where


def build_code(
    code_va: int, any_flag: int, unknown_fmt: int, overflow_fmt: int, callback_va: int
) -> Asm:
    """Every routine the patch installs, one `Asm` so they can call each other by label.

    `callback_va` is pushed as an immediate, so `_code` assembles twice: once to find where the
    callback lands, once with it. The layout does not depend on the value."""
    a = Asm(code_va)

    # The ModuleData constructor: run the stock one, then zero the new tail. `eax` is `this`.
    a.label("ctor")
    a.call_absolute(MODULEDATA_CTOR_VA)
    a.emit(0x57)  # push edi
    a.emit(0x50)  # push eax
    a.emit(b"\x8d\xb8", u32(LIST_COUNT))  # lea edi, [eax+LIST_COUNT]
    a.emit(b"\x33\xc0")  # xor eax, eax
    a.emit(0x6A, 2 + CAPACITY)  # push count, scratch and entries in dwords
    a.emit(0x59)  # pop ecx
    a.emit(b"\xf3\xab")  # rep stosd
    a.emit(0x58)  # pop eax
    a.emit(0x5F)  # pop edi
    a.emit(0xC3)  # ret

    # The field parser: cdecl (INI *, void *instance, void *store, const void *), `store` being
    # `&count`. Every line replaces the list; each token is resolved against the special-power
    # store now, and an unknown name or a seventeenth one is an INI error.
    a.label("parse")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    a.emit(b"\x8b\x7d\x10")  # mov edi, [ebp+0x10]      ; &count
    a.emit(b"\x83\x27\x00")  # and dword [edi], 0
    a.label("parse_next")
    a.emit(0x6A, 0x00)  # push 0                        ; the INI's own separators
    a.emit(b"\x8b\x4d\x08")  # mov ecx, [ebp+8]
    a.call_absolute(INI_NEXT_TOKEN_OR_NULL)  # ret 4, NULL at end of line
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "parse_done")
    a.emit(b"\x8b\xf0")  # mov esi, eax               ; the token
    a.emit(b"\x8b\x0d", u32(THE_SPECIAL_POWER_STORE))  # mov ecx, [TheSpecialPowerStore]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "parse_unknown")
    a.emit(0x51)  # push ecx                       ; the by-value AsciiString's slot
    a.emit(b"\x8b\xcc")  # mov ecx, esp
    a.emit(0x56)  # push esi
    a.call_absolute(ASCII_STRING_CTOR)  # ret 4
    a.emit(b"\x8b\x0d", u32(THE_SPECIAL_POWER_STORE))  # mov ecx, [TheSpecialPowerStore]
    a.call_absolute(FIND_SPECIAL_POWER_TEMPLATE)  # ret 4, destroys the argument
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "parse_unknown")
    a.emit(b"\x8b\x0f")  # mov ecx, [edi]
    a.emit(b"\x83\xf9", CAPACITY)  # cmp ecx, CAPACITY
    a.jcc(JAE, "parse_overflow")
    a.emit(b"\x89\x44\x8f\x08")  # mov [edi+ecx*4+8], eax     ; entries follow count, scratch
    a.emit(b"\xff\x07")  # inc dword [edi]
    a.emit(b"\xc6\x05", u32(any_flag), 0x01)  # mov byte [any], 1
    a.jmp("parse_next")
    a.label("parse_done")
    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi
    a.emit(0x5D)  # pop ebp
    a.emit(0xC3)  # ret
    a.label("parse_unknown")
    a.emit(0xB8, u32(unknown_fmt))  # mov eax, <format>
    a.jmp("parse_throw")
    a.label("parse_overflow")
    a.emit(0xB8, u32(overflow_fmt))  # mov eax, <format>
    a.label("parse_throw")
    a.emit(b"\x83\xec\x08")  # sub esp, 8                 ; the exception object
    a.emit(0x56)  # push esi                       ; the %s
    a.emit(0x50)  # push eax                       ; the format
    a.emit(0x6A, EXCEPTION_CODE)  # push 3
    a.emit(b"\x8d\x44\x24\x0c")  # lea eax, [esp+0xc]
    a.emit(0x50)  # push eax
    a.call_absolute(EXCEPTION_FORMAT)
    a.emit(b"\x83\xc4\x10")  # add esp, 0x10
    a.emit(0x68, u32(THROW_INFO))  # push <throwinfo>
    a.emit(b"\x8d\x44\x24\x04")  # lea eax, [esp+4]
    a.emit(0x50)  # push eax
    a.call_absolute(CXX_THROW_EXCEPTION)
    a.emit(0xCC)  # int3                           ; unreachable

    # The three writers of Player+0x718/+0x71C return early for a targeted module and otherwise
    # re-run their displaced prologue and continue in the stock body.
    a.label("on_delete")
    a.emit(b"\x8b\x41\xf4")  # mov eax, [ecx-0xc]
    a.emit(b"\x83\xb8", u32(LIST_COUNT), 0x00)  # cmp dword [eax+LIST_COUNT], 0
    a.jcc(JNE, "plain_ret")
    a.emit(ON_DELETE_STOCK)
    a.jmp_absolute(ON_DELETE_VA + len(ON_DELETE_STOCK))

    a.label("upgrade_impl")
    a.emit(b"\x8b\x41\xf4")  # mov eax, [ecx-0xc]
    a.emit(b"\x83\xb8", u32(LIST_COUNT), 0x00)  # cmp dword [eax+LIST_COUNT], 0
    a.jcc(JNE, "plain_ret")
    a.emit(UPGRADE_IMPL_STOCK)
    a.jmp_absolute(UPGRADE_IMPL_VA + len(UPGRADE_IMPL_STOCK))

    a.label("plain_ret")
    a.emit(0xC3)  # ret

    a.label("on_capture")
    a.emit(b"\x8b\x41\x04")  # mov eax, [ecx+4]
    a.emit(b"\x83\xb8", u32(LIST_COUNT), 0x00)  # cmp dword [eax+LIST_COUNT], 0
    a.emit(ON_CAPTURE_STOCK)  # push ebp / mov ebp, esp / push ecx / push ebx - flags survive
    a.jcc(JNE, "on_capture_targeted")
    a.jmp_absolute(ON_CAPTURE_VA + len(ON_CAPTURE_STOCK))
    a.label("on_capture_targeted")
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    a.emit(b"\x8b\xd9")  # mov ebx, ecx
    a.jmp_absolute(ON_CAPTURE_TAIL_VA)  # setUpgradeExecuted(1), then the stock epilogue

    # Flavour 1, called in place of the stock discount. The flags are still those of the flag
    # test, because `call` leaves them alone.
    a.label("gate1")
    a.jcc(JE, "gate1_targets")
    a.emit(b"\x8b\x4d\xfc")  # mov ecx, [ebp-4]
    a.call_absolute(PLAYER_GET_SPELL_RECHARGE_MODIFIER)
    a.emit(b"\xd8\x05", u32(FLOAT_ONE))  # fadd dword [1.0]
    a.emit(b"\xd9\x5d\xf8")  # fstp dword [ebp-8]
    a.label("gate1_targets")
    a.emit(b"\x80\x3d", u32(any_flag), 0x00)  # cmp byte [any], 0
    a.jcc(JE, "plain_ret")
    a.emit(b"\xff\x77\x08")  # push dword [edi+8]         ; the raw template
    a.emit(b"\xff\x75\xfc")  # push dword [ebp-4]         ; the player
    a.call("factor")
    a.emit(b"\xd8\x4d\xf8")  # fmul dword [ebp-8]
    a.emit(b"\xd9\x5d\xf8")  # fstp dword [ebp-8]
    a.emit(0xC3)  # ret

    # Flavour 2: the stock discount, then the targeted factor. Leaves the product in st(0) for
    # the stock `fstp [ebp-4]` that follows the hook.
    a.label("gate2")
    a.emit(b"\x8b\x4d\xfc")  # mov ecx, [ebp-4]
    a.call_absolute(PLAYER_GET_SPELL_RECHARGE_MODIFIER)
    a.emit(b"\xd8\x05", u32(FLOAT_ONE))  # fadd dword [1.0]
    a.emit(b"\x80\x3d", u32(any_flag), 0x00)  # cmp byte [any], 0
    a.jcc(JE, "plain_ret")
    a.emit(0x51)  # push ecx                       ; park the stock multiplier:
    a.emit(b"\xd9\x1c\x24")  # fstp dword [esp]           ; the x87 stack is empty at a call
    a.emit(0x57)  # push edi                       ; the raw template
    a.emit(b"\xff\x75\xfc")  # push dword [ebp-4]         ; the player
    a.call("factor")
    a.emit(b"\xd8\x0c\x24")  # fmul dword [esp]
    a.emit(0x59)  # pop ecx
    a.emit(0xC3)  # ret

    # stdcall factor(Player *, SpecialPowerTemplate *) -> st(0), ret 8. Two walks over the
    # player's objects with the same callback: the first counts each group, the second applies
    # and clears it. The context is {player, template, pass, product}.
    a.label("factor")
    a.emit(0x55)  # push ebp
    a.emit(b"\x8b\xec")  # mov ebp, esp
    a.emit(b"\x83\xec\x10")  # sub esp, 0x10
    a.emit(b"\x8b\x45\x08")  # mov eax, [ebp+8]
    a.emit(b"\x89\x45\xf0")  # mov [ebp-0x10], eax        ; player
    a.emit(b"\x8b\x45\x0c")  # mov eax, [ebp+0xc]
    a.emit(b"\x89\x45\xf4")  # mov [ebp-0xc], eax         ; template
    a.emit(b"\xc7\x45\xfc", u32(0x3F800000))  # mov dword [ebp-4], 1.0   ; product
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "factor_out")
    a.emit(b"\x83\x7d\x08\x00")  # cmp dword [ebp+8], 0
    a.jcc(JE, "factor_out")
    for walk in (0, 1):
        a.emit(b"\xc7\x45\xf8", u32(walk))  # mov dword [ebp-8], pass
        a.emit(b"\x8d\x45\xf0")  # lea eax, [ebp-0x10]
        a.emit(0x50)  # push eax                   ; ctx
        a.emit(0x68, u32(callback_va))  # push <callback>
        a.emit(b"\x8b\x4d\x08")  # mov ecx, [ebp+8]
        a.call_absolute(PLAYER_FOR_EACH_TEAM_OBJECT)  # thiscall, ret 8
    a.label("factor_out")
    a.emit(b"\xd9\x45\xfc")  # fld dword [ebp-4]
    a.emit(0xC9)  # leave
    a.emit(b"\xc2\x08\x00")  # ret 8

    # cdecl callback(Object *, ctx) -> eax != 0 to keep walking.
    a.label("callback")
    a.emit(0x53)  # push ebx
    a.emit(0x56)  # push esi
    a.emit(0x57)  # push edi
    a.emit(b"\x8b\x74\x24\x10")  # mov esi, [esp+0x10]        ; the object
    a.emit(b"\x8b\x5c\x24\x14")  # mov ebx, [esp+0x14]        ; the context
    a.emit(b"\xf6\x86", u32(OBJECT_STATUS), 0x01)  # test byte [esi+status], DESTROYED
    a.jcc(JNE, "cb_continue")
    a.emit(b"\x8b\xce")  # mov ecx, esi
    a.call_absolute(OBJECT_GET_CONTROLLING_PLAYER)
    a.emit(b"\x3b\x03")  # cmp eax, [ebx]
    a.jcc(JNE, "cb_continue")
    a.emit(b"\x8b\xbe", u32(OBJECT_MODULE_LIST))  # mov edi, [esi+0x24c]
    a.emit(b"\x85\xff")  # test edi, edi
    a.jcc(JE, "cb_continue")
    a.label("cb_module")
    a.emit(b"\x8b\x0f")  # mov ecx, [edi]
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "cb_continue")
    a.emit(b"\x83\xc7\x04")  # add edi, 4
    a.emit(b"\x81\x39", u32(MODULE_VTABLE))  # cmp dword [ecx], <vtable>
    a.jcc(JNE, "cb_module")
    a.emit(b"\x80\x79", MODULE_UPGRADE_EXECUTED, 0x00)  # cmp byte [ecx+0x14], 0
    a.jcc(JE, "cb_module")
    a.emit(b"\x8b\x51", MODULE_DATA)  # mov edx, [ecx+4]           ; ModuleData
    a.emit(b"\x8b\x82", u32(LIST_COUNT))  # mov eax, [edx+LIST_COUNT]
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "cb_module")
    a.emit(b"\x8b\x4b\x04")  # mov ecx, [ebx+4]           ; the template
    a.emit(b"\x8d\xb2", u32(LIST_ENTRIES))  # lea esi, [edx+LIST_ENTRIES]; the object is done
    a.label("cb_find")
    a.emit(b"\x39\x0e")  # cmp [esi], ecx
    a.jcc(JE, "cb_found")
    a.emit(b"\x83\xc6\x04")  # add esi, 4
    a.emit(0x48)  # dec eax
    a.jcc(JNE, "cb_find")
    a.jmp("cb_module")
    a.label("cb_found")
    a.emit(b"\x83\x7b\x08\x00")  # cmp dword [ebx+8], 0
    a.jcc(JNE, "cb_apply")
    a.emit(b"\xff\x82", u32(LIST_SCRATCH))  # inc dword [edx+LIST_SCRATCH]
    a.jmp("cb_module")
    a.label("cb_apply")
    a.emit(b"\x8b\x82", u32(LIST_SCRATCH))  # mov eax, [edx+LIST_SCRATCH]    ; the level
    a.emit(b"\x85\xc0")  # test eax, eax
    a.jcc(JE, "cb_module")  # this group is already applied
    a.emit(b"\x83\xa2", u32(LIST_SCRATCH), 0x00)  # and dword [edx+LIST_SCRATCH], 0
    a.emit(b"\x8b\x8a", u32(PERCENTAGE_END))  # mov ecx, [edx+0x13c]
    a.emit(b"\x2b\x8a", u32(PERCENTAGE_BEGIN))  # sub ecx, [edx+0x138]
    a.emit(b"\xc1\xf9\x02")  # sar ecx, 2                  ; entries
    a.emit(b"\x85\xc9")  # test ecx, ecx
    a.jcc(JE, "cb_module")  # no Percentage: no discount
    a.emit(b"\x3b\xc1")  # cmp eax, ecx
    a.jcc(JLE, "cb_level")
    a.emit(b"\x8b\xc1")  # mov eax, ecx                ; past the list: its last entry
    a.label("cb_level")
    a.emit(0x48)  # dec eax
    a.emit(b"\x8b\x8a", u32(PERCENTAGE_BEGIN))  # mov ecx, [edx+0x138]
    a.emit(b"\xd9\x04\x81")  # fld dword [ecx+eax*4]
    a.emit(b"\xd8\x05", u32(FLOAT_ONE))  # fadd dword [1.0]
    a.emit(b"\xd8\x4b\x0c")  # fmul dword [ebx+0xc]
    a.emit(b"\xd9\x5b\x0c")  # fstp dword [ebx+0xc]
    a.jmp("cb_module")
    a.label("cb_continue")
    a.emit(b"\x33\xc0")  # xor eax, eax
    a.emit(0x40)  # inc eax
    a.emit(0x5F)  # pop edi
    a.emit(0x5E)  # pop esi
    a.emit(0x5B)  # pop ebx
    a.emit(0xC3)  # ret
    return a


def _code(code_va: int, where: dict[str, int]) -> tuple[bytes, dict[str, int]]:
    """Assemble the routines, and return them with the VA of each one the engine is pointed at."""
    args = (code_va, where["any"], where["unknown"], where["overflow"])
    callback_va = build_code(*args, 0).label_va("callback")
    a = build_code(*args, callback_va)
    labels = {
        name: a.label_va(name)
        for name in ("ctor", "parse", "on_delete", "upgrade_impl", "on_capture", "gate1", "gate2")
    }
    return a.finish(), labels


class SpellRechargeTargetsPatch(Patch):
    name = "spell-recharge-targets"
    author = "officialNecro"
    description = (
        f"Let SpellRechargeModifierUpgrade name the special powers it discounts: {KEYWORD} = "
        "<SpecialPower> ... (up to 16). A module that names powers leaves the player-wide "
        "spellbook discount alone and scales only those powers' recharge, flagged "
        "RESPECT_RECHARGE_TIME_DISCOUNT or not; its Percentage levels count copies of the same "
        "module. A module without the keyword is stock. Logic-side: every peer needs the same "
        "binary"
    )

    def apply(self, data: bytearray) -> None:
        self._check(data)
        section_va = allocate_section(
            data,
            SECTION_NAME,
            lambda va: self._section(data, va)[0],
            SECTION_CHARACTERISTICS,
        )
        _content, labels = self._section(data, section_va)
        for va, old, new, note in self._edits(section_va, labels):
            apply_byte_patch(data, file_offset(data, va), old, new, note)

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located
        problems: list[str] = []
        try:
            content, labels = self._section(data, section_va)
        except ValueError as exc:
            return [f"cannot recompute the expected cave (wrong build?): {exc}"]
        if bytes(data[section_off : section_off + len(content)]) != content:
            problems.append(f"{SECTION_NAME} is not the table and code this patch builds")
        for va, _old, new, note in self._edits(section_va, labels):
            off = file_offset(data, va)
            got = bytes(data[off : off + len(new)])
            if got != new:
                problems.append(f"{note} @0x{va:08x}: expected {new.hex()}, got {got.hex()}")
        problems += self._anchor_problems(data)
        return problems

    def ini_surface(self) -> Engine:
        """The new list on `SpellRechargeModifierUpgrade`. Absent means stock behaviour."""
        field = FieldDelta(
            "SpellRechargeModifierUpgrade", KEYWORD, "Ref[]:specialpowers", None, self.name
        )
        return Engine(fields=(field,))

    def _section(self, data: bytes | bytearray, section_va: int) -> tuple[bytes, dict[str, int]]:
        """`(content, routine VAs)` for a cave at `section_va`: the relocated field table (the
        three stock rows verbatim, the new one, the terminator), the strings and flag, the code."""
        stock = self._stock_table(data)
        strings, where = _data_layout(section_va)
        code, labels = _code(where["code"], where)
        row = u32(where["keyword"]) + u32(labels["parse"]) + u32(0) + u32(LIST_COUNT)
        table = stock + row + bytes(FIELD_ENTRY_SIZE)
        return table + strings + code, labels

    def _stock_table(self, data: bytes | bytearray) -> bytes:
        """The three stock rows, fingerprinted by name and offset and checked to be terminated."""
        off = file_offset(data, FIELD_TABLE_VA, "the SpellRechargeModifierUpgrade field table")
        size = len(STOCK_FIELDS) * FIELD_ENTRY_SIZE
        rows = bytes(data[off : off + size])
        for index, (name, offset) in enumerate(STOCK_FIELDS):
            name_va, _parse, _user, field_off = struct.unpack_from("<4I", rows, index * 16)
            got = read_cstring(data, name_va)
            if got != name or field_off != offset:
                raise ValueError(
                    f"field table row {index}: expected {name!r} at 0x{offset:x}, found "
                    f"{got!r} at 0x{field_off:x}"
                )
        if bytes(data[off + size : off + size + FIELD_ENTRY_SIZE]) != bytes(FIELD_ENTRY_SIZE):
            raise ValueError("the SpellRechargeModifierUpgrade field table has grown")
        return rows

    def _edits(
        self, section_va: int, labels: dict[str, int]
    ) -> list[tuple[int, bytes, bytes, str]]:
        """Every byte range the patch rewrites, as `(VA, stock, patched, note)`."""
        gate1 = call_rel32(GATE1_VA, labels["gate1"]) + b"\xeb" + bytes([len(GATE1_STOCK) - 7])
        gate1 += b"\x90" * (len(GATE1_STOCK) - len(gate1))
        gate2 = call_rel32(GATE2_VA, labels["gate2"]) + b"\xeb" + bytes([len(GATE2_STOCK) - 7])
        gate2 += b"\x90" * (len(GATE2_STOCK) - len(gate2))
        return [
            (
                MODULEDATA_SIZE_VA,
                b"\x68" + u32(STOCK_MODULEDATA_SIZE),
                b"\x68" + u32(PATCHED_MODULEDATA_SIZE),
                "sizeof(SpellRechargeModifierUpgradeModuleData)",
            ),
            (
                MODULEDATA_CTOR_CALL_VA,
                call_rel32(MODULEDATA_CTOR_CALL_VA, MODULEDATA_CTOR_VA),
                call_rel32(MODULEDATA_CTOR_CALL_VA, labels["ctor"]),
                "ModuleData ctor -> zero the power list",
            ),
            (
                FIELD_TABLE_PUSH_VA,
                b"\x68" + u32(FIELD_TABLE_VA),
                b"\x68" + u32(section_va),
                "field table -> cave",
            ),
            (
                ON_DELETE_VA,
                ON_DELETE_STOCK,
                jmp_rel32(ON_DELETE_VA, labels["on_delete"]),
                "onDelete -> skip for a targeted module",
            ),
            (
                ON_CAPTURE_VA,
                ON_CAPTURE_STOCK,
                jmp_rel32(ON_CAPTURE_VA, labels["on_capture"]),
                "onCapture -> skip for a targeted module",
            ),
            (
                UPGRADE_IMPL_VA,
                UPGRADE_IMPL_STOCK,
                jmp_rel32(UPGRADE_IMPL_VA, labels["upgrade_impl"]),
                "upgradeImplementation -> skip for a targeted module",
            ),
            (GATE1_VA, GATE1_STOCK, gate1, "startPowerRecharge discount -> cave"),
            (GATE2_VA, GATE2_STOCK, gate2, "SpecialPowerUpdateModule discount -> cave"),
        ]

    @staticmethod
    def _anchor_problems(data: bytes | bytearray) -> list[str]:
        problems = []
        for va, expected, what in ANCHORS:
            off = file_offset(data, va)
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                problems.append(f"{what} @0x{va:08x}: expected {expected.hex()}, got {got.hex()}")
        return problems

    def _check(self, data: bytes | bytearray) -> None:
        if find_section(data, SECTION_NAME) is not None:
            raise ValueError(f"the file already carries this patch ({SECTION_NAME} exists)")
        problems = self._anchor_problems(data)
        if problems:
            raise ValueError("not the expected build: " + "; ".join(problems))
        if KEYWORD.lower() in (name.lower() for name in MUX_FIELDS):
            raise ValueError(f"{KEYWORD!r} is already an upgrade-mux field")
