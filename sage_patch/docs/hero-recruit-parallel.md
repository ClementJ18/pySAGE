# Hero recruitment blocks the queue behind it — reverse-engineering notes

The RE behind [`patches/hero_recruit_parallel.py`](../patches/hero_recruit_parallel.py). ROTWK
`game.dat` build `2.01.2614.37001`, ImageBase `0x400000`, recovered statically 2026-08-22.

## The report

> When a hero starts recruiting it will do so in parallel to the existing queue. However anything
> queued after that will be blocked by the hero.

Both halves are real, and they are the same mechanism seen from two sides.

## TL;DR

- A `ProductionUpdate` holds **one** queue — units, upgrades and hero revives in a single
  doubly-linked list, appended at the tail (`0x008A0C99`). Insertion order is queue order.
- `ProductionUpdate::update` advances **exactly one entry per frame**: the one
  `PRODUCTION_UPDATE_PICK_ENTRY` (`0x008A072F`) returns. Every arm of `update` ends at the single
  exit `0x008A2F0E`; no second entry is ever looked at.
- A revive's completion is **not** the queue's progress. `queueCreateUnit` calls
  `REVIVE_MGR_START` (`0x007812B2`), which stamps the **current logic frame** into the hero's
  roster record at `+0xA8`, and the entry is finished when
  `(now − start) / totalFrames >= 1.0` (`REVIVE_MGR_PROGRESS`, `0x00780C9F`). That clock runs on
  the game frame whatever the queue is doing.
- So a hero **behind** other entries still finishes on time: the picker's third rule scans the
  whole list for a revive whose clock has already elapsed and returns it out of order. That is
  the parallelism.
- And a hero **ahead** of other entries blocks them: once everything in front of it drains, the
  revive entry is the head, the picker's **last** rule returns the head unconditionally, the
  completion test fails (`0x008A1F56`, `jb` to the exit) and `update` returns. Nothing behind it
  moves until the hero's clock elapses.
- The patch is seven bytes and one cave: the last rule returns the first **non-revive** entry,
  falling back to the head only when the queue is all revives. A ready revive is still caught by
  the third rule, one rule earlier, so nothing is lost.

## 1. One queue, appended at the tail

`ProductionUpdate`'s layout is recovered in
[`production-model-condition.md`](production-model-condition.md) §5. The three fields this write-up
needs:

| offset | what |
|---|---|
| `module+0x08` | `Object *` — the producer |
| `module+0x20` | the `ProductionInterface` subobject (vtable `0x00C67DB0`) |
| `module+0x28` | **queue head**, or NULL |
| `module+0x2C` | **queue tail**, or NULL |
| `module+0x34` | entry count |

and, of the `0x54`-byte `ProductionEntry`:

| offset | what |
|---|---|
| `+0x04` | **kind**: 1 = unit, 2 = upgrade, **3 = revive** |
| `+0x08` | `ThingTemplate *` — for a revive, resolved from the revive index at queue time |
| `+0x0C` | `UpgradeTemplate *` (kind 2) |
| `+0x10` | the revive index / the production id |
| `+0x14`, `+0x18` | percent complete, percent per frame — display state |
| `+0x1C` | accrued progress |
| `+0x20`, `+0x24` | batch size, batch produced so far |
| `+0x48`, `+0x4C` | next, previous |

Insertion is unconditional append (`0x008A0C99`), the same for all three kinds:

```asm
008a0c99  push ebp / mov ebp,esp ...
008a0ca5  cmp  dword [esi+0x28], 0       ; head
008a0ca9  jne  0x8a0cae
008a0cab  mov  dword [esi+0x28], eax     ; first entry: it is the head
008a0cae  mov  ecx, [esi+0x2c]           ; tail
008a0cb1  test ecx, ecx
008a0cb3  je   0x8a0cbe
008a0cb5  mov  dword [ecx+0x48], eax     ; old tail -> new entry
008a0cb8  mov  ecx, [esi+0x2c]
008a0cbb  mov  dword [eax+0x4c], ecx     ; new entry -> old tail
008a0cbe  inc  dword [esi+0x34]
008a0cc1  mov  dword [esi+0x2c], eax     ; new tail
```

