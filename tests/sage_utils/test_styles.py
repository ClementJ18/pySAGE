"""The shared Qt themes: every image a stylesheet names exists, and the dock title bar glyphs are
drawn in their theme's text colour so they stay visible on it."""

import re
from pathlib import Path

import pytest

from sage_utils.styles import DARK, DARK_STYLE, LIGHT, LIGHT_STYLE

_URL = re.compile(r'url\("([^"]+)"\)')


@pytest.mark.parametrize("style", [DARK_STYLE, LIGHT_STYLE], ids=["dark", "light"])
def test_every_stylesheet_image_exists(style):
    paths = _URL.findall(style)
    assert paths
    for path in paths:
        assert Path(path).is_file(), path


@pytest.mark.parametrize(
    ("style", "palette"), [(DARK_STYLE, DARK), (LIGHT_STYLE, LIGHT)], ids=["dark", "light"]
)
def test_dock_buttons_use_the_theme_text_colour(style, palette):
    for key in ("titlebar-close-icon", "titlebar-normal-icon"):
        match = re.search(key + r': url\("([^"]+)"\)', style)
        assert match, key
        assert f'stroke="{palette["text"]}"' in Path(match.group(1)).read_text(encoding="utf-8")


@pytest.mark.full
@pytest.mark.parametrize(
    ("style", "palette"), [(DARK_STYLE, DARK), (LIGHT_STYLE, LIGHT)], ids=["dark", "light"]
)
def test_a_checked_radio_button_shows_its_dot(style, palette):
    import os  # noqa: PLC0415

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    qt_gui = pytest.importorskip("PyQt6.QtGui")
    qt_widgets = pytest.importorskip("PyQt6.QtWidgets")
    app = qt_widgets.QApplication.instance() or qt_widgets.QApplication([])
    previous = app.styleSheet()
    app.setStyleSheet(style)
    try:
        centres = []
        for checked in (True, False):
            button = qt_widgets.QRadioButton("Choice")
            button.setChecked(checked)
            button.resize(button.sizeHint())
            image = qt_gui.QImage(button.size(), qt_gui.QImage.Format.Format_ARGB32)
            button.render(image)
            option = qt_widgets.QStyleOptionButton()
            button.initStyleOption(option)
            rect = button.style().subElementRect(
                qt_widgets.QStyle.SubElement.SE_RadioButtonIndicator, option, button
            )
            centres.append(qt_gui.QColor(image.pixel(rect.center())).name())
    finally:
        app.setStyleSheet(previous)
    assert centres == [palette["accent"], palette["surface"]]
