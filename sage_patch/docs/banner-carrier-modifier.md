# `HordeContain` — an `AttributeModifier` for the horde that loses its banner carrier

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000` for everything cited here. Read from
`sage_patch/engine/game.dat.backup` (11,346,432 bytes — the clean Edain backup), and
every site cited below is byte-identical in the repo's own `game.dat`.

**Verdict up front: the behaviour is already written, twice.** `HordeContain` already notices its
banner carrier dying, and it already owns a routine that applies a named `ModifierList` to every
member of the horde plus the container object — that routine is what the stock `AttributeModifiers`
keyword drives — along with its exact inverse. What is missing is one field and four bytes of glue
between them. The only genuinely awkward part is *where to put the field*, and that is an
inheritance problem rather than a code problem: `AODHordeContainModuleData` derives from
`HordeContainModuleData` and has already claimed the space past its end.

- **Cost:** 3 size literals + 1 imm32 repoint + 3 displaced windows (23 bytes) + 1 repointed `call`
  + a 704 → 720-byte table copy + ~140 bytes of stubs. `HordeContainModuleData` grows by `0x4C`,
  of which 4 bytes are the field and `0x48` is the hole that makes one offset valid in all three
  classes.
- **Risk:** low, and opt-in — an unwritten keyword is a NULL `AsciiString` and every added path
  tests it before doing anything. It **is** simulation state, so peers must match; §7.
- **Status:** **built** — see [`patches/banner_modifier.py`](../patches/banner_modifier.py).

```
sage-patch apply banner-modifier --in game.dat.backup --out game.dat
sage-patch apply banner-modifier --keyword BannerLossModifier --no-restore --in ... --out ...
sage-patch verify banner-modifier game.dat
```

```ini
ModifierList NoBannerPanic
  Category  = LEADERSHIP
  Modifier  = ARMOR -25%
  Modifier  = RESIST_FEAR -50%
  Duration  = 0                 ; until the horde is re-bannered
  FX        = FX_BannerLost
End

Behavior = HordeContain ModuleTag_Horde
  BannerCarriersAllowed                = GondorBannerCarrier
  BannerCarrierPosition                = UnitType:GondorBannerCarrier Pos:X:0 Y:0
  BannerCarrierDestroyHordeOnDeath     = No
  BannerCarrierInflictsModifierOnDeath = NoBannerPanic     ; <- the new keyword
End
```

## 1. What the engine does today

### 1.1 The banner-carrier death arm

`HordeContain`'s member-removed handler is `0x00871915` (`__thiscall`, `ret 4`, argument is the
`Object *` that left). It compares that object's `ObjectID` (`Object+0x74`) against two slots on
the module:

```
00871921  mov  edx, [ebp+8]              ; the object that left
00871924  mov  eax, [edx+0x74]           ; its ObjectID
0087192a  lea  ecx, [esi+0x264]          ; the LEADER slot
00871930  cmp  [ecx], eax
00871932  jne  0x87193c
00871934  and  [ecx], 0                  ; the leader died: clear it and leave
00871937  jmp  0x8719d5
0087193c  cmp  [esi+0x26c], eax          ; the BANNER CARRIER slot
00871942  jne  0x8719d5                  ; somebody else: nothing to do
00871948  push edi
00871949  mov  edi, [esi+4]              ; the ModuleData
0087194c  test edi, edi
0087194e  je   0x8719b5
00871950  cmp  byte [edi+0x224], 0       ; BannerCarrierDestroyHordeOnDeath
00871957  je   0x8719b5                  ; No  -> the horde lives  (the arm this patch hooks)
                                         ; Yes -> kill every member with
                                         ;        BannerCarrierHordeDeathType (0x228)
