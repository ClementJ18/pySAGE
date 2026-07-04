"""Test PostEffectsChunk asset parsing."""

from sage_map.assets import PostEffectsChunk

from .conftest import create_context, create_writing_context, load_asset_bytes


def test_post_effects_chunk():
    """Test PostEffectsChunk asset parsing."""
    asset_bytes = load_asset_bytes("PostEffectsChunk")

    context = create_context(asset_bytes, "PostEffectsChunk")
    result = PostEffectsChunk.parse(context)
    assert result is not None


def test_post_effects_chunk_write():
    """Test PostEffectsChunk asset writing."""
    asset_bytes = load_asset_bytes("PostEffectsChunk")

    # Parse the asset
    parse_context = create_context(asset_bytes, "PostEffectsChunk")
    result = PostEffectsChunk.parse(parse_context)

    # Write the asset
    write_context = create_writing_context("PostEffectsChunk")
    result.write(write_context)
    written_bytes = write_context.stream.getvalue()

    # Compare
    assert written_bytes == asset_bytes
