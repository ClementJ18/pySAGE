# Recording a skirmish — reverse-engineering notes

The RE behind [`patches/skirmish_replay.py`](../patches/skirmish_replay.py). ROTWK `game.dat`
build `2.01.2614.37001`, ImageBase `0x400000`, recovered statically 2026-07-31.

## The gap

The stock engine records network games and nothing else. Start a skirmish from the menu, play
it, win it — no `.BfME2Replay` appears, and `Last Replay.BfME2Replay` still holds whatever LAN
game you played last.

## TL;DR

- `RecorderClass::startRecording` (`0x0077EA03`) has **exactly one caller**: the `MSG_NEW_GAME`
  branch of `RecorderClass::updateRecord` (`0x0077F8B0`). That branch is the entire decision.
- It whitelists the message's game mode against `{1, 5}` — the two network flavours. **A
  skirmish emits mode 2**, so it falls off the end of the list.
- Nothing else is in the way. `startRecording` already has a complete non-network path that
  builds the header's metadata string from `TheSkirmishGameInfo`, and the engine's own playback
  predicate at `0x00625456` already accepts a *recorded* mode of 2.
- So the patch replaces nine bytes: the `cmp eax, 5` / `jne` tail of the whitelist becomes a
  jump into a cave that tests 5 plus a table.
- The second half is naming. Every recording is written to `Last Replay.BfME2Replay` and
  overwrites the last one, so the patch also retargets the `call` at `0x0077EA45` that asks for
  the base name, and writes `YYYY-MM-DD HH-MM-SS <map>` instead. By default that applies to
  **every** recording (§5), because a fixed name is exactly what makes replays impossible to
  collect from other players.
- **The mode must be read from `startRecording`'s argument, not from
  `RecorderClass::m_gameMode`.** `startRecording` calls `reset()` before it names the file, and
  that stomps the cached mode with the sentinel 9 (§5.1). Getting this wrong is silent: the
  recording still happens, it just keeps the stock name.

## 1. What starts a recording

`updateRecord` walks `TheCommandList` and branches on the message type. `0x1E`
(`MSG_NEW_GAME`) is the only branch that can begin a recording:

```asm
0077f8d1  cmp  eax, 0x1e
0077f8d4  jne  0x77f977                 ; -> the MSG_CLEAR_GAME_DATA branch, and then orders
0077f8da  push ebp                      ; 0
0077f8db  mov  ecx, esi
0077f8dd  call 0x710c9e                 ; GameMessage::getArgument(0)
0077f8e2  mov  eax, [eax]               ; ... ->integer: the game mode
0077f8e4  cmp  eax, 4    ; je 0x77f9dd  ; the shell map
0077f8ed  cmp  eax, 7    ; je 0x77f9dd
0077f8f6  mov  ecx, [0xde412c]          ; TheGameLogic
0077f8fc  cmp  dword [ecx + 0x114], 3
0077f903  jne  0x77f9dd
0077f909  xor  ebx, ebx ; inc ebx       ; ebx = 1, the default arg1
0077f90c  cmp  eax, ebx  ; je 0x77f919  ; mode 1 -> record
0077f910  cmp  eax, 5                   ; <-- THE NINE BYTES
0077f913  jne  0x77f9dd                 ;     the epilogue: record nothing
0077f919  <read args 1..3, call startRecording>
```

`0x0077F9DD` is `pop ebx / pop edi / pop esi / pop ebp / pop ecx / ret` — the function
epilogue. Every rejected mode simply leaves.

Three tests, and only one of them is doing any work:

- **`arg0 != 4` and `arg0 != 7`** are redundant against the whitelist below them: neither 4 nor
  7 is 1 or 5. They are free bytes, which is what makes an in-place rewrite of the whole gate
  feasible if a cave were ever unwanted.
- **`TheGameLogic+0x114 == 3`** is satisfied by any game started from the shell. Outside a
  savegame load (`0x0082BC22`, which restores it through the `Xfer` alongside `+0x110`), the
  only writer in the image is `0x00779F20` — the `MSG_CLEAR_GAME_DATA` handler, which sets it
  to 3 on the way back to the menu. It is a coarse game-type field distinct from `+0x110`, the
  real game mode; `VictoryConditions::reset` reads it to pick flavour 3 over 2
  (`0x00808A93`), and the score-screen string at `0xC4F0E4` is `MPorSkirmishFadeToScoreScreen`.
- **`arg0 ∈ {1, 5}`** is the actual gate.

## 2. The mode enum, and why 2 is the answer

`GameLogic::startNewGame` (`0x0077948E`) stores the message's argument 0 into
`TheGameLogic+0x110`, so it is *the* game mode. Every emitter that names a constant:

| mode | emitter | what it is |
|---|---|---|
| 1 | `0x00612339`, `0x006494C3` | recorded |
| **2** | `0x00928817`, `0x0063CB7B` | **skirmish** |
| 3 | `0x0077F7D8` | `RecorderClass::startPlayback` — replay |
| 4 | `0x0075DEE2` | the shell map (`startNewGame`: `if (m_110 != 4) hide the shell`) |
| 5 | `0x00904654` | recorded |
| 6 | `0x0091BAAA`, `0x009C50D4` | — |
| 7 | `0x0091A06C` | — |

**Mode 2 is the skirmish menu's.** `0x00928817` is inside `Skirmish.apt`'s start-game handler,
in the same function region that allocates `TheSkirmishGameInfo`:

```asm
009288ee  push 0xe9c                    ; sizeof(SkirmishGameInfo)
00928905  call 0x628b3a                 ; its constructor
00928914  mov  [0xde8930], ecx          ; TheSkirmishGameInfo
...
00928807  push 0x1e ; call [eax+0x48]   ; appendMessage(MSG_NEW_GAME)
0092880c  neg  bl / sbb ebx, ebx
00928814  and  ebx, 2
00928817  push ebx                      ; arg0 = 2 on a real multiplayer map, else 0
0092881d  push 1                        ; arg1
00928826  push esi (0)                  ; arg2
```

Corroborated independently by the command-line map launch at `0x0063C5E2`, which pushes the
same `2` on the branch that builds a `SkirmishGameInfo` and `0` on the branch that does not.

And **mode 1 is what a real recording carries.** `startRecording` writes its four arguments into
the header's trailing block, which `sage_replay` reads as the last four words of `unknown_tail`
(or the tail of `custom_hero_tail` when a Create-A-Hero is present). Every replay in
[`tests/sage_replay/fixtures`](../../tests/sage_replay/fixtures) and every replay on a real
install reads `(arg1, mode, arg2, arg3) = (1, 1, 0, 0)`.

## 3. Why nothing downstream needs changing

### `startRecording` already has a non-network path

```asm
0077ec93  cmp  dword [0xde4468], 0      ; the network session object
0077ec9e  je   0x77ed54                 ; -> the local path
...                                     ; the network path: [0xde4394]'s GameInfo, or [0xde7d6c]
0077ed54  mov  eax, [0xde8930]          ; TheSkirmishGameInfo
0077ed59  test eax, eax ; je 0x77eda0   ; -> the recorder's own embedded GameInfo
0077ed6b  mov  [eax + 0xc], ecx         ; REPLAY_CRC_INTERVAL, clamped to 100
0077ed79  call 0x8023c1                 ; GameInfoToAsciiString -> the metadata string
```

So the header's `M=`/`MC=`/`SD=`/`S=` fields, the Create-A-Hero blobs and the local-player
index are all already written correctly for a skirmish. The patch adds no header code.

### Playback already anticipates a mode-2 recording

`0x00625456` — a predicate the gameplay code asks constantly — reads:

```asm
00625462  cmp  dword [esi + 0x110], 2   ; live: skirmish
00625469  je   <true>
0062546b  mov  ecx, [0xde7cd8]          ; TheRecorder
00625475  call 0x7b0f25                 ; m_mode
0062547a  cmp  eax, 1 ; jne <false>     ; PLAYBACK
0062547f  mov  eax, [TheRecorder + 0xed4]  ; the *recorded* mode
0062548a  cmp  eax, 2 ; je <true>
0062548f  cmp  eax, 1 ; je <true>
```

A recorded mode of 2 is a case the engine already handles. It just could never occur.

### AI slots are already attested

`Test Edain.BfME2Replay` in the corpus is one human and seven `CB` (Brutal computer) slots. The
metadata serializer needs nothing new for a skirmish's roster.

## 4. The gate patch — `0x0077F910`

Nine bytes (`83 F8 05 0F 85 C4 00 00 00`) become `jmp <cave>` plus four `nop`. The cave:

```asm
    cmp  eax, 5                 ; the mode the replaced bytes tested
    je   accept
    push ecx / push edx
    mov  ecx, [mode_count]
    mov  edx, mode_table
scan:
    test ecx, ecx ; je reject
    cmp  eax, [edx] ; je hit
    add  edx, 4 ; dec ecx ; jmp scan
hit:
    pop edx / pop ecx
accept:
    jmp  0x0077F919             ; the recorder's own accept
reject:
    pop edx / pop ecx
    jmp  0x0077F9DD             ; the recorder's own epilogue
```

