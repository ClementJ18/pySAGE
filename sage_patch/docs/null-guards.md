# Null tests the engine leaves out — the `null-guards` patch

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), verified byte-for-byte
against the shipped `game.dat`.

**Verdict:** the engine dereferences pointers it never tests, and some of those paths are
reachable. This patch collects the fixes: each guard is one hook into the shared `.nullgd` cave,
adds the missing null test, and on NULL leaves through the function's own failure or "no" answer,
so the caller sees an outcome it already handles. On a non-NULL pointer each guard runs the stock
instructions verbatim. `transfer`, `enter` and `path` were recovered from real crash dumps; `hero`
from a reproducible user report, read statically.

| guard | site | NULL pointer | answer on NULL | found in |
|---|---|---|---|---|
| `transfer` | `0x0066C410`, 5 bytes | a pending AI order's target, across a mount swap | "not worth transferring" | a skirmish: Galadriel takes the One Ring, then transforms |
| `enter` | `0x00751ACF`, 9 bytes | an Enter order's target, or its contain | the state fails (`-2`) | a replay: a recorded Enter on an object with no contain |
| `hero` | `0x0080C384`, 8 bytes | a saved hero's subclass, which the lobby reads later | the hero is not loaded | Edain: a hero made under another mod crashes the skirmish menu |
| `path` | `0x0066A26B`, 6 bytes | a unit's path, dropped while the unit moved along it | skip that frame's progress update | Edain skirmish dump, 2026-11-10: a unit with a NaN transform, following a path tied to a map waypoint |

`hero` is the one guard that does not sit on the dereference: the NULL is handed out by a lookup
with four unguarded readers, so the guard refuses the bad indices where they enter, in the `.cah`
loader, and none of the four ever sees them.

**Adding a guard.** Only for a site a dump or a live trace shows is reached, or one a reproducible
report leads to and the static reading pins down. Put the addresses in
`addresses/ai.py` (or the module the function belongs to), add an `_emit_<name>` routine and its
window to `hooks`, anchor every jump target and every instruction that fixes what a register or
stack slot holds at the hook, and add a section below. Leave by the function's own tail rather
than returning from the cave, so the guard owes no cleanup of its own.

## 1. `transfer` — a hero transform crashing on a dead order

`AICommandParmsStorage::reconstitute` turns a stored `ObjectID` into a pointer without checking
it, and the mount swap's "is this order still worth re-issuing" test dereferences the result.

### 1.1 The crash, as observed

`DUMP_2.01.2614.37001_20260830-103559_…_29432_26996.dmp`, 1.3 GB (so written by a build carrying
[`crash-dump`](crash-dump.md), which is what makes the heap readable):

```
ExceptionCode    = 0xc0000005
ExceptionAddress = 0x0066c410
ACCESS_VIOLATION: read at address 0x38
eax=00000000 ecx=18122c78 esi=1a18c350 edi=19688ff8 ebp=001ae6e0
```

Following the heap out of the dump names everyone involved:

| what | value | reads as |
|---|---|---|
| `ecx` | `0x18122C78` | the `AIUpdate`; `[ecx+8]` is `edi` |
| `edi` | `0x19688FF8` | `Object` id **3187**, template `LothlorienGaladriel` |
| `esi` | `0x1A18C350` | `Object` id **6841**, template `LothlorienGaladrielEvil` |
| `[ecx+0x40]` | 3385 | her current victim — a live `MordorFighter`, *not* the dead id |

and the `AICommandParms` on the stack at `ebp+8`, plus the storage it came out of at
`AIUpdate+0x3E4`, agree exactly:

| field | offset | value |
|---|---|---|
| `m_cmd` | `+0x00` | `1` — `AICMD_MOVE_TO_OBJECT` |
| `m_cmdSource` | `+0x04` | `2` — `CMD_FROM_AI` |
| `m_pos` | `+0x08` | `0, 0, 0` |
| `m_obj` / stored `ObjectID` | `+0x14` | **`NULL`** on the stack, **`0x1638` (5688)** in the storage |

