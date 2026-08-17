# `herobar` — a `HEROBAR` kindof: a hero-bar slot for something that is not a hero

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`).

**What it does.** Adds a kindof — `HEROBAR` by default, `--kindof` to rename — that puts an object
on the hero bar **without making it a `HERO`**. That is the default and the whole feature for most
callers: the object gets a slot of its own, drawn with the rank, health, highlight and flash every
other slot has, clicking it selects it, and nothing that asks "is this a hero" — armour, targeting,
the AI, scripts, `ExcludedKindOf` lists — answers differently because of it. Three detours, no
runtime state.

**`--grouped`** adds slot sharing on top: every instance of one `ThingTemplate` shares **one** slot,
two different templates take two, that slot shows **how many members the group has** where a hero's
shows its rank, and clicking it selects the members **one at a time** — click again for the next
one, or twice within `--jump-window` (500 ms by default) to **centre the camera** on the one you
just picked. Three more detours plus a two-byte tooltip fix, the count, and the cursors that make
stepping and jumping work.

Even grouped, that is deliberately not what `PORTER` does. `PORTER` collapses every porter the
player owns into a **single** slot regardless of template. The grouping key changes from *nothing*
to *the template*, and with it the number of slots stops being a constant.

The pre-implementation costing is in [`ideas/herobar-kindof.md`](herobar-kindof.md), kept as
written; this document is what shipped. The one open blocker that document records — the model's
allocation site — turned out not to need answering, because the design below never grows the model.

**Status: applies, verifies, round-trips through `detect` (mode included), composes with every
other `game.dat` patch in either order, and has been run in a game** — but everything grouping does
on a *click* or a *hover* post-dates that run and is static: the step-through click
([§3.4](#34-the-click)), the jump on a repeat click ([§3.4.1](#341-click-again-to-jump-and-why-not-right-click)),
the count badge ([§3.3.1](#331-the-count-badge)) and the tooltip fix ([§3.5](#35-the-tooltip)).
See [§7](#7-verifying-it-in-a-game).

## 1. The idea that makes it small

This section is about the grouped half. The default costs one detour and two more to clean up
after it ([§3.2](#32-removal-is-not-optional-bookkeeping)), because "put this object on the list
the draw loop already walks" is the entire implementation.

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
first entry of the next table — so [`kind_of.py`](../patches/utils/kind_of.py) rebuilds it into the
patch's cave, exactly as [`model_conditions.py`](../patches/utils/model_conditions.py) does for
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

## 3. The hooks — three, or six

| VA | size | mode | engine function | what the detour adds |
|---|---|---|---|---|
| `0x0092CD7F` | 7 | both | `onObjectAdded` | `HEROBAR` joins `HERO` on the way to the hero list |
| `0x0092C439` | 6 | both | `onObjectRemoved`, the accept gate | `HEROBAR` is a thing this function handles at all |
| `0x0092C467` | 6 | both | `onObjectRemoved`, the list pick | …and erases from the hero list, not the porter one |
| `0x0092D36F` | 6 | `--grouped` | draw-loop preheader | clear the per-pass template set |
| `0x0092D3EE` | 5 | `--grouped` | draw loop, per node | skip a drawn template; mark and count it |
| `0x0092DBD6` | 5 | `--grouped` | click dispatch | a `2` in `slot+0x16` means "step this group" |
| `0x0092BF4E` | 6 | `--grouped` | hover, the tooltip pick | …and *not* "select nearest unit" (§3.5) |

Each of the six is a `jmp rel32` padded with `nop` to cover the site exactly. The seventh is not a
detour at all: two of its bytes change, an immediate and a branch sense, and it needs no cave.

The default is not a grouped patch with grouping switched off: the bottom three sites keep the
engine's own bytes, so the draw loop and the click handler run exactly as they shipped and porters
cannot regress. `verify` asserts that too — a mode is defined as much by what it leaves alone as by
what it writes, and that is what lets `detect` report which of the two a binary carries. The
membership-only cave keeps no runtime state either, so its section goes in read-execute where the
grouped one needs `MEM_WRITE`.

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

`HERO` wins the tie *in the classifier* — but that decides nothing, because both arms end on the
same list. Under `--grouped` the draw hook asks only whether the template is `HEROBAR`, so a
template carrying both is a hero **and** groups with its own kind. (An earlier version of this
document said such a template "never groups". It does; the classifier's order is about which call
runs, not about what the draw loop later sees.)

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
    cmp  eax, 16                    ; the set is full: mark, but do not record or count
    jae  .mark
    <record the template>
    <count its members and write the count into [ebp-0x18]>   ; §3.3.1
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

### 3.3.1 The count badge

A `PORTER` slot shows how many porters there are. A group slot here shows how many members the
group has, and — this is the part that was mispriced for a long time, see [§5.1](#51-what-the-badge-cost) —
it needs no drawing code at all.

The number a hero slot draws is **one local**. `0x009D2437` fills `[ebp-0x18]` with the rank at
`0x0092D3AF`, and it is then read five more times:

| VA | read | relative to the hook |
|---|---|---|
| `0x0092D3B7` | the level-up flash compares it against `node+0xC` | **before** |
| `0x0092D3D0` | the node remembers it as its last-seen rank | **before** |
| `0x0092D4C7` | compared against the slot's cached number — equal means skip the redraw | after |
| `0x0092D501` | pushed to the `"%d"` at `0x00BDF1B0`, into `APT:_level%d.%s_Hero%dRank` | after |
| `0x0092D52D` | cached in `slot+0x08` | after |

Both flash reads happen before the hook and all three drawing reads after it, so
`mov [ebp-0x18], <count>` on the mark arm is the entire badge: the flash keeps comparing real
ranks, and the engine's own change test repaints the slot exactly when the count changes.

It is the *same* field the porter count is written to, by the *same* code shape — the earlier
reading that a badge meant hand-writing `SetButtonRankProgress` through the APT bridge confused
the progress ring (`0x0092D5BD` here, `0x0092D166` on the porter path) with the number.

Counting is the only real work. The count is not knowable when the representative is drawn, since
its duplicates come later in the same pass, so the hook walks the rest of the list itself:

```asm
    mov  [count_template], ecx
    and  dword [count], 0
    mov  edx, ebx                   ; start at this node, inclusive
