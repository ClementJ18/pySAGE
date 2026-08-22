# Combo hordes cannot be recruited

Static work against this repo's `game.dat` (RotWK `2.01.2614.37001`, ImageBase `0x400000`).
Nothing here has been read out of a running game yet — §7 says exactly which claim that leaves
open.

**The report.** A horde can be built out of several different objects by writing more than one
`InitialPayload` line in its `HordeContain` and placing the extra types in rank. Such *combo
hordes* work when a map places them. They cannot be recruited: a building asked to produce one
does not hand back the mix.

**Verdict up front.** Recruiting and placing a horde fill it by two completely different
mechanisms, and only one of them can read more than one payload.

- A horde placed by a map fills **itself**, in `HordeContain::onObjectCreated`, from the whole
  `InitialPayload` list.
- A horde produced by a building **skips that entirely** — `onObjectCreated` returns at its
  second instruction when the object has a producer — and is filled by the *building* instead,
  out of `ProductionUpdate::update`.
- The building's fill is driven by a production queue entry, and a queue entry has room for
  **one `ThingTemplate` and one count**. It asks the horde for that one template through a
  vtable slot whose implementation returns a name **only when the payload list has exactly one
  entry**, and the empty string otherwise.

So the mix is lost at the point where a list has to become a single template, and there is
nowhere downstream for it to survive.

## 1. `InitialPayload` really is a list

`InitialPayload` is a `TransportContain` field (inherited by `HordeContain`, `HorseHordeContain`,
`AODHordeContain`, `RiderChangeContain`, `SiegeEngineContain`). Its parse function is
`0x0086AF0A`, and the row's table offset is `0`, because the function stores by itself:

```
0086af0f  call 0xa3cef0                 ; __EH_prolog
0086af1f  call 0x42dc9f                 ; ebx = next token        (the template name)
0086af2a  call 0x42dbf5                 ; INI_NEXT_TOKEN_OR_NULL  (the count)
0086af37  call 0x42e9d7                 ; esi = INI_SCAN_INT      (absent -> esi = 1)
0086af50  call 0x4050e6                 ; AsciiString::set(&[ebp-0x14], ebx)
0086af55  mov  ecx, [ebp+0xc]           ; the ModuleData
0086af5c  add  ecx, 0xa4                ; &ModuleData.m_initialPayload
0086af62  mov  [ebp-0x10], esi          ; the count, beside the name
0086af65  call 0x86aed7                 ; push_back({name, count})
```

`ModuleData+0xA4` is four bytes and is constructed at `0x0086B464` by `0x00604340`, which
allocates a 16-byte node and points its `next` and `prev` at itself — an **MSVC `std::list`**
head. `0x0086AED7` links a fresh node in before that sentinel, so the list is `push_back` and
**declaration order is preserved**. Each node is `{next, prev, {AsciiString name, Int count}}`,
the payload starting at `node+8`.

So the data structure is fine. Every consumer below reads the same list.

| | |
|---|---|
| `TransportContainModuleData` size | `0x18C` |
| `m_initialPayload` | `ModuleData+0xA4`, `std::list<{AsciiString, Int}>` |
| `Slots` | `ModuleData+0x98` |
| module instance → its `ModuleData` | `module+0x04` |
| module instance → its owning `Object` | `module+0x08` |
| `ContainModuleInterface` sub-object | `module+0x11C` (its methods reach the `ModuleData` as `[ecx-0x118]`) |

## 2. The three readers of that list

A scan of `.text` for `+0xA4` displacements inside the contain modules finds exactly three, and
they are the whole story:

| address | what it is | how many payloads it can see |
|---|---|---|
| `0x0086A1FA` | `TransportContain::createPayload` | **all of them** — outer loop over the list, inner loop over each entry's count |
| `0x0086A688` | the build-cost / command-point walk | all of them |
| **`0x0087048F`** | vtable slot **`+0x24`** on the contain interface | **one, or none** |

`0x0086A1FA` is the correct one. It walks the list, and for each node reads the count at
`node+0xC`, resolves `node+8` through `TheThingFactory` (`0x006D1305`) and creates that many:

```
0086a204  mov  eax, [edi+4]             ; the ModuleData
0086a20a  mov  eax, [eax+0xa4]          ; the list head
0086a210  mov  esi, [eax]               ; first node
0086a212  cmp  esi, eax                 ; empty?
0086a229  lea  eax, [esi+8]             ; &payload
0086a22c  mov  ecx, [eax+4]             ; the count
0086a241  call 0x6d1305                 ; findTemplate(&payload.name)
      ...  create `count` objects, contain each ...
```

## 3. `0x0087048F` — where the mix is thrown away

This is the only function in the image that turns the payload list into a *single* answer, and it
refuses to answer at all when there is more than one entry:

```
0087048f  push ebp / mov ebp,esp / push ecx
00870493  mov  edx, [ecx-0x118]         ; the ModuleData
00870499  mov  ecx, [edx+0xa4]          ; the list head
0087049f  mov  eax, [ecx]               ; first node
008704a2  xor  esi, esi                 ; esi = 0
008704a4  cmp  eax, ecx
008704a9  je   0x8704c4                 ; empty  -> ""
008704ab  mov  eax, [eax]               ; walk, counting
008704ad  inc  esi
008704ae  cmp  eax, ecx
008704b0  jne  0x8704ab
008704b2  cmp  esi, 1
008704b5  jne  0x8704c4                 ; two or more -> ""      <-- the defect
008704b7  mov  eax, [edx+0xa4]
008704bd  mov  eax, [eax]
008704bf  add  eax, 8                   ; &first.name
008704c4: mov  eax, 0xdc62b8            ; the empty AsciiString
008704c9  ... *ret = eax ...
```

It sits at `+0x24` of the contain-module interface vtable, and **all three** horde vtables carry
this same implementation — `0x00C5B1F8`, `0x00C5BE98` and `0x00C5CFA8`, identified by the
neighbouring slot `+0x28`, which is the two-instruction `Slots` getter `0x0086C8AC`
(`return moduleData[0x98]`). So no horde class escapes it.

**It has exactly one caller in the whole binary**, and that caller is recruitment.

## 4. The producer gate — why a recruited horde does not fill itself

`HordeContain::onObjectCreated` is slot `+0x70` of the module vtable (`0x00C5B668`,
`0x00C5C2F8`, `0x00C5D460` — the same three classes). It begins:

```
00871b9b  mov  eax, 0xb9f7df / call 0xa3cef0    ; __EH_prolog
00871ba9  mov  esi, ecx                         ; this
00871bab  mov  eax, [esi+8]                     ; the Object
00871bae  mov  eax, [eax+0x78]                  ; Object::m_producerID
00871bb1  test eax, eax
00871bb3  jne  0x871d34                         ; produced -> return, do nothing at all
00871bb9  push ebx / push edi
00871bbb  call 0x86a1fa                         ; createPayload()  -- all payloads
00871bc0  ... formation update, strength trim, upgrade propagation ...
00871d34  ... epilogue ...
```

`Object+0x78` is `producer_id`, measured rather than inferred: on the recorded match in
`tests/sage_live/fixtures/match.snapshot.gz` it equals `parent_id` for **40 of 40** battalion
members ([`horde-formation-orphans.md`](horde-formation-orphans.md) §6). So the gate reads
"somebody built me", and the whole body — `createPayload` included — is skipped for every horde
that came out of a building.

That gate is not a bug on its own. It exists so the horde is **not** filled twice, because the
producing building is going to fill it. The bug is what the building can express.

**The strength trim below the gate is inert at creation.** The block at `0x00871C28` destroys
`(100 - [this+0x2A8])%` of the members, and `[this+0x2A8]` is initialised to `0x64` in the
`HordeContain` constructor at `0x00872972`. So a horde that runs this path loses nobody — which
matters, because §6's patch makes recruited combo hordes run it for the first time.

## 5. The production side — one template, one count

`ProductionUpdate::update` (`0x008A1B9F`) drives a queue entry. The fields that matter, on top of
the ones [`description-timers.md`](description-timers.md) §510 already records:

| field | meaning | established at |
|---|---|---|
| `entry+0x04` | kind — 1 unit, 2 upgrade, 3 hero | `0x008A1E08` |
| `entry+0x08` | the `ThingTemplate` to instantiate | `0x008A1FB8` |
| **`entry+0x20`** | **how many objects this entry makes** | `0x008A1FA3` |
| **`entry+0x24`** | **how many it has made** | `0x008A1FA6` |
| `entry+0x34` | "already switched to member-filling" | `0x008A1E50` |

`queueCreateUnit` starts every entry at one object:

```
008a12e1  and  dword [esi+0x24], 0
008a12ec  mov  dword [esi+0x20], 1
```

and the batch loop makes `entry+0x20 - entry+0x24` copies of the one template at `entry+0x08`:

```
008a1fa3  mov  eax, [ebx+0x20]
008a1fa6  sub  eax, [ebx+0x24]
008a1fad  test eax, eax
008a1fb2  jle  0x8a2ec4                 ; done -> unlink and free the entry
008a1fb8  mov  ecx, [ebx+8]             ; the template, for every one of them
```

So the first object a horde entry produces is the **container**. Immediately after it exists, the
entry is re-aimed at the container's members:

```
008a2c6a  mov  ecx, [edi+0x258]         ; the produced object's contain module
008a2c76  call [eax+0x7c]               ; -> the horde interface, NULL for a non-horde
008a2c82  cmp  [ebp-0x18], 0
008a2c86  je   0x8a2cd6
008a2c91  call [eax+0x24]               ; <-- 0x0087048F, the single-payload name
008a2ca2  call 0x6d1305                 ;     findTemplate(that name)
008a2cbb  call [eax+0x28]               ;     Slots
008a2cbe  cmp  [ebp-0x44], 0
008a2cc2  je   0x8a2cd6                 ; no template -> the entry is never re-aimed
008a2cc7  inc  eax                      ; Slots + 1
008a2cc8  and  dword [ebx+0x28], 0
008a2ccc  mov  [ebx+8], ecx             ; entry->template = the payload
008a2ccf  mov  [ebx+0x20], eax          ; entry->total    = Slots + 1
008a2cd2  mov  byte [ebx+0x34], 1
```

`entry+0x24` is already 1 (the container), so `Slots` more objects follow, all of the one
template. Two things are worth writing down beyond the bug itself:

- the member **count comes from `Slots`, not from the `InitialPayload` counts**, even for a
  single-payload horde; and
- for a combo horde `findTemplate("")` is `NULL`, the branch at `0x008A2CC2` is taken, the entry
  keeps `total == 1 == made`, and `0x008A2EC4` unlinks and frees it.

## 6. What the player sees, and what this predicts

The chain above predicts that a recruited combo horde arrives as **a container with zero
members** — not as a full-size horde of the first payload's unit. Those are different symptoms
and it is worth being explicit about which one the code says.

A full-size horde of the first unit is what you would get if `0x0087048F` returned the first
entry instead of the empty string; it does not. An empty `HordeContain` is also not a harmless
outcome: [`horde-formation-orphans.md`](horde-formation-orphans.md) §4 shows that an empty horde
is still a legal attack target and that `resolveAttackTarget` hands back `NULL` for it, which
every caller reads as "cannot be attacked".

Either way the fix is the same, because both symptoms have the same cause: the recruited horde is
filled through a path that cannot carry more than one template.

## 7. What is not established

Everything above is static. Two things would move from "read" to "measured" with one live
session (`sage_live`, a barracks, a two-payload horde):

1. **The symptom.** §6 predicts an empty container. The report says a full horde of the first
   unit. If the game shows the latter, something between `0x008A2C91` and the batch loop is doing
   more than this reading accounts for, and §5 needs revisiting — the *cause* in §3 and §4 would
   still stand, since `0x0087048F` and the producer gate are unambiguous.
2. **The trim block at `0x00871C28`.** `[this+0x2A8]` is `100` out of the constructor and no
   other site writes it, so the patch below should destroy nobody. That is a static reading of a
   block that has never run on a produced horde.

## 8. The patch

[`combo_horde_recruitment.py`](../patches/combo_horde_recruitment.py) — `combo-horde-recruitment`.

