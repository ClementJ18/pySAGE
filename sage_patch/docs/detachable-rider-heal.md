# A mount that is healed when its rider comes off — reverse-engineering notes

The RE behind [`patches/detachable_rider_heal.py`](../patches/detachable_rider_heal.py). ROTWK
`game.dat` build `2.01.2614.37001`, ImageBase `0x400000`, recovered statically 2026-08-19 from
`sage_patch/engine/game.dat.backup`, with every site re-checked against the repo's
own `game.dat`.

## The gap

`DetachableRiderBody` is the body module on a mount whose rider can be killed off it — the horse
survives, riderless, when the blow that would have killed the pair lands. What the riderless
object is worth is decided by one field, `HealthPercentageWhenRiderDies`: the module rewrites the
pending damage so what actually lands leaves the object at that fraction of its **maximum** health.

That is the only lever a mod has, and it is the wrong shape for half of what a mod wants to say.
A percentage of maximum scales with the unit and is spent out of the health the object happened to
have; there is no way to write "and give it 200 hit points back". This adds that: one `Real`,
`HealOnDetach`, granted at the moment the rider is detached, on top of whatever the percentage
leaves.

## TL;DR

- `DetachableRiderBody::attemptDamage` (`0x008C5EF3`) is the whole mechanism. On a killing blow it
  rewrites `DamageInfo.in.m_amount` to `health − maxHealth × HealthPercentageWhenRiderDies`, clears
  the instant-kill flag, finds the object's `DetachableRiderUpdate` by name and calls it
  (`0x008B2A46`), then falls into `ActiveBody::attemptDamage` (`0x008C3FA3`) to apply the amount it
  just wrote.
- **The rewritten amount is not raw.** `ActiveBody::attemptDamage` runs it through
  `Armor::adjustDamage` (`0x005D893C`, called at `0x008C4063`) and a per-body scalar, so a grant
  folded into it would be worth a different number of hit points per damage source — and would be
  bounded by the health the object had rather than by its maximum (§3.3).
- The engine's own primitive for "raw hit points" is `ActiveBody::internalChangeHealth`
  (`0x008C31A5`, body-interface vtable `+0x84`, `ret 8`): it adds, clamps to maximum and to zero,
  and runs the damage-state bookkeeping. Both `attemptHealing` and `attemptDamage` end at it.
- **`ModuleData` has no padding to move into.** Its own three fields sit at `+0x194`, `+0x198`,
  `+0x19C` and `sizeof` is `0x1A0` — the last field ends exactly at the end. The class has one
  allocation (`push 0x1A0`, `0x006514EA`) and one constructor call (`0x00651502`), so the struct is
  grown to `0x1A4` and the constructor is routed through a stub that zeroes the new dword.
- The field-parse table has **exactly one reference** in the image and is read through its NULL
  terminator rather than a count, so a fourth row is one 4-byte repoint with no bound to raise.
- Four edits, one `.rdheal` cave holding the keyword, the rebuilt table and two routines.

## 1. Anatomy

### 1.1 Registration and the ModuleData

`addModule` (`0x006570FE`) registers the module at `0x0065B293` from `0x006514A3` (instance
factory, `sizeof` `0x108`) and `0x006514DE` (ModuleData factory), name string `0x00C0A9B4`,
interface mask `0x20`.

| what | address |
|---|---|
| `ModuleData` ctor | `0x008C6035` |
| `ModuleData` `sizeof` | `0x1A0` (`push` at `0x006514EA`, ctor call at `0x00651502`) |
| `buildFieldParse` | `0x008C5D2B` |
| field-parse table | `0x00C72A0C` (`push` at `0x008C5D47`) |
| `attemptDamage` | `0x008C5EF3` (slot 0 of the `+0x10` body vtable `0x00C72A88`) |

`buildFieldParse` contributes three tables in this order, which is also the order the reader
matches keywords in:

```
008c5d2b  mov  esi, [esp+8]
008c5d2f  push esi
008c5d30  call 0x8c3f92          ; ActiveBody::buildFieldParse
008c5d36  push 0x64              ; the UpgradeMux data lives at ModuleData+0x64
008c5d38  call 0x8d26e0          ; ... and contributes its own table
008c5d40  call 0x42b8d7          ; MultiIniFieldParse::add
008c5d45  push 0
008c5d47  push 0xc72a0c          ; the module's own table
008c5d4e  call 0x42b8d7
```

