# The production door remembers one horde, and gives it everything that walks out

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR), read from this
repo's `game.dat` (the stock image plus an appended `.cahfac` cave, so `.text` and `.rdata` are
byte-identical to the clean build).

**The report.** A hero that finishes while a battalion is still walking out of the same building
becomes part of that battalion. It is possible at all because hero revives run in parallel with
unit production - see [`hero-recruit-parallel.md`](hero-recruit-parallel.md).

**Verdict up front.** It is not the horde that takes the hero; it is the door. `QueueProductionExitUpdate`
keeps **one** `ObjectID` for "the horde currently coming out of me", and `exitObjectViaDoor` applies
it to every object that leaves while it is set - with no test of any kind on what that object is.
The window is the whole of the battalion's production entry, which is `Slots + 1` objects long, so
anything else finishing inside it is bound to the battalion.

- **Cost:** one repointed `call` (5 bytes) and a 183-byte cave.
- **Risk:** low. The gate reuses the horde's own membership rule, and a rejected object takes a
  code path the stock engine already has.
- **Status:** **built** - see [`patches/horde_exit_absorption.py`](../patches/horde_exit_absorption.py).
  **Statically verified, not runtime-verified.**

```
sage-patch apply horde-exit-absorption --in game.dat.backup --out game.dat
sage-patch verify horde-exit-absorption game.dat
```

## 1. The module

`QueueProductionExitUpdate` is the exit module on every production building. `ModuleFactory` builds
it at `0x00659535`; `newModule` is `0x0064E651`, the instance constructor `0x008A3948`, and the
instance is `0x44` bytes.

| sub-object | at | vtable |
|---|---|---|
| the module itself | `+0x00` | `0x00C683BC` |
| `ExitInterface` | `+0x20` | `0x00C682C4` |

Every routine below receives that `ExitInterface` sub-object as `ecx`, so a field written
`interface +N` here is module `+0x20+N`.

| `ExitInterface` slot | VA | what |
|---|---|---|
| `+0x08` | `0x008A3DD5` | `exitObjectViaDoor(obj, door)` |
| `+0x2C` | `0x008A3BF8` | finish the exit: clear the pending horde, un-flag it, send it to the rally point |

`smart-rally` reverse-engineered the same module for a different purpose and calls `+0x2C` the
*release* routine; the two readings agree on what it does.

### The field this is all about

**Interface `+0x20`, module `+0x40`: the `ObjectID` of the horde currently coming out of the door.**

| | where |
|---|---|
| zeroed | `0x008A399B`, in the constructor (`mov [esi+0x40], ecx` with `ecx` zero) |
| written | `0x008A42A2`, and nowhere else in the image |
| read | `0x008A402D` (`exitObjectViaDoor`) and `0x008A3C09` (the finish routine) |
| cleared | `0x008A3C1D`, in the finish routine, and nowhere else |

The write is guarded, at the tail of `exitObjectViaDoor`:

```
008a4267  8b 43 04              mov  eax, [ebx+4]              ; the exiting object's ThingTemplate
008a426a  f6 80 15 01 00 00 20  test byte [eax+0x115], 0x20    ; KINDOF HORDE - bit 109
008a4271  74 42                 je   0x8a42b5                  ; not a horde: skip the whole block
...
008a4299  8b 43 74              mov  eax, [ebx+0x74]           ; the horde's ObjectID
008a429c  6a 01 / 6a 03         push 1 / push 3
008a42a2  89 47 20              mov  [edi+0x20], eax           ; <- remembered
008a42a5  e8 a3 25 d8 ff        call 0x62684d                  ; setStatus(UNSELECTABLE, true)
008a42aa  6a 01 / 6a 02         push 1 / push 2
008a42b0  e8 98 25 d8 ff        call 0x62684d                  ; setStatus(UNDER_CONSTRUCTION, true)
```

`0x115 & 0x20` is `KindOf` bit 109, `HORDE` - the same bit `resolveAttackTarget` tests as
`[tmpl+0x114] & 0x2000` in [`horde-formation-orphans.md`](horde-formation-orphans.md) §2, reached
byte-wise instead. The two status bits are `UNSELECTABLE` (3) and `UNDER_CONSTRUCTION` (2), which is
exactly the pair that document measured on a battalion mid-formation (§6b).

