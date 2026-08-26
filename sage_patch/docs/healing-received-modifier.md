# `HEALING_RECEIVED` — an `AttributeModifier` that scales the healing a target takes

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000`. Read from the repo's `game.dat` (11,346,944 bytes), which
`sage-patch sagepatch` reports as carrying no known patch, so every byte quoted here is stock.

**Status: built** - see [`patches/healing_received.py`](../patches/healing_received.py) - and
**statically verified, not runtime-verified.** Every claim below carries the instruction it came
from, and every site is byte-asserted in the tests against the real `game.dat`. None of it has
been watched in a running game.

```
sage-patch apply healing-received --in game.dat.backup --out game.dat
sage-patch apply healing-received --keyword HEAL_TAKEN --in ... --out ...
sage-patch apply healing-received-wb --in Worldbuilder.exe.backup --out Worldbuilder.exe
sage-patch verify healing-received game.dat
```

**Verdict up front: the behaviour is one five-byte call swap.** Every heal in the engine funnels
through a single `fstp` in `ActiveBody::attemptHealing`, the healed object is already in a
callee-saved register there, and the modifier system needs no new plumbing — `ModifierList` is a
linear scan over a dword and has no per-type array to widen. The only real cost is the
modifier-type **name table**, which has no slack and is already owned by `production-split`.

- **Cost:** 1 five-byte `call rel32` swap + ~45 bytes of stub + a 116 → 120-byte table copy +
  2 repointed imm32 operands.
- **Risk:** low and opt-in — an object with no modifier holder never reaches the new factor, and a
  multiplier the engine cannot produce leaves `[ebp-4]` exactly as stock. It **is** simulation
  state; §6.
- **The name table is a shared resource**, and §4 was the bulk of the work: it now lives in
  [`patches/utils/modifier_types.py`](../patches/utils/modifier_types.py), read live by both
  appenders so they compose in either order.

```ini
ModifierList MordorPoisonedWounds
  Category = SPELL
  Modifier = HEALING_RECEIVED 25%      ; heals land at a quarter strength
  Duration = 20000
End

ModifierList AthelasDraught
  Modifier = HEALING_RECEIVED 200%     ; and this one doubles them
