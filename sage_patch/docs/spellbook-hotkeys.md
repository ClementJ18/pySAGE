# Spellbook shortcuts under Ctrl — reverse-engineering notes

The RE behind [`patches/experimental/spellbook_hotkeys.py`](../patches/experimental/spellbook_hotkeys.py).
Engine build `2.01.2614.37001`, ImageBase `0x400000`, no ASLR. Every address below was read
statically out of `game.dat` (sha256 `5481de75b63e22483660ea8097478faef594f90b9ade7de893e092256ba68a26`),
which `sage-patch sagepatch` reports as carrying no known patch.

**Status: experimental.** It has been run. A spellbook power does fire from its own `&` letter
under Ctrl with nothing selected, which is the claim the patch exists to make. Two things came
back from that play, one fixed and one open:

- **Fixed:** it cast powers still on cooldown, arming a targeting cursor that refused every
  target. The gate it was missing is §6, and there was none in the engine to inherit.
- **Open:** the shortcut is **not reliably picked up** — reported as happening *after dragging to
  scroll the camera sideways*, and clearing when another button is clicked or the selection
  changes. One cause has been removed on suspicion (the equality match in §2, now a mask test);
  whether that was the cause is unverified, and the remaining candidates are in §7.

The cave is also executed against a modelled world in
[`tests/sage_patch/test_spellbook_hotkeys.py`](../../tests/sage_patch/test_spellbook_hotkeys.py),
which is a test of the frame arithmetic and nothing more: the stubs were written from the same
reading of the disassembly as the cave, so a wrong reading passes both. The open symptom above is
exactly the kind of thing that finds.

## 1. Why a spellbook power cannot have a shortcut today

A command button's shortcut is not an INI field. It is the character after the first `&` in the
button's **localized** `TextLabel`, found by `HotKeyManager::getHotKeyFromLabel` (`0x0075A7CB`),
which fetches the string through `TheGameText` and scans it:

```asm
0075a6b0  mov  ax, word ptr [esi]
0075a6b3  test ax, ax
0075a6b6  je   0x0075a6c2          ; end of string: no shortcut
0075a6b8  cmp  ax, 0x26            ; L'&'
0075a6bc  je   0x0075a6e1          ; take the next wide character
0075a6be  inc  esi / inc esi
```

Registration is per **GameWindow**, and it happens in `ControlBar::setControlCommand`, the function
that binds a `CommandButton` into one of the 33 grid slots:

```asm
0071d099  mov  [esi+0xc4], edi     ; esi the button, edi the window it now occupies
...
0071d0c0  cmp  dword [0x00de7870], ebx   ; TheHotKeyManager
0071d112  mov  ecx, eax
0071d114  call 0x0075ce47          ; CommandButton::getTextLabel
0071d124  call 0x0075a7cb          ; -> the letter
0071d139  call 0x0075ae14          ; HotKeyManager::addHotKey(out, functor, key, scope)
```

So the shortcut exists exactly as long as the button occupies a window, which is what makes an
ability's key work only while its unit is selected.

**The spellbook bar is not a window grid.** It is an APT movie: its click path is the callback
registered as `"OnAptInGameSpellBookButtonPressed"` at `0x00931880`, whose body is `0x00930DE5` and
whose argument arrives as a slot number in a *string* (`atoi` through `[0x00BD0628]`). No window
is ever created for those buttons, so `setControlCommand` never runs for them and no letter is
ever registered. That is the whole of the gap.

`addHotKey`'s last argument selects between two maps — `this+0x0c` (the per-window scope,
`setControlCommand` passes 0) and `this+0x18` (a global one, which the "select all heroes" button
at `0x0092C0BE` uses with 1). Registering spellbook buttons into the global map is therefore a
possible shape for this patch, and is the one **not** taken: it needs a functor object with a
vtable of its own and a registration lifecycle tied to every event that changes the bar. Walking
the set at the moment a key is pressed needs neither.

## 2. Ctrl is dead space

The hotkey translator (`0x0075B068`, `mov eax, imm32` entry, `ret 4`) builds the modifier mask
from the key message's second argument and then throws the press away if anything but Shift is
held:

```asm
0075b0f9  test ax, 0x430
0075b102  push 0x10 ; pop esi      ; esi |= SHIFT
0075b105  mov  byte [ebp-0x10], 1
0075b109  test al, 0xc             ; either Ctrl key
0075b10d  or   esi, 4
0075b110  mov  byte [ebp-0x10], bl ;   ... and clear the flag
0075b113  test al, 0xc0            ; either Alt key
0075b117  or   esi, 0x40
0075b11a  mov  byte [ebp-0x10], bl
0075b11d  cmp  esi, ebx            ; <- the gate
0075b11f  je   0x0075b12a          ;    no modifier: take the key
0075b121  cmp  byte [ebp-0x10], bl
0075b124  je   0x0075b1ac          ;    Ctrl or Alt: discard it
0075b12a  ... build the key's AsciiString, then executeHotKey
```

Two things fall out of that.

**`esi` is the `Modifiers` vocabulary.** `CommandMap`'s `Modifiers` keyword parses against the
name table at `0x00BF0E28`, which is exactly `CTRL 0x4`, `SHIFT 0x10`, `ALT 0x40` and their
combinations, and the `CommandMap` translator builds the identical mask from the identical tests
(`0x005DA8B1`, the only other site in the image that tests `ax, 0x430`).

**It matches that mask by equality**, at all three of its comparison sites:

```asm
005da92f  cmp dword [esi+0x10], eax   ; the MetaMapRec's Modifiers
005da932  je  0x005da96c
```

which is worth knowing because it is fragile and this patch deliberately does **not** copy it. A
binding on Ctrl stops matching the instant any other bit joins the mask, and one of the bits the
translator folds in - `0x400`, tested alongside the two Shift keys and not identified here - is
not a key the player is holding. The gate tests the two bits it cares about instead: Ctrl set,
Alt clear. Ctrl+Shift fires as well, which is the safe direction to be wrong in.

**Ctrl+letter reaches nothing at all in the stock build.** The gate discards it here, and RotWK's
shipped `CommandMap.ini` is two entries long (`RELOAD_RAPID_ITERATION_FEATURE` and
`REFRESH_RAPID_ITERATION_FEATURE`, both Shift). Claiming Ctrl therefore takes no combination away
from anything.

The thirteen bytes `0x0075B11D`–`0x0075B129` end exactly on the proceed target, and `xref` finds no
inbound branch into them other than the `je` being replaced. They are replaceable as a block.

## 3. Where a matched button is handed back to the engine

`ControlBar::processCommandUI` (`0x00941B9F`) is where a click enters, but it is the *window* that
it resolves; the part that acts on the button is one call further in:

```asm
00941bf6  push eax                 ; (msg != 0x4009)
00941bfa  push eax                 ; (msg == 0x400b)
00941bfb  push esi                 ; the CommandButton
00941bfc  call 0x00940435          ; ControlBar::doCommand
```

`ControlBar::doCommand` (`0x00940435`, `__thiscall` on `THE_COMMAND_SET_STORE` — the ControlBar and
the command-set store are one singleton at `0x00DE7744`, `ret 0xC`) is the whole of a click:
targeting cursor, sounds, `CommandTrigger`, and the network order. Both `Bool`s are read as bytes.

It has three commands exempt from needing a selection, and one of them is the spellbook:

```asm
00940455  mov  eax, [esi+0x14]     ; the button's Command
00940458  cmp  eax, 0x19           ; PURCHASE_SCIENCE
0094045d  cmp  eax, 0x20           ; SPECIAL_POWER_FROM_COMMAND_CENTER
00940462  cmp  eax, 0x26           ; SPELL_BOOK
00940465  je   0x00940498          ;   -> skip the "is anything selected" path
```

The `SPELL_BOOK` arm of its dispatch (`0x00941423`) confirms the same thing from the other side: it
emits `MSG_DO_SPELLBOOK_SPECIAL_POWER` (`0x456`) with the special power's id, the button's
`Options`, and an ObjectId of **zero**. The order is player-scoped by construction.

The APT bar already calls `doCommand` directly, and that call is what this patch reproduces —
including its second argument, which is not simply zero:

```asm
00930e07  mov  ecx, [0x00de3f0c]   ; TheAptPlayer
00930e0d  cmp  dword [ecx+0x318], 2
00930e14  push 0
00930e16  setne cl
00930e19  push ecx                 ; the low byte is the Bool; the rest is the pointer's
00930e1a  mov  ecx, [0x00de7744]
00930e20  push eax                 ; the button
00930e21  call 0x00940435
```

## 4. Which buttons, and how many

