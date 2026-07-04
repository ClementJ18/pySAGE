# Test Suite

This directory contains unit tests for individual map parser assets, mirroring the structure of `sage_map/assets/`.

## Structure

Each asset has its own test file, and test data is stored in the `fixtures/` directory:

### Test Files

#### Individual Asset Tests

- `test_global_version.py` - Tests for GlobalVersion asset
- `test_world_info.py` - Tests for WorldInfo asset
- `test_blend_tile_data.py` - Tests for BlendTileData asset
- `test_teams.py` - Tests for Teams asset
- `test_waypoint_list.py` - Tests for WaypointsList asset
- `test_asset_list.py` - Tests for AssetList asset
- `test_camera_animation_list.py` - Tests for CameraAnimationList asset
- `test_environment_data.py` - Tests for EnvironmentData asset
- `test_global_lighting.py` - Tests for GlobalLighting asset
- `test_height_map.py` - Tests for HeightMapData asset
- `test_library_map_lists.py` - Tests for LibraryMapLists asset
- `test_mp_positions.py` - Tests for MPPositionList asset
- `test_named_cameras.py` - Tests for NamedCameras asset
- `test_object_list.py` - Tests for ObjectsList asset
- `test_player_scripts.py` - Tests for PlayerScriptsList asset
- `test_polygon_triggers.py` - Tests for PolygonTriggers asset
- `test_post_effects_chunk.py` - Tests for PostEffectsChunk asset
- `test_river_areas.py` - Tests for RiverAreas asset
- `test_sides_list.py` - Tests for SidesList and BuildLists assets
- `test_standing_water_area.py` - Tests for StandingWaterAreas asset
- `test_standing_waves_area.py` - Tests for StandingWaveAreas asset
- `test_trigger_areas.py` - Tests for TriggerAreas asset
- `test_water_settings.py` - Tests for WaterSettings asset
- `test_skipped_asset.py` - Tests for SkippedAsset

#### Full Map Tests

- `test_full_maps.py` - Tests complete parsing of all `.map` files in `fixtures/maps/`

### Data Files

#### Individual Asset Data

Test data is stored in `fixtures/` with filenames matching the asset names:

- `WorldInfo`
- `BlendTileData`
- `Teams`
- `WaypointsList`
- `CameraAnimationList`
- `EnvironmentData`
- `GlobalLighting`
- `HeightMapData`
- `LibraryMapLists`
- `MPPositionList`
- `NamedCameras`
- `ObjectsList`
- `PlayerScriptsList`
- `PostEffectsChunk`
- `RiverAreas`
- `SidesList`
- `BuildLists`
- `StandingWaterAreas`
- `StandingWaveAreas`
- `TriggerAreas`

#### Full Map Files

Complete map files for integration testing are stored in `fixtures/maps/`:

- `map edain ford of bruinen.map`
- `map edain wor eaves of fangorn.map`
- `map kampa good 08.map`
- `Moria.map`

## Usage

### Running All Tests

```bash
pytest tests/
```

### Running Individual Asset Tests

```bash
# Run tests for a specific asset
pytest tests/test_teams.py

# Run a specific test function
pytest tests/test_teams.py::test_teams
```

### Running Full Map Tests

```bash
# Run all full map parsing tests
pytest tests/test_full_maps.py

# Run test for a specific map
pytest tests/test_full_maps.py::test_parse_map[Moria.map]

# Run with verbose output to see which maps are tested
pytest tests/test_full_maps.py -v
```

## How It Works

### Individual Asset Tests

Each asset test automatically loads asset bytes from the corresponding file in `fixtures/`:

```python
def test_teams():
    """Test Teams asset parsing."""
    asset_bytes = load_asset_bytes("Teams")  # Loads from fixtures/Teams
    
    if asset_bytes:
        context = create_context(asset_bytes)
        result = Teams.parse(context)
        assert result is not None
```

If a data file doesn't exist, the test is automatically skipped (the `if asset_bytes:` check ensures tests only run when data is available).

### Full Map Tests

The full map tests use pytest's parametrize feature to automatically discover and test all `.map` files in `fixtures/maps/`:

```python
@pytest.mark.parametrize("map_path", get_test_maps(), ids=lambda p: p.name)
def test_parse_map(map_path):
    """Test full parsing of individual map files."""
    map_obj = parse_map_from_path(str(map_path))
    assert map_obj is not None
    
    # Verify the map can be converted to dict (tests serialization)
    map_dict = map_obj.to_dict()
    assert isinstance(map_dict, dict)
```

Each map file gets its own individual test case, making it easy to identify which specific map fails if there's an issue.

## Shared Utilities

The `conftest.py` file contains shared test utilities:

- `load_asset_bytes(asset_name: str)` - Loads bytes from `fixtures/{asset_name}`
- `create_context(data: bytes)` - Helper function to create a ParsingContext from bytes
