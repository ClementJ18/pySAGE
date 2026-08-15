# A second resource, granted, shown and spent — reverse-engineering notes

> ⚠ **Experimental.** This patch is **unstable and largely untested** — it lives in
> [`patches/experimental/`](../patches/experimental/), `sage-patch list` marks it `exp`, and
> `sage-patch apply` warns before it writes. The status note below says how far it actually
> got; see the README's [Experimental patches](../README.md#-experimental-patches) note before
> applying it.

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), read out of a clean
`game.dat`. This is the writeup for the **`second-resource`** patch,
[`patches/experimental/second_resource.py`](../patches/experimental/second_resource.py), and it supersedes the costing
document this feature started as.

## What this is

A second spendable currency needs four pieces: a counter per player, a HUD element, an INI block
that grants it, and an INI field that makes something cost it. **All four are here** — §1–§6 are
the counter, the grant and the display; §7 is the cost.

```ini
AutoDepositUpdate ModuleTag_Income
  DepositTiming   = 15000
  DepositAmount   = 10        ; stock: gold per tick
  DepositAmount2  = 2         ; new:   resource 2 per tick
End

PlayerTemplate FactionMen
  StartMoney  = 1000          ; stock
  StartMoney2 = 50            ; new
End

Object OrcArcher
  BuildCost  = 100            ; stock: gold
  BuildCost2 = 25             ; new
End
```

The palantir reads `1000 (50)`, a priced button reads `Cost: 100 (25)`, and a player who is short
is refused with the engine's own "not enough money".

An `AutoDepositUpdate` that never names `DepositAmount2` and an `Object` that never names
`BuildCost2` are byte-for-byte unaffected, which is what lets the patch sit under a mod that does
not use it — and what makes the AI a non-problem (§8).

> **What this is not.** It is not a general second economy. Only unit and hero production is
> *charged*; structure placement, upgrade research and refunds are refused correctly and then
> cost nothing (§9). Read §9 before pricing a roster around it.

## TL;DR

| what | where | cost |
|---|---|---|
| the counter | `UInt32 pool[20]` in the `.res2` cave, indexed by `Player::m_playerIndex` | no struct growth |
| seed + per-game clear | one 6-byte hook at `Player::init`'s entry, `0x006B0243` | one hook |
| `DepositAmount2` storage | `AutoDepositUpdate` `ModuleData+0x22`, alignment padding | no growth |
| its default | the constructor's two `Bool` stores → one dword store | 3 bytes of 6 |
| its parser | the stock `INI::parseUnsignedShort` `0x0042EC11`, wrapped | ~30 bytes |
| the grant | one 5-byte hook on the module's own `call Money::deposit`, `0x0089DD08` | one hook |
| `StartMoney2` storage | a name-keyed row table in the cave | no template growth |
| its key | one 6-byte hook at `0x005FE880` | one hook |
| both field tables | rebuilt in the cave, **one** repoint each | 2 × 4 bytes |
| the bracket | one 11-byte hook on the text builder, `0x006D5721` | no `.apt`, no `.csf` |
| the refresh filter | one 5-byte hook on the change test, `0x006D5804` | one hook |
| `BuildCost2` storage | a pointer-keyed row table in the cave | no template growth |
| surviving an override | one 7-byte hook inside `ThingTemplate::copyFrom` | one hook |
| the refusal | one 6-byte hook on `BuildAssistant`'s one gold test | reuses code 2 |
| the charge | one 5-byte hook on `queueCreateUnit`'s withdrawal | one hook |
| the cost bracket | two 5-byte hooks on the `TOOLTIP:Cost` lines | no `.csf` |

## 1. The counter

### 1.1 Why a side table

Money lives in a `Money` subobject at `Player+0x90`:

```
Player +0x54   Int               m_playerIndex   (the Player's own)
       +0x90   Money m_money     (a Snapshot subobject, so +0x90 is its vptr)
       +0x94   UnsignedInt       current spendable    <- pinned live, see engine-globals.md
       +0x98   Int               m_playerIndex        (the Money's own)
       +0x3DC  ScoreKeeper       stats block
       +0x3E0    cumulative collected (stats+0x04)    monotonic, never falls
```

| what | VA | note |
|---|---|---|
| `Money::withdraw(amount, stats, playSound)` | `0x007B17EF` | **clamps to available and returns what it took — never refuses** |
| `Money::deposit(amount, stats, playSound)` | `0x007B18B8` | |

The clamp is load-bearing for the whole design: **affordability is always decided upstream of the
withdrawal, never by it**, which is why §7 puts the refusal in a gate and the debit somewhere
else, and why the debit clamps at zero of its own accord.

Growing `Player` to hold a second pool means an allocation-size hunt and a constructor edit for
one dword. `UInt32 pool[MAX_PLAYER_COUNT]` in the cave costs neither, and the array is *exact*
rather than generous: `MAX_PLAYER_COUNT` is 20 and [cannot practically be
raised](max-player-count.md), so every per-player array the engine embeds is already this wide.
Same shape as [`unique-production-id`](unique-production-id.md)'s `.prodid` counter.

