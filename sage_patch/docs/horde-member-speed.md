# A horde ignores its members' `SPEED` modifiers

Static work against this repo's `game.dat` (RotWK `2.01.2614.37001`, ImageBase `0x400000`). Every
claim below is read out of the image; nothing here has been watched in a running game yet, and
§7 says exactly which parts that leaves standing on a reading rather than on evidence.

**The report.** A `ModifierList` carrying `Modifier = SPEED n%`, applied to the *member* of a
battalion, changes nothing: the battalion still advances at the pace it always did.

**Why.** A battalion is two kinds of object, and only one of them is moving. The horde container
declares its own `LocomotorSet`, pathfinds, and sets the pace; the members are formation slots
being dragged along behind it. `SPEED` is folded in by `Locomotor::getMaxSpeed`, which reads the
speed of *the object it is asked about* — so a member's modifier scales the member, and the
member is not what decides how fast the formation advances.

The tuning in stock RotWK says this outright. `menhordes.ini` gives `GondorFighterHorde` a
`Speed` of `NORMAL_FOOT_MED_HORDE_SPEED`, and `_gamedata.inc` defines it as:

```
#define NORMAL_FOOT_MED_HORDE_SPEED 50 ; RotWK originally 45  Member speed was 50
#define NORMAL_FOOT_MED_MEMBER_SPEED 55 ; A little faster so when the formation wheels the unit can catch up.
```

Two numbers hand-kept in step, the member's deliberately the larger of the two so it has headroom
to catch its slot on a turn. Raising the member's 55 to 82 with a modifier buys more headroom and
nothing else. The 50 is untouched, and the 50 is the pace.

## 1. Where `SPEED` is applied today

`Locomotor::getMaxSpeed(Object *obj)` is `0x005E3F49`, `__thiscall` on the `Locomotor`, `ret 4`.
Forty call sites reach it, including `getMaxAcceleration` (`0x005E40AD`, which divides its result
by `Acceleration`) and the move-towards-position path, so it is the one place a speed becomes a
number. Transcribed:

```c
Real Locomotor::getMaxSpeed(Object *obj)
{
    Int   state = obj->m_body->getDamageState();          // +0x25C, vtable +0x24
    Real  base  = obj->m_ai->m_locomotorSetSpeed;          // +0x260 -> +0x1F8
    Real  speed;

    if (state >= TheGlobalData[+0xB3C] && !tmpl[+0x109])   // damaged
        speed = tmpl->SpeedDamaged * G * base;             // template +0x24
    else if (this->isCharging(obj))                        // 0x005E3EF7
        speed = tmpl->ChargeSpeed * G * base;              // template +0x104
    else
        speed = G * base;                                  // G = [0x00D9F61C], 0.2

    if (speed > this->m_speedCap)      speed = this->m_speedCap;      // instance +0x28
    if (tmpl->CrewPowered)             speed *= crewFactor(obj);      // 0x0068BF11
    if (getModifierMultiplier(obj, SPEED, &m))  speed *= m;           // <-- HERE
    if (tmpl->RiverModifier != 1.0 && inRiver(obj))  speed *= tmpl->RiverModifier;
    if (this->m_speedLimit != -1.0 && this->m_speedLimit <= speed)  speed = this->m_speedLimit;
    return speed;
}
```

The modifier query is `0x005E4002`..`0x005E402D`, and it is the hook this patch takes:

```
005e4002  0f 57 c0            xorps xmm0, xmm0
005e4005  6a 01               push 1                  ; flag
005e4007  53                  push ebx                ; ctx (ebx is 0 here)
005e4008  8d 45 f8            lea  eax, [ebp-8]
005e400b  50                  push eax                ; &out
005e400c  6a 08               push 8                  ; SPEED
005e400e  8b cf               mov  ecx, edi           ; the Object
005e4010  f3 0f 11 45 f8      movss [ebp-8], xmm0     ; out = 0.0
005e4015  e8 13 88 0a 00      call 0x68c82d           ; <-- the five bytes replaced
005e401a  84 c0               test al, al
005e401c  74 0f               je   0x5e402d           ; nothing contributed: leave the speed alone
005e401e  f3 0f 10 45 f8      movss xmm0, [ebp-8]
005e4023  f3 0f 59 45 fc      mulss xmm0, [ebp-4]
005e4028  f3 0f 11 45 fc      movss [ebp-4], xmm0     ; speed *= the product of the active lists
```

