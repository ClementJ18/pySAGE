# Two buttons sharing a slot in a mixed selection — reverse-engineering notes

The RE behind [`patches/multi_select_group.py`](../patches/multi_select_group.py). ROTWK
`game.dat` build `2.01.2614.37001`, ImageBase `0x400000`, no ASLR, recovered statically 2026-08-30.

**Status: built** as `multi-select-group`, applying and verifying against the real binary and
against a synthetic stand-in, and composing with `command-point-cost` and `queue-ignore-cp` in
any order. **Static-verified only — not yet runtime-verified in game.**

## The report

> In Imladris, troops can upgrade their weapon twice. This is done by changing the command set.
> However this creates the annoying thing that if you select troops at different stages of upgrade,
> the upgrade button is black due to the different buttons at the same spot.

Concretely, in the Edain tree: `BruchtalSchwertkampferHordeCommandset` holds
`Command_PurchaseUpgradeBruchtalForgedBlades` at slot 3, a `CommandSetUpgrade` swaps the whole set
to `..._Eregions` once that upgrade is bought, and the new set holds
`Command_PurchaseUpgradeBruchtalForgedBladesEregions` at the same slot 3. Select one battalion of
each and slot 3 goes dark.

Only slots 1..6 reach a unit's palantir, and all six are already spoken for, so moving the
second-stage button to a free slot is not available.

## TL;DR

- **It is hidden, not disabled.** The merge calls `winHide(TRUE)` on the slot's window; what the
  player sees is the empty socket behind the button, which reads as black.
- **`ControlBar::populateMultiSelect`'s per-drawable merge** (`0x00944534`) is the whole rule. The
  first selected unit's `CommandSet` fills the 33 slots; every later unit is merged in by the loop
  at `0x009446CA`, which compares its button for each slot with the one already installed **by
  pointer identity** (`cmp edi, eax` at `0x0094472E`). One exemption: `Command = ATTACK_MOVE`.
- **Enablement is the opposite — a union.** `ControlBar::updateContextMultiSelect` (`0x00944911`)
  keeps a 33-entry counter on the stack, bumps a slot for every selected unit whose
  `getCommandAvailability` answers 1 or 2, and finishes with `winEnable(count > 0)` at
  `0x00944B45`. So a *shared* button stays lit if anyone can use it; the intersection is only about
  which buttons are drawn at all.
- **A click reaches the whole selection and is gated per member on the upgrade, not on the button.**
  `MSG(0x415)` carries an object id of zero, and `AIGroup::doObjectUpgrade` (`0x0076FBFB`) skips a
  member that already has the upgrade or cannot accept it — and asks nothing about whose
  `CommandSet` the button came from. That is what makes *which* of two grouped buttons is displayed
  a correctness question and not a cosmetic one (§4).
- The new field goes in **`CommandButton+0x12E`**, the second three-byte alignment hole, and the
  constructor's `mov byte [esi+0x12C], bl` widened to a dword defaults it — **one byte changed, no
  constructor hook at all**.

## 1. Where the black slot comes from

`0x00944822` is `populateMultiSelect`'s fork. When the selection resolves to a single object it
calls the ordinary single-object populate (`0x00943D6F`) and there is no merge. Otherwise it hides
all 33 slots and walks `TheInGameUI`'s selected-drawable list, calling `0x00944534` once per
drawable with a `first` flag that is set only for the first:

```asm
00944853  call 0x944509                  ; clear [win+0x84] on all 33 slots
00944861  … 0x71552b(TRUE) × 33          ; hide every slot
009448a3  push [ebp-0x14]                ; first?
009448a8  push esi                       ; the Drawable
009448a9  call 0x944534                  ; the merge
009448b8  mov byte [ebp-0x14], 0         ; only the first is "first"
```

`0x00944534` is `thiscall(Drawable *, Bool first)`, `ret 8`. Its prologue puts three things in the
frame that the merge loop then lives off:

```asm
0094453a  mov eax, [ebp+8]               ; the Drawable
00944545  mov [ebp-4], edi               ; the ControlBar
0094454e  mov eax, [eax+0xfc]            ; ->Object
00944556  mov [ebp-0x14], eax            ; <-- the Object
00944559  je  0x944754                   ;     …and it returns if it is NULL
00944572  call 0x69156b                  ; Object::getCommandSetString
0094457a  call 0x71efa2                  ; CommandSetStore::findCommandSet
00944581  mov [ebp-8], eax               ; the CommandSet
009445ad  cmp byte [ebp+0xc], 1          ; first? -> the install pass, else the merge
```

The `first` pass installs each slot's button, requiring `OK_FOR_MULTI_SELECT` — `Options` bit 8,
tested as `test byte [btn+0x1d], 1` at `0x009445DA`.

### The merge loop, `0x009446CA`

`ebx` is the slot index, `esi` the slot's window, `edi` this object's button for the slot, `eax`
the button already installed there, `cl` a flag meaning one of the two is `ATTACK_MOVE`:

```asm
009446d3  mov  ecx, [ebp-8]              ; the CommandSet          <- loop top
009446d7  call 0x80c837                  ; ->getCommandButton(slot) -> edi
009446e2  cmp  dword [edi+0x14], 0xa     ; ATTACK_MOVE?
009446f2  cmp  dword [eax+0x14], 0xa     ;   …either side
00944700  mov  cl, 1
00944704  <install: [esi+0x84] = edi; winHide(eax); winEnable(1); setButton>
0094472c  xor  cl, cl
0094472e  cmp  edi, eax                  ; **pointer identity**
00944730  je   0x94474a                  ;   same button -> keep
00944732  test cl, cl
00944734  jne  0x94474a                  ;   ATTACK_MOVE -> keep
00944736  mov  ecx, [esi]                ; else: clear the slot…
00944738  and  dword [esi+0x84], 0
00944743  push 1
00944745  call 0x71552b                  ;   …and winHide(TRUE)
0094474a  inc  ebx / add esi, 4 / cmp ebx, 0x21 / jl
```

`0x0071552B` is `GameWindow::winHide(Bool)` — `cmp byte [esp+4], 0` — so `1` hides and `0` shows.
`0x009445F4` uses the same pair the same way on the install path, which is what identifies them.

**Nothing weaker than pointer equality is tried.** Two `CommandSet` blocks naming the same button
resolve to the same `CommandButton*` (there is one instance per name in the store), so identical
sets merge perfectly and any single differing slot is lost for the whole selection.

`ATTACK_MOVE` is GUI command `0xA`, read off the `Command` name table at `0x00DA4D10` — the array
`INI::parseCommandType` (`0x0075CB37`) resolves against; `SPECIAL_POWER` at index 24 agrees with
the already-known `GUI_COMMAND_SPECIAL_POWER = 0x18`, which is what anchors the indexing.

## 2. Enablement is a union, and that half already works

`ControlBar::updateContextMultiSelect` (`0x00944911`) runs per frame over the same selected-drawable
list. For each drawable it asks `getCommandAvailability` about every *visible* slot and applies the
verdict to the window immediately (3 → `winHide`, 0/4/8 → `winEnable(0)`, 1/2 → `winEnable(1)`), but
it also counts:

```asm
00944ae7  cmp  edi, 1
00944aec  cmp  edi, 2
00944af1  mov  eax, [esp+0x10]           ; the slot index
00944af5  lea  eax, [esp+eax*4+0x2c]     ; a 33-entry counter on the stack
00944af9  inc  dword [eax]
…
00944b45  cmp  dword [esp+ebp*4+0x2c], ebx   ; count > 0 ?
00944b4d  push 1 / call 0x7154b3             ;   -> winEnable(TRUE)
00944b6e  push ebx / call 0x7154b3           ;   -> winEnable(FALSE)
```

So the final state of a slot is "enabled if **any** selected unit can use it". A button that
survives the merge is therefore already clickable for the units that can still use it, and greyed
only when none can. Nothing in this patch has to touch it.

