# Summoning powers greyed at `MaxSimultaneousOfType`

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR), read from the
repo's `game.dat`, which `sage-patch sagepatch` reports as carrying only `cah-factions` (nowhere
near these sites).

- **Cost:** two `jmp` hooks (5 and 9 bytes) and a `.spcap` cave with three routines. No structure
  grows and no INI keyword is added: the patch gives the existing `CommandButton` `Object` field
  a meaning on `SPECIAL_POWER` buttons.
- **Risk:** low. The cave only turns a stock "available" into "unavailable", or a stock click into
  a refused one, and only for a `SPECIAL_POWER` button whose `Object` declares a cap the player
  has reached.
- **Status:** static-verified and emulated: the cave runs under Unicorn over the patched real
  `game.dat` (`tests/sage_patch/test_special_power_object_cap_emulated.py`). Not yet seen in a
  running game.

```
sage-patch apply special-power-object-cap --in game.dat.backup --out game.dat
```

```ini
CommandButton Command_SummonEnts
    Command      = SPECIAL_POWER
    SpecialPower = SpellBookSummonEnts
    Object       = ElvenEnt        ; greyed while the player has MaxSimultaneousOfType ElvenEnts
    ...
End
```

## The complaint

A permanent summon with `MaxSimultaneousOfType` (Edain uses this a lot) can be cast with the cap
already reached. The cast goes through and the recharge is spent, but nothing appears.

## Why

The cap is enforced in exactly one place, the OCL `CreateObject` nugget, after the template has
been looked up by name (`THING_FACTORY_FIND_TEMPLATE` at `0x005F11F4`, kept in `[ebp-0x18]`):

```
005f120b  call 0x68b678               ; Object::getControllingPlayer(source) -> [ebp-0x38]
005f1238  call 0x6a7f79               ; enough command points? (skipped by IgnoreCommandPointLimit)
005f1250  cmp  word [eax+0x5f0], 0    ; MaxSimultaneousOfType
005f1258  je   0x5f12b6               ;   none: create
005f125a  push 0 / lea eax,[ebp-0x78] / push eax / push esi(1) / lea eax,[ebp-0x18] / push eax / push esi(1)
005f1266  call 0x6abaf7               ; Player::countObjectsByThingTemplate
005f126e  movzx ecx, word [eax+0x5f0]
005f1275  cmp  [ebp-0x78], ecx
005f1278  jb   0x5f12b6               ;   count < max: create
005f127a  ...                         ; otherwise: nothing, silently
```

`+0x5F0` is the `UnsignedShort` `MaxSimultaneousOfType` (parse fn `0x0042EC11`,
`docs/ini-types.json`). `0x006ABAF7` is `Player::countObjectsByThingTemplate(count, templates,
ignoreDead, counts, ignoreUnderConstruction)`: `__thiscall`, `ret 0x14`, a walk of the player's
teams (`[player+0x34c]`) through `Team::countObjectsByThingTemplate` (`0x007A1714`). It zeroes
`counts` first, so the caller needs no initialisation.

Nothing on the button side looks at `+0x5F0`. The `SPECIAL_POWER` arm of
`ControlBar::getCommandAvailability` asks about sciences, levels, the power's module and model
conditions, and `doCommand` asks only `isReady`.

## The patch

One shared routine, `capped(button, player)` (`stdcall`, `ret 8`): true when the button is a
`SPECIAL_POWER` (`+0x14` = `0x18`), its `Object` (`COMMAND_BUTTON_GET_THING_TEMPLATE`, the
final override) declares a non-zero `+0x5F0`, and `countObjectsByThingTemplate` with the OCL's
own arguments (`1, &tmpl, 1, &count, 0`) answers `count >= max`. That's the OCL rule, so the
button and the spawn can't disagree.

Two hooks call it, each inside `pushad`/`popad` with the verdict carried out in the flags:

- **`available`, at `0x009435D7`** (`mov ecx,[ebp-0x14]; push ebx; push edi`, 5 bytes). The
  evaluator's `SPECIAL_POWER` arm lands here only once the power's module answers ready
  (`jne` at `0x00943583`), with `edi` the button and `ebx` the object (non-null since
  `0x0094279A`). The player is `Object::getControllingPlayer(ebx)`, the same one the OCL counts
  for. At the cap the cave jumps to `CONTROL_BAR_UNAVAILABLE` (`0x009438C8`, answer 0) at the
  depth the arm's own refusals use. Otherwise it replays the displaced bytes and resumes at
  `0x009435DC`. A power still recharging never reaches the hook, so it keeps its clock.
- **`click`, at `0x00940536`** (`cmp eax, 0x18; je 0x94070f`, 9 bytes). `doCommand` sends
  `SPECIAL_POWER` straight to its `isReady` gate and never asks the evaluator, so a hotkey would
  otherwise still cast. `eax` is the command (`0x0094052A`), `esi` the button, `ebx` the context
  object, or null in the mixed context, where the cave asks `ThePlayerList->getLocalPlayer()`
  instead. At the cap it jumps to `doCommand`'s "nothing done" exit (`0x00940485`: `xor eax, eax`
  and the epilogue), reached at the depth every other exit uses. Otherwise it takes the stock
  `je` to the gate.

The evaluator covers both bars: the command bar's slot updates and the spellbook's APT update
both ask it, and a greyed APT button never fires its callback (`docs/spellbook-hotkeys.md` §6).

## Behaviour

- **Button:** greyed while the player has `MaxSimultaneousOfType` of the named object alive, and
  usable again as soon as one dies. A recharging power shows its clock as stock.
- **Click / hotkey:** refused before any message is posted, so the recharge isn't spent.
- **Other buttons:** a `SPECIAL_POWER` without `Object`, an `Object` without
  `MaxSimultaneousOfType`, and every other command are stock.
- **Composition:** applies before or after every other registered patch that applies to this
  binary, in either order. `multi-execute-cooldown`'s and `special-power-pause-button`'s windows
  are next to these and untouched.
- **Client-side only:** the logic still refuses the spawn as before; peers don't need the patch.

## Side effects of `Object` on a `SPECIAL_POWER` button

`Object` is not otherwise read for this command by availability or dispatch, but two UI readers
take it for any command:

- the tooltip builder (`0x00807B14` → `[ebp-0x4c]`, used from `0x00807EF2`) appends the named
  template's cost and prerequisite lines for every command except `0x19` and `0x34`;
- the button's production-count overlay (`0x00729E01`) counts that template in the selected
  object's production queue, which shows nothing unless the caster also trains it.

So the power's tooltip gains the summoned unit's cost line.

## Not covered

- The AI, scripts and the logic side cast through other paths and are unchanged: they still spend
  the power for nothing at the cap.
- A summon that goes through an intermediate spawner object only works if the button names the
  object that actually carries `MaxSimultaneousOfType`.
