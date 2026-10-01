# Shared control on leave — scope

**Status: scoping.** The sites below were read statically from RotWK 2.01 `game.dat`
(2026-09-30); none of this has been tried in a running game yet.

**Goal.** When a player leaves, their objects stay with their own `Player`: their own money,
inflation, command points and upgrades, and their spellbook stays theirs. Every remaining allied
human can select those objects and give them orders, like the shared unit control in Warcraft III.
Today the engine gives everything to the first living ally instead. That ally's command points
fill up, their army ends up the wrong shape, and the leaver's economy is merged into theirs.

**Verdict.** The engine has one ownership check on the logic side and one small "is this mine"
predicate on the client side. The patch needs three hooks and one per-player bit of logic state.
The work is not in the hooks. It is in checking the edge cases on the client, listed in §4.

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
  and their money, upgrades and similar state onto the heir. This is the behaviour to remove.
- **`Player::killPlayer`** `0x006ABE7C` sets `m_isPlayerDead` (`+0x754`, `PLAYER_IS_DEFEATED`),
  kills every object on each of the player's teams, and withdraws all of their money. It returns
  early when the lookup at `0x6A950B`/`0x6C7518` succeeds, which looks like campaign or Living
  World and is not identified. If the leaver keeps their objects, this call must be skipped too.

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
`PLAYER_LIST_GET_LOCAL_PLAYER` (19 callers). These have to be checked one by one (§4).

## 2. Design

**New state: an `abandoned` bit per player index**, a 16-bit mask in a `.sagepatch` cave. Only the
leave order sets it, and that order runs on every client on the same frame, so the bit is lockstep
state like any other logic value. It needs no network traffic. It is cleared at game start.

**Shared-control relation.** Player `P` may command `Q`'s objects when `Q == P`, or when `Q` is
abandoned and `P` and `Q` see each other as `ALLIES` (`0x6ADBEB` in both directions == 2).
Allied AI players never issue orders, so they are left out automatically.

### Hooks

| # | site | change |
|---|---|---|
| H1 | `0x0077CA3D` leave case, the "heir found" arm `0x0077CAC3` | Replace `transferAssetsFromThat` + `killPlayer` with "set `abandoned[leaver]`". Keep the heir search as the test for "is there someone to hand control to". Change the heir condition to **a living human ally** (player type, see [`PLAYER_SET_TYPE`](../addresses/player.py)), and fall back to the stock transfer when only AI allies remain. |
| H2 | `0x0076ED2D` in `removeAnyObjectsNotOwnedByPlayer` | Keep the object when its controller is `P`, **or** when the controller is abandoned and allied with `P`. This is the only logic-side gate. |
| H3 | `0x0068B749` `Object::isLocallyControlled` | Answer the same relation for the local player, and false for observers. This one change moves most of the client: click and drag selection, the control bar, cursors, right-click orders. |

The **last human leaves a team**: in the stock "no heir" arm `0x0077CAE5`, also `killPlayer` every
abandoned ally of the leaver. Without this their armies stay on the map as targets nobody
controls, and the game waits for them to be destroyed.

### What comes out right with no further work (expected, to confirm in play)

- **Separate economies.** Production and upgrade handlers charge the *producer's* controlling
  player (the `ProductionUpdate` path), so an ally queuing units at the leaver's barracks spends the
  leaver's money and command points, under the leaver's inflation.
- **Resource buildings keep paying the leaver.** That money can be spent through their buildings.
- **XP, kills and score** stay with the leaver's objects and seat.
- **Replays stay deterministic.** The replay already contains the `0x448`. Both H1 and H2 are pure
  logic and replay identically with the patch installed, since every player runs the same
  `game.dat`.

## 3. Phases

1. **Leave-in-place only (H1 without H2/H3).** The leaver keeps everything and it stands idle.
   This alone tests the risky part: a departed human `Player` that still owns live objects, a case
   the stock leave never produces. Look at victory conditions, the score screen, the diplomacy
   panel, AI targeting and saving. This phase is also useful on its own as a "no inheritance"
   option.
2. **Logic permission (H2).** Test it with `sage_live` order injection before touching the UI.
   Inject a `MSG_CREATE_SELECTED_GROUP` naming the leaver's unit plus a `MSG_DO_MOVETO` from an
   ally's seat, and watch the unit move.
