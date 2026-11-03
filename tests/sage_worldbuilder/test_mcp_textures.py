"""The agent's texturing tools over a real map: painting by rectangle, area, path and terrain,
flood fill and blending, each as one undo entry, and which textures can be painted with and
without game data."""

import shutil
from pathlib import Path

import numpy as np
import pytest

from sage_worldbuilder.mcp_server import ToolError, WorldBuilderSession
from sage_worldbuilder.terrain.cells import TileLayer
from sage_worldbuilder.terrain.textures import texture_classes

FIXTURE = (
    Path(__file__).parents[1] / "sage_map" / "fixtures" / "maps" / "map edain ford of bruinen.map"
)


class GameSession(WorldBuilderSession):
    """A session that knows a game texture the map lacks, as the editor's does."""

    def _game_textures(self):
        return {"BrandNewGrass": "Grass/Rohan"}

    def _texture_cell_size(self, name):
        return 4


@pytest.fixture
def session(tmp_path):
    copy = tmp_path / "ford.map"
    shutil.copy(FIXTURE, copy)
    session = WorldBuilderSession()
    session.open_map(str(copy))
    return session


def textures(session):
    return [entry["name"] for entry in session.list_textures()["on_map"]]


def texture_at(session, x, y):
    document = session.document
    blend = document.map.blend_tile_data
    column, row = document.terrain.nearest_cell(x, y)
    tiles = document.cells(TileLayer.TILES)[row : row + 1, column : column + 1]
    return blend.textures[int(texture_classes(tiles, blend.textures)[0, 0])].name


def blended(session, x0, y0, x1, y1):
    document = session.document
    c0, r0 = document.terrain.nearest_cell(x0, y0)
    c1, r1 = document.terrain.nearest_cell(x1, y1)
    return int(np.count_nonzero(document.cells(TileLayer.BLENDS)[r0 : r1 + 1, c0 : c1 + 1]))


def test_list_textures_shares_and_no_game_data_headless(session):
    listed = session.list_textures(include_game=True)
    assert len(listed["on_map"]) >= 2
    # Each share is rounded to 0.001.
    shares = [entry["share"] for entry in listed["on_map"]]
    assert abs(sum(shares) - 1) <= 0.0005 * len(shares) + 1e-9
    assert listed["game"] is None and "no game data" in listed["note"]


def test_paint_a_region_then_undo(session):
    first, second = textures(session)[:2]
    session.mark_area(x0=400.0, y0=400.0, x1=600.0, y1=600.0)
    before = session.describe_marker("A")["terrain"]["textures"]
    result = session.paint_texture(second, region="A")
    assert result["cells"] == 21 * 21 and not result["added_to_map"]
    assert session.describe_marker("A")["terrain"]["textures"] == {second: 1.0}
    assert session.map_info()["undo"] == "Paint Texture"
    session.undo()
    assert session.describe_marker("A")["terrain"]["textures"] == before


def test_only_over_paints_just_one_texture(session):
    first, second = textures(session)[:2]
    session.paint_texture(first, 400.0, 400.0, 600.0, 600.0)
    session.paint_texture(second, 500.0, 400.0, 600.0, 600.0)
    third = textures(session)[2] if len(textures(session)) > 2 else first
    result = session.paint_texture(third, 400.0, 400.0, 600.0, 600.0, only_over=second)
    assert texture_at(session, 450.0, 500.0) == first
    assert texture_at(session, 550.0, 500.0) == third
    assert result["cells"] == 11 * 21
    with pytest.raises(ToolError, match="not on the map"):
        session.paint_texture(first, 0.0, 0.0, 10.0, 10.0, only_over="NoSuchTexture")


def test_a_texture_the_map_lacks_needs_game_data(session, tmp_path):
    with pytest.raises(ToolError, match="only the map's own textures"):
        session.paint_texture("BrandNewGrass", 0.0, 0.0, 50.0, 50.0)

    game = GameSession()
    game.open_map(session.document.path)
    count = len(game.document.map.blend_tile_data.textures)
    with pytest.raises(ToolError, match="no terrain texture"):
        game.paint_texture("Nonsense", 0.0, 0.0, 50.0, 50.0)
    result = game.paint_texture("brandnewgrass", 100.0, 100.0, 150.0, 150.0)
    assert result == {"texture": "BrandNewGrass", "cells": 36, "added_to_map": True}
    assert len(game.document.map.blend_tile_data.textures) == count + 1
    game.undo()
    assert len(game.document.map.blend_tile_data.textures) == count


