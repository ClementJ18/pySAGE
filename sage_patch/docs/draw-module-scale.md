# `Scale`, `Offset` and `AngleOffset` on a model draw module

RotWK 2.01 `game.dat`, ImageBase `0x400000`. Static recovery only - **nothing here has been run in
a game yet**; §8 is what a first session should look at. Shipped as
[`../patches/draw_module_scale.py`](../patches/draw_module_scale.py).

**The finding in one sentence.** An object's `Scale` reaches its models through one getter the model
draw modules call from 19 places, and every model draw positions what it draws through one helper
called from five - and all 24 of those places already hold the calling module in a register, so a
per-module scale, offset and rotation can be applied there and nowhere else.

**Why they need different sites.** A scale can be baked into a model when the render object is
created, and that is what the engine does with the object's `Scale` (§2). A position and a facing
cannot: nothing in the creation path takes either, so both have to go into the matrix the module
hands its render object (§4).

## 1. Where the object's scale lives

`Scale` is row 93 of the `Object` field table at `0x00DA3DF8`: `INI::parseReal` into
`ThingTemplate+0x4F0`. The drawable copies it once, in its constructor:

```
00679fd7  movss xmm0, [edi+0x4f0]      ; edi = the ThingTemplate
00679fe2  movss [esi+0x200], xmm0      ; esi = the Drawable
```

The only other stores to a float at `+0x200` in `.text` are `0x0068AE8C`, a setter with no callers,
and `0x0066298C`, which belongs to a variant type reached through thirteen vtables and keeps its type
tag at `+0x1FC`. A drawable's scale is fixed when it is built.

It is read back through `Drawable::getScale` at `0x00478180`:

```
00478180  d9 81 00 02 00 00   fld  dword [ecx+0x200]
00478186  c3                  ret
```

## 2. How a model draw uses it

The model draws never scale a transform. Their per-frame draw (`W3DScriptedModelDraw` vtable slot
11, `0x004C72BE`) builds the matrix and hands it to `renderObj->vt[0x54]` at `0x004C76DE` as it is.
The scale goes in earlier, when the render object is created:

```
004c4829  mov   ecx, edi               ; the Drawable
004c482b  call  0x478180               ; getScale
004c4830  push  ecx
004c4831  fstp  dword [esp]            ; the scale, as the second argument
004c4834  push  ebx                    ; the model name
004c4835  call  0x536310               ; create the render object
```

`0x00536310` is cdecl. It refuses a name that starts with `#` and compares `|scale - 1.0|` against
an epsilon (`0x005363A8`) to decide whether the model needs a scaled copy - the scale is baked into
the geometry.

The same number goes to `0x004C2F4E`, which validates a condition state's bone cache (the latch is
bit `0x10` of `+0xF4`, tested at `0x004C2F5D`) against the module's `ExtraPublicBone` list at
`ModuleData+0x30`. Pristine bone positions are therefore recorded at the scale the model was built
at, and anything that asks the module where a bone is gets a scaled answer.

The contrast is the draw class with vtable `0x00BDF700`, whose slot 11 (`0x004B135C`) *does* scale a
transform: it multiplies the matrix's 3×3 by `Drawable+0x200` and calls `renderObj->vt[0x174]`. It
is not a model draw and nothing below touches it.

## 3. The 22 callers

A byte scan of `.text` for `call rel32` to `0x00478180` finds exactly 22, and linear disassembly of
each enclosing function agrees. The module layout is the one
[`raised-wall-mesh-removal.md`](raised-wall-mesh-removal.md) §2 records: vtable at `+0`,
`ModuleData *` at `+4`, `Drawable *` at `+8`, the `ObjectDrawInterface` sub-object at `+0xC`.

