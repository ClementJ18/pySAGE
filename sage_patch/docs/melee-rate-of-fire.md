# Making melee attacks respect `RATE_OF_FIRE`

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000` for everything cited here. Read from the repo's own `game.dat`
(11,346,944 bytes).

**Verdict up front: melee is not excluded by a check — there is nothing to unblock.**
`RATE_OF_FIRE` is consulted at **exactly one instruction in the whole binary**
(`0x006cf03e`), and it scales **exactly one** of the four clocks an attack runs on:
`DelayBetweenShots`. A melee unit spends its cycle in the other three
(`PreAttackDelay` and `FiringDuration`), so the modifier multiplies a number that is already
zero-ish and nothing visibly changes. The patch is therefore not "remove a melee gate", it is
"apply the multiplier to the two clocks that carry a melee swing".

That makes it cheap — no structure grows, no INI keyword, no field table, no ctor/dtor:

- **Cost:** 3 instruction-site repoints (+1 optional) and ~150 bytes of cave.
- **Risk:** *medium*, and all of it is in one question — whether the swing **animation** follows a
  shortened `FiringDuration` or gets truncated. See
  [The one thing that needs a live test](#the-one-thing-that-needs-a-live-test). Scaling
  `PreAttackDelay` alone is low-risk and is most of the win; that is why the recipe is staged.
- **Status:** **scoped, not built.**

## The one consumer

`RATE_OF_FIRE` is index **21** (`0x15`) in the attribute-modifier type table at `0x00d8af48`
(`ATTRIBUTE_NONE` is index 0, `RECHARGE_TIME` is 12 — which independently confirms the indexing
against [`spell-recharge-filter.md`](spell-recharge-filter.md)).

The lookup is `0x0068c82d`, `__thiscall(ecx = Object*, type, float* out, 0, 1)`, `ret 0x10`. It
forwards to the accumulator at `0x00804fff`, which writes `1.0f` into `*out` and then multiplies in
every active modifier of that type — so an object with no modifiers yields exactly `1.0` and a
caller cannot tell the difference from not calling at all.

Every request for type `0x15` in the binary:

```
006cf021  movss xmm0, [0xbd1908]   ; 1.0f
006cf030  movss [ebp-8], xmm0      ;   seeded, though the callee overwrites it anyway
006cf035  je   0x6cf047            ; no source object -> skip
006cf037  push 1
006cf039  push 0
006cf03a  lea  eax, [ebp-8] / push eax
006cf03e  push 0x15                ;   <-- RATE_OF_FIRE, the only one
006cf040  mov  ecx, esi            ; the firing Object
006cf042  call 0x68c82d
006cf047  fld  [ebp-8]             ; the multiplier, consumed once:
006cf055  call 0x6ca066            ;   WeaponTemplate::getDelayBetweenShots(bonus, rof)
```

This was established by scanning every call site of `0x0068c82d` **and** of the accumulator
`0x00804fff` for the type they push (`0x15` appears at one of them), plus checking that the imm32
form `68 15 00 00 00` occurs nowhere in `.text`. `0x006cf03e` is it.

`WeaponTemplate::getDelayBetweenShots` (`0x006ca066`) is:

```
delayFrames = (min == max) ? min : GameLogicRandomValue(min, max)   ; tmpl+0xf0 / tmpl+0xf4
return floor(delayFrames / (weaponBonus[RATE_OF_FIRE] * rofModifier))
```

Note the **division**: a `RATE_OF_FIRE 150%` modifier yields `1.5` and shortens the delay. Any
extension has to divide too, not multiply — `PreAttackDelay`'s existing weapon bonus multiplies
(below), so the two conventions are opposite and easy to get backwards.

## The four clocks of an attack

`Weapon::getStatus` (`0x006cd142`) is the whole cadence, and it reads three different frame stamps
on the `Weapon` instance. The status names come from the table at `0x00da182c`
(`READY_TO_FIRE`, `OUT_OF_AMMO`, `BETWEEN_FIRING_SHOTS`, `RELOADING_CLIP`, `PRE_ATTACK`, `FIRING`,
`IN_FOLLOW_THRU`):

```
006cd14e  cmp now, [weapon+0x1c] / jb  -> 4  PRE_ATTACK
006cd166  cmp now, [weapon+0x20] / jb  -> 5  FIRING
006cd183  cmp now, [weapon+0x18] ...   -> 2  BETWEEN_FIRING_SHOTS / 0 READY_TO_FIRE
```

The AI only fires when `getStatus()` returns `0` (e.g. `0x007519cb`), so **all three windows block
the next swing**. Where each stamp comes from:

| stamp | set at | value | scaled by weapon bonus | scaled by `RATE_OF_FIRE` |
|---|---|---|---|---|
| `weapon+0x1c` (pre-attack ends) | `0x006ce9be` | `now + PreAttackDelay` | `bonus[4]` (`PRE_ATTACK`) | **no** |
| `weapon+0x20` (firing ends) | `0x006cf31b` | `now + FiringDuration` | none | **no** |
| `weapon+0x18` (may fire again) | `0x006cf2fd` | `now + DelayBetweenShots` | `bonus[3]` (`RATE_OF_FIRE`) | **yes** |
| `weapon+0x24` (both) | `0x006ce9d9` | `now + PreAttackDelay + FiringDuration` | inherits | inherits |
| clip reload | `0x006ce916` | `ClipReloadTime` (`0x006ca0c0`) | `bonus[3]` | **no** |

The formulas, stated canonically by two out-of-line copies the compiler kept but nothing calls
(they are inlined at every real site — which is why they have zero references):

```
006ca123  WeaponTemplate::getPreAttackDelay(bonus):
            cvtsi2ss xmm0, [tmpl+0x138]    ; PreAttackDelay
            mulss    xmm0, [bonus+0x10]    ; bonus[4] = PRE_ATTACK — a MULTIPLY
            cvttss2si eax, xmm0

