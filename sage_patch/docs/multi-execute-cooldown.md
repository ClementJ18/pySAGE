# Group cooldowns on a multi-execute special power

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR), read from the
repo's `game.dat`.

- **Cost:** 5 `rel32` repoints and a `0x216`-byte `.mxcool` cave. No structure grows, no INI
  keyword is added.
- **Risk:** low. The cave only turns a stock "recharging" or "not ready" into "ready", and only
  for a `SPECIAL_POWER` button with `OK_FOR_MULTI_EXECUTE`, and only when another selected unit
  has that power ready.
- **Status:** static-verified and emulated: all three routines run under Unicorn over the patched real
  `game.dat` (`tests/sage_patch/test_multi_execute_cooldown_emulated.py`). Not yet seen in a
  running game.

```
sage-patch apply multi-execute-cooldown --in game.dat.backup --out game.dat
```

## The complaint

Select several goblin hordes and use *Poisoned Blades* (a `SPECIAL_POWER` with
`OK_FOR_MULTI_SELECT OK_FOR_MULTI_EXECUTE`) from one of them. The button then shows that horde's
cooldown for the whole group and can't be clicked, though the other hordes still have the power.

## Why

### The bar paints one unit

`ControlBar::evaluateContextUI` (`0x0071EBDA`) picks the bar's context. With more than one unit
selected it asks `TheGameClient` (vtable `+0x40`) for a drawable by an id `TheInGameUI` supplies
(vtable `+0x130`):

```
0071ecce  call [eax+0x118]          ; TheInGameUI: selection count
0071ecd4  cmp  eax, 1
0071ecd7  jle  ...
0071ecec  call [eax+0x130]          ; an id for the selection
0071ecf9  call [esi+0x40]           ; TheGameClient: that drawable
0071ed00  sete bl                   ; none -> the mixed-selection context (7)
```

When a drawable comes back (in practice, a selection of one kind), the bar takes the
single-object context for that one drawable, and its slot update
(`CONTROL_BAR_UPDATE_SLOT_AVAILABILITY`, `0x0094397F`) asks the availability evaluator about it
alone (`call 0x942733` at `0x00943ADB`).

For a `SPECIAL_POWER` button whose module isn't ready, the evaluator writes the module's ready
fraction (vtable `+8`) to its progress out-argument and answers **5**:

```
0094357e  call [eax+4]              ; module ready?
00943583  jne  ...                  ;   yes
00943589  call [eax+8]              ; ready fraction
00943591  fstp [eax]                ; -> *progress
009435c3  call 0x942490             ; model-condition gate
009435c8  sub eax,3 / neg / sbb / and eax,5   ; available -> 5, disabled -> 0
```

The slot update paints 5 as a disabled window with a recharge clock. So the group shows the
representative's cooldown, whichever unit that happens to be.

A mixed selection (context 7) goes through `0x00944911` instead. That update asks every member
(`0x009449D6`) and counts the usable answers per slot, enabling a slot when the count is
non-zero. But it paints each member's state in turn, and its final pass doesn't clear the
recharge status bit (`0x400000`) or the clock, so the last member asked decides what the button
looks like.

### The click is gated the same way

`ControlBar::doCommand` (`0x00940435`) sends both special-power commands (`0x17`, `0x18`) to one
gate at `0x0094070F`:

```
0094070f  test ebx, ebx             ; a context object?
00940713  push ebx
00940716  call 0x75cc3e             ; CommandButton::isReady(that object)
0094071b  test al, al
0094071d  jne  0x940656             ;   -> post the command
00940723  jmp  0x940642             ;   -> drop the click
00940728  cmp  [edi+0x70], 7        ; the mixed context:
0094075a  push [eax+0xfc]           ;   every selected member...
00940762  call 0x75cc3e
00940769  je   0x940642             ;   ...and the first not ready drops the click
```

`CommandButton::isReady` (`0x0075CC3E`) answers, for `SPECIAL_POWER`, whether the object's module
for the button's power is at a ready fraction of exactly 1.0. So the click needs the
representative to be ready, or, in a mixed selection, every member.

### The order itself is already per unit

