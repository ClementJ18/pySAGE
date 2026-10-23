# Routing AI orders through a tunnel network

RotWK 2.01 `game.dat`, ImageBase `0x400000`.

**Status: implemented as `ai-tunnel-routing`**
([`../patches/ai_tunnel_routing.py`](../patches/ai_tunnel_routing.py)). **Runtime-verified for a
skirmish AI's hordes** (§6). Every site below was read from this repo's `game.dat`; the patch
applies, verifies and round-trips through `detect` on it, and its cave runs under unicorn against a
stand-in engine (`tests/sage_patch/test_ai_tunnel_routing.py`). §6 says what a running game showed
and what it has not settled yet.

**The finding in one sentence.** The pathfinder has no notion of a tunnel, but the engine already
holds every piece an order-time reroute needs - the player's list of tunnels, a "tunnel nearest
this point" helper, an enter order, and the per-passenger exit a tunnel's Evacuate gives - because
Generals' tunnel-network guard machine (`AITNGuard*`) shipped intact and uses them.

## 1. What the pathfinder does with tunnels

Nothing. A path is a walk over adjacent grid cells; no edge joins two `TunnelContain` objects, so
a unit ordered across the map walks the whole way even when its own player has a tunnel beside it
and another beside the goal. The only engine code that moves a unit *between* tunnels is the guard
machine of §2, reached from the script action `TEAM_GUARD_IN_TUNNEL_NETWORK` (template strings set
at `0x007E008B`).

## 2. The tunnel-network guard machine

`AITunnelNetworkGuardState` - primary vtable `0x00C27EB0`, built at `0x0074110C`, `getName`
`0x0074112D`. Its `onEnter` (`0x00743AA6`, slot 4) allocates a `0x50`-byte inner machine with
`0x0094C8D0`, copies the guard position into machine `+0x3C` and the guard target into `+0x4C`,
and enters state `0x138B`. `update` (slot 6, `0x00747EAA`) steps the inner machine; `onExit`
(slot 5, `0x00743B40`) deletes it.

The inner machine's states, from the `0x0094C8D0` constructor (`defineState` is `0x008DBE1D`;
names from each vtable's slot 2):

| id | class | vtable | `onEnter` | `update` |
|---|---|---|---|---|
| `0x1388` | `AITNGuardInnerState` | `0x00C81140` | `0x0094CBFC` | `0x0094CC98` |
| `0x1389` | `AITNGuardIdleState` | `0x00C81038` | `0x0094C579` | `0x0094CF2A` |
| `0x138A` | `AITNGuardOuterState` | `0x00C81198` | `0x0094CD9D` | `0x0094CE46` |
| `0x138B` | `AITNGuardReturnState` | `0x00C811F0` | `0x0094CEB4` | `0x0094C517` |
| `0x138C` | `AIPickUpCrateState` | `0x00C2DE48` | `0x00769D24` | `0x0094C5C1` |
| `0x138D` | `AITNGuardAttackAggressorState` | `0x00C81250` | `0x0094D02C` | `0x0094D11D` |

`AITNGuardIdleState::update` is the part that matters here. When `0x0094CA71` (the scan for a
target near the network) finds one, the machine's nemesis id is at machine `+0x48`, and:

```
0094cfad  mov  ecx, [ebx+0x14]            ; the owner
0094cfb0  cmp  dword [ecx+0x27c], 0       ; contained?  (Object+0x27C = the container)
0094cfb7  je   0x94cffc                   ; no -> leave the state
0094cfbb  lea  ebx, [eax+0x38]            ; the nemesis's position
0094cfbe  call 0x68b678                   ; Object::getControllingPlayer
0094cfc3  call 0x94c84f                   ; the player's tunnel nearest [ebx]
0094cfc8  mov  ecx, [eax+0x258]           ; that tunnel's contain module
0094cfd4  call [eax+0x74]                 ; ... its exit interface
0094cfe5  call [eax]                      ;   isExitBusy?  yes -> try next frame
0094cff5  call [eax+0x14]                 ;   push the owner out of *this* tunnel
```

The same machine goes back in through `aiEnter` (`0x00770EDE`, called at `0x0094D6EB` and
`0x0094D787` on the tunnel it found).

## 3. The building blocks

