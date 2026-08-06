# `herobar` — a `HEROBAR` kindof that groups a template's instances into one slot

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`).

**What it does.** Adds a kindof — `HEROBAR` by default, `--kindof` to rename — that puts an object
on the hero bar in a slot **shared with every other instance of the same `ThingTemplate`**. Two
instances of one template: one slot. Two instances of two templates: two slots. Clicking a grouped
slot selects the whole group.

That is deliberately not what `PORTER` does. `PORTER` collapses every porter the player owns into
a **single** slot regardless of template, and clicking it walks the mixed set one object at a time.
The grouping key changes from *nothing* to *the template*, and with it the number of slots stops
being a constant.

The pre-implementation costing is in [`ideas/herobar-kindof.md`](ideas/herobar-kindof.md), kept as
written; this document is what shipped. The one open blocker that document records — the model's
allocation site — turned out not to need answering, because the design below never grows the model.

**Status: applies, verifies, round-trips through `detect`, and composes with every other
`game.dat` patch in either order. It has not been run in a game** — see
[§7](#7-verifying-it-in-a-game).

## 1. The idea that makes it small

The obvious implementation is a second object list plus a second copy of the group-drawing code.
The drawing block is ~770 bytes of straight-line calls into the APT bridge, each building an
`AsciiString` temporary with exception-unwind state; hand-assembling it into a cave is both the
bulk of the work and the bulk of the risk.

None of it is necessary. The draw loop already emits one slot per node of the hero list, sorted,
with image, rank, health, highlight and flash. So this patch puts `HEROBAR` objects on **that**
list and changes only which nodes reach a slot:

* before the loop, clear a set of templates drawn this pass;
* per node, if its template is `HEROBAR` and already in the set, jump to the engine's own
  *ineligible* label — which advances to the next node **without consuming the slot**;
* otherwise record the template and mark the slot it is about to fill.

The engine draws the representative. The duplicates simply never reach a slot. No drawing code is
added, and the `.apt` movie is untouched.

The skip target is what makes this work. `0x0092D76F` is where the stock loop goes when
`0x0092BBEF` rejects an object (wrong player, or `NO_HERO_PROPERTIES`): it decrements the node's
flash countdown and advances, leaving the slot cursor `[ebp-0x24]` and the slot pointer `edi`
alone. A duplicate needs exactly that.

## 2. The kindof

`KindOfMaskType` is 7 dwords / 224 bits and the stock name table holds 222 names, so bits 222 and
223 are free. A 223rd kindof therefore costs **no data growth anywhere**: not in `ThingTemplate`
(the mask is a fixed `0x1C` bytes at `+0x108`), not in `Object`, and not in the savegame, because
`KindOfMaskType::xfer` packs bit-by-bit into a `0x1C`-byte blob that already covers 224.

Two independent confirmations of the width:

| site | evidence |
|---|---|
| `0x00655B3F` | `push 0x1C` → `memset(mask, 0, 0x1C)` on `KindOf = NONE` |
| `0x00444D39` | `push 0x1C` → the single-bit `KindOfMaskType` constructor |

The table cannot grow in place — `0x00DA11E0` is its terminator and `0x00DA11E4` is already the
first entry of the next table — so [`kind_of.py`](../patches/kind_of.py) rebuilds it into the
patch's cave, exactly as [`model_conditions.py`](../patches/model_conditions.py) does for
`ModelConditionFlags`. It is the smaller job of the two: **14 references** against that table's 16,
and **6 counts** against its 10.

The INI parse path is not one of the six. `INI::scanIndexList` (`0x0042B914`) walks to the
terminator, so `KindOf = HEROBAR` would parse from a table grown without touching a single count.
The six sites are the ones that enumerate or bounds-check by index:

| VA | bounds |
|---|---|
| `0x006AACEA` | `getCount()` — **dead**, nothing calls it or holds it in a vtable |
| `0x006AC637` | `xfer`'s bit-packing loop |
| `0x006ACBD5` | the name-list builder |
| `0x007079F5` | `getKindOfName(index)`'s range check |
| `0x00762A35` | editor/script list population |
| `0x007B58FD` | the script-condition text, `"Kind is '%s'"` |

`0x007B3CDB` is worth a note because it looks like a false positive and is not: it sits directly
after a byte table, but `0x007B3CDA` really is a six-byte `mov eax, <table>; ret` accessor. Like
`getCount`, nothing calls it. Both are repointed and raised anyway — "unreferenced today" is not a
reason to leave a stale answer behind.

**Only one bit is left after this.** A second kindof-adding patch fits; a third does not, and
widening the mask is an `Object` and `ThingTemplate` layout change rather than a byte patch.

## 3. The six hooks

| VA | size | engine function | what the detour adds |
|---|---|---|---|
| `0x0092CD7F` | 7 | `onObjectAdded` | `HEROBAR` joins `HERO` on the way to the hero list |
| `0x0092C439` | 6 | `onObjectRemoved`, the accept gate | `HEROBAR` is a thing this function handles at all |
| `0x0092C467` | 6 | `onObjectRemoved`, the list pick | …and erases from the hero list, not the porter one |
| `0x0092D36F` | 6 | draw-loop preheader | clear the per-pass template set |
| `0x0092D3EE` | 5 | draw loop, per node | skip a template already drawn; mark the slot |
| `0x0092DBD6` | 5 | click dispatch | a `2` in `slot+0x16` means "select this whole group" |

Each is a `jmp rel32` padded with `nop` to cover the site exactly.

### 3.1 The classifier

The stock code is 42 bytes and has no padding after it, so the third branch goes in a cave:

```asm
0092cd78  mov  edx, [esp+4]              ; Object*
0092cd7c  mov  eax, [edx+4]              ; -> ThingTemplate
0092cd7f  test byte [eax+0x113], 4       ; KindOf bit 90  = HERO      <-- replaced
0092cd86  je   0x92cd90
0092cd88  push edx ; call 0x92c734       ; -> hero list   (model+0x10)
0092cd90  test byte [eax+0x119], 0x80    ; KindOf bit 143 = PORTER
0092cd99  push edx ; call 0x92c809       ; -> porter list (model+0x14)
```

The detour re-tests `HERO`, then `HEROBAR`, and re-enters at **the engine's own two arms** —
`0x0092CD88` for the hero path, `0x0092CD90` for the stock `PORTER` test. Neither the `je` nor
either call is touched.

`HERO` wins a tie: a template carrying both is a hero and never groups. Documented rather than
reordered, because reordering would change shipped behaviour for nothing.

### 3.2 Removal is not optional bookkeeping

`onObjectRemoved` (`0x0092C428`) gates on `HERO`, then falls to `PORTER`, and ignores anything
that is neither. A `HEROBAR` object would therefore be added and never removed: its node would sit
on the hero list forever, `findObjectByID` would return null for it, and the draw loop's
`0x0092D392` would skip it — no crash, but an unbounded list and a group whose members cannot be
found.

Both hooks rejoin *before* the engine's own `jne`/`je`, so what they have to get right is the
**flags**, not a target:

```asm
remove_gate:
    test dword [eax+0x110], edi     ; the displaced HERO test
    jz   .herobar
    jmp  0x0092C43F                 ; ZF=0 -> the engine's jne takes the hero path
