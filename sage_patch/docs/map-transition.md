# Changing map mid-game from a script, carrying the army with it

Engine build `2.01.2614.37001`, ImageBase `0x400000`, read off the installed `game.dat` with
`explore.py`. **Static analysis throughout, with one exception**: the script ordering in §6.11 was
measured in game on 2026-09-08. Everything else is read off the disassembly and has not been run.
This is a scope with derivation done against it: §2, §3 and §6.1–§6.8 are established from the
disassembly quoted beside them, §6.12 is what is still open, and §7 says what the design refuses to
do.

**The goal.** A mapper places one script action, names another `.map`, and the game loads it with
the player's army, resources, powers and script state intact — so a scenario can be larger than a
single map file.

**Verdict up front.** The two hard-looking halves are already solved. The engine has a callable
mid-session map swap that `LivingWorldLogic` uses today, and a dead script action can be given a
body by rewriting one dword. What the patch actually costs is the middle: nothing carries across
the swap by itself, so the patch owns a snapshot of everything the mapper expects to survive, and
owns re-materialising it into a world that has just been rebuilt from scratch.

**Decided scope.** Per-object carryover of veterancy, experience, purchased upgrades and hero
levels; plus resources, powers and hero death/revive state; plus script counters, flags and
timers. One-way transitions only, no returning to a map already left. Single player only.

**Partly built.** The mechanism — §2's swap, driven by §3's repointed script action through §4's
deferred hook — is [`map-transition`](../patches/experimental/map_transition.py), experimental and
**not yet run in game**. It swaps maps and carries nothing. Everything §6 derives about carrying
state is still scope. §10 records what the build settled and what it left.

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

**Do not use these two calls, and do not post one message either - post two, through the shell.**
The short version: the direct pair is wrong, a single `MSG_NEW_GAME` is also wrong, and the reason
in both cases is the same. See the two dump analyses below. An earlier revision of this document
recommended the opposite - the direct pair, on the grounds that `MSG_NEW_GAME` is the only thing in
the image that calls `RecorderClass::startRecording` ([`skirmish-replay.md`](skirmish-replay.md)
§1) and so restarts the replay file. **That advice was wrong and it is what crashed the first
build.**

The direct pair enters world construction from wherever the caller happens to be, with the previous
session still live. `LivingWorldLogic::startCampaign` gets away with it because it runs from the
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

The recording cost is real and now unavoidable: a transition restarts the replay file. For the
single-player scope that is acceptable, and §7 already refuses to run while recording.

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

1. The cave validates, snapshots, writes the destination name and sets a pending flag, then
   returns through the epilogue.
2. A hook in `GameLogic::update` sees the flag at the top of the next tick, with no script frame
   on the stack, and runs `startNewGame` / `loadMap` / restore as one uninterrupted sequence.

The repo already hooks `GameLogic::update` for the live bridge, so the hook site is known
territory. Doing the whole transition inside one hook invocation matters for more than tidiness:
the pending flag is patch-owned memory that no save file knows about, and if the flag is never
observable across a frame boundary, a save can never be taken while one is set.

## 5. Where the snapshot lives

Everything the engine owns is destroyed by the swap, so the snapshot goes in patch-owned memory —
a fixed arena in an allocated section, sized once. A rough budget at the decided fidelity:

| record | bytes | count |
|---|---|---|
| carried object: template name, veterancy, experience, upgrade mask, hero level, health, script name, team name | ~64 | one per carried object |
| carried player: money, command points, sciences, spellbook points, player upgrade mask, revive records | ~256 | one per carrying player |
| counter / flag / timer | ~40 | one per script symbol |

A 256 KB arena covers roughly 3000 objects and leaves headroom, which is far above any plausible
scenario army. A fixed arena also sidesteps the engine allocator entirely, which matters because
the allocator is one of the subsystems the load path resets.

**The snapshot format is not a research problem.** `CHUNK_ScriptEngine` — counters, flags, timers
and the named-object table — is already decoded byte for byte in
[`sage_save/sav_format.md`](../../sage_save/sav_format.md), with an exact-inverse encoder validated
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

This was flagged as the one silent-corruption risk in the design. It is not a risk. The timer tick
walks the counter map every logic frame and decrements in place:

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
(`0x00D9F608`, value 5) already recorded in [`../addresses.py`](../addresses.py), and not with the
30 four bytes above it at `0x00D9F60C`, which is the client rate. The `+0x05` byte only records
that the value arrived as seconds rather than as a raw count.

None of that matters to the patch, and that is the point: **the same tick that decrements the
value is the unit the value is in**, so carrying the record verbatim is exact regardless of the
rate. No conversion, no rebase.

### 6.3 Which player receives the army

Already recorded in [`../addresses.py`](../addresses.py) and needing no new work:
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

**Read §6.8 first.** It supersedes this section: the engine marshals a unit into a record and back
in two calls, and that is the plan. What follows stays because restore still needs the placement
and naming calls, and because it documents what the engine is doing underneath.

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

It dies with the player on a map swap, and it is rebuildable without writing into it:
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

This supersedes §6.5. The engine has a matched pair for turning an object into a portable record
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
and then propagates the upgrades into the object's contain, which is the horde case §7 had given
up on.

**Why this looked blocked an hour ago.** The living-world entanglement is entirely in the callers.
`ARMY_RECORD_SPAWN` (`0x00811104`) resolves the `Player` from an army id at `record+0x1C` through
`TheLivingWorldLogic`, and `LIVING_WORLD_ARMY_DEPLOY` above it resolves armies and battles. Calling
`0x00780172` directly with a `Player` skips both. The harvest (`0x00811E1F`) stays unusable
regardless — it filters on living-world players, `KindOf = ARMY_SUMMARY`, and an army id at
`obj+0x47C` — but nothing needs it, because `forEachTeamObject` plus `toArmyRecord` is the same
walk without the filters.

**So the object half becomes:**

| phase | work |
|---|---|
| snapshot | `PLAYER_FOR_EACH_TEAM_OBJECT`, and per object: construct a `0xD8` record with `ARMY_ENTRY_RECORD_CTOR`, call `toArmyRecord`, note its position and angle |
| restore | per record: `createObject(player)`, then `setPosition` and `setOrientation` from §6.5 |

The hand-built field copy in §6.5 is no longer the plan. Its addresses stay because restore still
needs `setPosition`, `setOrientation` and the script-name binding, and because they document what
`createObject` is doing underneath.

### 6.9 Power cooldowns must be rebased, and script timers must not

