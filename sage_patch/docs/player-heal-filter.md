# `PlayerHealSpecialPower` — an `ObjectFilter` on the heal scan

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000` for everything cited here. Read from the repo's own `game.dat`
(11,346,944 bytes, clean).

**Verdict up front: this is the same shape as the banner-carrier filter, and slightly cheaper.** An
`ObjectFilter` field in a `ModuleData` is **four bytes** — an index into one global interned filter
store — not the 148-byte structure it describes. The `ModuleData` being grown here already carries
three of them, inherited from `SpecialAbilityUpdateModuleData`, so the ABI needs no arguing: it can
be read straight off this module's own parse table. The whole feature is three code writes, one
relocated field-parse table and about 96 bytes of cave.

- **Cost:** 4 bytes of allocation + 3 rel32/imm32 repoints + a 96-byte table copy + ~96 bytes of cave.
- **Risk:** low. The filter is skipped unless explicitly specified, by construction.
- **Status:** **built** — see [`patches/player_heal_filter.py`](../patches/player_heal_filter.py).

```
sage-patch apply player-heal-filter --in game.dat.backup --out game.dat
sage-patch apply player-heal-filter --keyword HealTargetFilter --in ... --out ...
sage-patch verify player-heal-filter game.dat
```

## The module as it stands

`ModuleFactory::addModule` registers it at `0x0065b8d9`:

| what | VA |
|---|---|
| name string `"PlayerHealSpecialPower"` | `0x00c0a718` |
| `newModule` | `0x0065232c` (`operator new 0x34`) |
| `newModuleData` | `0x00652364` |
| interface mask | `0x100` (`SpecialPower`) |
| `ModuleData` ctor | `0x008cc459` |
| `ModuleData` vtable | `0x00c75268` — **shared**, see [No destructor](#no-destructor) |
| `buildFieldParse` | `0x008cc282` |
| field-parse table | `0x00c74ec0` |

`newModuleData` is the ordinary three-step shape — allocate, construct, register the parse table:

```
00652370  68 ac000000        push 0xac              ; sizeof(ModuleData)
00652375  e8 66d3ddff        call 0x42f6e0          ; operator new
00652388  e8 cca02700        call 0x8cc459          ; ctor
0065239e  68 82c28c00        push 0x8cc282          ; buildFieldParse
006523a4  e8 14b8ddff        call 0x42dbbd
```

`buildFieldParse` chains: `0x008cc282` calls `SpecialAbilityUpdate`'s own
(`0x0089699b`, which adds `0x00c64db0`) and then adds `0x00c74ec0`. Both tables hang off the same
`MultiIniFieldParse`, and **the inherited one is added first** — which is why the patch refuses a
keyword `SpecialAbilityUpdate` already defines: lookup is a linear scan of the tables in order, so
a duplicate would be parsed into the inherited field instead of being reported.

### `ModuleData` layout — `0xac` bytes, fully packed

`0x00..0x7c` is `SpecialAbilityUpdateModuleData` (35 keywords, table at `0x00c64db0`). This module
adds six, and the ctor at `0x008cc459` initialises exactly the range below:

| offset | field | notes |
|---|---|---|
| `0x7c` | `HealAmount` | `Real`, zeroed |
| `0x80` | `HealAsPercent` | `Bool`, defaults `Yes` |
| `0x84` | `HealRadius` | `Real`, defaults `100` (`0x00bd88d8`) |
| `0x88` | `HealAffects` | `KindOfFlags`, `0x1c` bytes — ctor `0x0064c39a`, then `memset(0, 0x1c)` |
| `0xa4` | `HealFX` | `FXList*`, zeroed |
| `0xa8` | `HealOCL` | `ObjectCreationList*`, zeroed |
| `0xac` | — | **end of structure; where the new handle goes** |

No slack anywhere, and nothing `memcpy`s the structure, so the field can only go on the end and
the one size literal is the one thing that has to move.

## Where the healing actually happens

Three `SpecialPowerModuleInterface` entry points — self, targeted object, targeted location — do
the base `SpecialAbilityUpdate` bookkeeping and then funnel into one worker with a `Coord3D*`:

| thunk | what it passes |
|---|---|
| `0x008cc574` | its second argument |
| `0x008cc594` | `arg + 0x38` (the target's position) |
| `0x008cc5b7` | `Object+0x38` (the caster's own position) |

### The worker, `0x008cc4b4`

```
008cc4c5  mov  edi, [esi+8]           ; the caster Object
008cc4ce  call 0x9325b4               ; bail on a status check
008cc4dd  call 0x68b678               ; getControllingPlayer -> bail if null
008cc4eb  mov  eax, [ModuleData+0xa8] ; HealOCL, if any
008cc500  call 0x5f00ca               ;   -> ObjectCreationList::create
008cc508  mov  [ebp-0x18], 0xc10e20   ; a partition filter, built on the stack
008cc512  fld  [ModuleData+0x84]      ; HealRadius
008cc51f  mov  ecx, [0xde4354]        ; ThePartitionManager
008cc532  call 0xa39340               ; iterate objects in range
008cc54c  call 0x444f19               ; the iterator's next -> eax
008cc547  call 0x8cc37b               ;   -> heal this one
```

The scan itself takes no relationship argument worth filtering on — the screening is all done
per candidate.

### The per-candidate routine, `0x008cc37b`

`__thiscall(ecx = module, Object* candidate)`, `ret 4`. This is the whole of what a modder can
influence today:

```
008cc380  mov  esi, [ebp+8]           ; the candidate
008cc386  test byte [tmpl+0x11b], 8   ; a template flag -> skip
008cc38d  mov  ebx, ecx               ; the module
008cc390  mov  edi, [ebx+4]           ; the ModuleData
008cc399  lea  eax, [edi+0x88]        ; HealAffects
008cc3a2  call 0x70c548               ;   <-- THE HOOK
008cc3a7  test al, al / je            ;   no match -> skip
008cc3af  mov  eax, [ebx+8]           ; the caster
008cc3b5  cmp  [candidate+0x74], [caster+0x74]
008cc3bd  call 0x68d7ab               ;   different -> getRelationship
008cc3c2  cmp  eax, 2                 ;   not ALLIES -> skip
008cc3ce  test byte [tmpl+0x108], 0x80; a health-fraction screen
008cc3f7  mov  ecx, [candidate+0x25c] ; the body module -> skip if none
008cc403  cmp  byte [edi+0x80], 0     ; HealAsPercent -> scale by max health
008cc438  call 0x690532               ; heal
008cc43d  mov  edi, [edi+0xa4]        ; HealFX
008cc44a  call 0x4b1b5a               ;   -> FXList::doFXObj
```

Two things follow, and they are why this patch exists. The only statement a modder can make about
*who* gets healed is a `KINDOF` mask, and **the relationship half is hardcoded**: own units and
allies, always. There is no way to say "heal my own hordes but not my ally's", and no way to name
a specific unit.

`0x0070c548` is a thin `__thiscall(ecx = Object*, KindOfFlags*)`, `ret 4`:

```
0070c548  mov eax, [ecx+4]            ; the candidate's ThingTemplate
0070c54b  mov ecx, [esp+4]            ; the KindOfFlags argument
0070c54f  add eax, 0x108              ; the template's own KindOf
0070c555  call 0x661359               ; intersection test -> al
0070c55a  ret 4
```

Callee cleanup, a `bool` in `al`, and a caller that turns `al = 0` into "skip this candidate" —
which is exactly the shape a filter stub needs.

## The `ObjectFilter` ABI — the reason this is cheap

An `ObjectFilter` field is a four-byte index into one global interned store (stride `0x94`,
refcount at `+0x8c`, "was specified" flag at `+0x88`), not the structure it describes. **This
module's own inherited table proves it**, no reasoning required:

| inherited field | offset | parse fn |
|---|---|---|
| `AttributeModifierAffects` | `0x24` | `0x0076392f` |
| `RequirementsFilterMPSkirmish` | `0x38` | `0x0076392f` |
| `RequirementsFilterStrategic` | `0x3c` | `0x0076392f` |

Four bytes apart, same parse function, all three default-constructed by the base ctor at
`0x00896834`. The five entry points a patch needs:

| VA | what |
|---|---|
| `0x0076392f` | the INI field-parse function — what goes in the table |
| `0x0076406f` | `__thiscall(ecx=&field)` ctor — writes `-1`, interns the default |
| `0x007629b0` | `__thiscall(ecx=&field)` dtor — releases the store refcount |
| `0x00762977` | `__thiscall(ecx=&field) -> bool` — was the keyword written |
| `0x00763543` | `__thiscall(ecx=&field, template, player, source) -> bool`, `ret 0xc` |

The ctor is not optional: `0x0076392f` opens with `cmp dword [store], -1` and releases whatever it
finds if it is anything else, so an unconstructed field hands `operator new`'s leftovers to the
store as an index.

### Relationship tokens, and the wrapper that disables them

`0x007640c1` is a convenience wrapper around `0x00763543` that passes its own second parameter as
the **source** player, and every stock call site passes `0`. With a null source the evaluator
rejects unconditionally at `0x007635f6` whenever the relationship mask is non-zero — so
relationship tokens routed through the wrapper do not degrade to permissive, they *always* return
false. Calling the evaluator directly, with the caster's own player as the third argument, is what
makes `ALLIES` (`0x1`), `ENEMIES` (`0x2`), `NEUTRAL` (`0x4`) and `SAME_PLAYER` (`0x8`) mean
anything.

`SAME_PLAYER` is the distinction this keyword mainly exists for: it is relationship 2 **and** a
matching `Player+0x54`, which is precisely what `0x008cc3b5`'s own test cannot express.

`ENEMIES` and `NEUTRAL` can only narrow to nothing here — the stock relationship test runs
immediately after and rejects everything that is neither the caster's own nor an ally. And bit
`0x1` accepts relationship 2 *before* the player-index comparison, so `ALLIES` means "self and
allies", `SAME_PLAYER` means "self only", and "allies but not me" is not expressible.

### The source player, without a stack frame

The banner-carrier patch reads its source player out of a frame slot, and pays for it with an
anchor on `mov [ebp-0x20], eax`. Here that is unnecessary: the per-candidate routine keeps the
module in `ebx` for its own relationship test, so the cave recomputes the source with
`getControllingPlayer([ebx+8])` (`0x0068b678`) for five more bytes and no frame dependency. It is
never null in practice — the worker already bailed at `0x008cc4e6` if the caster has no player.

What that does depend on is the routine's **register allocation**, so the patch asserts all four
instructions that establish it before writing anything:

| VA | bytes | what it establishes |
|---|---|---|
| `0x008cc380` | `8b 75 08` | `esi` = the candidate |
| `0x008cc38d` | `8b d9` | `ebx` = the module |
| `0x008cc390` | `8b 7b 04` | `edi` = the `ModuleData` |
| `0x008cc39f` | `50 8b ce` | the `HealAffects` call, `ecx` = the candidate |

Nothing the patch writes would catch a mismatch here: the cave would simply dereference whatever
the registers happened to hold.

## The recipe

Four writes and one cave section (`sage_patch.utils.allocate_section`).

### 1. Grow the allocation — 4 bytes

```
00652370  68 ac000000  ->  68 b0000000
```

The field lands at `0xac`, the end of a fully packed structure.

### 2. Construct the new field — repoint one `call`

`0x00652388`'s `call 0x8cc459` goes through a cave shim. The stock ctor is `__thiscall`, takes no
arguments and returns `this` in `eax`, so the shim needs no frame of its own — which also keeps it
transparent to the unwinder, since the call site sits inside `newModuleData`'s protected region.
`eax` is saved across the handle ctor, which is a full SEH frame and does not preserve it.

```asm
cave_ctor:
    call 0x8cc459            ; eax = this
    push eax
    lea  ecx, [eax+0xac]
    call 0x76406f            ; ObjectFilter ctor
    pop  eax
    ret                      ; 19 bytes
