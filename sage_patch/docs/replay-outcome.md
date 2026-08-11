# Writing the match outcome into a replay — reverse-engineering notes

The RE behind [`patches/replay_outcome.py`](../patches/replay_outcome.py). ROTWK `game.dat`
build `2.01.2614.37001`, ImageBase `0x400000`, recovered statically 2026-07-31.

## The gap

> A replay records inputs, not state: eliminations are computed by the simulation and never
> written to the stream, so no chunk says who won.
>
> — [`sage_replay/winner.py`](../../sage_replay/winner.py)

That is true of the stock engine, and it is why `sage_replay`'s winner module is a *concession
heuristic*: it reads who stopped issuing orders and assumes leaving means losing. It answers
`undetermined` for every game that ended by elimination, and it cannot see AI players at all,
because an AI issues no orders.

The engine knows the answer perfectly well. It just never writes it down.

## TL;DR

- `VictoryConditions` (`TheVictoryConditions` = `0x00DE89AC`) holds a per-player defeat latch
  and two predicates that resolve teams. That is the answer, live, on the logic thread.
- `MSG_CLEAR_GAME_DATA` (`0x1D`), the message that ends a recording, has **thirteen emitters**.
  `GameLogic::clearGameData` (`0x00625E36`) is only the one a mid-match quit takes; a game that
  *finishes* ends through the score-screen code instead. There is no single site upstream.
- The funnel is downstream, in the consumer: `RecorderClass::updateRecord`'s `0x1D` branch
  (`0x0077F977`), which writes the marker and then calls `stopRecording`.
- `RecorderClass` keeps its output `FILE*` at `+0x10` and lays chunks down with plain `fwrite`
  in a format `sage_replay.ReplayChunk` already parses.
- So the patch retargets the 5-byte `call writeToFile` at `0x0077F98B` — inside that branch,
  with `m_file` already proven non-NULL — and writes one extra chunk per player straight to that
  handle, ahead of the `0x1D` marker, at the same logic frame.
- Nothing enters the simulation and nothing crosses the network, so **an unpatched peer is
  unaffected** — unlike `production-condition`, this patch does not have to be on every client.

## 1. Where the outcome lives — `VictoryConditions`

Found the same way the other subsystems were (see
[`engine-globals.md`](engine-globals.md)): the `"TheVictoryConditions"` literal at `0xBFEC68`
is pushed at `0x0063C1A1`, and the object registered right after it comes from the factory at
`0x00808F1E`:

```asm
00808f29  push 0x94                 ; sizeof(VictoryConditions)
00808f2e  call 0x42f6e0             ; operator new
00808f42  call 0x808d3c             ; the constructor
```

The constructor installs vtable `0x00C4F108` and calls `reset` (`0x00808A43`), whose zeroing
loop is what gives the layout away:

```asm
00808a48  lea  edx, [ecx + 0x18]
00808a4b  mov  [edx], ebx           ; m_players[i]     = NULL
00808a4d  mov  [ecx + eax + 0x70], bl   ; m_isDefeated[i] = FALSE
00808a55  cmp  eax, 0x14            ; MAX_PLAYER_COUNT = 20
00808a5a  or   dword [ecx + 0x68], -1    ; m_localSlot = -1
```

| offset | member | how it was read |
|---|---|---|
| `+0x00` | vtable `0x00C4F108` | the constructor |
| `+0x0C` | game-mode flavour (2 or 3) | `reset`, from `TheGameLogic+0x114 == 3` |
| `+0x18` | `Player *m_players[20]` | the `reset` loop; filled by `addPlayer` |
| `+0x68` | `Int m_localSlot` | seeded `-1`; indexes `m_players`, not `ThePlayerList` |
| `+0x70` | `Bool m_isDefeated[20]` | the `reset` loop; the getter at slot `+0x64` returns `[this + i + 0x70]` |
| `+0x84` | `Bool` local player is out | set together with `+0x86` |
| `+0x85` | `Bool` a verdict is possible | set once the first defeat is seen |
| `+0x86` | `Bool` local player is an observer | set when `m_localSlot < 0` |
| `+0x88` | `Int` defeats counted | bumped by `hasBeenDefeated` |
| `+0x8C` | `Int` players registered | the `addPlayer` cursor |
| `0x94` | `sizeof` | the allocation |

### `m_players` is compacted, so index it by nothing

`addPlayer` (vtable `+0x68`, `0x00808BD4`) is called for each of `ThePlayerList`'s 20 slots by
the game-start pass at `0x00808B6A`, and it **skips** the neutral player (`ThePlayerList+0x18`),
any player whose template is null or the default, and observers. Survivors land at
`m_players[m_8C++]`.