| function | what | sites | `ModuleData` at the call |
|---|---|---|---|
| `0x004C451D` | `W3DModelDraw::setModelState`; `mov esi, ecx` at `0x004C452E` | `0x004C4661` `0x004C482B` `0x004C48E2` `0x004C4AB7` `0x004C4ADB` `0x004C4B3D` `0x004C4C9E` `0x004C4DFF` | `[esi+4]` |
| `0x0047A0AD` | `W3DHordeModelDraw`'s own copy of it; `mov esi, ecx` at `0x0047A0C4` | `0x0047A181` `0x0047A30A` `0x0047A3CA` `0x0047A52A` `0x0047A54E` `0x0047A5AE` `0x0047A68F` `0x0047A77E` | `[esi+4]` |
| `0x004C34A2` | interface slot 6, entered on `module+0xC` | `0x004C34E4` | `edi`, loaded by `mov edi, [esi-8]` at `0x004C34DC` |
| `0x004C3731` | interface slot 3, entered on `module+0xC`; `mov edi, ecx` at `0x004C3746` | `0x004C3789` | `[edi-8]` |
| `0x004C6514` | per-frame bone update, called only from slot 11 (`0x004C7790`); `mov ebx, ecx` at `0x004C6525` | `0x004C6909` | `[ebx+4]` |
| `0x004B1810` | slot of vtable `0x00BDF6F8` - not a model draw | `0x004B1883` | - |
| `0x004CE793` | slot `0x00BE3258` of an unrelated vtable - not a model draw | `0x004CE7ED` | - |
| `0x004D12FA` | called from `0x004D341C` with the drawable, not from a module | `0x004D137A` | - |

In every model-draw row, the register named is not written between the instruction cited and the
call. The eight `setModelState` sites each sit beside a read of the same module (`[esi+0x28]`,
`[esi+0x50]` or `[esi+4]+0x30`), which is the cheap way to see it.

The first five functions read `W3DModelDrawModuleData` fields directly - `+0x30`
`ExtraPublicBone`, `+0x15F` `HighDetailOnly`, the containers at `+0x70`, `+0x7C` and `+0x8C` - so
they are model-draw methods by construction. The two interface methods each sit in exactly three
interface vtables (`0x004C3731` at `0x00BE1ADC`, `0x00BE1E64`, `0x00BE3B84`; `0x004C34A2` at
`0x00BE1AE8`, `0x00BE1E70`, `0x00BE3B90`), the last being `W3DScriptedModelDraw`'s `0x00BE3B78`.

## 4. Where a model draw positions what it draws

Every model draw hands its render object a matrix through the same two steps: a call to the helper
at `0x004B686D`, then `renderObj->vt[0x54]` (`Set_Transform`). The helper is
`__thiscall(Matrix3D *)`, `ret 4`; it overrides the matrix from another module's bone when
`ModuleData+0xA4` says the module is attached to one (`0x004B6880`), and otherwise leaves the
matrix exactly as the caller filled it.

It has **five callers, and they are the five places the family positions anything**:

| call | the module is in | the matrix |
|---|---|---|
| `0x004B79AA` | `esi` | `[ebp-0x38]` |
| `0x004B7CD8` | `esi` | `[ebp-0x58]` |
| `0x004B8A14` | `esi` | `[ebp-0x38]` |
| `0x004B988A` | `ebx` | `[ebp-0xA4]` |
| `0x004C76D0` | `ebx` | `[ebp-0x50]`, the per-frame draw |

Each is `lea <reg>, <the matrix>; push <reg>; mov ecx, <the module>; call`, so a replacement call is
entered with the module in `ecx` and the matrix still on the stack at `[esp+4]` - no frame pointer
of the caller's needs to be understood.

The last of the five is in `0x004C72BE`, the per-frame draw, which is **slot 11 of five model draw
vtables** (`0x00BDC83C`, `0x00BE0014`, `0x00BE1BC4`, `0x00BE1F4C`, `0x00BE3C6C`) and is called
directly by `W3DTruckDraw` (`0x004CC008`) and `W3DTankDraw` (`0x004CDECE`) from their own slot 11.
So all seven modules of §5 reach it.

