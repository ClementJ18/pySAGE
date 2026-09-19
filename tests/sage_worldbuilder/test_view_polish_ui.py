"""Waypoint link arrowheads, floating panels sized to their contents, panels dragged out
and grouped back together, undocked panels raised with the window, Lock Layout holding them
where they are, and the themed marks on checked tool buttons and menu items. Qt parts headless
via 'offscreen'; marked `full`."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless; must precede the Qt import

import pytest

pytestmark = pytest.mark.full

pytest.importorskip("PyQt6", reason="the [worldbuilder] extra (PyQt6) is not installed")
pytest.importorskip("numpy", reason="the [worldbuilder] extra (numpy) is not installed")

from PyQt6.QtCore import QEvent, QPoint, QPointF, QSize, Qt  # noqa: E402
from PyQt6.QtGui import QMouseEvent  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication,
    QDockWidget,
    QMainWindow,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from sage_utils.styles import DARK_STYLE, LIGHT_STYLE  # noqa: E402
from sage_worldbuilder.settings import Settings  # noqa: E402
from sage_worldbuilder.ui.map_view import arrow_head  # noqa: E402
from sage_worldbuilder.ui.window import (  # noqa: E402
    MainWindow,
    fit_floating_dock,
    floating_window,
)


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def test_arrow_head_points_at_the_end_short_of_the_gap():
    head = arrow_head((0.0, 0.0), (100.0, 0.0), gap=5.0)
    assert head[0] == (95.0, 0.0)
    assert head[1] == pytest.approx((86.0, 4.0))
    assert head[2] == pytest.approx((86.0, -4.0))
    upward = arrow_head((0.0, 100.0), (0.0, 0.0))
    assert upward[0] == (0.0, 0.0)
    assert upward[1][1] == pytest.approx(9.0)
    assert arrow_head((0.0, 0.0), (10.0, 0.0), gap=5.0) is None


def test_floating_panels_fit_their_contents_within_the_screen(qapp):
    window = QMainWindow()
    try:
        dock = QDockWidget("Panel", window)
        tree = QTreeWidget()
        tree.setMinimumSize(420, 330)
        dock.setWidget(tree)
        window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        window.resize(1200, 900)
        window.show()
        qapp.processEvents()
        dock.setFloating(True)
        dock.resize(900, 50)
        fit_floating_dock(dock)
        assert dock.width() >= 420 and dock.height() >= 330
        assert dock.width() < 900
        available = dock.screen().availableGeometry()
        assert dock.width() <= available.width() * 0.8 + 1

        tree.setMinimumSize(QSize(20, 20))
        dock.resize(900, 900)
        fit_floating_dock(dock)
        assert (dock.width(), dock.height()) >= (280, 200)
    finally:
        window.close()


@pytest.mark.parametrize("style", [DARK_STYLE, LIGHT_STYLE], ids=["dark", "light"])
def test_checked_tools_and_menu_items_are_marked_by_the_theme(style):
    assert "QToolButton:checked" in style
    assert "QMenu::indicator:checked" in style


def test_panels_can_be_dragged_out_and_grouped_into_one_window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr("sage_worldbuilder.gamedata.user_data_dir", lambda game: tmp_path)
    window = MainWindow(Settings(install=str(install)), load_game_data=False)
    try:
        options = window.dockOptions()
        assert options & QMainWindow.DockOption.GroupedDragging
        assert options & QMainWindow.DockOption.AllowTabbedDocks
        features = QDockWidget.DockWidgetFeature
        for dock in (window.camera_dock, window.palette_dock):
            assert dock.features() & features.DockWidgetFloatable
            assert dock.features() & features.DockWidgetMovable
    finally:
        window.close()


def test_a_grouped_panel_is_sized_through_the_window_it_shares(qapp):
    window = QMainWindow()
    group = QWidget()
    try:
        dock = QDockWidget("Panel", window)
        tree = QTreeWidget()
        tree.setMinimumSize(420, 330)
        dock.setWidget(tree)
        window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        window.resize(1200, 900)
        window.show()
        qapp.processEvents()
        assert floating_window(dock) is None

        # Stands in for the window Qt gives a group of floating panels.
        layout = QVBoxLayout(group)
        layout.addWidget(dock)
        group.resize(900, 60)
        group.show()
        qapp.processEvents()
        assert floating_window(dock) is group
        fit_floating_dock(dock)
        assert group.width() >= 420 and group.height() >= 330
        assert dock.size() == dock.size().boundedTo(group.size())
    finally:
        group.close()
        window.close()


def test_focusing_the_window_raises_the_undocked_panels(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    install = tmp_path / "install"
    install.mkdir()
    monkeypatch.setattr("sage_worldbuilder.gamedata.user_data_dir", lambda game: tmp_path)
    window = MainWindow(Settings(install=str(install)), load_game_data=False)
    group = QWidget()
    try:
        window.show()
        qapp.processEvents()
        raised: list[str] = []

        def records(name, widget):
            widget.raise_ = lambda: raised.append(name)

        window.palette_dock.setFloating(True)
        qapp.processEvents()
        # Two panels sharing a window of Qt's own, as grouped dragging makes.
        layout = QVBoxLayout(group)
        for dock in (window.camera_dock, window.layers_dock):
            layout.addWidget(dock)
        group.show()
        qapp.processEvents()

        records("palette", window.palette_dock)
        records("group", group)
        records("docked", window.object_dock)
        window.raise_floating_docks()
        # The docked panel is left alone, and the shared window comes up once, not once a panel.
        assert sorted(raised) == ["group", "palette"]
    finally:
        group.close()
        window.close()


def editor(tmp_path, monkeypatch, settings=None):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    install = tmp_path / "install"
    install.mkdir(exist_ok=True)
    monkeypatch.setattr("sage_worldbuilder.gamedata.user_data_dir", lambda game: tmp_path)
    return MainWindow(settings or Settings(install=str(install)), load_game_data=False)


def drag_title_bar(qapp, dock):
    """Drag a panel by its title bar: the gesture that pulls it out of its dock and drops it
    into whatever it lands on."""
    start = QPoint(dock.width() // 2, max(dock.widget().geometry().top() // 2, 4))
    QTest.mousePress(dock, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    for step in (10, 40, 120, 260):
        QTest.mouseMove(dock, start + QPoint(-step, step))
        qapp.processEvents()
    QTest.mouseRelease(
        dock, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + QPoint(-260, 260)
    )
    qapp.processEvents()


def test_a_panel_without_the_movable_feature_cannot_be_dragged_out(qapp):
    """What Lock Layout rests on: Qt starts no dock drag at all, so there is nothing to merge."""
    window = QMainWindow()
    try:
        window.setDockOptions(
            QMainWindow.DockOption.AnimatedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.GroupedDragging
        )
        dock = QDockWidget("Panel", window)
        dock.setWidget(QTreeWidget())
        window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        window.resize(900, 700)
        window.show()
        qapp.processEvents()

        drag_title_bar(qapp, dock)
        assert dock.isFloating()

        dock.setFloating(False)
        qapp.processEvents()
        features = QDockWidget.DockWidgetFeature
        dock.setFeatures(features.DockWidgetFloatable | features.DockWidgetClosable)
        drag_title_bar(qapp, dock)
        assert not dock.isFloating()
    finally:
        window.close()


def test_lock_layout_takes_every_drop_target_away(qapp, tmp_path, monkeypatch):
    window = editor(tmp_path, monkeypatch)
    try:
        window.show()
        qapp.processEvents()
        dock = window.palette_dock
        features = QDockWidget.DockWidgetFeature
        options = QMainWindow.DockOption

        window.lock_layout_action.setChecked(True)
        assert window.settings.lock_layout
        for panel in (dock, window.camera_dock):
            assert not panel.features() & features.DockWidgetMovable
            # The title bar buttons are untouched: a locked panel still floats and closes.
            assert panel.features() & features.DockWidgetFloatable
            assert panel.features() & features.DockWidgetClosable
            assert panel.allowedAreas() == Qt.DockWidgetArea.NoDockWidgetArea
        assert not window.dockOptions() & options.GroupedDragging
        assert not window.dockOptions() & options.AllowTabbedDocks
        # Panels already tabbed together stay that way; the lock only stops new ones.
        assert window.tabifiedDockWidgets(window.map_dock)

        window.lock_layout_action.setChecked(False)
        assert not window.settings.lock_layout
        for panel in (dock, window.camera_dock):
            assert panel.features() & features.DockWidgetMovable
            assert panel.allowedAreas() == Qt.DockWidgetArea.AllDockWidgetAreas
        assert window.dockOptions() & options.GroupedDragging
        assert window.dockOptions() & options.AllowTabbedDocks
    finally:
        window.close()


class QDockWidgetGroupWindow(QWidget):
    """Stands in for the window Qt makes when floating panels are dropped together: PyQt names
    the class after this one, which is how the editor recognises Qt's."""

    def __init__(self, parent):
        super().__init__(parent, Qt.WindowType.Tool)
        self.presses = 0

    def event(self, event):
        if event.type() == QEvent.Type.NonClientAreaMouseButtonPress:
            self.presses += 1
        return super().event(event)


