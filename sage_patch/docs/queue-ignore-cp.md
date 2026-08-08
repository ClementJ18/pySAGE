# Queuing past the command-point cap — reverse-engineering notes

The RE behind [`patches/queue_ignore_cp.py`](../patches/queue_ignore_cp.py). ROTWK `game.dat`
build `2.01.2614.37001`, ImageBase `0x400000`, recovered statically 2026-08-08.

## The report

> I have a power that triggers recruitment of a unit through a `DoCommandUpgrade`. Without enough
> command points this fails, wasting the power. I want a `CommandButton` field, `QueueIgnoreCP`,
> that always lets these units be queued but only lets the queue progress when there is enough CP.

## TL;DR

- A `DoCommandUpgrade` presses a real `CommandButton` through `Object::doCommandButton`
  (`0x00696FD2`), the same dispatcher a player's click goes through.
- The `UNIT_BUILD` and `REVIVE` cases both end in `ProductionUpdate::queueCreateUnit`, whose very
  first act is `TheBuildAssistant->vt[0x64](producer, what, reviveIndex)` (`0x00793ECB`). That
  gate's **last** refusal is the command-point cap, and it answers **7**. `queueCreateUnit`
  returns FALSE, and the press is gone — the upgrade has already been granted and nothing will
  press the button again.
- **The second half of the request is already in the engine.** `ProductionUpdate::update` refuses
  to advance a head entry whose template the player cannot afford in command points
  (`0x008A1E27`), and a parallel routine (`0x008A0669`) pushes a revive's completion frame out by
  one frame per tick while the cap holds. A unit that gets into the queue therefore *already*
  waits for command points. Only the door into the queue is shut.
- So the patch is one field and one verdict. `CommandButton+0x10D` — alignment padding — holds a
  new `Bool`; the two `queueCreateUnit` call sites are wrapped so that the pressed button's answer
  reaches a dword in the cave for exactly the length of the call; and the gate's command-point
  verdict consults that dword before it pushes 7.

## 1. How an upgrade presses a button

`DoCommandUpgrade` has two halves, `0x008B8E2E` for the grant and `0x008B8DFC` for the removal,
and they are the same six instructions with a different `ModuleData` offset:

```asm
008b8e2e  push esi
008b8e2f  mov  esi, [ecx-8]              ; the Object
008b8e36  mov  eax, [ecx-0xc]            ; the ModuleData
008b8e3d  mov  ecx, [0xde7744]           ; TheControlBar
008b8e43  add  eax, 0x138                ; &GetUpgradeCommandButtonName   (+0x13C for Remove)
008b8e48  push eax
008b8e49  call 0x71d6ea                  ; ControlBar::findCommandButton(AsciiString&)
008b8e4e  test eax, eax
008b8e50  je   0x8b8e5e
008b8e52  push 0 / push 0 / push eax
008b8e57  mov  ecx, esi
008b8e59  call 0x696fd2                  ; Object::doCommandButton(btn, 0, 0)
```

That is the whole reason a `CommandButton` field can carry engine-side behaviour here: the button
the upgrade names is a real, fully parsed `CommandButton`, and the press goes through the ordinary
dispatcher rather than through some private production path.

### `Object::doCommandButton` (`0x00696FD2`)

`btn` is `[ebp+8]` and is never written, so it is readable at every point in the function. The
switch at `0x00697086` reads `btn->Command` (`CommandButton+0x14`) and, of its cases, exactly two
reach production:

| `Command` | value | case | ends in |
|---|---|---|---|
| `FOUNDATION_CONSTRUCT` | 1 | `0x006977C5` | `queueCreateUnit(what, -1, id, …)` |
| `UNIT_BUILD` | 3 | `0x006977C5` | the same case |
| `REVIVE` | 46 | `0x006973CB` | `queueCreateUnit(NULL, reviveIndex, id, …)` |

