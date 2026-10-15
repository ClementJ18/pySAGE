# Asking about the unit that was requested, not its equivalent

The reverse-engineering behind
[`patches/ai_equivalent_build_gate.py`](../patches/ai_equivalent_build_gate.py). ROTWK `game.dat`
build `2.01.2614.37001`, ImageBase `0x400000`, recovered statically 2026-10-13, with the symptom
read live the same day from six Edain skirmishes with a Brutal Imladris AI. **Not yet played with
the patch applied.**

## TL;DR

- `BuildAssistant::canMakeUnit` (`0x00794F38`) accepts a producer when one of its build buttons
  names a template that is `EquivalentTo` the wanted one, and then asks the player whether it
  may build **the button's** template.
- `ProductionUpdate::update` asks, every frame, whether the player may build **the queued**
  template, and adds no progress while the answer is no.
- When the two templates differ and a script has disallowed only the wanted one, the gate says
  yes, the unit is queued, and it sits at 0% for the rest of the match with everything behind it.
- The fix is eight bytes at **`0x007950BD`**: push the wanted template (`[ebp+0xc]`) instead of
  fetching the button's. Identical whenever the two are the same template.

## 1. The symptom

Six skirmishes, each with a Brutal Imladris AI. In all six the AI's first `ImladrisBarracks` took
one or two ordinary battalions and then showed, for the rest of the match:

```
1x ImladrisBarracks    ImladrisWaffenmeisterLastAllianceHorde 0%
```

(`BruchtalLanzerLastAllianceHorde` in three of the six), with 2,000-2,500 in the bank and command
points free. That barracks never trained again; the AI recovered only as far as building a second one. Read
with
`tools/live/production_monitor.py` in pySAGE-edain.

## 2. Three facts that only fail together

**The AI may ask for either twin.** Edain's `ArmyDefinition` for Imladris lists both
`ImladrisWaffenmeisterHorde` and `ImladrisWaffenmeisterLastAllianceHorde` (and three more such
pairs). The stock barracks `CommandSet` carries a button for the first; the Last Alliance sets,
switched in by `Upgrade_MenWallTower`, carry a button for the second.

**A script disallows one of them.** `ki imladris spellbook` opens with

```
<This Player> allowed to build ImladrisWaffenmeisterLastAllianceHorde is FALSE.
```

for all five Last Alliance battalions, and sets them back to TRUE when the AI is granted
`SCIENCE_LastAlliancePassive`. `Player::isBuildableTemplate` (`0x006AC856`) answers from a set of
template ids on the `Player` (`+0x720`); that the script action is what fills it is inferred from
the behaviour, the write was not traced:

```asm
006ac885  mov  ax, [eax+0x5e8]            ; the template's id
006ac88d  mov  esi, [ecx+0x720]           ; the player's disallowed set
006ac8a2  call 0x6ac5d0                   ; find
006ac8ac  cmp  [eax], esi                 ; == end() ?
006ac8af  sete cl                         ; buildable iff it is not in the set
```

**The two are `EquivalentTo` each other.** Edain declares that so both kinds select together
when a player gathers units to use an ability. Before the declaration the barracks had no button that matched a Last Alliance
request, `canMakeUnit` said no, and the AI's order was skipped - the script's flag never
mattered, because nothing got that far.

## 3. The gate asks about the wrong template

`canMakeUnit(producer, what, reviveIndex)` walks the producer's `CommandSet`. For a
`UNIT_BUILD`-family button it tests equivalence, not identity:

```asm
00795011  push [ebp+0xc]                  ; what
00795014  mov  ecx, esi                   ; the button
00795016  call 0x75d1dc                   ; CommandButton::getThingTemplate
0079501b  mov  ecx, eax
0079501d  call 0x73d5c2                   ; ThingTemplate::isEquivalentTo(what)
00795022  test al, al
00795024  je   0x7950df                   ; next slot
```

and once the button's upgrade requirements pass, the accept path at `0x007950AD` asks the
player about the button's template:

```asm
007950ad  mov  ecx, [ebp+8]               ; producer
007950b0  call 0x68b678                   ; Object::getControllingPlayer
007950b5  cmp  byte [ebp-1], 0            ; a revive?
007950b9  mov  ebx, eax
007950bb  jne  0x7950ee
007950bd  mov  ecx, esi                   ; the button           <- the site
007950bf  call 0x75d1dc                   ; getThingTemplate
007950c4  push eax
007950c5  mov  ecx, ebx
007950c7  call 0x6ac927                   ; Player::canBuild(template)
```

`Player::canBuild` (`0x006AC927`) is `isBuildableTemplate`, then the template's `Buildable`
status, then its `Prerequisites`. With an ordinary barracks and a Last Alliance request it is
asked about `ImladrisWaffenmeisterHorde`, which is allowed.

## 4. Production asks about the right one

`ProductionUpdate::update`, on the head of the queue (derived in
[`queue-ignore-cp.md`](queue-ignore-cp.md)):

```asm
008a1e27  push [ebx+8]                    ; the entry's own ThingTemplate
008a1e2a  mov  ecx, [ebp-0x28]            ; the controlling Player
008a1e2d  call 0x6ac856                   ; Player::isBuildableTemplate
...
008a1e56  test al, al
008a1e58  jne  0x8a2f0e                   ; not buildable: stall silently
```

The entry holds the template the AI asked for. It is in the disallowed set, so the frame's
progress is never added, and in the matches watched nothing removed the entry.

## 5. The patch

```
007950bd  ff 75 0c     push dword [ebp+0xc]   ; what
007950c0  90 90 90 90 90
007950c5  8b cb        mov  ecx, ebx          ; unchanged from here
007950c7  e8 ..        call Player::canBuild
```

- `[ebp+0xc]` is non-null here: the path is reached only through the template branch, where it
  was the argument of `isEquivalentTo`, which answers no for a null. The revive branch leaves at
  `0x007950BB`.
- One push replaces one push, so `canBuild`'s `ret 4` balances as before. `esi` and `eax` are
  not read again before the function returns.
- When the button's template *is* the wanted one - every click a player makes, and every AI
  order for a unit with a button of its own - the argument is the same pointer or an override
  of the same template, and nothing changes.
- When they differ, the gate now reports what production will do. A disallowed twin is refused
  and the AI's order takes the pump's ordinary "cannot start" path; an allowed one that has no
  button of its own (Edain's `AngmarGrabunholdLvl2`..`Lvl5`, reached through `AngmarGrabunhold`)
  is accepted exactly as before.

One behaviour does change beyond the stall: a template reached only through an equivalent
button is now also held to its own `Buildable` status and `Prerequisites`, where before it
borrowed the button's. No Edain object declares `Prerequisites`.

## 6. What it does not do

After the AI is granted Last Alliance the barracks carries only the Last Alliance buttons, and
an order for the ordinary twin matches them through equivalence. Both are allowed by then, so
the order should be accepted and an ordinary battalion come out of a Last Alliance barracks. That
is the stock behaviour, unchanged by the patch, and has not been watched in a game.

## Addresses

| VA | what |
|---|---|
| `0x00794F38` | `BuildAssistant::canMakeUnit`, vtable `0x00C307D8` slot `+0x68` |
| `0x0079501D` | its `call ThingTemplate::isEquivalentTo` |
| `0x007950AD` | its accept path |
| `0x007950BD` | **the site**: `mov ecx, esi` / `call getThingTemplate` / `push eax` |
| `0x007950C5` | `mov ecx, ebx` / `call Player::canBuild` |
| `0x006AC927` | `Player::canBuild(template)`, `ret 4` |
| `0x006AC856` | `Player::isBuildableTemplate(template)`, `ret 4`; disallowed set at `Player+0x720` |
| `0x008A1E2D` | `ProductionUpdate::update`'s per-frame call of it on the queue head |