.loop:
    mov  eax, [ebp-0x3c]            ; &the list head
    cmp  edx, [eax]                 ; the sentinel
    je   .done
    push edx                        ; the walker, across both calls
    push dword [edx+8] ; call 0x00449681        ; findObjectByID
    test eax, eax ; jz .next
    mov  ecx, [eax+4] ; cmp ecx, [count_template] ; jne .next
    push eax ; call 0x0092BBEF                  ; the draw loop's own eligibility gate
    test al, al ; jz .next
    inc  dword [count]
.next:
    pop  edx ; mov edx, [edx] ; jmp .loop
.done:
    mov  eax, [count] ; mov [ebp-0x18], eax
```

Three things make that exact rather than approximate:

* **Inclusive from the current node.** Any earlier node of this template would have become the
  representative instead of this one, so nothing countable sits behind the walker.
* **The same two tests the draw loop applies** — `findObjectByID` and `0x0092BBEF`. A member that
  is dead, or not the local player's, or `NO_HERO_PROPERTIES`, is one a click could not reach
  either, so counting it would put a number on the slot that the group cannot honour.
* **The clamp path skips it.** Past sixteen distinct templates the set is full and those slots are
  drawn ungrouped, one per instance; they keep the rank the engine was going to draw rather than a
  count that would contradict the bar.

Cost: one walk per *drawn group* per pass, not per node — the duplicates never reach it. `edx` is
the walker, saved around both calls, which is why the hook has two `push edx` and three `pop edx`.

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

Then it **steps**, one member per click, which is the behaviour `PORTER` has and the reason this
routine is not simply "select everything that matches". The state that makes stepping possible is
a **16-dword cursor table in the cave, indexed by slot**, each entry holding the `ObjectID` this
patch last selected out of that slot:

```asm
    template = slot.node -> findObjectByID -> obj+4
    last     = slot < 16 ? cursor[slot] : 0
    if (slot + 1 == clickSlot && last && TheGameClient->getFrame() < clickDeadline)
        obj = findObjectByID(last)           ; §3.4.1 - the same slot, clicked again
        if (obj) { TheTacticalView->lookAt(obj->getDrawable()->getPosition()) ; done }
    first = chosen = 0 ; seen = false
    for each node on the hero list:
        obj = findObjectByID(node+8)         ; a dead member is simply not found
        if (obj+4 != template) continue
        if (!0x0092BBEF(obj)) continue       ; local player && !NO_HERO_PROPERTIES
        if (!first) first = obj              ; where a wrap-around lands
        if (seen) { chosen = obj ; break }   ; the one after the cursor
        if (obj+0x74 == last) seen = true
    obj = chosen ? chosen : first
    if (!obj) done                           ; the group is empty
    if (slot < 16) cursor[slot] = obj+0x74
    clickSlot = slot + 1 ; clickDeadline = now + frames(jumpWindowMs)  ; §3.4.1
    call [TheInGameUI + 0x110]               ; deselectAllDrawables
    msg = TheMessageStream->appendMessage(0x3E9)
    msg->appendBooleanArgument(1)            ; create a new group
    msg->appendObjectIDArgument(obj+0x74)    ; exactly one member
    TheInGameUI->selectDrawable(obj->getDrawable())
    jmp 0x0092DDE1                           ; pop edi ; pop esi ; leave ; ret 4