3. **Client (H3 + the §4 audit).** Make it playable.
4. **Last-human-out cleanup** and the AI-only fallback.

## 4. Open questions and risks

- **The inlined local-player comparisons** (~15 sites plus 19 `getLocalPlayer` callers). Each
  needs a verdict: widen it, or leave it because it really means "the seat at the keyboard". Likely
  offenders: double-click and "select all of type", which iterate the *local player's* objects
  only, so the leaver's units would be skipped. That is acceptable for v1.
- **Control-bar affordability.** Check whether button enable/disable reads the object's controlling
  player or the local player. If it reads the local player, the leaver's production buttons grey
  out, or light up, based on the wrong wallet. The money readout will show the local player's money
  either way. That might be good enough, or it might need a "viewing X's economy" readout.
- **Player-level actions** (`MSG_PURCHASE_SCIENCE`, spellbook powers, `MSG_GIVE_MONEY`) act on the
  *sender's* player. The leaver's spellbook becomes unusable. That seems correct for "separate
  pools", but it needs a decision.
- **Two allies giving orders** to the same unit: the later order wins, as in WC3. Each ally's
  control groups are their own logic-side selections, so there is no conflict there.
- **Object-id orders that skip the group**: `MSG_COMBINE_HORDES_WITH_OBJECT` (`0x423`),
  `MSG_CASTLE_UNPACK_EXPLICIT_OBJECT` (`0x43F`), `MSG_DO_SPECIAL_POWER` with an explicit object
  (`0x0077A4A8`). Check whether combining a mixed-owner horde, or unpacking at the leaver's plot,
  does something strange.
- **Disconnects vs voluntary leaves.** The corpus shows `0x448` only for voluntary exits. Find out
  what the engine does when a peer drops. If a dropped peer's units are already left in place, that
  is useful evidence that phase 1 is safe, and also a second trigger that should set `abandoned`.
- **What the ally defeat check counts.** `hasSinglePlayerBeenDefeated` and the team-loss rule have
  to count an abandoned player's live objects on the team's side (expected, since it is only an
  object census). They also have to **not** make an abandoned player win on their own if their
  last ally is defeated while the abandoned player's army survives. See
  [`replay-outcome.md`](replay-outcome.md) for how `VictoryConditions` latches.
- **Save/load.** The `abandoned` mask lives in a cave, not in the `Player` xfer block, so a
  multiplayer save made after a leave loses it. Low priority, but needs a decision: either accept
  it, or serialise the mask through an existing per-player field.
- **Living World** (`False` arm, `TheLivingWorldLogic+0xB4`) is left stock.

## 5. Addresses

These go into `sage_patch/addresses/player.py` and `logic.py` when implementation starts:

| name | VA | what |
|---|---|---|
| `MSG_SELF_DESTRUCT_CASE` | `0x0077CA3D` | leave-order case in the logic dispatcher |
| `SELF_DESTRUCT_TRANSFER_ARM` | `0x0077CAC3` | the "heir found" arm |
| `SELF_DESTRUCT_NO_HEIR_KILL` | `0x0077CAE5` | the "no heir" `killPlayer` |
| `PLAYER_TRANSFER_ASSETS_FROM` | `0x006AF598` | `Player::transferAssetsFromThat(Player *, Bool)` |
| `PLAYER_KILL` | `0x006ABE7C` | `Player::killPlayer()` |
| `PLAYER_GET_RELATIONSHIP` | `0x006ADBEB` | `Player::getRelationship(Team *)`, `2` = `ALLIES` |
| `PLAYER_DEFAULT_TEAM` | `0x30C` | `Player::m_defaultTeam` |
| `AIGROUP_REMOVE_NOT_OWNED_BY` | `0x0076ED16` | the only logic-side ownership gate, one caller at `0x00779B36` |
| `OBJECT_IS_LOCALLY_CONTROLLED` | `0x0068B749` | client "is this mine", 52 callers |
| `GAME_LOGIC_SELECT_OBJECT` | `0x00625685` | `selectObject(obj, createNew, playerMask, affectClient)` |