```

### 3. Add the INI keyword — relocate the field table

`0x00c74ec0` cannot grow in place: it ends at `0x00c74f30` where a vtable begins. It is loaded by
one instruction — `push 0xc74ec0` at `0x008cc292` — so the patch copies the six stock entries
verbatim into the cave, appends

```
{ "HealFilter", 0x0076392f, 0, 0xac }
{ NULL, NULL, 0, 0 }
```

and repoints the imm32 at `0x008cc293`. Lookup is a linear name scan and the stock table is in
declaration order (`HealAffects` before `HealRadius`), not alphabetical, so appending needs no
re-sort. The copied entries keep their original name pointers into `.rdata`.

### 4. Apply the filter — repoint one `call`

`0x008cc3a2`'s `call 0x70c548` goes through a cave stub that evaluates the filter first. On entry
`[esp]` is the return address, `[esp+4]` is the `&HealAffects` argument the caller already pushed,
and `ecx`/`esi`/`ebx`/`edi` are as tabulated above.

```asm
cave_filter:
    push ecx                 ; save the candidate
    lea  ecx, [edi+0xac]
    call 0x762977            ; isDefined?
    test al, al
    je   .stock_pop          ;   unwritten -> stock behaviour
    mov  ecx, [ebx+8]        ; the caster
    call 0x68b678
    push eax                 ; arg3 = source player
    mov  ecx, [esp+4]        ; the candidate
    call 0x68b678
    push eax                 ; arg2 = the candidate's player
    mov  ecx, [esp+8]
    push dword [ecx+4]       ; arg1 = its ThingTemplate
    lea  ecx, [edi+0xac]
    call 0x763543            ; the evaluator, ret 0xc
    test al, al
    jne  .stock_pop          ;   passes -> stock
    pop  ecx
    xor  al, al              ; reject: "does not match"
    ret  4
