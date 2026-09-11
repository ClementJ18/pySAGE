# Ranged units walk onto their target instead of stopping at weapon range

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000`. Read from a clean `game.dat` (11,346,944 bytes); every site quoted here is
byte-identical in the repo's patched `game.dat` and in a retail `game_backup.dat`.

**Status: static-verified only.** Every claim below carries the instruction it is read from, but
nothing here has been confirmed against a running game. Treat the causal chain as a reading of the
machine code, not as an observed behaviour, until someone watches it in `sage_live`.

## The short answer

`AIAttackApproachTargetState` has two ways to end. One of them checks weapon range. That one is
gated behind a flag which the state's own `computePath` guarantees is off.

`computePath` (`0x00749A3E`) ends an ordinary attack order by calling `0x00663802` — the setter
that moves toward an **object**:

```
00749c89  push eax                  ; &pos, the victim's own position
00749c8a  push dword ptr [edi+0x74] ; the victim's ObjectID
00749c8d  call 0x00663802           ; goal = that object
```

That setter stamps `AIUpdate+0x3B2` with 1:

```
0066386c  mov  dword ptr [ebx+0x144], eax   ; m_goalObjectID
00663872  mov  byte  ptr [ebx+0x3b2], 1     ; the goal is an object
```

and the first thing `updateInternal` (`0x00749D46`) does each frame is turn that byte into the
permission to stop:

```
00749d83  cmp  byte ptr [edi+0x3b2], 0
00749d8a  sete al                          ; only when the goal is a *position*
00749d8d  cmp  byte ptr [esi+0x71], 0
00749d91  mov  byte ptr [esi+0x6e], al
```

`[state+0x6E]` is the first term of the in-range exit, so with an object goal that exit is dead:

```
00749f1a  cmp  byte ptr [esi+0x6e], 0
00749f1e  je   0x00749f4b                  ; always taken -> skip the range check entirely
00749f20  cmp  dword ptr [ebp-8], 0        ; a weapon
00749f26  cmp  byte  ptr [ebp-2], 0        ; ... and the target in range
```

The unit therefore has no reason to stop at range. It keeps following a path whose destination is
the target's own body, and it stops when the locomotor runs out of path — that is, when it arrives
on top of the target.

## The state

| | |
|---|---|
| class name string | `0x00C28CB8` `"AIAttackApproachTargetState"`, returned by the getter at `0x007443BA` |
| vtable | `0x00C28C70`, installed by the constructor at `0x00744328` |
| `update` (vtable `+0x18`) | `0x0074A29F`, a wrapper around `updateInternal` |
| `updateInternal` | `0x00749D46` |
| `computePath` (vtable `+0x44`) | `0x00749A3E` |
| `onEnter` (vtable `+0x10`) | `0x0074E6CE` |

`computePath` is named by its own debug trace, `"CritterDesync: ComputePath10"` at `0x00C28770`,
pushed at `0x00749A5C`.

Instance layout, read from the two functions above:

| offset | what |
|---|---|
| `+0x20` | the goal position handed to the pathfinder |
| `+0x4C` | the victim's position when the path was last computed |
| `+0x58` | the unit's own position when the path was last computed |
| `+0x64` | the frame `computePath` last ran |
| `+0x68` | the frame a blocked unit may retry on |
| `+0x6E` | may this state end because the target is in range |
| `+0x71` | the unit is blocked and waiting |

## Return codes

`updateInternal` returns `-1`, `-2`, or a non-negative sleep count. `-1` is success: the debug
string `"%i AIAttackApproachTargetState success [3]"` (`0x00C2A02C`) is printed at `0x0074A100`
immediately before `jmp 0x00749F12`, and `0x00749F12` is `or eax, 0xffffffff`. `-2` is the failure
arm — it is what the state returns when the victim is gone (`0x00749D7B`), when the victim carries
object status `0x33` (`0x00749DE3`), and when the target has run past `StopChaseDistance`
(`0x0074A0DF`). Non-negative values are frame counts to sleep.

So there are exactly two ways for the approach to succeed, both returning `-1`.

## Exit one: the target is in range

`0x00749F1A`. It needs all six of:

1. `[state+0x6E]` — the goal is a position, or the unit is in its blocked wait.
2. a current weapon (`0x0068B58C` at `0x00749DA5`).
3. `[ebp-2]`, the in-range answer. For a target facing away it comes from `0x006CC07C` against a
   position led by `victimSpeed * 4.0` (`0x00BD88C0`); otherwise from `WEAPON_TARGET_IN_RANGE`
   (`0x006CC653`) at `0x00749EDB`.
4. the `AIUpdate` virtual at `+0x224` (`0x00749F31`).
5. `0x0070C55D` on the victim answering false.
6. `[ebp-3]`, from `hasClearLineOfFire` at `0x00744AAA`.

Term 1 is the one that never holds. Term 6 is a near-tautology: `0x00744AAA` returns true
immediately unless the attacker has KindOf `ATTACK_NEEDS_LINE_OF_SIGHT` (`[template+0x10F] & 8`)
or KindOf `CAN_SHOOT_OVER_WALLS` (`[template+0x122] & 0x40`), so most units skip the trace at `0x006616AC` entirely.

`[state+0x6E]` is forced **off** for melee, which is correct and is the only place the engine
distinguishes the two:

```
00749dbe  mov  ecx, dword ptr [eax+4]   ; the WeaponTemplate
00749dc1  call 0x00441b59               ; return template->[+0x125], i.e. MeleeWeapon
00749dc6  test al, al
00749dc8  je   0x00749dce
00749dca  mov  byte ptr [esi+0x6e], 0
```

`WeaponTemplate+0x125` is `MeleeWeapon`, from the weapon field table at `0x00C16DD8` row 45. The
engine takes the trouble to switch this off for melee, then hands ranged weapons the same
behaviour anyway because the object goal has already zeroed the byte one branch earlier.

`[state+0x6E]` is forced **on** in one case, `[state+0x71] != 0` — the blocked wait. That is why a
ranged unit that cannot physically reach its target does eventually stop and shoot: not because it
is in range, but because it gave up moving.

## Exit two: `computePath` returns false

`0x0074A0E9` calls the vtable `+0x44` slot; false there is the "success [3]" path. `computePath`
returns false in exactly one place, `0x00749BA7`, which needs `0x00746058` to answer true. That
function is not a range test. It reads:

```
007460e9  ...            ; A = the attacker's locomotor max speed  (0x006624C9)
007460f7  ...            ; B = the victim's current speed          (0x0068B34C)
00746107  fcompi st(1)
0074610b  jae  0x00746164 ; B >= A            -> false
00746112  mulss xmm0, dword ptr [0xbd83d4]    ; A * 0.1
0074611a  comiss xmm0, dword ptr [ebp-8]
0074611e  ja   0x00746164 ; A*0.1 > B         -> false
00746120  ...            ; dot(victim facing, victim - self)
00746162  jbe  0x00746168 ; dot >= 0          -> true
```

True means: *the target is moving away from me, at between 10% and 100% of my own top speed.* It is
a don't-chase-a-runner rule. Against a stationary target — the case the player complains about — it
is false, and `computePath` keeps returning true frame after frame.

## Where the goal comes from

`computePath` sets the goal to the victim's body and never adjusts it for range:

```
00749b61  lea  edi, [ebx+0x20]   ; the goal position
00749b64  lea  esi, [ebx+0x4c]   ; the victim's position, copied in at 0x00749B1A
00749b67  movsd / movsd / movsd
```

The point itself comes from `0x0068C9AC` on the victim, which copies `Object+0x38` outright when
the object's transform flag is set. There is no stand-off, no subtraction of weapon range, and no
use of the unit's own geometry.

The one function in this path that does know about weapon range is `0x006FB754`, on the pathfinder
(`TheAI+0x10`, `TheAI` = `0x00DE4B40`). It measures a ring:

```
006fb773  movss xmm0, dword ptr [0xc041f8]   ; 150.0, the floor
006fb795  call 0x006ca8bd                    ; the weapon's attack range
006fb7aa  jbe  0x006fb7b6
006fb7b1  movss dword ptr [ebp+8], xmm0      ; spacing = max(150.0, range)
```

and walks the eight cells at that spacing around the victim looking for one that works. But it
returns only a `Bool` — it never writes `[state+0x20]` — and it is called only when the attacker
has `ATTACK_NEEDS_LINE_OF_SIGHT`:

```
00749b4c  test byte ptr [eax+0x10f], 8   ; KindOf ATTACK_NEEDS_LINE_OF_SIGHT
00749b53  mov  byte ptr [ebp-1], 0
00749b57  jne  0x00749b5d
00749b59  mov  byte ptr [ebp-1], 1       ; without it, skip the ring entirely
00749b6a  jne  0x00749b8e
```

KindOf index 59, byte `+0x7` bit `0x08` of the array based at `template+0x108`, per
`explore.py enum KindOf`.

So the only ranged units the engine ever tries to place at weapon range are the ones flagged
`ATTACK_NEEDS_LINE_OF_SIGHT`, and even for those the placement decides a boolean, not a
destination.

## The knobs that exist, and what they actually do

`updateInternal` reads exactly two `AIUpdate` module fields, both from the module field table at
`0x00C0F530`:

| field | offset | where it is read | effect |
|---|---|---|---|
| `StopChaseDistance` | `ModuleData+0x20` | `0x0074A036` | if the straight-line distance to the victim exceeds it, return `-2` and stop |
| `StandGround` | `ModuleData+0x24` | `0x00749F6B` | with a ground/rubble locomotor surface and the target out of range, set the blocked wait instead of moving |

`StopChaseDistance` is scaled by the unit's mood before the comparison, and only for
player-controlled units:

```
0074a08d  test al, 1                       ; the controller bit from 0x00664D7E
0074a08f  jne  0x0074a0d6                  ; AI-controlled -> no scaling
0074a091  and  eax, 0x1f00                 ; the mood bits
0074a096  cmp  eax, 0x100                  ; sleep      -> 0.0
0074a09d  cmp  eax, 0x800                  ; alert      -> AIData AlertRangeModifier      (+0x4C)
0074a0a4  cmp  eax, 0x1000                 ; aggressive -> AIData AggressiveRangeModifier (+0x50)
```

Neither field shortens the approach. `StopChaseDistance` only aborts it, and it aborts the whole
attack rather than converting it into a shot. `StandGround` is the closest thing the data offers to
"stop and shoot", and it works by refusing to move at all.

`ContinueAttackRange` and `MinimumAttackRange` (weapon table `0x00C16DD8`, offsets `0x148` and
`0x18`) are read elsewhere in the weapon code and play no part in this state.

## EA knew

The stock weapon data carries the acknowledgement, on 17 `Weapon` blocks in the Edain corpus alone:

```
MeleeWeapon = Yes ; Sorry, stand off doesn't work.  This is just a melee weapon.
```

Which is the same conclusion reached from the other end: the stand-off does not work, and the
workaround shipped in the data was to declare the weapon melee so nobody expected one.

## Why a group makes it obvious

A group attack order is not a group operation. `AIGroup::groupAttackObject` walks its members and
issues an individual `aiAttackObject` to each one:

```
007721b5  lea  ecx, [esi+0x20]     ; the member's AIUpdate state machine
007721c5  call 0x0066c536          ; aiAttackObject
```

`0x0066C536` has 27 callers; `0x007721C5` and `0x00772230` are the two inside the AIGroup
translation unit, identified by the assert string `0x00C2E468`
(`E:\Builds\BFME2X\...\GameLogic\AI\AIGroup.cpp`).

So every member runs the chain above independently, each pathing to the same body. The behaviour is
identical for one unit; a group just makes it legible, and adds the mutual pushing of N units all
converging on one destination cell.

## The fix

`ranged-stand-off`, in [`patches/experimental/ranged_stand_off.py`](../patches/experimental/ranged_stand_off.py),
rewrites the `sete al` at `0x00749D8A` as `mov al, 1` so an object goal may stop at range too.
Three bytes, one site, no cave. Applying it to a clean `game.dat` changes exactly the three bytes
`0f 94 c0` -> `b0 01 90` at file offset `0x349D8A` and nothing else, which is what
`sage-patch verify` and the test suite assert.

It is unconditional because it does not have to be conditional: the `MeleeWeapon` clear at
`0x00749DCA` runs twelve bytes later and still zeroes the byte for melee. The engine already drew
the line; the patch only lets it reach the range exit. The cost is that `MeleeWeapon` defaults to
`No`, so a melee weapon that omits it now stops at its own `AttackRange`. In the Edain corpus 915
of 3,552 `Weapon` blocks declare `MeleeWeapon = Yes` and 303 declare `No`; the rest leave it unset,
and most of those are projectile and nugget weapons that never drive an approach.

The two alternatives, for the record. **Give the goal a stand-off** — pull `0x00749B67` back along
the victim-to-self vector by the weapon's range — is more correct in principle and is roughly what
`0x006FB754` already measures, but it needs a cave and has to cope with the ring being blocked.
**Data only** — `StandGround = Yes` on the `AIUpdate` — gets the refusal-to-close behaviour with no
patch at all, at the cost of the unit refusing to reposition.

**Still unverified in play.** The patch is a reading of this document and its tests are written
from the same reading, so a wrong reading passes both.

## Open questions

- `AIUpdate+0x3B2` is read in exactly three places and nowhere else: `0x00669049`, `0x00749D83`,
  and the accessor `0x007412B5` (`mov al, [ecx+0x3b2]; ret`), which has no caller and no vtable
  slot — it is dead. Of the nine writes, `0x00663872` (set, in `setGoalObject`) and `0x00667F5D`
  (cleared, in `setGoalPosition`) were decoded; the other seven were not, so "1 means the goal is
  an object" is a two-point reading rather than a survey.
- The `AIUpdate` virtual at `+0x224` and `0x0070C55D`, terms 4 and 5 of exit one, are unread. They
  are downstream of the term that already fails, so they were left black. They are what decides
  whether the patched exit actually fires as often as it should.
- `0x009188EB` is `xor al, al; ret` and is called directly on a `WeaponTemplate` at `0x00749F03`,
  `0x00749BCD` and `0x00744AD4`, making three branches statically unreachable — including the
  `setAdjustDestination` arm of `computePath` at `0x00749BD6`. Whether that is compiler folding of
  a `return FALSE` accessor or a feature switched off before shipping is unknown.
- `AIAttackPursueTargetState` (vtable `0x00C28D90`, `update` `0x0074AF91`, `computePath`
  `0x00746C69`) is a separate state that sets a **position** goal through `0x00667ED1` and never
  reads `+0x3B2`, so the patch neither helps nor harms it. Whether pursuit overshoots for reasons
  of its own has not been looked at, and it is the state that takes over once the target moves.

## Addresses

| VA | what |
|---|---|
| `0x00C28C70` | `AIAttackApproachTargetState` vtable |
| `0x00749D46` | its `updateInternal` |
| `0x00749A3E` | its `computePath`, the vtable `+0x44` slot |
| `0x00749D83` | the `sete` that decides whether the state may stop at range |
| `0x00663802` | `AIUpdateInterface::setGoalObject(id, pos)` — sets `+0x3B2` |
| `0x00667ED1` | `AIUpdateInterface::setGoalPosition(pos, flag)` — clears `+0x3B2` |
| `0x00746058` | the don't-chase-a-runner test |
| `0x00744AAA` | `hasClearLineOfFire(self, victim, weapon)` |
| `0x00441B59` | `WeaponTemplate::isMeleeWeapon`, the byte at `+0x125` |
| `0x006FB754` | the pathfinder's weapon-range ring probe |
| `0x0066C536` | `aiAttackObject`, what a group order issues per member |
| `0x00DE4B40` | `TheAI`; `+0x10` the pathfinder, `+0x18` the `AIData` |
