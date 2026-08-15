# A mana cost for hero abilities — the RE, and what the patch does with it

> ⚠ **Experimental.** This patch is **unstable and largely untested** — it lives in
> [`patches/experimental/`](../patches/experimental/), `sage-patch list` marks it `exp`, and
> `sage-patch apply` warns before it writes. The status note below says how far it actually
> got; see the README's [Experimental patches](../README.md#-experimental-patches) note before
> applying it.

Engine build `2.01.2614.37001`, ImageBase `0x400000`. Addresses are VAs, read statically from the
repo's clean [`game.dat`](../../game.dat). The one live fact (§3) was measured against the recorded
match in [`match.snapshot.gz`](../../tests/sage_live/fixtures/match.snapshot.gz).

Implemented by [`patches/experimental/hero_mana.py`](../patches/experimental/hero_mana.py) as `HeroManaPatch`.

**Status: partly runtime-verified.** A traced build was played on 2026-08-01 (RotWK + Edain) and
the core works: both field tables relocate, all three new fields parse, the side table populates,
the pool deducts and regenerates, and the cost shows in the button description. **One issue is
open** — abilities driven by `WeaponFireSpecialAbilityUpdate` are not charged at all. §10 is the
open-work list; §9 is the verification list.

## 1. Why `UnitCost` is a no-op on a hero

`SpecialPower` already has `UnitCost` and `UnitCostDeathType` — `Int`s at `SpecialPowerTemplate`
`+0x80` and `+0x84`. On a hero the field is not weak, it is **inert**, and the reason is one shared
branch. The ControlBar's availability evaluator:

```
00943439  mov  ecx, esi                    ; the SpecialPowerTemplate
0094343b  call 0x688d3c                    ; ->getFinalOverride()
00943440  cmp  dword ptr [eax+0x80], 0     ; unitCost == 0 ?
00943447  je   0x943486                    ;   yes -> skip the check
00943449  mov  ecx, dword ptr [ebx+0x258]  ; obj->m_contain
0094344f  test ecx, ecx
00943451  je   0x94345c                    ;   no contain module -> esi = 0
00943453  mov  eax, dword ptr [ecx]
00943455  call dword ptr [eax+0x7c]        ;   -> the horde interface
0094345e  test esi, esi
00943460  je   0x943486                    ; no horde -> SKIP, same label as cost == 0
0094346a  mov  eax, dword ptr [eax+0x80]   ; unitCost
00943477  call dword ptr [eax+0x188]       ; horde->count()
0094347d  cmp  dword ptr [ebp+8], eax
00943480  ja   0x9438c8                    ; cost > members -> unavailable
```

**`0x943486` is the "carry on" label.** Both the cost-is-zero branch and the no-horde branch land
on it, so an object with no `ContainModuleInterface` — every lone hero — is not *refused*, it is
*exempted*. `UnitCost = 5` on a hero is free.

The same shape appears verbatim at two more sites, which is three independent confirmations:

| site | VA | note |
|---|---|---|
| ControlBar availability | `0x943440`, `0x94346a` | greys the button |
| shared can-do gate | `0x82da20`, `0x82da4a` | inside `0x82d925`, **9** callers |
| payment — kills N members | `0x855057` … `0x855116` | second near-identical copy at `0x85522f` |
| tooltip | `0x808688`, `0x808697` | formats `TOOLTIP:UnitCost` (`0xc4ee20`) |
| `getUnitCost` accessor tail | `0x807747` | |

Corroborated in the shipped data: every `UnitCost` user across `__edain_data.big` and
`_patch201ini.big` is a horde or structure power — `SpecialPowerDunklesRitual`,
`SpecialAbilityNecroWellOfSouls`, `SpecialAbilityFluchesHexenmeisters`,
`SpecialAbilityHallderTrollhohen`. Nobody has put it on a lone hero, which is what you would
expect of a field that does nothing there.

## 2. The activation path

