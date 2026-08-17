# The infantry light environment, and the KindOf test that gates it

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), read statically from a
ROTWK `game.dat`. `.text` is untouched by every cave-adding patch in this package, so every address
below is also a stock address.

**Built.** This shipped as [`infantry-lighting`](../patches/infantry_lighting.py). The map-side
measurements at the end were taken with [`sage_map`](../../sage_map) over the shipped `Maps.big`
and `____edain_maps.big`.

---

## The symptom

A unit whose `KindOf` says `CAVALRY` renders noticeably darker than the infantry beside it, and
adding `INFANTRY` to the same `KindOf` line fixes it. Nothing in the unit's art, armor, house
colour or shadow settings is involved: the two units are being drawn with **different lights**.

## Verdict up front

The engine keeps **two light environments for drawables** and selects between them with a single
`KindOf` bit test that names `INFANTRY` and `MONSTER` and nothing else. Everything that fails that
test is lit as scenery. The fix is one immediate byte at each of two sites.

---

## 1. A map carries three light sets, not two

`GlobalLighting` in the `.map` gives every time of day **three** sets of three lights (a sun and two
accents), one set each for terrain, objects and infantry. The reader is at `0x004AC580`; it takes
`TheGlobalData` from `[0x00DE4364]` and writes into three bases, `0x6C` apart per time of day
(3 lights x 9 floats):

| set | base | span |
|---|---|---|
| terrain | `TheGlobalData+0x1AC` | 4 x `0x6C` |
| objects | `TheGlobalData+0x434` | 4 x `0x6C` |
| infantry | `TheGlobalData+0x6BC` | 4 x `0x6C` |

Two of those bases are also reachable from INI — `TerrainLighting*` and `TerrainObjectsLighting*`
in `GameData`, field-table rows at `0x00BFFB40` and `0x00BFFC00`, offsets `0x1AC` and `0x434`. The
third has **no INI surface at all**: the infantry set exists only in the map.

The reader's own fallback is what identifies it. At `0x004AC879` it checks the chunk version and,
below 4, jumps to `0x004AC945`, which copies the **object** set into the infantry base
(`lea esi,[eax+0x434]` / `lea edi,[eax+0x6BC]`) rather than reading anything. A map too old to carry
infantry lights gets object lights in that slot — which is only a sensible fallback if that slot is
the infantry one.

Per time of day, the nine records are stored in the order the reader writes them: terrain L0,
object L0..L2, terrain L1..L2, infantry L0..L2. (Note that
[`sage_map.assets.global_lighting`](../../sage_map/assets/global_lighting.py) currently labels them
as sun/accent triples interleaved across the three categories, which is a different order; the byte
count is the same, so files round-trip, but the field names past `object_sun` do not mean what they
say.)

## 2. The scene builds two of them into light environments

Two adjacent virtuals on the scene class — `0x00443FA9` (current time of day) and `0x0044406D`
(indexed) — read those bases and publish them:

```
00443FC4  lea esi, [eax+0x434]          ; the object set
00443FCA  lea edi, [eax+0x6BC]          ; the infantry set
00444024  push ebx (= this+0x148)  ...  ; the object light array,   3 x LightClass*
00444037  push eax (= this+0x158)  ...  ; the infantry light array, 3 x LightClass*
```

The accessors at `0x00443E2F` and `0x00443E66` index those two arrays by light number
(`[ecx + eax*4 + 0x148]` and `[ecx + eax*4 + 0x158]`), which is what fixes them at three lights
each. The assembled environments they feed live at `scene+0x164` (objects) and `scene+0x5B4`
(infantry).

## 3. The render loop picks one, per render object

`0x0046FD42`, inside the scene's render walk:

```
0046FD45  mov  eax, [ebx]
0046FD49  call [eax+0x1C0]              ; RenderObjClass flag getter
0046FD4F  test eax, eax
0046FD54  je   0046FD5E
0046FD56  lea  eax, [esi+0x5B4]         ; infantry light environment
0046FD5C  jmp  0046FD8A
0046FD5E  lea  eax, [esi+0x164]         ; object light environment
0046FD8A  mov  [edi+0x28], eax          ; RenderInfo.light_environment
```

`+0x1C0` / `+0x1C4` are the getter/setter pair for `RenderObjClass` bit `0x02000000`
(`m_Bits`, `+0x10`); the implementations are the usual one-liners at `0x0046C7C8`
(`and eax, 0x2000000`) and `0x0046C7D1` (`or/and byte [ecx+0x13], 2`). Nothing else feeds this
choice.

## 4. The gate

The bit is set in the model-draw path, and only there. Two sites, identical shape:

```
0047A792  mov  edi, [edi+4]             ; Thing -> ThingTemplate
0047A795  test edi, edi
0047A797  je   0047A7B3
0047A799  mov  ecx, [esi+0x50]          ; the RenderObjClass
0047A79C  test ecx, ecx
0047A79E  je   0047A7B3
0047A7A0  test byte ptr [edi+0x109], 5  ; <-- the gate
0047A7A7  je   0047A7B3
0047A7A9  mov  eax, [ecx]
0047A7AB  push 1
0047A7AD  call [eax+0x1C4]              ; set the infantry-lighting bit
```

