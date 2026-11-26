# Damage does not stop a worker's repair, and the cancel that exists is gated on auto-heal

RotWK `game.dat` 2.01.2614.37001, ImageBase `0x400000`. The write-up behind
`repair-damage-cancel`, in [`patches/structures/repair_damage_cancel.py`](../patches/structures/repair_damage_cancel.py).

`GettingBuiltBehavior::update` has a damage cancel: a structure hit in the last four seconds has
its repair stopped. It misses two cases:

1. **A structure with a `WorkerName`**, which in Edain is almost every building (399 of the
   `GettingBuiltBehavior` blocks). Its repair is a spawned worker healing it. The cancel only
   clears the structure's own repairing flag, which the worker path never sets, so the worker keeps
   going. This is the case a player sees, and a running game shows it (§5).
2. **A structure with `SpawnTimer < 0`** (auto-heal off): castles, walls, gates, camps, outposts.
   The cancel is behind a `SpawnTimer >= 0` test.

And any hit counts, however small: an arrow that a building's armour turns into a point of damage
stops a repair as surely as a ram. `--min-damage` sets the least damage a hit must deal (§7).

## 1. The interface

A structure's repair belongs to its `GettingBuiltBehavior`. The module exposes a
`GettingBuiltBehaviorInterface` at `module+0x20`, vtable `0x00C56BF0` (written by both
constructors, `0x008573DD` and `0x00857533`). The slots and fields that matter:

| slot / field | VA | what |
|---|---|---|
| `+0x04` | `0x00857A19` | the repair start for a structure with a `WorkerName`: `findTemplate(WorkerName)`, `newObject`, place it on the structure, make each the other's producer (`0x00857AEA`, `0x00857AF2`), set `+0x1C`, order the worker to repair (`0x00857BAE` / `0x00857BB5`). Without a `WorkerName` it calls `+0x10` instead |
| `+0x10` | `0x008566DF` | `startRepair(bool free)`: sets the repairing flag `+0x12` and `UNDERGOING_REPAIR`, charges the player unless `free` |
| `+0x14` | `0x00856644` | `stopRepair()`: if `+0x12` is set, clears it, `UNDERGOING_REPAIR` and `UNDER_CONSTRUCTION`, stops the sound loop. **Nothing else** |
| `+0x18` | `0x00857448` | `isRepairing()`: `[ecx+0x12]` |
| `+0x20` | `0x00856501` | `canStartRepair()`: refuses if damaged within `GameData TimeAfterDamageUntilRepairAllowed` (`+0xA88`, default 10 s, `0x00642F8F`) |
| `+0x2C` | `0x008227A4` | `isStillBuilding()`: `[ecx+0x16]` |
| `+0x08` | field | the auto-repair countdown, in seconds (§4) |
| `+0x1C` | field | set once `+0x04` has spawned a worker |

The worker is the structure's producer, `Object+0x7C` (written by `Object::setProducer`,
`0x0068B6B6`). The update reads it back at `0x00857EEF` and treats a live producer as a builder
driving the structure. That skips the structure's own heal (§1.2 of
[`construction-initial-health.md`](construction-initial-health.md)), so the repair is entirely
the worker's.

## 2. The cancel

`GettingBuiltBehavior::update` (`0x00857E77`) runs with `ecx` = the module's update interface,
`module+0x10`. The GettingBuilt interface is then `esi+0x10`, and `edi` is the structure.

The recent-damage probe:

```
00857eb4  cmp  byte [esi+0x25], 0        ; startRepair out of rubble?
00857eb8  jne  0x857ecf                  ;   yes -> [ebp-1] = 0
00857eba  push 4                         ; seconds
00857ec2  call 0x0068c933                ; wasDamagedWithin(&attacker, 4 s)
00857ec9  mov  byte [ebp-1], 1           ; ... or 0 at 0x00857ECF
```

`0x0068C933` compares the body's last-damage frame (`ActiveBody` slot `+0x44`, `[body+0xAC]`) plus
`seconds * LOGIC_FRAMES_PER_SECOND` against the current frame.

Then the cancel:

```
00857f21  test   bl, bl                          ; Object+0x458 bit 0 (effectively dead)
00857f23  jne    0x8580ac                        ;   -> stopRepair, every update
...
00857f2c  movss  xmm0, [ebx+0x20]                ; SpawnTimer
00857f31  comiss xmm0, [0x00c1b594]              ; 0.0
00857f38  jb     0x857f4a                        ; <-- SpawnTimer < 0: no cancel
00857f3a  cmp    byte [ebp-1], 0                 ; hit in the last 4 s?
00857f3e  je     0x857f4a
00857f40  cmp    byte [esi+0x26], 0              ; still being built?
00857f44  je     0x8580ac
...
008580ac  mov    ecx, [ebp-0x18]                 ; the GettingBuilt interface
008580af  mov    eax, [ecx]
008580b1  call   [eax+0x14]                      ; stopRepair
008580b4  ...                                    ; worker manager, auto-repair countdown, return
```

