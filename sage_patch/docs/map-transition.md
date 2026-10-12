# Changing map mid-game from a script, carrying the army with it

Engine build `2.01.2614.37001`, ImageBase `0x400000`, read off the installed `game.dat` with
`explore.py`, and run in game. §2, §3 and §6.1–§6.11 are the engine as read from the disassembly
quoted beside them; §6.13 is the mechanism as built and what running it established; §7 says what
the design refuses to do.

**The goal.** A mapper places one script action, names another `.map`, and the game loads it with
the player's army, resources, powers and script state intact — so a scenario can be larger than a
single map file.

**The shape.** The engine can be walked from one match to another through states it already
reaches on its own — end the match, let it land in the lobby, load the shell map, start the
destination — and a dead script action can be given a body by rewriting one dword. Nothing carries
across that by itself, so the patch owns a snapshot of everything the mapper expects to survive,
and re-materialises it into a world that has just been rebuilt from scratch.

**Status.** [`map-transition`](../patches/experimental/map_transition.py), experimental. **The
transition works in game**: action, teardown, score screen, lobby, shell map, destination. It
carries the local player's army (`KindOf ARMY_SUMMARY` objects, with veterancy, upgrades and
health), script counters, timers and flags, and the player's resources, command-point ceiling,
spellbook points, purchased sciences and completed upgrades. Power cooldowns are out of scope and
the hero revival ledger does not carry yet. §6.12 lists what is open, including a crash six to
twenty seconds into the destination.

## 1. What a map swap destroys

`GameLogic::loadMap` (`0x006314CD`) is a full teardown and rebuild. It parks the asset worker,
runs a dozen subsystem resets, and calls the world builder `GameLogic::startNewGame`
(`0x0062F91A`) at `0x0063157B`, which reads the new map's `SidesList` and constructs players and
objects from it.

So after the swap: every `Object` is gone, every `Player` is a new object built from the new map's
sides, `TheScriptEngine` holds the new map's scripts and none of the old counters, and
`GameLogic::m_frame` has restarted. Nothing the mapper cares about survives on its own. Every item
in the decided scope is therefore something the patch snapshots before the call and replays after
it.

## 2. The transition primitive, already in the binary

`LivingWorldLogic::startCampaign` swaps the running session onto a `ScriptHolder` layout
(see [`living-campaign/script-holder.md`](living-campaign/script-holder.md)). That path is the
worked example of a mid-session map load, and it is four instructions wide:

```asm
006b5320  push 0xc143bc               ; "%s\%s\%s.%s"
006b5326  call 0x437a90               ; AsciiString::format -> TheWritableGlobalData+0xC
006b532b  mov  ecx, [0xde412c]        ; TheGameLogic
006b5334  push 0 ; push 1 ; push 8    ; (mode 8, 1, 0)
006b533a  call 0x77948e               ; GameLogic::startNewGame
006b533f  mov  ecx, [0xde412c]
006b5345  push 0
006b5347  call 0x6314cd               ; GameLogic::loadMap
```

| fact | value | evidence |
|---|---|---|
| both calls are `__thiscall` on `TheGameLogic` | `0x00DE412C` | `ecx` loaded from the global immediately before each |
| `startNewGame` | `0x0077948E`, three args, `ret 0xC` | the function |
| `loadMap` | `0x006314CD`, one arg, `ret 4` | the function |
| the map to load | `TheWritableGlobalData+0xC`, a path with extension | formatted in place above |
| a staged override | `TheWritableGlobalData+0xAC0` | see below |
| the other caller | `0x00779DE5` / `0x00779DEE`, `GameLogic`'s `MSG_NEW_GAME` handler | same pair, same object |

`startNewGame` itself is small and does exactly three things that matter here:

```asm
00779493  mov  ecx, [0xde3bac]        ; TheScriptEngine
0077949b  call 0x603517               ; ScriptEngine+0x1A5C4 = 1
007794b3  mov  ecx, [0xde412c]
007794b9  mov  [ecx + 0x110], eax     ; the game mode
007794bf  mov  esi, [0xde4364]        ; TheWritableGlobalData
007794c5  lea  edi, [esi + 0xac0]     ; the staged map name
007794cd  call 0x401e64               ; AsciiString::isEmpty
007794d4  jne  0x7794f0               ; empty -> leave the active name alone
007794d7  lea  ecx, [esi + 0xc]
007794da  call 0x436030               ; active name = staged name
007794eb  call ASCII_STRING_DTOR      ; and clear the staged one
```

**So there are two ways to name the destination map** — write `+0xC` directly, as the
`ScriptHolder` path does, or write `+0xAC0` and let `startNewGame` promote it. The second is what
`-file` uses ([`headless.md`](headless.md)) and is the safer one for a patch, because the promote
also clears it and cannot leave a stale name behind.

**Do not use these two calls from a match, and do not post one message either.** Both enter world
construction with the previous session still live, and that faults (§6.13). The transition goes
through the shell, the way a player quitting to the menu does, in states the engine reaches by
itself (§6.13).

The direct pair enters world construction from wherever the caller happens to be. `LivingWorldLogic::startCampaign` gets away with it because it runs from the
shell, with nothing playing. The engine's own game-to-game transition is **quitting a match**,
which loads the shell map - and it does not call these two at all. It posts `MSG_NEW_GAME` at
`0x0075DEE2` and lets the handler run the sequence at the point in the frame that expects it:

```asm
0075deda  mov  ecx, [0xde6398]        ; TheMessageStream
0075dee0  mov  eax, [ecx]
0075dee2  push 0x1e                   ; MSG_NEW_GAME
0075dee4  call [eax + 0x48]           ; appendMessage -> GameMessage *
0075dee7  push 4                      ; the game mode, as its one integer argument
0075dee9  mov  ecx, eax
0075deeb  call 0x7111e5               ; GameMessage::appendIntegerArgument
```

**One integer argument is a complete message.** The handler defaults argument 1 to `1` at
`0x00779D58` and argument 2 to `0` at `0x00779D55`, taking the message's own only when
`[msg+0x18]` says it carries them - so the defaults are exactly the `(1, 0)` the `ScriptHolder`
path passes explicitly.

The recording cost is real and unavoidable: `MSG_NEW_GAME` is the only thing in the image that
calls `RecorderClass::startRecording` ([`skirmish-replay.md`](skirmish-replay.md) §1), so a
transition restarts the replay file. For the single-player scope that is acceptable (§7).

## 3. The authoring surface costs one dword

`ScriptActions::executeAction` (`0x007CAFA5`) dispatches 600 ids through the jump table at
`0x007CF857`. A stubbed action's table entry points straight at the shared epilogue `0x007CF846`,
which is why WorldBuilder offers it and the game ignores it
([`living-campaign/dead-script-actions.md`](living-campaign/dead-script-actions.md)). Four of the
34 dead ids, checked directly against the table:

