# A command-point price on a button — reverse-engineering notes

The RE behind [`patches/command_point_cost.py`](../patches/command_point_cost.py). ROTWK
`game.dat` build `2.01.2614.37001`, ImageBase `0x400000`, recovered statically 2026-08-19 from
[`sage_mods/edain/patching/engine/game.dat.backup`](../../sage_mods/edain/patching/engine/game.dat.backup).

## The report

> Add a field called `CommandPointCost` to a button which disables the button if there is not at
> least that many free command points. This is for special powers and upgrades that summon things.

## TL;DR

- Command points gate **recruitment and nothing else**. The cost is a `ThingTemplate` field
  (`+0x628`), read by `hasEnoughCommandPoints` (`0x006A7F79`) from inside the production gate. A
  special power that summons a battalion never touches that path, so it fires at 1500/1500.
- The ControlBar has exactly **one** routine that answers "is this button usable":
  `ControlBar::getCommandAvailability` (`0x00942733`), `stdcall`, `ret 0x14`, seven callers plus one
  recursive self-call. Everything that draws a button and everything that executes a click goes
  through it.
- It **already has a verdict for this**: **7**, pushed at `0x00942F47` when the production gate
  answers "not enough command points". Verdict 7 greys the button and turns a click into
  `GUI:ErrorNoMoreCommandPoints` (`0xC8028C`). So the patch does not invent a refusal — it reuses
  the number the engine reserves for exactly this sentence.
- The check goes at the **top** of the evaluator, not at its exit, and §4 is why: `edi` is reloaded
  eleven times inside the function and `[ebp+8]` is reused as scratch by four of the command cases,
  so by the time a verdict exists the button is unrecoverable.
- The field lives at `CommandButton+0x10E`, the aligned word of the same three-byte alignment hole
  `queue-ignore-cp` takes a byte out of, parsed by the engine's own `INI::parseUnsignedShort`.
  `sizeof` stays `0x2E0`.

## 1. Why `CommandPoints` is inert on a summon

`ThingTemplate+0x628` is the unit's command-point cost, and there is one predicate that reads it:

```asm
006a7f79  push ebx
006a7f7a  mov  ebx, [esp+8]              ; the ThingTemplate
006a7f7f  mov  edi, [ebx+0x628]          ; what->CommandPoints
006a7f85  test edi, edi
006a7f87  je   0x6a7fa3                  ; costs nothing -> TRUE
006a7f8a  mov  esi, [ecx+8]              ; command points in use   (Player+0x68)
006a7f8d  call 0x6a7b9f                  ; getCommandPointCap()
006a7f92  add  esi, edi
006a7f94  cmp  esi, eax
006a7f96  setle al                       ; inUse + cost <= cap
006a7f99  test byte [ebx+0x11a], 0x80    ; ... or KindOf ARMY_OF_DEAD
006a7fa1  je   0x6a7fa5
006a7fa3  mov  al, 1
```

`ecx` is `Player+0x60`, the command-point subobject. Its callers are the production gate
(`0x0079402B`, the site [`queue-ignore-cp`](queue-ignore-cp.md) takes) and the AI's own production
choices — all of them reached by *queueing a unit*.

**A summon queues nothing.** `ObjectCreationList`, `SpawnBehavior`, an `OCLSpecialPower`, a
`DoCommandUpgrade` that grants a spawn — every one of them creates finished objects. The accounting
still happens (the created unit adds its `CommandPoints` to `Player+0x68` at `0x006A7FDA`), so the
army *counts* against the cap; what never happens is the check that would have refused it. Usage
therefore climbs past the cap and stays there — which is why a live reading can show `1531/1500`
and why "points free" is better read as "stop ordering" than as a quantity.

So the request is not "make the summon cost points" — it already does, after the fact. It is
"**refuse the button while the points are not there**", which is a UI-side rule and has to be
written where the UI decides.

### `getCommandPointCap` (`0x006A7B9F`)

```asm
006a7b9f  push ecx                       ; a local slot, NOT a saved ecx
006a7ba0  push ebx / push esi
006a7ba2  mov  esi, ecx                  ; Player+0x60
006a7ba4  mov  ebx, [esi+0xc]            ; the CPObject bonus      (Player+0x6C)
006a7ba7  mov  ecx, [0xde4928]           ; ThePlayerList
006a7bad  add  ebx, [esi+4]              ; + the base              (Player+0x64)
006a7bb1  push [esi+0x14]
006a7bb4  call 0x6a844e
006a7bb9  mov  edi, [esi+0x20]           ; a filtered vector, [+0x20, +0x24)
006a7bbf  mov  [esp+0xc], eax            ; <-- overwrites the pushed ecx
          … each element that passes 0x762977 / 0x6abd0b adds [edi] to ebx …
006a7bf2  mov  esi, [esi+0x10]           ; the hard cap            (Player+0x70)
006a7bf5  cmp  ebx, esi
006a7bf7  cmovg ebx, esi                 ; min(base + bonus + terms, hard cap)
006a7bfc  mov  eax, ebx
```

