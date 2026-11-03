# Loading a DLL from game.dat's own import table

Engine build `2.01.2614.37001`. This patch does not depend on the build: it edits the PE import
directory, which every Windows executable has, and reads nothing else. Checked on 2026-10-28
against a `game.dat` carrying `cah-factions` (11,347,456 bytes).

- **Status: built and unit-tested. Loader behaviour checked under Wine 9.0 on a small 32-bit test
  executable, not yet with `game.dat` on Windows.** Registered as the experimental `dll-import`
  patch.
- **What it is for:** applying an in-memory patcher, such as
  [bfme2-patcher](https://github.com/DarkAtra/bfme2-patcher)'s `game-patcher.dll`, to the file
  instead of injecting it at every launch.
- **Cost:** one section of a few hundred bytes (`.dllimp`) and one data-directory entry. No code
  in `game.dat` is touched.

## 1. Why an import works where an injector was used

The Windows loader resolves an executable's whole import table before running any of its code:
it maps each DLL the import directory names, fills the executable's IAT slots, and then runs each
DLL's `DllMain(DLL_PROCESS_ATTACH)`. Only after that does it jump to the executable's entry point.
So a DLL listed in the import directory gets the same moment an injector aims for when it creates
the process suspended: before the game's first instruction, on the main thread.

`game-patcher.dll` is written for exactly this. It exports an empty `Noop()` whose comment says
the export "is only required when the dll is loaded by manipulating the process's import table",
and its EasyHook setup passes the ACL value for "loaded via the main thread (i.e. by manipulating
the import table)". Its `DllMain` applies its patches, hooks `gethostbyname` and patches the
certificate check, which is everything the injected path does.

**Checked under Wine** with a 32-bit test executable built with MinGW and a probe DLL that exports
`Noop`. Patched with `dll-import --dll probe.dll:Noop`:

| run | result |
|---|---|
| unpatched `host.exe` | `host main` only |
| patched, DLL beside it | the probe's `DllMain` prints first, then `host main` |
| inside that `DllMain` | the host's IAT slot for `GetTickCount` already holds kernel32's address |
| patched, DLL missing | the process never starts: `import_dll Library probe.dll ... not found`, status `c0000135` |

The third row matters for `game-patcher.dll`'s `sse_rounding`, which rewrites `game.dat`'s IAT
slots for `floor`, `ceil`, `sqrt` and `fabs` from `DllMain`. That only works if the loader has
already filled those slots, and it has.

## 2. What the patch writes

`game.dat`'s import directory already sits in a non-stock section (`.mackt`, RVA `0xAC6000`, 23
descriptors). Every descriptor is IAT-only (`OriginalFirstThunk = 0`). There is no bound-import
directory, no IAT directory and no delay-load directory.

The patch:

1. Copies every existing descriptor, byte for byte, into a new `.dllimp` section allocated with
   `allocate_section`. The copies still point at their original names and IAT slots, so every
   `call [iat]` in the engine and in other patches' caves keeps its target.
2. Adds one descriptor per DLL: a lookup table and an IAT, each with one by-name entry and a
   terminator, the hint/name entry and the DLL name. The IAT gets its own copy because the loader
   overwrites it with the resolved address.
3. Ends with the null descriptor and points data directory 1 at the new table.

The section is `0xC0000040` (initialised data, read, write). The loader writes the new IAT, and
with no IAT directory to tell it which pages to unprotect, a read-only section would rely on the
loader's fallback.

`detect` tells added descriptors from copied stock ones by where their name string lives: only an
added DLL's name is inside a `.dllimp` section. That also works across two applications, since the
second copies the first's descriptors, names and all.

## 3. Using it with bfme2-patcher

1. Build `game-patcher.dll` (bfme2-patcher's `game-patcher` Gradle project, MSVC, 32-bit x86).
   Leave out the patches that collide with pySAGE ones already in your `game.dat` (§4), e.g.
   `/DGAME_PATCHER_RENDER_RATE=0 /DGAME_PATCHER_PERF_SCOPE_SKIP=0`.
2. Put `game-patcher.dll` **and `EasyHook32.dll`**, which it imports, beside `game.dat`.
3. `sage-patch apply dll-import --in game.dat --out game.dat` (defaults to
   `game-patcher.dll:Noop`; repeat `--dll NAME:EXPORT` for other DLLs).
4. Launch as usual, without the updater's injector. Launching through the updater too would load
   the DLL twice.

## 4. What can go wrong

- **A missing DLL stops the game from starting.** Windows reports the missing DLL by name and
  exits. Keep an unpatched `game.dat` for that case.
- **Sites both projects patch.** `game-patcher.dll` checks every byte it rewrites and skips a patch
  whose bytes differ, then shows a message box listing what it skipped, on every launch. With a
  pySAGE `game.dat` that happens for its `render_rate` (pySAGE `render-rate`) and
  `perf_scope_skip` (pySAGE `perf-scope-skip`, and `perf-stage-readout`, which hooks the same
  constructor). None of its other eight patches overlaps a site any pySAGE patch edits. Turn the
  two off at build time instead.
- **The message box runs inside `DllMain`.** That is under the loader lock, which Microsoft warns
  against. It is the DLL's own behaviour, and only on that failure path.
- **`binary-attest` cannot see the DLL.** It hashes `.text` when the patch is applied, not the
  running code. Two peers with the same `game.dat` but different builds of the DLL are not told
  apart, and `game-patcher.dll`'s pathfinding and collision patches change simulation code. Every
  peer should run the same DLL build.
- **Antivirus.** A new import of an unsigned DLL is a common malware pattern, and some scanners
  flag it.

## 5. Not known

- Whether `game.dat` with `game-patcher.dll` behaves on Windows exactly as the injected path does.
  Wine's loader follows the same order, but no game has been played this way yet.
- Whether `lotrbfme2ep1.exe`, the launcher that starts `game.dat`, changes the DLL search path.
  The executable's own folder is searched first by default, which is where the DLL is put.
