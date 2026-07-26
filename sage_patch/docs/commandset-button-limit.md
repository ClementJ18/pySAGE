# The `CommandSet` button limit — reverse-engineering notes

How the SAGE engine (BFME2 / *The Battle for Middle-earth II: Rise of the Witch-King*,
patch **2.01.2614**, `game.dat`) enforces its **command-buttons-per-`CommandSet`** limit
(stock **33**), why adding a button past it aborts with an engine error, and the complete
surface that has to change to raise it to an arbitrary **N** — engine **and** APT UI.

The applied patch that implements this — generalised to any N in 34..127 — is
[`patches/commandset.py`](../patches/commandset.py) (`CommandSetLimitPatch(count=N)`); this doc
is the reverse-engineering behind it. Paging past the on-screen 33 once a set holds more is
covered in [`push-visible-command-range.md`](push-visible-command-range.md).

> Scope: static analysis of a game the author owns, for modding. Addresses are for
> `game.dat` v2.01.2614.37001 (T3A/Edain community patch), ImageBase `0x00400000`.
> They will differ in other builds; the *method* (below) relocates them.

## TL;DR

- The cap is `MAX_COMMANDS_PER_COMMAND_SET = 33`. A `CommandSet` object stores
  `CommandButton* m_command[33]` at struct offset `+0x14`; `sizeof(CommandSet) = 0xA0`.
- Adding `34 = Command_X` to a `CommandSet` block makes the INI loader fail its field
  lookup and throw **`"Unknown field '34' in block 'CommandSet'…"`** — a *fatal parse
  error*, which is the "error message from the engine" seen on load.
- **`33` is hard-coded in code, not read from a constant** — the field-parse table length,
  five immediates inside the `CommandSet` class, the `0xA0` allocation size, **and 42
  separate consumer functions** that iterate the array with a literal `cmp r32,0x21` bound.
  None of the consumers read the object's own count field.
- **Just to stop the crash** and let INI define >33 buttons: ~4 edits.
- **To make all N buttons actually work everywhere:** ~**50 machine-code sites**, almost all
  1-byte `0x21 → N` immediates, plus one table relocation and growing the object.
- **UI:** the in-game command bar is **APT-driven** (`AptControlBar`/`PalantirCommandUI`,
  `InGameSideCommandBar`), buttons are **created dynamically** (`attachMovie`/
  `duplicateMovieClip`), so the `.apt` movie isn't hard-capped by hand-placed slots — but
  the engine's Apt populate loops are themselves among the 42 literal-33 loops, and on-screen
  space/layout for a vertical side bar is the real UI constraint.

## Method / tooling

- **pySAGE** (`sage_apt`, `pyBIG`) to pull and decompile APT UI and read `.big` archives.
- **pefile + capstone** (installed into the repo venv) for PE mapping, offset⇄VA, byte-pattern
  and superset disassembly, and cross-reference scans.
- **Ghidra 12.1.2** headless (`analyzeHeadless`) for authoritative auto-analysis, the
  decompiler, and function-boundary / xref classification. Ghidra 12 needs **JDK 21**;
  a portable Temurin 21 was used. Note `analyzeHeadless.bat` chokes on the `(x86)` in the
  install path — import a copy of `game.dat` from a paren-free path.
- `game.dat` is an **unpacked** PE32 (SecuROM wrapper sections `stxt774/.mackt/.danetta`
  exist but `.text`/`.rdata` are readable at rest) and **debug-instrumented** (assertion
  strings intact), which makes both string- and xref-driven RE straightforward.

## The limit and the crash

`CommandSet` is a top-level INI block; each button slot is a **numbered field** (`1`..`N`):

```
CommandSet FooCommandSet
  1 = Command_A
  2 = Command_B
  ...
  33 = Command_Z
End
```

- Block parser **`parseCommandSetDefinition`** @ `0x007205b9` (Ghidra `FUN_007205b9`):
  finds-or-creates the named set, then calls
  **`initFromINI(commandSet, &fieldTable@0xc4f3d8)`** at `0x00720664`.
  It also owns the `"Duplicate commandset '%s' found!"` throw (@`0x00c233e0`).