| id | action | table entry |
|---|---|---|
| 148 | `MAP_SHROUD_AT_WAYPOINT` | `0x007CFAA7` → `0x007CF846` |
| 365 | `LIVING_WORLD_DESPAWN_ARMY` | `0x007CFE0B` → `0x007CF846` |
| 541 | `TEAM_ASSIMILATE_WITH_ARMY_BY_NAME` | `0x007D00CB` → `0x007CF846` |
| 553 | `MAP_REVEAL_IN_TRIGGER` | `0x007D00FB` → `0x007CF846` |

Repointing one of those dwords at a cave gives the mapper a working action in stock WorldBuilder,
with no editor patch at all. The cost is that the editor still shows the stock name, so a map
would read `LIVING_WORLD_DESPAWN_ARMY("map mp fords of isen")`. Renaming it properly means
rewriting the row in the 800-entry, `0x80`-stride action template table in **both** binaries —
feasible, since `worldbuilder-mod` already establishes patching `Worldbuilder.exe`, but it doubles
the surface and forces every mapper onto a patched editor. **Recommend shipping the repoint first
and treating the rename as a separate, optional patch.**

**Where a mapper finds it.** The template table carries the editor-facing text beside the internal
name, and for `540` it is `Player_/Assimilates player with an army by name.` - so the browser folder
is **`Player_`** and the entry is **"Assimilates player with an army by name."**. Placed, the line
reads:

```
Set <player> to be assimilated by army <name>.
```

built from the record's three fragments at `0x00C4BCA8`, `0x00C3C350` and `0x00C387CC`.

