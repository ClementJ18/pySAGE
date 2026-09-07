# Why a co-op War of the Ring battle auto-resolves, and what an observer seat would cost

Engine build `2.01.2614.37001`, ImageBase `0x400000`. Static analysis 2026-09-06,
**confirmed against a running three-player game on 2026-09-06** - see *Measured live*.
The fix is built as
[`wotr-battle-observers`](../../patches/experimental/wotr_battle_observers.py).

## The symptom

In multiplayer War of the Ring a battle is fought in real time only when every human player is
involved. With three or more people in the game most battles are auto-resolved instead, and the
players who *were* in the battle never get the choice.

## The gate

`LivingWorldLogic::onSetConflictResolutionMethod` — the handler for
`MSG_LW_SET_CONFLICT_RESOLUTION_METHOD` (`0x6A7`) at `0x006BE9A5` — decides how each battle runs.
The gate is eleven bytes of it:

```asm
006bebbf  cmp  [0x00DE892C], ebx        ; TheGameInfo - no lobby, nothing to decide
006bebc5  je   0x006BF2D8
006bebcb  mov  ecx, [0x00DE412C]        ; TheGameLogic
006bebd1  call 0x00610A21               ; living-world game?  m_gameType in {1,2}
006bebd6  test al, al
006bebd8  je   0x006BEBF2
006bebda  push ebx                      ; 0
006bebdb  mov  ecx, esi                 ; TheLivingWorldLogic
006bebdd  call 0x006B5E3E               ; count of active human living-world players
006bebe2  cmp  [ebp-0x18], eax          ; participants that have voted
006bebe5  jge  0x006BEBF2               ; enough -> honour the vote
006bebe7  mov  edx, [ebp+8]             ; not enough:
006bebea  and  edx, 0xFFFFFFF7          ;   drop the real-time bit
006bebed  or   edx, 2                   ;   force the auto-resolve bit
```

`[ebp-0x18]` counts the battle's participants; `0x006B5E3E` counts the humans in the session. When
the first is smaller, the real-time bit is stripped and the battle auto-resolves no matter what
anybody voted.

**Both operands, precisely.** `[ebp-0x18]` is built by the loop at `0x006BEA08`-`0x006BEA7E`, which
walks the battle's sides (`battle+0x18`…`+0x1C`, stride `0x1C`, count via `0x007F6403`, member via
`0x007F5D2B`) and asks each member for its vote through `0x006E18B8`:

```asm
006e18b8  mov  eax, [ecx+0x44]          ; LivingWorldPlayer control type
006e18be  je   0x006E18D1               ;   0 human -> return player+0x334, the vote
006e18c1  je   0x006E18C9               ;   1 AI    -> tail-call 0x009001FB, the AI's pick
006e18c3  ...  eax = 3                  ;   else    -> real time
```

with the accumulator `[ebp+8]` collecting one bit per vote — `1` undecided, `2` auto-resolve,
`4` method 2, `8` real time — and `[ebp-0x18]` incremented only for auto-resolve and real time.
Because `0x006BEA80` returns early when the undecided bit is set, every participant has voted by the
time the gate runs, so **`[ebp-0x18]` is simply the number of participants in the battle**.

`0x006B5E3E` walks `TheLivingWorldLogic`'s player vector (`+0x8C`…`+0x90`) and counts entries whose
control type (`+0x44`) is 0 and whose `+0x444` flag is clear. Its one argument, passed 0 here, would
have included the `+0x444` players.

So the rule the engine enforces is:

> **battle participants >= human players in the session, or the battle auto-resolves.**

It is a proxy for "everybody is in this battle", and a loose one: AI participants count toward the
left side, so a battle of one human against two AI armies passes in a three-human game while a
battle between two of the three humans does not.

Downstream, `0x006BE467` turns the mask into an action — `& 2` runs
`LivingWorldAutoResolveBattle` (`0x006BE15D`), otherwise `& 8` runs
`LivingWorldLogic::enterRealtimeBattle` (`0x006B95BB`). Auto-resolve is tested first, which is why a
split vote resolves rather than plays.

