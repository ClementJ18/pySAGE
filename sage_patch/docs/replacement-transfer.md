# Transferring state to a replacement

When an object turns into another (a `ReplaceSelfUpgrade` fires, or a
`SummonReplacementSpecialAbilityUpdate` swaps in its `MountedTemplate`), the new object starts
without the old one's object upgrades. A `ReplaceSelfUpgrade` replacement also starts without its
experience, at full health, out of its control group and selection, and with no rally point. A
replaced building's production queue is deleted with it, and nothing it was paid is refunded.
`replacement-transfer` adds one keyword to both modules to carry them across:

```ini
Behavior = ReplaceSelfUpgrade ModuleTag_Upgrade
    TriggeredBy           = Upgrade_Fortify
    ReplaceWith           = MyFortifiedTower
    TransferToReplacement = UPGRADES EXPERIENCE HEALTH SELECTION RALLY PRODUCTION HORDE
End
```

| flag | carries |
|---|---|
| `UPGRADES` | every object upgrade, granted so the new object's upgrade modules fire |
| `EXPERIENCE` | experience, and the level the new template's thresholds give it (only ever raised) |
| `HEALTH` | the health *ratio*: the new object gets the same fraction of its own maximum |
| `SELECTION` | the control group (1-0) and, if the old object was selected, the selection |
| `RALLY` | the rally point of a production building |
| `PRODUCTION` | the production queue, with each entry's progress and what was paid for it |
| `HORDE` | a horde's surviving member count, each member's health ratio and member experience |

Status: **static-verified**, and emulated over the real `game.dat`: both replacement hooks with
every flag, both constructors and the parse shim
(`tests/sage_patch/test_replacement_transfer_emulated.py`). Not yet seen in a running game.

## What the stock swaps carry

| path | experience / level | object upgrades | health | group / selection | rally point | queue |
|---|---|---|---|---|---|---|
| `ReplaceSelfUpgrade` | no | no | no (full) | no | no | lost, unrefunded |
| `SummonReplacementSpecialAbilityUpdate` | yes | no | absolute | yes | no | lost, unrefunded |
| `ToggleMountedSpecialAbilityUpdate` (not covered) | yes | no | absolute | yes | no | lost, unrefunded |

The queue is lost because neither swap touches production. The old object is destroyed, not
killed, so no die module runs, and `ProductionUpdate`'s destructor (`0x008A198B`) deletes the
entries without a deposit (`production-death-refund.md`, "Not covered").

The two `SpecialAbilityUpdate` swaps (`0x008B228C` summon, `0x008B140D` toggle mount) are
near-identical. Each builds the new object through `TheBuildAssistant` (vtable `+0x38`), copies the
script name, and then copies experience with level-up feedback switched off:

```
008b2341  mov eax, [esi+0x26c]        ; new ExperienceTracker
008b2347  mov byte [eax+0x3c], 0      ; feedback off
008b2357  fld dword [eax+0x10]        ; (old tracker) experience
008b2360  call 0x79d8ef               ; setExperienceAndLevel(xp, true)
008b2365  mov eax, [esi+0x26c]
008b236b  mov byte [eax+0x3c], 1      ; feedback back on
```

`ReplaceSelfUpgrade::upgradeImplementation` (`0x008BB5FA`) copies neither. Per `ReplaceWith`
entry it builds the object, sets its position and copies the script name, and nothing else of
the old object's state. The old object is handed to `destroyObject` at `0x008BB6CC` before the
loop, but that only queues it, so it is still intact while the replacements are made.

## The pieces the transfer uses

| what | where |
|---|---|
| `Object` completed object-upgrade bitset (36 dwords) | `+0x28C` |
| `Object::giveUpgrade(UpgradeTemplate*)`: sets the bit and fires the object's upgrade modules (recurses into a horde's members) | `0x0069388B` |
| `UpgradeCenter` template list (`TheUpgradeCenter+0x0C`, `next` at `+0x64`, mask index at `+0x38`) | `0x00DE45A0` |
| `Object` experience tracker | `+0x26C` |
| tracker experience (float) / level-up feedback byte | `+0x10` / `+0x3C` |
| `ExperienceTracker::setExperienceAndLevel(Real xp, Bool)`: stores the experience and re-derives the level, honouring the experience sink at `+0x38` | `0x0079D8EF` |
| `INI::parseBitString32(ini, instance, store, names)`: `1 << index` per name, `+`/`-` edit the current value | `0x0042E840` |
| `Object` body; body vtable `+0x14` health ratio, `+0x1C` maximum (both `st(0)`), `+0xAC` `setHealth(Real)` | `+0x25C` |
| `Object::getExitInterface()`: the exit module's interface, else the contain module's | `0x0068BB14` |
| `ExitInterface` `+0x20` get rally point (`Coord3D *` or NULL), `+0x1C` set it; the same slots on all three production exits | |
| `Object::isLocallyControlled()` / `getControllingPlayer()` | `0x0068B749` / `0x0068B678` |
| `Player::findSquadOf(Object *)`: control group 0-9 or -1 (`Player+0x728`) | `0x006AABB2` |
| `Drawable` selected flag | `+0x43C` |
| `TheInGameUI` `+0x108` select / `+0x10C` deselect a drawable | `0x00DE4830` |
| `Object::getProductionUpdateInterface(Bool)`: the module's interface at module `+0x20` | `0x0068C327` |
| interface `+0x08` / `+0x0C` queue head / tail, `+0x10` id counter, `+0x14` length, `+0x100` a finished unit held at the door | |
| `ProductionUpdate::append(entry)` (`ecx` = module): links at the tail, counts, wakes the module | `0x008A0C99` |
| entry `+0x14` progress (percent), `+0x48` / `+0x4C` next / prev | |

