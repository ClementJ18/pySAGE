"""Windows that open at the size the user last left them.

The sizes live in the editor's settings (`Settings.window_sizes`), keyed by the dialog's class
name or, for a floating panel, by `panel_key`. A dialog finds them through the widget it was
opened over: the first ancestor with a `window_sizes` mapping, the main window.
"""

from __future__ import annotations

from collections.abc import MutableMapping

from PyQt6.QtCore import QEvent, QObject, QSize
from PyQt6.QtWidgets import QDialog, QWidget

WindowSizes = MutableMapping[str, tuple[int, int]]

# Of the screen a window opens on, the most a remembered size may take, so a size kept from a
# larger monitor never opens the window hanging off a smaller one.
_SCREEN_SHARE = 0.95


def panel_key(name: str) -> str:
    """The key a floating panel's size is kept under, apart from the dialogs' class names."""
    return f"panel:{name}"


def remember_size(dialog: QDialog) -> None:
    """Open `dialog` at the size it was last closed at, and keep the size it is closed at."""
    dialog.installEventFilter(_DialogSizeFilter(dialog))


def window_sizes_for(widget: QWidget) -> WindowSizes | None:
    """The size memory of the first ancestor of `widget` that keeps one."""
    current = widget.parentWidget()
    while current is not None:
        sizes = getattr(current, "window_sizes", None)
        if isinstance(sizes, MutableMapping):
            return sizes
        current = current.parentWidget()
    return None


def fit_to_screen(widget: QWidget, size: QSize) -> QSize:
    """`size`, shrunk to fit most of the screen `widget` is on."""
    screen = widget.screen()
    if screen is None:
        return size
    available = screen.availableGeometry()
    return size.boundedTo(
        QSize(int(available.width() * _SCREEN_SHARE), int(available.height() * _SCREEN_SHARE))
    )


class _DialogSizeFilter(QObject):
    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:  # noqa: N802
        # Not spontaneous: minimising hides a dialog too, and restoring it shows it again.
        if isinstance(watched, QDialog) and event is not None and not event.spontaneous():
            if event.type() == QEvent.Type.Show:
                _restore(watched)
            elif event.type() == QEvent.Type.Hide:
                _keep(watched)
        return False


def _restore(dialog: QDialog) -> None:
    sizes = window_sizes_for(dialog)
    stored = sizes.get(type(dialog).__name__) if sizes is not None else None
    if stored is not None:
        # Before Qt centres the dialog over its parent, so it centres the size it opens at.
        dialog.resize(fit_to_screen(dialog, QSize(*stored)))


def _keep(dialog: QDialog) -> None:
    sizes = window_sizes_for(dialog)
    if sizes is not None:
        sizes[type(dialog).__name__] = (dialog.width(), dialog.height())
