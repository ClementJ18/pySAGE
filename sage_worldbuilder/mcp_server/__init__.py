"""An MCP server that lets an agent read and edit maps.

`tools` is the Qt-free, SDK-free tool layer over a `MapDocument`; `server` exposes it over stdio
(`python -m sage_worldbuilder.mcp_server`, needs the `mcp` extra).
"""

from sage_worldbuilder.mcp_server.tools import ToolError, WorldBuilderSession

__all__ = ["ToolError", "WorldBuilderSession"]