There is no "give mask" call, so the transfer walks the `UpgradeCenter` list and gives each
template whose bit the old object has and the new one lacks, the same walk `firstSetIn`
(`0x0066F468`) makes. Giving rather than copying bits is the point: the new object's own
`ArmorUpgrade`, `WeaponSetUpgrade`, `ModelConditionUpgrade` and so on fire as if it had been
upgraded itself.

## The keyword

`TransferToReplacement` is a one-byte flag set: `UPGRADES` (bit 0), `EXPERIENCE` (bit 1),
`HEALTH` (bit 2), `SELECTION` (bit 3), `RALLY` (bit 4), `PRODUCTION` (bit 5) and `HORDE`
(bit 6). The
stock bit-string parser writes a dword, so the new row's parse function is a shim in the cave. It
seeds a stack dword from the byte, calls `0x0042E840` on it, and stores the low byte back.
`+NAME` / `-NAME` work as on any engine flag list, and an unknown name is the engine's usual INI
error.

### Where the byte lives

- **`ReplaceSelfUpgrade`**: ModuleData `+0x137`. The `UpgradeMux` base occupies `+0x08..+0x137`
  and its constructor (`0x00653173`) writes as far as `+0x136`. `+0x137` is the base's tail
  padding, written by nothing (`foundation-rebind.md` 6.4 costs exactly this). The shared mux
  constructor is pinned byte-for-byte by `upgrade-module-removal`, so the byte is cleared from
  `ReplaceSelfUpgradeModuleData`'s own constructor instead. Its `lea esi, [edi+0x138]` at
  `0x008BBA59` jumps to a cave that writes the zero and replays the `lea`.
- **`SummonReplacementSpecialAbilityUpdate`**: ModuleData `+0xE6`, padding between
  `CancelDisguiseWhenDismounting` (`+0xE5`) and `MountedTemplate` (`+0xE8`). Its constructor
  stores `+0xE4` and `+0xE5` as two bytes from `ebx` (zero) at `0x008B223D`. They become one
  `mov dword [esi+0xE4], ebx` plus a six-byte `nop`, which clears `+0xE6/+0xE7` too.

Both module tables are rebuilt in the cave with the stock rows verbatim plus the new row. Each
has exactly one reference: `push 0xC6F6E8` at `0x008BB169` and `push 0xC05AF8` at `0x0064F569`.

## The hooks

- **`ReplaceSelfUpgrade`, `0x008BB8F6`**: `lea eax,[ebp-0x24]` / `lea ecx,[edi+0x88]` (9 bytes),
  right after the new object is positioned and before its name is copied. `edi` is the new
  object, `[esi-8]` the old one and `[ebp-0x50]` the ModuleData. The window sits between the
  two windows `foundation-rebind` pins (`0x008BB8D9..+0x10` and `0x008BB955..+0x16`), and nothing
  branches into it. `eax` and `ecx` are rewritten by the replayed pair, and `edx` belongs to the
  `AsciiString` copy that follows. Runs once per `ReplaceWith` entry.
- **`SummonReplacementSpecialAbilityUpdate`, `0x008B2365`**: the feedback restore above (10
  bytes), after the stock experience copy. `esi` is the new object, `edi` the old one, and
  `[ebp-0x18]` the module (`+4` its ModuleData). The rejoin at `0x008B236F` is the first byte of
  the health hand-over `mount-health-ratio` pins, which loads `eax` and `ecx` before reading
  either. With `HEALTH` the hook rejoins after that hand-over instead, at `0x008B2392`
  (`push 0xa` / `mov ecx, esi` / `call Object::getDrawable`), so the stock absolute copy doesn't
  overwrite the ratio. The hand-over is the only thing skipped, and `ebx`, the one register it
  leaves changed, is written again at `0x008B23CB` before anything reads it. The hook masks
  `SELECTION` out, because the swap already does that itself (`0x008B23A2..0x008B2473`).

