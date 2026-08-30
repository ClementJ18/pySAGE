# A reaction weapon cannot hit the thing that triggered it

RotWK `game.dat` 2.01.2614.37001, ImageBase `0x400000`. All static analysis; nothing here has been
watched in a running game. §7 lists what that leaves open.

The engine ships two ways to hurt whatever just hurt you, and each is missing the other's half.

| | aims at the attacker | can be gated on an upgrade |
|---|---|---|
| `FireWeaponWhenDamagedBehavior` | no | yes — the full `UpgradeMux` surface |
| `ReflectDamage` | yes | no — three fields, no mux at all |

So "20% thorns, from level 5" is not expressible. `FireWeaponWhenDamagedBehavior` fires its
reaction weapon at the damaged object's own feet, which means the only nugget that reaches anything
is one with a `Radius` — and that splashes every enemy standing near the defender, not the one that
swung. This patch gives that module the aim it is missing.

## 1. `FireWeaponWhenDamagedBehavior::onDamage`

The module registers at `0x006585BF` with interface mask `0x85`; its instance factory is
`0x0064BFE2` and its `ModuleData` factory `0x00653466`. The constructor at `0x00885A6F` writes four
interface vtables into the instance, of which `[esi+0x28] = 0x00C5FE10` is the damage interface —
three slots, the first being `onDamage` at **`0x00885CD5`**.

(The nearby `0x00885D90`, reached through `[esi+0x10] = 0x00C5FE68`, is the *update* — it returns
`0x3FFFFFFF`, the sleep-forever sentinel, and takes no arguments. That is the `Continuous*` weapons'
path, and this patch leaves it alone.)

`onDamage` is `__thiscall`, `ret 4`, with the `DamageInfo*` at `[esp+4]`. It does four things:

```
00885cd5  push esi
00885cd6  mov  esi, ecx                  ; the damage-interface sub-object, live throughout
00885cd8  lea  ecx, [esi-8]
00885cdb  mov  eax, [ecx]
00885cdd  call dword [eax]               ; the upgrade mux: is this module active?
00885cdf  test al, al
00885ce1  je   0x885d8c
00885ce7  mov  edx, [esp+8]              ; the DamageInfo
00885ceb  mov  ecx, [edx+0x10]           ; its DamageType
00885cee  mov  eax, [esi-0x24]           ; the ModuleData
00885cf1  push edi
00885cf4  dec  ecx
00885cf5  inc  edi
00885cf6  shl  edi, cl                   ; 1 << (type-1)
00885cf8  test dword [eax+0x13c], edi    ; DamageTypes
00885cfe  je   0x885d8b
00885d04  movss xmm0, dword [eax+0x140]  ; DamageAmount
00885d0c  comiss xmm0, dword [edx+0x70]  ; the damage that was actually dealt
00885d10  ja   0x885d8b                  ; below the threshold: nothing to do
00885d12  mov  edi, [esi-0x20]           ; the owning Object
```

Two things to take from the prologue. `esi` is the interface sub-object and the `ModuleData` hangs
off it at `[esi-0x24]`, pinned by the two reads through it — `DamageTypes` at `+0x13C` and
`DamageAmount` at `+0x140`, exactly where the field table puts them. And `edi` is the owning
`Object` from `0x00885D12` onwards. Both survive to the end of the function: the only calls after
this point are `__thiscall`s, which preserve `esi`/`edi`/`ebx`.

Then a four-arm ladder on the body damage state (`[edi+0x25C]`, vtable `+0x24`, returning 0..3)
picks `ReactionWeaponPristine` / `Damaged` / `ReallyDamaged` / `Rubble` from `ModuleData` `+0x144`,
`+0x148`, `+0x14C`, `+0x150` — and every arm jumps to the same five bytes:

```
00885d81  lea  eax, [edi+0x38]           ; the owning object's OWN position
00885d84  push eax
00885d85  push edi
00885d86  call 0x006cf3d2                ; createAndFireTempWeapon(source, const Coord3D *at)
00885d8b  pop  edi
00885d8c  pop  esi
00885d8d  ret  4
```

That is the whole defect, and it is three instructions long. The `DamageInfo` is still on the stack
at `[esp+0xc]`; its `+0x8` is the attacker's `ObjectID`; the function never reads it.

