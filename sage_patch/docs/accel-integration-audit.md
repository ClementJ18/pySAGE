# Accelerator integration audit — 2026-10-08

This records the initial upstream audit. The subsequent companion implementation and its
current limitations are documented in [accel-module](accel-module.md). In particular, the
native Windows D3D9 render harness did not pass; the companion's renderer is default-off.

## Result

The local accelerator can be compiled alongside pySAGE and loaded through the existing
experimental `accel-module` patch. **This is not yet a validated runtime combination.**
The local source still has the unknown-build thread-selection and device-reset problems
described in [accel-module](accel-module.md). A successful DLL build or loader test does
not establish rendering correctness, multiplayer compatibility, or an FPS improvement.

Sources inspected:

- `F:\Modding\bfme2-accelerator`, main `5b7f1edfebccc9a37184cf5b6103249bdb86f0a3`.
- `F:\Modding\OpenBfme2`, HEAD `bf6907fa9dd8e5eb7879bb497c7e45119ed6c565`.
- This repository's loader, render profiling patches, addresses and loader tests.

The accelerator checkout was read only. Compilation products and temporary test wrappers
are in `build/accelerator-audit/`; no game installation was changed. The audit DLL is an
unmodified production build for build verification, **not a compatibility-fixed release**.

## Tests actually run

Windows, Visual Studio 2022 Community, x86 MSVC, `/O2 /MT`:

| Check | Observed result | What it establishes |
| --- | --- | --- |
| rpmalloc + full accelerator, `/DAOTR_PROD /LD` | Compile/link exit 0 | Native toolchain and local source build successfully |
| `audiolimit_test 0` | 3,000 passes; 820,375 comparisons; 0 differences; proof 0 mismatches | Indexed audio answers agree with the test's list walk |
| `audiolimit_test 0 1 123` | 3,000 passes; 824,561 comparisons; 0 differences; proof 0 mismatches | Same property with highly concentrated event identities and another seed |
| `logicslicer_test`, seed 777 | 2,400 steps; 1,953,318 module updates; 0 differing steps; self-check 0/1,887,123 bad | The supplied model preserves its tested scheduling properties |
| Loader tests excluding `TestTheHookRuns` | 17 passed, 5 deselected | Registration, binary editing, verification and composition with both profiling patches |
| Complete loader suite | 22 passed, exit 0, but Windows access-violation diagnostics from Unicorn `mem_map` | Not accepted as a clean emulator validation on this host |

The slicer test does **not** compile unchanged: `aotr_logicspread.inc` calls `aotrPath`,
but its test translation unit does not define that helper. A temporary wrapper supplied
only the missing path helper, then included the original test unchanged:

```cpp
#include <windows.h>
#include <string.h>
static char* aotrPath(char* out, const char* name) {
    strcpy_s(out, MAX_PATH, name);
    return out;
}
#include "F:/Modding/bfme2-accelerator/src/logicslicer_test.cpp"
```

This helper resolves marker filenames relative to the test working directory; it is not
a modification to the slicer algorithm. The test includes irregular call patterns for
which it checks uniqueness/loss rather than a stock-equivalent operation sequence.

The first pytest attempt also failed to create its default sandbox temporary directory.
Using `--basetemp=build/accelerator-audit/pytest` resolved that filesystem issue, but not
the Unicorn diagnostics. The clean static run was:

```powershell
.venv\Scripts\python.exe -m pytest tests/sage_patch/test_accel_module.py --basetemp=build/accelerator-audit/pytest-static -q -k 'not TestTheHookRuns'
```

No in-game A/B run, D3D frame-hash comparison, save/reload, replay or multiplayer test was
performed. Model tests are correctness evidence for those models, not performance measurements.

## Compatibility findings from the source

1. **Build recognition still hashes all of `.text`.** `aotr_accel.cpp::initThread` uses
   the hash to set `g_engineHooks`. Applying even the loader changes this hash. The unknown
   family path retains generic rendering/heap/CRT work but disables the engine-specific
   optimizations. The README's broad signature-based description does not replace this gate.
2. **Unknown builds guess the producer thread.** `aotr_rt.inc::rtAdoptGameThread` adopts
   a thread after 64 effect calls. It does not query the device focus window's owner.
   Loading screens render too; activity alone is not proof of the game thread's identity.
