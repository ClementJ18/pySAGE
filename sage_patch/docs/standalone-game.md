# A standalone `game.dat` — cutting the install loose from the registry

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR), derived from
the stock `game.dat` (11,346,944 bytes) in this repo's fixtures. The launcher figures
(`lotrbfme2ep1.exe`) are carried over from [`multi-instance.md`](multi-instance.md), which already
reverse-engineered that shim; they are **not** re-derived here because the launcher binary was not
in hand when this was scoped.

> **The launcher half has since been done, and this document was wrong about it.** See
> [`standalone-launcher.md`](standalone-launcher.md). The shim does not resolve `game.dat` through
> the registry at all — it chdirs into its own image directory and spawns from there, so §2's third
> requirement was already met by the stock binary. The real dependency is one this document did not
> anticipate, on the far side of `CreateProcess`. §3's `StandaloneLauncherPatch` and §4's last row
> are corrected below; the `game.dat` sections are as originally scoped and still unbuilt.

- **Goal:** a `game.dat` that runs from wherever it sits, with **no dependency on the RotWK
  registry keys** and with the user-data / install folders **supplied by the operator**, so the
  binary can be dropped into an arbitrary directory and driven by an external mod launcher — the
  same slot Edain's launcher, a portable install, or a CI harness would plug into.
- **Cost / Risk / Status:** to be finalised per approach below. **Status: scoped — not built, not
  runtime-verified.** This document is stage 1 (locate) of the pipeline in
  [`runtime-re-workflow.md`](runtime-re-workflow.md); the byte-writing is stage 2.

This is the piece [`multi-instance.md`](multi-instance.md) called out and declined: *"doing so
would mean patching the path resolution rather than a branch."* That is exactly what is scoped
here.

## 1. What the stock engine seeks today, and where

Four distinct mechanisms decide where the engine reads and writes. Only two of them touch the
registry; the other two are already relative and are worth stating so the patch does not disturb
them.

### 1a. The working directory — already the executable's own folder

`WinMain` sets the current directory to the directory the running image lives in, before anything
else, and it does **not** use the registry to do it:

```
00402866  lea   eax, [ebp-0x2d4]
0040286e  call  [GetModuleFileNameW]     ; full path of this game.dat
0040287b  call  [wcslen]
00402882  lea   eax, [ebp+eax*2-0x2d4]    ; walk to the end
00402893  cmp   word [eax], '\'           ; find the last separator
00402899  mov   word [eax], di            ; di = 0 -> truncate the exe name off
004028a3  call  [SetCurrentDirectoryW]    ; chdir into our own directory
```

So a `game.dat` placed in a standalone folder already treats that folder as `.`. **This is the
half that is standalone by construction** and the patch must leave it alone — every data-file
lookup that resolves against the working directory is already pointed at the right place.

### 1b. `gi.dat` — the field block that names the registry keys and the user-data leaf

`gi.dat` (a plain `key value` text file, read from the working directory) is parsed once into a
run of `AsciiString*` globals. The parser is a chain of `strcmp`-then-store handlers entered at
`0x00AAA5A0`, driven by `0x00AAA6C0` behind the once-flag at `0x00DF0918`:

| `gi.dat` key | global | accessor (parse-on-first-call) |
|---|---|---|
| `SkuName` | `0x00DC1340` | `0x00AAA840` |
| `GameName` | `0x00DC1344` | `0x00AAA860` |
| `GameRegPath` | `0x00DC1348` | `0x00AAA880` |
| `InstallerRegPath` | `0x00DC134C` | `0x00AAA8A0` |
| `OnlineServer` | `0x00DC1350` | `0x00AAA8C0` |
| `UserDataLeafName` | `0x00DC1354` | `0x00AAA8E0` |
| *(G-field)* | `0x00DC1358` | `0x00AAA900` |

Each accessor is the ten-identical-accessor idiom [`multi-instance.md`](multi-instance.md) names
(`§ The mutex name is not a literal either`): `if not parsed: parse(); return global`. **The
strings that drive the registry lookup are already data in a file the operator controls** — this
is the lever the patch leans on rather than fights.

### 1c. The install path — read from HKLM (the "seeks bfme2" behaviour)

The path subsystem at `0x00640000`+ turns `GameRegPath` / `InstallerRegPath` into an
`HKEY_LOCAL_MACHINE` key and reads a value out of it. The generic helper is `0x00640BF3`:

```
00640c24  push 0x20019                    ; KEY_READ
00640c2c  push [ebp+8]                     ; hKey  (HKLM, from the caller)
00640c2f  call [RegOpenKeyExA]             ; subkey = arg (the *RegPath string)
...
00640c59  call [RegQueryValueExA]          ; value  = arg
```

