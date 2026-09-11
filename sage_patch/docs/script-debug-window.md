# The script debug window's quadratic log — the `script-debug-window` patch

Two binaries. Engine build `2.01.2614.37001` (ImageBase `0x400000`) for §1–§2, and
`DebugWindowLite.dll` (172,032 bytes, ImageBase `0x10000000`, 5 sections, MFC 7.1) for everything
after that. Addresses are VAs in whichever binary the section names.

**Verdict:** the stutter is not in `game.dat`. Every line the script engine logs makes the DLL
rebuild the entire window text from the first message of the session onwards and hand the whole
buffer to `SetWindowTextA`, on the game's own thread. Cost per line is proportional to the number
of lines already logged, so a session's total is quadratic. One redirected `call` in the DLL turns
the rebuild into an append. Read statically off the shipped binaries and confirmed in a running
game.

## 1. Getting to the window — the two command-line flags

The command-line table at `0x00C35DD8` holds two rows that reach it:

```
[ 4] 00c35dd8: 0x00c35ea0  ; "-scriptDebug2"      handler 0x007ba1d4
[ 6] 00c35de0: 0x00c35e8c  ; "-scriptDebugLite"   handler 0x007ba1fb
```

`TheWritableGlobalData` is `[0x00DE4364]`. Both handlers set the same three things, and the Lite
one sets a fourth:

```
007ba1d4  c680c109000001   mov byte [eax+0x9c1], 1   ; a debug window is wanted
007ba1e9  c680c609000001   mov byte [eax+0x9c6], 1
007ba1f0  c605ba87de0001   mov byte [0x00de87ba], 1  ; use the Lite DLL
                                                     ; -scriptDebugLite additionally:
007ba21e  c605b887de0001   mov byte [0x00de87b8], 1  ; suppress messages and variables
```

So **both flags load `DebugWindowLite.dll`**, which is the only one of the two that ships. The
selection is at `0x006056D0`:

```
006056d0  3898c1090000     cmp byte [eax+0x9c1], bl  ; not wanted -> load nothing
006056d6  7421             je  0x006056f9
006056d8  381dba87de00     cmp byte [0x00de87ba], bl
006056de  7412             je  0x006056f2            ; -> "DebugWindow.dll"  (unreachable here)
006056e0  68cc9cbf00       push 0xbf9ccc             ; "DebugWindowLite.dll"
006056e5  ff158801bd00     call [0x00bd0188]         ; LoadLibraryA
006056eb  a3983bde00       mov [0x00de3b98], eax     ; the module handle
```

Nothing in these two handlers leaves `0x00DE87BA` clear, so the `DebugWindow.dll` arm is dead on
this build's command line. The handle lands in `[0x00DE3B98]`.

`0x00DE87B8` is the byte that separates the two flags, and it is tested at the head of both
message-producing wrappers — `0x00604D90` (append) and `0x00605027` (adjust-variable) — each of
which jumps straight to its own epilogue when it is set. **`-scriptDebugLite` therefore gives you
the window with no message log and no variables pane**, which is a real workaround for the stutter
and a poor one, because the log is the reason to open the window.

## 2. The engine side of a log line

`0x00604D85` is the engine's append wrapper. It has 87 direct callers across the script engine.
Per call it:

```
00604d90  803db887de0000   cmp byte [0x00de87b8], 0  ; the Lite guard from §1
00604d9d  a1983bde00       mov eax, [0x00de3b98]     ; the module handle
00604da7  68249cbf00       push 0xbf9c24             ; "AppendMessage"
00604dad  ff158c01bd00     call [0x00bd018c]         ; GetProcAddress   <- every single line
00604de6  68209cbf00       push 0xbf9c20             ; "%d " - the frame-number prefix
00604dec  e89f2ce3ff       call 0x00437a90           ; AsciiString::format
00604e12  ffd7             call edi                  ; the export
```

The export address is **resolved by name on every message**, and again at `0x00604FE8` for the
`AppendMessageAndPause` path. That is an export-table lookup per line. It is real overhead and it
is not the problem; it is recorded here so a future reader does not go looking for the cost in the
wrong binary.