The preference order comes from `TheGameInfo+0x80` at `0x006BEBF5`: `0` tries auto-resolve then real
time, `1` tries real time then auto-resolve, anything else uses the players' own bits. The shipped
lobby rule tables put `RULE:BattleChoice` (`0x00C82670`) at exactly those values — `AutoResolve = 0`,
`RTS = 1` — while `RULE:AutoResolveType` (`0x00C82648`) is a three-way
`AutoResolveAndRTS / AutoResolve / RTS`. **The identification of `+0x80` as `BattleChoice` is
inferred from that value match, not traced** — needs a live check.

## The client writes the same rule down again

**Found 2026-09-07, after the first build of the patch left the Real Time button greyed out in
play.** The gate above decides what happens once everybody has voted. A second copy decides whether
the player can vote at all, and it runs first.

The battle prompt's three buttons - `AutoResolve`, `RealTime` and `Retreat` (`0x00C92810`,
`0x00C9281C`, `0x00C92828`) - are enabled from one mask. Both of the two sites that refresh them
(`0x009FC4FD` and `0x009FCC41`) call `LivingWorldBattle::getAllowedResolutions` at `0x007F662B` and
shift bits 1, 3 and 2 out of the result into `SetButtonState`, whose two states are `_up` and
`_disabled`. **Bit 3 is Real Time**, the same bit number the vote mask uses.

Its tail is the same two counts:

```asm
007f67a9  cmp  [eax+0x7c], 1            ; RULE:AutoResolveType == AutoResolve -> no RTS at all
007f67ad  je   0x007F67E1
007f67b4  cmp  [eax+0x114], 0           ; the strategic map -> RTS always offered
007f67bb  jne  0x007F67C3
007f67bd  or   [ebp-8], 8
007f67c3  mov  ecx, [0x00DE4950]
007f67cb  call 0x006B5E3E               ; active human living-world players
007f67d4  call 0x007F5ECF               ; this battle's participants
007f67d9  cmp  eax, esi
007f67db  je   0x007F67BD               ; equal -> mask |= 8
007f67dd  or   [ebp-8], 2               ; otherwise -> auto-resolve only
```

`0x007F5ECF` sums `0x007F5E84` over the sides, and that per-side helper counts **only members
whose player is human** (`cmp [player+0x44], 0`). So the two copies of the rule do not count
the same thing: the logic gate's `[ebp-0x18]` counts every participant that voted, AI
included, while the client's counts humans. Both walk `battle+0x18`…`+0x1C` with stride
`0x1C` and `side+4`…`+8` with stride `0x30`, which is independent confirmation of the
side-vector layout the patch's cave relies on.

Two things follow. The client's test is **stricter** than the logic gate's - `==` where that one
asks `>=` - so a battle with more participants than the session has humans lights the button and
then auto-resolves anyway. And `GameInfo+0x7C` is `RULE:AutoResolveType`, read here against `1`
(`AutoResolve`) and, at `0x007F66B4`, against `2` (`RTS`) to decide whether the auto-resolve bit
starts set. **That corrects the guess below**: `+0x80` is a different field, and the value match
that suggested `BattleChoice` for it is unconfirmed either way.

## Measured live

Read out of a running three-player War of the Ring session on the strategic map, 2026-09-06, with
`sage_live`'s `ProcessMemory` against `C:\RotWK\game.dat` — a **stock** binary, every one of this
patch's six sites reading its original bytes.

| | |
|---|---|
| `TheGameLogic+0x110` / `+0x114` | `1` / `1` |
| living-world players | id 0 human, id 1 human, id 2 AI (`+0x44` = 1) |
| lobby slots | 0 and 1 `state` 6 (human), 2 `state` 4 (AI), 3-7 closed with `m_playerTemplate` -2 |
| `GameInfo+0x7C` `AutoResolveType` | 0 — `AutoResolveAndRTS`, so the rule is not what greys the button |
| pending battles | two, each **player 0 (human) against player 2 (AI)** |
| `0x006B5E3E(0)` | **2** |
| `0x007F5ECF` per battle | **1** |