## 2. The window is a whole production entry

The field is cleared only by the finish routine, and `ProductionUpdate::update` calls that only when
a queue entry has emitted everything it owes:

```
008a2de7  ff 50 08     call [eax+8]              ; exitObjectViaDoor(obj, door)
008a2dea  ff 43 24     inc  [ebx+0x24]           ; entry->made
...
008a2ec4  8b 43 20     mov  eax, [ebx+0x20]      ; entry->total
008a2ec7  2b 43 24     sub  eax, [ebx+0x24]
008a2eca  75 42        jne  0x8a2f0e             ; not finished: nothing more this frame
008a2ecc  ...          remove the entry, destroy it
008a2ee9  ff 50 2c     call [eax+0x2c]           ; <- the finish routine, unconditionally
```

`entry+0x20` is the object count and `entry+0x24` the number made, both established in
[`combo-horde-recruitment.md`](combo-horde-recruitment.md) §"the queue entry". That document also
records the rewrite at `0x008A2CC4` that gives a battalion's entry its count:

```
008a2cc7  inc  eax                    ; Slots + 1
008a2ccf  mov  [ebx+0x20], eax        ; entry->total = Slots + 1
```

So the entry emits the horde container first and then one member per pass, and the pending-horde
field is set for the whole of it. That is the fourteen-to-sixteen frame window
[`horde-formation-orphans.md`](horde-formation-orphans.md) §6a measured live, with members
appearing one per logic frame.

**Hero revives are a separate entry on the same queue**, advanced out of order by the picker's
third rule (`hero-recruit-parallel.md`), and finish on the player's own revive clock rather than the
queue's. So a hero can complete on any frame inside that window, and it leaves through the same
door - `Object::getExitInterface` returns the building's one exit module.

## 3. What the door then does to it

The head of `exitObjectViaDoor`, with `ebx` the exiting object (loaded at `0x008A3F29`) and `edi`
the `ExitInterface`:

```
008a402d  ff 77 20              push [edi+0x20]                ; the remembered horde id
008a4030  8b 0d 2c 41 de 00     mov  ecx, [0xde412c]           ; TheGameLogic
008a4036  e8 46 56 ba ff        call 0x449681                  ; findObjectByID
008a403b  33 f6                 xor  esi, esi
008a403d  85 c0                 test eax, eax
008a403f  89 45 e4              mov  [ebp-0x1c], eax
008a4042  74 44                 je   0x8a4088                  ; nothing pending -> the plain path
008a4044  8b 88 58 02 00 00     mov  ecx, [eax+0x258]          ; horde->m_contain
008a404a  85 c9                 test ecx, ecx
008a404c  74 12                 je   0x8a4060
008a404e  8b 01                 mov  eax, [ecx]
008a4050  ff 50 7c              call [eax+0x7c]                ; ContainModuleInterface::getHordeIface
008a4053  8b f0                 mov  esi, eax
...
008a4062  85 f6                 test esi, esi
008a4064  74 22                 je   0x8a4088
008a4066  ff 75 e4              push [ebp-0x1c]                ; the horde
008a4069  8b cb                 mov  ecx, ebx
008a406b  e8 31 76 de ff        call 0x68b6a1                  ; obj->setProducer(horde)
008a4070  8b 06                 mov  eax, [esi]
008a4072  53                    push ebx
008a4073  8b ce                 mov  ecx, esi
008a4075  ff 50 2c              call [eax+0x2c]                ; hordeIface: give it a formation slot
008a4078  8b 45 e4              mov  eax, [ebp-0x1c]
008a407b  ff b0 1c 03 00 00     push [eax+0x31c]               ; the horde's Team
008a4081  8b cb                 mov  ecx, ebx
008a4083  e8 c2 54 df ff        call 0x69954a                  ; obj->setTeam(...)
```

Three bindings, none of them conditional on anything about `ebx`:

- **`0x0068B6A1` is `Object::setProducer`** - `mov [ecx+0x78], producer->m_id`, four instructions
  long. `Object+0x78` is `producer_id`, measured on 40 of 40 battalion members in
  `tests/sage_live/fixtures/match.snapshot.gz` ([`horde-formation-orphans.md`](horde-formation-orphans.md)
  §6). It is also the field `resolveAttackTarget`'s ancestry fallback reads at `0x006681D0` to decide
  that a unit is part of a horde - so from this instruction on, every attack aimed at the hero
  resolves onto the battalion instead.