`SPEED` is index **8** of the attribute-modifier name table at `0x00D8AF48`
(`ATTRIBUTE_NONE`, `ARMOR`, `DAMAGE_ADD`, `DAMAGE_MULT`, `RESIST_FEAR`, `RESIST_TERROR`,
`EXPERIENCE`, `RANGE`, `SPEED`, …), which the `push 8` names directly.

`0x0068C82D` is `Object::getModifierMultiplier(Int type, Real *out, void *ctx, Int flag)` —
`__thiscall`, `ret 0x10`, `al` is "something contributed", and it returns at its own holder guard
**without writing through `out`** for an object that has never been modified. That is why the site
seeds the slot itself, and why the cave has to as well.

## 2. Why the member's own speed is not the pace

`AIUpdate+0x1F8` is the object's speed for its **current locomotor set**, cached rather than
recomputed. It is written in exactly one place in the image — `AIUpdate::setLocomotorSet`,
`0x006680B2`:

```
006680ea  mov  eax, [esi+8]            ; the owning Object
006680ed  push dword [esi+0x1F4]       ; the locomotor set that was just chosen
006680f3  mov  ecx, [eax+4]            ; its ThingTemplate
006680f6  call 0x73dd2a                ; ThingTemplate::getSpeedForLocomotorSet
006680fb  fstp dword [esi+0x1F8]
```

and `0x0073DD2A` reads the per-set `Speed` out of the map at `ThingTemplate+0x3A0`, entry `+0x14`
— the `Speed` line inside a `LocomotorSet` block, not the `Locomotor`'s own. So the horde's speed
and the member's speed are two independent INI numbers on two independent objects, and
`getMaxSpeed` scales whichever object it was handed.

Three other `Locomotor` accessors read the same cached field and apply **no** modifier:
`getMinSpeed` (`0x005E3796`, `× MinSpeed`), `getMinTurnSpeed` (`0x005E37B5`, `× MinTurnSpeed`) and
`getBackingUpSpeed` (`0x005E36FB`, `× BackingUpSpeed`). They are lower bounds and a reverse gear;
this patch deliberately leaves all three stock (§6).

## 3. Reaching a horde's members

| | |
|---|---|
| `Object+0x258` | `ContainModuleInterface*`, NULL on anything that contains nothing |
| interface `+0x34` | the contained-items list: a pointer to an MSVC `std::list` sentinel node |
| node `+0x00` / `+0x08` | next / the member `Object*` |
| `ThingTemplate+0x115` bit `0x20` | `KINDOF HORDE` (bit 109) |
| `Object+0x98` bit `0x40` | `ObjectStatus HORDE_MEMBER` (bit 38) |