So a `VictoryConditions` index is neither a `ThePlayerList` index nor a replay slot index, and
the patch never uses one as an identity — it reads the player's own `m_playerIndex` instead
(§3).

### The three states, and who writes them

**Defeat is a latch**, set exactly once, inside `VictoryConditions::update` (`0x00808F53`):

```asm
0080906a  lea  edi, [esi + eax + 0x70]  ; &m_isDefeated[i]
0080906e  cmp  byte [edi], 0
00809071  jne  <next>                   ; already latched
0080907c  call dword [eax + 0x40]       ; this->hasBeenDefeated(player)
00809081  je   <next>
0080908a  mov  byte [edi], 1            ; <-- the transition, once per player
0080908d  mov  ecx, [0xde412c]
00809093  call 0x625f7c                 ; TheGameLogic: stamp the defeat frame for slot i
0080909e  mov  [ebx + 0x4cc], eax       ; player->m_defeatedFrame = current frame
```

That last store is why the chunk can carry *when* a player lost, not just that they did:
`Player+0x4CC` holds the frame of the transition.

**`hasBeenDefeated`** is vtable `+0x40` (`0x0080953C`) — the predicate everything in the engine
asks. It short-circuits on `Player+0x754`, the player's own hard defeat flag (set by the object
census at `0x006ABE9E`/`0x006ABEFD` when nothing that `MP_COUNT_FOR_VICTORY` counts is left, and
by a quit), and otherwise runs the full per-mode computation at `0x00809404`.

**`hasAchievedVictory`** is vtable `+0x38` (`0x00808AA8`): gated on a defeat having happened at
all (`m_85`, `m_88 > 0`), it walks `m_players` for an undefeated player that is the queried one
or a mutual ally of it — `0x008089F2` compares both directions through
`Player::getRelationship` (`0x006ADBEB`) for `ALLIES` (2), which is what makes it correct for
teams and not just for 1v1.

Both are already called every frame by the stock UI (`didLocalPlayerWin` at vtable `+0x48`
reaches `hasAchievedVictory` through `m_players[m_localSlot]`), which is the argument that the
cave calling them once more at teardown is not a new class of side effect.

## 2. Where a chunk can be written — `RecorderClass`

`TheRecorder` = `0x00DE7CD8`.

| offset | member | evidence |
|---|---|---|
| `+0x10` | `FILE *m_file` | closed with `fclose` in `stopRecording`, `fwrite` target everywhere else |
| `+0x1C` | `Int m_mode` | constructor writes 2, `startRecording` (`0x0077EA03`) zeroes it, `startPlayback` writes 1 |
| `+0x24` | embedded `GameInfo` | the 8-slot walk in `isMultiplayer` (`0x0077D627`) |

So `RECORD = 0`, `PLAYBACK = 1`, `NONE = 2` — and because `m_file` is *also* the handle a
playback reads from, "am I recording" needs both `m_mode == 0` and `m_file != NULL`.

### `RecorderClass::writeToFile` (`0x0077D8FC`) — the chunk format, from the writer

```asm
0077d909  mov  eax, [0xde412c]; mov eax, [eax+0x40]  ; TheGameLogic->m_frame
0077d92a  call fwrite                                ; 4 bytes: the timecode
0077d932  mov  eax, [edi + 0x10]                     ; GameMessage::m_type
0077d940  call fwrite                                ; 4 bytes
0077d945  mov  eax, [edi + 0x14]                     ; GameMessage::m_playerIndex
0077d953  call fwrite                                ; 4 bytes
...                                                  ; unique-type count, (type,count) pairs
0077da22  call fflush
```

Three points that matter:

- the **timecode is read from `TheGameLogic`, not from the message** — so anything writing its
  own chunk lands on the right frame simply by reading the same place;
- the player field is `GameMessage+0x14`, which the `GameMessage` constructor
  (`0x00710C36`) fills from `[[ThePlayerList] + 0x10] + 0x54` — the *local player's*
  `m_playerIndex`;
- it flushes after every chunk.

`fwrite` is `[0x00BD053C]` and `fflush` is `[0x00BD065C]` (`msvcr71.dll`, confirmed by name in
the import directory).

### `RecorderClass::updateRecord` (`0x0077F8B0`) — what gets recorded, and the `0x1D` case

