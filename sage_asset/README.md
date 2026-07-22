# sage_asset

A lossless reader/writer for `asset.dat`, the BFME2/RotWK asset cache index. No public
documentation of this format exists; the tables below are the reference, reverse-engineered
and checked byte-exact against EA's own `asset.dat` (BFME2, RotWK) and two community-built
ones (Edain's `_mod/asset.dat` and `complete_asset/asset.dat`).

`asset.dat` lists every source art file the engine's asset cache knows about (`.w3d` models,
`.tga` textures, ...), the individual assets each one provides with their byte range inside
it, and a dependency table of which assets reference which other assets.

Credit for the asset.dat parsing this package is built on goes to Brechstange, whose
Edain-Toolbar ships a native Python `asset.dat` builder
(`Edain_Toolbar/core/utils/asset_builder.py`); `sage_asset.builder` is a port of it (see
"Building an asset.dat" below). The format tables here were additionally verified byte-exact
against EA's own `asset.dat` files and the real `AssetCacheBuilder.exe`'s output.

## Binary format

All integers little-endian. Every string (`pstr` below) is a uint8 length prefix followed by
that many latin-1 bytes - no NUL terminator.

```
Header (16 bytes):
  bytes[4]  magic          # b"ALAE" ("EALA" byte-reversed)
  uint32    version        # 0x102 in every known file
  uint32    file_count     # number of section-1 records
  uint32    ref_count      # number of section-2 records

Section 1 - one record per source art file (file_count records):
  pstr      name           # e.g. "acolyte_soul.w3d", "263_rt_r1.tga" (lowercase)
  uint64    file_time      # Windows FILETIME (100ns ticks since 1601-01-01 UTC), file's mtime
  uint16    asset_count    # number of assets this file provides
  per asset:
    pstr    name           # e.g. "ACOLYTE_SOUL.KUACOLYTE_SKIN0", "H*ACOLYTE_SOUL"
    bytes[4] type          # FourCC stored byte-reversed, NUL-padded to 4
    uint32  offset         # asset chunk's byte offset inside the source file (0 for TEX)
    uint32  size           # chunk byte size (0 for TEX); consecutive assets tile the file

Section 2 - dependency table (ref_count records, runs to EOF):
  pstr      file_name      # section-1 file, e.g. "acolyte_soul.w3d"
  pstr      asset_name     # asset within it, e.g. "ACOLYTE_SOUL"
  uint16    n
  pstr[n]   references     # lowercase referenced asset names, e.g. "acolyte_soul.tga",
                           # "h*acolyte_soul", "normalmapped.fx"
```

Known type tags (raw on-disk bytes, decoded name):

| raw bytes  | decoded |
|------------|---------|
| `XET\0`    | `TEX`   |
| `HSEM`     | `MESH`  |
| `REIH`     | `HIER`  |
| `DOLH`     | `HLOD`  |
| `MINA`     | `ANIM`  |
| `XOB\0`    | `BOX`   |
| `HSXF`     | `FXSH`  |
| `TRAP`     | `PART`  |

Decoding strips trailing NULs and reverses the remaining bytes; encoding reverses the tag and
NUL-pads it back to 4 bytes. This is a lossless transform for any well-formed 4-byte tag, so an
unrecognized tag still parses and round-trips - it is not validated against this table.

Only assets with at least one reference get a section-2 record, so `ref_count` is not the
total asset count. In EA's own files section 2 is exactly section 1's assets, in order,
filtered to those with references - but a community-built `asset.dat` (Edain's
`complete_asset/asset.dat`) has been observed with duplicate `(file, asset)` section-2 records
and a different record order. `AssetDat` therefore keeps `references` as its own ordered list
rather than deriving it from `files`; do the same in any code built on top of it, or a
round-trip through that file will not be byte-exact.

