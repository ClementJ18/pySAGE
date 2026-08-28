# Why a scripted act stops advancing until you zoom out and back in

Engine build `2.01.2614.37001`, ImageBase `0x400000`. **Static analysis only** - every claim below
is read off the disassembly of the installed `game.dat`; none of it has yet been confirmed against
the running game, and the root-cause ranking in §5 is explicitly a hypothesis list.

- **Symptom.** In a War of the Ring scripted scenario the campaign stops advancing to the next act.
  Zooming the strategic camera all the way out and all the way back in releases it.
- **What is established.** The act cursor only moves when the living-world *turn phase* reaches 6,
  and the turn phase is gated - in four separate places - on the strategic message-box queue being
  empty and no message box being on screen. A box that is marked "showing" but never dismissed
  freezes the campaign permanently.
- **What is not established.** *Which* box gets stuck, and why the camera round trip clears it.
  §5 ranks the candidates and §6 says which measurement separates them.

## 1. Nothing advances an act except the turn phase

`LivingWorldCampaign::advanceAct` (`0x00932A57`) increments the act cursor at `campaign+0x08`,
clamps it at `campaign+0x18`, and runs the new act through `ACT_RUN`. It has exactly two entries:

| entry | who |
|---|---|
| `0x009333A8` | `LivingWorldCampaign::begin` - the initial jump to act 0 |
| `0x007B973B` | `LivingWorldCampaignManager::advanceAct` (`0x007B970F`) |

and the manager's `advanceAct` has exactly one live caller:

```asm
006bdec7  LivingWorldLogic::endTurn
006bdeca  cmp  dword [esi+0xF4], 6      ; the turn phase
006bded1  jne  006bdf2c                 ; not phase 6 -> do nothing
...       inc  [esi+0xFC]               ; turn number
006bdefe  mov  dword [esi+0xF4], 0      ; phase back to 0
006bdf16  mov  ecx, [0x00DE87AC]        ; TheLivingWorldCampaignManager
006bdf1c  call 007b970f                 ; -> advanceAct
```

The other two branches to `0x007B970F` - `0x006B3383` and `0x006B339C` - are in functions with
**zero** references of any kind (no `call`, no `jmp`, no dword anywhere in the image), i.e. dead
code. `0x006B339C` is the drain of a `TheLivingWorldLogic+0xC8` "advance requested" flag that
nothing ever sets; do not build on it.

So: **act N+1 runs when, and only when, the turn phase reaches 6.** This holds for scripted
campaigns too - `IsScriptedCampaign` removes the End Turn *button*, not the phase machine.
`ForceAdvanceTurnPhase` (`campaign+0x5A`) is read at `0x006BE27E` and simply seeds the
"may advance" flag true each tick, which is what makes a scripted campaign walk its acts by itself.

## 2. The phase machine, and the flag that drives it

`LivingWorldLogic::updateTurnPhase` is `0x006BE20A`, called from `LivingWorldLogic::update`
(`0x006BE50E`) at `0x006BE63B`. Its whole job is to compute one boolean - `bl`, "the phase may
advance" - and act on it:

```asm
006be25e  cmp  byte [esi+0x10A], 0
006be26a  jne  006be3b6              ; an advance is already pending -> drain path, skip
006be27e  mov  bl, [campaign+0x5A]   ; ForceAdvanceTurnPhase seeds it
006be283  call 006b5113              ; ...or this does
006be28e  switch ([esi+0xF4])        ; per-phase condition, may set bl = 1
             1,5 -> 006be35e   2 -> 006be32b   3 -> 006be31a
             4   -> 006be2c6   6 -> 006be2b6 (endTurn)
006be376  lea  eax, [esi+0x154]      ; THE MESSAGE-BOX QUEUE
006be37e  cmp  [eax], [eax+4]
006be381  jne  006be38e              ;   queue not empty -> bl = 0
006be385  call 006b4019              ;   or a box is on screen -> bl = 0
006be38e  xor  bl, bl
006be395  cmp  byte [TheGameLogic+0x11D], 0
006be39e  xor  bl, bl                ; and this clears it too
006be3a0  test bl, bl
006be3a6  call 006b6ba1              ; bl set -> request the advance
```

