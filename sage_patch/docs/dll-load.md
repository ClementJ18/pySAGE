# Loading optional DLLs from game.dat's entry point

Engine build `2.01.2614.37001`. Registered (once added to the registry) as the experimental
`dll-load` patch, `sage_patch/patches/platform/dll_load.py`.

- **Status: built and checked on Windows 11 with Edain's `game.dat` on 2026-11-02.** With
  `game-patcher.dll` and `EasyHook32.dll` beside it the dll loads and logs its patches, the same
  result as `dll-import`; with neither file there the game starts and reaches the menu as stock.
- **What it is for:** the same job as `dll-import` - carrying an in-memory patcher such as
  bfme2-patcher's `game-patcher.dll` in the file instead of injecting it - without the cost that
  the game refuses to start when the dll is missing.
- **Cost:** one small section (`.dllload`) and the entry point in the optional header. No code in
  `game.dat` is overwritten.

## 1. How

`AddressOfEntryPoint` is moved to a stub in `.dllload`:

```
pushfd
pushad
push "game-patcher.dll"      ; one push/call pair per DLL, in the order given
call [LoadLibraryA]          ; IAT slot 0x00BD0188, the one accel-module also calls through
popad
popfd
jmp <original entry point>   ; 0x00A3D082 in the stock build
```

The return value is ignored. `LoadLibraryA` returns 0, without a dialog, for a dll that is not
there or whose own imports are not; only a missing *static* import of the executable stops the
process with a system error, which is the failure `dll-import` has and this patch avoids.

## 2. Why the entry point is early enough

By the time the loader jumps to the entry point it has resolved every import of `game.dat`, filled
its IAT and run every imported dll's `DllMain`. No game code, not even the CRT startup, has run. A
dll loaded there therefore sees what a dll loaded from the import table sees: a filled IAT (which
`game-patcher.dll`'s `sse_rounding` rewrites) and code that has not yet executed. Its `DllMain`
runs on the main thread, under the loader lock, as it would from an injector's `LoadLibraryA`.

## 3. The block

| offset | what |
|---|---|
| `+0x00` | magic `'DLLD'` (`0x444C4C44`) |
| `+0x04` | the original entry point's VA |
| `+0x08` | the number of DLL names |
| `+0x10` | the names, NUL-terminated, back to back |
| 16-aligned after them | the stub |

`detect` reads the names back from the block; `verify` rebuilds the section from them and the
recorded entry point and compares, and checks that the entry point is the stub. Applying twice is
refused.
