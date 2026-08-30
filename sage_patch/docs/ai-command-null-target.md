# A hero transform crashing on a dead order — the `ai-command-null-target` patch

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), verified byte-for-byte
against the shipped `game.dat`.

**Verdict:** one window, five bytes, one cave. `AICommandParmsStorage::reconstitute` turns a
stored `ObjectID` into a pointer without checking it, and the mount swap's "is this order still
worth re-issuing" test dereferences the result. Recovered from a real crash dump; the patch adds
the missing null test and nothing else.

## 1. The crash, as observed

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

## 2. Where the NULL comes from — `0x0075315B`

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

## 3. Where it is dereferenced — `0x0066C2BF`

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

### The answer register, and the tail

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

## 4. How the dead id gets there

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

## 5. The patch

Five bytes at `0x0066C410` — exactly one `jmp rel32`, no padding — become a jump into an `.ainull`
cave holding 21 bytes:

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

## 6. Blast radius

`0x0066C2BF` has exactly two callers, `0x008B1644` and `0x008B24C3`, both inside
`ToggleMountedSpecialAbilityUpdate` — so the changed edge is reachable only from a mount or
dismount swap. On a non-null target the patched path executes the stock instruction stream with
one `test` added. The guard reads logic state and changes only whether an order is re-issued, on a
frame every peer runs identically, so it is network- and replay-safe.

## 7. What this does not fix

- **The other unchecked consumer.** `reconstitute` resolves a second id into `m_obj2`
  (`[ebp+0x18]`, `0x0075318A`) on the same terms. No arm of `0x0066C2BF` reads it, so it is not
  this crash — but it is the same defect one field over, and whatever does read it has not been
  audited.
- **`reconstitute` itself.** The real repair is a null test at `0x00753187`, or dropping the whole
  stored command when its target no longer resolves. That is a larger change with more consumers
  to reason about; this patch fixes the one site a dump proves is reached.
- **The stale storage.** `AIUpdate+0x3E4` still names a dead object after this patch. Nothing else
  observed reads it, and clearing it would need a hook on object destruction.

## 8. Verification

`apply` asserts the five hooked bytes and nine anchors: the check's prologue, the seed and the
read of `bl`, the object arm's head, the load that fixes which frame slot holds the target, both
jump targets, and both call sites — whose five bytes *are* their displacement, so asserting them
asserts that the edited function is the one the swap reaches. `verify` locates `.ainull` by name,
rebuilds the guard for the address the layout produced and compares it, and checks the window
holds a `jmp` to it. `detect` takes the default, the patch having no parameters.

`tests/sage_patch/test_ai_command_null_target.py` disassembles the cave and asserts each edge
separately, and — against the shipped `game.dat` — checks every stock byte, that both call sites
resolve to the patched function, and that nothing branches into the window's interior.

```sh
sage-patch apply ai-command-null-target --in game.dat.backup --out game.dat   # no parameters
sage-patch verify ai-command-null-target game.dat
```
