# Starting without the Windows XP compatibility mode

The reverse-engineering behind
[`patches/os_name_fallback.py`](../patches/os_name_fallback.py). ROTWK `game.dat` build
`2.01.2614.37001`, ImageBase `0x400000`, found 2026-10-15 from the crash dump of an Edain launch on
Windows 11 with the compatibility mode turned off.

## TL;DR

- Edain installs set `game.dat` (and the launcher) to the **Windows XP SP3 compatibility mode**.
  Turned off, `game.dat` crashes in `msvcr71.dll` before the first frame.
- The cause is the **startup hardware report**. It names the Windows version through a builder
  (`0x00A25630`) that knows NT major versions 4 and 5. For any other major it **returns without
  writing the name pointer**, and the report prints the uninitialised pointer with `%s`.
- The compatibility mode avoids it only by reporting version 5.1. It also loads the `AcLayers`
  shims, and one of them wraps the Direct3D device in `apphelp.dll`, which keeps rewriting the
  device's vtable (§4).
- The fix is six bytes at **`0x00A256A6`**: the `jne` for "major is not 5" goes to the major-5
  arm's last case, which writes "WINXX" and returns through the same epilogue.

## 1. The crash

Launched from the toolbar with neither `game.dat` nor `lotrbfme2ep1.exe` in compatibility mode, the
game's own crash dump (`DUMP__20261015-114235__*.dmp`) holds an access violation at
`msvcr71.dll+0xFEDC`:

```
eip 7c34fedc msvcr71+0xfedc   ecx 7ffffffe   edi 00be8266
```

`ecx = 0x7FFFFFFE` is the count the C runtime's string formatter runs with for an unbounded
`sprintf`, and `edi` is the format position: `0x00BE8266` is just past the `%s` of `"%s\t"` at
`0x00BE8264`. The `%s` argument was not a string.

## 2. The report

The format is pushed three times. The two at `0x00A26C77` and `0x00A26CD6` are in the hardware
report that writes the GPU and OS lines (`"Chip Vendor: %s"`, `"Product=%d, Version=%d, ..."` are
its neighbours at `0x00BE8250`):

```asm
00a26c50  mov  edx, [0x00DEE780]       ; platform id
00a26c56  mov  eax, [0x00DEE850]
00a26c5c  mov  ecx, [0x00DEE848]
          push ...                     ; (platform, major, minor, build) of GetVersionEx
00a26c65  lea  ecx, [esp+0x18]         ; a five-dword record on the stack, not initialised
00a26c69  call 0x00A25630              ; name the Windows version into it
00a26c6e  mov  edx, [esp+0x18]         ; its first dword: the name
00a26c72  push edx
00a26c77  push 0x00BE8264              ; "%s\t"
00a26c7d  call 0x00A24AD0              ; the report's vsnprintf into a 512-byte buffer
```

The third push (`0x0052B904`) prints a GPU vendor from a bounded table and is not involved.

## 3. The builder

`0x00A25630`, `__thiscall` on the record. Platform 1 (Windows 9x) and other platforms have arms of
their own; platform 2 (NT) is:

```asm
00a2568c  cmp  edi, 4                  ; edi = major
00a2568f  mov  [ecx+4], "UNKNOWN"
00a25696  jne  0x00A256A3
          mov  [ecx], "WINNT"  / ret
00a256a3  cmp  edi, 5
00a256a6  jne  0x00A257B1              ; <- any other major
00a256ac  test esi, esi                ; esi = minor
          ... minor 0 -> "WIN2K", minor 1 -> "WINXP"
00a256cb  pop  edi                     ; minor 2 and up
00a256cc  pop  esi
00a256cd  mov  dword [ecx], "WINXX"
00a256d3  pop  ebx
00a256d4  pop  ecx
00a256d5  ret

00a257b1  pop  edi                     ; the target of the unknown major
00a257b2  pop  esi
00a257b3  pop  ebx
00a257b4  pop  ecx
00a257b5  ret                          ; [ecx] never written
```

Windows 10 and 11 report major 10 to a process with no compatibility mode, so the report reads
whatever the stack held. The bare return and the "WINXX" case pop the same four registers in the
same order, so redirecting the branch changes nothing but the name:

```
00a256a6  0f 85 05 01 00 00   jne 0x00A257B1   ->   0f 85 1f 00 00 00   jne 0x00A256CB
```

"WINXX" is the name the engine already gives an NT version it does not list, so nothing downstream
sees a value it would not on Windows Server 2003. The record's `[ecx+8]` is left as stock leaves it
on the NT path.

## 4. Why it matters beyond the crash

With `~ WINXPSP3` set (in `HKCU\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers`),
the process loads `AcLayers.dll`, and the Direct3D 9 device's vtable is a heap copy owned by
`apphelp.dll`, with its own `QueryInterface`, `Release` and `Reset`. The shim swaps d3d9's original
table back in around its own calls. That defeated the BFME2 Accelerator's device hooks
([`accel-module.md`](accel-module.md) §4.3). Without the mode the device is plain `d3d9.dll`'s.

The launcher matters too: a launcher in compatibility mode passes the layer to `game.dat` through
`__COMPAT_LAYER`, so both have to be off for `game.dat` to run without it.

## 5. Testing it

Verified 2026-10-15 on Windows 11 with the Edain toolbar build: with this patch and no
compatibility mode on either file, `game.dat` starts, and the log of a DLL loaded at
`Direct3DCreate9` shows the device vtable in `D3D9.DLL` with no `AcLayers.dll` in the process.

Not verified: a whole match without the compatibility mode and without the accelerator loaded. The
XP mode carries other shims (heap, version lies) that a later code path might still rely on.

1. Apply `os-name-fallback` and install the `game.dat`.
2. Turn the compatibility mode off on `game.dat` and on the launcher.
3. Start a skirmish and play it out, then a save and load.
