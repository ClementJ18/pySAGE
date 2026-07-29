# `sage_live` — a Python API for a running game

Scope for the first piece of the [ML-agent plan](ml-agent.md): a library that attaches to a
running RotWK/Edain process, reports what is happening, and issues orders. Everything above it
(policies, training, bots) is a consumer of this API and is out of scope here.

> **This is the design document.** For the interface as it actually shipped — `attach()`, the
> query surface on `Observation`, the CLI, and the current known gaps — read
> [`sage_live/README.md`](../sage_live/README.md). This file records *why* it is shaped that
> way, and what is still open.

**Shape of the answer.** Almost all of the *modelling* already exists — `sage_replay` has the
order types, the argument types, the byte-exact encoder, and the name→id tables. What does not
exist is a **transport**, an **observation model**, and a **game-side component** to talk to. So
this is deliberately staged: the protocol and the whole Python surface can be built and tested
with no game and no reverse-engineering at all, then backed by progressively more capable
backends. The first genuinely useful milestone (read-only observation) needs **no code injection**.

## 1. What "communicating with a running game" decomposes into

| concern | question | where it lands |
|---|---|---|
| attach | find the process, confirm it is the right build | `session.py` |
| transport | move bytes across the process boundary | `transport.py` |
| protocol | frame, version and route those bytes | `protocol.py` |
| observe | turn a state blob into typed Python | `observation.py` |
| act | turn an intent into a well-formed order | `orders.py` (+ `sage_replay`) |
| resolve | turn `"MordorFighterHorde"` into this build's id | `resolve.py` (needs `sage_ini`) |
| game side | produce the state, accept the orders | `bridge/` (not Python) |

## 2. Name and package shape

**`sage_live`** — the symmetry with `sage_replay` is the argument: one reads recorded games, the
other reads and drives running ones. (`sage_bridge` names the mechanism instead; easy to change
now, painful after the first release.)

The internal split copies `sage_replay`'s, which is deliberate and load-bearing. That package's
root is **install-free** — `narrate`, `stats`, `translated` and `retarget` import `sage_ini` and
are therefore *not* re-exported from `__init__`. Same rule here:

- **stdlib-only, no game install:** `transport`, `protocol`, `observation`, `orders`, `session`.
  These are what the core test suite exercises.
- **needs a loaded game (`sage_ini`):** `resolve` only. Import it from its own module.

That keeps `from sage_live import connect` working on a machine with no game data, and it keeps
CONVENTIONS rule 7 satisfiable — a bare `pytest` must stay data-free.

## 3. Architecture: one interface, three backends

```
        policy / bot / notebook
                  |
        sage_live.Session          <- selection state, APM cap, name resolution
                  |
          Backend (Protocol)       <- observe() / send() / handshake
        /         |         \
LoopbackBackend  MemoryBackend  BridgeBackend
 (in-process)     (read-only)    (DLL, read+write)
```

**`LoopbackBackend`** — an in-process implementation of the same wire protocol, fed scripted
observations. Exists from day one, needs no game, and is what makes the whole Python layer
testable in the data-free suite. Not a toy: it is the conformance test for the protocol codec.

**`MemoryBackend`** — read-only, external, `OpenProcess` + `ReadProcessMemory` via `ctypes`. No
injection, no patched binary, no anti-tamper surface. This is the first milestone that talks to a
real game, and it is worth having permanently as the low-risk observation path.

**`BridgeBackend`** — the injected DLL. Full per-frame observation and order injection. Everything
that actually *plays* needs this.

Backends are constructed explicitly (`connect(backend=...)`) and the platform check happens at
construction, never at import — `sage_live` must import cleanly on Linux, matching how the repo
already guards its one Windows-only dependency.

## 4. Wire protocol

**Transport: TCP on loopback.** Chosen over a named pipe because it costs nothing to support the
cases that will come up anyway — the game in a VM, the game under Wine while the policy runs on
Linux, the trainer on a different host. A named pipe buys nothing here.

**Framing:** length-prefixed messages, little-endian, `uint32 length | uint16 type | payload`.
Two channels multiplexed on the one socket:

- **request/response** — handshake, query, send-orders, control.
- **events** — observation frames pushed by the game, plus session events (game over, desync).

