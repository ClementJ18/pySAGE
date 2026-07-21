"""Reader/writer for the SAGE engine's `asset.dat` file - the BFME2/RotWK asset cache index of
every source art file, the assets each one provides, and their cross-references. See
`sage_asset.assetdat` and README.md for the binary layout; `sage-asset` is the command-line
front end (`sage_asset.__main__`)."""

from sage_asset.assetdat import (
    Asset,
    AssetDat,
    AssetDatError,
    FileEntry,
    ReferenceRecord,
    ShadowedEntry,
    VersionMismatchWarning,
    combine_asset_dats,
    parse_asset_dat,
    parse_asset_dat_from_path,
    shadowed_entries,
    write_asset_dat,
    write_asset_dat_to_path,
)
from sage_asset.builder import build_asset_dat, collect_art_index

__all__ = [
    "Asset",
    "AssetDat",
    "AssetDatError",
    "FileEntry",
    "ReferenceRecord",
    "ShadowedEntry",
    "VersionMismatchWarning",
    "build_asset_dat",
    "collect_art_index",
    "combine_asset_dats",
    "parse_asset_dat",
    "parse_asset_dat_from_path",
    "shadowed_entries",
    "write_asset_dat",
    "write_asset_dat_to_path",
]