**Its two parameter types make the design work rather than merely allow it.** The record types them
`0x0B` `PLAYER_NAME` and `0x0A` `TEXT` (`sage_map`'s `ScriptArgumentType`). `TEXT` is a **literal**,
so the second slot is free text and a mapper can type any map name into it - had it been a picker
bound to declared army names, an arbitrary destination could not have been expressed at all. The
`PLAYER_NAME` slot is a dropdown of the map's players, unread by this build and waiting for the
layer that says whose army carries.

Reading the parameters needs no new work either. The concern raised in
[`script-action-injection.md`](script-action-injection.md) §5 — synthesising a `Parameter` from
outside the process — does not apply, because here the engine builds the parameters from the map
file and the cave only reads them:

```asm
007cb374  mov  ecx, [esi + 8]         ; ScriptAction::m_numParams
007cb37c  mov  eax, [esi + 0x10]      ; param 1  ([esi + 0xC + i*4])
007cb387  mov  esi, [esi + 0xc]       ; param 0
007cb3ad  add  eax, 0x10              ; -> the AsciiString inside the Parameter
007cb3b4  push esi
007cb3b7  call 0x7c8657               ; the implementation
007cb3bc  jmp  0x7cf846               ; the epilogue
```

| structure | offset | what |
|---|---|---|
| `ScriptAction` | `+0x04` | type, the switch value |
| | `+0x08` | parameter count |
| | `+0x0C + i*4` | `Parameter *` |
| | `+0x41` | enabled; the dispatcher skips the action when clear |
| `Parameter` | `+0x00` | type tag (`0x10` is `Coord3D`, per `0x007B3305`) |
| | `+0x08` | the integer slot — `CREATE_UNIT_REVIVAL_ENTRY_AT_LEVEL` reads its level from here |
| | `+0x0C` | the real slot, read as a float by the timer path |
| | `+0x10` | `AsciiString` — chars at `[+0x10] + 8` |

`getParameter` (`0x00602EFB`) is the bounds-checked accessor; live case bodies inline it. In the
cave, `esi` is the action and `edi` is the `ScriptActions` object, and the body must end with
`jmp 0x007CF846`.

## 4. The swap cannot happen inside the action

The action runs inside the script engine's own update, which runs inside the logic tick.
`loadMap` resets the script engine. Calling it from a case body tears down the object whose stack
frame is executing.

So the action is a **request**, not the transition:

1. The cave validates the destination, writes its name into the patch's own section, and sets a
   pending flag, then returns through the epilogue.
2. A hook at the top of `GameLogic::update`, with no script frame on the stack, drives the
   transition as a small state machine across several frames — each state waiting for a game mode
   the engine reaches by itself (§6.13).

The repo already hooks `GameLogic::update` for the live bridge, so the hook site is known
territory.

## 5. Where the snapshot lives

Everything the engine owns is destroyed by the swap, so the snapshot goes in patch-owned memory —
a fixed arena in an allocated section, sized once. A rough budget at the decided fidelity:

| record | bytes | count |
|---|---|---|
| carried object: template name, veterancy, experience, upgrade mask, hero level, health, script name, team name | ~64 | one per carried object |
| carried player: money, command points, sciences, spellbook points, player upgrade mask, revive records | ~256 | one per carrying player |
| counter / flag / timer | ~40 | one per script symbol |

The object half holds 256 slots of `0xE8` bytes — the engine's `0xD8` record plus a position and an
angle (§6.13) — about 58 KB, far above any plausible scenario army; the callback stops recording
past it rather than growing the arena. A fixed arena also sidesteps the engine allocator entirely,
which matters because the allocator is one of the subsystems the load path resets.

**The snapshot format is not a research problem.** `CHUNK_ScriptEngine` — counters, flags, timers
and the named-object table — is already decoded byte for byte by
[`sage_save.chunks`](../../sage_save/chunks.py), with an exact-inverse encoder validated
on 37 fixtures. That decoding names the fields; §6.1 locates them in memory. The save system
reaches the chunk through `GameState::registerSnapshot` (`0x006DF45B`), which appends a
`{name, snapshot}` pair to a list at `this + 0x10 + index*4`; `0x006DF904` registers
`CHUNK_ScriptEngine` with `TheScriptEngine + 0xC`, and `0x006DFCA5` does the same on the load
side. The patch does not call the serialiser — restore goes through the engine's own name-keyed
accessors instead.

## 6. Derivation

### 6.1 The script state containers

`TheScriptEngine` is `0x00DE3BAC`. Four sibling name-keyed maps live at `+0x191A0`, `+0x191AC`,
`+0x191B8` and `+0x191C4`, `0xC` apart, each with its own clear routine. The reset that empties
all four in order is the anchor:

```asm
00607642  lea  ecx, [esi + 0x191a0] ; call 0x6068fc
0060764d  lea  ecx, [esi + 0x191ac] ; call 0x606925
00607658  lea  ecx, [esi + 0x191b8] ; call 0x60694e
00607663  lea  ecx, [esi + 0x191c4] ; call 0x606977
```

| map | holds | lookup or create | value at node `+0x18` |
|---|---|---|---|
| `+0x191A0` | **counters and timers, in one map** | `0x0060817A` | `+0x00` dword value, `+0x04` byte "is a timer", `+0x05` byte "was given in seconds" |
| `+0x191AC` | **flags** | `0x006082CF`, find-only `0x00608249` | `+0x00` byte |
| `+0x191B8` | **probably the named-object table** — the only walker that types it compares the value against `OBJECT_ID` (`+0x74`), but that walker is dead code, so treat this as unconfirmed | around `0x006083EA` | `+0x00` dword id |
| `+0x191C4` | not identified. Its nodes are shaped differently — key `AsciiString` at node `+0x10`, value **byte** at node `+0x14` — so it is not a name-to-id table at all | around `0x0060867A` | node `+0x14` byte |

These are `std::map` nodes. For the counter and flag maps the mapped value sits at node `+0x18`,
iteration walks `[map+8]` until it comes back to the map header, and `0x00423EA0` is the iterator
increment. **Node shape is per-map and must not be assumed**: the `+0x191C4` map above puts its
value at `+0x14`, which is what an 8-byte composite key versus a 4-byte one does to the layout.

**Counters and flags are scoped, and restore has to honour it.** The key is not the bare name.
`0x0060817A` builds it through `0x00604043`, which calls `0x0072C43C(out, name, scope)` with the
scope taken from `ScriptEngine + 0x1A20C` — the script player currently being evaluated. That is
the same scope string the save format records, empty for globals. `0x0072C43C` also scans the name
for `/` and, when it finds one, takes the scope from the name instead, so `Player_1/MyCounter` is
an explicit cross-scope reference.

The consequence for the patch: the snapshot stores each record's scope, and restore sets
`ScriptEngine + 0x1A20C` before each call so the engine builds the same key it built originally.
Restoring a per-player counter into the global scope would silently create a second, unrelated
symbol.

**Counters and timers are the same records.** The timer setter and the counter setter both resolve
their name through `0x0060817A` into `+0x191A0`; a timer is simply a record with the `+0x04` byte
set. That collapses two of the three things the mapper asked to carry into one walk.

The three writers are reachable and name-keyed, which is what makes restore cheap:

| what | address | signature, `__thiscall` on `TheScriptEngine` |
|---|---|---|
| counter write | `0x00608D0B` | `(ScriptAction *, int, int, int)` — the three ints select set/increment/decrement and scope |
| flag write | `0x00608FCC` | `(ScriptAction *, Bool)` |
| timer write | `0x00609092` | `(ScriptAction *, Bool seconds, Bool random)` |

All three take a `ScriptAction` and read the name out of parameter 0, so driving them from a cave
means building a small synthetic action — the one place this patch does need the synthesis that
[`script-action-injection.md`](script-action-injection.md) §5 warns about. **The cheaper route is
to call `0x0060817A` / `0x006082CF` directly with an `AsciiString` and write the returned record**,
since both are plain lookup-or-create functions and the record layout above is three fields wide.

They are found through the stage-1 chain at `0x0060C211`, which handles 32 ids before delegating
the rest: `SET_FLAG` 1 → `0x00608FCC(action, 0)`, `SET_COUNTER` 2 → `0x00608D0B(action, 0, 0, 0)`,
`SET_TIMER` 6 → `0x00609092(action, 0, 0)`.

### 6.2 Timers count down, so nothing needs rebasing

It looks like a silent-corruption risk and is not. The timer tick walks the counter map every
logic frame and decrements in place:

```asm
0060cd4b  mov  edi, [esi + 0x191a0]
0060cd51  mov  eax, [edi + 8]           ; first node
0060cd56  cmp  byte [eax + 0x1c], 0     ; record+0x04 - is it a timer?
0060cd5a  je   next
0060cd5c  mov  ecx, [eax + 0x18]        ; record+0x00 - the value
0060cd5f  cmp  ecx, ebx                 ; ebx = 0
0060cd61  jl   next                     ; already spent - leave it
0060cd63  dec  ecx
0060cd64  mov  [eax + 0x18], ecx
0060cd67  push eax ; call 0x423ea0      ; ++iterator
```

A timer holds **ticks remaining**, counted down to -1 and then left alone. Nothing anywhere stores
an expiry frame, so `GameLogic::m_frame` restarting on the new map is irrelevant and a carried
timer resumes with exactly the time it had.

The unit is whatever the loop above is called on, and the conversion into it happens once, at
write time in `0x00609092`:

```asm
0060911c  fld   dword [0xd9f610]      ; 0.005
00609123  fmul  dword [ebp + 0xc]     ; x seconds
00609127  fmul  dword [0xbd4388]      ; x 1000.0
00609130  call  dword [0xbd0588]      ; a CRT rounding call
0060913e  fistp dword [ebp + 0xc]     ; -> an integer tick count
```

`0.005 × 1000` is **5 ticks per second**, which agrees with `LOGIC_FRAMES_PER_SECOND`
(`0x00D9F608`, value 5) already recorded in [`../addresses/`](../addresses/__init__.py), and not with the
30 four bytes above it at `0x00D9F60C`, which is the client rate. The `+0x05` byte only records
that the value arrived as seconds rather than as a raw count.

None of that matters to the patch, and that is the point: **the same tick that decrements the
value is the unit the value is in**, so carrying the record verbatim is exact regardless of the
rate. No conversion, no rebase.

### 6.3 Which player receives the army

Already recorded in [`../addresses/`](../addresses/__init__.py) and needing no new work:
`THE_PLAYER_LIST` `0x00DE4928`, `PLAYER_LIST_GET_LOCAL_PLAYER` `0x006A8839`,
`PLAYER_LIST_LOCAL_PLAYER` `+0x10`, `PLAYER_LIST_GET_NTH` `0x006A844E`,
`PLAYER_LIST_COUNT_OFFSET` `+0x14`. `getLocalPlayer` returns `[ThePlayerList+0x10]`, or the
observed player under `0x006AAC52` — a distinction that cannot arise in the single-player scope
but is worth not tripping over.

The default is therefore free: carry the local player. Naming other players stays a later
extension, and needs a matching rule across two sides lists rather than any new address.

### 6.4 The destination map path

The engine's own format literal is `maps\%s\%s.map` at `0x00BF51B4`, used from five sites
(`0x005EA7B6`, `0x006122DE`, `0x00649828`, `0x007F21F7`, `0x0090369C`). Real values in the image
match it — `maps\map mp harlindon\map mp harlindon.map`. A three-part variant `%s\%s\%s.map` at
`0x00C81760` exists for other roots such as `UserData\Maps`.

So the cave formats one mapper-supplied name through `AsciiString::format` (`0x00437A90`) against
the literal already in the image, and adds no string of its own.

### 6.5 Building an object back, by hand

The engine marshals a unit into a record and back in two calls (§6.8), and that is what the patch
uses. This section is what those calls do underneath, and the placement and naming calls restore
needs beside them.

The whole kit is present and every piece has a live call site. `RebuildHoleBehavior::onDie` is the
model to copy, because it does exactly what restore does — make an object from a template and dress
it to match one that no longer exists:

```asm
00889b14  push 0x10 ; push 0 ; push &local ; call 0xa3cf28  ; memset(status, 0, 16)
00889b21  mov  eax, [esi + 0x31c]        ; the source object's Team
00889b2a  push 0                         ; newObject arg 4
00889b2f  push ecx                       ; newObject arg 3 = &status
00889b36  push eax                       ; newObject arg 2 = Team
00889b3b  call 0x6d1305                  ; findTemplate  (ret 4)
00889b47  call 0x6d165e                  ; newObject     (ret 0x10)
00889b4e  lea  eax, [esi + 0x38] ; push ; call 0x70c201   ; setPosition(Coord3D *)
00889b59  fld  dword [esi + 0x44] ; ...  ; call 0x70c31e   ; setOrientation(float)
00889b7c  lea  eax, [esi + 0x88] ; push ; call 0x759467   ; bind the script name
```

| primitive | address | notes |
|---|---|---|
| `TheThingFactory` | `0x00DE4A40` | |
| `findTemplate(AsciiString *)` | `0x006D1305` | `ret 4`; already `THING_FACTORY_FIND_TEMPLATE` |
| `newObject(ThingTemplate *, Team *, StatusBits *, int)` | `0x006D165E` | `ret 0x10` — **four** args, not one. Forwards to `GameLogic::friend_createObject` `0x00625841`. The status argument is a zeroed 16 bytes, matching `OBJECT_STATUS_DWORDS` |
| `Object::setPosition(Coord3D *)` | `0x0070C201` | position at `Object+0x38` |
| `Object::setOrientation(float)` | `0x0070C31E` | angle at `Object+0x44`, pushed as a float |
| bind a script name | `0x00759467` | `__thiscall` on `TheScriptEngine`, `(AsciiString *, Object *)`; the name lives at `Object+0x88` |
| `Object::giveUpgrade(UpgradeTemplate *)` | `0x0069388B` | the object upgrade mask is `Object+0x28C` |
| `TheExperienceLevelSystem` | `0x00DE4704` | levels for a template through `0x00689509(out, template, level)` |
| the owning `Team` | `Object+0x31C` | what `newObject` wants, not a `Player` |

Two things fall out that shrink the work.

**Veterancy is upgrades.** [`live-object-model.md`](live-object-model.md) establishes that the
engine registers `Upgrade_Veterancy_VETERAN`, `_ELITE` and `_HEROIC` itself, before any ini is
parsed, as per-object upgrades at indices 0, 1 and 2. So veterancy and purchased upgrades are the
same carried field — one mask, replayed through one `giveUpgrade` loop — rather than two
mechanisms.

**Objects belong to a `Team`, not a `Player`.** `newObject` takes the team directly. Restore
therefore needs the receiving player's default team on the new map, which is one more lookup than
"the local player" and the reason the placement rule in §7 is worth stating precisely.

### 6.6 Hero revive records do not survive, and can be rebuilt

`ScriptActions::createUnitRevivalEntry` (`0x007C6D8E`) is the implementation behind
`CREATE_UNIT_REVIVAL_ENTRY` (595) and `CREATE_UNIT_REVIVAL_ENTRY_AT_LEVEL` (597), the latter
passing a level from `Parameter+0x08` and the former passing `-1`:

```asm
007c6daa  call 0x6d1305                  ; findTemplate(unit name)
007c6dc4  call 0x758f7c                  ; ScriptEngine: player name -> index
007c6dd6  call 0x6a85ee                  ; PlayerList: index -> Player *
007c6de5  lea  ebx, [edi + 0x758]        ; the hero ledger
007c6e03  cmp  dword [ebp + 0x10], -1    ; a level was given?
007c6e1b  call 0x689509                  ; TheExperienceLevelSystem: levels for (template, level)
```

**The store is the hero ledger**, already recorded as `PLAYER_HERO_LEDGER_OFFSET` (`Player+0x758`)
with entries between `+0x04` and `+0x08` at stride `0xE8` and the hero's template name at
`+0xE4`. [`living-campaign/hero-permadeath.md`](living-campaign/hero-permadeath.md) establishes the
part that matters here: **a dead hero's level and upgrades live in the ledger, not on his object**,
which is gone from the object list by the time anything wants to read it. So the ledger is not an
optional extra to carry — it is the only place a dead hero's state exists.

It dies with the player on a map swap, and it is rebuildable without writing into it (not built
yet):
`0x007C6D8E` takes a player name, a unit name and a level, which is exactly what a snapshot record
would hold, and it is the same call the stock script action makes. Restore drives the engine's own
entry point rather than reconstructing the store.

So hero revive costs a walk of the ledger on the way out and a loop of `0x007C6D8E` on the way in.

### 6.7 Player state, and the object walk

Almost all of this was already recorded, which collapses the item:

| what | where |
|---|---|
| money / resources | `PLAYER_MONEY` `+0x90`, `PLAYER_RESOURCES` `+0x94` |
| command points | used `+0x68`, cap `+0x64`, bonus `+0x6C`, hard cap `+0x70` |
| player-wide upgrades | `PLAYER_COMPLETED_UPGRADE_MASK` `+0x14C`, 36 words |
| spellbook points | `PLAYER_POWER_POINTS` `+0x24`, total `+0x1C` |
| the hero ledger | `PLAYER_HERO_LEDGER_OFFSET` `+0x758` |
| walking a player's objects | `PLAYER_FOR_EACH_TEAM_OBJECT` `0x006ABABD` |

`Player::forEachTeamObject(fn, ctx)` is `__thiscall`, `ret 8`, walks the team list at
`Player+0x34C`, stops early when the callback returns 0, and writes nothing. The callback is
`cdecl (Object *, void *ctx)`. That is the snapshot walk, already derived for the auto-deposit
work and reusable unchanged.

`Player+0x34C` being the team list is also the answer to the default-team question in the other
direction: the receiving player's teams are reachable from the player without a separate lookup.

### 6.8 The engine carries a unit for you, in both directions

The engine has a matched pair for turning an object into a portable record
and back, and **neither half is living-world code**.

**Out.** `Object::toArmyRecord` (`0x0069192F`), `__thiscall` on the object, one argument, `ret 4`.
It fills the same `0xD8` record an `ArmyEntry` line parses into, so its layout is documented rather
than guessed, and the inner half resolves a **horde to its member template** instead of writing the
horde object.

**In.** `ArmyRecord::createObject` (`0x00780172`), `__thiscall` on the record, one argument — the
receiving `Player` — returning the new object:

```asm
0078017c  call 0x7800dc               ; ARMY_ENTRY_FIND_TEMPLATE
007801a9  mov  eax, [player + 0x30c]  ; the player's DEFAULT TEAM
007801c0  call 0x6d165e               ; THING_FACTORY_NEW_OBJECT(template, team, &zeroed, 0)
007801e7  movss xmm0, [record + 8]    ; health, applied to the body if it exceeds the max
0078021a  lea  ecx, [obj + 0x28c]     ; OBJECT_UPGRADE_MASK
00780223  call 0x68cc6c               ;   <- record+0x10, the upgrade list
0078022a  call 0x6936fe               ; re-evaluate the object after upgrades
0078024f  call 0x693a1a               ; its contain, then push the same upgrade list into it
0078027b  call [iface + 0x110]        ;   so contained members are dressed too
```

That single call restores the template, the owning team, health, and the upgrade mask — which by
§6.5 **is** veterancy, since the three rank upgrades are per-object upgrades at indices 0 to 2 —
and then propagates the upgrades into the object's contain, so a horde's members come back
dressed.

**The living-world entanglement is entirely in the callers.**
`ARMY_RECORD_SPAWN` (`0x00811104`) resolves the `Player` from an army id at `record+0x1C` through
`TheLivingWorldLogic`, and `LIVING_WORLD_ARMY_DEPLOY` above it resolves armies and battles. Calling
`0x00780172` directly with a `Player` skips both. The harvest (`0x00811E1F`) itself is unusable — it
filters on living-world players and an army id at `obj+0x47C` — but two of its four filters are not
living-world-specific, and the patch keeps them (§6.13).

**So the object half is:**

| phase | work |
|---|---|
| snapshot | `PLAYER_FOR_EACH_TEAM_OBJECT`, and per object that passes the filters: construct a `0xD8` record with `ARMY_ENTRY_RECORD_CTOR`, call `toArmyRecord`, note its position and angle |
| restore | per record: `createObject(player)`, then `setPosition` and `setOrientation` from §6.5 |

### 6.9 Power cooldowns must be rebased, and script timers must not

**Out of scope, by decision.** Recorded because the contrast below is what keeps the script timers
correct.

A special power's cooldown is `readyFrame` at interface
`+0x08`, and [`recharge-rescale.md`](recharge-rescale.md) settles what it is: an **absolute logic
frame**, written once as `frame + duration` by `startPowerRecharge` (`0x00896F70`) and compared
against `TheGameLogic`'s frame on demand rather than counted down.

So the two timed things in this patch behave in opposite ways across a map swap:

| state | stored as | on a swap |
|---|---|---|
| script timer (`SCRIPT_COUNTER_VALUE`) | ticks **remaining**, decremented by the tick | carry verbatim, §6.2 |
| power cooldown (`SPECIAL_POWER_READY_FRAME`) | an **absolute frame** | **must be rebased**, or every power reads as ready |

Getting this backwards in either direction is a silent bug, and the two are easy to conflate
because both are "a timer".

If it is ever picked up, rebasing is a solved move rather than an invention: the engine already
adjusts `readyFrame` after the fact by adding the elapsed delta, so restore would do the same with
the frame counter's reset as the delta, over a walk of each power module the player owns. Not
carrying it at all leaves every power reading ready on arrival, which is the same outcome as
carrying it unrebased - so there is no half-measure to get wrong in the meantime.

### 6.10 The two fields that round-trip

`createObject` copies `record+0xA4` into `obj+0x488` through `0x005EA74E`, which moves three dwords
and then a `UnicodeString` at `+0xC` — the shape of a display-name block rather than anything
simulation-bearing. The `toArmyRecord` wrapper separately moves `Object+0x480` to `record+0xD0`,
and `obj+0x47C` next door is the army id the harvest filters on, so `+0x480` is very likely its
neighbour in the same living-world group.

Neither is worth chasing: **both round-trip through the record**, so the patch inherits whatever
they hold without needing to name them. Recorded here so the next reader does not re-derive them.

### 6.11 Restore lands before any script runs

Two parts hold statically, and the third is measured.

**Scripts are installed during the load.** The install is
`0x007A6DEA`, inside the team-instantiation routine at `0x007A6C91`, which adds a script list to
its owner if not already present. That routine is what emits the `- creating team instance.` log
line at `0x007A6E52`, and the three `-scriptdebug2` runs recorded in
[`living-campaign/script-holder.md`](living-campaign/script-holder.md) §4 show those lines **at
frame 0**, before any gameplay frame. So installation is complete inside `loadMap`, measured rather
than inferred.

**Nothing has evaluated a script by the time `loadMap` returns.** The runner is driven from the
script engine's update, which runs inside `GameLogic::update`. `loadMap` is a synchronous call from
the message handler that returns before the game loop's next update. So a restore placed
immediately after it necessarily precedes the first evaluation of any script on the new map.

**Measured: nothing evaluates during construction.** An init or on-load sweep would let a script see
carried counters before restore wrote them. The runner logs `"Run script - "` (`0xBF9C60`) or
`"Run script false - "` (`0xBF9C4C`) at `0x00609AE7`, each line carrying a leading frame number, so
a `-scriptdebug2` log answers it without anything being built.

Run 2026-09-08: **the first script line is at frame 1.** So scripts are installed during the load,
and nothing is evaluated during it. Where the restore sits relative to frame 1 is §6.12's item 3.

**A lead for someone else's open question.** `script-holder.md` §5 records that the bulk installer
attaching script lists to players "was not found", and reads the list as `Player+0x334`. That
labelling looks wrong. The runner obtains its holder from `0x007A2C47`, a **two-name keyed lookup**
into a map at `holder+0x150` returning the value at node `+0x18`, and it is that returned object
which carries the list at `+0x334`. In the install call at `0x007A6DEA` the object holding `+0x334`
and the team being registered are two different things. So the lists may not live on `Player` at
all, which would explain why no `Player`-side installer was ever found. Not chased further here
because this patch does not need it.

### 6.12 Still open

| # | unknown | notes |
|---|---|---|
| 1 | **The four reserved trees keep a dead team** | the crash six to twenty seconds into the destination — §6.13 |
| 2 | **What `+0x191C4` holds** | not a name-to-id table; a name to byte map with its value at node `+0x14`. Only matters if it carries script state a mapper can set |
| 3 | **Restore versus frame 1** | the restore runs from `GameLogic::update`'s entry on the first logic frame the destination runs, before the script engine's own update in that frame, so a destination script that initialises the same name at frame 1 overwrites the carried value — the opposite of §7's policy. If a mapper writes such a script, defer the restore by one frame |
| 4 | **The score screen** | the end-of-match flow shows it; if it waits for a click, the transition waits with it |
| 5 | **The hero revival ledger** | §6.6; not carried yet |
| 6 | **`map.ini` overrides across a chain** | §6.13 |

## 6.13 The transition as built

### The action, the hook, and what they cost

**Action id `540`, `PLAYER_ASSIMILATE_WITH_ARMY_BY_NAME`**, one of the five consecutive stubs at
539-543. The whole assimilate and reinforcement family appears **zero** times across the 480-map
Edain corpus, so no existing map can trigger a transition by accident; `LIVING_WORLD_DESPAWN_ARMY`
(365) and `MAP_REVEAL_IN_TRIGGER` (553) each have one live occurrence and cannot promise that. Its
stock parameters are a player and a string: the string is the destination, and the player slot is
where "whose army carries" would go.

**The game mode is read back, not pinned.** The session's current mode is at `TheGameLogic+0x110`;
the hook saves it and the destination is started in it, so a skirmish stays a skirmish. Pinning mode
8 the way the `ScriptHolder` path does would drop every transition into living-world mode.

**The hook brackets itself with `pushad`/`popad`.** `GameLogic::update` is dispatched
`__thiscall`, so `ecx` holds `this` at the entry the hook takes over, and the prologue has not run.

**It takes `GameLogic::update`'s first five bytes, which `live-bridge` also takes**, so the two do
not compose; the framework raises for whichever is applied second rather than corrupting the site.
The mapper-facing name stays `PLAYER_ASSIMILATE_WITH_ARMY_BY_NAME` in WorldBuilder until the optional
rename patch of §3 is built.

### The state machine

Four states, each waiting for a mode the engine reaches by itself:

```
1  snapshot the army, clearGameData(1), arm 2   -> engine shows the score screen, lands in the lobby (mode 9)
2  mode 9 -> stage the shell map, post mode 4   -> engine loads the shell map
   mode 4 -> TheGameInfo = TheSkirmishGameInfo, clearGameData,
             stage the destination, post the saved mode, arm 3
3  mode == saved mode -> put the army, the player state and the script state back
```

Each step is there because the engine forces it:

- **World construction over a live session faults.** Entered from a match — the direct
  `startNewGame`/`loadMap` pair, or one posted `MSG_NEW_GAME` — the load faults inside the new map's
  team instantiation at `0x007A2052` (`mov eax, [ecx]`, `ecx` = `0x158`), in `Object::setTeam`
  (`0x00697C09`) reading a **non-null stale** team: the dump shows recycled heap where the team was,
  holding floats that read as a position and a scale. The engine's own handler crashes the same way
  when asked from a playing mode. The only mid-match `MSG_NEW_GAME` in the image is the shell return
  at `0x0075DEE2`, and it carries mode 4.
- **`clearGameData(1)` (`0x00625E36`) is the teardown.** It is what the pause menu's Quit (`0x00921904`,
  call at `0x00921A67`) does; the argument only gates a network branch a single-player session skips
  at `0x00625E49`. It hands the session to the engine's end-of-match flow, which shows the score
  screen and reaches the lobby **on its own schedule** — so step 1 posts nothing; a second shell
  request in the middle of that flow is a second transition in one session.