So a keyword duplicating an inherited one would be matched in the base table and the new field
would never be written — which is why the patch refuses the 27 inherited names outright.

The module's own three fields, read out of `0x00C72A0C` (16-byte stride
`{const char *name, parseFn, userData, offset}`, terminated by a NULL name pointer at
`0x00C72A3C`):

| keyword | parse fn | type | ModuleData offset |
|---|---|---|---|
| `HealthPercentageWhenRiderDies` | `0x0042EEFA` | Percent | `+0x194` |
| `StartsActive` | `0x0042E558` | Bool | `+0x198` |
| `RiderlessDeathChance` | `0x0042EEFA` | Percent | `+0x19C` |

### 1.2 Why the struct has to grow

```
008c6035  push esi
008c6036  mov  esi, ecx
008c6038  call 0x8c373f              ; ActiveBodyModuleData ctor      — owns +0x00..+0x63
008c603d  lea  ecx, [esi+0x64]
008c6040  mov  dword [esi], 0xc73028 ; the ModuleData vtable
008c6046  call 0x653173              ; UpgradeMuxData ctor            — owns +0x64..+0x193
008c604b  xorps xmm0, xmm0
008c604e  movss dword [esi+0x19c], xmm0   ; RiderlessDeathChance = 0
008c6056  movss xmm0, dword [0xbd1908]    ; 1.0f
008c605e  mov  byte [esi+0x198], 0        ; StartsActive = No
008c6065  movss dword [esi+0x194], xmm0   ; HealthPercentageWhenRiderDies = 100%
008c606d  mov  eax, esi
008c606f  pop  esi
008c6070  ret
```

Two sub-objects and three fields account for the whole of `0x1A0`: `ActiveBodyModuleData` runs to
`+0x63` (its own last member is constructed at `+0x58`, `0x008C3774`), the `UpgradeMuxData` at
`+0x64` runs to `+0x193`, and the three own fields fill `+0x194`..`+0x19F`. Unlike
`terrain-resource-exp`, there is no alignment slack anywhere a `Real` could sit — so `sizeof` has
to change.

That is cheap here because the size has exactly one use. `0x006514DE` is the only place a
`DetachableRiderBodyModuleData` is ever allocated:

```
006514ea  push 0x1a0
006514ef  call 0x42f6e0        ; operator new(size)
...
00651502  call 0x8c6035        ; the ctor — the image's only call to it
```

and `operator delete` (`0x0042F6A0`, reached from the ModuleData's deleting destructor at
`0x00656D78`) takes **only a pointer**, so nothing else has to learn the new size. `operator new`
does not zero the block, which is why the constructor call is routed through a stub rather than
left alone.

## 2. `DetachableRiderBody::attemptDamage`

`esi` is the body-interface `this` throughout (`ModuleData` at `-0x0C`, owning `Object` at `-0x08`,
current health at `+0x08`, maximum at `+0x10`); `edi` is the `DamageInfo *` from `[ebp+8]`.

