# sage_replay

A Python library for reading SAGE-engine replay files: Generals `.rep`, BFME `.BfMEReplay`, and
BFME2 / RotWK `.BfME2Replay`.

A replay is a header (timestamps, game version, and a metadata string with the map and player
slots) followed by the recorded order stream: one chunk per command, with its logic frame, the
issuing player and typed arguments. Replays hold inputs, not state, but the order stream alone
gives build orders, APM, selections and timing.

The Generals parser follows [OpenSAGE](https://github.com/OpenSAGE/OpenSAGE). The BFME2 header was
reverse-engineered against real RotWK 2.01 replays (vanilla and Edain, 1v1 to 2v3 and vs AI); every
chunk stream parses exactly to end of file. `ReplayFile.slot_for` maps orders back to player slots.

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

`--game` takes an extracted `data/ini` tree or a live install; repeat it with the base game first.

```sh
python -m sage_replay info <replay> [--json]      # game, version, map, players, duration
python -m sage_replay orders <replay> --limit 50  # the order stream (--player, --order 0x415)
python -m sage_replay narrate <replay> --game <install>  # the match retold in English
python -m sage_replay stats <replay> --game <install>    # per-player builds, upgrades, casts
python -m sage_replay aggregate <replay|dir>... --game <install>  # per-faction tables, below
python -m sage_replay winner <replay>             # the outcome (see "Who won?")
python -m sage_replay annotations <replay>        # score records from a patched client
python -m sage_replay convert <doc.json|replay> --game <target> --donor <replay> -o out.BfME2Replay
python -m sage_replay roundtrip <replay>          # parse and re-serialize, compare byte for byte
python -m sage_replay coverage <replay|dir>... [--strict]    # still-opaque format surfaces
python -m sage_replay coverage --diff a.BfME2Replay b.BfME2Replay  # which of them moved
```

`aggregate` groups player-games by faction: win rates, and pick tables for sciences, buildings,
units and heroes, each with its own win-loss record and median first-purchase time. Options:

- `--track-upgrade`, `--track-power`, `--track-purchase NAME` (repeatable) add tables for chosen
  upgrades, powers and repeatable purchases. A mod overlay can register the command with its own
  sets (`sage-edain replay-aggregate` in [pySAGE-edain](https://github.com/ClementJ18/pySAGE-edain)).
- `--combines` shows horde combines; `--matchups` repeats the tables per enemy faction.
- `--faction` / `--player` filter by substring; `--markdown` and `--html` choose the output.
- `--winner-pov` counts undetermined games as won by the recording player's team.

All replays must come from one patch: a corpus mixing game-data checksums exits 1, listing the
groups.

A standalone binary (no Python) is `pyinstaller sage_replay/sage-replay.spec`, built once per OS.

## What the engine counted

A replay says what a player built, never what it cost them: kills, losses and income are
simulation state, kept in each player's `ScoreKeeper` and never written down. `sage_patch`'s
**`replay-annotations`** patch writes it: a `0x7D3` chunk per player at the end (built, lost and
destroyed per opponent, money earned and spent, final army and base size) plus a `0x7D1` manifest.
[`annotations.py`](annotations.py) reads them, and `aggregate` reports per-faction medians split by
won and lost. Replays from unpatched clients carry none, and are counted separately rather than
diluting the medians.

## Who won?

The stock engine never records the outcome. With `sage_patch`'s **`replay-outcome`** patch, the
recording client writes a `0x7D0` chunk per player at the end with that player's final state from
the engine's own `VictoryConditions`; `infer_winner` prefers these over everything else.

Without them, `winner` infers from how each human session ended (`0x448` leave-game, the `0x1D`
end marker, the `0x44A` heartbeat stopping): `decided` when every human on all but one side left,
`recorder_left` when the recording player quit first, and `undetermined` otherwise (eliminations,
AI opponents). See
[order_space_map.md](order_space_map.md#session-end-shapes--winner-inference).

`aggregate` first checks for a ladder metadata sidecar (`<replay>.BfME2Replay.json`) naming the
winning team; `sidecar.py` maps it onto the replay's slots and refuses one whose teams don't line
up.

## Sharing a parse without the game that made it

A replay's ids only resolve against the game build that recorded it. `translated.py` defines
`TranslatedReplay`: the replay serialized as versioned JSON with every build-specific id resolved
to its code name. Whoever has the recording build produces it once; anyone can then load it back as
a `ReplayFile` and analyse it against any game with the same names. The document is tied to its
replay by size and content hash, and outcomes are resolved at load time, not stored. `cache.py`
turns a tree of documents into a parse cache (`tools/rebuild_aggregates.py` builds one). Nothing in
`sage_replay` caches as a side effect.

## Converting a replay to another version

`serialize.py` is a byte-exact writer (`roundtrip` checks it), and `retarget.py` re-resolves a
translated document's names to another version's ids, re-running hero recruits through that
version's revive rosters and re-indexing slot factions. `convert` chains the two. Limits:

- The header's patch identity cannot be fabricated, so `--donor` names a replay recorded under the
  target version to copy it from.
- Resolution is all or nothing: a name the target lacks aborts with the full list.
- `ObjectId` arguments are runtime ids and cannot be remapped, so a target whose gameplay data
  differs will still diverge during playback.
- Only v2 documents (with the raw header) can be converted; v1 documents are analysis-only.

## Mapping order ids to mod objects

Order chunks carry integer ids for mod content. `ids` finds them and `align` joins a labelled
replay to them, producing an `id -> object` table. Each order type's id space and resolution rule
is in [order_space_map.md](order_space_map.md).

```sh
python -m sage_replay ids <replay> --player 0                # which order types carry ids
python -m sage_replay ids <replay> --order 0x415 --player 0  # the id runs of one order type
python -m sage_replay align <replay> labels.txt --order 0x415 --player 0 --out object_ids.json
```

Some orders carry two id spaces: `0x417`'s first argument is `False` for a unit or upgrade id and
`True` for a hero's revive-menu position. `--where INDEX=VALUE` filters by argument value, e.g.
`--order 0x417 --where 0=false`.

The label log is plain text: `#` comments, `key: value` header lines, then one action per line as
`[<count>x] <name>`, in order:

```
faction: Angmar
mod: Edain 4.8.2

1x Fortress
3x Thrall Master
```
