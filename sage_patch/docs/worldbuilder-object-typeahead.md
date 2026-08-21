# A type-ahead box for Worldbuilder's object picker

The derivation behind the `worldbuilder-object-typeahead` patch: an edit box above the object tree
in the dialog every script parameter of type "object" opens, so a name can be typed instead of
hunted for through collapsed folders. Addresses recovered statically from the shipped
`Worldbuilder.exe` (ImageBase `0x400000`, RotWK 2.01) with `pefile` + `capstone`, read from
`Worldbuilder.exe.pristine.bak` rather than the installed copy, which already carries patches.

**This patch targets `Worldbuilder.exe`, not `game.dat`.**

## 0. What the dialog is

One class, `EditObjectParameter`, from
`E:\Builds\BFME2X\Code\production\Code\Tools\WorldBuilder\src\EditObjectParameter.cpp` - the build
path is still in the binary, next to the class vtable. It is reached from exactly two places, both
inside `EditParameter::edit` (the big `switch` on `param->m_type` that every script action and
condition argument goes through):

| call site | parameter type | what it sets |
|---|---|---|
| `0x004F4238` | `*(int*)param == 0x0F` | `this+0xD0 = 0` - objects only |
| `0x004F429B` | `*(int*)param == 0x3D` | `this+0xD0 = 1` - objects **and** object lists |

So "many scripts" is one dialog serving two parameter kinds, and a change here reaches every script
argument that names an object type. Sibling pickers (teams, waypoints, script names) are separate
classes in separate `.cpp` files and are **not** touched by this patch; the same technique ports to
them one class at a time.

## 1. The dialog, as it exists

`IDD` 190, a `DLGTEMPLATEEX`, 146x178 dlu, `WS_THICKFRAME` (it is resizable), no `WS_SYSMENU`.

| what | where |
|---|---|
| `RT_DIALOG` id 190, `IMAGE_RESOURCE_DATA_ENTRY` | file offset `0x01EA0640` (RVA `0x01EFF640`) |
| template data | RVA `0x01F51E60`, file offset `0x01EF2E60`, **292 bytes** |
| caption | `"Edit object parameter."` |
| `IDC_OBJECT_GROUP` group box `"Object:"` | id 1133, rect (7, 7, 131, 145) |
| the tree | id **1175 = `0x497`**, `SysTreeView32`, rect (15, 20, 114, 126) |
| OK / Cancel | id 1 / id 2, at y=157 |

| member | offset | recovered from |
|---|---|---|
| `CTreeCtrl m_objectTreeView` | `this+0x7C` | `DoDataExchange`, `0x004F2920` - `DDX_Control(pDX, 0x497, this+0x7C)` |
| the tree's `HWND` | `this+0x9C` | every `SendMessageA` in the class (`m_hWnd` is `CWnd+0x20`) |
| the `Parameter*` being edited | `this+0x78` | ctor arg 2, `0x004F27CC` |
| parent `CWnd*` | `this+0x74` | ctor arg 1 |
| "include object lists" | `this+0xD0` | set by the caller after construction |
| `DialogLayoutManager` | `this+0xD4` | `0x004AEC00`, asserts name the class |

| function | address | note |
|---|---|---|
| ctor | `0x004F2780` | `push 0; push 0xBE; call CDialog::CDialog` |
| `DoDataExchange` | `0x004F2920` | vtable slot 63 |
| `GetMessageMap` | `0x004F2950` / `0x004F2960` | both return `0x01DF2050`, as `mov eax, imm32` |
| `OnInitDialog` | `0x004F2980` | vtable slot 83 |
| `addObject` | `0x004F2B20` | one call per `ThingTemplate` |
| `OnDestroy` | `0x004F2AF0` | saves window placement under `"EditObjectParameter"` |
| `OnNotify` | `0x004F33B0` | vtable slot 61, already an override - see §4 |
| `OnOK` | `0x004F34C0` | vtable slot 85 |
| `OnSize` | `0x004F3690` | message map |

