# TextEntry clipboard — RotWK 2.01

`TextEntryClipboardPatch` (`text-entry-clipboard`) adds Ctrl+A/C/X/V to existing
`GadgetTextEntry` fields. `runtime_verified`.

```python
from sage_patch import TextEntryClipboardPatch, apply_patches

apply_patches("game.dat", [TextEntryClipboardPatch()], "game-clipboard.dat")
```

The CLI exposes the same patch as `sage-patch apply text-entry-clipboard`; use its `--help`
for input/output options. Preserve the original binary and test an output copy first.

## Hook and build contract

All VAs target x86 RotWK 2.01, ImageBase `0x00400000`. RVAs are VA minus ImageBase.
PE32 magic, machine, preferred base and the absence of DYNAMIC_BASE are checked. Rebasing
this engine is unsupported; no process-specific Windows export address is written to disk.

| VA | RVA | Meaning |
| --- | --- | --- |
| `0x00722745` | `0x00322745` | GadgetTextEntryInput |
| `0x00722A8A` | `0x00322A8A` | Eight-byte hook |
| `0x00722B87` | `0x00322B87` | Original continuation |
| `0x007220D3` | `0x003220D3` | GadgetTextEntrySetCursorPosition |
| `0x007224D8` | `0x003224D8` | GadgetTextEntryUpdateComposition (used internally) |
| `0x0072260B` | `0x0032260B` | GadgetTextEntryInsertCharacter (used internally) |
| `0x00DA1BDC` | `0x009A1BDC` | Name pointer in registration |
| `0x00DA1BE0` | `0x009A1BE0` | Input function pointer in registration |
| `0x00C18814` | `0x00818814` | GadgetTextEntryInput name |
| `0x00C189E8` | `0x008189E8` | GadgetTextEntrySystem name |
| `0x00DE495C` | `0x009E495C` | GameWindowManager pointer |
| `0x00DE433C` | `0x009E433C` | IMEManager pointer |

The hook verifies `89 55 0C E9 F5 00 00 00` and writes a relative JMP plus three NOPs.
The stock Ctrl+Left/Right branches occur before this fallback and remain untouched.
Other keys, key-up, missing Ctrl and Alt/AltGr restore all saved registers/flags, execute
`mov [ebp+0x0c],edx`, and jump to `0x00722B87`. Recognized shortcuts set status 1, including
empty selection and API-failure no-ops. Shift does not disable these shortcuts.

`.txtclip` is allocated past all existing PE sections through `allocate_section`. Its
permissions are execute/read, with initialized data and code; it has no writable globals.
Apply builds on a temporary image, so failures are atomic even when section-header space is
exhausted. Duplicate application or a changed hook raises before mutation. Verify/detect
compare the entire generated cave, hook and unchanged ABI anchors.

A source search found no existing patch changing this eight-byte hook. Composition with
`SlavedUpdateIdlePatch` is tested in both orders against the original binary. Unknown future
patches sharing the hook are rejected by the byte contract.

## Engine ABI and strings

The hook keeps the original EBP: `[ebp+8]` is GameWindow, `[ebp+0x10]` the scancode and
`[ebp+0x14]` the modifier word. ESI is EntryData. `pushfd/pushad` preserve all integer
registers and flags; 80 private stack bytes hold operation state and resolved API pointers.
EDI points to that storage and remains preserved by the engine and Win32 callees.

Binary evidence from `tools/BFME-FILES/game.dat.backup` (SHA-256
`5481de75b63e22483660ea8097478faef594f90b9ade7de893e092256ba68a26`):

- `0x0072264E`: virtual `getText` at slot +8 receives a hidden result pointer on the
  stack, which the callee pops. The returned object is one backing-header pointer;
  the WORD length is at header+4. Slot +12 returns the text length.
- `0x00437881`: StringBase substring uses `lea esi,[edi+8]`, then indexes UTF-16 by
  twice the character offset. Characters are **inline at backing+8**, not reached
  through another pointer stored there.
- `0x004367ED`: the existing `UNICODE_STRING_DTOR` (`0x004367B0`, thiscall) decrements
  the backing reference, calls the engine allocator's free function at zero, and clears
  the pointer. The hook calls that destructor on every path after obtaining the temporary.

These three byte sequences are checked before patching; no independent string allocator
or guessed reference-count operation is introduced.

Copy/cut refuse secretMode (+0x12). Selection endpoints (+0x1c/+0x1e) are unsigned WORDs,
ordered and clamped against both virtual length and backing length. Empty selection does
nothing. Copy allocates `2*(count+1)` bytes, writes exactly the selected UTF-16 units and
one UTF-16 NUL. Only successful SetClipboardData permits cut, which sends GWM_CHAR 0x15,
KEY_DEL 0xd3, KEY_STATE_DOWN 2 to the original handler after closing the clipboard and
releasing the temporary string. That handler owns selection deletion and notifications.