The trade is the one that counter accepted too: **a cave-resident value is not `Xfer`'d, so a
savegame does not carry it.** For a production id that costs at most one collision; for a resource
pool it is a visible limitation, and the patch states it rather than hiding it. Extending
`Player::xfer` is a savegame format change, and is the largest single thing this patch does
not do (§9).

### 1.2 `Money` is 12 bytes, and that matters twice

`PlayerTemplate`'s own `Money` sits at +0x2C, and the constructor writes three dwords:

```
005fe430  mov  dword [esi+0x2c], 0xbf7bd8     ; the Money vptr
005fe437  mov  dword [esi+0x30], ebx          ; current  == StartMoney
005fe43a  mov  dword [esi+0x34], ebx          ; m_playerIndex
```

So `PlayerTemplate+0x34` looks like a free dword — the ctor zeroes it, the copy at `0x005FE038`
copies it, and **no INI field names it**. It is not free. `Player::init` reads it:

```
006b0539  mov  eax, [esi+0x30]                ; esi = the PlayerTemplate
006b053c  lea  ecx, [ebx+0x90]                ; ebx = the Player
006b0542  mov  [ecx+4], eax                   ; player money  = StartMoney
006b0545  mov  eax, [esi+0x34]                ; the template's Money::m_playerIndex
006b0548  mov  [ecx+8], eax                   ; player Money::m_playerIndex
006b054b  cmp  [ebx+0x94], edi
006b0551  mov  eax, [ebx+0x54]
006b0554  mov  [ebx+0x98], eax                ; ...immediately overwritten with the real index
```

The copy is dead — `Player+0x98` is rewritten two instructions later — but the member is real, and
"the only read I found is dead" is not the same claim as "nothing reads it". **An apparent hole in
a template is usually a subobject member the field scan cannot see**, and `ThingTemplate+0x5E8`
turned out to be the same trap (§7.1). `StartMoney2` goes elsewhere (§4).

## 2. Seeding, and why `Player::init`'s entry

The pool has to be zeroed on a new game *and* seeded per faction. `Player::init(PlayerTemplate*)`
at `0x006B0239` does exactly that for gold, and `PlayerList`'s own reset calls it on every slot:

```
006a8916  ...
006a891a  mov  ecx, [esi+0x18]                ; the neutral player
006a8927  call 0x6b0239                       ; Player::init(NULL)
006a892c  push 0x13                           ; the other 19 slots
006a8932  mov  ecx, [edi]
006a8936  call 0x6b0239                       ; Player::init(NULL)
```

> **`PlayerList::newGame` is the wrong hook**, which is what makes the reset above the right one:
> it skips the neutral side, and the slot census is not the participant census — a solo skirmish
> still carries five `Player` slots. Seeding per *participant* would leave the others dirty.

Four callers, none of them a per-frame path. **The hook cannot go at the money block**, because
that block is inside the `template != NULL` branch (`0x006B04FA` jumps past it) and the reset
passes NULL — a slot that never gets a faction would keep the previous game's number. At the
function's entry, past the SEH prologue and before the branch, `ecx` is still the `Player` and
`[ebp+8]` the template, so one hook does both jobs: a NULL template seeds 0, which *is* the clear.

The seed **assigns** rather than adds, so re-initialising a slot cannot accumulate. The window is
six bytes:

```
006b0243  83 ec 0c        sub  esp, 0xc
006b0246  8b 45 08        mov  eax, [ebp+8]
```

## 3. `DepositAmount2`

### 3.1 The module, and which one it is not

`AutoDepositUpdate` is the "this structure pays you on a timer" module. Its `ModuleData`
constructor is at `0x00653EBA`, `sizeof` `0x24` (`push 0x24` at `0x00653F2B`):

```
AutoDepositUpdate ModuleData      size 0x24, ctor 0x00653EBA
  +0x08  DepositTiming          Duration
  +0x0c  DepositAmount          Int
  +0x10  InitialCaptureBonus    Int
  +0x14  Upgrade                UpgradeTemplate
  +0x18  UpgradeBonusPercent    Percent
  +0x1c  UpgradeMustBePresent   KindOfFilter
  +0x20  GiveNoXP               Bool
  +0x21  OnlyWhenGarrisoned     Bool
  +0x22  ---- alignment padding ----
```

> **It is not the module `AUTO_DEPOSIT_SCALE` names.** That constant, and
> [`command-point-upkeep`](command-point-upkeep.md)'s hook, sit inside
> `TerrainResourceBehavior::update` (`0x008854D3`) — the *other* income module, and the only
> reader of `PlayerTemplate.ResourceModifierValues`. The two read alike and the name in
> `addresses.py` is misleading; the discriminator is the `ModuleData`, reached as `[ebp-0x18]`
> there and as `[esi-0x0C]` in `AutoDepositUpdate::update`.