Two things the patch depends on. It is a **min, not a sum**, so reading `Player+0x64` or even
`+0x64 + 0x6C` gives the wrong number and the field would disagree with the engine — calling the
routine is the only honest way to ask. And `mov [esp+0xc], eax` writes over the slot the entry
`push ecx` created, so **`ecx` is not preserved**: the cave carries its running total across the
call on the stack, not in a register.

`ebx`, `esi`, `edi` and `ebp` *are* preserved.

## 2. The one availability evaluator

`ControlBar::getCommandAvailability` at **`0x00942733`**. `stdcall`, five arguments
(`ret 0x14`), SEH-framed, `sub esp, 0x5c`. Seven callers:

| caller | what it is | how it reads the answer |
|---|---|---|
| `0x0071CCB0` | the radial / palantir button draw | 1,2 → `winEnable(1)`; 6,7 → `winEnable(0)` + `0x1000000`; 0,4,8 → `winEnable(0)` + `0x80000000`; **3 → `winHide(1)`** |
| `0x00931370` | a second draw path | 3 → skip; 5 → keep the cached float |
| `0x009405B3` | the click executor, **multi-select arm** | 1,2 → do the command; 7 → the error message; 6 → a second flag |
| `0x00940625` | the click executor, single arm | the same four |
| `0x009428B5` | **itself**, for a toggle button's partner | maps 3→3 and everything else→0 |
| `0x00943ADB` | the command-bar context update | 0,3,4 handled apart |
| `0x009449D6` | window-status maintenance | pushes four status bits |

The verdict space is 0..8, and the two that mean **usable** are **1** and **2** — both click paths
test exactly those. Note that **3 is not "greyed", it is hidden** (`0x0071CD1B` calls `0x0071552B`,
which sets `0x10` = `WIN_STATUS_HIDDEN`), which is worth knowing because 3 is what almost every
internal refusal answers and it is *not* the verdict this patch wants.

### The exits

There is exactly **one** `ret 0x14` in the whole function, at `0x00942C6E`. Every path funnels
through the tail:

```asm
00942c5d  6a03                 push 3
00942c5f  58                   pop  eax            ; <- the shared "take the pushed code" edge
00942c60  5f                   pop  edi
00942c61  5b                   pop  ebx
00942c62  8b4df4               mov  ecx, [ebp-0xc]
00942c65  5e                   pop  esi
00942c66  64890d00000000       mov  fs:[0], ecx
00942c6d  c9                   leave
00942c6e  c21400               ret  0x14
```

`0x00942C5F` is the engine's own idiom for "answer with this code": `push <n>` / `jmp 0x942c5f`,
used at `0x009437E0` (2), `0x00942F2C` (4), `0x00942F47` (7), `0x0094311C` (6), `0x009431A6` (8),
`0x00943245` (5). The patch's refusal is one more of those, byte for byte.

## 3. Verdict 7 is already "not enough command points"

`0x00942F33`, inside the `UNIT_BUILD` case, asks the same `BuildAssistant` gate a real production
does and translates its codes:

```asm
00942f33  mov  ecx, [0xde8200]           ; TheBuildAssistant
00942f3b  push edi / push 0 / push ebx
00942f3f  call [eax+0x64]                ; isPossibleToMakeUnit(producer, what, reviveIndex)
00942f42  cmp  eax, 7                    ; 7 = not enough command points
00942f45  jne  0x942f4e
00942f47  6a07                 push 7
00942f49  e911fdffff           jmp  0x942c5f
00942f4e  cmp  eax, 6                    ; the per-type build limit
00942f51  je   0x9438c8                  ;   -> 0
00942f57  cmp  eax, 5                    ; parking places full
00942f5a  je   0x9438c8                  ;   -> 0
```

The gate's code space is the one [`queue-ignore-cp`](queue-ignore-cp.md) §2 derives, and **7 is its
command-point refusal**. So the ControlBar verdict 7 *is* "not enough command points", and both
consumers already do the right thing with it:

- `0x0071CCB0` greys the button (`winEnable(0)`) and sets status bit `0x1000000`, the same
  treatment "cannot afford" gets — **not** the hidden treatment 3 gets.
