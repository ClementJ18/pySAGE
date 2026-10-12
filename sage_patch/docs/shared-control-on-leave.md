# Shared control on leave

**Status: built, not played.** `shared-control-on-leave` (experimental) applies, verifies and
passes its emulated tests. Every site was read statically from RotWK 2.01 `game.dat`; nothing here
has been observed in a running game yet. §4 is the list to work through in play.

**Goal.** When a player leaves, their objects stay with their own `Player`: their own money,
inflation, command points and upgrades, and their spellbook stays theirs. Every remaining allied
human can select those objects and give them orders, like the shared unit control in Warcraft III.
Stock, the engine gives everything to the first living ally instead. That ally's command points
fill up, their army ends up the wrong shape, and the leaver's economy is merged into theirs.

**Shape.** The engine has one ownership check on the logic side and one small "is this mine"
predicate on the client side. The patch is four edits and one bit of logic state per player. The
risk is not in the hooks. It is in the client's edge cases, listed in §4.

## 1. What the engine does today

### The leave order

A voluntary leave is `MSG_SELF_DESTRUCT` (`0x448`, one `Boolean` argument; see
[`message-stream.md`](message-stream.md)). The logic dispatcher `0x00779A3D` reaches it through
the second-level switch at `0x0077B455` (`lea eax,[edi-0x437]`, byte table `0x0077D1E3`, jump
table `0x0077D127`, index 12), which lands on **`0x0077CA3D`**:

```asm
0077ca46  push 0 / call 0x710c9e          ; arg0 (Boolean)
0077ca4e  cmp  byte ptr [eax], bl
0077ca50  je   0x77cafd                   ; False: killPlayer, then the Living World branch
          ; True: for each player i != the sender
0077ca6d  call PLAYER_LIST_GET_NTH
0077ca81  call 0x6adbeb ; cmp eax,2       ;   leaver sees i as ALLIES
0077ca96  call 0x6adbeb ; cmp eax,2       ;   and i sees the leaver as ALLIES
0077caa9  call [TheVictoryConditions+0x40]  ; hasSinglePlayerBeenDefeated(i)
0077caae  je   0x77cac3                   ;   i is not defeated: this is the heir
0077cac3  push 1 / push leaver / mov ecx, heir
0077caca  call 0x6af598                   ; heir->transferAssetsFromThat(leaver, 1)
0077cad2  call 0x6abe7c                   ; leaver->killPlayer()
0077cae8  call 0x6abe7c                   ; (no heir found) leaver->killPlayer()
0077caf3  call 0x6328ee                   ; on TheGameEngine, both paths
```

Every leave recorded in the replay corpus carries `True`. The `False` arm (`0x0077CAFD`) calls
`killPlayer` and then walks allies again for Living World (`TheLivingWorldLogic+0xB4`). It is out
of scope here.

- **`Player::transferAssetsFromThat`** `0x006AF598` moves the leaver's objects (a `setTeam` loop)
  and their money, upgrades and similar state onto the heir. This is the behaviour the patch removes.
- **`Player::killPlayer`** `0x006ABE7C` sets `m_isPlayerDead` (`+0x754`, `PLAYER_IS_DEFEATED`),
  kills every object on each of the player's teams, and withdraws all of their money. It returns
  early when the lookup at `0x6A950B`/`0x6C7518` succeeds, which looks like campaign or Living
  World and is not identified. A leaver who keeps their objects must not reach this call either.

### The logic-side ownership check

For every command order (`0x3E8..0x7CF`, except `0x447`/`0x44A`), the head of the dispatcher
builds the sender's selection as an `AIGroup` (`0x779AE1`–`0x779AEF`) and then filters it:

```asm
00779b2a  cmp  eax, 0x41d                 ; MSG_EXIT: no filter
00779b31  push thisPlayer / mov ecx, group
00779b36  call 0x76ed16                   ; AIGroup::removeAnyObjectsNotOwnedByPlayer
00779b3f  mov  [ebp-0x10], 0              ;   group emptied: the order does nothing
```

`0x0076ED16` compares `OBJECT_GET_CONTROLLING_PLAYER(obj)` with the argument and removes any
object that does not match. **It has exactly one caller**, so the whole logic-side gate can be
hooked at the `call` at `0x0076ED2D`/`0x0076ED32` without affecting anything else.
(`MSG_EVACUATE_CONTESTERS` goes through its sibling `0x0076ED57`, which compares the container's
player. It can stay as it is.)

Selection itself is not gated. `MSG_CREATE_SELECTED_GROUP` goes to `GameLogic::selectObject`
(`0x00625685`) with the sender's player mask, and nothing checks ownership until the next order is
filtered. So a patched client only has to *send* a selection that includes the leaver's objects.

