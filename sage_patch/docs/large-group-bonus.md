# `LargeGroupBonusUpdate` — the loose-object count and the upgrade gate

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000` for everything cited here. Read from the repo's own `game.dat`
(11,346,944 bytes, clean).

Two features over one module, and one patch, because they are one structure. Both are opt-in and
both default to bit-for-bit stock.

**`CountLooseObjects` — the filter is not horde-scoped by accident, and it is not scoped by the
filter grammar either.** `HordeMemberFilter` is a perfectly ordinary `ObjectFilter` — the same
4-byte interned handle the banner-carrier and player-heal patches use, parsed by the same
`0x0076392f`. It is horde-only because **it is never evaluated against the object the scan
returned**. It is only ever handed *down* into that object's contain interface, which counts its
own contained members against it. An object with no contain module has nothing to hand the filter
to, so it contributes zero — and the same test runs twice, once in the partition filter and once in
the accumulator, so a loose object is not merely uncounted, it is never even returned by the scan.

**`TriggeredBy` / `ConflictsWith` — the module registers as an `Update` and nothing else**
(interface mask `1`), so it has no `UpgradeMux` subobject and none of the upgrade keywords every
`*Upgrade` module takes. What it does have is a per-`UpdateRate` poll, the owning `Object` live in a
register for the whole of `update`, and a falling edge that already removes the bonus through one
call — so the gate costs a test at the top of `update` and nothing else. See §4.

- **Cost to widen the filter:** 2 rel32/imm32 repoints + 2 short code windows + a 12-byte vtable
  copy + 273 bytes of stubs.
- **Cost of the gate:** 1 five-byte window + 203 bytes of stubs, plus the 41-byte allocation stub
  the `ModuleData` growth below needs.
- **Cost of both:** one field-table relocation (144 → 224 bytes) and `sizeof(ModuleData)`
  `0x30` → `0x158`, because two 36-dword upgrade masks do not fit in three bytes of padding. 849
  bytes of cave, five edited sites.
- **Risk:** low. Every widened or gated path is dead unless the INI writes a new keyword, the gate
  reuses the engine's own mask helpers and its own bonus-removal call, and the allocation growth
  ends at the module's private `newModuleData` thunk — nothing else in the image reads that
  `sizeof`, and the destructor's `operator delete` is the unsized form.
- **Status:** **built** — see [`patches/large_group_bonus.py`](../patches/large_group_bonus.py).
  The loose-object half is **runtime-verified in game**; the upgrade gate is verified statically
  and against the real binary's rebuilt table, and has not yet been run in a match.

```
sage-patch apply large-group-bonus --in game.dat.backup --out game.dat
sage-patch apply large-group-bonus --keyword LooseObjects --in ... --out ...
sage-patch verify large-group-bonus game.dat
```

**This supersedes `large-group-bonus-filter`.** That patch put its flag in the `ModuleData`'s
alignment padding and defaulted it with a constructor shim; this one grows the structure instead,
so the flag moves to `+0x152` and the shim is gone. A binary carrying the older patch is refused by
the anchor at `0x0064d139` rather than patched on top of, and has to be rebuilt from a clean image.

## 1. The module as it stands

`ModuleFactory::addModule` registers it at `0x00658d9a` (name pushed at `0x00658d72`):

| what | VA |
|---|---|
| name string `"LargeGroupBonusUpdate"` | `0x00c0b770` |
| `newModule` | `0x0064d0e0` (`operator new 0x2c`) |
| `newModuleData` | `0x0064d118` (`operator new 0x30`) |
| interface mask | `1` (`Update`) |
| `Module` ctor | `0x00893765` |
| `ModuleData` ctor | `0x00893871` — **one caller**, `0x0064d139` |
| `ModuleData` vtable | `0x00c63ad8` — **not shared**, written only at `0x00893891` |
| `ModuleData` vdtor / dtor | `0x00893b26` / `0x00893b42` |
| `buildFieldParse` | `0x00893754` |
| field-parse table | `0x00c639d8` — **one reference**, the imm32 at `0x0089375b` |
| `update` | `0x008938d9` |

### `ModuleData` layout — `0x30` bytes, with three bytes of padding

The constructor at `0x00893871` initialises exactly this, in this order:

| offset | field | how the ctor writes it |
|---|---|---|
| `0x00` | vtable | `mov [esi], 0xc63ad8` |
| `0x08` | `UpdateRate` | `mov [esi+8], [0xde93d4]` |
| `0x0c` | `HordeMemberFilter` | `lea ecx,[esi+0xc]` → `call 0x76406f` — **the `ObjectFilter` handle ctor** |
| `0x10` | `Count` | `and dword [esi+0x10], 0` |
| `0x14` | `Radius` | `movss [esi+0x14], 0.0` |
| `0x18` | `AlliesOnly` | `mov byte [esi+0x18], 1` — a **byte** store |
| `0x19`–`0x1b` | — | **alignment padding, never written** |
| `0x1c` | `RubOffRadius` | `movss [esi+0x1c], [0xbdbc6c]` (`20.0`) |
| `0x20` | `FlagSubObjectNames` | `lea ecx,[esi+0x20]` → `call 0x478cbe` (12-byte vector) |
| `0x2c` | `AttributeModifier` | `and dword [esi+0x2c], 0` (`AsciiString`) |
| `0x30` | — | end of structure |

The field table confirms the types, and settles the one thing
[`module-reference.md`](module-reference.md) gets wrong — it labels `HordeMemberFilter` a
`KindOfFilter`, but its parse function is `0x0076392f`, the shared `ObjectFilter` one:

```
[0] UpdateRate           parse=0x0073a429  off=0x08
[1] HordeMemberFilter    parse=0x0076392f  off=0x0c     <-- ObjectFilter
[2] Count                parse=0x0042ec5e  off=0x10
[3] Radius               parse=0x0042ed00  off=0x14
[4] RubOffRadius         parse=0x0042ed00  off=0x1c
[5] AlliesOnly           parse=0x0042e558  off=0x18
[6] FlagSubObjectNames   parse=0x0042eed6  off=0x20
[7] AttributeModifier    parse=0x0042ee5e  off=0x2c
```

The destructor agrees: `0x00893b42` releases the handle with
`lea ecx,[esi+0xc]` → `call 0x7629b0`, the `ObjectFilter` handle dtor. So the whole
`ObjectFilter` ABI documented in [`banner-carrier-filter.md`](banner-carrier-filter.md) §"The
`ObjectFilter` ABI" applies here unchanged, and **nothing about the grammar is horde-specific** —
`ALL` / `ANY` / `NONE`, `+KIND` / `-KIND`, template names and relationship tokens all parse today.

## 2. What `update` actually does

`0x008938d9` is an adjustor thunk entered on the module's `Update` subobject, so the registers
that matter are established in the first four instructions and hold for the whole function:

| register | what | established at |
|---|---|---|
| `esi` | the module, biased by `+0x10` | `0x008938e8` `mov esi, ecx` |
| `ebx` | the **owning `Object`** (`[esi-8]`) | `0x008938ea` `mov ebx, [esi-8]` |
| `edi` | the `ModuleData` (`[esi-0xc]`) | `0x00893909` `mov edi, [esi-0xc]` |

`ebx` and `edi` are live and unclobbered from there to `0x00893af2`, which is what makes both hooks
below cheap.

The body is two passes over one partition scan.

### The scan, `0x0089393c`–`0x008939c3`

Four `PartitionFilter`s are built as stack temporaries and passed to
`0x00a39340` (`iterateObjectsInRange`) as a NULL-terminated variadic list:

| slot | vtable | `allow` | what it tests |
|---|---|---|---|
| `[ebp-0x50]` | `0x00c63870` | `0x00660c72` | **the horde gate** — see §3 |
| `[ebp-0x40]` | `0x00c10e14` | `0x00660afe` | `getControllingPlayer(candidate) == the module owner's player` |
| `[ebp-0x28]` | `0x00c10e20` | `0x00660e71` | bit 0 of `Object+0x458` is clear (not dead) |
| `[ebp-0x34]` | `0x00c0f374` | `0x00660e93` | bit 3 of `Object+0x458` agrees between source and candidate |

