"""Shared test utilities and fixtures."""

import io
import json
from pathlib import Path

import pytest

from sage_map.context import ParsingContext, WritingContext
from sage_utils.stream import BinaryStream


def load_asset_bytes(asset_name: str) -> bytes:
    """Load asset bytes from the data directory.

    Args:
        asset_name: Name of the asset file in tests/sage_map/fixtures/

    Returns:
        Bytes content of the asset file, or empty bytes if file doesn't exist
    """
    data_dir = Path(__file__).parent / "fixtures"
    asset_path = data_dir / asset_name
    return asset_path.read_bytes()


def require_asset(asset_name: str) -> bytes:
    """Asset bytes for `asset_name`, or skip when its fixture is not present.

    A test needs both the raw asset (fixtures/<name>) and its asset list
    (fixtures/asset_lists/<name>.assets); if either is missing the test skips,
    so it self-enables the moment both fixtures are added - unlike a hard skip
    mark, which stays skipped even once the data exists.
    """
    fixtures = Path(__file__).parent / "fixtures"
    asset_path = fixtures / asset_name
    assets_path = fixtures / "asset_lists" / f"{asset_name}.assets"
    if not asset_path.is_file() or not assets_path.is_file():
        pytest.skip(f"no {asset_name} fixture present")
    return asset_path.read_bytes()


def load_asset_list(asset_name: str) -> dict[int, str]:
    """Load asset list mapping for a specific test asset.

    Args:
        asset_name: Name of the asset file in tests/sage_map/fixtures/asset_lists/

    Returns:
        Dictionary mapping asset indices to asset names, or default assets if file doesn't exist
    """
    data_dir = Path(__file__).parent / "fixtures" / "asset_lists"
    assets_path = data_dir / f"{asset_name}.assets"

    with open(assets_path) as f:
        # JSON keys are strings, convert them to integers
        loaded = json.load(f)
        return {int(k): v for k, v in loaded.items()}


def create_context(data: bytes, asset_name: str) -> ParsingContext:
    """Helper function to create a ParsingContext from bytes.

    Args:
        data: The bytes to parse
        asset_name: Name of the asset to load its specific asset list
    """
    stream = BinaryStream(io.BytesIO(data))
    context = ParsingContext(stream)
    context.assets = load_asset_list(asset_name)

    return context


def create_writing_context(asset_name: str) -> WritingContext:
    """Helper function to create a WritingContext with an empty BytesIO stream.

    Args:
        asset_name: Name of the asset to load its specific asset list
    """
    stream = BinaryStream(io.BytesIO())
    context = WritingContext(stream)

    # Load asset list
    asset_list = load_asset_list(asset_name)

    # Manually set the assets dictionaries to match the test assets (1-based indexing)
    context.assets_by_index = asset_list.copy()
    context.index_by_asset = {v: k for k, v in asset_list.items()}
    return context
