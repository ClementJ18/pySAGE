# `OK_FOR_MULTI_EXECUTE` and the model conditions it does not check

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR), derived from a
stock `game.dat` (11,346,944 bytes).

- **Cost:** 2 `rel32` repoints + a `0xDB`-byte `.mxgate` cave. No structure grows, no name table
  moves, no INI keyword is added.
- **Risk:** low, and bounded by construction — a member is only ever *skipped*, and only when its
  own command button carries a model condition that disables it.
- **Status:** **built** — see [`patches/multi_execute_gate.py`](../patches/multi_execute_gate.py).
  **Not yet runtime-verified in game.**

```
sage-patch apply multi-execute-gate --in game.dat.backup --out game.dat
sage-patch verify multi-execute-gate game.dat
```

## The complaint

Edain's Lothlórien units carry *Ambush of the Wood-elves*, which is only meant to be usable while
the battalion is stealthed. Its button says exactly that:

```ini
CommandButton Command_ElvenAmbush
    Command                = SPECIAL_POWER
    Options                = OK_FOR_MULTI_SELECT  OK_FOR_MULTI_EXECUTE
    SpecialPower           = SpecialAbilityElvenAmbush
    EnableOnModelCondition = INVISIBLE_CAMOUFLAGE
    ...
End
```

…and it does not work as a group. Select five battalions of which one is stealthed, click the
button, and **all five** fire the ambush. The mod's shipped workaround is a command-set swap — a
second, `NONPRESSABLE` `Command_ElvenAmbushFake` button and a set that is exchanged when the unit
enters and leaves stealth — which restores correctness at the cost of the mass trigger. Players
click battalions one at a time.

## Why the button's own condition does not reach the click

### The one place model conditions are evaluated

`0x00942490` is the whole of it. `stdcall(CommandButton *button, Object *obj)`, `ret 8`:

```
00942490  53 56 57              push ebx / esi / edi
00942493  8b7c2410              mov  edi, [esp+0x10]      ; the button
00942497  8db7e0010000          lea  esi, [edi+0x1e0]     ; DisableOnModelCondition
0094249d  8bce                  mov  ecx, esi
0094249f  e8df12b7ff            call 0x4b3783             ; ModelConditionFlags::any()
009424a4  84c0                  test al, al
009424a6  8b5c2414              mov  ebx, [esp+0x14]      ; the Object
009424aa  7410                  je   0x9424bc
009424ac  56                    push esi
009424ad  8d8b0c010000          lea  ecx, [ebx+0x10c]     ; Object's model-condition mask
009424b3  e8310ed2ff            call 0x6632e9             ; testAny()
009424b8  84c0                  test al, al
009424ba  7521                  jne  0x9424dd             ; disabled
009424bc  8db794010000          lea  esi, [edi+0x194]     ; EnableOnModelCondition
              …same shape, inverted…
009424dd  6a03                  push 3                    ; DISABLED
009424e1  6a02                  push 2                    ; AVAILABLE
```

Three callers, all in the ControlBar: `0x00942818`, `0x009435C3`, `0x009435DC`. It is a pure
predicate — it reads the button's two masks and the object's `+0x10c` and returns — which is what
makes it safe to call from anywhere, including the logic side.

The two masks are `CommandButton` fields at `+0x194` (`EnableOnModelCondition`) and `+0x1E0`
(`DisableOnModelCondition`), each a 19-dword `ModelConditionFlags` (`0x4C` bytes), from the field
table at `0x00C2BAC8`.

### The ControlBar's group rule is "any member"

`0x00940435` is the command-button executor — the function a click reaches through the window
handler at `0x00941BFC`. Its prologue reads `[ControlBar+0x70]`, and when that is **7** (the
multi-select context) it walks `TheInGameUI`'s selected-drawable list and asks the availability
evaluator `0x00942733` about each member:

```
0094056c  8b0d3048de00          mov  ecx, [TheInGameUI]
00940574  ff9024010000          call [eax+0x124]          ; getAllSelectedDrawables()
…
009405b3  e87b210000            call 0x942733             ; availability(button, obj, …)
009405b8  83f801                cmp  eax, 1
009405bb  0f8495000000          je   0x940656             ; -> DO THE COMMAND
009405c1  83f802                cmp  eax, 2
009405c4  0f848c000000          je   0x940656             ; -> DO THE COMMAND
```

That is defensible on its own: with a mixed selection you want the button lit and clickable if
anyone can use it. It is not the bug.

### The click sends the *group*, not the units

