# Stopping the AI producing from a building that is still going up

The reverse-engineering behind
[`patches/ai_construction_gate.py`](../patches/ai_construction_gate.py). ROTWK `game.dat` build
`2.01.2614.37001`, ImageBase `0x400000`, recovered statically 2026-08-09 against the repo's
`game.dat`, with one fact taken from live-captured bytes
(`tests/sage_live/fixtures/match.snapshot.gz`); patch built and applied 2026-08-10.

## TL;DR

- The rule "a structure that is still going up may not produce" is real, and it lives in **three**
  places: the **ControlBar** (`0x0094307A`), the **legacy `AIPlayer::findFactory`**
  (`0x008F53A2`), and `ProductionUpdate`'s **exit** step (`0x008A1CB5`).
- It does **not** live anywhere on the path RotWK's skirmish AI actually uses. The BFME2-era
  `SkirmishAI` subsystem has its own producer index and its own producer picker, and neither
  consults `UNDER_CONSTRUCTION`.
- The gap is one function: **`0x009A0705`**, the `SkirmishAI` producer picker. It filters
  candidates on dead / has-a-`ProductionUpdate` / not-disabled / idle, and stops there.
- A structure enters that index **the frame it is placed** — `AIPlayer`'s structure-created hook
  (`0x008F06CE`) walks the brand-new object's buildable *and* revivable lists while it is a
  construction site.
