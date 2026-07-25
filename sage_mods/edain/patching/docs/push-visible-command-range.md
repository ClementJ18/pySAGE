# Paging past 33 with `PUSH_VISIBLE_COMMAND_RANGE` (and the off-the-end crash)

Once the [button-limit patch](commandset-button-limit.md) lets a `CommandSet` **define** up to N
buttons (N = 64 in the shipped build), the ControlBar still **draws only 33 at a time**. The
vanilla mechanism to show a different window of the set is a command button whose
`Command = PUSH_VISIBLE_COMMAND_RANGE`, with `CommandRangeStart` / `CommandRangeCount` selecting
`m_command[start .. start+count)`.

## The rule

```
CommandRangeStart + CommandRangeCount ≤ N          (N = the patched limit, e.g. 64)
CommandRangeCount ≤ 33                             (the on-screen ceiling)
```

Also keep `CommandRangeCount ≤` the number of real buttons past `start`, so the page does not draw
trailing empty slots. Empty slots *inside* the array are `NULL` and harmlessly skipped; it is only
running to index **≥ N** that is fatal.

## Why `start + count > N` crashes

The `m_command` array holds indices `0 .. N-1`; the object's count and flag fields sit
**immediately after it**, at indices N and N+1. A range that reaches index N makes the ControlBar
populate loop read the count field as a `CommandButton*`:

| array index | what it holds |
|-------------|---------------|
| `start … last real` | real page buttons |
| … up to `N-1`       | empty slots — `NULL`, safely skipped |
| **N**               | **the count field** (holds `InitialVisible`, e.g. `33`) |
| N+1                 | the flag field |

`getCommandButton(N)` returns the count value, the loop uses it as a `CommandButton*`, and the
draw path dereferences `[value + 0xf0]` → access violation. Concrete fault signature from a
`start=33, count=33` overrun (66 > 64): `EIP=0x0075d244`, `ACCESS_VIOLATION read 0x111`,
`esi=ecx=0x21` (33), loop bounded by `cmp edi,0x21` in the ControlBar populate function at
`~0x543e29`.

## Worked example

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

## Indexing note

INI slot numbers are 1-based; the `m_command` array is 0-based (`parseCommandButton` writes slot
`"K"` to `m_command[K-1]`). `CommandRangeStart` is an **array index**, so `start=33` begins at INI
button `34`.
