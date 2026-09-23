# Training an ML agent to play Edain

An assessment of the path from "a folder of replays" to "a model that plays a live game of Edain",
and where pySAGE stands on it. Not an attempt.

**The verdict.** The hard part is the interface, not the model. A replay is an input stream, so
the corpus holds actions with no observations. That splits the work:

- **Macro** (build orders, timings, spellbook, matchup picks) is trainable from the corpus today.
  `sage_replay` already reduces a replay to a clocked event timeline with ground-truth winners.
- **Micro** (fights, positioning) cannot be learned from replays: the stream never says what the
  moved objects were or what state they were in. It needs live state from the engine.

The recommended shape is a **hybrid bot**: a learned macro policy driving hand-written micro,
acting in the live engine. End-to-end reinforcement learning comes last, if at all.

## The three interfaces, and their status

| interface | what it needs | status |
|---|---|---|
| **act** | issue orders as a player would | `sage_live` orders through the experimental `live-bridge` patch, which injects into the engine's own message stream (network-ordered and checksummed). Which orders are verified: "Verified orders" in [live-api.md](live-api.md) |
| **observe** | the board, per frame | `sage_live.MemoryBackend` reads players, objects, production, cooldowns and the shroud grid read-only; `fog=True` and `godsight=False` keep a policy to what a human could see and know |
| **control time** | many games, fast and unattended | `headless` (`-renderEvery`, `-uncapped`), `command-line-skirmish` and `sage_test` for scripted launches, `multi-instance` for parallel copies. Parallel runs are not exercised yet, and nothing steps the engine deterministically |

Two rules still hold for acting: inject at the message-stream level, never by calling logic
directly (that desyncs lockstep), and track selection, since several orders only mean something
against it (`Session` does both).

## What the corpus trains today

All of this runs on `TranslatedReplay` documents and the existing `stats` / `build_orders`
pipeline, with no engine work:

1. **A macro policy**: a sequence model over `(category, label)` events, conditioned on faction,
   enemy faction, map and clock, predicting the next decision.
2. **A value head**: `P(win | faction, matchup, map, state at t)`, trained on sidecar winners. Also a
   balance tool for the mod in its own right.
3. **Timing and matchup structure**, generalizing what `aggregate` already tabulates.

None of them can fight. For data hygiene: dedupe by the document's size and hash identity, keep
`undetermined` games out of outcome labels, and hold out by player, not by game.

## Turning the corpus into observed data

Once observations can be recorded per frame, playing the replay corpus back through the engine
yields (state, action) pairs of real human play - the standard bootstrap for RTS agents, and far
cheaper than self-play. Playback needs the exact recording build (one install per Edain version);
converted replays diverge in playback, because `ObjectId` arguments cannot be remapped.

## Staged plan

| stage | deliverable | status |
|---|---|---|
| 0. Dataset | corpus to translated documents to tokenized sequences | tooling exists |
| 1. Macro model and value head | next-decision model, win predictor, balance report | not started |
| 2. Order injection | live control through the message stream | built (`live-bridge`, `sage_live`) |
| 3. Observation | per-frame state | built for external reads (`MemoryBackend`); no in-process per-frame dump |
| 4. Hybrid bot | learned macro plus scripted micro, against the skirmish AI | needs stage 1 |
| 5. Re-simulation dataset | corpus replayed into (state, action) pairs | needs frame-aligned observation during playback |
| 6. Imitation micro | a learned micro policy on stage 5's data | needs stage 5 |
| 7. Reinforcement learning | headless, parallel self-play | a research project |

## The alternative: a reimplemented engine

An open reimplementation such as [OpenSAGE](https://github.com/OpenSAGE/OpenSAGE) would make
headless, state and clock trivial, but BFME2 support is a moving target and Edain exercises far more
of the engine than vanilla skirmish. Worth it only if an agent is the goal and the timeline is
years.

## Risks

- **Edain renumbers ids every release**: express policies in code names, never raw ids.
- **Multiplayer is out of scope**: a patched client desyncs against unpatched peers, and an agent on
  the ladder is cheating.
- **Ship recipes, never binaries**, as `sage_patch` already does.
- **Lockstep is an asset**: a self-play game is a replay the existing pipeline analyses unchanged.
- **The data's ceiling**: a model trained on ladder replays reproduces that meta, mistakes included.

## Where to start

Stages 0 and 1. They need no reverse engineering, and they answer the question that decides the
rest: how much of Edain's outcome does macro alone decide? If a build-order model and value head
predict winners well, a macro bot on scripted micro will be a real opponent.