.herobar:
    test byte [eax+0x123], 0x40     ; HEROBAR
    jmp  0x0092C43F                 ; ZF now reflects HEROBAR
```

`jz` and `jmp` do not write flags, so the last `test` executed is the one the engine reads. The
list-pick hook at `0x0092C467` has the same shape through `esi`.

### 3.3 The draw pass

The preheader at `0x0092D36F` runs once per pass — the back edge re-enters at `0x0092D37F`, past
it — which makes it the right place to clear the set.

The per-node hook sits at `0x0092D3EE`, **after** the engine's eligibility check (`0x0092D3DC`)
and slot ceiling (`0x0092D3E8`), so a node that reaches it is one the engine was about to draw.
It borrows `eax`, `ecx` and `edx`, and both ways out pop all three:

```asm
per_node:
    push eax ; push ecx ; push edx
    mov  ecx, [ebp-0x20]            ; Object*
    mov  ecx, [ecx+4]               ; ThingTemplate*
    test byte [ecx+0x123], 0x40     ; HEROBAR?
    jz   .plain
    <linear scan of the emitted set; on a hit -> .dup>
    <else record it>
.mark:
    mov  byte [edi+0x12], 2         ; slot+0x16 = "this slot is a group"
    jmp  .resume
.plain:
    mov  byte [edi+0x12], 0