- **The end-of-match flow parks at mode 9**, the skirmish lobby, not at 4. The engine's own shell
  return special-cases the same value at `0x0075DEAA`, so 9 is a real resting state.
- **A `MSG_NEW_GAME` posted from mode 9 for a playing mode is ignored**: the mode stays 9 and the
  staged name is never promoted. Mode 4, the shell map, is the state the engine's shell-to-game start
  works from, so step 2 goes there first.
- **The mode does not select the map.** The loader takes the map from `GlobalData`'s active name
  (`GLOBAL_DATA_ACTIVE_MAP`) whatever the mode argument says; posting mode 4 without naming the shell
  map reloads the map already running. `ShellMapName` is `GlobalData+0xAEC`
  (`GLOBAL_DATA_SHELL_MAP`, row 248 of the `GameData` table), defaulting to
  `Maps\ShellMap1\ShellMap1.map` (written at `0x0064306B`). Both names are written into the
  **staged** slot `GLOBAL_DATA_STAGED_MAP` (`+0xAC0`), as the engine's own branch at `0x0075DEBC`
  does: `startNewGame` promotes and clears it, so a request that is never served cannot leave a stale
  name behind.
- **`loadMap` nulls `TheGameInfo` for the shell map and for nothing else** (`0x0063153A`, when the
  incoming mode is 4). The destination would then load without one: `LoadScreen::init(GameInfo *)`
  (`0x0081CB08`) returns early on null, leaving the progress window at `LoadScreen+0x88` null, and the
  first progress tick faults at `0x0081C650`. The skirmish info survives — `0x0082BE98` sets
  `THE_SKIRMISH_GAME_INFO` (`0x00DE8930`) and `THE_GAME_INFO` together and `0x0082BE30` nulls both —
  so the mode-4 arm copies the one back into the other before posting, after the shell's `loadMap`
  has cleared it.
