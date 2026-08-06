# Running two copies of the game at once

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR), derived from a
stock `game.dat` (11,349,504 bytes) and the `lotrbfme2ep1.exe` shipped beside it (499,712 bytes).

- **Cost:** three bytes, one per gate. No cave, no section, no structure grows, no INI keyword.
- **Risk:** low. Every edit turns a `jcc` into a `jmp` with the same displacement, so the patched
  control flow is a path the stock binary already takes — just unconditionally.
- **Status:** **built** — see [`patches/multi_instance.py`](../patches/multi_instance.py).
  **Not yet runtime-verified in game.**

```
sage-patch apply multi-instance          --in game.dat.backup        --out game.dat
sage-patch apply multi-instance-launcher --in lotrbfme2ep1.exe.backup --out lotrbfme2ep1.exe
sage-patch verify multi-instance          game.dat
sage-patch verify multi-instance-launcher lotrbfme2ep1.exe
```

Both are needed. They are separate patches because they edit separate files, and the CLI applies
one image at a time.

## The complaint

Starting the game while a copy is already running puts up **"The game is already running"** and
quits. For anyone testing a mod that is a real cost: two clients on one machine is how you exercise
a network match, compare a change against an unchanged build side by side, or watch a replay while
the game that produced it is still open.

## Three gates, not one

The message comes from the launcher, so that is where the search starts — but removing it only
reveals the next gate. All three are the same construction: name a mutex, `CreateMutex`, read
`GetLastError` for `ERROR_ALREADY_EXISTS` (`0xB7`), branch.

### 1. The launcher's message — `lotrbfme2ep1.exe`

`lotrbfme2ep1.exe` is not the game; it is a ~500 KB shim that reads `lotrbfme2ep1.lcf`, locates
`game.dat` and starts it. Its instance check sits in the same function that loads the launcher's
own localisation:

```
004092c1  push 0x460bf4              ; "launcher\launcher.csf"
004092d1  push 0x460bd8              ; "launcher\gameLauncher.csf"
004092db  call 0x00416780            ; -> the G1 GUID
004092e0  push eax                   ; lpName
004092e1  push ebp                   ; bInitialOwner = FALSE
004092e2  push ebp                   ; lpMutexAttributes = NULL
004092e3  call CreateMutexA
004092ef  call GetLastError
004092f5  cmp  eax, 0xb7             ; ERROR_ALREADY_EXISTS
004092fa  jne  0x0040933e            ; <- not running: on to the .lcf and the launch
00409305  push 0x460bb8              ; "Launcher:LauncherErrorCaption"
00409314  push 0x460ba0              ; "Launcher:GameRunning"
00409322  call 0x00419420            ; the message box
00409333  call CloseHandle
00409339  jmp  0x004093ea            ; quit
```

`Launcher:GameRunning` is the CSF label behind the message. It resolves out of
`launcher\launcher.csf`, which is why the string does not appear in the executable.

**The mutex name is not a literal either.** `0x00416780` is one of ten identical accessors over a
`gi.dat` parse, cached behind a once-flag at `0x00472F00`:

```
00416780  call 0x004166e0            ; parse gi.dat if not already parsed
00416788  mov  eax, [0x0046f5ac]
0041678e  ret
```

`0x004164E0` reads `gi.dat` from the install directory and fills `0x0046F594`..`0x0046F5B8` with
its ten values, in file order. `gi.dat` ships as:

```
SkuName lotrbfme2ep1
GameName The Lord of the Rings, The Rise of the Witch-king
GameRegPath ...  InstallerRegPath ...  OnlineServer ...  UserDataLeafName ...
G1 4CE5E3EE-B113-4417-B651-6575C092F128
G2 37915039-6803-49e7-B69E-64FD313B7E8B
G3 D0BE288D-395A-4a73-A50E-A796A9E1D804
G4 D9151691-DF43-448c-87C2-742C1FC0FAEB
```