## 3. `DebugWindowLite.dll` — the ten exports

```
0x1700 AdjustVariable          0x10d0 CanAppContinue      0x1110 RunAppFast
0x17d0 AdjustVariableAndPause  0x1180 CreateDebugDialog   0x1130 SetFrameNumber
0x1610 AppendMessage           0x10a0 DestroyDebugDialog
0x1680 AppendMessageAndPause   0x10f0 ForceAppContinue
```

Every one of them opens by fetching the dialog singleton through `0x10001070` (from
`[0x100217E0]`) and returning if it is null. `AppendMessage` (`0x10001610`) and
`AppendMessageAndPause` (`0x10001680`) both build a `std::string` on the stack from the `char *`
they were handed and call the same dialog method, `0x100034B0`:

```
1000165e  e84d1e0000       call 0x100034b0     ; from AppendMessage
100016ce  e8dd1d0000       call 0x100034b0     ; from AppendMessageAndPause
```

so one hook covers both.

**The MSVC 7.1 `std::string` layout**, which the patch needs and which the DLL states twice — once
at `0x100026CE` and once at `0x10001663`:

| offset | field |
|---|---|
| `+0x00` | allocator |
| `+0x04` | 16-byte union: the characters inline, or a heap `char *` |
| `+0x14` | size |
| `+0x18` | capacity — `>= 0x10` means the union holds the pointer |

Stride in a vector is `0x1C`.

## 4. The append path — `0x100034B0`

```
100034b0  8b442404         mov eax, [esp+4]        ; const std::string *msg
100034b4  56               push esi
100034b5  8bf1             mov esi, ecx            ; the dialog
100034b7  50               push eax
100034b8  8d8eec000000     lea ecx, [esi+0xec]     ; the message vector
100034be  e89dfdffff       call 0x10003260         ; push_back
100034c3  8bce             mov ecx, esi
100034c5  e8b6f1ffff       call 0x10002680         ; updateDisplay   <- the whole cost
100034ca  5e               pop esi
100034cb  c20400           ret 4
```

The vector's three members sit at `+0xF0` (begin), `+0xF4` (end) and `+0xF8` (capacity).

**Nothing trims it.** A scan of every instruction in `.text` that touches `+0xEC`/`+0xF0`/`+0xF4`
/`+0xF8` yields exactly five sites: the constructor (`0x10003397`), the `push_back` above, the
rebuild in §5, the destructor (`0x10003670`), and a clear at `0x10003440` whose only reference in
the image is the dword at `0x10019574` — an entry in the dialog's MFC message map. So the only
thing in the world that empties the log is a human clicking Clear.

## 5. `updateDisplay` — `0x10002680`, the quadratic

```
10002680  53 56 57 8bf1    push ebx/esi/edi; mov esi, ecx
10002687  8d9e94000000     lea ebx, [esi+0x94]     ; the scratch string, member of the dialog
1000268d  68dc950110       push 0x100195dc         ; ""  - cleared first
10002699  8bbef0000000     mov edi, [esi+0xf0]     ; <- the FIRST message of the session
1000269f  3bbef4000000     cmp edi, [esi+0xf4]
100026a7  6aff 6a00 57     push -1; push 0; push edi
100026ae  e8ddf7ffff       call 0x10001e90         ; scratch += *edi
100026b3  6a02 68d4950110  push 2; push 0x100195d4 ; "\r\n"
100026bc  e8bff8ffff       call 0x10001f80         ; scratch += "\r\n"
100026c7  83c71c           add edi, 0x1c           ; next std::string
100026cc  75d9             jne 0x100026a7          ; ... to the last
```

Then the whole buffer goes to the control in one shot, and the caret is driven to the end:

```
10002705  68ec030000       push 0x3ec              ; the message edit control, id 1004
1000270c  e8e4df0000       call 0x100106f5         ; CWnd::GetDlgItem
10002713  e868e00000       call 0x10010780         ; CWnd::SetWindowText -> [0x100192e8]
10002737  68b1000000       push 0xb1               ; EM_SETSEL
1000273d  ffd7             call edi                ; edi = [0x10019340] = SendMessageA
10002746  68b7000000       push 0xb7               ; EM_SCROLLCARET
1000274c  ffd7             call edi
```

