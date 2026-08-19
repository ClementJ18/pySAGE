# Making `AutoDepositUpdate` obey the income inflation

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), read from
`sage_mods/edain/patching/engine/game.dat.backup` — the clean reference, not the repo-root
`game.dat`. This is the writeup for the **`auto-deposit-inflation`** patch,
[`patches/auto_deposit_inflation.py`](../patches/auto_deposit_inflation.py), with the tests in
[`tests/sage_patch/test_auto_deposit_inflation.py`](../../tests/sage_patch/test_auto_deposit_inflation.py).

**What it does.** `AutoDepositUpdate`'s deposit is scaled by the faction's
`ResourceModifierValues` inflation — the per-building income penalty the engine already applies to
`TerrainResourceBehavior` and to nothing else.

```sh
sage-patch apply auto-deposit-inflation --in game.dat.backup --out game.dat   # no parameters
sage-patch verify auto-deposit-inflation game.dat
```

**Status: built and static-verified.** The window holds its stock bytes in both binaries, no
branch reaches its interior, the cave disassembles cleanly, apply/verify/detect round-trip, and it
composes in both orders with `maintenance-cost`, `command-point-upkeep` and `inflation-readout`.

**One 5-byte detour and a 242-byte cave.** No new INI field: it reuses the two `PlayerTemplate`
fields every faction already declares.

---

## 1. The asymmetry

The engine has two "this structure pays you on a timer" modules, and applies inflation to exactly
one of them.

| | module | reads `ResourceModifierValues` | in Edain |
|---|---|---|---|
| resource spots | `TerrainResourceBehavior` | **yes**, at `0x00885685` | 274 uses |
| flat tick income | `AutoDepositUpdate` | no | 126 uses |

`TerrainResourceBehavior::update` (`0x008854D3`) is the **only** reader of
`PlayerTemplate.ResourceModifierValues` in the whole image — see
[`inflation-readout`](inflation-readout.md) §1, which reproduces the computation for the HUD, and
[`command-point-upkeep`](command-point-upkeep.md), which multiplies a second factor into the same
slot. `AutoDepositUpdate::update` pays `DepositAmount` flat, for ever.

In Edain that split is load-bearing rather than incidental. `_gamedata.inc` gives the castle and
camp keeps `GENERIC_KEEP_MONEY_AMOUNT 40` every `GENERIC_KEEP_MONEY_TIME 12000` ms, and outposts
`OUTPOST_KEEP_MONEY_AMOUNT 10` on the same clock — through `AutoDepositUpdate`. So a keep's base
income is the one income in the game that a player's building count never touches, and the more
farms they own the larger the *share* of their economy that inflation cannot reach.

## 2. Where to multiply

The whole amount path, `0x0089DC99`–`0x0089DD08`:

```asm
0089dc99  mov  eax, [esi-0xc]               ; the ModuleData
0089dc9c  cvtsi2ss xmm0, dword [eax+0xc]    ; DepositAmount
0089dca7  mulss xmm0, xmm1                  ; UpgradeBonusPercent, or 1.0
0089dcab  movss [ebp-0x14], xmm0
0089dcb0  call 0x625456                     ; a solo game?
0089dcb7  je   0x89dcdd                     ;   no  -> skip the handicap        <- (!)
0089dcd2  call 0x642002 / fmul [ebp-0x14]   ;   yes -> the difficulty handicap
0089dcdd  cvttss2si eax, [ebp-0x14]         ; the amount stops being a float    <- the window
0089dce2  push eax
0089dce5  call 0x6aa858                     ; the WotR region money bonus
0089dced  fild [ebp-0x14] / call 0xa3cfa4   ; round half away from zero
0089dcf5  push 1 / push scorekeeper / push eax
0089dcff  lea  ecx, [edi+0x90]              ; &player->m_money
0089dd08  call 0x7b18b8                     ; Money::deposit
```

`0x0089DCDD` is the right place for three separate reasons.

**It is where the value stops being a float.** Everything above it is `xmm0`/`[ebp-0x14]`
arithmetic and everything below is an integer, so a multiply here needs no conversion of its own
and adds no rounding step — the displaced `cvttss2si` simply truncates the scaled value instead of
the unscaled one.

**It is where both paths converge.** The `je` at `0x0089DCB7` (marked `(!)` above) targets this
address, so a skirmish (no handicap) and a campaign game (handicap applied) both arrive here. One
hook covers both. A detour whose *first* byte is a branch target is exactly right; one whose
interior is a branch target would be fatal, and §5 establishes that no branch reaches this
interior.

**It is five bytes holding one instruction.** `f3 0f 2c 45 ec` is `cvttss2si eax, dword ptr
[ebp-0x14]`, and a `jmp rel32` is five bytes. No `nop` padding, no partially displaced second
instruction — the only hook in this pair of patches that pads nothing.

The resulting order — after `UpgradeBonusPercent` and the handicap, before the region bonus and the
final rounding — is where `TerrainResourceBehavior` applies its own (after its upgrade bonus,
before its own final `ceil`), so the two modules agree about more than the number.

## 3. The multiplier

The cave reproduces `0x008855A3`–`0x0088564B` instruction for instruction:

```
tmpl  = player->m_playerTemplate          (Player+0x34)          ; null -> 1.0
filt  = &tmpl->ResourceModifierObjectFilter (+0x1C8)
if !ObjectFilter::isValid(filt)                                  ; -> 1.0
if !ObjectFilter::allow(filt, thisObject, player)                ; -> 1.0   <- the gate
count = Player::forEachTeamObject(player, 0x00885230, {filt, 0})
n     = tmpl->ResourceModifierValues.size()                      ; 0 -> 1.0
mult  = count < n ? values[count] * 0.01f
                  : max(0, values[n-1] * 0.01f - (count - n) * 0.02f)
```

