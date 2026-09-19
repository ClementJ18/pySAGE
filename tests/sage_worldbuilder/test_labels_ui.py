"""Qt-level tests for the names the map views draw over the terrain: the halo that keeps them
readable, the cache behind them, and their landing on whole device pixels. Headless via the Qt
'offscreen' platform; marked `full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")

from PyQt6.QtCore import QPointF  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from sage_worldbuilder.ui import overlays  # noqa: E402
from sage_worldbuilder.ui.overlays import draw_label  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def painted(point: QPointF, text: str = "Waypoint 3", ratio: float = 2.0) -> QImage:
    image = QImage(round(240 * ratio), round(80 * ratio), QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(ratio)
    image.fill(QColor(120, 120, 120))
    painter = QPainter(image)
    draw_label(painter, point, text)
    painter.end()
    return image


def colors(image: QImage) -> list[int]:
    return [image.pixel(x, y) for y in range(image.height()) for x in range(image.width())]


def test_a_label_is_white_glyphs_in_a_dark_halo(qapp):
    image = painted(QPointF(20.0, 40.0))
    values = [QColor(pixel) for pixel in colors(image)]
    assert any(color.lightness() > 240 for color in values), "no white glyph pixels"
    assert any(color.lightness() < 40 for color in values), "no dark halo pixels"


def test_a_label_lands_on_whole_device_pixels(qapp):
    # Halfway across a device pixel at ratio 2, so the point itself is not on one.
    rough = painted(QPointF(20.3, 40.4))
    snapped = painted(QPointF(20.5, 40.5))
    assert colors(rough) == colors(snapped)


def test_a_label_is_drawn_once_per_text_font_colour_and_ratio(qapp):
    overlays._label_cache.clear()
    font = QFont()
    first = overlays._label_pixmap("Waypoint 3", font, QColor(255, 255, 255), 2.0)
    again = overlays._label_pixmap("Waypoint 3", font, QColor(255, 255, 255), 2.0)
    assert again is first
    other = overlays._label_pixmap("Waypoint 3", font, QColor(255, 255, 255), 1.0)
    assert other is not first
    assert first[0].devicePixelRatio() == 2.0
    assert other[0].devicePixelRatio() == 1.0
    overlays._label_cache.clear()


def test_an_empty_label_draws_nothing(qapp):
    blank = painted(QPointF(20.0, 40.0), text="")
    empty = QImage(blank.size(), QImage.Format.Format_ARGB32_Premultiplied)
    empty.setDevicePixelRatio(blank.devicePixelRatio())
    empty.fill(QColor(120, 120, 120))
    assert colors(blank) == colors(empty)


def test_a_centred_label_sits_about_the_point(qapp):
    image = QImage(400, 80, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(120, 120, 120))
    painter = QPainter(image)
    draw_label(painter, QPointF(200.0, 40.0), "Zone", centered=True)
    painter.end()
    painted_columns = [
        x
        for x in range(image.width())
        for y in range(image.height())
        if QColor(image.pixel(x, y)).lightness() < 40
    ]
    # Centred on the text's advance, as Qt's own AlignHCenter is, so the ink can sit a pixel or
    # two left of the point: the last glyph's advance carries its right bearing.
    middle = (min(painted_columns) + max(painted_columns)) / 2
    assert abs(middle - 200.0) <= 4.0