### 3.2 The padding, and the default that costs three bytes

Fields end at +0x21 and the block is 0x24, so **+0x22..+0x23 is alignment padding** — the same
argument [`terrain-resource-exp`](terrain-resource-exp.md) makes for its `Bool` at +0x16. A
`UInt16` fits with no growth at all: cap 65535 per tick, which is ample for a per-tick grant.

`operator new` does not zero the block, so the field table giving the field a *name* is not the
same as giving it a *default*. The constructor's tail is:

```
00653efb  88 5e 20        mov  [esi+0x20], bl        ; GiveNoXP = 0
00653efe  88 5e 21        mov  [esi+0x21], bl        ; OnlyWhenGarrisoned = 0
```

`ebx` is already zero (`xor ebx, ebx` at `0x00653ED4`), so both stores collapse into one:

```
00653efb  89 5e 20        mov  [esi+0x20], ebx       ; +0x20..+0x23, all four
00653efe  90 90 90
```

Three bytes for six, and it clears the padding on the way past. **`DepositAmount2 = 0` therefore
costs nothing**, which is what makes the patch invisible to a module that never mentions it.

### 3.3 The field table — one repoint

```
AutoDepositUpdate field-parse table   0x00C07FD8
  8 rows x 16 bytes { const char *name; ParseFn; void *userdata; UnsignedInt offset; }
  terminator 0x00C08058
  references: exactly one — the push immediate at 0x00653F14, inside buildFieldParse
```

One reference, and the table is walked to its terminator rather than to a count, so appending a
row is a rebuild in the cave plus **one** 4-byte repoint and no bound raised anywhere. The new row
uses the stock `INI::parseUnsignedShort` at `0x0042EC11`, which range-checks `0..0xFFFF` and
stores a **word** through `store`:

```
0042ec2d  cmp  eax, 0xffff
0042ec32  jg   0x42ec3c
0042ec34  mov  ecx, [ebp+0x10]        ; store == instance + offset
0042ec37  mov  word [ecx], ax
```

That word store is what lets the field live in two bytes of padding, exactly as
`INI::parseBool`'s byte store does for one. Using `INI::parseInt` instead would write four bytes
at +0x22 and run two past `sizeof` — it would apply, verify and corrupt whatever the allocator
put next.

### 3.4 The grant

`AutoDepositUpdate::update` computes the gold, rounds it and deposits it:

```
0089dcdd  cvttss2si eax, [ebp-0x14]
0089dce5  call 0x6aa858                       ; the handicap / clamp
0089dcf5  push 1
0089dcf7  lea  ecx, [edi+0x3dc]               ; the ScoreKeeper
0089dcfd  push ecx
0089dcfe  push eax
0089dcff  lea  ecx, [edi+0x90]                ; &player->m_money
0089dd08  call 0x7b18b8                       ; Money::deposit
0089dd0d  mov  eax, [esi-8]                   ; <- edi stops being the Player here
0089dd10  mov  edi, [eax+0x26c]               ;    (the ExperienceTracker)
```

The hook replaces the whole five-byte `call`, so it displaces exactly one complete instruction and
needs no padding. `esi` is the module — `[esi-0x0C]` is its `ModuleData`, the same slot the
`GiveNoXP` gate five instructions later reads — and `edi` is the controlling `Player`; both are
callee-saved across the deposit. The cave makes the call itself, then credits
`pool[player->m_playerIndex]` from `ModuleData+0x22`.

Two deliberate properties:

* **The grant is flat.** Neither `UpgradeBonusPercent` (`0x0089DC83`) nor the difficulty handicap
  (`0x0089DCD2`) scales it, so `DepositAmount2 = N` means N per tick and nothing else. For a pool
  nothing prices against yet, a rule that needs no arithmetic to predict is the right one.
* **It saturates rather than wraps.** A long game at a large `DepositAmount2` would otherwise roll
  a player's balance back through zero, which reads as a bug rather than as a cap.

`InitialCaptureBonus` has its own deposit at `0x0089DABE` and is **not** covered: there is no
`InitialCaptureBonus2`, so capturing a structure pays gold only.

## 4. `StartMoney2`

### 4.1 Why it cannot live on the template

`PlayerTemplate` is `0x1DC` bytes with no hole — §1.2 disposes of the apparent one at +0x34 — and
growing it means correcting 24 separate `0x1DC` literals in the store's compiland alone. Worse, a
pointer key would not survive: templates live in a `std::vector<PlayerTemplate>` and a new block is
parsed into a **stack temporary** before being copied in, so the `this` a field callback sees is
transient and is reused by the next block.

So the value goes in the cave, keyed by the template's `NameKeyType` at +0x10 — the one stable
identity a template has, and the one `PlayerTemplateStore::findPlayerTemplate` itself matches on.
This is [`command-point-upkeep`](command-point-upkeep.md)'s mechanism for
`command-point-upkeep`'s reasons, and it carries the same consequences: the rows are INI-derived
and rebuilt on every load (no savegame change, no init hook), an override block *merges* rather
than replaces, and a missing row is "start at 0" rather than a wrong number.

