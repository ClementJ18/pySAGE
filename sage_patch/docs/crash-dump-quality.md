# Making the crash `.dmp` worth opening — scoping notes

Scope for a `crash-dump` patch. ROTWK `game.dat` build `2.01.2614.37001`, ImageBase `0x400000`,
recovered statically 2026-08-18 from
`sage_patch/engine/game.dat.backup`;
every site below was re-checked byte-for-byte against the **installed** Edain
`C:\Program Files (x86)\Games\bfme\rotwk\game.dat` and is identical there. Measurements come from
the six real dumps sitting in the install root.

## TL;DR

- The engine already writes a minidump on every unhandled exception, from EA's `Debug` library.
  The writer is **`0x0043BE80`**, called from the unhandled-exception filter **`0x0043D610`**
  (installed with `SetUnhandledExceptionFilter` at `0x00437EB3`).
- It asks for **`MiniDumpWithDataSegs` (type `1`)** and passes **`NULL` for both the user-stream
  and the callback parameter**. Those two nulls are the whole problem.
- Consequence, measured: **every engine singleton pointer is in the dump and every object it
  points at is not.** `TheGameLogic` (`0x00DE412C`) reads `0x08186978`; that address is in no
  captured range. Same for `ThePlayerList`, `TheWritableGlobalData`, `TheScienceStore`. The dump
  tells you a pointer's value and nothing about what it points at.
- **73% of each dump is video-driver globals.** `nvd3dum.dll` (11.46 MB) and `igd9dxva32.dll`
  (8.50 MB) data segments account for 20 MB of 27.4 MB. `game.dat`'s own `.rdata` + `.data` is
  2.34 MB of it.
- **Four of the five readable dumps are not hardware faults.** Their exception code is
  `0x04560123` at `KERNELBASE!RaiseException` — the engine's own "Game crash" raise at
  `0x0043AC5A`, i.e. an assert or `DERROR` fired. It is raised with **zero exception parameters**,
  and the message text goes to a `Debug` I/O sink that no shipping config registers, so **the
  reason for the crash is formatted and then discarded.** The faulting EIP is a Windows frame.
- One of the six dumps is **truncated**: header written, stream directory all zeros, 5.8 MB of
  payload orphaned. Nothing checks `MiniDumpWriteDump`'s return.
- The shipped `dbghelp.dll` is **6.3.5.1, dated Sept 2003**, and the engine loads it by explicit
  full path out of the game folder. It caps which dump types are even available.

Two of the wins need no patch at all. Start there.

**Implemented in [`crash-dump.md`](crash-dump.md):** Stage 1, Stage 2's module filter and Stage 4.
That document also records where these notes turned out to be wrong - the dump-type window's
length, `dbghelp` 6.3's actual flag support, and what `Debug::crash` still has in hand at the raise
site.

## 1. What the engine does today

### 1.1 The writer — `0x0043BE80`

`writeMiniDump(EXCEPTION_POINTERS *ep, BOOL fullDump)`, `cdecl`, two args.

