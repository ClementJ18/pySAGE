# sage_asset

A lossless reader and writer for `asset.dat`, the BFME2/RotWK asset cache index, plus a builder,
a combiner and a checker. `asset.dat` lists every source art file the engine's asset cache knows
(`.w3d` models, `.tga` textures, ...), the assets each provides with their byte range inside it,
and which assets reference which.

No public documentation of the format exists; the tables below are the reference, checked
byte-exact against EA's own files (BFME2, RotWK), two Edain-built ones, and the output of EA's
`AssetCacheBuilder.exe`. The builder is a port of Brechstange's Edain-Toolbar builder
(`Edain_Toolbar/core/utils/asset_builder.py`), credited here.

## Binary format

All integers little-endian. A `pstr` is a uint8 length followed by that many latin-1 bytes, no NUL.

```
Header (16 bytes):
  bytes[4]  magic          # b"ALAE" ("EALA" byte-reversed)
  uint32    version        # 0x102 in every known file
  uint32    file_count     # number of section-1 records
  uint32    ref_count      # number of section-2 records

Section 1 - one record per source art file (file_count records):
  pstr      name           # e.g. "acolyte_soul.w3d", "263_rt_r1.tga" (lowercase)
  uint64    file_time      # Windows FILETIME of the file's mtime
  uint16    asset_count
  per asset:
    pstr    name           # e.g. "ACOLYTE_SOUL.KUACOLYTE_SKIN0", "H*ACOLYTE_SOUL"
    bytes[4] type          # FourCC stored byte-reversed, NUL-padded to 4
    uint32  offset         # chunk byte offset in the source file (0 for TEX)
    uint32  size           # chunk byte size (0 for TEX); consecutive assets tile the file

Section 2 - dependency table (ref_count records, runs to EOF):
  pstr      file_name      # section-1 file, e.g. "acolyte_soul.w3d"
  pstr      asset_name     # asset within it, e.g. "ACOLYTE_SOUL"
  uint16    n
  pstr[n]   references     # lowercase asset names, e.g. "acolyte_soul.tga", "normalmapped.fx"
```

| raw type bytes | `XET\0` | `HSEM` | `REIH` | `DOLH` | `MINA` | `XOB\0` | `HSXF` | `TRAP` |
|---|---|---|---|---|---|---|---|---|
| decoded | `TEX` | `MESH` | `HIER` | `HLOD` | `ANIM` | `BOX` | `FXSH` | `PART` |

Decoding strips trailing NULs and reverses the bytes; any well-formed tag round-trips, known or not.

Only assets with references get a section-2 record. EA's files list them in section-1 order, but
Edain's `complete_asset/asset.dat` has duplicates and another order, so `AssetDat.references` is kept
as its own ordered list; code built on it should do the same to stay byte-exact. A reference naming
something the file does not contain is reported by `sage-asset check`; every real file checked has
none, so one means corruption or a hand edit.

## Combining a base and mod asset.dat

A mod that ships its own asset.dat is loaded by concatenating it with the base game's: all the mod's
records, then all the base's, counts summed, no sorting or deduplication. **The mod must come first,
because the cache is first-wins**: the first record naming an asset keeps it (the gate at
`0x0052C6F6`, see [`sage_patch/docs/multi-mod.md`](../sage_patch/docs/multi-mod.md) section 4b). A
base-first combine overrides nothing and breaks art the mod replaced, since the stock byte ranges are
then read from the mod's file (26 files in Edain, `ebfoundationx.w3d` among them).

`combine_asset_dats(base, *overlays)` puts the overlays first, in argument order, then `base`. The
result shares its entry objects with the inputs.

```python
from sage_asset import combine_asset_dats, parse_asset_dat_from_path, write_asset_dat_to_path

base = parse_asset_dat_from_path("BFME2/asset.dat")
mod = parse_asset_dat_from_path("Edain/_mod/asset.dat")
write_asset_dat_to_path(combine_asset_dats(base, mod), "combined_asset.dat")
```

`shadowed_entries(ad)` lists each entry an earlier same-named one overrides; `.identical` marks an
unchanged file an overlay re-shipped for nothing. `sage-asset combine` prints the counts, and
`--show-overrides` the names.

## Building an asset.dat

`build_asset_dat(art_dir)` scans `compiledtextures/`, `Textures/` and `w3d/`: each texture becomes a
TEX entry named `<stem>.tga` (for several extensions, dds < tga < jpg < jpeg < png), and each `.w3d`
is walked chunk by chunk for its sub-assets, byte ranges, texture references and HLOD members. Its
output is byte-identical to the Edain-Toolbar builder's on the same tree.

The engine derives a texture's location from its name, so the file must sit there: names starting
`apt_` are read from `art/Textures/`, everything else from `art/CompiledTextures/XX/` (`XX` the
name's first two letters). `aptcomponents_001.tga` has no underscore, so it is an ordinary texture.

```python
from pathlib import Path
from sage_asset import build_asset_dat, write_asset_dat_to_path

ad = build_asset_dat(Path("art"), progress=lambda percent, message: print(percent, message))
write_asset_dat_to_path(ad, "asset.dat")
```

## Checking an asset.dat against its art tree

`sage-asset check --art <art_dir>` catches an asset.dat that was not rebuilt after the art changed,
using the builder's collection rules without its W3D parse:

- **missing**: files in the tree the asset.dat does not list (fails the check);
- **stale**: entries whose `file_time` no longer matches the file (fails the check);
- **orphaned**: entries whose file is gone. Expected for a combined asset.dat, whose base-game
  entries are not in the mod's tree.

## Model

```python
from sage_asset import Asset, AssetDat, FileEntry, ReferenceRecord

Asset(name: str, type: str, offset: int, size: int)
FileEntry(name: str, file_time: int, assets: list[Asset])   # .modified -> datetime (UTC)
ReferenceRecord(file_name: str, asset_name: str, references: list[str])
AssetDat(version: int, files: list[FileEntry], references: list[ReferenceRecord])
```

`AssetDat.file(name)` looks up case-insensitively, `references_for(file_name, asset_name)` returns
every matching reference list, and `asset_counts()` tallies by type. `w3d_references(data)` reads
one `.w3d`'s texture names and external skeletons without any tree or asset.dat.

```python
from sage_asset import parse_asset_dat_from_path, write_asset_dat_to_path

ad = parse_asset_dat_from_path("asset.dat")
entry = ad.file("acolyte_soul.w3d")
print(entry.modified, [a.name for a in entry.assets])
write_asset_dat_to_path(ad, "asset.rewritten.dat")  # byte-identical to the input
```

## Command-line tool

```
sage-asset info <dat>                      # version, counts, per-type tallies, file_time range
sage-asset ls <dat> [--type TEX] [--files-only]
sage-asset deps <dat> <name> [--reverse]   # reference lists; --reverse: who references <name>
sage-asset json <dat> [--out] [--compact]
sage-asset check <dat> [--art <art_dir>]   # round-trip, consistency, dangling references
sage-asset diff <a> <b>                    # files added / removed / changed
sage-asset combine <base> <overlay>... -o <out> [--show-overrides]
sage-asset build <art_dir> -o <out>        # scan the art tree and write asset.dat
```

## Desktop UI

A small window for building and combining, with a progress bar:

```
pip install "pysage-tools[asset-ui]"
sage-asset-ui        # or: python -m sage_asset.ui
```