A reference can also simply be wrong - naming a file or asset that doesn't exist anywhere in
the same asset.dat (dangling). `sage-asset check` reports these; all six real fixtures this
package has been checked against (EA's two, both Edain files, and both builder outputs) have
exactly zero, so a nonzero count is a genuine corruption or hand-edit, not an expected pattern.

## Combining a base and mod asset.dat

BFME2 mods that ship their own asset.dat (Edain's `_mod`) are loaded together with the base
game's by concatenating the two: every section-1 record and every section-2 record of the base
game's file, followed by every record of the mod's, with the header counts summed and the
version left unchanged. There is no sorting and no deduplication - a file name present in both
inputs ends up in the combined file twice, base's copy first and the mod's copy after it, and
that ordering (not some other resolution rule) is what lets the mod's asset override the base
game's at load time. The shipping `Edain/complete_asset/asset.dat` has 781 such duplicate file
names and 69 duplicate `(file, asset)` section-2 pairs; this is expected, not a corruption to
fix. This concatenation semantics was checked byte-exact: that shipping file's section 1 is
BFME2's `asset.dat` section 1 verbatim followed by the mod's, and likewise for section 2.
Exactly *how* the engine picks between two entries for the same name at load time is not
something this package claims to know - only that base-first/mod-after is the layout that ships
and works.

`combine_asset_dats(base, *overlays)` builds this layout for any number of overlays (combining
several mods is associative - just concatenate each in turn). The returned `AssetDat` is a new
top-level object but shares its `FileEntry`/`ReferenceRecord` objects with the inputs, so
mutating an entry in the result also mutates the corresponding input.

```python
from sage_asset import combine_asset_dats, parse_asset_dat_from_path, write_asset_dat_to_path

base = parse_asset_dat_from_path("BFME2/asset.dat")
mod = parse_asset_dat_from_path("Edain/_mod/asset.dat")
write_asset_dat_to_path(combine_asset_dats(base, mod), "combined_asset.dat")
```

`shadowed_entries(ad)` reports the shadowing a combine (or any duplicate-carrying asset.dat)
produced: one `ShadowedEntry` per file-entry occurrence that a later same-named entry
overrides, pairing it with the entry that actually wins. `.identical` is true when the
shadowed entry has the same `file_time` and asset list as its winner - an unchanged file the
overlay re-shipped for no reason, pure size bloat rather than a real override. `sage-asset
combine` prints the identical/changed counts automatically; `--show-overrides` lists every
shadowed name with its tag.

## Building an asset.dat

`sage_asset.builder` scans an unpacked art tree - `compiledtextures/` for textures, `w3d/` for
models - and builds the `AssetDat` it describes: every texture becomes a TEX entry (the
lowest-priority extension wins when a stem has more than one - dds < tga < jpg < jpeg < png -
and the entry is always named `<stem>.tga`), and every `.w3d` file is walked chunk by chunk to
list its mesh/hierarchy/animation/HLOD/box sub-assets with their byte range, and to record
which known textures each mesh references and which sub-objects each HLOD covers. This is a
faithful port of Brechstange's Edain-Toolbar builder - see the credit above - checked
byte-for-byte identical to it on the same art tree.

```python
from pathlib import Path
from sage_asset import build_asset_dat, write_asset_dat_to_path

ad = build_asset_dat(Path("art"))  # compiledtextures/ and w3d/ under here
write_asset_dat_to_path(ad, "asset.dat")

# report progress (e.g. from a UI) with a callback: percent (0-100), status message
ad = build_asset_dat(Path("art"), progress=lambda percent, message: print(percent, message))
```

## Checking an asset.dat against its art tree

`sage-asset check --art <art_dir>` catches the classic failure: the art changed but the
asset.dat wasn't rebuilt. It compares the asset.dat's entries against `art_dir`'s current state
- the same collection rules `build` uses (texture extension priority, `.tga`/`.w3d` naming),
but without the expensive W3D chunk parse (`collect_art_index`) - and reports:

- **missing** - files the tree has that the asset.dat doesn't list at all
- **stale** - entries whose recorded `file_time` no longer matches the source file's current one
- **orphaned** - entries whose source file is no longer in the tree

`missing` or `stale` findings fail the check (exit 1); `orphaned` alone does not. `--art` is
meant for a mod's own asset.dat checked against its own art tree - a *combined* asset.dat
legitimately carries base-game entries that mod's art tree never had, and those show up as
orphaned rather than as a problem.

## Model

```python
from sage_asset import Asset, AssetDat, FileEntry, ReferenceRecord

Asset(name: str, type: str, offset: int, size: int)
FileEntry(name: str, file_time: int, assets: list[Asset])   # .modified -> datetime (UTC)
ReferenceRecord(file_name: str, asset_name: str, references: list[str])
AssetDat(version: int, files: list[FileEntry], references: list[ReferenceRecord])
```

`AssetDat` adds a few read-only conveniences: `file(name)` (case-insensitive lookup),
`references_for(file_name, asset_name)` (a list of reference lists - duplicates exist in the
wild), and `asset_counts()` (asset tally by type).

`w3d_references(data: bytes) -> W3dRefs` reads a single `.w3d` file's outward references
without a `compiledtextures/`/`w3d/` tree or an asset.dat: `W3dRefs.textures` is the texture
names its meshes carry, `W3dRefs.hierarchies` the external skeleton stem(s) its HLOD(s) pull
in (empty when the file carries its own hierarchy-def).

## Example

```python
from sage_asset import parse_asset_dat_from_path, write_asset_dat_to_path

ad = parse_asset_dat_from_path("asset.dat")
print(ad.version, len(ad.files), len(ad.references))

entry = ad.file("acolyte_soul.w3d")
print(entry.modified, [a.name for a in entry.assets])

for refs in ad.references_for("acolyte_soul.w3d", "ACOLYTE_SOUL"):
    print(refs)

write_asset_dat_to_path(ad, "asset.rewritten.dat")  # byte-identical to the input
```

## Command-line tool

```
sage-asset info <dat>                  # version, counts, per-type tallies, file_time range
sage-asset ls <dat> [--type TEX] [--files-only]
sage-asset deps <dat> <name> [--reverse]   # reference lists; --reverse: who references <name>
sage-asset json <dat> [--out] [--compact]
sage-asset check <dat> [--art <art_dir>]   # round-trip + consistency + dangling-ref warnings;
                                            # --art also compares against the art tree's state
sage-asset diff <a> <b>                # files added / removed / changed
sage-asset combine <base> <overlay> [<overlay> ...] -o <out> [--show-overrides]
                                        # concatenate base + overlay(s); reports shadowing
sage-asset build <art_dir> -o <out>    # scan compiledtextures/ + w3d/ and write asset.dat
```

## Desktop UI

A small PyQt6 window for the two operations most useful outside a terminal - building an
asset.dat from an art tree and combining a base with a mod overlay - with a progress bar on the
build and both operations reporting their result counts, in the style of the other SAGE front
ends (`sage-lint-ui`, `sage-edain-lint`). Install the `asset-ui` extra and launch it:

```
pip install "pysage-tools[asset-ui]"
sage-asset-ui
# or: python -m sage_asset.ui
```
