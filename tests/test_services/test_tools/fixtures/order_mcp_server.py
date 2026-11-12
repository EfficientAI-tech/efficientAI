"""Tiny stdio MCP server used by the MCP provider tests."""

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

server = FastMCP("orders")


@server.tool(annotations=ToolAnnotations(readOnlyHint=True))
def lookup_order(order_id: str) -> str:
    """Look up an order's shipping status."""
    if order_id == "missing":
        raise ValueError("order not found")
    return f"Order {order_id}: shipped on 2026-10-01"


@server.tool()
def send_message(channel: str, text: str) -> str:
    """Post a message to a channel."""
    return f"posted to {channel}"


if __name__ == "__main__":
    server.run()
