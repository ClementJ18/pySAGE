# Switching players in a replay — reverse-engineering notes

The RE behind [`patches/observer_switch.py`](../patches/observer_switch.py). ROTWK `game.dat`
build `2.01.2614.37001`, ImageBase `0x400000`, recovered statically 2026-08-07.

## The gap

Watch a recorded skirmish and there is no way to change seat. No *next player* / *prior player*
buttons appear, so the camera stays on whichever player recorded it — you cannot see another
side's vision, its palantir, or the spellbook powers it has unlocked. The same replay taken from a
network game offers all of it.

## TL;DR

- The observer bar is the APT clip **`ObserverStuff`**, holding `NextPlayerBttn` and
  `PriorPlayerBttn`. It is shown or hidden once per frame by the palantir's update, at
  `0x006D7809`, through the APT invoke `SetObserverStuffState` (`_show` `0x008003F6` / `_hide`
  `0x0080041A`).
- That decision is the AND of two predicates. The second — *is the local player an observer?* — is
  true in **any** replay. The first (`0x0062541E`) whitelists the **recorded** game mode against
  `{1, 5}`, the two network flavours. **A skirmish records mode 2**, so the bar is hidden for the
  whole playback. That is the entire gap.
- `0x0062541E` has **exactly one caller in the image**, and it is this gate. Nothing else is
  affected by it either way.
- Everything downstream already works. The observer *seat* is installed on the playback game mode
  (3), not on what was recorded; `PlayerList::observeNextPlayer` gates on nothing that cares about
  skirmish; and switching already re-runs the shroud and taint managers for the new seat.
- The engine ships the fix. `0x00625456` is the same predicate with mode 2 added on both sides, is
  the one [`skirmish-replay.md`](skirmish-replay.md) §3 cites as "playback already anticipates a
  mode-2 recording", and has 31 callers. So the patch is **one `call` retargeted**, five bytes,
  no cave.

## 1. Finding the bar

Strings are the entry point, as ever. `ObserverStuff/NextPlayerBttn` (`0xC193DC`) and
`ObserverStuff/PriorPlayerBttn` (`0xC193BC`) each have one reference, in a registration table at
`0x006D6BA4`/`0x006D6BF9` that binds an APT button path to a handler. `SetObserverStuffState`
(`0xC4E4B8`) has two, both APT invokes: `_show` at `0x008003F6` and `_hide` at `0x0080041A`.

Both `_show` and `_hide` have exactly one caller each, five bytes apart:

```asm
006d7809  mov  ecx, [0x00de412c]        ; TheGameLogic
006d780f  test ecx, ecx ; je <hide>
006d7813  call 0x0062541e               ; <-- THE FIVE BYTES
006d7818  test al, al   ; je <hide>
006d781c  mov  ecx, [0x00de4928]        ; ThePlayerList
006d7822  call 0x006a87f5
006d7827  test al, al   ; je <hide>
006d782b  mov  bl, 1 ; jmp
006d782f  xor  bl, bl                   ; <hide>
006d7831  mov  al, [esi+0x7e] ; shr al, 7
006d7837  cmp  bl, al ; je <unchanged>  ; the cached bit: only act on a change
006d783f  call 0x008003f6               ; SetObserverStuffState("_show")
006d7846  call 0x0080041a               ; SetObserverStuffState("_hide")
```

Those 66 bytes are the guard the patch asserts. A bare `call` says nothing about which comparison
it is; the second predicate and the two thunks below it do.

## 2. The two predicates, side by side

`0x006A87F5` is short and not the problem:

```asm
006a87f5  mov  ecx, [ecx+0x10]          ; PlayerList::m_local
006a87f8  call 0x006aac52               ; Player::isPlayerActive
006a87fd  neg al / sbb eax, eax / inc eax   ; return !active
```

and `isPlayerActive` is `!m_isObserver && !m_isDefeated` — `Player+0x35A` and `Player+0x754`, the
same two fields [`replay-outcome.md`](replay-outcome.md) already names. So question 2 is *"is the
local player sitting out"*, which a replay always is (§4).

`0x0062541E` is the one that rejects a skirmish:

```asm
0062541e  call 0x00441b7c               ; GameLogic::isInMultiplayerGame
00625423  test al, al ; jne <true>
00625427  mov  ecx, [0x00de7cd8]        ; TheRecorder
0062542d  test ecx, ecx ; je <false>
00625431  call 0x007b0f25               ; m_mode
00625436  cmp  eax, 1 ; jne <false>     ; PLAYBACK
0062543b  mov  eax, [TheRecorder+0xed4] ; the *recorded* mode
00625446  cmp  eax, 1 ; je <true>
0062544b  cmp  eax, 5 ; jne <false>
```

