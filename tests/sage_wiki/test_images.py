"""Tests for the headless portrait-image helpers (sage_wiki.images)."""

import io
from types import SimpleNamespace

import pytest
from PIL import Image

import sage_ini.model.definitions  # noqa: F401  (register classes, incl. MappedImage)
from sage_ini.model.game import Game
from sage_ini.parser.blockparser import parse
from sage_utils.textures import TextureSource
from sage_utils.views import flatten_button_images
from sage_wiki.images import (
    command_icon_names,
    command_icon_rows,
    command_set_icon_rows,
    filename_from_value,
    icon_filename,
    object_command_icon_rows,
    portrait_filename,
    render_icon_png,
    render_portrait_png,
    rewrite_image_value,
)
from sage_wiki.infobox import parse_infobox

pytestmark = pytest.mark.full


def _mapped_image(body: str):
    """A parsed MappedImage definition from its block body (as in test_textures)."""
    game = Game()
    result = parse(f"MappedImage TestImg\n{body}End\n", file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    return game.mappedimages["TestImg"]


def test_portrait_filename_uses_internal_object_id():
    obj = SimpleNamespace(name="GondorRangerHorde")
    assert portrait_filename(obj) == "GondorRangerHorde.png"


def test_filename_from_value_handles_each_form():
    assert filename_from_value(None) is None
    assert filename_from_value("  ") is None
    assert filename_from_value("Old.png") == "Old.png"
    assert filename_from_value("File:Old.png") == "Old.png"
    assert filename_from_value("Image:Old.png") == "Old.png"
    assert filename_from_value("[[File:Old.png|thumb|200px]]") == "Old.png"
    # A <gallery> lists one "Filename|caption" per line; the first entry is the portrait.
    gallery = "<gallery>\nMordor Ram Portrait.PNG|Portrait\nBattering Ram.jpg|In Game</gallery>"
    assert filename_from_value(gallery) == "Mordor Ram Portrait.PNG"
    # An opening tag with attributes and a File: prefix on the first entry both resolve.
    attrs = '<gallery widths="200">\nFile:Hero Portrait.png|Portrait\n</gallery>'
    assert filename_from_value(attrs) == "Hero Portrait.png"


def test_rewrite_image_value_preserves_style():
    assert rewrite_image_value(None, "New.png") == "New.png"
    assert rewrite_image_value("Old.png", "New.png") == "New.png"
    assert rewrite_image_value("File:Old.png", "New.png") == "File:New.png"
    assert (
        rewrite_image_value("[[File:Old.png|thumb|200px]]", "New.png")
        == "[[File:New.png|thumb|200px]]"
    )


def test_rewrite_image_value_into_parsed_infobox():
    # The value the uploader writes round-trips through the infobox parser unchanged.
    infobox = parse_infobox("{{Infobox unit\n|image = Old.png\n|cost = 300\n}}")
    assert infobox is not None
    infobox.set("image", rewrite_image_value(infobox.get("image"), "GondorRangerHorde.png"))
    assert infobox.get("image") == "GondorRangerHorde.png"


def test_render_portrait_png_crops_select_portrait(tmp_path):
    # SelectPortrait -> a MappedImage -> cropped to PNG bytes with a PNG signature.
    Image.new("RGBA", (64, 64), (0, 128, 255, 255)).save(_dds(tmp_path, "te", "Tex"), format="DDS")
    source = TextureSource([("folder", str(tmp_path))])
    image = _mapped_image(
        "Texture = Tex.tga\n"
        "TextureWidth = 64\n"
        "TextureHeight = 64\n"
        "Coords = Left:0 Top:0 Right:32 Bottom:32\n"
    )
    obj = SimpleNamespace(name="Unit", SelectPortrait=image, ButtonImage=None)
    png = render_portrait_png(source, obj)
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic
    assert Image.open(io.BytesIO(png)).size == (32, 32)


def test_render_portrait_png_none_without_image(tmp_path):
    source = TextureSource([("folder", str(tmp_path))])
    obj = SimpleNamespace(name="Unit", SelectPortrait=None, ButtonImage=None)
    assert render_portrait_png(source, obj) is None


def test_icon_filename_uses_button_name():
    assert icon_filename("Command_ConstructGondorFarm") == "Command_ConstructGondorFarm.png"


def test_flatten_button_images_expands_and_keeps_empty():
    entries = [
        {"name": "A", "text": "Alpha", "image": []},  # no icon -> one row, image None
        {"name": "B", "text": "Beta", "image": ["img"]},  # single -> plain name
        {"name": "C", "text": "Gamma", "image": ["i1", "i2"]},  # multiple -> suffixed
        # An unresolved ButtonImage: no croppable image, but a known image name —
        # the row is named after the image, not the button.
        {"name": "D", "text": "Delta", "image": [], "image_names": ["Img_D"]},
    ]
    rows = flatten_button_images(entries)
    assert [(r["name"], r["image"]) for r in rows] == [
        ("A", None),
        ("B", "img"),
        ("C_1", "i1"),
        ("C_2", "i2"),
        ("Img_D", None),
    ]
    assert rows[2]["text"] == "Gamma (1)"  # multi-image rows carry the index


def test_render_icon_png_crops_and_handles_missing(tmp_path):
    Image.new("RGBA", (32, 32), (10, 20, 30, 255)).save(_dds(tmp_path, "te", "Tex"), format="DDS")
    source = TextureSource([("folder", str(tmp_path))])
    image = _mapped_image(
        "Texture = Tex.tga\nTextureWidth = 32\nTextureHeight = 32\n"
        "Coords = Left:0 Top:0 Right:16 Bottom:16\n"
    )
    png = render_icon_png(source, image)
    assert png is not None and png[:8] == b"\x89PNG\r\n\x1a\n"
    assert Image.open(io.BytesIO(png)).size == (16, 16)
    assert render_icon_png(source, None) is None  # a button with no icon


COMMAND_ICON_FIXTURE = """
Object IconUnit
  CommandSet = IconSet
End
MappedImage Icon_Build
  Texture = INGameUI.tga
  Coords = Left:0 Top:0 Right:60 Bottom:60
End
CommandButton Command_Build
  Command = UNIT_BUILD
  ButtonImage = Icon_Build
End
CommandButton Command_NoIcon
  Command = OBJECT_UPGRADE
End
CommandSet IconSet
  1 = Command_Build
  2 = Command_NoIcon
End
"""


def test_command_icon_rows_names_by_mapped_image():
    game = Game()
    result = parse(COMMAND_ICON_FIXTURE, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    rows = command_icon_rows(game, game.objects["IconUnit"])
    # The icon-bearing button is named after its MappedImage, not the button.
    build = next(r for r in rows if r["image"] is not None)
    assert build["name"] == "Icon_Build"
    assert icon_filename(build["name"]) == "Icon_Build.png"
    # A button with no icon keeps the button name (no MappedImage to borrow from).
    noicon = next(r for r in rows if r["image"] is None)
    assert noicon["name"] == "Command_NoIcon"


def test_command_icon_names_maps_buttons_to_upload_filenames():
    # The ability autofill joins a button to the file its icon uploads as.
    game = Game()
    result = parse(COMMAND_ICON_FIXTURE, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    names = command_icon_names(game, game.commandsets["IconSet"])
    # The icon-bearing button maps to its MappedImage name (matching the uploader);
    # the icon-less button is left out (no file the uploader can produce).
    assert names == {"Command_Build": "Icon_Build.png"}


UNLOADED_ICON_FIXTURE = """
Object IconUnit
  CommandSet = IconSet
End
CommandButton Command_Brute
  Command = SPECIAL_POWER
  ButtonImage = DUZerkBeserkGangIcon
End
CommandSet IconSet
  1 = Command_Brute
End
"""


def test_unresolved_button_image_keeps_its_name():
    # A ButtonImage whose MappedImage definition wasn't loaded (it lives in an art
    # archive) must still surface the icon's real name, not the command button's.
    game = Game()
    result = parse(UNLOADED_ICON_FIXTURE, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    command_set = game.commandsets["IconSet"]

    # The page-draft autofill points the ability at the icon's real file name.
    assert command_icon_names(game, command_set) == {"Command_Brute": "DUZerkBeserkGangIcon.png"}

    # The extract list names the (uncroppable) row after the image, not the button.
    row = command_set_icon_rows(game, command_set)[0]
    assert row["name"] == "DUZerkBeserkGangIcon"
    assert row["image"] is None  # nothing to crop — the definition isn't loaded


def test_command_set_icon_rows_lists_a_chosen_set():
    # A command set can be listed directly (the searchbox path), without an object.
    game = Game()
    result = parse(COMMAND_ICON_FIXTURE, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    rows = command_set_icon_rows(game, game.commandsets["IconSet"])
    assert next(r for r in rows if r["image"] is not None)["name"] == "Icon_Build"


def test_object_command_icon_rows_reports_set_name():
    # The auto path returns the resolved command set's name (to fill the searchbox).
    game = Game()
    result = parse(COMMAND_ICON_FIXTURE, file="t.ini")
    assert not result.diagnostics
    game.load_document(result.document)
    set_name, rows = object_command_icon_rows(game, game.objects["IconUnit"])
    assert set_name == "IconSet"
    assert next(r for r in rows if r["image"] is not None)["name"] == "Icon_Build"


def test_render_portrait_png_composites_when_background_given(tmp_path):
    Image.new("RGBA", (32, 32), (0, 200, 0, 255)).save(_dds(tmp_path, "te", "Tex"), format="DDS")
    source = TextureSource([("folder", str(tmp_path))])
    image = _mapped_image("Texture = Tex.tga\n")
    obj = SimpleNamespace(name="Unit", SelectPortrait=image, ButtonImage=None)
    background = Image.new("RGBA", (192, 197), (50, 40, 30, 255))
    png = render_portrait_png(source, obj, background)
    assert png is not None
    assert Image.open(io.BytesIO(png)).size == (192, 197)  # output is background-sized


def _dds(base, two, stem):
    path = base / "art" / "compiledtextures" / two / f"{stem}.dds"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