Object 5688 is absent from `TheGameLogic`'s id-indexed table (`+0xB8`/`+0xBC`, 1240 live objects
in this dump), which is the whole defect in one line: a nonzero id that resolves to nothing.

> `TheGameLogic` itself could not be read — `game.dat`'s data segments are not in the dump even
> though the profile asks for `MiniDumpWithDataSegs`, so the table was located by pattern-scanning
> for the wrapper entries instead. That gap is [`crash-dump`](crash-dump.md)'s to answer for, not
> this patch's.

### 1.2 Where the NULL comes from — `0x0075315B`

`AICommandParmsStorage::reconstitute` copies the stored command back into a live `AICommandParms`,
resolving its two object ids on the way:

```
0075315e  mov  eax, [ebx]                ; m_cmd
00753166  mov  [ebp], eax
0075316d  mov  [ebp+4], eax              ; m_cmdSource
00753176  movsd; movsd; movsd            ; m_pos
00753179  push dword [ebx+0x14]          ; the stored ObjectID
0075317c  mov  ecx, [0x00de412c]         ; TheGameLogic
00753182  call 0x00449681                ; findObjectByID -> NULL when the id is gone
00753187  mov  [ebp+0x14], eax           ; AICommandParms::m_obj  -- no null test
0075318a  push dword [ebx+0x18]          ; the second id, same treatment
00753193  call 0x00449681
00753198  mov  [ebp+0x18], eax
```

`findObjectByID` (`0x00449681`) is a hash lookup on `TheGameLogic+0xB4` that returns zero for id 0
and zero for a miss, so a stale id and "no target at all" are indistinguishable by the time they
reach a consumer. Every consumer therefore has to null-test, and this one does not.

### 1.3 Where it is dereferenced — `0x0066C2BF`

`AIUpdateInterface::isCommandWorthTransferring(AICommandParms)` — `__thiscall` on the `AIUpdate`
with the parms **by value** (`ret 0xC0`), answering in `al`. It switches on the command type:

| command types | arm | reads |
|---|---|---|
| `0x09`, `0x23`–`0x25` | `0x0066C326` | the waypoint vector at `[ebp+0x28]`, guarded by a count test |
| `0`, `0x0F`, `0x35`–`0x38`, `0x47`, `0x4E`, `0x50`–`0x52` | `0x0066C421` | `m_pos` from the parms — safe |
| **`1`, `0x48`, `0x49`** | **`0x0066C3FB`** | **`m_obj`'s position — unguarded** |
| everything else | `0x0066C3E1` | nothing; answers 0 |

The object arm:

```
0066c3fb  mov   eax, [ecx+8]              ; the AIUpdate's owning Object
0066c3fe  movss xmm0, [eax+0x38]          ; its position
0066c403  movss xmm1, [eax+0x3c]
0066c408  movss xmm2, [eax+0x40]
0066c40d  mov   eax, [ebp+0x1c]           ; AICommandParms::m_obj
0066c410  subss xmm0, [eax+0x38]          ; *** the fault
0066c415  subss xmm1, [eax+0x3c]
0066c41a  subss xmm2, [eax+0x40]
0066c41f  jmp   0x0066c442                ; length vs the locomotor's [+0x3c]
```

`[ebp+0x1c]` is `m_obj` because the struct arrives by value: `+8` for the return address and saved
`ebp`, `+0x14` for the field. `[ecx+8]` is a module's owner back-pointer and is never NULL for a
live module, so the first three loads are not at risk; only the second base is.

#### The answer register, and the tail

`bl` is seeded to 1 at the top and read back out at the bottom:

```
0066c2d1  xor  ebx, ebx
0066c2d3  inc  ebx                        ; bl = 1
...
0066c470  or   dword [ebp-4], 0xffffffff  ; SEH state
0066c474  cmp  dword [ebp+0x28], 0        ; the parms' waypoint vector
0066c478  je   0x0066c483
0066c47a  push dword [ebp+0x28]
0066c47d  call 0x00430170                 ; free
0066c482  pop  ecx
0066c483  mov  al, bl                     ; the answer
0066c485  ...                             ; epilogue, ret 0xc0
```

