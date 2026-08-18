# Making the crash `.dmp` readable — the `crash-dump` patch

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), verified byte-for-byte
against the stock `game.dat` (11,346,944 bytes). The reverse engineering behind this patch — what
the engine writes today, what six real dumps actually contain, and the five stages the work was
split into — is in [`crash-dump-quality.md`](crash-dump-quality.md). This document is what the
patch does.

**Verdict:** two windows and one cave. The dump gains the whole SAGE heap and loses the video
driver's 20 MB, and the engine's own assert text arrives in the exception record. Nothing else
about the game changes: both hooked sites are reached only from code that runs after a crash.

## 1. The two defects, restated

`writeMiniDump` (`0x0043BE80`) calls `MiniDumpWriteDump` with `MiniDumpWithDataSegs` and two null
pointers, and `Debug::crash` (`0x0043A820`) raises the engine's own `0x04560123` with zero
exception parameters. Measured on the six dumps in the install root, that costs:

| what the stock dump has | what it does not |
|---|---|
| every engine singleton **pointer** | the object any of them points at |
| 20 MB of `nvd3dum.dll` and `igd9dxva32.dll` globals | any heap page at all |
| the exception code `0x04560123` | which assertion fired, in which file, on which line |

The second row is the one that matters. `TheGameLogic` (`0x00DE412C`) reads a heap address that
falls in no captured range, so a null-pointer fault inside a live object — a `ThingFactory` lookup
that returned `NULL` and was used as `this`, say — leaves a dump that names the pointer and cannot
be asked what it pointed at.

## 2. The dump type — `0x0043C001`, eighteen bytes

The stock sequence derives the type from the `fulldump` debug flag and nothing else:

```
0043c001  8a 55 0c        mov  dl, [ebp+0xc]        ; fullDump
0043c004  33 c9           xor  ecx, ecx
0043c006  84 d2           test dl, dl
0043c008  0f 95 c1        setne cl
0043c00b  57              push edi                  ; CallbackParam    = NULL
0043c00c  57              push edi                  ; UserStreamParam  = NULL
0043c00d  8d 45 f0        lea  eax, [ebp-0x10]
0043c010  50              push eax                  ; ExceptionParam
0043c011  41              inc  ecx
0043c012  51              push ecx                  ; DumpType = 1 or 2
0043c013  56              push esi                  ; hFile   <- the resume point
```

`edi` is a literal zero from the `xor edi, edi` at `0x0043BF24`, which is what makes the two
`push edi` the null callback and user-stream parameters rather than live values.

> **Correction to the scoping notes.** Their anchor table gives this site as the eleven bytes
> `8a550c33c984d20f95c141`, folding the `inc ecx` in with the `setne`. The `inc ecx` is actually at
> `0x0043C011`, *after* the `lea`/`push eax` pair, and the window that has to be taken whole runs
> `0x0043C001`..`0x0043C012` — eighteen bytes, `8a550c33c984d20f95c157578d45f0504151`. Nothing
> branches into its interior; `0x0043BFFD` targets its first byte, which a `jmp` placed there
> handles.

The whole window becomes `jmp <cave>` plus thirteen `nop`, and the cave pushes the same four
arguments: the cave's own `MINIDUMP_CALLBACK_INFORMATION`, a still-null `UserStreamParam`, the same
`ExceptionParam`, and a dump type read out of a **two-entry table in the cave** indexed by the
`fulldump` flag. Four dwords in, four dwords out, and only `eax`/`ecx` clobbered where the stock
code used `eax`/`ecx`/`edx`.

### The profile

| bit | flag | why |
|---|---|---|
| `0x0001` | `WithDataSegs` | keep — it is what carries `game.dat`'s own globals |
| `0x0004` | `WithHandleData` | names the open map, replay and socket handles |
| `0x0020` | `WithUnloadedModules` | a return address into a DLL that already went away resolves |
| `0x0040` | `WithIndirectlyReferencedMemory` | a window around every pointer-shaped stack value |
| `0x0100` | `WithProcessThreadData` | process create time and uptime in `MiscInfo` |
| `0x0200` | `WithPrivateReadWriteMemory` | **the heap** — committed private RW pages, no images |
| `0x0800` | `WithFullMemoryInfo` | the VA map, so a freed pointer is distinguishable from a live one |
| `0x1000` | `WithThreadInfo` | thread start addresses, so the logic thread is identifiable |

`0x1B65` in total, and `0x1B67` — the same plus `WithFullMemory` — when `fulldump` is on.