```
0089393c  mov  eax, [eax+0x40]        ; TheGameLogic frame -> next-update stamp
00893946  lea  eax, [edi+0xc]         ; &HordeMemberFilter
00893949  mov  dword [ebp-0x50], 0xc63870
0089394c  ;                  ^^^^^^^^ the imm32 gate 1 repoints
00893950  mov  [ebp-0x48], eax        ; the wrapper's filter slot, +8
00893953  mov  byte [ebp-0x44], 1     ; the wrapper's polarity byte, +0xc
0089395d  call 0x68b678               ; getControllingPlayer(ebx) -> the same-player filter
008939ab  fld  dword [edi+0x14]       ; Radius
008939c3  call 0xa39340               ; iterate
```

Note `0x0089393f` `and dword [ebp-0x4c], 0` — the wrapper's `+4` slot is zeroed and **never read
by anything**. That free dword is what §6 uses to carry a source player into the filter.

### Pass A — the count, `0x008939db`–`0x00893a12`

```
008939db  mov  ecx, eax               ; the candidate the iterator returned
008939dd  call 0x68c866               ; Object::getContain()
008939e2  test eax, eax
008939e4  je   0x8939f7               ; NO CONTAIN INTERFACE -> contribute nothing
008939e6  mov  edx, [eax]
008939e8  lea  ecx, [edi+0xc]         ; &HordeMemberFilter
008939eb  push ecx
008939ec  mov  ecx, eax
008939ee  call [edx+0x180]            ; -> how many of ITS members match the filter
008939f4  add  [ebp-0x18], eax        ; accumulate
008939f7  lea  ecx, [ebp-0x14]
008939fa  call 0x444f19               ; iterator next
00893a03  ...
00893a0b  mov  eax, [edi+0x10]        ; Count
00893a0e  dec  eax
00893a0f  cmp  [ebp-0x18], eax
00893a12  jb   0x893a42               ; short -> lose the bonus, try the rub-off pass
00893a14  mov  byte [esi+0x19], 1     ; module+0x29
00893a18  mov  byte [esi+0x18], 1     ; module+0x28  -> "this object has the bonus"
```

On a rising edge the `AttributeModifier` at `ModuleData+0x2c` is applied through `0x0068f1a8`; on a
falling edge it is removed through `0x0068f259`.

### Pass B — the rub-off, `0x00893a5d`–`0x00893ac2`

If the count came up short, the same iterator is re-walked looking for a nearby object that
*already* has the bonus: for each candidate, walk its module array at `Object+0x24c`, ask each
module's `+0xc` subobject vslot `0x74` for a `LargeGroupBonus` interface (`0x008a18e0`), ask that
interface vslot `+0x8` whether it currently holds the bonus (`0x008936bb`, which answers yes only
when **both** `module+0x28` and `module+0x29` are set), and compare the squared distance
(`0x0066137c`) against `RubOffRadius²`.

**Pass B is not horde-gated.** It asks objects directly. Only the counting pass is.

## 3. Why the filter is horde-only

Two gates, and they are the same gate.

### Gate 1 — the partition filter, `0x00660c72`

