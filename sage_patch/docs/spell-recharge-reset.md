# Clearing the spellbook discount at level 0

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000`.

**Verdict:** a stock `SpellRechargeModifierUpgrade` never takes its discount away. When the
player's last counting module is deleted or captured, the level drops to 0 and the discount is set
to the module's **first** `Percentage`. `spell-recharge-reset` writes `0.0` instead at level 0 and
leaves every other level stock.

- **Cost:** two 5-byte `call` hooks and a 58-byte cave (`.sprrst`). No INI change.
- **Risk:** low. The cave reads and writes the same two `Player` fields the stock routines use,
  and jumps to points the stock code reaches at the same stack depth.
- **Status:** built ([`patches/special_powers/spell_recharge_reset.py`](../patches/special_powers/spell_recharge_reset.py)).
  The stock bodies run under unicorn, stock and patched, in
  `tests/sage_patch/test_spell_recharge_reset.py`. **Runtime-verified for `onDelete`**
  (2026-10-28): Edain-Mod's `tests/test_angmar_sorcery_tower_recharge.py` sells two towers of
  sorcery one at a time. Stock reads level 0 with -0.2, patched level 0 with 0.0. `onCapture` is
  checked only under emulation.

## 1. The example

Edain's Angmar tower of sorcery spawns `AngmarHexerturmSBReloaderObject`, which carries
`Percentage = -20% -40% -60%`. One tower makes the spellbook recharge 20% faster, two make it 40%
faster. Losing one of two steps back to -20%. Losing the last one leaves -20% for the rest of the
match. Edain's Mordor tribute camps, Rohan's Drúedain statues and Imladris's scriptorium avoid it
with a leading `Percentage = 0%`. That makes level 0 harmless, but the first building then gives
nothing.

## 2. The stock routines

See [`spell-recharge-targets.md`](spell-recharge-targets.md) §1 for the module. The per-player
state is the level `Player+0x71C` and the discount `Player+0x718`. Each routine moves the level,
reads it back, and writes `Percentage[clamp(level - 1, 0, size - 1)]`:

```
008ba004  call 0x6aaae7            ; onDelete: Player+0x71C--
008ba009  mov  ecx, edi
008ba00b  call 0x6aaad9            ; eax = level            <- hooked
008ba014  dec  eax
008ba018  test eax, eax / jg       ; index = max(level - 1, 0)
...
008ba04c  fld  [Percentage + index*4]
008ba055  call 0x6aaaee            ; Player+0x718 = that
008ba05a  pop esi / pop edi / leave / ret
```

`onCapture` (`0x008BA05E`) runs the same sequence for the old owner (`0x008BA073`..`0x008BA0C4`,
level read at `0x008BA07A`) and then the increment for the new owner from `0x008BA0C9`. The
clamp at level 0 picks index 0, which is the bug. There is no other writer of `+0x718` that could
clear it later.

## 3. The patch

Both level reads become a `call` into the cave, with `ecx` still the player:

| site | stock | at level 0, resumes at |
|---|---|---|
| `0x008BA00B` (`onDelete`) | `call 0x6aaad9` | `0x008BA05A`, the epilogue |
| `0x008BA07A` (`onCapture`, old owner) | `call 0x6aaad9` | `0x008BA0C9`, the new owner's half |

```
mov  eax, [ecx+0x71C]
test eax, eax
jle  zero
ret                        ; level > 0: the stock code carries on
zero:
mov  dword [ecx+0x718], 0
add  esp, 4                ; drop the return address
jmp  <resume>
```

At both sites the stack holds nothing between the call and its resume point beyond the return
address. The single `push` before `0x6aaaee` is popped by that function's `ret 4`. A level below 0
is cleared too. Stock clamps it to index 0 the same way, and only a mismatched decrement could
produce one.

## 4. Composition

`spell-recharge-targets` hooks the prologues of the same routines and returns early for a module
that declares `AffectedSpecialPowers`. Those modules never reach these sites, and stock ones do.
The test applies the two in both orders and verifies both. `recharge-rescale` and
`description-timers` read `+0x718` and simply see `0.0`.

## 5. To check in a game

1. Build one tower of sorcery (or any single-module source), then lose it: a spellbook power cast
   afterwards recharges at full length.
2. Two towers, lose one: the discount steps down to the first level, as stock does.
3. A signal fire captured by another player: the old owner's discount clears when it was their
   only module.