`Matrix3D` is three rows of four floats: the rotation in the first three of each row, the
translation in the fourth (`+0x0C`, `+0x1C`, `+0x2C`). `0x004B135C` - the one draw class that
scales a transform - multiplies exactly the nine rotation entries and leaves those three alone,
which is what fixes the layout.

## 5. The model draw family

The `ModuleFactory` registrations (from `0x00464B4A`: the name, then three code pointers pushed as
`push <unidentified>`, `push newModuleData`, `push newModule`, then `call 0x006570FE`) and each
`newModuleData` thunk give:

| module | `newModuleData` | `sizeof` | ctor | `buildFieldParse` | own table (its `push`) |
|---|---|---|---|---|---|
| `W3DScriptedModelDraw` | `0x004640CD` | `0x188` | `0x004C85E9` | `0x004C893A` | - |
| `W3DHordeModelDraw` | `0x004646B2` | `0x1C4` | `0x00478289` | `0x00478C74` | `0x00BDCAA0` (`0x00478C7A`) |
| `W3DQuadrupedDraw` | `0x00464A0F` | `0x198` | `0x004649B9` | `0x004C97A1` | `0x00BE1A80` (`0x004C97B1`) |
| `W3DSupplyDraw` | `0x00464258` | `0x18C` | `0x004CA6F5` | `0x004CA601` | `0x00BE1E38` (`0x004CA611`) |
| `W3DTruckDraw` | `0x004642E7` | `0x1F0` | `0x004CA9B6` | `0x004CA91B` | `0x00BE22B8` (`0x004CA92B`) |
| `W3DTankDraw` | `0x00464376` | `0x19C` | `0x004CDEDA` | `0x004CD78A` | `0x00BE2968` (`0x004CD79A`) |
| `W3DSailModelDraw` | not read | not read | runs the base at `0x004CFF2D` | `0x004CFF67` | `0x00BE3B30` (`0x004CFF77`) |

`0x004C893A` is `push 0; push 0x00BE1320; call 0x0042B8D7` (the append that adds a table to the
reader), and every derived `buildFieldParse` calls or jumps to it - so the 57-row table at
`0x00BE1320` is parsed by all seven, alongside the derived module's own. The base constructor
`0x004C85E9` has exactly seven callers, one per module above. The base `ModuleData` vtable
`0x00BE0D40` is referenced only by that constructor (`0x004C860D`) and the destructor
(`0x004C82EB`), so there is no copy constructor that could skip a field.

Every derived class starts its own fields at `0x188`, so the base structure cannot grow.

## 6. The hole

The base table's rows around the end of the structure:

| keyword | offset | parser |
|---|---|---|
| `BirthFadeTime` | `+0x150` | `0x0073A429` (a duration) |
| `BirthFadeAdditive` | `+0x154` | `0x0042E558` `INI::parseBool` - one byte |
| `StaticSortLevelWhileFading` | `+0x158` | `0x0042EC5E` `INI::parseInt` |
| `ZWriteDisableOverride` | `+0x15C` | `INI::parseBool` |

`+0x155..+0x157` is alignment padding, and no row names an offset inside it. A displacement scan of
`0x0046F000..0x004D3000` for `+0x154..+0x157` finds only the constructor's store and a byte read
(`0x004C09F6`, `mov al, [eax+0x154]`). The three dword reads of `+0x154` elsewhere in the image
(`0x004A0682`, `0x004A0786`, `0x004A3073`) are in getters and loops over other structures, outside
every model draw function.

The constructor never writes the padding, and `operator new` does not zero:

```
004c8604  xor   ebx, ebx
          ...                          ; every default below is stored from ebx
004c8730  mov   byte [esi+0x154], bl   ; 88 9e 54 01 00 00
```

## 7. The patch

Three bytes cannot hold a scale, an offset and an angle, so they hold a **24-bit index** into a
table of records in the cave - `{scale, offset x/y/z, a turn flag, cos, sin}`, `0x20` bytes each.
The three keywords share a record: whichever parses first allocates it, the others find it. Index
zero is "declared none of them", which is what the constructor leaves.

