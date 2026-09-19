"""Test EnvironmentData asset parsing."""

from sage_map.assets import EnvironmentData

from .conftest import create_context, create_writing_context, load_asset_bytes


def test_environment_data():
    """Test EnvironmentData asset parsing."""
    asset_bytes = load_asset_bytes("EnvironmentData")

    context = create_context(asset_bytes, "EnvironmentData")
    result = EnvironmentData.parse(context)
    assert result is not None


def test_environment_data_write():
    """Test EnvironmentData asset writing."""
    asset_bytes = load_asset_bytes("EnvironmentData")

    # Parse the asset
    parse_context = create_context(asset_bytes, "EnvironmentData")
    result = EnvironmentData.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("EnvironmentData")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes


def test_environment_data_write_without_unknown_texture2():
    """A v6+ chunk that ends before the optional second texture writes back without it."""
    asset_bytes = load_asset_bytes("EnvironmentData")
    result = EnvironmentData.parse(create_context(asset_bytes, "EnvironmentData"))
    # The fixture's own version may predate the optional texture, so write it as v6.
    result.version = 6
    if result.water_max_alpha_depth is None:
        result.water_max_alpha_depth = 0.0
    if result.deep_water_alpha is None:
        result.deep_water_alpha = 0.0
    if result.unknown_texture is None:
        result.unknown_texture = ""
    result.unknown_texture2 = None

    write_context = create_writing_context("EnvironmentData")
    result.write(write_context)
    reparsed = EnvironmentData.parse(
        create_context(write_context.stream.getvalue(), "EnvironmentData")
    )

    assert reparsed.version == 6
    assert reparsed.unknown_texture2 is None
    assert reparsed.macro_texture == result.macro_texture
