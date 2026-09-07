# Paging past 33 with `PUSH_VISIBLE_COMMAND_RANGE` (and the off-the-end crash)

Once the [button-limit patch](commandset-button-limit.md) lets a `CommandSet` **define** up to N
buttons (N = 64 in the shipped build), the ControlBar still **draws only 33 at a time**. The
vanilla mechanism to show a different window of the set is a command button whose
`Command = PUSH_VISIBLE_COMMAND_RANGE`, with `CommandRangeStart` / `CommandRangeCount` selecting
`m_command[start .. start+count)`.

Overshooting that window is a **stock engine crash**, and one the raised limit inherits.
`CommandSetLimitPatch`'s Phase 3 clamps it; §4 is what changes.

## The rule

```
CommandRangeStart + CommandRangeCount ≤ N          (N = the patched limit, e.g. 64)
CommandRangeCount ≤ 33                             (the widget array, not just the screen)
```

Also keep `CommandRangeCount ≤` the number of real buttons past `start`, so the page does not draw
trailing empty slots. Empty slots *inside* the array are `NULL` and harmlessly skipped.

The same two ceilings bind `InitialVisible`, which is not a hint: §2.

## 1. Where the window is read, and the three loops over it

`ControlBar::populate` (`0x00943D6F`, the single-object path) reads the top `{start, count}`
record of the paging stack **once**:

```asm
00943e11  lea  eax, [ebp-0x48]        ; &range
00943e14  push eax
00943e15  mov  ecx, ebx               ; the ControlBar
00943e17  call 0x0071cf0a             ; getVisibleRange(&range)  -> [ebp-0x48]=start, [ebp-0x44]=count
```

`0x0071CF0A` copies the last 8-byte record of the vector at `ControlBar+0x2B0`, or default-builds
one when the stack is empty. It is the **only** consumer of that stack — the two handlers at
`0x00941A7D` / `0x00941A9C` push and pop it, nothing else reads it.

The function then walks the window **three** times, and each pass steps a pointer through the
ControlBar's **33-entry** button-widget array at `+0xDC` alongside the slot index:

| pass | head | bound | what it does |
|---|---|---|---|
| capped | `0x00943E29` | `cmp edi, 0x21` **and** `edi < count` | the ordinary slot fill |
| revive | `0x00943F2B` | `i < count` **only** | the revive-slot pass (`GUICOMMAND_REVIVE`, `0x2E`) |
| production | `0x0094426A` | `i < min(other, count)` **only** | the production/queue pass |

Every pass indexes `getCommandButton(start + i)`, an unchecked `[this + i*4 + 0x14]`.

**Only the first pass carries the 33.** That is the whole bug: the two later passes run `count`
iterations whatever `count` is, so an oversized window runs *two* arrays off their ends at once.

## 2. Why the two ceilings are what they are

**`start + count > N` overruns `m_command[]`.** The array holds indices `0 .. N-1`; the object's
count and flag fields sit **immediately after it**, at indices N and N+1:

| array index | what it holds |
|-------------|---------------|
| `start … last real` | real page buttons |
| … up to `N-1`       | empty slots — `NULL`, safely skipped |
| **N**               | **the count field** (holds `InitialVisible`, e.g. `33`) |
| N+1                 | the flag field |

`getCommandButton(N)` returns the count *value*, the loop uses it as a `CommandButton*`, and the
draw path dereferences `[value + 0xf0]` → access violation. Concrete fault signature from a
`start=33, count=33` overrun (66 > 64): `EIP=0x0075d244`, `ACCESS_VIOLATION read 0x111`,
`esi=ecx=0x21` (33).

**`count > 33` overruns the widget array.** `ControlBar+0xDC` holds 33 `GameWindow*`. Past entry
33 the revive and production passes read ordinary ControlBar fields (the object runs out to
`+0x2B0`) as window pointers, and a non-null one is called. So `CommandRangeCount` above 33 is
fatal on its own, even when `start + count` stays inside `m_command[]`.

**`InitialVisible` is the same window.** With the paging stack empty, `0x00943DF6` seeds it with
`{0, InitialVisible}` straight out of the `CommandSet`'s count field:

```asm
00943df6  mov  eax, [ebp-0x18]        ; the CommandSet
00943df9  push dword [eax+0x98]       ; InitialVisible   (relocated to the array end by Phase 1)
00943dff  lea  ecx, [ebp-0x40]
00943e02  push 0                      ; start = 0
00943e04  call 0x007f8c91             ; Range(&r, 0, InitialVisible)
```