What a click posts is `MSG_DO_SPECIAL_POWER` with the button's `Options` and source id 0, which
the logic side routes to the issuing player's whole selection
(`docs/multi-execute-gate.md`). With `OK_FOR_MULTI_EXECUTE`, `AIGroup::doSpecialPower`
(`0x0076F5DB`) visits every member and asks the per-member gate `0x0082D5DA` with its "check
recharge" argument set:

```
0076f6cf  push 1                    ; check recharge
...
0076f6da  call 0x82d5da
0082d673  cmp  byte [ebp+0x18], 0   ; check recharge?
0082d67d  call [eax+8]              ;   the module's ready fraction
0082d680  fld1 / fcompi             ;   < 1.0 -> refuse this member
```

So a member still recharging is already skipped and the ready ones fire. Only the bar was in
the way.

## The mixed-selection clock

A recharge clock is a one-frame request, not a state. `GAME_WINDOW_COMMAND_PROGRESS`
(`0x00729F0C`) writes it into the command window's `0x38`-byte data record: kind 2 at `+0`, the
percentage at `+4`, the colour at `+8`. The button renderer draws the request and clears it:

```
004a4911  mov  al, [esi]             ; the kind
004a4968  cmp  al, 2
004a49ae  call 0x4a427e              ; draw the clock at [esi+4] percent, [esi+8] colour
004a49b7  mov  byte [esi], 0         ; consumed
```

The mixed-selection update paints every member into the same window in turn. A recharging member
requests a clock and sets `WINDOW_STATUS_RECHARGING` (`0x400000`). A ready member asked later
requests nothing, so the earlier request stands. The final pass then enables any slot some member
can use (count > 0), but clears only status `0x80000000` and `0x1000000`:

```
00944b45  cmp  [esp+ebp*4+0x2c], ebx  ; usable members for this slot
00944b4b  jle  0x944b6e               ;   none -> disable
00944b4f  call WINDOW_ENABLE(1)
00944b5b  call clearStatus(0x80000000)
00944b67  call clearStatus(0x1000000) ; <- hooked
```

So a usable button can carry a clock. That's wrong for every command whose click needs only one
usable member, which is the mixed-selection rule for everything except the two special-power
commands. With `availability_any` in place, multi-execute special powers can't produce the case at
all, since every member answers the same. The remaining cases are other commands that report
progress (types `0x08`, `0x10`, `0x16`).

## The patch

Three routines in a `.mxcool` cave. The first two each stand in for the stock routine at two call
sites. Each
calls the stock routine first and returns its answer unchanged unless the button is a
`SPECIAL_POWER` (`Command` `+0x14` = `0x18`) with `OK_FOR_MULTI_EXECUTE` (`Options` `+0x1C` bit
20), and the stock answer is the one being widened.

- **`availability_any`** (`__thiscall` on the ControlBar, `ret 0x14`), at `0x00943ADB` and
  `0x009449D6`. On a 5 it asks the evaluator again for every other selected unit
  (`TheInGameUI` vtable `+0x124`, a `std::list` whose nodes carry the `Drawable *` at `+8`;
  `Drawable+0xFC` is the `Object *`). The first unit that answers 1 or 2 decides: that answer,
  with progress 1.0 (no clock). If nobody does, it stays 5 with the progress of the member
  closest to ready, so a group that has all used the power shows the clock that will finish
  first.
- **`ready_any`** (`__thiscall` on the button, `ret 4`), at `0x00940716` and `0x00940762`. On a
  refusal it asks `isReady` of every selected unit and passes if any is ready. In the mixed
  context that makes every iteration pass when anyone is ready, which turns the stock "every
  member" rule into "any member".

- **`usable_paint`** (`__thiscall` on the window, `ret 4`), at `0x00944B67`. It does the stock
  `clearStatus`, then reads the slot's button (`GAME_WINDOW_GET_COMMAND_BUTTON`). Unless it is a
  special power whose click still needs every member ready (`0x17`, or `0x18` without
  `OK_FOR_MULTI_EXECUTE`), it clears `0x400000` and drops a pending clock request (kind 2 only;
  any other overlay request is left alone).