**Queue order is press order.** There is no priority slot, no second list, and nothing anywhere
that moves an entry once it is linked.

## 2. One entry per frame

`ProductionUpdate::update` (`0x008A1B9F`) asks which entry to work on exactly once, near the top,
and keeps the answer in `ebx` for the rest of the function:

```asm
008a1bfb  lea  ebx, [esi-0x10]           ; the module base (esi is the UpdateModule subobject)
008a1c0e  mov  ecx, ebx
008a1c10  call 0x8a0669                  ; PRODUCTION_UPDATE_REVIVE_COMMAND_POINT_DELAY
008a1c15  mov  ecx, ebx
008a1c17  call 0x8a072f                  ; PRODUCTION_UPDATE_PICK_ENTRY
008a1c1c  mov  ecx, edi
008a1c1e  mov  ebx, eax                  ; <- the one entry this frame will advance
...
008a1ddd  test ebx, ebx
008a1ddf  je   0x8a2f0e                  ; nothing to do
```

`0x008A072F` has exactly one caller. Everything after `0x008A1DDD` — the command-point stall, the
progress accrual at `0x008A1EBC`, the completion test, the spawn — reads `ebx` and only `ebx`, and
every arm ends at `0x008A2F0E`, the function's single exit block. **A frame that advances one
entry advances no other**, and the ordering of the queue is therefore the whole of the scheduling
policy.

## 3. The picker's four rules

`PRODUCTION_UPDATE_PICK_ENTRY` is three walks of the same list, tried in order, with a fallback.
`esi` is the module base throughout; `[esi+0x20]` is the interface subobject, whose vtable slot
`+0x58` is `getNextProduction` (`0x008A1904`, literally `entry ? entry->+0x48 : NULL`).

**Rule A — a batch already in progress** (`0x008A0732`):

```asm
008a0732  mov  eax, [esi+0x28]           ; head
008a0735  jmp  0x8a0750
008a0737  mov  ecx, [eax+0x20]           ; batch size
008a073a  mov  edx, ecx
008a073c  sub  edx, [eax+0x24]           ; minus produced so far
008a073f  cmp  ecx, edx
008a0741  jne  0x8a07da                  ; produced != 0 -> return this entry
008a0747  lea  ecx, [esi+0x20]           ; next
```

The first entry that has already produced at least one of its batch keeps the frame, so a
five-unit order is not interleaved with anything else once it starts.

**Rule B — a builder** (`0x008A0754`): the first entry of kind 1 or 3 (`0x00729661`) whose
template carries KindOf **`DOZER`** — `test byte [tmpl+0x109], 0x40`, and `ThingTemplate+0x108` is
the `KindOf` mask ([`herobar-kindof.md`](herobar-kindof.md) §, field entry `0x00DA4148`).

**Rule C — a revive whose clock has elapsed** (`0x008A0780`):

```asm
008a078a  cmp  dword [ebx+4], 3          ; a revive?
008a078e  jne  0x8a07c6                  ; no: next entry
008a0790  mov  ecx, [esi+8]              ; the producer Object
008a0793  call 0x68b678                  ; ->getControllingPlayer()
008a0798  mov  ecx, [ebx+8]              ; the hero's ThingTemplate
008a079d  mov  eax, [ebx+0x10]           ; the revive index
008a07a3  add  edi, 0x758                ; Player+0x758: the revive manager
008a07ac  call 0x78131e                  ; -> the roster record's index
008a07b7  call 0x780c9f                  ; -> progress, as a fraction of 1.0
008a07bc  fld1 / fxch / fcompi / fstp
008a07c4  jae  0x8a07dc                  ; progress >= 1.0 -> return this entry
```

**Rule D — otherwise the head** (`0x008A07D5`), which is where the report's second half lives:

```asm
008a07d1  test ebx, ebx
008a07d3  jne  0x8a078a                  ; rule C's loop
008a07d5  mov  eax, [esi+0x28]           ; the head, whatever it is
008a07d8  pop ebx / pop edi / pop esi / ret
```

## 4. A revive's clock is not the queue's