and the `InstallerRegPath` caller at `0x00640F00` supplies `HKEY_LOCAL_MACHINE`:

```
00640f3b  call 0x00AAA8A0                  ; InstallerRegPath accessor
00640f45  call 0x00640A7A                  ; build the key string
00640f53  push 0x80000002                  ; HKEY_LOCAL_MACHINE
00640f5c  call 0x00640A9A                  ; open + query
```

A second reader at `0x00978760` pulls the literal value name `InstallPath` (`0x00C850F4`) and
stores the result in the global at `0x00DEBD6C`. **These HKLM reads are "the engine seeks the
bfme2 install path".** On a machine with no RotWK install — a CI box, a portable stick, a fresh
container — the key is absent and the engine falls back to (at best) the working directory or (at
worst) an empty root, which is why a bare copy misbehaves today.

### 1d. The user-data directory — `%APPDATA%\My <GameName> Files\`, keyed off `UserDataLeafName`

`Options.ini`, `Last Replay.BfME2Replay`, save games and the `UserData\Maps` tree
(`0x00C1D9A8`, consumed at `0x00702578`) all resolve under a per-user folder. It is built from a
`SHELL32` known-folder (APPDATA) plus the `UserDataLeafName` accessor (`0x00AAA8E0`), consumed at
`0x006412D7` and `0x006417AF`. `UserDataLeafName` is already a `gi.dat` field — so **the user-data
folder is already operator-configurable** without a patch, provided the engine gets that far.

## 2. What "standalone" actually requires

Cross-referencing §1: two of the four mechanisms (working dir §1a, user-data leaf §1d) are already
relative or already data-driven. The standalone gap is exactly the two HKLM reads in §1c, plus the
launcher shim that uses the *same* registry to find `game.dat` in the first place.

1. **Sever the HKLM install-path dependency in `game.dat`** so the engine's install root is the
   working directory (§1a) — or an operator-supplied path — instead of an `InstallPath` value that
   may not exist.
2. **Expose the folder/registry values as operator input.** Most are already `gi.dat` fields; the
   remaining decision is *how* an external launcher overrides them (§3).