End
```

## 1. The choke point

`ActiveBody::attemptHealing` is `0x008C2FC1` — body-interface vtable slot `+0x04`, `__thiscall`,
`ret 4`, argument is a `DamageInfo *`. Nine `.rdata` vtables point that slot at this one
implementation (`0x00C71ED4`, `0x00C71FE4`, `0x00C720F4`, `0x00C72434`, `0x00C7267C`, `0x00C7284C`,
`0x00C72A8C`, `0x00C72CC4`, `0x00C72E5C`).

```
008c3005  cmp  dword [ebx+0x10], 7    ; DamageInfo.in.m_damageType
008c3009  je   0x8c3017
008c300b  ...  call [eax]             ; not a heal: hand it to attemptDamage (slot +0x00)
...
008c3051  mov  eax, [esi-8]           ; the healed Object, also live in edi since 0x008c2fdd
008c3054  push 0
008c3056  push eax
008c3057  lea  eax, [ebx+4]           ; &info.in
008c305a  push eax
008c305b  lea  ecx, [esi+0xe8]        ; the body's Armor
008c3061  call 0x5d893c               ; Armor::adjustDamage -> st(0)
008c3066  fstp dword [ebp-4]          ; <- THE AMOUNT, and the hook site
008c3069  fldz
008c306b  fld  dword [ebp-4]
008c306e  fcompi st(1)
008c3070  fstp st(0)
008c3072  jbe  0x8c3195               ; <= 0: nothing happens at all
008c3078  mov  eax, [esi+0x20]
008c307b  fld  dword [ebp-4]
008c307e  push ebx
008c307f  push ecx                    ; a stack slot for the float, not a value
008c3086  mov  eax, [esi]
008c308a  call [eax+0x84]             ; internalChangeHealth(amount, info)
008c3090  movss xmm0, [ebp-4]
008c3095  movss [ebx+0x70], xmm0      ; info.out.m_actualDamageDealt
```

Three properties make `0x008C3066` the right site and not merely a convenient one:

- **`[ebp-4]` is the only amount.** The health change, the `out` field the caller reads back and
  the observer pass below it all come from that one dword.
- **`edi` is the healed object and survives.** `mov edi, [esi-8]` at `0x008C2FDD`, still live at
  `0x008C30C2` (`mov ebx, [edi+0x24c]`) — so the target is in a register at the hook with no
  reload, which is exactly what `getModifierMultiplier` wants for `this`.
- **The `<= 0` test is downstream.** Scaling `[ebp-4]` by zero makes the whole tail of the function
  disappear — no health change, no `out.m_actualDamageDealt`, no healing observers, no full-health
  notify. Immunity to healing falls out of the arithmetic rather than needing an arm of its own.

`Armor::adjustDamage` returns its input unscaled for type 7 (`0x005D8963`), so `[ebp-4]` at the
hook is the raw amount the source asked for — armour never has an opinion about a heal, and the
new modifier is the first thing that does.

**`InactiveBody` is the one body that does not reach this code.** Its own slot `+0x04`
(`0x008C191D`, between `InactiveBody`'s two name-string references at `0x008C18F2` and
`0x008C19CC`) zeroes the `out` fields and returns. A scan of `.text` for `cmp dword [reg+0x10], 7`
finds exactly two sites inside the body compiland — that one and `0x008C3005` — so no third body
overrides healing.

## 2. Every heal in the game reaches it

`Object::attemptHealing(Real amount, Object *source)` is `0x00690532`, `__thiscall`, `ret 8`: it
takes the body from `[this+0x25C]`, builds a `DamageInfo` on the stack (ctor `0x0066365E`), writes
`7` at `+0x10` and `1` at `+0x1C`, drops the amount at `+0x20` and calls slot `+0x04`. Ten call
sites over nine owners:

| caller | what it is | attribution |
|---|---|---|
| `0x008557E2` | **`AutoHealBehavior`** — `HealingAmount` (`+0x13C`) per pulse | reads that field at `0x008557BF`, and sits between the module's name-string refs at `0x008553F6` and `0x00855E21` |
| `0x0086B92C` | **`OpenContain`** — `HealthRegen%PerSec` (`+0xA8`) for contained members | the field pair `+0xA8` Real / `+0x150` Bool belongs only to `HordeContain` and its five relatives |
| `0x0085A384` | **`BridgeBehavior`** — repair, as a fraction of max health | name refs at `0x0085A22A` / `0x0085B425` |
| `0x0085BAC0`, `0x0085BAE5` | **`BridgeTowerBehavior`** — the same, relayed to the bridge | name refs at `0x0085B7D0` / `0x0085BB31` |
| `0x00886DE3` | **`SupplyWarehouseCripplingBehavior`** — `SelfHealAmount` every `SelfHealDelay` | moduledata `+0xC` / `+0x10` and size 20 match only this module |
| `0x008CC438` | **`PlayerHealSpecialPower`** | its ModuleData ctor is `0x008CC459` |
| `0x0090E71D` | **`DamageNugget`** — a `DamageType = HEALING` nugget, per victim | the enclosing `0x0090E683` is the nugget's "apply to one victim", vtable slot `+0x38` |
| `0x0079B2C8` | **`CastleBehavior`** | name refs at `0x0079AA82` |
| `0x00690687` | the neighbouring `Object` helper that heals and then clears the dying flags | same compiland |

More sites build the same `DamageInfo` **inline** and call slot `+0x04` directly rather than going
through `0x00690532`. Scanning `.text` for a `mov dword [mem], 7` with a `call [reg+4]` within the
next `0x140` bytes finds twelve, of which `0x0087B9FE`, `0x008A49FC`, `0x008A5C36` and
`0x008FA1FC` carry the same `[ebp-0x6c] = 7` / `[ebp-0x60] = 1` stack shape as `0x00690532`'s own
`DamageInfo`; they are not individually attributed to modules here, and the rest of that scan's
hits are unchecked. That is the reason to hook the body implementation rather than
`Object::attemptHealing`: the `Object` helper is a convenience, not a funnel, and `0x008C2FC1` is
below all of them.

**What does *not* go through it, correctly:**

- **Construction and repair health.** The `DozerAIUpdate` build state machine adds health with
  `internalChangeHealth` at `0x0088DEB5` (see
  [`construction-speed-modifiers.md`](construction-speed-modifiers.md)), never a `DamageInfo`.
- **Setting health.** `ActiveBody` slots `+0x08`, `+0x0C` and `+0x14` (`0x008C1C51`, `0x008C1C75`,
  `0x008C1D75`) call `internalChangeHealth` at `0x008C1C3D`, `0x008C1D23` and `0x008C1D49` — that
  is respawn, `HEALTH` / `HEALTH_MULT` max-health changes and level-up, which are not heals.
- **`HealOnDetach`**, added by [`detachable-rider-heal.md`](detachable-rider-heal.md), which calls
  `internalChangeHealth` directly and deliberately (§3.2 there). A mod running both patches gets a
  detach grant that this modifier does not scale.

## 3. What the modifier means

`getModifierMultiplier` is `0x0068C82D` — `__thiscall(Int type, Real *out, void *ctx, Int flag)`,
`ret 0x10`, `al` is "something contributed". It guards on the object's modifier holder and
tail-jumps to `0x00804FFF`, which:

```
0080500f  movss [eax], xmm0          ; *out = 1.0
00805039  call 0x804d27              ; per-list gate (expiry, category, the Upgrade condition)
0080505d  call 0x6144bf              ; the store -> ModifierList::getValue, into a local seeded 0.0
0080506d  mulss xmm0, [ebp-8]
00805072  movss [eax], xmm0          ; *out *= this list's value
```

So the value is a **plain multiplier**, and several active lists multiply together. With the
`ModifierList` parser dividing a detached `%` token by 100, `HEALING_RECEIVED 25%` is a quarter of
the healing and `200%` is double — the reading a modder expects, with no `1 +` convention to learn.

**The stub must seed `*out` itself.** `0x0068C82D` returns at its own guard
(`xor al,al; ret 0x10`) without writing through `out` when the object has never been modified, and
every engine caller seeds 1.0 before the call for exactly that reason (`0x005E4010`, `0x00896E9B`,
`0x0090E49D`).

The new type is **complementary to `AUTO_HEAL`, not a duplicate of it.** `AUTO_HEAL` (index 19) is
read once, by `AutoHealBehavior` at `0x008557B4`, through the *additive* `hasModifier`
(`0x0068C818`), on the **healer** (`ecx = [edi+8]`), and is added to `HealingAmount` at
`0x008557C7`. It is an output bonus on one module; this is an input scalar on every target.

Worth knowing while writing the INI: a heal **nugget** is already scaled by the caster's
`DAMAGE_ADD` (`0x0090E476`, index 2) and, when the nugget's `DamageType` is `MAGIC`,
`SPELL_DAMAGE` (`0x0090E4AF`, index 11). A heal weapon therefore ends up with a source factor and
a target factor, in that order.

### The hook

```
        fstp  dword [ebp-4]           ; displaced (d9 5d fc)
        sub   esp, 4
        mov   dword [esp], 0x3f800000 ; *out = 1.0
        push  1                       ; flag, as the engine's own sites pass
        push  0                       ; no ctx
        lea   eax, [esp+8]
        push  eax                     ; &out
        push  <HEALING_RECEIVED>
        mov   ecx, edi                ; the healed object
        call  0x68c82d                ; ret 0x10
        movss xmm0, [esp]
        mulss xmm0, [ebp-4]
        movss [ebp-4], xmm0
        add   esp, 4
        fldz                          ; displaced (d9 ee)
        ret