The list layout is read straight out of `0x0086620E`, a base-class walk that appears in **17**
contain vtables (`0x00C5B510` is `HordeContain`'s slot for it), which is what makes `+0x34` a
property of every contain module rather than of one:

```
0086620e  53                  push ebx
0086620f  8b d9               mov  ebx, ecx
00866211  8b 43 34            mov  eax, [ebx+0x34]         ; the sentinel node
00866214  8b 30               mov  esi, [eax]              ; the first node
00866217  3b f0               cmp  esi, eax                ; empty when they are the same
00866219  74 49               je   0x866264
0086621c  8b 7e 08            mov  edi, [esi+8]            ; the member Object
0086621f  8b 47 04            mov  eax, [edi+4]            ;   -> its ThingTemplate
...
0086625e  3b 73 34            cmp  esi, [ebx+0x34]
00866261  75 b9               jne  0x86621c
```

The status bit encoding is `Object::testStatus`'s own (`0x0044DDEC`): bit *n* is
`1 << (n & 31)` of the dword at `Object+0x94 + (n >> 5) * 4`, so `HORDE_MEMBER` is `0x40` of the
byte at `Object+0x98`.

**Why `HORDE_MEMBER` and not "everything in the list".** `HordeContain::addToContain`
(`0x0086CF2A`) *clears* `HORDE_MEMBER` for a `MACHINE`, a `HERO` or a `SIEGE_TOWER` joining the
battalion. Filtering on the bit is therefore the engine's own answer to "is this one of the rank
and file", and it is what keeps a hero who has joined a battalion — who carries none of the
battalion's upgrades — from dragging a minimum back down to 1.0.

## 4. The patch

Replace the five bytes at `0x005E4015` with a `call` into a cave that:

1. forwards to `0x0068C82D` for the object itself, into a **private** out slot, so the caller's
   `[ebp-8]` is written exactly once and only at the end;
2. returns immediately unless the object is `KINDOF HORDE` and has a contain module with a list;
3. walks the list, and for each member carrying `HORDE_MEMBER` asks `0x0068C82D` for the same
   type, aggregating with `min` (or `max`, `--aggregate`);
4. writes `*out = own × aggregate` and returns `al = 1` if **either** half contributed, otherwise
   `al = 0` with `*out` untouched.

The type, the ctx and the flag are forwarded from the caller's own arguments rather than
hard-coded, so the cave is a widening of the query the site already makes and not a second,
differently-shaped one.

**It is bit-exact-neutral wherever it changes nothing.** An object with no horde members
contributing takes path 4's `al = 0` arm and the caller skips the multiply, byte for byte as
stock. A horde whose own modifier is the only one active gets `own × 1.0f`, which is exact. Only
a horde with a modifier-carrying member sees a different number.

### The cave

```
    push  ebp
    mov   ebp, esp
    sub   esp, 0x10               ; [ebp-4] own, [ebp-8] the private out, [ebp-0xC] the aggregate
    push  ebx / esi / edi
    mov   edi, ecx                ; the Object
    mov   dword [ebp-4],  1.0
    mov   dword [ebp-0xC], 1.0
    xor   ebx, ebx                ; contributed

    push  [ebp+0x14] / [ebp+0x10] / &[ebp-8] / [ebp+8]
    mov   ecx, edi
    call  0x0068C82D              ; ret 0x10 - cleans all four
    test  al, al
    je    .horde
    mov   ebx, 1
    movss xmm0, [ebp-8]
    movss [ebp-4], xmm0

.horde:
    mov   eax, [edi+4]
    test  byte [eax+0x115], 0x20  ; KINDOF HORDE
    je    .done
    mov   edi, [edi+0x258]        ; the contain interface
    test  edi, edi
    je    .done
    mov   esi, [edi+0x34]         ; the sentinel node
    test  esi, esi
    je    .done
    mov   edi, [esi]
.loop:
    cmp   edi, esi
    je    .done
    mov   eax, [edi+8]            ; the member
    test  eax, eax
    je    .next
    test  byte [eax+0x98], 0x40   ; HORDE_MEMBER
    je    .next
    mov   ecx, eax
    push  [ebp+0x14] / [ebp+0x10] / &[ebp-8] / [ebp+8]
    call  0x0068C82D
    test  al, al
    je    .next
    mov   ebx, 1
    movss xmm0, [ebp-8]
    comiss xmm0, [ebp-0xC]
    jae   .next                   ; `jbe` for --aggregate max
    movss [ebp-0xC], xmm0
.next:
    mov   edi, [edi]
    jmp   .loop

.done:
    test  ebx, ebx
    je    .none
    mov   eax, [ebp+0xC]          ; the caller's out pointer
    movss xmm0, [ebp-4]
    mulss xmm0, [ebp-0xC]
    movss [eax], xmm0
    mov   al, 1
    jmp   .epilogue
.none:
    xor   al, al
.epilogue:
    pop   edi / esi / ebx
    mov   esp, ebp
    pop   ebp
    ret   0x10
```

**Registers.** The caller reads `al`, `[ebp-8]`, `[ebp-4]` and keeps `ebx`, `esi`, `edi` and `ebp`
live across the call, so the cave saves the three it uses and restores `esp` from `ebp`. `xmm0` is
reloaded by the caller at `0x005E401E` and every XMM register is volatile across a call anyway,
which is why the accumulators live on the stack rather than in registers. `ecx` is not preserved
by `0x0068C82D`, so the member pointer is re-established from `[edi+8]` on every iteration.

## 5. Choosing the aggregate

`min` is the default because a formation moves at the pace of its slowest rank, and because a slow
is the case where the wrong answer is a balance bug rather than a cosmetic one: `SPEED 0%` is how
RotWK's own `attributemodifier.ini` writes "cannot move" (six lists use it), and a battalion that
keeps marching because eleven of its twelve members are unrooted is worse than one that stops.

`--aggregate max` is offered for the mirror-image reading — one buffed member speeds the whole
battalion — and is the safer choice for a mod that applies speed buffs through something that can
miss a member, such as a radius-limited `AttributeModifierNugget`.

Neither is a substitute for putting the modifier on the horde as well, which has always worked and
still does.

## 6. What this deliberately does not reach

- **`MinSpeed`, `MinTurnSpeed`, `BackingUpSpeed`** (§2). All three scale the same cached
  `AIUpdate+0x1F8` and apply no modifier at all; a member modifier does not move them, and neither
  does the horde's own, so the patch leaves the stock relationship intact.
- **`AttributeModifier` types other than `SPEED`.** The cave forwards whatever type the caller
  pushed, and the only caller is this one site, which pushes 8. Nothing else about the modifier
  system changes.
- **A horde inside a horde.** The walk goes one level. A combo horde's members are its own
  members, not its components' members.
- **The horde's own modifier.** Unchanged, and multiplied with the aggregate rather than replaced
  by it, so a mod that already buffs the container keeps exactly the number it had.

## 7. What is read and what is watched

Everything above is static. The parts that a running game has **not** yet confirmed, in the order
they would break the patch if wrong:

1. That the pace a player sees really is `getMaxSpeed(hordeObject)` and not some second clamp
   further down `locoUpdate_moveTowardsPosition` (`0x005E4F44`). The INI tuning in the header is
   strong circumstantial evidence and the 40 call sites all funnel here, but "the battalion got
   faster" has not been observed.
2. That `+0x34` on a live `HordeContain` interface holds the members and not, say, a payload
   template list. `0x0086620E`'s walk reads `[node+8]->tmpl` and tests a `KindOf` on it, which
   only makes sense for objects — but reading a battalion's list out of a live game with
   `sage_live` is one command and would settle it.
3. That the per-frame cost is invisible. The walk is at most `Slots` iterations of a cheap query
   per `getMaxSpeed` call **on a horde**; every other object pays one `test` and a not-taken
   branch. No measurement has been taken.

## 8. Appendix — every address this document depends on

| VA | meaning |
|---|---|
| `0x0044DDEC` | `Object::testStatus(bit)` — the status bit encoding |
| `0x005E36FB` | `Locomotor::getBackingUpSpeed(obj)` — reads `AIUpdate+0x1F8`, no modifier |
| `0x005E3796` | `Locomotor::getMinSpeed(obj)` — likewise |
| `0x005E37B5` | `Locomotor::getMinTurnSpeed(obj)` — likewise |
| `0x005E3EF7` | `Locomotor::isCharging(obj)` — picks `ChargeSpeed` over the plain path |
| `0x005E3F49` | **`Locomotor::getMaxSpeed(obj)`** — the function this patch hooks inside |
| `0x005E4002` | its `SPEED` query setup: `push 1 / push ctx / push &out / push 8` |
| `0x005E4015` | its `call 0x0068C82D` — the five bytes replaced |
| `0x005E401A` | the fold that consumes the result: `test al,al / je / mulss` |
| `0x005E40AD` | `Locomotor::getMaxAcceleration(obj)` — calls the above, so it scales too |
| `0x005E4F44` | `Locomotor::locoUpdate_moveTowardsPosition` |
| `0x006680B2` | `AIUpdate::setLocomotorSet` — the only writer of `AIUpdate+0x1F8` |
| `0x0068C82D` | `Object::getModifierMultiplier(type, out, ctx, flag)`, `ret 0x10` |
| `0x0073DD2A` | `ThingTemplate::getSpeedForLocomotorSet(set)` — the `LocomotorSet`'s `Speed` |
| `0x0086620E` | the contain base's member walk — the `+0x34` list layout |
| `0x0086CF2A` | `HordeContain::addToContain` — clears `HORDE_MEMBER` for `MACHINE`/`HERO`/`SIEGE_TOWER` |
| `0x00872A6F` | `getHordeIface`, contain interface `+0x7C` |
| `0x00C5B480` | the `HordeContain` contain-interface vtable (`this` = module `+0x20`) |
| `0x00D8AF48` | the attribute-modifier name table; index 8 is `SPEED` |
| `0x00D9F61C` | the 0.2 scale every locomotor speed accessor multiplies by |
