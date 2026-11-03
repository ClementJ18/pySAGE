"""The MCP bridge's protocol without Qt: what `dispatch` refuses, and the client's round trip and
reconnect against a plain socket server standing in for the editor."""

import json
import shutil
import socket
import socketserver
import threading
from pathlib import Path

import pytest

from sage_worldbuilder.mcp_server import ToolError, WorldBuilderSession
from sage_worldbuilder.mcp_server.bridge import (
    BridgeClient,
    BridgeSession,
    dispatch,
    read_connection,
)

FIXTURE = (
    Path(__file__).parents[1] / "sage_map" / "fixtures" / "maps" / "map edain ford of bruinen.map"
)
TOKEN = "secret"


@pytest.fixture
def session(tmp_path):
    copy = tmp_path / "ford.map"
    shutil.copy(FIXTURE, copy)
    session = WorldBuilderSession()
    session.open_map(str(copy))
    return session


def ask(session, **request):
    return json.loads(dispatch(session, TOKEN, json.dumps({"token": TOKEN, **request}).encode()))


def test_dispatch_answers_a_tool_call(session):
    answer = ask(session, id=7, method="list_objects", kwargs={"limit": 1})
    assert answer["id"] == 7
    assert answer["result"]["total"] > 0


def test_dispatch_refuses_a_bad_token_and_anything_but_a_tool(session):
    bad = json.loads(dispatch(session, TOKEN, b'{"id": 1, "token": "nope", "method": "undo"}'))
    assert bad["error"] == "bad token"
    for method in ("_doc", "document", "__init__", "_find"):
        assert "unknown tool" in ask(session, id=2, method=method)["error"]
    assert ask(session, id=3, method="list_objects", kwargs=[1])["error"].startswith("unknown")
    assert json.loads(dispatch(session, TOKEN, b"not json"))["error"] == "the request is not JSON"


def test_dispatch_separates_tool_errors_from_failures(session):
    missing = ask(session, id=1, method="get_object", kwargs={"object_id": "nope"})
    assert missing["tool_error"] is True
    wrong = ask(session, id=2, method="get_object", kwargs={"no_such_argument": 1})
    assert wrong["tool_error"] is False
    assert wrong["error"].startswith("TypeError")


class _Editor(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(session):
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            for line in self.rfile:
                self.wfile.write(dispatch(session, TOKEN, line))

    server = _Editor(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_the_client_forwards_positional_and_keyword_arguments(session):
    server = serve(session)
    try:
        port = server.server_address[1]
        remote = BridgeSession(BridgeClient(lambda: (port, TOKEN)))
        placed = remote.place_object("TestTree", 100.0, 120.0, angle=30.0)
        assert session.get_object(placed["id"])["angle"] == 30.0
        assert remote.list_objects("TestTree", None, False, 0, 5)["total"] >= 1
        with pytest.raises(ToolError, match="no object"):
            remote.get_object("nope")
        with pytest.raises(AttributeError):
            remote._doc  # noqa: B018 - only tools forward
        remote.client.close()
    finally:
        server.shutdown()
        server.server_close()


def test_the_client_reconnects_once_after_the_editor_drops(session):
    server = serve(session)
    try:
        port = server.server_address[1]
        client = BridgeClient(lambda: (port, TOKEN))
        assert client.call("map_info", {})["title"] == "ford"
        assert client._socket is not None
        client._socket.shutdown(socket.SHUT_RDWR)  # as if the editor had gone away
        assert client.call("map_info", {})["title"] == "ford"
        client.close()
    finally:
        server.shutdown()
        server.server_close()


def test_no_connection_file_says_how_to_turn_the_bridge_on(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    with pytest.raises(ToolError, match="Allow Agent Connections"):
        read_connection()