`0x008580AC` is reached two ways: the damage cancel, and **every update** of a structure whose
`Object+0x458` bit 0 is set. A running game (§5) shows that bit set on a building being rebuilt
out of rubble by its worker, at 37% health.

## 3. Why the worker keeps going

`stopRepair` tests the repairing flag `+0x12` and returns if it is clear. Slot `+0x04` never sets
it. On a worker-repaired structure the cancel therefore does nothing, from either entry. The
engine only removes a worker in the worker manager (`0x00857238`), once the worker's AI reports it
done (`[ai]` slot `+0x1B8`):

```
008572d2  mov  eax, 0x10000000
008572d7  test [esi+0x128], eax        ; a model-condition bit on the worker
008572df  or   [esi+0x128], eax
008572e7  call 0x0068b53c              ;   and the model-condition-changed notification
008572ec  push 0x16                    ; FADED
008572ee  push 8                       ; UNRESISTABLE
008572f2  call 0x00698ec3              ; Object::kill
008572f7  push 0
008572fb  call 0x0068b6b6              ; structure->setProducer(NULL)
```

## 4. The auto-repair countdown

`0x00857818`, called at the end of every update, keeps a countdown in interface `+0x08`. The update
seeds it from `SpawnTimer` (`0x00857EA4`), and `0x00857818` takes `1.0` off it each time it runs
while the structure is hurt and was not hit in the last four seconds (`0x008579ED`). When the
countdown is at or below zero and the structure has no worker, it calls slot `+0x04` and a worker
spawns (`0x008579FA`). Measured live: it falls by 1.0 per second of game time.

After the countdown has run out once it stays at zero. So a worker removed any other way is
replaced on the next update. §5 shows that happening.

## 5. What the running game showed (2026-09-29)

`sage_live` against an Edain skirmish, Lothlorien, an `ElvenMallornTree_Extern`
(`WorkerName = ElvenWorkerNoSelect_Lorien`, `SpawnTimer = DEFAULT_STRUCTURE_HEALDELAY`, 180) under
attack while its worker repaired it.

- **With only the `SpawnTimer` gate erased:** the
  structure's `+0x12` read `0` and it carried no `UNDERGOING_REPAIR`, while the worker (id 408,
  the structure's producer at `Object+0x7C`) stayed `WORKER_REPAIRING` throughout. The cancel ran
  and had nothing to stop. The structure's `Object+0x458` bit 0 was set.
- **With the worker dismissal but no countdown rewind:** each hit faded the worker, and a new one
  spawned the next update. Worker ids climbed 431 → 454 in about ten seconds, each one
  `WORKER_REPAIRING` then `SINKING`. The countdown read `0`.
- **With the rewind:** the hit faded the worker (515) and set the countdown to `180.0` and the
  producer to `0`. No worker spawned. Once the attacker was killed, the countdown fell at one per
  second (150 → 145 → 139 → … → 3). At `0.0`, 932 frames after the last hit, slot `+0x04` spawned
  a new worker (519), which went straight to `WORKER_REPAIRING`.

## 6. The patch

Two edits.

**The gate.** The two bytes at `0x00857F38` (`72 10`) become `66 90`, a single two-byte `nop`.
The `comiss` before it only sets flags, and the next instruction reads none of them.

**The worker dismissal.** The eight bytes at `0x008580AC` (`mov ecx, [ebp-0x18] / mov eax, [ecx] /
call [eax+0x14]`) become a `jmp` to a cave in a `.rdcan` section, plus three `nop`s. The only
branches into that run target its first byte (`0x00857F23`, `0x00857F44`). The resume point
`0x008580B4` is a branch target itself (`0x008580A5`), so it is where the stolen run has to end.
The cave:

```asm
    mov  ecx, [ebp-0x18]            ; stopRepair, as stock
    mov  eax, [ecx]
    call [eax+0x14]
    cmp  byte [ebp-1], 0            ; hit in the last 4 s? (both entries reach here)
    je   done
    mov  eax, [ebp-0x18]
    cmp  byte [eax+0x1c], 0         ; did this module spawn a worker?
    je   done
    push esi
    push dword [edi+0x7c]           ; the structure's producer
    mov  ecx, [TheGameLogic]
    call findObjectById
    test eax, eax / je pop
    cmp  eax, edi / je pop          ; not the structure itself
    mov  esi, eax
    push 97                         ; WORKER_REPAIRING
    mov  ecx, esi
    call Object::testStatus
    test al, al / je pop
    ...                             ; 0x008572D2's dismissal: condition bit, kill(UNRESISTABLE,
                                    ;   FADED), structure->setProducer(NULL)
    mov  eax, [ebp-0x10]            ; moduleData
    mov  eax, [eax+0x20]            ; SpawnTimer
    mov  ecx, [ebp-0x18]
    mov  [ecx+0x8], eax             ; rewind the auto-repair countdown
pop:
    pop  esi
done:
    jmp  0x008580b4
```

`edi` (the structure) and `[ebp-0x18]` (the interface) are set before either entry and survive
the calls. `[ebp-0x10]` still holds `moduleData` on both entries: the only later write to it is the
self-heal at `0x00857FE0`, which never reaches the cancel. `esi` is callee-saved and popped by the
epilogue, so the cave saves it. Every callee cleans its own arguments.

Every worker-using `GettingBuiltBehavior` in Edain has a positive `SpawnTimer`: 360 use the
180 s default, 31 leave it at the 30 s field default, and 6 set 120 or 15. So the rewind never
stores a value that would spawn at once. Structures with `SpawnTimer = -1` have no worker.

## 7. `--min-damage`: only a heavy hit counts

### 7.1 Where "damaged recently" is decided

The probe of §2 turns `wasDamagedWithin`'s answer into the flag `[ebp-1]`:

```
00857ec2  call 0x0068c933               ; Object::wasDamagedWithin(&attacker, 4 s)
00857ec7  test al, al                   ; <-- min-damage hook: 8 bytes, to 0x00857ECF
00857ec9  mov  byte [ebp-1], 1
00857ecd  jne  0x857ed3
00857ecf  mov  byte [ebp-1], 0
00857ed3  lea  ecx, [esi-0x10]          ; resume
```

`[ebp-1]` has two readers: the stock cancel at `0x00857F3A`, and this patch's cave. The auto-repair
countdown (`0x00857818`) calls `wasDamagedWithin` itself, so a light hit still holds a new worker
back for four seconds.

### 7.2 The last hit's damage

The body keeps the whole `DamageInfo` of its last hit. Body vtable slot `+0x40`,
`getLastDamageInfo`, is `lea eax, [ecx+0x30]; ret` (`0x00715914`) on every `ActiveBody` vtable,
and `xor eax, eax; ret` (`0x00851E97`) on `InactiveBody`'s. The `DamageInfo` is `0x7C` bytes, so
the last-hit frame at `+0xAC` that slot `+0x44` reads directly follows it.

`ActiveBody::attemptDamage` (`0x008C3FA3`) fills `DamageInfo+0x70` and then copies the info:

```
008c4063  call 0x5d893c                 ; Armor::adjustDamage
008c4068  fstp dword [ebp-0x18]
008c407c  movss xmm0, [esi+4]           ; the body's damage scalar
008c4081  mulss xmm0, [ebp-0x18]
008c4086  movss [ebp-0x18], xmm0
...
008c4280  movss [ebx+0x70], xmm0        ; dealt = [ebp-0x18]
008c428f  movss [ebx+0x74], xmm0        ; health actually lost
...
008c42f5  call 0x7441e0                 ; body+0x30 = this DamageInfo
008c4309  mov  [esi+0xac], eax          ; and its frame
```

So `+0x70` is the hit after armour and the body's damage scalar, not clipped to the health left.
Within one frame, and the frame after it, a later hit only replaces the record under conditions on
the two attackers (`0x008C429C`-`0x008C42EF`).

### 7.3 The edit

With `min_damage` above zero, the eight bytes at `0x00857EC7` become a `jmp` and three `nop`s to a
routine placed in `.rdcan` after the dismissal cave. Nothing branches into those eight bytes. With
`min_damage` 0 (the default) they are left alone and the cave is the dismissal alone, byte for byte
the patch as it was before the option.