The bar's own update loop answers both. `ebx` is the spellbook UI, `[ebx+0x2c]` its cached
`CommandSet`, and the walk is bounded at 24:

```asm
00931331  cmp  dword [ebp-0x14], 0x18
00931335  jge  0x00931578
0093134a  mov  ecx, [ebx+0x2c]
00931351  call 0x0080c837          ; CommandSet::getCommandButton(slot)
```

`CommandSet::getCommandButton` (`0x0080C837`, `ret 4`) is `[this + slot*4 + 0x14]` with an override
hook in front and **no bounds check**, so the bound has to come from the caller;
`SPELLBOOK_UI_SLOT_LIMIT` is that 24.

The patch does not use the UI object — it has no reachable global — and resolves the same set from
the player instead, which is the chain [`spellbook-commandset-refresh`](spellbook-commandset-refresh.md)
already runs in a cave: `PlayerList::getLocalPlayer` (`0x006A8839`) →
`Player::getSpellBookObject` (`0x006AD0F8`) → `Object::getCommandSetString` (`0x0069156B`) →
`ControlBar::findCommandSet` (`0x0071EFA2`).

`Object::getCommandSetString` is deliberately **not** anchored: `commandset-button-upgrade`
legitimately detours it, and this cave wants whatever overlay is installed.

## 5. The two edits

### 5a. The gate, at `0x0075B11D`

Thirteen bytes become a `jmp rel32` and eight `nop`s. The cave repeats the stock decision and adds
one arm:

| `esi` | stock | patched |
|---|---|---|
| `0` (none) | proceed | proceed |
| `0x10` Shift | proceed, flag 1 | unchanged |
| `0x04` Ctrl | **discard** | proceed, flag `2` |
| `0x14` Ctrl+Shift | discard | proceed, flag `2` |
| `0x40` Alt, `0x44` Ctrl+Alt, `0x54` | discard | discard |

The mark is written into the same byte stock uses for the flag, which is the second argument
`executeHotKey` receives. Stock only ever puts 0 or 1 there, so no stock functor can see a 2. It is
written as a byte and read as a byte, exactly as stock does — the dword that gets pushed carries
three bytes of whatever the frame held.

### 5b. The executor, at `0x0075AF43`

`HotKeyManager::executeHotKey` (`0x0075AEFA`, `__thiscall(AsciiString *key, Bool flag)`, `ret 8`)
opens with four game-state gates — a running game, `TheInGameUI+0x15` and `+0x16`, and its vtable
`+0x17c`. The hook goes **past** them, at the first instruction after the last one:

```asm
0075af43  push esi                 ; five bytes, three whole instructions
0075af44  push edi
0075af45  push [ebp+8]
0075af48  lea  ecx, [ebp-0x10]     ; the resume point
```

Two consequences make this the right five bytes rather than the function entry:

- The gates have already run, so the branch inherits them instead of re-deriving them.
- `ebp` is set up, so `[ebp+8]` (the key) and `[ebp+0xc]` (the flag) are addressable.

`ebx` has held the `HotKeyManager` since `0x0075AF06`, and at this depth only `ebx` is pushed below
`ebp` — which is what makes the function's own exits reachable from the cave. `0x0075B057` forces
`al` to zero and returns; `0x0075B059` is the same epilogue one instruction later, so the cave sets
its own `al` and jumps there. `esi` and `edi` have *not* been saved yet at this point, so the cave
saves them itself.

An unmarked press re-emits the three displaced instructions and resumes. A marked one runs:

```
    save esi/edi, make three slots:  [esp+0] out AsciiString, [esp+4] button, [esp+8] pressed char
    read [ebp+8]->m_data, take byte +8, fold to lower       -> [esp+8]
    local player -> spellbook Object -> CommandSet, or miss
    for slot in 0 .. 23:
        button = getCommandButton(slot);  skip if null
        label  = getTextLabel(button);    skip if null
        getHotKeyFromLabel(&out, label)
        if out.m_data and fold(out[8]) == [esp+8]:
            destroy out
            if getCommandAvailability(button, 0, 0, &real, 0) in (1, 2):   # see §6
                doCommand(button, TheAptPlayer+0x318 != 2, 0); al = 1; -> 0x0075B059
            continue
        destroy out
    -> 0x0075B057
```

Three details that are not obvious from that sketch, and that the tests pin:

