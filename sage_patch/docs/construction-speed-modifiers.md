# Splitting `PRODUCTION` — five modifiers for money, units, upgrades, heroes and construction

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR), recovered
**statically** on 2026-08-13 from the stock `game.dat` in this repo's fixtures (11,346,944 bytes)
with `pefile` + `capstone`, then partially confirmed in a live match on the same date — see §8 for
which claims that settled and which are still static-only.

- **Goal:** four new `ModifierList` keywords, each addressing one thing `PRODUCTION` currently
  addresses all at once (or, for construction, does not address at all):
  - **`PRODUCTION_MONEY`** — resource output only.
  - **`PRODUCTION_UNIT`** — objects coming out of a production queue only.
  - **`PRODUCTION_UPGRADE`** — upgrades researching in a production queue only.
  - **`PRODUCTION_CONSTRUCTION`** — structure construction only.
- **A fifth keyword, `PRODUCTION_HERO`, was built and then withdrawn.** It was correct about
  *which* queue entries are heroes and wrong about what moves them; §2.2 is the post-mortem. Do not
  re-add it at the queue site.
- **Status: implemented as `production-split`**
  ([`../patches/production_split.py`](../patches/production_split.py)), applying and verifying
  against the real `game.dat` and composing in either order with `commandset-limit` and
  `foundation-rebind`. The queue hook is **runtime-verified** (2026-08-13, live match: a keyword of
  5.0 measured as exactly 5.000 progress per frame at `entry+0x1c`); the money and construction
  hooks are still static-only, and §8 lists what remains. The AI sites of §5 are built but opt-in,
  behind `--ai-sites`.

## TL;DR

- **The engine has already done most of the separating for us.** `PRODUCTION` (type index 13) is
  read at exactly eight sites, and they fall cleanly into the buckets asked for — except
  construction, which reads nothing at all. Three of the four keywords are therefore not new
  plumbing: they are **one extra factor at a call site that already asks for type 13**.
- **Money is four sites**, all the same shape: `AutoDepositUpdate` (`0x0089DC44`),
  `TerrainResourceBehavior` (`0x0088559E`), the `SlaughterHordeContain` cash-back path
  (`0x00883C4D`) and `SupplyCenterDockUpdate` (`0x008A4622`).
- **Units and upgrades are one site between the two of them.**
  `ProductionUpdate::update` accrues `+= multiplier` per frame at `0x008A1ED6` for *every* queue
  entry, and the entry's kind is a dword at `entry+0x04`: **1 = unit, 2 = upgrade, 3 = hero
  (recruit or revive)**. One hook that reads that dword picks which keyword applies.
  No second site to find.
- **Heroes accrue there too, and it means nothing.** Kind 3 completes off the player's hero ledger,
  which is wall-clock (`(now - startFrame) / totalFrames`), not off the accrual — so scaling the
  accrual moves only the progress bar. This is why there is no `PRODUCTION_HERO`; §2.2.
- **Construction has no modifier query at all.** It advances in one place — the `DozerAIUpdate`
  build state machine, `0x0088DE43`–`0x0088DE99` — which divides `100` and `maxHealth` by the frame
  count from `ThingTemplate::calcTimeToBuild` (`0x0073C39E`). `PRODUCTION_CONSTRUCTION` wraps that
  call and divides the frame count.
- **Every hook is a 5-byte `call rel32` swap.** Six required, three optional (the AI's estimation
  sites), all into one shared cave.
- **`PRODUCTION` keeps every meaning it has today.** The new keywords multiply *on top* at their
  own sites, so no existing mod's INI changes behaviour — and a mod that wants clean separation
  simply stops writing `PRODUCTION`. This is what makes the patch safe to ship.
- **Runtime is structurally free.** There is no per-type array, no bitmask and no switch anywhere
  in the modifier system: `ModifierList::getValue` (`0x00805268`) is a linear scan comparing a
  dword. The only real cost is the name table at `0x00DA6D28`, which has **zero slack** and must be
  relocated.
- **This is simulation state.** Every peer needs the patched binary; replays will not play back on
  a stock one. And INI using a new keyword **hard-fails to load** on an unpatched `game.dat`
  (`"Attribute '%s' not found"`).

## 1. What a modifier is, end to end

