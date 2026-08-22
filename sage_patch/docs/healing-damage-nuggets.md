# `DamageType = HEALING` in a weapon's `DamageNugget`

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000`. Read from a clean `game.dat` (11,346,944 bytes) and re-checked against the
repo's `cah-factions` image — every site quoted here is byte-identical in both, and nothing in the
`PATCHES` registry touches any of them.

**Status: statically verified, not runtime-verified.** Every claim below carries its instruction,
and the ten load-bearing sites were byte-asserted in two images. None of it has been watched in a
running game.

## The short answer

A healing nugget's *application* is fine. What is missing is everything that would make the weapon
**fire at a friendly target in the first place**:

1. **Nothing auto-acquires a non-enemy.** Every target-selection site in the AI calls
   `getRelationship` and drops the candidate unless the answer is `ENEMIES`, *before* it asks
   whether the weapon may attack it.
2. **A player-issued order at a non-enemy is refused**, unless the target is the player's *own*
   unit *and* the order is a force-attack.

So the weapon goes off exactly when the player force-attacks a unit they own, and does nothing on
auto-acquire, on an allied player's units, or on a plain click. That is the "unreliable" — it is
not intermittent, it is a narrow set of conditions that a modder hits by accident during testing
and then cannot reproduce.

Two further gates bite once it does fire, and one of them is the reason self-healing weapons look
especially broken: **`SELF` is not in the default `RadiusDamageAffects`.**

## `DAMAGE_HEALING` is enum `7`

The name table is at `0x00d9da08`, 28 entries, `FORCE` at index 0:

| index | token | | index | token |
|---|---|---|---|---|
| 0 | `FORCE` | | 6 | `FLAME` |
| 1 | `CRUSH` | | **7** | **`HEALING`** |
| 2 | `SLASH` | | 8 | `UNRESISTABLE` |
| 3 | `PIERCE` | | 15 | `MAGIC` |
| 4 | `SIEGE` | | 22 | `UNDEFINED` |
| 5 | `STRUCTURAL` | | 27 | `FROST` |

`22` (`UNDEFINED`) is the default for **both** the nugget's `DamageType` (`0x0090de3e`, writing
`+0x178`) and the weapon-level `DamageType` (`0x006cdf98`, writing `WeaponTemplate+0x58`). They are
separate fields; setting one does not set the other, and `0x006cb6ea` — "does this weapon deal
damage type N" — reads the **weapon-level** one first and only walks the nuggets if it does not
match.

### `DamageNugget` layout

Object size `0x1c4` (allocated at `0x006cd30e`), ctor `0x0090dd99`, vtable `0x00c7ae78`, own
field-parse table `0x00c7afb0` (plus the base nugget table `0x00c7ae00`).

| offset | field | default |
|---|---|---|
| `0x148` | `Damage` | `0` |
| `0x14c` | `DamageTaperOff` | `-1` |
| `0x150` | `Radius` | `0` |
| `0x154` | `MinRadius` | `0` |
| `0x158` | `DamageArc` | `pi` |
| `0x160` / `0x164` | `DamageMaxHeight` / `…AboveTerrain` | `-1` |
| `0x168` | `AcceptDamageAdd` | `1` |
| `0x174` | `DelayTime` | `0` |
| `0x178` | **`DamageType`** | `22` (`UNDEFINED`) |
| `0x17c` / `0x180` / `0x184` | `DeathType` / `DamageFXType` / `DamageSubType` | `29` / `0` / `0` |
| `0x188`..`0x18c` | `DamageScalar` list (stride 8: filter handle + float) | empty |
| `0x1bc` | `ForceKillObjectFilter` | unspecified |
| `0x1c0` | `CylinderAOE` | `0` |

The nugget vtable slots this document uses:

| slot | VA | what |
|---|---|---|
| `+0x04` | `0x0090e855` | is this candidate a valid victim |
| `+0x14` | `0x0090dafd` | fire at an object |
| `+0x18` | `0x0090def0` | fire at a position (the radius scan) |
| `+0x38` | `0x0090e683` | apply to one victim |

## Where the weapon fails to fire

### Auto-acquisition never considers a friendly

Three target-selection sites, all in the AI, all the same shape — `getRelationship`, then reject
anything that is not `0`:

```
0094c81f  call 0x68d7ab              ; getRelationship(attacker, candidate)
0094c824  test eax, eax
0094c826  jne  0x94c84a              ; not ENEMIES -> drop the candidate
0094c828  test byte [esi+0x458], 1   ; effectively dead -> drop
0094c831  push 2                     ; cmdSource = CMD_FROM_AI
0094c833  push esi                   ; the victim
0094c834  push eax                   ; attackType = 0
0094c837  call 0x68d6a6              ; getAbleToAttackSpecificObject
0094c83c  cmp  eax, 3 / cmp eax, 2   ; only 2 and 3 mean "yes"
```

`0x0094cb96` and the `0x009499f8` / `0x0094c07a` pair are the same pre-filter. The permission
function is never even consulted for an ally, so no amount of INI on the weapon can make a unit
pick a friendly target on its own.

`getRelationship` (`0x0068d7ab`) returns **`0` = `ENEMIES`, `1` = `NEUTRAL`, `2` = `ALLIES`** —
confirmed independently at `0x0090d8a0` (which maps the result onto the `RadiusDamageAffects` bits
`ENEMIES=0x4`, `NEUTRALS=0x8`, `ALLIES=0x2`) and by `0x008cc3c2` in the player-heal write-up.

### The permission gate refuses a player order at a non-enemy

`Object::getAbleToAttackSpecificObject` is `0x0068d6a6`
(`__thiscall(attackType, victim, cmdSource)`, `ret 0xc`); it tail-calls the real work in
`WeaponSet::getAbleToAttackSpecificObject` at **`0x006c9147`**
(`attackType`, `attacker`, `victim`, `cmdSource`). Two facts it establishes early:

```
006c91c5  cmp  esi, eax          ; same controlling player?
006c91c9  test byte [ebp+8], 1   ; attackType & 1 == forced
006c91cd  mov  byte [ebp-1], 1
006c91d1  jne  0x6c91d7          ;   [ebp-1] = samePlayer && forced
006c91d3  mov  byte [ebp-1], 0
```

and then the gate itself:

```
006c934f  call 0x68d7ab           ; relationship
...
006c93a9  test eax, eax
006c93ab  je   0x6c93cc           ; ENEMIES            -> allowed
006c93ad  cmp  byte [ebp-1], 0
006c93b1  jne  0x6c93cc           ; own unit + forced  -> allowed
006c93b3  cmp  byte [ebp+0x13], 0
006c93b7  jne  0x6c93cc           ; the mine/tree case -> allowed
006c93b9  cmp  dword [ebp+0x14], 0
006c93bd  jne  0x6c93cc           ; cmdSource != FROM_PLAYER -> allowed
006c93bf  test byte [edi+0x457], 0x10
006c93c6  je   0x6c9496           ; otherwise -> DENY (returns 0)
```

`cmdSource` is `0 = CMD_FROM_PLAYER`, `2 = CMD_FROM_AI` — fixed by the AI sites above passing `2`
and the player force-attack path at `0x0081d9fa` passing `0`. So the denial applies **only** to
orders that came from the player, and the escape from it is `samePlayer && forced`.

What that means in play:

| how the heal is aimed | result |
|---|---|
| left alone to auto-acquire | never fires — dropped by the relationship pre-filter |
| plain click on an ally | not an attack order at all |
| force-attack on **your own** unit | fires (`samePlayer && forced`) |
| force-attack on an **allied player's** unit | denied — different player, so `[ebp-1]` is `0` |
| ordered by a script / AI (`cmdSource != 0`) | passes this gate |

`[ebp+0x13]` is the mine-and-tree special case built at `0x006c92eb`..`0x006c9345` (victim is
`MINE` + `IMMOBILE`, or `TREE` with a flame weapon); it forces the relationship to `ENEMIES`, and
nothing a healing weapon can say reaches it.

## Where it fails after firing

### `RadiusDamageAffects` — the second, different relationship gate

`WeaponTemplate+0x110`, default **`0xe`** written at `0x006ce062`:

```
006ce062  mov dword [esi+0x110], 0xe   ; ALLIES | ENEMIES | NEUTRALS
```

Name table `0x00da16e0`: `SELF=0x1`, `ALLIES=0x2`, `ENEMIES=0x4`, `NEUTRALS=0x8`, `SUICIDE=0x10`,
`NOT_SIMILAR=0x20`, `NOT_AIRBORNE=0x40`, `PROJECTILES=0x80`, `SAME_HEIGHT_ONLY=0x100`,
`MINES=0x200`.

The nugget's own victim test, `0x0090d77c`, ends on it:

```
0090d882  call 0x68d7ab            ; relationship
0090d89b  cmp  eax, 2              ; ALLIES -> keep 2
0090d8a0  ...                      ; 0 -> 4 (ENEMIES), 1 -> 8 (NEUTRALS)
0090d8b3  test ecx, eax            ; ecx = RadiusDamageAffects
0090d8b5  je   0x90d7db            ;   no bit -> reject this victim
```

Allies pass by default. **`SELF` does not**, and its absence is a hard reject taken before
anything else:

```
0090d7d0  test al, 1               ; SELF in RadiusDamageAffects?
0090d7d5  jne  0x90d7f6            ;   yes -> skip the self-rejection
0090d7d7  cmp  ebx, esi            ; the firer IS the victim
0090d7d9  jne  0x90d7e2
0090d7db  xor  al, al              ;   -> reject
```

The same test also rejects the object the firer is contained by or produced by (`Object+0x78`
against the victim's `ObjectID`) unless the victim's template carries the bit at `+0x10f & 0x80`.
**A weapon meant to heal its own bearer needs `SELF` in `RadiusDamageAffects`** — this is the single
most likely reason a self-heal weapon "does nothing at all".

Note this gate is applied to every victim, not only to radius damage: a `Radius = 0` nugget still
goes through it, via `0x0090db21` in the single-target path.

### Delivery: single-target vs. radius

`0x0090dafd` (slot `+0x14`) is what the fire loop calls when the weapon has a victim:

```
0090db08  ucomiss [esi+0x150], 0.0  ; Radius
0090db18  jp   0x90db36             ;   != 0 -> skip the direct hit
0090db21  call [vtbl+4]             ;   isValidTarget  (-> 0x90d77c)
0090db33  call [vtbl+0x38]          ;   apply to this victim
0090db36  comiss [esi+0x150], 0.0
0090db45  jbe  0x90db56
0090db53  call [vtbl+0x18]          ; Radius > 0 -> the partition scan at the victim's position
```

The fire loop is `0x006ccec0`..`0x006ccf25` (and `0x006ccdb5` for `ScatterIndependently`); it
checks the same `isValidTarget` at `0x006ccee6` before calling `0x0090dafd`, so the gate above is
evaluated twice with the same answer.

### Application — this part works

`0x0090e683` (slot `+0x38`) builds a `DamageInfo` via `0x0090e28c` and then branches:

```
0090e6ae  cmp  al, 1                ; the DamageInfo was accepted
0090e6b0  jne  0x90e722
0090e6b2  cmp  dword [ebp-0x6c], 7  ; DamageInfo.damageType == HEALING
0090e6b6  jne  0x90e6c1
0090e6b8  fld  dword [ebp-0x5c]     ;   the amount
0090e6bd  mov  ecx, ebx             ;   this = the victim
0090e6bf  jmp  0x90e71a             ;   -> call 0x690532
...
0090e6c7  call 0x698e7d             ; every other damage type
```

`DamageInfo` layout, as built by `0x0090e28c`: `+0x08` source `ObjectID`, `+0x0c` `1 << playerIndex`,
`+0x10` `DamageType`, `+0x14` `DamageFXType`, `+0x18` `DamageSubType`, `+0x1c` `DeathType`,
`+0x20` amount, `+0x24` force-kill flag, `+0x70` damage dealt, `+0x74` health delta.

`0x00690532` is `Object::attemptHealing(Real amount, Object *source)`: it bails silently if the
object has no body module (`Object+0x25c`), otherwise stamps a fresh `DamageInfo` with
`damageType = 7`, `deathType = 1` and calls the body's `attemptHealing`
(`ActiveBody::attemptHealing`, `0x008c2fc1`). There:

- `0x008c3005` re-checks `damageType == 7` and forwards anything else to `attemptDamage`;
- `0x008c2fe5` refuses outright when the module data flag at `+0x51` is set **and** the object is in
  the `BURNINGDEATH` model condition (`0x220`);
- `0x008c3037` refuses when the object is effectively dead (`Object+0x458 & 1`), unless the
  template carries one of three flags;
- `0x008c3061` runs the amount through the armor set — **which returns it unchanged**, because
  `0x005d893c` opens with `cmp [damageInfo+0xc], 7 / jne` and returns the raw value for `HEALING`
  (`0x005d8965`). Armor coefficients do not scale healing;
- `0x008c3072` drops the heal silently if the amount is not `> 0`;
- otherwise `internalChangeHealth` (`0x008c31a5`) adds it and clamps to max health.

`ActiveBody` health fields, off the body-interface pointer (`Object+0x25c`, which is the interface
sub-object — vtable `0x00c720f0`): `+0x04` damage scalar, `+0x08` current health, `+0x0c` previous
health, `+0x10` max health, `+0x20` damage state. Fixed by `0x008c31b1`..`0x008c31d2`, which reads
old current into `+0x0c` and clamps the new value against `+0x10`.

## Two consequences of the bypass

The `HEALING` branch jumps straight to `0x00690532`, so it never enters `0x00698e7d` →
`0x00697e50`, the path every other damage type takes. That path owns three things:

- **the delayed-damage queue.** `0x00698e7d` reads `DamageInfo+0x28` (which `0x0090e28c` fills from
  `DelayTime` and `DamageSpeed`) and either queues the damage on `Object+0x460` or applies it now.
  Healing is therefore always instantaneous — **`DelayTime` and `DamageSpeed` on a healing nugget
  do nothing**;
- **the post-damage notification** `0x006968bc`;
- **the "I was attacked" hook into the victim's AI**, `0x00672c81`, gated on `Object+0x84`.

Second, `0x0090e683` reports whether it did anything as `DamageInfo+0x74 > 0` (`0x0090e722`), and
`attemptHealing` sets `+0x74 = previousHealth - newHealth` (`0x008c30a4`) — **negative** after a
successful heal. A healing nugget therefore always answers "nothing happened". The visible effect
is in the radius scan, whose single-target early-out is conditional on that answer:

```
0090e243  call [vtbl+0x38]
0090e246  test al, al
0090e248  je   0x90e25d           ; "no damage" -> keep scanning
0090e24a  mov  eax, [0xde4364]    ; TheWriteableGlobalData
0090e257  comiss [eax+0xb40], [ebp-0x20]
0090e25b  jae  0x90e26f           ; threshold >= scanRadius -> stop after the first hit
```

so a radius healing nugget never stops early and heals every eligible object in range, where a
damage nugget of the same shape would stop at one. The scan radius is `max(1.0, Radius)`
(`0x0090df00`), so this applies even to a nugget written with `Radius = 0` that reaches the scan.

## What a working healing weapon needs

```ini
Weapon HealingTouch
  RadiusDamageAffects = SELF ALLIES   ; SELF is not in the 0xe default
  DamageNugget
    Damage     = 100
    Radius     = 0
    DamageType = HEALING              ; the nugget's field, not the weapon's
    DeathType  = NONE
  End
