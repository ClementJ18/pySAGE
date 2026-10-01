# Loading OH1A's accelerator from `game.dat`

The `accel-module` patch makes `game.dat` load OH1A's BFME2 Accelerator, `bfme2_accel.dll`, by
itself, in place of the accelerator's injecting loader. It started as the loader for a native module
of our own ([`accel-port.md`](accel-port.md) §6, option B2) and is now just that loader, pointed at
the original.

**Status 2026-10-01: the loader cave armed in Edain on 2026-09-24. Loading `bfme2_accel.dll` through
it has not been played.**

## TL;DR

- **Why our own module was dropped.** OH1A published the accelerator's source under the MIT licence
  ([github.com/OhadBaehr/bfme2-accelerator](https://github.com/OhadBaehr/bfme2-accelerator)). Our
  module had grown into a C port of its render thread. That duplicated a maintained codebase to fix
  three faults that are better fixed in it (§3). Our package, `sage_accel`, was removed on
  2026-10-01. The census is in git history (`a9f5ab1`); the render-thread port is commit `2973e6c` on
  the local branch `claude/accel-implementation-wrap-h42653`.
- **What stays here:** this patch, the arming site (§2), and the census's findings (§4). The census
  measured what a render thread costs on Edain, and it found the compatibility-shim behaviour that
  the fixes in §3 address.
- **The DLL has to be a build with those fixes.** Stock `bfme2_accel.dll` identifies its build by a
  hash over all of `.text`. Any `sage_patch` edit makes that hash unknown, and on an unknown build
  the render thread picks the load screen's thread as the game thread and crashes
  ([`accel-port.md`](accel-port.md) §1). The fixes are on branch `patched-builds` of
  `ClementJ18/bfme2-accelerator`, to be offered upstream.

## 1. The patch

| | |
|---|---|
| what it edits | the store of the resolved `Direct3DCreate9` at `0x00525199` becomes a `jmp` to a `.accel` cave |
| what the cave does | re-runs the store, then `LoadLibraryA("bfme2_accel.dll")`, and records the outcome. It preserves every register and the flags |
| without the DLL | `LoadLibraryA` fails, the state byte says so, and the game runs as stock |
| the DLL | installs itself from its own `DllMain` (a thread it starts), exactly as when injected. It logs to `bfme2_accel.log` beside itself |
| `.accel` block | magic `SACL` at `+0`, state byte at `+4` (0 not reached, 1 no DLL, 2 loaded), module handle at `+8`, the DLL's name at `+0x10`, code at `+0x20` |

**Why this moment.** `d3d9.dll` and `d3dx9_27.dll` are loaded, but the device does not exist yet and
no effect has been created. The DLL's installer therefore races only the device's creation, not its
use. If the installer is still running when the first effect appears, the render thread arms at
that effect's first call, as it does under the injector.

**Why a cave and not the import table.** With an import descriptor, Windows refuses to start a
`game.dat` whose DLL is absent. With the cave, the patched binary runs unchanged without it.

**`sage-patch verify`** checks `game.dat` only. The DLL is optional at runtime, so nothing about it is
verified.

## 2. The site

Read 2026-09-24 in `C:\RotWK\game.dat`:

```
00525171  68 04 72 be 00      push 0xBE7204            ; "D3D9.DLL"
00525176  ff 15 88 01 bd 00   call [LoadLibraryA]
0052517e  a3 10 36 dd 00      mov  [0x00DD3610], eax   ; the d3d9 module
00525189  8b 35 8c 01 bd 00   mov  esi, [GetProcAddress]
0052518f  68 f4 71 be 00      push 0xBE71F4            ; "Direct3DCreate9"
00525195  ff d6               call esi
00525199  a3 14 36 dd 00      mov  [0x00DD3614], eax   ; <- the pointer, and the hook
...
00525209  ff 15 14 36 dd 00   call [0x00DD3614]        ; Direct3DCreate9(0x20)
```

The `je` after the store reads the flags of the `cmp eax, ebx` before it, which is why the cave
saves the flags. The anchor covers the compare, the store and the `je`. `perf-scope-skip` hooks the
same function ninety bytes further on, and the two compose in any order.

## 3. What the DLL needs, and where it is fixed

On branch `patched-builds` of `ClementJ18/bfme2-accelerator` (2026-10-01). It compiles with MSVC
and loads; it has not been played.

1. **The game thread, named rather than guessed.** On an unrecognised build the original took the
   first thread to make 64 effect calls, and the load screen draws first
   ([`accel-thread-identity.md`](accel-thread-identity.md)). The fix takes the thread that owns the
   device's focus window, read once from the device the first effect is created on. The engine
   creates that window on the game thread. The call count stays as the fallback.
2. **Device hooks put back after `Reset`.** On a machine where Windows shims `game.dat`, the
   compatibility shim rewrites the device's vtable entries during the engine's startup `Reset`
   (§4). The original never re-hooks, so from then on the game thread's calls would reach the device
   directly while the worker runs the queue on it. The fix re-hooks after every `Reset`, and once a
   second from the DLL's key thread.
3. **Device `Release` drains only when it may be the last.** The census counted 200 to 380 device
   releases a late-game frame (§4), and each one was a full queue drain.
4. **The effect de-dupe forgets what it does not follow.** `SetValue`, the array setters,
   `SetString`, `SetArrayRange`, `SetRawValue`, and setters called by name. Before the fix, a later
   write of the remembered value could be skipped.

The fixes also install the minimap pixel writes, the shroud updates and the radar mirrors on an
unrecognised build. Each already checks the bytes at its own sites, and without the pixel writes
alone the render thread drains its queue about 650 times a battle frame.

**Building it.** VS 2022 Build Tools (the C++ workload), then `src\build.bat`. That writes
`src\aotr_accel.dll`, the reporting build, which logs a render-thread report every 5 s.
`src\build_prod.bat` writes `src\bfme2_accel.new.dll`, the shipped build without the reports.
Either one is renamed to `bfme2_accel.dll` beside `game.dat`.

## 4. What the census measured

The census was `sage_accel`'s milestone M1: pass-through hooks on every device, effect and lock call,
counting what a render thread would queue and what would make it wait. It ran in Edain on
2026-09-24.

**The device's vtable belongs to the Windows compatibility shim.** It sits at a heap address, and its
`QueryInterface` is in `apphelp.dll`: the shim copied `d3d9`'s table and hooked entries in it. Four
runs established how to live with it:

1. Hooked entry by entry, all 119 slots were put back by the shim within 10 s
   (`Present slot is D3D9.DLL+0xE05D0 - REPLACED`). The engine calls `Reset` during startup
   (`0x0052220F`), and that is when the shim rewrites its table.
2. Giving the device a table of our own crashed inside that `Reset`, calling address 0 from
   `apphelp.dll+0x80D6C`: the shim finds its saved original by the device's vtable pointer.
3. So the device is hooked in place, and the hooks are put back after `Reset`, taking whatever the
   shim installed as each slot's original. With that, all 119 slots held for whole sessions.

**`game.dat` has no import name table.** Every import descriptor's `OriginalFirstThunk` is 0, so once
the game is loaded its IAT holds only resolved addresses. An import hook must find its slot by the
address `GetProcAddress` gives, not by name. The first census build did the latter and crashed at
startup. The accelerator already does the former.

**The cost of a render thread on Edain.** Nine minutes of a late-game skirmish, counted under the
original's rules; all figures per frame:

| fps | frame | device calls | effect calls | waits | device `Release` | VB locks (`NOOVERWRITE`) | VB lock waits |
|---|---|---|---|---|---|---|---|
| 17.6 | 56.7 ms | 38,122 | ~55,000 | 599 | 382 | 934 (923) | 213 |
| 13.5 | 74.0 ms | 29,843 | ~41,000 | 499 | 320 | 757 (742) | 175 |
| 16.8 | 59.7 ms | 21,285 | ~26,000 | 375 | 220 | 591 (583) | 150 |

Two changes take those 400 to 600 waits to about 3: device `Release` drains only when it is the
last one (§3, fix 3), and `NOOVERWRITE` buffer locks are staged, which the original already does.
The load screen was also seen: 11 `Present`s and 1,584 device calls from a second thread during
loading, the thread [`multicore.md`](multicore.md) §1.1 identifies.

## 5. Testing it

1. Build the DLL from the `patched-builds` branch (§3), or take the copies in that repository's
   `dist\report` (reporting) or `dist\prod`.
2. Copy it beside `game.dat` as `bfme2_accel.dll`.
3. `sage-patch apply accel-module` on a copy of the `game.dat` you play, alongside your other
   patches, and put it in place.
4. Start Edain. `bfme2_accel.log` should show, in this order:
   - `init: an unrecognised build of this engine` (expected: the patches changed `.text`);
   - `rt: armed`;
   - `the device's focus window ... belongs to thread N`;
   - `RENDER THREAD LIVE ... game thread N`, with the same `N`.

   After the startup `Reset`, a line saying the device vtable slots are hooked again is the shim
   case of §4, handled.
5. Sit through a loading screen, alt-tab once (a `Reset`), and play into a large late-game army.
   Scroll Lock switches the render thread off and on, so frame rates can be compared in one match.
6. Remove the DLL and check the patched game still starts as stock.

## 6. Decisions

1. **Credit** (2026-09-24). `author = "officialNecro"`, who is asked for fixes to the patch; OH1A is
   credited in the patch's credit line and description for the DLL it loads.
2. **No module of our own** (2026-10-01). The fixes go to the accelerator's repository, and this
   repository keeps only the loader patch. The DLL is not committed here.
