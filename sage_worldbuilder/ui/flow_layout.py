"""A layout that packs its widgets left to right and wraps onto a new row when the next one
would not fit, growing taller instead of hiding what does not fit on one line.

`QToolBar` has no such layout of its own: past a certain width it hides overflow behind a `»`
button instead of wrapping, which is exactly wrong for a toolbar whose row count should follow
the window's width. `FlowLayout` is the classic Qt "Flow Layout" example, adapted for a container
that only understands ordinary width/height sizing; `FlowWidget` is the widget that hosts it and
solves the other half of the problem, making its own height follow from a given width even inside
a parent (a toolbar) whose layout does not propagate Qt's height-for-width protocol.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtGui import QResizeEvent
from PyQt6.QtWidgets import QLayout, QLayoutItem, QSizePolicy, QWidget


class FlowLayout(QLayout):
    """Lays its items out left to right, wrapping to a new row whenever the next item would run
    past the layout's width. `heightForWidth` reports how tall that wrapping makes the layout for
    a given width, and `minimumSize` is deliberately just the largest single item - not the sum of
    all of them - so a container built around this layout can be as narrow as one button."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 4) -> None:
        super().__init__(parent)
        self.setSpacing(spacing)
        self._items: list[QLayoutItem] = []

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        size += QSize(left + right, top + bottom)
        return size

    def _layout(self, rect: QRect, *, apply: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        area = rect.adjusted(left, top, -right, -bottom)
        x, y = area.x(), area.y()
        spacing = self.spacing()
        line_height = 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + spacing
            if next_x - spacing > area.right() and line_height > 0:
                x = area.x()
                y += line_height + spacing
                next_x = x + hint.width() + spacing
                line_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + bottom


class FlowWidget(QWidget):
    """A widget whose sole job is hosting a `FlowLayout` inside a container - a `QToolBar` - whose
    own layout sizes its children by plain width/height and never asks a child what height a given
    width would need. Qt's normal height-for-width protocol never reaches this widget from such a
    parent, so it fixes its own height by hand on every resize instead of relying on that protocol
    to propagate; the guard against re-fixing to the same height is what keeps that from recursing
    forever, since `setFixedHeight` itself triggers another resize event."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 4) -> None:
        super().__init__(parent)
        self.flow = FlowLayout(self, spacing=spacing)
        self.setLayout(self.flow)
        policy = self.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
        policy.setVerticalPolicy(QSizePolicy.Policy.Fixed)
        self.setSizePolicy(policy)
        self._wrapped_height = -1

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self.flow.heightForWidth(width)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._sync_height(event.size().width())

    def _sync_height(self, width: int) -> None:
        height = max(self.heightForWidth(width), 1)
        if height == self._wrapped_height:
            return
        self._wrapped_height = height
        self.setFixedHeight(height)