- **The shell map's render scene stays standing** into the destination unless the session is torn
  down between them: the logic world is the destination's while its terrain is never added to the
  scene and the shell map's drawables are never removed. The mode-4 arm calls `clearGameData` before
  its post, leaving `MSG_CLEAR_GAME_DATA` and `MSG_NEW_GAME` in one stream, in order. One supporting
  instance, not a derivation: the stock shell-to-game start calls `clearGameData` nowhere — clicking
  Skirmish leaves the shell map first.
- **`TheGameLogic` is not reallocated by a load**: `0x00DE412C` has exactly one writer, `0x0062CD16`,
  in the startup constructor, so the `this` the hook restores stays valid.

### What carries: the army

**The selection rule is `KindOf ARMY_SUMMARY`**, two of the harvest's four filters (§6.8), plus the
engine's own per-object skip of `OBJECT_STATUS_UNDER_CONSTRUCTION` (`0x00885234`):

```
00811e93  mov  eax, [edi + 4]           ; the ThingTemplate
00811e96  test byte [eax + 0x118], bl   ; KindOf = ARMY_SUMMARY
00811e9c  je   skip
00811ea2  test byte [edi + 0x458], bl   ; bit 0 has no setter
00811ea8  jne  skip
```

`ARMY_SUMMARY` is War of the Ring's own answer to "which of these objects go home with the player",
and it is better than "not a structure" for two reasons:

- Structures do not carry it, so a player who built a castle does not arrive with its walls, keep,
  elevators, plot flags and foundations.
- **Hordes carry it and their members do not.** Measured on a live map: `GondorFighterHorde_-
  StartUnit` has the bit, `GondorFighter` does not. Filtering on it carries the horde once and lets
  `createObject` rebuild its members (§6.8); walking every team object would put back each horde
  *and* a crowd of loose soldiers.

The fourth filter, `obj+0x458` bit 0, is mirrored anyway. It has no setter in the binary — only two
zeroing stores in constructors ([`army-id-custody.md`](living-campaign/army-id-custody.md)) — yet a
221-object live census read it set on `FarmTemplate`, `GondorSpellBook` and `EdainTroopSpawnPoint`,
map furniture, never a unit or a horde. That reading needs re-measuring.

**One consequence a mapper has to know about.** `ARMY_SUMMARY` is mod data, not engine data, and
Edain does not set it everywhere. It is on 257 unit files and on the hordes, but `HOBBIT_KINDOF`
(`_gamedata.inc:65`) omits it, so Pippin, Merry, Frodo and Sam do not carry. That is a one-word fix
in the mod rather than in the patch.

**The record does not carry position**, so each slot is `ARMY_RECORD_SIZE` plus a `Coord3D` and an
angle - `SLOT_SIZE` `0xE8`. Units come back at the coordinates they left: right for maps laid out as
a continuous world, wrong for arbitrary pairs (§7). `RECORD_POSITION_OFF` is `0xD8`, which does not
fit a **signed** byte displacement — `89 47 D8` is `[edi-0x28]`, not `[edi+0xD8]` — so a test asserts
no negative displacement appears in the routine at all. The snapshot runs in step 1, **before**
`clearGameData`; every call it makes was checked against its epilogue (`PLAYER_LIST_GET_LOCAL_PLAYER`
`ret`, `PLAYER_FOR_EACH_TEAM_OBJECT` `ret 8`, `ARMY_ENTRY_RECORD_CTOR` `ret`, `OBJECT_TO_ARMY_RECORD`,
`ARMY_RECORD_CREATE_OBJECT`, `OBJECT_SET_POSITION` and `OBJECT_SET_ORIENTATION` `ret 4`), and the
walk's callback convention against `0x007A0626`: it pushes `ctx`, then the object, calls `[ebp+8]`
and pops both, so `fn` is argument one, the object comes first, and the caller cleans.