The `Command = SPECIAL_POWER` case is at `0x0094153C`:

```
0094153c  mov  ecx, [TheMessageStream]
00941544  mov  edi, 0x410                    ; MSG_DO_SPECIAL_POWER
0094154a  call [eax+0x48]                    ; appendMessage
0094154d  mov  ecx, [esi+0x44]               ; button->m_specialPower
00941552  call 0x688d3c                      ; getFinalOverride
00941557  push [eax+0x14]                    ; arg0 = the special power's id
0094155c  call 0x7111e5                      ;   appendIntegerArgument
00941561  push [esi+0x1c]                    ; arg1 = the button's Options word
00941566  call 0x7111e5
0094156b  push 0                             ; arg2 = source object id: ZERO
0094156f  call 0x71111a                      ;   appendObjectIDArgument
00941574  push 0                             ; arg3
```

Two things ride out of the ControlBar: the button's **`Options`** word, and an object id of
**zero**. Nothing else about the button survives — not its name, not its masks.

### Zero means "the whole selection"

`0x0077A42C` is the `MSG_DO_SPECIAL_POWER` case of the logic-side message dispatcher (jump table
`0x0077D087`, indexed from `0x0040D`):

```
0077a42f  call 0x710c9e ; arg0 -> edi        ; special power id
0077a43a  call 0x710c9e ; arg1 -> [ebp+0xc]  ; the command options
0077a448  call 0x710c9e ; arg2
0077a455  call 0x449681                      ; GameLogic::findObjectByID  -> [ebp+8]
…
0077a4a8  cmp  [ebp+8], ebx                  ; did arg2 name an object?
0077a4ab  je   0x77a4d6
          ; yes: build a one-member AIGroup around it and run the power
0077a4d6  cmp  [ebp-0x10], ebx               ; no: [ebp-0x10] is the issuing player's selection
0077a4f2  push 2 / push [ebp+0xc] / push edi
0077a4f8  call 0x76f5db                      ; AIGroup::doSpecialPower(id, options, CMD_FROM_PLAYER)
```

So the ControlBar's zero routes the order at the **`AIGroup` built from the player's selection**,
and the button's options word is what the group is told about it.

### `OK_FOR_MULTI_EXECUTE` is bit 20, and two instructions read it

The `CommandButton` `Options` name table is at `0x00DA4C88`: 32 names, NULL-terminated at
`0x00DA4D08`, resolved by the shared bit-string parser `0x0042E840`, which does
`xor edx,edx / inc edx / shl edx, cl / or [esi], edx` — index *i* means bit *i*, plainly.
`OK_FOR_MULTI_EXECUTE` is entry 20, so the mask is `0x00100000`.

A sweep of `.text` finds **exactly two** instructions that test that bit of anything:

| VA | in | instruction |
|---|---|---|
| `0x0076F5FF` | `AIGroup::doSpecialPower` | `and eax, 0x100000` on `[ebp+0xc]` |
| `0x007709BD` | `AIGroup::doSpecialPowerAt*` | `and eax, 0x100000` on `[ebp+0x10]` |

That is the entire implementation of the flag. Both are the same shape: when the bit is set, skip
the "pick the best member" scoring pass and go straight to the loop that visits every member.

### The loop, and the gate it already has

`AIGroup::doSpecialPower` at `0x0076F5DB`:

```
0076f5f2  call 0x7b1b05                      ; findSpecialPowerTemplateByID -> [ebp-4]
0076f5fa  mov  eax, [ebp+0xc]                ; the options word
0076f5ff  and  eax, 0x100000                 ; OK_FOR_MULTI_EXECUTE?
0076f607  mov  [ebp-0xc], eax
0076f60a  jne  0x76f697                      ;   yes -> straight to the member loop
          …the scoring pass: pick one "best" member…
0076f697  mov  eax, [esi+4]                  ; the member list
0076f6a4  mov  esi, [edi+8]                  ; <- loop body: esi = this member's Object*
0076f6c3  cmp  dword [ebp-4], 0
0076f6c7  je   0x76f704                      ;   no template -> skip
0076f6c9  mov  ecx, [0xde8ba8]
0076f6cf  push 1                             ; check recharge
0076f6d1  push [ebp+0xc]                     ; the options word
0076f6d4  push 0
0076f6d6  push [ebp-4]                       ; the SpecialPowerTemplate
0076f6d9  push esi                           ; the Object
0076f6da  call 0x82d5da                      ; <-- THE PER-MEMBER GATE
0076f6df  test al, al
0076f6e1  je   0x76f704                      ;   refused -> skip this member, keep going
0076f6ee  call 0x68e5a3                      ; Object::doSpecialPower
0076f6fb  cmp  [ebp-0xc], ebx                ; multi-execute?
0076f6fe  mov  byte [ebp+0xb], 1
0076f702  je   0x76f767                      ;   no -> stop after the first success
0076f704  mov  edi, [edi]                    ; next member
```