- **`0x0069954A` is `Object::setTeam`**, with a fall-back to the neutral player's default team when
  the argument is unusable. `Object+0x31C` is the horde's team.
- **`[hordeIface+0x2C]` is `0x00873F30`**, the formation-slot assignment - and it is the only one of
  the three that checks anything. §5 is what it checks.

### And the object is no longer a lone unit

Further down, the same resolved pointer decides the shape of the exit path:

```
008a4169  8b 43 04              mov  eax, [ebx+4]
008a416c  f6 80 15 01 00 00 20  test byte [eax+0x115], 0x20    ; is this object itself a horde?
008a4173  75 0a                 jne  0x8a417f                  ;   yes -> flag = 0
008a4175  83 7d e4 00           cmp  dword [ebp-0x1c], 0
008a4179  c6 45 0b 01           mov  byte [ebp+0xb], 1
008a417d  74 04                 je   0x8a4183                  ;   no horde pending -> flag stays 1
008a417f  c6 45 0b 00           mov  byte [ebp+0xb], 0
008a4183  80 7f 14 00           cmp  byte [edi+0x14], 0        ; is a rally point set?
008a4187  74 45                 je   0x8a41ce
008a4189  80 7d 0b 00           cmp  byte [ebp+0xb], 0
008a418d  74 3f                 je   0x8a41ce                  ; not a lone unit -> no rally waypoint
```

`[ebp+0xb]` means **"this is a lone unit"**: not a horde container, and no horde pending. Only a
lone unit gets the structure's rally point appended to its own exit path (`0x008A4189`..`0x008A41C6`);
a battalion's members do not, because the finish routine moves the container instead
(`0x008A3D32`). `[edi+0x14]` is module `+0x34`, the "rally point set" flag written by the position
setter at `0x008A3BF0`.

So the hero, wrongly flagged as a horde member, **is denied its own rally-point waypoint**. It walks
out of the door, stops, and is then carried along by the battalion's move order. That is the half of
the failure a player actually sees.

The same pointer is read once more at `0x008A4223`, to tell the AI to ignore the horde as a
pathfinding obstacle.

## 4. Where the horde interface comes from

Three call sites use the identical idiom - `mov ecx, [obj+0x258]` / `mov eax, [ecx]` /
`call [eax+0x7c]` with nothing pushed - and it is worth pinning down because it crosses two
vtables that are easy to conflate.

| | |
|---|---|
| `Object+0x258` | `ContainModuleInterface*` (`OBJECT_CONTAIN`) |
| for a `HordeContain`, that is | module `+0x20`, vtable `0x00C5B480` |
| its `+0x7C` | `0x00872A6F` |

```
00872a6f  8d 41 e0        lea  eax, [ecx-0x20]          ; the module base, or 0 if this was 0
00872a72  81 c1 fc 00 00 00  add ecx, 0xfc              ; -> module +0x11C
00872a78  f7 d8 / 1b c0 / 23 c1   ; eax = (module != 0) ? module+0x11C : 0
```

So `getHordeIface` hands back the sub-object at module `+0x11C`, whose vtable is `0x00C5B1F8`. That
is the vtable holding `+0x2C` slot-assign (`0x00873F30`), `+0x48` pick-a-member (`0x0086FA87`) and
`+0x180` count-members (`0x008706DF`).

> [`horde-formation-orphans.md`](horde-formation-orphans.md) §3 lists `0x00875C93` as
> "get the horde interface, vtable `+0x7C`". `0x00875C93` is `0x00C5B1F8+0x7C`, i.e. `+0x7C` of the
> *horde* interface, and it is a three-argument function (`ret 0xc`). The getter every call site
> actually reaches is `0x00872A6F`, `+0x7C` of `0x00C5B480`. The `+0x48` and `+0x180` entries in
> that same table are correct as listed.
>
> Separately, [`banner-carrier-filter.md`](banner-carrier-filter.md) labels `0x0044DDEC`
> `Object::isKindOf`. It is `Object::testStatus`, as `horde-formation-orphans.md` §2 has it - it
> indexes `[esi + edx*4 + 0x94]`, which is `OBJECT_STATUS`.

## 5. The one rule the engine does apply, and why it is the right gate