```

Four things fall out of that shape and each is deliberate:

* **The cursor is an `ObjectID`, not a node pointer.** Nothing runs when a group member dies, so
  the cursor outlives what it names. A stale pointer would be dereferenced; a stale ID is looked
  up, not found, and the click falls back to `first` — which is also what a fresh slot and the end
  of a round look like, so one fallback covers all three.
* **The cursor is per slot, not per bar.** `PORTER`'s cycle keeps `bar+0x1DA`/`bar+0x1DC` for the
  single group the stock engine can have, and the class has no slack for one per template
  ([`ideas`](herobar-kindof.md) §8.2 prices the alternatives). A side table in the cave costs no
  engine struct change at all, and the bar is a client-local singleton so there is nothing to key
  it by beyond the slot.
* **A slot whose group changed between clicks starts over.** The cursor is not tagged with the
  template, so after a reorder the ID it holds simply matches nobody in the new group and the
  click takes `first`. Wrong-by-one at worst, and only for the click after a reorder.
* **Selection is the engine's own single-object idiom** from `0x0092DDA2`, one `ObjectID` and one
  `selectDrawable`, so a stepped member ends up selected exactly as a clicked hero does.

`0x0092DDE1` pops only `edi` and `esi`, which is correct to jump to exactly as long as the routine
has not pushed `ebx`. It never does.

### 3.4.1 Click again to jump, and why not right-click

A second click on the same slot, soon enough after the first, means **"take me there"** rather than
"next one": it centres the camera on the member the previous click selected and leaves the cursor
where it is. A slow click, a different slot, or a member that died in between all fall through and
step as normal. Nothing else changes — the first click of any pair still just selects.

*Soon enough* is **`--jump-window` milliseconds, 500 by default**, held as a dword in the cave at
`+0xB8` and scaled to logic frames at runtime the way the engine scales its own window at
`0x0092BAA4`: `fild`, `fmul` against the milliseconds-to-frames float at `0x00D9F624`, and MSVC's
`_ftol` at `0x00A3CFA4`. `--jump-window 0` makes the window zero frames, which turns the gesture
off and leaves every click a step. `now` comes from `TheGameClient`'s `getFrame` (`[0xDE4388]`,
vtable `+0x7C`), and the camera move is the porter's own pair: the drawable's position through
`0x00676711`, into `TheTacticalView::lookAt` (`[0xDE447C]`, vtable `+0x54`).

Because the setting is *data* and not code — one word, with byte-identical routines around it —
`detect` reads it back out of the image rather than trying values against `verify`.

**Why the window is this patch's own constant.** The obvious value to share is the one the porter's
identical-looking question uses: `SelectNearestBuilderCycleTimeOut`, `TheInGameUI+0x988`, which the
engine converts in the routine at `0x0092BA91`. An earlier version of this patch called that
routine and read its answer back. Both halves of that were wrong.

*The value is the wrong quantity.* It is **3500 ms** on this data. That is a sensible length for a
porter *round* to stay open — you press the button, walk your eyes across the base, press it again —
and roughly seven times too long for "was that a double click". A gesture window and a round
timeout are different things that happen to be read by similar-looking comparisons, and sharing the
number because the comparison rhymes is the mistake.

*The answer is not at a fixed address.* `0x0092BA91` **stores** into `bar+0x1DC`, which sits past
the slot array — and [`hero-bar-slots`](hero-bar-slots.md) grows that array in place and slides
everything after it up by `(count-16)*0x18`. On a 25-slot bar `bar+0x1DC` is not the deadline at
all: it is byte `0x14` of *slot 16*. So on that combination the window came out of a slot's cached
bytes (the repeat click essentially never fired) **and** the porter's real deadline, by then at
`bar+0x2B4`, was overwritten by the call and never put back.

Emitting the scaling costs about twenty bytes and leaves this patch reading nothing off the bar
object except the slot array itself, which does not move.

One difference from the porter, deliberately: the porter cycle asks `0x0092BB2A` whether the object
is already on screen and skips the camera if it is. Here the second click *is* the request, so it
moves the camera either way.

**Why not "left selects, right jumps"**, which is the obvious shape for this. The mouse button is
not available at this hook. `_OnBttnHeroSelect` is registered as a *named engine function the movie
calls* (`bar+0x14`, bound at `0x0092DED9`), and the movie hands it one argument: the button's path,
`"Hero3"`. The APT runtime's event vocabulary is Flash's, interned at `0x00B20E40`: `onMouseWheel`,
`onPress`, `onRelease`, `onReleaseOutside`, `onRollOut`, `onRollOver`. There is no right-button
event on that path and no button state reaches the callback, so the two clicks cannot be told
apart here at all.

Doing it properly would mean intercepting the right button in the engine's own input path and
working out which slot the cursor is over. That is not hopeless — the hover handler of
[§3.5](#35-the-tooltip) is called with `{bar, slot}` and could record it — but it needs a
right-click site that fires while the cursor is over the palantir, which has not been found. Until
it is, a repeat click is the gesture.

Past slot 16 both the cursor read and the cursor write are skipped rather than clamped into a
neighbour's entry, so on a bar widened by [`hero-bar-slots`](hero-bar-slots.md) a group in slot 17
or beyond always selects its first member. That matches how the per-pass set degrades on the same
bar, and neither corrupts anything.

### 3.5 The tooltip

Hovering a hero-bar button reaches a small per-button functor — `{bar, slot}`, built at
`0x0092C385`, its one virtual method at `0x0092BF34` through the thunk at `0x0092C420`. It picks
which tooltip to show off **the same `slot+0x16` byte the click dispatches on**, and it reads that
byte as a flag rather than as a kind:

```asm
0092bf41  eax = bar + 0x48 + slot*0x18        ; the slot
0092bf4e  cmp  byte [eax+0x16], 0
0092bf52  je   0x0092BFAA                     ; plain: build the tooltip from slot.node's object
          ; else: look up the command button "NonCommand_SelectNearestBuilder" (0x0071D6EA)
          ;       and show its text — "select nearest unit"