### 1.1 The block

`ModifierList` blocks are parsed by `0x006149AB` into `0xD4`-byte objects held by
**`TheAttributeModifierStore`** (`0x00DE3C14`), which hands them out **by index**, not by pointer.
The field table is at `0x00C4EAF0`:

| field | parse fn | offset |
|---|---|---|
| `Modifier` | `0x00806264` | `0x00` (vector) |
| `Category` | `0x00804DEA` | `0x0C` |
| `Duration` | `0x0073A429` | `0x18` |
| `ModelCondition` / `ClearModelCondition` | `0x004B8C21` | `0x1C` / `0x68` |
| `FX`…`EndFX3` | `0x0073A302` | `0xB4`–`0xC8` |
| `Upgrade` | `0x008050D3` | `0x00` |
| `MultiLevelFX` / `ReplaceInCategoryIfLongest` / `IgnoreIfAnticategoryActive` | `0x0042E558` | `0xD0` / `0xD2` / `0xD3` |

Each `Modifier =` line becomes a **`0x14`-byte entry** appended by `0x008061D0` (re-assigning in
place if the type is already present):

```
+0x00  Int    type index
+0x04  Real   value          ; a detached '%' token divides by 100 at parse time
+0x08  vector<UpgradeTemplate*>   ; the optional per-entry Upgrade gate
```

### 1.2 The type names

`0x00806264` resolves the first token through the name→index walk at `0x00804CAD`, over a
**NULL-terminated `const char *[]` at `0x00DA6D28`**:

```
00804cb1  39 3d 28 6d da 00   cmp  [0xda6d28], edi          ; edi = 0
00804cb9  be 28 6d da 00      mov  esi, 0xda6d28            ; the two references
00804cc6  e8 ..               call strcmp
00804cd1  83 c6 04            add  esi, 4                   ; next name, edi++
```

Index 0 is the `ATTRIBUTE_NONE` sentinel and doubles as "not found" — an unrecognised name raises
`"Attribute '%s' not found"` (`0x00C4EA38`) and aborts the load. **The engine's numbering is:**

| # | name | # | name | # | name |
|---|---|---|---|---|---|
| 0 | `ATTRIBUTE_NONE` | 10 | `RESIST_KNOCKBACK` | 19 | `AUTO_HEAL` |
| 1 | `ARMOR` | 11 | `SPELL_DAMAGE` | 20 | `SHROUD_CLEARING` |
| 2 | `DAMAGE_ADD` | 12 | `RECHARGE_TIME` | 21 | `RATE_OF_FIRE` |
| 3 | `DAMAGE_MULT` | **13** | **`PRODUCTION`** | 22 | `DAMAGE_STRUCTURE_BOUNTY_ADD` |
| 4 | `RESIST_FEAR` | 14 | `HEALTH` | 23 | `CRUSHER_LEVEL` |
| 5 | `RESIST_TERROR` | 15 | `HEALTH_MULT` | 24 | `COMMAND_POINT_BONUS` |
| 6 | `EXPERIENCE` | 16 | `VISION` | 25 | `CRUSHABLE_LEVEL` |
| 7 | `RANGE` | 17 | `BOUNTY_PERCENTAGE` | 26 | `CRUSHED_DECELERATE` |
| 8 | `SPEED` | 18 | `MINIMUM_CRUSH_VELOCITY` | 27 | `INVULNERABLE` |
| 9 | `CRUSH_DECELERATE` | | | | |

Confirmed against use: the crush maths at `0x006933B6`/`0x00693490`/`0x006933E4` asks for 9, 18 and
26 — `CRUSH_DECELERATE`, `MINIMUM_CRUSH_VELOCITY`, `CRUSHED_DECELERATE`.

`.data` holds **~135 copies** of this array (a header-defined table, one per translation unit);
only `0x00DA6D28` is reachable from code, and only from the two instructions above.

> `sage_ini/model/enums.py:ModifierType` numbers these differently (`ARMOR = 0`, `PRODUCTION = 16`,
> with a synthetic `SEPARATOR` splitting additive from multiplicative). That is a model-side
> convention and nothing interoperates with the binary through it — but if anything ever needs the
> engine's numbering, it is the table above, not that enum.

### 1.3 Reading a modifier at runtime

