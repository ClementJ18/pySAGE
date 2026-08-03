# `BannerCarrierUpdate` — an `ObjectFilter` on the replenish scan

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR), read from the
uploaded `game.dat` (11,347,456 bytes — the stock image plus an appended `.cahfac` cave, so `.text`
and `.rdata` are byte-identical to the clean build).

**Verdict up front: this is cheap.** An `ObjectFilter` field in a `ModuleData` is **four bytes** — an
index into one global interned filter store — not the 148-byte structure it describes. So the whole
feature is four code writes, one relocated field-parse table and about 90 bytes of cave code. No
enum grows, no mask runs out of bits, no structure other than `BannerCarrierUpdateModuleData` changes
size, and a mod that does not write the new keyword takes the stock path bit-for-bit.

Two things need a decision rather than a lookup:

- **The scan the filter would guard runs whenever `ReplenishNearbyHorde = Yes`**, not only when
  `ReplenishAllNearbyHordes = Yes`. See [The one design decision](#the-one-design-decision).
- **Relationship tokens work, but only if the patch skips the convenience wrapper.** `SAME_PLAYER`
  and `ALLIES` are already distinct in the engine; the wrapper at `0x007640c1` starves the evaluator
  of a source player and makes every relationship token return false. Calling `0x00763543` directly
  costs 16 extra bytes and buys the own-units-versus-ally's-units distinction that the partition scan
  cannot express. See
  [Relationship tokens](#relationship-tokens-and-the-wrapper-that-disables-them).

- **Cost:** 1 byte + 3 rel32/imm32 repoints + a 224-byte table copy + ~90 bytes of cave.
- **Risk:** low. The filter is skipped unless explicitly specified, by construction.
- **Status:** **built** — see [`patches/banner_filter.py`](../patches/banner_filter.py).

```
sage-patch apply banner-filter --in game.dat.backup --out game.dat
sage-patch apply banner-filter --keyword HordeFilter --only-when-all --in ... --out ...
sage-patch verify banner-filter game.dat
```

## The module as it stands

`ModuleFactory::addModule` registers it at `0x00659464`:

| what | VA |
|---|---|
| name string `"BannerCarrierUpdate"` | `0x00c0b548` |
| `newModule` | `0x0064de4c` (`operator new 0x20`) |
| `newModuleData` | `0x0064de84` |
| interface mask | `1` |
| `ModuleData` vtable | `0x00c65f18` |
| `ModuleData` ctor | `0x0089a765` |
| `ModuleData` vdtor / dtor | `0x0089ae6e` / `0x0089a816` |
| `buildFieldParse` | `0x0089ae8a` |
| field-parse table | `0x00c66090` |

`newModuleData` is the ordinary three-step shape — allocate, construct, register the parse table:

```
0064de90  6a 44              push 0x44              ; sizeof(ModuleData)
0064de92  e8 4918deff        call 0x42f6e0          ; operator new
0064dea5  e8 bbc82400        call 0x89a765          ; ctor
0064debb  68 8aae8900        push 0x89ae8a          ; buildFieldParse
0064dec1  e8 f7fcddff        call 0x42dbbd
```

### `ModuleData` layout — `0x44` bytes, fully packed

| offset | field | type |
|---|---|---|
| `0x00` | vtable | — |
| `0x08` | `IdleSpawnRate` | Duration |
| `0x0c` | `MeleeFreeUnitSpawnTime` | Duration |
| `0x10` | `DiedRespawnTime` | Duration |
| `0x14` | `MeleeFreeBannerReSpawnTime` | Duration |
| `0x18` | `MorphCondition` | vector |
| `0x24` | `ExpLevelDraw` | vector |
| `0x30` | `BannerMorphFX` | FXList\* |
| `0x34` | `UnitSpawnFX` | FXList\* |
| `0x38` | `ReplenishNearbyHorde` | Bool |
| `0x39` | `ReplenishAllNearbyHordes` | Bool |
| `0x3c` | `ScanHordeDistance` | Real |
| `0x40` | `UpgradeRequired` | AsciiString |

There is no slack — `0x40..0x44` is the `AsciiString` and the allocation ends there. **A new field must
grow the allocation.** The ctor confirms the tail:

```
0089a7e7  c6 4638 00         mov byte [esi+0x38], 0     ; ReplenishNearbyHorde
0089a7eb  c6 4639 00         mov byte [esi+0x39], 0     ; ReplenishAllNearbyHordes
0089a7ef  f30f11 463c        movss [esi+0x3c], xmm0     ; ScanHordeDistance = 0
```

`0x44` is written in exactly one place (`0x0064de90`). Nothing `memcpy`s the structure.

## Where the replenishing actually happens

`BannerCarrierUpdate::update()` sits at `0x0089ace4`. It is an adjustor thunk: the Object is
`[ecx-8]`, the `ModuleData` is `[ecx-0xc]`, and the real `this` is `ecx-0x10`. After a chain of status
and kind-of rejections it reaches the branch that matters:

```
0089adc7  80 7f38 00         cmp byte [edi+0x38], 0     ; ReplenishNearbyHorde
0089adcb  74 10              je   0x89addd              ; No  -> normal own-horde spawn path
0089adcd  8b 4dfc            mov  ecx, [ebp-4]
0089add0  83 c1 f0           add  ecx, -0x10
0089add3  e8 b7fdffff        call 0x89ab8f              ; Yes -> THE NEARBY-HORDE SCAN
0089add8  e9 89000000        jmp  0x89ae66
```

`0x0089ab8f` has exactly one caller. It is the only place `ScanHordeDistance` and
`ReplenishAllNearbyHordes` are read.

### The scan, `0x0089ab8f`

`edi` is loaded with the `ModuleData` at `0x0089abb3` and is live, untouched, for the whole function
(`pop edi` only at `0x0089acd5`). It builds a partition filter on the stack from the banner's own
controlling player (`Object::getControllingPlayer` at `0x0068b678`, filter vtable `0x00c1676c`), then
asks `ThePartitionManager` (`[0x00de4354]`) to iterate objects within `ScanHordeDistance` of the
banner's position (`[obj+0x38]`) via `0x00a39340`.

The loop body runs `0x0089ac34 .. 0x0089acb7`, with `ebx` = the candidate `Object*`:

```
0089ac34  6a 02              push 2                     ; KINDOF_IMMOBILE
0089ac36  8b cb              mov  ecx, ebx
0089ac38  e8 af31bbff        call 0x44ddec              ; Object::isKindOf
0089ac3d  84 c0              test al, al
0089ac3f  75 76              jne  0x89acb7              ; immobile -> next object
0089ac41  8b cb              mov  ecx, ebx
0089ac43  e8 1e1cdfff        call 0x68c866              ; -> contain interface via [obj+0x258]
0089ac4a  85 f6              test esi, esi
0089ac4c  74 69              je   0x89acb7
          ...                                           ; vslots 0x17c vs 0x188: room in the horde?
0089ac6c  73 32              jae  0x89aca0
0089ac6e  83 c3 08           add  ebx, 8                ; <- ebx clobbered from here on
0089ac71  53                 push ebx
0089ac72  ff 908c010000      call [eax+0x18c]           ; spawn the replacement -> esi
0089ac7e  8b ce              mov  ecx, esi
0089ac80  e8 641bdfff        call 0x68c7e9
0089ac85  8b 47 34           mov  eax, [edi+0x34]       ; UnitSpawnFX
0089ac88  85 c0              test eax, eax
0089ac8a  74 0c              je   0x89ac98
0089ac8c  6a 00              push 0
0089ac8e  56                 push esi
0089ac8f  50                 push eax
0089ac90  e8 c56ec1ff        call 0x4b1b5a              ; FXList::doFXObj
0089ac98  80 7f39 00         cmp  byte [edi+0x39], 0    ; ReplenishAllNearbyHordes
0089ac9c  74 2b              je   0x89acc9              ;   No  -> BREAK out of the loop
0089ac9e  eb 17              jmp  0x89acb7              ;   Yes -> keep scanning
0089acb7  8d 4df0            lea  ecx, [ebp-0x10]
0089acba  e8 5aa2baff        call 0x444f19              ; iterator next -> ebx
```

So `ReplenishAllNearbyHordes` is **not a mode switch on the scan** — it is a loop-break. The scan
always runs when `ReplenishNearbyHorde = Yes`; `ReplenishAllNearbyHordes = No` merely stops it after
the first horde it actually replenished.

`0x0089ac34` is the natural filter point: `ebx` is still the untouched candidate object, and nothing
has been read from it yet.

## The `ObjectFilter` ABI — the reason this is cheap

An `ObjectFilter` keyword does **not** embed a filter in the `ModuleData`. It stores a 4-byte index
into one global interned store, and the store owns the 148-byte descriptors.

Proof, from the parse function's tail (`0x0076392f`):

```
00763c4b  8d 8540ffffff      lea  eax, [ebp-0xc0]       ; the locally-parsed descriptor
00763c51  50                 push eax
00763c52  e8 c3f7ffff        call 0x76341a              ; intern -> index
00763c5b  89 06              mov  [esi], eax            ; 4 bytes into ModuleData+offset
```

`0x0076341a` linearly scans the store for an equal descriptor; on a hit it bumps the refcount and
returns that index, on a miss it appends and returns `count-1`.

| store fact | value |
|---|---|
| `begin` / `end` | `[0x00de78b0]` / `[0x00de78b4]` |
| element stride | `0x94` (148 bytes) |
| "was specified" byte | `+0x88` |
| refcount | `+0x8c` |
| unset sentinel | `-1` |

This is corroborated across the whole engine: of the 59 fields in
[`module-reference.json`](module-reference.json) that use parse function `0x0076392f`, **56 occupy
exactly 4 bytes**. (The three apparent outliers — `OpenContain.ManualPickUpFilter`,
`AttributeModifierAuraUpdate.ObjectFilter`, `RadiateFearUpdate.VictimFilter` — are simply followed by
undeclared padding or unlisted members, not by a larger filter.)

### The five entry points a patch needs

| what | VA | convention |
|---|---|---|
| INI parse fn (goes in the field table) | `0x0076392f` | `(ini, instance, store, userdata)` |
| handle ctor | `0x0076406f` | `__thiscall`, `ecx` = `&field`, `ret` |
| handle dtor (release refcount) | `0x007629b0` | `__thiscall`, `ecx` = `&field`, `ret` |
| `bool isDefined()` | `0x00762977` | `__thiscall`, `ecx` = `&field`, `ret` |
| `bool test(Object*, int)` | `0x007640c1` | `__thiscall`, `ecx` = `&field`, `ret 8` |

The ctor writes `-1`, builds the default descriptor and interns it. `isDefined()` returns the `+0x88`
byte of the interned entry — **false for a filter that no INI line ever wrote**, which is what makes
the patch backward-compatible for free.

The canonical call site pattern, lifted from `0x0082d128`:

```
mov  ecx, edi            ; &filter
call 0x762977            ; isDefined?
test al, al
je   .skip               ; unspecified -> don't filter
push 0
push esi                 ; the Object*
mov  ecx, edi
call 0x7640c1            ; test
test al, al
```

The keyword grammar is whatever every other `ObjectFilter` in the game accepts —
`ALL` / `ANY` / `NONE` / relationship tokens / `+KIND` / `-KIND` / template names. Mods would not
learn anything new.

## Relationship tokens, and the wrapper that disables them

`0x007640c1` is only a convenience wrapper. The real evaluator is `0x00763543`
(`__thiscall`, `ret 0xc`) and it takes **three** arguments:

| arg | what | how the wrapper supplies it |
|---|---|---|
| `[ebp+8]` | `ThingTemplate*` — for kind-of and template-name matching | `[obj+4]` |
| `[ebp+0xc]` | the **candidate's** `Player*` | `Object::getControllingPlayer(obj)` |
| `[ebp+0x10]` | the **source** `Player*` — the side the filter is written from | its own 2nd parameter |

The relationship mask lives at `store[i] + 0x84`, and the parse function
(`0x00763a5a`…`0x00763b1d`) sets one bit per token:

| bit | token |
|---|---|
| `0x1` | `ALLIES` |
| `0x2` | `ENEMIES` |
| `0x4` | `NEUTRAL` |
| `0x8` | `SAME_PLAYER` |

The evaluation, at `0x007635e5`:

```
if (mask == 0)                       -> skip the relationship test entirely
if (candidatePlayer == NULL)         -> reject
if (sourcePlayer == NULL)            -> reject                    ; 0x007635f6
rel = sourcePlayer->getRelationship(candidatePlayer->m_defaultTeam)   ; 0x006adbeb
  rel == 0 (ENEMIES) -> accept iff mask & 0x2
  rel == 1 (NEUTRAL) -> accept iff mask & 0x4
  rel == 2 (ALLIES)  -> if (mask & 0x1) accept
                        else accept iff  src->m_playerIndex == cand->m_playerIndex
                                    and  mask & 0x8
```

`m_playerIndex` is `Player+0x54` — already carried in this repo as
[`addresses.PLAYER_INDEX`](../addresses.py). So **the engine already separates "my own units" from
"my ally's units", and has done all along.** `SAME_PLAYER` is a true same-player test, not a
same-faction or same-team approximation.

**The trap:** the wrapper passes its own 2nd parameter straight through as the *source* player, and
every stock call site passes `0`. With a null source player, `0x007635f6` rejects unconditionally
whenever the mask is non-zero. Relationship tokens routed through `0x007640c1` therefore do not
"fall back to permissive" — they **always return false**. That is why they look inert.

Two tokens are unaffected: `EVIL` and `GOOD` set a tri-state at `store[i]+0x90` which is checked at
`0x007635c2` against the candidate player's `PlayerTemplate` (`Player+0x34` → `+0x1bc`). That test
needs no source player and works through the wrapper today.

## The one design decision

`ReplenishAllNearbyHordes` is a loop-break inside the scan, and the scan is gated by
`ReplenishNearbyHorde`. A filter placed at `0x0089ac34` therefore applies to **both** replenish modes.

- **(a) Filter always — recommended.** One keyword, one rule: *this banner only replenishes hordes
  matching the filter.* In single-horde mode it stops the banner picking the wrong nearby horde and
  then breaking out — which is arguably the more common complaint. Zero extra instructions.
- **(b) Filter only when `ReplenishAllNearbyHordes = Yes`.** Two extra instructions in the cave
  (`cmp byte [edi+0x39], 0` / `je .orig`). Matches the literal request, but produces a keyword whose
  effect silently vanishes depending on a *different* keyword — awkward to document and easy to
  mis-report as a bug.

Either way, note the good consequence of filtering at the top of the loop body: a rejected object
jumps to the loop tail **without** reaching the `ReplenishAllNearbyHordes` break at `0x0089ac98`. So
in single-horde mode the scan keeps looking until it finds an object the filter accepts, rather than
burning its one replenish on a rejected candidate. That is the behaviour a modder would expect.

## The recipe

Five writes and one cave section (`sage_patch.utils.allocate_section` / `append_section`, the same
mechanism `.cahfac` uses). New field at `+0x44`, new `sizeof(ModuleData)` = `0x48`.

### 1. Grow the allocation — 1 byte

| VA | file off | from | to |
|---|---|---|---|
| `0x0064de90` | `0x0024de90` | `6a 44` | `6a 48` |

### 2. Construct the new field — repoint one `call`

`0x0064dea5`: `e8 bbc82400` → `call cave_ctor`.

```asm
cave_ctor:
    call 0x89a765            ; original ctor, eax = this
    push eax
    lea  ecx, [eax+0x44]
    call 0x76406f            ; ObjectFilter handle ctor
    pop  eax
    ret                      ; 16 bytes
```

The call site sits inside `newModuleData`'s protected region, and the cave keeps no frame of its own,
so an exception out of `0x76406f` unwinds correctly.

### 3. Release it on destruction — repoint one `call`

`0x0089ae71` (inside the vdtor): `e8 a0f9ffff` → `call cave_dtor`.

```asm
cave_dtor:
    push ecx
    call 0x89a816            ; original ModuleData dtor
    pop  ecx
    add  ecx, 0x44
    jmp  0x7629b0            ; tail-call the handle dtor; returns to the vdtor
                             ; 15 bytes
```

Optional, strictly. `ModuleData` objects are built once per INI object definition and torn down on
shutdown or INI reload, so skipping this leaks one store refcount per template per reload — invisible
in practice. Do it anyway; it is 15 bytes.

### 4. Add the INI keyword — relocate the field table

The table at `0x00c66090` is 12 entries plus a 16-byte NULL terminator, ending at `0x00c66160`.
Unrelated `.rdata` (a `FLT_MAX`, then `ADD_…` / `HEAL_…` strings) starts immediately at `0x00c66160`,
so **it cannot grow in place**.

It is loaded in exactly one instruction, so a copy-and-repoint costs one immediate:

```
0089ae8a  8b 4c2404          mov  ecx, [esp+4]
0089ae8e  6a 00              push 0
0089ae90  68 9060c600        push 0xc66090          ; <- patch this imm32 at 0x0089ae91
0089ae95  e8 3d0ab9ff        call 0x42b8d7          ; MultiIniFieldParse::add
```

Copy the 208 bytes to the cave, append a 14th 16-byte entry and a fresh terminator (224 bytes total),
plus the name string:

```
{ "ReplenishFilter", 0x0076392f, 0, 0x44 }
```

Field lookup is a linear name scan — the stock table is ordered by declaration, not alphabetically
(`IdleSpawnRate`, `MeleeFreeUnitSpawnTime`, `DiedRespawnTime`, …) — so appending at the end is safe
and needs no re-sort. `MultiIniFieldParse::add` (`0x0042b8d7`) just stores the table pointer in a
16-slot array; nothing inspects the entry count.

### 5. Apply the filter — repoint one `call`

`0x0089ac38`: `e8 af31bbff` → `call cave_filter`.

Entry state: `[esp]` = return address `0x0089ac3d`, `[esp+4]` = the `2` pushed at `0x0089ac34`,
`ecx` = the candidate `Object*`, `edi` = the `ModuleData`.

Call the evaluator `0x00763543` directly rather than the wrapper, so relationship tokens work — see
[above](#relationship-tokens-and-the-wrapper-that-disables-them). The source player the evaluator
needs is already in the scan's own frame: `0x0089aba3` computes the banner's controlling player and
stores it at `[ebp-0x20]`, and nothing in the function overwrites that slot.

```asm
cave_filter:
    push ecx                 ; save the candidate
    lea  ecx, [edi+0x44]
    call 0x762977            ; isDefined?
    test al, al
    je   .stock              ; no filter written -> stock behaviour

    push dword [ebp-0x20]    ; arg3 = the BANNER's controlling player
    mov  ecx, [esp+4]        ; ecx = candidate
    call 0x68b678            ; eax = the candidate's controlling player
    push eax                 ; arg2
    mov  ecx, [esp+8]        ; ecx = candidate
    push dword [ecx+4]       ; arg1 = ThingTemplate*
    lea  ecx, [edi+0x44]
    call 0x763543            ; ret 0xc, callee cleans all three
    test al, al
    jne  .stock              ; passes the filter -> stock behaviour

    pop  ecx                 ; drop the saved candidate
    mov  al, 1               ; reject: report "immobile" so the caller's
    ret  4                   ;   `test al,al / jne 0x89acb7` skips this object
.stock:
    pop  ecx                 ; ecx = candidate
    jmp  0x44ddec            ; tail-call Object::isKindOf; its `ret 4` lands at 0x89ac3d
                             ; 57 bytes
```

For option (b), prefix with `cmp byte [edi+0x39], 0` / `je .stock` (5 bytes).

Why this shape works:

- **`ret 4` on the reject path** reproduces `Object::isKindOf`'s callee-cleanup of its one stack arg,
  so the caller's stack is correct on both paths.
- **`al = 1`** reuses the existing `test al,al / jne 0x89acb7`, so no second branch is needed and the
  rejected object skips straight to the loop tail — before any contain lookup, and before the
  `ReplenishAllNearbyHordes` break.
- **`edi` is safe.** It holds the `ModuleData` across the whole loop, and `0x762977`, `0x68b678` and
  `0x763543` are all `__thiscall` functions that preserve `ebx`/`esi`/`edi`/`ebp`.
- **`ecx` is not safe** — `0x762977` starts `mov ecx, [ecx]` — hence the saved copy on the stack.
- **`[ebp-0x20]` is stable.** Every `ebp`-relative write in `0x0089ab8f` was enumerated: the frame
  slots touched are `-0x84`, `-0x28`, `-0x24`, `-0x20`, `-0x1c`, `-0x18`, `-0x14` and `-4`, and only
  `-0x28` is written twice (the vtable slot, retyped at `0x0089ac2c`). `-0x20` is written once, at
  `0x0089abc0`.

This is the one part of the patch coupled to a stack frame rather than to a symbol. A verify pass
should assert the three bytes at `0x0089abc0` are `89 45 e0`; if a future build reorders the frame,
that assertion fails loudly instead of reading a stale slot.

### Cave budget

| block | bytes |
|---|---|
| relocated field table (14 × 16) | 224 |
| `"ReplenishFilter\0"` | 16 |
| `cave_ctor` | 16 |
| `cave_dtor` | 15 |
| `cave_filter` | 57 (62 for option b) |
| **total** | **~328** |

One `0x1000` section, as the other patches allocate.

## What a mod then writes

```ini
Behavior = BannerCarrierUpdate ModuleTag_Banner
  ReplenishNearbyHorde     = Yes
  ReplenishAllNearbyHordes = Yes
  ScanHordeDistance        = 150.0
  ReplenishFilter          = SAME_PLAYER ANY +INFANTRY -CAVALRY
End
```

`SAME_PLAYER` confines the banner to its owner's own hordes; `ALLIES` restores the current
behaviour explicitly (self *and* allies). Omitting the relationship tokens entirely leaves the mask
at zero, which skips the relationship test — so a kind-of-only filter still behaves exactly as
before.

Omit `ReplenishFilter` and the behaviour is bit-for-bit stock: the handle's `+0x88` byte stays zero,
`isDefined()` returns false, and `cave_filter` tail-calls straight into the original `isKindOf`.

## Known rough edges

- **The candidate is filtered, not the horde members.** `ebx` is the object the partition scan
  returned — the horde container (or the unit whose contain interface is queried at `0x0068c866`).
  A filter naming unit templates therefore matches whatever that scan yields, which is not always the
  horde's member template. Worth a line in the modder-facing docs, and worth one in-game check before
  the patch is called done.
- **Ally-scoped, but not player-scoped — and that gap is the point.** The scan's partition filter is
  `PartitionFilterRelationship` (`allow` at `0x0066110a`), built at `0x0089abb9` with mask `2` and
  accept-flag `1` — that is, **relationship 2 = ALLIES only**. It has no same-player narrowing of any
  kind. So today a banner carrier in a 2v2 will happily replenish an *ally's* hordes, and no INI
  keyword can stop it. `SAME_PLAYER` is precisely the distinction the partition scan cannot make,
  which is what makes the relationship tokens worth wiring up rather than redundant.
- **`ALLIES` and `SAME_PLAYER` nest, they do not partition.** Bit `0x1` accepts relationship 2
  outright, before the player-index comparison — so `ALLIES` means *self and allies*, and
  `SAME_PLAYER` means *self only*. "Allies but not me" is not expressible with these tokens.
- **`ENEMIES` and `NEUTRAL` are inert here regardless.** The partition scan has already rejected
  everything that is not an ally before the filter ever runs, so those two bits can only ever narrow
  to nothing. Worth rejecting such a filter at INI-parse time, or at least documenting.
- **Conflicts.** Any other patch that relocates the same field-parse table, hooks `0x0089ac38`, or
  changes `sizeof(BannerCarrierUpdateModuleData)` collides. Nothing in the current `PATCHES` registry
  touches this module.
- **`0x0089aca0` is untouched.** The "horde is already full" branch (vslots `0x178`/`0x174`) still
  runs for filtered-in objects only, which is the intent — but it is not independently gated.
- **Verification.** `0x0089ab8f` has exactly one caller and `0x44` appears once, so a
  `sage-patch verify` pass can assert both plus the five patched byte ranges.

## Appendix — every address this document depends on

| VA | meaning |
|---|---|
| `0x0042b8d7` | `MultiIniFieldParse::add(table, offsetAdjust)` |
| `0x0042dbbd` | ModuleData field-parse registration helper |
| `0x0042f6e0` | `operator new` |
| `0x0044ddec` | `Object::isKindOf(KindOfType)`, `__thiscall`, `ret 4` |
| `0x00444f19` | object-iterator `next` |
| `0x004b1b5a` | `FXList::doFXObj` |
| `0x0064de4c` | `BannerCarrierUpdate` `newModule` |
| `0x0066110a` | `PartitionFilterRelationship::allow` — the scan's own ALLIES gate |
| `0x006adbeb` | `Player::getRelationship(Team*)` → 0 enemies / 1 neutral / 2 allies |
| `0x00763543` | `ObjectFilter` evaluator, `(template, candidatePlayer, sourcePlayer)`, `ret 0xc` |
| `0x007635e5` | the relationship block — mask at `store[i]+0x84` |
| `0x007635f6` | null-source-player rejection — why the wrapper kills relationship tokens |
| `0x0089abc0` | `mov [ebp-0x20], eax` — the banner's controlling player, read by the cave |
| `0x0064de84` | `BannerCarrierUpdate` `newModuleData` |
| `0x0064de90` | `push 0x44` — `sizeof(ModuleData)` |
| `0x0064dea5` | `call` ModuleData ctor |
| `0x00659464` | `ModuleFactory::addModule` registration site |
| `0x0068b678` | `Object::getControllingPlayer` |
| `0x0068c866` | contain-interface lookup via `[obj+0x258]` |
| `0x00762977` | `ObjectFilter::isDefined` |
| `0x0076392f` | `ObjectFilter` INI parse function |
| `0x0076341a` | intern a filter descriptor → index |
| `0x007629b0` | `ObjectFilter` handle dtor |
| `0x0076406f` | `ObjectFilter` handle ctor |
| `0x007640c1` | `ObjectFilter::test(Object*, int)`, `ret 8` |
| `0x0089a765` | `ModuleData` ctor |
| `0x0089a816` | `ModuleData` dtor |
| `0x0089ab8f` | the nearby-horde replenish scan |
| `0x0089ac34` | scan loop body — the filter point |
| `0x0089ac38` | `call Object::isKindOf` — the hook |
| `0x0089ac98` | `ReplenishAllNearbyHordes` loop-break |
| `0x0089ace4` | `BannerCarrierUpdate::update` |
| `0x0089adc7` | `ReplenishNearbyHorde` gate |
| `0x0089ae6e` | `ModuleData` vdtor |
| `0x0089ae71` | `call` ModuleData dtor — the hook |
| `0x0089ae8a` | `buildFieldParse` |
| `0x0089ae91` | field-table imm32 — the repoint |
| `0x00c66090` | field-parse table |
| `0x00c65f18` | `ModuleData` vtable |
| `0x00de78b0` | interned `ObjectFilter` store, `begin` |
| `0x00de78b4` | interned `ObjectFilter` store, `end` |