- **Field-parse table @ `0x00c4f3d8`** — stride 16, entries `{char* name, parseFn,
  userData, offset}`. Exactly **33** slot entries named `"1"`..`"33"`, each:
  - `parseFn = parseCommandButton` @ `0x0080c9e1`
  - `userData = slot index 0..32`
  - `offset  = 0x14` (the `m_command` array base within the object)

  Entry 34 = `"InitialVisible"` (fn `0x0042ec5e`, offset `0x98`); entry 35 = NULL terminator.
- **`parseCommandButton`** @ `0x0080c9e1`: resolves the button name, then stores
  `*(store + userData*4) = button` — i.e. `m_command[index] = button`. **No per-call range
  check**; the 33-slot range is gated *solely* by which names exist in the field table.
  (It only throws `"Unknown command '%s' found in CommandSet '%s'"` (@`0x00c4f68c`) when the
  *button* name is unresolved — a different error.)

**Why >33 is a hard error, not a silent truncation:** `initFromINI` looks each field name up
in the 33-entry table. `"34"` is absent, so it raises the generic INI failure
**`"Unknown field '%s' in block '%s'."`** (@`0x007d3e98`) →
**`"Error parsing field '34' in block 'CommandSet' in file '…', line …"`** (@`0x007d3ebb`),
which aborts data loading.

## Object layout & allocation

Allocated via `operator new(0xA0)` — `push 0xa0 ; call 0x0042f6e0` @ `0x00720298`
(`FUN_0072028b`), then the constructor @ `0x0080c949`.

Ghidra-decompiled constructor (`this` = `extraout_ECX`, dword-indexed):

```c
*this        = &PTR__scalar_deleting_destructor__00c4f688;  // vtable @ +0x00 (only a dtor slot)
StringBase::StringBase(this+0x10, name);                    // m_name @ +0x10
this[0x27]   = arg;                                          // +0x9c = ctor arg (initiallyVisible)
this[0x26]   = 0x21;                                         // +0x98 = 33  (slot-count field)
for (i = 0x21; i != 0; i--) *p++ = 0;                       // zero m_command[0..32] @ +0x14
```

| offset | field |
|--------|-------|
| `0x00` | vtable (`0xc4f688`) |
| `0x04`–`0x0f` | base / Overridable links |
| `0x10` | `AsciiString m_name` |
| **`0x14`–`0x97`** | **`CommandButton* m_command[33]`** (33 × 4 = `0x84`) |
| `0x98` | slot-count field (ctor sets = 33; `setCommandButton` bumps it) |
| `0x9c` | flag (ctor arg; `setCommandButton` guards on `== 1`) |
| → `0xA0` | end |

**`0x14 + 33·4 = 0x98` exactly** — the array is mid-struct with **zero slack**, immediately
followed by live fields. It cannot grow in place without shifting `0x98`/`0x9c` and enlarging
the `0xA0` allocation.

## The class accessors (one compiland, `0x0080c840`–`0x0080caa0`)

Array access funnels through a handful of methods, each carrying its own hard-coded 33:

| method | entry | detail |
|--------|-------|--------|
| `getCommandButton(i)` | `0x0080c837` | `mov eax,[esi+edi*4+0x14]` — returns `m_command[i]`, **no bound check** (trusts caller) |
| `setCommandButton(i,b)` | `0x0080c8ef` | `cmp edx,0x21` guard, writes `m_command[i]`, bumps count `+0x98` |
| `clearCommandButtons` | `0x0080c8e2` | `push 0x21 ; rep stosd` |
| reset / count | `0x0080c91b` | `push 0x21` loop |
| (slot-scan) | in `0x0080c8?? ` | `cmp ebx,0x21` @ `0x0080c8c6` |
| ctor | `0x0080c949` | `push 0x21` (`rep stosd`) @ `0x0080c97e` |
| `parseCommandButton` | `0x0080c9e1` | store `m_command[userData]` |