```
0043be89  mov  eax, [0x00DC62EC]          ; HMODULE dbghelp, loaded by 0x0043B1A0
0043be96  push "MiniDumpWriteDump" ; push eax ; call GetProcAddress
0043beb0  lea  eax, [ebp-0x28] ; call GetLocalTime
0043beba  mov  ecx, [0x00DC62C0]          ; the Debug singleton
          call [vtbl+0xA4]                ; -> esi, the install GUID
          call [vtbl+0xA0]                ; -> edi, "2.01.2614.37001"
0043bee0  call GetCurrentThreadId ; push   ; the trailing %ld
0043bee3  call GetCurrentProcessId ; push  ; the first %ld
0043bf0a  push 0x00BD4E40                 ; "DUMP_%s_%04d%02d%02d-%02d%02d%02d_%s_%ld_%ld.dmp"
0043bf1b  call _snprintf                  ; 0x106-byte buffer
0043bf39  call CreateFileA(name, GENERIC_READ|WRITE, SHARE_RW, 0, CREATE_ALWAYS, 0, 0)
0043bf4a  ...OpenThreadToken / OpenProcessToken / LookupPrivilegeValueA("SeDebugPrivilege")
          ...AdjustTokenPrivileges
0043bf9d  call GetCurrentThreadId ; [ebp-0x10] = mei.ThreadId
0043bfa6  mov  eax,[ebp+8]        ; [ebp-0x0c] = mei.ExceptionPointers
0043bfb7  mov  [ebp-8], ebx       ; mei.ClientPointers = 1
0043c001  mov  dl, [ebp+0xc]      ; fullDump
          xor  ecx, ecx ; test dl,dl ; setne cl              ; ecx = 0 or 1
0043c00b  push 0                  ; CallbackParam        <-- null
0043c00c  push 0                  ; UserStreamParam      <-- null
0043c00d  lea  eax,[ebp-0x10] ; push eax                 ; ExceptionParam
0043c011  inc  ecx
0043c012  push ecx                ; DumpType = 1 or 2
0043c013  push esi                ; hFile
0043c014  call GetCurrentProcessId ; push
0043c01b  call GetCurrentProcess   ; push
0043c022  call [ebp-0x14]          ; MiniDumpWriteDump
```

The return value is discarded. The file is created in the **process working directory** — the
install root, which is under `Program Files (x86)`; the game runs elevated so this works, but it
is the wrong place for a crash artifact.

The name decodes as `DUMP_<version>_<date>-<time>_<install GUID>_<pid>_<tid>.dmp`. It carries no
exception code, no map and no build tag, so a directory of these cannot be triaged without opening
each one.

### 1.2 `fullDump` — `Debug+0x9F56`

The flag is a byte on the `Debug` singleton, zeroed in the constructor at `0x00437E6A` and toggled
by the **`fulldump`** debug command at `0x0043E902` / `0x0043E910`. So the type is `1`
(`MiniDumpWithDataSegs`) unless something turned it on, and `2` (`MiniDumpWithFullMemory`) when it
did. Nothing between those two.

### 1.3 The `.dbgcmd` config channel is live in the retail build

`0x00439C80` resolves a config file, in this order:

1. `GetEnvironmentVariableA("_EA_RTS_FILENAME")`
2. `-dbgcmd:<path>` on the command line (token-delimited by a space)
3. `GetModuleFileNameA(NULL)` with the extension replaced by `.dbgcmd` — i.e. **`game.dbgcmd`**
   beside `game.dat`
4. `default.dbgcmd`

then `CreateFileA(..., OPEN_EXISTING)` and reads it. `Worldbuilder.dbgcmd` in the install root is
the shipping example, and its four lines are all *silencers*:

```
debug.errors -
debug.add c - *
debug.add a - *
debug.add l - *
```

There is no `game.dbgcmd`, so `game.dat` runs on the constructor defaults. The command set is
`list, io, alwaysflush, skipstackwalk, timestamp, exit, beep, clear, add, view, windowed,
fulldump, errors` (help text at `0x00BD68C0`). The I/O classes — `con`, `flat`, `net`, `dbg` — are
**registered as factories** at `0x00439BE0` and **none is added by default**, which is why the
formatted crash text has no sink.

### 1.4 Where the crash reason goes

`0x0043AC5A` raises the engine's own code:

```
0043ac32  push 0x00BD4B60      ; "Game crash"
0043ac57  push edi ; push edi ; push edi   ; lpArguments=NULL, nNumberOfArguments=0, flags=0
0043ac5a  push 0x04560123
0043ac5f  call RaiseException
```

The filter at `0x0043D610` recognises the code (`cmp edx, 0x04560123` at `0x0043D673`) and treats
it as a crash rather than a fault. Everything that made it a crash — the expression, file and
line, formatted with the strings at `0x00BD4B20`..`0x00BD4BAC` — is written into the `Debug`
object, and **the `Debug` object is on the heap** (`[0x00DC62C0]` reads `0x010EFC28` in a real
dump, not captured). It is not in the exception record and not in the dump.

