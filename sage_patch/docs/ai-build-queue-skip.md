# Skipping an AI build order that has no builder

The reverse-engineering behind
[`patches/ai_build_queue_skip.py`](../patches/ai_build_queue_skip.py). ROTWK `game.dat` build
`2.01.2614.37001`, ImageBase `0x400000`, recovered statically 2026-10-12, with the symptom and the
queue contents read live the same day from an Edain skirmish with a Brutal Imladris AI.

## TL;DR

- The skirmish AI holds every build order - farms, structures, upgrades, units, heroes - in one
  vector sorted by priority, and `AIPlayer`'s order pump (`0x008F0FB8`) walks it from the front
  each tick, starting the first order that can start.
- An order answers the pump with a code. **8 means "I have no builder I can use"**, and the pump
  then **ends the walk** if the AI's pool of free builders is not empty.
- A farm order has a fixed priority of 2000. A unit order's priority is capped at
  `1800 + 300 * (1 - command points used / cap)`, which passes 2000 only below a third of the cap.
- So an AI whose farm orders cannot start, and whose pool holds any builder, recruits only when
  its army is under a third of its command points - however much money it has.
- The fix is two bytes at **`0x008F1032`**: the `ja` that ends the walk becomes `nop`s, and the
  order takes the pump's ordinary "not this one, next" path.

## 1. The symptom

A Brutal Imladris AI holding the whole map, at frame 28,000-31,000 of a skirmish:

- bank 340,000-410,000 and rising, command points oscillating between about 420 and 860 of 1500;
- every barracks idle while command points fell from 860 to 420, then eight battalions queued in
  the same few seconds, then idle again;
- the Gondor AI in the same match recruiting continuously.

The AI's own queue, read from the running game in dispatch order
(`tools/live/ai_build_queue.py` in pySAGE-edain), with 828 of 1500 command points in use:

```
economy   ImladrisEconomyVariants_AI                 st=0 pri=2000        x6
unit      BruchtalLichtbringerFeuerHorde             st=0 pri=150 cur=1934
unit      BruchtalLanzerLastAllianceHorde            st=0 pri=150 cur=1934
...                                                  (seven unit orders)
structure ImladrisBarracksFreeBuild                  st=0 pri=1725
...
```

Nothing in it starts. The six farm orders sit at the head across every sample, and the free
builder pool holds two objects, `ImladrisDunedainOutpost2` and `DunedainCampKeep`. Gondor's pool is
empty.

## 2. The order pump

`0x008F0F8F`..`0x008F1104`, with `esi` the `AIPlayer` and the queue at `+0x130`..`+0x134`:

```asm
008f0f8f  mov  ecx, [esi+0x144]      ; the free builder pool, a list
008f0f95  and  dword [ebp-8], 0
          ...                        ; [ebp-8] = how many builders it holds
008f0fb8  mov  edi, [ebx]            ; the next order
          ...                        ; give it a producer or a builder, if it wants one
008f1020  call 0x00961975            ; can this order start now?
008f1025  test eax, eax
008f1027  je   0x008f1073            ; 0: start it, and stop for this tick
008f1029  cmp  eax, 8
008f102c  jne  0x008f1034
008f102e  cmp  dword [ebp-8], 0
008f1032  ja   0x008f1073            ; 8 and a builder in the pool: end the walk
008f1034  cmp  eax, 2
008f1037  je   0x008f1073            ; 2: end the walk
          ...                        ; 9 or 10: cancel the order
008f1056  add  ebx, 4                ; anything else: next order
```

`0x008F1073` with a non-zero answer does nothing but leave the loop. `0x00961975` calls the
order's own vtable slot `+0x40`, wrapped in a deposit and a withdrawal for an order flagged at
`+0x21`.

The pool is the list `0x009A1BC0` removes a builder from when an order is handed to it, and
`0x009A23A4` prunes of dead objects each tick.

## 3. Where 8 comes from

A farm order is the class with vtable `0x00C88090`. Its slot `+0x40`, `0x0097DFCD`, cancels the
order (9) when more than two matching objects already stand near the site, and otherwise asks
`0x0097DC99`:

```asm
0097dcaa  push dword [esi+8]         ; the order's builder id
0097dcad  call 0x00449681            ; findObjectByID
0097dcb4  test ebx, ebx
0097dcb6  je   0x0097dd61            ; no builder
          ...
0097dcc4  call dword [eax+0x1b8]     ; the builder's AI: can it take this?
0097dccc  je   0x0097dd61            ; no
          ...
0097dd61  push 8
0097dd63  pop  eax
```

In the live queue every farm order has builder id 0 between ticks: the pump clears the id of an
order it did not start (`0x008F103F`).

## 4. Why units get through at all

`0x009EDA30` recomputes a unit order's priority each tick from the `ArmyDefinition`:

```
ratio    = command points used / cap
priority = max(base + (MustUseCommandPointPercentage[phase] - ratio)
                      * LowUnitPriorityModifier[phase], DefaultUnitPriority)
priority = min(priority, 1800 + 300 * (1 - ratio))
```

The cap is the full one, bonuses included (`0x006A7B9F`). The ceiling passes a farm order's 2000
only when `ratio < 1/3`, which is the 500 of 1500 the live game recruits below.

## 5. The patch

`0x008F1032`, `77 3f`, becomes `90 90`. Answer 8 then falls to `cmp eax, 2` like any answer the
pump has no special case for: the builder id it was lent is cleared and the walk moves on.

Anchors: the can-start call at `0x008F1020` (its displacement proves the answer tested is that
helper's) and the nine bytes of the test at `0x008F1029`, which the removed branch follows.

Answer 2 still ends the walk, so an order the AI cannot afford is still saved for.

## 6. What changes in a game

- Units, upgrades and structures behind an order that has no builder start in priority order,
  one per tick, as they do for an AI whose builder pool is empty.
- A structure order waiting for a busy builder no longer reserves the queue for itself. Orders
  behind it can spend money first; it is still ahead of them the tick a builder is free.
- An AI with an empty pool behaves as before.

## 7. Open questions

- Why the six `ImladrisEconomyVariants_AI` orders cannot start. No plot left is the obvious guess
  for an AI holding the whole map; not traced.
- Why `ImladrisDunedainOutpost2` and `DunedainCampKeep` are in the builder pool and whether they
  can serve any order. Both are `CASTLE_KEEP DOZER_FACTORY`.
- Whether other factions with outposts stall the same way.

## 8. Status

Static only, with the symptom and the queue read live. Not yet run in a game with the patch -
`runtime_verified` stays empty until it has been.