### What carries: script state

§6.1 names the containers and §6.2 settles that timers need no rebasing. The node layout, read out
of a dump:

| node offset | field |
|---|---|
| `+0x04` `+0x08` `+0x0C` | parent, left, right |
| `+0x10` | the **scope** `AsciiString` - null for a global |
| `+0x14` | the **name** `AsciiString` |
| `STD_MAP_NODE_VALUE` (`+0x18`) | the record: value, then `IS_TIMER` and `IS_SECONDS` |

The two string fields are told apart twice over. The scope field holds `Player_1` and
`PlyrCreeps` where the name field holds `Hoehe` and `SkirmishGollum_SpawnPoint#`; and walking the
tree in order gives all the empty-scope records first and the `Player_1` ones after, so the
comparison runs scope-first and `+0x10` is the leading key.

A live Edain skirmish holds 11 counters and 17 flags:

```
count  /E                                    1125
count  /Spieleranzahl                           1
count  /Timer                               49814   timer, authored in seconds
count  Player_1/Hoehe                           16
count  PlyrCreeps/SkirmishGollum_SpawnPoint#     8
flag   /FreeBuild                                0
flag   /GamemodesLoaded                          1
flag   /Starttyp                                 1
```

and twenty `___MusicScript_` symbols, which are **not** carried. Three leading underscores is the
engine's own convention for script state the map did not author, and handing the destination's
music scripts the source map's idea of what has already been initialised is not what "carry the
counters" meant.

A flag's value is a **byte**, and the three bytes above it in the node belong to someone else -
`___MusicScript_Level1MusicDone` reads `0xFFFFFF00` as a dword. Carrying the dword would restore
garbage into the neighbouring fields.

And the scope does not have to be restored through `SCRIPT_ENGINE_SCOPE` at all. `SCRIPT_KEY_COMPOSE`
scans the name for `/` and, finding one, takes everything before it as the scope and ignores the
engine's current one (`0x0072C492`). So the snapshot stores `<scope>/<name>` with the separator
written **unconditionally** - a global becomes `/FreeBuild`, whose scope is the empty string before
the slash, which is exactly right. Restore then never depends on what the engine's scope field
happens to hold at a moment outside script evaluation, which is not a defined thing.

Restore uses the two lookup-or-create functions rather than synthesising a `ScriptAction`. Both are
`__thiscall` on `TheScriptEngine`, take an `AsciiString` **by value**, destroy it themselves and
return the record (`0x0060820E` and `0x0060835C` both `add esi, 0x18`). So the string is
constructed directly into the stack slot that is already the argument, and the callee's `ret 4`
disposes of the slot and the string together.
The restore runs before the script engine's own update in the destination's first logic frame;
§6.12 item 3 is what that means for a script that initialises the same name.

### What carries: the player's own state

§6.7 records the fields; the question is which are *state* and which are *bookkeeping*. Checked
against a dump beside its screenshot: `Player+0x94` reads **4240** where the
HUD shows 4240 gold, and `+0x64` reads **500** where the HUD shows a cap of 500. The mapping is
right.

Carried: the purse (`+0x94`), the command-point ceiling as all three flat fields
(`+0x64` base, `+0x6C` bonus, `+0x70` hard), and the spellbook currency (`+0x24` points, `+0x1C`
total).

**Not carried: `+0x68`, the points in use.** The engine maintains it as objects are created and
destroyed (`0x006A7FDA` / `0x006A7FEB`), so restoring the army re-accrues it from nothing; carrying
the number as well would count every carried unit twice and leave the player permanently over cap.
This is the one field in the block that looks like state and is not.

The ceiling carries even though it is normally earned from buildings, and buildings do not carry.
That is a deliberate asymmetry rather than an oversight: an army arrives whole, so it needs the
headroom to exist. The `<filtered extras>` term the engine adds between base and hard cap is a
vector of `ObjectFilter`-carrying entries that has to be evaluated by the engine, so it is left to
the destination and the three flat fields are what move.

### What carries: sciences and upgrades

`LIVING_WORLD_BATTLE_SETUP` (`0x008125FC`) is War of the Ring putting a living-world player's money,
sciences and upgrades back onto its RTS player at the start of a battle. That is the same problem
this patch has, and reading it answers both halves.

**Sciences are a `std::vector<ScienceType>` at `Player+0x310`**, assigned by
`PLAYER_SET_SCIENCES` (`0x006ACEF4`, `__thiscall`, `ret 4`). It reads only `[src]` and `[src+4]`
and returns without doing anything when they are equal, so the argument can be a three-word header
built on the stack over the arena's own buffer, and the empty case handles itself. Confirmed live:
every seat in a skirmish carries the four baseline sciences 30-33, and only the human seat had a
fifth - `16`, a purchased spellbook power. Only that seat had upgrade bits set, too, which is the
shape the fields should have and a check on both at once.

**Upgrades are replayed, not written.** Writing the mask raw would set each bit and run nothing,
and the engine does not do that either:

```
008126e5  mov  ecx, [TheUpgradeCenter]
008126ef  call UPGRADE_FIRST_SET       ; the mask -> the first UpgradeTemplate whose bit is set
008126ff  mov  ecx, esi                ; the Player
00812701  call PLAYER_GRANT_UPGRADE    ; (template, 2, 0) - sets the bit *and* completes it
00812706  mov  ecx, [edi + 0x38]       ; UPGRADE_TEMPLATE_INDEX
0081271c  and  [mask + word], ~bit     ; clear it and go round
```