`0x00873F30` - horde interface `+0x2C` - is "give this object a formation slot", and it is
template-gated:

```
00873f30  55 8b ec ...
00873f39  80 7e 7c 00        cmp  byte [esi+0x7c], 0     ; have the slots been built?
00873f3d  75 10              jne  0x873f50
00873f40  8d 8e e4 fe ff ff  lea  ecx, [esi-0x11c]       ; -> the HordeContain module
00873f46  8b 01              mov  eax, [ecx]
00873f48  6a 01              push 1
00873f4a  ff 90 84 00 00 00  call [eax+0x84]             ; build them
00873f50  8b 46 78           mov  eax, [esi+0x78]        ; the unfilled-slot list (circular, sentinel)
00873f53  8b 38              mov  edi, [eax]
00873f55  3b f8              cmp  edi, eax
00873f57  0f 84 84 00 00 00  je   0x873fe1               ; none left -> no slot, silently
00873f5d  8b 5d 08           mov  ebx, [ebp+8]           ; the candidate object
00873f60  8b 47 08           mov  eax, [edi+8]           ; this slot's index
00873f63  8b 4e 6c           mov  ecx, [esi+0x6c]        ; the slot array
00873f69  6b c0 1c           imul eax, eax, 0x1c         ; stride 0x1C
00873f6c  ff 34 08           push [eax+ecx]              ; the slot's payload key
00873f6f  8b 8e e8 fe ff ff  mov  ecx, [esi-0x118]       ; the HordeContainModuleData
00873f75  e8 6d 84 ff ff     call 0x86c3e7               ; key -> declared payload entry
00873f7a  85 c0 / 74 1c      test eax,eax / je next
00873f7e  8b 0d 40 4a de 00  mov  ecx, [0xde4a40]        ; TheThingFactory
00873f84  83 c0 04           add  eax, 4                 ; the entry's template name
00873f87  50                 push eax
00873f88  e8 78 d3 e5 ff     call 0x6d1305               ; findTemplate
00873f8d  8b 4b 04           mov  ecx, [ebx+4]           ; the candidate's ThingTemplate
00873f90  50                 push eax
00873f91  e8 2c 96 ec ff     call 0x73d5c2               ; ThingTemplate::isEquivalentTo
00873f96  84 c0 / 75 09      test al,al / jne  <take the slot>
...
00873f9a  8b 3f              mov  edi, [edi]             ; next:
00873f9c  3b 7e 78           cmp  edi, [esi+0x78]
00873f9f  75 bf              jne  0x873f60
```

Taking the slot records `objID -> slotIndex` in the maps at `iface+0x54` and `iface+0x60` and erases
the node from the unfilled list.

`0x0086C3E7` is a linear scan of the `ModuleData` vector at `+0x18C`..`+0x190` for the entry whose
first dword is the key; `0x006D1305` is `ThingFactory::findTemplate`; `0x0073D5C2` is
`ThingTemplate::isEquivalentTo`, which compares final overrides and then the name lists at
`+0x33C`/`+0x340`, so an upgraded variant of a declared payload still answers yes. All three are
`__thiscall`, `ret 4`.

**This is already the engine's own answer to "does this object belong in this horde".** It is the
only test anywhere on the path, it is applied one instruction too late to stop the other two
bindings, and it is what the patch lifts to the top.

Note what it means for a hero: the assignment quietly does nothing (no slot's template is
equivalent), so on a stock build the hero gets the producer link, the team and the exit routing
**without** a formation slot. Half-bound, which is why the symptom is "it follows the battalion
around" rather than "it is one of them".

## 6. The patch

One repointed `call`, at `0x008A4036`, into a cave that answers the membership question and hands
back the horde or NULL. **NULL is a value the stock code already handles**: `0x008A4042` takes the
`je` to `0x8A4088`, `esi` stays zero from `0x008A403B`, `[ebp-0x1c]` is zero, so the bind block
never runs, `0x008A4169` reads "lone unit", and `0x008A4223` skips the obstacle hint. The object
leaves exactly as it would from a building with nothing in its door.

| VA | file off | from | to |
|---|---|---|---|
| `0x008A4036` | `0x004A4036` | `e8 46 56 ba ff` | `call <cave>` |

