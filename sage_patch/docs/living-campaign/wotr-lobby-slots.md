# Why a War of the Ring lobby seats two humans, and the two bytes that lift it

Engine build `2.01.2614.37001`, ImageBase `0x400000`. Static analysis 2026-10-08. **Partly
confirmed live the same day**: five humans seated in one War of the Ring session (read with
`sage_live`). Rows 7-8 have not been looked at. The fix is built as [`wotr-lobby-slots`](../../patches/wotr_lobby_slots.py).

## The symptom

In a multiplayer War of the Ring lobby only one slot besides the host's offers `Open`, so one
other human can join and every other seat can only be an AI. Slots 7 and 8 do not appear at all.

## Not the scenario

`MaxPlayers` is read through `getMaxPlayers` (`0x009758E3`): `Scenario+0x10` in War of the Ring,
the map's player count otherwise. Its callers cap it at 8 (`cmp eax, 8` / `mov eax, 0xC53F2C` /
`jg`, the `std::min` idiom) and use it in two places:

- the start gate, `0x0084355A`-`0x00843571`: more players than the cap, or fewer than
  `MinPlayers` (`0x0097597F`, `Scenario+0x14`), refuses to start;
- the slot-state combo, `0x008417FF`: **in a `HistoricalScenario` only**, a slot at or above the
  cap gets no `Open` row.

Neither counts humans. The freeform scenarios ship with `MaxPlayers = 6` and still seat two humans.

## Rule 1 - the gadget binder hides slots 7 and 8

The game-setup screen's binder (`0x00840906`) files each per-slot window and then, for every one
of them, runs:

```asm
00840a8e  cmp  dword [ebp+0x10], 6     ; the slot
00840a92  jb   0x00840AA3              ; slots 0-5: done
00840a94  cmp  dword [edi+0x7c], 1     ; the screen's mode: War of the Ring
00840a98  jne  0x00840AA3
00840a9a  push 1
00840a9e  call 0x0071552B              ; Window::hide(TRUE)
```

So in War of the Ring every window of slots 6 and 7 (counted from 0) is hidden: the six-seat
ceiling. The windows exist in the movie - they are filed like every other slot's before being
hidden - so nothing is missing for them to show.

## Rule 2 - the slot-state combo offers one `Open` at a time

`fillSlotStateCombo(slot)` at `0x0084160F` (`ret 4`; called from `0x00844F5E`, `0x00845555`,
`0x00846875`) rebuilds a slot's Open / Closed / AI box. Whether it adds `GUI:Open` (`0x00C4E60C`) is
`bl`, seeded from bit 1 of `screen+0x3A4` and then, only in a networked War of the Ring lobby,
replaced by a walk of the other slots:

```asm
00841777  test al, al                  ; [screen+0x58]->vtbl[1]: networked
00841779  je   0x008417DD
0084177b  cmp  byte [ebp-0xe], 0       ; screen+0x7c == 1: War of the Ring
0084177f  je   0x00841820
00841785  test bl, bl
00841787  je   0x008417DD
00841789  cmp  dword [ebp-0x24], 0     ; the GameInfo
0084178d  je   0x008417DD              ; <-- the patched branch
0084178f  mov  dword [ebp-0x20], 1     ; i = 1 (slot 0 is the host)
loop:
          slot = getSlot(i)            ; 0x00800B55
          if slot->state == 0          ; open
              goto found
          if slot->state == 6          ; human (0x008009A7)
              if slot->playerTemplate != -2      ; not an observer (0x00800A1B)
                  bl = 0; goto done
          if ++i < 8 goto loop
          goto done
found:    bl = (i == slot argument)
done:     0x008417DD                   ; the historical MaxPlayers cap
```

`state` is `GameSlot+0x4` (`0` open, `1` closed, `2`-`5` AI, `6` human) and `playerTemplate` is
`GameSlot+0x18`, with `-2` the observer sentinel. Read as a rule:

> **Only the first open slot may stay open, and no slot may be opened once a second non-observer
> human is seated.**

With the host in slot 0 that is one more human, ever: the two-human ceiling. Observers do not
count, which is why a War of the Ring lobby still fills with spectators.

The skirmish and ordinary LAN lobbies never enter the walk (`0x0084177F` jumps past it), so
`bl` keeps its seed there and every slot may be open.

## The patch

Both branches become `jmp rel8` (`0xEB`), keeping their targets:

| site | stock | patched | effect |
|---|---|---|---|
| `0x00840A92` | `72 0F` `jb` | `EB 0F` | the binder never reaches the hide |
| `0x0084178D` | `74 4E` `je` | `EB 4E` | the combo skips the walk, so `bl` keeps its seed, as in every other lobby |

The second lands on `0x008417DD`, which is where the historical cap runs, so a
`HistoricalScenario` still closes the slots from `MaxPlayers` up. Nothing else in the function
changes: the AI rows, the `Closed` row and the "a seated human may be re-opened" arm at
`0x00841835`-`0x00841847` are untouched.