with the leaf at `0x00441B7C` being `m_gameMode ∈ {1, 5}` — the two network flavours, exactly the
whitelist [`skirmish-replay.md`](skirmish-replay.md) §1 had to widen at the *recording* end.

And immediately after it, at `0x00625456`, sits its sibling:

```asm
00625456  push esi / mov esi, ecx
00625459  call 0x00441b7c               ; live: network
0062545e  test al, al ; jne <true>
00625462  cmp  dword [esi+0x110], 2     ; live: skirmish          <-- added
00625469  je   <true>
0062546b  ...                            ; the same PLAYBACK test
0062548a  cmp  eax, 2 ; je <true>       ; recorded: skirmish       <-- added
0062548f  cmp  eax, 1 ; je <true>
00625494  cmp  eax, 5 ; jne <false>
```

Same convention — thiscall on `TheGameLogic`, no stack arguments, a bool in `al`, and it saves and
restores `esi`, which the caller holds live. It is a drop-in.

**The recorded mode really is 2.** `startPlayback` `fread`s it straight out of the header into
`TheRecorder+0xED4` at `0x0077F788`, and [`skirmish-replay.md`](skirmish-replay.md) §5.1 already
measured that header's trailing block reading `(1, 2, 0, 0)` on a live skirmish. Nothing is
inferred here.

## 3. Why nothing else needs changing

### The observer seat is installed for any playback

```asm
006283d1  cmp  dword [edi+0x110], 3     ; TheGameLogic::m_gameMode == PLAYBACK
006283d8  jne  <not a replay>
006283de  <nameToKey("ReplayObserver")>
006283f5  call 0x006a8466               ; PlayerList::findPlayerWithNameKey
00628401  call 0x006a8559               ; PlayerList::setLocalPlayer
0062840b  push [TheRecorder+0xecc]      ; the recorded local player index
00628417  call 0x006a844e               ; getNthPlayer
00628422  mov  [ControlBar+0x218], eax  ; the initially observed player
```

Mode 3 is mode 3 whatever was recorded, so a skirmish replay already gets a `ReplayObserver` local
player and a seeded observed player. That also settles question 2 of §1 affirmatively — the
observer's `m_isObserver` is set, so `0x006A87F5` returns true.

The `ReplayObserver` slot exists in a skirmish, not only in a network game: the twenty-slot census
in [`fog-of-war.md`](fog-of-war.md) §6 was taken in a live two-player skirmish and found seat 5
holding it, with every one of the 10816 shroud cells visible. Had it been absent,
`setLocalPlayer(NULL)` would fall back to `m_players[0]` (`0x006A8565`) — the neutral player, which
is *active* — and question 2 would fail too. It does not.

### The switch itself has no multiplayer gate

`PlayerList::observeNextPlayer` (`0x006A8D2B`), reached from `AptPalantir::OnBttnObserveNextPlayer`
(`0x006D40F2`) and its prior-player twin:

```asm
006a8d3e  call 0x006a87f5               ; the local player is sitting out
006a8d45  je   <bail>
006a8d51  call 0x006a8839               ; getLocalPlayer
006a8d66  call 0x00441b60               ; GameLogic::isInGame: mode not in {4, 7, 9}
006a8d6b  je   <bail>
```

`0x00441B60` rejects only the shell map (4), 7 and the sentinel 9. Skirmish (2) and playback (3)
both pass. Then it walks `ThePlayerList` for the next seat that is not active and not filtered by
`Player+0x5C`, sets `ControlBar+0x218`, posts the "now observing" message, and:

```asm
006a8eee  mov  eax, [esi+0x54]          ; the new player's index
006a8ef7  call 0x00b4d8e0               ; TheShroudManager, for that seat
006a8f0b  call 0x00ad4960               ; TheTaintManager
006a8f14  call 0x006a8867               ; finish the switch
```

That shroud call is the vision. So everything the user actually wants — camera, fog, palantir,
spellbook — follows the button, and the button is the only thing missing.

## 4. The patch — `0x006D7813`

Retarget the `call`:

```
e8 06 dc f4 ff   ->   e8 3e dc f4 ff
```

`0x006D7818 - 0xB23FA = 0x0062541E`; `0x006D7818 - 0xB23C2 = 0x00625456`. One byte of the
displacement, and the two functions are adjacent, so an off-by-a-few `rel32` lands in real code —
which is why the patch anchors **both** of them by their first bytes before writing.

Four things make it safe:

- **Same signature.** Both are thiscall on `TheGameLogic`, take nothing on the stack, return a
  bool in `al`. `0x00625456` saves and restores `esi`; the caller's `esi` (the palantir) and `ebx`
  (the answer being accumulated) both survive.
- **The call site has no other meaning.** `0x0062541E` has exactly one caller in the image and
  this is it, so retargeting it removes the stock predicate from the running binary entirely
  rather than changing what some other feature sees.
