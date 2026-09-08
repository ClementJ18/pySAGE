# Training an ML agent to play Edain — what it would take

An assessment, not an attempt. What follows costs out the whole path from "a folder of replays"
to "a model that plays a live game of Edain", using what pySAGE already has as the inventory.

**Verdict up front.** The hard part is not the model. It is that BFME2/RotWK ships no agent
interface of any kind: no headless mode, no state API, no scriptable clock. A replay is an
*input stream*, so the corpus - however large - contains actions with no observations attached.
That splits the work cleanly in two:

- **Macro (build orders, timings, spellbook, matchup picks) is trainable today**, from the
  corpus, with zero reverse-engineering. `sage_replay` already reduces a replay to a clocked
  event timeline with ground-truth winners; that is a supervised dataset.
- **Micro (army control, fights, positioning) is not learnable from replays at all**, because
  the stream never says what the moved objects *were* or what state they were in. It needs
  live state out of the engine, which is a reverse-engineering project.

The recommended shape is therefore a **hybrid bot**: a learned macro policy over the corpus,
driving a hand-written micro layer, injected into the live engine through the message stream.
Full end-to-end RL is a separate, much larger project, and section 7 argues it should not be
attempted first.

## 1. What an agent needs from a game

Three interfaces, and they are independent problems:

| interface | question | BFME2 status |
|---|---|---|
| **act** | how does the policy issue a command? | no API; the order enum is documented ([order_space_map.md](../sage_replay/order_space_map.md)) |
| **observe** | how does the policy see the board? | no API; partially recoverable from memory / saves |
| **control time** | how do you run 10⁶ games? | no headless mode, no uncapped clock, no scripted reset |

Games with published RTS agents had all three handed to them - StarCraft II ships an official
headless Linux binary with a full-state protobuf API, and AlphaStar still needed the equivalent
of centuries of game time per agent. Edain starts from zero on all three. Any plan that ignores
this ordering (interface first, learning second) stalls immediately.

## 2. Inventory - what this repo already contributes

More than it looks like. In rough order of value to an agent:

| asset | what it buys the agent |
|---|---|
| [`order_space_map.md`](../sage_replay/order_space_map.md) | **the action space, already specified.** ~76 order types, with the id space and resolution rule for every content-bearing one (recruit, build, unpack, upgrade, science, four cast shapes, wall build, stance, rally, control groups) |
| [`serialize.py`](../sage_replay/serialize.py) | a **byte-exact order-stream writer**, gated by `serialize(parse(x)) == x` over the fixture corpus - the agent's output encoder already exists and is proven |
| [`retarget.py`](../sage_replay/retarget.py) | name → id resolution **against any target build**, including the dynamic revive-menu slots. A policy over code names stays valid across Edain patches |
| [`translated.py`](../sage_replay/translated.py) / [`cache.py`](../sage_replay/cache.py) | a version-independent corpus format. Parse once against the recording build, train against the documents forever |
| [`stats.py`](../sage_replay/stats.py) / [`build_orders.py`](../sage_replay/build_orders.py) | the timeline is already reduced to clocked `StatEvent(seconds, category, label)` and folded into per-faction opening trees with win/loss splits - this is the training set, pre-built |
| [`sidecar.py`](../sage_replay/sidecar.py) | **ground-truth labels.** Ladder replays carry a sidecar naming the winning team; strict structural matching means a label is trusted or refused, never guessed |
| `sage_ini` + the mod overlay ([`sage_edain`](https://github.com/ClementJ18/pySAGE-edain)) | every unit's cost, health, armor, weapon, build time, faction tree. Unit features are *given*, not learned |
| `sage_map` | terrain, plot placements, start positions - the static half of a spatial observation |
| [`runtime-re-workflow.md`](../sage_patch/docs/runtime-re-workflow.md) | verified live struct offsets: `PlayerList+0x10` → local player, `Player+0x3DC` stats block, object `+0x04` → `ThingTemplate`, template `+0x64` name / `+0x6C` Side / `+0x70` CommandSet. The seed of a memory-read observation API |
| `sage_patch` | proof that engine intervention works and is repeatable: PE cave allocation, verified byte patches, headless Ghidra scripts, a minidump parser, and a build that runs in-game with no anti-tamper failure on 2.01.2614 |
| [`sage_save`](../sage_save/README.md) | a decoded **serialized snapshot** of the very structures an observation needs (section 5 - this is worth more than it first appears) |

## 3. The blocking fact: replays are inputs, not state

From the `sage_replay` README, and it is the single most important sentence for this project:

> A replay is a header … followed by the recorded order stream. Replays are **inputs, not
> state**: reconstructing what *happened* requires re-simulating the game.

Three consequences, all load-bearing:

1. **No observations.** For imitation learning you need (state, action) pairs. The corpus gives
   you actions and a clock, and nothing else. You can train "what does a good player build at
   4:30 as Mordor vs Gondor on Fords of Isen" - you cannot train "what does a good player do
   when six Uruks are flanking their farm", because the flank is not in the file.
2. **`ObjectId` arguments are runtime handles.** Section B of the order map and OPEN 8: mapping
   a runtime `ObjectId` back to a template is unsolved. So `0x42F` move orders carry positions
   but not *what moved*; `0x412` casts carry a target id but not *what was targeted*; `0x3E9`
   selections name handles, not units. Micro is opaque even at the action level.
3. **Outcomes are inferred, not stored.** [`winner.py`](../sage_replay/winner.py) applies a
   concession heuristic and answers `decided` / `recorder_left` / `undetermined`. Ladder
   sidecars fix this for the corpus that has them; elimination endings without a sidecar stay
   unlabelled. Budget for a labelled subset smaller than the raw download count.

## 4. Acting - inject into the message stream

Three ways for a policy to issue a command, in increasing order of correctness:

**(a) Synthetic mouse/keyboard.** Drive the UI like a human. Needs no engine changes, and the
order map shows a surprising amount of play is hotkey-driven (`0x3EE`-`0x401` are Ctrl+digit
control groups and digit recalls). But every spatial command needs camera control plus a
screen→world inverse, and the agent spends most of its actions scrolling. Brittle, slow,
resolution-coupled. Fine for a demo, wrong as a foundation.

**(b) Inject `GameMessage`s - the right answer.** Section E of the order map already did the
groundwork: BFME2's order ids descend from Generals' `GameMessage::Type` in `MessageStream.h`,
and `GameMessage::getCommandTypeAsAsciiString` is **not debug-gated**, so every `MSG_*` name
should exist as a string literal in `game.dat`. That string table is the entry point the
[Ghidra workflow](../sage_patch/docs/runtime-re-workflow.md) is built for: strings → xrefs →
the message construction and append functions.

Hook that append path from an injected DLL, expose it over a pipe or socket, and the agent's
action space becomes *exactly* the order enum pySAGE already encodes - same ids, same argument
layouts, same `Options` bitfield semantics for casts. One hook converts the entire existing
order vocabulary into a live control API.

Two rules for the hook:

- **Inject at the message-stream level, not below it.** The engine is deterministic lockstep
  (the `0x44A` CRC heartbeat every 100 frames, plus the header's desync flag, are that
  mechanism). Orders entering through the normal path get network-ordered and check-summed like
  any input. Calling logic functions directly bypasses that and desyncs.
- **Respect the selection model.** Several orders are meaningless without it: `0x417` flag=True
  is "press command-button slot N of the *currently selected object*", which is a hero recruit
  or a `CASTLE_UNPACK` depending purely on what is selected. The agent must track its own
  selection state, exactly as the order map says a narrator must.

**(c) Author a replay file.** `serialize.py` + `retarget.py` can already emit a playable replay
for a target build. That is not interactive - no feedback loop, so useless for control - but it
is a first-class **test harness**: emit a scripted order sequence, let the engine play it, and
diff what happened against what was intended.

**The closed-loop validation this repo can already do:** inject a scripted opening through the
hook, let the game record its own replay, then parse that replay with `sage_replay` and assert
the order stream matches what was injected. The action interface is testable end-to-end with
existing tooling on day one.

## 5. Observing - the save format is a map of the runtime structs

The non-obvious lever. A `.sav` is a serialized engine snapshot written by `Xfer` - and `Xfer`
serializes struct members in declaration order. So **every field decoded in `sage_save` is a
candidate runtime struct offset**, and the existing decode already reaches `CHUNK_GameLogic`'s
object template table and per-object index (`iter_objects` names every live object on the map).
Continuing that decode - the "Phase 3" work already on the `sage_save` roadmap - is not just
save-file work; it doubles as reconnaissance for the observation API, cross-checkable against
the offsets already verified in `runtime-re-workflow.md`.

Four ways to observe, again in increasing order of correctness:

| approach | rate | cost | verdict |
|---|---|---|---|
| force a save, parse it | ~0.1 Hz | low - mostly works today | fine for coarse state; too slow and too disruptive for control |
| external `ReadProcessMemory` | 5-30 Hz | medium | good bootstrap; fragile across builds, no frame alignment |
| **in-process DLL, per-frame dump to shared memory** | every logic frame | high | **the target.** Frame-aligned, cheap, and the only one that scales |
| screen pixels | 30 Hz | high, plus a vision model | last resort; adds fog, camera and UI-layout coupling for no gain here |

A workable observation, per logic frame: for each visible object - template id (→ all its ini
stats for free), owning player, position, facing, health fraction, and production/queue state;
per player - resources, command points, spellbook points, upgrades held; plus the static map
from `sage_map`. Fog of war must be applied deliberately, or the agent trains on information a
human never had.

**Self-validating again:** dump an observation and force a save on the same frame; the object
list `sage_save.iter_objects` reports must match the dump. The correctness check for the hardest
component is a diff between two existing parsers.

## 6. Turning the corpus into observed data - re-simulation

This is the highest-value thing the observation work unlocks, and it is easy to miss: **once the
engine can emit per-frame observations, you play the existing replay corpus back through it and
record (state, action) pairs at every frame.** Replay playback is far cheaper than self-play -
no policy in the loop, no exploration - and it converts a pile of inputs into a fully observed
imitation-learning dataset covering real human play. It is the standard bootstrap for RTS
agents, and it is the reason to do section 5 before any RL.

Two honest costs:

- **Playback needs the exact recording build.** A replay's ids resolve against the build that
  wrote it, and `aggregate` already refuses a corpus mixing patch fingerprints. Re-simulating a
  multi-version corpus means one install per Edain version, driven separately.
- **Conversion is not a shortcut here.** `convert` can retarget a replay's ids, but the README
  is explicit that `ObjectId` arguments are runtime handles no conversion can remap, so a
  converted replay diverges during playback. Converted replays are for analysis, not for
  faithful re-simulation. Use real installs.

## 7. Controlling time - why RL is the last stage, not the first

RL needs 10⁷-10⁹ environment steps. Getting there needs four things BFME2 does not have:

1. **Headless.** No documented headless mode; it is a 32-bit DirectX Windows binary. Stubbing
   the device to a null renderer is the standard approach for games of this era and is plausible
   here, but it is a real RE project.
2. **An uncapped clock.** Logic is paced to the frame limiter. Removing the pacing sleep is
   likely a small patch - probably the *cheapest* item on this list - but it is untested.
3. **Scripted reset.** Launch → skirmish with chosen factions/map → finish → exit, unattended
   and deterministically.
4. **Parallelism.** One process per instance, on Windows or under Wine. Wine matters if this is
   ever to run on cloud Linux hosts.

Even granting all four: a 15-minute game at 10× is 90 seconds; 10⁵ games is ~2,500 core-hours.
That is affordable. The point is that *reaching* 10× costs months of reverse-engineering before
a single training step runs, and the published precedent (AlphaStar, with a vendor-supported
headless API and full state handed over) still needed compute far past a hobby budget. Do
sections 8-9 first; they produce a bot that plays. Revisit this only if that bot's ceiling is
the thing that actually blocks you.

## 8. What the corpus trains *today*, with no engine work

All of this runs against `TranslatedReplay` documents and the existing `stats` / `build_orders`
pipeline. No Ghidra, no DLL, no install of the recording build once the documents exist.

**Model 1 - the macro policy.** A sequence model over the clocked event timeline. Tokens are
`(category, label)` pairs from `StatEvent` - buildings, units, heroes, upgrades, sciences,
powers - conditioned on faction, enemy faction, map, and clock. Trained to predict the next
opening decision. `build_orders.py` already establishes the right identity for a build: two
independent streams (eco and spellbook) folded by *introduction order*, so the model learns
decisions rather than click noise. This is a complete macro brain, and it is a standard
next-token problem on data already in hand.

**Model 2 - the value head.** With sidecar winners, train `P(win | faction, matchup, map, state
at time t)`. Useful three ways: it is the evaluation function any later search or RL needs, it
ranks openings better than raw frequency, and on its own it is a **balance-analysis tool for the
mod** - "which Edain openings actually win, controlling for matchup and map" - which is arguably
more valuable to this project than the bot.

**Model 3 - timing and matchup structure.** `aggregate.py` already produces the frequentist view
(pick tables with win-loss records and median first-purchase times, optionally per enemy
faction). A model generalizes it to combinations the corpus never saw enough of.

**What none of them can do:** fight. Sections 3 and 5 are the reason.

Data hygiene worth building in from the start: dedupe by the size+hash identity
`translated.py` already assigns; filter to a skill band if the ladder index exposes rating;
keep `winner`'s `undetermined` games out of anything supervised by outcome; and hold out by
*player*, not by game, or the model memorizes individuals' habits and validation lies.

## 9. Staged plan and costs

| stage | deliverable | prerequisites | rough cost |
|---|---|---|---|
| **0. Dataset** | corpus → translated documents → tokenized sequences; splits, dedupe, labels | none (tooling exists) | days |
| **1. Macro model + value head** | next-decision model, win predictor, and a balance report as the visible artifact | stage 0 | 1-3 weeks |
| **2. Order injection** | DLL hook on the message-stream append path + Python client over the pySAGE order model; validated by inject → record → re-parse | Ghidra pass off the `MSG_*` string table | weeks (the `commandset-limit` work is the same skill set) |
| **3. Observation** | per-frame state to shared memory; validated against a same-frame save | continued `sage_save` decode; stage 2's DLL scaffolding | 1-3 months |

Stages 2 and 3 are the same library and are scoped together in [live-api.md](live-api.md).
| **4. Hybrid bot** | learned macro (stage 1) + scripted micro, playing live vs the skirmish AI | stages 1-3 | weeks |
| **5. Re-simulation dataset** | corpus replayed through the engine into (state, action) pairs | stage 3 + one install per Edain version | weeks, then compute |
| **6. Imitation micro** | a learned micro policy on stage 5's data | stage 5 | months |
| **7. RL** | headless, uncapped, parallel, self-play | everything above | a research project |

Stages 0-1 are worth doing on their own merits even if the bot never happens - they produce a
balance tool for Edain out of data that already exists. Stage 4 is the first thing that "plays
Edain". Stage 7 should not start until stage 4's ceiling is the measured problem.

## 10. The strategic alternative - a reimplemented engine

Every cost in sections 4-7 exists because `game.dat` is a closed 32-bit binary. An open
reimplementation inverts all of them: headless is a build flag, state is a field access, the
clock is a variable, and parallelism is process-spawning. This repo already follows
[OpenSAGE](https://github.com/OpenSAGE/OpenSAGE) for the Generals replay path.

The honest counterweight: BFME2 support in any reimplementation is a moving target, and Edain
is a very heavy mod that exercises far more of the engine than a vanilla skirmish - so
"contribute BFME2/Edain support upstream, then train against it" trades a bounded RE project
for an unbounded compatibility one. It is the right long game *if* an agent is the real goal
and the timeline is years. If the goal is a bot that plays Edain this year, patch the binary.

## 11. Risks and constraints

- **Edain is a moving target.** Ids shift every release. The mitigation is already the repo's
  design: policies must be expressed over **code names**, with `retarget.py` resolving to
  whatever build is running. Never train on raw integer ids.
- **Multiplayer is out of scope, and should stay out.** A patched client desyncs against
  unpatched peers (the `engine/README.md` caveat), and an injected agent on the ladder is
  cheating regardless. Skirmish, self-play, and offline analysis only.
- **Ship recipes, never binaries.** `sage_patch` already holds this line - the repo carries the
  patch, never a copyrighted `game.dat`. An agent DLL follows the same rule.
- **Anti-tamper.** No immediate failure observed on 2.01.2614 with the shipped patch, which is
  encouraging but not a guarantee for a DLL injection.
- **Determinism is a feature - use it.** Lockstep means a self-play game *is* a replay, which
  the entire existing analysis pipeline consumes unchanged. Evaluation, regression testing and
  post-hoc debugging of the bot all come free.
- **Skill ceiling of the data.** Ladder replays are a specific meta on specific maps. A macro
  model trained on them reproduces that meta, including its mistakes; it will not invent a build
  the corpus never contains.

## Where to start

Stage 0-1. They need no reverse-engineering, they exercise tooling that already exists, and
they answer the question that decides whether the rest is worth it: **how much of Edain's
outcome is decided by macro alone?** If a build-order model plus a value head predicts winners
well, a macro bot on scripted micro will be a real opponent and stages 2-4 are justified. If it
does not, the answer was always micro, and the project's true cost is section 5 onward - which
is much better to know before writing a single line of assembly.