`1 != 2`, so `0x007F67DD` runs and the mask is `2` — AutoResolve on, **RealTime greyed** — which is
the reported symptom, reproduced arithmetically from the engine's own state. With the patched
constant the same state yields `0xA`, both buttons live. The logic gate would not have fired here
at all: its count includes the AI, giving `2 >= 2`. **In this session the client gate is the whole
of the bug**, which is why the first build of the patch changed nothing visible.

Three things this settles that were open above:

- **The battle layout is right.** Walking `battle+0x18`…`+0x1C` by `0x1C` and `side+4`…`+8` by
  `0x30`, taking the first dword of each member, yields exactly the two `LivingWorldPlayer`s the
  battle is between. That was the reading the patch's cave rests on.
- **`battle+0x24` names the region and `region+0x14C` is its id** (79 and 92 here), which is the
  link `find_battle` uses to match `LivingWorldLogic+0xB8`.
- **`GameInfo+0x7C` is `AutoResolveType`.**

And two it corrects:

- **`TheGameLogic+0x114` is not an "in a battle" test.** It reads `1` on the strategic map, with
  zero objects on the field. It says the living-world session is network-hosted, nothing more. What
  actually keeps the patch's seating hooks inert outside a battle is
  `LivingWorldLogic+0xB8` holding `-1`; the cave now tests that explicitly rather than relying on
  the region lookup failing, because **whether that field is reset on the way back out of a battle
  has not been observed.** That is the next thing to check live.
- **`region+0x15C`, the owner, is `-1` for both pending battles.** Neither is a defence of an owned
  region, so the stock naming gives nobody `Player_1` and every seat `Player_<slot + 2>`. What a
  War of the Ring battle map does with no `Player_1` is unknown.

## Measured live, the seat

Read out of the observer client itself during a battle, 2026-09-06, with the first build of the
patch installed and running. The peer is slot 0, living-world player 0; the battle is between
player 1 (the other human) and player 2 (the AI), so it is correctly a non-participant and the
patch's predicate says so.

| | |
|---|---|
| `m_sides` | `''`, `PlyrCivilian`, `PlyrCreeps`, `Player_2` (Rohan, human), `Player_3` (Dwarves), `ReplayObserver` |
| a side for slot 0 | **none** |
| `multiplayerIsLocal` | **0 on every side** |
| `ThePlayerList` local seat | `PlyrCivilian` |
| slot 0 `startPos` | **-1** — the engine's own mark that this seat has no place on the map |
| slot 0 / slot 1 team | **0 / 0** — the co-op pair is already allied; the AI is team 1 |

With no side marked local, `PlayerList::newGame` falls through to the loop at `0x006A8B5F` and
hands the client the first player that is not `m_players[0]` — `PlyrCivilian`. The peer then sees
the map through the neutral player's eyes, which is exactly the failure this document predicted
under *Why the gate is there* and the first build did not prevent.

**Why `Observer_%d` was not enough.** The map's authored side pool (`m_skirmishSides`) holds
`Player_1`–`Player_4`, `PlyrNeutral` and the eleven `Skirmish*` templates. There is no `Observer_*`
in it, and the per-slot records built by `buildSidesFromGameInfo` only fill sides that already
exist — a record naming a side nobody declared is simply dropped. `ReplayObserver` is the one name
that always resolves.

Two things this hands the next step for free: the seat already knows it has no start position, and
it is already on the same team as the player it should be watching.

## Why the gate is there

Not networking. `MSG_LW_SET_CONFLICT_RESOLUTION_METHOD` travels through `TheMessageStream`, so the
handler, the mask and `enterRealtimeBattle` already run on **every** peer in the same frame. The
peers all transition to the battle map regardless.

The reason is that the battle map has nowhere to seat a peer that is not fighting.

`GameLogic::buildSidesFromGameInfo` at `0x00627C1F` runs whenever `TheGameInfo` is non-null
(`0x0062FB0A`), which includes every War of the Ring battle. Its first loop stamps each occupied
lobby slot with the name of the side it should be matched against:

```asm
00627c6e  cmp  [esi+0x18], ebx          ; slot's player template
00627c74  jl   0x00627CD5               ;   < 0 -> "Observer_%d"  (0x00BFD4FC), slot + 1
00627c79  cmp  [eax+0x114], 3
00627c80  je   0x00627CC9               ;   scripted campaign -> "Player_%d", slot->[0x10] + 1
00627c82  mov  eax, [esi+0x4c]          ;   War of the Ring:
00627c8d  call 0x006B5DE0               ;     the slot's LivingWorldPlayer
00627c9a  call 0x006B351E               ;     the current region
00627cad  cmp  eax, [edi+0x14]          ;     region+0x15C owner == player id ?
00627cb2  push 0x00BFD520               ;       yes -> "Player_1"
00627cc1  add  eax, 2                   ;       no  -> "Player_%d", slot index + 2
```

The second loop (`0x00627D8F` onward) builds each side from its slot, taking the faction from the
same `slot+0x18`: a non-negative value indexes `ThePlayerTemplateStore` (`0x00627E27`), a negative
one resolves `FactionObserver` (`0x00627E3B`). It also sets `multiplayerIsLocal` on the side whose
slot name matches the local slot's (`0x00627AC3`-`0x00627AE1`), which is what
`PlayerList::newGame` reads at `0x006A8AC0` to choose the client's seat.

There is no test of battle participation anywhere in that. A slot is `Player_1` if it owns the
region and `Player_(slot + 2)` otherwise — so in a three-human game the third player is named
`Player_4` or `Player_5`, a side no War of the Ring map declares. With no matching side, nothing
sets `multiplayerIsLocal` for that peer, and `PlayerList::newGame` falls through to the loop at
`0x006A8B5F`, which hands the client **the first player that is not `m_players[0]`** — somebody
else's army. That is the failure the gate is avoiding.

The same reading says the naming is index-based even for two players: a two-human battle works only
when the attacker occupies slot 0, because an attacker in slot 1 is named `Player_3`. **Needs a live
check** — it is a strong claim from a single `add eax, 2`, and it would mean shipped 1v1 real-time
battles are seat-order dependent.

## What the engine already has

Every piece an observer needs is present and reachable.

| piece | where | note |
|---|---|---|
| observer lobby slot | `slot+0x18 < 0` | `-2` is the observer sentinel, tested at `0x0062FE9C` |
| observer side name | `"Observer_%d"`, `0x00BFD4FC` | `0x00627CD5`, from the same `slot+0x18` test |
| observer faction | `FactionObserver`, `0x00BFD484` | `0x00627E3B`, same test |
| full-map vision | `0x00B4D940` on `[0x00DE4358]` | `0x0062FEA2` for `-2` slots, and `0x0062FE3D` for `ReplayObserver` |
| a spare observer side | `ReplayObserver` | `0x00626E1F` adds it to `TheSidesList` unconditionally, called once from `0x0062FBA0` |
| observer seat plumbing | `Player+0x35A`/`+0x35B` | `Player::initFromSide` `0x006B07EF` recognises the name/faction pair at `0x006B0A70` |
| observer camera and bar | — | already patched: [`observer-switch`](../observer-switch.md), [`observer-command-range`](../observer-command-range.md) |

`ReplayObserver` is in `m_sides` for every game, which is consistent with the seat
[`battle-sides.md`](battle-sides.md) measured live when a scripted campaign left the client with no
slot of its own.

## The patch

Built as [`wotr-battle-observers`](../../patches/experimental/wotr_battle_observers.py). Nine
rewritten sites, one cave, no INI surface. It applies and verifies against the build; **it has not
been run in a game.**

**1 — Stop forcing auto-resolve, in both places.** `0x006BEBE5`, `jge` to `jmp` (`0x7D` to
`0xEB`), file offset `0x2BEBE5`. Stock bytes at `0x006BEBBF` are
`391d2c89de00 0f840d070000 8b0d2c41de00 e84b1ef5ff 84c0 7418 53 8bce e85c72ffff 3945e8 7d0b`.
And `0x007F67DD`, `or [ebp-8], 2` to `or [ebp-8], 0x0A` (`834df802` to `834df80a`), which adds
the real-time bit to the button mask instead of replacing the auto-resolve one - so the player
keeps both choices, and an `AutoResolveType` of `AutoResolve` still greys the button on purpose.
Three bytes between them, no cave. **The second is the one that shows**: without it the button
stays disabled and the logic gate never runs.