Both call one `__stdcall transfer(old, new, flags)`, in this order:

1. **`EXPERIENCE`** raises the new tracker to the old one's experience, only if that's higher,
   with `+0x3C` cleared around the call as the stock swaps do.
2. **`UPGRADES`** runs the `UpgradeCenter` walk.
3. **`HEALTH`** sets the new body to `old ratio x new maximum`, after the first two so the
   maximum already includes rank and upgrade bonuses. A ratio of zero or less sets nothing.
4. **`HORDE`** runs `horde_copy(old, new)`, described in [Hordes](#hordes).
5. **`RALLY`** reads the old exit interface's rally point and, if one is set and the new object
   has an exit interface, passes it to the new one's setter. That's the slot a player's own rally
   order reaches, so a production exit's snap-to-target near the point applies as usual.
6. **`PRODUCTION`** takes both objects' production interfaces and, when both exist and differ,
   empties the old queue and re-appends each entry to the new module through the stock `append`,
   which also wakes the new module's update. Each entry's links are cleared first, and the order
   is kept. It moves the entry object itself, so its progress, the amount paid (`+0x28`, what a
   later cancel refunds) and a hero's revive record (`+0x38`) all stay as they were. Two
   exceptions:
   - An entry at 100% while the old module's door hold (`+0x100`) is set goes back on the old
     queue. That's the test `cancelUnitCreate` uses for a unit already handed to the door, and
     the door state can't move.
   - The new id counter is raised to the old one's if it's lower. Moved entries keep their
     `ProductionID`s, and the new building would otherwise mint 1, 2, 3... again and could
     collide with a moved revive's id (the failure `unique-production-id` fixes).
7. **`SELECTION`** does what the summon swap does in stock, but only when the old object is
   locally controlled. If the old object is in one of its owner's control groups, it posts
   `MSG_ADD_TO_TEAM<n>` with the new id. If its drawable is selected, it deselects it, posts
   `MSG_CREATE_SELECTED_GROUP(false, new id)` and selects the new drawable.

It keeps `ebx`, `esi`, `edi` and `ebp`.

## Behaviour notes

- **Level follows experience.** The level is re-derived from the new template's
  `ExperienceRequired`. A replacement with steeper thresholds can land on a lower rank with the
  same experience. Experience is never lowered, so a replacement created at a higher rank keeps it.
- **Upgrades fire.** A transferred upgrade can trigger any upgrade module on the new object,
  including another `ReplaceSelfUpgrade`. If the new template has a `ReplaceSelfUpgrade`
  triggered by an upgrade the old one carried (including the one that caused this replacement),
  it fires immediately. That's data the mod controls. Don't give the replacement a module
  triggered by its own trigger upgrade.
- **Only object upgrades.** Player upgrades live on the player and are unaffected by a
  replacement anyway.
- **Hordes.** `giveUpgrade` on a horde forwards to its members, as stock. `EXPERIENCE` raises
  the horde object's own tracker; the members' experience lives in the horde's experience
  groups and needs `HORDE`.
- **`SummonReplacementSpecialAbilityUpdate` + `EXPERIENCE`** or **`+ SELECTION`** does nothing
  extra: stock already does both.
- **Health is a ratio.** A unit at 25% health becomes a replacement at 25% of its own maximum.
  On the summon swap that replaces the stock behaviour, which copies the absolute value and so
  can overheal or underheal between templates with a different `MaxHealth`.
- **Selection is local.** The stock summon swap posts its control-group message on every
  machine. This patch posts only on the owner's, where the control groups and selection belong.
  The messages travel the ordinary command stream, so peers and replays see the same group change
  a player's own keypress would make.
- **Production moves as paid.** A moved entry finishes on the new building, and cancelling it
  there refunds what was paid. The new building's `MaxQueueEntries` isn't re-checked, and nor is
  whether its command set offers what was queued. What's in the queue still completes.
- **Rally points** exist only on production exits (and on contain modules that answer the same
  interface). A replacement without an exit just doesn't take one.

## Hordes

Without `HORDE`, a replacement horde spawns its full `InitialPayload` at full health and with
fresh members, whatever state the old horde was in. `HORDE` hands the old members' state over.

### Where a horde keeps its members

| what | where |
|---|---|
| `Object::getHordeIface()`: contain `+0x7C`, NULL for anything that is not a horde | `0x0068C866` |
| the horde interface, `HordeContain` module `+0x11C`; vtable | `0x00C5B1F8` |
| contained objects: contain (`Object+0x258`) `+0x34`, a `std::list` sentinel; node `+8` the object | |
| leader / banner carrier `ObjectID`, module `+0x264` / `+0x26C` (interface `+0x148` / `+0x150`) | |
| interface `+0x34` (`0x0087370B`, `ret 4`): a member leaves the horde, freeing its formation slot | |
| `GameLogic::destroyObject(obj)` | `0x0062BBAB` |
| experience accounts, interface `+0x13C`: a map from the member template's group key (word at `ThingTemplate+0x5E8`) to a `Real` | |
| `lookupOrInsert(WORD *key)` on that map, `ret 4`: inserts at 0.0, returns `Real *` | `0x00873322` |
| `HORDE_EXPERIENCE_ADD(member, Real delta)` on the interface, `ret 8`: account += delta, every member of that group set to the account, the horde's own tracker raised to it | `0x00873A02` |

The removal pair is the one `HordeContain::onObjectCreated` uses for its own strength trim
(`0x00871C28`): for each member it drops, `[iface]+0x34(member)` and then `destroyObject(member)`.
The member's slot goes back on the free list, so a banner carrier can replenish it later, as it
would for a member killed in battle.

### When the members exist

A swap builds the new horde with `buildObjectNow`, which passes the old object as the constructor
and so makes it the new horde's producer (`setProducer` at `0x007978B9`, right after `newObject`).
Both of `HordeContain`'s own fill paths skip a horde that has a producer: `onObjectCreated`
(`0x00871BB3`) and `onBuildComplete` (`0x008718FC`). Edain's swapped hordes (the Dwarven Guardian
stances through `SummonReplacementSpecialAbilityUpdate`, the Rohan traitor hordes through
`ReplaceSelfUpgrade`) are populated in game, so the members are created inside `newObject`, before
the producer is set, and they are there when the transfer hook runs. `horde_copy` reads the live
member list anyway and does nothing when either horde is empty.

