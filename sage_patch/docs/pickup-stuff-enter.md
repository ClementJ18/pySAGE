# PickupStuffUpdate that enters a slaughter contain

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR).

**Goal.** Units that walk into a building on their own, with nobody ordering them in. Two uses:

- Angmar tribute carts answering a building's call. A button spawns a short-lived collection
  point; every cart in range walks in and is paid out.
- Isengard's ambient armory workers walking into a furnace or keep. Today they kill themselves
  beside it with a fake weapon.

**Verdict:** `PickupStuffUpdate` already does the search: on a timer, find the nearest object
matching an INI filter, then order a move to it. The patch turns that move into `aiEnter` when the
target has a slaughter contain. That is one `call` replaced like for like, and a 60-byte cave
(`.pkpent`).

- **Status:** built ([`patches/pickup_stuff_enter.py`](../patches/pickup_stuff_enter.py)),
  statically verified, and emulated. `tests/sage_patch/test_pickup_stuff_enter.py` runs the cave
  against every target shape, and runs `PickupStuffUpdate`'s own move routine from the real
  `game.dat` with the engine's real contain vtables. **Not runtime-verified.**

## 1. What PickupStuffUpdate does

`ModuleData`, `0x18` bytes:

| field | offset | default |
|---|---|---|
| `SkirmishAIOnly` | `+0x08` | `Yes` |
| `ScanRange` | `+0x0C` | `200` |
| `StuffToPickUp` | `+0x10` | an `ObjectFilter` |
| `ScanIntervalSeconds` | `+0x14` | `0.5` |

The update (`0x008957B7`) returns at once for an owner with no `AIUpdate`. With `SkirmishAIOnly`
it also needs the owner's player to have skirmish-AI data (`0x006A950B`). Then it takes one of
two branches on the module's "on my way" flag (`+0x20`).

**Scanning** (`0x00895741`). This branch runs once every `ScanIntervalSeconds`, and only while
the owner's `AIUpdate+0x34` is zero (`PICKUP_STUFF_SCAN_IDLE_TEST`). That slot is non-zero exactly
while a temporary state machine is pushed. The search (`0x00895632`) is a partition search around
the owner, out to `ScanRange`. It uses two filters:

- `PARTITION_FILTER_OBJECT_FILTER_VTABLE`, built from `StuffToPickUp` and the owner's controlling
  player. So the filter's template names, KindOf and relationship tokens (`SAME_PLAYER`,
  `ALLIES`, ...) all apply.
- `PARTITION_FILTER_NOT_DESTROYED_VTABLE`.

It also excludes `ATTACHED` objects through the status masks. On a hit, `PICKUP_STUFF_MOVE_TO`
(`0x00895715`) runs:

```
00895721  call 0x6630a9            ; push a temporary state machine; the current one is saved at +0x34
0089572f  push 2                   ; CMD_FROM_AI
00895731  push dword [esp+0xc]     ; the target
00895735  add  ecx, 0x20           ; AIUpdate+0x20
00895738  call 0x7549d7            ; aiMoveToObject   <- the hook
```

and sets the flag.

**Arriving** (`0x00895572`). Once the `AIUpdate` reports idle (vtable `+0x1B8`), the temporary
machine is popped (`0x006630D7`), which restores whatever the unit was doing before, and the flag
is cleared.

So the search does not care whether the unit is busy. A unit under orders is diverted, and goes
back to those orders afterwards.

## 2. The change

`aiMoveToObject` (`0x007549D7`) and `aiEnter` (`0x00770EDE`) take the same arguments:
`__thiscall` on `AIUpdate+0x20`, `(Object *target, CommandSourceType)`, `ret 8`. They have the
same body too, apart from the command type each builds (`push 1` and `push 0x42`). So the call at
`0x00895738` is pointed at a cave with that signature. The cave walks the target's module list
(`OBJECT_MODULE_LIST`) and asks each contain module its slaughter slot (`CONTAIN_IS_SLAUGHTER_SLOT`,
`+0x30`). It tail-jumps to `aiEnter` if any answers yes, and to `aiMoveToObject` otherwise.