- `0x009405B3` / `0x00940625` route a click to `0x009405F1`, which formats the string at
  `0xC8028C` — `"GUI:ErrorNoMoreCommandPoints"` — appends it through `TheInGameUI`'s vtable `+0x48`,
  and drops floating text of type `0xC` at the object's position (`[ebx+0x38]`).

That is the entire user-visible behaviour the report asks for, already written, reachable by
answering with one number.

## 4. Why the check cannot go at the exit

The obvious hook is the shared tail: read the verdict in `eax`, and if it is 1 or 2, ask the field.
It does not work, for a reason that is only visible by looking for writes rather than reads.

**`edi` holds the button — for the first 0x28F bytes of the function.** It is loaded at
`0x00942775` and then reloaded eleven times:

```
00942775  mov edi, [ebp+8]        <- the button
00942a04  lea edi, [ebp-0x68]     <- a local buffer
00942a21  mov edi, [ebp+8]           (reloaded)
00942d23  mov edi, eax
00942da1  mov edi, [esi]
00942e09  mov edi, [esi]
00942ef7  mov edi, [edi+0xc0]
00943028  mov edi, [edi+0x24]
009430ff  mov edi, [edi+0x24]
009431cb  mov edi, eax
00943664  mov edi, [edi+0x1c]
```

**And the argument slot is not a fallback**, because the function writes to it too:

```
00942f7e  fst   dword [ebp+8]     <- an x87 temporary
00943369  mov   [ebp+8], ecx
00943470  mov   [ebp+8], eax
009434b4  mov   [ebp+8], ecx
```

So at `0x00942C60` neither the register nor the stack slot holds the `CommandButton` any more.
Stashing it in the cave at entry does not save it either: the function calls **itself** at
`0x009428B5` for a toggle button's partner, so a single global would be the inner call's button by
the time the outer call reached the tail.

The check therefore goes at the **top**, where both are still what the caller passed — and nothing
is lost by answering early, because every refusal the evaluator would have reached on its own
answers **3**, and it answers 3 whether it is reached or not. Short-circuiting can only convert an
otherwise-usable button, which is the whole feature.

### The window

```asm
0094275c  push esi
0094275d  e8d760d6ff           call 0x6a8839            ; ThePlayerList::getLocalPlayer
00942762  mov  ecx, eax
00942764  test ecx, ecx
00942766  894df0               mov  [ebp-0x10], ecx     ; <- the player, for the rest of the frame
00942769  jne  0x942773
0094276b  push 3 / pop eax / jmp 0x942c62               ; no player: hidden, and no ebx/edi pushed
00942773  53                   push ebx
00942774  57                   push edi
00942775  8b7d08               mov  edi, [ebp+8]        ; ] the six bytes displaced
00942778  8b4714               mov  eax, [edi+0x14]     ; ]  (button, then its GUI command)
0094277b  cmp  eax, 0x20
```

Six bytes, two whole instructions, no branch anywhere in `.text` landing inside them (checked by
sweeping every `jcc`/`jmp`/`call` immediate in the section). `ebx` and `edi` have just been pushed,
so the tail's `pop edi` / `pop ebx` still balance — and a `push 7` / `jmp 0x942c5f` from here leaves
the stack in exactly the shape `0x00942C5F` expects, because the engine's own refusals at
`0x0094279A` and `0x009427A8` jump to `0x00942C5D` from this same depth, three instructions later.

### ⚠ `ecx` is live across the window, and it does not look it

This is the one that got the first version of the patch wrong, so it is worth stating plainly.
`mov ecx, eax` at `0x00942762` leaves the local player in `ecx`, and **nothing between there and
`0x0094278C` writes it** — including the two instructions displaced here, which touch only `edi`
and `eax`. Six bytes past the resume point, `ecx` is consumed:

```asm
0094277b  cmp  eax, 0x20
0094277e  je   0x94278c
00942780  cmp  eax, 0x26
00942783  jne  0x942795
00942785  e86ea9d6ff           call 0x6ad0f8        ; __thiscall(ecx = the Player)
0094278a  eb05                 jmp  0x942791
0094278c  e848a9d6ff           call 0x6ad0d9        ; __thiscall(ecx = the Player)
```

```asm
006ad0f8  push ebp / mov ebp,esp / push ecx / push ecx / push esi
006ad0fe  8bf1                 mov  esi, ecx
006ad100  83be1007000000       cmp  dword [esi+0x710], 0     ; <- faults on a null this
```

