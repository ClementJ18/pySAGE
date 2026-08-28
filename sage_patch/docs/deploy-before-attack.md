# `MustDeployToAttack` does not gate an attack the AI starts

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000`. Read from a clean `game.dat` (11,346,944 bytes).

**Status: runtime-verified.** Every claim carries the instruction it is read from, the section
"What the running game says" reads the failing case out of a paused match, and the finished patch
was confirmed in a live game: `MustDeployToAttack` siege now deploys before its first shot, whether
it acquires while idle, while guarding, or under an attack-move.

## The short answer

`MustDeployToAttack` is read in exactly one place that decides anything — the `READY_TO_MOVE` arm
of `DeployStyleAIUpdate::update` — and that arm is reached only once the module has a **recorded
command** to resolve:

```
0089295d  test bl, bl                     ; guarding at its post with nothing to shoot
0089295f  jne  0x00892975
00892961  cmp  byte ptr [esp+0x11], bl    ; is the recorded target in range
00892965  je   0x00892998
00892967  cmp  byte ptr [esp+0x12], bl    ; was a range question asked at all
0089296b  je   0x00892998
0089296d  mov  eax, [esi-0xc]             ; the ModuleData
00892970  cmp  byte ptr [eax+0x6f], bl    ; MustDeployToAttack
00892973  je   0x00892998                 ; No -> stay packed and shoot on the move
00892975  push 1
00892977  lea  ecx, [esi-0x10]
0089297a  call 0x008921e3                 ; setMyState(DEPLOY)
```

`[esp+0x12]` is set only by the three branches that resolve a **recorded** command. Nothing is
recorded unless `aiDoCommand` recorded it, so only an order that arrived as an `AICommandParms`
can ever make the unit stand up.

**Almost nothing the engine starts on its own becomes one.** The mood-target picker at
`0x0066844A` has nine callers, and they do not all attack the same way:

| acquire site | AI state | how it attacks | reaches `aiDoCommand`? |
|---|---|---|---|
| `0x00755534` | `AIIdleState` | `aiAttackObject(t, 0x7FFFFFFF, CMD_FROM_AI)` | **yes** |
| `0x0075587F` | `AIInternalMoveToState` | `machine->setGoalObject(t)` + `setState(0x0A)` | no |
| `0x0075003B` | `AIFollowPathAsTeamState` | same | no |
| `0x00755E5B` | `AIAttackFollowWaypointPathState` | same | no |
| `0x0074A317`, `0x0074A4CD` | `AIAttackApproachTargetState` | `0x006622C7` → the attack machine | no |
| `0x0074AFC8` | `AIAttackPursueTargetState` | same | no |
| `0x0076B3FC` | `GiantBirdAttackMoveToState` | same | no |
| `0x00892621`, `0x00892641` | the module's own `update` | — | — |

The state each site belongs to is fixed by the vtable that points at the enclosing function: the
slot two dwords ahead of the `update` slot is a `mov eax, <string>; ret` getter, and the string is
the class name (`AIIdleState` at `0x00C284AC`, and so on).

`AIInternalMoveToState` is the one that matters in practice. It is the state a unit is in **while
moving**, including the move inside an attack-move, and its acquire is:

```
0075587f  call 0x0066844a               ; pick a mood target
00755884  mov  edi, eax
00755886  test edi, edi
00755888  je   0x007558b7
00755891  mov  ecx, [ebx+0x54]          ; the AI's own state machine
00755896  push edi
00755897  call dword ptr [eax+0x38]     ; setGoalObject(target)
0075589f  push 0xa
007558a1  call dword ptr [eax+0x20]     ; setState(AI_ATTACK_OBJECT)
```

No `AICommandParms` is built, so the module hears nothing, `[esp+0x12]` stays zero, and a
`MustDeployToAttack = Yes` trebuchet ordered across the map — or given an attack-move — fires
packed.

And the survey above is still not the whole story, which is what the running game had to settle.

## What the running game says

Read out of a paused match with `sage_live` (`ReadProcessMemory` only). Three `EvilmenTrebuchet`s
were on the field; 376 was the reported case — `FIRING_A`, `ATTACKING`, and **no `DEPLOYED`**
model condition:

| | 376 (firing, packed) | 377 (idle) | 378 (moving) |
|---|---|---|---|
| module vtable | `0x00C63230` | same | same |
| `MustDeployToAttack` (`ModuleData+0x6F`) | 1 | 1 | 1 |
| `m_state` (`+0x578`) | 0 `READY_TO_MOVE` | 0 | 0 |
| recorded flags (`+0x594..0x596`) | `00 00 00` | `00 00 00` | `00 00 00` |
| attack machine (`+0x20C`) | **NULL** | NULL | NULL |
| `AIStateMachine` (`+0x30`) goal object | 0 | 0 | 0 |
| `m_currentVictimID` (`+0x40`) | **1182** | 0 | 0 |

So the module *was* packed with `MustDeployToAttack` set and nothing recorded — and every question
`update` knows how to ask came back empty. The unit's state was two machines down:

```
AIStateMachine  (Object+0x260 -> AIUpdate, +0x30)  current state = AIGuardState
  AIGuardState                          (+0x20)  ->  AIGuardMachine
    AIGuardMachine   state id 6,  goal object 1182  ->  AIGuardInnerState
