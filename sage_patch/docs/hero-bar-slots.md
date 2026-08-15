# `hero-bar-slots` — raising the in-game hero bar past 16 slots

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`).

**What it does.** Widens the in-game hero bar from its stock **16** slots to any **N** in 17..126.
The shipped default is **21**.

**Status: runtime-verified in game at N = 21** (Edain, 2026-08-10) — the engine fills slots 17+
with real heroes and the movie draws them. The patch alone is not enough: it must be paired with
an `.apt` edit, and **which movie** to edit is the single most expensive thing to get wrong here.
See [§7](#7-the-apt-half-which-movie-and-what-to-add).

The class layout this builds on was recovered in [`herobar-kindof.md`](herobar-kindof.md) §1,
which is also where the 16-slot ceiling was first written down as a *cost* of that feature. This
is the patch that removes it.

## 1. Why an `.apt` edit alone does nothing

The obvious move — add `Hero17`…`Hero21` clips to the hero-bar movie — changes nothing
observable, and it fails **silently**, which is what makes it worth documenting.

Two independent reasons:

* the constructor registers the `_OnBttnHeroSelect` callback on `%s/Hero%d/` for indices 1..16
  only, in a loop bounded at `0x0092E02E`, so the new clips are never wired to anything; and
* the draw loop `break`s at `0x0092D3E5` before it ever names index 17, so nothing calls
  `SetButtonState` / `SetImageState` on them.

The stock overflow behaviour is a `break`, not an error, so the extra buttons simply stay in
whichever state the movie parks them in. Nothing is logged and nothing looks wrong.

This is also why the failure is *not* evidence of a broken `.apt`: a movie the engine rejected
would lose slots 1..16 as well.

## 2. The class, and why it has no slack

One class, constructed **once**, in `AptPalantir::OnHeroSelectLoaded` (`0x006D4FC8`):

| | |
|---|---|
| class ctor | `0x0092DDE7` (allocating wrapper `0x0092E1D6`, `push 0x1E0` ⇒ **480-byte class**) |
| vtable | `0x00C7EE88` |
| only construction site | `0x006D502B` — exactly **one** bar object |
| `+0x08` | APT movie / level handle |
| `+0x0C` | `AsciiString` path prefix — the `%s` in `%s/Hero%d/` |
| `+0x10` | the shared model that owns the hero and porter lists |
| `+0x44` | "the bar has been shown" latch |
| `+0x48` | **slot cache**: `0x18`-byte stride × `0x10` entries, built by `0x00401399(base, 0x18, 0x10, 0x8CEF91)` |
| `+0x1C8`…`+0x1DF` | iteration/selection state |
| `0x1E0` | `sizeof` |

`0x48 + 16*0x18 == 0x1C8` exactly. The array ends on the byte before the state block, and the
state block ends on the byte before the end of the class. **There is nowhere to put a 17th slot
without moving something.**

The proof that `+0x1C8` is live and adjacent is one instruction away from the array's own
construction:

```asm
0092de4c  push 0x8cef91          ; element ctor
0092de51  push 0x10              ; count      <-- 16 slots
0092de53  lea  eax, [esi+0x48]   ; base
0092de56  push 0x18              ; stride
0092de58  push eax
0092de63  call 0x401399          ; eh vector constructor iterator
0092de68  mov  [esi+0x1c8], ebx  ; <-- the first byte after the array
```

## 3. Grow the class, do not move the array

Two ways to make room, and the choice is decided by instruction *encoding*, not by taste.

**Move the array into a cave.** Rejected. The array is addressed as disp8 off `this`:
`lea edi, [eax+esi+0x4c]` (`0x0092D37B`, 4 bytes), `lea edi, [edi+esi+0x4c]` (`0x0092D79C`),
`cmp byte [ecx+esi+0x5e]` (`0x0092DBD6`), and `mov eax, [eax+esi]` after the base is folded into
the index (`0x0092DBF4`). Re-pointing any of them at an absolute cave address needs a disp32
form that is 2–3 bytes longer than the instruction it replaces, so each site needs a detour and a
stub. Four detours, plus the ctor's base.

**Grow the class and slide the state block up.** Chosen. Every reference to the state block is
*already* a disp32 — `[esi+0x1c8]`, `[esi+0x1dc]`, … — because those offsets do not fit a signed
byte. Adding `(N-16)*0x18` rewrites the four displacement bytes **inside an instruction that
keeps its exact length and encoding**. The array stays at `+0x48`, so all four disp8 addressing
sites above are untouched and need no edit at all.

The result needs **no cave, no relocated code and no assembly** — 38 immediates:

```
sizeof(N)  =  0x48 + N*0x18 + 0x18          ; array offset, array, state block
             = 0x1E0 at N=16 (the shipped value, which is how the tables are checked)
             = 0x258 at N=21