```asm
0077f8b1  mov  eax, [0xde639c]; mov esi, [eax+0xc]   ; TheCommandList's first message
0077f8ce  mov  eax, [esi + 0x10]
0077f8d1  cmp  eax, 0x1e                             ; MSG_NEW_GAME -> startRecording
0077f977  cmp  eax, 0x1d                             ; MSG_CLEAR_GAME_DATA
0077f98b  call 0x77d8fc                              ;   writeToFile(msg)
0077f992  call 0x77d8c8                              ;   stopRecording()
0077f9a6  cmp  eax, 0x3e8 ; jle <skip>               ; otherwise: 1000 < type
0077f9ad  cmp  eax, 0x7cf ; jge <skip>               ;            type < 1999
0077f9b7  call 0x77d8fc                              ;   writeToFile(msg)
```

This settles two things at once.

**`0x1D` is `MSG_CLEAR_GAME_DATA`** — the id `sage_replay` calls `EndOfRecording`. It is the
message that makes the recorder write its last chunk and close the file.

**The recordable range is the network range**, `1001..1998`. Which is the reason this patch does
*not* inject a message: anything in that range is relayed to every peer and executed by all of
them, so carrying a verdict that way would put a new message type on the wire and make the patch
a desync risk every client had to share. Writing the bytes directly keeps it client-local.

It also fixes the order type to use. The `GameMessage::Type` enum stops at `0x47B` (see
[`message-stream.md`](message-stream.md)), and the recorder copies nothing at or above `0x7CF`,
so **`0x7D0` is unreachable for the engine** — a chunk of that type came from this patch or from
nowhere.

### The header stays consistent

`stopRecording` (`0x0077D8C8`) calls `0x0077D2E9`, which seeks and back-patches the header:
`end_time` at `0x0C` (from `time()`, `[0x00BD0508]`) and `num_timecodes` at `0x10` (from
`TheGameLogic->m_frame`). The periodic `0x0077D251` does the same for `crc_interval` at `0x14`
(the constant at `0xDA1880`, **100** — `REPLAY_CRC_INTERVAL`) and the abnormal-end frame at
`0x18`. All four match the layout `sage_replay.ReplayHeader` parses.

Because our chunks carry the same frame the `0x1D` marker will, `num_timecodes` still equals the
last chunk's timecode and `parse_replay`'s consistency check passes unchanged.

## 3. The hook — `RecorderClass::updateRecord`'s `0x1D` branch (`0x0077F98B`)

### Why not `GameLogic::clearGameData`

`GameLogic::clearGameData` (`0x00625E36`) reads like the single funnel both endings pass
through:

```asm
00625e36  cmp  byte [esp+4], 0        ; leaving?
00625e3e  je   0x625e7e
00625e6d  push 0x448                  ; MSG_SELF_DESTRUCT — the voluntary leave-game order
00625e84  call 0x5ea8a5               ; <-- the tempting hook site
00625e91  push 0x1d                   ; MSG_CLEAR_GAME_DATA
00625e93  call dword [eax+0x48]
```

**It is not.** Hooked there, a *leave* writes both chunks while a *win* and a *loss* write
nothing at all and still carry a `0x1D` chunk of their own. A scan for every `push 0x1D` feeding
`appendMessage` explains it — there are **thirteen** such sites, not one:

| site | reached by |
|---|---|
| `0x00625E91` | `GameLogic::clearGameData` — a mid-match quit |
| `0x009C5088`, `0x00919BB5`, `0x0091A041`, `0x0091B0DA`, `0x0092292C` | the window/score-screen code — **this is where a finished game ends** |
| `0x0075DEB7`, `0x0075DF1A` | the shell/ControlBar paths |
| `0x0065DF45`, `0x0065E6A3`, `0x006BE7C2`, `0x0062CA71` | menu and logic paths |
| `0x0077D8C2` | `RecorderClass`'s own playback teardown |

A patch hooking any one of them covers one ending. The lesson is the general one: *one* caller
being on the path is not evidence that it is the *only* caller, and the cheap check —
pattern-scan the whole image for the constant being pushed — takes a minute.

### The right site

Every one of those thirteen emitters puts the message on `TheCommandList`, and exactly one place
consumes it:

```asm
0077f977  cmp  eax, 0x1d                  ; RecorderClass::updateRecord
0077f97a  jne  <ordinary order>
0077f97c  cmp  [edi+0x10], ebp            ; m_file != NULL
0077f97f  je   <nothing to write>
0077f981  or   dword [0xda570c], -1
0077f988  push esi                        ; the GameMessage *
0077f989  mov  ecx, edi
0077f98b  call 0x0077d8fc                 ; writeToFile(msg)   <-- THE HOOK SITE
0077f990  mov  ecx, edi
0077f992  call 0x0077d8c8                 ; stopRecording() — closes the file
```

Hooking the `writeToFile` call puts the cave **between the last order and the end marker**, and:

- it fires for every ending, whichever emitter appended the message;
- `m_file` is already proven non-NULL by the branch two instructions above;
- `stopRecording` has not run, so the file is still open — this is the last moment anything can
  be appended to a recording;
- it is a 5-byte `call rel32`, so retargeting needs **no displaced instruction**: the cave
  tail-`jmp`s to `0x0077D8FC`, whose own `ret 4` returns to `0x0077F990` and pops the
  `GameMessage *` the recorder pushed.

The five bytes are safe to take. A sweep of `.text` for every `call`/`jmp`/`jcc` (rel8 and
rel32) landing anywhere in `0x77F98B..0x77F98F`, plus a scan of the whole image for a stored
pointer to any of them, finds **nothing** — so no branch enters the site and no table names it.
That matters more here than at a function entry: taking bytes mid-function is exactly where a
missed inbound edge lands in the middle of an instruction.

The guard is a 20-byte fingerprint of `0x0077F977` onward — the `cmp eax, 0x1D`, the `m_file`
test and the `mov ecx, edi` that sets up the call — because the site itself is a bare `call` and
nothing about those five bytes says which one it is.

### Ordering inside the file

The cave's `fwrite` happens before the tail-jump, so the outcome chunks land immediately ahead
of the `0x1D` chunk, at the same timecode (`writeToFile` reads `TheGameLogic->m_frame`, and so
does the cave). No seek is involved — the handle is at end-of-file, which is where the
recorder's next chunk would have gone.

## 4. The chunk the patch writes

23 bytes, in `writeToFile`'s own layout:

| bytes | field | value |
|---|---|---|
| `0..3` | timecode | `TheGameLogic->m_frame` — the frame the recording ends on |
| `4..7` | order type | `0x7D0` |
| `8..11` | player number | `Player+0x54` (`m_playerIndex`) |
| `12` | unique argument types | `1` |
| `13..14` | `(type, count)` | `(0 Integer, 2)` |
| `15..18` | Integer 0 | outcome: `0` undetermined, `1` victorious, `2` defeated |
| `19..22` | Integer 1 | `Player+0x4CC`, the frame of the defeat, or `0` |

**Why the player number is `m_playerIndex` and not an index of our own.** It is the same field
the engine fills for a human's own orders, so `ReplayFile.slot_index` maps our chunk exactly as
it maps every other one, with no new rule and no new assumption about the `+3` offset the corpus
shows. Whatever that offset is, ours matches by construction.

Per player, the cave answers:

```c
if (player->m_isObserver)                 continue;          /* plays no side */
if (vc->m_isDefeated[i] || player->m_isDefeated)  outcome = DEFEATED;
else if (vc->hasAchievedVictory(player))          outcome = VICTORIOUS;
else                                              outcome = UNDETERMINED;
```

`UNDETERMINED` is the honest answer, not a fallback: it is what everyone but the quitter gets
when the recording player leaves a match that is still live, and `sage_replay` treats a record
naming no winner as no verdict, deferring to the concession heuristic rather than overriding it
with a non-answer.

## 5. What this does *not* do

- **It does not record a defeat that happens after the recording ends.** If the recording player
  quits at frame N, the file ends at frame N and the states written are the states at frame N.
  That is inherent to a replay, not to the patch.
- **It does not make a crashed recording say anything.** A client that never reaches
  `clearGameData` finalizes no header either; there is nothing to attach a verdict to.
- **It does not narrow the outcome for a campaign or a `VictoryConditions` with no registered
  players.** The loop finds nothing and writes nothing, and the replay reads exactly as it did
  before.
- **It does not change what any other client sees.** The one thing the cave mutates outside its
  own section is `VictoryConditions`' defeat counter and `GameLogic`'s per-slot result frames,
  both of which the stock per-frame path already writes, and neither of which the logic CRC
  covers. Runtime confirmation of that is the open item below.

## Status

**Runtime-verified, 2026-07-31**, on two rounds of three recordings from a patched build
(1v1 vs AI, Edain, one recording per ending).

The cave runs on the logic thread, the direct `fwrite` lands where the recorder's next chunk
would have, the file still parses, the header's `num_timecodes` cross-check still passes, and
**the player numbering is right** — the chunks carry 3 and 4, which `ReplayFile.slot_index` maps
to slots 0 and 1 with no special case, AI included.

### Correct on all three endings

| recording | ending | chunks | outcome |
|---|---|---|---|
| 1 | won (AI eliminated) | tc 875, nums 3/4 | `Necro` **victorious**, AI **defeated** @ 795 |
| 2 | lost | tc 462, nums 3/4 | `Necro` **defeated** @ 403, AI **victorious** |
| 3 | left mid-match | tc 47, nums 3/4 | `Necro` **defeated** @ 45, AI **victorious** |