```
order / UI ─► Object::doSpecialPower*  ─► SpecialPowerStore::canUseSpecialPower   (the predicate)
                                       ─► Object::getSpecialPowerModule           (the module)
                                       ─► module vtable +0x2c / +0x30 / +0x34     (the effect)
```

`SpecialPowerStore::canUseSpecialPower(Object*, SpecialPowerTemplate*)` at **`0x7b1d79`**
(`__thiscall`, two stack arguments, `ret 8`, bool in `al`) is the whole affordability decision:

```
007b1da2  call 0x68c26d          ; Object::getSpecialPowerModule(tmpl) - walks Object+0x24C
007b1dbd  call [edx+0x48]        ; module->isReady()                   - the recharge check
007b1dc6  call 0x68b678          ; Object::getControllingPlayer()
007b1dee  call 0x6ac22f          ; Player::hasScience()                - RequiredSciences
007b1e14  call 0x75cdc4          ; obj->m_status (+0x94) vs PreventActivationConditions (+0x64)
```

It has **six** callers, and that list is why this patch is small:

| caller | what it is |
|---|---|
| `0x68e63f`, `0x68e716`, `0x68e778`, `0x68e7d0` | the four `Object::doSpecialPower*` entries |
| `0x7e9d4d` | AI-side special-power evaluation |
| `0x8b70aa` | `AISpecialPowerUpdate`'s own tick |

**The AI comes free.** It asks the same predicate the activation path asks, so a hero that cannot
pay simply does not fire. That is the opposite of
[`second-resource`](second-resource.md), where a cost the AI could not
see meant permanent economic stalls. What the AI still will not do is *plan* around mana — it will
not hold a power back to afford a better one. A behaviour gap, and it needs no code.

The three activation variants share one shape — resolve the module, then dispatch:

| VA | variant | dispatch | window taken | resumes at |
|---|---|---|---|---|
| `0x68e67a` | `doSpecialPower` | vtable `+0x2c` | `0x68e73e` (5 bytes) | `0x68e743` |
| `0x68e754` | `doSpecialPowerAtLocation` | vtable `+0x30` | `0x68e7a1` (5 bytes) | `0x68e7a6` |
| `0x68e7ac` | `doSpecialPowerAtObject` | vtable `+0x34` | `0x68e7f9` (8 bytes) | `0x68e801` |

⚠ **Each variant lets its caller skip the predicate.** `cmp byte ptr [ebp+0x14], 0` at `0x68e706`
and `0x68e769` guards the `canUseSpecialPower` call on a caller-supplied bool. So the gate is not
sufficient on its own: the charge has to re-check, or a scripted activation spends mana it does not
have and wraps an unsigned counter.

No branch anywhere in `.text` lands strictly inside any of the six windows this patch overwrites —
checked by disassembling the section and collecting every `jcc`/`jmp`/`call` immediate target.

## 3. `Object+0x74` is the object id

Needed because the pool has to be keyed by something that is the *same number on every peer*.

**Measured, not inferred.** For **386 of 386** live objects in the recorded match, the dword at
`Object+0x74` equals the id `TheGameLogic`'s object table carries beside the `Object*`. Every other
offset in the first `0x400` bytes was tested and none matched more than a handful.

⚠ **The id space is not dense.** 382 of those 386 sat at `slot == id`; four engine-reserved objects
held ids `99999996`–`99999999` at slots 4403–4406. An array indexed by the raw id would be written
400 MB out of bounds by those four. The patch folds the id instead — see §5.

This belongs in [`live-object-model.md`](live-object-model.md) §2 as well; it removes an
indirection `sage_live` currently takes through the object table.

## 4. The three new fields

A hero has **one** pool and **many** abilities, so the two quantities live on different blocks:

| block | field | unit |
|---|---|---|
| `SpecialPower` | `ManaCost` | whole points per activation; **0 leaves the power exactly as it is today** |
| `Object` | `ManaPool` | the caster's maximum, whole points; 0 = the patch default |
| `Object` | `ManaRegen` | hundredths of a point per logic frame; 0 = the patch default |