**Out of scope, decided 2026-09-08.** Recorded because the reading is done and because the contrast
below is what keeps the script timers correct - not because anything is going to act on it.

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
because both are "a timer". That is the reason this section still earns its place: it is what says
the script timers in §6.2 carry **verbatim** rather than by analogy with a cooldown.

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

### 6.11 Restore lands in the right place — settled

This was written down as needing a live run. Most of it did not, and the part that did has now been
measured.

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

Those two together are the assumption §7's merge rule needs, and both hold statically.

**Measured, and it closes the question.** The remaining doubt was whether some load-time pass
evaluates scripts once during construction — an init or on-load sweep — which would let a script
see carried counters before restore wrote them. The runner logs `"Run script - "` (`0xBF9C60`) or
`"Run script false - "` (`0xBF9C4C`) at `0x00609AE7`, each line carrying a leading frame number, so
a `-scriptdebug2` log answers it without anything being built.

**Run 2026-09-08: the first script line is at frame 1.** Nothing evaluates during construction. The
window between `loadMap` returning and the first evaluation is real, and restore sits inside it.

So the ordering holds on all three counts — installed during the load, nothing evaluated during the
load, and no gameplay update until after restore — and §7's merge rule needs no adjustment.

**A lead for someone else's open question.** `script-holder.md` §5 records that the bulk installer
attaching script lists to players "was not found", and reads the list as `Player+0x334`. That
labelling looks wrong. The runner obtains its holder from `0x007A2C47`, a **two-name keyed lookup**
into a map at `holder+0x150` returning the value at node `+0x18`, and it is that returned object
which carries the list at `+0x334`. In the install call at `0x007A6DEA` the object holding `+0x334`
and the team being registered are two different things. So the lists may not live on `Player` at
all, which would explain why no `Player`-side installer was ever found. Not chased further here
because this patch does not need it.

### 6.12 Still open

| # | unknown | how | size |
|---|---|---|---|
| 1 | **What `+0x191C4` holds** | Not a name-to-id table; a name to byte map with its value at node `+0x14`. Only matters if it turns out to carry script state a mapper can set, in which case it joins the carried set. | two hours |

## 6.13 What building the mechanism settled

The first layer is written, and three things came out of writing it that reading could not settle.

**The action id is chosen, and the reason is corpus evidence rather than taste.** `540`
`PLAYER_ASSIMILATE_WITH_ARMY_BY_NAME`, one of the five consecutive stubs at 539-543. The whole
assimilate and reinforcement family appears **zero** times across the 480-map Edain corpus, so no
existing map can trigger a transition by accident. `LIVING_WORLD_DESPAWN_ARMY` (365) and
`MAP_REVEAL_IN_TRIGGER` (553) each have one live occurrence and cannot promise that. Its stock
parameters are a player and a string, which is the shape the later layers want anyway: the string
is the destination, and the player slot is where "whose army carries" goes.

**The game mode is read back, not pinned.** `startNewGame`'s first argument lands in
`TheGameLogic+0x110`, and the session's current mode is already there, so the cave passes
`[ecx+0x110]` and a skirmish stays a skirmish. Pinning mode 8 the way the `ScriptHolder` path does
would drop every transition into living-world mode.

**The hook must bracket itself with `pushad`/`popad`.** `GameLogic::update` is dispatched
`__thiscall`, so `ecx` holds `this` at the entry the hook takes over, and the prologue has not run.
The original scope said nothing about this because it is invisible until the code is written.

Two costs the scope did not name. The patch takes `GameLogic::update`'s first five bytes, which
**`live-bridge` also takes**, so the two do not compose; the framework raises for whichever is
applied second rather than corrupting the site. And the mapper-facing name stays
`PLAYER_ASSIMILATE_WITH_ARMY_BY_NAME` in WorldBuilder until the optional rename patch of §3 is
built, so a map reads oddly even though it works.

### First run, 2026-09-08: the swap fires and the load then dies

Transitioning to `map edain Tolfalas` **reached the destination map's load screen** and then
crashed with no error dialog.

That is a real result and most of it is positive. Reaching the load screen means the action fired,
the pending flag survived to the hook, `AsciiString::format` built a path the file system resolved,
and both `startNewGame` and `loadMap` were entered. §2's mechanism works. The re-entrancy worry
this section previously led with is **not** what happened: a nested update would have faulted
before the load screen appeared, not during it.

Two candidates were ruled out on the way to the real one:

- **`TheGameLogic` is not reallocated by a load.** `0x00DE412C` has exactly one writer,
  `0x0062CD16`, inside the startup constructor. So the `this` the hook restores through `popad`
  stays valid, and the update the cave returns into is not running on a freed object.
- **The map name is not the problem**, since the existence check passed and the loader got as far
  as its screen.

**The live suspect is `TheGameInfo`.** The world builder `GameLogic::startNewGame` (`0x0062F91A`)
rebuilds players by walking `TheGameInfo` (`0x00DE892C`) slots 0-7 at `0x0062F976` through
`GAME_INFO_GET_SLOT`, and branches on the game mode at `0x0062F992` to consult the skirmish info at
`0x00DE8930` for modes 0 and 6. The cave updates `TheWritableGlobalData`'s active map name and
**nothing else**, so at the moment the world is rebuilt the lobby still describes the *previous*
map: its name at `GAME_INFO_MAP`, its CRC and size, and a slot layout matching its start positions.
A destination whose player and start-position layout differs from the source is then built against
slots that correspond to nothing in it.

That is also why the `ScriptHolder` path the swap was copied from does not hit this: it runs in
mode 8, and a living-world session does not construct players from lobby slots the way a skirmish
does.

The setters exist if this is confirmed - `GameInfo::setMap` (`0x00801C46`), `setMapCRC`
(`0x0080298E`), `setMapSize` (`0x00802A49`) - but they only fix the *name*. A slot layout that does
not match the destination is a design question rather than a missing call, and the likely answer is
that a destination must declare the same players as its source.

**Run 2, same day: `TheGameInfo` is a red herring.** Transitioning between `map edain thirdhall`
and `map edain thirdhall2` - the same map saved twice - crashed identically. Same sides list, same
start positions, same slot layout, so nothing about the lobby describing the previous map can be
responsible. The suspect above is dead and the fault is in the swap itself.

What that leaves is the one difference static reading cannot resolve: the engine has **no
game-to-game path at all**. Every legitimate `MSG_NEW_GAME` arrives from the shell map, so
`startNewGame` and `loadMap` have only ever been entered with a shell session live, never with a
playing one. The guard at the top of the handler is not the general "already in a game" test it
first looks like - `0x00484A85` returns true only for modes 4 and 7 - so it does not name the
constraint either.

