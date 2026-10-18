# Production refund on death

When a producer dies, the engine cancels its whole production queue and refunds every entry. This
write-up covers where that happens, how a death differs from the other three ways a queue gets
cancelled with a refund, and what `production-death-no-refund` changes.

Status: **static-verified**, and emulated over the real `game.dat` with the engine's own loss
path (`tests/sage_patch/test_production_death_no_refund_emulated.py`). Not yet seen in a running
game.

## The refund

`ProductionUpdateInterface` (vtable `0x00C67DB0`, at `ProductionUpdate+0x20`) has two cancels that
pay back, and a cancel-all that drives them:

| slot | VA | what |
|---|---|---|
| 4 (`+0x10`) | `0x008A1140` | `cancelUpgrade(upgradeTemplate)` |
| 10 (`+0x28`) | `0x008A13EE` | `cancelUnitCreate(productionID)`: units (kind 1) and hero revives (kind 3) |
| 15 (`+0x3C`) | `0x008A05B2` | `cancelAndRefundAllProduction` |
| 16 (`+0x40`) | `0x008A1666` | loss of the producer: cancel-all, then release a held `RespawnUpdate` object |

Cancel-all raises `+0xFD` (cancel the head whatever its id or progress) and cancels the head entry
until the queue is empty:

```
008a05b5  mov byte [esi+0xfd], 1
008a05be  mov eax, [esi+8]            ; head entry
008a05c1  mov ecx, [eax+4]            ; kind: 1 and 3 -> slot 10, 2 -> slot 4
008a05d4  call [edx+0x28]             ; cancelUnitCreate(entry+0x10)
008a05ed  call [edx+0x10]             ; cancelUpgrade(entry+0xc)
008a05dd  mov byte [esi+0xfd], 0
```

Each cancel deposits the amount the entry paid (`entry+0x28`) into the owner's `Money`
(`Player+0x90`) through `MONEY_DEPOSIT` (`0x007B18B8`):

```
; cancelUpgrade
008a1189  mov eax, [ebp+8]            ; the owner
008a118c  push 1
008a118e  lea ecx, [eax+0x3dc]
008a1194  push ecx
008a1195  push [esi+0x28]             ; paid
008a1198  lea ecx, [eax+0x90]
008a119e  call MONEY_DEPOSIT
008a11a3  push esi                    ; remove the entry, delete it, release a player upgrade

; cancelUnitCreate
008a1443  cmp byte [ebp-1], 0         ; finished and waiting at the door: no refund
008a1447  mov edi, eax                ; the owner
008a1449  jne 0x8a1476
008a145d  call MONEY_DEPOSIT          ; paid, as above
008a1471  call 0x79dfc2               ; owner+0x3dc tally, by -paid
008a1476  cmp [esi+4], 3              ; a revive: release its record (Player+0x758)
```

## Four ways in

Slot 15 is reached four ways. Only one is a death:

| site | path | refund after the patch |
|---|---|---|
| `0x008A05A7` | `onDie`, through slot 16 | **no** |
| `0x0069974D` | owner change (capture), through slot 16 | yes |
| `0x007967E3` | selling (`BuildAssistant`), directly | yes |
| `0x0079481B` | the sell list's final step, directly | yes (the queue is already empty) |
| `0x0087661B`, `0x0087662E` | replacing an object with another template, directly | yes |
| `0x00856D80` | the construction-cancel path, directly | yes |

The sites marked "directly" were found by walking every caller of `getProductionUpdateInterface`
(`0x0068C327`) for a following `call [reg+0x3C]`. The two slot-16 callers were found the same
way with `+0x40`.

`ProductionUpdate` has no die module of its own. It implements `DieModuleInterface` as a third
base at `+0x24`, whose vtable (`0x00C67DA8`) has one slot, `0x008A05A7`:

```
008a05a7  add ecx, -4                 ; +0x24 -> the interface at +0x20
008a05aa  mov eax, [ecx]
008a05ac  call [eax+0x40]             ; slot 16
008a05af  ret 4
```

The constructors at `0x008A182D` / `0x008A19B7` write that vtable into `+0x24`. Nothing else
references `0x008A05A7`, so the vtable slot is the only way a death reaches it.

Slot 16 is shared with capture, so a death can't be told apart there or anywhere below it. The
thunk is the only place that can.

## The patch

`production-death-no-refund` adds a `.pdnoref` section holding a one-byte flag and three routines:

- **`on_die`** becomes the `onDie` vtable target. It raises the flag, calls the stock thunk with
  the same `this` and argument, and lowers the flag.
- **`upgrade_gate`** takes over `0x008A1189`, the first five bytes of `cancelUpgrade`'s refund
  (before any of the deposit's pushes). With the flag down it replays them and resumes at
  `0x008A118E`. With it up it jumps to `0x008A11A3`, past the deposit.
- **`unit_gate`** takes over the eight bytes of `cancelUnitCreate`'s own refund gate at
  `0x008A1443`. It keeps the stock `[ebp-1]` test first, then skips to `0x008A1476` when the
  flag is up. That skips the deposit and the tally together, so the tally still matches what was
  actually spent.

Everything after the skipped run still executes. Entries are removed and deleted, a revive
record is released (the hero can be recruited again), and a player upgrade leaves its
in-production state. Game logic is single-threaded and the cancel-all is synchronous, so a
global flag can't leak into another producer's cancel. The emulated test checks that a sale
right after a death still refunds.

## What is not covered

- A producer **removed without dying** (destroyed by script, or replaced through
  `ReplaceSelf`-style paths that call the destructor) never refunded. Its destructor at
  `0x008A198B` deletes the entries without a deposit, before and after the patch. For `ReplaceSelfUpgrade` and
  `SummonReplacementSpecialAbilityUpdate`, `replacement-transfer`'s `PRODUCTION` flag moves the
  queue to the replacement instead.
- The `+0x3DC` object that `MONEY_DEPOSIT` and `0x0079DFC2` both receive is taken to be the
  owner's money/score tally. It isn't named here. It just isn't touched on death.
- Not yet seen in a running game. The cheap test: queue a unit, an upgrade and a hero in one
  building, note the money, kill the building with a cheat or a script, and check the money
  hasn't moved. Then sell another building with a queue, and check it still refunds.
