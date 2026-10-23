# War of the Ring reinforcements

A War of the Ring battle often has more armies in it than fight from the start. The rest wait as
**reinforcements**, each behind a banner the player clicks to bring it in. Nothing a map script
could do reached that mechanism: the one action that names it, `CALL_IN_REINFORCEMENTS_WITHOUT_MOVIE`
(543), is a stub (see [`dead-script-actions.md`](dead-script-actions.md)). This page traces the
mechanism end to end, and [`call-in-reinforcements`](../../patches/call_in_reinforcements.py)
gives action 543 a body built on it.

## The roster state

Every army's roster container (`army+0x78`, the object `LIVING_WORLD_FIND_ARMY_ROSTER` returns)
carries a reinforcement state at `+0x2C` (`LIVING_WORLD_ROSTER_STATE`):

| value | name | set by |
|---|---|---|
| 0 | `WAITING` | battle setup, for every battle army not `IN_BATTLE` (`0x00812784`) |
| 1 | `IN_BATTLE` | `detectConflicts`, for every army it seats (`0x0080FE01`) |
| 2 | `SUMMONING` | `roster.summon(frame)` (`0x0080F3C0`) |
| 3 | `READY` | `roster.tickSummon()` (`0x0080F444`) |
| 4 | `CALLED_IN` | `roster.callIn()` (`0x00812563`) |

The transitions each test the state they leave, so none of them can be driven out of order:

```
0080f3c0  cmp  dword [ecx+0x2c], 0        ; summon: only from WAITING
0080f3c4  jne  done
0080f3ca  mov  edx, [ecx+0x30]            ; the delay in frames
0080f3cd  add  edx, eax                   ; + the frame passed in
0080f3cf  mov  dword [ecx+0x2c], 2
0080f3d6  mov  [ecx+0x38], eax            ; start
0080f3d9  mov  [ecx+0x34], edx            ; deadline

0080f444  mov  eax, [TheGameLogic]
0080f449  mov  eax, [eax+0x40]            ; the logic frame
0080f44c  cmp  eax, [ecx+0x34]
0080f44f  jb   done
0080f451  cmp  dword [ecx+0x2c], 2        ; tick: only from SUMMONING
0080f457  mov  dword [ecx+0x2c], 3

00812563  cmp  dword [ecx+0x2c], 3        ; call in: only from READY
00812567  jne  done
0081256e  mov  dword [ecx+0x2c], 4
00812575  call LIVING_WORLD_ARMY_DEPLOY   ; (0, 0, 0)
```

`WAITING` is also the resting state of every army that is in no battle at all, so the state alone
does not say an army belongs to this one. The battle's own list does: the army ids at
`TheGameLogic+0x184` (the battle bridge), `+0x14 .. +0x18`, which battle setup and
`LIVING_WORLD_BATTLE_PRIMARY_ARMY_ID` both walk.

## The banner

The banner button is a Flash callback. `AptBannerUI::OnBttnBanner` (`0x00616443`) is registered
under that name with `TheAptPlayer` at `0x00617026`, and resolves its argument to a banner entry
for `0x006163C9`:

```
006163d9  cmp  byte [esi+0x18], 0         ; already pressed through
006163df  mov  eax, [esi+0xc]             ; banner state
006163e2  test eax, eax
006163e4  jne  ...
006163ee  push 0x45e                      ; MSG_SUMMON_REINFORCEMENTS
006163f6  push [esi+4]                    ;   (army id)
00616402  cmp  eax, 2
00616405  jne  done
00616410  call 0x00625DA7                 ; the roster's +0x18 string
0061641c  call 0x007598B7                 ;   to TheScriptEngine
00616429  push 0x45f                      ; MSG_CALL_IN_REINFORCEMENTS
00616436  push [esi+4]                    ;   (army id)
0061643b  mov  byte [esi+0x18], 1
```

The banner's own state is not stored separately. Every update it reads the roster's through
`LIVING_WORLD_BATTLE_ARMY_STATE` (`0x0080FE9C`, which answers 1 for an unknown id) and folds it at
`0x00616546`: roster `0 -> 0`, `2 -> 1`, `3 -> 2`, anything else `-> 3`. So whatever moves the
roster moves the banner.

## The messages

`GAME_LOGIC_DISPATCH_MESSAGE` reaches both through its second-level table (index byte
`0x0077D1E3`, targets `0x0077D127`, base `0x437`). Each takes one integer, the army id:

```
0077cf63  call GAME_MESSAGE_GET_ARGUMENT_DATA   ; MSG_SUMMON_REINFORCEMENTS
0077cf6d  mov  ecx, [TheGameLogic]
0077cf73  call 0x00625DC8                       ; bridge.summon(id) -> 0x0080FEB2

0077cf7a  call GAME_MESSAGE_GET_ARGUMENT_DATA   ; MSG_CALL_IN_REINFORCEMENTS
0077cf84  mov  ecx, [TheGameLogic]
0077cf8a  call 0x00625DD3                       ; bridge.callIn(id) -> 0x00812875
```

`bridge.summon` passes `TheGameLogic+0x40`, the current frame, to `roster.summon`; `bridge.callIn`
calls `roster.callIn`.

## The AI, and a dead auto-summon

The AI does not go through messages. `0x009A0426`, in the AI module beside `AI_PRODUCER_PICKER`
and reached from the update at `0x009A1196`, walks its player's armies and, for each whose roster
is `READY`, calls `bridge.callIn` directly (`0x009A04B2`). That is the precedent for calling one in
from logic code: it runs on every machine alike, so it needs no message.

`0x0081257B` is one step of a complete auto-summon: `WAITING` logs `"Auto-Summoning army %d into
battle"` and summons, `SUMMONING` ticks, `READY` calls in. No direct branch and no dword in the
image reaches it. It is most likely what is left of BFME1's `RegionReinforcements` `AutoSummon`
(see [`bfme1-act-verbs.md`](bfme1-act-verbs.md)).

## The patch

`call-in-reinforcements` points action 543's jump-table slot at a cave. The action takes the
army's overworld `ScriptingName`, the one `SpawnArmy` gives it, and:

1. refuses an empty name, which `AsciiString::compare` would match against every unnamed army;
2. finds the army with `LIVING_WORLD_FIND_ARMY_BY_NAME`, and its roster at `+0x78`;
3. requires the roster's id (`+0x1C`) to be in the battle's army list, so an army elsewhere on
   the board is never deployed onto this map;
4. requires the state to be `WAITING`, `SUMMONING` or `READY`, the three a banner still offers;
5. sets `READY` and calls `roster.callIn()`, which sets `CALLED_IN` and deploys.

It skips both the countdown and the script-engine handoff of the banner's second click, which is
the "without movie" of the action's name. A banner clicked afterwards does nothing: the roster is
`CALLED_IN`, which neither `summon` nor `callIn` acts on, and the banner already reads it as gone.

## Still unknown

- What the script-engine call on the banner's second click does with the roster's `+0x18` string
  (`0x007598B7`). The name suggests the arrival movie.
- Battle setup's other branch, taken when `[TheLivingWorldLogic+0xB0]+0x0C` is non-zero
  (`0x00812760`), deploys every army at once and never resets states to `WAITING`. The action finds
  nothing to call in there, by construction.
- Where the integer behind the summon delay (`0x0080F475`, scaled by `0x00D9F618`) comes from.
  `SecondsPerReinforcement` (`campaign+0x44`) is the obvious candidate.