The filter also, after the dump, `sprintf`s `"crashmailer.exe %i %s"` (`0x00BD5C0C`) and
`CreateProcessA`s it. `crashmailer.exe` does not ship. That call is dead.

## 2. What the dumps actually contain

Six files in the install root, 2026-08-16 to 2026-08-18. All `MDMP`, flags `0x1`, 8 directory
slots of which 6 are used: `ThreadList`, `ModuleList`, `MemoryList`, `Exception`, `SystemInfo`,
`MiscInfo`.

| dump | size | exception | at | modules | ranges |
|---|---|---|---|---|---|
| `20260816-153503` | 27.5 MB | `c0000005` read `0x34` | `game.dat+0x2c6a24` | 120 | 251 |
| `20260817-204929` | 5.8 MB | `04560123` | `KERNELBASE+0x13b6d2` | 90 | 190 |
| `20260817-213342` | 27.4 MB | `04560123` | `KERNELBASE+0x13b6d2` | 109 | 229 |
| `20260817-213459` | 27.4 MB | `04560123` | `KERNELBASE+0x13b6d2` | 109 | 229 |
| `20260818-141811` | 5.8 MB | — | — | — | **truncated** |
| `20260818-195354` | 27.5 MB | `04560123` | `KERNELBASE+0x13b6d2` | 115 | 247 |

Only the first is a genuine fault, and it is the only one where the dump names the bug on its own
(a null-ish `this` dereferenced at `+0x34`).

Where the 27.4 MB goes, on the 2026-08-18 dump:

| range | size | owner |
|---|---|---|
| `0x63217000` | 11.46 MB | `nvd3dum.dll` data |
| `0x37426000` | 8.50 MB | `igd9dxva32.dll` data |
| `0x00bd0000` | 2.34 MB | `game.dat` `.rdata` + `.data` |
| `0x6d4a1000` | 2.26 MB | `AcLayers.dll` data |
| `0x65682000` | 0.85 MB | `nvgpucomp32.dll` data |
| 242 more | 1.9 MB | stacks, TEBs, small data segs |

33 threads, **33 472 bytes of stack in total**; the faulting thread contributes `0x33E0`.

What is missing, and what it costs:

| missing | consequence |
|---|---|
| any heap | no `Object`, no `Player`, no `Drawable`, no `GameLogic` — only the pointers to them |
| `MemoryInfoList` | cannot tell "pointer into freed memory" from "pointer into a live commit" |
| `UnloadedModuleList` | a return address into an unloaded DLL resolves to nothing |
| `ThreadNames` / `ThreadInfoList` | 33 anonymous thread ids; no way to say which is the logic thread |
| `HandleData` | no file or socket state at crash time |
| `CommentStreamA` | no frame number, map, seat count, replay position, current INI file |
| exception parameters on `0x04560123` | no assert text, no file, no line |
| `MiscInfo` beyond 24 bytes | no process create time, no uptime, no CPU info |

## 3. Proposed changes, in the order they should be done

### Stage 0 — two changes that need no patch