```

`0x008C3066` holds `d9 5d fc d9 ee` — five bytes exactly, and `xref` finds no branch landing
anywhere inside them. `eax`, `ecx`, `edx` and `xmm0` are all dead across the window (`eax` is
reloaded at `0x008C3078`, the `push ecx` at `0x008C307F` reserves a slot rather than passing a
value, `xmm0` is reloaded at `0x008C3090`); `ebx`, `esi` and `edi` are callee-saved by the stdcall
callee. The x87 stack is empty from the displaced `fstp` until the displaced `fldz`, so the call
sits in an x87-neutral window — **static reasoning only, worth confirming in a live match.**

## 4. The actual work: the name table is already owned

`0x00DA6D28` is a NULL-terminated `const char *[28]`, read from exactly two instructions inside the
name walk at `0x00804CAD` (the imm32 operands at `0x00804CB3` and `0x00804CBA`). The next enum's
list starts four bytes past its terminator, so **there is no slack** and the table has to be rebuilt
in a cave with both references repointed.

`production-split` already does that, and does it **from stock constants**:
`STOCK_TYPE_COUNT = 28`, a fingerprint asserting index 27 spells `INVULNERABLE`, and new indices
computed as `28 + position` in `NEW_TYPES`
([`patches/production_split.py`](../patches/production_split.py)). Applied in either order, the two
patches collide: `production-split` second would rebuild from stock and drop `HEALING_RECEIVED`;
`healing-received` second would fail its own stock fingerprint.

The repo already has the answer for three other tables.
[`patches/utils/name_tables.py`](../patches/utils/name_tables.py) exists precisely so that appends
compose — *"read the live table, wherever the image's references currently point and however many
entries it currently has, rather than assuming the stock base and count"* — and
`model_conditions`, `weapon_set_flags` and `locomotor_sets` are its three owners. The modifier
table is the fourth, and nobody has written it because until now only one patch appended to it.

**So the work was: extract `patches/utils/modifier_types.py` on the `name_tables` pattern, refit
`production-split` onto it, then add `healing-received` as its second consumer.** Two consequences
followed, and they are why this was not a half-hour job:

- **Indices became dynamic.** `production-split` used to bake `28 + position` into the bytes it
  emits (a `push <type>` in each thunk) and into `ini_surface`. Both patches now take the index the
  live table hands them at apply time; `ini_surface` claims **no** index, and `sagepatch` reads it
  off the live table and fuses it with the patch's provenance, which is the mechanism `_fuse`
  already existed for.
- **Neither `verify` may claim the two table operands.** Whichever appender ran last owns them.
  What both check instead is the invariant that survives either order: the walk reaches a table
  that gives this patch's keyword the index this patch's code was built to push.
- **Worldbuilder needed a twin.** `Worldbuilder.exe` carries its own copy of the same table, and
  INI naming a token it does not know ends the editor's load. `healing-received-wb` is
  `production-split-wb`'s shape with one name, sharing the same reader.

## 5. What this does not do

- **It does not filter.** The multiplier is read off the target and applies to every source. A
  "heals from allies only" distinction would need the source object, which is pushed at
  `0x008C3056` but is not carried into the hook's window in a form it reads today.
- **It does not touch damage.** Type 7 only, by construction — `0x008C3005` has already routed
  everything else to `attemptDamage` before the hook is reached.
- **It cannot turn a heal into damage.** A negative product still fails the `jbe` at `0x008C3072`,
  which means "no effect", not "hurt the target".
- **It does not scale max health.** `HEALTH` and `HEALTH_MULT` are separate types on a separate
  path (§2).

## 6. Determinism

An `AttributeModifier` reached through a target's modifier holder changes how much health an object
has on the logic side, so this is **simulation state**: every peer must run the same patched
binary, and a replay recorded on it will not play back on a stock one — the same rule as
`production-split` and `banner-modifier`.

INI naming the new keyword also **fails to load** on an unpatched `game.dat`: the name walk's
index 0 doubles as "not found" and raises `"Attribute '%s' not found"` (`0x00C4EA38`). A mod using
it ships the binary with it rather than degrading quietly.

## 7. Address summary

| what | VA |
|---|---|
| `ActiveBody::attemptHealing` / the hook site | `0x008C2FC1` / `0x008C3066` |
| its damage-type guard / the `<= 0` bail | `0x008C3005` / `0x008C3072` |
| `Armor::adjustDamage` / its type-7 passthrough | `0x005D893C` / `0x005D8963` |
| `internalChangeHealth` (body slot `+0x84`) | `0x008C31A5` |
| `InactiveBody::attemptHealing` | `0x008C191D` |
| `Object::attemptHealing(amount, source)` | `0x00690532` |
| `DamageInfo` ctor | `0x0066365E` |
| `Object::getModifierMultiplier` / its core | `0x0068C82D` / `0x00804FFF` |
| `Object::hasModifier` / its core | `0x0068C818` / `0x00804F39` |
| `ModifierList::getValue` | `0x00805268` |
| `AUTO_HEAL` read (`AutoHealBehavior`) | `0x008557B4` |
| modifier-type name table / its two references | `0x00DA6D28` / `0x00804CB3`, `0x00804CBA` |
| the name walk / its "not found" message | `0x00804CAD` / `0x00C4EA38` |
| `TheAttributeModifierStore` | `0x00DE3C14` |