.stock_pop:
    pop  ecx
    jmp  0x70c548            ; its ret 4 lands at 0x008cc3a7
                             ; 77 bytes
```

`ecx` cannot be held across the calls (`isDefined` opens with `mov ecx, [ecx]`), so the candidate
lives on the stack; `ebx` and `edi` survive because every callee is `__thiscall`.

The two tests are an **AND** — a candidate must satisfy `HealAffects` *and* the filter — because
the accepting path tail-calls the test it replaced. A reject happens before the heal, before
`HealFX` and before the OCL.

### No destructor

The banner-carrier patch releases its handle's store refcount by repointing the `ModuleData`
destructor call. That is not available here: `0x00c75268` is written by **eight** different
`ModuleData` constructors (`0x008c8969`, `0x008c91fc`, `0x008c9405`, `0x008c98b7`, `0x008cad43`,
`0x008cc46c`, `0x008ccca7`, `0x008ccec1`) — the linker folded eight identical vtables into one —
so its destructor slot is not this class's to hook. Doing it properly would mean giving the class
a private vtable copy, and the cost is out of proportion to what is leaked:

- `ModuleData` objects are built once per INI object definition and live for the process;
- re-parsing the same field releases the previous value *inside* `0x0076392f`, so overrides do not
  accumulate;
- what stays interned is one store entry (148 bytes) per definition that writes the keyword.

### Cave budget

| block | bytes |
|---|---|
| relocated field table (8 × 16) | 128 |
| `"HealFilter\0"`, dword-padded | 12 |
| `cave_ctor` | 19 |
| `cave_filter` | 77 |
| **total** | **236** |

One `0x1000` section (`.hlflt`).

## What a mod then writes

```ini
Behavior = PlayerHealSpecialPower ModuleTag_Heal
  SpecialPowerTemplate = SpecialAbilityHealDefault
  HealAmount           = 50%
  HealRadius           = 300
  HealAffects          = INFANTRY CAVALRY
  HealFilter           = ANY SAME_PLAYER +INFANTRY -HERO