**The block has one entry.** All four arms (`0x00885D38`, `0x00885D52`, `0x00885D6C` and the
fall-through from `0x00885D7E`) jump to `0x00885D81` itself, never into the middle of it — so
replacing those five bytes catches every path, and five bytes is exactly a `jmp rel32`.

## 2. Why a position is not enough: the two `createAndFireTempWeapon` overloads

`0x006CF3D2` is one of seven thin wrappers (`0x006CF328`–`0x006CF428`) over the shared firing
routine `0x006CEF6D`. Reading the pushes back to front gives that routine's argument shape:

```
a1 = source object        a4 = victim ObjectID     a7 = ?
a2 = &source->position    a5 = victim position     a8 = ?
a3 = victim object        a6 = ?                   a9 = &out ObjectID
```

The positional overload the module uses passes `a3 = a4 = 0`:

```
006cf3d2  push ebp
006cf3d5  push ecx
006cf3d6  xor  eax, eax
006cf3db  push edx                       ; a9 = &outId
006cf3dc  push eax                       ; a8 = 0
006cf3dd  push eax                       ; a7 = 0
006cf3de  push 1                         ; a6
006cf3e0  push dword [ebp+0xc]           ; a5 = the position passed in
006cf3e6  push eax                       ; a4 = 0   <- no victim id
006cf3e7  push eax                       ; a3 = 0   <- no victim object
006cf3e8  mov  eax, [ebp+8]
006cf3eb  lea  edx, [eax+0x38]
006cf3ee  push edx                       ; a2 = &source->position
006cf3ef  push eax                       ; a1 = source
006cf3f0  call 0x006cef6d
006cf3f5  ...
006cf404  ret  8
```

A NULL victim is why only a `Radius` reaches anything: with no object to apply to, a nugget has
nothing but the area around `a5`.

The sibling at **`0x006CF3AE`** is the same call with the victim filled in:

```
006cf3ae  mov  eax, [esp+8]              ; argB
006cf3b2  mov  edx, [eax+0x74]           ; argB's ObjectID
006cf3b5  push 0                         ; a9
006cf3b7  push 0                         ; a8
006cf3b9  push 1                         ; a7
006cf3bb  push 1                         ; a6
006cf3bd  push 0                         ; a5 = no position
006cf3bf  push edx                       ; a4 = victim id
006cf3c0  push eax                       ; a3 = victim object
006cf3c1  mov  eax, [esp+0x20]           ; argA
006cf3c5  lea  edx, [eax+0x38]
006cf3c8  push edx                       ; a2 = &source->position
006cf3c9  push eax                       ; a1 = source
006cf3ca  call 0x006cef6d
006cf3cf  ret  8
```

so its signature is `createAndFireTempWeapon(Object *source, Object *victim)`, `__thiscall` with
the `WeaponTemplate` in `ecx`, `ret 8`.

**Which argument is which, twice over.** `argA` lands in `a1`, the same slot the positional
overload fills with its own first argument — which `onDamage` passes `edi`, the reflecting object,
so `a1` is the source. And its live caller at `0x006CF62D` agrees:

```
006cf618  mov  eax, [edi+0x74]
006cf61b  mov  [esi+8], eax              ; esi is a temp weapon; +8 takes edi's id as its owner
006cf626  push dword [esp+0x14]          ; argB
006cf62c  push edi                       ; argA — the object whose id was just stored as owner
006cf62d  call 0x006cf3ae
```

Getting this backwards would make the Umbar Lord damage himself, so it is worth the two readings.

## 3. `ReflectDamage`, for contrast

The other module (registered `0x0065ADAB`, `ModuleData` ctor `0x008BECE3`, damage vtable
`0x00C70968`) has the aim and not the gate. `onDamage` at `0x008BED43`:

```
008bed4f  mov  eax, [edi+0x10]           ; the DamageType
008bed52  cmp  eax, 0xd
008bed5a  je   0x8bedc5                  ; REFLECTED (index 13): never reflect a reflection
008bed64  test dword [esi+8], eax        ; DamageTypesToReflect
008bed67  je   0x8bedc5
008bed69  push dword [edi+8]             ; the attacker's ObjectID   <- the field FWWD ignores
008bed6c  mov  ecx, dword [0xde412c]     ; TheGameLogic
008bed72  call 0x00449681                ; findObjectByID
008bed7c  je   0x8bedc5                  ; gone: nothing to reflect onto
008bed86  movss xmm0, dword [edi+0x20]   ; the damage taken
008bed8b  mulss xmm0, dword [esi+0xc]    ; ReflectDamagePercentage
008bed90  comiss xmm0, dword [esi+0x10]  ; MinimumDamageToReflect
008beda0  mov  dword [ebp-0x6c], 0xd     ; the new DamageInfo's type: REFLECTED
008bedad  ja   0x8bedb4
008bedaf  movss xmm0, dword [esi+0x10]   ; ... so the "minimum" is a FLOOR, not a threshold
008bedb4  mov  ecx, [ebp+8]              ; the attacker
008bedc0  call 0x00698e7d                ; attemptDamage, on the attacker
```