**The three slots survive every call.** `getCommandButton` is `ret 4`, `getHotKeyFromLabel` is
`ret 8`, `doCommand` is `ret 0xC`, and the rest take no stack arguments — every callee cleans its
own, so `esp` is back where it was after each one and the offsets hold.

**`out` is constructed into, not assigned.** `0x00435F30` is the copy constructor —
`mov [edi], eax` then `inc [eax]`, with no release of what was there — so the slot does not need to
be valid before the call. It does need to be **destroyed** after, and `AsciiString::~AsciiString`
(`0x00435D50`) is null-safe and leaves the slot null, which is what lets the early exits destroy a
slot that was never written and lets the next iteration construct into it again.

**Case.** The letter the `&` scan yields carries the string table's case; the key name the
translator built carries the keyboard map's. Stock resolves this by looking the key up twice, lower
then upper (`0x0075AF57` and `0x0075AFC1`); the cave folds both sides instead, which is the same
answer for the single ASCII character these strings hold.

## 6. Availability, and why the engine had no check to inherit

**Reported from play: the shortcut cast powers that were still on cooldown**, opening a targeting
cursor that then refused every target. Nothing on the `SPELL_BOOK` path stops that, and the reason
is that the gate was never in the engine.

`ControlBar::doCommand` asks `ControlBar::getCommandAvailability` (`0x00942733`, `__thiscall`,
`ret 0x14`) once, at `0x009405B3`, and that call is inside its **per-selected-drawable** loop —
the loop the three exempt commands at `0x009404AD` skip, `SPELL_BOOK` among them. The APT click
path at `0x00930DE5` does not ask either: `atoi`, a bounds check, and straight into `doCommand`.

So the greying lives in the **movie**. The bar's update evaluates each slot and pushes the result
into the APT button's state, and a disabled movie button never fires its callback — which is why
the engine never needed a check and why a cave that bypasses the movie has to supply one.

**The rule is 1 or 2, and two independent sites say so.** `doCommand`'s own call tests exactly
those:

```asm
009405b8  cmp eax, 1
009405bb  je  0x00940656          ; this drawable can take the command
009405c1  cmp eax, 2
009405c4  je  0x00940656
```

and the bar's update maps them to the only two movie states it then marks clickable, sending 0, 4,
6 and 7 to a greyed state (`0x009313B3`–`0x009313E4`) and skipping the slot outright on 3
(`0x00931377`). A call with no local player returns 3 (`0x0094276B`).

The cave asks only about the button whose letter matched, and a refusal **rejoins the walk** rather
than ending it — the same rule duplicate letters already follow, so a greyed button does not shadow
a usable one further down the bar.

## 7. What is still unknown

- **Why the shortcut is often not picked up.** The open symptom above, reported as following a
  drag-scroll. One candidate has been acted on: the modifier match was an equality test copied
  from the engine, so any stray state bit in the mask lost the press, and it is now a mask test
  (§2). That is a fix on suspicion, not a diagnosis. The rest, none checked against the running
  game:
  - **The gates this hook sits behind.** `executeHotKey` refuses on `TheGameLogic+0x124`, on
    `TheInGameUI+0x15` or `+0x16` being zero, and on `TheInGameUI`'s vtable `+0x17c` answering
    true (`0x0075AF08`–`0x0075AF3D`). The last is a virtual call this write-up has not identified.
    If it means something like "a modal or order mode is active", that alone would explain both
    the flakiness and why clicking elsewhere clears it.
  - **Another translator consuming the key first.** The translator chain's order has not been
    recovered, and a window holding keyboard focus would be changed by clicking.
  - **An armed targeting cursor swallowing the next press.** A press that arms a cursor leaves the
    UI in order mode, and clicking elsewhere cancels it. The §6 fix removes the commonest way to
    end up there by accident, so this one may already be smaller than it was.
- **Auto-repeat.** The gate is reached once per `0x16` message. Whether holding Ctrl+letter
  produces repeats depends on bit `0x400` of the key state, which the modifier block tests
  (`test ax, 0x430`) but which is not identified here. A repeated `doCommand` on a power already
  spent is a no-op, so the failure mode is noise rather than a double cast — but it is unverified.
- **Two buttons with the same letter.** The lowest slot wins. Nothing warns.
- **A button shared between factions** carries one letter everywhere, because the letter lives in
  the string table entry and not in the faction.
- **SEH.** The cave constructs and destroys an `AsciiString` without registering a scope in
  `[ebp-4]`. So do the function's own early exits, which is the precedent it follows.