`0x0082D5DA` is a real predicate, and it is not lazy: it checks `RequiredSciences` (via
`getFinalOverride(tmpl)+0x1c` against `Object::hasScience` `0x0068DF46`), `SpecialPower.UnitCost`
against the horde's member count (`+0x258` → vtable `+0x7c` → vslot `+0x188`), that the object has
a module for the power at all (`0x0068C26D`), and that the module is recharged (module vtable
`+8` ≥ 1.0, then `+0x48`).

**What it is never given is the `CommandButton`.** Its arguments are an `Object*` and a
`SpecialPowerTemplate*`. `EnableOnModelCondition` and `DisableOnModelCondition` are properties of
the *button*, and the button did not cross the message. So they are checked once, per member, to
decide whether to light the button — and then never again.

That is the bug, stated precisely: **the group availability rule is "any member", and the group
execution rule is "every member", and nothing between them re-applies the per-member rule.**

### The same shape, for targeted powers

`0x0077097E` is the `AtLocation` / `AtObject` sibling, behind `MSG_DO_SPECIAL_POWER_AT_LOCATION`
(`0x411`) and `..._AT_OBJECT` (`0x412`). Same multi-execute test at `0x007709BD`, same member
loop, same missing check; its per-member gate is `0x0082D925` at `0x00770B67` — six arguments
instead of five, with the template fourth rather than second.

## The fix

Add the check the loop cannot make, by recovering the button the loop was not given.

### The button is recoverable from the object

The logic side already does this walk, twice. `0x0076FE16` (an `AIGroup` helper) and `0x0082DDE1`
both go object → command set → button:

```
0082de20  call 0x69156b                      ; Object::getCommandSetString -> AsciiString*
0082de25  mov  ecx, [0xde7744]               ; TheControlBar
0082de2c  call 0x71efa2                      ; findCommandSet -> CommandSet*
0082de42  call 0x80c837                      ; getCommandButton(i)
0082de4d  cmp  dword [esi+0x14], 0x18        ; Command == SPECIAL_POWER
0082de53  mov  ecx, [esi+0x44]               ; the button's SpecialPower
0082de56  call 0x688d3c                      ; getFinalOverride
0082de93  cmp  dword [ebp+0xc], 0x21         ; …for 33 slots
```

`Object::getCommandSetString` (`0x0069156B`) is the piece that matters most here, because it is not
a template read:

```
0069156b  lea  edi, [esi+0x438]  ; if non-empty, this is the set
00691580  lea  edi, [esi+0x440]  ; else, if non-empty, this one
00691591  lea  edi, [esi+0x43c]  ; else, if non-empty, this one
006915a6  mov  eax, [esi+4]      ; else the ThingTemplate's own
006915a9  add  eax, 0x70         ;   CommandSet at +0x70
```

Three per-object override strings ahead of the template's. **A command-set swap writes those**, so
this returns the set the player is actually looking at — which is what makes the check agree with
the button that was clicked even in a mod that swaps sets at runtime.

### The cave

One routine and two shims, in a `.mxgate` section allocated past every existing one.

`gate(Object *obj, SpecialPowerTemplate *tmpl) -> bool`, cdecl:

```asm
    ecx = obj;  eax = Object::getCommandSetString()      ; 0x69156b
    ecx = [TheControlBar];  if (!ecx) return true
    eax = ControlBar::findCommandSet(eax)                ; 0x71efa2
    if (!eax) return true
    esi = eax;  ebx = 0
.next:
    edi = CommandSet::getCommandButton(esi, ebx)         ; 0x80c837
    if (!edi)                     goto .step
    if (edi->m_command != 0x18)   goto .step             ; SPECIAL_POWER only
    ecx = edi->m_specialPower;  if (!ecx) goto .step
    eax = getFinalOverride(ecx)                          ; 0x688d3c
    if (eax->m_id != tmpl->m_id)  goto .step
    eax = <model-condition gate>(edi, obj)               ; 0x942490
    return eax != 3
.step:
    if (++ebx < <slots>)          goto .next
    return true
```

