# `-mod` is mounted after the first INI files are read

Why a `#define` changed in a loose (uncompiled) `-mod` tree has no effect, and what the
`mod-load-order` patch moves to fix it. Addresses recovered statically from `game.dat` build
`2.01.2614.37001` (ImageBase `0x400000`) with `pefile` + `capstone`. The ordering below is read
off the machine code, and the patch built from it is confirmed in a running game.

## 1. The symptom

Run an uncompiled mod with `-mod <folder>`. Loose edits to almost every `.ini` take effect.
Edits to a `#define` do not - the old value stays in force until the file carrying it is packed
into a `.big`.

The macro machinery itself is not at fault. `INI::load` (`0x0042CFC9`) makes a pre-pass over
every line of a file before parsing it, and each line that starts with `#define`
(`0x0042D0EC` tests it) is turned into a macro-table entry and then blanked out of the buffer
(`0x0042D104`). The table is `TheMacroTable`, a `std::map<AsciiString, AsciiString>` at
`0x00DC51D4`, inserted into at `0x0042D1F4`; the pre-pass runs over the line list **after**
`#include` expansion, so an included file's defines count as the includer's. Nothing about that
depends on where the bytes came from.

What differs is *when* the file is read.

## 2. The order inside `GameEngine::init`

`GameEngine::init` is `0x0063AD4F`. Four things happen in this order, and the fourth is the
problem:

```
0063af40  call 0x0063638F            ; register TheSubsystemLegend
0063af60  call 0x0042D97D            ; INI::load "Data\INI\Default\SubsystemLegendExpansion1.ini"
0063af65  push 0x1254 / call new     ; allocate GlobalData
0063af7d  call 0x006429AD            ;   ...and construct it
0063afa4  call 0x00636404            ; register TheWritableGlobalData -> loads its INI files
0063afb2  call 0x007BAA44            ; parse the startup switches, and mount the mod
```

`0x00636404` reaches `initSubsystem` (`0x005B4A7C`), which calls the subsystem's `vtbl+8`.
`GlobalData`'s vtable is `0x00C04220` and slot `+8` is `0x005B4B9A` - the legend-driven loader:
it looks the subsystem's name up in `TheSubsystemLegend` (`0x00DE337C`) and `INI::load`s
(`0x005B4C94`, load type 1) every `InitFile` and `InitPath` that entry declares. For
`TheWritableGlobalData` the legend declares:

```
LoadSubsystem TheWritableGlobalData
  Loader = INI
  InitFile = Data\INI\Default\GameData.ini
  InitFile = Data\INI\GameData.ini
End
```

So `GameData.ini` is read at `0x0063AFA4`. The mod is mounted fourteen bytes later.

## 3. What `0x007BAA44` does, and why nothing before it can see the mod

`0x007BAA44` is the whole of the mod pipeline in one function:

```
007baa4b  mov ebx, 0x00C35DA8        ; the 16-entry startup switch table (-mod, -preferLocalFiles, ...)
007baa56  call 0x007BA7E1            ; parseCommandLine(16, argc, argv) -> fills GlobalData+0xD38/+0xD3C
007baa90  call [TheArchiveFileSystem+0x14]   ; m_modBIG (GlobalData+0xD3C) -> mount that one archive
007baab8  call 0x00A14313            ; m_modDir (GlobalData+0xD38) -> the loose-file root
```

`0x00A14313` is what actually turns the mod on. It copies the directory into `0x00DEC498`, sets
the flag byte `0x00DEC490`, and mounts every `*.BIG` beneath it. Those two globals are the only
thing the file system consults:

| site | what it does when `0x00DEC490` is set |
|---|---|
| `FileSystem::openFile` `0x00A149A2` | tries `<modDir>\<file>` first (`0x00A14A1A` builds it), and on a hit resets the `File`'s name back to the logical one at `0x00A14A41` |
| `FileSystem::getFileInfo` `0x00A14B9A` | same, at `0x00A14C25` |
| `FileSystem::getFileListInDirectory` `0x00A14D2B` | scans `<modDir>\<dir>` at `0x00A14DCE` and reports the results under their *logical* names |

