# `ScriptHolder` — a campaign's own script map, and where it stops

Engine build `2.01.2614.37001`, ImageBase `0x400000`. Static analysis of the installed `game.dat`,
plus **three live runs on 2026-09-04** against Edain's `_mod` tree, which is what turned this from
a dead INI keyword into a measured result.

- **What it is.** A `LivingWorldCampaign` field naming a WorldBuilder layout that the campaign
  loads as its strategic session, in place of the default one. The engine builds
  `LivingWorldScripts\<name>\<name>.lws` from it.
- **What is confirmed working.** The keyword parses, the path resolves, and the file loads. A live
  run instantiated the layout's own teams. Nothing had ever exercised this path before.
- **What does not work.** The layout's scripts never run. Not one, on any player, in any run.
- **Where the wall is.** Script *installation*, not evaluation. The runner skips a player whose
  script list is empty and no player in a living-world session has one.
- **Not established.** Which code installs a map's script lists onto players, and what living-world
  mode does differently. That is the next piece of work and it is bounded.

## 1. The field

Row 7 of the `LivingWorldCampaign` field-parse table at `0xC7F898`:

```
[ 7] 'ScriptHolder'   parse=0x0042ee5e  userData=0  offset=0x40
```

`0x0042EE5E` is the `AsciiString` parser, so the value is a bare name and the default is empty.
It sits beside `LocalPlayer` at `+0x3C`. Both `ScriptHolder` and the `LivingWorldScripts` folder
name are **absent from BFME1** — `lotrbfme.exe` contains neither string — so this is a RotWK
addition alongside `SecondsPerReinforcement` and `ForceAdvanceTurnPhase`.

The field has exactly one reader, `0x006B5286`, reached only from
`LivingWorldLogic::startCampaign` (`0x006BE09E`) at `0x006BE110`:

```asm
006b5286  mov  eax, [0x00DE87AC]      ; TheLivingWorldCampaignManager
006b528b  mov  ecx, [eax+0x10]        ; selected campaign index
006b528e  mov  eax, [eax+0x14]        ; campaign pointer vector
006b5293  mov  esi, [eax+ecx*4]       ; the selected campaign
006b5296  add  esi, 0x40              ; &campaign->ScriptHolder
006b529b  call 0x00401E64             ; AsciiString::isEmpty
006b52a2  je   006b52d9               ; not empty -> the .lws path
```

**Not empty.** The name is formatted through `%s\%s\%s.%s` at `0xC143BC` from four strings — the
static `"LivingWorldScripts"`, the field twice, and the static `"lws"` — into
`TheWritableGlobalData+0xC`, the active map name the loader reads. Then
`GameLogic::startNewGame(8, 1, 0)` (`0x0077948E`) and the loading entry `0x006314CD`.

**Empty**, which is every shipped campaign. It reads `TheGameLogic+0x114`, the coarse game-type
field: `1` starts mode 1, `2` starts mode 5 — the two network flavours — and any other value
starts nothing at all, after which `TheGameLogic+0x44` is set to 1. Since `+0x114` is 3 in a
shell-started game (see [`skirmish-replay.md`](../skirmish-replay.md) §1), the empty path starts
no session in single player.

## 2. Mode 8 is the living-world mode

`startNewGame` stores its first argument into `TheGameLogic+0x110` and special-cases only mode 4,
the shell map. Mode 8 is produced nowhere else in the image, which reads as exotic until you find
the predicate at `0x005DC46C`:

```asm
005dc46c  mov  eax, [ecx+0x110]
005dc472  cmp  eax, 8
005dc475  je   -> return 1
005dc477  cmp  eax, 9
005dc47a  jne  -> return 0
005dc47c  cmp  dword [ecx+0x114], 3
005dc483  jne  -> return 1
```

`GameLogic::isLivingWorldMode`. Mode 8 **is** the strategic mode, and 18 sites branch on this
predicate. Several are inside the script engine, including the interval scheduler at `0x0060A18F`,
which swaps `TheGameLogic+0x40` (the frame counter) for `TheLivingWorldLogic+0xFC` (a living-world
counter) when deciding when a script is next due. So the script engine is not switched off here.
Parts of it are explicitly built to run in this mode.

The same swap happens in the script debug logger (`0x00604F7F`), which matters when reading a
`-scriptdebug2` log: **in living-world mode the leading number on each line is not a frame.**

## 3. What the layout is, and how WorldBuilder authors one