One consequence worth recording: a verdict of 3 from *any* single member hides the slot for the
whole selection until the next repopulate, because the final pass skips hidden windows
(`0x00944B36`) and only ever enables. `HIDE_WHILE_DISABLED` on a button therefore behaves
order-dependently in a mixed selection — unrelated to this patch, but the same code.

## 3. What the click actually does

`0x00940435` is the click executor. Its multi-select arm walks the selection asking
`getCommandAvailability`, and takes the command as soon as one member answers 1 or 2 (`0x009405B3`).
The `OBJECT_UPGRADE` handler is `0x00940D49`, reached through the two-level switch on
`CommandButton+0x14` (index table `0x00941B63`, jump table `0x00941AC3`). It ends:

```asm
00940e45  call 0x66f492                  ; the player-side legality gate
00940e5a  push 0x415                     ; MSG_DO_OBJECT_UPGRADE
00940e64  push 0                         ;   arg0 = object id: ZERO
00940e6d  push [edi+0x38]                ;   arg1 = the Upgrade's id
```

Zero means the whole selection, exactly as it does for `MSG_DO_SPECIAL_POWER`
(see [`multi-execute-gate`](multi-execute-gate.md) §"Zero means the whole selection"). The logic
side's `0x415` case is `0x0077A6FD`, which resolves the upgrade and calls
`AIGroup::doObjectUpgrade` (`0x0076FBFB`). Its per-member gate is:

```asm
0076fc2a  call 0x66f492                  ; legality: skip this member
0076fc33  cmp  dword [ebx+4], 1          ; Upgrade Type == OBJECT?
0076fc3c  call 0x691421                  ;   Object::hasUpgrade -> skip if it has it
0076fc48  call 0x694914                  ;   Object::canAcceptUpgrade -> skip if it cannot
0076fc65  call [eax+4] / [eax+0xc]       ; queue it on the production update
```

**It never asks whose `CommandSet` the button came from.** A unit that has a module triggered by
the upgrade accepts it, full stop.

That is the constraint the merge rule has to satisfy. Showing a mixed selection the *second-stage*
button would let a battalion still at stage zero take stage two directly — Edain's blades cost 300
for stage one and 200 for stage two, so that is both a skipped prerequisite and 300 gold. Showing
the *first-stage* button is harmless in the other direction: the units that already own it are
skipped by `hasUpgrade` and the ones behind are advanced, which is what a player clicking a mixed
group means.

## 4. Ranking two grouped buttons without a second field