1. **`0x004C8730`: `88` -> `89`.** The store becomes `mov [esi+0x154], ebx` and clears
   `BirthFadeAdditive` and the index together, for all seven modules - `operator new` does not.
2. **`0x004C8940`: the table.** The `push` is repointed at a copy in the cave - the live rows, then
   one row each for `Scale`, `Offset` and `AngleOffset`, then a terminator. All three name the same
   `ModuleData` offset because what they write there is the index.
3. **The parsers.** Each calls an engine parser into a stack slot and then copies into the record:
   `INI::parsePositiveNonZeroReal` (`0x0042ED1C`) for the scale, which stores and then throws the
   engine's INI error when the value is not above zero (`fldz / fcompi st(1) / jb` at `0x0042ED3D`);
   `INI::parseCoord3D` (`0x0042F247`) for the offset; and the plain `INI::parseReal` (`0x0042ED00`)
   for the angle, because a negative angle turns the other way and zero is a legitimate "no turn".
   The allocator writes the index as a word at `+0x155` and a byte at `+0x157`, never touching the
   `Bool` at `+0x154`, and starts a fresh record at scale `1.0` - the section is zero-filled, so a
   module declaring only one of the other two would otherwise collapse to nothing.

   **`AngleOffset` costs no trigonometry per frame.** Its parser turns the degrees into radians
   (`fldpi`, then `fidiv` by 180) and runs `fsincos` **once**, storing the cosine and the sine in
   the record and setting its flag. A turn about the up axis is all the keyword offers, which is
   what makes it that cheap: three floats and a matrix composition would be needed for a full
   orientation, and lining an animation up needs one angle.
4. **The 19 `getScale` calls** are retargeted, five bytes for five, at four stubs that differ only
   in the load:

```
fld   dword [ecx+0x200]     ; getScale, verbatim
push  eax
mov   eax, <ModuleData>     ; [esi+4] / edi / [edi-8] / [ebx+4]
mov   eax, [eax+0x154]
shr   eax, 8                ; the record index
je    .unset
shl   eax, 4
fmul  dword [eax+<records-0x10>]
.unset:
pop   eax
ret
```

The stub preserves every general register, as the getter does, and returns with one value on the
x87 stack, as the getter does. None of the 19 callers reads flags across the call.

5. **The five transform calls** are retargeted at one stub, which runs the helper exactly as the
   call site did and then moves and turns the matrix the helper settled:

```
push  esi
push  edi                   ; both callee-saved, so they survive the helper
mov   esi, [esp+0xc]        ; the matrix the caller pushed
mov   edi, ecx              ; the module
push  esi
call  <0x004B686D>          ; ret 4: the helper pops that
mov   eax, [edi+4]          ; the ModuleData
mov   eax, [eax+0x154]
shr   eax, 8
je    .done
shl   eax, 5
add   eax, <records-0x20>
<three rows of: translation += rotation . offset>
cmp   dword [eax+0x10], 0   ; did it declare an angle?
je    .done
sub   esp, 8                ; two scratch dwords
<three rows of: (x, y) -> (x*cos + y*sin, y*cos - x*sin)>
add   esp, 8
.done:
pop   edi
pop   esi
ret   4                     ; as the helper does
```

Each offset row is `fld ox / fmul m[row][0] / fld oy / fmul m[row][1] / faddp / fld oz /
fmul m[row][2] / faddp / fadd t / fstp t`, two x87 slots deep and balanced. Multiplying by the
rotation is what puts the offset in the **object's own frame**, so it turns with the unit; a raw add
to the translation would point it north regardless of facing.

Each turn row copies the row's first two entries to the stack first, because both answers read both
originals; the third entry is what a turn about the up axis does not touch, and is never written.
The turn is applied **after** the offset and only to the rotation, so the two are independent knobs:
the offset is measured in the object's frame whatever the angle says, and the model turns about the
point the offset put it at rather than swinging around the object.

## 8. Unverified