`SpecialPowerTemplate` is `0x88` bytes, id at `+0x14`, `UnitCostDeathType` at `+0x84` its last
field, and the constructor zeroes both cost fields at `0x7b2007`/`0x7b200d` — **no padding to hide
in**, so it grows to `0x8C` with `ManaCost` at `+0x88`. The `Object` pair is not stored in a
template at all; see §8.

The field-parse table is the cheapest move in the tree: base `0x00DA5FD8` in writable `.data`, 24
entries of `{name, ParseFn, userData, offset}`, all-zero terminator at `0x00DA6158`, **no slack
after it** (`0x00DA6168` is live data), and exactly **two** references —

```
0x7b1abd   mov eax, 0xda5fd8 ; ret     the getFieldParse accessor
0x7b2324   push 0xda5fd8               the parse call
```

— against `production-condition`'s sixteen and `Object.BuildCost`'s five. Both new entries use the
stock `Int` parser at `0x42ec5e`, so no parser had to be written: its signature is cdecl
`(INI*, void *instance, void *store, const void *userData)` with `store == instance + offset`.

The `Object` table is the same shape: base `0x00DA3DF8`, 191 entries, terminator at `0x00DA49E8`,
**five** references (`0x73bdf4` a `mov`, four `push`es). It has **no interior reference** — a byte
scan reports one at `0x7162a4`, but that address disassembles to `call 0x723cee`, whose `E8`
opcode plus the first three bytes of its displacement happen to spell `0x00DA45E8`. A false
positive; the table relocates as a unit.

Growing the `SpecialPower` struct costs four kinds of edit:

- **three `push 0x88` → `push 0x94`** at `0x7b218e`, `0x7b21da`, `0x7b2292`. (26 other sites in the
  image allocate `0x88` bytes for other classes, so the three are named, never searched for.)
- **three `call operator new` → `call <cave>`** at `0x7b2195`, `0x7b21df`, `0x7b2297`. The
  constructor has no five-byte site safe to take and no room for three more stores, so the grown
  tail is zeroed where the memory is handed out instead.
- **the copy constructor's epilogue** at `0x7b1f53` (8 bytes, `8b c3 5e 5d 5b c2 04 00`). It copies
  field by field, and an INI **override block is a copy** — without this, an override that does not
  mention `ManaCost` would silently drop it. `ebp` is the *source pointer* in that routine, not a
  frame pointer.
- nothing else: `0x88 → 0x94` stays in the same DMA allocator class.

**Every template read must go through `getFinalOverride` (`0x688d3c`)**, for the same reason: the
live template is the last copy in the chain, not the one the base name resolves to.

## 5. Where the pool lives

A cave-resident array of `{ UnsignedInt id; UnsignedInt stamp; UnsignedInt value; }` rows, 8192 of
them, indexed by `id & 8191`. `value` is in **hundredths of a point**, which is what lets the whole
computation stay in exact integers with no division anywhere — and therefore nothing for two peers
to round differently.

**The pool is not ticked; it is computed on read:**

```
value = min(cap, stored + clamp(now - stamp, 0, 0xFFFF) * regen)
```

`now` is `[[TheGameLogic]+0x40]`, the logic frame. Only a spend writes a row. That single decision
removes most of what the scoping note budgeted:

- **No per-frame hook.** Nothing walks the table each frame, and in particular nothing has to hook
  `GameLogic::update` — which matters, because [`live_bridge`](../patches/live_bridge.py) already
  owns those five bytes and the two would have collided. There is a test for the pair.
- **No init hook.** A row whose `id` does not match reads as *full*, so a hero that has never cast
  is full by construction, at frame 0 or frame 40,000. Row 0 is never a false match: object ids
  start at 1.
- **No destroy hook.** An id reused by a new object finds a row that still names the old one, and
  reads full.
- **No savegame format change.** A load starts with the table zeroed, so every hero comes back
  full — a defined, benign state, not "everyone drained".