This is the `allow` of the wrapper built at `0x00893946`. Its class appears **nowhere else in the
image**: `0x00660c72` is referenced only from vtable `0x00c63870`, and that vtable is referenced
only from `0x0089361f` (an out-of-line constructor with **zero callers** — the update inlines it)
and from `0x0089394c` (the update's own store).

```
00660c72  push esi
00660c73  mov  esi, ecx               ; the wrapper
00660c75  mov  ecx, [esp+8]           ; the candidate Object*
00660c79  call 0x68c866               ; Object::getContain()
00660c7e  test eax, eax
00660c80  je   0x660c98               ; NO CONTAIN INTERFACE -> "does not match"
00660c82  push [esi+8]                ; &HordeMemberFilter
00660c85  mov  edx, [eax]
00660c87  mov  ecx, eax
00660c89  call [edx+0x180]            ; count its members matching the filter
00660c8f  test eax, eax
00660c91  jbe  0x660c98               ; zero matched -> "does not match"
00660c93  mov  al, [esi+0xc]          ; matched -> the wrapper's polarity byte
00660c96  jmp  0x660ca0
00660c98  xor  eax, eax
00660c9a  cmp  [esi+0xc], al
00660c9d  sete al
00660ca0  pop  esi
00660ca1  ret  4
```

### Gate 2 — the accumulator, `0x008939dd`

Byte for byte the same shape, quoted in §2 above: `getContain`, bail on null, otherwise hand the
filter to `+0x180`.

### `Object::getContain`, `0x0068c866`

```
0068c866  mov  ecx, [ecx+0x258]
0068c86c  test ecx, ecx
0068c86e  jne  0x68c873
0068c870  xor  eax, eax               ; no contain module -> NULL
0068c872  ret
0068c873  mov  eax, [ecx]
0068c875  jmp  [eax+0x7c]
```

`Object+0x258` is one of a run of cached module pointers `Object::Object` NULLs at `0x00699acc`
(the module array itself is the neighbouring `+0x24c`). It is non-NULL only for an object carrying
a contain module — `HordeContain`, `TransportContain`, `OpenContain` and friends. A lone hero, a
single unit that is not in a horde, a structure, a siege engine: all of them keep it NULL.

**So `HordeMemberFilter` is never evaluated against the object the scan returned.** It is passed as
an argument, one level down, to a method on the *container*. Its whole job is to say "which of your
occupants do I count" — and the question is only ever asked of things that have occupants. That is
the entire mechanism, and it is why no filter expression, however written, can make a
`LargeGroupBonusUpdate` notice a unit that is not inside a horde.

### On `+0x180` itself

Contain-interface vslot `+0x180` is `__thiscall(ecx = interface, const ObjectFilter *) -> Int`,
`ret 4`. Its contract is fixed by its call sites rather than by a recovered implementation: two of
them pass **NULL** and use the result as a population count — `0x007a0204`, where it is compared
against `+0x17c`'s answer, and `0x008c6ebc`, where it is divided into `[esi+0xd0]` — and the two
here pass a filter and use the result as "how many of them match". Chasing the concrete
implementation through `HordeContain`'s multiply-inherited module (nine vtables, written at
`0x00869bde`–`0x00869c15`) did not resolve cleanly and **is not needed**: for a container-less
object both gates fail *before* the call is made, so the widening below never has to reason about
what `+0x180` would have done.

## 4. Why there is no upgrade gate — and what one costs

`ModuleFactory::addModule` registers this module with interface mask `1`. That is `Update` and
nothing else: no `UpgradeMux` subobject at `module+0x10`, no `getUpgrade` vslot for
`0x00693752` to find, so none of the machinery
[`commandset-button-upgrade.md`](commandset-button-upgrade.md) §3 describes reaches it.
`TriggeredBy` here is not disabled, it was never wired.

What the module does give a gate, for free:

1. **The registers are already right.** `ebx` is the owning `Object` from `0x008938ea` and `edi`
   the `ModuleData` from `0x00893909`, both live to `0x00893af2` (§2). An upgrade is held either by
   the object (`Object+0x28c`) or by its controlling player (`Player+0x14c`), and both are reached
   from `ebx` alone.
2. **It already polls.** `update` returns `[edi+8]` (`UpdateRate`) or `1`, never `0x3fffffff`,
   unless its object is dead — so a mask that becomes satisfied mid-game is noticed on the next
   poll with no arming hook. This is the cost `lifetime-extend-upgrade` §2 had to pay a per-frame
   wake-up for, and here it is already paid.
3. **The falling edge is already written.** `0x00893a1c` compares `module+0x28` against the value
   saved at `0x0089390c` and, when it has gone from set to clear, calls `0x0068f259` with `ecx` =
   the object and `&ModuleData.AttributeModifier` pushed. A gate that switches the module off can
   make exactly that call rather than reinventing the bookkeeping.

And the one thing it does not give: **anywhere to put the masks.** `UpgradeMaskType` is 36 dwords
([`upgrade-mask-limit.md`](upgrade-mask-limit.md)), so `TriggeredBy` and `ConflictsWith` are `0x120`
bytes between them against three bytes of padding at `+0x19`. The structure has to grow, which is
affordable only because `newModuleData` (`0x0064d118`) is this module's own thunk and its
`push 0x30` is the sole `sizeof` literal — the same shape `lifetime-extend-upgrade` grew
`LifetimeUpdate` with.

### The gate is the mux's *condition*, not its execute

`UpgradeMux` is a one-shot: it latches at `module+0x14` once its conditions are met and never fires
again ([`commandset-button-upgrade.md`](commandset-button-upgrade.md) §4). That model does not fit
a module whose whole job is to recompute a state on a timer, so this gate takes only the condition
half — `TriggeredBy`, `ConflictsWith` and the two `RequiresAll…` selectors — and re-evaluates it on
every poll. There is no `StartsActive`, no `Permanent`, no `CustomAnimAndDuration`, and no latch: an
upgrade granted turns the module on, an upgrade stripped turns it back off.

The nearest thing in stock INI is `AttributeModifierAuraUpdate`'s condition, not an upgrade
module's — which is the right neighbour for a module that applies an `AttributeModifier` by
proximity.