3. **Patch `lotrbfme2ep1.exe`** so the launcher starts the `game.dat` beside it rather than the one
   the registry points at — this is what makes a shortcut (or a mod launcher's spawn call) land on
   the custom install.

## 3. Proposed design

Two patches, mirroring the `multi-instance` / `multi-instance-launcher` split, because the work is
again spread across two binaries and the CLI patches one image at a time.

### `StandalonePatch` — `game.dat`

Neutralise the two HKLM reads (§1c) so the install root is resolved locally. Two candidate
strategies, in increasing order of flexibility:

- **(A) Redirect to the working directory.** Make `0x00640F00` / `0x00978760` skip the
  `RegOpenKeyExA` / `RegQueryValueExA` pair and return the current directory (already the exe's own
  folder, §1a) as the install path. Cheapest, deterministic, no new input surface. The install path
  *is* wherever `game.dat` was dropped.
- **(B) Redirect to an operator-supplied string.** Same hook, but the returned path comes from a
  patched-in literal (a patch parameter, baked and `verify`-checkable in the repo's usual model) or
  from a new `gi.dat` field read through the existing parser (§1b) — e.g. `InstallPath <path>`,
  which slots into the field chain at `0x00AAA5A0` and a fresh global for one more `strcmp`. This
  is the "pass a custom value for the folder path" the task asks for, and it composes with (A) as
  the default when the field is absent.

**Recommendation: build (A) as the floor and layer (B)'s `gi.dat` field on top**, so the default
behaviour needs zero configuration (drop-in) and a launcher that wants an out-of-tree data root
sets one `gi.dat` line. The `GameRegPath` / `InstallerRegPath` / `UserDataLeafName` values are
*already* `gi.dat`-editable (§1b/§1d), so the only genuinely new input is the install path itself,
and folding it into `gi.dat` keeps all path configuration in one operator-owned file rather than
splitting it across a file and a patch flag.

### ~~`StandaloneLauncherPatch` — `lotrbfme2ep1.exe`~~ — superseded

> ~~The launcher reads `lotrbfme2ep1.lcf`, resolves `game.dat`'s location, and starts it. […] The
> patch makes it launch `.\game.dat` (relative to the launcher) instead of the registry-resolved
> path.~~

Wrong on both counts, and the correction is in
[`standalone-launcher.md`](standalone-launcher.md). The shim `chdir`s into the directory of its own
image — `argv[0]`, which the MSVC CRT seeds from the module path, not from the command line — and
then spawns with `lpApplicationName = NULL` and `lpCurrentDirectory = NULL`, so `game.dat` is found
beside the launcher and the registry is nowhere on that route. A patch for the resolve site was
built and measured to change nothing.

What is registry-bound runs **after** `CreateProcessA` returns: the launcher hands the game a token
through the `game2.dat` shared mapping, and derives it by Blowfish-decrypting a payload under a key
built from `HKLM\<GameRegPath>\InstallPath` and that path's volume serial number. On a relocated
copy every input to that key is wrong, and nothing refuses — the game simply receives the wrong
plaintext. `standalone-launcher` replaces the derivation with `gi.dat`'s otherwise-unused `G4`
field, in 38 bytes, in place.

### Why not just delete the registry keys or ship a `.reg`?

Writing HKLM needs admin and pollutes a shared machine; it also does not survive a portable copy,
which is the whole point. Patching the read is the only approach that makes the binary itself
location-independent.

## 4. Hook sites (candidate)

| Binary | VA | Stock behaviour | Standalone action |
|---|---|---|---|
| `game.dat` | `0x00640F00` | open `HKLM\<InstallerRegPath>`, query install path | return working dir / `gi.dat` `InstallPath` |
| `game.dat` | `0x00978760` | read `InstallPath` value → `0x00DEBD6C` | same source as above |
| `game.dat` | `0x00AAA5A0` | `gi.dat` field chain | *(B only)* one more `strcmp`/store for `InstallPath` |
| `lotrbfme2ep1.exe` | ~~*TBD*~~ `0x0040B533` | ~~resolve `game.dat` via registry~~ decrypt the shared-memory token under an `InstallPath` + volume-serial key | **built**: take it from `gi.dat`'s `G4` instead ([`standalone-launcher.md`](standalone-launcher.md) §3) |

Left deliberately untouched: the `WinMain` chdir (§1a), the `UserDataLeafName` consumers (§1d), and
the `gi.dat` parser's existing fields — all already do the right thing for a relocated install.

## 5. Composition

Neither game-side strategy allocates a cave in a byte range any bundled patch touches (the
`0x00640000` path subsystem and `0x00978760` are outside every existing patch's footprint; the
`gi.dat` parser at `0x00AAA5A0` is adjacent to but distinct from the accessors `multi-instance`
*reads* but never writes). It should be order-independent with the whole bundle under the
[`Patch` composition contract](../patcher.py). The launcher patch shares `lotrbfme2ep1.exe` with
`multi-instance-launcher`; the two edit different sites and should compose, but that must be
asserted once the launcher binary is in hand.

## 6. Verification & runtime plan

- **`verify`** re-derives the patched bytes from the same parameters (working-dir redirect, or the
  `gi.dat` field name), matching the repo's disassembler-free structural check.
- **Runtime** (the oracle in [`runtime-re-workflow.md`](runtime-re-workflow.md)): drop a patched
  `game.dat` + `gi.dat` in a directory with **no** RotWK registry keys present (rename/remove the
  HKLM key, or test in a clean container), confirm it starts, loads its data, and writes
  `Options.ini` / replays under the `UserDataLeafName` folder — not under a stock RotWK path.
  Then repeat driven by the launcher to confirm the shim lands on the local `game.dat`.

## Open questions

- ~~**The launcher binary.**~~ **Answered.** `lotrbfme2ep1.exe` was reverse-engineered against the
  real file in [`standalone-launcher.md`](standalone-launcher.md), and the answer was not the one
  §3 predicted: the resolution site does not exist, and the dependency that does is at
  `0x0040B533`. The patch is built, and the instrumentation method it used (a `.probe` section
  writing marker files, §4 there) is the tool for the two `game.dat` questions below.
- **Second install-path reader.** `0x00978760` (→ `0x00DEBD6C`) and the `0x00640F00` subsystem may
  or may not be independently load-bearing at startup; which reads are actually consulted on the
  fatal path wants a runtime breakpoint pass (step 4 of the workflow doc) before both are assumed
  necessary to hook.
- **Multiplayer / online.** `OnlineServer` (§1b) and the GameSpy registration keys are a separate
  surface; a standalone build that only needs skirmish/LAN/replays can ignore them, but an online
  build cannot, and that is out of this scope.
- **Shared user-data across copies.** As `multi-instance.md` notes, nothing here separates two
  instances' `Options.ini`; a per-instance `UserDataLeafName` (already a `gi.dat` field) is the
  lever if that is wanted, but it is orthogonal to going standalone.
