# Targeting a `SpellRechargeModifierUpgrade` at named powers

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`). Read statically from the
clean `game_original.dat`. **Nothing here has run in a game yet.** The routines are checked under
an emulator (`tests/sage_patch/test_spell_recharge_targets.py`) against stand-ins for the engine
calls they make. §6 lists what only a match can confirm.

## 1. What the module does today

`SpellRechargeModifierUpgrade` has no idea which powers it affects. It writes one float per
player, and the recharge code decides which powers read it.

| routine | VA | effect on the player |
|---|---|---|
| `upgradeImplementation` | `0x008BA139` | `Player+0x71C++`, then `Player+0x718 = Percentage[level-1]` |
| `onDelete` (if executed) | `0x008B9FE0` | `Player+0x71C--`, re-reads the float |
| `onCapture(old, new)` | `0x008BA05E` | moves one level from the old owner to the new one, then `setUpgradeExecuted(1)` |

`Percentage` is a `vector<float>` at `ModuleData+0x138..+0x13C`, one entry per level. The level is
clamped to the list (`0x008BA171`). These three are the only writers of `+0x718`/`+0x71C`
(`0x006AAAEE`, `0x006AAAE0`, `0x006AAAE7`, each called only from them). `Player::xfer` saves both
fields (`0x006B281C`, `0x006B282A`), so the stock state survives a save.

Two routines read the float:

- **`startPowerRecharge`, flavour 1** (`0x00896E31`, 23 module vtables) uses it only for a power
  flagged `RESPECT_RECHARGE_TIME_DISCOUNT`:
  ```
  00896eba  mov eax, [eax+0x18] / shr eax, 5 / test al, 1   ; the flag
  00896ec2  je  0x896ed5
  00896ec4  mov ecx, [ebp-4]                                ; the controlling player
  00896ec7  call 0x6aaad2                                   ; fld [Player+0x718]
  00896ecc  fadd [1.0] / fstp [ebp-8]                       ; multiplier
  ```
  `edi` holds the ability's `ModuleData` throughout (`0x00896E3B`), with the raw template at
  `[edi+8]`.
- **flavour 2** (`0x00991500`, the `SpecialPowerUpdateModule` family, including
  `WeaponModeSpecialPowerUpdate`) applies it **with no flag test**:
  `0x00991569 mov ecx,[ebp-4] / call 0x6aaad2 / fadd [1.0]`. `edi` is the raw template here
  (`0x00991535`).

`SharedSyncedTimer = Yes` powers go to `Player::startSharedSyncedTimer` (`0x006AD1B0`), which
multiplies by the float at `0x006AD20E` with no flag test either.

So a mod can aim the discount only through the flag, and that aims it at every flagged power at
once, in practice the whole spellbook.

## 2. Why the discount can't be kept per player

The obvious design keeps a per-player record for each targeted module. The `Player` has no room
for it, and a cave-side table would not be saved. `Player::xfer` writes `+0x718`/`+0x71C`
explicitly, and nothing would write a cave table, so a loaded game would lose every targeted
discount until each upgrade fired again.

The patch avoids stored state altogether. Everything the discount depends on is already live and
saved: which objects the player owns, which modules they carry, and whether each module's upgrade
has executed (the mux interface's `+0x04` byte). The discount is **computed at the moment a power
starts recharging**, from those facts.

## 3. The patch: `spell-recharge-targets`

```ini
Behavior = SpellRechargeModifierUpgrade ModuleTag_SunflareFaster
  TriggeredBy           = Upgrade_Lore
  Percentage            = -25% -40%
  AffectedSpecialPowers = SpecialAbilitySunflare SpecialAbilityWordOfPower