**2 — Get the seat looked at.** Both of `buildSidesFromGameInfo`'s loops skip a slot whose
`GameSlot::isOccupied` (`0x008009B1`) is false, which is `m_state in {2..6} and m_isOccupied != 0`.
The engine leaves `m_isOccupied` (`GameSlot+0x1AC`) **clear on a seat that is not in this battle** —
read live 2026-09-06 as 1 on the two seats fighting and 0 on the third human. So that seat is never
named, never built into a side, and the client falls through to `PlyrCivilian` no matter what the
naming hooks say. A pre-pass at `0x00627C41`, before either loop, marks those seats occupied. It is
what makes everything below reachable, and it is the piece the second build was missing.

**3 — Seat non-participants as observers.** One predicate in the cave answers *is this human seat
out of this battle*: it finds the battle by matching `battle+0x24`'s region id against the id
`enterRealtimeBattle` left on the logic, resolves the slot's `LivingWorldPlayer` through
`0x006B5DE0`, and walks the battle's side and member vectors looking for it. The walk strides
exactly as `0x007F6403` and `0x007F5D2B` do, which is where the layout comes from.

Three hooks ask it. Two force a comparison negative so the seat takes the observer arm — the side
name (`0x00627C6E`) and the faction (`0x00627E20`) — rather than writing the observer sentinel into
`GameSlot::m_playerTemplate`, because the lobby `GameInfo` outlives the battle and a seat left
marked would make that player an observer on their own strategic map. Both are `call` detours whose
last instruction is the comparison the caller's `jl` reads.

The third replaces the name outright. `0x00627CEB`, where all three naming arms converge to copy
the formatted string into `GameSlot::m_mapPlayer`, assigns the literal **`ReplayObserver`** instead
whenever the predicate said observer, through the same `AsciiString::operator=` (`0x004050E6`) the
`Player_1` arm above it uses.

**That third hook is the one the first build got wrong**, and *Measured live, the seat* below is
the evidence. Naming the seat `Observer_%d` — the arm the engine's own lobby observers take — is
not enough, because **no War of the Ring map declares an `Observer_N` side** and a slot record only
fills a side that already exists. `ReplayObserver` is the side that always exists: `startNewGame`
adds it to every game unconditionally at `0x00626E1F`.

**4 — Name the participants correctly.** `0x00627CC1`'s `slot index + 2` becomes a count of the
human seats before this one that are in the battle and are not its defender, so the defender keeps
`Player_1` and the attackers take `Player_2` upward. Every way of not knowing the answer falls back
to the stock number, which the hook writes before it tests anything.

**5 — Do not hand the observer the whole map.** `GameLogic::startNewGame` reveals every shroud cell
for the `ReplayObserver` player before it walks the lobby slots:

```asm
0062fe1e  push 0x00BFD4A8               ; "ReplayObserver"
0062fe23  call 0x005487EC               ; the name key
0062fe2f  call 0x006A8466               ; ThePlayerList::findPlayerWithNameKey
0062fe34  push [eax+0x54]               ; that player's index
0062fe37  mov  ecx, [0x00DE4358]        ; TheShroudManager
0062fe3d  call 0x00B4D940               ; revealMapForPlayer, ret 4
```

Right for a replay, where the side is the audience and there is nobody to watch through. Wrong
here: the peer is a player in this session, seated on that side only because it is the one side
that always exists, and it has allies whose vision it should share. `0x0062FE3D` becomes a `call`
into the cave, which tail-jumps to `0x00B4D940` unless the pre-pass seated somebody — so a replay
played on a patched build still gets the whole map. The skip arm does the callee's own `ret 4`.