```asm
    test al, al                     ; hit in the last four seconds?
    je   quiet
    mov  ecx, [edi+0x25c]           ; body
    test ecx, ecx
    je   recent                     ; no body: stock answer
    mov  eax, [ecx]
    call [eax+0x40]                 ; getLastDamageInfo
    test eax, eax
    je   recent                     ; no record: stock answer
    movss xmm0, [eax+0x70]          ; dealt
    mov  eax, <min_damage as float>
    movd xmm1, eax
    comiss xmm0, xmm1
    jp   recent                     ; NaN: stock answer
    jb   quiet
recent:
    mov  byte [ebp-1], 1
    jmp  0x00857ed3
quiet:
    mov  byte [ebp-1], 0
    jmp  0x00857ed3
```

`eax`, `ecx`, `edx` and `xmm0`/`xmm1` are free here, since a call comes before the hook and another
follows at `0x00857ED9`. `edi` (the structure) and `esi` are untouched. The rubble case
(`[esi+0x25]` set) branches straight to `0x00857ECF` and never reaches the hook.

### 7.4 Choosing the value

Edain uses 5, measured over Edain-Mod `main` on 2026-11-20 from each object's default `WeaponSet`
`PRIMARY` weapon (through its warhead, without `RequiredUpgradeNames` nuggets) against the default
`ArmorSet` of every object with a `GettingBuiltBehavior` (726):

| Damage type | Units | Raw damage | Building armour | Hits that still cancel at 5 |
|---|---|---|---|---|
| `PIERCE` | 86 | 1-200 (half at 57 or less) | 0% or 1% | none |
| `CAVALRY_RANGED` | 9 | 50-125, one wagon 400 | 0% or 1% (`HouseofElrondArmor` 25%) | 0.4% |
| `HERO_RANGED` | 38 | 50-500 (most 225 or less) | 0-2%, a few 10% | 6.9% |

Two buildings, `DolGoldurPrison` and `IsengardEconomyKeep`, carry `NoArmor` and take everything
at 100%. They are left out above.

At 5, other damage types lose these shares of their hits against repairable buildings: `SLASH`
22%, `CAVALRY` 23%, `URUK` 20%, `SPECIALIST` 14%, `HERO` 4%, `SIEGE` 5% (its 0% armours). Those are
weak units against high-armour buildings (walls, fortresses), which deal under 5 per hit after
armour.

### 7.5 Limits

- **One hit is measured: the last.** A light hit after a heavy one, before the next update reads
  it, hides the heavy one. The update runs about once a second (§4), so a ram hitting alongside
  many archers cancels less often than it would alone.
- **Unupgraded weapons.** Fire arrows, forged blades and rank bonuses raise `+0x70`, and can lift
  an archer's hit over the threshold.

## 8. What the player gets

- A hit stops a worker's repair or rubble rebuild immediately. The worker fades out as it would on
  finishing.
- Auto-repair resumes `SpawnTimer` seconds after the last hit (180 s by default). The countdown
  only runs while the structure is not being hit.
- A structure without a worker (castles, walls, gates) has its repair flag cleared by the stock
  cancel, which now also reaches `SpawnTimer < 0`.
- The repair cost is not refunded. `canStartRepair` refuses a manual restart for
  `TimeAfterDamageUntilRepairAllowed` (10 s) after the last hit.
- Any damage counts, including a burning DOT, unless `--min-damage` is set: then only a hit
  dealing at least that much after armour (§7).
- A structure still being built (`isStillBuilding`, `+0x16`) is not interrupted. A non-worker
  repair out of rubble (`startRepair` with `+0x15`) is not interrupted either, because the probe
  reports no damage for it.

## 9. Determinism and composition

Everything here is logic state, so every peer must run the same patched binary. The edited engine
bytes are the two at `0x00857F38` and the eight at `0x008580AC`, and with `--min-damage` the
eight at `0x00857EC7`. The nearest other patched site in
the function is the self-build heal at `0x00857FC1` (`construction-initial-health`), outside both.

## 10. Status

- The worker dismissal and the countdown rewind have been played: the cave was installed in a
  running game with `sage_live`'s live patcher (§5), not from a patched `game.dat`. A hit faded
  the worker, nothing respawned, and auto-repair came back when the rewound countdown ran out.
- Still to watch: the gate erase on a castle wall with no worker, a manual repair restarted after
  the 10 s lockout, and one run from a patched `game.dat` on disk.
- `--min-damage` has been run under Unicorn over the real probe
  (`tests/sage_patch/test_repair_damage_cancel_min_damage.py`), not yet in a game: archers alone
  should no longer stop a worker, a ram or a battalion of swordsmen still should.
- The `wasDamagedWithin` probe has a second arm (`0x0068C94E`) for an object with a module at
  `Object+0x258` whose slot `+0x7C` answers non-NULL. Which structures take it is not established.
