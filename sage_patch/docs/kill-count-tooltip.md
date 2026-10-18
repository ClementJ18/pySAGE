# A kill count in the object tooltip

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`). This is the write-up for
**`kill-count-tooltip`**, [`patches/kill_count_tooltip.py`](../patches/kill_count_tooltip.py), with
the tests in
[`tests/sage_patch/test_kill_count_tooltip.py`](../../tests/sage_patch/test_kill_count_tooltip.py).

**What it does.** Hovering an object in the world shows a tooltip: name, rank, health, upgrades,
battles fought, description. The patch adds one more line at the bottom, `TOOLTIP:Kills`
formatted with the object's kill count. A battalion member shows its battalion's count.

```sh
sage-patch apply kill-count-tooltip --in game.dat.backup --out game.dat   # no parameters
sage-patch verify kill-count-tooltip game.dat
```

The mod supplies the string, with the count as its one `%d`:

```
TOOLTIP:Kills
"Kills: %d"
END
```

- **Nothing shows below one kill.** Nor does anything show while the string table has no
  `TOOLTIP:Kills`: the line is dropped, not shown as `MISSING:`. A mod opts in by adding the
  string.
- **Cost:** one 5-byte window and a 167-byte section.
- **Not needed:** no INI field, `.apt` edit or savegame change.
- **Client-side and read-only.** The engine already keeps the number; the patch only prints it.

**Status: built and static-verified.** It applies, verifies and detects against the real
`game.dat`, and composes with `herobar` in either order. The cave runs under Unicorn on every
path. Everything it relies on in the engine was confirmed in a running game (§4), with the stock
`BattlesFought` line standing in for the new one.

## 1. The engine already counts kills

The kill scorer `0x006955BC` runs once per death. At `0x00695701` it does this:

```asm
00695701  inc  dword [esi+0x490]       ; esi = the killer
00695707  mov  eax, [esi+0x27c]        ; OBJECT_CONTAINED_BY
0069570d  inc  dword [esi+0x48c]
0069571a  test byte [ecx+0x115], 0x20  ; the container is KINDOF_HORDE
00695723  inc  dword [eax+0x490]
00695729  inc  dword [eax+0x48c]
```

What reaches that code:

- **Summons count for their summoner.** Before counting, the scorer walks from the killer up the
  producer chain (`+0x78`) while the template has `PASS_EXPERIENCE_TO_PRODUCER`.
- **Only enemy kills count.** It skips victims that are not enemies, and victims of the killer's
  own player.

The two counters sit in an identity record at `Object+0x488`:

| offset | field |
|---|---|
| `+0x488` | battles fought |
| `+0x48C` | kills |
| `+0x490` | kills, again |
| `+0x494` | the custom name (`UnicodeString`) |
| `+0x498` | an `AsciiString` |
| `+0x49C` | a byte |

- **Created zeroed.** `Object::Object` zeroes the record at `0x00699CEA` (`0x008E4919`).
- **Copied across a mount swap** at `0x008B14B0`.
- **Copied into the War of the Ring snapshot** at `0x00691903`.

**The two kill fields are equal.** Nothing else in the image writes them. In a live match they
read equal through 80 recorded changes, so the patch reads `OBJECT_KILLS` (`+0x48C`) and either
would do.

## 2. Where the tooltip is built

`0x008EBC61` builds the object tooltip once per hover. It goes through the same request manager
(`0x00807848`) as the button tooltip that
[`description-timers`](description-timers.md#2-the-tooltip-is-built-once-per-hover) documents. Two
frame slots matter:

| slot | what |
|---|---|
| `ebp-0x18` | the hovered `Object`, written once at entry. A null one jumps to `0x008EC13D`, past every line |
| `ebp-0x1c` | the line list, a `UnicodeString` |

Lines join the list through the builder's own helper `0x008EBC3B`, a cdecl
`(lines, line)` that puts a newline first unless the list is still empty. The engine already prints
one field of the record, `TOOLTIP:BattlesFought`, at `0x008EC052`:

```asm
008ec052  mov  eax, [esi+0x488]        ; battles fought
008ec05b  jle  0x8ec09c                ; nothing at zero
008ec05d  mov  [ebp-0x2c], ebx         ; an empty temporary
008ec066  push eax                     ; the count, left pushed for the format
008ec069  push ebx / push 0xc79200     ; exists, "TOOLTIP:BattlesFought"
008ec073  call [TheGameText+0x44]      ; fetch: __thiscall, ret 8
008ec07b  call 0xadf7e0                ; format into the temporary
008ec088  call 0x8ebc3b                ; add the line
```

The kills line is that code with one key swapped. Two contracts make the copy safe:

- **The fetch returns a string the caller does not own,** so nothing frees it.
- **`0x00ADF7E0` replaces its destination.** It takes the fetched `UnicodeString *`, formats
  through `0x00437120`, and `set`s. So the line is built in a zeroed temporary, not in the list.
  `description-timers` §1.3 documents the trap.

After the description line, which is added at `0x008EC112`, the builder releases the description
temporary:

```asm
008ec119  lea  ecx, [ebp-0x28]
008ec11c  mov  byte [ebp-4], 0xc
008ec120  call 0x4367b0                ; ~UnicodeString        <- the hook
008ec125  ...                          ; then the tooltip record is made at 0x008EC13D
```

## 3. The patch

**The window is the 5-byte `call` at `0x008EC120`, not the 7 bytes in front of it.**
[`herobar`](herobar.md) owns `0x008EC119`–`0x008EC11F` for its group line and resumes at
`0x008EC120`, so taking the call composes with it. With both applied, the kills line comes after
the group line. The window is not a branch target (every byte offset of `.text` was scanned) and no
32-bit immediate points into it.

The call is retargeted at the cave, which:

1. **Saves every register** (`pushad`). The tail call at the end must see the builder's state.
2. **Finds the object.** It reads `[ebp-0x18]` and does nothing on null.
3. **Picks the battalion when there is one.** If `[obj+0x27C]` is set and its template has
   `KINDOF_HORDE`, it reads that object instead. The battalion's count is the sum of its members'
   kills and survives a member being replaced. The tooltip itself reads the hovered member's own
   record (§4), so this redirect is the patch's job.
4. **Reads `+0x48C`** and stops unless it is above zero.
5. **Formats the line** exactly as §2's idiom does: two locals below `esp` (the fetch's `exists`
   and an empty `UnicodeString`), the count pushed ahead of the fetch, then `0x00ADF7E0` into the
   local, `0x008EBC3B` into `[ebp-0x1c]`, and `~UnicodeString` on the local.
6. **Drops the line when `exists` comes back 0.** That path is reached before the format, so the
   local owns nothing and only the count is popped.
7. **Makes the displaced call last.** It restores the registers (`popad`) and makes the displaced
   call as a tail `jmp` to `~UnicodeString`, which returns to `0x008EC125` with `ecx` as the stock
   bytes left it.

The section is `TOOLTIP:Kills\0`, padded to `0x10`, followed by the code. The string comes first
because the cave pushes its address.

**Exception safety:** the local is not covered by the builder's `ebp-4` state, so a throw out of
the format or the append leaks its buffer. Both throw only on allocation failure, as in
`description-timers`.

## 4. What a running game confirmed

All measured on 2026-10-18 in Edain Unchained, in a Harlindon skirmish of Mordor against an Elf AI.
Values were read with `sage_live` and written with `WriteProcessMemory`.

- **The builder is the world-hover tooltip.** With `+0x488` set to 7 on the keep, hovering it
  showed `Citadel / Health: 4000 / Battles Fought: 7`. So a line added through `0x008EBC3B` here
  is drawn.
- **The tooltip reads the hovered object's own record.** With the battalion's battles fought set to
  5 and its members' left at 0, hovering a member showed
  `Orc Warrior / Level: 1 / Maximum Level: 5 / Health: 142` and no battles line.
- **Battalion totals.** `ElvenLorienWarriorHorde#515` read 12, the sum of its members' kills, and
  kept counting as members changed.