Message map at `0x01DF2050`, entries at `0x01DF2060`: **two entries and a terminator**, `WM_DESTROY`
and `WM_SIZE`. Nothing in the map touches the tree, IDOK or IDCANCEL.

## 2. How the tree gets filled

`OnInitDialog` walks `TheThingFactory`'s template list and calls `addObject` for each:

```
004f2a51  mov ecx, [0x022C9640]     ; TheThingFactory
004f2a57  mov edx, [ecx + 0x0C]     ;   first template
004f2a62  mov ecx, [eax + 0x494]    ;   next template
004f2a78  call 0x004F2B20           ;   addObject(template)
```

`addObject` places each template under two levels of folder:

- level 1 - the template's **side** (`ThingTemplate+0x6C`, an `AsciiString`); empty side raises the
  `!side.isEmpty()` / `NULL default side in template` assert and falls back to `""`;
- level 2 - the **editor sorting** byte at `ThingTemplate+0x604`, indexed into a 16-entry name table
  at `0x02219CE0`; out of range spells `UNSORTED`;
- the leaf - `TVM_INSERTITEM` with `hInsertAfter = TVI_SORT`, `mask = TVIF_TEXT|TVIF_PARAM`,
  `pszText = ThingTemplate+0x64` (the template name) and **`lParam = 0`**.

Two consequences that shape the patch: the item text *is* the object name, character for character;
and no item carries a back-pointer to its `ThingTemplate`, so nothing downstream can be resolved
from the selection except through that text.

## 3. How OK reads the result - the fact the whole design rests on

`OnOK` (`0x004F34C0`) does exactly this:

```
004f34ec  SendMessageA(tree, TVM_GETNEXTITEM, TVGN_CARET, 0)
004f350b  je -> MessageBeep(0x30) and return          ; nothing selected: stays open
004f354b  SendMessageA(tree, TVM_GETITEM, ...)        ; mask 0x1D, 0x102-char buffer
004f3570  AsciiString(buffer)                         ; text -> AsciiString
004f35cf  (*(this+0x78) + 0x10) = that string         ; store into the Parameter
004f35ef  CDialog::OnOK                               ; EndDialog(IDOK)
```

It reads the **selected item's label text** and nothing else. It does not consult `lParam`, does not
ask `TheThingFactory` whether the name exists, and does not check that the item is a leaf - selecting
a side folder called `Gondor` writes `Gondor` into the script as happily as a real object name.

That is what makes the small design work: **anything that moves the tree's caret is a complete
implementation of "type the name"**. The accept path needs no patch at all, so the patched dialog
cannot produce a value the stock dialog could not, and a typo that matches nothing produces no
selection - which the stock beep already handles.

## 4. The patch

Implemented in
[`../patches/worldbuilder_object_typeahead.py`](../patches/worldbuilder_object_typeahead.py) as
`worldbuilder-object-typeahead`.

### 4.1 The control - an in-place resource edit

One `EDIT`, id **`0x7000`** (the highest id anywhere in the 109 dialogs is 1538, plus two AFX ids;
`0x7000` collides with nothing), at (15, 20, 114, 12), with the tree moved down to
(15, 35, 114, 111). Everything else keeps its rect, so the group box, OK and Cancel do not move and
the `DialogLayoutManager` anchors, which are keyed by control id, keep working for the tree.

The edit goes in as the **second** item, after the group box: it is the first `WS_TABSTOP` either
way, so it still takes focus when the dialog opens, and leaving the group box first keeps the
z-order the stock dialog already paints correctly.

The template stays **exactly 292 bytes**, so the `IMAGE_RESOURCE_DATA_ENTRY` at file offset
`0x01EA0640` needs no edit at all. A fifth `DLGITEMTEMPLATEEX` for an `EDIT` costs 32 bytes (24-byte
header, `0xFFFF 0x0081` class ordinal, empty title, zero creation data, DWORD-aligned), and the
caption pays for it: `"Edit object parameter."` is 46 bytes of UTF-16 and `"Object"` is 14, which
frees exactly 32. Because the saving is a multiple of four, every item stays on the DWORD boundary
it was already on.