The caves only call the stock routines they stand in for, the window helpers and one
`TheInGameUI` virtual. Callee-saved registers
are kept, and each routine pops exactly what the routine it replaces pops.

## Behaviour

- **Button:** with several units selected, a `SPECIAL_POWER` button with `OK_FOR_MULTI_EXECUTE`
  shows ready and is clickable while any selected unit has the power ready. When none does, it
  shows the cooldown of the unit closest to ready.
- **Click:** fires the power on the ready units only. That is stock logic-side behaviour, so
  peers don't need the patch, and replays are unaffected.
- **Mixed selections:** a button that some selected unit can use no longer shows a cooldown clock
  left by another unit. A special power without `OK_FOR_MULTI_EXECUTE` keeps its clock, because
  its click is still refused until every unit is ready.
- **Other buttons:** special powers without `OK_FOR_MULTI_EXECUTE` keep the stock rule, and
  single-unit selections behave exactly as stock.
- **Composition:** applies before or after every other registered patch that applies to this
  binary, including `multi-execute-gate`. The two compose: `multi-execute-gate` skips members
  whose own button is disabled by a model condition, and this patch keeps the button usable
  while anyone has the power.

## Targeted powers

These need nothing beyond the button and its click. The map click that confirms a target posts
`MSG_DO_SPECIAL_POWER_AT_OBJECT` / `_AT_LOCATION` from `0x0081E14D`. The only check it makes first
is the relationship between one selected unit and the target (`0x0075CCE7` →
`0x0075CC13`), not cooldown:

```
0081e1b8  call 0x75cce7              ; relationship(first selected, target)
0081e1c9  mov  ebx, 0x412            ; MSG_DO_SPECIAL_POWER_AT_OBJECT
```

On the logic side the dispatcher's `0x411` / `0x412` cases (`0x0077A502` / `0x0077A5D7`) call the
targeted group loop (`0x0077097E`) with command source `ebx` = 0. That loop passes
`source == 0` as the per-member gate's check-recharge argument:

```
00770aee  mov  ecx, [ebp+0x14]       ; command source
00770af3  sete al
00770af8  mov  [ebp-0x1c], al        ; check recharge = (source == 0)
00770b54  push [ebp-0x1c]
00770b67  call 0x82d925              ; CAN_DO_SPECIAL_POWER_AT_OBJECT, arg 6
0082da8c  cmp  byte [ebp+0x1c], 0    ; -> module ready fraction < 1.0 refuses
```

So a player's targeted multi-execute order also fires only the ready units.

## Not covered

- **`SPECIAL_POWER_FROM_COMMAND_CENTER` (`0x17`)** keeps its stock rule.
- **Tooltips** that print a cooldown read it on their own and aren't changed.

## Addresses

| VA | meaning |
|---|---|
| `0x0071EBDA` | `ControlBar::evaluateContextUI` |
| `0x0075CC3E` | `CommandButton::isReady(Object *)`, `ret 4` |
| `0x0076F5DB` | `AIGroup::doSpecialPower` |
| `0x0082D5DA` | its per-member gate; arg 5 = check recharge |
| `0x0094070F` | `doCommand`'s special-power gate |
| `0x00940716` / `0x00940762` | its two `isReady` calls (hooked) |
| `0x00942733` | `ControlBar::getCommandAvailability` |
| `0x0094397F` | the single-object slot update |
| `0x00943ADB` | its availability call (hooked) |
| `0x00944911` | the mixed-selection slot update |
| `0x009449D6` | its availability call (hooked) |
| `0x00944B67` | its final pass's last `clearStatus` for a usable slot (hooked) |
| `0x007155B9` | `GameWindow::clearStatus(mask)` |
| `0x00729F0C` | `GAME_WINDOW_COMMAND_PROGRESS`: a one-frame clock request |
| `0x004A4911` | the button renderer drawing and consuming that request |
| `0x0081E14D` | the targeted-power command emitter |
| `0x0077097E` | `AIGroup::doSpecialPowerAt*`; check recharge = (source == 0) |
| `0x00DE4830` | `TheInGameUI`; vtable `+0x124` the selected-drawable list |
