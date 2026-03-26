"""Entry point: `python -m tplink_sg1016_mcp` or `uv run tplink-sg1016-mcp`."""

from .server import mcp

mcp.run()