Select-all uses the original virtual length and cursor setter, then sets the anchor to zero.
Paste sends each accepted unit through GWM_IME_CHAR 0x19 to the original input handler, so
validation, length enforcement, selection replacement, secret rendering and text-change
notifications remain engine responsibilities. Tabs, CR/LF and all units 0xd800–0xdfff are
skipped. Normal BMP characters, including German umlauts, are preserved. The read bound
is min(4096, GlobalSize(handle)/2), including filtered units; a missing terminator never
causes a read past the allocation. This intentionally skips non-BMP emoji rather than
inserting isolated surrogates. Other BMP format/control characters retain CE behavior.

## Win32 resolution and ownership

The PE import directory must identify `kernel32!GetModuleHandleA` at `0x00BD0134` and
`kernel32!GetProcAddress` at `0x00BD018C`. For each clipboard hotkey the handler borrows
already loaded user32/kernel32 module handles and resolves all named exports into private
stack slots. Missing modules/exports are safe no-ops. There is no LoadLibrary reference
leak, shared cache, import-directory modification or hardcoded Windows export address.

Resolved user32 exports: OpenClipboard, GetClipboardData, SetClipboardData, EmptyClipboard,
CloseClipboard, GetForegroundWindow. Kernel32 exports: GlobalAlloc, GlobalFree, GlobalLock,
GlobalUnlock, GlobalSize. All are stdcall and pop their own arguments.

Paste uses OpenClipboard(NULL) and never frees the borrowed clipboard handle. Copy opens
with GetForegroundWindow's HWND: [Microsoft documents](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setclipboarddata)
that NULL ownership after EmptyClipboard causes SetClipboardData to fail. Allocation and
population happen before EmptyClipboard. An owned allocation is freed on failure; after
successful SetClipboardData the local handle is cleared because Windows owns it. Successful
open/lock operations are paired with close/unlock on every path. GlobalUnlock's zero return
is not treated as failure: it can indicate the final unlock succeeded.

## Automated validation and remaining acceptance

The data-free tests execute the actual generated x86 in Unicorn with synthetic engine
objects and Win32 callbacks that clobber volatile registers. They cover selection bounds,
empty/full/reversed selection, secret fields, UTF-16 termination, surrogate filtering,
allocation bounds, API lookup failures, clipboard failure paths, memory ownership,
integer-register/flags preservation and stack balance. Capstone checks instruction
coverage and all branch destinations at two different cave VAs. PE tests cover address
mapping, hook offsets, unrelated original bytes, rejection and atomic repeat application.
The optional `--full` test checks actual RotWK bytes and both SlavedUpdate composition orders.

Run:

```text
python -m pytest tests/sage_patch/test_text_entry_clipboard.py --full -q -p no:faulthandler
```

On this Windows Unicorn build, pytest's faulthandler reports native access violations
handled internally by Unicorn during memory allocation; disabling that pytest plugin
avoids misleading dumps. Assertions and emulator errors remain enabled.

Validation on 2026-10-14: 96 focused tests passed with `--full`, including actual binary
application and composition. The broader patch/public-surface/layering run passed 9,558 tests
with 413 skipped and 80 deselected. Ruff passes for the changed Python files and this document;
mypy passes across 686 source files. CLI application and verification passed. A byte comparison
of the real output found changes only in the eight hook bytes and PE headers, plus appended
section content. The test output is `_local/game-text-entry-clipboard.dat`; no installed game
binary was replaced.

The repository-wide core run passed 14,903 tests, with 576 skipped and 750 deselected,
but initially reported 16 failures and eight setup errors. Fifteen failures were caused by
sandbox restrictions on the system temporary directory; all fifteen passed when rerun with
TEMP/TMP inside the workspace. The eight local HTTP editor fixtures cannot connect because
of WinError 10013. The remaining documentation-link test uses `git ls-files` and rejects the
new, unstaged documentation (including the pre-existing SlavedUpdate files). Checking the
same references with those pending files included passed. The Git index was left untouched.
Thus the raw full core run is not green; the focused patch and regression runs are green.

The following runtime checks are **not yet performed for this generated patch**:

- Chat and menu fields: Ctrl+A/C/X/V; copy both directions between RotWK and Windows Editor.
- Replace partial/full selections, both selection directions; no selection means no copy/cut.
- Umlauts ÄÖÜäöüß; Discord emoji omitted; ordinary BMP characters still insert.
- Ctrl+Left/Right, Shift shortcuts, key release, right Ctrl, AltGr and existing shortcuts.
- MaxTextLen and character validation; paste at limit and into secret/password fields.
- Secret fields never export text through copy/cut; IME composition behaves correctly.
- Clipboard contention with another application; cut never deletes on failed copy.

Emulation stubs model engine calls and Windows APIs; they do not prove real HWND ownership,
actual game notifications, IME interaction, glyph availability or clipboard reentrancy.
Win32 close/unlock/free failures cannot be repaired generically here. Resolver caching and
additional BMP format/glyph filtering may be investigated separately after in-game acceptance.