### The client-side predicate

**`Object::isLocallyControlled`** is `0x0068B749`:
`getControllingPlayer() == [ThePlayerList+0x10]`. It has 52 direct callers in the UI, the
selection and command translators, the control bar, audio and feedback code. That includes three
feedback-only calls inside the logic dispatcher (`0x77790D`, `0x779559`, `0x7798E8`) and one at
`0x77BECB`. None of them changes logic state, which is why using it inside the logic dispatcher is
safe in stock.

About 15 other sites inline the same comparison instead of calling the function. The `loc.py`
scan pattern found them, for example `0x6990F2` and `0x8CDF64`, plus the users of
`PLAYER_LIST_GET_LOCAL_PLAYER` (19 callers). None of them is patched (§4).

## 2. What the patch does

**State: an `abandoned` bit per player index**, a dword mask at the head of the `.shctl` cave.
Only the leave order sets it, and that order runs on every client on the same frame, so the bit is
lockstep state like any other logic value and needs no network traffic.

**The relation.** Player `P` may command an object of another player `Q` when all of these hold:

- `Q` is abandoned;
- `P` is not dead (`Player+0x754`, the hard flag `killPlayer` sets) and not an observer
  (`Player+0x35A`);
- `P` and `Q` each see the other's default team as `ALLIES` (`Player::getRelationship`,
  `0x006ADBEB`, in both directions).

It reads only latched player state. That matters because the client asks it at its own rate:
`hasBeenDefeated` (`0x0080953C`) is not safe there, since it bumps the defeat counter at
`VictoryConditions+0x88` whenever it answers true. Allied AI players satisfy the relation too,
which is harmless: an AI never sends orders through the dispatcher.

### The four edits

| site | change |
|---|---|
| `0x0077CA56`, the leave order's `True` arm | Replaced whole (a `jmp` over its first instruction; `0x0077CA5C`-`0x0077CAEC` is no longer reached). See below. |
| `0x0076ED2D`, the `call getControllingPlayer` in `removeAnyObjectsNotOwnedByPlayer` | Repointed at a routine that answers the *sender* for an object the sender may command, so the stock compare keeps it. This is the only logic-side gate. |
| `0x0068B749`, `Object::isLocallyControlled` | Replaced whole: true for the local player's own objects and for those the local player may command. This one change moves most of the client: click and drag selection, the control bar, cursors, right-click orders. |
| `0x00C4F12C`, `VictoryConditions` vtable `+0x24` (`reset`, `0x00808A43`) | Repointed at a routine that clears the mask and continues into `reset`, so a new game starts with nobody abandoned. |

### The leave order

The replaced arm looks for a mutual ally of the leaver that is **human** (`Player+0x5C == 0`),
has not left, and is not defeated by `hasBeenDefeated`, which is asked exactly as the stock arm
asks it.

- **One exists:** the leaver's bit is set. Nothing is transferred and `killPlayer` is not called.
- **None exists:** the leaver is the last human of the team. The arm looks again for any ally that
  has not left and is not defeated, which by now can only be an AI. Then the leaver *and every
  abandoned ally of the leaver* are each transferred to that ally if there is one, killed, and
  their bit cleared. For a leaver with no abandoned allies this is the stock behaviour exactly.

The second case is why an abandoned ally never counts as "still playing", and why the heir is
never taken from the stock search: that search would pick the first undefeated ally by index,
which can be a player who left earlier.

Both paths continue at `0x0077CAED`, where the stock paths meet.

### What comes out right with no further work (expected, to confirm in play)

- **Separate economies.** Production and upgrade handlers charge the *producer's* controlling
  player (the `ProductionUpdate` path), so an ally queuing units at the leaver's barracks spends the
  leaver's money and command points, under the leaver's inflation.
- **Resource buildings keep paying the leaver.** That money can be spent through their buildings.
- **XP, kills and score** stay with the leaver's objects and seat.
- **Replays stay deterministic.** The replay already contains the `0x448`, and the leave arm and
  the order filter are pure logic, so a replay recorded with the patch plays back with it. A
  replay recorded *without* it diverges at the first leave when played on a patched binary, and
  the reverse.

## 3. What is tested, and how

`tests/sage_patch/test_shared_control_on_leave.py` runs the real stock bytes and the cave in an
emulator over small worlds of players, with the engine calls answered from a model:

- the stock leave arm and the replacement, side by side, wherever they must agree (no ally, a
  defeated ally, a one-way alliance, an AI-only ally), and the cases where they differ;
- the real filter loop, stock and patched, over mixed selections;
- the real `isLocallyControlled` against the cave, which must be identical while nobody has left;
- the reset routine.

