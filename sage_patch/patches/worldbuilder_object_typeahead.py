r"""A type-ahead box above Worldbuilder's object tree.

**This patch targets `Worldbuilder.exe`, not `game.dat`.** See
``../docs/worldbuilder-object-typeahead.md`` for the derivation.

Every script action and condition that names an object type opens one dialog: `IDD` 190, driven by
`EditObjectParameter` from
``E:\Builds\BFME2X\Code\production\Code\Tools\WorldBuilder\src\EditObjectParameter.cpp``. It is a
tree of every `ThingTemplate` in the game, filed under its side and then its editor-sorting
category, and it opens with every folder collapsed. Finding `GondorArcherHorde` in it is a hunt
through three levels of folder, once per argument.

`OnInitDialog` (``0x004F2980``) walks `TheThingFactory`'s template list and calls `addObject`
(``0x004F2B20``) for each, which inserts the template's name as the item text and **lParam 0** -
no back-pointer to anything. `OnOK` (``0x004F34C0``) then reads only ``TVM_GETNEXTITEM``/
``TVGN_CARET`` followed by ``TVM_GETITEM``, and stores the selected item's *label text* into the
`Parameter` at ``this+0x78``. It never consults lParam, never asks `TheThingFactory` whether the
name exists, and never checks the item is a leaf - a side folder called `Gondor` is accepted as
readily as a real object name.

That is what makes this patch small: **anything that moves the tree's caret already implements
"type the name"**. The accept path is not touched, so the patched dialog cannot produce a value the
stock dialog could not, and text matching nothing clears the selection so OK falls into the stock
"nothing is selected" beep rather than accepting a stale highlight.

**The control.** One `EDIT`, id ``0x7000`` - the highest id in any of the 109 dialogs is 1538 - as
the second item of the template, so it is the first tabstop and takes focus when the dialog opens.
The template stays **exactly 292 bytes**: the caption shrinks from ``"Edit object parameter."`` to
``"Object"``, which frees the 32 bytes a fifth `DLGITEMTEMPLATEEX` costs, so nothing about the
resource directory moves. The tree drops from y=20 to y=35 and loses 15 dlu of height; every other
control keeps its rect, which matters because the `DialogLayoutManager` at ``this+0xD4`` anchors by
control id.

**The behaviour, without subclassing anything.** `GetMessageMap` returns ``0x01DF2050`` from two
``mov eax, imm32`` sites (``0x004F2953``, ``0x004F2967``). Both are repointed at an `AFX_MSGMAP` in
the cave holding the stock two entries - `WM_DESTROY` and `WM_SIZE` - plus one more:

    msg = WM_COMMAND (0x0111)   code = EN_CHANGE (0x0300)   id = 0x7000   sig = 0x35

`pfnGetBaseMap` stays ``0x016C2030``, so the base-class chain is unchanged. The encoding is read,
not guessed: the neighbouring class's message map, 0x3C4 bytes further into `.rdata`, carries a
literal `ON_EN_CHANGE` in exactly this shape. Signature ``0x35`` is `AfxSig_vv`, so the handler is a
plain ``void (CWnd::*)()`` - `this` in `ECX`, no arguments, no return.

So there is no window subclassing, no `SetWindowLongA`/`CallWindowProcA`, no vtable rewrite, and
**no new imports**: the cave needs only `SendMessageA` (``0x022F54D0``) and `SendDlgItemMessageA`
(``0x022F55BC``), both already imported. That matters, because `CreateWindowExA`, `SetWindowLongA`,
`CallWindowProcA` and `GetWindowTextA` are all absent from Worldbuilder's user32 imports.

**What the handler does.** Reads the box, lower-cases it, walks the tree in pre-order (`TVGN_ROOT`,
then `TVGN_CHILD`/`TVGN_NEXT`/`TVGN_PARENT` - no stack needed), and scores every item as
``rank * 2 + is_leaf``, where rank is 3 for an exact match, 2 for a prefix, 1 for a substring and 0
for none, case-insensitively. The first item with the highest score wins, an exact leaf match stops
the walk, and the result is selected with ``TVM_SELECTITEM``/``TVGN_CARET``, which expands its
ancestors on the way. An empty box leaves the selection alone; a box that matches nothing clears it.

Enter needs no code at all. The edit has no `ES_WANTRETURN`, so `IsDialogMessage` routes Enter to
the default button, which is IDOK, which reads the caret the handler just set.

**Cost.** Two `SendMessageA` per tree item per keystroke, same thread, no marshalling - about 8,000
in-process messages for a 4,000-template mod tree.

**Scope.** The two `EditParameter::edit` sites that open this dialog (``0x004F4238`` for parameter
type ``0x0F``, ``0x004F429B`` for ``0x3D``) are the whole of it. Sibling pickers - teams, waypoints,
script names - are separate classes in separate files and keep their stock behaviour.

**Not done.** The edit is not registered with the `DialogLayoutManager`, so it keeps its width when
the dialog is resized while the tree stretches. The anchor table passed at ``0x004F29FD`` lives in
`.data`'s zero-fill tail, past the raw data, so it is built at run time and cannot be extended by a
static byte patch; doing it properly means copying the four anchors into the cave during
`OnInitDialog`, which is a second hook for a cosmetic gain.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from ..asm import JA, JB, JE, JGE, JLE, JNE, Asm
from ..patcher import Patch
from ..utils import allocate_section, apply_byte_patch, find_section, va_to_offset

if TYPE_CHECKING:
    import argparse

__all__ = [
    "ANCHORS",
    "EDIT_ID",
    "MESSAGE_MAP_SITES",
    "SECTION_NAME",
    "TEMPLATE_VA",
    "WorldbuilderObjectTypeaheadPatch",
    "build_section",
]

SECTION_NAME = ".wbtype"

# IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ | MEM_WRITE. Writable because
# the cave holds the two text buffers and the TVITEM the handler fills in.
_CHARACTERISTICS = 0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000

#: The new edit control's dialog id. Free: no control in any of the binary's 109 dialogs uses an id
#: above 1538 outside the AFX range, and this is clear of both.
EDIT_ID = 0x7000

#: `RT_DIALOG` 190's template, at RVA ``0x01F51E60``. Rewritten in place and to the same length, so
#: the resource directory entry that points here is left alone.
TEMPLATE_VA = 0x02351E60

#: The two ``mov eax, <AFX_MSGMAP>`` sites - `EditObjectParameter::GetThisMessageMap` and its
#: virtual `GetMessageMap` - that decide which message map the dialog dispatches through.
MESSAGE_MAP_SITES = (0x004F2953, 0x004F2967)
_STOCK_MESSAGE_MAP = 0x01DF2050
_GET_BASE_MAP = 0x016C2030

#: The stock map's entries, copied verbatim into the cave's array ahead of the new one: `WM_DESTROY`
#: -> ``0x0040AE57`` and `WM_SIZE` -> ``0x0040C086``, both as the thunks the linker emitted.
_STOCK_ENTRIES = bytes.fromhex(
    "020000000000000000000000000000001000000057ae4000"
    "050000000000000000000000000000001600000086c04000"
)
_TERMINATOR = bytes(24)

#: `CWnd::m_hWnd`, and the tree control's copy of it. ``this+0x7C`` is the `CTreeCtrl` member
#: `DoDataExchange` binds to control ``0x497``; ``0x7C + 0x20`` is where its handle lands, which is
#: what every `SendMessageA` in the class pushes.
_M_HWND = 0x20
_TREE_HWND = 0x9C

_SEND_MESSAGE_A = 0x022F54D0
_SEND_DLG_ITEM_MESSAGE_A = 0x022F55BC

_WM_GETTEXT = 0x0D
_TVM_GETNEXTITEM = 0x110A
_TVM_SELECTITEM = 0x110B
_TVM_GETITEM = 0x110C
_TVM_ENSUREVISIBLE = 0x1114
_TVGN_ROOT = 0
_TVGN_NEXT = 1
_TVGN_PARENT = 3
_TVGN_CHILD = 4
_TVGN_CARET = 9
_TVIF_TEXT_HANDLE = 0x11

_TEXT_MAX = 0x100
_BUFFER_SIZE = 0x104

_NEEDLE_OFF = 0x000
_ITEM_OFF = 0x104
_TVITEM_OFF = 0x208
_LEAF_OFF = 0x230
_MSGMAP_OFF = 0x238
_ENTRIES_OFF = 0x240
_CODE_OFF = 0x2A0

#: `IDD` 190 as shipped: `DLGTEMPLATEEX`, 146x178 dlu, `WS_THICKFRAME`, four controls - the
#: ``"Object:"`` group box (1133), the tree (1175), OK (1) and Cancel (2).
STOCK_TEMPLATE = bytes.fromhex(
    "0100ffff00000000000000004800c4800400000000009200b2000000000045006400"
    "6900740020006f0062006a00650063007400200070006100720061006d0065007400"
    "650072002e0000000800000000004d00530020005300680065006c006c0020004400"
    "6c006700000000000000000000000700005007000700830091006d040000ffff8000"
    "4f0062006a006500630074003a000000000000000000000000000000370081500f00"
    "140072007e0097040000530079007300540072006500650056006900650077003300"
    "32000000000000000000000000000000010001501d009d0032000e0001000000ffff"
    "80004f004b000000000000000000000000000000015058009d0032000e0002000000"
    "ffff8000430061006e00630065006c0000000000"
)

#: The same template with the caption shortened to ``"Object"``, the edit control inserted as item
#: 1, and the tree moved from (15, 20, 114, 126) to (15, 35, 114, 111). Same 292 bytes.
PATCHED_TEMPLATE = bytes.fromhex(
    "0100ffff00000000000000004800c4800500000000009200b200000000004f006200"
    "6a0065006300740000000800000000004d00530020005300680065006c006c002000"
    "44006c006700000000000000000000000700005007000700830091006d040000ffff"
    "80004f0062006a006500630074003a000000000000000000000000000000800081500f00"
    "140072000c0000700000ffff8100000000000000000000000000370081500f002300"
    "72006f0097040000530079007300540072006500650056006900650077003300320000"
    "00000000000000000000000000010001501d009d0032000e0001000000ffff80004f00"
    "4b000000000000000000000000000000015058009d0032000e0002000000ffff8000"
    "430061006e00630065006c0000000000"
)

#: Everything outside the sites this patch writes that it assumes about the build: the constructor's
#: binding of the class to `IDD` 190, `DoDataExchange`'s bind of the tree to control ``0x497``, and
#: `OnOK`'s read of the caret - the accept path the handler steers rather than replaces.
ANCHORS = {
    0x004F279E: bytes.fromhex("6a0068be000000"),  # push 0; push 190 -> CDialog::CDialog
    0x004F292E: bytes.fromhex("6897040000"),  # push 0x497 -> DDX_Control
    0x004F34EC: bytes.fromhex("6a006a09680a110000"),  # push 0; push TVGN_CARET; push TVM_GETNEXT
    _STOCK_MESSAGE_MAP: struct.pack("<II", _GET_BASE_MAP, 0x01DF2060),
    0x01DF2060: _STOCK_ENTRIES + _TERMINATOR,
}

#: PE `DllCharacteristics` bit that would let the loader move the image out from under the absolute
#: addresses the cave reads, calls and hands to MFC.
_DYNAMIC_BASE = 0x0040


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _assemble(base_va: int) -> Asm:
    """The cave's three routines: the `EN_CHANGE` handler, the per-item scorer it calls, and the
    case-insensitive prefix compare under that.

    The handler is reached as an MFC message-map entry, so it is entered `thiscall` with the dialog
    in `ECX` and returns with a bare `ret`. `pushad`/`popad` bracket it because MFC's dispatcher
    expects a member function's register discipline, not a hook's."""
    a = Asm(base_va + _CODE_OFF)
    needle = base_va + _NEEDLE_OFF
    item = base_va + _ITEM_OFF
    tvitem = base_va + _TVITEM_OFF
    leaf = base_va + _LEAF_OFF

    a.label("handler")
    a.emit(0x60)  # pushad
    a.emit(0x8B, 0xD1)  # mov edx, ecx                ; this
    a.emit(0x8B, 0xBA, _u32(_TREE_HWND))  # mov edi, [edx+0x9c]         ; the tree's HWND
    a.emit(0x85, 0xFF)  # test edi, edi
    a.jcc(JE, "done")  #                              ; EN_CHANGE before DDX ran: nothing to steer

    # SendDlgItemMessageA(dialog, EDIT_ID, WM_GETTEXT, _TEXT_MAX, needle). A missing control and an
    # empty box both return zero, and both mean the same thing here: leave the selection alone.
    a.emit(0x68, _u32(needle))  # push needle
    a.emit(0x68, _u32(_TEXT_MAX))  # push _TEXT_MAX
    a.emit(0x6A, _WM_GETTEXT)  # push WM_GETTEXT
    a.emit(0x68, _u32(EDIT_ID))  # push EDIT_ID
    a.emit(0xFF, 0x72, _M_HWND)  # push [edx+0x20]             ; the dialog's HWND
    a.emit(0xFF, 0x15, _u32(_SEND_DLG_ITEM_MESSAGE_A))
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "done")

    # Fold the needle once, so the per-item compare only has to fold the item text.
    a.emit(0xBE, _u32(needle))  # mov esi, needle
    a.label("lower")
    a.emit(0x8A, 0x06)  # mov al, [esi]
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "lower_done")
    a.emit(0x3C, 0x41)  # cmp al, 'A'
    a.jcc_short(JB, "lower_next")
    a.emit(0x3C, 0x5A)  # cmp al, 'Z'
    a.jcc_short(JA, "lower_next")
    a.emit(0x0C, 0x20)  # or al, 0x20
    a.emit(0x88, 0x06)  # mov [esi], al
    a.label("lower_next")
    a.emit(0x46)  # inc esi
    a.jmp("lower")
    a.label("lower_done")

    a.emit(0x31, 0xDB)  # xor ebx, ebx                ; best item so far
    a.emit(0x31, 0xED)  # xor ebp, ebp                ; its score

    a.emit(0x6A, 0x00)  # push 0
    a.emit(0x6A, _TVGN_ROOT)  # push TVGN_ROOT
    a.emit(0x68, _u32(_TVM_GETNEXTITEM))
    a.emit(0x57)  # push edi
    a.emit(0xFF, 0x15, _u32(_SEND_MESSAGE_A))
    a.emit(0x8B, 0xF0)  # mov esi, eax                ; node

    # Pre-order without a stack: descend to the first child, and when there is none, climb to the
    # first ancestor that still has a sibling.
    a.label("walk")
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JE, "select")
    a.emit(0x56)  # push esi
    a.emit(0x6A, _TVGN_CHILD)  # push TVGN_CHILD
    a.emit(0x68, _u32(_TVM_GETNEXTITEM))
    a.emit(0x57)  # push edi
    a.emit(0xFF, 0x15, _u32(_SEND_MESSAGE_A))
    a.emit(0x50)  # push eax                    ; the child, across the visit
    a.emit(0x31, 0xD2)  # xor edx, edx
    a.emit(0x85, 0xC0)  # test eax, eax
    a.emit(0x0F, 0x94, 0xC2)  # setz dl                     ; no child == a leaf
    a.emit(0x89, 0x15, _u32(leaf))  # mov [leaf], edx
    a.call("visit")
    a.emit(0x58)  # pop eax
    a.emit(0x83, 0xFD, 0x07)  # cmp ebp, 7                  ; an exact leaf match cannot be beaten
    a.jcc(JGE, "select")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "sibling")
    a.emit(0x8B, 0xF0)  # mov esi, eax
    a.jmp("walk")

    a.label("sibling")
    a.emit(0x56)  # push esi
    a.emit(0x6A, _TVGN_NEXT)  # push TVGN_NEXT
    a.emit(0x68, _u32(_TVM_GETNEXTITEM))
    a.emit(0x57)  # push edi
    a.emit(0xFF, 0x15, _u32(_SEND_MESSAGE_A))
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "parent")
    a.emit(0x8B, 0xF0)  # mov esi, eax
    a.jmp("walk")

    a.label("parent")
    a.emit(0x56)  # push esi
    a.emit(0x6A, _TVGN_PARENT)  # push TVGN_PARENT
    a.emit(0x68, _u32(_TVM_GETNEXTITEM))
    a.emit(0x57)  # push edi
    a.emit(0xFF, 0x15, _u32(_SEND_MESSAGE_A))
    a.emit(0x8B, 0xF0)  # mov esi, eax
    a.emit(0x85, 0xF6)  # test esi, esi
    a.jcc(JE, "select")
    a.jmp("sibling")

    # ebx is zero when nothing matched, and TVM_SELECTITEM with a null item clears the selection -
    # which is what turns a typo into the stock "nothing is selected" beep on OK.
    a.label("select")
    a.emit(0x53)  # push ebx
    a.emit(0x6A, _TVGN_CARET)  # push TVGN_CARET
    a.emit(0x68, _u32(_TVM_SELECTITEM))
    a.emit(0x57)  # push edi
    a.emit(0xFF, 0x15, _u32(_SEND_MESSAGE_A))
    a.emit(0x85, 0xDB)  # test ebx, ebx
    a.jcc(JE, "done")
    a.emit(0x53)  # push ebx
    a.emit(0x6A, 0x00)  # push 0
    a.emit(0x68, _u32(_TVM_ENSUREVISIBLE))
    a.emit(0x57)  # push edi
    a.emit(0xFF, 0x15, _u32(_SEND_MESSAGE_A))

    a.label("done")
    a.emit(0x61)  # popad
    a.emit(0xC3)  # ret

    # visit: score the item in esi and keep it if it beats ebx/ebp. Reads [leaf], set by the caller
    # from the same TVGN_CHILD query the walk needs anyway.
    a.label("visit")
    a.emit(0xC7, 0x05, _u32(tvitem + 0x00), _u32(_TVIF_TEXT_HANDLE))  # mask
    a.emit(0x89, 0x35, _u32(tvitem + 0x04))  # hItem = esi
    a.emit(0xC7, 0x05, _u32(tvitem + 0x10), _u32(item))  # pszText
    a.emit(0xC7, 0x05, _u32(tvitem + 0x14), _u32(_TEXT_MAX))  # cchTextMax
    a.emit(0xC6, 0x05, _u32(item), 0x00)  # mov byte [item], 0
    a.emit(0x68, _u32(tvitem))  # push &tvitem
    a.emit(0x6A, 0x00)  # push 0
    a.emit(0x68, _u32(_TVM_GETITEM))
    a.emit(0x57)  # push edi
    a.emit(0xFF, 0x15, _u32(_SEND_MESSAGE_A))
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "visit_ret")
    a.call("rank")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "visit_ret")
    a.emit(0x03, 0xC0)  # add eax, eax                ; rank * 2
    a.emit(0x03, 0x05, _u32(leaf))  # add eax, [leaf]             ; + the leaf bit
    a.emit(0x3B, 0xC5)  # cmp eax, ebp
    a.jcc(JLE, "visit_ret")  #                              ; ties keep the item found first
    a.emit(0x8B, 0xE8)  # mov ebp, eax
    a.emit(0x8B, 0xDE)  # mov ebx, esi
    a.label("visit_ret")
    a.emit(0xC3)  # ret

    # rank: 3 exact, 2 prefix, 1 substring, 0 none. Only eax/ecx/edx are touched, so the walk's
    # node, tree handle and running best survive the call.
    a.label("rank")
    a.emit(0xBA, _u32(item))  # mov edx, item
    a.call("prefix_at")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "rank_substring")
    a.emit(0x40)  # inc eax                     ; 1 -> prefix, 2 -> exact
    a.emit(0xC3)  # ret
    a.label("rank_substring")
    a.emit(0xBA, _u32(item))  # mov edx, item
    a.label("rank_step")
    a.emit(0x42)  # inc edx
    a.emit(0x80, 0x3A, 0x00)  # cmp byte [edx], 0
    a.jcc(JE, "rank_none")
    a.call("prefix_at")
    a.emit(0x85, 0xC0)  # test eax, eax
    a.jcc(JE, "rank_step")
    a.emit(0xB8, _u32(1))  # mov eax, 1
    a.emit(0xC3)  # ret
    a.label("rank_none")
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.emit(0xC3)  # ret

    # prefix_at: does the (already folded) needle prefix the string at edx? 2 when it matches the
    # whole of it, 1 when it matches a prefix, 0 otherwise. edx comes back unchanged so the
    # substring scan can walk it one character at a time.
    a.label("prefix_at")
    a.emit(0x52)  # push edx
    a.emit(0xB9, _u32(needle))  # mov ecx, needle
    a.label("prefix_loop")
    a.emit(0x8A, 0x01)  # mov al, [ecx]
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "prefix_end")
    a.emit(0x8A, 0x22)  # mov ah, [edx]
    a.emit(0x84, 0xE4)  # test ah, ah
    a.jcc(JE, "prefix_no")
    a.emit(0x80, 0xFC, 0x41)  # cmp ah, 'A'
    a.jcc_short(JB, "prefix_cmp")
    a.emit(0x80, 0xFC, 0x5A)  # cmp ah, 'Z'
    a.jcc_short(JA, "prefix_cmp")
    a.emit(0x80, 0xCC, 0x20)  # or ah, 0x20
    a.label("prefix_cmp")
    a.emit(0x38, 0xE0)  # cmp al, ah
    a.jcc(JNE, "prefix_no")
    a.emit(0x41)  # inc ecx
    a.emit(0x42)  # inc edx
    a.jmp("prefix_loop")
    a.label("prefix_end")
    a.emit(0x8A, 0x02)  # mov al, [edx]
    a.emit(0x84, 0xC0)  # test al, al
    a.jcc(JE, "prefix_exact")
    a.emit(0xB8, _u32(1))  # mov eax, 1
    a.emit(0x5A)  # pop edx
    a.emit(0xC3)  # ret
    a.label("prefix_exact")
    a.emit(0xB8, _u32(2))  # mov eax, 2
    a.emit(0x5A)  # pop edx
    a.emit(0xC3)  # ret
    a.label("prefix_no")
    a.emit(0x31, 0xC0)  # xor eax, eax
    a.emit(0x5A)  # pop edx
    a.emit(0xC3)  # ret

    return a


def build_section(base_va: int) -> bytes:
    """The cave: the two text buffers and the `TVITEM` the handler reuses, the leaf flag it passes
    to itself, the `AFX_MSGMAP` the dialog now dispatches through, its entries, then the code."""
    assembled = _assemble(base_va)
    body = bytearray(_CODE_OFF)
    struct.pack_into("<II", body, _MSGMAP_OFF, _GET_BASE_MAP, base_va + _ENTRIES_OFF)
    entry = struct.pack(
        "<IIIIII",
        0x0111,  # WM_COMMAND
        0x0300,  # EN_CHANGE
        EDIT_ID,
        EDIT_ID,
        0x35,  # AfxSig_vv
        assembled.label_va("handler"),
    )
    body[_ENTRIES_OFF : _ENTRIES_OFF + len(_STOCK_ENTRIES)] = _STOCK_ENTRIES
    offset = _ENTRIES_OFF + len(_STOCK_ENTRIES)
    body[offset : offset + len(entry)] = entry
    return bytes(body) + assembled.finish()


class WorldbuilderObjectTypeaheadPatch(Patch):
    """Let Worldbuilder's object picker be typed into instead of hunted through."""

    name = "worldbuilder-object-typeahead"
    author = "officialNecro"
    description = (
        "Worldbuilder.exe (not game.dat): add a type-ahead box above the object tree in the "
        "dialog every script action's object argument opens, so a name can be typed instead of "
        "found by hand through collapsed folders. Each keystroke selects the first tree item "
        "whose label matches - exact, then prefix, then substring, case-insensitively, leaves "
        "before folders - and clears the selection when nothing matches, so Enter and OK keep "
        "reading the selected item exactly as they do now. Needs no INI, map or .str change"
    )

    def apply(self, data: bytearray) -> None:
        self._check_not_rebased(data)
        self._check_anchors(data)
        section_va = allocate_section(data, SECTION_NAME, build_section, _CHARACTERISTICS)
        apply_byte_patch(
            data,
            self._offset(data, TEMPLATE_VA),
            STOCK_TEMPLATE,
            PATCHED_TEMPLATE,
            f"IDD 190 dialog template @0x{TEMPLATE_VA:08x}",
        )
        for va in MESSAGE_MAP_SITES:
            apply_byte_patch(
                data,
                self._offset(data, va),
                self._load_map(_STOCK_MESSAGE_MAP),
                self._load_map(section_va + _MSGMAP_OFF),
                f"GetMessageMap @0x{va:08x} -> {SECTION_NAME} cave",
            )

    def verify(self, data: bytes | bytearray) -> list[str]:
        located = find_section(data, SECTION_NAME)
        if located is None:
            return [f"no {SECTION_NAME} section: the file does not carry this patch"]
        section_va, section_off, _vsize = located

        problems: list[str] = []
        expected = build_section(section_va)
        got = bytes(data[section_off : section_off + len(expected)])
        if got != expected:
            problems.append(
                f"the {SECTION_NAME} cave does not match what this patch builds for base "
                f"0x{section_va:08x}"
            )

        off = va_to_offset(data, TEMPLATE_VA)
        if off is None:
            problems.append(f"0x{TEMPLATE_VA:08x} is not mapped")
        elif bytes(data[off : off + len(PATCHED_TEMPLATE)]) != PATCHED_TEMPLATE:
            problems.append(
                f"the IDD 190 template @0x{TEMPLATE_VA:08x} is not the one this patch writes - "
                "the edit control is missing or the dialog is a different build's"
            )

        wanted = self._load_map(section_va + _MSGMAP_OFF)
        for va in MESSAGE_MAP_SITES:
            off = va_to_offset(data, va)
            if off is None:
                problems.append(f"0x{va:08x} is not mapped")
                continue
            found = bytes(data[off : off + len(wanted)])
            if found != wanted:
                problems.append(
                    f"GetMessageMap @0x{va:08x} is {found.hex()}, expected {wanted.hex()}"
                )
        return problems

    @classmethod
    def detect(cls, data: bytes | bytearray) -> WorldbuilderObjectTypeaheadPatch | None:
        if find_section(data, SECTION_NAME) is None:
            return None
        patch = cls()
        return None if patch.verify(data) else patch

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """No options: the control, its id and the match order are all fixed by the dialog."""

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> WorldbuilderObjectTypeaheadPatch:
        return cls()

    @staticmethod
    def _load_map(map_va: int) -> bytes:
        """``mov eax, <AFX_MSGMAP>`` - the whole of what both `GetMessageMap` bodies do."""
        return b"\xb8" + _u32(map_va)

    @staticmethod
    def _offset(data: bytes | bytearray, va: int) -> int:
        off = va_to_offset(data, va)
        if off is None:
            raise ValueError(f"0x{va:08x} is not mapped - not the expected build")
        return off

    @staticmethod
    def _check_anchors(data: bytes | bytearray) -> None:
        for va, expected in ANCHORS.items():
            off = va_to_offset(data, va)
            if off is None:
                raise ValueError(f"0x{va:08x} is not mapped - not the expected build")
            got = bytes(data[off : off + len(expected)])
            if got != expected:
                raise ValueError(
                    f"0x{va:08x} holds {got.hex()}, expected {expected.hex()} - this build's "
                    "object picker is not the one the handler was written against, so the cave "
                    "would be dispatched from the wrong map or steer the wrong control"
                )

    @staticmethod
    def _check_not_rebased(data: bytes | bytearray) -> None:
        """Raise if the loader could move the image. The cave reads two import slots by absolute
        address and hands MFC an absolute pointer to its own message map, none of which carry
        base-relocation entries."""
        e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
        dll_characteristics = struct.unpack_from("<H", data, e_lfanew + 24 + 70)[0]
        if dll_characteristics & _DYNAMIC_BASE:
            raise ValueError(
                "the image opts in to ASLR (DllCharacteristics DYNAMIC_BASE), so the absolute "
                "addresses this cave uses would move under it - refusing rather than writing a "
                "message map the dialog would dispatch through into nothing"
            )
