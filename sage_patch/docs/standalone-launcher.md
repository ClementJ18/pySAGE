# The launcher half of standalone

The launcher shim `lotrbfme2ep1.exe` shipped beside ROTWK's `game.dat` (499,712 bytes, ImageBase
`0x400000`, `DllCharacteristics = 0` so no ASLR — a VA here is also where the byte sits in a
running process). This is the binary [`standalone-game.md`](standalone-game.md) §3 scoped a
`StandaloneLauncherPatch` against, before the file was in hand.

- **Cost:** 38 bytes, in place. No cave, no section, no relocation.
- **Risk:** low, and unusually well evidenced: the patched image is **byte-identical to the
  launcher the Edain mod ships**, which is what `apply` is asserted to reproduce.
- **Status:** **built** — [`patches/standalone_launcher.py`](../patches/standalone_launcher.py).
  The path half is **runtime-verified** (§2, §5); the token half is the edit Edain has shipped for
  years, and is verified here only as far as byte identity with theirs.

```sh
sage-patch apply  standalone-launcher --in lotrbfme2ep1.exe.backup --out lotrbfme2ep1.exe
sage-patch verify standalone-launcher lotrbfme2ep1.exe
```

## 1. Two halves, and only one of them needed patching

The scope document, working from `multi-instance.md`'s prior RE rather than from the binary, wrote:

> The launcher reads `lotrbfme2ep1.lcf`, resolves `game.dat`'s location, and starts it. […] The
> patch makes it launch `.\game.dat` (relative to the launcher) instead of the registry-resolved
> path.

There is no registry-resolved path, and the shim needs no help finding `game.dat` (§2). What is
registry-bound is what happens **after** the spawn: the launcher hands the game a token through
shared memory, and it derives that token from where the registry says the game is installed and
which volume that is (§3). That is the install lock, and that is the patch.

## 2. Finding and starting the game — already standalone

`main` is at `0x00409140` — a CRT `main(argc, argv, envp)`, with `argv` at `[esp+0x10cc]` once the
frame is up. Its first two acts are to remember where it was started from and then to leave:

```
0040917c  call 0x00448ed3            ; _getcwd(buf, 0x104)  — kept, and restored at 0x00409872
00409181  mov  esi, [esp+0x10d4]     ; argv
00409188  mov  ecx, [esi]            ; argv[0]
0040918b  call 0x004085c0            ; chdir into argv[0]'s directory
00409190  mov  eax, [esi]            ; argv[0] again — the .lcf name is built from it
```

`0x004085C0` is the whole of the path logic, and it is the C runtime doing the work:

```
004085f4  call 0x004492d5            ; _splitpath(path, drive, dir, fname, ext)
0040860f  call 0x00449245            ; _makepath(out, drive, dir, NULL, NULL)
00408629  ...                        ; strip the trailing '\'
0040864a  call 0x004485b7            ; toupper(out[0])
00408653  call 0x004491b7            ; _chdrive(that - 'A' + 1)
0040865b  test eax, eax
0040865d  jne  0x0040866c            ; _chdrive failed -> skip the chdir entirely
00408664  call 0x0045ac57            ; _chdir(out)
```

Everything downstream hangs off that one directory:

| what | where | how it is named |
|---|---|---|
| `lotrbfme2ep1.lcf` | `0x00409190`–`0x0040935B` | `argv[0]` with the last `.ext` replaced by `".lcf"` (`0x00460B98`) |
| `gi.dat`, `launcher\*.csf`, `launcher\launcher.bmp` | — | relative, i.e. against the directory just entered |
| the second chdir, immediately before the launch | `0x004097DF` and `0x00408864` | `argv[0]` again, re-read from the array |
| `game.dat` | `0x0040ACB0` → `0x0040AD58` | the `.lcf`'s `RUN` line, as a command line |

The launch itself takes no path at all:

```
0040ad00  ...                        ; cmdline  = strcpy(buf, run+0x100)
0040ad2f  ...                        ;            strcat(buf, run+0x200)
0040ad42  push 0                     ; lpCurrentDirectory = NULL
0040ad55  push edx                   ; lpCommandLine      = buf
0040ad56  push 0                     ; lpApplicationName  = NULL
0040ad58  call [CreateProcessA]
```

`RUN` (`0x00460EA4`, plus the `"RUN2"` / `"RUNEAD"` variants at `0x00460B50` / `0x00460B48`) is
parsed by `0x0040AE70`, which splits the value on `" "` (`0x00460950`). The shipped line is

```
RUN  = . game.dat
```

and the command line that reaches `CreateProcessA` is measured (§4) to be exactly **`game.dat`** —
the first field never reaches it. So the `game.dat` that starts is the one `CreateProcess` finds
first, and the first entry of that search order is *the directory the calling image loaded from*,
which is the launcher's own. Pinned, without anything having to say so.