Static analysis has stopped paying here. Three readings of the handler produced three hypotheses
and the two that were testable were both wrong, which is the signal to get a faulting address
instead of a fourth hypothesis. The crash prints no dialog, so it is an unhandled fault rather than
the caught C++ exception [`living-campaign/script-holder.md`](living-campaign/script-holder.md) §4
warns writes no `.dmp` - which means [`crash-dump`](crash-dump.md) will capture it. The two patches
compose: `crash-dump` hooks the unhandled-exception filter and `Debug::crash`, neither of which
this patch touches.

### The crash, localised from a dump

Two dumps from 2026-09-08, both identical. `sage_save`-style manual minidump parsing (exception
stream, thread context, memory ranges) rather than a debugger.

| | |
|---|---|
| exception | `0xC0000005`, read of address `0x158` |
| faulting instruction | `0x007A2052`, `mov eax, [ecx]` |
| `ecx` | `0x00000158` |
| `edi` (`this`) | `0x087A7490` |

The faulting routine is `0x007A2045`: `esi = this + 0x140`, `ecx = [esi]`, `mov eax, [ecx]` - a map
walk whose container head is garbage. Its **single** caller is `0x00697C4E`:

```asm
00697c45  push dword [esi + 0x74]        ; OBJECT_ID
00697c48  mov  ecx, [esi + 0x31c]        ; OBJECT_TEAM
00697c4e  call 0x7a2045
```

So an `Object`'s **team** is being asked about that object, and the team's container at `+0x140`
holds `0x158` instead of a pointer.

**The stack proves the patch drove it.** Return addresses, oldest first:

```
00639ee4   GameEngine, call [eax+0x28]
006326cc   call [eax+0x98]  -> GameLogic::update   (0x00BD85C4 holds 0x0062E4E8; base 0x00BD852C)
00f0712a   the cave - jumped into at update's entry, so update itself pushes no frame
00631580   GameLogic::loadMap, just after its call to the world builder
0062fbdb   GameLogic::startNewGame
007a62xx   team instantiation (the 0x007A6C91 family)
0069xxxx   object creation
007a2052   fault
```

The crash is therefore **inside the new map's world construction**, not after the load and not in a
logic frame. Reaching the load screen and dying there is exactly this.

**Ruled out, each by evidence rather than argument:**

- *Map shape / `TheGameInfo`* - an identical copy of the source map crashes identically.
- *Re-entrancy* - `GameLogic::update` appears once on the stack, and only as the frame the cave was
  jumped into from.
- *A stale `this`* - `TheGameLogic` has one writer, `0x0062CD16`, in the startup constructor.
- *A missing subsystem reset* - the two `SubsystemInterface` slots either side of update
  (`0x00BD85B8`, `0x00BD85C0`) both hold `0x0063F3BF`, which is a bare `ret`.

**What remains.** An object reaching world construction with a team that is not a live team. The
engine has no game-to-game path: every legitimate `MSG_NEW_GAME` arrives from the shell map, so the
previous session is always torn down on the way out rather than by the loader. The next piece of
work is finding that teardown - the nearest analogue in the image is the living-world battle exit
at `LIVING_WORLD_BATTLE_END` (`0x00626662`), which is the only place the engine leaves a playing
session for another one - and calling it before the swap.

### Second dump: the message path was necessary and not sufficient

Posting `MSG_NEW_GAME` moved the crash but did not remove it. The third dump faults at the **same
instruction** (`0x007A2052`, reading `0x148` where the first read `0x158`), and the stack is now
entirely the engine's own:

```
00639ee4   GameEngine
006326cc   -> GameLogic::update  (the cave's frame is gone; it posted and returned)
00779df3   MSG_NEW_GAME handler, just after its own call to loadMap
00631580   GameLogic::loadMap
0062fbdb   GameLogic::startNewGame
007a62xx   team instantiation
0069xxxx   -> Object::setTeam
007a2052   fault
```

So the sequencing was fixed and the fault is unchanged. **The engine's own handler crashes the same
way**, which means this is not something the patch does wrongly around the transition - it is the
transition itself.

**What the fault is.** `0x00697C09` is `Object::setTeam(Team *)`: it reads the object's current team
from `OBJECT_TEAM`, and if that is non-null removes the object from it before joining the new one.
The null case is handled. What is not handled is a **non-null stale** pointer, which is what it has.
Reading the pointed-to memory out of the dump settles what it is:

```
+0x000: 09ec8468 0a00a5a0 00000000 00000000     <- first dword is a heap pointer, not a vtable
+0x140: 00000148 00000098 45033000 447e77af     <- 1017.9f
+0x150: 43481400 00000000 00000000 3f800000     <- 200.08f, 1.0f
```

Floats that read as a position and a scale. The "team" is **recycled heap** - the team was freed and
something else now occupies the memory - and an object still points at it.

**The conclusion, and the design that follows.** The engine has a game-to-shell path and a
shell-to-game path. It has no game-to-game path, and `MSG_NEW_GAME` carrying a *playing* mode
mid-match is a case nothing in the shipped game produces: the only mid-match `MSG_NEW_GAME` in the
image is the shell return at `0x0075DEE2`, and it carries mode 4. `loadMap` is visibly
mode-conditional about this - at `0x0063153A` it nulls `TheGameInfo`, but only when the incoming
mode is 4.

So the transition became **two** posted messages with the shell in between: leave the match for the
shell map, wait until `TheGameLogic`'s mode actually reads 4, then name the destination and post
again with the mode the session had. That is what a player does by hand, and it is the only
sequence the engine is known to survive. The destination's name is written only in the second step,
because the shell load reads the same field.

### Third run: past construction, into `map.ini`

The two-step transition cleared the access violation. The next failure is a different one, later in
the load, and it is a clean fatal INI error rather than a fault:

```
RemoveModule ModuleTag_01 was not found for EreborTorch.
Error parsing field 'RemoveModule' in block 'Object' in file
'maps\map edain thirdhall\map.ini', line 418.
```

A map's `map.ini` is loaded as an **override pass** over the already-parsed global data: the loader
builds `<mapdir>\map.ini` at `0x00627223`, checks it exists, and loads it with INI load type `2`
at `0x00627250`. Those overrides mutate the live definitions.

