"""The link between the MCP server and a running editor: one JSON object per line over a
localhost socket.

The editor listens only while the user allows agent connections. It then writes the port and a
random token to a connection file in its settings folder and removes the file when it stops; the
server reads it to connect, and every request must carry the token, so a process that cannot read
the user's settings cannot drive the editor.

A request is `{"id", "token", "method", "kwargs"}` and its answer `{"id", "result"}` or
`{"id", "error", "tool_error"}`. Only the session methods in `TOOLS` are dispatched.
"""

from __future__ import annotations

import hmac
import inspect
import json
import socket
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sage_utils.config import read_json, user_file
from sage_worldbuilder.mcp_server.tools import TOOLS, ToolError, WorldBuilderSession

__all__ = [
    "BridgeClient",
    "BridgeSession",
    "Connection",
    "connection_file",
    "dispatch",
    "read_connection",
]

# The editor's settings folder (`sage_worldbuilder.settings.APP`) and the file in it.
_APP = "sage_worldbuilder"
_FILE = "mcp_bridge.json"
HOST = "127.0.0.1"
# The longest a call may take; opening a large map is the slowest.
TIMEOUT_SECONDS = 120.0

Connection = tuple[int, str]


def connection_file() -> Path:
    return user_file(_APP, _FILE)


def read_connection() -> Connection:
    """The listening editor's port and token."""
    data = read_json(_APP, _FILE, None)
    if not isinstance(data, dict) or not isinstance(data.get("port"), int):
        raise ToolError(
            "the editor is not accepting agent connections: open the map editor (WorldbuilderV2) "
            "and turn on Tools > Allow Agent Connections"
        )
    return data["port"], str(data.get("token", ""))


def _answer(request_id: object, **fields: Any) -> bytes:
    return json.dumps({"id": request_id, **fields}).encode() + b"\n"


def dispatch(session: WorldBuilderSession, token: str, line: bytes) -> bytes:
    """Carry out one request line against `session` and return the answer line. Never raises:
    a failure of any kind is an error answer, so a bad request cannot take the editor down."""
    try:
        request = json.loads(line)
    except ValueError:
        return _answer(None, error="the request is not JSON", tool_error=False)
    if not isinstance(request, dict):
        return _answer(None, error="the request is not an object", tool_error=False)
    request_id = request.get("id")
    if not hmac.compare_digest(str(request.get("token", "")), token):
        return _answer(request_id, error="bad token", tool_error=False)
    method = request.get("method")
    kwargs = request.get("kwargs") or {}
    if method not in TOOLS or not isinstance(kwargs, dict):
        return _answer(request_id, error=f"unknown tool {method!r}", tool_error=False)
    try:
        result = getattr(session, method)(**kwargs)
    except ToolError as error:
        return _answer(request_id, error=str(error), tool_error=True)
    except Exception as error:  # noqa: BLE001 - reported to the agent, the editor keeps running
        return _answer(request_id, error=f"{type(error).__name__}: {error}", tool_error=False)
    return _answer(request_id, result=result)


class BridgeClient:
    """A connection to the editor, made on first use and again once after it drops."""

    def __init__(self, connect: Callable[[], Connection] = read_connection) -> None:
        self._connect = connect
        self._lock = threading.Lock()
        self._socket: socket.socket | None = None
        self._reader: Any = None
        self._token = ""
        self._next_id = 0

    def close(self) -> None:
        if self._socket is not None:
            self._reader.close()
            self._socket.close()
        self._socket = self._reader = None

    def _open(self) -> None:
        port, self._token = self._connect()
        try:
            self._socket = socket.create_connection((HOST, port), timeout=TIMEOUT_SECONDS)
        except OSError as error:
            raise ToolError(f"cannot reach the editor on port {port}: {error}") from error
        self._reader = self._socket.makefile("rb")

    def _exchange(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._socket is None:
            self._open()
        assert self._socket is not None
        self._socket.sendall(json.dumps({**payload, "token": self._token}).encode() + b"\n")
        line = self._reader.readline()
        if not line:
            raise ConnectionError("the editor closed the connection")
        return json.loads(line)

    def call(self, method: str, kwargs: dict[str, Any]) -> Any:
        with self._lock:
            self._next_id += 1
            payload = {"id": self._next_id, "method": method, "kwargs": kwargs}
            try:
                answer = self._exchange(payload)
            except (ConnectionError, OSError):
                # The editor restarted or stopped listening: reconnect once, from a fresh file.
                self.close()
                try:
                    answer = self._exchange(payload)
                except (ConnectionError, OSError) as error:
                    self.close()
                    raise ToolError(f"lost the connection to the editor: {error}") from error
        if "error" in answer:
            raise ToolError(answer["error"])
        return answer.get("result")


class BridgeSession:
    """Stands in for a `WorldBuilderSession`, forwarding each tool to the editor by name."""

    def __init__(self, client: BridgeClient | None = None) -> None:
        self.client = client or BridgeClient()

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if name not in TOOLS:
            raise AttributeError(name)
        signature = inspect.signature(getattr(WorldBuilderSession, name))

        def forward(*args: Any, **kwargs: Any) -> Any:
            bound = signature.bind(None, *args, **kwargs)
            arguments = dict(bound.arguments)
            arguments.pop("self")
            return self.client.call(name, arguments)

        return forward
