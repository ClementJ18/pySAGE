# Two buttons sharing a slot in a mixed selection — reverse-engineering notes

The RE behind [`patches/multi_select_group.py`](../patches/multi_select_group.py). ROTWK
`game.dat` build `2.01.2614.37001`, ImageBase `0x400000`, no ASLR, recovered statically 2026-08-30.

**Status: built** as `multi-select-group`, applying and verifying against the real binary and
against a synthetic stand-in, and composing with `command-point-cost` and `queue-ignore-cp` in
any order. **Static-verified only — not yet runtime-verified in game.**

Three behaviours, four hooks: the slot survives a mixed selection (§1, §6); the button shown is one
something can actually click (§2, §7); and one click starts every stage in the group, each on the
units that are at it (§3, §8).

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
- **One click reaches every stage without a second message.** `AIGroup::doObjectUpgrade` carries the
  message's upgrade in `ebx` for the whole member loop, and `[ebp+8]` keeps the original argument;
  rewriting `ebx` per member from that member's *own* command set makes every downstream check —
  legality, `hasUpgrade`, `canAcceptUpgrade`, the production queue — run on the right upgrade with
  no further edits (§8).

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

**That is the hazard, and it is why §8 exists.** Left alone, showing a mixed selection the
*second-stage* button would let a battalion still at stage zero take stage two directly — Edain's
blades cost 300 for stage one and 200 for stage two, so that is a skipped prerequisite and 300 gold.
Choosing which button to display carefully would hide the hazard rather than remove it; §8 removes
it, by making the member loop resolve the upgrade per member instead.

It is also the mechanism the second half of this patch is built on. Since a click already reaches
the whole selection and is already filtered per member, "start every stage in the group" needs no
extra message and no extra order — only a different answer to *which upgrade this member is being
offered*.

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

The rule converges on the least advanced button in the selection **in any merge order**: with three
stages A/B/C selected, orders A,B,C and C,B,A and B,A,C all end on A's button. Where either button
has no `Upgrade` (`+0x24 == 0`) there is no stage to compare and the installed one stands — the
first selected unit's, which is what the rest of the bar already is.

Since §8 makes the click correct whichever button is displayed, this is a **display preference**,
not a safety property: it puts the icon and tooltip on the stage most of the selection is about to
buy.

### The rule the stage tie-break defers to

A button no selected unit can click makes the slot unclickable, and then the click expansion never
fires — so usability outranks stage. The merge asks
`ControlBar::getCommandAvailability` (`0x00942733`, verdicts 1 and 2) about each candidate, passing
a **NULL window**, which the click executor also does at `0x009405B0`, so no window pointer has to
be found or tested.

The awkward half is the *installed* button: the object that installed it is long gone by the time a
later object disagrees, and asking a different object is asking a different question. So the answer
is accumulated instead — a **33-byte record, one byte per slot**, saying whether anything in this
selection has been able to use what is currently in that slot:

| site | what it does to the record |
|---|---|
| `0x00944853` (§6) | zeroed, once per repopulate |
| `0x009445E8` (§7) | the first object's verdict on its own button |
| `0x0094472E` | union in each later object's verdict; reset to the new verdict when the slot is replaced |

Ordering then falls out: exactly one usable → that one; both or neither → the stage rule above.
The record is why the first object's install needs a hook of its own: without it the merge would
never learn that object's opinion of its own button, and a slot only *it* could use would look dead
to the very first object merged after it.

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

## 6. The merge edit

Four `rel32`, one widened store, the field table rebuilt and its three references repointed, and a
cave holding four hook routines and five helpers. The section is **writable**, unlike
`command-point-cost`'s, because the per-slot record lives in it.

The first hook is `0x0094472E`, eight bytes and four whole instructions — the identity compare, the
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
the routine room to work; the `hasUpgrade` call is bracketed in `pushad`/`popad`, whose `popad` does
not touch EFLAGS, so the answer rides out in the flags. Once the pair is known grouped the routine
takes a two-dword frame — the installed button, which every call clobbers out of `eax`, and this
object's verdict on the new one — and every exit past that point drops it.

## 7. The other two ControlBar hooks

**The reset, `0x00944853`.** The per-slot record has to be cleared once per repopulate, and
`0x00944509` — which clears `[win+0x84]` on all 33 slots — has **exactly one caller**, this one. So
the `call` becomes a `call` into the cave, which zeroes the record and then `jmp`s to the helper,
leaving it to return to the engine's own caller. `ecx` is the `ControlBar` for that thiscall and is
untouched.