`Player+0x758` is the revive manager: a vector of `0xE8`-byte roster records at `+0x04`..`+0x08`,
one per `BuildableHeroesMP` entry ([`hero-recruitment.md`](hero-recruitment.md) §2 is the index
space). Three of its methods matter.

`REVIVE_MGR_START` (`0x007812B2`), called from `queueCreateUnit` at `0x008A1371` — **before** the
entry is linked into the queue:

```asm
007812e1  cmp  dword [ecx], -1           ; ecx = &record->+0xa8; -1 = not recruiting
007812e4  movss [eax+0xdc], xmm0
007812ec  jne  0x781317                  ; already recruiting -> refuse
007812ee  mov  edx, [0xde412c]           ; TheGameLogic
007812f4  mov  edx, [edx+0x40]           ; ->frame
007812f7  mov  [eax+0xb4], esi
00781303  mov  [ecx], edx                ; record->+0xa8 = the frame it was queued on
```

`REVIVE_MGR_PROGRESS` (`0x00780C9F`), which both rule C and the completion test call:

```asm
00780cb9  cmp  dword [esi+0xa8], -1
00780cc0  je   0x780cb1                  ; not recruiting -> 0.0
00780cca  call 0x780687                  ; total frames = buildTime * the producer's modifier
00780cd6  mov  eax, [0xde412c]
00780cdb  mov  eax, [eax+0x40]           ; TheGameLogic->frame
00780ce3  fild  [ebp+0x0c]
00780cee  fisub [esi+0xa8]               ;   now - start
00780cf4  fidiv [ebp+8]                  ; ( now - start ) / total
```

and `0x00780C64`, the cancel, which puts `+0xA8` back to `-1`.

**The numerator is the logic frame.** Nothing about the queue enters it. The one thing that
touches it is `PRODUCTION_UPDATE_REVIVE_COMMAND_POINT_DELAY` (`0x008A0669`), which walks the whole
queue every tick and increments `+0xA8` for each revive the player cannot afford in command
points — pushing the start frame forward, and with it the completion, for as long as the cap
holds. That routine is not the picker and does not care where in the queue an entry sits.

So a revive entry is a **token**: it holds the hero's place, carries the refund and the command-point
stall, and is the thing the completion path deletes — but its timing lives on the player.

## 5. The two halves of the report

`update` reaches the completion test with the selected entry in `ebx`, and branches on kind
(`0x008A1EF3`):

| kind | test | at |
|---|---|---|
| 1, 2 | `entry+0x14` (percent) >= 100.0 | `0x008A1F6B` `comiss` / `jb` exit |
| **3** | `REVIVE_MGR_PROGRESS` >= 1.0 | `0x008A1F4C` `fcompi` / `jb` exit |

**Parallel, for what was queued first.** Queue `[UnitA, Hero]`. Rules A–C do not fire while the
hero's clock is short of 1.0, so rule D returns `UnitA` and `UnitA` builds. The hero's clock ran
from the frame it was queued regardless. The moment it reaches 1.0, **rule C** finds it by
scanning the whole list, returns it out of order, and it completes — `UnitA` losing exactly one
frame of progress. That is the observed parallelism, and it is real: the hero's revive time is
never extended by anything ahead of it.

**Blocked, for what is queued after.** Queue `[Hero, UnitC]`, or `[UnitA, Hero, UnitC]` after
`UnitA` completes and is unlinked. Rule A: no batch in progress. Rule B: a hero is not a `DOZER`.
Rule C: the clock has not elapsed, or the hero would already be gone. **Rule D returns the head,
which is the hero**, `update` runs the command-point stall and the progress accrual on it, reaches
`0x008A1F56`, sees progress < 1.0 and returns. `UnitC` is never looked at. It stays frozen for the
whole remaining revive time, and its own displayed percent stays where it was.

The asymmetry is entirely rule C versus rule D: **a revive can jump the queue to finish, but a
revive at the head still owns the frame while it waits.**

## 6. The patch

Rule D is the only site that needs to change, and it needs one word added to it: return the first
entry that is **not** a revive.

That is sufficient *and* complete, in that order:

- **Sufficient**, because a revive that is genuinely ready is returned by rule C, which runs
  first and scans the entire list. Rule D never has to return a revive for a hero to complete.