`RemoveModule` is **not idempotent**. Applying it twice in one process fails, because the second
application looks for a module the first one removed - which is exactly what happens when two maps
whose `map.ini` carries the same directive are loaded one after another without the overrides being
reset in between. The obvious suspects for that reset - a subsystem legend walker - did not turn up;
`0x005B45D8` is registration, not a reset pass.

**Tracing the override lifetime.** `map.ini` is applied by the map-INI loader at `0x0062710D`,
which has exactly **one** caller: `0x0062FA07`, inside `GameLogic::startNewGame`. So the overrides
are applied on every world build. Nothing in that path reverts them first - `0x0062550D` beside it
is a small forwarder, the subsystem legend site `0x005B45D8` is registration rather than a reset
pass, and no "delete overrides" routine turned up by string or structure.

If that reading is right, **`map.ini` overrides accumulate for the lifetime of the process**, and
loading two maps whose `map.ini` carries the same non-idempotent directive fails on the second one
however you got there - by script transition or by quitting to the menu and picking the next map.
Nobody hits it in normal play because nobody loads two maps with the *same* `map.ini` in one
session. Two byte-identical copies, which is what the current test pair is, is precisely the
pathological case.

**The test that separates the two readings** is the manual equivalent of what the patch now does:
load the first map from the menu, quit to the menu, load the second from the menu. Same two maps,
no patch involved. If that errors, this is an engine limitation the patch merely reaches, and the
identical-copy pair has to go. If it does not error, the override reset exists somewhere and the
transition is skipping it.

**If it is the limitation**, there are two answers and both are cheap. The mapper rule - a chain of
maps must not carry non-idempotent `map.ini` directives for the same object - or a small separate
patch downgrading `RemoveModule`'s "not found" from a fatal parse error to a skip, which would make
map chains workable without constraining what a mapper may write.

**Whether this is the patch's problem is a one-test question, and the test is not mine to run.**
The two-step transition now goes entirely through the engine's own route: the shell return, then a
new game start. That is structurally what a player does by quitting to the menu and picking another
map. So if a manual quit-and-restart onto a map with the same `map.ini` reproduces this error, it is
stock behaviour that the patch merely makes easy to reach, and the answer is a **mapper rule**: a
chain of maps must not carry non-idempotent `map.ini` directives for the same object. If a manual
restart does *not* reproduce it, something in the transition is skipping an override reset the menu
path performs, and that reset is the next thing to find.

One asymmetry is worth recording either way: the second post reuses the previous match's
`TheGameInfo`, where the skirmish menu builds a fresh one naming the chosen map and its slots. That
cannot explain an INI parse error, which happens before any of it is read, but it is a real
difference from a manual restart and it will matter later.

### Fourth and fifth runs: the shell step was never reaching the shell

Two observations from the same session, and together they explain both earlier failures at once.

1. With `map.ini` files present, a transition to a *different* map still tried to load **the first
   map's** `map.ini`.
2. With the `map.ini` files deleted, the crash returned - byte for byte the same fault at
   `0x007A2052`, same stack through the engine's own handler into world construction.

**Posting `MSG_NEW_GAME` with the shell's mode does not select the shell map.** The loader takes
the map from `GlobalData`'s active map name (`GLOBAL_DATA_ACTIVE_MAP`) whatever the mode argument
says; the mode only selects *how* the session is built. Step one posted mode 4 and changed no map
name, so the engine reloaded **the map already running**: re-applying its `map.ini` over itself,
which is observation 1, and rebuilding its world on top of the live one, which is observation 2.

So the shell step never reached the shell, and the two-step design was never actually tested. Both
crash signatures were the same underlying mistake wearing different clothes depending on whether a
`map.ini` was present to fail first.

The missing piece is one call. `ShellMapName` is `GlobalData+0xAEC` (`GLOBAL_DATA_SHELL_MAP`, row
248 of the `GameData` table), an `AsciiString` defaulting to the full path
`Maps\ShellMap1\ShellMap1.map` written by `GlobalData`'s constructor at `0x0064306B` - the same
shape as the active map name. Step one now copies it over the active name with
`AsciiString::operator=` (`ASCII_STRING_COPY`, `0x00436030`, the same call `startNewGame` uses to
promote the staged name) before posting the mode.

**What this retires.** The conclusion recorded above - that the engine has no game-to-game path and
world construction cannot run over a live session - was drawn from a fault that is now explained by
the map name never changing. It may still be true; nothing has tested it. The two-step through the
shell stands because it is what the engine's own quit-to-menu does, not because that conclusion
survived.

### Where this stands, and why the next step is instrumentation

The shell-map naming was a real bug and fixing it did not stop the crash. Five dumps now, and the
fault is **identical every time**: `0xC0000005` at `0x007A2052`, `Object::setTeam` reading a
non-null team whose container is garbage, inside team instantiation, inside world construction.

It is identical across four materially different ways of asking for the transition - the direct
`startNewGame`/`loadMap` pair, one posted `MSG_NEW_GAME`, the two-step that silently reloaded the
running map, and the two-step that names the shell map first. **That invariance is the finding.**
Changing how the transition is requested does not move it, which says the fault is not in the
request path.

**What cannot currently be told apart** is which of the two loads dies: the shell load, or the
destination load after it. They produce the same stack, because both are `MSG_NEW_GAME` -> loader
-> world builder -> team instantiation. The dumps cannot answer it either, because `crash-dump`'s
default type (`0x1B65`) carries heap but **not module data segments**: `TheWritableGlobalData` and
`TheGameLogic` are both unreadable, so the map name being loaded and the game mode are both
unknown. Every conclusion about which step failed has been inferred from side effects.

That is the thing to fix before hypothesis six. Applying `crash-dump --dump-type 0x1b67` adds
`MiniDumpWithFullMemory` and captures the data segments, which makes four questions answerable
directly from the next dump rather than argued from symptoms:

| question | where it is read from |
|---|---|
| which map was loading | `GLOBAL_DATA_ACTIVE_MAP` on `TheWritableGlobalData` |
| whether the shell step happened | the same field reading `Maps\ShellMap1\ShellMap1.map` |
| which game mode the load was given | `TheGameLogic + 0x110` |
| which step the patch thought it was in | `PENDING_OFF` and `SAVED_MODE_OFF` in `.maptran` |

The last row is the one that matters most: the cave's own state machine has never been observed,
only inferred.

### The full-memory dump: the crash is in the **shell** load

Raising `crash-dump --dump-type` to `0x1b67` captured the data segments, and the first dump that
carries them answers in one read what five earlier ones could not:

| read from the dump | value |
|---|---|
| `.maptran` `pending` | `2` - step one done, waiting for the shell |
| `.maptran` `saved_mode` | `2` - an ordinary skirmish |
| `.maptran` name buffer | `'map edain Tolfalas'` |
| `GLOBAL_DATA_ACTIVE_MAP` | `'Maps\ShellMap1\ShellMap1.map'` |
| `GLOBAL_DATA_SHELL_MAP` | `'Maps\ShellMap1\ShellMap1.map'` |
| `TheGameLogic + 0x110` | `4` |

**Step one works.** The shell map is named, its mode is posted and taken, the destination is
buffered, and the state machine is correctly parked waiting. The crash happens **inside the shell
map's load**, before step two ever runs.

That retires a lot at once. The destination map is irrelevant - it is never reached. The `map.ini`
collision was a side effect of the earlier bug and not a separate problem. And the two-step design
is not what is failing: **step one alone reproduces the crash**, and step one is nothing more than
"leave this match for the shell map", which the engine does every time a player quits to the menu.

**So the question is now narrow and well posed:** why does posting `MSG_NEW_GAME` with the shell's
mode, from the logic update, crash when the menu's own quit does the same thing safely?

The difference is visible. The stock quit does not just post that message. It runs
`0x0075DCF4` - reached from its single caller `0x0075E1BA` - which performs a long teardown
sequence (window and subsystem calls through vtable slots `+0x20` and `+4`, interleaved with
`operator delete`) and only then posts at `0x0075DEDA`. The cave posts the message with none of it.

The next step is therefore to identify which part of that teardown is load-bearing, rather than to
replicate the post more faithfully. The post is already faithful; what precedes it is not.

### The teardown, found

The dump narrowed the failure to "posting `MSG_NEW_GAME` with the shell's mode, from the logic
update, crashes where the menu's own quit does not". The difference is a call, and it was findable
once the question was that specific.