008719b5  and  dword [esi+0x26c], 0      ; clear the banner slot
008719bc  push edx                       ; <- edx is still the dying object
008719bd  mov  ecx, esi
008719bf  call 0x86bf43                  ; pick what happens next (respawn bookkeeping)
```

Two things about `0x008719B5` decide the shape of the patch:

- **It is a join point.** Both the `No` answer *and* the "no `ModuleData` at all" check jump here,
  so a hook placed on it must re-test `edi` rather than assume it.
- **`edx` is live across it.** `0x008719BC` pushes the dying object as an argument, and on this
  path nothing between `0x00871921` and there is a `call` — so the compiler kept it in `edx`. A
  hook that calls anything has to put it back.

**The member is already out of the contain list** when this runs. The caller at `0x008739F6`
removes it first, at `0x008739A0` (`call [eax+0xa4]` on the contain sub-object), so "every member"
at the hook means every *surviving* member.

### 1.2 The routine that applies a `ModifierList` to a horde

`0x00870E50` — `__thiscall(AsciiString *name, ObjectFilter *filter, Int duration)`, `ret 0xc`. It
is the implementation behind the stock `AttributeModifiers` keyword, and it is virtual (present in
all three of the family's vtables, `0x00C5B3D0`, `0x00C5C070`, `0x00C5D180` — the same address in
each, so a direct call is exactly what dispatch would do).

```
00870e60  call [eax+0x118]               ; the contained list, via [this-0xfc]
00870e8f  mov  ecx, [0xdd90e4]           ; TheNameKeyGenerator  -> intern the name
00870ea1  mov  ecx, [0xde3c14]           ; TheAttributeModifierStore -> name key to index
00870eae  mov  ecx, [0xde3c14]           ;                          -> index to ModifierList *
00870eb3  test eax, eax
00870eb5  je   0x870f53                  ; no such block: apply nothing
00870ebb  cmp  [eax+0xc], 6              ; Category 6 is refused outright
00870ec8  ... per member: optional ObjectFilter test (0x7640c1), then
00870eef  call 0x68f1a8                  ;   Object::applyAttributeModifier(name, duration)
00870f07  ... the same again over the module's own ObjectID list at [this+0x54]
00870f6c  call 0x805a8e                  ; and finally the container object itself
```

Its inverse is `0x00870F75`, `__thiscall(AsciiString *name, ObjectFilter *filter)`, `ret 8`, with
the same three passes calling `0x0068F259` / `0x008052FB` instead.

**The name is resolved at apply time, not at parse time**, through
`TheAttributeModifierStore` (`0x00DE3C14`) — which is what lets INI name a `ModifierList` block
defined later in the load order. So the field can be a plain `AsciiString` and the patch needs no
parse hook of its own.

### 1.3 What the duration argument means

`0x0068F1A8` passes it through to `0x00805A8E`, where:

```
00805b08  mov  ecx, [ebp+0xc]            ; the duration argument
00805b0b  mov  eax, [0xde412c]           ; TheGameLogic -> +0x40 is the current frame
00805b17  jge  0x805b1c
00805b19  mov  ecx, [edi+0x18]           ; NEGATIVE -> the ModifierList's own Duration
00805b1f  test ecx, ecx
00805b24  jg   0x805b29
00805b39  mov  dword [ebp+0xc], 0x3fffffff  ; ZERO -> effectively forever
```

So `-1` is "whatever the block says", and a block with no `Duration` then lasts until something
removes it. That is why the patch passes `-1` and adds no duration keyword of its own: `Duration =
20000` in the `ModifierList` is a twenty-second effect that expires by itself, and its absence is
an effect that lasts until the horde is re-bannered.

### 1.4 Where a banner carrier is installed

The banner slot at `module+0x26C` is written in exactly one place at runtime — through an
out-parameter:

```
00876427  lea  eax, [esi+0x26c]          ; &m_bannerCarrierID
0087642d  push eax
0087642e  push edi                       ; the new carrier
0087642f  mov  ecx, esi
00876431  call 0x876394                  ; <- the site the restore hook replaces
```

and inside the callee, `0x008763A9  mov [ecx], eax`. The same callee has one other caller,
`0x0087651F`, which points it at `module+0x264` — the **leader** slot — and is deliberately left
alone. The constructor at `0x00872924` zeroes both; the save/load xfer at `0x0087846C` restores
them, and needs no hook because the modifier state lives on the objects and is saved with them.

## 2. The one hard part: where the field goes

`HordeContainModuleData` is `0x284` bytes and **fully packed** — the last field,
`LivingWorldOverloadTemplate`, is an `AsciiString` at `0x280` and the allocation ends at `0x284`.
So a new field must grow it.

Three modules share this `ModuleData`, and one of them derives:

| module | `newModuleData` | `sizeof` | ctor | own fields |
|---|---|---|---|---|
| `HordeContain` | `0x0064B61C` | `0x284` | `0x00878EE5` | `0x00`–`0x284` |
| `HorseHordeContain` | `0x00653317` | `0x284` | `0x00878EE5` (+ vtable `0xC5CC70`) | — |
| `AODHordeContain` | `0x0064B851` | `0x2CC` | `0x0087D55F` → base ctor | **`0x284`–`0x2CC`** |

`AODHordeContainModuleData`'s thirteen fields (`FrequencyScale` … `ScatterRandomness`) occupy
exactly the range a field appended at the base's old end would land in. The reader — the death arm
at `0x008719B5` — is shared code that cannot know which class it has.

**So the field goes at `0x2CC`, past every layout in the family, and all three allocations grow to
`0x2D0`.** `HordeContain` and `HorseHordeContain` carry `0x48` bytes of hole they never touch. That
is a per-*template* cost, paid once at INI load for a few hundred hordes, and it buys one offset
that is correct in every class sharing the code that reads it.

Two things make this safe rather than merely convenient:

- **The base constructor runs first.** `0x0087D562` calls it before writing `0x284`–`0x2CC`, so
  zeroing `0x2CC` in the base cannot be clobbered by the derived class.
- **`buildFieldParse` chains.** `0x0087D62E` calls `0x00878B63` and then contributes its own table
  — the engine's `MultiIniFieldParse` holds several tables per module — so relocating
  `HordeContain`'s table is all three classes' keyword, and neither derived table has to move.

There is a fourth `push 0x284` in the image (`0x0064BA58`) and a second `HorseHordeContain`
constructor (`0x0064B69F`); the first belongs to an unrelated module (ctor `0x00881D4B`) and the
second has **zero callers**. Neither is touched.

## 3. The `ModuleData` sites

| what | VA | stock bytes |
|---|---|---|
| ctor tail — zeroes `LivingWorldOverloadTemplate` | `0x008790D7` | `89 9e 80 02 00 00` (`mov [esi+0x280], ebx`) |
| dtor — releases the same string | `0x00878D3B` | `8d 8e 80 02 00 00 c6 45 fc 0c` |
| field table | `0x00C5BB50` | 43 entries + terminator, **704 bytes** |
| its sole reference | `0x00878B74` | the imm32 of `push 0xc5bb50` |

The constructor writes `AsciiString` fields as a plain zero store (`ebx` is its zero register
throughout), so the new field is initialised the same way — no `AsciiString` constructor call is
involved anywhere in this `ModuleData`.

The destructor does call one: `0x00435D50`, on `0x1B0`, `0x244` and `0x280`, each preceded by the
unwind-state byte the compiler pairs with it. The new field is released immediately before
`0x280`, and the displaced `lea`/`mov` pair is reproduced verbatim so the stock `call` that follows
the hook still destroys `0x280`.

**The table cannot grow in place**: it ends at `0x00C5BE10`, which is the `ModuleData` vtable. It
is loaded by a single instruction, so the patch copies it into the cave with one appended entry —
`{ "BannerCarrierInflictsModifierOnDeath", 0x0042EE5E, 0, 0x2CC }`, naming the engine's own
`AsciiString` parser — and repoints that one imm32. Lookup is a linear name scan, so appending
needs no re-sort.

## 4. The two glue sites

### 4.1 Apply — `0x008719B5`, seven bytes

```
        and  dword [esi+0x26c], 0        ; the displaced instruction
        test edi, edi
        je   .done                       ; no ModuleData
        mov  eax, [edi+0x2cc]
        test eax, eax
        je   .done                       ; keyword unwritten -> stock, bit for bit
        push edx                          ; the dying object, live for the caller's next push
        push -1                           ; duration: the ModifierList's own
        push 0                            ; no ObjectFilter
        lea  eax, [edi+0x2cc]
        push eax
        lea  ecx, [esi+0x11c]             ; the contain sub-object
        call 0x870e50
        pop  edx