Five `0x21` immediates live in this compiland: `0x0080c8c6`, `0x0080c8e3`, `0x0080c8fc`,
`0x0080c91d`, `0x0080c97e`.

## Consumer loops — the broad part of the surface

`getCommandButton` @ `0x0080c837` has **59 call refs across 46 functions**. Classified by how
each bounds its slot loop (Ghidra `CommandSetCallers` script):

- **42 functions bound on the literal 33** (`cmp r32,0x21`)
- **0 read the object's count field** (`+0x98`)
- **4 use a fixed index** (no loop): `FUN_0061903f`, `FUN_0071f207`, `FUN_0071f97b`,
  `FUN_00822a98`

`setCommandButton` @ `0x0080c8ef`: 3 calls, all in `FUN_00809ffb` (`copyButtons`), which
bounds on the literal 33.

**Because no consumer reads the count field, every one of these 42 loops must have its bound
raised** for the extra buttons to be iterated / drawn — they don't scale automatically.

### The 42 literal-33 consumer functions (Ghidra `FUN_` entry, call count)

```
0x0061900a (1)  0x00691f7f (1)  0x00691fce (1)  0x00692a75 (1)  0x00697aeb (1)
0x006add22 (1)  0x0071efc8 (1)  0x0076fe16 (1)  0x00779a3d (2)  0x00793d57 (1)
0x00793e64 (1)  0x00794f38 (1)  0x007c3c88 (1)  0x007c3d61 (1)  0x007c46a0 (1)
0x007c6243 (1)  0x007c62bf (1)  0x007c6363 (1)  0x007c6793 (4)  0x007e5142 (1)
0x00809ffb (1)  0x0081df04 (1)  0x0081e60b (2)  0x0082dde1 (1)  0x0085d7fd (1)
0x00898b7c (1)  0x00898ee8 (1)  0x008b714f (1)  0x008ef572 (1)  0x008f7599 (1)
0x009312b9 (1)  0x0094251f (1)  0x00943d6f (3)  0x00944534 (2)  0x0099f94c (1)
0x009a018b (1)  0x009a155c (1)  0x009b62f6 (1)  0x009b64ac (2)  0x009b7458 (3)
0x009b8f84 (1)  0x009ed4d2 (1)
```

Indexed/other (fixed slot, no bound to change): `0x0061903f`, `0x0071f207`, `0x0071f97b`,
`0x00822a98`.

The `0x0092…`–`0x009e…` cluster is the **`Apt*` UI layer** (see UI section); the
`0x006x`–`0x008x` functions are the ControlBar / selection / AI consumers.

### Mirror array

The ControlBar/store object (ctor region `0x00720302`, fields out to `+0x2b0`) keeps its own
33-slot array (`push 0x21` @ `0x0072036e`, `0x007203df`). Patch if it caches a set's buttons
per-frame.

## UI / APT side

The in-game command bar is **APT-driven**, not the legacy Window/gadget system:

- Bridge class `AptControlBar` / `PalantirCommandUI`; engine callbacks
  `OnAptInGameSideCommandBarButtonFrameLoaded/Unloaded` (handler @ `0x0092f4c0`),
  `PalantirCommandUI::OnButtonFrameLoaded/Unloaded/SubMenuLoaded/ToggleFlash…`.
- The engine addresses clips by movie **path**, e.g.
  `PalantirButtons/Buttons/Objectives/ButtonClip/` (@`0x00c19424`, used from `0x006d6afb`),
  `SpellStore/Buttons/Spell%d` (@`0x00c50c20`).
- The `W3DCommandBar*Draw` strings are the **legacy** gadget path; only **5 `.wnd`** files
  exist across the archives, i.e. the in-game command UI does not come from `.wnd`.

Movie (`Palantir.apt` in `__edain_apt.big`, decompiled with `sage_apt to-xml`):

- Command buttons live in a **`CommandButtons`** container; the per-button artwork is a
  **`ButtonClip`** template, and the sub-menu / back panels are **imported from
  `libInGameUI`** (`CommandButtonSubMenu` char 106, `CommandButtonBacks` char 107).