```

So a `2` inherited the porter's tooltip along with its own click behaviour: hovering a `HEROBAR`
group said *select nearest unit* instead of naming the unit. Narrowing the test to
`cmp ..., 1 ; jne` fixes it in **two bytes** and no cave — `1` is still the porter group, and `0`
and `2` both take the arm that builds the tooltip from the slot's own node, which is the
representative's object, described exactly as a hero's slot describes its hero.

That edit is `--grouped` only, because nothing writes a `2` without grouping, and `verify` asserts
the site holds stock bytes in the other mode.

## 4. What it does *not* need

* **No `.apt` edit and no ActionScript.** A group slot is drawn through the same
  `_level%d.%s_Hero%dImage` / `SetButtonRankProgress` / `SetButtonHealthBar` calls a hero slot is.
* **No new model list, no `Object` or `ThingTemplate` growth, no savegame change.** The one bit is
  inside the existing mask, and the cave holds the only new state — including the per-slot cursor
  that `PORTER` keeps on the bar object, where there is no room for more than one.
* **No init or destroy hook.** The cave's scratch words are zero in the image; the emitted set is
  rewritten at the top of every draw pass and a zero cursor already means "nothing picked yet".
* **Nothing at all, for the default.** Membership installs three detours and no state: the cave is
  the rebuilt name table, the new name, and about sixty bytes of code.

## 5. What it costs

Everything here is about `--grouped`; the default costs the kindof bit and nothing else.

* **No rank survives on a group slot.** The number is the member count
  ([§3.3.1](#331-the-count-badge)), so two instances at different veterancy show `2` and neither
  level is readable from the bar. The health bar and the progress ring still come from the
  representative. A group of one shows `1`, exactly as a lone porter's slot does — see
  [§5.1](#51-what-the-badge-cost) for why that is a judgement rather than a mechanism.
* **A repeat click always centres**, where the porter cycle asks `0x0092BB2A` whether the object is
  on screen first and skips the camera if it is. The second click is an explicit request here, so
  it is honoured either way. ([§3.4.1](#341-click-again-to-jump-and-why-not-right-click))
* **No right-click gesture.** The mouse button does not reach this hook at all — §3.4.1.
* **The representative is whichever member sorts first**, so the icon a group shows can change
  when that member dies, even though the group did not.
* **The bar is still 16 slots.** Groups consume slots, so enough distinct `HEROBAR` templates in
  play push heroes off the end. The overflow at `0x0092D3E5` is graceful — it jumps to the loop's
  own "next node" label, and since that label leaves the slot cursor alone, every later node
  skips too, so it behaves as a `break`. Nothing crashes, the extra heroes are simply not drawn,
  but which side gets cut is now player-controlled rather than fixed. Raising the ceiling past 16
  is the one change that would need real `.apt` work.
* **Slot order is `HeroSortOrder`.** `HEROBAR` objects go through `addHero`, whose sorted insert
  keys on `ThingTemplate+0x648`. A `HEROBAR` template with no `HeroSortOrder` sorts as 0.

### 5.1 What the badge cost

Worth recording, because this document priced it wrongly for a long time and the error is
instructive. It said a badge meant "write `SetButtonRankProgress` from the cave — a call through
the APT bridge with an `AsciiString` temporary, and a much bigger patch". **Both halves were
wrong**, and the mistake was reading the porter block and assuming the hero block was different.

`SetButtonRankProgress` (`0x0092D5BD` on the hero path, `0x0092D166` on the porter one) draws the
**progress ring**, not the number. The number is a *text* write to `APT:_level%d.%s_Hero%dRank`,
and both paths make it identically — the porter count at `0x0092D207`, the hero rank at
`0x0092D4F3` — down to sharing the wide `"%d"` at `0x00BDF1B0`. The hero path was already drawing
a number into the field the porter path puts its count in, from a local this patch's hook is
standing in front of. [§3.3.1](#331-the-count-badge) is what it turned into: about 60 bytes of
cave, one `mov`, and a walk.

What it actually costs, now that it is in:

* **A walk per drawn group per pass** — `findObjectByID` + `0x0092BBEF` per remaining node, the
  same two calls the draw loop itself makes. O(list) per group on every `update()` against O(1)
  before, which at hero-bar list sizes is nothing, but it is the one recurring cost. If it ever
  matters, counting in the previous pass and reading it in this one is free and one frame stale.
* **A group of one shows `1`.** `PORTER` behaves the same way — a lone porter's slot shows `1` —
  so this is consistent with the engine rather than with a hero slot. It is the one thing here
  that is a judgement rather than a mechanism.
* **A veteran member's rank is no longer readable from the bar.** The health bar and the progress
  ring still come from the representative; only the number changed meaning.

**Static.** The addresses and the reasoning are read out of the binary; nothing about the badge
has been run in a game.

## 6. Composition

Order-independent with every other patch here. It allocates its cave with `allocate_section` and
locates it with `find_section`, and it is the only patch that touches the kindof table or any of
the seven sites.

Neither mode composes with the *other* mode: both claim `.hbar` and both add the same kindof, so
applying one to a binary that carries the other fails at `allocate_section`. The two are choices,
not layers.

The one it has to *stay* clear of is [`hero-bar-slots`](hero-bar-slots.md), which grows the slot
array in place and slides every field after it up. Nothing here reads past the array —
`bar+0x10` (the model) is before it and the slot addressing is index-scaled — so a wider bar
changes no address this patch assumes, in either order. §3.4.1 is the one place that had to be
written that way on purpose.

The other interaction worth naming is with a *future* second kindof-adding patch. `verify` reads the
bit and the end of the table out of **the cave's own copy**, never the live one, so a later patch
that appends to the table and becomes the live one leaves this patch correctly installed and still
verifiable. The live table is consulted only to confirm it still agrees.

## 7. Verifying it in a game

The list. Items **4 to 8** are the ones outstanding — everything grouping does on a click or a
hover post-dates the run that cleared the rest:

1. **`KindOf = HEROBAR` parses** on an `Object` block, `-HEROBAR` unsets it, and an unpatched
   `game.dat` still rejects the token — i.e. the table really moved.
2. **Default: one object, one slot.** A `HEROBAR` unit that is not a `HERO` appears on the bar,
   with its own icon, rank and health bar, and clicking it selects that one object. Two instances
   take two slots — the grouping is the *other* build, not this one.
3. **`--grouped`: one template, two instances ⇒ one slot.** Killing one leaves the slot; killing
   both frees it and the heroes below shift up. Two templates ⇒ two slots, each with its own icon.
4. **The slot counts.** Two instances show `2`; build a third and it becomes `3` **without a
   reload**, which is the engine's own change test firing on the new number. Kill one and it drops.
   A group of one shows `1`. A member that is not the local player's, or is `NO_HERO_PROPERTIES`,
   is **not** counted — the number has to match what the clicks can reach, item 5.
5. **Clicking a group steps.** Click once: the first member is selected, alone. Click again *after
   the jump window has closed* — half a second on the default: the next one, and nothing of the
   previous. Click past the last: back to the first. Never a member of the other group, and never
   two at once. As many distinct members as the badge claims.
6. **Clicking twice quickly jumps.** The second click centres the camera on the member the first
   one selected and does **not** advance — then a later click advances as normal. Clicking slot A
   then slot B quickly must *step* B rather than jump, since it is a different slot.
7. **Hovering a group names the unit.** The tooltip is the representative's own, not
   *"select nearest unit"* — and hovering the **porter** slot on the same build still says exactly
   that, which is the §3.5 edit not having gone one value too far.
8. **The cursor survives the group changing.** Kill the member a slot is parked on, then click:
   the click has to land on a live member rather than doing nothing. Same for clicking group A,
   then B, then A — A resumes where it was, which is the per-bar cursor's failure if the table
   were not per slot.
9. **A dead group member leaves the list.** Build and kill the same `HEROBAR` unit repeatedly and
   confirm the bar does not accumulate stale slots — the §3.2 failure, if either removal hook is
   wrong. Worth doing on **both** builds; the removal pair is shared.
10. **Porters still behave exactly as before** on the same build: their single mixed slot, its
    count badge, its tooltip, its click-to-iterate, its camera centring, and its *round timing* —
    which this patch no longer touches at all now that it computes its own window (§3.4.1), but
    which is worth confirming precisely because an earlier version did.
11. **A hero that is also `HEROBAR`** groups with its own kind and counts — §3.1, and *not* what an
    earlier draft of this document predicted.
12. **Overflow**: force more distinct `HEROBAR` templates than slots and confirm no crash, no blank
    buttons left behind, and that the templates past the sixteenth show a rank rather than a count.
13. **Savegame**: save and load on a patched build; and confirm a stock-built save still loads,
    since the `xfer` blob length is unchanged.
12. **Multiplayer**: the bar is client-local and selection goes through the ordinary message
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
| `0x00676711` | `Drawable::getPosition` |
| `0x00A3CFA4` | MSVC `_ftol` — `st(0)` truncated into `eax` |
| `0x00D9F624` | the milliseconds-to-logic-frames float the repeat window is scaled by |
| `0x0092BA91` | the engine's own deadline routine — the arithmetic §3.4.1 re-emits, **not** called |
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