Four things make this safe:

- **Mode 1 is not re-tested.** The `cmp eax, ebx / je` that accepts it is above the bytes taken
  and is left alone, so `ebx` is still 1 when `startRecording` is reached — it is the default
  `arg1` the recorder pushes when the message carries fewer than two arguments.
- **Only `ecx` and `edx` are borrowed**, and both exits restore them. `ebx`/`esi`/`edi`/`ebp`
  belong to the command-list loop.
- **`0x0077F919` reads nothing from flags**, so the cave's own comparisons cannot leak in.
- **The nine bytes have no inbound edge.** The only way to reach `0x0077F910` was the
  fall-through the jump replaces; `0x0077F919` and `0x0077F9DD` are both branch targets from
  above and are untouched.

The guard is the 63-byte run from `0x0077F8D1` — the message-type compare, the argument fetch,
both rejects and the `TheGameLogic` test. A bare `cmp eax, 5` says nothing about which
comparison it is; that context does.

## 5. The naming patch — `0x0077EA45`

### Where the name comes from

```asm
0077ea28  call 0x77de6f     ; getReplayDir()        -> <UserDataDir>\Replays\
0077ea45  call 0x77defd     ; getLastReplayFileName() -> TheGameText->fetch("GUI:LastReplay")
0077ea6c  call 0x77dee3     ; getReplayExtension()  -> ".BfME2Replay"
0077eaaa  call [0xbd052c]   ; _wfopen(dir + name + ext, L"wb")
```

`0x0077DEFD` falls back to the literal `00000000` when `TheGameText` is null, which is where the
`00000000.rep` names in older SAGE games come from. Localized, it is `Last Replay`.

**The helper has a second caller.** `0x00817E49` is the replay menu rebuilding exactly
`Last Replay` + `.BfME2Replay` to find that entry in the list. So the patch retargets the *call
site* inside `startRecording`, not the helper: the file gets a new name, and the menu goes on
finding the file it expects.

### 5.1 The trap: `m_gameMode` is already gone

The first version of this patch decided whether to rename by reading `TheRecorder + 0xED4`, the
mode `updateRecord` caches at `0x0077F923` immediately before calling `startRecording`. That is
wrong, and it fails silently — the skirmish records, but keeps the stock name.

`startRecording`'s **first** act is `reset()` (vtable `+0x24`, `0x0077D86C`), which tail-jumps
through vtable slot `+0x04` to `0x0077D7C1`, and there:

```asm
0077d7d2  mov dword [esi + 0xed4], 9      ; m_gameMode = 9
```

That runs at `startRecording+0x1A`, forty bytes before the file is named at `+0x42`. So by the
time anything inside `startRecording` looks at the field, it reads **9** — always, for every
game type.

Confirmed live, mid-skirmish, which is also what settled the whole investigation:

| read | value |
|---|---|
| `TheGameLogic+0x110` (game mode) | **2** — skirmish, as derived in §2 |
| `TheGameLogic+0x114` (game type) | **3** — the gate's third test passes |
| `TheRecorder+0x1C` (recorder mode) | **0** = RECORD — the gate patch works |
| `TheRecorder+0xED4` (cached mode) | **9** — the sentinel, not the mode |
| the header the same call wrote | tail `(1, **2**, 0, 0)` |

The header is the authority: `startRecording` writes its four arguments into the trailing block
at `0x0077EFBB`, and the second of them read back as **2**. The mode is right there on the
stack; only the cache is stale. So the routine reads `[ebp+0x0C]` — `startRecording`'s own
second argument, on the frame its SEH prologue established, and by construction the value the
replay will claim it was recorded at.

### 5.2 The routine

cdecl with one argument — the uninitialised `UnicodeString` storage `startRecording` wants the
name constructed into (`lea eax, [ebp-0x14] / push eax`, cleaned by the `pop ecx` after) — and
it returns that storage in `eax`.

1. **Decide** — only when `rename="added"`. Read `[ebp+0x0C]` and walk the same mode table the
   gate uses. Not one of ours ⇒ tail-`jmp` to `0x0077DEFD`; the argument is still on the stack
   exactly as the helper wants it, and its `ret` and its `eax` are already the right answer.
   Under the default `rename="all"` there is nothing to decide and this block is not emitted,
   so the routine never touches the caller's frame at all.
2. **Timestamp.** `GetLocalTime` into a `SYSTEMTIME` in the cave. stdcall, so it cleans its own
   argument — `startRecording` calls it the same way at `0x0077EBB1` for the header.