`0x006B6BA1` is the request: it refuses at phase >= 6, re-checks the preconditions through
`0x006B6ACC`, posts message `0x6A6` onto `TheMessageStream` with `(turn, phase, region)`, and sets
`+0x10A` - "pending". While `+0x10A` is set the phase machine is skipped and `0x006BE3B6` runs
instead, waiting until every army has settled before clearing `+0x10A` and finally incrementing
the phase at `0x006BDF30`.

## 3. The gate: `LivingWorldLogic+0x154` and `+0x160`

Two members of `TheLivingWorldLogic` (`0x00DE4950`) hold the strategic message boxes:

| member | what |
|---|---|
| `+0x154` … `+0x158` | a list of **queued** message boxes, refcounted |
| `+0x160` | the box **currently on screen**, refcounted, or NULL |

and `0x006B4019` is the one-line predicate everything asks:

```asm
006b4019  mov  eax, [ecx+0x160]
006b401f  test eax, eax
006b4021  je   006b402d              ; nothing showing -> false
006b4023  cmp  byte [eax+0x25], 0    ; the box's "is showing" flag
006b4027  je   006b402d
006b4029  mov  eax, 1                ; a box is up -> true, everything waits
```

Four call sites, and every one of them is a brake:

| site | in | effect while a box is up |
|---|---|---|
| `0x006BE385` | `updateTurnPhase` | clears the may-advance flag |
| `0x006B6B06` | `0x006B6ACC`, `requestAdvanceTurnPhase`'s precondition | refuses the request |
| `0x006B56DC` | `0x006B56CC`, the phase 1 / phase 5 predicate | reports "not ready" |
| `0x006B74E3` | `0x006B74D5`, the queue pump | will not start the next box |

The pump is the whole lifecycle in eleven instructions:

```asm
006b74d5  LivingWorldLogic::pumpMessageBoxes
006b74d8  lea  edx, [esi+0x160]
006b74de  cmp  dword [edx], 0
006b74e1  je   006b74f3              ; nothing showing
006b74e3  call 006b4019
006b74ea  jne  006b7508              ; still showing -> RETURN, do nothing else
006b74ee  call 00a110bb              ; done -> release it
006b74f3  lea  eax, [esi+0x154]
006b74fe  je   006b7508              ; queue empty -> nothing to start
006b7503  jmp  006b67b2              ; pop the front into +0x160 and show it
```

Called once per `LivingWorldLogic::update`, at `0x006BE5D7`.

**There is no timeout anywhere in this path.** A box whose `+0x25` stays 1 stalls the campaign for
the rest of the session.

## 4. What the box is, and how `+0x25` is supposed to clear

The box object's vtable is `0x00C7A17C`. Its layout, from its constructor, `show` and destructor:

| offset | what |
|---|---|
| `+0x08`, `+0x0C` | title and body, `UnicodeString` |
| `+0x10` | the APT level id (`APT:_level%u.%s_`, `0x00C8171C`) |
| `+0x14` | the EVA event played with the box |
| `+0x18`…`+0x23` | an optional world position for that EVA event |
| `+0x24` | position valid |
| `+0x25` | **is showing** - the gate byte |
| `+0x26` | finished |

`0x00900CBC` shows one: it registers a completion delegate `{this, 0x00900B6D}` with the strategic
message-box manager `[0x00DEBA1C]` through `0x00953C0B`, sets `+0x25 = 1`, and plays `+0x14` on
`TheEva` (`0x00DE3670`) - positioned at `+0x18` if `+0x24` is set.

The delegate is the only writer that clears the gate:

```asm
00900b6d  cmp  dword [esp+4], 3      ; only event 3 - "dismissed"
00900b72  jne  00900b81              ; every other event: ignored
00900b76  mov  byte [ecx+0x25], 0
00900b7a  mov  byte [ecx+0x26], 1
00900b7e  call [vtbl+8]              ; deliver the result
```

Event 3 is fired from exactly one place - `0x009532A8`, inside
`StrategicMessageBox::hide(notify)` (`0x00953243`), and only when `notify` is non-zero. The manager
is a `StrategicMessageBox` (`0x00C81660`) with button sets `Ok` / `OkCancel` / `YesNo` / `Cancel` /
`NonInteractive` (`0x00C81684`…`0x00C816AC`), driven onto `TheAptPlayer` (`0x00DE3F0C`).