def test_a_locked_group_window_cannot_start_a_dock_drag(qapp, tmp_path, monkeypatch):
    """Qt lets a window of several panels dock anywhere, whatever their allowed areas; the lock
    keeps its title bar from starting that drag."""
    window = editor(tmp_path, monkeypatch)
    group = QDockWidgetGroupWindow(window)
    try:
        group.show()
        qapp.processEvents()

        def press():
            event = QMouseEvent(
                QEvent.Type.NonClientAreaMouseButtonPress,
                QPointF(10, -10),
                QPointF(group.mapToGlobal(QPoint(10, -10))),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            QApplication.sendEvent(group, event)

        press()
        assert group.presses == 1
        window.lock_layout_action.setChecked(True)
        press()
        assert group.presses == 1
        window.lock_layout_action.setChecked(False)
        press()
        assert group.presses == 2
    finally:
        group.close()
        window.close()


def test_the_lock_is_remembered_for_the_next_run(qapp, tmp_path, monkeypatch):
    window = editor(tmp_path, monkeypatch)
    try:
        window.lock_layout_action.setChecked(True)
    finally:
        window.close()
    saved = Settings.load()
    assert saved.lock_layout is True

    again = editor(tmp_path, monkeypatch, saved)
    try:
        assert again.lock_layout_action.isChecked()
        movable = QDockWidget.DockWidgetFeature.DockWidgetMovable
        assert not again.palette_dock.features() & movable
        assert again.palette_dock.allowedAreas() == Qt.DockWidgetArea.NoDockWidgetArea
    finally:
        again.close()