3. **Map.** `TheGameInfo` (`0x00DE892C`) if set, else `TheSkirmishGameInfo` (`0x00DE8930`); the
   skirmish setup screen assigns one to the other at `0x006309BF`. `GameInfo::m_map` is an
   `AsciiString` at `+0x40` — `getMap` (`0x00627692`) is a plain copy of it and `setMap`
   (`0x00801C46`) writes it — so the cave reads the member rather than constructing a copy it
   would then have to destruct. An `AsciiString` is one pointer, characters at `+8`.
4. **Basename, widen, sanitise.** `M=` carries `maps/map mp westfold`, so the text after the
   last `/` or `\` is taken, widened a byte at a time, capped at 63 characters, and anything
   outside printable ASCII or in `<>:"/\|?*` replaced with `_`. Widening by hand rather than
   with `swprintf`'s `%S` is what keeps the result independent of the ANSI code page.
5. **Format.** `swprintf(name, L"%04d-%02d-%02d %02d-%02d-%02d %s", …)` — cdecl variadic, nine
   dwords cleaned by the caller, `SYSTEMTIME`'s 16-bit fields zero-extended because `%d` reads a
   full dword.
6. **Construct.** `UnicodeString::UnicodeString(const WideChar *)` (`0x00437770`, thiscall,
   `ret 4`). It zeroes the object before assigning, which is what makes it correct on
   uninitialised storage; it is the same one `getReplayExtension` uses for its literal.

Result: `2026-07-31 09-54-12 map mp westfold.BfME2Replay`. Chronological sort order, and the map
is last so a long name loses the map rather than the timestamp.

### 5.3 What the rename scope costs

`rename="all"` (the default) renames every recording, network games included. Exactly one thing
depends on the fixed name, and it is worth knowing what it is.

`0x00817D0E` is command **7** of the replay menu's dispatch (`cmp eax, 7 / call` at
`0x00819693`). It rebuilds `Last Replay` + `.BfME2Replay`, hands the path to `0x0077FDF0`, and
reports `APT:ReplaySaveCompleteMessageBox` or `APT:ReplaySaveErrorMessageBox`. That is the
**Save Replay** button: it copies the fixed-name file to a name the user types.

With nothing at that path it takes the error branch. The loss is not a real one — the button
exists *only* to rescue a recording before the next game overwrites it, which is the problem the
rename removes. Every replay already has a unique, meaningful, shareable name.

`rename="added"` keeps the stock name for anything the engine would have recorded anyway, so
Save Replay goes on working for network games and only skirmishes get the new naming. It is the
right setting for someone who wants the skirmish fix and nothing else changed.

Neither setting affects the header: the replay's `filename` field is a *display* string fetched
separately at `0x0077EB56` and still reads `Last Replay` in both.

## 6. What this does *not* do

- **It does not add a UI.** Replays appear in the replay list as ordinary files. Under
  `rename="all"` the Save Replay button stops working (§5.3), by design.
- **It does not clean up.** Uniquely named files are never overwritten, so the Replays folder
  grows without bound.
- **It does not leave a skirmish's message stream identical.** `startRecording` writes the
  clamped `REPLAY_CRC_INTERVAL` into the `GameInfo` (`0x0077ED6B`), so a recorded skirmish
  starts emitting `MSG_LOGIC_CRC` (`0x44A`) every 100 frames — recorded, like every other
  message in the network range, and harmless with no peer to disagree with, but real.
- **It does not change what any other client sees.** Both edits are inside one client's
  recorder. Like `replay-outcome` and unlike `production-condition`, it does not have to be on
  every peer.

## Status

**The gate is runtime-verified (2026-07-31). The naming is fixed but not yet re-tested.**

What the first in-game test proved, reading the live process mid-skirmish and parsing the
recording the same session was writing:

- ✅ **A skirmish records.** `TheRecorder+0x1C` read 0 (RECORD) with a live `FILE*` at `+0x10`,
  and `Last Replay.BfME2Replay` was on disk, growing, timestamped to the match start.
- ✅ **The mode is 2**, exactly as §2 derives. `TheGameLogic+0x110` read 2, and the header the
  same call wrote carries `(1, 2, 0, 0)` in its trailing block.
- ✅ **`TheGameLogic+0x114` is 3** in the menu *and* in a skirmish, so the branch's third test —
  the one open question that could have changed the patch's shape — is satisfied.
- ❌ **The naming did nothing.** It read `TheRecorder+0xED4` for the mode, which `reset()` has
  already overwritten with 9 (§5.1), so it fell back to the stock helper every time. Fixed by
  reading `startRecording`'s own argument instead.

The failure was invisible from outside: recordings were happening from the first build, all of
them into `Last Replay.BfME2Replay`, each overwriting the last — which looks exactly like
nothing being recorded at all.