def test_paint_by_terrain_follows_slope_and_height(session):
    first, second = textures(session)[:2]
    session.set_terrain_height(400.0, 400.0, 600.0, 600.0, 30.0)
    session.paint_texture(first, 400.0, 400.0, 600.0, 600.0)
    session.mark_area(x0=420.0, y0=420.0, x1=580.0, y1=580.0)
    too_low = session.paint_texture_by_terrain(second, max_height=20, region="A")
    assert too_low["cells"] == 0
    flat = session.paint_texture_by_terrain(second, max_slope=5, region="A")
    assert flat["cells"] > 0
    assert texture_at(session, 500.0, 500.0) == second
    assert session.map_info()["undo"] == "Apply Texture to Tiles"


def test_flood_fill_and_replace_all(session):
    first, second = textures(session)[:2]
    session.paint_texture(first, 400.0, 400.0, 600.0, 600.0)
    assert session.flood_fill_texture(second, 500.0, 500.0)["changed"]
    assert texture_at(session, 450.0, 450.0) == second

    game = GameSession()
    game.document = session.document
    replaced = game.flood_fill_texture("BrandNewGrass", 500.0, 500.0, replace_all=True)
    # The same cell size: the table entry is renamed in place, keeping every tile and blend.
    assert replaced == {"texture": "BrandNewGrass", "replaced": second}
    assert "BrandNewGrass" in textures(game) and second not in textures(game)


def test_blending_a_painted_region_is_one_undo_entry(session):
    first, second = textures(session)[:2]
    session.paint_texture(first, 300.0, 300.0, 700.0, 700.0)
    session.paint_texture(second, 450.0, 450.0, 550.0, 550.0)
    assert blended(session, 400.0, 400.0, 600.0, 600.0) == 0
    session.mark_area(x0=400.0, y0=400.0, x1=600.0, y1=600.0)
    result = session.blend_region("A")
    assert result["areas"] >= 2 and result["edged"] >= 1 and result["skipped"] == 0
    assert blended(session, 400.0, 400.0, 600.0, 600.0) > 0
    assert session.map_info()["undo"] == "Blend Region"
    session.undo()
    assert blended(session, 400.0, 400.0, 600.0, 600.0) == 0


def test_auto_blend_at_a_point(session):
    first, second = textures(session)[:2]
    session.paint_texture(first, 300.0, 300.0, 700.0, 700.0)
    session.paint_texture(second, 450.0, 450.0, 550.0, 550.0)
    assert session.auto_blend(500.0, 500.0)["changed"]
    assert blended(session, 400.0, 400.0, 600.0, 600.0) > 0
    with pytest.raises(ToolError, match="off the map"):
        session.auto_blend(-99999.0, 0.0)


def test_a_polygon_paints_only_inside_it(session):
    first, second = textures(session)[:2]
    session.paint_texture(first, 300.0, 300.0, 700.0, 700.0)
    # A diamond inscribed in the square: its corners stay unpainted.
    session.mark_area([[500.0, 300.0], [700.0, 500.0], [500.0, 700.0], [300.0, 500.0]])
    session.paint_texture(second, region="A")
    assert texture_at(session, 500.0, 500.0) == second
    assert texture_at(session, 320.0, 320.0) == first
    session.paint_texture_by_terrain(first, region="A")
    assert texture_at(session, 500.0, 500.0) == first
    session.paint_texture(second, 300.0, 300.0, 700.0, 700.0)
    session.paint_texture_by_terrain(first, region="A")
    assert texture_at(session, 320.0, 320.0) == second


def test_paint_path_paints_a_blended_band_as_one_undo_entry(session):
    first, second = textures(session)[:2]
    session.paint_texture(first, 200.0, 200.0, 800.0, 800.0)
    session.mark_path([[300.0, 300.0], [700.0, 300.0], [700.0, 700.0]], name="road")
    result = session.paint_path(second, "road", width=40.0)
    assert result["path"] == "ROAD" and result["length"] == 800.0 and result["cells"] > 0
    assert result["blended_areas"] >= 1
    assert texture_at(session, 500.0, 300.0) == second  # on the band
    assert texture_at(session, 700.0, 500.0) == second
    assert texture_at(session, 500.0, 500.0) == first  # inside the bend, off the band
    assert blended(session, 250.0, 250.0, 750.0, 750.0) > 0
    assert session.map_info()["undo"] == "Paint Path"
    session.undo()
    assert texture_at(session, 500.0, 300.0) == first
    assert blended(session, 250.0, 250.0, 750.0, 750.0) == 0

    unblended = session.paint_path(second, "road", blend=False)
    assert "blended_areas" not in unblended
    assert blended(session, 250.0, 250.0, 750.0, 750.0) == 0
    session.mark_area(x0=0.0, y0=0.0, x1=10.0, y1=10.0)
    with pytest.raises(ToolError, match="A is an area, not a path"):
        session.paint_path(second, "A")
    with pytest.raises(ToolError, match="ROAD is a path, not an area; paint along it"):
        session.paint_texture(second, region="road")