| what | where | notes |
|---|---|---|
| the player's `TunnelTracker` | `Player+0x308` | NULL until the player owns a tunnel |
| the tracker's tunnel list | `TunnelTracker+0x08` | `std::list<ObjectID>` head; nodes `{next, prev, id}` |
| nearest tunnel to a point | `0x0094C84F` | **custom convention**: `eax` the `Player*`, `ebx` a `Coord3D*`; returns the `Object*` in `eax` (NULL for no player or no tunnel). 2D squared distance; **does not test the tracker for NULL**, and does not filter tunnels under construction |
| an object's contain | `Object+0x258` | `TunnelContain`'s contain interface has vtable `0x00C5DCE0` |
| what contains an object | `Object+0x27C` | the tunnel while a unit is in the network; a horde member's horde otherwise |
| enter | `aiEnter` `0x00770EDE` | command `0x42`; what the guard machine and `pickup-stuff-enter` use |
| exit one passenger | `aiExit` `0x007716C1` | command `0x1A`, `(container, source)`: what the exit-all loop gives every lone passenger of the tunnel being evacuated |
| exit a battalion | horde interface `+0x84` (`0x00875EFD`) | `(container, source)`: command `0x3E` to the horde's own AI - the exit-all loop's horde arm |
| `AIUpdateInterface::aiDoCommand` | `0x0066A7EC` | `__thiscall` on the AIUpdate's `+0x20` subobject, one `AICommandParms*`. Command type `[parms+0]`, source `[parms+4]` (`2` = `CMD_FROM_AI`), position `[parms+8]`, an attack-move's shots `[parms+0x34]` |
| its command switch | `0x0066AA18` | `jmp [eax*4+0x0066B07C]`, cases `0..0x54`. Case `0` (move to position) is `privateMoveToPosition` (`0x00661F85`); case `0x0F` (attack-move) its sibling `0x00661F67` |
| `TunnelContain::update` | `0x008812B0` | update-module slot 0 at `0x00C5DE58`, no other reference. Sleeps 1 frame once the owner has a tracker, so it runs every frame for every tunnel |
| `GameLogic::reset` | `0x0062D232` | zeroes the frame counter; slot 9 of `0x00BD8590` and `0x00BFDB68`, no direct caller |

The `AICommandType` enum is Generals' with one waypoint variant removed: from value 8 on, a BFME
value is one below its Generals counterpart (`ATTACK_OBJECT` is `0x0B`, attack-move `0x0F`, exit
`0x1A`), and BFME's additions start past Generals' end. Case `0x17` is **not** Generals' `ENTER`:
its handler (`0x0066468F`) forwards to a horde's exit and otherwise sets state `0x26` with the
container as goal, which is an exit.

Every override of `aiDoCommand` found reaches the base. The `+0x20` interface's slot 0 is the
entry, and `DeployStyleAIUpdate` (`0x0089209F`), `HordeAIUpdate` (`0x0089E169`, vtable
`0x00C66D38`) and four more (`0x0076D995`, `0x0088E44F`, `0x00892E3C`, `0x008AE798`) call
`0x0066A7EC` directly. `0x0076D995` handles moves itself and calls the base only for the rest,
so whatever class it belongs to is not routed.

`aiDoCommand` already special-cases containment before the switch (`0x0066A94D`..`0x0066A9A1`):
an object with status `0x26` whose container has its own AI has commands `0x1C`, `0x3B` and `0x43`
forwarded to that container. A `TunnelContain` building has no AI, so that path never runs for a
tunnel.

## 4. Edain's tunnels

From `__edain_data.big`. The base tunnels - the Moria, Wild, Gundabad and Orkstadt keeps, command
sets `MoriaTunnelBaseKeepCommandSet` and siblings - contain with
`PassengerFilter = ANY +INFANTRY +BANNER +CAVALRY -MONSTER -SUMMONED -COMBO_HORDE`, `ContainMax =
10`, `ExitDelay = 0`. Ordinary hordes therefore fit, combo hordes and monsters do not. The keeps
carry `Command_TransportEvacuateEdain`, so a player can already enter at one tunnel and evacuate
at another. The wight lairs (`GENERIC_WIGHT_TUNNEL_CONTAIN`, and the barrow-wight list) take
only wights, so they never take part in routing an army.

## 5. The patch

Three hooks and one cave (`.tunrte`, writable: a 64-entry table at its base).