Open, and needing one more session:

1. A finished skirmish writes `<timestamp> <map>.BfME2Replay`, and
   `sage_replay.parse_replay_from_path` parses it clean (the chunk stream ends exactly at EOF
   and the header's `num_timecodes` matches the last chunk's timecode).
2. The map name comes out as expected. `GameInfo::m_map` is a full path with backslashes and a
   `.map` file on the end (`maps\map wor forlindon\map wor forlindon.map`, read live), so the
   basename scan and the extension strip both have to fire to give `map wor forlindon`.
3. **The recording plays back in-game.** The highest residual risk: §3 argues the engine
   anticipates a mode-2 recording, but no such file has ever existed.
4. A LAN or online game still records. Under `rename="all"` it now also gets the new name, and
   Save Replay reports its error box (§5.3) — expected, not a regression.
5. Stacked with `replay-outcome`, a skirmish carries `0x7D0` chunks naming the winner. That
   combination is the only way `sage_replay` can resolve a game against an AI at all, since the
   concession heuristic needs orders and an AI issues none.

## Address index

`RecorderClass::update` `0x007800BB` (vtable `0x00C2EF80` slot `+0x28`; dispatches to
`updateRecord` when `m_mode` is RECORD **or** NONE, which is why a skirmish reaches it at all) ·
`RecorderClass::updateRecord` `0x0077F8B0` (reached only by the `jmp` at `0x007800D1`) · its
`MSG_NEW_GAME` branch `0x0077F8D1` · the game mode whitelist `0x0077F910` (9 bytes,
`cmp eax, 5` / `jne`) · accept `0x0077F919` · reject `0x0077F9DD` · `startRecording` `0x0077EA03`
(its only caller is `0x0077F96E`; mode argument at `[ebp+0x0C]`, written to the header at
`0x0077EFC7`) · `reset` `0x0077D86C` (vtable `+0x24`) → `0x0077D7C1`, which sets `m_gameMode` to
the sentinel 9 at **`0x0077D7D2`** · `m_gameMode` `+0xED4` (cached at `0x0077F923`, stale by
`0x0077EA45`) · the replay menu's Save Replay `0x00817D0E` (command 7, dispatched at
`0x00819693`; the copy at `0x0077FDF0`, the message boxes at `0x00C50148`/`0x00C50168`) ·
the local/network branch `0x0077EC93` on
`[0x00DE4468]` · the `GameInfo` CRC-interval store `0x0077ED6B` · `GameInfoToAsciiString`
`0x008023C1`.

`getReplayDir` `0x0077DE6F` (`<UserDataDir>\Replays\`, the literal at `0x00C2EEF0`) ·
`getLastReplayFileName` `0x0077DEFD` (`GUI:LastReplay`, fallback `00000000` at `0x00C2EED0`;
second caller `0x00817E49`) · `getReplayExtension` `0x0077DEE3` (`.BfME2Replay` at `0x00C2EEB4`)
· the name call site `0x0077EA45` · `_wfopen` `[0x00BD052C]`.

`TheGameLogic` `0x00DE412C` · `m_gameMode` `+0x110` (written by `startNewGame` `0x0077948E`) ·
the coarse game type `+0x114` (set to 3 at `0x00779F20`, restored by the `Xfer` at `0x0082BC22`)
· `GameLogic`'s message dispatcher `0x00779A3D`, its `MSG_NEW_GAME` case `0x00779D40`.

`TheGameInfo` `0x00DE892C` · `TheSkirmishGameInfo` `0x00DE8930` (allocated `0x009288EE`, ctor
`0x00628B3A`, `sizeof` `0xE9C`, vtable `0x00BFD668` with `isSkirmish` `+0x48` / `isMultiplayer`
`+0x4C` / `isSandBox` `+0x50`) · `TheGameInfo = TheSkirmishGameInfo` `0x006309BF` ·
`GameInfo::m_map` `+0x40` · `getMap` `0x00627692` · `setMap` `0x00801C46`.

The skirmish start handler `0x009287D9` (`MSG_NEW_GAME` at `0x00928807`, mode at `0x00928817`) ·
the command-line map launch `0x0063C5E2` (mode at `0x0063CB7B`) · `startPlayback`'s
`MSG_NEW_GAME` `0x0077F7D8` (mode 3) · the shell-map start `0x0075DEE2` (mode 4) ·
`0x00625456`, the predicate that accepts a recorded mode of 2.

`UnicodeString::UnicodeString(const WideChar *)` `0x00437770` · `swprintf` `[0x00BD0490]` ·
`GetLocalTime` `[0x00BD01D4]`.
