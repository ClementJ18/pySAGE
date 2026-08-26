# Attack eligibility ignores whether a nugget deals damage

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000`. Read from a clean `game.dat` (11,346,944 bytes).

**Status: mostly statically verified.** Every claim below carries its instruction. The one part
that has been watched in a running game is the `HordeAttackNugget` defect below - it was found by
a live match in which nothing acquired a target.

## The short answer

Whether object A can attack object B — for **auto-acquisition** and for a **right-click / attack
order** — ends in a check that asks *"does any nugget of this weapon have an effect on this
victim?"* and answers yes if **any** nugget's per-victim test passes. That test does not care
whether the nugget does anything worth attacking for. A weapon whose only relevant nugget is a
knockback (`MetaImpactNugget`) or an `AttributeModifierNugget` therefore reports itself able to
attack a target it cannot actually hurt, which is what surfaces as "my unit keeps attacking
something it does no damage to".

Narrowing it correctly turns out to need a **named list of nugget kinds**, not a property read off
the nugget - see [the discriminator is wrong](#the-discriminator-is-wrong-and-the-fix-is-a-named-list).

## The chain

```
Object::getAbleToAttackSpecificObject          0x0068d6a6   (thiscall, ret 0xc)
  -> WeaponSet::getAbleToAttackSpecificObject   0x006c9147   relationship / status gating
     -> 0x006c8652                              returns 0 / 2 / 3; 2 and 3 == attackable
        -> 0x006cdbf3                           "is victim a valid attack target for this weapon"
           -> 0x006cb779   @ call site 0x006cdcd1   <-- the nugget check this patch gates