The cave mirrors `0x00873F30`'s walk - the same offsets, the same three helpers, and the same
register assignment (`esi` the interface, `edi` the list node, `ebx` the object), which is what lets
it inherit that loop's own demonstration that the helpers preserve all three. It re-pushes the
argument the hooked site pushed, calls `findObjectByID` itself, and returns `ret 4` like the call it
replaced.

```asm
    push dword [esp+4]
    call 0x00449681               ; eax = the pending horde, or NULL
    test eax, eax
    je   .out
    push esi / push edi / push eax    ; the horde is also the return slot
    mov  ecx, [eax+0x258]
    test ecx, ecx
    je   .keep                    ; no contain module: stock declines on its own
    mov  eax, [ecx]
    call [eax+0x7c]               ; getHordeIface
    test eax, eax
    je   .keep
    mov  esi, eax
    cmp  byte [esi+0x7c], 0       ; the free-slot list is lazy
    jne  .walk
    lea  ecx, [esi-0x11c] / mov eax,[ecx] / push 1 / call [eax+0x84]
.walk:
    mov  eax, [esi+0x78] / mov edi,[eax] / cmp edi,eax
    je   .reject                  ; every slot taken: not expecting anybody
.loop:
    mov  eax, [edi+8] / imul eax,eax,0x1c / add eax,[esi+0x6c]
    push dword [eax]
    mov  ecx, [esi-0x118]
    call 0x0086c3e7               ; key -> payload entry
    test eax,eax / je .next
    mov  ecx, [0x00de4a40] / add eax,4 / push eax
    call 0x006d1305               ; findTemplate
    test eax,eax / je .next
    mov  ecx, [ebx+4] / push eax
    call 0x0073d5c2               ; isEquivalentTo
    test al,al
    jne  .keep
.next:
    mov  edi,[edi] / cmp edi,[esi+0x78] / jne .loop
.reject:
    pop  eax / xor eax,eax / jmp .restore
.keep:
    pop  eax
.restore:
    pop  edi / pop esi
.out:
    ret  4
```

183 bytes, in one `0x1000` section (`.hrdexit`) allocated with `allocate_section`.

**Why not a `KINDOF HERO` test.** It is four bytes and it is wrong: `LothlorienRumil` fields Rumil
and Orophin as a two-slot battalion, so the member walking out of that door *is* `KINDOF HERO` and
*does* belong. The discriminator has to be the battalion's payload list, not the kind of thing being
produced. The same argument rules out `MACHINE` and `SIEGE_TOWER` - `HordeContain::addToContain`
(`0x0086CF2A`) refuses to call those three kinds horde *members*, but they are legitimately inside a
siege battalion.

**Why not gate the slot assignment instead.** It is three bytes (`ff 50 2c`), too short for a jump,
and gating it there would leave `setProducer` and `setTeam` already done.

**The lazy build moves a few instructions earlier.** The cave has to build the free-slot list before
it can walk it, and that is the call the stock code makes at the next site it reaches, with the same
argument, on the same horde, on the same frame. The only case where the two differ is an object the
cave rejects, whose horde then has its list built sooner than it otherwise would - and needs it
built anyway, for the members that follow.

### Anchors

The patch refuses to apply unless all ten hold, checked before anything is written:

| VA | what it pins |
|---|---|
| `0x008A3DD5` | the function being edited |
| `0x008A4066` | the bind block: what the hook prevents |
| `0x008A4169` | the lone-unit flag: the other reader of the same answer |
| `0x008A4267` | the `KINDOF HORDE` test and the only write of the pending-horde field |
| `0x00449681` | `findObjectByID` |
| `0x00872A6F` | `getHordeIface` returning module `+0x11C` |
| `0x00873F30` | **106 bytes**: the whole rule being mirrored |
| `0x0086C3E7` | the payload-key lookup |
| `0x006D1305` | `findTemplate` |
| `0x0073D5C2` | `isEquivalentTo` |

The 106-byte anchor is the load-bearing one. Duplicating an engine rule is only safe while the
original still says what the duplicate assumes, so the patch asserts the original verbatim rather
than trusting a comment.

## 7. What this does not fix