**The INI half.** The start gate still refuses more players than `MaxPlayers`, so a scenario has to
say 8. Edain's two freeform scenarios, `wotrscenario001` and `wotrscenarioClassic`, were raised to
8 on 2026-10-08. The preset-layout scenarios (`007`-`011`) have one `OwnershipSet` per player and
need new layouts, and the two-player historical ones need a faction, a `StartingRestriction` and a
start spot per extra player.

## What else was checked

- **No other War of the Ring branch in the setup screen counts players.** Every read of
  `screen+0x7C` in `0x0083F000`-`0x00848000`, found by a byte-wise decode, was inspected:
  `0x00840566` and `0x008441CE` raise the historical redraw flags, `0x00841D6A` gates the faction
  combo on `isHistoricalScenario`, `0x008440DD` sets `screen+0x3DC`, `0x00846856` is the per-slot
  refresh that calls the combo fill.
- **The LAN join path.** `LAN:ErrorGameFull` (`0x00C04A68`) has no direct reference, and the
  `GameSlot` tests in `0x00985000`-`0x0098D000` are name handling. No War of the Ring test was
  found on the host's side of a join, but the join handler itself **was not traced**.

## How a client gets dropped from a lobby

Read 2026-10-08 while chasing a report of a joiner who showed up in the lobby, vanished, and was
told "Game has already started". The two halves are separate code paths:

- **"Game has already started" is `LAN:ErrorGameGone`**, return code 8 in the LAN error switch at
  `0x00648BA7` (table `0x00648C2A`; the codes match Zero Hour's `RET_*` order, with 6
  `ErrorGameStarted` "Sorry, this game has already started"). The joiner raises it itself only
  when handed no game (`0x0084CB68`, `0x0084CCB9`). The usual source is a **host's denial**:
  the join handler answers reason 8 whenever it is not hosting, and with several instances on one
  machine every one of them answers - see [`multi-instance.md`](../multi-instance.md), fixed by
  [`lan-join-bystanders`](../../patches/lan_join_bystanders.py).
- **Being dropped is the client's own decision.** Every host broadcast goes through
  `0x0084BF0D` (parse, then `LAN_GAME_INFO_PARSE`), after which the client looks for its own
  address in slots 1-7 (`0x00648FDB`-`0x00649007`, stride `0x1DC`, compare `0x0064897C`). A
  broadcast that fails to parse or does not contain it increments `[0x00DE4398]` and the previous
  options are re-applied. At more than 16 in a row (`0x0064902D`), it calls `vtbl+0x94`
  (`0x00649DAB`) with its own name, which leaves the game screen through `0x00847AB2`. A good
  broadcast resets the counter (`0x00649074`).

So "in the lobby for a moment, then gone" is either about 17 host broadcasts in a row that did not
seat the client or could not be parsed, or - with several instances on one machine, the case
measured on 2026-10-08 - a bystander instance's late denial arriving after the host's accept.
Other causes of the first kind: peers running different binaries (any patch that changes the
packed `GameInfo`, such as [`lobby-faction-byte`](../lobby-faction-byte.md), must be on every
machine), or a faction index of 14 or more on stock binaries pushing the colour out of range.

## Open questions for a play session

1. **More than two humans seat - confirmed 2026-10-08** with five instances on one machine (three
   seated at once before `lan-join-bystanders`, five on an earlier run). The host's join handler
   (`0x0098A7F1`, see [`multi-instance.md`](../multi-instance.md)) has no War of the Ring rule.
2. **Do rows 7 and 8 lay out correctly?** The War of the Ring lobby movie may put something
   (the map preview) where the stock layout never showed those rows.
3. **The strategic layer with 7-8 players.** Its player vector is dynamic (`LivingWorldLogic+0x8C`)
   and the turn logic counts humans generically (`0x006B5E3E`), but no fixed-size per-player array
   was looked for. The battle side has two known limits that 8 players will hit more often: the
   War of the Ring battle map measured in [`mp-battle-participation.md`](mp-battle-participation.md)
   declares `Player_1`-`Player_4`, and a region holds four hero armies
   ([`hero-army-slot-overflow.md`](hero-army-slot-overflow.md)).
4. **Battles without every human in them** auto-resolve stock; play with
   [`wotr-battle-observers`](../../patches/wotr_battle_observers.py).

## Addresses

In [`../../addresses/ui.py`](../../addresses/ui.py):

| name | VA |
|---|---|
| `MP_SETUP_GADGET_WOTR_SLOT_TEST` / `_JB` | `0x00840A8E` / `0x00840A92` |
| `MP_SETUP_SLOT_COMBO` | `0x0084160F` |
| `MP_SETUP_SLOT_COMBO_WOTR_OPEN_GATE` / `_JE` | `0x00841789` / `0x0084178D` |
| `MP_SETUP_SLOT_COMBO_WALK_DONE` | `0x008417DD` |
