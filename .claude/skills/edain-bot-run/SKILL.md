---
name: edain-bot-run
description: >-
  Run the Edain bot against a live RotWK match end to end - close the game, set the skirmish
  lobby to a known configuration, relaunch, drive the menus into a match with game_macro, attach
  the bot, and watch the run. Use whenever asked to run, restart, drive, or babysit the bot
  (`sage_mods.edain.bot`) against the real game, or when a live match is needed for `sage_live`
  work and nobody wants to click through the lobby by hand.
---

# Running the Edain bot against a live match

Four steps, in this order. **The order is a constraint, not a preference**: the lobby file can
only be written with the game closed, and the menu macro only works from a cold main menu.

```
1. close the game        (the lobby file is owned by the running game)
2. set the lobby         (faction, seed - what makes two runs comparable)
3. launch + drive menus  (game_macro start --launch, one command)
4. attach the bot        (last - attach needs the process to already exist)
```

Steps 1-3 are only needed when the lobby has to change. If a run just ended and the next one
wants the *same* faction and seed, `restart-match.json` replaces all three - see
[The recordings](#the-recordings).

**The bot cannot start before the game, but it can start before the match - and should.**
`attach` looks for a running `game.dat` and exits immediately with `no running game.dat - launch
the game and start a match, or pass an explicit pid` when there is none; it does not wait for one
to appear. But the *menu* is a running game, so the process exists from the moment the shortcut
launches, and `--wait` covers waiting for a match from there.

That matters because the bot spends its first ~36 seconds parsing the ini tree, and it now does
that **on a background thread while it waits for the match**. Started at the menu, it is loaded
and ready at frame 0; started after the match has begun, it parses into the opening exactly as it
used to. So step 4 can be run *concurrently with* step 3 rather than after it - launch, then fire
the bot at the menu, then let the macro drive.

(This was worse until measured: `Resolver.from_root` and `Statics.from_root` each loaded the tree
independently, 40.6s + 25.4s = 66s of walking the same eleven thousand definitions twice. One
`load_game` now feeds both, at 35.8s.)

## The whole thing

Run from the repo root, in an **elevated** shell - reading the game's memory needs
`PROCESS_VM_READ`, and an unelevated process gets `ERROR_ACCESS_DENIED` while still being
allowed to see the process exists.

```powershell
# 1. close the game, and wait for it to actually go
Stop-Process -Name 'game.dat' -Force -ErrorAction SilentlyContinue
Stop-Process -Name 'lotrbfme2ep1' -Force -ErrorAction SilentlyContinue

# 2. a known lobby - refuses while the game runs, hence step 1 first
python tools/skirmish_config.py set --faction 3 --seed 1234

# 3. launch and click through to a running match
python tools/game_macro.py start tools/recordings/cold-start-1080x720.json `
    --launch "C:\Users\Clement\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\ROTWK Debug"

# 4. the bot - only once step 3 reports "match is running"
New-Item -ItemType Directory -Force sage_mods/edain/bot/runs | Out-Null
python -u -m sage_mods.edain.bot --game "C:\Program Files (x86)\Games\bfme\rotwk" `
    --fog --no-camera --cycles 1400 --wait 3600 2>&1 | tee sage_mods/edain/bot/runs/run.log
```

`sage_mods/edain/bot/runs/` is gitignored, and it is where every run transcript belongs - the
kept ones are renamed `run-<n>-<what-happened>.log` once the match is over.

Step 3 prints `match is running` when the menus are through; that is the signal to start step 4.
The bot then spends about a minute loading the ini tree before its first order, so the opening it
plays begins a little way into the match - unavoidable, since it cannot attach any earlier.

## Why each step is there

**Close the game first.** `Skirmish.ini` is read when the lobby opens and rewritten when a match
starts, so an edit made while `game.dat` is running is ignored or overwritten;
`skirmish_config.py save` refuses outright rather than writing something that will be lost.

**Set the lobby** so runs are comparable. `--faction 3` is `FactionMen`, confirmed against a
running game (that match's local player reported Side `Men`). `--seed` is what makes two runs the
same match. Only factions with an entry in `PLANS` can be played - the bot exits with the known
list if you pick one it has no plan for, or pass `--faction` to the *bot* to borrow another's.

**Relaunch through the "ROTWK Debug" shortcut**, which `--launch` does for you. It starts the
game **windowed**; a fullscreen launch takes over the display and makes it painful to read tool
output and drive the game side by side.

**Drive from a cold main menu.** `cold-start-1080x720.json` is written for the main menu. From a
post-match screen its clicks land on buttons that sit at the same coordinates and mean different
things, and it fails with `no match started - a step probably missed its button` after moving
your mouse for nothing. Starting from a fresh launch is what makes it deterministic.

## The recordings

`tools/recordings/` holds five files, and only two of them are for getting into a match the
normal way. They are **not interchangeable**: each starts from one specific screen, and a
recording replayed from the wrong screen clicks whatever happens to sit at those coordinates.
All five are client-space and **1080x720**; a different client size is refused outright.

| file | starts from | replay with |
|---|---|---|
| `cold-start-1080x720.json` | a cold main menu | `start ... --launch "..."` |
| `restart-match.json` | inside a live match | `play ... --restart` |
| `post-match.json` | the post-match lobby | `play ... --now` |
| `load-save.json` | inside a live match | `play ... --now` |
| `skirmish-1080x720.json` | *superseded - do not use* | - |

**`cold-start-1080x720.json`** is the one step 3 uses. Three named steps - solo play, skirmish,
play - written from screenshots rather than recorded, which is why a failure names the button it
could not reach instead of silently clicking past it.

**`restart-match.json`** is the cheap path and the one to reach for when a run has ended and
another is wanted on the *same* lobby. It drives the in-match pause menu's restart button, so it
skips steps 1-3 entirely - no kill, no relaunch, no menu walk:

```powershell
python tools/game_macro.py play tools/recordings/restart-match.json --restart
```

`--restart` is not optional decoration. Plain `play` verifies by asking whether a match is
running, which is *already true* when these clicks go in, so it would report success without a
restart having happened; `--restart` verifies the match **cycled** - `in_match` dropping and
rising again. The trade is that a restart replays the lobby as it stands: it cannot change
faction or seed, so changing either still means the full close-set-relaunch sequence.

**`post-match.json`** walks the post-match lobby back into a running skirmish - same map, full
army, all plots neutral. Three clicks on the same button at (966,674), spaced for the screens
between. Use it when the game is *already sitting* in that lobby:

```powershell
python tools/game_macro.py play tools/recordings/post-match.json --now
```

`--now` skips the default wait-for-a-running-match-to-end. Without it the replay blocks until
the current match finishes, which is the right default for an unattended loop and the wrong one
when you are standing there.

**`load-save.json`** goes from the in-match pause menu into the load-game dialog and loads a
save. It is not part of any bot run - it exists for `sage_live` work that needs a specific board
back rather than a fresh one. Being a recorded click walk it depends on the save list looking
the way it did when recorded, so treat a changed save list as a reason to re-record.

**`skirmish-1080x720.json`** is the original recorded main-menu walk from 2026-07-29, superseded
by `cold-start-1080x720.json`. Leave it alone: its first click is (982,679), the coordinate that
is empty space in the post-match lobby and **QUIT** on the main menu - the one that closed the
game during an early blind replay - and it contains a click at (-70,-79), outside the client
area entirely.

## Bot flags that matter

| flag | why |
|---|---|
| `--fog` | the seat only sees what it can see; opponents must be scouted |
| `--no-camera` | leaves the view alone - the camera stage fights the engine's clamp and reads as the view zooming in and snapping back |
| `--cycles N` | see the pacing note below; 1400 for a run meant to resolve |
| `--wait N` | seconds to wait at the menu. Without it `wait_for_match` defaults to **120s** and the bot exits with a `TimeoutError` traceback |
| `--record` | film the run - presses **F8**, OBS's start/stop recording hotkey, once at each end |
| `--dry-run` | decide and print, send nothing |

`--record` needs OBS **already running** when the bot starts; it says so and films nothing if not.
The press is real system-wide input, so it is not private - anything else bound to F8 hears it,
and running the bot's recorder outside a filmed run will stop a recording somebody else started.
Nothing confirms a recording began: a hotkey reports nothing back, which is the price of not
needing OBS's WebSocket server (shipped disabled, behind a generated password).

## Cycles buy far less match than they look

The engine advances at roughly **4-6 logic frames per second against its nominal 30** under the
bridge, and degrades as the match grows. So:

- 900 cycles at the 2s default ≈ **45 minutes of wall time** and only **~8 minutes of game time**
- `MenOfTheWestArmy` phases are 300s rush / 400s midgame, and midgame is a **duration**, so phase
  3 starts at 700 match-seconds - about **cycle 1340**
- a fight whose line repeats for 50 cycles is not a stalemate; check the frame delta first

Budget `--cycles 1400`+ for a run intended to actually finish.

## Watching a run

Filter the log rather than reading it - 1400 cycles is ~2800 lines:

```bash
tail -f sage_mods/edain/bot/runs/run.log | grep -E --line-buffered -A 1 \
  "the match ended|the game is gone|defeat:|victory:|stopped after|Traceback|NOT QUEUED|could not be sent|^\[ *[0-9]*00\] "
```

**The status line carries two clocks and they are far apart.** The trailing `667s` is
**wall-clock** time since the bot attached; the match clock is `frame`, counted from the bot's
own first frame at 30fps. At 5 logic fps they diverge by about 6x, so a line reading `phase 1`
next to `667s` is not a stuck phase - it is 134 match-seconds, still inside the 300s rush.
Judge phase, and anything else in match time, from the frame delta.

**Check these two things at cycle 1**, because both have silently wasted whole matches:

- `flags` must be non-zero. Zero means the plot census failed and `stage_expand` has nothing to
  claim, so the starting troops never leave home.
- `map` must be low, not `100%`. `map_control` returns 1.0 when it finds no claimable flag at
  all, so a blind bot reports total map control.

Then watch for `NOT QUEUED` (recruit refused) and `could not be sent` (defend refused). The
end-of-run ledger prints what every order type actually achieved - that is the honest scorecard,
because game logic discards a malformed or unaffordable order *after* the stream has taken it,
with no error and no diagnostic.

## Gotchas

- The process is named **`game.dat`**, not `game` - `Get-Process -Name game` finds nothing while
  the game is plainly running.
- The recording refuses a different client **size** rather than scaling it. Menu hit boxes do not
  move linearly with resolution, so this is a safe failure, not a bug to work around.
- Driving the macro takes over the mouse and keyboard for a few seconds. Say so before doing it.
- Under `--fog` a win still prints `victory:` - the match-over test reads the unfogged snapshot
  deliberately, because whether the match is over is not a tactical read.