`0x0200` is the deviation from the scoping notes, which put it only in the deep profile. It is
what the acceptance test for this patch asks for: following a singleton to the object it names has
to work on an ordinary crash, not only on one somebody predicted. `WithIndirectlyReferencedMemory`
does not get there on its own — it walks the *stack*, and the six observed dumps carry 33 KB of
stack in total across 33 threads.

Both values are patch parameters (`--dump-type`, `--deep-dump-type`), and the constructor refuses
any profile carrying neither `0x0002` nor `0x0200`, because such a profile installs the patch and
fixes nothing.

### The `dbghelp.dll` question

The shipped `dbghelp.dll` is **6.3.0005.1 (DbgBuild.030922-1449)**, loaded by explicit full path
from the install folder. Every flag above is documented as unsupported on *DbgHelp 5.1* (`0x0020`
through `0x0400`) or on *DbgHelp 6.1 and earlier* (`0x0800` through `0x2000`) — and 6.3 is past
both cut-offs. **So none of these bits needs stage 0a**, the "rename the 2003 `dbghelp.dll` out of
the way" step the scoping notes made a prerequisite for `0x0800` and `0x1000`. A type bit an older
`dbghelp` did not recognise is masked off rather than failing the write, so a build that somehow
did load one degrades to a smaller dump rather than to none.

## 3. The module filter — the callback

`MINIDUMP_CALLBACK_INFORMATION` is `{ CallbackRoutine, CallbackParam }`; the cave holds one, with a
null context. The routine is `stdcall` with three arguments and answers exactly one question:

```
cmp  dword [eax+8], 0                 ; CallbackType == ModuleCallback?
cmp  dword [eax+0x1c], 0              ; BaseOfImage, high dword
cmp  dword [eax+0x18], 0x400000       ; BaseOfImage, low dword
and  dword [ecx], 0xfffffffd          ; clear ModuleWriteDataSeg
mov  eax, 1 ; ret 12
```

`MINIDUMP_CALLBACK_INPUT` puts its union at `+0x10`, not `+0x0C`: every arm of it contains a
`ULONG64`, so the union aligns to 8. `MINIDUMP_MODULE_CALLBACK` is
`{ PWCHAR FullPath; ULONG64 BaseOfImage; ... }`, hence `+0x18` for the base and `+0x1c` for its
high half. Both halves are tested, so a module loaded above 4 GB cannot pass by accident.

`ModuleWriteModule` (`0x01`) is left set, so a filtered module still appears in the module list
with its name, version and load address — only its globals are dropped. That is the 20 MB, and it
is what pays for `0x0200`: the dump gets **more useful and smaller** at the same time.

Every other callback type gets `TRUE` with the flags untouched, which is what "no opinion" looks
like. Both pointers are null-tested, there is no loop, no call and no backward branch: the routine
runs inside a process that has already faulted, where the failure mode is "no dump".

## 4. The assert parameters — `0x0043AC57`, eight bytes

`Debug::crash` formats the crash text into a heap buffer, shows it in a message box, and then
raises with nothing attached:

```
0043ac2a  8b 4d fc          mov  ecx, [ebp-4]         ; the formatted crash text
0043ac2d  68 10 10 01 00    push 0x11010
0043ac32  68 60 4b bd 00    push 0xbd4b60             ; "Game crash"
0043ac37  51                push ecx
0043ac38  57                push edi
0043ac39  ff 15 fc 07 bd 00 call MessageBoxA
...
0043ac57  57 57 57          push edi ; push edi ; push edi
0043ac5a  68 23 01 56 04    push 0x04560123
0043ac5f  ff 15 d8 01 bd 00 call RaiseException        <- the resume point
```

The eight bytes at `0x0043AC57` become `jmp <cave>` plus three `nop`, and the cave spills three
`ULONG_PTR`s into a static slot before pushing its address:

| slot | value | where it lives |
|---|---|---|
| `ExceptionInformation[0]` | `[ebp-4]`, the formatted crash text | heap, allocated at `0x0043A91E` |
| `ExceptionInformation[1]` | `[ebp-8]`, the assertion/error literal | `.rdata` (`0x00BD4BAC` / `0x00BD0C3F`) |
| `ExceptionInformation[2]` | `[ebp+8]`, the mode | immediate |

The scoping notes proposed the file-name pointer, the line number and the expression pointer, and
warned that the `sprintf` might already have consumed them. It has — but it consumed them *into*
`[ebp-4]`, which is strictly better: one pointer to the whole formatted message, expression, file
and line included. `0x0043AC2A` reads it five instructions earlier on the same path, which is what
says it is live rather than uninitialised; the only two branches that reach the raise
(`0x0043AB48` and `0x0043AC1F`) both come from past the point where both slots are assigned.