### `argv[0]` is not the command-line token

The obvious objection is that `argv[0]` is whatever the parent put in the command line, so a
launcher spawned by bare name would have no drive letter, `_chdrive` would fail, `0x0040865D`
would skip the `chdir`, and every lookup in the table above would land in the inherited working
directory. A patch for exactly that was written, applied, verified — and then measured to change
nothing, because the premise is false.

The MSVC CRT seeds `argv[0]` from the **module path**, not from `GetCommandLineA`'s first token.
Measured rather than argued (§5, row 4): with a valid `lotrbfme2ep1.lcf` in the working directory,
none beside the executable, and the executable spawned as
`CreateProcess(<full path>, "lotrbfme2ep1.exe")`, the shim reports its config file **missing** — it
looked beside its own image and nowhere else. The launcher is location-independent by construction,
the same way `game.dat`'s `WinMain` is (`standalone-game.md` §1a).

## 3. The install lock — what the patch is for

Two functions read `"InstallPath"` (`0x00460944`). One, at `0x0040791D`, only locates a patch
directory and answers "none" when the key is missing (`0x004079C1` is `xor al, al`). The other is
the one that matters.

`0x0040B1A0` runs immediately **after** `CreateProcessA` returns — its caller passes the child's
`PROCESS_INFORMATION` fields straight out of the run struct:

```
0040886f  call 0x0040acb0            ; launch()
00408874  mov  ecx, [edi+0x30c]
0040887a  mov  edx, [edi+0x300]
00408882  call 0x0040b1a0
```

and it fills the shared mapping the game reads. The mapping is `game2.dat`, opened under the name
in `gi.dat`'s `G2` field — which is why `game.dat` contains no `"game2.dat"` string; it knows the
mapping by GUID, out of the same file. What goes into it is not a constant. It is decrypted, under
a key the launcher builds out of where this install is:

```
0040b203  call [MapViewOfFileEx]     ; edi = the view, and it stays in edi all the way down
0040b271  call [RegOpenKeyExA]       ; HKLM\<GameRegPath>            (HKCU at 0x0040b289 on failure)
0040b2bb  call [RegQueryValueExA]    ; "InstallPath"
0040b2d7  call 0x004492d5            ; _splitpath -> the drive it names
0040b320  call [GetVolumeInformationA]   ; that volume's serial number
0040b338  call 0x00448d28            ; sprintf("%lx-", serial)
...
0040b529  cmp  eax, 0x38             ; clamp the key to 56 bytes — Blowfish's maximum
0040b540  call 0x00405e20            ; setKey  (its schedule copies the 18-dword P-array at 0x0045f5c0)
0040b554  call 0x004061c0            ; decrypt into edi
```

So the plaintext the game receives is right only where the registry still names *this* install and
that install still sits on the volume it was installed to. Copy the folder to a stick, drop it in a
container, or hand it to a mod launcher on a machine that never ran the EA installer, and every
input to that key is wrong.

### The replacement

`gi.dat` already carries the answer. Its tenth and last field, `G4`, has an accessor at
`0x004167B0` (returning `0x0046F5B8`) with **zero callers** in the shipped binary — a parsed,
reachable field the stock launcher never reads. The 38 bytes that set the key and decrypt become:

```
0040b533  call 0x004167b0            ; -> gi.dat's G4
0040b538  push eax
0040b539  push edi                   ; the view the decrypt would have written
0040b53a  call 0x0044a170            ; strcpy
0040b53f  add  esp, 8
0040b542  <23 * nop>
```

Everything above the site is left standing — the mapping is still opened, the registry is still
read, the volume serial is still printed. None of it is load-bearing once the answer no longer
comes from it, and leaving it in place is what lets `verify` fingerprint the derivation the patch
switches off.

**This is not a way to run a copy of the game you do not have.** The `.big` archives and `game.dat`
itself are still required and unchanged, and the token is not a gate on playing at all: the engine
is perfectly startable without the shim (`-file <map>.map` is a stock command line — see
[`headless.md`](headless.md)), which is what most of the tooling in this repository already does.
What it removes is an *install-location* lock on the launcher path, for an install that is already
yours.

### Provenance and credit

The edit is the **Edain mod's**. It ships in the Edain install as `lotrbfme2ep1.dif` — an IDA
difference file, 38 single-byte lines — beside a hand-written `lotrbfme2ep1_manual.diff` stating
the same replacement as two hex strings. An install that has run the Edain launcher already carries
it, and `sage-patch verify standalone-launcher` says so.

