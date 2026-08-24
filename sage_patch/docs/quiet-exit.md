# No crash dump for a normal quit — the `quiet-exit` patch

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), checked against the
installed Edain `game.dat`. This is a companion to [`crash-dump.md`](crash-dump.md): that patch
makes the dump the engine writes worth opening; this one stops it being written at all when the game
is simply closed.

**Verdict:** one cave, one redirected call. Closing the game through the menu's exit button no longer
leaves a `.dmp`. A real fault during play still writes one, unchanged.

## 1. The defect

The engine raises its own "Game crash" exception — `0x04560123`, from `Debug::crash` (`0x0043A820`)
— whenever a `DEBUG_CRASH`/assert trips, and a benign one trips on the shutdown path every time the
game is closed. Nothing catches it, so it reaches the unhandled-exception filter at `0x0043D610`
(the `SetUnhandledExceptionFilter` target, installed at `0x00437EB3` — `push 0x43d610` at
`0x00437EA6`), which recognises the code and writes a minidump before letting the process die.

The result is a `DUMP_*.dmp` in the working directory on **every** exit, indistinguishable at a
glance from a real crash — and, once [`crash-dump`](crash-dump.md) is applied, a large one, because
its profile now captures the SAGE heap.

This is the same mechanism [`crash-dump-quality.md`](crash-dump-quality.md) measured: four of the
six dumps found in the install root were `0x04560123`, the engine's own assert, not hardware faults.

## 2. The discriminator — `m_quitting`

`GameEngine` keeps a `m_quitting` byte at `+0x10`. The main loop reads it at `0x00639EC6`
(`cmp byte [esi+0x10], bl`, with `esi = TheGameEngine`) to decide whether to run another iteration;
[`render-rate.md`](render-rate.md) §2 derives both the loop and the field. It is set true by
`GameEngine::setQuitting` (`0x0093D255`, `mov byte [ecx+0x10], 1 ; ret`) when the application is
asked to exit, and it stays true through the teardown that follows.

So `m_quitting` cleanly separates the two cases a dump exists to tell apart:

| situation | `m_quitting` | wanted |
|---|---|---|
| a fault or assert **during play** | `0` | write the dump |
| the shutdown assert **after the exit button** | `1` | skip the dump |

Reading it is one indirection from a `.data` global: `[GAME_ENGINE]` (`0x00DE4324`) is the
`GameEngine *` — `0x04b750d8` in a real shutdown dump, confirming the object still exists at assert
time — and its `+0x10` byte is the flag. A null pointer (the singleton not yet built, or already
gone) takes the write path, which is the stock behaviour.

## 3. The redirect — `0x0043D74E`, five bytes

The filter reaches `writeMiniDump` at exactly one site:

```
0043d746  8a 93 56 9f 00 00   mov  dl, [ebx+0x9f56]   ; ebx = Debug singleton; the fulldump flag
0043d74c  52                  push edx                ; fullDump
0043d74d  56                  push esi                ; esi = EXCEPTION_POINTERS
0043d74e  e8 2d e7 ff ff      call writeMiniDump       <- redirected
0043d753  83 c4 08            add  esp, 8              ; the caller cleans its two arguments
```

The image's other `call writeMiniDump` (`0x0043818B`) sits in a wrapper with **no static callers**
and is left alone; every observed shutdown dump was written from this one.

The five bytes at `0x0043D74E` become a `call` into an appended `.qexit` cave — the same five bytes,
only the target changes:

```asm
mov  eax, [0x00DE4324]    ; TheGameEngine
test eax, eax
je   write                ; no engine -> can't tell -> write (stock behaviour)
cmp  byte [eax+0x10], 0   ; m_quitting
jne  skip                 ; quitting -> drop the dump
write:
jmp  writeMiniDump        ; tail call: writeMiniDump returns straight to 0x0043D753
skip:
ret                       ; return to 0x0043D753; the filter's `add esp, 8` balances the two pushes
```

**Why the stack stays balanced.** The original was a `call`, so the filter had already pushed `esi`
and `edx` and expects `writeMiniDump` to return to the `add esp, 8` at `0x0043D753`, which cleans
them. Replacing it with a `call` into the cave pushes that same return address before the gate runs:

- **write path** — `jmp writeMiniDump` (not `call`). `writeMiniDump` therefore sees `[esp] = 0x43d753`,
  `[esp+4] = esi`, `[esp+8] = edx` — the identical frame it would have had from the stock call — and
  returns to `0x0043D753`.
- **skip path** — `ret` pops `0x43d753` and returns there directly; `esp` is left pointing at the two
  pushed arguments, which the filter's own `add esp, 8` then cleans.

Either way the instruction after the call runs with the stack the stock code expects. `eax` is the
only register touched, and the stock call discards `writeMiniDump`'s return in `eax` anyway.

## 4. Crash-time safety

The cave runs inside a process that has already raised an exception, so it is leaf code: no
allocation, no CRT, no locks, no loop. It reads one global, and only if that is non-null one byte
through it. A fault inside it costs the dump and nothing else — the filter's own second-chance guard
at `0x00DC6E50` sits outside it. The section is `CNT_CODE | MEM_EXECUTE | MEM_READ`, not writable:
unlike `crash-dump`'s cave it spills nothing.

## 5. Blast radius

Client-local, entirely. Nothing here touches the simulation, the frame checksum, the order stream or
the replay format — the same category as [`crash-dump`](crash-dump.md) and
[`infantry-lighting`](infantry-lighting.md). The one site it edits is reached only from the
unhandled-exception filter, which never runs in a game that is not already over. Peers need not match
and replays cross both ways.

## 6. Composition

Order-independent. The cave is allocated past every existing section and `verify` finds it by name.
The only engine bytes it edits are the five at `0x0043D74E`, which no other bundled patch touches —
`crash-dump`, the other patch on this path, rewrites the argument push at `0x0043C001` and the raise
at `0x0043AC57` and only *reads* `writeMiniDump`'s prologue as a build anchor, none of which this
patch disturbs. It reads no structure another patch rewrites and has no INI surface.

## 7. Verification

`apply` asserts the stock five bytes at `0x0043D74E` before redirecting them. `verify` locates
`.qexit` by name, recomputes the gate and compares it, and checks that the call site is a `call`
reaching the cave. `tests/sage_patch/test_quiet_exit.py` disassembles the gate and asserts each
path, that neither pushes nor pops, and — against the real `game.dat` — that the site is stock, that
it really calls `writeMiniDump`, and that nothing branches into the call's interior.

```sh
sage-patch apply  quiet-exit --in game.dat.backup --out game.dat
sage-patch verify quiet-exit game.dat
```

**Status: static-verified.** It applies, verifies and disassembles as intended, and the redirect is
confirmed against the real binary. The one thing only a live exit can settle is that `m_quitting` is
already set at the instant the shutdown assert fires — which is what the flag is set for, but has not
yet been watched happening. Because the gate defaults to writing the dump whenever the flag is not
set, the failure mode of that assumption being wrong is a dump that is still written, never a real
crash whose dump is lost.