and the same at `0x004C4E2B` with `ebx` as the template register. The enclosing functions are
`0x0047A0AD` and `0x004C451D`, the two implementations of one draw virtual: seven draw-module
vtables hold one or the other at **slot 64** (`0x00BDC910` for the first, `0x00BE00E8`,
`0x00BE1C98`, `0x00BE2020`, `0x00BE25E8` and `0x00BE3D40` for the second), and `0x00BE2B80` holds
the second at slot 65.

`+0x108` is `ThingTemplate`'s `KindOf` mask (`Object` field-table row at `0x00DA4148`, and the
constant [`kind_of.THING_TEMPLATE_MASK_OFFSET`](../patches/utils/kind_of.py) derived there), so
`+0x109` is mask **bits 8..15** and the immediate `5` is bits 8 and 10. Against the engine's own
kindof name table at `0x00DA0E68`:

| bit | mask | name | in the stock test |
|---|---|---|---|
| 8 | `0x01` | `INFANTRY` | yes |
| 9 | `0x02` | `CAVALRY` | **no** |
| 10 | `0x04` | `MONSTER` | yes |
| 11 | `0x08` | `MACHINE` | no |
| 12 | `0x10` | `AIRCRAFT` | no |
| 13 | `0x20` | `HUGE_VEHICLE` | no |
| 14 | `0x40` | `DOZER` | no |
| 15 | `0x80` | `SWARM_DOZER` | no |

A scan of `.text` for every instruction addressing `[reg+0x109]` finds exactly these two sites
carrying immediate `5`, and the getter at `+0x1C0` is called five times inside the render walk
(`0x0046F6DB`, `0x0046FAB2`, `0x0046FD49`, `0x00470054`, `0x004700C0`) — §3 is one of them.

## 5. How much darker, and on which maps

Reading `GlobalLighting` out of every shipped map and comparing the object set against the infantry
set, the difference — where there is one — is almost always the **sun's ambient** alone. Diffuse
colour, direction and both accent lights match.

| map set | maps | infantry ambient lift | mean object ambient | mean infantry ambient |
|---|---|---|---|---|
| stock `Maps.big` | 103 | 19 | 0.086 | 0.242 |
| Edain `____edain_maps.big` | 510 | 295 | 0.072 | 0.313 |

`map mp amon sul fortress`, evening, sun light:

```
object   amb=(0.090, 0.071, 0.043)  col=(0.835, 0.553, 0.373)  dir=(0.673, 0.545, -0.500)
infantry amb=(0.290, 0.306, 0.290)  col=(0.835, 0.553, 0.373)  dir=(0.673, 0.545, -0.500)
```

On a good number of Edain maps (`map edain framsburg`, `Erebor_gold`, `MAP ANG Mirkwood`,
`MAP ANG Framsburg`, `map edain dorwinion winter`, `map edain wor barrow downs` and more) the object
ambient is flat `0.000` against an infantry ambient of `0.339`, so an object-lit model gets no fill
at all and its shadowed side goes to black. On the maps where the two sets are identical the gate
has no visible effect, which is why the bug looks map-dependent.

## 6. What the patch writes

Nine bytes at each of the two sites — the `test`'s immediate and the `je` that skips the setter:

* **Widen:** immediate `05` becomes the mask the named kindofs encode. The default names
  `INFANTRY`, `CAVALRY`, `MONSTER`, i.e. `07`. Same instruction, same branch, same target.
* **Everything:** immediate becomes `FF` and the two-byte `je` becomes two `nop`s, so the setter
  call is unconditional. The two null checks ahead of it are left standing.

Names are resolved through the image's live kindof table rather than a hardcoded list, so the patch
composes with anything that relocates that table, and a name outside bits 8..15 is refused by index
with a pointer at the `--all` form. Reaching such a kindof for real needs a second mask byte read,
which does not fit in the nine bytes at the site — it would need a cave and a detour, and the
`--all` form covers the cases that motivated asking.

## 7. Determinism

Client-side render state only. The flag lives on a `RenderObjClass`, is written during draw and read
once per draw, and reaches nothing on the logic thread. Nothing the engine CRCs changes, so a peer
running a stock binary disagrees about pixels and about nothing else, and replays cross in both
directions. That is the main reason to prefer this over adding `KINDOF_INFANTRY` in INI, which
changes crush rules, `PATH_THROUGH_INFANTRY`, KindOf filters on weapons, armor and powers, and AI
target selection — all of which are logic-side and all of which do have to match across peers.

## 8. Verifying it in a game

Static so far, apart from the map measurements. What would settle it:

1. A map with a divergent infantry set (`map mp amon sul fortress`, or any Edain map from §5) and a
   cavalry unit beside an infantry unit, before and after.
2. The same on a map where the two sets are identical, which must show no change either way.
3. `--all`, checking that structures and props brighten too — the sign that the branch, and not
   only the mask, is what the second form defuses.