- **What counts kills.** Heroes (`MordorGorbag`, 2), towers (`MordorBattleTower`, 13) and creeps
  all counted.
- **`+0x48C` and `+0x490` never differed** across 80 recorded changes.
- **Saves keep the record.** I wrote `(7, 11, 12)` to the keep and `(5, 21, 22)` to a battalion,
  saved, zeroed both in memory, then loaded. Both came back exactly, while an untouched battalion
  read `(0, 0, 0)`.

**What a live run of the patch itself still has to show:**

1. A unit with kills shows the line, and the number matches `sage_live`.
2. A battalion member shows its battalion's number.
3. Without `TOOLTIP:Kills` in the string table, nothing shows.

## 5. Addresses

| VA | what |
|---|---|
| `0x006955BC` | the kill scorer |
| `0x00695701` | its kill-count increments (`OBJECT_SCORE_KILL_COUNT`) |
| `0x008EBC61` | the object tooltip builder (`OBJECT_TOOLTIP_BUILD`) |
| `0x008EBC3B` | its add-a-line helper (`OBJECT_TOOLTIP_APPEND_LINE`) |
| `0x008EC052` | the `TOOLTIP:BattlesFought` line (`OBJECT_TOOLTIP_BATTLES_FOUGHT`) |
| **`0x008EC120`** | **the hook**: the description release (`OBJECT_TOOLTIP_DESCRIPTION_RELEASE`) |
| `0x008EC125` | where it returns |
| `Object+0x488` / `+0x48C` / `+0x490` | battles fought, kills, kills again |