Both callers read it the same way, so **non-zero means "do not transfer"**:

```
008b1644  call 0x0066c2bf
008b1649  test al, al
008b164b  jne  0x008b1661                 ; skip the re-issue
008b164d  mov  esi, [esi+0x260]           ; else: hand the order to the new object
```

### 1.4 How the dead id gets there

`aiMoveToObject` is `0x007549D7` — by a sweep of all 84 construction sites of `AICommandParms`
(`0x007536DD`), the **only** one that builds command type 1. Three call sites pass `CMD_FROM_AI`;
one is `0x00895738`, inside a module whose `ModuleData` fingerprint identifies it:

- `+0x08` read as a Bool gating `Object::getControllingPlayer` → an is-AI-player test
  (`0x008957C6`) — `SkirmishAIOnly`
- `+0x14` read as a `Real`, scaled to frames and compared against a stored frame at `module+0x24`
  (`0x00895763`) — `ScanIntervalSeconds`
- a partition query built from two 16-byte `ObjectStatus` masks (`0x00895632`), then
  `aiMoveToObject(target, CMD_FROM_AI)` and a flag at `module+0x20`

That is `PickupStuffUpdate`. Galadriel carries it with `StuffToPickUp = PICKUP_STUFF_FILTER_RING`,
which closes the loop: the skirmish AI walks her to the One Ring, the pickup destroys the Ring
object, and the module's arrival branch (`0x00895572`) clears only its own flag — it issues no
replacement order, so `AIUpdate+0x3E4` keeps naming the dead id until some other command
overwrites it. Becoming a Ring hero fires the toggle, and the swap reads it.

`+0x3E4` is written whenever a command arrives and reset only where the storage is constructed
(`0x0066EE02` / `0x0066EBF8` call `0x0066A56C`, which writes `-1`); unlike the one-shot slot at
`+0x2EC`, which `0x0066D810` explicitly invalidates after use, nothing clears it on completion.
It is intermittent rather than certain only because `aiIdle` alone has 108 call sites, so a
replacement order usually lands first.

### 1.5 The patch

Five bytes at `0x0066C410` — exactly one `jmp rel32`, no padding — become a jump to the `transfer`
guard in the `.nullgd` cave:

```
test  eax, eax
je    no_target
subss xmm0, dword [eax+0x38]     ; the displaced instruction, verbatim
jmp   0x0066c415                 ; resume
no_target:
mov   bl, 1                      ; "not worth transferring"
jmp   0x0066c470                 ; the function's own cleanup and `mov al, bl`
```

Nothing in `.text` branches into `0x0066C411`..`0x0066C414`, so the window can be taken whole.

**Why the null answer is 1, not 0.** Both callers skip the re-issue on non-zero. Answering 0
would hand the same `AICommandParms` — `m_obj` still NULL — to the replacement object's state
machine at `0x008B165F`, which moves the fault rather than removing it. A move-to-object with no
object is not an order worth inheriting.

**Why `bl` is written rather than inherited.** No arm on the path to the hook touches `ebx`, so
jumping straight to `0x0066C470` would already answer 1. Two bytes make that independent of a
fact about the path.

**Flags.** `test eax, eax` clobbers EFLAGS, and nothing downstream reads them: the resume point
runs two `subss` and a `jmp`, and the first consumer after it is the `ja` at `0x0066C46C`, whose
flags come from the `fcompi` at `0x0066C468`. The other edge lands on `or dword [ebp-4], -1`,
which sets flags itself.

### 1.6 Blast radius

`0x0066C2BF` has exactly two callers, `0x008B1644` and `0x008B24C3`, both inside
`ToggleMountedSpecialAbilityUpdate` — so the changed edge is reachable only from a mount or
dismount swap. On a non-null target the patched path executes the stock instruction stream with
one `test` added. The guard reads logic state and changes only whether an order is re-issued, on a
frame every peer runs identically, so it is network- and replay-safe.

### 1.7 What this does not fix

- **The other unchecked consumer.** `reconstitute` resolves a second id into `m_obj2`
  (`[ebp+0x18]`, `0x0075318A`) on the same terms. No arm of `0x0066C2BF` reads it, so it is not
  this crash — but it is the same defect one field over, and whatever does read it has not been
  audited.