### 4.2 The key is not readable from the instance

All three parse paths write the key **after** `initFromINI` returns:

```
005fe886  mov  edi, eax                       ; eax = the block's name key
005fe889  call 0x5fca2e                       ; findPlayerTemplate(key)
005fe890  test ebx, ebx
          ; found, mode 2: construct a copy, parse it, then...
005fe8df  call 0x5fdf75                       ; initFromINI
005fe8e4  mov  [esi+0x10], edi                ;     <- key written after
          ; found, mode 5: parse into the existing one, then...
005fe8f8  call 0x5fdf75
005fe8fd  mov  [ebx+0x10], edi                ;     <- after
          ; not found: parse into a stack temporary at [ebp-0x1f4], then...
005fe94e  call 0x5fdf75
005fe95c  mov  [ebp-0x1e4], edi               ;     <- after, and into a temporary besides
```

So the callback has to be told which faction it is parsing, by a hook before the paths branch.

### 4.3 Two patches, two windows

`command-point-upkeep` already owns the instruction pair at `0x005FE886`. This patch takes the
six bytes immediately before it, where `eax` already holds the key:

```
005fe880  8b 0d 10 3b de 00     mov  ecx, [PlayerTemplateStore]     <- second-resource
005fe886  8b f8                 mov  edi, eax                       <- command-point-upkeep
005fe888  57                    push edi
005fe889  e8 a0 e1 ff ff        call findPlayerTemplate
```

The windows do not overlap, and neither hook does anything but copy `eax` — so neither reads what
the other writes, and the pair composes in either order.

### 4.4 The row table

`{ UnsignedInt key; UnsignedInt start; }`, 128 rows, open-addressed with a mask fold (Edain
defines ~40 `PlayerTemplate` blocks). Entries are never removed, so a run of occupied slots is
never broken and the walk is exact. A full table, an absent key and a zero value all take the same
"start at 0" path — a degraded faction, never a wrong number and never a failed load. The parse
function consumes its token whether or not there is a row to put it in, so neither case can leave
the INI reader mid-line.

## 5. Composition

Every rule in [`patcher.py`](../patcher.py) holds, and the interesting pair is stated in §4.3. One
thing is worth naming because it changed a sibling patch:

**Two patches rebuilding the same field table is an ordered pair for `verify`, not for `apply`.**
Both read the table live from its own reference, so whichever runs second rebuilds the first one's
table — by pointer, so the first one's rows keep their own name strings and their own parse
functions — and points the reference at its own copy. The binary is correct either way. Two
rules keep `verify` correct with it:

* Rows are located **by name** (`entries_before`), never by counting back from the end of the
  table — that count is wrong as soon as another patch appends past them, and it sizes the
  rebuilt table, which places every routine in the cave.
* `verify` does **not** assert that the table reference still names *its* copy, because a later
  patch is entitled to overwrite exactly that one edit. It checks the thing that actually has to
  hold: the live table still names its fields with its parse functions.

## 6. The display, for no `.apt` at all

The resource bar really is data-bound, which is what made this look expensive. `TheAptPlayer`
(`0x00DE3F0C`) holds a binding map at `+0xA4`; the HUD constructor at `0x006D61BC` registers paths
against pointers into its own members and the teardown at `0x006D4B6E` unregisters them:

| binding path | bound to | register call |
|---|---|---|
| `Palantir/ResourceBar/Resources/` | `this+0x0C` (Int) | `0x006241CE` |
| `Palantir/ResourceBar/CommandPoints/` | `this+0x10` (Int) | `0x006241CE` |
| `Palantir/ResourceBar/ResourceMultiplier/` | `this+0x18` (Real) | `0x006241CE` |
| `ResourceBar/ResourceIcon` | string → `Resource_Icon` | `0x006236F6` |

```
006d61d7  lea  edi, [esi+0xc]                    ; &this->resources
006d6299  push 0xc18f5c                          ; "Palantir/ResourceBar/Resources/"
006d62b4  mov  [ebp-0x10], edi                   ; the closure captures the *pointer*
006d62b7  call 0x6d55ea                          ; make watcher: 12 bytes, vtable 0xc18e74
006d62c6  call 0x6241ce                          ;   +0x08 = the captured pointer
```

The watcher holds a **pointer to the value** and the movie re-reads it every frame. Driving the
display off this would mean one more binding, a mirror `Int` fed from `pool[localPlayerIndex]`,
and an edit to the `APT:PalantirResources` movie to add a second text field — which is the
expensive route, because [`sage_apt`](../../sage_apt/README.md)'s own README says it is *"not
yet fully functional and largely untested"*.

**None of that is needed.** The readout has a numeric binding *and* an engine-formatted text
string, and it is the second one that draws:

```
006d56e1  <the setter, one argument: the amount>
006d56ec  test byte [0xde4a88], 1              ; lazily build the static path AsciiString
006d5706  push 0xc19050                        ; "APT:PalantirResources"
006d571d  and  dword [ebp-0x10], 0             ; the AsciiString result
006d5721  cmp  dword [ebp+8], 0                ; <- the hook window
006d5725  mov  dword [ebp-4], 1                ;    (SEH state: the string is live)
006d572c  jl   0x6d5744                        ; negative -> the " " placeholder at 0x00BD343C
006d572e  push dword [ebp+8]                   ; <- the first vararg
006d5734  push 0xbd4194                        ; "%d"   ** 8-bit, not UTF-16 **
006d573a  call 0x437a90                        ; AsciiString::format  (cdecl)
006d573f  add  esp, 0xc                        ;   one vararg
006d5751  call 0x625071                        ; TheAptPlayer::setValue(path, text, 0)
```

So the movie's own text is overwritten every refresh and a mod's `.csf` entry of that name is a
design-time placeholder — exactly what `command-point-upkeep` found on the command-point readout.
A second number is **one more vararg on a call the engine already makes**: no `.apt` edit, no
`.csf` edit, no second binding, and no dependency on `sage_apt`.

The hook sits *before* the first vararg push, because `AsciiString::format` is cdecl and the
varargs are pushed last-first. Two instructions are displaced and each runs exactly once on every
path, but in the other order: `mov [ebp-4], 1` first, because it sets no flags and both edges need
it; the `cmp` last on the stock edge, because the resume address is the engine's own `jl` and the
flags it reads have to be the ones this hook set.

### 6.1 The refresh filter has to widen with it

The palantir only rebuilds the string when the number changed:

```
006d57a8  call 0x6a8839                        ; PlayerList::getLocalPlayer
006d57fd  mov  edi, [eax+4]                    ; its gold  (edi stays -1 if there is none)
006d5804  cmp  edi, [esi+0xc]                  ; <- the hook window, five bytes
006d5807  je   0x6d5813                        ;    unchanged: no text this frame
006d5809  push edi
006d580a  mov  [esi+0xc], edi
006d580d  call 0x6d56e1
```

A second number in the same string has to be part of that test, or the bracket shows whatever it
said the last time *gold* moved. The hook keeps both stock edges and adds one: a change in the
local player's pool forces the push whatever gold did.

### 6.2 When the bracket appears

**Decided at INI load, by a flag both parse functions raise on a non-zero value** — which is why
`DepositAmount2` gets a wrapper around the stock `UInt16` parser at all. A mod that mentions
neither field gets the stock readout byte for byte; a mod that uses either always shows the
bracket, including at zero.

Not "whenever the pool is non-zero": a readout that grows and loses a number mid-game reads as a
bug, and it would flicker for any mod that spends down to 0.

`--no-hud` drops both hooks and the local-player read entirely, leaving the mechanic.

## 7. What it costs

```ini
Object OrcArcher
  BuildCost  = 100        ; stock: gold
  BuildCost2 = 25         ; new
End
```

and a priced button reads `Cost: 100 (25)`.

### 7.1 `ThingTemplate` has no hole either

The costing document hoped the 2-byte gap between `CampnessValue` (an `Int` at +0x5E4) and
`BuildCost` (a `UInt16` at +0x5EA) might be free storage. It is not, and
[`hero-mana`](hero-mana.md) §8 had already established that for its own fields: the constructor
writes it as a word at `0x0073FF8D`, so it is a live non-INI member and using it would have been
a memory-corruption bug rather than a missing field.

What it *is*:

```
006d112d  mov  ecx, [0xda18e4]        ; a global UInt16 counter
006d1133  dec  word [0xda18e4]        ; counting down
006d113a  mov  word [eax], cx         ; template->+0x5E8 = a fresh id
```

`+0x5E8` is the template's engine-assigned **id**: a dedicated setter at `0x006CFBC7`, ~15
readers, and the ControlBar pushes it into build orders (`0x00940948`). An override *swaps* ids so
the new template inherits the old one's identity — which is why the id copy is the natural place
to hang anything else keyed on template identity (§7.2).

That is the second apparent hole in a template this feature has had to reject: `PlayerTemplate
+0x34` in §1.2 is the `Money` subobject's own `m_playerIndex`. **The pattern is worth naming: an
unnamed gap in a template is usually a member the INI field scan cannot see, and both of the ones
here were.**

Growing `ThingTemplate` is the fallback, and it buys less than it looks like. `sizeof` is `0x650`,
allocated at two sites (`0x006D2750` in `ThingFactory::newOverride`, `0x006D27BD` in
`newTemplate`) — but with 11,143 instances loaded, an allocation site a scan missed corrupts the
heap, and the `SpecialPowerTemplate` case in `hero-mana` showed the adjacent-`push`/`call` scan
*can* miss one. More decisively, **the copy at `0x006D24AB` is field by field**, so growing does
not even get the copy for free. Both routes need the same copy hook, so the cost goes in the cave
keyed by `ThingTemplate *` and the struct is left alone — the same conclusion `hero-mana` reached
for `ManaPool`, by the same reasoning.