**The order.** `0x0066AA09`, the six bytes in front of the switch (`mov eax, [esi]` / `or dword
[ebp+8], -1`; three short branches land on the first, none inside), becomes a `jmp` to the cave,
which does those two instructions first. With the switch reached, `esi` is the parms, `ebx` the
source, `edi` the `AIUpdate`, `[ebp-0x10]` the `+0x20` interface and `[ebp-0x14]` the owning
`Object`. For a move or attack-move from the AI or the player (`CMD_FROM_AI` or `CMD_FROM_PLAYER` -
the skirmish AI gives its army orders as the latter, §6) to a unit of a computer player
(`Player+0x5C == 1`) whose tracker exists:

- **outside the network**: A = the tunnel nearest the unit, B = the tunnel nearest the goal. If A
  and B differ, `|A - unit| + |goal - B| + transit_cost < |goal - unit|` (ground-plane distances),
  and A's contain answers `isValidContainerFor(unit, 0, 0)` (filter, relationship and status, not
  capacity), the order is recorded and replaced by `aiEnter(A, CMD_FROM_AI)`. The cave then leaves
  by `aiDoCommand`'s common tail (`0x0066B03F`), as a handled command does.
- **inside a tunnel**: the order is recorded and taken over; the per-frame pass brings the unit
  out.

The straight-line `|goal - unit|` underestimates the walk, so the test only routes when the tunnel
wins against the best case for walking.

The AI repeats its orders, so neither half restarts on a repeat: the same order again to a unit
walking to the door is absorbed, and an order to a unit already inside only changes its goal,
keeping its exit in progress. Any other order to a routed unit outside - except `AICMD_IDLE` -
drops the route. Orders the cave gives itself set a busy word that sends them straight to the
switch.

**Every frame.** `TunnelContain::update`'s slot (`0x00C5DE58`) points at a routine that runs the
stock update and then, once per logic frame, the routing pass over the table:

| the unit is | and | then |
|---|---|---|
| gone, or has no AI | | forgotten |
| in a tunnel | no exit ordered yet | exit at the tunnel nearest its goal; 10 s to happen |
| in a tunnel | the exit's 10 s are up | exit ordered again; from the third attempt, at the tunnel it is in |
| contained by something else | | forgotten |
| outside, walking in | idle, or 60 s gone | the recorded order, given again as a walk |
| outside, walking in | otherwise | left alone |
| outside, after being inside | | the recorded order, given again |

An exit is the order Evacuate gives that passenger: `aiExit(tunnel, CMD_FROM_AI)`, or for a
passenger whose contain has a horde interface, that interface's `+0x84`. Unlike the stock exit-all
loop (see [`evacuate-contained-heroes.md`](evacuate-contained-heroes.md)), a passenger with a
non-horde contain - a ring hero - gets `aiExit` rather than nothing.

**Between matches.** Both `GameLogic::reset` slots point at a routine that empties the table and
then jumps to the stock reset. The table holds `ObjectID`s, which a new match hands out again from
the start, so an entry left over from one match would otherwise act on an unrelated unit of the
next - and differently on each peer, which is a desync.

## 6. What a running game showed, and what it has not settled

Watched in Edain's `tests/test_ai_tunnel_routing.py` (2026-10-23): a Brutal Dwarves AI with two
`DwarvenMineShaft_Extern` sent three `DwarvenGuardianLangbarteHorde` in at one shaft and out by the
other, ~2,100 units on, in 22-30 logic frames where the walk took ~180. Counters in an
instrumented copy of the cave settled what this section used to open with:

- **The skirmish AI's army orders are `CMD_FROM_PLAYER`.** Each horde gets an attack-move (`0x0F`)
  with source `0`, on the horde object: the AI orders its armies as its player. The first version
  took `CMD_FROM_AI` only and routed nothing - the few AI-sourced moves were workers inside the
  base. The engine's own `CMD_FROM_AI` orders were mostly idles and BFME case `0x31` (no goal, to
  horde members and scouts).
- **Hordes.** The order reaches `aiDoCommand` on the horde object, and `aiEnter` on it takes the
  battalion in as one passenger.
- **The exit.** `aiExit` against the far tunnel brings a horde out there.

Not yet established, in order of how much each would change:

- **Idle as "the enter failed".** `AI_STATE_IDLE` is read off the state machine; a unit that idles
  for a frame on its way in would fall back to walking early.
- **Tunnels under construction** are in the tracker's list; an enter into one fails, which the
  fallback turns back into a walk.
- **A saved game** loses the table at load (`GameLogic::reset` runs first). A unit inside at save
  time stays there until the AI orders it again, which the "inside" arm then routes out.