## 5. Two other things this module does not do

Both were found in passing, both will be the next thing a modder hits, and neither is fixed by
either half of this patch.

- **`AlliesOnly` is parsed and never read.** `ModuleData+0x18` appears in the field table, gets its
  `Yes` default from the constructor, and is read by nothing. The scan's ownership rule is instead
  hardcoded in the second partition filter: `0x00660afe` is a strict
  `getControllingPlayer(candidate) == getControllingPlayer(owner)` test, with no `AlliesOnly`
  branch anywhere near it. So the keyword's `No` setting does nothing, and **a widened filter still
  only ever sees the module owner's own objects.** The fix has the same shape as gate 1 — the
  vtable is stored by the imm32 at `0x0089396a` — but the vtable itself (`0x00c10e14`) is shared
  with twelve other sites, so it must be repointed at the store, never patched in place.
- **`FlagSubObjectNames` can only ever be hidden, never shown.** The sub-object show/hide routine
  is `0x00893810`, and it has exactly one caller: `0x0089386b`, which passes a hardcoded `push 0`.
  The visibility state it would be driven from is `module+0x2a`, and that byte is written **once in
  the whole image** — `mov byte [esi+0x2a], al` at `0x00893791`, in the constructor, with `al` zero
  — so the accessor at `0x008267cb` (the bonus interface's vslot `+0x4`, which has no direct
  callers at all) always answers false.

## 6. The recipe

Five keywords. One is renameable with `--keyword`:

- `CountLooseObjects` (a `Bool`, default `No`). When it is `Yes`, both gates of §3 additionally
  accept an object with **no contain interface** whose `ThingTemplate` the `HordeMemberFilter`
  itself matches, and count it as one.

The other four are the engine's own spellings, taken row for row from the `UpgradeMuxData` base
table at `0x00c76ad8`, and are deliberately **not** renameable:

- `TriggeredBy`, `ConflictsWith` (upgrade masks, empty by default) and `RequiresAllTriggers`,
  `RequiresAllConflictingTriggers` (`Bool`, default `No`). With no `TriggeredBy` nothing is
  required; with no `ConflictsWith` nothing blocks.

**`isDefined` gates the widened filter path as well as the flag.** A module that never wrote
`HordeMemberFilter` still hands the default handle to the contain interface today, and what that
means for a *container* is the contain module's business; on the loose-object side there is no such
precedent, and "count every object within `Radius`" is not a default worth inferring from silence.
So both filter stubs ask `0x00762977` first and contribute nothing when the keyword was never
written — `CountLooseObjects` without a `HordeMemberFilter` is inert rather than sweeping. The
upgrade gate needs no companion test: an undeclared mask is all-zero and `0x00444dce` answering
false is what makes each half optional.

Five writes and one cave section (`sage_patch.utils.allocate_section`).

### 6.1 Grow the `ModuleData` — one window, no constructor shim

Two masks and three bools do not fit in the three bytes of padding at `+0x19`, so the structure
grows and every new field lands past the stock `0x30`:

| offset | field |
|---|---|
| `0x00`–`0x2f` | the stock structure of §1, untouched — including the padding at `0x19` |
| `0x30` | `TriggeredBy` — 36 dwords |
| `0xc0` | `ConflictsWith` — 36 dwords |
| `0x150` | `RequiresAllTriggers` |
| `0x151` | `RequiresAllConflictingTriggers` |
| `0x152` | `CountLooseObjects` |
| `0x158` | end of structure |

`newModuleData` is this module's own thunk and its `push 0x30` is the sole `sizeof` literal:

```
0064d122  51                push ecx
0064d123  56                push esi
0064d124  6a30              push 0x30
0064d126  e8b525deff        call 0x42f6e0            ; operator new
0064d12b  59                pop  ecx                 ; <- the cave rejoins here
...
0064d139  e833672400        call 0x893871            ; the ModuleData ctor -- NOT touched
```

Nine bytes become `jmp <cave>` and four `nop`s:

```asm
cave_alloc:
    push ecx                     ; both displaced pushes, in order
    push esi
    push 0x158
    call 0x42f6e0                ; cdecl: the argument stays for the caller's `pop ecx`
    test eax, eax
    je   .done                   ; the caller tests for null too
    push eax
    lea  edx, [eax+0x30]
    mov  ecx, 74
    xor  eax, eax
.zero:
    mov  [edx], eax
    add  edx, 4
    dec  ecx
    jne  .zero
    pop  eax
.done:
    jmp  0x64d12b                ; 41 bytes
```

**The zeroing is the defaults.** `operator new` does not zero; `parseUpgradeMask` memsets the mask
it is handed, so a block that writes a mask keyword would be fine either way, but a block that
writes none never reaches a parser at all. Zeroing here is also what removes the constructor shim
the previous version of this patch needed for its one byte: the stock ctor writes nothing past
`+0x2c`, so `0x0064d139` keeps calling the engine's own constructor and the patch hooks one site
fewer than it used to.

`sizeof` is read nowhere else, and `0x00893b36` deletes with the **unsized** `operator delete`
(`push esi; call 0x42f6a0`), so the growth ends here. The `ModuleData` is template-side parse data
and is not `Xfer`'d, so savegames are unaffected by its size.

### 6.2 Add the keywords — relocate the field table

`0x00c639d8` is 8 entries plus a 16-byte NULL terminator, ending at `0x00c63a68` where an
unrelated `.rdata` string (`E:\Builds\BFME2X\Code\...`) begins, so **it cannot grow in place**. It
is named by exactly one instruction, which makes this the cheapest table relocation in the package
alongside `science-prereqs`:

```
00893754  mov  ecx, [esp+4]
00893758  push 0
0089375a  push 0xc639d8              ; <- the imm32 at 0x0089375b
0089375f  call 0x42b8d7              ; MultiIniFieldParse::add
```

