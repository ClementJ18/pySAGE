# sage_save

A Python library for reading SAGE-engine save games: Battle for Middle-earth `.sav`-family
files (BFME2 `.BfME2Skirmish` and friends). Sibling to `sage_map`.

A save is a serialized engine snapshot — a 16-byte file header, a flat sequence of named,
self-delimiting chunks, and an `SG_EOF` token. Each chunk is
`ascii-name + "KOLB" marker + uint32 end-offset + payload`, where the end-offset is the
*absolute* file position the chunk ends at. Because every chunk is self-delimiting, the
container parses losslessly without understanding any payload: `sage_save` walks the top
level, keeps each payload as opaque bytes, and round-trips a save byte-for-byte. The deep
per-object state inside `CHUNK_GameLogic` is intentionally left undecoded.

On top of the container, `sage_save.xfer` implements the `Xfer` wire primitives and
`sage_save.chunks` decodes the chunks understood so far: `CHUNK_GameState` (description,
local timestamp, map, profile), `CHUNK_GameStateMap` (whose embedded map extracts to a
plain on-disk `.map` that every `sage_map` tool runs on unchanged), `CHUNK_Campaign`, and
`CHUNK_GameLogic` down to its object template table and per-object index — so `iter_objects`
names every live object on the map. Object bodies and the deeper per-player/script state stay
opaque.

`sage_save.xref` resolves the harvested ini-names against a `sage_ini` `Game` (`check_save`),
reporting the danglers — "will this save still load under this mod tree". Two classes are
harvested: object templates (`CHUNK_GameLogic`), which are *non-fatal* — the engine drops the
object at load — and the upgrade/science names (`CHUNK_Players`, via `sage_save.players`),
which are *fatal* — a dangling one aborts the load. The remaining classes (kind-of flags,
command buttons) await a fuller chunk decode; see "Phase 3 — work still to do" in
[sav_format.md](sav_format.md).

The framing follows the GPL Generals/Zero Hour `XferSave` source
(https://github.com/TheSuperHackers/GeneralsGameCode); the BFME container header, the
per-block `KOLB`/absolute-offset framing, and the chunk layouts were reverse-engineered
against real BFME2 skirmish saves and cross-validated on three saves across two maps with
different factions (Dwarves/Wild and Mordor/Men on one map, Elves vs a Mordor/Men/Isengard
team on another) — all round-trip byte-exact, all maps re-parse under `sage_map`, and the
object/upgrade/science harvests recognise each save's real content. Full format notes:
[sav_format.md](sav_format.md).

## Example

```python
from sage_save import (
    parse_save_from_path, decode_game_state, extract_map, iter_objects, check_save,
    save_to_json, apply_json, write_save_to_path,
)

save = parse_save_from_path("Saved Game 1.BfME2Skirmish")

header = decode_game_state(save.chunk("CHUNK_GameState"))
print(header.description, header.saved_at, header.map_name)

for chunk in save.chunks:
    print(chunk.name, f"v{chunk.version}", len(chunk.payload))

for obj in iter_objects(save):        # every live object, resolved to its ini template
    print(obj.object_id, obj.template_name)

open("embedded.map", "wb").write(extract_map(save))  # a normal on-disk .map

# Everything decoded as one JSON document
open("save.json", "w").write(save_to_json(save))

# Edit decoded attributes and write them back (length-preserving edits only — see below)
edited = apply_json(save, {"game_state": {"saved_at": "2030-12-25T09:00:00"}})
write_save_to_path(edited, "edited.sav")

# Cross-reference against a loaded game (Phase 3)
from sage_ini.loader import load_game
game = load_game("path/to/data/ini").game
for finding in check_save(save, game):
    print(finding.status, finding.reference.name)  # e.g. "missing HarlindonRuin10"
```

## Command line

```sh
# Header + full chunk table (names, versions, payload sizes)
python -m sage_save info <save>

# Write the embedded .map out (--out PATH, default <save>.map)
python -m sage_save extract-map <save>

# Live objects from CHUNK_GameLogic, grouped by ini template (--list for one row per object)
python -m sage_save objects <save>

# Everything decoded as one JSON document (--out FILE, --no-objects, --compact)
python -m sage_save json <save> --out save.json

# Apply edited JSON attributes back onto a save (edit save.json first, then:)
python -m sage_save edit <save> save.json --out edited.sav

# Resolve the save's ini-names (object templates + fatal upgrade/science names) against a
# game; report the danglers (exit 1 if any; a missing upgrade/science means the save won't
# load). --base layers the base game under an overlay mod so its base-game references resolve.
python -m sage_save check <save> --game <ini-tree-or-install> [--base <base-game>]

# Chunk-name/version inventory across a folder of saves (answers "which chunks
# does this game / save-kind write"); detection is by header magic, not extension
python -m sage_save scan <dir>

# Machine-readable output
python -m sage_save info <save> --json
```

## Editing a save

`apply_json(save, data)` (CLI: `edit`) writes the editable fields of a `json` export back onto
a save: the `game_state` (description, timestamp, map path, profile), `game_state_map` (map
paths, game mode) and `campaign` sections. Everything else in the JSON is a read-only view and
is ignored — the object index, upgrade/science names and the opaque chunk bulk cannot be edited
this way.

Because a save stores **absolute file offsets** inside its nested blocks, an edit that changes a
chunk's byte length would shift every later chunk and invalidate those offsets (a corrupt save,
confirmed empirically). `apply_json` therefore refuses any edit that changes a chunk's length,
raising a clear error. In practice this means you can change the **timestamp**, the **game
mode**, or **rename to a same-length string**; a different-length rename is rejected rather than
silently corrupting the file. The JSON is a decoded view, not the raw bytes, so `edit` needs the
original save as the source of the unchanged (mostly opaque) chunks.