```

## 4. The ten counts

The ceiling looks like one constant and is ten. Missing any of them is a different bug:

| VA | stock | basis | what it bounds |
|---|---|---|---|
| `0x0092C013` | `83 fe 10` | 0-based | slot search — "which slot is showing this node" |
| `0x0092C2DA` | `6a 10` | count | vtable[2]: reset every slot to the list head, ungrouped |
| `0x0092C307` | `83 fa 10` | 0-based | vtable[3]: find a slot by node, then index it |
| `0x0092C955` | `83 7d f8 10` | 0-based | the expanded-hero scan |
| `0x0092D3E5` | `83 f8 11` | **1-based** | the draw ceiling — the one the bar visibly stops at |
| `0x0092D78D` | `83 ff 10` | 0-based | cleanup entry guard: are there leftover slots to blank |
| `0x0092D8B6` | `83 fb 11` | **1-based** | the cleanup loop's own back edge |
| `0x0092DBC8` | `83 f8 10` | 0-based | click dispatch: reject a slot index past the end |
| `0x0092DE51` | `6a 10` | count | the vector-ctor's element count — the array itself |
| `0x0092E02E` | `83 f8 10` | 0-based | the ctor's `Hero%d` callback registration loop |

Only the first is cosmetic on its own. Leaving `0x0092DE51` alone while raising the others is the
dangerous combination: every loop would then run off the end of a 16-element array and into the
state block.

**Two of them are 1-based**, and that is not a quirk — the APT surface is 1-based (`%s/Hero%d/`
names `Hero1` first), so the draw cursor `[ebp-0x14]` counts from one while the slot index
`[ebp-0x24]` counts from zero, and the two bounds differ by exactly that. Getting a basis
backwards loses a slot at one end or writes one past the array at the other.

### How the set was closed

Three sweeps, because no single one is exhaustive:

1. **Displacement search** for disp32 references in `[0x1C8, 0x1E0)`, done twice by different
   methods — a byte search for the packed displacement with disassembly confirmation, and a
   linear sweep of the cluster — which agree on **27 sites** (the byte search additionally
   reports three one-byte-early decodes where the preceding byte reads as a segment prefix).
2. **Immediate sweep** of every `0x10` / `0x11` in `0x0092B000`…`0x0092E400`, classified by hand.
   Most are `add esp, 0x10`, `ret 0x10`, or `model+0x10` (the hero list head); `0x0092C386` is
   `operator new(0x10)` for the 16-byte callback object and is **not** a slot count.
3. **The vtable** at `0x00C7EE88`, which is what found `0x0092C2DA` and `0x0092C307` — both walk
   the array with their own loop counter and neither touches the state block, so neither sweep
   above could see them.

Sweep 3 is the one worth remembering. A displacement search finds code that reads *past* the
array; it cannot find code that walks the array itself.

## 5. The 27 re-based references

Fields `+0x1C8`, `+0x1CC`, `+0x1D0`, `+0x1D4`, `+0x1D8`, `+0x1D9`, `+0x1DA`, `+0x1DC` — a
`0x18`-byte block whose internal layout is unchanged; the whole block slides up by
`(N-16)*0x18` (`0x78` at N=21, landing at `+0x240`…`+0x254`).

The sites are listed in [`../patches/hero_bar_slots.py`](../patches/hero_bar_slots.py) as whole
stock instruction bytes rather than as "four bytes at a VA", so the assertion covers the opcode
and ModRM too: a build where one of these is not what it was here is one whose class layout this
patch must not assume.

## 6. What it does *not* need

* **No cave, no `allocate_section`, no assembly.** Every edit is an immediate of the same width.
* **No savegame change.** The bar is UI built from the model's object lists each pass; it is not
  `Xfer`'d.
* **No `.csf`/`.str` and no new engine strings.** Slot *N* is drawn through the same four format
  strings slot 1 is.
* **No determinism cost.** The bar is client-local: nothing enters the simulation, and the click
  path raises the same `MSG_CREATE_SELECTED_GROUP` it always did. A patched and a stock peer do
  not desync, and replays cross.

## 7. The APT half: which movie, and what to add

**This is the half that costs the time.** The engine change is 38 immediates and applies blind;
the movie edit needs you to find the right file first, and the obvious candidate is wrong.

### 7.1 The movie is not the one named after the feature

On Edain the hero bar is drawn by **`FactionFrame.apt`**. `InGameHeroSelect.apt` ships in the same
archive, contains a full `Hero1`..`Hero16` bar, is byte-for-byte plausible — and **nothing loads
it**. Editing it changes nothing, silently, exactly like not applying the patch at all.

The engine gives no hint: it drives slot *i* through `%s/Hero%d/` (`0x00C7EF8C`) where `%s` is a
path prefix held on the bar object at `+0x0C`, so the movie's *file name* never appears in the
code. Do not infer it.

**How to identify the real movie, in a running game.** Strings in a loaded `.apt` survive
verbatim (only pointers are fixed up on load), so a string's offset *relative to the movie's own
`Apt Data:` header* is a fingerprint that survives loading:

1. find a hero-bar string in the process — `SelectAllHeroesBttn\0` works well;
2. scan backwards from each hit for the `Apt Data:` magic. Expect several hits and only one
   usable: the string is also copied into parsed structures elsewhere on the heap, and those
   copies have no movie header behind them, which is exactly what identifies the real buffer;
3. the delta from magic to string is the offset within the file. Search every `.apt` on disk
   (loose and inside `.big`s) for the same string at the same file-relative offset.

On this install that gave `0x2d0ac`, matching `FactionFrame.apt` and nothing else — Edain's
`InGameHeroSelect.apt` has it at `0x2c0c0`, EA's stock one at `0x29678`.

Two traps that cost real time here, both worth avoiding by using the offset method directly:

* **Absence of a string is weak evidence, presence of one is weaker.** `Hero17` missing from
  process memory proves the loaded movie lacks it, but says nothing about *which* movie it is.
  Edain-only strings like `HeroRallyImla_reg.tga` or `_Imladris` are imports and frame labels that
  also appear in `libInGameImagesMain` and other movies, so finding them proves nothing.
* **The structural bytes around a name are not a fingerprint.** They differ between versions only
  in embedded file offsets, which loading rewrites — so two different movies compare equal there.

### 7.2 Where the file lives, and what actually gets loaded

| | |
|---|---|
| source tree | `<mod>/_mod/apt/FactionFrame.apt` + `.const` (4:3) and `<mod>/_mod/apt_widescreen/FactionFrame.apt` + `.const` |
| what the game reads | `<rotwk>/__edain_apt.big` and `<rotwk>/___edain_apt_widescreen.big`, entries stored **flat at the archive root** (`FactionFrame.apt`, not `apt\FactionFrame.apt`) |

The loose `_mod/apt/` folder is **not** in the load path — it is the source the archives are built
from. Editing it alone changes nothing; the archive must be repacked. And on Edain the archives
are **not** produced by `final_big_builder_config.ini`, which has no section covering `_mod/apt`,
so they are maintained outside that pipeline: edit the loose file *and* repack the archive, or the
next rebuild silently drops the change.

Both archives must be done. `apt_widescreen` wins at widescreen resolutions and the two variants
have **different layouts** (§7.4), so they are not interchangeable copies.

### 7.3 The records to add

`FactionFrame`'s root timeline holds the bar on two frames, and a new slot needs an entry in both:

| frame | label | what a slot has there |
|---|---|---|
| 9 | `_fadein` | the full `placeobject`: `HasCharacter\|HasColorTransform\|HasMatrix\|HasName\|HasRatio`, `alpha="0"` |
| 19 | `_show` | a `HasColorTransform\|Move` record on the same depth, `alpha="255"` |

Nothing else in the movie is per-slot, and **no ActionScript changes are needed**: every entry
point (`SetButtonState`, `SetImageState`, `SetButtonSelectedHighlightState`,
`SetButtonFlashEffectState`, `PlayButtonAttackedEffect`, `PlayButtonLevelUpEffect`,
`KillButtonEffects`, `SetButtonHealthBar`, `SetButtonRankProgress`) resolves its target as
`this["Hero" + index]` / `this["FlashEffect" + index]`. Clip names live in the `.apt` itself, not
the `.const`, so no constant-pool authoring either.

Copy `Hero16` and `FlashEffect16` as templates — the flash effect carries a `clipaction` that must
come with it — then override `depth`, `tx`, `ty` and the `poname`. Two details that are easy to
miss:

* **Write the final position into `_fadein` and give `_show` a colour-only `Move`.** Slots 1..9 do
  exactly this; slots 10..16 instead sit at a staging position on `_fadein` and are repositioned by
  a `HasMatrix` `Move` on `_show`. Copying the second pattern works but is pointless indirection.
* **Reset the matrix to identity** (`rotm00`/`rotm11 = 1`) — some templates carry a fade-in scale
  like `0.99925202`.
* **A `FlashEffect` sits at its hero's position plus a fixed offset**: `(+28.05, +28)` on the 4:3
  variant, `(+28, +28)` on widescreen.

Depths only have to be unused and ordered sensibly; flash effects draw over buttons. The shipped
build used heroes `469, 496, 523, 550, 577` (continuing the stock `+27` spacing) and flash effects
`604, 606, 608, 610, 612` (stock `+2`), all above the stock maximum of `467`. New heroes landing
above the *stock* flash effects is harmless — a button never overlaps another slot's flash.

### 7.4 The two variants have different grids

Read the geometry out of the file you are editing; do not carry positions across.

| variant | row 1 | row 2 | pitch |
|---|---|---|---|
| `apt/` (4:3) | `Hero1`..`Hero9`, x = 24 + 70k | `Hero10`..`Hero16`, x = 94..514, y = −70 | 70 |
| `apt_widescreen/` | `Hero1`..`Hero13`, x = 24 + 75k | `Hero14`..`Hero16`, x = 99..249, y = −70 | 75 |

The 4:3 grid is a centred pyramid (9 over 7, indented one column), so N = 21 continues it with a
centred third row of five at y = −140, x = 164/234/304/374/444. The widescreen row 2 is simply
filled left to right and has room to column 13, so N = 21 just keeps filling it at
x = 324/399/474/549/624, y = −70.

The two files are the same size and differ in only ~200 bytes — all layout numbers, **no string
differences** — so nothing but the geometry distinguishes them. A probe that looks for a
variant-only string will not find one.

### 7.5 The numbers actually used

`N = 21`, shipped and runtime-verified. Depths are shared by both variants; only the positions
differ.

| slot | depth | flash depth | 4:3 position | widescreen position |
|---|---|---|---|---|
| `Hero17` | 469 | 604 | (164, −140) | (324, −70) |
| `Hero18` | 496 | 606 | (234, −140) | (399, −70) |
| `Hero19` | 523 | 608 | (304, −140) | (474, −70) |
| `Hero20` | 550 | 610 | (374, −140) | (549, −70) |
| `Hero21` | 577 | 612 | (444, −140) | (624, −70) |

`N = 25`, built and validated but **not installed** — kept here because the arithmetic is the
part worth not redoing. The 4:3 variant gets a fourth row at y = −210, centred on x = 304 at
half-pitch offsets (a centred pyramid staggers; grid-aligning four slots under a five-slot row
cannot also centre them). Widescreen keeps filling row 2, which reaches its last column at 924.

| slot | depth | flash depth | 4:3 position | widescreen position |
|---|---|---|---|---|
| `Hero22` | 614 | 722 | (199, −210) | (699, −70) |
| `Hero23` | 641 | 724 | (269, −210) | (774, −70) |
| `Hero24` | 668 | 726 | (339, −210) | (849, −70) |
| `Hero25` | 695 | 728 | (409, −210) | (924, −70) |

Sizes, as a sanity check when repacking: stock `FactionFrame.apt` is 191,060 bytes with a 3,436-byte
`.const`; at N = 21 it is 193,140 / 3,496; at N = 25, 194,644 / 3,496.

### 7.6 Reproducing it

```sh
# 1. decompile the variant you are editing (do both)
python -m sage_apt to-xml  <mod>/_mod/apt/FactionFrame.apt
python -m sage_apt to-xml  <mod>/_mod/apt_widescreen/FactionFrame.apt