`SetWindowTextA` makes the edit control discard its buffer, re-parse the replacement, re-wrap it
and invalidate — for the entire log, every time one line is added. All of it runs on the caller's
thread, which is the game's, inside the logic frame that produced the message. Message number *N*
costs *O(N)*; a session costs *O(N²)*.

## 6. The pane that does it right

The variables pane is the same shape and does not have the problem, which is the clearest evidence
that the message pane's behaviour is an oversight rather than a design.

`AdjustVariable` sets a dirty byte at dialog `+0xDA` and returns. The rebuild — `0x10002560`, a
loop over a second vector at `+0xE0`/`+0xE4`, stride `0x38`, emitting `name` + `" = "` + `value`
into control `0x3EB` — opens with

```
10002566  8a83da000000     mov al, [ebx+0xda]
1000256c  84c0             test al, al
1000256e  0f84ff000000     je  0x10002673          ; nothing changed: do nothing
```

and is reached once per frame from `SetFrameNumber` (`0x10002920`, which also writes the frame
counter into control `0x3F2`). So the variables pane rebuilds at most once a frame no matter how
many variables move. The message pane has no such flag and no such gate.

## 7. What the patch does

The cave is reached by redirecting the five bytes at `0x100034C5` — the `call updateDisplay` in
§4 — and it never returns to `updateDisplay` at all. Instead of rebuilding, it appends:

```
hEdit = GetDlgItem(this->m_hWnd, 1004)
len   = SendMessageA(hEdit, WM_GETTEXTLENGTH, 0, 0)
        SendMessageA(hEdit, EM_SETSEL,     len, len)
        SendMessageA(hEdit, EM_REPLACESEL, FALSE, msg)
        SendMessageA(hEdit, EM_REPLACESEL, FALSE, "\r\n")
        SendMessageA(hEdit, EM_SCROLLCARET, 0, 0)
```

`m_hWnd` is at `CWnd+0x1C`, which the stock code states at `0x100106FF` (`push [ecx+0x1c]` into
`::GetDlgItem`) and again at `0x10002734`. The two imports are addressed through their IAT slots,
`0x100192F0` for `GetDlgItem` and `0x10019340` for `SendMessageA`, `0x50` apart, so one register
reaches both.

**The `push_back` is left standing.** The vector still records every line, so the Clear button
still works: it empties the vector and calls `updateDisplay`, which now writes an empty buffer over
the control. The consequence is that the log's *memory* still grows without bound. That is a
separate defect from the one being fixed and it is not fixed here.

**Reloc-free by construction.** The DLL has a `.reloc` section, so it can be rebased, and a cave
containing an absolute operand would need relocation entries the patch does not write. It contains
none: the IAT is reached through the classic

```
e800000000       call next
next:
5f               pop edi                 ; edi = the runtime address of `next`
81ef ........    sub edi, next - 0x100192f0
```

which yields `actualBase + 0x192F0` whatever the load address turns out to be. The only other
non-relative reference is the `"\r\n"` argument, and that is built on the stack by `push 0xa0d`
rather than pointed at in `.rdata`.

**Composition** is not really in question — nothing else in this package touches this binary — but
the cave is allocated with `allocate_section` and located by name in `verify`, like every other,
so a second DLL patch would compose with it.

## 8. What is unknown

- **`WM_GETTEXTLENGTH` on a multiline edit** is assumed cheap relative to a full `SetWindowTextA`.
  That is near-certainly true and is not measured. If it turns out to walk the buffer, caching the
  running length in the cave removes it.
- **The `[eax+0x9c6]` byte** the two flag handlers set alongside the others is unidentified. It is
  not read on any path this write-up needed.
- **`DebugWindow.dll`**, the non-Lite build, is not present in any install checked, so its
  `AppendMessage` has not been read. If it ever shows up, do not assume it shares this defect.
