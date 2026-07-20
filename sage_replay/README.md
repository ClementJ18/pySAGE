# sage_replay

A Python library for reading SAGE-engine replay files: Generals `.rep`, BFME
`.BfMEReplay`, and BFME2 / RotWK `.BfME2Replay`.

A replay is a header (timestamps, game version, and an ASCII metadata string carrying
the map and player slots) followed by the recorded order stream - one chunk per issued
command, tagged with its logic-frame timecode, the issuing player, and typed arguments
(object ids, world positions, screen rectangles, ...). Replays are inputs, not state:
reconstructing what *happened* requires re-simulating the game, but the order stream
alone already yields build orders, APM, selections, and command timing.

The Generals parsing path follows the OpenSAGE C# implementation
(https://github.com/OpenSAGE/OpenSAGE). The BFME2 header layout diverges and was
reverse-engineered against a corpus of real RotWK 2.01 replays (vanilla and Edain,
1v1 through 2v3 and vs-AI) - validated by every chunk stream parsing exactly to
end-of-file with the header's timecode count matching the last chunk. Orders map
back to player slots via `ReplayFile.slot_for`.

## Example

```python
from sage_replay import parse_replay_from_path

replay = parse_replay_from_path("game.BfME2Replay")

print(replay.header.metadata.map_file)
for slot in replay.header.metadata.players:
    print(slot.human_name, slot.faction)

for chunk in replay.chunks[:10]:
    print(chunk.timecode, hex(chunk.order_type), chunk.order.arguments)
```

## Command line

```sh
# Header summary: game, version, map, players, duration, top order types
python -m sage_replay info <replay>

# Dump the order stream (--limit N, --player N, --order 0x415 to filter)
python -m sage_replay orders <replay> --limit 50

# Retell the match in English, resolving recruit/build/power/science/upgrade ids
# against a loaded game (--game an extracted data/ini tree or a live install; repeatable,
# base game first and mod after it)
python -m sage_replay narrate <replay> --game <install>

# Per-player stats: building/unit/hero counts per template type (fortress-hero
# recruits resolve to hero names via the revive-submenu model - see
# order_space_map.md 0x417 - falling back to raw slot numbers), upgrades
# researched, special-power casts (hero abilities / summons / unit toggles),
# and the spellbook sciences in purchase order
python -m sage_replay stats <replay> --game <install>

# Aggregate stats across many replays, grouped by faction: win rates plus science /
# building / unit / hero pick tables, each pick with its own win-loss record and median
# first-purchase time ("does the faction win more with science X or Y?"). Upgrade
# researches get pick tables, special-power casts get a table nested under Units, and
# repeatable system purchases per-instance depth rows (CPObject1, CPObject2, ...), each
# only for a tracked set: --track-upgrade / --track-power / --track-purchase NAME
# (repeatable), or `sage-edain replay-aggregate` = this same command with Edain's sets
# injected (its Imladris Loremaster shows as its element-specific horde, read off the
# toggle cast a `power_recruits` hook counts as a recruit). Horde combines
# are shown only with --combines. --matchups appends the same tables per enemy faction (buildings built
# vs Mordor, units vs Gondor) after each faction's own sections.
# --faction / --player filter the player-games (case-insensitive substring);
# --markdown renders the same tables as GitHub markdown, --html as one self-contained page.
# The replays must all come from one patch/mod: a corpus mixing patch fingerprints
# (the header's game-data checksum) exits 1 listing the groups.
python -m sage_replay aggregate <replay|dir>... --game <install>

# Re-emit a translated document (or a replay + --source-game) as a binary replay whose ids
# are valid for the --game version; --donor supplies the target patch identity (see below)
python -m sage_replay convert <doc.json|replay> --game <target install> --donor <replay> -o out.BfME2Replay

# Parse + re-serialize a replay and compare byte-for-byte (the writer's self-test)
python -m sage_replay roundtrip <replay>

# Infer the outcome from session-end signals (see below). --winner-pov (also on
# aggregate) assumes the recording player's team won any game the stream leaves
# undetermined - for corpora whose replays belong to the winner.
python -m sage_replay winner <replay>

# Format-coverage dashboard over a corpus: the distinct values still seen for every
# opaque surface (header reserved blocks, unnamed order ids, raw slot fields, untyped
# metadata keys). --strict exits non-zero on any deviation from the documented state.
python -m sage_replay coverage <replay|dir>... [--strict]

# Diff the opaque surfaces of two replays (the differential-decoding tool): which reserved
# bytes, tail words, metadata fields, slot fields, and order-id sets moved between them.
python -m sage_replay coverage --diff a.BfME2Replay b.BfME2Replay

# Machine-readable output
python -m sage_replay info <replay> --json
```

### Standalone binary (no Python)

```sh
pyinstaller sage_replay/sage-replay.spec
```

This produces `dist/sage_replay` (`dist/sage_replay.exe` on Windows) - one binary serving
every subcommand, the `--game`-resolved ones included. PyInstaller binaries are not
cross-platform, so build once per OS you support.

## Who won?

The outcome is never stored - a replay is inputs, and eliminations happen inside the
simulation. But how each human session *ends* is recorded: `0x448` is the voluntary
leave-game action, `0x1D` marks the end of the recording (attributed to the player whose
client wrote the file - the replay's point of view), and the `0x44A` checksum heartbeat
stops when a client drops. `winner` applies a concession heuristic over those signals
and answers honestly: `decided` when every human on all-but-one side left, `recorder_left`
when the recording player quit first (they conceded; the rest of the game lies beyond the
recording), and `undetermined` for elimination endings or surviving AI opposition (AI
players emit no orders at all). Details in
[order_space_map.md](order_space_map.md#session-end-shapes--winner-inference).

`aggregate` doesn't have to guess when the truth is on disk: a replay downloaded from the
ladder carries a `<replay>.BfME2Replay.json` metadata sidecar that names the winning team
outright. `sidecar.py` reads it and maps that team onto the replay's human slots (so even a
lobby-Random slot, which records no faction, is placed by its team), and `collect` prefers it,
falling back to the concession heuristic only for a replay with no trustworthy sidecar. The
match is deliberately strict - a sidecar whose team structure doesn't line up with the replay
(a stale or mismatched record) is refused rather than trusted - so the heuristic still backs
every game the sidecars can't vouch for.

## Sharing a parse without the game that made it

Everything in a replay's order stream resolves against the exact game build that recorded it -
template ids by ini load order, hero recruits by revive-menu position - so consuming a corpus
normally means installing each recording patch in turn. `translated.py` defines the document
that breaks the coupling: `TranslatedReplay`, one replay's own structure serialized as versioned
JSON with every version-coupled id resolved to its code name and nothing else raw. Whoever holds
the recording patch produces the document once; anyone else can then rehydrate it into a
`ReplayFile` and run the whole analysis pipeline against any game whose templates share those
names, with no matching install at all. All analysis - KindOf bucketing, the faction/power
overlay, the winner - lives at load time, so a pipeline or overlay change never invalidates a
document; it only goes stale when id-space knowledge itself changes. The document is tied to its
replay by size + content hash (identity that survives copying), and winners are *not* baked in:
a load re-resolves each outcome from whatever sidecar sits beside the replay now, falling back to
the concession heuristic. `cache.py` turns a tree of these documents into a parse cache: a folder
structure mirroring the replay tree (`tools/rebuild_aggregates.py` mirrors `downloads/replays/`
into `downloads/cached/`), the trust checks, and the load-time pipeline that turns a document
back into player-games. Producing a document is always an explicit step by the caller - nothing
in sage_replay caches as a side effect.

## Converting a replay to another version

The translated document also works in reverse. `serialize.py` is a byte-exact binary writer
(`serialize_replay(parse_replay(data)) == data` across the whole fixture corpus - the `roundtrip`
command is that check as a one-liner), and `retarget.py` takes a v2 document plus a *target*
game's data and re-resolves every code name back to that version's integer ids: template /
upgrade / science / special-power names looked up in the target's tables, fortress-hero recruits
re-run through the `ReviveList` simulation under the target's rosters and build times (so the
emitted slot ids follow the *target's* revive-menu dynamics), and the metadata slot factions
re-indexed against the target's PlayerTemplate order. `convert` chains the two into a playable
file. Only a v2 document (one carrying the raw `header` block) can be re-emitted; v1 documents
stay valid for analysis and are refused with a request to re-translate.

Three honest limits. The header's patch identity - the `version` / `build_date` strings, the
`data_checksum`, the metadata `GSID` - is computed by the engine and cannot be fabricated, so
`--donor` names any replay recorded under the target version and the converter lifts its
identity; without one the file keeps the source identity and the target game will flag it.
Resolution is all-or-nothing: a name the target lacks (renamed or removed template, a hero off
the target roster) aborts the conversion with the full failure list, because a silently wrong id
corrupts the simulation and a dropped chunk would shift every later revive-menu position. And
`ObjectId` arguments are runtime simulation ids that no conversion can remap - the order
stream's ids are exact for the target, but a target version whose gameplay data differs at all
will still diverge from the recorded commands during playback.

## Mapping order ids to mod objects

Order chunks carry integer ids that reference mod content (the unit recruited, the
structure built). `ids` isolates them and `align` turns a controlled, labelled replay
into an `id -> object` table. Each order type's id space and its resolution rule are in
[order_space_map.md](order_space_map.md).

```sh
# Which order types carry an integer id, ranked (spot the recruit/build order)
python -m sage_replay ids <replay> --player 0

# The timecode-ordered id runs for one order type (a run = one recruit action)
python -m sage_replay ids <replay> --order 0x415 --player 0

# Join a label log to those runs → id/object rows; --out accumulates a JSON mapping
python -m sage_replay align <replay> labels.txt --order 0x415 --player 0 --out object_ids.json
```

Some order types carry more than one id space. The recruit order `0x417` has a leading
Boolean that switches meaning: `False` = a global unit/upgrade id, `True` = the hero's
current position in the player's revive submenu (stats/narrate resolve it to a hero name
via the model in order_space_map.md). `--where INDEX=VALUE` (repeatable) filters
`ids`/`align` to one mode by an argument's value:

```sh
# just the unit/upgrade recruits (drops the fortress-hero orders)
python -m sage_replay align <replay> labels.txt --order 0x417 --where 0=false --out object_ids.json

# just the hero-slot orders
python -m sage_replay ids <replay> --order 0x417 --where 0=true
```

The label log is plain text: `#` comments, `key: value` header lines, and one action
per line as `[<count>x] <name>`, in the order performed:

```
faction: Angmar
mod: Edain 4.8.2

1x Fortress
3x Thrall Master
2x Dark Ranger
```