# 2. add the placeobjects on frame 9 and the alpha Moves on frame 19 (see 7.3),
#    then compile back — this rewrites FactionFrame.apt and .const together
python -m sage_apt to-apt  <mod>/_mod/apt/FactionFrame.xml

# 3. prove the movie still round-trips before shipping it
python -m sage_apt check   <mod>/_mod/apt/FactionFrame.apt

# 4. repack BOTH archives, replacing FactionFrame.apt and FactionFrame.const
#    (pyBIG: Archive.edit_file -> repack -> save; or FinalBIGv2)
```

Rebuild each archive **from a pristine copy** rather than from the previously patched one, so the
diff stays exactly two entries. Verify by reading the entries back out of the written archive, not
by trusting the write.

### 7.7 Verifying it in a game

1. **17+ heroes produce 17+ slots**, with the 17th drawing its portrait, rank and health like any
   other.
2. **Clicking slot 17..N selects that hero** — this is `0x0092DBC8`, and it is the one that fails
   *only* on click, so a bar that draws correctly is not evidence it passed.
3. **A hero dying past slot 16 frees its slot** and the ones after it shift up — the cleanup pair
   (`0x0092D78D` / `0x0092D8B6`), which is what blanks the tail.
4. **Fewer heroes than slots leaves no stale buttons** — the same pair, from the other side.
5. **Select-all-heroes still works** and includes the ones past 16.
6. **Porters still behave exactly as before**, including their single mixed slot.
7. **The bar survives a reload**: hide and re-show the palantir (`_hide` → `_show`) with more than
   16 heroes alive.
8. **N=17 and N=126** both boot, to confirm nothing else assumed a small class.

**Checking the two halves separately is what makes this tractable**, and both can be read out of
the live process without looking at the screen:

* *engine half* — find the bar object by scanning the heap for its vtable `0x00C7EE88` at
  offset `+0x00`, then read the slot array at `+0x48`, stride `0x18`. A slot showing a hero has a
  non-null cached image at `+0x04`; an empty one reads rank/progress/health as `-1`. Slots past 16
  holding real heroes is the patch working, regardless of what is drawn.
* *movie half* — count occurrences of `Hero17\0` in process memory. The movie is only loaded once
  a match starts, so this reads zero in the menus.

The engine half can pass while the movie half fails, and that combination looks exactly like
"nothing happened": the bar shows sixteen heroes and no error appears anywhere.

## 8. Composition

Order-independent. It allocates no section and reads nothing another patch writes.

It shares functions with [`herobar`](herobar.md) but **not a byte**: that patch's detours are at
`0x0092CD7F`, `0x0092C439`, `0x0092C467`, `0x0092D36F`, `0x0092D3EE` and `0x0092DBD6`, and the
nearest sites here are `0x0092D3E5` (3 bytes clear of `0x0092D3EE`) and `0x0092DBC8` (8 bytes
clear of `0x0092DBD6`).

One behavioural interaction is worth naming, since the framework cannot catch it. `herobar`'s
per-pass "already drawn" template set is **16 dwords** in its own cave, and it *clamps* rather
than overflows:

```asm
per_node_add:
    cmp eax, 16
    jae per_node_mark      ; past 16 kinds: mark the slot, record nothing