- **Complete**, because selecting a not-yet-ready revive accomplishes nothing that is lost by
  skipping it. `update`'s three effects on such an entry are the command-point stall, the progress
  accrual into `entry+0x1C`, and the completion test. The accrual and the test are dead for a
  revive — completion reads the player's clock — and the stall is separately and more thoroughly
  done for *every* revive in the queue by `0x008A0669` at the top of the same tick.
- **The all-revive case keeps the stock answer.** When the queue holds nothing but revives the
  fallback still returns the head, so nothing about a queue of heroes changes.

Seven bytes are displaced at `PRODUCTION_UPDATE_PICK_FALLBACK` (`0x008A07D1`) — rule C's loop
condition and the first byte of the fallback load — for a `jmp rel32` into a cave. Nothing in the
image branches into `0x008A07D2`..`0x008A07D7`; `0x008A07D1` is itself a branch target
(`0x008A0784`) and is preserved as the cave's entry. The cave:

```asm
        test ebx, ebx
        je   fallback
        jmp  0x008a078a                  ; rule C's loop body, unchanged
fallback:
        mov  eax, [esi+0x28]             ; the head
        test eax, eax
        je   done
scan:   cmp  dword [eax+0x04], 3         ; a revive?
        jne  done                        ; no -> this one gets the frame
        mov  eax, [eax+0x48]             ; next
        test eax, eax
        jne  scan
        mov  eax, [esi+0x28]             ; all revives -> the head, exactly as stock
done:   jmp  0x008a07d8                  ; pop ebx / pop edi / pop esi / ret
```

`eax` is the only register written, and it is the return value. `esi` — the module base — is read
and left alone; `ebx`, `edi` and `esi` are all restored by the pops the cave jumps to, so their
live values at the hook are dead by definition.

The raw `+0x48` walk is what `getNextProduction` does (`0x008A1904` is `entry ? entry->+0x48 :
NULL`), so no vtable call is needed and the NULL case is handled by the `test`/`jne` pair.

## 7. What this does not change

- **Nothing about revive timing.** The clock is armed at `queueCreateUnit` and read from the game
  frame; the patch does not touch either. A hero recruited into an empty queue finishes on exactly
  the frame it does today.
- **Nothing about the command-point stall.** `0x008A0669` still delays every unaffordable revive
  in the queue, and a *ready* revive short of command points is still selected by rule C, still
  hits `PRODUCTION_UPDATE_COMMAND_POINT_STALL` and still plays the EVA cue.
- **Nothing about ordering among non-revives.** Rules A and B are untouched, and the fallback
  returns the first non-revive entry — which, in a queue with no revives in it, is the head.
- **The displayed percent of a waiting hero.** `entry+0x14` is written only for the selected
  entry, so today a hero queued *behind* other entries — the parallel case that already works —
  never has it written either. Whatever draws a recruiting hero's progress is therefore already
  not reading it, and the patch makes the head case behave like the behind case.

**Every peer must run the same patched binary.** Which entry advances is logic state feeding the
per-frame CRC, so a patched and an unpatched client diverge the first frame a hero sits at the head
of a non-empty queue, and replays do not cross.

## 8. What is still open

- **Not runtime-verified.** Every claim here is read out of the machine code, and the tests are
  written from the same reading. The cheap check is a building with a hero and one unit queued
  behind it: stock, the unit's bar does not move until the hero pops; patched, both advance.
- **What draws the recruiting hero's timer has not been disassembled.** §7 argues from
  `entry+0x14` being unwritten in the already-parallel case that the control bar reads the
  player-side record instead, which is consistent but is not the same as having read the drawing
  code.
- **Rule B's `DOZER` priority is described, not explored.** It is stated here because it precedes
  rule C and can therefore delay a ready hero by a frame, which is stock behaviour the patch keeps.
- **The AI's view is unexamined.** The picker is reached only from `update`, so the AI's producer
  choice ([`ai-construction-gate.md`](ai-construction-gate.md)) is upstream of all of this, but
  whether an AI that queues a hero then stalls its own barracks has ever mattered is unknown.
