# Binding a REVIVE button to a hero by `Object`

The RE behind [`patches/revive_object_binding.py`](../patches/revive_object_binding.py). ROTWK
`game.dat` build `2.01.2614.37001`, ImageBase `0x400000`, recovered statically 2026-10-01. **Not yet
run in a game.**

## TL;DR

- Stock, a `REVIVE` button's hero is decided by **position** in three separate walks: the
  ControlBar's pass 1 (`REVIVE` ordinal n → roster hero n), its pass 2 (each unclaimed ledger entry
  → the next free `REVIVE` button), and `BuildAssistant::canMakeUnit` (accept once `reviveIndex`
  `REVIVE` buttons have been counted). None of them reads the button's `Object`.
- So a building that offers the eighth hero carries eight `REVIVE` buttons and disables seven with
  an upgrade it can never own ([`hero-recruitment.md`](hero-recruitment.md) §3).
- The patch makes `Object` mean the hero. A `REVIVE` button with `Object = X` is bound in pass 1 to
  `ledger.findEntry(X)`, skipped by pass 2, and accepted by `canMakeUnit` only for that ledger
  index, through the button's `NeededUpgrade` gate. Bound buttons take no positional ordinal and no
  positional count, so bound and unbound buttons can share a set.
- Three hooks and one 279-byte cave (`.revobj`). Composes with `commandset-limit` and
  `ai-revive-gate`, which also edit `canMakeUnit`.

```ini
CommandButton Command_ReviveBeregond
    Command       = REVIVE
    Object        = GondorBeregond
    ButtonImage   = HIBeregond
    ButtonBorderType = ACTION
End
```

A `GondorBarracksCommandSet` that offers Beregond and Boromir then needs two `REVIVE` buttons, not
fourteen.

## 1. The `Object` field

`CommandButton` field-parse table (`explore.py block CommandButton`): `Object` is `+0x20`, parsed by
`0x0073AD1F`. The field holds a **handle**, not the template: `CommandButton::getThingTemplate`
(`0x0075D1DC`) follows it to the template's final override (`0x00465AF4` walks `[x+4]`) and, when the
template table was reloaded since (`[tmpl+0x5E8]` against `[0x00DA4EE8]`), looks it up again by name.
So the cave calls the getter, as `canMakeUnit`'s unit branch already does at `0x00795016`.

The getter is `__thiscall` with no arguments and a plain `ret`, keeps `esi`, and clobbers `eax`,
`ecx` and `edx`.

## 2. Matching a template to a ledger entry

