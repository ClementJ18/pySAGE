"""An MCP server that lets an agent read and edit maps.

`tools` is the Qt-free, SDK-free tool layer over a `MapDocument`; `server` exposes it over stdio
(`python -m sage_worldbuilder.mcp_server`, needs the `worldbuilder-mcp` extra). The names below
load on first use, so the entry point can check for that extra before numpy is imported.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sage_worldbuilder.mcp_server.tools import ToolError, WorldBuilderSession

__all__ = ["ToolError", "WorldBuilderSession"]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from sage_worldbuilder.mcp_server import tools  # noqa: PLC0415 - needs numpy

    value = getattr(tools, name)
    globals()[name] = value
    return value