```

A stationary unit sits in **`AIGuardState`** — the stance system puts it there — and its guard
machine acquires and attacks from `AIGuardInnerState`. That machine is not one of the attack-machine
slots at `+0x20C`, so `getActiveAttackMachine` answers -1, and it is not the top-level machine's
goal object either. Object 377, guard-*idle* in the same structure, differs only in its inner state
(`AIGuardIdleState`) and in `m_currentVictimID` being zero.

`AIUpdateInterface::m_currentVictimID` at `+0x40` is the field that separates them. Across all 581
objects with an `AIUpdate` in that match it produced **no false positives** — never set on an object
without an attacking model condition — and its misses were all melee creature templates
(`EvilmenBeastmaster`, `EvilmenBuffalo`, `EvilmenPanther`, `EvilmenRazorbeak`) and peasants, none of
which is a `DeployStyleAIUpdate` user.

## The module

`DeployStyleAIUpdate`, `sizeof` `0x59C`, constructor `0x00892013`, vtable `0x00C63230`. The
`ModuleData` (`0x00654EA3`, `sizeof` `0x74`) is the one the [module reference](module-reference.md)
lists; `MustDeployToAttack` is the byte at `+0x6F`, defaulting to `1`:

```
00654ec5  mov  byte ptr [esi+0x6f], 1     ; MustDeployToAttack defaults to Yes
```

and its getter is the whole of `0x00891ED4`, which also fixes the module→`ModuleData` link at `+4`:

```
00891ed4  mov  eax, [ecx+4]               ; the ModuleData
00891ed7  mov  al,  [eax+0x6f]            ; MustDeployToAttack
00891eda  ret
```

The constructor also plants four secondary vtables, and one of them is what makes the module's
`aiDoCommand` reachable at all:

```
00892029  mov  dword ptr [esi],      0xc63230   ; UpdateModule
0089202f  mov  dword ptr [esi+0x0c], 0xc61fb0
00892036  mov  dword ptr [esi+0x10], 0xc63224   ; slot 0 = update (0x0089251C)
0089203d  mov  dword ptr [esi+0x20], 0xc63220   ; slot 0 = 0x00891F87
```

`0x00891F87` is the adjustor thunk every `AIUpdateInterface` command entry goes through:

```
00891f87  push 0                          ; "not a replay"
00891f89  push dword ptr [esp+8]          ; the AICommandParms
00891f8d  add  ecx, -0x20                 ; back to the module
00891f90  mov  eax, [ecx]
00891f92  call dword ptr [eax+0x268]      ; DeployStyleAIUpdate::aiDoCommand
```

so `aiAttackObject` (`0x0066C536`, called on `module+0x20`) does reach the derived override —
which is why the player's own attack order deploys, and why `AIIdleState`'s acquire would too.

### State

`m_state` is the dword at `+0x578`, written by `setMyState` (`0x008921E3`) before it switches on the
new value:

```
008921fe  mov  dword ptr [esi+0x578], ebx  ; the new state, then switch(ebx)
```

| value | what `setMyState` does for it | name |
|---|---|---|
| 0 | clears the deploy model condition, drops the timer | `READY_TO_MOVE` |
| 1 | `aiIdle(CMD_FROM_AI)`, condition `0x5E`→`0x60`, timer = `UnpackTime`, animation `"Deploy"` | `DEPLOY` |
| 2 | condition `0x60`→`0x64`, enables the turret when `TurretsFunctionOnlyWhenDeployed`, replays a held command **if `+0x594` is set** | `READY_TO_ATTACK` |
| 3 | `aiIdle(CMD_FROM_AI)`, timer = `PackTime`, animation `"Undeploy"` | `UNDEPLOY` |
| 4 | waits for the turret to recentre, then `setMyState(3)` | pre-pack turret centring |

The two animation names are the literals at `0x00C6349C` (`"Deploy"`) and `0x00C634A4`
(`"Undeploy"`), pushed by the state-1 and state-3 arms — which is what fixes 1 and 3 rather than
leaving them inferred from position.

The `aiIdle(CMD_FROM_AI)` at the head of state 1 (`0x008923FF`) is the load-bearing one: it is what
takes an attack in progress off the base state machine while the unit stands up.

### How a player-ordered attack actually resumes

Worth writing down, because the fix relies on it. A right-click on an enemy is recorded by
`aiDoCommand` (`+0x595`, target `ObjectID` at `+0x584`) and, because `m_state` is 0, **forwarded**
to the base state machine as well. `update` then resolves it, finds it in range, and calls
`setMyState(DEPLOY)` — whose `aiIdle` cancels the attack it just forwarded. When the deploy timer
expires, `setMyState(READY_TO_ATTACK)` replays the held command only when `+0x594` is set
(`0x00892376`), and an attack-object order does not set `+0x594`. Nothing replays it.

The unit resumes because it is now idle and deployed, so `AIIdleState` acquires the same target
again — this time with `m_state == 2`, where the module leaves it alone. Auto-acquisition is the
resume mechanism for the stock path too.

### The recorded command

Everything `aiDoCommand` records lives past `+0x594` and is cleared as a block by `0x00891CEB`:

| offset | meaning |
|---|---|
| `+0x4A8` | the saved `AICommandParms` — stored by `0x0075307D`, restored by `0x0075315B`, first dword `-1` when empty |
| `+0x56C` | the command was forwarded to the base state machine |
| `+0x56D` | a saved command is waiting to be replayed (`0x00891F9B` replays it) |
| `+0x574` | recomputed every update: 0 stopped, 1 moving, 2 target in range, 3 target out of range |
| `+0x578` | `m_state` |
| `+0x57C` | the frame the current deploy/pack timer expires on |
| `+0x580` | the `ObjectID` the module is tracking |
| `+0x584` | the `ObjectID` of a recorded attack-object command |
| `+0x588` | the `Coord3D` of a recorded attack-position command |
| `+0x594` | recorded: an attack-ish command with no explicit target |
| `+0x595` | recorded: attack object |
| `+0x596` | recorded: attack position |
| `+0x597` | the recorded command was `0x1E` (guard position) |
| `+0x598` | the module has re-issued an attack of its own |
| `+0x599` | a deploy has been requested (`0x00891D3B`) |
| `+0x59A` | a pack has been requested (`0x00891D62`) |

### `update` — `0x0089251C`

**`update` biases `esi` to `this + 0x10` for its whole body**, which is the single most important
thing to hold on to when reading it: `[esi-0x10]` is the module, `[esi-0xc]` the `ModuleData`,
`[esi+0x568]` is `m_state` (`+0x578`) and `[esi+0x584]`/`[esi+0x585]`/`[esi+0x586]` are the three
recorded-command flags (`+0x594`/`+0x595`/`+0x596`).

```
0089251c  push ecx / push ecx / push ebx / push ebp / push esi
00892521  mov  esi, ecx                   ; esi = this ... then +0x10 by every displacement
00892523  mov  ebp, [esi-8]               ; the owning Object
00892527  xor  edi, edi
00892529  push edi
0089252c  call 0x0068b58c                 ; the weapon
00892531  mov  ebx, eax
00892535  mov  byte ptr [esp+0x11], 0     ; "the target is in range"
0089253a  mov  byte ptr [esp+0x12], 0     ; "a range question was asked"
0089253f  je   0x008926e7                 ; no weapon: nothing to resolve
00892545  cmp  byte ptr [esi+0x586], 0    ; <-- the hook: recorded attack position?
0089254c  je   0x00892578                 ;     no -> try the recorded attack object
0089254e  ...                             ;     yes -> range-test the position
```

Every arm of the resolution rejoins at `0x008926E7` with `edi` holding the resolved target (zero
when there is none) and `[esp+0x11]`/`[esp+0x12]` holding the range answer. The state switch is at
`0x00892750`, dispatching on `m_state`: 0 → `0x0089292A`, 1 → `0x008928C6`, 2 → `0x008927CB`,
3 → `0x008927AF`, 4 → `0x0089277E`.

## The patch

Replace the nine bytes at `0x00892545` with `jmp rel32` + four `nop`, into a cave that runs
**before** the resolution and deploys the unit when all of:

* neither `+0x595` nor `+0x596` is set — no *targeted* order is recorded, so this is not one the
  `READY_TO_MOVE` arm resolves and deploys for by itself (see "Why `+0x594` is not in that list"),
  and
* `m_state == READY_TO_MOVE` — packed, and not already on its way up, and
* `ModuleData->MustDeployToAttack` is set, and
* `AIUpdateInterface::getCurrentVictim` (`0x00668303`) returns an object, and
* `Weapon::isTargetObjectInRange` (`0x006CC653`) says that object is in range.

Then `setMyState(DEPLOY)` and jump to `0x008926E7`. Anything else falls into the reproduced stock
test and reaches `0x00892578` or `0x0089254E` exactly as before.

`getCurrentVictim` is the whole of `0x00668303`:

```
00668303  mov  eax, [ecx+0x40]            ; m_currentVictimID
00668306  test eax, eax
00668308  je   0x00668317                 ; -> NULL
0066830a  mov  ecx, [0x00de412c]          ; TheGameLogic
00668310  push eax
00668311  call 0x00449681                 ; findObjectByID
00668316  ret
```

and the field it reads is written by the setter at `0x006682B1`, which stores `victim->id`:

```
006682f3  and  dword ptr [esi+0x40], 0    ; setCurrentVictim(NULL)
006682f9  mov  eax, [eax+0x74]            ; victim->id
006682fc  mov  dword ptr [esi+0x40], eax
```

That setter has **27 call sites** across the idle, move, guard, approach and pursue states — which
is what makes it see every acquire path in the survey above and the guard machine as well. It is
also cleared when the victim dies, by the `onVictimDied` arm at `0x00668280`, so it can never name
a dead object.

The range question is copied verbatim from the shape `update` uses at `0x0089269E`:
`(source Object, victim, 0.0f, 1)` with the weapon in `ecx`, `ret 0x10`.

### Why `+0x594` is not in that list

The first revision required all three recorded flags clear, which read as the conservative choice
and was wrong. `+0x595` and `+0x596` name a target the arm resolves itself — an attack-object id at
`+0x584`, an attack-position `Coord3D` at `+0x588` — and it deploys for both, which is why a
player's right-click has always worked. `+0x594` names **nothing**: it is set for the attack-move,
hunt and guard forms, and its arm at `0x008925C2` looks for a target in only three places —
`getActiveAttackMachine`, the top-level machine's goal object, and the tracked id at `+0x580`.

A second reading of the paused match found a trebuchet with exactly that shape: `+0x594` set,
`m_state` 0, firing, and all three of those places empty (`-1`, `0`, `0`). It fell out of the stock
arm at `0x0089296B` with `[esp+0x12]` still zero and out of the cave on the recorded-flag test, so
it never deployed at all. `m_currentVictimID` held `1182` the whole time.

### Why not the attack machine

The obvious-looking pair `getActiveAttackMachine` (`0x0066243F`) / `getAttackMachineTarget`
(`0x006622E6`) is what `update` itself reaches for at `0x008925D7`, so it looks like the sanctioned
way to ask. It is wrong here: the slots at `+0x20C` were **null** on the firing trebuchet. Only
some attack forms allocate one; an attack running inside the guard machine does not.

### Why it writes nothing to the module

Synthesising a recorded command (`+0x595` plus a target `ObjectID`) would work on the frame it is
written, and then never be cleared: `0x00891CEB` only runs when a real command arrives, so the
first auto-acquired target would leave a flag behind that blocked every later one. Calling
`setMyState(DEPLOY)` and rejoining with nothing resolved keeps the whole thing to one frame — next
frame the same question is asked again from scratch.

### Why the range test

Without it the unit stands up the moment it acquires anything, including a target it first has to
walk half the map to reach, and then makes the trip deployed. `Weapon::isTargetObjectInRange` is
the same question the stock arm asks for a recorded target, so "close enough to shoot" means one
thing in both places. Out of range, the cave declines, the base AI keeps closing, and the question
is asked again next frame.

### Register safety

`ebx` (the weapon), `ebp` (the `Object`), `esi` (the biased `this`) and `edi` (zero) are all live
across the hook and all needed by the code the cave falls back into. `0x0066243F`, `0x006622E6`,
`0x006CC653` and `setMyState` are `__thiscall` and preserve `ebx`, `esi`, `edi` and `ebp`; the cave
writes only `eax`, `ecx` and flags of its own.

### Nothing branches into the displaced bytes

A scan of every branch displacement in `.text` finds no edge into `0x00892546`–`0x0089254D`. The
one apparent hit is at `0x0089258F`, which is the middle of the `call 0x00449681` at `0x0089258D` —
the scanner decodes at every byte offset, so a false positive there is expected and visible.

### What changes in game

A `MustDeployToAttack` unit that acquires a target on its own — idle, on the move, or under
attack-move — now stands up first. The deploy's `aiIdle` takes the attack away, the unpack timer
runs, and the unit re-acquires once `READY_TO_ATTACK` is reached, exactly as it does after a
player-ordered deploy.

`MustDeployToAttack = No` is untouched: the cave reads the same byte the stock arm reads and falls
through when it is zero. So is a unit that is already deployed, already deploying, or already
holding a recorded order.

This changes when a logic-side state machine is told to deploy, so **every peer must run the same
patched binary** and replays do not cross — the same requirement `attack-requires-damage`,
`multi-execute-gate` and `spawn-union` carry. There is **no INI change**: the keyword already
exists and this makes it mean what it says.

## Alternatives that do not work

**Hook `aiDoCommand`'s command-source test.** This is what the patch did first: divert a
`CMD_FROM_AI` attack into the record-and-hold path instead of the bypass at `0x008920D2`. It is a
correct reading of that function and it fixes exactly one acquire path — `AIIdleState`'s — because
that is the only one that builds an `AICommandParms`. A stationary unit is in `AIGuardState`, not
`AIIdleState`, so in practice it fixes nothing.

**Ask the attack machine instead.** The second attempt, and also wrong: see "Why not the attack
machine". It is the question `update` asks, but the guard machine is not one of those slots.

**Stand aside whenever any command is recorded.** The third attempt. It leaves the guarding case —
`+0x594` recorded, nothing resolvable — firing packed. See "Why `+0x594` is not in that list".

**Hook each acquire site.** Seven sites, in six state classes, two different attack idioms. Each
would have to be taught the module's state, and a state class the survey missed stays broken.

**Gate `Object::getAbleToAttackSpecificObject` (`0x0068D6A6`) on the deploy state.** It is the choke
point every acquire and every right-click reaches, so it does stop the firing — and it also stops
the player's attack order being accepted, which is the only thing that would have made the unit
deploy. The unit sits packed forever. Gating it on `cmdSource` instead spares the player's order
but still leaves the unit standing next to an enemy doing nothing, because nothing deploys it.

**Set `OBJECT_STATUS_NO_AUTO_ACQUIRE` while packed.** Cheap and engine-native, but it only silences
the unit; it never deploys. It also cannot tell its own bit from one the template set, so clearing
it on deploy changes a unit that was meant never to auto-acquire.

**Synthesise the recorded command instead of calling `setMyState`.** Tempting, because it puts the
unit on exactly the stock path — but the flag it writes has no owner and nothing clears it. See
"Why it writes nothing to the module".

## Every address this document depends on

| VA | meaning |
|---|---|
| `0x0089251C` | `DeployStyleAIUpdate::update` — vtable `0x00C63224`; biases `esi` to `this+0x10` |
| `0x00892545` | **the hook** — `cmp byte [esi+0x586], 0` + `je 0x00892578` (`80 be 86 05 00 00 00 74 2a`) |
| `0x0089254E` | the recorded-attack-position arm the displaced branch falls through to |
| `0x00892578` | the recorded-attack-object arm the displaced branch jumps to |
| `0x008926E7` | where every arm of the resolution rejoins — the cave's deploying exit |
| `0x0089295D` | `update`'s `READY_TO_MOVE` arm; `0x0089296D` is where it reads `MustDeployToAttack` |
| `0x00892013` | the module constructor; `sizeof` `0x59C`, vtable `0x00C63230` |
| `0x00891F87` | the `+0x20` adjustor thunk — `AIUpdateInterface` command entries reach `+0x268` through it |
| `0x00654EA3` | the `ModuleData` constructor; `MustDeployToAttack` defaults to 1 at `0x00654EC5` |
| `0x00891ED4` | the `MustDeployToAttack` getter — `[this+4]` is the `ModuleData`, `+0x6F` the byte |
| `0x008921E3` | `setMyState`; `0x008921FE` stores the new state at `+0x578`, `0x008923FF` is its `DEPLOY` arm |
| `0x00892376` | `setMyState`'s `READY_TO_ATTACK` arm — replays a held command only when `+0x594` is set |
| `0x00891CAF` / `0x00891F9B` | "is a command held" / replay it |
| `0x00891CEB` | clears the recorded command block (`+0x580`, `+0x584`, `+0x588`, `+0x594`–`+0x59A`) |
| `0x0089209F` | `DeployStyleAIUpdate::aiDoCommand`, `ret 8` — vtable `+0x268` (`0x00C63498`) |
| `0x008920CE` | its command-source test — `CMD_FROM_AI` goes straight to the base state machine |
| `0x00892175` / `0x008921AC` / `0x0089217E` | the stores that set `+0x594` / `+0x595` / `+0x596` |
| `0x00668303` | `AIUpdateInterface::getCurrentVictim` — `m_currentVictimID` at `+0x40`, resolved |
| `0x006682B1` | `setCurrentVictim` — 27 call sites; `0x00668280` clears the id when the victim dies |
| `0x0066243F` | `getActiveAttackMachine` — the running attack machine's index, or -1; null slots on a guard-attacking unit |
| `0x006622E6` | `getAttackMachineTarget(index)` — its target `Object*`, or NULL |
| `0x006622C7` | the sibling that *sets* an attack machine's target — how the approach and pursue states attack |
| `0x00449681` | `findObjectByID` on `TheGameLogic` (`0x00DE412C`), `ret 4` |
| `0x00C27DA0` / `0x00C80680` | the `AIGuardState` and `AIGuardMachine` vtables — how the live walk was anchored |
| `0x006CC653` | `Weapon::isTargetObjectInRange(source, victim, extraRange, flag)`, `ret 0x10` |
| `0x0066C536` | `aiAttackObject(victim, maxShots, cmdSource)` — builds `AICMD_ATTACK_OBJECT` (`0x0B`) |
| `0x005E821A` | `aiIdle(cmdSource)` — builds `AICMD_IDLE` (`5`) |
| `0x0066844A` | the mood-target picker — reads `AutoAcquireEnemiesWhenIdle` at `0x00668598` / `0x006685B0` |
| `0x007553AB` | `AIIdleState::update` — its acquire at `0x00755534` is the only one that reaches `aiDoCommand` |
| `0x00755572` | `AIInternalMoveToState::update` — acquires at `0x0075587F` straight into the state machine |
| `0x0074A29F` / `0x0074A49B` / `0x0074AF91` | the attack-approach and attack-pursue states that re-target through `0x006622C7` |
| `0x00C6349C` / `0x00C634A4` | `"Deploy"` / `"Undeploy"` — what fixes states 1 and 3 |