`LivingWorldScripts\` is a first-class asset root. It sits in the path-prefix table at `0x00DA2160`
next to `Maps\` and `UserData\Maps\`, and WorldBuilder has the matching category system —
`filetools.cpp`, `writeCurrentMapFileCategory`, `getDirectoryName` — with parallel tables:

| directory | extension |
|---|---|
| `Maps\`, `UserData\Maps\` | `.map` |
| `Bases\` | `.bse` |
| `Libraries\`, `LivingWorldLibraries\` | |
| `LivingWorldScripts\` | `.lws` |

Its open and save dialogs offer these as **User Maps / Bases / Libraries / Living World Scripts /
Living World Libraries**, so saving through the Living World Scripts category writes the doubled-name
path itself. Do not rename a `.map` by hand.

There is also a world property, `isLivingWorldScriptHolder`, with a WorldBuilder checkbox reading
*"Map is a script holder for the Living World (a.k.a. Strategy Map )"*. It lives in the
new-height-map dialog rather than **Edit → Edit Map Settings**, so it is a creation-time and
resize-time option. Two Edain library layouts carry it, both false. **No reader was found**, and
that is not evidence of absence: the static key objects in its table have no references the
scanner can see, and neither do keys that are certainly used, such as `InitialCameraPosition`.

## 4. What three live runs measured

Launched as `lotrbfme2ep1.exe -mod <_mod> -win -scriptdebug2`, with a `ScriptHolder = TestHolder`
on `WOTRScenarioAngmar` and a hand-built layout carrying one always-true script whose action is
`SHOW_MILITARY_CAPTION`.

**Run 1 — crash.** *"Uncaught Exception in `GameEngine::update`"*, seven addresses. The layout at
that point had one side, the neutral player, and no start positions. The crash stopped once the
layout gained a full side list and three `Player_N_Start` waypoints; the cause was never isolated,
so do not read this as diagnosed.

That dialog is worth a warning of its own. **Every `game.dat` frame in it is inside the crash
reporter.** `0x00639FD1` pushes `0xBFE6A0`, the message string itself, four instructions before the
address the box reported as frame 2. The walker captured its own frames and then jumped to the
thread entry, so nothing localises the fault, and the symbol names come from the 2003 `dbghelp` in
the game folder resolving against a near-exportless binary. This is a caught C++ exception, so the
unhandled-exception filter never runs and **no `.dmp` is written** — the `crash-dump` patch hooks
the filter and does not help here.

**Runs 2 and 3 — the layout loads, the scripts do not run.** The `-scriptdebug2` log ends with a
third block, after the two shell-map blocks, which is the `.lws` session starting:

```
0 PlyrCivilian/teamPlyrCivilian - creating team instance.
0 PlyrCreeps/teamPlyrCreeps - creating team instance.
0 /team - creating team instance.
0 ReplayObserver/teamReplayObserver - creating team instance.
```

Two things follow. The layout loaded — those are its teams. And **only 3 of its 16 sides were
instantiated**, which is the side-list prune that [`battle-sides.md`](battle-sides.md) has open.

Run 3 put copies of the script on the neutral player, on `PlyrCivilian` and on `Player_1`..`4`.
No script ran in either run.

The log is trustworthy on this point. The team-instance line (`0x007A6E52`) and the run-script line
(`0x00604F1C`) go through the **same** debug gate on `[0x00DE87B8]`, and the team lines came
through, so logging was live throughout.

## 5. Where it stops

The script runner iterates players. Per player it calls `0x007A00B0`, which walks the list at
`player+0x334` and returns the count:

```asm
00609a74  mov  ecx, [ebp-0x14]        ; the player
00609a79  je   00609b7e               ; null -> skip
00609a7f  call 007a00b0               ; count of that player's scripts
00609a86  jle  00609b7e               ; zero -> skip, silently
00609a8f  mov  eax, [eax+0x334]       ; else walk the list
```

Only past that gate does it evaluate conditions (`0x0060930F`) and log one of
`"Run script - "` (`0xBF9C60`) or `"Run script false - "` (`0xBF9C4C`) at `0x00609AE7`. **Neither
line ever appeared**, so execution never reached the evaluator: it is the `jle` that fires. No
player in a living-world session has a script list at all.

So the failure is not ownership, not the conditions, not the caption action, and not the
script-holder flag. The layout's script lists are parsed and then never installed onto a player.

`player+0x334` is zeroed in the Player constructor at `0x007A663B`. The per-script accessors are
`0x0079FA49`, `0x0079FA5C` and `0x0079FA7F`. The **bulk installer was not found**, and that is
exactly what the next pass needs: what attaches a map's `PlayerScriptsList` to players, and what
mode 8 does differently. The chunk itself is registered at `0x007B3F65`.

## 6. Reproducing it

Uncommitted in the Edain tree, on the `engine-patching` branch:

- `_mod/data/ini/campaigns/scenarios/wotrscenarioangmar.inc` — `ScriptHolder = TestHolder`
- `_mod/LivingWorldScripts/TestHolder/TestHolder.lws` — 37×37, full side list, three start
  waypoints, `isLivingWorldScriptHolder = True`, six copies of an always-true script showing
  `SCRIPT:01intro_text_01`

`sage_ini` types the field as of this pass, alongside `ForceAdvanceTurnPhase`, which was also
missing from the schema.

## Addresses

| what | address |
|---|---|
| `LivingWorldCampaign` field table | `0x00C7F898`, `ScriptHolder` row 7, offset `0x40` |
| the only reader | `0x006B5286` |
| `LivingWorldLogic::startCampaign` | `0x006BE09E`, calls it at `0x006BE110` |
| `GameLogic::startNewGame` | `0x0077948E`, mode into `+0x110` |
| `GameLogic::isLivingWorldMode` | `0x005DC46C` |
| the `%s\%s\%s.%s` path format | `0x00C143BC` |
| `LivingWorldScripts\` prefix | `0x00DA2168`, beside `Maps\` at `0x00DA2160` |
| script runner's per-player gate | `0x00609A7F` → `0x007A00B0` |
| condition evaluator | `0x0060930F` |
| script debug logger / its gate | `0x00604F1C` / `[0x00DE87B8]` |
| `Player` script list | `+0x334`, zeroed at `0x007A663B` |
| the crash box's own frame | `0x00639FD1` pushes `0xBFE6A0` |