- Buttons are **created dynamically** — the ActionScript uses `attachMovie` /
  `duplicateMovieClip` / a `CreateContent` method, not a fixed row of hand-placed slots.
  So the movie itself does **not** impose a low fixed cap.

**Net UI conclusion:** the "UI cap" is effectively the *same* engine literal-33 loops, but
located inside the `Apt*` populate code (`0x0092…`–`0x009e…` above). The `.apt` movie can
create more clips than 33 as-is; what actually constrains showing many more buttons is
(a) those engine populate bounds and (b) **on-screen space/layout** for a vertical side bar —
a design problem (paging / smaller icons / scrolling), not an APT format limit. If the goal is
merely "don't crash when a set defines >33," the movie likely needs **no** change.

## Raising the cap 33 → N — recommended approach

**A. Stop the crash / allow INI to define >33 (minimum):**

1. **Field table @ `0x00c4f3d8`** → N entries. No slack after entry 33, so relocate the whole
   table to a code cave / new section, add entries `"34".."N"` (`{name, 0x0080c9e1, index,
   0x14}`), and repoint the **single** consumer `push 0xc4f3d8` @ `0x0072065c`. Fix the
   `InitialVisible` entry's `offset` from `0x98` to the new array end.
2. **Allocation size** `push 0xa0` @ `0x00720298` → `0xa0 + (N-33)*4`.
3. **Constructor** `push 0x21` @ `0x0080c97e` → N (and the shifted `+0x98/+0x9c` offsets if
   grown in place).

**B. Make all N usable (full):** additionally bump the four other in-class `0x21` immediates,
and the **42 consumer loop bounds** (each a 1-byte `0x21 → N`), plus the mirror array.

**Simplifier — avoid the offset cascade:** move `m_command` to the **end** of the struct so
`+0x98/+0x9c` (and their accessors) don't move. Then only the array base (`0x14` in the table
+ the accessor displacements), the count/bound immediates, and the `0xA0` size change.

**Mechanical aids:** every "33 as bound/count" site is greppable by byte pattern — `6A 21`
(`push 0x21`) and `83 F8..FF 21` (`cmp r32,0x21`) — so this is a find-verify-replace sweep,
not a research problem. Risk is concentrated in *missing* a site: because the array is
followed by live fields, an unpatched write path corrupts the count/flag rather than crashing
cleanly; an unpatched *read* loop simply won't show the extra buttons.

## Effort estimate

| Goal | Sites | Nature |
|------|-------|--------|
| Stop the >33 load crash | ~4 | table relocate + alloc + ctor |
| All N buttons fully functional (engine) | ~50 | mostly 1-byte `0x21→N` + struct growth |
| Show >33 at once on screen (UI) | design | APT layout/paging + engine positioning; movie creates clips dynamically already |

Roughly an afternoon-to-a-few-days of binary patching for the engine (dominated by verifying
the 42 consumer loops), plus separate UI/layout work only if the goal is to *display* many
more buttons at once rather than merely to stop the crash.

## Key addresses (v2.01.2614.37001, ImageBase 0x00400000)

| what | address |
|------|---------|
| Field-parse table (33 slots) | `0x00c4f3d8` |
| Table's only code xref (`push`) | `0x0072065c` |
| `parseCommandSetDefinition` | `0x007205b9` |
| `initFromINI` call | `0x00720664` |
| `operator new(0xA0)` site | `0x00720298` |
| Constructor | `0x0080c949` (count immediate `0x0080c97e`) |
| `parseCommandButton` | `0x0080c9e1` |
| `getCommandButton` | `0x0080c837` |
| `setCommandButton` | `0x0080c8ef` |
| `clearCommandButtons` | `0x0080c8e2` |
| CommandSet vtable | `0x00c4f688` |
| Apt command-bar handler | `0x0092f4c0` |
| Error: unknown field | string `0x007d3e98` |
| Error: unknown command in set | string `0x00c4f68c` |
| Error: duplicate commandset | string `0x00c233e0` |