**The hero's entry still finishes the battalion's exit early.** `ProductionUpdate::update` calls the
finish routine at `0x008A2EE9` whenever *any* entry completes, and the finish routine acts on
whatever `+0x40` names. So a hero completing mid-battalion still clears the pending horde, takes the
container off `UNDER_CONSTRUCTION`/`UNSELECTABLE`, and sends it to the rally point while members are
still in the door - and those members then exit with nothing pending and no formation slot.

That state is recognisable: it is the ghost container of
[`horde-formation-orphans.md`](horde-formation-orphans.md) §6b, alive with zero members,
`UNDER_CONSTRUCTION` and `UNSELECTABLE` cleared but `IS_LEAVING_FACTORY` still set, its units loose
and still naming it as producer. **This is a hypothesis, not a finding.** §6c of that document is a
standing warning about exactly this kind of inference: two patches were built there from a causal
reading that measured facts supported and the running game refused. The thing to do is reproduce it
- recruit a hero into a battalion's exit window and read the container back through `sage_live` -
before writing anything.

**The obvious gate is worse than the bug.** Deferring the finish while the horde still has unfilled
slots is five instructions at `0x008A3C0C`, the same shape as this patch's hook. But a horde whose
list can never empty then never clears `+0x40`, and the next battalion of the *same* unit type is
absorbed into the stale one - a template match, so this patch's gate would wave it through. Any real
fix there needs a bound (a frame count, or the identity of the entry that produced the horde), and
the entry is destroyed at `0x008A2EDB` and freed at `0x008A2EDE`, just before the call.

## 8. Appendix - every address this document depends on

| VA | meaning |
|---|---|
| `0x00449681` | `TheGameLogic::findObjectByID`, `ret 4` |
| `0x0064E651` | `QueueProductionExitUpdate` `newModule` |
| `0x00659535` | its `ModuleFactory::addModule` registration |
| `0x00668167` | `resolveAttackTarget` - the producer-link reader |
| `0x006681D0` | its ancestry fallback, `push [esi+0x78]` |
| `0x0068B6A1` | `Object::setProducer` |
| `0x0069954A` | `Object::setTeam` |
| `0x006D1305` | `ThingFactory::findTemplate`, `ret 4` |
| `0x0073D5C2` | `ThingTemplate::isEquivalentTo`, `ret 4` |
| `0x0086C3E7` | payload key -> declared entry, `ret 4` |
| `0x0086CF2A` | `HordeContain::addToContain` - clears `HORDE_MEMBER` for `MACHINE`/`HERO`/`SIEGE_TOWER` |
| `0x0086FA87` | horde interface `+0x48`, pick a member |
| `0x008706DF` | horde interface `+0x180`, count members |
| `0x00872A6F` | `getHordeIface` - contain interface `+0x7C` |
| `0x00873F30` | horde interface `+0x2C`, assign a formation slot |
| `0x008A1FB8` | the batch loop's per-object template read |
| `0x008A2CC4` | `entry->total = Slots + 1` |
| `0x008A2DE7` | `ProductionUpdate::update`'s `exitObjectViaDoor` call |
| `0x008A2EE9` | its unconditional finish-the-exit call |
| `0x008A3948` | `QueueProductionExitUpdate` instance constructor |
| `0x008A399B` | the pending-horde field zeroed |
| `0x008A3BF0` | the rally-point setter's `[module+0x34] = 1` |
| `0x008A3BF8` | `ExitInterface` `+0x2C`, finish the exit |
| `0x008A3C0C` | its own `findObjectByID` on the pending horde |
| `0x008A3C1D` | the only clear of the pending-horde field |
| `0x008A3D32` | the container's move to the rally point |
| `0x008A3DD5` | `exitObjectViaDoor` |
| `0x008A402D` | the pending-horde read |
| `0x008A4036` | **the hook** |
| `0x008A4050` | `getHordeIface` call |
| `0x008A4066` | the bind block |
| `0x008A4169` | the lone-unit flag |
| `0x008A4223` | the obstacle hint |
| `0x008A4267` | the `KINDOF HORDE` test |
| `0x008A42A2` | the only write of the pending-horde field |
| `0x00C5B1F8` | horde interface vtable |
| `0x00C5B480` | `HordeContain`'s `ContainModuleInterface` vtable |
| `0x00C682C4` | `QueueProductionExitUpdate`'s `ExitInterface` vtable |
| `0x00DE412C` | `TheGameLogic` |
| `0x00DE4A40` | `TheThingFactory` |