.done:  ret
```

`this` for `0x00870E50` is the module base plus `0x11C`. That relationship is read straight off
the engine: the caller of the death handler computes `lea ebx, [esi-0x11c]` at `0x00873821` to get
the module base from that same sub-object pointer, and the death handler itself uses
`lea ecx, [esi+0x11c]` at `0x0087195D` for its own list walk.

### 4.2 Restore — `0x00876431`, one `call`

```
        push ecx
        mov  eax, [ecx+4]                 ; the ModuleData
        test eax, eax
        je   .done
        mov  edx, [eax+0x2cc]
        test edx, edx
        je   .done
        push 0                            ; no ObjectFilter
        add  eax, 0x2cc
        push eax
        add  ecx, 0x11c
        call 0x870f75                     ; ret 8
.done:  pop  ecx
        jmp  0x876394                     ; the installer, whose ret 0xc cleans the caller's frame
```

The **tail jump matters**: the displaced callee cleans twelve argument bytes that are already on
the stack above this stub's return address, so returning and then calling would push them twice.

Removal is by name, which is the only grain the engine's own API has — `0x00870F75` looks the
block up in `TheAttributeModifierStore` exactly as the apply does. An instance of the same block
applied from somewhere else is therefore lifted too. The engine's `LargeGroupBonusUpdate` has the
same property.

## 5. Why the removal is part of the feature

A banner carrier is not gone for good: `BannerCarrierUpdate` has `DiedRespawnTime` and
`MeleeFreeBannerReSpawnTime`, and the death arm's own tail (`0x008719BF`) is the respawn
bookkeeping. Without the removal, a horde that lost and regained its banner would carry the
"no banner" malus for the rest of the match, which is the opposite of what the keyword reads like.
`--no-restore` drops that hook for a mod that wants a permanent on-death effect (a revenge bonus,
say) and does not want it cancelled by a respawn.

## 6. What this does *not* do

- **It does not fire when `BannerCarrierDestroyHordeOnDeath = Yes`.** That arm kills every member;
  there is nothing left to modify. The two keywords are independent and this one is simply ignored
  there.
- **It does not fire for the leader.** `module+0x264` is a separate slot with its own, much
  shorter arm (`0x00871934`), and nothing in the INI names a leader-loss effect today.
- **It does not filter.** Both engine routines take an `ObjectFilter`, and the patch passes NULL.
  Adding `Yes`/`No` per member would be a second four-byte field and a second keyword; the
  `ModifierList`'s own `Category` and per-`Modifier` `Upgrade` gates already cover most of what a
  filter would say.

## 7. Determinism and load-time compatibility

An `AttributeModifier` changes armour, damage, speed and model conditions on the logic-side
`Object`, so this is **simulation state**: every peer must run the same patched binary, and a
replay recorded on it will not play back on a stock one — the same rule as `spawn-union` and
`production-condition`.

INI naming the new keyword also **fails to load** on an unpatched `game.dat` (the field-parse scan
raises on an unknown field), so a mod using it ships the binary with it rather than degrading
quietly.

## 8. Address summary

| what | VA |
|---|---|
| `HordeContain` `newModuleData` size literal | `0x0064B61C` |
| `HorseHordeContain` `newModuleData` size literal | `0x00653317` |
| `AODHordeContain` `newModuleData` size literal | `0x0064B851` |
| `HordeContainModuleData` ctor / its tail store | `0x00878EE5` / `0x008790D7` |
| `HordeContainModuleData` dtor / its `0x280` release | `0x00878B7E` / `0x00878D3B` |
| `AsciiString::~AsciiString` | `0x00435D50` |
| `buildFieldParse` / table / sole reference | `0x00878B63` / `0x00C5BB50` / `0x00878B74` |
| `AsciiString` field parser | `0x0042EE5E` |
| member-removed handler (the death arm) | `0x00871915` (arm at `0x008719B5`) |
| apply `ModifierList` to members | `0x00870E50` |
| remove `ModifierList` from members | `0x00870F75` |
| `Object::applyAttributeModifier` / remove | `0x0068F1A8` / `0x0068F259` |
| duration resolution | `0x00805A8E` |
| banner-carrier install call / callee | `0x00876431` / `0x00876394` |
| `TheAttributeModifierStore` / `TheNameKeyGenerator` | `0x00DE3C14` / `0x00DD90E4` |