Three things about that are deliberate.

**The object gate is kept.** `filter.allow(thisObject, player)` at `0x008855CE` is what the engine
asks before taxing a deposit, and reproducing it is what makes a faction whose
`ResourceModifierObjectFilter` does not accept its keeps **byte-for-byte unaffected at run time**.
Dropping it would silently tax every structure in the game that carries the module, including
captured neutral ones — the scope line [`command-point-upkeep`](command-point-upkeep.md) draws for
the same reason.

**The count comes from the engine's own callback** (`0x00885230`), not a second loop. That
callback skips objects failing `testStatus(2)` and calls `allow(o, NULL)` with a *null* player
where the gate three instructions earlier passes the real one; reusing it inherits both, which is
the only way this patch's number and `TerrainResourceBehavior`'s are the same number by
construction rather than by inspection. `inflation-readout` reuses it for the same reason, and
`multiplier()` in the two modules is asserted to agree for counts 0–11.

**The factor lives in memory across the calls.** Nothing in this image's calling conventions
promises an SSE register survives a call, so the multiplier is kept at `[ebp-0x04]` in the helper's
own frame and only loaded into `xmm0` at the tail. Every degenerate path therefore yields the
`1.0f` the prologue stored.

One deliberate divergence, the same one `inflation-readout` makes: a faction that sets
`ResourceModifierObjectFilter` and no `ResourceModifierValues` reaches `values[n-1]` of an **empty
vector** in the engine — a stray read of one dword. The cave returns `1.0f` instead.

## 4. What applying it costs

**It re-balances a mod, on purpose.** Every `AutoDepositUpdate` starts paying less as its owner's
inflation-listed object count rises. In Edain a keep's 40 gold a tick becomes 40 gold a tick times
whatever the palantir's resource-multiplier readout is showing — install
[`inflation-readout`](inflation-readout.md) and the number is on screen while it happens. This is
the entire content of the patch, and it is why it is a patch rather than a branch inside
[`maintenance-cost`](maintenance-cost.md).

**It costs one object walk per deposit tick per structure.** `Player::forEachTeamObject` writes
nothing and takes no lock, and `TerrainResourceBehavior` already spends exactly this on every one
of its own ticks. `DepositTiming` is milliseconds and Edain's is 12000, so it is one walk every
twelve seconds per keep.

**Money is logic state and the engine CRCs it**, so every peer must run the same patched binary —
the `command-point-upkeep` rule, stricter than the client-local `inflation-readout`.

## 5. The window is safe, and how that was actually established

The first attempt at this check used a linear sweep of `.text` with capstone. **It was wrong**:
`Cs.disasm` stops at the first undecodable byte and returns what it had, so the sweep covered
43,078 instructions of a 8.2 MB section and silently answered "no branches" for every window in
both patches — including one address it could be proved wrong about by hand.

[`scripts/scan_branches.py`](../scripts/scan_branches.py) replaces it and cannot fail that way: it
decodes a branch at **every byte offset** in `.text`, treating each of `E8`/`E9`/`EB`/`70–7F`/`0F
80–8F` as a possible instruction start. That over-approximates — most of those offsets are not
instruction boundaries — so it yields false positives and never a false negative. A window it
reports nothing for is unreachable by any direct branch. It also counts appearances of each window
byte as an absolute `imm32` anywhere in the image, which is what would catch a jump table.

```
TRB income gate (in place)           first-byte:   0   INTERIOR: []
TRB floor                            first-byte:   0   INTERIOR: []
TRB pay                              first-byte:   0   INTERIOR: []
ADU scale (auto-deposit-inflation)   first-byte:   1   INTERIOR: []
ADU pay                              first-byte:   0   INTERIOR: []
ADU xp gate                          first-byte:   0   INTERIOR: []
```

The one first-byte hit is the `je 0x0089DCDD` from `0x0089DCB7` discussed in §2, which is the
convergence a detour wants. No window byte appears as an `imm32` anywhere.

## 6. With `maintenance-cost`

[`maintenance-cost`](maintenance-cost.md) hooks `0x0089DCFF`, eight bytes below this window, and
performs **no arithmetic** on the amount — it reads the sign and either lets the deposit happen or
negates the value into `Money::withdraw`. So the two patches meet at a single number in `eax` and
neither contains a reference to the other:

```
0089dcdd  jmp <.adinfl>   ; amount *= inflation          (this patch)
0089dce2  ...             ; region bonus, rounding       (stock)
0089dcff  jmp <.upkeep2>  ; pay it, or charge it         (maintenance-cost)
```

Which produces exactly the intended rule, in both directions:

| | income (`DepositAmount > 0`) | charge (`DepositAmount < 0`) |
|---|---|---|
| neither patch | flat | discarded |
| `maintenance-cost` only | flat | **flat charge** |
| both | inflated | **inflated charge** |

`TerrainResourceBehavior` needs none of this: its income has always been inflated, so its charge
always is too.

## 7. Site table

| what | VA | window | resume |
|---|---|---|---|
| the amount truncation | `0x0089DCDD` | `f30f2c45ec` | `0x0089DCE2` |

Engine routines the cave calls: `ObjectFilter::isValid` `0x00762977` · `ObjectFilter::allow`
`0x007640C1` · `Player::forEachTeamObject` `0x006ABABD` · the counting callback `0x00885230`.
Constants: `1.0f` `0x00BD1908` · `0.01f` `0x00BE5600` · `0.02f` `0x00BDC320`. Offsets:
`Player::m_playerTemplate` `+0x34` · `ResourceModifierObjectFilter` `+0x1C8` ·
`ResourceModifierValues` `+0x1CC`.
