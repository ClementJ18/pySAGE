# Command-point upkeep

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), read from the repo's
clean `game.dat`. Implemented by [`patches/command_point_upkeep.py`](../patches/command_point_upkeep.py);
the palantir side of it lives in [`inflation-readout.md`](inflation-readout.md), which draws the
product of both patches' factors.

**What it does.** A faction's resource buildings pay less as its army grows. Two new
`PlayerTemplate` fields declare the curve, the deposit is scaled by it, and the palantir's
command-point readout gains a third number saying how much is currently being lost:

```
UpkeepCommandPointStep = 500                 ; Int. 0 (the default) == no upkeep at all.
UpkeepValues           = 100 90 80 70 60 50  ; percent of income kept, indexed by tier
```

`tier = commandPointsInUse / step`, clamped to the last entry. So the block above is
"−10% per 500 command points, floored at −50%", and a player sitting at 500 CP with a cap of
1500 sees `500/1500 (-10%)` where the stock engine draws `500/1500`.

**Status: built and static-verified; not yet runtime-verified in a game.** The bytes apply,
disassemble as intended and verify. The in-game behaviour check is open — see
[Verifying it in a game](#verifying-it-in-a-game).

## 1. The mechanic it rides on

`PlayerTemplate.ResourceModifierValues` — the per-building "inflation" every Edain faction sets —
is not an analogue of upkeep. It is **the same computation**, and it has exactly one reader in
the whole image: `AutoDepositUpdate::update` at `0x008854D3`, the tick-income module, which Edain
puts on **97** objects.

```
PlayerTemplate  sizeof 0x1DC          vptr 0xBF7D20, ctor tail 0x5FE59C, dtor 0x5FD8D0
       +0x10    NameKeyType           the block name's interned id
       +0x1C8   ObjectFilter          ResourceModifierObjectFilter (4 bytes: an interned handle)
       +0x1CC   std::vector<Int>      ResourceModifierValues       (0x1CC/0x1D0/0x1D4)
       +0x1D8   AsciiString           MultiSelectionPortrait
```

```asm
008855a3  mov  eax, [esi+0x34]          ; esi = controlling Player -> its PlayerTemplate
008855ae  lea  ecx, [eax+0x1c8]         ; &tmpl->resourceModifierFilter
008855bc  call 0x762977                 ; ObjectFilter::isValid       -> bail if unset
008855ce  call 0x7640c1                 ; filter.allow(thisObject, player) -> bail if no match
008855e5  push 0x885230                 ; per-object callback: counts matching objects
008855ec  call 0x6ababd                 ; Player::forEachTeamObject   (Player+0x34C)
008855f7  add  eax, 0x1cc               ; &tmpl->resourceModifierValues
00885601  sub  eax, ecx / sar eax, 2    ; n = values.size()
00885606  cmp  edx, eax                 ; edx = count
0088560a  cvtsi2ss/mulss [0xBE5600]     ; in range : mult = values[count] * 0.01
0088561e  ...      mulss [0xBDC320]     ; past end : values[n-1]*0.01 - (count-n)*0.02, floor 0
                                        ;            -> [ebp-0x1c]
```

and then the deposit itself:

```asm
00885650  mov  eax, [ebp-0x18]          ; the AutoDepositUpdate ModuleData
00885653  fild dword ptr [eax+0xc]      ; DepositAmount
00885658  fmul [ebx+0x1c]               ; per-instance scale
0088565b  fmul [ebp-0x10]               ; attribute modifier (type 0xD)
0088565e  fmul [ebp-0x14]               ; UpgradeBonusPercent
00885685  fmul [ebp-0x1c]               ; the inflation multiplier
0088569f  if (amount <= 0) amount = 1   ; income can never round to zero
008856b6  call 0x7b18b8                 ; Money::deposit(amount, player+0x3DC, TRUE)
```

Three properties of the stock mechanic that the patch inherits:

- **The tier index counts the depositing building itself**, so index 0 is never reached — which
  is why Edain's tables open with five `100`s and still mean "no penalty until the sixth
  building".
- **The table extends itself** past its last entry, at −2% per extra object, floored at zero.
- **The multiplier is applied last, and the result is clamped to ≥ 1 gold.** Upkeep therefore
  stacks multiplicatively on inflation and inherits that floor for free.

### Do not confuse it with the other two "resource modifiers"

Three unrelated mechanisms share the name; only the first is on this code path.

| mechanism | entry point | what it modifies |
|---|---|---|
| `PlayerTemplate.ResourceModifierValues` | `0x8855A3` | **income**, per resource building |
| `CostModifierUpgrade` | `Player::getResourceModifier` `0x6AD8A7`, list at `Player+0x714` | build cost, via `ThingTemplate::calcCostToBuild` `0x73C25F` |
| `GameData.ResourceMultiplierLimit` (`+0xE98`, default `4.0`) | `0x6E1F2F` | the War-of-the-Ring **region** bonus, and the `ResourceMultiplier` palantir binding |

## 2. Where the command-point number lives

Already an engine field, so there is nothing to count and nothing to maintain.

```
Player +0x34   PlayerTemplate*                (the final override)
       +0x60   command-point bookkeeping subobject
       +0x04     base cap
       +0x08     command points IN USE        <- Player+0x68
       +0x0C     cap bonus
       +0x10     hard cap
       +0x14     player index
       +0x20/24  vector of conditional cap bonuses
```

| what | VA | note |
|---|---|---|
| `getCurrentCommandPoints` | `0x6A7AC7` | `mov eax,[ecx+8]; ret 4` — takes an argument and ignores it |
| `getCommandPointCap` | `0x6A7B9F` | base + bonus + conditional entries, clamped to `+0x10` |
| add on object create | `0x6A7FDA` | from `0x6AA588` |
| subtract on destroy | `0x6A7FEB` | from `0x6AA5AB` |
| per-object cost | `0x6A7FAA` | returns `ThingTemplate+0x628` (`CommandPoints`), 0 for some KindOfs |

Reading it from the deposit site is `mov esi, [ecx+0x68]` — one instruction, no call.

`Player+0x34` is corroborated twice: the palantir refresh reads `[ebx+0x34]` and then
`template->PlayableSide` at `+0x151` (`0x6D586A`), and `AutoDepositUpdate` reads the same slot to
reach `+0x1C8`.

## 3. Where the per-faction numbers live

**Not on the `PlayerTemplate`**, and the reason matters more than the alternative.

- There is no hole. The struct is `0x1DC` bytes; the apparent gap at `+0x152` is a **subobject
  with its own field table**, added by `PlayerTemplate::parse` with extra offset `0x154`
  (`0x5FDF9E`).
- Growing it means correcting **24** separate `0x1DC` literals in the store's compiland alone
  (`0x5F478E`–`0x5FEA98`), plus the copy constructor and the assignment operator.
- And a pointer key would not survive anyway. Templates live in a `std::vector<PlayerTemplate>`
  at `PlayerTemplateStore+0x0C`, and a **new block is parsed into a stack temporary** at
  `[ebp-0x1F4]` (`0x5FE935`) before being copied in — so the `this` a field callback receives is
  transient, and the next block reuses the same stack address.

So the rows live in the cave, keyed by `PlayerTemplate+0x10`, the block name's `NameKeyType`.
That is the one stable identity a template has, and
`PlayerTemplateStore::findPlayerTemplate` (`0x5FCA2E`) proves it survives the vector copy — it
finds a template by walking the vector at stride `0x1DC` comparing exactly that dword.

### Getting the key to the field callback

The key is computed once per block, at the top of the block parser and **before** the three
parse paths branch:

```asm
005fe86c  call 0x42dc9f              ; ini->getNextToken()  -> "FactionGondor"
005fe87b  call 0x5487ec              ; TheNameKeyGenerator->nameToKey(name)
005fe886  mov  edi, eax              ; <- the hook: also store it in the cave
005fe888  push edi
005fe889  call 0x5fca2e              ; findPlayerTemplate(key)
```

The three paths that follow all need it and none of them has it earlier than this:

| path | site | `this` during parse |
|---|---|---|
| a new block | `0x5FE94E` | a stack temporary; `+0x10` not yet written |
| an override block (mode 2) | `0x5FE8DF` | a fresh `operator new(0x1DC)`; `+0x10` not yet written |
| re-parse of an existing one (mode 5) | `0x5FE8F8` | the live template; `+0x10` already valid |

One hook at `0x5FE886` covers all three.

**Consequences of keying by name rather than by pointer**, all of them wanted:

- **No savegame change and no init hook.** The rows are INI-derived and rebuilt on every load;
  the command-point count is an existing `Xfer`'d field. Nothing new is per-game state.
- **An override block merges rather than replaces.** A `map.ini` re-declaring a faction shares
  its key, so it overwrites only the fields it names — where the engine's own copy semantics
  would have dropped the rest.
- **A missing row is "no upkeep", never a wrong number.** A full table, an absent key and a zero
  step all take the same untaxed path.

### The row table

`{ UnsignedInt key; Int step; UnsignedInt count; Int values[16]; }`, 76 bytes, 128 rows,
open-addressed with a linear probe and no removal. A key of 0 is the empty marker. Edain defines
about forty `PlayerTemplate` blocks, so the table is roughly a third full at worst.

## 4. Parsing

Both fields share one parse function and are told apart by `userData`; both carry table offset
**0**, because neither is written into the template at all.

```
UpkeepCommandPointStep   userData 0   one Int, the shape of the stock INI::parseInt
UpkeepValues             userData 1   Int tokens to end of line, the shape of 0x5FD599
```

The only engine help it needs is the pair the stock `ResourceModifierValues` parser loops over:
`INI::getNextTokenOrNull` (`0x42DBF5`) and `INI::scanInt` (`0x42E9D7`), both thiscall on the
`INI` and both `ret 4`. **Tokens are consumed even when there is no row to put them in**, so a
full table or a missing block key cannot leave the parser mid-line.

**The `PlayerTemplate` field-parse table has exactly one reference** — `push 0xBF81A8` at
`0x5FDF8E`, with no interior references. That is the smallest repoint in this tree; `hero-mana`
moves a two-reference table and a five-reference one, `production-condition` sixteen.

## 5. The charge

One detour, at `0x885650`, six bytes (`mov eax,[ebp-0x18]` + `fild dword ptr [eax+0xc]`).
`[ebp-0x1c]` holds the finished inflation multiplier and nothing touches it between there and
the `fmul` at `0x885685`, so the cave multiplies it by `percent / 100` and returns.

```
mult *= kept(player) / 100      where kept = UpkeepValues[min(cp / step, count-1)]
```

The hook site is bounded on both sides for a reason. It cannot move later, because a `fistp` at
`0x885672` **reuses `[ebp-0x20]`** — the slot still holding `&template->ResourceModifierObjectFilter`
at `0x885650` — for the rounded amount.

**Only filtered income is taxed.** The cave re-runs the exact pair of calls the inflation block
made a few instructions earlier: `ObjectFilter::isValid` (`0x762977`) then
`ObjectFilter::allow(object, player)` (`0x7640C1`), with `esi` = the `Player` and `edi` = the
`Object`. `AutoDepositUpdate` is *all* tick income — Edain also puts it on civilian buildings,
outposts and creep lairs — and without the gate upkeep would silently tax captured neutral
structures too. A faction with no `ResourceModifierObjectFilter` therefore gets no upkeep,
exactly as it gets no inflation.

The x87 stack is empty at the hook (the displaced `fild` is the next push), so the cave's one
`fild` / `fstp` pair is balanced.

> `fild dword ptr [esp]` is **`DB /0`**. `DF /0` is the 16-bit form, and it assembles, applies
> and verifies exactly as happily while reading half the value. The first draft had it wrong;
> `test_command_point_upkeep.py` now asserts the operand width.

## 6. The display

The palantir's command-point text is **not** a numeric data binding. `0x0080078F` formats
`L"%d/%d"` (`0x00C4E594`, UTF-16) with `(used, cap)` into a `UnicodeString` and hands it to
`TheAptPlayer::setValue("APT:PalantirCommandPoints", …)` (`0x00624FFD`). It has exactly one
caller, the HUD refresh at `0x6D5968`.

A mod's `.csf` / `.str` entry of the same name is a **design-time placeholder**, not the live
text — Edain's `Lotr.csv` carries `apt:palantircommandpoints;102/200`, next to
`apt:palantirresources;1000` and `apt:palantirresourcemultiplier;x23`. All three are overwritten
every refresh. So a third number has to come from the engine, and no data edit can produce it.

`UnicodeString::format` is cdecl, so its varargs are pushed **last-argument-first** and the
trailing `add esp` counts them. The hook therefore sits at `0x8007DC`, *before* the first vararg
push — the only place a third one fits:

```asm
008007dc  cmp  [ebp+0xc], edi          ; <- the six-byte window taken
008007df  push dword ptr [ebp+8]       ;    (cap, vararg 2)
008007e2  lea  eax, [ebp-0x10]
008007e5  jl   0x8007fa                ; a negative "used" falls back to a single %d
008007e7  push dword ptr [ebp+0xc]     ;    (used, vararg 1)
008007ea  push 0xc4e594                ;    L"%d/%d"
008007f0  call 0xadf750                ;    UnicodeString::format
008007f5  add  esp, 0x10               ;    two varargs + this + fmt
```

With a non-zero loss the cave pushes `(loss, cap, used)`, its own `L"%d/%d (-%d%%)"`, cleans
`0x14` instead of `0x10` and rejoins at `0x800817`. With zero loss it re-emits the displaced
compare and push and rejoins at `0x8007E2`, so the stock two-number form — including the
negative-`used` branch — is byte-identical.

The loss shown is the **local** player's, read through `PlayerList::getLocalPlayer`
(`0x6A8839`), which is how the refresh itself reaches the player whose numbers are drawn. The
whole HUD path is a pure read; a write there would desync.

`--no-hud` skips this edit entirely and leaves the text as the stock engine draws it.

### A caveat on what the number means

The palantir shows usage against the **cap**, and upkeep bands are **absolute**. A faction whose
cap is 400 can never reach a `500+` threshold; one whose cap is 3000 spends most of the game in
a band. That is what was asked for, and it is worth knowing before tuning: the thresholds are
army-size thresholds, not a fraction of the player's cap.

## Cross-cutting

- **Every peer must run the same patched binary.** Income decides what gets built, so the effect
  is inside the simulation: a patched and an unpatched client desync and replays do not cross.
  Same rule as `production-condition`, stricter than `replay-outcome`'s client-local guarantee.
- **Determinism.** Every input is simulation state identical on every peer — the player's
  command points, its template's name key, the INI. No pointer *value* is read, and the only
  writes happen at INI load.
- **No AI work.** Upkeep never makes something unaffordable that the AI believes it can afford;
  it only makes gold arrive more slowly, exactly as the existing inflation already does. Expect
  the AI to *play* worse under a harsh curve, not to stall.
- **No per-frame hook**, so no collision with [`live-bridge`](../patches/live_bridge.py)'s
  `GameLogic::update` hook.
- **Composition.** The cave is allocated past every existing section and `verify` finds it by
  name. The field table is read **live** rather than assumed, so a patch that extended it first
  still composes. It shares no edited byte with any other bundled patch — `hero-mana` is the
  only other one that rebuilds field tables, and it rebuilds `Object` and `SpecialPower`.

## Verifying it in a game

Nothing below has been done yet.

1. **The curve.** Give one faction `UpkeepCommandPointStep = 100` and
   `UpkeepValues = 100 50 0`, build past 100 and then 200 command points, and watch income halve
   and then stop. A short step makes the effect visible in a minute rather than ten.
2. **Opt-in.** A faction with neither field set must earn exactly what it earns today. Run the
   same map on a patched and an unpatched binary and compare the gold curve.
3. **The gate.** Capture a neutral / creep structure that has `AutoDepositUpdate` but is outside
   `RESOURCE_MODIFIER_OBJECT_FILTER`, and confirm its income is *not* taxed.
4. **The HUD.** Confirm the suffix appears at the first threshold, tracks the tier, and vanishes
   at tier 0 — and that a `--no-hud` build draws the stock text.
5. **The overlap with inflation.** With both a full `ResourceModifierValues` and an upkeep curve
   set, confirm the two multiply rather than one winning.
6. **`map.ini` override.** Re-declare a faction in a map and confirm the row merges (a block
   that names only `UpkeepValues` keeps the base's step).

## Follow-ups

- `sage_ini`'s `PlayerTemplate` model now carries both fields
  ([`sage_ini/model/ini_objects.py`](../../sage_ini/model/ini_objects.py)).
  `docs/ini-types.json` is generated from a live binary by
  [`scripts/module_defaults.py`](../scripts/module_defaults.py) and does **not** carry them yet —
  the same open item `hero-mana` records for `ManaCost`.
- The model types `ResourceModifierValues` as `List[Float]`. The engine parses it with
  `INI::scanInt` (`0x5FD599` → `0x42E9D7`, `"%d"`), so it is an `Int` list. Harmless in practice
  and left alone here, but noted.