`ReviveMgr::findEntry(ThingTemplate *what, Int id, Int ordinal)` (`0x0078131E`, `ret 0xC`) on the
ledger at `Player+0x758` compares `what+0x64` (the template's name) against each entry's name at
`+0xE4`. With `id == -1` it returns the index of the `ordinal`-th entry of that name, or -1.
Pass 1 calls it this way at `0x0094401B`.

Matching by name rather than by pointer is what makes an override, or a map-scoped redefinition,
find the entry its base filed. The patch always asks for ordinal 0, the first entry of that name.
A ledger holding two entries with the same template name would reach only the first through a bound
button. No stock roster does this.

## 3. Pass 1: `0x00943F97`

Per visible slot, inside `ControlBar::populate`'s second range loop (`CONTROL_BAR_RANGE_LOOP_REVIVE`).
`esi` is the button, `edi` the widget slot, `ebx` the ControlBar. The frame:

| slot | what |
|---|---|
| `[ebp-0x1c]` | the selected object's player |
| `[ebp-0x20]` | the `REVIVE` ordinal - the roster position the next button gets |
| `[ebp-0x28]` | the roster template, then the ledger entry |
| `[ebp-0x60]` | a `map<ThingTemplate*, int>` of how often each roster template has been seen |
| `[ebp-0x84]` | 33 used-ledger-index flags, cleared at `0x00943F03`, read by pass 2 |

```
00943f97  cmp  [esi+0x14], 0x2e            ; REVIVE?
00943fb4  call 0x6a8803                    ; local player may see this producer's heroes?
00943fbb  jne  0x943fd6                    ;   no: hide, inc [ebp-0x20], next slot
00943fd6  push [ebp-0x20]                  ; <- hook (11 bytes)
00943fd9  mov  ecx, [ebp-0x1c]
00943fdc  call 0x6ab249                    ; getBuildableHeroName(ordinal)
00943fe1  mov  [ebp-0x28], eax
...                                        ; occurrence count of that template -> edi
0094401b  call 0x78131e                    ; ebx = findEntry(tmpl, -1, occurrence)
0094402e  call 0x781298                    ; [ebp-0x28] = getEntry(ebx)
00944039  call 0x780c2f                    ; edi = getTemplate(ebx)
00944044  je   0x9440bd                    ; no entry or no template: unbound
00944050  call 0x5ff924                    ; campaign / Living World?
00944057  jne  0x9440bd                    ;   yes: unbound - pass 2 binds everything there
00944059  push [ebp-0x28]                  ; BIND
0094405c  mov  ecx, esi
0094405e  mov  byte [ebp+ebx-0x84], 1      ;   claim the ledger index (unguarded)
00944066  call 0x75d3bc                    ;   button <- entry
...                                        ;   hero's display name -> button+0x7c
009440ac  mov  [esi+0xc0], ebx             ;   the ledger index the click will queue
009440bd  or   [esi+0xc0], -1              ; UNBOUND
009440c4  inc  [ebp-0x10]
009440c7  inc  [ebp-0x20]                  ; every path ends here: next ordinal
```

The hook replaces the roster lookup. For a button with no `Object` the cave runs the three displaced
instructions and resumes at `0x00943FE1`. For a bound button it:

1. pre-decrements `[ebp-0x20]`, so the tail's `inc` leaves the ordinal where it was and the next
   unbound button gets the roster position this one would have taken;
2. computes `ebx = findEntry(Object, -1, 0)`, `[ebp-0x28] = getEntry(ebx)` and `edi = getTemplate(ebx)`,
   leaving through `UNBOUND` when any is missing, which is the stock state of a fielded hero;
3. claims `used[ebx]` when `ebx < 33`. The stock store at `0x0094405E` has no bound check, and the
   cave does not copy that;
4. pushes the entry, sets `ecx` to the button, and enters `BIND` on its `call` (`0x00944066`).

Entering past `0x00944050` is deliberate. In a campaign or Living World game stock pass 1 binds
nothing, and pass 2 hands out ledger entries in order. A bound button means the same hero in every
game mode, so it binds there too.

## 4. Pass 2: `0x0094428F`

The third range loop (`CONTROL_BAR_RANGE_LOOP_PRODUCTION`) walks slots `0 .. min(ledgerSize,
rangeCount)` (all of `rangeCount` in campaign). It holds a running ledger index in `[ebp-0x10]`:
each `REVIVE` button either finds that index already claimed (`0x009442BB`) or is bound to it. Either
way the index advances.

```
0094428f  cmp  [esi+0x14], 0x2e            ; <- hook (10 bytes)
00944293  jne  0x944362                    ; not REVIVE: next slot
00944299  ...                              ; campaign NEED_UPGRADE skip, then claim-or-bind
00944362  mov  ecx, [ebp-0x38]             ; next slot (reloads everything)
```

The cave sends a bound `REVIVE` button to `0x00944362`. Stock, pass 2 would otherwise overwrite a
pass-1 binding whenever the running index at that button was unclaimed, which is how a positional
set comes to show a hero other than the one its slot was meant for. A bound button is not counted,
so it does not advance the running index either.

Pass 2's slot bound is `min(ledgerSize, rangeCount)` slots of the visible range, counted over
*every* slot, bound ones included. In a set that mixes bound and unbound buttons, bound buttons
placed early in the range shorten pass 2's reach over the unbound ones. Pass 2 matters for heroes
the roster never names (script-granted heroes, a dominated hero; see
[`hero-revive-ownership.md`](hero-revive-ownership.md) §2). To keep offering those, place the spare
unbound `REVIVE` slots before the bound ones.

## 5. `canMakeUnit`: `0x00794FF1`

The order a click sends carries the ledger index from `+0xC0`, and `ProductionUpdate::queueCreateUnit`
asks `BuildAssistant::canMakeUnit(producer, NULL, index)` before it queues
([`ai-revive-gate.md`](ai-revive-gate.md)). Stock, the revive branch accepts on the `index`-th
`REVIVE` button. A set of two bound buttons can never count to Beregond's index 7, so every bound
recruit would be refused unless this branch changes too.

```
00794fdc  push [ebp-8] / call getCommandButton(slot) -> esi
00794ff1  cmp  byte [ebp-1], 0             ; <- hook (10 bytes): isRevive
00794ff5  jne  0x7950ce                    ;   REVIVE_BRANCH
00794ffb  mov  eax, [esi+0x14]             ; the template branch
...
0079502a  UPGRADE_GATE                     ; NeededUpgrade / NeededUpgradeAny
007950ad  ACCEPT                           ; -> player->reviveMgr->canRevive(index)
007950ce  cmp  [esi+0x14], 0x2e / jne NEXT ; REVIVE_BRANCH (ai-revive-gate hooks here)
007950d4  cmp  [ebp-0xc], [ebp+0x10] / je ACCEPT
007950dc  inc  [ebp-0xc]                   ; BUMP
007950df  inc  [ebp-8]                     ; NEXT
```

The hook takes the `isRevive` split one step before the revive branch. Unit questions resume at
`0x00794FFB` unchanged. A non-`REVIVE` or unbound button jumps to `0x007950CE`, which is the stock
count or `ai-revive-gate`'s cave, whichever is installed. A bound button goes to `UPGRADE_GATE`
when `findEntry(Object)` on the producer's controlling player's ledger equals `reviveIndex`, and to
`NEXT` otherwise, so it is never counted.

Routing a match through `UPGRADE_GATE` means a bound button's `NeededUpgrade` is enforced for every
caller, player and AI alike, instead of only on the ControlBar's display. `ai-revive-gate` could
not do this for positional buttons, because the button the count lands on is not the button the
player saw. For a bound button they are the same button. One consequence is that a bound recruit
the interface would refuse is refused by the engine too. That closes the hole in
[`hero-recruitment.md`](hero-recruitment.md) §4 for bound buttons.

Registers: `ebx` and `edi` are scratch at this point in the loop (`UPGRADE_GATE` zeroes both and
`ACCEPT` reloads the producer from `[ebp+8]`). The cave still uses only `eax`, `ecx` and `edx`.

## 6. Other `REVIVE` readers

`explore.py` finds five sites that compare a command type against `0x2E` ([`ai-revive-gate.md`](ai-revive-gate.md)):

| site | what | effect of the patch |
|---|---|---|
| `0x00943F97`, `0x0094428F` | pass 1, pass 2 | hooked (§3, §4) |
| `0x007950CE` | `canMakeUnit` | preceded by the §5 hook |
| `0x008083F2` | tooltip builder | reads `+0xC0`, so it describes the bound hero |
| `0x00697B19` | an "execute the n-th REVIVE button" helper, called only from an `AIGroup` routine (`0x0076FF1C`) | counts every `REVIVE` button positionally, bound ones included, then dispatches with that button's `+0xC0`. Unchanged, and so as positional as before |

`Object::doCommandButton`'s revive case (`0x006973D3`) queues `+0xC0` directly, so a click on a
bound button orders the bound hero.

## 7. What is still open

- **Not run in a game.** The tests emulate each routine against stubbed helpers. They check exits,
  registers, the frame and the stack, which is the patch's reading of the engine, not the engine.
- **Whether the ControlBar's enabled state reads `canMakeUnit`.** If it does, a bound button whose
  `NeededUpgrade` is unmet is greyed by both, which matches stock `NeededUpgrade` semantics. If a
  path instead hides buttons that `canMakeUnit` refuses, such a button would vanish instead of
  greying.
- **Ledger entries with the same name.** Only the first is reachable through a bound button (§2).