Every chunk lands at the closing frame, immediately ahead of the `0x1D` marker, exactly one per
player. Three further things this settles:

- **`VictoryConditions` is still populated at the consumer.** The subsystem reset has *not* run
  by the time the recorder writes the end marker, so reading the state there is sound and the
  fallback of latching at the transition (`0x00809093`) is not needed.
- **The leave case resolves too, and precisely.** Recording 3's `0x448` is at frame 45 and the
  defeat frame written is 45 — the ~2-frame gap to the `0x1D` at 47 is enough for the leave to
  be applied and for `VictoryConditions::update` to latch it. Hooking this far downstream is
  what buys correct values as well as full coverage.
- **`Player+0x4CC` is the frame of the loss, not of the recording's end.** 795 against a
  close at 875, and 403 against 462.

### What it changes for `sage_replay`

The same three replays with the `0x7D0` chunks stripped, through the concession heuristic alone:

| recording | truth | heuristic alone | recorded |
|---|---|---|---|
| 1 | won | `undetermined` | `decided` → Necro |
| 2 | lost | `undetermined` | `decided` → the AI |
| 3 | left | `recorder_left` | `decided` → the AI |

Both elimination endings — the case the input stream can never explain, made worse here by an AI
opponent that issues no orders at all — go from no answer to the right one.

### Still open

1. **A multiplayer game against an unpatched peer.** The claim that this patch is client-local
   (nothing enters the simulation, nothing crosses the network) is argued from the code but has
   not been played. Both replays should parse and the game should not desync.
2. **Teams.** Every verified recording is 1v1 vs AI, so `hasAchievedVictory`'s ally walk has
   been exercised only in the degenerate case. A 2v2 would test it.
3. **An observer slot**, which the cave skips on `Player+0x35A` and which no recording had.

## Address index

`TheVictoryConditions` `0x00DE89AC` · vtable `0x00C4F108` · `sizeof` `0x94` · ctor `0x00808D3C` ·
factory `0x00808F1E` · `reset` `0x00808A43` · `update` `0x00808F53` · the defeat latch
`0x0080908A` · `hasAchievedVictory` `0x00808AA8` (slot `+0x38`) · `hasBeenDefeated` `0x0080953C`
(slot `+0x40`) · `m_isDefeated(i)` `0x00808D92` (slot `+0x64`) · `addPlayer` `0x00808BD4`
(slot `+0x68`) · the per-mode defeat computation `0x00809404` · the mutual-ally test
`0x008089F2` · `Player::getRelationship` `0x006ADBEB`.

`Player` `m_playerIndex` `+0x54` · `m_isObserver` `+0x35A` (getter `0x006AAC44`) ·
`m_defeatedFrame` `+0x4CC` · `m_isDefeated` `+0x754` (getter `0x006AAC4B`, written by the object
census at `0x006ABE9E`).

`TheRecorder` `0x00DE7CD8` · `m_file` `+0x10` · `m_mode` `+0x1C` (RECORD 0 / PLAYBACK 1 / NONE 2) ·
`writeToFile` `0x0077D8FC` · `updateRecord` `0x0077F8B0` · `stopRecording` `0x0077D8C8` ·
`startRecording` `0x0077EA03` · `isMultiplayer` `0x0077D627` · header back-patch `0x0077D2E9`
(`end_time` `0x0C`, `num_timecodes` `0x10`) and `0x0077D251` (`crc_interval` `0x14`,
abnormal-end `0x18`) · `REPLAY_CRC_INTERVAL` at `0xDA1880` = 100 · `TheCommandList` `0x00DE639C`
(head `+0x0C`).

`GameLogic::clearGameData` `0x00625E36` (the `0x1D` append at `0x00625E91` — one emitter of
thirteen, **not** the hook site) · the hook site `0x0077F98B` (`call 0x0077D8FC`) inside
`updateRecord`'s `0x1D` branch at `0x0077F977` · `GameLogic::m_frame` `+0x40` · per-slot result records `+0x1C4`,
stride `0x1C`, 8 entries (defeat frame `+0x1CC` via `0x00625F7C`, victory frame `+0x1D0` via
`0x00625F9F`).

`fwrite` `[0x00BD053C]` · `fflush` `[0x00BD065C]` · `fseek` `[0x00BD0648]` · `ftell`
`[0x00BD0654]` · `fclose` `[0x00BD0560]` · `time` `[0x00BD0508]`.