End
```

and, for it to fire at all, something that hands the weapon a victim other than auto-acquisition:
a force-attack on a unit the same player owns, or a script order. There is no INI that makes
auto-acquire pick a friendly target — that pre-filter is in the AI, above the weapon.

## Corroboration from the data

No object in the Edain `_mod/data/ini` tree — which carries the full vanilla object set — writes
`DamageType = HEALING` in a nugget. Healing there is done with `AutoHealBehavior`
(`HealingAmount` / `HealingDelay`) and with heal special powers, and `armor.ini` lists `HEALING`
only in a comment. The weapon path is essentially unexercised by shipped content, which is
consistent with how little of it is wired up.

## Unknowns

- `Object+0x457 & 0x10`, the flag that bypasses **both** relationship gates (`0x006c93bf`,
  `0x006c9475`, `0x0090d879`, `0x004b5988`). Only ever read; the writes at `0x00693185`..`0x006931ef`
  are a bitfield read-modify-write whose caller was not traced. If this is settable from INI it is
  the intended way to make an object healable by a weapon.
- `TheWriteableGlobalData+0xb40`, the scan-radius threshold at `0x0090e257`. Its INI keyword was
  not chased.
- The nugget's `[vtbl+0x30]` test at `0x006cced3`, which routes a nugget away from the object path.
- Whether any of this changes for a `DamageFieldNugget` (`0x006cd494`) or the other nugget kinds;
  only `DamageNugget` was read.

## Every address this document depends on

| VA | meaning |
|---|---|
| `0x0044ddec` | `Object::testStatus(bit)` — bitfield at `Object+0x94` |
| `0x0046e918` | `Object::testModelCondition(bit)` — bitfield at `Object+0x10c` |
| `0x00449681` | `ObjectID -> Object*` |
| `0x005d893c` | armor adjust; `0x005d8950` its `cmp damageType, 7`, `0x005d8965` the raw return |
| `0x0068b678` | `Object::getControllingPlayer` |
| `0x0068d6a6` | `Object::getAbleToAttackSpecificObject`, `ret 0xc` |
| `0x0068d7ab` | `Object::getRelationship` — `0` ENEMIES, `1` NEUTRAL, `2` ALLIES |
| `0x00690532` | `Object::attemptHealing(Real, Object*)` |
| `0x006968bc` / `0x00672c81` | post-damage notification / victim-AI hook (skipped by healing) |
| `0x00697e50` | immediate damage — calls the body's `attemptDamage` |
| `0x00698e7d` | damage entry that dispatches delayed vs immediate |
| `0x006c9147` | `WeaponSet::getAbleToAttackSpecificObject`, `ret 0x10` |
| `0x006c93a9`..`0x006c93c6` | **the relationship gate**; `0x006c9496` its deny |
| `0x006cb6ea` | "does this weapon deal damage type N" — weapon-level `+0x58` first |
| `0x006cc779` | `WeaponTemplate::addNugget` (vector at `+0x17c`) |
| `0x006ccec0`..`0x006ccf25` | the fire loop over nuggets |
| `0x006cd301` | the `DamageNugget` sub-block parser (`0x1c4` bytes) |
| `0x006cdf98` | weapon-level `DamageType` default `22` |
| `0x006ce062` | **`RadiusDamageAffects` default `0xe`** |
| `0x008c2fc1` | `ActiveBody::attemptHealing` |
| `0x008c31a5` | `ActiveBody::internalChangeHealth` |
| `0x008c3fa3` | `ActiveBody::attemptDamage`; `0x008c406b` its own `HEALING` arm |
| `0x0090d77c` | the nugget's victim test; `0x0090d8b3` the `RadiusDamageAffects` test |
| `0x0090dafd` | nugget slot `+0x14` — fire at an object |
| `0x0090dd99` | `DamageNugget` ctor; vtable `0x00c7ae78` |
| `0x0090def0` | nugget slot `+0x18` — the radius scan; `0x0090e24a` its early-out |
| `0x0090e28c` | `DamageInfo` builder |
| `0x0090e683` | nugget slot `+0x38` — apply; `0x0090e6b2` **the `HEALING` branch** |
| `0x0090e855` | nugget slot `+0x04` — is this candidate valid |
| `0x00c7afb0` / `0x00c7ae00` | the `DamageNugget` field tables |
| `0x00c16dd8` | the `WeaponTemplate` field table |
| `0x00c720f0` | the body-module interface vtable |
| `0x00d9da08` | the `DamageType` name table (`HEALING` = 7) |
| `0x00da16e0` | the `RadiusDamageAffects` name table |
| `0x00de4364` | `TheWriteableGlobalData` |