Both push their arguments, call `requestUniqueUnitID` (interface vtable `+0x08`) for the id, and
then call `queueCreateUnit` (interface vtable `+0x20`). `sage_patch`'s
[`unique-production-id`](unique-production-id.md) writeup covers that argument order.

## 2. The refusal

`ProductionUpdate::queueCreateUnit` (`0x008A11D2`) opens with the gate:

```asm
008a11f3  push [ebp+0x0c]                ; reviveIndex
008a11f9  push [ebp+8]                   ; what   (NULLed above when this is a revive)
008a1204  push [edi-0x18]                ; the producer Object
008a1205  call [edx+0x64]                ; TheBuildAssistant->isPossibleToMakeUnit(...)
008a1208  test eax, eax
008a120a  jne  0x8a1217                  ; any non-zero code -> return FALSE
```

so every refusal the gate can name kills the production before a queue entry exists and before
any money moves.

### The gate's verdicts (`0x00793ECB`, vtable `+0x64`)

Reading the function bottom-up gives the code space, which the ControlBar's own message table
corroborates (`GUI:NotEnoughMoneyToBuild` for 2, `GUI:ParkingPlacesFull` for 5):

| code | pushed at | means |
|---|---|---|
| 0 | `0x00794098` | allowed |
| 1 | `0x00793EE9`, `0x00793F5D` | no producer / `canMakeUnit` said no |
| 2 | `0x00794017` | not enough money |
| 3 | `0x00793F2D`, `0x0079409C` | producer disabled or held |
| 6 | `0x00794094` | at the per-type build limit |
| **7** | **`0x0079402F`** | **not enough command points** |

The command-point verdict is the last of them:

```asm
0079401e  push 1
00794020  push [ebp+0x0c]                ; the ThingTemplate being produced
00794023  lea  ecx, [esi+0x60]           ; Player+0x60, the command-point bookkeeping
00794026  call 0x6a7f79                  ; hasEnoughCommandPoints
0079402b  test al, al
0079402d  jne  0x794033                  ; enough -> on with the rest of the checks
0079402f  push 7
00794031  jmp  0x79409e                  ; pop eax; return 7
```

**One site covers both cases.** The revive branch does not have its own check: at `0x00793FED`
it resolves the hero's template through the revive manager and jumps straight into the `lea` at
`0x00794023`. So `UNIT_BUILD` and `REVIVE` share these eight bytes.

### `hasEnoughCommandPoints` (`0x006A7F79`)

```asm
006a7f7f  mov  edi, [ebx+0x628]          ; what->CommandPoints
006a7f85  test edi, edi
006a7f87  je   0x6a7fa3                  ; costs nothing -> TRUE
006a7f8a  mov  esi, [ecx+8]              ; command points in use
006a7f8d  call 0x6a7b9f                  ; getCommandPointCap()
006a7f92  add  esi, edi
006a7f94  cmp  esi, eax
006a7f96  setle al                       ; inUse + cost <= cap
006a7f99  test byte [ebx+0x11a], 0x80    ; KindOf ARMY_OF_DEAD
006a7fa1  je   0x6a7fa5
006a7fa3  mov  al, 1                     ; ... or the thing is exempt outright
```

Two things worth noting. The `count` argument every caller pushes is never read. And the exemption
already in the engine — `ARMY_OF_DEAD`, bit 151 of the `KindOf` mask — bypasses *the check*, not
the accounting: the unit still adds its `CommandPoints` to `Player+0x68` when it is created
(`0x006A7FDA`). That is exactly the shape this patch reuses, one level up.

## 3. The half that needs no patching

The request's second clause — "only progress the queue when there is enough CP" — is stock
behaviour. `ProductionUpdate::update` (`0x008A1B9F`) checks the cap **again**, on the head entry,
every frame:

```asm
008a1e08  mov  eax, [ebx+4]              ; the head entry's kind
008a1e0b  cmp  eax, 1                    ; 1 = unit
008a1e0e  je   0x8a1e15
008a1e10  cmp  eax, 3                    ; 3 = revive
008a1e13  jne  0x8a1e87                  ; an upgrade: no cap applies
008a1e15  cmp  dword [esi+0x110], 0
008a1e1c  jne  0x8a1e87                  ; mid-exit (the door is running): not our business
008a1e1e  cmp  dword [esi+0x108], 0
008a1e25  ja   0x8a1e87                  ; likewise, the door timer
008a1e27  push [ebx+8]                   ; the entry's own ThingTemplate
008a1e2a  mov  ecx, [ebp-0x28]           ; the controlling Player
008a1e2d  call 0x6ac856                  ; Player::isBuildableTemplate  -> [ebp-0x0d]
008a1e38  mov  eax, [ebx+8]
008a1e3b  push 1
008a1e3d  push eax
008a1e3e  add  ecx, 0x60
008a1e41  call 0x6a7f79                  ; the SAME predicate the gate used
008a1e46  cmp  byte [ebp-0x0d], 0
008a1e4a  je   0x8a1e50
008a1e4c  test al, al
008a1e4e  jne  0x8a1e87                  ; buildable AND affordable -> produce
008a1e50  cmp  byte [ebx+0x34], 0
008a1e54  jne  0x8a1e87                  ; the entry's own override
008a1e56  test al, al
008a1e58  jne  0x8a2f0e                  ; not buildable: stall silently
008a1e5e  ...                            ; local player only: TheEva->setShouldPlay(0x0B)
008a1e82  jmp  0x8a2f0e                  ; stall
```

`0x008A2F0E` is the function's exit. The progress this frame would have added lives past
`0x008A1E87`, at `0x008A1EBC`:

```asm
008a1ed6  call 0x68c82d                  ; the producer's build-speed attribute modifier
008a1edb  movss xmm0, [ebx+0x1c]         ; the entry's accumulated progress
008a1ee0  addss xmm0, [ebp-0x68]
008a1ee9  movss [ebx+0x1c], xmm0
```

So a head entry the player cannot afford in command points **does not advance at all**, and the
local player hears about it. `[ebx+8]` is populated for a revive as well as a unit: the revive
branch of `queueCreateUnit` writes the hero's template there at `0x008A138B`.

Revives get a second, independent brake. `0x008A0669`, called from the top of `update` at
`0x008A1C10`, walks the whole queue and, for every kind-3 entry the player cannot afford,
increments that hero's revive start frame in the revive manager (`entry+0xA8`) — pushing the
completion out one frame per tick for as long as the cap holds.

None of this is patched. It is why the patch is a door and not a mechanism.

## 4. Where the field goes

`CommandButton` is `0x2E0` bytes, allocated by `ControlBar::newCommandButton` (`0x0071C439`) with
a literal `operator new(0x2E0)` and constructed at `0x0075D516`. Growing it would mean moving that
literal; there is no need to.

The constructor writes **every** member, in order, and the tail of that run is:

```asm
0075d65c  mov  byte  [esi+0x102], bl     ; InPalantir
0075d662  mov  byte  [esi+0x103], bl     ; -- see below
0075d668  mov  byte  [esi+0x104], bl     ; ShowProductionCount
0075d66e  mov  byte  [esi+0x105], 1      ; IsClickable
0075d675  mov  byte  [esi+0x106], 1      ; ShowButton
0075d67c  mov  byte  [esi+0x107], bl     ; RequiresValidContainer
0075d682  mov  dword [esi+0x108], ebx    ; RequireLevel
0075d688  mov  byte  [esi+0x10c], bl     ; AutoAbility
...
0075d721  push 0x1c / lea eax,[esi+0x110] / push ebx / push eax / call memset
```

`ebx` is zero for the whole constructor (`xor ebx, ebx` at `0x0075D52A`).