006ca13b  WeaponTemplate::getFiringDuration():
            mov eax, [tmpl+0x144]          ; FiringDuration — raw, no bonus at all
```

The live copies are at `0x006cdd61` / `0x006ce9e5` (pre-attack) and `0x006ce9c1` / `0x006cf306`
(firing duration).

### A supporting oddity

The weapon-bonus field table at `0x00da179c` is
`DAMAGE, RADIUS, RANGE, RATE_OF_FIRE, PRE_ATTACK, FIRING` — six floats, indices 0..5 at array
offsets `0x00..0x14`. `bonus[3]` and `bonus[4]` are consumed as tabulated above; **`bonus[5]`
(`FIRING`) has no reader** — a targeted scan of the weapon module finds it written by the
`WeaponBonusSet` parser (`0x006c9d93`) and read nowhere. The engine has a slot for scaling the
firing window, parses it, and drops it. That is a second, independent statement that
`FiringDuration` is unscaled by design or by omission.

## Why melee sees nothing

Nothing tests `MeleeWeapon` on this path. The flag (`WeaponTemplate+0x125`) is read at exactly one
place in the binary, `0x006cc083`, inside a targeting check — not in any timing code.

The cause is arithmetic, not a branch. A melee swing's cycle is

```
PreAttackDelay (wind-up)  ->  fire  ->  FiringDuration (follow-through)  ->  DelayBetweenShots
```

and melee weapons put their whole cadence in the first and third terms, because those are the ones
the swing animation occupies; `DelayBetweenShots` is typically `0`. Scale a term that is zero and
nothing happens. A ranged weapon does the opposite — the wind-up is short, the reload is the
cadence — which is why the same modifier visibly works there.

`PreAttackDelay` is paid **every swing** when `PreAttackType = PER_SHOT` (type table at
`0x00da16cc`: `PER_SHOT`, `PER_ATTACK`, `PER_CLIP`, `PER_POSITION`). `Weapon::getPreAttackDelay`
(`0x006cdd10`) short-circuits to `0` for the other three when the clip/target/position has not
changed, so `PER_SHOT` is the case where this patch buys the most:

```
006cdd20  mov  ecx, [tmpl+0x12c]      ; PreAttackType
006cdd26  cmp  ecx, 2 (PER_CLIP)      ; -> 0 unless the clip just refilled
006cdd7c  cmp  ecx, 1 (PER_ATTACK)    ; -> 0 unless the victim changed
006cdd94  cmp  ecx, 3 (PER_POSITION)  ; -> 0 unless the position changed
006cdd5e  cvtsi2ss xmm0, [tmpl+0x138] ; PER_SHOT falls straight through: every shot
006cdd69  mulss xmm0, [ebp-8]         ;   * bonus[4]
006cdd72  add  eax, [weapon+0x58]     ;   + a per-instance extra
```

**Not verified here:** that any *particular* mod's melee weapons are authored that way. There is
no INI corpus on this machine to cite. It is a two-minute check on your own data — read
`PreAttackDelay`, `PreAttackType`, `FiringDuration` and `DelayBetweenShots` off one melee weapon
and the effect of this patch is predictable to the frame. The design does not change either way,
since it covers both terms.

## The design decision

**Should the extension apply to every weapon, or only to `MeleeWeapon = Yes`?**

Applying it to everything is one instruction cheaper per site but it **changes existing balance**:
every `Modifier = RATE_OF_FIRE …` in a shipping mod would suddenly also compress every ranged
unit's wind-up and follow-through, on top of the reload it already compresses. That is a
behaviour change nobody asked for, in a value modders have already tuned around.

**Recommendation: gate on `MeleeWeapon` (`WeaponTemplate+0x125`)** — `cmp byte [tmpl+0x125], 0 / je
stock`, 8 bytes per site. Ranged weapons then take the stock path bit-for-bit, and the patch does
literally what its name says. The honest cost: the flag is only consulted today by one targeting
check, so a mod that never bothered setting it on its melee weapons will see no effect until it
does — and setting it has that small targeting side effect. A `--all-weapons` switch on the patch
covers the other preference; it is the same cave with the gate omitted.

## The recipe

Three sites, one cave section (`sage_patch.utils.allocate_section`). Every site is a single
instruction ≥ 5 bytes, so each hosts a `call rel32` with padding; nothing needs a trampoline and
no structure changes size.

| # | site | stock bytes | what it loads |
|---|---|---|---|
| 1 | `0x006cf306` | `8b 80 44 01 00 00` | `FiringDuration` in `fireWeapon` |
| 2 | `0x006ce9c1` | `8b 86 44 01 00 00` | `FiringDuration` in `preFireWeapon` |
| 3 | `0x006cdd61` | `f3 0f 2a 80 38 01 00 00` | `PreAttackDelay` in `getPreAttackDelay` |
| 4 | `0x006ce9e5` | `db 86 38 01 00 00` | the `LeechRangeWeapon` copy of pre-attack — optional |

The template pointer is live in a register at all four (`eax`, `esi`, `eax`, `esi` respectively),
so the melee gate costs nothing extra. The multiplier is the only thing that differs:

- **Site 1 already has it** — `fireWeapon` computed it into `[ebp-8]` twenty instructions earlier.
  Free.
- **Sites 2, 3 and 4 must fetch it.** Both frames carry the source `Object*` in the same place:
  `preFireWeapon`'s first argument `[ebp+8]` and `getPreAttackDelay`'s `ebx`
  (`mov ebx, [ebp+8]` at `0x006cdd17`). Both are the pointer those functions themselves pass to the
  weapon-bonus builder `0x006ca7ac`, so they are the right object by construction.

A shared helper keeps sites 2-4 to a few bytes each:

```asm
cave_rof:                          ; ecx = Object* -> xmm0 = the RATE_OF_FIRE multiplier
    push ecx                       ; reserve the out float
    mov  edx, esp
    push 1
    push 0
    push edx
    push 0x15
    call 0x68c82d                  ; ret 0x10; writes 1.0 when nothing applies
    movss xmm0, [esp]
    pop  ecx
    ret                            ; ~28 bytes