so `0x0046F5AC` is `G1` and the launcher's mutex is `4CE5E3EE-B113-4417-B651-6575C092F128`,
optionally prefixed by `0x00472D00` + `\` when that global is non-empty. Nothing in the shipped
build ever calls the setter for it (`0x00416700` has zero callers), so the prefix is always empty
and renaming the mutex per-instance is not reachable from the command line.

`G2` drives a second `CreateMutexA` at `0x0040B68F`, but that one is **not** a gate: on `0xB7` it
simply skips creating a `game2.dat`-backed file mapping and returns. It publishes the running
instance for IPC rather than blocking a new one, so it is left alone.

### 2. `game.dat`'s silent abort

Patch the launcher alone and the second copy dies with no message at all. `WinMain` has its own
check, immediately after the splash bitmap is loaded:

```
00402adb  push dword [0x00d8afd0]    ; -> L"E99E8455-CC9B-488a-BA22-0E8A8F74F9FA"
00402ae1  push 0                     ; bInitialOwner
00402ae6  push 0                     ; lpMutexAttributes
00402aed  call CreateMutexW
00402af5  call GetLastError
00402afb  cmp  eax, 0xb7
00402b00  jne  0x00402b5c            ; <- not running: on with startup
00402b04  push 0                     ; lpWindowName
00402b05  push dword [0x00d8afd0]    ; lpClassName — the same GUID
00402b0b  call FindWindowW
00402b18  call SetForegroundWindow
00402b21  call ShowWindow             ; SW_RESTORE
00402b2c  call CloseHandle
00402b5a  jmp  0x00402b7e            ; -> 0x00402b99: xor eax,eax / ret 0x10
```

The GUID is used twice: once as the mutex name, once as the **window class** name the game
registers. So the abort path is also how a second launch raises the window of the first — which is
what makes it silent by design rather than by omission.

`ret 0x10` with `eax = 0` is `WinMain` returning success, so the process exits with no dialog, no
log line and exit code 0.

### 3. `game.dat`'s wait loop, which shuts the first instance down

This one is easy to miss because it is not a refusal. `0x0063F68D` is a bool probe — the same
`CreateMutexA`/`0xB7` construction, but it closes the handle immediately and returns the answer in
`al`:

```
0063f68f  call 0x00aaa900            ; -> another gi.dat GUID
0063f699  call CreateMutexA
0063f6a1  call GetLastError
0063f6a7  cmp  eax, 0xb7
0063f6ac  sete bl
0063f6b4  call CloseHandle
0063f6bd  ret                        ; al = "another copy is running"
```

It has exactly one caller, back in `WinMain`:

```
00402c6e  call 0x0063f68d
00402c73  test al, al
00402c75  je   0x00402ca4            ; <- nobody else: on to LoadLibrary("setupapi.dll")
00402c77  call 0x0063f6bf            ; the wait loop
00402c7e  jmp  0x00402ca4             ; …and on regardless
```

The `test al, al` at `0x00402C7C` after the wait call is dead — both arms reach `0x00402CA4` — so
the loop's return value is discarded and this gate cannot refuse. What it does instead is worse:

```
0063f6d6  call PeekMessageA
0063f6e2  call timeGetTime
0063f6e6  add  edi, 0xea60           ; deadline = now + 60000 ms
0063f6ee  call 0x00aaa940            ; -> the event's name
0063f6f8  call OpenEventA
0063f702  jne  0x0063f71b
0063f705  call Sleep(0)
0063f70b  call timeGetTime
0063f70f  jb   0x0063f6ee            ; …until the deadline
0063f711  xor  al, al
0063f71b  push ebx
0063f71c  call SetEvent              ; ask the other copy to quit
0063f723  call CloseHandle
```

A named event that the running game has open is how a second copy asks it to shut down — the path
that exists so a fresh launch can take over from a stale one. Left in place, starting a second
instance **terminates the first**, after up to a minute of the second one sitting there apparently
hung. So this gate has to go too, and it is the reason the game half of the patch is two edits
rather than one.

## The edits

| Binary | VA | Stock | Patched | Gate |
|---|---|---|---|---|
| `lotrbfme2ep1.exe` | `0x004092F5` | `3D B7 00 00 00 75 42` | `3D B7 00 00 00 EB 42` | the message |
| `game.dat` | `0x00402AFB` | `3D B7 00 00 00 75 5A` | `3D B7 00 00 00 EB 5A` | the silent abort |
| `game.dat` | `0x00402C6E` | `E8 1A CA 23 00 84 C0 74 2D` | `E8 1A CA 23 00 84 C0 EB 2D` | the wait loop |

Only the opcode byte changes in each; the `rel8` displacement is untouched, so every branch still
lands exactly where it landed before. `CreateMutex` still runs and its handle is still closed on
the normal path — the mutex remains a correct "a copy of the game is running" signal for anything
else that reads it, it simply no longer stops a launch. The probe call at `0x00402C6E` is likewise
left standing rather than `nop`ped out; it has no effect beyond its own handle, and keeping it
makes the site's `rel32` part of what the patch asserts before it writes.

The bytes preceding each jump are asserted along with it, and five further call sites are asserted
and not written (`CreateMutexW`, `GetLastError`, `FindWindowW`, the probe's `CreateMutexA`, the
wait loop's `rel32`; and in the launcher, `CreateMutexA`, `GetLastError` and the two `push`es of
the CSF labels). A two-byte `75 xx` is not distinctive; those calls are.

## What this does not fix

Both processes still resolve the same user-data directory, `%APPDATA%\My The Lord of the Rings,
The Rise of the Witch-king Files`. `Options.ini` and `Last Replay.BfME2Replay` are written by
whichever instance exits last, so a run whose replay matters should not be sharing a machine with
a second client. Nothing in this patch separates the two, and doing so would mean patching the
path resolution rather than a branch.

Networking is untested and there is no command-line escape hatch for it: `game.dat` has no `-port`
option (the only port controls in the build are the `GameData` INI fields `FirewallPortOverride`
and `FirewallPortAllocationDelta`). Whether two clients on one machine can see each other on LAN
has not been checked.