**Overflow is structural, not hoped for.** Every INI-supplied number is clamped to `0xFFFF` before
it is multiplied, and the gain is clamped to the cap *before* being added to the stored value:

| product | bound |
|---|---|
| `elapsed * regen` | `0xFFFF * 0xFFFF` < 2³² |
| `pool * 100` | `0xFFFF * 100` < 2²³ |
| `gain + stored` | ≤ 2 × cap ≤ 13,107,000 |

**Collisions.** Two live objects whose ids differ by a multiple of 8192 share a row; the one that
does not own it reads *full*. So the failure mode is "a power was occasionally free" — never a
crash, never a wrong refusal, and never a desync, because every peer folds the same ids the same
way. It takes two mana-using heroes alive at once with ids 8192 apart.

## 5a. Determinism

Affordability decides whether a power fires, so the pool is **inside the simulation** and every
peer has to reach the same number from the same inputs. It does, because every input is simulation
state: the object id (`Object+0x74`), the logic frame, and template fields parsed from the same
INI. Nothing reads a wall clock, a random source, or anything client-local.

Three specifics that keep it that way, and are easy to break:

- **No pointer value ever reaches the arithmetic.** The template side table (§8) is *keyed* by a
  `ThingTemplate*`, which differs between machines - but it is only ever probed with a pointer both
  peers derived the same way, and a probe is a read. Were a pointer to reach a *comparison whose
  result changes the pool*, that would desync.
- **The read path writes nothing.** The ControlBar runs on the local client only, so `check` and
  `value` are pure; a test disassembles the cave and asserts no store through a pointer exists
  outside `spend`. Only the logic-side charge writes a row, and it runs on all peers.
- **No per-frame walk to schedule.** Computing the pool on read (§5) means there is no ticked pass
  whose position in the frame or iteration order could differ; a ticked pool would have to be
  frame-locked and order-stable.

> **Every peer must run the same patched binary.** A patched and an unpatched client desync the
> first time a costing power fires, and replays do not cross. Same rule as `production-condition`,
> stricter than `replay-outcome`, whose effects are client-local.

## 6. The five hooks

| what | site | form |
|---|---|---|
| the gate | `0x7b1d79` (entry, 5 bytes) | `jmp` → cave; refuses with `xor eax,eax; ret 8` |
| the charge ×3 | the windows in §2 | `jmp` → cave; skips the dispatch and `add esp,8` on refusal |
| the button | `0x94343b` (`call getFinalOverride`, 5 bytes) | `call` → cave, which must **return** the override |

The ControlBar one is a `call`, not a `jmp`, because the instruction it replaces produces a value
the caller immediately uses (`cmp [eax+0x80], 0`). On a refusal the cave drops its own return
address and jumps to `0x9438c8` — the `xor eax, eax` tail the engine's own `unitCost > members`
branch already uses, in the same function at the same stack depth (nothing between `0x94343b` and
`0x943480` pushes).

**The ControlBar path is a pure read.** It runs on the local client only, so a write there would
diverge from every other peer. A test disassembles the cave and asserts that no store through a
pointer exists outside the `spend` routine.

## 7. What is deliberately not covered

- **`MSG_DO_SPELLBOOK_SPECIAL_POWER` (`0x456`)** is player-scoped, not hero-scoped, and does not run
  through `Object::doSpecialPower*`. Out of scope.
- **The shared can-do gate at `0x82d925`** (9 callers) is not hooked. Everything it guards reaches
  `Object::doSpecialPower*` afterwards, so an unaffordable power is still refused — one step later,
  and without a "cannot do that" cue.
- **A mana bar.** Showing the number needs the Palantir `.apt`, and
  [`sage_apt`](../../sage_apt/README.md) is not production-ready. The button state and a future
  `TOOLTIP:ManaCost` line (the `0x808697` pattern) carry the information meanwhile.
- **Per-`Object` declaration of the pool.** See §8.

## 8. Where the caster's numbers are stored

`ManaPool` and `ManaRegen` are declared on the `Object` block but are **not** stored in the
`ThingTemplate`, because there is nowhere safe to put them:

- The one apparent hole is `+0x5E8`, two bytes between `CampnessValue` (`Int` at `+0x5E4`) and
  `BuildCost` (`UInt16` at `+0x5EA`) that no INI field names. It is **not** padding: the
  constructor writes it as a word at `0x73ff8d` (`mov word ptr [ebx+0x5e8], si`), and again at
  `0x740630`. A live non-INI member, and it would have been a memory-corruption bug rather
  than a missing field. [`second-resource`](second-resource.md) §7.1 identifies what it
  actually is: the template's engine-assigned id.
- Growing the struct is possible but a poor trade: `sizeof` is `0x650`, allocated at exactly two
  sites (`0x6d2750` in `ThingFactory::newOverride`, `0x6d27bd` in `newTemplate`), but with 11,143
  instances an allocation site the scan missed corrupts the heap. The `SpecialPowerTemplate` case
  showed the adjacent-`push`/`call` scan *can* miss one.

So the pair parses into a **side table in the cave, keyed by the `ThingTemplate*`** — an
open-addressed array of `{template, pool, regen}`, 1024 rows, hashed `(ptr >> 4) & 1023`.
Templates are `0x650` apart, so `>> 4` steps 101 slots per template and the probe covers the whole
table. The parse function borrows the engine's own `Int` tokenizer, pointing it at a scratch dword
instead of at the template, then files the value against the instance being parsed.

**The override problem, and the hook that closes it.** An INI override block is a *copy* of the
template, made by `ThingFactory::newOverride` → `ThingTemplate::copyFrom` (`0x6d1d80`,
`__thiscall`, `ret 4`) and **nowhere else**. A pointer-keyed table would lose the row there, so the
patch wraps that one call and copies the row from source to destination. A miss falls back to the
patch defaults; it never yields a wrong number.

## 8a. The description line

Case `0x18` of the button-description builder appends `UnitCost` as one formatted line. The patch
takes the five bytes of that case's own `cmp ecx, 0x18` / `jne <done>` guard at `0x808675`, makes
the same decision in the cave, appends a `ManaCost` line first, and falls into the stock body at
`0x80867a` — so both lines appear.

The line carries **two** numbers — what the ability costs and what the caster currently has:

```
push <current> / push <cost>   ; the varargs, lowest address read first
push 0                         ; fetch's `exists` out-parameter - NOT a value slot
push "TOOLTIP:ManaCost"
mov  ecx, [TheGameText]        ; 0x00DE4B04
mov  eax, [ecx]
call [eax+0x44]                ; fetch(label, exists) - __thiscall, cleans both
push eax
lea  eax, [ebp-0x28]           ; the builder's buffer, in its own frame
push eax
call 0xadf7e0                  ; format into it  (the one relative call, re-derived)
add  esp, 0x10                 ; two varargs + the concat's two arguments
```

**The two-number form is the idiom's own, not an invention.** `fetch` cleans its two arguments, so
the varargs `0xadf7e0` reads at `[esp+0xc]` are whatever sits below `exists`, lowest address first
— which makes the *last* push before `exists` the first `%d`. Two sites pin the cleanup rule:
the one-vararg `TOOLTIP:UnitCost` block cleans `0xc`, and `CONTROLBAR:UnderConstructionDesc` at
`0x677e6b`, which passes a `double`, cleans `0x10`. So a second value costs exactly one more dword
of cleanup. Getting that constant wrong corrupts the builder's frame rather than failing, which is
why a test asserts both blocks' constants.

The caster is the builder's own `ebp-0x1c` — the `Object` its prologue resolved
(`[0x00DE4830]` vtable `+0x12c` → `Drawable`, `+0xfc` → `Object`; `0x00807AE4` passing it to
`getControllingPlayer` is what identifies it). A null one prints zero rather than dropping the
line, so the cost still shows. The pool is divided by `100` on the way out, so the string sees
whole points.