End
```

- A module **with** `AffectedSpecialPowers` never touches `Player+0x718`/`+0x71C`, so the stock
  spellbook discount is unaffected by it. It discounts exactly the powers it names, flagged or
  not, in both recharge flavours.
- A module **without** it is stock, byte for byte in behaviour.
- Levels count **copies of the same module definition** (the same `ModuleData`): three signal
  fires of one template are level 3 of that template's `Percentage` list, clamped to its last
  entry. Stock counts every `SpellRechargeModifierUpgrade` of the player together.
- Different targeted modules that name the same power multiply, and they multiply with the stock
  discount: `(1 + stock) * (1 + a) * (1 + b)`.
- Names resolve when the INI loads. An unknown name, or a 17th one, is an INI error
  (`AffectedSpecialPowers: unknown special power '<name>'`). Every line replaces the list.

### Edits

| VA | stock | patched |
|---|---|---|
| `0x00650148` | `push 0x14C` | `push 0x194`: `ModuleData` grows by count, scratch and 16 template pointers |
| `0x00650160` | `call 0x8BA1AB` | the stock ctor, then zero the new tail |
| `0x008BA2AB` | `push 0x00C6F0D0` | the field table relocated into `.sprtgt` with the new row |
| `0x008B9FE0` | `onDelete` prologue | `jmp`: return for a targeted module, else resume at `+5` |
| `0x008BA139` | `upgradeImplementation` prologue | the same |
| `0x008BA05E` | `onCapture` prologue | the same, but a targeted module goes to the tail at `0x008BA128`, which still calls `setUpgradeExecuted(1)` |
| `0x00896EC2` | the 19-byte flag branch and discount | `call gate1` / `jmp 0x896ED5` |
| `0x00991569` | the 14-byte discount | `call gate2` / `jmp 0x991577` |

The eight bytes of the flag test at `0x00896EBA` are left alone, because `description-timers` and
`special-power-charges` anchor them. `gate1` is entered with the flags that `test al, 1` left
(a `call` does not change them) and re-runs the stock branch itself.

### The discount walk

`factor(player, template)`: two passes of `Player::forEachTeamObject` (`0x006ABABD`) with one
callback. For each object that is not `DESTROYED` (`+0x94` bit 0) and whose controlling player is
`player`, it walks `Object+0x24C` for modules whose vtable is `0x00C6F020`
(`SpellRechargeModifierUpgrade` only: that vtable, the ctor and the three routines each have
exactly one reference). A module counts if its upgrade has executed (byte `module+0x14`) and its
list names the template.

- Pass 1 increments the module's `ModuleData` scratch counter.
- Pass 2 applies `1 + Percentage[min(level, size) - 1]` once per `ModuleData` and zeroes the
  counter, so the scratch is always zero between walks.

The executed byte is the right test: `giveSelfUpgrade` (`0x00855388`) calls `upgradeImplementation`
and then `setUpgradeExecuted(1)` (`0x005B462D`, writing interface `+0x04`). `isAlreadyUpgraded` is
`0x004986C4`, which reads the same byte. A removed upgrade clears it, which the stock module never
handled.

Both gates skip the walk entirely until some module has declared the keyword (a flag byte that the
parser sets in the cave). A mod that never uses it pays nothing at recharge time.

## 4. What it does not cover

- **`SharedSyncedTimer` powers.** `0x006AD1B0` is left stock: a targeted module does nothing for
  them. Its arithmetic (`cmp`/`sbb`/`and` on an unsigned product at `0x006AD219`) also looks wrong
  for a negative float in stock, which is a separate question.
- **Tooltips.** `description-timers` transcribes the stock formula to print a cooldown. With both
  patches installed, a button's printed time leaves out a targeted discount.
- **`recharge-rescale`** (experimental) also transcribes the formula and anchors the 27 bytes at
  `0x00896EBA`, so the two patches refuse to be applied together.

## 5. Composition

Checked by applying each registered patch that builds with default arguments to the stock binary,
alone and on top of this one, in both orders: every one still applies and verifies, except
`recharge-rescale` (above).

## 6. To check in a game

1. A targeted module on a building, naming one spellbook power: cast it and a second flagged power.
   Only the named one comes back faster, and the second keeps any stock discount.
2. Build a second and third copy: the named power's cooldown follows `Percentage` level 2 and 3.
   Lose one: the next cast uses the lower level.
3. Save with a targeted module active, load, cast: the discount is still there.
4. Name a power on a hero's `WeaponModeSpecialPowerUpdate` (flavour 2): it is discounted.
5. A typo in the list stops the load with the error message above.
6. Watch for a hitch on a cast with many objects. The walk is two passes over the caster's owner's
   objects and their modules, once per recharge start (and once per power on a `CurseSpecialPower`
   victim).
