# Command-button shortcuts and hidden slots

The RE behind [`patches/visible_hotkeys.py`](../patches/visible_hotkeys.py). ROTWK `game.dat`
`2.01.2614.37001`, ImageBase `0x400000`. Read statically; the cave is executed under Unicorn in
[`tests/sage_patch/test_visible_hotkeys.py`](../../tests/sage_patch/test_visible_hotkeys.py)
against the engine's own getter and method bytes.

## 1. How a shortcut is registered

A button's shortcut is the character after the first `&` in its localized `TextLabel`
(`HotKeyManager::getHotKeyFromLabel`, `0x0075A7CB`; see [spellbook-hotkeys.md](spellbook-hotkeys.md)
§1). `ControlBar::setControlCommand` (`0x0071CF3E`) registers it for the slot window being bound:

```asm
0071d0e0  call 0x75a7cb             ; -> the letter, an AsciiString at [ebp+0xc]
0071d0e8  cmp  eax, ebx / je         ; none
0071d0f3  cmp  word [eax+4], bx / je ; empty
0071d0f9  push 0xc
0071d0fb  call 0x42f6e0             ; operator new - the handler
0071d10f  call 0x9444f3             ; handler(window)
0071d139  call 0x75ae14             ; HotKeyManager::addHotKey(out, handler, key, scope 0)
```

Every bound slot registers, hidden or not. The bind loop (`0x009445C0`) binds the 33 slots in
order, so registration order is slot order.

The handler is `{vtable 0x00C80310, refcount, GameWindow *}`. Its constructor (`0x009444F3`) has
one caller and is the only reference to the vtable. The three methods read only `[this+8]`:

| slot | VA | does |
|---|---|---|
| `+4` | `0x00944476` | `winGetStatus() >> 4 & 1`: HIDDEN (`0x10`) |
| `+8` | `0x00944487` | `winGetStatus() >> 3 & 1`: ENABLED (`0x08`) |
| `+0xC` | `0x00944498` | the click: `processCommandUI` on the window |

`winGetStatus` is `0x009F9F16`, `mov eax, [ecx+8]`.

## 2. Two slots per letter, hidden ones included

`addHotKey` (`0x0075AE14`) keeps one handler per key string. It lowercases the key
(`0x004363B0`, CRT `tolower` through `[0x00BD05C8]`) and inserts if that is free. Otherwise it
uppercases (`0x004364A0`, `toupper`, `[0x00BD05C4]`) and inserts if *that* is free. Otherwise it
drops the new handler. So the first slot with a letter owns `k`, the second `K`, and any third
gets nothing.

`executeHotKey` (`0x0075AEFA`) mirrors it. It looks up the lowercased key and asks `+4`; hidden
skips to the uppercase lookup, and so does visible-but-disabled (setting a "disabled" flag that
plays the refusal at `0x0075A5BC`). Visible and enabled runs `+0xC`. A hidden slot never fires.

**Consequence.** Edain's `DwarvenFoundationCommandSet` lists three subfaction barracks in slots
3, 5 and 7 and three forge works in 4, 6 and 8, each pair sharing a label and so a letter, each
`NEED_UPGRADE HIDE_WHILE_DISABLED` on its clan upgrade, so exactly one of each shows. Erebor and
Ered Luin get `k`/`K`; the Iron Hills variant is never registered, and an Iron Hills player has no
barracks or forge shortcut. Any set with three or more same-letter buttons loses all but the
first two, whichever are visible.

`HIDE_WHILE_DISABLED` reaches the window as `winHide` when the availability verdict is 3
(`updateContextMultiSelect`, `0x00944911`; see [multi-select-group.md](multi-select-group.md) §2),
which is the HIDDEN bit the `+4` method reads.

## 3. The patch

- **Record.** `0x0071D0F9` (`push 0xC; call new`, 7 bytes) jumps to a cave. The cave finds the
  slot index of `edi` in `ControlBar+0xDC` (`this` is `[ebp-0x14]`), stores the button (`esi`)
  and the ASCII-lowercased letter (`[eax+8]`), then runs the displaced allocation and returns to
  `0x0071D100`. A window outside the slot array records nothing.
- **Resolve.** The constructor's vtable immediate (`0x009444FF`) points at a cave vtable that
  keeps the stock deleting destructor. Each method finds its own window's slot. If that slot is
  still bound to the recorded button (`GAME_WINDOW_GET_COMMAND_BUTTON`, `0x0072979C`), it scans
  the 33 slots in order for a window that is not hidden, carries the same letter, and is still
  bound to its recorded button. It takes the first enabled one, else the first visible one, then
  calls the stock method with `ecx = &slots[i] - 8`, so the stock `[ecx+8]` reads that window. No
  match, or a window outside the array, calls the stock method on the handler itself.

The slot array is read from the live `ControlBar` (`[0x00DE7744] + 0xDC`, the same expression
as `0x0092FF8F`) on every press. The cave keeps only button pointers to compare against, never
to dereference, so windows freed at the end of a match cannot be reached through it.
`commandset-limit` keeps the control bar at 33 widgets, so the bound holds with it applied.

## 4. What does not change

- A hidden slot is never chosen, and a letter no visible slot carries does nothing, as in stock.
- The map is untouched: the first two slots per letter still own `k`/`K`, and both now resolve
  to the same choice.
- Only scope-0 (slot) handlers change. The global-scope handlers `addHotKey` takes with scope 1
  (`0x0092C0BE`, select all heroes) use other classes.
- Client-side only: the click is the same `processCommandUI` a mouse click reaches.
