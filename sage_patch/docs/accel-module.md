# Accelerator companion loaded by `game.dat`

`accel-module` loads the experimental pySAGE companion derived from OH1A's MIT-licensed
BFME2 Accelerator. Its source and reproducible Windows build live in `native/accelerator`.
The companion filename is **`pysage_accel.dll`**. An upstream `bfme2_accel.dll` is not a
substitute: the loader requires the explicit `SageAccelInitialize` entry point.

## Current scope

The default profile installs the supported heap/CRT optimizations and D3DX preshader cache.
It leaves fixed-address engine hooks off, so it cannot overwrite the engine hooks owned by
other sage-patch recipes. No whole-`.text` hash bypass or `ANY_BINARY_OK` force mode is used.

**The parallel renderer is disabled by default.** The Windows native D3D9 harness exposed
vtable replacement outside Reset and an ensuing deadlock. Repairing only Reset does not
solve that problem. `PYSAGE_EXPERIMENTAL_RT=1` enables the still-unvalidated renderer for
developer investigation; do not treat it as a working game-performance option.
Effect-value deduplication is also disabled until all mutating setters are covered.

This is an integration of the compatible subset, not a claim that every upstream
optimization is compatible or that an FPS increase has been measured. Audio indexing,
logic spreading, pose workers, render-list sorting and template/filter memoization remain
blocked behind their engine-specific validation work.

## Building and applying

```powershell
.\native\accelerator\build.ps1
sage-patch apply accel-module --in game_original.dat --out patched.dat
sage-patch verify accel-module patched.dat
```

Build output: `build/pysage-accel-prod/pysage_accel.dll`. `-Report` selects a separate
reporting build, and `-CrtPath` runs differential tests against a specified `msvcr71.dll`.
The native build does not modify a game installation. Deploy the DLL beside the game
binary built with your complete patch selection. The DLL writes `pysage_accel.log`
beside itself. Do not simultaneously inject the upstream accelerator.

For an existing old-format `accel-module` binary, rebuild from its clean source with the
same patch selection. The old cave loads a different DLL name and has no initialization
handshake; `apply` deliberately refuses to overwrite an existing hook in place.

## Loader contract

The store of the resolved `Direct3DCreate9` at `0x00525199` jumps to a `.accel` cave. The
cave replays that store, preserves registers and flags, and calls
`LoadLibraryA("pysage_accel.dll")`. It then resolves and calls `SageAccelInitialize()`.
Only a return value of exactly 1 counts as successful initialization. The DLL's DllMain
initializes its own bookkeeping but does not start an installer thread. Installation
therefore happens outside the Windows loader lock, on the engine thread, before the
engine resumes toward device creation. There is no effect-call-count thread guess.

Missing DLLs, missing exports and initialization failures are recorded separately:

| Offset | Meaning |
| --- | --- |
| `+0x00` | Magic `SACL` |
| `+0x04` | State: 0 not reached; 1 DLL unavailable; 2 initialized; 3 export missing; 4 initialization failed |
| `+0x08` | Loaded module handle, or zero |
| `+0x10` | NUL-terminated companion DLL name |
| `+0x30` | NUL-terminated initializer export name |
| `+0x50` | Cave code |

State 2 means initialization returned successfully, not that the parallel renderer is
active or that every optional optimization installed. Consult the DLL log for feature
results. `sage-patch verify` verifies the game binary's cave and hook; it does not inspect
an external DLL or certify runtime correctness.

The anchor includes the resolve, the preceding comparison, the displaced store and the
following conditional jump. The flags from that comparison are restored, including when
resolving Direct3DCreate9 failed. The IAT entries used are LoadLibraryA at `0x00BD0188` and
GetProcAddress at `0x00BD018C`.

## Compatibility work included

- Explicit, synchronous initialization on the engine's resolve thread.
- Separate DLL name and export contract so an ordinary upstream DLL is not selected.
- Fixed-address engine hooks disabled regardless of whether the build hash is recognized;
  this avoids conflicts with `perf-stage-readout` at `0x00517690` and other engine patches.
- Device slots repaired after successful and failed Reset, including the renderer-off
  path. Slots still pointing to our hooks keep their original targets, avoiding recursion.
- Required render-queue allocations and worker readiness checked before activation.
- Effect-cache epoch wrap clears the whole allocation rather than pointer-sized storage.
- Main-thread execution-lock waits can service sent Windows messages.

The latter renderer changes have native regression coverage but remain behind the
experimental renderer gate. Neither an off/on frame-hash pass nor stable in-game threaded
rendering has been established on this machine.

## Validation and remaining work

The 25 loader tests execute the cave with mocked Windows APIs, including export lookup,
initialization failure, register/flag preservation and composition with `perf-scope-skip`
and `perf-stage-readout`. On Windows, pytest's faulthandler printed access-violation traces
while Unicorn handled its own exceptions; running with `-p no:faulthandler` completed all
25 tests with exit 0. This does not replace native or in-game validation.

Both user-supplied `game.dat` images accepted and verified the loader/profiling combination
on workspace copies. Direct startup tests exited with code 666 before reaching the loader;
the normal launcher required Windows elevation (error 740). Temporary companion copies
were removed. No installed game binary was modified by these tests.

The upstream source/build audit, measured audio/slicer model results and OpenBfme2 reference
analysis are retained separately in the repository. Remaining runtime work
includes matched replay benchmarks, extended stability and multiplayer checks. The render
thread requires a correct strategy for native D3D9/compatibility-shim table replacement
before it can be enabled by default. Performance claims require matched save/replay runs.

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