Matching on `SpecialPowerTemplate::m_id` (`+0x14`) rather than on the pointer is deliberate: the
loop's template came out of the store *by id*, while the button names one that may be an INI
override copy of it. The id is what the message carried and what the store resolved, so comparing
ids cannot disagree with the click. It is also what the ControlBar itself does.

Every callee is `__thiscall` or `stdcall` and preserves `ebx`/`esi`/`edi` — proven by the engine's
own use of them, since `0x0082DDE1` holds all three live across the same three calls — so the slot
index, the `CommandSet` and the candidate button stay in registers for the whole walk.

The two shims are identical but for two displacements and one immediate:

```asm
shim:                            ; [esp]=return, then the stock gate's arguments
    push ecx                     ; the gate's `this`
    push dword [esp+<tmpl+4>]    ; the SpecialPowerTemplate
    push dword [esp+<obj+8>]     ; the Object
    call gate
    add  esp, 8
    pop  ecx
    test al, al
    jne  .stock
    xor  al, al
    ret  <arg bytes>             ; refuse, cleaning what the stock gate would have
.stock:
    jmp  <stock gate>            ; its own ret <arg bytes> lands back in the loop
```

| shim | hook | falls through to | args | `Object*` | `SpecialPowerTemplate*` |
|---|---|---|---|---|---|
| targetless | `0x0076F6DA` | `0x0082D5DA` | `ret 0x14` | `[esp+4]` | `[esp+8]` |
| targeted | `0x00770B67` | `0x0082D925` | `ret 0x18` | `[esp+4]` | `[esp+0x10]` |

Both loops already treat a false answer as *skip this member and continue* (`je 0x0076F704` /
`je 0x00770B89`), so the shim needs no new control flow — only a reason to answer false.

### What a mod then writes

Nothing new. `Command_ElvenAmbush` as it already stands starts behaving the way its
`EnableOnModelCondition` reads, and the swap plus `Command_ElvenAmbushFake` can be deleted:

- the button stays lit while any selected battalion is stealthed (unchanged);
- clicking it ambushes exactly the stealthed ones;
- a group with no stealthed member does nothing, because the button is already greyed.

## Design decisions, and what was rejected

**Client-side filtering, rejected.** The ControlBar could emit one `MSG_DO_SPECIAL_POWER` per
eligible selected object instead of one with a zero id. That would be *client-local* — the message
stream is what crosses the network, so an unpatched peer would process the explicit per-object
orders identically and replays would still cross, which is a genuine advantage over the logic-side
fix. It was rejected on coverage: the emitter is one of ~60 cases in a 6.7 KB function, each with
its own message shape, and it would leave the auto-ability, script and AI paths — which reach the
same `AIGroup` loops — unfixed. The gate belongs where the decision is made.

**Hooking `0x0082D5DA` / `0x0082D925` themselves, rejected.** Fewer bytes, but those two have nine
callers between them, including the ControlBar's own availability evaluation and two update
modules. Hooking the *call sites* inside the two group loops confines the change to the path that
is actually wrong.

**The single-member paths, deliberately left stock.** Both group functions have a second gate call
(`0x0076F746`, `0x00770BD3`) on the "best member" the scoring pass picks when
`OK_FOR_MULTI_EXECUTE` is *absent*. That pass filters on a kind-of bit and scores by distance; it
does not know about model conditions, so it can pick a disabled member — a real second gap. But
gating it there would turn "the wrong unit acts" into "nothing happens", because there is no
fall-through to another candidate. Fixing it properly means replacing the scoring pass, not
filtering it, and that is a different patch.

## Known rough edges

- **Every peer must run the same patched binary.** This changes which objects a logic-side order
  reaches, so a patched and an unpatched client diverge on the first multi-execute activation of a
  model-conditioned button, and replays do not cross. Same requirement as
  [`production-condition`](production-model-condition.md); the opposite of `replay-outcome`.
- **The slot bound is a literal, and `commandset-limit` owns it.** The cave walks
  `0..slots-1`, matching the 42 stock consumers that hardcode 33. `slots=None` (the default) reads
  the bound back out of the image with `CommandSetLimitPatch.detect`, so **apply `commandset-limit`
  first**; `--slots N` pins it. Applied the other way round nothing corrupts — a button in a slot
  past the bound is simply not found and that member takes the stock path — but `sage-patch verify`
  reports the disagreement, and `detect` answers "not patched".