### `horde_copy(old, new)`

`__stdcall`, `ret 8`, after `UPGRADES` and `HEALTH` so the members' maxima already include their
upgrades.

1. Both member lists are copied into arrays on the stack, up to `HORDE_MEMBER_CAP` (64) each.
   Either horde without an interface or without members ends it.
2. Each new member is paired. The new leader takes the old leader, the new banner carrier takes
   the old banner carrier, and every other member takes the next old member that is neither.
   A role whose old holder is dead has no partner.
3. An unpaired new member leaves the horde through the removal pair above. So a horde that had
   lost its banner carrier comes back without one, and one with 4 of 10 members comes back with 4.
4. A paired member gets `partner ratio x own maximum` through `setHealth`, as `HEALTH` does for the
   object itself (a ratio of zero sets nothing). Its group account is looked up (inserted if new)
   and raised to the partner's experience if that's higher.
5. With the new horde's level-up feedback (`tracker+0x3C`) cleared, every kept member goes through
   `HORDE_EXPERIENCE_ADD(member, 0.0)`. That sets the members of each group to the group's account
   and raises the horde object's own tracker to it, then the feedback byte is put back.

Accounts are keyed by the new members' templates, so experience carries across a swap to
different member types: each new group gets the experience of the old members paired into it.
Experience is never lowered.

## Not covered

- **`ToggleMountedSpecialAbilityUpdate`.** Its swap is the same shape, but `lifetime-fields`
  drives it with a `LifetimeUpdate` ModuleData built to exactly `0xE8` bytes. A flag placed past
  `+0xE8` would be read off the end of that allocation. Covering it means first agreeing a byte
  inside `+0x00..+0xE7` that both layouts leave free.
- **`ReplaceObjectUpdate`** and OCL-based swaps (`foundation-rebind.md` 6.3 lists the same gap).

## In-game check

1. Give a unit with a `ReplaceSelfUpgrade` some experience and an object upgrade with a visible
   effect (armour, a weapon set). Damage it, put it in control group 1, keep it selected, and, for a
   building, set a rally point. Set
   `TransferToReplacement = UPGRADES EXPERIENCE HEALTH SELECTION RALLY PRODUCTION HORDE`, and queue
   a few units with the first part-built.
2. Trigger the replacement. The new object should show the same rank (or the rank its own
   thresholds give that experience) and the upgrade's effect, without level-up effects. It should
   be at the same health fraction, selected, recalled by `1`, and its production should walk to
   the old rally point. The queue should carry on from where it was, and cancelling an entry should
   refund it.
3. Without the keyword, the replacement should behave as stock.