```

`0x006cdbf3` is a pure boolean target-eligibility predicate: all five of its callers
(`0x006c894b`, `0x006c8bf2`, `0x0082c41c`, `0x00910e76`, `0x00911a4a`) are `call; test al`
eligibility checks, none an apply/fire site. Its final answer is the return value of the nugget
check it makes at `0x006cdcd1`.

## The nugget check — `0x006cb779`

`WeaponTemplate::<any-nugget-accepts-victim>` — `__thiscall`, `ret 8`, `this` = `WeaponTemplate`,
stack args `victim` at `[esp+4]` and `weapon` at `[esp+8]`. It walks the nugget vector at
`WeaponTemplate+0x17c` (an MSVC `std::list`; each node's nugget pointer is at `node+0x08`) and, for
each nugget, calls vtable slot `+0x04` — "is this a valid victim". It returns TRUE on the **first**
nugget that accepts, regardless of what that nugget does:

```
006cb779  cmp  [esp+4], 0            ; victim != NULL
006cb787  mov  eax, [edi+0x17c]      ; &nugget list head (edi = WeaponTemplate)
006cb78e  mov  esi, [eax]            ; first node
006cb794  push [esp+0xc]            ; victim
006cb798  mov  ecx, [esi+8]          ; the nugget
006cb79b  push [esp+0x14]           ; weapon
006cb79f  mov  eax, [ecx]            ; nugget vtable
006cb7a1  call [eax+4]               ; +0x04 = "is this a valid victim"
006cb7a4  test al, al
006cb7a6  jne  <return 1>            ; ANY nugget accepts -> weapon can affect target
006cb7a8  mov  esi, [esi]            ; next node
006cb7b0  jne  <loop>
006cb7b2  xor  al, al                ; no nugget accepted -> 0
```

The victim-test slot for a `DamageNugget` is `0x0090e855` (nugget vtable `0x00c7ae78`, slot
`+0x04`).

### The three callers of `0x006cb779`, and why only one is patched

| call site | what it is | patched? |
|---|---|---|
| `0x006cdcd1` | the attack-eligibility path (`0x006cdbf3`) | **yes** |
| `0x0090f527` | a sub-weapon nugget's own `+0x04` (valid-victim), recursion **and firing** | no |
| `0x0090f97e` | another sub-weapon nugget's `+0x04`, same | no |

Redirecting only the `call` at `0x006cdcd1` gates every attack-eligibility use — auto-acquire,
attack-move, right-click — uniformly, while leaving the nugget-level valid-victim test the fire
loop uses untouched. So a knockback still knocks back once the weapon is engaged on a legitimately
damageable enemy; it just no longer *causes* the engagement on its own.

## The damage discriminator

The engine already distinguishes damaging from non-damaging nuggets, in `0x006cb6ea`
("does this weapon deal damage type N"), through two nugget vtable slots:

- **`+0x1c`** — a boolean "this nugget deals direct damage". `DamageNugget` overrides it to
  `mov al,1; ret` at `0x008bd372`; the base nugget and `MetaImpactNugget` return 0. **It is not a
  reliable reading of "worth attacking for":** `AttributeModifierNugget`, `ParalyzeNugget`,
  `FireLogicNugget` and `EmotionWeaponNugget` all return 1 from it, and `HordeAttackNugget`,
  `SlaveAttackNugget`, `DamageFieldNugget` and `GrabNugget` all return 0. The table below has the
  measurements.
- **`+0x2c`** — returns a sub-weapon `WeaponTemplate*`. `DamageNugget` returns NULL
  (`0x00851e97`, `xor eax,eax; ret`); a `ProjectileNugget` returns the projectile's weapon, which
  is how it deals damage.

That `0x006cb6ea` falls through `+0x1c` (false) to `+0x2c` for a projectile is the proof that
`+0x1c` is false for indirect-damage nuggets and that `+0x2c` is where their damage lives.

That suggests **"this nugget can damage the victim"** = valid-victim(`+0x04`) **AND**
( dealsDamage(`+0x1c`) **OR** hasSubWeapon(`+0x2c`) ).

**It does not work, in both directions.** See the next section: that pair of getters is not a
reading of "this nugget is a reason to attack", and using it stops most of the game attacking.

## The discriminator is wrong, and the fix is a named list

**Runtime-observed.** A live match on the patched binary had nothing acquiring anything - hordes
walked past each other and past the creeps without ever engaging.

Reading every nugget's vtable out of the parse table at `0x00C17458` (rows of
`{name, parseFn, 0, 0}`; each parse function's `call OPERATOR_NEW` is followed by the constructor,
which stores the vtable) and asking both getters gives this:

| nugget | vtable | `+0x1c` | `+0x2c` | getters say | should be |
|---|---|---|---|---|---|
| `DamageNugget` | `0x00c7ae78` | true | NULL | attack | **attack** |
| `ProjectileNugget` | `0x00c7b538` | false | sub-weapon | attack | **attack** |
| `DOTNugget` | `0x00c7bae8` | true | NULL | attack | **attack** |
| `DamageContainedNugget` | `0x00c7ba60` | true | NULL | attack | **attack** |
| `DamageFieldNugget` | `0x00c7b3a8` | false | NULL | *skip* | **attack** |
| `GrabNugget` | `0x00c7b970` | false | NULL | *skip* | **attack** |
| `HordeAttackNugget` | `0x00c7bcac` | false | NULL | *skip* | **attack** |
| `SlaveAttackNugget` | `0x00c7b9b0` | false | NULL | *skip* | **attack** |
| `AttributeModifierNugget` | `0x00c7b1c8` | **true** | NULL | *attack* | **skip** |
| `ParalyzeNugget` | `0x00c7b328` | **true** | NULL | *attack* | **skip** |
| `FireLogicNugget` | `0x00c7bf68` | **true** | NULL | *attack* | **skip** |
| `EmotionWeaponNugget` | `0x00c7bbc0` | **true** | NULL | *attack* | **skip** |
| `MetaImpactNugget` | `0x00c7b848` | false | NULL | skip | skip |
| `WeaponOCLNugget` | `0x00c7b410` | false | NULL | skip | skip |
| `SpawnAndFadeNugget` | `0x00c7bd60` | false | NULL | skip | skip |
| `SpecialModelConditionNugget` | `0x00c7b25c` | false | NULL | skip | skip |
| `OpenGateNugget` | `0x00c7bb44` | false | NULL | skip | skip |
| `StealMoneyNugget` | `0x00c7bc30` | false | NULL | skip | skip |
| `LuaEventNugget` | `0x00c7be28` | false | NULL | skip | skip |

Two independent failures:

**`+0x1c` is true for things that are not a reason to attack.** `AttributeModifierNugget`'s vtable
`+0x1c` is `DAMAGE_NUGGET_DEALS_DAMAGE_BODY` - literally the same `mov al,1; ret` that
`DamageNugget` uses. So the nugget named in this document's opening paragraph as a motivating case
*was never excluded by the discriminator at all*, and neither were `ParalyzeNugget`,
`FireLogicNugget` or `EmotionWeaponNugget`.

**Both are false for things that are.** The worst is `HordeAttackNugget` (`0x00c7bcac`, stored by
its constructor `0x00911b39` at `0x00911b41`). Its `+0x1c` is `0x009188eb` - `xor al,al; ret` - and
its `+0x2c` is `DAMAGE_NUGGET_SUBWEAPON_BODY`, NULL. Yet its damage is real, one indirection
further out than a projectile's: `+0x04` (`0x009119cb`) resolves the victim through
`GAME_LOGIC_FIND_OBJECT_BY_ID` and dispatches into the target horde to ask the members' own weapon.

```
009119d5  call 0x90d77c            ; base valid-victim
009119e8  call 0x449681            ; GAME_LOGIC_FIND_OBJECT_BY_ID  ([esi+8] = victim id)
009119f3  cmp  dword ptr [esi + 0x258], 0
009119fe  call 0x68c866            ; the target's horde/contain interface
00911a17  call dword ptr [eax + 0x50]
```

**Why that one takes the whole game down rather than one unit.** A horde does not acquire with its
members' weapons; it carries a *rangefinder* weapon whose only nugget is this one. Edain's
`weapon.ini` and `includes/*.inc` define 61 weapons carrying a `HordeAttackNugget`, and in **60 of
them it is the only nugget** - including the generic `NormalMeleeHordeRangefinder`,
`NormalPikeHordeRangefinder` and `NormalMissileHordeRangefinder` that the standard hordes of every
faction use:

```
Weapon SchattenbinderMissileHordeRangefinder
    AttackRange             = 250.0
    DelayBetweenShots       = 1000
    AcceptableAimDelta      = 45
    MeleeWeapon             = Yes
    FinishAttackOnceStarted = No

    HordeAttackNugget
    End
End
```

No damage nugget at all. Under the getters, every one of these reports itself unable to attack
anything, so the hordes carrying them never acquire a target.

**Nothing in the vtable separates the two groups**, so the patch names them instead:
`ATTACK_NUGGET_VTABLES` is the eight rows marked **attack** above, compared by vtable identity. The
getters are not consulted at all - which also makes the cave one vtable call per nugget cheaper
than the stock routine it replaces.

## The patch

Redirect the single `call 0x006cb779` at `0x006cdcd1` into a cave that repeats the walk above but
counts a nugget only when its vtable is one of `ATTACK_NUGGET_VTABLES` **and** it accepts the
victim. Every other use of `0x006cb779` is left stock. See
[`../patches/attack_requires_damage.py`](../patches/attack_requires_damage.py).

Each allowlisted vtable is anchored by the `mov dword ptr [esi], <vtable>` in its own constructor
(`ATTACK_NUGGET_VTABLE_STORES`), reached from that nugget's row of the parse table - so a build
that laid the nuggets out differently fails on apply rather than allowlisting the wrong eight.

This changes which targets a logic-side order reaches, so **every peer must run the same patched
binary** and replays do not cross — the same requirement `multi-execute-gate` and `spawn-union`
carry.

## Every address this document depends on

| VA | meaning |
|---|---|
| `0x0068d6a6` | `Object::getAbleToAttackSpecificObject`, `ret 0xc` |
| `0x006c9147` | `WeaponSet::getAbleToAttackSpecificObject` — relationship/status gating |
| `0x006c8652` | returns 0 / 2 / 3; 2 and 3 mean attackable |
| `0x006cdbf3` | "is victim a valid attack target for this weapon" — boolean predicate |
| `0x006cdcd1` | **the hooked call** — `call 0x006cb779` (`e8 a3 da ff ff`) |
| `0x006cb779` | walk the nugget vector; TRUE if any nugget's `+0x04` accepts the victim |
| `0x006cb6ea` | "does this weapon deal damage type N" — uses `+0x1c`, `+0x28`, `+0x2c` |
| `0x0090f527` / `0x0090f97e` | sub-weapon nuggets' `+0x04`; left stock |
| `0x00c7ae78` | `DamageNugget` vtable; `+0x04` = `0x0090e855` (valid victim) |
| `0x008bd372` | `DamageNugget` vtable `+0x1c` — `mov al,1; ret` (deals damage) |
| `0x00851e97` | `DamageNugget` vtable `+0x2c` — `xor eax,eax; ret` (no sub-weapon) |
| `+0x17c` | `WeaponTemplate` nugget vector; node's nugget pointer at `+0x08` |
| `0x00c17458` | the nugget parse table - rows of `{name, parseFn, 0, 0}` |
| `0x0042f6e0` | `OPERATOR_NEW`; the call after it in a parse fn is the nugget's constructor |
| `0x00911b39` | `HordeAttackNugget`'s constructor; `0x00911b41` stores its vtable |
| `0x00c7bcac` | **`HordeAttackNugget` vtable** - `+0x1c` false, `+0x2c` NULL |
| `0x009119cb` | its `+0x04`, which asks the target horde's members' own weapon |
| `0x009188eb` | `xor al,al; ret` - the "deals no direct damage" body |
| `0x00c7b1c8` | `AttributeModifierNugget` vtable - `+0x1c` is `mov al,1`, i.e. **true** |
| `0x00c17458` | the nugget parse table - rows of `{name, parseFn, 0, 0}` |
| `0x006cd8ea` | `HordeAttackNugget`'s parse function |
| `0x00911b39` | `HordeAttackNugget`'s constructor; `0x00911b41` stores the vtable |
| `0x00c7bcac` | **`HordeAttackNugget` vtable** - `+0x1c` false, `+0x2c` NULL |
| `0x009119cb` | its `+0x04`, which asks the target horde's members' own weapon |
| `0x009188eb` | `xor al,al; ret` - the "deals no direct damage" body |