.resume:
    pop edx ; pop ecx ; pop eax
    cmp  ebx, [edi-4]               ; the displaced instruction
    jne  0x0092D3F3                 ; draw the slot from scratch
    jmp  0x0092D425                 ; the slot already shows this node
.dup:
    pop edx ; pop ecx ; pop eax
    jmp  0x0092D76F                 ; next node, no slot consumed
```

`edi` reaches the loop already biased by 4 (`lea edi, [eax+esi+0x4c]` against a slot base of
`+0x48`), so `slot+0x16` is `[edi+0x12]` and the node is `[edi-4]`.

Both arms write the group byte. Clearing it on the non-`HEROBAR` arm is what stops a slot that
held a group last pass from dispatching a group click after an ordinary hero moves into it.

The emitted set is 16 dwords and a length, in the cave. Sixteen because that is the whole bar; the
scan is linear and runs at most once per drawn slot.

### 3.4 The click

The stock dispatch is two-way — `0` selects one object, non-zero runs the porter cycle. It becomes
three-way, reading the byte twice rather than caching it in a register so that both stock arms
receive exactly the registers they expect:

```asm
click:
    cmp  byte [ecx+esi+0x5e], 2 ; je -> the group routine
    cmp  byte [ecx+esi+0x5e], 0 ; jne -> 0x0092DBDD, the porter cycle
    jmp  0x0092DBEB             ; the single-object select
```

The group routine resolves the clicked slot's node, then **validates it against the live list**
before dereferencing it. A slot's node pointer is only as fresh as the last draw pass, and the
stock cleanup at `0x0092D78D` sets leftover buttons to `_unused` without clearing their cache; the
walk costs one traversal and removes any chance of handing a freed pointer to `findObjectByID`.

Selection copies the engine's own idiom from the hero bar's single-object path at `0x0092DDA2`,
with the member loop appending one `ObjectID` per match instead of one in total:

```asm
    call [TheInGameUI + 0x110]      ; deselectAllDrawables
    msg = TheMessageStream->appendMessage(0x3E9)
    msg->appendBooleanArgument(1)   ; create a new group
    for each node whose template matches and which 0x0092BBEF accepts:
        msg->appendObjectIDArgument(obj+0x74)
        TheInGameUI->selectDrawable(obj->getDrawable())
    jmp 0x0092DDE1                  ; pop edi ; pop esi ; leave ; ret 4
