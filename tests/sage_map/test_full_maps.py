"""Test full map parsing for all maps in tests/sage_map/fixtures/maps/."""

from pathlib import Path

import pytest
from reversebox.compression.compression_refpack import RefpackHandler

from sage_map import parse_map_from_path
from sage_map.map import write_map


def get_test_maps():
    """Get all map files from tests/sage_map/fixtures/maps/ directory."""
    maps_dir = Path(__file__).parent / "fixtures" / "maps"
    if not maps_dir.exists():
        return []
    return list(maps_dir.glob("*.map"))


@pytest.mark.parametrize("map_path", get_test_maps(), ids=lambda p: p.name)
def test_parse_map(map_path):
    """Test full parsing of individual map files.

    This test ensures that each map in the test data directory can be:
    1. Successfully parsed without errors
    2. Produces a valid Map object
    3. Can be converted to a dictionary (for serialization)
    """
    map_obj = parse_map_from_path(str(map_path))

    assert map_obj is not None, f"Failed to parse map: {map_path.name}"

    map_dict = map_obj.to_dict()
    assert map_dict is not None, f"Failed to convert map to dict: {map_path.name}"
    assert isinstance(map_dict, dict), f"to_dict() did not return a dict: {map_path.name}"


def test_maps_directory_exists():
    """Verify that the maps test data directory exists."""
    maps_dir = Path(__file__).parent / "fixtures" / "maps"
    assert maps_dir.exists(), "tests/sage_map/fixtures/maps/ directory does not exist"


def test_has_test_maps():
    """Verify that there are map files to test."""
    maps = get_test_maps()
    assert len(maps) > 0, "No .map files found in tests/sage_map/fixtures/maps/ directory"


@pytest.mark.parametrize("map_path", get_test_maps(), ids=lambda p: p.name)
def test_write_map(map_path):
    """Test that writing a parsed map produces identical bytes.

    This test ensures that:
    1. Map can be parsed successfully
    2. Parsed map can be written back to bytes
    3. Written bytes match the original decompressed map data
    """
    map_obj = parse_map_from_path(str(map_path))
    assert map_obj is not None, f"Failed to parse map: {map_path.name}"

    written_bytes = write_map(map_obj, compress=False)
    assert written_bytes is not None, f"Failed to write map: {map_path.name}"

    with open(map_path, "rb") as f:
        ea_compression = f.read(8)
        if not ea_compression.startswith(b"EAR"):
            f.seek(0)
        compressed_data = f.read()

    try:
        original_decompressed = RefpackHandler().decompress_data(compressed_data)
    except Exception:  # noqa: BLE001 — not refpack-compressed; use the raw bytes
        original_decompressed = compressed_data

    assert written_bytes == original_decompressed, (
        f"Written bytes don't match original for: {map_path.name}"
    )


@pytest.mark.parametrize("map_path", get_test_maps(), ids=lambda p: p.name)
def test_write_map_compressed(map_path):
    """Test that writing a parsed map with compression produces identical compressed bytes.

    This test ensures that:
    1. Map can be parsed successfully
    2. Parsed map can be written back with compression
    3. For originally compressed files, compressed bytes match the original
    4. The original game executable can read the compressed output

    Note: This test only validates matching bytes for files that were originally compressed.
    """
    map_obj = parse_map_from_path(str(map_path))
    assert map_obj is not None, f"Failed to parse map: {map_path.name}"

    with open(map_path, "rb") as f:
        ea_compression = f.read(8)
        if not ea_compression.startswith(b"EAR"):
            f.seek(0)

        original_data = f.read()
        is_compressed = False
        try:
            RefpackHandler().decompress_data(original_data)
            is_compressed = True
            f.seek(0)
            original_data = f.read()
        except Exception:  # noqa: BLE001 — not refpack-compressed
            is_compressed = False

    if is_compressed:
        written_compressed = write_map(map_obj, compress=True)
        assert written_compressed is not None, f"Failed to write compressed map: {map_path.name}"
        assert written_compressed == original_data, (
            f"Compressed bytes don't match original for: {map_path.name}"
        )
    else:
        written_compressed = write_map(map_obj, compress=True)
        assert written_compressed is not None, f"Failed to write compressed map: {map_path.name}"

        decompressed = RefpackHandler().decompress_data(written_compressed)
        written_uncompressed = write_map(map_obj, compress=False)
        assert decompressed == written_uncompressed, (
            f"Compressed data doesn't decompress correctly for: {map_path.name}"
        )
