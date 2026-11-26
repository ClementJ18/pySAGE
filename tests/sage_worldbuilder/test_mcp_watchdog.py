"""The MCP server's client watch: which ancestor counts as the client."""

from sage_worldbuilder.mcp_server.watchdog import client_pid

# client (10) -> shim (20) -> venv redirector (30) -> server python (40)
TABLE = {
    10: (1, "claude.exe"),
    20: (10, "sage-worldbuilder-mcp.exe"),
    30: (20, "python.exe"),
    40: (30, "python.exe"),
}


def test_the_client_is_the_first_ancestor_past_every_launcher():
    assert client_pid(TABLE, 30, lambda pid, name: pid in (20, 30)) == 10


def test_a_direct_parent_that_is_no_launcher_is_the_client():
    assert client_pid(TABLE, 10, lambda pid, name: False) == 10


def test_a_parent_cycle_or_a_missing_ancestor_ends_the_walk():
    cyclic = {1: (2, "a.exe"), 2: (1, "a.exe")}
    assert client_pid(cyclic, 1, lambda pid, name: True) in (1, 2)
    assert client_pid(TABLE, 20, lambda pid, name: True) == 1