At the mismatch the cave holds `edi` (this object's button), `eax` (the installed button) and, in
`[ebp-0x14]`, **this object**. It does not hold the object the installed button came from — but it
does not need to:

> if this object already owns the installed button's `Upgrade`, this object is past that stage, so
> the installed button is the earlier of the two; otherwise this object is the one behind, and its
> own button is.

`Object::hasUpgrade` (`0x00691421`) answers it — `thiscall`, `ret 4`, NULL-safe on the argument:

```asm
00691421  mov  eax, [esp+4]
00691425  test eax, eax
00691427  jne  0x69142d
00691429  xor  al, al
0069142d  push [eax+0x38]                ; the upgrade's mask
00691430  call 0x68e040
00691435  ret  4
```

The rule converges on the least advanced button in the selection **in any merge order**, which is
what makes it safe to rely on: with three stages A/B/C selected, orders A,B,C and C,B,A and B,A,C
all end on A's button. Where either button has no `Upgrade` (`+0x24 == 0`) there is no stage to
compare and the installed one stands — the first selected unit's, which is what the rest of the bar
already is.

## 5. The field's home

`CommandButton` has two three-byte alignment holes. The first, `+0x10D..+0x10F`, is already spent:
[`queue-ignore-cp`](queue-ignore-cp.md) takes the byte and
[`command-point-cost`](command-point-cost.md) the aligned word. The second is `+0x12D..+0x12F`,
between `TriggerWhenReady` (a `Bool` at `+0x12C`) and `PresetRange` (a `Real` at `+0x130`), and the
constructor proves it is free:

```asm
0075d69c  mov   byte [esi+0x12c], bl     ; TriggerWhenReady = No
0075d6a2  movss [esi+0x130], xmm0        ; PresetRange
0075d6aa  movss [esi+0x134], xmm0        ; AutoDelay
0075d6b2  mov   byte [esi+0x138], bl     ; NeedDamagedTarget
…
0075d721  push 0x1c / lea eax,[esi+0x110] / call memset    ; +0x110..+0x12B
0075d758  push 0x4c / lea eax,[esi+0x13c] / call memset    ; +0x13C..+0x187
```

The `+0x110` memset stops at `+0x12B`, one byte short of `TriggerWhenReady`, and the `+0x13C` one
starts past the hole. No row of the field table at `0x00C2BAC8` names `+0x12D..+0x12F`.

**Nothing zeroes it, so the field has to default itself** — `operator new(0x2E0)`
(`0x0071C439`/`0x0071C446`) hands back uninitialised memory, and a random non-zero group on every
button would merge buttons that collided. The fix costs nothing: `0x88` is `mov r/m8, r8` and
`0x89` is `mov r/m32, r32` over the same ModRM, so `0075d69c` becomes
`mov dword [esi+0x12C], ebx` — **one byte changed, six bytes for six**. `ebx` is the zero the whole
constructor stores from (`xor ebx, ebx` at `0x0075D52A`; the dword store `mov [esi+0x2DC], ebx` at
`0x0075D72B` is the proof all four bytes of it are zero, not just `bl`), so `TriggerWhenReady`
still defaults to `No` and the hole is cleared on the way past. No displaced instruction, no
constructor routine, no cave entry.

+0x12D is left alone, the way +0x10D was, for whatever wants a byte next.

## 6. The edit

One `rel32`, one widened store, the field table rebuilt and its three references repointed, and a
`0x75`-byte cave holding one routine.

The hook is `0x0094472E`, eight bytes and four whole instructions — the identity compare, the
`ATTACK_MOVE` test, and the two branches out of them. Nothing jumps into the middle of it (`xref`
finds branches to `0x0094472E` only, from `0x00944702`), so the window takes a `jmp rel32` and three
`nop`. The cave reproduces both stock tests and dispatches to one of the loop's own three arms:

| arm | VA | what it is |
|---|---|---|
| `KEEP` | `0x0094474A` | the loop's `inc ebx` / `add esi, 4` |
| `HIDE` | `0x00944736` | the stock refusal — clear `[esi+0x84]`, `winHide(TRUE)` |
| `INSTALL` | `0x00944704` | the empty-slot arm — `[esi+0x84] = edi`, `winHide(eax)`, `winEnable(1)`, set the button |

**`INSTALL` is reusable only with `eax` zero.** It passes `eax` straight to `winHide`, which the
empty-slot path can do because `eax` is the NULL it just tested. Re-entering it to *replace* an
installed button means zeroing `eax` first, or the window is hidden rather than shown. That is the
one property of the routine a running game would punish and a structural check would not notice, so
`tests/sage_patch/test_multi_select_group.py` asserts the two bytes before that jump specifically.

`edx` is dead across the whole merge loop and `cl` is dead past its own test, which is what leaves
the routine room to work; the one engine call is bracketed in `pushad`/`popad`, whose `popad` does
not touch EFLAGS, so the answer rides out in the flags.

## What is still unknown

- **Why `ATTACK_MOVE` is exempt.** The edge at `0x009446E2`/`0x009446F2` is real and load-bearing
  (it is the shape the new rule was modelled on), but nothing here explains what it is *for*.
- **Whether `Object::canAcceptUpgrade` (`0x00694914`) could be a cheaper stage test** than
  `hasUpgrade`. Not needed for this rule, so it was left unread.
- **Runtime confirmation.** Everything above is static. The rule is a reading of the machine code
  and the tests are written from the same reading, so a wrong reading passes both; the honest claim
  today is static-verified, not runtime-verified.