- **Nothing has run in a game.**
- **What else reads the matrix after the helper.** The offset is added to the matrix each of the
  five sites is about to hand to `Set_Transform`, so anything that asks the render object where it
  or its bones are afterwards sees the offset, and anything reading the drawable's own transform
  does not. Which of the two a given effect uses has not been traced case by case.
- **The offset is not scaled.** It is added in world units after the rotation, so a module with
  both keywords is scaled about its own origin and then displaced by the offset as written. Whether
  a modder expects the offset to scale with the model is a design question a first session should
  answer.
- **Which way the angle turns.** The matrix is multiplied by a rotation about the up axis, so a
  positive angle turns one way and a negative one the other; which of the two is "left" has not been
  seen on screen, and a first session should try `AngleOffset = 90` and read it off. The turn is
  about the module's origin - the object's position - not the model's visual centre, so an
  off-centre model swings rather than spins. Roll and pitch are deliberately not offered: lining an
  animation up needs one angle, and one angle is four multiplies a row.
- **Whether a scaled bone cache reaches logic.** In the Generals lineage, weapon launch offsets come
  from the pristine bone cache. If RotWK's do, `Scale` on a unit's draw module moves where its
  projectiles leave from, exactly as the object's `Scale` does - which would make the keyword
  simulation state. Not traced in this build.
- **`0x004C6514`'s exact job.** It is named from its shape: called from the per-frame draw, it walks
  the module's attachment lists and scales a bone transform by `getScale` before using it. It
  receives the factor like the other 18, which keeps whatever it positions consistent with the model.
- **Horde instancing.** `W3DHordeModelDraw` compares two members' drawable scales (`0x00478755`,
  `0x00479E4F`). Those compares read the drawable, not the module, and members of one template
  share one `ModuleData`, so they still agree.
- **Shared `ModuleData`.** A draw module inherited by a `ChildObject` with a different object
  `Scale` already bakes the first object's scale into the shared bone cache in the stock game; the
  factor does not change that.

## 9. Address table

| address | what |
|---|---|
| `0x00478180` | `Drawable::getScale` - `fld [ecx+0x200]; ret` |
| `0x00679FD7` / `0x00679FE2` | the `Drawable` constructor copying `ThingTemplate+0x4F0` to `+0x200` |
| `0x00536310` | cdecl render-object create, taking the scale |
| `0x004C2F4E` | condition-state bone-cache validation, taking the scale |
| `0x004C451D` / `0x0047A0AD` | `setModelState`, base and horde |
| `0x004C34A2` / `0x004C3731` | interface slots 6 and 3 |
| `0x004C6514` | per-frame bone update, from slot 11 at `0x004C7790` |
| `0x004C72BE` | `W3DScriptedModelDraw` slot 11, the per-frame draw |
| `0x00BE1320` | the shared model draw field table, 57 rows; one reference, `0x004C8940` |
| `0x004C893A` | its `buildFieldParse` |
| `0x0042B8D7` | append a field table to the reader |
| `0x004C85E9` | `W3DModelDrawModuleData` constructor; `0x004C8730` the `BirthFadeAdditive` default |
| `0x00BE0D40` | `W3DModelDrawModuleData` vtable |
| `0x004B686D` | the transform helper every model draw runs before `Set_Transform`; `ret 4` |
| `0x004B79AA` `0x004B7CD8` `0x004B8A14` `0x004B988A` `0x004C76D0` | its five callers - §4 |
| `0x004CC008` / `0x004CDECE` | `W3DTruckDraw` / `W3DTankDraw` calling the shared per-frame draw |
| `0x0042ED1C` | `INI::parsePositiveNonZeroReal` |
| `0x0042F247` | `INI::parseCoord3D`; the `X`/`Y`/`Z` tokens at `0x00BD43F8`/`F4`/`F0` |
| `0x0042ED00` | `INI::parseReal` - the angle's parser, which accepts zero and negatives |
| `0x004B1883` `0x004CE7ED` `0x004D137A` | the three `getScale` callers outside the family |