`TOOLTIP:ManaCost` is a **localization key**, exactly like `TOOLTIP:UnitCost` — a mod has to add it
to its `.str`/`.csf` string table, and it needs **two** `%d`s, cost first:
`"Mana: %d  (you have %d)"`. `TOOLTIP:ManaPool` (§8a2) takes one.

## 8a2. The pool, under the hero's level

The same builder's **hero revive / recruit** case describes the hero itself: it resolves the
hero's `ThingTemplate` through `TheThingFactory::findTemplate` (so `esi` is the template, not the
button), appends an `APT:RankLabel` line for the level, and then folds the accumulated line at
`ebp-0x2c` into the description at `ebp-0x18`.

The patch takes that fold — `lea ecx, [ebp-0x18]` + `call` at `0x8085c4`, eight bytes — adds a
`TOOLTIP:ManaPool` line to the same buffer first, then performs the fold. So the pool reads as one
more property of the hero, immediately under its level, which is where a player already looks for
"what is this hero".

Two deliberate limits:

- **Only the maximum.** A revive button describes a hero that does not exist yet, so there is no
  current value to show. The live figure belongs to a live object.
- **Silent unless declared.** No line at all unless the template has a `ManaPool` row, so an
  unmodified mod sees no change — the same rule `ManaCost = 0` follows.

## 8b. A mana *bar* under the experience bar — not done, and why

The readout above is text in the description. A live `current / max` next to the experience bar
was asked for and **not delivered**; this is what the search settled, so a later attempt need not
repeat it.

The Palantir HUD is APT (Flash), and the engine feeds it through data bindings registered with
`0x6241ce` (numeric) and `0x6236f6` (string). A binding holds a *pointer* to the value and the
movie re-reads it every frame, which is why the resource bar needs no per-frame push. There are
**28 such registrations in the whole image**, and they are:

| group | paths |
|---|---|
| resource bar | `Palantir/ResourceBar/Resources/`, `…/CommandPoints/`, `…/ResourceMultiplier/`, `ResourceBar/ResourceIcon` |
| spellbook | `Palantir/%s/Spell%d/` |
| banner UI | `BannerUI/~Location%d/Banner/…` |
| campaign / CAH screens | `StrategicVeterancy/…`, `Cah::TypeIcon%d`, `CahAward:Image_%d`, … |

**None is a unit-detail or hero binding**, so there is nothing to hang a mana number on. The
experience bar is not a `.wnd` window either: `Window.big` holds no `ControlBar.wnd` reference and
no `Experience` string, and the `GenExpBar1` / `GenExpBarTop1` image names in the binary are
unreferenced Generals-era leftovers.

That leaves two routes, both bigger than "basic":

1. **Author the field into the Palantir `.apt`** and register a matching binding. The engine half
   is small and well understood — one `0x6241ce` call with a path and a mirror dword. The movie
   half is blocked on [`sage_apt`](../../sage_apt/README.md), whose own README says it is "not yet
   fully functional and largely untested"; the same schedule risk the second-resource costing flagged
   for a second resource icon.
2. **Draw it natively**, beside the in-world health bar rather than in the Palantir. No APT, but it
   needs the health-bar draw located and the placement iterated against a running game.

Until one of those lands: the ability's description shows its cost *and* the caster's current
points (§8a), the hero's maximum shows under its level (§8a2), and an unaffordable power greys out
(§6). What is missing is only the always-visible bar, not the number.

## 9. Verify before shipping

Nothing below is a known defect; each is a claim the static work cannot close.

1. **Cast a power with `ManaCost` set and watch the button grey out**, then come back after
   `pool*100/regen` frames. That exercises the gate, the charge and the ControlBar in one go.
2. **`Object+0x74` on a second match**, ideally across a save and reload. 386/386 is strong but it
   is one sample, and it is the single fact the row table is keyed on.
   [`sage_live`](../../sage_live/README.md) can check it in a minute.
