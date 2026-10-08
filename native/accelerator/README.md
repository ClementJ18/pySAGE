# pySAGE accelerator companion

This is an experimental native companion for `sage-patch accel-module`, derived from
OH1A's BFME2 Accelerator. The upstream revision and local changes are in `UPSTREAM.txt`;
MIT attribution is retained in `LICENSE` and rpmalloc's source headers.

## Build

From the repository root, using Visual Studio 2022 with the x86 C++ workload:

```powershell
.\native\accelerator\build.ps1
.\native\accelerator\build.ps1 -Report
.\native\accelerator\build.ps1 -CrtPath 'C:\path\to\RotWK\msvcr71.dll'
```

Outputs stay under `build/pysage-accel-prod` or `build/pysage-accel-report`. The script
builds `pysage_accel.dll`, runs the native compatibility regression executable, and builds
`crt_test.exe` and `rt_harness.exe`. `-CrtPath` also runs the CRT differential tests.
No game files are copied, installed or modified by this script.

## Use

Build a fresh game binary with the current `accel-module` recipe alongside your other
patches, then put `pysage_accel.dll` beside that binary. See `sage_patch/docs/accel-module.md`.
An older `accel-module` cave still loads `bfme2_accel.dll`; replacing its DLL alone does
not migrate it. Rebuild from a clean binary with the full patch selection.

Do not load this companion and upstream BFME2 Accelerator into the same process.
The companion is initialized by the game's cave through `SageAccelInitialize`, outside
DllMain, on the game thread. An upstream injector is not its entry point.

## Enabled profile

- rpmalloc for the game's supported CRT allocation imports.
- Faster CRT memory/string/math imports, retaining upstream validation.
- D3DX preshader cache when its expected library code matches.

Fixed-address engine hooks are disabled, including audio indexing, the logic slicer,
pose workers, render-list sorting, equivalence/filter memoization and engine perf hooks.
They are not silently enabled on an unknown hash or by `ANY_BINARY_OK`.
Effect-value deduplication is also disabled because the full write surface is not tracked.

**Parallel rendering is off by default.** The native Windows D3D9 test exposed complete
device-table replacement outside Reset, a deadlock, and a crash in a subsequent repair
experiment. The unsuccessful repair experiment is not in the delivered code. Reset
repair has fake-device regression coverage, but does not establish whole-renderer safety.
`PYSAGE_EXPERIMENTAL_RT=1` is for developer investigation only; it is not a recommended
performance setting. `AOTR_RT=0` still disables the renderer even when opted in.

The renderer harness opts into that experimental path explicitly:

```powershell
.\rt_harness.exe off 120 off120.txt
.\rt_harness.exe on 120 on120.txt
```

Run from the build directory with matching 32-bit D3D9/D3DX libraries available. Use a
process timeout for `on`; it currently hangs on the tested Windows native D3D9/shim stack.
Compare all frame hashes and the reported query/mirror/lock mismatches, not just exit codes
or timings. These synthetic timings are not game FPS measurements.

## Validation on 2026-10-08

- Production and native regression build succeeds with VS 2022 Community x86.
- Native tests cover the default-off gate, explicit thread identity, successful/failed
  Reset while active/inactive, partial vtable repair, invalid-table rejection, sent-window-
  message handling during execution-lock contention and cache epoch wrap.
- Upstream CRT differential tests pass against the user's RotWK `msvcr71.dll`.
- Python loader tests: 25 passed, including missing/incompatible DLLs, initialization
  failure, register/flag preservation and composition with both pySAGE profiling patches.
- Both supplied game binaries accepted and verified the loader plus profiling patches in
  workspace copies. A subsequently rebuilt installed game already contained this loader.
- Direct game startup exited with code 666 before reaching the cave. Launching through
  the installed launcher requires Windows elevation (error 740). Subsequent elevated
  startup and a 60-second in-game observation passed;
  save/replay and multiplayer validation remain outstanding.

The tests do not establish a numerical game-performance improvement. The DLL remains
experimental, and advanced engine hooks require per-feature address/layout and conflict
validation before being enabled.

Upstream `AOTR_PROFILE`, `AOTR_DIAG`, `AOTR_CAPTURE` and their marker files
do not enable engine instrumentation in this companion. This also closes the profiling
path that otherwise bypassed the engine-hook gate.

### Live validation and build review (2026-10-08)

A subsequent normal mod-launcher start with the companion installed reached loader state 2.
The runtime log confirmed rpmalloc, all 16 matched CRT import slots, and the preshader cache;
the parallel renderer stayed off. Seven read-only samples over 60 seconds of a running
unit/effect-heavy scene recorded 8,607,419 cache hits and 3,171,693 misses (73.07% of cacheable
calls), zero detected verification mismatches, 22,871 allocations and 22,836 frees.
No crash or hang was observed. These are activity/correctness observations, not FPS gains
or proof of multiplayer determinism. Preshader verification is sampled, not exhaustive.

The build now treats compiler warnings as errors (`/WX`). The harness explicitly converts
its double-precision expressions to float at the original conversion boundaries and checks
output-file opening with `fopen_s`. Native tests additionally cover allocator zero-fill,
growth preservation, overflow and `realloc(p, 0)` freeing the allocation and returning NULL.
`AOTR_NOPRESHADER` cannot bypass shader evaluation in the companion.

The renderer-off harness still produces the same 120 frame hashes after warning cleanup,
with zero query, lock or render-target mirror mismatches. Both production and report builds
pass with warnings treated as errors. The CRT differential test passes against msvcr71.