3. **Reset does not restore hooks.** `rt_dev_16` invalidates caches and calls the original
   Reset, but does not reinstall device vtable hooks afterwards. This leaves the documented
   compatibility-shim case unresolved in this checkout.
4. **Device Release still drains the queue.** `aotr_rt_gen.inc::rt_dev_2` calls `rtDrain`
   for every active main-thread release. Avoiding unnecessary drains is an implementation
   opportunity, but requires correct lifetime accounting, not removal of the wait alone.
5. **Profiling hooks can collide.** `PerfStageReadoutPatch` patches `0x00517690`;
   `installStageTimersAndEventSkips` also attempts to patch that constructor. Its original-byte
   check declines the event-skip group if the constructor differs. `perf-scope-skip` instead
   uses `0x00517699` and `0x00525202`; separate addresses do not prove compatible control flow.
   Loader composition tests cover pySAGE patches, not these later runtime DLL writes.
6. **The loader is asynchronous.** `DllMain` starts `initThread` and returns. The cave's
   loaded state means LoadLibrary succeeded, not that hook installation completed. The
   selected resolve site alone cannot guarantee installation before first device use.
7. **Do not force the global gate.** Enabling all fixed-address hooks on every patched
   executable would bypass the protection against changed dispatcher code and layouts.
   `ANY_BINARY_OK` is not a compatibility solution (and the family branch precedes it).

## What OpenBfme2 contributes

`Code/GameEngine/Source/Common/Thing/ThingTemplateIsEquivalentTo.cpp` reconstructs the
final-override identity, case-insensitive EquivalentTo comparisons and BuildVariations
checks. This supports memoization as a useful candidate. It also shows why an integer
type-ID shortcut must preserve both lists and override semantics. BFME2's offsets and
addresses must still be verified separately against the target RotWK binary.

`Code/GameEngine/Source/Common/Rva00040F1EMutex.cpp` reconstructs a constructor accepting
name, initial ownership and security attributes for CreateMutexA. Therefore a critical
section is only a candidate for verified process-local, compatible uses; named/shared
mutexes and wait semantics cannot be replaced indiscriminately.

`Code/GameEngine/Source/GameClient/GUI/LoadScreenUpdates.cpp` documents and implements
loading-screen pumps that update/draw the display. `Source/Main/WinMain.cpp` contains
window creation. These support investigating explicit window/game-thread identity; they
do not independently prove the corresponding RotWK thread ownership or addresses.

## Integration path and additional performance work

Keep the native accelerator as a companion DLL and reuse `accel-module`. Translating its
command queue and worker pool into Python or a small static cave is not a practical route.
Preserve upstream MIT attribution if native sources are vendored; no vendoring was done here.

Order the next implementation by prerequisites:

1. Establish the game thread explicitly and decline parallel rendering if identity cannot
   be established; restore hooks safely around Reset; make initialization readiness observable.
2. Replace the single whole-code gate with per-feature validation of *all* dependent hook
   sites, callees and layouts. Keep unsupported features off and report why. Resolve ownership
   of profiling sites rather than overwriting a pySAGE hook.
3. Validate a fixed DLL with the D3D off/on frame-hash harness on the same GPU/driver, then
   loading screens, alt-tab/device reset, match restart, replay and multiplayer checks.
4. Measure render-worker busy time, main-thread waits and frame-time percentiles on the
   same save/replay and camera. Separately measure simulation throughput. Compare production
   builds; instrumentation itself adds overhead.
5. First investigate avoidable device-Release waits and the currently gated minimap/shroud
   batching. These can recover parallelism before adding more worker threads. Then evaluate
   audio indexing, template/filter memoization, sort reference-count traffic and pose workers
   individually. The ordering is a source-based hypothesis until measured in the target game.

For memoization, explicit template-generation invalidation would be more robust than
detecting a new game only when the frame counter decreases: pointer reuse and reloads
must not retain an old answer. For pose workers, test cancellation/lifetime during model
destruction and loading before increasing concurrency. The logic slicer primarily targets
frame pacing; its model result does not imply higher simulation throughput or multiplayer
determinism in the real engine.

**No numerical FPS gain is claimed.** The concrete outcome is a successful native build,
passing audio/scheduling models, a clean static loader test, and identified compatibility
work that must precede enabling this source revision on a sage-patched game.
