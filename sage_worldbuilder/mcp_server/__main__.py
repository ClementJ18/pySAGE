"""`python -m sage_worldbuilder.mcp_server [MAP | --bridge]`: serve the map tools over stdio.

Headless, the server edits its own copy of MAP. With `--bridge` it drives the running editor
instead (Tools > Allow Agent Connections), so the user sees every edit.
"""

from __future__ import annotations

import argparse

from sage_utils.cli import existing_file
from sage_utils.extras import require_extra


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sage-worldbuilder-mcp",
        description="Serve sage-worldbuilder's map tools to an agent over MCP (stdio).",
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument("map", nargs="?", type=existing_file, help="a .map to open at start")
    target.add_argument(
        "--bridge",
        action="store_true",
        help="drive the running editor (Tools > Allow Agent Connections) instead of a copy",
    )
    args = parser.parse_args(argv)
    require_extra("worldbuilder-mcp", "sage-worldbuilder-mcp", "mcp", "numpy")

    from sage_worldbuilder.mcp_server.server import build_server  # noqa: PLC0415 - needs mcp

    if args.bridge:
        from sage_worldbuilder.mcp_server.bridge import BridgeSession  # noqa: PLC0415

        build_server(BridgeSession()).run("stdio")
        return 0

    from sage_worldbuilder.mcp_server.tools import WorldBuilderSession  # noqa: PLC0415

    session = WorldBuilderSession()
    if args.map is not None:
        session.open_map(str(args.map))
    build_server(session).run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