so the patch drives the same loop. `UPGRADE_FIRST_SET` was already recorded for `give-upgrade-all`,
which hooks its *call site* in `GiveUpgradeUpdate::trigger` rather than the function, so calling it
from another cave composes.

Restore consumes a **copy** of the snapshotted mask rather than the mask itself: the loop clears
each bit as it grants it, and the arena keeps what it captured. The bit is cleared after the grant
whatever the grant returned, so an upgrade the destination refuses cannot spin the cave.

**Power cooldowns are out of scope**, so powers arrive ready; §6.9 records why that is the same
outcome as carrying `readyFrame` unrebased. The hero revival ledger (§6.6) is not carried yet.

### Open: the four reserved trees keep a dead team

Six to twenty seconds into the destination the game faults at `0x0079FD77`, `mov eax, [eax + 8]`,
reached from `Object::isLocallyControlled`:

```
0068b678  mov ecx, [ecx + 0x31c]   ; the Object's Team
0068b682  jmp 0x79fd6f             ; team -> [+0x30] prototype -> [+8] player
```

The object is `TheOneTree`, and its three siblings are in the same state. They hold ids
99999996-99999999 and a `Team *` of `0x0A526148`, whose `+0x30` reads **6**: freed memory. Every
other object in the census resolves cleanly.

They survive because their creation site looks them up before it builds them:

```
0062f508  mov  edi, 0x5f5e0ff              ; 99999999
0062f510  call GAME_LOGIC_FIND_OBJECT_BY_ID
0062f517  mov  [esi + 0x154], eax
0062f51d  jne  0x62f5f1                    ; already there -> keep it
```

and the team they were given is `ThePlayerList->players[0]->defaultTeam` (`0x0062F5A2`), which the
destination's player setup replaces and frees. So a set of objects that is meant to be per-session
outlives one session and points into the previous one. The four cached pointers at
`TheGameLogic + 0x154`-`0x160` are nulled only in the `GameLogic` constructor (`0x00630219`), so
nothing per-map resets them either. Destroying the four at transition time would put the
recreation branch back in charge; that needs a `destroyObject` address this build does not have
named yet.

### Open: `map.ini` overrides across a chain

A map's `map.ini` is loaded as an **override pass** over the already-parsed global data: the loader
builds `<mapdir>\map.ini` at `0x00627223`, checks it exists, and loads it with INI load type `2` at
`0x00627250`, from `0x0062710D`, whose one caller is `0x0062FA07` inside `GameLogic::startNewGame`.
Nothing in that path reverts earlier overrides first — `0x0062550D` beside it is a small forwarder,
`0x005B45D8` is registration rather than a reset pass, and no "delete overrides" routine turns up by
string or structure. If that reading is right, **`map.ini` overrides accumulate for the lifetime of
the process**.

`RemoveModule` is **not idempotent**: applying it twice fails, because the second application looks
for a module the first removed —

```
RemoveModule ModuleTag_01 was not found for EreborTorch.
Error parsing field 'RemoveModule' in block 'Object' in file
'maps\map edain thirdhall\map.ini', line 418.
```

— so loading two maps whose `map.ini` carries the same non-idempotent directive fails on the second
one. The test that settles whether this is stock behaviour: load the first map from the menu, quit
to the menu, load the second. If that errors, the answer is a **mapper rule** — a chain of maps must
not carry non-idempotent `map.ini` directives for the same object — or a small separate patch
downgrading `RemoveModule`'s "not found" from a fatal parse error to a skip. If it does not, the
menu path performs an override reset the transition skips.

### Debugging a transition

- **`crash-dump --dump-type 0x1b67`.** The default type (`0x1B65`) carries heap but **not module
  data segments**, so `TheWritableGlobalData`, `TheGameLogic` and the patch's own `.maptran` state
  are unreadable and which step failed has to be inferred. `normal = 0x1B67` adds
  `MiniDumpWithFullMemory`; `deep` is only used by the engine's own `fulldump` command. A full-memory
  dump is around 950 MB and does not always survive the crash that produced it.
- **A stalled transition is still in memory.** `sage_live`'s `ProcessMemory` reads `.maptran`'s
  `pending`, `saved_mode` and name, `TheGameLogic+0x110` and the staged and active map names out of
  a running game with no dump at all.

## 7. Decisions the patch has to state, not discover

- **Counter and flag collision.** A name in both the snapshot and the new map's scripts takes the
  carried value; a carried name the new map never declares is created. The reverse policy — the
  new map wins — makes carrying pointless. State it in the patch description, because a mapper who
  initialises a counter on map 2 will otherwise be surprised.
- **Only the named players carry.** Everything else on the destination map comes from the
  destination map. Enemies, neutrals and structures are the new map's business. Structures were
  excluded from scope, so a player who built a base does not bring it.
- **Placement.** Carried units come back at the coordinates they left, which suits maps laid out
  as a continuous world; an entry waypoint is the better rule for arbitrary pairs and is not built.
  Garrison and transport contents and standing orders are out of scope. A horde carries once and
  its members are rebuilt and dressed by `createObject` (§6.8). Objects are created onto the
  receiving player's default team.
- **Single player only.** A map load is not in the order stream, so in a network game it is a
  dropped match for everyone. The cave does not check yet; `THE_GAME_INFO` (`0x00DE892C`) and
  `GAME_MODE_SKIRMISH` are in [`../addresses/`](../addresses/__init__.py), so the check is a read.
- **Recording.** A transition restarts the replay file (§2), so a recording covers one map. The
  cave does not refuse while recording.
- **Saves.** The transition materialises entirely into ordinary engine state, so a save taken after
  it is an ordinary save of map 2 and reloads without the patch needing to know. The pending state
  spans the score screen, the lobby and the shell load, none of which is a point a game is saved
  from.

## 8. Acceptance test

1. Two maps and one script. Transition with a mixed army: a veterancy-2 unit, a levelled hero, a
   unit carrying a purchased upgrade. All three arrive with those properties, checked through
   `sage_live` rather than by eye.
2. A counter, a flag and a **timer** set before the transition. A timer with 60 seconds left must
   still have about 60 seconds left. §6.2 says this should work by construction, which makes it a
   test of the reading rather than of the design.
3. Save on map 2 after a transition, quit to the shell, reload. The army and the script state come
   back.
4. Kill a hero on map 1, transition, confirm the hero is still dead and came back revivable at
   the level and with the upgrades he died with — once §6.6 is built. It rebuilds the ledger through
   the engine's own `0x007C6D8E`, so this tests that call as much as the carry.
5. Transition twice, to confirm the arena and the pending flag survive being used more than once.