This is the routine that establishes `DamageInfo+0x8` as the source `ObjectID` — the same struct
`FireWeaponWhenDamagedBehavior::onDamage` reads `+0x10` and `+0x70` of and `+0x8` of never. Its
`ModuleData` is `0x14` bytes with three fields and its `onDamage` opens with no mux check, which is
the whole reason it cannot be put behind a level.

## 4. Where a new field can go

`FireWeaponWhenDamagedBehavior`'s `ModuleData` is **`0x164` bytes** (`push 0x164` at `0x00653467`)
and it has no room in it.

The `UpgradeMux` base sub-object sits at `+0x8` and its constructor `0x00653173` writes as far as
base `+0x12E`; the derived constructor `0x006533E5` starts at `+0x138`. That gap is the base's own
tail padding, not the derived class's — every `UpgradeMux`-derived module in the build puts its
first field at `0x138`, which is what says the base is `0x130` bytes and ends there:

| module | `sizeof(ModuleData)` | first derived field |
|---|---|---|
| `LocomotorSetUpgrade` | `0x13C` | `KillLocomotorUpgrade` at `0x138` |
| `ArmorUpgrade` | `0x140` | `KillArmorUpgrade` at `0x138` |
| `WeaponSetUpgrade` | `0x148` | `WeaponCondition` at `0x138` |
| `FireWeaponWhenDamagedBehavior` | `0x164` | `StartsActive` at `0x138` |

and this module's own fields then run `0x138`, `0x13C`, `0x140`, `0x144`…`0x160` with no hole in
them. `ContinuousWeaponRubble` is a dword at `0x160`, so the stock fields end flush at `0x164`.

There is therefore nothing to borrow, the way `queue-ignore-cp` borrows `CommandButton+0x10D`. The
block is **grown** instead: `push 0x164` becomes `push 0x168`, and the field takes `0x164` — past
every stock field by construction rather than by inspection. `_check_table` asserts exactly that,
by reading the live table and requiring its highest offset plus four to still be the stock size.

`0x00653466` is the only allocation: it is the `newModuleData` the module's registration names, and
its `push 0x164` is a bare `imm32`.

## 5. The patch

One cave (`.faa`) holding the keyword string, a rebuilt field-parse table and two routines, and
four edits outside it.

| site | stock | becomes |
|---|---|---|
| `0x00653467` | `push 0x164` | `push 0x168` |
| `0x00653478` | `call 0x006533E5` | `call <cave: ctor shim>` |
| `0x0065344A` | `push 0x00C06698` | `push <cave: rebuilt table>` |
| `0x00885D81` | `lea eax,[edi+0x38]` / `push eax` / `push edi` | `jmp <cave: aim>` |

**The table.** `FireWeaponWhenDamagedBehavior`'s own field table is `0x00C06698`, eleven rows, named
by exactly one instruction — the `push` inside its parse callback at `0x00653444`, which walks this
table and then the shared `UpgradeMux` one (fetched by `0x008D26E0` with a base offset of 8, which
is why the mux fields' offsets are base-relative and this module's are not). The cave holds the
eleven live rows copied verbatim, plus `{name, INI_PARSE_BOOL, 0, 0x164}`, plus a terminator. The
table is resolved from that reference rather than from the stock constant, so the patch appends to
whatever is live and a second application fails cleanly instead of installing a duplicate row.

**The default.** `operator new` does not zero, so the constructor call is redirected through a shim.
The stock constructor is `__thiscall` with no arguments returning `this` in `eax`, so the shim is
three instructions and needs no frame:

```
call 0x006533e5                ; the stock ModuleData constructor
mov  dword [eax+0x164], 0      ; FireAtAttacker = No
ret
```

`newModuleData` goes on to test `eax` for NULL exactly as before.