Because the message is a heap pointer, this half is only readable in a dump that carries the heap.
**The two halves of this patch need each other**, which is why they ship as one. The `.rdata`
literal in slot 1 is readable either way, and already separates an assertion from an error.

A minidump stores `ExceptionInformation[]` in full — fifteen slots — so nothing here is truncated,
and `sage_patch/engine/dump.py` can print all three without symbols.

## 5. The cave

One appended `.crshdp` section, `IMAGE_SCN_CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE |
MEM_READ | MEM_WRITE` — writable, unlike most caves here, because the raise hook spills into it.
`RaiseException`'s `lpArguments` has to point at real memory, and a static slot is what keeps that
spill off a stack that is about to unwind.

| offset | contents |
|---|---|
| `+0x00` | `dword[2]` — the normal dump type, then the deep one |
| `+0x08` | `MINIDUMP_CALLBACK_INFORMATION` — the routine's VA, and a null context |
| `+0x10` | `ULONG_PTR[3]` — the raise hook's exception parameters, written at crash time |
| `+0x20` | the three routines: args hook, raise hook, module callback |

Roughly 0x9B bytes in total.

## 6. What still needs no patch

Two of the wins in the scoping notes are configuration, not binary edits, and both remain worth
doing beside this patch:

- **A `game.dbgcmd`.** `0x00439C80` resolves a debug-command file at startup — `_EA_RTS_FILENAME`,
  then `-dbgcmd:<path>`, then `<exe name>.dbgcmd`, then `default.dbgcmd` — and reads up to `0x800`
  bytes of it. `game.dat` ships without one, so it runs on the constructor defaults and **none of
  the four I/O sinks is registered**, which is why the crash text currently goes nowhere. A file
  registering a flat-file sink gives it somewhere to go; `debug.fulldump +` in the same file is
  what selects this patch's deep profile; and the `fatalcrash` command is how a dump is produced
  on demand rather than by waiting for a real crash.
- **Renaming `rotwk\dbghelp.dll`.** Still a reasonable thing to do — the modern system copy walks
  stacks better and the engine warns about the old one itself (`0x00BD49D0`) — but, per section 2,
  **not a prerequisite for anything this patch installs.**

## 7. What is deliberately out of scope

- **A `CommentStreamA` user stream** (stage 3 of the scoping notes). `UserStreamParam` stays
  `NULL`. Collecting the frame number, map name and seat list means a chain of defensive
  dereferences through logic state that is by construction already broken, and with the heap in
  the dump most of it is recoverable offline anyway.
- **The file's name and location** (stage 5). Dumps still land in the process working directory
  under `Program Files (x86)` with a name carrying no exception code, and `MiniDumpWriteDump`'s
  return value is still discarded, so a truncated dump still looks like a real one.
- **An arena walk.** With `WithPrivateReadWriteMemory` the whole heap is captured, so the
  `MemoryCallback` the notes describe — and the `TheMemoryPoolFactory` reverse engineering it
  needs — buys nothing this patch does not already have.

## 8. Blast radius

Client-local, entirely. Nothing here touches the simulation, the frame checksum, the order stream
or the replay format, so unpatched peers are unaffected and replays cross both ways — the same
category as [`infantry-lighting`](infantry-lighting.md), not
[`production-condition`](production-model-condition.md). Both hooked sites are reached only from
the unhandled-exception filter and from `Debug::crash`, neither of which runs in a game that is not
already over, and both sit *inside* the filter's second-chance guard at `0x00DC6E50` — so a fault
in either costs the dump and nothing else.

## 9. Verification

`apply` asserts the stock bytes at both windows and at six anchors: `writeMiniDump`'s prologue, the
`xor edi, edi` that makes the displaced pushes literal nulls, both resume points, and the two
instructions that pin `Debug::crash`'s frame slots to a live message pointer and a live tag
pointer. `verify` locates `.crshdp` by name, recomputes the header and the three routines and
compares them — skipping the three argument slots, which are state the game writes when it crashes
and not part of the patch — and checks that both windows hold a `jmp` to the entry point the
layout actually produced. `detect` reads the two dump types back out of the first eight bytes of
the cave and hands them to `verify`, so a binary somebody else patched reports its own profile
rather than being called unpatched.

`tests/sage_patch/test_crash_dump.py` disassembles the cave and asserts each routine separately,
counts the pushes on each hook against the window it replaced, and — against the shipped
`game.dat` — checks every stock byte and that nothing branches into either window's interior.

```sh
sage-patch apply crash-dump --in game.dat.backup --out game.dat   # defaults 0x1b65 / 0x1b67
sage-patch verify crash-dump game.dat
```