`0x0075DE01` is the go-to-shell routine - `__thiscall`, three bool arguments, and the function that
posts `MSG_NEW_GAME(4)` at `0x0075DEDA`. (An earlier reading put that post inside `0x0075DCF4`;
that address is a **destructor** and the boundary was wrong. The real function begins at
`0x0075DDD7`'s successor.) Before posting, it emits message `0x22` - and separately, the mid-match
quit button at `0x00921A67` calls:

```asm
00921a67  push 1
00921a69  mov  ecx, esi                 ; TheGameLogic
00921a6b  call 0x625e36                 ; GameLogic::clearGameData(Bool)
```

**`CLEAR_GAME_DATA` (`0x00625E36`) was already recorded in `addresses.py`** - as the site a
mid-match quit takes on the way to ending a recording. It was sitting in the module the whole time
under a name that described a different consumer, which is why six passes over the load path never
turned it up: the load path is not where it lives.

So step one now ends the match before it asks for the shell:

```
clearGameData(1)  ->  name the shell map  ->  post MSG_NEW_GAME(4)
```

`ret 4`, one bool, and the quit passes `1`. That argument only gates a network branch which a
single-player session skips at `0x00625E49` anyway, so `1` is both faithful to the stock call and
inert here.

This is the first change aimed at what the dump actually showed rather than at a reconstruction of
what might be happening. Whether it is sufficient is a separate question from whether it is
necessary - it is plainly necessary, since the world was being built over a live session, which is
exactly the fault `Object::setTeam` reported every time.

### Score screen: the teardown was right, the timing was not

With `clearGameData` added, the run reached the **end-of-match score screen**, which flashed and
then crashed. That is a different failure again, and it says the teardown call is correct: the
match genuinely ended.

`0x00921904` is the **pause menu**'s handler - it pushes `APT:Pause` at `0x00921A9B` - and its Quit
branch is where `clearGameData(1)` comes from. So the call is the right one, but it is not a
self-contained teardown: it hands the session to the engine's own end-of-match flow, which shows
the score screen and reaches the shell map **on its own schedule**.

The build that produced the score screen also posted `MSG_NEW_GAME(4)` and named the shell map by
hand, in the same breath. That put a second shell request into the middle of a flow already heading
there. Two transitions, one session.

So step one now does the teardown **and stops**:

```
step one:  save the mode, arm step two, clearGameData(1), return
step two:  wait for TheGameLogic's mode to read 4, then name the destination and post
```

Nothing names the shell map any more - the engine's own flow does that, as it does for a real quit.
Step two's wait was already written to watch for mode 4 and needed no change; it now waits for the
engine to arrive there rather than racing it.

**What is unresolved** is the score screen itself. If the flow stops there for a click, the
transition will stall until the player dismisses it, which is wrong for a scenario but proves the
mechanism. Suppressing it is a separate problem and only worth solving once the chain completes.

**A note on the dump for this run: it is unusable.** 45 MB, one stream, no exception record - the
process died before the writer finished. Disk space was not the cause (1.1 TB free). A full-memory
dump is around 950 MB and evidently does not always survive the crash that produced it, so a run
that crashes without leaving a readable dump is now a possible outcome to plan around rather than
be surprised by.

### Read from a live process: the wait was on the wrong number

The teardown worked. The run showed the score screen and then returned to the **skirmish lobby**,
and simply stopped there - no crash, no transition. With the game still sitting in that state,
`sage_live`'s `ProcessMemory` read the answer straight out of it, no dump required:

| | |
|---|---|
| `.maptran` `pending` | `2` - step two armed and waiting |
| `.maptran` `saved_mode` | `2` |
| `.maptran` name | `'map edain Tolfalas'` |
| `TheGameLogic + 0x110` | **`9`** |
| `GLOBAL_DATA_ACTIVE_MAP` | `'maps\map edain thirdhall\map edain thirdhall.map'` |

**Mode 9, not 4.** The end-of-match flow does not park on the shell map; it leaves the engine at
mode 9 in the skirmish lobby. Step two waited for `4` and would have waited forever. The engine's
own shell return special-cases the same value at `0x0075DEAA`, which is corroboration that 9 is a
real resting state rather than a transient.

That branch also shows the right way to name a map from this state:

```asm
0075debc  mov  eax, [0xde4364]
0075dec1  lea  ecx, [eax + 0xaec]     ; ShellMapName
0075dec7  push ecx
0075dec8  lea  ecx, [eax + 0xac0]     ; the STAGED name, not the active one
0075dece  call 0x436030               ; staged = ShellMapName
```

So step two now does two things differently: it proceeds on mode 4 **or** 9, and it formats the
destination into `GLOBAL_DATA_STAGED_MAP` rather than the active name. `startNewGame` promotes the
staged name and clears it, so a request that never gets served cannot leave a stale map name
behind - which is what made the very first two-step build silently reload the running map.

**Method note.** This was the cheapest diagnosis in the whole effort and it needed no crash, no
dump and no guess: the failure state was still on screen, so the state was still in memory.
`sage_live` should have been the first instrument reached for, not the last.

### The transition works, and the first carryover layer

**The map transition works.** Action, teardown, score screen, lobby, destination map. Six wrong
diagnoses and one live memory read to get there.

Nothing carried, which was expected - every build to this point was mechanism only. §6.8's record
round-trip is now built on top of it, for the local player's army:

| phase | where | what |
|---|---|---|
| snapshot | step one, **before** `clearGameData` | `PLAYER_FOR_EACH_TEAM_OBJECT` over the local player, and per object: construct a record in the arena with `ARMY_ENTRY_RECORD_CTOR`, fill it with `OBJECT_TO_ARMY_RECORD`, and store the position and facing beside it |
| restore | a new step three, once the mode matches the saved one | per record: `ARMY_RECORD_CREATE_OBJECT` onto the local player, then `OBJECT_SET_POSITION` and `OBJECT_SET_ORIENTATION` |

The engine marshals template, health, purchased upgrades and veterancy itself, so the patch copies
none of it. What the record does **not** carry is position, which is why each slot is
`ARMY_RECORD_SIZE` plus a `Coord3D` and an angle - `SLOT_SIZE` `0xE8`, 256 of them, a 58 KB arena.

Units come back at the coordinates they left. That is right for maps laid out as a continuous
world and wrong for arbitrary pairs; an entry waypoint is the better rule and a later change.

**One bug worth recording, because it assembles cleanly and is invisible.** `RECORD_POSITION_OFF`
is `0xD8`, which does not fit a **signed** byte displacement. Emitted as `89 47 D8` it is not
`[edi+0xD8]` but `[edi-0x28]`, writing over the record instead of after it. The disassembly check
caught it before it ever ran; the test that now pins it asserts no negative displacement appears in
the routine at all.

### The carryover's first crash, and what the dump could not say

A new fault, in a new place: `0x0062E5A0`, **inside `GameLogic::update` itself** rather than world
construction. The instruction is `mov eax, [ecx+4]` two after `lea ecx, [esi + 0x164]`, and `esi`
- the engine's own `this` for the whole function - is **zero**. Register or stack corruption, not
a dangling object.

The previous build did not crash, so the fault is in the snapshot or the restore. Every call either
adds makes was re-checked against its actual epilogue:

| call | cleanup | pushed |
|---|---|---|
| `PLAYER_LIST_GET_LOCAL_PLAYER` | `ret` | 0 |
| `PLAYER_FOR_EACH_TEAM_OBJECT` | `ret 8` | 2 |
| `ARMY_ENTRY_RECORD_CTOR` | `ret` | 0 |
| `OBJECT_TO_ARMY_RECORD` | `ret 4` | 1 |
| `ARMY_RECORD_CREATE_OBJECT` | `ret 4` | 1 |
| `OBJECT_SET_POSITION` / `OBJECT_SET_ORIENTATION` | `ret 4` | 1 |

All balanced, and the callback's convention was confirmed the long way rather than assumed:
`0x007A0626` pushes `ctx`, then the object, then `call [ebp+8]`, then `pop ecx` twice - so
`fn` is argument one, the object comes first, and the caller cleans. That is what the cave emits.

One difference from the engine's own use of that walk **was** real and is now fixed: the engine's
per-object callback tests `OBJECT_STATUS_UNDER_CONSTRUCTION` at `0x00885234` and skips before
counting. The snapshot did not. It now does.

**The dump could not answer the question that matters.** `crash-dump` had reverted to its default
type when the build was re-applied, so the module data segments are absent and `.maptran`'s
`count` and `pending` are unreadable. Those two words say whether the crash happened during the
snapshot on the source map or during the restore on the destination, which halves the search. The
next run needs `--dump-type 0x1b67` again.

### The full-memory dump, read at last: the lobby ignores the message

With `normal = 0x1B67` finally set (`deep` was already that value and is only used by the engine's
own `fulldump` command - changing it did nothing), the dump carries the data segments:

| | |
|---|---|
| `.maptran` `pending` | `3` |
| `.maptran` `count` | **`58`** |
| `.maptran` name | `'map edain Tolfalas'` |
| staged map | `'maps\map edain Tolfalas\map edain Tolfalas.map'` |
| active map | `'maps\map edain thirdhall\map edain thirdhall.map'` |
| `TheGameLogic + 0x110` | `9` |

**The snapshot works.** 58 objects captured off the local player before the teardown. **Step two
works**: it staged the destination correctly and armed step three. And then nothing happened.

**A `MSG_NEW_GAME` posted from mode 9 is not acted on.** The mode stayed 9, the staged name was
never promoted over the active one, and the active map still named the source - so `startNewGame`
never ran. The message went out and the engine ignored it.

So the transition stalls in the lobby, and the crash that follows is a consequence of sitting there
in that state rather than its cause. The fault itself is in a plugin dispatch: `0x006034FB` is
`GetProcAddress(module, "ForceAppContinue")` followed by `jmp eax`, tail-jumping into a loaded DLL,
and the engine's `this` for `GameLogic::update` comes back zero. `interpolation-alpha`'s cave at the
adjacent `ALPHA_RECOMPUTE` site was checked and preserves `ecx` correctly, so it is not that.

**The fix follows the same rule as everything else that has worked here: only ask the engine for
transitions it already performs.** Mode 4, the shell map, is the state its own shell-to-game start
works from; mode 9 is not. So the lobby state now stages the shell map and posts *its* mode, and
the destination is only requested once the mode reads 4:

```
1  snapshot the army, clearGameData, arm 2      -> engine shows the score screen, lands in the lobby
2  mode 9 -> stage the shell map, post mode 4   -> engine loads the shell map
   mode 4 -> stage the destination, post the saved mode, arm 3
3  mode == saved mode -> put the army back
```

Four states, each waiting for a mode the engine reaches by itself.

### The fix, and what it cost to find

Replacing the two direct calls with the posted message is a fifteen-instruction change, and every
hypothesis before it was wrong. Worth recording which, because the wrong ones all *sounded* better
than the right one:

| hypothesis | killed by |
|---|---|
| re-entrancy through the loading screen | the stack: `GameLogic::update` appears once, as the frame the cave was entered from |
| the lobby still describing the old map | an identical copy of the source map crashing identically |
| `TheGameLogic` reallocated by the load | one writer, `0x0062CD16`, in the startup constructor |
| a missing subsystem reset | both vtable slots either side of update hold `0x0063F3BF`, a bare `ret` |

What actually settled it was not another reading of the swap. It was asking **where the engine
already does this**, which is the shell return, and finding it takes a different route entirely.
The direct pair was copied from `startCampaign` because that was the only mid-session map load in
the image; it is also the only one that runs from the shell, which is the property that mattered
and the one that was not checked.

### The shell hop takes the `GameInfo` with it

The four-state machine reached the destination. The dump taken from the next crash reads, in full:
`TheGameLogic + 0x110` is **2**, `GlobalData + 0xC` names `maps\map edain Tolfalas\map edain
Tolfalas.map`, the staged slot is empty and the pending flag is **3** with 60 records banked. So
`startNewGame` ran, promoted the destination over the active name and handed off to `loadMap`. The
swap is done; the crash is inside the destination's own load.

The faulting instruction is `0x0081C650`, `mov eax, [ecx]`, with `ecx` zero:

```
0081c64a  mov  ecx, [esi + 0x88]     ; the load screen's progress window
0081c650  mov  eax, [ecx]            ; <- faults
0081c653  call [eax + 0x34]
```

`esi` is the `LoadScreen` at `TheGameLogic + 0x120`, alive and correctly built for game mode 2.
Only its `+0x88` is null, and the constructor at `0x0081D3B4` initialises that field to zero, so
what did not happen is the assignment. There is exactly one:

```
0081cb08  ; LoadScreen::init(GameInfo *)
0081cb18  mov  eax, [ebp + 8]
0081cb20  cmp  eax, edi              ; edi = 0
0081cb27  je   0x81d30d              ; hand it a null GameInfo and it returns, field untouched
0081cb2d  mov  [ebx + 0x88], eax
```

and its one caller passes `TheGameInfo` straight through:

```
0063155a  push [0xde892c]            ; TheGameInfo, into loadMap's helper
0062dcaa  call 0x626a87              ; getLoadScreen(mode) - reads TheGameLogic + 0x110
0062dcb1  mov  [esi + 0x120], eax
0062dcbe  call [edx + 8]             ; loadScreen->init(theGameInfo)
0062dcc5  call 0x62550d              ; first progress tick -> the fault above
```

`TheGameInfo` was null. Six instructions into `loadMap` is the reason:

```
0063152d  cmp  [esi + 0x110], 4      ; game mode 4, the shell map
00631538  jne  0x631540
0063153a  mov  [0xde892c], ebx       ; TheGameInfo = NULL
```

**`loadMap` nulls `TheGameInfo` for the shell map and for nothing else.** The hop through the shell
that made the transition work is the same hop that took the `GameInfo` away, and the destination
then loads without one. The load screen is only the first thing to notice.

The skirmish info itself survived - the dump has `THE_SKIRMISH_GAME_INFO` (`0x00DE8930`) at
`0x08E07F10` with `THE_GAME_INFO` at zero. Those two globals are written together by the shell
menu: `0x0082BE98` sets both when the skirmish info is created, and `0x0082BE30` nulls both when it
is destroyed. So a non-null `THE_SKIRMISH_GAME_INFO` is a live object, and the repair is the
assignment the shell start already makes, five instructions in the mode-4 arm just before the
destination's mode is posted:

```asm
mov  eax, [THE_SKIRMISH_GAME_INFO]
test eax, eax
je   no_game_info
mov  [THE_GAME_INFO], eax
no_game_info:
```

It has to be here rather than earlier: the arm runs once the shell map is up, which is after that
`loadMap` cleared the global, and `loadMap` for the destination's own mode never clears it.

This is also the shape of the answer to the last four crashes in a row. Each one was the engine
being asked for a state it does reach on its own, and each fix was a smaller instruction sequence
than the reading that preceded it.

### The destination loads; the selection rule was the wrong one

The transition now completes. Read out of a dump taken twenty seconds into the destination:
`TheTerrainLogic + 0x1C` is **520 x 370**, which is `map edain Tolfalas`'s heightmap exactly;
`TheTerrainVisual`'s world heightmap holds the same pair and its filename buffer reads
`maps\map edain Tolfalas\map edain Tolfalas.map`; and the 221 live objects match that map's own
object list template for template (19 `FarmTemplate`, 16 `WirtschaftPlotFlag` - the source map has
24 and 0). The map swap is right, logic and render both.

**What was wrong was what got carried.** §6.8 chose `forEachTeamObject` plus `toArmyRecord`
because it is "the same walk without the filters", and dismissed the harvest at `0x00811E1F` as
unusable. The filters were the part worth keeping. Two of the harvest's four are not
living-world-specific:

```
00811e93  mov  eax, [edi + 4]           ; the ThingTemplate
00811e96  test byte [eax + 0x118], bl   ; KindOf = ARMY_SUMMARY
00811e9c  je   skip
00811ea2  test byte [edi + 0x458], bl   ; still unidentified
00811ea8  jne  skip
```

`KindOf ARMY_SUMMARY` is War of the Ring's own answer to "which of these objects go home with the
player", and it is a better rule than "not a structure" for two reasons:

- Structures do not carry it, which is the reported bug: a player who had built a castle arrived
  on the destination with its walls, keep, elevators, plot flags and foundations around him.
- **Hordes carry it and their members do not.** Measured on the live map: `GondorFighterHorde_-
  StartUnit` has the bit, `GondorFighter` does not. The old walk took the horde *and* each of its
  members and put both back, so every horde was duplicated as a horde plus a crowd of loose
  soldiers. Filtering on the bit carries the horde once and lets `createObject` rebuild its
  members, which §6.8 already established that it does.

The fourth filter, `obj+0x458` bit 0, stays unidentified and is mirrored anyway: across the whole
221-object census it is set only on `FarmTemplate`, `GondorSpellBook` and `EdainTroopSpawnPoint` -
map furniture, never a unit or a horde.

**One consequence a mapper has to know about.** `ARMY_SUMMARY` is mod data, not engine data, and
Edain does not set it everywhere. It is on 257 unit files and on the hordes, but `HOBBIT_KINDOF`
(`_gamedata.inc:65`) omits it, so Pippin, Merry, Frodo and Sam do not carry. That is a one-word
fix in the mod rather than in the patch, and using the engine's own flag is what makes it a fix
the mod can make.

### The render scene is not the world: the shell map stays standing

Two screenshots settled what the dump could not. Where the destination should be: the citadel, the
walls, the plot-flag rings and the carried army, all correctly placed, on **black** - no terrain at
all. Scroll away and the Argonath are still there, lit and textured, with the in-game HUD over
them. That is the shell map's scenery, still in the render scene, twenty seconds into a game whose
logic world is entirely the destination's.

So the earlier reading was right and incomplete. `TheTerrainLogic` and the world heightmap both
hold 520 x 370 and the destination's path, and the object list matches its map file template for
template - the **logic** load is correct. The render scene simply never changed hands: the shell
map's drawables were never removed and the destination's terrain was never added. New objects do
reach the scene, which is why the army and the buildings draw.

The one hop in the whole sequence that came up whole is the shell map itself, and the thing in
front of it is step one's `clearGameData`. Nothing tears down between the shell map and the
destination. So the mode-4 arm now does, with the same call and the argument the engine's own
non-match teardown uses, leaving both messages in one stream in order: `MSG_CLEAR_GAME_DATA` from
the call, `MSG_NEW_GAME` from the post.

This is a hypothesis with one supporting instance, not a derivation - the stock shell-to-game start
calls `clearGameData` nowhere (there are three call sites in the image and all three are the pause
menu, the living-world battle exit, and one wrapper). The likeliest reason it does not need to is
that clicking Skirmish leaves the shell map first, so stock's start runs from mode 9 with nothing
standing, which is also what §"the lobby ignores the message" ran into from the other side.

### Still open: the four reserved trees keep a dead team

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

### The script state, built and checked against a live engine

§6.1 named the containers and §6.2 settled that timers need no rebasing. What was left was the
node layout, which the write-up had inferred. Reading it out of a dump instead settles it and
adds the piece that was missing:

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

**Two things fell out of reading the real records rather than the design.**

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

**One ordering question this cannot answer without a run.** The restore happens on the first logic
frame the destination is running, from `GameLogic::update`'s entry - which is before the script
engine's own update in that same frame. A destination script that initialises the same name at
frame 1 will therefore overwrite the carried value, which is the opposite of the policy §7 states.
Whether that matters depends on whether a mapper writes such a script, and the fix if it does is to
defer restore by one frame.

### The player's own state, and the field that must not carry

§6.7 had these recorded already, so the work was deciding which of them are *state* and which are
*bookkeeping*. Checked against a dump beside its screenshot: `Player+0x94` reads **4240** where the
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

### Sciences and upgrades, from the engine's own restore

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

**Upgrades are replayed, not written.** The earlier note here said the mask was out of scope partly
because writing it raw would set each bit and run nothing. The engine does not write it either:

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

**Power cooldowns are out of scope** (decided 2026-09-08), so the layer still outstanding is the
hero revival ledger in §6.6. Powers arrive ready; §6.9 records why that is the same outcome as
carrying `readyFrame` unrebased, and what rebasing would take if it is ever wanted.

## 7. Decisions the patch has to state, not discover

- **Counter and flag collision.** A name in both the snapshot and the new map's scripts takes the
  carried value; a carried name the new map never declares is created. The reverse policy — the
  new map wins — makes carrying pointless. State it in the patch description, because a mapper who
  initialises a counter on map 2 will otherwise be surprised.
- **Only the named players carry.** Everything else on the destination map comes from the
  destination map. Enemies, neutrals and structures are the new map's business. Structures were
  excluded from scope, so a player who built a base does not bring it.
- **Placement is by convention.** Carried units appear at a waypoint in the destination map,
  arranged around it. Relative formation is out of scope, and so are garrison and transport
  contents, horde member layout, and standing orders. A carried horde arrives as its members'
  templates. **Hordes are no longer in that list**: §6.8 pushes the carried upgrade list into the
  object's contain, so members come back dressed. Objects are created onto a `Team`, so the rule
  names a team, and `createObject` picks the receiving player's default team for you.
- **Refuse outside single player.** A map load is not in the order stream, so in a network game it
  is a dropped match for everyone. `THE_GAME_INFO` (`0x00DE892C`) and `GAME_MODE_SKIRMISH` are
  already in [`../addresses.py`](../addresses.py), so the check is a read.
- **Refuse, or mark, while recording.** The direct call pair avoids restarting the replay file,
  which means a replay recorded across a transition will run map 1's orders against map 2's world
  and diverge with nothing in the file to say why. Refusing is the honest default.
- **Saves are fine, and that is not an accident.** The transition materialises entirely into
  ordinary engine state, so a save taken after it is an ordinary save of map 2 and reloads without
  the patch needing to know. This holds only because §4 keeps the pending flag from ever spanning a
  frame boundary.

## 8. Acceptance test

1. Two maps and one script. Transition with a mixed army: a veterancy-2 unit, a levelled hero, a
   unit carrying a purchased upgrade. All three arrive with those properties, checked through
   `sage_live` rather than by eye.
2. A counter, a flag and a **timer** set before the transition. A timer with 60 seconds left must
   still have about 60 seconds left. §6.2 says this should work by construction, which makes it a
   test of the reading rather than of the design.
3. ~~A hero power on cooldown carries its remaining time.~~ Dropped with §6.9 - powers arrive
   ready by decision. Test 2 stands on its own: a script timer that resumed correctly is enough to
   show the tick-count reading was right.
4. Save on map 2 after a transition, quit to the shell, reload. The army and the script state come
   back.
5. Kill a hero on map 1, transition, confirm the hero is still dead and came back revivable at
   the level and with the upgrades he died with. §6.6 rebuilds the ledger through the engine's
   own `0x007C6D8E`, so this tests that call as much as the carry.
6. Transition twice, to confirm the arena and the pending flag survive being used more than once.

## 9. Effort

| piece | size |
|---|---|
| the action: repoint one dword, read two string parameters, set the pending flag | small |
| the `GameLogic::update` hook and the call sequence | small — §2 is the whole mechanism |
| script state snapshot and restore | small — §6.1 found the containers and the accessors, and §6.2 removed the conversion |
| object snapshot and re-materialisation | one day — §6.8 makes it two engine calls per unit rather than a field-by-field copy |
| player state | half a day — §6.7 found nearly all of it already recorded |
| hero revive | half a day — §6.6 found both the store and the rebuild call |
| gates, refusals, tests | one day |

Call it two to three days. The map swap is an afternoon, the script state is an afternoon, and
the object carry is a day now that the engine does the marshalling. What is left in §6.9 is
naming two round-tripped fields and one live check.