An implicit `this` carried across two unrelated instructions is invisible in the window itself: the
six bytes being replaced neither set `ecx` nor read it, so nothing about them says it matters. It
shows up only by reading forward past the resume point for the *next* use of every register, which
is the check that has to be made at any hook and is not the same check as "which registers does
this window write".

**A cave that clobbers `ecx` therefore crashes** — `0xC0000005` reading `0x710`, at `0x006AD100`,
for any button whose `Command` is `0x20` or `0x26` — and only for those, which is why it survives
a great deal of play before it is seen.

So the cave saves **every** register rather than the ones it noticed. `pushad` / `popad` are one
byte each, neither touches `EFLAGS` — which is what lets the verdict leave the guarded region in
the flags — and the routine runs once per button per ControlBar refresh, where the cost of eight
pushes is not measurable. Being wrong about a live register is the one mistake here that
assembles, applies, verifies and then crashes in play; `pushad` makes it unrepresentable rather
than merely checked.

`[ebp-0x10]` is the player whose command bar is being evaluated —
`ThePlayerList->getLocalPlayer()` at `0x006A8839`, which returns `[ThePlayerList+0x10]` or, under
`0x006AAC52`, the observed player. It is filled unconditionally, and the one path that leaves it
NULL is the one that returns before the hook. The cave tests it anyway; four bytes against a null
dereference is not a trade worth thinking about.

## 5. Where the field lives

`CommandButton` is `0x2E0` bytes, allocated in exactly two places — `ControlBar::newCommandButton`
(`0x0071C446`) and `0x00720563` — both `push 0x2e0` / `operator new` / `call 0x0075D516`. The field
table at `0x00C2BAC8` has 55 rows and the highest, `CreateAHeroUICostIfSelected`, is an `Int` at
`+0x2DC` — so the struct is packed to its last byte and **growing it would mean two allocation
edits and a constructor hook**.

It does not have to grow. Sorting the table by offset leaves one genuine hole:

```
  0x108  RequireLevel                      Int   -> ends 0x10C
  0x10C  AutoAbility                       Bool  -> ends 0x10D
    ---- 0x10D .. 0x110 : three bytes, named by nothing
  0x110  AffectsKindOf                     KindOfFlags (0x1C bytes)
```

Nothing in the table names `+0x10D`..`+0x10F`, the constructor never writes them, and the
`memset(this+0x110, 0, 0x1C)` at `0x0075D721` starts past them. `queue-ignore-cp` already takes
`+0x10D` for a `Bool`; **`+0x10E` is the aligned word above it**, and the two do not overlap.

An `UnsignedShort` is the right shape for it. `INI::parseUnsignedShort` (`0x0042EC11`) is stock:

```asm
0042ec24  call 0x42e9d7                  ; scan the token as an int
0042ec29  test eax, eax
0042ec2b  jl   0x42ec3c
0042ec2d  cmp  eax, 0xffff
0042ec32  jg   0x42ec3c                  ; -> "value out of range, expected 0..65535" (0xBD42B8)
0042ec34  mov  ecx, [ebp+0x10]           ; the store pointer
0042ec37  668901               mov  word [ecx], ax
```

`0..65535` against a hard command-point cap of **1500** is not a range anyone can reach, and the
word store is what lets the field live in two bytes of padding — the same trick `INI_PARSE_BOOL`'s
byte store does for `queue-ignore-cp`'s one.

### The default

`operator new` does not zero the block, so an uninitialised `+0x10E` would give every button in the
game a random cost and most of them would be unpressable. `queue-ignore-cp` solves its byte by
widening the constructor's `AutoAbility` store from `mov byte` to `mov dword` — six bytes for six —
but that instruction is *taken*, and sharing it would make the two patches order-dependent.

The instruction **before** it is free:

```asm
0075d682  899e08010000         mov  dword [esi+0x108], ebx      ; RequireLevel = 0
0075d688  889e0c010000         mov  byte  [esi+0x10c], bl       ; AutoAbility = No  (queue-ignore-cp's)
```

Six bytes, one whole instruction, no branch target inside it, and `ebx` is the zero the whole
constructor stores from (`xor ebx, ebx` at `0x0075D52A`). Displacing it into the cave gives room to
reproduce it and then write an explicit zero word at `+0x10E`. The two patches then touch
**different instructions in the same constructor**, and either order works.