So `InitialVisible` above 33 is not "buttons that cannot be drawn". It is the widget overrun
above, on the very first populate, with no click needed.

## 3. Worked example (unclamped)

A set defining 49 buttons (INI `1..49` → array indices `0..48`) whose page-2 button reads:

```ini
CommandButton Command_SelectRevivablesPage2
    Command           = PUSH_VISIBLE_COMMAND_RANGE
    CommandRangeStart = 33
    CommandRangeCount = 33      ; <-- BUG: 33 + 33 = 66 > 64
    ...
```

reads `m_command[33 .. 65]` and crashes on index 64. Set `CommandRangeCount` to the actual number
of page-2 buttons — here `49 − 33 = 16`:

```ini
    CommandRangeStart = 33
    CommandRangeCount = 16      ; array indices 33..48, all valid
```

If a per-map variant of the same button targets the set, apply the identical ceiling there.

## 4. The clamp (`CommandSetLimitPatch` Phase 3)

The fix is one hook, at the fetch rather than at the loops: the three passes read the record
after it has been trimmed, so all three become safe from a single edit. The two later loop heads
have no spare bytes anyway.

The eleven bytes at `0x00943E11` — three whole instructions plus the `call`, with `0x00943DF4`
jumping to the first byte and nothing branching into the other ten — become a `jmp` into the
`.cmdext` cave, `nop`-padded to length. The routine there performs the displaced fetch verbatim
and then trims:

```asm
  lea  eax, [ebp-0x48]        ; the displaced fetch
  push eax
  mov  ecx, ebx
  call 0x0071cf0a
  mov  eax, [ebp-0x48]        ; start
  mov  ecx, [ebp-0x44]        ; count
  cmp  eax, N
  jae  empty                  ; start outside 0..N-1 (unsigned, so negatives land here too)
  cmp  ecx, 33
  jle  fits_screen
  mov  ecx, 33                ; cap at the widget array
fits_screen:
  mov  edx, N
  sub  edx, eax               ; slots left after start
  cmp  ecx, edx
  jle  fits_array
  mov  ecx, edx               ; cap at the command array
fits_array:
  test ecx, ecx
  jg   store
empty:
  xor  ecx, ecx
store:
  mov  [ebp-0x44], ecx
  jmp  0x00943e1c
```

`start` itself is left alone: with a zero count no loop reads it. Only `eax`, `ecx`, `edx` and
the flags are touched, all of which the stock `call` already clobbered, and `ebx` — the ControlBar
the caller keeps using — is only read.

**What changes for a mod.** Nothing that was correct. A window inside both ceilings is untouched
byte for byte. A window outside them draws the buttons it has instead of crashing, so
`InitialVisible = 64` shows 33 and an overlong page shows its real entries and blanks. The
diagnostics in `sage_lint` follow: `command-range-overflow` and `initial-visible-over-max` are
ERROR on an unclamped engine and WARNING once a `.sagepatch` declares `commandset.range_clamped`.

The clamp does **not** raise the on-screen count. 33 is still the most the bar draws, and paging
is still how the rest is reached.

## 5. Indexing note

INI slot numbers are 1-based; the `m_command` array is 0-based (`parseCommandButton` writes slot
`"K"` to `m_command[K-1]`). `CommandRangeStart` is an **array index**, so `start=33` begins at INI
button `34`.

## Key addresses (v2.01.2614.37001, ImageBase 0x00400000)

| what | address |
|------|---------|
| `ControlBar::populate` (single object) | `0x00943D6F` |
| `InitialVisible` → initial window | `0x00943DF6` |
| visible-range fetch (the clamped span) | `0x00943E11` … `0x00943E1B` |
| resume point | `0x00943E1C` |
| `getVisibleRange` | `0x0071CF0A` |
| capped loop head | `0x00943E29` |
| revive loop head (uncapped) | `0x00943F2B` |
| production loop head (uncapped) | `0x0094426A` |
| widget array / range stack | `ControlBar+0xDC` / `ControlBar+0x2B0` |
| `PUSH` / `POP` handlers | `0x00941A7D` / `0x00941A9C` |
| `CommandRangeStart` / `CommandRangeCount` | `CommandButton+0x22C` / `+0x230` |
