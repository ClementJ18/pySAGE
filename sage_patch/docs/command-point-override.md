# Command-point overrides, defeats and the lobby's command-point factor

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), read statically from the
repo's `game.dat`. **Status: statically derived. Both patches - `command-point-override` (the fix, §3) and
`command-point-modes` (more lobby entries, §4) - are built and static-verified, not yet played.**

Two questions about the same few routines:

1. A map script sets command points with `OVERRIDE_PLAYER_COMMAND_POINTS`, a player is defeated,
   and the command points go back to what they were. Why, and how is it fixed? (§1–§3)
2. Edain uses the lobby's command-point option as its game-mode picker. How are more entries
   added? (§4)

## 1. Where a player's command points come from

The bookkeeping subobject at `Player+0x60` (layout in
[`command-point-upkeep.md`](command-point-upkeep.md) §2) holds the base cap at `+0x04`, the hard cap
at `+0x10` and an **overridden** byte at `+0x2C`. One routine fills the first two.

`CommandPointBookkeeping::init(playerIndex, isEvil)`, `0x006A7C86`, `ret 8`, has one caller,
`Player::initCommandPoints` (`0x006AA432`), which passes `Player+0x54` and the template's evil flag
(`PlayerTemplate+0x1BC`). It picks a `{base, max}` pair from `GameData`:

| session | pair |
|---|---|
| multiplayer or skirmish, not living world | `Good/EvilCommandPointsMPn`, n = live players counted by `0x006A8630` (MP2 below 3, MP8 from 8) |
| otherwise, human | `Good/EvilCommandPoints` |
| otherwise, AI | `Good/EvilCommandPointsAI` |
| living-world battle | plus `ScoreKeeper`/region bonuses |

and then merges it into the bookkeeping:

```asm
006a7dc7  mov  al, [edi+0x2c]          ; overridden?
006a7dca  test al, al
006a7dcc  je   0x6a7dd3                ;   no  -> store
006a7dce  cmp  esi, [edi+0x10]         ;   yes -> store only if computed max is larger
006a7dd1  jle  0x6a7dd6
006a7dd3  mov  [edi+0x10], esi         ; hard cap
006a7dd6  test al, al
006a7dd8  je   0x6a7ddf
006a7dda  cmp  ebx, [edi+4]            ;   same for the base
006a7ddd  jle  0x6a7de2
006a7ddf  mov  [edi+4], ebx            ; base
006a7de2  mov  eax, [0xde892c]         ; TheGameInfo
...
006a7df1  cmp  dword [ecx+0x114], 3    ; not a living-world session
006a7dfa  mov  eax, [eax+0x6c]         ; GameInfo rule 3: the lobby's CommandPointFactor
006a7dfd  imul eax, [edi+0x10]
006a7e05  idiv 100                     ; hard cap *= factor / 100
006a7e07  mov  [edi+0x10], eax
```

**The override is a floor, not an override.** On an overridden bookkeeping each value becomes
`max(current, computed)`, and the hard cap is then scaled by the factor *again*.

The script side is `OVERRIDE_PLAYER_COMMAND_POINTS` (action 504: player, total, maximum). Its case
body (`0x007CF2BF`) calls `0x007BDC36`, which resolves the player (or every player of a multi-player
argument) and calls `CommandPointBookkeeping::override` at `0x006A7ACD`:

```asm
006a7acd  mov  eax, [esp+4]  /  mov [ecx+4], eax      ; base  = total
006a7ad4  mov  eax, [esp+8]  /  mov [ecx+0x10], eax   ; hard  = maximum
006a7adb  mov  byte [ecx+0x2c], 1                     ; overridden
```

So an override writes raw numbers, with no factor applied. `0x006A8183`, called from `Player::init`,
clears the byte. The bookkeeping's xfer saves it from version 7 (`0x006A83A7`), so a save keeps it.

## 2. What a defeat does

`Player::killPlayer`, `0x006ABE7C`, sets `Player+0x754` (`PLAYER_IS_DEFEATED`), destroys what the
player owns, and then:

```asm
006abf3c  mov  ecx, [0xde4928]         ; ThePlayerList
006abf42  mov  eax, [ecx]
006abf44  call [eax+0x40]              ; PlayerList::recomputeCommandPoints
```

`PlayerList`'s vtable is `0x00C136F0` (stored by both constructors, `0x006A83E1` and `0x006A89CE`).
Slot `+0x40` is `0x006A84F3`: for all twenty players, `Player::initCommandPoints`, which is §1's
`init`. This is the only call through that slot. The obvious reason for it is that n, the live
player count, has just changed, so every `MPn` pair may be different.

Put §1 and §2 together. Every defeat re-runs `init` for every player, and for an overridden player:

- the base becomes `max(scripted total, GameData base)`;
- the hard cap becomes `max(scripted maximum, GameData max) * factor / 100`.

A script that **lowered** command points loses the lowering at the first defeat. A script that
**reset** them after reading the factor (Edain's game modes, §4) gets the factor back. And with a
factor other than 100, the hard cap is multiplied again at each defeat even when the override was
the larger value. Nothing else calls `init` after the game has started.

## 3. The fix

`command-point-override` rewrites the merge in place, `0x006A7DC7`–`0x006A7DE1`, 27 bytes:

```asm
006a7dc7  cmp  byte [edi+0x2c], 0
006a7dcb  jne  0x6a7e0a                ; overridden -> return, bookkeeping untouched
006a7dcd  mov  [edi+0x10], esi         ; otherwise the stock unconditional stores
006a7dd0  mov  [edi+4], ebx
006a7dd3  jmp  0x6a7de2                ; and the stock factor
006a7dd5  nop x13
```

`0x006A7E0A` is `pop ebx / pop edi / pop esi / leave / ret 8`. Every path into the merge comes after
`push ebx` at `0x006A7CCA`, and the routine's own other exit after that point (`0x006A7EE1`) uses the
same epilogue. The only branches into the rewritten range come from inside it (checked with `xref`
over each byte).

Effect:

- **An overridden player keeps exactly the scripted base and maximum** until a script overrides
  again. That holds through defeats, and also through the player-count change that would have
  picked a different `MPn`.
- **Everyone else is unchanged.** A bookkeeping no script touched takes the same path as stock: the
  `max` was never on its path.
- The overridden player also no longer picks up living-world region bonuses on a recompute. A
  script that overrides command points has taken them over, so that is intended.

No INI change. Every peer runs the same `game.dat`, so this is not a desync concern.

### Confirming it in a game

1. Skirmish, three or more players, with a map script that calls `OVERRIDE_PLAYER_COMMAND_POINTS`
   on the local player with a total and maximum **below** the `GameData` `MPn` values (or any values
   at a factor other than 100).
2. `python -m sage_live info`: read `Player+0x64` (base) and `+0x70` (hard cap) for that player.
3. Defeat one AI. Stock, both jump back to the `GameData`/factor numbers. Patched, they stay put.

## 4. More command-point modifiers in the lobby

### What the option is

The lobby's rules (`AptMpGameRules`, the `RuleComboBox_N` gadgets) come from static tables.
`0x00960A10(ruleSet)` returns a NULL-padded array of combo descriptors. For rule set 0 (skirmish,
LAN, online) that array is `0x00DB77BC`, with length 2 hard-coded at `0x00960A46`. A descriptor is:

```
+0x00  Int  rule        index into GameInfo's ten GR rules (GameInfo+0x60 + 4*rule)
+0x04  ptr  options     {const char *label, Int value} pairs
+0x08  Int  count
+0x0C  Int  default     option index
```

| descriptor | rule | options | count | default |
|---|---|---|---|---|
| `0x00C825E0` | 4, `InitialResources` | `0x00C82588` | 11 | 2 (1000) |
| `0x00C82578` | 3, `CommandPointFactor` | `0x00C82540` | 7 | 2 (100) |

The `CommandPointFactor` options, with the labels Edain's `lotr.str` gives them:

| value | label key | Edain's text |
|---|---|---|
| 33 | `VALUE:ThirdX` | Massacre |
| 50 | `VALUE:HalfX` | Elite |
| 100 | `VALUE:1X` | Skirmish (default) |
| 200 | `VALUE:2X` | FreeBuild |
| 400 | `VALUE:4X` | Conquest |
| 800 | `VALUE:8X` | Legendary Heroes |
| 10000 | `VALUE:100X` | Epic Battle |

Edain also renames `RULE:CommandPointFactor` to "Game Mode".

### Why a longer list needs no code change

- **The combo is built from the descriptor**: `GAME_RULES_POPULATE` (`0x00986B1C`) loops `count`
  times and adds each `label` (localised) with `value` as the item's data.
- **Choosing an option** writes `options[index].value` into the rules array (`0x00960A74`). The
  `GR` string carries values, not indices: peers, `Skirmish.ini` and the replay header all store
  the number.
- **Showing a received value** matches it against the items' data (`0x00986624` →
  `COMBO_BOX_GET_ITEM_DATA`). A value no item carries shows no selection and changes nothing else.