Copy the 144 bytes verbatim, append

```
{ "CountLooseObjects",              0x0042e558, 0, 0x152 }   ; the Bool parser AlliesOnly uses
{ "TriggeredBy",                    0x0066f603, 0, 0x030 }   ; INI::parseUpgradeMask
{ "ConflictsWith",                  0x0066f603, 0, 0x0c0 }
{ "RequiresAllTriggers",            0x0042e558, 0, 0x150 }
{ "RequiresAllConflictingTriggers", 0x0042e558, 0, 0x151 }
{ NULL, NULL, 0, 0 }
```

and repoint. The four upgrade rows are the `UpgradeMuxData` rows with this module's offsets
substituted: the parse function takes the offset from the row it is called for, which is what makes
rows portable between blocks at all. Lookup is a linear name scan and the stock table is in
declaration order, not alphabetical, so appending needs no re-sort. This module inherits no second
table, so there is no duplicate-keyword hazard of the kind `player-heal-filter` has to guard
against.

### 6.3 The upgrade gate

`0x0089390f` is a lone five-byte instruction — `mov eax, [TheGameLogic]` — with the module in
`esi`, the owner in `ebx`, the `ModuleData` in `edi` and the frame in `ebp`, and it is the last
instruction before `0x00893914` consumes the flags set at `0x00893901`. It becomes `jmp <cave>`
with no padding at all:

```asm
cave_gate:
    pushfd                       ; 0x00893914 branches on flags set before the window
    push ecx                     ; the ThingTemplate, read again at 0x0089391a
    lea  ecx, [edi+0x30]
    call 0x444dce                ; TriggeredBy declared at all?
    test al, al
    je   .conflicts
    lea  eax, [edi+0x30]
    movzx edx, byte [edi+0x150]  ; RequiresAllTriggers
    call held
    test al, al
    je   .inactive               ; required and not held
.conflicts:
    lea  ecx, [edi+0xc0]
    call 0x444dce
    test al, al
    je   .active
    lea  eax, [edi+0xc0]
    movzx edx, byte [edi+0x151]
    call held
    test al, al
    jne  .inactive               ; a conflict is held
.active:
    pop  ecx
    popfd
    mov  eax, [0xde412c]         ; the displaced instruction
    jmp  0x893914
.inactive:
    pop  ecx
    popfd
    cmp  byte [esi+0x18], 0
    je   .quiet                  ; never had the bonus -> nothing to undo
    mov  byte [esi+0x18], 0
    mov  byte [esi+0x19], 0
    lea  eax, [edi+0x2c]         ; &AttributeModifier
    push eax
    mov  ecx, ebx
    call 0x68f259                ; the stock falling edge's own removal, ret 4
.quiet:
    mov  byte [ebp-0xd], 0       ; the tail's "UpdateRate or 1" selector
    jmp  0x893af2                ; 203 bytes with `held`
```

with the two-mask test the engine writes at `0x008b901a`, one call deep so both sites share it:

```asm
held:                            ; eax = &mask, dl = the RequiresAll flag, ebx = the Object
    mov  ecx, 0x8097d6           ; testForAny
    test dl, dl
    je   .picked
    mov  ecx, 0x6aacb3           ; ... or testForAll
.picked:
    push ecx                     ; the test, and
    push eax                     ; the mask, both parked across two __thiscall calls
    push eax
    lea  ecx, [ebx+0x28c]        ; the object's completed mask
    call dword [esp+8]           ; ret 4
    test al, al
    jne  .yes
    mov  ecx, ebx
    call 0x68b678                ; getControllingPlayer
    test eax, eax
    je   .no                     ; unowned -> its own mask alone
    push dword [esp]
    lea  ecx, [eax+0x14c]        ; the player's completed mask
    call dword [esp+8]
    test al, al
    jne  .yes
.no:
    xor  al, al
    jmp  .done
.yes:
    mov  al, 1
.done:
    add  esp, 8
    ret
```

**Why the top of `update` and not the count comparison.** Forcing the count short at `0x00893a0b`
would let the stock code lose the bonus for us, and it is wrong twice over: pass B, the rub-off at
`0x00893a5d`, is not gated by the count and would hand the bonus straight back from a neighbour
that has it; and the partition scan at `0x00a39340` would still run every `UpdateRate` frames for a
module that is switched off. Gating at the top skips the scan entirely, so an inactive module costs
two `any()` calls per frame and nothing else — and jumping to `0x00893af2` is legal precisely
because that point is past the iterator destructor and the four stack-filter vtable resets, neither
of which this path created. The stock `ebx == NULL` early-out at `0x008938f1` leaves the same frame
state one step further on, which is the evidence that `[ebp-4]` needs no fixing up.

### 6.4 Gate 1 of the loose-object count — replace the partition filter's vtable, conditionally

Ten bytes at `0x00893946` (`lea eax,[edi+0xc]` + `mov dword [ebp-0x50], 0xc63870`) become a 5-byte
`call` and five `nop`s. The shim owes the caller both of their effects — the wrapper's vtable slot
written, and `eax` holding `&HordeMemberFilter` for the `mov [ebp-0x48], eax` that follows the
window — and then, only on the widened path, swaps in a cave-built copy of the wrapper vtable whose
`allow` is the widened one and parks the owning `Object` in the wrapper's free `+4` slot:

```asm
cave_setup:                      ; ebp = update's frame, edi = ModuleData, ebx = the owner
    mov  dword [ebp-0x50], 0xc63870
    cmp  byte [edi+0x152], 0
    je   .done                   ; flag clear -> stock
    lea  ecx, [edi+0xc]
    call 0x762977                ; isDefined?
    test al, al
    je   .done                   ; no filter written -> stock
    mov  dword [ebp-0x50], <cave vtable>
    mov  [ebp-0x4c], ebx         ; the wrapper's +4: the source Object
.done:
    lea  eax, [edi+0xc]          ; what the window left in eax
    ret                          ; 50 bytes
```