### 7.2 The `Object` field table

```
base         0x00DA3DF8       in .data (writable, 0xC0000040)
entries      191 x 16 bytes   { const char *name; ParseFn; void *userdata; UnsignedInt offset; }
terminator   0x00DA49E8       all-zero entry
references   5                0x73bdf4 (a mov) + four pushes: 0x73befb 0x73bf4f 0x73c142 0x73e8c9

0x00DA4028   { 0xc10b70 "BuildCost", 0x42ec11 (UInt16 parser), 0, 0x5ea }
```

Five references is a smaller repoint than `production-condition`'s sixteen, and the table is
walked to its terminator rather than to a count, so no bound needs raising.

> **There is no interior reference.** A byte scan reports one at `0x7162A4` pointing into the
> table, and it is a false positive: that address disassembles to `call 0x723CEE`, whose `E8`
> opcode plus the first three bytes of its displacement happen to spell `0x00DA45E8`.
> [`hero-mana`](hero-mana.md) §7 establishes this; the table relocates as a unit.

### 7.3 Riding the copy

An INI override block is parsed into a *fresh* template copied from the old one, so anything keyed
on the pointer dies unless it rides that call. The hook is the engine's own id copy, in the middle
of `copyFrom`, where `eax` is the source and `ebx` the destination:

```
006d24ab  mov  ecx, [eax+0x5e4]       ; CampnessValue
006d24b7  mov  cx,  word [eax+0x5e8]  ; <- the hook window, seven bytes
006d24c5  mov  cx,  word [eax+0x5ea]  ; BuildCost
```

[`hero-mana`](hero-mana.md) rides the same copy from the outside, by retargeting its **call
site**. This is the body, so the two share no byte — and the body also covers any caller that is
not that one call.

### 7.4 One gate, and the engine's own refusal

`BuildAssistant`'s `+0x64` predicate is the one affordability check the ControlBar,
`queueCreateUnit` and every script path share:

```
00793fff  mov  ebx, [esi+0x94]        ; the player's gold
00794009  call 0x73c25f               ; ThingTemplate::calcCostToBuild
00794013  cmp  eax, ebx               ; <- the hook window, six bytes
00794015  jbe  0x79401e               ;    affordable
00794017  push 2                      ;    "not enough money"
```

**Refusing with the engine's own code 2 is the whole UI story**: the button tint, the refusal
sound and the message are the ones the player already knows, and no new string is needed.

The AI reaches this predicate too, and that is fine by construction — see §8. A cost of 0 short
-circuits before the pool is ever read, so an object that never names `BuildCost2` is priced
exactly as it is today.

### 7.5 The charge

`ProductionUpdate::queueCreateUnit`'s withdrawal is a whole five-byte `call`, so the hook
displaces one complete instruction:

```
008a129c  add  ecx, 0x90              ; &player->m_money
008a12a2  call 0x7b17ef               ; Money::withdraw   <- the hook
```

`[ebp-0x0C]` is the `Player` and `[ebp+8]` the `ThingTemplate`. The debit **clamps at zero rather
than going negative** — `Money::withdraw` does the same for gold, taking what is there and never
refusing, which is what puts affordability upstream at the gate and means a debit that arrives
anyway must not wrap a `UInt32` into four billion.

### 7.6 The bracket

`TOOLTIP:Cost` (`0x00C4F028`) has four call sites, all the same shape: three pushes,
`TheGameText`'s vtable `+0x44` formats the localized line into `eax`, then the line is
concatenated onto the description at `ebp-0x28`.

```
00807f7a  push 0xc4f028               ; "TOOLTIP:Cost"
00807f7f  call [eax+0x44]             ; -> eax = the formatted line
00807f82  push eax                    ; <- the hook window, five bytes
00807f83  lea  eax, [ebp-0x28]
00807f86  push eax
00807f87  call UnicodeString::concat
```

The window sits **after the line exists and before it is handed over**, which is the one place a
suffix can join it — and appending rather than rebuilding is what keeps the `Cost:` label the
mod's own localized string. **No `.csf` edit and no new tooltip key.**

Two of the four sites are hooked: the ones where the thing being priced is a `ThingTemplate` in a
known register (`ebx` for a unit or structure, `esi` for a hero to revive), which are exactly the
two `BuildCost2` applies to. The other two price a science and a per-frame float.

`UnicodeString::format` allocates, so the suffix is a real temporary with a real destructor. A
cost of 0 constructs nothing at all.

## 8. The AI

**Out of scope by construction, not by omission.** AI players are given unit variants that leave
`BuildCost2` at its default of 0, so the AI's economy reasoning — `EconomyBuilderMinMoney`,
`AIMoneyLender`, the build manager — never has to know the pool exists. The gate is shared, so the
AI *does* run through it; a cost of 0 sails through without reading anything.