- **In a game**, the factor's only simulation reader is §1's `hard cap *= factor / 100`. The two
  other readers are a stats string at `0x00903D30` and the online lobby's
  `APT:CommandPointsTooHigh` warning for a factor above 100 (`0x008422E5`), which 200–10000 already
  trigger.

So adding entries is data only, and that is what `command-point-modes` does:

```sh
python -m sage_patch apply command-point-modes --in game.dat --modes "300=VALUE:Siege,1500=VALUE:Ranked" --default 100
```

It writes a section `.cpmodes` holding the stock seven pairs, copied byte for byte so their
labels stay the `.rdata` strings, then the new pairs and their label strings. It then rewrites
the 16-byte descriptor at `0x00C82578` to point at that list, with the new count and the default
index. Nothing in `.text` changes, and no other patch touches these tables, so it composes with
everything. Before writing, it checks two things: the stock list is intact, and rule set 0's combo
array (`0x00DB77C0`) still points at this descriptor.

The parameters are checked before anything is written:

- **Values** must be 1–100000, unique, and not one of the stock seven. The lobby selects by value,
  so a repeated value could never be shown as chosen. The ceiling keeps
  `hard cap * value` inside the engine's 32-bit `imul`.
- **Labels** are string-table keys of up to 63 ASCII characters, with no spaces.
- **At most 32 entries.**
- **`--default`** must be one of the values (stock is 100).

`detect` reads the list back from the descriptor and section, so `sagepatch`/`rebuild` keep the
parameters.

### What it takes outside the binary

- **Strings.** A `VALUE:<key>` entry in `lotr.str`/`.csf` for each new label. An absent one renders
  as the missing-string marker, not a crash. The engine fetches the label with the value as its
  format argument, so the text may contain `%d`. The default entry gets `VALUE:Default` appended.
- **Distinct values that scripts can tell apart.** The factor never reaches a script directly. A
  map sees it only as the hard cap, `MPn.max * factor / 100` (integer division), through
  `SET_PLAYER_COMMAND_POINTS_TOTAL_TO_COUNTER` and friends. Each new mode's value must give a hard
  cap no other mode gives, for every `MPn` Edain ships (all `COMMAND_POINTS_MAX` today, which makes
  this easy). Values that are not meant to change command points must be undone by script, which
  is exactly the override `command-point-override` now keeps.
- **Every peer needs the patched list** to show and pick the new entries. An unpatched peer still
  plays the number it receives; it just shows no selection. Everyone runs the same `game.dat`, so
  this is moot.
- **`sage_replay`** labels GR rules 3 and 4 the wrong way round (see
  [`game-info.md`](game-info.md) §7). Fix that before it reports game modes.

### Open

1. **The combo's height.** `Apt/ComboBox.wnd` is shared by every rule combo, and none in stock has
   more than eleven entries. Whether a list of twelve or more scrolls or clips has to be seen in the
   lobby.
2. **A cleaner signal than a scaled hard cap.** A script condition that reads `GameInfo+0x6C`
   directly would let a game mode stop meaning "a command-point factor" at all. Neither is built;
   the CP-factor route needs no new script surface.