**Observations are a versioned binary struct, not JSON**, from the very first version. Not for
speed today but so that the later optimisation — hand the client a shared-memory handle and write
frames into a ring buffer instead of the socket — is a transport swap with **no change to
`Observation` or to any caller**. Designing this in costs one afternoon; retrofitting it costs a
rewrite of every consumer.

**The handshake is a gate, not a greeting.** It carries the protocol version, the engine build id,
and the loaded mod's data checksum — the same patch identity the replay header already records and
that `aggregate` already refuses to mix. A mismatch **fails the connection** rather than degrading.
This is the same discipline `sage_patch` applies when it asserts expected bytes before writing:
refuse early, never operate on an assumption.

## 5. Observation model

```python
@dataclass(frozen=True)
class Observation:
    frame: int
    local_player: int
    players: tuple[PlayerState, ...]
    objects: tuple[GameObject, ...]

@dataclass(frozen=True)
class PlayerState:
    index: int
    faction: str            # Side token, e.g. "Mordor"
    resources: int
    power_points: int       # spellbook
    command_points: tuple[int, int]   # used, cap
    upgrades: frozenset[str]          # completed, PLAYER-scoped only

@dataclass(frozen=True)
class GameObject:
    object_id: int
    template_name: str      # -> every ini stat, for free, via sage_ini
    owner_index: int | None # the owning *player*, which is not template_side
    position: tuple[float, float, float]
    angle: float
    health: float           # fraction
    upgrades: frozenset[str]  # completed, OBJECT-scoped: this battalion's, this structure's
```

**The model is also the query surface.** Every consumer was writing the same four filters by
hand — mine, by template, damaged, within range — and each copy was a chance to filter by
`template_side` where it meant ownership, which is a mistake that returns plausible wrong
answers rather than failing. So `find`/`nearest`/`census`/`me`/`mine`/`opponents` live on the
dataclasses, and `to_dict` gives one JSON schema for consumers that are not Python. None of it
holds state; they are queries over a frozen snapshot.

Four notes that shape the design:

- **Upgrades live in two places and neither is optional.** Faction-wide researches are on the
  player; per-battalion and per-structure ones are on the object and appear in no other field —
  not the template name, not the player's set. A policy asking "did the upgrade I paid for land?"
  has to look at the right one. See [`live-object-model.md`](../sage_patch/docs/live-object-model.md)
  §3a, including the in-progress mask that the engine never clears for object-scoped upgrades.

- **`template_name` carries the whole unit model.** Once an object names its template, `sage_ini`
  and `sage_mods.edain` supply cost, armour, weapons, build time, command points and the faction
  tree. The observation stays small and the consumer joins against static data it already has.
- **Fog of war must be applied on the game side, per player, and it must be explicit.** The
  engine knows what a player can see; the API must not quietly hand over the whole map. Make it a
  session option that defaults to fogged, so training on impossible information is a deliberate
  act rather than an accident.
- **Frozen dataclasses.** An observation is a snapshot; making it immutable stops a whole class of
  bug where a policy mutates last frame's world.

## 6. Action model — reuse `sage_replay`, do not reinvent

The action space is `sage_replay.Order` / `OrderArgument` / `OrderArgumentType` /
`Bfme2OrderType`, unchanged. `sage_live` adds constructors, not a parallel model:

```python
game.select([12, 13, 14])
game.move((1200.0, 880.0, 0.0))
game.build("MordorSlaughterHouse", (1024.0, 768.0, 0.0), angle=0.0)
game.recruit("MordorFighterHorde")
game.research("Upgrade_MordorFireArrows", building_id=12)
game.purchase_power("Science_EyeOfSauron")
game.send(Order(...))                      # escape hatch, always available
```

Each of those takes a **name or an id**, resolved through the session's `NameLookup`. That is a
protocol, not a class, precisely so `Session` imports nothing from `sage_ini`: `LiveNames` fits
the engine's own registry and `resolve.Resolver` fits an ini load, and a session can be handed
either. `research` takes the building's id explicitly rather than reading the selection, because
0 is not a wildcard — the engine consumes that order and then discards it, charging nothing.