- **`reconstitute` itself.** The real repair is a null test at `0x00753187`, or dropping the whole
  stored command when its target no longer resolves. That is a larger change with more consumers
  to reason about; this patch fixes the one site a dump proves is reached.
- **The stale storage.** `AIUpdate+0x3E4` still names a dead object after this patch. Nothing else
  observed reads it, and clearing it would need a hook on object destruction.

## 2. `enter` — an Enter order on an object with no contain

`AIMoveToPositionAndEnterState::onEnter` reads the target's contain to find where to walk, and
tests neither the target nor the contain.

### 2.1 The crash, as observed

`DUMP_2.01.2614.37001_20261031-191410_…_21628_35600.dmp`, 22 MB, written while a replay played
on an unpatched `game.dat`. It holds stacks and globals but no heap, so the unit and its target
cannot be named:

```
ExceptionCode    = 0xc0000005
ExceptionAddress = 0x00751ad8
ACCESS_VIOLATION: read at address 0x0
eax=0caf2238 ecx=00000000 ebx=0be01260 esi=0b903cd0 edi=0be01260 ebp=001ae394
```

`eax` is the goal object, `ecx` its contain (NULL), `ebx` the state.

### 2.2 The faulting function — `0x00751A8A`

The vtable at `0x00C29D08` returns `"AIMoveToPositionAndEnterState"` from slot 0 and holds
`0x00751A8A` at `+8`, its `onEnter`:

```
00751a8a  push ebp / mov ebp, esp / sub esp, 0xc     ; plain frame, no SEH
00751a97  push ebx / push esi
00751ab3  mov  ecx, [ebx+0x18]                       ; the state machine
00751aba  mov  eax, [ecx+0x14]                       ; its owner, the unit
00751ac0  mov  eax, [eax+0x260]                      ; the unit's AIUpdate
00751ac6  push edi
00751aca  call 0x008dbace                            ; getGoalObject -> eax, may be NULL
00751acf  mov  ecx, [eax+0x258]                      ; the goal's contain -- no test of eax
00751ad5  mov  [ebp-0xc], eax
00751ad8  mov  eax, [ecx]                            ; *** the fault -- no test of ecx
00751ada  call [eax+0x15c]                           ; the contain's entry position
...
00751af7  pop  edi
...
00751b4a  mov  eax, esi                              ; answer
00751b4c  pop esi / pop ebx / leave / ret
```

`Object+0x258` is the object's one stored contain (see [`multi-contain`](multi-contain.md)), NULL
on any object that declares none. Its siblings test first: `AIEnterState::onEnter` (`0x007515E1`)
null-tests the goal and runs `canEnterObject` (`0x0082CBD5`, which tests the contain), and returns
`-2` from `0x0075170C` when either fails. This state's `update` (`0x00756452`) also runs
`canEnterObject` before its own load of `+0x258`. Only `onEnter` skips both.

### 2.3 How the order got there

The stack walks back to a player's order, replayed:

| return address | function |
|---|---|
| `0x00751E72` | the state machine's `setState`, entering the state |
| `0x0066D8BB` / `0x0066AB2C` | `aiDoCommand`'s switch, case `0x42` → `[vtable+0x5C]` |
| `0x00770F1B` | `aiEnter(Object *target, CommandSourceType)` (`0x00770EDE`), command `0x42` |
| `0x0094D6F0` | the Enter AI order's execute (`0x0094D6A3`), vtable `0x00C8137C` |
| `0x00757591` | `TheAiOrdersManager` (`0x00DE7860`) creating and running that order (`0x0075754C`) |
| `0x0077AC7F` | `GameLogic`'s message dispatcher, message `0x42C` |

Message `0x42C` (index 18 of the table at `0x0077D0B7`, base `0x41A`) is the player's **Enter**.
The handler at `0x0077AC26` resolves its object argument, gives up only if that is NULL, and, with
`PlanningModeEnabled` (`TheGlobalData+0x11CA`) set, hands it to the orders manager. Nothing on
that path asks whether the target can be entered. The order's sibling slot (`0x0094D6FD`) does run
`canEnterObject`; the execute slot that crashed does not.