An object's active lists live on a holder reached by `Object::getModifierHolder` (`0x0068C4A6`,
null until the object has been modified once). Two public per-type queries sit on `Object`:

| entry | forwards to | shape |
|---|---|---|
| `0x0068C818` — `hasModifier(type, &out, ctx)` | `0x00804F39` | seeds `*out = 0.0`, **sums** |
| `0x0068C82D` — `getModifierMultiplier(type, &out, ctx, flag)` | `0x00804FFF` | seeds `*out = 1.0`, **multiplies** |

Both walk `holder+0x20 .. holder+0x24` (`0x10`-byte entries: list index at `+0`, expiry frame at
`+8`, tested against `TheGameLogic+0x40`), then go through the store (`0x006144BF`,
index-bounds-checked) into `ModifierList::getValue` (`0x00805268`):

```
00805274  8b 06        mov  eax, [esi]        ; entry->type
00805276  3b 45 08     cmp  eax, [ebp+8]      ; wanted type
00805279  74 0f        je   .hit
0080527b  83 c6 14     add  esi, 0x14         ; next entry
```

**A linear scan over a dword.** There is no array indexed by type, no bit width to overflow, and no
switch to extend. Additive-versus-multiplicative is decided **by the caller**, not by the type —
every `PRODUCTION` site uses the multiplicative entry, and so will all four new keywords.

## 2. Every place `PRODUCTION` (13) is read, and which keyword it becomes

All eight sites go through `0x0068C82D`, so all eight are the same 5-byte `call rel32`:

| site | what it scales | becomes |
|---|---|---|
| `0x0089DC44` | `AutoDepositUpdate` — per-tick income | `PRODUCTION_MONEY` |
| `0x0088559E` | `TerrainResourceBehavior::update` (`0x008854D3`, see [`terrain-resource-exp.md`](terrain-resource-exp.md)) — per-tick income | `PRODUCTION_MONEY` |
| `0x00883C4D` | `SlaughterHordeContain` cash-back on entry (`CashBackPercent`, ModuleData `+0xD4`) | `PRODUCTION_MONEY` |
| `0x008A4622` | `SupplyCenterDockUpdate` — deposited cargo value (`ValueMultiplier`, ModuleData `+0x10`) | `PRODUCTION_MONEY` |
| **`0x008A1ED6`** | **`ProductionUpdate::update` — queue progress per frame** | **`PRODUCTION_UNIT` / `PRODUCTION_UPGRADE`** (kind 3 is handed back unhooked) |
| `0x009BB858`, `0x009BBC4F` | AI valuation of a building | `PRODUCTION_MONEY` (optional) |
| `0x009E7594` | AI picking the object with the highest multiplier | `PRODUCTION_MONEY` (optional) |