What this package adds is the frame around it: the same bytes as a named, attributed,
`verify`/`detect`-able patch instead of an offset in a text file; the two `rel32`s re-derived from
the function addresses rather than transcribed, so the patch states which functions it calls and
cannot disagree with itself; nine anchor sites asserted before it writes; and the derivation above,
which no `.dif` can carry. Per the README's *Credit* section, a frame is not authorship — `author`
names Edain.

## 4. How the command line and the token were measured

Static reading gets as far as "the command line is two struct fields concatenated"; it does not say
what those fields hold, because the `RUN` parser is inlined STL. So the binary was instrumented — a
throwaway `.probe` section reachable from five hooks, each writing one marker file:

| hook | site | what it records |
|---|---|---|
| A | `0x004087B0` | the "no `RUN2`/`RUNEAD`" branch was entered |
| B | `0x0040ACB0` | `launch()` was called |
| C | `0x0040AD58` | `lpCommandLine`, via `lstrlenA` + `WriteFile` |
| D | `0x0040AD58` | `GetCurrentDirectoryA` at the moment of the spawn |
| E | `0x0040AD5E` | `CreateProcessA`'s return value and `GetLastError` |

Every import the probe needs — `CreateFileA`, `WriteFile`, `CloseHandle`, `lstrlenA`,
`GetCurrentDirectoryA`, `GetLastError` — is already in the launcher's IAT, so it needs no new
import and no loader work. The same trick is available to any future launcher question.

From a self-contained folder it reported:

```
C  game.dat
D  ...\scratch\selfcontained          <- the launcher's own directory, as intended
E  CreateProcessA -> ok, GetLastError = 0
```

## 5. The experiments

`game.dat` is a copy of a real executable, so "did it start" is a live process rather than an
inference. Every row spawns the shim with `CreateProcess(<image>, <argv[0]>)` so the image and the
command-line token can be varied independently — the only way to reach the failure mode §2 was
worried about.

| # | launcher | `argv[0]` | working directory | result |
|---|---|---|---|---|
| 1 | as shipped | full path | its own | **launched** |
| 2 | as shipped | `lotrbfme2ep1.exe` | unrelated | **launched** |
| 3 | + the rejected path patch | `lotrbfme2ep1.exe` | unrelated | **launched** — indistinguishable |
| 4 | no `.lcf` beside it, a valid one in the working directory | `lotrbfme2ep1.exe` | unrelated | **refused**: config file missing, i.e. `argv[0]` is the module path |
| 5 | `gi.dat`'s `GameRegPath` / `InstallerRegPath` pointed at a nonexistent vendor | `lotrbfme2ep1.exe` | unrelated | **launched** |
| 6 | and the `.lcf`'s `SKU1` subkey likewise | `lotrbfme2ep1.exe` | unrelated | **launched** |

Rows 1–3 are the path patch's obituary. Row 4 is why. Rows 5–6 show that no registry key is needed
to *start* the game — which is exactly why the remaining dependency is the one in §3, on the far
side of `CreateProcess`, where nothing refuses and a wrong answer is simply handed over.

> **The trap that cost two wrong conclusions.** The first proof program was a copy of Windows 10's
> `notepad.exe` renamed to `game.dat`. It is spawned successfully and then **exits immediately** —
> a renamed copy of that particular binary does not stay up — so rows 1–3 all read as "nothing
> launched" and the shim looked broken in every configuration. `mspaint.exe` survives being renamed
> and gives the true answer. If a launch experiment says *nothing at all works*, suspect the proof
> program before the subject.

## 6. Composition

Order-independent with everything bundled. No cave, so nothing to place; the 38 bytes at
`0x0040B533` are touched by nothing else, and the only other patch aimed at this binary —
`multi-instance-launcher` — flips one opcode at `0x004092FA`, in a different function 0x2000 bytes
away. Applying both to one launcher is the expected case.

## 7. What is left of the standalone scope

The launcher item in [`standalone-game.md`](standalone-game.md) is closed, though not as it was
scoped: §2's third requirement ("patch `lotrbfme2ep1.exe` so the launcher starts the `game.dat`
beside it") is already true of the stock shim, and the patch that was needed instead is §3's.

The **`game.dat` side** (§1c, `0x00640F00` and `0x00978760`) remains scoped-not-built. Two findings
here bear on it, and they point in opposite directions. Against: the shim's *path* registry reads
turned out to be advisory, and both binaries locate their install by naming their own image, so the
engine's HKLM reads may be no more load-bearing than the launcher's were. For: the dependency that
did turn out to be real was the one that fails **silently and late**, with nothing refusing at the
time. Whichever it is, the method is settled — a probe at the read, a run with the key unreachable
— and it should be applied before a patch is written for them.