| contain | `+0x30` |
|---|---|
| `SlaughterHordeContain` (`0x00C5F0D0`) | `CONTAIN_ANSWER_YES` |
| `CitadelSlaughterHordeContain` (`0x00C5F2E8`) | `CONTAIN_ANSWER_YES` |
| `HordeGarrisonContain`, `TunnelContain`, transports | `CONTAIN_ANSWER_NO` |

**The Ring is unchanged.** The dropped Ring carries no contain, so a Ring hero still gets the
stock move and collects it on contact. Crates are the same.

**`multi-contain`.** The cave asks every contain module, not only the stored one, so a slaughter
contain declared ahead of a `TunnelContain` is found. With `multi-contain` applied, the enter
then reaches it. Without that patch, the enter goes to the stored contain, which refuses the
rider. The unit idles there, the temporary machine pops, and it scans again on the next interval.

**If the enter fails** (a full contain, a filter mismatch), `AIEnterState` ends, the unit goes
idle, and the arrival branch pops the machine as it would after a move.

## 3. Using it

The unit carries the module with `SkirmishAIOnly = No`, so it runs for humans too. The building
it should enter carries the slaughter contain.

### Tribute carts answering a call

A collection-point object holds the slaughter contain and lives for the length of the call:

```ini
Object AngmarTributeCollectionPoint
    KindOf = IMMOBILE UNATTACKABLE NO_COLLIDE
    Behavior = SlaughterHordeContain ModuleTag_Collect
        PassengerFilter              = NONE +AngmarTributkarrenCarnDum +AngmarTributkarrenHillman +AngmarTributkarrenOrcs
        CashBackPercent              = 100%
        ContainMax                   = 99
        AllowOwnPlayerInsideOverride = Yes
        ObjectStatusOfContained      = UNSELECTABLE
    End
    Behavior = LifetimeUpdate ModuleTag_Call
        MinLifetime = 30000
        MaxLifetime = 30000
    End
End
```

The building's button is an `OCLSpecialPower` that creates it at the building's door. Each cart
gets:

```ini
Behavior = PickupStuffUpdate ModuleTag_AnswerTributeCall
    SkirmishAIOnly      = No
    StuffToPickUp       = NONE +AngmarTributeCollectionPoint SAME_PLAYER
    ScanRange           = 600
    ScanIntervalSeconds = 1.0
End
```

`ScanRange` is measured from the cart, so it is also the radius of the call.

### Isengard armory workers

Give each furnace and keep a `SlaughterHordeContain` with
`PassengerFilter = NONE +IsengardMineshaftWorker` and `CashBackPercent = 0%`. Then replace the
worker's `AutoAbilityBehavior` with a `PickupStuffUpdate` whose `StuffToPickUp` names those
buildings. A worker goes to the **nearest** match, so every worker from one armory walks to the
same building. `IsengardCastleBaseKeep_Magierturm` already has a `TransportContain`, so it needs
`multi-contain`, with the slaughter contain declared first.

## 4. Not known, and what to check in game

- **Does `SpawnBehavior` replace a slave that was removed by a slaughter contain rather than
  killed?** Workers come from a `SlavedEggSpawner` (`SpawnReplaceDelay = 20000`). If the
  replacement keys on a death, a slaughtered worker is never replaced.
- **The cart's existing `AutoAbilityBehavior` walk to the fortress.** It also runs on idle carts.
  `PickupStuffUpdate` does not wait for idle, so the call should win while a collection point
  exists. Untested.
- **Can `OCLSpecialPower` spawn at the caster** with no target click? This decides whether the
  call is one click.

In game:

1. Place a collection point (or give a building the contain) with a cart inside `ScanRange`. The
   cart turns towards it within `ScanIntervalSeconds`, walks to the door, is destroyed, and the
   cash text appears.
2. Leave a Ring hero beside the dropped Ring. It still walks over and collects it.
3. With `multi-contain`, on a lair carrying a slaughter contain ahead of a `TunnelContain`, a cart
   enters the slaughter contain.
