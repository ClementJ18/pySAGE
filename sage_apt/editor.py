"""Browser-based editor for the XML form of an APT file: an SVG rendering of the
movieclip's stage with click-to-select elements, a properties panel that writes
placeobject / character attributes back into the XML, and save / export-to-`.apt`
endpoints. `serve()` hosts the page (loaded from the packaged `assets/editor.html`)
over a local HTTP server; `sage-apt edit <file.xml>` opens it."""

import importlib.resources
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse
from xml.dom import minidom
from xml.etree import ElementTree as ET

from sage_apt.aptfile import AptError, xml_to_apt

# The editor page ships as a package asset; read it once at import.
EDITOR_HTML = (importlib.resources.files("sage_apt") / "assets" / "editor.html").read_text("utf-8")


def reformat_xml(xml_str):
    """Round-trip through ElementTree + minidom for consistent formatting."""
    root = ET.fromstring(xml_str)
    raw = ET.tostring(root, encoding="unicode")
    return minidom.parseString(raw).toprettyxml(indent="  ", encoding="utf-8")


class _EditorHandler(BaseHTTPRequestHandler):
    """Serves the editor page plus the JSON API. `xml_path` is set per server by
    `serve` on a subclass, since http.server instantiates the handler itself."""

    xml_path: Path

    def log_message(self, *_):
        pass

    def _send(self, code, ctype, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data):
        self._send(200, "application/json", json.dumps(data))

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, "text/html; charset=utf-8", EDITOR_HTML)
        elif path == "/api/xml":
            self._json(
                {"content": self.xml_path.read_text("utf-8"), "filename": self.xml_path.name}
            )
        else:
            self._send(404, "text/plain", "Not found")

    def do_POST(self):
        path = urlparse(self.path).path
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))

        if path == "/api/xml":
            try:
                pretty = reformat_xml(body["content"])
                self.xml_path.write_bytes(pretty)
                self._json({"ok": True})
            except Exception as e:  # noqa: BLE001 — report to the browser, keep serving
                self._json({"ok": False, "msg": str(e)})

        elif path == "/api/convert":
            try:
                apt_path, _const_path = xml_to_apt(str(self.xml_path))
                self._json({"ok": True, "msg": "Exported " + apt_path.name})
            except AptError as e:
                self._json({"ok": False, "msg": str(e)})
            except Exception as e:  # noqa: BLE001 — report to the browser, keep serving
                self._json({"ok": False, "msg": str(e)})

        else:
            self._send(404, "text/plain", "Not found")


def serve(xml_path: Path, port: int = 8080, open_browser: bool = True) -> None:
    """Serve the editor for `xml_path` on localhost:`port` until interrupted."""
    handler = type("EditorHandler", (_EditorHandler,), {"xml_path": Path(xml_path)})
    server = HTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"APT editor   {url}")
    print(f"File:        {Path(xml_path).resolve()}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