> ⚠ **A displaced `call` is not a displaced instruction like any other, and this one bit.** The
> first build of this patch reached the routine with a `jmp`, the way the other three hooks are
> reached — so the helper's `ret` popped a value that had never been a return address, and the game
> crashed on the first multi-select. Two shapes work and they are not interchangeable:
>
> | site reached by | the routine must |
> |---|---|
> | `call` | end in a `jmp` to the callee, letting **its** `ret` return past the site |
> | `jmp` | reproduce the `call` itself, then `jmp` to the resume point |
>
> [`cooldown-through-death`](cooldown-through-death.md) takes the second shape at its own displaced
> call; this one takes the first. `tests/sage_patch/test_multi_select_group.py` now derives the
> required opcode from the site's own **stock first byte** rather than from a table, so the two can
> no longer disagree — and the write-up saying "call" while the code emitted `jmp` is exactly the
> disagreement that shipped.

**The first object's install, `0x009445E8`.** Six bytes, one whole instruction
(`mov [edi+0x84], ebx`), and nothing branches into it. Two things are live across it and both have
to be put back:

```asm
009445e4  mov  ecx, [edi]          ; the window — live to the winHide at 0x009445F4
009445e6  cmp  ecx, esi            ; the flags the je at the resume point reads
009445e8  mov  [edi+0x84], ebx     ; <-- displaced
009445ee  je   0x9446b5
```

`popad` restores `ecx` and leaves EFLAGS alone, so the routine re-issues the `cmp` rather than
assuming the flags survived a call. The slot index in that loop is `[ebp+8]` — the `Drawable`
argument slot, reused as the counter at `0x009445B7` and `0x009446B5` — and `[ebp-0x14]` still holds
the `Object`.

## 8. Making one click start every stage

`AIGroup::doObjectUpgrade` keeps the message's upgrade in `ebx` for the whole member loop:

```asm
0076fc00  mov  ebx, [ebp+8]           ; the UpgradeTemplate — set once
…
0076fc15  mov  edi, [esi+8]           ; <-- the member, and the loop's back-edge target
0076fc18  push 0
0076fc1a  push edi
0076fc1b  push ebx                    ; every gate below reads ebx
```

**`[ebp+8]` is never written**, so a hook at the loop's top can rewrite `ebx` per member and still
re-derive the message's own upgrade on the next pass. Six bytes, three whole instructions, and
`0x0076FC15` is where the back-edge lands so the window starts exactly there.

The resolver answers *what should this member be offered*:

1. if the member's own effective command set already has a button buying the message's upgrade, it
   is at the right stage — return it unchanged, which is also every ungrouped case;
2. otherwise find the message upgrade's group, by walking the **selection** for whichever member
   *does* name it — the click came from one of them;
3. return the upgrade of the member's own button in that group, or the message's if it has none.

The walk is the object → command set → button chain `multi-execute-gate` uses —
`Object::getCommandSetString` (`0x0069156B`, the *effective* set, so a `CommandSetUpgrade` swap is
what it sees) → `findCommandSet` (`0x0071EFA2`) → `getCommandButton` (`0x0080C837`), all three
`ret`-cleaning their own arguments and preserving `ebx`/`esi`/`edi`.

Everything downstream then runs on the right upgrade with no further edits: the legality gate,
`hasUpgrade`, `canAcceptUpgrade` and the production queue all read `ebx`. One click on the shared
slot starts stage one on the battalions at stage zero and stage two on the battalions at stage one,
each paying its own price, with **no change to the message and nothing extra emitted**.

It also closes §3's hazard structurally: a member is only ever offered a button from its own set, so
no display choice can produce a stage skip.

**This is the one part that is not client-side.** It changes which upgrade a logic-side order
delivers to which object, so every peer must run the same patched binary and replays do not cross —
the same caveat `multi-execute-gate` carries, and for the same reason.

## What is still unknown

- **Why `ATTACK_MOVE` is exempt.** The edge at `0x009446E2`/`0x009446F2` is real and load-bearing
  (it is the shape the new rule was modelled on), but nothing here explains what it is *for*.
- **Whether `Object::canAcceptUpgrade` (`0x00694914`) could be a cheaper stage test** than
  `hasUpgrade`. Not needed for this rule, so it was left unread.
- **The 33-slot bound is hardcoded** in the resolver's walks and in the record's size, where
  `multi-execute-gate` reads its bound out of the image so `commandset-limit` can raise it. The
  ControlBar only ever *draws* 33 and a unit's palantir only six, so a grouped button past slot 33
  cannot be displayed or clicked — but a mod that put one there would not have it found. Raising
  this means a `slots` parameter and the ordering constraint that comes with it.
- **What a repopulate costs now.** The merge asks `getCommandAvailability` up to twice per
  mismatched grouped slot, and the resolver walks the selection once per member per click. Both are
  event-driven rather than per-frame, and neither has been measured.
- **Runtime confirmation.** Everything above is static. The rules are a reading of the machine code
  and the tests are written from the same reading, so a wrong reading passes both; the honest claim
  today is static-verified, not runtime-verified. The two things a live test would settle first are
  whether re-entering `INSTALL` really refreshes the button's image rather than leaving a stale
  icon, and whether the per-member rewrite charges each unit its own upgrade's price.