The rejected alternative was dropping the `"Object:"` group box to make room, which keeps the item
count at 4 and costs the frame around the tree. Relocating the template into the cave (rewriting
`OffsetToData`/`Size` in the data entry) stays available as the stretch version - it is what a nicer
layout with a `"Filter:"` static label would need.

### 4.2 The behaviour - extend the message map, do not subclass

`GetMessageMap` returns `0x01DF2050` from two `mov eax, imm32` sites (`0x004F2953`, `0x004F2967`) -
the static `GetThisMessageMap` and the virtual `GetMessageMap`, and MFC reaches the map through
either, so both are repointed at an `AFX_MSGMAP` in the cave whose entry array is the stock two
entries, plus one more, plus the terminator:

```
msg = 0x0111 (WM_COMMAND)   code = 0x0300 (EN_CHANGE)
id  = 0x7000 .. 0x7000      sig  = 0x35   pfn = <cave handler>
```

`pfnGetBaseMap` stays `0x016C2030`, so the base-class chain is untouched. The encoding is not
guessed: the neighbouring class's map, 0x3C4 bytes further into `.rdata`, carries a literal
`ON_EN_CHANGE` entry in exactly this shape (`msg=0x111 code=0x300 sig=0x35`). Signature `0x35` is
`AfxSig_vv`, so the handler is a plain `void (CWnd::*)()`: `this` in `ECX`, no arguments, no return.

This buys the whole feature with **no window subclassing, no `SetWindowLongA`/`CallWindowProcA`,
no vtable rewrite and no new imports**. Everything the handler needs is already in the import table:
`SendMessageA` (`0x022F54D0`) and `SendDlgItemMessageA` (`0x022F55BC`), which is the whole list -
reading the box through `SendDlgItemMessageA` saves even the `GetDlgItem` call. No `GetProcAddress`
dance, which matters because `CreateWindowExA`, `SetWindowLongA`, `CallWindowProcA` and
`GetWindowTextA` are all **absent** from Worldbuilder's user32 imports.

### 4.3 The handler

```
onFilterChanged():                                     ; ecx = the dialog, pushad/popad around it
    tree = this+0x9C;  if tree == 0: return            ; EN_CHANGE before DDX ran
    SendDlgItemMessageA(this+0x20, 0x7000, WM_GETTEXT, 0x100, needle)
    if nothing was copied: return                      ; empty box: leave the selection alone
    fold the needle to lower case, once
    best = 0, score = 0
    node = TVM_GETNEXTITEM(TVGN_ROOT)
    while node:                                        ; pre-order, no stack
        child = TVM_GETNEXTITEM(TVGN_CHILD, node)
        text  = TVM_GETITEM(node).pszText
        rank  = 3 if equal, 2 if prefix, 1 if substring, else 0       ; case-insensitive
        if rank and rank*2 + (child == 0) > score:     ; the leaf bit breaks ties
            best, score = node, rank*2 + (child == 0)
        if score == 7: break                           ; an exact leaf cannot be beaten
        node = child or TVM_GETNEXTITEM(TVGN_NEXT) or climb TVGN_PARENT until one has a sibling
    SendMessageA(tree, TVM_SELECTITEM, TVGN_CARET, best)   ; best == 0 clears the selection
    if best: SendMessageA(tree, TVM_ENSUREVISIBLE, 0, best)
```

Selecting an item expands its ancestors and scrolls it into view for free, so the tree becomes a
live preview of what OK will write. Clearing the selection on no match is deliberate: it turns a
typo into the stock "nothing is selected" beep instead of quietly accepting whatever was highlighted
before the typo.

Enter needs no code. The edit has no `ES_WANTRETURN`, so `IsDialogMessage` sends Enter to the default
button, which is IDOK, which reads the caret we just set.

Cost per keystroke is two `SendMessageA` per tree item - same thread, no marshalling - so a
4,000-template Edain tree is ~8,000 in-process messages, a low single-digit number of milliseconds.
If that ever reads as lag, the fix is to rank on the first keystroke only and re-rank incrementally,
not to change the design.

### 4.4 Case-insensitive compare