```

and each site becomes: gate on `MeleeWeapon`, load the stock value, `cvtsi2ss`, `divss` by the
multiplier, `cvttss2si`, clamp, return. Two guards are not optional:

- **`rof <= 0`** — a modifier of `0%` would divide by zero and `cvttss2si` turns the resulting
  infinity into `0x80000000`, i.e. a hugely *negative* frame count. Skip to the stock value.
  (The stock `getDelayBetweenShots` has this same hazard today and no guard; do not copy that.)
- **result `< 1`** — clamp up when the stock value was `> 0`, so a large modifier cannot collapse
  a window to zero frames. `FiringDuration <= 0` already means "no window" at both sites
  (`0x006ce9c7`, `0x006cf30c` both `jle` past the store), and that invariant must survive.

`PreAttackDelay` at site 3 keeps its existing `* bonus[4]` and gains `/ rof`; the `+ [weapon+0x58]`
that follows stays unscaled, matching how the weapon bonus already behaves.

### Staging

**Stage 1 is site 3 alone** (plus site 4 for symmetry). It is low-risk: the engine already expects
`PreAttackDelay` to vary at runtime — that is what `bonus[4]` is for — so scaling it further is
inside behaviour the engine was written for, and for `PreAttackType = PER_SHOT` melee it is most
of the cadence.

**Stage 2 adds sites 1 and 2** (`FiringDuration`), behind its own switch, once the animation
question below has an answer from a real match.

### Cave budget

| block | bytes |
|---|---|
| `cave_rof` helper | ~28 |
| site 1 stub (multiplier already in frame) | ~34 |
| sites 2 / 3 / 4 stubs | ~40 each |
| **total** | **~180** |

One `0x1000` section.

## The one thing that needs a live test

**Nothing in `Weapon` tells the drawable how long the swing may take.** The animation and the
`FIRING` window are independent clocks: the model condition is set around pre-fire (`0x006921d9`
builds the condition bitset and `0x005e3b79` applies it) and the W3D animation then plays at its
own speed. Shortening `weapon+0x20` does not speed the animation up — it ends the window earlier,
and the state machine is free to start the next swing on top of an animation still playing, which
would show as a truncated or restarted swing.

That is a prediction from the code, not an observation. It is also cheap to settle **before writing
any bytes**: halve `FiringDuration` on one melee weapon in INI and watch the unit. If the swing
still reads correctly, site 1 and 2 are safe as described; if it stutters, `FiringDuration` needs
to stay out of the patch (stage 1 only) or the patch needs to reach the drawable too, which is a
different and much larger job.

The same experiment on `PreAttackDelay` predicts stage 1 exactly, since the patch does to it
precisely what a smaller INI value would.

## Known rough edges

- **Two different things are called `RATE_OF_FIRE`.** The attribute-modifier type (index 21, from
  a `ModifierList` block's `Modifier = RATE_OF_FIRE 150%`) and the weapon-bonus field (index 3,
  from `WeaponBonus = <condition> RATE_OF_FIRE 150%`). This patch is about the first. They meet
  only in `getDelayBetweenShots`, which multiplies them together. Anyone reading the patch will
  confuse them once; the docs should name them apart.
- **Melee weapons that do not set `MeleeWeapon = Yes`** get nothing from the gated build. That is
  the price of not touching ranged balance; `--all-weapons` is the escape hatch.
- **`ClipReloadTime` stays unscaled** (`0x006ca0c0`, `bonus[3]` only). Irrelevant to melee, which
  does not use clips, but it is the obvious fifth site if "RATE_OF_FIRE should mean rate of fire"
  is the goal rather than "melee should benefit".
- **`IdleAfterFiringDelay` / `HoldAfterFiringDelay`** (`tmpl+0x78` / `+0x7c`, read at
  `0x006cd17d`) also go unscaled. They gate the return to idle rather than the next swing, so they
  are outside the cadence — but a unit whose swing rate doubles while its hold time does not may
  look odd.
- **Determinism.** Everything here is integer frame arithmetic on values every client computes the
  same way, so replays and multiplayer stay in sync **provided every player runs the same patched
  binary** — the usual condition for this repo's patches. The float division is IEEE and the
  `cvttss2si` truncation is deterministic.
- **Conflicts.** Nothing in the current `PATCHES` registry touches `0x006cf306`, `0x006ce9c1`,
  `0x006cdd61`, `0x006ce9e5` or anything in the weapon module.
- **Verification.** `verify` should assert the four stock instruction encodings above, the
  `push 0x15 / mov ecx,esi / call 0x68c82d` sequence at `0x006cf03e` (untouched — if a future build
  moves it, the premise moved), and the frame anchors `mov ebx, [ebp+8]` at `0x006cdd17` and the
  `[ebp+8]` argument use at `0x006ce9a6`, since the cave reads the source object from both.

## Appendix — every address this document depends on

| VA | meaning |
|---|---|
| `0x0068c82d` | `Object::getAttributeModifierBonus(type, float* out, 0, 1)`, `ret 0x10` |
| `0x0068c4a6` | the modifier container accessor it forwards from |
| `0x00804fff` | the accumulator: `*out = 1.0f`, then `*out *=` each active modifier |
| `0x006c9d93` | the `WeaponBonusSet` parser writing `bonus[5]` (`FIRING`) — never read back |
| `0x006ca066` | `WeaponTemplate::getDelayBetweenShots(bonus, rof)` — `delay / (bonus[3] * rof)` |
| `0x006ca0c0` | `WeaponTemplate::getClipReloadTime(bonus)` — `bonus[3]` only |
| `0x006ca123` | `WeaponTemplate::getPreAttackDelay(bonus)` — out-of-line, unreferenced |
| `0x006ca13b` | `WeaponTemplate::getFiringDuration()` — out-of-line, unreferenced, unscaled |
| `0x006ca7ac` | the weapon-bonus array builder (6 floats, all `1.0` before it runs) |
| `0x006cc083` | the only read of `MeleeWeapon` in the binary (a targeting check) |
| `0x006cd142` | `Weapon::getStatus` — the three windows that block the next swing |
| `0x006cd298` | shots-remaining / clip helper |
| `0x006cdd10` | `Weapon::getPreAttackDelay(Object*, …)` — the `PreAttackType` switch |
| `0x006cdd17` | `mov ebx, [ebp+8]` — the source `Object*` the cave reads at site 3 |
| `0x006cdd61` | `cvtsi2ss xmm0, [tmpl+0x138]` — **site 3** |
| `0x006ce95d` | `Weapon::preFireWeapon` |
| `0x006ce9a6` | its `push [ebp+8]` — the source `Object*` the cave reads at site 2 |
| `0x006ce9be` | `weapon+0x1c = now + preAttackDelay` |
| `0x006ce9c1` | `mov eax, [tmpl+0x144]` — **site 2** |
| `0x006ce9d9` | `weapon+0x24 = now + preAttackDelay + FiringDuration` |
| `0x006ce9e5` | the `LeechRangeWeapon` copy of the pre-attack maths — **site 4** |
| `0x006cef6d` | `Weapon::fireWeapon` |
| `0x006cf03e` | `push 0x15` — **the only `RATE_OF_FIRE` request in the binary** |
| `0x006cf042` | `call 0x68c82d` for it |
| `0x006cf055` | `call 0x6ca066` — the multiplier's only consumer |
| `0x006cf2fd` | `weapon+0x18 = now + delayBetweenShots` |
| `0x006cf306` | `mov eax, [tmpl+0x144]` — **site 1** |
| `0x006cf31b` | `weapon+0x20 = now + FiringDuration` |
| `0x007519cb` | an AI attack state calling `getStatus`, firing only on `0` |
| `0x00bd1908` | `1.0f` |
| `0x00d8af48` | attribute-modifier type table; index 21 = `RATE_OF_FIRE`, 12 = `RECHARGE_TIME` |
| `0x00da16cc` | `PreAttackType` name table (`PER_SHOT`, `PER_ATTACK`, `PER_CLIP`, `PER_POSITION`) |
| `0x00da179c` | weapon-bonus field table (`DAMAGE`, `RADIUS`, `RANGE`, `RATE_OF_FIRE`, `PRE_ATTACK`, `FIRING`) |
| `0x00da182c` | weapon-status name table (`READY_TO_FIRE` … `IN_FOLLOW_THRU`) |
| `0x00de412c` | `TheGameLogic` (frame counter at `+0x40`) |
| WeaponTemplate `+0xe8/+0xec` | `ClipReloadTime` min/max |
| WeaponTemplate `+0xf0/+0xf4` | `DelayBetweenShots` min/max |
| WeaponTemplate `+0x125` | `MeleeWeapon` |
| WeaponTemplate `+0x12c` | `PreAttackType` |
| WeaponTemplate `+0x138/+0x13c` | `PreAttackDelay` / `PreAttackRandomAmount` |
| WeaponTemplate `+0x144` | `FiringDuration` |
