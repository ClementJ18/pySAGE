"""Tools > Allow Agent Connections: the editor's end of the MCP bridge.

`AgentListener` accepts the MCP server's connections on localhost and answers each request line
on the GUI thread, so a tool touches the document exactly as a menu command would: the views
update, and the edit is one entry on the undo stack the user sees. `EditorSession` is the tool
session over the window's open map, with what only the editor can do - move its view, capture it -
and with opening and saving routed through the window.
"""

from __future__ import annotations

import base64
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QBuffer, QIODevice, QObject, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtNetwork import QHostAddress, QTcpServer, QTcpSocket

from sage_utils.config import write_json
from sage_worldbuilder.castles import is_base_path
from sage_worldbuilder.document import MapDocument
from sage_worldbuilder.mcp_server.bridge import connection_file, dispatch
from sage_worldbuilder.mcp_server.tools import ToolError, WorldBuilderSession
from sage_worldbuilder.settings import APP, RecentMap
from sage_worldbuilder.texture_colors import texture_palette

if TYPE_CHECKING:
    from sage_worldbuilder.ui.map_view import MapView
    from sage_worldbuilder.ui.map_view_3d import MapView3D
    from sage_worldbuilder.ui.window import MainWindow

__all__ = ["AgentListener", "EditorSession"]

# A request line longer than this is refused and its connection dropped.
_MAX_LINE = 1 << 20
# A marker's picture shows this much of its surroundings on each side, as a share of its size.
_CROP_MARGIN = 0.1


class EditorSession(WorldBuilderSession):
    """The tool session over the editor's open map."""

    def __init__(self, window: MainWindow) -> None:
        self._window = window

    @property
    def document(self) -> MapDocument | None:  # type: ignore[override]
        return self._window.document

    def _idle(self) -> None:
        if self._window._busy:
            raise ToolError("the editor is busy (opening or saving); try again shortly")

    def open_map(self, path: str) -> dict[str, Any]:
        self._idle()
        current = self.document
        if current is not None and current.dirty:
            raise ToolError(
                f"{current.title} has unsaved changes: save it with save_map, or ask the user to "
                "save or discard them in the editor"
            )
        try:
            document = MapDocument.open(path)
        except OSError as error:
            raise ToolError(f"cannot open {path}: {error}") from error
        self._window._opened(document, RecentMap("file", str(Path(path))))
        return self.map_info()

    def save_map(self, path: str | None = None) -> dict[str, Any]:
        self._idle()
        document = self._doc
        target = Path(path) if path is not None else document.path
        if target is not None and is_base_path(target):
            raise ToolError(
                "save a base (.bse) from the editor, which rebuilds its castle templates"
            )
        result = super().save_map(path)
        self._window._remember(RecentMap("file", result["saved"]))
        self._window._refresh()
        return result

    def _game_textures(self) -> dict[str, str] | None:
        game = self._window.game
        if game is None:
            return None
        return {
            name: f"{kind}/{region}" if region else kind
            for kind, regions in texture_palette(game).items()
            for region, names in regions.items()
            for name in names
        }

    def _texture_cell_size(self, name: str) -> int | None:
        return self._window.texture_cell_size(name)

    def view_at(self, x: float, y: float, zoom: float = 1.0) -> dict[str, Any]:
        if self.document is None:
            raise ToolError("no map is open; call open_map first")
        self._window.active_view().zoom_to(x, y, zoom)
        return {"x": x, "y": y}

    def screenshot(self, max_width: int = 1280, marker: str | None = None) -> dict[str, Any]:
        view = self._window.active_view()
        crop = None
        if marker is not None:
            bounds = self._marker_bounds(marker)
            crop = _screen_rect(view, bounds)
            if crop is None:
                view.fit_rect(*bounds)
                crop = _screen_rect(view, bounds)
        # The 3D view's own framebuffer, when there is one to read (not without a GL context).
        grab = getattr(view, "grabFramebuffer", None)
        image = grab() if grab is not None else None
        if image is None or image.isNull():
            image = view.grab().toImage()
        if crop is not None and not image.isNull():
            # The grab is in device pixels, the projection in logical ones.
            ratio = image.width() / max(view.width(), 1)
            image = image.copy(
                QRect(
                    round(crop.x() * ratio),
                    round(crop.y() * ratio),
                    round(crop.width() * ratio),
                    round(crop.height() * ratio),
                )
            )
        if image.width() > max_width > 0:
            image = image.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if image.isNull() or not image.save(buffer, "PNG"):
            raise ToolError("the view could not be captured")
        return {
            "format": "png",
            "width": image.width(),
            "height": image.height(),
            "data": base64.b64encode(bytes(buffer.data().data())).decode("ascii"),
        }


def _screen_rect(view: MapView | MapView3D, bounds: tuple[float, ...]) -> QRectF | None:
    """Where a world rectangle shows in the view, with a margin; None unless all of it is on
    screen."""
    x0, y0, x1, y1 = bounds
    corners = [view._to_screen(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    if any(corner is None for corner in corners):
        return None
    xs = [corner.x() for corner in corners if corner is not None]
    ys = [corner.y() for corner in corners if corner is not None]
    shown = QRectF(0, 0, view.width(), view.height())
    rect = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    if rect.isEmpty() or not shown.contains(rect):
        return None
    margin = max(rect.width(), rect.height()) * _CROP_MARGIN
    return rect.adjusted(-margin, -margin, margin, margin).intersected(shown)


class AgentListener(QObject):
    """Listens on localhost while started; publishes its port and token in the connection file."""

    connections_changed = pyqtSignal(int)

    def __init__(self, session: WorldBuilderSession, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.token = ""
        self._server = QTcpServer(self)
        self._server.newConnection.connect(self._accept)
        self._sockets: dict[QTcpSocket, bytearray] = {}

    @property
    def listening(self) -> bool:
        return self._server.isListening()

    @property
    def port(self) -> int:
        return self._server.serverPort()

    def start(self) -> bool:
        if self.listening:
            return True
        if not self._server.listen(QHostAddress(QHostAddress.SpecialAddress.LocalHost), 0):
            return False
        self.token = secrets.token_urlsafe(32)
        if not write_json(APP, connection_file().name, {"port": self.port, "token": self.token}):
            self._server.close()
            return False
        return True

    def stop(self) -> None:
        if not self.listening:
            return
        self._server.close()
        for socket in list(self._sockets):
            socket.disconnectFromHost()
        self._sockets.clear()
        connection_file().unlink(missing_ok=True)
        self.connections_changed.emit(0)

    def _accept(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            self._sockets[socket] = bytearray()
            socket.readyRead.connect(lambda s=socket: self._read(s))
            socket.disconnected.connect(lambda s=socket: self._drop(s))
        self.connections_changed.emit(len(self._sockets))

    def _drop(self, socket: QTcpSocket) -> None:
        if self._sockets.pop(socket, None) is not None:
            socket.deleteLater()
            self.connections_changed.emit(len(self._sockets))

    def _read(self, socket: QTcpSocket) -> None:
        pending = self._sockets.get(socket)
        if pending is None:
            return
        pending += bytes(socket.readAll().data())
        while (end := pending.find(b"\n")) >= 0:
            line = bytes(pending[:end])
            del pending[: end + 1]
            socket.write(dispatch(self.session, self.token, line))
        if len(pending) > _MAX_LINE:
            socket.disconnectFromHost()
