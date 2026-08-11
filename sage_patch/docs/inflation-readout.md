# Showing the current inflation penalty in the palantir

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), read from the repo's
clean `game.dat`. This is the writeup for the **`inflation-readout`** patch,
[`patches/inflation_readout.py`](../patches/inflation_readout.py), with the cross-patch link in
[`patches/utils/income_link.py`](../patches/utils/income_link.py) and the tests in
[`tests/sage_patch/test_inflation_readout.py`](../../tests/sage_patch/test_inflation_readout.py).

**What it does.** The local player's current *income* multiplier — the per-resource-building
"inflation" every Edain faction sets via `ResourceModifierValues`, **times
[`command-point-upkeep`](command-point-upkeep.md)'s factor when that patch is also installed** —
is drawn live in the palantir's **resource-multiplier** readout, which in a skirmish is an
existing, already-blank slot. `x0.7` while 30% of income is being taken, `x0.765` with a −15%
inflation and a −10% upkeep, and blank when nothing is being taken.

```sh
sage-patch apply inflation-readout --in game.dat.backup --out game.dat   # no parameters
sage-patch verify inflation-readout game.dat
```

**Status: built and static-verified; not yet runtime-verified in a game.** The bytes apply,
disassemble as intended, verify, `detect` round-trips, and the link with `command-point-upkeep` is
asserted in both application orders. Everything that needs a running game is still open — see
[§8](#8-verifying-it-in-a-game), starting with whether the field is placed in the skirmish
palantir layout at all.

**For a HUD feature it is remarkably small** — one 13-byte detour and a 286-byte section (270
bytes of code plus a 16-byte header holding one import slot). Only
[`science-prereqs`](science-forward-references.md)' permissive tier is smaller. **No new INI
field**,
so no field-table rebuild and no `sage_ini` surface. **No new format string**, because the
engine's own builder already formats a float as `x%g` and already blanks itself at exactly `1.0`.
**No `.apt` edit and no `.csf` edit**, for the same reason [`second-resource`](second-resource.md)
and [`command-point-upkeep`](command-point-upkeep.md) need none. No savegame change, no init hook,
no INI parsing, client-local and read-only throughout. Compare `command-point-upkeep`, which
needed four edits, a rebuilt `PlayerTemplate` field table, a 128-row name-keyed store and its own
INI parse function to move one number.

The one thing that is *not* free is the per-refresh object walk — see [§5](#5-the-cost-that-is-not-free).

## 1. The number

`PlayerTemplate.ResourceModifierValues` is read in exactly one place, `AutoDepositUpdate::update`
(`0x008854D3`), and [`command-point-upkeep`](command-point-upkeep.md#1-the-mechanic-it-rides-on)
already documents the site. The whole computation, `0x008855A3`–`0x0088564B`:

```asm
008855a3  mov  eax, [esi+0x34]              ; esi = controlling Player -> its PlayerTemplate
008855a6  movss xmm0, [0xbd1908]            ; mult = 1.0f  (the default, no penalty)
008855ae  lea  ecx, [eax+0x1c8]             ; &tmpl->resourceModifierFilter
008855bc  call 0x762977                     ; ObjectFilter::isValid          -> bail, mult stays 1
008855ce  call 0x7640c1                     ; filter.allow(thisObject, player) -> bail
008855da  and  [ebp-0x24], 0                ; ctx.count  = 0
008855de  mov  [ebp-0x28], eax              ; ctx.filter = &the filter
008855e5  push 0x885230 / push &ctx
008855ec  call 0x6ababd                     ; Player::forEachTeamObject      (ret 8)
008855f7  add  eax, 0x1cc                   ; &tmpl->resourceModifierValues
00885601  sub eax, ecx / sar eax, 2         ; n = values.size()
00885606  cmp  edx, eax                     ; edx = count
0088560a  in range : mult = values[count] * 0.01f                            ; [0xbe5600]
0088561e  past end : mult = values[n-1] * 0.01f - (count - n) * 0.02f, floor 0  ; [0xbdc320]
```

So, as a formula, and note that **every matching building of a player gets the same multiplier** —
the count does not depend on which building is depositing, which is what makes this a *per-player*
number worth putting on the HUD at all:

```
count = #{ o in player's team objects : !o->testStatus(2) && filter.allow(o, NULL) }
n     = values.size()
mult  = count < n ? values[count] * 0.01f
                  : max(0, values[n-1] * 0.01f - (count - n) * 0.02f)
```

| what | VA | shape |
|---|---|---|
| `ObjectFilter::isValid` | `0x00762977` | thiscall, no arguments, returns `bool` |
| `ObjectFilter::allow(object, player)` | `0x007640C1` | thiscall, `ret 8` |
| `Player::forEachTeamObject(fn, ctx)` | `0x006ABABD` | thiscall, `ret 8`, walks `Player+0x34C` |
| the counting callback | `0x00885230` | cdecl `(Object*, void *ctx)`; `ctx = { ObjectFilter*; Int count; }` |
| `PlayerList::getLocalPlayer` | `0x006A8839` | thiscall on `ThePlayerList` (`0x00DE4928`) |

Two details the callback settles, both worth stating because they make the HUD number *exactly*
the deposit's number rather than approximately it: it skips objects failing `testStatus(2)`
(`0x0044DDEC`), and it calls `allow(o, NULL)` — a null player — where the gate three instructions
earlier calls `allow(o, player)`. Reusing the engine's own callback rather than writing one
inherits both.

## 2. The display slot, and why it is already free

`APT:PalantirResourceMultiplier` (`0x00C4E5C4`) has **one** reference in the image, at
`0x0080086A`, inside a text builder at `0x00800844` — the same shape as the command-point builder
`0x0080078F` sitting immediately above it in the same compiland:

```asm
00800844  <fn>(float mult) -> bool          ; one argument, at [ebp+8]
00800880  and  [ebp-0x10], 0
00800884  movss xmm0, [ebp+8]
00800889  ucomiss xmm0, [0xbd1908]          ; == 1.0f exactly?
0080089b  jnp  0x8008b8                     ;   yes -> the blank placeholder
0080089d  fld  [ebp+8] / fstp qword [esp]   ;   no  -> promote to double
008008a8  push 0xc4e5bc                     ;          L"x%g"
008008ae  call 0xadf750                     ;          UnicodeString::format
008008b8  push 0xbd16e4                     ; L" "     (the blank)
008008d2  call 0x624ffd                     ; TheAptPlayer::setValue("APT:PalantirResourceMultiplier", …)
```

Three things fall out of that, and together they are the whole idea:

- **The slot draws a float, formatted by the engine, every refresh.** A mod's `.csf` entry of the
  same name is a design-time placeholder exactly as for the other two readouts — Edain's
  `Lotr.csv` carries `apt:palantirresourcemultiplier;x23`. So no data edit can produce the number,
  and none is needed either.
- **`L"x%g"` is already the right format.** `0.7f` prints as `x0.7`, `0.65f` as `x0.65`. `%g` at
  six significant digits absorbs the `0.01f` representation error (`70 * 0.01f` is
  `0.699999988…`, which prints `0.7`).
- **The builder blanks itself at exactly `1.0f`**, so "no penalty" needs no special case and looks
  identical to the stock game. This is load-bearing and it is *not* luck-of-the-rounding: `0.01f`
  is `0.00999999977648258…`, and `100.0f * 0.01f` rounds to `1.0f` exactly (the product is
  `2.2e-8` from `1.0` and `3.7e-8` from the next float below it). A table entry of `100` therefore
  blanks. Worth an assertion in the tests and a look in game.

**The field exists in the movie.** `Palantir.apt` inside `__edain_apt.big` (entry at `0xEFAC4`,
396268 bytes) carries the name at `0x1505FD`, and `___edain_apt_widescreen.big` carries it too. So
`setValue` has somewhere to land. What is *not* proven statically is that the field is positioned
and visible in the skirmish layout rather than only in the War-of-the-Ring one — that is verify
item 1.

### Who owns the slot today

The palantir refresh at `0x006D577C` computes the float and drives the builder through its own
change filter:

```asm
006d597c  cmp  [ebp-1], 0                   ; the WotR "live region battle" flag
006d5980  jne  0x6d59c4                     ;   yes -> the animated widget path
006d598f  mov  eax, [0xde4950]              ;   no  -> the campaign-state global
006d5997  je   0x6d59b7                     ;          absent          -> 1.0f
006d5999  cmp  byte [eax+0xb4], 0
006d59a0  je   0x6d59b7                     ;          not a WotR game -> 1.0f
006d59a9  call 0x6e1f2f                     ;          region bonus, as a percent
006d59ae  cvtsi2ss xmm0, eax
006d5a59  mulss / addss                     ; mult = 1.0f + percent * 0.01f
006d5a6e  ucomiss xmm0, [esi+0x18]          ; the change filter: the cached float
006d5a7d  jnp  0x6d5a9a                     ; unchanged -> no text this frame
006d5a86  call 0x800844
006d5a95  movss [esi+0x18], xmm0            ; cache it
```

`0x006E1F2F` is the region bonus, capped by `GameData.ResourceMultiplierLimit` (`+0xE98`, default
`4.0`) as `min(percent, limit * 100 - 100)` — with the default that is `min(percent, 300)`, i.e.
`4.0x`. **In a skirmish none of it applies**: the flag is clear, the campaign global's `+0xB4` is
clear, the float is `1.0f`, and the builder writes `L" "`. The slot is present, refreshed every
frame, and blank.

> Do not confuse this with the other two "resource modifiers" —
> `command-point-upkeep`'s [table](command-point-upkeep.md#do-not-confuse-it-with-the-other-two-resource-modifiers)
> already separates them. The slot named `ResourceMultiplier` is the region one; the number this
> patch puts *in* it is the `ResourceModifierValues` one. Reusing the slot is a deliberate pun,
> not a confusion, which is why the patch docstring says so too.

## 3. The patch: one detour

Take the `1.0f` fallback and make it the inflation multiplier instead. The window is
`0x006D59B7`, **thirteen bytes**, `f3 0f 10 05 08 19 bd 00` + `e9 a5 00 00 00`:

```asm
006d59b7  movss xmm0, [0xbd1908]            ; <- replaced by  jmp <cave>
006d59bf  jmp  0x6d5a69                     ;    resume point
```

All three branches into it (`0x6D5997`, `0x6D59A0`, `0x6D59A7`) land on `0x006D59B7` exactly —
verified by disassembling the enclosing function and checking every branch target, so nothing
lands mid-window and a five-byte `jmp` plus eight `nop`s is safe.

The cave leaves the multiplier in `xmm0` and jumps to `0x006D5A69`, the `movss [ebp-0xc], xmm0`
that the stock fallback already jumps to. Everything downstream — the change filter, the cache,
the builder, the blank-at-1.0 rule — is untouched.

`mult`, the routine `_emit_multiplier` builds, is 270 bytes and reads as follows. The whole of it
is `xmm0` — there is no return value, no output parameter and no state:

```
mult:                                   ; -> xmm0, and 1.0f on every degenerate path
    push ebp / mov ebp, esp / sub esp, 0x10       ; a frame, so nothing is held in a register
    xmm0 = 1.0f                                   ;   across the engine calls below
    [ebp-8] = 100                                 ; the upkeep factor, see §6
    if (!ThePlayerList) done
    player = ThePlayerList->getLocalPlayer()      ; NULL -> done
    [ebp-4] = player
    if ([g_upkeep]) { ecx = player; [ebp-8] = call [g_upkeep] }   ; the import slot, §6
inflation:
    tmpl = player->[0x34]                         ; NULL -> fold
    [ebp-0x10] = &tmpl->[0x1c8]                   ; ctx.filter
    [ebp-0x0c] = 0                                ; ctx.count
    if (!filter->isValid()) fold                  ; no filter -> no inflation, as in the engine
    player->forEachTeamObject(0x885230, &ctx)     ; the engine's own counting callback
    n = (tmpl->[0x1d0] - tmpl->[0x1cc]) >> 2      ; values.size()
    if (n == 0) fold                              ; see "one deliberate divergence" below
    <the arithmetic of 0x8855F7-0x88564B, verbatim>
fold:
    if ([ebp-8] != 100) {                         ; xmm0 *= kept * 0.01f
        cvtsi2ss xmm1, [ebp-8] / mulss xmm1, [0xbe5600] / mulss xmm0, xmm1
    }
done:
    leave / jmp 0x6d5a69
```

| slot | holds |
|---|---|
| `[ebp-0x04]` | the local `Player *` |
| `[ebp-0x08]` | the upkeep percentage kept, `100` when there is no upkeep to ask |
| `[ebp-0x0c]` | `ctx.count` — the callback's output |
| `[ebp-0x10]` | `ctx.filter` — the callback's input, and the base the context is passed by |

The frame is not decoration: `percent` clobbers `eax`, `ecx` and the flags, and the three engine
calls are MSVC thiscall. Holding the player and the upkeep factor in stack slots rather than in
`esi`/`edi` means the cave does not depend on a callee-save convention it has not verified, and it
is the same cost. The two context fields are frame slots for a second reason — the callback writes
`count` through the pointer, so it has to live somewhere addressable, and `_CTX_EBP` being the
*lower* of the pair is what makes `lea eax, [ebp-0x10]` the context base the engine expects.

The arithmetic block is copied instruction-for-instruction from `0x008855F7`, which is what makes
the readout and the deposit the same number: the past-end extension, the `0.02f` slope and the
floor at zero all come along. The tests disassemble the emitted routine back and assert it reads
the engine's own `0.01f`/`0.02f` constants, calls the engine's own callback rather than a private
one, converts the percentages as full dwords, and leaves a multiplier in `xmm0` on every path out.

**Two deliberate divergences from the deposit**, both in the direction of doing less:

- **The `filter.allow(thisObject, player)` gate is skipped.** The engine asks it because it is
  answering "is the building I am depositing for a taxed one"; a per-player readout has no such
  building. The *count* is taken identically.
- **An empty `ResourceModifierValues` folds to `1.0f`.** The engine reads `values[n-1]` on the
  past-end path without checking the vector is non-empty, which a faction that sets
  `ResourceModifierObjectFilter` and no values reaches — a stray dword read in the deposit path.
  Reproducing that in a per-frame HUD read is not worth it, so an empty table draws a blank slot.

**No change filter widening.** Unlike [`second-resource`](second-resource.md), whose bracket
went stale because its call was gated behind the *gold* filter, this path runs unconditionally
every refresh and its filter compares the float this patch produces. It updates the frame the
count changes, for free — and, once [§6](#6-combining-with-command-point-upkeep) is in, the frame
the *command-point tier* changes too, with no extra work. That is worth noting because it is the
one place where reusing the engine's own filter pays a dividend a hand-rolled one would have
missed: the filter watches the finished multiplier, not its inputs, so adding a second input to
the product needed nothing.

### 3.1 The section, and what `verify` checks

One appended section, `.inflrd`, 286 bytes:

| offset | what |
|---|---|
| `+0x00` | the upkeep import slot — `percent`'s VA, or zero. `READOUT_IMPORT_OFF` |
| `+0x04..+0x0f` | padding to `CODE_OFF` |
| `+0x10` | `mult`, 270 bytes |

Characteristics are `CNT_CODE | CNT_INITIALIZED_DATA | MEM_EXECUTE | MEM_READ` and deliberately
**not** `MEM_WRITE`: the import slot is written at patch time, and nothing in the section is
written at runtime. (`command-point-upkeep`'s cave and `science-prereqs`' pending list both need
`MEM_WRITE`; this one does not, and a test asserts it.)

`apply` fingerprints the thirteen-byte fallback window *before* allocating anything, so a build
that is not this one raises instead of being left carrying a cave nothing jumps into — and the
"you already applied this" case is checked first, because a second apply fails the window check
too and that is the less useful half of the answer. `verify` recomputes the same edit from the
located section's VA and compares it to the file, plus the import slot against whatever `.upkeep`
exports; `detect` is the framework's default probe, since the patch has no parameters.

## 4. What it does *not* need

| | `command-point-upkeep` | `second-resource` | this |
|---|---|---|---|
| new INI fields | 2 | 2 | **0** |
| field tables rebuilt | 1 (`PlayerTemplate`) | 2 | **0** |
| engine byte windows taken | 4 | 5 | **1** |
| new format strings in the cave | 1 | 1 | **0** |
| cave data | 128-row keyed store | `UInt32 pool[20]` | **one 4-byte import slot** |
| writable cave | yes | yes | **no** |
| `sage_ini` surface | 2 `FieldDelta`s | 2 | **0** |
| in the simulation? | yes — desyncs unpatched peers | yes | **no** |
| savegame | unaffected | **broken** (cave counter) | **unaffected** |

Client-local and read-only means the multiplayer rule is `replay-outcome`'s, not
`command-point-upkeep`'s: a patched and an unpatched client can play each other, and replays
cross. Nothing this patch reads or writes enters the simulation.

Repo-side that came out as [`patches/inflation_readout.py`](../patches/inflation_readout.py), the
shared [`patches/utils/income_link.py`](../patches/utils/income_link.py), one line in
[`registry.py`](../registry.py) and this document. `ini_surface()` stays `STOCK` — no
`Engine`/`FieldDelta` work and no `docs/ini-types.json` follow-up, which is the open item both
`hero-mana` and `command-point-upkeep` still carry.

`multiplier(count, values, kept)` in the patch module states the whole rule in Python and in
single precision, and the tests assert the emitted code and that function against the same
worked examples ([§6](#6-combining-with-command-point-upkeep)). It is the thing to read, or to
call, when the question is "what should the palantir be showing right now".

## 5. The cost that is not free

`Player::forEachTeamObject` is **O(the player's objects)** and the palantir refresh runs from the
in-game UI update (`0x006D7728`, one caller), so this walks the local player's object list on
every UI frame. The engine already does this walk **once per depositing building per deposit
tick** — with Edain putting `AutoDepositUpdate` on 97 objects that is a lot of walks — so the
added cost is in the same order as work the game already does, not a new class of cost. But it is
a per-frame walk on the render path, which nothing else in this tree adds.

Two mitigations, in order of preference:

1. **Measure first.** A late-game Edain player has a few hundred team objects and the callback is
   a `testStatus` plus an `ObjectFilter::allow`. This may simply not show up.
2. **Recompute on a frame stride.** Keep the last multiplier and the last logic frame in the cave
   (8 bytes) and recompute only every N frames — `TheGameLogic` is at `0x00DE412C` and the frame
   counter is already pinned in [`engine-globals.md`](engine-globals.md). Ten extra bytes of
   cave, and the downstream change filter still suppresses the text call on unchanged frames, so
   the only thing a stride costs is up to N frames of staleness on a number that moves when a
   building finishes.

**The shipped patch does neither**, on purpose: it walks every refresh, and the measurement is
[verify item 7](#8-verifying-it-in-a-game). Adding a stride later costs the eight bytes above and
would make the section writable, which is the only reason the current one is not.

## 6. Combining with `command-point-upkeep`

When both patches are installed the readout is **the product of both factors**, because that is
what the deposit actually does. `command-point-upkeep`'s
[charge](command-point-upkeep.md#5-the-charge) multiplies the *same* `[ebp-0x1c]` slot the
inflation block just wrote:

```asm
008855f7-0088564b   [ebp-0x1c] = inflation                     ; the values table
<upkeep cave>       [ebp-0x1c] = (kept * 0.01f) * [ebp-0x1c]   ; fild / fmul / fmul / fstp
00885685            fmul [ebp-0x1c]                            ; the deposit, scaled once
```

So the readout multiplies in the same order, and the two numbers agree.

> **The factors multiply, they do not add.** −15% inflation and −10% upkeep is **`x0.765`**, not
> `x0.75` — `0.85 × 0.90`. The additive reading would leave the palantir and the treasury
> disagreeing by 1.5% of income, growing as the penalties do (−50% and −50% is `x0.25`, not `x0`).
> The whole value of this readout is that it equals what the deposit does, so the patch is
> multiplicative and `multiplier()` states it that way. Switching to additive would be a
> one-instruction change; it would also make the number wrong, so do not.

Worked examples, computed in single precision and printed through the engine's `%g` — the same
rows the tests feed to `multiplier()`:

| inflation | upkeep kept | shown |
|---|---|---|
| 85 (`−15%`) | 90 (`−10%`) | `x0.765` |
| 85 | 100 (upkeep off) | `x0.85` |
| 100 (no penalty) | 90 | `x0.9` |
| 70 | 80 | `x0.56` |
| 100 | 100 | *blank* |

The last row matters: with neither penalty active the product is exactly `1.0f`, so the
[blank-at-1.0 rule](#2-the-display-slot-and-why-it-is-already-free) still fires and a player
running both patches with a faction that opts into neither sees the stock empty slot. Every row
above prints the same whether the product is formed in SSE or in x87, so the readout does not need
to reproduce upkeep's `fild`/`fmul` sequence to agree with it.

### The link, without breaking order-independence

[`Patch`'s composition contract](../patcher.py) says the bundled patches apply in any order, and
its rule 3 — *do not derive your output from bytes another patch rewrites* — is exactly the trap
here: if `inflation-readout` simply baked upkeep's address in when it found `.upkeep`, then
applying the two in the other order would also "succeed" and silently drop the upkeep factor.
Both orders pass, and they disagree. That is the one failure the framework cannot catch.

The fix, in [`patches/utils/income_link.py`](../patches/utils/income_link.py), is a **null function pointer
that either patch can fill**, so whichever applies second completes the link:

- **`.upkeep + 0x04` (`UPKEEP_EXPORT_OFF`) — the export slot.** `command-point-upkeep` already
  has `percent`, and publishing its VA costs **zero bytes of growth**: the upkeep cave's block key
  is one dword at `+0x00` and its row table starts at `+0x10`, so `+0x04..+0x0F` was padding.
  Nothing moved and `percent`'s own address did not change.
- **`.inflrd + 0x00` (`READOUT_IMPORT_OFF`) — the import slot**, zero unless linked. The emitted
  code tests it on every refresh (`mov eax, [slot] / test eax, eax`), so an unlinked file simply
  keeps `kept = 100` and folds nothing in.
- **Whichever patch is applied second writes the link.** Readout second: `_build_section` calls
  `read_export` and lays the value into its own section as it builds it — no cross-patch write at
  all. Upkeep second: `import_slot_offset` finds `.inflrd` and it appends one conditional entry to
  its `_edits` list writing `+0x00` from four zero bytes to `percent`, which `apply_byte_patch`
  guards like every other edit.

**The exported contract**, which `command-point-upkeep` may not now change without breaking a
linked readout:

```
percent(ecx: Player*) -> eax: int     ; the percentage of income that player keeps, 0..100
```

`100` for every degenerate case (no player, no template, no row, a zero step, an empty value
list), preserving every register but `eax`, `ecx` and the flags, and reading no memory the
simulation writes during a frame. It is stated once, in `income_link`'s docstring, and both
patches' tests assert it.

Both `verify`s check the slot from their own side. The readout's accepts *zero, or exactly what
`.upkeep` exports*, and names the three ways it can be wrong: a non-zero import with no `.upkeep`
in the file, an import that disagrees with the export, and — the one that would otherwise be
silent — an unlinked readout in a file that *does* carry upkeep, which would draw the inflation
factor alone. Upkeep's own `verify` asserts its export still equals `percent`'s recomputed VA.
Neither patch's code layout depends on the other's; only these four bytes of data do, so rule 3
is satisfied rather than waived. The tests apply the pair in both orders and assert the readout
ends up calling the same address either way.

Two consequences worth knowing:

- **Upkeep draws nothing of its own.** Its penalty is a strict subset of what the multiplier
  slot shows, so it is not drawn twice — which is why `command-point-upkeep` has no `--no-hud`
  flag.
- **No flag on `inflation-readout`.** If both patches are in the file the readout is combined,
  full stop; nobody wants a multiplier that is deliberately wrong. If an escape hatch is ever
  needed, a `0xFFFFFFFF` sentinel in the import slot that upkeep declines to overwrite costs three
  lines — but do not build it speculatively.

## 7. Open questions

- **Is the field visible in the skirmish palantir layout?** The name is in `Palantir.apt`, so
  `setValue` lands. Whether the text field is placed and shown outside War of the Ring is a
  runtime question, and it is the one thing that could sink the idea. If the field is hidden in
  skirmish, the fallback is the command-point readout's trick — a suffix on
  `APT:PalantirResources` — which costs the second format string and a second detour this design
  currently avoids, and collides with `second-resource`'s bracket.
- **What to show.** The shipped form is the free one, `x0.7`. A penalty reading (`-30%`) would
  need the patch's own format string and a second hook at `0x00800844`, roughly what
  `second-resource`'s `_emit_text` costs. Add a `--style percent` only if `x0.7` reads
  badly in game; there is no flag today.
- **War of the Ring.** In a live region battle the slot is the region bonus and this patch never
  runs — the hook is on the skirmish fallback only. That is the shipped default. Showing both
  would mean multiplying them into one number, which is arithmetically right (they scale the same
  deposit) but conflates two mechanics in one readout. Leave it.
- **Publishing `percent` makes it an ABI.** That is the point, and it means
  `command-point-upkeep` can no longer change `percent`'s calling contract without breaking a
  linked `.inflrd`. The contract is small and already what upkeep's own callers rely on, so it is
  cheap to hold; it is written down in `income_link`'s docstring and asserted from both sides.
- **Which income the number describes.** Only objects the faction's `ResourceModifierObjectFilter`
  accepts — the same caveat upkeep carries. A faction with no filter set sees a blank slot, which
  is correct and also indistinguishable from "no penalty". Acceptable.

## 8. Verifying it in a game

Nothing here has been done yet — the patch is static-verified only, and item 1 is still the one
that could sink it.

1. **The slot is visible in skirmish.** Apply the patch to a build and start a skirmish with a
   faction whose table takes something. If no text appears, the field is placed for War of the
   Ring only and the whole approach needs the fallback in [§7](#7-open-questions). Everything else
   depends on this.
2. **It tracks the count.** Build resource buildings one at a time and watch the number step down
   through Edain's table. Its leading `100`s mean the first several buildings show nothing, which
   is [the stock mechanic's own off-by-one](command-point-upkeep.md#1-the-mechanic-it-rides-on)
   — the tier index counts the depositing building itself — and is the expected result, not a bug.
3. **It blanks at no penalty.** Start a game and confirm the slot is empty, exactly as an
   unpatched build draws it. This is the `100.0f * 0.01f == 1.0f` claim.
4. **It matches the mechanic.** Compare the displayed multiplier against measured income per tick
   at two different building counts, including one past the end of the table where the `-2% per
   extra object` extension and the floor at zero apply.
5. **It loses nothing on the filter path.** A faction with no `ResourceModifierObjectFilter` must
   draw a blank slot and not a `x0`.
6. **War of the Ring is untouched.** A region battle must still show the region bonus.
7. **Cost.** Frame time in a late-game 8-player match against an unpatched build, before deciding
   whether §5's frame stride is needed.
8. **The combined number.** Both application orders already agree statically — the tests assert
   the linked address, and `sage-patch verify` passes on both files — so what is left is one
   game: with `UpkeepValues` at tier 1 and enough buildings for one inflation step, the slot must
   read the *product* and not either factor.
9. **Neither patch alone regresses.** The readout with no `.upkeep` in the file, and upkeep with no
   `.inflrd`, must each behave exactly as [§2](#2-the-display-slot-and-why-it-is-already-free) and
   [`command-point-upkeep`](command-point-upkeep.md#verifying-it-in-a-game) already describe.
