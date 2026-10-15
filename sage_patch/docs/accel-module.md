# Loading OH1A's accelerator from `game.dat`

The `accel-module` patch makes `game.dat` load OH1A's BFME2 Accelerator, `bfme2_accel.dll`, by
itself, in place of the accelerator's injecting loader.

**Status 2026-10-15: the loader cave works (armed in Edain since 2026-09-24). The DLL it loads does
not yet run Edain: Accelerator 2.0, stock or with the fixes in §3, hangs or crashes at the load
screen or as the main menu comes up (§4.4).** Ship `game.dat` with the patch if you like, since
without the DLL beside it the game runs as stock, but do not ship the DLL.

## TL;DR

- **The accelerator is OH1A's, not ours.** OH1A publishes its source under the MIT licence
  ([github.com/OhadBaehr/bfme2-accelerator](https://github.com/OhadBaehr/bfme2-accelerator)), so
  the faults it has on a patched `game.dat` are fixed there (§3), not duplicated here.
- **What lives here:** this patch, the arming site (§2), what 2.0 does on Edain (§4), and a census's
  findings (§5).
- **The DLL has to be a build with the §3 fixes.** Stock `bfme2_accel.dll` identifies its build by a
  hash over all of `.text`. Any `sage_patch` edit makes that hash unknown, and on an unknown build
  it guesses the game thread and leaves the engine-specific features off ([`accel-port.md`](accel-port.md) §1).
- **Windows 10/11 rewrite the device's vtable on every `BeginStateBlock`** (§4.2), so the DLL has to
  re-hook the device after every call, not once a second.
- **Edain's XP compatibility mode wraps the device in a shim** that defeats the hooks a second way
  (§4.3). [`os-name-fallback`](os-name-fallback.md) removes the reason Edain needs that mode.
- **Still open:** with all of that fixed, the render worker stalls inside the NVIDIA driver or
  crashes in a queued surface `Release` (§4.4). A report for OH1A is written (§4.5).

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

The fixes live on the user's fork, `ClementJ18/bfme2-accelerator`:

- **`patched-builds`**, on 1.0, with fixes 1-4. Built 2026-10-01, never played.
- **`edain-2.0`**, on OH1A's 2.0 (`c993d9a`, build 73), with fixes 1-7. Built and run in Edain on
  2026-10-15 (§4).

1. **The game thread, named rather than guessed.** On an unrecognised build the original took the
   first thread to make 64 effect calls, and the load screen draws first
   ([`accel-thread-identity.md`](accel-thread-identity.md)). The fix takes the thread that owns the
   device's focus window, read once from the device the first effect is created on. The engine
   creates that window on the game thread. The call count stays as the fallback. Confirmed in every
   2.0 run.
2. **Device hooks put back whenever the table is rewritten.** On 1.0 this was after `Reset` and once
   a second. On 2.0 it is after every record the worker runs and before every release of the render
   lock (`rtDevCheck`, `rtExecLeave()`), because `d3d9.dll` rewrites the table on every
   `BeginStateBlock` (§4.2). The check is one pointer compare.
3. **Device `Release` drains only when it may be the last.** The census counted 200 to 380 device
   releases a late-game frame (§5), and each one was a full queue drain. The compile switch
   `AOTR_RELEASE_DRAINS` turns this off for testing.
4. **The effect de-dupe forgets what it does not follow.** `SetValue`, the array setters,
   `SetString`, `SetArrayRange`, `SetRawValue`, and setters called by name. Otherwise a later
   write of the remembered value can be skipped.
5. **(2.0) The re-hook leaves 2.0's own shims in place.** `twWrap` (in-between frames) and `spWrap`
   (smooth shadows) put shims into the hooks' original-pointer table. A re-hook that writes the new
   original there removes them, so `twRebase` / `spRebase` update the shim's kept original instead.
6. **(2.0) The game thread's wait for the render lock lets window messages through.** 2.0's queue
   drain already did this once the worker had not finished a record for 100 ms. Taking the lock did
   not, and it deadlocked with the worker inside `Present` waiting on the window. `rtExecEnter()`
   applies the same rule.
7. **(2.0) Diagnostics.** `rt: diag -` lines for every `Reset`, a `Release` on a device other than
   the hooked one, the device's last `Release`, and the slot owners on a rewrite. Remove them
   before offering the branch upstream.

The fixes also install the minimap pixel writes, the shroud updates and the radar mirrors on an
unrecognised build. Each already checks the bytes at its own sites, and without the pixel writes
alone the render thread drains its queue about 650 times a battle frame.

**Building it.** VS 2022 Build Tools (the C++ workload), then `src\build.bat`. That writes
`src\aotr_accel.dll`, the reporting build, which logs a render-thread report every 5 s.
`src\build_prod.bat` writes `src\bfme2_accel.new.dll`, the shipped build without the reports.
Either one is renamed to `bfme2_accel.dll` beside `game.dat`. `src\aotr_rt_gen.inc` is generated by
`src\gen_rt_hooks.py`; edit the generator, not the output.

## 4. Accelerator 2.0 on Edain

Run 2026-10-15 on Windows 11 build 26100, `d3d9.dll` 10.0.26100.9549, NVIDIA driver 32.0.15.9186,
from the pySAGE-edain toolbar's `game.dat`.

### 4.1 What 2.0 does on a patched build

2.0 adds a `bfme2_accel.ini` with an `[Engine]` section (`FpsLimit`, `LogicHz`, `SmoothAnimation`,
`MergeDraws`, `InBetweenFrames`, `PictureBeat`, `PanPictures`, `ExitFix`, `FactionAI`,
`ScriptTableSort`, `StreamerSets`, `TerrainThreads`, ...). Every one of those depends on the
whole-`.text` hash, so on any patched `game.dat` the log says
`init: an unrecognised build of this engine` and none of them run. What does run is
build-independent: the render thread, `TextureThreads`, `TextureCache`, `FileReadAhead`,
`FileWarm`, `rpmalloc` and the fast CRT. In particular, 2.0's 60 fps is not available on Edain, and
`render-rate` still has to provide the higher frame rate. The two must not both be active if that
ever changes, because each moves the client rate.

### 4.2 `d3d9.dll` rewrites the device's vtable on every `BeginStateBlock`

The device's vtable is a heap copy beside the device (`device 3D0FFF40`, `vtable 3D102E9C`), and
`d3d9.dll` writes all 119 entries back to its own functions during `BeginStateBlock`. That was
logged from the call site:

```
rt: the device's vtable was rewritten during a call that held the render lock (called from 005515D6, thread 29364) - rewrite 1.
rt: diag - device slots no longer ours: 109 hold the original taken at hooking, 10 hold something else
```

`0x005515D6` returns from `call [vtable+0xF0]`, slot 60. During loading it happened dozens of times a
second. The 10 "something else" are 2.0's own `twWrap`/`spWrap` slots.

Stock 2.0 never re-hooks, so after the first state block every device call from the game thread
reaches `d3d9.dll` directly while the worker may be inside it. One stock run deadlocked that way,
with the game thread and the worker both in D3D9, waiting in the driver.

### 4.3 The Windows XP compatibility mode wraps the device

Edain installs set `game.dat` and the launcher to `~ WINXPSP3`
(`HKCU\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers`). Under it the device's
table belongs to `apphelp.dll`, with its own `QueryInterface`, `Release` and `Reset`, and the shim
swaps d3d9's original table back in around its own calls. It was caught mid-swap with slots 0, 2 and
16 holding d3d9's functions instead of apphelp's.

`game.dat` only needs the mode because of a startup crash that
[`os-name-fallback`](os-name-fallback.md) fixes. With that patch, the mode can be off. It has to be
off on the launcher too, because a launcher in compatibility mode passes the layer to `game.dat`
through `__COMPAT_LAYER`.

### 4.4 Still open

With fixes 1-7 and no compatibility mode, every run ends at the load screen or as the main menu
fades in, in one of two ways:

- **The worker stalls inside the driver**, alone in D3D9, while nobody holds the render lock and the
  game thread waits in the queue drain (letting window messages through):
  `nvd3dum+16eb402 ... D3D9+4bef0 ... D3D9+e044b | twRealPresent | twPresentCore`. The same
  `D3D9+4bef0` wait appears from a draw as well as from `Present`.
- **The worker crashes in a queued surface `Release`.** `d3d9+0x626bd`, the helper just before
  `Surface::Release` (`+0x62730`), calls the device's `Release` through the vtable, and d3d9 faults
  inside it (`D3D9.DLL+0x48239`, reading `[[edi+8]+0x14]` with `[edi+8] = 0x15`).

Stock 2.0 fails at the same moment: once with an NVIDIA driver worker thread jumping to garbage
(`0x00198086`, frames only in `nvd3dum.dll`), and with the driver's Threaded optimization off, with
the §4.2 deadlock. Threaded optimization off did not help the `edain-2.0` build either; it stalled
earlier, at the first load screen.

What the driver waits on, and what damaged the surface, cannot be read from outside the driver. The
likeliest remaining cause is a device call that still reaches the driver from a second thread, but
none was found in the stacks.

### 4.5 Reporting upstream

A report for OH1A was written on 2026-10-15, to be posted as an issue on his repository and to
point at `edain-2.0` once that branch is pushed. It also asks whether the `[Engine]` options could check the bytes at their own sites, as the
minimap, shroud and radar hooks already do, so they would run on a patched build.

### 4.6 How the hangs were read

The game's own crash dumps (`C:\RotWK\DUMP_*.dmp`) are only usable when they are full-memory
dumps of about 690 MB. Smaller ones written while the accelerator was loaded had every stream
directory entry zeroed. For a hang, the threads of the live process were read instead: suspend
each thread, `Wow64GetThreadContext`, read its stack with `ReadProcessMemory`, and match return
addresses to module ranges. The owner of `g_rtExecCs` is its `OwningThread` field, at the DLL's base
plus the offset the build's `.map` gives.

## 5. What the census measured

The census was a set of pass-through hooks on every device, effect and lock call, counting what a
render thread would queue and what would make it wait. It ran in Edain on 2026-09-24, under the XP
compatibility mode (§4.3).

**The device's vtable belonged to the Windows compatibility shim.** It sat at a heap address, and its
`QueryInterface` was in `apphelp.dll`: the shim copied `d3d9`'s table and hooked entries in it. Four
runs established how to live with it:

1. Hooked entry by entry, all 119 slots were put back by the shim within 10 s
   (`Present slot is D3D9.DLL+0xE05D0 - REPLACED`). The census attributed this to the engine's
   startup `Reset` (`0x0052220F`). §4.2 and §4.3 show it is the shim's own table swap and
   `d3d9.dll`'s rewrite on `BeginStateBlock`.
2. Giving the device a table of our own crashed inside that `Reset`, calling address 0 from
   `apphelp.dll+0x80D6C`: the shim finds its saved original by the device's vtable pointer.
3. So the device is hooked in place, and the hooks are put back after the table is rewritten, taking
   whatever is in each slot as that slot's original.

**`game.dat` has no import name table.** Every import descriptor's `OriginalFirstThunk` is 0, so once
the game is loaded its IAT holds only resolved addresses. An import hook must find its slot by the
address `GetProcAddress` gives, not by name; a by-name lookup crashes at startup. The accelerator
already finds slots by address.

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

## 6. Testing it

1. Build the DLL from `edain-2.0` (§3), or take the copies in that repository's `dist\report`
   (reporting) or `dist\prod`.
2. Copy it beside `game.dat` as `bfme2_accel.dll`. The pySAGE-edain toolbar replaces `game.dat` on
   every launch from `tools\mod-starter\assets\tools\game.dat`, but leaves the DLL alone.
3. `sage-patch apply accel-module` (and `os-name-fallback`) on the `game.dat` the toolbar ships, and
   turn the compatibility mode off on `game.dat` and on the launcher (§4.3).
4. Start Edain. `bfme2_accel.log` should show, in this order:
   - `init: an unrecognised build of this engine` (expected: the patches changed `.text`);
   - `rt: armed`;
   - `the device's focus window ... belongs to thread N`;
   - `Device vtable ... implemented in D3D9.DLL` (with the compatibility mode on it says
     `apphelp.dll`);
   - `RENDER THREAD LIVE ... game thread N`, with the same `N`;
   - `the device's vtable was rewritten during ...` lines, the §4.2 rewrite being caught.
5. Sit through a loading screen, alt-tab once (a `Reset`), and play into a large late-game army.
   Scroll Lock switches the render thread off and on, so frame rates can be compared in one match.
6. Remove the DLL and check the patched game still starts as stock.

A hung game leaves `game.dat` processes that cannot be ended and keep the DLL mapped. A loaded DLL
can still be renamed, so rename the old one aside before copying a new build in.

## 7. Decisions

1. **Credit** (2026-09-24). `author = "officialNecro"`, who is asked for fixes to the patch; OH1A is
   credited in the patch's credit line and description for the DLL it loads.
2. **No module of our own** (2026-10-01). The fixes go to the accelerator's repository, and this
   repository keeps only the loader patch. The DLL is not committed here.
3. **Report rather than keep patching** (2026-10-15). The §4.4 failure happens in stock 2.0 too, and
   the stacks end inside the driver, so it goes to OH1A (§4.5) with the branch as a starting point.