The constructor has three callers — `0x005DA7CB` (the INI block parser's override path),
`0x0071C461` and `0x0072057B` (the two allocations) — so hooking it covers every `CommandButton`
that can exist, which hooking either allocation site would not.

## 6. The patch

```asm
ctor:                                    ; in place of 0x0075D682
    mov   dword [esi+0x108], ebx         ; the displaced store
    mov   word  [esi+0x10E], 0
    jmp   0x0075D688

gate:                                    ; in place of 0x00942775
    mov   edi, [ebp+8]                   ; the CommandButton      (displaced #1)
    pushad                               ; ecx is live; see §4. save all eight, cost 1 byte
    movzx eax, word [edi+0x10E]          ; its CommandPointCost
    test  eax, eax
    je    stock                          ; no cost declared
    mov   edx, [ebp-0x10]                ; the player this bar belongs to
    test  edx, edx
    je    stock
    add   edx, 0x60                      ; &Player::m_commandPoints
    add   eax, [edx+8]                   ; + the points already in use
    push  eax                            ; getCommandPointCap answers in eax, clobbers ecx
    mov   ecx, edx
    call  0x006A7B9F
    pop   edx
    cmp   edx, eax                       ; the comparison hasEnoughCommandPoints makes
    jg    refuse
stock:
    popad                                ; POPAD does not touch EFLAGS, so the verdict survives
    mov   eax, [edi+0x14]                ; the displaced #2
    jmp   0x0094277B
refuse:
    popad
    push  7                              ; GUI:ErrorNoMoreCommandPoints
    jmp   0x00942C5F
```

`pushad` runs *after* the displaced load, so `popad` restores `edi` as the `CommandButton` the
`stock` path then reads `+0x14` from. Both exits `popad` exactly once, and the `push`/`pop` pair
inside the guarded region balances, so the stack depth at `0x00942C5F` is the one its pops expect.

Plus the field-table rebuild — the 55 live rows copied verbatim into the cave, one appended
`{keyword, INI::parseUnsignedShort, 0, 0x10E}` row, the terminator, and the three references at
`0x005DA706` / `0x005DA7B6` / `0x005DA7D0` repointed. That is the same three-reference move
`queue-ignore-cp` makes, and the table is resolved from those references rather than from the stock
constant, so whichever patch runs second copies the first's row across.

## 7. What it does not do

- **It does not charge anything.** No points are deducted, reserved, or held. The units the power
  summons still add their own `CommandPoints` to `Player+0x68` when they exist, exactly as before.
- **It does not gate the power.** The evaluator is client-side UI. A script action, an
  `AISpecialPowerUpdate` tick, or anything else that reaches `doSpecialPower*` without going
  through a command button is unaffected. The field is a *requirement on pressing the button*, in
  the way `RequireLevel` is.
- **It does not change what the cap means.** `IgnoreCommandPointLimit`, `ARMY_OF_DEAD`, the
  `CPObject` bonus and the 1500 clamp all behave as they did.
- **The AI does not see it.** The AI's special-power evaluation asks
  `SpecialPowerStore::canUseSpecialPower` (`0x007B1D79`), not the ControlBar, so an AI player will
  fire a power a human's button would be greyed for. Closing that would mean a logic-side gate and
  a different patch.

## 8. Determinism

Nothing written is logic-side state and nothing read is state a peer can disagree about: the
evaluator runs on the client, over the local player's own bar, and its answer decides whether an
*order is created* rather than what an order does. An unpatched peer would simply let its own
player press a button this one greys, which is a difference in what the two players can do, not a
divergence in the simulation.

What *is* fatal on a stock build is the keyword: SAGE treats an unknown field in a known block as a
parse error, so a mod using `CommandPointCost` ships the patched `game.dat` or does not run.

## 9. Verification list

Held statically by [`tests/sage_patch/test_command_point_cost.py`](../../tests/sage_patch/test_command_point_cost.py):

- `+0x10E..+0x10F` is claimed by no row of the stock field table, is word-aligned, ends at or
  before `AffectsKindOf`, and is disjoint from `queue-ignore-cp`'s `+0x10D`;
- `operator new(0x2E0)` is anchored and still holds `0x2E0` after `apply`;
- the `ctor` routine reproduces the displaced store *before* it zeroes the field, and never names
  `+0x10D`;
- the `gate` routine's `push`/`pop` around `getCommandPointCap` balance, its fall-through emits the
  displaced load byte for byte, and its refusal edge is `push 7` / `jmp 0x00942C5F`;
- `7` is read back out of the anchored `0x00942F42` window rather than asserted as a literal;
- the pair with `queue-ignore-cp` applies **and verifies** in either order, and the two share no
  byte outside the PE header and the three table references they both repoint.

Against the real binary: all 43 non-experimental patches apply together and every one verifies.