**+0x10D..+0x10F is alignment padding.** No row in the field table names it, the constructor skips
it, and the `memset` that clears the `KindOfFlags` starts at +0x110. That the constructor
initialises every *real* member — including ones no field parses — is what makes the omission
evidence rather than an assumption.

**+0x103 looks like the same thing and is not.** The constructor zeroes it explicitly, and
`CommandButton::getBorderType` reads it:

```asm
0075cba5  cmp  byte [ecx+0x103], 0
0075cbac  je   0x75cbb2
0075cbae  push 5 / pop eax / ret         ; force border type 5
0075cbb2  mov  eax, [ecx+0xb0]           ; ButtonBorderType
```

Reusing it would have given every `QueueIgnoreCP` button a different border. A scan of the image
for `[reg+0x10D]`, `[reg+0x10E]` and `[reg+0x10F]` accesses turns up nothing in the
`CommandButton` compiland — every hit is a `ThingTemplate` `KindOf` test, whose mask starts at
`ThingTemplate+0x108`.

### The default costs one byte

```
0075d688  88 9e 0c 01 00 00    mov byte  [esi+0x10c], bl
0075d688  89 9e 0c 01 00 00    mov dword [esi+0x10c], ebx
```

`0x88` → `0x89`, six bytes for six. `AutoAbility` still ends up `No` and +0x10D..+0x10F are
cleared on the way past, so the new field defaults to `No` with no hook and no displaced
instruction. This is the same trick
[`terrain-resource-exp`](terrain-resource-exp.md) §2.1 uses on `TerrainResourceBehavior`.

### The field table

`CommandButton`'s field-parse table is at `0x00C2BAC8`: 55 rows of 16 bytes plus a NULL
terminator. It is read to that terminator, never to a count, so appending a row raises no bound.

It has **three** references, all naming the same base:

| VA | instruction | what |
|---|---|---|
| `0x005DA706` | `mov eax, 0xc2bac8` / `ret` | the static `getFieldParse` accessor |
| `0x005DA7B6` | `push 0xc2bac8` | the block parser, fresh button |
| `0x005DA7D0` | `push 0xc2bac8` | the block parser, override block |

The two `push`es hand the table to `INI::initFromINI` (`0x0042DB80`). The accessor has no callers
in the image — the compiler inlined every use — but it is repointed anyway, so nothing that finds
the table through it can disagree with what the parser uses.

The table is boxed in by its own terminator, so the patch rebuilds it in the cave: every live row
copied by value (their name pointers are absolute and keep pointing at `.rdata`), then one row
`{ "QueueIgnoreCP", INI::parseBool (0x0042E558), 0, 0x10D }`, then the terminator. Rows are read
from wherever the references currently point rather than from `0x00C2BAC8`, which is what makes
the patch compose with anything that rebuilt the same table first — and what makes applying it
twice fail cleanly.

## 5. Getting the button's answer to the gate

The gate is `isPossibleToMakeUnit(producer, what, reviveIndex)`. It has **14 callers** and no
argument that could carry a `CommandButton`, so widening its signature is out. Instead the
patch carries the answer in a dword in the cave, raised for exactly the length of one
`queueCreateUnit` call.

The two call sites are whole instructions, which is what makes the wrap cheap:

```asm
; UNIT_BUILD, 0x00697800 - five bytes
00697800  8b cf           mov  ecx, edi          ; edi = the production interface
00697802  ff 56 20        call [esi+0x20]        ; esi = its vtable
00697805  eb 78           jmp  0x69787f          ; the function's common exit

; REVIVE, 0x00697403 - six bytes
00697403  8b ce           mov  ecx, esi          ; esi = the production interface
00697405  53              push ebx               ; what = NULL
00697406  ff 57 20        call [edi+0x20]        ; edi = its vtable
00697409  e9 71 04 00 00  jmp  0x69787f
```

`eax` is dead at both — it holds the id `requestUniqueUnitID` returned, and both sites pushed it
one instruction earlier — so the wrapper can use it freely. Each becomes:

```asm
  mov   eax, [ebp+8]                     ; the CommandButton this press came from
  movzx eax, byte [eax+0x10d]            ; QueueIgnoreCP
  mov   [flag], eax
  <the displaced instructions, verbatim>
  and   dword [flag], 0
  jmp   <the instruction after the window>
```

and the gate's eight-byte verdict becomes a `jmp rel32` plus three `nop`s into:

```asm
  test al, al
  jne  allow
  cmp  dword [flag], 0
  je   refuse
allow:
  jmp  0x794033                          ; the engine's own accept edge
refuse:
  push 7
  jmp  0x79409e                          ; the engine's own refusal tail
```

Neither hook window is a branch target: a sweep of `Object::doCommandButton` and of the gate finds
no `jcc`/`jmp` landing inside either, and the gate's own `jne` lands on `0x00794033`, past the
window's end.

### Why the flag is safe

- It is written and read on the **logic thread**, inside one order's execution, and both wrappers
  clear it immediately after the call they wrap. It is zero at every frame boundary, so it is not
  state a peer can disagree about and nothing the engine CRCs changes.
- It is set and cleared by the **same routine**, so nesting cannot leave it raised — the concern a
  set-on-entry / clear-on-exit hook of `doCommandButton` would have had.
- The only reader is the gate, and the only way to reach the gate with the flag raised is from
  inside the `queueCreateUnit` the wrapper is wrapping. A `ControlBar` refresh, an AI production
  decision or a script's own `canMakeUnit` all run with it at zero.

## 6. What a mod then writes

```ini
CommandButton Command_SummonTheGuard
  Command       = UNIT_BUILD
  Object        = GondorTowerGuard
  QueueIgnoreCP = Yes
End

Behavior = DoCommandUpgrade ModuleTag_Summon
  TriggeredBy                 = Upgrade_SummonTheGuard
  GetUpgradeCommandButtonName = Command_SummonTheGuard
End
```

The press is now accepted at the cap. The unit is charged, queued, and sits at the head of the
producer's queue — with the EVA "not enough command points" cue firing for its owner — until
command points free up, at which point it builds normally.

## 7. What this does *not* do

- **The ControlBar is left stock.** A *visible* button carrying the field is still drawn
  unavailable at the cap and still answers 7 when clicked, because the ControlBar reaches that
  verdict from its own frames (`0x00942EA9`, `0x00942F3F`) rather than through
  `doCommandButton`. The field is for buttons the engine presses.
- **The cap still means what it meant.** A unit queued past it costs its command points once it
  exists, `Player+0x68` counts it, and the palantir readout, the AI's production choices and
  `IgnoreCommandPointLimit` on a template are all unchanged.
- **It is not a refund.** The gold is taken at queue time, as it always is; a player who then
  cancels gets the engine's ordinary refund.
- **Nothing else on the gate moves.** Money (code 2), the producer's state (3), the per-type build
  limit (6) and `canMakeUnit` itself (1) all refuse exactly as before.

## 8. Determinism and compatibility

**Every peer must run the same binary.** Not because of the flag — that is transient, thread-local
in practice, and identical on every peer that executes the same order — but because of the
consequence: an unpatched client refuses a production a patched client accepts, and the two
diverge on the next frame. Replays cross only between identically patched builds.

And the keyword is fatal on a stock build: SAGE treats an unknown field in a known block as a
parse error, the same failure mode the `CommandSet` limit produces as `"Error parsing field
'34'…"`. A mod that writes `QueueIgnoreCP` ships the patched `game.dat` or does not run.

Savegames are unaffected. `CommandButton` is load-time INI data, never `Xfer`'d, and the cave's
flag is meaningless outside a single call.

## 9. Composition

Order-independent. The cave is allocated with `allocate_section` and located by name, the field
table is read from its live references, and no bundled patch touches any of the seven bytes'
worth of sites:

| neighbour | how close it gets |
|---|---|
| `second-resource` | takes the **money** verdict at `0x00794013` (6 bytes) in the same function; the command-point verdict is at `0x0079402B`, 24 bytes later. It rebuilds the `AutoDepositUpdate`, `PlayerTemplate` and `Object` field tables — not `CommandButton`'s. |
| `unique-production-id` | rewrites `requestUniqueUnitID` (`0x008A18FA`), which both hooked cases call one instruction *before* the window this patch takes. |
| `ai-revive-gate` | hooks `canMakeUnit` at `0x007950CE`, inside the function the gate calls, not the gate. |
| `commandset-limit` | grows `CommandSet`, a different object with a different field table (`0x00C4F3D8`). |

## Status

**Static-verified, not yet runtime-verified.** The patch applies to a clean `game.dat`, `verify`
passes, and the cave disassembles to the three intended routines with every branch landing on an
engine instruction boundary. What is open is the in-game confirmation: a `DoCommandUpgrade` firing
at the cap should queue its unit, the producer should hold it with the EVA cue, and it should
start building the moment a unit dies.

## Address index

| VA | what |
|---|---|
| `0x00696FD2` | `Object::doCommandButton`; the button is `[ebp+8]` throughout |
| `0x00697086` | the `Command` read the switch dispatches on (`CommandButton+0x14`) |
| `0x006973CB` | the `REVIVE` case |
| `0x00697403` | its `queueCreateUnit` call — the 6-byte hook window, resume `0x00697409` |
| `0x006977C5` | the `FOUNDATION_CONSTRUCT` / `UNIT_BUILD` case |
| `0x00697800` | its `queueCreateUnit` call — the 5-byte hook window, resume `0x00697805` |
| `0x00793ECB` | `BuildAssistant::isPossibleToMakeUnit`, vtable `0x00C307D8` `+0x64` |
| `0x00794013` | the money verdict (`second-resource`'s window) |
| `0x0079402B` | the command-point verdict — the 8-byte hook window |
| `0x00794033` | its accept edge |
| `0x0079409E` | its refusal tail (`pop eax`) |
| `0x006A7F79` | `hasEnoughCommandPoints(what, count)` on `Player+0x60` |
| `0x006A7B9F` | `getCommandPointCap` |
| `0x006A7FAA` | a template's command-point cost (`ThingTemplate+0x628`) |
| `0x006A7FDA` | the add on object creation — why the exemption is not an exemption from paying |
| `0x006AC856` | `Player::isBuildableTemplate`, the other half of the production-side check |
| `0x008A11D2` | `ProductionUpdate::queueCreateUnit`; its gate call at `0x008A1205` |
| `0x008A138B` | where a revive entry's `ThingTemplate` (`entry+8`) is filled in |
| `0x008A1B9F` | `ProductionUpdate::update` |
| `0x008A1E27` | its command-point stall |
| `0x008A1EBC` | the progress block the stall skips |
| `0x008A2F0E` | `update`'s exit |
| `0x008A0669` | the revive completion-frame delay, called from `0x008A1C10` |
| `0x008B8E2E` | `DoCommandUpgrade`'s grant half (`ModuleData+0x138`) |
| `0x008B8DFC` | its removal half (`ModuleData+0x13C`) |
| `0x0071D6EA` | `ControlBar::findCommandButton(AsciiString&)` |
| `0x0071C439` | `ControlBar::newCommandButton` — `operator new(0x2E0)` |
| `0x0075D516` | the `CommandButton` constructor |
| `0x0075D688` | its `AutoAbility` store — the one-byte widening |
| `0x0075CBA5` | `CommandButton::getBorderType`, the reader that rules out +0x103 |
| `0x00C2BAC8` | the `CommandButton` field-parse table (55 rows) |
| `0x005DA706` / `0x005DA7B6` / `0x005DA7D0` | its three references |
| `0x0042DB80` | `INI::initFromINI(void *, const FieldParse *)` |
| `0x0042E558` | `INI::parseBool` |