Which gives the failure shape precisely: **the campaign advances only when the player dismisses a
dialog, and the dismissal is the only thing that unlocks it.** If the dialog is never presented,
or is torn off screen without `notify`, the act never comes.

## 5. Candidate root causes, ranked

**(a) The box is shown but its APT level is never pushed.** `0x009532F3` is what actually creates
the dialog on `TheAptPlayer`, and both places that reach it are conditional:

```asm
0095397f  mov  eax, [0x00DE3F0C]     ; TheAptPlayer
00953984  test eax, eax
00953986  je   00953997              ; NULL -> state is set to 2, nothing is drawn
00953988  cmp  byte [eax+0x312], bl
0095398e  jne  00953997
00953992  call 009532f3
```

The manager records "showing" either way, and so does the box (`+0x25 = 1`). The **only** recovery
is `0x00782C56`, which walks the overlay managers - `[0x00DE8A9C]`, `[0x00DEBA1C]`, `[0x00DE9ED0]`,
`[0x00DEA110]` - and re-applies each one's state through `0x009534A0` → `0x009532F3`. That is a
"the strategic screen came (back) up" hook. **A camera round trip that tears the strategic APT
context down and rebuilds it would run exactly this, and would be exactly the observed
workaround.** This is the leading candidate. (`+0x312` is only ever written 0, in the `AptPlayer`
constructor at `0x00624BFF`, so the null check is the live half of the guard.)

**(b) A second box silently replaces the first.** `0x00953861`, the add path, begins with
`if (state != 5) hide(0)` - dismiss the current box **without** notifying. The replaced box's
delegate never fires, `+0x25` stays 1, and `+0x160` holds a corpse forever. `LivingWorldLogic`
serialises its own boxes through `+0x154` so it cannot do this to itself, and the other producer
(`0x0081A4EB`) posts to a *different* manager instance `[0x00DE8A9C]`. Reachable only if some
third path adds to `[0x00DEBA1C]` directly; nothing in the image does. Low.

**(c) A `NonInteractive` box with nothing to dismiss it.** Button set 4 draws no button. If the
authored scenario raises one, whatever was meant to close it must exist; if it does not, the stall
is permanent and camera-independent. Does not explain the workaround on its own, but would explain
the *"sometimes"*.

**(d) Not the message box at all.** Two other brakes sit on the same tick and would produce the
same symptom: `TheGameLogic+0x11D` (`0x006BE395`) forces the flag off, and the whole living-world
tick is skipped at `0x006BE5B2` unless
`distinctOwnersOfLiveArmies(0x006B839A) >= 2 || distinctOwnersOfAllArmies(0x006B83DF) == 1` - a
two-sides-still-standing test that a scripted scenario with two declared players can fail the
moment one side momentarily has no army. Neither is camera-sensitive, so neither fits the
workaround, but both are worth ruling out by reading the live values.

## 6. The measurement that decides it

One `sage_live` read while the campaign is stuck, in this order:

1. `TheLivingWorldLogic+0x160` - non-NULL? Then a box is the cause and (d) is out.
2. `[+0x160]+0x25` - 1 confirms the gate; read `+0x08`/`+0x0C` for the title and body, which names
   the offending box outright.
3. `[0x00DEBA1C]+0x14` - the manager's state. **2 with `TheAptPlayer` non-NULL is candidate (a)
   caught red-handed**: the manager thinks it is showing, the dialog is not there.
4. `TheAptPlayer` (`0x00DE3F0C`) - NULL at the moment the box was added is the mechanism.
5. Then zoom out and back in and re-read: `+0x160` going NULL and the act advancing closes it.

If step 1 comes back NULL, read `TheLivingWorldLogic+0xF4` (phase), `+0x10A` (advance pending) and
`TheGameLogic+0x11D` instead and follow §2 down.

## 7. The scoped patch

Whichever candidate wins, the fix has the same shape and the same single site, because the defect
class is *a gate with no timeout*. The patch is **`living-world-box-watchdog`**:

- **Hook** the queue pump `0x006B74D5` at its entry (5-byte `call` to a cave; the first
  instructions `56 8B F1 8D 96 60 01 00 00` relocate cleanly, and no other patch touches this
  window - checked against `registry.py`).
- **In the cave**, keep a two-dword static: the last-seen `+0x160` pointer and the
  `TheGameLogic+0x40` frame it was first seen at. When `+0x160` is unchanged, `[+0x160]+0x25` is
  still 1, and the box has been up for more than *N* logic frames, call
  `StrategicMessageBox::hide(1)` on `[0x00DEBA1C]` (`0x00953498`) - the notifying path, so the
  delegate fires event 3, `+0x25` clears, `+0x26` sets, the result is delivered through
  `[vtbl+8]` exactly as a player click would, and the pump releases the box on the same tick.
- Reset the static whenever `+0x160` changes or goes NULL.
- *N* is the one knob. It must be long enough that a player reading a dialog is never rushed - a
  minute of logic frames is the right order - and the timer should only run while the dialog is
  **not** actually presented, which is what makes step 3 of §6 load-bearing: if the manager state
  says "showing" and `TheAptPlayer` disagrees, the box is invisible and the watchdog may fire in
  seconds instead of a minute.

Forcing `hide(1)` delivers the box's *default* answer to a `YesNo` / `OkCancel` prompt. For a
`NonInteractive` box that is exactly right. For an interactive one it is a policy choice, and the
reason the watchdog must not fire on a dialog the player can actually see.

**Two cheaper variants**, if the measurement pins candidate (a):

- *Re-arm on show.* Make `0x00953992`'s null-`TheAptPlayer` path record "deferred" and have the
  pump retry `0x009532F3` each tick instead of waiting for `0x00782C56`. Smaller and exact, but it
  needs a spare byte on the manager.
- *Refuse to arm.* Make `0x00900CBC` decline to set `+0x25` when `TheAptPlayer` is NULL, so the box
  stays on the `+0x154` queue and is shown on a later tick. This is the smallest change of the
  three - one conditional at a single site - and is the preferred fix if (a) is confirmed.

## Addresses

| what | where |
|---|---|
| `LivingWorldLogic::update` | `0x006BE50E` |
| ... its living-world-tick gate | `0x006BE57C` / `0x006BE5B2` |
| ... the message-box pump call | `0x006BE5D7` |
| `LivingWorldLogic::pumpMessageBoxes` | `0x006B74D5` |
| ... show the queue front | `0x006B67B2` |
| `LivingWorldLogic::updateTurnPhase` | `0x006BE20A` |
| ... the message-box brake | `0x006BE376` |
| ... the pending-advance drain | `0x006BE3B6` |
| `LivingWorldLogic::endTurn` | `0x006BDEC7` |
| `LivingWorldLogic::advanceTurnPhase` | `0x006BDF30` |
| `LivingWorldLogic::requestAdvanceTurnPhase` | `0x006B6BA1` |
| ... its precondition | `0x006B6ACC` |
| `LivingWorldLogic::isMessageBoxShowing` | `0x006B4019` |
| `LivingWorldCampaignManager::advanceAct` | `0x007B970F` |
| `LivingWorldCampaign::advanceAct` | `0x00932A57` |
| `StrategicMessageBox::show` | `0x009539D3` |
| `StrategicMessageBox::hide(notify)` | `0x00953243`, `0x00953498` |
| `StrategicMessageBox::applyToApt` | `0x009532F3` |
| `StrategicMessageBox::add` | `0x00953861`, `0x00953C0B` |
| the overlay re-show hook | `0x00782C56` |
| the box's `show` / completion delegate | `0x00900CBC` / `0x00900B6D` |
| `TheLivingWorldLogic` message-box queue / current | `+0x154`…`+0x158` / `+0x160` |
| turn phase / turn number / advance-pending | `+0xF4` / `+0xFC` / `+0x10A` |
| the box's is-showing byte | `+0x25` |
| the living-world strategic message-box manager | `0x00DEBA1C` |
| the general message-box manager | `0x00DE8A9C` |
| `TheAptPlayer` | `0x00DE3F0C` |