Choosing the vtable rather than editing `0x00660c72` in place is what keeps the stock path
byte-identical, and `[ebp-0x4c]` is safe because `0x0089393f` zeroes it and nothing reads it.
`eax`/`ecx`/`edx` are dead at the window on every incoming path and `isDefined` is `__thiscall`, so
nothing has to be saved.

The cave vtable is a 12-byte copy of `0x00c63870` — the class has exactly three slots, since
`0x00c6387c` is where the module's `LargeGroupBonus` interface vtable begins — with slot `+4`
pointing at:

```asm
new_allow:                       ; __thiscall(ecx = wrapper, Object *cand) -> bool, ret 4
    push ebx
    push esi
    mov  esi, ecx
    mov  ebx, [esp+0xc]          ; the candidate
    mov  ecx, ebx
    call 0x68c866                ; getContain
    test eax, eax
    je   .loose
    push dword [esi+8]
    mov  edx, [eax]
    mov  ecx, eax
    call dword [edx+0x180]
    test eax, eax
    ja   .match
    jmp  .nomatch
.loose:
    mov  ecx, [esi+8]            ; &HordeMemberFilter
    call 0x762977                ; isDefined?
    test al, al
    je   .nomatch
    mov  ecx, [esi+4]            ; the owning Object, stashed by cave_setup
    call 0x68b678                ; -> the source Player
    push eax                     ; arg3
    mov  ecx, ebx
    call 0x68b678                ; -> the candidate's Player
    push eax                     ; arg2
    push dword [ebx+4]           ; arg1 = its ThingTemplate*
    mov  ecx, [esi+8]
    call 0x763543                ; the three-argument evaluator, ret 0xc
    test al, al
    je   .nomatch
.match:
    mov  al, [esi+0xc]
    pop  esi
    pop  ebx
    ret  4
.nomatch:
    xor  eax, eax
    cmp  [esi+0xc], al
    sete al
    pop  esi
    pop  ebx
    ret  4                       ; 122 bytes
```

Calling `0x00763543` directly rather than the two-argument wrapper `0x007640c1` is the same
decision both existing filter patches made, and for the same reason: the wrapper passes a null
source player and `0x007635f6` then rejects unconditionally whenever the relationship mask is
non-zero, so relationship tokens routed through it always return false rather than degrading to
permissive. With the owner's player in hand, `SAME_PLAYER` / `ALLIES` mean what they say — though
see §5 on the same-player filter that runs alongside and will veto anything else regardless.

### 6.5 Gate 2 — the accumulator

`0x008939db`–`0x008939f6` is 28 bytes and self-contained: the only inbound branch is
`0x00893a01`'s `jne 0x8939db` to the top, and the internal `je 0x8939f7` targets the loop tail just
past the end, which the replacement reaches by falling through. It becomes

```
008939db  mov  ecx, eax
008939dd  call cave_count
008939e2  add  [ebp-0x18], eax
008939e5  nop x 18
```

with

```asm
cave_count:                      ; ecx = candidate; ebx/edi as established in §2
    push ecx                     ; save the candidate
    call 0x68c866                ; ecx is still the candidate
    test eax, eax
    je   .loose
    lea  ecx, [edi+0xc]
    push ecx
    mov  edx, [eax]
    mov  ecx, eax
    call dword [edx+0x180]       ; ret 4
    pop  ecx
    ret
.loose:
    cmp  byte [edi+0x152], 0
    je   .zero
    lea  ecx, [edi+0xc]
    call 0x762977                ; isDefined?
    test al, al
    je   .zero
    mov  ecx, ebx                ; the owning Object
    call 0x68b678
    push eax                     ; arg3 = the source player
    mov  ecx, [esp+4]            ; the candidate
    call 0x68b678
    push eax                     ; arg2
    mov  ecx, [esp+8]            ; the candidate
    push dword [ecx+4]           ; arg1 = its ThingTemplate*
    lea  ecx, [edi+0xc]
    call 0x763543                ; ret 0xc
    movzx eax, al                ; a match contributes exactly 1
    pop  ecx
    ret
.zero:
    xor  eax, eax
    pop  ecx
    ret                          ; 101 bytes
```

The candidate lives on the stack rather than in a register because every callee here is
`__thiscall`: only `ebx`/`esi`/`edi`/`ebp` survive a call, and all four are already spoken for — the
stub reads `ebx` as the owning `Object` and `edi` as the `ModuleData`, and clobbers only
`eax`/`ecx`/`edx`, which the stock window clobbered too.

### 6.6 Cave budget

| block | bytes |
|---|---|
| the five keyword strings, dword-padded | 96 |
| copied wrapper vtable (3 × 4) | 12 |
| relocated field table (14 × 16) | 224 |
| `cave_alloc` | 41 |
| `cave_gate` + `held` | 203 |
| `cave_setup` | 50 |
| `new_allow` | 122 |
| `cave_count` | 101 |
| **total** | **849** |

One `0x1000` section (`.lgbupd`), as every other patch here allocates. The renameable keyword is
first so `detect` can read it straight off the section base; the four fixed names follow it.

## 7. What a mod then writes

```ini
Behavior = LargeGroupBonusUpdate ModuleTag_Bonus
  UpdateRate         = 500
  HordeMemberFilter  = ANY +INFANTRY -HERO
  CountLooseObjects  = Yes
  Count              = 20
  Radius             = 150.0
  RubOffRadius       = 40.0
  AttributeModifier  = HordeBonusArmor

  TriggeredBy                    = Upgrade_ShieldDrill
  ConflictsWith                  = Upgrade_Disbanded
  RequiresAllTriggers            = No
  RequiresAllConflictingTriggers = No
End
```