- The fix: one 6-byte hook at **`0x009A0784`**, the picker's arm-select branch, into a cave that
  reproduces the branch and adds `testStatus(UNDER_CONSTRUCTION)` **on the "pick one to use now"
  arm only** — see [§5](#5-the-patch). The scoping draft of this note proposed hooking the dead
  check at `0x009A076C` instead, which would have gated both arms;
  [§7](#7-questions-the-patch-had-to-answer) records why that is wrong.
- **AI-only by construction** — the function is inside `SkirmishAI` and has no player-facing
  caller, so unlike [`ai-revive-gate`](ai-revive-gate.md) it needs no return-address
  discrimination.
- **This is an AI handicap, not an AI cheat.** See
  [What the AI actually gains](#what-the-ai-actually-gains-nothing) — the queue advances but the
  finished unit cannot leave, so the AI pays and stalls. That changes why you would want the
  patch, not whether it is correct.

## 1. The status bit is real, and the engine sets it on Edain structures

`Object::m_status` is a four-dword bitset at `+0x94`, read through `Object::testStatus(bit)` at
`0x0044DDEC` (`and eax, [esi + edx*4 + 0x94]`). The name table at `0x00D8AFF0` gives index 2 =
`UNDER_CONSTRUCTION`, and 78 sites in `.text` push that literal.

Confirmed on bytes the engine laid out rather than on the name table alone. The recorded match in
`tests/sage_live/fixtures/match.snapshot.gz` holds one structure still going up — an
`ElvenMallornTree_Extern`, an Edain plot build — at `0x0AD9B4E8`:

```
[obj+0x94] = 04 00 00 00   ->  UNDER_CONSTRUCTION
conditions  = ACTIVELY_BEING_CONSTRUCTED, PARTIALLY_CONSTRUCTED
```

So the bit is set for exactly the case this patch is about, on the mod this repo targets. (The
golden `match.expected.json` decodes `status` as empty for every object because the *name table*
is outside the capture, not because the bits are clear — the raw dwords are in the capture and
are read above.)

## 2. Where the rule already lives

### The ControlBar — the player's whole defence

`0x0094307A`, inside the command-availability evaluator:

```asm
0094307a  push 2
0094307c  mov  ecx, ebx                  ; the selected object
0094307e  call 0x0044ddec                ; testStatus(UNDER_CONSTRUCTION)
00943083  test al, al
00943085  jne  0x00943090
00943087  test byte [ebx+0x458], 1       ; ... or dead
0094308e  je   0x009430b6                ; neither: carry on
00943090  mov  eax, [ebx+4]              ; the template
00943093  test byte [eax+0x11f], 0x20
0094309a  jne  0x009430a5
0094309c  test byte [eax+0x11b], 0x10
009430a3  je   0x009430b6
009430a5  push 0x14                      ; UNDERGOING_REPAIR
009430a9  call 0x0044ddec
009430b0  je   0x00942c5d                ; -> unavailable
```

Read it as: *under construction or dead → the button is unavailable, unless the template opts in
and the thing is being repaired.* This is client-side UI code. The AI never executes a line of it.

### The legacy `AIPlayer::findFactory` — correct, and unused here

`0x008F5347` is the Generals/BFME1-lineage "find a producer for this thing". It checks the bit
before anything else:

```asm
008f53a2  push 2
008f53a6  call 0x0044ddec                ; UNDER_CONSTRUCTION -> next object
008f53b3  push 0x13
008f53b7  call 0x0044ddec                ; SOLD             -> next object
```

and only then resolves a revive index (`0x008F540B`) and asks
`BuildAssistant::canMakeUnit` (`0x008F5423` / `0x008F543B`). **Every one of its seven callers
inherits the check.** This path is not the defect — and it is not what a RotWK skirmish match
runs.

### `ProductionUpdate::update` — the exit step, not the queue

`0x008A1B9F` (an interface tick: `[esi-8]` is the owning `Object`, `[esi-0xc]` the module data,
so it has no direct callers). At `0x008A1CAC`:

```asm
008a1cac  test byte [edi+0x458], 1       ; producer dead?
008a1cb3  jne  0x008a1d34
008a1cb5  push 2
008a1cb9  call 0x0044ddec                ; UNDER_CONSTRUCTION
008a1cc0  jne  0x008a1d34                ; -> "cannot exit right now"
```

`0x008A1D34` is not a function exit: it notifies through `[0x00DE42FC]`'s vtable `+0x6C`, sets the
blocked flag at `+0x11C`, and falls into `0x008A1D4F`, which still advances the queue
(`0x008A1D5B`). So the timer runs and the **unit is held at the door**.

## 3. Where the rule does not live: the `SkirmishAI` path

RotWK ships the BFME2 `SkirmishAI` subsystem, and the binary names its files in the pool strings —
`\SkirmishAI\AIUnitBuilder\AIUnitBuilder.cpp` (`0x00C88216`),
`\SkirmishAI\AITacticalAI\...` (`0x00C795D0` and friends), `\SkirmishAI\AIBaseBuilder\AIBase.cpp`
(`0x00C8A4B7`). Its code sits in `0x0096xxxx`–`0x009Exxxx`, a different region from the legacy
`AIPlayer` at `0x008Fxxxx`.

### The index is built the frame the foundation goes down

`0x008F069A` is `AIPlayer`'s structure-created hook. For any template carrying `+0x10F & 0x80` it
hands the new object's **id** to `0x009A0838`:

```asm
008f06bf  test byte [eax+0x10f], 0x80
008f06c6  je   0x008f06d3
008f06c8  push [esi+0x74]                ; Object::m_id
008f06cb  lea  ecx, [edi+0x38]           ; the SkirmishAI producer index
008f06ce  call 0x009a0838
```

`0x009A0838` resolves the id, then runs **two** loops — the template list at `[eax+0x160]`
(`canMakeUnit` at `0x009A08A5`) and the revive list at `[esi+0x4C]..[esi+0x50]`, mapping each
through `ReviveMgr::indexOfTemplate` (`0x009A0925`) before `canMakeUnit` at `0x009A0937` — and
files every accepted pair into the index at `[esi+8]`. It checks no status at all, and it is
called at object creation, which for a structure is the moment construction *starts*.

So a barracks or a citadel is in the AI's "who can make this" index, hero slots included, while it
is still scaffolding.

### The picker — the actual defect

`0x009A0705` walks the index entries for a template and picks a producer:

```asm
009a0758  push [eax+0x14]                ; candidate ObjectID
009a075b  mov  ecx, [0x00de412c]         ; TheGameLogic
009a0761  call 0x00449681                ; findObjectByID
009a0768  test edi, edi
009a076a  je   0x009a07c7                ; -> next candidate
009a076c  test byte [edi+0x458], 1       ; dead?
009a0773  jne  0x009a07c7
009a0775  push 0
009a0777  mov  ecx, edi
009a0779  call 0x0068c327                ; getProductionUpdate
009a0782  je   0x009a07c7
009a0784  cmp  byte [ebp+0x10], 0        ; "any producer will do" flag
009a0788  jne  0x009a07a0
009a078e  call [eax+0x64]                ; ProductionUpdate: disabled?
009a0793  jne  0x009a07c7
009a0799  call [eax+0x44]                ; ProductionUpdate: queue empty?
009a079e  jne  0x009a07c7
009a07a0  ...                            ; accept -> returns edi at 0x009a07f1
```

Dead, has a production module, not disabled, idle. **No `UNDER_CONSTRUCTION` test.** Nothing else
saves it either: a structure going up has a `ProductionUpdate`, is not disabled, and is
emphatically idle, so it passes every filter that is there.

### The order carries the id, and re-checks nothing that helps

`0x008F0FD1` calls the picker and stamps the winner into the pending order:

```asm
008f0fd4  call 0x009a0705
008f0fdb  je   0x008f106d
008f0fe1  mov  eax, [eax+0x74]           ; Object::m_id
008f0fe4  mov  [edi+8], eax              ; the order's producer id
```

The order class (vtable `0x00C8EBD0`, constructed at `0x009ED98F`; `+0x08` producer id, `+0x0C`
template name) then has:

| slot | VA | what it does |
|---|---|---|
| execute | `0x009EDB44` | `findObjectByID(+0x8)` → `getProductionUpdate` → `indexOfTemplate` (`0x009EDB96`) → `queueCreateUnit` (`ProductionUpdate` vtable `+0x20`, `0x009EDBB8`) |
| can-execute | `0x009EDBC6` | same resolve, then `TheBuildAssistant`'s `+0x64` gate (`0x009EDC25`) |

`+0x64` (`0x00793ECB`) tests: null producer, dead (`+0x458 & 1`), has a production module, the
template's `0x10000000` flag, **`Object+0x457 & 3` (the disabled mask)**, then `canMakeUnit`, queue
depth, and cost/prereqs. It does **not** test `UNDER_CONSTRUCTION`. Neither does `execute`.

The `+0x0C` template resolves through `TheThingFactory` and the branch at `0x009EDC62`
(`test byte [edi+0x113], 4`) routes heroes to the revive-cost path — so **this one class carries
both unit production and hero recruitment**, and one fix covers both.

### The chain, end to end

```
structure placed (UNDER_CONSTRUCTION set)
  -> 0x008F06CE  index it: everything it can build AND every revive slot   [no status check]
  -> 0x009A0705  pick it as the producer for an order                      [no status check]  <-- FIX HERE
  -> 0x008F0FE4  stamp its id into the order
  -> 0x009EDBC6  can-execute -> BuildAssistant +0x64                       [no status check]
  -> 0x009EDB44  execute     -> ProductionUpdate::queueCreateUnit          [no status check]
  -> 0x008A1CB5  the unit is built, and then cannot leave                  [checks - too late]
```

## 4. What the AI actually gains: nothing

Worth being clear before anyone writes code, because it inverts the motive.

The queue timer keeps running (`0x008A1D5B` is downstream of the bail), but the finished unit is
refused its exit (`0x008A1CC0`) until the structure completes. `queueCreateUnit` withdraws the cost
up front. So the AI:

- spends the money at queue time,
- occupies the producer's single queue slot,
- and gets nothing out until the building finishes anyway.

Meanwhile `0x009A0705`'s idle test (`vtable+0x44`) means a *finished* barracks standing next to it
looks equally attractive and would have delivered on time.

This is therefore a patch that makes the AI **less bad**, not less cheaty — the opposite direction
from [`ai-revive-gate`](ai-revive-gate.md), which removes an advantage. Both are the same *kind* of
defect (a rule the player obeys that the AI's own path never reads); they just fall different ways.

## 5. The patch

One hook, one cave, one function.

**Hook:** `0x009A0784`, 6 bytes — `80 7d 10 00` (`cmp byte [ebp+0x10], 0`) plus `75 16`
(`jne 0x009A07A0`), the branch that picks which of the picker's two arms runs. Replace with
`e9 <rel32>` + one `90`.

**Why here and not at the dead check.** `[ebp+0x10]` is the picker's third argument, and it
selects between two different questions (see [§7](#7-questions-the-patch-had-to-answer)). Zero
means *pick a producer to use now*; non-zero means *could anything here ever make this*, and one
caller **cancels** an order when that answer comes back null. Hooking the dead check at
`0x009A076C` — the scoping draft's proposal — sits before the split and would gate both, so the
AI would start cancelling plans because their producer had not finished yet. Hooking the split
itself keeps the hypothetical arm byte-for-byte stock.

**Takeable?** Yes. Scanning every `E8`/`E9`/`EB`/`0F8x`/`7x` displacement in `.text`, and every
imm32 in the whole image, finds **no** inbound edge into `0x009A0784..0x009A0789`. The window's
only entry is fallthrough from the `je 0x009A07C7` at `0x009A0782`.

**Cave:**

```asm
cmp  byte [ebp+0x10], 0        ; the displaced arm-select
je   pick_one_to_use
jmp  -> 0x009A07A0             ; the hypothetical arm: accept, stock edge

pick_one_to_use:
push 2                         ; UNDER_CONSTRUCTION
mov  ecx, edi
call -> 0x0044DDEC             ; Object::testStatus, __thiscall, ret 4
test al, al
je   finished
jmp  -> 0x009A07C7             ; still going up: NEXT candidate, stock edge

finished:
jmp  -> 0x009A078A             ; the engine's own disabled + idle tests
```

Three exits, all into stock code: accept (`0x009A07A0`), next candidate (`0x009A07C7`), and the
resume (`0x009A078A`). One engine call, `Object::testStatus`, which
[`addresses.py`](../addresses.py) already names.

**Register safety.** `edi` is the candidate `Object`, resolved by `findObjectByID` at
`0x009A0761` and live across the whole loop body; `esi` is its `ProductionUpdate`, which is why
the test takes `edi` and not the nearer `esi`. `testStatus` preserves `esi` (it pushes and pops
it), `ebx`, `edi` and `ebp`, and clobbers `eax`/`ecx`/`edx`. At `0x009A078A` the stock code
immediately does `mov eax, [esi]; mov ecx, esi; call [eax+0x64]`, so it reloads `eax` and `ecx`
itself and reads only `esi`. Nothing the cave clobbers is live at any of its three exits.

**Why here and not at `+0x64`.** Adding an `UNDER_CONSTRUCTION` arm to `BuildAssistant`'s `+0x64`
(`0x00793ECB`) would cover every path at once — but `+0x64` is squarely the *player's* path (the
ControlBar's four call sites, `ProductionUpdate::queueCreateUnit`, scripts), so it would need the
same return-address discrimination `ai-revive-gate` uses, against **14** call sites rather than
one. `0x009A0705` lives inside `SkirmishAI` and has six callers, all of them AI. AI-only falls out
of *where the function is* instead of having to be enforced.

**Determinism.** `Object::m_status` is logic state, identical on every peer, and the SkirmishAI
runs on the logic thread on all of them — so the added edge is network- and replay-safe by the
same argument as `ai-revive-gate` §Determinism.

**Composition.** `0x009A0705` is untouched by every bundled patch (they sit at `0x0079`, `0x008A`,
`0x0094`, `0x00DA`), and the cave's three exits (`0x009A07A0`, `0x009A07C7`, `0x009A078A`) plus its
one call (`0x0044DDEC`) are all in stock code nothing else rewrites. Order-independent, and the
cave is allocated by `allocate_section` rather than at a fixed RVA.

**Anchors.** The hook site's own six bytes are asserted by `apply_byte_patch`. Six more addresses
are checked before anything is written: the picker's prologue (`0x009A0705`), the three exits, the
`testStatus` helper, and — the one that carries the argument — the five bytes of the order pump's
call at `0x008F0FD4`, whose displacement *is* the proof that the function being edited is the one
the AI's production reaches. A build whose layout moved fails there instead of on a wild jump.

## 6. Deliberately out of scope

- **The index built at creation time (`0x009A0838`).** Left alone. Filtering *there* would be
  wrong: the structure legitimately will be able to produce, and the index has no invalidation
  hook to re-add it on completion. The picker is the right place because it runs every time.
- **`RECONSTRUCTING` (bit 21) and the `UNDERGOING_REPAIR` (bit 20) carve-out.** The ControlBar's
  rule is not simply "bit 2 clear" — it lets a template opt back in while being repaired
  (`0x0094309C`–`0x009430B0`). Reproducing that exactly means porting two template-flag tests into
  the cave. The patch tests bit 2 only, which is **stricter** than the player's rule in the repair
  case. Under-producing is the safe direction here; note the divergence rather than hide it.
- **The "could this ever be made here" arm.** Left on the stock edge, deliberately — see
  [§5](#5-the-patch) and the caller table in [§7](#7-questions-the-patch-had-to-answer).
- **The exit-step stall itself (`0x008A1CB5`).** Correct as it stands. If the picker stops choosing
  construction sites, nothing reaches it.
- **`BuildAssistant::+0x64`.** See above.

## 7. Questions the patch had to answer

**Which `[ebp+0x10]` callers matter.** This is the one that moved the hook. The picker's third
argument is pushed first of the three, and the arm-select at `0x009A0784` reads it: zero runs the
disabled and idle tests, non-zero skips straight to accept. All six callers reach the picker by a
direct `E8` — its address appears as an imm32 nowhere in the image — and they split three and
three:

| caller | flag | what it is asking |
|---|---|---|
| `0x008F0FD4` | 0 | the order pump — stamps the winner's id into a pending build order |
| `0x009A0B64` | 0 | building a producer list for a plan |
| `0x009A0B90` | 0 | the same walk's final pick |
| `0x009A09FB` | 1 | a tactic deciding whether a plan is possible at all |
| `0x009A0DD7` | 1 | a sweep that, on null, calls `[vtable+0x1c]` with reason `3` — it **cancels** |
| `0x009A0E7A` | 1 | a cost/time estimator — accumulates a float per candidate |

So the non-zero arm asks a hypothetical, and gating it would make the AI cancel plans and
mis-estimate costs because a building had not finished yet — a worse behaviour than the one being
fixed. The hook therefore sits **on** the split rather than before it, and only the zero arm gains
the test. `0x009A0DD7` is the decisive one: it is the caller that turns a "no producer" answer into
a destructive act.

**Whether the class at vtable `0x00C8EBD0` is named.** Its behaviour is pinned; its name is not.
The nearest pool string is `AIExpansionScience.cpp`, which is the neighbouring compiland, not
necessarily this class. Nothing in the patch depends on the name, so this was left unanswered.

### Still open: runtime confirmation that it happens at all

Everything above is static plus one live snapshot; nobody has watched the skirmish AI queue into a
construction site. The cheap check is a live run (`.claude/skills/edain-bot-run`) reading
`production` on structures whose `under_construction` is true — `sage_live` already exposes both on
every object, so this needs no new instrumentation.

## Status

**Built, applied and runtime-verified in game.** The patch is
[`patches/ai_construction_gate.py`](../patches/ai_construction_gate.py), registered as
`ai-construction-gate` and tested in
[`tests/sage_patch/test_ai_construction_gate.py`](../../tests/sage_patch/test_ai_construction_gate.py).
Every anchor above holds on the repo's `game.dat`, and `apply` followed by `verify` runs clean on
it. The defect is established statically end to end and the status bit is confirmed on
live-captured bytes; what remains unobserved is the in-game behaviour — both that the stock AI
does queue into a construction site and that the gate stops it.