- **Nothing enters the simulation.** `observeNextPlayer` issues no `GameMessage`; it moves a camera
  and re-evaluates a shroud. Like `replay-outcome` and `skirmish-replay`, and unlike
  `production-condition`, this does not have to be on every peer.
- **The guard is the 66-byte run.** The `TheGameLogic` load, the `ThePlayerList` predicate, the
  cached-bit compare against `Palantir+0x7E` and both `SetObserverStuffState` thunks. `verify`
  checks it either side of the call, never across it.

### Why not patch the predicate instead

`0x0062541E` could be rewritten in place to accept mode 2 — it has one caller, so nothing else
would notice. It does not fit in the ten bytes the two `cmp`/`jcc` pairs occupy (three compares
need fifteen), so it would want a cave, and the cave would be a third copy of a mode whitelist the
binary already states twice. Repointing the call reuses the shipped one and leaves a diff that
says exactly what it does.

## 5. What this does *not* do

- **It does not touch the recording end.** A skirmish only records at all with
  [`skirmish-replay`](skirmish-replay.md) applied. The two are independent — either works without
  the other — but this one has nothing to act on until a mode-2 replay exists.
- **It does not make a skirmish replay faithful.** A skirmish AI is not a network participant, so
  its orders were never recorded and playback re-derives it from scratch; switching to the AI's
  seat shows you a divergent AI, not the one that was played against. `message-stream.md` §4c and
  the repo's own measurements say the same thing. **If the replay has to be reviewed, record the
  match in network mode.**
- **It does not add a UI.** The bar it reveals is the stock one, in the stock place.
- **It does have one live-game spillover.** `0x00625456` also answers true for a *live* skirmish,
  so the bar appears in a live game against the AI once the local player is an observer or has
  been defeated. That is exactly what the stock engine does in a live network game under the same
  condition; it cannot appear while you are still playing, because the second predicate is false
  for an active player.

## Status

**Statically derived, applied, verified against the installed `game.dat`, and watched in
game.** What a session confirms:

1. A recorded skirmish, played back, shows the next/prior player buttons.
2. Clicking through changes the camera *and* the fog — a seat's own base visible, the others not.
3. The palantir redraws for the observed player, spellbook included.
4. A network replay still behaves exactly as before.

## Address index

The observer bar: `ObserverStuff/NextPlayerBttn` `0xC193DC` → handler `0x006D4E0C` (which looks up
the `NonCommand_ObserveNextPlayer` command button) · `PriorPlayerBttn` `0xC193BC` → `0x006D4E67` ·
`AptPalantir::OnBttnObserveNextPlayer` `0x006D40F2` / `...Prior` `0x006D4102`, both calling
`PlayerList::observeNextPlayer` `0x006A8D2B` · `SetObserverStuffState` `0xC4E4B8`, `_show`
`0x008003F6`, `_hide` `0x0080041A` · the visibility gate `0x006D7809`, its `call` **`0x006D7813`**,
its cached bit `Palantir+0x7E` bit 7.

The predicates: `GameLogic::isInMultiplayerGame` `0x00441B7C` (`m_gameMode ∈ {1,5}`) ·
`GameLogic::isInGame` `0x00441B60` (mode ∉ {4,7,9}) · **`0x0062541E`** (network, or a replay of
one — one caller) · **`0x00625456`** (that, plus skirmish live and recorded — 31 callers) ·
`PlayerList::localPlayerIsNotActive` `0x006A87F5` · `Player::isPlayerActive` `0x006AAC52`
(`!m_isObserver && !m_isDefeated`, `Player+0x35A` / `Player+0x754`) · `RecorderClass::m_mode`
getter `0x007B0F25`.

The observer seat: the playback install `0x006283D1` · `"ReplayObserver"` `0xBFD4A8` ·
`"FactionObserver"` `0xBFD484` · `PlayerList::findPlayerWithNameKey` `0x006A8466` ·
`PlayerList::setLocalPlayer` `0x006A8559` (NULL falls back to `m_players[0]` at `0x006A8565`) ·
`getNthPlayer` `0x006A844E` · `getLocalPlayer` `0x006A8839` · `ControlBar+0x218`, the observed
player · `TheRecorder+0xECC`, the recorded local player index (written at `0x0077F4A5`) ·
`TheRecorder+0xED4`, the recorded game mode (`fread` at `0x0077F788`).

`TheGameLogic` `0x00DE412C` (`m_gameMode` `+0x110`) · `ThePlayerList` `0x00DE4928` (`m_local`
`+0x10`, count `+0x14`, players `+0x18`) · `TheRecorder` `0x00DE7CD8` · `TheControlBar` `0x00DE7744`
· `TheShroudManager` `0x00DE4358` (per-seat refresh `0x00B4D8E0`) · `TheTaintManager` `0x00DE435C`
(`0x00AD4960`).
