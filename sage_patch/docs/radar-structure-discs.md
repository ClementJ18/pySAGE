# Minimap blips for structures

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000`.

**Verdict:** there is no INI field for minimap blip size. The blip painter picks one of three
shapes from the template's `KindOf`. Only `WALL_SEGMENT` and `COMMANDCENTER` get anything scaled
to the object. Every other object, every ordinary building included, gets a fixed 2x2 dot. The
`COMMANDCENTER` circle is also hollow. `radar-structure-discs` sends every object whose radar
priority is `STRUCTURE` down the `COMMANDCENTER` branch, and fills the circle.

- **Cost:** one 6-byte `call` hook, two re-aimed `call`s, an optional one-byte minimum radius and a 102-byte cave (`.rdrdsc`). No INI
  change.
- **Risk:** low. Presentation only: the painter runs on the client, draws into the radar surface
  and changes no game state.
- **Status:** built ([`patches/radar_structure_discs.py`](../patches/radar_structure_discs.py)),
  and both caves are emulated against the engine's own bytes in
  `tests/sage_patch/test_radar_structure_discs.py`. **Not runtime-verified.**

## 1. The observation

In Edain, settlement buildings (farms, lumber mills, Lorien's Mallorn tree) show on the minimap
as the same small dot however large they are. Raising one building's `GeometryMajorRadius` to 250
left the dot unchanged. Adding `WALL_SEGMENT` to its `KindOf` then drew a large patch. The
fortress, a `COMMANDCENTER`, has always drawn larger.

## 2. The painter

The radar draw loop walks the radar object list. For each entry `esi` is the `RadarObject`
(`+4` the `Object*`, `+0xC` the colour, `+8` the next entry). The per-object body opens at
`0x0044fa61`:

```
0044fa73  mov  edi, [esi+4]            ; Object*           <- RADAR_BLIP_KINDOF_SEQUENCE
0044fa76  mov  eax, [edi+4]            ; ThingTemplate*
0044fa79  mov  ebx, [eax+0x108]        ; KindOf dword 0    <- hooked (RADAR_BLIP_KINDOF_LOAD)
0044fa7f  push [ebp-0x28]
0044fa82  shr  ebx, 0x11
0044fa85  mov  ecx, edi
0044fa87  and  bl, 1                   ; bl = COMMANDCENTER (KindOf index 17)
0044fa8a  call 0x0068d8f7              ; shroud / visibility
0044fa98  mov  eax, [edi+4]
0044fa9b  mov  eax, [eax+0x11c]
0044faa1  shr  eax, 0x1d
0044faa4  and  al, 1                   ; WALL_SEGMENT (KindOf index 189)
0044faa8  mov  [ebp-0xf], al
```

`HERO` (`tmpl+0x113` bit `0x04`, at `0x0044fb4e`) draws a hero icon. Past that, the shape is
chosen in this order:

| test | address | shape |
|---|---|---|
| `[ebp-0xf]` (`WALL_SEGMENT`) | `0x0044fc12` | `0x0044d814`: every radar pixel inside the bounding square that the geometry contains, alpha `0xFF` inside and `0x80` on the edge |
| `bl` (`COMMANDCENTER`) | `0x0044fc49` | a circle of radius `floor(boundingRadius * scale + 0.5)`, at least 2 |
| neither | `0x0044fd50` | four pixels: `(x, y)`, `(x-1, y)`, `(x-1, y-1)`, `(x, y-1)` |

`boundingRadius` is `Object+0xb8`, from the `GeometryInfo` at `Object+0xa8`. Only these two
branches read it, which is why a radius change alone did nothing.

## 3. Why the circle is hollow

The `COMMANDCENTER` branch calls `0x006e0ae4` to rasterise the circle into a vector of 12-byte
spans `{row, a, b}`. Then it makes two passes:

```
0044fcb3  mov  esi, [edi]              ; row                <- RADAR_CIRCLE_SPAN_LOOP
0044fcb5  lea  eax, [ebp-0x14]         ; &surface
0044fcb8  push eax / push [edi+8] / push [edi+4]
0044fcbf  call 0x0044de11              ; (a, b, &surface)
0044fcc4  mov  esi, [ebp-0x24]
0044fcc7  sub  esi, [edi]              ; the row mirrored about the centre
0044fccc  push eax / push [edi+8] / push [edi+4]
0044fcd3  call 0x0044de11
0044fcd8  ...                          ; ebx := the span with the largest row
0044fce2  add  edi, 0xc
0044fce5  cmp  edi, [ebp-0x54] / jne 0x0044fcb3
0044fcea  ...                          ; second pass: every x of ebx's span, at its row and mirror
```

`0x0044de11` (`RADAR_PLOT_SPAN_ENDS`) plots only `(a, row)` and `(b, row)`, each behind the
`[0, 128)` bounds check at `0x0044dda3`, in the colour at `0x00dc7738`. The second pass fills
only the two extreme rows. So the result is an outline. Nothing else calls `0x0044de11`.

## 4. The patch

1. `0x0044fa79` becomes `call <kindof>; nop`. The cave performs the replaced load, then calls
   `Object::getRadarPriority` (`0x0068ebe9`, which returns the template byte at `+0x600`) with
   `ecx = edi`. When it answers `STRUCTURE` (2), the cave sets bit 17 in `ebx`. The painter's own
   `shr / and` then selects the circle. `eax`, `ecx` and `edx` are preserved.
   `getRadarPriority` preserves `esi`, `edi` and `ebx`.
2. Both calls at `0x0044fcbf` and `0x0044fcd3` are re-aimed at `<fill>`. It has the same
   `cdecl (a, b, surface)` contract with the row in `esi`, but it plots every `x` from `min(a, b)`
   to `max(a, b)`, each through the same bounds check and `DrawPixel` (`0x005165e0`,
   `__thiscall`, callee-cleaned).

The results:
- Filled circles for every `STRUCTURE` object and for every `COMMANDCENTER`.
- `WALL_SEGMENT` objects keep their footprint, because that test comes first.
- `UNIT`, `NOT_ON_RADAR`, `LOCAL_UNIT_ONLY` and `INVALID` priorities are untouched.

The values come from the engine's name table at `0x00da3b24`: `INVALID` 0, `NOT_ON_RADAR` 1,
`STRUCTURE` 2, `UNIT` 3, `LOCAL_UNIT_ONLY` 4. That's the Generals order. A template that leaves
`RadarPriority` unset (`INVALID`) is reported as `STRUCTURE` by the fallback in
`getRadarPriority` when it is `KindOf CAPTURABLE` (index 49, `tmpl+0x10e` bit `0x02`), or when its
contain module's vtable `+0x10` answers yes. So Edain's `GondorFarm`, which sets no priority,
counts as a structure here too. Otherwise the fallback reports `INVALID`, which draws as a dot.

3. Optionally, `--min-radius N` rewrites the `push 2` at `0x0044fc57` (its imm8 is
   `RADAR_CIRCLE_MIN_RADIUS`). It's the smallest radius the painter allows, popped into `ebx` and
   compared against the rounded radius.

The minimum matters more than the scale. Read from a running Edain skirmish, `TheRadar+0x24`
(world units per radar pixel, `extent * 1/128`) was 29.7 by 27.3. At that scale a Mallorn tree
(radius 40) rounds to 1 pixel. So every ordinary building sits on the minimum, which is a disc
about 5 pixels wide at the stock 2. A fortress (radius 140) rounds to 5 and grows past a raised
minimum only when it's larger.

## 5. Addresses

| constant | VA | what |
|---|---|---|
| `RADAR_BLIP_KINDOF_SEQUENCE` | `0x0044fa73` | the KindOf test, asserted in full |
| `RADAR_BLIP_KINDOF_LOAD` | `0x0044fa79` | the hooked `mov ebx, [eax+0x108]` |
| `RADAR_CIRCLE_RADIUS` | `0x0044fc51` | the radius computation, asserted in full |
| `RADAR_CIRCLE_MIN_RADIUS` | `0x0044fc58` | the minimum radius, the `push`'s imm8 (stock 2) |
| `RADAR_CIRCLE_SPAN_LOOP` | `0x0044fcb3` | the first circle pass, asserted in full |
| `RADAR_CIRCLE_SPAN_CALLS` | `0x0044fcbf`, `0x0044fcd3` | the re-aimed calls |
| `RADAR_PLOT_SPAN_ENDS` | `0x0044de11` | the stock ends-only row routine, left in place |
| `RADAR_PIXEL_IN_BOUNDS` | `0x0044dda3` | `(x, y)` in `[0, 128)` |
| `RADAR_BLIP_COLOUR` | `0x00dc7738` | the current blip colour |
| `SURFACE_DRAW_PIXEL` | `0x005165e0` | `SurfaceClass::DrawPixel` |
| `OBJECT_GET_RADAR_PRIORITY` | `0x0068ebe9` | `Object::getRadarPriority` |