**The aim.** Entered by `jmp` from `0x00885D81`, so the stack is still `onDamage`'s — `[esp]` saved
`edi`, `+4` saved `esi`, `+8` the return address, `+0xC` the `DamageInfo`. `ecx` holds the chosen
`WeaponTemplate` and is destroyed by `findObjectByID`, so it is bracketed; `findObjectByID` is
`ret 4` and cleans its own argument, so the bracket balances.

```
aim:
    mov   eax, [esi-0x24]          ; the ModuleData
    cmp   byte [eax+0x164], 0
    je    at_self                  ; FireAtAttacker = No
    push  ecx                      ; the WeaponTemplate, over the lookup
    mov   eax, [esp+0x10]          ; the DamageInfo (one push deeper than [esp+0xc])
    push  dword [eax+8]            ; whatever dealt the damage
    mov   ecx, dword [0xde412c]    ; TheGameLogic
    call  0x00449681               ; findObjectByID -> eax, or NULL
    pop   ecx
    test  eax, eax
    je    at_self                  ; no source object, or it is already gone
    push  eax                      ; victim = the attacker
    push  edi                      ; source = the reflecting object, as before
    call  0x006cf3ae               ; createAndFireTempWeapon(source, victim)
    jmp   0x00885d8b               ; past the stock call, into the epilogue
at_self:
    lea   eax, [edi+0x38]          ; the three displaced instructions, verbatim
    push  eax
    push  edi
    jmp   0x00885d86               ; the stock call
```

The two resume addresses are the thing to get right: `at_self` returns to the stock `call`, the
taken path returns *past* it. Swapping them fires the weapon twice or not at all.

**It falls back rather than failing.** Damage with no source object — fire, poison, a script, an
attacker that has already died — leaves the lookup returning NULL and takes the `at_self` path,
which is stock behaviour. A reaction weapon that silently stopped firing would be much harder to
diagnose than one that occasionally goes off at home.

## 6. What the INI gets

One `Bool` on the behavior, `No` by default:

```ini
Behavior = FireWeaponWhenDamagedBehavior ModuleTag_Reflect
    StartsActive           = No
    TriggeredBy            = Upgrade_Level_5
    ReactionWeaponPristine = UmbarLordReflectDamage
    DamageTypes            = +CRUSH +SLASH +CHOP +PIERCE
    DamageAmount           = 1
    FireAtAttacker         = Yes
End
```

With it on, the reaction weapon's nuggets apply to the attacker as a victim object, so `Radius` can
go to zero and the damage stops splashing. The source of the damage is still the reflecting unit,
so kill credit and XP are unchanged, and `DamageTypes`/`DamageAmount`/the upgrade mux all run stock
and are reached before the aim.

The `Continuous*` weapons are untouched — they fire from the module's `update`, where there is no
attacker in scope at all.

## 7. What is not established

- **Nothing has been watched in a running game.** The reading is here and the bytes verify; that is
  all.
- **`a6`, `a7` and `a8` of `0x006CEF6D` are unidentified.** The object-targeted overload passes
  `a7 = 1` where the positional one passes `0`. Both are stock call sites used elsewhere in the
  engine, so the patch inherits whatever they mean rather than choosing, but what they mean is not
  written down here.
- **`DamageInfo+0x20` and `+0x70` are two different fields**, and which is the requested damage and
  which the amount actually dealt after armour is not established. `ReflectDamage` scales `+0x20`;
  `FireWeaponWhenDamagedBehavior` thresholds `DamageAmount` against `+0x70`. This patch reads
  neither — it only adds `+0x8` to what the module looks at — so nothing here depends on the
  answer.
- **How two reflectors facing each other behave.** `ReflectDamage` guards itself by refusing damage
  of type `REFLECTED`; `FireWeaponWhenDamagedBehavior` has no such guard and never had one. This
  is **not new** — two stock units whose reaction weapons each pass the other's `DamageTypes` filter
  already ping-pong whenever their radii reach, and the module's `DamageTypes` filter is the only
  thing that has ever stopped it. What the patch changes is that the exchange no longer depends on
  a radius, so a pairing that happened to be out of range before will now connect. Each round still
  has to clear `DamageAmount` and both units take real damage throughout, so it should terminate;
  that has not been demonstrated, and a mod pairing two reflectors is better off giving their
  reaction weapons a `DamageType` neither filter accepts.