This proves the routines do what §2 says. It does not prove §2 is the right reading of the engine.

## 4. To check in a running game

In the order that costs least:

1. **Leave in place.** Two humans allied against anyone; one leaves. The leaver's base must stay
   up, keep earning, and the game must go on. Look at victory conditions, the score screen, the
   diplomacy panel and AI targeting. A departed human `Player` that still owns live objects is a
   state the stock leave never produces.
2. **Logic permission, without the UI.** With `sage_live` order injection, send a
   `MSG_CREATE_SELECTED_GROUP` naming one of the leaver's units and a `MSG_DO_MOVETO` from the
   ally's seat, and watch the unit move. This isolates the order filter from everything in item 3.
3. **The client.** Select the leaver's units by click and by drag, move and attack, queue a unit
   at their barracks, use a hero power.
4. **Last human out**, with and without an AI ally on the team.

### Open questions

- **Selection is assumed ungated.** `MSG_CREATE_SELECTED_GROUP` goes to `GameLogic::selectObject`
  (`0x00625685`) with the sender's player mask, and nothing was seen to check ownership before the
  next order is filtered. Item 2 is the test of that.
- **The inlined local-player comparisons.** About 15 sites compare `getControllingPlayer()` with
  `[ThePlayerList+0x10]` inline instead of calling `isLocallyControlled` (for example `0x6990F2`
  and `0x8CDF64`), and `PLAYER_LIST_GET_LOCAL_PLAYER` has 19 callers. None is patched. Each needs
  a verdict: widen it, or leave it because it really means "the seat at the keyboard". Likely
  offenders: double-click and "select all of type", which iterate the *local player's* objects
  only, so the leaver's units would be skipped.
- **`isLocallyControlled` inside the logic dispatcher.** Three feedback calls (`0x77790D`,
  `0x779559`, `0x7798E8`) and one at `0x77BECB` use it. They were read as changing no logic state,
  which is what makes a per-client answer safe there. A desync right after an ally orders a
  leaver's unit would point here first.
- **Control-bar affordability.** Check whether button enable/disable reads the object's
  controlling player or the local player. If it reads the local player, the leaver's production
  buttons grey out, or light up, based on the wrong wallet. The money readout will show the local
  player's money either way.
- **Player-level actions** (`MSG_PURCHASE_SCIENCE`, spellbook powers, `MSG_GIVE_MONEY`) act on the
  *sender's* player, so the leaver's spellbook is unusable. That is what "separate pools" implies.
- **Two allies giving orders** to the same unit: the later order wins, as in WC3.
- **Object-id orders that skip the group**: `MSG_COMBINE_HORDES_WITH_OBJECT` (`0x423`),
  `MSG_CASTLE_UNPACK_EXPLICIT_OBJECT` (`0x43F`), `MSG_DO_SPECIAL_POWER` with an explicit object
  (`0x0077A4A8`). Check whether combining a mixed-owner horde, or unpacking at the leaver's plot,
  does something strange.
- **The last human is defeated instead of leaving.** Nothing runs then: the abandoned allies'
  armies stay on the map with nobody to command them, and the enemy has to destroy them to win. A
  defeated player commands nothing by the relation above. Closing this needs a hook on the defeat
  latch (`0x0080908A`, see [`replay-outcome.md`](replay-outcome.md)).
- **Disconnects vs voluntary leaves.** The replay corpus shows `0x448` only for voluntary exits,
  always with `True`. What the engine does when a peer drops is not known. If it issues the same
  order the patch already covers it; if it takes the `False` arm (`0x0077CAFD`, `killPlayer` and
  the Living World branch, left stock), a dropped player is still destroyed.
- **What the defeat check counts.** The team-loss rule has to count an abandoned player's live
  objects on the team's side (expected, since it is an object census). It also has to **not** make
  an abandoned player win on their own.
- **Save/load.** The mask lives in the cave, not in the `Player` xfer block, so a multiplayer save
  made after a leave loads with nobody abandoned: the leavers' armies stand idle and are not
  cleaned up when the last human leaves.

## 5. Addresses

In [`addresses/logic.py`](../addresses/logic.py) (`SELF_DESTRUCT_*`,
`AIGROUP_REMOVE_NOT_OWNED_BY*`), [`addresses/player.py`](../addresses/player.py) (`PLAYER_TYPE`,
`PLAYER_GET_RELATIONSHIP`, `PLAYER_TRANSFER_ASSETS_FROM`, `VICTORY_CONDITIONS_RESET*`) and
[`addresses/objects.py`](../addresses/objects.py) (`OBJECT_IS_LOCALLY_CONTROLLED`).
