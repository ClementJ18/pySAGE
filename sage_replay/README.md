# sage_replay

A Python library for reading SAGE-engine replay files: Generals `.rep`, BFME
`.BfMEReplay`, and BFME2 / RotWK `.BfME2Replay`.

A replay is a header (timestamps, game version, and an ASCII metadata string carrying
the map and player slots) followed by the recorded order stream — one chunk per issued
command, tagged with its logic-frame timecode, the issuing player, and typed arguments
(object ids, world positions, screen rectangles, ...). Replays are inputs, not state:
reconstructing what *happened* requires re-simulating the game, but the order stream
alone already yields build orders, APM, selections, and command timing.

The Generals parsing path follows the OpenSAGE C# implementation
(https://github.com/OpenSAGE/OpenSAGE). The BFME2 header layout diverges and was
reverse-engineered against a corpus of real RotWK 2.01 replays (vanilla and Edain,
1v1 through 2v3 and vs-AI) — validated by every chunk stream parsing exactly to
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

# Infer the outcome from session-end signals (see below)
python -m sage_replay winner <replay>

# Machine-readable output
python -m sage_replay info <replay> --json
```

## Who won?

The outcome is never stored — a replay is inputs, and eliminations happen inside the
simulation. But how each human session *ends* is recorded: `0x448` is the voluntary
leave-game action, `0x1D` marks the end of the recording (attributed to the player whose
client wrote the file — the replay's point of view), and the `0x44A` checksum heartbeat
stops when a client drops. `winner` applies a concession heuristic over those signals
and answers honestly: `decided` when every human on all-but-one side left, `recorder_left`
when the recording player quit first (they conceded; the rest of the game lies beyond the
recording), and `undetermined` for elimination endings or surviving AI opposition (AI
players emit no orders at all). Details in
[order_space_map.md](order_space_map.md#session-end-shapes--winner-inference).

## Mapping order ids to mod objects

Order chunks carry integer ids that reference mod content (the unit recruited, the
structure built). `ids` isolates them and `align` turns a controlled, labelled replay
into an `id -> object` table. The method and the controlled-replay protocol are in
[object_id_mapping_plan.md](object_id_mapping_plan.md).

```sh
# Which order types carry an integer id, ranked (spot the recruit/build order)
python -m sage_replay ids <replay> --player 0

# The timecode-ordered id runs for one order type (a run = one recruit action)
python -m sage_replay ids <replay> --order 0x415 --player 0

# Join a label log to those runs → id/object rows; --out accumulates a JSON mapping
python -m sage_replay align <replay> labels.txt --order 0x415 --player 0 --out object_ids.json
```

Some order types carry more than one id space. The recruit order `0x417` has a leading
Boolean that switches meaning: `False` = a global unit/upgrade id, `True` = a
building-local hero-button slot. `--where INDEX=VALUE` (repeatable) filters `ids`/`align`
to one mode by an argument's value:

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