End
```

Omit the keyword and the binary behaves exactly as stock — the field is unspecified, `isDefined`
answers no, and the stub tail-calls the `HealAffects` test it replaced.

## Known rough edges

- **The filter narrows, it never widens.** `HealAffects` still applies. A `HealFilter` that names
  something `HealAffects` excludes heals nothing, which is easy to write by accident.
- **`ENEMIES` / `NEUTRAL` are useless here** (see above) but not rejected: blocking them would
  mean patching the shared `ObjectFilter` parser every other filter keyword in the game uses.
- **Keyword collisions.** The patch refuses a name already in either table — its own six, or the
  35 `SpecialAbilityUpdate` inherits — because the inherited table is searched first and a
  duplicate would silently parse into the wrong field.
- **The `HealOCL` fires regardless.** It is created once at `0x008cc500`, before the scan, so it
  is not per candidate and the filter has nothing to say about it.
- **Conflicts.** Nothing in the current `PATCHES` registry touches `0x00652370`, `0x00652388`,
  `0x008cc293` or `0x008cc3a2`, and the two field tables read here are rewritten by nothing else.
  Verified composing in both orders with `banner-filter` and `commandset-limit`.
- **Verification.** `sage-patch verify player-heal-filter` recomputes the cave from the keyword,
  compares every repointed site, and re-asserts the four register anchors.

## Appendix — every address this document depends on

| VA | meaning |
|---|---|
| `0x0042dbbd` | `ModuleFactory` parse-table registration (`buildFieldParse` callback) |
| `0x0042b8d7` | `MultiIniFieldParse::add(table, offsetAdjust)`, `ret 8` |
| `0x0042f6e0` | `operator new` |
| `0x00444f19` / `0x0044a2a5` | the partition iterator's next / destructor |
| `0x004b1b5a` | `FXList::doFXObj` |
| `0x005f00ca` | `ObjectCreationList::create` |
| `0x0064c39a` | `KindOfFlags` ctor |
| `0x0065232c` / `0x00652364` | `newModule` / `newModuleData` |
| `0x00652370` | `push 0xac` — **the size literal** |
| `0x00652388` | `call 0x8cc459` — **the ctor call** |
| `0x0065b8d9` | `ModuleFactory::addModule` for `PlayerHealSpecialPower` |
| `0x00661359` | `KindOfFlags` intersection test |
| `0x0068b678` | `Object::getControllingPlayer` |
| `0x0068d7ab` | `Object::getRelationship` (`2` = allies) |
| `0x00690532` | the heal itself |
| `0x0070c548` | `__thiscall(Object*, KindOfFlags*) -> bool`, `ret 4` — **the hook target** |
| `0x00762977` | `ObjectFilter::isDefined` |
| `0x0076392f` | the `ObjectFilter` INI parse function |
| `0x00763543` | the three-argument `ObjectFilter` evaluator, `ret 0xc` |
| `0x007635f6` | its null-source rejection |
| `0x0076406f` | `ObjectFilter` ctor |
| `0x007629b0` | `ObjectFilter` dtor (unused here) |
| `0x007640c1` | the two-argument wrapper — **not used**, it starves the evaluator |
| `0x00896834` | `SpecialAbilityUpdateModuleData` ctor |
| `0x0089699b` | `SpecialAbilityUpdate::buildFieldParse` (adds `0x00c64db0`) |
| `0x008cc282` | `PlayerHealSpecialPower::buildFieldParse` (adds `0x00c74ec0`) |
| `0x008cc292` / `0x008cc293` | `push 0xc74ec0` and **its imm32** |
| `0x008cc37b` | the per-candidate heal routine |
| `0x008cc3a2` | `call 0x70c548` — **the filter hook** |
| `0x008cc459` | `PlayerHealSpecialPowerModuleData` ctor |
| `0x008cc46c` | `mov [esi], 0xc75268` — the shared vtable store |
| `0x008cc4b4` | the heal worker (partition scan) |
| `0x008cc574` / `0x008cc594` / `0x008cc5b7` | the three interface entry points |
| `0x009325b4` | the caster status check |
| `0x00a39340` | `PartitionManager::iterateObjectsInRange` |
| `0x00bd88d8` | `100.0f` — `HealRadius`'s default |
| `0x00c0a718` | `"PlayerHealSpecialPower"` |
| `0x00c10e20` | the stack-built partition filter's vtable |
| `0x00c64db0` | `SpecialAbilityUpdate`'s field table (35 entries) |
| `0x00c74ec0` | `PlayerHealSpecialPower`'s field table (6 entries, ends `0x00c74f30`) |
| `0x00c75268` | the shared `ModuleData` vtable |
| `0x00de4354` | `ThePartitionManager` |