That last one is worth stating precisely, because it rules out the obvious alternative
explanation. The local walker is `0x00A18B2E`; it scans the path built from argument 3 but
inserts `(arg1 ? arg1 : arg3) + subdir + filename` into the set (`0x00A18BF8`), and the mod
branch passes the logical directory as arg1. So a file present both loosely and in a `.big`
yields **one** set entry, is loaded once, and `openFile` picks the loose copy. Loose files are
not double-loaded, and `#define` is never seen twice - a duplicate would not be quiet anyway,
it throws (`0x0042D246` formats `"%s:\nDuplicate MACRO names.\n%s."` and `0x0042D257` is
`_CxxThrowException`).

Before `0x007BAA44` runs, `0x00DEC490` is zero and `0x00DEC498` is empty, so every one of those
sites skips the mod branch entirely. `Data\INI\Default\GameData.ini` and `Data\INI\GameData.ini`
are therefore always read out of the archives, whatever the loose tree says.

## 4. Why that reads as "macros don't work"

Edain keeps its shared `#define`s in `data\ini\_gamedata.inc`, pulled in by
`data\ini\gamedata.ini` - and `gamedata.ini` is the one file guaranteed to be read before the
mod exists. `#include` resolution (`0x00A15C4A`, relative to the including file's own name via
`PathRemoveFileSpec` + `PathAppend`, then `FileSystem::openFile` at `0x00A15CEB`) is correct;
it just inherits the fact that the includer came from an archive at a moment when the mod was
not mounted.

Everything else in the tree is loaded later and does pick up loose edits, which is exactly why
the failure looks specific to macros rather than to a file.

Two things follow that are worth testing before building anything, because both are cheap and
both are predicted by this reading and by nothing else:

- a loose edit to an ordinary (non-macro) field in `Data\INI\GameData.ini` is ignored too;
- so is a loose `Data\INI\Default\SubsystemLegendExpansion1.ini`, since the legend is read
  earlier still (`0x0063AF60`).

`-preferLocalFiles` (`0x00C35DF0`, handler `0x007B9EBE`, which sets the same `0x00DEC490` flag)
lives in the same table and is parsed at the same moment, so it has the same blind spot.

## 5. The fix

Built as `mod-load-order`, in
[`patches/mod_load_order.py`](../patches/mod_load_order.py).

The mod has to be mounted before the first `INI::load`. The startup switches cannot simply be
parsed earlier as they stand: the `-mod` handler (`0x007BADB9`) writes into `GlobalData+0xD38` /
`+0xD3C` and bails silently at `0x007BADC6` while `TheWritableGlobalData` (`0x00DE4364`) is still
null, and that global is published inside `0x00636404`. The earliest point at which the stock
handler can work is therefore the `call` at `0x0063AFA4`, where the object exists - it is that
call's third argument - but its INI has not been read yet.

There is a second constraint. The addresses note on `GLOBAL_DATA_FPS_LIMIT` records that the
command line is parsed *after* `GameData.ini` precisely so a switch beats the tree. Moving the
parse wholesale would invert that for every field both can set (`Windowed`, `XResolution`,
`FramesPerSecondLimit`, ...). So the parse happens twice: once early, to learn the mod path, and
once at the stock site, untouched, to keep switch-over-INI precedence.

**Site 1** - `0x0063AFA4`, `E8 5B B4 FF FF` (`call 0x00636404`). Repointed to a `.modord` cave
that:

1. saves `ebx`, `esi` and `edi`, then reads the `GlobalData` object from `[esp+0x18]` - three saved
   registers and the return address above the third argument of the call it replaced - and
   publishes it to `0x00DE4364`, so the `-mod` handler's guard passes;
2. sets `ebx = 0x00C35DA8` and calls `0x007BA7E1(0x10, argc, argv)`. `argc` and `argv` are
   `[ebp+8]` and `[ebp+0x0C]` of `GameEngine::init`, whose frame is still live at the call site;