Every one of the five is absent from every mod shipping today, and absent means stock:
`cave_setup` installs the stock vtable, `cave_count` returns zero for a container-less object,
`cave_gate` finds both masks empty and resumes. Omitting `HordeMemberFilter` disables the widened
path even with the flag set — see the `isDefined` note in §6.

The gate switches **this module** on and off. It does not filter which objects are counted: the
upgrade is tested on the module's own object, so `TriggeredBy` here means "this unit contributes
and receives a large-group bonus only once the research is bought", not "only count neighbours who
have it".

## 8. Known rough edges

- **The two filter gates must move together.** Widening only the accumulator achieves nothing,
  because the partition filter has already removed loose objects from the iteration. Widening only
  the partition filter achieves nothing either, because the accumulator would then skip what the
  scan handed it. Any build that ships one without the other is a no-op, not a half-feature.
- **The scan is still same-player.** See §5. A `CountLooseObjects` build lets a `LargeGroupBonus`
  count its owner's loose units; it does not let it count an ally's or an enemy's, and no
  `HordeMemberFilter` relationship token can override the hardcoded filter at `0x00660afe`.
  Honouring `AlliesOnly` is a separate, adjacent patch.
- **One filter, two questions.** Reusing `HordeMemberFilter` means the same expression decides both
  "which members inside a horde count" and "which loose objects count". A second `ObjectFilter`
  keyword is now cheap — the structure already grows, so it costs four bytes of it, a handle ctor
  and a release in the destructor — and the destructor **is** available: `0x00c63ad8` is written
  from exactly one site, so its dtor slot belongs to this class alone and the `call 0x893b42` at
  `0x00893b29` can be repointed.
- **Loose objects count as 1.** A container contributes its matching member count; a loose object
  contributes one. That is the only sensible reading, but it does mean a `Count` tuned against
  hordes will be reached by far fewer loose objects than the number of models on screen suggests.
- **Rub-off already ignores hordes**, so it needs no change — but that also means a loose object
  could always *receive* the bonus by proximity, and only ever failed to *produce* it. Mods that
  worked around the limitation with a rub-off donor will now double-count.
- **A gated-off module cannot receive the bonus either.** The gate returns before pass B, so a
  module whose `TriggeredBy` is unmet neither produces nor receives — which is the point, but it
  does mean the gate is stronger than "stop counting".
- **`RequiresAllTriggers` does not span the two mask owners.** An upgrade is held either by the
  object or by its player, and the test asks each mask separately, exactly as `UpgradeMux` does at
  `0x008b901a`. So a `RequiresAllTriggers` set split across an object-scoped and a player-scoped
  upgrade satisfies neither call and reads as unmet. Copying the stock behaviour is deliberate; it
  is still a trap worth knowing.
- **The gate re-evaluates, it does not latch.** Strip the upgrade and the bonus goes away on the
  next poll, through the same removal call the count-came-up-short path uses. Mods wanting "once
  earned, kept" want a different feature (`Permanent` on a real `UpgradeMux`), not this one.
- **This changes the simulation.** The bonus is applied through `AttributeModifier` on the logic
  side, so **every peer must run the same patched binary** and replays do not cross — the same rule
  as `production-condition` and `spawn-union`. And, as with `terrain-resource-exp` and
  `queue-ignore-cp`, the new keywords are an INI **parse error** on a stock build, not a warning.
- **It supersedes `large-group-bonus-filter`.** The flag moved from `+0x19` to `+0x152` and the
  constructor shim is gone, so a binary carrying that patch cannot be upgraded in place: the anchor
  at `0x0064d139` refuses it, and the build has to be redone from a clean image. Manifests naming
  `large-group-bonus-filter` need the new name.
- **Conflicts.** Nothing else in the current `PATCHES` registry touches `0x0064d122`, `0x0089375b`,
  `0x0089390f`, `0x00893946`, `0x008939db` or the tables at `0x00c639d8` / `0x00c63870`. The
  nearest neighbour is `banner-filter`, which lives in `0x0089a7xx`–`0x0089aexx`. Verified composing
  in both orders with `banner-filter`, `player-heal-filter`, `commandset-limit`, `production-split`
  and `terrain-resource-exp`.
- **Verification.** `sage-patch verify large-group-bonus` recomputes the whole cave from the
  keyword, compares every rewritten site, re-reads the rebuilt table's thirteen rows and re-asserts
  the twenty-three build anchors — including the three that establish `ebx`, `edi` and `esi`, and the
  five engine helpers the cave calls, none of which the patch writes anything that would otherwise
  catch.

## 9. Appendix — every address this document depends on