That flag is the pre-pass's other output. It is cleared at the top of every run, because the cave
outlives a game and a stale 1 would take the map away from the next replay.

**6 — Open the camera somewhere real.** `0x006311A0` formats `Player_%d_Start` (`0x00BFDA18`) from
the local seat's `m_startPos + 1` — `mov eax, [esi+0x10]` / `inc eax` / `push eax` at `0x006311D3` —
and that waypoint is where the camera opens. A seat with no place on the map carries a start
position no two-army battle map declares — `Player_6_Start` and up on a battle between two armies —
and the camera opens in the map's corner. (The seat read live on 2026-09-06 held `-1` there, before
this build's pre-pass put it back into the loops that assign one; **which value it ends up with once
it is seated has not been observed.**)

The hook lends the observer a participant's: an ally's where the lobby team (`GameSlot+0x1C`) says
which side it is on, otherwise the first participant's in slot order. Preferring the ally matters on
a map where the two bases are far apart — the enemy's base is not somewhere the observer's shroud is
lifted. `-1` is the lobby's no-team value and means *everyone is an enemy*, so it takes the first
participant instead. A seat that is fighting, a game with no observer seated, and an observer with
nobody to borrow from all keep the stock answer. The hook displaces the `push` as well as the two
instructions that compute it, so it puts the argument back **under** its own return address.

The whole cave answers "no" to any question it cannot resolve — not a multiplayer battle, no
battle found, no living-world player for the seat — and leaves the stock path exactly as it was.
That is what keeps it inert in a skirmish, a campaign mission or a replay.

### What this does not need

- No new network message. The vote is already replicated and the mask is already computed
  identically on every peer.
- No change to the auto-resolve path, the post-battle harvest (`0x00811E1F`, which only records
  survivors owned by living-world players, and an observer owns none) or hero permadeath.
- No new UI: `observer-switch` and `observer-command-range` already cover the observer's camera and
  command bar. Whether `observer-switch`'s mode whitelist admits a War of the Ring battle depends on
  `TheGameLogic+0x110` during one — **needs a live check**; if it does not, the same retarget to
  `0x00625456` that patch already uses applies here.

### Risks

- **Desync.** The observer peer runs the same simulation with no orders to issue, which is the
  replay-playback shape and should be safe. It is still the thing to watch first, and
  [`desync-detection`](../desync-detection.md) is the instrument.
- **What the observer can see before it switches.** Dropping the map-wide reveal leaves the seat on
  its own shroud, and an observer owns nothing that lifts one.
  [`observer-switch`](../observer-switch.md) is what supplies the vision: switching re-runs
  `TheShroudManager` for the seat it moves to (`0x00B4D8E0`). **Which seat the client is on before
  the first switch, and therefore what the battle opens on, has not been observed.** If it opens
  black, the answer is to switch on entry rather than to put the reveal back — the reveal is what
  makes a co-op battle a spectator's map rather than a player's.
- **Victory conditions.** An observer is excluded by `Player::isPlayerActive`
  (`m_isObserver` and `m_isDefeated` both clear, `0x006AAC52`), so it should not hold a battle open.
  Unverified for the War of the Ring end-of-battle path specifically.
- **Turn timing.** Every peer already transitions to the battle map today, so this adds no new
  waiting, but a longer real-time battle now blocks players who used to sit through an
  auto-resolve. That is the feature, not a defect, and `RULE:StrategicPhaseTimer` is the existing
  knob.

## Method

Message ids from the name chain at `0x00712120`, where `0x6A5` is `MSG_LW_DONE_SESSION` and the
sequence runs to `0x6BC`. The handler was reached from `LivingWorldLogic`'s dispatch at
`0x006BE77D` (`type - 0x6A5`, bound `0x1B`, table `0x006BF2E9`) rather than by scanning for the
constant, which only finds the emitters. Side naming from the string literals `Player_1`
(`0x00BFD520`), `Player_%d` (`0x00BFD508`) and `Observer_%d` (`0x00BFD4FC`). Lobby rule values read
out of the tables at `0x00DB7794` and the `VALUE:` arrays they point at.