```

So on a bar wider than 16, the 17th and later distinct `HEROBAR` templates stop being
de-duplicated — each instance takes its own slot. Nothing corrupts and nothing crashes; grouping
degrades past 16 *kinds*. Widening that set is a one-constant change in `herobar`'s cave if the
pair is ever shipped together.

Its click cursor is 16 dwords in the same cave and clamps the same way, indexed by slot rather
than by template: a group drawn in slot 17 or beyond reads and writes no cursor, so every click on
it selects the group's first member instead of stepping to the next. Same one constant.

Both only concern `herobar --grouped`. The default `herobar` keeps no state at all and is
indifferent to how wide the bar is.

## 9. Key addresses

| VA | meaning |
|---|---|
| `0x00401399` | `eh vector constructor iterator` — builds the slot array |
| `0x006D4FC8` | `AptPalantir::OnHeroSelectLoaded` — the only construction site |
| `0x0092BBEF` | hero-bar eligibility: local player && !`NO_HERO_PROPERTIES` |
| `0x0092C2DA` | vtable[2] — reset every slot |
| `0x0092C2F5` | vtable[3] — find a slot by node |
| `0x0092CF64` | the hero bar's `update()` |
| `0x0092D375` | `imul eax, eax, 0x18` — the slot stride, in the draw loop |
| `0x0092D3E5` | the draw ceiling |
| `0x0092D76F` | the loop's "next node, no slot consumed" label |
| `0x0092D78D` | the cleanup loop that blanks leftover slots |
| `0x0092DB91` | the hero-bar click handler |
| `0x0092DDE7` | the class ctor |
| `0x0092E1D6` | the allocating wrapper (`push <sizeof>` at `0x0092E1E2`) |
| `0x00C7EE88` | the class vtable |
| `0x00C7EF8C` | `%s/Hero%d/` — the button path, **1-based** |
| `0x00C7EF38` | `_level%d.%s_Hero%dImage` |
| `0x00C7EEF0` | `APT:_level%d.%s_Hero%dRank` |
