"""A tiny stdlib HTTP server for the faction-explorer web UI.

Serves the static files in `sage_mods/edain/ui/` plus the built graph as `/graph.json`, so the
page can fetch it on load. No third-party dependency - `python -m sage_mods.edain serve …` opens
a browser onto a live, navigable view of one faction's ownership graph.
"""

from __future__ import annotations

import http.server
import json
import webbrowser
from functools import partial
from pathlib import Path

UI_DIR = Path(__file__).parent / "ui"


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Serves the bundled UI directory, with `/graph.json` answered from the in-memory graph."""

    def __init__(self, *args, graph_bytes: bytes = b"", **kwargs):
        self._graph_bytes = graph_bytes
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def do_GET(self) -> None:  # noqa: N802 - http.server's required method name
        if self.path.split("?", 1)[0] == "/graph.json":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(self._graph_bytes)))
            self.end_headers()
            self.wfile.write(self._graph_bytes)
            return
        super().do_GET()

    def log_message(self, *args) -> None:  # keep the console quiet
        pass


def serve(
    payload: dict, label: str = "faction graph", port: int = 8765, open_browser: bool = True
) -> None:
    """Serve the explorer for `payload` (a single graph dict, or a `{"factions": [...]}` wrapper)
    on localhost until interrupted. `label` is shown in the console line."""
    graph_bytes = json.dumps(payload, indent=2).encode("utf-8")
    handler = partial(_Handler, graph_bytes=graph_bytes)
    httpd = http.server.HTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"serving {label} at {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