A live client sends Enter only when the cursor shows the enter hint, and the hint's own contain
load (`ENTER_HINT_CONTAIN_LOAD`, `0x0082CF1A`) is null-tested. So a recorded Enter on an object
without a contain means the replay no longer matches the game that recorded it, most likely a
replay recorded on another Edain or `game.dat` build. The id it names is now a different object.

### 2.4 The patch

Nine bytes at `0x00751ACF`, the contain load and the store after it, become a `jmp rel32` and four
`nop`s into the `enter` guard:

```
test eax, eax                   ; the goal object
je   fail
mov  ecx, [eax+0x258]           ; displaced, verbatim
test ecx, ecx                   ; its contain
je   fail
mov  [ebp-0xc], eax             ; displaced, verbatim
jmp  0x00751ad8                 ; resume
fail:
pop  edi                        ; the stock path pops it at 0x00751af7, before the tail
push -2
pop  esi                        ; STATE_FAILURE, which the tail moves into eax
jmp  0x00751b4a                 ; mov eax, esi / pop esi / pop ebx / leave / ret
```

**Why `-2`.** It is the value `AIEnterState::onEnter` refuses with, so the state machine already
handles it from an enter state's `onEnter`.

**Why the stack balances.** At the hook the frame holds `ebx`, `esi` and `edi` above the locals,
and `getGoalObject` is `__thiscall` with no arguments, so `[esp]` is the saved `edi`. The guard
pops it; the tail pops `esi` and `ebx`, and `leave` restores `esp` from `ebp`. Nothing between the
prologue and the tail touches SEH.

**Flags.** Both `test`s clobber EFLAGS. On resume the next instruction but one is a `call`, so
nothing reads them; the tail reads none either.

Nothing in `onEnter` branches into `0x00751AD0`..`0x00751AD7`, so the window can be taken whole.

### 2.5 Blast radius

`onEnter` runs whenever a unit starts an Enter (command `0x42`, every caller of `aiEnter`: the
player's Enter through the orders manager's Enter order at `0x0094D6EB` and `0x0094D787`, and
four more). On a target with a contain the patched path runs the stock instructions with two `test`s added. The
guard reads only logic state and changes only whether the state starts, so every peer running the
same binary takes the same branch. Peers on different binaries would diverge, as with any
logic-side patch.

### 2.6 What this does not fix

- **The desync itself.** A replay that has drifted out of step keeps playing wrongly after this;
  the guard only stops it crashing.
- **The message handler.** `0x0077AC26` still accepts any object. Testing `canEnterObject` there
  would refuse earlier, but it would also change what a recorded order does, which a guard in the
  state avoids.

<a name="hero"></a>
## 3. `hero` — a Create-a-Hero from another mod crashing the skirmish menu

A `.cah` stores its class and subclass as bare indices into whatever `CreateAHeroClass` blocks the
game that wrote it had loaded (see [`sage_cah`](../../sage_cah/README.md)). Nothing checks them on
load, and the lookup the shell uses hands a bad subclass to four readers as the pointer `0x68`.

### 3.1 The report

Edain: with a hero in the profile that was made under another mod, entering the skirmish menu
crashes. No dump came with it. The two mods' class tables show how easily it happens. Edain
declares seven classes with 3, 3, 2, 2, 2, 2 and 3 subclasses. Age of the Ring declares eight,
with 2, 3, 3, 2, 2, 2, 4 and 1. So an Age of the Ring Hermit (class 2, subclass 2), Gundabad
Berserker (6, 3) or Mound-dweller (class 7) has no counterpart in Edain.

### 3.2 The loader — `0x0080C2E8`

`CreateAHeroHero::load` is `__thiscall` with `edi` = the hero throughout. It opens the file, runs
the hero's `xfer` and answers `bl`. Both callers drop the hero on false:

| caller | what it loads | on false |
|---|---|---|
| `0x0061F271` | each `MyHero*.cah` the shell lists | deletes the hero, never adds it to `+0x17C` |
| `0x0061A219` | the legacy `MyHero.dat` | answers NULL |

The verdict is the checksum: `CreateAHeroHero::xfer` compares the stored CRC with the one it
recomputed, `sete al`, `mov [esi+0x71], al` (`0x0080BA84`). The loader's last act before the
shared tail is

```
0080c382  mov  ecx, edi
0080c384  call 0x00809ca6           ; sum the powers' costs, skipping unknown CommandButtons
0080c389  mov  bl, [edi+0x71]       ; checksum matched
0080c38c  or   dword [ebp-4], -1    ; the tail every path joins
```

The xfer reads the class into `+0x0C` and the subclass into `+0x10`, with no range test.

### 3.3 Where it is dereferenced — `0x006199E4`

The shell asks for a subclass's `UsableFactions` mask through `0x00619CE6`, `(class, subclass) ->
UsableFactions *`. Its class step is bounds-checked and answers a static dummy for a bad class.
Its subclass step is not:

```
006198f6  mov  eax, [ecx+0x18]      ; SubClass vector end
006198f9  sub  eax, [ecx+0x14]      ;            - begin
006198fe  cdq
006198ff  mov  edi, 0xd8
00619904  idiv edi                  ; count
0061990c  cmp  edx, eax
0061990e  jae  -> answer NULL
...
006199e4  add  eax, 0x68            ; &SubClass::UsableFactions, NULL or not
```

Its four callers, `0x0062D66C`, `0x00842E77`, `0x00843BF9` and `0x009326CD`, each read through the
answer at once. Two are the `cah-factions` gates 2 and 3 (`docs/cah-faction-limit.md`), and
`0x009326CD` does `mov eax, [eax]` with no side short-circuit at all. A foreign subclass index
is a read of address `0x68`.

A foreign *class* index survives that path, because of the dummy. It is refused anyway: it names
no class this mod has, and the class tables' other readers were not audited.

### 3.4 The patch

Eight bytes at `0x0080C384`, the call and the verdict, become a `jmp rel32` and three `nop`s into
the `hero` guard:

```
call 0x00809ca6                 ; displaced, relocated
mov  bl, [edi+0x71]             ; displaced, verbatim
mov  eax, [0x00de3d84]          ; TheCreateAHeroManager
test eax, eax
je   done
mov  ecx, [eax+0x154]           ; class vector begin
mov  edx, [eax+0x158]           ;              end
sub  edx, ecx
je   done                       ; no classes parsed: nothing to judge against
sar  edx, 5                     ; class count, 32-byte entries
mov  eax, [edi+0xc]             ; the hero's class
cmp  eax, edx
jae  foreign                    ; unsigned: a negative index is foreign too
shl  eax, 5
add  ecx, eax                   ; the class
mov  eax, [ecx+0x18]
sub  eax, [ecx+0x14]
xor  edx, edx
mov  ecx, 0xd8
div  ecx                        ; subclass count, as 0x006198F6 takes it
cmp  [edi+0x10], eax            ; the hero's subclass
jb   done
foreign:
xor  bl, bl                     ; "not loaded", the answer a bad checksum gives
done:
jmp  0x0080c38c
```

**Why the loader.** Rejecting there turns a foreign hero into one with a bad checksum, a case
both callers and every later list already handle. Guarding the four readers instead would leave
the hero in the list for whatever reads it next.

**Registers.** From `0x0080C38C` on, the tail reloads `ecx`, calls out and returns `bl`, so `eax`,
`ecx` and `edx` are dead and `edi` is untouched. EFLAGS are dead too: the next instruction is an
`or`.

Nothing in the loader branches into `0x0080C385`..`0x0080C38B`, so the window can be taken whole.

### 3.5 Blast radius

The guard runs once per hero file, when the shell lists heroes. A hero whose indices fit is kept
exactly as before. A foreign hero disappears from the Create-a-Hero screen as well as the skirmish
lobby; the file on disk is untouched, and it comes back under the mod that made it. The guard only
decides which heroes the local list holds, and it reads nothing a peer could see differently.

### 3.6 What this does not fix

- **A foreign hero whose indices happen to fit.** Indices are positions, not names, so a hero from
  another mod that lands on an existing class and subclass still loads. It brings its own
  `CommandButton` names, bling group names and bling indices. The cost sum skips buttons it cannot
  find. Whether the spawn and bling paths cope with values this mod does not define was not
  examined.
- **A hero received over the network.** How a peer's hero reaches this machine was not traced. If
  it skips the loader, the guard does not see it. A peer on another mod is a mismatched game
  anyway.

## 4. `path` — a path dropped while the unit follows it

### 4.1 The crash, as observed

A skirmish played "single-player over network" with Edain, around 3500 CP, shortly after Imladris
reinforcements arrived. No error box. The dump (`DUMP_2.01.2614.37001_20261110-144605_…`):

```
ExceptionCode    = 0xc0000005   read at 0x00000004
ExceptionAddress = 0x0076559c   mov eax, [ecx+4]        ; ecx = 0
esi = 0x0e225a60  (vtable 0x00C10590: AIUpdateInterface)
edi = 0x0b282040  (the Object)    ebx = edi+0x38 (its position)
```

The EBP chain (the raw stack walk is mostly stale return addresses):

```
0x00765598  PATH_UPDATE_PROGRESS          <- faults on its first read, the path's head
0x0066A279  AIUpdateInterface::doLocomotor (0x00669932, vtable slot +0x254)
0x0066CD39  its caller (0x0066C748), through `call [eax+0x254]`
0x0066E707  AIUpdateInterface's update
bfme2_accel.dll+0x5BD86                   <- the accelerator's timing wrapper, pass-through
```

`[esi+0x140]` (`AI_PATH_OFFSET`) is 0 in the dump. The unit's whole transform is NaN: `Object+0x08`
through `+0x24` and the position at `+0x38`..`+0x40` all hold `0xFFC00000`, with only the matrix's
`(0, 0, 1)` z axis intact.

### 4.2 Where the NULL comes from

The caller at `0x0066CCED` tests the path before it calls `doLocomotor`: goal type `4` and
`[esi+0x140] != 0`, then sets the goal type to `1` (follow the path). In `doLocomotor` the `1` arm
(`0x00669BB2`) tests it again and calls `0x00766173` on it at `0x00669EA2`. So the path was there
at that point. The arm then reads the id at the next node's `+0x20` (`0x005E2D74`, `0x7FFFFFFF` for none),
asks TheTerrainLogic for the object with that id (vtable `+0x8C`, `0x00669D30`), and switches on
its `+0x60`: 3 in the dump, which takes `0x0066A050`. That object is a **waypoint**: vtable
`0x00C1132C`, stamped by the constructor at `0x006829B0`, which takes an id (`+4`), a name (`+8`)
and a location (`+0xC`). In the dump it is id `0x165` at (2016, 2014, 87). So the unit was moving
along a path tied to a map waypoint, the way scripted reinforcements usually enter. That arm sets
model condition bits and joins the shared tail at `0x0066A23E`:

```
0066a23e  mov  ecx, [esi+0x1f0] / ... / call 0x005e6810   ; Locomotor: move towards the point
0066a256  call 0x0070c201                                  ; Object::setPosition
0066a266  call 0x0068bbf4                                  ; Object::setLayer
0066a26b  mov  ecx, [esi+0x140]                            ; <- the window: reload the path
0066a271  push 1 / push ebx / call 0x00765598              ; no test
0066a279  jmp  0x00669b08
```

Every arm of that switch except `7` (`0x0066A170`, which leaves through `0x0066A4EA`) ends here.
Arm `8` (`0x00669F1B`) makes its own calls first and then **re-tests** the path (`0x00669F4F`:
`mov ecx, [esi+0x140]` / `test ecx, ecx` / `je`) before falling into the same tail. So the engine's
authors knew a call can drop the path, and did not repeat the test after the tail's own move.
`AI_DESTROY_PATH` (`0x0066276B`) has 45 direct callers, and this tail reaches several translation
units, so which callee freed it in this dump was not pinned down. A NaN position is a likely
trigger: it can make any position or cell validity check fail.

### 4.3 The patch

Six bytes at `0x0066A26B` become `jmp <cave>` / `nop`:

```
mov   ecx, [esi+0x140]           ; the displaced reload, verbatim
test  ecx, ecx
je    .none
jmp   0x0066a271                 ; push 1 / push ebx / call - unchanged
.none:
jmp   0x0066a279                 ; past the call
```

`.none` lands after the call, before anything was pushed for it, so `PATH_UPDATE_PROGRESS`'s
`ret 8` has nothing to balance. Its `bool` answer is never read: `0x00669B08` writes a byte and
jumps to `0x0066A45B`, which sets `eax` before reading it. `ecx` is the only register written, and
the stock code wrote it too. Nothing in `doLocomotor` branches into `0x0066A26C`..`0x0066A270`.

### 4.4 Blast radius

The guard runs once per path-following unit per frame and adds a `test`. With a path it is the
stock code. Without one, the unit misses that frame's path progress update, which it has no path
to make. It reads logic state only, and the outcome depends only on logic state, so peers that all
have the patch stay in sync.

### 4.5 What this does not fix

- **The NaN transform.** Where it came from is not in the dump. The guard only stops this read
  crashing. A NaN unit can still crash a later read, or freeze in place. If the guard is installed
  and the same report comes back, the next dump should be taken with `debug.fulldump +` so the
  unit's template and locomotor are in it.
- **What freed the path.** See 4.2.
- **Stock or `wall-mesh-release`.** The unguarded reload is stock: the bytes at `0x0066A26B` are
  the same in the shipped `game.dat`, and `wall-mesh-release` hooks only the pathfinder's wall
  add/remove (`0x00935FAA`..`0x00936B5C`) and the slot release (`0x00768AA7`). The player's build
  did carry `wall-mesh-release` (Edain image size `0xBC2000`, the size of Edain-Mod `975ceba9d`'s
  binary, which has it). Whether it set up the NaN or the dropped path is open: it would need a
  wall that died while this unit's path crossed its layer, and the dump does not hold the path's
  nodes to say which layer they were on.

## 5. Verification

`apply` asserts all four windows and thirty-three anchors before writing anything. For `transfer`: the
check's prologue, the seed and the read of `bl`, the object arm's head, the load that fixes which
frame slot holds the target, both jump targets, and both call sites, whose five bytes *are* their
displacement, so asserting them asserts that the edited function is the one the swap reaches. For
`enter`: the vtable slot (its four bytes *are* `onEnter`'s address), the prologue, the `push edi`
and the goal call before the window, the resume, the `pop edi`, the tail, and `AIEnterState`'s
`push -2` that fixes the failure value. For `hero`: the loader's prologue, its `mov edi, ecx`, the
tail, the refresh's prologue, both callers' `call`s, the checksum store at `+0x71`, the engine's own
class and subclass lookups (which fix the `+0x154`, `+0x14` and `0xD8` the guard reads), the
unguarded `add eax, 0x68`, and a lobby caller's reads of `+0x10` and `+0x0C`. For `path`: the
vtable slot that proves the function is `doLocomotor`, its prologue, the `push`/`push`/`call`
resume (the call's bytes fix the callee), the `jmp` after it, and the callee's prologue up to its
`[ecx+4]` read. `verify` locates `.nullgd` by name, rebuilds the cave for
the address the layout produced, and checks each window holds a `jmp` to its guard. `detect` takes
the default, the patch having no parameters.

`tests/sage_patch/test_null_guards.py` disassembles each guard and asserts each edge, the stack
balance on `enter`'s failure path, the unsigned bounds and the registers `hero` may write, and,
against the shipped `game.dat`, every stock byte, that nothing branches into any window, and that
`apply` then `verify` round-trips.

**Runtime status.** `hero` and `path` are verified statically only; `path` has not met a dropped
path in a running game. `hero` has not been run against a
foreign hero in the game.

```sh
sage-patch apply null-guards --in game.dat.backup --out game.dat   # no parameters
sage-patch verify null-guards game.dat
```
