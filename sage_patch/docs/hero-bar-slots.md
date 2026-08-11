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

## 7. Verifying it in a game

Everything above is static. The list that would make it real:

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

The `.apt` half is the precondition for all of it: the movie must define `Hero<n>` and
`FlashEffect<n>` clips for every new slot, in each frame state the stock sixteen appear in
(`_fadein` places them, `_show` reveals them). `sage_apt` is the tooling for that.

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
