"""Script sentences drawn with their arguments as links, as WorldBuilder shows them, so it is
plain which words are the arguments and a click on one edits it."""

from __future__ import annotations

import html

from PyQt6.QtCore import QEvent, QModelIndex, QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPalette, QTextDocument
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from sage_map.assets.player_scripts import ScriptDerived
from sage_worldbuilder.scripting import sentence_parts
from sage_worldbuilder.templates import TemplateKind

__all__ = ["HTML_ROLE", "SentenceDelegate", "argument_at", "link_color", "sentence_html"]

ARGUMENT_LINK = "argument:"
# The item data role a list row keeps its sentence markup under.
HTML_ROLE = Qt.ItemDataRole.UserRole + 1
# How light a link has to be to read on a dark background, and how dark a background has to be to
# count as one.
LINK_LIGHTNESS = 175
DARK_BACKGROUND = 128


def link_color(palette: QPalette, background: QColor) -> QColor:
    """The colour to draw a link in over `background`. A dark theme usually keeps the deep blue
    the light theme uses, which all but disappears on a dark row, so lighten it there."""
    link = palette.color(QPalette.ColorRole.Link)
    if background.lightness() >= DARK_BACKGROUND or link.lightness() >= LINK_LIGHTNESS:
        return link
    lighter = QColor(link)
    lighter.setHsl(link.hslHue(), link.hslSaturation(), LINK_LIGHTNESS, link.alpha())
    return lighter


def sentence_html(item: ScriptDerived, kind: TemplateKind) -> str:
    """The sentence as rich text, each argument a link to `argument:<index>`."""
    pieces = []
    for text, index in sentence_parts(item, kind):
        escaped = html.escape(text)
        pieces.append(
            escaped if index is None else f'<a href="{ARGUMENT_LINK}{index}">{escaped}</a>'
        )
    return "".join(pieces)


def argument_at(anchor: str | None) -> int | None:
    """The argument index a link names, or `None` for anything else."""
    if not anchor or not anchor.startswith(ARGUMENT_LINK):
        return None
    try:
        return int(anchor.removeprefix(ARGUMENT_LINK))
    except ValueError:
        return None


class SentenceDelegate(QStyledItemDelegate):
    """Draws rows that carry markup under `HTML_ROLE` as rich text, and reports a click on an
    argument link as `argument_clicked(row, argument index)`. Other rows draw as plain text."""

    argument_clicked = pyqtSignal(int, int)

    def _document(self, option: QStyleOptionViewItem, markup: str) -> QTextDocument:
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        palette = option.palette
        text = palette.color(
            QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
        )
        link = text if selected else link_color(palette, palette.color(QPalette.ColorRole.Base))
        document = QTextDocument()
        document.setDocumentMargin(2)
        document.setDefaultFont(option.font)
        document.setDefaultStyleSheet(
            f"a {{ color: {link.name()}; text-decoration: underline; }}"
            f" body {{ color: {text.name()}; }}"
        )
        document.setHtml(f"<body>{markup}</body>")
        return document

    def paint(
        self, painter: QPainter | None, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        markup = index.data(HTML_ROLE)
        if painter is None or not isinstance(markup, str):
            super().paint(painter, option, index)
            return
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        styled.text = ""
        style = styled.widget.style() if styled.widget is not None else QApplication.style()
        if style is not None:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, styled.widget)
        document = self._document(styled, markup)
        painter.save()
        painter.translate(QPointF(styled.rect.topLeft()))
        document.drawContents(painter, QRectF(0, 0, styled.rect.width(), styled.rect.height()))
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        markup = index.data(HTML_ROLE)
        if not isinstance(markup, str):
            return super().sizeHint(option, index)
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        size = self._document(styled, markup).size()
        return QSize(int(size.width()) + 4, int(size.height()))

    def anchor_at(
        self, option: QStyleOptionViewItem, index: QModelIndex, point: QPointF
    ) -> str | None:
        """The link under `point`, given relative to the row's top-left corner."""
        markup = index.data(HTML_ROLE)
        if not isinstance(markup, str):
            return None
        # The layout belongs to the document, so the document has to outlive the lookup.
        document = self._document(option, markup)
        layout = document.documentLayout()
        anchor = layout.anchorAt(point) if layout is not None else ""
        return anchor or None

    def editorEvent(  # noqa: N802 - Qt override
        self,
        event: QEvent | None,
        model: object,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> bool:
        if isinstance(event, QMouseEvent):
            point = event.position() - QPointF(option.rect.topLeft())
            argument = argument_at(self.anchor_at(option, index, point))
            view = option.widget
            if event.type() == QEvent.Type.MouseMove and isinstance(view, QAbstractItemView):
                viewport = view.viewport()
                if viewport is not None:
                    if argument is None:
                        viewport.unsetCursor()
                    else:
                        viewport.setCursor(Qt.CursorShape.PointingHandCursor)
            if (
                event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
                and argument is not None
            ):
                self.argument_clicked.emit(index.row(), argument)
                return True
        return super().editorEvent(event, model, option, index)  # type: ignore[arg-type]