What that costs, and it is not nothing: a parallel `_AI` template per priced unit, maintained
alongside the human one. Keep those generated or diffed rather than hand-copied, and consider a
`sage_lint` check that an AI variant matches its counterpart on everything except the cost.

## 9. What is still not covered

The engine has **22 call sites of `Money::withdraw` and 35 of `Money::deposit`**. A coherent
second currency has to reach a subset of them; this is where that subset stands.

| path | site | state |
|---|---|---|
| pre-production affordability gate | `BuildAssistant` vtable `+0x64`, `0x00793ECB` | **done** — one hook refuses every human path |
| unit + hero production withdrawal | `0x008A12A2` in `queueCreateUnit` (`0x008A11D2`) | **done** |
| AI producer choice | `BuildAssistant::canMakeUnit` `0x00794F38` | passes unchanged at cost 0, by design (§8) |
| "not enough" UI | `0x00940A4A`, `0x0083E798` | free — the gate reuses the engine's own code 2 |
| tooltip | `0x00807F82`, `0x008085EC` | **done** (§7.6) |
| structure placement | its own withdrawal among the 22 | **refused, not charged** |
| upgrade research | `Upgrade.BuildCost`, its own withdrawal | **refused, not charged** |
| cancel / refund | `GameData.RefundPercent` | **not refunded** |

* **Structure placement and upgrade research are refused but not charged.** Both go through the
  shared gate, so neither can be *started* without the resource — and then neither debits it.
  `Upgrade.BuildCost` is a separate `Int` at +52 in a separate field table and needs the same
  field-table treatment `Object` got. **Which of the 22 withdrawal sites is structure placement,
  and which is upgrade research, is still unanswered** — that is the next thing to find.
* **Cancelling a production refunds no resource 2.** `GameData.RefundPercent` applies to gold only.
* **`TerrainResourceBehavior` grants nothing** — the other income module, and the one Edain uses
  *more* for resource spots (239 references against `AutoDepositUpdate`'s 95 in
  `__edain_data.big`). Its `ModuleData` has a single spare padding byte, already claimed by
  `terrain-resource-exp`, so a `DepositAmount2` there means growing the struct rather than reusing
  a hole.
* **`InitialCaptureBonus` has no second-resource twin**: capturing a structure pays gold only.
* **A savegame still resets the pool** (§1.1), which now costs a player their spending power
  rather than just a number.
* **The cost table holds 4096 priced objects.** Past that a template silently claims no row and
  **becomes free** — the worst failure mode in the patch, which is why the ceiling is four times
  what `hero-mana` uses for the same key space rather than the same. Edain loads 11,143 templates;
  pricing more than a third of them would need the number raised.

### 9.1 Tail work in the Python tooling

None of it is required for the patch to run — `sage-patch sagepatch` already teaches `sage_ini`
and `sage_lint` the three new fields — but the model is where a mod author meets them:

* [`sage_ini/model/ini_objects.py`](../../sage_ini/model/ini_objects.py) annotates `BuildCost`
  (line 78); `BuildCost2` wants the same for anything reading the model directly.
* [`sage_lint/analysis.py`](../../sage_lint/analysis.py)'s cost analysis (line 26) prices units in
  gold only.
* `sage_live`'s economy observation can read the pool straight out of the `.res2` section, which
  is the cheapest way to watch the mechanic in a running game.
* `module-reference.json` / `ini-types.json` regenerate from a patched binary.

## 10. Determinism and compatibility

Every input is simulation state identical on every peer: the module's INI, the player's index, the
template's name key. Nothing reads a pointer *value*, and the only writes outside the pool happen
at INI load.

> **Every peer must run the same patched binary.** Affordability decides what gets built, so the
> effect is inside the simulation: a patched and an unpatched client desync and replays do not
> cross. That is the `production-condition` rule, stricter than `replay-outcome`'s client-local
> guarantee. This was true of the grant half only *once anything reacted to the counter*; with
> `BuildCost2` in, something does.

A mod using either keyword cannot run on an unpatched binary at all: an unknown field in a known
block is an INI parse error, not a warning. `sage-patch sagepatch` writes the `.sagepatch` that
teaches `sage_ini` and `sage_lint` about both fields.

## Status

**Applied, structurally verified and runtime-verified.** `apply` + `verify` round-trip on the
real binary in both `--hud` and `--no-hud` builds, the cave disassembles cleanly, every ordering
of the bundled patches verifies, and
[`tests/sage_patch/test_second_resource.py`](../../tests/sage_patch/test_second_resource.py)
asserts the encodings that fail silently — the word load, the `UInt16` parser, the dword clear in
the constructor, the bounds checks, the pointer fold, the cdecl cleanups, and that the displaced
deposit *and* withdrawal both survive.

The in-game check is a five-minute one, and is how this was verified: put `DepositAmount2` on a
farm and `BuildCost2` on a unit, start a skirmish, and watch the palantir count up and the button
refuse. **Two things worth re-checking after any change**, because they are the least constrained
by structure:

1. **The tooltip suffix**, the only place this patch allocates. `UnicodeString::format` into a
   stack temporary, concatenated and destroyed — a convention error there is a leak per tooltip
   frame at best and a crash at worst. Hover a priced button and hold it.
2. **The gate's refusal**, which reuses code 2. Confirm the button greys and the stock "not enough
   money" message appears, rather than the click silently doing nothing.

## Address index

`AutoDepositUpdate` `ModuleData` ctor `0x00653EBA` (`sizeof` `0x24`), its two `Bool` defaults
`0x00653EFB`, `buildFieldParse` `0x00653F0E` and its push immediate `0x00653F14` · field-parse
table `0x00C07FD8` (8 rows, terminator `0x00C08058`, **one** reference) · `update`'s deposit
`0x0089DD08`, resume `0x0089DD0D`, `ModuleData` at `[esi-0x0C]`, `Player` in `edi` ·
`InitialCaptureBonus` deposit `0x0089DABE` · the stock `GiveNoXP` gate `0x0089DD19`.

`Money::deposit` `0x007B18B8` · `Money::withdraw` `0x007B17EF` (clamps, never refuses) ·
`Money` = `{ vptr, UnsignedInt current, Int m_playerIndex }`, 12 bytes · on `Player` at +0x90,
on `PlayerTemplate` at +0x2C.

`Player::init` `0x006B0239`, entry hook `0x006B0243`, resume `0x006B0249` · its money block
`0x006B0539` · `PlayerList` reset `0x006A8916` (20 slots, NULL template) · `Player::m_playerIndex`
+0x54 · `m_playerTemplate` +0x34.

`PlayerTemplate` field table `0x00BF81A8` (61 rows, **one** reference at `0x005FDF8E`) · ctor
`0x005FE3F1` · copy `0x005FDFF4` · block key in `eax` at `0x005FE880`, hooked there; resume
`0x005FE886` · `findPlayerTemplate` `0x005FCA2E` · `initFromINI` `0x005FDF75` · `NameKeyType`
+0x10 · `sizeof` `0x1DC`.

`ThingTemplate` id `+0x5E8` (setter `0x006CFBC7`, counter `0x00DA18E4`, ctor default `0x0073FF8D`)
· `BuildCost` `+0x5EA` · `RefundValue` `+0x5EC` · `CampnessValue` `+0x5E4` · `CommandPoints`
`+0x628` · `sizeof` `0x650`, allocated at `0x006D2750` and `0x006D27BD` · `copyFrom` `0x006D1D80`,
its id copy `0x006D24B7` · `calcCostToBuild` `0x0073C25F` · `Object` field table `0x00DA3DF8`
(191 rows, terminator `0x00DA49E8`, **five** references, no interior one).

`BuildAssistant` `+0x64` gate `0x00793ECB`, its gold test `0x00794013`, affordable `0x0079401E`,
refusal `0x00794019`, code 2 = not enough money · `canMakeUnit` `0x00794F38` · `Player` gold
`+0x94` · `queueCreateUnit` `0x008A11D2`, its withdrawal `0x008A12A2`.

The palantir's resource text: setter `0x006D56E1`, hook `0x006D5721`, resume `0x006D572C`, rejoin
`0x006D5751` · `"%d"` `0x00BD4194` (**8-bit**) · the `" "` placeholder `0x00BD343C` ·
`"APT:PalantirResources"` `0x00C19050`, its static `AsciiString` `0x00DE4A84` ·
`AsciiString::format` `0x00437A90` (cdecl) · `TheAptPlayer::setValue` wrapper `0x00625071` over
`0x00624FFD` · the refresh `0x006D577C`, its change filter `0x006D5804`, push `0x006D5809`, skip
`0x006D5813`, cached value `HUD+0x0C` · `PlayerList::getLocalPlayer` `0x006A8839` · `TheAptPlayer`
`0x00DE3F0C` (binding map `+0xA4`) · the HUD ctor `0x006D61BC` / teardown `0x006D4B6E` ·
`registerBinding` `0x006241CE`.

The cost line: `TOOLTIP:Cost` `0x00C4F028` (four sites; the two template-priced ones hooked at
`0x00807F82` and `0x008085EC`) · `TheGameText` `0x00DE4B04` vtable `+0x44` ·
`UnicodeString::format` `0x00ADF750` · `::concat` `0x00ADF7E0` · `::~UnicodeString` `0x004367B0` ·
the description buffer `ebp-0x28` · the "not enough" UI `0x00940A4A` / `0x0083E798`.

`INI::parseUnsignedShort` `0x0042EC11` (cdecl, range-checked, **word** store) · `INI::parseInt`
`0x0042EC5E` · `INI::getNextTokenOrNull` `0x0042DBF5` · `INI::scanInt` `0x0042E9D7` ·
`MultiIniFieldParse::add` `0x0042B8D7`.