Module attribution for `0x00883C4D` and `0x008A4622` is by compiland neighbourhood plus a field
match (`+0xD4` is written by `SlaughterHordeContain`'s ModuleData ctor at `0x008842E2`;
`ValueMultiplier` at `+0x10` is `SupplyCenterDockUpdate`'s only Real). Both are consistent but
not proven; the *shape* of the call is identical either way, which is all the patch needs.

### 2.1 The queue site, and why units and upgrades split cleanly there

```
008a1ebc  movss xmm0, [0xbd1908]        ; 1.0
008a1ec4  mov   ecx, [esi-8]            ; the producing Object
008a1ecf  6a 0d push 0x0d               ; PRODUCTION
008a1ed6  e8 .. call 0x68c82d           ; -> local = product of active PRODUCTION modifiers
008a1ee0  addss xmm0, [ebp-0x68]
008a1ee9  movss [ebx+0x1c], xmm0        ; entry->progressFrames += multiplier
008a1eee  e8 .. call 0x8a04da           ; eax = total build time in frames
008a1f08  divss xmm0, xmm2              ; percent = progress / total
008a1f0f  mulss xmm0, [0xbd88d8]        ;         * 100
```

`ebx` is the queue entry and is callee-saved across the call. Its kind lives at `entry+0x04`, and
the engine itself branches on it twice — once for the total build time (`0x008A04F5`) and once at
completion (`0x008A1F74`):

| `entry+0x04` | meaning | total time from | completion |
|---|---|---|---|
| 1 | unit | `ThingTemplate::calcTimeToBuild` (`0x0073C39E`) | create object |
| 2 | upgrade | the `UpgradeTemplate`'s own time (`0x0066F1A8`) | grant upgrade (`0x008A2015`) |
| 3 | hero — recruit **or** revive | the player's hero ledger (`Player+0x758`, `0x00780B72`) | create object, hero flag |

All three reach the accrual at `0x008A1EBC` — kind 2 has a pre-check above it (`0x008A1E87`) that
can bail out early, but otherwise falls straight through. **So one hook, reading one dword, routes
the entry to the right keyword.** Note the upgrade's *total* time comes from the `UpgradeTemplate`,
not a `ThingTemplate`, which is why `PRODUCTION_UPGRADE` needs nothing beyond the accrual.

Kind 3 reaches the accrual as well — and that is the trap §2.2 documents. Reaching the accrual and
being *completed* by it are different things.

### 2.2 Why there is no `PRODUCTION_HERO` — a post-mortem

**This section describes a keyword that was built, shipped into a live test, and removed.** It is
kept because the mistake is entirely reasonable from static reading and would be made again.

Kind 3 is chosen in `queueCreateUnit` (`0x008A11D2`, interface vtable slot `+0x20`) by the second
argument alone:

```
008a11d8  83 7d 0c ff     cmp   dword [ebp+0xc], -1   ; a hero id, or -1 for a plain template
008a11e2  0f 95 45 ff     setne byte [ebp-1]          ; -> kind 3 instead of kind 1
008a11ed  74 04           je    .unit
008a11ef  83 65 08 00     and   dword [ebp+8], 0      ; and the ThingTemplate is discarded
```

All of that is true, and a keyword keyed on it is correctly *scoped*: verified live, both a
first-time recruit and a revive of a dead hero are kind-3 entries, and both come from the ledger at
`Player+0x758`. The error was assuming that scaling the accrual would therefore move them.

**It does not, because kind 3 does not complete off the accrual.** Immediately after the
total-time call, `ProductionUpdate::update` branches on the kind and sends heroes somewhere else
entirely:

```
008a1ef3  83 7b 04 03     cmp   dword [ebx+4], 3      ; hero?
008a1f21  75 48           jne   0x8a1f6b              ; no  -> the percentage test
008a1f26  05 58 07 00 00  add   eax, 0x758            ; yes -> the player's hero ledger
008a1f3d  e8 ..           call  0x78131e              ; find this hero's ledger entry
008a1f47  e8 ..           call  0x780c9f              ; ask it how ready he is
008a1f4c  d9 e8           fld1
008a1f50  df f1           fcompi st(1)
008a1f56  0f 82 ..        jb    0x8a2f0e              ; < 1.0 -> not done, leave
008a1f6b  0f 2f c1        comiss xmm0, xmm1           ; the percentage test - kinds 1 and 2 ONLY
```

and `0x00780C9F` is pure wall clock:

```
00780cc9  e8 ..           call  0x780687              ; eax = total build time, in frames
00780cdb  8b 40 40        mov   eax, [eax+0x40]       ; TheGameLogic's current frame
00780ce3  db 45 0c        fild  dword [ebp+0xc]       ; (float)currentFrame
00780cee  da a6 a8 00 ..  fisub dword [esi+0xa8]      ;   - startFrame
00780cf4  da 75 08        fidiv dword [ebp+8]         ;   / totalFrames
```

`entry+0x1c` — the thing the accrual hook scales — is never read on this path. So the keyword did
exactly what it was written to do and had no effect anyone could see.

**Measured, 2026-08-13, live match, `GondorBarracks#5856` reviving `GondorBoromir_mod`:** with the
keyword at 5.0, `entry+0x1c` advanced at exactly `5.000` per frame (stock is `1.000`), the derived
percentage at `entry+0x14` ran to **480%**, and the hero still arrived after ~150 frames — his
unscaled `totalFrames`. A progress bar sprinting four times around the dial while nothing else
changed.

**Where a working hero keyword would have to go.** Both hero denominators — the ledger's
(`0x00780C9F` → `0x00780CCA`) and the progress bar's (`0x00780B72` → `0x00780BDF`/`0x00780C05`) —
call `0x00780687`, which gets its frame count from `calcTimeToBuild` at **`0x007806DF`** and then
multiplies in `ProductionModifier`'s hero-flavoured `TimeMultiplier` (vtable slot `+0x74`,
selected by the ledger entry's revive-vs-purchase bool at `+0xB0`). One hook there, dividing `eax`
the way §4.5's construction thunk does, would move the hero *and* keep the bar in step, reading its
multiplier off the producing building at `[ebp+0xc]`.

Two conditions on ever doing it:

- **The queue-site kind-3 branch must stay gone.** With `0x007806DF` hooked the bar's denominator
  already shrinks by N; scaling the numerator as well makes the bar read N² and hit 100% long
  before the hero exists.
- `0x007806DF` is one of five `calcTimeToBuild` call sites, and `0x008A052C` is the unit path's
  total time. Hooking the *function* rather than the site squares the factor for units — the same
  trap §4.5 warns about.

One further consequence, unchanged and still true: **a hero sold as an ordinary buildable unit**
from an ordinary `UNIT_BUILD` button is a **kind 1** entry, answers to `PRODUCTION_UNIT`, and — 
because kind 1 *does* complete off the accrual — actually speeds up. Heroes are therefore already
scalable today, provided the mod sells them as units rather than through the ledger.

## 3. How a structure's construction speed is decided

### 3.1 The frame count

`ThingTemplate::calcTimeToBuild(Player*, Object *producer, Int overrideSeconds)` at **`0x0073C39E`**
is the single source of build time:

1. `overrideSeconds == -1` → take `ThingTemplate+0x4EC` (the INI `BuildTime`, Real seconds);
2. multiply by the player's handicap (`Player+0x3C`, `0x007B19BF`);
3. multiply by a template-side factor (`0x006AF484` on `+0x64`, used as `1 + x`);
4. **if `producer != NULL`**, multiply by that producer's `ProductionUpdate` time multiplier —
   interface vtable slot `+0x6C` (`0x008A09B7`), which walks the module's `ProductionModifier`
   sub-blocks and applies each `TimeMultiplier` whose `ModifierFilter` matches the template and
   whose `RequiredUpgrade` the player holds;
5. divide by the `TheWritableGlobalData` build-speed factors (`+0xA74`/`+0xA78`/`+0xA7C`) and
   truncate to an Int frame count.

`ProductionModifier` is `0x14` bytes: `RequiredUpgrade+0x00`, `ModifierFilter+0x04`,
`CostMultiplier+0x08`, `TimeMultiplier+0x0C`, `HeroPurchase+0x10`, `HeroRevive+0x11`; the list
hangs off `ProductionUpdate` ModuleData `+0x3C`. Slots `+0x70`/`+0x74` are the hero-flavoured
cost/time variants used by the player's per-hero build-entry cache (`Player+0x758`, `0x00780687`).

### 3.2 The one place construction actually advances

Inside the `DozerAIUpdate` build state machine (function `0x0088D7D2`), per frame:

```
0088de43  movss xmm0, [edi+0x288]       ; structure's construction percent
0088de4b  ucomiss xmm0, [0xbd19dc]      ; -1.0 == "not building"
0088de5c  mov   ecx, [ebp-0x14]         ; the builder Object
0088de5f  mov   esi, [edi+4]            ; the structure's ThingTemplate
0088de62  6a ff push -1                 ; overrideSeconds
0088de64  51    push ecx                ; producer = the builder
0088de65  e8 .. call 0x68b678           ; -> controlling player
0088de6a  50    push eax
0088de6b  8b ce mov  ecx, esi
0088de6d  e8 2c e5 ea ff  call 0x73c39e ; eax = frames          <-- the hook
0088de72  movss xmm1, [0xbd88d8]        ; 100.0
0088de89  divss xmm1, xmm0              ; 100 / frames
0088de99  movss [edi+0x288], xmm0       ; percent += 100/frames
0088dea8  call  [esi+0x1c]              ; body->getMaxHealth()
0088deab  fdiv  [ebp-0x1c]              ; / frames
0088deb5  call  [esi+0x84]              ;   -> internalAddHealth
0088ded3  comiss xmm0, [0xbd88d8]       ; done at 100%
```

Two facts follow. **One**, the percent and the health ramp both come from that single `eax`, so
scaling it scales the whole thing coherently — no second site to keep in step. **Two**, because the
percent is *accumulated on the object* rather than derived from a start frame, a rate that changes
mid-build (an aura arriving, an upgrade completing) is handled naturally.

`Object+0x288` is the construction percent; `GettingBuiltBehavior` re-derives it from the body's
health ratio (`0x00856809`, `0x00858081`) and the drawable copies it for the build-up animation
(`0x004B51FD`). **No modifier query appears anywhere on this path.**

## 4. The design

### 4.1 `PRODUCTION` is left alone

The four keywords take indices **28–31** and each multiplies *in addition to* whatever `PRODUCTION`
already contributes at that site. Effective factors become:

```
income        = PRODUCTION * PRODUCTION_MONEY             ; 28
queue kind 1  = PRODUCTION * PRODUCTION_UNIT              ; 29
queue kind 2  = PRODUCTION * PRODUCTION_UPGRADE           ; 30
construction  =              PRODUCTION_CONSTRUCTION      ; 31 - PRODUCTION never reached here
queue kind 3  = PRODUCTION                                ; unhooked - see §2.2
```

Absent modifiers are `1.0`, so **no existing INI changes behaviour**. A mod wanting clean
separation stops writing `PRODUCTION` and writes only the specific keywords. The alternative —
repointing the existing `push 0x0D` immediates at each site — is one byte cheaper per site and
would silently break every mod already shipping `PRODUCTION`; do not do it.

### 4.2 The name table (all four keywords, one edit)

`0x00DA6D28` is 28 pointers plus a terminator, and the next enum's list begins at `0x00DA6D9C` —
**no slack to append into**. Allocate a section with `sage_patch.utils.allocate_section` (never a
fixed RVA — see `patcher.py`'s rules, and [`commandset-button-limit.md`](commandset-button-limit.md)
for the same move done on the `CommandSet` field table), write the 28 stock pointers, the four new
name strings, and the terminator, then repoint the two operands at **`0x00804CB1`** and
**`0x00804CB9`**. Nothing else needs to grow (§1.3).

### 4.3 Widening a query — the shape used by money, units and upgrades

Five sites already ask for type 13 with the same four arguments. Replace each
`call 0x0068C82D` with `call <cave_n>`, where the cave forwards, then folds in the second type:

```
cave_n:
    mov   ebx_save, ecx           ; ecx (the Object) is NOT callee-saved - stash it
    mov   out_ptr, [esp+8]        ; arg2, the Real* the caller wants written
    call  0x0068C82D              ; stock call: consumes the 4 args, writes *out = product(13)
    movss saved, [out_ptr]        ; keep it: the next call overwrites *out
    push  flag / ctx / out_ptr / <new type>
    mov   ecx, ebx_save
    call  0x0068C82D              ; *out = product(new type)
    mulss [out_ptr], saved        ; *out = product(13) * product(new type)
    ret   0x10
```

Two traps, both load-bearing:

- **`0x00804FFF` seeds `*out = 1.0` on entry** (`0x00805007`). Calling it twice with the same
  pointer discards the first result unless the cave saves it.
- **`ecx` is the `this` pointer and is not preserved** across the first call, so the cave must
  stash it. `ebx`/`esi`/`edi` are preserved, which is why the queue site's `ebx` (the entry) and
  the construction site's `edi` (the structure) are still valid after the call.

The return value in `al` ("any modifier found") is consumed by three of the sites; the cave should
return the **logical OR** of the two calls, which for the multiplicative path means "either
contributed".

### 4.4 Unit versus upgrade — one hook, one `cmp` and one early exit

At `0x008A1ED6` the cave additionally reads `[ebx+4]` (`ebx` is the queue entry and survives the
call). A hero leaves before the thunk builds a frame; the rest choose a second type:

```
    cmp   dword [ebx+4], 3
    jne   .widen
    jmp   0x0068c82d              ; kind 3 -> stock, untouched (§2.2)
.widen:
    <prologue>
    mov   eax, [ebx+4]
    cmp   eax, 2
    je    .upgrade                ; kind 2 -> PRODUCTION_UPGRADE (30)
    ...                           ; kind 1 -> PRODUCTION_UNIT    (29)
```

The hero exit is a `jmp`, not a `call`: at that instruction the four arguments and `ecx` are still
exactly as the site pushed them, so tail-calling leaves the stock callee returning straight to the
site and the hook is invisible. It must also come **before** the prologue — once the thunk has
pushed anything, the stock callee's `ret 0x10` no longer balances the site.

### 4.5 Construction — a divide, not a multiply

`PRODUCTION_CONSTRUCTION` has no existing query to widen, so it wraps the frame count instead.
Replace `call 0x0073C39E` at **`0x0088DE6D`**:

```
cave_construction:
    call  0x0073C39E              ; stock call, unchanged args, eax = frames
    ; multiplier = getModifierMultiplier(PRODUCTION_CONSTRUCTION) on edi (the structure)
    ; eax = (int)(eax / multiplier), clamped to >= 1, multiplier <= 0 ignored
    ret
```

- **Clamp.** The caller divides by `eax` at `0x0088DE89`; the cave must floor at 1 frame and ignore
  a non-positive multiplier, or a degenerate modifier divides by zero.
- **Whose modifiers?** `edi` is the structure being built and `[ebp-0x14]` is the builder — both are
  addressable. Three defensible readings (structure, builder, or the product of both, each factor
  being `1.0` when absent). Recommend a patch parameter defaulting to **both**.
- **Do not hook `calcTimeToBuild` itself** to cover everything at once: it is also the unit path's
  total-time source (`0x008A052C`), which already accrues at the modifier rate, so units would get
  the factor **squared**.

## 5. Hook inventory

Every site is a 5-byte `call rel32`; expected original bytes are listed so `verify` can assert them.

| # | site | original bytes | target | second type | required |
|---|---|---|---|---|---|
| 1 | `0x0089DC44` `AutoDepositUpdate` | `e8 e4 eb de ff` | `0x0068C82D` | 28 `PRODUCTION_MONEY` | yes |
| 2 | `0x0088559E` `TerrainResourceBehavior` | `e8 8a 72 e0 ff` | `0x0068C82D` | 28 | yes |
| 3 | `0x00883C4D` slaughter cash-back | `e8 db 8b e0 ff` | `0x0068C82D` | 28 | yes |
| 4 | `0x008A4622` `SupplyCenterDockUpdate` | `e8 06 82 de ff` | `0x0068C82D` | 28 | yes |
| 5 | `0x008A1ED6` `ProductionUpdate::update` | `e8 52 a9 de ff` | `0x0068C82D` | 29 / 30 by `[ebx+4]`; kind 3 tail-jumps to stock | yes |
| 6 | `0x0088DE6D` dozer construction | `e8 2c e5 ea ff` | `0x0073C39E` | 31 `PRODUCTION_CONSTRUCTION` | yes |
| 7 | `0x009BB858` AI valuation | `e8 d0 0f cd ff` | `0x0068C82D` | 28 | optional |
| 8 | `0x009BBC4F` AI valuation | `e8 d9 0b cd ff` | `0x0068C82D` | 28 | optional |
| 9 | `0x009E7594` AI max-multiplier pick | `e8 94 52 ca ff` | `0x0068C82D` | 28 | optional |

7–9 are the AI's own reading of how productive a building is. Leaving them stock means an AI that
under-values a `PRODUCTION_MONEY` building — harmless for a human-facing mod, wrong for anything
that cares about AI economy play. They are the same edit as 1–4, so the cheap answer is to include
them; `0x009E7594` compares rather than accumulates, so confirm the semantics before assuming a
product is the right thing to hand it.

## 6. Data-side and tooling work

- **`.sagepatch` / `Patch.ini_surface()`** so `sage_ini` and `sage_lint` accept
  `Modifier = PRODUCTION_MONEY 1.25` on a patched build and reject it on a stock one.
- **`sage_ini/model/enums.py:ModifierType`** — four new members on the multiplicative side of its
  `SEPARATOR`, which then flows into `sage_ini.model.state` and the `sage_live` statics.
- **`sage_ini/model/state.py`** — `production_multiplier` currently means "resource output" and
  reads `PRODUCTION`. Under the split it should become `PRODUCTION * PRODUCTION_MONEY`, with
  siblings for the unit/upgrade/construction factors. `LEVEL_MODIFIER_KEYS` (which detects Edain's
  economy-level upgrades by looking for `HEALTH`/`PRODUCTION`) needs `PRODUCTION_MONEY` added or it
  stops recognising levelled economy buildings written in the new style.

## 7. Cost and risk

| | |
|---|---|
| edits to `.text` | 6 required (+3 optional) `call rel32`, plus 2 operands for the name table |
| new sections | 1 (relocated table + 4 strings + 3 thunks; roughly 450 bytes) |
| INI surface | 4 new `Modifier` keywords |
| model changes | `enums.py`, `state.py`, `.sagepatch` |
| effort | ~2 days including tests, most of it in the shared cave and its `verify` |
| risk | **low-medium.** Each hook is a wrapped call whose failure mode is a wrong rate, not a crash. The one crash-shaped risk is a mis-sized relocated name table walking off the end of a NULL-terminated array during INI load — which surfaces on the very first parse, so it cannot ship silently. |

Shared consequences:

- **Simulation state.** Income, build rates and construction rates all feed the lockstep
  simulation. Every peer needs the patched binary; replays recorded on it will not play back on a
  stock one and vice versa.
- **The keywords are a hard dependency for the data that uses them.** A `ModifierList` naming
  `PRODUCTION_MONEY` on a stock `game.dat` aborts the load with `"Attribute '…' not found"`. Mods
  must ship the patched binary rather than offer the keywords as an optional extra.
- **No existing behaviour changes.** Because `PRODUCTION` is untouched (§4.1), applying this patch
  to an unmodified install is a no-op until INI starts using the new names — which makes it a
  cheap patch to test and a cheap one to back out.

## 8. What a live test has to settle

**Settled on 2026-08-13** (live RotWK + Edain match, read out of process with `sage_live`):

- **The queue hook works and the arithmetic is right.** A keyword of 5.0 on the producing building
  measured as exactly `5.000` added to `entry+0x1c` per frame against a stock `1.000` — so the
  double-query widening of §4.3 keeps both factors, and the modifier is read off the *building*, as
  `mov ecx, [esi-8]` says.
- **The queue kinds are what §2.1 says.** `GondorBeregond` and `GondorBoromir_mod` both read
  `entry+0x04 == 3` while queued in a `GondorBarracks`, confirming the ledger path.
- **But kind 3 does not complete off the accrual**, which retired `PRODUCTION_HERO`. See §2.2 for
  the measurement and for where a working hero keyword would have to hook instead.

Still open:

1. **That plot-built structures go through `DozerAIUpdate`.** `0x0088DE43` is the *only* site in
   the image that advances `Object+0x288` and adds construction health, so everything must funnel
   through it — but that is an argument from absence. `FoundationAIUpdate` does **not** derive from
   the dozer (its base ctor is `0x00653114`, not the dozer's), so what plays "builder" for a
   settlement plot is unconfirmed. **Test:** build a plot structure and a builder-built structure
   with the same `PRODUCTION_CONSTRUCTION` and check both change.
2. **That `PRODUCTION_UPGRADE` reaches kind 2.** Kind 2 has a pre-check at `0x008A1E87` that can
   bail out before the accrual; only kind 3 was exercised live, and kind 1/2 were read off the
   disassembly. Queue an upgrade with the keyword live and confirm the rate.
3. **That a hero sold as an ordinary unit answers to `PRODUCTION_UNIT` and actually arrives
   sooner** (§2.2's closing note). This is the supported way to scale a hero under this patch, so
   it is worth confirming rather than assuming.
4. **That the four money sites are the whole of income.** Bounty, crates, tribute and campaign
   grants are *not* modified by `PRODUCTION` today and are therefore out of this patch's reach —
   confirm no faction's economy leans on a path that was never in the list.
5. **That the rate responds mid-build**, per §3.2's accumulate-not-derive reading, and that
   completion is clean: 100% with full health, no `GettingBuiltBehavior` re-derivation
   (`0x00856809`) snapping the bar backwards.
6. **Degenerate values:** multiplier `0`, negative, and very large, at every hook.
7. **Module identity for `0x00883C4D` and `0x008A4622`** (§2) if anything downstream depends on
   naming them correctly in documentation.