**0a. Stop loading the 2003 `dbghelp.dll`.** `0x0043B1A0` builds the full path
`<exe dir>\DBGHELP.DLL` (writing the 12 bytes of `"DBGHELP.DLL"` at `0x00BD4D8C` after the last
`\`) and `LoadLibraryA`s it; **only if that fails** does it fall back to a bare
`LoadLibraryA("DBGHELP.DLL")` at `0x0043B224`, which picks up the system copy. The shipped file is
`6.3.5.1 (DbgBuild.030922-1449)`; Windows 10 ships `10.0.x` in `System32`. Renaming
`rotwk\dbghelp.dll` to `dbghelp.dll.bak` takes the fallback branch and unlocks the modern
`MINIDUMP_TYPE` bits and stream set. Free, reversible, and a prerequisite for anything in Stage 1
above `0x200`. The engine even warns about this itself — `0x00BD49D0`, *"You are using an older
version of the DBGHELP.DLL library"*.

**0b. Add a `game.dbgcmd`.** It is read at startup with no patch. Two useful lines:

```
debug.io flat add crash
debug.errors +
```

The first registers a flat-file sink, so the assert text, the register block, the "Bytes around
EIP" hex and the `dbghelp` stack walk stop going nowhere — and `debug.fulldump +` is the existing
(blunt) switch to type `2`. Check how much of the file the reader consumes; the buffer at
`0x00439DB7` is `0x800` bytes.

Both of these are worth doing first because they change what the *patch* still has to do.

### Stage 1 — the dump type constant

`0x0043C001`, **18 bytes**, `8a550c 33c9 84d2 0f95c1 57 57 8d45f0 50 41 51` - the whole argument
push, up to but not including the `push esi` at `0x0043C013`. (An earlier revision of these notes
gave the site as 11 bytes ending in the `inc ecx`; the `inc` is at `0x0043C011`, between the
`push eax` and the `push ecx`, so the window cannot stop before it.)

Replace with a load of a patch-owned dword, so the type is a parameter rather than a two-valued
toggle, keeping the `fulldump` flag as the selector between a *normal* and a *deep* profile. Twelve
bytes is enough for two `8B 0D <abs32>` loads plus the test on `[ebp+0xc]` that is already there;
otherwise take the following `push ecx` into the rewrite and re-emit it. Suggested normal profile,
all of which costs far less than `MiniDumpWithFullMemory`:

| bit | flag | why |
|---|---|---|
| `0x0001` | `WithDataSegs` | keep — it is what carries `game.dat`'s globals |
| `0x0004` | `HandleData` | cheap, and names the open map and replay files |
| `0x0020` | `WithUnloadedModules` | resolves return addresses into DLLs that already went away |
| `0x0040` | `WithIndirectlyReferencedMemory` | **the big one** — walks the stack for pointer-shaped values and captures a window around each, which is exactly the objects in flight |
| `0x0100` | `WithProcessThreadData` | fills out `MiscInfo` with times, and thread data |
| `0x0800` | `WithFullMemoryInfo` | the VA map — needed to distinguish freed from live |
| `0x1000` | `WithThreadInfo` | thread start addresses, so the logic thread is identifiable |

`0x0001`..`0x0200` are available on the 2003 `dbghelp`, and so, on inspection, are `0x0800` and
`0x1000`: the shipped file is **6.3.0005.1**, and MSDN's cut-off for those two is *DbgHelp 6.1 and
earlier*. **Neither depends on Stage 0a** - see [`crash-dump.md`](crash-dump.md) section 2. The deep profile should be `0x0200` (`WithPrivateReadWriteMemory`, the whole SAGE
heap without mapped images) rather than `0x0002` — the same information for the debugging that
matters, without the image pages.

**Measure before settling on a default.** `0x40` over a 13 KB stack should add a few hundred KB; if
it does not, the profile is wrong.

### Stage 2 — a `MiniDumpCallback` (`0x0043C00B`, the null `CallbackParam`)

One `push edi` becomes `push <cave>` pointing at a `MINIDUMP_CALLBACK_INFORMATION`. The callback
body lives in a cave section allocated with `sage_patch.utils.allocate_section` (the
`commandset-limit` `.cmdext` pattern). Two jobs:

- **`IncludeModuleCallback` / `ModuleCallback`: drop foreign data segments.** Returning `FALSE`
  for modules that are not `game.dat` — or that are on a denylist of `nvd3dum`, `ig*`, `atiu*`,
  `amdvlk*`, `AcLayers` — removes **20 MB of the 27.4 MB** and loses nothing anyone will ever read.
  That budget is what pays for Stage 1's `0x40`, so the dump gets *more useful and smaller*.
- **`MemoryCallback`: add the ranges that matter.** Hand back explicit `(base, size)` pairs for the
  engine's own heap arenas.

The callback runs inside a crashed process, so it must be leaf-simple — no allocation, no CRT, no
locks, a static state word for the `MemoryCallback` cursor.

**Open RE item, and the one thing blocking the best version of this:** the callback wants the SAGE
allocator's arena list — `TheMemoryPoolFactory` / `TheDynamicMemoryAllocator` — and neither is in
[`addresses.py`](../addresses.py) yet. Without it, the fallback is to enumerate the four known
singleton pointers (`TheGameLogic` `0x00DE412C`, `ThePlayerList` `0x00DE4928`,
`TheWritableGlobalData` `0x00DE4364`, `TheScienceStore` `0x00DE3B20`), `VirtualQuery` each, and
hand back the containing region — which already turns four dead pointers into four live objects and
is a strictly smaller job. Do the fallback first; the arena walk is a follow-up.

### Stage 3 — a user stream with the game's own state (`0x0043C00C`)

The other `push edi` becomes `push <cave>` pointing at a `MINIDUMP_USER_STREAM_INFORMATION` with
one `CommentStreamA` (type `10`) entry. The cave holds a fixed text buffer the patch fills just
before the call. Everything worth putting in it is one or two dereferences from a `.data` global
that is already captured:

- frame number off `TheGameLogic`
- map name, game mode, network vs skirmish, seat count and each seat's faction
- whether a replay is recording or playing, and its frame
- the patch set applied to this binary — the registry already knows it, and
  [`binary-attest`](binary-attest.md) is the existing precedent for stamping it in

A `CommentStreamA` is read by every dump tool without any tooling change, and it is the difference
between "this dump crashed" and "this dump crashed on frame 18 240 of `map mp fords of isen`, seat
3, Mordor AI".

Keep the collection defensive: read through pointers with an inline null test and bail on the first
zero, because by construction this code runs when invariants are already broken.

### Stage 4 — put the assert into the exception record (`0x0043AC57`)

The cheapest large win in the whole scope, and independent of the rest.

```
0043ac57  57 57 57 68 23 01 56 04    push 0 ; push 0 ; push 0 ; push 0x04560123
```

Becomes `push <cave args>`, `push 3`, `push 0`, `push 0x04560123` — where the cave holds three
`ULONG_PTR`s already available at the raise site: the file-name pointer, the line number and the
expression pointer. Those land in the exception record's `ExceptionInformation[]`, which the
minidump stores in full (15 slots), and they point into `game.dat`'s `.rdata`, which
`WithDataSegs` **already captures**. So the assert text becomes readable offline with no symbols,
no Stage 2 and no Stage 3 — and [`engine/dump.py`](../engine/dump.py) can print it directly.

Confirm the caller's register and stack state at `0x0043AC30`..`0x0043AC57` actually still holds
those three values before committing to it; the `sprintf` at `0x0043AC39` consumed them, so they
may need to be spilled to the cave a few instructions earlier.

### Stage 5 — where the file goes and what it is called

Three smaller quality items in `writeMiniDump`:

- **Path.** `CreateFileA` at `0x0043BF39` gets a bare filename, so dumps land in the install root
  under `Program Files (x86)`. Prefix the `_snprintf` at `0x0043BF1B` with the user files
  directory the engine already resolves for `Replays` and `options.ini`
  (`%APPDATA%\My The Lord of the Rings, The Rise of the Witch-king Files\`), so a dump sits beside
  the replay that reproduces it and survives an unelevated run.
- **Name.** The format string at `0x00BD4E40` is 48 bytes in a 52-byte slot, so it can be edited in
  place only if it does not grow and the argument count does not change. Adding the exception code
  — the single most useful triage field, and what separates a real fault from a `0x04560123`
  assert — means one more `push` at `0x0043BF0A` and a longer format in a cave. Worth it: it makes
  a directory of dumps sortable without opening any of them.
- **Check the return.** `MiniDumpWriteDump`'s result at `0x0043C022` is discarded, and one of six
  observed dumps is a truncated file with a zeroed stream directory. At minimum delete the file on
  `FALSE`, so a corrupt dump is not mistaken for a real one; better, record `GetLastError`. The
  `0xC00000FD` (stack overflow) branch at `0x0043D64F` is the likely producer — the filter adds
  `0x470` bytes of frame and `writeMiniDump` another `0x150` on a stack that just ran out — so
  consider taking the stack-overflow case onto a dedicated thread instead.

## 4. Risk and blast radius

- **Client-local, entirely.** Nothing here touches the simulation, the CRC, the order stream or the
  replay format. Unpatched peers are unaffected and replays cross both ways — the same category as
  [`infantry-lighting`](infantry-lighting.md), not
  [`production-condition`](production-model-condition.md).
- **The code runs in a process that is already broken.** That is the real risk, and it argues for
  the staging above: Stage 1 and Stage 4 add no new code paths at crash time (a constant and four
  pushes); Stage 2 and Stage 3 add a callback and a state collector that execute *only* after a
  crash, where the failure mode is "no dump" rather than "no game". Every dereference in those two
  needs an explicit null test.
- **Bigger or smaller dumps.** Stage 2's module filter is what keeps Stage 1 from inflating the
  files. Land them together, or land Stage 2 first.
- **`SetUnhandledExceptionFilter` is called twice** in the image — `0x00437EB3` (this handler) and
  `0x00A9BB1E`, in the SafeDisc/CRT region. Confirm which one wins at runtime before assuming the
  handler is reached in every configuration; the six dumps say it usually is.
- **A second-chance exception inside the handler is already handled** by the guard byte at
  `0x00DC6E50` (`0x0043D619`), which short-circuits to "Exception in exception handler" and writes
  no dump. Anything added in Stages 2–3 sits *inside* that guard, so a fault there costs the dump
  and nothing more.

## 5. How to verify

- **Static**, per this repo's convention: assert the original bytes at every site in
  [`tests/sage_patch/`](../../tests/sage_patch/) against `game.dat.backup` *and* the installed
  Edain `game.dat`, and round-trip `apply` / `verify` / `detect`.
- **Runtime**, and this one is unusually easy to exercise: `debug` has a **`fatalcrash`** command
  (`0x00BD5DD0`, help text *"Serious test crash. Everything is fine."*) alongside `exception` and
  `crash`. A `game.dbgcmd` can fire a crash on demand, so each stage can be validated without
  waiting for a real one.
- **Offline**, extend [`engine/dump.py`](../engine/dump.py) as the stages land: it already prints
  the faulting EIP, the register block and a `game.dat`-relative stack walk. Add the
  `CommentStreamA` (Stage 3), the `ExceptionInformation[]` decode (Stage 4) and `MemoryInfoList`
  classification of the faulting address (Stage 1). Each addition is testable against the six dumps
  already in the install root — the four `0x04560123` ones are the regression corpus for "the
  reason is now recoverable".

## 6. Byte-level anchor table

| site | VA | bytes | change |
|---|---|---|---|
| dump type | `0x0043C001` | `8a550c33c984d20f95c157578d45f0504151` | Stage 1 — load a patch-owned profile |
| `CallbackParam` | `0x0043C00B` | `57` | Stage 2 — `push <cave>` |
| `UserStreamParam` | `0x0043C00C` | `57` | Stage 3 — `push <cave>` |
| `MiniDumpWriteDump` | `0x0043C022` | `ff55ec` | Stage 5 — check the return |
| name `_snprintf` | `0x0043BF0A` | `68404ebd00…` | Stage 5 — path prefix, exception code |
| `CreateFileA` | `0x0043BF39` | `ff152801bd00` | Stage 5 — writable directory |
| `RaiseException` | `0x0043AC57` | `5757576823015604` | Stage 4 — three parameters |
| format string | `0x00BD4E40` | 48 bytes in a 52-byte slot | Stage 5 |
| `fulldump` flag | `Debug+0x9F56` | default `0`, set at `0x00437E6A` | Stage 1 selector |
| `dbghelp` path build | `0x0043B1A0` | — | Stage 0a, no patch needed |
| `.dbgcmd` loader | `0x00439C80` | — | Stage 0b, no patch needed |
