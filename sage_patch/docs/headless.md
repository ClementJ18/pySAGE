# Running the game headless

> ⚠ **Experimental.** This patch is **unstable and largely untested** — it lives in
> [`patches/experimental/`](../patches/experimental/), `sage-patch list` marks it `exp`, and
> `sage-patch apply` warns before it writes. The status note below says how far it actually
> got; see the README's [Experimental patches](../README.md#-experimental-patches) note before
> applying it.

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR). Derived
statically — capstone over the image — and confirmed in game.

- **Cost:** one cave (`.hless`, 0x190 bytes), two byte edits in the command-line caller, one
  11-byte redirect at the draw call.
- **Risk:** low for what is built (§3a–c); §3d, the skirmish setup, is the real work and rests on
  a `GameInfo` layout nobody has mapped yet.
- **Status:** §3a–c **built** — see [`patches/experimental/headless.py`](../patches/experimental/headless.py). §3d and §3e
  are **scoped only**; §3d is blocked on question 2 in [Open](#open). **Runtime-verified in
  game.**

```sh
sage-patch apply headless --in game.dat.backup --out game.dat   # no parameters
sage-patch verify headless game.dat
```

## The complaint

Automated testing wants to run a lot of games and look at what happened. The stock engine makes
that expensive: it renders every frame at full resolution, it caps the loop to wall-clock, it opens
on a 3D shell map behind a Flash front end that has to be clicked through, and it refuses to start
a second copy of itself. [`../../docs/ml-agent.md`](../../docs/ml-agent.md) states the problem in
one line — "no headless mode, no uncapped clock, no scripted reset" — and treats all three as
reverse-engineering projects.

Two of the three turn out to be already present in the retail binary.

## 1. What the stock engine already does

Nothing in this section needs a patch, and a harness should take all of it before a byte is edited.

### The command line the retail build parses

Sixteen options, in a table of `{const char *name, int (*handler)(char **argSlot, int remaining)}`
at `0x00C35DA8`. The dispatcher is `0x007BA7E1`: it compares with `_strnicmp` and requires equal
length, rewrites a leading `0x96` (a Word en-dash) to `-` first, and adds each handler's return
value to the argument index, so a handler returns how many arguments it consumed.

| option | handler | what it does |
|---|---|---|
| `-file <path>` | `0x007BACA4` | **auto-start.** A `.map` starts a skirmish, a `.rep` plays a replay — no menus |
| `-noshellmap` | `0x007B9EC7` | clears `ShellMapOn` (`GlobalData+0xAF0`) |
| `-noaudio` | `0x007BA024` | clears the four audio flags at `+0x99C…+0x9A0` |
| `-win` / `-xres` / `-yres` | `0x007B9FC6`, `0x007BA104`, `0x007BA131` | windowed at an arbitrary size |
| `-randomSeed <n>` | `0x007BA795` | fixes `GlobalData+0x1228` |
| `-mod <path>` | `0x007BADB9` | mod tree, plus `preferLocalFiles` |
| `-resumeGame <f>` | `0x007BACE3` | sets `+0xAC4` and the initial file |

plus `-scriptDebug2`, `-scriptDebugLite`, `-fullVersion`, `-preferLocalFiles`, `-Watchdog`,
`-noWatchdog`, `-rif`.

**Sixteen rows is what retail dispatches, not what the engine was built with.** See
[§5](#5-what-else-production-orphaned): 84 more handlers are still in the binary with nothing able
to reach them, each one an 8-byte table row away from working again.

**There is also a second, older parser the table knows nothing about.** `WinMain` walks argv itself
at `0x00402977` with a chain of `stricmp` calls, before any engine object exists, handling `-win`,
`-fullscreen`, `-xpos`, `-ypos` and `-automatch` — writing a windowed flag at `0x00DC3C68` and the
window position at `0x00D8AFE0`/`0x00D8AFE4`. Only `-win` is in both. So `-xpos`/`-ypos` work, are
undocumented, and are invisible to anything reading the table; check both before adding a name.

### The frame cap is an INI field

The `GameData` field-parse table at `0x00BFF580` (457 fields, name → `GlobalData` offset) maps
`UseFPSLimit` to `+0x26` and `FramesPerSecondLimit` to `+0x28`. Both are live: `0x0063A01B` copies
`+0x26` into the loop's own global, and `0x0062C6FF` already flips the pair at runtime. So
`GameData UseFPSLimit = No` uncaps the loop with no patch at all.

**Do not raise the logic rate at `0x00D9F60C` (30) to go faster.** Every duration in the game is
counted in logic frames; changing the rate changes the simulation and invalidates any replay
recorded against it. Uncapping the loop removes only the wall-clock throttle, which is the property
a test rig actually wants — the simulation stays bit-identical.

### `-file` already starts a game with no menu

`-file` writes its argument to `GlobalData+0xABC`. At the tail of `GameEngine::init`, `0x0063C9C1`
copies it to `+0xAC0` — the staged map name `startNewGame` consumes, as
[`skirmish-replay.md`](skirmish-replay.md) notes — and then:

```asm
0063C9DD  cmp  byte [GlobalData+0xAC5], 0
0063C9E3  jne  0063CBDB               ; skip the auto-start
0063CA19  push 0x1E                   ; MSG_NEW_GAME
0063CA1B  call [eax+0x48]             ; TheMessageStream->appendMessage
0063CA31  ...                         ; build the GameInfo at 0x00DE8930, seed from time()
0063CB7B  push 2                      ; game mode 2 = skirmish
0063CB7F  call 007111E5               ; GameMessage::appendIntegerArgument
0063CBB0  ...                         ; else-branch: ".rep" -> TheRecorder (0x00DE7CD8) playback
```

`+0xAC5` is zeroed by `GlobalData`'s constructor at `0x0064301B` and has **exactly one writer** —
the orphan handler at `0x007BAD3F`, which nothing can reach. It is therefore always zero, the
branch is always taken, and no front end appears: `Shell`'s front-end selector at `0x0075E43C`
returns early the moment it sees a non-empty initial file.

Game mode 2 matches the skirmish mode [`skirmish-replay.md`](skirmish-replay.md) enumerates, so a
`-file` start is recordable by that patch like any other skirmish.

### EA's own headless mode, still wired up

Six sites call `getenv("_EA_RTS_HEADLESS")`:

| site | in | effect when the variable is set |
|---|---|---|
| `0x0063CBE7` | `GameEngine::init` | clears `ShellMapOn` (`+0xAF0`), `PlayIntro` (`+0xAF2`) and `+0xD36` |
| `0x0075E48D` | `Shell` front end | pushes `Menus/LanLobbyMenu.wnd` instead of `MainMenu.apt` |
| `0x0084C79F` | LAN transport | a timeout goes from 5000 ms to 50000 ms |
| `0x0084C862` | LAN transport | `atoi(value) + 8086` is the port, scanned up to 8093 |
| `0x0084D698` | LAN transport | the same port arithmetic, against `127.0.0.1` |
| `0x00649CAC` | LAN join | silent failure instead of a `LAN:JoinFailed` dialog |

Two corroborating details. The control name `MapSelectMenu.wnd:HeadlessCount` at `0x00C7C16A` — the
map-select screen had a field for how many headless clients to wait for. And `_EA_RTS_FILENAME`
(`0x00439C9F`, via `GetEnvironmentVariableA`) names a file of extra `-dbgcmd:` arguments, so the
harness could pass options without touching the command line.

Read together: N loopback instances on ports 8086+n, each told how many peers to expect, driven
through the legacy `.wnd` lobby. That is a distributed test rig, and it is in the shipped binary.

## 2. What headless can and cannot mean here

`GameClient::init` builds its subsystems through virtual factory slots, which looks like the seam a
null-renderer design would want:

| slot | creates | global |
|---|---|---|
| `+0x94` | `Display` | `0x00DE4418` |
| `+0x98` | `InGameUI` | `0x00DE4830` |
| `+0x9C` | `WindowManager` | `0x00DE495C` |
| `+0xA4` | `DisplayStringManager` | `0x00DE4518` |
| `+0xB0` | `Keyboard` | `0x00DE4334` |
| `+0xB4` | `Mouse` | `0x00DE36E0` |

It is not usable. `TheDisplay` alone has **540 references in `.text`**, overwhelmingly
`getWidth`/`getHeight` for layout arithmetic, and the call sites do not null-check. Stubbing the
factory means authoring a replacement class with a complete vtable in a cave, which is larger than
everything else here combined and fails somewhere new on every path it has not covered.

So headless here means **render-suppressed, not device-free**: the D3D9 device is still created
(`Direct3DCreate9` resolved dynamically from `D3D9.DLL`; `d3dx9_27.dll` and `mss32.dll` are static
imports), every subsystem still exists and answers, and the per-frame `draw` does not run. What
stays: device creation, texture and model loading, the Windows message pump, and the audio DLL in
memory. A CI machine still needs a display device or a software rasteriser.

## 3. The patch

One `Patch` subclass, one cave named `.hless`, allocated with `allocate_section` and found back
with `find_section` per the composition contract on `Patch`.

### a. A command-line surface

The dispatcher takes its table in `ebx` and its length as a pushed constant, at the single call
site:

```asm
007BAA44  push ebx / esi / edi
007BAA47  push [esp+0x14]
007BAA4B  mov  ebx, 0x00C35DA8        ; BB A8 5D C3 00
007BAA50  push [esp+0x14]
007BAA54  push 0x10                   ; 6A 10 — 16 entries
007BAA56  call 007BA7E1
```

Copy the sixteen entries into the cave, append new ones, and make two edits. `push imm8` holds up
to 127 entries, so both edits keep their length and nothing shifts:

```
0x007BAA4B   BB A8 5D C3 00   ->  BB <cave base VA>
0x007BAA54   6A 10            ->  6A <16 + new>
```

Handler ABI, recovered from the dispatcher and confirmed against six stock handlers:
`int __cdecl handler(char **argSlot, int remaining)`, returning arguments consumed (1 for a flag, 2
for one taking a value); the caller pops; only `eax`, `ecx` and `edx` are free.

The four options built, as rows 16..19 of the extended table:

| option | args | what it writes |
|---|---|---|
| `-headless` | — | the cave's interval to 0 (never draw), and `UseFPSLimit` to `No` |
| `-renderEvery <n>` | 1 | the cave's interval to *n* — 0 never, 1 every frame, *n* one in *n* |
| `-maxfps <n>` | 1 | `FramesPerSecondLimit` = *n*, `UseFPSLimit` = `Yes` |
| `-uncapped` | — | `UseFPSLimit` = `No` |

The table is scanned in order and stops at the first match, so a later option wins over an
earlier one: `-headless -maxfps 30` is a headless run that still paces itself.

`-headless` is deliberately **not** a bundle of the stock options. `-noshellmap` and `-noaudio`
do more than write the fields they name — `-noaudio` also marks the run in the engine's own
command-line flag word at `0x00DA62F0`, which is folded into `GlobalData+0xB38` when parsing ends
— and reproducing them here would reproduce them wrongly. A headless run passes them alongside:

```
game.dat -mod <mod> -file maps\<map>.map \
         -headless -noshellmap -noaudio -win -xres 640 -yres 480 -randomSeed <n>
```

**`-instance <n>` is not built,** although §1 makes it look free. `_putenv` is not in the import
table, so setting `_EA_RTS_HEADLESS` from inside the process means `GetProcAddress` against
`msvcr71` — `SetEnvironmentVariableA` will not do, because the CRT's `getenv` reads the CRT's own
copy of the environment, not the process block. That is affordable, but it should wait on
question 1 in [Open](#open): until the `.wnd` menus are known to ship, setting that variable
sends the shell to a screen that may not load. A harness that wants it today can set the variable
itself, which is what EA's did.

This part is worth having on its own, headless or not: it is the general answer to "this engine
needs a new command-line option".

### b. Render suppression

One call site, in `GameClient::update`, immediately after the display's own `update` at
`0x00648838`:

```asm
00648861  8B 0D 18 44 DE 00   mov  ecx, [TheDisplay]
00648867  8B 01               mov  eax, [ecx]
00648869  FF 50 30            call [eax+0x30]        ; Display::draw()
```

Eleven bytes from `0x00648861`, comfortably more than the five a `call rel32` needs. Redirect the
whole sequence into the cave, which tests the headless flag and either returns or re-issues the
original three instructions. No vtable byte is touched, so anything else that draws still can.

The cave's interval starts at **1** — every frame, which is stock behaviour. An applied patch
that is never asked for anything on the command line therefore changes nothing, which is what
makes it safe to bundle into a build that also serves ordinary players.

`-renderEvery n` exists because suppressing *every* frame is the cheapest thing to do and the
least proven: drawing one frame in *n* keeps whatever state the render path incidentally
maintains alive, still removes most of the cost, and is a cheap escape hatch if full suppression
starves something (question 3 in [Open](#open)).

A second draw site at `0x00645CD1` is followed by `Sleep(100)` at `0x00645CDC` — the loading and
inactive path. Leave it: it costs nothing and it is where the engine is already idle.

### c. Window and clock

- **Clock.** No engine byte is patched: `-uncapped` and `-maxfps` write the two fields the engine
  already honours, from handlers in the cave.
- **Window.** `-win -xres 640 -yres 480` is stock and already cheap. Hiding the window outright
  means `SW_HIDE` at `WinMain`'s `ShowWindow` (`0x00402B21`) — one byte, but it risks the D3D9
  present path. Not built: ship the small window, and treat hiding as an experiment.

### d. Steering a game with no screen

Three routes, answering three different questions.

**1 — Don't navigate the UI; skip it.** The recommendation. §1 already reaches a running skirmish
with no menu interaction; what it does not do is let you say *which* skirmish. Everything needed is
built between `0x0063CA31` and `0x0063CB7B`, into the `GameInfo` at `0x00DE8930`, before
`MSG_NEW_GAME`'s arguments are appended. A cave hooked just ahead of `0x0063CB7B` can overwrite the
slots from parsed arguments:

```
game.dat -mod Edain -file maps\fords_of_isen.map \
         -headless -uncapped -instance 0 \
         -slot 0=human -slot 1=ai:hard \
         -side 0=Mordor -side 1=Gondor \
         -team 0=1 -team 1=2 -randomSeed 4242
```

This is the bulk of the effort: the `GameInfo` slot layout has to be mapped and side names resolved
against the loaded tree. Everything else in this document is small beside it.

**2 — Drive the legacy `.wnd` front end.** With `_EA_RTS_HEADLESS` set the shell pushes
`Menus/LanLobbyMenu.wnd`, not APT — and `.wnd` controls are addressable *by name*
(`MapSelectMenu.wnd:ButtonOK`, `:ListboxMap`, `:HeadlessCount`, `:ButtonSinglePlayer` are all
present as literals). A cave can post GUI messages to a named control, which becomes
`-click MapSelectMenu.wnd:ButtonOK`. This is the only route that reaches multi-client LAN tests,
and it is how EA drove it. It carries one hard precondition — see [Open](#open).

**3 — Inject at the message stream.** Already solved: [`live_bridge`](../patches/experimental/live_bridge.py)
hooks `GameLogic::update` and appends orders through the engine's own `appendMessage`, camera
control included. Note the boundary — shell and APT buttons are not message-stream orders, so this
covers the match and never the menus.

### e. Getting the result out, and stopping

Both halves exist as bundled patches. `skirmish-replay` makes a single-player skirmish record at
all, under a timestamped name; `replay-outcome` appends a per-player verdict chunk (outcome and
defeat frame) at teardown. Compose the three and a headless run leaves a replay `sage_replay`
parses into a result — no new output format and no new parser.

What is missing is termination: a run that finishes and sits at the score screen holds its CI slot
forever. `-exitOnEnd` and `-exitAfter <frames>` need a hook, and the obvious sites are taken —
`replay-outcome` owns `0x0077F98B` and `live-bridge` owns `GameLogic::update`'s entry. Pick a third
(the score-screen entry, or `GameLogic::clearGameData` itself) so the three stay order-independent,
and say so in the docstring.

## 4. Composition

Every site here is untouched by anything bundled: `0x007BAA4B` and `0x007BAA54` in the command-line
caller, `0x00648861` in `GameClient::update`, and a hook near `0x0063CB7B` in `GameEngine::init`.
The cave is allocated past every existing section and `verify` finds it by name, so the patch
composes in any order — the one thing to watch is §3e's exit hook.

[`multi-instance`](multi-instance.md) is a hard dependency for parallel runs, not an optional
extra: three mutex gates refuse a second copy, and one of them shuts the *first* instance down. It
is also what makes the `_EA_RTS_HEADLESS` port offset meaningful.

All 24 orderings of `headless` + `multi-instance` + `skirmish-replay` + `replay-outcome` apply
and verify against a real `game.dat`.

`verify` checks, all as structural byte reads so verification stays disassembler-free:

- a `.hless` section exists, located by name;
- its first 16 table rows match the stock table at `0x00C35DA8` byte for byte;
- `0x007BAA4B` points at the cave's table and `0x007BAA54` matches its row count;
- the draw site carries a `call` to the cave's hook, padded with `nop` to eleven bytes;
- each appended row names its option and dispatches into the cave's code, not past it.

`apply` refuses before allocating anything unless four of the stock table's names are where they
should be and the dispatcher at `0x007BA7E1` is still a function entry — so a build whose layout
moved fails with the image untouched, rather than carrying an orphaned cave.

A run, end to end:

```sh
# once
for p in multi-instance headless skirmish-replay replay-outcome; do
    sage-patch apply "$p" --in game.dat --out game.dat
done

# per test, N of these in parallel (multi-instance is what allows the N)
game.dat -mod Edain -file maps\fords_of_isen.map \
         -headless -noshellmap -noaudio -win -xres 640 -yres 480 \
         -randomSeed $seed

# then, offline
sage-replay parse "Replays/2026-08-11 14-02-11 fords_of_isen.BfME2Replay"
```

§3d would add the skirmish setup to that invocation (`-side`, `-slot`, `-team`) and §3e the
termination (`-exitOnEnd`); until they exist, the run ends when the harness kills it and the map
is whatever `-file` names, with the auto-start path's own defaults for everything else.

Rough effort on what is left: §3d medium-to-large, §3e small.

## 5. What else production orphaned

The command-line region `0x007B9EBE`–`0x007BAE00` holds **105 handler-shaped routines**. The table
names sixteen. Six more are reached some other way. The remaining **84 have no table row, no call
site and no pointer anywhere in the image** — 2339 bytes of working code nothing can invoke. They
follow the same ABI as the live ones, so [§3a](#a-a-command-line-surface)'s table makes each one an 8-byte row away from
working again.

Grouped by what they write, they are a developer and QA toolkit removed wholesale:

| group | n | what the handlers do |
|---|---|---|
| desync verification | 17 | The CRC suite. Thirteen set bits in a flag word at `0x00DA62F0`–`0x00DA62F2` plus a byte each at `0x00DE87BB`+; four take a **frame number** (`0x00DA62E4`, `0x00DA62E8`, `0x00DA62EC`, `0x00DA1880`) — start checksumming at frame N. Two refuse each other and share the string `"Do not specify both -deepCRC and -liteCRC in your commandline arguments."` |
| debug log channels | 4 | Each issues a text command to the debug subsystem at `0x00DC62C0`: `debug.fulldump +`, `debug.add L + NETWORK_CRCDUMP`, `debug.add L + GAMEREPORT`, `debug.add L + PACKET_OVERFLOW`. **That subsystem is alive** — constructed at `0x00437F95`, 393 references, grammar intact (`debug.exit`, `debug.io stringbuf add`, `debug.add l ± SceneAnalyst`). Only the switches are gone |
| renderer | ~8 | Named from the `GameData` field table by the offsets they write: `UseShadowVolumes`, `UseShadowDecals`, `UseShadowMapping`, `Windowed` on *and* off, `SkipMapUnroll`, `DumpAssetUsage` |
| determinism & test | ~10 | `FixedSeed` (`+0x9E8`, takes a value), `PlayStats` (`+0xC30`, takes a value), `ShellMapName` override, `DisableCameraMovements`, `ShowTooltips`, `UseHelpTextSystem`, `PlanningModeEnabled` on and off, and one pointing the mod path at `Mods\open_beta` |
| living world | 3 | `LiveCampaignMode`, `HideLivingWorldRegions`, `LivingWorldTurbo` |
| scene loaders | 2 | Take a filename, store it at `0x00DE414C`/`0x00DE4150`, set `0x00DE4148`, and force `Windowed = 1` with `ShellMapOn = 0` |
| frame rate | 1 | `0x007BA404` sets `FramesPerSecondLimit` to **30000** — §3c's uncapping switch already existed |

### The session report writer

One of those log channels is `GAMEREPORT`, and the code behind it is **live** — a function at
`0x0062FFC8`, called from two places, that formats:

```
GAME REPORT:
  BuildType: RELEASE
  Session Game #%d
    Map Name: %s
    GameMode: isSkirmish:%d, isMultiplayer:%d, isSandBox:%d
    Player List:
      Slot %d: %s(%s), %s %s, Team:%d, StartPos:%d
  Important CommandLine Arguments:
    Network:   -binaryDeepCRC -liteCRC -deepCRC -verifyClientCRC -xLWCRC -xAICRC
               -xPlayerCRC -xTerrainLogicCRC -xTaintCRC -xShroudCRC -xCollisionCRC
               -xPartitionCRC -xObjectCRC
    GamePlay:  -startingMoney %d -fastGamePlay
    System:    -noMusic -noAudio -bigmemorysentinals -poolbigblocks zeroFillMemory:ON|OFF
```

A machine-readable session header: build, map, mode, every slot with its faction, team and start
position, and which options were in force. Exactly what an automated run wants beside its replay —
already written, already called, gated behind a channel whose only switch was one of the 84.

**Those option names are report fragments, not table entries.** Each begins with a *space*
(`" -noAudio"`, `" -deepCRC"`), and each is referenced from this writer. A sweep that searches for
the address of the `-` reports them unreferenced and concludes the parse table was trimmed; the
orphans are the handlers, not the strings. Of the option-shaped strings in the image, only
`-nullsystem` is referenced by nothing at all.

### Two more facilities that survived intact

- **An argument file.** `_EA_RTS_FILENAME` (`0x00439C9F`, via `GetEnvironmentVariableA`) names a
  `.dbgcmd` file from which `-dbgcmd:` arguments are read — options without a command line, which
  is how a harness drives a process it did not launch. Live.
- **`-startPaused`** (`0x0042F977`). Live, and not in the table: the engine can come up paused.

### What this is worth

In rough order of value to a test rig: `GAMEREPORT` (a structured session header, free),
`FixedSeed` (reproducibility with no INI edit), the CRC family (the only instrument the engine has
for proving two runs stayed in step), `DumpAssetUsage` (what a run actually loaded). None needs new
assembly — only a row.

The caveat is that none of it has been exercised since the switches were cut. A handler writing a
flag no surviving code reads will apply silently and do nothing; a log channel whose sink was
compiled out will accept the command and drop it. Re-exposing one is cheap; confirming it still
does something is the work, and it is per switch.

## Open

The first two block §3d, which is why it is not built. The next two are how what *is* built
gets proven. None needs more than an afternoon.

1. **Do the `.wnd` menus still ship?** *(blocking)* The code and every control name for
   `LanLobbyMenu.wnd` and `MapSelectMenu.wnd` are in the binary, but RotWK's front end is APT and
   those assets may have been dropped from the `.big` archives. If they are gone, route 2 of §3d
   dies and `_EA_RTS_HEADLESS` becomes actively harmful — it sends the shell to a screen that
   cannot load. This decides whether `-headless` should set the variable at all.

2. **What does the auto-start `GameInfo` default to?** *(blocking)* The path builds a playable
   skirmish from defaults nobody has inspected: how many slots, which sides, which AI. Run
   `-file <map>` against an unpatched binary and look. If the defaults are sane, §3d shrinks
   dramatically.

3. **Does suppressing `draw` starve anything?** *(verifies §3b)* `Display::draw` may also drive
   culling and view state that non-render code reads. Test at `-renderEvery 1` (which is the
   patch applied but inert), then 10, then 0, and diff a rendered against a suppressed run of the
   same seed — a `skirmish-replay` recording is the instrument.

4. **Is an uncapped loop still deterministic?** *(verifies §3c)* It should be, since the
   simulation is frame-counted rather than clock-counted, but this assumption carries the whole
   testing case. Same seed, same map, capped and uncapped, diff the replays.

5. **Provenance.** The image these addresses were read from is *not* stock: it carries a `.cahfac`
   section — this package's own `cah-factions` patch, applied with a non-default side list, so
   `detect()` returns nothing and `verify()` reports a wrapper mismatch — alongside the retail
   SafeDisc sections. Every site cited is untouched engine code and `sage-patch apply headless`
   succeeds on it, but re-check the byte assertions against a clean `2.01.2614.37001` image
   before shipping a patched build.

## Method

Static only. The PE section table and import directory were parsed by hand; strings were recovered
by regex over the image and cross-referenced by scanning for their little-endian addresses at every
byte offset rather than every fourth — which is what surfaces `push imm32` operands, and with them
the dead options and the `getenv` sites. Instruction decoding is capstone anchored on known call
sites, not a linear sweep: a linear sweep of this `.text` desynchronises on inlined data, exactly as
[`engine-globals.md`](engine-globals.md) found.