3. mounts, transcribing `0x007BAA5B`-`0x007BAABD` instruction for instruction apart from that
   block's `add esp, 0x0c`, which belongs to the parse and is emitted with it in step 2:
   `AsciiString::isEmpty` (`0x00401E64`) on `GlobalData+0xD3C`, else `TheArchiveFileSystem`
   (`0x00DEC9A4`) `vtbl+0x14`; then the same test on `GlobalData+0xD38`, else `0x00A14313`;
4. restores the three registers and `jmp`s to `0x00636404` - the return address and all seven
   arguments are untouched on the stack, so the registration runs and returns to `0x0063AFA9` as
   before.

Preserving `ebx`, `esi` and `edi` is not optional. `GameEngine::init` carries `ebx = 0` as its zero
register and `edi = 1` across this whole region, and `edi` is what supplies the INI load type at
`0x0063B028` and at every load after it.

**Site 2** - `0x007BAA5B`, the first eight bytes of the mount block, replaced with
`83 C4 0C E9 5B 00 00 00`: `add esp, 0x0c`, then a near jump to `0x007BAABE`, the tail the stock
function still has to run. The `call` at `0x0063AFB2` is **left alone**, so `0x007BAA44` still
parses the switches after `GameData.ini`; all it loses is the mount, which by then has already
happened.

The `add esp, 0x0c` is not decoration and the jump cannot replace it. That instruction sits twelve
bytes into the block, at `0x007BAA67`, and it is the **parse's** cleanup for the three arguments
pushed at `0x007BAA47`-`0x007BAA54`, scheduled into the middle of the mount by the compiler. A bare
jump from `0x007BAA5B` to `0x007BAABE` drops it, and `0x007BAA44` runs the rest of itself twelve
bytes out of balance: its epilogue pops `0x10`, `argc` and `argv` into `edi`, `esi` and `ebx`, then
`ret`s to the saved `edi` - which this very document says is `1` across the region. The crash is an
access violation at `EIP = 1`, about two seconds in, before a window opens. So the skip performs
the cleanup itself. The cave emits its own copy for its own parse, at `_parse_startup_switches`.

That last decision is what makes the patch compose with `headless`, which repoints the stock site's
table and count (`0x007BAA4B` and `0x007BAA54`) at an extended copy. Repointing `0x0063AFB2` would
have left those edits unreachable and `-headless` unparsed. The cave's own parse uses the stock
table by address, deliberately: it exists only to find `-mod`, which is a row of the stock sixteen,
and reading the operands `headless` rewrites would make this patch's bytes depend on whether that
one had been applied first.

### What this does not fix

`TheSubsystemLegend` and `Data\INI\Default\SubsystemLegendExpansion1.ini` are read at
`0x0063AF40` / `0x0063AF60`, before `GlobalData` is even allocated, so a mod still cannot replace
the legend from loose files. Covering that needs the allocation and constructor at
`0x0063AF65`-`0x0063AF82` moved ahead of the legend registration - a bigger rewrite of the
function's opening, and a separate change if it turns out a mod wants it.

### Testing

[`tests/sage_patch/test_mod_load_order.py`](../../tests/sage_patch/test_mod_load_order.py)
disassembles the cave and asserts the order that matters (publish before parse, parse before
mount), that the three live registers come back, that it tail-jumps rather than returning, and that
the mount is instruction-for-instruction the block at `0x007BAA5B` - compared against that block's
own bytes, with branch targets as positions so the widened jumps cannot hide a dropped one. Both
sites and all ten anchors are asserted byte for byte, each one individually corrupted in a
stand-in image to check it refuses.

None of that is play. The claim only becomes real in a running game: launch with `-mod <folder>`
over a loose tree whose `Data\INI\GameData.ini` changes one readable `GameData` field, and read
that field back out of `GLOBAL_DATA` with `sage_live`. Unpatched it should hold the archive's
value, patched the loose one.