3. **An INI override block** — one that re-declares a *power* without `ManaCost` (confirming the
   copy-constructor edit at `0x7b1f53`), and one that re-declares an *Object* without `ManaPool`
   (confirming the `copyFrom` wrap at `0x6d2781`). These are the two inheritance paths, and both
   fail silently rather than loudly.
3a. **The two description lines**, with `TOOLTIP:ManaCost` (two `%d`s) and `TOOLTIP:ManaPool`
   (one) added to a `.str` file. Hover a costing ability on a hero that has spent some: the line
   should read the cost and the hero's *current* points, and the second number should climb as it
   regenerates. Expect no line at all when `ManaCost` is 0. Hover a hero's revive/recruit button:
   a `ManaPool` line right under its level, and none when the hero declares no pool.
   ⚠ The cleanup constant on the two-value line (`add esp, 0x10`) is derived from two other call
   sites, not observed - a wrong one corrupts the builder's frame, so watch for a crash or garbled
   text on the *first* hover.
4. **An AI hero with a mana power** — confirm it stops casting when empty rather than stalling or
   spamming, via the two AI callers in §2.
5. **A long match**, for the row-collision behaviour of §5, and to confirm ids stay bounded by the
   object table for ordinary objects.
6. **Multiplayer between two identically patched clients.** Affordability is inside the simulation:
   a patched and an unpatched client desync the first time a costing power fires, and replays do
   not cross. Same rule as `production-condition`, stricter than `replay-outcome`.

## 10. Open work

State after the live session of **2026-08-01**, played on RotWK + Edain with a
`HeroManaPatch(trace=True)` build and [`tools/hero_mana_trace.py`](../../tools/hero_mana_trace.py)
attached.

### 10a. Confirmed working in a real game

Nothing below is inference; each was read out of the running process.

- **Both field tables relocate and parse.** Four `SpecialPower` templates carried a live
  `ManaCost` (100 / 50 / 25 / 33) and one `Object` carried `ManaPool = 145`, `ManaRegen = 6`. The
  `Object` pair proves the custom parse function and the `ThingTemplate`-keyed side table (§8) run.
- **The charge deducts and the pool regenerates.** `SpecialAbilityLightningSword` at cost 50 took
  a pool from 145 to 95, and a later cast saw 136.44 - the compute-on-read regen of §5 working.
- **The description line works.** Confirmed in-game: the mana cost appears in the button
  description, which also settles the `add esp, 0x10` cleanup constant §8a derives rather than
  observes.
- **`Object+0x74`** holds up as the row key - charges landed on the casting hero.

### 10b. Fixed from that session

- **Double-charge.** An ability with an update module runs *both* the dispatch and the trigger, so
  charging at both took the price twice. Measured:

  ```
  frame 1696  DISPATCH v1   cost=50 available=145    -> CHARGED   (the click)
  frame 1713  ABILITY-FIRE  cost=50 available=96.02  -> CHARGED   (the fire, 17 frames later)
  ```

  The charge now lives only at the trigger; the dispatch sites are observation points that exist
  in `--trace` builds and nowhere else.
- **A missing fourth activation variant.** `Object::doSpecialPower` has a **targetless** form
  dispatching through vtable `+0x28` at `0x0068E664`, sitting *before* the three known ones and
  using a different slot. A `Command = SPECIAL_POWER` button with no target emits exactly that, so
  Gandalf's Word of Power went through it and nowhere else - invisible to every hook. Now in
  `DO_SPECIAL_POWER_SITES`.

### 10c. **OPEN — `WeaponFireSpecialAbilityUpdate` abilities are never charged**

The one real defect left. Word of Power (`ManaCost = 100`) produces a `DISPATCH v0` record and
then **nothing**: no `ABILITY-FIRE`, so no charge.

The charge sits at `0x00855042`, reachable down only one branch of the ability tick:

```
0085502d  mov  eax, [ebp+0x2c]     ; the unpack countdown
00855032  je   0x855195            ; already zero -> a third path
00855038  dec  eax
0085503c  jne  0x85516b            ; still counting -> not yet
00855042  <the charge, and the engine's own UnitCost payment>
```

