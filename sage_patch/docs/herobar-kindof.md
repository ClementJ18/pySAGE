# A `HEROBAR` kindof — one hero-bar slot per object type — what it would cost

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), read statically from a
ROTWK `game.dat` (11,347,456 bytes — a stock 11,346,944-byte image with the `cah-factions` cave
section `.cahfac` already appended; `.text` is untouched by that patch, so every address below is
also a stock address).

**Built.** This shipped as [`herobar`](../patches/herobar.py), as **two** kindofs rather than one -
`HEROBAR` for a slot per object and `HEROBAR_GROUP` for the shared slot this document costs. The
implementation writeup is [`../herobar.md`](herobar.md), and that is the description of what the
patch does. This document is the static costing behind it — the kindof bit, the name-table relocation and the hero-bar
model. Where the two differ, `herobar.md` wins: the shipped design reuses the engine's own draw
loop instead of copying it (which removes both the per-group cursor problem and the blocker in
[§9](#9-open-questions)), and it selects the group on a click rather than iterating it, which is
the question §5 leaves open here.

**Nothing here has been run.** Everything is static: disassembly, name tables, field tables, call
graphs. Section [§10](#10-verifying-it-in-a-game) is the whole runtime list, and it is still open.

**Scope of the idea:** add a kindof — `HEROBAR` — that puts an object on the hero bar in a slot
*shared with other instances of the same object*, so that

- two instances of **one** template ⇒ **one** slot, clicking it iterates through them;
- two instances of **two** templates ⇒ **two** slots, one per template.

That is deliberately not what `PORTER` does. `PORTER` collapses *every* porter the player owns into
a **single** slot regardless of template, and iterating that slot walks the whole mixed set. So this
is not "a second `PORTER`" — the grouping key changes from *nothing* to *the `ThingTemplate`*, and
with it the number of slots stops being a constant.

---

## Verdict up front

**The engine is already 80% of the way there, and almost none of the remaining 20% is the kindof.**

The hero bar already has a *generic per-slot "this slot is a group" bit* (`slot+0x16`), the click
handler already routes a flagged slot to an iterate-through-the-group routine instead of a
select-one-object routine, and the group's icon/count drawing is already written. What is hardcoded
is that exactly **one** group exists, that it is **always slot 0**, that its membership is **one
fixed list on the model**, and that its iteration cursor is **one field on the bar** rather than one
per group.

The kindof itself is the cheapest part of the job: `KindOfMaskType` is **224 bits wide with only 222
names used**, so a 223rd kindof costs **no data growth anywhere** — not in `ThingTemplate`, not in
the savegame blob. Adding the name is the same table-relocation this repo already ships twice
(`production-condition`, `desert-weather`), and the KindOf table needs *fewer* fixups than the
`ModelConditionFlags` table those patches already move.

| | new INI surface | cave | edits | risk | what you get |
|---|---|---|---|---|---|
| **Tier 0** — name only | `KindOf = HEROBAR` parses | ~0.95 KB | 12 refs + 5 counts | very low | a kindof no code reads |
| **Tier 1** — a second collapsed group | + it behaves like `PORTER` | +~0.4 KB | 2 detours, model +4 | low | all `HEROBAR` objects in **one** slot |
| **Tier 2** — one slot per template | + the actual ask | +~0.7 KB | 4 detours, per-group cursors | **medium** | one slot **per template**, iterating within it |

Tier 2 is where the real work is, and its cost is dominated by two things that have nothing to do
with kindofs: **a variable number of groups against a 16-slot bar**, and **an iteration cursor that
is currently per-bar, not per-group** ([§8](#8-what-tier-2-actually-costs)).

---

## 1. What the hero bar is, in the binary

The bar is an APT (Flash) movie driven from C++. The C++ side is one class, constructed **once**, in
`AptPalantir::OnHeroSelectLoaded` (`0x006D4FC8`) — the handler registered under the string
`AptPalantir::OnHeroSelectLoaded` (`0x00C19260`).

| | |
|---|---|
| class ctor | `0x0092DDE7` (allocating wrapper `0x0092E1D6`, `push 0x1E0` ⇒ **480-byte class**) |
| vtable | `0x00C7EE88` |
| only construction site | `0x006D502B` — so there is exactly **one** bar object |
| `+0x08` | APT movie / level handle |
| `+0x0C` | `AsciiString` path prefix — the `%s` in every format below |
| `+0x10` | pointer to the shared **model** (`AptPalantir+0xC0`) that owns the object lists |
| `+0x44` | "the bar has been shown" latch |
| `+0x48` | **slot cache array**: `0x18`-byte stride × `0x10` entries, built by `0x00401399(base, 0x18, 0x10, 0x8CEF91)` |
| `+0x1C8`..`+0x1DF` | iteration/selection state (see [§5](#5-iterating-a-group)) |

`0x48 + 16*0x18 == 0x1C8`, so the slot array runs to the byte before the cursor state and the class
has no slack. **The bar is 16 slots wide, fixed at construction.**

### The slot cache struct (`0x18` bytes)

Recovered by intersecting the expanded-hero writer (`edi = this + 0x4C + i*0x18`, fields at
`[edi-4]`…`[edi+0x11]`) with the group writer (which addresses slot 0 absolutely at `this+0x48`…
`this+0x5E`):

| offset | field |
|---|---|
| `+0x00` | the model list node this slot is showing |
| `+0x04` | cached button image |
| `+0x08` | cached rank number — **for a group slot, the member count** |
| `+0x0C` | cached rank progress |
| `+0x10` | cached health percentage |
| `+0x14` | selected-highlight bool |
| `+0x15` | flash-effect bool |
| `+0x16` | **"this slot is a group" bool** |
| `+0x17` | unused |

`+0x16` is the load-bearing field for this whole document, and it is already generic per slot.

### The APT names

The bar's ActionScript surface is built from four format strings and a fixed set of method names:

| string | VA | use |
|---|---|---|
| `%s/Hero%d/` | `0x00C7EF8C` | button path, **1-based** slot index |
| `_OnBttnHeroSelect` | `0x00C7EFB0` | per-slot click callback |
| `_level%d.%s_Hero%dImage` | `0x00C7EF38` | the slot's portrait |
| `APT:_level%d.%s_Hero%dRank` | `0x00C7EEF0` | the slot's rank number |
| `SetButtonRankProgress` / `SetButtonHealthBar` / `SetButtonSelectedHighlightState` / `SetButtonFlashEffectState` / `SetButtonState` / `KillButtonEffects` / `PlayButtonLevelUpEffect` | `0x00C7EF20` … | per-slot ActionScript calls |

The ctor registers `_OnBttnHeroSelect` for `Hero1`..`Hero16` in a loop bounded by `cmp eax, 0x10`
at `0x0092E02E`, plus one `_OnBttnSelectAllHeroes` on `/SelectAllHeroesBttn/`.

**A group slot uses exactly the same strings as a hero slot.** The porter group is drawn through
`_level%d.%s_Hero%dImage` and `APT:_level%d.%s_Hero%dRank` with index `1` — i.e. cache slot 0 — the
same calls a hero slot gets, only with the count substituted for the rank. **So no new APT asset,
no `.apt` edit, and no ActionScript work is needed to add groups.** That is the single most
expensive thing this feature does *not* need.

---

## 2. The model, and the classifier that fills it

The model (`bar+0x10`) is shared and holds two intrusive lists plus a counter:

| offset | contents |
|---|---|
| `+0x10` | **hero** list — nodes `{next, prev, ObjectID@+8, …}` |
| `+0x14` | **porter** list — nodes `{next, prev, ObjectID@+8, visited-byte@+0xC, …}` |
| `+0x18` | pending-attention counter; drives the group slot's flash (`0x0092D2EE`) |

Everything routes through one 42-byte function. This is the seam:

```asm
; 0x0092CD78  onObjectAdded(Object *obj)
0092cd78  8b542404              mov  edx, [esp+4]              ; Object*
0092cd7c  8b4204                mov  eax, [edx+4]              ; -> ThingTemplate
0092cd7f  f68013010000 04       test byte [eax+0x113], 4       ; KindOf bit 90  = HERO
0092cd86  7408                  je   0x92cd90
0092cd88  52                    push edx
0092cd89  e8a6f9ffff            call 0x92c734                  ; -> hero list  (+0x10)
0092cd8e  eb0f                  jmp  0x92cd9f
0092cd90  f68019010000 80       test byte [eax+0x119], 0x80    ; KindOf bit 143 = PORTER
0092cd97  7406                  je   0x92cd9f
0092cd99  52                    push edx
0092cd9a  e86afaffff            call 0x92c809                  ; -> porter list (+0x14)
0092cd9f  c20400                ret  4
```

`ThingTemplate+0x108` is the `KindOf` mask (field table entry 57, `0x00DA4148`), so bit *N* is
`byte [tmpl + 0x108 + N/8] & (1 << N%8)`. `0x113 → bit 90 = HERO`; `0x119 → bit 143 = PORTER`. Both
match the name table exactly.

`PORTER` is tested in **three** places in the whole binary, all of them in this module:

| VA | what |
|---|---|
| `0x0092CD90` | the classifier above |
| `0x0092C443` | `onObjectRemoved` — accept the object at all |
| `0x0092C4A8` | `onObjectRemoved` — pick which list to erase from |

That is the entire engine-wide footprint of `PORTER`. There is no AI use, no INI use beyond the
mask, no script use.

### The two insert paths differ, and the difference matters

`addHero` (`0x0092C734`) resolves the button image, dedupes on `ObjectID` (`Object+0x74`), then
**inserts in sorted position by `ThingTemplate+0x648` — `HeroSortOrder`** (field table entry 180).

`addPorter` (`0x0092C809`) dedupes on `ObjectID` and **appends**. No sort, no template key. Which is
exactly why the porter slot's icon is "whichever porter joined first": the group's image comes from
`0x0073D0BA(template, obj)` on the list head.

---

## 3. How the group slot is drawn

`bar::update()` is `0x0092CF64` (reached through the adjustor thunk `0x0092D97C`). Its shape:

```
0x92CF74   build a local list; collectPorters(list, filter=1)      -> 0x0092CE90
0x92CF95   if (!shown) { scan hero list for a visible object; "Show"; shown = 1 }
0x92D043   edi = the collected porter list
           if (empty) goto 0x92D34F                                ; no group this frame
           if (slot0.grouped != 1) { first-time init of slot 0 }
0x92D1CD   count = length(list)
           if (count != slot0.rank) SetButtonRankProgress(1, count) ; the number on the icon
           … selected-highlight, flash …
0x92D346   nextSlot = 1                                            ; heroes start after the group
0x92D34F   (no porters) slot0.grouped = 0 ; nextSlot stays 0
0x92D353   for each hero in model->heroList:
0x92D36F     eax = nextSlot; buttonIndex = eax + 1
             edi = this + 0x4C + eax*0x18
0x92D3E5     if (buttonIndex >= 0x11) break                        ; the 16-slot ceiling
             … draw image / rank / health / highlight / flash …
0x92D75F     nextSlot++
0x92D78D   for the remaining slots up to 0x10: KillButtonEffects, SetButtonState "_unused"
```

Two facts fall out of this and they are the design constraints for Tier 2:

1. **The group always occupies cache slot 0** (`mov dword [ebp-0x24], 1` at `0x0092D346`), and the
   "is a group" flag it sets is `slot0.grouped` — written absolutely as `[esi+0x5E]` at `0x0092D0A3`
   and cleared at `0x0092D34F`.
2. **The whole bar is one group followed by heroes.** There is no notion of "the k-th group".

`collectPorters` (`0x0092CE90`) is worth naming separately: it walks `model->porterList`, resolves
each `ObjectID` through `TheGameLogic::findObjectByID` (`0x00449681`), keeps only objects whose
controlling player is the local player (`0x0068B678` → `0x006AA7B2`), and — when its `filter`
argument is 1 — additionally applies `0x0092BAD7`. It is the natural place to grow a `groupKey`
argument.

---

## 4. Which objects are eligible at all

`0x0092BBEF`, called from both drawing loops:

```asm
0092bbef  mov  ecx, [esp+4]
0092bbf3  call 0x68b678        ; Object::getControllingPlayer
0092bbfa  call 0x6aa7b2        ; Player::isLocalPlayer  (cmp this, [TheThing+0x10])
0092bc01  je   fail
0092bc03  mov  ecx, [esp+4]
0092bc07  push 0x5c            ; ObjectStatus 92
0092bc09  call 0x44ddec        ; Object::testStatus  (mask at Object+0x94)
0092bc0e  neg al ; sbb al,al ; inc al   ; = !status
```

Status 92 in the table at `0x00D8AFF0` is **`NO_HERO_PROPERTIES`**. So the eligibility rule is
"locally controlled and not `NO_HERO_PROPERTIES`", and a `HEROBAR` object inherits it for free.

(Note for `addresses.py`: `0x0044DDEC` is `Object::testStatus`, reading a bitmask at `Object+0x94`;
its sibling `0x00444D39` is the single-bit `KindOfMaskType` constructor — `memset(this, 0, 0x1C)`
then set the bit. The `0x1C` there is the first of the two independent confirmations of the mask
width in [§6](#6-the-kindof-itself-is-the-cheap-part).)

---

## 5. Iterating a group

Clicking any hero-bar button lands in `0x0092DB91`:

```asm
0092db9b  push 4 ; push "Hero" ; push name ; strncmp
0092dbb0  jne  done                                  ; not a Hero button
0092dbb9  atoi(name+4) ; dec eax                     ; -> 0-based slot
0092dbc8  cmp  eax, 0x10 ; jge done
0092dbd3  imul ecx, eax, 0x18
0092dbd6  cmp  byte [ecx+esi+0x5e], 0                ; slot[i].grouped
0092dbdb  je   0x92dbeb
0092dbdd  push 0 ; call 0x92d9f4                     ; ITERATE THE GROUP
0092dbe6  jmp  done
0092dbeb  mov  ecx, [esi+0x10]                       ; else: select the one object
0092dbee  add  eax, 3 ; imul eax, eax, 0x18
0092dbf4  mov  eax, [eax+esi]                        ; = slot[i].node  (i*0x18 + 0x48)
```

**The click path is already generic.** It reads the per-slot flag and dispatches. It does not know
or care that the group is porters, or that it is slot 0. This is the strongest single argument that
the feature is cheaper than it looks.

`0x0092D9F4` is the iterator. It:

- re-collects the porter list with `filter=1` (`0x0092CE90`);
- scores each entry by squared distance to the camera and sorts (`0x0092D8FA`);
- picks the first entry not yet visited this round (`0x0092CA77`, testing the **visited byte on the
  list node itself**, node`+0xC`);
- if none is left, resets the round (`0x0092C080`: clear every node's visited byte, clear
  `bar+0x1DA`) and picks again;
- selects the object through the message stream (`0x3EB`) and, on a repeat click inside
  `bar+0x1DC` frames, centres the camera.

**The per-entry "visited" byte lives on the list node, so it is already per-group** if groups are
disjoint sublists. What is *not* per-group is `bar+0x1DA` ("a cycle is in progress") and `bar+0x1DC`
(the last-click frame stamp). Those are single fields on a 480-byte class with no slack. Tier 2 has
to move them into the slot struct (which has one spare byte at `+0x17`, not four) or grow the class.

---

## 6. The kindof itself is the cheap part

### The mask has room

`KindOfMaskType` is **7 dwords / 28 bytes / 224 bits**, confirmed twice and independently:

| site | evidence |
|---|---|
| `0x00655B3F` | `push 0x1C` → `memset(mask, 0, 0x1C)` on `KindOf = NONE` |
| `0x00444D3A` | `push 0x1C` → the single-bit mask constructor |
| `0x00DA4148` | `ThingTemplate.KindOf` at offset `0x108`; the next mask field in the sibling table (`0x00DA7008`/`0x00DA7018`, `KindOf`/`ExcludedKindOf`) sits exactly `0x1C` later |

The name table at `0x00DA0E68` is NULL-terminated and holds **222** entries (`[0] OBSTACLE` …
`[143] PORTER` … `[221] HORDE_MONSTER`). So **bits 222 and 223 are free** and a `HEROBAR` at index
222 lands in dword 6, bit 30 — inside the existing 28 bytes.

That means: **no `ThingTemplate` growth, no savegame length change, no `Object` growth.** The
`KindOfMaskType::xfer` packing loop at `0x006AC637` walks bit-by-bit into a fixed `0x1C`-byte blob
(`push 0x1C` at `0x006AC644`); raising its bound from 222 to 223 sets one more bit in the *same*
blob. A patched and an unpatched build write the same number of bytes.

This is the whole reason a new kindof is affordable at all — contrast
[`upgrade-mask-limit.md`](upgrade-mask-limit.md), where the mask is full and the next entry
corrupts its neighbour.

### Growing the table is a shape this repo already ships

The parser is `INI::scanIndexList` (`0x0042B914`), reached three times from the `KindOf` mask parser
at `0x00655B0E` (`+NAME`, `-NAME`, bare `NAME`). It walks the table to its NULL terminator; there is
no count on the parse path. That is exactly the contract
[`name_tables.py`](../patches/utils/name_tables.py) was written for — read the table live, rebuild it
into a cave with one more entry, repoint every reference.

The table cannot grow in place: `0x00DA11E0` is its terminator and `0x00DA11E4` is already the first
entry of the next table (`NONE`, `HOLD`, `KILL`, `SPAWN`).

**References to relocate — 14 sites.** `0x007B3CDB` is among them and looks like a jump-table
false positive but is not: `0x007B3CDA` is a six-byte `mov eax, <table>; ret` accessor sitting
after a byte table. Nothing calls it, exactly like the dead `getCount` below, and it is
repointed anyway.

| VA | site |
|---|---|
| `0x00655B67` | mask parser, `+NAME` |
| `0x00655BA7` | mask parser, `-NAME` |
| `0x00655C12` | mask parser, bare `NAME` |
| `0x006AAD0F` | `nameFromBit` → `mov eax, [eax*4 + table]` |
| `0x006AAD20` | `nameToBit` → `cmp dword [table], edi` |
| `0x006AAD25` | `nameToBit` → `mov esi, table` |
| `0x007079FF` | `getKindOfName(index)` → `mov eax, [eax*4 + table]` |
| `0x007B3CDB` | a dead `mov eax, <table>; ret` accessor |
| `0x007B67E3`, `0x007B67F3`, `0x007B6869`, `0x007B6885`, `0x007B6899`, `0x007B68DD` | the script/editor kindof-picker, one function |

(Fingerprint the sites the way `model_conditions.py` does rather than trusting the byte search —
the literal also appears inside data, and two of these addresses have a second, wrong decoding
that a naive backward disassembly will prefer.)

**Counts to raise — 5 sites, all `222`:**

| VA | instruction | what it bounds |
|---|---|---|
| `0x006AC637` | `cmp esi, 0xDE` | `xfer` bit-packing loop |
| `0x006ACBD5` | `cmp [ebp+8], 0xDE` | name-list builder |
| `0x007079F5` | `cmp eax, 0xDE` | `getKindOfName` range check |
| `0x00762A35` | `cmp edi, 0xDE` | editor/script list population |
| `0x007B58FD` | `cmp esi, 0xDE` | script-condition text (`"Kind is '%s'"`) |

`0x006AACEA` (`mov eax, 0xDE`) is the `getBitCount()` accessor and is **dead** — no call, no data
pointer references it. Leave it or fix it; nothing reads it.

For comparison, the already-shipped `production-condition` moves `ModelConditionFlags` with **16**
references and **10** counts. The KindOf table is the smaller job.

### The pySAGE side is a one-liner

`sage_ini.engine.EnumDelta` already exists for exactly this:

```python
EnumDelta("KindOf", "HEROBAR", 222, self.name)
```

`sage_patch/docs/ini-types.json` and `module-reference.json` regenerate from a patched binary; the
`KindOf` member of `sage_ini/model/enums.py` gains one entry.

---

## 7. Tier 1 — `HEROBAR` as a second `PORTER`

Worth pricing separately because it is a genuinely small patch and it de-risks Tier 2.

1. **Name table** — [§6](#6-the-kindof-itself-is-the-cheap-part). ~0.95 KB of cave.
2. **Model list** — a third list head. The model's `+0x10`/`+0x14`/`+0x18` are the tail of its
   layout as far as this module is concerned, but the class is allocated elsewhere (`AptPalantir`
   at `+0xC0`) and **its size has not been recovered** — this is the one number Tier 1 needs and
   this document does not have ([§9](#9-open-questions)). Two ways out: grow `AptPalantir`'s
   allocation, or keep the second list entirely in the cave, keyed by nothing since there is only
   one of it.
3. **Classifier** — the 42 bytes at `0x0092CD78` are followed immediately by `0x0092CDA2`
   (`mov ecx,[ecx]`), so there is no padding to grow into. Detour: replace the
   `test/je` pair at `0x0092CD90` with a `jmp` into a cave that tests `PORTER`, then `HEROBAR`, and
   tail-calls the matching add.
4. **Update pass** — a second collapsed block. The existing one is ~770 bytes of straight-line code
   from `0x0092D043` to `0x0092D34F`; a cave copy parameterised on (list, slot index) is the
   honest cost, and it is the bulk of Tier 1's cave.
5. **Iteration** — `0x0092D9F4` needs the list as a parameter instead of a constant.

Tier 1 gives you *one* extra collapsed slot. It does **not** give you the requested behaviour.

---

## 8. What Tier 2 actually costs

The ask is grouping keyed on `ThingTemplate`, which makes the group count dynamic. Three problems,
in increasing order of unpleasantness.

### 8.1 Producing the groups — the cheap trick

Do not build a list-of-lists. Instead:

- keep **one** `HEROBAR` list on the model;
- make its insert **sorted by `ThingTemplate` pointer, then by `HeroSortOrder`** — `addHero`
  (`0x0092C734`) is already a sorted insert on `ThingTemplate+0x648` and is the template to copy;
- in the update pass, walk the list emitting **one slot per run of equal template**.

A run's slot then needs exactly what the porter slot already computes: the head entry's image
(`0x0073D0BA`), the run length as the rank number, and `slot.grouped = 1`. The drawing code is
reusable verbatim if it is parameterised on `(firstNode, runLength, slotIndex)` instead of
`(theWholeList, 0)`.

This is the piece that makes Tier 2 only modestly more expensive than Tier 1 rather than a rewrite.

### 8.2 The cursor is per-bar, not per-group — the real cost

From [§5](#5-iterating-a-group): the *visited* flag is per node (fine), but `bar+0x1DA` and
`bar+0x1DC` are single fields. With N groups, clicking group A then group B would inherit A's
in-progress state and its double-click window.

Options, cheapest first:

- **Slot-local.** The slot struct has one spare byte at `+0x17`; that can hold the "cycling" flag,
  but the frame stamp needs four more bytes and there are none. Widening the stride from `0x18` to
  `0x20` changes `imul …, 0x18` at `0x0092D375`, `0x0092D799`, `0x0092DBD3`, `0x0092DBEE`, the
  array-construction call at `0x0092DE56`, and the class size at `0x0092E1E2` — six edits, all
  mechanical, and `0x48 + 16*0x20 = 0x248` exceeds `0x1E0` so the class grows anyway.
- **Cave-side table.** A 16-entry side array in the patch's own cave, indexed by slot. No engine
  struct changes at all. Loses nothing because the bar is a singleton and client-local.

The side table is almost certainly right, and it is the same technique
[`hero-mana`](hero-mana.md) uses for per-object state the engine has no room for.

### 8.3 Sixteen slots, and what overflows

The bar breaks at `buttonIndex >= 0x11` (`0x0092D3E5`) and the ctor only ever registered
`Hero1`..`Hero16`. Today the worst case is 1 porter group + 15 heroes. With per-template `HEROBAR`
groups the slot count is *player-controlled*: a faction with eight `HEROBAR` templates in play
silently drops heroes off the end.

The stock overflow behaviour is a silent `break` — heroes past the ceiling simply are not drawn,
and the leftover slots get `KillButtonEffects` + `SetButtonState "_unused"` at `0x0092D78D`. So the
failure is graceful, but it is a **design** decision that has to be made explicitly:

- heroes first, groups after (protects heroes, hides groups);
- groups first, heroes after (matches how the porter group behaves today);
- or raise the ceiling, which is the one place this feature *would* need `.apt` work — the movie
  must define `Hero17`+ clips, and that is outside `game.dat`.

The ordering choice is free; raising the ceiling is not.

---

## 9. Open questions

1. **The model's class size and owner.** `bar+0x10` points at `AptPalantir+0xC0`; the allocation
   site for `AptPalantir` itself was not recovered here. Every "grow the model" option in §7.2 is
   blocked on that number. Recoverable statically in under an hour; do it before committing to an
   approach.
2. **Whether `HEROBAR` should imply hero-bar eligibility on its own.** `HERO` objects reach the bar
   through `addHero`, which requires a button image from `0x0073D0BA`. A `HEROBAR` object with no
   such image would be silently dropped. That is probably the right behaviour, but it should be
   stated rather than discovered.
3. **`HERO` + `HEROBAR` on the same template.** The classifier is an if/else chain with `HERO`
   first, so a template with both would take the hero path and never group. Either document that or
   reorder — reordering changes existing behaviour for nothing, so document it.
4. **What the count means when a run spans veterancy levels.** Heroes show a rank; a group shows a
   count. Two instances of one template at different ranks share a slot and one of the ranks is
   necessarily discarded. The porter group sidesteps this by having no rank at all.
5. **`+0x18` on the model** — the porter attention counter that drives the group slot's flash. Per
   group, or global? It is incremented by porter-side code this document did not chase.
6. **Interaction with `SelectAllHeroes`.** `0x0092C080` is called from the select-all path and
   clears cycling state wholesale. With per-group cursors, "clear wholesale" needs to mean "clear
   all 16 side-table entries".

---

## 10. Verifying it in a game

Everything above is static. The list that would make it real:

1. **`KindOf = HEROBAR` parses** on an `Object` block, `-HEROBAR` unsets it, and an unpatched
   `game.dat` still rejects the token — i.e. the table really moved.
2. **`sage-patch verify` round-trips** and `detect` recovers the patch from a patched binary, and
   the patch composes with all existing `game.dat` patches in either order.
3. **One template, two instances ⇒ one slot** showing count `2`; killing one shows count `1`;
   killing both frees the slot and heroes shift down.
4. **Two templates ⇒ two slots**, each with its own icon and its own count.
5. **Clicking a group iterates within that group only**, and never selects a member of the other
   group.
6. **Clicking group A then group B** starts B's cycle from B's own beginning — the §8.2 regression.
7. **A repeat click inside the double-click window centres the camera**, per group.
8. **Porters still behave exactly as before** on the same build, including their single mixed slot.
9. **Overflow**: force more groups than slots and confirm the chosen ordering rule, with no crash
   and no blank buttons left behind.
10. **Savegame compatibility**: save on a patched build, load on a patched build; and confirm a
    stock-built save still loads, since the `xfer` blob length is unchanged.
11. **Multiplayer**: the bar is client-local (it drives selection through the ordinary message
    stream at `0x3EB`), so a patched and unpatched peer should not desync — assert it rather than
    assume it.

---

## Appendix — address table

| VA | meaning |
|---|---|
| `0x00DA0E68` | `KindOf` name table, 222 entries, NULL-terminated |
| `0x00DA4148` | `ThingTemplate` field entry `KindOf` → parse `0x006564E7`, offset `0x108` |
| `0x00DA3DB8` | `ThingTemplate` field-parse table (195 entries); `HeroSortOrder` = entry 180, offset `0x648` |
| `0x00D8AFF0` | `ObjectStatus` name table; 92 = `NO_HERO_PROPERTIES` |
| `0x0042B914` | `INI::scanIndexList` |
| `0x00444D39` | single-bit `KindOfMaskType` constructor (`memset 0x1C`) |
| `0x0044DDEC` | `Object::testStatus`, mask at `Object+0x94` |
| `0x00449681` | `TheGameLogic::findObjectByID` |
| `0x00655B0E` | `KindOf` mask parser (`+`/`-`/bare, `NONE`) |
| `0x0068B678` | `Object::getControllingPlayer` |
| `0x006AA7B2` | `Player::isLocalPlayer` |
| `0x006AAD1A` | `nameToBit` over the KindOf table |
| `0x006AC637` | `KindOfMaskType::xfer` bit loop, bound 222 |
| `0x006D4FC8` | `AptPalantir::OnHeroSelectLoaded` — builds the bar |
| `0x0073D0BA` | hero-bar button image for (template, object) |
| `0x0092BAD7` | the extra `filter=1` predicate on collected group members |
| `0x0092BBEF` | eligibility: local player && !`NO_HERO_PROPERTIES` |
| `0x0092C080` | reset the iteration round |
| `0x0092C428` | `onObjectRemoved` (tests `HERO` at `0x0092C443`, `PORTER` at `0x0092C4A8`) |
| `0x0092C734` | `addHero` — sorted insert by `HeroSortOrder` |
| `0x0092C809` | `addPorter` — append |
| `0x0092CA77` | pick the next unvisited group member |
| `0x0092CD78` | **the classifier** — `HERO` → list `+0x10`, `PORTER` → list `+0x14` |
| `0x0092CE90` | collect the porter list, filtered |
| `0x0092CF64` | `bar::update()` |
| `0x0092D346` | `nextSlot = 1` when a group was drawn |
| `0x0092D3E5` | the 16-slot ceiling |
| `0x0092D8FA` | sort group members by distance to camera |
| `0x0092D9F4` | **iterate the group** |
| `0x0092DB91` | hero-bar click handler; reads `slot[i].grouped` at `0x0092DBD6` |
| `0x0092DDE7` | bar constructor; slot array at `+0x48`, `0x18` × `0x10` |
| `0x0092E1D6` | allocating wrapper, `push 0x1E0` |
| `0x00C7EE88` | bar vtable |