Everything above compiles to an `Order`, so the *entire* order vocabulary is reachable from day
one via `send`, and the named helpers are ergonomics added as they are validated. It also means
an emitted action can be round-tripped through `sage_replay.serialize` — which is what makes
section 10's acceptance test possible.

**The name→id tables already exist and should be extracted, not copied.**
`retarget._resolve_chunks` builds exactly the four inverse tables a live encoder needs:

```python
things    = {name: i + 1 for i, name in enumerate(target.object_order)}
upgrades  = {name: i + 3 for i, name in enumerate(target.upgrades)}
powers    = {name: i + 1 for i, name in enumerate(target.specialpowers)}
sciences  = {name: i + 1 for i, name in enumerate(target.sciences)}
```

Promote those into a public encoder over `narrate.GameData` that both `retarget` and `sage_live`
use. One id-space rule, one place, one set of tests — and any future offset correction fixes both
callers at once. (The `+3` on upgrades is now explained: three veterancy upgrades the engine
registers before parsing any ini, so an ini-derived table starts three short. OPEN 4 is closed,
and a live consumer reading `TheUpgradeCenter` needs no offset at all.)

**Live state deletes the hardest part of the replay-side model.** Recruiting a fortress hero is
`0x417` flag=True, "press command-button slot N of the currently selected object", where N is the
hero's *dynamic* position in the revive submenu. Offline, that needs the whole `ReviveList`
simulation — rosters, build times, who has fielded, where a dead hero re-enters. Live, you read
the selected object's current command set out of the engine and look up which slot holds the
button you want. The simulation becomes an assertion instead of a dependency.

**Selection is session state, and it is mandatory.** `0x417` flag=True is byte-identical whether
it recruits a hero or unpacks an outpost; only the current selection disambiguates. `Session`
tracks selection, refuses a selection-dependent order when nothing is selected, and exposes it —
the same conclusion the order map reaches for a narrator.

**APM cap as a first-class session option.** An unthrottled agent can emit orders at a rate no
human could and that the engine was never tested against. `sage_replay`'s own stats give the
realistic distribution to calibrate against. Default it on.

## 7. Frame model: async now, stepped later, decided now

| mode | game waits for the agent? | needs | for |
|---|---|---|---|
| **async** | no — policy reads the latest observation | nothing extra | bots, live play, human-like agents |
| **stepped** | yes — blocks until orders are returned | blocking the logic loop | reproducible rollouts, faster-than-real-time, RL |

Implement async first; it needs no clock control. But put `step()` and `poll()` in the interface
**now**, because the difference between "a bot" and "an RL environment" is exactly this, and
retrofitting a blocking contract through an async-shaped API is a rewrite. Stepped mode is safe
in skirmish; in multiplayer it would break lockstep timing, which is one more reason section 11
keeps MP out of scope.

## 8. What the game side has to be

Not Python, and it needs stating so the boundary is clear.

**Loading.** A proxy DLL in the game folder (a stub standing in for a DLL the game already
imports, forwarding every export) is the standard approach: no admin rights, no
`CreateRemoteThread`, no modified `game.dat`, and it survives a game reinstall of everything
except that one file. The alternatives — runtime injection, or a `sage_patch` byte patch adding
an import — both work and both cost more.

**Responsibilities.** Hook the message-stream append path to inject orders; walk the object and
player lists once per logic frame to produce an observation; own the fog filter; implement the
handshake and refuse a build it does not recognise. Nothing else — no policy logic, no game
knowledge. Everything the bridge knows how to do is a primitive.

**Ship the recipe, never the binary.** `sage_patch` already holds this line for `game.dat`; the
bridge follows it. Source plus a build script, not a compiled DLL in the tree.

**Debugging is already tooled.** `sage_patch/engine/dump.py` parses minidumps with a
`game.dat`-relative stack walk — which is exactly what a crash caused by a bad hook produces.

## 9. Known unknowns — the reverse-engineering list

Honest inventory. Each is a blocker for a specific milestone, and each has a stated method.