- **`SPECIAL_POWER` buttons only.** The gate matches `Command == 0x18`. Other command types that
  can carry `OK_FOR_MULTI_EXECUTE` (`FIRE_WEAPON`, the toggles) go through different messages and
  different group methods; none of them was in scope here, and each would need its own hook.
- **A member with no matching button is allowed.** Deliberate: that is the AI, a script, or a power
  granted by a module rather than by a button, and none of those has a model condition to consult.
- **The AI module's "last command source" is still stamped on refused members.** `0x0076F6C0`
  writes `[AIUpdate+0x48]` before the gate runs, so a skipped member records the command source
  without acting on it — exactly what already happens to a member the stock gate refuses.
- **Cost.** One command-set walk per member per activation: at most 33 iterations of a call and
  three compares, and only on a group ability. Nothing on the per-frame path.

## Appendix — every address this document depends on

| VA | meaning |
|---|---|
| `0x0042E840` | the shared `Options` bit-string parser — index *i* → bit *i* |
| `0x00465AF4` | the override-chain walk `getFinalOverride` tail-jumps into |
| `0x004B3783` | `ModelConditionFlags::any()` |
| `0x006632E9` | `ModelConditionFlags::testAny()` on `Object+0x10c` |
| `0x0069156B` | `Object::getCommandSetString` — three overrides, then `ThingTemplate+0x70` |
| `0x00688D3C` | `Overridable::getFinalOverride` |
| `0x0068C26D` | `Object::getSpecialPowerModule(template)` |
| `0x0068DF46` | `Object::hasScience` |
| `0x0068E5A3` | `Object::doSpecialPower` (targetless) |
| `0x0068E67A` | `Object::doSpecialPowerAt*` |
| `0x0071EFA2` | `ControlBar::findCommandSet(AsciiString*)`, `ret 4` |
| `0x0071111A` / `0x007111E5` | `appendObjectIDArgument` / `appendIntegerArgument` |
| `0x00710C9E` | `GameMessage::getArgument(i)` |
| `0x0076F5DB` | `AIGroup::doSpecialPower` |
| `0x0076F5FF` | its `and eax, 0x100000` — the multi-execute test |
| `0x0076F697` | the member loop's head |
| `0x0076F6DA` | its per-member gate call — **hook A** |
| `0x0076F704` | the loop tail a refused member jumps to |
| `0x0076F746` | the single-member gate call, left stock |
| `0x0076FE16` | the engine's own object → command set → button walk |
| `0x0077097E` | `AIGroup::doSpecialPowerAtLocation` / `...AtObject` |
| `0x007709BD` | its `and eax, 0x100000` |
| `0x00770B67` | its per-member gate call — **hook B** |
| `0x00770BD3` | its single-member gate call, left stock |
| `0x0077A42C` | the `MSG_DO_SPECIAL_POWER` dispatcher case |
| `0x0077D087` | the `0x40D..0x418` case table |
| `0x0080C837` | `CommandSet::getCommandButton(i)`, unchecked, `ret 4` |
| `0x0082D5DA` | the targetless per-member precondition gate, `ret 0x14` |
| `0x0082D925` | the targeted one, `ret 0x18` |
| `0x0082DDE1` | the second object → command set → button walk |
| `0x00940435` | the ControlBar's command-button executor |
| `0x0094056C` | its multi-select availability walk |
| `0x0094153C` | the `Command = SPECIAL_POWER` emitter |
| `0x00941BFC` | the click handler that calls the executor |
| `0x00942490` | the model-condition gate, `stdcall(button, object)`, `ret 8` |
| `0x00942733` | `ControlBar`'s availability evaluator |
| `0x00C2BAC8` | the `CommandButton` field-parse table |
| `0x00DA4C88` | the `CommandButton` `Options` name table (32 entries) |
| `0x00DE7744` | `TheControlBar` |
| `0x00DE8BA8` | the singleton both precondition gates are methods of |
| `CommandButton+0x14` | `Command` (`SPECIAL_POWER` = `0x18`) |
| `CommandButton+0x1C` | `Options` |
| `CommandButton+0x44` | `SpecialPower` |
| `CommandButton+0x194` | `EnableOnModelCondition` (`0x4C` bytes) |
| `CommandButton+0x1E0` | `DisableOnModelCondition` (`0x4C` bytes) |
| `SpecialPowerTemplate+0x14` | `m_id` |
| `Object+0x10C` | the model-condition mask |
| `Object+0x438` / `+0x43C` / `+0x440` | the per-object command-set overrides |