| VA | meaning |
|---|---|
| `0x0042b8d7` | `MultiIniFieldParse::add(table, offsetAdjust)`, `ret 8` |
| `0x0042dbbd` | `ModuleFactory` parse-table registration |
| `0x0042e558` | the `Bool` INI parse function — `AlliesOnly`'s, and three of the new rows' |
| `0x0042f6a0` / `0x0042f6e0` | `operator delete` (unsized) / `operator new` |
| `0x00444dce` | `UpgradeMaskType::any()` — "was this mask keyword ever written" |
| `0x00444f19` | object-iterator `next` |
| `0x0044a2a5` | object-iterator destructor |
| `0x00478cbe` | `AsciiStringList` (vector) ctor — `FlagSubObjectNames` |
| `0x0064d0e0` / `0x0064d118` | `newModule` / `newModuleData` |
| `0x0064d122` | the nine-byte allocation window — **hook 6.1** |
| `0x0064d124` | `push 0x30` — the sole `sizeof(ModuleData)` literal, inside that window |
| `0x0064d12b` | `pop ecx` — where the allocation cave rejoins |
| `0x0064d139` | `call 0x893871` — the ctor call, **not** hooked, anchored |
| `0x00658d72` | the name push inside `ModuleFactory::addModule` |
| `0x00660afe` | the same-player partition filter's `allow` — **why `AlliesOnly` is inert** |
| `0x00660c72` | the horde-gate partition filter's `allow` — **filter gate 1** |
| `0x00660c79` | its `call Object::getContain` |
| `0x00660e71` / `0x00660e93` | the alive / same-status partition filters' `allow` |
| `0x0066137c` | squared distance, used by the rub-off pass |
| `0x0066f603` | `INI::parseUpgradeMask` — the parser the two mask rows name |
| `0x0068b678` | `Object::getControllingPlayer` — NULL for an unowned object |
| `0x0068c866` | `Object::getContain` via `Object+0x258` — **the whole filter mechanism** |
| `0x0068f1a8` / `0x0068f259` | `AttributeModifier` apply / remove — the gate uses the second |
| `0x00699acc` | `Object::Object` NULLing `Object+0x258` |
| `0x006aacb3` / `0x008097d6` | `testForAll` / `testForAny` on an upgrade mask, both `ret 4` |
| `0x0070e013` | `Object::getDrawable`, used by the flag routine |
| `0x0073a429` | the `Duration` INI parse function (`UpdateRate`) |
| `0x00762977` | `ObjectFilter::isDefined` |
| `0x0076392f` | the `ObjectFilter` INI parse function — **`HordeMemberFilter`'s** |
| `0x00763543` | the three-argument `ObjectFilter` evaluator, `ret 0xc` |
| `0x0076406f` / `0x007629b0` | `ObjectFilter` handle ctor / dtor |
| `0x007640c1` | the two-argument wrapper — **not used**, it starves the evaluator |
| `0x008267cb` | the bonus interface's `+0x4` — reads `module+0x2a`, which is always 0 |
| `0x00850c60` | called from the module's `Xfer` |
| `0x00893630` | the free-function `LargeGroupBonus` interface lookup (inlined into `update`) |
| `0x00893754` | `buildFieldParse` |
| `0x0089375b` | the field-table imm32 — **the repoint, 6.2** |
| `0x00893765` | `Module` ctor |
| `0x00893791` | `mov byte [esi+0x2a], al` — the only write to the flag-visibility state |
| `0x00893810` | the `FlagSubObjectNames` show/hide routine (one caller, always `0`) |
| `0x00893871` | `ModuleData` ctor |
| `0x00893891` | `mov [esi], 0xc63ad8` — the sole `ModuleData` vtable store |
| `0x008938b8` | `mov byte [esi+0x18], 1` — `AlliesOnly`'s default |
| `0x008938d9` | `LargeGroupBonusUpdate::update` |
| `0x008938f1` | the `ebx == NULL` early-out — why the tail is re-entrable |
| `0x00893901` | the KindOf test whose flags the gate carries across itself |
| `0x0089390f` | the five-byte gate window — **hook 6.3** |
| `0x00893914` | the branch that consumes those flags — where the active path resumes |
| `0x00893932` | `mov byte [ebp-0xd], 0` — the sleep selector |
| `0x0089393f` | `and dword [ebp-0x4c], 0` — the wrapper's unread `+4` slot |
| `0x00893946` | `lea eax,[edi+0xc]` — **the 10-byte window, filter gate 1** |
| `0x0089394c` | the wrapper-vtable imm32 |
| `0x0089396a` | the same-player filter's vtable imm32 (for the `AlliesOnly` follow-up) |
| `0x008939db` | **the 28-byte window, filter gate 2** |
| `0x008939dd` | its `call Object::getContain` |
| `0x008939ee` | `call [edx+0x180]` — count matching contained members |
| `0x00893a0b` | `mov eax, [edi+0x10]` — `Count`, compared as `count >= Count-1` |
| `0x00893a14` / `0x00893a18` | the two bonus flag bytes, `module+0x29` / `+0x28` |
| `0x00893a1c` | the bonus edge compare |
| `0x00893a5d` | pass B, the rub-off — why the gate is not at the count |
| `0x00893acb` | the stock falling edge's `call 0x68f259` |
| `0x00893af2` | the re-entrable tail — where the inactive path lands |
| `0x00893b09` | `cmp byte [ebp-0xd], 0` — the sleep the tail returns |
| `0x008936bb` | the bonus interface's `+0x8` — "do I hold the bonus" |
| `0x00893b26` / `0x00893b42` | `ModuleData` vdtor / dtor |
| `0x00893b36` | the dtor's unsized `operator delete` — why the growth needs no matching edit |
| `0x00893b75` | the dtor's `ObjectFilter` release |
| `0x008a18e0` | behavior-module vslot `0x74` → the `LargeGroupBonus` interface |
| `0x008b901a` | `UpgradeMux`'s two-mask idiom, which `held` reproduces |
| `0x00a39340` | `PartitionManager::iterateObjectsInRange` |
| `0x00a394c0` | the `PartitionFilter` upcast thunk |
| `0x00bdbc6c` | `20.0f` — `RubOffRadius`'s default |
| `0x00c0b770` | `"LargeGroupBonusUpdate"` |
| `0x00c10e14` / `0x00c10e20` / `0x00c0f374` | the three shared partition-filter vtables |
| `0x00c63870` | the horde-gate filter's vtable — **2 references, both in this module** |
| `0x00c6387c` | the `LargeGroupBonus` interface vtable (3 slots) |
| `0x00c63888` | the `Update` interface vtable — slot 0 is `update` |
| `0x00c639d8` | the stock field-parse table (8 entries, ends `0x00c63a68`) |
| `0x00c63ad8` | the `ModuleData` vtable |
| `0x00c76ad8` | the `UpgradeMuxData` base table — the four upgrade rows' template |
| `0x00de412c` | `TheGameLogic` (frame counter at `+0x40`) |
| `0x00de4354` | `ThePartitionManager` |
| `Object+0x28c` / `Player+0x14c` | the completed-upgrade masks `held` tests |