Hand-rolled in the cave, roughly 15 instructions. `lstrcmpiA` is imported but compares whole strings;
`CharUpperBuffA` is not imported at all. ASCII folding is correct here - object names are ASCII
identifiers.

## 5. What this deliberately does not do

- **It does not filter the tree.** Hiding non-matching items means deleting and reinserting tree
  items on every keystroke, which is destructive, slow, and loses the expansion state. Jump-to-match
  keeps the tree exactly as it is.
- **It does not make the typed text authoritative.** An alternative design hooks `OnOK` at
  `0x004F34EC`, copies the edit text into the stack buffer at `[ebp-0x14C]` and jumps to `0x004F3569`
  to reuse the existing `AsciiString` store - about 20 bytes of cave code, the smallest possible
  patch. It is rejected as the primary because it accepts any typed string, including a misspelling,
  and validating would then mean calling into `TheThingFactory` to keep the guarantee that §3 gives
  for free. It stays recorded here as the fallback if the tree walk ever misbehaves.
- **It does not register the edit with the `DialogLayoutManager`.** The anchor table passed at
  `0x004F29FD` (`push 0x022931C4; push 4`) lives in `.data`'s zero-fill tail, past the raw data, so
  it is filled at runtime and cannot be extended by a static byte patch - a cave copy of 4x8 bytes at
  `OnInitDialog` time would be needed. Until then the edit keeps its width when the dialog is
  resized while the tree stretches. Cosmetic; scoped as stretch work.
- **It does not touch the other parameter pickers.** See §0.

## 6. Risks

| risk | weight | handling |
|---|---|---|
| Template rewrite breaks the dialog | low | in-place, size-preserving; a wrong template fails loudly at `DoModal` |
| `EN_CHANGE` fires during `DDX`/init before the tree exists | low | the handler returns when `this+0x9C` is still null |
| Two dialogs open at once sharing the cave text buffer | none | modal, and the buffer is only live inside the handler |
| Message map redirect collides with another patch | none | no bundled patch touches `EditObjectParameter` |
| Composition | none | cave via `allocate_section`, two `imm32` sites, one resource blob - all disjoint from `worldbuilder-mod`, `worldbuilder-label-assert`, `worldbuilder-silent-errors` and the five `-wb` twins |

## 7. What shipped

| piece | where |
|---|---|
| the patch | [`../patches/worldbuilder_object_typeahead.py`](../patches/worldbuilder_object_typeahead.py) |
| registry entry | `worldbuilder-object-typeahead`, author `officialNecro`, non-experimental |
| tests | `tests/sage_patch/test_worldbuilder_object_typeahead.py`, against `worldbuilder_object_typeahead_image()` - the first synthetic stand-in that plants a resource |

The cave is `.wbtype`, `0x4A4` bytes: two `0x104`-byte text buffers, a `TVITEM`, the leaf flag, the
`AFX_MSGMAP` and its four entries, then `0x204` bytes of code in three routines. `apply` writes three
things and nothing else - the template, and the two `mov eax, imm32` sites - and `verify` re-reads
all three plus the whole cave, which it locates with `find_section` rather than recomputing.

Checked against the real `Worldbuilder.exe.pristine.bak`: applies, verifies, `detect` recognises it,
the rewritten `IDD` 190 reparses as a five-control template, and all 24 orderings of this patch with
`worldbuilder-mod`, `worldbuilder-label-assert` and `worldbuilder-silent-errors` apply with all four
verifying afterwards.

## 8. Open questions for the live dialog

Two things static reading cannot settle, both answerable by opening the picker once:

1. **Does the dialog preselect the parameter's current value?** No selection code appears in
   `OnInitDialog`, which would mean re-opening a parameter that already names an object starts with
   an empty caret. If it does preselect, something outside the class is doing it and the handler must
   not fight it on the first `EN_CHANGE`.
2. **How deep is the tree in practice?** §2 says side then editor-sorting category then object, so
   three levels. Confirming the folder names (and whether Edain leaves most templates in `UNSORTED`)
   decides whether ranking should prefer leaves as strongly as §4.3 assumes.