`WeaponFireSpecialAbilityUpdate` (`SkipContinue = Yes`, `UnpackTime = 1700`) exits down one of the
other two. It *does* reach the tick - two of the tick's four direct callers, `0x008963D6` and
`0x0089643A`, are in its code region (its module data ctor is `0x00895D5A`).

**To finish it:** find where that module actually fires its `SpecialWeapon` and charge there, or
identify the branch it leaves the tick by. Leads:

| what | where |
|---|---|
| the tick | `0x00854DF7`, virtual through vtable `0x00C769EC` slot 0 |
| its direct callers | `0x008963D6`, `0x0089643A` (WeaponFire), `0x008A00DF`, `0x008B1966` |
| the branch targets to classify | `0x00855195` (countdown already zero), `0x0085516B` (still counting) |
| the module data ctors | `WeaponFireSpecialAbilityUpdate 0x00895D5A`, `SpecialAbilityUpdate 0x00851909` |

**The stop-gap, if timing can wait:** charge at the dispatch *and* the trigger, and have the
second skip when the same hero already paid for the same power within its own `ReloadTime`
(`template+0x20`, milliseconds). Everything is then charged exactly once; the cost is that
`WeaponFire` abilities pay at the click rather than at the effect, so cancelling one mid-cast
still costs. Correct on the money, imperfect on the moment.

### 10d. Known gaps that are not bugs

- **Instant powers with no ability update are not charged.** `SpecialAbilitySandboxHeroExperienceGrant`
  dispatches and never triggers. Deliberate per §7's reasoning - under-charging is visible and
  safe, double-charging is silent and wrong - but it is a gap, and a `--trace` build names the
  class exactly (a `DISPATCH` with no matching `ABILITY-FIRE`).
- **`SpecialAbilityWordOfPowerGandalf` is shared.** Saruman, Gimli, Boromir and the Imladris
  hordes point at the same template, so a `ManaCost` on it charges all of them. A hero wanting its
  own price needs its own `SpecialPower` block.
- **A mana bar** - still §8b.

### 10e. Tooling and docs still to do

Small, independent of §10c, and each cheap now that the facts are known.

- **Regenerate `module-reference.json` and `ini-types.json`.** Neither carries `ManaCost`,
  `ManaPool` or `ManaRegen`, so `sage_ini` consumers that read the generated tables (rather than
  the hand-written model) do not know the fields exist. The model in
  [`sage_ini/model/ini_objects.py`](../../sage_ini/model/ini_objects.py) *is* updated.
- **Teach `sage_live` to read the pool.** One row lookup - `g_mana[[obj+0x74] & (POOL_ROWS-1)]`,
  validated against the row's id - would put a hero's current mana in `Observation`, which is what
  any policy or overlay would want. Nearly free now that `+0x74` is known.
- **Record `Object+0x74` and `Object+0x258` in
  [`live-object-model.md`](live-object-model.md).** Both are new facts about the object layout and
  belong there whether or not this patch survives. `+0x74` (the object id, 386/386) in particular
  removes an indirection `sage_live` currently takes through the object table; `+0x258` is the
  `ContainModuleInterface*` that makes `UnitCost` inert on a hero (§1).

### 10f. Reproducing the session

```sh
sage-patch apply hero-mana --trace --in game.dat.backup --out game.dat
# close the game, install, start it, then (elevated, game.dat runs as admin):
python tools/hero_mana_trace.py
```

A cast should read `DISPATCH v<n>` -> `ABILITY-FIRE` -> `SPEND-ENTER` -> `SPEND ... CHARGED`, once
each. Two `SPEND ... CHARGED` for one cast is the double-charge regression; a `DISPATCH` with no
`ABILITY-FIRE` is the §10c class.

⚠ The trace ring's layout is part of the cave, so a reader only makes sense against the build it
came from. A reader pointed at an older `.heromna` prints plausible-looking garbage - budget a
minute for that confusion, or add the build marker the reader currently lacks.
