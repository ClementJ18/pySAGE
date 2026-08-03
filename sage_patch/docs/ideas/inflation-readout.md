# Showing the current inflation penalty — what it would cost

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), read from the repo's
clean `game.dat`. Nothing below is built yet; the addresses, byte windows and call shapes are
measured, the effort claims are judgement.

**Scope of the idea:** the local player's current *income* multiplier — the per-resource-building
"inflation" every Edain faction sets via `ResourceModifierValues`, **times
[`command-point-upkeep`](../command-point-upkeep.md)'s factor when that patch is also installed** —
drawn live in the palantir's **resource-multiplier** readout, which in a skirmish is an existing,
already-blank slot. See [§6](#6-combining-with-command-point-upkeep) for the link between the two
patches, which is the only part of this that is not trivial.

**Verdict up front: this is the smallest patch in the tree by a wide margin.** One 13-byte detour
and roughly 150 bytes of cave. **No new INI field**, so no field-table rebuild and no `sage_ini`
surface. **No new format string**, because the engine's own builder already formats a float as
`x%g` and already blanks itself at exactly `1.0`. **No `.apt` edit and no `.csf` edit**, for the
same reason [`second-resource`](../second-resource.md) and
[`command-point-upkeep`](../command-point-upkeep.md) need none. No savegame change, no init hook,
no INI parsing, client-local and read-only throughout. Compare `command-point-upkeep`, which
needed four edits, a rebuilt `PlayerTemplate` field table, a 128-row name-keyed store and its own
INI parse function to put one number on screen.

The one thing that is *not* free is the per-refresh object walk — see [§5](#5-the-cost-that-is-not-free).

## 1. The number

`PlayerTemplate.ResourceModifierValues` is read in exactly one place, `AutoDepositUpdate::update`
(`0x008854D3`), and [`command-point-upkeep`](../command-point-upkeep.md#1-the-mechanic-it-rides-on)
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
> `command-point-upkeep`'s [table](../command-point-upkeep.md#do-not-confuse-it-with-the-other-two-resource-modifiers)
> already separates them. The slot named `ResourceMultiplier` is the region one; the number this
> idea wants to put *in* it is the `ResourceModifierValues` one. Reusing the slot is a deliberate
> pun, not a confusion, and it is worth saying so in the patch docstring.

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

```
mult:                                   ; -> xmm0, and 1.0f on every degenerate path
    push ebp / mov ebp, esp / sub esp, 8          ; a frame, so nothing is held in a register
    xmm0 = 1.0f                                   ;   across the engine calls below
    player = ThePlayerList->getLocalPlayer()      ; NULL -> done
    [ebp-4] = player
    [ebp-8] = 100                                 ; the upkeep factor, see §6
    if (g_upkeep) { ecx = player; [ebp-8] = call [g_upkeep] }
    tmpl   = player->[0x34]                       ; NULL -> upkeep_only
    filter = &tmpl->[0x1c8]
    if (!filter->isValid()) upkeep_only           ; no filter -> no inflation, as in the engine
    ctx = { filter, 0 }
    player->forEachTeamObject(0x885230, &ctx)     ; the engine's own counting callback
    <the arithmetic of 0x8855F7-0x88564B, verbatim>
upkeep_only:
    if ([ebp-8] != 100) {                         ; xmm0 *= kept * 0.01f
        cvtsi2ss xmm1, [ebp-8] / mulss xmm1, [0xbe5600] / mulss xmm0, xmm1
    }
done:
    leave / jmp 0x6d5a69
```

The frame is not decoration: `percent` is documented to clobber `eax`, `ecx` and the flags, and
the three engine calls are MSVC thiscall. Holding the player and the upkeep factor in stack slots
rather than in `esi`/`edi` means the cave does not depend on a callee-save convention it has not
verified, and it is the same cost.

The arithmetic block is copied instruction-for-instruction from `0x008855F7`, which is what makes
the readout and the deposit provably the same number: the past-end extension, the `0.02f` slope
and the floor at zero all come along, and a divergence between HUD and mechanic can only be a
transcription bug the tests can catch by asserting the two byte sequences agree.

**No change filter widening.** Unlike [`second-resource`](../second-resource.md), whose bracket
went stale because its call was gated behind the *gold* filter, this path runs unconditionally
every refresh and its filter compares the float this patch produces. It updates the frame the
count changes, for free — and, once [§6](#6-combining-with-command-point-upkeep) is in, the frame
the *command-point tier* changes too, with no extra work. That is worth noting because it is the
one place where reusing the engine's own filter pays a dividend a hand-rolled one would have
missed: the filter watches the finished multiplier, not its inputs, so adding a second input to
the product needed nothing.

## 4. What it does *not* need

| | `command-point-upkeep` | `second-resource` | this |
|---|---|---|---|
| new INI fields | 2 | 2 | **0** |
| field tables rebuilt | 1 (`PlayerTemplate`) | 2 | **0** |
| engine byte windows taken | 4 | 5 | **1** |
| new format strings in the cave | 1 | 1 | **0** |
| cave data | 128-row keyed store | `UInt32 pool[20]` | **one 4-byte pointer** |
| `sage_ini` surface | 2 `FieldDelta`s | 2 | **0** |
| in the simulation? | yes — desyncs unpatched peers | yes | **no** |
| savegame | unaffected | **broken** (cave counter) | **unaffected** |

Client-local and read-only means the multiplayer rule is `replay-outcome`'s, not
`command-point-upkeep`'s: a patched and an unpatched client can play each other, and replays
cross. Nothing this patch reads or writes enters the simulation.

Repo-side the cost is a `patches/inflation_readout.py`, one line in
[`registry.py`](../../registry.py), a README entry, a `docs/inflation-readout.md`, and a test
file. No `Engine`/`FieldDelta` work, no `docs/ini-types.json` follow-up — which is the open item
both `hero-mana` and `command-point-upkeep` still carry.

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
   counter is already pinned in [`engine-globals.md`](../engine-globals.md). Ten extra bytes of
   cave, and the downstream change filter still suppresses the text call on unchanged frames, so
   the only thing a stride costs is up to N frames of staleness on a number that moves when a
   building finishes.

Do not reach for the second one before doing the first.

## 6. Combining with `command-point-upkeep`

When both patches are installed the readout is **the product of both factors**, because that is
what the deposit actually does. `command-point-upkeep`'s
[charge](../command-point-upkeep.md#5-the-charge) multiplies the *same* `[ebp-0x1c]` slot the
inflation block just wrote:

```asm
008855f7-0088564b   [ebp-0x1c] = inflation                     ; the values table
<upkeep cave>       [ebp-0x1c] = (kept * 0.01f) * [ebp-0x1c]   ; fild / fmul / fmul / fstp
00885685            fmul [ebp-0x1c]                            ; the deposit, scaled once
```

So the readout multiplies in the same order, and the two numbers agree.

> **One correction to the example in the brief.** −15% inflation and −10% upkeep is **`x0.765`**,
> not `x0.75` — the engine multiplies the factors (`0.85 × 0.90`), it does not add the penalties.
> `x0.75` is the additive reading, and showing it would mean the palantir and the treasury
> disagree by 1.5% of income, growing as the penalties do (−50% and −50% is `x0.25`, not `x0`).
> The whole value of this readout is that it equals what the deposit does, so **the recommendation
> is multiplicative**. Switching to additive is a one-instruction change if you want it anyway,
> but it should then be documented as a deliberate simplification rather than as the multiplier.

Worked examples, computed in single precision and printed through the engine's `%g`:

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

[`Patch`'s composition contract](../../patcher.py) says the bundled patches apply in any order,
and its rule 3 — *do not derive your output from bytes another patch rewrites* — is exactly the
trap here: if `inflation-readout` simply baked upkeep's address in when it found `.upkeep`, then
applying the two in the other order would also "succeed" and silently drop the upkeep factor.
Both orders pass, and they disagree. That is the one failure the framework cannot catch.

The fix is a **null function pointer that either patch can fill**, so whichever applies second
completes the link:

- **`.upkeep + 0x04` — an export slot.** `command-point-upkeep` already has `percent` (`ecx` = a
  `Player*` → `eax` = the percentage kept, `100` for every degenerate case, preserving everything
  but `eax`/`ecx`/flags). Publishing its VA costs **zero bytes of growth**: `_KEY_OFF` is `0x00`
  and `_ROWS_OFF` is `0x10`, so `+0x04..+0x0F` is padding today, and the patch's `verify` only
  asserts the first four bytes are zero. Nothing moves, `percent`'s own address does not change,
  and `--no-hud` does not affect it — `_emit_percent` is emitted before the HUD-conditional
  routines, so its offset is independent of that flag.
- **`.inflrd + 0x00` — the import slot**, null unless linked.
- **Whichever patch is applied second writes the link.** `inflation-readout` second: it finds
  `.upkeep`, reads `+0x04`, and bakes the value into its own section as it builds it — no
  cross-patch write at all. `command-point-upkeep` second: it finds `.inflrd` and adds one
  conditional entry to its `_edits` list writing `+0x00` from four zero bytes to `percent`, which
  `apply_byte_patch` guards like every other edit.

Both `verify`s then accept the slot as *either* zero or the partner's export, and both `detect`s
report which. Neither patch's code layout depends on the other's — only four bytes of data do —
so rule 3 is satisfied rather than waived.

Two consequences worth stating in the patch docs:

- **Upkeep's own `(-N%)` suffix is now partly redundant**, since the multiplier slot already
  contains that factor. Keep both: the command-point line attributes the loss to army size, the
  multiplier slot is the bottom line on income, and a player reading `500/1500 (-10%)` next to
  `x0.765` can decompose it. Anyone who disagrees can pass `--no-hud` to upkeep and keep the
  combined number only — which still works, because the export does not depend on that flag.
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
- **What to show.** `x0.7` is free. A penalty reading (`-30%`) needs the patch's own format string
  and a second hook at `0x00800844`, roughly what `command-point-upkeep`'s `_emit_text` costs.
  Recommendation: ship `x0.7`, add `--style percent` only if the free form reads badly in game.
- **War of the Ring.** In a live region battle the slot is the region bonus and this patch never
  runs — the hook is on the skirmish fallback only. That is the honest default. Showing both would
  mean multiplying them into one number, which is arithmetically right (they scale the same
  deposit) but conflates two mechanics in one readout. Leave it.
- **Does publishing `percent` make it an ABI?** Yes, and that is the point — but it means
  `command-point-upkeep` can no longer change `percent`'s calling contract without breaking a
  linked `.inflrd`. The contract is small (`ecx` = `Player*` → `eax` = 0..100 kept, `100` on every
  degenerate path) and already what the patch's own two callers rely on, so this is cheap to hold.
  Write it down in `addresses.py` beside the export offset, and have both patches' tests assert it.
- **Which income the number describes.** Only objects the faction's `ResourceModifierObjectFilter`
  accepts — the same caveat upkeep carries. A faction with no filter set sees a blank slot, which
  is correct and also indistinguishable from "no penalty". Acceptable.

## 8. Verifying it in a game

1. **The slot is visible in skirmish.** Before writing any code: force the fallback to something
   other than `1.0f` (a two-byte change of the constant reference is enough for a throwaway build)
   and confirm text appears in the palantir. Everything else depends on this.
2. **It tracks the count.** Build resource buildings one at a time and watch the number step down
   through Edain's table. Its leading `100`s mean the first several buildings show nothing, which
   is [the stock mechanic's own off-by-one](../command-point-upkeep.md#1-the-mechanic-it-rides-on)
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
8. **The combined number, both application orders.** Build a binary with upkeep first and one with
   the readout first, confirm the two files agree byte-for-byte in the linked slots, and run one of
   them with a faction that opts into both: with `UpkeepValues` at tier 1 and enough buildings for
   one inflation step, the slot must read the *product*. This is the item that catches the rule-3
   trap, and it is cheap — `sage-patch verify` on both orders plus one game.
9. **Neither patch alone regresses.** The readout with no `.upkeep` in the file, and upkeep with no
   `.inflrd`, must each behave exactly as [§2](#2-the-display-slot-and-why-it-is-already-free) and
   [`command-point-upkeep`](../command-point-upkeep.md#verifying-it-in-a-game) already describe.