| # | unknown | blocks | method |
|---|---|---|---|
| 1 | **GameLogic object-list head + iteration** — how to enumerate live objects | M1 | `sage_save` already decodes `CHUNK_GameLogic`'s object template table and per-object index; `Xfer` serialises in declaration order, so the save layout is a map of the runtime struct |
| 2 | **Object body offsets** — position, health, state | M1 | same lever; these are precisely the "object bodies stay opaque" part of the save decode. Confirm with Cheat Engine against a unit you damage on demand |
| 3 | **Player resources / power points** — `Player+0x3DC` is the *stats* block, not the economy | M1 | known-value search on a resource number you can change by building something |
| 4 | **MessageStream append function** | M2 | `getCommandTypeAsAsciiString` is not debug-gated, so every `MSG_*` name is a string literal in `game.dat`; strings → xrefs is the documented workflow, and it closes OPEN 10 as a side effect |
| 5 | **Live CommandSet state of a selected object** | hero recruits | `ThingTemplate+0x70` is the static CommandSet; the runtime availability/paging state is adjacent work |

Already verified and not on this list: `PlayerList+0x10` (local player), `Player+0x3DC`,
object `+0x04` → `ThingTemplate`, template `+0x64` name / `+0x6C` Side / `+0x70` CommandSet.

Unknown 1 is the gate on everything. It is also the one with the strongest existing lead, and it
is worth doing as `sage_save` work first — it improves that package on its own terms and produces
the runtime map as a by-product.

## 10. Milestones, each with an acceptance test that uses tools we already have

| # | deliverable | acceptance test | blocked by |
|---|---|---|---|
| **M0** | protocol codec, `Observation`/`Order` models, `Session`, `LoopbackBackend` | round-trip every message type; a scripted session drives a policy end to end — **all data-free** | nothing |
| **M1** | `MemoryBackend`: attach, identify build, list players and objects | force a save at the same moment; the object list must match `sage_save.iter_objects` | unknowns 1–3 |
| **M2** | order injection: one order, correctly | let the game record its own replay; parse it with `sage_replay` and assert the injected order appears at the expected frame with the expected arguments | unknown 4 |
| **M3** | `BridgeBackend`: per-frame observation + full order vocabulary + selection tracking | a scripted opening executes; the recorded replay's order stream matches the intent, and `narrate` retells it correctly | M1, M2 |
| **M4** | stepped mode | N identical rollouts from one save produce identical observation hashes | M3 |

M0–M3 are done. What the interface still misrepresents is **per-object activity**: production
and queue state are not located, so a barracks already training reads as idle and a half-built
structure is indistinguishable from a finished one; and horde membership is not reported, so a
battalion appears as its individual members. Both are read-side reverse engineering against
`Object`, not API work — see [`live-object-model.md`](../sage_patch/docs/live-object-model.md) §5.

M0's test suite is the whole Python surface. M1 and M2 are each independently useful — M1 is a
live game inspector, M2 is scripted-build automation — so neither is dead weight if the project
stops there.

The M2 and M3 tests deserve emphasis: **the verification tool for the write path is the read path
we already shipped.** The engine records its own replay of a session the API drove; `sage_replay`
parses it; the parse must equal the intent. That is an unusually strong acceptance test for
something this deep in a closed binary, and it exists only because the replay layer came first.

## 11. Checklist and boundaries

**Repo conventions this has to meet:** `__all__` on every public module; full annotations under
mypy with a `py.typed` marker; Ruff format and lint; imports at module top level except a lazily
imported optional dependency; parsing that emits diagnostics rather than raising on malformed
input — which here means a bridge sending a frame we cannot decode degrades to a diagnostic, it
does not kill the session. Packaging: add `sage_live*` to `packages.find`, `py.typed` to
`package-data`, a `sage-live` console script for the inspector, `tests/sage_live/`, and mark any
test needing a real game `full`.

**Out of scope, deliberately:** multiplayer (a patched or bridged client desyncs against
unpatched peers, and an injected agent on the ladder is cheating regardless — skirmish and
self-play only); the DLL's implementation; the RL clock work from
[ml-agent.md](ml-agent.md) §7; and any policy or model code, which is a consumer of this API.

## Where to start

M0, then unknown 1. M0 is pure Python against a fake backend, it locks the protocol and the
observation shape while both are still cheap to change, and it is fully covered by the data-free
suite. Unknown 1 is the real gate, and the cheapest attack on it is to keep decoding `.sav`
object bodies — work that stands on its own inside `sage_save` and hands over the runtime struct
map as a side effect.