```

`0x0092DDE1` pops only `edi` and `esi`, which is correct to jump to exactly as long as the routine
has not pushed `ebx`. It never does.

## 4. What it does *not* need

* **No `.apt` edit and no ActionScript.** A group slot is drawn through the same
  `_level%d.%s_Hero%dImage` / `SetButtonRankProgress` / `SetButtonHealthBar` calls a hero slot is.
* **No new model list, no `Object` or `ThingTemplate` growth, no savegame change.** The one bit is
  inside the existing mask, and the cave holds the only new state.
* **No per-group cursor.** Selecting the whole group is stateless; the iterate-one-at-a-time
  behaviour `PORTER` has is what would need one, and that is the axis this kindof does not share.
* **No init or destroy hook.** The cave's scratch words are zero in the image and rewritten at the
  top of every draw pass.

## 5. What it costs

* **No count badge.** A `PORTER` slot shows how many porters there are, because the porter path
  writes the count where a hero's rank goes. Here the engine draws the representative unmodified,
  so a group slot shows *its* rank and health. A badge means writing `SetButtonRankProgress` from
  the cave — a call through the APT bridge with an `AsciiString` temporary, and a much bigger
  patch.
* **A group has a count where a hero has a rank.** Two instances of one template at different
  veterancy share a slot and one of the ranks is necessarily discarded. `PORTER` dodges this by
  having no rank at all; `HEROBAR` units will not.
* **The bar is still 16 slots.** Groups consume slots, so enough distinct `HEROBAR` templates in
  play push heroes off the end. The stock overflow is a graceful `break` at `0x0092D3E5` — nothing
  crashes, the extra heroes are simply not drawn — but which side gets cut is now
  player-controlled rather than fixed. Raising the ceiling past 16 is the one change that would
  need real `.apt` work.
* **Slot order is `HeroSortOrder`.** `HEROBAR` objects go through `addHero`, whose sorted insert
  keys on `ThingTemplate+0x648`. A `HEROBAR` template with no `HeroSortOrder` sorts as 0.

## 6. Composition

Order-independent with every other patch here. It allocates its cave with `allocate_section` and
locates it with `find_section`, and it is the only patch that touches the kindof table or any of
the six hook sites.

The one interaction worth naming is with a *future* second kindof-adding patch. `verify` reads the
bit and the end of the table out of **the cave's own copy**, never the live one, so a later patch
that appends to the table and becomes the live one leaves this patch correctly installed and still
verifiable. The live table is consulted only to confirm it still agrees.

## 7. Verifying it in a game

Everything above is static. The list that would make it real:

1. **`KindOf = HEROBAR` parses** on an `Object` block, `-HEROBAR` unsets it, and an unpatched
   `game.dat` still rejects the token — i.e. the table really moved.
2. **One template, two instances ⇒ one slot.** Killing one leaves the slot; killing both frees it
   and the heroes below shift up.
3. **Two templates ⇒ two slots**, each with its own icon.
4. **Clicking a group selects every member of that template and nothing else** — in particular no
   member of the other group.
5. **A dead group member leaves the list.** Build and kill the same `HEROBAR` unit repeatedly and
   confirm the bar does not accumulate stale slots — the §3.2 failure, if either removal hook is
   wrong.
6. **Porters still behave exactly as before** on the same build, including their single mixed slot
   and its click-to-iterate.
7. **A hero that is also `HEROBAR`** takes the hero path and does not group.
8. **Overflow**: force more distinct `HEROBAR` templates than slots and confirm no crash and no
   blank buttons left behind.
9. **Savegame**: save and load on a patched build; and confirm a stock-built save still loads,
   since the `xfer` blob length is unchanged.
10. **Multiplayer**: the bar is client-local and selection goes through the ordinary message
    stream, so a patched and an unpatched peer should not desync — assert it rather than assume it.

## 8. Key addresses

| VA | meaning |
|---|---|
| `0x00DA0E68` | `KindOf` name table, 222 entries, NULL-terminated |
| `0x00DA4148` | `ThingTemplate` field entry `KindOf` → parse `0x006564E7`, offset `0x108` |
| `0x0042B914` | `INI::scanIndexList` — the terminator-driven token lookup |
| `0x00444D39` | single-bit `KindOfMaskType` constructor (`memset 0x1C`) |
| `0x00449681` | `TheGameLogic::findObjectByID` |
| `0x00655B0E` | the `KindOf` mask parser (`+`/`-`/bare, `NONE`) |
| `0x0070E013` | `Object::getDrawable` |
| `0x00711104` | `GameMessage::appendBooleanArgument` |
| `0x0071111A` | `GameMessage::appendObjectIDArgument` |
| `0x0092BBEF` | hero-bar eligibility: local player && !`NO_HERO_PROPERTIES` |
| `0x0092C428` | `onObjectRemoved` |
| `0x0092C734` | `addHero` — sorted insert by `HeroSortOrder` (`ThingTemplate+0x648`) |
| `0x0092CD78` | `onObjectAdded` — the classifier |
| `0x0092CF64` | the hero bar's `update()` |
| `0x0092D3E5` | the 16-slot ceiling |
| `0x0092D76F` | the loop's "next node, no slot consumed" label |
| `0x0092DB91` | the hero-bar click handler |
| `0x0092DDE1` | its epilogue (`pop edi ; pop esi ; leave ; ret 4`) |
| `0x00DE412C` / `0x00DE4830` / `0x00DE6398` | `TheGameLogic` / `TheInGameUI` / `TheMessageStream` |