Six bytes at `0x00871BAB` become a `call` into a cave. The cave computes the same
`Object::m_producerID` the two replaced instructions did, and returns it **unless** the payload
list holds two or more entries, in which case it returns `0`. The stock
`test eax, eax / jne` at `0x00871BB1` is left exactly as it is, so a combo horde now falls
through into `createPayload` and fills itself from every `InitialPayload` line, the way a
map-placed one always has.

```asm
    mov  eax, [esi+8]         ; the Object
    mov  eax, [eax+0x78]      ; m_producerID
    test eax, eax
    je   .done                ; no producer -> stock, and eax is already 0
    mov  ecx, [esi+4]         ; the ModuleData
    mov  ecx, [ecx+0xa4]      ; the InitialPayload list head
    mov  edx, [ecx]           ; first node
    cmp  edx, ecx
    je   .done                ; empty list -> stock skip
    mov  edx, [edx]           ; second node
    cmp  edx, ecx
    je   .done                ; exactly one -> stock skip
    xor  eax, eax             ; two or more -> "no producer", fill myself
.done:
    ret
```

**Why the gate and not `0x0087048F`.** Making the getter return the first entry would recruit
`Slots` copies of one unit — the wrong mix, delivered confidently. Carrying the whole list
through production instead would mean widening a queue entry to hold a list and teaching the
batch loop at `0x008A1FB8` to pick a template per index; that is a much larger patch for the same
end state, and its only advantage is cosmetic (members would leave the door one at a time rather
than appearing formed at it).

**Why it is unconditional.** It can only change objects that are (a) produced by a building and
(b) declare two or more `InitialPayload` lines — which today come out empty. There is no data in
any shipping mod for it to regress, so it costs no keyword.

**Registers.** The cave clobbers `eax`, `ecx` and `edx`. At `0x00871BAB` `esi` is `this`, `ebx`
and `edi` are still the caller's (they are pushed at `0x00871BB9`, after the branch), and `ecx`
is a dead copy of `this` — every later use reloads it. The cave has no frame of its own, so it is
transparent to the `__EH_prolog` frame the function set up at `0x00871B9B`.

**Every peer must run the same patched binary.** Creating objects is logic state, so a patched
and an unpatched client diverge the first frame anybody recruits a combo horde, and replays do
not cross. Same requirement as `rebuild-hole-construction` and `production-condition`.

**Composition.** One cave, allocated with `allocate_section`, and six bytes rewritten at an
address no other bundled patch touches. Nothing it reads is a structure another patch rewrites.
Order-independent with everything.

## 9. Addresses

| address | what |
|---|---|
| `0x0086AF0A` | `InitialPayload`'s INI parse function |
| `0x0086AED7` / `0x0086AEB2` | the payload list's `push_back` |
| `0x00604340` | the list head's constructor |
| `0x0086A1FA` | `TransportContain::createPayload` — reads every payload |
| `0x0086A688` | the build-cost walk — reads every payload |
| **`0x0087048F`** | **the single-payload name getter, contain-interface vtable `+0x24`** |
| `0x0086C8AC` | the `Slots` getter, vtable `+0x28` |
| `0x00875C93` | the horde-interface getter, vtable `+0x7C` |
| **`0x00871B9B`** | **`HordeContain::onObjectCreated`, module vtable `+0x70`** |
| **`0x00871BAB`** | **the producer gate this patch rewrites** |
| `0x00871BBB` | its `call` to `createPayload` |
| `0x00871C28` | the strength trim; `0x00872972` initialises its percent to 100 |
| `0x008A1B9F` | `ProductionUpdate::update` |
| `0x008A12E1` | `queueCreateUnit` — `entry+0x24 = 0`, `entry+0x20 = 1` |
| `0x008A1FA3` | the batch loop's `total - made` test |
| **`0x008A2C91`** | **the only call to `0x0087048F` in the image** |
| `0x008A2CC4` | the queue-entry rewrite |
| `0x006D1305` | `ThingFactory::findTemplate` |
| `0x00C5B1F8` / `0x00C5BE98` / `0x00C5CFA8` | the three horde contain-interface vtables |
| `0x00C5B668` / `0x00C5C2F8` / `0x00C5D460` | their `onObjectCreated` slots |