```
008c5f07  lea  ecx, [esi+0xf0]
008c5f16  call [eax]                  ; the UpgradeMux: is the module active?     -> [ebp-0xd]
008c5f1c  push 0xc72c58 / 0x5e
008c5f2f  call 0x6d332c               ; GameLogicRandomValueReal(0.0, 1.0)
008c5f34  fld  dword [edi+0x19c]      ; RiderlessDeathChance
008c5f3d  fcompi st(1)                ; roll -> "kill it outright instead"        -> al
008c5f49  mov  ecx, [ebx+0x114]       ; ... or the object already says so
008c5f60  je   0x8c601c               ; not active            -> stock damage
008c5f68  jne  0x8c601c               ; rolled to die         -> stock damage
008c5f6e  push 0x27 / call 0x44ddec   ; a status test         -> stock damage
008c5f7f  test byte [ebx+0x1c8], 0x10 ;                       -> stock damage

008c5f8c  call [eax+0x10]             ; getHealth   (0x005F2D41: fld [ecx+8])     -> [ebp+8]
008c5f9d  call [eax+0x1c]             ; getMaxHealth(0x006AA274: fld [ecx+0x10])
008c5fa0  fmul dword [ebx+0x194]      ; x HealthPercentageWhenRiderDies           -> [ebp-0x14]
008c5fa6  cmp  byte [edi+0x24], 0     ; DamageInfo.in.m_kill
008c5faa  movss xmm1, [edi+0x20]      ; DamageInfo.in.m_amount
008c5fbc  subss xmm2, xmm1            ; health - amount
008c5fc6  jb   0x8c601c               ; it survives anyway    -> stock damage

008c5fcf  subss xmm0, dword [ebp-0x14]
008c5fd4  movss dword [edi+0x20], xmm0 ; amount := health - maxHealth x percentage
008c5fd9  mov  byte [edi+0x24], 0      ; and it is no longer a kill
008c5fe6  push 0xc0b0a8 / call 0x5487ec ; NameKey("DetachableRiderUpdate"), cached at 0xde9bc8
008c600c  call 0x68bda5                ; Object::findModule
008c6013  je   0x8c601c                ; no such module -> nothing detaches
008c6015  mov  ecx, eax
008c6017  call 0x8b2a46                ; DetachableRiderUpdate: take the rider off

008c601c  push edi
008c601d  mov  ecx, esi
008c601f  call 0x8c3fa3                ; ActiveBody::attemptDamage — applies the amount
008c6024  ...                          ; epilogue
```

Three things this establishes, all of which the patch depends on:

1. **`0x008C6015`..`0x008C601B` is the detach and nothing else.** The seven bytes are reached only
   by falling through the `jne` at `0x008C6013`; the six branch targets in the function are
   `0x008C5F47`, `0x008C5F49`, `0x008C5F59`, `0x008C5FC8`, `0x008C6003` and `0x008C601C`, and no
   data reference in the image points into the window either.
2. **`esi` and `edi` are still live there.** `edi` is pushed as the `DamageInfo *` two instructions
   later, and `esi` is loaded into `ecx` beside it — the stock code says so itself.
3. **The damage is applied *after* the detach**, at `0x008C601F`. A grant issued before it would be
   spent against the clamp at maximum health (§3.3).

## 3. Where the hit points come from

### 3.1 `ActiveBody::internalChangeHealth`

Body-interface vtable slot `+0x84` → `0x008C31A5`, `__thiscall`, `ret 8`:

```
008c31a9  movss xmm1, [ebp+8]        ; delta
008c31b1  mov  eax, [esi+8]          ; the old health, kept as "previous" at +0x0c
008c31b4  movss xmm2, [esi+0x10]     ; maximum
008c31bc  addss xmm0, [esi+8]
008c31c1  movss [esi+8], xmm0
008c31c6  comiss xmm0, xmm2
008c31d0  jbe  0x8c31e5
008c31d2  movss [esi+8], xmm2        ; clamp to maximum
...
008c3264  comiss xmm0, [esi+8]
008c326a  movss [esi+8], xmm0        ; clamp to zero
008c327d  call [eax+0x54]            ; damage-state / model-condition update
008c32c2  call 0x68d950              ; and the object is told its health changed
```

`[ebp+0xc]`, the `DamageInfo *`, is **never read** by this implementation — but both engine call
sites pass theirs (`0x008C308A` in `attemptHealing`, `0x008C4257` in `attemptDamage`, both
`push <DamageInfo>; push ecx; movss [esp], xmm0`), so the patch passes the live one too rather
than inventing a NULL the engine has never handed it.

### 3.2 Why not the healing path

`ActiveBody::attemptHealing` (`0x008C2FC1`) is a `DamageInfo`-taking virtual: it wants a whole
`DamageInfo` built on the stack with `in.m_damageType == 7`, runs the armor lookup on it and fires
the object's healing observers. Building one to grant a fixed number of hit points is a great deal
of structure for a number that then goes straight into `internalChangeHealth` anyway.

### 3.3 Why not fold the grant into the damage

The cheap edit — subtract the grant from the amount written at `0x008C5FD4` — is wrong twice.

**Armor.** `ActiveBody::attemptDamage` does not apply `in.m_amount`; it applies what comes back
from the armor:

```
008c4056  push 0 / push edi / lea eax,[ebx+4]
008c405d  lea  ecx, [esi+0xe8]        ; the body's current Armor
008c4063  call 0x5d893c               ; Armor::adjustDamage(in, source, ...)
008c4068  fstp dword [ebp-0x18]
008c407c  movss xmm0, [esi+4]         ; ... and a per-body damage scalar
008c4081  mulss xmm0, [ebp-0x18]
...
008c4247  subss xmm0, [ebp-0x18]
008c4257  call [eax+0x84]             ; internalChangeHealth(-applied, info)
```

So an amount written into the `DamageInfo` is scaled by whatever the mount's armor does to that
damage type — a "flat 200" would be worth 200 against one attacker and 340 against another.
(`adjustDamage` returns its input unscaled for type 7, healing, at `0x005D8963` — the engine's own
statement that a heal is the raw-amount path and damage is not.)

**The clamp.** The amount is computed from the health the object had, so a grant folded into it can
only ever give back health the object already lost. Granting *after* the damage lands is what makes
`HealthPercentageWhenRiderDies` + `HealOnDetach` add up as written, with one clamp at maximum
health at the end.

## 4. The patch

Four edits and one cave (keyword string, rebuilt table, two routines).

| site | stock | patched |
|---|---|---|
| `0x006514EA` | `push 0x1A0` | `push 0x1A4` |
| `0x00651502` | `call 0x008C6035` | `call <cave: ctor>` |
| `0x008C5D47` | `push 0x00C72A0C` | `push <cave: table>` |
| `0x008C6015` | `mov ecx, eax` / `call 0x008B2A46` | `jmp <cave: detach>` + 2 × `nop` |

```
ctor:    call 0x008c6035                 ; the stock ctor, which returns this in eax
         and  dword [eax+0x1a0], 0       ; HealOnDetach = 0 — operator new does not zero it
         ret

detach:  mov  ecx, eax                   ; displaced
         call 0x008b2a46                 ; displaced — the rider comes off
         push edi
         mov  ecx, esi
         call 0x008c3fa3                 ; the stock tail: ActiveBody::attemptDamage
         mov  eax, [esi-0x0c]            ; the ModuleData
         movss xmm0, dword [eax+0x1a0]   ; HealOnDetach
         xorps xmm1, xmm1
         comiss xmm0, xmm1
         jbe  done                       ; nothing to grant (and a NaN counts as nothing)
         comiss xmm1, dword [esi+0x08]   ; zero vs the health the damage left
         jae  done                       ; it died anyway — top up, never resurrect
         push edi                        ; the DamageInfo, as both engine call sites pass theirs
         push ecx
         movss dword [esp], xmm0
         mov  eax, [esi]
         mov  ecx, esi
         call dword [eax+0x84]           ; ActiveBody::internalChangeHealth(heal, info)
done:    jmp  0x008c6024
```

The rebuilt table is the three stock rows **verbatim** — their name pointers are absolute and stay
pointing at the stock strings in `.rdata` — plus one row
`{<cave keyword>, 0x0042ED00 (INI::parseReal), 0, 0x1A0}` and a NULL terminator. The stock table is
abandoned where it is rather than edited.

Two properties worth stating out loud:

- **The grant follows the detach, not the survival.** The `je` at `0x008C6013` — the object has a
  `DetachableRiderBody` but no `DetachableRiderUpdate` to find — keeps the stock bytes and grants
  nothing.
- **It cannot resurrect.** `HealthPercentageWhenRiderDies = 0%`, or an armor multiplier that takes
  the rewritten damage past the intended floor, leaves the object at zero health and already dying;
  the second guard leaves it there.

## 5. Determinism, INI and composition

Health is logic-side `Object` state and the engine CRCs it, so **every peer must run the same
patched binary**. The keyword is fatal on a stock one — SAGE treats an unknown field in a known
block as a parse error, not a warning — so a mod that writes `HealOnDetach` ships the patched
`game.dat` or does not load. Savegames are unaffected: `ModuleData` is load-time configuration read
from `.ini` and never `Xfer`'d, and the new dword is past everything a save has ever carried.

Composition is order-independent: the cave is allocated past every existing section and `verify`
finds it by name. No other bundled patch touches `0x006514EA`, `0x00651502`, `0x008C5D47` or
`0x008C6015`, and this patch reads nothing another patch rewrites. `terrain-resource-exp` is the
nearest neighbour — the same three-step recipe (default, table, behaviour) applied to a different
module — and the two share no byte.
