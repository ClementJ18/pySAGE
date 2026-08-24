# Attack eligibility ignores whether a nugget deals damage

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000`. Read from a clean `game.dat` (11,346,944 bytes).

**Status: statically verified, not runtime-verified.** Every claim below carries its instruction.
None of it has been watched in a running game.

## The short answer

Whether object A can attack object B — for **auto-acquisition** and for a **right-click / attack
order** — ends in a check that asks *"does any nugget of this weapon have an effect on this
victim?"* and answers yes if **any** nugget's per-victim test passes. That test does not care
whether the nugget deals damage. A weapon whose only relevant nugget is a knockback
(`MetaImpactNugget`) or an `AttributeModifierNugget` therefore reports itself able to attack a
target it cannot actually hurt, which is what surfaces as "my unit keeps attacking something it
does no damage to".

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
  `mov al,1; ret` at `0x008bd372`; the base nugget and non-damaging nuggets (`MetaImpactNugget`,
  `AttributeModifierNugget`, …) return 0.
- **`+0x2c`** — returns a sub-weapon `WeaponTemplate*`. `DamageNugget` returns NULL
  (`0x00851e97`, `xor eax,eax; ret`); a `ProjectileNugget` returns the projectile's weapon, which
  is how it deals damage.

That `0x006cb6ea` falls through `+0x1c` (false) to `+0x2c` for a projectile is the proof that
`+0x1c` is false for indirect-damage nuggets and that `+0x2c` is where their damage lives.

So **"this nugget can damage the victim"** = valid-victim(`+0x04`) **AND**
( dealsDamage(`+0x1c`) **OR** hasSubWeapon(`+0x2c`) ). The `+0x2c` clause is load-bearing: without
it, a projectile-only weapon (an archer) would report itself unable to attack anything.

## The patch

Redirect the single `call 0x006cb779` at `0x006cdcd1` into a cave that repeats the walk above but
counts a nugget only when it both accepts the victim and satisfies the damage discriminator. Every
other use of `0x006cb779` is left stock. See
[`../patches/attack_requires_damage.py`](../patches/attack_requires_damage.py).

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
